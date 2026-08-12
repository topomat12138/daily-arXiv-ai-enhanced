'use strict';

const assert = require('node:assert/strict');
const {
  SYNC_MARKER,
  MAX_BATCH_EVENTS,
  feedbackEventId,
  fetchRemoteEventIds,
  selectUnsynchronizedRecords,
  createIssuePayload,
  buildIssueTitle,
  buildIssueBody,
  buildIssueUrl
} = require('../js/feedback-sync.js');


const KNOWN_EVENT_ID = 'c90b6ceeb29ae15d126b22310819cc59e9ae9787e966e91b00c85eda7adecb0c';

function feedbackRecord(overrides = {}) {
  return {
    paper_id: '2607.08845',
    label: 'focus',
    source_date: '2026-07-13',
    updated_at: '2026-07-13T18:25:00.000Z',
    ...overrides
  };
}

const tests = [];
function test(name, callback) {
  tests.push({ name, callback });
}


test('deterministic event ID matches the cross-language test vector', async () => {
  assert.equal(await feedbackEventId(feedbackRecord()), KNOWN_EVENT_ID);
});

test('the same record always produces the same event ID', async () => {
  const record = feedbackRecord();
  assert.equal(await feedbackEventId(record), await feedbackEventId({ ...record }));
});

test('changing label changes the event ID', async () => {
  assert.notEqual(
    await feedbackEventId(feedbackRecord()),
    await feedbackEventId(feedbackRecord({ label: 'interested' }))
  );
});

test('changing updated_at changes the event ID', async () => {
  assert.notEqual(
    await feedbackEventId(feedbackRecord()),
    await feedbackEventId(feedbackRecord({ updated_at: '2026-07-13T18:25:01.000Z' }))
  );
});

test('null cancellation hashes and remains null in the payload', async () => {
  const cancellation = feedbackRecord({
    paper_id: '2607.09437',
    label: null,
    updated_at: '2026-07-14T01:10:00.000Z'
  });
  assert.equal(
    await feedbackEventId(cancellation),
    '4f82d7dd931fbf275686c1276677df2578dccdb580a78c301a018e4700f4eb30'
  );
  assert.equal(createIssuePayload([cancellation], {
    batchId: 'batch-1',
    generatedAt: '2026-08-11T22:30:00.000Z'
  }).events[0].label, null);
});

test('remote IDs remove already synchronized records', async () => {
  const synchronized = feedbackRecord();
  const unsynchronized = feedbackRecord({ paper_id: '2607.08846' });
  const selected = await selectUnsynchronizedRecords(
    [synchronized, unsynchronized],
    new Set([await feedbackEventId(synchronized)])
  );
  assert.deepEqual(selected, [unsynchronized]);
});

test('only records absent from the remote ledger remain', async () => {
  const records = [
    feedbackRecord({ paper_id: 'a', updated_at: '2026-07-13T18:25:02.000Z' }),
    feedbackRecord({ paper_id: 'b', updated_at: '2026-07-13T18:25:01.000Z' }),
    feedbackRecord({ paper_id: 'c', updated_at: '2026-07-13T18:25:03.000Z' })
  ];
  const remoteIds = new Set([
    await feedbackEventId(records[0]),
    await feedbackEventId(records[2])
  ]);
  assert.deepEqual(await selectUnsynchronizedRecords(records, remoteIds), [records[1]]);
});

test('a 404 feedback ledger is treated as empty', async () => {
  let requestedUrl = null;
  const ids = await fetchRemoteEventIds(
    async url => {
      requestedUrl = url;
      return { status: 404, ok: false, text: async () => '' };
    },
    { getDataUrl: path => `https://data.example/${path}` }
  );
  assert.equal(ids.size, 0);
  assert.equal(requestedUrl, 'https://data.example/feedback/events.jsonl');
});

test('malformed successful ledger data fails instead of becoming empty', async () => {
  await assert.rejects(
    fetchRemoteEventIds(
      async () => ({ status: 200, ok: true, text: async () => '{bad json\n' }),
      { getDataUrl: path => `https://data.example/${path}` }
    ),
    /Malformed feedback ledger JSON/
  );
});

test('a historical remote event without event_id is still recognized', async () => {
  const record = feedbackRecord();
  const ids = await fetchRemoteEventIds(
    async () => ({ status: 200, ok: true, text: async () => JSON.stringify(record) }),
    { getDataUrl: path => `https://data.example/${path}` }
  );
  assert.equal(ids.has(KNOWN_EVENT_ID), true);
});

test('batch size is capped at 20 events', () => {
  const records = Array.from({ length: 25 }, (_, index) => feedbackRecord({
    paper_id: `paper-${index}`,
    updated_at: `2026-07-13T18:25:${String(index).padStart(2, '0')}.000Z`
  }));
  assert.equal(createIssuePayload(records, { batchId: 'batch-1' }).events.length, MAX_BATCH_EVENTS);
  assert.equal(MAX_BATCH_EVENTS, 20);
});

test('batch records are ordered by updated_at ascending', () => {
  const later = feedbackRecord({ paper_id: 'later', updated_at: '2026-07-14T01:10:00.000Z' });
  const earlier = feedbackRecord({ paper_id: 'earlier', updated_at: '2026-07-13T18:25:00.000Z' });
  const payload = createIssuePayload([later, earlier], { batchId: 'batch-1' });
  assert.deepEqual(payload.events.map(event => event.paper_id), ['earlier', 'later']);
});

test('Issue title starts with the required feedback-sync prefix', () => {
  assert.equal(buildIssueTitle('batch-1'), '[feedback-sync] batch-1');
});

test('Issue body contains the exact marker', () => {
  const payload = createIssuePayload([feedbackRecord()], {
    batchId: 'batch-1',
    generatedAt: '2026-08-11T22:30:00.000Z'
  });
  assert.equal(buildIssueBody(payload).includes(SYNC_MARKER), true);
  assert.equal(SYNC_MARKER, '<!-- daily-arxiv-feedback-sync:v1 -->');
});

test('Issue events contain only permitted feedback fields', () => {
  const payload = createIssuePayload([
    { ...feedbackRecord(), title: 'must not leak', abstract: 'must not leak' }
  ], {
    batchId: 'batch-1',
    generatedAt: '2026-08-11T22:30:00.000Z'
  });
  assert.deepEqual(Object.keys(payload.events[0]).sort(), [
    'label', 'paper_id', 'source_date', 'updated_at'
  ]);
  const body = buildIssueBody(payload);
  assert.equal(body.includes('must not leak'), false);
});

test('Issue body contains no credentials or unrelated local data', () => {
  const body = buildIssueBody(createIssuePayload([feedbackRecord()], {
    batchId: 'batch-1',
    generatedAt: '2026-08-11T22:30:00.000Z'
  }));
  assert.equal(/github_token|oauth|password|cookie|abstract|authors/i.test(body), false);
});

test('Issue URL is built from repository configuration without a hardcoded owner', () => {
  let calls = 0;
  const url = new URL(buildIssueUrl({
    getIssuesUrl: () => {
      calls += 1;
      return 'https://github.example/configured/repository/issues';
    }
  }, '[feedback-sync] batch-1', 'body'));
  assert.equal(calls, 1);
  assert.equal(url.origin + url.pathname, 'https://github.example/configured/repository/issues/new');
  assert.equal(url.searchParams.get('title'), '[feedback-sync] batch-1');
  assert.equal(url.searchParams.get('body'), 'body');
});


(async () => {
  let assertions = 0;
  for (const { name, callback } of tests) {
    await callback();
    assertions += 1;
    process.stdout.write(`ok ${assertions} - ${name}\n`);
  }
  process.stdout.write(`Feedback sync tests passed: ${assertions}\n`);
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
