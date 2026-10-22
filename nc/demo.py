"""장비 없이 화면과 판단 로직을 확인하는 데모 모드.

실제 장비 명령 출력과 같은 형식의 텍스트를 만들어 같은 파서·판단 로직을 거치게 합니다.
주소는 문서용 예약 대역(192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24)만 사용합니다.
"""

from __future__ import annotations

import math
import random
import time
from datetime import datetime

from .collector import ConnectFailure

DEMO_CONFIG = {
    "site_name": "데모 사업장",
    # 사업장 구성: 백본 4대, MM 2대, WLC 8대
    "devices": (
        [{"id": f"bb{i}", "name": f"백본 {i}호기", "role": "BB", "host": f"192.0.2.{i}"} for i in range(1, 5)]
        + [{"id": f"mm{i}", "name": f"MM-0{i}", "role": "MM", "host": f"192.0.2.{9 + i}"} for i in range(1, 3)]
        # WLC: IN 클러스터 4대(7240XM) + OUT 클러스터 4대(7210)
        + [{"id": f"wlc{i}", "name": f"WLC-{'IN' if i <= 4 else 'OUT'}-0{(i - 1) % 4 + 1}", "role": "WLC",
            "host": f"198.51.100.{10 + i}", "cluster": "IN" if i <= 4 else "OUT", "cluster_primary": i in (1, 5)}
           for i in range(1, 9)]
    ),
    "schedule": {"enabled": True, "interval_minutes": 60, "align_to_clock": True},
}

BACKFILL_RUNS = 24
VRRP_SWAP_AT = 18   # 이 회차부터 bb3 → bb4로 Vlan20 VRRP Master 절체(데모)
BASE_UPTIME_DAYS = {"BB": 86, "MM": 41, "WLC": 25}


def _seed(dev_id: str) -> int:
    import zlib

    return zlib.crc32(dev_id.encode())


class DemoSession:
    def __init__(self, world: "DemoWorld", device: dict) -> None:
        self.world = world
        self.device = device

    def run(self, command: str, timeout: int) -> str:
        time.sleep(self.world.rng.uniform(0.05, 0.25) * self.world.speed)
        return self.world.output(self.device, command)

    def close(self) -> None:
        pass


class DemoWorld:
    """DemoDriver 역할도 함께 합니다(open/begin_run)."""

    def __init__(self, speed: float = 1.0) -> None:
        self.index = 0
        self.ts = time.time()
        self.speed = speed
        self.rng = random.Random(7)
        self.reboot_at: dict[str, float] = {}
        # 현재 설정의 장비 목록(데모 설정을 바꿔도 따라감). app.py가 지정, 기본은 DEMO_CONFIG
        self.devices_provider = lambda: DEMO_CONFIG["devices"]
        self.vrrp_ts: float | None = None

    def _devs(self, role: str) -> list[dict]:
        return [d for d in self.devices_provider() if d["role"] == role and d.get("enabled", True)]

    def _model(self, dev: dict) -> str:
        if dev["role"] == "MM":
            return "ArubaMM-VA"
        return "Aruba7210" if dev.get("cluster") == "OUT" else "Aruba7240XM"

    def _same_cluster(self, dev: dict) -> list[dict]:
        return [w for w in self._devs("WLC") if w.get("cluster", "") == dev.get("cluster", "")]

    def _role(self, dev_id: str) -> str:
        return next((d["role"] for d in self.devices_provider() if d["id"] == dev_id),
                    "BB" if dev_id.startswith("bb") else "MM" if dev_id.startswith("mm") else "WLC")

    # Driver 인터페이스
    def begin_run(self, ts: float) -> None:
        self.ts = ts
        self.rng = random.Random(1000 + self.index)
        self.index += 1
        if self.i == VRRP_SWAP_AT:
            self.vrrp_ts = ts - 1260   # 점검 21분 전 VRRP 절체(데모)

    def open(self, device: dict, cred, ssh: dict) -> DemoSession:
        time.sleep(self.rng.uniform(0.1, 0.4) * self.speed)
        if device["id"] == "wlc2" and self.i in (14, 15):
            raise ConnectFailure("timeout", "접속 시간 초과(15초): 관리망 경로와 SSH 허용 여부를 확인하세요.")
        if cred is None:
            raise ConnectFailure("credential", "계정 없음")
        return DemoSession(self, device)

    @property
    def i(self) -> int:
        return self.index - 1

    # ------------------------------------------------------------- 상태
    def hour_factor(self) -> float:
        h = datetime.fromtimestamp(self.ts).hour + datetime.fromtimestamp(self.ts).minute / 60
        day = max(0.0, math.sin((h - 6) / 14 * math.pi)) if 6 <= h <= 20 else 0.0
        return 0.12 + 0.88 * day

    def cpu(self, dev_id: str) -> float:
        role = self._role(dev_id)
        base = {"BB": 8, "MM": 9, "WLC": 14}[role] + _seed(dev_id) % 6
        v = base + 10 * self.hour_factor() * (1 if role == "WLC" else 0.4) + self.rng.uniform(-3, 3)
        if dev_id == "bb4" and self.i >= 21:
            v = 52 + self.rng.uniform(0, 9)
        return round(max(1, v), 1)

    def mem(self, dev_id: str) -> float:
        base = {"BB": 40, "MM": 45, "WLC": 36}[self._role(dev_id)] + _seed(dev_id) % 4
        v = base + 4 * self.hour_factor() + self.rng.uniform(-1, 1)
        if dev_id == "mm2" and 30 <= self.i < 32:
            v = 74 + self.rng.uniform(0, 2)
        return round(v, 1)

    def uptime(self, dev_id: str) -> int:
        if dev_id == "wlc2" and self.i >= 16:
            return int((self.i - 16) * 3600 + 1500)
        return int(BASE_UPTIME_DAYS[self._role(dev_id)] * 86400 + _seed(dev_id) % 7200 + self.i * 3600)

    def wlc_down(self, dev_id: str) -> bool:
        return dev_id == "wlc2" and self.i in (14, 15)

    def clients(self, group: list[dict] | None = None) -> dict[str, tuple[int, int]]:
        f = self.hour_factor()
        out = {}
        for d in (group if group is not None else self._devs("WLC")):
            k, ip = d["id"], d["host"]
            if self.wlc_down(k):
                continue
            peak = 160 if d.get("cluster") == "OUT" else 410  # OUT(7210)은 수용량이 작음
            a = int(peak * f + self.rng.randint(-15, 15))
            if k == "wlc3" and self.i >= 23:
                a = int(a * 0.08)
            s = int(peak * 0.97 * f + self.rng.randint(-12, 12))
            out[ip] = (max(0, a), max(0, s))
        return out

    # ------------------------------------------------------------- 출력 생성
    def output(self, dev: dict, command: str) -> str:
        c = " ".join(command.lower().split())
        did = dev["id"]
        if dev["role"] == "BB":
            return self._comware(did, dev, c)
        return self._aruba(did, dev, c)

    @staticmethod
    def _fmt_up_aruba(sec: int) -> str:
        d, r = divmod(sec, 86400)
        h, r = divmod(r, 3600)
        m, s = divmod(r, 60)
        return f"{d} days {h} hours {m} minutes {s} seconds"

    def _aruba(self, did: str, dev: dict, c: str) -> str:
        name = dev["name"]
        if c == "show version":
            model = self._model(dev)
            return (f"Aruba Operating System Software.\nArubaOS (MODEL: {model}), Version 8.10.0.7\n"
                    "Compiled on 2023-09-05 at 11:51:01 UTC (build 88523) by p4build\n"
                    f"Switch uptime is {self._fmt_up_aruba(self.uptime(did))}\nReboot Cause: User reboot")
        if c in ("show cpuload", "show cpu"):
            v = self.cpu(did)
            u = round(v * 0.45, 1)
            return f"user {u}%, system {round(v - u, 1)}%, idle {round(100 - v, 1)}%"
        if c == "show memory":
            total = 15995392 if dev["role"] == "MM" else 3949512
            used = int(total * self.mem(did) / 100)
            return f"Memory (Kb): total: {total}, used: {used}, free: {total - used}"
        if c == "show switches" and dev["role"] == "MM":
            lines = ["All Switches", "------------",
                     "IP Address      IPv6 Address  Name        Location   Type     Model        Version            Status  Configuration State  Config Sync Time (sec)  Config ID",
                     "----------      ------------  ----        --------   ----     -----        -------            ------  -------------------  ----------------------  ---------"]
            rows = [(m["host"], m["name"][:11], "master" if i == 0 else "standby", "ArubaMM-VA", "up", "UPDATE SUCCESSFUL")
                    for i, m in enumerate(self._devs("MM"))]
            for w in self._devs("WLC"):
                down = self.wlc_down(w["id"])
                rows.append((w["host"], w["name"][:11], "MD", self._model(w)[:12], "down" if down else "up",
                             "UPDATE REQUIRED" if down else "UPDATE SUCCESSFUL"))
            for ip, n, t, m, st, cs in rows:
                lines.append(f"{ip:<16}None          {n:<12}Building1  {t:<9}{m:<13}8.10.0.7_88523     {st:<8}{cs:<21}0                       215")
            lines += ["", f"Total Switches:{len(rows)}"]
            return "\n".join(lines)
        if c == "show lc-cluster group-membership":
            lines = ["Cluster Info Table", "------------------",
                     "Type IPv4 Address    Priority Connection-Type STATUS",
                     "---- --------------- -------- --------------- ------"]
            group = self._same_cluster(dev)
            leader = (group or [{"id": ""}])[0]["id"]
            for w in group:
                k, ip = w["id"], w["host"]
                if self.wlc_down(k):
                    lines.append(f"peer {ip:<15}      128    L2-Connected DISCONNECTED")
                    continue
                if k == leader:
                    lines.append(f"self {ip:<15}      128             N/A CONNECTED (Leader)")
                else:
                    ms = self.rng.randint(20, 90)
                    lines.append(f"peer {ip:<15}      128    L2-Connected CONNECTED (Member, last HBT_RSP {ms}ms ago, RTD = 0.{self.rng.randint(100, 499)} ms)")
            return "\n".join(lines)
        if c == "show lc-cluster load distribution client":
            lines = ["Cluster Load Distribution for Clients", "-------------------------------------",
                     "Type IPv4 Address    Active Clients Standby Clients",
                     "---- --------------- -------------- ---------------"]
            group = self._same_cluster(dev)
            cl = self.clients(group)
            for ip, (a, s) in cl.items():
                t = "self" if ip == dev["host"] else "peer"
                lines.append(f"{t} {ip:<15} {a:>14} {s:>15}")
            lines.append(f"Total: Active Clients {sum(a for a, _ in cl.values())} Standby Clients {sum(s for _, s in cl.values())}")
            return "\n".join(lines)
        if c.startswith("show "):
            return f"Demo output for '{c}' on {name}.\n(데모 모드에서는 일부 명령만 실제와 같은 형식으로 응답합니다.)"
        return "% Invalid input detected at '^' marker."

    def _comware(self, did: str, dev: dict, c: str) -> str:
        incident = did == "bb3" and self.i in (26, 27)
        if c == "display version":
            sec = self.uptime(did)
            w, r = divmod(sec, 604800)
            d, r = divmod(r, 86400)
            h, r = divmod(r, 3600)
            return ("HPE Comware Software, Version 7.1.070, Release 2609\n"
                    "Copyright (c) 2010-2020 Hewlett Packard Enterprise Development LP\n"
                    f"HPE FF 5940 48SFP+ 6QSFP28 Switch uptime is {w} weeks, {d} days, {h} hours, {r // 60} minutes\n"
                    "Last reboot reason : User reboot")
        if c in ("show cpu summary", "display cpu-usage summary"):
            v = self.cpu(did)
            return ("Slot CPU        Last 5 sec        Last 1 min        Last 5 min\n"
                    f"1    0          {v + self.rng.uniform(-2, 4):.0f}%{'':<15}{v:.0f}%{'':<15}{v - 1:.0f}%\n"
                    f"2    0          {max(1, v - 4):.0f}%{'':<15}{max(1, v - 5):.0f}%{'':<15}{max(1, v - 5):.0f}%")
        if c in ("show memory summary", "display memory summary"):
            used_pct = self.mem(did)
            total = 8018440
            u1 = int(total * used_pct / 100)
            u2 = int(total * (used_pct - 6) / 100)
            return ("Memory statistics are measured in KB:\n"
                    "Slot Total      Used       Free       Shared     Buffers    Cached     FreeRatio\n"
                    f"1    {total:<10} {u1:<10} {total - u1:<10} 0          2208       454056     {100 - used_pct:.1f}%\n"
                    f"2    {total:<10} {u2:<10} {total - u2:<10} 0          2208       454056     {100 - used_pct + 6:.1f}%")
        if c in ("show logbuffer reverse", "display logbuffer reverse"):
            base = datetime.fromtimestamp(self.ts)
            lines = ["Log buffer: Enabled", "Max buffer size: 1024", "Current messages: 6"]
            stamp = lambda mins: (base.replace(second=0, microsecond=0)).strftime("%b %d %H:%M") if False else \
                datetime.fromtimestamp(self.ts - mins * 60).strftime("%b %d %H:%M:%S:000 %Y")
            if incident:
                lines.append(f"%{stamp(3)} {dev['name']} IFNET/3/PHY_UPDOWN: Physical state on the interface Ten-GigabitEthernet1/0/2 changed to down.")
                lines.append(f"%{stamp(3)} {dev['name']} OSPF/5/OSPF_NBR_CHG: OSPF 1 Neighbor 192.0.2.111(Vlan-interface101) changed from FULL to INIT.")
            rest = [(14, f"{dev['name']} SHELL/5/SHELL_LOGIN: op logged in from 192.0.2.50."),
                    (75, f"{dev['name']} SSHS/6/SSHS_CONNECT: SSH user op (IP: 192.0.2.50) connected to the server successfully."),
                    (240, f"{dev['name']} LLDP/6/LLDP_CREATE_NEIGHBOR: Nearest bridge agent neighbor created on port Ten-GigabitEthernet1/0/49."),
                    (600, f"{dev['name']} DEV/4/FAN_RECOVERED: Fan 2 recovered.")]
            if self.vrrp_ts and self.i >= VRRP_SWAP_AT and did in ("bb3", "bb4"):
                ago = (self.ts - self.vrrp_ts) / 60
                if did == "bb3":
                    rest.append((ago, f"{dev['name']} VRRP4/6/VRRP_STATUS_CHANGE: The status of IPv4 virtual router 20 "
                                      "(configured on Vlan-interface20) changed from Master to Backup: "
                                      "Received a VRRP packet with higher priority."))
                else:
                    rest.append((ago, f"{dev['name']} VRRP4/6/VRRP_STATUS_CHANGE: The status of IPv4 virtual router 20 "
                                      "(configured on Vlan-interface20) changed from Backup to Master: "
                                      "Master_Down_Timer expired."))
            for mins, text in sorted(rest):
                lines.append(f"%{stamp(mins)} {text}")
            return "\n".join(lines)
        if c == "display cpu-usage":
            v = self.cpu(did)
            return "\n".join([
                "Slot 1 CPU 0 CPU usage:",
                f"      {v + self.rng.uniform(-2, 4):4.0f}% in last 5 seconds",
                f"      {v:4.0f}% in last 1 minute",
                f"      {v - 1:4.0f}% in last 5 minutes",
                "Slot 2 CPU 0 CPU usage:",
                f"      {max(1, v - 4):4.0f}% in last 5 seconds",
                f"      {max(1, v - 5):4.0f}% in last 1 minute",
                f"      {max(1, v - 5):4.0f}% in last 5 minutes"])
        if c == "display memory":
            used_pct = self.mem(did)
            total = 1001004
            used = int(total * used_pct / 100)
            return ("Memory statistics are measured in KB:\nSlot 1:\n"
                    "             Total      Used      Free    Shared   Buffers    Cached   FreeRatio\n"
                    f"Mem:       {total}    {used}    {total - used}         0      2196    136228       {100 - used_pct:.1f}%\n"
                    "-/+ Buffers/Cache:    404860    596144\nSwap:            0         0         0")
        if c == "display device":
            return ("Slot Type             State    Subslot  Soft Ver             Patch Ver\n"
                    "1    S5940-48SFP      Master   0        S5940-2609           None\n"
                    "2    S5940-48SFP      Standby  0        S5940-2609           None")
        if c == "display power":
            return (" Slot 1:\n PowerID State    Mode   Current(A)  Voltage(V)  Power(W)\n"
                    " 1       Normal   AC     --          --          --\n 2       Normal   AC     --          --          --\n"
                    " Slot 2:\n PowerID State    Mode   Current(A)  Voltage(V)  Power(W)\n"
                    " 1       Normal   AC     --          --          --\n 2       Normal   AC     --          --          --")
        if c == "display fan":
            return " Slot 1:\n Fan Frame 1 State: Normal\n Fan Frame 2 State: Normal\n Slot 2:\n Fan Frame 1 State: Normal\n Fan Frame 2 State: Normal"
        if c == "display interface brief":
            peer = "BB4" if did == "bb3" else "BB3"
            down2 = "DOWN auto    A   " if incident else "UP   10G(a)  F(a)"
            return ("Brief information on interfaces in route mode:\nLink: ADM - administratively down; Stby - standby\n"
                    "Interface            Link Protocol Primary IP      Description\n"
                    "Loop0                UP   UP(s)    203.0.113.3\nVlan10               UP   UP       192.0.2.132       WLAN-MGMT\n"
                    "Vlan100              UP   UP       192.0.2.101        TO-CORE\n\n"
                    "Brief information on interfaces in bridge mode:\n"
                    "Interface            Link Speed   Duplex Type PVID Description\n"
                    f"BAGG10               UP   20G(a)  F(a)   T    1    TO-{peer}\n"
                    f"BAGG20               UP   {'10G(a)' if incident else '20G(a)'}  F(a)   T    1    TO-WLC-AGG\n"
                    f"XGE1/0/49            UP   10G(a)  F(a)   T    1    TO-{peer}-1\n"
                    f"XGE1/0/50            UP   10G(a)  F(a)   T    1    TO-{peer}-2\n"
                    "XGE1/0/1             UP   10G(a)  F(a)   T    1    TO-WLC-AGG-1\n"
                    f"XGE1/0/2             {down2}   T    1    TO-WLC-AGG-2\n"
                    "XGE1/0/3             UP   10G(a)  F(a)   T    1    TO-MM-01\n"
                    "XGE1/0/4             UP   10G(a)  F(a)   T    1    TO-MM-02\n"
                    "XGE1/0/48            ADM  auto    A      A    1    SPARE")
        if c == "display link-aggregation summary":
            return ("Aggregation Interface Type:\nBAGG -- Bridge-Aggregation, RAGG -- Route-Aggregation\n"
                    "Actor System ID: 0x8000, 0cda-41b5-cf00\n\n"
                    "AGG        AGG   Partner ID              Selected  Unselected  Individual  Share\n"
                    "Interface  Mode                          Ports     Ports       Ports       Type\n"
                    "--------------------------------------------------------------------------------\n"
                    "BAGG10     D     0x8000, 0cda-41b5-d100  2         0           0           Shar\n"
                    f"BAGG20     D     0x8000, 0cda-41b5-e200  {1 if incident else 2}         {1 if incident else 0}           0           Shar")
        if c == "display ospf peer":
            st = "Init/DROther" if incident else "Full/DR"
            return ("\n         OSPF Process 1 with Router ID 203.0.113.3\n               Neighbor Brief Information\n\n"
                    " Area: 0.0.0.0\n Router ID       Address         Pri Dead-Time  State             Interface\n"
                    f" 203.0.113.{4 if did == 'bb3' else 3}      192.0.2.102        1   37         Full/BDR          Vlan100\n"
                    f" 203.0.113.1      192.0.2.111        1   33         {st:<17} Vlan101")
        if c == "display vrrp":
            master = did == "bb3"
            swapped = self.i >= VRRP_SWAP_AT
            master20 = did == ("bb4" if swapped else "bb3")
            return ("IPv4 Virtual Router Information:\n Running mode : Standard\n Total number of virtual routers : 2\n"
                    " Interface          VRID  State        Running  Adver   Auth     Virtual\n"
                    "                                       Pri      Timer   Type        IP\n"
                    " ---------------------------------------------------------------------\n"
                    f" Vlan10             10    {'Master' if master else 'Backup':<12} {120 if master else 100:<8} 100     None     192.0.2.131\n"
                    f" Vlan20             20    {'Master' if master20 else 'Backup':<12} {120 if master else 100:<8} 100     None     192.0.2.141")
        if c.startswith("display "):
            return f"Demo output for '{c}' on {dev['name']}.\n(데모 모드에서는 일부 명령만 실제와 같은 형식으로 응답합니다.)"
        return "              ^\n % Unrecognized command found at '^' position."


def seed_history(engine, world: DemoWorld, runs: int = BACKFILL_RUNS) -> None:
    """지난 24시간 동안 매시 점검한 것처럼 이력을 채웁니다."""
    now = time.time()
    top = now - (now % 3600)
    speed = world.speed
    world.speed = 0.0
    engine.demo_quiet = True  # 지난 24시간 데모 이력은 엑셀 저장·알림 없이
    for k in range(runs, 0, -1):
        ts = top - k * 3600 + 60
        engine.run_blocking("auto", now=ts)
    world.speed = speed
    engine.demo_quiet = False
