const test = require('node:test');
const assert = require('node:assert/strict');
const O = require('../src/fluxlake/web/observatory.js');

test('model text cannot introduce executable markup or off-origin links',()=>{
  const html=O.renderMarkdown('## Evidence\n- **Observed** `count`\n- <img src=x onerror=alert(1)>\n- [unsafe](javascript:alert(1))\n- [external](https://attacker.example)\n- /api/workspace/overview\n```html\n<script>alert(1)</script>\n```');
  assert.ok(html.includes('<strong>Observed</strong>'));
  assert.ok(html.includes('<code>count</code>'));
  assert.ok(html.includes('href="/api/workspace/overview"'));
  assert.ok(html.includes('&lt;img'));
  assert.ok(!html.includes('<img')&&!html.includes('<script'));
  assert.ok(!html.includes('href="javascript:')&&!html.includes('href="https://'));
});

test('only fixed public evidence paths become markdown links',()=>{
  const html=O.renderMarkdown('[source](/api/workspace/gold?group=event_type) [private](/transactions) [inject](/api/workspace/overview"onclick="alert)');
  assert.ok(html.includes('href="/api/workspace/gold?group=event_type"'));
  assert.ok(!html.includes('href="/transactions"'));
  assert.ok(!html.includes('onclick="'));
});

test('record sorting preserves precise long identities and stable equal values',()=>{
  const rows=[{event_id:'9007199254740993999',actor:'same',index:0},{event_id:'9007199254740993001',actor:'same',index:1},{event_id:'9',actor:'other',index:2}];
  assert.deepEqual(O.sortRecords(rows,'event_id').map(r=>r.event_id),['9','9007199254740993001','9007199254740993999']);
  assert.deepEqual(O.sortRecords(rows,'actor').filter(r=>r.actor==='same').map(r=>r.index),[0,1]);
  assert.equal(rows[0].index,0);
});

test('native distributions derive counts and widths from supplied observations',()=>{
  const rows=[{event_type:'PushEvent',events:3},{event_type:'CreateEvent',events:1}];
  const stack=O.typeStack(rows),chart=O.composition(rows);
  assert.ok(stack.includes('width="75"')&&stack.includes('width="25"'));
  assert.ok(chart.includes('3 (75%)')&&chart.includes('1 (25%)'));
  assert.ok(chart.includes('/workspace/silver?event_type=PushEvent'));
  assert.ok(chart.includes('composition of 4 actual retained events'));
  assert.ok(O.composition([]).includes('No event types'));
});

test('untrusted dimension labels are escaped inside native SVG',()=>{
  const html=O.rankChart([{dimension:'<script>bad</script>',events:5}], 'repository');
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(html.includes('/workspace/silver?q='));
});
