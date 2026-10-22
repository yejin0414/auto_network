"""Reject accidentally tracked runtime data, secret containers and private IPv4 literals.

Run from any directory: python tools/check_snapshot.py
Secret values are separately checked with Gitleaks; this is a source inventory guard.
"""
from pathlib import Path
import ipaddress
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
FORBIDDEN_DIRS = {"data", "data-demo", "보고서", "보고서-demo", "dist", "build", ".venv", "venv", "__pycache__"}
FORBIDDEN_SUFFIXES = {".log", ".db", ".sqlite", ".sqlite3", ".pem", ".key", ".p12", ".zip", ".exe"}


def main():
    result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True)
    paths = [Path(x.decode("utf-8")) for x in result.stdout.split(b"\0") if x]
    if not paths:
        print("FAIL: stage the reviewed snapshot before checking its tracked inventory")
        return 1
    findings = []
    for rel in paths:
        path = ROOT / rel
        if (set(rel.parts) & FORBIDDEN_DIRS or rel.suffix.lower() in FORBIDDEN_SUFFIXES
                or rel.as_posix() == "config/config.json" or rel.name.startswith(".env")
                or re.search(r"\.(?:sqlite3?|db)-(?:wal|shm|journal)$", rel.name)):
            findings.append(f"{rel}: runtime/credential/archive file")
        if path.is_symlink():
            findings.append(f"{rel}: symlink requires manual review")
            continue
        try:
            content = path.read_text(encoding="utf-8-sig")
        except UnicodeError:
            if rel.suffix.lower() not in {".png", ".ico"}:
                findings.append(f"{rel}: unexpected binary")
            continue
        # This file defines the disallowed ranges, not an operational inventory.
        if rel.as_posix() == "tools/check_snapshot.py":
            continue
        for number, line in enumerate(content.splitlines(), 1):
            for literal in IPV4.findall(line):
                try:
                    addr = ipaddress.ip_address(literal)
                except ValueError:
                    continue
                if any(addr in net for net in PRIVATE):
                    findings.append(f"{rel}:{number}: private IPv4 literal")
    for finding in findings:
        print(f"FAIL: {finding}")
    print(f"{'FAIL' if findings else 'PASS'}: inspected {len(paths)} tracked files")
    return bool(findings)


if __name__ == "__main__":
    sys.exit(main())
