const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../src/facetide/static/app.js'), 'utf8');

function harness() {
  const fields = Object.fromEntries(['startDate', 'endDate', 'reviewConfirm', 'saveReview',
    'revisionNotice', 'stateReport', 'toast'].map(id => [id, {
      value: '', checked: true, disabled: false, style: {},
      classList: {add() {}, remove() {}},
    }]));
  fields.startDate.value = '2026-12-01'; fields.endDate.value = '2026-12-31';
  const requests = [];
  const context = vm.createContext({
    document: {getElementById: id => fields[id], querySelectorAll: () => []},
    window: {addEventListener() {}}, setTimeout() {}, clearTimeout() {}, URLSearchParams,
    fetch: async (...args) => {requests.push(args); throw Error('unexpected request');},
  });
  vm.runInContext(source, context);
  return {fields, requests, context};
}

test('saving a changed period cannot confirm the cached draft', async () => {
  const {context, fields, requests} = harness();
  vm.runInContext(`state.context={period_start:'2026-11-01',period_end:'2026-11-05',
    agent_handoff:{draft:{draft_id:'old'}}};`, context);
  await vm.runInContext('saveReview()', context);
  assert.equal(requests.length, 0);
  assert.equal(fields.reviewConfirm.checked, false);
  assert.equal(fields.saveReview.disabled, true);
});

test('date edits invalidate confirmation and revision', () => {
  const {context, fields} = harness();
  vm.runInContext(`state.context={};state.revisionOf='old';invalidateReviewPeriod()`, context);
  assert.equal(vm.runInContext('state.context', context), null);
  assert.equal(vm.runInContext('state.revisionOf', context), null);
  assert.equal(fields.reviewConfirm.checked, false);
});

test('late context responses cannot restore a changed period', async () => {
  const {context} = harness();
  vm.runInContext(`api=async()=>{
    $('endDate').value='2027-01-01';return {};
  }`, context);
  assert.equal(await vm.runInContext('loadContext()', context), null);
  assert.equal(vm.runInContext('state.context', context), null);
});
