(function(root, factory) {
  const api = factory();

  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }

  if (root && typeof root.document !== 'undefined') {
    let storage = null;
    try {
      storage = root.localStorage;
    } catch (error) {
      storage = null;
    }
    root.FeedbackStore = api.createFeedbackStore(storage);
  }
})(typeof window !== 'undefined' ? window : globalThis, function() {
  'use strict';

  const STORAGE_KEY = 'arxivFeedback';
  const STORAGE_VERSION = 1;
  const VALID_LABELS = new Set(['focus', 'interested', null]);
  const TOGGLE_LABELS = new Set(['focus', 'interested']);

  function emptyState() {
    return { version: STORAGE_VERSION, papers: {} };
  }

  function isRecord(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
  }

  function isIsoTimestamp(value) {
    if (typeof value !== 'string') {
      return false;
    }

    const parsed = new Date(value);
    return !Number.isNaN(parsed.getTime()) && parsed.toISOString() === value;
  }

  function normalizeStoredState(value) {
    if (!isRecord(value) || value.version !== STORAGE_VERSION || !isRecord(value.papers)) {
      return emptyState();
    }

    const papers = {};
    Object.entries(value.papers).forEach(([paperId, record]) => {
      if (
        !paperId ||
        !isRecord(record) ||
        record.paper_id !== paperId ||
        !VALID_LABELS.has(record.label) ||
        typeof record.source_date !== 'string' ||
        !isIsoTimestamp(record.updated_at)
      ) {
        return;
      }

      papers[paperId] = {
        paper_id: paperId,
        label: record.label,
        source_date: record.source_date,
        updated_at: record.updated_at
      };
    });

    return { version: STORAGE_VERSION, papers: papers };
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function createFeedbackStore(storage) {
    let state = null;

    function load() {
      let parsed = null;
      try {
        const storedValue = storage && storage.getItem(STORAGE_KEY);
        parsed = storedValue ? JSON.parse(storedValue) : null;
      } catch (error) {
        parsed = null;
      }

      state = normalizeStoredState(parsed);
      return clone(state);
    }

    function ensureLoaded() {
      if (!state) {
        load();
      }
    }

    function persist() {
      try {
        if (storage) {
          storage.setItem(STORAGE_KEY, JSON.stringify(state));
        }
      } catch (error) {
        // Keep the in-memory state usable when browser storage is unavailable.
      }
    }

    function get(paperId) {
      ensureLoaded();
      const record = state.papers[String(paperId)];
      return record ? clone(record) : null;
    }

    function getLabel(paperId) {
      const record = get(paperId);
      return record ? record.label : null;
    }

    function set(paperId, label, sourceDate) {
      ensureLoaded();
      const normalizedPaperId = typeof paperId === 'string' ? paperId.trim() : '';
      if (!normalizedPaperId) {
        throw new TypeError('paperId must be a non-empty string');
      }
      if (!VALID_LABELS.has(label)) {
        throw new RangeError('label must be focus, interested, or null');
      }

      const existing = state.papers[normalizedPaperId];
      const normalizedSourceDate = typeof sourceDate === 'string' && sourceDate
        ? sourceDate
        : existing && existing.source_date;
      if (!normalizedSourceDate) {
        throw new TypeError('sourceDate must be a non-empty string');
      }

      const record = {
        paper_id: normalizedPaperId,
        label: label,
        source_date: normalizedSourceDate,
        updated_at: new Date().toISOString()
      };
      state.papers[normalizedPaperId] = record;
      persist();
      return clone(record);
    }

    function toggle(paperId, requestedLabel, sourceDate) {
      if (!TOGGLE_LABELS.has(requestedLabel)) {
        throw new RangeError('requestedLabel must be focus or interested');
      }

      const nextLabel = getLabel(paperId) === requestedLabel ? null : requestedLabel;
      return set(paperId, nextLabel, sourceDate);
    }

    return {
      load: load,
      get: get,
      getLabel: getLabel,
      set: set,
      toggle: toggle
    };
  }

  return {
    STORAGE_KEY: STORAGE_KEY,
    STORAGE_VERSION: STORAGE_VERSION,
    createFeedbackStore: createFeedbackStore
  };
});
