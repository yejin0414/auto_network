"""장비 명령 출력 파서.

모든 파서는 예외를 던지지 않고, 해석에 실패하면 None 또는 빈 결과를 돌려줍니다.
'해석 실패'는 장비 장애가 아니라 '확인 불가'로 다뤄야 하기 때문입니다.
"""

from __future__ import annotations

import ipaddress
import math
import re
from typing import Any

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)?")
PAGER_RE = re.compile(r"(?:-{2,}\s*more\s*-{2,}|<-+\s*more\s*-+>|press any key to continue)", re.I)
IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
ERROR_LINE_RE = re.compile(
    r"^\s*(?:%\s*(?:unrecognized|invalid|incomplete|ambiguous|too many|wrong|unknown)|"
    r"invalid input|parse error|unknown command|% ?error)",
    re.I | re.M,
)


# --------------------------------------------------------------------------- 공통

def clean(text: str | bytes | None) -> str:
    if text is None:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = ANSI_RE.sub("", text)
    if "\b" in text:
        out: list[str] = []
        for ch in text:
            if ch == "\b":
                if out:
                    out.pop()
            else:
                out.append(ch)
        text = "".join(out)
    text = PAGER_RE.sub("", text)
    return "\n".join(line.rstrip() for line in text.split("\n"))


def looks_like_error(text: str) -> bool:
    """장비가 명령을 거부했는지(미지원 명령, 권한 없음 등)."""
    body = clean(text)
    if not body.strip():
        return False
    lines = [l for l in body.split("\n") if l.strip()]
    # 짧은 출력에서 오류 문구가 보이면 거부로 판단
    return bool(ERROR_LINE_RE.search(body)) and len(lines) <= 6


def valid_ip(value: str) -> str | None:
    m = IPV4_RE.search(value or "")
    if not m:
        return None
    try:
        return str(ipaddress.IPv4Address(m.group(0)))
    except ValueError:
        return None


def to_int(value: str) -> int | None:
    v = (value or "").strip().replace(",", "")
    return int(v) if v.isdigit() and len(v) < 19 else None


def _norm(label: str) -> str:
    return re.sub(r"[\s_\-()]+", "", label).casefold()


SEPARATOR_RE = re.compile(r"^[\s\-=+]+$")
PROMPT_RE = re.compile(r"^\s*(?:\([^)]*\)\s*(?:\[[^\]]*\]\s*)?[#>]|<[^>]+>|\[[^\]]+\]|[\w.\-]+\s*[#>])\s*$")


def parse_table(
    text: str,
    aliases: dict[str, tuple[str, ...]],
    required: tuple[str, ...],
) -> list[dict[str, str]]:
    """고정 폭 표를 해석합니다. 머리글 바로 아래 '----' 구분선이 있으면 그 폭을 우선 사용합니다."""
    lines = clean(text).split("\n")
    lookup = {_norm(a): canon for canon, names in aliases.items() for a in names}
    for idx, line in enumerate(lines):
        if not line.strip() or len(line) > 4000:
            continue
        segs = [(m.group(0), m.start()) for m in re.finditer(r"\S+(?: \S+)*", line)]
        mapped: list[tuple[str, int]] = []
        seen: set[str] = set()
        for label, start in segs:
            canon = lookup.get(_norm(label))
            if canon and canon not in seen:
                mapped.append((canon, start))
                seen.add(canon)
        if not set(required).issubset(seen):
            # 머리글 사이가 공백 1칸인 표(예: 'Type IPv4 Address    Priority Connection-Type STATUS')
            hits = []
            for canon, names in aliases.items():
                best = None
                for a in sorted(names, key=len, reverse=True):
                    m = re.search(r"(?<![A-Za-z0-9-])" + re.escape(a) + r"(?![A-Za-z0-9-])", line, re.I)
                    if m:
                        best = m.start()
                        break
                if best is not None:
                    hits.append((canon, best))
            if not set(required).issubset({c for c, _ in hits}):
                continue
            hits.sort(key=lambda x: x[1])
            mapped = hits
            segs = [(c, s) for c, s in hits]
            seen = {c for c, _ in hits}

        # 열 시작 위치: 구분선이 있으면 구분선 기준
        all_starts = [s for _, s in segs]
        body_start = idx + 1
        if body_start < len(lines) and SEPARATOR_RE.match(lines[body_start] or " ") and "-" in lines[body_start]:
            dash_starts = [m.start() for m in re.finditer(r"[-=]+", lines[body_start])]
            if len(dash_starts) >= len(segs):
                remap = {}
                for _, s in segs:
                    remap[s] = min(dash_starts, key=lambda d: abs(d - s))
                all_starts = [remap[s] for s in all_starts]
                mapped = [(c, remap[s]) for c, s in mapped]
            body_start += 1
        all_starts = sorted(set(all_starts))

        rows: list[dict[str, str]] = []
        for raw in lines[body_start:]:
            if not raw.strip() or SEPARATOR_RE.match(raw) or PROMPT_RE.match(raw):
                continue
            if re.match(r"^\s*(?:total|number of|entries|displayed)\b", raw, re.I):
                continue
            row: dict[str, str] = {}
            for canon, start in mapped:
                nxt = [s for s in all_starts if s > start]
                end = nxt[0] if nxt else len(raw)
                # 값이 다음 열로 넘쳐 들어간 경우 단어 경계까지 확장
                while end < len(raw) and raw[end - 1] != " " and raw[end] != " ":
                    end += 1
                b = start
                while 0 < b < len(raw) and raw[b - 1] != " " and raw[b] != " ":
                    b += 1
                row[canon] = raw[b:end].strip()
            row["_line"] = raw.strip()
            rows.append(row)
        return rows
    return []


# --------------------------------------------------------------------------- 공용 지표

UNIT_SECONDS = {"year": 31536000, "week": 604800, "day": 86400, "hour": 3600, "minute": 60, "min": 60, "second": 1, "sec": 1}


def parse_uptime(text: str) -> int | None:
    body = clean(text)
    m = re.search(r"uptime\s+is\s+([^\n]+)", body, re.I)
    if not m:
        return None
    total = 0
    found = False
    for num, unit in re.findall(r"(\d+)\s*(years?|weeks?|days?|hours?|minutes?|mins?|seconds?|secs?)", m.group(1), re.I):
        key = unit.lower().rstrip("s")
        total += int(num) * UNIT_SECONDS.get(key, 0)
        found = True
    return total if found else None


def parse_version(text: str) -> dict[str, str]:
    body = clean(text)
    info: dict[str, str] = {}
    m = re.search(r"MODEL:\s*([^)\s,]+)\)?,?\s*Version\s+([\w.\-]+)", body, re.I)
    if m:
        info["model"], info["version"] = m.group(1), m.group(2)
        return info
    m = re.search(r"Comware Software,\s*Version\s+([\d.]+)(?:,\s*(?:Release|ESS)\s+(\w+))?", body, re.I)
    if m:
        info["version"] = m.group(1) + (f" R{m.group(2)}" if m.group(2) else "")
    m = re.search(r"^\s*((?:HPE?|H3C)\s+.+?)\s+(?:Switch\s+)?uptime is", body, re.I | re.M)
    if m:
        info["model"] = m.group(1).strip()
    if "version" not in info:
        m = re.search(r"\bVersion\s+([\w.\-]+)", body)
        if m:
            info["version"] = m.group(1)
    return info


# --------------------------------------------------------------------------- CPU / 메모리

PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def parse_cpu_comware(text: str) -> dict[str, Any] | None:
    """show cpu summary / display cpu-usage summary / display cpu-usage
    → {'5s','1m','5m': 슬롯 중 최대값, 'slots': [{'slot','5s','1m','5m'}]}"""
    body = clean(text)
    slots: list[dict[str, Any]] = []
    in_table = False
    for line in body.split("\n"):
        low = line.lower()
        if re.search(r"5\s*sec", low) and re.search(r"1\s*min", low) and re.search(r"5\s*min", low):
            in_table = True  # 요약표 머리글: Slot CPU Last 5 sec Last 1 min Last 5 min
            continue
        if in_table:
            pcts = PCT_RE.findall(line)
            if len(pcts) >= 3:
                label = PCT_RE.sub("", line).split()
                slots.append({"slot": "/".join(t for t in label if t not in ("-",)) or str(len(slots) + 1),
                              "5s": float(pcts[-3]), "1m": float(pcts[-2]), "5m": float(pcts[-1])})
            elif line.strip() and not SEPARATOR_RE.match(line):
                in_table = bool(PCT_RE.search(line))
    if not slots:
        # 상세 형식: "Slot 1 CPU 0 CPU usage:" 아래 "6% in last 5 seconds"
        cur: dict[str, Any] | None = None
        labels = {"5s": r"5\s*sec(?:ond)?s?", "1m": r"1\s*min(?:ute)?s?", "5m": r"5\s*min(?:ute)?s?"}
        for line in body.split("\n"):
            m = re.search(r"slot\s+(\d+)(?:\s+cpu\s+(\d+))?", line, re.I)
            if m and "usage" in line.lower():
                cur = {"slot": m.group(1) + (f"/{m.group(2)}" if m.group(2) else "")}
                slots.append(cur)
                continue
            for key, lab in labels.items():
                v = re.search(rf"(\d+(?:\.\d+)?)\s*%\s*in\s+last\s+{lab}\b", line, re.I) or \
                    re.search(rf"\b{lab}\s*[:=]\s*(\d+(?:\.\d+)?)\s*%", line, re.I)
                if v:
                    if cur is None:
                        cur = {"slot": "1"}
                        slots.append(cur)
                    cur.setdefault(key, float(v.group(1)))
        slots = [x for x in slots if any(k in x for k in ("5s", "1m", "5m"))]
    if not slots:
        return None
    out: dict[str, Any] = {"slots": slots}
    for key in ("5s", "1m", "5m"):
        vals = [x[key] for x in slots if key in x]
        if vals:
            out[key] = max(vals)
    return out


def _num(tok: str) -> float | None:
    m = re.match(r"^(\d+(?:\.\d+)?)%?$", tok.replace(",", ""))
    value = float(m.group(1)) if m else None
    return value if value is not None and math.isfinite(value) else None


def parse_mem_comware(text: str) -> dict[str, Any] | None:
    """show memory summary / display memory summary / display memory
    → {'used_pct','free_ratio','total_kb','used_kb','free_kb', 'slots': [...]} (여유가 가장 적은 슬롯 기준)"""
    body = clean(text)
    slots: list[dict[str, Any]] = []
    header: list[str] | None = None
    cur_slot = ""
    for line in body.split("\n"):
        toks = line.split()
        if not toks:
            continue
        m = re.match(r"^\s*slot\s+(\d+)\s*:?\s*$", line, re.I)
        if m:
            cur_slot = m.group(1)
            continue
        names = [re.sub(r"[^a-z]", "", t.lower()) for t in toks]
        if "total" in names and "free" in names:
            header = names
            continue
        if header is None:
            continue
        if toks[0].lower().startswith("mem"):
            values, cols, slot = toks[1:], [h for h in header if h != "slot"], cur_slot or "1"
        elif header[0] == "slot" and re.match(r"^\d+(/\d+)*$", toks[0]):
            values, cols, slot = toks[1:], header[1:], toks[0]
        else:
            continue
        row = {c: _num(v) for c, v in zip(cols, values)}
        if row.get("total") is None or row.get("free") is None:
            continue
        total, free = row["total"], row["free"]
        used = row.get("used") if row.get("used") is not None else total - free
        if total <= 0 or not 0 <= free <= total or not 0 <= used <= total:
            continue
        ratio = row.get("freeratio")
        if ratio is None:
            ratio = round(free / total * 100, 1)
        if not 0 <= ratio <= 100:
            continue
        slots.append({"slot": slot, "total_kb": int(total), "used_kb": int(used), "free_kb": int(free), "free_ratio": ratio})
    if not slots:
        ratios = [float(v) for v in re.findall(r"free\s*ratio\s*[:=]?\s*(\d+(?:\.\d+)?)\s*%", body, re.I)
                  if 0 <= float(v) <= 100]
        if ratios:
            free = min(ratios)
            return {"free_ratio": free, "used_pct": round(100 - free, 1), "slots": []}
        m = re.search(r"Total\s+(\d+)\s+Used\s+(\d+)", body, re.I)
        if m and int(m.group(1)) > 0:
            t, u = int(m.group(1)), int(m.group(2))
            if u > t:
                return None
            r = round((t - u) / t * 100, 1)
            return {"free_ratio": r, "used_pct": round(100 - r, 1), "total_kb": t, "used_kb": u, "free_kb": t - u,
                    "slots": [{"slot": "1", "total_kb": t, "used_kb": u, "free_kb": t - u, "free_ratio": r}]}
        return None
    tight = min(slots, key=lambda x: x["free_ratio"] if x["free_ratio"] is not None else 101)
    return {"free_ratio": tight["free_ratio"], "used_pct": round(100 - tight["free_ratio"], 1),
            "total_kb": tight["total_kb"], "used_kb": tight["used_kb"], "free_kb": tight["free_kb"], "slots": slots}


def parse_cpu_aruba(text: str) -> dict[str, float] | None:
    """show cpu / show cpuload → user, system, idle (%)."""
    body = clean(text)
    def grab(name: str) -> float | None:
        m = re.search(rf"\b{name}\s*[:=]?\s*(\d+(?:\.\d+)?)\s*%", body, re.I)
        return float(m.group(1)) if m else None
    user, system, idle = grab("user"), grab("system"), grab("idle")
    if user is None or system is None:
        return None
    if idle is None:
        idle = round(max(0.0, 100 - user - system), 1)
    return {"user": user, "system": system, "idle": idle, "1m": round(100 - idle, 1)}


def parse_mem_aruba(text: str) -> dict[str, float] | None:
    """show memory → Memory (Kb): total: X, used: Y, free: Z."""
    body = clean(text)
    m = re.search(r"total\s*:?\s*(\d+)\s*,?\s*used\s*:?\s*(\d+)\s*,?\s*free\s*:?\s*(\d+)", body, re.I)
    if not m:
        return None
    total, used, free = (int(x) for x in m.groups())
    if total <= 0:
        return None
    pct = round(used / total * 100, 1)
    return {"total_kb": total, "used_kb": used, "free_kb": free, "used_pct": pct, "free_ratio": round(100 - pct, 1)}


LOG_LINE_RE = re.compile(r"^\s*%?(?P<ts>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}(?::\d+)?(?:\s+\d{4})?)\s+(?P<host>.+?)\s+(?P<mod>[\w-]+)/(?P<sev>\d)/(?P<tag>[\w-]+)\s*:?\s*(?P<msg>.*)$")
SEVERITY = {0: "긴급", 1: "경보", 2: "치명", 3: "오류", 4: "경고", 5: "알림", 6: "정보", 7: "디버그"}


def parse_logbuffer(text: str, limit: int = 100) -> list[dict[str, Any]]:
    """show logbuffer reverse → 최근 로그(최대 limit줄). 해석 못 한 줄도 원문으로 남김."""
    out: list[dict[str, Any]] = []
    for line in clean(text).split("\n"):
        if not line.strip() or re.match(r"^\s*(log buffer|max buffer|actual buffer|dropped|overwritten|current messages)", line, re.I):
            continue
        m = LOG_LINE_RE.match(line)
        if m:
            sev = int(m.group("sev"))
            out.append({"time": m.group("ts"), "module": f"{m.group('mod')}/{m.group('tag')}", "severity": sev,
                        "severity_name": SEVERITY.get(sev, str(sev)), "message": m.group("msg").strip(), "raw": line.strip()})
        elif line.lstrip().startswith("%") or (out and line.startswith(" ")):
            if out and line.startswith(" "):
                out[-1]["message"] += " " + line.strip()
                continue
            out.append({"time": "", "module": "", "severity": None, "severity_name": "", "message": line.strip(), "raw": line.strip()})
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- 백본(Comware)

LINK_STATES = ("UP", "DOWN", "ADM", "STBY")


def parse_interfaces(text: str) -> dict[str, str]:
    """display interface brief → {인터페이스: UP/DOWN/ADM/STBY}."""
    result: dict[str, str] = {}
    for line in clean(text).split("\n"):
        m = re.match(r"^\s*([A-Za-z][\w\-]*\d[\w/:.\-]*)\s+(UP|DOWN|ADM|Stby)(?:\(s\))?\b", line, re.I)
        if m:
            result[m.group(1)] = m.group(2).upper()
    return result


def is_physical_or_agg(name: str) -> bool:
    n = name.upper()
    return not n.startswith(("VLAN", "LOOP", "NULL", "INLOOP", "REG", "TUNNEL", "M-", "MGE"))


def parse_lagg(text: str) -> dict[str, dict[str, int]]:
    """display link-aggregation summary → {BAGG: {selected, unselected}}."""
    result: dict[str, dict[str, int]] = {}
    for line in clean(text).split("\n"):
        m = re.match(r"^\s*((?:BAGG|RAGG|Bridge-Aggregation|Route-Aggregation)\d+)\b(.*)$", line, re.I)
        if not m:
            continue
        rest = m.group(2)
        sm = re.search(r"Selected\s+(\d+)\s*/\s*(\d+)", rest, re.I)
        if sm:
            sel, tot = int(sm.group(1)), int(sm.group(2))
            result[m.group(1)] = {"selected": sel, "unselected": tot - sel}
            continue
        ints = [int(t) for t in rest.split() if t.isdigit()]
        if len(ints) >= 2:
            result[m.group(1)] = {"selected": ints[0], "unselected": ints[1]}
    return result


OSPF_STATE_RE = re.compile(r"^(Full|2-Way|Init|Down|ExStart|Exchange|Loading|Attempt)(?:/\S+)?$", re.I)


def parse_ospf(text: str) -> list[dict[str, str]]:
    peers: list[dict[str, str]] = []
    area = ""
    for line in clean(text).split("\n"):
        am = re.match(r"^\s*Area:\s*(\S+)", line, re.I)
        if am:
            area = am.group(1)
            continue
        toks = line.split()
        if len(toks) >= 4 and valid_ip(toks[0]) and toks[0].count(".") == 3 and len(toks) > 1 and valid_ip(toks[1]):
            state = next((t for t in toks[2:] if OSPF_STATE_RE.match(t)), None)
            if not state:
                continue
            intf = next((t for t in reversed(toks[2:]) if t != state and not t.isdigit() and not OSPF_STATE_RE.match(t)), "")
            peers.append({"router_id": toks[0], "address": toks[1], "state": state, "interface": intf, "area": area})
            continue
        mm = re.search(r"Peer\s+(\S+)\s+State\s+(\S+)", line, re.I)  # 단순/모의 형식
        if mm:
            peers.append({"router_id": mm.group(1), "address": mm.group(1), "state": mm.group(2), "interface": "", "area": area})
    return peers


def parse_vrrp(text: str) -> list[dict[str, str]]:
    groups: list[dict[str, str]] = []
    for line in clean(text).split("\n"):
        m = re.match(r"^\s*(\S+)\s+(\d+)\s+(Master|Backup|Initialize|Inactive)\b\s*(\d+)?", line, re.I)
        if m and not m.group(1).lower().startswith("vrid"):
            groups.append({"interface": m.group(1), "vrid": m.group(2), "state": m.group(3).capitalize(), "priority": m.group(4) or ""})
            continue
        m = re.search(r"VRID\s+(\d+)\s+State\s+(\w+)(?:\s+Priority\s+(\d+))?", line, re.I)
        if m:
            groups.append({"interface": "", "vrid": m.group(1), "state": m.group(2).capitalize(), "priority": m.group(3) or ""})
    return groups


def parse_vrrp_snapshot(text: str) -> list[dict[str, str]] | None:
    """확인된 그룹 목록([]는 명시적 0개), 해석 불가/불완전 출력은 None.

    부분 출력이나 빈 응답을 '모든 그룹 소실'로 단정하지 않습니다.
    기존 parse_vrrp의 목록 반환 계약은 유지합니다.
    """
    body = clean(text)
    groups = parse_vrrp(body)
    for line in body.splitlines():
        # A row/header that identifies another group is evidence of its presence,
        # even when its state or the rest of a verbose block could not be parsed.
        # Do not turn that partially understood output into a missing-group alarm.
        table_row = re.match(r"^\s*[A-Za-z][\w./:-]*\d[\w./:-]*\s+\d+(?:\s|$)", line)
        verbose_header = (re.match(r"^\s*Interface\s*:?[ \t]*[A-Za-z][\w./:-]*\d", line, re.I)
                          or re.match(r"^\s*[A-Za-z][\w./:-]*\d[\w./:-]*\s*(?:\||$)", line)
                          or re.search(r"\b(?:Virtual\s+Router(?:\s+ID)?\s*[:=]?\s*\d|VRID\s*[:=]\s*\d)", line, re.I))
        if (table_row or verbose_header) and not parse_vrrp(line):
            return None
    totals = re.findall(r"^\s*Total\s+number\s+of\s+virtual\s+routers\s*:\s*(\d+)\s*$", body, re.I | re.M)
    if totals and (len(set(totals)) != 1 or int(totals[0]) != len(groups)):
        return None
    if groups:
        keys = [vrrp_group_key(g["interface"], g["vrid"]) for g in groups]
        if len(keys) != len(set(keys)) or any(g["state"] not in ("Master", "Backup", "Initialize", "Inactive") for g in groups):
            return None
        return groups
    if totals and int(totals[0]) == 0:
        return []
    # Only an explicit no-configuration message counts as a verified empty set.
    if re.fullmatch(r"\s*No\s+VRRP\s+(?:groups?\s+)?configured\.?\s*", body, re.I):
        return []
    return None


_VRRP_ID = re.compile(r"(?:virtual\s+router|VRID|VR)\s*[:=]?\s*(\d+)", re.I)
_VRRP_FROMTO = re.compile(r"\bfrom\s+([A-Za-z]+)\s+to\s+([A-Za-z]+)", re.I)
_VRRP_INTF = re.compile(r"\b(Vlan-interface\s?\d+|Vlanif\s?\d+|Vlan\s?\d+|(?:Ten-|Forty-|Hundred-|Twenty-Five-)?GigabitEthernet\s?[\d/:.]+|"
                        r"Route-Aggregation\s?\d+|Bridge-Aggregation\s?\d+|[A-Z][A-Za-z-]+\d+(?:/\d+)+)", re.I)
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def log_time_ts(text: str, now: float | None = None) -> float | None:
    """'Oct 22 10:15:32:123 2026' 같은 장비 로그 시각 → timestamp(연도가 없으면 올해/작년 추정)."""
    import time as _t
    from datetime import datetime as _dt

    m = re.match(r"^\s*([A-Za-z]{3})\s+(\d{1,2})\s+(\d{2}):(\d{2}):(\d{2})(?::(\d+))?(?:\s+(\d{4}))?", text or "")
    if not m or m.group(1).lower() not in _MONTHS:
        return None
    now = now if now is not None else _t.time()
    year = int(m.group(7)) if m.group(7) else _dt.fromtimestamp(now).year
    microsecond = int((m.group(6) or "0").ljust(6, "0")[:6])
    try:
        dt = _dt(year, _MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)), microsecond)
        if not m.group(7) and dt.timestamp() > now + 86400:
            dt = dt.replace(year=year - 1)
    except ValueError:
        return None
    return dt.timestamp()


def vrrp_group_key(intf: str, vrid: str) -> str:
    """show vrrp의 'Vlan20' 와 로그의 'Vlan-interface20' 를 같은 그룹으로 맞춤."""
    i = re.sub(r"\s+", "", intf or "")
    vlan = re.fullmatch(r"vlan(?:-interface|if)?(\d+)", i, re.I)
    i = f"Vlan{int(vlan.group(1))}" if vlan else i.casefold()
    v = str(vrid).strip()
    v = str(int(v)) if v.isdigit() else v
    return f"{i}/{v}"


def parse_vrrp_logs(text: str, now: float | None = None) -> list[dict[str, Any]]:
    """show logbuffer 출력에서 VRRP 상태 변경 로그(언제, 어느 그룹, 무엇→무엇)를 뽑습니다."""
    out: list[dict[str, Any]] = []
    for x in parse_logbuffer(text, 5000):
        blob = f"{x['module']} {x['message']}"
        if "vrrp" not in blob.lower():
            continue
        ft = _VRRP_FROMTO.search(x["message"])
        if not ft:
            continue
        vid = _VRRP_ID.search(x["message"])
        intf = _VRRP_INTF.search(x["message"])
        vrid = vid.group(1) if vid else ""
        out.append({
            "time": x["time"], "ts": log_time_ts(x["time"], now=now), "vrid": vrid,
            "interface": (intf.group(1) if intf else ""),
            "group": vrrp_group_key(intf.group(1) if intf else "", vrid),
            "old": ft.group(1).capitalize(), "new": ft.group(2).capitalize(),
            "text": x["raw"][:400],
        })
    return out


BAD_HW = ("fault", "abnormal", "failed", "failure", "error", "offline")


def parse_power(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    slot = ""
    for line in clean(text).split("\n"):
        sm = re.match(r"^\s*Slot\s+(\d+)\s*:?\s*$", line, re.I)
        if sm:
            slot = sm.group(1)
            continue
        m = re.match(r"^\s*(\d+)\s+(Normal|Absent|Fault|Abnormal|Failed|Off|NotSupply|Not\s+Supply)\b", line, re.I)
        if not m:
            m = re.search(r"\b(?:Power(?:ID)?|PSU|PWR)\s*(\d+)\b[^\n]*?\bState\s*[:=]?\s*(\w+)", line, re.I)
        if m:
            items.append({"slot": slot, "id": m.group(1), "state": m.group(2).capitalize(), "line": line.strip()})
    return items


def parse_fan(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    slot = ""
    for line in clean(text).split("\n"):
        sm = re.match(r"^\s*Slot\s+(\d+)\s*:?\s*$", line, re.I)
        if sm:
            slot = sm.group(1)
            continue
        m = re.search(r"\bFan(?:\s+Frame|\s+Tray)?\s*(\d+)\s*(?:State)?\s*[:=]?\s*(Normal|Absent|Fault|Abnormal|Failed)\b", line, re.I)
        if m:
            items.append({"slot": slot, "id": m.group(1), "state": m.group(2).capitalize(), "line": line.strip()})
    return items


def parse_device_slots(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for line in clean(text).split("\n"):
        m = re.match(r"^\s*(\d+)\s+(\S+)\s+(Master|Standby|Normal|Fault|Absent|Abnormal|Offline|Faulty)\b", line, re.I)
        if m:
            items.append({"slot": m.group(1), "type": m.group(2), "state": m.group(3).capitalize(), "line": line.strip()})
            continue
        m = re.match(r"^\s*Slot\s+(\d+)\s+State\s+(\w+)", line, re.I)
        if m:
            items.append({"slot": m.group(1), "type": "", "state": m.group(2).capitalize(), "line": line.strip()})
    return items


# --------------------------------------------------------------------------- Aruba MM / WLC

SWITCH_ALIASES = {
    "ip": ("IP Address", "Switch IP", "IPv4 Address"),
    "name": ("Name", "Switch Name", "Hostname", "Host Name"),
    "type": ("Type",),
    "model": ("Model",),
    "version": ("Version",),
    "status": ("Status",),
    "config_state": ("Configuration State", "Config State"),
}


def parse_show_switches(text: str) -> list[dict[str, str]]:
    rows = parse_table(text, SWITCH_ALIASES, ("ip", "status"))
    out = []
    seen = set()
    for r in rows:
        ip = valid_ip(r.get("ip", "")) or valid_ip(r["_line"])
        if not ip or ip in seen:
            continue
        status = (r.get("status") or "").strip()
        if not status:
            continue
        seen.add(ip)
        st = status.lower()
        out.append({
            "ip": ip,
            "name": r.get("name", ""),
            "type": r.get("type", ""),
            "model": r.get("model", ""),
            "version": r.get("version", ""),
            "status": "Up" if st == "up" else "Down" if st == "down" else status,
            "config_state": r.get("config_state", ""),
        })
    return out


MEMBERSHIP_ALIASES = {
    "role": ("Type",),
    "ip": ("IPv4 Address", "IP Address", "IP"),
    "priority": ("Priority",),
    "conn": ("Connection-Type", "Connection Type"),
    "status": ("STATUS", "Status"),
}


def parse_membership(text: str) -> list[dict[str, str]]:
    rows = parse_table(text, MEMBERSHIP_ALIASES, ("ip", "conn"))
    out = []
    for r in rows:
        ip = valid_ip(r.get("ip", ""))
        if not ip:
            continue
        status = r.get("status", "")
        state = status.split("(")[0].strip().upper() if status else ""
        role = ""
        rm = re.search(r"\((Leader|Member)", status, re.I)
        if rm:
            role = rm.group(1).capitalize()
        out.append({
            "ip": ip,
            "self": r.get("role", "").lower() == "self",
            "conn": r.get("conn", ""),
            "state": state,
            "role": role,
            "status_raw": status,
        })
    return out


def parse_load_distribution(text: str) -> dict[str, Any]:
    rows: dict[str, dict[str, int]] = {}
    total = None
    for line in clean(text).split("\n"):
        tm = re.search(r"Total\s*:?\s*Active[\s-]*Clients\s*[:=]?\s*([\d,]+)", line, re.I)
        if tm:
            total = to_int(tm.group(1))
            continue
        m = re.search(r"((?:\d{1,3}\.){3}\d{1,3})\s+([\d,]+)\s+([\d,]+)\s*$", line)
        if m and valid_ip(m.group(1)):
            a, s = to_int(m.group(2)), to_int(m.group(3))
            if a is not None and s is not None:
                rows[m.group(1)] = {"active": a, "standby": s}
    computed = sum(r["active"] for r in rows.values())
    return {"rows": rows, "total_active": total if total is not None else computed}
