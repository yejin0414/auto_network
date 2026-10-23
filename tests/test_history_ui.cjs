// Exercise the actual history/state functions with deferred API promises.
// No browser, server, equipment, or external package is required.
// Standalone: node tests/test_history_ui.cjs [path/to/web/app.js] [--only=load,refresh]
// A name, or its load/refresh/vrrp prefix, selects baseline regression cases.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const DEFAULT_SOURCE = path.join(__dirname, '../web/app.js');
const NOW = 1700000000;
const AUX = ['/api/trends?hours=48', '/api/events?limit=80', '/api/vrrp'];
const flush = () => new Promise(resolve => setImmediate(resolve));
const copy = value => JSON.parse(JSON.stringify(value));

function browserCode(sourcePath) {
  const source = fs.readFileSync(sourcePath, 'utf8');
  function section(start, end) {
    const from = source.indexOf(start), to = source.indexOf(end, from);
    assert.ok(from >= 0 && to > from, `Missing browser section: ${start}`);
    return source.slice(from, to);
  }
  // Keep every real S initializer, including request ownership counters. A
  // manually invented S would hide NaN/uninitialized-state regressions.
  const state = section('  const S = {', '  // ------------------------------------------------------------------ 유틸');
  const updates = section('  // ------------------------------------------------------------------ 데이터 갱신', '  let pollTimer;');
  const bar = section('  function renderBar()', '  function bgNote(');
  const vrrp = section('  async function loadVrrp()', '  function renderVrrp(');
  // Use the real empty-state retry branch. Once data exists, record the draw
  // rather than emulate the unrelated VRRP table and its event handlers.
  const vrrpRender = section('  function renderVrrp() {', '    const all = S.vrrp.items || [];')
    + '    recordVrrpDraw(S.vrrp);\n  }\n';
  return `${state}\n${updates}\n${bar}\n${vrrp}\n${vrrpRender}\n`
    + 'globalThis.historyUI = {S, refreshState, loadRun, loadVrrp, renderVrrp};';
}

function stateFor(id, extra = {}) {
  const {engine = {}, config = {}, ...rest} = extra;
  return {
    latest_run_id: id, storage_error: '', credentials: {}, credential_profiles: {},
    background: {}, web_mode: false, vrrp_unacked: 0,
    config: {site_name: `Site ${id}`, devices: [], schedule: {enabled: false, interval_minutes: 60}, ...config},
    engine: {now: NOW + (id || 0), running: false, demo: false, run_trigger: 'manual', last_error: '', ...engine},
    ...rest,
  };
}

function runFor(id) {
  return {id, started: NOW, finished: NOW + 1, trigger: 'manual', devices: {},
    summary: {overall: 'ok', counts: {ok: 0, warn: 0, crit: 0, unknown: 0}}};
}

function warningFor(id, text = `Warning ${id}`) {
  return {id, run_id: id, kind: 'new', level: 'warn', text, ts: NOW};
}

function fixture(code) {
  const requests = [], renders = [], notices = [], vrrpDraws = [], nodes = new Map();
  const aux = {trends: {}, events: [], vrrp: {items: [], unacked: 0}};
  let context, ui;
  const control = {holdAux: false};
  function element() {
    return {textContent: '', innerHTML: '', hidden: false, disabled: false,
      classList: {toggle() {}, add() {}, remove() {}}, setAttribute() {}};
  }
  const main = element();
  main.prepend = node => nodes.set(`#${node.id}`, node);
  nodes.set('main', main);
  function $(selector) {
    if (selector === '#storageBanner') return nodes.get(selector) || null;
    if (!nodes.has(selector)) nodes.set(selector, element());
    return nodes.get(selector);
  }
  function api(url, body) {
    assert.equal(body, undefined, 'history refresh must not write through the API');
    assert.ok(url === '/api/state' || /^\/api\/run(?:\?id=\d+)?$/.test(url) || AUX.includes(url),
      `Unexpected history API: ${url}`);
    let resolve, reject;
    const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
    const request = {url, claimed: false, settled: false,
      resolve(value) {assert.equal(this.settled, false, `Already settled: ${url}`); this.settled = true; resolve(value);},
      reject(error) {assert.equal(this.settled, false, `Already settled: ${url}`); this.settled = true; reject(error);}};
    requests.push(request);
    if (AUX.includes(url) && !control.holdAux) {
      request.claimed = true;
      request.resolve(copy(url === AUX[0] ? aux.trends : url === AUX[1] ? aux.events : aux.vrrp));
    }
    return promise;
  }
  class FixedDate extends Date { static now() { return NOW * 1000; } }
  context = vm.createContext({
    api, $, Date: FixedDate, DESKTOP: false,
    document: {title: '', createElement: () => element()},
    renderCredBanner() {}, renderTopo() {}, rel: seconds => String(seconds), hm: seconds => String(seconds),
    toast: message => notices.push(message),
    renderAll() {
      renders.push({run: ui.S.run?.id ?? null, viewing: ui.S.viewing,
        rawKeys: Object.keys(ui.S.rawCache), trends: copy(ui.S.trends),
        events: copy(ui.S.events), vrrp: copy(ui.S.vrrp)});
      context.renderBar();
    },
    recordVrrpDraw: value => vrrpDraws.push(copy(value)),
  });
  vm.runInContext(code, context, {filename: 'extracted-history-ui.js'});
  ui = context.historyUI;
  function find(url) {
    return requests.find(request => request.url === url && !request.claimed && !request.settled);
  }
  function take(url) {
    const request = find(url);
    assert.ok(request, `Expected pending API request: ${url}`);
    request.claimed = true;
    return request;
  }
  return {ui, context, S: ui.S, requests, renders, notices, vrrpDraws, nodes, aux, control, take, find,
    takeAux: () => AUX.map(take),
    runRequests: () => requests.filter(request => request.url.startsWith('/api/run'))};
}

function replyAux(requests, marker, events = []) {
  requests[0].resolve({marker});
  requests[1].resolve(events);
  requests[2].resolve({marker, items: [], unacked: 0});
}

async function settleLatest(f, id) {
  await flush();
  const request = f.find('/api/run');
  if (request) {f.take('/api/run').resolve(runFor(id)); await flush();}
}

async function refresh(f, state) {
  const pending = f.ui.refreshState();
  f.take('/api/state').resolve(state);
  await settleLatest(f, state.latest_run_id);
  await pending;
}

async function bootstrap(f, id = 10) {
  await refresh(f, stateFor(id));
  assert.equal(f.S.run.id, id);
  assert.equal(f.S.viewing, null);
  assert.equal(f.notices.length, 0, 'initial history load must not announce a new run');
}

async function showHistory(f, id) {
  const pending = f.ui.loadRun(id);
  f.take(`/api/run?id=${id}`).resolve(runFor(id));
  await pending;
  assert.equal(f.S.run.id, id);
  assert.equal(f.S.viewing, id);
}

const cases = [
  ['load_response_order', async make => {
    const f = make(); f.S.latestId = 20;
    const older = f.ui.loadRun(7), first = f.take('/api/run?id=7');
    const newer = f.ui.loadRun(8), second = f.take('/api/run?id=8');
    second.resolve(runFor(8)); await newer;
    const cache = {retained: 'raw for current selection'}; f.S.rawCache = cache;
    const renders = f.renders.length;
    first.resolve(runFor(7)); await older;
    assert.equal(f.S.run.id, 8); assert.equal(f.S.viewing, 8);
    assert.equal(f.S.rawCache, cache, 'stale success must not reset current raw cache');
    assert.equal(f.renders.length, renders, 'stale success must not rerender the old selection');
  }],
  ['load_stale_error', async make => {
    const f = make(); f.S.latestId = 20;
    const older = f.ui.loadRun(7), first = f.take('/api/run?id=7');
    const newer = f.ui.loadRun(8), second = f.take('/api/run?id=8');
    second.resolve(runFor(8)); await newer;
    const cache = {retained: 'raw for successful selection'}; f.S.rawCache = cache;
    const renders = f.renders.length;
    first.reject(Error('Old history unavailable')); await older;
    assert.equal(f.S.run?.id, 8); assert.equal(f.S.viewing, 8);
    assert.equal(f.S.rawCache, cache, 'stale failure must not clear current raw cache');
    assert.equal(f.renders.length, renders, 'stale failure must not render an empty result');
  }],
  ['refresh_latest_retry', async make => {
    const f = make(); await bootstrap(f);
    const failed = f.ui.refreshState(); f.take('/api/state').resolve(stateFor(11));
    await flush(); f.take('/api/run').reject(Error('Temporary run read failure')); await failed;
    const before = f.runRequests().length;
    await refresh(f, stateFor(11));
    assert.equal(f.runRequests().length, before + 1, 'unchanged latest ID must retry the failed run fetch');
    assert.equal(f.S.run?.id, 11); assert.equal(f.S.viewing, null);
  }],
  ['refresh_pending_history_selection', async make => {
    const f = make(); await bootstrap(f, 20); f.control.holdAux = true;
    const polling = f.ui.refreshState(); f.take('/api/state').resolve(stateFor(21));
    await flush(); const auxiliary = f.takeAux();
    const selection = f.ui.loadRun(7), selected = f.take('/api/run?id=7');
    const requestCount = f.runRequests().length;
    replyAux(auxiliary, 21); await flush();
    assert.equal(f.runRequests().length, requestCount, 'poll must not override a still-pending user selection');
    await polling;
    selected.resolve(runFor(7)); await selection;
    assert.equal(f.S.run.id, 7); assert.equal(f.S.viewing, 7);
  }],
  ['refresh_inflight_latest_selection', async make => {
    const f = make(); await bootstrap(f, 20);
    const polling = f.ui.refreshState(); f.take('/api/state').resolve(stateFor(21));
    await flush(); const latest = f.take('/api/run');
    await showHistory(f, 7);
    const cache = {retained: 'history raw'}; f.S.rawCache = cache;
    const renders = f.renders.length;
    latest.resolve(runFor(21)); await polling;
    assert.equal(f.S.run.id, 7); assert.equal(f.S.viewing, 7);
    assert.equal(f.S.rawCache, cache);
    assert.equal(f.renders.length, renders, 'late automatic run must not render over a selected history');
  }],
  ['refresh_history_selection_persists', async make => {
    const f = make(); await bootstrap(f, 20); await showHistory(f, 7);
    const count = f.runRequests().length;
    await refresh(f, stateFor(21)); await refresh(f, stateFor(21));
    assert.equal(f.runRequests().length, count, 'polling must not fetch over a displayed historical run');
    assert.equal(f.S.run.id, 7); assert.equal(f.S.viewing, 7); assert.equal(f.S.latestId, 21);
    const latest = f.ui.loadRun(null); f.take('/api/run').resolve(runFor(21)); await latest;
    assert.equal(f.S.run.id, 21); assert.equal(f.S.viewing, null);
  }],
  ['refresh_notification_rules', async make => {
    const f = make(); f.aux.events = [warningFor(10, 'Existing warning')]; await bootstrap(f);
    f.aux.events = [warningFor(11, 'New warning'), warningFor(10, 'Old warning'),
      {...warningFor(11, 'Recovered'), kind: 'recovery'}];
    await refresh(f, stateFor(11)); await refresh(f, stateFor(11));
    assert.deepEqual(f.notices, ['새 이상 1건: New warning']);
    f.aux.events = [];
    await refresh(f, stateFor(12)); await refresh(f, stateFor(12));
    assert.deepEqual(f.notices, ['새 이상 1건: New warning', '점검을 마쳤습니다.']);
    await refresh(f, stateFor(13, {engine: {run_trigger: 'auto'}}));
    assert.equal(f.notices.length, 2, 'normal automatic completion has no extra manual-completion toast');
  }],
  ['refresh_state_response_order', async make => {
    const f = make(); await bootstrap(f, 9);
    const older = f.ui.refreshState(), oldState = f.take('/api/state');
    const newer = f.ui.refreshState(), newState = f.take('/api/state');
    newState.resolve(stateFor(11)); await settleLatest(f, 11); await newer;
    const requests = f.requests.length;
    oldState.resolve(stateFor(10)); await flush();
    assert.equal(f.S.st.latest_run_id, 11); assert.equal(f.S.latestId, 11);
    assert.equal(f.S.st.config.site_name, 'Site 11'); assert.equal(f.S.clockOffset, 11);
    assert.equal(f.requests.length, requests, 'stale state must not start old-run auxiliary work');
    await older;
    assert.equal(f.S.run.id, 11); assert.equal(f.notices.length, 1);
  }],
  ['refresh_stale_failure_warning', async make => {
    const f = make(); await bootstrap(f);
    const older = f.ui.refreshState(), oldState = f.take('/api/state');
    await refresh(f, stateFor(10, {storage_error: 'Stored history requires attention',
      engine: {last_error: 'Lower priority engine warning'}}));
    const schedule = f.nodes.get('#schedText').textContent;
    assert.equal(f.nodes.get('#storageBanner').textContent, 'Stored history requires attention');
    assert.equal(f.nodes.get('#storageBanner').hidden, false);
    oldState.reject(Error('Stale network failure')); await older;
    assert.equal(f.nodes.get('#schedText').textContent, schedule, 'stale failure must not replace a fresh status');
    assert.equal(f.nodes.get('#storageBanner').textContent, 'Stored history requires attention');
    await refresh(f, stateFor(10, {engine: {last_error: 'Engine warning remains visible'}}));
    assert.equal(f.nodes.get('#storageBanner').textContent, 'Engine warning remains visible');
  }],
  ['refresh_aux_response_order', async make => {
    const f = make(); await bootstrap(f, 9); f.control.holdAux = true;
    const older = f.ui.refreshState(); f.take('/api/state').resolve(stateFor(10));
    await flush(); const oldAux = f.takeAux();
    const newer = f.ui.refreshState(); f.take('/api/state').resolve(stateFor(11));
    await flush(); const newAux = f.takeAux();
    replyAux(newAux, 11, [warningFor(11, 'Current warning')]);
    await settleLatest(f, 11); await newer;
    const requestCount = f.requests.length;
    replyAux(oldAux, 10, [warningFor(10, 'Stale warning')]); await flush();
    assert.equal(f.requests.length, requestCount, 'old auxiliary completion must not reload the screen');
    await older;
    assert.equal(f.S.trends.marker, 11); assert.equal(f.S.events[0].text, 'Current warning');
    assert.equal(f.S.vrrp.marker, 11); assert.equal(f.S.run.id, 11); assert.equal(f.S.latestId, 11);
    assert.deepEqual(f.notices, ['새 이상 1건: Current warning']);
  }],
  ['refresh_same_id_notification_owner', async make => {
    const f = make(); await bootstrap(f, 9); f.control.holdAux = true;
    const first = f.ui.refreshState(); f.take('/api/state').resolve(stateFor(10));
    await flush(); const auxiliary = f.takeAux();
    const second = f.ui.refreshState(); f.take('/api/state').resolve(stateFor(10));
    await settleLatest(f, 10); await second;
    assert.equal(f.notices.length, 0, 'completion must wait for its event data');
    replyAux(auxiliary, 10, [warningFor(10, 'One completion warning')]);
    await settleLatest(f, 10); await first;
    assert.deepEqual(f.notices, ['새 이상 1건: One completion warning']);
    const rendered = f.renders.at(-1);
    assert.equal(rendered.run, 10);
    assert.equal(rendered.trends.marker, 10, 'completed auxiliary data must reach the displayed run');
    assert.equal(rendered.events[0]?.text, 'One completion warning');
    assert.equal(rendered.vrrp.marker, 10);
    await refresh(f, stateFor(10));
    assert.equal(f.notices.length, 1, 'same-ID poll must not cancel or duplicate a pending completion notification');
  }],
  ['refresh_failure_modes', async make => {
    const f = make(); await bootstrap(f);
    const before = f.S.st;
    const ordinary = f.ui.refreshState(); f.take('/api/state').reject(Error('Ordinary refresh unavailable'));
    await ordinary;
    assert.equal(f.S.st, before);
    assert.equal(f.nodes.get('#schedText').textContent, '프로그램과 연결이 끊겼습니다');
    const error = Error('Strict refresh unavailable');
    const strict = f.ui.refreshState(true);
    const rejection = assert.rejects(strict, value => value === error);
    f.take('/api/state').reject(error); await rejection;
    assert.equal(f.S.st, before);
  }],
  ['refresh_strict_overlap', async make => {
    const f = make(); await bootstrap(f);
    const oldBackground = f.ui.refreshState(), oldState = f.take('/api/state');
    const strict = f.ui.refreshState(true), savedState = f.take('/api/state');
    const newBackground = f.ui.refreshState(), pendingState = f.take('/api/state');
    savedState.resolve(stateFor(10, {config: {site_name: 'Committed settings'}, engine: {now: NOW + 50}}));
    await strict;
    assert.equal(f.S.st.config.site_name, 'Committed settings', 'pending later poll must not discard strict success');
    oldState.resolve(stateFor(9, {config: {site_name: 'Old settings'}})); await flush();
    assert.equal(f.S.st.config.site_name, 'Committed settings', 'older background response must not undo strict success');
    await oldBackground;
    pendingState.reject(Error('Later ordinary poll unavailable')); await newBackground;
    assert.equal(f.S.st.config.site_name, 'Committed settings'); assert.equal(f.S.clockOffset, 50);
    assert.equal(f.S.latestId, 10); assert.equal(f.S.run.id, 10);
  }],
  ['refresh_stale_strict_failure', async make => {
    const f = make(); await bootstrap(f);
    const error = Error('Superseded strict request failed');
    const strict = f.ui.refreshState(true), strictState = f.take('/api/state');
    const rejection = assert.rejects(strict, value => value === error);
    await refresh(f, stateFor(10, {config: {site_name: 'Newer applied settings'}}));
    const schedule = f.nodes.get('#schedText').textContent;
    strictState.reject(error); await rejection;
    assert.equal(f.S.st.config.site_name, 'Newer applied settings');
    assert.equal(f.nodes.get('#schedText').textContent, schedule);
  }],
  ['vrrp_initial_render_overlap', async make => {
    for (const newerFirst of [false, true]) {
      const f = make(); f.control.holdAux = true; f.S.tab = 'vrrp';
      f.ui.renderVrrp(); const first = f.take('/api/vrrp');
      const background = f.ui.loadVrrp(), second = f.take('/api/vrrp');
      const olderData = {marker: 'older', items: [], unacked: 0};
      const newerData = {marker: 'newer', items: [], unacked: 0};
      if (newerFirst) {second.resolve(newerData); await background; first.resolve(olderData);}
      else {first.resolve(olderData);}
      await flush();
      assert.equal(f.requests.length, 2, 'initial VRRP completion must not recursively request a third load');
      assert.equal(f.S.vrrp?.marker, newerFirst ? 'newer' : 'older');
      assert.equal(f.vrrpDraws.at(-1)?.marker, newerFirst ? 'newer' : 'older');
      if (!newerFirst) {second.resolve(newerData); await background;}
      f.ui.renderVrrp();
      assert.equal(f.S.vrrp.marker, 'newer'); assert.equal(f.vrrpDraws.at(-1).marker, 'newer');
      assert.equal(f.requests.length, 2);
    }
  }],
];

async function runHistoryTests(sourcePath = DEFAULT_SOURCE, options = {}) {
  const code = browserCode(path.resolve(sourcePath));
  const only = typeof options.only === 'string' ? options.only.split(',') : options.only || [];
  const selected = cases.filter(([name]) => !only.length || only.some(value => name === value || name.startsWith(`${value}_`)));
  assert.ok(selected.length, `No history test matched: ${only.join(',')}`);
  const failures = [];
  for (const [name, test] of selected) {
    let timer;
    try {
      await Promise.race([
        test(() => fixture(code)),
        new Promise((_, reject) => {timer = setTimeout(() => reject(Error(`Unsettled synthetic promise: ${name}`)), 3000);}),
      ]);
    } catch (error) {failures.push({name, error});}
    finally {clearTimeout(timer);}
  }
  const result = {total: selected.length, passed: selected.length - failures.length,
    failed: failures.length, cases: selected.map(([name]) => name)};
  if (failures.length) {
    const error = new AggregateError(failures.map(({name, error}) => Error(`${name}: ${error.message}`, {cause: error})),
      `History UI: ${result.failed}/${result.total} cases failed (${failures.map(item => item.name).join(', ')})`);
    error.results = result;
    throw error;
  }
  console.log(`PASS: history UI ${result.passed} cases (request order, retry, selection, notifications, strict refresh, VRRP loading)`);
  return result;
}

module.exports = runHistoryTests;
module.exports.testNames = Object.freeze(cases.map(([name]) => name));
if (require.main === module) {
  const args = process.argv.slice(2), only = [];
  let sourcePath = DEFAULT_SOURCE, sourceGiven = false;
  for (const argument of args) {
    if (argument.startsWith('--only=')) only.push(...argument.slice(7).split(',').filter(Boolean));
    else if (argument !== '--list') {
      if (sourceGiven) throw Error(`Unexpected argument: ${argument}`);
      sourcePath = argument; sourceGiven = true;
    }
  }
  if (args.includes('--list')) console.log(module.exports.testNames.join('\n'));
  else runHistoryTests(sourcePath, {only}).catch(error => {console.error(error); process.exitCode = 1;});
}
