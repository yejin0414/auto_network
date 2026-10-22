"""점검 회차 1건을 인쇄·보고용 단일 HTML로 만듭니다."""

from __future__ import annotations

import html
import time

from .evaluate import LEVEL_LABEL, fmt_uptime
from .report_context import resolve_context

ROLE_ORDER = {"BB": 0, "MM": 1, "WLC": 2}
ROLE_NAME = {"BB": "백본", "MM": "Mobility Master", "WLC": "WLC"}
COLOR = {"ok": "#1d7f5f", "info": "#1d7f5f", "unknown": "#5b6577", "warn": "#a76700", "crit": "#c0342b"}


def _e(v) -> str:
    return html.escape(str(v if v is not None else "-"))


def render(run: dict, site: str) -> str:
    site, _thresholds, context_note = resolve_context(run, site)
    s = run["summary"]
    t = time.strftime("%Y-%m-%d %H:%M", time.localtime(run["started"]))
    counts = s.get("counts", {})
    devs = sorted(run["devices"].values(), key=lambda d: (ROLE_ORDER.get(d["role"], 9), d["name"]))
    rows = []
    for d in devs:
        m = d.get("metrics", {})
        rows.append(
            f"<tr><td>{_e(ROLE_NAME.get(d['role']))}</td><td><b>{_e(d['name'])}</b><br><small>{_e(d['host'])}</small></td>"
            f"<td><span class='b' style='background:{COLOR[d['status']]}'>{LEVEL_LABEL[d['status']]}</span></td>"
            f"<td class='n'>{_e(m.get('cpu'))}{'%' if m.get('cpu') is not None else ''}</td>"
            f"<td class='n'>{_e(m.get('mem'))}{'%' if m.get('mem') is not None else ''}</td>"
            f"<td>{_e(fmt_uptime(m.get('uptime')))}</td><td class='n'>{d.get('issues', 0)}</td></tr>"
        )
    details = []
    for d in devs:
        items = []
        for c in d["checks"]:
            ev = "".join(f"<div class='ev'>{_e(x)}</div>" for x in c.get("evidence", []))
            cmd = f"<code>{_e(c['command'])}</code>" if c.get("command") else ""
            if c.get("source"):
                cmd += f"<div><small>출처: {_e(c['source'])}</small></div>"
            items.append(
                f"<tr><td style='color:{COLOR[c['level']]};font-weight:600'>{LEVEL_LABEL[c['level']]}</td>"
                f"<td>{_e(c['label'])}</td><td>{_e(c['summary'])}{ev}</td><td>{cmd}</td></tr>"
            )
        details.append(f"<h3>{_e(d['name'])} <small>{_e(d['host'])}</small></h3><table class='d'>{''.join(items)}</table>")
    cluster = s.get("cluster") or []
    crow = "".join(
        f"<tr><td>{_e(c['name'])}</td><td>{_e(c['ip'])}</td><td>{_e(c['mm_status'])}</td><td>{_e(c['state'])} {_e(c['role'])}</td>"
        f"<td>{_e(c['conn'])}</td><td class='n'>{_e(c['active'])}</td><td class='n'>{_e(c['standby'])}</td></tr>" for c in cluster
    )
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>{_e(site)} 점검 보고서 {t}</title>
<style>
body{{font-family:"Segoe UI","Malgun Gothic",sans-serif;color:#1b2433;margin:32px auto;max-width:1000px;padding:0 16px;font-size:14px}}
h1{{font-size:22px;margin:0}} h2{{font-size:16px;margin:28px 0 8px;border-bottom:2px solid #1b2433;padding-bottom:4px}}
h3{{font-size:14px;margin:18px 0 6px}} small{{color:#5b6577;font-weight:400}}
table{{border-collapse:collapse;width:100%}} td,th{{border-bottom:1px solid #d9dee6;padding:6px 8px;text-align:left;vertical-align:top}}
th{{background:#eef1f5;font-weight:600}} .n{{text-align:right;font-variant-numeric:tabular-nums}}
.b{{color:#fff;border-radius:3px;padding:1px 8px;font-size:12px}} .ev{{font-family:Consolas,monospace;font-size:12px;color:#5b6577}}
code{{font-family:Consolas,monospace;font-size:12px}} .meta{{color:#5b6577;margin-top:4px}}
.kpi{{display:flex;gap:24px;margin-top:16px}} .kpi div b{{display:block;font-size:22px}}
@media print{{body{{margin:0}} h2{{break-after:avoid}} table{{break-inside:auto}}}}
</style></head><body>
<h1>{_e(site)} 무선망 점검 보고서</h1>
<div class="meta">점검 시각 {t} · 회차 #{run['id']} · {'자동' if run.get('trigger') == 'auto' else '수동'} 점검</div>
<div class="meta">{_e(context_note)}</div>
<div class="kpi"><div><b style="color:{COLOR[s['overall']]}">{LEVEL_LABEL[s['overall']]}</b>종합</div>
<div><b>{counts.get('crit', 0)}</b>장애</div><div><b>{counts.get('warn', 0)}</b>주의</div>
<div><b>{counts.get('unknown', 0)}</b>확인 불가</div><div><b>{counts.get('ok', 0)}</b>정상</div>
<div><b>{_e(f"{s['total_active']:,}" if s.get('total_active') is not None else '-')}</b>Active Client</div></div>
<h2>장비 요약</h2><table><tr><th>구분</th><th>장비</th><th>상태</th><th class='n'>CPU</th><th class='n'>메모리</th><th>가동시간</th><th class='n'>이상 항목</th></tr>{''.join(rows)}</table>
{'<h2>WLC 클러스터</h2><table><tr><th>WLC</th><th>IP</th><th>MM 보고</th><th>클러스터</th><th>Connection-Type</th><th class=n>Active</th><th class=n>Standby</th></tr>' + crow + '</table>' if cluster else ''}
<h2>항목별 결과</h2>{''.join(details)}
</body></html>"""
