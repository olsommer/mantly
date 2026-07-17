import { type DragEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { AlertCircle, AlertTriangle, Bell, BookOpen, Building2, CheckCircle2, Clock, Columns3, Copy, Database, ExternalLink, Inbox as InboxIcon, Link, List, Loader, Mail, Pencil, Plus, RefreshCw, Save, Scissors, Search, Send, Sparkles, Star, Tag, Trash2, UserCheck, X } from 'lucide-react';
import { toast } from 'sonner';

import { api } from '@/api/endpoints';
import type { KnowledgeArticle, KnowledgeGap, ProjectMember, SupportAccount, SupportAccountInsight, SupportAccountInsightSummary, SupportActionExecution, SupportAgentAnswer, SupportAgentMessage, SupportAiRun, SupportAnalytics, SupportChannelActivationBacklog, SupportChannelWebhookEvent, SupportCustomFieldDefinition, SupportCustomFieldType, SupportExternalObject, SupportExternalSyncRun, SupportFieldPreparation, SupportInboxView, SupportIssue, SupportIssueActivityEvent, SupportIssueAnswerWorkspace, SupportIssueBoard, SupportIssueBoardAction, SupportIssueDuplicateSuggestion, SupportIssueListFilters, SupportIssueMessage, SupportIssuePriority, SupportIssueStatus, SupportNotification, SupportOutboundMessage, SupportQueue, SupportQueueOwnerWorkload, SupportReplyMacro, SupportRunbookConcern, SupportSlaEvent, SupportTriagePreparation, SupportWatcher } from '@/api/endpoints';
import { InboxAgentPanel } from './InboxAgentPanel';
import type { AgentArticleSource } from './InboxAgentPanel';
import { InboxAttachments } from './InboxAttachments';
import { InboxMessageTimeline } from './InboxMessageTimeline';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Drawer, DrawerContent, DrawerDescription, DrawerTitle } from '@/components/ui/drawer';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useI18n } from '@/lib/i18n-context';

interface InboxProps {
    projectId: string;
}

type WorkflowLane = 'open' | 'ongoing' | 'done';
type InboxView = 'list' | 'board';
type InboxStatusFilter = 'all' | 'needs-response' | 'approvals' | 'reply-approvals' | 'action-approvals' | 'unassigned' | 'failed-delivery' | 'low-csat' | 'due-soon-sla' | 'overdue-sla' | WorkflowLane;
type IssuePatch = Partial<Pick<SupportIssue, 'status' | 'priority' | 'assigneeEmail' | 'queueKey' | 'queueName' | 'tags' | 'customFields'>> & {
    workflowSource?: string;
    resolveWithoutReply?: boolean;
    resolutionNote?: string;
};
type TranslateFn = (key: string, params?: Record<string, string | number>) => string;
type SupportReplyReadiness = SupportIssueAnswerWorkspace['replyReadiness'];
type SupportTicketProof = SupportIssueAnswerWorkspace['ticketProof'];
type AgentQuickAction = {
    key: string;
    label: string;
    question: string;
    createDraft: boolean;
};
type AgentCitationPreview = {
    id: string;
    title: string;
    body: string;
    status: string;
    tags: string[];
    sourceUrl: string;
    visibility: string;
    public: boolean;
    score?: number;
};
type ActionExecutionReviewState = {
    status: 'approved' | 'rejected' | 'pending' | '';
    actor: string;
    at: string;
    note: string;
};
type ChannelSourceDetail = {
    label: string;
    value: string;
};
type ChannelSourceInfo = {
    channel: string;
    source: string;
    provider: string;
    channelKey: string;
    ticketMode: string;
    resolverAction: string;
    sourceIssueId: string;
    sourceMessageId: string;
    externalTicketKey: string;
    externalMessageKey: string;
    replyTarget: string;
    details: ChannelSourceDetail[];
};
type AutopilotActionProof = {
    type: string;
    label: string;
    status: string;
    executionId: string;
    runId: string;
    replyId: string;
    fieldCount: number;
    reason: string;
    error: string;
};
type AutopilotProof = {
    event: SupportIssueActivityEvent;
    complete: boolean;
    failed: boolean;
    channelKey: string;
    channelType: string;
    source: string;
    onUpdate: boolean;
    replyId: string;
    aiRunId: string;
    actions: AutopilotActionProof[];
    gaps: string[];
};
type LaneHealthSummary = {
    unassigned: number;
    needsResponse: number;
    approvals: number;
    failedDelivery: number;
    overdueSla: number;
    closeBlocked: number;
    attentionCount: number;
};
type LaneHealthBadge = {
    key: keyof Omit<LaneHealthSummary, 'attentionCount'>;
    label: string;
    count: number;
    variant: 'destructive' | 'secondary' | 'outline';
    title: string;
};
type ApprovalQueueCardProps = {
    issue: SupportIssue;
    active: boolean;
    selected: boolean;
    t: TranslateFn;
    onOpen: () => void;
    onSelectionChange: (selected: boolean) => void;
};
type SavedInboxFilters = {
    statusFilter: InboxStatusFilter;
    queueFilter: string;
    accountFilter: string;
    channelFilter: string;
    assigneeFilter: string;
    tagFilter: string;
    query: string;
    viewMode: InboxView;
};
type SupportViewPreset = {
    key: string;
    label: string;
    description: string;
    filters: SavedInboxFilters;
};

const UNASSIGNED_VALUE = '__unassigned__';
const ALL_ASSIGNEES_VALUE = '__all_assignees__';
const MY_ASSIGNEE_VALUE = '__my_assignee__';
const ALL_ACCOUNTS_VALUE = '__all_accounts__';
const NO_ACCOUNT_VALUE = '__no_account__';
const ALL_CHANNELS_VALUE = '__all_channels__';
const NO_CHANNEL_VALUE = '__no_channel__';
const ALL_QUEUES_VALUE = '__all_queues__';
const NO_QUEUE_VALUE = '__no_queue__';
const ALL_TAGS_VALUE = '__all_tags__';
const NO_TAGS_VALUE = '__no_tags__';
const NO_REPLY_MACRO_VALUE = '__no_reply_macro__';
const NO_ACCOUNT_RECORD_VALUE = '__no_account_record__';
const NO_CONTACT_RECORD_VALUE = '__no_contact_record__';
const inboxStatusFilters = new Set<InboxStatusFilter>(['all', 'needs-response', 'approvals', 'reply-approvals', 'action-approvals', 'unassigned', 'failed-delivery', 'low-csat', 'due-soon-sla', 'overdue-sla', 'open', 'ongoing', 'done']);
const inboxFilterQueryKeys = ['filter', 'queue', 'account', 'channel', 'assignee', 'label', 'q', 'view'];
const SLA_DUE_SOON_WINDOW_MS = 60 * 60 * 1000;
const INBOX_REFRESH_INTERVAL_MS = 15_000;
const REPLY_MACRO_TOKEN_PATTERN = /\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}/g;

function defaultSavedInboxFilters(viewMode: InboxView = 'board'): SavedInboxFilters {
    return {
        statusFilter: 'all',
        queueFilter: ALL_QUEUES_VALUE,
        accountFilter: ALL_ACCOUNTS_VALUE,
        channelFilter: ALL_CHANNELS_VALUE,
        assigneeFilter: ALL_ASSIGNEES_VALUE,
        tagFilter: ALL_TAGS_VALUE,
        query: '',
        viewMode,
    };
}

const supportViewPresets: SupportViewPreset[] = [
    {
        key: 'needs-response',
        label: 'Needs response',
        description: 'Customer replies waiting for an owner response.',
        filters: { ...defaultSavedInboxFilters('board'), statusFilter: 'needs-response' },
    },
    {
        key: 'approvals',
        label: 'Approvals',
        description: 'Agent replies and actions waiting for review.',
        filters: { ...defaultSavedInboxFilters('list'), statusFilter: 'approvals' },
    },
    {
        key: 'unassigned',
        label: 'Needs assignee',
        description: 'Tickets that still need a human owner.',
        filters: { ...defaultSavedInboxFilters('board'), statusFilter: 'unassigned' },
    },
    {
        key: 'overdue-sla',
        label: 'Overdue SLA',
        description: 'Breached SLA targets that need escalation.',
        filters: { ...defaultSavedInboxFilters('list'), statusFilter: 'overdue-sla' },
    },
    {
        key: 'due-soon-sla',
        label: 'SLA due soon',
        description: 'Tickets approaching their next SLA target.',
        filters: { ...defaultSavedInboxFilters('list'), statusFilter: 'due-soon-sla' },
    },
    {
        key: 'failed-delivery',
        label: 'Failed delivery',
        description: 'Replies that need retry or channel repair.',
        filters: { ...defaultSavedInboxFilters('list'), statusFilter: 'failed-delivery' },
    },
    {
        key: 'low-csat',
        label: 'Low CSAT',
        description: 'Customer feedback that needs recovery.',
        filters: { ...defaultSavedInboxFilters('list'), statusFilter: 'low-csat' },
    },
];

const statusOptions: Array<{ value: SupportIssueStatus; label: string }> = [
    { value: 'open', label: 'Open' },
    { value: 'ongoing', label: 'Ongoing' },
    { value: 'done', label: 'Done' },
];

const kanbanLanes: Array<{ value: WorkflowLane; label: string }> = [
    { value: 'open', label: 'Open' },
    { value: 'ongoing', label: 'Ongoing' },
    { value: 'done', label: 'Done' },
];

const agentQuickActions: AgentQuickAction[] = [
    {
        key: 'best-answer',
        label: 'Find answer',
        question: 'Find the best answer from the ticket context and knowledge base. Include what is known, what is uncertain, and which knowledge articles support the answer.',
        createDraft: false,
    },
    {
        key: 'prepare-reply',
        label: 'Prepare reply',
        question: 'Draft an approval-ready customer reply using the ticket context and knowledge base. Keep it concise, specific, and ready for a human to approve.',
        createDraft: true,
    },
    {
        key: 'next-step',
        label: 'Next step',
        question: 'Recommend the next internal action for the assignee. Include owner, urgency, and missing context.',
        createDraft: false,
    },
    {
        key: 'knowledge-gaps',
        label: 'Find gaps',
        question: 'Identify missing knowledge articles, account context, or runbook steps that block a confident answer.',
        createDraft: false,
    },
];

function normalizeInboxFilter(value: string | null | undefined): InboxStatusFilter {
    if (value && inboxStatusFilters.has(value as InboxStatusFilter)) {
        return value as InboxStatusFilter;
    }
    return 'all';
}

function normalizeInboxView(value: string | null | undefined): InboxView {
    return value === 'list' ? 'list' : 'board';
}

function inboxStatusFilterLabel(status: InboxStatusFilter, t: TranslateFn): string {
    const labels: Record<InboxStatusFilter, string> = {
        all: 'All',
        'needs-response': 'Needs response',
        approvals: 'Approvals',
        'reply-approvals': 'Reply approvals',
        'action-approvals': 'Action approvals',
        unassigned: 'Needs assignee',
        'failed-delivery': 'Failed delivery',
        'low-csat': 'Low CSAT',
        'due-soon-sla': 'SLA due soon',
        'overdue-sla': 'Overdue SLA',
        open: 'Open',
        ongoing: 'Ongoing',
        done: 'Done',
    };
    return t(labels[status]);
}

function inboxFiltersFromSearch(search: string): SavedInboxFilters {
    const params = new URLSearchParams(search);
    const defaults = defaultSavedInboxFilters();
    return {
        statusFilter: normalizeInboxFilter(params.get('filter')),
        queueFilter: params.get('queue') || defaults.queueFilter,
        accountFilter: params.get('account') || defaults.accountFilter,
        channelFilter: params.get('channel') || defaults.channelFilter,
        assigneeFilter: params.get('assignee') || defaults.assigneeFilter,
        tagFilter: params.get('label') || defaults.tagFilter,
        query: params.get('q') || defaults.query,
        viewMode: normalizeInboxView(params.get('view')),
    };
}

function inboxFiltersEqual(left: SavedInboxFilters, right: SavedInboxFilters): boolean {
    return left.statusFilter === right.statusFilter
        && left.queueFilter === right.queueFilter
        && left.accountFilter === right.accountFilter
        && left.channelFilter === right.channelFilter
        && left.assigneeFilter === right.assigneeFilter
        && left.tagFilter === right.tagFilter
        && left.query === right.query
        && left.viewMode === right.viewMode;
}

function searchWithInboxFilters(search: string, filters: SavedInboxFilters): string {
    const params = new URLSearchParams(search);
    for (const key of inboxFilterQueryKeys) params.delete(key);
    if (filters.statusFilter !== 'all') params.set('filter', filters.statusFilter);
    if (filters.queueFilter !== ALL_QUEUES_VALUE) params.set('queue', filters.queueFilter);
    if (filters.accountFilter !== ALL_ACCOUNTS_VALUE) params.set('account', filters.accountFilter);
    if (filters.channelFilter !== ALL_CHANNELS_VALUE) params.set('channel', filters.channelFilter);
    if (filters.assigneeFilter !== ALL_ASSIGNEES_VALUE) params.set('assignee', filters.assigneeFilter);
    if (filters.tagFilter !== ALL_TAGS_VALUE) params.set('label', filters.tagFilter);
    if (filters.query.trim()) params.set('q', filters.query.trim());
    if (filters.viewMode === 'list') params.set('view', 'list');
    return params.toString();
}

function boardApiStatusFilter(statusFilter: InboxStatusFilter): string {
    return [
        'needs-response',
        'approvals',
        'reply-approvals',
        'action-approvals',
        'unassigned',
        'failed-delivery',
        'low-csat',
        'due-soon-sla',
        'overdue-sla',
    ].includes(statusFilter) ? statusFilter : 'all';
}

function queueApiFilter(queueFilter: string): string {
    if (queueFilter === ALL_QUEUES_VALUE) return '';
    if (queueFilter === NO_QUEUE_VALUE) return NO_QUEUE_VALUE;
    return queueFilter;
}

function boardApiFiltersFrom(filters: SavedInboxFilters, currentUserEmail: string): SupportIssueListFilters {
    const apiFilters: SupportIssueListFilters = {};
    if (filters.accountFilter === NO_ACCOUNT_VALUE) apiFilters.accountKey = NO_ACCOUNT_VALUE;
    else if (filters.accountFilter !== ALL_ACCOUNTS_VALUE) apiFilters.accountKey = filters.accountFilter;
    if (filters.channelFilter === NO_CHANNEL_VALUE) apiFilters.channel = NO_CHANNEL_VALUE;
    else if (filters.channelFilter !== ALL_CHANNELS_VALUE) apiFilters.channel = filters.channelFilter;
    if (filters.assigneeFilter === UNASSIGNED_VALUE) apiFilters.assigneeEmail = UNASSIGNED_VALUE;
    else if (filters.assigneeFilter === MY_ASSIGNEE_VALUE) apiFilters.assigneeEmail = currentUserEmail.trim().toLowerCase();
    else if (filters.assigneeFilter !== ALL_ASSIGNEES_VALUE) apiFilters.assigneeEmail = filters.assigneeFilter;
    if (filters.tagFilter === NO_TAGS_VALUE) apiFilters.tag = NO_TAGS_VALUE;
    else if (filters.tagFilter !== ALL_TAGS_VALUE) apiFilters.tag = filters.tagFilter;
    if (filters.query.trim()) apiFilters.query = filters.query.trim();
    return Object.fromEntries(Object.entries(apiFilters).filter(([, value]) => Boolean(value))) as SupportIssueListFilters;
}

const priorityOptions: Array<{ value: SupportIssuePriority; label: string }> = [
    { value: 'urgent', label: 'Urgent' },
    { value: 'high', label: 'High' },
    { value: 'normal', label: 'Normal' },
    { value: 'low', label: 'Low' },
];

function formatTime(value: string) {
    if (!value) return '-';
    try {
        return new Intl.DateTimeFormat(undefined, {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        }).format(new Date(value));
    } catch {
        return value;
    }
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function textFrom(value: unknown): string {
    if (typeof value === 'string') return value;
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
    return '';
}

function textListFrom(value: unknown): string[] {
    if (!Array.isArray(value)) return [];
    return [...new Set(value.map(textFrom).filter(Boolean))].slice(0, 10);
}

function macroValueFromRecord(record: Record<string, unknown> | undefined, key: string): string {
    if (!record) return '';
    return textFrom(record[key]).trim();
}

function customFieldValue(issue: SupportIssue | null | undefined, fieldKey: string): string {
    const direct = macroValueFromRecord(issue?.customFields, fieldKey);
    if (direct) return direct;
    const customFields = issue?.metadata?.customFields;
    if (isRecord(customFields)) {
        return macroValueFromRecord(customFields, fieldKey);
    }
    return '';
}

function replyMacroTokenValue(
    token: string,
    context: {
        issue?: SupportIssue | null;
        account?: SupportAccount | null;
        currentUserEmail?: string;
    },
): string {
    const key = token.trim().toLowerCase();
    const { issue, account, currentUserEmail } = context;
    if (!key) return '';
    if (key === 'today') return new Date().toLocaleDateString();
    if (key === 'now') return new Date().toLocaleString();
    if (key.startsWith('custom.') || key.startsWith('field.') || key.startsWith('customfields.')) {
        return customFieldValue(issue, token.slice(token.indexOf('.') + 1));
    }
    const values: Record<string, string> = {
        'ticket.id': issue?.id ?? '',
        'issue.id': issue?.id ?? '',
        'ticket.subject': issue?.subject ?? '',
        'issue.subject': issue?.subject ?? '',
        'ticket.status': issue?.workflowStatus || issue?.status || '',
        'issue.status': issue?.workflowStatus || issue?.status || '',
        'ticket.priority': issue?.priority ?? '',
        'issue.priority': issue?.priority ?? '',
        'ticket.channel': issue?.channel ?? '',
        'issue.channel': issue?.channel ?? '',
        'ticket.queue': issue?.queueName || issue?.queueKey || '',
        'issue.queue': issue?.queueName || issue?.queueKey || '',
        'queue.name': issue?.queueName ?? '',
        'queue.key': issue?.queueKey ?? '',
        'assignee.email': issue?.assigneeEmail ?? '',
        'owner.email': issue?.assigneeEmail ?? '',
        'agent.email': currentUserEmail ?? '',
        'current_user.email': currentUserEmail ?? '',
        'contact.name': issue?.contactName ?? '',
        'customer.name': issue?.contactName ?? '',
        'requester.name': issue?.contactName ?? '',
        'contact.email': issue?.contactEmail || issue?.fromAddress || '',
        'customer.email': issue?.contactEmail || issue?.fromAddress || '',
        'requester.email': issue?.contactEmail || issue?.fromAddress || '',
        'account.name': issue?.accountName || account?.name || '',
        'account.domain': issue?.accountDomain || account?.domain || '',
        'account.health': account?.healthStatus || '',
    };
    return values[key] ?? '';
}

function renderReplyMacroBody(
    body: string,
    context: {
        issue?: SupportIssue | null;
        account?: SupportAccount | null;
        currentUserEmail?: string;
    },
) {
    return body.replace(REPLY_MACRO_TOKEN_PATTERN, (match, token: string) => {
        const value = replyMacroTokenValue(token, context);
        return value || match;
    });
}

function unresolvedReplyMacroTokens(body: string): string[] {
    const tokens = new Set<string>();
    for (const match of body.matchAll(REPLY_MACRO_TOKEN_PATTERN)) {
        const token = match[1]?.trim();
        if (token) tokens.add(token);
    }
    return [...tokens];
}

const customFieldTypes: SupportCustomFieldType[] = ['text', 'number', 'select', 'boolean', 'date', 'url'];

function customFieldDefinitionsFromMetadata(metadata: Record<string, unknown> | undefined): SupportCustomFieldDefinition[] {
    const source = metadata ?? {};
    const raw = Array.isArray(source.customFields)
        ? source.customFields
        : Array.isArray(source.custom_fields)
            ? source.custom_fields
            : [];
    return raw
        .filter((item): item is Record<string, unknown> => isRecord(item))
        .map((item) => {
            const rawType = (textFrom(item.type) || 'text') as SupportCustomFieldType;
            const type = customFieldTypes.includes(rawType) ? rawType : 'text';
            const options = Array.isArray(item.options)
                ? item.options.map(option => textFrom(option).trim()).filter(Boolean)
                : textFrom(item.options).split(',').map(option => option.trim()).filter(Boolean);
            return {
                key: textFrom(item.key),
                label: textFrom(item.label || item.key),
                type,
                required: item.required === true,
                options,
            };
        })
        .filter(item => item.key && item.label);
}

function customFieldDisplayValue(value: unknown) {
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    return textFrom(value);
}

function emailListFrom(value: unknown): string[] {
    const rawItems = Array.isArray(value)
        ? value
        : typeof value === 'string'
            ? value.replace(/\n/g, ',').split(',')
            : [];
    const seen = new Set<string>();
    const emails: string[] = [];
    for (const item of rawItems) {
        const email = typeof item === 'string' ? item.trim().toLowerCase() : '';
        if (!email || seen.has(email)) continue;
        seen.add(email);
        emails.push(email);
    }
    return emails;
}

function queueOwnerEmails(queue: SupportQueue | null): string[] {
    const metadata = queue?.metadata ?? {};
    return emailListFrom(
        metadata.allowedAssigneeEmails
        ?? metadata.allowed_assignee_emails
        ?? metadata.assigneeEmails
        ?? metadata.assignee_emails
        ?? metadata.ownerEmails
        ?? metadata.owner_emails
        ?? metadata.owners,
    );
}

function queueOwnerWorkloadByEmail(queue: SupportQueue | null): Map<string, SupportQueueOwnerWorkload> {
    const workloads = new Map<string, SupportQueueOwnerWorkload>();
    for (const item of queue?.ownerWorkloads ?? []) {
        const email = item.assigneeEmail.trim().toLowerCase();
        if (email) workloads.set(email, item);
    }
    return workloads;
}

function queueOwnerWorkloadLabel(email: string, workload?: SupportQueueOwnerWorkload): string {
    if (!workload) return email;
    if (workload.capacity > 0) {
        const suffix = workload.atCapacity ? ' at capacity' : '';
        return `${email} (${workload.activeTickets}/${workload.capacity}${suffix})`;
    }
    return `${email} (${workload.activeTickets} active)`;
}

function queueOwnerWorkloadDetail(email: string, workload?: SupportQueueOwnerWorkload): string {
    if (!workload) return '';
    if (workload.capacity > 0 && workload.atCapacity) {
        return `${email} is at ${workload.activeTickets}/${workload.capacity} active tickets for this queue.`;
    }
    if (workload.capacity > 0) {
        return `${email} has ${workload.activeTickets}/${workload.capacity} active tickets for this queue.`;
    }
    return `${email} has ${workload.activeTickets} active tickets for this queue.`;
}

function messageText(message: SupportIssueMessage): string {
    if (message.body) return message.body;
    if (typeof message.content === 'string') return message.content;
    if (isRecord(message.content)) {
        const body = textFrom(message.content.emailBody) || textFrom(message.content.email_body);
        if (body) return body;
    }
    return '';
}

function messageLabel(message: SupportIssueMessage) {
    if (message.direction === 'ai' || message.user === 'response') return 'AI draft';
    if (message.direction === 'customer' || message.user === 'email') return 'Customer email';
    if (message.direction === 'agent') return 'Agent reply';
    return 'Internal note';
}

function messageIdentifier(message: SupportIssueMessage): string {
    return message.id || message.sourceMessageId || '';
}

function sameTimelineMessage(a: SupportIssueMessage, b: SupportIssueMessage): boolean {
    const aId = messageIdentifier(a);
    const bId = messageIdentifier(b);
    if (aId && bId) return aId === bId;
    return a === b;
}

function messageOccurredAt(message: SupportIssueMessage): string {
    return message.occurredAt || '';
}

function latestTimelineMessageAt(messages: SupportIssueMessage[]): string {
    return messages
        .map(messageOccurredAt)
        .filter(Boolean)
        .sort()
        .at(-1) ?? '';
}

function canSplitTimelineMessage(message: SupportIssueMessage, totalMessages: number): boolean {
    if (totalMessages <= 1 || !messageIdentifier(message)) return false;
    const direction = (message.direction || message.user || '').toLowerCase();
    const kind = (message.messageKind || message.role || '').toLowerCase();
    return direction !== 'ai' && direction !== 'response' && !kind.includes('outbound');
}

function defaultSplitSubject(issue: SupportIssue, message: SupportIssueMessage): string {
    const base = issue.subject || messageText(message).slice(0, 80) || issue.id;
    return `Split: ${base}`;
}

function recordText(record: Record<string, unknown> | undefined, ...keys: string[]): string {
    if (!record) return '';
    for (const key of keys) {
        const value = textFrom(record[key]);
        if (value) return value;
    }
    return '';
}

function latestChannelMessage(issue: SupportIssue): SupportIssueMessage | null {
    const messages = issue.messages ?? [];
    for (const message of [...messages].reverse()) {
        if (message.direction && !['customer', 'visitor', 'agent'].includes(message.direction)) continue;
        const metadata = message.metadata ?? {};
        if (
            message.sourceMessageId
            || recordText(metadata, 'provider', 'channelKey', 'channelId', 'chatId', 'conversationId', 'threadId', 'threadTs')
        ) {
            return message;
        }
    }
    return messages[messages.length - 1] ?? null;
}

function ticketModeLabel(mode: string): string {
    if (mode === 'per_thread') return 'Thread';
    if (mode === 'per_message') return 'Every message';
    return mode;
}

function resolverActionLabel(action: string): string {
    if (action === 'created') return 'Created';
    if (action === 'updated') return 'Updated';
    if (action === 'deduplicated') return 'Deduplicated';
    return action || 'Linked';
}

function sourceProofActionVariant(action: string): 'secondary' | 'outline' {
    return action === 'created' ? 'secondary' : 'outline';
}

function channelSourceInfo(issue: SupportIssue): ChannelSourceInfo | null {
    const message = latestChannelMessage(issue);
    const messageMetadata = message?.metadata ?? {};
    const issueMetadata = issue.metadata ?? {};
    const resolver = isRecord(messageMetadata.resolver)
        ? messageMetadata.resolver
        : isRecord(issueMetadata.resolver)
            ? issueMetadata.resolver
            : {};
    const channel = issue.channel || recordText(messageMetadata, 'channel') || recordText(issueMetadata, 'channel');
    const source = issue.source || recordText(messageMetadata, 'source', 'issueSource') || recordText(issueMetadata, 'source', 'issueSource');
    const provider = recordText(messageMetadata, 'provider', 'externalProvider')
        || recordText(issueMetadata, 'provider', 'externalProvider')
        || recordText(resolver, 'provider')
        || channel;
    const channelKey = recordText(messageMetadata, 'channelKey')
        || recordText(issueMetadata, 'channelKey')
        || recordText(resolver, 'channelKey')
        || source;
    const ticketMode = recordText(messageMetadata, 'ticketCreationMode')
        || recordText(issueMetadata, 'ticketCreationMode')
        || recordText(resolver, 'ticketCreationMode');
    const resolverAction = recordText(resolver, 'resolverAction');
    const sourceIssueId = recordText(messageMetadata, 'sourceIssueId')
        || recordText(issueMetadata, 'sourceIssueId')
        || recordText(resolver, 'sourceIssueId')
        || issue.sourceEmailId;
    const sourceMessageId = message?.sourceMessageId
        || recordText(messageMetadata, 'sourceMessageId')
        || recordText(issueMetadata, 'sourceMessageId')
        || recordText(resolver, 'sourceMessageId');
    const externalTicketKey = recordText(messageMetadata, 'externalTicketKey')
        || recordText(issueMetadata, 'externalTicketKey')
        || recordText(resolver, 'externalTicketKey');
    const externalMessageKey = recordText(messageMetadata, 'externalMessageKey')
        || recordText(issueMetadata, 'externalMessageKey')
        || recordText(resolver, 'externalMessageKey');
    const channelId = recordText(messageMetadata, 'channelId', 'chatId', 'conversationId', 'webChatSessionId')
        || recordText(issueMetadata, 'channelId', 'chatId', 'conversationId', 'webChatSessionId')
        || recordText(resolver, 'providerChannelId');
    const threadId = recordText(messageMetadata, 'threadId', 'threadTs')
        || recordText(issueMetadata, 'threadId', 'threadTs')
        || recordText(resolver, 'threadId');
    const providerMessageId = recordText(messageMetadata, 'providerMessageId', 'messageId', 'eventId')
        || recordText(issueMetadata, 'providerMessageId', 'messageId', 'eventId')
        || recordText(resolver, 'providerMessageId');
    const reply = (issue.outboundMessages ?? []).find(item => replyTargetDetail(item)) ?? null;
    const replyTarget = reply ? replyTargetDetail(reply) : '';

    const details: ChannelSourceDetail[] = [
        { label: 'Provider', value: provider },
        { label: 'Channel key', value: channelKey },
        { label: 'Channel ID', value: channelId },
        { label: 'Thread', value: threadId },
        { label: 'Source issue', value: sourceIssueId },
        { label: 'Source message', value: sourceMessageId || providerMessageId },
        { label: 'External ticket', value: externalTicketKey },
        { label: 'External message', value: externalMessageKey },
        { label: 'Reply target', value: replyTarget },
    ].filter(item => item.value);

    if (!channel && !source && details.length === 0) return null;
    return {
        channel,
        source,
        provider,
        channelKey,
        ticketMode,
        resolverAction,
        sourceIssueId,
        sourceMessageId,
        externalTicketKey,
        externalMessageKey,
        replyTarget,
        details,
    };
}

function conversationSourceLabel(source: string): string {
    if (source === 'externalConversationKey') return 'Conversation';
    if (source === 'externalThreadKey' || source === 'threadId' || source === 'threadTs') return 'Thread';
    if (source === 'webChatSessionId' || source === 'sessionKey') return 'Web chat';
    if (source === 'conversationId') return 'Conversation';
    if (source === 'contact') return 'Contact';
    if (source === 'account') return 'Account';
    return source || 'Context';
}

function conversationAnchorLabel(source: string, label: string): string {
    const sourceLabel = conversationSourceLabel(source);
    if (!label) return sourceLabel;
    return `${sourceLabel}: ${shortProofValue(label, 64)}`;
}

function outboundTimelineMessage(reply: SupportOutboundMessage): SupportIssueMessage {
    return {
        id: `outbound:${reply.id}`,
        sourceMessageId: `outbound:${reply.id}`,
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
        occurredAt: reply.sentAt || new Date().toISOString(),
    };
}

function appendSentReplyToTimeline(messages: SupportIssueMessage[] | undefined, reply: SupportOutboundMessage) {
    const existingMessages = messages ?? [];
    const sourceMessageId = `outbound:${reply.id}`;
    if (existingMessages.some(message => message.sourceMessageId === sourceMessageId || message.id === sourceMessageId)) {
        return existingMessages;
    }
    return [...existingMessages, outboundTimelineMessage(reply)];
}

function issueSearchText(issue: SupportIssue): string {
    const customFieldText = Object.entries(issue.customFields ?? {})
        .flatMap(([key, value]) => [key, customFieldDisplayValue(value)])
        .filter(Boolean);
    return [
        issue.subject,
        issue.fromAddress,
        issue.accountName,
        issue.contactEmail,
        issue.queueName,
        issue.queueKey,
        issue.channel,
        issue.source,
        ...(issue.tags ?? []),
        ...customFieldText,
        issue.activatedIntent,
        issue.aiSummary,
    ].join(' ').toLowerCase();
}

function parseIssueTags(value: string | string[] | undefined): string[] {
    const rawItems = Array.isArray(value) ? value : String(value ?? '').replace(/\n/g, ',').split(',');
    const tags: string[] = [];
    const seen = new Set<string>();
    for (const item of rawItems) {
        const tag = item.trim().replace(/\s+/g, ' ').slice(0, 64);
        const key = tag.toLowerCase();
        if (!tag || seen.has(key)) continue;
        seen.add(key);
        tags.push(tag);
        if (tags.length >= 20) break;
    }
    return tags;
}

function savedInboxFiltersFrom(value: Record<string, unknown>): SavedInboxFilters {
    const savedStatus = normalizeInboxFilter(textFrom(value.statusFilter));
    const savedViewMode = normalizeInboxView(textFrom(value.viewMode));
    return {
        statusFilter: savedStatus,
        queueFilter: textFrom(value.queueFilter) || ALL_QUEUES_VALUE,
        accountFilter: textFrom(value.accountFilter) || ALL_ACCOUNTS_VALUE,
        channelFilter: textFrom(value.channelFilter) || ALL_CHANNELS_VALUE,
        assigneeFilter: textFrom(value.assigneeFilter) || ALL_ASSIGNEES_VALUE,
        tagFilter: textFrom(value.tagFilter) || ALL_TAGS_VALUE,
        query: textFrom(value.query),
        viewMode: savedViewMode,
    };
}

function issueQueueKey(issue: SupportIssue): string {
    return issue.queueKey?.trim() || '';
}

function issueQueueLabel(issue: SupportIssue): string {
    return issue.queueName?.trim() || issue.queueKey?.trim() || 'No queue';
}

function issueAccountLabel(issue: SupportIssue): string {
    return issue.accountName?.trim() || issue.accountDomain?.trim() || 'No account';
}

function issueAccountKey(issue: SupportIssue): string {
    const accountId = issue.accountId?.trim();
    if (accountId) return `id:${accountId}`;
    const label = issue.accountName?.trim() || issue.accountDomain?.trim();
    return label ? `label:${label.toLowerCase()}` : '';
}

function issueChannelKey(issue: SupportIssue): string {
    return issue.channel?.trim().toLowerCase() || '';
}

function issueChannelLabel(issue: SupportIssue): string {
    return issue.channel?.trim() || 'No channel';
}

function issueAssigneeKey(issue: SupportIssue): string {
    return issue.assigneeEmail?.trim().toLowerCase() || '';
}

function mergeTargetLabel(issue: SupportIssue): string {
    const identity = issue.accountName || issue.contactEmail || issue.fromAddress;
    return [issue.subject || '(No subject)', identity].filter(Boolean).join(' - ');
}

function duplicateScoreLabel(score: number): string {
    if (score >= 80) return 'Strong';
    if (score >= 55) return 'Likely';
    return 'Possible';
}

function duplicateSummaryTitle(issue: SupportIssue): string | undefined {
    if (!issue.duplicateSuggestionCount) return undefined;
    const target = issue.topDuplicateIssueSubject || issue.topDuplicateIssueId;
    const reasons = (issue.duplicateReasons ?? []).join(', ');
    return [target ? `Matches ${target}` : '', reasons].filter(Boolean).join(' - ') || undefined;
}

function knowledgeSearchText(article: KnowledgeArticle): string {
    return [article.title, article.body, article.status, article.visibility, article.sourceUrl, (article.tags ?? []).join(' ')].join(' ').toLowerCase();
}

function knowledgeVisibilityLabel(visibility: string, isPublic?: boolean): string {
    const normalized = visibility.trim().toLowerCase();
    if (normalized === 'public' || isPublic === true) return 'Public';
    if (normalized === 'private') return 'Private';
    return 'Internal';
}

function knowledgeSourceUrl(value: Pick<KnowledgeArticle, 'sourceUrl'> | AgentCitationPreview): string {
    return value.sourceUrl.trim();
}

function knowledgeMatch(article: KnowledgeArticle): Record<string, unknown> | null {
    const match = article.metadata?.knowledgeMatch;
    return isRecord(match) ? match : null;
}

function knowledgeMatchScore(article: KnowledgeArticle): number {
    const score = knowledgeMatch(article)?.score;
    return typeof score === 'number' ? score : 0;
}

function knowledgeMatchTerms(article: KnowledgeArticle): string[] {
    const terms = knowledgeMatch(article)?.matchedTerms;
    return Array.isArray(terms) ? terms.map(textFrom).filter(Boolean).slice(0, 4) : [];
}

function knowledgeMatchSignals(article: KnowledgeArticle): string[] {
    const signals = knowledgeMatch(article)?.signals;
    return Array.isArray(signals) ? signals.map(textFrom).filter(Boolean).slice(0, 3) : [];
}

function statusIcon(status: string) {
    const workflowStatus = normalizeWorkflowStatus(status);
    if (workflowStatus === 'done') return <CheckCircle2 className="size-3.5" />;
    if (workflowStatus === 'ongoing') return <Clock className="size-3.5" />;
    return <AlertCircle className="size-3.5" />;
}

function normalizeWorkflowStatus(status: string): WorkflowLane {
    if (status === 'done' || status === 'closed') return 'done';
    if (status === 'ongoing' || status === 'pending' || status === 'triaged') return 'ongoing';
    return 'open';
}

function issueWorkflowStatus(issue: SupportIssue): WorkflowLane {
    return issue.workflowStatus ?? normalizeWorkflowStatus(issue.status);
}

function replyActionOwnerEmail(reply: SupportOutboundMessage, fallbackEmail: string): string {
    return textFrom(reply.metadata.approvedBy)
        || textFrom(reply.metadata.approved_by)
        || reply.createdBy
        || fallbackEmail.trim()
        || reply.fromAddress;
}

function replyApprovalIssuePatch(
    issue: SupportIssue,
    reply: SupportOutboundMessage,
    actorEmail: string,
): Partial<SupportIssue> {
    const patch: Partial<SupportIssue> = {};
    const workflowStatus = issueWorkflowStatus(issue);
    if (workflowStatus !== 'ongoing' && workflowStatus !== 'done') {
        patch.status = 'ongoing';
        patch.workflowStatus = 'ongoing';
    }
    if (!issue.assigneeEmail) {
        const ownerEmail = replyActionOwnerEmail(reply, actorEmail);
        if (ownerEmail) patch.assigneeEmail = ownerEmail;
    }
    return patch;
}

function sentReplyIssuePatch(reply: SupportOutboundMessage, actorEmail: string): Partial<SupportIssue> {
    const patch: Partial<SupportIssue> = { status: 'ongoing', workflowStatus: 'ongoing' };
    const ownerEmail = replyActionOwnerEmail(reply, actorEmail);
    if (ownerEmail) patch.assigneeEmail = ownerEmail;
    return patch;
}

function statusNeedsAssignee(status: string): boolean {
    return ['open', 'ongoing', 'done'].includes(normalizeWorkflowStatus(status));
}

function workflowLabel(status: string) {
    const workflowStatus = normalizeWorkflowStatus(status);
    if (workflowStatus === 'done') return 'Done';
    if (workflowStatus === 'ongoing') return 'Ongoing';
    return 'Open';
}

function activityEventKey(event: SupportIssueActivityEvent) {
    return event.id || `${event.eventType}-${event.occurredAt}`;
}

function isWorkflowProofEvent(event: SupportIssueActivityEvent): boolean {
    if (event.eventType !== 'status_changed' || !event.fromStatus || !event.toStatus) return false;
    if (event.metadata?.workflowTransition === true) return true;
    return normalizeWorkflowStatus(event.fromStatus) !== normalizeWorkflowStatus(event.toStatus);
}

function activityEventTitle(event: SupportIssueActivityEvent): string {
    if (isWorkflowProofEvent(event)) return 'Lifecycle proof';
    if (event.eventType === 'channel_agent_autopilot') {
        const metadata = event.metadata ?? {};
        const rawActions: unknown[] = Array.isArray(metadata.actions)
            ? metadata.actions as unknown[]
            : [];
        const replyAction: unknown = rawActions
            .find(action => isRecord(action)
                && textFrom(action.type).toLowerCase() === 'prepare_agent_reply');
        const replyId = textFrom(metadata.replyId ?? metadata.reply_id)
            || (isRecord(replyAction) ? textFrom(replyAction.replyId ?? replyAction.reply_id) : '');
        const draftBlockedReason = textFrom(
            metadata.draftBlockedReason ?? metadata.draft_blocked_reason,
        );
        const replyActionClaimedPrepared = isRecord(replyAction)
            && textFrom(replyAction.status).toLowerCase() === 'prepared';
        if (!replyId && (draftBlockedReason || replyActionClaimedPrepared)) {
            return 'Channel autopilot reply withheld';
        }
    }
    return event.title || event.eventType;
}

function activityEventChangeText(event: SupportIssueActivityEvent): string {
    const parts = [
        event.fromStatus && event.toStatus
            ? `${isWorkflowProofEvent(event) ? 'Workflow ' : ''}${workflowLabel(event.fromStatus)} -> ${workflowLabel(event.toStatus)}`
            : '',
        event.fromPriority && event.toPriority ? `${event.fromPriority} -> ${event.toPriority}` : '',
    ].filter(Boolean);
    return parts.join(' · ');
}

function priorityVariant(priority: string): 'destructive' | 'secondary' | 'outline' {
    if (priority === 'urgent') return 'destructive';
    if (priority === 'high') return 'secondary';
    return 'outline';
}

function accountHealthVariant(status: string): 'destructive' | 'secondary' | 'outline' {
    if (status === 'at_risk' || status === 'blocked') return 'destructive';
    if (status === 'needs_attention' || status === 'active') return 'secondary';
    return 'outline';
}

function syncVariant(status: string): 'destructive' | 'secondary' | 'outline' {
    const normalized = status.toLowerCase();
    if (normalized === 'failed' || normalized === 'partial') return 'destructive';
    if (normalized === 'success' || normalized === 'completed') return 'secondary';
    return 'outline';
}

function providerLabel(provider: string) {
    if (provider === 'hubspot') return 'HubSpot';
    if (provider === 'salesforce') return 'Salesforce';
    if (provider === 'identity') return 'Identity';
    return provider || 'CRM';
}

function accountLabel(account: SupportAccount) {
    return account.name || account.domain || account.accountKey || 'Unknown account';
}

function insightIsUnresolved(status: string) {
    return !['resolved', 'closed', 'dismissed'].includes(status);
}

function accountInsightSummary(account: SupportAccount): SupportAccountInsightSummary {
    const insights = account.insights ?? [];
    if (insights.length === 0 && account.insightSummary) return account.insightSummary;
    const risks = insights.filter(insight => insight.type === 'risk');
    const featureRequests = insights.filter(insight => insight.type === 'feature_request');
    return {
        total: insights.length,
        unresolved: insights.filter(insight => insightIsUnresolved(insight.status)).length,
        risks: risks.length,
        openRisks: risks.filter(insight => insightIsUnresolved(insight.status)).length,
        featureRequests: featureRequests.length,
        openFeatureRequests: featureRequests.filter(insight => insightIsUnresolved(insight.status)).length,
        summaries: insights.filter(insight => insight.type === 'summary').length,
        lastInsightAt: insights.map(insight => insight.lastSeenAt || insight.updated).sort().at(-1) ?? '',
    };
}

function mergeAccountInsight(account: SupportAccount, insight: SupportAccountInsight): SupportAccount {
    const insights = [insight, ...(account.insights ?? []).filter(item => item.id !== insight.id)];
    return {
        ...account,
        healthStatus: insight.type === 'risk' && insight.status !== 'resolved'
            ? 'at_risk'
            : account.healthStatus,
        insights,
        insightSummary: accountInsightSummary({ ...account, insights }),
    };
}

function updateAccountInsightInAccount(account: SupportAccount, insight: SupportAccountInsight): SupportAccount {
    const insights = (account.insights ?? []).some(item => item.id === insight.id)
        ? (account.insights ?? []).map(item => item.id === insight.id ? insight : item)
        : [insight, ...(account.insights ?? [])];
    return {
        ...account,
        insights,
        insightSummary: accountInsightSummary({ ...account, insights }),
    };
}

function syncRunTime(run: SupportExternalSyncRun) {
    return run.completedAt || run.startedAt || run.updated || run.created || '';
}

function syncRunScore(run: SupportExternalSyncRun) {
    const value = Date.parse(syncRunTime(run));
    return Number.isNaN(value) ? 0 : value;
}

function crmProviders(objects: SupportExternalObject[], runs: SupportExternalSyncRun[]) {
    const providers = new Set<string>();
    objects.forEach(object => {
        if (object.provider) providers.add(object.provider);
    });
    runs.forEach(run => {
        if (run.provider) providers.add(run.provider);
    });
    return Array.from(providers).sort();
}

function accountCrmHealth(account: SupportAccount) {
    const externalObjects = account.externalObjects ?? [];
    const syncRuns = account.externalSyncRuns ?? [];
    const failedRuns = syncRuns.filter(run => ['failed', 'partial'].includes(run.status.toLowerCase()));
    const latestRun = syncRuns.slice().sort((a, b) => syncRunScore(b) - syncRunScore(a))[0];
    const providers = crmProviders(externalObjects, syncRuns);
    return {
        externalObjects,
        syncRuns,
        failedRuns,
        latestRun,
        providers,
        variant: failedRuns.length > 0
            ? 'destructive' as const
            : externalObjects.length > 0 ? 'secondary' as const : 'outline' as const,
        label: failedRuns.length > 0
            ? 'CRM attention'
            : externalObjects.length > 0 ? 'CRM linked' : 'No CRM records',
    };
}

function tokenTotal(value: Record<string, unknown>): number {
    const raw = value.totalTokens ?? value.total_tokens ?? value.total;
    return typeof raw === 'number' ? raw : 0;
}

function isAgentChatRun(run: SupportAiRun): boolean {
    return run.source === 'agent_answer' || run.metadata.kind === 'agent_answer';
}

function latestRunbookConcerns(runs: SupportAiRun[]): SupportRunbookConcern[] {
    for (const run of runs) {
        const concerns = run.intentResult.concerns;
        if (!Array.isArray(concerns)) continue;
        const validConcerns = concerns.filter(isRecord) as SupportRunbookConcern[];
        if (validConcerns.length > 0) return validConcerns;
    }
    return [];
}

function runbookConcernStatus(concern: SupportRunbookConcern): string {
    const status = textFrom(concern.status).toLowerCase();
    if (status) return status;
    if (concern.requiresHuman === true) return 'requires_human';
    if (concern.matched === true) return 'ready';
    return 'unmatched';
}

function runbookConcernStatusLabel(status: string): string {
    if (status === 'ready') return 'Ready';
    if (status === 'requires_human') return 'Human review';
    if (status === 'failed') return 'Failed';
    return 'No match';
}

function RunbookAudit({
    primaryIntent,
    concerns,
    t,
}: {
    primaryIntent: string;
    concerns: SupportRunbookConcern[];
    t: TranslateFn;
}) {
    return (
        <div className="space-y-2" data-ticket-runbook-audit data-ticket-runbook-concern-count={concerns.length}>
            <div>
                <div className="text-xs font-medium uppercase text-muted-foreground">{t('Runbook')}</div>
                <div className="mt-1 text-sm" data-ticket-runbook-primary>{primaryIntent || t('No match')}</div>
            </div>
            {concerns.length > 0 && (
                <div className="space-y-2" data-ticket-runbook-concerns>
                    <div className="flex items-center justify-between gap-2 text-xs font-medium uppercase text-muted-foreground">
                        <span>{t('Concerns')}</span>
                        <Badge variant="outline" className="font-normal">{concerns.length}</Badge>
                    </div>
                    {concerns.map((concern, index) => {
                        const concernId = textFrom(concern.concernId) || `concern-${index + 1}`;
                        const intentName = textFrom(concern.intentName);
                        const summary = textFrom(concern.concernSummary)
                            || textFrom(concern.summary)
                            || `${t('Concern')} ${index + 1}`;
                        const status = runbookConcernStatus(concern);
                        return (
                            <div
                                key={`${concernId}-${index}`}
                                className="rounded-md border bg-muted/20 p-2 text-sm"
                                data-ticket-runbook-concern={concernId}
                                data-ticket-runbook-concern-intent={intentName}
                                data-ticket-runbook-concern-status={status}
                            >
                                <div className="flex items-start justify-between gap-2">
                                    <span className="min-w-0 text-xs text-muted-foreground">{summary}</span>
                                    <Badge variant={intentName ? 'secondary' : 'outline'} className="max-w-[55%] shrink-0 truncate font-normal">
                                        {intentName || t('No match')}
                                    </Badge>
                                </div>
                                <div className="mt-1 text-xs text-muted-foreground">{t(runbookConcernStatusLabel(status))}</div>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

function agentRunQuestion(run: SupportAiRun): string {
    return textFrom(run.metadata.question);
}

function agentRunAnswer(run: SupportAiRun): string {
    return textFrom(run.metadata.answer) || run.summary;
}

function citationFromRecord(value: unknown): AgentCitationPreview | null {
    if (!isRecord(value)) return null;
    const title = textFrom(value.title);
    const id = textFrom(value.id);
    if (!title && !id) return null;
    const tags = Array.isArray(value.tags) ? value.tags.map(textFrom).filter(Boolean).slice(0, 6) : [];
    const metadata = isRecord(value.metadata) ? value.metadata : {};
    const rawMatch = isRecord(metadata.knowledgeMatch)
        ? metadata.knowledgeMatch
        : metadata.knowledge_match;
    const match = isRecord(rawMatch) ? rawMatch : {};
    const rawScore = typeof value.score === 'number' ? value.score : typeof match.score === 'number' ? match.score : undefined;
    return {
        id,
        title: title || id,
        body: textFrom(value.body),
        status: textFrom(value.status),
        tags,
        sourceUrl: textFrom(value.sourceUrl ?? value.source_url ?? metadata.sourceUrl ?? metadata.source_url ?? metadata.url),
        visibility: textFrom(value.visibility ?? metadata.visibility ?? metadata.access),
        public: value.public === true || metadata.public === true,
        score: rawScore,
    };
}

function agentAnswerCitationPreviews(answer: SupportAgentAnswer | null): AgentCitationPreview[] {
    if (!answer) return [];
    return (answer.citations ?? [])
        .map(citationFromRecord)
        .filter((item): item is AgentCitationPreview => Boolean(item));
}

function agentRunCitationPreviews(run: SupportAiRun): AgentCitationPreview[] {
    const raw = Array.isArray(run.metadata.citations)
        ? run.metadata.citations
        : Array.isArray(run.metadata.knowledgeCitations)
            ? run.metadata.knowledgeCitations
            : [];
    const citations = raw.map(citationFromRecord).filter((item): item is AgentCitationPreview => Boolean(item));
    if (citations.length > 0) return citations;
    return (run.toolCalls ?? [])
        .filter(tool => textFrom(tool.type) === 'knowledge_article')
        .map(citationFromRecord)
        .filter((item): item is AgentCitationPreview => Boolean(item));
}

function compactAgentText(value: string, max = 280): string {
    const compact = value.replace(/\s+/g, ' ').trim();
    if (compact.length <= max) return compact;
    return `${compact.slice(0, max - 3)}...`;
}

function agentRunFollowUpPrompt(run: SupportAiRun): string {
    const question = agentRunQuestion(run);
    const answer = agentRunAnswer(run);
    return [
        'Follow up on this previous agent turn.',
        question ? `Previous question: ${question}` : '',
        answer ? `Previous answer: ${compactAgentText(answer)}` : '',
        'New ask:',
    ].filter(Boolean).join('\n');
}

function autopilotActionLabel(type: string): string {
    if (type === 'prepare_triage') return 'Triage';
    if (type === 'prepare_custom_fields') return 'Custom fields';
    if (type === 'prepare_agent_reply') return 'Draft reply';
    return type || 'Action';
}

function autopilotActionProof(value: unknown): AutopilotActionProof | null {
    if (!isRecord(value)) return null;
    const type = textFrom(value.type).toLowerCase();
    if (!type) return null;
    const rawFieldCount = value.fieldCount ?? value.field_count;
    return {
        type,
        label: autopilotActionLabel(type),
        status: textFrom(value.status).toLowerCase() || 'unknown',
        executionId: textFrom(value.executionId ?? value.execution_id),
        runId: textFrom(value.runId ?? value.run_id),
        replyId: textFrom(value.replyId ?? value.reply_id),
        fieldCount: typeof rawFieldCount === 'number' ? rawFieldCount : 0,
        reason: textFrom(value.reason),
        error: textFrom(value.error),
    };
}

function autopilotActionStatus(actions: AutopilotActionProof[], type: string): string {
    return actions.find(action => action.type === type)?.status ?? '';
}

function autopilotDraftWithheldReason(reason: string): string {
    if (reason === 'ungrounded_answer') {
        return 'The answer was not sufficiently grounded, so no reply was created.';
    }
    if (reason === 'grounding_evidence_incomplete') {
        return 'Grounding evidence was incomplete, so no reply was created.';
    }
    if (reason === 'grounding_check_failed') {
        return 'Grounding verification did not pass, so no reply was created.';
    }
    return reason || 'No reply was created.';
}

function autopilotPackageGaps(actions: AutopilotActionProof[]): string[] {
    const gaps: string[] = [];
    if (autopilotActionStatus(actions, 'prepare_triage') !== 'prepared') gaps.push('Triage');
    const fieldStatus = autopilotActionStatus(actions, 'prepare_custom_fields');
    if (fieldStatus && !['prepared', 'skipped'].includes(fieldStatus)) gaps.push('Custom fields');
    if (!fieldStatus) gaps.push('Custom fields');
    if (autopilotActionStatus(actions, 'prepare_agent_reply') !== 'prepared') gaps.push('Draft reply');
    return gaps;
}

function latestAutopilotProof(issue: SupportIssue): AutopilotProof | null {
    const events = (issue.activityEvents ?? [])
        .filter(event => event.eventType === 'channel_agent_autopilot' || event.eventType === 'channel_agent_autopilot_failed')
        .slice()
        .sort((a, b) => Date.parse(b.occurredAt || b.created) - Date.parse(a.occurredAt || a.created));
    const event = events[0];
    if (!event) return null;
    const metadata = event.metadata ?? {};
    const context = isRecord(metadata.automationContext)
        ? metadata.automationContext
        : isRecord(metadata.automation_context)
            ? metadata.automation_context
            : {};
    const replyId = textFrom(metadata.replyId ?? metadata.reply_id);
    const draftBlockedReason = textFrom(
        metadata.draftBlockedReason ?? metadata.draft_blocked_reason,
    ).toLowerCase();
    const actions = (Array.isArray(metadata.actions) ? metadata.actions : [])
        .map(autopilotActionProof)
        .filter((action): action is AutopilotActionProof => Boolean(action))
        .map(action => {
            if (action.type !== 'prepare_agent_reply') return action;
            const provenReplyId = action.replyId || replyId;
            if (action.status === 'prepared' && !provenReplyId) {
                return {
                    ...action,
                    status: 'withheld',
                    reason: action.reason || autopilotDraftWithheldReason(draftBlockedReason),
                };
            }
            return provenReplyId === action.replyId ? action : { ...action, replyId: provenReplyId };
        });
    const aiRunId = textFrom(metadata.aiRunId ?? metadata.ai_run_id);
    const gaps = autopilotPackageGaps(actions);
    const failed = event.eventType === 'channel_agent_autopilot_failed';
    return {
        event,
        complete: !failed && Boolean(replyId && aiRunId && actions.length > 0 && gaps.length === 0),
        failed,
        channelKey: textFrom(metadata.channelKey ?? metadata.channel_key ?? context.channelKey ?? context.channel_key),
        channelType: textFrom(metadata.channelType ?? metadata.channel_type ?? context.channelType ?? context.channel_type),
        source: textFrom(metadata.source ?? context.eventSource ?? context.source),
        onUpdate: metadata.onUpdate === true || context.onUpdate === true,
        replyId,
        aiRunId,
        actions,
        gaps,
    };
}

function autopilotStatusVariant(status: string): 'destructive' | 'secondary' | 'outline' {
    if (status === 'failed') return 'destructive';
    if (status === 'prepared') return 'secondary';
    return 'outline';
}

function replyNeedsApproval(reply: SupportOutboundMessage): boolean {
    return reply.metadata.approvalRequired === true
        && reply.metadata.approved !== true
        && reply.metadata.reviewStatus !== 'changes_requested';
}

function replyChangesRequested(reply: SupportOutboundMessage): boolean {
    return reply.metadata.reviewStatus === 'changes_requested';
}

function replyChangesNote(reply: SupportOutboundMessage): string {
    return textFrom(reply.metadata.changesNote);
}

function replyAttachmentItems(reply: SupportOutboundMessage): unknown[] {
    if (Array.isArray(reply.attachments) && reply.attachments.length > 0) return reply.attachments;
    const metadataAttachments = reply.metadata.attachments;
    return Array.isArray(metadataAttachments) ? metadataAttachments : [];
}

function replaceOutboundReply(replies: SupportOutboundMessage[], reply: SupportOutboundMessage): SupportOutboundMessage[] {
    return replies.some(item => item.id === reply.id)
        ? replies.map(item => item.id === reply.id ? reply : item)
        : [reply, ...replies];
}

function outboundReplySummaryFromReplies(replies: SupportOutboundMessage[], actionApprovalCount = 0) {
    const replyApprovalCount = replies.filter(replyNeedsApproval).length;
    const pendingApprovalCount = replyApprovalCount + actionApprovalCount;
    const failedDeliveryCount = replies.filter(replyFailedDelivery).length;
    const pendingDeliveryCount = replies.filter(replyPendingDelivery).length;
    return {
        hasPendingApproval: pendingApprovalCount > 0,
        pendingApprovalCount,
        hasPendingReplyApproval: replyApprovalCount > 0,
        pendingReplyApprovalCount: replyApprovalCount,
        hasFailedDelivery: failedDeliveryCount > 0,
        failedDeliveryCount,
        hasPendingDelivery: pendingDeliveryCount > 0,
        pendingDeliveryCount,
    };
}

function replaceActionExecution(executions: SupportActionExecution[], execution: SupportActionExecution): SupportActionExecution[] {
    return executions.some(item => item.id === execution.id)
        ? executions.map(item => item.id === execution.id ? execution : item)
        : [execution, ...executions];
}

function actionExecutionProposedAction(execution: SupportActionExecution): Record<string, unknown> | null {
    const fromResult = execution.result.proposedAction ?? execution.result.proposed_action;
    if (isRecord(fromResult)) return fromResult;
    const fromMetadata = execution.metadata.proposedAction ?? execution.metadata.proposed_action;
    return isRecord(fromMetadata) ? fromMetadata : null;
}

function actionExecutionNeedsApproval(execution: SupportActionExecution): boolean {
    return (
        execution.status === 'pending'
        && execution.metadata.approvalRequired === true
        && textFrom(execution.metadata.reviewStatus || 'pending') === 'pending'
    );
}

function actionExecutionReviewState(execution: SupportActionExecution): ActionExecutionReviewState {
    const approval = isRecord(execution.result.approval) ? execution.result.approval : {};
    const rawStatus = textFrom(execution.metadata.reviewStatus || approval.status);
    const status = rawStatus === 'approved' || rawStatus === 'rejected' || rawStatus === 'pending' ? rawStatus : '';
    if (status === 'approved') {
        return {
            status,
            actor: textFrom(execution.metadata.approvedBy || approval.approvedBy || execution.metadata.reviewerEmail),
            at: textFrom(execution.metadata.approvedAt || approval.approvedAt || execution.completedAt),
            note: textFrom(execution.metadata.changesNote || approval.note),
        };
    }
    if (status === 'rejected') {
        return {
            status,
            actor: textFrom(execution.metadata.rejectedBy || approval.rejectedBy || execution.metadata.reviewerEmail),
            at: textFrom(execution.metadata.rejectedAt || approval.rejectedAt || execution.completedAt),
            note: textFrom(execution.metadata.changesNote || approval.note || execution.error),
        };
    }
    return {
        status,
        actor: '',
        at: '',
        note: '',
    };
}

function explicitCount(value: number | null | undefined): number | null {
    return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, value) : null;
}

function pendingActionApprovalCount(issue: SupportIssue): number {
    return explicitCount(issue.pendingActionApprovalCount)
        ?? (issue.actionExecutions ?? []).filter(actionExecutionNeedsApproval).length;
}

function pendingReplyApprovalCount(issue: SupportIssue): number {
    return explicitCount(issue.pendingReplyApprovalCount)
        ?? (issue.outboundMessages ?? []).filter(replyNeedsApproval).length;
}

function issueApprovalCount(issue: SupportIssue): number {
    return Math.max(
        explicitCount(issue.pendingApprovalCount) ?? 0,
        pendingReplyApprovalCount(issue) + pendingActionApprovalCount(issue),
    );
}

function blockerCountLabel(count: number, singular: string, plural: string): string {
    if (count <= 0) return '';
    return count === 1 ? `1 ${singular}` : `${count} ${plural}`;
}

function actionExecutionDetail(execution: SupportActionExecution): string {
    const action = actionExecutionProposedAction(execution);
    if (!action) return textFrom(execution.result.summary) || textFrom(execution.metadata.summary);
    const type = textFrom(action.type || action.actionType || action.action_type || action.action);
    if (type === 'assign' || type === 'set_assignee') {
        const assignee = textFrom(action.assigneeEmail || action.assignee_email || action.email);
        return assignee ? `Assign to ${assignee}` : 'Assign ticket';
    }
    if (type === 'set_status') {
        const status = textFrom(action.status);
        return status ? `Set status to ${status}` : 'Set status';
    }
    if (type === 'set_priority') {
        const priority = textFrom(action.priority);
        return priority ? `Set priority to ${priority}` : 'Set priority';
    }
    if (type === 'set_custom_fields' || type === 'set_custom_field' || type === 'update_custom_fields') {
        const fields = action.customFields || action.custom_fields || action.fields || action.values;
        const labels = Object.entries(isRecord(fields) ? fields : {})
            .map(([field, value]) => `${field}=${customFieldDisplayValue(value)}`);
        return labels.length > 0 ? `Set fields ${labels.slice(0, 3).join(', ')}` : 'Set fields';
    }
    if (type === 'triage_ticket' || type === 'triage' || type === 'update_issue') {
        const labels = [
            action.priority ? `priority=${textFrom(action.priority)}` : '',
            action.status ? `status=${textFrom(action.status)}` : '',
            action.assigneeEmail || action.assignee_email ? `assignee=${textFrom(action.assigneeEmail || action.assignee_email)}` : '',
            action.queueName || action.queue_name || action.queueKey || action.queue_key
                ? `queue=${textFrom(action.queueName || action.queue_name || action.queueKey || action.queue_key)}`
                : '',
            Array.isArray(action.tags) && action.tags.length > 0 ? `tags=${action.tags.map(textFrom).filter(Boolean).slice(0, 3).join(',')}` : '',
        ].filter(Boolean);
        return labels.length > 0 ? `Triage ${labels.join(', ')}` : 'Triage ticket';
    }
    if (type === 'add_note') {
        return textFrom(action.body || action.note) || 'Add internal note';
    }
    return textFrom(action.label || action.tool || action.name) || type;
}

function aggregateCountWithDelta(current: number, previousActive: boolean, nextActive: boolean): number {
    return Math.max(0, current + (nextActive ? 1 : 0) - (previousActive ? 1 : 0));
}

function mergeActionExecutionIntoIssue(issue: SupportIssue, execution: SupportActionExecution): SupportIssue {
    const previous = (issue.actionExecutions ?? []).find(item => item.id === execution.id) ?? null;
    const actionExecutions = replaceActionExecution(issue.actionExecutions ?? [], execution);
    const actionApprovalCount = aggregateCountWithDelta(
        pendingActionApprovalCount(issue),
        previous ? actionExecutionNeedsApproval(previous) : false,
        actionExecutionNeedsApproval(execution),
    );
    const replyApprovalCount = pendingReplyApprovalCount(issue);
    const pendingApprovalCount = replyApprovalCount + actionApprovalCount;
    return {
        ...issue,
        actionExecutions,
        pendingApprovalCount,
        hasPendingApproval: pendingApprovalCount > 0,
        pendingActionApprovalCount: actionApprovalCount,
        hasPendingActionApproval: actionApprovalCount > 0,
    };
}

function mergeOutboundReplyIntoIssue(
    issue: SupportIssue,
    reply: SupportOutboundMessage,
    options: {
        mode?: 'full' | 'aggregate';
        previousReply?: SupportOutboundMessage | null;
        issuePatch?: Partial<SupportIssue>;
        appendSentTimeline?: boolean;
    } = {},
): SupportIssue {
    const previousReplies = issue.outboundMessages ?? [];
    const previousReply = previousReplies.find(item => item.id === reply.id) ?? options.previousReply ?? null;
    const outboundMessages = replaceOutboundReply(previousReplies, reply);
    const issueWithPatch = { ...issue, ...(options.issuePatch ?? {}) };
    const messages = options.appendSentTimeline && reply.status === 'sent'
        ? appendSentReplyToTimeline(issueWithPatch.messages, reply)
        : issueWithPatch.messages;
    if (options.mode !== 'aggregate') {
        return {
            ...issueWithPatch,
            messages,
            outboundMessages,
            ...outboundReplySummaryFromReplies(outboundMessages, pendingActionApprovalCount(issueWithPatch)),
        };
    }

    const previousNeedsApproval = previousReply ? replyNeedsApproval(previousReply) : false;
    const replyApprovalCount = aggregateCountWithDelta(
        pendingReplyApprovalCount(issue),
        previousNeedsApproval,
        replyNeedsApproval(reply),
    );
    const actionApprovalCount = pendingActionApprovalCount(issueWithPatch);
    const pendingApprovalCount = replyApprovalCount + actionApprovalCount;
    const failedDeliveryCount = aggregateCountWithDelta(
        issue.failedDeliveryCount || 0,
        previousReply ? replyFailedDelivery(previousReply) : false,
        replyFailedDelivery(reply),
    );
    const pendingDeliveryCount = aggregateCountWithDelta(
        issue.pendingDeliveryCount || 0,
        previousReply ? replyPendingDelivery(previousReply) : false,
        replyPendingDelivery(reply),
    );
    return {
        ...issueWithPatch,
        messages,
        outboundMessages,
        hasPendingApproval: pendingApprovalCount > 0,
        pendingApprovalCount,
        hasPendingReplyApproval: replyApprovalCount > 0,
        pendingReplyApprovalCount: replyApprovalCount,
        hasFailedDelivery: failedDeliveryCount > 0,
        failedDeliveryCount,
        hasPendingDelivery: pendingDeliveryCount > 0,
        pendingDeliveryCount,
    };
}

function issueNeedsApproval(issue: SupportIssue): boolean {
    return issue.hasPendingApproval || issueApprovalCount(issue) > 0;
}

function approvalLabel(issue: SupportIssue): string {
    const count = issueApprovalCount(issue) || 1;
    return count === 1 ? '1 approval' : `${count} approvals`;
}

function reviewPackageParts(issue: SupportIssue): string[] {
    const replyDrafts = pendingReplyApprovalCount(issue);
    const actionProposals = pendingActionApprovalCount(issue);
    const parts = [];
    if (replyDrafts > 0) parts.push(replyDrafts === 1 ? '1 reply draft' : `${replyDrafts} reply drafts`);
    if (actionProposals > 0) parts.push(actionProposals === 1 ? '1 action proposal' : `${actionProposals} action proposals`);
    if (parts.length === 0 && issueNeedsApproval(issue)) parts.push(approvalLabel(issue));
    return parts;
}

function reviewPackageSummary(issue: SupportIssue): string {
    return reviewPackageParts(issue).join(' + ');
}

function approvalPreviewText(issue: SupportIssue): string {
    const pendingReply = (issue.outboundMessages ?? []).find(replyNeedsApproval);
    if (pendingReply?.body) return pendingReply.body;
    const pendingAction = (issue.actionExecutions ?? []).find(actionExecutionNeedsApproval);
    if (pendingAction) return actionExecutionDetail(pendingAction);
    return issue.aiSummary || issue.draftReply || '';
}

function replyFailedDelivery(reply: SupportOutboundMessage): boolean {
    return reply.status === 'failed' || reply.status === 'delivery_uncertain';
}

function replyPendingDelivery(reply: SupportOutboundMessage): boolean {
    return reply.status === 'queued' || reply.status === 'sending';
}

function replyDeliveryLocked(reply: SupportOutboundMessage): boolean {
    return reply.status === 'sending' || reply.status === 'delivery_uncertain';
}

function replyStatusLabel(reply: SupportOutboundMessage): string {
    if (reply.status === 'delivery_uncertain') return 'Delivery uncertain';
    if (reply.status === 'sending') return 'Sending';
    return reply.status;
}

function issueHasFailedDelivery(issue: SupportIssue): boolean {
    const failedDeliveryCount = explicitCount(issue.failedDeliveryCount);
    if (failedDeliveryCount !== null) return failedDeliveryCount > 0;
    return issue.hasFailedDelivery || (issue.outboundMessages ?? []).some(replyFailedDelivery);
}

function issueHasPendingDelivery(issue: SupportIssue): boolean {
    const pendingDeliveryCount = explicitCount(issue.pendingDeliveryCount);
    if (pendingDeliveryCount !== null) return pendingDeliveryCount > 0;
    return issue.hasPendingDelivery || (issue.outboundMessages ?? []).some(replyPendingDelivery);
}

function issueOperationalDoneBlockers(issue: SupportIssue): string[] {
    const blockers: string[] = [];
    const replyDrafts = pendingReplyApprovalCount(issue);
    const actionProposals = pendingActionApprovalCount(issue);
    const fallbackApprovals = Math.max(0, issueApprovalCount(issue) - replyDrafts - actionProposals);
    if (replyDrafts > 0) blockers.push(blockerCountLabel(replyDrafts, 'reply draft awaiting approval', 'reply drafts awaiting approval'));
    if (actionProposals > 0) blockers.push(blockerCountLabel(actionProposals, 'action proposal awaiting approval', 'action proposals awaiting approval'));
    if (fallbackApprovals > 0) blockers.push(blockerCountLabel(fallbackApprovals, 'approval pending', 'approvals pending'));
    if (issueHasPendingDelivery(issue)) blockers.push('queued replies');
    if (issueHasFailedDelivery(issue)) blockers.push('failed deliveries');
    return blockers;
}

function issueResponseDoneBlockers(issue: SupportIssue): string[] {
    const blockers: string[] = [];
    if (issueNeedsResponse(issue)) blockers.push('customer response required');
    if ((issue.outboundMessages ?? []).some(replyChangesRequested)) {
        blockers.push('reply changes requested');
    }
    return blockers;
}

function issueDoneBlockers(issue: SupportIssue): string[] {
    return [...issueOperationalDoneBlockers(issue), ...issueResponseDoneBlockers(issue)];
}

function issueCanResolveWithoutReply(issue: SupportIssue): boolean {
    return issueOperationalDoneBlockers(issue).length === 0
        && issueResponseDoneBlockers(issue).length > 0;
}

function issueDoneBlockerText(issue: SupportIssue): string {
    return issueDoneBlockers(issue).join(', ');
}

function laneHealthSummary(issues: SupportIssue[]): LaneHealthSummary {
    const summary: LaneHealthSummary = {
        unassigned: 0,
        needsResponse: 0,
        approvals: 0,
        failedDelivery: 0,
        overdueSla: 0,
        closeBlocked: 0,
        attentionCount: 0,
    };
    for (const issue of issues) {
        if (issueNeedsAssignee(issue)) summary.unassigned += 1;
        if (issueNeedsResponse(issue)) summary.needsResponse += 1;
        if (issueNeedsApproval(issue)) summary.approvals += 1;
        if (issueHasFailedDelivery(issue)) summary.failedDelivery += 1;
        if (issueHasOverdueSla(issue)) summary.overdueSla += 1;
        if (issueDoneBlockers(issue).length > 0) summary.closeBlocked += 1;
    }
    summary.attentionCount = summary.unassigned
        + summary.needsResponse
        + summary.approvals
        + summary.failedDelivery
        + summary.overdueSla;
    return summary;
}

function laneHealthBadges(summary: LaneHealthSummary): LaneHealthBadge[] {
    const badges: LaneHealthBadge[] = [
        {
            key: 'unassigned',
            label: 'Unassigned',
            count: summary.unassigned,
            variant: 'outline',
            title: 'Tickets without an assignee',
        },
        {
            key: 'needsResponse',
            label: 'Needs reply',
            count: summary.needsResponse,
            variant: 'secondary',
            title: 'Tickets waiting for a customer reply',
        },
        {
            key: 'approvals',
            label: 'Approvals',
            count: summary.approvals,
            variant: 'secondary',
            title: 'Tickets with reply drafts or action proposals waiting for human review',
        },
        {
            key: 'failedDelivery',
            label: 'Failed delivery',
            count: summary.failedDelivery,
            variant: 'destructive',
            title: 'Tickets with failed outbound delivery',
        },
        {
            key: 'overdueSla',
            label: 'Overdue SLA',
            count: summary.overdueSla,
            variant: 'destructive',
            title: 'Tickets with overdue SLA targets',
        },
        {
            key: 'closeBlocked',
            label: 'Close blocked',
            count: summary.closeBlocked,
            variant: 'outline',
            title: 'Tickets that cannot move to Done yet',
        },
    ];
    return badges.filter(item => item.count > 0);
}

function failedDeliveryLabel(issue: SupportIssue): string {
    const count = explicitCount(issue.failedDeliveryCount)
        ?? ((issue.outboundMessages ?? []).filter(replyFailedDelivery).length || 1);
    return count === 1 ? '1 failed delivery' : `${count} failed deliveries`;
}

function pendingDeliveryLabel(issue: SupportIssue): string {
    const count = explicitCount(issue.pendingDeliveryCount)
        ?? ((issue.outboundMessages ?? []).filter(replyPendingDelivery).length || 1);
    return count === 1 ? '1 queued reply' : `${count} queued replies`;
}

function replyNextAttemptAt(reply: SupportOutboundMessage): string {
    return textFrom(reply.metadata.nextAttemptAt) || textFrom(reply.metadata.next_attempt_at);
}

function replyRetryDeferred(nextAttemptAt: string): boolean {
    if (!nextAttemptAt) return false;
    const timestamp = Date.parse(nextAttemptAt);
    return Number.isFinite(timestamp) && timestamp > Date.now();
}

function replyProviderDetail(reply: SupportOutboundMessage): string {
    return [reply.provider, reply.providerMessageId].filter(Boolean).join(' - ');
}

function replyTargetDetail(reply: SupportOutboundMessage): string {
    const target = isRecord(reply.metadata.replyTarget) ? reply.metadata.replyTarget : null;
    const label = textFrom(target?.label);
    if (label) return label;
    const targetValue = textFrom(target?.value);
    if (targetValue) {
        const targetKey = textFrom(target?.key);
        if (targetKey) return `${targetKey}: ${targetValue}`;
        return targetValue;
    }
    return reply.toAddress;
}

function shortProofValue(value: string, max = 40): string {
    if (value.length <= max) return value;
    const head = Math.max(8, Math.floor((max - 3) / 2));
    const tail = Math.max(6, max - 3 - head);
    return `${value.slice(0, head)}...${value.slice(-tail)}`;
}

function channelWebhookEventStatusVariant(status: string): 'destructive' | 'secondary' | 'outline' {
    if (['failed', 'unmatched', 'error'].includes(status)) return 'destructive';
    if (['processed', 'success', 'sent', 'delivered'].includes(status)) return 'secondary';
    return 'outline';
}

function channelWebhookNestedIssueId(record: Record<string, unknown>): string {
    const direct = recordText(record, 'issueId', 'issue_id', 'sourceIssueId', 'source_issue_id');
    if (direct) return direct;
    for (const key of ['issue', 'inbound', 'delivery', 'message', 'item', 'result']) {
        const nested = record[key];
        if (isRecord(nested)) {
            const value = channelWebhookNestedIssueId(nested);
            if (value) return value;
        }
    }
    for (const key of ['items', 'events']) {
        const items = record[key];
        if (!Array.isArray(items)) continue;
        for (const item of items) {
            if (isRecord(item)) {
                const value = channelWebhookNestedIssueId(item);
                if (value) return value;
            }
        }
    }
    return '';
}

function channelWebhookEventDetails(event: SupportChannelWebhookEvent): ChannelSourceDetail[] {
    const result = event.result ?? {};
    const payload = event.payload ?? {};
    const issueId = channelWebhookNestedIssueId(result) || channelWebhookNestedIssueId(payload);
    const providerMessageId = event.providerMessageId
        || recordText(result, 'providerMessageId', 'provider_message_id', 'messageId', 'message_id')
        || recordText(payload, 'providerMessageId', 'provider_message_id', 'messageId', 'message_id');
    const outboundMessageId = event.outboundMessageId || recordText(result, 'outboundMessageId', 'outbound_message_id', 'replyId', 'reply_id');
    return [
        { label: 'Event', value: event.eventId },
        { label: 'Provider message', value: providerMessageId },
        { label: 'Ticket', value: issueId },
        { label: 'Reply draft', value: outboundMessageId },
    ].filter(detail => detail.value);
}

function replyDeliveryReceipt(reply: SupportOutboundMessage): Record<string, unknown> | null {
    const receipt = reply.metadata.deliveryReceipt ?? reply.metadata.delivery_receipt;
    return isRecord(receipt) ? receipt : null;
}

function replyDeliveryPreflight(reply: SupportOutboundMessage): Record<string, unknown> | null {
    const preflight = reply.metadata.deliveryPreflight ?? reply.metadata.delivery_preflight;
    return isRecord(preflight) ? preflight : null;
}

function replyDeliveryAttempts(reply: SupportOutboundMessage): string {
    return textFrom(reply.metadata.deliveryAttempts) || textFrom(reply.metadata.delivery_attempts);
}

function replyLastAttemptAt(reply: SupportOutboundMessage): string {
    return textFrom(reply.metadata.lastAttemptAt) || textFrom(reply.metadata.last_attempt_at);
}

function replyLastDeliveryError(reply: SupportOutboundMessage): string {
    return textFrom(reply.metadata.lastDeliveryError)
        || textFrom(reply.metadata.last_delivery_error)
        || textFrom(reply.metadata.lastTransientError)
        || textFrom(reply.metadata.last_transient_error);
}

interface ReplyDeliveryProofChip {
    label: string;
    detail?: string;
    variant?: 'outline' | 'secondary' | 'destructive';
}

function replyDeliveryProofChips(reply: SupportOutboundMessage): ReplyDeliveryProofChip[] {
    const receipt = replyDeliveryReceipt(reply);
    const providerMessageId = reply.providerMessageId
        || textFrom(reply.metadata.providerMessageId)
        || textFrom(reply.metadata.provider_message_id)
        || textFrom(receipt?.providerMessageId)
        || textFrom(receipt?.provider_message_id);
    const provider = textFrom(receipt?.provider) || reply.provider || reply.channel;
    const attempts = replyDeliveryAttempts(reply);
    const lastAttemptAt = replyLastAttemptAt(reply);
    const channelId = textFrom(reply.metadata.channelId)
        || textFrom(reply.metadata.channel_id)
        || textFrom(reply.metadata.chatId)
        || textFrom(reply.metadata.chat_id)
        || textFrom(reply.metadata.conversationId)
        || textFrom(reply.metadata.conversation_id)
        || textFrom(reply.metadata.webChatSessionId)
        || textFrom(reply.metadata.web_chat_session_id);
    const threadId = textFrom(reply.metadata.threadId)
        || textFrom(reply.metadata.thread_id)
        || textFrom(reply.metadata.threadTs)
        || textFrom(reply.metadata.thread_ts);
    const lastError = replyLastDeliveryError(reply);
    const targetDetail = replyTargetDetail(reply);
    const preflight = replyDeliveryPreflight(reply);
    const chips: ReplyDeliveryProofChip[] = [];
    if (targetDetail && reply.status !== 'sent') {
        chips.push({ label: 'Target', detail: shortProofValue(targetDetail, 48) });
    }
    if (preflight && reply.status !== 'sent') {
        const status = textFrom(preflight.status);
        const transport = textFrom(preflight.transport);
        const preflightProvider = textFrom(preflight.provider);
        chips.push({
            label: status === 'blocked' ? 'Preflight blocked' : 'Preflight ready',
            detail: [preflightProvider, transport].filter(Boolean).join(' - '),
            variant: status === 'blocked' ? 'destructive' : 'outline',
        });
    }
    if (reply.status === 'sent' && providerMessageId) {
        chips.push({
            label: 'Delivery proof',
            detail: [provider, shortProofValue(providerMessageId)].filter(Boolean).join(' - '),
        });
    }
    if (receipt) {
        const eventType = textFrom(receipt.eventType) || textFrom(receipt.event_type) || 'matched';
        const receivedAt = textFrom(receipt.receivedAt) || textFrom(receipt.received_at);
        chips.push({
            label: eventType === 'matched' ? 'Receipt matched' : `Receipt ${eventType}`,
            detail: receivedAt ? formatTime(receivedAt) : undefined,
            variant: eventType.includes('fail') || eventType.includes('bounce') ? 'destructive' : 'outline',
        });
    }
    if (attempts) {
        chips.push({
            label: `Attempt ${attempts}`,
            detail: lastAttemptAt ? formatTime(lastAttemptAt) : undefined,
        });
    }
    if (channelId) chips.push({ label: `Channel ${shortProofValue(channelId, 32)}` });
    if (threadId) chips.push({ label: `Thread ${shortProofValue(threadId, 32)}` });
    if (lastError && reply.status !== 'failed') {
        chips.push({ label: 'Last delivery error', detail: lastError, variant: 'destructive' });
    }
    return chips;
}

type AutoSendBadgeVariant = 'outline' | 'secondary' | 'destructive';

interface ReplyAutoSendState {
    label: string;
    detail: string;
    variant: AutoSendBadgeVariant;
}

function autoSendReasonLabel(reason: string): string {
    if (reason === 'approval_required') return 'Approval required';
    return reason.split('_').join(' ');
}

function replyAutoSendState(reply: SupportOutboundMessage): ReplyAutoSendState | null {
    const requested = reply.metadata.autoSendRequested === true || reply.metadata.autoSend === true;
    const active = reply.metadata.autoSend === true;
    const blockedReason = textFrom(reply.metadata.autoSendBlockedReason);
    if (!requested && !active && !blockedReason) return null;
    if (blockedReason) {
        const reason = autoSendReasonLabel(blockedReason);
        return {
            label: 'Auto-send blocked',
            detail: reason,
            variant: 'secondary',
        };
    }
    if (active) {
        let label = 'Auto-send queued';
        let variant: AutoSendBadgeVariant = 'outline';
        if (reply.status === 'sent') label = 'Auto-sent';
        if (reply.status === 'failed') {
            label = 'Auto-send failed';
            variant = 'destructive';
        }
        return {
            label,
            detail: 'No approval required',
            variant,
        };
    }
    return {
        label: 'Auto-send requested',
        detail: textFrom(reply.metadata.autoSendPolicy),
        variant: 'outline',
    };
}

function generationModeLabel(value: string | undefined): string {
    if (value === 'llm') return 'LLM';
    if (value === 'knowledge_agent') return 'Knowledge agent';
    if (value === 'deterministic_fallback') return 'Fallback';
    return value || '';
}

function replyAutomationContext(reply: SupportOutboundMessage): Record<string, unknown> | null {
    const context = reply.metadata.automationContext ?? reply.metadata.automation_context;
    return isRecord(context) ? context : null;
}

function automationContextLabel(context: Record<string, unknown>): string {
    const source = textFrom(context.source);
    if (source === 'channel_autopilot') {
        const channel = textFrom(context.channelKey) || textFrom(context.eventSource);
        return channel ? `Channel autopilot - ${channel}` : 'Channel autopilot';
    }
    const ruleName = textFrom(context.ruleName);
    const actionLabel = textFrom(context.actionLabel);
    if (ruleName && actionLabel && actionLabel !== textFrom(context.actionType)) {
        return `${ruleName} - ${actionLabel}`;
    }
    return ruleName || actionLabel || (source === 'automation' ? 'Automation rule' : source);
}

function issueNeedsAssignee(issue: SupportIssue): boolean {
    return !issue.assigneeEmail;
}

function issueAssignmentRequired(issue: SupportIssue): boolean {
    const value = issue.metadata?.assignmentRequired ?? issue.metadata?.assignment_required;
    return issueNeedsAssignee(issue) && (value === true || textFrom(value).toLowerCase() === 'true');
}

function issueAssignmentBadge(issue: SupportIssue): string {
    return issueAssignmentRequired(issue) ? 'Routing missed owner' : 'Needs assignee';
}

function issueAssignmentSourceDetail(issue: SupportIssue): string {
    const metadata = issue.metadata ?? {};
    const source = textFrom(metadata.assignmentSource ?? metadata.assignment_source) || issue.source || issue.channel;
    const channel = textFrom(metadata.assignmentChannelKey ?? metadata.assignment_channel_key);
    const queue = (
        textFrom(metadata.assignmentQueueName ?? metadata.assignment_queue_name)
        || textFrom(metadata.assignmentQueueKey ?? metadata.assignment_queue_key)
        || issue.queueName
        || issue.queueKey
    );
    return [
        source ? `source ${source}` : '',
        channel ? `channel ${channel}` : '',
        queue ? `queue ${queue}` : '',
    ].filter(Boolean).join(' · ');
}

function issueAssignmentDetail(issue: SupportIssue): string {
    const detail = issueAssignmentSourceDetail(issue);
    if (issueAssignmentRequired(issue)) {
        return detail ? `No default owner matched · ${detail}` : 'No default owner matched.';
    }
    return detail || 'Claim or assign this ticket before work starts.';
}

function issueAssignmentHint(issue: SupportIssue): string {
    return (
        textFrom(issue.metadata?.assignmentHint ?? issue.metadata?.assignment_hint)
        || (issueAssignmentRequired(issue)
            ? 'Configure a channel or queue default assignee, or approve an automation assignment.'
            : '')
    );
}

function issueNeedsResponse(issue: SupportIssue): boolean {
    if (issue.workflowStatus === 'done' || issue.status === 'done') return false;
    if (issue.needsResponse) return true;
    return issue.latestMessageDirection === 'customer' || issue.latestMessageDirection === 'visitor';
}

function knowledgeGapIsOpen(gap: KnowledgeGap): boolean {
    const status = textFrom(gap.status).toLowerCase();
    return !['closed', 'dismissed', 'resolved'].includes(status);
}

function issueHasOpenKnowledgeGap(issue: SupportIssue): boolean {
    return (issue.knowledgeGaps ?? []).some(knowledgeGapIsOpen);
}

function needsResponseLabel(issue: SupportIssue): string {
    return issue.latestCustomerMessageAt ? `Needs response ${formatTime(issue.latestCustomerMessageAt)}` : 'Needs response';
}

type TicketNextActionKind =
    | 'failed_delivery'
    | 'reply_approval'
    | 'action_approval'
    | 'assign_owner'
    | 'overdue_sla'
    | 'reply_needed'
    | 'due_soon_sla'
    | 'pending_delivery'
    | 'ready_to_close'
    | 'clear';

interface TicketNextAction {
    kind: TicketNextActionKind;
    title: string;
    detail: string;
    badge: string;
    variant: 'outline' | 'secondary' | 'destructive';
}

function ticketNextAction(issue: SupportIssue): TicketNextAction {
    const replyDrafts = pendingReplyApprovalCount(issue);
    const actionProposals = pendingActionApprovalCount(issue);
    if (issueHasFailedDelivery(issue)) {
        return {
            kind: 'failed_delivery',
            title: 'Fix failed delivery',
            detail: failedDeliveryLabel(issue),
            badge: 'Delivery',
            variant: 'destructive',
        };
    }
    if (replyDrafts > 0) {
        return {
            kind: 'reply_approval',
            title: 'Review reply draft',
            detail: replyDrafts === 1 ? '1 reply draft waits for approval.' : `${replyDrafts} reply drafts wait for approval.`,
            badge: 'Human loop',
            variant: 'secondary',
        };
    }
    if (actionProposals > 0) {
        return {
            kind: 'action_approval',
            title: 'Review action proposal',
            detail: actionProposals === 1 ? '1 action proposal waits for approval.' : `${actionProposals} action proposals wait for approval.`,
            badge: 'Human loop',
            variant: 'secondary',
        };
    }
    if (issueNeedsAssignee(issue)) {
        return {
            kind: 'assign_owner',
            title: 'Assign owner',
            detail: issueAssignmentDetail(issue),
            badge: 'Ownership',
            variant: 'outline',
        };
    }
    if (issueHasOverdueSla(issue)) {
        return {
            kind: 'overdue_sla',
            title: 'Handle overdue SLA',
            detail: slaBadgeLabel(issue) || 'SLA target is overdue.',
            badge: 'SLA',
            variant: 'destructive',
        };
    }
    if (issueNeedsResponse(issue)) {
        return {
            kind: 'reply_needed',
            title: 'Reply to customer',
            detail: needsResponseLabel(issue),
            badge: 'Response',
            variant: 'secondary',
        };
    }
    if (issueHasDueSoonSla(issue)) {
        return {
            kind: 'due_soon_sla',
            title: 'Watch SLA',
            detail: slaBadgeLabel(issue),
            badge: 'SLA',
            variant: 'outline',
        };
    }
    if (issueHasPendingDelivery(issue)) {
        return {
            kind: 'pending_delivery',
            title: 'Monitor queued reply',
            detail: pendingDeliveryLabel(issue),
            badge: 'Delivery',
            variant: 'outline',
        };
    }
    if (issueWorkflowStatus(issue) !== 'done' && issueDoneBlockers(issue).length === 0) {
        return {
            kind: 'ready_to_close',
            title: 'Ready to close',
            detail: 'No open approval, delivery, or SLA blocker detected.',
            badge: 'Lifecycle',
            variant: 'outline',
        };
    }
    return {
        kind: 'clear',
        title: 'No immediate action',
        detail: 'Ticket is clear for now.',
        badge: 'Clear',
        variant: 'outline',
    };
}

function slaEventLabel(eventType: string) {
    if (eventType === 'first_response_due') return 'First response';
    if (eventType === 'resolution_due') return 'Resolution';
    return eventType || 'SLA';
}

function slaEventIsOverdue(event: SupportSlaEvent): boolean {
    if (event.status !== 'pending' || !event.targetAt) return false;
    const targetMs = Date.parse(event.targetAt);
    return Number.isFinite(targetMs) && targetMs < Date.now();
}

function issueHasOverdueSla(issue: SupportIssue): boolean {
    return issue.hasOverdueSla || (issue.slaEvents ?? []).some(slaEventIsOverdue);
}

function issueHasDueSoonSla(issue: SupportIssue): boolean {
    if (issueHasOverdueSla(issue) || !issue.nextSlaTargetAt) return false;
    const targetMs = Date.parse(issue.nextSlaTargetAt);
    if (!Number.isFinite(targetMs)) return false;
    const now = Date.now();
    return targetMs >= now && targetMs <= now + SLA_DUE_SOON_WINDOW_MS;
}

function issueHasLowCsat(issue: SupportIssue): boolean {
    const lowCsatFeedbackCount = explicitCount(issue.lowCsatFeedbackCount);
    if (lowCsatFeedbackCount !== null) return lowCsatFeedbackCount > 0;
    if (issue.hasLowCsatFeedback) return true;
    if ((issue.latestCsatRating ?? 0) > 0 && issue.latestCsatRating <= 2) return true;
    return (issue.csatFeedback ?? []).some(feedback => feedback.rating > 0 && feedback.rating <= 2);
}

function issueMatchesInboxStatus(issue: SupportIssue, statusFilter: InboxStatusFilter): boolean {
    if (statusFilter === 'all') return true;
    if (statusFilter === 'needs-response') return issueNeedsResponse(issue);
    if (statusFilter === 'approvals') return issueNeedsApproval(issue);
    if (statusFilter === 'reply-approvals') return pendingReplyApprovalCount(issue) > 0;
    if (statusFilter === 'action-approvals') return pendingActionApprovalCount(issue) > 0;
    if (statusFilter === 'unassigned') return issueNeedsAssignee(issue);
    if (statusFilter === 'failed-delivery') return issueHasFailedDelivery(issue);
    if (statusFilter === 'low-csat') return issueHasLowCsat(issue);
    if (statusFilter === 'due-soon-sla') return issueHasDueSoonSla(issue);
    if (statusFilter === 'overdue-sla') return issueHasOverdueSla(issue);
    return issueWorkflowStatus(issue) === statusFilter;
}

function lowCsatLabel(issue: SupportIssue) {
    const count = explicitCount(issue.lowCsatFeedbackCount)
        ?? (issue.csatFeedback ?? []).filter(feedback => feedback.rating > 0 && feedback.rating <= 2).length;
    return count > 1 ? `Low CSAT ${count}` : 'Low CSAT';
}

function nextSlaLabel(issue: SupportIssue) {
    if (!issue.nextSlaTargetAt) return '';
    return `${slaEventLabel(issue.nextSlaEventType)} ${formatTime(issue.nextSlaTargetAt)}`;
}

function slaBadgeLabel(issue: SupportIssue) {
    if (!issue.nextSlaTargetAt) return '';
    const label = slaEventLabel(issue.nextSlaEventType);
    return issueHasOverdueSla(issue)
        ? `${label} overdue ${formatTime(issue.nextSlaTargetAt)}`
        : `${label} due ${formatTime(issue.nextSlaTargetAt)}`;
}

function slaWorkTag(mode: 'overdue' | 'due-soon') {
    return mode === 'overdue' ? 'sla-overdue-watch' : 'sla-due-soon-watch';
}

function slaWorkPriority(issue: SupportIssue, mode: 'overdue' | 'due-soon'): SupportIssuePriority {
    if (mode === 'overdue') return 'urgent';
    return issue.priority === 'urgent' ? 'urgent' : 'high';
}

function slaWorkNoteBody(mode: 'overdue' | 'due-soon', scope: 'single' | 'bulk') {
    if (mode === 'overdue') {
        return scope === 'bulk'
            ? 'Bulk SLA escalation started from Inbox. Confirm owner, reply path, and resolution plan.'
            : 'SLA escalation started from Inbox next action. Confirm owner, reply path, and resolution plan.';
    }
    return scope === 'bulk'
        ? 'Bulk SLA watch started from Inbox. Confirm next owner action before each SLA target.'
        : 'SLA watch started from Inbox next action. Confirm next owner action before the SLA target.';
}

function slaWorkSource(mode: 'overdue' | 'due-soon', scope: 'single' | 'bulk') {
    const suffix = mode === 'overdue' ? 'overdue_sla' : 'due_soon_sla';
    return `inbox_${scope === 'bulk' ? 'bulk' : 'next_action'}_${suffix}`;
}

function IssueListItem({
    issue,
    active,
    selected,
    canClaim,
    claiming,
    onSelect,
    onSelectionChange,
    onClaim,
}: {
    issue: SupportIssue;
    active: boolean;
    selected: boolean;
    canClaim: boolean;
    claiming: boolean;
    onSelect: () => void;
    onSelectionChange: (selected: boolean) => void;
    onClaim: () => void;
}) {
    return (
        <div
            role="button"
            tabIndex={0}
            onClick={onSelect}
            onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    onSelect();
                }
            }}
            className={[
                'w-full cursor-pointer border-b px-4 py-3 text-left transition-colors',
                active ? 'bg-muted/60' : 'bg-background hover:bg-muted/40',
            ].join(' ')}
        >
            <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                    <Checkbox
                        checked={selected}
                        aria-label={`Select ${issue.subject || 'ticket'}`}
                        onClick={event => event.stopPropagation()}
                        onKeyDown={event => event.stopPropagation()}
                        onCheckedChange={checked => onSelectionChange(checked === true)}
                    />
                    <div className="min-w-0 truncate text-sm font-medium">
                        {issue.subject || '(No subject)'}
                    </div>
                </div>
                <span className="shrink-0 text-xs text-muted-foreground">{formatTime(issue.latestMessageAt)}</span>
            </div>
            <div className="mb-2 flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
                <Mail className="size-3.5 shrink-0" />
                <span className="truncate">{issue.accountName || issue.contactEmail || issue.fromAddress || '-'}</span>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
                <Badge variant="outline" className="gap-1 font-normal">
                    {statusIcon(issue.status)}
                    {workflowLabel(issue.status)}
                </Badge>
                <Badge variant={priorityVariant(issue.priority)} className="font-normal">
                    {issue.priority}
                </Badge>
                <Badge variant="secondary" className="font-normal">
                    {issueQueueLabel(issue)}
                </Badge>
                {(issue.tags ?? []).slice(0, 3).map(tag => (
                    <Badge key={tag} variant="outline" className="font-normal">
                        {tag}
                    </Badge>
                ))}
                {issueNeedsApproval(issue) && (
                    <Badge variant="secondary" className="font-normal">
                        {approvalLabel(issue)}
                    </Badge>
                )}
                {issueNeedsResponse(issue) && (
                    <Badge variant="secondary" className="font-normal">
                        {needsResponseLabel(issue)}
                    </Badge>
                )}
                {issueHasPendingDelivery(issue) && (
                    <Badge variant="secondary" className="font-normal">
                        {pendingDeliveryLabel(issue)}
                    </Badge>
                )}
                {issueHasFailedDelivery(issue) && (
                    <Badge variant="destructive" className="font-normal">
                        {failedDeliveryLabel(issue)}
                    </Badge>
                )}
                {issueHasLowCsat(issue) && (
                    <Badge variant="destructive" className="font-normal" title={issue.latestCsatComment || undefined}>
                        {lowCsatLabel(issue)}
                    </Badge>
                )}
                {slaBadgeLabel(issue) && (
                    <Badge
                        variant={issueHasOverdueSla(issue) ? 'destructive' : 'outline'}
                        className="font-normal"
                        title={nextSlaLabel(issue) || undefined}
                    >
                        {slaBadgeLabel(issue)}
                    </Badge>
                )}
                {(issue.duplicateSuggestionCount ?? 0) > 0 && (
                    <Badge variant="secondary" className="font-normal" title={duplicateSummaryTitle(issue)}>
                        {duplicateScoreLabel(issue.topDuplicateScore)} duplicate
                    </Badge>
                )}
                {issueNeedsAssignee(issue) && (
                    <div className="flex items-center gap-1.5">
                        <Badge variant="outline" className="font-normal" title={issueAssignmentDetail(issue)}>
                            {issueAssignmentBadge(issue)}
                        </Badge>
                        {canClaim && (
                            <Button
                                type="button"
                                size="sm"
                                variant="ghost"
                                className="h-6 px-2 text-xs"
                                disabled={claiming}
                                onClick={(event) => {
                                    event.stopPropagation();
                                    onClaim();
                                }}
                            >
                                {claiming && <Loader className="mr-1 size-3 animate-spin" />}
                                Claim
                            </Button>
                        )}
                    </div>
                )}
                {issue.activatedIntent && (
                    <Badge variant="secondary" className="max-w-[10rem] truncate font-normal">
                        {issue.activatedIntent}
                    </Badge>
                )}
            </div>
            {issueNeedsApproval(issue) && (
                <div className="mt-2 flex min-w-0 items-center gap-2 rounded-md border bg-muted/30 px-2 py-1.5 text-xs">
                    <CheckCircle2 className="size-3.5 shrink-0 text-muted-foreground" />
                    <span className="shrink-0 font-medium">Review package</span>
                    <span className="min-w-0 truncate text-muted-foreground">{reviewPackageSummary(issue)}</span>
                </div>
            )}
        </div>
    );
}

function ApprovalQueueCard({
    issue,
    active,
    selected,
    t,
    onOpen,
    onSelectionChange,
}: ApprovalQueueCardProps) {
    const replyCount = pendingReplyApprovalCount(issue);
    const actionCount = pendingActionApprovalCount(issue);
    const preview = approvalPreviewText(issue);
    const customer = issue.accountName || issue.contactEmail || issue.fromAddress || '-';

    return (
        <div
            role="button"
            tabIndex={0}
            data-approval-review-card
            onClick={onOpen}
            onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    onOpen();
                }
            }}
            className={[
                'rounded-md border bg-background p-2 text-left transition-colors',
                active ? 'border-primary bg-primary/5' : 'hover:bg-muted/50',
            ].join(' ')}
        >
            <div className="flex min-w-0 items-start gap-2">
                <Checkbox
                    checked={selected}
                    aria-label={`${t('Select')} ${issue.subject || t('ticket')}`}
                    className="mt-0.5"
                    onClick={event => event.stopPropagation()}
                    onKeyDown={event => event.stopPropagation()}
                    onCheckedChange={checked => onSelectionChange(checked === true)}
                />
                <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-start justify-between gap-2">
                        <div className="min-w-0">
                            <div className="truncate text-sm font-medium">{issue.subject || t('(No subject)')}</div>
                            <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
                                <Mail className="size-3.5 shrink-0" />
                                <span className="truncate">{customer}</span>
                            </div>
                        </div>
                        <span className="shrink-0 text-[11px] text-muted-foreground">{formatTime(issue.latestMessageAt)}</span>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                        {replyCount > 0 && (
                            <Badge variant="secondary" className="font-normal">
                                {replyCount} {t(replyCount === 1 ? 'reply draft' : 'reply drafts')}
                            </Badge>
                        )}
                        {actionCount > 0 && (
                            <Badge variant="secondary" className="font-normal">
                                {actionCount} {t(actionCount === 1 ? 'action proposal' : 'action proposals')}
                            </Badge>
                        )}
                        <Badge variant={priorityVariant(issue.priority)} className="font-normal">
                            {issue.priority}
                        </Badge>
                        <Badge variant="outline" className="max-w-32 truncate font-normal">
                            {issue.assigneeEmail || t('Unassigned')}
                        </Badge>
                    </div>
                    <div className="mt-2 min-w-0 rounded border bg-muted/20 px-2 py-1.5">
                        <div className="truncate text-[11px] font-medium text-muted-foreground">
                            {reviewPackageSummary(issue) || approvalLabel(issue)}
                        </div>
                        <div className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
                            {preview || t('Open ticket to review prepared work.')}
                        </div>
                    </div>
                    <div className="mt-2 flex items-center justify-between gap-2">
                        <div className="min-w-0 truncate text-[11px] text-muted-foreground">
                            {issueChannelLabel(issue)} · {workflowLabel(issueWorkflowStatus(issue))}
                        </div>
                        <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            data-approval-review-open
                            className="h-6 shrink-0 px-2 text-xs"
                            onClick={(event) => {
                                event.stopPropagation();
                                onOpen();
                            }}
                        >
                            <ExternalLink className="size-3" />
                            {t('Open review')}
                        </Button>
                    </div>
                </div>
            </div>
        </div>
    );
}

function IssueBoardCard({
    issue,
    active,
    selected,
    selectedGroupCount,
    moving,
    canClaim,
    claiming,
    doneBlockers,
    onOpen,
    onSelectionChange,
    onClaim,
    onMove,
    onDragStart,
    onDragEnd,
}: {
    issue: SupportIssue;
    active: boolean;
    selected: boolean;
    selectedGroupCount: number;
    moving: boolean;
    canClaim: boolean;
    claiming: boolean;
    doneBlockers: string[];
    onOpen: () => void;
    onSelectionChange: (selected: boolean) => void;
    onClaim: () => void;
    onMove: (status: WorkflowLane) => void;
    onDragStart: (event: DragEvent<HTMLDivElement>) => void;
    onDragEnd: () => void;
}) {
    const workflowStatus = issueWorkflowStatus(issue);
    const moveTargets = kanbanLanes.filter(lane => lane.value !== workflowStatus);
    const doneBlocked = doneBlockers.length > 0;
    const ticketState = issue.ticketState ?? null;
    const stateCounts = ticketState?.counts ?? null;
    const channelLifecycle = ticketState?.channelLifecycle ?? null;
    const cardNextAction = ticketNextAction(issue);

    return (
        <div
            role="button"
            tabIndex={moving ? -1 : 0}
            data-kanban-card={issue.id}
            data-kanban-card-status={workflowStatus}
            data-kanban-card-subject={issue.subject || ''}
            data-kanban-card-ticket-state={ticketState?.kind ?? ''}
            data-kanban-card-next-action={ticketState?.nextActionKind ?? ''}
            data-kanban-card-agent-prepared={ticketState ? String(ticketState.agentPrepared) : ''}
            data-kanban-card-human-loop={ticketState ? String(ticketState.humanLoopRequired) : ''}
            data-kanban-card-knowledge-covered={ticketState ? String(ticketState.knowledgeCovered) : ''}
            data-kanban-card-channel-lifecycle={channelLifecycle?.kind ?? ''}
            data-kanban-card-channel-ready={channelLifecycle ? String(channelLifecycle.ready) : ''}
            data-kanban-card-channel={channelLifecycle?.channel ?? issue.channel ?? ''}
            draggable={!moving}
            aria-disabled={moving}
            onClick={() => {
                if (!moving) onOpen();
            }}
            onKeyDown={(event) => {
                if (!moving && (event.key === 'Enter' || event.key === ' ')) {
                    event.preventDefault();
                    onOpen();
                }
            }}
            onDragStart={(event) => {
                if (moving) {
                    event.preventDefault();
                    return;
                }
                onDragStart(event);
            }}
            onDragEnd={onDragEnd}
            className={[
                'w-full rounded-md border bg-background p-3 text-left shadow-xs transition-colors',
                moving ? 'cursor-wait opacity-60' : 'cursor-grab active:cursor-grabbing',
                active ? 'border-primary bg-primary/5' : 'hover:bg-muted/50',
            ].join(' ')}
        >
            <div className="mb-2 flex min-w-0 items-start justify-between gap-2">
                <div className="flex min-w-0 items-start gap-2">
                    <Checkbox
                        checked={selected}
                        aria-label={`Select ${issue.subject || 'ticket'}`}
                        className="mt-0.5"
                        draggable={false}
                        onClick={event => event.stopPropagation()}
                        onKeyDown={event => event.stopPropagation()}
                        onCheckedChange={checked => onSelectionChange(checked === true)}
                    />
                    <div className="min-w-0 truncate text-sm font-medium">{issue.subject || '(No subject)'}</div>
                </div>
                <Badge variant={priorityVariant(issue.priority)} className="shrink-0 font-normal">
                    {issue.priority}
                </Badge>
            </div>
            <Badge variant="secondary" className="mb-2 font-normal">
                {issueQueueLabel(issue)}
            </Badge>
            {(issue.tags ?? []).slice(0, 3).map(tag => (
                <Badge key={tag} variant="outline" className="mb-2 mr-1 font-normal">
                    {tag}
                </Badge>
            ))}
            {issueNeedsApproval(issue) && (
                <Badge variant="secondary" className="mb-2 font-normal">
                    {approvalLabel(issue)}
                </Badge>
            )}
            {issueNeedsResponse(issue) && (
                <Badge variant="secondary" className="mb-2 font-normal">
                    {needsResponseLabel(issue)}
                </Badge>
            )}
            {issueHasPendingDelivery(issue) && (
                <Badge variant="secondary" className="mb-2 font-normal">
                    {pendingDeliveryLabel(issue)}
                </Badge>
            )}
            {issueHasFailedDelivery(issue) && (
                <Badge variant="destructive" className="mb-2 font-normal">
                    {failedDeliveryLabel(issue)}
                </Badge>
            )}
            {issueHasLowCsat(issue) && (
                <Badge variant="destructive" className="mb-2 font-normal" title={issue.latestCsatComment || undefined}>
                    {lowCsatLabel(issue)}
                </Badge>
            )}
            {slaBadgeLabel(issue) && (
                <Badge
                    variant={issueHasOverdueSla(issue) ? 'destructive' : 'outline'}
                    className="mb-2 font-normal"
                    title={nextSlaLabel(issue) || undefined}
                >
                    {slaBadgeLabel(issue)}
                </Badge>
            )}
            {(issue.duplicateSuggestionCount ?? 0) > 0 && (
                <Badge variant="secondary" className="mb-2 font-normal" title={duplicateSummaryTitle(issue)}>
                    {duplicateScoreLabel(issue.topDuplicateScore)} duplicate
                </Badge>
            )}
            {doneBlocked && (
                <Badge variant="destructive" className="mb-2 font-normal" title={doneBlockers.join(', ')}>
                    Close blocked
                </Badge>
            )}
            {issueNeedsAssignee(issue) && (
                <div className="mb-2 flex flex-wrap items-center gap-1.5">
                    <Badge variant="outline" className="font-normal" title={issueAssignmentDetail(issue)}>
                        {issueAssignmentBadge(issue)}
                    </Badge>
                    {canClaim && (
                        <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            className="h-6 px-2 text-xs"
                            disabled={claiming}
                            onClick={(event) => {
                                event.stopPropagation();
                                onClaim();
                            }}
                        >
                            {claiming && <Loader className="mr-1 size-3 animate-spin" />}
                            Claim
                        </Button>
                    )}
                </div>
            )}
            <div className="space-y-1 text-xs text-muted-foreground">
                <div className="truncate">{issue.accountName || issue.contactEmail || issue.fromAddress || '-'}</div>
                <div className="flex items-center justify-between gap-2">
                    <span className="truncate">{issue.assigneeEmail || 'Unassigned'}</span>
                    <span className="shrink-0">{formatTime(issue.latestMessageAt)}</span>
                </div>
            </div>
            {(issue.activatedIntent || issue.channel) && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                    {issue.activatedIntent && (
                        <Badge variant="secondary" className="max-w-full truncate font-normal">
                            {issue.activatedIntent}
                        </Badge>
                    )}
                    {issue.channel && (
                        <Badge variant="outline" className="font-normal">
                            {issue.channel}
                        </Badge>
                    )}
                </div>
            )}
            {ticketState && (
                <div
                    className="mt-3 rounded-md border bg-muted/20 p-2 text-xs"
                    data-ticket-list-state={ticketState.kind}
                    data-ticket-list-state-action={ticketState.nextActionKind}
                    data-ticket-list-state-agent-prepared={String(ticketState.agentPrepared)}
                    data-ticket-list-state-human-loop={String(ticketState.humanLoopRequired)}
                    data-ticket-list-state-knowledge-covered={String(ticketState.knowledgeCovered)}
                    data-ticket-list-state-agent-runs={stateCounts?.agentRuns ?? 0}
                    data-ticket-list-state-drafts={stateCounts?.replyDrafts ?? 0}
                    data-ticket-list-state-gaps={stateCounts?.openKnowledgeGaps ?? 0}
                    data-ticket-list-state-channel={channelLifecycle?.channel ?? ''}
                    data-ticket-list-state-channel-ready={channelLifecycle ? String(channelLifecycle.ready) : ''}
                    data-ticket-list-state-channel-source={channelLifecycle?.channelKey || channelLifecycle?.source || ''}
                    data-ticket-list-state-reply-targeted={channelLifecycle ? String(channelLifecycle.replyTargeted) : ''}
                >
                    <div className="mb-1.5 flex min-w-0 items-center justify-between gap-2">
                        <div className="flex min-w-0 items-center gap-1.5 font-medium">
                            <Sparkles className="size-3.5 shrink-0 text-muted-foreground" />
                            <span className="truncate">{ticketState.label}</span>
                        </div>
                        <Badge variant={cardNextAction.variant} className="shrink-0 font-normal">
                            {cardNextAction.badge}
                        </Badge>
                    </div>
                    <div className="line-clamp-2 text-muted-foreground" title={ticketState.detail}>
                        {ticketState.detail}
                    </div>
                    {channelLifecycle && (
                        <div
                            className="mt-2 rounded border bg-background px-2 py-1.5"
                            data-ticket-channel-lifecycle={channelLifecycle.kind}
                            data-ticket-channel-lifecycle-ready={String(channelLifecycle.ready)}
                            data-ticket-channel-lifecycle-channel={channelLifecycle.channel}
                            data-ticket-channel-lifecycle-source={channelLifecycle.channelKey || channelLifecycle.source}
                            data-ticket-channel-lifecycle-target={channelLifecycle.replyTarget.label}
                        >
                            <div className="mb-1 flex min-w-0 items-center justify-between gap-2">
                                <div className="flex min-w-0 items-center gap-1.5 font-medium">
                                    <Link className="size-3.5 shrink-0 text-muted-foreground" />
                                    <span className="truncate">{channelLifecycle.label}</span>
                                </div>
                                <Badge variant={channelLifecycle.ready ? 'secondary' : 'destructive'} className="shrink-0 font-normal">
                                    {channelLifecycle.ready ? 'routable' : 'blocked'}
                                </Badge>
                            </div>
                            <div className="line-clamp-2 text-muted-foreground" title={channelLifecycle.detail}>
                                {channelLifecycle.detail}
                            </div>
                        </div>
                    )}
                    <div className="mt-2 flex flex-wrap gap-1.5">
                        {ticketState.agentPrepared && (
                            <Badge variant="secondary" className="font-normal">
                                <Sparkles className="size-3" />
                                {stateCounts?.agentRuns ?? 0}
                            </Badge>
                        )}
                        {(stateCounts?.replyDrafts ?? 0) > 0 && (
                            <Badge variant="secondary" className="font-normal">
                                <Send className="size-3" />
                                {stateCounts?.replyDrafts ?? 0}
                            </Badge>
                        )}
                        {(stateCounts?.openKnowledgeGaps ?? 0) > 0 ? (
                            <Badge variant="destructive" className="font-normal">
                                <AlertCircle className="size-3" />
                                {stateCounts?.openKnowledgeGaps ?? 0}
                            </Badge>
                        ) : (
                            <Badge variant="outline" className="font-normal">
                                <BookOpen className="size-3" />
                                KB
                            </Badge>
                        )}
                    </div>
                </div>
            )}
            {issueNeedsApproval(issue) && (
                <div className="mt-3 rounded-md border bg-muted/30 p-2 text-xs">
                    <div className="mb-1 flex items-center gap-1.5 font-medium">
                        <CheckCircle2 className="size-3.5 text-muted-foreground" />
                        Review package
                    </div>
                    <div className="line-clamp-2 text-muted-foreground">
                        {reviewPackageSummary(issue)}
                    </div>
                </div>
            )}
            <div className="mt-3 border-t pt-2">
                <div className="mb-1.5 text-[11px] font-medium uppercase text-muted-foreground">
                    Move to
                </div>
                <div className="flex flex-wrap gap-1.5">
                    {selectedGroupCount > 1 && (
                        <Badge variant="secondary" className="h-7 font-normal">
                            Moves {selectedGroupCount}
                        </Badge>
                    )}
                    {moveTargets.map(lane => (
                        <Button
                            key={lane.value}
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-xs"
                            disabled={moving || (lane.value === 'done' && doneBlocked)}
                            draggable={false}
                            title={lane.value === 'done' && doneBlocked ? `Resolve first: ${doneBlockers.join(', ')}` : undefined}
                            aria-label={`Move ${issue.subject || 'ticket'} to ${lane.label}`}
                            onClick={(event) => {
                                event.stopPropagation();
                                onMove(lane.value);
                            }}
                        >
                            {lane.label}
                        </Button>
                    ))}
                </div>
            </div>
        </div>
    );
}

function ActivityEventCard({ event, compact = false, t }: { event: SupportIssueActivityEvent; compact?: boolean; t: TranslateFn }) {
    const workflowProof = isWorkflowProofEvent(event);
    const title = activityEventTitle(event);
    const changeText = activityEventChangeText(event);

    return (
        <div className="rounded-md border bg-muted/20 p-2 text-sm" data-activity-event={event.id || event.eventType}>
            <div className="flex min-w-0 items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-1.5">
                    <span className="min-w-0 truncate">{t(title)}</span>
                    {workflowProof && (
                        <Badge variant="secondary" className="shrink-0 font-normal">
                            {t('Workflow')}
                        </Badge>
                    )}
                </div>
                <span className="shrink-0 text-xs text-muted-foreground">{formatTime(event.occurredAt)}</span>
            </div>
            {event.actorEmail && (
                <div className="mt-1 truncate text-xs text-muted-foreground">{event.actorEmail}</div>
            )}
            {changeText && (
                <div className="mt-1 truncate text-xs text-muted-foreground">{changeText}</div>
            )}
            {event.body && (
                <div className={`mt-1 text-xs text-muted-foreground ${compact ? 'line-clamp-2' : 'whitespace-pre-wrap'}`}>
                    {event.body}
                </div>
            )}
        </div>
    );
}

function ActionExecutionCard({
    execution,
    compact = false,
    t,
    approvingActionExecutionId,
    rejectingActionExecutionId,
    onApprove,
    onReject,
}: {
    execution: SupportActionExecution;
    compact?: boolean;
    t: TranslateFn;
    approvingActionExecutionId: string;
    rejectingActionExecutionId: string;
    onApprove: (execution: SupportActionExecution) => void | Promise<void>;
    onReject: (execution: SupportActionExecution) => void | Promise<void>;
}) {
    const needsApproval = actionExecutionNeedsApproval(execution);
    const detail = actionExecutionDetail(execution);
    const review = actionExecutionReviewState(execution);
    const showReviewBadge = review.status === 'approved' || review.status === 'rejected' || needsApproval;
    const reviewBadgeLabel = review.status === 'approved'
        ? t('Approved')
        : review.status === 'rejected'
            ? t('Rejected')
            : t('Approval required');
    const reviewLineLabel = review.status === 'approved'
        ? t('Approved by')
        : review.status === 'rejected'
            ? t('Rejected by')
            : '';
    const busy = Boolean(approvingActionExecutionId || rejectingActionExecutionId);
    const textClamp = compact ? 'line-clamp-2' : 'whitespace-pre-wrap';
    const iconSize = compact ? 'size-3' : 'size-4';

    return (
        <div className="rounded-md border bg-muted/20 p-2 text-sm">
            <div className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate">{execution.label}</span>
                <div className="flex shrink-0 items-center gap-1.5">
                    {showReviewBadge && (
                        <Badge
                            variant={review.status === 'rejected' ? 'destructive' : 'secondary'}
                            className="font-normal"
                        >
                            {reviewBadgeLabel}
                        </Badge>
                    )}
                    <Badge variant="outline" className="font-normal">{t(execution.status)}</Badge>
                </div>
            </div>
            {detail && (
                <div className={`mt-1 text-xs text-muted-foreground ${textClamp}`}>
                    {detail}
                </div>
            )}
            <div className="mt-1 truncate text-xs text-muted-foreground">
                {execution.requestedBy || '-'} · {formatTime(execution.completedAt || execution.startedAt || execution.created)}
            </div>
            {reviewLineLabel && (review.actor || review.at) && (
                <div className="mt-1 truncate text-xs text-muted-foreground">
                    {reviewLineLabel} {review.actor || '-'}{review.at ? ` · ${formatTime(review.at)}` : ''}
                </div>
            )}
            {review.note && (
                <div className="mt-2 rounded-md border bg-background/70 p-2 text-xs">
                    <div className="font-medium text-foreground">{t('Reviewer note')}</div>
                    <div className={`mt-1 text-muted-foreground ${textClamp}`}>
                        {review.note}
                    </div>
                </div>
            )}
            {needsApproval && (
                <div className={`mt-2 flex justify-end ${compact ? 'gap-1.5' : 'gap-2'}`}>
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className={compact ? 'h-7 px-2 text-xs' : undefined}
                        onClick={() => void onReject(execution)}
                        disabled={busy}
                    >
                        {rejectingActionExecutionId === execution.id ? <Loader className={`${iconSize} animate-spin`} /> : <X className={iconSize} />}
                        {t('Reject')}
                    </Button>
                    <Button
                        type="button"
                        size="sm"
                        className={compact ? 'h-7 px-2 text-xs' : undefined}
                        onClick={() => void onApprove(execution)}
                        disabled={busy}
                    >
                        {approvingActionExecutionId === execution.id ? <Loader className={`${iconSize} animate-spin`} /> : <CheckCircle2 className={iconSize} />}
                        {t('Approve')}
                    </Button>
                </div>
            )}
        </div>
    );
}

function EmptyState({ label }: { label: string }) {
    return (
        <div className="flex h-full min-h-64 flex-col items-center justify-center text-center text-muted-foreground">
            <InboxIcon className="mb-3 size-9" />
            <div className="text-sm">{label}</div>
        </div>
    );
}

function replyReadinessBlockDetail(readiness: SupportReplyReadiness | null, t: TranslateFn): string {
    if (!readiness || readiness.ready) return '';
    const parts = [
        ...readiness.blockers.map(item => item.split('_').join(' ')),
        ...readiness.missingEnvVars.map(item => `${t('Missing env')}: ${item}`),
    ].filter(Boolean);
    return parts.length > 0 ? parts.join(' | ') : t('Reply channel is blocked');
}

function replyReadinessRouteLabel(readiness: SupportReplyReadiness | null): string {
    if (!readiness) return '';
    return [readiness.provider, readiness.transport, readiness.channelKey].filter(Boolean).join(' / ');
}

function replyReadinessFixAction(readiness: SupportReplyReadiness | null): string {
    if (!readiness) return 'inspect_reply_route';
    if (readiness.missingEnvVars.length > 0) return 'missing_env';
    if (readiness.adapter?.requiresChannelConfig && !readiness.adapter.channelConfigured) return 'channel_config';
    return readiness.blockers[0] || 'reply_readiness';
}

function replyAdapterTransportLabel(value: string): string {
    if (value === 'provider_api') return 'Provider API';
    if (value === 'webhook') return 'Webhook adapter';
    if (value === 'smtp') return 'SMTP';
    if (value === 'internal') return 'Internal';
    return value || 'Unknown';
}

function replyReadinessTargetRows(readiness: SupportReplyReadiness | null): ChannelSourceDetail[] {
    if (!readiness) return [];
    const target = readiness.target ?? {};
    return [
        { label: 'Target', value: textFrom(target.label) || textFrom(target.value) },
        { label: 'Address', value: textFrom(target.address) || textFrom(target.email) },
        { label: 'Channel ID', value: textFrom(target.channelId) || textFrom(target.channel_id) || textFrom(target.chatId) || textFrom(target.chat_id) },
        { label: 'Thread', value: textFrom(target.threadId) || textFrom(target.thread_id) || textFrom(target.threadTs) || textFrom(target.thread_ts) },
        { label: 'Conversation', value: textFrom(target.conversationId) || textFrom(target.conversation_id) },
        { label: 'Reply to', value: textFrom(target.replyToId) || textFrom(target.reply_to_id) },
        { label: 'Service URL', value: textFrom(target.serviceUrl) || textFrom(target.service_url) },
    ].filter(row => row.value.trim());
}

export function Inbox({ projectId }: InboxProps) {
    const { tenantId, issueId } = useParams<{ tenantId: string; issueId?: string }>();
    const navigate = useNavigate();
    const location = useLocation();
    const { t } = useI18n();
    const initialInboxFilters = inboxFiltersFromSearch(location.search);
    const [viewMode, setViewMode] = useState<InboxView>(initialInboxFilters.viewMode);
    const [statusFilter, setStatusFilter] = useState<InboxStatusFilter>(initialInboxFilters.statusFilter);
    const [queueFilter, setQueueFilter] = useState(initialInboxFilters.queueFilter);
    const [accountFilter, setAccountFilter] = useState(initialInboxFilters.accountFilter);
    const [channelFilter, setChannelFilter] = useState(initialInboxFilters.channelFilter);
    const [assigneeFilter, setAssigneeFilter] = useState(initialInboxFilters.assigneeFilter);
    const [tagFilter, setTagFilter] = useState(initialInboxFilters.tagFilter);
    const [query, setQuery] = useState(initialInboxFilters.query);
    const [issues, setIssues] = useState<SupportIssue[]>([]);
    const [supportQueues, setSupportQueues] = useState<SupportQueue[]>([]);
    const [inboxViews, setInboxViews] = useState<SupportInboxView[]>([]);
    const [replyMacros, setReplyMacros] = useState<SupportReplyMacro[]>([]);
    const [channelActivationBacklog, setChannelActivationBacklog] = useState<SupportChannelActivationBacklog | null>(null);
    const [loadingChannelCoverage, setLoadingChannelCoverage] = useState(false);
    const [supportAnalytics, setSupportAnalytics] = useState<SupportAnalytics | null>(null);
    const [loadingSupportAnalytics, setLoadingSupportAnalytics] = useState(false);
    const [selectedIssue, setSelectedIssue] = useState<SupportIssue | null>(null);
    const [issueBoard, setIssueBoard] = useState<SupportIssueBoard | null>(null);
    const [answerWorkspace, setAnswerWorkspace] = useState<SupportIssueAnswerWorkspace | null>(null);
    const [ticketAccount, setTicketAccount] = useState<SupportAccount | null>(null);
    const [loadingList, setLoadingList] = useState(false);
    const [loadingViews, setLoadingViews] = useState(false);
    const [loadingReplyMacros, setLoadingReplyMacros] = useState(false);
    const [loadingDetail, setLoadingDetail] = useState(false);
    const [loadingTicketAccount, setLoadingTicketAccount] = useState(false);
    const [projectMembers, setProjectMembers] = useState<ProjectMember[]>([]);
    const [knowledgeArticles, setKnowledgeArticles] = useState<KnowledgeArticle[]>([]);
    const [loadingKnowledge, setLoadingKnowledge] = useState(false);
    const [knowledgeQuery, setKnowledgeQuery] = useState('');
    const [currentUserEmail, setCurrentUserEmail] = useState('');
    const [assigneeDraft, setAssigneeDraft] = useState('');
    const [savingAssignee, setSavingAssignee] = useState(false);
    const [savingQueue, setSavingQueue] = useState(false);
    const [tagDraft, setTagDraft] = useState('');
    const [savingTags, setSavingTags] = useState(false);
    const [customFieldDefinitions, setCustomFieldDefinitions] = useState<SupportCustomFieldDefinition[]>([]);
    const [customFieldDraft, setCustomFieldDraft] = useState<Record<string, unknown>>({});
    const [savingCustomFields, setSavingCustomFields] = useState(false);
    const [preparingCustomFields, setPreparingCustomFields] = useState(false);
    const [preparingTriage, setPreparingTriage] = useState(false);
    const [preparingTicketPackage, setPreparingTicketPackage] = useState(false);
    const [noteDraft, setNoteDraft] = useState('');
    const [savingNote, setSavingNote] = useState(false);
    const [replyDraft, setReplyDraft] = useState('');
    const [replyRequiresApproval, setReplyRequiresApproval] = useState(false);
    const [replyIncludeFeedbackLink, setReplyIncludeFeedbackLink] = useState(true);
    const [selectedReplyMacroId, setSelectedReplyMacroId] = useState(NO_REPLY_MACRO_VALUE);
    const [saveMacroOpen, setSaveMacroOpen] = useState(false);
    const [macroTitleDraft, setMacroTitleDraft] = useState('');
    const [macroVisibilityDraft, setMacroVisibilityDraft] = useState<'private' | 'shared'>('shared');
    const [macroTagsDraft, setMacroTagsDraft] = useState('');
    const [savingMacro, setSavingMacro] = useState(false);
    const [archivingMacroId, setArchivingMacroId] = useState('');
    const [renderingMacroId, setRenderingMacroId] = useState('');
    const [savingReplyStatus, setSavingReplyStatus] = useState('');
    const [editingReplyId, setEditingReplyId] = useState('');
    const [editingReplyBody, setEditingReplyBody] = useState('');
    const [savingReplyEditId, setSavingReplyEditId] = useState('');
    const [sendingReplyId, setSendingReplyId] = useState('');
    const [approvingReplyId, setApprovingReplyId] = useState('');
    const [changeRequestReplyId, setChangeRequestReplyId] = useState('');
    const [changeRequestNote, setChangeRequestNote] = useState('');
    const [requestingChangesReplyId, setRequestingChangesReplyId] = useState('');
    const [revisingReplyId, setRevisingReplyId] = useState('');
    const [movingIssueId, setMovingIssueId] = useState('');
    const [claimingIssueId, setClaimingIssueId] = useState('');
    const [selectedIssueIds, setSelectedIssueIds] = useState<string[]>([]);
    const [bulkUpdating, setBulkUpdating] = useState(false);
    const [bulkLabelDraft, setBulkLabelDraft] = useState('');
    const [bulkLabelingMode, setBulkLabelingMode] = useState<'' | 'add' | 'remove'>('');
    const [bulkApprovingReplies, setBulkApprovingReplies] = useState(false);
    const [bulkRequestingReplyChanges, setBulkRequestingReplyChanges] = useState(false);
    const [bulkRequestReplyChangesOpen, setBulkRequestReplyChangesOpen] = useState(false);
    const [bulkRequestReplyChangesNote, setBulkRequestReplyChangesNote] = useState('');
    const [bulkReviewingActions, setBulkReviewingActions] = useState<'' | 'approve' | 'reject'>('');
    const [bulkRejectActionsOpen, setBulkRejectActionsOpen] = useState(false);
    const [bulkRejectActionsNote, setBulkRejectActionsNote] = useState('');
    const [bulkRetryingFailedReplies, setBulkRetryingFailedReplies] = useState(false);
    const [bulkPreparingAgentReplies, setBulkPreparingAgentReplies] = useState(false);
    const [bulkFindingKnowledgeGaps, setBulkFindingKnowledgeGaps] = useState(false);
    const [ticketNextActionBusy, setTicketNextActionBusy] = useState('');
    const [reviewingPackageMode, setReviewingPackageMode] = useState<'' | 'approve' | 'approve-send'>('');
    const [dragOverLane, setDragOverLane] = useState<WorkflowLane | ''>('');
    const [savingActionKey, setSavingActionKey] = useState('');
    const [savingAccountInsightKey, setSavingAccountInsightKey] = useState('');
    const [approvingActionExecutionId, setApprovingActionExecutionId] = useState('');
    const [rejectingActionExecutionId, setRejectingActionExecutionId] = useState('');
    const [creatingPortalLink, setCreatingPortalLink] = useState(false);
    const [creatingKnowledgeArticle, setCreatingKnowledgeArticle] = useState('');
    const [publishingKnowledgeArticleId, setPublishingKnowledgeArticleId] = useState('');
    const [portalUrl, setPortalUrl] = useState('');
    const [agentQuestion, setAgentQuestion] = useState('');
    const [askingAgent, setAskingAgent] = useState(false);
    const [runningAgentActionKey, setRunningAgentActionKey] = useState('');
    const [agentAnswer, setAgentAnswer] = useState<SupportAgentAnswer | null>(null);
    const agentQuestionRef = useRef<HTMLTextAreaElement | null>(null);
    const [newTicketOpen, setNewTicketOpen] = useState(false);
    const [creatingTicket, setCreatingTicket] = useState(false);
    const [newTicketSubject, setNewTicketSubject] = useState('');
    const [newTicketFrom, setNewTicketFrom] = useState('');
    const [newTicketName, setNewTicketName] = useState('');
    const [newTicketAccount, setNewTicketAccount] = useState('');
    const [newTicketBody, setNewTicketBody] = useState('');
    const [newTicketAccounts, setNewTicketAccounts] = useState<SupportAccount[]>([]);
    const [loadingNewTicketAccounts, setLoadingNewTicketAccounts] = useState(false);
    const [loadingNewTicketAccountDetail, setLoadingNewTicketAccountDetail] = useState(false);
    const [newTicketAccountId, setNewTicketAccountId] = useState(NO_ACCOUNT_RECORD_VALUE);
    const [newTicketContactId, setNewTicketContactId] = useState(NO_CONTACT_RECORD_VALUE);
    const [newTicketAccountDetail, setNewTicketAccountDetail] = useState<SupportAccount | null>(null);
    const [newTicketPriority, setNewTicketPriority] = useState<SupportIssuePriority>('normal');
    const [newTicketAssignee, setNewTicketAssignee] = useState('');
    const [newTicketQueueKey, setNewTicketQueueKey] = useState('support');
    const [saveViewOpen, setSaveViewOpen] = useState(false);
    const [editingViewId, setEditingViewId] = useState('');
    const [viewName, setViewName] = useState('');
    const [viewVisibility, setViewVisibility] = useState<'private' | 'shared'>('private');
    const [savingView, setSavingView] = useState(false);
    const [deletingViewId, setDeletingViewId] = useState('');
    const [notifications, setNotifications] = useState<SupportNotification[]>([]);
    const [loadingNotifications, setLoadingNotifications] = useState(false);
    const [refreshingInbox, setRefreshingInbox] = useState(false);
    const [lastRefreshedAt, setLastRefreshedAt] = useState('');
    const [refreshError, setRefreshError] = useState('');
    const [togglingWatcher, setTogglingWatcher] = useState(false);
    const [mergeOpen, setMergeOpen] = useState(false);
    const [mergeTargetIssueId, setMergeTargetIssueId] = useState('');
    const [mergeNote, setMergeNote] = useState('');
    const [mergingIssue, setMergingIssue] = useState(false);
    const [closeWithoutReplyOpen, setCloseWithoutReplyOpen] = useState(false);
    const [closeWithoutReplyNote, setCloseWithoutReplyNote] = useState('');
    const [closingWithoutReply, setClosingWithoutReply] = useState(false);
    const [duplicateSuggestions, setDuplicateSuggestions] = useState<SupportIssueDuplicateSuggestion[]>([]);
    const [loadingDuplicateSuggestions, setLoadingDuplicateSuggestions] = useState(false);
    const [splitMessageOpen, setSplitMessageOpen] = useState(false);
    const [splitMessageTarget, setSplitMessageTarget] = useState<SupportIssueMessage | null>(null);
    const [splitMessageSubject, setSplitMessageSubject] = useState('');
    const [splitMessageNote, setSplitMessageNote] = useState('');
    const [splittingMessageId, setSplittingMessageId] = useState('');

    const basePath = tenantId ? `/${tenantId}/${projectId}/inbox` : '';

    const currentInboxFilters = useCallback((): SavedInboxFilters => ({
        statusFilter,
        queueFilter,
        accountFilter,
        channelFilter,
        assigneeFilter,
        tagFilter,
        query: query.trim(),
        viewMode,
    }), [accountFilter, assigneeFilter, channelFilter, query, queueFilter, statusFilter, tagFilter, viewMode]);

    const writeInboxFiltersToUrl = useCallback((filters: SavedInboxFilters) => {
        const search = searchWithInboxFilters(location.search, filters);
        const nextPath = `${location.pathname}${search ? `?${search}` : ''}`;
        if (nextPath !== `${location.pathname}${location.search}`) {
            void navigate(nextPath, { replace: true });
        }
    }, [location.pathname, location.search, navigate]);

    const changeInboxFilters = useCallback((patch: Partial<SavedInboxFilters>) => {
        const nextFilters = { ...currentInboxFilters(), ...patch };
        if (patch.statusFilter !== undefined) setStatusFilter(nextFilters.statusFilter);
        if (patch.queueFilter !== undefined) setQueueFilter(nextFilters.queueFilter);
        if (patch.accountFilter !== undefined) setAccountFilter(nextFilters.accountFilter);
        if (patch.channelFilter !== undefined) setChannelFilter(nextFilters.channelFilter);
        if (patch.assigneeFilter !== undefined) setAssigneeFilter(nextFilters.assigneeFilter);
        if (patch.tagFilter !== undefined) setTagFilter(nextFilters.tagFilter);
        if (patch.query !== undefined) setQuery(nextFilters.query);
        if (patch.viewMode !== undefined) setViewMode(nextFilters.viewMode);
        writeInboxFiltersToUrl(nextFilters);
    }, [currentInboxFilters, writeInboxFiltersToUrl]);

    const changeStatusFilter = useCallback((nextValue: string) => {
        changeInboxFilters({ statusFilter: normalizeInboxFilter(nextValue) });
    }, [changeInboxFilters]);

    const openBoardOperatingAction = useCallback((action: SupportIssueBoardAction | null | undefined) => {
        if (!action) return;
        const nextStatus = normalizeInboxFilter(action.statusFilter || action.lane || 'all');
        changeInboxFilters({ statusFilter: nextStatus, viewMode: 'board' });
    }, [changeInboxFilters]);

    const boardStatusFilter = boardApiStatusFilter(statusFilter);
    const boardQueueFilter = queueApiFilter(queueFilter);
    const boardApiFilters = useMemo(
        () => boardApiFiltersFrom(currentInboxFilters(), currentUserEmail),
        [currentInboxFilters, currentUserEmail],
    );

    const navigateToIssue = useCallback((nextIssueId: string, patch: Partial<SavedInboxFilters> = {}) => {
        if (!basePath) return;
        const nextFilters = { ...currentInboxFilters(), ...patch };
        if (patch.viewMode !== undefined) setViewMode(nextFilters.viewMode);
        const search = searchWithInboxFilters(location.search, nextFilters);
        void navigate(`${basePath}/${nextIssueId}${search ? `?${search}` : ''}`);
    }, [basePath, currentInboxFilters, location.search, navigate]);

    const closeIssueDrawer = useCallback((patch: Partial<SavedInboxFilters> = {}) => {
        if (!basePath) return;
        const nextFilters = { ...currentInboxFilters(), ...patch };
        if (patch.viewMode !== undefined) setViewMode(nextFilters.viewMode);
        const search = searchWithInboxFilters(location.search, nextFilters);
        void navigate(`${basePath}${search ? `?${search}` : ''}`);
    }, [basePath, currentInboxFilters, location.search, navigate]);

    useEffect(() => {
        const filters = inboxFiltersFromSearch(location.search);
        setStatusFilter(prev => prev === filters.statusFilter ? prev : filters.statusFilter);
        setQueueFilter(prev => prev === filters.queueFilter ? prev : filters.queueFilter);
        setAccountFilter(prev => prev === filters.accountFilter ? prev : filters.accountFilter);
        setChannelFilter(prev => prev === filters.channelFilter ? prev : filters.channelFilter);
        setAssigneeFilter(prev => prev === filters.assigneeFilter ? prev : filters.assigneeFilter);
        setTagFilter(prev => prev === filters.tagFilter ? prev : filters.tagFilter);
        setQuery(prev => prev === filters.query ? prev : filters.query);
        setViewMode(prev => prev === filters.viewMode ? prev : filters.viewMode);
    }, [location.search]);

    const loadIssues = useCallback(async (options: { silent?: boolean } = {}) => {
        const silent = options.silent === true;
        if (!silent) setLoadingList(true);
        try {
            const res = await api.getIssues(projectId, 'all');
            if (res.error || !res.data) {
                if (!silent) toast.error(res.error || t('Could not load inbox'));
                else setRefreshError(t('Could not refresh inbox'));
                return false;
            }
            setIssues(res.data.items);
            setLastRefreshedAt(new Date().toISOString());
            if (!silent) setRefreshError('');
            return true;
        } finally {
            if (!silent) setLoadingList(false);
        }
    }, [projectId, t]);

    const loadIssueBoard = useCallback(async () => {
        const res = await api.getIssueBoard(projectId, boardStatusFilter, 200, boardQueueFilter, boardApiFilters);
        if (res.error || !res.data) {
            setRefreshError(t('Could not refresh board'));
            return false;
        }
        setIssueBoard(res.data);
        return true;
    }, [boardApiFilters, boardQueueFilter, boardStatusFilter, projectId, t]);

    useEffect(() => {
        void loadIssues();
    }, [loadIssues]);

    useEffect(() => {
        void loadIssueBoard();
    }, [loadIssueBoard]);

    const loadQueues = useCallback(() => {
        void api.getSupportQueues(projectId, 'active', true).then((res) => {
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not load queues'));
                return;
            }
            setSupportQueues(res.data.items);
        });
    }, [projectId, t]);

    useEffect(() => {
        loadQueues();
    }, [loadQueues]);

    const loadInboxViews = useCallback(() => {
        setLoadingViews(true);
        void api.getInboxViews(projectId).then((res) => {
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not load views'));
                return;
            }
            setInboxViews(res.data.items);
        }).finally(() => setLoadingViews(false));
    }, [projectId, t]);

    useEffect(() => {
        loadInboxViews();
    }, [loadInboxViews]);

    const loadReplyMacros = useCallback(() => {
        setLoadingReplyMacros(true);
        void api.getReplyMacros(projectId, 'active').then((res) => {
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not load reply macros'));
                return;
            }
            setReplyMacros(res.data.items);
        }).finally(() => setLoadingReplyMacros(false));
    }, [projectId, t]);

    useEffect(() => {
        loadReplyMacros();
    }, [loadReplyMacros]);

    const loadNotifications = useCallback(async (options: { silent?: boolean } = {}) => {
        const silent = options.silent === true;
        if (!silent) setLoadingNotifications(true);
        try {
            const res = await api.getNotifications(projectId, 'unread');
            if (res.error || !res.data) {
                if (!silent) toast.error(res.error || t('Could not load notifications'));
                else setRefreshError(t('Could not refresh inbox'));
                return false;
            }
            setNotifications(res.data.items);
            return true;
        } finally {
            if (!silent) setLoadingNotifications(false);
        }
    }, [projectId, t]);

    useEffect(() => {
        void loadNotifications();
    }, [loadNotifications]);

    const loadChannelCoverage = useCallback(async (options: { silent?: boolean } = {}) => {
        const silent = options.silent === true;
        if (!silent) setLoadingChannelCoverage(true);
        try {
            const res = await api.getChannelActivationBacklog(projectId);
            if (res.error || !res.data) {
                if (!silent) toast.error(res.error || t('Could not load channel coverage'));
                return false;
            }
            setChannelActivationBacklog(res.data);
            return true;
        } finally {
            if (!silent) setLoadingChannelCoverage(false);
        }
    }, [projectId, t]);

    useEffect(() => {
        void loadChannelCoverage();
    }, [loadChannelCoverage]);

    const loadSupportAnalytics = useCallback(async (options: { silent?: boolean } = {}) => {
        const silent = options.silent === true;
        if (!silent) setLoadingSupportAnalytics(true);
        try {
            const res = await api.getSupportAnalytics(projectId);
            if (res.error || !res.data) {
                if (!silent) toast.error(res.error || t('Could not load account actions'));
                return false;
            }
            setSupportAnalytics(res.data);
            return true;
        } finally {
            if (!silent) setLoadingSupportAnalytics(false);
        }
    }, [projectId, t]);

    useEffect(() => {
        void loadSupportAnalytics();
    }, [loadSupportAnalytics]);

    const loadKnowledgeArticles = useCallback(() => {
        setLoadingKnowledge(true);
        void api.getKnowledgeArticles(projectId, 'all').then((res) => {
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not load knowledge'));
                return;
            }
            setKnowledgeArticles(res.data.items);
        }).finally(() => setLoadingKnowledge(false));
    }, [projectId, t]);

    useEffect(() => {
        loadKnowledgeArticles();
    }, [loadKnowledgeArticles]);

    useEffect(() => {
        let cancelled = false;
        void api.getSlaPolicy(projectId).then((res) => {
            if (cancelled || !res.data) return;
            setCustomFieldDefinitions(customFieldDefinitionsFromMetadata(res.data.metadata));
        });
        return () => { cancelled = true; };
    }, [projectId]);

    useEffect(() => {
        let cancelled = false;
        void api.listMembers(projectId).then((res) => {
            if (!cancelled && res.data) {
                setProjectMembers(res.data);
            }
        });
        void api.getCurrentUser().then((res) => {
            if (!cancelled && res.data?.email) {
                setCurrentUserEmail(res.data.email);
            }
        });
        return () => { cancelled = true; };
    }, [projectId]);

    const loadIssueDetail = useCallback(async (nextIssueId: string, options: { silent?: boolean } = {}) => {
        const silent = options.silent === true;
        if (!silent) setLoadingDetail(true);
        try {
            const [res, workspaceRes] = await Promise.all([
                api.getIssue(projectId, nextIssueId),
                api.getIssueAnswerWorkspace(projectId, nextIssueId),
            ]);
            if (res.error || !res.data) {
                if (!silent) toast.error(res.error || t('Could not load ticket'));
                else setRefreshError(t('Could not refresh inbox'));
                return false;
            }
            setSelectedIssue(res.data);
            setAnswerWorkspace(workspaceRes.data ?? null);
            if (!silent) {
                setAssigneeDraft(res.data.assigneeEmail || '');
                setTagDraft((res.data.tags ?? []).join(', '));
                setCustomFieldDraft(res.data.customFields ?? {});
                setReplyDraft(res.data.draftReply || '');
                setReplyRequiresApproval(Boolean(res.data.draftReply?.trim()));
                setAgentAnswer(null);
                setAgentQuestion('');
                setEditingReplyId('');
                setEditingReplyBody('');
                setChangeRequestReplyId('');
                setChangeRequestNote('');
                setCloseWithoutReplyOpen(false);
                setCloseWithoutReplyNote('');
            }
            return true;
        } finally {
            if (!silent) setLoadingDetail(false);
        }
    }, [projectId, t]);

    const refreshAnswerWorkspace = useCallback(async (nextIssueId: string) => {
        const workspaceRes = await api.getIssueAnswerWorkspace(projectId, nextIssueId);
        if (workspaceRes.data) {
            setAnswerWorkspace(workspaceRes.data);
            return true;
        }
        setAnswerWorkspace(prev => prev?.issueId === nextIssueId ? null : prev);
        return false;
    }, [projectId]);

    useEffect(() => {
        if (!issueId) {
            setSelectedIssue(null);
            setAnswerWorkspace(null);
            setTicketAccount(null);
            setTagDraft('');
            setCustomFieldDraft({});
            setDuplicateSuggestions([]);
            return;
        }
        void loadIssueDetail(issueId);
    }, [issueId, loadIssueDetail]);

    useEffect(() => {
        setCustomFieldDraft(selectedIssue?.customFields ?? {});
    }, [selectedIssue?.id, selectedIssue?.customFields]);

    const refreshInboxData = useCallback(async () => {
        const results = await Promise.all([
            loadIssues({ silent: true }),
            loadIssueBoard(),
            loadNotifications({ silent: true }),
            loadChannelCoverage({ silent: true }),
            loadSupportAnalytics({ silent: true }),
            issueId ? loadIssueDetail(issueId, { silent: true }) : Promise.resolve(true),
        ]);
        const refreshed = results.every(Boolean);
        setRefreshError(refreshed ? '' : t('Could not refresh inbox'));
        return refreshed;
    }, [issueId, loadChannelCoverage, loadIssueBoard, loadIssueDetail, loadIssues, loadNotifications, loadSupportAnalytics, t]);

    useEffect(() => {
        const timer = window.setInterval(() => {
            if (document.visibilityState === 'hidden') return;
            void refreshInboxData();
        }, INBOX_REFRESH_INTERVAL_MS);
        return () => window.clearInterval(timer);
    }, [refreshInboxData]);

    useEffect(() => {
        const accountId = selectedIssue?.accountId;
        if (!accountId) {
            setTicketAccount(null);
            setLoadingTicketAccount(false);
            return;
        }
        let cancelled = false;
        setLoadingTicketAccount(true);
        void api.getAccount(projectId, accountId).then((res) => {
            if (cancelled) return;
            setTicketAccount(res.data ?? null);
        }).finally(() => {
            if (!cancelled) setLoadingTicketAccount(false);
        });
        return () => {
            cancelled = true;
        };
    }, [projectId, selectedIssue?.accountId]);

    useEffect(() => {
        if (!issueId) {
            setDuplicateSuggestions([]);
            return;
        }
        let cancelled = false;
        setLoadingDuplicateSuggestions(true);
        void api.getIssueDuplicateSuggestions(projectId, issueId, 5).then((res) => {
            if (cancelled) return;
            if (res.error || !res.data) {
                setDuplicateSuggestions([]);
                return;
            }
            setDuplicateSuggestions(res.data.items);
        }).finally(() => {
            if (!cancelled) setLoadingDuplicateSuggestions(false);
        });
        return () => { cancelled = true; };
    }, [issueId, projectId]);

    const searchedIssues = useMemo(() => {
        const needle = query.trim().toLowerCase();
        if (!needle) return issues;
        return issues.filter(issue => issueSearchText(issue).includes(needle));
    }, [issues, query]);

    const queueOptions = useMemo(() => {
        const byKey = new Map<string, { queueKey: string; name: string }>();
        for (const queue of supportQueues) {
            if (queue.queueKey) {
                byKey.set(queue.queueKey, { queueKey: queue.queueKey, name: queue.name || queue.queueKey });
            }
        }
        for (const issue of issues) {
            const key = issueQueueKey(issue);
            if (key && !byKey.has(key)) {
                byKey.set(key, { queueKey: key, name: issueQueueLabel(issue) });
            }
        }
        if (selectedIssue) {
            const key = issueQueueKey(selectedIssue);
            if (key && !byKey.has(key)) {
                byKey.set(key, { queueKey: key, name: issueQueueLabel(selectedIssue) });
            }
        }
        if (!byKey.has('support')) {
            byKey.set('support', { queueKey: 'support', name: 'Support' });
        }
        return [...byKey.values()].sort((a, b) => {
            if (a.queueKey === 'support') return -1;
            if (b.queueKey === 'support') return 1;
            return a.name.localeCompare(b.name);
        });
    }, [issues, selectedIssue, supportQueues]);

    const queueFilteredIssues = useMemo(() => {
        if (queueFilter === ALL_QUEUES_VALUE) return searchedIssues;
        if (queueFilter === NO_QUEUE_VALUE) return searchedIssues.filter(issue => !issueQueueKey(issue));
        return searchedIssues.filter(issue => issueQueueKey(issue) === queueFilter);
    }, [queueFilter, searchedIssues]);

    const accountFilterOptions = useMemo(() => {
        const accounts = new Map<string, string>();
        for (const issue of issues) {
            const key = issueAccountKey(issue);
            if (key && !accounts.has(key)) {
                accounts.set(key, issueAccountLabel(issue));
            }
        }
        if (selectedIssue) {
            const key = issueAccountKey(selectedIssue);
            if (key && !accounts.has(key)) {
                accounts.set(key, issueAccountLabel(selectedIssue));
            }
        }
        return [...accounts.entries()]
            .map(([value, label]) => ({ value, label }))
            .sort((a, b) => a.label.localeCompare(b.label));
    }, [issues, selectedIssue]);

    const accountFilteredIssues = useMemo(() => {
        if (accountFilter === ALL_ACCOUNTS_VALUE) return queueFilteredIssues;
        if (accountFilter === NO_ACCOUNT_VALUE) return queueFilteredIssues.filter(issue => !issueAccountKey(issue));
        return queueFilteredIssues.filter(issue => issueAccountKey(issue) === accountFilter);
    }, [accountFilter, queueFilteredIssues]);

    const channelOptions = useMemo(() => {
        const channels = new Map<string, string>();
        for (const issue of issues) {
            const key = issueChannelKey(issue);
            if (key && !channels.has(key)) channels.set(key, issueChannelLabel(issue));
        }
        if (selectedIssue) {
            const key = issueChannelKey(selectedIssue);
            if (key && !channels.has(key)) channels.set(key, issueChannelLabel(selectedIssue));
        }
        return [...channels.entries()]
            .map(([value, label]) => ({ value, label }))
            .sort((a, b) => a.label.localeCompare(b.label));
    }, [issues, selectedIssue]);

    const channelFilteredIssues = useMemo(() => {
        if (channelFilter === ALL_CHANNELS_VALUE) return accountFilteredIssues;
        if (channelFilter === NO_CHANNEL_VALUE) return accountFilteredIssues.filter(issue => !issueChannelKey(issue));
        return accountFilteredIssues.filter(issue => issueChannelKey(issue) === channelFilter);
    }, [accountFilteredIssues, channelFilter]);

    const tagOptions = useMemo(() => {
        const tags = new Map<string, string>();
        for (const issue of issues) {
            for (const tag of issue.tags ?? []) {
                const clean = tag.trim();
                if (clean) tags.set(clean.toLowerCase(), clean);
            }
        }
        for (const tag of selectedIssue?.tags ?? []) {
            const clean = tag.trim();
            if (clean) tags.set(clean.toLowerCase(), clean);
        }
        return [...tags.values()].sort((a, b) => a.localeCompare(b));
    }, [issues, selectedIssue?.tags]);

    const tagFilteredIssues = useMemo(() => {
        if (tagFilter === ALL_TAGS_VALUE) return channelFilteredIssues;
        if (tagFilter === NO_TAGS_VALUE) return channelFilteredIssues.filter(issue => (issue.tags ?? []).length === 0);
        return channelFilteredIssues.filter(issue => (issue.tags ?? []).some(tag => tag.toLowerCase() === tagFilter));
    }, [channelFilteredIssues, tagFilter]);

    const assigneeFilterOptions = useMemo(() => {
        const emails = new Map<string, string>();
        for (const member of projectMembers) {
            const email = member.email?.trim();
            if (email) emails.set(email.toLowerCase(), email);
        }
        for (const issue of issues) {
            const email = issue.assigneeEmail?.trim();
            if (email) emails.set(email.toLowerCase(), email);
        }
        const selectedAssignee = selectedIssue?.assigneeEmail?.trim();
        if (selectedAssignee) emails.set(selectedAssignee.toLowerCase(), selectedAssignee);
        const current = currentUserEmail.trim();
        if (current) emails.set(current.toLowerCase(), current);
        return [...emails.values()].sort((a, b) => a.localeCompare(b));
    }, [currentUserEmail, issues, projectMembers, selectedIssue?.assigneeEmail]);

    const assigneeFilteredIssues = useMemo(() => {
        if (assigneeFilter === ALL_ASSIGNEES_VALUE) return tagFilteredIssues;
        if (assigneeFilter === UNASSIGNED_VALUE) return tagFilteredIssues.filter(issue => !issueAssigneeKey(issue));
        if (assigneeFilter === MY_ASSIGNEE_VALUE) {
            const current = currentUserEmail.trim().toLowerCase();
            if (!current) return [];
            return tagFilteredIssues.filter(issue => issueAssigneeKey(issue) === current);
        }
        const selectedAssignee = assigneeFilter.trim().toLowerCase();
        if (!selectedAssignee) return tagFilteredIssues;
        return tagFilteredIssues.filter(issue => issueAssigneeKey(issue) === selectedAssignee);
    }, [assigneeFilter, currentUserEmail, tagFilteredIssues]);

    const filteredIssues = useMemo(() => {
        if (statusFilter === 'all') return assigneeFilteredIssues;
        return assigneeFilteredIssues.filter(issue => issueMatchesInboxStatus(issue, statusFilter));
    }, [assigneeFilteredIssues, statusFilter]);

    const boardSourceIssues = useMemo(() => {
        if (['all', 'open', 'ongoing', 'done'].includes(statusFilter)) return assigneeFilteredIssues;
        return assigneeFilteredIssues.filter(issue => issueMatchesInboxStatus(issue, statusFilter));
    }, [assigneeFilteredIssues, statusFilter]);

    useEffect(() => {
        if (!basePath) return;
        const search = searchWithInboxFilters(location.search, currentInboxFilters());
        if (filteredIssues.length === 0) {
            if (issueId) {
                void navigate(`${basePath}${search ? `?${search}` : ''}`, { replace: true });
            }
            return;
        }
        if (issueId && filteredIssues.some(issue => issue.id === issueId)) return;
        if (issueId) void navigate(`${basePath}${search ? `?${search}` : ''}`, { replace: true });
    }, [basePath, currentInboxFilters, filteredIssues, issueId, location.search, navigate]);

    useEffect(() => {
        const visibleIssueIds = new Set(filteredIssues.map(issue => issue.id));
        setSelectedIssueIds(prev => prev.filter(issueId => visibleIssueIds.has(issueId)));
    }, [filteredIssues]);

    const boardGroups = useMemo(() => {
        const groups: Record<WorkflowLane, SupportIssue[]> = {
            open: [],
            ongoing: [],
            done: [],
        };
        for (const issue of boardSourceIssues) {
            groups[issueWorkflowStatus(issue)].push(issue);
        }
        return groups;
    }, [boardSourceIssues]);
    const issueBoardLaneByStatus = useMemo(() => new Map(
        (issueBoard?.lanes ?? []).map(lane => [lane.status, lane]),
    ), [issueBoard]);
    const boardNextAction = issueBoard?.nextAction ?? null;
    const boardWorkflowPolicy = issueBoard?.workflow;
    const boardWorkflowLanePolicies = boardWorkflowPolicy?.lanes ?? [];
    const boardWorkflowAssigneeStatuses = boardWorkflowPolicy?.assigneeRequiredStatuses ?? ['ongoing', 'done'];
    const boardWorkflowDoneBlockers = boardWorkflowPolicy?.doneBlockers ?? ['pending approvals', 'pending action approvals', 'queued replies', 'failed deliveries'];
    const boardLaneHealth = useMemo(() => ({
        open: laneHealthSummary(boardGroups.open),
        ongoing: laneHealthSummary(boardGroups.ongoing),
        done: laneHealthSummary(boardGroups.done),
    }), [boardGroups]);

    const approvalQueueIssues = useMemo(
        () => assigneeFilteredIssues.filter(issueNeedsApproval),
        [assigneeFilteredIssues],
    );
    const approvalQueueIssueIds = useMemo(
        () => approvalQueueIssues.map(issue => issue.id),
        [approvalQueueIssues],
    );
    const approvalQueueReplyCount = useMemo(
        () => approvalQueueIssues.reduce((count, issue) => count + pendingReplyApprovalCount(issue), 0),
        [approvalQueueIssues],
    );
    const approvalQueueActionCount = useMemo(
        () => approvalQueueIssues.reduce((count, issue) => count + pendingActionApprovalCount(issue), 0),
        [approvalQueueIssues],
    );
    const approvalQueueApprovalCount = useMemo(
        () => approvalQueueIssues.reduce((count, issue) => count + issueApprovalCount(issue), 0),
        [approvalQueueIssues],
    );
    const selectedApprovalIssueCount = useMemo(
        () => selectedIssueIds.filter(id => approvalQueueIssueIds.includes(id)).length,
        [approvalQueueIssueIds, selectedIssueIds],
    );
    const approvalQueueFullySelected = approvalQueueIssueIds.length > 0
        && selectedApprovalIssueCount === approvalQueueIssueIds.length;
    const approvalQueuePreviewIssues = useMemo(
        () => approvalQueueIssues.slice(0, 5),
        [approvalQueueIssues],
    );
    const hiddenApprovalQueueCount = Math.max(approvalQueueIssues.length - approvalQueuePreviewIssues.length, 0);

    const selectedMessages = selectedIssue?.messages ?? [];
    const pendingReviewReplies = useMemo(
        () => (selectedIssue?.outboundMessages ?? []).filter(replyNeedsApproval),
        [selectedIssue?.outboundMessages],
    );
    const pendingReviewActions = useMemo(
        () => (selectedIssue?.actionExecutions ?? []).filter(actionExecutionNeedsApproval),
        [selectedIssue?.actionExecutions],
    );
    const pendingReviewCount = pendingReviewReplies.length + pendingReviewActions.length;
    const selectedWorkspace = selectedIssue && answerWorkspace?.issueId === selectedIssue.id ? answerWorkspace : null;
    const selectedTicketProof = selectedWorkspace?.ticketProof ?? null;
    const selectedReplyReadiness = selectedWorkspace?.replyReadiness ?? null;
    const selectedReplySendBlocked = Boolean(selectedReplyReadiness && !selectedReplyReadiness.ready);
    const selectedReplySendBlockDetail = replyReadinessBlockDetail(selectedReplyReadiness, t);
    const selectedReplySendNowBlocked = selectedReplySendBlocked || replyRequiresApproval;
    const selectedReplySendNowBlockDetail = replyRequiresApproval
        ? t('Turn off approval to send now.')
        : selectedReplySendBlockDetail;
    const selectedReplyRouteLabel = replyReadinessRouteLabel(selectedReplyReadiness);
    const selectedReplyTargetRows = useMemo(
        () => replyReadinessTargetRows(selectedReplyReadiness),
        [selectedReplyReadiness],
    );
    const selectedReplyAdapter = selectedReplyReadiness?.adapter ?? null;
    const selectedReplyAdapterTransports = selectedReplyAdapter?.supportedTransports ?? [];
    const selectedReplyRouteFixAction = replyReadinessFixAction(selectedReplyReadiness);
    const selectedReplyRouteFixChannel = selectedReplyReadiness?.channelKey
        || selectedReplyAdapter?.channel
        || selectedIssue?.channel
        || '';
    const selectedReplyRouteFixHref = tenantId
        ? `/${encodeURIComponent(tenantId)}/${encodeURIComponent(projectId)}/channels?${new URLSearchParams({
            ...(selectedReplyRouteFixChannel ? { channel: selectedReplyRouteFixChannel } : {}),
            action: selectedReplyRouteFixAction,
        }).toString()}`
        : '';
    const reviewPackageBusy = Boolean(
        reviewingPackageMode
        || approvingReplyId
        || sendingReplyId
        || savingReplyEditId
        || requestingChangesReplyId
        || revisingReplyId
        || approvingActionExecutionId
        || rejectingActionExecutionId,
    );
    const draftReply = selectedIssue?.draftReply || '';
    const selectedReplyMacro = useMemo(
        () => replyMacros.find(macro => macro.id === selectedReplyMacroId) ?? null,
        [replyMacros, selectedReplyMacroId],
    );
    const selectedKnowledgeGaps = selectedIssue?.knowledgeGaps ?? [];
    const agentChatRuns = useMemo(
        () => (selectedIssue?.aiRuns ?? []).filter(isAgentChatRun),
        [selectedIssue?.aiRuns],
    );
    const agentMessages = useMemo<SupportAgentMessage[]>(
        () => selectedIssue?.agentMessages ?? [],
        [selectedIssue?.agentMessages],
    );
    const auditAiRuns = useMemo(
        () => (selectedIssue?.aiRuns ?? []).filter(run => !isAgentChatRun(run)),
        [selectedIssue?.aiRuns],
    );
    const auditRunbookConcerns = useMemo(
        () => latestRunbookConcerns(auditAiRuns),
        [auditAiRuns],
    );
    const searchedKnowledgeArticles = useMemo(() => {
        const needle = knowledgeQuery.trim().toLowerCase();
        if (!needle) return [];
        const suggestionIds = new Set((selectedIssue?.knowledgeSuggestions ?? []).map(article => article.id));
        return knowledgeArticles
            .filter(article => !suggestionIds.has(article.id) && knowledgeSearchText(article).includes(needle))
            .slice(0, 5);
    }, [knowledgeArticles, knowledgeQuery, selectedIssue?.knowledgeSuggestions]);
    const selectedQueue = useMemo(() => {
        const key = selectedIssue ? issueQueueKey(selectedIssue) : '';
        if (!key) return null;
        return supportQueues.find(queue => queue.queueKey === key) ?? null;
    }, [selectedIssue, supportQueues]);
    const selectedQueueOwnerEmails = useMemo(
        () => queueOwnerEmails(selectedQueue),
        [selectedQueue],
    );
    const selectedQueueOwnerWorkloads = useMemo(
        () => queueOwnerWorkloadByEmail(selectedQueue),
        [selectedQueue],
    );
    const assigneeOptions = useMemo(() => {
        const emails = new Set<string>();
        const allowed = new Set(selectedQueueOwnerEmails);
        if (allowed.size > 0) {
            for (const email of allowed) emails.add(email);
        } else {
            for (const member of projectMembers) {
                if (member.email) emails.add(member.email);
            }
            if (currentUserEmail) emails.add(currentUserEmail);
        }
        if (assigneeDraft) emails.add(assigneeDraft);
        return [...emails].sort((a, b) => a.localeCompare(b));
    }, [assigneeDraft, currentUserEmail, projectMembers, selectedQueueOwnerEmails]);
    const selectedAssigneeWorkload = useMemo(
        () => selectedQueueOwnerWorkloads.get(assigneeDraft.trim().toLowerCase()),
        [assigneeDraft, selectedQueueOwnerWorkloads],
    );
    const selectedAssigneeWorkloadDetail = useMemo(
        () => queueOwnerWorkloadDetail(assigneeDraft.trim(), selectedAssigneeWorkload),
        [assigneeDraft, selectedAssigneeWorkload],
    );
    const selectedWatchers = useMemo(
        () => selectedIssue?.watchers ?? [],
        [selectedIssue?.watchers],
    );
    const ticketAccountInsightSummary = useMemo(
        () => ticketAccount ? accountInsightSummary(ticketAccount) : null,
        [ticketAccount],
    );
    const ticketAccountCrmHealth = useMemo(
        () => ticketAccount ? accountCrmHealth(ticketAccount) : null,
        [ticketAccount],
    );
    const ticketAccountOpenInsights = useMemo(
        () => (ticketAccount?.insights ?? [])
            .filter(insight => insight.type !== 'summary' && insightIsUnresolved(insight.status))
            .slice(0, 3),
        [ticketAccount?.insights],
    );
    const currentWatcher = useMemo(() => {
        const current = currentUserEmail.trim().toLowerCase();
        if (!current) return null;
        return selectedWatchers.find(watcher => watcher.watcherEmail.toLowerCase() === current) ?? null;
    }, [currentUserEmail, selectedWatchers]);
    const canAutoClaim = Boolean(currentUserEmail.trim());
    const selectedIssueIdSet = useMemo(() => new Set(selectedIssueIds), [selectedIssueIds]);
    const selectedIssues = useMemo(
        () => issues.filter(issue => selectedIssueIdSet.has(issue.id)),
        [issues, selectedIssueIdSet],
    );
    const bulkAssigneeOptions = useMemo(() => {
        const emails = new Map<string, string>();
        const addEmail = (value: string | undefined | null) => {
            const email = value?.trim();
            const key = email?.toLowerCase();
            if (email && key && !emails.has(key)) emails.set(key, email);
        };
        addEmail(currentUserEmail);
        for (const member of projectMembers) addEmail(member.email);
        for (const issue of selectedIssues) addEmail(issue.assigneeEmail);
        const selectedQueueKeys = new Set(selectedIssues.map(issueQueueKey).filter(Boolean));
        for (const queue of supportQueues) {
            if (selectedQueueKeys.size > 0 && !selectedQueueKeys.has(queue.queueKey)) continue;
            addEmail(queue.defaultAssigneeEmail);
            for (const email of queueOwnerEmails(queue)) addEmail(email);
            for (const workload of queue.ownerWorkloads ?? []) addEmail(workload.assigneeEmail);
        }
        return [...emails.values()].sort((a, b) => a.localeCompare(b));
    }, [currentUserEmail, projectMembers, selectedIssues, supportQueues]);
    const selectedReplyApprovalIssueIds = useMemo(
        () => selectedIssues.filter(issue => pendingReplyApprovalCount(issue) > 0).map(issue => issue.id),
        [selectedIssues],
    );
    const bulkApproveSendBlocked = Boolean(
        selectedReplySendBlocked
        && selectedIssue
        && selectedReplyApprovalIssueIds.length === 1
        && selectedReplyApprovalIssueIds[0] === selectedIssue.id,
    );
    const selectedReplyApprovalCount = useMemo(
        () => selectedIssues.reduce((count, issue) => count + pendingReplyApprovalCount(issue), 0),
        [selectedIssues],
    );
    const selectedAgentReplyPrepIssues = useMemo(
        () => selectedIssues.filter(issue => issueNeedsResponse(issue) && pendingReplyApprovalCount(issue) === 0),
        [selectedIssues],
    );
    const selectedKnowledgeGapScanIssues = useMemo(
        () => selectedIssues.filter(issue => issueWorkflowStatus(issue) !== 'done' && !issueHasOpenKnowledgeGap(issue)),
        [selectedIssues],
    );
    const selectedActionApprovalIssueIds = useMemo(
        () => selectedIssues.filter(issue => pendingActionApprovalCount(issue) > 0).map(issue => issue.id),
        [selectedIssues],
    );
    const selectedActionApprovalCount = useMemo(
        () => selectedIssues.reduce((count, issue) => count + pendingActionApprovalCount(issue), 0),
        [selectedIssues],
    );
    const selectedFailedDeliveryIssueIds = useMemo(
        () => selectedIssues.filter(issueHasFailedDelivery).map(issue => issue.id),
        [selectedIssues],
    );
    const selectedOverdueSlaIssues = useMemo(
        () => selectedIssues.filter(issueHasOverdueSla),
        [selectedIssues],
    );
    const selectedDueSoonSlaIssues = useMemo(
        () => selectedIssues.filter(issue => !issueHasOverdueSla(issue) && issueHasDueSoonSla(issue)),
        [selectedIssues],
    );
    const selectedUnassignedIssueIds = useMemo(
        () => selectedIssues.filter(issueNeedsAssignee).map(issue => issue.id),
        [selectedIssues],
    );
    const selectedDoneBlockedIssueCount = useMemo(
        () => selectedIssues.filter(issue => issueDoneBlockers(issue).length > 0).length,
        [selectedIssues],
    );
    const selectedDoneBlockerText = useMemo(() => {
        const labels = new Set<string>();
        for (const issue of selectedIssues) {
            for (const blocker of issueDoneBlockers(issue)) labels.add(blocker);
        }
        return [...labels].join(', ');
    }, [selectedIssues]);
    const duplicateSuggestionByIssueId = useMemo(
        () => new Map(duplicateSuggestions.map(suggestion => [suggestion.issue.id, suggestion])),
        [duplicateSuggestions],
    );
    const mergeTargetOptions = useMemo(() => {
        if (!selectedIssue) return [];
        const selectedAccount = issueAccountKey(selectedIssue);
        const selectedContact = selectedIssue.contactEmail?.trim().toLowerCase();
        const score = (issue: SupportIssue) => {
            let value = 0;
            if (selectedContact && issue.contactEmail?.trim().toLowerCase() === selectedContact) value += 4;
            if (selectedAccount && issueAccountKey(issue) === selectedAccount) value += 2;
            if (issueWorkflowStatus(issue) !== 'done') value += 1;
            return value;
        };
        const byId = new Map<string, SupportIssue>();
        for (const suggestion of duplicateSuggestions) {
            if (suggestion.issue.id !== selectedIssue.id && !suggestion.issue.mergedIntoIssueId) {
                byId.set(suggestion.issue.id, suggestion.issue);
            }
        }
        for (const issue of issues) {
            if (issue.id !== selectedIssue.id && !issue.mergedIntoIssueId && !byId.has(issue.id)) {
                byId.set(issue.id, issue);
            }
        }
        return [...byId.values()]
            .sort((a, b) => {
                const suggestionDelta = (duplicateSuggestionByIssueId.get(b.id)?.score ?? 0)
                    - (duplicateSuggestionByIssueId.get(a.id)?.score ?? 0);
                if (suggestionDelta !== 0) return suggestionDelta;
                const scoreDelta = score(b) - score(a);
                if (scoreDelta !== 0) return scoreDelta;
                return (b.latestMessageAt || '').localeCompare(a.latestMessageAt || '');
            })
            .slice(0, 100);
    }, [duplicateSuggestionByIssueId, duplicateSuggestions, issues, selectedIssue]);
    const selectedMergeTarget = useMemo(
        () => mergeTargetOptions.find(issue => issue.id === mergeTargetIssueId) ?? null,
        [mergeTargetIssueId, mergeTargetOptions],
    );
    const selectedMergeSuggestion = useMemo(
        () => duplicateSuggestionByIssueId.get(mergeTargetIssueId) ?? null,
        [duplicateSuggestionByIssueId, mergeTargetIssueId],
    );

    const toggleIssueSelection = (issueIdToToggle: string, checked: boolean) => {
        setSelectedIssueIds(prev => {
            if (checked) {
                return prev.includes(issueIdToToggle) ? prev : [...prev, issueIdToToggle];
            }
            return prev.filter(id => id !== issueIdToToggle);
        });
    };

    const clearSelection = () => setSelectedIssueIds([]);

    const issueWithAgentAnswer = (issue: SupportIssue, answer: SupportAgentAnswer, mode: 'full' | 'aggregate'): SupportIssue => {
        const reply = answer.reply;
        const run = answer.run;
        const gap = answer.knowledgeGap ?? null;
        const appendedAgentMessages = [answer.userMessage, answer.assistantMessage]
            .filter((message): message is SupportAgentMessage => Boolean(message));
        const issueWithRun: SupportIssue = {
            ...issue,
            aiRuns: run ? [run, ...(issue.aiRuns ?? [])] : issue.aiRuns,
            agentMessages: answer.agentMessages ?? [...(issue.agentMessages ?? []), ...appendedAgentMessages],
            knowledgeGaps: gap ? [gap, ...(issue.knowledgeGaps ?? []).filter(item => item.id !== gap.id)] : issue.knowledgeGaps,
        };
        return reply
            ? mergeOutboundReplyIntoIssue(issueWithRun, reply, { mode })
            : issueWithRun;
    };

    const toggleApprovalQueueSelection = () => {
        if (approvalQueueFullySelected) {
            setSelectedIssueIds(prev => prev.filter(id => !approvalQueueIssueIds.includes(id)));
            return;
        }
        setSelectedIssueIds(prev => Array.from(new Set([...prev, ...approvalQueueIssueIds])));
    };

    const toggleLaneSelection = (lane: WorkflowLane, checked: boolean) => {
        const laneIds = boardGroups[lane].map(issue => issue.id);
        if (laneIds.length === 0) return;
        const laneIdSet = new Set(laneIds);
        setSelectedIssueIds(prev => {
            if (!checked) return prev.filter(id => !laneIdSet.has(id));
            const next = [...prev];
            for (const id of laneIds) {
                if (!next.includes(id)) next.push(id);
            }
            return next;
        });
    };

    const issueIdsForMove = useCallback((sourceIssueId: string) => {
        if (selectedIssueIdSet.has(sourceIssueId)) return selectedIssueIds;
        return [sourceIssueId];
    }, [selectedIssueIdSet, selectedIssueIds]);

    const openSaveViewDialog = () => {
        const selectedAccountName = accountFilterOptions.find(option => option.value === accountFilter)?.label || accountFilter;
        const selectedChannelName = channelOptions.find(option => option.value === channelFilter)?.label || channelFilter;
        const selectedAssigneeName = assigneeFilterOptions.find(email => email.toLowerCase() === assigneeFilter);
        const parts = [
            statusFilter !== 'all' ? inboxStatusFilterLabel(statusFilter, t) : '',
            queueFilter !== ALL_QUEUES_VALUE ? queueOptions.find(option => option.queueKey === queueFilter)?.name || queueFilter : '',
            accountFilter === NO_ACCOUNT_VALUE ? t('No account') : '',
            accountFilter !== ALL_ACCOUNTS_VALUE && accountFilter !== NO_ACCOUNT_VALUE ? selectedAccountName : '',
            channelFilter === NO_CHANNEL_VALUE ? t('No channel') : '',
            channelFilter !== ALL_CHANNELS_VALUE && channelFilter !== NO_CHANNEL_VALUE ? selectedChannelName : '',
            assigneeFilter === MY_ASSIGNEE_VALUE ? t('Mine') : '',
            assigneeFilter === UNASSIGNED_VALUE ? t('Unassigned') : '',
            assigneeFilter !== ALL_ASSIGNEES_VALUE && assigneeFilter !== MY_ASSIGNEE_VALUE && assigneeFilter !== UNASSIGNED_VALUE ? selectedAssigneeName || assigneeFilter : '',
            tagFilter !== ALL_TAGS_VALUE ? tagOptions.find(tag => tag.toLowerCase() === tagFilter) || tagFilter : '',
            query.trim(),
        ].filter(Boolean);
        setEditingViewId('');
        setViewName(parts.join(' / ') || t('Saved view'));
        setViewVisibility('private');
        setSaveViewOpen(true);
    };

    const openEditInboxViewDialog = (view: SupportInboxView) => {
        setEditingViewId(view.id);
        setViewName(view.name);
        setViewVisibility(view.visibility === 'shared' ? 'shared' : 'private');
        setSaveViewOpen(true);
    };

    const applyInboxView = (view: SupportInboxView) => {
        const filters = savedInboxFiltersFrom(view.filters);
        changeInboxFilters(filters);
    };

    const canManageInboxView = (view: SupportInboxView) => {
        const owner = (view.ownerEmail || '').trim().toLowerCase();
        const current = currentUserEmail.trim().toLowerCase();
        return !owner || !current || owner === current;
    };

    const canManageReplyMacro = (macro: SupportReplyMacro) => {
        const owner = (macro.ownerEmail || '').trim().toLowerCase();
        const current = currentUserEmail.trim().toLowerCase();
        return !owner || !current || owner === current;
    };

    const saveCurrentInboxView = async () => {
        const name = viewName.trim();
        if (!name) {
            toast.error(t('View name is required'));
            return;
        }
        setSavingView(true);
        const editingView = inboxViews.find(view => view.id === editingViewId) ?? null;
        const res = await api.saveInboxView(projectId, {
            id: editingViewId || undefined,
            name,
            visibility: viewVisibility,
            filters: currentInboxFilters(),
            sortOrder: editingView?.sortOrder ?? inboxViews.length + 1,
        });
        setSavingView(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not save view'));
            return;
        }
        setInboxViews(prev => {
            const saved = res.data!;
            const withoutSaved = prev.filter(view => view.id !== saved.id);
            if (!editingViewId) return [saved, ...withoutSaved];
            const existingIndex = prev.findIndex(view => view.id === saved.id);
            if (existingIndex < 0) return [saved, ...withoutSaved];
            const next = [...withoutSaved];
            next.splice(existingIndex, 0, saved);
            return next;
        });
        setSaveViewOpen(false);
        setEditingViewId('');
        toast.success(t('Saved'));
    };

    const deleteSavedView = async (view: SupportInboxView) => {
        if (deletingViewId) return;
        setDeletingViewId(view.id);
        const res = await api.deleteInboxView(projectId, view.id);
        setDeletingViewId('');
        if (res.error) {
            toast.error(res.error || t('Could not delete view'));
            return;
        }
        setInboxViews(prev => prev.filter(item => item.id !== view.id));
    };

    const applyReplyMacro = async (mode: 'append' | 'replace') => {
        if (!selectedReplyMacro) {
            toast.error(t('Select a macro'));
            return;
        }
        setRenderingMacroId(selectedReplyMacro.id);
        let renderedBody = '';
        let unresolved: string[] = [];
        try {
            if (selectedIssue) {
                const res = await api.renderReplyMacro(projectId, selectedReplyMacro.id, selectedIssue.id);
                if (!res.error && res.data) {
                    renderedBody = res.data.body;
                    unresolved = res.data.unresolvedVariables;
                }
            }
        } finally {
            setRenderingMacroId('');
        }
        if (!renderedBody) {
            renderedBody = renderReplyMacroBody(selectedReplyMacro.body, {
                issue: selectedIssue,
                account: ticketAccount,
                currentUserEmail,
            });
            unresolved = unresolvedReplyMacroTokens(renderedBody);
        }
        setReplyDraft(prev => mode === 'replace'
            ? renderedBody
            : [prev.trim(), renderedBody].filter(Boolean).join('\n\n'));
        setReplyRequiresApproval(true);
        if (unresolved.length > 0) {
            toast.warning(t('Macro inserted with unresolved variables'));
            return;
        }
        toast.success(t('Macro inserted'));
    };

    const openSaveMacroDialog = () => {
        const body = replyDraft.trim();
        if (!body) {
            toast.error(t('Reply is empty'));
            return;
        }
        setMacroTitleDraft(selectedIssue?.subject || t('Reply macro'));
        setMacroVisibilityDraft('shared');
        setMacroTagsDraft((selectedIssue?.tags ?? []).join(', '));
        setSaveMacroOpen(true);
    };

    const saveReplyMacro = async () => {
        const title = macroTitleDraft.trim();
        const body = replyDraft.trim();
        if (!title || !body || savingMacro) return;
        setSavingMacro(true);
        const res = await api.saveReplyMacro(projectId, {
            title,
            body,
            visibility: macroVisibilityDraft,
            status: 'active',
            tags: parseIssueTags(macroTagsDraft),
        });
        setSavingMacro(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not save macro'));
            return;
        }
        setReplyMacros(prev => [res.data!, ...prev.filter(macro => macro.id !== res.data?.id)]
            .sort((a, b) => a.title.localeCompare(b.title)));
        setSelectedReplyMacroId(res.data.id);
        setSaveMacroOpen(false);
        toast.success(t('Macro saved'));
    };

    const archiveSelectedReplyMacro = async () => {
        if (!selectedReplyMacro || archivingMacroId) return;
        if (!canManageReplyMacro(selectedReplyMacro)) {
            toast.error(t('Only the owner can archive this macro'));
            return;
        }
        setArchivingMacroId(selectedReplyMacro.id);
        const res = await api.deleteReplyMacro(projectId, selectedReplyMacro.id);
        setArchivingMacroId('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not archive macro'));
            return;
        }
        setReplyMacros(prev => prev.filter(macro => macro.id !== selectedReplyMacro.id));
        setSelectedReplyMacroId(NO_REPLY_MACRO_VALUE);
        toast.success(t('Macro archived'));
    };

    const refreshInboxNow = async () => {
        if (refreshingInbox) return;
        setRefreshingInbox(true);
        const refreshed = await refreshInboxData();
        setRefreshingInbox(false);
        if (refreshed) {
            toast.success(t('Inbox refreshed'));
            return;
        }
        toast.error(t('Could not refresh inbox'));
    };

    const openNotification = async (notification: SupportNotification) => {
        if (basePath && notification.issueId) {
            void navigate(`${basePath}/${notification.issueId}`);
        }
        setNotifications(prev => prev.filter(item => item.id !== notification.id));
        const res = await api.markNotificationRead(projectId, notification.id);
        if (res.error) {
            toast.error(res.error || t('Could not update notification'));
            void loadNotifications();
        }
    };

    const mergeWatcher = (watcher: SupportWatcher, active: boolean) => {
        setSelectedIssue(prev => {
            if (!prev) return prev;
            const existing = prev.watchers ?? [];
            if (!active) {
                return {
                    ...prev,
                    watchers: existing.filter(item => item.id !== watcher.id && item.watcherEmail !== watcher.watcherEmail),
                };
            }
            const next = existing.some(item => item.id === watcher.id || item.watcherEmail === watcher.watcherEmail)
                ? existing.map(item => item.id === watcher.id || item.watcherEmail === watcher.watcherEmail ? watcher : item)
                : [...existing, watcher];
            return { ...prev, watchers: next };
        });
    };

    const toggleWatching = async () => {
        if (!selectedIssue || !currentUserEmail.trim() || togglingWatcher) return;
        setTogglingWatcher(true);
        const res = currentWatcher
            ? await api.unwatchIssue(projectId, selectedIssue.id)
            : await api.watchIssue(projectId, selectedIssue.id);
        setTogglingWatcher(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not update watchers'));
            return;
        }
        mergeWatcher(res.data, !currentWatcher);
    };

    const openMergeDialog = (targetIssueId = '') => {
        if (!selectedIssue) return;
        setMergeTargetIssueId(targetIssueId || mergeTargetOptions[0]?.id || '');
        setMergeNote('');
        setMergeOpen(true);
    };

    const mergeSelectedIssue = async () => {
        if (!selectedIssue || !mergeTargetIssueId || mergingIssue) return;
        const sourceIssueId = selectedIssue.id;
        setMergingIssue(true);
        const res = await api.mergeIssue(projectId, sourceIssueId, mergeTargetIssueId, mergeNote.trim());
        setMergingIssue(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not merge tickets'));
            return;
        }
        const target = res.data;
        setIssues(prev => {
            const withoutSource = prev.filter(issue => issue.id !== sourceIssueId);
            return withoutSource.some(issue => issue.id === target.id)
                ? withoutSource.map(issue => issue.id === target.id ? { ...issue, ...target } : issue)
                : [target, ...withoutSource];
        });
        setSelectedIssue(target);
        setAssigneeDraft(target.assigneeEmail || '');
        setTagDraft((target.tags ?? []).join(', '));
        setReplyDraft(target.draftReply || '');
        setSelectedIssueIds(prev => prev.filter(id => id !== sourceIssueId));
        setMergeOpen(false);
        toast.success(t('Tickets merged'));
        navigateToIssue(target.id, { viewMode: 'list' });
    };

    const openSplitMessageDialog = (message: SupportIssueMessage) => {
        if (!selectedIssue || !canSplitTimelineMessage(message, selectedMessages.length)) return;
        setSplitMessageTarget(message);
        setSplitMessageSubject(defaultSplitSubject(selectedIssue, message));
        setSplitMessageNote('');
        setSplitMessageOpen(true);
    };

    const closeSplitMessageDialog = () => {
        if (splittingMessageId) return;
        setSplitMessageOpen(false);
        setSplitMessageTarget(null);
        setSplitMessageSubject('');
        setSplitMessageNote('');
    };

    const splitMessageToTicket = async () => {
        if (!selectedIssue || !splitMessageTarget || splittingMessageId) return;
        const splitId = messageIdentifier(splitMessageTarget);
        if (!splitId) return;
        const sourceIssue = selectedIssue;
        const sourceIssueId = sourceIssue.id;
        setSplittingMessageId(splitId);
        const res = await api.splitIssueMessage(projectId, sourceIssueId, {
            messageId: splitId,
            subject: splitMessageSubject.trim(),
            note: splitMessageNote.trim(),
            runAutomations: true,
        });
        setSplittingMessageId('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not split message'));
            return;
        }
        const newIssue = res.data;
        const remainingMessages = selectedMessages.filter(message => !sameTimelineMessage(message, splitMessageTarget));
        const updatedSource: SupportIssue = {
            ...sourceIssue,
            messages: remainingMessages,
            messageCount: remainingMessages.length,
            latestMessageAt: latestTimelineMessageAt(remainingMessages) || sourceIssue.latestMessageAt,
        };
        setIssues(prev => {
            const withoutNew = prev.filter(issue => issue.id !== newIssue.id);
            const withSource = withoutNew.map(issue => issue.id === sourceIssueId ? { ...issue, ...updatedSource } : issue);
            return [newIssue, ...withSource];
        });
        setSelectedIssue(newIssue);
        setAssigneeDraft(newIssue.assigneeEmail || '');
        setTagDraft((newIssue.tags ?? []).join(', '));
        setReplyDraft(newIssue.draftReply || '');
        setSelectedIssueIds(prev => prev.filter(id => id !== sourceIssueId));
        setSplitMessageOpen(false);
        setSplitMessageTarget(null);
        setSplitMessageSubject('');
        setSplitMessageNote('');
        toast.success(t('Message split to new ticket'));
        navigateToIssue(newIssue.id, { viewMode: 'list' });
    };

    const bulkPatchIssues = async (data: IssuePatch) => {
        if (selectedIssueIds.length === 0 || bulkUpdating) return;
        const updates = { ...data };
        const nextStatus = data.status ? normalizeWorkflowStatus(data.status) : '';
        if (nextStatus === 'done') {
            const blockedIssues = selectedIssues.filter(issue => issueDoneBlockers(issue).length > 0);
            if (blockedIssues.length > 0) {
                const blockers = selectedDoneBlockerText || t('open blockers');
                toast.error(`${blockedIssues.length} ${t('tickets cannot close')}: ${blockers}`);
                return;
            }
        }
        if (nextStatus && statusNeedsAssignee(nextStatus)) {
            const hasUnassignedTarget = selectedIssues.some(issue => {
                const nextAssignee = 'assigneeEmail' in data ? data.assigneeEmail : issue.assigneeEmail;
                return !nextAssignee?.trim();
            });
            if (hasUnassignedTarget) {
                const claimedAssignee = currentUserEmail.trim();
                if (!claimedAssignee) {
                    toast.error(t('Assign the ticket before changing status.'));
                    return;
                }
                updates.assigneeEmail = claimedAssignee;
            }
        }
        if (data.status && !updates.workflowSource) {
            updates.workflowSource = 'inbox_bulk';
        }

        setBulkUpdating(true);
        const res = await api.bulkUpdateIssues(projectId, selectedIssueIds, updates);
        setBulkUpdating(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not update tickets'));
            return;
        }

        const updatedById = new Map(res.data.items.map(issue => [issue.id, issue]));
        setIssues(prev => prev.map(issue => {
            const updated = updatedById.get(issue.id);
            return updated ? { ...issue, ...updated } : issue;
        }));
        setSelectedIssue(prev => {
            if (!prev) return prev;
            const updated = updatedById.get(prev.id);
            return updated ? { ...prev, ...updated } : prev;
        });
        if (selectedIssue && updatedById.has(selectedIssue.id)) {
            setAssigneeDraft(updatedById.get(selectedIssue.id)?.assigneeEmail || '');
        }
        setSelectedIssueIds(prev => prev.filter(id => !updatedById.has(id)));

        if (res.data.failed.length > 0) {
            toast.error(`${res.data.failed.length} ${t('ticket updates failed')}`);
            return;
        }
        toast.success(t('Tickets updated'));
    };

    const applyBulkIssueUpdates = (updatedIssues: SupportIssue[]) => {
        const updatedById = new Map(updatedIssues.map(issue => [issue.id, issue]));
        setIssues(prev => prev.map(issue => {
            const updated = updatedById.get(issue.id);
            return updated ? { ...issue, ...updated } : issue;
        }));
        setSelectedIssue(prev => {
            if (!prev) return prev;
            const updated = updatedById.get(prev.id);
            return updated ? { ...prev, ...updated } : prev;
        });
        if (selectedIssue && updatedById.has(selectedIssue.id)) {
            const updated = updatedById.get(selectedIssue.id);
            setAssigneeDraft(updated?.assigneeEmail || '');
            setReplyDraft(updated?.draftReply || '');
        }
    };

    const bulkUpdateLabels = async (mode: 'add' | 'remove') => {
        if (selectedIssueIds.length === 0 || bulkLabelingMode) return;
        const tags = parseIssueTags(bulkLabelDraft);
        if (tags.length === 0) {
            toast.error(t('Add at least one label'));
            return;
        }
        setBulkLabelingMode(mode);
        const res = mode === 'add'
            ? await api.bulkAddIssueLabels(projectId, selectedIssueIds, tags)
            : await api.bulkRemoveIssueLabels(projectId, selectedIssueIds, tags);
        setBulkLabelingMode('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not update tickets'));
            return;
        }
        applyBulkIssueUpdates(res.data.items);
        const updatedIds = new Set(res.data.items.map(issue => issue.id));
        setSelectedIssueIds(prev => prev.filter(id => !updatedIds.has(id)));
        setBulkLabelDraft('');
        if (res.data.failed.length > 0) {
            toast.error(`${res.data.failed.length} ${t('ticket updates failed')}`);
            return;
        }
        toast.success(t('Tickets updated'));
    };

    const bulkApproveSelectedReplies = async () => {
        if (selectedReplyApprovalIssueIds.length === 0 || bulkApprovingReplies || bulkRequestingReplyChanges || bulkRetryingFailedReplies || bulkReviewingActions) return;
        setBulkApprovingReplies(true);
        const res = await api.bulkApproveIssueReplies(projectId, selectedReplyApprovalIssueIds);
        setBulkApprovingReplies(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not approve replies'));
            return;
        }

        applyBulkIssueUpdates(res.data.issues);

        const clearedIds = new Set(res.data.issues.filter(issue => !issueNeedsApproval(issue)).map(issue => issue.id));
        setSelectedIssueIds(prev => prev.filter(id => !clearedIds.has(id)));

        const approved = res.data.approved ?? res.data.processed;
        if (approved > 0) {
            toast.success(`${approved} ${t('replies approved')}`);
        }
        if (res.data.failed.length > 0) {
            toast.error(`${res.data.failed.length} ${t('approvals failed')}`);
        }
    };

    const bulkApproveSendSelectedReplies = async () => {
        if (selectedReplyApprovalIssueIds.length === 0 || bulkApprovingReplies || bulkRequestingReplyChanges || bulkRetryingFailedReplies || bulkReviewingActions) return;
        if (bulkApproveSendBlocked) {
            toast.error(selectedReplySendBlockDetail || t('Reply channel is blocked'));
            return;
        }
        setBulkApprovingReplies(true);
        const res = await api.bulkApproveSendIssueReplies(projectId, selectedReplyApprovalIssueIds);
        setBulkApprovingReplies(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not approve replies'));
            return;
        }

        applyBulkIssueUpdates(res.data.issues);

        const clearedIds = new Set(res.data.issues.filter(issue => !issueNeedsApproval(issue)).map(issue => issue.id));
        setSelectedIssueIds(prev => prev.filter(id => !clearedIds.has(id)));

        if (res.data.sent > 0) {
            toast.success(`${res.data.sent} ${t('replies sent')}`);
        }
        if (res.data.failed.length > 0) {
            toast.error(`${res.data.failed.length} ${t('approval sends failed')}`);
        }
    };

    const openBulkRequestReplyChangesDialog = () => {
        if (selectedReplyApprovalIssueIds.length === 0 || bulkApprovingReplies || bulkRequestingReplyChanges || bulkRetryingFailedReplies || bulkReviewingActions) return;
        setBulkRequestReplyChangesNote('');
        setBulkRequestReplyChangesOpen(true);
    };

    const bulkRequestSelectedReplyChanges = async () => {
        if (selectedReplyApprovalIssueIds.length === 0 || bulkApprovingReplies || bulkRequestingReplyChanges || bulkRetryingFailedReplies || bulkReviewingActions) return;
        setBulkRequestingReplyChanges(true);
        const res = await api.bulkRequestIssueReplyChanges(projectId, selectedReplyApprovalIssueIds, bulkRequestReplyChangesNote.trim());
        setBulkRequestingReplyChanges(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not request changes'));
            return;
        }

        applyBulkIssueUpdates(res.data.issues);

        const clearedIds = new Set(res.data.issues.filter(issue => !issueNeedsApproval(issue)).map(issue => issue.id));
        setSelectedIssueIds(prev => prev.filter(id => !clearedIds.has(id)));

        const requested = res.data.changesRequested ?? res.data.processed;
        if (requested > 0) {
            toast.success(`${requested} ${t('change requests sent')}`);
            setBulkRequestReplyChangesOpen(false);
            setBulkRequestReplyChangesNote('');
        }
        if (res.data.failed.length > 0) {
            toast.error(`${res.data.failed.length} ${t('change requests failed')}`);
        }
    };

    const bulkApproveSelectedActions = async () => {
        if (selectedActionApprovalIssueIds.length === 0 || bulkReviewingActions || bulkApprovingReplies || bulkRequestingReplyChanges || bulkRetryingFailedReplies) return;
        setBulkReviewingActions('approve');
        const res = await api.bulkApproveIssueActions(projectId, selectedActionApprovalIssueIds);
        setBulkReviewingActions('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not approve actions'));
            return;
        }

        applyBulkIssueUpdates(res.data.issues);

        const clearedIds = new Set(res.data.issues.filter(issue => !issueNeedsApproval(issue)).map(issue => issue.id));
        setSelectedIssueIds(prev => prev.filter(id => !clearedIds.has(id)));

        const approved = res.data.approved ?? res.data.processed;
        if (approved > 0) {
            toast.success(`${approved} ${t('actions approved')}`);
        }
        if (res.data.failed.length > 0) {
            toast.error(`${res.data.failed.length} ${t('action approvals failed')}`);
        }
    };

    const openBulkRejectActionsDialog = () => {
        if (selectedActionApprovalIssueIds.length === 0 || bulkReviewingActions || bulkApprovingReplies || bulkRequestingReplyChanges || bulkRetryingFailedReplies) return;
        setBulkRejectActionsNote('');
        setBulkRejectActionsOpen(true);
    };

    const bulkRejectSelectedActions = async () => {
        if (selectedActionApprovalIssueIds.length === 0 || bulkReviewingActions || bulkApprovingReplies || bulkRequestingReplyChanges || bulkRetryingFailedReplies) return;
        setBulkReviewingActions('reject');
        const res = await api.bulkRejectIssueActions(projectId, selectedActionApprovalIssueIds, bulkRejectActionsNote.trim());
        setBulkReviewingActions('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not reject actions'));
            return;
        }

        applyBulkIssueUpdates(res.data.issues);

        const clearedIds = new Set(res.data.issues.filter(issue => !issueNeedsApproval(issue)).map(issue => issue.id));
        setSelectedIssueIds(prev => prev.filter(id => !clearedIds.has(id)));

        const rejected = res.data.rejected ?? res.data.processed;
        if (rejected > 0) {
            toast.success(`${rejected} ${t('actions rejected')}`);
            setBulkRejectActionsOpen(false);
            setBulkRejectActionsNote('');
        }
        if (res.data.failed.length > 0) {
            toast.error(`${res.data.failed.length} ${t('action rejections failed')}`);
        }
    };

    const reviewSelectedIssuePackage = async (mode: 'approve' | 'approve-send') => {
        if (!selectedIssue || pendingReviewCount === 0 || reviewPackageBusy || bulkApprovingReplies || bulkRequestingReplyChanges || bulkReviewingActions || bulkRetryingFailedReplies) return;
        if (mode === 'approve-send' && selectedReplySendBlocked) {
            toast.error(selectedReplySendBlockDetail || t('Reply channel is blocked'));
            return;
        }
        const issueIds = [selectedIssue.id];
        setReviewingPackageMode(mode);
        let failed = 0;
        let approvedActions = 0;
        let approvedReplies = 0;
        let sentReplies = 0;
        try {
            if (pendingReviewActions.length > 0) {
                const actionRes = await api.bulkApproveIssueActions(projectId, issueIds);
                if (actionRes.error || !actionRes.data) {
                    toast.error(actionRes.error || t('Could not approve actions'));
                    return;
                }
                applyBulkIssueUpdates(actionRes.data.issues);
                approvedActions = actionRes.data.approved ?? actionRes.data.processed;
                failed += actionRes.data.failed.length;
            }

            if (pendingReviewReplies.length > 0) {
                const replyRes = mode === 'approve-send'
                    ? await api.bulkApproveSendIssueReplies(projectId, issueIds)
                    : await api.bulkApproveIssueReplies(projectId, issueIds);
                if (replyRes.error || !replyRes.data) {
                    toast.error(replyRes.error || t('Could not approve replies'));
                    return;
                }
                applyBulkIssueUpdates(replyRes.data.issues);
                approvedReplies = replyRes.data.approved ?? replyRes.data.processed;
                sentReplies = replyRes.data.sent;
                failed += replyRes.data.failed.length;
            }

            const reviewed = approvedActions + approvedReplies;
            if (sentReplies > 0) {
                toast.success(`${sentReplies} ${t('replies sent')}`);
            } else if (reviewed > 0) {
                toast.success(`${reviewed} ${t('items approved')}`);
            }
            if (failed > 0) {
                toast.error(`${failed} ${t('package items failed')}`);
            }
        } finally {
            setReviewingPackageMode('');
        }
    };

    const bulkRetryFailedSelectedReplies = async () => {
        if (selectedFailedDeliveryIssueIds.length === 0 || bulkRetryingFailedReplies || bulkApprovingReplies || bulkReviewingActions) return;
        setBulkRetryingFailedReplies(true);
        const res = await api.bulkRetryFailedIssueReplies(projectId, selectedFailedDeliveryIssueIds);
        setBulkRetryingFailedReplies(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not retry failed replies'));
            return;
        }

        const updatedById = new Map(res.data.issues.map(issue => [issue.id, issue]));
        setIssues(prev => prev.map(issue => {
            const updated = updatedById.get(issue.id);
            return updated ? { ...issue, ...updated } : issue;
        }));
        setSelectedIssue(prev => {
            if (!prev) return prev;
            const updated = updatedById.get(prev.id);
            return updated ? { ...prev, ...updated } : prev;
        });
        if (selectedIssue && updatedById.has(selectedIssue.id)) {
            const updated = updatedById.get(selectedIssue.id);
            setAssigneeDraft(updated?.assigneeEmail || '');
            setReplyDraft(updated?.draftReply || '');
        }

        const clearedIds = new Set(res.data.issues.filter(issue => !issueHasFailedDelivery(issue)).map(issue => issue.id));
        setSelectedIssueIds(prev => prev.filter(id => !clearedIds.has(id)));

        if (res.data.sent > 0) {
            toast.success(`${res.data.sent} ${t('replies sent')}`);
        }
        if (res.data.failed.length > 0) {
            toast.error(`${res.data.failed.length} ${t('retries failed')}`);
        }
    };

    const retryFailedRepliesForIssue = async (issue: SupportIssue) => {
        if (ticketNextActionBusy || bulkRetryingFailedReplies || bulkApprovingReplies || bulkReviewingActions) return;
        setTicketNextActionBusy(`${issue.id}:retry`);
        const res = await api.bulkRetryFailedIssueReplies(projectId, [issue.id]);
        setTicketNextActionBusy('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not retry failed replies'));
            return;
        }
        applyBulkIssueUpdates(res.data.issues);
        if (res.data.sent > 0) {
            toast.success(t('Reply sent'));
        }
        if (res.data.failed.length > 0) {
            toast.error(t('Retry failed'));
        }
    };

    const runDeliveryForIssue = async (issue: SupportIssue) => {
        if (ticketNextActionBusy) return;
        setTicketNextActionBusy(`${issue.id}:delivery`);
        const res = await api.runSupportDelivery(projectId, 25, false);
        if (res.error || !res.data) {
            setTicketNextActionBusy('');
            toast.error(res.error || t('Could not run delivery'));
            return;
        }
        await refreshInboxData();
        setTicketNextActionBusy('');
        if (res.data.sent > 0) {
            toast.success(t('Delivery run sent replies'));
        } else if ((res.data.deferred ?? 0) > 0) {
            toast.success(t('Delivery still deferred'));
        } else {
            toast.success(t('Delivery checked'));
        }
    };

    const openReviewPackage = () => {
        document.querySelector<HTMLElement>('[data-ticket-review-package]')?.scrollIntoView({
            behavior: 'smooth',
            block: 'start',
        });
    };

    const startSlaWorkForIssue = async (issue: SupportIssue, mode: 'overdue' | 'due-soon') => {
        if (ticketNextActionBusy) return;
        const ownerEmail = issue.assigneeEmail || currentUserEmail.trim();
        if (!ownerEmail) {
            toast.error(t('Assign the ticket before changing status.'));
            return;
        }
        const tag = slaWorkTag(mode);
        const tags = (issue.tags ?? []).some(item => item.toLowerCase() === tag)
            ? issue.tags
            : [...(issue.tags ?? []), tag];
        const priority = slaWorkPriority(issue, mode);
        const noteBody = slaWorkNoteBody(mode, 'single');

        setTicketNextActionBusy(`${issue.id}:sla`);
        const updated = await api.updateIssue(projectId, issue.id, {
            status: 'ongoing',
            priority,
            assigneeEmail: ownerEmail,
            tags,
            workflowSource: slaWorkSource(mode, 'single'),
        });
        if (updated.error || !updated.data) {
            setTicketNextActionBusy('');
            toast.error(updated.error || t('Could not update ticket'));
            return;
        }

        applyBulkIssueUpdates([updated.data]);
        const note = await api.createIssueNote(projectId, issue.id, noteBody);
        setTicketNextActionBusy('');
        if (note.data) {
            setSelectedIssue(prev => prev?.id === issue.id ? {
                ...prev,
                notes: [...(prev.notes ?? []), note.data!],
            } : prev);
        }
        if (note.error) {
            toast.error(note.error || t('Could not save note'));
            return;
        }
        toast.success(mode === 'overdue' ? t('SLA escalated') : t('SLA watch started'));
    };

    const startSlaWorkForSelectedTickets = async (mode: 'overdue' | 'due-soon') => {
        const targetIssues = mode === 'overdue' ? selectedOverdueSlaIssues : selectedDueSoonSlaIssues;
        const ownerFallback = currentUserEmail.trim();
        if (
            targetIssues.length === 0
            || bulkUpdating
            || bulkApprovingReplies
            || bulkRequestingReplyChanges
            || bulkRetryingFailedReplies
            || bulkReviewingActions
        ) return;
        if (!ownerFallback && targetIssues.some(issue => !issue.assigneeEmail)) {
            toast.error(t('Assign the ticket before changing status.'));
            return;
        }

        setBulkUpdating(true);
        const updatedIssues: SupportIssue[] = [];
        const failed: Array<{ id: string; error: string }> = [];
        let noteFailures = 0;
        for (const issue of targetIssues) {
            const ownerEmail = issue.assigneeEmail || ownerFallback;
            const tag = slaWorkTag(mode);
            const tags = (issue.tags ?? []).some(item => item.toLowerCase() === tag)
                ? issue.tags
                : [...(issue.tags ?? []), tag];
            const updated = await api.updateIssue(projectId, issue.id, {
                status: 'ongoing',
                priority: slaWorkPriority(issue, mode),
                assigneeEmail: ownerEmail,
                tags,
                workflowSource: slaWorkSource(mode, 'bulk'),
            });
            if (updated.error || !updated.data) {
                failed.push({ id: issue.id, error: updated.error || t('Could not update ticket') });
                continue;
            }
            updatedIssues.push(updated.data);
            const note = await api.createIssueNote(projectId, issue.id, slaWorkNoteBody(mode, 'bulk'));
            if (note.data) {
                setSelectedIssue(prev => prev?.id === issue.id ? {
                    ...prev,
                    notes: [...(prev.notes ?? []), note.data!],
                } : prev);
            } else if (note.error) {
                noteFailures += 1;
            }
        }
        setBulkUpdating(false);

        if (updatedIssues.length > 0) {
            applyBulkIssueUpdates(updatedIssues);
            const updatedIds = new Set(updatedIssues.map(issue => issue.id));
            setSelectedIssueIds(prev => prev.filter(id => !updatedIds.has(id)));
            toast.success(`${updatedIssues.length} ${mode === 'overdue' ? t('SLA escalated') : t('SLA watch started')}`);
        }
        if (failed.length > 0) {
            toast.error(`${failed.length} ${t('ticket updates failed')}`);
        }
        if (noteFailures > 0) {
            toast.error(`${noteFailures} ${t('notes failed')}`);
        }
    };

    const bulkClaimSelectedTickets = async () => {
        const claimedAssignee = currentUserEmail.trim();
        if (
            selectedUnassignedIssueIds.length === 0
            || !claimedAssignee
            || bulkUpdating
            || bulkApprovingReplies
            || bulkRetryingFailedReplies
            || bulkFindingKnowledgeGaps
            || bulkReviewingActions
        ) return;

        setBulkUpdating(true);
        const res = await api.bulkUpdateIssues(projectId, selectedUnassignedIssueIds, {
            assigneeEmail: claimedAssignee,
            workflowSource: 'inbox_bulk_claim',
        });
        setBulkUpdating(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not assign tickets'));
            return;
        }

        applyBulkIssueUpdates(res.data.items);
        const updatedIds = new Set(res.data.items.map(issue => issue.id));
        setSelectedIssueIds(prev => prev.filter(id => !updatedIds.has(id)));

        if (res.data.failed.length > 0) {
            toast.error(`${res.data.failed.length} ${t('ticket updates failed')}`);
            return;
        }
        toast.success(`${updatedIds.size} ${t('tickets claimed')}`);
    };

    const bulkPrepareAgentReplies = async () => {
        if (
            selectedAgentReplyPrepIssues.length === 0
            || bulkPreparingAgentReplies
            || bulkFindingKnowledgeGaps
            || bulkUpdating
            || bulkApprovingReplies
            || bulkRequestingReplyChanges
            || bulkRetryingFailedReplies
            || bulkReviewingActions
        ) return;
        const question = agentQuickActions.find(action => action.key === 'prepare-reply')?.question
            || 'Draft an approval-ready customer reply using the ticket context and knowledge base.';
        setBulkPreparingAgentReplies(true);
        const answers = new Map<string, SupportAgentAnswer>();
        const failed: Array<{ id: string; error: string }> = [];
        for (const issue of selectedAgentReplyPrepIssues) {
            const res = await api.askIssueAgent(
                projectId,
                issue.id,
                question,
                true,
                replyIncludeFeedbackLink,
                true,
                false,
            );
            if (res.error || !res.data) {
                failed.push({ id: issue.id, error: res.error || t('Could not ask agent') });
                continue;
            }
            answers.set(issue.id, res.data);
        }
        setBulkPreparingAgentReplies(false);
        if (answers.size > 0) {
            setIssues(prev => prev.map(issue => {
                const answer = answers.get(issue.id);
                return answer ? issueWithAgentAnswer(issue, answer, 'aggregate') : issue;
            }));
            setSelectedIssue(prev => {
                if (!prev) return prev;
                const answer = answers.get(prev.id);
                return answer ? issueWithAgentAnswer(prev, answer, 'full') : prev;
            });
            if (selectedIssue) {
                const selectedAnswer = answers.get(selectedIssue.id);
                if (selectedAnswer) {
                    setAgentAnswer(selectedAnswer);
                    if (selectedAnswer.reply) {
                        setReplyDraft(selectedAnswer.answer);
                        setReplyRequiresApproval(Boolean(selectedAnswer.approvalRequired));
                    }
                    void refreshAnswerWorkspace(selectedIssue.id);
                }
            }
            setSelectedIssueIds(prev => prev.filter(id => !answers.has(id)));
            toast.success(`${answers.size} ${t('reply drafts prepared')}`);
        }
        if (failed.length > 0) {
            toast.error(`${failed.length} ${t('agent drafts failed')}`);
        }
    };

    const bulkFindKnowledgeGaps = async () => {
        if (
            selectedKnowledgeGapScanIssues.length === 0
            || bulkFindingKnowledgeGaps
            || bulkPreparingAgentReplies
            || bulkUpdating
            || bulkApprovingReplies
            || bulkRequestingReplyChanges
            || bulkRetryingFailedReplies
            || bulkReviewingActions
        ) return;
        const question = agentQuickActions.find(action => action.key === 'knowledge-gaps')?.question
            || 'Identify missing knowledge articles, account context, or runbook steps that block a confident answer.';
        setBulkFindingKnowledgeGaps(true);
        const answers = new Map<string, SupportAgentAnswer>();
        const failed: Array<{ id: string; error: string }> = [];
        for (const issue of selectedKnowledgeGapScanIssues) {
            const res = await api.askIssueAgent(
                projectId,
                issue.id,
                question,
                false,
                false,
                true,
                false,
            );
            if (res.error || !res.data) {
                failed.push({ id: issue.id, error: res.error || t('Could not ask agent') });
                continue;
            }
            answers.set(issue.id, res.data);
        }
        setBulkFindingKnowledgeGaps(false);
        if (answers.size > 0) {
            setIssues(prev => prev.map(issue => {
                const answer = answers.get(issue.id);
                return answer ? issueWithAgentAnswer(issue, answer, 'aggregate') : issue;
            }));
            setSelectedIssue(prev => {
                if (!prev) return prev;
                const answer = answers.get(prev.id);
                return answer ? issueWithAgentAnswer(prev, answer, 'full') : prev;
            });
            if (selectedIssue) {
                const selectedAnswer = answers.get(selectedIssue.id);
                if (selectedAnswer) {
                    setAgentAnswer(selectedAnswer);
                    void refreshAnswerWorkspace(selectedIssue.id);
                }
            }
            setSelectedIssueIds(prev => prev.filter(id => !answers.has(id)));
            toast.success(`${answers.size} ${t('knowledge gaps scanned')}`);
        }
        if (failed.length > 0) {
            toast.error(`${failed.length} ${t('knowledge scans failed')}`);
        }
    };

    const openCloseWithoutReplyDialog = () => {
        if (!selectedIssue || !issueCanResolveWithoutReply(selectedIssue)) return;
        setCloseWithoutReplyNote('');
        setCloseWithoutReplyOpen(true);
    };

    const closeSelectedIssueWithoutReply = async () => {
        if (!selectedIssue || closingWithoutReply) return;
        if (!issueCanResolveWithoutReply(selectedIssue)) {
            toast.error(t('Resolve pending approvals or delivery problems before closing.'));
            return;
        }
        const resolutionNote = closeWithoutReplyNote.trim();
        if (!resolutionNote) {
            toast.error(t('Add a resolution note before closing without a reply.'));
            return;
        }
        setClosingWithoutReply(true);
        const res = await api.updateIssue(projectId, selectedIssue.id, {
            status: 'done',
            workflowSource: 'inbox_close_without_reply',
            resolveWithoutReply: true,
            resolutionNote,
        });
        setClosingWithoutReply(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not close ticket without a reply'));
            return;
        }
        setSelectedIssue(prev => prev ? { ...prev, ...res.data } : res.data);
        setIssues(prev => prev.map(issue => issue.id === res.data?.id ? { ...issue, ...res.data } : issue));
        setCloseWithoutReplyOpen(false);
        setCloseWithoutReplyNote('');
        toast.success(t('Ticket closed without a reply'));
    };

    const patchSelectedIssue = async (data: IssuePatch) => {
        if (!selectedIssue) return;
        const updates = { ...data };
        const nextStatus = data.status ? normalizeWorkflowStatus(data.status) : issueWorkflowStatus(selectedIssue);
        if (nextStatus === 'done') {
            const blockers = issueDoneBlockerText(selectedIssue);
            if (blockers) {
                toast.error(`${t('Resolve before closing')}: ${blockers}`);
                return;
            }
        }
        const nextAssignee = 'assigneeEmail' in data ? data.assigneeEmail : selectedIssue.assigneeEmail;
        if (statusNeedsAssignee(nextStatus) && !nextAssignee?.trim()) {
            const claimedAssignee = currentUserEmail.trim();
            if (!claimedAssignee) {
                toast.error(t('Assign the ticket before changing status.'));
                return;
            }
            updates.assigneeEmail = claimedAssignee;
            setAssigneeDraft(claimedAssignee);
        }
        if (data.status && !updates.workflowSource) {
            updates.workflowSource = 'inbox_detail';
        }
        const res = await api.updateIssue(projectId, selectedIssue.id, updates);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not update ticket'));
            return;
        }
        setSelectedIssue(prev => prev ? { ...prev, ...res.data } : res.data);
        setIssues(prev => prev.map(issue => issue.id === res.data?.id ? { ...issue, ...res.data } : issue));
    };

    const moveIssueToLane = async (movingId: string, status: WorkflowLane) => {
        const movingIssue = issues.find(issue => issue.id === movingId);
        if (!movingIssue || issueWorkflowStatus(movingIssue) === status) return;
        if (status === 'done') {
            const blockers = issueDoneBlockerText(movingIssue);
            if (blockers) {
                toast.error(`${t('Resolve before closing')}: ${blockers}`);
                return;
            }
        }
        const updates: IssuePatch = { status, workflowSource: 'inbox_board' };
        if (statusNeedsAssignee(status) && !movingIssue.assigneeEmail) {
            const claimedAssignee = currentUserEmail.trim();
            if (!claimedAssignee) {
                toast.error(t('Assign the ticket before changing status.'));
                return;
            }
            updates.assigneeEmail = claimedAssignee;
        }
        setMovingIssueId(movingId);
        const res = await api.updateIssue(projectId, movingId, updates);
        setMovingIssueId('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not update ticket'));
            return;
        }
        const updated = res.data;
        setIssues(prev => prev.map(issue => issue.id === updated.id ? { ...issue, ...updated } : issue));
        setSelectedIssue(prev => prev?.id === updated.id ? { ...prev, ...updated } : prev);
    };

    const moveIssueGroupToLane = async (sourceIssueId: string, status: WorkflowLane) => {
        const movingIds = [...new Set(issueIdsForMove(sourceIssueId))];
        const movingIdSet = new Set(movingIds);
        const movingIssues = issues.filter(issue => movingIdSet.has(issue.id) && issueWorkflowStatus(issue) !== status);
        if (movingIssues.length === 0) return;
        if (movingIssues.length === 1) {
            await moveIssueToLane(movingIssues[0].id, status);
            return;
        }
        if (status === 'done') {
            const blockedIssues = movingIssues.filter(issue => issueDoneBlockers(issue).length > 0);
            if (blockedIssues.length > 0) {
                const labels = new Set<string>();
                for (const issue of blockedIssues) {
                    for (const blocker of issueDoneBlockers(issue)) labels.add(blocker);
                }
                const blockers = [...labels].join(', ') || t('open blockers');
                toast.error(`${blockedIssues.length} ${t('tickets cannot close')}: ${blockers}`);
                return;
            }
        }
        const updates: IssuePatch = { status, workflowSource: 'inbox_board_bulk' };
        if (statusNeedsAssignee(status) && movingIssues.some(issue => !issue.assigneeEmail.trim())) {
            const claimedAssignee = currentUserEmail.trim();
            if (!claimedAssignee) {
                toast.error(t('Assign the ticket before changing status.'));
                return;
            }
            updates.assigneeEmail = claimedAssignee;
        }

        setMovingIssueId(sourceIssueId);
        setBulkUpdating(true);
        const res = await api.bulkUpdateIssues(projectId, movingIssues.map(issue => issue.id), updates);
        setBulkUpdating(false);
        setMovingIssueId('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not update tickets'));
            return;
        }

        const updatedById = new Map(res.data.items.map(issue => [issue.id, issue]));
        setIssues(prev => prev.map(issue => {
            const updated = updatedById.get(issue.id);
            return updated ? { ...issue, ...updated } : issue;
        }));
        setSelectedIssue(prev => {
            if (!prev) return prev;
            const updated = updatedById.get(prev.id);
            return updated ? { ...prev, ...updated } : prev;
        });
        if (selectedIssue && updatedById.has(selectedIssue.id)) {
            const updated = updatedById.get(selectedIssue.id);
            setAssigneeDraft(updated?.assigneeEmail || '');
        }
        setSelectedIssueIds(prev => prev.filter(id => !updatedById.has(id)));

        if (res.data.failed.length > 0) {
            toast.error(`${res.data.failed.length} ${t('ticket updates failed')}`);
            return;
        }
        toast.success(`${updatedById.size} ${t('tickets moved')}`);
    };

    const assignIssue = async (email: string) => {
        if (!selectedIssue) return;
        setAssigneeDraft(email);
        setSavingAssignee(true);
        try {
            await patchSelectedIssue({ assigneeEmail: email.trim() });
        } finally {
            setSavingAssignee(false);
        }
    };

    const saveAssignee = async () => {
        await assignIssue(assigneeDraft.trim());
    };

    const assignQueue = async (queueKey: string) => {
        if (!selectedIssue) return;
        const queue = queueOptions.find(option => option.queueKey === queueKey);
        setSavingQueue(true);
        try {
            await patchSelectedIssue({
                queueKey: queueKey === NO_QUEUE_VALUE ? '' : queueKey,
                queueName: queueKey === NO_QUEUE_VALUE ? '' : queue?.name || queueKey,
            });
        } finally {
            setSavingQueue(false);
        }
    };

    const saveTags = async (nextTags?: string[]) => {
        if (!selectedIssue) return;
        const tags = nextTags ?? parseIssueTags(tagDraft);
        setSavingTags(true);
        try {
            await patchSelectedIssue({ tags });
            setTagDraft(tags.join(', '));
        } finally {
            setSavingTags(false);
        }
    };

    const removeTag = async (tagToRemove: string) => {
        if (!selectedIssue) return;
        const nextTags = (selectedIssue.tags ?? []).filter(tag => tag.toLowerCase() !== tagToRemove.toLowerCase());
        await saveTags(nextTags);
    };

    const saveCustomFields = async () => {
        if (!selectedIssue) return;
        setSavingCustomFields(true);
        try {
            await patchSelectedIssue({ customFields: customFieldDraft });
        } finally {
            setSavingCustomFields(false);
        }
    };

    const mergeFieldPreparation = (issue: SupportIssue, preparation: SupportFieldPreparation): SupportIssue => {
        let nextIssue = preparation.issue?.id === issue.id ? { ...issue, ...preparation.issue } : issue;
        if (preparation.actionExecution) {
            nextIssue = mergeActionExecutionIntoIssue(nextIssue, preparation.actionExecution);
        }
        if (preparation.run) {
            nextIssue = {
                ...nextIssue,
                aiRuns: [preparation.run, ...(nextIssue.aiRuns ?? []).filter(run => run.id !== preparation.run?.id)],
            };
        }
        return nextIssue;
    };

    const mergeTriagePreparation = (issue: SupportIssue, preparation: SupportTriagePreparation): SupportIssue => {
        let nextIssue = preparation.issue?.id === issue.id ? { ...issue, ...preparation.issue } : issue;
        if (preparation.actionExecution) {
            nextIssue = mergeActionExecutionIntoIssue(nextIssue, preparation.actionExecution);
        }
        if (preparation.run) {
            nextIssue = {
                ...nextIssue,
                aiRuns: [preparation.run, ...(nextIssue.aiRuns ?? []).filter(run => run.id !== preparation.run?.id)],
            };
        }
        return nextIssue;
    };

    const prepareTriage = async () => {
        if (!selectedIssue || preparingTriage) return;
        const issueIdForTriage = selectedIssue.id;
        setPreparingTriage(true);
        const res = await api.prepareIssueTriage(projectId, issueIdForTriage, true);
        setPreparingTriage(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not prepare triage'));
            return;
        }
        const preparation = res.data;
        setSelectedIssue(prev => prev ? mergeTriagePreparation(prev, preparation) : prev);
        setIssues(prev => prev.map(issue => issue.id === issueIdForTriage ? mergeTriagePreparation(issue, preparation) : issue));
        if (preparation.issue) {
            setAssigneeDraft(preparation.issue.assigneeEmail || '');
            setTagDraft((preparation.issue.tags ?? []).join(', '));
            setCustomFieldDraft(preparation.issue.customFields ?? {});
        }
        const changedCount = Object.keys(preparation.triage ?? {}).filter(key => key !== 'type').length;
        void refreshAnswerWorkspace(issueIdForTriage);
        toast.success(changedCount > 0 ? t('Triage proposed') : t('No triage suggested'));
    };

    const prepareCustomFields = async () => {
        if (!selectedIssue || preparingCustomFields) return;
        const issueIdForFields = selectedIssue.id;
        setPreparingCustomFields(true);
        const res = await api.prepareIssueFields(projectId, issueIdForFields, true, true);
        setPreparingCustomFields(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not prepare fields'));
            return;
        }
        const preparation = res.data;
        setSelectedIssue(prev => prev ? mergeFieldPreparation(prev, preparation) : prev);
        setIssues(prev => prev.map(issue => issue.id === issueIdForFields ? mergeFieldPreparation(issue, preparation) : issue));
        if (preparation.issue) {
            setCustomFieldDraft(preparation.issue.customFields ?? {});
        }
        const fieldCount = Object.keys(preparation.customFields ?? {}).length;
        void refreshAnswerWorkspace(issueIdForFields);
        toast.success(fieldCount > 0 ? t('Fields proposed') : t('No fields suggested'));
    };

    const prepareTicketPackage = async () => {
        if (!selectedIssue || preparingTicketPackage) return;
        const issueIdForPackage = selectedIssue.id;
        const packageQuestion = 'Prepare the complete human-review package for this ticket: propose triage, fill missing custom fields, and draft an approval-ready customer reply using ticket context, account context, and knowledge articles.';
        const packageErrors: string[] = [];
        let preparedTriage = false;
        let preparedFields = false;
        let preparedReply = false;
        setPreparingTicketPackage(true);
        setPreparingTriage(true);
        setPreparingCustomFields(true);
        setAskingAgent(true);
        setRunningAgentActionKey('prepare-package');
        try {
            const triageRes = await api.prepareIssueTriage(projectId, issueIdForPackage, true);
            if (triageRes.error || !triageRes.data) {
                packageErrors.push(triageRes.error || t('Could not prepare triage'));
            } else {
                const preparation = triageRes.data;
                preparedTriage = true;
                setSelectedIssue(prev => prev && prev.id === issueIdForPackage ? mergeTriagePreparation(prev, preparation) : prev);
                setIssues(prev => prev.map(issue => issue.id === issueIdForPackage ? mergeTriagePreparation(issue, preparation) : issue));
                if (preparation.issue) {
                    setAssigneeDraft(preparation.issue.assigneeEmail || '');
                    setTagDraft((preparation.issue.tags ?? []).join(', '));
                    setCustomFieldDraft(preparation.issue.customFields ?? {});
                }
            }

            const fieldsRes = await api.prepareIssueFields(projectId, issueIdForPackage, true, true);
            if (fieldsRes.error || !fieldsRes.data) {
                packageErrors.push(fieldsRes.error || t('Could not prepare fields'));
            } else {
                const preparation = fieldsRes.data;
                preparedFields = true;
                setSelectedIssue(prev => prev && prev.id === issueIdForPackage ? mergeFieldPreparation(prev, preparation) : prev);
                setIssues(prev => prev.map(issue => issue.id === issueIdForPackage ? mergeFieldPreparation(issue, preparation) : issue));
                if (preparation.issue) {
                    setCustomFieldDraft(preparation.issue.customFields ?? {});
                }
            }

            const replyRes = await api.askIssueAgent(
                projectId,
                issueIdForPackage,
                packageQuestion,
                true,
                replyIncludeFeedbackLink,
                true,
                false,
            );
            if (replyRes.error || !replyRes.data) {
                packageErrors.push(replyRes.error || t('Could not ask agent'));
            } else {
                const answer = replyRes.data;
                const reply = answer.reply;
                const run = answer.run;
                const gap = answer.knowledgeGap ?? null;
                const responseAgentMessages = answer.agentMessages;
                const appendedAgentMessages = [answer.userMessage, answer.assistantMessage]
                    .filter((message): message is SupportAgentMessage => Boolean(message));
                setAgentQuestion(packageQuestion);
                setAgentAnswer(answer);
                if (reply && !answer.autoSend) {
                    setReplyDraft(answer.answer);
                    setReplyRequiresApproval(Boolean(answer.approvalRequired));
                }
                if (reply) {
                    preparedReply = true;
                    setSelectedIssue(prev => {
                        if (!prev || prev.id !== issueIdForPackage) return prev;
                        const issueWithRun = {
                            ...prev,
                            aiRuns: run ? [run, ...(prev.aiRuns ?? [])] : prev.aiRuns,
                            agentMessages: responseAgentMessages ?? [...(prev.agentMessages ?? []), ...appendedAgentMessages],
                            knowledgeGaps: gap ? [gap, ...(prev.knowledgeGaps ?? []).filter(item => item.id !== gap.id)] : prev.knowledgeGaps,
                        };
                        return mergeOutboundReplyIntoIssue(issueWithRun, reply, { mode: 'full' });
                    });
                    setIssues(prev => prev.map(issue => issue.id === issueIdForPackage
                        ? mergeOutboundReplyIntoIssue(issue, reply, { mode: 'aggregate' })
                        : issue));
                } else {
                    setSelectedIssue(prev => prev && prev.id === issueIdForPackage ? {
                        ...prev,
                        aiRuns: run ? [run, ...(prev.aiRuns ?? [])] : prev.aiRuns,
                        agentMessages: responseAgentMessages ?? [...(prev.agentMessages ?? []), ...appendedAgentMessages],
                        knowledgeGaps: gap ? [gap, ...(prev.knowledgeGaps ?? []).filter(item => item.id !== gap.id)] : prev.knowledgeGaps,
                    } : prev);
                }
            }
        } finally {
            setPreparingTicketPackage(false);
            setPreparingTriage(false);
            setPreparingCustomFields(false);
            setAskingAgent(false);
            setRunningAgentActionKey('');
            void refreshAnswerWorkspace(issueIdForPackage);
        }
        if (packageErrors.length > 0) {
            toast.error(packageErrors[0]);
            return;
        }
        const parts = [
            preparedTriage ? t('triage') : '',
            preparedFields ? t('fields') : '',
            preparedReply ? t('reply') : '',
        ].filter(Boolean).join(', ');
        toast.success(parts ? `${t('Package prepared')}: ${parts}` : t('Package prepared'));
    };

    const claimIssue = async (issue: SupportIssue) => {
        const claimedAssignee = currentUserEmail.trim();
        if (!claimedAssignee || claimingIssueId || issue.assigneeEmail) return;
        setClaimingIssueId(issue.id);
        try {
            const res = await api.updateIssue(projectId, issue.id, { assigneeEmail: claimedAssignee });
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not assign ticket'));
                return;
            }
            const updated = res.data;
            setIssues(prev => prev.map(item => item.id === updated.id ? { ...item, ...updated } : item));
            setSelectedIssue(prev => prev?.id === updated.id ? { ...prev, ...updated } : prev);
            if (issueId === updated.id) setAssigneeDraft(updated.assigneeEmail || claimedAssignee);
            toast.success(t('Assigned'));
        } finally {
            setClaimingIssueId('');
        }
    };

    const newTicketContactOptions = newTicketAccountDetail?.contacts ?? [];

    const loadNewTicketAccounts = useCallback(async () => {
        if (loadingNewTicketAccounts) return;
        setLoadingNewTicketAccounts(true);
        const res = await api.getAccounts(projectId, 100);
        setLoadingNewTicketAccounts(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not load accounts'));
            return;
        }
        setNewTicketAccounts(res.data.items);
    }, [loadingNewTicketAccounts, projectId, t]);

    const selectNewTicketAccount = async (accountId: string) => {
        setNewTicketAccountId(accountId);
        setNewTicketContactId(NO_CONTACT_RECORD_VALUE);
        setNewTicketAccountDetail(null);
        if (accountId === NO_ACCOUNT_RECORD_VALUE) return;

        const listAccount = newTicketAccounts.find(account => account.id === accountId);
        if (listAccount) setNewTicketAccount(accountLabel(listAccount));
        setLoadingNewTicketAccountDetail(true);
        const res = await api.getAccount(projectId, accountId);
        setLoadingNewTicketAccountDetail(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not load account'));
            return;
        }
        setNewTicketAccountDetail(res.data);
        setNewTicketAccount(accountLabel(res.data));
    };

    const selectNewTicketContact = (contactId: string) => {
        setNewTicketContactId(contactId);
        if (contactId === NO_CONTACT_RECORD_VALUE) return;
        const contact = newTicketContactOptions.find(item => item.id === contactId);
        if (!contact) return;
        if (contact.email) setNewTicketFrom(contact.email);
        if (contact.name) setNewTicketName(contact.name);
    };

    const openNewTicket = () => {
        setNewTicketSubject('');
        setNewTicketFrom('');
        setNewTicketName('');
        setNewTicketAccount('');
        setNewTicketBody('');
        setNewTicketAccountId(NO_ACCOUNT_RECORD_VALUE);
        setNewTicketContactId(NO_CONTACT_RECORD_VALUE);
        setNewTicketAccountDetail(null);
        setNewTicketPriority('normal');
        setNewTicketAssignee(currentUserEmail.trim());
        setNewTicketQueueKey(queueOptions[0]?.queueKey || 'support');
        setNewTicketOpen(true);
        if (newTicketAccounts.length === 0) {
            void loadNewTicketAccounts();
        }
    };

    const createManualTicket = async () => {
        const fromAddress = newTicketFrom.trim();
        const body = newTicketBody.trim();
        if (!fromAddress || !body) {
            toast.error(t('Requester email and message are required.'));
            return;
        }
        setCreatingTicket(true);
        const res = await api.createIssue(projectId, {
            subject: newTicketSubject.trim(),
            fromAddress,
            body,
            accountId: newTicketAccountId === NO_ACCOUNT_RECORD_VALUE ? undefined : newTicketAccountId,
            contactId: newTicketContactId === NO_CONTACT_RECORD_VALUE ? undefined : newTicketContactId,
            contactName: newTicketName.trim(),
            accountName: newTicketAccount.trim(),
            priority: newTicketPriority,
            assigneeEmail: newTicketAssignee.trim() || currentUserEmail.trim(),
            queueKey: newTicketQueueKey,
            queueName: queueOptions.find(option => option.queueKey === newTicketQueueKey)?.name || newTicketQueueKey,
        });
        setCreatingTicket(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not create ticket'));
            return;
        }
        const issue = res.data;
        setIssues(prev => [issue, ...prev.filter(item => item.id !== issue.id)]);
        setSelectedIssue(issue);
        setAssigneeDraft(issue.assigneeEmail || '');
        setReplyDraft(issue.draftReply || '');
        setNewTicketOpen(false);
        toast.success(t('Ticket created'));
        navigateToIssue(issue.id, { viewMode: 'list' });
    };

    const updateOutboundReply = (
        reply: SupportOutboundMessage,
        options: { issuePatch?: Partial<SupportIssue>; appendSentTimeline?: boolean } = {},
    ) => {
        const targetIssueId = reply.issueId || selectedIssue?.id;
        const selectedPreviousReply = selectedIssue?.outboundMessages?.find(item => item.id === reply.id) ?? null;
        if (targetIssueId && selectedIssue?.id === targetIssueId && options.issuePatch?.assigneeEmail !== undefined) {
            setAssigneeDraft(options.issuePatch.assigneeEmail || '');
        }
        setSelectedIssue(prev => {
            if (!prev || (targetIssueId && prev.id !== targetIssueId)) return prev;
            const previousReply = prev.outboundMessages?.find(item => item.id === reply.id) ?? selectedPreviousReply;
            return mergeOutboundReplyIntoIssue(prev, reply, {
                mode: 'full',
                previousReply,
                issuePatch: options.issuePatch,
                appendSentTimeline: options.appendSentTimeline,
            });
        });
        if (targetIssueId) {
            setIssues(prev => prev.map(issue => {
                if (issue.id !== targetIssueId) return issue;
                const previousReply = issue.outboundMessages?.find(item => item.id === reply.id) ?? selectedPreviousReply;
                return mergeOutboundReplyIntoIssue(issue, reply, {
                    mode: 'aggregate',
                    previousReply,
                    issuePatch: options.issuePatch,
                });
            }));
        }
    };

    const startEditingReply = (reply: SupportOutboundMessage) => {
        setEditingReplyId(reply.id);
        setEditingReplyBody(reply.body);
        setChangeRequestReplyId('');
        setChangeRequestNote('');
    };

    const cancelEditingReply = () => {
        setEditingReplyId('');
        setEditingReplyBody('');
    };

    const saveEditedReply = async (reply: SupportOutboundMessage) => {
        if (!selectedIssue || !editingReplyBody.trim()) return;
        setSavingReplyEditId(reply.id);
        const res = await api.updateIssueReply(projectId, selectedIssue.id, reply.id, {
            body: editingReplyBody.trim(),
            status: reply.status,
        });
        setSavingReplyEditId('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not save reply'));
            return;
        }
        updateOutboundReply(res.data);
        cancelEditingReply();
        toast.success(t('Saved'));
    };

    const addNote = async () => {
        if (!selectedIssue || !noteDraft.trim()) return;
        setSavingNote(true);
        const res = await api.createIssueNote(projectId, selectedIssue.id, noteDraft.trim());
        setSavingNote(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not save note'));
            return;
        }
        setSelectedIssue(prev => prev ? { ...prev, notes: [...(prev.notes ?? []), res.data!] } : prev);
        setNoteDraft('');
        void api.getIssue(projectId, selectedIssue.id).then((detail) => {
            if (detail.data) {
                setSelectedIssue(detail.data);
                setAssigneeDraft(detail.data.assigneeEmail || '');
            }
        });
    };

    const saveReply = async (status: 'draft' | 'queued') => {
        if (!selectedIssue || !replyDraft.trim()) return;
        if (status === 'queued' && selectedReplySendBlocked) {
            toast.error(selectedReplySendBlockDetail || t('Reply channel is blocked'));
            return;
        }
        setSavingReplyStatus(status);
        const res = await api.createIssueReply(
            projectId,
            selectedIssue.id,
            replyDraft.trim(),
            status,
            replyRequiresApproval,
            replyIncludeFeedbackLink,
        );
        setSavingReplyStatus('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not save reply'));
            return;
        }
        const claimedAssigneeEmail = selectedIssue.assigneeEmail || currentUserEmail;
        const issuePatch: Partial<SupportIssue> = {
            assigneeEmail: claimedAssigneeEmail || selectedIssue.assigneeEmail,
        };
        if (status === 'queued') {
            issuePatch.status = 'ongoing';
            issuePatch.workflowStatus = 'ongoing';
        }
        setSelectedIssue(prev => prev ? mergeOutboundReplyIntoIssue(prev, res.data!, {
            mode: 'full',
            issuePatch,
        }) : prev);
        setIssues(prev => prev.map(issue => issue.id === selectedIssue.id
            ? mergeOutboundReplyIntoIssue(issue, res.data!, {
                mode: 'aggregate',
                issuePatch,
            })
            : issue));
        toast.success(status === 'queued' ? t('Queued') : t('Saved'));
        if (status === 'queued') {
            setReplyDraft('');
            setReplyRequiresApproval(false);
        }
        void refreshAnswerWorkspace(selectedIssue.id);
    };

    const sendReplyDraftNow = async () => {
        if (!selectedIssue || !replyDraft.trim() || savingReplyStatus) return;
        if (replyRequiresApproval) {
            toast.error(t('Turn off approval to send now.'));
            return;
        }
        if (selectedReplySendBlocked) {
            toast.error(selectedReplySendBlockDetail || t('Reply channel is blocked'));
            return;
        }
        const issueId = selectedIssue.id;
        const body = replyDraft.trim();
        setSavingReplyStatus('send-now');
        try {
            const created = await api.createIssueReply(
                projectId,
                issueId,
                body,
                'queued',
                false,
                replyIncludeFeedbackLink,
            );
            if (created.error || !created.data) {
                toast.error(created.error || t('Could not save reply'));
                return;
            }
            const claimedAssigneeEmail = selectedIssue.assigneeEmail || currentUserEmail;
            const queuedIssuePatch: Partial<SupportIssue> = {
                assigneeEmail: claimedAssigneeEmail || selectedIssue.assigneeEmail,
                status: 'ongoing',
                workflowStatus: 'ongoing',
            };
            updateOutboundReply(created.data, { issuePatch: queuedIssuePatch });
            setReplyDraft('');
            setReplyRequiresApproval(false);

            const sent = await api.sendIssueReply(projectId, issueId, created.data.id);
            if (sent.error || !sent.data) {
                toast.error(sent.error || t('Could not send reply'));
                void refreshAnswerWorkspace(issueId);
                return;
            }
            updateOutboundReply(sent.data, {
                issuePatch: sent.data.status === 'sent'
                    ? sentReplyIssuePatch(sent.data, currentUserEmail)
                    : queuedIssuePatch,
                appendSentTimeline: sent.data.status === 'sent',
            });
            void refreshAnswerWorkspace(issueId);
            if (sent.data.status === 'sent') {
                toast.success(t('Sent'));
            } else {
                toast.error(sent.data.error || t('Delivery failed'));
            }
        } finally {
            setSavingReplyStatus('');
        }
    };

    const recordAction = async (
        action: { label: string; type: string },
        index: number,
        status: 'running' | 'success' | 'failed',
    ) => {
        if (!selectedIssue) return;
        const key = `${action.type || 'action'}:${action.label || index}`;
        setSavingActionKey(`${key}:${status}`);
        const res = await api.createIssueActionExecution(projectId, selectedIssue.id, {
            actionKey: key,
            label: action.label || t('Action'),
            type: action.type || 'manual',
            status,
        });
        setSavingActionKey('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not record action'));
            return;
        }
        setSelectedIssue(prev => prev ? {
            ...prev,
            actionExecutions: [res.data!, ...(prev.actionExecutions ?? [])],
        } : prev);
        toast.success(t('Saved'));
    };

    const updateActionExecution = (execution: SupportActionExecution, issuePatch?: SupportIssue | null) => {
        const targetIssueId = execution.issueId || selectedIssue?.id;
        setSelectedIssue(prev => {
            if (!prev || (targetIssueId && prev.id !== targetIssueId)) return prev;
            const nextIssue = issuePatch?.id === prev.id ? { ...prev, ...issuePatch } : prev;
            return mergeActionExecutionIntoIssue(nextIssue, execution);
        });
        if (targetIssueId) {
            setIssues(prev => prev.map(issue => {
                if (issue.id !== targetIssueId) return issue;
                const nextIssue = issuePatch?.id === issue.id ? { ...issue, ...issuePatch } : issue;
                return mergeActionExecutionIntoIssue(nextIssue, execution);
            }));
        }
    };

    const approveActionExecution = async (execution: SupportActionExecution) => {
        if (!selectedIssue || approvingActionExecutionId || rejectingActionExecutionId) return;
        setApprovingActionExecutionId(execution.id);
        const res = await api.approveIssueActionExecution(projectId, selectedIssue.id, execution.id);
        setApprovingActionExecutionId('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not approve action'));
            return;
        }
        updateActionExecution(res.data.execution, res.data.issue);
        if (res.data.issue) {
            setAssigneeDraft(res.data.issue.assigneeEmail || '');
            setTagDraft((res.data.issue.tags ?? []).join(', '));
            setCustomFieldDraft(res.data.issue.customFields ?? {});
        }
        toast.success(t('Approved'));
    };

    const rejectActionExecution = async (execution: SupportActionExecution) => {
        if (!selectedIssue || approvingActionExecutionId || rejectingActionExecutionId) return;
        setRejectingActionExecutionId(execution.id);
        const res = await api.rejectIssueActionExecution(projectId, selectedIssue.id, execution.id);
        setRejectingActionExecutionId('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not reject action'));
            return;
        }
        updateActionExecution(res.data.execution, res.data.issue);
        toast.success(t('Rejected'));
    };

    const approveReply = async (reply: SupportOutboundMessage) => {
        if (!selectedIssue || approvingReplyId || savingReplyEditId || revisingReplyId) return;
        setApprovingReplyId(reply.id);
        const res = await api.approveIssueReply(projectId, selectedIssue.id, reply.id);
        setApprovingReplyId('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not approve reply'));
            return;
        }
        updateOutboundReply(res.data, {
            issuePatch: replyApprovalIssuePatch(selectedIssue, res.data, currentUserEmail),
        });
        toast.success(t('Approved'));
    };

    const openChangeRequest = (reply: SupportOutboundMessage) => {
        setChangeRequestReplyId(reply.id);
        setChangeRequestNote(replyChangesNote(reply));
        setEditingReplyId('');
        setEditingReplyBody('');
    };

    const cancelChangeRequest = () => {
        setChangeRequestReplyId('');
        setChangeRequestNote('');
    };

    const requestReplyChanges = async (reply: SupportOutboundMessage) => {
        if (!selectedIssue || requestingChangesReplyId || savingReplyEditId || revisingReplyId) return;
        setRequestingChangesReplyId(reply.id);
        const res = await api.requestIssueReplyChanges(projectId, selectedIssue.id, reply.id, changeRequestNote.trim());
        setRequestingChangesReplyId('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not request changes'));
            return;
        }
        updateOutboundReply(res.data);
        cancelChangeRequest();
        toast.success(t('Changes requested'));
    };

    const reviseReplyWithAgent = async (reply: SupportOutboundMessage) => {
        if (!selectedIssue || revisingReplyId || askingAgent || savingReplyEditId) return;
        setRevisingReplyId(reply.id);
        const res = await api.reviseIssueReply(
            projectId,
            selectedIssue.id,
            reply.id,
            replyChangesNote(reply),
            replyIncludeFeedbackLink,
        );
        setRevisingReplyId('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not revise draft'));
            return;
        }
        const answer = res.data;
        const revisedReply = answer.reply;
        const run = answer.run;
        const gap = answer.knowledgeGap ?? null;
        setAgentAnswer(answer);
        if (revisedReply) {
            setSelectedIssue(prev => {
                if (!prev) return prev;
                const issueWithRun = {
                    ...prev,
                    aiRuns: run ? [run, ...(prev.aiRuns ?? [])] : prev.aiRuns,
                    knowledgeGaps: gap ? [gap, ...(prev.knowledgeGaps ?? []).filter(item => item.id !== gap.id)] : prev.knowledgeGaps,
                };
                return mergeOutboundReplyIntoIssue(issueWithRun, revisedReply, { mode: 'full' });
            });
            setIssues(prev => prev.map(issue => issue.id === selectedIssue.id
                ? mergeOutboundReplyIntoIssue(issue, revisedReply, { mode: 'aggregate' })
                : issue));
        } else {
            setSelectedIssue(prev => prev ? {
                ...prev,
                aiRuns: run ? [run, ...(prev.aiRuns ?? [])] : prev.aiRuns,
                knowledgeGaps: gap ? [gap, ...(prev.knowledgeGaps ?? []).filter(item => item.id !== gap.id)] : prev.knowledgeGaps,
            } : prev);
        }
        toast.success(revisedReply ? t('Revision prepared') : t('Agent answered'));
    };

    const sendReply = async (
        reply: SupportOutboundMessage,
        approveFirst = false,
        options: { forceRetry?: boolean } = {},
    ) => {
        if (!selectedIssue || revisingReplyId) return;
        if (selectedReplySendBlocked) {
            toast.error(selectedReplySendBlockDetail || t('Reply channel is blocked'));
            return;
        }
        setSendingReplyId(reply.id);
        try {
            let replyToSend = reply;
            if (approveFirst && replyNeedsApproval(reply)) {
                setApprovingReplyId(reply.id);
                const approval = await api.approveIssueReply(projectId, selectedIssue.id, reply.id);
                if (approval.error || !approval.data) {
                    toast.error(approval.error || t('Could not approve reply'));
                    return;
                }
                replyToSend = approval.data;
                updateOutboundReply(replyToSend, {
                    issuePatch: replyApprovalIssuePatch(selectedIssue, replyToSend, currentUserEmail),
                });
            }
            const res = await api.sendIssueReply(projectId, selectedIssue.id, replyToSend.id, options.forceRetry === true);
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not send reply'));
                return;
            }
            updateOutboundReply(res.data, {
                issuePatch: res.data.status === 'sent'
                    ? sentReplyIssuePatch(res.data, currentUserEmail)
                    : undefined,
                appendSentTimeline: res.data.status === 'sent',
            });
            if (res.data.status === 'sent') {
                toast.success(t('Sent'));
            } else {
                toast.error(res.data.error || t('Delivery failed'));
            }
        } finally {
            setSendingReplyId('');
            setApprovingReplyId('');
        }
    };

    const createPortalLink = async () => {
        if (!selectedIssue) return;
        setCreatingPortalLink(true);
        const res = await api.createIssuePortalSession(projectId, selectedIssue.id);
        setCreatingPortalLink(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not create portal link'));
            return;
        }
        const url = res.data.url || '';
        setPortalUrl(url);
        setSelectedIssue(prev => prev ? {
            ...prev,
            portalSessions: [res.data!, ...(prev.portalSessions ?? [])],
        } : prev);
        if (url && navigator.clipboard) {
            try {
                await navigator.clipboard.writeText(url);
                toast.success(t('Portal link copied'));
                return;
            } catch {
                // Fall through to visible link.
            }
        }
        toast.success(t('Portal link created'));
    };

    const appendKnowledgeToReply = (article: KnowledgeArticle) => {
        const addition = [
            article.title,
            article.body,
        ].filter(Boolean).join('\n\n');
        setReplyDraft(prev => [prev.trim(), addition].filter(Boolean).join('\n\n'));
    };

    const ticketArticleBody = (
        gap?: KnowledgeGap,
        source?: { run?: SupportAiRun; answer?: string },
    ) => {
        const latestCustomerMessage = [...selectedMessages]
            .reverse()
            .find(message => message.direction === 'customer');
        const agentRun = source?.run;
        const agentAnswerText = (source?.answer ?? '').trim()
            || (agentRun ? agentRunAnswer(agentRun).trim() : '')
            || agentAnswer?.answer.trim()
            || (agentChatRuns[0] ? agentRunAnswer(agentChatRuns[0]).trim() : '');
        const agentQuestionText = agentRun
            ? agentRunQuestion(agentRun)
            : agentQuestion.trim() || (agentChatRuns[0] ? agentRunQuestion(agentChatRuns[0]) : '');
        return [
            selectedIssue?.aiSummary ? `Summary:\n${selectedIssue.aiSummary}` : '',
            latestCustomerMessage ? `Customer evidence:\n${messageText(latestCustomerMessage)}` : '',
            agentQuestionText ? `Agent question:\n${agentQuestionText}` : '',
            agentAnswerText ? `Agent answer:\n${agentAnswerText}` : '',
            gap?.evidence ? `Knowledge gap evidence:\n${gap.evidence}` : '',
            draftReply ? `Current draft reply:\n${draftReply}` : '',
        ].filter(Boolean).join('\n\n');
    };

    const ticketInsightBody = (type: 'risk' | 'feature_request') => {
        const latestCustomerMessage = [...selectedMessages]
            .reverse()
            .find(message => message.direction === 'customer');
        const parts = [
            selectedIssue?.aiSummary ? `Summary:\n${selectedIssue.aiSummary}` : '',
            latestCustomerMessage ? `Customer evidence:\n${messageText(latestCustomerMessage)}` : '',
            draftReply ? `Current draft reply:\n${draftReply}` : '',
        ].filter(Boolean);
        if (parts.length > 0) return parts.join('\n\n');
        return type === 'risk'
            ? 'Ticket flagged as an account risk from the support inbox.'
            : 'Ticket flagged as a feature request from the support inbox.';
    };

    const createTicketAccountInsight = async (type: 'risk' | 'feature_request') => {
        if (!selectedIssue || !ticketAccount || savingAccountInsightKey) return;
        const key = `${type}:${selectedIssue.id}`;
        setSavingAccountInsightKey(key);
        const title = type === 'risk'
            ? `Support risk: ${selectedIssue.subject || accountLabel(ticketAccount)}`
            : `Feature request: ${selectedIssue.subject || accountLabel(ticketAccount)}`;
        const res = await api.createAccountInsight(projectId, ticketAccount.id, {
            type,
            title,
            body: ticketInsightBody(type),
            severity: type === 'risk' ? 'high' : 'normal',
            status: 'open',
            sourceIssueId: selectedIssue.id,
            insightKey: `ticket:${type}:${selectedIssue.id}`,
            metadata: {
                source: 'ticket_workspace',
                issueId: selectedIssue.id,
                channel: selectedIssue.channel,
                priority: selectedIssue.priority,
            },
        });
        setSavingAccountInsightKey('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not create insight'));
            return;
        }
        setTicketAccount(prev => prev ? mergeAccountInsight(prev, res.data!) : prev);
        toast.success(type === 'risk' ? t('Risk added') : t('Feature request added'));
    };

    const updateTicketAccountInsightStatus = async (insight: SupportAccountInsight, status: string) => {
        if (!ticketAccount || savingAccountInsightKey) return;
        const key = `insight:${insight.id}:${status}`;
        setSavingAccountInsightKey(key);
        const res = await api.updateAccountInsight(projectId, insight.id, { status });
        setSavingAccountInsightKey('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not update insight'));
            return;
        }
        setTicketAccount(prev => prev ? updateAccountInsightInAccount(prev, res.data!) : prev);
        const accountRes = await api.getAccount(projectId, ticketAccount.id);
        if (accountRes.data) {
            setTicketAccount(accountRes.data);
        }
        toast.success(status === 'resolved' ? t('Insight resolved') : t('Insight updated'));
    };

    const createKnowledgeArticleFromTicket = async (
        gap?: KnowledgeGap,
        source?: AgentArticleSource,
    ) => {
        if (!selectedIssue) return;
        const title = source?.title
            || gap?.suggestedArticleTitle
            || gap?.title.replace(/^Knowledge gap:\s*/i, '')
            || selectedIssue.subject
            || t('Support article');
        const body = ticketArticleBody(gap, source);
        if (!body.trim()) {
            toast.error(t('Could not create article'));
            return;
        }
        const key = source?.key || gap?.id || selectedIssue.id;
        setCreatingKnowledgeArticle(key);
        const sourceTags = source?.tags ?? [];
        const res = await api.createKnowledgeArticle(projectId, {
            title,
            body,
            status: 'draft',
            sourceIssueId: selectedIssue.id,
            sourceGapId: gap?.id,
            tags: [selectedIssue.channel, selectedIssue.activatedIntent, 'ticket', ...sourceTags].filter(Boolean),
        });
        setCreatingKnowledgeArticle('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not create article'));
            return;
        }
        setSelectedIssue(prev => prev ? {
            ...prev,
            knowledgeSuggestions: [res.data!, ...(prev.knowledgeSuggestions ?? [])],
            knowledgeGaps: gap ? (prev.knowledgeGaps ?? []).filter(item => item.id !== gap.id) : prev.knowledgeGaps,
        } : prev);
        toast.success(t('Saved'));
    };

    const publishKnowledgeArticleFromTicket = async (article: KnowledgeArticle) => {
        if (publishingKnowledgeArticleId) return;
        setPublishingKnowledgeArticleId(article.id);
        const res = await api.updateKnowledgeArticle(projectId, article.id, {
            status: 'published',
            visibility: 'public',
            public: true,
        });
        setPublishingKnowledgeArticleId('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not publish article'));
            return;
        }
        const published = res.data;
        setKnowledgeArticles(prev => prev.some(item => item.id === published.id)
            ? prev.map(item => item.id === published.id ? published : item)
            : [published, ...prev]);
        setSelectedIssue(prev => prev ? {
            ...prev,
            knowledgeSuggestions: (prev.knowledgeSuggestions ?? []).some(item => item.id === published.id)
                ? (prev.knowledgeSuggestions ?? []).map(item => item.id === published.id ? published : item)
                : [published, ...(prev.knowledgeSuggestions ?? [])],
        } : prev);
        toast.success(t('Article published'));
    };

    const askAgent = async (questionOverride?: string, createDraft = false, actionKey = '', autoSend = false) => {
        if (!selectedIssue) return;
        const question = questionOverride ?? agentQuestion.trim();
        if (questionOverride) setAgentQuestion(questionOverride);
        setAskingAgent(true);
        setRunningAgentActionKey(actionKey);
        const shouldCreateDraft = createDraft || autoSend;
        const res = await api.askIssueAgent(
            projectId,
            selectedIssue.id,
            question,
            shouldCreateDraft,
            shouldCreateDraft && replyIncludeFeedbackLink,
            !autoSend,
            autoSend,
        );
        setAskingAgent(false);
        setRunningAgentActionKey('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not ask agent'));
            return;
        }
        const answer = res.data;
        const reply = answer.reply;
        const run = answer.run;
        const gap = answer.knowledgeGap ?? null;
        const responseAgentMessages = answer.agentMessages;
        const appendedAgentMessages = [answer.userMessage, answer.assistantMessage]
            .filter((message): message is SupportAgentMessage => Boolean(message));
        setAgentAnswer(answer);
        if (reply && !answer.autoSend) {
            setReplyDraft(answer.answer);
            setReplyRequiresApproval(Boolean(answer.approvalRequired));
        }
        if (reply) {
            setSelectedIssue(prev => {
                if (!prev) return prev;
                const issueWithRun = {
                    ...prev,
                    aiRuns: run ? [run, ...(prev.aiRuns ?? [])] : prev.aiRuns,
                    agentMessages: responseAgentMessages ?? [...(prev.agentMessages ?? []), ...appendedAgentMessages],
                    knowledgeGaps: gap ? [gap, ...(prev.knowledgeGaps ?? []).filter(item => item.id !== gap.id)] : prev.knowledgeGaps,
                };
                return mergeOutboundReplyIntoIssue(issueWithRun, reply, { mode: 'full' });
            });
            setIssues(prev => prev.map(issue => issue.id === selectedIssue.id
                ? mergeOutboundReplyIntoIssue(issue, reply, { mode: 'aggregate' })
                : issue));
        } else {
            setSelectedIssue(prev => prev ? {
                ...prev,
                aiRuns: run ? [run, ...(prev.aiRuns ?? [])] : prev.aiRuns,
                agentMessages: responseAgentMessages ?? [...(prev.agentMessages ?? []), ...appendedAgentMessages],
                knowledgeGaps: gap ? [gap, ...(prev.knowledgeGaps ?? []).filter(item => item.id !== gap.id)] : prev.knowledgeGaps,
            } : prev);
        }
        void refreshAnswerWorkspace(selectedIssue.id);
        toast.success(answer.autoSend
            ? t('Reply queued')
            : reply && answer.autoSendRequested && answer.autoSendBlockedReason
                ? t('Draft needs approval')
                : reply
                    ? t('Draft prepared')
                    : t('Agent answered'));
    };

    const applyAgentAnswerToReply = (mode: 'replace' | 'append') => {
        const answer = agentAnswer?.answer.trim();
        if (!answer) return;
        setReplyDraft(prev => mode === 'append' ? [prev.trim(), answer].filter(Boolean).join('\n\n') : answer);
        setReplyRequiresApproval(true);
        toast.success(t('Draft ready'));
    };

    const applyAgentRunToReply = (run: SupportAiRun, mode: 'replace' | 'append') => {
        const answer = agentRunAnswer(run).trim();
        if (!answer) return;
        setReplyDraft(prev => mode === 'append' ? [prev.trim(), answer].filter(Boolean).join('\n\n') : answer);
        setReplyRequiresApproval(true);
        toast.success(t('Draft ready'));
    };

    const startAgentFollowUp = (run: SupportAiRun) => {
        setAgentQuestion(agentRunFollowUpPrompt(run));
        window.setTimeout(() => agentQuestionRef.current?.focus(), 0);
    };

    const renderKnowledgeGapCallout = (gap: KnowledgeGap | null | undefined, compact = false) => {
        if (!gap) return null;
        const title = gap.suggestedArticleTitle || gap.title || t('Knowledge gap');
        const evidence = gap.evidence || gap.title || t('Missing knowledge for this answer.');
        const key = gap.id || 'agent-knowledge-gap';
        return (
            <div data-ticket-knowledge-gap-callout className="rounded-md border border-dashed bg-muted/20 p-2 text-sm">
                <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-1.5 font-medium">
                        <AlertCircle className="size-3.5 shrink-0 text-muted-foreground" />
                        <span className="min-w-0 truncate">{title}</span>
                    </div>
                    <Badge variant={priorityVariant(gap.severity)} className="shrink-0 font-normal">
                        {gap.severity}
                    </Badge>
                </div>
                <div className={compact ? 'line-clamp-2 text-xs text-muted-foreground' : 'whitespace-pre-wrap text-xs text-muted-foreground'}>
                    {evidence}
                </div>
                <div className="mt-2 flex flex-wrap justify-end gap-2">
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 px-2 text-xs"
                        data-ticket-draft-knowledge-article={key}
                        onClick={() => void createKnowledgeArticleFromTicket(gap)}
                        disabled={Boolean(creatingKnowledgeArticle)}
                    >
                        {creatingKnowledgeArticle === key
                            ? <Loader className="size-3 animate-spin" />
                            : <BookOpen className="size-3" />}
                        {t('Draft article')}
                    </Button>
                </div>
            </div>
        );
    };

    const renderCustomFieldInput = (field: SupportCustomFieldDefinition) => {
        const value = customFieldDraft[field.key];
        const setFieldValue = (nextValue: unknown) => {
            setCustomFieldDraft(prev => ({ ...prev, [field.key]: nextValue }));
        };
        if (field.type === 'boolean') {
            return (
                <div className="flex h-10 items-center gap-2">
                    <Switch checked={value === true || value === 'true'} onCheckedChange={setFieldValue} />
                    <span className="text-sm text-muted-foreground">{customFieldDisplayValue(value)}</span>
                </div>
            );
        }
        if (field.type === 'select') {
            return (
                <Select value={textFrom(value)} onValueChange={setFieldValue}>
                    <SelectTrigger>
                        <SelectValue placeholder={t('Select')} />
                    </SelectTrigger>
                    <SelectContent>
                        {field.options.map(option => (
                            <SelectItem key={option} value={option}>{option}</SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            );
        }
        return (
            <Input
                type={field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : field.type === 'url' ? 'url' : 'text'}
                value={textFrom(value)}
                onChange={event => setFieldValue(event.target.value)}
                placeholder={field.label}
            />
        );
    };

    const customFieldsPanel = selectedIssue && customFieldDefinitions.length > 0 ? (
        <section className="rounded-md border p-3" data-ticket-custom-fields>
            <div className="mb-3 flex items-center justify-between gap-2">
                <div className="text-sm font-medium">{t('Custom fields')}</div>
                <div className="flex items-center gap-1.5">
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        data-ticket-custom-fields-agent
                        onClick={() => void prepareCustomFields()}
                        disabled={preparingCustomFields}
                    >
                        {preparingCustomFields ? <Loader className="size-3.5 animate-spin" /> : <Sparkles className="size-3.5" />}
                        {t('Agent')}
                    </Button>
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => void saveCustomFields()}
                        disabled={savingCustomFields}
                    >
                        {savingCustomFields ? <Loader className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
                        {t('Save')}
                    </Button>
                </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
                {customFieldDefinitions.map(field => (
                    <div key={field.key} className="space-y-1.5">
                        <Label>
                            {field.label}
                            {field.required && <span className="ml-1 text-destructive">*</span>}
                        </Label>
                        {renderCustomFieldInput(field)}
                    </div>
                ))}
            </div>
        </section>
    ) : null;

    const renderKnowledgeArticleCard = (article: KnowledgeArticle) => {
        const matchScore = knowledgeMatchScore(article);
        const matchTerms = knowledgeMatchTerms(article);
        const matchSignals = knowledgeMatchSignals(article);
        const sourceUrl = knowledgeSourceUrl(article);
        const visibilityLabel = knowledgeVisibilityLabel(article.visibility, article.public);
        return (
            <div key={article.id} className="rounded-md border bg-muted/20 p-2 text-sm" data-ticket-knowledge-article={article.id}>
                <div className="flex min-w-0 items-center justify-between gap-2">
                    <div className="truncate font-medium">{article.title}</div>
                    <div className="flex shrink-0 items-center gap-1.5">
                        {sourceUrl && (
                            <Button type="button" size="icon-xs" variant="ghost" asChild title={t('Open source')}>
                                <a href={sourceUrl} target="_blank" rel="noreferrer" aria-label={t('Open source')}>
                                    <ExternalLink className="size-3" />
                                </a>
                            </Button>
                        )}
                        {matchScore > 0 && (
                            <Badge variant="secondary" className="font-normal">
                                {t('Score')} {matchScore}
                            </Badge>
                        )}
                        <Badge variant="outline" className="font-normal">{article.status}</Badge>
                        <Badge variant={article.public ? 'secondary' : 'outline'} className="font-normal">
                            {t(visibilityLabel)}
                        </Badge>
                    </div>
                </div>
                <div className="mt-1 line-clamp-3 text-xs text-muted-foreground">{article.body}</div>
                {sourceUrl && (
                    <a
                        href={sourceUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-1 block truncate text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                    >
                        {sourceUrl}
                    </a>
                )}
                {(article.tags ?? []).length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                        {(article.tags ?? []).slice(0, 3).map(tag => (
                            <Badge key={tag} variant="outline" className="font-normal">{tag}</Badge>
                        ))}
                    </div>
                )}
                {(matchTerms.length > 0 || matchSignals.length > 0) && (
                    <div className="mt-2 flex flex-wrap gap-1">
                        {matchSignals.map(signal => (
                            <Badge key={`signal-${signal}`} variant="secondary" className="font-normal">{signal}</Badge>
                        ))}
                        {matchTerms.map(term => (
                            <Badge key={`term-${term}`} variant="outline" className="font-normal">{term}</Badge>
                        ))}
                    </div>
                )}
                <div className="mt-2 flex flex-wrap justify-end gap-1.5">
                    {(article.status !== 'published' || !article.public || article.visibility !== 'public') && (
                        <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            data-ticket-knowledge-publish={article.id}
                            onClick={() => void publishKnowledgeArticleFromTicket(article)}
                            disabled={Boolean(publishingKnowledgeArticleId)}
                        >
                            {publishingKnowledgeArticleId === article.id
                                ? <Loader className="size-3.5 animate-spin" />
                                : <CheckCircle2 className="size-3.5" />}
                            {t('Publish')}
                        </Button>
                    )}
                    <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        onClick={() => appendKnowledgeToReply(article)}
                    >
                        {t('Use')}
                    </Button>
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => void askAgent(`Draft an approval-ready answer using the knowledge article "${article.title}".`, true, `article:${article.id}`)}
                        disabled={askingAgent}
                    >
                        {runningAgentActionKey === `article:${article.id}` ? <Loader className="size-3.5 animate-spin" /> : <Sparkles className="size-3.5" />}
                        {t('Draft')}
                    </Button>
                </div>
            </div>
        );
    };

    const renderTicketAccountInsightCard = (insight: SupportAccountInsight) => {
        const resolvingKey = `insight:${insight.id}:resolved`;
        return (
            <div key={insight.id} className="rounded-md border bg-muted/20 p-2 text-sm" data-ticket-account-insight={insight.id}>
                <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate font-medium">{insight.title}</span>
                    <div className="flex shrink-0 items-center gap-1.5">
                        <Badge variant="outline" className="font-normal">
                            {t(insight.type === 'feature_request' ? 'Feature request' : insight.type || 'signal')}
                        </Badge>
                        <Badge variant={priorityVariant(insight.severity)} className="font-normal">
                            {insight.severity || 'info'}
                        </Badge>
                    </div>
                </div>
                {insight.body && (
                    <div className="line-clamp-2 text-xs text-muted-foreground">
                        {insight.body}
                    </div>
                )}
                <div className="mt-2 flex justify-end">
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 px-2 text-xs"
                        data-ticket-account-insight-resolve={insight.id}
                        onClick={() => void updateTicketAccountInsightStatus(insight, 'resolved')}
                        disabled={Boolean(savingAccountInsightKey)}
                    >
                        {savingAccountInsightKey === resolvingKey
                            ? <Loader className="size-3 animate-spin" />
                            : <CheckCircle2 className="size-3" />}
                        {t('Resolve')}
                    </Button>
                </div>
            </div>
        );
    };

    const accountInsightActions = ticketAccount ? (
        <div className="flex flex-wrap justify-end gap-2">
            <Button
                type="button"
                size="sm"
                variant="outline"
                data-ticket-account-risk
                onClick={() => void createTicketAccountInsight('risk')}
                disabled={Boolean(savingAccountInsightKey)}
            >
                {savingAccountInsightKey === `risk:${selectedIssue?.id}`
                    ? <Loader className="size-3.5 animate-spin" />
                    : <AlertTriangle className="size-3.5" />}
                {t('Add risk')}
            </Button>
            <Button
                type="button"
                size="sm"
                variant="outline"
                data-ticket-account-feature-request
                onClick={() => void createTicketAccountInsight('feature_request')}
                disabled={Boolean(savingAccountInsightKey)}
            >
                {savingAccountInsightKey === `feature_request:${selectedIssue?.id}`
                    ? <Loader className="size-3.5 animate-spin" />
                    : <Tag className="size-3.5" />}
                {t('Add feature request')}
            </Button>
        </div>
    ) : null;

    const statusFilterSelect = (
        <Select value={statusFilter} onValueChange={changeStatusFilter}>
            <SelectTrigger className="h-9 w-44">
                <SelectValue />
            </SelectTrigger>
            <SelectContent>
                <SelectItem value="all">{t('All')}</SelectItem>
                <SelectItem value="needs-response">{t('Needs response')}</SelectItem>
                <SelectItem value="approvals">{t('Approvals')}</SelectItem>
                <SelectItem value="reply-approvals">{t('Reply approvals')}</SelectItem>
                <SelectItem value="action-approvals">{t('Action approvals')}</SelectItem>
                <SelectItem value="unassigned">{t('Needs assignee')}</SelectItem>
                <SelectItem value="failed-delivery">{t('Failed delivery')}</SelectItem>
                <SelectItem value="low-csat">{t('Low CSAT')}</SelectItem>
                <SelectItem value="due-soon-sla">{t('SLA due soon')}</SelectItem>
                <SelectItem value="overdue-sla">{t('Overdue SLA')}</SelectItem>
                {kanbanLanes.map(option => (
                    <SelectItem key={option.value} value={option.value}>{t(option.label)}</SelectItem>
                ))}
            </SelectContent>
        </Select>
    );

    const queueFilterSelect = (
        <Select value={queueFilter} onValueChange={value => changeInboxFilters({ queueFilter: value })}>
            <SelectTrigger className="h-9 w-36">
                <SelectValue />
            </SelectTrigger>
            <SelectContent>
                <SelectItem value={ALL_QUEUES_VALUE}>{t('All queues')}</SelectItem>
                {queueOptions.map(option => (
                    <SelectItem key={option.queueKey} value={option.queueKey}>{option.name}</SelectItem>
                ))}
                <SelectItem value={NO_QUEUE_VALUE}>{t('No queue')}</SelectItem>
            </SelectContent>
        </Select>
    );

    const accountFilterSelect = (
        <Select value={accountFilter} onValueChange={value => changeInboxFilters({ accountFilter: value })}>
            <SelectTrigger className="h-9 w-40">
                <SelectValue />
            </SelectTrigger>
            <SelectContent>
                <SelectItem value={ALL_ACCOUNTS_VALUE}>{t('All accounts')}</SelectItem>
                {accountFilterOptions.map(option => (
                    <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))}
                <SelectItem value={NO_ACCOUNT_VALUE}>{t('No account')}</SelectItem>
            </SelectContent>
        </Select>
    );

    const channelFilterSelect = (
        <Select value={channelFilter} onValueChange={value => changeInboxFilters({ channelFilter: value })}>
            <SelectTrigger className="h-9 w-36">
                <SelectValue />
            </SelectTrigger>
            <SelectContent>
                <SelectItem value={ALL_CHANNELS_VALUE}>{t('All channels')}</SelectItem>
                {channelOptions.map(option => (
                    <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))}
                <SelectItem value={NO_CHANNEL_VALUE}>{t('No channel')}</SelectItem>
            </SelectContent>
        </Select>
    );

    const assigneeFilterSelect = (
        <Select value={assigneeFilter} onValueChange={value => changeInboxFilters({ assigneeFilter: value })}>
            <SelectTrigger className="h-9 w-40">
                <SelectValue />
            </SelectTrigger>
            <SelectContent>
                <SelectItem value={ALL_ASSIGNEES_VALUE}>{t('All assignees')}</SelectItem>
                <SelectItem value={MY_ASSIGNEE_VALUE}>{t('Mine')}</SelectItem>
                <SelectItem value={UNASSIGNED_VALUE}>{t('Unassigned')}</SelectItem>
                {assigneeFilterOptions.map(email => (
                    <SelectItem key={email} value={email.toLowerCase()}>{email}</SelectItem>
                ))}
            </SelectContent>
        </Select>
    );

    const tagFilterSelect = (
        <Select value={tagFilter} onValueChange={value => changeInboxFilters({ tagFilter: value })}>
            <SelectTrigger className="h-9 w-36">
                <SelectValue />
            </SelectTrigger>
            <SelectContent>
                <SelectItem value={ALL_TAGS_VALUE}>{t('All labels')}</SelectItem>
                {tagOptions.map(tag => (
                    <SelectItem key={tag} value={tag.toLowerCase()}>{tag}</SelectItem>
                ))}
                <SelectItem value={NO_TAGS_VALUE}>{t('No labels')}</SelectItem>
            </SelectContent>
        </Select>
    );

    const notificationsPanel = (
        <div className="rounded-md border bg-muted/20 p-2" data-inbox-notifications-panel>
            <div className="mb-2 flex items-center justify-between gap-2 text-xs font-medium text-muted-foreground">
                <span className="flex min-w-0 items-center gap-2">
                    <Bell className="size-3.5" />
                    {t('Notifications')}
                </span>
                {loadingNotifications ? (
                    <Loader className="size-3.5 animate-spin" />
                ) : (
                    <Badge variant="outline" className="h-5 px-1.5 text-[10px] font-normal">
                        {notifications.length}
                    </Badge>
                )}
            </div>
            <div className="max-h-40 space-y-1 overflow-y-auto">
                {notifications.length === 0 ? (
                    <div className="px-2 py-3 text-center text-[11px] text-muted-foreground">-</div>
                ) : (
                    notifications.slice(0, 5).map(notification => (
                        <button
                            key={notification.id}
                            type="button"
                            className="w-full rounded border bg-background px-2 py-1.5 text-left text-xs hover:bg-muted"
                            data-inbox-notification={notification.id}
                            onClick={() => void openNotification(notification)}
                        >
                            <div className="flex min-w-0 items-center justify-between gap-2">
                                <span className="truncate font-medium">{notification.title}</span>
                                <span className="shrink-0 text-[10px] text-muted-foreground">
                                    {formatTime(notification.created)}
                                </span>
                            </div>
                            {notification.body && (
                                <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
                                    {notification.body}
                                </div>
                            )}
                        </button>
                    ))
                )}
            </div>
        </div>
    );

    const channelCoverageSummary = channelActivationBacklog?.summary ?? null;
    const channelCoverageNextAction = channelActivationBacklog?.nextActions?.[0] ?? null;
    const channelCoverageHref = tenantId
        ? `/${encodeURIComponent(tenantId)}/${encodeURIComponent(projectId)}/channels?action=activation`
        : `/channels?action=activation`;
    const channelCoveragePanel = (loadingChannelCoverage || channelActivationBacklog) ? (
        <div
            className="rounded-md border bg-muted/20 p-2"
            data-inbox-channel-coverage
            data-inbox-channel-coverage-active={channelCoverageSummary?.activeSurfaces ?? ''}
            data-inbox-channel-coverage-ready={channelCoverageSummary?.readySurfaces ?? ''}
            data-inbox-channel-coverage-backlog={channelCoverageSummary?.backlogSurfaces ?? ''}
            data-inbox-channel-coverage-next-action={channelCoverageNextAction?.action ?? ''}
        >
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
                <div className="flex min-w-0 items-center gap-2 font-medium text-muted-foreground">
                    <Database className="size-3.5 shrink-0" />
                    <span className="truncate">{t('Channel coverage')}</span>
                    {loadingChannelCoverage && <Loader className="size-3 animate-spin" />}
                </div>
                <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 px-2 text-xs"
                    data-inbox-channel-coverage-open
                    onClick={() => navigate(channelCoverageHref)}
                >
                    <ExternalLink className="size-3" />
                    {t('Channels')}
                </Button>
            </div>
            {channelCoverageSummary && (
                <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
                    <div className="rounded border bg-background px-2 py-1">
                        <div className="text-[10px] uppercase text-muted-foreground">{t('Active')}</div>
                        <div className="text-sm font-semibold">{channelCoverageSummary.activeSurfaces}</div>
                    </div>
                    <div className="rounded border bg-background px-2 py-1">
                        <div className="text-[10px] uppercase text-muted-foreground">{t('Ready')}</div>
                        <div className="text-sm font-semibold">{channelCoverageSummary.readySurfaces}</div>
                    </div>
                    <div className="rounded border bg-background px-2 py-1">
                        <div className="text-[10px] uppercase text-muted-foreground">{t('Backlog')}</div>
                        <div className="text-sm font-semibold">{channelCoverageSummary.backlogSurfaces}</div>
                    </div>
                    <div className="rounded border bg-background px-2 py-1">
                        <div className="text-[10px] uppercase text-muted-foreground">{t('Missing env')}</div>
                        <div className="truncate text-sm font-semibold" title={channelCoverageSummary.requiredMissingEnvVars.join(', ')}>
                            {channelCoverageSummary.requiredMissingEnvVars.length}
                        </div>
                    </div>
                </div>
            )}
            {channelCoverageNextAction && (
                <div className="mt-2 flex min-w-0 flex-wrap items-center gap-2 rounded border bg-background px-2 py-1.5 text-xs">
                    <Badge variant="outline" className="font-normal">
                        {channelCoverageNextAction.surfaceLabel || channelCoverageNextAction.surfaceType}
                    </Badge>
                    <span className="min-w-0 flex-1 truncate font-medium">
                        {t(channelCoverageNextAction.title || 'Next channel action')}
                    </span>
                    <span className="min-w-0 truncate text-muted-foreground">
                        {t(channelCoverageNextAction.detail || channelCoverageNextAction.action || '')}
                    </span>
                </div>
            )}
        </div>
    ) : null;

    const ticketCreationProof = supportAnalytics?.launchProof?.ticketCreation ?? null;
    const ticketCreationReady = ticketCreationProof?.ready
        ?? Math.max((supportAnalytics?.activeChannels ?? 0) - (supportAnalytics?.activeChannelsWrongTicketMode ?? 0), 0);
    const ticketCreationBlocked = ticketCreationProof?.blocked ?? supportAnalytics?.activeChannelsWrongTicketMode ?? 0;
    const ticketCreationTotal = ticketCreationProof?.total ?? Math.max(supportAnalytics?.activeChannels ?? 0, ticketCreationReady + ticketCreationBlocked);
    const ticketCreationWrongMode = ticketCreationProof?.wrongMode ?? supportAnalytics?.activeChannelsWrongTicketMode ?? 0;
    const ticketCreationLifecycleReady = supportAnalytics?.activeChannelsWithLifecycleSmoke ?? 0;
    const ticketCreationLifecycleMissing = supportAnalytics?.activeChannelsMissingLifecycleSmoke ?? 0;
    const ticketCreationAutoPrepMissing = supportAnalytics?.activeChannelsWithoutAutoPrepare ?? 0;
    const topTicketCreationItem = ticketCreationProof?.items?.find(item => !item.ready) ?? ticketCreationProof?.items?.[0] ?? null;
    const ticketCreationNeedsAttention = ticketCreationBlocked > 0
        || ticketCreationLifecycleMissing > 0
        || ticketCreationAutoPrepMissing > 0;
    const ticketCreationHref = tenantId
        ? `/${encodeURIComponent(tenantId)}/${encodeURIComponent(projectId)}/channels?action=activation`
        : '/channels?action=activation';
    const ticketCreationPanel = (loadingSupportAnalytics || supportAnalytics) ? (
        <div
            className="rounded-md border bg-muted/20 p-2"
            data-inbox-ticket-creation-proof
            data-inbox-ticket-creation-proof-total={ticketCreationTotal}
            data-inbox-ticket-creation-proof-ready={ticketCreationReady}
            data-inbox-ticket-creation-proof-blocked={ticketCreationBlocked}
            data-inbox-ticket-creation-proof-wrong-mode={ticketCreationWrongMode}
            data-inbox-ticket-creation-proof-lifecycle-ready={ticketCreationLifecycleReady}
            data-inbox-ticket-creation-proof-lifecycle-missing={ticketCreationLifecycleMissing}
            data-inbox-ticket-creation-proof-auto-prep-missing={ticketCreationAutoPrepMissing}
            data-inbox-ticket-creation-proof-top-channel={topTicketCreationItem?.channelKey || topTicketCreationItem?.channelId || ''}
            data-inbox-ticket-creation-proof-top-mode={topTicketCreationItem?.mode || ''}
        >
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
                <div className="flex min-w-0 items-center gap-2 font-medium text-muted-foreground">
                    <InboxIcon className="size-3.5 shrink-0" />
                    <span className="truncate">{t('Ticket creation')}</span>
                    {loadingSupportAnalytics && <Loader className="size-3 animate-spin" />}
                </div>
                <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 px-2 text-xs"
                    data-inbox-ticket-creation-open
                    onClick={() => navigate(ticketCreationHref)}
                >
                    <ExternalLink className="size-3" />
                    {t('Channels')}
                </Button>
            </div>
            <div className="mb-2 flex min-w-0 flex-wrap items-center gap-2 rounded border bg-background px-2 py-1.5 text-xs">
                <Badge variant={ticketCreationNeedsAttention ? 'destructive' : 'secondary'} className="font-normal">
                    {ticketCreationReady}/{ticketCreationTotal} {t('ready')}
                </Badge>
                <span className="min-w-0 flex-1 truncate">
                    {ticketCreationNeedsAttention
                        ? t('Channel ticket creation needs proof.')
                        : t('New channel messages create tickets.')}
                </span>
            </div>
            <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
                <div className="rounded border bg-background px-2 py-1">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Ready')}</div>
                    <div className="text-sm font-semibold">{ticketCreationReady}</div>
                </div>
                <div className="rounded border bg-background px-2 py-1">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Blocked')}</div>
                    <div className="text-sm font-semibold">{ticketCreationBlocked}</div>
                </div>
                <div className="rounded border bg-background px-2 py-1">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Lifecycle')}</div>
                    <div className="text-sm font-semibold">{ticketCreationLifecycleReady}</div>
                </div>
                <div className="rounded border bg-background px-2 py-1">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Auto prep')}</div>
                    <div className="text-sm font-semibold">{ticketCreationAutoPrepMissing}</div>
                </div>
            </div>
            {topTicketCreationItem && (
                <div className="mt-2 flex min-w-0 flex-wrap items-center gap-2 rounded border bg-background px-2 py-1.5 text-xs">
                    <Badge variant={topTicketCreationItem.ready ? 'secondary' : 'outline'} className="font-normal">
                        {topTicketCreationItem.type || 'channel'}
                    </Badge>
                    <span className="min-w-0 flex-1 truncate">
                        {topTicketCreationItem.name || topTicketCreationItem.channelKey || t('Channel')}
                    </span>
                    <span className="min-w-0 truncate text-muted-foreground">
                        {topTicketCreationItem.ready ? t('per message') : t(topTicketCreationItem.detail || 'Set every-message ticketing')}
                    </span>
                </div>
            )}
        </div>
    ) : null;

    const replyRouteProof = supportAnalytics?.launchProof?.replyRoute ?? null;
    const replyRouteFallbackReady = supportAnalytics?.activeChannelsWithOutboundSmoke ?? 0;
    const replyRouteFallbackBlocked = (supportAnalytics?.activeChannelsMissingOutboundSmoke ?? 0)
        + (supportAnalytics?.activeEmailChannelsMissingDelivery ?? 0)
        + (supportAnalytics?.activeWebChatChannelsMissingDelivery ?? 0);
    const replyRouteReady = replyRouteProof?.ready ?? replyRouteFallbackReady;
    const replyRouteBlocked = replyRouteProof?.blocked ?? replyRouteFallbackBlocked;
    const replyRouteTotal = replyRouteProof?.total ?? Math.max(supportAnalytics?.activeChannels ?? 0, replyRouteReady + replyRouteBlocked);
    const replyRouteDeliveryFailures = (supportAnalytics?.failedDeliveryRuns ?? 0)
        + (supportAnalytics?.failedOutboundMessages ?? 0)
        + (supportAnalytics?.failedWebChatChannelDeliveryProofs ?? 0);
    const replyRouteSmokeFailures = supportAnalytics?.failedOutboundChannelSmokeRuns ?? 0;
    const replyRouteNeedsAttention = replyRouteBlocked > 0 || replyRouteDeliveryFailures > 0;
    const topReplyRouteItem = replyRouteProof?.items?.find(item => !item.ready) ?? replyRouteProof?.items?.[0] ?? null;
    const replyRouteHref = tenantId
        ? replyRouteDeliveryFailures > 0
            ? `/${encodeURIComponent(tenantId)}/${encodeURIComponent(projectId)}/inbox?filter=failed-delivery`
            : `/${encodeURIComponent(tenantId)}/${encodeURIComponent(projectId)}/channels`
        : replyRouteDeliveryFailures > 0
            ? '/inbox?filter=failed-delivery'
            : '/channels';
    const replyRouteProofPanel = (loadingSupportAnalytics || supportAnalytics) ? (
        <div
            className="rounded-md border bg-muted/20 p-2"
            data-inbox-reply-route-proof
            data-inbox-reply-route-proof-total={replyRouteTotal}
            data-inbox-reply-route-proof-ready={replyRouteReady}
            data-inbox-reply-route-proof-blocked={replyRouteBlocked}
            data-inbox-reply-route-proof-failures={replyRouteDeliveryFailures}
            data-inbox-reply-route-proof-smoke-failures={replyRouteSmokeFailures}
            data-inbox-reply-route-proof-top-channel={topReplyRouteItem?.channelKey || topReplyRouteItem?.channelId || ''}
            data-inbox-reply-route-proof-top-proof-key={topReplyRouteItem?.proofKey || ''}
        >
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
                <div className="flex min-w-0 items-center gap-2 font-medium text-muted-foreground">
                    <Send className="size-3.5 shrink-0" />
                    <span className="truncate">{t('Reply-route proof')}</span>
                    {loadingSupportAnalytics && <Loader className="size-3 animate-spin" />}
                </div>
                <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 px-2 text-xs"
                    data-inbox-reply-route-open
                    onClick={() => navigate(replyRouteHref)}
                >
                    <ExternalLink className="size-3" />
                    {t(replyRouteDeliveryFailures > 0 ? 'Failures' : 'Channels')}
                </Button>
            </div>
            <div className="mb-2 flex min-w-0 flex-wrap items-center gap-2 rounded border bg-background px-2 py-1.5 text-xs">
                <Badge variant={replyRouteNeedsAttention ? 'destructive' : 'secondary'} className="font-normal">
                    {replyRouteReady}/{replyRouteTotal} {t('ready')}
                </Badge>
                <span className="min-w-0 flex-1 truncate">
                    {!replyRouteNeedsAttention
                        ? t('Agents can answer from the app.')
                        : t('Reply delivery needs proof.')}
                </span>
            </div>
            <div className="grid grid-cols-3 gap-2">
                <div className="rounded border bg-background px-2 py-1">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Ready')}</div>
                    <div className="text-sm font-semibold">{replyRouteReady}</div>
                </div>
                <div className="rounded border bg-background px-2 py-1">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Blocked')}</div>
                    <div className="text-sm font-semibold">{replyRouteBlocked}</div>
                </div>
                <div className="rounded border bg-background px-2 py-1">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Failures')}</div>
                    <div className="text-sm font-semibold">{replyRouteDeliveryFailures}</div>
                </div>
            </div>
            {replyRouteSmokeFailures > 0 && !replyRouteNeedsAttention && (
                <div className="mt-2 rounded border bg-background px-2 py-1.5 text-xs text-muted-foreground">
                    {t('Historical outbound smoke failures')}: {replyRouteSmokeFailures}
                </div>
            )}
            {topReplyRouteItem && (
                <div className="mt-2 flex min-w-0 flex-wrap items-center gap-2 rounded border bg-background px-2 py-1.5 text-xs">
                    <Badge variant={topReplyRouteItem.ready ? 'secondary' : 'outline'} className="font-normal">
                        {topReplyRouteItem.type || topReplyRouteItem.provider || 'route'}
                    </Badge>
                    <span className="min-w-0 flex-1 truncate">
                        {topReplyRouteItem.name || topReplyRouteItem.channelKey || topReplyRouteItem.detail || t('Reply route')}
                    </span>
                    <span className="min-w-0 truncate text-muted-foreground">
                        {topReplyRouteItem.ready ? t('Can answer') : t('No route proof')}
                    </span>
                </div>
            )}
        </div>
    ) : null;

    const ticketWorkflowProof = supportAnalytics?.launchProof?.ticketWorkflow ?? null;
    const ticketWorkflowReady = ticketWorkflowProof?.ready
        ?? ((supportAnalytics?.successfulWorkflowLifecycleProofs ?? 0) > 0 && (supportAnalytics?.unassignedIssues ?? 0) === 0);
    const ticketWorkflowTransitions = ticketWorkflowProof?.transitions ?? supportAnalytics?.workflowTransitionEvents ?? 0;
    const ticketWorkflowOngoing = ticketWorkflowProof?.ongoingTransitions ?? supportAnalytics?.workflowOngoingTransitions ?? 0;
    const ticketWorkflowDone = ticketWorkflowProof?.doneTransitions ?? supportAnalytics?.workflowDoneTransitions ?? 0;
    const ticketWorkflowIssues = ticketWorkflowProof?.successfulIssues ?? supportAnalytics?.successfulWorkflowLifecycleProofs ?? 0;
    const ticketWorkflowUnassigned = supportAnalytics?.unassignedIssues ?? 0;
    const ticketWorkflowOpenWork = supportAnalytics?.openWorkloadIssues ?? 0;
    const ticketWorkflowCapacity = supportAnalytics?.queueOwnersAtCapacity ?? 0;
    const ticketWorkflowNeedsAttention = !ticketWorkflowReady || ticketWorkflowUnassigned > 0 || ticketWorkflowCapacity > 0;
    const topTicketWorkflowItem = ticketWorkflowProof?.items?.[0] ?? null;
    const ticketWorkflowHref = tenantId
        ? ticketWorkflowUnassigned > 0
            ? `/${encodeURIComponent(tenantId)}/${encodeURIComponent(projectId)}/inbox?filter=unassigned`
            : `/${encodeURIComponent(tenantId)}/${encodeURIComponent(projectId)}/inbox?view=board`
        : ticketWorkflowUnassigned > 0
            ? '/inbox?filter=unassigned'
            : '/inbox?view=board';
    const ticketWorkflowPanel = (loadingSupportAnalytics || supportAnalytics) ? (
        <div
            className="rounded-md border bg-muted/20 p-2"
            data-inbox-ticket-workflow-proof
            data-inbox-ticket-workflow-proof-ready={ticketWorkflowReady ? 'true' : 'false'}
            data-inbox-ticket-workflow-proof-transitions={ticketWorkflowTransitions}
            data-inbox-ticket-workflow-proof-ongoing={ticketWorkflowOngoing}
            data-inbox-ticket-workflow-proof-done={ticketWorkflowDone}
            data-inbox-ticket-workflow-proof-issues={ticketWorkflowIssues}
            data-inbox-ticket-workflow-proof-unassigned={ticketWorkflowUnassigned}
            data-inbox-ticket-workflow-proof-open-work={ticketWorkflowOpenWork}
            data-inbox-ticket-workflow-proof-capacity={ticketWorkflowCapacity}
            data-inbox-ticket-workflow-proof-top-issue={topTicketWorkflowItem?.issueId ?? ''}
            data-inbox-ticket-workflow-proof-top-events={(topTicketWorkflowItem?.eventIds ?? []).join(',')}
        >
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
                <div className="flex min-w-0 items-center gap-2 font-medium text-muted-foreground">
                    <Columns3 className="size-3.5 shrink-0" />
                    <span className="truncate">{t('Ticket workflow')}</span>
                    {loadingSupportAnalytics && <Loader className="size-3 animate-spin" />}
                </div>
                <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 px-2 text-xs"
                    data-inbox-ticket-workflow-open
                    onClick={() => navigate(ticketWorkflowHref)}
                >
                    <ExternalLink className="size-3" />
                    {t(ticketWorkflowUnassigned > 0 ? 'Unassigned' : 'Board')}
                </Button>
            </div>
            <div className="mb-2 flex min-w-0 flex-wrap items-center gap-2 rounded border bg-background px-2 py-1.5 text-xs">
                <Badge variant={ticketWorkflowNeedsAttention ? 'destructive' : 'secondary'} className="font-normal">
                    {ticketWorkflowReady ? t('Ready') : t('Blocked')}
                </Badge>
                <span className="min-w-0 flex-1 truncate">
                    {ticketWorkflowNeedsAttention
                        ? t('Assignee or board proof needs attention.')
                        : t('Tickets have owner and Kanban proof.')}
                </span>
            </div>
            <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
                <div className="rounded border bg-background px-2 py-1">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Active')}</div>
                    <div className="text-sm font-semibold">{ticketWorkflowOpenWork}</div>
                </div>
                <div className="rounded border bg-background px-2 py-1">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Unassigned')}</div>
                    <div className="text-sm font-semibold">{ticketWorkflowUnassigned}</div>
                </div>
                <div className="rounded border bg-background px-2 py-1">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Transitions')}</div>
                    <div className="text-sm font-semibold">{ticketWorkflowTransitions}</div>
                </div>
                <div className="rounded border bg-background px-2 py-1">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Done')}</div>
                    <div className="text-sm font-semibold">{ticketWorkflowDone}</div>
                </div>
            </div>
            {ticketWorkflowCapacity > 0 && (
                <div className="mt-2 rounded border bg-background px-2 py-1.5 text-xs text-muted-foreground">
                    {t('Queue owners at capacity')}: {ticketWorkflowCapacity}
                </div>
            )}
            {topTicketWorkflowItem && (
                <div className="mt-2 flex min-w-0 flex-wrap items-center gap-2 rounded border bg-background px-2 py-1.5 text-xs">
                    <Badge variant="outline" className="font-normal">
                        {topTicketWorkflowItem.issueId || t('ticket')}
                    </Badge>
                    <span className="min-w-0 flex-1 truncate">
                        {topTicketWorkflowItem.detail || topTicketWorkflowItem.label || t('Ticket moved through board')}
                    </span>
                    <span className="min-w-0 truncate text-muted-foreground">
                        {ticketWorkflowOngoing}/{ticketWorkflowDone} {t('steps')}
                    </span>
                </div>
            )}
        </div>
    ) : null;

    const accountActionQueue = supportAnalytics?.accountActionQueue ?? [];
    const topAccountAction = accountActionQueue[0] ?? null;
    const topAccountActionMeta = topAccountAction?.action ?? null;
    const accountActionHref = (() => {
        if (!topAccountAction) {
            return tenantId
                ? `/${encodeURIComponent(tenantId)}/${encodeURIComponent(projectId)}/accounts`
                : '/accounts';
        }
        const base = tenantId
            ? `/${encodeURIComponent(tenantId)}/${encodeURIComponent(projectId)}`
            : '';
        const accountFilterValue = encodeURIComponent(`id:${topAccountAction.accountId}`);
        if (topAccountActionMeta?.route === 'channels') return `${base}/channels`;
        if (topAccountActionMeta?.route === 'inbox') return `${base}/inbox?account=${accountFilterValue}`;
        return `${base}/accounts/${encodeURIComponent(topAccountAction.accountId)}`;
    })();
    const accountActionPanel = (loadingSupportAnalytics || supportAnalytics) ? (
        <div
            className="rounded-md border bg-muted/20 p-2"
            data-inbox-account-action
            data-inbox-account-action-count={supportAnalytics?.accountsNeedingAction ?? ''}
            data-inbox-account-action-risks={supportAnalytics?.openAccountRisks ?? ''}
            data-inbox-account-action-features={supportAnalytics?.featureRequests ?? ''}
            data-inbox-account-action-kind={topAccountActionMeta?.kind ?? ''}
            data-inbox-account-action-health={topAccountAction?.healthStatus ?? ''}
            data-inbox-account-action-route={topAccountActionMeta?.route ?? ''}
            data-inbox-account-action-score={topAccountActionMeta?.score ?? ''}
        >
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
                <div className="flex min-w-0 items-center gap-2 font-medium text-muted-foreground">
                    <Building2 className="size-3.5 shrink-0" />
                    <span className="truncate">{t('Account action')}</span>
                    {loadingSupportAnalytics && <Loader className="size-3 animate-spin" />}
                </div>
                <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 px-2 text-xs"
                    data-inbox-account-action-open
                    onClick={() => navigate(accountActionHref)}
                >
                    <ExternalLink className="size-3" />
                    {t(topAccountActionMeta?.route === 'inbox' ? 'Tickets' : topAccountActionMeta?.route === 'channels' ? 'Channels' : 'Account')}
                </Button>
            </div>
            {supportAnalytics && (
                <div className="grid grid-cols-3 gap-2">
                    <div className="rounded border bg-background px-2 py-1">
                        <div className="text-[10px] uppercase text-muted-foreground">{t('Actions')}</div>
                        <div className="text-sm font-semibold">{supportAnalytics.accountsNeedingAction}</div>
                    </div>
                    <div className="rounded border bg-background px-2 py-1">
                        <div className="text-[10px] uppercase text-muted-foreground">{t('Risks')}</div>
                        <div className="text-sm font-semibold">{supportAnalytics.openAccountRisks}</div>
                    </div>
                    <div className="rounded border bg-background px-2 py-1">
                        <div className="text-[10px] uppercase text-muted-foreground">{t('Features')}</div>
                        <div className="text-sm font-semibold">{supportAnalytics.featureRequests}</div>
                    </div>
                </div>
            )}
            {topAccountAction ? (
                <div className="mt-2 flex min-w-0 flex-wrap items-center gap-2 rounded border bg-background px-2 py-1.5 text-xs">
                    <Badge variant={topAccountAction.healthStatus === 'at_risk' ? 'destructive' : 'outline'} className="font-normal">
                        {topAccountAction.healthStatus || 'unknown'}
                    </Badge>
                    <span className="min-w-0 flex-1 truncate font-medium">
                        {topAccountAction.name || topAccountAction.domain || topAccountAction.accountKey || t('Account')}
                    </span>
                    <span className="min-w-0 truncate text-muted-foreground">
                        {t(topAccountActionMeta?.label || topAccountAction.nextAction || 'Review')}
                    </span>
                </div>
            ) : supportAnalytics && (
                <div className="mt-2 rounded border bg-background px-2 py-1.5 text-xs text-muted-foreground">
                    {t('No account action waiting.')}
                </div>
            )}
        </div>
    ) : null;

    const humanLoopProof = supportAnalytics?.launchProof?.humanLoop ?? null;
    const channelAutopilotProof = supportAnalytics?.launchProof?.channelAutopilot ?? null;
    const humanLoopReady = humanLoopProof?.ready
        ?? ((supportAnalytics?.humanLoopAutomationRules ?? 0) > 0 && (supportAnalytics?.successfulHumanLoopAutomationRuns ?? 0) > 0);
    const humanLoopRules = humanLoopProof?.rules ?? supportAnalytics?.humanLoopAutomationRules ?? 0;
    const humanLoopRuns = humanLoopProof?.successfulRuns ?? supportAnalytics?.successfulHumanLoopAutomationRuns ?? 0;
    const humanLoopPending = humanLoopProof?.pendingApprovals ?? supportAnalytics?.issuesNeedingApproval ?? 0;
    const channelAutopilotTotal = channelAutopilotProof?.total ?? supportAnalytics?.activeChannels ?? 0;
    const channelAutopilotReady = channelAutopilotProof?.ready ?? supportAnalytics?.activeChannelsWithAutopilotPrepPackage ?? 0;
    const channelAutopilotBlocked = channelAutopilotProof?.blocked ?? supportAnalytics?.activeChannelsMissingAutopilotPrepPackage ?? 0;
    const autopilotHref = tenantId
        ? `/${encodeURIComponent(tenantId)}/${encodeURIComponent(projectId)}/automations`
        : '/automations';
    const approvalsHref = tenantId
        ? `/${encodeURIComponent(tenantId)}/${encodeURIComponent(projectId)}/inbox?filter=approvals`
        : '/inbox?filter=approvals';
    const automationProofPanel = (loadingSupportAnalytics || supportAnalytics) ? (
        <div
            className="rounded-md border bg-muted/20 p-2"
            data-inbox-human-loop-proof
            data-inbox-human-loop-proof-ready={humanLoopReady ? 'true' : 'false'}
            data-inbox-human-loop-proof-rules={humanLoopRules}
            data-inbox-human-loop-proof-runs={humanLoopRuns}
            data-inbox-human-loop-proof-pending={humanLoopPending}
            data-inbox-channel-autopilot-proof-ready={channelAutopilotReady}
            data-inbox-channel-autopilot-proof-total={channelAutopilotTotal}
            data-inbox-channel-autopilot-proof-blocked={channelAutopilotBlocked}
        >
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
                <div className="flex min-w-0 items-center gap-2 font-medium text-muted-foreground">
                    <Sparkles className="size-3.5 shrink-0" />
                    <span className="truncate">{t('Human-loop automation')}</span>
                    {loadingSupportAnalytics && <Loader className="size-3 animate-spin" />}
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                    {humanLoopPending > 0 && (
                        <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-xs"
                            data-inbox-human-loop-approvals
                            onClick={() => navigate(approvalsHref)}
                        >
                            <UserCheck className="size-3" />
                            {t('Approvals')}
                        </Button>
                    )}
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 px-2 text-xs"
                        data-inbox-human-loop-automations
                        onClick={() => navigate(autopilotHref)}
                    >
                        <ExternalLink className="size-3" />
                        {t('Automations')}
                    </Button>
                </div>
            </div>
            <div className="mb-2 flex min-w-0 flex-wrap items-center gap-2 rounded border bg-background px-2 py-1.5 text-xs">
                <Badge variant={humanLoopReady ? 'secondary' : 'destructive'} className="font-normal">
                    {humanLoopReady ? t('Ready') : t('Blocked')}
                </Badge>
                <span className="min-w-0 flex-1 truncate">
                    {humanLoopReady
                        ? t('Agent prepares, editor approves.')
                        : t('Add approval-required agent automation.')}
                </span>
            </div>
            <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
                <div className="rounded border bg-background px-2 py-1">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Rules')}</div>
                    <div className="text-sm font-semibold">{humanLoopRules}</div>
                </div>
                <div className="rounded border bg-background px-2 py-1">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Proof runs')}</div>
                    <div className="text-sm font-semibold">{humanLoopRuns}</div>
                </div>
                <div className="rounded border bg-background px-2 py-1">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Pending')}</div>
                    <div className="text-sm font-semibold">{humanLoopPending}</div>
                </div>
                <div className="rounded border bg-background px-2 py-1">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Channels')}</div>
                    <div className="text-sm font-semibold">{channelAutopilotReady}/{channelAutopilotTotal}</div>
                </div>
            </div>
            {channelAutopilotBlocked > 0 && (
                <div className="mt-2 rounded border bg-background px-2 py-1.5 text-xs text-muted-foreground">
                    {t('Channel autopilot proof blocked')}: {channelAutopilotBlocked}
                </div>
            )}
        </div>
    ) : null;

    const knowledgeAssistProof = supportAnalytics?.launchProof?.knowledgeAssist ?? null;
    const knowledgeAssistReady = knowledgeAssistProof?.ready
        ?? ((supportAnalytics?.successfulKnowledgeAssistRuns ?? 0) > 0 && (supportAnalytics?.openKnowledgeGaps ?? 0) === 0);
    const knowledgeAssistRuns = knowledgeAssistProof?.successfulRuns ?? supportAnalytics?.successfulKnowledgeAssistRuns ?? 0;
    const knowledgeAssistCitations = knowledgeAssistProof?.citationRuns ?? 0;
    const knowledgeAssistGapRuns = knowledgeAssistProof?.gapRuns ?? 0;
    const knowledgeAssistOpenGaps = knowledgeAssistProof?.openGaps ?? supportAnalytics?.openKnowledgeGaps ?? 0;
    const knowledgeAssistArticles = knowledgeAssistProof?.articles ?? supportAnalytics?.knowledgeArticles ?? 0;
    const topKnowledgeAssistItem = knowledgeAssistProof?.items?.[0] ?? null;
    const knowledgeHref = tenantId
        ? `/${encodeURIComponent(tenantId)}/${encodeURIComponent(projectId)}/knowledge`
        : '/knowledge';
    const knowledgeAssistPanel = (loadingSupportAnalytics || supportAnalytics) ? (
        <div
            className="rounded-md border bg-muted/20 p-2"
            data-inbox-knowledge-assist-proof
            data-inbox-knowledge-assist-proof-ready={knowledgeAssistReady ? 'true' : 'false'}
            data-inbox-knowledge-assist-proof-runs={knowledgeAssistRuns}
            data-inbox-knowledge-assist-proof-citations={knowledgeAssistCitations}
            data-inbox-knowledge-assist-proof-gap-runs={knowledgeAssistGapRuns}
            data-inbox-knowledge-assist-proof-open-gaps={knowledgeAssistOpenGaps}
            data-inbox-knowledge-assist-proof-articles={knowledgeAssistArticles}
            data-inbox-knowledge-assist-proof-top-gap={topKnowledgeAssistItem?.knowledgeGapId ?? ''}
        >
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
                <div className="flex min-w-0 items-center gap-2 font-medium text-muted-foreground">
                    <BookOpen className="size-3.5 shrink-0" />
                    <span className="truncate">{t('Knowledge assist')}</span>
                    {loadingSupportAnalytics && <Loader className="size-3 animate-spin" />}
                </div>
                <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 px-2 text-xs"
                    data-inbox-knowledge-assist-open
                    onClick={() => navigate(knowledgeHref)}
                >
                    <ExternalLink className="size-3" />
                    {t('Knowledge')}
                </Button>
            </div>
            <div className="mb-2 flex min-w-0 flex-wrap items-center gap-2 rounded border bg-background px-2 py-1.5 text-xs">
                <Badge variant={knowledgeAssistReady ? 'secondary' : 'destructive'} className="font-normal">
                    {knowledgeAssistReady ? t('Ready') : t('Blocked')}
                </Badge>
                <span className="min-w-0 flex-1 truncate">
                    {knowledgeAssistOpenGaps > 0
                        ? t('Knowledge gaps need article coverage.')
                        : t('Agent answers have knowledge proof.')}
                </span>
            </div>
            <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
                <div className="rounded border bg-background px-2 py-1">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Runs')}</div>
                    <div className="text-sm font-semibold">{knowledgeAssistRuns}</div>
                </div>
                <div className="rounded border bg-background px-2 py-1">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Cited')}</div>
                    <div className="text-sm font-semibold">{knowledgeAssistCitations}</div>
                </div>
                <div className="rounded border bg-background px-2 py-1">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Gaps')}</div>
                    <div className="text-sm font-semibold">{knowledgeAssistOpenGaps}</div>
                </div>
                <div className="rounded border bg-background px-2 py-1">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Articles')}</div>
                    <div className="text-sm font-semibold">{knowledgeAssistArticles}</div>
                </div>
            </div>
            {topKnowledgeAssistItem && (
                <div className="mt-2 flex min-w-0 flex-wrap items-center gap-2 rounded border bg-background px-2 py-1.5 text-xs">
                    <Badge variant="outline" className="font-normal">
                        {(topKnowledgeAssistItem.citationCount ?? 0) > 0 ? t('cited') : topKnowledgeAssistItem.knowledgeGapId ? t('gap') : t('proof')}
                    </Badge>
                    <span className="min-w-0 flex-1 truncate">
                        {topKnowledgeAssistItem.detail || topKnowledgeAssistItem.label || t('Knowledge assist proof')}
                    </span>
                </div>
            )}
        </div>
    ) : null;

    const supportViewPresetCounts = useMemo(() => {
        const counts = new Map<string, number>();
        for (const preset of supportViewPresets) {
            counts.set(preset.key, issues.filter(issue => issueMatchesInboxStatus(issue, preset.filters.statusFilter)).length);
        }
        return counts;
    }, [issues]);

    const currentSupportViewFilters = currentInboxFilters();
    const supportViewIcon = (key: string) => {
        if (key === 'needs-response') return <Send className="size-3.5" />;
        if (key === 'approvals') return <UserCheck className="size-3.5" />;
        if (key === 'unassigned') return <InboxIcon className="size-3.5" />;
        if (key === 'overdue-sla') return <AlertTriangle className="size-3.5" />;
        if (key === 'due-soon-sla') return <Clock className="size-3.5" />;
        if (key === 'failed-delivery') return <RefreshCw className="size-3.5" />;
        return <Star className="size-3.5" />;
    };

    const supportViewsPanel = (
        <div className="rounded-md border bg-muted/20 p-2" data-inbox-support-views>
            <div className="mb-2 flex items-center justify-between gap-2 text-xs font-medium text-muted-foreground">
                <span className="flex items-center gap-2">
                    <Columns3 className="size-3.5" />
                    {t('Support views')}
                </span>
                <Badge variant="outline" className="h-5 px-1.5 text-[10px] font-normal">
                    {supportViewPresets.length} {t('default')}
                </Badge>
            </div>
            <div className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-4">
                {supportViewPresets.map(preset => {
                    const active = inboxFiltersEqual(currentSupportViewFilters, preset.filters);
                    const count = supportViewPresetCounts.get(preset.key) ?? 0;
                    return (
                        <Button
                            key={preset.key}
                            type="button"
                            variant={active ? 'secondary' : 'outline'}
                            className="h-auto min-h-16 justify-start gap-2 px-2 py-2 text-left"
                            data-inbox-support-view={preset.key}
                            data-inbox-support-view-active={active ? 'true' : 'false'}
                            onClick={() => changeInboxFilters(preset.filters)}
                        >
                            <span className="mt-0.5 shrink-0 text-muted-foreground">
                                {supportViewIcon(preset.key)}
                            </span>
                            <span className="min-w-0 flex-1">
                                <span className="flex items-center justify-between gap-2">
                                    <span className="truncate text-xs font-medium">{t(preset.label)}</span>
                                    <Badge variant="outline" className="h-5 shrink-0 px-1.5 text-[10px] font-normal">
                                        {count}
                                    </Badge>
                                </span>
                                <span className="line-clamp-2 whitespace-normal text-[11px] font-normal leading-4 text-muted-foreground">
                                    {t(preset.description)}
                                </span>
                            </span>
                        </Button>
                    );
                })}
            </div>
        </div>
    );

    const savedViewsPanel = (
        <div className="rounded-md border bg-muted/20 p-2">
            <div className="mb-2 flex items-center justify-between gap-2 text-xs font-medium text-muted-foreground">
                <span className="flex items-center gap-2">
                    <BookOpen className="size-3.5" />
                    {t('Views')}
                </span>
                {loadingViews && <Loader className="size-3.5 animate-spin" />}
            </div>
            {inboxViews.length === 0 ? (
                <div className="text-xs text-muted-foreground">-</div>
            ) : (
                <div className="flex flex-wrap gap-1.5">
                    {inboxViews.map(view => (
                        <div key={view.id} className="flex min-w-0 items-center rounded-md border bg-background">
                            <button
                                type="button"
                                className="min-w-0 truncate px-2 py-1 text-left text-xs hover:bg-muted"
                                data-inbox-saved-view={view.id}
                                onClick={() => applyInboxView(view)}
                                title={view.name}
                            >
                                {view.name}
                            </button>
                            <Badge variant="outline" className="mx-1 hidden h-5 shrink-0 px-1.5 text-[10px] font-normal sm:inline-flex">
                                {t(view.visibility === 'shared' ? 'Shared' : 'Private')}
                            </Badge>
                            {canManageInboxView(view) && (
                                <button
                                    type="button"
                                    className="border-l px-1.5 py-1 text-muted-foreground hover:text-foreground"
                                    onClick={() => openEditInboxViewDialog(view)}
                                    aria-label={t('Edit view')}
                                >
                                    <Pencil className="size-3" />
                                </button>
                            )}
                            <button
                                type="button"
                                className="border-l px-1.5 py-1 text-muted-foreground hover:text-foreground"
                                onClick={() => void deleteSavedView(view)}
                                disabled={deletingViewId === view.id || !canManageInboxView(view)}
                                aria-label={t('Delete view')}
                            >
                                {deletingViewId === view.id ? <Loader className="size-3 animate-spin" /> : <X className="size-3" />}
                            </button>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );

    const replyMacroControls = (
        <div className="rounded-md border bg-muted/20 p-2">
            <div className="mb-2 flex items-center justify-between gap-2 text-xs font-medium text-muted-foreground">
                <span className="flex items-center gap-2">
                    <Pencil className="size-3.5" />
                    {t('Reply macros')}
                </span>
                {loadingReplyMacros && <Loader className="size-3.5 animate-spin" />}
            </div>
            <div className="flex flex-wrap items-center gap-2">
                <Select value={selectedReplyMacroId} onValueChange={setSelectedReplyMacroId}>
                    <SelectTrigger className="h-8 min-w-0 flex-1" data-reply-macro-select>
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value={NO_REPLY_MACRO_VALUE}>{t('Select macro')}</SelectItem>
                        {replyMacros.map(macro => (
                            <SelectItem key={macro.id} value={macro.id} data-reply-macro-option={macro.id}>{macro.title}</SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-8 px-2 text-xs"
                    data-reply-macro-insert
                    disabled={!selectedReplyMacro || renderingMacroId === selectedReplyMacro.id}
                    onClick={() => void applyReplyMacro('append')}
                >
                    {renderingMacroId === selectedReplyMacro?.id
                        ? <Loader className="size-3.5 animate-spin" />
                        : <Plus className="size-3.5" />}
                    {t('Insert')}
                </Button>
                <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-8 px-2 text-xs"
                    data-reply-macro-replace
                    disabled={!selectedReplyMacro || renderingMacroId === selectedReplyMacro.id}
                    onClick={() => void applyReplyMacro('replace')}
                >
                    {renderingMacroId === selectedReplyMacro?.id
                        ? <Loader className="size-3.5 animate-spin" />
                        : <Copy className="size-3.5" />}
                    {t('Replace')}
                </Button>
                <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="h-8 px-2 text-xs"
                    data-reply-macro-save-open
                    disabled={!replyDraft.trim()}
                    onClick={openSaveMacroDialog}
                >
                    <Save className="size-3.5" />
                    {t('Save macro')}
                </Button>
                <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="h-8 px-2 text-xs"
                    disabled={!selectedReplyMacro || Boolean(archivingMacroId) || (selectedReplyMacro ? !canManageReplyMacro(selectedReplyMacro) : false)}
                    onClick={() => void archiveSelectedReplyMacro()}
                    aria-label={t('Archive macro')}
                    title={selectedReplyMacro && !canManageReplyMacro(selectedReplyMacro) ? t('Only the owner can archive this macro') : undefined}
                >
                    {archivingMacroId === selectedReplyMacro?.id
                        ? <Loader className="size-3.5 animate-spin" />
                        : <Trash2 className="size-3.5" />}
                    {t('Archive')}
                </Button>
            </div>
            {selectedReplyMacro && selectedReplyMacro.tags.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                    {selectedReplyMacro.tags.slice(0, 4).map(tag => (
                        <Badge key={tag} variant="outline" className="font-normal">{tag}</Badge>
                    ))}
                </div>
            )}
        </div>
    );

    const replyRoutePanel = selectedIssue ? (
        <div
            className="rounded-md border bg-muted/20 p-2 text-sm"
            data-ticket-reply-route
            data-ticket-reply-route-ready={selectedReplyReadiness ? String(selectedReplyReadiness.ready) : ''}
            data-ticket-reply-route-status={selectedReplyReadiness?.status ?? ''}
            data-ticket-reply-route-provider={selectedReplyReadiness?.provider ?? ''}
            data-ticket-reply-route-transport={selectedReplyReadiness?.transport ?? ''}
            data-ticket-reply-route-channel-key={selectedReplyReadiness?.channelKey ?? ''}
            data-ticket-reply-route-blocked={selectedReplySendBlocked ? 'true' : 'false'}
            data-ticket-reply-route-adapter-transport={selectedReplyAdapter?.selectedTransport ?? ''}
            data-ticket-reply-route-adapter-provider={selectedReplyAdapter?.selectedProvider ?? ''}
            data-ticket-reply-route-adapter-native={selectedReplyAdapter?.nativeProvider === undefined ? '' : String(selectedReplyAdapter.nativeProvider)}
            data-ticket-reply-route-adapter-webhook={selectedReplyAdapter?.webhookAdapter === undefined ? '' : String(selectedReplyAdapter.webhookAdapter)}
        >
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-1.5 font-medium">
                    <Send className="size-3.5 shrink-0 text-muted-foreground" />
                    <span className="truncate">{t('Reply route')}</span>
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                    {selectedReplyRouteFixHref && (
                        <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-7 gap-1.5 px-2 text-xs"
                            data-ticket-reply-route-fix
                            data-ticket-reply-route-fix-channel={selectedReplyRouteFixChannel}
                            data-ticket-reply-route-fix-action={selectedReplyRouteFixAction}
                            data-ticket-reply-route-fix-blockers={selectedReplyReadiness?.blockers.join(',') ?? ''}
                            data-ticket-reply-route-fix-env={selectedReplyReadiness?.missingEnvVars.join(',') ?? ''}
                            onClick={() => navigate(selectedReplyRouteFixHref)}
                        >
                            <ExternalLink className="size-3.5" />
                            {selectedReplySendBlocked ? t('Fix route') : t('Open setup')}
                        </Button>
                    )}
                    {selectedReplyReadiness ? (
                        <Badge variant={selectedReplyReadiness.ready ? 'secondary' : 'destructive'} className="font-normal">
                            {selectedReplyReadiness.ready ? t('Ready') : t('Blocked')}
                        </Badge>
                    ) : (
                        <Badge variant="outline" className="font-normal">{t('Unknown')}</Badge>
                    )}
                </div>
            </div>
            <div className="grid gap-2 sm:grid-cols-3">
                <div className="rounded-md border bg-background p-2">
                    <div className="text-[11px] text-muted-foreground">{t('Provider')}</div>
                    <div className="truncate font-medium">{selectedReplyReadiness?.provider || selectedIssue.channel || '-'}</div>
                </div>
                <div className="rounded-md border bg-background p-2">
                    <div className="text-[11px] text-muted-foreground">{t('Transport')}</div>
                    <div className="truncate font-medium">{selectedReplyReadiness?.transport || '-'}</div>
                </div>
                <div className="rounded-md border bg-background p-2">
                    <div className="text-[11px] text-muted-foreground">{t('Channel')}</div>
                    <div className="truncate font-medium">{selectedReplyReadiness?.channelKey || selectedReplyRouteLabel || selectedIssue.channel || '-'}</div>
                </div>
            </div>
            {selectedReplyTargetRows.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5" data-ticket-reply-route-targets>
                    {selectedReplyTargetRows.slice(0, 4).map(row => (
                        <Badge key={`${row.label}:${row.value}`} variant="outline" className="max-w-full truncate font-normal" title={row.value}>
                            {t(row.label)}: {shortProofValue(row.value, 42)}
                        </Badge>
                    ))}
                </div>
            )}
            {selectedReplyAdapter && (
                <div className="mt-2 flex flex-wrap gap-1.5" data-ticket-reply-route-adapter>
                    <Badge variant="secondary" className="font-normal">
                        {t('Selected')}: {t(replyAdapterTransportLabel(selectedReplyAdapter.selectedTransport))}
                    </Badge>
                    {selectedReplyAdapterTransports.length > 0 && (
                        <Badge variant="outline" className="font-normal">
                            {t('Supports')}: {selectedReplyAdapterTransports.map(replyAdapterTransportLabel).join(', ')}
                        </Badge>
                    )}
                    {selectedReplyAdapter.nativeProvider && (
                        <Badge variant="outline" className="font-normal">{t('Native provider')}</Badge>
                    )}
                    {selectedReplyAdapter.webhookAdapter && (
                        <Badge variant="outline" className="font-normal">{t('Webhook adapter')}</Badge>
                    )}
                    {selectedReplyAdapter.internal && (
                        <Badge variant="outline" className="font-normal">{t('Internal')}</Badge>
                    )}
                    {selectedReplyAdapter.requiresChannelConfig && !selectedReplyAdapter.channelConfigured && (
                        <Badge variant="destructive" className="font-normal">{t('Channel missing')}</Badge>
                    )}
                    {selectedReplyAdapter.requiredEnvVars.length > 0 && (
                        <Badge
                            variant={selectedReplyAdapter.missingEnvVars.length > 0 ? 'destructive' : 'outline'}
                            className="font-normal"
                        >
                            {t('Env')}: {selectedReplyAdapter.requiredEnvVars.length}
                        </Badge>
                    )}
                </div>
            )}
            {selectedReplyReadiness && (selectedReplyReadiness.blockers.length > 0 || selectedReplyReadiness.missingEnvVars.length > 0) && (
                <div className="mt-2 space-y-1" data-ticket-reply-route-blockers>
                    {selectedReplyReadiness.blockers.map(blocker => (
                        <div key={`blocker:${blocker}`} className="flex min-w-0 items-center gap-1.5 text-xs text-destructive">
                            <AlertTriangle className="size-3 shrink-0" />
                            <span className="truncate">{blocker.split('_').join(' ')}</span>
                        </div>
                    ))}
                    {selectedReplyReadiness.missingEnvVars.map(env => (
                        <div key={`env:${env}`} className="flex min-w-0 items-center gap-1.5 text-xs text-destructive">
                            <AlertTriangle className="size-3 shrink-0" />
                            <span className="truncate">{t('Missing env')}: {env}</span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    ) : null;

    const newTicketDialog = newTicketOpen ? (
        <Dialog open={newTicketOpen} onOpenChange={setNewTicketOpen}>
            <DialogContent className="sm:max-w-xl">
                <DialogHeader>
                    <DialogTitle>{t('New ticket')}</DialogTitle>
                    <DialogDescription>{t('Customer message')}</DialogDescription>
                </DialogHeader>
                <div className="grid gap-3">
                    <div className="grid gap-3 sm:grid-cols-2">
                        <div className="space-y-1.5">
                            <Label htmlFor="new-ticket-email">{t('Requester email')}</Label>
                            <Input
                                id="new-ticket-email"
                                data-new-ticket-email
                                type="email"
                                value={newTicketFrom}
                                onChange={event => setNewTicketFrom(event.target.value)}
                                placeholder="customer@example.com"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="new-ticket-name">{t('Requester name')}</Label>
                            <Input
                                id="new-ticket-name"
                                data-new-ticket-name
                                value={newTicketName}
                                onChange={event => setNewTicketName(event.target.value)}
                            />
                        </div>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                        <div className="space-y-1.5">
                            <Label>{t('Account record')}</Label>
                            <Select value={newTicketAccountId} onValueChange={value => void selectNewTicketAccount(value)}>
                                <SelectTrigger data-new-ticket-account-record-select>
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value={NO_ACCOUNT_RECORD_VALUE}>{t('New account')}</SelectItem>
                                    {newTicketAccounts.map(account => (
                                        <SelectItem key={account.id} value={account.id} data-new-ticket-account-record-option={account.id}>
                                            {accountLabel(account)}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                            {loadingNewTicketAccounts && (
                                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                                    <Loader className="size-3 animate-spin" />
                                    {t('Loading')}
                                </div>
                            )}
                        </div>
                        <div className="space-y-1.5">
                            <Label>{t('Contact record')}</Label>
                            <Select
                                value={newTicketContactId}
                                onValueChange={selectNewTicketContact}
                                disabled={newTicketAccountId === NO_ACCOUNT_RECORD_VALUE || loadingNewTicketAccountDetail || newTicketContactOptions.length === 0}
                            >
                                <SelectTrigger
                                    data-new-ticket-contact-record-select
                                    data-new-ticket-contact-record-count={newTicketContactOptions.length}
                                >
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value={NO_CONTACT_RECORD_VALUE}>{t('No contact')}</SelectItem>
                                    {newTicketContactOptions.map(contact => (
                                        <SelectItem key={contact.id} value={contact.id} data-new-ticket-contact-record-option={contact.id}>
                                            {contact.name || contact.email || contact.id}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                            {loadingNewTicketAccountDetail && (
                                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                                    <Loader className="size-3 animate-spin" />
                                    {t('Loading')}
                                </div>
                            )}
                        </div>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                        <div className="space-y-1.5">
                            <Label htmlFor="new-ticket-account">{t('Account')}</Label>
                            <Input
                                id="new-ticket-account"
                                data-new-ticket-account
                                value={newTicketAccount}
                                onChange={event => setNewTicketAccount(event.target.value)}
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="new-ticket-assignee">{t('Assignee')}</Label>
                            <Input
                                id="new-ticket-assignee"
                                data-new-ticket-assignee
                                type="email"
                                value={newTicketAssignee}
                                onChange={event => setNewTicketAssignee(event.target.value)}
                                placeholder="agent@example.com"
                            />
                        </div>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-[1fr_10rem_10rem]">
                        <div className="space-y-1.5">
                            <Label htmlFor="new-ticket-subject">{t('Subject')}</Label>
                            <Input
                                id="new-ticket-subject"
                                data-new-ticket-subject
                                value={newTicketSubject}
                                onChange={event => setNewTicketSubject(event.target.value)}
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label>{t('Priority')}</Label>
                            <Select value={newTicketPriority} onValueChange={value => setNewTicketPriority(value as SupportIssuePriority)}>
                                <SelectTrigger>
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {priorityOptions.map(option => (
                                        <SelectItem key={option.value} value={option.value}>{t(option.label)}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="space-y-1.5">
                            <Label>{t('Queue')}</Label>
                            <Select value={newTicketQueueKey} onValueChange={setNewTicketQueueKey}>
                                <SelectTrigger>
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {queueOptions.map(option => (
                                        <SelectItem key={option.queueKey} value={option.queueKey}>{option.name}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="new-ticket-body">{t('Message')}</Label>
                        <Textarea
                            id="new-ticket-body"
                            data-new-ticket-body
                            value={newTicketBody}
                            onChange={event => setNewTicketBody(event.target.value)}
                            rows={5}
                        />
                    </div>
                </div>
                <DialogFooter>
                    <Button type="button" variant="outline" onClick={() => setNewTicketOpen(false)}>
                        {t('Cancel')}
                    </Button>
                    <Button type="button" data-new-ticket-create onClick={() => void createManualTicket()} disabled={creatingTicket}>
                        {creatingTicket ? <Loader className="size-4 animate-spin" /> : <Plus className="size-4" />}
                        {t('Create ticket')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    ) : null;

    const saveViewDialog = saveViewOpen ? (
        <Dialog
            open={saveViewOpen}
            onOpenChange={(open) => {
                setSaveViewOpen(open);
                if (!open) setEditingViewId('');
            }}
        >
            <DialogContent className="sm:max-w-md">
                <DialogHeader>
                    <DialogTitle>{editingViewId ? t('Edit view') : t('Save view')}</DialogTitle>
                    <DialogDescription>
                        {editingViewId ? t('Overwrite this view with current Inbox filters') : t('Current Inbox filters')}
                    </DialogDescription>
                </DialogHeader>
                <div className="grid gap-3">
                    <div className="space-y-1.5">
                        <Label htmlFor="saved-view-name">{t('Name')}</Label>
                        <Input
                            id="saved-view-name"
                            data-inbox-save-view-name
                            value={viewName}
                            onChange={event => setViewName(event.target.value)}
                            placeholder={t('VIP escalations')}
                        />
                    </div>
                    <div className="space-y-1.5">
                        <Label>{t('Visibility')}</Label>
                        <Select value={viewVisibility} onValueChange={value => setViewVisibility(value as 'private' | 'shared')}>
                            <SelectTrigger>
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="private">{t('Private')}</SelectItem>
                                <SelectItem value="shared">{t('Shared')}</SelectItem>
                            </SelectContent>
                        </Select>
                    </div>
                </div>
                <DialogFooter>
                    <Button
                        type="button"
                        variant="outline"
                        onClick={() => {
                            setSaveViewOpen(false);
                            setEditingViewId('');
                        }}
                        disabled={savingView}
                    >
                        {t('Cancel')}
                    </Button>
                    <Button type="button" data-inbox-save-view-submit onClick={() => void saveCurrentInboxView()} disabled={savingView || !viewName.trim()}>
                        {savingView ? <Loader className="size-4 animate-spin" /> : <Save className="size-4" />}
                        {editingViewId ? t('Update view') : t('Save view')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    ) : null;

    const saveMacroDialog = saveMacroOpen ? (
        <Dialog open={saveMacroOpen} onOpenChange={setSaveMacroOpen}>
            <DialogContent className="sm:max-w-md">
                <DialogHeader>
                    <DialogTitle>{t('Save macro')}</DialogTitle>
                    <DialogDescription>{t('Reusable reply')}</DialogDescription>
                </DialogHeader>
                <div className="grid gap-3">
                    <div className="space-y-1.5">
                        <Label htmlFor="reply-macro-title">{t('Title')}</Label>
                        <Input
                            id="reply-macro-title"
                            data-reply-macro-title
                            value={macroTitleDraft}
                            onChange={event => setMacroTitleDraft(event.target.value)}
                            placeholder={t('Refund approved')}
                        />
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="reply-macro-tags">{t('Labels')}</Label>
                        <Input
                            id="reply-macro-tags"
                            data-reply-macro-tags
                            value={macroTagsDraft}
                            onChange={event => setMacroTagsDraft(event.target.value)}
                            placeholder="billing, vip"
                        />
                    </div>
                    <div className="space-y-1.5">
                        <Label>{t('Visibility')}</Label>
                        <Select value={macroVisibilityDraft} onValueChange={value => setMacroVisibilityDraft(value as 'private' | 'shared')}>
                            <SelectTrigger>
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="private">{t('Private')}</SelectItem>
                                <SelectItem value="shared">{t('Shared')}</SelectItem>
                            </SelectContent>
                        </Select>
                    </div>
                    <div className="rounded-md border bg-muted/20 p-2">
                        <pre className="max-h-40 overflow-auto whitespace-pre-wrap text-sm text-muted-foreground">
                            {replyDraft.trim()}
                        </pre>
                    </div>
                </div>
                <DialogFooter>
                    <Button type="button" variant="outline" onClick={() => setSaveMacroOpen(false)} disabled={savingMacro}>
                        {t('Cancel')}
                    </Button>
                    <Button type="button" data-reply-macro-save-submit onClick={() => void saveReplyMacro()} disabled={savingMacro || !macroTitleDraft.trim() || !replyDraft.trim()}>
                        {savingMacro ? <Loader className="size-4 animate-spin" /> : <Save className="size-4" />}
                        {t('Save macro')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    ) : null;

    const closeWithoutReplyDialog = closeWithoutReplyOpen && selectedIssue ? (
        <Dialog
            open={closeWithoutReplyOpen}
            onOpenChange={(open) => {
                if (!closingWithoutReply) setCloseWithoutReplyOpen(open);
            }}
        >
            <DialogContent className="sm:max-w-lg" data-ticket-close-without-reply-dialog>
                <DialogHeader>
                    <DialogTitle>{t('Close without replying')}</DialogTitle>
                    <DialogDescription>
                        {t('Use this only when the customer does not need a reply. The reason is saved in the ticket history.')}
                    </DialogDescription>
                </DialogHeader>
                <div className="space-y-2">
                    <Label htmlFor="close-without-reply-note">{t('Resolution note')}</Label>
                    <Textarea
                        id="close-without-reply-note"
                        value={closeWithoutReplyNote}
                        onChange={event => setCloseWithoutReplyNote(event.target.value)}
                        rows={4}
                        placeholder={t('Explain why no customer reply is required')}
                        data-ticket-close-without-reply-note
                    />
                </div>
                <DialogFooter>
                    <Button
                        type="button"
                        variant="outline"
                        onClick={() => setCloseWithoutReplyOpen(false)}
                        disabled={closingWithoutReply}
                    >
                        {t('Cancel')}
                    </Button>
                    <Button
                        type="button"
                        variant="destructive"
                        onClick={() => void closeSelectedIssueWithoutReply()}
                        disabled={closingWithoutReply || !closeWithoutReplyNote.trim()}
                        data-ticket-close-without-reply-confirm
                    >
                        {closingWithoutReply ? <Loader className="size-4 animate-spin" /> : <CheckCircle2 className="size-4" />}
                        {t('Close without reply')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    ) : null;

    const mergeDialog = mergeOpen && selectedIssue ? (
        <Dialog open={mergeOpen} onOpenChange={(open) => {
            if (!mergingIssue) setMergeOpen(open);
        }}>
            <DialogContent className="sm:max-w-lg">
                <DialogHeader>
                    <DialogTitle>{t('Merge ticket')}</DialogTitle>
                    <DialogDescription>{selectedIssue.subject || selectedIssue.id}</DialogDescription>
                </DialogHeader>
                <div className="space-y-4">
                    <div className="space-y-1.5">
                        <Label htmlFor="merge-target">{t('Target ticket')}</Label>
                        <Select value={mergeTargetIssueId} onValueChange={setMergeTargetIssueId}>
                            <SelectTrigger id="merge-target">
                                <SelectValue placeholder={t('Select ticket')} />
                            </SelectTrigger>
                            <SelectContent>
                                {mergeTargetOptions.map(issue => (
                                    <SelectItem key={issue.id} value={issue.id}>
                                        {mergeTargetLabel(issue)}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                    {selectedMergeTarget && (
                        <div className="rounded-md border bg-muted/20 p-3 text-sm">
                            <div className="truncate font-medium">{selectedMergeTarget.subject || '(No subject)'}</div>
                            <div className="mt-1 truncate text-xs text-muted-foreground">
                                {selectedMergeTarget.accountName || selectedMergeTarget.contactEmail || selectedMergeTarget.fromAddress || '-'}
                            </div>
                            <div className="mt-2 flex flex-wrap gap-1.5">
                                <Badge variant="outline" className="font-normal">{workflowLabel(selectedMergeTarget.status)}</Badge>
                                <Badge variant={priorityVariant(selectedMergeTarget.priority)} className="font-normal">{selectedMergeTarget.priority}</Badge>
                                <Badge variant="secondary" className="font-normal">{issueQueueLabel(selectedMergeTarget)}</Badge>
                                {selectedMergeSuggestion && (
                                    <Badge variant="secondary" className="font-normal">
                                        {t(duplicateScoreLabel(selectedMergeSuggestion.score))}
                                    </Badge>
                                )}
                            </div>
                            {selectedMergeSuggestion && selectedMergeSuggestion.reasons.length > 0 && (
                                <div className="mt-2 text-xs text-muted-foreground">
                                    {selectedMergeSuggestion.reasons.join(', ')}
                                </div>
                            )}
                        </div>
                    )}
                    <div className="space-y-1.5">
                        <Label htmlFor="merge-note">{t('Note')}</Label>
                        <Textarea
                            id="merge-note"
                            value={mergeNote}
                            onChange={event => setMergeNote(event.target.value)}
                            rows={3}
                        />
                    </div>
                </div>
                <DialogFooter>
                    <Button type="button" variant="outline" onClick={() => setMergeOpen(false)} disabled={mergingIssue}>
                        {t('Cancel')}
                    </Button>
                    <Button
                        type="button"
                        data-ticket-merge-confirm
                        onClick={() => void mergeSelectedIssue()}
                        disabled={mergingIssue || !mergeTargetIssueId}
                    >
                        {mergingIssue ? <Loader className="size-4 animate-spin" /> : <Link className="size-4" />}
                        {t('Merge')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    ) : null;

    const splitMessageDialog = splitMessageOpen && selectedIssue && splitMessageTarget ? (
        <Dialog open={splitMessageOpen} onOpenChange={(open) => {
            if (open) {
                setSplitMessageOpen(true);
                return;
            }
            closeSplitMessageDialog();
        }}>
            <DialogContent className="sm:max-w-lg">
                <DialogHeader>
                    <DialogTitle>{t('Split message')}</DialogTitle>
                    <DialogDescription>{selectedIssue.subject || selectedIssue.id}</DialogDescription>
                </DialogHeader>
                <div className="space-y-4">
                    <div className="rounded-md border bg-muted/20 p-3">
                        <div className="mb-1 flex items-center justify-between gap-2 text-xs">
                            <span className="font-medium">{t(messageLabel(splitMessageTarget))}</span>
                            <Badge variant="outline" className="font-normal">
                                {splitMessageTarget.messageKind || splitMessageTarget.direction || 'message'}
                            </Badge>
                        </div>
                        <pre className="max-h-32 overflow-auto whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
                            {messageText(splitMessageTarget)}
                        </pre>
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="split-message-subject">{t('Subject')}</Label>
                        <Input
                            id="split-message-subject"
                            value={splitMessageSubject}
                            onChange={event => setSplitMessageSubject(event.target.value)}
                        />
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="split-message-note">{t('Note')}</Label>
                        <Textarea
                            id="split-message-note"
                            value={splitMessageNote}
                            onChange={event => setSplitMessageNote(event.target.value)}
                            rows={3}
                        />
                    </div>
                </div>
                <DialogFooter>
                    <Button type="button" variant="outline" onClick={closeSplitMessageDialog} disabled={Boolean(splittingMessageId)}>
                        {t('Cancel')}
                    </Button>
                    <Button
                        type="button"
                        data-ticket-split-confirm
                        onClick={() => void splitMessageToTicket()}
                        disabled={Boolean(splittingMessageId) || !splitMessageSubject.trim()}
                    >
                        {splittingMessageId ? <Loader className="size-4 animate-spin" /> : <Scissors className="size-4" />}
                        {t('Split')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    ) : null;

    const bulkRejectActionsDialog = bulkRejectActionsOpen ? (
        <Dialog open={bulkRejectActionsOpen} onOpenChange={(open) => {
            if (bulkReviewingActions) return;
            setBulkRejectActionsOpen(open);
            if (!open) setBulkRejectActionsNote('');
        }}>
            <DialogContent className="sm:max-w-md">
                <DialogHeader>
                    <DialogTitle>{t('Reject action proposals')}</DialogTitle>
                    <DialogDescription>
                        {selectedActionApprovalCount} {t('action proposals selected')}
                    </DialogDescription>
                </DialogHeader>
                <div className="space-y-2">
                    <Label htmlFor="bulk-reject-actions-note">{t('Reviewer note')}</Label>
                    <Textarea
                        id="bulk-reject-actions-note"
                        value={bulkRejectActionsNote}
                        onChange={event => setBulkRejectActionsNote(event.target.value)}
                        placeholder={t('Optional rationale for the rejection.')}
                        rows={4}
                        disabled={Boolean(bulkReviewingActions)}
                    />
                    <p className="text-xs text-muted-foreground">
                        {t('Rejected action proposals stay in the audit trail and are not applied to tickets.')}
                    </p>
                </div>
                <DialogFooter>
                    <Button
                        type="button"
                        variant="outline"
                        onClick={() => {
                            setBulkRejectActionsOpen(false);
                            setBulkRejectActionsNote('');
                        }}
                        disabled={Boolean(bulkReviewingActions)}
                    >
                        {t('Cancel')}
                    </Button>
                    <Button
                        type="button"
                        variant="destructive"
                        onClick={() => void bulkRejectSelectedActions()}
                        disabled={Boolean(bulkReviewingActions) || selectedActionApprovalIssueIds.length === 0}
                    >
                        {bulkReviewingActions === 'reject' ? <Loader className="size-4 animate-spin" /> : <X className="size-4" />}
                        {t('Reject proposals')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    ) : null;

    const bulkRequestReplyChangesDialog = bulkRequestReplyChangesOpen ? (
        <Dialog open={bulkRequestReplyChangesOpen} onOpenChange={(open) => {
            if (bulkRequestingReplyChanges) return;
            setBulkRequestReplyChangesOpen(open);
            if (!open) setBulkRequestReplyChangesNote('');
        }}>
            <DialogContent className="sm:max-w-md">
                <DialogHeader>
                    <DialogTitle>{t('Request reply changes')}</DialogTitle>
                    <DialogDescription>
                        {selectedReplyApprovalCount} {t('reply drafts selected')}
                    </DialogDescription>
                </DialogHeader>
                <div className="space-y-2">
                    <Label htmlFor="bulk-request-reply-changes-note">{t('Reviewer note')}</Label>
                    <Textarea
                        id="bulk-request-reply-changes-note"
                        value={bulkRequestReplyChangesNote}
                        onChange={event => setBulkRequestReplyChangesNote(event.target.value)}
                        placeholder={t('What should the agent or editor revise?')}
                        rows={4}
                        disabled={bulkRequestingReplyChanges}
                    />
                    <p className="text-xs text-muted-foreground">
                        {t('Requested changes move reply drafts out of the approval queue until they are revised.')}
                    </p>
                </div>
                <DialogFooter>
                    <Button
                        type="button"
                        variant="outline"
                        onClick={() => {
                            setBulkRequestReplyChangesOpen(false);
                            setBulkRequestReplyChangesNote('');
                        }}
                        disabled={bulkRequestingReplyChanges}
                    >
                        {t('Cancel')}
                    </Button>
                    <Button
                        type="button"
                        onClick={() => void bulkRequestSelectedReplyChanges()}
                        disabled={bulkRequestingReplyChanges || selectedReplyApprovalIssueIds.length === 0}
                    >
                        {bulkRequestingReplyChanges ? <Loader className="size-4 animate-spin" /> : <AlertTriangle className="size-4" />}
                        {t('Request changes')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    ) : null;

    const bulkActionsBusy = bulkUpdating || bulkPreparingAgentReplies || bulkFindingKnowledgeGaps || bulkApprovingReplies || bulkRequestingReplyChanges || bulkRetryingFailedReplies || Boolean(bulkReviewingActions);

    const bulkActionsPanel = selectedIssueIds.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/20 p-2 text-xs">
            <span className="mr-1 font-medium">{selectedIssueIds.length} {t('selected')}</span>
            <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-7 px-2 text-xs"
                disabled={!canAutoClaim || bulkActionsBusy || selectedUnassignedIssueIds.length === 0}
                title={selectedUnassignedIssueIds.length === 0 ? t('Selected tickets already have assignees') : undefined}
                onClick={() => void bulkClaimSelectedTickets()}
            >
                {bulkUpdating ? <Loader className="size-3 animate-spin" /> : <UserCheck className="size-3.5" />}
                {t('Claim')} ({selectedUnassignedIssueIds.length})
            </Button>
            {selectedAgentReplyPrepIssues.length > 0 && (
                <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 px-2 text-xs"
                    disabled={bulkActionsBusy}
                    data-bulk-agent-reply-prepare
                    onClick={() => void bulkPrepareAgentReplies()}
                >
                    {bulkPreparingAgentReplies ? <Loader className="size-3 animate-spin" /> : <Sparkles className="size-3.5" />}
                    {t('Prepare replies')} ({selectedAgentReplyPrepIssues.length})
                </Button>
            )}
            {selectedKnowledgeGapScanIssues.length > 0 && (
                <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 px-2 text-xs"
                    disabled={bulkActionsBusy}
                    data-bulk-knowledge-gap-scan
                    onClick={() => void bulkFindKnowledgeGaps()}
                >
                    {bulkFindingKnowledgeGaps ? <Loader className="size-3 animate-spin" /> : <BookOpen className="size-3.5" />}
                    {t('Find gaps')} ({selectedKnowledgeGapScanIssues.length})
                </Button>
            )}
            <Select
                value=""
                onValueChange={(value) => void bulkPatchIssues({
                    assigneeEmail: value,
                    workflowSource: 'inbox_bulk_assign',
                })}
                disabled={bulkActionsBusy || bulkAssigneeOptions.length === 0}
            >
                <SelectTrigger className="h-7 w-44 px-2 text-xs" data-bulk-assignee-select>
                    <SelectValue placeholder={t('Assign')} />
                </SelectTrigger>
                <SelectContent>
                    {bulkAssigneeOptions.map(email => (
                        <SelectItem key={email.toLowerCase()} value={email}>{email}</SelectItem>
                    ))}
                </SelectContent>
            </Select>
            <Select
                value=""
                onValueChange={(value) => {
                    const queue = queueOptions.find(option => option.queueKey === value);
                    void bulkPatchIssues({
                        queueKey: value === NO_QUEUE_VALUE ? '' : value,
                        queueName: value === NO_QUEUE_VALUE ? '' : queue?.name || value,
                    });
                }}
                disabled={bulkActionsBusy}
            >
                <SelectTrigger className="h-7 w-32 px-2 text-xs">
                    <SelectValue placeholder={t('Queue')} />
                </SelectTrigger>
                <SelectContent>
                    {queueOptions.map(option => (
                        <SelectItem key={option.queueKey} value={option.queueKey}>{option.name}</SelectItem>
                    ))}
                    <SelectItem value={NO_QUEUE_VALUE}>{t('No queue')}</SelectItem>
                </SelectContent>
            </Select>
            <Select
                value=""
                onValueChange={(value) => void bulkPatchIssues({ priority: value as SupportIssuePriority })}
                disabled={bulkActionsBusy}
            >
                <SelectTrigger className="h-7 w-28 px-2 text-xs">
                    <SelectValue placeholder={t('Priority')} />
                </SelectTrigger>
                <SelectContent>
                    {priorityOptions.map(option => (
                        <SelectItem key={option.value} value={option.value}>{t(option.label)}</SelectItem>
                    ))}
                </SelectContent>
            </Select>
            <Input
                value={bulkLabelDraft}
                onChange={event => setBulkLabelDraft(event.target.value)}
                placeholder={t('Labels')}
                className="h-7 w-36 px-2 text-xs"
                disabled={Boolean(bulkLabelingMode || bulkActionsBusy)}
            />
            <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-7 px-2 text-xs"
                disabled={Boolean(bulkLabelingMode || bulkActionsBusy || !bulkLabelDraft.trim())}
                onClick={() => void bulkUpdateLabels('add')}
            >
                {bulkLabelingMode === 'add' ? <Loader className="size-3 animate-spin" /> : null}
                {t('Add label')}
            </Button>
            <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-7 px-2 text-xs"
                disabled={Boolean(bulkLabelingMode || bulkActionsBusy || !bulkLabelDraft.trim())}
                onClick={() => void bulkUpdateLabels('remove')}
            >
                {bulkLabelingMode === 'remove' ? <Loader className="size-3 animate-spin" /> : null}
                {t('Remove label')}
            </Button>
            {selectedReplyApprovalIssueIds.length > 0 && (
                <>
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 px-2 text-xs"
                        disabled={bulkActionsBusy}
                        onClick={() => void bulkApproveSelectedReplies()}
                    >
                        {bulkApprovingReplies
                            ? <Loader className="size-3 animate-spin" />
                            : <CheckCircle2 className="size-3.5" />}
                        {t('Approve')} ({selectedReplyApprovalCount})
                    </Button>
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 px-2 text-xs"
                        disabled={bulkActionsBusy || bulkApproveSendBlocked}
                        title={bulkApproveSendBlocked ? selectedReplySendBlockDetail : undefined}
                        data-bulk-approve-send-readiness-blocked={bulkApproveSendBlocked ? 'true' : 'false'}
                        onClick={() => void bulkApproveSendSelectedReplies()}
                    >
                        {bulkApprovingReplies
                            ? <Loader className="size-3 animate-spin" />
                            : <Send className="size-3.5" />}
                        {t('Approve & send')} ({selectedReplyApprovalCount})
                    </Button>
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 px-2 text-xs"
                        disabled={bulkActionsBusy}
                        onClick={openBulkRequestReplyChangesDialog}
                    >
                        {bulkRequestingReplyChanges
                            ? <Loader className="size-3 animate-spin" />
                            : <AlertTriangle className="size-3.5" />}
                        {t('Request changes')} ({selectedReplyApprovalCount})
                    </Button>
                </>
            )}
            {selectedActionApprovalIssueIds.length > 0 && (
                <>
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 px-2 text-xs"
                        disabled={bulkActionsBusy}
                        onClick={() => void bulkApproveSelectedActions()}
                    >
                        {bulkReviewingActions === 'approve'
                            ? <Loader className="size-3 animate-spin" />
                            : <CheckCircle2 className="size-3.5" />}
                        {t('Approve actions')} ({selectedActionApprovalCount})
                    </Button>
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 px-2 text-xs"
                        disabled={bulkActionsBusy}
                        onClick={openBulkRejectActionsDialog}
                    >
                        {bulkReviewingActions === 'reject'
                            ? <Loader className="size-3 animate-spin" />
                            : <X className="size-3.5" />}
                        {t('Reject actions')} ({selectedActionApprovalCount})
                    </Button>
                </>
            )}
            {selectedFailedDeliveryIssueIds.length > 0 && (
                <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 px-2 text-xs"
                    disabled={bulkActionsBusy}
                    onClick={() => void bulkRetryFailedSelectedReplies()}
                >
                    {bulkRetryingFailedReplies
                        ? <Loader className="size-3 animate-spin" />
                        : <RefreshCw className="size-3.5" />}
                    {t('Retry failed')} ({selectedFailedDeliveryIssueIds.length})
                </Button>
            )}
            {selectedOverdueSlaIssues.length > 0 && (
                <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 px-2 text-xs"
                    disabled={bulkActionsBusy}
                    data-bulk-sla-action="overdue"
                    onClick={() => void startSlaWorkForSelectedTickets('overdue')}
                >
                    {bulkUpdating ? <Loader className="size-3 animate-spin" /> : <AlertTriangle className="size-3.5" />}
                    {t('Escalate SLA')} ({selectedOverdueSlaIssues.length})
                </Button>
            )}
            {selectedDueSoonSlaIssues.length > 0 && (
                <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 px-2 text-xs"
                    disabled={bulkActionsBusy}
                    data-bulk-sla-action="due-soon"
                    onClick={() => void startSlaWorkForSelectedTickets('due-soon')}
                >
                    {bulkUpdating ? <Loader className="size-3 animate-spin" /> : <Clock className="size-3.5" />}
                    {t('Watch SLA')} ({selectedDueSoonSlaIssues.length})
                </Button>
            )}
            {kanbanLanes.map(lane => (
                <Button
                    key={lane.value}
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 px-2 text-xs"
                    disabled={
                        bulkUpdating
                        || bulkApprovingReplies
                        || bulkRequestingReplyChanges
                        || Boolean(bulkReviewingActions)
                        || bulkRetryingFailedReplies
                        || (lane.value === 'done' && selectedDoneBlockedIssueCount > 0)
                    }
                    title={lane.value === 'done' && selectedDoneBlockedIssueCount > 0
                        ? `${t('Resolve before closing')}: ${selectedDoneBlockerText || t('open blockers')}`
                        : undefined}
                    onClick={() => void bulkPatchIssues({ status: lane.value })}
                >
                    {t(lane.label)}
                </Button>
            ))}
            <Button
                type="button"
                size="icon"
                variant="ghost"
                className="ml-auto size-7"
                disabled={bulkActionsBusy}
                onClick={clearSelection}
                aria-label={t('Clear selection')}
            >
                <X className="size-3.5" />
            </Button>
        </div>
    ) : null;

    const approvalWorkbenchPanel = approvalQueueIssues.length > 0 ? (
        <div data-approval-workbench className="rounded-md border bg-muted/20 p-2 text-xs">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2 font-medium">
                    <CheckCircle2 className="size-3.5 text-primary" />
                    <span>{t('Approval workbench')}</span>
                </div>
                <Badge variant="outline" className="font-normal">
                    {approvalQueueApprovalCount} {t('approvals')}
                </Badge>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <div className="rounded border bg-background px-2 py-1.5">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Tickets')}</div>
                    <div className="text-sm font-medium">{approvalQueueIssues.length}</div>
                </div>
                <div className="rounded border bg-background px-2 py-1.5">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Reply drafts')}</div>
                    <div className="text-sm font-medium">{approvalQueueReplyCount}</div>
                </div>
                <div className="rounded border bg-background px-2 py-1.5">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Action proposals')}</div>
                    <div className="text-sm font-medium">{approvalQueueActionCount}</div>
                </div>
                <div className="rounded border bg-background px-2 py-1.5">
                    <div className="text-[10px] uppercase text-muted-foreground">{t('Selected')}</div>
                    <div className="text-sm font-medium">{selectedApprovalIssueCount}</div>
                </div>
            </div>
            <div className="mt-3 space-y-2">
                <div className="flex items-center justify-between gap-2 text-[11px] font-medium uppercase text-muted-foreground">
                    <span>{t('Next reviews')}</span>
                    {hiddenApprovalQueueCount > 0 && (
                        <span>+{hiddenApprovalQueueCount} {t('more')}</span>
                    )}
                </div>
                <div className="grid gap-2 lg:grid-cols-2">
                    {approvalQueuePreviewIssues.map(issue => (
                        <ApprovalQueueCard
                            key={issue.id}
                            issue={issue}
                            active={issue.id === issueId}
                            selected={selectedIssueIdSet.has(issue.id)}
                            t={t}
                            onOpen={() => navigateToIssue(issue.id, { viewMode })}
                            onSelectionChange={checked => toggleIssueSelection(issue.id, checked)}
                        />
                    ))}
                </div>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
                {statusFilter !== 'approvals' && (
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 px-2 text-xs"
                        onClick={() => changeStatusFilter('approvals')}
                    >
                        <List className="size-3.5" />
                        {t('Open approvals')}
                    </Button>
                )}
                {approvalQueueReplyCount > 0 && statusFilter !== 'reply-approvals' && (
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 px-2 text-xs"
                        onClick={() => changeStatusFilter('reply-approvals')}
                    >
                        <Mail className="size-3.5" />
                        {t('Reply approvals')}
                    </Button>
                )}
                {approvalQueueActionCount > 0 && statusFilter !== 'action-approvals' && (
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 px-2 text-xs"
                        onClick={() => changeStatusFilter('action-approvals')}
                    >
                        <CheckCircle2 className="size-3.5" />
                        {t('Action approvals')}
                    </Button>
                )}
                <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 px-2 text-xs"
                    onClick={toggleApprovalQueueSelection}
                >
                    {approvalQueueFullySelected ? t('Clear queue') : t('Select queue')}
                </Button>
                {selectedReplyApprovalIssueIds.length > 0 && (
                    <>
                        <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-xs"
                            disabled={bulkActionsBusy}
                            onClick={() => void bulkApproveSelectedReplies()}
                        >
                            {bulkApprovingReplies
                                ? <Loader className="size-3 animate-spin" />
                                : <CheckCircle2 className="size-3.5" />}
                            {t('Approve reply drafts')} ({selectedReplyApprovalCount})
                        </Button>
                        <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-xs"
                            disabled={bulkActionsBusy || bulkApproveSendBlocked}
                            title={bulkApproveSendBlocked ? selectedReplySendBlockDetail : undefined}
                            data-bulk-approve-send-readiness-blocked={bulkApproveSendBlocked ? 'true' : 'false'}
                            onClick={() => void bulkApproveSendSelectedReplies()}
                        >
                            {bulkApprovingReplies
                                ? <Loader className="size-3 animate-spin" />
                                : <Send className="size-3.5" />}
                            {t('Approve & send drafts')} ({selectedReplyApprovalCount})
                        </Button>
                        <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-xs"
                            disabled={bulkActionsBusy}
                            onClick={openBulkRequestReplyChangesDialog}
                        >
                            {bulkRequestingReplyChanges
                                ? <Loader className="size-3 animate-spin" />
                                : <AlertTriangle className="size-3.5" />}
                            {t('Request changes')} ({selectedReplyApprovalCount})
                        </Button>
                    </>
                )}
                {selectedActionApprovalIssueIds.length > 0 && (
                    <>
                        <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-xs"
                            disabled={bulkActionsBusy}
                            onClick={() => void bulkApproveSelectedActions()}
                        >
                            {bulkReviewingActions === 'approve'
                                ? <Loader className="size-3 animate-spin" />
                                : <CheckCircle2 className="size-3.5" />}
                            {t('Approve action proposals')} ({selectedActionApprovalCount})
                        </Button>
                        <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-xs"
                            disabled={bulkActionsBusy}
                            onClick={openBulkRejectActionsDialog}
                        >
                            {bulkReviewingActions === 'reject'
                                ? <Loader className="size-3 animate-spin" />
                                : <X className="size-3.5" />}
                            {t('Reject action proposals')} ({selectedActionApprovalCount})
                        </Button>
                    </>
                )}
            </div>
        </div>
    ) : null;

    const closeBoardDetail = () => {
        closeIssueDrawer({ viewMode: 'board' });
    };

    const ticketWorkspacePanel = selectedIssue ? (() => {
        const workspace = selectedWorkspace;
        const latestAgentRun = agentChatRuns[0] ?? null;
        const latestAgentQuestion = latestAgentRun ? agentRunQuestion(latestAgentRun) : '';
        const latestAgentText = agentAnswer?.answer || (latestAgentRun ? agentRunAnswer(latestAgentRun) : '');
        const latestMissingInformation = agentAnswer
            ? textListFrom(agentAnswer.missingInformation)
            : latestAgentRun
                ? textListFrom(latestAgentRun.metadata.missingInformation ?? latestAgentRun.metadata.missing_information)
                : [];
        const latestKnowledgeGap = agentAnswer?.knowledgeGap ?? selectedKnowledgeGaps[0] ?? null;
        const confidence = agentAnswer?.confidence || (latestAgentRun ? textFrom(latestAgentRun.metadata.confidence) : '');
        const latestCitationCount = workspace?.agent.citationCount ?? (agentAnswer
            ? agentAnswerCitationPreviews(agentAnswer).length
            : latestAgentRun ? agentRunCitationPreviews(latestAgentRun).length : 0);
        const suggestionCount = workspace?.knowledge.suggestionCount ?? selectedIssue.knowledgeSuggestions?.length ?? 0;
        const openGapCount = workspace?.knowledge.openGapCount ?? selectedKnowledgeGaps.length;
        const pendingApprovals = workspace?.humanLoop.pendingApprovalCount ?? selectedIssue.pendingApprovalCount ?? 0;
        const answerAction = agentQuickActions.find(action => action.key === 'best-answer');
        const replyAction = agentQuickActions.find(action => action.key === 'prepare-reply');
        const gapAction = agentQuickActions.find(action => action.key === 'knowledge-gaps');
        const topKnowledgeSuggestions = (selectedIssue.knowledgeSuggestions ?? []).slice(0, 2);
        const nextAction = ticketNextAction(selectedIssue);
        const showAssignAction = nextAction.kind === 'assign_owner' && canAutoClaim && currentUserEmail;
        const nextActionReplyAction = nextAction.kind === 'reply_needed' ? replyAction : undefined;
        const showCloseAction = nextAction.kind === 'ready_to_close';
        const showReviewAction = nextAction.kind === 'reply_approval' || nextAction.kind === 'action_approval';
        const showFailedDeliveryAction = nextAction.kind === 'failed_delivery';
        const showPendingDeliveryAction = nextAction.kind === 'pending_delivery';
        const showSlaAction = nextAction.kind === 'overdue_sla' || nextAction.kind === 'due_soon_sla';
        const nextActionBusy = ticketNextActionBusy.startsWith(`${selectedIssue.id}:`);
        const nextActionBusyKind = ticketNextActionBusy.split(':')[1] || '';
        const replyReadiness = workspace?.replyReadiness ?? null;
        const replyReadinessTitle = replyReadiness
            ? [
                replyReadiness.provider ? `${t('Provider')}: ${replyReadiness.provider}` : '',
                replyReadiness.transport ? `${t('Transport')}: ${replyReadiness.transport}` : '',
                replyReadiness.target?.label ? `${t('Target')}: ${replyReadiness.target.label}` : '',
                replyReadiness.blockers.length ? `${t('Blocked')}: ${replyReadiness.blockers.join(', ')}` : '',
                replyReadiness.missingEnvVars.length ? `${t('Missing env')}: ${replyReadiness.missingEnvVars.join(', ')}` : '',
            ].filter(Boolean).join(' | ')
            : '';
        const knowledgeAssistQuestion = topKnowledgeSuggestions.length > 0
            ? `Find the best answer from the ticket context and these suggested knowledge articles: ${topKnowledgeSuggestions.map(article => article.title).join('; ')}. Include what is certain, what is uncertain, and cite the supporting sources.`
            : answerAction?.question || 'Find the best answer from the ticket context and knowledge base.';
        const showKnowledgeAssist = topKnowledgeSuggestions.length > 0 || Boolean(latestKnowledgeGap);
        const latestCustomerMessage = [...selectedMessages]
            .reverse()
            .find(message => ['customer', 'visitor'].includes((message.direction || '').toLowerCase()));
        const latestCustomerPreview = latestCustomerMessage ? messageText(latestCustomerMessage).trim() : '';
        const answerCenterContextReady = Boolean(latestCustomerPreview || selectedIssue.aiSummary);
        const answerCenterKnowledgeReady = openGapCount === 0 || suggestionCount > 0 || latestCitationCount > 0;
        const answerCenterAgentReady = Boolean(agentAnswer || latestAgentRun);
        const answerCenterDraftReady = Boolean(
            replyDraft.trim()
            || draftReply.trim()
            || agentAnswer?.reply
            || pendingReviewReplies.length > 0
            || (selectedIssue.outboundMessages ?? []).some(reply => ['draft', 'queued', 'sent'].includes(reply.status)),
        );
        const answerCenterDeliveryReady = Boolean(replyReadiness?.ready);
        const answerCenterHumanLoopClear = pendingApprovals === 0;
        const answerCenterReadyCount = [
            answerCenterContextReady,
            answerCenterKnowledgeReady,
            answerCenterAgentReady,
            answerCenterDraftReady,
            answerCenterDeliveryReady,
            answerCenterHumanLoopClear,
        ].filter(Boolean).length;
        const answerCenterStage = pendingReviewCount > 0
            ? 'review'
            : answerCenterDraftReady && answerCenterDeliveryReady
                ? 'ready_to_send'
                : answerCenterDraftReady
                    ? 'draft'
                    : answerCenterAgentReady
                        ? 'answer_ready'
                        : 'needs_answer';

        return (
            <section
                className="rounded-md border bg-muted/20 p-3"
                data-ticket-answer-workspace={workspace?.kind ?? ''}
                data-ticket-answer-workspace-action={workspace?.nextAction.kind ?? ''}
                data-ticket-answer-workspace-phase={workspace?.nextAction.phase ?? ''}
                data-ticket-answer-workspace-agent-runs={workspace?.agent.runCount ?? ''}
                data-ticket-answer-workspace-knowledge-suggestions={workspace?.knowledge.suggestionCount ?? ''}
                data-ticket-answer-workspace-knowledge-gaps={workspace?.knowledge.openGapCount ?? ''}
                data-ticket-answer-workspace-human-approvals={workspace?.humanLoop.pendingApprovalCount ?? ''}
                data-ticket-answer-workspace-can-answer={workspace?.channel.canAnswerFromApp === undefined ? '' : String(workspace.channel.canAnswerFromApp)}
                data-ticket-reply-readiness={workspace?.replyReadiness.status ?? ''}
                data-ticket-reply-readiness-transport={workspace?.replyReadiness.transport ?? ''}
                data-ticket-reply-readiness-provider={workspace?.replyReadiness.provider ?? ''}
                data-ticket-reply-readiness-blockers={workspace?.replyReadiness.blockers.join(',') ?? ''}
                data-ticket-reply-readiness-missing-env={workspace?.replyReadiness.missingEnvVars.join(',') ?? ''}
            >
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2 text-sm font-medium">
                        <Sparkles className="size-4 shrink-0" />
                        <span className="truncate">{t('Ticket workspace')}</span>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                        {confidence && (
                            <Badge variant="outline" className="font-normal">
                                {confidence}
                            </Badge>
                        )}
                        {latestCitationCount > 0 && (
                            <Badge variant="outline" className="font-normal">
                                {latestCitationCount} {t('sources')}
                            </Badge>
                        )}
                        {agentAnswer?.reply && (
                            <Badge variant="secondary" className="font-normal">
                                {t('Draft ready')}
                            </Badge>
                        )}
                        {replyReadiness && (
                            <Badge
                                variant={replyReadiness.ready ? 'secondary' : 'destructive'}
                                className="max-w-[14rem] gap-1 truncate font-normal"
                                title={replyReadinessTitle || undefined}
                                data-ticket-reply-readiness-badge={replyReadiness.status}
                            >
                                {replyReadiness.ready
                                    ? <CheckCircle2 className="size-3.5 shrink-0" />
                                    : <AlertTriangle className="size-3.5 shrink-0" />}
                                <span className="truncate">
                                    {replyReadiness.ready ? t('Reply ready') : t('Reply blocked')}
                                </span>
                            </Badge>
                        )}
                    </div>
                </div>
                <div
                    className="mb-3 rounded-md border bg-background p-3"
                    data-ticket-answer-center
                    data-ticket-answer-center-stage={answerCenterStage}
                    data-ticket-answer-center-context-ready={answerCenterContextReady ? 'true' : 'false'}
                    data-ticket-answer-center-knowledge-ready={answerCenterKnowledgeReady ? 'true' : 'false'}
                    data-ticket-answer-center-agent-ready={answerCenterAgentReady ? 'true' : 'false'}
                    data-ticket-answer-center-draft-ready={answerCenterDraftReady ? 'true' : 'false'}
                    data-ticket-answer-center-delivery-ready={answerCenterDeliveryReady ? 'true' : 'false'}
                    data-ticket-answer-center-human-loop-clear={answerCenterHumanLoopClear ? 'true' : 'false'}
                    data-ticket-answer-center-ready-count={answerCenterReadyCount}
                    data-ticket-answer-center-sources={latestCitationCount}
                    data-ticket-answer-center-gaps={openGapCount}
                    data-ticket-answer-center-approvals={pendingReviewCount}
                    data-ticket-answer-center-outbound={(selectedIssue.outboundMessages ?? []).length}
                    data-ticket-answer-center-channel={selectedIssue.channel || ''}
                >
                    <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                            <div className="flex items-center gap-2 text-sm font-medium">
                                <Sparkles className="size-4 shrink-0" />
                                <span className="truncate">{t('Answer center')}</span>
                            </div>
                            <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                                {latestCustomerPreview || selectedIssue.aiSummary || t('No customer context loaded yet.')}
                            </div>
                        </div>
                        <Badge
                            variant={answerCenterStage === 'ready_to_send' ? 'secondary' : answerCenterStage === 'review' ? 'outline' : 'destructive'}
                            className="shrink-0 font-normal"
                        >
                            {answerCenterReadyCount}/6 {t('ready')}
                        </Badge>
                    </div>
                    <div className="grid gap-2 md:grid-cols-3 xl:grid-cols-6">
                        <div className="rounded border bg-muted/20 px-2 py-1.5">
                            <div className="flex items-center gap-1.5 text-[10px] uppercase text-muted-foreground">
                                <Mail className="size-3" />
                                {t('Context')}
                            </div>
                            <div className="mt-1 truncate text-xs font-medium">
                                {answerCenterContextReady ? t('Loaded') : t('Missing')}
                            </div>
                        </div>
                        <div className="rounded border bg-muted/20 px-2 py-1.5">
                            <div className="flex items-center gap-1.5 text-[10px] uppercase text-muted-foreground">
                                <BookOpen className="size-3" />
                                {t('Knowledge')}
                            </div>
                            <div className="mt-1 truncate text-xs font-medium">
                                {openGapCount > 0 ? `${openGapCount} ${t('gaps')}` : `${suggestionCount} ${t('sources')}`}
                            </div>
                        </div>
                        <div className="rounded border bg-muted/20 px-2 py-1.5">
                            <div className="flex items-center gap-1.5 text-[10px] uppercase text-muted-foreground">
                                <Sparkles className="size-3" />
                                {t('Agent')}
                            </div>
                            <div className="mt-1 truncate text-xs font-medium">
                                {answerCenterAgentReady ? t('Answered') : t('Ask needed')}
                            </div>
                        </div>
                        <div className="rounded border bg-muted/20 px-2 py-1.5">
                            <div className="flex items-center gap-1.5 text-[10px] uppercase text-muted-foreground">
                                <Pencil className="size-3" />
                                {t('Draft')}
                            </div>
                            <div className="mt-1 truncate text-xs font-medium">
                                {answerCenterDraftReady ? t('Ready') : t('Missing')}
                            </div>
                        </div>
                        <div className="rounded border bg-muted/20 px-2 py-1.5">
                            <div className="flex items-center gap-1.5 text-[10px] uppercase text-muted-foreground">
                                <Send className="size-3" />
                                {t('Delivery')}
                            </div>
                            <div className="mt-1 truncate text-xs font-medium">
                                {answerCenterDeliveryReady ? t('Ready') : t('Blocked')}
                            </div>
                        </div>
                        <div className="rounded border bg-muted/20 px-2 py-1.5">
                            <div className="flex items-center gap-1.5 text-[10px] uppercase text-muted-foreground">
                                <UserCheck className="size-3" />
                                {t('Review')}
                            </div>
                            <div className="mt-1 truncate text-xs font-medium">
                                {pendingReviewCount > 0 ? `${pendingReviewCount} ${t('pending')}` : t('Clear')}
                            </div>
                        </div>
                    </div>
                    <div className="mt-3 flex flex-wrap justify-end gap-2">
                        <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-8 px-2.5 text-xs"
                            data-ticket-answer-center-ask
                            onClick={() => void askAgent(knowledgeAssistQuestion, false, 'answer-center:sources')}
                            disabled={askingAgent}
                        >
                            {runningAgentActionKey === 'answer-center:sources'
                                ? <Loader className="size-3.5 animate-spin" />
                                : <Sparkles className="size-3.5" />}
                            {t('Ask with sources')}
                        </Button>
                        {replyAction && (
                            <Button
                                type="button"
                                size="sm"
                                className="h-8 px-2.5 text-xs"
                                data-ticket-answer-center-draft
                                onClick={() => void askAgent(replyAction.question, true, 'answer-center:draft')}
                                disabled={askingAgent}
                            >
                                {runningAgentActionKey === 'answer-center:draft'
                                    ? <Loader className="size-3.5 animate-spin" />
                                    : <Send className="size-3.5" />}
                                {t('Prepare draft')}
                            </Button>
                        )}
                        {pendingReviewCount > 0 && (
                            <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                className="h-8 px-2.5 text-xs"
                                data-ticket-answer-center-review
                                onClick={openReviewPackage}
                            >
                                <CheckCircle2 className="size-3.5" />
                                {t('Open review')}
                            </Button>
                        )}
                        <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-8 px-2.5 text-xs"
                            data-ticket-answer-center-send-now
                            data-ticket-answer-center-send-blocked={selectedReplySendNowBlocked ? 'true' : 'false'}
                            onClick={() => void sendReplyDraftNow()}
                            disabled={Boolean(savingReplyStatus) || !replyDraft.trim() || selectedReplySendNowBlocked}
                            title={selectedReplySendNowBlocked ? selectedReplySendNowBlockDetail : undefined}
                        >
                            {savingReplyStatus === 'send-now'
                                ? <Loader className="size-3.5 animate-spin" />
                                : <Send className="size-3.5" />}
                            {t('Send now')}
                        </Button>
                    </div>
                </div>
                <div data-ticket-next-action className="mb-3 rounded-md border bg-background p-3">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0 space-y-1">
                            <div className="flex flex-wrap items-center gap-2">
                                <Badge variant={nextAction.variant} className="font-normal">
                                    {t(nextAction.badge)}
                                </Badge>
                                <span className="text-sm font-medium">{t('Next action')}</span>
                            </div>
                            <div className="text-sm font-semibold">{t(nextAction.title)}</div>
                            <div className="text-xs text-muted-foreground">{t(nextAction.detail)}</div>
                            {nextAction.kind === 'assign_owner' && issueAssignmentHint(selectedIssue) && (
                                <div className="text-xs text-muted-foreground">
                                    {t(issueAssignmentHint(selectedIssue))}
                                </div>
                            )}
                        </div>
                        {(showAssignAction || nextActionReplyAction || showReviewAction || showFailedDeliveryAction || showPendingDeliveryAction || showSlaAction || showCloseAction) && (
                            <div className="flex shrink-0 flex-wrap gap-2">
                                {showAssignAction && (
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant="outline"
                                        onClick={() => void claimIssue(selectedIssue)}
                                        disabled={claimingIssueId === selectedIssue.id}
                                    >
                                        {claimingIssueId === selectedIssue.id
                                            ? <Loader className="size-3.5 animate-spin" />
                                            : <UserCheck className="size-3.5" />}
                                        {t('Assign to me')}
                                    </Button>
                                )}
                                {nextActionReplyAction && (
                                    <Button
                                        type="button"
                                        size="sm"
                                        onClick={() => void askAgent(nextActionReplyAction.question, true, nextActionReplyAction.key)}
                                        disabled={askingAgent}
                                    >
                                        {runningAgentActionKey === nextActionReplyAction.key
                                            ? <Loader className="size-3.5 animate-spin" />
                                            : <Send className="size-3.5" />}
                                        {t('Prepare reply')}
                                    </Button>
                                )}
                                {showReviewAction && (
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant="outline"
                                        onClick={openReviewPackage}
                                    >
                                        <CheckCircle2 className="size-3.5" />
                                        {t('Open review')}
                                    </Button>
                                )}
                                {showFailedDeliveryAction && (
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant="outline"
                                        data-ticket-retry-failed="true"
                                        onClick={() => void retryFailedRepliesForIssue(selectedIssue)}
                                        disabled={nextActionBusy || bulkRetryingFailedReplies}
                                    >
                                        {nextActionBusyKind === 'retry'
                                            ? <Loader className="size-3.5 animate-spin" />
                                            : <RefreshCw className="size-3.5" />}
                                        {t('Retry failed')}
                                    </Button>
                                )}
                                {showPendingDeliveryAction && (
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant="outline"
                                        onClick={() => void runDeliveryForIssue(selectedIssue)}
                                        disabled={nextActionBusy}
                                    >
                                        {nextActionBusyKind === 'delivery'
                                            ? <Loader className="size-3.5 animate-spin" />
                                            : <RefreshCw className="size-3.5" />}
                                        {t('Run delivery')}
                                    </Button>
                                )}
                                {showSlaAction && (
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant={nextAction.kind === 'overdue_sla' ? 'destructive' : 'outline'}
                                        onClick={() => void startSlaWorkForIssue(selectedIssue, nextAction.kind === 'overdue_sla' ? 'overdue' : 'due-soon')}
                                        disabled={nextActionBusy}
                                    >
                                        {nextActionBusyKind === 'sla'
                                            ? <Loader className="size-3.5 animate-spin" />
                                            : <AlertTriangle className="size-3.5" />}
                                        {nextAction.kind === 'overdue_sla' ? t('Escalate SLA') : t('Start SLA watch')}
                                    </Button>
                                )}
                                {showCloseAction && (
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant="outline"
                                        data-ticket-next-action-mark-done
                                        onClick={() => void patchSelectedIssue({ status: 'done' })}
                                        disabled={movingIssueId === selectedIssue.id}
                                    >
                                        {movingIssueId === selectedIssue.id
                                            ? <Loader className="size-3.5 animate-spin" />
                                            : <CheckCircle2 className="size-3.5" />}
                                        {t('Mark done')}
                                    </Button>
                                )}
                            </div>
                        )}
                    </div>
                </div>
                <div className="grid gap-2 sm:grid-cols-4">
                    <div className="rounded-md border bg-background p-2">
                        <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase text-muted-foreground">
                            <Sparkles className="size-3.5" />
                            {t('Agent')}
                        </div>
                        <div className="mt-1 text-lg font-semibold">{agentChatRuns.length}</div>
                        <div className="truncate text-xs text-muted-foreground">
                            {latestAgentQuestion || t('No agent answer yet')}
                        </div>
                    </div>
                    <div className="rounded-md border bg-background p-2">
                        <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase text-muted-foreground">
                            <BookOpen className="size-3.5" />
                            {t('Knowledge')}
                        </div>
                        <div className="mt-1 text-lg font-semibold">{suggestionCount}</div>
                        <div className="truncate text-xs text-muted-foreground">
                            {suggestionCount === 1 ? t('suggestion') : t('suggestions')}
                        </div>
                    </div>
                    <div className="rounded-md border bg-background p-2">
                        <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase text-muted-foreground">
                            <AlertCircle className="size-3.5" />
                            {t('Gaps')}
                        </div>
                        <div className="mt-1 text-lg font-semibold">{openGapCount}</div>
                        <div className="truncate text-xs text-muted-foreground">
                            {openGapCount > 0 ? t('needs article') : t('covered')}
                        </div>
                    </div>
                    <div className="rounded-md border bg-background p-2">
                        <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase text-muted-foreground">
                            <CheckCircle2 className="size-3.5" />
                            {t('Human loop')}
                        </div>
                        <div className="mt-1 text-lg font-semibold">{pendingApprovals}</div>
                        <div className="truncate text-xs text-muted-foreground">
                            {pendingApprovals > 0 ? t('approval pending') : t('clear')}
                        </div>
                    </div>
                </div>
                {showKnowledgeAssist && (
                    <div
                        className="mt-3 rounded-md border bg-background p-2 text-sm"
                        data-ticket-knowledge-assist
                        data-ticket-knowledge-assist-suggestions={topKnowledgeSuggestions.length}
                        data-ticket-knowledge-assist-gaps={openGapCount}
                    >
                        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                            <div className="flex min-w-0 items-center gap-1.5 text-xs font-medium uppercase text-muted-foreground">
                                <BookOpen className="size-3.5 shrink-0" />
                                <span className="truncate">{t('Knowledge assist')}</span>
                            </div>
                            <div className="flex flex-wrap gap-1.5">
                                {topKnowledgeSuggestions.length > 0 && (
                                    <Badge variant="outline" className="font-normal">
                                        {topKnowledgeSuggestions.length} {t('sources')}
                                    </Badge>
                                )}
                                {openGapCount > 0 && (
                                    <Badge variant="destructive" className="font-normal">
                                        {openGapCount} {t('gaps')}
                                    </Badge>
                                )}
                            </div>
                        </div>
                        <div className="grid gap-2 md:grid-cols-2">
                            {topKnowledgeSuggestions.map(article => {
                                const matchScore = knowledgeMatchScore(article);
                                return (
                                    <div
                                        key={article.id}
                                        className="rounded-md border bg-muted/20 p-2"
                                        data-ticket-knowledge-assist-article={article.id}
                                    >
                                        <div className="mb-1 flex min-w-0 items-center justify-between gap-2">
                                            <div className="min-w-0 truncate font-medium">{article.title}</div>
                                            <div className="flex shrink-0 items-center gap-1">
                                                {matchScore > 0 && (
                                                    <Badge variant="secondary" className="font-normal">
                                                        {matchScore}
                                                    </Badge>
                                                )}
                                                <Badge variant={article.public ? 'secondary' : 'outline'} className="font-normal">
                                                    {t(knowledgeVisibilityLabel(article.visibility, article.public))}
                                                </Badge>
                                            </div>
                                        </div>
                                        <div className="line-clamp-2 text-xs text-muted-foreground">
                                            {article.body || '-'}
                                        </div>
                                        <div className="mt-2 flex flex-wrap justify-end gap-1.5">
                                            <Button
                                                type="button"
                                                size="sm"
                                                variant="ghost"
                                                className="h-7 px-2 text-xs"
                                                onClick={() => appendKnowledgeToReply(article)}
                                            >
                                                <Plus className="size-3" />
                                                {t('Use')}
                                            </Button>
                                            <Button
                                                type="button"
                                                size="sm"
                                                variant="outline"
                                                className="h-7 px-2 text-xs"
                                                data-ticket-knowledge-assist-draft={article.id}
                                                onClick={() => void askAgent(`Draft an approval-ready answer using the knowledge article "${article.title}".`, true, `knowledge-assist:${article.id}`)}
                                                disabled={askingAgent}
                                            >
                                                {runningAgentActionKey === `knowledge-assist:${article.id}`
                                                    ? <Loader className="size-3 animate-spin" />
                                                    : <Sparkles className="size-3" />}
                                                {t('Draft')}
                                            </Button>
                                        </div>
                                    </div>
                                );
                            })}
                            {latestKnowledgeGap && (
                                <div data-ticket-knowledge-assist-gap>
                                    {renderKnowledgeGapCallout(latestKnowledgeGap, true)}
                                </div>
                            )}
                        </div>
                        <div className="mt-2 flex flex-wrap justify-end gap-2">
                            <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                className="h-7 px-2 text-xs"
                                data-ticket-knowledge-assist-ask
                                onClick={() => void askAgent(knowledgeAssistQuestion, false, 'knowledge-assist')}
                                disabled={askingAgent}
                            >
                                {runningAgentActionKey === 'knowledge-assist'
                                    ? <Loader className="size-3 animate-spin" />
                                    : <Sparkles className="size-3" />}
                                {t('Ask with sources')}
                            </Button>
                            {gapAction && (
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="ghost"
                                    className="h-7 px-2 text-xs"
                                    data-ticket-knowledge-assist-find-gaps
                                    onClick={() => void askAgent(gapAction.question, false, gapAction.key)}
                                    disabled={askingAgent}
                                >
                                    {runningAgentActionKey === gapAction.key
                                        ? <Loader className="size-3 animate-spin" />
                                        : <AlertCircle className="size-3" />}
                                    {t(gapAction.label)}
                                </Button>
                            )}
                        </div>
                    </div>
                )}
                {latestAgentText && (
                    <div className="mt-3 rounded-md border bg-background p-2 text-sm">
                        <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                            <div className="text-xs font-medium uppercase text-muted-foreground">
                                {t('Latest answer')}
                            </div>
                            <div className="flex flex-wrap gap-1.5">
                                {agentAnswer ? (
                                    <>
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            className="h-7 px-2 text-xs"
                                            onClick={() => applyAgentAnswerToReply('append')}
                                        >
                                            <Plus className="size-3" />
                                            {t('Append')}
                                        </Button>
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            className="h-7 px-2 text-xs"
                                            onClick={() => applyAgentAnswerToReply('replace')}
                                        >
                                            <Copy className="size-3" />
                                            {t('Use as reply')}
                                        </Button>
                                    </>
                                ) : latestAgentRun ? (
                                    <>
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            className="h-7 px-2 text-xs"
                                            onClick={() => applyAgentRunToReply(latestAgentRun, 'append')}
                                        >
                                            <Plus className="size-3" />
                                            {t('Append')}
                                        </Button>
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            className="h-7 px-2 text-xs"
                                            onClick={() => applyAgentRunToReply(latestAgentRun, 'replace')}
                                        >
                                            <Copy className="size-3" />
                                            {t('Use as reply')}
                                        </Button>
                                    </>
                                ) : null}
                            </div>
                        </div>
                        {latestMissingInformation.length > 0 && (
                            <div
                                className="mb-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-2.5"
                                data-ticket-agent-missing-information
                                role="status"
                                aria-live="polite"
                                aria-atomic="true"
                            >
                                <div className="mb-1 text-xs font-medium uppercase text-muted-foreground">
                                    {t('Missing information')}
                                </div>
                                <ul className="list-disc space-y-1 pl-4 text-xs text-muted-foreground">
                                    {latestMissingInformation.map(item => <li key={item}>{item}</li>)}
                                </ul>
                            </div>
                        )}
                        <div className="line-clamp-3 whitespace-pre-wrap text-muted-foreground">
                            {latestAgentText}
                        </div>
                    </div>
                )}
                <div className="mt-3 flex flex-wrap justify-end gap-2">
                    <Button
                        type="button"
                        size="sm"
                        data-ticket-prepare-package
                        data-ticket-prepare-package-running={preparingTicketPackage ? 'true' : 'false'}
                        onClick={() => void prepareTicketPackage()}
                        disabled={preparingTicketPackage || preparingTriage || preparingCustomFields || askingAgent}
                    >
                        {preparingTicketPackage
                            ? <Loader className="size-3.5 animate-spin" />
                            : <Sparkles className="size-3.5" />}
                        {t('Prepare package')}
                    </Button>
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        data-ticket-triage-agent
                        onClick={() => void prepareTriage()}
                        disabled={preparingTriage}
                    >
                        {preparingTriage ? <Loader className="size-3.5 animate-spin" /> : <Columns3 className="size-3.5" />}
                        {t('Triage')}
                    </Button>
                    {answerAction && (
                        <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => void askAgent(answerAction.question, false, answerAction.key)}
                            disabled={askingAgent}
                        >
                            {runningAgentActionKey === answerAction.key
                                ? <Loader className="size-3.5 animate-spin" />
                                : <Sparkles className="size-3.5" />}
                            {t(answerAction.label)}
                        </Button>
                    )}
                    {gapAction && (
                        <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => void askAgent(gapAction.question, false, gapAction.key)}
                            disabled={askingAgent}
                        >
                            {runningAgentActionKey === gapAction.key
                                ? <Loader className="size-3.5 animate-spin" />
                                : <BookOpen className="size-3.5" />}
                            {t(gapAction.label)}
                        </Button>
                    )}
                    {replyAction && (
                        <Button
                            type="button"
                            size="sm"
                            onClick={() => void askAgent(replyAction.question, true, replyAction.key)}
                            disabled={askingAgent}
                        >
                            {runningAgentActionKey === replyAction.key
                                ? <Loader className="size-3.5 animate-spin" />
                                : <Send className="size-3.5" />}
                            {t(replyAction.label)}
                        </Button>
                    )}
                </div>
            </section>
        );
    })() : null;

    const ticketOperatingProofPanel = selectedTicketProof ? (() => {
        const proof: SupportTicketProof = selectedTicketProof;
        const summary = proof.summary;
        const blockedCount = summary.blockedChecks;
        const readyCount = summary.readyChecks;
        const totalCount = summary.totalChecks;

        return (
            <section
                className="rounded-md border bg-background p-3"
                data-ticket-operating-proof={proof.kind}
                data-ticket-operating-proof-ready={String(proof.ready)}
                data-ticket-operating-proof-ready-count={readyCount}
                data-ticket-operating-proof-blocked-count={blockedCount}
                data-ticket-operating-proof-total={totalCount}
                data-ticket-operating-proof-blocked-keys={summary.blockedKeys.join(',')}
            >
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2 text-sm font-medium">
                        <CheckCircle2 className="size-4 shrink-0 text-muted-foreground" />
                        <span className="truncate">{t('Ticket proof')}</span>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                        <Badge variant={proof.ready ? 'secondary' : 'outline'} className="font-normal">
                            {readyCount}/{totalCount} {t('ready')}
                        </Badge>
                        {blockedCount > 0 && (
                            <Badge variant="destructive" className="font-normal">
                                {blockedCount} {t('blocked')}
                            </Badge>
                        )}
                    </div>
                </div>
                <div className="grid gap-2 md:grid-cols-2">
                    {proof.checks.map(check => {
                        const showFixChannel = check.action === 'fix_channel' && Boolean(selectedReplyRouteFixHref);
                        return (
                            <div
                                key={check.key}
                                className="rounded-md border bg-muted/20 p-2"
                                data-ticket-operating-proof-check={check.key}
                                data-ticket-operating-proof-check-ready={String(check.ready)}
                                data-ticket-operating-proof-check-action={check.action}
                            >
                                <div className="mb-1 flex min-w-0 items-center justify-between gap-2">
                                    <div className="flex min-w-0 items-center gap-1.5 text-sm font-medium">
                                        {check.ready
                                            ? <CheckCircle2 className="size-3.5 shrink-0 text-emerald-600" />
                                            : <AlertTriangle className="size-3.5 shrink-0 text-destructive" />}
                                        <span className="truncate">{t(check.label)}</span>
                                    </div>
                                    <Badge variant={check.ready ? 'secondary' : 'destructive'} className="shrink-0 font-normal">
                                        {check.ready ? t('Ready') : t('Blocked')}
                                    </Badge>
                                </div>
                                <div className="line-clamp-2 text-xs text-muted-foreground" title={check.detail}>
                                    {check.detail || '-'}
                                </div>
                                {showFixChannel && (
                                    <div className="mt-2 flex justify-end">
                                        <Button asChild size="sm" variant="outline" className="h-7 px-2 text-xs">
                                            <a href={selectedReplyRouteFixHref}>
                                                <ExternalLink className="size-3" />
                                                {t('Fix route')}
                                            </a>
                                        </Button>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </section>
        );
    })() : null;

    const ticketConversationPanel = selectedIssue ? (() => {
        const conversation = selectedIssue.conversation;
        if (!conversation?.key) return null;
        const tickets = conversation.tickets ?? [];
        const visibleTickets = tickets.slice(0, 5);
        const hiddenTicketCount = Math.max(tickets.length - visibleTickets.length, 0);
        const visibleMessages = (conversation.messages ?? []).slice(-4).reverse();
        const currentTicketId = conversation.currentIssueId || selectedIssue.id;
        const anchorLabel = conversationAnchorLabel(conversation.source, conversation.label || conversation.key);

        return (
            <section
                data-ticket-conversation
                data-ticket-conversation-key={conversation.key}
                data-ticket-conversation-source={conversation.source}
                data-ticket-conversation-issues={conversation.issueCount}
                data-ticket-conversation-messages={conversation.messageCount}
                className="rounded-md border bg-background p-3"
            >
                <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                        <div className="flex min-w-0 items-center gap-2 text-sm font-medium">
                            <InboxIcon className="size-4 shrink-0 text-muted-foreground" />
                            <span className="truncate">{t('Conversation context')}</span>
                        </div>
                        <div className="mt-1 truncate text-xs text-muted-foreground" title={anchorLabel}>
                            {anchorLabel}
                        </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                        {conversation.channel && (
                            <Badge variant="secondary" className="font-normal">
                                {conversation.channel}
                            </Badge>
                        )}
                        {conversation.latestMessageAt && (
                            <Badge variant="outline" className="font-normal">
                                {formatTime(conversation.latestMessageAt)}
                            </Badge>
                        )}
                    </div>
                </div>
                <div className="grid gap-2 sm:grid-cols-4">
                    <div className="rounded-md border bg-muted/20 p-2">
                        <div className="text-[11px] font-medium uppercase text-muted-foreground">{t('Tickets')}</div>
                        <div className="mt-1 text-lg font-semibold">{conversation.issueCount}</div>
                    </div>
                    <div className="rounded-md border bg-muted/20 p-2">
                        <div className="text-[11px] font-medium uppercase text-muted-foreground">{t('Open')}</div>
                        <div className="mt-1 text-lg font-semibold">{conversation.openCount}</div>
                    </div>
                    <div className="rounded-md border bg-muted/20 p-2">
                        <div className="text-[11px] font-medium uppercase text-muted-foreground">{t('Ongoing')}</div>
                        <div className="mt-1 text-lg font-semibold">{conversation.ongoingCount}</div>
                    </div>
                    <div className="rounded-md border bg-muted/20 p-2">
                        <div className="text-[11px] font-medium uppercase text-muted-foreground">{t('Messages')}</div>
                        <div className="mt-1 text-lg font-semibold">{conversation.messageCount}</div>
                    </div>
                </div>
                {visibleTickets.length > 0 && (
                    <div className="mt-3 space-y-1.5">
                        {visibleTickets.map(ticket => {
                            const isCurrent = ticket.id === currentTicketId;
                            return (
                                <button
                                    key={ticket.id}
                                    type="button"
                                    className="flex w-full items-center gap-2 rounded-md border bg-muted/20 px-2 py-1.5 text-left hover:bg-muted"
                                    onClick={() => !isCurrent && navigateToIssue(ticket.id)}
                                    disabled={isCurrent}
                                >
                                    <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
                                        {statusIcon(ticket.status)}
                                        {t(workflowLabel(ticket.status))}
                                    </span>
                                    <span className="min-w-0 flex-1 truncate text-sm">{ticket.subject || t('(No subject)')}</span>
                                    {ticket.needsResponse && (
                                        <Badge variant="secondary" className="shrink-0 font-normal">
                                            {t('Needs response')}
                                        </Badge>
                                    )}
                                    {ticket.pendingApprovalCount > 0 && (
                                        <Badge variant="outline" className="shrink-0 font-normal">
                                            {ticket.pendingApprovalCount} {t('approval')}
                                        </Badge>
                                    )}
                                    <span className="shrink-0 text-xs text-muted-foreground">
                                        {formatTime(ticket.latestMessageAt)}
                                    </span>
                                </button>
                            );
                        })}
                        {hiddenTicketCount > 0 && (
                            <div className="text-xs text-muted-foreground">
                                +{hiddenTicketCount} {t('more tickets')}
                            </div>
                        )}
                    </div>
                )}
                {visibleMessages.length > 0 && (
                    <div className="mt-3 space-y-2">
                        {visibleMessages.map(message => (
                            <div key={`${message.issueId}:${message.id}`} className="rounded-md border bg-muted/20 px-2 py-1.5">
                                <div className="mb-1 flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground">
                                    <span className="truncate">
                                        {[message.sender || message.direction || t('Message'), message.ticketSubject].filter(Boolean).join(' · ')}
                                    </span>
                                    <span className="shrink-0">{formatTime(message.occurredAt)}</span>
                                </div>
                                <div className="line-clamp-2 whitespace-pre-wrap text-xs">
                                    {message.body || '-'}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </section>
        );
    })() : null;

    const channelSourcePanel = selectedIssue ? (() => {
        const sourceInfo = channelSourceInfo(selectedIssue);
        if (!sourceInfo) return null;
        const visibleDetails = sourceInfo.details.slice(0, 6);
        const sourceProofChannel = sourceInfo.channelKey || sourceInfo.source || sourceInfo.channel;
        const sourceProofMode = sourceInfo.ticketMode || 'unknown';
        const sourceProofAction = sourceInfo.resolverAction || 'linked';
        const sourceProofMessage = sourceInfo.sourceMessageId || sourceInfo.externalMessageKey || '';
        const sourceProofTicket = sourceInfo.sourceIssueId || sourceInfo.externalTicketKey || '';
        const channelSetupHref = tenantId && sourceInfo.channelKey
            ? `/${encodeURIComponent(tenantId)}/${encodeURIComponent(projectId)}/channels?channel=${encodeURIComponent(sourceInfo.channelKey)}`
            : '';
        return (
            <section
                data-channel-source-panel
                data-ticket-source-proof
                data-ticket-source-proof-channel={sourceProofChannel}
                data-ticket-source-proof-mode={sourceProofMode}
                data-ticket-source-proof-action={sourceProofAction}
                data-ticket-source-proof-message={sourceProofMessage}
                className="rounded-md border bg-background p-3"
            >
                <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                        <div className="flex min-w-0 items-center gap-2 text-sm font-medium">
                            <Database className="size-4 shrink-0 text-muted-foreground" />
                            <span className="truncate">{t('Channel source')}</span>
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                            {t('Source proof for routing, ticket creation, and replies.')}
                        </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                        {channelSetupHref && (
                            <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                className="h-7 gap-1.5 px-2 text-xs"
                                onClick={() => navigate(channelSetupHref)}
                            >
                                <ExternalLink className="size-3.5" />
                                {t('Open channel setup')}
                            </Button>
                        )}
                        {sourceInfo.channel && (
                            <Badge variant="secondary" className="font-normal">
                                {sourceInfo.channel}
                            </Badge>
                        )}
                        {sourceInfo.ticketMode && (
                            <Badge variant="outline" className="font-normal">
                                {t(ticketModeLabel(sourceInfo.ticketMode))}
                            </Badge>
                        )}
                        {sourceInfo.resolverAction && (
                            <Badge variant="outline" className="font-normal">
                                {t('Resolver')}: {t(sourceInfo.resolverAction)}
                            </Badge>
                        )}
                    </div>
                </div>
                <div className="mb-3 rounded-md border bg-muted/20 p-2" data-ticket-source-proof-card>
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                        <div className="text-xs font-medium uppercase text-muted-foreground">
                            {t('Ticket creation proof')}
                        </div>
                        <div className="flex flex-wrap items-center gap-1.5">
                            <Badge variant={sourceProofMode === 'per_message' ? 'secondary' : 'outline'} className="font-normal">
                                {t(ticketModeLabel(sourceProofMode))}
                            </Badge>
                            <Badge variant={sourceProofActionVariant(sourceProofAction)} className="font-normal">
                                {t(resolverActionLabel(sourceProofAction))}
                            </Badge>
                        </div>
                    </div>
                    <div className="grid gap-2 sm:grid-cols-2">
                        {sourceProofTicket && (
                            <div className="min-w-0 rounded border bg-background px-2 py-1">
                                <div className="text-[10px] font-medium uppercase text-muted-foreground">
                                    {t('Ticket source')}
                                </div>
                                <div className="truncate text-xs" title={sourceProofTicket}>
                                    {shortProofValue(sourceProofTicket, 48)}
                                </div>
                            </div>
                        )}
                        {sourceProofMessage && (
                            <div className="min-w-0 rounded border bg-background px-2 py-1">
                                <div className="text-[10px] font-medium uppercase text-muted-foreground">
                                    {t('Message source')}
                                </div>
                                <div className="truncate text-xs" title={sourceProofMessage}>
                                    {shortProofValue(sourceProofMessage, 48)}
                                </div>
                            </div>
                        )}
                    </div>
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                    {visibleDetails.map(detail => (
                        <div key={`${detail.label}:${detail.value}`} className="min-w-0 rounded-md border bg-muted/20 px-2 py-1.5">
                            <div className="text-[10px] font-medium uppercase text-muted-foreground">
                                {t(detail.label)}
                            </div>
                            <div className="truncate text-xs" title={detail.value}>
                                {shortProofValue(detail.value, 56)}
                            </div>
                        </div>
                    ))}
                </div>
                {sourceInfo.details.length > visibleDetails.length && (
                    <div className="mt-2 text-xs text-muted-foreground">
                        +{sourceInfo.details.length - visibleDetails.length} {t('more source fields')}
                    </div>
                )}
            </section>
        );
    })() : null;

    const channelWebhookEventsPanel = selectedIssue ? (() => {
        const events = selectedIssue.channelWebhookEvents ?? [];
        if (events.length === 0) return null;
        const visibleEvents = events.slice(0, 4);
        return (
            <section data-channel-events-panel className="rounded-md border bg-background p-3">
                <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                        <div className="flex min-w-0 items-center gap-2 text-sm font-medium">
                            <Bell className="size-4 shrink-0 text-muted-foreground" />
                            <span className="truncate">{t('Channel events')}</span>
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                            {t('Provider events linked to this ticket.')}
                        </div>
                    </div>
                    <Badge variant="outline" className="font-normal">
                        {events.length}
                    </Badge>
                </div>
                <div className="grid gap-2">
                    {visibleEvents.map(event => {
                        const details = channelWebhookEventDetails(event).slice(0, 4);
                        return (
                            <div key={event.id || `${event.provider}:${event.eventId}`} className="rounded-md border bg-muted/20 p-2">
                                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                                    <div className="min-w-0">
                                        <div className="truncate text-sm font-medium">
                                            {event.eventType || t('Provider event')}
                                        </div>
                                        <div className="text-xs text-muted-foreground">
                                            {[event.provider, formatTime(event.receivedAt)].filter(Boolean).join(' - ')}
                                        </div>
                                    </div>
                                    <Badge variant={channelWebhookEventStatusVariant(event.status)} className="font-normal">
                                        {t(event.status || 'unknown')}
                                    </Badge>
                                </div>
                                {details.length > 0 && (
                                    <div className="grid gap-2 sm:grid-cols-2">
                                        {details.map(detail => (
                                            <div key={`${event.id}:${detail.label}:${detail.value}`} className="min-w-0 rounded border bg-background px-2 py-1">
                                                <div className="text-[10px] font-medium uppercase text-muted-foreground">
                                                    {t(detail.label)}
                                                </div>
                                                <div className="truncate text-xs" title={detail.value}>
                                                    {shortProofValue(detail.value, 48)}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                                {event.error && (
                                    <div className="mt-2 rounded border bg-background px-2 py-1 text-xs text-muted-foreground">
                                        {event.error}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
                {events.length > visibleEvents.length && (
                    <div className="mt-2 text-xs text-muted-foreground">
                        +{events.length - visibleEvents.length} {t('more channel events')}
                    </div>
                )}
            </section>
        );
    })() : null;

    const autopilotProofPanel = selectedIssue ? (() => {
        const proof = latestAutopilotProof(selectedIssue);
        if (!proof) return null;
        const replyWithheld = proof.actions.some(
            action => action.type === 'prepare_agent_reply' && action.status === 'withheld',
        );
        const proofBadgeLabel = proof.complete ? 'Complete' : proof.failed ? 'Failed' : 'Needs review';
        const proofBadgeVariant = proof.failed ? 'destructive' : proof.complete ? 'secondary' : 'outline';
        const proofDescription = proof.failed
            ? 'Channel automation failed.'
            : replyWithheld
                ? 'Agent reply was withheld because no grounded draft was created.'
                : proof.complete
                    ? 'Agent package prepared from channel automation.'
                    : 'Agent package needs review.';
        return (
            <section data-autopilot-proof-panel className="rounded-md border bg-background p-3">
                <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                        <div className="flex min-w-0 items-center gap-2 text-sm font-medium">
                            <Sparkles className="size-4 shrink-0 text-muted-foreground" />
                            <span className="truncate">{t('Autopilot proof')}</span>
                        </div>
                        <div data-autopilot-proof-description className="mt-1 text-xs text-muted-foreground">
                            {t(proofDescription)}
                        </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                        <Badge variant={proofBadgeVariant} className="font-normal">
                            {t(proofBadgeLabel)}
                        </Badge>
                        {proof.channelKey && (
                            <Badge variant="outline" className="font-normal">
                                {shortProofValue(proof.channelKey, 36)}
                            </Badge>
                        )}
                        <Badge variant="outline" className="font-normal">
                            {t(proof.onUpdate ? 'Follow-up' : 'New ticket')}
                        </Badge>
                    </div>
                </div>
                {proof.gaps.length > 0 && (
                    <div className="mb-3 flex min-w-0 items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-900">
                        <AlertTriangle className="size-3.5 shrink-0" />
                        <span className="min-w-0 truncate">
                            {t('Package incomplete')}: {proof.gaps.map(gap => t(gap)).join(', ')}
                        </span>
                    </div>
                )}
                <div className="grid gap-2 sm:grid-cols-3">
                    {proof.actions.map(action => (
                        <div
                            key={action.type}
                            data-autopilot-action={action.type}
                            data-autopilot-action-status={action.status}
                            className="rounded-md border bg-muted/20 p-2 text-xs"
                        >
                            <div className="mb-1 flex min-w-0 items-center justify-between gap-2">
                                <span className="min-w-0 truncate font-medium">{t(action.label)}</span>
                                <Badge variant={autopilotStatusVariant(action.status)} className="font-normal">
                                    {t(action.status)}
                                </Badge>
                            </div>
                            {action.fieldCount > 0 && (
                                <div className="truncate text-muted-foreground">
                                    {t('Fields')}: {action.fieldCount}
                                </div>
                            )}
                            {action.replyId && (
                                <div className="truncate text-muted-foreground">
                                    {t('Reply')}: {shortProofValue(action.replyId, 32)}
                                </div>
                            )}
                            {action.executionId && (
                                <div className="truncate text-muted-foreground">
                                    {t('Execution')}: {shortProofValue(action.executionId, 32)}
                                </div>
                            )}
                            {action.runId && (
                                <div className="truncate text-muted-foreground">
                                    {t('Run')}: {shortProofValue(action.runId, 32)}
                                </div>
                            )}
                            {action.reason && (
                                <div className="mt-1 line-clamp-2 text-muted-foreground">
                                    {t('Reason')}: {action.reason}
                                </div>
                            )}
                            {action.error && (
                                <div className="mt-1 line-clamp-2 text-destructive">
                                    {t('Error')}: {action.error}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5 text-xs text-muted-foreground">
                    {proof.replyId && <Badge variant="outline" className="font-normal">{t('Draft reply')}: {shortProofValue(proof.replyId, 32)}</Badge>}
                    {proof.aiRunId && <Badge variant="outline" className="font-normal">{t('AI run')}: {shortProofValue(proof.aiRunId, 32)}</Badge>}
                    {proof.channelType && <Badge variant="outline" className="font-normal">{proof.channelType}</Badge>}
                    {proof.source && <Badge variant="outline" className="font-normal">{proof.source}</Badge>}
                    <Badge variant="outline" className="font-normal">{formatTime(proof.event.occurredAt || proof.event.created)}</Badge>
                </div>
                {proof.failed && proof.event.body && (
                    <div className="mt-3 rounded-md border bg-muted/20 p-2 text-xs text-muted-foreground">
                        {proof.event.body}
                    </div>
                )}
            </section>
        );
    })() : null;

    const reviewPackagePanel = selectedIssue && pendingReviewCount > 0 ? (
        <section data-ticket-review-package className="rounded-md border bg-background p-3">
            <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                    <div className="flex min-w-0 items-center gap-2 text-sm font-medium">
                        <CheckCircle2 className="size-4 shrink-0 text-muted-foreground" />
                        <span className="truncate">{t('Review package')}</span>
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                        {t('AI prepared items awaiting approval.')}
                    </div>
                </div>
                <div className="flex flex-wrap justify-end gap-1.5">
                    {pendingReviewReplies.length > 0 && (
                        <Badge variant="secondary" className="font-normal">
                            {pendingReviewReplies.length} {t('reply drafts')}
                        </Badge>
                    )}
                    {pendingReviewActions.length > 0 && (
                        <Badge variant="secondary" className="font-normal">
                            {pendingReviewActions.length} {t('action proposals')}
                        </Badge>
                    )}
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 px-2 text-xs"
                        data-ticket-review-package-approve
                        onClick={() => void reviewSelectedIssuePackage('approve')}
                        disabled={reviewPackageBusy}
                    >
                        {reviewingPackageMode === 'approve' ? <Loader className="size-3 animate-spin" /> : <CheckCircle2 className="size-3" />}
                        {t('Approve package')}
                    </Button>
                    {pendingReviewReplies.length > 0 && (
                        <Button
                            type="button"
                            size="sm"
                            className="h-7 px-2 text-xs"
                            data-ticket-review-package-approve-send
                            data-ticket-review-package-readiness-blocked={selectedReplySendBlocked ? 'true' : 'false'}
                            onClick={() => void reviewSelectedIssuePackage('approve-send')}
                            disabled={reviewPackageBusy || selectedReplySendBlocked}
                            title={selectedReplySendBlocked ? selectedReplySendBlockDetail : undefined}
                        >
                            {reviewingPackageMode === 'approve-send' ? <Loader className="size-3 animate-spin" /> : <Send className="size-3" />}
                            {t('Approve & send package')}
                        </Button>
                    )}
                </div>
            </div>
            <div className="grid gap-3 lg:grid-cols-2">
                {pendingReviewReplies.length > 0 && (
                    <div className="space-y-2">
                        <div className="flex items-center justify-between gap-2 text-xs font-medium uppercase text-muted-foreground">
                            <span>{t('Pending reply drafts')}</span>
                            <Badge variant="outline" className="font-normal">{pendingReviewReplies.length}</Badge>
                        </div>
                        {pendingReviewReplies.map(reply => (
                            <div key={reply.id} className="rounded-md border bg-muted/20 p-2 text-sm">
                                <div className="mb-1 flex items-center justify-between gap-2">
                                    <span className="min-w-0 truncate font-medium">{reply.subject || t('Reply draft')}</span>
                                    <div className="flex shrink-0 items-center gap-1.5">
                                        <Badge variant="secondary" className="font-normal">{t('Approval required')}</Badge>
                                        <Badge variant="outline" className="font-normal">{t(reply.status)}</Badge>
                                    </div>
                                </div>
                                <div className="mb-2 truncate text-xs text-muted-foreground">
                                    {replyTargetDetail(reply) || selectedIssue.contactEmail || selectedIssue.fromAddress || '-'} · {formatTime(reply.created)}
                                </div>
                                <pre className="max-h-28 overflow-auto whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
                                    {reply.body}
                                </pre>
                                <InboxAttachments attachments={replyAttachmentItems(reply)} t={t} />
                                <div className="mt-2 flex flex-wrap justify-end gap-1.5">
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant="outline"
                                        className="h-7 px-2 text-xs"
                                        data-outbound-reply-request-changes={reply.id}
                                        onClick={() => openChangeRequest(reply)}
                                        disabled={Boolean(approvingReplyId || sendingReplyId || savingReplyEditId || requestingChangesReplyId)}
                                    >
                                        <AlertTriangle className="size-3" />
                                        {t('Request changes')}
                                    </Button>
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant="outline"
                                        className="h-7 px-2 text-xs"
                                        onClick={() => void approveReply(reply)}
                                        disabled={Boolean(approvingReplyId || sendingReplyId || savingReplyEditId || requestingChangesReplyId)}
                                    >
                                        {approvingReplyId === reply.id ? <Loader className="size-3 animate-spin" /> : <CheckCircle2 className="size-3" />}
                                        {t('Approve')}
                                    </Button>
                                    <Button
                                        type="button"
                                        size="sm"
                                        className="h-7 px-2 text-xs"
                                        onClick={() => void sendReply(reply, true)}
                                        disabled={Boolean(approvingReplyId || sendingReplyId || savingReplyEditId || requestingChangesReplyId || selectedReplySendBlocked)}
                                        title={selectedReplySendBlocked ? selectedReplySendBlockDetail : undefined}
                                        data-outbound-reply-readiness-blocked={selectedReplySendBlocked ? 'true' : 'false'}
                                    >
                                        {sendingReplyId === reply.id ? <Loader className="size-3 animate-spin" /> : <Send className="size-3" />}
                                        {t('Approve & send')}
                                    </Button>
                                </div>
                                {changeRequestReplyId === reply.id && (
                                    <div className="mt-2 space-y-2 rounded-md border bg-background p-2">
                                        <Label htmlFor={`package-change-request-${reply.id}`} className="text-xs">
                                            {t('Requested changes')}
                                        </Label>
                                        <Textarea
                                            id={`package-change-request-${reply.id}`}
                                            data-outbound-change-note={reply.id}
                                            value={changeRequestNote}
                                            onChange={event => setChangeRequestNote(event.target.value)}
                                            rows={3}
                                            placeholder={t('Explain what needs to change before approval.')}
                                        />
                                        <div className="flex justify-end gap-2">
                                            <Button
                                                type="button"
                                                size="sm"
                                                variant="outline"
                                                onClick={cancelChangeRequest}
                                                disabled={requestingChangesReplyId === reply.id}
                                            >
                                                <X className="size-3" />
                                                {t('Cancel')}
                                            </Button>
                                            <Button
                                                type="button"
                                                size="sm"
                                                data-outbound-change-submit={reply.id}
                                                onClick={() => void requestReplyChanges(reply)}
                                                disabled={requestingChangesReplyId === reply.id}
                                            >
                                                {requestingChangesReplyId === reply.id
                                                    ? <Loader className="size-3 animate-spin" />
                                                    : <AlertTriangle className="size-3" />}
                                                {t('Request changes')}
                                            </Button>
                                        </div>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}
                {pendingReviewActions.length > 0 && (
                    <div className="space-y-2">
                        <div className="flex items-center justify-between gap-2 text-xs font-medium uppercase text-muted-foreground">
                            <span>{t('Pending action proposals')}</span>
                            <Badge variant="outline" className="font-normal">{pendingReviewActions.length}</Badge>
                        </div>
                        {pendingReviewActions.map(execution => (
                            <ActionExecutionCard
                                key={execution.id}
                                execution={execution}
                                compact
                                t={t}
                                approvingActionExecutionId={approvingActionExecutionId}
                                rejectingActionExecutionId={rejectingActionExecutionId}
                                onApprove={approveActionExecution}
                                onReject={rejectActionExecution}
                            />
                        ))}
                    </div>
                )}
            </div>
        </section>
    ) : null;

    const duplicateSuggestionsPanel = selectedIssue ? (
        <section className="rounded-md border p-3" data-ticket-duplicate-panel>
            <div className="mb-3 flex items-center justify-between gap-2">
                <div className="text-sm font-medium">{t('Suggested duplicates')}</div>
                <div className="flex items-center gap-2">
                    {loadingDuplicateSuggestions && <Loader className="size-3.5 animate-spin" />}
                    <Badge variant="outline" className="font-normal">
                        {duplicateSuggestions.length}
                    </Badge>
                </div>
            </div>
            <div className="space-y-2">
                {duplicateSuggestions.slice(0, 5).map(suggestion => (
                    <div
                        key={suggestion.issue.id}
                        className="rounded-md border bg-muted/20 p-2.5"
                        data-ticket-duplicate-suggestion={suggestion.issue.id}
                    >
                        <div className="flex min-w-0 items-start justify-between gap-2">
                            <div className="min-w-0">
                                <div className="truncate text-sm font-medium">
                                    {suggestion.issue.subject || '(No subject)'}
                                </div>
                                <div className="mt-0.5 truncate text-xs text-muted-foreground">
                                    {suggestion.issue.accountName || suggestion.issue.contactEmail || suggestion.issue.fromAddress || suggestion.issue.id}
                                </div>
                            </div>
                            <Badge variant="secondary" className="shrink-0 font-normal">
                                {t(duplicateScoreLabel(suggestion.score))} · {Math.round(suggestion.score)}%
                            </Badge>
                        </div>
                        {suggestion.reasons.length > 0 && (
                            <div className="mt-2 flex flex-wrap gap-1.5">
                                {suggestion.reasons.slice(0, 4).map(reason => (
                                    <Badge key={`${suggestion.issue.id}:${reason}`} variant="outline" className="font-normal">
                                        {reason}
                                    </Badge>
                                ))}
                            </div>
                        )}
                        <div className="mt-2 flex justify-end gap-2">
                            <Button
                                type="button"
                                size="sm"
                                variant="ghost"
                                data-ticket-duplicate-open={suggestion.issue.id}
                                onClick={() => navigateToIssue(suggestion.issue.id, { viewMode })}
                            >
                                <ExternalLink className="size-3.5" />
                                {t('Open')}
                            </Button>
                            <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                data-ticket-duplicate-merge={suggestion.issue.id}
                                onClick={() => openMergeDialog(suggestion.issue.id)}
                            >
                                <Link className="size-3.5" />
                                {t('Merge')}
                            </Button>
                        </div>
                    </div>
                ))}
                {!loadingDuplicateSuggestions && duplicateSuggestions.length === 0 && (
                    <div className="text-sm text-muted-foreground">{t('No duplicate suggestions')}</div>
                )}
                <Button
                    type="button"
                    variant="outline"
                    className="w-full justify-start"
                    data-ticket-merge-duplicate-open
                    onClick={() => openMergeDialog()}
                    disabled={mergeTargetOptions.length === 0 || mergingIssue}
                >
                    <Link className="size-4" />
                    {t('Merge another ticket')}
                </Button>
            </div>
        </section>
    ) : null;

    const boardDetailPanel = (
        <Drawer
            open={Boolean(issueId)}
            onOpenChange={(open) => {
                if (!open) closeIssueDrawer({ viewMode: 'board' });
            }}
        >
        <DrawerContent
            data-ticket-drawer
            className="gap-0 overflow-hidden p-0 md:w-[min(46rem,calc(100vw-2rem))]"
            showCloseButton={false}
        >
            <DrawerTitle className="sr-only">
                {selectedIssue?.subject || t('Ticket workspace')}
            </DrawerTitle>
            <DrawerDescription className="sr-only">{t('Ticket workspace')}</DrawerDescription>
            {loadingDetail ? (
                <div className="flex h-full items-center justify-center text-muted-foreground">
                    <Loader className="mr-2 size-4 animate-spin" />
                    {t('Loading')}
                </div>
            ) : !selectedIssue ? (
                <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                    {t('Select a ticket')}
                </div>
            ) : (
                <>
                    <div className="shrink-0 border-b p-4">
                        <div className="mb-3 flex items-start justify-between gap-3">
                            <div className="min-w-0">
                                <div className="mb-2 flex flex-wrap items-center gap-1.5">
                                    <Badge variant="outline" className="gap-1 font-normal">
                                        {statusIcon(selectedIssue.status)}
                                        {workflowLabel(selectedIssue.status)}
                                    </Badge>
                                    <Badge variant={priorityVariant(selectedIssue.priority)} className="font-normal">
                                        {selectedIssue.priority}
                                    </Badge>
                                    {issueNeedsApproval(selectedIssue) && (
                                        <Badge variant="secondary" className="font-normal">
                                            {approvalLabel(selectedIssue)}
                                        </Badge>
                                    )}
                                    {issueHasFailedDelivery(selectedIssue) && (
                                        <Badge variant="destructive" className="font-normal">
                                            {failedDeliveryLabel(selectedIssue)}
                                        </Badge>
                                    )}
                                    {issueHasLowCsat(selectedIssue) && (
                                        <Badge variant="destructive" className="font-normal" title={selectedIssue.latestCsatComment || undefined}>
                                            {lowCsatLabel(selectedIssue)}
                                        </Badge>
                                    )}
                                </div>
                                <h2 className="truncate text-base font-semibold">{selectedIssue.subject || '(No subject)'}</h2>
                                <div className="mt-1 truncate text-xs text-muted-foreground">
                                    {selectedIssue.accountName || selectedIssue.contactEmail || selectedIssue.fromAddress || '-'}
                                </div>
                            </div>
                            <div className="flex shrink-0 items-center gap-1">
                                <Button
                                    type="button"
                                    size="icon"
                                    variant="ghost"
                                    className="size-8"
                                    onClick={() => navigateToIssue(selectedIssue.id, { viewMode: 'list' })}
                                    aria-label={t('List')}
                                >
                                    <List className="size-4" />
                                </Button>
                                <Button
                                    type="button"
                                    size="icon"
                                    variant="ghost"
                                    className="size-8"
                                    onClick={closeBoardDetail}
                                    aria-label={t('Close')}
                                >
                                    <X className="size-4" />
                                </Button>
                            </div>
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                            <Badge variant="secondary" className="font-normal">{issueQueueLabel(selectedIssue)}</Badge>
                            {selectedIssue.channel && <Badge variant="outline" className="font-normal">{selectedIssue.channel}</Badge>}
                            {(selectedIssue.tags ?? []).slice(0, 3).map(tag => (
                                <Badge key={tag} variant="outline" className="font-normal">{tag}</Badge>
                            ))}
                        </div>
                    </div>

                    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
                        {ticketWorkspacePanel}
                        {ticketOperatingProofPanel}
                        {ticketConversationPanel}
                        {channelSourcePanel}
                        {channelWebhookEventsPanel}
                        {autopilotProofPanel}
                        {reviewPackagePanel}
                        {duplicateSuggestionsPanel}

                        <section className="rounded-md border bg-muted/20 p-3">
                            <div className="mb-2 text-sm font-medium">{t('AI summary')}</div>
                            <p className="whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
                                {selectedIssue.aiSummary || '-'}
                            </p>
                        </section>

                        <section className="rounded-md border p-3">
                            <div className="mb-3 flex items-center justify-between gap-2">
                                <div className="text-sm font-medium">{t('Workflow')}</div>
                                {!selectedIssue.assigneeEmail && (
                                    <Badge variant="outline" className="font-normal" title={issueAssignmentDetail(selectedIssue)}>
                                        {t(issueAssignmentBadge(selectedIssue))}
                                    </Badge>
                                )}
                            </div>
                            <div className="grid gap-3 sm:grid-cols-2">
                                <div className="space-y-1.5">
                                    <Label>{t('Status')}</Label>
                                    <Select
                                        value={issueWorkflowStatus(selectedIssue)}
                                        onValueChange={(value) => void patchSelectedIssue({ status: value as SupportIssueStatus })}
                                    >
                                        <SelectTrigger className="w-full">
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {statusOptions.map(option => {
                                                const doneBlocked = option.value === 'done'
                                                    && issueWorkflowStatus(selectedIssue) !== 'done'
                                                    && issueDoneBlockers(selectedIssue).length > 0;
                                                return (
                                                    <SelectItem
                                                        key={option.value}
                                                        value={option.value}
                                                        disabled={
                                                            (statusNeedsAssignee(option.value) && !selectedIssue.assigneeEmail && !canAutoClaim)
                                                            || doneBlocked
                                                        }
                                                    >
                                                        {t(option.label)}
                                                    </SelectItem>
                                                );
                                            })}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div className="space-y-1.5">
                                    <Label>{t('Priority')}</Label>
                                    <Select
                                        value={selectedIssue.priority}
                                        onValueChange={(value) => void patchSelectedIssue({ priority: value as SupportIssuePriority })}
                                    >
                                        <SelectTrigger className="w-full">
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {priorityOptions.map(option => (
                                                <SelectItem key={option.value} value={option.value}>{t(option.label)}</SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div className="space-y-1.5">
                                    <Label>{t('Queue')}</Label>
                                    <Select
                                        value={issueQueueKey(selectedIssue) || NO_QUEUE_VALUE}
                                        onValueChange={(value) => void assignQueue(value)}
                                        disabled={savingQueue}
                                    >
                                        <SelectTrigger className="w-full">
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {queueOptions.map(option => (
                                                <SelectItem key={option.queueKey} value={option.queueKey}>{option.name}</SelectItem>
                                            ))}
                                            <SelectItem value={NO_QUEUE_VALUE}>{t('No queue')}</SelectItem>
                                        </SelectContent>
                                    </Select>
                                    {selectedQueueOwnerEmails.length > 0 && (
                                        <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                                            <span>{t('Queue owners')}:</span>
                                            {selectedQueueOwnerEmails.map(email => {
                                                const workload = selectedQueueOwnerWorkloads.get(email.toLowerCase());
                                                return (
                                                    <Badge
                                                        key={email}
                                                        variant={workload?.atCapacity ? 'outline' : 'secondary'}
                                                        className="font-normal"
                                                        title={queueOwnerWorkloadDetail(email, workload)}
                                                    >
                                                        {queueOwnerWorkloadLabel(email, workload)}
                                                    </Badge>
                                                );
                                            })}
                                        </div>
                                    )}
                                </div>
                                <div className="space-y-1.5">
                                    <Label htmlFor="board-issue-assignee">{t('Assignee')}</Label>
                                    <div className="flex gap-2">
                                        {assigneeOptions.length > 0 ? (
                                            <Select
                                                value={assigneeDraft || UNASSIGNED_VALUE}
                                                onValueChange={(value) => setAssigneeDraft(value === UNASSIGNED_VALUE ? '' : value)}
                                            >
                                                <SelectTrigger id="board-issue-assignee" className="min-w-0 flex-1">
                                                    <SelectValue />
                                                </SelectTrigger>
                                                <SelectContent>
                                                    <SelectItem value={UNASSIGNED_VALUE}>{t('Unassigned')}</SelectItem>
                                                    {assigneeOptions.map(email => {
                                                        const workload = selectedQueueOwnerWorkloads.get(email.toLowerCase());
                                                        return (
                                                            <SelectItem key={email} value={email}>
                                                                {queueOwnerWorkloadLabel(email, workload)}
                                                            </SelectItem>
                                                        );
                                                    })}
                                                </SelectContent>
                                            </Select>
                                        ) : (
                                            <Input
                                                id="board-issue-assignee"
                                                value={assigneeDraft}
                                                onChange={event => setAssigneeDraft(event.target.value)}
                                                placeholder="agent@example.com"
                                            />
                                        )}
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            onClick={() => void saveAssignee()}
                                            disabled={savingAssignee || selectedIssue.assigneeEmail === assigneeDraft}
                                        >
                                            {savingAssignee ? <Loader className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
                                            {t('Save')}
                                        </Button>
                                    </div>
                                    {selectedAssigneeWorkloadDetail && (
                                        <div className={`flex items-start gap-1.5 text-xs ${selectedAssigneeWorkload?.atCapacity ? 'text-amber-700' : 'text-muted-foreground'}`}>
                                            {selectedAssigneeWorkload?.atCapacity && <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />}
                                            <span>{selectedAssigneeWorkloadDetail}</span>
                                        </div>
                                    )}
                                    {!selectedIssue.assigneeEmail && canAutoClaim && (
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="ghost"
                                            className="h-7 px-2 text-xs"
                                            onClick={() => void assignIssue(currentUserEmail.trim())}
                                            disabled={savingAssignee}
                                        >
                                            {t('Assign to me')}
                                        </Button>
                                    )}
                                </div>
                            </div>
                            {issueWorkflowStatus(selectedIssue) !== 'done' && issueDoneBlockerText(selectedIssue) && (
                                <div className="mt-3 flex items-center gap-1.5 rounded-md border border-destructive/30 bg-destructive/5 px-2 py-1.5 text-xs text-destructive">
                                    <AlertTriangle className="size-3.5 shrink-0" />
                                    <span>{t('Resolve before closing')}: {issueDoneBlockerText(selectedIssue)}</span>
                                </div>
                            )}
                            {issueWorkflowStatus(selectedIssue) !== 'done' && issueCanResolveWithoutReply(selectedIssue) && (
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    className="mt-3"
                                    onClick={openCloseWithoutReplyDialog}
                                    data-ticket-close-without-reply-open
                                >
                                    <CheckCircle2 className="size-3.5" />
                                    {t('Close without reply')}
                                </Button>
                            )}
                            {!selectedIssue.assigneeEmail && (
                                <div className="mt-3 flex items-start gap-1.5 text-xs text-muted-foreground">
                                    <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
                                    <div className="space-y-1">
                                        <div>
                                            {canAutoClaim
                                                ? t('Working this ticket assigns it to you.')
                                                : t('Assign before changing status.')}
                                        </div>
                                        <div>{t(issueAssignmentDetail(selectedIssue))}</div>
                                        {issueAssignmentHint(selectedIssue) && (
                                            <div>{t(issueAssignmentHint(selectedIssue))}</div>
                                        )}
                                    </div>
                                </div>
                            )}
                            <div className="mt-3 space-y-2">
                                <Label htmlFor="board-issue-labels">{t('Labels')}</Label>
                                <div className="flex flex-wrap gap-1.5">
                                    {(selectedIssue.tags ?? []).length === 0 ? (
                                        <span className="text-xs text-muted-foreground">-</span>
                                    ) : (
                                        (selectedIssue.tags ?? []).map(tag => (
                                            <Badge key={tag} variant="outline" className="gap-1 font-normal">
                                                {tag}
                                                <button
                                                    type="button"
                                                    onClick={() => void removeTag(tag)}
                                                    disabled={savingTags}
                                                    aria-label={t('Remove label')}
                                                    className="rounded-full text-muted-foreground hover:text-foreground disabled:pointer-events-none disabled:opacity-50"
                                                >
                                                    <X className="size-3" />
                                                </button>
                                            </Badge>
                                        ))
                                    )}
                                </div>
                                <div className="flex gap-2">
                                    <Input
                                        id="board-issue-labels"
                                        value={tagDraft}
                                        onChange={event => setTagDraft(event.target.value)}
                                        placeholder="billing, vip"
                                    />
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant="outline"
                                        onClick={() => void saveTags()}
                                        disabled={savingTags}
                                    >
                                        {savingTags ? <Loader className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
                                        {t('Save')}
                                    </Button>
                                </div>
                            </div>
                        </section>

                        {customFieldsPanel}

                        <section className="rounded-md border p-3">
                            <div className="mb-3 flex items-center justify-between gap-2">
                                <div className="text-sm font-medium">{t('Collaboration')}</div>
                                <div className="flex items-center gap-1.5">
                                    {currentUserEmail && (
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            data-ticket-watch-toggle
                                            onClick={() => void toggleWatching()}
                                            disabled={togglingWatcher}
                                        >
                                            {togglingWatcher ? <Loader className="size-3.5 animate-spin" /> : <Bell className="size-3.5" />}
                                            {currentWatcher ? t('Unwatch') : t('Watch')}
                                        </Button>
                                    )}
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant="outline"
                                        data-ticket-create-portal-link
                                        onClick={() => void createPortalLink()}
                                        disabled={creatingPortalLink}
                                    >
                                        {creatingPortalLink ? <Loader className="size-3.5 animate-spin" /> : <Link className="size-3.5" />}
                                        {t('Portal')}
                                    </Button>
                                </div>
                            </div>
                            {portalUrl && (
                                <div className="mb-3 flex min-w-0 items-center gap-2 rounded-md border bg-muted/20 p-2 text-xs">
                                    <a
                                        href={portalUrl}
                                        target="_blank"
                                        rel="noreferrer"
                                        className="min-w-0 flex-1 truncate underline"
                                        data-ticket-portal-url
                                    >
                                        {portalUrl}
                                    </a>
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant="ghost"
                                        onClick={() => {
                                            void navigator.clipboard?.writeText(portalUrl);
                                            toast.success(t('Copied'));
                                        }}
                                    >
                                        <Copy className="size-3.5" />
                                    </Button>
                                </div>
                            )}
                            <div className="grid gap-3">
                                <div className="grid gap-3 sm:grid-cols-2">
                                    <div className="min-w-0 space-y-2">
                                        <div className="flex items-center justify-between gap-2 text-xs font-medium uppercase text-muted-foreground">
                                            <span>{t('Watchers')}</span>
                                            <Badge variant="outline" className="font-normal">{selectedWatchers.length}</Badge>
                                        </div>
                                        {selectedWatchers.length === 0 ? (
                                            <div className="text-sm text-muted-foreground">-</div>
                                        ) : (
                                            <div className="space-y-1.5">
                                                {selectedWatchers.slice(0, 3).map(watcher => (
                                                    <div key={watcher.id || watcher.watcherEmail} className="rounded-md border bg-muted/20 p-2 text-xs" data-ticket-watcher-row data-ticket-watcher-email={watcher.watcherEmail}>
                                                        <div className="truncate font-medium">{watcher.watcherEmail}</div>
                                                        <div className="mt-0.5 truncate text-muted-foreground">
                                                            {watcher.source || 'manual'} · {watcher.addedBy || '-'}
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                    <div className="min-w-0 space-y-2">
                                        <div className="flex items-center justify-between gap-2 text-xs font-medium uppercase text-muted-foreground">
                                            <span>{t('SLA')}</span>
                                            <Badge variant="outline" className="font-normal">{(selectedIssue.slaEvents ?? []).length}</Badge>
                                        </div>
                                        {(selectedIssue.slaEvents ?? []).length === 0 ? (
                                            <div className="text-sm text-muted-foreground">-</div>
                                        ) : (
                                            <div className="space-y-1.5">
                                                {(selectedIssue.slaEvents ?? []).slice(0, 2).map(event => {
                                                    const overdue = slaEventIsOverdue(event);
                                                    return (
                                                        <div key={event.id} className="rounded-md border bg-muted/20 p-2 text-xs">
                                                            <div className="flex items-center justify-between gap-2">
                                                                <span className="truncate">{t(slaEventLabel(event.eventType))}</span>
                                                                <Badge variant={overdue ? 'destructive' : 'outline'} className="font-normal">
                                                                    {overdue ? t('Overdue') : event.status}
                                                                </Badge>
                                                            </div>
                                                            <div className="mt-1 text-muted-foreground">{formatTime(event.targetAt)}</div>
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        )}
                                    </div>
                                </div>
                                <div className="space-y-2">
                                    <div className="flex items-center justify-between gap-2 text-xs font-medium uppercase text-muted-foreground">
                                        <span>{t('Internal notes')}</span>
                                        <Badge variant="outline" className="font-normal">{(selectedIssue.notes ?? []).length}</Badge>
                                    </div>
                                    {(selectedIssue.notes ?? []).length > 0 && (
                                        <div className="space-y-1.5">
                                            {(selectedIssue.notes ?? []).slice(-2).map(note => (
                                                <div key={note.id} className="rounded-md border bg-muted/20 p-2 text-sm">
                                                    <div className="mb-1 text-xs text-muted-foreground">
                                                        {note.authorEmail || '-'} · {formatTime(note.created)}
                                                    </div>
                                                    <div className="whitespace-pre-wrap">{note.body}</div>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                    <Textarea
                                        id="board-internal-note"
                                        data-ticket-internal-note-input
                                        value={noteDraft}
                                        onChange={event => setNoteDraft(event.target.value)}
                                        rows={3}
                                        placeholder={t('Internal note')}
                                    />
                                    <div className="flex justify-end">
                                        <Button
                                            type="button"
                                            size="sm"
                                            data-ticket-internal-note-submit
                                            onClick={() => void addNote()}
                                            disabled={savingNote || !noteDraft.trim()}
                                        >
                                            {savingNote ? <Loader className="size-3.5 animate-spin" /> : <Plus className="size-3.5" />}
                                            {t('Add note')}
                                        </Button>
                                    </div>
                                </div>
                            </div>
                        </section>

                        {(selectedIssue.accountId || loadingTicketAccount) && (
                            <section className="rounded-md border p-3">
                                <div className="mb-3 flex items-center justify-between gap-2">
                                    <div className="flex min-w-0 items-center gap-2 text-sm font-medium">
                                        <Building2 className="size-4 shrink-0" />
                                        <span className="truncate">{t('Account intelligence')}</span>
                                    </div>
                                    {ticketAccount && tenantId && (
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            onClick={() => navigate(`/${tenantId}/${projectId}/accounts/${ticketAccount.id}`)}
                                        >
                                            <ExternalLink className="size-3.5" />
                                            {t('Open')}
                                        </Button>
                                    )}
                                </div>
                                {loadingTicketAccount ? (
                                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                                        <Loader className="size-3.5 animate-spin" />
                                        {t('Loading')}
                                    </div>
                                ) : ticketAccount && ticketAccountInsightSummary && ticketAccountCrmHealth ? (
                                    <div className="space-y-3">
                                        <div className="min-w-0">
                                            <div className="truncate text-sm font-medium">{accountLabel(ticketAccount)}</div>
                                            <div className="mt-1 flex flex-wrap gap-1.5">
                                                <Badge variant={accountHealthVariant(ticketAccount.healthStatus)} className="font-normal">
                                                    {ticketAccount.healthStatus || 'unknown'}
                                                </Badge>
                                                <Badge variant={ticketAccountCrmHealth.variant} className="font-normal">
                                                    {t(ticketAccountCrmHealth.label)}
                                                </Badge>
                                            </div>
                                        </div>
                                        <div className="grid grid-cols-3 gap-2">
                                            <div className="rounded-md border bg-muted/20 p-2">
                                                <div className="text-[11px] text-muted-foreground">{t('Risks')}</div>
                                                <div className="text-base font-semibold">{ticketAccountInsightSummary.openRisks}</div>
                                            </div>
                                            <div className="rounded-md border bg-muted/20 p-2">
                                                <div className="text-[11px] text-muted-foreground">{t('Requests')}</div>
                                                <div className="text-base font-semibold">{ticketAccountInsightSummary.openFeatureRequests}</div>
                                            </div>
                                            <div className="rounded-md border bg-muted/20 p-2">
                                                <div className="text-[11px] text-muted-foreground">{t('Signals')}</div>
                                                <div className="text-base font-semibold">{ticketAccountInsightSummary.unresolved}</div>
                                            </div>
                                        </div>
                                        {accountInsightActions}
                                        <div className="rounded-md border bg-muted/20 p-2 text-sm">
                                            <div className="mb-1 flex items-center justify-between gap-2">
                                                <span className="flex min-w-0 items-center gap-1.5">
                                                    <Database className="size-3.5 shrink-0 text-muted-foreground" />
                                                    <span className="truncate">
                                                        {ticketAccountCrmHealth.providers.length > 0
                                                            ? ticketAccountCrmHealth.providers.map(providerLabel).join(', ')
                                                            : t('No CRM provider')}
                                                    </span>
                                                </span>
                                                <Badge variant="outline" className="shrink-0 font-normal">
                                                    {ticketAccountCrmHealth.externalObjects.length}
                                                </Badge>
                                            </div>
                                            {ticketAccountCrmHealth.latestRun ? (
                                                <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                                                    <span>{t('Latest sync')} {formatTime(syncRunTime(ticketAccountCrmHealth.latestRun))}</span>
                                                    <Badge variant={syncVariant(ticketAccountCrmHealth.latestRun.status)} className="shrink-0 font-normal">
                                                        {ticketAccountCrmHealth.latestRun.status || 'unknown'}
                                                    </Badge>
                                                </div>
                                            ) : (
                                                <div className="text-xs text-muted-foreground">{t('No sync history')}</div>
                                            )}
                                            {ticketAccountCrmHealth.failedRuns[0]?.error && (
                                                <div className="mt-1 text-xs text-destructive">
                                                    {ticketAccountCrmHealth.failedRuns[0].error}
                                                </div>
                                            )}
                                        </div>
                                        <div className="space-y-2">
                                            <div className="text-xs font-medium uppercase text-muted-foreground">{t('Open account signals')}</div>
                                            {ticketAccountOpenInsights.length === 0 ? (
                                                <div className="text-sm text-muted-foreground">-</div>
                                            ) : (
                                                ticketAccountOpenInsights.slice(0, 2).map(renderTicketAccountInsightCard)
                                            )}
                                        </div>
                                    </div>
                                ) : (
                                    <div className="text-sm text-muted-foreground">{t('No account intelligence')}</div>
                                )}
                            </section>
                        )}

                        <section className="rounded-md border p-3">
                            <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                                <Mail className="size-4 text-muted-foreground" />
                                {t('Contact')}
                            </div>
                            <div className="grid gap-2 text-sm sm:grid-cols-3">
                                <div className="min-w-0">
                                    <div className="text-xs text-muted-foreground">{t('Name')}</div>
                                    <div className="truncate">{selectedIssue.contactName || '-'}</div>
                                </div>
                                <div className="min-w-0">
                                    <div className="text-xs text-muted-foreground">{t('Email')}</div>
                                    <div className="truncate">{selectedIssue.contactEmail || selectedIssue.fromAddress || '-'}</div>
                                </div>
                                <div className="min-w-0">
                                    <div className="text-xs text-muted-foreground">{t('Account')}</div>
                                    <div className="truncate">{selectedIssue.accountName || selectedIssue.accountDomain || '-'}</div>
                                </div>
                            </div>
                        </section>

                        <section className="rounded-md border p-3">
                            <div className="mb-3 flex items-center justify-between gap-2">
                                <div className="flex items-center gap-2 text-sm font-medium">
                                    <Sparkles className="size-4 text-muted-foreground" />
                                    {t('Automation audit')}
                                </div>
                                <Badge variant="outline" className="font-normal">
                                    {auditAiRuns.length} {t('AI runs')}
                                </Badge>
                            </div>
                            <div className="space-y-3">
                                <RunbookAudit
                                    primaryIntent={selectedIssue.activatedIntent}
                                    concerns={auditRunbookConcerns}
                                    t={t}
                                />
                                <Separator />
                                <div className="space-y-2">
                                    <div className="flex items-center justify-between gap-2 text-xs font-medium uppercase text-muted-foreground">
                                        <span>{t('Actions')}</span>
                                        <Badge variant="outline" className="font-normal">{(selectedIssue.actionLog ?? []).length}</Badge>
                                    </div>
                                    {(selectedIssue.actionLog ?? []).length === 0 ? (
                                        <div className="text-sm text-muted-foreground">-</div>
                                    ) : (
                                        (selectedIssue.actionLog ?? []).slice(0, 2).map((action, index) => (
                                            <div key={`${action.label}-${index}`} className="rounded-md border bg-muted/20 p-2 text-sm">
                                                <div className="mb-2 flex items-center justify-between gap-2">
                                                    <span className="min-w-0 truncate">{action.label}</span>
                                                    <Badge variant="outline" className="shrink-0 font-normal">{action.status}</Badge>
                                                </div>
                                                <div className="flex flex-wrap gap-1.5">
                                                    {(['running', 'success', 'failed'] as const).map(status => {
                                                        const key = `${action.type || 'action'}:${action.label || index}:${status}`;
                                                        return (
                                                            <Button
                                                                key={status}
                                                                type="button"
                                                                size="sm"
                                                                variant="outline"
                                                                className="h-7 px-2 text-xs"
                                                                onClick={() => void recordAction(action, index, status)}
                                                                disabled={Boolean(savingActionKey)}
                                                            >
                                                                {savingActionKey === key ? <Loader className="size-3 animate-spin" /> : null}
                                                                {status}
                                                            </Button>
                                                        );
                                                    })}
                                                </div>
                                            </div>
                                        ))
                                    )}
                                </div>
                                <div className="grid gap-3 sm:grid-cols-2">
                                    <div className="space-y-2">
                                        <div className="flex items-center justify-between gap-2 text-xs font-medium uppercase text-muted-foreground">
                                            <span>{t('Action history')}</span>
                                            <Badge variant="outline" className="font-normal">{(selectedIssue.actionExecutions ?? []).length}</Badge>
                                        </div>
                                        {(selectedIssue.actionExecutions ?? []).length === 0 ? (
                                            <div className="text-sm text-muted-foreground">-</div>
                                        ) : (
                                            (selectedIssue.actionExecutions ?? []).slice(0, 2).map(execution => (
                                                <ActionExecutionCard
                                                    key={execution.id}
                                                    execution={execution}
                                                    compact
                                                    t={t}
                                                    approvingActionExecutionId={approvingActionExecutionId}
                                                    rejectingActionExecutionId={rejectingActionExecutionId}
                                                    onApprove={approveActionExecution}
                                                    onReject={rejectActionExecution}
                                                />
                                            ))
                                        )}
                                    </div>
                                    <div className="space-y-2">
                                        <div className="flex items-center justify-between gap-2 text-xs font-medium uppercase text-muted-foreground">
                                            <span>{t('AI runs')}</span>
                                            <Badge variant="outline" className="font-normal">{auditAiRuns.length}</Badge>
                                        </div>
                                        {auditAiRuns.length === 0 ? (
                                            <div className="text-sm text-muted-foreground">-</div>
                                        ) : (
                                            auditAiRuns.slice(0, 2).map(run => (
                                                <div key={run.id} className="rounded-md border bg-muted/20 p-2 text-sm">
                                                    <div className="flex items-center justify-between gap-2">
                                                        <span className="min-w-0 truncate">{run.activatedIntent || t('No match')}</span>
                                                        <Badge variant="outline" className="shrink-0 font-normal">{run.status}</Badge>
                                                    </div>
                                                    <div className="mt-1 truncate text-xs text-muted-foreground">
                                                        {run.source || '-'} · {tokenTotal(run.tokenUsage)} {t('tokens')}
                                                    </div>
                                                    {run.requiresHuman && (
                                                        <div className="mt-1 text-xs text-muted-foreground">{t('Human review required')}</div>
                                                    )}
                                                </div>
                                            ))
                                        )}
                                    </div>
                                </div>
                            </div>
                        </section>

                        <section className="rounded-md border p-3">
                            <div className="mb-3 flex items-center justify-between gap-2">
                                <div className="flex items-center gap-2 text-sm font-medium">
                                    <Clock className="size-4 text-muted-foreground" />
                                    {t('Activity')}
                                </div>
                                <Badge variant="outline" className="font-normal">
                                    {(selectedIssue.activityEvents ?? []).length}
                                </Badge>
                            </div>
                            <div className="space-y-2">
                                {(selectedIssue.activityEvents ?? []).length === 0 ? (
                                    <div className="text-sm text-muted-foreground">-</div>
                                ) : (
                                    (selectedIssue.activityEvents ?? []).slice(0, 3).map(event => (
                                        <ActivityEventCard key={activityEventKey(event)} event={event} compact t={t} />
                                    ))
                                )}
                            </div>
                        </section>

                        <section className="rounded-md border p-3">
                            <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                                <Star className="size-4 text-muted-foreground" />
                                {t('Customer satisfaction')}
                            </div>
                            {(selectedIssue.csatFeedback ?? []).length === 0 ? (
                                <div className="text-sm text-muted-foreground">-</div>
                            ) : (
                                <div className="space-y-2">
                                    {(selectedIssue.csatFeedback ?? []).slice(0, 2).map(feedback => (
                                        <div
                                            key={feedback.id}
                                            className="rounded-md border bg-muted/20 p-2 text-sm"
                                            data-ticket-csat-feedback
                                        >
                                            <div className="flex items-center justify-between gap-2">
                                                <Badge variant={feedback.rating <= 2 ? 'destructive' : 'secondary'} className="font-normal">
                                                    {feedback.rating}/5
                                                </Badge>
                                                <span className="text-xs text-muted-foreground">{formatTime(feedback.receivedAt)}</span>
                                            </div>
                                            {feedback.comment && (
                                                <div className="mt-2 whitespace-pre-wrap text-sm">{feedback.comment}</div>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </section>

                        <InboxAgentPanel
                            variant="compact"
                            issue={selectedIssue}
                            quickActions={agentQuickActions}
                            questionRef={agentQuestionRef}
                            question={agentQuestion}
                            onQuestionChange={setAgentQuestion}
                            asking={askingAgent}
                            runningActionKey={runningAgentActionKey}
                            answer={agentAnswer}
                            runs={agentChatRuns}
                            messages={agentMessages}
                            creatingKnowledgeArticle={creatingKnowledgeArticle}
                            t={t}
                            onAsk={askAgent}
                            onCreateKnowledgeArticle={source => void createKnowledgeArticleFromTicket(undefined, source)}
                            onApplyAnswerToReply={applyAgentAnswerToReply}
                            onApplyRunToReply={applyAgentRunToReply}
                            onStartFollowUp={startAgentFollowUp}
                            renderKnowledgeGap={renderKnowledgeGapCallout}
                        />

                        <InboxMessageTimeline
                            variant="compact"
                            messages={selectedMessages}
                            splittingMessageId={splittingMessageId}
                            t={t}
                            onSplitMessage={openSplitMessageDialog}
                        />

                        <section className="rounded-md border p-3">
                            <div className="mb-3 flex items-center justify-between gap-2">
                                <div className="flex items-center gap-2 text-sm font-medium">
                                    <BookOpen className="size-4" />
                                    {t('Knowledge')}
                                </div>
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    onClick={() => void createKnowledgeArticleFromTicket()}
                                    disabled={Boolean(creatingKnowledgeArticle)}
                                >
                                    {creatingKnowledgeArticle === selectedIssue.id
                                        ? <Loader className="size-3.5 animate-spin" />
                                        : <BookOpen className="size-3.5" />}
                                    {t('New')}
                                </Button>
                            </div>
                            <div className="mb-3">
                                <Input
                                    value={knowledgeQuery}
                                    onChange={event => setKnowledgeQuery(event.target.value)}
                                    placeholder={t('Search knowledge')}
                                    className="h-9"
                                />
                            </div>
                            <div className="space-y-2">
                                {knowledgeQuery.trim()
                                    ? searchedKnowledgeArticles.map(article => renderKnowledgeArticleCard(article))
                                    : (selectedIssue.knowledgeSuggestions ?? []).map(article => renderKnowledgeArticleCard(article))}
                                {knowledgeQuery.trim() && searchedKnowledgeArticles.length === 0 && (
                                    <div className="text-sm text-muted-foreground">-</div>
                                )}
                                {!knowledgeQuery.trim() && (selectedIssue.knowledgeSuggestions ?? []).length === 0 && (
                                    <div className="text-sm text-muted-foreground">-</div>
                                )}
                            </div>
                        </section>

                        <section className="rounded-md border p-3">
                            <div className="mb-3 flex items-center justify-between gap-2">
                                <div className="text-sm font-medium">{t('Reply')}</div>
                                <Badge variant="outline" className="font-normal">
                                    {(selectedIssue.outboundMessages ?? []).length} {t('outbound')}
                                </Badge>
                            </div>
                            <div className="space-y-3">
                                <Textarea
                                    value={replyDraft}
                                    data-ticket-reply-draft
                                    onChange={event => setReplyDraft(event.target.value)}
                                    rows={6}
                                    placeholder={t('Reply')}
                                />
                                {replyRoutePanel}
                                {replyMacroControls}
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                    <div className="flex flex-wrap items-center gap-2">
                                        <label className="flex items-center gap-2 rounded-md border bg-muted/20 px-3 py-2 text-sm">
                                            <Switch checked={replyRequiresApproval} onCheckedChange={setReplyRequiresApproval} />
                                            <span>{t('Require approval')}</span>
                                        </label>
                                        <label className="flex items-center gap-2 rounded-md border bg-muted/20 px-3 py-2 text-sm">
                                            <Switch checked={replyIncludeFeedbackLink} onCheckedChange={setReplyIncludeFeedbackLink} />
                                            <span>{t('CSAT link')}</span>
                                        </label>
                                    </div>
                                    <div className="flex flex-wrap gap-2">
                                        <Button type="button" size="sm" variant="outline" onClick={() => void saveReply('draft')} disabled={Boolean(savingReplyStatus) || !replyDraft.trim()}>
                                            {savingReplyStatus === 'draft' ? <Loader className="size-3.5 animate-spin" /> : null}
                                            {t('Save draft')}
                                        </Button>
                                        <Button
                                            type="button"
                                            size="sm"
                                            onClick={() => void saveReply('queued')}
                                            disabled={Boolean(savingReplyStatus) || !replyDraft.trim() || selectedReplySendBlocked}
                                            title={selectedReplySendBlocked ? selectedReplySendBlockDetail : undefined}
                                            data-ticket-queue-reply-readiness-blocked={selectedReplySendBlocked ? 'true' : 'false'}
                                        >
                                            {savingReplyStatus === 'queued' ? <Loader className="size-3.5 animate-spin" /> : <Send className="size-3.5" />}
                                            {t('Queue reply')}
                                        </Button>
                                        <Button
                                            type="button"
                                            size="sm"
                                            onClick={() => void sendReplyDraftNow()}
                                            disabled={Boolean(savingReplyStatus) || !replyDraft.trim() || selectedReplySendNowBlocked}
                                            title={selectedReplySendNowBlocked ? selectedReplySendNowBlockDetail : undefined}
                                            data-ticket-send-reply-now
                                            data-ticket-send-reply-readiness-blocked={selectedReplySendBlocked ? 'true' : 'false'}
                                            data-ticket-send-reply-approval-blocked={replyRequiresApproval ? 'true' : 'false'}
                                        >
                                            {savingReplyStatus === 'send-now' ? <Loader className="size-3.5 animate-spin" /> : <Send className="size-3.5" />}
                                            {t('Send now')}
                                        </Button>
                                    </div>
                                </div>
                            </div>
                        </section>

                        {(selectedIssue.outboundMessages ?? []).length > 0 && (
                            <section className="rounded-md border p-3">
                                <div className="mb-3 text-sm font-medium">{t('Outbound replies')}</div>
                                <div className="space-y-2">
                                    {(selectedIssue.outboundMessages ?? []).map(reply => {
                                        const needsApproval = replyNeedsApproval(reply);
                                        const changesRequested = replyChangesRequested(reply);
                                        const changeNote = replyChangesNote(reply);
                                        const automationContext = replyAutomationContext(reply);
                                        const automationLabel = automationContext ? automationContextLabel(automationContext) : '';
                                        const autoSendState = replyAutoSendState(reply);
                                        const deliveryProofChips = replyDeliveryProofChips(reply);
                                        return (
                                            <div
                                                key={reply.id}
                                                data-outbound-reply={reply.id}
                                                data-outbound-reply-status={reply.status}
                                                className="rounded-md border bg-muted/20 p-2"
                                            >
                                                <div className="mb-2 flex items-center justify-between gap-2">
                                                    <div className="min-w-0 truncate text-sm font-medium">{reply.subject}</div>
                                                    <div className="flex shrink-0 items-center gap-1.5">
                                                        {automationContext && (
                                                            <Badge variant="outline" className="gap-1 font-normal" title={automationLabel || t('Autopilot')}>
                                                                <Sparkles className="size-3" />
                                                                {t('Autopilot')}
                                                            </Badge>
                                                        )}
                                                        {autoSendState && (
                                                            <Badge variant={autoSendState.variant} className="font-normal" title={autoSendState.detail || autoSendState.label}>
                                                                {t(autoSendState.label)}
                                                            </Badge>
                                                        )}
                                                        {needsApproval && <Badge variant="secondary" className="font-normal">{t('Approval required')}</Badge>}
                                                        {changesRequested && <Badge variant="outline" className="font-normal">{t('Changes requested')}</Badge>}
                                                        <Badge variant={replyFailedDelivery(reply) ? 'destructive' : 'outline'} className="font-normal">{t(replyStatusLabel(reply))}</Badge>
                                                    </div>
                                                </div>
                                                {(automationLabel || autoSendState?.detail || deliveryProofChips.length > 0) && (
                                                    <div className="mb-2 flex flex-wrap gap-1.5 text-xs text-muted-foreground">
                                                        {automationLabel && <span>{automationLabel}</span>}
                                                        {autoSendState?.detail && <span>{t(autoSendState.detail)}</span>}
                                                        {deliveryProofChips.slice(0, 5).map((chip, index) => (
                                                            <Badge key={`${reply.id}:proof:${index}:${chip.label}`} variant={chip.variant ?? 'outline'} className="max-w-full truncate font-normal" title={chip.detail || chip.label}>
                                                                {chip.detail ? `${t(chip.label)}: ${chip.detail}` : t(chip.label)}
                                                            </Badge>
                                                        ))}
                                                    </div>
                                                )}
                                                <pre className="max-h-32 overflow-auto whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
                                                    {reply.body}
                                                </pre>
                                                {reply.error && (
                                                    <div className="mt-2 rounded-md border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive">
                                                        {reply.error}
                                                    </div>
                                                )}
                                                <InboxAttachments attachments={replyAttachmentItems(reply)} t={t} />
                                                {changesRequested && changeNote && (
                                                    <div className="mt-2 rounded-md border bg-background p-2 text-xs text-muted-foreground">
                                                        <div className="mb-1 font-medium text-foreground">{t('Requested changes')}</div>
                                                        <div className="whitespace-pre-wrap">{changeNote}</div>
                                                    </div>
                                                )}
                                                {changesRequested && (
                                                    <div className="mt-2 flex justify-end">
                                                        <Button
                                                                type="button"
                                                                size="sm"
                                                                variant="outline"
                                                                data-outbound-reply-revise={reply.id}
                                                                onClick={() => void reviseReplyWithAgent(reply)}
                                                                disabled={Boolean(approvingReplyId || sendingReplyId || savingReplyEditId || requestingChangesReplyId || revisingReplyId || askingAgent)}
                                                            >
                                                            {revisingReplyId === reply.id
                                                                ? <Loader className="size-3.5 animate-spin" />
                                                                : <Sparkles className="size-3.5" />}
                                                            {t('Revise draft')}
                                                        </Button>
                                                    </div>
                                                )}
                                                {reply.status !== 'sent' && !changesRequested && !replyDeliveryLocked(reply) && (
                                                    <div className="mt-2 flex justify-end gap-2">
                                                        {needsApproval && (
                                                            <Button
                                                                type="button"
                                                                size="sm"
                                                                variant="outline"
                                                                onClick={() => void approveReply(reply)}
                                                                disabled={Boolean(approvingReplyId || sendingReplyId || savingReplyEditId || requestingChangesReplyId || revisingReplyId)}
                                                            >
                                                                {approvingReplyId === reply.id ? <Loader className="size-3.5 animate-spin" /> : <CheckCircle2 className="size-3.5" />}
                                                                {t('Approve')}
                                                            </Button>
                                                        )}
                                                        <Button
                                                            type="button"
                                                            size="sm"
                                                            data-outbound-reply-action={reply.status === 'failed' ? 'retry' : needsApproval ? 'approve-send' : 'send'}
                                                            data-outbound-reply-id={reply.id}
                                                            data-outbound-reply-readiness-blocked={selectedReplySendBlocked ? 'true' : 'false'}
                                                            onClick={() => void sendReply(reply, needsApproval)}
                                                            disabled={Boolean(approvingReplyId || sendingReplyId || savingReplyEditId || requestingChangesReplyId || revisingReplyId || selectedReplySendBlocked)}
                                                            title={selectedReplySendBlocked ? selectedReplySendBlockDetail : undefined}
                                                        >
                                                            {sendingReplyId === reply.id
                                                                ? <Loader className="size-3.5 animate-spin" />
                                                                : reply.status === 'failed' ? <RefreshCw className="size-3.5" /> : <Send className="size-3.5" />}
                                                            {reply.status === 'failed'
                                                                ? t('Retry')
                                                                : needsApproval ? t('Approve & send') : t('Send')}
                                                        </Button>
                                                    </div>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            </section>
                        )}
                    </div>
                </>
            )}
        </DrawerContent>
        </Drawer>
    );

    const refreshControls = (
        <div className="flex shrink-0 items-center gap-1.5">
            <Badge
                variant={refreshError ? 'destructive' : 'outline'}
                className="h-7 gap-1 font-normal"
                title={refreshError || undefined}
            >
                <Clock className="size-3" />
                {refreshError
                    ? t('Refresh failed')
                    : lastRefreshedAt ? `${t('Updated')} ${formatTime(lastRefreshedAt)}` : t('Live')}
            </Badge>
            <Button
                type="button"
                size="icon"
                variant="outline"
                className="size-8"
                onClick={() => void refreshInboxNow()}
                disabled={refreshingInbox}
                aria-label={t('Refresh inbox')}
                title={t('Refresh inbox')}
            >
                {refreshingInbox
                    ? <Loader className="size-4 animate-spin" />
                    : <RefreshCw className="size-4" />}
            </Button>
        </div>
    );

    if (viewMode === 'board') {
        return (
            <>
                {newTicketDialog}
                {saveViewDialog}
                {saveMacroDialog}
                {closeWithoutReplyDialog}
                {mergeDialog}
                {splitMessageDialog}
                {bulkRejectActionsDialog}
                {bulkRequestReplyChangesDialog}
                <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-md border bg-background">
                <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
                    <div className="min-w-0">
                        <h2 className="text-base font-semibold">{t('Inbox')}</h2>
                        <p className="text-xs text-muted-foreground">{filteredIssues.length} {t('tickets')}</p>
                    </div>
                    <div className="flex min-w-0 flex-1 flex-wrap items-center justify-end gap-2">
                        <div className="relative min-w-48 flex-1 sm:max-w-xs">
                            <Search className="pointer-events-none absolute left-2 top-2.5 size-3.5 text-muted-foreground" />
                            <Input
                                value={query}
                                onChange={event => changeInboxFilters({ query: event.target.value })}
                                placeholder={t('Search')}
                                className="h-9 pl-7"
                            />
                        </div>
                        {statusFilterSelect}
                        {queueFilterSelect}
                        {accountFilterSelect}
                        {channelFilterSelect}
                        {assigneeFilterSelect}
                        {tagFilterSelect}
                        {refreshControls}
                        <Button type="button" size="sm" variant="outline" data-inbox-save-view-open onClick={openSaveViewDialog}>
                            <Save className="size-4" />
                            {t('Save view')}
                        </Button>
                        <Button type="button" size="sm" variant="outline" onClick={() => changeInboxFilters({ viewMode: 'list' })}>
                            <List className="size-4" />
                            {t('List')}
                        </Button>
                        <Button type="button" size="sm" variant="outline" data-new-ticket-open onClick={openNewTicket}>
                            <Plus className="size-4" />
                            {t('New')}
                        </Button>
                        <Button type="button" size="sm">
                            <Columns3 className="size-4" />
                            {t('Board')}
                        </Button>
                    </div>
                </div>
                <div className="space-y-2 border-b px-4 py-3">
                    {supportViewsPanel}
                    {savedViewsPanel}
                    {channelCoveragePanel}
                    {ticketCreationPanel}
                    {replyRouteProofPanel}
                    {ticketWorkflowPanel}
                    {accountActionPanel}
                    {automationProofPanel}
                    {knowledgeAssistPanel}
                    {notificationsPanel}
                    {approvalWorkbenchPanel}
                    {bulkActionsPanel}
                </div>
                <div
                    className="border-b px-4 py-2 text-xs"
                    data-kanban-workflow-policy
                    data-kanban-workflow-policy-kind={boardWorkflowPolicy?.kind ?? 'local'}
                    data-kanban-workflow-lanes={boardWorkflowLanePolicies.length || kanbanLanes.length}
                    data-kanban-workflow-assignee-required={boardWorkflowAssigneeStatuses.join(',')}
                    data-kanban-workflow-done-gate={boardWorkflowPolicy?.doneRequiresNoBlockers ? 'true' : 'false'}
                    data-kanban-workflow-done-blockers={boardWorkflowDoneBlockers.join(',')}
                    data-kanban-workflow-drag-drop={boardWorkflowPolicy?.dragDropEnabled === false ? 'false' : 'true'}
                    data-kanban-workflow-bulk-move={boardWorkflowPolicy?.bulkMoveEnabled === false ? 'false' : 'true'}
                >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex min-w-0 items-center gap-2">
                            <Columns3 className="size-3.5 text-muted-foreground" />
                            <span className="font-medium">{t('Workflow policy')}</span>
                            <span className="truncate text-muted-foreground">
                                {boardWorkflowLanePolicies.length || kanbanLanes.length} {t('lanes')}
                            </span>
                        </div>
                        <div className="flex flex-wrap justify-end gap-1.5">
                            <Badge variant="outline" className="font-normal">
                                {t('Assignee')}: {boardWorkflowAssigneeStatuses.map(status => t(workflowLabel(status))).join(' / ')}
                            </Badge>
                            <Badge variant={boardWorkflowPolicy?.doneRequiresNoBlockers ? 'secondary' : 'outline'} className="font-normal">
                                {t('Done gated')}
                            </Badge>
                            <Badge variant="outline" className="font-normal">
                                {boardWorkflowDoneBlockers.length} {t('close blockers')}
                            </Badge>
                            <Badge variant={boardWorkflowPolicy?.dragDropEnabled === false ? 'outline' : 'secondary'} className="font-normal">
                                {t('Drag/drop')}
                            </Badge>
                            <Badge variant={boardWorkflowPolicy?.bulkMoveEnabled === false ? 'outline' : 'secondary'} className="font-normal">
                                {t('Bulk move')}
                            </Badge>
                        </div>
                    </div>
                </div>

                {boardNextAction && (
                    <div
                        className="border-b bg-muted/20 px-4 py-2 text-xs"
                        data-kanban-board-operating-action
                        data-kanban-board-operating-action-kind={boardNextAction.kind}
                        data-kanban-board-operating-action-phase={boardNextAction.phase}
                        data-kanban-board-operating-action-status-filter={boardNextAction.statusFilter}
                        data-kanban-board-operating-action-count={boardNextAction.count}
                        data-kanban-board-operating-action-issues={boardNextAction.issueCount}
                        data-kanban-board-operating-action-attention={boardNextAction.attentionCount}
                        data-kanban-board-operating-action-blocked={boardNextAction.blocked ? 'true' : 'false'}
                    >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex min-w-0 items-center gap-2">
                                <Badge variant={boardNextAction.blocked ? 'destructive' : 'secondary'} className="font-normal">
                                    {t(boardNextAction.label)}
                                </Badge>
                                <span className="min-w-0 truncate text-muted-foreground">
                                    {t(boardNextAction.detail)}
                                </span>
                            </div>
                            <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                className="h-7 px-2 text-xs"
                                data-kanban-board-operating-action-open
                                onClick={() => openBoardOperatingAction(boardNextAction)}
                            >
                                <ExternalLink className="size-3" />
                                {t(boardNextAction.blocked ? 'Open queue' : 'Show board')}
                            </Button>
                        </div>
                    </div>
                )}

                <div
                    className="flex min-h-0 flex-1 overflow-hidden"
                    data-kanban-board-api-total={issueBoard?.total ?? ''}
                    data-kanban-board-api-attention={issueBoard?.attention.attentionCount ?? ''}
                >
                <div className="grid min-h-0 flex-1 gap-3 overflow-x-auto p-4 lg:grid-cols-3">
                    {kanbanLanes.map(lane => {
                        const laneIssues = boardGroups[lane.value];
                        const laneHealth = boardLaneHealth[lane.value];
                        const apiLane = issueBoardLaneByStatus.get(lane.value);
                        const lanePolicy = apiLane?.policy;
                        const laneAction = apiLane?.operatingAction ?? null;
                        const laneHealthItems = laneHealthBadges(laneHealth);
                        const selectedInLane = laneIssues.filter(issue => selectedIssueIdSet.has(issue.id)).length;
                        const laneFullySelected = laneIssues.length > 0 && selectedInLane === laneIssues.length;
                        return (
                            <section
                                key={lane.value}
                                data-kanban-lane={lane.value}
                                data-kanban-lane-api-count={apiLane?.count ?? ''}
                                data-kanban-lane-api-attention={apiLane?.attention.attentionCount ?? ''}
                                data-kanban-lane-policy-requires-assignee={lanePolicy?.requiresAssignee ? 'true' : 'false'}
                                data-kanban-lane-policy-done-gate={lanePolicy?.doneGate ? 'true' : 'false'}
                                data-kanban-lane-policy-transitions={(lanePolicy?.allowedTransitions ?? []).join(',')}
                                className={[
                                    'flex min-h-[24rem] min-w-[18rem] flex-col overflow-hidden rounded-md border bg-muted/20 transition-colors',
                                    dragOverLane === lane.value ? 'border-primary bg-primary/5' : '',
                                ].join(' ')}
                                onDragOver={(event) => {
                                    event.preventDefault();
                                    event.dataTransfer.dropEffect = 'move';
                                    setDragOverLane(lane.value);
                                }}
                                onDragLeave={() => setDragOverLane(prev => prev === lane.value ? '' : prev)}
                                onDrop={(event) => {
                                    event.preventDefault();
                                    setDragOverLane('');
                                    const droppedIssueId = event.dataTransfer.getData('text/plain');
                                    if (droppedIssueId) void moveIssueGroupToLane(droppedIssueId, lane.value);
                                }}
                            >
                                <div className="flex shrink-0 items-center justify-between gap-2 border-b bg-background px-3 py-2">
                                    <label className="flex min-w-0 items-center gap-2">
                                        <Checkbox
                                            checked={laneFullySelected}
                                            disabled={laneIssues.length === 0}
                                            aria-label={`${t(laneFullySelected ? 'Clear lane selection' : 'Select lane')} ${t(lane.label)}`}
                                            onClick={event => event.stopPropagation()}
                                            onCheckedChange={checked => toggleLaneSelection(lane.value, checked === true)}
                                        />
                                        {statusIcon(lane.value)}
                                        <h3 className="truncate text-sm font-medium">{t(lane.label)}</h3>
                                    </label>
                                    <div className="flex shrink-0 items-center gap-1.5">
                                        {selectedInLane > 0 && (
                                            <Badge variant="secondary" className="font-normal">
                                                {selectedInLane} {t('selected')}
                                            </Badge>
                                        )}
                                        <Badge variant="outline" className="font-normal">
                                            {laneIssues.length}
                                        </Badge>
                                    </div>
                                </div>
                                {laneAction && (
                                    <div
                                        className="border-b bg-background px-3 py-2 text-xs"
                                        data-kanban-lane-operating-action={lane.value}
                                        data-kanban-lane-operating-action-kind={laneAction.kind}
                                        data-kanban-lane-operating-action-phase={laneAction.phase}
                                        data-kanban-lane-operating-action-status-filter={laneAction.statusFilter}
                                        data-kanban-lane-operating-action-count={laneAction.count}
                                        data-kanban-lane-operating-action-issues={laneAction.issueCount}
                                        data-kanban-lane-operating-action-attention={laneAction.attentionCount}
                                        data-kanban-lane-operating-action-blocked={laneAction.blocked ? 'true' : 'false'}
                                    >
                                        <div className="flex min-w-0 items-start justify-between gap-2">
                                            <div className="min-w-0 space-y-1">
                                                <Badge variant={laneAction.blocked ? 'destructive' : 'outline'} className="font-normal">
                                                    {t(laneAction.label)}
                                                </Badge>
                                                <div className="line-clamp-2 text-muted-foreground">
                                                    {t(laneAction.detail)}
                                                </div>
                                            </div>
                                            <Button
                                                type="button"
                                                size="icon-xs"
                                                variant="ghost"
                                                className="shrink-0"
                                                data-kanban-lane-operating-action-open={lane.value}
                                                onClick={() => openBoardOperatingAction(laneAction)}
                                                aria-label={t('Open queue')}
                                                title={t('Open queue')}
                                            >
                                                <ExternalLink className="size-3" />
                                            </Button>
                                        </div>
                                    </div>
                                )}
                                {laneHealthItems.length > 0 && (
                                    <div
                                        data-kanban-lane-health={lane.value}
                                        className="border-b bg-background px-3 py-2"
                                    >
                                        <div className="flex flex-wrap gap-1.5">
                                            {laneHealthItems.map(item => (
                                                <Badge
                                                    key={item.key}
                                                    variant={item.variant}
                                                    className="font-normal"
                                                    title={t(item.title)}
                                                >
                                                    {item.count} {t(item.label)}
                                                </Badge>
                                            ))}
                                        </div>
                                    </div>
                                )}
                                {lane.value !== 'open' && canAutoClaim && (
                                    <div className="border-b bg-background px-3 py-1 text-xs text-muted-foreground">
                                        {t('Drop unassigned tickets here to claim them.')}
                                    </div>
                                )}
                                <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-2">
                                    {laneIssues.length === 0 ? (
                                        <div className="flex h-24 items-center justify-center rounded-md border border-dashed bg-background text-sm text-muted-foreground">
                                            -
                                        </div>
                                    ) : (
                                        laneIssues.map(issue => {
                                            const selectedGroup = selectedIssueIdSet.has(issue.id)
                                                ? selectedIssues
                                                : [issue];
                                            const blockedGroupCount = selectedGroup.filter(item => issueDoneBlockers(item).length > 0).length;
                                            const doneBlockers = selectedGroup.length > 1 && blockedGroupCount > 0
                                                ? [`${blockedGroupCount} selected blocked`]
                                                : issueDoneBlockers(issue);
                                            return (
                                                <IssueBoardCard
                                                    key={issue.id}
                                                    issue={issue}
                                                    active={issue.id === issueId}
                                                    selected={selectedIssueIdSet.has(issue.id)}
                                                    selectedGroupCount={selectedGroup.length}
                                                    moving={movingIssueId === issue.id || (bulkUpdating && selectedGroup.length > 1)}
                                                    canClaim={canAutoClaim}
                                                    claiming={claimingIssueId === issue.id}
                                                    doneBlockers={doneBlockers}
                                                    onOpen={() => {
                                                        navigateToIssue(issue.id, { viewMode: 'board' });
                                                    }}
                                                    onSelectionChange={checked => toggleIssueSelection(issue.id, checked)}
                                                    onClaim={() => void claimIssue(issue)}
                                                    onMove={(status) => void moveIssueGroupToLane(issue.id, status)}
                                                    onDragStart={(event) => {
                                                        event.dataTransfer.effectAllowed = 'move';
                                                        event.dataTransfer.setData('text/plain', issue.id);
                                                    }}
                                                    onDragEnd={() => {
                                                        setMovingIssueId('');
                                                        setDragOverLane('');
                                                    }}
                                                />
                                            );
                                        })
                                    )}
                                </div>
                            </section>
                        );
                    })}
                </div>
                {boardDetailPanel}
                </div>

                {loadingList && (
                    <div className="border-t px-4 py-2 text-xs text-muted-foreground">
                        <Loader className="mr-2 inline size-3.5 animate-spin" />
                        {t('Loading')}
                    </div>
                )}
                </div>
            </>
        );
    }

    return (
        <>
            {newTicketDialog}
            {saveViewDialog}
            {saveMacroDialog}
            {closeWithoutReplyDialog}
            {mergeDialog}
            {splitMessageDialog}
            {bulkRejectActionsDialog}
            {bulkRequestReplyChangesDialog}
            <div className="flex min-h-0 flex-1 overflow-hidden rounded-md border bg-background">
            <aside className="flex min-w-0 flex-1 flex-col">
                <div className="space-y-3 border-b p-4">
                    <div className="flex items-center justify-between gap-3">
                        <div>
                            <h2 className="text-base font-semibold">{t('Inbox')}</h2>
                            <p className="text-xs text-muted-foreground">{filteredIssues.length} {t('tickets')}</p>
                        </div>
                        <div className="flex items-center gap-2">
                            {loadingList && <Loader className="size-4 animate-spin text-muted-foreground" />}
                            {refreshControls}
                            <Button type="button" size="sm" variant="outline" data-inbox-save-view-open onClick={openSaveViewDialog}>
                                <Save className="size-4" />
                                {t('Save view')}
                            </Button>
                            <Button type="button" size="sm" variant="outline" data-new-ticket-open onClick={openNewTicket}>
                                <Plus className="size-4" />
                                {t('New')}
                            </Button>
                            <Button type="button" size="sm" variant="outline" onClick={() => changeInboxFilters({ viewMode: 'board' })}>
                                <Columns3 className="size-4" />
                                {t('Board')}
                            </Button>
                        </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        <div className="relative min-w-40 flex-1">
                            <Search className="pointer-events-none absolute left-2 top-2.5 size-3.5 text-muted-foreground" />
                            <Input
                                value={query}
                                onChange={event => changeInboxFilters({ query: event.target.value })}
                                placeholder={t('Search')}
                                className="h-9 pl-7"
                            />
                        </div>
                        {statusFilterSelect}
                        {queueFilterSelect}
                        {accountFilterSelect}
                        {channelFilterSelect}
                        {assigneeFilterSelect}
                        {tagFilterSelect}
                    </div>
                    {supportViewsPanel}
                    {savedViewsPanel}
                    {channelCoveragePanel}
                    {ticketCreationPanel}
                    {replyRouteProofPanel}
                    {ticketWorkflowPanel}
                    {accountActionPanel}
                    {automationProofPanel}
                    {knowledgeAssistPanel}
                    {approvalWorkbenchPanel}
                    {bulkActionsPanel}
                    <div className="rounded-md border bg-muted/20 p-2">
                        <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
                            <Columns3 className="size-3.5" />
                            {t('Kanban')}
                        </div>
                        <div className="grid grid-cols-3 gap-2">
                            {kanbanLanes.map(lane => {
                                const laneHealthItems = laneHealthBadges(boardLaneHealth[lane.value]).slice(0, 3);
                                return (
                                    <div
                                        key={lane.value}
                                        className={[
                                            'min-w-0 rounded-md border bg-background transition-colors',
                                            dragOverLane === lane.value ? 'border-primary bg-primary/5' : '',
                                        ].join(' ')}
                                        onDragOver={(event) => {
                                            event.preventDefault();
                                            event.dataTransfer.dropEffect = 'move';
                                            setDragOverLane(lane.value);
                                        }}
                                        onDragLeave={() => setDragOverLane(prev => prev === lane.value ? '' : prev)}
                                        onDrop={(event) => {
                                            event.preventDefault();
                                            setDragOverLane('');
                                            const droppedIssueId = event.dataTransfer.getData('text/plain');
                                            if (droppedIssueId) void moveIssueGroupToLane(droppedIssueId, lane.value);
                                        }}
                                    >
                                        <button
                                            type="button"
                                            className={[
                                                'flex w-full items-center justify-between gap-2 border-b px-2 py-1.5 text-left text-xs font-medium',
                                                statusFilter === lane.value ? 'bg-muted' : '',
                                            ].join(' ')}
                                            onClick={() => changeStatusFilter(statusFilter === lane.value ? 'all' : lane.value)}
                                        >
                                            <span>{t(lane.label)}</span>
                                            <Badge variant="outline" className="h-5 px-1.5 text-[10px] font-normal">
                                                {boardGroups[lane.value].length}
                                            </Badge>
                                        </button>
                                        {laneHealthItems.length > 0 && (
                                            <div className="flex flex-wrap gap-1 border-b bg-muted/20 px-1.5 py-1">
                                                {laneHealthItems.map(item => (
                                                    <Badge
                                                        key={item.key}
                                                        variant={item.variant}
                                                        className="max-w-full truncate px-1.5 text-[10px] font-normal"
                                                        title={t(item.title)}
                                                    >
                                                        {item.count} {t(item.label)}
                                                    </Badge>
                                                ))}
                                            </div>
                                        )}
                                        <div className="max-h-36 space-y-1 overflow-y-auto p-1.5">
                                            {boardGroups[lane.value].slice(0, 4).map(issue => (
                                            <button
                                                key={issue.id}
                                                type="button"
                                                data-kanban-card={issue.id}
                                                data-kanban-card-status={issueWorkflowStatus(issue)}
                                                data-kanban-card-subject={issue.subject || ''}
                                                draggable
                                                className={[
                                                    'w-full cursor-grab truncate rounded border px-2 py-1 text-left text-[11px] active:cursor-grabbing disabled:cursor-wait disabled:opacity-60',
                                                    issue.id === issueId ? 'border-primary bg-primary/5' : 'bg-muted/20 hover:bg-muted',
                                                ].join(' ')}
                                                disabled={movingIssueId === issue.id}
                                                onDragStart={(event) => {
                                                    event.dataTransfer.effectAllowed = 'move';
                                                    event.dataTransfer.setData('text/plain', issue.id);
                                                }}
                                                onDragEnd={() => {
                                                    setMovingIssueId('');
                                                    setDragOverLane('');
                                                }}
                                                onClick={() => navigateToIssue(issue.id)}
                                                title={issue.subject}
                                            >
                                                {issue.subject || '(No subject)'}
                                            </button>
                                        ))}
                                        {boardGroups[lane.value].length === 0 && (
                                            <div className="px-2 py-3 text-center text-[11px] text-muted-foreground">-</div>
                                        )}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                    {notificationsPanel}
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto">
                    {filteredIssues.length === 0 ? (
                        <EmptyState label={loadingList ? t('Loading') : t('No tickets')} />
                    ) : (
                        filteredIssues.map(issue => (
                            <IssueListItem
                                key={issue.id}
                                issue={issue}
                                active={issue.id === issueId}
                                canClaim={canAutoClaim}
                                claiming={claimingIssueId === issue.id}
                                selected={selectedIssueIdSet.has(issue.id)}
                                onSelect={() => navigateToIssue(issue.id)}
                                onSelectionChange={checked => toggleIssueSelection(issue.id, checked)}
                                onClaim={() => void claimIssue(issue)}
                            />
                        ))
                    )}
                </div>
            </aside>

            <Drawer
                open={Boolean(issueId)}
                onOpenChange={(open) => {
                    if (!open) closeIssueDrawer();
                }}
            >
            <DrawerContent
                data-ticket-drawer
                className="gap-0 overflow-hidden p-0 md:w-[min(72rem,calc(100vw-2rem))]"
            >
            <DrawerTitle className="sr-only">
                {selectedIssue?.subject || t('Ticket workspace')}
            </DrawerTitle>
            <DrawerDescription className="sr-only">{t('Ticket workspace')}</DrawerDescription>
            <section className="min-h-0 flex-1 overflow-y-auto">
                {loadingDetail ? (
                    <div className="flex h-full items-center justify-center text-muted-foreground">
                        <Loader className="mr-2 size-4 animate-spin" />
                        {t('Loading')}
                    </div>
                ) : !selectedIssue ? (
                    <EmptyState label={t('Select a ticket')} />
                ) : (
                    <div className="mx-auto max-w-5xl px-6 py-5">
                        <div className="mb-5 flex min-w-0 items-start justify-between gap-4">
                            <div className="min-w-0">
                                <div className="mb-2 flex flex-wrap items-center gap-2">
                                    <Badge variant="outline" className="gap-1 font-normal">
                                        {statusIcon(selectedIssue.status)}
                                        {workflowLabel(selectedIssue.status)}
                                    </Badge>
                                    <Badge variant={priorityVariant(selectedIssue.priority)} className="font-normal">
                                        {selectedIssue.priority}
                                    </Badge>
                                    <Badge variant="secondary" className="font-normal">{issueQueueLabel(selectedIssue)}</Badge>
                                    <Badge variant="secondary" className="font-normal">{selectedIssue.channel}</Badge>
                                    {(selectedIssue.tags ?? []).map(tag => (
                                        <Badge key={tag} variant="outline" className="font-normal">
                                            {tag}
                                        </Badge>
                                    ))}
                                    {issueHasOverdueSla(selectedIssue) && (
                                        <Badge variant="destructive" className="font-normal">
                                            {t('Overdue SLA')}
                                        </Badge>
                                    )}
                                    {issueHasLowCsat(selectedIssue) && (
                                        <Badge variant="destructive" className="font-normal" title={selectedIssue.latestCsatComment || undefined}>
                                            {t(lowCsatLabel(selectedIssue))}
                                        </Badge>
                                    )}
                                </div>
                                <h1 className="truncate text-xl font-semibold">{selectedIssue.subject || '(No subject)'}</h1>
                                <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted-foreground">
                                    <span>{selectedIssue.accountName || selectedIssue.accountDomain || selectedIssue.contactEmail || '-'}</span>
                                    <span>{selectedIssue.fromAddress}</span>
                                    <span>{formatTime(selectedIssue.latestMessageAt)}</span>
                                </div>
                            </div>
                            <div className="flex shrink-0 items-center gap-2">
                                {selectedIssue.accountId && tenantId && (
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => navigate(`/${tenantId}/${projectId}/accounts/${selectedIssue.accountId}`)}
                                    >
                                        <ExternalLink className="size-4" />
                                        {t('Account')}
                                    </Button>
                                )}
                                <Button variant="outline" size="sm" asChild>
                                    <a href={`mailto:${selectedIssue.contactEmail || selectedIssue.fromAddress}`}>
                                        <ExternalLink className="size-4" />
                                        {t('Email')}
                                    </a>
                                </Button>
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => void createPortalLink()}
                                    disabled={creatingPortalLink}
                                >
                                    {creatingPortalLink ? <Loader className="size-4 animate-spin" /> : <Link className="size-4" />}
                                    {t('Portal')}
                                </Button>
                            </div>
                        </div>

                        {ticketWorkspacePanel}
                        {ticketOperatingProofPanel}
                        {ticketConversationPanel}
                        {channelSourcePanel}
                        {channelWebhookEventsPanel}
                        {autopilotProofPanel}
                        {reviewPackagePanel}

                        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
                            <div className="min-w-0 space-y-5">
                                <section className="rounded-md border bg-muted/20 p-4">
                                    <div className="mb-2 text-sm font-medium">{t('AI summary')}</div>
                                    <p className="whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
                                        {selectedIssue.aiSummary || '-'}
                                    </p>
                                </section>

                                <InboxAgentPanel
                                    issue={selectedIssue}
                                    quickActions={agentQuickActions}
                                    questionRef={agentQuestionRef}
                                    question={agentQuestion}
                                    onQuestionChange={setAgentQuestion}
                                    asking={askingAgent}
                                    runningActionKey={runningAgentActionKey}
                                    answer={agentAnswer}
                                    runs={agentChatRuns}
                                    messages={agentMessages}
                                    creatingKnowledgeArticle={creatingKnowledgeArticle}
                                    t={t}
                                    onAsk={askAgent}
                                    onCreateKnowledgeArticle={source => void createKnowledgeArticleFromTicket(undefined, source)}
                                    onApplyAnswerToReply={applyAgentAnswerToReply}
                                    onApplyRunToReply={applyAgentRunToReply}
                                    onStartFollowUp={startAgentFollowUp}
                                    renderKnowledgeGap={renderKnowledgeGapCallout}
                                />

                                <InboxMessageTimeline
                                    messages={selectedMessages}
                                    splittingMessageId={splittingMessageId}
                                    t={t}
                                    onSplitMessage={openSplitMessageDialog}
                                />

                                {draftReply && (
                                    <section className="rounded-md border p-4">
                                        <div className="mb-2 text-sm font-medium">{t('Draft reply')}</div>
                                        <pre className="max-h-96 overflow-auto whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
                                            {draftReply}
                                        </pre>
                                    </section>
                                )}

                                <section className="rounded-md border p-4">
                                    <div className="mb-3 flex items-center justify-between gap-3">
                                        <div className="text-sm font-medium">{t('Reply')}</div>
                                        <Badge variant="outline" className="font-normal">
                                            {(selectedIssue.outboundMessages ?? []).length} {t('outbound')}
                                        </Badge>
                                    </div>
                                    <div className="space-y-3">
                                        <Textarea
                                            value={replyDraft}
                                            data-ticket-reply-draft
                                            onChange={event => setReplyDraft(event.target.value)}
                                            rows={8}
                                            placeholder={t('Reply')}
                                        />
                                        {replyRoutePanel}
                                        {replyMacroControls}
                                        <div className="flex flex-wrap items-center justify-between gap-3">
                                            <div className="flex flex-wrap items-center gap-2">
                                                <label className="flex items-center gap-2 rounded-md border bg-muted/20 px-3 py-2 text-sm">
                                                    <Switch
                                                        checked={replyRequiresApproval}
                                                        onCheckedChange={setReplyRequiresApproval}
                                                    />
                                                    <span>{t('Require approval')}</span>
                                                </label>
                                                <label className="flex items-center gap-2 rounded-md border bg-muted/20 px-3 py-2 text-sm">
                                                    <Switch
                                                        checked={replyIncludeFeedbackLink}
                                                        onCheckedChange={setReplyIncludeFeedbackLink}
                                                    />
                                                    <span>{t('CSAT link')}</span>
                                                </label>
                                            </div>
                                            <div className="flex flex-wrap justify-end gap-2">
                                            <Button
                                                type="button"
                                                variant="outline"
                                                onClick={() => void saveReply('draft')}
                                                disabled={Boolean(savingReplyStatus) || !replyDraft.trim()}
                                            >
                                                {savingReplyStatus === 'draft' ? <Loader className="size-4 animate-spin" /> : null}
                                                {t('Save draft')}
                                            </Button>
                                            <Button
                                                type="button"
                                                onClick={() => void saveReply('queued')}
                                                disabled={Boolean(savingReplyStatus) || !replyDraft.trim() || selectedReplySendBlocked}
                                                title={selectedReplySendBlocked ? selectedReplySendBlockDetail : undefined}
                                                data-ticket-queue-reply-readiness-blocked={selectedReplySendBlocked ? 'true' : 'false'}
                                            >
                                                {savingReplyStatus === 'queued'
                                                    ? <Loader className="size-4 animate-spin" />
                                                    : <Send className="size-4" />}
                                                {t('Queue reply')}
                                            </Button>
                                            <Button
                                                type="button"
                                                onClick={() => void sendReplyDraftNow()}
                                                disabled={Boolean(savingReplyStatus) || !replyDraft.trim() || selectedReplySendNowBlocked}
                                                title={selectedReplySendNowBlocked ? selectedReplySendNowBlockDetail : undefined}
                                                data-ticket-send-reply-now
                                                data-ticket-send-reply-readiness-blocked={selectedReplySendBlocked ? 'true' : 'false'}
                                                data-ticket-send-reply-approval-blocked={replyRequiresApproval ? 'true' : 'false'}
                                            >
                                                {savingReplyStatus === 'send-now'
                                                    ? <Loader className="size-4 animate-spin" />
                                                    : <Send className="size-4" />}
                                                {t('Send now')}
                                            </Button>
                                            </div>
                                        </div>
                                    </div>
                                </section>

                                {(selectedIssue.outboundMessages ?? []).length > 0 && (
                                    <section className="rounded-md border p-4">
                                        <div className="mb-3 text-sm font-medium">{t('Outbound replies')}</div>
                                        <div className="space-y-3">
                                            {(selectedIssue.outboundMessages ?? []).map(reply => {
                                                const needsApproval = replyNeedsApproval(reply);
                                                const changesRequested = replyChangesRequested(reply);
                                                const changeNote = replyChangesNote(reply);
                                                const isEditing = editingReplyId === reply.id;
                                                const isRequestingChanges = changeRequestReplyId === reply.id;
                                                const nextAttemptAt = replyNextAttemptAt(reply);
                                                const retryDeferred = reply.status === 'queued' && replyRetryDeferred(nextAttemptAt);
                                                const manualRetryNow = retryDeferred;
                                                const providerDetail = replyProviderDetail(reply);
                                                const generationMode = generationModeLabel(textFrom(reply.metadata.generationMode));
                                                const automationContext = replyAutomationContext(reply);
                                                const automationLabel = automationContext ? automationContextLabel(automationContext) : '';
                                                const autoSendState = replyAutoSendState(reply);
                                                const deliveryProofChips = replyDeliveryProofChips(reply);
                                                return (
                                                    <div
                                                        key={reply.id}
                                                        data-outbound-reply={reply.id}
                                                        data-outbound-reply-status={reply.status}
                                                        className="rounded-md border bg-muted/20 p-3"
                                                    >
                                                        <div className="mb-2 flex items-center justify-between gap-3">
                                                            <div className="min-w-0 truncate text-sm font-medium">{reply.subject}</div>
                                                            <div className="flex shrink-0 items-center gap-2">
                                                                {automationContext && (
                                                                    <Badge variant="outline" className="gap-1 font-normal" title={automationLabel || t('Autopilot')}>
                                                                        <Sparkles className="size-3" />
                                                                        {t('Autopilot')}
                                                                    </Badge>
                                                                )}
                                                                {autoSendState && (
                                                                    <Badge variant={autoSendState.variant} className="font-normal" title={autoSendState.detail || autoSendState.label}>
                                                                        {t(autoSendState.label)}
                                                                    </Badge>
                                                                )}
                                                                {needsApproval && (
                                                                    <Badge variant="secondary" className="font-normal">
                                                                        {t('Approval required')}
                                                                    </Badge>
                                                                )}
                                                                {changesRequested && (
                                                                    <Badge variant="outline" className="gap-1 font-normal">
                                                                        <AlertTriangle className="size-3" />
                                                                        {t('Changes requested')}
                                                                    </Badge>
                                                                )}
                                                                <Badge variant={replyFailedDelivery(reply) ? 'destructive' : 'outline'} className="font-normal">{t(replyStatusLabel(reply))}</Badge>
                                                                {reply.status !== 'sent' && !replyDeliveryLocked(reply) && (
                                                                    <>
                                                                        {!isEditing && (
                                                                            <Button
                                                                                type="button"
                                                                                size="sm"
                                                                                variant="outline"
                                                                                onClick={() => startEditingReply(reply)}
                                                                            >
                                                                                <Pencil className="size-4" />
                                                                                {t('Edit')}
                                                                            </Button>
                                                                        )}
                                                                        {changesRequested && !isEditing && (
                                                                            <Button
                                                                                    type="button"
                                                                                    size="sm"
                                                                                    variant="outline"
                                                                                    data-outbound-reply-revise={reply.id}
                                                                                    onClick={() => void reviseReplyWithAgent(reply)}
                                                                                    disabled={Boolean(approvingReplyId || sendingReplyId || savingReplyEditId || requestingChangesReplyId || revisingReplyId || askingAgent)}
                                                                                >
                                                                                {revisingReplyId === reply.id
                                                                                    ? <Loader className="size-4 animate-spin" />
                                                                                    : <Sparkles className="size-4" />}
                                                                                {t('Revise draft')}
                                                                            </Button>
                                                                        )}
                                                                        {needsApproval && !isEditing && (
                                                                            <>
                                                                                <Button
                                                                                        type="button"
                                                                                        size="sm"
                                                                                        variant="outline"
                                                                                        data-outbound-reply-request-changes={reply.id}
                                                                                        onClick={() => openChangeRequest(reply)}
                                                                                        disabled={Boolean(approvingReplyId || sendingReplyId || savingReplyEditId || requestingChangesReplyId || revisingReplyId)}
                                                                                    >
                                                                                    <AlertTriangle className="size-4" />
                                                                                    {t('Request changes')}
                                                                                </Button>
                                                                                <Button
                                                                                    type="button"
                                                                                    size="sm"
                                                                                    variant="outline"
                                                                                    onClick={() => void approveReply(reply)}
                                                                                    disabled={Boolean(approvingReplyId || sendingReplyId || savingReplyEditId || requestingChangesReplyId || revisingReplyId)}
                                                                                >
                                                                                    {approvingReplyId === reply.id
                                                                                        ? <Loader className="size-4 animate-spin" />
                                                                                        : <CheckCircle2 className="size-4" />}
                                                                                    {approvingReplyId === reply.id ? t('Approving') : t('Approve')}
                                                                                </Button>
                                                                            </>
                                                                        )}
                                                                        {!changesRequested && (
                                                                            <Button
                                                                                type="button"
                                                                                size="sm"
                                                                                variant="outline"
                                                                                data-outbound-reply-action={manualRetryNow ? 'retry-now' : reply.status === 'failed' ? 'retry' : needsApproval ? 'approve-send' : 'send'}
                                                                                data-outbound-reply-id={reply.id}
                                                                                data-outbound-reply-readiness-blocked={selectedReplySendBlocked ? 'true' : 'false'}
                                                                                onClick={() => void sendReply(reply, needsApproval, { forceRetry: manualRetryNow })}
                                                                                disabled={Boolean(approvingReplyId || sendingReplyId || savingReplyEditId || requestingChangesReplyId || revisingReplyId || isEditing || selectedReplySendBlocked)}
                                                                                title={selectedReplySendBlocked ? selectedReplySendBlockDetail : manualRetryNow && nextAttemptAt ? `${t('Next retry')} ${formatTime(nextAttemptAt)}` : undefined}
                                                                            >
                                                                                {sendingReplyId === reply.id
                                                                                    ? <Loader className="size-4 animate-spin" />
                                                                                    : manualRetryNow ? <RefreshCw className="size-4" /> : reply.status === 'failed' ? <RefreshCw className="size-4" /> : needsApproval ? <CheckCircle2 className="size-4" /> : <Send className="size-4" />}
                                                                                {manualRetryNow
                                                                                    ? t('Retry now')
                                                                                    : reply.status === 'failed'
                                                                                    ? t('Retry')
                                                                                    : needsApproval
                                                                                    ? approvingReplyId === reply.id ? t('Approving') : t('Approve & send')
                                                                                    : t('Send')}
                                                                            </Button>
                                                                        )}
                                                                    </>
                                                                )}
                                                            </div>
                                                        </div>
                                                        <div className="mb-2 text-xs text-muted-foreground">
                                                            {replyTargetDetail(reply) || reply.toAddress} · {formatTime(reply.sentAt || reply.created)}
                                                        </div>
                                                        {(automationLabel || autoSendState || generationMode || providerDetail || nextAttemptAt || deliveryProofChips.length > 0) && (
                                                            <div className="mb-2 flex flex-wrap gap-1.5 text-xs text-muted-foreground">
                                                                {automationLabel && (
                                                                    <Badge variant="outline" className="gap-1 font-normal">
                                                                        <Sparkles className="size-3" />
                                                                        {automationLabel}
                                                                    </Badge>
                                                                )}
                                                                {autoSendState?.detail && (
                                                                    <Badge variant="outline" className="font-normal">
                                                                        {t(autoSendState.detail)}
                                                                    </Badge>
                                                                )}
                                                                {generationMode && (
                                                                    <Badge variant="secondary" className="font-normal">
                                                                        {generationMode}
                                                                    </Badge>
                                                                )}
                                                                {providerDetail && (
                                                                    <Badge variant="outline" className="font-normal">
                                                                        {providerDetail}
                                                                    </Badge>
                                                                )}
                                                                {nextAttemptAt && (
                                                                    <Badge variant="outline" className="gap-1 font-normal">
                                                                        <Clock className="size-3" />
                                                                        {t('Next retry')} {formatTime(nextAttemptAt)}
                                                                    </Badge>
                                                                )}
                                                                {deliveryProofChips.map((chip, index) => (
                                                                    <Badge key={`${reply.id}:proof:${index}:${chip.label}`} variant={chip.variant ?? 'outline'} className="max-w-full truncate font-normal" title={chip.detail || chip.label}>
                                                                        {chip.detail ? `${t(chip.label)}: ${chip.detail}` : t(chip.label)}
                                                                    </Badge>
                                                                ))}
                                                            </div>
                                                        )}
                                                        {reply.error && (
                                                            <div className="mb-2 rounded-md border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive">
                                                                {reply.error}
                                                            </div>
                                                        )}
                                                        <InboxAttachments attachments={replyAttachmentItems(reply)} t={t} />
                                                        {changesRequested && changeNote && (
                                                            <div className="mb-2 rounded-md border bg-background p-2 text-xs text-muted-foreground">
                                                                <div className="mb-1 font-medium text-foreground">{t('Requested changes')}</div>
                                                                <div className="whitespace-pre-wrap">{changeNote}</div>
                                                            </div>
                                                        )}
                                                        {isRequestingChanges && (
                                                            <div className="mb-2 space-y-2 rounded-md border bg-background p-2">
                                                                <Label htmlFor={`change-request-${reply.id}`} className="text-xs">
                                                                    {t('Requested changes')}
                                                                </Label>
                                                                    <Textarea
                                                                        id={`change-request-${reply.id}`}
                                                                        data-outbound-change-note={reply.id}
                                                                        value={changeRequestNote}
                                                                        onChange={event => setChangeRequestNote(event.target.value)}
                                                                        rows={3}
                                                                    placeholder={t('Explain what needs to change before approval.')}
                                                                />
                                                                <div className="flex justify-end gap-2">
                                                                    <Button
                                                                        type="button"
                                                                        size="sm"
                                                                        variant="outline"
                                                                        onClick={cancelChangeRequest}
                                                                        disabled={requestingChangesReplyId === reply.id}
                                                                    >
                                                                        <X className="size-4" />
                                                                        {t('Cancel')}
                                                                    </Button>
                                                                        <Button
                                                                            type="button"
                                                                            size="sm"
                                                                            data-outbound-change-submit={reply.id}
                                                                            onClick={() => void requestReplyChanges(reply)}
                                                                            disabled={requestingChangesReplyId === reply.id}
                                                                        >
                                                                        {requestingChangesReplyId === reply.id
                                                                            ? <Loader className="size-4 animate-spin" />
                                                                            : <AlertTriangle className="size-4" />}
                                                                        {t('Request changes')}
                                                                    </Button>
                                                                </div>
                                                            </div>
                                                        )}
                                                        {isEditing ? (
                                                            <div className="space-y-2">
                                                                <Textarea
                                                                    value={editingReplyBody}
                                                                    onChange={event => setEditingReplyBody(event.target.value)}
                                                                    rows={8}
                                                                    className="bg-background"
                                                                />
                                                                <div className="flex justify-end gap-2">
                                                                    <Button
                                                                        type="button"
                                                                        size="sm"
                                                                        variant="outline"
                                                                        onClick={cancelEditingReply}
                                                                        disabled={savingReplyEditId === reply.id}
                                                                    >
                                                                        <X className="size-4" />
                                                                        {t('Cancel')}
                                                                    </Button>
                                                                    <Button
                                                                        type="button"
                                                                        size="sm"
                                                                        onClick={() => void saveEditedReply(reply)}
                                                                        disabled={savingReplyEditId === reply.id || !editingReplyBody.trim()}
                                                                    >
                                                                        {savingReplyEditId === reply.id
                                                                            ? <Loader className="size-4 animate-spin" />
                                                                            : <Save className="size-4" />}
                                                                        {t('Save changes')}
                                                                    </Button>
                                                                </div>
                                                            </div>
                                                        ) : (
                                                            <>
                                                                <pre className="max-h-48 overflow-auto whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
                                                                    {reply.body}
                                                                </pre>
                                                                <InboxAttachments attachments={replyAttachmentItems(reply)} t={t} />
                                                            </>
                                                        )}
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    </section>
                                )}
                            </div>

                            <aside className="space-y-4">
                                {(selectedIssue.accountId || loadingTicketAccount) && (
                                    <section className="rounded-md border p-4">
                                        <div className="mb-3 flex items-center justify-between gap-2">
                                            <div className="flex min-w-0 items-center gap-2 text-sm font-medium">
                                                <Building2 className="size-4 shrink-0" />
                                                <span className="truncate">{t('Account intelligence')}</span>
                                            </div>
                                            {ticketAccount && tenantId && (
                                                <Button
                                                    type="button"
                                                    size="sm"
                                                    variant="outline"
                                                    onClick={() => navigate(`/${tenantId}/${projectId}/accounts/${ticketAccount.id}`)}
                                                >
                                                    <ExternalLink className="size-3.5" />
                                                    {t('Open')}
                                                </Button>
                                            )}
                                        </div>
                                        {loadingTicketAccount ? (
                                            <div className="flex items-center gap-2 text-sm text-muted-foreground">
                                                <Loader className="size-3.5 animate-spin" />
                                                {t('Loading')}
                                            </div>
                                        ) : ticketAccount && ticketAccountInsightSummary && ticketAccountCrmHealth ? (
                                            <div className="space-y-3">
                                                <div className="min-w-0">
                                                    <div className="truncate text-sm font-medium">{accountLabel(ticketAccount)}</div>
                                                    <div className="mt-1 flex flex-wrap gap-1.5">
                                                        <Badge variant={accountHealthVariant(ticketAccount.healthStatus)} className="font-normal">
                                                            {ticketAccount.healthStatus || 'unknown'}
                                                        </Badge>
                                                        <Badge variant={ticketAccountCrmHealth.variant} className="font-normal">
                                                            {t(ticketAccountCrmHealth.label)}
                                                        </Badge>
                                                    </div>
                                                </div>
                                                <div className="grid grid-cols-3 gap-2">
                                                    <div className="rounded-md border bg-muted/20 p-2">
                                                        <div className="text-[11px] text-muted-foreground">{t('Risks')}</div>
                                                        <div className="text-lg font-semibold">{ticketAccountInsightSummary.openRisks}</div>
                                                    </div>
                                                    <div className="rounded-md border bg-muted/20 p-2">
                                                        <div className="text-[11px] text-muted-foreground">{t('Requests')}</div>
                                                        <div className="text-lg font-semibold">{ticketAccountInsightSummary.openFeatureRequests}</div>
                                                    </div>
                                                    <div className="rounded-md border bg-muted/20 p-2">
                                                        <div className="text-[11px] text-muted-foreground">{t('Signals')}</div>
                                                        <div className="text-lg font-semibold">{ticketAccountInsightSummary.unresolved}</div>
                                                    </div>
                                                </div>
                                                {accountInsightActions}
                                                <div className="rounded-md border bg-muted/20 p-2 text-sm">
                                                    <div className="mb-1 flex items-center justify-between gap-2">
                                                        <span className="flex min-w-0 items-center gap-1.5">
                                                            <Database className="size-3.5 shrink-0 text-muted-foreground" />
                                                            <span className="truncate">
                                                                {ticketAccountCrmHealth.providers.length > 0
                                                                    ? ticketAccountCrmHealth.providers.map(providerLabel).join(', ')
                                                                    : t('No CRM provider')}
                                                            </span>
                                                        </span>
                                                        <Badge variant="outline" className="shrink-0 font-normal">
                                                            {ticketAccountCrmHealth.externalObjects.length}
                                                        </Badge>
                                                    </div>
                                                    {ticketAccountCrmHealth.latestRun ? (
                                                        <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                                                            <span>{t('Latest sync')} {formatTime(syncRunTime(ticketAccountCrmHealth.latestRun))}</span>
                                                            <Badge variant={syncVariant(ticketAccountCrmHealth.latestRun.status)} className="shrink-0 font-normal">
                                                                {ticketAccountCrmHealth.latestRun.status || 'unknown'}
                                                            </Badge>
                                                        </div>
                                                    ) : (
                                                        <div className="text-xs text-muted-foreground">{t('No sync history')}</div>
                                                    )}
                                                    {ticketAccountCrmHealth.failedRuns[0]?.error && (
                                                        <div className="mt-1 text-xs text-destructive">
                                                            {ticketAccountCrmHealth.failedRuns[0].error}
                                                        </div>
                                                    )}
                                                </div>
                                                <div className="space-y-2">
                                                    <div className="text-xs font-medium uppercase text-muted-foreground">{t('Open account signals')}</div>
                                                    {ticketAccountOpenInsights.length === 0 ? (
                                                        <div className="text-sm text-muted-foreground">-</div>
                                                    ) : (
                                                        ticketAccountOpenInsights.map(renderTicketAccountInsightCard)
                                                    )}
                                                </div>
                                            </div>
                                        ) : (
                                            <div className="text-sm text-muted-foreground">{t('No account intelligence')}</div>
                                        )}
                                    </section>
                                )}

                                <section className="rounded-md border p-4">
                                    <div className="mb-3 flex items-center justify-between gap-2">
                                        <div className="flex items-center gap-2 text-sm font-medium">
                                            <BookOpen className="size-4" />
                                            {t('Knowledge')}
                                        </div>
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            data-ticket-create-knowledge-article
                                            onClick={() => void createKnowledgeArticleFromTicket()}
                                            disabled={Boolean(creatingKnowledgeArticle)}
                                        >
                                            {creatingKnowledgeArticle === selectedIssue.id
                                                ? <Loader className="size-3.5 animate-spin" />
                                                : <BookOpen className="size-3.5" />}
                                            {t('New')}
                                        </Button>
                                    </div>
                                    {selectedKnowledgeGaps.length > 0 && (
                                        <div className="mb-3 space-y-2">
                                            <div className="text-xs font-medium uppercase text-muted-foreground">{t('Knowledge gaps')}</div>
                                            {selectedKnowledgeGaps.map(gap => (
                                                <div key={gap.id} className="rounded-md border border-dashed bg-muted/20 p-2 text-sm">
                                                    <div className="mb-1 flex items-center justify-between gap-2">
                                                        <div className="min-w-0 truncate font-medium">{gap.suggestedArticleTitle || gap.title}</div>
                                                        <Badge variant={priorityVariant(gap.severity)} className="shrink-0 font-normal">
                                                            {gap.severity}
                                                        </Badge>
                                                    </div>
                                                    <div className="line-clamp-3 text-xs text-muted-foreground">{gap.evidence}</div>
                                                    <div className="mt-2 flex justify-end">
                                                        <Button
                                                            type="button"
                                                            size="sm"
                                                            variant="outline"
                                                            data-ticket-draft-knowledge-article={gap.id}
                                                            onClick={() => void createKnowledgeArticleFromTicket(gap)}
                                                            disabled={Boolean(creatingKnowledgeArticle)}
                                                        >
                                                            {creatingKnowledgeArticle === gap.id
                                                                ? <Loader className="size-3.5 animate-spin" />
                                                                : <BookOpen className="size-3.5" />}
                                                            {t('Draft article')}
                                                        </Button>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                    <div className="mb-3 space-y-2">
                                        <div className="relative">
                                            <Search className="pointer-events-none absolute left-2 top-2.5 size-3.5 text-muted-foreground" />
                                            <Input
                                                value={knowledgeQuery}
                                                onChange={event => setKnowledgeQuery(event.target.value)}
                                                placeholder={t('Search knowledge')}
                                                className="h-9 pl-7"
                                            />
                                        </div>
                                        {knowledgeQuery.trim() && (
                                            <div className="space-y-2">
                                                <div className="flex items-center justify-between gap-2 text-xs font-medium uppercase text-muted-foreground">
                                                    <span>{t('Search results')}</span>
                                                    {loadingKnowledge && <Loader className="size-3.5 animate-spin" />}
                                                </div>
                                                {searchedKnowledgeArticles.length === 0 ? (
                                                    <div className="text-sm text-muted-foreground">-</div>
                                                ) : (
                                                    searchedKnowledgeArticles.map(article => renderKnowledgeArticleCard(article))
                                                )}
                                            </div>
                                        )}
                                    </div>
                                    <div className="space-y-2">
                                        {(selectedIssue.knowledgeSuggestions ?? []).length === 0 ? (
                                            <div className="text-sm text-muted-foreground">-</div>
                                        ) : (
                                            (selectedIssue.knowledgeSuggestions ?? []).map(article => renderKnowledgeArticleCard(article))
                                        )}
                                    </div>
                                </section>

                                {customFieldsPanel}

                                <section className="rounded-md border p-4">
                                    <div className="mb-3 text-sm font-medium">{t('Lifecycle')}</div>
                                    <div className="space-y-3">
                                        <div className="space-y-1.5">
                                            <Label>{t('Status')}</Label>
                                            <Select
                                                value={issueWorkflowStatus(selectedIssue)}
                                                onValueChange={(value) => void patchSelectedIssue({ status: value as SupportIssueStatus })}
                                            >
                                                <SelectTrigger>
                                                    <SelectValue />
                                                </SelectTrigger>
                                                <SelectContent>
                                                    {statusOptions.map(option => {
                                                        const doneBlocked = option.value === 'done'
                                                            && issueWorkflowStatus(selectedIssue) !== 'done'
                                                            && issueDoneBlockers(selectedIssue).length > 0;
                                                        return (
                                                            <SelectItem
                                                                key={option.value}
                                                                value={option.value}
                                                                disabled={
                                                                    (statusNeedsAssignee(option.value) && !selectedIssue.assigneeEmail && !canAutoClaim)
                                                                    || doneBlocked
                                                                }
                                                            >
                                                                {t(option.label)}
                                                            </SelectItem>
                                                        );
                                                    })}
                                                </SelectContent>
                                            </Select>
                                            {issueWorkflowStatus(selectedIssue) !== 'done' && issueDoneBlockerText(selectedIssue) && (
                                                <div className="flex items-center gap-1.5 text-xs text-destructive">
                                                    <AlertTriangle className="size-3.5" />
                                                    {t('Resolve before closing')}: {issueDoneBlockerText(selectedIssue)}
                                                </div>
                                            )}
                                            {issueWorkflowStatus(selectedIssue) !== 'done' && issueCanResolveWithoutReply(selectedIssue) && (
                                                <Button
                                                    type="button"
                                                    size="sm"
                                                    variant="outline"
                                                    onClick={openCloseWithoutReplyDialog}
                                                    data-ticket-close-without-reply-open
                                                >
                                                    <CheckCircle2 className="size-3.5" />
                                                    {t('Close without reply')}
                                                </Button>
                                            )}
                                            {!selectedIssue.assigneeEmail && (
                                                <div className="flex items-start gap-1.5 text-xs text-muted-foreground">
                                                    <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
                                                    <div className="space-y-1">
                                                        <div>
                                                            {canAutoClaim
                                                                ? t('Working this ticket assigns it to you.')
                                                                : t('Assign before changing status.')}
                                                        </div>
                                                        <div>{t(issueAssignmentDetail(selectedIssue))}</div>
                                                        {issueAssignmentHint(selectedIssue) && (
                                                            <div>{t(issueAssignmentHint(selectedIssue))}</div>
                                                        )}
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                        <div className="space-y-1.5">
                                            <Label>{t('Priority')}</Label>
                                            <Select
                                                value={selectedIssue.priority}
                                                onValueChange={(value) => void patchSelectedIssue({ priority: value as SupportIssuePriority })}
                                            >
                                                <SelectTrigger>
                                                    <SelectValue />
                                                </SelectTrigger>
                                                <SelectContent>
                                                    {priorityOptions.map(option => (
                                                        <SelectItem key={option.value} value={option.value}>{t(option.label)}</SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                        </div>
                                        <div className="space-y-1.5">
                                            <Label>{t('Queue')}</Label>
                                            <Select
                                                value={issueQueueKey(selectedIssue) || NO_QUEUE_VALUE}
                                                onValueChange={(value) => void assignQueue(value)}
                                                disabled={savingQueue}
                                            >
                                                <SelectTrigger>
                                                    <SelectValue />
                                                </SelectTrigger>
                                                <SelectContent>
                                                    {queueOptions.map(option => (
                                                        <SelectItem key={option.queueKey} value={option.queueKey}>{option.name}</SelectItem>
                                                    ))}
                                                    <SelectItem value={NO_QUEUE_VALUE}>{t('No queue')}</SelectItem>
                                                </SelectContent>
                                            </Select>
                                            {selectedQueueOwnerEmails.length > 0 && (
                                                <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                                                    <span>{t('Queue owners')}:</span>
                                                    {selectedQueueOwnerEmails.map(email => {
                                                        const workload = selectedQueueOwnerWorkloads.get(email.toLowerCase());
                                                        return (
                                                            <Badge
                                                                key={email}
                                                                variant={workload?.atCapacity ? 'outline' : 'secondary'}
                                                                className="font-normal"
                                                                title={queueOwnerWorkloadDetail(email, workload)}
                                                            >
                                                                {queueOwnerWorkloadLabel(email, workload)}
                                                            </Badge>
                                                        );
                                                    })}
                                                </div>
                                            )}
                                        </div>
                                        <div className="space-y-1.5">
                                            <Label htmlFor="issue-tags">{t('Labels')}</Label>
                                            {(selectedIssue.tags ?? []).length > 0 && (
                                                <div className="flex flex-wrap gap-1.5">
                                                    {(selectedIssue.tags ?? []).map(tag => (
                                                        <Badge key={tag} variant="outline" className="gap-1 font-normal">
                                                            <Tag className="size-3" />
                                                            {tag}
                                                            <button
                                                                type="button"
                                                                className="ml-0.5 rounded-sm text-muted-foreground hover:text-foreground"
                                                                onClick={() => void removeTag(tag)}
                                                                disabled={savingTags}
                                                                aria-label={t('Remove label')}
                                                            >
                                                                <X className="size-3" />
                                                            </button>
                                                        </Badge>
                                                    ))}
                                                </div>
                                            )}
                                            <div className="flex gap-2" data-ticket-assignee-current={selectedIssue.assigneeEmail || ''}>
                                                <Input
                                                    id="issue-tags"
                                                    value={tagDraft}
                                                    onChange={event => setTagDraft(event.target.value)}
                                                    placeholder={t('bug, vip, feature-request')}
                                                />
                                                <Button
                                                    type="button"
                                                    variant="outline"
                                                    onClick={() => void saveTags()}
                                                    disabled={savingTags}
                                                >
                                                    {savingTags ? <Loader className="size-4 animate-spin" /> : t('Save')}
                                                </Button>
                                            </div>
                                        </div>
                                        <div className="space-y-1.5">
                                            <Label htmlFor="issue-assignee">{t('Assignee')}</Label>
                                            <div className="flex gap-2">
                                                {assigneeOptions.length > 0 ? (
                                                    <Select
                                                        value={assigneeDraft || UNASSIGNED_VALUE}
                                                        onValueChange={(value) => setAssigneeDraft(value === UNASSIGNED_VALUE ? '' : value)}
                                                    >
                                                        <SelectTrigger id="issue-assignee" className="min-w-0 flex-1">
                                                            <SelectValue />
                                                        </SelectTrigger>
                                                        <SelectContent>
                                                            <SelectItem value={UNASSIGNED_VALUE}>{t('Unassigned')}</SelectItem>
                                                            {assigneeOptions.map(email => {
                                                                const workload = selectedQueueOwnerWorkloads.get(email.toLowerCase());
                                                                return (
                                                                    <SelectItem key={email} value={email}>
                                                                        {queueOwnerWorkloadLabel(email, workload)}
                                                                    </SelectItem>
                                                                );
                                                            })}
                                                        </SelectContent>
                                                    </Select>
                                                ) : (
                                                    <Input
                                                        id="issue-assignee"
                                                        value={assigneeDraft}
                                                        onChange={event => setAssigneeDraft(event.target.value)}
                                                        placeholder="agent@example.com"
                                                    />
                                                )}
                                                <Button
                                                    type="button"
                                                    variant="outline"
                                                    onClick={() => void saveAssignee()}
                                                    disabled={savingAssignee}
                                                >
                                                    {savingAssignee ? <Loader className="size-4 animate-spin" /> : t('Save')}
                                                </Button>
                                            </div>
                                            {selectedAssigneeWorkloadDetail && (
                                                <div className={`flex items-start gap-1.5 text-xs ${selectedAssigneeWorkload?.atCapacity ? 'text-amber-700' : 'text-muted-foreground'}`}>
                                                    {selectedAssigneeWorkload?.atCapacity && <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />}
                                                    <span>{selectedAssigneeWorkloadDetail}</span>
                                                </div>
                                            )}
                                            <div className="flex gap-2">
                                                {currentUserEmail && (
                                                    <Button
                                                        type="button"
                                                        size="sm"
                                                        variant="ghost"
                                                        onClick={() => void assignIssue(currentUserEmail)}
                                                        disabled={savingAssignee || selectedIssue.assigneeEmail === currentUserEmail}
                                                    >
                                                        {t('Assign to me')}
                                                    </Button>
                                                )}
                                                <Button
                                                    type="button"
                                                    size="sm"
                                                    variant="ghost"
                                                    onClick={() => void assignIssue('')}
                                                    disabled={savingAssignee || statusNeedsAssignee(issueWorkflowStatus(selectedIssue)) || (!selectedIssue.assigneeEmail && !assigneeDraft)}
                                                >
                                                    {t('Unassign')}
                                                </Button>
                                            </div>
                                        </div>
                                        <div className="border-t pt-3">
                                            {duplicateSuggestionsPanel}
                                        </div>
                                    </div>
                                </section>

                                <section className="rounded-md border p-4">
                                    <div className="mb-3 flex items-center justify-between gap-2">
                                        <div className="text-sm font-medium">{t('Customer portal')}</div>
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            data-ticket-create-portal-link
                                            onClick={() => void createPortalLink()}
                                            disabled={creatingPortalLink}
                                        >
                                            {creatingPortalLink ? <Loader className="size-3.5 animate-spin" /> : <Link className="size-3.5" />}
                                            {t('New link')}
                                        </Button>
                                    </div>
                                    {portalUrl && (
                                        <div className="mb-3 flex min-w-0 items-center gap-2 rounded-md border bg-muted/20 p-2 text-xs">
                                            <a
                                                href={portalUrl}
                                                target="_blank"
                                                rel="noreferrer"
                                                className="min-w-0 flex-1 truncate underline"
                                                data-ticket-portal-url
                                            >
                                                {portalUrl}
                                            </a>
                                            <Button
                                                type="button"
                                                size="sm"
                                                variant="ghost"
                                                onClick={() => {
                                                    void navigator.clipboard?.writeText(portalUrl);
                                                    toast.success(t('Copied'));
                                                }}
                                            >
                                                <Copy className="size-3.5" />
                                            </Button>
                                        </div>
                                    )}
                                    <div className="space-y-2">
                                        {(selectedIssue.portalSessions ?? []).length === 0 ? (
                                            <div className="text-sm text-muted-foreground">-</div>
                                        ) : (
                                            (selectedIssue.portalSessions ?? []).map(session => (
                                                <div key={session.id} className="space-y-1 rounded-md border bg-muted/20 p-2 text-sm">
                                                    <div className="flex items-center justify-between gap-2">
                                                        <span className="truncate">{session.createdBy || t('Portal link')}</span>
                                                        <Badge variant="outline" className="font-normal">{session.status}</Badge>
                                                    </div>
                                                    <div className="text-xs text-muted-foreground">
                                                        {t('Expires')} {formatTime(session.expiresAt)}
                                                    </div>
                                                    {session.lastAccessedAt && (
                                                        <div className="text-xs text-muted-foreground">
                                                            {t('Last opened')} {formatTime(session.lastAccessedAt)}
                                                        </div>
                                                    )}
                                                </div>
                                            ))
                                        )}
                                    </div>
                                </section>

                                <section className="rounded-md border p-4">
                                    <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                                        <Star className="size-4 text-muted-foreground" />
                                        {t('Customer satisfaction')}
                                    </div>
                                    {(selectedIssue.csatFeedback ?? []).length === 0 ? (
                                        <div className="text-sm text-muted-foreground">-</div>
                                    ) : (
                                        <div className="space-y-2">
                                            {(selectedIssue.csatFeedback ?? []).slice(0, 3).map(feedback => (
                                                <div
                                                    key={feedback.id}
                                                    className="rounded-md border bg-muted/20 p-2 text-sm"
                                                    data-ticket-csat-feedback
                                                >
                                                    <div className="flex items-center justify-between gap-2">
                                                        <Badge variant={feedback.rating <= 2 ? 'destructive' : 'secondary'} className="font-normal">
                                                            {feedback.rating}/5
                                                        </Badge>
                                                        <span className="text-xs text-muted-foreground">{formatTime(feedback.receivedAt)}</span>
                                                    </div>
                                                    {(feedback.customerEmail || feedback.customerName) && (
                                                        <div className="mt-1 truncate text-xs text-muted-foreground">
                                                            {feedback.customerName || feedback.customerEmail}
                                                        </div>
                                                    )}
                                                    {feedback.comment && (
                                                        <div className="mt-2 whitespace-pre-wrap text-sm">{feedback.comment}</div>
                                                    )}
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </section>

                                <section className="rounded-md border p-4">
                                    <div className="mb-3 text-sm font-medium">{t('Activity')}</div>
                                    <div className="space-y-2">
                                        {(selectedIssue.activityEvents ?? []).length === 0 ? (
                                            <div className="text-sm text-muted-foreground">-</div>
                                        ) : (
                                            (selectedIssue.activityEvents ?? []).map(event => (
                                                <ActivityEventCard key={activityEventKey(event)} event={event} t={t} />
                                            ))
                                        )}
                                    </div>
                                </section>

                                <section className="rounded-md border p-4">
                                    <div className="mb-3 text-sm font-medium">{t('SLA')}</div>
                                    <div className="space-y-2">
                                        {(selectedIssue.slaEvents ?? []).length === 0 ? (
                                            <div className="text-sm text-muted-foreground">-</div>
                                        ) : (
                                            (selectedIssue.slaEvents ?? []).map((event) => {
                                                const overdue = slaEventIsOverdue(event);
                                                return (
                                                    <div key={event.id} className="space-y-1 rounded-md border bg-muted/20 p-2 text-sm">
                                                        <div className="flex items-center justify-between gap-2">
                                                            <span className="truncate">{t(slaEventLabel(event.eventType))}</span>
                                                            <Badge variant={overdue ? 'destructive' : 'outline'} className="font-normal">
                                                                {overdue ? t('Overdue') : event.status}
                                                            </Badge>
                                                        </div>
                                                        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                                                            {overdue && <AlertTriangle className="size-3.5" />}
                                                            {formatTime(event.targetAt)}
                                                        </div>
                                                    </div>
                                                );
                                            })
                                        )}
                                    </div>
                                </section>

                                <section className="rounded-md border p-4">
                                    <div className="mb-3 text-sm font-medium">{t('Assignments')}</div>
                                    <div className="space-y-2">
                                        {(selectedIssue.assignmentHistory ?? []).length === 0 ? (
                                            <div className="text-sm text-muted-foreground">-</div>
                                        ) : (
                                            (selectedIssue.assignmentHistory ?? []).map(assignment => (
                                                <div key={assignment.id} className="text-sm">
                                                    <div>{assignment.assigneeEmail || t('Unassigned')}</div>
                                                    <div className="text-xs text-muted-foreground">
                                                        {assignment.assignedBy || '-'} · {formatTime(assignment.created)}
                                                    </div>
                                                </div>
                                            ))
                                        )}
                                    </div>
                                </section>

                                <section className="rounded-md border p-4">
                                    <div className="mb-3 flex items-center justify-between gap-2">
                                        <div className="text-sm font-medium">{t('Watchers')}</div>
                                        {currentUserEmail && (
                                            <Button
                                                type="button"
                                                size="sm"
                                                variant="outline"
                                                data-ticket-watch-toggle
                                                onClick={() => void toggleWatching()}
                                                disabled={togglingWatcher}
                                            >
                                                {togglingWatcher ? <Loader className="size-3.5 animate-spin" /> : <Bell className="size-3.5" />}
                                                {currentWatcher ? t('Unwatch') : t('Watch')}
                                            </Button>
                                        )}
                                    </div>
                                    <div className="space-y-2">
                                        {selectedWatchers.length === 0 ? (
                                            <div className="text-sm text-muted-foreground">-</div>
                                        ) : (
                                            selectedWatchers.map(watcher => (
                                                <div key={watcher.id || watcher.watcherEmail} className="text-sm" data-ticket-watcher-row data-ticket-watcher-email={watcher.watcherEmail}>
                                                    <div>{watcher.watcherEmail}</div>
                                                    <div className="text-xs text-muted-foreground">
                                                        {watcher.source || 'manual'} · {watcher.addedBy || '-'}
                                                    </div>
                                                </div>
                                            ))
                                        )}
                                    </div>
                                </section>

                                <section className="rounded-md border p-4">
                                    <div className="mb-3 text-sm font-medium">{t('Internal notes')}</div>
                                    <div className="mb-3 space-y-2">
                                        {(selectedIssue.notes ?? []).length === 0 ? (
                                            <div className="text-sm text-muted-foreground">-</div>
                                        ) : (
                                            (selectedIssue.notes ?? []).map(note => (
                                                <div key={note.id} className="rounded-md border bg-muted/20 p-2 text-sm">
                                                    <div className="mb-1 text-xs text-muted-foreground">
                                                        {note.authorEmail || '-'} · {formatTime(note.created)}
                                                    </div>
                                                    <div className="whitespace-pre-wrap">{note.body}</div>
                                                </div>
                                            ))
                                        )}
                                    </div>
                                    <div className="space-y-2">
                                        <Textarea
                                            data-ticket-internal-note-input
                                            value={noteDraft}
                                            onChange={event => setNoteDraft(event.target.value)}
                                            rows={3}
                                            placeholder={t('Internal note')}
                                        />
                                        <Button
                                            type="button"
                                            variant="outline"
                                            className="w-full"
                                            data-ticket-internal-note-submit
                                            onClick={() => void addNote()}
                                            disabled={savingNote || !noteDraft.trim()}
                                        >
                                            {savingNote ? <Loader className="size-4 animate-spin" /> : null}
                                            {t('Add note')}
                                        </Button>
                                    </div>
                                </section>

                                <section className="rounded-md border p-4">
                                    <RunbookAudit
                                        primaryIntent={selectedIssue.activatedIntent}
                                        concerns={auditRunbookConcerns}
                                        t={t}
                                    />
                                    <Separator className="my-3" />
                                    <div className="space-y-2">
                                        <div className="text-xs font-medium uppercase text-muted-foreground">{t('Actions')}</div>
                                        {(selectedIssue.actionLog ?? []).length === 0 ? (
                                            <div className="text-sm text-muted-foreground">-</div>
                                        ) : (
                                            (selectedIssue.actionLog ?? []).map((action, index) => (
                                                <div key={`${action.label}-${index}`} className="space-y-2 rounded-md border bg-muted/20 p-2 text-sm">
                                                    <div className="flex items-center justify-between gap-2">
                                                        <span className="truncate">{action.label}</span>
                                                        <Badge variant="outline" className="font-normal">{action.status}</Badge>
                                                    </div>
                                                    <div className="flex flex-wrap gap-1.5">
                                                        {(['running', 'success', 'failed'] as const).map(status => {
                                                            const key = `${action.type || 'action'}:${action.label || index}:${status}`;
                                                            return (
                                                                <Button
                                                                    key={status}
                                                                    type="button"
                                                                    size="sm"
                                                                    variant="outline"
                                                                    onClick={() => void recordAction(action, index, status)}
                                                                    disabled={Boolean(savingActionKey)}
                                                                >
                                                                    {savingActionKey === key ? <Loader className="size-3.5 animate-spin" /> : null}
                                                                    {status}
                                                                </Button>
                                                            );
                                                        })}
                                                    </div>
                                                </div>
                                            ))
                                        )}
                                    </div>
                                </section>

                                <section className="rounded-md border p-4">
                                    <div className="mb-3 flex items-center justify-between gap-2">
                                        <div className="text-sm font-medium">{t('Action history')}</div>
                                        <Badge variant="outline" className="font-normal">
                                            {(selectedIssue.actionExecutions ?? []).length}
                                        </Badge>
                                    </div>
                                    <div className="space-y-2">
                                        {(selectedIssue.actionExecutions ?? []).length === 0 ? (
                                            <div className="text-sm text-muted-foreground">-</div>
                                        ) : (
                                            (selectedIssue.actionExecutions ?? []).map(execution => (
                                                <ActionExecutionCard
                                                    key={execution.id}
                                                    execution={execution}
                                                    t={t}
                                                    approvingActionExecutionId={approvingActionExecutionId}
                                                    rejectingActionExecutionId={rejectingActionExecutionId}
                                                    onApprove={approveActionExecution}
                                                    onReject={rejectActionExecution}
                                                />
                                            ))
                                        )}
                                    </div>
                                </section>

                                <section className="rounded-md border p-4">
                                    <div className="mb-3 flex items-center justify-between gap-2">
                                        <div className="text-sm font-medium">{t('AI runs')}</div>
                                        <Badge variant="outline" className="font-normal">
                                            {auditAiRuns.length}
                                        </Badge>
                                    </div>
                                    <div className="space-y-3">
                                        {auditAiRuns.length === 0 ? (
                                            <div className="text-sm text-muted-foreground">-</div>
                                        ) : (
                                            auditAiRuns.map(run => (
                                                <div key={run.id} className="rounded-md border bg-muted/20 p-2 text-sm">
                                                    <div className="mb-1 flex items-center justify-between gap-2">
                                                        <span className="truncate">{run.activatedIntent || t('No match')}</span>
                                                        <Badge variant="outline" className="font-normal">{run.status}</Badge>
                                                    </div>
                                                    <div className="space-y-1 text-xs text-muted-foreground">
                                                        <div>{run.source || '-'} · {formatTime(run.completedAt || run.updated)}</div>
                                                        <div>
                                                            {run.toolCalls.length} {t('tools')} · {tokenTotal(run.tokenUsage)} {t('tokens')}
                                                        </div>
                                                        {run.requiresHuman && <div>{t('Human review required')}</div>}
                                                    </div>
                                                </div>
                                            ))
                                        )}
                                    </div>
                                </section>

                                <section className="rounded-md border p-4">
                                    <div className="mb-3 text-sm font-medium">{t('Contact')}</div>
                                    <div className="space-y-2 text-sm">
                                        <div>
                                            <div className="text-xs text-muted-foreground">{t('Name')}</div>
                                            <div>{selectedIssue.contactName || '-'}</div>
                                        </div>
                                        <div>
                                            <div className="text-xs text-muted-foreground">{t('Email')}</div>
                                            <div className="break-all">{selectedIssue.contactEmail || '-'}</div>
                                        </div>
                                        <div>
                                            <div className="text-xs text-muted-foreground">{t('Account')}</div>
                                            <div>{selectedIssue.accountName || selectedIssue.accountDomain || '-'}</div>
                                        </div>
                                    </div>
                                </section>
                            </aside>
                        </div>
                    </div>
                )}
            </section>
            </DrawerContent>
            </Drawer>
            </div>
        </>
    );
}
