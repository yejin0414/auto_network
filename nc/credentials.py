"""접속 계정 보관.

- 기본: 프로그램 메모리에만 보관(종료하면 사라짐)
- 선택: Windows 자격 증명 관리자(keyring)에 저장해 재시작 후에도 자동 점검 유지
비밀번호는 설정 파일, DB, 로그, 보고서 어디에도 쓰지 않습니다.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Callable, Any

SERVICE = "AutoNetwork.NetcheckCenter"


@dataclass
class Credential:
    username: str
    password: str
    secret: str = ""


_KR = None
_KR_CHECKED = False


def _keyring():
    """Windows 자격 증명 관리자 백엔드. EXE에서는 자동 탐색이 실패할 수 있어 직접 지정합니다."""
    global _KR, _KR_CHECKED
    if _KR_CHECKED:
        return _KR
    _KR_CHECKED = True
    try:
        import sys

        import keyring  # type: ignore

        if sys.platform == "win32":
            from keyring.backends.Windows import WinVaultKeyring  # type: ignore

            keyring.set_keyring(WinVaultKeyring())
        backend = keyring.get_keyring()
        name = type(backend).__module__ + "." + type(backend).__name__
        if "fail" in name.lower() or "null" in name.lower():
            return None
        _KR = keyring
    except Exception:
        _KR = None
    return _KR


SHARED = "shared"
LEGACY = ("backbone", "aruba")  # v1.4.0 이하: 백본·Aruba 계정을 따로 저장했음


def _p(profile: str) -> str:
    """계정은 하나(공통)만 씁니다. 예전 이름(backbone/aruba)도 같은 계정으로 봅니다."""
    return SHARED


class CredentialError(RuntimeError):
    def __init__(self, message: str, *, rollback_failed: bool = False) -> None:
        super().__init__(message)
        self.rollback_failed = rollback_failed


class CredentialStore:
    def __init__(self, *, persistent: bool = True) -> None:
        # Demo/tests must never discover or mutate the user's OS credential store.
        self.persistent = persistent
        self._lock = threading.RLock()
        self._mem: dict[str, Credential] = {}
        self._remembered: set[str] = set()
        self._storage_uncertain = False

    @property
    def keyring_available(self) -> bool:
        return self.persistent and _keyring() is not None

    @property
    def storage_uncertain(self) -> bool:
        with self._lock:
            return self._storage_uncertain

    def load_saved(self, profiles: list[str]) -> None:
        kr = _keyring() if self.persistent else None
        if kr is None:
            return
        # 공통 계정이 없으면 예전 백본 계정 → Aruba 계정 순으로 옮겨 씀
        for p in [SHARED, *LEGACY]:
            if self.get(SHARED):
                break
            try:
                raw = kr.get_password(SERVICE, p)
            except Exception:
                # A failed read does not prove absence. Do not replace a
                # possibly existing account with a lower-priority profile.
                return
            if raw:
                try:
                    d = json.loads(raw)
                    with self._lock:
                        self._mem[SHARED] = Credential(d["u"], d["p"], "")
                        self._remembered.add(SHARED)
                    if p != SHARED:
                        self.apply([{"profile": SHARED, "username": d["u"], "password": d["p"],
                                     "remember": True}], force=True)
                except (ValueError, KeyError, TypeError, CredentialError):
                    pass

    def _prepare(self, changes: list[dict]) -> tuple[Credential | None, bool, bool]:
        """Validate the entire request before reading or writing the OS store."""
        if not isinstance(changes, list) or len(changes) > 1:
            raise ValueError("공통 계정 변경은 한 번에 하나만 전달하세요.")
        old = self._mem.get(SHARED)
        remembered = SHARED in self._remembered
        if not changes:
            return old, remembered, False
        change = changes[0]
        if not isinstance(change, dict) or change.get("profile") not in (SHARED, *LEGACY):
            raise ValueError("알 수 없는 계정 종류입니다.")
        for key in ("clear", "remember"):
            if key in change and not isinstance(change[key], bool):
                raise ValueError(f"계정 {key} 값은 true 또는 false여야 합니다.")
        if change.get("clear"):
            return None, False, True
        username = change.get("username", old.username if old else "")
        password = change.get("password", "")
        if not isinstance(username, str) or not isinstance(password, str):
            raise ValueError("아이디와 비밀번호는 문자열이어야 합니다.")
        username = username.strip()
        if not username:
            raise ValueError("아이디를 입력하세요.")
        if not password:
            if old is None or old.username != username:
                raise ValueError("새 계정이나 아이디를 변경할 때는 비밀번호도 입력하세요.")
            password = old.password
        cred = Credential(username, password)
        remember = change.get("remember", remembered)
        return cred, remember, cred != old or remember != remembered or self._storage_uncertain

    def apply(self, changes: list[dict], commit: Callable[[], Any] | None = None, *, force: bool = False) -> Any:
        """Serialize account changes with an optional atomic config-file commit.

        Keyring has no transactions: retain its old values for compensation if
        any write or the config commit fails. Never publish partial memory state.
        """
        with self._lock:
            cred, remember, changed = self._prepare(changes)
            if not changed and not force:
                return commit() if commit else None
            kr = _keyring() if self.persistent else None
            if kr is None and (remember or self._remembered or self._storage_uncertain):
                raise CredentialError("자격 증명 관리자를 사용할 수 없습니다. PC 저장 선택을 해제하거나 저장소를 확인한 뒤 다시 시도하세요.")
            before, touched = {}, []
            if kr is not None:
                try:
                    before = {p: kr.get_password(SERVICE, p) for p in (SHARED, *LEGACY)}
                except Exception:
                    raise CredentialError("PC에 저장된 계정을 확인하지 못했습니다. 변경하지 않았습니다.") from None
            committing = False
            try:
                if kr is not None:
                    desired = json.dumps({"u": cred.username, "p": cred.password, "s": ""}) if cred and remember else None
                    for profile in (SHARED, *LEGACY):
                        value = desired if profile == SHARED else None
                        if before[profile] == value:
                            continue
                        # A backend can mutate and then raise, so include even
                        # the attempted operation in compensation.
                        touched.append(profile)
                        if value is None:
                            kr.delete_password(SERVICE, profile)
                        else:
                            kr.set_password(SERVICE, profile, value)
                committing = True
                result = commit() if commit else None
            except Exception as exc:
                restored = True
                for profile in reversed(touched):
                    try:
                        if before[profile] is not None:
                            kr.set_password(SERVICE, profile, before[profile])
                        elif kr.get_password(SERVICE, profile) is not None:
                            kr.delete_password(SERVICE, profile)
                    except Exception:
                        restored = False
                if not restored:
                    self._storage_uncertain = True
                    raise CredentialError("저장 실패 후 PC 계정 복구도 실패했습니다. PC 저장 상태를 확인할 수 없습니다. 계정 지우기를 완료한 뒤 다시 저장하세요.", rollback_failed=True) from None
                if committing and isinstance(exc, OSError):
                    raise
                raise CredentialError("계정 또는 설정을 저장하지 못했습니다. 기존 상태로 복구했습니다.") from None
            if cred is None:
                self._mem.pop(SHARED, None)
            else:
                self._mem[SHARED] = cred
            self._remembered = {SHARED} if cred and remember else set()
            self._storage_uncertain = False
            return result

    def set(self, profile: str, cred: Credential, remember: bool) -> str | None:
        # Preserve the original note-returning API for CLI/demo callers.
        try:
            self.apply([{"profile": profile, "username": cred.username, "password": cred.password,
                         "remember": remember}])
        except CredentialError as exc:
            return str(exc)
        return None

    def forget_saved(self, profile: str) -> None:
        with self._lock:
            cred = self._mem.get(_p(profile))
            change = {"profile": profile, "remember": False} if cred else {"profile": profile, "clear": True}
            self.apply([change])

    def clear(self, profile: str) -> None:
        self.apply([{"profile": profile, "clear": True}])

    def get(self, profile: str = SHARED) -> Credential | None:
        with self._lock:
            cred = self._mem.get(_p(profile))
            return Credential(cred.username, cred.password, cred.secret) if cred else None

    def status(self) -> dict[str, dict]:
        with self._lock:
            return {
                p: {"set": True, "username": c.username,
                    "remembered": p in self._remembered and not self._storage_uncertain,
                    "storage_uncertain": self._storage_uncertain}
                for p, c in self._mem.items()
            }
