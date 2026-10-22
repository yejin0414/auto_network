"""접속 계정 보관.

- 기본: 프로그램 메모리에만 보관(종료하면 사라짐)
- 선택: Windows 자격 증명 관리자(keyring)에 저장해 재시작 후에도 자동 점검 유지
비밀번호는 설정 파일, DB, 로그, 보고서 어디에도 쓰지 않습니다.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass

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


class CredentialStore:
    def __init__(self, *, persistent: bool = True) -> None:
        # Demo/tests must never discover or mutate the user's OS credential store.
        self.persistent = persistent
        self._lock = threading.Lock()
        self._mem: dict[str, Credential] = {}
        self._remembered: set[str] = set()

    @property
    def keyring_available(self) -> bool:
        return self.persistent and _keyring() is not None

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
                raw = None
            if raw:
                try:
                    d = json.loads(raw)
                    with self._lock:
                        self._mem[SHARED] = Credential(d["u"], d["p"], "")
                        self._remembered.add(SHARED)
                    if p != SHARED:
                        self.set(SHARED, self._mem[SHARED], remember=True)
                except (ValueError, KeyError):
                    pass

    def set(self, profile: str, cred: Credential, remember: bool) -> str | None:
        profile = _p(profile)
        cred = Credential(cred.username, cred.password, "")  # enable 비밀번호는 쓰지 않음
        with self._lock:
            self._mem[profile] = cred
        kr = _keyring() if self.persistent else None
        if remember:
            if kr is None:
                return "이 PC에서는 자격 증명 관리자를 사용할 수 없어 이번 실행 동안만 기억합니다."
            try:
                kr.set_password(SERVICE, profile, json.dumps({"u": cred.username, "p": cred.password, "s": cred.secret}))
                with self._lock:
                    self._remembered.add(profile)
            except Exception as exc:  # pragma: no cover
                return f"자격 증명 관리자 저장 실패: {type(exc).__name__}"
        else:
            self.forget_saved(profile)
        return None

    def forget_saved(self, profile: str) -> None:
        profile = _p(profile)
        kr = _keyring() if self.persistent else None
        with self._lock:
            self._remembered.discard(profile)
        if kr is not None:
            try:
                kr.delete_password(SERVICE, profile)
            except Exception:
                pass

    def clear(self, profile: str) -> None:
        profile = _p(profile)
        kr = _keyring() if self.persistent else None
        if kr is not None:
            for old in LEGACY:
                try:
                    kr.delete_password(SERVICE, old)
                except Exception:
                    pass
        with self._lock:
            self._mem.pop(profile, None)
        self.forget_saved(profile)

    def get(self, profile: str = SHARED) -> Credential | None:
        with self._lock:
            return self._mem.get(_p(profile))

    def status(self) -> dict[str, dict]:
        with self._lock:
            return {
                p: {"set": True, "username": c.username, "remembered": p in self._remembered}
                for p, c in self._mem.items()
            }
