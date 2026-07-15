#!/usr/bin/env node
import { randomUUID } from 'node:crypto';

const DEFAULT_BODY = 'Lifecycle smoke customer message';
const DEFAULT_REPLY = 'Lifecycle smoke support reply.';

function usage() {
  return `Usage:
  node scripts/support-channel-lifecycle-smoke.mjs --api-url URL --project-id ID (--channel-id ID | --channel-key KEY) [options]

Options:
  --tenant-id ID             Tenant id for display only.
  --token TOKEN              Admin bearer token. Defaults to SUPPORT_ADMIN_TOKEN or ADMIN_API_TOKEN.
  --transport http|direct    Smoke transport. Defaults to http.
  --body TEXT                Inbound customer message body.
  --reply-body TEXT          Approval-required reply body.
  --author-name TEXT         Inbound author name.
  --author-email EMAIL       Inbound author email.
  --author-id ID             Provider author id.
  --from-address EMAIL       Reply author address.
  --provider-channel-id ID   Provider channel/chat id in smoke payload.
  --thread-id ID             Provider thread id.
  --message-id ID            Provider message id. Defaults to a unique smoke id.
  --event-id ID              Provider event id. Defaults to message id.
  --attachment JSON          Inbound attachment object. May be repeated.
  --reply-attachment JSON    Reply attachment object. May be repeated.
  --allow-deferred           Exit 0 for queued/deferred delivery.
  --json                     Print full response JSON.
  --help                     Show this help.

Environment:
  SUPPORT_SMOKE_API_URL, SUPPORT_SMOKE_PROJECT_ID, SUPPORT_SMOKE_CHANNEL_ID,
  SUPPORT_SMOKE_CHANNEL_KEY, SUPPORT_ADMIN_TOKEN, ADMIN_API_TOKEN
`;
}

function parseArgs(argv) {
  const args = {
    apiUrl: process.env.SUPPORT_SMOKE_API_URL || '',
    projectId: process.env.SUPPORT_SMOKE_PROJECT_ID || '',
    tenantId: process.env.SUPPORT_SMOKE_TENANT_ID || '',
    channelId: process.env.SUPPORT_SMOKE_CHANNEL_ID || '',
    channelKey: process.env.SUPPORT_SMOKE_CHANNEL_KEY || '',
    token: process.env.SUPPORT_ADMIN_TOKEN || process.env.ADMIN_API_TOKEN || '',
    transport: 'http',
    body: DEFAULT_BODY,
    replyBody: DEFAULT_REPLY,
    authorName: 'Lifecycle Smoke Customer',
    authorEmail: 'smoke-customer@example.invalid',
    authorId: '',
    fromAddress: 'support-agent@example.com',
    providerChannelId: '',
    threadId: '',
    messageId: '',
    eventId: '',
    attachments: [],
    replyAttachments: [],
    allowDeferred: false,
    json: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    const next = () => {
      index += 1;
      if (index >= argv.length) throw new Error(`Missing value for ${key}`);
      return argv[index];
    };
    if (key === '--help' || key === '-h') {
      args.help = true;
    } else if (key === '--api-url') {
      args.apiUrl = next();
    } else if (key === '--project-id') {
      args.projectId = next();
    } else if (key === '--tenant-id') {
      args.tenantId = next();
    } else if (key === '--channel-id') {
      args.channelId = next();
    } else if (key === '--channel-key') {
      args.channelKey = next();
    } else if (key === '--token') {
      args.token = next();
    } else if (key === '--transport') {
      args.transport = next();
    } else if (key === '--body') {
      args.body = next();
    } else if (key === '--reply-body') {
      args.replyBody = next();
    } else if (key === '--author-name') {
      args.authorName = next();
    } else if (key === '--author-email') {
      args.authorEmail = next();
    } else if (key === '--author-id') {
      args.authorId = next();
    } else if (key === '--from-address') {
      args.fromAddress = next();
    } else if (key === '--provider-channel-id') {
      args.providerChannelId = next();
    } else if (key === '--thread-id') {
      args.threadId = next();
    } else if (key === '--message-id') {
      args.messageId = next();
    } else if (key === '--event-id') {
      args.eventId = next();
    } else if (key === '--attachment') {
      args.attachments.push(parseJsonFlag(key, next()));
    } else if (key === '--reply-attachment') {
      args.replyAttachments.push(parseJsonFlag(key, next()));
    } else if (key === '--allow-deferred') {
      args.allowDeferred = true;
    } else if (key === '--json') {
      args.json = true;
    } else {
      throw new Error(`Unknown argument: ${key}`);
    }
  }
  return args;
}

function parseJsonFlag(key, value) {
  try {
    const parsed = JSON.parse(value);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('expected object');
    }
    return parsed;
  } catch (error) {
    throw new Error(`${key} must be a JSON object: ${error.message}`);
  }
}

function requireArgs(args) {
  if (args.help) return;
  const missing = [];
  if (!args.apiUrl.trim()) missing.push('--api-url');
  if (!args.projectId.trim()) missing.push('--project-id');
  if (!args.channelId.trim() && !args.channelKey.trim()) missing.push('--channel-id or --channel-key');
  if (args.transport !== 'http' && args.transport !== 'direct') {
    throw new Error('--transport must be http or direct');
  }
  if (!args.body.trim() && args.attachments.length === 0) missing.push('--body or --attachment');
  if (!args.replyBody.trim()) missing.push('--reply-body');
  if (missing.length > 0) throw new Error(`Missing required option(s): ${missing.join(', ')}`);
}

function baseUrl(apiUrl) {
  return apiUrl.replace(/\/+$/, '');
}

function headers(args) {
  const result = { 'Content-Type': 'application/json' };
  if (args.token.trim()) result.Authorization = `Bearer ${args.token.trim()}`;
  return result;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  let body = {};
  if (text.trim()) {
    try {
      body = JSON.parse(text);
    } catch {
      body = { detail: text };
    }
  }
  if (!response.ok) {
    const detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body);
    throw new Error(`${response.status} ${response.statusText}: ${detail}`);
  }
  return body;
}

async function resolveChannelId(args) {
  if (args.channelId.trim()) return args.channelId.trim();
  const url = `${baseUrl(args.apiUrl)}/api/admin/projects/${encodeURIComponent(args.projectId)}/channels?limit=200`;
  const data = await fetchJson(url, { headers: headers(args) });
  const items = Array.isArray(data.items) ? data.items : [];
  const channel = items.find(item => {
    const key = String(item.channelKey || item.channel_key || '').trim();
    return key === args.channelKey.trim();
  });
  if (!channel) throw new Error(`Channel key not found: ${args.channelKey}`);
  const id = String(channel.id || '').trim();
  if (!id) throw new Error(`Channel key has no id: ${args.channelKey}`);
  return id;
}

function smokePayload(args) {
  const smokeId = args.messageId.trim() || `lifecycle-smoke-${randomUUID()}`;
  return {
    body: args.body,
    replyBody: args.replyBody,
    authorName: args.authorName,
    authorEmail: args.authorEmail,
    authorId: args.authorId || `customer-${smokeId}`,
    fromAddress: args.fromAddress,
    channelId: args.providerChannelId,
    threadId: args.threadId,
    messageId: smokeId,
    eventId: args.eventId || smokeId,
    transport: args.transport,
    attachments: args.attachments,
    replyAttachments: args.replyAttachments,
  };
}

function passed(result, allowDeferred) {
  const hasTicket = Boolean(String(result.issueId || '').trim());
  const hasReply = Boolean(String(result.replyId || '').trim());
  const sent = result.sent === true || String(result.status || '').trim() === 'sent';
  const deferred = allowDeferred && (result.deferred === true || String(result.status || '').trim() === 'queued');
  return hasTicket && hasReply && (sent || deferred) && result.failed !== true;
}

function summary(result) {
  return [
    `status=${String(result.status || '') || '-'}`,
    `transport=${String(result.inbound?.transport || '') || String(result.transport || '') || '-'}`,
    `channel=${String(result.channelKey || '') || '-'}`,
    `issue=${String(result.issueId || '') || '-'}`,
    `reply=${String(result.replyId || '') || '-'}`,
    `provider=${String(result.provider || '') || '-'}`,
    `providerMessage=${String(result.providerMessageId || '') || '-'}`,
  ].join(' ');
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    process.stdout.write(usage());
    return 0;
  }
  requireArgs(args);
  const channelId = await resolveChannelId(args);
  const url = `${baseUrl(args.apiUrl)}/api/admin/projects/${encodeURIComponent(args.projectId)}/channels/${encodeURIComponent(channelId)}/lifecycle-smoke`;
  const result = await fetchJson(url, {
    method: 'POST',
    headers: headers(args),
    body: JSON.stringify(smokePayload(args)),
  });
  const ok = passed(result, args.allowDeferred);
  if (args.json) {
    process.stdout.write(`${JSON.stringify({ ok, result }, null, 2)}\n`);
  } else {
    process.stdout.write(`support channel lifecycle smoke: ${ok ? 'ok' : 'blocked'} ${summary(result)}\n`);
    if (!ok && result.error) process.stderr.write(`error: ${result.error}\n`);
  }
  return ok ? 0 : 2;
}

main().then(
  code => {
    process.exitCode = code;
  },
  error => {
    process.stderr.write(`support channel lifecycle smoke: error: ${error.message}\n`);
    process.exitCode = 1;
  },
);
