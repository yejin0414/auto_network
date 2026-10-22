"""역할별 읽기 전용 점검 명령.

여러 명령이 적힌 항목은 앞의 명령이 '미지원'으로 거부되면 다음 명령을 시도합니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CommandSpec:
    id: str
    label: str
    commands: tuple[str, ...]
    optional: bool = False          # 장비별 제공 여부가 다른 보조 명령; 실패/해석 불가는 판정기에서 별도 처리
    cluster: bool = False           # 클러스터 대표 WLC 1대에서만 실행
    timeout: int = 0                # 0이면 기본값 사용
    expect: str = ""                # 출력에 이 패턴이 없으면 다음 대체 명령을 시도(정규식)


BB_COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("version", "버전·가동시간", ("display version",)),
    CommandSpec("cpu", "CPU", ("show cpu summary", "display cpu-usage summary", "display cpu-usage"),
                expect=r"\d+(?:\.\d+)?\s*%"),
    CommandSpec("memory", "메모리", ("show memory summary", "display memory summary", "display memory"),
                expect=r"(?i)free"),
    CommandSpec("device", "슬롯/IRF 멤버", ("display device",), optional=True),
    CommandSpec("power", "전원", ("display power",), optional=True),
    CommandSpec("fan", "팬", ("display fan",), optional=True),
    CommandSpec("interface", "인터페이스", ("display interface brief",), timeout=45),
    CommandSpec("lagg", "LACP(링크 집계)", ("display link-aggregation summary",), optional=True),
    CommandSpec("ospf", "OSPF 인접", ("display ospf peer",), optional=True),
    CommandSpec("vrrp", "VRRP", ("display vrrp", "show vrrp"), optional=True),
    CommandSpec("log", "로그(최근순)", ("show logbuffer reverse", "display logbuffer reverse"), optional=True, timeout=90),
)

CTRL_CPU = CommandSpec("cpu", "CPU", ("show cpu", "show cpuload"), expect=r"(?i)user\s*[:=]?\s*\d")
CTRL_MEM = CommandSpec("memory", "메모리", ("show memory",), expect=r"(?i)used")

MM_COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("version", "버전·가동시간", ("show version",)),
    CTRL_CPU,
    CTRL_MEM,
    CommandSpec("switches", "관리 컨트롤러 상태", ("show switches",), timeout=45),
)

WLC_COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("version", "버전·가동시간", ("show version",)),
    CTRL_CPU,
    CTRL_MEM,
)

CLUSTER_COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("membership", "클러스터 멤버십", ("show lc-cluster group-membership",), cluster=True),
    CommandSpec("load", "Client 분배", ("show lc-cluster load distribution client",), cluster=True),
)

ROLE_COMMANDS = {"BB": BB_COMMANDS, "MM": MM_COMMANDS, "WLC": WLC_COMMANDS}
ROLE_DEVICE_TYPE = {"BB": "hp_comware", "MM": "aruba_os", "WLC": "aruba_os"}
ROLE_LABEL = {"BB": "백본", "MM": "Mobility Master", "WLC": "WLC"}


def commands_for(role: str, extra: list[str] | None = None) -> list[CommandSpec]:
    specs = list(ROLE_COMMANDS[role])
    for i, cmd in enumerate(extra or []):
        cmd = cmd.strip()
        if cmd:
            reason = check_console_command(cmd)
            if reason:
                raise ValueError(f"추가 명령 {i + 1}: {reason}")
            specs.append(CommandSpec(f"extra{i + 1}", cmd, (cmd,), optional=True))
    return specs


# ------------------------------------------------------------------ 직접 확인(콘솔) 안전 검사

ALLOWED_PREFIXES = ("show ", "display ")
BLOCKED_WORDS = {
    "reload", "reboot", "reset", "delete", "erase", "format", "write", "save", "copy", "move",
    "rename", "configure", "config", "system-view", "undo", "debug", "debugging", "clear",
    "shutdown", "tech-support", "boot", "upgrade", "install", "commit", "apply", "terminal",
    "ping", "traceroute", "tracert", "telnet", "ssh", "start", "restart", "exit", "quit",
}


def check_console_command(command: str) -> str | None:
    """허용되지 않으면 이유 문자열, 허용되면 None."""
    cmd = " ".join(command.strip().split())
    if not cmd:
        return "명령을 입력하세요."
    if len(cmd) > 200:
        return "명령이 너무 깁니다(최대 200자)."
    if any(not ch.isprintable() for ch in command):
        return "제어 문자가 포함된 명령은 실행할 수 없습니다."
    if any(ch in command for ch in ";`$&><"):
        return "여러 명령을 한 번에 실행할 수 없습니다."
    low = cmd.lower() + " "
    if not low.startswith(ALLOWED_PREFIXES):
        return "조회 명령(show / display)만 실행할 수 있습니다."
    words = set(low.replace("|", " ").split())
    hit = words & BLOCKED_WORDS
    if hit:
        return f"안전을 위해 '{sorted(hit)[0]}'가 포함된 명령은 실행하지 않습니다."
    for part in low.split("|")[1:]:
        tokens = part.split()
        if not tokens or tokens[0] not in ("include", "exclude", "begin", "count"):
            return "파이프에는 조회 필터(include / exclude / begin / count)만 사용할 수 있습니다."
    return None
