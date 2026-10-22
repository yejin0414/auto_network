"""설정 파일(config/config.json) 읽기·검증·저장. 비밀번호는 여기에 저장하지 않습니다."""

from __future__ import annotations

import copy
import ipaddress
import json
import math
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from .commands import check_console_command

ROLES = ("BB", "MM", "WLC")
# 백본·MM·WLC 모두 같은 계정 하나로 접속합니다.
CREDENTIAL_PROFILES = {"shared": "접속 계정 (백본·MM·WLC 공통)"}

DEFAULTS: dict[str, Any] = {
    "site_name": "무선망 통합 점검",
    "devices": [],
    "schedule": {"enabled": False, "interval_minutes": 60, "align_to_clock": True, "background": False},
    "thresholds": {
        "cpu_warn": 50, "cpu_crit": 70,
        "mem_warn": 60, "mem_crit": 70,
        "client_ratio_pct": 25, "client_min_total": 50,
    },
    # 백본(BB)과 컨트롤러(MM·WLC)는 대기 시간을 따로 씁니다.
    "ssh": {"bb_connect_timeout": 120, "bb_command_timeout": 120,
            "ctrl_connect_timeout": 60, "ctrl_command_timeout": 60, "parallel": 6, "retries": 1},
    "extra_commands": {"BB": [], "MM": [], "WLC": []},
    "retention_days": 30,
    # 점검이 끝날 때마다: 엑셀 보고서 자동 저장, Windows 알림(화면 오른쪽 아래)
    "report": {"excel_auto": True, "folder": "", "notify": True},
    "server": {"host": "127.0.0.1", "port": 8875},
}


class ConfigError(ValueError):
    pass


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def ssh_for(device: dict[str, Any], ssh: dict[str, Any]) -> dict[str, Any]:
    """장비 종류에 맞는 대기 시간(백본 / 컨트롤러)을 connect_timeout·command_timeout으로 돌려줍니다."""
    pre = "bb" if device.get("role") == "BB" else "ctrl"
    out = dict(ssh)
    out["connect_timeout"] = int(ssh.get(f"{pre}_connect_timeout", ssh.get("connect_timeout", 60)))
    out["command_timeout"] = int(ssh.get(f"{pre}_command_timeout", ssh.get("command_timeout", 60)))
    return out


def normalize_device(raw: dict[str, Any], index: int) -> dict[str, Any]:
    role = str(raw.get("role", "")).upper()
    if role not in ROLES:
        raise ConfigError(f"{index + 1}번째 장비: 역할은 BB / MM / WLC 중 하나여야 합니다.")
    host = str(raw.get("host", "")).strip()
    if not host:
        raise ConfigError(f"{index + 1}번째 장비: 접속 주소(IP)를 입력하세요.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r"[A-Za-z0-9.\-]{1,253}", host):
            raise ConfigError(f"{index + 1}번째 장비: '{host}'는 올바른 IP나 호스트명이 아닙니다.")
    name = str(raw.get("name", "")).strip() or host
    dev_id = str(raw.get("id", "")).strip() or re.sub(r"[^a-z0-9]+", "-", f"{role}-{name}".lower()).strip("-")
    device_type = str(raw.get("device_type") or "").strip().lower()
    if device_type and not re.fullmatch(r"[a-z0-9_]{2,40}", device_type):
        raise ConfigError(f"{index + 1}번째 장비: 장비 종류(device_type) '{device_type}'가 올바르지 않습니다.")
    protocol = str(raw.get("protocol", "telnet" if device_type.endswith("_telnet") else "ssh")).lower()
    if protocol not in ("ssh", "telnet"):
        protocol = "ssh"
    if protocol == "telnet" and role != "BB":
        raise ConfigError(f"{index + 1}번째 장비: Telnet 접속은 백본(Comware)에서만 지원합니다.")
    try:
        port = int(raw.get("port", 23 if protocol == "telnet" else 22))
    except (TypeError, ValueError):
        raise ConfigError(f"{name}: 포트는 숫자여야 합니다.")
    if not 1 <= port <= 65535:
        raise ConfigError(f"{name}: 포트는 1~65535 범위여야 합니다.")
    cred = "shared"
    return {
        "id": dev_id[:40],
        "name": name[:40],
        "role": role,
        "host": host,
        "port": port,
        "protocol": protocol,
        "device_type": device_type,
        "enabled": bool(raw.get("enabled", True)),
        "credential": cred,
        "cluster_primary": bool(raw.get("cluster_primary", False)) if role == "WLC" else False,
        # WLC 클러스터 이름(예: IN, OUT). 모델이 다른 컨트롤러는 클러스터를 따로 둡니다.
        "cluster": re.sub(r"\s+", " ", str(raw.get("cluster") or "")).strip()[:20] if role == "WLC" else "",
        "group": str(raw.get("group", "")).strip()[:30],
    }


def validate(cfg: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(cfg, dict):
        raise ConfigError("설정은 JSON 객체여야 합니다.")
    def reject_secrets(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in {"password", "secret", "credentials", "api_token", "access_token", "token"}:
                    raise ConfigError("계정과 비밀번호·토큰은 설정 파일에 포함할 수 없습니다. 접속 계정 항목을 사용하세요.")
                reject_secrets(item)
        elif isinstance(value, list):
            for item in value:
                reject_secrets(item)
    reject_secrets(cfg)
    for key in ("schedule", "thresholds", "ssh", "extra_commands", "report", "server"):
        if key in cfg and not isinstance(cfg[key], dict):
            raise ConfigError(f"{key} 설정은 JSON 객체여야 합니다.")
    if "devices" in cfg and not isinstance(cfg["devices"], list):
        raise ConfigError("devices 설정은 장비 목록이어야 합니다.")
    if any(not isinstance(d, dict) for d in cfg.get("devices", [])):
        raise ConfigError("장비 설정은 JSON 객체여야 합니다.")
    raw_ssh = dict((cfg or {}).get("ssh") or {})
    cfg = _merge(DEFAULTS, cfg)
    devices = [normalize_device(d, i) for i, d in enumerate(cfg.get("devices") or [])]
    ids = [d["id"] for d in devices]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise ConfigError(f"장비 ID가 중복됩니다: {', '.join(sorted(dup))}")
    # 클러스터마다 대표 WLC는 1대만
    seen_primary: set[str] = set()
    for d in devices:
        if d["role"] == "WLC" and d["cluster_primary"]:
            if d["cluster"] in seen_primary:
                d["cluster_primary"] = False
            seen_primary.add(d["cluster"])
    cfg["devices"] = devices
    s = cfg["schedule"]
    for key in ("enabled", "align_to_clock", "background"):
        if not isinstance(s[key], bool):
            raise ConfigError(f"schedule.{key} 값은 true 또는 false여야 합니다.")
    try:
        s["interval_minutes"] = int(s.get("interval_minutes", 60))
    except (TypeError, ValueError):
        raise ConfigError("점검 주기는 분 단위 숫자여야 합니다.")
    if not 5 <= s["interval_minutes"] <= 1440:
        raise ConfigError("점검 주기는 5분~1440분(24시간) 사이로 설정하세요.")
    t = cfg["thresholds"]
    for k in DEFAULTS["thresholds"]:
        try:
            t[k] = float(t.get(k, DEFAULTS["thresholds"][k]))
        except (TypeError, ValueError):
            raise ConfigError(f"임계값 {k}는 숫자여야 합니다.")
        if not math.isfinite(t[k]) or t[k] < 0:
            raise ConfigError(f"임계값 {k}는 0 이상의 유한한 숫자여야 합니다.")
        if k != "client_min_total" and t[k] > 100:
            raise ConfigError(f"임계값 {k}는 0~100 범위여야 합니다.")
        if k == "client_min_total" and not t[k].is_integer():
            raise ConfigError("client_min_total은 0 이상의 정수여야 합니다.")
    if t["cpu_warn"] >= t["cpu_crit"] or t["mem_warn"] >= t["mem_crit"]:
        raise ConfigError("주의 임계값은 장애 임계값보다 작아야 합니다.")
    for role in ROLES:
        cmds = cfg["extra_commands"].get(role) or []
        if not isinstance(cmds, list) or any(not isinstance(c, str) for c in cmds):
            raise ConfigError(f"{role} 추가 명령은 문자열 목록이어야 합니다.")
        for command in cmds:
            if command.strip():
                error = check_console_command(command)
                if error:
                    raise ConfigError(f"{role} 추가 명령: {error}")
        cfg["extra_commands"][role] = [c.strip() for c in cmds if c.strip()][:10]
    cfg["retention_days"] = max(1, min(365, int(cfg.get("retention_days", 30))))
    rep = cfg["report"]
    rep["excel_auto"] = bool(rep.get("excel_auto", True))
    rep["notify"] = bool(rep.get("notify", True))
    rep["folder"] = str(rep.get("folder") or "").strip()[:260]
    ssh = cfg["ssh"]
    # 이전 버전(공통 connect_timeout/command_timeout) → 백본·컨트롤러 따로
    old_conn, old_cmd = ssh.pop("connect_timeout", None), ssh.pop("command_timeout", None)
    ssh.pop("timeouts_v2", None)
    if old_conn is not None and "ctrl_connect_timeout" not in raw_ssh:
        ssh["ctrl_connect_timeout"] = max(int(old_conn), 60)
        ssh["bb_connect_timeout"] = max(int(old_conn), 120)
    if old_cmd is not None and "ctrl_command_timeout" not in raw_ssh:
        ssh["ctrl_command_timeout"] = max(int(old_cmd), 60)
        ssh["bb_command_timeout"] = max(int(old_cmd), 120)
    try:
        for k in ("bb_connect_timeout", "bb_command_timeout", "ctrl_connect_timeout", "ctrl_command_timeout", "parallel", "retries"):
            ssh[k] = int(ssh.get(k, DEFAULTS["ssh"][k]))
    except (TypeError, ValueError):
        raise ConfigError("접속 대기 시간은 초 단위 숫자여야 합니다.")
    for k, label, lo, hi in (("bb_connect_timeout", "백본 접속 대기", 10, 600), ("bb_command_timeout", "백본 명령 응답 대기", 10, 600),
                             ("ctrl_connect_timeout", "컨트롤러 접속 대기", 10, 600), ("ctrl_command_timeout", "컨트롤러 명령 응답 대기", 10, 600)):
        if not lo <= ssh[k] <= hi:
            raise ConfigError(f"{label} 시간은 {lo}~{hi}초 사이로 설정하세요.")
    ssh["parallel"] = max(1, min(16, ssh["parallel"]))
    ssh["retries"] = max(0, min(3, ssh["retries"]))
    return cfg


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._cfg = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            example = self.path.with_name("config.example.json")
            raw = json.loads(example.read_text(encoding="utf-8")) if example.exists() else {}
            cfg = validate(raw)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            return cfg
        return validate(json.loads(self.path.read_text(encoding="utf-8-sig")))

    def get(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._cfg)

    def save(self, new_cfg: dict[str, Any]) -> dict[str, Any]:
        cfg = validate(new_cfg)
        text = json.dumps(cfg, ensure_ascii=False, indent=2, allow_nan=False)
        result = copy.deepcopy(cfg)
        with self._lock:
            tmp = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                                 prefix=self.path.name + ".", suffix=".tmp", delete=False) as file:
                    tmp = Path(file.name)
                    file.write(text)
                tmp.replace(self.path)
                tmp = None  # The commit succeeded; cleanup cannot undo it.
            finally:
                if tmp is not None:
                    try:
                        tmp.unlink(missing_ok=True)
                    except OSError:
                        pass  # Retain the original write/replace error.
            self._cfg = cfg
        return result
