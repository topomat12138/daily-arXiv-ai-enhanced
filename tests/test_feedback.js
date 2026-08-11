'use strict';

const assert = require('node:assert/strict');
const {
  STORAGE_KEY,
  STORAGE_VERSION,
  createFeedbackStore
} = require('../js/feedback.js');


class MockLocalStorage {
  constructor(initialValues = {}) {
    this.values = new Map(Object.entries(initialValues));
  }

  getItem(key) {
    return this.values.has(key) ? this.values.get(key) : null;
  }

  setItem(key, value) {
    this.values.set(key, String(value));
  }
}


function storedState(storage) {
  return JSON.parse(storage.getItem(STORAGE_KEY));
}


let assertions = 0;
function test(name, callback) {
  callback();
  assertions += 1;
  process.stdout.write(`ok ${assertions} - ${name}\n`);
}


test('empty localStorage loads as no feedback', () => {
  const store = createFeedbackStore(new MockLocalStorage());
  assert.deepEqual(store.load(), { version: STORAGE_VERSION, papers: {} });
  assert.equal(store.getLabel('2607.08845'), null);
});

test('null transitions to focus', () => {
  const store = createFeedbackStore(new MockLocalStorage());
  assert.equal(store.toggle('2607.08845', 'focus', '2026-07-13').label, 'focus');
});

test('null transitions to interested', () => {
  const store = createFeedbackStore(new MockLocalStorage());
  assert.equal(store.toggle('2607.08845', 'interested', '2026-07-13').label, 'interested');
});

test('interested switches to focus', () => {
  const store = createFeedbackStore(new MockLocalStorage());
  store.toggle('2607.08845', 'interested', '2026-07-13');
  assert.equal(store.toggle('2607.08845', 'focus', '2026-07-13').label, 'focus');
});

test('focus switches to interested', () => {
  const store = createFeedbackStore(new MockLocalStorage());
  store.toggle('2607.08845', 'focus', '2026-07-13');
  assert.equal(store.toggle('2607.08845', 'interested', '2026-07-13').label, 'interested');
});

test('clicking active focus again produces null', () => {
  const store = createFeedbackStore(new MockLocalStorage());
  store.toggle('2607.08845', 'focus', '2026-07-13');
  assert.equal(store.toggle('2607.08845', 'focus', '2026-07-13').label, null);
});

test('clicking active interested again produces null', () => {
  const store = createFeedbackStore(new MockLocalStorage());
  store.toggle('2607.08845', 'interested', '2026-07-13');
  assert.equal(store.toggle('2607.08845', 'interested', '2026-07-13').label, null);
});

test('only one feedback label exists at a time', () => {
  const storage = new MockLocalStorage();
  const store = createFeedbackStore(storage);
  store.toggle('2607.08845', 'focus', '2026-07-13');
  store.toggle('2607.08845', 'interested', '2026-07-13');
  const record = storedState(storage).papers['2607.08845'];
  assert.equal(record.label, 'interested');
  assert.equal(Object.hasOwn(record, 'focus'), false);
  assert.equal(Object.hasOwn(record, 'interested'), false);
});

test('cancellation persists a record with a null label', () => {
  const storage = new MockLocalStorage();
  const store = createFeedbackStore(storage);
  store.toggle('2607.08845', 'focus', '2026-07-13');
  store.toggle('2607.08845', 'focus', '2026-07-13');
  assert.equal(storedState(storage).papers['2607.08845'].label, null);
});

test('paper_id and source_date are preserved', () => {
  const store = createFeedbackStore(new MockLocalStorage());
  const record = store.toggle('2607.08845', 'focus', '2026-07-13');
  assert.equal(record.paper_id, '2607.08845');
  assert.equal(record.source_date, '2026-07-13');
});

test('updated_at is a valid generated ISO timestamp', () => {
  const store = createFeedbackStore(new MockLocalStorage());
  const timestamp = store.toggle('2607.08845', 'focus', '2026-07-13').updated_at;
  assert.equal(new Date(timestamp).toISOString(), timestamp);
});

test('state survives save and reload from localStorage', () => {
  const storage = new MockLocalStorage();
  createFeedbackStore(storage).toggle('2607.08845', 'interested', '2026-07-13');
  const reloadedStore = createFeedbackStore(storage);
  reloadedStore.load();
  assert.equal(reloadedStore.getLabel('2607.08845'), 'interested');
});

test('malformed JSON and malformed records do not crash loading', () => {
  const malformedStorage = new MockLocalStorage({ [STORAGE_KEY]: '{bad json' });
  assert.doesNotThrow(() => createFeedbackStore(malformedStorage).load());
  assert.deepEqual(createFeedbackStore(malformedStorage).load().papers, {});

  const validTimestamp = new Date().toISOString();
  const mixedStorage = new MockLocalStorage({
    [STORAGE_KEY]: JSON.stringify({
      version: STORAGE_VERSION,
      papers: {
        '2607.08845': {
          paper_id: '2607.08845',
          label: 'focus',
          source_date: '2026-07-13',
          updated_at: validTimestamp
        },
        broken: { label: 'dislike' }
      }
    })
  });
  const loaded = createFeedbackStore(mixedStorage).load();
  assert.equal(loaded.papers['2607.08845'].label, 'focus');
  assert.equal(Object.hasOwn(loaded.papers, 'broken'), false);
});

test('invalid labels cannot enter persistent state', () => {
  const storage = new MockLocalStorage();
  const store = createFeedbackStore(storage);
  store.toggle('2607.08845', 'focus', '2026-07-13');
  const before = storage.getItem(STORAGE_KEY);
  assert.throws(
    () => store.set('2607.08845', 'dislike', '2026-07-13'),
    /label must be focus, interested, or null/
  );
  assert.throws(
    () => store.toggle('2607.08845', null, '2026-07-13'),
    /requestedLabel must be focus or interested/
  );
  assert.equal(storage.getItem(STORAGE_KEY), before);
});

process.stdout.write(`FeedbackStore tests passed: ${assertions}\n`);
