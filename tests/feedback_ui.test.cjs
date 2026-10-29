const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
// Execute the production handler without starting services or device control.
const source = html.slice(html.indexOf('  // Stars rating'), html.indexOf('  // Dropzone (FunScript)'));
function setup(fetch) {
  const buttons = [-5, 5].map(score => ({
    disabled: false, active: score === -5,
    getAttribute: () => String(score),
    addEventListener(_, callback) { this.click = callback; },
    classList: null,
  }));
  buttons.forEach(b => b.classList = {
    add() { b.active = true; }, remove() { b.active = false; }
  });
  const toasts = [];
  vm.runInNewContext(source, {
    document: {querySelectorAll: () => buttons, getElementById: () => ({value: '  Helpful ✓  '})},
    fetch, toast: message => toasts.push(message), console: {error() {}},
  });
  return {buttons, toasts};
}
test('payload, pending lock, success acknowledgement and selection', async () => {
  let complete, request;
  const {buttons, toasts} = setup((url, options) => {
    request = {url, options};
    return new Promise(resolve => complete = resolve);
  });
  const pending = buttons[1].click();
  assert.ok(buttons.every(b => b.disabled));
  assert.equal(request.url, '/api/feedback');
  assert.equal(request.options.method, 'POST');
  assert.equal(request.options.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(request.options.body), {score: 5, note: 'Helpful ✓'});
  await buttons[0].click(); // Even a programmatic repeat is ignored.
  assert.deepEqual(toasts, []);
  complete({ok: true, json: async () => ({ok: true})});
  await pending;
  assert.deepEqual(buttons.map(b => b.active), [false, true]);
  assert.ok(buttons.every(b => !b.disabled));
  assert.match(toasts[0], /Saved rating 5 to feedback log/);
});
for (const [name, response] of [
  ['HTTP failure', async () => ({ok: false})],
  ['network failure', async () => {throw Error('offline');}],
  ['application failure', async () => ({ok: true, json: async () => ({ok: false})})],
  ['invalid JSON', async () => ({ok: true, json: async () => {throw Error('invalid JSON');}})],
  ['missing acknowledgement', async () => ({ok: true, json: async () => ({})})],
]) test(name + ' preserves selection and allows retry', async () => {
  const {buttons, toasts} = setup(response);
  await buttons[1].click();
  assert.deepEqual(buttons.map(b => b.active), [true, false]);
  assert.ok(buttons.every(b => !b.disabled));
  assert.deepEqual(toasts, ['Failed to save feedback. Please try again.']);
});
