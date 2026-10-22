// Exercise the actual browser save functions without a server or equipment.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
function section(start, end) {
  const from = source.indexOf(start), to = source.indexOf(end, from);
  assert.ok(from >= 0 && to > from, `Missing browser function: ${start}`);
  return source.slice(from, to);
}
const code = section('  function readCredentialChanges()', '  async function afterCredentialsSaved(')
  + section('  function showCredentialStorageUncertain()', '  // ------------------------------------------------------------------ 상세 서랍');
const refreshCode = section('  async function refreshState(', '  async function loadRun(')
  + section('  async function afterCredentialsSaved(', '  // 장비 표');
const clearCode = section('    $$(".cred [data-clear]", el).forEach(', '    $("#devBody").addEventListener(');

function fixture() {
  const fields = {
    '#sEnabled': {checked: false}, '#sInterval': {value: '60'}, '#sAlign': {checked: true},
    '#sBackground': {checked: false}, '#t_cpu_warn': {value: '50'}, '#t_cpu_crit': {value: '70'},
    '#sBbConn': {value: '120'}, '#sBbCmd': {value: '120'}, '#sCtrlConn': {value: '60'},
    '#sCtrlCmd': {value: '60'}, '#sRetry': {value: '0'}, '#rExcel': {checked: false},
    '#rNotify': {checked: false}, '#rFolder': {value: ''}, '#sSite': {value: 'Synthetic site'},
    '#sRetention': {value: '30'}, '#saveErr': {textContent: ''}, '#schedText': {textContent: ''},
  };
  const clear = {hidden: true, disabled: false, addEventListener(type, handler) {this.click = handler;}};
  const form = {dataset: {profile: 'shared'}, values: {username: 'synthetic', password: 'new-synthetic', remember: true},
    clear, warning: null, append(node) {this.warning = node;}};
  clear.closest = () => form;
  const buttons = [{disabled: false}, {disabled: false}];
  const calls = [], errors = [], notices = [];
  let after = 0, refreshed = 0;
  const context = vm.createContext({
    S: {st: {config: {devices: [], thresholds: {cpu_warn: 50, cpu_crit: 70}, extra_commands: {}, ssh: {}},
      credentials: {shared: {username: 'synthetic', remembered: true}}, credential_profiles: {shared: '접속 계정'}},
      devDirty: true, savingSettings: false},
    FormData: class {constructor(f) {this.values = f.values;} get(k) {return this.values[k];}},
    $: (key, parent) => parent ? key === '[data-clear]' ? parent.clear : parent.warning : fields[key],
    $$: key => key === '#tab-settings .cred' ? [form] : key === '.cred [data-clear]' ? [clear] : key.includes('#saveCfg') ? buttons : [],
    document: {createElement: () => ({})}, el: {},
    readDevRows: () => [{id: 'bb', role: 'BB', name: 'Synthetic BB', host: '192.0.2.1'}],
    showSaveError: message => errors.push(message), toast: message => notices.push(message),
    afterCredentialsSaved: async () => {after++;},
    refreshState: async () => {refreshed++;}, renderAll() {}, renderSettings() {},
    api: async (url, body) => {calls.push({url, body}); return {config: body.config};},
  });
  vm.runInContext(code, context);
  return {context, form, clear, fields, buttons, calls, errors, notices,
    after: () => after, refreshed: () => refreshed};
}

(async () => {
  {
    const f = fixture();
    f.form.values.username = 'changed-user'; f.form.values.password = '';
    await f.context.saveSettings();
    assert.equal(f.calls.length, 0);
    assert.match(f.errors[0], /비밀번호/);
    assert.equal(f.context.S.devDirty, true);
  }
  {
    const f = fixture();
    f.context.api = async (url, body) => {f.calls.push({url, body}); throw Error('Invalid synthetic settings');};
    await f.context.saveSettings();
    assert.equal(f.calls.length, 1);
    assert.equal(f.calls[0].url, '/api/settings');
    assert.equal(f.calls[0].body.credentials[0].password, 'new-synthetic');
    assert.equal(f.calls[0].body.config.site_name, 'Synthetic site');
    assert.equal(f.after(), 0, 'failed save must not start a check');
    assert.equal(f.context.S.devDirty, true);
    assert.equal(f.form.values.password, 'new-synthetic', 'failed save must retain input');
    assert.equal(f.context.S.savingSettings, false);
    assert.ok(f.buttons.every(b => !b.disabled));
  }
  {
    const f = fixture(); let finish;
    f.context.api = (url, body) => {f.calls.push({url, body}); return new Promise(resolve => {finish = resolve;});};
    const pending = f.context.saveSettings();
    assert.ok(f.buttons.every(b => b.disabled));
    await f.context.saveSettings();
    assert.equal(f.calls.length, 1, 'rapid double save must remain one transaction');
    finish({config: f.calls[0].body.config}); await pending;
    assert.equal(f.after(), 1);
    assert.equal(f.context.S.devDirty, false);
    assert.ok(f.buttons.every(b => !b.disabled));
  }
  {
    const f = fixture();
    f.form.values.password = ''; f.form.values.remember = false;
    await f.context.saveSettings();
    assert.equal(f.calls[0].body.credentials[0].password, '');
    assert.equal(f.calls[0].body.credentials[0].remember, false);
    assert.equal(f.after(), 0, 'remember toggle must not start an unsolicited check');
    assert.equal(f.refreshed(), 1);
  }
  {
    const f = fixture();
    f.form.values.password = '';
    f.context.refreshState = async () => {throw Error('Synthetic refresh failed');};
    await f.context.saveSettings();
    assert.equal(f.calls[0].body.credentials.length, 0);
    assert.equal(f.errors.length, 0, 'post-commit refresh failure is not a save failure');
    assert.match(f.notices[0], /저장했습니다/);
    assert.equal(f.context.S.savingSettings, false);
    assert.ok(f.buttons.every(b => !b.disabled));
  }
  {
    const f = fixture();
    f.context.api = async (url, body) => {
      f.calls.push({url, body});
      return {config: body.config, warning: '설정은 저장했지만 기준값 정리가 필요합니다.'};
    };
    await f.context.saveSettings();
    assert.equal(f.after(), 0, 'storage maintenance warning must not start a check');
    assert.equal(f.errors.length, 0, 'committed settings must not be reported as a failed save');
    assert.equal(f.context.S.devDirty, false);
    assert.match(f.fields['#saveErr'].textContent, /기준값 정리/);
    assert.match(f.notices[0], /설정은 저장했지만/);
  }
  {
    const f = fixture();
    vm.runInContext(refreshCode, f.context);
    let settingsRendered = 0;
    f.context.renderSettings = () => {settingsRendered++;};
    f.context.api = async (url, body) => {
      f.calls.push({url, body});
      if (url === '/api/state') throw Error('Synthetic refresh failed');
      assert.equal(url, '/api/settings', 'state failure must prevent check request');
      return {config: body.config};
    };
    await f.context.saveSettings();
    assert.deepEqual(f.calls.map(c => c.url), ['/api/settings', '/api/state']);
    assert.equal(settingsRendered, 0, 'failed refresh must preserve the settings form');
    assert.equal(f.form.values.password, 'new-synthetic');
    assert.equal(f.errors.length, 0);
    assert.match(f.notices[0], /저장했습니다/);
    await f.context.refreshState(); // ordinary background polling remains tolerant
    await assert.rejects(() => f.context.refreshState(true), /Synthetic refresh failed/);
  }
  for (const action of ['save', 'clear']) {
    const f = fixture();
    f.context.S.st.credentials = {};
    f.context.api = async (url, body) => {
      f.calls.push({url, body});
      throw Object.assign(Error('Synthetic rollback failed'), {rollbackFailed: true});
    };
    if (action === 'save') await f.context.saveSettings();
    else {vm.runInContext(clearCode, f.context); await f.clear.click();}
    assert.equal(f.context.S.st.credential_storage_uncertain, true);
    assert.equal(f.clear.hidden, false, `${action}: recovery control must stay visible`);
    assert.match(f.form.warning.textContent, /계정 지우기/);
    assert.equal(f.form.values.password, 'new-synthetic');
    assert.equal(f.context.S.devDirty, true);
    assert.equal(f.context.S.savingSettings, false);
    assert.equal(f.clear.disabled, false);
    assert.equal(f.after(), 0);
  }
  {
    const f = fixture();
    f.fields['#dbBackup'] = {disabled: false};
    f.fields['#dbBackupNote'] = {textContent: ''};
    vm.runInContext(section('  async function backupDatabase()', '  $("#excelBtn").addEventListener'), f.context);
    let finish;
    f.context.api = (url, body) => {
      f.calls.push({url, body});
      return new Promise(resolve => {finish = resolve;});
    };
    const pending = f.context.backupDatabase();
    await f.context.backupDatabase();
    assert.equal(f.calls.length, 1, 'a pending backup must not be duplicated');
    assert.equal(f.calls[0].url, '/api/backup');
    assert.equal(JSON.stringify(f.calls[0].body), '{}', 'backup must not accept a UI supplied path');
    finish({ok: true, path: 'synthetic/backups/history.sqlite3'}); await pending;
    assert.match(f.fields['#dbBackupNote'].textContent, /synthetic\/backups\/history.sqlite3/);
    assert.equal(f.fields['#dbBackup'].disabled, false);
    f.context.api = async () => {throw Error('Synthetic backup failure');};
    await f.context.backupDatabase();
    assert.match(f.fields['#dbBackupNote'].textContent, /백업 실패/);
    assert.doesNotMatch(f.fields['#dbBackupNote'].textContent, /저장했습니다/);
    assert.equal(f.fields['#dbBackup'].disabled, false);
  }
  console.log('PASS: settings UI validation, single transaction, duplicate save, real refresh failure, save/clear rollback recovery, storage warnings, managed backup');
})().catch(error => {console.error(error); process.exitCode = 1;});
