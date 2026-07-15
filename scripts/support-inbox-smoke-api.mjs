#!/usr/bin/env node
import crypto from 'node:crypto';
import http from 'node:http';

const port = Number(process.env.PORT || process.env.SUPPORT_INBOX_SMOKE_API_PORT || 5181);
const host = process.env.HOST || '127.0.0.1';
const apiUrl = `http://${host}:${port}`;
const now = '2026-07-05T10:30:00.000Z';

function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'authorization,content-type',
    'Access-Control-Allow-Methods': 'GET,POST,PATCH,PUT,DELETE,OPTIONS',
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(payload),
  });
  res.end(payload);
}

function html(res, status, body) {
  res.writeHead(status, {
    'Access-Control-Allow-Origin': '*',
    'Content-Type': 'text/html; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

function javascript(res, status, body) {
  res.writeHead(status, {
    'Access-Control-Allow-Origin': '*',
    'Content-Type': 'application/javascript; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

function empty(res, status = 204) {
  res.writeHead(status, {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'authorization,content-type',
    'Access-Control-Allow-Methods': 'GET,POST,PATCH,PUT,DELETE,OPTIONS',
  });
  res.end();
}

function text(value) {
  return typeof value === 'string' ? value : '';
}

function escapeHtml(value) {
  return text(value).replace(/[&<>"']/g, char => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[char]));
}

function baseIssue(overrides) {
  const status = text(overrides.status) || 'open';
  return {
    id: '',
    accountId: '',
    contactId: '',
    sourceEmailId: '',
    chatRecordId: '',
    chatId: '',
    status,
    workflowStatus: status === 'done' ? 'done' : status === 'ongoing' ? 'ongoing' : 'open',
    priority: 'normal',
    assigneeEmail: '',
    queueKey: 'support',
    queueName: 'Support',
    tags: [],
    accountName: '',
    accountDomain: '',
    contactEmail: '',
    contactName: '',
    subject: '',
    fromAddress: '',
    channel: 'email',
    source: 'email:support',
    aiSummary: '',
    activatedIntent: '',
    requiresHuman: true,
    pendingApprovalCount: 0,
    hasPendingApproval: false,
    pendingReplyApprovalCount: 0,
    hasPendingReplyApproval: false,
    pendingActionApprovalCount: 0,
    hasPendingActionApproval: false,
    failedDeliveryCount: 0,
    hasFailedDelivery: false,
    pendingDeliveryCount: 0,
    hasPendingDelivery: false,
    csatFeedbackCount: 0,
    lowCsatFeedbackCount: 0,
    hasLowCsatFeedback: false,
    latestCsatRating: 0,
    latestCsatComment: '',
    latestCsatReceivedAt: '',
    overdueSlaCount: 0,
    hasOverdueSla: false,
    nextSlaTargetAt: '',
    nextSlaEventType: '',
    needsResponse: false,
    latestMessageDirection: 'customer',
    latestCustomerMessageAt: now,
    latestAgentMessageAt: '',
    duplicateSuggestionCount: 0,
    topDuplicateScore: 0,
    topDuplicateIssueId: '',
    topDuplicateIssueSubject: '',
    duplicateReasons: [],
    messageCount: 1,
    actionLog: [],
    metadata: {},
    customFields: {},
    latestMessageAt: now,
    mergedIntoIssueId: '',
    mergedAt: '',
    mergedBy: '',
    mergeNote: '',
    created: now,
    updated: now,
    messages: [],
    draftReply: '',
    notes: [],
    slaEvents: [],
    portalSessions: [],
    assignmentHistory: [],
    watchers: [],
    outboundMessages: [],
    aiRuns: [],
    actionExecutions: [],
    activityEvents: [],
    channelWebhookEvents: [],
    csatFeedback: [],
    knowledgeGaps: [],
    knowledgeSuggestions: [],
    ...overrides,
  };
}

function outbound(overrides) {
  return {
    id: '',
    issueId: '',
    channel: 'email',
    toAddress: '',
    fromAddress: 'agent@example.com',
    subject: 'Re: Support request',
    body: '',
    status: 'draft',
    provider: 'manual_draft',
    providerMessageId: '',
    error: '',
    createdBy: 'agent@example.com',
    sentAt: '',
    metadata: {},
    attachments: [],
    created: now,
    updated: now,
    ...overrides,
  };
}

function actionExecution(overrides) {
  return {
    id: '',
    issueId: '',
    actionKey: '',
    label: '',
    type: 'ticket_update',
    status: 'pending',
    requestedBy: 'automation',
    result: {},
    error: '',
    metadata: {},
    startedAt: now,
    completedAt: '',
    created: now,
    updated: now,
    ...overrides,
  };
}

function activity(overrides) {
  return {
    id: '',
    issueId: '',
    eventType: '',
    actorEmail: 'automation',
    title: '',
    body: '',
    fromStatus: '',
    toStatus: '',
    fromPriority: '',
    toPriority: '',
    metadata: {},
    occurredAt: now,
    created: now,
    updated: now,
    ...overrides,
  };
}

const knowledgeArticle = {
  id: 'kb-api-outage',
  sourceIssueId: 'issue-discord-open',
  sourceUrl: 'https://kb.example.test/api-outage',
  visibility: 'public',
  public: true,
  title: 'API outage response checklist',
  body: 'Confirm current incident status, share workaround, and ask for request IDs before promising an ETA.',
  status: 'published',
  tags: ['incident', 'api'],
  metadata: { knowledgeMatch: { score: 0.93, terms: ['api', 'outage'] } },
  created: now,
  updated: now,
};

const knowledgeArticles = [knowledgeArticle];
const webChatSessions = [];
const launchProofRuns = [];
const automationRules = [
  {
    id: 'automation-sla-escalate',
    name: 'SLA breach escalation',
    active: true,
    trigger: 'sla_breached',
    conditions: { priorityIn: ['high', 'urgent'] },
    actions: [
      { type: 'add_note', body: 'SLA breached. Review owner, customer reply, and resolution path.' },
      { type: 'prepare_agent_reply', approvalRequired: true, question: 'Draft an urgent, approval-ready customer update for this SLA breach using the ticket context and knowledge base.' },
    ],
    lastRunAt: now,
    created: now,
    updated: now,
  },
];
const automationRuns = [];

const issues = [
  baseIssue({
    id: 'issue-discord-open',
    accountId: 'account-acme',
    contactId: 'contact-ana',
    sourceEmailId: 'discord:discord-main:G123:C123:m-1',
    chatId: 'discord:discord-main:G123:C123:m-1',
    status: 'open',
    workflowStatus: 'open',
    priority: 'urgent',
    assigneeEmail: '',
    queueKey: 'support',
    queueName: 'Support',
    tags: ['incident', 'api'],
    accountName: 'Acme Cloud',
    accountDomain: 'acme.test',
    contactEmail: 'discord:G123:U123',
    contactName: 'Ana Discord',
    subject: 'Discord incident: production API down',
    fromAddress: 'discord:G123:U123',
    channel: 'discord',
    source: 'discord-main',
    aiSummary: 'Customer reports production API errors from Discord. Agent prepared incident response and triage fields for human approval.',
    activatedIntent: 'incident_response',
    pendingApprovalCount: 3,
    hasPendingApproval: true,
    pendingReplyApprovalCount: 1,
    hasPendingReplyApproval: true,
    pendingActionApprovalCount: 2,
    hasPendingActionApproval: true,
    pendingDeliveryCount: 1,
    hasPendingDelivery: true,
    needsResponse: true,
    metadata: {
      externalProvider: 'discord',
      externalTicketKey: 'discord:discord-main:G123:C123:m-1',
    },
    messages: [
      {
        id: 'msg-discord-1',
        sourceMessageId: 'discord:discord-main:G123:C123:m-1:m-1',
        direction: 'customer',
        sender: 'Ana Discord',
        body: 'Production API is down for our checkout flow. Can someone confirm the incident status?',
        messageKind: 'discord_message',
        attachments: [],
        metadata: {
          provider: 'discord',
          channelKey: 'discord-main',
          workspaceId: 'G123',
          channelId: 'C123',
          providerMessageId: 'm-1',
          externalTicketKey: 'discord:discord-main:G123:C123:m-1',
        },
        occurredAt: now,
      },
    ],
    outboundMessages: [
      outbound({
        id: 'reply-discord-1',
        issueId: 'issue-discord-open',
        channel: 'discord',
        toAddress: 'C123',
        subject: 'Re: Discord incident: production API down',
        body: 'We are checking the incident now. Please send one failing request ID while we verify the API status.',
        status: 'queued',
        provider: 'channel_adapter_pending',
        metadata: {
          approvalRequired: true,
          approved: false,
          reviewStatus: 'pending',
          channelKey: 'discord-main',
          replyTarget: { channel: 'discord', key: 'channelId', value: 'C123', label: 'Channel: C123' },
          automationContext: { source: 'channel_autopilot', channelKey: 'discord-main', channelType: 'discord' },
          externalProvider: 'discord',
          externalTicketKey: 'discord:discord-main:G123:C123:m-1',
        },
      }),
    ],
    actionExecutions: [
      actionExecution({
        id: 'action-discord-triage',
        issueId: 'issue-discord-open',
        actionKey: 'prepare_triage',
        label: 'Triage ticket',
        result: { action: { type: 'triage_ticket', status: 'ongoing', priority: 'urgent', queueName: 'Support', tags: ['incident', 'api'] } },
        metadata: { approvalRequired: true, reviewStatus: 'pending', source: 'channel_autopilot' },
      }),
      actionExecution({
        id: 'action-discord-fields',
        issueId: 'issue-discord-open',
        actionKey: 'prepare_custom_fields',
        label: 'Apply custom fields',
        result: { action: { type: 'set_custom_fields', customFields: { impact: 'checkout_down', customerPlan: 'enterprise' } } },
        metadata: { approvalRequired: true, reviewStatus: 'pending', source: 'channel_autopilot' },
      }),
    ],
    aiRuns: [
      {
        id: 'ai-discord-answer',
        issueId: 'issue-discord-open',
        runKey: 'agent_answer:issue-discord-open',
        source: 'agent_answer',
        status: 'success',
        activatedIntent: 'incident_response',
        requiresHuman: true,
        summary: 'Share current incident status, ask for request IDs, and avoid committing to an ETA until engineering confirms.',
        identityResult: {},
        intentResult: {},
        securityResult: {},
        tokenUsage: { totalTokens: 872 },
        toolCalls: [],
        metadata: {
          kind: 'agent_answer',
          question: 'Prepare reply',
          answer: 'Ask for request IDs and give an incident-status update.',
          confidence: 'high',
          citations: [knowledgeArticle],
        },
        startedAt: now,
        completedAt: now,
        created: now,
        updated: now,
      },
    ],
    activityEvents: [
      activity({
        id: 'event-discord-message',
        issueId: 'issue-discord-open',
        eventType: 'discord_message_received',
        title: 'Discord message received',
        body: 'Production API is down for our checkout flow.',
        metadata: { externalTicketKey: 'discord:discord-main:G123:C123:m-1' },
      }),
      activity({
        id: 'event-discord-autopilot',
        issueId: 'issue-discord-open',
        eventType: 'channel_agent_autopilot',
        title: 'Channel autopilot prepared work',
        body: 'Triage, custom fields, and reply draft prepared.',
        metadata: {
          replyId: 'reply-discord-1',
          aiRunId: 'ai-discord-answer',
          automationContext: { source: 'channel_autopilot', channelKey: 'discord-main', channelType: 'discord' },
          actions: [
            { type: 'prepare_triage', status: 'prepared', executionId: 'action-discord-triage', runId: 'triage-run-1' },
            { type: 'prepare_custom_fields', status: 'prepared', executionId: 'action-discord-fields', runId: 'fields-run-1', fieldCount: 2 },
            { type: 'prepare_agent_reply', status: 'prepared', replyId: 'reply-discord-1', runId: 'ai-discord-answer' },
          ],
        },
      }),
      activity({
        id: 'event-discord-reply',
        issueId: 'issue-discord-open',
        eventType: 'reply_queued',
        title: 'Reply queued',
        body: 'Human approval required.',
        metadata: { replyId: 'reply-discord-1' },
      }),
    ],
    channelWebhookEvents: [
      {
        id: 'webhook-discord-1',
        channelId: 'channel-discord-main',
        outboundMessageId: '',
        provider: 'discord',
        eventId: 'msg-1',
        eventType: 'MESSAGE_CREATE',
        providerMessageId: 'm-1',
        status: 'processed',
        error: '',
        payload: {},
        result: { issueId: 'issue-discord-open' },
        receivedAt: now,
        processedAt: now,
        created: now,
        updated: now,
      },
    ],
    knowledgeGaps: [
      {
        id: 'gap-discord-eta',
        issueId: 'issue-discord-open',
        gapKey: 'incident_eta',
        title: 'Incident ETA missing',
        evidence: 'No confirmed engineering ETA in ticket context.',
        status: 'open',
        severity: 'medium',
        suggestedArticleTitle: 'API incident ETA policy',
        metadata: {},
        firstSeenAt: now,
        lastSeenAt: now,
        created: now,
        updated: now,
      },
      {
        id: 'gap-discord-runbook',
        issueId: 'issue-discord-open',
        gapKey: 'incident_runbook_owner',
        title: 'Incident runbook owner missing',
        evidence: 'Escalation owner and customer-update cadence are not documented for API incidents.',
        status: 'open',
        severity: 'high',
        suggestedArticleTitle: 'API incident ownership policy',
        metadata: {},
        firstSeenAt: now,
        lastSeenAt: now,
        created: now,
        updated: now,
      },
    ],
    knowledgeSuggestions: [knowledgeArticle],
  }),
  baseIssue({
    id: 'issue-telegram-ongoing',
    accountId: 'account-orbit',
    contactId: 'contact-tom',
    sourceEmailId: 'telegram:telegram-main:chat-1:chat-1:456',
    chatId: 'telegram:telegram-main:chat-1:chat-1:456',
    status: 'ongoing',
    workflowStatus: 'ongoing',
    priority: 'normal',
    assigneeEmail: 'agent@example.com',
    queueKey: 'tier-2',
    queueName: 'Tier 2',
    tags: ['billing'],
    accountName: 'Orbit Logistics',
    accountDomain: 'orbit.test',
    contactEmail: 'telegram:chat-1:U123',
    contactName: 'Tom Telegram',
    subject: 'Telegram billing question',
    fromAddress: 'telegram:chat-1:U123',
    channel: 'telegram',
    source: 'telegram-main',
    aiSummary: 'Billing follow-up is assigned and waiting for account confirmation.',
    latestAgentMessageAt: now,
    messages: [
      {
        id: 'msg-telegram-1',
        sourceMessageId: 'telegram:telegram-main:chat-1:456:456',
        direction: 'customer',
        sender: 'Tom Telegram',
        body: 'Can you confirm the current invoice status?',
        messageKind: 'telegram_message',
        metadata: { provider: 'telegram', chatId: 'chat-1' },
        occurredAt: now,
      },
      {
        id: 'msg-telegram-2',
        sourceMessageId: 'outbound:reply-telegram-1',
        direction: 'agent',
        sender: 'agent@example.com',
        body: 'We are checking the invoice with finance.',
        messageKind: 'agent_reply',
        metadata: { providerMessageId: 'telegram:reply:1' },
        occurredAt: now,
      },
    ],
    outboundMessages: [
      outbound({
        id: 'reply-telegram-1',
        issueId: 'issue-telegram-ongoing',
        channel: 'telegram',
        toAddress: 'chat-1',
        subject: 'Re: Telegram billing question',
        body: 'We are checking the invoice with finance.',
        status: 'sent',
        provider: 'telegram_bot',
        providerMessageId: 'telegram:reply:1',
        sentAt: now,
        metadata: { channelKey: 'telegram-main' },
      }),
    ],
  }),
  baseIssue({
    id: 'issue-email-done',
    accountId: 'account-nova',
    contactId: 'contact-nora',
    sourceEmailId: 'email:support:nova-1',
    chatId: 'email:support:nova-1',
    status: 'done',
    workflowStatus: 'done',
    priority: 'low',
    assigneeEmail: 'lead@example.com',
    queueKey: 'support',
    queueName: 'Support',
    tags: ['how-to'],
    accountName: 'Nova Labs',
    accountDomain: 'nova.test',
    contactEmail: 'nora@nova.test',
    contactName: 'Nora Email',
    subject: 'Email setup solved',
    fromAddress: 'nora@nova.test',
    channel: 'email',
    source: 'email:support',
    aiSummary: 'Setup instructions sent and customer confirmed resolution.',
    latestAgentMessageAt: now,
  }),
];

const supportChannelWebhookEvents = [
  {
    id: 'webhook-unmatched-receipt',
    channelId: 'channel-discord-main',
    outboundMessageId: '',
    provider: 'discord',
    eventId: 'receipt-lost-1',
    eventType: 'MESSAGE_DELIVERY',
    providerMessageId: 'discord:reply:m-lost',
    status: 'unmatched',
    error: 'No outbound message matched this provider receipt.',
    payload: { providerMessageId: 'discord:reply:m-lost' },
    result: {},
    receivedAt: now,
    processedAt: '',
    created: now,
    updated: now,
  },
];

const accounts = {
  'account-acme': {
    id: 'account-acme',
    accountKey: 'acme-cloud',
    name: 'Acme Cloud',
    domain: 'acme.test',
    externalId: 'crm-acme',
    healthStatus: 'needs_attention',
    metadata: {},
    issueCount: 4,
    latestIssueAt: now,
    insightSummary: { openRisks: 1, openFeatureRequests: 1, unresolved: 2 },
    healthRollup: { status: 'needs_attention', score: 62, openRisks: 1, openFeatureRequests: 1, unresolved: 2 },
    contacts: [],
    issues: [],
    insights: [
      {
        id: 'insight-risk-1',
        accountId: 'account-acme',
        insightKey: 'api-risk',
        type: 'risk',
        title: 'API outage risk',
        body: 'Production API reliability is now a renewal risk.',
        severity: 'high',
        status: 'open',
        sourceIssueId: 'issue-discord-open',
        metadata: {},
        created: now,
        updated: now,
      },
    ],
    externalObjects: [],
    externalSyncRuns: [],
    created: now,
    updated: now,
  },
};

const crmConnectors = [
  {
    id: 'crm-hubspot-main',
    connectorKey: 'hubspot-main',
    provider: 'hubspot',
    name: 'HubSpot main',
    status: 'active',
    config: { adapter: 'buffer' },
    lastSyncAt: '',
    created: now,
    updated: now,
  },
];
const crmSyncRuns = [];
let crmSyncRunSequence = 1;

function issueSummary(issue) {
  const {
    messages,
    notes,
    slaEvents,
    portalSessions,
    assignmentHistory,
    watchers,
    outboundMessages,
    aiRuns,
    actionExecutions,
    activityEvents,
    channelWebhookEvents,
    csatFeedback,
    knowledgeGaps,
    knowledgeSuggestions,
    ...summary
  } = issue;
  return summary;
}

let replySequence = 1;
let agentRunSequence = 1;
let agentReplySequence = 1;
let lifecycleSequence = 1;
let splitSequence = 1;
let webChatSequence = 1;
let portalSequence = 1;
let accountInsightSequence = 1;
let noteSequence = 1;
let watcherSequence = 1;
let inboxViewSequence = 1;
let replyMacroSequence = 1;
let knowledgeArticleSequence = 1;
let manualIssueSequence = 1;
let automationRunSequence = 1;
const portalSessionsByToken = new Map();

const inboxViews = [
  { id: 'view-approvals', name: 'Needs approval', visibility: 'shared', ownerEmail: 'agent@example.com', filters: { statusFilter: 'approvals', viewMode: 'board' }, sortOrder: 1, created: now, updated: now },
];

const replyMacros = [
  { id: 'macro-incident', title: 'Incident acknowledgement', body: 'Thanks for the report. We are investigating and will update this ticket.', visibility: 'shared', ownerEmail: 'agent@example.com', status: 'active', tags: ['incident'], metadata: {}, created: now, updated: now },
];

const notifications = [
  { id: 'notification-1', issueId: 'issue-discord-open', recipientEmail: 'agent@example.com', type: 'approval_required', title: 'Approval required', body: 'Discord incident reply needs approval.', status: 'unread', metadata: { replyId: 'reply-discord-1' }, created: now, updated: now, readAt: '' },
];

function findIssue(issueId) {
  return issues.find(item => item.id === issueId) || null;
}

function createIssueNoteFixture(issue, body) {
  const noteBody = text(body.body);
  if (!noteBody) return null;
  const note = {
    id: `note-smoke-${noteSequence++}`,
    issueId: issue.id,
    authorEmail: 'agent@example.com',
    body: noteBody,
    metadata: {},
    created: now,
    updated: now,
  };
  issue.notes = [...(issue.notes ?? []), note];
  addActivity(issue, {
    id: `event-${note.id}`,
    issueId: issue.id,
    eventType: 'internal_note_created',
    actorEmail: 'agent@example.com',
    title: 'Internal note added',
    body: noteBody,
    metadata: { noteId: note.id },
  });
  return note;
}

function watchIssueFixture(issue) {
  const email = 'agent@example.com';
  const existing = (issue.watchers ?? []).find(watcher => text(watcher.watcherEmail).toLowerCase() === email);
  if (existing) return { ...existing, status: 'active' };
  const watcher = {
    id: `watcher-smoke-${watcherSequence++}`,
    issueId: issue.id,
    watcherEmail: email,
    addedBy: email,
    source: 'manual',
    status: 'active',
    created: now,
    updated: now,
  };
  issue.watchers = [...(issue.watchers ?? []), watcher];
  addActivity(issue, {
    id: `event-${watcher.id}`,
    issueId: issue.id,
    eventType: 'watcher_added',
    actorEmail: email,
    title: 'Watcher added',
    body: `${email} is watching this ticket.`,
    metadata: { watcherId: watcher.id },
  });
  return watcher;
}

function unwatchIssueFixture(issue) {
  const email = 'agent@example.com';
  const existing = (issue.watchers ?? []).find(watcher => text(watcher.watcherEmail).toLowerCase() === email);
  const watcher = existing || {
    id: `watcher-smoke-${watcherSequence++}`,
    issueId: issue.id,
    watcherEmail: email,
    addedBy: email,
    source: 'manual',
    status: 'inactive',
    created: now,
    updated: now,
  };
  issue.watchers = (issue.watchers ?? []).filter(item => item.id !== watcher.id && text(item.watcherEmail).toLowerCase() !== email);
  return { ...watcher, status: 'inactive', updated: now };
}

function upsertInboxViewFixture(body) {
  const id = text(body.id) || `view-smoke-${inboxViewSequence++}`;
  const existingIndex = inboxViews.findIndex(view => view.id === id);
  const existing = existingIndex >= 0 ? inboxViews[existingIndex] : {};
  const view = {
    id,
    name: text(body.name) || text(existing.name) || 'Saved view',
    visibility: text(body.visibility) === 'shared' ? 'shared' : 'private',
    ownerEmail: text(existing.ownerEmail) || 'agent@example.com',
    filters: body.filters && typeof body.filters === 'object' ? body.filters : (existing.filters || {}),
    sortOrder: Number(body.sortOrder || existing.sortOrder || inboxViews.length + 1),
    created: text(existing.created) || now,
    updated: now,
  };
  if (existingIndex >= 0) inboxViews.splice(existingIndex, 1, view);
  else inboxViews.unshift(view);
  return view;
}

function archiveInboxViewFixture(viewId) {
  const index = inboxViews.findIndex(view => view.id === viewId);
  if (index < 0) return null;
  inboxViews.splice(index, 1);
  return { status: 'deleted' };
}

function upsertReplyMacroFixture(body) {
  const id = text(body.id) || `macro-smoke-${replyMacroSequence++}`;
  const existingIndex = replyMacros.findIndex(macro => macro.id === id);
  const existing = existingIndex >= 0 ? replyMacros[existingIndex] : {};
  const macro = {
    id,
    title: text(body.title) || text(existing.title) || 'Reply macro',
    body: text(body.body) || text(existing.body),
    visibility: text(body.visibility) === 'private' ? 'private' : 'shared',
    ownerEmail: text(existing.ownerEmail) || 'agent@example.com',
    status: text(body.status) || text(existing.status) || 'active',
    tags: Array.isArray(body.tags) ? body.tags.map(text).filter(Boolean) : (existing.tags || []),
    metadata: body.metadata && typeof body.metadata === 'object' ? body.metadata : (existing.metadata || {}),
    created: text(existing.created) || now,
    updated: now,
  };
  if (existingIndex >= 0) replyMacros.splice(existingIndex, 1, macro);
  else replyMacros.unshift(macro);
  return macro;
}

function archiveReplyMacroFixture(macroId) {
  const macro = replyMacros.find(item => item.id === macroId);
  if (!macro) return null;
  macro.status = 'archived';
  macro.updated = now;
  return macro;
}

function renderReplyMacroFixture(macroId) {
  const macro = replyMacros.find(item => item.id === macroId && item.status === 'active');
  if (!macro) return null;
  return {
    body: macro.body,
    unresolvedVariables: [],
    macro,
  };
}

function markNotificationReadFixture(notificationId) {
  const notification = notifications.find(item => item.id === notificationId);
  if (!notification) return null;
  notification.status = 'read';
  notification.readAt = now;
  notification.updated = now;
  return notification;
}

function knowledgeArticleRevisionEntry(article, revision, action, changedFields) {
  const body = text(article.body);
  return {
    revision,
    action,
    actorEmail: 'agent@example.com',
    at: now,
    changedFields,
    title: text(article.title),
    status: text(article.status) || 'draft',
    visibility: text(article.visibility) || 'public',
    public: article.public === true,
    tags: Array.isArray(article.tags) ? article.tags : [],
    sourceIssueId: text(article.sourceIssueId),
    sourceUrl: text(article.sourceUrl),
    bodySha256: crypto.createHash('sha256').update(body).digest('hex'),
    bodyPreview: body.slice(0, 240),
  };
}

function appendKnowledgeArticleRevision(article, action, changedFields) {
  const revision = Number(article.revision || 0) + 1;
  article.revision = revision;
  article.revisions = [
    ...(Array.isArray(article.revisions) ? article.revisions : []),
    knowledgeArticleRevisionEntry(article, revision, action, changedFields),
  ].slice(-20);
  article.metadata = {
    ...(article.metadata ?? {}),
    revision,
    revisions: article.revisions,
  };
}

function createKnowledgeArticleFixture(body) {
  const title = text(body.title) || 'Support article';
  const visibility = text(body.visibility) || 'public';
  const article = {
    id: `kb-smoke-${knowledgeArticleSequence++}`,
    sourceIssueId: text(body.sourceIssueId),
    sourceGapId: text(body.sourceGapId),
    sourceUrl: text(body.sourceUrl),
    visibility,
    public: visibility === 'public',
    title,
    body: text(body.body),
    status: text(body.status) || 'draft',
    tags: Array.isArray(body.tags) ? body.tags.map(text).filter(Boolean) : [],
    metadata: {
      source: 'ticket_workspace',
      knowledgeMatch: { score: 0.81, terms: ['ticket', 'article'] },
    },
    revision: 0,
    revisions: [],
    created: now,
    updated: now,
  };
  appendKnowledgeArticleRevision(article, 'created', ['title', 'body', 'status', 'tags', 'sourceIssueId', 'sourceUrl', 'visibility', 'public']);
  knowledgeArticles.unshift(article);
  if (article.sourceIssueId) {
    const issue = findIssue(article.sourceIssueId);
    if (issue) {
      issue.knowledgeSuggestions = [article, ...(issue.knowledgeSuggestions ?? [])];
      if (article.sourceGapId) {
        issue.knowledgeGaps = (issue.knowledgeGaps ?? []).filter(gap => gap.id !== article.sourceGapId);
      }
      addActivity(issue, {
        id: `event-${article.id}`,
        issueId: issue.id,
        eventType: 'knowledge_article_created',
        actorEmail: 'agent@example.com',
        title: 'Knowledge article drafted',
        body: title,
        metadata: { articleId: article.id, sourceGapId: article.sourceGapId },
      });
    }
  }
  return article;
}

function allKnowledgeGapsFixture(status = 'open') {
  return issues.flatMap(issue => (issue.knowledgeGaps ?? []).map(gap => ({ ...gap })))
    .filter(gap => !status || status === 'all' || gap.status === status);
}

function updateKnowledgeGapFixture(gapId, body) {
  for (const issue of issues) {
    const gap = (issue.knowledgeGaps ?? []).find(item => item.id === gapId);
    if (!gap) continue;
    if (body.status !== undefined) gap.status = text(body.status);
    if (body.severity !== undefined) gap.severity = text(body.severity);
    if (body.title !== undefined) gap.title = text(body.title);
    if (body.evidence !== undefined) gap.evidence = text(body.evidence);
    if (body.suggestedArticleTitle !== undefined) gap.suggestedArticleTitle = text(body.suggestedArticleTitle);
    gap.updated = now;
    if (gap.status && gap.status !== 'open') {
      issue.knowledgeGaps = (issue.knowledgeGaps ?? []).filter(item => item.id !== gapId);
    }
    return gap;
  }
  return null;
}

function createKnowledgeArticleFromGapFixture(gapId, body) {
  for (const issue of issues) {
    const gap = (issue.knowledgeGaps ?? []).find(item => item.id === gapId);
    if (!gap) continue;
    return createKnowledgeArticleFixture({
      title: gap.suggestedArticleTitle || gap.title.replace(/^Knowledge gap:\s*/i, ''),
      body: gap.evidence || gap.title,
      status: text(body.status) || 'draft',
      sourceIssueId: gap.issueId,
      sourceGapId: gap.id,
      visibility: 'public',
      tags: ['support-gap'],
    });
  }
  return null;
}

function updateKnowledgeArticleFixture(articleId, body) {
  const article = knowledgeArticles.find(item => item.id === articleId);
  if (!article) return null;
  const beforeStatus = article.status;
  const changed = new Set();
  if (body.title !== undefined && article.title !== text(body.title)) {
    article.title = text(body.title);
    changed.add('title');
  }
  if (body.body !== undefined && article.body !== text(body.body)) {
    article.body = text(body.body);
    changed.add('body');
  }
  if (body.status !== undefined && article.status !== text(body.status)) {
    article.status = text(body.status);
    changed.add('status');
  }
  if (Array.isArray(body.tags)) {
    const nextTags = body.tags.map(text).filter(Boolean);
    if (JSON.stringify(article.tags ?? []) !== JSON.stringify(nextTags)) {
      article.tags = nextTags;
      changed.add('tags');
    }
  }
  if (body.sourceIssueId !== undefined && article.sourceIssueId !== text(body.sourceIssueId)) {
    article.sourceIssueId = text(body.sourceIssueId);
    changed.add('sourceIssueId');
  }
  if (body.sourceUrl !== undefined && article.sourceUrl !== text(body.sourceUrl)) {
    article.sourceUrl = text(body.sourceUrl);
    changed.add('sourceUrl');
  }
  if (body.visibility !== undefined) {
    const nextVisibility = text(body.visibility) || 'public';
    const nextPublic = nextVisibility === 'public';
    if (article.visibility !== nextVisibility) changed.add('visibility');
    if (article.public !== nextPublic) changed.add('public');
    article.visibility = nextVisibility;
    article.public = nextPublic;
  }
  if (body.public !== undefined) {
    const nextPublic = body.public === true;
    const nextVisibility = nextPublic ? 'public' : 'internal';
    if (article.public !== nextPublic) changed.add('public');
    if (article.visibility !== nextVisibility) changed.add('visibility');
    article.public = nextPublic;
    article.visibility = nextVisibility;
  }
  if (changed.size > 0) {
    const action = beforeStatus !== 'published' && article.status === 'published'
      ? 'published'
      : changed.has('visibility') || changed.has('public') ? 'visibility_changed' : 'updated';
    appendKnowledgeArticleRevision(article, action, [...changed]);
  }
  article.updated = now;
  return article;
}

function createManualIssueFixture(body) {
  const fromAddress = text(body.fromAddress);
  const messageBody = text(body.body);
  if (!fromAddress || !messageBody) return null;
  const sequence = manualIssueSequence++;
  const id = `issue-manual-smoke-${sequence}`;
  const assigneeEmail = text(body.assigneeEmail) || 'agent@example.com';
  const queueKey = text(body.queueKey) || 'support';
  const queueName = text(body.queueName) || (queueKey === 'support' ? 'Support' : queueKey);
  const subject = text(body.subject) || 'Manual ticket';
  const issue = baseIssue({
    id,
    accountName: text(body.accountName) || fromAddress.split('@')[1] || fromAddress,
    accountDomain: fromAddress.includes('@') ? fromAddress.split('@')[1] : '',
    contactEmail: fromAddress,
    contactName: text(body.contactName),
    subject,
    fromAddress,
    channel: 'email',
    source: 'admin_inbox',
    sourceEmailId: `manual:${id}`,
    chatId: `manual:${id}`,
    status: 'open',
    workflowStatus: 'open',
    priority: text(body.priority) || 'normal',
    assigneeEmail,
    queueKey,
    queueName,
    aiSummary: messageBody.slice(0, 300),
    latestMessageDirection: 'customer',
    latestCustomerMessageAt: now,
    latestMessageAt: now,
    needsResponse: true,
    messageCount: 1,
    messages: [{
      id: `msg-manual-smoke-${sequence}`,
      sourceMessageId: `manual:${id}:initial`,
      direction: 'customer',
      sender: text(body.contactName) || fromAddress,
      body: messageBody,
      messageKind: 'manual_message',
      attachments: [],
      metadata: { source: 'admin_inbox', createdBy: 'agent@example.com' },
      occurredAt: now,
    }],
    assignmentHistory: assigneeEmail ? [{
      id: `assignment-manual-smoke-${sequence}`,
      issueId: id,
      assigneeEmail,
      assignedBy: 'agent@example.com',
      status: 'active',
      created: now,
      updated: now,
    }] : [],
    activityEvents: [
      activity({
        id: `event-${id}-created`,
        issueId: id,
        eventType: 'issue_created',
        actorEmail: 'agent@example.com',
        title: 'Issue created',
        body: messageBody.slice(0, 240),
        toStatus: 'open',
        toPriority: text(body.priority) || 'normal',
        metadata: { source: 'admin_inbox' },
      }),
    ],
  });
  issues.unshift(issue);
  recalculateIssueState(issue);
  return issue;
}

function automationRunFixture(overrides = {}) {
  return {
    id: `automation-run-smoke-${automationRunSequence++}`,
    ruleId: 'automation-sla-escalate',
    issueId: 'issue-discord-open',
    trigger: 'sla_breached',
    status: 'success',
    actionsApplied: 2,
    error: '',
    context: { source: 'admin', event: 'sla_breached' },
    result: { note: true, replyPrepared: true },
    startedAt: now,
    completedAt: now,
    created: now,
    updated: now,
    ...overrides,
  };
}

function runSlaEscalationFixture() {
  const issue = findIssue('issue-discord-open');
  const run = automationRunFixture();
  automationRuns.unshift(run);
  if (issue) {
    issue.priority = 'urgent';
    issue.tags = uniqueTags(issue.tags, ['sla-overdue-watch']);
    issue.notes = [
      ...(issue.notes ?? []),
      {
        id: `note-sla-smoke-${automationRunSequence}`,
        issueId: issue.id,
        authorEmail: 'sla-monitor',
        body: 'SLA escalation started by automation scan. Confirm owner, customer reply, and resolution path.',
        metadata: { source: 'sla_scan' },
        created: now,
        updated: now,
      },
    ];
    addActivity(issue, {
      id: `event-sla-smoke-${run.id}`,
      issueId: issue.id,
      eventType: 'sla_breached',
      actorEmail: 'sla-monitor',
      title: 'SLA breached: First response',
      body: 'First response target passed.',
      metadata: { slaEventId: 'sla-event-discord-overdue', automationRunId: run.id },
    });
    recalculateIssueState(issue);
  }
  return {
    processed: 1,
    escalated: 1,
    skipped: 0,
    failed: 0,
    items: [{
      slaEventId: 'sla-event-discord-overdue',
      issueId: 'issue-discord-open',
      eventType: 'first_response',
      targetAt: '2026-07-05T09:15:00.000Z',
      status: 'escalated',
      reason: '',
      automation: {
        processed: 1,
        failed: 0,
        items: [run],
      },
    }],
  };
}

function findAccountInsight(insightId) {
  for (const account of Object.values(accounts)) {
    const insight = (account.insights ?? []).find(item => item.id === insightId);
    if (insight) return { account, insight };
  }
  return null;
}

function accountInsightSummaryFixture(account) {
  const insights = account.insights ?? [];
  const unresolved = insight => !['resolved', 'closed', 'dismissed'].includes(text(insight.status));
  const risks = insights.filter(insight => insight.type === 'risk');
  const featureRequests = insights.filter(insight => insight.type === 'feature_request');
  return {
    total: insights.length,
    unresolved: insights.filter(unresolved).length,
    risks: risks.length,
    openRisks: risks.filter(unresolved).length,
    featureRequests: featureRequests.length,
    openFeatureRequests: featureRequests.filter(unresolved).length,
    summaries: insights.filter(insight => insight.type === 'summary').length,
    lastInsightAt: insights.map(insight => insight.lastSeenAt || insight.updated || insight.created || '').sort().at(-1) || '',
  };
}

function accountHealthRollupFixture(account) {
  const summary = account.insightSummary ?? accountInsightSummaryFixture(account);
  const issueList = issues.filter(issue => issue.accountId === account.id);
  const openIssues = issueList.filter(issue => !['done', 'closed'].includes(text(issue.status)));
  const urgentIssues = openIssues.filter(issue => issue.priority === 'urgent');
  const highPriorityIssues = openIssues.filter(issue => ['urgent', 'high'].includes(issue.priority));
  const hasOpenHighRisk = (account.insights ?? []).some(insight => (
    insight.type === 'risk'
    && !['resolved', 'closed', 'dismissed'].includes(text(insight.status))
    && ['urgent', 'high', 'at_risk', 'blocked'].includes(text(insight.severity))
  ));
  let status = 'healthy';
  let reason = 'No unresolved account risks or open support tickets.';
  let nextAction = 'Keep monitoring support health.';
  if (urgentIssues.length > 0 || hasOpenHighRisk) {
    status = 'at_risk';
    reason = 'Urgent support signal or high-severity account risk is open.';
    nextAction = 'Assign an owner, confirm the customer update, and close the risk loop.';
  } else if (summary.openRisks > 0 || highPriorityIssues.length > 0) {
    status = 'needs_attention';
    reason = 'Open risk, high-priority ticket, or CRM sync issue needs review.';
    nextAction = 'Review the open risk and decide the next customer-facing step.';
  } else if (openIssues.length > 0 || summary.openFeatureRequests > 0) {
    status = 'active';
    reason = 'Account has open support work or tracked feature demand.';
    nextAction = 'Keep ticket owner and feature-request follow-up current.';
  }
  return {
    status,
    score: status === 'at_risk' ? 38 : status === 'needs_attention' ? 62 : status === 'active' ? 78 : 94,
    reason,
    nextAction,
    openIssues: openIssues.length,
    urgentIssues: urgentIssues.length,
    highPriorityIssues: highPriorityIssues.length,
    openRisks: summary.openRisks,
    openFeatureRequests: summary.openFeatureRequests,
    unresolvedSignals: summary.unresolved,
    failedExternalSyncRuns: (account.externalSyncRuns ?? []).filter(run => ['failed', 'partial', 'error'].includes(text(run.status).toLowerCase())).length,
    lastSignalAt: summary.lastInsightAt,
  };
}

function normalizeAccountFixture(account) {
  const accountIssues = issues.filter(issue => issue.accountId === account.id);
  const summary = accountInsightSummaryFixture(account);
  const healthRollup = accountHealthRollupFixture({ ...account, insightSummary: summary });
  return {
    ...account,
    issueCount: accountIssues.length,
    latestIssueAt: accountIssues.map(issue => issue.latestMessageAt || issue.updated || issue.created || '').sort().at(-1) || account.latestIssueAt || '',
    issues: accountIssues.map(issueSummary),
    insightSummary: summary,
    healthRollup,
    healthStatus: healthRollup.status,
  };
}

function accountContextFixture(issue) {
  const account = accounts[issue.accountId];
  if (!account) return {};
  const normalized = normalizeAccountFixture(account);
  const unresolved = (normalized.insights ?? [])
    .filter(insight => !['resolved', 'closed', 'dismissed'].includes(text(insight.status)));
  const providers = new Set();
  (normalized.externalObjects ?? []).forEach(object => {
    if (object.provider) providers.add(object.provider);
  });
  (normalized.externalSyncRuns ?? []).forEach(run => {
    if (run.provider) providers.add(run.provider);
  });
  const latestSync = (normalized.externalSyncRuns ?? [])[0] || {};
  return {
    accountId: normalized.id,
    name: normalized.name,
    domain: normalized.domain,
    health: normalized.healthRollup,
    insightSummary: normalized.insightSummary,
    openSignals: unresolved.slice(0, 6).map(insight => ({
      id: insight.id,
      type: insight.type,
      title: insight.title,
      severity: insight.severity,
      status: insight.status,
      sourceIssueId: insight.sourceIssueId,
      lastSeenAt: insight.lastSeenAt || insight.updated || insight.created || '',
      bodyPreview: text(insight.body).slice(0, 240),
    })),
    crm: {
      providers: Array.from(providers).sort(),
      externalRecordCount: (normalized.externalObjects ?? []).length,
      latestSyncStatus: text(latestSync.status),
      latestSyncAt: text(latestSync.completedAt || latestSync.startedAt),
    },
  };
}

function createAccountInsightFixture(account, body) {
  const type = text(body.type) || 'risk';
  const id = `insight-smoke-${accountInsightSequence++}`;
  const insight = {
    id,
    accountId: account.id,
    insightKey: text(body.insightKey) || `manual:${type}:${id}`,
    type,
    title: text(body.title) || (type === 'feature_request' ? 'Feature request' : type === 'summary' ? 'Account summary' : 'Risk needs attention'),
    body: text(body.body),
    severity: text(body.severity) || (type === 'risk' ? 'high' : 'info'),
    status: text(body.status) || (type === 'summary' ? 'active' : 'open'),
    sourceIssueId: text(body.sourceIssueId),
    metadata: body.metadata && typeof body.metadata === 'object' ? body.metadata : {},
    lastSeenAt: now,
    created: now,
    updated: now,
  };
  account.insights = [insight, ...(account.insights ?? []).filter(item => item.id !== id)];
  const normalized = normalizeAccountFixture(account);
  Object.assign(account, {
    insightSummary: normalized.insightSummary,
    healthRollup: normalized.healthRollup,
    healthStatus: normalized.healthStatus,
    issueCount: normalized.issueCount,
    latestIssueAt: normalized.latestIssueAt,
  });
  return insight;
}

function updateAccountInsightFixture(insightId, body) {
  const found = findAccountInsight(insightId);
  if (!found) return null;
  if (body.status !== undefined) found.insight.status = text(body.status);
  if (body.severity !== undefined) found.insight.severity = text(body.severity);
  if (body.title !== undefined) found.insight.title = text(body.title);
  if (body.body !== undefined) found.insight.body = text(body.body);
  found.insight.updated = now;
  const normalized = normalizeAccountFixture(found.account);
  Object.assign(found.account, {
    insightSummary: normalized.insightSummary,
    healthRollup: normalized.healthRollup,
    healthStatus: normalized.healthStatus,
    issueCount: normalized.issueCount,
    latestIssueAt: normalized.latestIssueAt,
  });
  return found.insight;
}

function runCrmSyncFixture() {
  const account = accounts['account-acme'];
  const runId = `crm-sync-run-${crmSyncRunSequence++}`;
  const externalObject = {
    id: 'external-hubspot-acme-company',
    accountId: account.id,
    contactId: '',
    provider: 'hubspot',
    objectType: 'account',
    externalId: 'hubspot-company-123',
    externalUrl: 'https://app.hubspot.test/companies/hubspot-company-123',
    displayName: 'Acme Cloud HubSpot company',
    raw: { owner: 'Customer Success', lifecycleStage: 'customer' },
    lastSeenAt: now,
    created: now,
    updated: now,
  };
  const externalRun = {
    id: `external-sync-acme-${runId}`,
    accountId: account.id,
    sourceIssueId: '',
    provider: 'hubspot',
    status: 'success',
    objectsSeen: 1,
    error: '',
    result: { connectorId: 'crm-hubspot-main', externalObjectId: externalObject.id },
    startedAt: now,
    completedAt: now,
    created: now,
    updated: now,
  };
  account.externalObjects = [externalObject];
  account.externalSyncRuns = [externalRun, ...(account.externalSyncRuns ?? []).filter(run => run.id !== externalRun.id)];
  crmConnectors[0].lastSyncAt = now;
  crmConnectors[0].updated = now;
  const connectorResult = {
    connectorId: 'crm-hubspot-main',
    connectorKey: 'hubspot-main',
    provider: 'hubspot',
    adapter: 'buffer',
    status: 'success',
    processed: 1,
    failed: 0,
    skipped: 0,
    objectsSeen: 1,
    cursorValue: 'hubspot-company-123',
    items: [
      {
        id: 'hubspot-company-123',
        objectType: 'account',
        externalId: 'hubspot-company-123',
        status: 'processed',
        accountId: account.id,
        objectsSeen: 1,
      },
    ],
    error: '',
  };
  crmSyncRuns.unshift({
    id: runId,
    connectorId: 'crm-hubspot-main',
    source: 'admin',
    status: 'success',
    processed: connectorResult.processed,
    failed: connectorResult.failed,
    skipped: connectorResult.skipped,
    objectsSeen: connectorResult.objectsSeen,
    error: '',
    result: connectorResult,
    startedAt: now,
    completedAt: now,
    created: now,
    updated: now,
  });
  return {
    connectors: crmConnectors.length,
    processed: connectorResult.processed,
    failed: connectorResult.failed,
    skipped: connectorResult.skipped,
    objectsSeen: connectorResult.objectsSeen,
    items: [connectorResult],
  };
}

function rematchChannelWebhookEventFixture(eventId, body = {}) {
  const event = supportChannelWebhookEvents.find(item => item.id === eventId);
  if (!event) return null;
  const outboundMessageId = text(body.outboundMessageId) || 'reply-discord-1';
  event.outboundMessageId = outboundMessageId;
  event.status = 'processed';
  event.error = '';
  event.result = {
    outboundMessageId,
    issueId: 'issue-discord-open',
    matchedBy: 'providerMessageId',
  };
  event.processedAt = now;
  event.updated = now;
  const issue = findIssue('issue-discord-open');
  const reply = issue?.outboundMessages?.find(item => item.id === outboundMessageId);
  if (reply) {
    reply.providerMessageId = event.providerMessageId;
    reply.metadata = {
      ...(reply.metadata ?? {}),
      deliveryReceipt: {
        eventId: event.eventId,
        status: 'matched',
        providerMessageId: event.providerMessageId,
      },
    };
  }
  return event;
}

function schemaHealthFixture() {
  return {
    status: 'ready',
    ready: true,
    requiredCollections: 31,
    presentCollections: 31,
    missingCollections: [],
    requiredFields: 126,
    presentFields: 126,
    missingFields: [],
    expectedMigrations: 31,
    presentMigrations: 31,
    missingMigrationFiles: [],
    items: [
      { name: 'support_issues', exists: true, error: '', area: 'issues', migration: '25_support_issues.js' },
      { name: 'support_channels', exists: true, error: '', area: 'channels', migration: '27_support_collaboration_knowledge_channels.js' },
      { name: 'support_sla_events', exists: true, error: '', area: 'sla', migration: '38_support_sla_policies.js' },
    ],
    fieldItems: [],
    migrationItems: [],
  };
}

function launchReadinessFixture(status = 'needs_attention') {
  return {
    status,
    blockers: [],
    warnings: [
      { key: 'due_soon_sla', label: 'SLA due soon', count: 1 },
      { key: 'open_knowledge_gaps', label: 'Open knowledge gaps', count: 1 },
    ],
    checks: 18,
  };
}

function launchProofCheckFixture(channel, key, label, issueId, providerMessageId = '') {
  const attachmentOnly = key === 'attachment_lifecycle_smoke';
  return {
    key,
    label,
    status: 'done',
    detail: `${label} proved for ${channel.name}.`,
    runId: `${key}:${channel.key}`,
    source: channel.key,
    runStatus: 'success',
    processed: 1,
    failed: 0,
    sent: key.includes('delivery') || key.includes('lifecycle') ? 1 : 0,
    startedAt: now,
    transport: channel.type === 'web_chat' ? 'internal' : 'http',
    provider: channel.deliveryProvider || channel.provider,
    providerMessageId,
    issueId,
    replyId: key.includes('delivery') || key.includes('lifecycle') ? `reply-proof-${channel.key}` : '',
    attachmentCount: attachmentOnly ? 1 : 0,
    fileOnly: attachmentOnly,
  };
}

function launchProofChannelFixture(channel) {
  const issueId = channel.type === 'web_chat' ? 'issue-web-chat-smoke-1' : channel.type === 'telegram' ? 'issue-telegram-ongoing' : 'issue-discord-open';
  const providerMessageId = channel.type === 'web_chat'
    ? 'web_chat:reply:web-session-smoke-1'
    : `${channel.type}:reply:${channel.targetId}`;
  return {
    channelId: channel.id,
    channelKey: channel.key,
    name: channel.name,
    type: channel.type,
    status: 'active',
    proofKind: channel.type === 'web_chat' ? 'web_chat_session_delivery' : 'channel_lifecycle',
    required: true,
    ready: true,
    checks: channel.type === 'web_chat' ? 2 : 4,
    passed: channel.type === 'web_chat' ? 2 : 4,
    blocked: 0,
    lastCheckedAt: now,
    blockers: [],
    checklist: channel.type === 'web_chat'
      ? [
        launchProofCheckFixture(channel, 'web_chat_session', 'Visitor session', issueId),
        launchProofCheckFixture(channel, 'web_chat_delivery', 'Web chat delivery', issueId, providerMessageId),
      ]
      : [
        launchProofCheckFixture(channel, 'inbound_smoke', 'Inbound smoke', issueId),
        launchProofCheckFixture(channel, 'outbound_smoke', 'Outbound smoke', issueId, providerMessageId),
        launchProofCheckFixture(channel, 'lifecycle_smoke', 'Lifecycle smoke', issueId, providerMessageId),
        launchProofCheckFixture(channel, 'attachment_lifecycle_smoke', 'Attachment lifecycle smoke', issueId, providerMessageId),
      ],
  };
}

function launchProofFixture(status = 'needs_attention') {
  return {
    status,
    schema: {
      status: 'ready',
      ready: true,
      requiredCollections: 31,
      presentCollections: 31,
      missingCollections: [],
      requiredFields: 126,
      presentFields: 126,
      missingFields: [],
      expectedMigrations: 31,
      presentMigrations: 31,
      missingMigrationFiles: [],
    },
    channels: {
      total: channelFixtures.length,
      active: channelFixtures.length,
      required: channelFixtures.length,
      ready: channelFixtures.length,
      blocked: 0,
      items: channelFixtures.map(launchProofChannelFixture),
    },
    blockers: [],
    warnings: launchReadinessFixture(status).warnings,
    checkedAt: now,
    evidence: {
      workflowLifecycle: [
        {
          kind: 'workflow',
          label: 'Workflow lifecycle proof',
          detail: 'Ticket moved through Ongoing and Done',
          issueId: 'issue-discord-open',
          replyId: 'reply-discord-1',
          runId: 'workflow-proof-1',
          occurredAt: now,
          source: 'cmux_smoke',
        },
      ],
      humanLoopAutomation: [
        {
          kind: 'automation',
          label: 'Human-loop automation proof',
          detail: 'Agent prepared approval-required draft and actions',
          issueId: 'issue-discord-open',
          replyId: 'reply-discord-1',
          runId: 'automation-proof-1',
          occurredAt: now,
          source: 'cmux_smoke',
        },
      ],
    },
  };
}

function launchProofRunFixture() {
  const run = {
    id: `launch-proof-run-${launchProofRuns.length + 1}`,
    status: 'success',
    actions: [
      {
        key: 'sla_due_soon_watch',
        label: 'SLA due-soon watch',
        status: 'success',
        error: '',
        result: {
          processed: 1,
          updated: 1,
          notes: 1,
          insights: 1,
          issueId: 'issue-telegram-ongoing',
          detail: 'Tagged due-soon SLA ticket, added note, and created account insight.',
        },
      },
      {
        key: 'workflow_lifecycle',
        label: 'Workflow lifecycle proof',
        status: 'success',
        error: '',
        result: {
          processed: 1,
          issueId: 'issue-discord-open',
          replyId: 'reply-discord-1',
        },
      },
    ],
    ran: 2,
    failed: 0,
    skipped: 0,
    launchReadiness: launchReadinessFixture('needs_attention'),
    launchProof: launchProofFixture('needs_attention'),
    startedAt: now,
    completedAt: now,
    created: now,
    updated: now,
  };
  launchProofRuns.unshift(run);
  return run;
}

function supportAnalyticsFixture() {
  const openIssues = issues.filter(issue => issue.status === 'open').length;
  const ongoingIssues = issues.filter(issue => issue.status === 'ongoing').length;
  const doneIssues = issues.filter(issue => issue.status === 'done').length;
  const queuedOutbound = issues.reduce((count, issue) => count + (issue.outboundMessages ?? []).filter(reply => reply.status === 'queued').length, 0);
  const sentOutbound = issues.reduce((count, issue) => count + (issue.outboundMessages ?? []).filter(reply => reply.status === 'sent').length, 0);
  const accountInsightCount = Object.values(accounts).reduce((count, account) => count + (account.insights ?? []).length, 0);
  const openAccountRisks = Object.values(accounts).reduce((count, account) => count + (account.insights ?? []).filter(insight => insight.type === 'risk' && !['resolved', 'closed', 'dismissed'].includes(text(insight.status))).length, 0);
  const featureRequests = Object.values(accounts).reduce((count, account) => count + (account.insights ?? []).filter(insight => insight.type === 'feature_request').length, 0);
  const hasWebChatSessionProof = webChatSessions.length > 0;
  const hasWebChatDeliveryProof = issues.some(issue => (issue.outboundMessages ?? []).some(reply => (
    reply.status === 'sent'
    && (reply.provider === 'web_chat_internal' || String(reply.providerMessageId || '').startsWith('web_chat:reply:'))
  )));
  const externalLaunchChannels = channelFixtures.filter(channel => channel.type !== 'web_chat');
  const emailLaunchChannels = 1;
  return {
    launchReadiness: launchReadinessFixture('needs_attention'),
    launchProof: launchProofFixture('needs_attention'),
    latestLaunchProofRun: launchProofRuns[0] || null,
    totalIssues: issues.length,
    openIssues,
    ongoingIssues,
    doneIssues,
    pendingIssues: 0,
    closedIssues: 0,
    unassignedIssues: issues.filter(issue => !issue.assigneeEmail).length,
    openWorkloadIssues: issues.filter(issue => issue.status !== 'done').length,
    openQueueBreakdown: [
      { key: 'support', label: 'Support', count: 3 },
      { key: 'tier-2', label: 'Tier 2', count: 1 },
    ],
    openAssigneeBreakdown: [
      { key: 'agent@example.com', label: 'agent@example.com', count: 3 },
      { key: '__unassigned__', label: 'Unassigned', count: 1 },
    ],
    openChannelBreakdown: [
      { key: 'discord', label: 'discord', count: 1 },
      { key: 'telegram', label: 'telegram', count: 1 },
      { key: 'web_chat', label: 'web_chat', count: webChatSessions.length },
    ],
    supportHealthInsights: [
      {
        key: 'sla_health',
        label: 'SLA risk',
        detail: '1 ticket has an SLA target due soon.',
        severity: 'warning',
        route: '/inbox?filter=due-soon-sla',
        value: 1,
        target: 0,
        unit: 'tickets',
      },
      {
        key: 'first_response',
        label: 'First response',
        detail: 'P90 first response is within the configured SLA.',
        severity: 'good',
        route: '/analytics',
        value: 42,
        target: 60,
        unit: 'minutes',
      },
      {
        key: 'launch_readiness',
        label: 'Launch readiness',
        detail: 'Schema, channels, workflow proof, and human-loop automation are present.',
        severity: 'good',
        route: '/analytics',
        value: channelFixtures.length,
        target: channelFixtures.length,
        unit: 'channels',
      },
    ],
    issuesNeedingApproval: issues.filter(issue => issue.hasPendingApproval).length,
    issuesNeedingResponse: issues.filter(issue => issue.needsResponse).length,
    oldestNeedsResponseAt: now,
    oldestNeedsResponseHours: 4,
    urgentIssues: issues.filter(issue => issue.priority === 'urgent').length,
    highPriorityIssues: issues.filter(issue => ['urgent', 'high'].includes(issue.priority)).length,
    channels: channelFixtures.length,
    activeChannels: channelFixtures.length,
    accounts: Object.keys(accounts).length,
    knowledgeArticles: 1,
    knowledgeGaps: 1,
    openKnowledgeGaps: 1,
    accountInsights: accountInsightCount,
    openAccountRisks,
    featureRequests,
    externalObjects: Object.values(accounts).reduce((count, account) => count + (account.externalObjects ?? []).length, 0),
    externalSyncRuns: Object.values(accounts).reduce((count, account) => count + (account.externalSyncRuns ?? []).length, 0),
    failedExternalSyncRuns: 0,
    crmConnectors: crmConnectors.length,
    activeCrmConnectors: crmConnectors.filter(connector => connector.status === 'active').length,
    crmSyncRuns: crmSyncRuns.length,
    failedCrmSyncRuns: 0,
    crmWebhookEvents: 0,
    failedCrmWebhookEvents: 0,
    overdueSlaEvents: 1,
    dueSoonSlaEvents: 1,
    slaEvents: 4,
    pendingSlaEvents: 2,
    metSlaEvents: 1,
    breachedSlaEvents: 1,
    averageFirstResponseMinutes: 42,
    p90FirstResponseMinutes: 55,
    averageResolutionHours: 18,
    p90ResolutionHours: 26,
    aiRuns: issues.reduce((count, issue) => count + (issue.aiRuns ?? []).length, 0),
    aiRunsNeedingHuman: 2,
    actionExecutions: issues.reduce((count, issue) => count + (issue.actionExecutions ?? []).length, 0),
    successfulActionExecutions: 1,
    automationRules: 2,
    activeAutomationRules: 2,
    agentAutomationRules: 1,
    humanLoopAutomationRules: 1,
    automationRuns: 3,
    successfulAutomationRuns: 2,
    successfulHumanLoopAutomationRuns: 1,
    successfulChannelAutopilotPrepPackages: 1,
    successfulChannelAutopilotDrafts: 1,
    failedAutomationRuns: 0,
    workflowTransitionEvents: 3,
    workflowOngoingTransitions: 2,
    workflowDoneTransitions: 1,
    successfulWorkflowLifecycleProofs: 1,
    activityEvents: issues.reduce((count, issue) => count + (issue.activityEvents ?? []).length, 0),
    outboundMessages: queuedOutbound + sentOutbound,
    queuedOutboundMessages: queuedOutbound,
    sentOutboundMessages: sentOutbound,
    failedOutboundMessages: 0,
    channelSyncRuns: 5,
    failedChannelSyncRuns: 0,
    activeEmailChannelsWithSync: emailLaunchChannels,
    activeEmailChannelsMissingSync: 0,
    failedEmailChannelSyncRuns: 0,
    activeEmailChannelsWithDelivery: emailLaunchChannels,
    activeEmailChannelsMissingDelivery: 0,
    channelValidationRuns: channelFixtures.length,
    failedChannelValidationRuns: 0,
    channelRemediationRuns: 1,
    channelRemediationItems: 1,
    latestChannelRemediations: [
      {
        channelId: 'channel-slack-main',
        channelKey: 'slack-main',
        channelName: 'Slack main',
        source: 'launch_proof',
        status: 'open',
        startedAt: now,
        key: 'sla_watch',
        label: 'Review due-soon SLA watch',
        detail: 'SLA watch proof created a ticket note and account insight.',
        severity: 'info',
        action: 'review',
        runAction: 'sla_due_soon_watch',
      },
    ],
    activeChannelsWithProviderValidation: channelFixtures.length,
    activeChannelsMissingProviderValidation: 0,
    activeChannelsWithLiveSmokeTarget: externalLaunchChannels.length,
    activeChannelsMissingLiveSmokeTarget: 0,
    channelSmokeRuns: channelFixtures.length,
    failedChannelSmokeRuns: 0,
    activeChannelsWithSmoke: channelFixtures.length,
    activeChannelsMissingSmoke: 0,
    outboundChannelSmokeRuns: channelFixtures.length,
    failedOutboundChannelSmokeRuns: 0,
    activeChannelsWithOutboundSmoke: channelFixtures.length,
    activeChannelsMissingOutboundSmoke: 0,
    lifecycleChannelSmokeRuns: channelFixtures.length,
    failedLifecycleChannelSmokeRuns: 0,
    activeChannelsWithLifecycleSmoke: channelFixtures.length,
    activeChannelsMissingLifecycleSmoke: 0,
    activeChannelsWithAttachmentLifecycleSmoke: externalLaunchChannels.length,
    activeChannelsMissingAttachmentLifecycleSmoke: 0,
    activeSlackChannelsWithAttachmentLifecycleSmoke: externalLaunchChannels.some(channel => channel.type === 'slack') ? 1 : 0,
    activeSlackChannelsMissingAttachmentLifecycleSmoke: 0,
    failedAttachmentLifecycleChannelSmokeRuns: 0,
    activeChannelsWrongTicketMode: 0,
    activeChannelsWithoutAutoPrepare: 0,
    activeChannelsWithOwnerRouting: channelFixtures.length,
    activeChannelsMissingOwnerRouting: 0,
    activeChannelsWithAutopilotPrepPackage: channelFixtures.length,
    activeChannelsMissingAutopilotPrepPackage: 0,
    activeChannelsWithAutopilotDraft: channelFixtures.length,
    activeChannelsMissingAutopilotDraft: 0,
    channelWebhookEvents: 5,
    failedChannelWebhookEvents: 0,
    unmatchedChannelWebhookEvents: 0,
    webChatSessions: webChatSessions.length,
    openWebChatSessions: webChatSessions.filter(session => session.status === 'open').length,
    activeWebChatChannelsWithSession: hasWebChatSessionProof ? 1 : 0,
    activeWebChatChannelsMissingSession: hasWebChatSessionProof ? 0 : 1,
    failedWebChatChannelSessionProofs: 0,
    activeWebChatChannelsWithDelivery: hasWebChatDeliveryProof ? 1 : 0,
    activeWebChatChannelsMissingDelivery: hasWebChatDeliveryProof ? 0 : 1,
    failedWebChatChannelDeliveryProofs: 0,
    deliveryRuns: 5,
    failedDeliveryRuns: 0,
    portalSessions: 0,
    activePortalSessions: 0,
    csatFeedback: 1,
    averageCsatRating: 4,
    lowCsatFeedback: 0,
    csatRatingCounts: { '4': 1 },
    statusCounts: { open: openIssues, ongoing: ongoingIssues, done: doneIssues },
    priorityCounts: { urgent: 1, normal: 2, low: 1 },
    channelCounts: { discord: 1, telegram: 1, email: 1, web_chat: webChatSessions.length },
    queueCounts: { support: 3, 'tier-2': 1 },
    assigneeCounts: { 'agent@example.com': 3, 'lead@example.com': 1 },
  };
}

function messageMatches(message, messageId) {
  const cleanId = text(messageId);
  if (!cleanId) return false;
  return message.id === cleanId || message.sourceMessageId === cleanId;
}

function uniqueTags(...tagGroups) {
  const seen = new Set();
  const tags = [];
  for (const group of tagGroups) {
    for (const tag of Array.isArray(group) ? group : []) {
      const clean = text(tag);
      const key = clean.toLowerCase();
      if (clean && !seen.has(key)) {
        seen.add(key);
        tags.push(clean);
      }
    }
  }
  return tags;
}

function replyNeedsApprovalFixture(reply) {
  return reply.metadata?.approvalRequired === true
    && reply.metadata?.approved !== true
    && reply.metadata?.reviewStatus !== 'changes_requested';
}

function actionNeedsApprovalFixture(execution) {
  return execution.status === 'pending'
    && execution.metadata?.approvalRequired === true
    && (execution.metadata?.reviewStatus || 'pending') === 'pending';
}

function recalculateIssueState(issue) {
  const replyApprovalCount = (issue.outboundMessages ?? []).filter(replyNeedsApprovalFixture).length;
  const actionApprovalCount = (issue.actionExecutions ?? []).filter(actionNeedsApprovalFixture).length;
  const pendingDeliveryCount = (issue.outboundMessages ?? []).filter(reply => reply.status === 'queued').length;
  const failedDeliveryCount = (issue.outboundMessages ?? []).filter(reply => reply.status === 'failed').length;
  const messages = [...(issue.messages ?? [])].sort((left, right) => String(left.occurredAt || '').localeCompare(String(right.occurredAt || '')));
  const latestMessage = messages[messages.length - 1] || null;
  const latestCustomerMessage = messages.filter(message => ['customer', 'visitor'].includes(text(message.direction))).at(-1) || null;
  const latestAgentMessage = messages.filter(message => text(message.direction) === 'agent').at(-1) || null;
  issue.pendingReplyApprovalCount = replyApprovalCount;
  issue.hasPendingReplyApproval = replyApprovalCount > 0;
  issue.pendingActionApprovalCount = actionApprovalCount;
  issue.hasPendingActionApproval = actionApprovalCount > 0;
  issue.pendingApprovalCount = replyApprovalCount + actionApprovalCount;
  issue.hasPendingApproval = issue.pendingApprovalCount > 0;
  issue.pendingDeliveryCount = pendingDeliveryCount;
  issue.hasPendingDelivery = pendingDeliveryCount > 0;
  issue.failedDeliveryCount = failedDeliveryCount;
  issue.hasFailedDelivery = failedDeliveryCount > 0;
  issue.messageCount = (issue.messages ?? []).length;
  if (latestMessage) {
    issue.latestMessageAt = latestMessage.occurredAt || now;
    issue.latestMessageDirection = text(latestMessage.direction);
  }
  if (latestCustomerMessage) issue.latestCustomerMessageAt = latestCustomerMessage.occurredAt || now;
  if (latestAgentMessage) issue.latestAgentMessageAt = latestAgentMessage.occurredAt || now;
  issue.needsResponse = issue.status !== 'done' && ['customer', 'visitor'].includes(text(issue.latestMessageDirection));
  issue.updated = now;
  return issue;
}

function claimIssue(issue) {
  if (!issue.assigneeEmail) issue.assigneeEmail = 'agent@example.com';
  if (issue.status === 'open') {
    issue.status = 'ongoing';
    issue.workflowStatus = 'ongoing';
  }
}

function addActivity(issue, event) {
  if ((issue.activityEvents ?? []).some(item => item.id === event.id)) return;
  issue.activityEvents = [activity(event), ...(issue.activityEvents ?? [])];
}

function appendSentTimeline(issue, reply) {
  const sourceMessageId = `outbound:${reply.id}`;
  if ((issue.messages ?? []).some(message => message.id === sourceMessageId || message.sourceMessageId === sourceMessageId)) return;
  issue.messages = [
    ...(issue.messages ?? []),
    {
      id: sourceMessageId,
      sourceMessageId,
      direction: 'agent',
      sender: reply.createdBy || reply.fromAddress || 'Support agent',
      body: reply.body,
      messageKind: 'outbound_reply',
      attachments: [],
      metadata: {
        outboundMessageId: reply.id,
        status: reply.status,
        provider: reply.provider,
        providerMessageId: reply.providerMessageId,
      },
      occurredAt: reply.sentAt || now,
    },
  ];
  issue.latestAgentMessageAt = now;
  issue.latestMessageDirection = 'agent';
  issue.latestMessageAt = now;
}

function approveReply(issue, reply) {
  claimIssue(issue);
  reply.metadata = {
    ...reply.metadata,
    approvalRequired: false,
    approved: true,
    reviewStatus: 'approved',
    approvedBy: 'agent@example.com',
    approvedAt: now,
  };
  if (reply.provider === 'channel_adapter_pending') reply.provider = 'channel_adapter_approved';
  reply.updated = now;
  addActivity(issue, {
    id: `event-${reply.id}-approved`,
    issueId: issue.id,
    eventType: 'reply_approved',
    actorEmail: 'agent@example.com',
    title: 'Reply approved',
    body: 'Human approved the prepared channel reply.',
    metadata: { replyId: reply.id },
  });
  recalculateIssueState(issue);
  return reply;
}

function requestReplyChanges(issue, reply, body) {
  const note = text(body.note) || 'Revise this draft before approval.';
  reply.metadata = {
    ...reply.metadata,
    approvalRequired: true,
    approved: false,
    reviewStatus: 'changes_requested',
    changesNote: note,
    changesRequestedBy: 'agent@example.com',
    changesRequestedAt: now,
  };
  reply.updated = now;
  addActivity(issue, {
    id: `event-${reply.id}-changes-requested`,
    issueId: issue.id,
    eventType: 'reply_changes_requested',
    actorEmail: 'agent@example.com',
    title: 'Reply changes requested',
    body: note,
    metadata: { replyId: reply.id, note },
  });
  recalculateIssueState(issue);
  return reply;
}

function reviseReplyWithAgentFixture(issue, reply, body) {
  const note = text(body.note) || text(reply.metadata?.changesNote) || 'Revise this draft before approval.';
  const answer = createAgentAnswer(issue, {
    question: `Revise reply ${reply.id}: ${note}`,
    createDraft: true,
  });
  if (answer.reply) {
    answer.reply.body = `Revised draft from smoke: ${note} We will confirm the next support update after review.`;
    answer.reply.metadata = {
      ...answer.reply.metadata,
      source: 'reply_revision',
      revisionOfReplyId: reply.id,
      revisionNote: note,
      revisionRequestedBy: text(reply.metadata?.changesRequestedBy),
      revisionRequestedAt: text(reply.metadata?.changesRequestedAt),
    };
    answer.reply.updated = now;
  }
  if (answer.run) {
    answer.run.metadata = {
      ...answer.run.metadata,
      revisionContext: {
        source: 'reply_revision',
        revisionOfReplyId: reply.id,
        revisionNote: note,
      },
    };
  }
  addActivity(issue, {
    id: `event-${reply.id}-revised`,
    issueId: issue.id,
    eventType: 'reply_revised',
    actorEmail: 'agent@example.com',
    title: 'Revision prepared',
    body: note,
    metadata: { replyId: answer.reply?.id || reply.id, revisionOfReplyId: reply.id },
  });
  recalculateIssueState(issue);
  return answer;
}

function sendReply(issue, reply) {
  if (replyNeedsApprovalFixture(reply)) approveReply(issue, reply);
  claimIssue(issue);
  const providerMessageId = reply.providerMessageId || `${reply.channel}:reply:${reply.toAddress || 'C123'}`;
  reply.status = 'sent';
  reply.provider = text(reply.metadata?.deliveryProvider) || (reply.channel === 'discord' ? 'discord_webhook' : `${reply.channel}_adapter`);
  reply.providerMessageId = providerMessageId;
  reply.error = '';
  reply.sentAt = now;
  reply.updated = now;
  reply.metadata = {
    ...reply.metadata,
    approvalRequired: false,
    approved: true,
    reviewStatus: 'approved',
    providerMessageId,
    deliveryReceipt: {
      provider: reply.provider,
      providerMessageId,
      eventType: 'matched',
      receivedAt: now,
    },
  };
  appendSentTimeline(issue, reply);
  addActivity(issue, {
    id: `event-${reply.id}-sent`,
    issueId: issue.id,
    eventType: 'reply_sent',
    actorEmail: 'agent@example.com',
    title: 'Reply sent',
    body: 'Prepared reply sent through the channel adapter.',
    metadata: {
      replyId: reply.id,
      provider: reply.provider,
      providerMessageId,
    },
  });
  recalculateIssueState(issue);
  return reply;
}

function applyApprovedAction(issue, execution) {
  const action = execution?.result?.action ?? {};
  const type = text(action.type);
  if (['triage_ticket', 'triage', 'update_issue'].includes(type)) {
    if (action.status) {
      issue.status = text(action.status);
      issue.workflowStatus = issue.status === 'done' ? 'done' : issue.status === 'ongoing' ? 'ongoing' : 'open';
    }
    if (action.priority) issue.priority = text(action.priority);
    if (action.queueName || action.queue_name) issue.queueName = text(action.queueName || action.queue_name);
    if (action.queueKey || action.queue_key) issue.queueKey = text(action.queueKey || action.queue_key);
    if (action.assigneeEmail || action.assignee_email) issue.assigneeEmail = text(action.assigneeEmail || action.assignee_email);
    if (Array.isArray(action.tags)) issue.tags = action.tags.map(text).filter(Boolean);
  }
  if (['set_custom_fields', 'set_custom_field', 'update_custom_fields'].includes(type)) {
    const fields = action.customFields || action.custom_fields || action.fields || {};
    if (fields && typeof fields === 'object' && !Array.isArray(fields)) {
      issue.customFields = { ...(issue.customFields || {}), ...fields };
    }
  }
}

function approveAction(issue, execution) {
  claimIssue(issue);
  applyApprovedAction(issue, execution);
  execution.status = 'success';
  execution.completedAt = now;
  execution.updated = now;
  execution.metadata = {
    ...execution.metadata,
    approvalRequired: false,
    reviewStatus: 'approved',
    approved: true,
    approvedBy: 'agent@example.com',
    approvedAt: now,
  };
  execution.result = {
    ...execution.result,
    approval: {
      status: 'approved',
      approvedBy: 'agent@example.com',
      approvedAt: now,
    },
  };
  addActivity(issue, {
    id: `event-${execution.id}-approved`,
    issueId: issue.id,
    eventType: 'action_approved',
    actorEmail: 'agent@example.com',
    title: 'Action approved',
    body: execution.label || 'Action approved',
    metadata: { executionId: execution.id },
  });
  recalculateIssueState(issue);
  return execution;
}

function requestIssueIds(body) {
  return Array.isArray(body?.issueIds) ? body.issueIds.map(text).filter(Boolean) : [];
}

function bulkApproveActions(body) {
  const issueIds = requestIssueIds(body);
  const failed = [];
  const items = [];
  const updatedIssues = [];
  let approved = 0;
  for (const issueId of issueIds) {
    const issue = findIssue(issueId);
    if (!issue) {
      failed.push({ id: issueId, error: 'Not found' });
      continue;
    }
    let changed = false;
    for (const execution of (issue.actionExecutions ?? []).filter(actionNeedsApprovalFixture)) {
      const approvedExecution = approveAction(issue, execution);
      approved += 1;
      changed = true;
      items.push({ issueId, executionId: execution.id, status: 'approved', error: '', execution: approvedExecution });
    }
    if (changed) updatedIssues.push(issue);
  }
  return { processed: approved + failed.length, approved, failed, items, issues: updatedIssues };
}

function bulkReviewReplies(body, send) {
  const issueIds = requestIssueIds(body);
  const failed = [];
  const items = [];
  const updatedIssues = [];
  let approved = 0;
  let sent = 0;
  for (const issueId of issueIds) {
    const issue = findIssue(issueId);
    if (!issue) {
      failed.push({ id: issueId, error: 'Not found' });
      continue;
    }
    let changed = false;
    for (const reply of (issue.outboundMessages ?? []).filter(replyNeedsApprovalFixture)) {
      const reviewedReply = send ? sendReply(issue, reply) : approveReply(issue, reply);
      approved += 1;
      if (send && reviewedReply.status === 'sent') sent += 1;
      changed = true;
      items.push({ issueId, replyId: reply.id, status: reviewedReply.status, error: '', reply: reviewedReply });
    }
    if (changed) updatedIssues.push(issue);
  }
  return { processed: approved + failed.length, approved, sent, failed, items, issues: updatedIssues };
}

function bulkRetryFailedReplies(body) {
  const issueIds = requestIssueIds(body);
  const failed = [];
  const items = [];
  const updatedIssues = [];
  let sent = 0;
  let processed = 0;
  for (const issueId of issueIds) {
    const issue = findIssue(issueId);
    if (!issue) {
      failed.push({ id: issueId, error: 'Not found' });
      processed += 1;
      continue;
    }
    const failedReplies = (issue.outboundMessages ?? []).filter(reply => reply.status === 'failed');
    if (failedReplies.length === 0) {
      failed.push({ id: issueId, error: 'No failed reply' });
      updatedIssues.push(issue);
      processed += 1;
      continue;
    }
    for (const reply of failedReplies) {
      const retried = sendReply(issue, reply);
      processed += 1;
      if (retried.status === 'sent') sent += 1;
      items.push({ issueId, replyId: reply.id, status: retried.status, error: retried.error || '', reply: retried });
    }
    updatedIssues.push(issue);
  }
  return { processed, approved: 0, sent, failed, items, issues: updatedIssues };
}

function automationActionPreview(action) {
  const actionType = text(action.type || action.action || action.kind) || 'unknown';
  const approvalRequired = action.approvalRequired !== false && action.approval_required !== false;
  const createDraft = action.createDraft !== false && action.create_draft !== false;
  const autoSendRequested = action.autoSend === true || action.auto_send === true || action.autoSendRequested === true;
  const autoSend = autoSendRequested && !approvalRequired;
  const autoSendBlocked = autoSendRequested && approvalRequired;
  const directTicketMutation = ['assign', 'set_status', 'set_priority', 'set_custom_fields', 'set_custom_field', 'update_custom_fields', 'add_note'].includes(actionType)
    || (['prepare_triage', 'prepare_custom_fields'].includes(actionType) && !approvalRequired);
  const normalizedType = ['ask_agent', 'agent_answer'].includes(actionType) ? 'prepare_agent_reply'
    : ['extract_custom_fields', 'prepare_ticket_fields'].includes(actionType) ? 'prepare_custom_fields'
      : ['triage_ticket', 'agent_triage'].includes(actionType) ? 'prepare_triage'
        : ['set_custom_field', 'update_custom_fields'].includes(actionType) ? 'set_custom_fields'
          : actionType;
  const createsCustomerReply = normalizedType === 'queue_reply'
    || (normalizedType === 'prepare_agent_reply' && (createDraft || autoSendRequested));
  const createsApprovalWork = approvalRequired && ['queue_reply', 'prepare_agent_reply', 'prepare_triage', 'prepare_custom_fields', 'record_action'].includes(normalizedType);
  const deliveryEffect = createsCustomerReply
    ? approvalRequired ? 'approval_queue' : autoSend ? 'auto_send' : 'queued_for_delivery'
    : 'none';
  const effect = directTicketMutation ? 'ticket_mutation'
    : createsApprovalWork ? 'approval_work'
      : createsCustomerReply ? 'customer_reply'
        : 'audit';
  return {
    ...action,
    type: normalizedType,
    status: 'would_run',
    action,
    createDraft,
    approvalRequired,
    autoSend,
    autoSendRequested,
    autoSendBlocked,
    directTicketMutation,
    createsApprovalWork,
    createsCustomerReply,
    approvalGate: approvalRequired ? 'required' : createsCustomerReply || directTicketMutation ? 'not_required' : 'not_applicable',
    deliveryEffect,
    effect,
    ungated: directTicketMutation || (createsCustomerReply && !approvalRequired),
  };
}

function automationPreviewSummary(actions) {
  const summary = {
    matchedActions: actions.length,
    approvalActions: actions.filter(action => action.createsApprovalWork).length,
    directTicketMutations: actions.filter(action => action.directTicketMutation).length,
    customerReplyActions: actions.filter(action => action.createsCustomerReply).length,
    autoSendActions: actions.filter(action => action.autoSend).length,
    autoSendBlocked: actions.filter(action => action.autoSendBlocked).length,
    ungatedActions: actions.filter(action => action.ungated).length,
    warnings: [],
  };
  if (summary.directTicketMutations > 0) {
    summary.warnings.push({
      key: 'direct_ticket_mutation',
      label: 'Direct ticket changes',
      detail: 'Matched actions can change ticket state without a reviewer step.',
      count: summary.directTicketMutations,
    });
  }
  if (summary.autoSendActions > 0) {
    summary.warnings.push({
      key: 'auto_send',
      label: 'Auto-send enabled',
      detail: 'Matched agent replies can be queued for delivery without approval.',
      count: summary.autoSendActions,
    });
  }
  if (summary.autoSendBlocked > 0) {
    summary.warnings.push({
      key: 'auto_send_blocked',
      label: 'Auto-send blocked',
      detail: 'Auto-send was requested but approval is still required.',
      count: summary.autoSendBlocked,
    });
  }
  return summary;
}

function previewAutomationFixture(body) {
  const issueId = text(body.issueId || body.issue_id);
  const issue = findIssue(issueId);
  if (!issue) return null;
  const trigger = text(body.trigger) || 'manual';
  const previewRule = body.previewRule && typeof body.previewRule === 'object' ? body.previewRule : null;
  const rule = previewRule || automationRules[0];
  const actions = Array.isArray(rule?.actions) ? rule.actions.map(automationActionPreview) : [];
  const summary = automationPreviewSummary(actions);
  return {
    issueId,
    trigger,
    rules: 1,
    matched: 1,
    summary,
    items: [{
      rule: {
        id: text(rule?.id) || '__current_draft__',
        name: text(rule?.name) || 'Current draft',
        active: rule?.active !== false,
        trigger,
      },
      conditions: rule?.conditions && typeof rule.conditions === 'object' ? rule.conditions : {},
      matched: true,
      actions,
    }],
  };
}

function duplicateSuggestionsFor(issueId) {
  const issue = findIssue(issueId);
  if (!issue) return [];
  const splitFromIssueId = text(issue.metadata?.splitFromIssueId);
  if (!splitFromIssueId) return [];
  const target = findIssue(splitFromIssueId);
  if (!target || target.mergedIntoIssueId) return [];
  return [{
    issue: issueSummary(target),
    score: 96,
    reasons: ['split source', 'same account', 'same channel'],
  }];
}

function splitIssueMessageFixture(sourceIssue, body) {
  const messageId = text(body.messageId);
  const messages = Array.isArray(sourceIssue.messages) ? sourceIssue.messages : [];
  if (messages.length <= 1 || !messageId) return null;
  const message = messages.find(item => messageMatches(item, messageId));
  if (!message) return null;
  const newIssueId = `issue-split-smoke-${splitSequence++}`;
  const splitSubject = text(body.subject) || `Split: ${sourceIssue.subject || newIssueId}`;
  const assigneeEmail = text(sourceIssue.assigneeEmail) || 'agent@example.com';
  const splitMessage = {
    ...message,
    metadata: {
      ...(message.metadata || {}),
      splitFromIssueId: sourceIssue.id,
      splitToIssueId: newIssueId,
    },
  };
  sourceIssue.messages = messages.filter(item => !messageMatches(item, messageId));
  addActivity(sourceIssue, {
    id: `event-${newIssueId}-split-out`,
    issueId: sourceIssue.id,
    eventType: 'message_split_out',
    actorEmail: 'agent@example.com',
    title: 'Message split out',
    body: splitSubject,
    metadata: {
      splitTargetIssueId: newIssueId,
      splitFromMessageId: message.id || '',
      splitFromSourceMessageId: message.sourceMessageId || '',
      note: text(body.note),
    },
  });
  const newIssue = baseIssue({
    id: newIssueId,
    accountId: sourceIssue.accountId,
    contactId: sourceIssue.contactId,
    sourceEmailId: `split:${sourceIssue.id}:${message.id || message.sourceMessageId || messageId}:${newIssueId}`,
    chatId: `split:${sourceIssue.id}:${newIssueId}`,
    status: 'open',
    workflowStatus: 'open',
    priority: sourceIssue.priority,
    assigneeEmail,
    queueKey: sourceIssue.queueKey,
    queueName: sourceIssue.queueName,
    tags: uniqueTags(sourceIssue.tags, ['split']),
    accountName: sourceIssue.accountName,
    accountDomain: sourceIssue.accountDomain,
    contactEmail: sourceIssue.contactEmail,
    contactName: sourceIssue.contactName,
    subject: splitSubject,
    fromAddress: sourceIssue.fromAddress,
    channel: sourceIssue.channel,
    source: sourceIssue.source,
    aiSummary: `Split from ${sourceIssue.subject || sourceIssue.id}.`,
    activatedIntent: sourceIssue.activatedIntent,
    duplicateSuggestionCount: 1,
    topDuplicateScore: 96,
    topDuplicateIssueId: sourceIssue.id,
    topDuplicateIssueSubject: sourceIssue.subject,
    metadata: {
      ...(sourceIssue.metadata || {}),
      splitFromIssueId: sourceIssue.id,
      splitFromMessageId: message.id || '',
      splitFromSourceMessageId: message.sourceMessageId || '',
      splitBy: 'agent@example.com',
      splitAt: now,
      splitNote: text(body.note),
    },
    messages: [splitMessage],
    activityEvents: [
      activity({
        id: `event-${newIssueId}-split-from`,
        issueId: newIssueId,
        eventType: 'issue_split_from',
        actorEmail: 'agent@example.com',
        title: 'Issue split from ticket',
        body: sourceIssue.subject || sourceIssue.id,
        metadata: { sourceIssueId: sourceIssue.id, sourceMessageId: message.sourceMessageId || message.id || '' },
      }),
    ],
    assignmentHistory: [{
      id: `assignment-${newIssueId}`,
      issueId: newIssueId,
      assigneeEmail,
      assignedBy: 'agent@example.com',
      status: 'assigned',
      created: now,
    }],
    knowledgeSuggestions: sourceIssue.knowledgeSuggestions ?? [],
  });
  recalculateIssueState(sourceIssue);
  recalculateIssueState(newIssue);
  issues.unshift(newIssue);
  return newIssue;
}

function mergeIssuesFixture(sourceIssue, body) {
  const targetIssueId = text(body.targetIssueId);
  const target = findIssue(targetIssueId);
  if (!target || target.id === sourceIssue.id) return null;
  const sourceMessages = Array.isArray(sourceIssue.messages) ? sourceIssue.messages : [];
  const existingMessageIds = new Set((target.messages ?? []).flatMap(message => [message.id, message.sourceMessageId].filter(Boolean)));
  target.messages = [
    ...(target.messages ?? []),
    ...sourceMessages.filter(message => !existingMessageIds.has(message.id) && !existingMessageIds.has(message.sourceMessageId)),
  ];
  target.tags = uniqueTags(target.tags, sourceIssue.tags);
  target.duplicateSuggestionCount = Math.max(0, (target.duplicateSuggestionCount ?? 0) - 1);
  addActivity(target, {
    id: `event-${sourceIssue.id}-merged-into-${target.id}`,
    issueId: target.id,
    eventType: 'issue_merged',
    actorEmail: 'agent@example.com',
    title: 'Issue merged',
    body: `${sourceIssue.subject || sourceIssue.id} merged into this ticket.`,
    metadata: {
      sourceIssueId: sourceIssue.id,
      note: text(body.note),
    },
  });
  sourceIssue.mergedIntoIssueId = target.id;
  sourceIssue.mergedAt = now;
  sourceIssue.mergedBy = 'agent@example.com';
  sourceIssue.mergeNote = text(body.note);
  sourceIssue.status = 'done';
  sourceIssue.workflowStatus = 'done';
  const sourceIndex = issues.findIndex(item => item.id === sourceIssue.id);
  if (sourceIndex >= 0) issues.splice(sourceIndex, 1);
  recalculateIssueState(target);
  return target;
}

function createAgentAnswer(issue, body) {
  const question = text(body?.question) || 'Find answer';
  const createDraft = body?.createDraft === true;
  const approvalRequired = body?.approvalRequired !== false;
  const autoSendRequested = body?.autoSend === true;
  const effectiveAutoSend = createDraft && autoSendRequested && !approvalRequired;
  const answer = 'Live agent answer from smoke: acknowledge the API incident, ask for one failing request ID, and avoid promising an ETA until engineering confirms.';
  const accountContext = accountContextFixture(issue);
  const run = {
    id: `ai-smoke-agent-${agentRunSequence++}`,
    issueId: issue.id,
    runKey: `agent_answer:${issue.id}:smoke:${agentRunSequence}`,
    source: 'agent_answer',
    status: 'success',
    activatedIntent: issue.activatedIntent || 'incident_response',
    requiresHuman: createDraft,
    summary: answer,
    identityResult: {},
    intentResult: { accountContext },
    securityResult: {},
    tokenUsage: { totalTokens: 318 },
    toolCalls: [],
    metadata: {
      kind: 'agent_answer',
      question,
      answer,
      confidence: 'high',
      citations: [knowledgeArticle],
      accountContext,
      autoSend: effectiveAutoSend,
      autoSendRequested,
      autoSendPolicy: effectiveAutoSend ? 'approval_not_required' : autoSendRequested ? 'approval_required' : '',
      autoSendBlockedReason: autoSendRequested && !effectiveAutoSend ? 'approval_required' : '',
    },
    startedAt: now,
    completedAt: now,
    created: now,
    updated: now,
  };
  issue.aiRuns = [run, ...(issue.aiRuns ?? [])];
  let reply = null;
  if (createDraft) {
    reply = outbound({
      id: `reply-smoke-agent-${agentReplySequence++}`,
      issueId: issue.id,
      channel: issue.channel,
      toAddress: issue.channel === 'discord' ? 'C123' : issue.fromAddress,
      subject: `Re: ${issue.subject}`,
      body: answer,
      status: effectiveAutoSend ? 'queued' : 'draft',
      provider: effectiveAutoSend ? 'channel_adapter_pending' : 'manual_draft',
      metadata: {
        approvalRequired,
        approved: !approvalRequired,
        reviewStatus: approvalRequired ? 'pending' : 'approved',
        source: 'agent_answer',
        confidence: 'high',
        citations: [knowledgeArticle],
        accountContext,
        autoSend: effectiveAutoSend,
        autoSendRequested,
        autoSendPolicy: effectiveAutoSend ? 'approval_not_required' : autoSendRequested ? 'approval_required' : '',
        autoSendBlockedReason: autoSendRequested && !effectiveAutoSend ? 'approval_required' : '',
      },
    });
    issue.outboundMessages = [reply, ...(issue.outboundMessages ?? [])];
  }
  recalculateIssueState(issue);
  return {
    answer,
    confidence: 'high',
    citations: [knowledgeArticle],
    reply,
    run,
    approvalRequired: createDraft && approvalRequired,
    priorAgentRunIds: ['ai-discord-answer'],
    accountContext,
    includeFeedbackLink: false,
    generationMode: 'smoke_fixture',
    generationError: '',
    knowledgeGap: null,
    automationContext: { source: 'cmux_smoke' },
    autoSend: effectiveAutoSend,
    autoSendRequested,
    autoSendPolicy: effectiveAutoSend ? 'approval_not_required' : autoSendRequested ? 'approval_required' : '',
    autoSendBlockedReason: autoSendRequested && !effectiveAutoSend ? 'approval_required' : '',
  };
}

function webChatSessionByKey(sessionKey) {
  return webChatSessions.find(session => session.sessionKey === sessionKey) || null;
}

function webChatSessionMessages(session) {
  const issueIds = Array.isArray(session.issueIds) && session.issueIds.length > 0
    ? session.issueIds
    : [session.issueId].filter(Boolean);
  return issueIds
    .flatMap((issueId) => {
      const issue = findIssue(issueId);
      return (issue?.messages ?? []).map((message) => ({ ...message, issueId }));
    })
    .sort((a, b) => String(a.occurredAt || '').localeCompare(String(b.occurredAt || '')));
}

function webChatSessionResponse(session) {
  const issue = findIssue(session.issueId);
  const messages = webChatSessionMessages(session);
  return {
    ...session,
    issueIds: Array.isArray(session.issueIds) ? session.issueIds : [session.issueId].filter(Boolean),
    latestIssueId: session.issueId,
    messageCount: messages.length,
    issue: issue || null,
    messages,
  };
}

function createWebChatTicket(body) {
  const sequence = webChatSequence++;
  const channelKey = text(body.channelKey) || 'web-main';
  const visitorName = text(body.visitorName) || text(body.visitor_id) || 'Website visitor';
  const visitorEmail = text(body.visitorEmail) || text(body.senderEmail) || `visitor-${sequence}@example.com`;
  const initialMessage = text(body.initialMessage) || 'Need help from web chat.';
  const sessionId = `session-web-chat-smoke-${sequence}`;
  const sessionKey = `web-session-smoke-${sequence}`;
  const issueId = `issue-web-chat-smoke-${sequence}`;
  const messageId = `msg-web-chat-smoke-${sequence}`;
  const pageUrl = text(body.pageUrl) || `${apiUrl}/support/web-chat/project1?channel_key=${encodeURIComponent(channelKey)}`;
  const issue = baseIssue({
    id: issueId,
    accountId: 'account-web-chat',
    contactId: 'contact-web-chat-smoke',
    sourceEmailId: `web-chat:${sessionKey}`,
    chatId: `web-chat:${sessionKey}`,
    status: 'open',
    workflowStatus: 'open',
    priority: 'normal',
    assigneeEmail: 'agent@example.com',
    queueKey: 'support',
    queueName: 'Support',
    accountName: 'Website Visitors',
    accountDomain: visitorEmail.includes('@') ? visitorEmail.split('@').at(-1) : 'website.test',
    contactEmail: visitorEmail,
    contactName: visitorName,
    subject: `Web chat from ${visitorName}`,
    fromAddress: visitorEmail,
    channel: 'web_chat',
    source: channelKey,
    aiSummary: 'Visitor opened a web chat ticket. AI prepared a first response and routed it to the support queue.',
    activatedIntent: 'incident_response',
    latestMessageDirection: 'visitor',
    latestCustomerMessageAt: now,
    needsResponse: true,
    metadata: {
      provider: 'web_chat',
      channelKey,
      webChatSessionId: sessionId,
      sessionKey,
      pageUrl,
    },
    messages: [
      {
        id: messageId,
        sourceMessageId: `web-chat:${sessionId}:${messageId}`,
        direction: 'visitor',
        sender: visitorName,
        body: initialMessage,
        messageKind: 'web_chat_message',
        attachments: [],
        metadata: {
          provider: 'web_chat',
          channelKey,
          webChatSessionId: sessionId,
          sessionKey,
          pageUrl,
          source: 'hosted_web_chat',
        },
        occurredAt: now,
      },
    ],
    outboundMessages: [
      outbound({
        id: `reply-web-chat-smoke-${sequence}`,
        issueId,
        channel: 'web_chat',
        toAddress: sessionKey,
        subject: `Re: Web chat from ${visitorName}`,
        body: `Thanks ${visitorName}. We have your web chat ticket and are checking this now.`,
        status: 'queued',
        provider: 'channel_adapter_pending',
        metadata: {
          approvalRequired: true,
          approved: false,
          reviewStatus: 'pending',
          source: 'web_chat_agent_autopilot',
          channelKey,
          webChatSessionId: sessionId,
          deliveryProvider: 'web_chat_internal',
          replyTarget: { channel: 'web_chat', key: 'sessionKey', value: sessionKey, label: `Web chat: ${sessionKey}` },
        },
      }),
    ],
    aiRuns: [
      {
        id: `ai-web-chat-smoke-${sequence}`,
        issueId,
        runKey: `agent_answer:${issueId}`,
        source: 'agent_answer',
        status: 'success',
        activatedIntent: 'incident_response',
        requiresHuman: true,
        summary: 'Answer the visitor, confirm the ticket is open, and keep the reply pending for human approval.',
        identityResult: {},
        intentResult: {},
        securityResult: {},
        tokenUsage: { totalTokens: 318 },
        toolCalls: [],
        prompt: 'Prepare first web chat response.',
        output: `Thanks ${visitorName}. We have your web chat ticket and are checking this now.`,
        confidence: 'high',
        metadata: {
          kind: 'agent_answer',
          question: 'Prepare web chat reply',
          answer: `Thanks ${visitorName}. We have your web chat ticket and are checking this now.`,
          confidence: 'high',
          channelKey,
          webChatSessionId: sessionId,
        },
        startedAt: now,
        completedAt: now,
        created: now,
        updated: now,
      },
    ],
    activityEvents: [
      activity({
        id: `event-web-chat-started-${sequence}`,
        issueId,
        eventType: 'web_chat_started',
        actorEmail: visitorEmail,
        title: 'Web chat started',
        body: initialMessage,
        metadata: { channelKey, webChatSessionId: sessionId, sessionKey },
      }),
    ],
  });
  recalculateIssueState(issue);
  issues.unshift(issue);
  const session = {
    id: sessionId,
    tenantId: 'tenant1',
    projectId: 'project1',
    issueId,
    channelKey,
    sessionKey,
    visitorId: text(body.visitorId) || `visitor-${sequence}`,
    visitorEmail,
    visitorName,
    pageUrl,
    status: 'open',
    issueIds: [issueId],
    metadata: {
      ...(body.metadata && typeof body.metadata === 'object' ? body.metadata : { source: 'hosted_web_chat' }),
      issueIds: [issueId],
      latestIssueId: issueId,
      ticketCreationMode: 'per_message',
    },
    created: now,
    updated: now,
  };
  webChatSessions.unshift(session);
  return webChatSessionResponse(session);
}

function createWebChatMessage(sessionKey, body) {
  const session = webChatSessionByKey(sessionKey);
  if (!session) return null;
  const sequence = webChatSequence++;
  const issueId = `issue-web-chat-smoke-${sequence}`;
  const messageId = `msg-web-chat-smoke-${sequence}`;
  const messageBody = text(body.body) || 'Follow-up web chat message.';
  const message = {
    id: messageId,
    sourceMessageId: `web-chat:${session.id}:${messageId}`,
    direction: 'visitor',
    sender: text(body.senderName) || session.visitorName || 'Website visitor',
    body: messageBody,
    messageKind: 'web_chat_message',
    attachments: [],
    metadata: {
      provider: 'web_chat',
      channelKey: session.channelKey,
      webChatSessionId: session.id,
      sessionKey,
    },
    occurredAt: now,
  };
  const issue = baseIssue({
    id: issueId,
    accountId: 'account-web-chat',
    contactId: 'contact-web-chat-smoke',
    sourceEmailId: `web-chat:${sessionKey}:${messageId}`,
    chatId: `web-chat:${sessionKey}:${messageId}`,
    status: 'open',
    workflowStatus: 'open',
    priority: 'normal',
    assigneeEmail: 'agent@example.com',
    queueKey: 'support',
    queueName: 'Support',
    accountName: 'Website Visitors',
    accountDomain: session.visitorEmail.includes('@') ? session.visitorEmail.split('@').at(-1) : 'website.test',
    contactEmail: session.visitorEmail,
    contactName: session.visitorName,
    subject: `Web chat from ${session.visitorName || 'Website visitor'}`,
    fromAddress: session.visitorEmail,
    channel: 'web_chat',
    source: session.channelKey,
    aiSummary: messageBody,
    latestMessageDirection: 'visitor',
    latestCustomerMessageAt: now,
    needsResponse: true,
    metadata: {
      provider: 'web_chat',
      channelKey: session.channelKey,
      webChatSessionId: session.id,
      sessionKey,
      ticketCreationMode: 'per_message',
    },
    messages: [message],
    activityEvents: [
      activity({
        id: `event-web-chat-message-${sequence}`,
        issueId,
        eventType: 'web_chat_message_received',
        actorEmail: session.visitorEmail,
        title: 'Web chat message received',
        body: messageBody,
        metadata: { channelKey: session.channelKey, webChatSessionId: session.id, sessionKey, ticketCreationMode: 'per_message' },
      }),
    ],
  });
  recalculateIssueState(issue);
  issues.unshift(issue);
  session.issueId = issueId;
  session.issueIds = Array.from(new Set([...(session.issueIds ?? []), issueId]));
  session.metadata = {
    ...(session.metadata ?? {}),
    issueIds: session.issueIds,
    latestIssueId: issueId,
    ticketCreationMode: 'per_message',
  };
  session.updated = now;
  return { ...message, issue };
}

function portalSessionResponse(session) {
  return {
    id: session.id,
    issueId: session.issueId,
    status: session.status,
    expiresAt: session.expiresAt,
    lastAccessedAt: session.lastAccessedAt || '',
    createdBy: session.createdBy,
    metadata: session.metadata || {},
    created: session.created,
    updated: session.updated,
    url: session.url,
    apiUrl: session.apiUrl,
  };
}

function createPortalSessionFixture(issue) {
  const sequence = portalSequence++;
  const token = `portal-smoke-${sequence}`;
  const session = {
    id: `portal-session-smoke-${sequence}`,
    issueId: issue.id,
    status: 'active',
    expiresAt: '2026-07-12T10:30:00.000Z',
    lastAccessedAt: '',
    createdBy: 'agent@example.com',
    metadata: { source: 'cmux_smoke' },
    created: now,
    updated: now,
    token,
    url: `${apiUrl}/support/portal/${token}`,
    apiUrl: `${apiUrl}/api/support/portal/${token}`,
  };
  portalSessionsByToken.set(token, session);
  issue.portalSessions = [portalSessionResponse(session), ...(issue.portalSessions ?? [])];
  addActivity(issue, {
    id: `event-${session.id}-created`,
    issueId: issue.id,
    eventType: 'portal_session_created',
    actorEmail: 'agent@example.com',
    title: 'Customer portal link created',
    body: 'Agent created a customer-facing ticket portal link.',
    metadata: { portalSessionId: session.id },
  });
  return portalSessionResponse(session);
}

function portalFixture(token) {
  const session = portalSessionsByToken.get(token);
  if (!session) return null;
  const issue = findIssue(session.issueId);
  if (!issue) return null;
  session.lastAccessedAt = now;
  session.updated = now;
  const feedback = (issue.csatFeedback ?? []).find(item => item.portalSessionId === session.id) || null;
  return {
    session: portalSessionResponse(session),
    issue: {
      ...issue,
      messages: (issue.messages ?? []).filter(message => text(message.direction) !== 'internal'),
      outboundMessages: [],
      notes: [],
      aiRuns: [],
      actionExecutions: [],
    },
    feedback,
  };
}

function createPortalMessageFixture(token, body) {
  const fixture = portalFixture(token);
  if (!fixture) return null;
  const issue = findIssue(fixture.session.issueId);
  if (!issue) return null;
  const messageId = `msg-portal-smoke-${portalSequence++}`;
  const senderEmail = text(body.senderEmail) || text(body.sender_email) || issue.contactEmail || 'customer@example.com';
  const senderName = text(body.senderName) || text(body.sender_name) || issue.contactName || senderEmail;
  const message = {
    id: messageId,
    sourceMessageId: `portal:${fixture.session.id}:${messageId}`,
    direction: 'customer',
    sender: senderName,
    body: text(body.body) || 'Portal follow-up message.',
    messageKind: 'portal_message',
    attachments: [],
    metadata: {
      source: 'customer_portal',
      portalSessionId: fixture.session.id,
    },
    occurredAt: now,
  };
  issue.messages = [...(issue.messages ?? []), message];
  if (issue.status === 'done') {
    issue.status = issue.assigneeEmail ? 'ongoing' : 'open';
    issue.workflowStatus = issue.status;
  }
  addActivity(issue, {
    id: `event-${messageId}-received`,
    issueId: issue.id,
    eventType: 'portal_message_received',
    actorEmail: senderEmail,
    title: 'Customer portal message received',
    body: message.body,
    metadata: { portalSessionId: fixture.session.id, messageId },
  });
  recalculateIssueState(issue);
  return message;
}

function createPortalFeedbackFixture(token, body) {
  const fixture = portalFixture(token);
  if (!fixture) return null;
  const issue = findIssue(fixture.session.issueId);
  if (!issue) return null;
  const rating = Number(body.rating || 0);
  const feedbackId = `csat-portal-smoke-${fixture.session.id}`;
  const senderEmail = text(body.senderEmail) || text(body.sender_email) || issue.contactEmail || 'customer@example.com';
  const senderName = text(body.senderName) || text(body.sender_name) || issue.contactName || senderEmail;
  const feedback = {
    id: feedbackId,
    issueId: issue.id,
    portalSessionId: fixture.session.id,
    rating,
    comment: text(body.comment),
    customerEmail: senderEmail,
    customerName: senderName,
    source: 'customer_portal',
    metadata: { source: 'cmux_smoke' },
    receivedAt: now,
    created: now,
    updated: now,
  };
  issue.csatFeedback = [
    feedback,
    ...(issue.csatFeedback ?? []).filter(item => item.portalSessionId !== fixture.session.id),
  ];
  issue.csatFeedbackCount = issue.csatFeedback.length;
  issue.lowCsatFeedbackCount = issue.csatFeedback.filter(item => item.rating > 0 && item.rating <= 2).length;
  issue.hasLowCsatFeedback = issue.lowCsatFeedbackCount > 0;
  issue.latestCsatRating = rating;
  issue.latestCsatComment = feedback.comment;
  issue.latestCsatReceivedAt = now;
  if (rating > 0 && rating <= 2) {
    issue.tags = uniqueTags(issue.tags, ['low-csat']);
    if (['low', 'normal'].includes(issue.priority)) issue.priority = 'high';
    if (issue.status === 'done') {
      issue.status = issue.assigneeEmail ? 'ongoing' : 'open';
      issue.workflowStatus = issue.status;
    }
  }
  addActivity(issue, {
    id: `event-${feedbackId}-received`,
    issueId: issue.id,
    eventType: 'csat_received',
    actorEmail: senderEmail,
    title: 'Customer satisfaction received',
    body: `${rating}/5${feedback.comment ? ` - ${feedback.comment}` : ''}`,
    metadata: { portalSessionId: fixture.session.id, rating },
  });
  recalculateIssueState(issue);
  return feedback;
}

function renderPortalPage(token) {
  const fixture = portalFixture(token);
  if (!fixture) return '';
  const issue = fixture.issue;
  const feedback = fixture.feedback || {};
  const rating = Number(feedback.rating || 0);
  const messages = (issue.messages ?? []).map(message => `
    <article class="message ${escapeHtml(message.direction)}">
      <div class="meta">${escapeHtml(message.sender || message.direction)} · ${escapeHtml(message.occurredAt || '')}</div>
      <pre>${escapeHtml(message.body || '')}</pre>
    </article>
  `).join('') || '<div class="empty">No messages yet.</div>';
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${escapeHtml(issue.subject || 'Support request')}</title>
  <style>
    body { margin: 0; background: #f8fafc; color: #111827; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    main { max-width: 820px; margin: 0 auto; padding: 28px 16px; display: grid; gap: 14px; }
    section, article { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; }
    h1 { margin: 8px 0; font-size: 24px; line-height: 1.25; }
    label { display: block; font-size: 13px; font-weight: 600; margin: 10px 0 6px; }
    input, textarea { width: 100%; box-sizing: border-box; border: 1px solid #cbd5e1; border-radius: 6px; padding: 10px; font: inherit; }
    button { margin-top: 10px; border: 0; border-radius: 6px; background: #111827; color: white; padding: 10px 14px; font: inherit; cursor: pointer; }
    .article-button, .rating button { border: 1px solid #cbd5e1; background: white; color: #111827; }
    .article-button { display: block; width: 100%; text-align: left; }
    .rating { display: flex; flex-wrap: wrap; gap: 8px; }
    .rating button.active { background: #111827; color: white; }
    .meta, .subtle { color: #64748b; font-size: 12px; }
    .stack { display: grid; gap: 10px; }
    .ok { color: #166534; font-size: 14px; margin-top: 8px; }
    .error { color: #b91c1c; font-size: 14px; margin-top: 8px; }
    pre { white-space: pre-wrap; font: inherit; margin: 0; line-height: 1.5; }
  </style>
</head>
<body>
  <main>
    <header>
      <div class="meta">Customer portal</div>
      <h1>${escapeHtml(issue.subject || 'Support request')}</h1>
      <div class="subtle">${escapeHtml(issue.accountName || issue.contactEmail || '')}</div>
    </header>
    <section>
      <div class="meta">Summary</div>
      <pre>${escapeHtml(issue.aiSummary || 'Support is reviewing this request.')}</pre>
    </section>
    <section class="stack">${messages}</section>
    <section>
      <div class="meta">Help articles</div>
      <button type="button" class="article-button" data-article-id="${escapeHtml(knowledgeArticle.id)}">
        <strong>${escapeHtml(knowledgeArticle.title)}</strong>
        <div class="subtle">${escapeHtml(knowledgeArticle.excerpt || 'Known response guidance')}</div>
      </button>
      <article id="helpArticle" style="display:none;margin-top:10px"></article>
    </section>
    <section>
      <div class="meta">Reply</div>
      <label for="senderEmail">Email</label>
      <input id="senderEmail" type="email" value="${escapeHtml(issue.contactEmail || '')}" />
      <label for="body">Message</label>
      <textarea id="body" rows="5"></textarea>
      <button id="send" type="button">Send message</button>
      <div id="status"></div>
    </section>
    <section>
      <div class="meta">Satisfaction</div>
      <div class="rating" id="rating">
        ${[1, 2, 3, 4, 5].map(value => `<button type="button" data-rating="${value}" class="${rating === value ? 'active' : ''}">${value}</button>`).join('')}
      </div>
      <label for="feedbackComment">Comment</label>
      <textarea id="feedbackComment" rows="3">${escapeHtml(feedback.comment || '')}</textarea>
      <button id="submitFeedback" type="button">Save rating</button>
      <div id="feedbackStatus"></div>
    </section>
  </main>
  <script>
    const portalToken = ${JSON.stringify(token)};
    let selectedRating = ${JSON.stringify(rating)};
    const statusEl = document.getElementById('status');
    const feedbackStatusEl = document.getElementById('feedbackStatus');
    document.querySelector('[data-article-id]').addEventListener('click', () => {
      const article = document.getElementById('helpArticle');
      article.style.display = 'block';
      article.innerHTML = '<strong>${escapeHtml(knowledgeArticle.title)}</strong><pre style="margin-top:8px">${escapeHtml(knowledgeArticle.body || knowledgeArticle.excerpt || '')}</pre>';
    });
    document.getElementById('rating').addEventListener('click', event => {
      const target = event.target;
      if (!(target instanceof HTMLButtonElement)) return;
      selectedRating = Number(target.dataset.rating || '0');
      for (const item of document.querySelectorAll('#rating button')) item.classList.remove('active');
      target.classList.add('active');
    });
    document.getElementById('send').addEventListener('click', async () => {
      const body = document.getElementById('body').value.trim();
      const senderEmail = document.getElementById('senderEmail').value.trim();
      if (!body) {
        statusEl.className = 'error';
        statusEl.textContent = 'Message required.';
        return;
      }
      const res = await fetch('/api/support/portal/' + encodeURIComponent(portalToken) + '/messages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ body, senderEmail })
      });
      statusEl.className = res.ok ? 'ok' : 'error';
      statusEl.textContent = res.ok ? 'Message sent.' : 'Could not send message.';
    });
    document.getElementById('submitFeedback').addEventListener('click', async () => {
      const comment = document.getElementById('feedbackComment').value.trim();
      const senderEmail = document.getElementById('senderEmail').value.trim();
      if (!selectedRating) {
        feedbackStatusEl.className = 'error';
        feedbackStatusEl.textContent = 'Rating required.';
        return;
      }
      const res = await fetch('/api/support/portal/' + encodeURIComponent(portalToken) + '/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rating: selectedRating, comment, senderEmail })
      });
      feedbackStatusEl.className = res.ok ? 'ok' : 'error';
      feedbackStatusEl.textContent = res.ok ? 'Rating saved.' : 'Could not save rating.';
    });
  </script>
</body>
</html>`;
}

function publicKnowledgeArticlesFixture(query = '') {
  const needle = text(query).trim().toLowerCase();
  return knowledgeArticles
    .filter(article => article.public && article.status === 'published')
    .filter(article => !needle || [article.title, article.body, ...(article.tags ?? [])].join(' ').toLowerCase().includes(needle))
    .map(article => ({
      id: article.id,
      title: article.title,
      excerpt: article.body.length > 180 ? `${article.body.slice(0, 177)}...` : article.body,
      tags: article.tags ?? [],
      status: 'published',
      updated: article.updated || now,
    }));
}

function renderPublicKnowledgePage(query = '') {
  const articles = publicKnowledgeArticlesFixture(query);
  const articleHtml = articles.map(article => `
    <article class="article" data-public-knowledge-article="${escapeHtml(article.id)}">
      <a href="/support/knowledge/project1/articles/${encodeURIComponent(article.id)}">
        <h2>${escapeHtml(article.title)}</h2>
      </a>
      <p>${escapeHtml(article.excerpt)}</p>
      <div class="tags">${(article.tags ?? []).map(tag => `<span>${escapeHtml(tag)}</span>`).join('')}</div>
    </article>
  `).join('') || '<div class="empty">No public articles found.</div>';
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Support knowledge</title>
  <style>
    body { margin: 0; background: #f8fafc; color: #111827; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    main { max-width: 820px; margin: 0 auto; padding: 28px 16px; display: grid; gap: 14px; }
    .article, header { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; }
    h1 { margin: 8px 0; font-size: 24px; }
    h2 { margin: 0 0 8px; font-size: 18px; }
    a { color: #111827; text-decoration: none; }
    .subtle, p { color: #64748b; }
    .tags { display: flex; flex-wrap: wrap; gap: 6px; }
    .tags span { border: 1px solid #cbd5e1; border-radius: 999px; padding: 2px 8px; font-size: 12px; }
  </style>
</head>
<body>
  <main>
    <header>
      <div class="subtle">Help center</div>
      <h1>Support knowledge</h1>
      <div class="subtle">Search published support articles.</div>
    </header>
    ${articleHtml}
  </main>
</body>
</html>`;
}

function renderPublicKnowledgeArticlePage(articleId) {
  const article = knowledgeArticles.find(item => item.id === articleId && item.public && item.status === 'published');
  if (!article) return '';
  return `<!doctype html>
<html lang="en">
<head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /><title>${escapeHtml(article.title)}</title></head>
<body>
  <main data-public-knowledge-article="${escapeHtml(article.id)}">
    <a href="/support/knowledge/project1">Back</a>
    <h1>${escapeHtml(article.title)}</h1>
    <pre>${escapeHtml(article.body)}</pre>
  </main>
</body>
</html>`;
}

function renderWebChatPage(projectId, channelKey) {
  const safeProjectId = escapeHtml(projectId);
  const safeChannelKey = escapeHtml(channelKey);
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Support chat</title>
  <style>
    body { margin: 0; background: #f8fafc; color: #111827; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    main { max-width: 520px; margin: 0 auto; padding: 24px 16px; display: grid; gap: 12px; }
    section, article { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; }
    label { display: block; font-size: 13px; font-weight: 600; margin: 10px 0 6px; }
    input, textarea { width: 100%; box-sizing: border-box; border: 1px solid #cbd5e1; border-radius: 6px; padding: 10px; font: inherit; }
    button { margin-top: 10px; border: 0; border-radius: 6px; background: #111827; color: white; padding: 10px 14px; font: inherit; cursor: pointer; }
    .meta { color: #64748b; font-size: 12px; }
    .error { color: #b91c1c; }
    pre { white-space: pre-wrap; font: inherit; margin: 6px 0 0; line-height: 1.5; }
  </style>
</head>
<body>
  <main>
    <section>
      <div class="meta">Support chat · ${safeChannelKey}</div>
      <h1>Support chat</h1>
      <label for="name">Name</label>
      <input id="name" autocomplete="name" />
      <label for="email">Email</label>
      <input id="email" type="email" autocomplete="email" />
      <label for="body">Message</label>
      <textarea id="body" rows="5"></textarea>
      <button id="send" type="button">Start chat</button>
      <div id="status" role="status"></div>
    </section>
    <section id="messages"></section>
  </main>
  <script>
    const projectId = ${JSON.stringify(projectId)};
    const channelKey = ${JSON.stringify(channelKey)};
    let sessionKey = window.localStorage.getItem('supportWebChatSession:' + projectId + ':' + channelKey) || '';
    const statusEl = document.getElementById('status');
    const sendEl = document.getElementById('send');
    const messagesEl = document.getElementById('messages');
    function esc(value) {
      return String(value || '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
    }
    function render(data) {
      const messages = Array.isArray(data.messages) ? data.messages : data.issue && Array.isArray(data.issue.messages) ? data.issue.messages : [];
      messagesEl.innerHTML = messages.map((message) => '<article><div class="meta">' + esc(message.sender || message.direction) + '</div><pre>' + esc(message.body || '') + '</pre></article>').join('');
    }
    async function refresh() {
      if (!sessionKey) return;
      const res = await fetch('/api/support/web-chat/sessions/' + encodeURIComponent(sessionKey));
      if (!res.ok) return;
      const data = await res.json();
      const issueIds = Array.isArray(data.issueIds) ? data.issueIds : [data.issueId].filter(Boolean);
      const messageCount = typeof data.messageCount === 'number' ? data.messageCount : Array.isArray(data.messages) ? data.messages.length : 0;
      const ticketLabel = issueIds.length === 1 ? '1 ticket' : issueIds.length + ' tickets';
      const messageLabel = messageCount === 1 ? '1 message' : messageCount + ' messages';
      statusEl.textContent = 'Ticket opened: ' + data.issueId + ' - ' + ticketLabel + ' - ' + messageLabel;
      render(data);
    }
    sendEl.addEventListener('click', async () => {
      const body = document.getElementById('body').value.trim();
      const visitorName = document.getElementById('name').value.trim();
      const visitorEmail = document.getElementById('email').value.trim();
      if (!body) {
        statusEl.className = 'error';
        statusEl.textContent = 'Message required.';
        return;
      }
      sendEl.disabled = true;
      try {
        if (!sessionKey) {
          const res = await fetch('/api/support/web-chat/' + encodeURIComponent(projectId) + '/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ channelKey, visitorName, visitorEmail, initialMessage: body, pageUrl: window.location.href, metadata: { source: 'hosted_web_chat' } })
          });
          if (!res.ok) throw new Error('Could not start chat.');
          const data = await res.json();
          sessionKey = data.sessionKey;
          window.localStorage.setItem('supportWebChatSession:' + projectId + ':' + channelKey, sessionKey);
        } else {
          const res = await fetch('/api/support/web-chat/sessions/' + encodeURIComponent(sessionKey) + '/messages', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ body, senderName: visitorName, senderEmail: visitorEmail })
          });
          if (!res.ok) throw new Error('Could not send message.');
        }
        document.getElementById('body').value = '';
        await refresh();
      } catch (error) {
        statusEl.className = 'error';
        statusEl.textContent = error instanceof Error ? error.message : 'Could not send message.';
      } finally {
        sendEl.disabled = false;
      }
    });
    void refresh();
  </script>
</body>
</html>`;
}

function renderWebChatEmbedScript(projectId, channelKey) {
  return `(() => {
  const iframe = document.createElement('iframe');
  iframe.src = ${JSON.stringify(`${apiUrl}/support/web-chat/${projectId}?channel_key=${encodeURIComponent(channelKey)}`)};
  iframe.title = 'Support chat';
  iframe.setAttribute('data-automail-support-chat', ${JSON.stringify(`${projectId}:${channelKey}`)});
  document.body.appendChild(iframe);
})();`;
}

const channelFixtures = [
  {
    id: 'channel-discord-main',
    key: 'discord-main',
    type: 'discord',
    name: 'Discord main',
    targetId: 'C123',
    provider: 'discord',
    deliveryProvider: 'discord_webhook',
    eventType: 'MESSAGE_CREATE',
    messageKind: 'discord_message',
    replyTargetKey: 'channelId',
    replyTargetLabel: 'Channel',
    providerUrl: `${apiUrl}/api/internal/support/discord/discord-main`,
    inboundUrl: `${apiUrl}/api/internal/support/channel-webhooks/discord-main`,
  },
  {
    id: 'channel-slack-main',
    key: 'slack-main',
    type: 'slack',
    name: 'Slack main',
    targetId: 'C777',
    provider: 'slack',
    deliveryProvider: 'slack_bot',
    eventType: 'message',
    messageKind: 'slack_message',
    replyTargetKey: 'channelId',
    replyTargetLabel: 'Channel',
    providerUrl: `${apiUrl}/api/internal/support/slack/slack-main?project_id=project1`,
    inboundUrl: `${apiUrl}/api/internal/support/channel-webhooks/slack-main?project_id=project1`,
  },
  {
    id: 'channel-teams-main',
    key: 'teams-main',
    type: 'teams',
    name: 'Teams main',
    targetId: '19:general@thread.tacv2',
    provider: 'teams',
    deliveryProvider: 'teams_graph',
    eventType: 'message.created',
    messageKind: 'teams_message',
    replyTargetKey: 'conversationId',
    replyTargetLabel: 'Conversation',
    providerUrl: `${apiUrl}/api/internal/support/teams/teams-main?project_id=project1`,
    inboundUrl: `${apiUrl}/api/internal/support/channel-webhooks/teams-main?project_id=project1`,
  },
  {
    id: 'channel-telegram-main',
    key: 'telegram-main',
    type: 'telegram',
    name: 'Telegram main',
    targetId: 'chat-1',
    provider: 'telegram',
    deliveryProvider: 'telegram_bot',
    eventType: 'message',
    messageKind: 'telegram_message',
    replyTargetKey: 'chatId',
    replyTargetLabel: 'Chat',
    providerUrl: `${apiUrl}/api/internal/support/telegram/telegram-main`,
    inboundUrl: `${apiUrl}/api/internal/support/channel-webhooks/telegram-main`,
  },
  {
    id: 'channel-whatsapp-main',
    key: 'whatsapp-main',
    type: 'whatsapp',
    name: 'WhatsApp main',
    targetId: '4915112345678',
    provider: 'whatsapp',
    deliveryProvider: 'whatsapp',
    eventType: 'messages',
    messageKind: 'whatsapp_message',
    replyTargetKey: 'toAddress',
    replyTargetLabel: 'Recipient',
    providerUrl: `${apiUrl}/api/internal/support/whatsapp/whatsapp-main?project_id=project1`,
    inboundUrl: `${apiUrl}/api/internal/support/channel-webhooks/whatsapp-main?project_id=project1`,
  },
  {
    id: 'channel-messenger-main',
    key: 'messenger-main',
    type: 'messenger',
    name: 'Messenger main',
    targetId: 'customer-psid-1',
    provider: 'messenger',
    deliveryProvider: 'messenger',
    eventType: 'message',
    messageKind: 'messenger_message',
    replyTargetKey: 'toAddress',
    replyTargetLabel: 'PSID',
    providerUrl: `${apiUrl}/api/internal/support/messenger/messenger-main?project_id=project1`,
    inboundUrl: `${apiUrl}/api/internal/support/channel-webhooks/messenger-main?project_id=project1`,
  },
  {
    id: 'channel-sms-main',
    key: 'sms-main',
    type: 'sms',
    name: 'SMS main',
    targetId: '+14155550123',
    provider: 'sms',
    deliveryProvider: 'twilio_sms',
    eventType: 'incoming_message',
    messageKind: 'sms_message',
    replyTargetKey: 'toAddress',
    replyTargetLabel: 'Recipient',
    providerUrl: `${apiUrl}/api/internal/support/twilio/sms-main?project_id=project1`,
    smsUrl: `${apiUrl}/api/internal/support/sms/sms-main?project_id=project1`,
    inboundUrl: `${apiUrl}/api/internal/support/channel-webhooks/sms-main?project_id=project1`,
  },
  {
    id: 'channel-web-main',
    key: 'web-main',
    type: 'web_chat',
    name: 'Web main',
    targetId: 'web-session-smoke-1',
    provider: 'web_chat',
    deliveryProvider: 'web_chat_internal',
    eventType: 'web_chat_message',
    messageKind: 'web_chat_message',
    replyTargetKey: 'sessionKey',
    replyTargetLabel: 'Web chat',
    providerUrl: '',
    inboundUrl: `${apiUrl}/api/support/web-chat/project1/sessions`,
  },
];

function channelFixtureById(channelId) {
  return channelFixtures.find(channel => channel.id === channelId || channel.key === channelId) || null;
}

function providerAddress(channel, targetId, authorId) {
  if (channel.type === 'slack') return `slack:T123:${targetId}:${authorId || 'smoke-user'}`;
  if (channel.type === 'teams') return `teams:tenant-1:team-1:${targetId}:${authorId || 'smoke-user'}`;
  if (channel.type === 'discord') return `discord:G123:${authorId || 'smoke-user'}`;
  if (channel.type === 'telegram') return `telegram:${targetId}:${authorId || 'smoke-user'}`;
  if (channel.type === 'whatsapp') return `whatsapp:waba-1:${authorId || targetId}`;
  if (channel.type === 'messenger') return `messenger:page-1:${authorId || targetId}`;
  if (channel.type === 'sms') return `sms:AC123:${authorId || targetId}`;
  return `${channel.type}:${targetId}:${authorId || 'smoke-user'}`;
}

function externalTicketKey(channel, targetId, messageId) {
  if (channel.type === 'slack') return `slack:${channel.key}:T123:${targetId}:${messageId}`;
  if (channel.type === 'teams') return `teams:${channel.key}:tenant-1:team-1:${targetId}:${messageId}`;
  if (channel.type === 'discord') return `discord:${channel.key}:G123:${targetId}:${messageId}`;
  if (channel.type === 'telegram') return `telegram:${channel.key}:${targetId}:${messageId}`;
  if (channel.type === 'whatsapp') return `whatsapp:${channel.key}:waba-1:${targetId}:${messageId}`;
  if (channel.type === 'messenger') return `messenger:${channel.key}:page-1:${targetId}:${messageId}`;
  if (channel.type === 'sms') return `sms:${channel.key}:AC123:${targetId}:${messageId}`;
  return `${channel.type}:${channel.key}:${targetId}:${messageId}`;
}

function providerMetadata(channel, targetId, messageId, ticketKey) {
  if (channel.type === 'slack') {
    return {
      provider: channel.provider,
      channelKey: channel.key,
      workspaceId: 'T123',
      channelId: targetId,
      providerMessageId: messageId,
      externalTicketKey: ticketKey,
    };
  }
  if (channel.type === 'teams') {
    return {
      provider: channel.provider,
      channelKey: channel.key,
      tenantId: 'tenant-1',
      teamId: 'team-1',
      conversationId: targetId,
      providerMessageId: messageId,
      externalTicketKey: ticketKey,
    };
  }
  if (channel.type === 'discord') {
    return {
      provider: channel.provider,
      channelKey: channel.key,
      workspaceId: 'G123',
      channelId: targetId,
      providerMessageId: messageId,
      externalTicketKey: ticketKey,
    };
  }
  if (channel.type === 'telegram') {
    return {
      provider: channel.provider,
      channelKey: channel.key,
      chatId: targetId,
      providerMessageId: messageId,
      externalTicketKey: ticketKey,
    };
  }
  if (channel.type === 'whatsapp') {
    return {
      provider: channel.provider,
      channelKey: channel.key,
      businessAccountId: 'waba-1',
      recipient: targetId,
      providerMessageId: messageId,
      externalTicketKey: ticketKey,
    };
  }
  if (channel.type === 'messenger') {
    return {
      provider: channel.provider,
      channelKey: channel.key,
      pageId: 'page-1',
      psid: targetId,
      providerMessageId: messageId,
      externalTicketKey: ticketKey,
    };
  }
  if (channel.type === 'sms') {
    return {
      provider: channel.provider,
      channelKey: channel.key,
      accountSid: 'AC123',
      toAddress: targetId,
      providerMessageId: messageId,
      externalTicketKey: ticketKey,
    };
  }
  return {
    provider: channel.provider,
    channelKey: channel.key,
    providerMessageId: messageId,
    externalTicketKey: ticketKey,
  };
}

function channelSetupFixture(channel) {
  const providerName = channel.type === 'telegram'
    ? 'Telegram'
    : channel.type === 'discord'
      ? 'Discord'
      : channel.type === 'slack'
        ? 'Slack'
        : channel.type === 'teams'
          ? 'Microsoft Teams'
          : channel.type === 'web_chat' ? 'Web chat' : channel.name;
  if (channel.type === 'web_chat') {
    const webChatUrl = `${apiUrl}/support/web-chat/project1?channel_key=${encodeURIComponent(channel.key)}`;
    const webChatEmbedScriptUrl = `${apiUrl}/support/web-chat/project1/embed.js?channel_key=${encodeURIComponent(channel.key)}`;
    return {
      ready: true,
      providerName,
      providerWebhookUrl: '',
      inboundWebhookUrl: channel.inboundUrl,
      outboundTransport: 'internal',
      inboundReady: true,
      outboundReady: true,
      authConfigured: true,
      outboundConfigKeys: [],
      messagePayloadExample: {},
      receiptPayloadExample: {},
      webChatUrl,
      webChatEmbedScriptUrl,
      webChatEmbedSnippet: `<script async src="${webChatEmbedScriptUrl}"></script>`,
      health: { ready: true, status: 'ready' },
      launch: {
        required: true,
        ready: false,
        checks: 4,
        passed: 2,
        missing: 2,
        failed: 0,
        blockers: [
          {
            key: 'web_chat_session',
            label: 'Prove visitor session',
            status: 'missing',
            detail: 'Open web chat and create a ticket from a visitor message.',
            action: 'web_chat_session',
            runId: '',
          },
          {
            key: 'web_chat_delivery',
            label: 'Prove reply delivery',
            status: 'missing',
            detail: 'Send an Inbox reply back into the web chat session.',
            action: 'web_chat_delivery',
            runId: '',
          },
        ],
        checklist: [
          { key: 'install_widget', label: 'Install web chat', status: 'done', detail: 'Hosted URL and embed script are available.', action: 'copy' },
          { key: 'auto_prepare', label: 'Agent preparation enabled', status: 'done', detail: 'Web chat tickets get AI drafts.', action: 'auto_prepare' },
          { key: 'web_chat_session', label: 'Prove visitor session', status: 'missing', detail: 'Open web chat and create a ticket from a visitor message.', action: 'web_chat_session' },
          { key: 'web_chat_delivery', label: 'Prove reply delivery', status: 'missing', detail: 'Send an Inbox reply back into the web chat session.', action: 'web_chat_delivery' },
        ],
      },
      launchChecklist: [
        { key: 'install_widget', label: 'Install web chat', status: 'done', detail: 'Hosted URL and embed script are available.', action: 'copy' },
        { key: 'auto_prepare', label: 'Agent preparation enabled', status: 'done', detail: 'Web chat tickets get AI drafts.', action: 'auto_prepare' },
        { key: 'web_chat_session', label: 'Prove visitor session', status: 'missing', detail: 'Open web chat and create a ticket from a visitor message.', action: 'web_chat_session' },
        { key: 'web_chat_delivery', label: 'Prove reply delivery', status: 'missing', detail: 'Send an Inbox reply back into the web chat session.', action: 'web_chat_delivery' },
      ],
      launchPlaybook: [
        {
          key: 'install_widget',
          label: 'Install web chat',
          status: 'done',
          detail: 'Use hosted web chat URL or embed script on the customer-facing site.',
          action: 'copy',
          runAction: '',
          copyLabel: 'Web chat URL',
          copyValue: webChatUrl,
          targetUrl: webChatUrl,
        },
        {
          key: 'visitor_session',
          label: 'Prove visitor session',
          status: 'missing',
          detail: 'Open web chat and create a ticket from a visitor message.',
          action: '',
          runAction: 'web_chat_session',
          copyLabel: '',
          copyValue: '',
          smokeCommand: `Open ${webChatUrl} and send a visitor message.`,
          targetUrl: webChatUrl,
        },
      ],
    };
  }
  return {
    ready: true,
    providerName,
    providerWebhookUrl: channel.providerUrl,
    smsWebhookUrl: channel.smsUrl ?? '',
    smsWebhookPath: channel.smsUrl ? `/api/internal/support/sms/${channel.key}` : '',
    inboundWebhookUrl: channel.inboundUrl,
    outboundTransport: channel.type === 'telegram' ? 'bot' : 'webhook',
    inboundReady: true,
    outboundReady: true,
    authConfigured: true,
    outboundConfigKeys: [],
    messagePayloadExample: {},
    receiptPayloadExample: {},
    health: { ready: true, status: 'ready' },
    launch: {
      required: true,
      ready: false,
      checks: 4,
      passed: 2,
      missing: 2,
      failed: 0,
      blockers: [
        {
          key: 'lifecycle_smoke',
          label: 'Lifecycle smoke passed',
          status: 'missing',
          detail: 'Run HTTP lifecycle smoke to prove provider endpoint, ticket, approval, and delivery',
          action: 'lifecycle_smoke',
          runId: '',
        },
        {
          key: 'attachment_lifecycle_smoke',
          label: 'Attachment lifecycle smoke passed',
          status: 'missing',
          detail: `Run attachment-only HTTP lifecycle smoke to prove ${providerName} files create tickets and replies deliver`,
          action: 'attachment_lifecycle_smoke',
          runId: '',
        },
      ],
      checklist: [
        { key: 'inbound_smoke', label: 'Inbound smoke passed', status: 'done', detail: 'Fixture inbound proof', action: 'inbound_smoke' },
        { key: 'outbound_smoke', label: 'Outbound smoke passed', status: 'done', detail: 'Fixture outbound proof', action: 'outbound_smoke' },
        { key: 'lifecycle_smoke', label: 'Lifecycle smoke passed', status: 'missing', detail: 'Run HTTP lifecycle smoke to prove provider endpoint, ticket, approval, and delivery', action: 'lifecycle_smoke' },
        {
          key: 'attachment_lifecycle_smoke',
          label: 'Attachment lifecycle smoke passed',
          status: 'missing',
          detail: `Run attachment-only HTTP lifecycle smoke to prove ${providerName} files create tickets and replies deliver`,
          action: 'attachment_lifecycle_smoke',
        },
      ],
    },
    launchChecklist: [
      { key: 'inbound_smoke', label: 'Inbound smoke passed', status: 'done', detail: 'Fixture inbound proof', action: 'inbound_smoke' },
      { key: 'outbound_smoke', label: 'Outbound smoke passed', status: 'done', detail: 'Fixture outbound proof', action: 'outbound_smoke' },
      { key: 'lifecycle_smoke', label: 'Lifecycle smoke passed', status: 'missing', detail: 'Run HTTP lifecycle smoke to prove provider endpoint, ticket, approval, and delivery', action: 'lifecycle_smoke' },
      {
        key: 'attachment_lifecycle_smoke',
        label: 'Attachment lifecycle smoke passed',
        status: 'missing',
        detail: `Run attachment-only HTTP lifecycle smoke to prove ${providerName} files create tickets and replies deliver`,
        action: 'attachment_lifecycle_smoke',
      },
    ],
    launchPlaybook: [
      {
        key: 'endpoint',
        label: 'Connect inbound surface',
        status: 'done',
        detail: `Copy provider URL into ${providerName} setup.`,
        action: 'copy',
        runAction: '',
        copyLabel: 'Provider URL',
        copyValue: channel.providerUrl,
        targetUrl: '',
      },
      {
        key: 'lifecycle_proof',
        label: 'Run lifecycle smoke',
        status: 'missing',
        detail: 'Prove endpoint auth, ticket creation, approval, and provider delivery together.',
        action: '',
        runAction: 'lifecycle_smoke',
        copyLabel: '',
        copyValue: '',
        smokeCommand: `SUPPORT_PROJECT_ID=project1 ADMIN_AUTH_TOKEN=<admin-api-token> ./support-channel-lifecycle-smoke.sh --channel-key ${channel.key} --transport http`,
        targetUrl: '',
      },
      {
        key: 'attachment_lifecycle_proof',
        label: 'Run attachment lifecycle smoke',
        status: 'missing',
        detail: 'Prove provider file-only messages create tickets and replies deliver.',
        action: '',
        runAction: 'attachment_lifecycle_smoke',
        copyLabel: '',
        copyValue: '',
        smokeCommand: `SUPPORT_PROJECT_ID=project1 ADMIN_AUTH_TOKEN=<admin-api-token> ./support-channel-lifecycle-smoke.sh --channel-key ${channel.key} --transport http --body "" --attachment '{"id":"smoke-file","filename":"incident.txt","url":"https://files.example/incident.txt"}'`,
        targetUrl: '',
      },
    ],
  };
}

function channelResponseFixture(channel) {
  const config = {
    ticketCreationMode: 'per_message',
    autoPrepare: true,
    autoPrepareAgentReply: true,
  };
  if (channel.type === 'telegram') {
    config.smokeChatId = channel.targetId;
    config.telegramBotTokenEnv = 'SUPPORT_TELEGRAM_BOT_TOKEN';
  } else if (['whatsapp', 'messenger', 'sms'].includes(channel.type)) {
    config.smokeToAddress = channel.targetId;
  } else if (channel.type === 'web_chat') {
    config.public = true;
    config.adapter = 'web_chat';
    config.defaultAssigneeEmail = 'agent@example.com';
  } else {
    config.smokeChannelId = channel.targetId;
  }
  return {
    id: channel.id,
    channelKey: channel.key,
    type: channel.type,
    name: channel.name,
    status: 'active',
    config,
    setup: channelSetupFixture(channel),
  };
}

function createLifecycleSmoke(channel, body) {
  const sequence = lifecycleSequence++;
  const issueId = `issue-lifecycle-smoke-${sequence}`;
  const replyId = `reply-lifecycle-smoke-${sequence}`;
  const messageId = text(body.messageId) || `lifecycle-smoke-message-${sequence}`;
  const eventId = text(body.eventId) || messageId;
  const channelId = text(body.channelId) || channel.targetId;
  const hasInboundAttachments = Array.isArray(body.attachments) && body.attachments.length > 0;
  const inboundBody = text(body.body) || (hasInboundAttachments ? '' : 'Lifecycle smoke customer message');
  const replyBody = text(body.replyBody) || 'Lifecycle smoke support reply.';
  const authorId = text(body.authorId) || 'smoke-user';
  const authorAddress = providerAddress(channel, channelId, authorId);
  const ticketKey = externalTicketKey(channel, channelId, messageId);
  const smokeIssue = baseIssue({
    id: issueId,
    accountId: 'account-acme',
    contactId: 'contact-lifecycle-smoke',
    sourceEmailId: ticketKey,
    chatId: ticketKey,
    status: 'ongoing',
    workflowStatus: 'ongoing',
    priority: 'normal',
    assigneeEmail: 'agent@example.com',
    queueKey: 'support',
    queueName: 'Support',
    accountName: 'Acme Cloud',
    accountDomain: 'acme.test',
    contactEmail: authorAddress,
    contactName: text(body.authorName) || 'Lifecycle Smoke Customer',
    subject: `${channel.name} lifecycle smoke ticket`,
    fromAddress: authorAddress,
    channel: channel.type,
    source: channel.key,
    aiSummary: 'Lifecycle smoke ticket proving inbound, approval, and reply delivery.',
    activatedIntent: 'incident_response',
    latestAgentMessageAt: now,
    latestMessageDirection: 'agent',
    metadata: {
      externalProvider: channel.provider,
      externalTicketKey: ticketKey,
    },
    messages: [
      {
        id: `msg-lifecycle-smoke-${sequence}`,
        sourceMessageId: ticketKey,
        direction: 'customer',
        sender: text(body.authorName) || 'Lifecycle Smoke Customer',
        body: inboundBody,
        messageKind: channel.messageKind,
        attachments: body.attachments || [],
        metadata: providerMetadata(channel, channelId, messageId, ticketKey),
        occurredAt: now,
      },
    ],
    outboundMessages: [
      outbound({
        id: replyId,
        issueId,
        channel: channel.type,
        toAddress: channelId,
        subject: `Re: ${channel.name} lifecycle smoke ticket`,
        body: replyBody,
        status: 'queued',
        provider: 'channel_adapter_pending',
        metadata: {
          approvalRequired: true,
          approved: false,
          reviewStatus: 'pending',
          channelKey: channel.key,
          replyTarget: { channel: channel.type, key: channel.replyTargetKey, value: channelId, label: `${channel.replyTargetLabel}: ${channelId}` },
          externalProvider: channel.provider,
          externalTicketKey: ticketKey,
          deliveryProvider: channel.deliveryProvider,
        },
        attachments: body.replyAttachments || [],
      }),
    ],
    activityEvents: [
      activity({
        id: `event-lifecycle-smoke-${sequence}`,
        issueId,
        eventType: `${channel.type}_message_received`,
        title: `${channel.name} message received`,
        body: inboundBody,
        metadata: { externalTicketKey: ticketKey },
      }),
    ],
    channelWebhookEvents: [
      {
        id: `webhook-lifecycle-smoke-${sequence}`,
        channelId: channel.id,
        outboundMessageId: '',
        provider: channel.provider,
        eventId,
        eventType: channel.eventType,
        providerMessageId: messageId,
        status: 'processed',
        error: '',
        payload: {},
        result: { issueId, messageId: `msg-lifecycle-smoke-${sequence}` },
        receivedAt: now,
        processedAt: now,
        created: now,
        updated: now,
      },
    ],
  });
  issues.unshift(smokeIssue);
  const reply = smokeIssue.outboundMessages[0];
  const approved = approveReply(smokeIssue, reply);
  const delivered = sendReply(smokeIssue, approved);
  const inbound = {
    channelId: channel.id,
    channelKey: channel.key,
    type: channel.type,
    provider: channel.provider,
    transport: text(body.transport) || 'http',
    ready: true,
    validation: { ready: true },
    payload: {},
    ingestion: { status: 'success', processed: 1, items: [{ issueId, messageId: `msg-lifecycle-smoke-${sequence}` }] },
    http: { status: 200, auth: { mode: 'token' } },
    eventId,
    messageId,
    issueId,
    attachmentCount: Array.isArray(body.attachments) ? body.attachments.length : 0,
    fileOnly: Boolean(Array.isArray(body.attachments) && body.attachments.length > 0 && !inboundBody.trim()),
    status: 'success',
    processed: 1,
    failed: 0,
    skipped: 0,
    unmatched: 0,
    items: [{ issueId, messageId: `msg-lifecycle-smoke-${sequence}` }],
  };
  return {
    channelId: channel.id,
    channelKey: channel.key,
    type: channel.type,
    ready: true,
    validation: { ready: true },
    inbound,
    issueId,
    replyId,
    messageId,
    attachmentCount: inbound.attachmentCount,
    replyAttachmentCount: Array.isArray(body.replyAttachments) ? body.replyAttachments.length : 0,
    fileOnly: inbound.fileOnly,
    provider: delivered.provider,
    providerMessageId: delivered.providerMessageId,
    status: delivered.status,
    sent: delivered.status === 'sent',
    deferred: delivered.status === 'queued',
    failed: delivered.status !== 'sent' && delivered.status !== 'queued',
    processed: 1,
    skipped: 0,
    error: delivered.error,
    approval: approved,
    delivery: delivered,
    deliveryRoute: delivered.metadata?.deliveryReceipt || {},
    providerResponse: { ok: true, messageId: delivered.providerMessageId },
  };
}

function responseFor(method, pathname, body = {}) {
  if (pathname === '/api/health') return { status: 'ok' };
  if (pathname === '/api/auth/config') return { isSaas: false, allowSignups: false };
  if (pathname === '/api/admin/projects') {
    return [{ id: 'project1', name: 'Support workspace', description: 'Pylon direction smoke', tenant: 'tenant1', role: 'admin', created: now }];
  }
  if (pathname === '/api/admin/me') {
    return {
      id: 'user-agent',
      email: 'agent@example.com',
      name: 'Agent Example',
      language: 'en',
      defaultProject: 'project1',
      projects: [{ id: 'project1', name: 'Support workspace', description: '', tenant: 'tenant1', role: 'admin', created: now }],
    };
  }
  if (pathname === '/api/admin/tenant/settings') {
    return { supportEmail: 'support@example.com', feedbackEmail: 'feedback@example.com' };
  }
  if (pathname === '/api/admin/projects/project1/intents') {
    return [{ name: 'incident_response', description: 'Incident reply runbook', actions: [], response: {}, active: true }];
  }
  if (pathname === '/api/admin/projects/project1/members') {
    return [
      { id: 'member-agent', userId: 'user-agent', email: 'agent@example.com', isRoot: true, role: 'admin', projectId: 'project1', created: now },
      { id: 'member-lead', userId: 'user-lead', email: 'lead@example.com', isRoot: false, role: 'editor', projectId: 'project1', created: now },
    ];
  }
  if (pathname === '/api/admin/projects/project1/crm/connectors') {
    return { items: crmConnectors };
  }
  if (pathname === '/api/admin/projects/project1/crm/connectors/sync/runs') {
    return { items: crmSyncRuns };
  }
  if (pathname === '/api/admin/projects/project1/crm/connectors/webhook-events') {
    return { items: [] };
  }
  if (
    pathname === '/api/admin/projects/project1/crm/connectors/sync/run'
    || pathname === '/api/admin/projects/project1/crm/connectors/crm-hubspot-main/sync'
  ) {
    if (method === 'POST') return runCrmSyncFixture();
  }
  if ([
    '/api/admin/projects/project1/channels/presets',
    '/api/admin/projects/project1/channels/sync/runs',
    '/api/admin/projects/project1/channels/cursors',
    '/api/admin/projects/project1/support/delivery/runs',
  ].includes(pathname)) {
    return { items: [] };
  }
  if (pathname === '/api/admin/projects/project1/channels/webhook-events') {
    return { items: supportChannelWebhookEvents };
  }
  const rematchChannelWebhookMatch = pathname.match(/^\/api\/admin\/projects\/project1\/channels\/webhook-events\/([^/]+)\/rematch$/);
  if (rematchChannelWebhookMatch && method === 'POST') {
    return rematchChannelWebhookEventFixture(decodeURIComponent(rematchChannelWebhookMatch[1]), body);
  }
  if (pathname === '/api/admin/projects/project1/issues') {
    if (method === 'POST') return createManualIssueFixture(body);
    return { items: issues.map(issueSummary) };
  }
  if (pathname === '/api/admin/projects/project1/automations') {
    return { items: automationRules };
  }
  if (pathname === '/api/admin/projects/project1/automations/runs') {
    return { items: automationRuns };
  }
  if (pathname === '/api/admin/projects/project1/automations/preview' && method === 'POST') {
    return previewAutomationFixture(body);
  }
  if (pathname === '/api/support/knowledge/project1') {
    return {
      items: publicKnowledgeArticlesFixture(),
    };
  }
  const publicKnowledgeArticleMatch = pathname.match(/^\/api\/support\/knowledge\/project1\/articles\/([^/]+)$/);
  if (publicKnowledgeArticleMatch) {
    return knowledgeArticles.find(article => article.id === decodeURIComponent(publicKnowledgeArticleMatch[1]) && article.public && article.status === 'published') || null;
  }
  if (pathname === '/api/admin/projects/project1/channels') {
    return {
      items: channelFixtures.map(channelResponseFixture),
    };
  }
  if (pathname === '/api/admin/projects/project1/channels/web-chat/sessions') {
    return { items: webChatSessions.map(webChatSessionResponse) };
  }
  if (pathname === '/api/support/web-chat/project1/sessions' && method === 'POST') {
    return createWebChatTicket(body);
  }
  const webChatMessageMatch = pathname.match(/^\/api\/support\/web-chat\/sessions\/([^/]+)\/messages$/);
  if (webChatMessageMatch && method === 'POST') {
    return createWebChatMessage(decodeURIComponent(webChatMessageMatch[1]), body);
  }
  const webChatSessionMatch = pathname.match(/^\/api\/support\/web-chat\/sessions\/([^/]+)$/);
  if (webChatSessionMatch) {
    const session = webChatSessionByKey(decodeURIComponent(webChatSessionMatch[1]));
    if (!session) return null;
    return webChatSessionResponse(session);
  }
  const portalApiMatch = pathname.match(/^\/api\/support\/portal\/([^/]+)$/);
  if (portalApiMatch && method === 'GET') {
    return portalFixture(decodeURIComponent(portalApiMatch[1]));
  }
  const portalMessageMatch = pathname.match(/^\/api\/support\/portal\/([^/]+)\/messages$/);
  if (portalMessageMatch && method === 'POST') {
    return createPortalMessageFixture(decodeURIComponent(portalMessageMatch[1]), body);
  }
  const portalFeedbackMatch = pathname.match(/^\/api\/support\/portal\/([^/]+)\/feedback$/);
  if (portalFeedbackMatch && method === 'POST') {
    return createPortalFeedbackFixture(decodeURIComponent(portalFeedbackMatch[1]), body);
  }
  const lifecycleSmokeMatch = pathname.match(/^\/api\/admin\/projects\/project1\/channels\/([^/]+)\/lifecycle-smoke$/);
  if (lifecycleSmokeMatch && method === 'POST') {
    const channel = channelFixtureById(decodeURIComponent(lifecycleSmokeMatch[1]));
    if (!channel) return null;
    return createLifecycleSmoke(channel, body);
  }
  if (pathname === '/api/admin/projects/project1/issues/actions/bulk-approve' && method === 'POST') {
    return bulkApproveActions(body);
  }
  if (pathname === '/api/admin/projects/project1/issues/replies/bulk-approve' && method === 'POST') {
    return bulkReviewReplies(body, false);
  }
  if (pathname === '/api/admin/projects/project1/issues/replies/bulk-approve-send' && method === 'POST') {
    return bulkReviewReplies(body, true);
  }
  if (pathname === '/api/admin/projects/project1/issues/replies/bulk-retry-failed' && method === 'POST') {
    return bulkRetryFailedReplies(body);
  }
  const createReplyMatch = pathname.match(/^\/api\/admin\/projects\/project1\/issues\/([^/]+)\/replies$/);
  if (createReplyMatch && method === 'POST') {
    const issue = findIssue(decodeURIComponent(createReplyMatch[1]));
    if (!issue) return null;
    const status = text(body.status) || 'draft';
    const deliveryError = text(body.error) || (status === 'failed' ? 'Simulated provider timeout' : '');
    const reply = outbound({
      id: `reply-smoke-manual-${replySequence++}`,
      issueId: issue.id,
      channel: issue.channel,
      toAddress: issue.channel === 'discord' ? 'C123' : issue.fromAddress,
      subject: `Re: ${issue.subject}`,
      body: text(body.body),
      status,
      provider: status === 'queued' ? 'channel_adapter_pending' : status === 'failed' ? `${issue.channel}_adapter_failed` : 'manual_draft',
      error: deliveryError,
      metadata: {
        approvalRequired: body.approvalRequired === true,
        approved: body.approvalRequired !== true,
        reviewStatus: body.approvalRequired === true ? 'pending' : 'approved',
        source: 'manual_reply',
        ...(deliveryError ? { lastDeliveryError: deliveryError, deliveryAttempts: 1 } : {}),
      },
    });
    issue.outboundMessages = [reply, ...(issue.outboundMessages ?? [])];
    recalculateIssueState(issue);
    return reply;
  }
  const createNoteMatch = pathname.match(/^\/api\/admin\/projects\/project1\/issues\/([^/]+)\/notes$/);
  if (createNoteMatch && method === 'POST') {
    const issue = findIssue(decodeURIComponent(createNoteMatch[1]));
    if (!issue) return null;
    return createIssueNoteFixture(issue, body);
  }
  const watchIssueMatch = pathname.match(/^\/api\/admin\/projects\/project1\/issues\/([^/]+)\/watchers\/me$/);
  if (watchIssueMatch && method === 'POST') {
    const issue = findIssue(decodeURIComponent(watchIssueMatch[1]));
    if (!issue) return null;
    return watchIssueFixture(issue);
  }
  if (watchIssueMatch && method === 'DELETE') {
    const issue = findIssue(decodeURIComponent(watchIssueMatch[1]));
    if (!issue) return null;
    return unwatchIssueFixture(issue);
  }
  const createPortalSessionMatch = pathname.match(/^\/api\/admin\/projects\/project1\/issues\/([^/]+)\/portal-sessions$/);
  if (createPortalSessionMatch && method === 'POST') {
    const issue = findIssue(decodeURIComponent(createPortalSessionMatch[1]));
    if (!issue) return null;
    return createPortalSessionFixture(issue);
  }
  const requestReplyChangesMatch = pathname.match(/^\/api\/admin\/projects\/project1\/issues\/([^/]+)\/replies\/([^/]+)\/changes$/);
  if (requestReplyChangesMatch && method === 'POST') {
    const issue = findIssue(decodeURIComponent(requestReplyChangesMatch[1]));
    const reply = issue?.outboundMessages?.find(item => item.id === decodeURIComponent(requestReplyChangesMatch[2]));
    if (!issue || !reply) return null;
    return requestReplyChanges(issue, reply, body);
  }
  const reviseReplyMatch = pathname.match(/^\/api\/admin\/projects\/project1\/issues\/([^/]+)\/replies\/([^/]+)\/revise$/);
  if (reviseReplyMatch && method === 'POST') {
    const issue = findIssue(decodeURIComponent(reviseReplyMatch[1]));
    const reply = issue?.outboundMessages?.find(item => item.id === decodeURIComponent(reviseReplyMatch[2]));
    if (!issue || !reply) return null;
    return reviseReplyWithAgentFixture(issue, reply, body);
  }
  const approveReplyMatch = pathname.match(/^\/api\/admin\/projects\/project1\/issues\/([^/]+)\/replies\/([^/]+)\/approve$/);
  if (approveReplyMatch && method === 'POST') {
    const issue = findIssue(decodeURIComponent(approveReplyMatch[1]));
    const reply = issue?.outboundMessages?.find(item => item.id === decodeURIComponent(approveReplyMatch[2]));
    if (!issue || !reply) return null;
    return approveReply(issue, reply);
  }
  const sendReplyMatch = pathname.match(/^\/api\/admin\/projects\/project1\/issues\/([^/]+)\/replies\/([^/]+)\/send$/);
  if (sendReplyMatch && method === 'POST') {
    const issue = findIssue(decodeURIComponent(sendReplyMatch[1]));
    const reply = issue?.outboundMessages?.find(item => item.id === decodeURIComponent(sendReplyMatch[2]));
    if (!issue || !reply) return null;
    return sendReply(issue, reply);
  }
  const updateReplyMatch = pathname.match(/^\/api\/admin\/projects\/project1\/issues\/([^/]+)\/replies\/([^/]+)$/);
  if (updateReplyMatch && method === 'PATCH') {
    const issue = findIssue(decodeURIComponent(updateReplyMatch[1]));
    const reply = issue?.outboundMessages?.find(item => item.id === decodeURIComponent(updateReplyMatch[2]));
    if (!issue || !reply) return null;
    if (body.body !== undefined) reply.body = text(body.body);
    if (body.status !== undefined) reply.status = text(body.status);
    reply.updated = now;
    recalculateIssueState(issue);
    return reply;
  }
  const approveActionMatch = pathname.match(/^\/api\/admin\/projects\/project1\/issues\/([^/]+)\/actions\/([^/]+)\/approve$/);
  if (approveActionMatch && method === 'POST') {
    const issue = findIssue(decodeURIComponent(approveActionMatch[1]));
    const execution = issue?.actionExecutions?.find(item => item.id === decodeURIComponent(approveActionMatch[2]));
    if (!issue || !execution) return null;
    return { execution: approveAction(issue, execution), issue };
  }
  const agentAnswerMatch = pathname.match(/^\/api\/admin\/projects\/project1\/issues\/([^/]+)\/agent-answer$/);
  if (agentAnswerMatch && method === 'POST') {
    const issue = findIssue(decodeURIComponent(agentAnswerMatch[1]));
    if (!issue) return null;
    return createAgentAnswer(issue, body);
  }
  const mergeIssueMatch = pathname.match(/^\/api\/admin\/projects\/project1\/issues\/([^/]+)\/merge$/);
  if (mergeIssueMatch && method === 'POST') {
    const issue = findIssue(decodeURIComponent(mergeIssueMatch[1]));
    if (!issue) return null;
    return mergeIssuesFixture(issue, body);
  }
  const splitIssueMessageMatch = pathname.match(/^\/api\/admin\/projects\/project1\/issues\/([^/]+)\/split-message$/);
  if (splitIssueMessageMatch && method === 'POST') {
    const issue = findIssue(decodeURIComponent(splitIssueMessageMatch[1]));
    if (!issue) return null;
    return splitIssueMessageFixture(issue, body);
  }
  const issueDetailMatch = pathname.match(/^\/api\/admin\/projects\/project1\/issues\/([^/]+)$/);
  if (issueDetailMatch) {
    const issue = findIssue(decodeURIComponent(issueDetailMatch[1]));
    if (!issue) return null;
    if (method === 'PATCH') {
      Object.assign(issue, body, { updated: now });
      if (body.status !== undefined && body.workflowStatus === undefined) {
        issue.workflowStatus = text(body.status) === 'done' ? 'done' : text(body.status) === 'ongoing' ? 'ongoing' : 'open';
      }
      recalculateIssueState(issue);
      return issue;
    }
    return issue;
  }
  const duplicateMatch = pathname.match(/^\/api\/admin\/projects\/project1\/issues\/([^/]+)\/duplicate-suggestions$/);
  if (duplicateMatch) return { items: duplicateSuggestionsFor(decodeURIComponent(duplicateMatch[1])) };
  if (pathname === '/api/admin/projects/project1/support/queues') {
    return {
      items: [
        { id: 'queue-support', queueKey: 'support', name: 'Support', description: 'Main support queue', defaultAssigneeEmail: 'agent@example.com', status: 'active', metadata: { ownerEmails: ['agent@example.com', 'lead@example.com'] }, created: now, updated: now },
        { id: 'queue-tier-2', queueKey: 'tier-2', name: 'Tier 2', description: 'Escalated support queue', defaultAssigneeEmail: 'lead@example.com', status: 'active', metadata: { ownerEmails: ['lead@example.com'] }, created: now, updated: now },
      ],
    };
  }
  if (pathname === '/api/admin/projects/project1/support/inbox-views') {
    if (method === 'POST') return upsertInboxViewFixture(body);
    return { items: inboxViews };
  }
  const deleteInboxViewMatch = pathname.match(/^\/api\/admin\/projects\/project1\/support\/inbox-views\/([^/]+)$/);
  if (deleteInboxViewMatch && method === 'DELETE') {
    return archiveInboxViewFixture(decodeURIComponent(deleteInboxViewMatch[1]));
  }
  if (pathname === '/api/admin/projects/project1/support/reply-macros') {
    if (method === 'POST') return upsertReplyMacroFixture(body);
    return { items: replyMacros.filter(macro => macro.status === 'active') };
  }
  const renderReplyMacroMatch = pathname.match(/^\/api\/admin\/projects\/project1\/support\/reply-macros\/([^/]+)\/render$/);
  if (renderReplyMacroMatch && method === 'POST') {
    return renderReplyMacroFixture(decodeURIComponent(renderReplyMacroMatch[1]));
  }
  const deleteReplyMacroMatch = pathname.match(/^\/api\/admin\/projects\/project1\/support\/reply-macros\/([^/]+)$/);
  if (deleteReplyMacroMatch && method === 'DELETE') {
    return archiveReplyMacroFixture(decodeURIComponent(deleteReplyMacroMatch[1]));
  }
  if (pathname === '/api/admin/projects/project1/notifications') {
    return { items: notifications.filter(notification => notification.status === 'unread') };
  }
  const readNotificationMatch = pathname.match(/^\/api\/admin\/projects\/project1\/notifications\/([^/]+)\/read$/);
  if (readNotificationMatch && method === 'POST') {
    return markNotificationReadFixture(decodeURIComponent(readNotificationMatch[1]));
  }
  if (pathname === '/api/admin/projects/project1/knowledge') {
    if (method === 'POST') return createKnowledgeArticleFixture(body);
    return { items: knowledgeArticles };
  }
  if (pathname === '/api/admin/projects/project1/knowledge/gaps') {
    return { items: allKnowledgeGapsFixture() };
  }
  const adminKnowledgeGapArticleMatch = pathname.match(/^\/api\/admin\/projects\/project1\/knowledge\/gaps\/([^/]+)\/article$/);
  if (adminKnowledgeGapArticleMatch && method === 'POST') {
    return createKnowledgeArticleFromGapFixture(decodeURIComponent(adminKnowledgeGapArticleMatch[1]), body);
  }
  const adminKnowledgeGapMatch = pathname.match(/^\/api\/admin\/projects\/project1\/knowledge\/gaps\/([^/]+)$/);
  if (adminKnowledgeGapMatch && method === 'PATCH') {
    return updateKnowledgeGapFixture(decodeURIComponent(adminKnowledgeGapMatch[1]), body);
  }
  const adminKnowledgeArticleMatch = pathname.match(/^\/api\/admin\/projects\/project1\/knowledge\/([^/]+)$/);
  if (adminKnowledgeArticleMatch) {
    const articleId = decodeURIComponent(adminKnowledgeArticleMatch[1]);
    if (method === 'PATCH') return updateKnowledgeArticleFixture(articleId, body);
    return knowledgeArticles.find(article => article.id === articleId) || null;
  }
  if (pathname === '/api/admin/projects/project1/support/sla-policy') {
    return {
      id: 'sla-policy-1',
      name: 'Default SLA',
      active: true,
      firstResponseMinutes: 60,
      resolutionMinutes: 1440,
      businessHours: {},
      metadata: { customFields: [{ key: 'impact', label: 'Impact', type: 'select', required: false, options: ['low', 'medium', 'high'] }] },
      created: now,
      updated: now,
    };
  }
  if (pathname === '/api/admin/projects/project1/support/sla/run' && method === 'POST') {
    return runSlaEscalationFixture();
  }
  if (pathname === '/api/admin/projects/project1/support/analytics') {
    return supportAnalyticsFixture();
  }
  if (pathname === '/api/admin/projects/project1/support/schema-health') {
    return schemaHealthFixture();
  }
  if (pathname === '/api/admin/projects/project1/support/launch-proof') {
    return launchProofFixture('needs_attention');
  }
  if (pathname === '/api/admin/projects/project1/support/launch-proof/runs') {
    return { items: launchProofRuns };
  }
  if (pathname === '/api/admin/projects/project1/support/launch-proof/run' && method === 'POST') {
    return launchProofRunFixture();
  }
  if (pathname === '/api/admin/projects/project1/support/workflow-proof/run' && method === 'POST') {
    return {
      issue: findIssue('issue-discord-open'),
      launchReadiness: launchReadinessFixture('needs_attention'),
      workflowTransitionEvents: 2,
      workflowOngoingTransitions: 1,
      workflowDoneTransitions: 1,
      successfulWorkflowLifecycleProofs: 1,
    };
  }
  if (pathname === '/api/admin/projects/project1/support/automation-proof/run' && method === 'POST') {
    return {
      issue: findIssue('issue-discord-open'),
      launchReadiness: launchReadinessFixture('needs_attention'),
      automationRuns: 1,
      successfulAutomationRuns: 1,
      successfulHumanLoopAutomationRuns: 1,
      issuesNeedingApproval: 1,
    };
  }
  if (pathname === '/api/admin/projects/project1/accounts') {
    return { items: Object.values(accounts).map(normalizeAccountFixture) };
  }
  const createInsightMatch = pathname.match(/^\/api\/admin\/projects\/project1\/accounts\/([^/]+)\/insights$/);
  if (createInsightMatch && method === 'POST') {
    const account = accounts[decodeURIComponent(createInsightMatch[1])];
    if (!account) return null;
    return createAccountInsightFixture(account, body);
  }
  const generateSummaryMatch = pathname.match(/^\/api\/admin\/projects\/project1\/accounts\/([^/]+)\/summary$/);
  if (generateSummaryMatch && method === 'POST') {
    const account = accounts[decodeURIComponent(generateSummaryMatch[1])];
    if (!account) return null;
    return createAccountInsightFixture(account, {
      type: 'summary',
      title: `Generated account summary: ${account.name || account.accountKey}`,
      body: `Health: ${account.healthStatus || 'unknown'}\nNext action: ${account.healthRollup?.nextAction || 'Review current support context.'}`,
      severity: account.healthStatus === 'at_risk' ? 'high' : 'info',
      status: 'active',
      insightKey: `summary:generated:${account.id}`,
      metadata: { source: 'account_summary_generator' },
    });
  }
  const updateInsightMatch = pathname.match(/^\/api\/admin\/projects\/project1\/accounts\/insights\/([^/]+)$/);
  if (updateInsightMatch && method === 'PATCH') {
    return updateAccountInsightFixture(decodeURIComponent(updateInsightMatch[1]), body);
  }
  const accountMatch = pathname.match(/^\/api\/admin\/projects\/project1\/accounts\/([^/]+)$/);
  if (accountMatch) {
    const account = accounts[decodeURIComponent(accountMatch[1])];
    return account ? normalizeAccountFixture(account) : null;
  }
  return undefined;
}

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    let raw = '';
    req.setEncoding('utf8');
    req.on('data', chunk => {
      raw += chunk;
    });
    req.on('end', () => {
      if (!raw.trim()) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(raw));
      } catch (error) {
        reject(error);
      }
    });
    req.on('error', reject);
  });
}

const server = http.createServer(async (req, res) => {
  if (req.method === 'OPTIONS') {
    empty(res);
    return;
  }
  const url = new URL(req.url || '/', `http://${req.headers.host || `${host}:${port}`}`);
  if (req.method === 'GET' && url.pathname === '/support/web-chat/project1') {
    html(res, 200, renderWebChatPage('project1', url.searchParams.get('channel_key') || 'web-main'));
    return;
  }
  if (req.method === 'GET' && url.pathname === '/support/web-chat/project1/embed.js') {
    javascript(res, 200, renderWebChatEmbedScript('project1', url.searchParams.get('channel_key') || 'web-main'));
    return;
  }
  if (req.method === 'GET' && url.pathname === '/support/knowledge/project1') {
    html(res, 200, renderPublicKnowledgePage(url.searchParams.get('q') || ''));
    return;
  }
  const publicKnowledgeArticlePageMatch = url.pathname.match(/^\/support\/knowledge\/project1\/articles\/([^/]+)$/);
  if (req.method === 'GET' && publicKnowledgeArticlePageMatch) {
    const body = renderPublicKnowledgeArticlePage(decodeURIComponent(publicKnowledgeArticlePageMatch[1]));
    if (!body) {
      json(res, 404, { detail: 'Article not found' });
      return;
    }
    html(res, 200, body);
    return;
  }
  const portalPageMatch = url.pathname.match(/^\/support\/portal\/([^/]+)$/);
  if (req.method === 'GET' && portalPageMatch) {
    const body = renderPortalPage(decodeURIComponent(portalPageMatch[1]));
    if (!body) {
      json(res, 404, { detail: 'Portal session not found' });
      return;
    }
    html(res, 200, body);
    return;
  }
  let requestBody = {};
  if (['POST', 'PATCH', 'PUT'].includes(req.method || '')) {
    try {
      requestBody = await readJsonBody(req);
    } catch {
      json(res, 400, { detail: 'Invalid JSON body' });
      return;
    }
  }
  const body = responseFor(req.method || 'GET', url.pathname, requestBody);
  if (body === undefined) {
    json(res, 404, { detail: `No smoke fixture for ${req.method} ${url.pathname}` });
    return;
  }
  if (body === null) {
    json(res, 404, { detail: 'Not found' });
    return;
  }
  json(res, 200, body);
});

server.listen(port, host, () => {
  console.log(`support inbox smoke api listening on http://${host}:${port}`);
});
