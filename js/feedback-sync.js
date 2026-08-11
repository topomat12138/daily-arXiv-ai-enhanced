(function(root, factory) {
  let nodeCrypto = null;
  if (typeof module === 'object' && module.exports) {
    nodeCrypto = require('node:crypto');
  }

  const api = factory(root, nodeCrypto);

  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }

  if (root && typeof root.document !== 'undefined') {
    root.FeedbackSync = api;
  }
})(typeof window !== 'undefined' ? window : globalThis, function(root, nodeCrypto) {
  'use strict';

  const SYNC_MARKER = '<!-- daily-arxiv-feedback-sync:v1 -->';
  const MAX_BATCH_EVENTS = 20;
  const EVENT_FIELDS = ['paper_id', 'label', 'source_date', 'updated_at'];
  const EVENT_ID_PATTERN = /^[0-9a-f]{64}$/;

  function cloneRecord(record) {
    return {
      paper_id: record.paper_id,
      label: record.label,
      source_date: record.source_date,
      updated_at: record.updated_at
    };
  }

  function canonicalFeedbackEvent(record) {
    return [
      record.paper_id,
      record.label === null ? 'null' : record.label,
      record.source_date,
      record.updated_at
    ].join('\n');
  }

  async function feedbackEventId(record) {
    const canonical = canonicalFeedbackEvent(record);
    const webCrypto = root && root.crypto && root.crypto.subtle
      ? root.crypto
      : nodeCrypto && nodeCrypto.webcrypto;

    if (webCrypto && webCrypto.subtle) {
      const bytes = new TextEncoder().encode(canonical);
      const digest = await webCrypto.subtle.digest('SHA-256', bytes);
      return Array.from(new Uint8Array(digest))
        .map(byte => byte.toString(16).padStart(2, '0'))
        .join('');
    }

    if (nodeCrypto) {
      return nodeCrypto.createHash('sha256').update(canonical, 'utf8').digest('hex');
    }

    throw new Error('SHA-256 is unavailable in this browser');
  }

  function hasCoreFields(record) {
    return record !== null &&
      typeof record === 'object' &&
      !Array.isArray(record) &&
      typeof record.paper_id === 'string' &&
      (record.label === 'focus' || record.label === 'interested' || record.label === null) &&
      typeof record.source_date === 'string' &&
      typeof record.updated_at === 'string';
  }

  async function parseRemoteLedger(text) {
    const eventIds = new Set();
    const lines = String(text).split(/\r?\n/);

    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index].trim();
      if (!line) {
        continue;
      }

      let event;
      try {
        event = JSON.parse(line);
      } catch (error) {
        throw new Error(`Malformed feedback ledger JSON on line ${index + 1}`);
      }

      if (event && typeof event.event_id === 'string' && EVENT_ID_PATTERN.test(event.event_id)) {
        eventIds.add(event.event_id);
      } else if (hasCoreFields(event) && (event.event_id === undefined || event.event_id === null)) {
        eventIds.add(await feedbackEventId(event));
      } else {
        throw new Error(`Malformed feedback ledger event on line ${index + 1}`);
      }
    }

    return eventIds;
  }

  async function fetchRemoteEventIds(fetchImpl, dataConfig) {
    const response = await fetchImpl(
      dataConfig.getDataUrl('feedback/events.jsonl'),
      { cache: 'no-store' }
    );

    if (response.status === 404) {
      return new Set();
    }
    if (!response.ok) {
      throw new Error(`Feedback ledger request failed with status ${response.status}`);
    }

    return parseRemoteLedger(await response.text());
  }

  function compareRecords(left, right) {
    const timestampOrder = left.updated_at.localeCompare(right.updated_at);
    return timestampOrder || left.paper_id.localeCompare(right.paper_id);
  }

  async function selectUnsynchronizedRecords(records, remoteEventIds) {
    const unsynchronized = [];
    for (const record of records) {
      const eventId = await feedbackEventId(record);
      if (!remoteEventIds.has(eventId)) {
        unsynchronized.push(cloneRecord(record));
      }
    }
    return unsynchronized.sort(compareRecords);
  }

  function createBatchId() {
    if (root && root.crypto && typeof root.crypto.randomUUID === 'function') {
      return root.crypto.randomUUID();
    }
    if (nodeCrypto && typeof nodeCrypto.randomUUID === 'function') {
      return nodeCrypto.randomUUID();
    }
    const random = Math.random().toString(36).slice(2, 12);
    return `feedback-${Date.now().toString(36)}-${random}`;
  }

  function createIssuePayload(records, options = {}) {
    const sorted = records.map(cloneRecord).sort(compareRecords);
    const selected = sorted.slice(0, MAX_BATCH_EVENTS);
    return {
      schema_version: 1,
      batch_id: options.batchId || createBatchId(),
      generated_at: options.generatedAt || new Date().toISOString(),
      events: selected.map(cloneRecord)
    };
  }

  function buildIssueTitle(batchId) {
    return `[feedback-sync] ${batchId}`;
  }

  function buildIssueBody(payload) {
    return `${SYNC_MARKER}\n\n\`\`\`json\n${JSON.stringify(payload, null, 2)}\n\`\`\``;
  }

  function buildIssueUrl(dataConfig, title, body) {
    const issuesUrl = dataConfig.getIssuesUrl().replace(/\/+$/, '');
    const issueUrl = new URL(`${issuesUrl}/new`);
    issueUrl.searchParams.set('title', title);
    issueUrl.searchParams.set('body', body);
    return issueUrl.toString();
  }

  function getNotificationElement(documentRef) {
    let notification = documentRef.getElementById('feedbackSyncNotification');
    if (!notification) {
      notification = documentRef.createElement('div');
      notification.id = 'feedbackSyncNotification';
      notification.className = 'feedback-sync-notification';
      notification.setAttribute('role', 'status');
      notification.setAttribute('aria-live', 'polite');
      documentRef.body.appendChild(notification);
    }
    return notification;
  }

  function showNotification(documentRef, message, options = {}) {
    const notification = getNotificationElement(documentRef);
    if (notification.feedbackSyncTimer) {
      root.clearTimeout(notification.feedbackSyncTimer);
      notification.feedbackSyncTimer = null;
    }
    notification.className = `feedback-sync-notification visible ${options.type || ''}`.trim();
    notification.replaceChildren();

    const messageElement = documentRef.createElement('span');
    messageElement.className = 'feedback-sync-message';
    messageElement.textContent = message;
    notification.appendChild(messageElement);

    if (options.linkUrl) {
      const link = documentRef.createElement('a');
      link.className = 'feedback-sync-link';
      link.href = options.linkUrl;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = options.linkText || '打开 GitHub Issue';
      notification.appendChild(link);
    }

    const closeButton = documentRef.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'feedback-sync-close';
    closeButton.setAttribute('aria-label', '关闭同步通知');
    closeButton.textContent = '×';
    closeButton.addEventListener('click', () => notification.classList.remove('visible'));
    notification.appendChild(closeButton);

    if (!options.linkUrl && options.autoHide !== false) {
      notification.feedbackSyncTimer = root.setTimeout(() => {
        notification.classList.remove('visible');
        notification.feedbackSyncTimer = null;
      }, 4500);
    }
  }

  function confirmationMessage(batchCount, totalCount) {
    const lines = [
      '此仓库是公开的，提交后的 GitHub Issue 内容也会公开。',
      '载荷仅包含论文 ID，以及重点阅读、感兴趣或取消标记；不会发送 GitHub token 或任何凭据。',
      `将同步 ${batchCount} / ${totalCount} 条未同步标记。`
    ];
    if (totalCount > MAX_BATCH_EVENTS) {
      lines.push('本批次导入后，请再次点击“同步标记”同步剩余记录。');
    }
    lines.push('是否准备 GitHub Issue？');
    return lines.join('\n\n');
  }

  async function handleSyncClick(options) {
    const button = options.button;
    const documentRef = options.document;
    const feedbackStore = options.feedbackStore;
    const dataConfig = options.dataConfig;
    const fetchImpl = options.fetchImpl;
    const confirmImpl = options.confirmImpl;

    button.disabled = true;
    showNotification(documentRef, '正在检查同步状态…', { autoHide: false });

    try {
      const records = feedbackStore.getAll();
      if (records.length === 0) {
        showNotification(documentRef, '没有可同步的标记');
        return;
      }

      const remoteEventIds = await fetchRemoteEventIds(fetchImpl, dataConfig);
      const unsynchronized = await selectUnsynchronizedRecords(records, remoteEventIds);
      if (unsynchronized.length === 0) {
        showNotification(documentRef, '所有标记均已同步', { type: 'success' });
        return;
      }

      showNotification(documentRef, `发现 ${unsynchronized.length} 条未同步标记`, { autoHide: false });
      const batchCount = Math.min(unsynchronized.length, MAX_BATCH_EVENTS);
      if (!confirmImpl(confirmationMessage(batchCount, unsynchronized.length))) {
        showNotification(documentRef, '已取消同步准备');
        return;
      }

      const payload = createIssuePayload(unsynchronized);
      const title = buildIssueTitle(payload.batch_id);
      const body = buildIssueBody(payload);
      const issueUrl = buildIssueUrl(dataConfig, title, body);
      const remainingMessage = unsynchronized.length > MAX_BATCH_EVENTS
        ? ` 本批包含前 ${MAX_BATCH_EVENTS} 条；导入后请再次同步剩余记录。`
        : '';
      showNotification(
        documentRef,
        `GitHub Issue 已准备好。请打开并手动提交；打开页面不代表同步完成。${remainingMessage}`,
        {
          type: 'success',
          autoHide: false,
          linkUrl: issueUrl,
          linkText: '打开 GitHub Issue'
        }
      );
    } catch (error) {
      console.error('Unable to verify feedback synchronization state:', error);
      showNotification(documentRef, '无法读取同步状态，请稍后重试', { type: 'error' });
    } finally {
      button.disabled = false;
    }
  }

  function init(options = {}) {
    const documentRef = options.document || (root && root.document);
    if (!documentRef) {
      return false;
    }

    const button = documentRef.getElementById('feedbackSyncButton');
    const feedbackStore = options.feedbackStore || root.FeedbackStore;
    const dataConfig = options.dataConfig || root.DATA_CONFIG;
    const fetchImpl = options.fetchImpl || root.fetch.bind(root);
    const confirmImpl = options.confirmImpl || root.confirm.bind(root);
    if (!button || !feedbackStore || !dataConfig) {
      return false;
    }

    button.addEventListener('click', () => handleSyncClick({
      button: button,
      document: documentRef,
      feedbackStore: feedbackStore,
      dataConfig: dataConfig,
      fetchImpl: fetchImpl,
      confirmImpl: confirmImpl
    }));
    return true;
  }

  return {
    SYNC_MARKER: SYNC_MARKER,
    MAX_BATCH_EVENTS: MAX_BATCH_EVENTS,
    EVENT_FIELDS: EVENT_FIELDS,
    canonicalFeedbackEvent: canonicalFeedbackEvent,
    feedbackEventId: feedbackEventId,
    parseRemoteLedger: parseRemoteLedger,
    fetchRemoteEventIds: fetchRemoteEventIds,
    selectUnsynchronizedRecords: selectUnsynchronizedRecords,
    createIssuePayload: createIssuePayload,
    buildIssueTitle: buildIssueTitle,
    buildIssueBody: buildIssueBody,
    buildIssueUrl: buildIssueUrl,
    confirmationMessage: confirmationMessage,
    handleSyncClick: handleSyncClick,
    init: init
  };
});
