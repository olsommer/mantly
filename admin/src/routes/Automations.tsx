import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import type { LucideIcon } from 'lucide-react';
import { AlertTriangle, CheckCircle2, ExternalLink, Loader, MessageSquareText, Play, Plus, Sparkles, UserPlus, Workflow } from 'lucide-react';
import { toast } from 'sonner';

import { api } from '@/api/endpoints';
import type {
    ProjectMember,
    SupportAutomationBacklogRunResult,
    SupportAutomationPreviewAction,
    SupportAutomationPreviewResult,
    SupportAutomationPreviewSummary,
    SupportAutomationRule,
    SupportAutomationRun,
    SupportAutomationTrigger,
    SupportSlaEscalationRun,
} from '@/api/endpoints';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useI18n } from '@/lib/i18n-context';

interface AutomationsProps {
    projectId: string;
}

type ActionBuilderType = 'assign' | 'queue_reply' | 'prepare_agent_reply' | 'prepare_triage' | 'prepare_custom_fields' | 'set_priority' | 'set_status' | 'set_custom_fields' | 'add_note';
type ApprovalPolicy = 'approval_required' | 'no_approval';
type ConditionBuilderType = 'priorityIn' | 'statusIn' | 'channelIn' | 'tagsAny' | 'customFields' | 'unassigned' | 'requiresHuman' | 'activatedIntent' | 'assigneeEmail';

const DEFAULT_ASSIGNEE = 'agent@example.com';
const DEFAULT_AGENT_QUESTION = 'Draft an approval-ready response from the ticket context and knowledge base.';
const DEFAULT_QUEUE_REPLY_BODY = 'Thanks for reaching out. We are looking into this.';
const DEFAULT_CONDITION_VALUES: Record<ConditionBuilderType, string> = {
    priorityIn: 'high, urgent',
    statusIn: 'open, ongoing',
    channelIn: 'email, slack',
    tagsAny: 'vip, billing',
    customFields: 'plan=Enterprise',
    unassigned: '',
    requiresHuman: '',
    activatedIntent: 'incident_response',
    assigneeEmail: DEFAULT_ASSIGNEE,
};

const DEFAULT_CONDITIONS = JSON.stringify({
    priorityIn: ['high', 'urgent'],
    unassigned: true,
}, null, 2);

function defaultActionsJson(assigneeEmail: string = DEFAULT_ASSIGNEE) {
    return JSON.stringify([
        {
            type: 'assign',
            assigneeEmail,
        },
        {
            type: 'prepare_triage',
            approvalRequired: true,
        },
        {
            type: 'prepare_custom_fields',
            approvalRequired: true,
            onlyMissing: true,
        },
        {
            type: 'prepare_agent_reply',
            question: DEFAULT_AGENT_QUESTION,
            createDraft: true,
            includeFeedbackLink: true,
        },
    ], null, 2);
}

function autopilotConditionsJson() {
    return JSON.stringify({
        requiresHuman: true,
        unassigned: true,
    }, null, 2);
}

function autopilotActionsJson(assigneeEmail: string) {
    return JSON.stringify([
        {
            type: 'assign',
            assigneeEmail,
        },
        {
            type: 'prepare_triage',
            approvalRequired: true,
        },
        {
            type: 'prepare_custom_fields',
            approvalRequired: true,
            onlyMissing: true,
        },
        {
            type: 'prepare_agent_reply',
            question: DEFAULT_AGENT_QUESTION,
            createDraft: true,
            includeFeedbackLink: true,
        },
    ], null, 2);
}

const DEFAULT_ACTIONS = defaultActionsJson();

const automationTriggerOptions: Array<{ value: SupportAutomationTrigger; label: string }> = [
    { value: 'issue_created', label: 'Issue created' },
    { value: 'issue_updated', label: 'Issue updated' },
    { value: 'sla_breached', label: 'SLA breached' },
    { value: 'reply_approved', label: 'Reply approved' },
    { value: 'reply_sent', label: 'Reply sent' },
    { value: 'reply_failed', label: 'Reply failed' },
    { value: 'reply_deferred', label: 'Reply deferred' },
    { value: 'any_issue_event', label: 'Any issue event' },
    { value: 'manual', label: 'Manual' },
];

const ACTION_TEMPLATES: Array<{
    label: string;
    icon: LucideIcon;
    actions: Array<Record<string, unknown>>;
}> = [
    {
        label: 'Agent triage',
        icon: Workflow,
        actions: [{
            type: 'prepare_triage',
            approvalRequired: true,
        }],
    },
    {
        label: 'Agent draft',
        icon: Sparkles,
        actions: [{
            type: 'prepare_agent_reply',
            question: DEFAULT_AGENT_QUESTION,
            createDraft: true,
            includeFeedbackLink: true,
        }],
    },
    {
        label: 'Agent fields',
        icon: Sparkles,
        actions: [{
            type: 'prepare_custom_fields',
            approvalRequired: true,
            onlyMissing: true,
        }],
    },
    {
        label: 'Assign',
        icon: UserPlus,
        actions: [{
            type: 'assign',
            assigneeEmail: 'agent@example.com',
        }],
    },
    {
        label: 'Queue reply',
        icon: MessageSquareText,
        actions: [{
            type: 'queue_reply',
            body: DEFAULT_QUEUE_REPLY_BODY,
            approvalRequired: true,
            includeFeedbackLink: true,
            assigneeEmail: 'agent@example.com',
        }],
    },
    {
        label: 'SLA escalate',
        icon: AlertTriangle,
        actions: [
            {
                type: 'set_priority',
                priority: 'urgent',
            },
            {
                type: 'add_note',
                body: 'SLA breached. Review owner, customer reply, and resolution path.',
            },
            {
                type: 'prepare_agent_reply',
                question: 'Draft an urgent, approval-ready customer update for this SLA breach using the ticket context and knowledge base.',
                createDraft: true,
                includeFeedbackLink: true,
            },
        ],
    },
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

function triggerLabel(trigger: string) {
    if (trigger === 'issue_created') return 'Issue created';
    if (trigger === 'issue_updated') return 'Issue updated';
    if (trigger === 'sla_breached') return 'SLA breached';
    if (trigger === 'reply_approved') return 'Reply approved';
    if (trigger === 'reply_sent') return 'Reply sent';
    if (trigger === 'reply_failed') return 'Reply failed';
    if (trigger === 'reply_deferred') return 'Reply deferred';
    if (trigger === 'any_issue_event') return 'Any issue event';
    if (trigger === 'manual') return 'Manual';
    return trigger;
}

function stringFrom(value: unknown): string {
    if (typeof value === 'string') return value;
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
    return '';
}

function summaryValues(value: unknown): string[] {
    if (Array.isArray(value)) return value.map(stringFrom).filter(Boolean);
    const raw = stringFrom(value);
    return raw ? [raw] : [];
}

function shortValueList(value: unknown) {
    const values = summaryValues(value);
    if (values.length === 0) return '-';
    const visible = values.slice(0, 3).join(', ');
    return values.length > 3 ? `${visible} +${values.length - 3}` : visible;
}

function actionOwnerEmail(action: { assigneeEmail?: unknown; ownerEmail?: unknown; reviewerEmail?: unknown }) {
    const owner = action.assigneeEmail || action.ownerEmail || action.reviewerEmail;
    return typeof owner === 'string' ? owner.trim() : '';
}

function conditionSummaryLabel(key: string, value: unknown): string {
    if (key === 'priorityIn') return `Priority: ${shortValueList(value)}`;
    if (key === 'statusIn') return `Status: ${shortValueList(value)}`;
    if (key === 'channelIn') return `Channel: ${shortValueList(value)}`;
    if (key === 'tag' || key === 'tagIn' || key === 'tagsIn' || key === 'tagsAny') return `Tags: ${shortValueList(value)}`;
    if (key === 'tagsAll') return `All tags: ${shortValueList(value)}`;
    if (key === 'customFields' || key === 'custom_fields' || key === 'customFieldEquals') {
        return `Ticket fields: ${shortValueList(Object.entries(isRecord(value) ? value : {}).map(([field, fieldValue]) => `${field}=${stringFrom(fieldValue)}`))}`;
    }
    if (key === 'customFieldExists') return `Field exists: ${shortValueList(value)}`;
    if (key === 'customFieldMissing') return `Field missing: ${shortValueList(value)}`;
    if (key === 'unassigned') return value ? 'Unassigned' : 'Assigned';
    if (key === 'requiresHuman') return value ? 'Needs human' : 'No human';
    if (key === 'activatedIntent') return `Runbook: ${shortValueList(value)}`;
    if (key === 'assigneeEmail') return `Assignee: ${shortValueList(value)}`;
    if (key.endsWith('In')) return `${key.slice(0, -2)}: ${shortValueList(value)}`;
    return `${key}: ${shortValueList(value)}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function keyValueObjectFrom(value: string): Record<string, string> {
    const result: Record<string, string> = {};
    for (const item of value.split(/[,\n]/)) {
        const clean = item.trim();
        if (!clean) continue;
        const separator = clean.includes('=') ? '=' : clean.includes(':') ? ':' : '';
        if (!separator) continue;
        const [rawKey, ...rawValueParts] = clean.split(separator);
        const key = rawKey.trim();
        const fieldValue = rawValueParts.join(separator).trim();
        if (key && fieldValue) result[key] = fieldValue;
    }
    return result;
}

function conditionSummaryLabels(conditions: Record<string, unknown>, limit = 4): string[] {
    const labels = Object.entries(conditions).map(([key, value]) => conditionSummaryLabel(key, value));
    if (labels.length <= limit) return labels;
    return [...labels.slice(0, limit), `+${labels.length - limit}`];
}

function actionApprovalRequired(action: Record<string, unknown>): boolean {
    return action.approvalRequired !== false && action.approval_required !== false;
}

function actionAutoSendRequested(action: Record<string, unknown>): boolean {
    return action.autoSend === true || action.auto_send === true || action.autoSendRequested === true;
}

function actionAutoSendBlocked(action: Record<string, unknown>): boolean {
    return actionAutoSendRequested(action) && actionApprovalRequired(action);
}

function actionSummaryLabel(action: Record<string, unknown>): string {
    const actionType = stringFrom(action.type || action.action || action.kind) || 'Action';
    if (actionType === 'assign') return `Assign ${shortValueList(action.assigneeEmail || action.assignee_email || action.email)}`;
    if (actionType === 'set_status') return `Set status ${shortValueList(action.status)}`;
    if (actionType === 'set_priority') return `Set priority ${shortValueList(action.priority)}`;
    if (actionType === 'set_custom_fields' || actionType === 'set_custom_field' || actionType === 'update_custom_fields') {
        const fields = action.customFields || action.custom_fields || action.fields || action.values;
        const labels = Object.entries(isRecord(fields) ? fields : {}).map(([field, value]) => `${field}=${stringFrom(value)}`);
        return `Set fields ${shortValueList(labels)}`;
    }
    if (actionType === 'add_note') return 'Add note';
    if (actionType === 'queue_reply') {
        const label = action.approvalRequired === false || action.approval_required === false ? 'Queue reply' : 'Queue approval';
        const owner = actionOwnerEmail(action);
        const csat = action.includeFeedbackLink === true || action.include_feedback_link === true ? ' + CSAT' : '';
        return owner ? `${label}: ${owner}${csat}` : `${label}${csat}`;
    }
    if (actionType === 'prepare_agent_reply' || actionType === 'ask_agent' || actionType === 'agent_answer') {
        let label = action.createDraft === false || action.create_draft === false ? 'Ask agent' : 'Agent draft';
        if (actionAutoSendRequested(action)) label = 'Agent auto-send';
        if (actionAutoSendBlocked(action)) label = 'Agent auto-send blocked';
        return action.includeFeedbackLink === true || action.include_feedback_link === true ? `${label} + CSAT` : label;
    }
    if (actionType === 'prepare_triage' || actionType === 'triage_ticket' || actionType === 'agent_triage') {
        return action.approvalRequired === false || action.approval_required === false ? 'Agent triage' : 'Agent triage approval';
    }
    if (actionType === 'prepare_custom_fields' || actionType === 'extract_custom_fields' || actionType === 'prepare_ticket_fields') {
        return action.approvalRequired === false || action.approval_required === false ? 'Agent fields' : 'Agent fields approval';
    }
    if (actionType === 'record_action') return `Record ${shortValueList(action.label || action.actionKey || action.action_key)}`;
    return actionType;
}

function actionSummaryLabels(actions: Array<Record<string, unknown>>, limit = 4): string[] {
    const labels = actions.map(actionSummaryLabel);
    if (labels.length <= limit) return labels;
    return [...labels.slice(0, limit), `+${labels.length - limit}`];
}

function automationActionType(action: Record<string, unknown>) {
    return stringFrom(action.type || action.action || action.kind);
}

function actionCreatesAgentDraft(action: Record<string, unknown>) {
    const actionType = automationActionType(action);
    return (actionType === 'prepare_agent_reply' || actionType === 'agent_answer' || actionType === 'ask_agent')
        && action.createDraft !== false
        && action.create_draft !== false;
}

function actionChangesTicketWithoutApproval(action: Record<string, unknown>) {
    const actionType = automationActionType(action);
    return !actionApprovalRequired(action) && [
        'prepare_agent_reply',
        'queue_reply',
        'prepare_triage',
        'prepare_custom_fields',
        'set_custom_fields',
        'set_status',
        'set_priority',
    ].includes(actionType);
}

function ruleHasAction(rule: SupportAutomationRule, predicate: (action: Record<string, unknown>) => boolean) {
    return (rule.actions ?? []).some(action => predicate(action));
}

function ruleHasHumanLoopAgentDraft(rule: SupportAutomationRule) {
    return ruleHasAction(rule, action => actionCreatesAgentDraft(action) && actionApprovalRequired(action));
}

function ruleHasAutopilotPackage(rule: SupportAutomationRule) {
    return ruleHasAction(rule, action => automationActionType(action) === 'prepare_triage' && actionApprovalRequired(action))
        && ruleHasAction(rule, action => automationActionType(action) === 'prepare_custom_fields' && actionApprovalRequired(action))
        && ruleHasHumanLoopAgentDraft(rule);
}

function automationRunFailed(run: SupportAutomationRun) {
    return run.status === 'failed' || run.status === 'error' || Boolean(run.error);
}

function automationRunActionLabels(run: SupportAutomationRun, limit = 4): string[] {
    const actions = run.result.actions;
    if (!Array.isArray(actions)) return [];
    return actionSummaryLabels(actions.filter(isRecord), limit);
}

function previewActionLabel(action: SupportAutomationPreviewAction) {
    if (action.type === 'assign') return `Assign ${action.assigneeEmail || '-'}`;
    if (action.type === 'set_status') return `Set status ${action.statusValue || '-'}`;
    if (action.type === 'set_priority') return `Set priority ${action.priority || '-'}`;
    if (action.type === 'set_custom_fields') {
        const fields = isRecord(action.customFields) ? action.customFields : {};
        const labels = Object.entries(fields).map(([field, value]) => `${field}=${stringFrom(value)}`);
        return `Set fields ${shortValueList(labels)}`;
    }
    if (action.type === 'add_note') return 'Add note';
    if (action.type === 'queue_reply') {
        const label = action.approvalRequired ? 'Queue reply for approval' : 'Queue reply';
        const owner = actionOwnerEmail(action);
        const csat = action.includeFeedbackLink ? ' + CSAT' : '';
        return owner ? `${label} - ${owner}${csat}` : `${label}${csat}`;
    }
    if (action.type === 'prepare_agent_reply') {
        let label = action.createDraft ? 'Prepare agent draft' : 'Ask agent';
        if (actionAutoSendRequested(action)) label = 'Agent auto-send';
        if (actionAutoSendBlocked(action)) label = 'Agent auto-send blocked';
        return action.includeFeedbackLink ? `${label} + CSAT` : label;
    }
    if (action.type === 'prepare_triage') return action.approvalRequired ? 'Prepare triage approval' : 'Prepare triage';
    if (action.type === 'prepare_custom_fields') return action.approvalRequired ? 'Prepare field approval' : 'Prepare fields';
    if (action.type === 'record_action') return `Record ${action.label || action.actionKey || 'action'}`;
    return action.type || 'Action';
}

function previewSummaryBadges(summary: SupportAutomationPreviewSummary | undefined): Array<{ key: string; label: string; variant: 'secondary' | 'destructive' | 'outline' }> {
    if (!summary) return [];
    const badges: Array<{ key: string; label: string; variant: 'secondary' | 'destructive' | 'outline' }> = [];
    badges.push({ key: 'matched-actions', label: `${summary.matchedActions} actions`, variant: 'outline' });
    if (summary.approvalActions > 0) {
        badges.push({ key: 'approval-actions', label: `${summary.approvalActions} approvals`, variant: 'secondary' });
    }
    if (summary.directTicketMutations > 0) {
        badges.push({ key: 'direct-mutations', label: `${summary.directTicketMutations} direct changes`, variant: 'destructive' });
    }
    if (summary.customerReplyActions > 0) {
        badges.push({ key: 'customer-replies', label: `${summary.customerReplyActions} customer replies`, variant: 'outline' });
    }
    if (summary.autoSendActions > 0) {
        badges.push({ key: 'auto-send', label: `${summary.autoSendActions} auto-send`, variant: 'destructive' });
    }
    if (summary.autoSendBlocked > 0) {
        badges.push({ key: 'auto-send-blocked', label: `${summary.autoSendBlocked} blocked auto-send`, variant: 'outline' });
    }
    return badges;
}

function parseJsonObject(value: string): Record<string, unknown> | null {
    const parsed = JSON.parse(value) as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
    return parsed as Record<string, unknown>;
}

function formatJsonObject(value: Record<string, unknown>) {
    return JSON.stringify(value, null, 2);
}

function parseActionList(value: string): Array<Record<string, unknown>> | null {
    const parsed = JSON.parse(value) as unknown;
    if (!Array.isArray(parsed) || parsed.some(item => !item || typeof item !== 'object' || Array.isArray(item))) return null;
    return parsed as Array<Record<string, unknown>>;
}

function formatActionsJson(actions: Array<Record<string, unknown>>) {
    return JSON.stringify(actions, null, 2);
}

function listConditionValues(value: string): string[] {
    const values: string[] = [];
    const seen = new Set<string>();
    for (const item of value.replace(/\n/g, ',').split(',')) {
        const clean = item.trim();
        const key = clean.toLowerCase();
        if (!clean || seen.has(key)) continue;
        seen.add(key);
        values.push(clean);
    }
    return values;
}

export function Automations({ projectId }: AutomationsProps) {
    const { t } = useI18n();
    const navigate = useNavigate();
    const { tenantId } = useParams<{ tenantId: string }>();
    const [rules, setRules] = useState<SupportAutomationRule[]>([]);
    const [runs, setRuns] = useState<SupportAutomationRun[]>([]);
    const [projectMembers, setProjectMembers] = useState<ProjectMember[]>([]);
    const [currentUserEmail, setCurrentUserEmail] = useState('');
    const [selectedId, setSelectedId] = useState('');
    const [loading, setLoading] = useState(false);
    const [saving, setSaving] = useState(false);
    const [running, setRunning] = useState(false);
    const [previewing, setPreviewing] = useState(false);
    const [runningSla, setRunningSla] = useState(false);
    const [runningBacklog, setRunningBacklog] = useState(false);
    const [settingUpHumanLoop, setSettingUpHumanLoop] = useState(false);
    const [name, setName] = useState('');
    const [active, setActive] = useState(true);
    const [trigger, setTrigger] = useState<SupportAutomationTrigger>('issue_created');
    const [conditionsJson, setConditionsJson] = useState(DEFAULT_CONDITIONS);
    const [actionsJson, setActionsJson] = useState(DEFAULT_ACTIONS);
    const [manualIssueId, setManualIssueId] = useState('');
    const [manualTrigger, setManualTrigger] = useState<SupportAutomationTrigger>('manual');
    const [automationPreview, setAutomationPreview] = useState<SupportAutomationPreviewResult | null>(null);
    const [backlogTrigger, setBacklogTrigger] = useState<SupportAutomationTrigger>('issue_created');
    const [backlogStatus, setBacklogStatus] = useState('open');
    const [backlogLimit, setBacklogLimit] = useState('25');
    const [backlogResult, setBacklogResult] = useState<SupportAutomationBacklogRunResult | null>(null);
    const [slaResult, setSlaResult] = useState<SupportSlaEscalationRun | null>(null);
    const [conditionBuilderType, setConditionBuilderType] = useState<ConditionBuilderType>('priorityIn');
    const [conditionBuilderValue, setConditionBuilderValue] = useState(DEFAULT_CONDITION_VALUES.priorityIn);
    const [conditionBuilderBool, setConditionBuilderBool] = useState(true);
    const [builderType, setBuilderType] = useState<ActionBuilderType>('assign');
    const [builderAssigneeEmail, setBuilderAssigneeEmail] = useState('');
    const [builderStatus, setBuilderStatus] = useState('ongoing');
    const [builderPriority, setBuilderPriority] = useState('urgent');
    const [builderBody, setBuilderBody] = useState(DEFAULT_QUEUE_REPLY_BODY);
    const [builderQuestion, setBuilderQuestion] = useState(DEFAULT_AGENT_QUESTION);
    const [builderCustomFields, setBuilderCustomFields] = useState(DEFAULT_CONDITION_VALUES.customFields);
    const [builderApprovalRequired, setBuilderApprovalRequired] = useState(true);
    const [builderCreateDraft, setBuilderCreateDraft] = useState(true);
    const [builderIncludeFeedbackLink, setBuilderIncludeFeedbackLink] = useState(true);
    const [builderAutoSend, setBuilderAutoSend] = useState(false);

    const selectedRule = useMemo(
        () => rules.find(rule => rule.id === selectedId) ?? null,
        [rules, selectedId],
    );

    const assignmentCandidates = useMemo(() => {
        const emails = new Set<string>();
        if (currentUserEmail) emails.add(currentUserEmail);
        for (const member of projectMembers) {
            if (member.email) emails.add(member.email);
        }
        return [...emails].sort((a, b) => a.localeCompare(b));
    }, [currentUserEmail, projectMembers]);

    const automationAssignee = currentUserEmail || assignmentCandidates[0] || DEFAULT_ASSIGNEE;
    const currentConditionSummary = useMemo(() => {
        try {
            const conditions = parseJsonObject(conditionsJson);
            return conditions ? conditionSummaryLabels(conditions, 6) : ['Invalid conditions'];
        } catch {
            return ['Invalid conditions'];
        }
    }, [conditionsJson]);
    const currentActionSummary = useMemo(() => {
        try {
            const actions = parseActionList(actionsJson);
            return actions ? actionSummaryLabels(actions, 6) : ['Invalid actions'];
        } catch {
            return ['Invalid actions'];
        }
    }, [actionsJson]);
    const automationOpsSummary = useMemo(() => {
        const activeRules = rules.filter(rule => rule.active);
        const humanLoopRules = activeRules.filter(rule => ruleHasHumanLoopAgentDraft(rule));
        const autopilotRules = activeRules.filter(rule => ruleHasAutopilotPackage(rule));
        const autoSendRules = activeRules.filter(rule => ruleHasAction(rule, actionAutoSendRequested));
        const immediateChangeRules = activeRules.filter(rule => ruleHasAction(rule, actionChangesTicketWithoutApproval));
        const failedRuns = runs.filter(automationRunFailed);
        const recentRun = runs
            .slice()
            .sort((a, b) => Date.parse(b.startedAt || b.created || '') - Date.parse(a.startedAt || a.created || ''))[0] ?? null;
        let nextAction = 'Review workflow rule health';
        let nextDetail = 'Check active rules, recent failures, and approval policy before enabling more rules.';
        if (activeRules.length === 0) {
            nextAction = 'Create approval workflow';
            nextDetail = 'Start with an issue_created rule that assigns, prepares triage, extracts fields, and drafts for approval.';
        } else if (humanLoopRules.length === 0) {
            nextAction = 'Require editor approval';
            nextDetail = 'Launch readiness needs an active agent draft rule that creates approval-required work.';
        } else if (failedRuns.length > 0) {
            nextAction = 'Repair failed workflow runs';
            nextDetail = failedRuns[0]?.error || 'Open run history, inspect the failed run, and rerun after fixing inputs.';
        } else if (immediateChangeRules.length > 0 || autoSendRules.length > 0) {
            nextAction = 'Audit no-approval rule';
            nextDetail = 'Auto-send or immediate ticket changes should be deliberate and visible to reviewers.';
        } else if (autopilotRules.length === 0) {
            nextAction = 'Complete AI prep rule';
            nextDetail = 'Add triage, field preparation, and approval-ready agent draft actions to one active rule.';
        } else {
            nextAction = 'Ready for approval queue';
            nextDetail = 'Human-in-loop workflow exists. Watch Inbox approvals and run backlog when ready.';
        }
        return {
            activeRules,
            humanLoopRules,
            autopilotRules,
            autoSendRules,
            immediateChangeRules,
            failedRuns,
            recentRun,
            nextAction,
            nextDetail,
        };
    }, [rules, runs]);
    const builderUsesApprovalPolicy = builderType === 'queue_reply' || builderType === 'prepare_agent_reply' || builderType === 'prepare_triage' || builderType === 'prepare_custom_fields';
    const builderApprovalPolicy: ApprovalPolicy = builderApprovalRequired ? 'approval_required' : 'no_approval';

    const setBuilderApprovalPolicy = (value: ApprovalPolicy) => {
        const requiresApproval = value === 'approval_required';
        setBuilderApprovalRequired(requiresApproval);
        if (requiresApproval) {
            setBuilderAutoSend(false);
        }
    };

    const loadRules = useCallback(() => {
        setLoading(true);
        void api.getAutomationRules(projectId).then((res) => {
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not load workflow rules'));
                return;
            }
            setRules(res.data.items);
        }).finally(() => setLoading(false));
    }, [projectId, t]);

    const loadRuns = useCallback((ruleId = '') => {
        void api.getAutomationRuns(projectId, ruleId).then((res) => {
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not load workflow runs'));
                return;
            }
            setRuns(res.data.items);
        });
    }, [projectId, t]);

    useEffect(() => {
        const timer = window.setTimeout(() => loadRules(), 0);
        return () => window.clearTimeout(timer);
    }, [loadRules]);

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

    useEffect(() => {
        const timer = window.setTimeout(() => loadRuns(selectedRule?.id ?? ''), 0);
        return () => window.clearTimeout(timer);
    }, [loadRuns, selectedRule?.id]);

    useEffect(() => {
        const timer = window.setTimeout(() => {
            if (!selectedRule) {
                setName('');
                setActive(true);
                setTrigger('issue_created');
                setConditionsJson(DEFAULT_CONDITIONS);
                setActionsJson(defaultActionsJson(automationAssignee));
                return;
            }
            setName(selectedRule.name);
            setActive(selectedRule.active);
            setTrigger((selectedRule.trigger || 'issue_created') as SupportAutomationTrigger);
            setConditionsJson(JSON.stringify(selectedRule.conditions || {}, null, 2));
            setActionsJson(JSON.stringify(selectedRule.actions || [], null, 2));
        }, 0);
        return () => window.clearTimeout(timer);
    }, [automationAssignee, selectedRule]);

    const startNew = () => {
        setSelectedId('');
        setName('');
        setActive(true);
        setTrigger('issue_created');
        setConditionsJson(DEFAULT_CONDITIONS);
        setActionsJson(defaultActionsJson(automationAssignee));
    };

    const applyActionTemplate = (actions: Array<Record<string, unknown>>) => {
        setActionsJson(formatActionsJson(actions.map((action) => {
            const nextAction = { ...action };
            if (nextAction.assigneeEmail === DEFAULT_ASSIGNEE) {
                nextAction.assigneeEmail = automationAssignee;
            }
            if (nextAction.ownerEmail === DEFAULT_ASSIGNEE) {
                nextAction.ownerEmail = automationAssignee;
            }
            if (nextAction.reviewerEmail === DEFAULT_ASSIGNEE) {
                nextAction.reviewerEmail = automationAssignee;
            }
            return nextAction;
        })));
    };

    const changeConditionBuilderType = (value: ConditionBuilderType) => {
        setConditionBuilderType(value);
        setConditionBuilderValue(DEFAULT_CONDITION_VALUES[value]);
    };

    const buildStructuredCondition = (): Record<string, unknown> | null => {
        if (conditionBuilderType === 'unassigned' || conditionBuilderType === 'requiresHuman') {
            return { [conditionBuilderType]: conditionBuilderBool };
        }
        if (conditionBuilderType === 'customFields') {
            const fields = keyValueObjectFrom(conditionBuilderValue);
            if (Object.keys(fields).length === 0) {
                toast.error(t('Use key=value pairs for ticket fields'));
                return null;
            }
            return { customFields: fields };
        }
        if (conditionBuilderType.endsWith('In') || conditionBuilderType === 'tagsAny') {
            const values = listConditionValues(conditionBuilderValue);
            if (values.length === 0) {
                toast.error(t('Condition values required'));
                return null;
            }
            return { [conditionBuilderType]: values };
        }
        const value = conditionBuilderValue.trim();
        if (!value) {
            toast.error(t('Condition value required'));
            return null;
        }
        return { [conditionBuilderType]: value };
    };

    const appendStructuredCondition = () => {
        let conditions: Record<string, unknown> | null;
        try {
            conditions = parseJsonObject(conditionsJson);
        } catch {
            toast.error(t('Invalid JSON'));
            return;
        }
        if (!conditions) {
            toast.error(t('Conditions must be a JSON object'));
            return;
        }
        const condition = buildStructuredCondition();
        if (!condition) return;
        setConditionsJson(formatJsonObject({ ...conditions, ...condition }));
    };

    const buildStructuredAction = (): Record<string, unknown> | null => {
        const ownerEmail = builderAssigneeEmail.trim() || automationAssignee;
        if (builderType === 'assign') {
            return { type: 'assign', assigneeEmail: ownerEmail };
        }
        if (builderType === 'queue_reply') {
            const body = builderBody.trim();
            if (!body) {
                toast.error(t('Reply body required'));
                return null;
            }
            return {
                type: 'queue_reply',
                body,
                approvalRequired: builderApprovalRequired,
                includeFeedbackLink: builderIncludeFeedbackLink,
                assigneeEmail: ownerEmail,
            };
        }
        if (builderType === 'prepare_agent_reply') {
            const question = builderQuestion.trim();
            if (!question) {
                toast.error(t('Question required'));
                return null;
            }
            const agentAutoSend = !builderApprovalRequired && builderAutoSend;
            return {
                type: 'prepare_agent_reply',
                question,
                createDraft: builderCreateDraft || agentAutoSend,
                approvalRequired: builderApprovalRequired,
                autoSend: agentAutoSend,
                includeFeedbackLink: (builderCreateDraft || agentAutoSend) && builderIncludeFeedbackLink,
            };
        }
        if (builderType === 'prepare_custom_fields') {
            return {
                type: 'prepare_custom_fields',
                approvalRequired: builderApprovalRequired,
                onlyMissing: true,
            };
        }
        if (builderType === 'prepare_triage') {
            return {
                type: 'prepare_triage',
                approvalRequired: builderApprovalRequired,
            };
        }
        if (builderType === 'set_priority') {
            return { type: 'set_priority', priority: builderPriority };
        }
        if (builderType === 'set_status') {
            return { type: 'set_status', status: builderStatus };
        }
        if (builderType === 'set_custom_fields') {
            const fields = keyValueObjectFrom(builderCustomFields);
            if (Object.keys(fields).length === 0) {
                toast.error(t('Use key=value pairs for ticket fields'));
                return null;
            }
            return { type: 'set_custom_fields', customFields: fields };
        }
        const body = builderBody.trim();
        if (!body) {
            toast.error(t('Note body required'));
            return null;
        }
        return { type: 'add_note', body };
    };

    const appendStructuredAction = () => {
        let actions: Array<Record<string, unknown>> | null;
        try {
            actions = parseActionList(actionsJson);
        } catch {
            toast.error(t('Invalid JSON'));
            return;
        }
        if (!actions) {
            toast.error(t('Actions must be a JSON array'));
            return;
        }
        const action = buildStructuredAction();
        if (!action) return;
        setActionsJson(formatActionsJson([...actions, action]));
    };

    const applyAutopilotRecipe = () => {
        setActive(true);
        setName(name.trim() || t('Human-in-loop AI prep'));
        setTrigger('issue_created');
        setConditionsJson(autopilotConditionsJson());
        setActionsJson(autopilotActionsJson(automationAssignee));
    };

    const applySlaRecipe = () => {
        setActive(true);
        setName(name.trim() || t('SLA breach escalation'));
        setTrigger('sla_breached');
        setConditionsJson(JSON.stringify({}, null, 2));
        setActionsJson(JSON.stringify([
            {
                type: 'assign',
                assigneeEmail: automationAssignee,
            },
            {
                type: 'set_priority',
                priority: 'urgent',
            },
            {
                type: 'add_note',
                body: 'SLA breached. Review owner, customer reply, and resolution path.',
            },
            {
                type: 'prepare_agent_reply',
                question: 'Draft an urgent, approval-ready customer update for this SLA breach using the ticket context and knowledge base.',
                createDraft: true,
                includeFeedbackLink: true,
            },
        ], null, 2));
    };

    const saveRule = async () => {
        let conditions: Record<string, unknown> | null;
        let actions: Array<Record<string, unknown>> | null;
        try {
            conditions = parseJsonObject(conditionsJson);
            actions = parseActionList(actionsJson);
        } catch {
            toast.error(t('Invalid JSON'));
            return;
        }
        if (!conditions) {
            toast.error(t('Conditions must be a JSON object'));
            return;
        }
        if (!actions || actions.length === 0) {
            toast.error(t('Actions must be a non-empty JSON array'));
            return;
        }
        setSaving(true);
        const res = await api.saveAutomationRule(projectId, {
            id: selectedRule?.id,
            name,
            active,
            trigger,
            conditions,
            actions,
        });
        setSaving(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not save workflow rule'));
            return;
        }
        toast.success(t('Saved'));
        setSelectedId(res.data.id);
        loadRules();
        loadRuns(res.data.id);
    };

    const runManual = async () => {
        const issueId = manualIssueId.trim();
        if (!issueId) {
            toast.error(t('Issue ID required'));
            return;
        }
        setAutomationPreview(null);
        setRunning(true);
        const res = await api.runAutomations(projectId, issueId, manualTrigger);
        setRunning(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not run workflow rule'));
            return;
        }
        toast.success(`${res.data.processed} ${t('processed')}, ${res.data.failed} ${t('failed')}`);
        loadRuns(selectedRule?.id ?? '');
    };

    const previewManual = async () => {
        const issueId = manualIssueId.trim();
        if (!issueId) {
            toast.error(t('Issue ID required'));
            return;
        }
        let conditions: Record<string, unknown> | null;
        let actions: Array<Record<string, unknown>> | null;
        try {
            conditions = parseJsonObject(conditionsJson);
            actions = parseActionList(actionsJson);
        } catch {
            toast.error(t('Invalid JSON'));
            return;
        }
        if (!conditions) {
            toast.error(t('Conditions must be a JSON object'));
            return;
        }
        if (!actions || actions.length === 0) {
            toast.error(t('Actions must be a non-empty JSON array'));
            return;
        }
        setPreviewing(true);
        const res = await api.previewAutomations(projectId, issueId, manualTrigger, {
            id: selectedRule?.id || '__current_draft__',
            name: name.trim() || t('Current draft'),
            active,
            trigger: manualTrigger,
            conditions,
            actions,
        });
        setPreviewing(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not preview workflow rule'));
            return;
        }
        setAutomationPreview(res.data);
        toast.success(`${res.data.matched}/${res.data.rules} ${t('matched')}`);
    };

    const runBacklog = async () => {
        const parsedLimit = Number.parseInt(backlogLimit, 10);
        const limit = Number.isFinite(parsedLimit) ? Math.max(1, Math.min(parsedLimit, 100)) : 25;
        setBacklogResult(null);
        setRunningBacklog(true);
        const res = await api.runAutomationBacklog(projectId, {
            trigger: backlogTrigger,
            status: backlogStatus,
            limit,
        });
        setRunningBacklog(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not run workflow rule'));
            return;
        }
        setBacklogResult(res.data);
        setBacklogLimit(String(limit));
        toast.success(`${res.data.processed} ${t('tickets')}, ${res.data.runs} ${t('runs')}`);
        loadRuns(selectedRule?.id ?? '');
    };

    const setupHumanLoopAutomation = async () => {
        setSettingUpHumanLoop(true);
        const res = await api.setupHumanLoopAutomation(projectId);
        setSettingUpHumanLoop(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not set up human-in-loop workflow'));
            return;
        }
        const setup = res.data;
        setRules((previous) => {
            const nextRule = setup.rule;
            return previous.some(rule => rule.id === nextRule.id)
                ? previous.map(rule => rule.id === nextRule.id ? nextRule : rule)
                : [nextRule, ...previous];
        });
        setSelectedId(setup.rule.id);
        loadRules();
        loadRuns(setup.rule.id);
        toast.success(setup.createdRule
            ? t('Approval workflow created')
            : t('Approval workflow verified'));
    };

    const runSlaScan = async () => {
        setSlaResult(null);
        setRunningSla(true);
        const res = await api.runSlaEscalations(projectId);
        setRunningSla(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not run SLA scan'));
            return;
        }
        setSlaResult(res.data);
        toast.success(`${res.data.escalated} ${t('escalated')}, ${res.data.skipped} ${t('skipped')}`);
        loadRuns(selectedRule?.id ?? '');
    };

    const openTicket = (issueId: string) => {
        if (!tenantId || !issueId) return;
        void navigate(`/${tenantId}/${projectId}/inbox/${issueId}`);
    };

    return (
        <div className="flex min-h-0 flex-1 overflow-hidden rounded-md border bg-background">
            <aside className="flex w-[24rem] shrink-0 flex-col border-r">
                <div className="flex items-center justify-between gap-3 border-b p-4">
                    <div>
                        <h2 className="text-base font-semibold">{t('Workflow rules')}</h2>
                        <p className="text-xs text-muted-foreground">{rules.length} {t('rules')}</p>
                    </div>
                    <Button size="sm" variant="outline" onClick={startNew}>
                        <Plus className="size-4" />
                        {t('New')}
                    </Button>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto">
                    {loading ? (
                        <div className="flex h-full items-center justify-center text-muted-foreground">
                            <Loader className="mr-2 size-4 animate-spin" />
                            {t('Loading')}
                        </div>
                    ) : rules.length === 0 ? (
                        <div className="flex h-full items-center justify-center text-muted-foreground">{t('No workflow rules')}</div>
                    ) : (
                        rules.map((rule) => {
                            const conditionLabels = conditionSummaryLabels(rule.conditions || {}, 3);
                            const actionLabels = actionSummaryLabels(rule.actions || [], 3);
                            return (
                                <button
                                    key={rule.id}
                                    type="button"
                                    className={[
                                        'w-full border-b px-4 py-3 text-left transition-colors',
                                        rule.id === selectedId ? 'bg-muted/60' : 'bg-background hover:bg-muted/40',
                                    ].join(' ')}
                                    onClick={() => setSelectedId(rule.id)}
                                >
                                    <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
                                        <span className="truncate text-sm font-medium">{rule.name}</span>
                                        <Badge variant="outline" className="font-normal">
                                            {rule.active ? t('Active') : t('Paused')}
                                        </Badge>
                                    </div>
                                    <div className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
                                        <Workflow className="size-3.5 shrink-0" />
                                        <span>{t(triggerLabel(rule.trigger))}</span>
                                        <span className="truncate">{formatTime(rule.lastRunAt)}</span>
                                    </div>
                                    <div className="mt-2 flex flex-wrap gap-1.5">
                                        {conditionLabels.map((label, index) => (
                                            <Badge key={`condition:${index}:${label}`} variant="outline" className="max-w-full truncate font-normal">
                                                {t(label)}
                                            </Badge>
                                        ))}
                                        {actionLabels.map((label, index) => (
                                            <Badge key={`action:${index}:${label}`} variant="secondary" className="max-w-full truncate font-normal">
                                                {t(label)}
                                            </Badge>
                                        ))}
                                    </div>
                                </button>
                            );
                        })
                    )}
                </div>
            </aside>

            <section className="min-w-0 flex-1 overflow-y-auto">
                <div className="mx-auto max-w-3xl space-y-4 px-6 py-5">
                    <section data-automation-operations className="rounded-md border p-4">
                        <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                            <div className="min-w-0">
                                <div className="flex min-w-0 items-center gap-2 text-sm font-medium">
                                    <Sparkles className="size-4 text-muted-foreground" />
                                    <span className="truncate">{t('Workflow rule operations')}</span>
                                </div>
                                <p className="mt-1 text-xs text-muted-foreground">
                                    {t('Human-in-loop agent readiness, failure recovery, and auto-send policy.')}
                                </p>
                            </div>
                            <Badge
                                variant={automationOpsSummary.failedRuns.length > 0 || automationOpsSummary.humanLoopRules.length === 0 ? 'destructive' : 'secondary'}
                                className="font-normal"
                            >
                                {automationOpsSummary.failedRuns.length > 0
                                    ? `${automationOpsSummary.failedRuns.length} ${t('failed')}`
                                    : automationOpsSummary.humanLoopRules.length === 0
                                        ? t('Needs setup')
                                        : t('Human in loop')}
                            </Badge>
                        </div>
                        <div className="grid gap-2 sm:grid-cols-4">
                            <div className="rounded-md border bg-muted/20 p-2 text-xs">
                                <div className="font-medium">{automationOpsSummary.activeRules.length}</div>
                                <div className="text-muted-foreground">{t('active rules')}</div>
                            </div>
                            <div className="rounded-md border bg-muted/20 p-2 text-xs">
                                <div className="font-medium">{automationOpsSummary.humanLoopRules.length}</div>
                                <div className="text-muted-foreground">{t('approval agents')}</div>
                            </div>
                            <div className="rounded-md border bg-muted/20 p-2 text-xs">
                                <div className="font-medium">{automationOpsSummary.autoSendRules.length}</div>
                                <div className="text-muted-foreground">{t('auto-send rules')}</div>
                            </div>
                            <div className="rounded-md border bg-muted/20 p-2 text-xs">
                                <div className="font-medium">{automationOpsSummary.failedRuns.length}</div>
                                <div className="text-muted-foreground">{t('failed runs')}</div>
                            </div>
                        </div>
                        <div data-automation-next-action className="mt-3 rounded-md border bg-muted/20 p-3">
                            <div className="mb-2 flex flex-wrap items-start justify-between gap-3">
                                <div className="min-w-0">
                                    <div className="truncate text-sm font-medium">{t(automationOpsSummary.nextAction)}</div>
                                    <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                                        {t(automationOpsSummary.nextDetail)}
                                    </div>
                                </div>
                                {automationOpsSummary.recentRun && (
                                    <Badge variant={automationRunFailed(automationOpsSummary.recentRun) ? 'destructive' : 'outline'} className="shrink-0 font-normal">
                                        {automationOpsSummary.recentRun.status}
                                    </Badge>
                                )}
                            </div>
                            <div className="flex flex-wrap justify-end gap-2">
                                <Button
                                    type="button"
                                    size="sm"
                                    onClick={() => void setupHumanLoopAutomation()}
                                    disabled={settingUpHumanLoop}
                                    data-automation-setup-human-loop
                                >
                                    {settingUpHumanLoop ? <Loader className="size-3.5 animate-spin" /> : <Sparkles className="size-3.5" />}
                                    {automationOpsSummary.humanLoopRules.length === 0
                                        ? t('Create approval rule')
                                        : t('Verify approval rule')}
                                </Button>
                                <Button type="button" size="sm" variant="outline" onClick={applyAutopilotRecipe}>
                                    <Sparkles className="size-3.5" />
                                    {t('Apply approval recipe')}
                                </Button>
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    onClick={() => tenantId && navigate(`/${tenantId}/${projectId}/inbox?filter=approvals`)}
                                    disabled={!tenantId}
                                >
                                    <CheckCircle2 className="size-3.5" />
                                    {t('Open approvals')}
                                </Button>
                                <Button type="button" size="sm" onClick={() => void runBacklog()} disabled={runningBacklog}>
                                    {runningBacklog ? <Loader className="size-3.5 animate-spin" /> : <Play className="size-3.5" />}
                                    {t('Run backlog')}
                                </Button>
                            </div>
                        </div>
                    </section>
                    <div className="flex items-start justify-between gap-3">
                        <div>
                            <h1 className="text-xl font-semibold">{selectedRule ? t('Workflow rule') : t('New workflow rule')}</h1>
                            {selectedRule && (
                                <p className="text-sm text-muted-foreground">{formatTime(selectedRule.lastRunAt)}</p>
                            )}
                        </div>
                        <div className="flex items-center gap-2">
                            <Label htmlFor="automation-active" className="text-sm">{t('Active')}</Label>
                            <Switch id="automation-active" checked={active} onCheckedChange={setActive} />
                        </div>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-[1fr_14rem]">
                        <div className="space-y-1.5">
                            <Label htmlFor="automation-name">{t('Name')}</Label>
                            <Input id="automation-name" value={name} onChange={event => setName(event.target.value)} />
                        </div>
                        <div className="space-y-1.5">
                            <Label>{t('Trigger')}</Label>
                            <Select value={trigger} onValueChange={value => setTrigger(value as SupportAutomationTrigger)}>
                                <SelectTrigger>
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {automationTriggerOptions.map(option => (
                                        <SelectItem key={option.value} value={option.value}>{t(option.label)}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                    </div>
                    <section className="rounded-md border bg-muted/20 p-3">
                        <div className="grid gap-3 md:grid-cols-2">
                            <div>
                                <div className="mb-2 text-xs font-medium uppercase text-muted-foreground">{t('Conditions')}</div>
                                <div className="flex flex-wrap gap-1.5">
                                    {currentConditionSummary.map((label, index) => (
                                        <Badge key={`current-condition:${index}:${label}`} variant="outline" className="font-normal">
                                            {t(label)}
                                        </Badge>
                                    ))}
                                </div>
                            </div>
                            <div>
                                <div className="mb-2 text-xs font-medium uppercase text-muted-foreground">{t('Actions')}</div>
                                <div className="flex flex-wrap gap-1.5">
                                    {currentActionSummary.map((label, index) => (
                                        <Badge key={`current-action:${index}:${label}`} variant="secondary" className="font-normal">
                                            {t(label)}
                                        </Badge>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </section>
                    <div className="space-y-1.5">
                        <Label htmlFor="automation-conditions">{t('Conditions')}</Label>
                        <section className="rounded-md border bg-muted/20 p-3">
                            <div className="grid gap-3 md:grid-cols-[12rem_1fr_auto]">
                                <div className="space-y-1.5">
                                    <Label>{t('Condition')}</Label>
                                    <Select value={conditionBuilderType} onValueChange={value => changeConditionBuilderType(value as ConditionBuilderType)}>
                                        <SelectTrigger id="automation-condition-builder-type">
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="priorityIn">{t('Priority')}</SelectItem>
                                            <SelectItem value="statusIn">{t('Status')}</SelectItem>
                                            <SelectItem value="channelIn">{t('Channel')}</SelectItem>
                                            <SelectItem value="tagsAny">{t('Tags')}</SelectItem>
                                            <SelectItem value="customFields">{t('Ticket fields')}</SelectItem>
                                            <SelectItem value="unassigned">{t('Unassigned')}</SelectItem>
                                            <SelectItem value="requiresHuman">{t('Needs human')}</SelectItem>
                                            <SelectItem value="activatedIntent">{t('Runbook')}</SelectItem>
                                            <SelectItem value="assigneeEmail">{t('Assignee')}</SelectItem>
                                        </SelectContent>
                                    </Select>
                                </div>

                                {(conditionBuilderType === 'unassigned' || conditionBuilderType === 'requiresHuman') ? (
                                    <div className="flex items-end">
                                        <label className="flex h-9 items-center gap-2 text-sm">
                                            <Switch checked={conditionBuilderBool} onCheckedChange={setConditionBuilderBool} />
                                            {conditionBuilderBool ? t('Yes') : t('No')}
                                        </label>
                                    </div>
                                ) : (
                                    <div className="space-y-1.5">
                                        <Label htmlFor="automation-condition-value">{t('Value')}</Label>
                                        <Input
                                            id="automation-condition-value"
                                            value={conditionBuilderValue}
                                            onChange={event => setConditionBuilderValue(event.target.value)}
                                            placeholder={conditionBuilderType === 'customFields' ? 'plan=Enterprise, seats=50' : undefined}
                                        />
                                    </div>
                                )}

                                <div className="flex items-end">
                                    <Button type="button" size="sm" variant="outline" onClick={appendStructuredCondition}>
                                        <Plus className="size-3.5" />
                                        {t('Add condition')}
                                    </Button>
                                </div>
                            </div>
                        </section>
                        <Textarea
                            id="automation-conditions"
                            data-automation-conditions-json
                            value={conditionsJson}
                            onChange={event => setConditionsJson(event.target.value)}
                            rows={8}
                            className="font-mono text-sm"
                        />
                    </div>
                    <div className="space-y-1.5">
                        <div className="flex items-center justify-between gap-2">
                            <Label htmlFor="automation-actions">{t('Actions')}</Label>
                            <div className="flex flex-wrap justify-end gap-1.5">
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    onClick={applyAutopilotRecipe}
                                >
                                    <Sparkles className="size-3.5" />
                                    {t('AI prep')}
                                </Button>
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    onClick={applySlaRecipe}
                                >
                                    <AlertTriangle className="size-3.5" />
                                    {t('SLA breach')}
                                </Button>
                                {ACTION_TEMPLATES.map(template => {
                                    const Icon = template.icon;
                                    return (
                                        <Button
                                            key={template.label}
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            onClick={() => applyActionTemplate(template.actions)}
                                        >
                                            <Icon className="size-3.5" />
                                            {t(template.label)}
                                        </Button>
                                    );
                                })}
                            </div>
                        </div>
                        <section className="rounded-md border bg-muted/20 p-3">
                            <div className="grid gap-3 md:grid-cols-[12rem_1fr]">
                                <div className="space-y-1.5">
                                    <Label>{t('Action')}</Label>
                                    <Select value={builderType} onValueChange={value => setBuilderType(value as ActionBuilderType)}>
                                        <SelectTrigger id="automation-action-builder-type">
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="assign">{t('Assign')}</SelectItem>
                                            <SelectItem value="queue_reply">{t('Queue reply')}</SelectItem>
                                            <SelectItem value="prepare_agent_reply">{t('Agent draft')}</SelectItem>
                                            <SelectItem value="prepare_triage">{t('Agent triage')}</SelectItem>
                                            <SelectItem value="prepare_custom_fields">{t('Agent fields')}</SelectItem>
                                            <SelectItem value="set_priority">{t('Set priority')}</SelectItem>
                                            <SelectItem value="set_status">{t('Set status')}</SelectItem>
                                            <SelectItem value="set_custom_fields">{t('Set ticket fields')}</SelectItem>
                                            <SelectItem value="add_note">{t('Add note')}</SelectItem>
                                        </SelectContent>
                                    </Select>
                                </div>

                                {(builderType === 'assign' || builderType === 'queue_reply') && (
                                    <div className="space-y-1.5">
                                        <Label htmlFor="automation-action-assignee">{t('Assignee')}</Label>
                                        <Input
                                            id="automation-action-assignee"
                                            type="email"
                                            value={builderAssigneeEmail}
                                            onChange={event => setBuilderAssigneeEmail(event.target.value)}
                                            placeholder={automationAssignee}
                                        />
                                    </div>
                                )}

                                {builderType === 'set_priority' && (
                                    <div className="space-y-1.5">
                                        <Label>{t('Priority')}</Label>
                                        <Select value={builderPriority} onValueChange={setBuilderPriority}>
                                            <SelectTrigger id="automation-action-priority">
                                                <SelectValue />
                                            </SelectTrigger>
                                            <SelectContent>
                                                <SelectItem value="urgent">{t('Urgent')}</SelectItem>
                                                <SelectItem value="high">{t('High')}</SelectItem>
                                                <SelectItem value="normal">{t('Normal')}</SelectItem>
                                                <SelectItem value="low">{t('Low')}</SelectItem>
                                            </SelectContent>
                                        </Select>
                                    </div>
                                )}

                                {builderType === 'set_status' && (
                                    <div className="space-y-1.5">
                                        <Label>{t('Status')}</Label>
                                        <Select value={builderStatus} onValueChange={setBuilderStatus}>
                                            <SelectTrigger id="automation-action-status">
                                                <SelectValue />
                                            </SelectTrigger>
                                            <SelectContent>
                                                <SelectItem value="open">{t('Open')}</SelectItem>
                                                <SelectItem value="ongoing">{t('Ongoing')}</SelectItem>
                                                <SelectItem value="done">{t('Done')}</SelectItem>
                                            </SelectContent>
                                        </Select>
                                    </div>
                                )}

                                {builderType === 'set_custom_fields' && (
                                    <div className="space-y-1.5 md:col-span-2">
                                        <Label htmlFor="automation-action-custom-fields">{t('Ticket fields')}</Label>
                                        <Textarea
                                            id="automation-action-custom-fields"
                                            value={builderCustomFields}
                                            onChange={event => setBuilderCustomFields(event.target.value)}
                                            placeholder="plan=Enterprise, seats=50"
                                            rows={3}
                                        />
                                    </div>
                                )}

                                {(builderType === 'queue_reply' || builderType === 'add_note') && (
                                    <div className="space-y-1.5 md:col-span-2">
                                        <Label htmlFor="automation-action-body">{builderType === 'queue_reply' ? t('Reply') : t('Note')}</Label>
                                        <Textarea
                                            id="automation-action-body"
                                            value={builderBody}
                                            onChange={event => setBuilderBody(event.target.value)}
                                            rows={3}
                                        />
                                    </div>
                                )}

                                {builderType === 'prepare_agent_reply' && (
                                    <div className="space-y-1.5 md:col-span-2">
                                        <Label htmlFor="automation-action-question">{t('Question')}</Label>
                                        <Textarea
                                            id="automation-action-question"
                                            value={builderQuestion}
                                            onChange={event => setBuilderQuestion(event.target.value)}
                                            rows={3}
                                        />
                                    </div>
                                )}

                                {builderUsesApprovalPolicy && (
                                    <div className="space-y-3 rounded-md border bg-background p-3 md:col-span-2">
                                        <div className="flex flex-wrap items-start justify-between gap-2">
                                            <div className="min-w-0">
                                                <div className="text-sm font-medium">{t('Human loop')}</div>
                                                <p className="text-xs text-muted-foreground">
                                                    {builderType === 'queue_reply'
                                                        ? t('Queued replies wait for approval before customer delivery.')
                                                        : builderType === 'prepare_agent_reply'
                                                            ? t('Agent replies are prepared for approval before customer delivery.')
                                                            : builderType === 'prepare_triage'
                                                                ? t('Agent triage waits for approval before changing tickets.')
                                                                : t('Agent field suggestions wait for approval before changing tickets.')}
                                                </p>
                                            </div>
                                            <Badge variant="outline" className="font-normal">
                                                {builderApprovalRequired ? t('Approval required') : t('No approval')}
                                            </Badge>
                                        </div>
                                        <RadioGroup
                                            value={builderApprovalPolicy}
                                            onValueChange={value => setBuilderApprovalPolicy(value as ApprovalPolicy)}
                                            className="grid gap-2 sm:grid-cols-2"
                                        >
                                            <label
                                                htmlFor="automation-approval-required"
                                                className={[
                                                    'flex cursor-pointer items-start gap-2 rounded-md border p-3 text-sm transition-colors',
                                                    builderApprovalRequired
                                                        ? 'border-primary bg-primary/5'
                                                        : 'bg-background hover:bg-muted/40',
                                                ].join(' ')}
                                            >
                                                <RadioGroupItem id="automation-approval-required" value="approval_required" className="mt-0.5" />
                                                <span className="min-w-0">
                                                    <span className="block font-medium">{t('Require approval')}</span>
                                                    <span className="block text-xs text-muted-foreground">
                                                        {t('Human approves before a customer-visible send.')}
                                                    </span>
                                                </span>
                                            </label>
                                            <label
                                                htmlFor="automation-no-approval"
                                                className={[
                                                    'flex cursor-pointer items-start gap-2 rounded-md border p-3 text-sm transition-colors',
                                                    !builderApprovalRequired
                                                        ? 'border-primary bg-primary/5'
                                                        : 'bg-background hover:bg-muted/40',
                                                ].join(' ')}
                                            >
                                                <RadioGroupItem id="automation-no-approval" value="no_approval" className="mt-0.5" />
                                                <span className="min-w-0">
                                                    <span className="block font-medium">{t('No approval')}</span>
                                                    <span className="block text-xs text-muted-foreground">
                                                        {builderType === 'prepare_custom_fields'
                                                            ? t('Workflow rule may change ticket fields immediately.')
                                                            : builderType === 'prepare_triage'
                                                                ? t('Workflow rule may triage tickets immediately.')
                                                            : t('Workflow rule may send when auto-send is enabled.')}
                                                    </span>
                                                </span>
                                            </label>
                                        </RadioGroup>
                                        {builderType === 'prepare_agent_reply' && builderApprovalRequired && (
                                            <p className="text-xs text-muted-foreground">
                                                {t('Auto-send disabled while approval is required.')}
                                            </p>
                                        )}
                                    </div>
                                )}

                                <div className="flex flex-wrap items-center justify-between gap-3 md:col-span-2">
                                    <div className="flex flex-wrap items-center gap-4">
                                        {builderType === 'prepare_agent_reply' && (
                                            <label className="flex items-center gap-2 text-sm">
                                                <Switch
                                                    checked={builderCreateDraft}
                                                    onCheckedChange={(checked) => {
                                                        setBuilderCreateDraft(checked);
                                                        if (!checked) setBuilderAutoSend(false);
                                                    }}
                                                />
                                                {t('Draft')}
                                            </label>
                                        )}
                                        {builderType === 'prepare_agent_reply' && (
                                            <label className="flex items-center gap-2 text-sm">
                                                <Switch
                                                    checked={!builderApprovalRequired && builderAutoSend}
                                                    onCheckedChange={(checked) => {
                                                        setBuilderAutoSend(checked);
                                                        if (checked) {
                                                            setBuilderCreateDraft(true);
                                                            setBuilderApprovalRequired(false);
                                                        }
                                                    }}
                                                    disabled={builderApprovalRequired || !builderCreateDraft}
                                                />
                                                {t('Auto-send')}
                                            </label>
                                        )}
                                        {(builderType === 'queue_reply' || builderType === 'prepare_agent_reply') && (
                                            <label className="flex items-center gap-2 text-sm">
                                                <Switch
                                                    checked={builderIncludeFeedbackLink}
                                                    onCheckedChange={setBuilderIncludeFeedbackLink}
                                                    disabled={builderType === 'prepare_agent_reply' && !builderCreateDraft && !builderAutoSend}
                                                />
                                                {t('CSAT link')}
                                            </label>
                                        )}
                                    </div>
                                    <Button type="button" size="sm" variant="outline" onClick={appendStructuredAction}>
                                        <Plus className="size-3.5" />
                                        {t('Add action')}
                                    </Button>
                                </div>
                            </div>
                        </section>
                        <Textarea
                            id="automation-actions"
                            data-automation-actions-json
                            value={actionsJson}
                            onChange={event => setActionsJson(event.target.value)}
                            rows={10}
                            className="font-mono text-sm"
                        />
                    </div>
                    <section className="rounded-md border p-4">
                        <div className="mb-3 flex items-center justify-between gap-2">
                            <h2 className="text-sm font-medium">{t('Manual run')}</h2>
                            <div className="flex items-center gap-2">
                                <Button size="sm" variant="outline" data-automation-preview-run onClick={() => void previewManual()} disabled={previewing || running}>
                                    {previewing ? <Loader className="size-4 animate-spin" /> : <Workflow className="size-4" />}
                                    {t('Preview')}
                                </Button>
                                <Button size="sm" variant="outline" onClick={() => void runManual()} disabled={running || previewing}>
                                    {running ? <Loader className="size-4 animate-spin" /> : <Play className="size-4" />}
                                    {t('Run')}
                                </Button>
                            </div>
                        </div>
                        <div className="grid gap-3 sm:grid-cols-[1fr_14rem]">
                            <div className="space-y-1.5">
                                <Label htmlFor="manual-issue-id">{t('Issue ID')}</Label>
                                <Input
                                    id="manual-issue-id"
                                    data-automation-manual-issue
                                    value={manualIssueId}
                                    onChange={(event) => {
                                        setManualIssueId(event.target.value);
                                        setAutomationPreview(null);
                                    }}
                                />
                            </div>
                            <div className="space-y-1.5">
                                <Label>{t('Trigger')}</Label>
                                <Select value={manualTrigger} onValueChange={(value) => {
                                    setManualTrigger(value as SupportAutomationTrigger);
                                    setAutomationPreview(null);
                                }}>
                                    <SelectTrigger>
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {automationTriggerOptions.map(option => (
                                            <SelectItem key={option.value} value={option.value}>{t(option.label)}</SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                        </div>
                        {automationPreview && (
                            <div data-automation-preview className="mt-3 rounded-md border bg-muted/20 p-3">
                                <div className="mb-3 flex items-center justify-between gap-2">
                                    <div className="min-w-0">
                                        <div className="text-sm font-medium">{t('Preview')}</div>
                                        <div className="truncate text-xs text-muted-foreground">
                                            {automationPreview.issueId} - {t(triggerLabel(automationPreview.trigger))}
                                        </div>
                                    </div>
                                    <Badge variant="outline" className="shrink-0 font-normal">
                                        {automationPreview.matched}/{automationPreview.rules} {t('matched')}
                                    </Badge>
                                </div>
                                <div className="mb-3 flex flex-wrap gap-1.5">
                                    {previewSummaryBadges(automationPreview.summary).map(badge => (
                                        <Badge key={badge.key} data-automation-preview-badge={badge.key} variant={badge.variant} className="font-normal">
                                            {badge.label}
                                        </Badge>
                                    ))}
                                </div>
                                {(automationPreview.summary?.warnings ?? []).length > 0 && (
                                    <div className="mb-3 space-y-1.5">
                                        {(automationPreview.summary?.warnings ?? []).map(warning => (
                                            <div
                                                key={warning.key}
                                                data-automation-preview-warning={warning.key}
                                                className="rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-2 text-xs"
                                            >
                                                <div className="flex items-center justify-between gap-2">
                                                    <span className="font-medium text-destructive">{t(warning.label)}</span>
                                                    <Badge variant="destructive" className="font-normal">{warning.count}</Badge>
                                                </div>
                                                <div className="mt-1 text-muted-foreground">{t(warning.detail)}</div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                                {automationPreview.items.length === 0 ? (
                                    <div className="text-sm text-muted-foreground">{t('No rules for this trigger')}</div>
                                ) : (
                                    <div className="space-y-2">
                                        {automationPreview.items.map(item => (
                                            <div
                                                key={item.rule.id}
                                                className={[
                                                    'rounded-md border bg-background p-2 text-sm',
                                                    item.matched ? 'border-primary/40' : 'opacity-70',
                                                ].join(' ')}
                                            >
                                                <div className="flex items-center justify-between gap-2">
                                                    <div className="min-w-0">
                                                        <div className="truncate font-medium">{item.rule.name}</div>
                                                        <div className="truncate text-xs text-muted-foreground">
                                                            {JSON.stringify(item.conditions)}
                                                        </div>
                                                    </div>
                                                    <Badge variant="outline" className="shrink-0 font-normal">
                                                        {item.matched ? t('Match') : t('Skip')}
                                                    </Badge>
                                                </div>
                                                <div className="mt-2 flex flex-wrap gap-1.5">
                                                    {item.actions.length === 0 ? (
                                                        <span className="text-xs text-muted-foreground">{t('No actions')}</span>
                                                    ) : item.actions.map((action, index) => (
                                                        <Badge
                                                            key={`${item.rule.id}-${action.type}-${index}`}
                                                            data-automation-preview-action={action.type}
                                                            data-automation-preview-action-effect={action.effect}
                                                            variant={action.ungated ? 'destructive' : action.createsApprovalWork ? 'secondary' : 'outline'}
                                                            className="font-normal"
                                                        >
                                                            {previewActionLabel(action)}
                                                        </Badge>
                                                    ))}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}
                        <div className="mt-4 border-t pt-4">
                            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                                <div>
                                    <h3 className="text-sm font-medium">{t('Backlog run')}</h3>
                                    <p className="text-xs text-muted-foreground">{t('Run active automation rules across existing tickets.')}</p>
                                </div>
                                <Button size="sm" variant="outline" onClick={() => void runBacklog()} disabled={runningBacklog}>
                                    {runningBacklog ? <Loader className="size-4 animate-spin" /> : <Play className="size-4" />}
                                    {t('Run backlog')}
                                </Button>
                            </div>
                            <div className="grid gap-3 sm:grid-cols-[1fr_1fr_8rem]">
                                <div className="space-y-1.5">
                                    <Label>{t('Trigger')}</Label>
                                    <Select value={backlogTrigger} onValueChange={(value) => {
                                        setBacklogTrigger(value as SupportAutomationTrigger);
                                        setBacklogResult(null);
                                    }}>
                                        <SelectTrigger>
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {automationTriggerOptions.map(option => (
                                                <SelectItem key={option.value} value={option.value}>{t(option.label)}</SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div className="space-y-1.5">
                                    <Label>{t('Status')}</Label>
                                    <Select value={backlogStatus} onValueChange={(value) => {
                                        setBacklogStatus(value);
                                        setBacklogResult(null);
                                    }}>
                                        <SelectTrigger>
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="open">{t('Open')}</SelectItem>
                                            <SelectItem value="ongoing">{t('Ongoing')}</SelectItem>
                                            <SelectItem value="all">{t('All')}</SelectItem>
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div className="space-y-1.5">
                                    <Label htmlFor="automation-backlog-limit">{t('Limit')}</Label>
                                    <Input
                                        id="automation-backlog-limit"
                                        type="number"
                                        min={1}
                                        max={100}
                                        value={backlogLimit}
                                        onChange={(event) => {
                                            setBacklogLimit(event.target.value);
                                            setBacklogResult(null);
                                        }}
                                    />
                                </div>
                            </div>
                            {backlogResult && (
                                <div className="mt-3 flex flex-wrap gap-2 text-sm">
                                    <Badge variant="outline" className="font-normal">{backlogResult.issues} {t('tickets')}</Badge>
                                    <Badge variant="secondary" className="font-normal">{backlogResult.processed} {t('processed')}</Badge>
                                    <Badge variant={backlogResult.failed > 0 ? 'destructive' : 'outline'} className="font-normal">
                                        {backlogResult.failed} {t('failed')}
                                    </Badge>
                                    <Badge variant="outline" className="font-normal">{backlogResult.skipped} {t('skipped')}</Badge>
                                    <Badge variant="outline" className="font-normal">{backlogResult.runs} {t('runs')}</Badge>
                                </div>
                            )}
                        </div>
                        <div className="mt-3 flex justify-end">
                            <Button type="button" size="sm" variant="outline" data-run-sla-scan onClick={() => void runSlaScan()} disabled={runningSla}>
                                {runningSla ? <Loader className="size-4 animate-spin" /> : <AlertTriangle className="size-4" />}
                                {t('Run SLA scan')}
                            </Button>
                        </div>
                        {slaResult && (
                            <div data-sla-scan-result className="mt-3 rounded-md border bg-muted/20 p-3 text-sm">
                                <div className="mb-2 flex items-center justify-between gap-2">
                                    <span className="font-medium">{t('SLA escalation result')}</span>
                                    <Badge variant={slaResult.failed > 0 ? 'destructive' : 'secondary'} className="font-normal">
                                        {slaResult.escalated} {t('escalated')}
                                    </Badge>
                                </div>
                                <div className="flex flex-wrap gap-2">
                                    <Badge variant="outline" className="font-normal">{slaResult.processed} {t('processed')}</Badge>
                                    <Badge variant="outline" className="font-normal">{slaResult.skipped} {t('skipped')}</Badge>
                                    <Badge variant={slaResult.failed > 0 ? 'destructive' : 'outline'} className="font-normal">{slaResult.failed} {t('failed')}</Badge>
                                </div>
                                {slaResult.items.length > 0 && (
                                    <div className="mt-2 space-y-1">
                                        {slaResult.items.slice(0, 3).map(item => (
                                            <div key={`${item.slaEventId}:${item.issueId}`} className="flex min-w-0 items-center justify-between gap-2 rounded border bg-background px-2 py-1 text-xs">
                                                <button
                                                    type="button"
                                                    className="min-w-0 truncate text-left underline-offset-2 hover:underline"
                                                    onClick={() => openTicket(item.issueId)}
                                                >
                                                    {item.issueId}
                                                </button>
                                                <div className="flex shrink-0 items-center gap-1.5">
                                                    <Badge variant={item.status === 'escalated' ? 'secondary' : 'outline'} className="font-normal">
                                                        {item.status}
                                                    </Badge>
                                                    {item.automation && (
                                                        <Badge variant="outline" className="font-normal">
                                                            {item.automation.processed} {t('automation')}
                                                        </Badge>
                                                    )}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}
                    </section>
                    <section className="rounded-md border p-4">
                        <div className="mb-3 flex items-center justify-between gap-2">
                            <h2 className="text-sm font-medium">{t('Run history')}</h2>
                            <Badge variant="outline" className="font-normal">{runs.length}</Badge>
                        </div>
                        {runs.length === 0 ? (
                            <div className="text-sm text-muted-foreground">-</div>
                        ) : (
                            <div className="space-y-2">
                                {runs.map(run => {
                                    const actionLabels = automationRunActionLabels(run, 5);
                                    return (
                                        <div key={run.id} className="rounded-md border bg-muted/20 p-2 text-sm">
                                            <div className="flex items-center justify-between gap-2">
                                                <div className="flex min-w-0 items-center gap-2">
                                                    <Badge variant="outline" className="font-normal">{run.status}</Badge>
                                                    <span className="truncate">{t(triggerLabel(run.trigger))}</span>
                                                </div>
                                                <span className="shrink-0 text-xs text-muted-foreground">{formatTime(run.startedAt)}</span>
                                            </div>
                                            <div className="mt-1 flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
                                                <span className="shrink-0">{run.actionsApplied} {t('actions')}</span>
                                                <span className="min-w-0 flex-1 truncate">{run.issueId}</span>
                                                {run.issueId && tenantId && (
                                                    <Button
                                                        type="button"
                                                        size="sm"
                                                        variant="outline"
                                                        className="h-7 shrink-0 px-2 text-xs"
                                                        onClick={() => openTicket(run.issueId)}
                                                    >
                                                        <ExternalLink className="size-3.5" />
                                                        {t('Open ticket')}
                                                    </Button>
                                                )}
                                            </div>
                                            {actionLabels.length > 0 && (
                                                <div className="mt-2 flex flex-wrap gap-1.5">
                                                    {actionLabels.map((label, index) => (
                                                        <Badge key={`${run.id}:action:${index}:${label}`} variant="secondary" className="max-w-full truncate font-normal">
                                                            {t(label)}
                                                        </Badge>
                                                    ))}
                                                </div>
                                            )}
                                            {run.error && <div className="mt-1 text-xs text-destructive">{run.error}</div>}
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </section>
                    <div className="flex justify-end">
                        <Button onClick={() => void saveRule()} disabled={saving || !name.trim()}>
                            {saving ? <Loader className="size-4 animate-spin" /> : null}
                            {t('Save')}
                        </Button>
                    </div>
                </div>
            </section>
        </div>
    );
}
