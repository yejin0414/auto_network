"""Minimal per-run reporting metadata; never persist full application settings."""

from __future__ import annotations

import math
from typing import Any

SCHEMA_VERSION = 1
# Bump when the meaning of stored evaluation results changes.
EVALUATION_VERSION = "1"
THRESHOLD_KEYS = ("cpu_warn", "cpu_crit", "mem_warn", "mem_crit", "client_ratio_pct", "client_min_total")
LEGACY_NOTE = ("당시 판단 기준 없음: 사업장명은 현재 설정의 참고값입니다. "
               "저장된 점검 결과를 표시하며 현재 임계값으로 재판정하지 않았습니다.")


def normalize_context(value: Any) -> dict | None:
    """Accept only the supported, complete snapshot format and copy allowed keys."""
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int:
        return None
    if value["schema_version"] != SCHEMA_VERSION or not isinstance(value.get("site_name"), str):
        return None
    evaluation_version = value.get("evaluation_version")
    if evaluation_version != EVALUATION_VERSION:
        return None
    thresholds = value.get("thresholds")
    if not isinstance(thresholds, dict):
        return None
    selected = {}
    for key in THRESHOLD_KEYS:
        number = thresholds.get(key)
        if type(number) not in (int, float):
            return None
        try:
            if not math.isfinite(number) or number < 0:
                return None
        except OverflowError:
            return None
        if key != "client_min_total" and number > 100:
            return None
        if key == "client_min_total" and int(number) != number:
            return None
        selected[key] = number
    if selected["cpu_warn"] >= selected["cpu_crit"] or selected["mem_warn"] >= selected["mem_crit"]:
        return None
    return {"schema_version": SCHEMA_VERSION, "evaluation_version": evaluation_version,
            "site_name": value["site_name"], "thresholds": selected}


def capture_context(config: dict) -> dict:
    """Copy only the report allowlist from the exact settings used for evaluation."""
    value = normalize_context({"schema_version": SCHEMA_VERSION, "evaluation_version": EVALUATION_VERSION,
                               "site_name": config.get("site_name", ""),
                               "thresholds": config.get("thresholds")})
    if value is None:
        raise ValueError("보고서 시점의 사업장명과 판단 기준이 올바르지 않습니다.")
    return value


def resolve_context(run: dict, fallback_site: str) -> tuple[str, dict | None, str]:
    context = normalize_context(run.get("report_context"))
    if context is None:
        return fallback_site, None, LEGACY_NOTE
    t = context["thresholds"]
    note = (f"점검 당시 판단 기준 (기록 형식 v{context['schema_version']}, 평가 v{context['evaluation_version']}): "
            f"CPU 주의 {t['cpu_warn']:g}% / 장애 {t['cpu_crit']:g}%, "
            f"메모리 사용 주의 {t['mem_warn']:g}% / 장애 {t['mem_crit']:g}%. "
            f"Client 비율 {t['client_ratio_pct']:g}% / 최소 합계 {t['client_min_total']:g}명.")
    return context["site_name"], t, note


def saved_metric_level(device: dict) -> str:
    """Historical CPU/memory result, without inferring thresholds from today's settings."""
    rank = {"ok": 0, "info": 0, "unknown": 1, "warn": 2, "crit": 3}
    checks = device.get("checks") or []
    levels = []
    for key in ("cpu", "memory"):
        found = [c.get("level") for c in checks if c.get("key") == key]
        levels.append(max((level if level in rank else "unknown" for level in found),
                          key=rank.__getitem__) if found else "unknown")
    return max(levels, key=rank.__getitem__)
