/* 무선망 통합 점검 — 화면 스크립트 (외부 라이브러리 없음, 사내망 오프라인 동작) */
(() => {
  "use strict";

  const DESKTOP = window.NC_DESKTOP === true;
  const pv = () => (window.pywebview && window.pywebview.api) || null;
  const LV = { ok: "정상", info: "정상", unknown: "확인 불가", warn: "주의", crit: "장애" };
  const RANK = { ok: 0, info: 0, unknown: 1, warn: 2, crit: 3 };
  const ROLE = { BB: "백본", MM: "Mobility Master", WLC: "WLC" };
  const ROLE_HINT = {
    BB: "Comware: CPU·메모리·전원·팬·인터페이스·LACP·OSPF·VRRP",
    MM: "ArubaOS: CPU·메모리·가동시간·관리 컨트롤러 상태",
    WLC: "ArubaOS: CPU·메모리·MM 보고 상태·클러스터 연결·Client 분배",
  };
  const QUICK = {
    BB: ["display interface brief", "display ospf peer", "display vrrp", "display link-aggregation summary", "display cpu-usage", "display memory", "display power", "display fan", "display alarm", "display irf", "display logbuffer reverse"],
    MM: ["show switches", "show cpuload", "show memory", "show version", "show master-redundancy", "show database synchronize", "show log system 50"],
    WLC: ["show lc-cluster group-membership", "show lc-cluster load distribution client", "show cpuload", "show memory", "show version", "show ap active", "show log system 50"],
  };

  const S = {
    st: null, run: null, latestId: null, viewing: null, trends: {}, events: [], tab: "devices",
    drawer: null, dtab: "checks", rawCmd: null, rawCache: {}, trendHours: 24, trend7: null,
    lastNotified: 0, consoleOut: null, settingsDirty: false, vrrp: null, vrrpFilter: "all",
  };

  // ------------------------------------------------------------------ 유틸
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pad = (n) => String(n).padStart(2, "0");
  const hm = (ts) => { const d = new Date(ts * 1000); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
  const md = (ts) => { const d = new Date(ts * 1000); return `${d.getMonth() + 1}/${d.getDate()}`; };
  const full = (ts) => { const d = new Date(ts * 1000); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hm(ts)}`; };
  const rel = (sec) => { sec = Math.max(0, Math.round(sec)); if (sec < 60) return `${sec}초`; const m = Math.round(sec / 60); if (m < 60) return `${m}분`; const h = Math.floor(m / 60); return `${h}시간${m % 60 ? ` ${m % 60}분` : ""}`; };
  const fmtUp = (s) => { if (s == null) return "-"; const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60); return d ? `${d}일 ${h}시간` : h ? `${h}시간 ${m}분` : `${m}분`; };
  const num = (v) => (v == null ? "-" : Number(v).toLocaleString("ko-KR"));
  const worst = (arr) => arr.reduce((a, b) => (RANK[b] > RANK[a] ? b : a), "ok");

  async function api(path, body) {
    const opt = { headers: { "X-NC-Token": window.NC_TOKEN } };
    if (body !== undefined) { opt.method = "POST"; opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    const r = await fetch(path, opt);
    let data = null;
    try { data = await r.json(); } catch { data = null; }
    if (!r.ok) {
      const error = new Error((data && data.error) || `요청 실패 (${r.status})`);
      error.rollbackFailed = data?.rollback_failed === true;
      throw error;
    }
    return data;
  }

  let toastTimer;
  function toast(msg) {
    const t = $("#toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 3200);
  }

  function devicesOrdered() {
    const cfg = S.st?.config?.devices || [];
    const order = { BB: 0, MM: 1, WLC: 2 };
    return cfg.filter((d) => d.enabled).sort((a, b) => order[a.role] - order[b.role]);
  }
  const devResult = (id) => S.run?.devices?.[id];
  function missingProfiles() {
    const st = S.st; if (!st) return [];
    const need = new Set((st.config.devices || []).filter((d) => d.enabled).map((d) => d.credential));
    return [...need].filter((p) => !(st.credentials || {})[p]);
  }
  function renderCredBanner() {
    const miss = missingProfiles();
    const b = $("#credBanner");
    if (!miss.length) { b.hidden = true; return; }
    const names = miss.map((p) => S.st.credential_profiles[p]).join(", ");
    $("#credBannerText").textContent = `${names}이 입력되지 않아 해당 장비에 SSH 접속을 하지 못합니다. 계정을 저장하면 바로 점검합니다.`;
    b.hidden = false;
  }
  function gotoCredentials() {
    switchTab("settings");
    setTimeout(() => {
      const miss = missingProfiles();
      const first = $(`.cred[data-profile="${miss[0] || "backbone"}"]`);
      miss.forEach((p) => $(`.cred[data-profile="${p}"]`)?.classList.add("need"));
      first?.scrollIntoView({ behavior: "smooth", block: "center" });
      $('input[name="username"]', first)?.focus();
    }, 50);
  }
  $("#credBannerBtn").addEventListener("click", gotoCredentials);

  // ------------------------------------------------------------------ 테마
  function applyTheme(t) {
    if (t) document.documentElement.setAttribute("data-theme", t); else document.documentElement.removeAttribute("data-theme");
  }
  try { applyTheme(localStorage.getItem("nc-theme")); } catch { /* 저장소 없음 */ }
  $("#themeBtn").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    applyTheme(next);
    try { localStorage.setItem("nc-theme", next); } catch { /* 무시 */ }
  });

  // ------------------------------------------------------------------ 데이터 갱신
  async function refreshState(strict = false) {
    try {
      S.st = await api("/api/state");
      S.clockOffset = S.st.engine.now - Date.now() / 1000;
    } catch (e) {
      $("#schedText").textContent = "프로그램과 연결이 끊겼습니다";
      if (strict) throw e;
      return;
    }
    const newest = S.st.latest_run_id;
    if (newest && newest !== S.latestId) {
      const first = S.latestId === null;
      S.latestId = newest;
      await Promise.all([loadTrends(), loadEvents(), loadVrrp()]);
      if (!S.viewing) await loadRun(null);
      if (!first) notifyNewRun();
    } else if (!S.run && !newest) {
      renderAll();
    }
    renderBar();
    if (S.st.engine.running) renderTopo();
  }

  async function loadRun(id) {
    try {
      S.run = await api(`/api/run${id ? `?id=${id}` : ""}`);
    } catch { S.run = null; }
    S.viewing = id && id !== S.latestId ? id : null;
    S.rawCache = {};
    renderAll();
  }
  async function loadTrends() { try { S.trends = await api("/api/trends?hours=48"); } catch { S.trends = {}; } }
  async function loadEvents() { try { S.events = await api("/api/events?limit=80"); } catch { S.events = []; } }

  function notifyNewRun() {
    const fresh = S.events.filter((e) => e.run_id === S.latestId && e.kind === "new" && (e.level === "crit" || e.level === "warn"));
    if (!fresh.length) { if (S.st.engine.run_trigger === "manual") toast("점검을 마쳤습니다."); return; }
    toast(`새 이상 ${fresh.length}건: ${fresh[0].text}`);
    // 화면 오른쪽 아래 Windows 알림은 프로그램(점검 엔진)이 직접 띄웁니다.
  }

  let pollTimer;
  function schedulePoll() {
    clearTimeout(pollTimer);
    const fast = S.st?.engine?.running;
    pollTimer = setTimeout(async () => { await refreshState(); schedulePoll(); }, fast ? 1500 : 10000);
  }

  // ------------------------------------------------------------------ 상단 바
  function renderBar() {
    const st = S.st; if (!st) return;
    renderCredBanner();
    $("#siteName").textContent = st.config.site_name || "무선망 통합 점검";
    $("#demoTag").hidden = !st.engine.demo;
    if (st.version) $("#appVer").textContent = `v${st.version}`;
    $("#quitBtn").hidden = !st.web_mode;
    const sc = st.config.schedule;
    const box = $("#schedBox");
    box.classList.toggle("on", !!sc.enabled);
    const e = { ...st.engine, now: Date.now() / 1000 + (S.clockOffset || 0) };
    let txt;
    if (e.running) txt = `점검 중 · ${rel(e.now - e.run_started)} 경과`;
    else if (!sc.enabled) txt = "자동 점검 꺼짐";
    else if (e.next_run) txt = `다음 자동 점검 ${hm(e.next_run)} (${rel(e.next_run - e.now)} 후)${st.background?.registered ? " · 창 닫아도 점검" : ""}`;
    else txt = `자동 점검 ${sc.interval_minutes}분 주기`;
    $("#schedText").textContent = txt;
    const btn = $("#runBtn");
    btn.classList.toggle("busy", e.running);
    btn.disabled = e.running;
    $("#runLabel").textContent = e.running ? "점검 중" : "지금 점검";
    const crit = S.run?.summary?.counts?.crit || 0;
    const warn = S.run?.summary?.counts?.warn || 0;
    const title = (crit ? `(장애 ${crit}) ` : warn ? `(주의 ${warn}) ` : "") + "AutoNetwork · 무선망 통합 점검";
    if (document.title !== title) { document.title = title; if (DESKTOP) { try { pv()?.set_title(title); } catch { /* 무시 */ } } }
  }

  function bgNote(st) {
    const sc = st.config.schedule, bg = st.background || {};
    if (bg.pending) return "최신 자동 점검 설정을 Windows 작업에 반영하는 중입니다…";
    if (bg.ok === false) return `<span style="color:var(--crit)">⚠ ${esc(bg.message || "작업 스케줄러 동기화 실패")}</span>${bg.retrying ? " — 잠시 후 최신 설정으로 다시 시도합니다." : ""}`;
    if (!sc.enabled) return "자동 점검이 꺼져 있습니다.";
    if (sc.background === false) return "프로그램 창이 켜져 있는(최소화 포함) 동안만 자동 점검합니다. 창을 닫으면 자동 점검도 멈춥니다.";
    if (bg.registered) return "✓ 창을 닫아도 Windows 작업 스케줄러가 정해진 시간마다 창 없이 점검합니다(엑셀 저장·알림 포함). PC를 끄거나 로그아웃하면 멈추고, 절전에서 깨어나면 놓친 점검을 바로 합니다. 프로그램 폴더를 옮겼다면 프로그램을 한 번 실행하면 다시 맞춰집니다.";
    if (st.windows) return "창을 닫아도 점검하도록 Windows 작업 스케줄러에 등록하는 중입니다…";
    return "창을 닫아도 점검하는 기능은 Windows에서만 동작합니다.";
  }

  async function openExcel(id) {
    if (!S.run && !id) { toast("점검 기록이 없습니다. 먼저 ‘지금 점검’을 누르세요."); return; }
    toast("엑셀 보고서를 만드는 중…");
    try {
      const r = await api("/api/excel_open", { id: id || S.run.id });
      toast(S.st?.windows ? `엑셀 보고서를 열었습니다: ${r.path}` : `엑셀 보고서를 저장했습니다: ${r.path}`);
    } catch (e) { toast(e.message); }
  }
  $("#excelBtn").addEventListener("click", () => openExcel(S.run?.id));

  $("#runBtn").addEventListener("click", async () => {
    try { await api("/api/check", {}); toast("점검을 시작했습니다. 장비마다 결과가 들어오는 대로 표시합니다."); await refreshState(); schedulePoll(); }
    catch (e) { toast(e.message); }
  });

  // ------------------------------------------------------------------ 종합 판정
  function renderVerdict() {
    const v = $("#verdict");
    const run = S.run;
    if (!run) {
      v.dataset.level = "unknown";
      $("#verdictState").textContent = "점검 기록 없음";
      const hasDev = (S.st?.config?.devices || []).length > 0;
      $("#verdictLine").textContent = hasDev ? "‘지금 점검’을 누르면 등록된 장비를 한 번에 점검합니다." : "설정 탭에서 장비와 계정을 먼저 등록하세요.";
      $("#verdictStats").innerHTML = ""; $("#verdictMeta").textContent = "";
      return;
    }
    const s = run.summary, c = s.counts;
    v.dataset.level = s.overall;
    const head = { ok: "모두 정상", warn: "주의 필요", crit: "장애 발생", unknown: "일부 확인 불가" }[s.overall];
    $("#verdictState").textContent = head;
    const bad = Object.values(run.devices).filter((d) => RANK[d.status] >= 2).sort((a, b) => RANK[b.status] - RANK[a.status]);
    let line;
    if (bad.length) line = bad.slice(0, 3).map((d) => `${d.name} ${LV[d.status]}`).join(", ") + (bad.length > 3 ? ` 외 ${bad.length - 3}대` : "");
    else if (c.unknown && missingProfiles().length) line = `접속 계정이 없어 ${c.unknown}대를 확인하지 못했습니다. ‘계정 입력하기’ 버튼을 누르세요.`;
    else if (c.unknown) line = `${c.unknown}대는 접속하지 못해 상태를 확인하지 못했습니다.`;
    else line = `${s.total_devices}대 장비의 모든 점검 항목이 기준 안에 있습니다.`;
    $("#verdictLine").textContent = line;
    const cell = (k, label) => `<div class="s-${k}${c[k] ? "" : " zero"}"><dt>${label}</dt><dd>${c[k] || 0}</dd></div>`;
    $("#verdictStats").innerHTML = cell("crit", "장애") + cell("warn", "주의") + cell("unknown", "확인 불가") + cell("ok", "정상");
    const recent = S.events.slice(0, 4);
    $("#verdictRecent").innerHTML = recent.length ? recent.map((e) => `<li class="${e.level}"><time>${hm(e.ts)}</time><span>${esc(e.text)}</span></li>`).join("") : "";
    const dur = run.finished ? Math.round(run.finished - run.started) : null;
    $("#verdictMeta").textContent = `${full(run.started)} ${run.trigger === "auto" ? "자동" : "수동"} 점검${dur != null ? `, ${dur}초 소요` : ""}` +
      (s.total_active != null ? `  |  Active Client ${num(s.total_active)}명` : "");
  }

  // ------------------------------------------------------------------ 구성도
  function renderTopo() {
    const el = $("#topo");
    const devs = devicesOrdered();
    if (!devs.length) { el.innerHTML = `<div class="empty" style="margin:30px"><b>등록된 장비가 없습니다</b>설정 탭에서 백본, MM, WLC를 추가하세요.</div>`; return; }
    const W = 1000, NH = 54;
    const tiers = { BB: devs.filter((d) => d.role === "BB"), MM: devs.filter((d) => d.role === "MM"), WLC: devs.filter((d) => d.role === "WLC") };
    const Y = { BB: 20, MM: 118, WLC: 214 };
    const running = S.st?.engine?.running;
    const prog = S.st?.engine?.progress || {};
    const pos = {};
    let svg = "";
    // 한 줄에 최대 perRow대, 넘치면 다음 줄(예: WLC 8대 → 4대씩 2줄)
    const ROWGAP = 12;
    const place = (list, y, x0, x1, maxW, perRow) => {
      if (!list.length) return 0;
      const rows = Math.ceil(list.length / perRow);
      for (let r = 0; r < rows; r++) {
        const part = list.slice(r * perRow, (r + 1) * perRow);
        const n = part.length, gap = 14;
        const w = Math.min(maxW, (x1 - x0 - gap * (perRow - 1)) / perRow);
        const total = n * w + gap * (n - 1); let x = x0 + (x1 - x0 - total) / 2;
        part.forEach((d) => { pos[d.id] = { x, y: y + r * (NH + ROWGAP), w }; x += w + gap; });
      }
      return rows;
    };
    const bbRows = place(tiers.BB, Y.BB, 120, W - 20, 200, 4);
    Y.MM = Y.BB + Math.max(1, bbRows) * (NH + ROWGAP) + 44;
    const mmRows = place(tiers.MM, Y.MM, 120, W - 20, 190, 4);
    Y.WLC = Y.MM + Math.max(1, mmRows) * (NH + ROWGAP) + 42;
    // WLC: 클러스터(IN/OUT …)마다 상자 하나, 위아래로 쌓음
    const wlcGroups = [...new Set(tiers.WLC.map((d) => d.cluster || ""))].map((c) => ({ name: c, list: tiers.WLC.filter((d) => (d.cluster || "") === c) }));
    let gy = Y.WLC;
    wlcGroups.forEach((g) => { g.y = gy; g.rows = place(g.list, gy, 140, W - 40, 190, 4); gy += g.rows * (NH + ROWGAP) - ROWGAP + 24 + 22; });
    const wlcBottom = gy - 22;
    const busY = Y.BB + bbRows * (NH + ROWGAP) - ROWGAP + 22;
    const levelOf = (d) => (running && !devResult(d.id) ? "unknown" : devResult(d.id)?.status || "unknown");
    // 계층 라벨
    [["BB", "백본"], ["MM", "MM"]].forEach(([k, lab]) => {
      if (tiers[k].length) svg += `<text class="tier" x="0" y="${Y[k] + NH / 2 + 4}">${lab}</text>`;
    });
    wlcGroups.forEach((g) => { svg += `<text class="tier" x="0" y="${g.y + NH / 2 + 4}">${g.name ? `WLC ${esc(g.name)}` : "WLC 클러스터"}</text>`; });
    // 버스와 링크
    const bbs = tiers.BB.map((d) => pos[d.id]);
    const lower = [...tiers.MM.map((d) => [d, pos[d.id]])];
    if (bbs.length) {
      const xs = [...bbs.map((p) => p.x + p.w / 2), ...lower.map(([, p]) => p.x + p.w / 2)];
      if (tiers.WLC.length) xs.push(W / 2 + 50);
      svg += `<path class="link" d="M${Math.min(...xs)} ${busY} H${Math.max(...xs)}"/>`;
      tiers.BB.forEach((d) => { const p = pos[d.id]; const bad = RANK[levelOf(d)] >= 3; svg += `<path class="link${bad ? " bad" : ""}" d="M${p.x + p.w / 2} ${p.y + NH} V${busY}"/>`; });
      // 같은 줄에 나란히 있는 백본끼리 연결(이중화)
      for (let i = 0; i + 1 < bbs.length; i++) {
        if (bbs[i].y === bbs[i + 1].y) svg += `<path class="link" d="M${bbs[i].x + bbs[i].w} ${bbs[i].y + NH / 2} H${bbs[i + 1].x}"/>`;
      }
      lower.forEach(([d, p]) => { const bad = RANK[levelOf(d)] >= 3; svg += `<path class="link${bad ? " bad" : ""}" d="M${p.x + p.w / 2} ${busY} V${p.y}"/>`; });
    }
    if (tiers.WLC.length) {
      let prevBottom = null;
      wlcGroups.forEach((g, gi) => {
        const ws = g.list.map((d) => pos[d.id]);
        const bx = Math.min(...ws.map((p) => p.x)) - 12, bw = Math.max(...ws.map((p) => p.x + p.w)) - bx + 12;
        const bh = g.rows * (NH + ROWGAP) - ROWGAP + 24;
        svg += `<rect class="cluster-box" x="${bx}" y="${g.y - 12}" width="${bw}" height="${bh}" rx="12"/>`;
        if (gi === 0 && bbs.length) svg += `<path class="link" d="M${W / 2 + 50} ${busY} V${g.y - 12}"/>`;
        if (prevBottom !== null) svg += `<path class="link" d="M${bx + 24} ${prevBottom} V${g.y - 12}"/>`;
        prevBottom = g.y - 12 + bh;
      });
    }
    // 노드
    devs.forEach((d) => {
      const p = pos[d.id]; if (!p) return;
      const r = devResult(d.id); const lvl = levelOf(d); const m = r?.metrics || {};
      const flag = lvl === "ok" ? "" : LV[lvl];
      const busy = running && prog[d.id] && !["완료", "실패"].includes(prog[d.id]);
      const sub = busy ? prog[d.id] : d.host;
      const credMissing = r && !r.connected && r.checks.some((c) => c.source === "credential");
      const vals = r && r.connected ? `CPU ${m.cpu ?? "-"}%  MEM ${m.mem ?? "-"}%` : (r ? (credMissing ? "계정 미입력" : "접속 실패") : "");
      const nm = d.name.length > 14 ? d.name.slice(0, 13) + "…" : d.name;
      svg += `<g class="node" data-level="${lvl}" data-dev="${esc(d.id)}" tabindex="0" role="button" aria-label="${esc(d.name)} ${LV[lvl]}">
        ${lvl === "crit" ? `<rect class="pulse" x="${p.x}" y="${p.y}" width="${p.w}" height="${NH}" rx="9"/>` : ""}
        <rect class="body" x="${p.x}" y="${p.y}" width="${p.w}" height="${NH}" rx="9"/>
        <rect class="bar-s" x="${p.x}" y="${p.y + 8}" width="4" height="${NH - 16}" rx="2"/>
        ${busy ? `<rect class="scan" x="${p.x}" y="${p.y}" width="${p.w}" height="${NH}" rx="9"><animate attributeName="opacity" values=".05;.25;.05" dur="1.2s" repeatCount="indefinite"/></rect>` : ""}
        <text class="n-name" x="${p.x + 14}" y="${p.y + 20}">${esc(nm)}</text>
        <text class="n-flag" x="${p.x + p.w - 10}" y="${p.y + 20}" text-anchor="end">${esc(flag)}</text>
        <text class="n-sub" x="${p.x + 14}" y="${p.y + 35}">${esc(sub)}</text>
        <text class="n-val" x="${p.x + 14}" y="${p.y + 48}">${esc(vals)}</text>
      </g>`;
    });
    const H = tiers.WLC.length ? wlcBottom + 8 : (tiers.MM.length ? Y.MM + mmRows * (NH + ROWGAP) : Y.BB + bbRows * (NH + ROWGAP)) + 8;
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${svg}</svg>`;
    $$(".node", el).forEach((n) => {
      const open = () => openDrawer(n.dataset.dev);
      n.addEventListener("click", open);
      n.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); open(); } });
    });
  }

  // ------------------------------------------------------------------ 장비 현황
  function meter(val, warn, crit, label) {
    if (val == null) return `<div class="meter na"><div class="meter-top"><span>${label}</span><b>-</b></div><div class="meter-track"></div></div>`;
    const cls = val >= crit ? "crit" : val >= warn ? "warn" : "";
    return `<div class="meter"><div class="meter-top"><span>${label}</span><b>${val}%</b></div>
      <div class="meter-track"><div class="meter-fill ${cls}" style="width:${Math.min(100, val)}%"></div>
      <span class="meter-tick" style="left:${warn}%" title="주의 ${warn}%"></span><span class="meter-tick" style="left:${crit}%" title="장애 ${crit}%"></span></div></div>`;
  }

  function spark(id) {
    const pts = (S.trends[id] || []).slice(-24);
    if (pts.length < 2) return `<svg class="spark"></svg>`;
    const W = 120, H = 34, n = pts.length;
    const x = (i) => (i / (n - 1)) * (W - 4) + 2, y = (v) => H - 3 - (Math.min(100, v || 0) / 100) * (H - 6);
    const line = (k) => pts.map((p, i) => (p[k] == null ? null : `${x(i)},${y(p[k])}`)).filter(Boolean).join(" ");
    const dots = pts.map((p, i) => (RANK[p.status] >= 2 ? `<circle class="${p.status === "crit" ? "dot-bad" : "dot-warn"}" cx="${x(i)}" cy="${H - 2}" r="2"/>` : "")).join("");
    return `<svg class="spark" viewBox="0 0 ${W} ${H}" aria-label="최근 24회 CPU·메모리 추이"><polyline class="l-mem" points="${line("mem")}"/><polyline class="l-cpu" points="${line("cpu")}"/>${dots}</svg>`;
  }

  function issueText(r) {
    if (!r) return `<span class="okline">아직 점검하지 않았습니다</span>`;
    const bad = r.checks.filter((c) => RANK[c.level] >= 1).sort((a, b) => RANK[b.level] - RANK[a.level]);
    if (!bad.length) return `<span class="okline">${r.checks.length}개 항목 모두 정상</span>`;
    return bad.slice(0, 2).map((c) => `<b>${esc(c.label)}</b> ${esc(c.summary)}`).join("<br>") + (bad.length > 2 ? ` 외 ${bad.length - 2}건` : "");
  }

  function renderDevices() {
    const el = $("#tab-devices");
    const devs = devicesOrdered();
    if (!devs.length) {
      el.innerHTML = `<div class="empty"><b>등록된 장비가 없습니다</b>설정 탭에서 백본·MM·WLC 장비와 접속 계정을 등록하면 한 번에 점검합니다.<br><br><button class="btn primary" data-goto="settings">장비 등록하기</button></div>`;
      return;
    }
    const th = S.st.config.thresholds;
    const head = `<div class="row head"><span>상태</span><span>장비</span><span>CPU</span><span>메모리</span><span class="up-col">가동시간</span><span>확인할 내용</span><span class="spark-col">24시간 추이</span><span></span></div>`;
    // 섹션: 백본 / MM / WLC(클러스터별: WLC IN, WLC OUT …)
    const sections = [["BB", ""], ["MM", ""]];
    [...new Set(devs.filter((d) => d.role === "WLC").map((d) => d.cluster || ""))].forEach((c) => sections.push(["WLC", c]));
    el.innerHTML = sections.map(([role, cl]) => {
      const list = devs.filter((d) => d.role === role && (role !== "WLC" || (d.cluster || "") === cl)); if (!list.length) return "";
      const model = role === "WLC" ? (list.map((d) => devResult(d.id)?.metrics?.model).find(Boolean) || "") : "";
      const rows = list.map((d) => {
        const r = devResult(d.id); const m = r?.metrics || {}; const lvl = r?.status || "unknown";
        return `<button class="row" data-dev="${esc(d.id)}">
          <span class="badge-col"><span class="badge ${lvl}">${r ? LV[lvl] : "대기"}</span></span>
          <span class="name-col"><div class="name">${esc(d.name)}</div><div class="ip">${esc(d.host)}</div></span>
          ${meter(m.cpu, th.cpu_warn, th.cpu_crit, "CPU")}
          ${meter(m.mem, th.mem_warn, th.mem_crit, "메모리")}
          <span class="up up-col">${fmtUp(m.uptime)}</span>
          <span class="issue">${issueText(r)}</span>
          <span class="spark-col">${spark(d.id)}</span>
          <span class="chev" aria-hidden="true">›</span>
        </button>`;
      }).join("");
      const bad = list.filter((d) => RANK[devResult(d.id)?.status] >= 2).length;
      const title = role === "WLC" && cl ? `WLC ${esc(cl)} 클러스터` : ROLE[role];
      return `<div class="group"><div class="group-head"><h2>${title}</h2><span class="hint">${list.length}대${model ? ` · ${esc(model)}` : ""}${bad ? `, 이상 ${bad}대` : ""}  |  ${ROLE_HINT[role]}</span></div>
        <div class="rows">${head}${rows}</div></div>`;
    }).join("");
    $$(".row[data-dev]", el).forEach((b) => b.addEventListener("click", () => openDrawer(b.dataset.dev)));
  }

  // ------------------------------------------------------------------ 클러스터
  function renderCluster() {
    const el = $("#tab-cluster");
    const s = S.run?.summary;
    const members = s?.cluster || [];
    if (!members.length) { el.innerHTML = `<div class="empty"><b>클러스터 정보가 없습니다</b>WLC를 등록하고 점검하면 MM 보고 상태, 클러스터 멤버십, Client 분배를 함께 보여 줍니다.</div>`; return; }
    // 클러스터(IN/OUT 등)별로 따로 표시
    const names = [...new Set(members.map((m) => m.cluster || ""))];
    const info = Object.fromEntries((s.clusters || []).map((c) => [c.name, c]));
    const block = (name) => {
      const ms = members.filter((m) => (m.cluster || "") === name);
      const ci = info[name] || {};
      const connected = ms.filter((m) => m.state === "CONNECTED").length;
      const leader = ms.find((m) => m.role === "Leader");
      const mmUp = ms.filter((m) => m.mm_status === "Up").length;
      const maxC = Math.max(1, ...ms.map((m) => (m.active || 0) + (m.standby || 0)));
      const model = ci.model || ms.find((m) => m.model)?.model || "";
      const rows = ms.map((m) => {
        const a = m.active || 0, sb = m.standby || 0;
        return `<tr data-dev="${esc(m.id)}" style="cursor:pointer">
          <td><b>${esc(m.name)}</b><div class="ip mono" style="font-size:12px;color:var(--muted)">${esc(m.ip)}${m.model ? ` · ${esc(m.model)}` : ""}</div></td>
          <td><span class="badge ${m.status}">${LV[m.status]}</span></td>
          <td>${esc(m.mm_status || "-")}${m.config_state && m.config_state !== "UPDATE SUCCESSFUL" ? `<div class="note">${esc(m.config_state)}</div>` : ""}</td>
          <td>${esc(m.state || "-")}${m.role ? ` <span class="note">(${esc(m.role)})</span>` : ""}</td>
          <td>${esc(m.conn || "-")}</td>
          <td class="r">${num(m.active)}</td><td class="r">${num(m.standby)}</td>
          <td><div class="cbar"><div class="t" style="max-width:${((a + sb) / maxC) * 100}%"><span class="a" style="flex:${a}"></span><span class="s" style="flex:${sb}"></span></div></div></td>
        </tr>`;
      }).join("");
      return `<div class="group"><div class="group-head"><h2>${name ? `WLC ${esc(name)} 클러스터` : "WLC 클러스터"}</h2>
          <span class="hint">${ms.length}대${model ? ` · ${esc(model)}` : ""}${ci.source ? ` · 수집 ${esc(ci.source)}` : ""}</span></div>
        <div class="cluster-top">
          <div class="stat"><div class="k">Active Client</div><div class="v">${num(ci.total_active)}<small> 명</small></div></div>
          <div class="stat"><div class="k">클러스터 연결</div><div class="v">${connected}<small> / ${ms.length}대 CONNECTED</small></div></div>
          <div class="stat"><div class="k">MM 보고 Up</div><div class="v">${mmUp}<small> / ${ms.length}대</small></div></div>
          <div class="stat"><div class="k">Leader</div><div class="v" style="font-size:18px">${esc(leader?.name || "-")}</div></div>
        </div>
        <table class="grid"><thead><tr><th>WLC</th><th>상태</th><th>MM 보고</th><th>클러스터</th><th>Connection-Type</th><th class="r">Active</th><th class="r">Standby</th><th>분배</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    };
    el.innerHTML = (names.length > 1 ? `<p class="note" style="margin-top:0">전체 Active Client ${num(s.total_active)}명 · 클러스터 ${names.length}개(모델이 다른 컨트롤러는 클러스터를 따로 구성)</p>` : "")
      + names.map(block).join("")
      + `<div class="legend"><span><i style="background:var(--accent)"></i>Active Client</span><span><i style="background:color-mix(in srgb,var(--accent) 30%,transparent)"></i>Standby Client</span>
        <span>MM 수집: ${esc(s.mm_source || "-")}</span></div>`;
    $$("tr[data-dev]", el).forEach((tr) => tr.addEventListener("click", () => openDrawer(tr.dataset.dev)));
  }

  // ------------------------------------------------------------------ 이력
  function renderHistory() {
    const el = $("#tab-history");
    const devs = devicesOrdered();
    const runsSet = new Map();
    devs.forEach((d) => (S.trends[d.id] || []).forEach((p) => runsSet.set(p.run, p.t)));
    const runs = [...runsSet.entries()].sort((a, b) => a[0] - b[0]).slice(-48);
    const curId = S.run?.id;
    let grid = "";
    if (runs.length) {
      const cols = `140px repeat(${runs.length}, minmax(10px, 1fr))`;
      grid += `<div class="heat-grid" style="grid-template-columns:${cols}">`;
      devs.forEach((d) => {
        const map = new Map((S.trends[d.id] || []).map((p) => [p.run, p]));
        grid += `<div class="lab">${esc(d.name)}</div>`;
        runs.forEach(([rid, t]) => {
          const p = map.get(rid); const st = p ? p.status : "";
          grid += `<button class="cell ${st} ${rid === curId ? "sel" : ""}" data-run="${rid}" title="${esc(d.name)} ${full(t)} ${p ? LV[st] : "기록 없음"}${p && p.cpu != null ? ` / CPU ${p.cpu}%` : ""}"></button>`;
        });
      });
      grid += `<div></div>`;
      runs.forEach(([, t], i) => { grid += `<div class="time">${i % 6 === 0 ? `${md(t)}<br>${hm(t)}` : ""}</div>`; });
      grid += `</div>`;
    } else grid = `<div class="empty"><b>이력이 아직 없습니다</b>점검이 쌓이면 장비별 상태 변화를 시간 순서로 보여 줍니다.</div>`;
    const ev = S.events.length ? S.events.map((e) => `<div class="ev-item ${e.level}"><time>${hm(e.ts)}<br>${md(e.ts)}</time><div class="t">${esc(e.text)}</div></div>`).join("")
      : `<div class="ev-item"><time></time><div class="t">기록된 변화가 없습니다.</div></div>`;
    el.innerHTML = `<div class="hist-wrap"><div class="heat"><div class="group-head" style="margin-bottom:12px"><h2>최근 48회 점검</h2><span class="hint">칸을 누르면 그 회차 결과를 봅니다</span></div>${grid}
      <div class="actions" style="justify-content:flex-start">${S.run ? `<button class="btn small primary" data-excel>이 회차 엑셀 보고서 열기</button>
        <button class="btn small" data-reports>보고서 폴더 열기</button>` : ""}${S.run ? (DESKTOP
        ? `<button class="btn small" data-report="open">이 회차 보고서 열기</button><button class="btn small" data-report="save">보고서 파일로 저장</button>`
        : `<a class="btn small" href="/report?id=${S.run.id}&t=${encodeURIComponent(window.NC_TOKEN)}" target="_blank" rel="noopener">이 회차 보고서 열기</a>
      <a class="btn small" href="/report?id=${S.run.id}&download=1&t=${encodeURIComponent(window.NC_TOKEN)}">보고서 HTML 저장</a>`) : ""}</div></div>
      <div class="events"><h3>상태 변화 기록</h3>${ev}</div></div>`;
    $$(".cell[data-run]", el).forEach((c) => c.addEventListener("click", () => loadRun(Number(c.dataset.run))));
    $("[data-excel]", el)?.addEventListener("click", () => openExcel(S.run.id));
    $("[data-reports]", el)?.addEventListener("click", async () => { try { const r = await api("/api/open_reports", {}); toast(`보고서 폴더: ${r.path}`); } catch (e) { toast(e.message); } });
    $$("[data-report]", el).forEach((b) => b.addEventListener("click", async () => {
      const api = pv(); if (!api) { toast("잠시 후 다시 눌러 주세요."); return; }
      try {
        const r = b.dataset.report === "open" ? await api.open_report(S.run.id) : await api.save_report(S.run.id);
        if (r && r.ok) toast(b.dataset.report === "open" ? "보고서를 열었습니다. 인쇄(Ctrl+P)로 PDF 저장도 됩니다." : `저장했습니다: ${r.path}`);
        else if (r && r.error) toast(r.error);
      } catch (e) { toast(`보고서를 처리하지 못했습니다: ${e}`); }
    }));
  }

  // ------------------------------------------------------------------ VRRP 변경 이력
  async function loadVrrp() {
    try { S.vrrp = await api("/api/vrrp"); } catch { S.vrrp = S.vrrp || { items: [], unacked: 0 }; }
  }

  function renderVrrp() {
    const el = $("#tab-vrrp");
    if (!S.vrrp) { el.innerHTML = `<div class="empty"><b>불러오는 중…</b></div>`; loadVrrp().then(() => S.tab === "vrrp" && renderVrrp()); return; }
    const all = S.vrrp.items || [];
    const items = S.vrrpFilter === "open" ? all.filter((x) => !x.acked) : all;
    const open = all.filter((x) => !x.acked);
    const openDevs = [...new Map(open.map((x) => [x.device_id, x.device_name])).entries()];
    // 지금 '역할 변화'로 표시 중인 백본(기준값과 다른 VRRP)
    const flagged = Object.values(S.run?.devices || {}).filter((d) => d.role === "BB" && (d.checks || []).some((c) => c.key === "vrrp" && c.level === "warn"));
    const stateCls = (v) => (v === "Master" ? "ok" : v === "Backup" ? "neutral" : "crit");
    const sec = (ts) => `${full(ts)}:${pad(new Date(ts * 1000).getSeconds())}`;
    const when = (x) => x.log_ts ? `<b>${sec(x.log_ts)}</b><div class="hint">장비 로그 시각</div>`
      : `<b>${x.prev_check ? `${full(x.prev_check)} ~ ${hm(x.detected)}` : full(x.detected)}</b><div class="hint">이 두 점검 사이에 바뀜(장비 로그 없음)</div>`;
    const src = (x) => ({ "check+log": "점검 + 장비 로그", check: "점검에서 발견", log: "장비 로그" }[x.source] || x.source);
    const rows = items.map((x) => `<tr class="${x.acked ? "acked" : ""}">
        <td>${x.acked ? `<span class="badge ok">확인함</span><div class="hint">${md(x.acked)} ${hm(x.acked)}</div>` : `<span class="badge warn">미확인</span>`}</td>
        <td>${when(x)}</td>
        <td><b>${esc(x.device_name || x.device_id)}</b></td>
        <td class="mono">${esc(x.grp)}</td>
        <td><span class="badge ${stateCls(x.old)}">${esc(x.old)}</span> → <span class="badge ${stateCls(x.new)}">${esc(x.new)}</span></td>
        <td>${esc(src(x))}<div class="hint">발견 ${md(x.detected)} ${hm(x.detected)} 점검</div></td>
        <td class="mono small">${esc(x.text || "")}</td></tr>`).join("");
    el.innerHTML = `<div class="card vrrp-card">
      <div class="group-head"><h2>VRRP 변경 이력</h2><span class="hint">백본의 VRRP Master/Backup이 언제 바뀌었는지 보여 줍니다. 장비 로그(show logbuffer)에 기록이 있으면 정확한 변경 시각을, 없으면 앞뒤 점검 시각을 표시합니다.</span></div>
      ${open.length || flagged.length ? `<div class="vrrp-ack">
        <div><b>미확인 ${open.length}건</b>${flagged.length ? ` · 지금 ‘역할 변화’로 표시 중: ${flagged.map((d) => esc(d.name)).join(", ")}` : ""}
          <div class="hint">확인했으면 ‘확인 · 초기화’를 누르세요. 해당 백본의 VRRP 기준값만 지금 역할로 다시 잡고(다른 점검 항목은 그대로) 바로 다시 점검해서 장애 표시에서 VRRP 역할 변화를 지웁니다.</div></div>
        <div class="actions" style="margin:0;flex-wrap:wrap">${[...new Map([...openDevs, ...flagged.map((d) => [d.id, d.name])]).entries()].map(([id, name]) => `<button class="btn small" data-ack="${esc(id)}">${esc(name)} 확인 · 초기화</button>`).join("")}
          <button class="btn small primary" data-ack="">모두 확인 · 초기화하고 다시 점검</button></div></div>` : `<div class="vrrp-ack ok"><b>✓ 확인할 VRRP 변경이 없습니다.</b></div>`}
      <div class="actions" style="justify-content:flex-start;margin:12px 0 8px">
        <button class="btn small ${S.vrrpFilter === "all" ? "primary" : ""}" data-vf="all">전체 ${all.length}</button>
        <button class="btn small ${S.vrrpFilter === "open" ? "primary" : ""}" data-vf="open">미확인 ${open.length}</button></div>
      ${items.length ? `<div style="overflow-x:auto"><table class="dev-table vrrp-table"><thead><tr><th>상태</th><th>변경 시각</th><th>백본</th><th>그룹 (인터페이스/VRID)</th><th>변경</th><th>발견</th><th>장비 로그</th></tr></thead><tbody>${rows}</tbody></table></div>`
        : `<div class="empty"><b>기록된 VRRP 변경이 없습니다</b>점검 때마다 백본의 VRRP 역할과 장비 로그를 확인해 바뀌면 여기에 쌓습니다.</div>`}
    </div>`;
    $$("[data-vf]", el).forEach((b) => b.addEventListener("click", () => { S.vrrpFilter = b.dataset.vf; renderVrrp(); }));
    $$("[data-ack]", el).forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true;
      try {
        const r = await api("/api/vrrp/ack", { device: b.dataset.ack || null, recheck: true });
        toast(r.recheck ? "확인 처리했습니다. VRRP 기준값을 다시 잡고 바로 점검합니다." : "확인 처리했습니다. 진행 중인 점검이 끝나면 다음 점검부터 반영됩니다.");
        await loadVrrp(); await refreshState(); renderVrrp(); schedulePoll();
      } catch (e) { toast(e.message); b.disabled = false; }
    }));
  }

  // ------------------------------------------------------------------ 직접 확인
  function renderConsole() {
    const el = $("#tab-console");
    const devs = devicesOrdered();
    if (!devs.length) { el.innerHTML = `<div class="empty"><b>등록된 장비가 없습니다</b>설정 탭에서 장비를 등록하세요.</div>`; return; }
    const prev = $("#cDev")?.value;
    const sel = devs.find((d) => d.id === prev) || devs[0];
    const out = S.consoleOut;
    el.innerHTML = `<div class="console"><div class="console-side">
        <div><label for="cDev">장비</label><select class="input" id="cDev">${devs.map((d) => `<option value="${esc(d.id)}" ${d.id === sel.id ? "selected" : ""}>${esc(d.name)} (${ROLE[d.role]})</option>`).join("")}</select></div>
        <div><label for="cCmd">조회 명령</label><input class="input mono" id="cCmd" autocomplete="off" spellcheck="false" placeholder="${esc(QUICK[sel.role][0])}"></div>
        <button class="btn primary" id="cRun"><span class="spin"></span>실행</button>
        <div><label>자주 쓰는 명령</label><div class="chips" id="cChips">${QUICK[sel.role].map((c) => `<button class="chip" data-cmd="${esc(c)}">${esc(c)}</button>`).join("")}</div></div>
        <p class="note">show / display로 시작하는 조회 명령만 실행합니다. 설정 변경, 재부팅, 삭제 등은 막혀 있습니다.</p>
      </div>
      <div class="term"><div class="term-head"><span id="cHead">${out ? esc(`${out.device} > ${out.command}  (${out.duration ?? "-"}초)`) : "명령을 실행하면 장비 응답이 그대로 표시됩니다"}</span>
        <button class="btn small" id="cCopy" ${out?.output ? "" : "disabled"}>복사</button></div>
        <pre id="cOut">${out ? esc(out.output || out.error || "") : ""}</pre></div></div>`;
    $("#cDev").addEventListener("change", () => renderConsole());
    $$("#cChips .chip").forEach((c) => c.addEventListener("click", () => { $("#cCmd").value = c.dataset.cmd; runConsole(); }));
    $("#cRun").addEventListener("click", runConsole);
    $("#cCmd").addEventListener("keydown", (e) => { if (e.key === "Enter") runConsole(); });
    $("#cCopy").addEventListener("click", () => copyText(S.consoleOut?.output || ""));
  }

  async function runConsole() {
    const dev = $("#cDev").value, cmd = $("#cCmd").value.trim() || $("#cCmd").placeholder;
    const btn = $("#cRun"); btn.classList.add("busy"); btn.disabled = true;
    $("#cHead").textContent = `${cmd} 실행 중…`;
    try {
      const r = await api("/api/console", { device: dev, command: cmd });
      const d = devicesOrdered().find((x) => x.id === dev);
      S.consoleOut = { device: d?.name || dev, command: r.command || cmd, output: r.ok ? r.output : "", error: r.ok ? "" : `[실행하지 못함] ${r.error}`, duration: r.duration };
    } catch (e) { S.consoleOut = { device: dev, command: cmd, output: "", error: `[실행하지 못함] ${e.message}` }; }
    renderConsole();
    $("#cCmd").value = cmd;
  }

  function drawDiag(box) {
    const d = S.diag;
    const head = `<div class="actions" style="justify-content:flex-start;margin-top:0">
        <button class="btn primary small" id="diagRun" ${d?.running ? "disabled" : ""}><span class="spin"></span>${d?.running ? "진단 중… (최대 1~2분)" : "접속 진단 실행"}</button>
        ${d?.result?.copy_text ? `<button class="btn small" id="diagCopy">결과 복사 (IP 일부 가림)</button>` : ""}</div>
      <p class="note">TCP 연결 → SSH 배너 → 암호 방식 → 인증 방식 → 로그인 → 로그인 직후 화면 → 실제 명령 순서로 시험합니다. 장비 설정은 바꾸지 않습니다.</p>`;
    let body = "";
    if (d?.result) {
      const res = d.result;
      body = `<p style="font-weight:650;color:${res.ok ? "var(--ok)" : "var(--crit)"}">${esc(res.summary)}</p>` +
        res.steps.map((s) => `<div class="diag-step ${s.ok === false ? "bad" : ""}"><span class="ic ${s.ok ? "ok" : s.ok === false ? "bad" : ""}">${s.ok ? "✓" : s.ok === false ? "✕" : "i"}</span>
          <b>${esc(s.name)}</b><div class="d">${esc(s.detail)}</div></div>`).join("") +
        (res.log ? `<details class="diag-log"><summary>상세 로그 보기</summary><pre>${esc(res.log)}</pre></details>` : "");
    } else if (d?.error) body = `<p class="err">${esc(d.error)}</p>`;
    box.innerHTML = head + body;
    $("#diagRun", box).classList.toggle("busy", !!d?.running);
    $("#diagRun", box).addEventListener("click", runDiag);
    $("#diagCopy", box)?.addEventListener("click", () => copyText(d.result.copy_text));
  }

  async function runDiag() {
    const id = S.drawer; if (!id) return;
    S.diag = { running: true };
    if (S.dtab === "diag") renderDrawer();
    try { S.diag = { result: await api("/api/diagnose", { device: id }) }; }
    catch (e) { S.diag = { error: e.message }; }
    if (S.drawer === id && S.dtab === "diag") renderDrawer();
  }

  function copyText(t) {
    const done = () => toast("복사했습니다.");
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(t).then(done, () => fallback());
    else fallback();
    function fallback() { const ta = document.createElement("textarea"); ta.value = t; document.body.appendChild(ta); ta.select(); try { document.execCommand("copy"); done(); } catch { toast("복사하지 못했습니다."); } ta.remove(); }
  }

  // ------------------------------------------------------------------ 설정
  function renderSettings() {
    const el = $("#tab-settings");
    const st = S.st; if (!st) return;
    const cfg = st.config;
    const creds = st.credentials || {};
    const credCard = Object.entries(st.credential_profiles).map(([p, label]) => {
      const c = creds[p];
      return `<form class="cred" data-profile="${p}">
        <div class="cred-head"><b>${esc(label)}</b><span class="badge ${c ? "ok" : "unknown"}">${c ? `입력됨: ${esc(c.username)}${c.storage_uncertain ? " (PC 저장 확인 필요)" : c.remembered ? " (PC에 저장)" : ""}` : "미입력"}</span></div>
        <div class="form-row">
          <div class="field"><label>아이디</label><input class="input" name="username" autocomplete="username" value="${esc(c?.username || "")}"></div>
          <div class="field"><label>비밀번호</label><input class="input" name="password" type="password" autocomplete="current-password" placeholder="${c ? "변경할 때만 입력" : ""}"></div>
        </div>
        <label class="check"><input type="checkbox" name="remember" ${c?.remembered || (!c && st.keyring) ? "checked" : ""} ${st.keyring ? "" : "disabled"}> Windows 자격 증명 관리자에 저장 (재시작 후에도 자동 점검 유지)</label>
        ${st.keyring ? "" : `<p class="note">이 PC에서는 자격 증명 관리자를 사용할 수 없어 프로그램이 켜져 있는 동안만 기억합니다.</p>`}
        ${st.credential_storage_uncertain ? `<p class="err">PC에 저장된 계정 상태를 확인할 수 없습니다. 계정 지우기를 완료한 뒤 다시 저장하세요.</p>` : ""}
        <div class="actions" style="margin-top:0"><button type="button" class="btn ghost small danger" data-clear ${c || st.credential_storage_uncertain ? "" : "hidden"}>계정 지우기</button><button class="btn small primary">계정·설정 저장</button></div>
      </form>`;
    }).join("");

    const bt = st.baseline_times || {};
    const devList = S.devDirty && $("#devBody") ? readDevRows() : cfg.devices;  // 저장 전 입력은 화면을 다시 그려도 유지
    const devRows = devList.map((d, i) => devRow(d, i, bt[d.id])).join("");
    const sc = cfg.schedule, th = cfg.thresholds;
    const intervals = [15, 30, 60, 120, 180, 240, 360, 720];
    if (!intervals.includes(sc.interval_minutes)) intervals.push(sc.interval_minutes);
    el.innerHTML = `<div class="settings">
      <div class="card"><h3>접속 계정</h3><p>백본·MM·WLC 모두 이 계정 하나로 접속합니다. 비밀번호는 설정 파일, 점검 기록, 보고서 어디에도 저장하지 않습니다.</p><div class="cred-grid">${credCard}</div></div>

      <div class="card"><h3>점검 장비</h3><p>한 번 점검할 때 아래 장비를 동시에 접속합니다. 대표 WLC에서 클러스터 명령(group-membership, load distribution)을 실행하고, 실패하면 다른 WLC에서 다시 시도합니다.</p>
        <div style="overflow-x:auto"><table class="dev-table"><thead><tr><th>사용</th><th>구분</th><th>이름</th><th>접속 IP</th><th>접속 방식</th><th>포트</th><th>클러스터</th><th>대표 WLC</th><th>기준값</th><th></th></tr></thead><tbody id="devBody">${devRows}</tbody></table></div>
        <div class="actions" style="justify-content:space-between"><span style="display:flex;gap:8px"><button class="btn small" id="addDev">장비 추가</button><button class="btn small" id="bulkDev">여러 대 한 번에 추가</button>
        <button class="btn small" id="importOld">기존 백본 도구 설정 가져오기</button><input type="file" id="importFile" accept=".yaml,.yml,.txt" hidden></span>
        <datalist id="clusterNames"><option value="IN"><option value="OUT"></datalist>
        <button class="btn small ghost" id="resetAll">전체 기준값 다시 잡기</button></div>
        <div id="bulkBox" class="bulk" hidden>
          <label for="bulkText">한 줄에 한 대씩: 구분(백본/MM/WLC), 이름, IP[:포트], WLC는 클러스터(IN/OUT)도. 엑셀에서 칸을 복사해 붙여 넣어도 됩니다.</label>
          <textarea class="input mono" id="bulkText" rows="7" spellcheck="false" placeholder="백본	백본 1호기	192.0.2.1&#10;MM	MM-01	192.0.2.10&#10;WLC	WLC-IN-01	198.51.100.11	IN&#10;WLC	WLC-OUT-01	198.51.100.15	OUT"></textarea>
          <div class="actions" style="justify-content:flex-start;margin-top:8px"><button class="btn small primary" id="bulkApply">표에 추가</button><span class="note" id="bulkNote"></span></div>
        </div>
        <p class="note">기준값: 백본의 UP 인터페이스, LACP Selected 수, OSPF 인접, VRRP 역할, 전원·팬 상태와 WLC Connection-Type을 첫 점검 때 저장해 두고 이후 달라지면 알립니다. 계획된 변경 작업 뒤에는 기준값을 다시 잡으세요.</p></div>

      <div class="card"><h3>자동 점검</h3><p>정해진 주기로 전체 장비를 점검하고, 끝나면 엑셀 보고서 저장과 완료 알림까지 합니다.</p>
        <div class="form-row" style="max-width:720px">
          <label class="check"><input type="checkbox" id="sEnabled" ${sc.enabled ? "checked" : ""}> 자동 점검 켜기</label>
          <div class="field"><label for="sInterval">주기</label><select class="input" id="sInterval">${intervals.sort((a, b) => a - b).map((m) => `<option value="${m}" ${m === sc.interval_minutes ? "selected" : ""}>${m < 60 ? `${m}분` : `${m / 60}시간`}마다</option>`).join("")}</select></div>
          <label class="check"><input type="checkbox" id="sAlign" ${sc.align_to_clock ? "checked" : ""}> 정각에 맞춰 실행 (예: 1시간마다 → 매시 00분)</label>
          <label class="check"><input type="checkbox" id="sBackground" ${sc.background !== false ? "checked" : ""}> 창을 닫아도 자동 점검 (Windows 작업 스케줄러)</label>
        </div>
        <p class="note" style="margin-top:12px">${bgNote(st)}</p></div>

      <div class="card"><h3>보고서·알림</h3><p>점검이 끝날 때마다 엑셀 보고서를 저장하고, 화면 오른쪽 아래에 결과를 알려 줍니다.</p>
        <div class="form-row" style="max-width:860px">
          <label class="check"><input type="checkbox" id="rExcel" ${cfg.report.excel_auto ? "checked" : ""}> 점검마다 엑셀 보고서 자동 저장</label>
          <label class="check"><input type="checkbox" id="rNotify" ${cfg.report.notify ? "checked" : ""}> 점검 완료 알림 (화면 오른쪽 아래)</label>
        </div>
        <div class="form-row" style="max-width:860px;margin-top:10px">
          <div class="field" style="grid-column: span 2"><label for="rFolder">보고서 저장 폴더 (비우면 기본 폴더)</label>
            <input class="input" id="rFolder" value="${esc(cfg.report.folder || "")}" placeholder="${esc(st.report_folder || "")}" spellcheck="false"></div>
        </div>
        <div class="actions" style="justify-content:flex-start">
          <button class="btn small" id="rOpen">보고서 폴더 열기</button>
          <button class="btn small" id="rTest">알림 테스트</button><span class="note" id="rNote"></span></div>
        <p class="note">엑셀 시트: 요약 · 백본 CPU·메모리(Last 5 sec / 1 min / 5 min, Free) · 컨트롤러 CPU·메모리(user / system / used) · 백본 로그 · 백본 VRRP · 점검 항목 · 원본 출력.
          파일 이름은 무선망점검_날짜_시각_run회차.xlsx이며 점검 기록 보관 기간이 지나면 지웁니다.</p></div>

      <div class="card"><h3>접속 대기 시간</h3><p>백본과 컨트롤러(MM·WLC)를 따로 정합니다. ‘응답 없음’이나 ‘시간 초과’가 나오는 쪽만 늘리세요. 응답 없는 장비는 이 시간만큼 기다린 뒤 ‘확인 불가’로 표시합니다. 장비 한 대가 ‘접속 대기×2 + 명령 대기×3’(최소 5분)을 넘기면 그 장비만 중단하고 점검을 끝내, ‘점검 중’에 멈춰 있지 않습니다.</p>
        <table class="dev-table" style="max-width:760px"><thead><tr><th></th><th>접속 대기 (SSH 연결·로그인)</th><th>명령 응답 대기 (명령 1개당)</th></tr></thead><tbody>
          <tr><td><b>백본</b></td>
            <td><select class="input" id="sBbConn" aria-label="백본 접속 대기">${timeoutOpts([30, 60, 90, 120, 180, 240, 300, 600], cfg.ssh.bb_connect_timeout, 120)}</select></td>
            <td><select class="input" id="sBbCmd" aria-label="백본 명령 응답 대기">${timeoutOpts([30, 60, 90, 120, 180, 300, 600], cfg.ssh.bb_command_timeout, 120)}</select></td></tr>
          <tr><td><b>컨트롤러</b><div class="note">MM·WLC</div></td>
            <td><select class="input" id="sCtrlConn" aria-label="컨트롤러 접속 대기">${timeoutOpts([30, 60, 90, 120, 180, 240, 300, 600], cfg.ssh.ctrl_connect_timeout, 60)}</select></td>
            <td><select class="input" id="sCtrlCmd" aria-label="컨트롤러 명령 응답 대기">${timeoutOpts([30, 60, 90, 120, 180, 300, 600], cfg.ssh.ctrl_command_timeout, 60)}</select></td></tr>
        </tbody></table>
        <div class="form-row" style="max-width:360px;margin-top:12px">
          <div class="field"><label for="sRetry">접속 실패 시 재시도 (공통)</label><select class="input" id="sRetry">${[0, 1, 2, 3].map((n) => `<option value="${n}" ${n === cfg.ssh.retries ? "selected" : ""}>${n ? `${n}회` : "안 함"}</option>`).join("")}</select></div>
        </div></div>

      <div class="card"><h3>판단 기준</h3><p>CPU·메모리는 주의/장애 두 단계로 판단합니다. Client 분배는 한 WLC의 Active Client가 다른 WLC 중앙값의 일정 비율보다 낮을 때 주의로 봅니다.</p>
        <div class="form-row">
          ${numField("cpu_warn", "CPU 주의 (%)", th.cpu_warn)}${numField("cpu_crit", "CPU 장애 (%)", th.cpu_crit)}
          ${numField("mem_warn", "메모리 주의 (%)", th.mem_warn)}${numField("mem_crit", "메모리 장애 (%)", th.mem_crit)}
          ${numField("client_ratio_pct", "Client 낮음 비율 (%)", th.client_ratio_pct)}${numField("client_min_total", "판단 최소 전체 Client", th.client_min_total)}
        </div></div>

      <div class="card"><h3>원본 확인용 추가 명령</h3><p>여기 적은 명령은 매 점검마다 함께 실행해 원본 출력만 보관합니다(판단에는 쓰지 않음). 한 줄에 하나씩, show/display 조회 명령만 적으세요.</p>
        <div class="form-row">${["BB", "MM", "WLC"].map((r) => `<div class="field"><label>${ROLE[r]}</label><textarea class="input mono" rows="4" data-extra="${r}" spellcheck="false">${esc((cfg.extra_commands[r] || []).join("\n"))}</textarea></div>`).join("")}</div></div>

      <div class="card"><div class="form-row" style="max-width:560px">
          <div class="field"><label for="sSite">화면 제목(사업장 이름)</label><input class="input" id="sSite" value="${esc(cfg.site_name)}"></div>
          ${numField("retention_days", "점검 기록 보관 (일)", cfg.retention_days, "sRetention")}
        </div>
        <div class="actions"><span class="err" id="saveErr"></span><button class="btn primary" id="saveCfg">설정 저장</button></div></div>
    </div>`;

    $$(".cred", el).forEach((f) => f.addEventListener("submit", async (e) => {
      e.preventDefault();
      await saveSettings();
    }));
    $$(".cred [data-clear]", el).forEach((b) => b.addEventListener("click", async () => {
      if (S.savingSettings) return;
      const f = b.closest(".cred"), p = f.dataset.profile;
      S.savingSettings = true; b.disabled = true;
      try {
        const result = await api("/api/credentials", { profile: p, clear: true });
        S.st.credentials = result.credentials; S.st.credential_storage_uncertain = false;
      } catch (err) {
        toast(err.message); if (err.rollbackFailed) showCredentialStorageUncertain();
        S.savingSettings = false; b.disabled = false; return;
      }
      // Keep unrelated unsaved settings in the form after clearing the account.
      $("[name=username]", f).value = ""; $("[name=password]", f).value = "";
      const badge = $(".badge", f); badge.textContent = "미입력"; badge.className = "badge unknown";
      $(".err", f)?.remove(); b.hidden = true; b.disabled = false;
      try { await refreshState(true); toast("계정을 지웠습니다. 다른 설정의 입력은 유지했습니다."); }
      catch { toast("계정은 지웠습니다. 상태를 확인하려면 화면을 새로고침하세요."); }
      S.savingSettings = false;
    }));
    $("#devBody").addEventListener("input", () => { S.devDirty = true; });
    $("#devBody").addEventListener("change", () => { S.devDirty = true; });
    $("#bulkDev").addEventListener("click", () => {
      const box = $("#bulkBox"); box.hidden = !box.hidden; if (!box.hidden) $("#bulkText").focus();
    });
    $("#bulkApply").addEventListener("click", () => {
      const lines = $("#bulkText").value.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
      const body = $("#devBody");
      let added = 0, updated = 0; const bad = [];
      lines.forEach((line) => {
        const ipm = line.match(/(\d{1,3}(?:\.\d{1,3}){3})(?::(\d+))?/);
        if (!ipm) { bad.push(line); return; }
        const roleTok = (line.match(/(백본|BB|backbone|MM|mobility|WLC|컨트롤러|controller)/i) || [""])[0].toLowerCase();
        const role = /백본|bb|backbone/.test(roleTok) ? "BB" : /mm|mobility/.test(roleTok) ? "MM" : /wlc|컨트롤러|controller/.test(roleTok) ? "WLC"
          : /백본|bb/i.test(line) ? "BB" : /mm/i.test(line) ? "MM" : "WLC";
        const name = line.replace(ipm[0], " ").split(/[\t,;]+/).map((x) => x.trim()).filter((x) => x && !/^(백본|BB|MM|WLC|컨트롤러|IN|OUT)$/i.test(x)).join(" ").trim() || ipm[1];
        const host = ipm[1], port = Number(ipm[2] || 22);
        const clm = line.match(/(?:^|[\s,;\t-])(IN|OUT)(?=$|[\s,;\t-])/i);
        const cluster = role === "WLC" && clm ? clm[1].toUpperCase() : "";
        const same = $$("#devBody tr").find((tr) => $("[data-f=host]", tr).value.trim() === host);
        if (same) {
          $("[data-f=role]", same).value = role; $("[data-f=name]", same).value = name; $("[data-f=port]", same).value = port;
          $("[data-f=protocol]", same).disabled = role !== "BB"; $("[data-f=cluster_primary]", same).disabled = role !== "WLC";
          $("[data-f=cluster]", same).disabled = role !== "WLC"; if (cluster) $("[data-f=cluster]", same).value = cluster; updated++;
        } else {
          body.insertAdjacentHTML("beforeend", devRow({ id: "", name, role, host, port, protocol: "ssh", enabled: true, cluster_primary: false, cluster }, body.children.length, null)); added++;
        }
      });
      bindDevRows(); S.devDirty = true;
      $("#bulkNote").textContent = `새로 ${added}대, 갱신 ${updated}대` + (bad.length ? ` · IP를 찾지 못한 줄 ${bad.length}개: ${bad.slice(0, 2).join(" / ")}` : "") + ". 아래 ‘설정 저장’을 누르면 적용됩니다.";
      if (added || updated) $("#bulkText").value = bad.join("\n");
    });
    $("#addDev").addEventListener("click", () => {
      const body = $("#devBody");
      body.insertAdjacentHTML("beforeend", devRow({ id: "", name: "", role: "WLC", host: "", port: 22, protocol: "ssh", enabled: true, cluster_primary: false }, body.children.length, null));
      bindDevRows(); S.devDirty = true;
      const tr = body.lastElementChild;
      tr.scrollIntoView({ behavior: "smooth", block: "center" });
      $("[data-f=role]", tr).focus();
      toast("새 줄에 구분·이름·IP를 넣고 아래 ‘설정 저장’을 누르세요.");
    });
    $("#importOld").addEventListener("click", () => $("#importFile").click());
    $("#importFile").addEventListener("change", async (ev) => {
      const file = ev.target.files[0]; if (!file) return;
      try {
        const r = await api("/api/import_backbone", { text: await file.text() });
        const body = $("#devBody");
        let added = 0, updated = 0;
        r.devices.forEach((d) => {
          const same = $$("#devBody tr").find((tr) => $("[data-f=host]", tr).value.trim() === d.host);
          if (same) {
            $("[data-f=role]", same).value = "BB"; $("[data-f=name]", same).value = d.name;
            $("[data-f=port]", same).value = d.port; $("[data-f=protocol]", same).disabled = false; $("[data-f=protocol]", same).value = d.protocol;
            same.dataset.deviceType = d.device_type; updated++;
          } else {
            body.insertAdjacentHTML("beforeend", devRow({ id: "", enabled: d.enabled, cluster_primary: false, ...d }, body.children.length, null)); added++;
          }
        });
        bindDevRows(); S.devDirty = true;
        $("#saveErr").textContent = "";
        toast(`기존 백본 도구에서 ${r.devices.length}대를 가져왔습니다(새로 ${added}, 갱신 ${updated}). 아래 ‘설정 저장’을 눌러 적용하세요.`);
      } catch (e) { toast(e.message); }
      ev.target.value = "";
    });
    $("#resetAll").addEventListener("click", async () => {
      try { await api("/api/baseline/reset", {}); toast("다음 점검 결과를 새 기준값으로 저장합니다."); await refreshState(); renderSettings(); } catch (err) { toast(err.message); }
    });
    $("#saveCfg").addEventListener("click", saveSettings);
    $("#rOpen").addEventListener("click", async () => { try { const r = await api("/api/open_reports", {}); $("#rNote").textContent = r.path; } catch (e) { toast(e.message); } });
    $("#rTest").addEventListener("click", async () => {
      $("#rNote").textContent = "알림을 보내는 중…";
      try { const r = await api("/api/test_notify", {}); $("#rNote").textContent = r.ok ? "알림을 보냈습니다. 화면 오른쪽 아래를 확인하세요." : (r.error || "이 PC에서는 Windows 알림을 띄울 수 없습니다."); }
      catch (e) { $("#rNote").textContent = e.message; }
    });
    bindDevRows();
  }

  function timeoutOpts(list, cur, def) {
    const all = [...new Set([...list, cur])].sort((a, b) => a - b);
    const fmt = (v) => (v < 60 ? `${v}초` : v % 60 ? `${Math.floor(v / 60)}분 ${v % 60}초` : `${v / 60}분`);
    return all.map((v) => `<option value="${v}" ${v === cur ? "selected" : ""}>${fmt(v)}${v === def ? " (기본)" : ""}</option>`).join("");
  }

  function numField(key, label, val, id) {
    return `<div class="field"><label for="${id || `t_${key}`}">${label}</label><input class="input num" type="number" min="0" step="1" id="${id || `t_${key}`}" value="${esc(val)}"></div>`;
  }
  function devRow(d, i, btime) {
    return `<tr data-id="${esc(d.id)}" data-device-type="${esc(d.device_type || "")}">
      <td class="c"><input type="checkbox" data-f="enabled" ${d.enabled ? "checked" : ""} aria-label="사용"></td>
      <td><select class="input" data-f="role">${["BB", "MM", "WLC"].map((r) => `<option value="${r}" ${d.role === r ? "selected" : ""}>${ROLE[r]}</option>`).join("")}</select></td>
      <td><input class="input" data-f="name" value="${esc(d.name)}" placeholder="예: 백본 3호기"></td>
      <td><input class="input mono" data-f="host" value="${esc(d.host)}" placeholder="192.0.2.101"></td>
      <td><select class="input" data-f="protocol" ${d.role === "BB" ? "" : "disabled"} title="Telnet은 백본(Comware)만 지원">
        <option value="ssh" ${d.protocol !== "telnet" ? "selected" : ""}>SSH</option><option value="telnet" ${d.protocol === "telnet" ? "selected" : ""}>Telnet</option></select></td>
      <td><input class="input num" data-f="port" type="number" min="1" max="65535" value="${esc(d.port || 22)}" style="width:80px"></td>
      <td><input class="input" data-f="cluster" list="clusterNames" value="${esc(d.cluster || "")}" placeholder="${d.role === "WLC" ? "IN / OUT" : ""}" ${d.role === "WLC" ? "" : "disabled"} style="width:90px" title="모델이 다른 WLC는 클러스터를 따로(예: IN, OUT)"></td>
      <td class="c"><input type="checkbox" data-f="cluster_primary" ${d.cluster_primary ? "checked" : ""} ${d.role === "WLC" ? "" : "disabled"} aria-label="대표 WLC" title="클러스터마다 1대: 이 WLC에서 클러스터 명령을 실행"></td>
      <td>${d.role !== "BB" ? `<span class="note">${d.role === "WLC" ? "클러스터 기준 공용" : "해당 없음"}</span>` : d.id ? `<button type="button" class="btn small ghost" data-reset="${esc(d.id)}" title="${btime ? `저장 ${full(btime)}` : "아직 없음"}">${btime ? "다시 잡기" : "미저장"}</button>` : `<span class="note">저장 후</span>`}</td>
      <td><button type="button" class="btn small ghost danger" data-del>삭제</button></td></tr>`;
  }
  function bindDevRows() {
    $$("#devBody tr").forEach((tr) => {
      const del = $("[data-del]", tr);
      if (!del.dataset.bound) { del.dataset.bound = 1; del.addEventListener("click", () => { tr.remove(); S.devDirty = true; }); }
      const role = $("[data-f=role]", tr);
      if (!role.dataset.bound) { role.dataset.bound = 1; role.addEventListener("change", () => {
        const rd = $("[data-f=cluster_primary]", tr); rd.disabled = role.value !== "WLC"; if (rd.disabled) rd.checked = false;
        const cl = $("[data-f=cluster]", tr); cl.disabled = role.value !== "WLC"; if (cl.disabled) cl.value = "";
        const pr = $("[data-f=protocol]", tr); pr.disabled = role.value !== "BB";
        if (pr.disabled && pr.value === "telnet") { pr.value = "ssh"; const po = $("[data-f=port]", tr); if (po.value === "23") po.value = "22"; }
      }); }
      const prim = $("[data-f=cluster_primary]", tr);
      if (!prim.dataset.bound) { prim.dataset.bound = 1; prim.addEventListener("change", () => {
        if (!prim.checked) return;  // 같은 클러스터의 다른 대표 표시는 해제(클러스터마다 1대)
        const mine = $("[data-f=cluster]", tr).value.trim();
        $$("#devBody tr").forEach((o) => { if (o !== tr && $("[data-f=cluster]", o).value.trim() === mine) $("[data-f=cluster_primary]", o).checked = false; });
      }); }
      const proto = $("[data-f=protocol]", tr);
      if (!proto.dataset.bound) { proto.dataset.bound = 1; proto.addEventListener("change", () => {
        const po = $("[data-f=port]", tr);
        if (proto.value === "telnet" && po.value === "22") po.value = "23";
        if (proto.value === "ssh" && po.value === "23") po.value = "22";
      }); }
      const rs = $("[data-reset]", tr);
      if (rs && !rs.dataset.bound) {
        rs.dataset.bound = 1;
        rs.addEventListener("click", async () => {
          try { await api("/api/baseline/reset", { device: rs.dataset.reset }); toast("다음 점검 결과를 이 장비의 새 기준값으로 저장합니다."); rs.textContent = "미저장"; } catch (err) { toast(err.message); }
        });
      }
    });
  }

  // Collect all changes first; one server request validates and commits them.
  function readCredentialChanges() {
    const saved = [], changes = [];
    let check = false;
    for (const f of $$("#tab-settings .cred")) {
      const fd = new FormData(f);
      const username = String(fd.get("username") || "").trim();
      const password = String(fd.get("password") || "");
      const remember = !!fd.get("remember");
      const label = S.st.credential_profiles[f.dataset.profile];
      const already = (S.st.credentials || {})[f.dataset.profile];
      if (!username && !password && !already) continue;
      if (!username) return { error: `${label}의 아이디를 입력하세요.` };
      if (!password && (!already || username !== already.username)) return { error: `${label}의 새 비밀번호를 입력하세요.` };
      if (!password && remember === !!already?.remembered && !S.st.credential_storage_uncertain) continue;
      changes.push({ profile: f.dataset.profile, username, password, remember });
      saved.push(label); check ||= !!password;
    }
    return { saved, changes, check, notes: [] };
  }

  async function afterCredentialsSaved(r) {
    try { await refreshState(true); renderSettings(); }
    catch { toast("계정과 설정은 저장했습니다. 상태를 확인하려면 화면을 새로고침하세요."); return; }
    const miss = missingProfiles();
    const head = `${r.saved.join(", ")}을 저장했습니다.` + (r.notes.length ? ` ${r.notes.join(" ")}` : "");
    if (miss.length) { toast(`${head} ${miss.map((p) => S.st.credential_profiles[p]).join(", ")}도 입력하세요.`); return; }
    if (S.st.engine.running) { toast(`${head} 진행 중인 점검이 끝나면 다음 점검부터 적용됩니다.`); return; }
    try { await api("/api/check", {}); toast(`${head} 바로 점검을 시작합니다.`); await refreshState(); schedulePoll(); }
    catch { toast(`${head} ‘지금 점검’을 눌러 확인하세요.`); }
  }

  // 장비 표 → 장비 목록(저장 전 입력값 포함)
  function readDevRows() {
    return $$("#devBody tr").map((tr) => {
      const g = (f) => $(`[data-f=${f}]`, tr);
      return { id: tr.dataset.id || "", enabled: g("enabled").checked, role: g("role").value, name: g("name").value.trim(), host: g("host").value.trim(), port: Number(g("port").value || 22), protocol: g("protocol").value, cluster_primary: g("cluster_primary").checked, cluster: g("cluster").value.trim(),
        device_type: (tr.dataset.deviceType || "").replace(/_telnet$/, "") + ((tr.dataset.deviceType || "") && g("protocol").value === "telnet" ? "_telnet" : "") };
    });
  }

  function showSaveError(msg) {
    $("#saveErr").textContent = msg;
    toast(`저장하지 못했습니다: ${msg}`);
    $$("#devBody tr").forEach((tr) => tr.classList.remove("row-err"));
    let tr = null;
    const m = msg.match(/(\d+)번째 장비/);
    if (m) tr = $$("#devBody tr").filter((x) => { const g = (f) => $(`[data-f=${f}]`, x); return g("host").value.trim() || g("name").value.trim(); })[Number(m[1]) - 1];
    if (!tr) tr = $$("#devBody tr").find((x) => { const n = $("[data-f=name]", x).value.trim(); return n && msg.startsWith(n + ":"); });
    if (tr) { tr.classList.add("row-err"); tr.scrollIntoView({ behavior: "smooth", block: "center" }); $("[data-f=host]", tr).focus(); }
    else $("#saveErr").scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function showCredentialStorageUncertain() {
    S.st.credential_storage_uncertain = true;
    $$("#tab-settings .cred").forEach((form) => {
      $("[data-clear]", form).hidden = false;
      let warning = $(".err", form);
      if (!warning) { warning = document.createElement("p"); warning.className = "err"; form.append(warning); }
      warning.textContent = "PC에 저장된 계정 상태를 확인할 수 없습니다. 계정 지우기를 완료한 뒤 다시 저장하세요.";
    });
  }

  async function saveSettings() {
    if (S.savingSettings) return;
    const cfg = JSON.parse(JSON.stringify(S.st.config));
    const rows = readDevRows();
    const half = rows.find((d) => (d.name && !d.host));
    if (half) { showSaveError(`${half.name}: 접속 IP를 입력하세요.`); return; }
    cfg.devices = rows.filter((d) => d.host || d.name);
    cfg.schedule = { enabled: $("#sEnabled").checked, interval_minutes: Number($("#sInterval").value), align_to_clock: $("#sAlign").checked, background: $("#sBackground").checked };
    Object.keys(cfg.thresholds).forEach((k) => { const i = $(`#t_${k}`); if (i) cfg.thresholds[k] = Number(i.value); });
    $$("[data-extra]").forEach((t) => { cfg.extra_commands[t.dataset.extra] = t.value.split("\n").map((s) => s.trim()).filter(Boolean); });
    const bad = Object.values(cfg.extra_commands).flat().find((c) => !/^(show|display)\s/i.test(c));
    if (bad) { showSaveError(`추가 명령은 show/display 조회 명령만 쓸 수 있습니다: ${bad}`); return; }
    cfg.ssh = { ...cfg.ssh, bb_connect_timeout: Number($("#sBbConn").value), bb_command_timeout: Number($("#sBbCmd").value),
      ctrl_connect_timeout: Number($("#sCtrlConn").value), ctrl_command_timeout: Number($("#sCtrlCmd").value), retries: Number($("#sRetry").value) };
    cfg.report = { excel_auto: $("#rExcel").checked, notify: $("#rNotify").checked, folder: $("#rFolder").value.trim() };
    cfg.site_name = $("#sSite").value.trim() || "무선망 통합 점검";
    cfg.retention_days = Number($("#sRetention").value || 30);
    const cr = readCredentialChanges();
    if (cr.error) { showSaveError(cr.error); return; }
    S.savingSettings = true;
    const buttons = $$("#tab-settings .cred button, #saveCfg");
    buttons.forEach((button) => { button.disabled = true; });
    let res;
    try {
      res = await api("/api/settings", { config: cfg, credentials: cr.changes });
    } catch (e) {
      showSaveError(e.message);
      if (e.rollbackFailed) showCredentialStorageUncertain();
      S.savingSettings = false; buttons.forEach((button) => { button.disabled = false; });
      return;
    }
    $("#saveErr").textContent = "";
    S.devDirty = false;
    const ds = res.config.devices, cnt = (r) => ds.filter((d) => d.role === r).length;
    const summary = `장비 ${ds.length}대(백본 ${cnt("BB")} · MM ${cnt("MM")} · WLC ${cnt("WLC")})와 설정을 저장했습니다.`;
    try {
      if (cr.check) { await afterCredentialsSaved(cr); renderAll(); }
      else { await refreshState(true); renderAll(); renderSettings(); toast(summary + " 다음 점검부터 적용됩니다."); }
    } catch {
      toast("계정과 설정은 저장했습니다. 상태를 확인하려면 화면을 새로고침하세요.");
    } finally {
      S.savingSettings = false; buttons.forEach((button) => { button.disabled = false; });
    }
  }

  // ------------------------------------------------------------------ 상세 서랍
  function openDrawer(id) {
    S.drawer = id; S.dtab = "checks"; S.rawCmd = null; S.diag = null;
    const dr = $("#drawer"); dr.classList.add("open"); dr.setAttribute("aria-hidden", "false");
    renderDrawer();
    setTimeout(() => $(".drawer-head [data-close]")?.focus(), 50);
  }
  function closeDrawer() { S.drawer = null; const dr = $("#drawer"); dr.classList.remove("open"); dr.setAttribute("aria-hidden", "true"); }
  $$("#drawer [data-close]").forEach((b) => b.addEventListener("click", closeDrawer));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && S.drawer) closeDrawer(); });
  $$(".drawer-tabs button").forEach((b) => b.addEventListener("click", () => { S.dtab = b.dataset.dtab; renderDrawer(); }));

  function renderDrawer() {
    if (!S.drawer) return;
    const cfgDev = (S.st?.config?.devices || []).find((d) => d.id === S.drawer);
    const r = devResult(S.drawer);
    const name = r?.name || cfgDev?.name || S.drawer;
    const lvl = r?.status || "unknown";
    $("#drawerTitle").innerHTML = `${esc(name)} <span class="badge ${lvl}">${r ? LV[lvl] : "기록 없음"}</span>`;
    const m = r?.metrics || {};
    $("#drawerSub").textContent = [cfgDev ? ROLE[cfgDev.role] : "", r?.host || cfgDev?.host, m.model, m.version ? `v${m.version}` : "", m.uptime != null ? `가동 ${fmtUp(m.uptime)}` : "", S.run ? `${full(S.run.started)} 점검` : ""].filter(Boolean).join("  |  ");
    $$(".drawer-tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.dtab === S.dtab)));
    const box = $("#drawerContent");
    if (S.dtab === "diag") return drawDiag(box);
    if (!r) { box.innerHTML = `<div class="empty"><b>이 회차에는 기록이 없습니다</b>‘지금 점검’을 누르면 결과가 여기에 표시됩니다.</div>`; return; }
    if (S.dtab === "checks") return drawChecks(box, r);
    if (S.dtab === "raw") return drawRaw(box, r);
    if (S.dtab === "diag") return drawDiag(box);
    return drawTrend(box, r);
  }

  function drawChecks(box, r) {
    const icon = { ok: "✓", info: "✓", warn: "!", crit: "✕", unknown: "?" };
    const sorted = [...r.checks].sort((a, b) => RANK[b.level] - RANK[a.level]);
    const credErr = r.checks.some((c) => c.key === "ssh" && c.source === "credential");
    box.innerHTML = (r.error ? `<p class="err" style="margin-top:0">${esc(r.error)}</p>` : "") +
      (credErr ? `<p><button class="btn primary small" data-gocred>계정 입력하기</button></p>`
        : (!r.connected ? `<p><button class="btn primary small" data-godiag>접속 진단 실행</button> <span class="note">SecureCRT는 되는데 여기서만 안 되면, 어느 단계에서 막히는지 확인합니다.</span></p>` : "")) + sorted.map((c) => `<div class="chk">
      <span class="ic ${c.level}" aria-label="${LV[c.level]}">${icon[c.level]}</span>
      <span class="lab">${esc(c.label)}</span>
      <div class="sum-col"><div class="sum">${esc(c.summary)}</div>
        ${c.evidence?.length ? `<div class="evid">${c.evidence.map(esc).join("\n")}</div>` : ""}
        ${c.command ? `<div class="src mono">${esc(c.command)}</div>` : ""}
        ${c.source ? `<div class="src">출처: ${esc(c.source)}</div>` : ""}</div>
      <span class="act">${c.cmd_id ? `<button class="btn small" data-raw="${esc(c.cmd_id)}" data-raw-device="${esc(c.source_id || r.id)}">원본</button>` : ""}</span>
    </div>`).join("") +
      `<div class="actions" style="justify-content:flex-start;margin-top:18px"><button class="btn small" data-console>이 장비에 직접 명령 실행</button></div>`;
    $$("[data-raw]", box).forEach((b) => b.addEventListener("click", () => { S.drawer = b.dataset.rawDevice || S.drawer; S.dtab = "raw"; S.rawCmd = b.dataset.raw; renderDrawer(); }));
    $("[data-gocred]", box)?.addEventListener("click", () => { closeDrawer(); gotoCredentials(); });
    $("[data-godiag]", box)?.addEventListener("click", () => { S.dtab = "diag"; renderDrawer(); runDiag(); });
    $("[data-console]", box).addEventListener("click", () => { const id = S.drawer; closeDrawer(); switchTab("console"); const s = $("#cDev"); if (s) { s.value = id; renderConsole(); } });
  }

  async function drawRaw(box, r) {
    const cmds = r.commands || [];
    if (!cmds.length) { box.innerHTML = `<div class="empty"><b>원본 출력이 없습니다</b>${esc(r.error || "장비에 접속하지 못했습니다.")}</div>`; return; }
    if (!S.rawCmd || !cmds.find((c) => c.cmd_id === S.rawCmd)) S.rawCmd = cmds[0].cmd_id;
    box.innerHTML = `<div class="raw-wrap"><div class="raw-list" role="tablist">${cmds.map((c) => `<button data-c="${esc(c.cmd_id)}" aria-selected="${c.cmd_id === S.rawCmd}"><span>${esc(c.label)}</span>${c.ok ? "" : `<span class="fail">실패</span>`}</button>`).join("")}</div>
      <div class="raw-pane"><div class="raw-tools"><input class="input" id="rawFind" placeholder="출력에서 찾기" spellcheck="false"><button class="btn small" id="rawCopy">복사</button></div>
      <div class="raw-cmd" id="rawCmdLine"></div><pre class="raw" id="rawPre">불러오는 중…</pre></div></div>`;
    $$(".raw-list button", box).forEach((b) => b.addEventListener("click", () => { S.rawCmd = b.dataset.c; drawRaw(box, r); }));
    const key = `${S.run.id}|${S.drawer}|${S.rawCmd}`;
    let raw = S.rawCache[key];
    if (!raw) {
      try { raw = await api(`/api/raw?run=${S.run.id}&device=${encodeURIComponent(S.drawer)}&cmd=${encodeURIComponent(S.rawCmd)}`); S.rawCache[key] = raw; }
      catch (e) { raw = { output: "", error: e.message, command: "" }; }
    }
    if (S.dtab !== "raw" || key !== `${S.run?.id}|${S.drawer}|${S.rawCmd}`) return;
    const meta = cmds.find((c) => c.cmd_id === S.rawCmd);
    $("#rawCmdLine").textContent = `> ${raw.command}${meta?.duration != null ? `   (${meta.duration}초)` : ""}${raw.error ? `   ${raw.error}` : ""}`;
    const show = (q) => {
      const text = raw.output || (raw.error ? `[출력 없음] ${raw.error}` : "");
      if (!q) { $("#rawPre").innerHTML = esc(text); return; }
      const re = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
      $("#rawPre").innerHTML = esc(text).replace(re, (mm) => `<mark>${mm}</mark>`);
      $("#rawPre mark")?.scrollIntoView({ block: "center" });
    };
    show("");
    $("#rawFind").addEventListener("input", (e) => show(e.target.value));
    $("#rawCopy").addEventListener("click", () => copyText(raw.output || ""));
  }

  async function drawTrend(box, r) {
    const hours = S.trendHours;
    let pts;
    if (hours === 24) pts = (S.trends[S.drawer] || []).filter((p) => p.t >= Date.now() / 1000 - 86400);
    else {
      if (!S.trend7) { try { S.trend7 = await api("/api/trends?hours=168"); } catch { S.trend7 = {}; } }
      pts = S.trend7[S.drawer] || [];
    }
    const th = S.st.config.thresholds;
    const chart = (key, label, warn, crit) => {
      const W = 680, H = 180, L = 34, R = 8, T = 10, B = 24;
      const vals = pts.filter((p) => p[key] != null);
      if (vals.length < 2) return `<div><b>${label}</b><p class="note">표시할 기록이 부족합니다.</p></div>`;
      const t0 = vals[0].t, t1 = vals[vals.length - 1].t || t0 + 1;
      const x = (t) => L + ((t - t0) / Math.max(1, t1 - t0)) * (W - L - R), y = (v) => T + (1 - Math.min(100, v) / 100) * (H - T - B);
      let g = [0, 25, 50, 75, 100].map((v) => `<line class="gl" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`).join("");
      g += `<line class="th-w" x1="${L}" x2="${W - R}" y1="${y(warn)}" y2="${y(warn)}"/><line class="th-c" x1="${L}" x2="${W - R}" y1="${y(crit)}" y2="${y(crit)}"/>`;
      const ticks = 6; for (let i = 0; i <= ticks; i++) { const t = t0 + ((t1 - t0) * i) / ticks; g += `<text x="${x(t)}" y="${H - 6}" text-anchor="middle">${hours > 24 ? md(t) + " " : ""}${hm(t)}</text>`; }
      const line = vals.map((p) => `${x(p.t).toFixed(1)},${y(p[key]).toFixed(1)}`).join(" ");
      const last = vals[vals.length - 1][key];
      const max = Math.max(...vals.map((p) => p[key]));
      return `<div><div style="display:flex;justify-content:space-between;align-items:baseline"><b>${label}</b><span class="note">현재 ${last}%  |  최고 ${max}%  |  주의 ${warn}% · 장애 ${crit}%</span></div>
        <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${label} 추이">${g}<polyline class="l1" points="${line}"/></svg></div>`;
    };
    box.innerHTML = `<div class="actions" style="justify-content:flex-start;margin-top:0">
        <button class="btn small ${hours === 24 ? "primary" : ""}" data-h="24">24시간</button><button class="btn small ${hours === 168 ? "primary" : ""}" data-h="168">7일</button></div>
      <div class="trend-box">${chart("cpu", "CPU 사용률", th.cpu_warn, th.cpu_crit)}${chart("mem", "메모리 사용률", th.mem_warn, th.mem_crit)}</div>`;
    $$("[data-h]", box).forEach((b) => b.addEventListener("click", () => { S.trendHours = Number(b.dataset.h); if (S.trendHours === 168) S.trend7 = null; drawTrend(box, r); }));
  }

  // ------------------------------------------------------------------ 탭 / 전체
  function switchTab(tab) {
    S.tab = tab;
    $$(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
    $$(".panel").forEach((p) => (p.hidden = p.id !== `tab-${tab}`));
    renderTab();
  }
  $$(".tabs button").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));
  document.addEventListener("click", (e) => { const g = e.target.closest("[data-goto]"); if (g) switchTab(g.dataset.goto); });

  function renderTab() {
    if (S.tab === "devices") renderDevices();
    else if (S.tab === "cluster") renderCluster();
    else if (S.tab === "history") renderHistory();
    else if (S.tab === "vrrp") renderVrrp();
    else if (S.tab === "console") renderConsole();
    else if (S.tab === "settings") renderSettings();
  }

  function renderAll() {
    renderBar(); renderVerdict(); renderTopo();
    // 설정 탭은 입력 중인 값을 지우지 않도록 자동 갱신하지 않음
    if (S.tab !== "settings" && S.tab !== "console") renderTab();
    const banner = $("#historyBanner");
    if (S.viewing && S.run) { banner.hidden = false; $("#historyText").textContent = `${full(S.run.started)} 회차 결과를 보고 있습니다. 최신 결과가 아닙니다.`; }
    else banner.hidden = true;
    const bad = S.run ? Object.values(S.run.devices).filter((d) => RANK[d.status] >= 2).length : 0;
    const devTab = $('.tabs [data-tab="devices"]');
    devTab.innerHTML = `장비 현황${bad ? `<span class="count">${bad}</span>` : ""}`;
    const vn = S.st?.vrrp_unacked || 0;
    $('.tabs [data-tab="vrrp"]').innerHTML = `VRRP 이력${vn ? `<span class="count">${vn}</span>` : ""}`;
    if (S.drawer) renderDrawer();
  }
  $("#backLatest").addEventListener("click", () => loadRun(null));

  $("#quitBtn").addEventListener("click", async () => {
    const bgOn = S.st?.background?.registered;
    if (!confirm(`프로그램을 끌까요?${bgOn ? "\n(작업 스케줄러가 등록되어 있어 꺼져 있어도 정해진 시간마다 자동 점검은 계속됩니다)" : "\n끄면 자동 점검도 멈춥니다."}`)) return;
    try { await api("/api/quit", {}); } catch { /* 종료되며 연결이 끊김 */ }
    document.body.innerHTML = `<div style="display:grid;place-items:center;height:100vh;font-size:18px;color:#5b6577">프로그램을 껐습니다. 이 탭을 닫아도 됩니다.<br><br>다시 켜려면 ‘웹 버전으로 실행’을 실행하세요.</div>`;
  });

  // 창 살아 있음 신호(창을 닫으면 프로그램이 완전히 종료되도록)
  const beat = () => api("/api/heartbeat", {}).catch(() => {});
  beat();
  setInterval(beat, 5000);
  window.addEventListener("pagehide", () => {
    try { navigator.sendBeacon(`/api/bye?t=${encodeURIComponent(window.NC_TOKEN)}`, ""); } catch { /* 무시 */ }
  });

  // 시작
  refreshState().then(schedulePoll);
  setInterval(renderBar, 5000);
})();
