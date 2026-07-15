import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import type { LucideIcon } from 'lucide-react';
import { AlertTriangle, BarChart3, BookOpen, Building2, CheckCircle2, Clock, Database, Download, ExternalLink, Inbox as InboxIcon, Loader, Rocket, Send, Sparkles, Star, Users, Workflow } from 'lucide-react';
import { toast } from 'sonner';

import { api } from '@/api/endpoints';
import type { SupportAnalytics, SupportAnalyticsBreakdownItem, SupportAnalyticsChannelRemediation, SupportAnalyticsInsight, SupportAnalyticsQueueCapacityItem, SupportLaunchProof, SupportLaunchProofChannel, SupportLaunchProofChannelBacklogItem, SupportLaunchProofInitialProviderItem, SupportLaunchProofInitialProviders, SupportLaunchProofRunAction, SupportLaunchProofRunResult, SupportLaunchReadinessItem, SupportSchemaHealth } from '@/api/endpoints';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useI18n } from '@/lib/i18n-context';

interface AnalyticsProps {
    projectId: string;
}

type LaunchProofTicketEvidence = {
    key: string;
    label: string;
    detail: string;
    issueId: string;
    accountId: string;
    accountName: string;
    replyId: string;
    runId: string;
    source: string;
    status: string;
    occurredAt: string;
    channelName: string;
    kind: 'workflow' | 'automation' | 'knowledge' | 'account' | 'channel';
};

const initialProviderTargets = [
    { surfaceType: 'email', surfaceLabel: 'Email' },
    { surfaceType: 'chat', surfaceLabel: 'Web chat' },
    { surfaceType: 'slack', surfaceLabel: 'Slack' },
    { surfaceType: 'discord', surfaceLabel: 'Discord' },
];

function initialProviderSurfaceType(value?: string) {
    const surfaceType = (value || '').toLowerCase();
    if (surfaceType === 'web_chat' || surfaceType === 'webchat' || surfaceType === 'web') return 'chat';
    return surfaceType;
}

function Metric({
    label,
    value,
    icon: Icon,
}: {
    label: string;
    value?: number;
    icon: LucideIcon;
}) {
    return (
        <div className="rounded-md border bg-background p-4">
            <div className="mb-3 flex items-center justify-between gap-3 text-muted-foreground">
                <span className="text-sm">{label}</span>
                <Icon className="size-4" />
            </div>
            <div className="text-2xl font-semibold">{(value ?? 0).toLocaleString()}</div>
        </div>
    );
}

function csvCell(value: string | number | undefined | null): string {
    const text = value === undefined || value === null ? '' : String(value);
    return `"${text.replace(/"/g, '""')}"`;
}

function analyticsReportCsv(summary: SupportAnalytics): string {
    const initialProviderProof = summary.launchProof ? launchProofInitialProviderCounts(summary.launchProof) : null;
    const replyRouteProof = summary.launchProof ? launchProofReplyRouteCounts(summary.launchProof) : null;
    const channelAutopilotProof = summary.launchProof ? launchProofChannelAutopilotCounts(summary.launchProof) : null;
    const knowledgeAssistProof = summary.launchProof ? launchProofKnowledgeAssistCounts(summary.launchProof) : null;
    const accountIntelligenceProof = summary.launchProof ? launchProofAccountIntelligenceCounts(summary.launchProof) : null;
    const humanLoopProof = summary.launchProof ? launchProofHumanLoopCounts(summary.launchProof) : null;
    const ticketWorkflowProof = summary.launchProof ? launchProofTicketWorkflowCounts(summary.launchProof) : null;
    const rows: Array<[string, string, string | number]> = [
        ['section', 'metric', 'value'],
        ['Tickets', 'Total issues', summary.totalIssues],
        ['Tickets', 'Open issues', summary.openIssues],
        ['Tickets', 'Ongoing issues', summary.ongoingIssues],
        ['Tickets', 'Done issues', summary.doneIssues],
        ['Workload', 'Active tickets', summary.openWorkloadIssues],
        ['Workload', 'Needs assignee', summary.unassignedIssues],
        ['Workload', 'Needs response', summary.issuesNeedingResponse],
        ['Workload', 'Needs approval', summary.issuesNeedingApproval],
        ['Workload', 'Queue owners at capacity', summary.queueOwnersAtCapacity],
        ['Workflow', 'Ticket workflow proof ready', ticketWorkflowProof?.ready ? 1 : 0],
        ['Workflow', 'Ticket workflow proof blocked', ticketWorkflowProof?.blocked ?? 0],
        ['Workflow', 'Successful workflow tickets', ticketWorkflowProof?.successfulIssues ?? 0],
        ['SLA', 'Overdue SLA', summary.overdueSlaEvents],
        ['SLA', 'SLA due soon', summary.dueSoonSlaEvents],
        ['SLA', 'Avg first response min', summary.averageFirstResponseMinutes],
        ['SLA', 'P90 resolution hours', summary.p90ResolutionHours],
        ['Channels', 'Active channels', summary.activeChannels],
        ['Channels', 'Initial providers ready', initialProviderProof?.ready ?? summary.initialProviderReady ?? 0],
        ['Channels', 'Initial providers blocked', initialProviderProof?.blocked ?? summary.initialProviderBlocked ?? 0],
        ['Channels', 'Configured backlog', summary.channelBacklogSurfaces],
        ['Channels', 'Every-message ticketing', Math.max(summary.activeChannels - summary.activeChannelsWrongTicketMode, 0)],
        ['Channels', 'Wrong ticket mode', summary.activeChannelsWrongTicketMode],
        ['Channels', 'Reply-route ready', replyRouteProof?.ready ?? 0],
        ['Channels', 'Reply-route blocked', replyRouteProof?.blocked ?? 0],
        ['Channels', 'Live target proof passed', summary.activeChannelsWithLiveSmokeTarget],
        ['Channels', 'Live target proof missing', summary.activeChannelsMissingLiveSmokeTarget],
        ['Channels', 'Channels missing smoke', summary.activeChannelsMissingSmoke],
        ['Channels', 'Failed delivery', summary.failedDeliveryRuns + summary.failedOutboundMessages],
        ['Email', 'Sync proof passed', summary.activeEmailChannelsWithSync],
        ['Email', 'Sync proof missing', summary.activeEmailChannelsMissingSync],
        ['Email', 'Sync proof failed', summary.failedEmailChannelSyncRuns],
        ['Email', 'Delivery proof passed', summary.activeEmailChannelsWithDelivery],
        ['Email', 'Delivery proof missing', summary.activeEmailChannelsMissingDelivery],
        ['Channels', 'Attachment lifecycle proof passed', summary.activeChannelsWithAttachmentLifecycleSmoke],
        ['Channels', 'Attachment lifecycle proof missing', summary.activeChannelsMissingAttachmentLifecycleSmoke],
        ['Channels', 'Attachment lifecycle proof failed', summary.failedAttachmentLifecycleChannelSmokeRuns],
        ['Web chat', 'Session proof passed', summary.activeWebChatChannelsWithSession],
        ['Web chat', 'Session proof missing', summary.activeWebChatChannelsMissingSession],
        ['Web chat', 'Session proof failed', summary.failedWebChatChannelSessionProofs],
        ['Web chat', 'Delivery proof passed', summary.activeWebChatChannelsWithDelivery],
        ['Web chat', 'Delivery proof missing', summary.activeWebChatChannelsMissingDelivery],
        ['Web chat', 'Delivery proof failed', summary.failedWebChatChannelDeliveryProofs],
        ['Knowledge', 'Knowledge articles', summary.knowledgeArticles],
        ['Knowledge', 'Open knowledge gaps', summary.openKnowledgeGaps],
        ['Knowledge', 'Knowledge assist proof ready', knowledgeAssistProof?.ready ? 1 : 0],
        ['Knowledge', 'Knowledge assist proof blocked', knowledgeAssistProof?.blocked ?? 0],
        ['Knowledge', 'Successful knowledge assist runs', knowledgeAssistProof?.successfulRuns ?? 0],
        ['Accounts', 'Accounts', summary.accounts],
        ['Accounts', 'Accounts needing action', summary.accountsNeedingAction],
        ['Accounts', 'Open account risks', summary.openAccountRisks],
        ['Accounts', 'Feature requests', summary.featureRequests],
        ['Accounts', 'Account intelligence proof ready', accountIntelligenceProof?.ready ? 1 : 0],
        ['Accounts', 'Account intelligence proof blocked', accountIntelligenceProof?.blocked ?? 0],
        ['Accounts', 'Account intelligence actions', accountIntelligenceProof?.actions ?? 0],
        ['Automation', 'Active automation rules', summary.activeAutomationRules],
        ['Automation', 'Human-in-loop automations', summary.humanLoopAutomationRules],
        ['Automation', 'Successful human-loop proofs', summary.successfulHumanLoopAutomationRuns],
        ['Automation', 'Channel autopilot ready', channelAutopilotProof?.ready ?? 0],
        ['Automation', 'Channel autopilot blocked', channelAutopilotProof?.blocked ?? 0],
        ['Automation', 'Human-loop proof ready', humanLoopProof?.ready ? 1 : 0],
        ['Automation', 'Human-loop proof blocked', humanLoopProof?.blocked ?? 0],
        ['CSAT', 'CSAT responses', summary.csatFeedback],
        ['CSAT', 'Low CSAT', summary.lowCsatFeedback],
    ];
    for (const item of summary.openQueueBreakdown) {
        rows.push(['Workload by queue', item.label || item.key, item.count]);
    }
    for (const item of summary.openAssigneeBreakdown) {
        rows.push(['Workload by assignee', item.label || item.key, item.count]);
    }
    for (const item of summary.openChannelBreakdown) {
        rows.push(['Workload by channel', item.label || item.key, item.count]);
    }
    for (const item of summary.queueOwnerCapacityItems ?? []) {
        rows.push([
            'Queue owner capacity',
            `${item.queueName || item.queueKey} / ${item.assigneeEmail}`,
            `${item.activeTickets}/${item.capacity}`,
        ]);
    }
    return rows.map(row => row.map(csvCell).join(',')).join('\n');
}

function analyticsReportHref(summary: SupportAnalytics): string {
    return `data:text/csv;charset=utf-8,${encodeURIComponent(analyticsReportCsv(summary))}`;
}

function launchProofBundleHref(
    projectId: string,
    launchProof: SupportLaunchProof,
    latestRun: SupportLaunchProofRunResult | null,
    runHistory: SupportLaunchProofRunResult[],
): string {
    const ticketCreation = launchProof.ticketCreation ?? launchProofTicketCreationCounts(launchProof);
    const initialProviders = launchProof.initialProviders ?? launchProofInitialProviderCounts(launchProof);
    const replyRoute = launchProof.replyRoute ?? launchProofReplyRouteCounts(launchProof);
    const channelAutopilot = launchProof.channelAutopilot ?? launchProofChannelAutopilotCounts(launchProof);
    const knowledgeAssist = launchProof.knowledgeAssist ?? launchProofKnowledgeAssistCounts(launchProof);
    const accountIntelligence = launchProof.accountIntelligence ?? launchProofAccountIntelligenceCounts(launchProof);
    const humanLoop = launchProof.humanLoop ?? launchProofHumanLoopCounts(launchProof);
    const ticketWorkflow = launchProof.ticketWorkflow ?? launchProofTicketWorkflowCounts(launchProof);
    const payload = {
        kind: 'support_launch_proof_bundle',
        projectId,
        exportedAt: new Date().toISOString(),
        status: launchProof.status,
        launchProof,
        initialProviders,
        ticketCreation,
        replyRoute,
        channelAutopilot,
        knowledgeAssist,
        accountIntelligence,
        humanLoop,
        ticketWorkflow,
        latestRun,
        runHistory,
    };
    return `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(payload, null, 2))}`;
}

function QueueAction({
    label,
    value,
    icon: Icon,
    onClick,
}: {
    label: string;
    value?: number;
    icon: LucideIcon;
    onClick: () => void;
}) {
    return (
        <Button
            type="button"
            variant="outline"
            className="h-auto justify-start gap-3 px-3 py-2 text-left"
            onClick={onClick}
        >
            <Icon className="size-4 shrink-0" />
            <span className="min-w-0 flex-1 truncate text-sm">{label}</span>
            <Badge variant="secondary" className="ml-auto font-normal">{(value ?? 0).toLocaleString()}</Badge>
            <ExternalLink className="size-3.5 shrink-0 text-muted-foreground" />
        </Button>
    );
}

function inboxRoute(params: Record<string, string>) {
    const query = new URLSearchParams(params);
    return `/inbox?${query.toString()}`;
}

function channelLaunchProofRoute(channel: SupportLaunchProofChannel) {
    const query = new URLSearchParams();
    const channelRef = channel.channelKey || channel.channelId;
    if (channelRef) query.set('channel', channelRef);
    const blockerKey = channel.blockers[0]?.key;
    if (blockerKey) query.set('action', blockerKey);
    const suffix = query.toString();
    return suffix ? `/channels?${suffix}` : '/channels';
}

function channelBacklogRoute(channel: SupportLaunchProofChannelBacklogItem) {
    const query = new URLSearchParams();
    const channelRef = channel.channelKey || channel.channelId;
    if (channelRef) query.set('channel', channelRef);
    query.set('action', 'activation');
    const suffix = query.toString();
    return suffix ? `/channels?${suffix}` : '/channels';
}

function initialProviderRoute(item: SupportLaunchProofInitialProviderItem) {
    const query = new URLSearchParams();
    const channelRef = item.channelKey || item.channelId;
    if (channelRef) query.set('channel', channelRef);
    if (item.surfaceType) query.set('surface', item.surfaceType);
    query.set('action', item.ready ? 'proof' : 'activation');
    const suffix = query.toString();
    return suffix ? `/channels?${suffix}` : '/channels';
}

function ticketProofRoute(issueId: string) {
    return `/inbox/${encodeURIComponent(issueId)}?view=board`;
}

function accountProofRoute(accountId: string) {
    return `/accounts/${encodeURIComponent(accountId)}`;
}

function knowledgeProofRoute(articleId: string) {
    return `/knowledge/${encodeURIComponent(articleId)}`;
}

const runnableLaunchProofBlockerKeys = new Set([
    'workflow_lifecycle_proof_missing',
    'no_active_channels',
    'channel_ticket_mode',
    'channel_auto_prepare_disabled',
    'channel_owner_routing_missing',
    'unassigned_issues',
    'overdue_sla',
    'delivery_failures',
    'channel_failures',
    'channel_autopilot_proof_missing',
    'channel_provider_validation_missing',
    'channel_provider_validation_failures',
    'channel_smoke_missing',
    'channel_smoke_failures',
    'channel_outbound_smoke_missing',
    'channel_outbound_smoke_failures',
    'channel_lifecycle_smoke_missing',
    'channel_lifecycle_smoke_failures',
    'channel_attachment_lifecycle_smoke_missing',
    'channel_attachment_lifecycle_smoke_failures',
    'email_channel_sync_missing',
    'email_channel_sync_failures',
    'email_delivery_missing',
    'web_chat_session_missing',
    'web_chat_session_failures',
    'web_chat_delivery_missing',
    'web_chat_delivery_failures',
    'no_human_loop_automation',
    'automation_proof_missing',
]);

const runnableLaunchProofWarningKeys = new Set([
    'due_soon_sla',
    'empty_knowledge_base',
    'external_sync_failures',
    'low_csat',
    'open_knowledge_gaps',
]);

function launchProofRunnableBlockers(launchProof: SupportLaunchProof): SupportLaunchReadinessItem[] {
    return (launchProof.blockers ?? []).filter(item => runnableLaunchProofBlockerKeys.has(item.key));
}

function launchProofRunnableWarnings(launchProof: SupportLaunchProof): SupportLaunchReadinessItem[] {
    return (launchProof.warnings ?? []).filter(item => runnableLaunchProofWarningKeys.has(item.key));
}

function launchProofTicketEvidence(launchProof: SupportLaunchProof): LaunchProofTicketEvidence[] {
    const evidence: LaunchProofTicketEvidence[] = [];
    (launchProof.evidence?.workflowLifecycle ?? []).forEach((item, index) => {
        if (!item.issueId) return;
        evidence.push({
            key: `workflow:${item.issueId}:${index}`,
            label: item.label || 'Workflow lifecycle proof',
            detail: item.detail || 'Ticket moved through Ongoing and Done',
            issueId: item.issueId,
            accountId: '',
            accountName: '',
            replyId: item.replyId || '',
            runId: item.runId || '',
            source: item.source || '',
            status: 'done',
            occurredAt: item.occurredAt || '',
            channelName: '',
            kind: 'workflow',
        });
    });
    (launchProof.evidence?.humanLoopAutomation ?? []).forEach((item, index) => {
        if (!item.issueId) return;
        evidence.push({
            key: `automation:${item.issueId}:${item.runId || index}`,
            label: item.label || 'Human-loop automation proof',
            detail: item.detail || 'Automation prepared an approval-required agent draft',
            issueId: item.issueId,
            accountId: '',
            accountName: '',
            replyId: item.replyId || '',
            runId: item.runId || '',
            source: item.source || '',
            status: 'done',
            occurredAt: item.occurredAt || '',
            channelName: '',
            kind: 'automation',
        });
    });
    (launchProof.evidence?.knowledgeAssist ?? []).forEach((item, index) => {
        if (!item.issueId) return;
        evidence.push({
            key: `knowledge:${item.issueId}:${item.runId || index}`,
            label: item.label || 'Ticket knowledge assist proof',
            detail: item.detail || 'Agent answer used knowledge citations or recorded a gap',
            issueId: item.issueId,
            accountId: '',
            accountName: '',
            replyId: item.replyId || '',
            runId: item.runId || '',
            source: item.source || '',
            status: 'done',
            occurredAt: item.occurredAt || '',
            channelName: '',
            kind: 'knowledge',
        });
    });
    (launchProof.evidence?.accountIntelligence ?? []).forEach((item, index) => {
        if (!item.accountId) return;
        evidence.push({
            key: `account:${item.accountId}:${item.actionKind || index}`,
            label: item.label || 'Account intelligence proof',
            detail: item.detail || 'Account health, risk, or feature demand needs action',
            issueId: '',
            accountId: item.accountId,
            accountName: item.accountName || item.domain || item.accountKey || '',
            replyId: '',
            runId: '',
            source: item.source || '',
            status: 'done',
            occurredAt: item.occurredAt || '',
            channelName: item.healthStatus || '',
            kind: 'account',
        });
    });
    launchProof.channels.items.forEach(channel => {
        const channelName = channel.name || channel.channelKey || channel.type;
        channel.checklist.forEach(check => {
            if (!check.issueId) return;
            evidence.push({
                key: `channel:${channel.channelId}:${check.key}:${check.issueId}`,
                label: check.label || check.key,
                detail: check.detail,
                issueId: check.issueId,
                accountId: '',
                accountName: '',
                replyId: check.replyId || '',
                runId: '',
                source: check.source,
                status: check.status,
                occurredAt: check.startedAt,
                channelName,
                kind: 'channel',
            });
        });
    });
    return evidence.slice(0, 8);
}

function channelReadinessLedgerItems(launchProof: SupportLaunchProof): SupportLaunchProofChannel[] {
    return [...launchProof.channels.items]
        .sort((left, right) => {
            const leftBlocked = left.required && !left.ready ? 1 : 0;
            const rightBlocked = right.required && !right.ready ? 1 : 0;
            if (leftBlocked !== rightBlocked) return rightBlocked - leftBlocked;
            if (left.required !== right.required) return left.required ? -1 : 1;
            return (left.name || left.channelKey || left.type).localeCompare(right.name || right.channelKey || right.type);
        })
        .slice(0, 8);
}

function launchProofInitialProviderCounts(launchProof: SupportLaunchProof): SupportLaunchProofInitialProviders {
    if (launchProof.initialProviders) return launchProof.initialProviders;
    const items = initialProviderTargets.map<SupportLaunchProofInitialProviderItem>(target => {
        const channel = launchProof.channels.items.find(
            item => initialProviderSurfaceType(item.surfaceType || item.type) === target.surfaceType,
        );
        const backlogChannel = launchProof.channelBacklog?.items.find(
            item => initialProviderSurfaceType(item.type) === target.surfaceType,
        );
        if (!channel) {
            if (backlogChannel) {
                const detail = `Activate ${target.surfaceLabel} provider channel and run launch proof`;
                return {
                    surfaceType: target.surfaceType,
                    surfaceLabel: target.surfaceLabel,
                    launchWave: 'initial',
                    channelId: backlogChannel.channelId,
                    channelKey: backlogChannel.channelKey,
                    name: backlogChannel.name || target.surfaceLabel,
                    type: backlogChannel.type,
                    status: backlogChannel.status,
                    ready: false,
                    checks: 0,
                    passed: 0,
                    blocked: 1,
                    proofKind: 'activation_backlog',
                    detail,
                    blockers: [{
                        key: 'provider_inactive',
                        label: `${target.surfaceLabel} provider inactive`,
                        status: backlogChannel.status,
                        detail,
                        runId: '',
                    }],
                };
            }
            const detail = `Create and prove ${target.surfaceLabel} provider channel`;
            return {
                surfaceType: target.surfaceType,
                surfaceLabel: target.surfaceLabel,
                launchWave: 'initial',
                channelId: '',
                channelKey: '',
                name: target.surfaceLabel,
                type: target.surfaceType,
                status: 'missing',
                ready: false,
                checks: 0,
                passed: 0,
                blocked: 1,
                proofKind: 'missing',
                detail,
                blockers: [{
                    key: 'provider_not_configured',
                    label: `${target.surfaceLabel} provider not configured`,
                    status: 'missing',
                    detail,
                    runId: '',
                }],
            };
        }
        const blocker = channel.blockers[0];
        return {
            surfaceType: target.surfaceType,
            surfaceLabel: target.surfaceLabel,
            launchWave: 'initial',
            channelId: channel.channelId,
            channelKey: channel.channelKey,
            name: channel.name || target.surfaceLabel,
            type: channel.type,
            status: channel.status,
            ready: channel.ready,
            checks: channel.checks,
            passed: channel.passed,
            blocked: channel.blocked,
            proofKind: channel.proofKind,
            detail: blocker?.detail || blocker?.label || `${target.surfaceLabel} provider ready`,
            blockers: channel.blockers,
        };
    });
    const ready = items.filter(item => item.ready).length;
    return {
        required: true,
        total: items.length,
        ready,
        blocked: Math.max(items.length - ready, 0),
        items,
    };
}

function channelTicketCreationCheck(channel: SupportLaunchProofChannel) {
    return channel.checklist.find(check => check.key === 'ticket_mode');
}

function channelTicketCreationReady(channel: SupportLaunchProofChannel) {
    const check = channelTicketCreationCheck(channel);
    return check?.status === 'done' || check?.runStatus === 'per_message';
}

function launchProofTicketCreationCounts(launchProof: SupportLaunchProof) {
    if (launchProof.ticketCreation) return launchProof.ticketCreation;
    const total = launchProof.channels.items.length;
    const ready = launchProof.channels.items.filter(channelTicketCreationReady).length;
    return {
        total,
        ready,
        blocked: Math.max(total - ready, 0),
        wrongMode: Math.max(total - ready, 0),
        items: launchProof.channels.items.map(channel => {
            const check = channelTicketCreationCheck(channel);
            return {
                channelId: channel.channelId,
                channelKey: channel.channelKey,
                name: channel.name,
                type: channel.type,
                mode: check?.runStatus || '',
                ready: channelTicketCreationReady(channel),
                detail: check?.detail || '',
            };
        }),
    };
}

const replyRouteProofKeyPriority = [
    'human_approved_real_channel_reply',
    'real_channel_reply',
    'lifecycle_smoke',
    'outbound_smoke',
    'email_delivery',
    'web_chat_delivery',
];

function channelReplyRouteCheck(channel: SupportLaunchProofChannel) {
    for (const key of replyRouteProofKeyPriority) {
        const readyCheck = channel.checklist.find(check => check.key === key && check.status === 'done');
        if (readyCheck) return readyCheck;
    }
    for (const key of replyRouteProofKeyPriority) {
        const check = channel.checklist.find(item => item.key === key);
        if (check) return check;
    }
    return undefined;
}

function channelReplyRouteReady(channel: SupportLaunchProofChannel) {
    return channelReplyRouteCheck(channel)?.status === 'done';
}

function launchProofReplyRouteCounts(launchProof: SupportLaunchProof) {
    if (launchProof.replyRoute) return launchProof.replyRoute;
    const total = launchProof.channels.items.length;
    const items = launchProof.channels.items.map(channel => {
        const check = channelReplyRouteCheck(channel);
        const deliveryRoute = (check?.deliveryRoute ?? {}) as Record<string, string>;
        return {
            channelId: channel.channelId,
            channelKey: channel.channelKey,
            name: channel.name,
            type: channel.type,
            ready: channelReplyRouteReady(channel),
            proofKey: check?.key || '',
            transport: check?.transport || deliveryRoute.transport || '',
            provider: check?.provider || deliveryRoute.provider || '',
            providerMessageId: check?.providerMessageId || '',
            runId: check?.runId || '',
            issueId: check?.issueId || '',
            replyId: check?.replyId || '',
            detail: check?.detail || '',
        };
    });
    const ready = items.filter(item => item.ready).length;
    return {
        total,
        ready,
        blocked: Math.max(total - ready, 0),
        items,
    };
}

function channelAutopilotCheck(channel: SupportLaunchProofChannel) {
    const readyCheck = channel.checklist.find(check => check.key === 'channel_autopilot' && check.status === 'done');
    if (readyCheck) return readyCheck;
    return channel.checklist.find(check => check.key === 'channel_autopilot')
        ?? channel.checklist.find(check => check.key === 'auto_prepare');
}

function channelAutopilotReady(channel: SupportLaunchProofChannel) {
    const check = channelAutopilotCheck(channel);
    return check?.key === 'channel_autopilot' && check.status === 'done';
}

function launchProofChannelAutopilotCounts(launchProof: SupportLaunchProof) {
    if (launchProof.channelAutopilot) return launchProof.channelAutopilot;
    const total = launchProof.channels.items.length;
    const items = launchProof.channels.items.map(channel => {
        const check = channelAutopilotCheck(channel);
        return {
            channelId: channel.channelId,
            channelKey: channel.channelKey,
            name: channel.name,
            type: channel.type,
            ready: channelAutopilotReady(channel),
            proofKey: check?.key || '',
            runStatus: check?.runStatus || '',
            runId: check?.runId || '',
            issueId: check?.issueId || '',
            replyId: check?.replyId || '',
            aiRunId: check?.aiRunId || '',
            detail: check?.detail || '',
        };
    });
    const ready = items.filter(item => item.ready).length;
    return {
        required: true,
        total,
        ready,
        blocked: Math.max(total - ready, 0),
        items,
    };
}

function launchProofKnowledgeAssistCounts(launchProof: SupportLaunchProof) {
    if (launchProof.knowledgeAssist) return launchProof.knowledgeAssist;
    const items = launchProof.evidence?.knowledgeAssist ?? [];
    const openGapWarning = launchProof.warnings.find(item => item.key === 'open_knowledge_gaps');
    const ready = items.length > 0;
    return {
        required: true,
        ready,
        blocked: ready ? 0 : 1,
        articles: 0,
        openGaps: openGapWarning?.count ?? 0,
        successfulRuns: items.length,
        citationRuns: items.filter(item => (item.citationCount ?? 0) > 0).length,
        gapRuns: items.filter(item => Boolean(item.knowledgeGapId)).length,
        items,
    };
}

function launchProofAccountIntelligenceCounts(launchProof: SupportLaunchProof) {
    if (launchProof.accountIntelligence) return launchProof.accountIntelligence;
    const items = launchProof.evidence?.accountIntelligence ?? [];
    const ready = items.length > 0;
    return {
        required: true,
        ready,
        blocked: ready ? 0 : 1,
        accounts: new Set(items.map(item => item.accountId).filter(Boolean)).size,
        actions: items.length,
        openRisks: items.reduce((total, item) => total + (item.openRisks ?? 0), 0),
        featureRequests: items.reduce((total, item) => total + (item.openFeatureRequests ?? 0), 0),
        failedSyncRuns: items.reduce((total, item) => total + (item.failedExternalSyncRuns ?? 0), 0),
        items,
    };
}

function launchProofHumanLoopCounts(launchProof: SupportLaunchProof) {
    if (launchProof.humanLoop) return launchProof.humanLoop;
    const items = launchProof.evidence?.humanLoopAutomation ?? [];
    const blocker = launchProof.blockers.find(item => item.key === 'no_human_loop_automation' || item.key === 'automation_proof_missing');
    const pendingApprovals = launchProof.warnings.find(item => item.key === 'pending_approvals')?.count ?? 0;
    const ready = items.length > 0 && !blocker;
    return {
        required: true,
        ready,
        blocked: ready ? 0 : 1,
        rules: blocker?.count ?? items.length,
        successfulRuns: items.length,
        pendingApprovals,
        items,
    };
}

function launchProofTicketWorkflowCounts(launchProof: SupportLaunchProof) {
    if (launchProof.ticketWorkflow) return launchProof.ticketWorkflow;
    const items = launchProof.evidence?.workflowLifecycle ?? [];
    const blocker = launchProof.blockers.find(item => item.key === 'workflow_lifecycle_proof_missing');
    const ready = items.length > 0 && !blocker;
    return {
        required: true,
        ready,
        blocked: ready ? 0 : 1,
        transitions: 0,
        ongoingTransitions: 0,
        doneTransitions: 0,
        successfulIssues: items.length,
        items,
    };
}

function channelReadinessLabel(channel: SupportLaunchProofChannel) {
    if (!channel.required) return 'Optional';
    return channel.ready ? 'Ready' : 'Blocked';
}

function channelReadinessVariant(channel: SupportLaunchProofChannel): 'destructive' | 'secondary' | 'outline' {
    if (!channel.required) return 'outline';
    return channel.ready ? 'secondary' : 'destructive';
}

function channelReadinessDetail(channel: SupportLaunchProofChannel) {
    const blocker = channel.blockers[0];
    if (blocker?.detail) return blocker.detail;
    if (blocker?.label) return blocker.label;
    const openCheck = channel.checklist.find(check => check.status !== 'passed' && check.status !== 'ready' && check.status !== 'success');
    if (openCheck?.detail) return openCheck.detail;
    if (openCheck?.label) return openCheck.label;
    if (channel.lastCheckedAt) return `Last checked ${channel.lastCheckedAt}`;
    return channel.proofKind || channel.type || channel.status || 'No proof detail';
}

function WorkloadBreakdown({
    title,
    items,
    icon: Icon,
    onOpen,
    routeFor,
    t,
}: {
    title: string;
    items?: SupportAnalyticsBreakdownItem[];
    icon: LucideIcon;
    onOpen: (path: string) => void;
    routeFor: (item: SupportAnalyticsBreakdownItem) => string;
    t: (value: string) => string;
}) {
    return (
        <section className="rounded-md border bg-background p-4">
            <div className="mb-3 flex items-center gap-2">
                <Icon className="size-4 text-muted-foreground" />
                <h2 className="text-sm font-medium">{title}</h2>
            </div>
            {(items ?? []).length === 0 ? (
                <div className="text-sm text-muted-foreground">-</div>
            ) : (
                <div className="space-y-2">
                    {(items ?? []).map(item => (
                        <Button
                            key={item.key}
                            type="button"
                            variant="outline"
                            className="h-auto w-full justify-start gap-3 px-3 py-2 text-left"
                            onClick={() => onOpen(routeFor(item))}
                        >
                            <span className="min-w-0 flex-1 truncate text-sm">{item.label || item.key}</span>
                            <Badge variant="secondary" className="font-normal">{item.count.toLocaleString()}</Badge>
                            <ExternalLink className="size-3.5 shrink-0 text-muted-foreground" />
                        </Button>
                    ))}
                </div>
            )}
            <div className="mt-3 text-xs text-muted-foreground">{t('Open and ongoing tickets only')}</div>
        </section>
    );
}

function QueueCapacityPanel({
    items,
    onOpen,
    t,
}: {
    items?: SupportAnalyticsQueueCapacityItem[];
    onOpen: (path: string) => void;
    t: (value: string) => string;
}) {
    const capacityItems = items ?? [];
    if (capacityItems.length === 0) return null;
    return (
        <section className="rounded-md border bg-background p-4">
            <div className="mb-3 flex items-center gap-2">
                <Users className="size-4 text-muted-foreground" />
                <h2 className="text-sm font-medium">{t('Owners at capacity')}</h2>
            </div>
            <div className="space-y-2">
                {capacityItems.map(item => (
                    <Button
                        key={`${item.queueKey}:${item.assigneeEmail}`}
                        type="button"
                        variant="outline"
                        className="h-auto w-full justify-start gap-3 px-3 py-2 text-left"
                        onClick={() => onOpen(inboxRoute({ queue: item.queueKey, assignee: item.assigneeEmail }))}
                    >
                        <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm">{item.assigneeEmail}</span>
                            <span className="block truncate text-xs font-normal text-muted-foreground">
                                {item.queueName || item.queueKey}
                            </span>
                        </span>
                        <Badge variant="outline" className="font-normal">
                            {item.activeTickets.toLocaleString()}/{item.capacity.toLocaleString()}
                        </Badge>
                        <ExternalLink className="size-3.5 shrink-0 text-muted-foreground" />
                    </Button>
                ))}
            </div>
            <div className="mt-3 text-xs text-muted-foreground">{t('Least-open queue owners at or above configured active ticket capacity')}</div>
        </section>
    );
}

function insightVariant(severity: SupportAnalyticsInsight['severity']): 'destructive' | 'secondary' | 'outline' {
    if (severity === 'critical') return 'destructive';
    if (severity === 'good') return 'secondary';
    return 'outline';
}

function insightIcon(severity: SupportAnalyticsInsight['severity']) {
    if (severity === 'critical' || severity === 'warning') {
        return <AlertTriangle className="size-4 shrink-0 text-muted-foreground" />;
    }
    if (severity === 'good') {
        return <CheckCircle2 className="size-4 shrink-0 text-muted-foreground" />;
    }
    return <BarChart3 className="size-4 shrink-0 text-muted-foreground" />;
}

function SupportHealthInsights({
    items,
    onOpen,
    t,
}: {
    items?: SupportAnalyticsInsight[];
    onOpen: (path: string) => void;
    t: (value: string) => string;
}) {
    const insights = items ?? [];
    if (insights.length === 0) return null;
    return (
        <section className="space-y-3">
            <div className="flex items-center gap-2">
                <BarChart3 className="size-4 text-muted-foreground" />
                <h2 className="text-sm font-medium">{t('Support health')}</h2>
            </div>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
                {insights.map(insight => (
                    <Button
                        key={insight.key}
                        type="button"
                        variant="outline"
                        className="h-full min-h-32 flex-col items-start justify-between gap-3 px-4 py-3 text-left"
                        onClick={() => insight.route && onOpen(insight.route)}
                        disabled={!insight.route}
                    >
                        <span className="flex w-full items-start justify-between gap-3">
                            <span className="flex min-w-0 items-center gap-2">
                                {insightIcon(insight.severity)}
                                <span className="truncate text-sm font-medium">{t(insight.label)}</span>
                            </span>
                            <Badge variant={insightVariant(insight.severity)} className="font-normal">
                                {t(insight.severity)}
                            </Badge>
                        </span>
                        <span className="line-clamp-3 text-sm font-normal leading-5 text-muted-foreground">
                            {t(insight.detail)}
                        </span>
                        <span className="flex w-full items-center justify-between gap-3 text-xs text-muted-foreground">
                            <span className="truncate">
                                {insight.unit
                                    ? `${insight.value.toLocaleString()} ${t(insight.unit)}`
                                    : t('Open')}
                            </span>
                            {insight.route && <ExternalLink className="size-3.5 shrink-0" />}
                        </span>
                    </Button>
                ))}
            </div>
        </section>
    );
}

function remediationVariant(severity: SupportAnalyticsChannelRemediation['severity']): 'destructive' | 'secondary' | 'outline' {
    if (severity === 'critical') return 'destructive';
    if (severity === 'info') return 'secondary';
    return 'outline';
}

function ChannelRemediationPanel({
    items,
    onOpen,
    t,
}: {
    items?: SupportAnalyticsChannelRemediation[];
    onOpen: (path: string) => void;
    t: (value: string) => string;
}) {
    const visible = items ?? [];
    if (visible.length === 0) return null;
    return (
        <section className="rounded-md border bg-background p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                    <AlertTriangle className="size-4 text-muted-foreground" />
                    <h2 className="text-sm font-medium">{t('Channel remediation')}</h2>
                </div>
                <Badge variant="secondary" className="font-normal">{visible.length.toLocaleString()}</Badge>
            </div>
            <div className="space-y-2">
                {visible.map((item, index) => {
                    const query = new URLSearchParams();
                    const channelRef = item.channelKey || item.channelId;
                    if (channelRef) query.set('channel', channelRef);
                    if (item.runAction) query.set('action', item.runAction);
                    const route = query.toString() ? `/channels?${query.toString()}` : '/channels';
                    return (
                        <Button
                            key={`${item.channelId}-${item.source}-${item.key}-${index}`}
                            type="button"
                            variant="outline"
                            className="h-auto w-full justify-start gap-3 px-3 py-2 text-left"
                            onClick={() => onOpen(route)}
                        >
                            <AlertTriangle className="size-4 shrink-0 text-muted-foreground" />
                            <span className="min-w-0 flex-1">
                                <span className="block truncate text-sm font-medium">
                                    {t(item.channelName || item.channelKey || item.channelId || 'Channel')}
                                    {item.source ? ` · ${item.source}` : ''}
                                </span>
                                <span className="line-clamp-2 text-xs font-normal text-muted-foreground">
                                    {t(item.label || item.key)}{item.detail ? ` · ${item.detail}` : ''}
                                </span>
                            </span>
                            <Badge variant={remediationVariant(item.severity)} className="font-normal">
                                {t(item.severity || 'warning')}
                            </Badge>
                            <ExternalLink className="size-3.5 shrink-0 text-muted-foreground" />
                        </Button>
                    );
                })}
            </div>
        </section>
    );
}

function CountList({ title, counts }: { title: string; counts?: Record<string, number> }) {
    const entries = Object.entries(counts ?? {}).sort((a, b) => b[1] - a[1]);
    return (
        <section className="rounded-md border bg-background p-4">
            <h2 className="mb-3 text-sm font-medium">{title}</h2>
            {entries.length === 0 ? (
                <div className="text-sm text-muted-foreground">-</div>
            ) : (
                <div className="space-y-2">
                    {entries.map(([name, value]) => (
                        <div key={name} className="flex items-center justify-between gap-4 text-sm">
                            <span>{name}</span>
                            <Badge variant="outline" className="font-normal">{value}</Badge>
                        </div>
                    ))}
                </div>
            )}
        </section>
    );
}

function readinessLabel(status: string) {
    if (status === 'ready') return 'Ready';
    if (status === 'blocked') return 'Blocked';
    if (status === 'needs_attention') return 'Needs attention';
    return status || 'Unknown';
}

function readinessVariant(status: string): 'destructive' | 'secondary' | 'outline' {
    if (status === 'blocked') return 'destructive';
    if (status === 'ready') return 'secondary';
    return 'outline';
}

function launchActionVariant(status: string): 'destructive' | 'secondary' | 'outline' {
    if (status === 'failed') return 'destructive';
    if (status === 'success') return 'secondary';
    return 'outline';
}

function textFrom(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

function recordFrom(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, unknown>
        : null;
}

function firstText(...values: unknown[]): string {
    for (const value of values) {
        const text = textFrom(value);
        if (text) return text;
    }
    return '';
}

function firstRecordItem(value: unknown): Record<string, unknown> | null {
    return Array.isArray(value)
        ? recordFrom(value.find(item => recordFrom(item)))
        : null;
}

function numberFrom(value: unknown): number | null {
    if (value === undefined || value === null || value === '') return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
}

function launchActionRoute(action: SupportLaunchProofRunAction): string {
    const result = recordFrom(action.result) ?? {};
    const issue = recordFrom(result.issue);
    const article = recordFrom(result.article);
    const session = recordFrom(result.session);
    const sessionIssue = recordFrom(session?.issue);
    const firstItem = firstRecordItem(result.items);
    const nestedResult = recordFrom(firstItem?.result);
    const nestedIssue = recordFrom(nestedResult?.issue);
    const nestedArticle = recordFrom(nestedResult?.article);
    const articleId = firstText(
        result.articleId,
        result.article_id,
        article?.id,
        firstItem?.articleId,
        firstItem?.article_id,
        nestedResult?.articleId,
        nestedResult?.article_id,
        nestedArticle?.id,
    );
    if (articleId) return knowledgeProofRoute(articleId);

    const issueId = firstText(
        result.issueId,
        result.issue_id,
        issue?.id,
        session?.issueId,
        session?.issue_id,
        sessionIssue?.id,
        firstItem?.issueId,
        firstItem?.issue_id,
        nestedResult?.issueId,
        nestedResult?.issue_id,
        nestedIssue?.id,
    );
    if (issueId) return ticketProofRoute(issueId);

    const channel = recordFrom(result.channel);
    const channelRef = firstText(
        result.channelKey,
        result.channel_key,
        channel?.channelKey,
        channel?.channel_key,
        channel?.id,
        result.channelId,
        result.channel_id,
        firstItem?.channelKey,
        firstItem?.channel_key,
        firstItem?.channelId,
        firstItem?.channel_id,
        action.key.startsWith('provider_validation:') ? action.key.split(':')[1] : '',
    );
    if (channelRef) return `/channels?channel=${encodeURIComponent(channelRef)}`;

    if (
        action.key.includes('channel')
        || action.key.includes('smoke')
        || action.key.includes('web_chat')
        || action.key.includes('email_sync')
    ) {
        return '/channels';
    }
    if (action.key.includes('delivery')) return '/inbox?filter=failed-delivery';
    if (action.key.includes('due_soon')) return '/inbox?filter=due-soon-sla';
    if (action.key.includes('sla')) return '/inbox?filter=overdue-sla';
    if (action.key.includes('workflow')) return '/inbox?view=board';
    if (action.key.includes('automation')) return '/automations';
    if (action.key.includes('knowledge')) return '/knowledge';
    if (action.key.includes('csat')) return '/inbox?filter=low-csat';
    if (action.key.includes('crm') || action.key.includes('external_sync')) return '/channels';
    return '';
}

function launchActionDetail(action: SupportLaunchProofRunAction): string {
    if (action.error) return action.error;
    const detail = textFrom(action.result.detail);
    if (detail) return detail;
    const parts = [
        ['processed', numberFrom(action.result.processed)],
        ['updated', numberFrom(action.result.updated)],
        ['created', numberFrom(action.result.created)],
        ['resolved', numberFrom(action.result.resolved)],
        ['notes', numberFrom(action.result.notes)],
        ['insights', numberFrom(action.result.insights)],
        ['sent', numberFrom(action.result.sent)],
        ['connectors', numberFrom(action.result.connectors)],
        ['objects', numberFrom(action.result.objectsSeen)],
        ['failed', numberFrom(action.result.failed)],
        ['skipped', numberFrom(action.result.skipped)],
        ['deferred', numberFrom(action.result.deferred)],
    ]
        .filter((item): item is [string, number] => item[1] !== null)
        .map(([label, value]) => `${value.toLocaleString()} ${label}`);
    return parts.join(' · ');
}

function proofRunTime(run: SupportLaunchProofRunResult): string {
    const raw = run.completedAt || run.startedAt || run.created || '';
    if (!raw) return '';
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) return raw;
    return date.toLocaleString();
}

function readinessRoute(key: string): string {
    if (
        key === 'schema_collections_missing'
        || key === 'schema_fields_missing'
        || key === 'schema_migrations_missing'
    ) {
        return '/analytics';
    }
    if (key === 'overdue_sla') return '/inbox?filter=overdue-sla';
    if (key === 'due_soon_sla') return '/inbox?filter=due-soon-sla';
    if (key === 'delivery_failures' || key === 'failed_outbound_messages') return '/inbox?filter=failed-delivery';
    if (key === 'low_csat') return '/inbox?filter=low-csat';
    if (key === 'unassigned_issues') return '/inbox?filter=unassigned';
    if (key === 'workflow_lifecycle_proof_missing') return '/inbox?view=board';
    if (key === 'pending_approvals') return '/inbox?filter=approvals';
    if (key === 'open_knowledge_gaps' || key === 'empty_knowledge_base') return '/knowledge';
    if (
        key === 'automation_failures'
        || key === 'no_active_automations'
        || key === 'no_agent_automation'
        || key === 'no_agent_draft_automation'
        || key === 'no_human_loop_automation'
        || key === 'automation_proof_missing'
    ) {
        return '/automations';
    }
    if (
        key === 'no_active_channels'
        || key === 'channel_ticket_mode'
        || key === 'channel_auto_prepare_disabled'
        || key === 'channel_owner_routing_missing'
        || key === 'channel_autopilot_proof_missing'
        || key === 'channel_live_smoke_target_missing'
        || key === 'channel_failures'
        || key === 'channel_ingestion_failures'
        || key === 'failed_channel_webhooks'
        || key === 'unmatched_channel_webhooks'
        || key === 'channel_provider_validation_missing'
        || key === 'channel_provider_validation_failures'
        || key === 'channel_smoke_missing'
        || key === 'channel_smoke_failures'
        || key === 'channel_outbound_smoke_missing'
        || key === 'channel_outbound_smoke_failures'
        || key === 'channel_lifecycle_smoke_missing'
        || key === 'channel_lifecycle_smoke_failures'
        || key === 'channel_attachment_lifecycle_smoke_missing'
        || key === 'channel_attachment_lifecycle_smoke_failures'
        || key === 'email_channel_sync_missing'
        || key === 'email_channel_sync_failures'
        || key === 'email_delivery_missing'
        || key === 'web_chat_session_missing'
        || key === 'web_chat_session_failures'
        || key === 'web_chat_delivery_missing'
        || key === 'web_chat_delivery_failures'
        || key === 'external_sync_failures'
        || key === 'crm_or_external_sync_failures'
    ) {
        return '/channels';
    }
    return '';
}

function ReadinessItemRow({
    item,
    badgeVariant,
    onOpen,
    onRunWorkflowProof,
    onRunAutomationProof,
    onRunLaunchProof,
    workflowProofRunning,
    automationProofRunning,
    launchProofRunning,
    t,
}: {
    item: SupportLaunchReadinessItem;
    badgeVariant: 'destructive' | 'outline';
    onOpen: (path: string) => void;
    onRunWorkflowProof?: () => void;
    onRunAutomationProof?: () => void;
    onRunLaunchProof?: () => void;
    workflowProofRunning?: boolean;
    automationProofRunning?: boolean;
    launchProofRunning?: boolean;
    t: (value: string) => string;
}) {
    const route = readinessRoute(item.key);
    const launchRunnable = runnableLaunchProofBlockerKeys.has(item.key) || runnableLaunchProofWarningKeys.has(item.key);
    const runProofAction = item.key === 'workflow_lifecycle_proof_missing' && onRunWorkflowProof
        ? {
            running: Boolean(workflowProofRunning),
            onRun: onRunWorkflowProof,
            icon: <Workflow className="size-3.5" />,
        }
        : item.key === 'automation_proof_missing' && onRunAutomationProof
            ? {
                running: Boolean(automationProofRunning),
                onRun: onRunAutomationProof,
                icon: <Sparkles className="size-3.5" />,
            }
            : launchRunnable && onRunLaunchProof
                ? {
                    running: Boolean(launchProofRunning),
                    onRun: onRunLaunchProof,
                    icon: <Rocket className="size-3.5" />,
                }
                : null;
    return (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border bg-muted/20 px-2.5 py-2 text-sm">
            <span className="min-w-0 flex-1 truncate">{t(item.label)}</span>
            <div className="flex shrink-0 items-center gap-2">
                <Badge variant={badgeVariant} className="font-normal">{item.count.toLocaleString()}</Badge>
                {runProofAction && (
                    <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-7 gap-1 px-2"
                        onClick={runProofAction.onRun}
                        disabled={runProofAction.running}
                    >
                        {runProofAction.running
                            ? <Loader className="size-3.5 animate-spin" />
                            : runProofAction.icon}
                        {t('Run proof')}
                    </Button>
                )}
                {route && (
                    <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 gap-1 px-2"
                        onClick={() => onOpen(route)}
                    >
                        {t('Open')}
                        <ExternalLink className="size-3.5" />
                    </Button>
                )}
            </div>
        </div>
    );
}

function schemaLabel(status: string) {
    if (status === 'ready') return 'Ready';
    if (status === 'missing') return 'Missing';
    if (status === 'migration_missing') return 'Migration missing';
    return status || 'Unknown';
}

function SchemaHealthPanel({
    schemaHealth,
    t,
}: {
    schemaHealth: SupportSchemaHealth;
    t: (value: string) => string;
}) {
    const missingFields = schemaHealth.missingFields ?? [];
    const missingMigrationFiles = schemaHealth.missingMigrationFiles ?? [];
    const requiredFields = schemaHealth.requiredFields ?? 0;
    const presentFields = schemaHealth.presentFields ?? 0;
    const expectedMigrations = schemaHealth.expectedMigrations ?? 0;
    const presentMigrations = schemaHealth.presentMigrations ?? 0;

    return (
        <section className="rounded-md border bg-background p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2">
                    {schemaHealth.ready
                        ? <CheckCircle2 className="size-4 text-emerald-600" />
                        : <Database className="size-4 text-destructive" />}
                    <h2 className="text-sm font-medium">{t('Schema health')}</h2>
                </div>
                <Badge variant={schemaHealth.ready ? 'secondary' : 'destructive'} className="font-normal">
                    {t(schemaLabel(schemaHealth.status))}
                </Badge>
            </div>
            <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-5">
                <div>
                    <div className="text-xs font-medium uppercase text-muted-foreground">{t('Required collections')}</div>
                    <div className="mt-1 text-lg font-semibold">{schemaHealth.requiredCollections.toLocaleString()}</div>
                </div>
                <div>
                    <div className="text-xs font-medium uppercase text-muted-foreground">{t('Present collections')}</div>
                    <div className="mt-1 text-lg font-semibold">{schemaHealth.presentCollections.toLocaleString()}</div>
                </div>
                <div>
                    <div className="text-xs font-medium uppercase text-muted-foreground">{t('Missing collections')}</div>
                    <div className="mt-1 text-lg font-semibold">{schemaHealth.missingCollections.length.toLocaleString()}</div>
                </div>
                <div>
                    <div className="text-xs font-medium uppercase text-muted-foreground">{t('Present fields')}</div>
                    <div className="mt-1 text-lg font-semibold">{presentFields.toLocaleString()} / {requiredFields.toLocaleString()}</div>
                </div>
                <div>
                    <div className="text-xs font-medium uppercase text-muted-foreground">{t('Migrations')}</div>
                    <div className="mt-1 text-lg font-semibold">{presentMigrations.toLocaleString()} / {expectedMigrations.toLocaleString()}</div>
                </div>
            </div>
            {schemaHealth.missingCollections.length > 0 && (
                <div className="mt-3">
                    <div className="mb-2 text-xs font-medium uppercase text-muted-foreground">
                        {t('Missing support collections')}
                    </div>
                    <div className="flex flex-wrap gap-2">
                        {schemaHealth.missingCollections.slice(0, 12).map(name => (
                            <Badge key={name} variant="destructive" className="font-normal">{name}</Badge>
                        ))}
                        {schemaHealth.missingCollections.length > 12 && (
                            <Badge variant="outline" className="font-normal">
                                +{schemaHealth.missingCollections.length - 12}
                            </Badge>
                        )}
                    </div>
                </div>
            )}
            {missingFields.length > 0 && (
                <div className="mt-3">
                    <div className="mb-2 text-xs font-medium uppercase text-muted-foreground">
                        {t('Missing support fields')}
                    </div>
                    <div className="flex flex-wrap gap-2">
                        {missingFields.slice(0, 12).map(name => (
                            <Badge key={name} variant="destructive" className="font-normal">{name}</Badge>
                        ))}
                        {missingFields.length > 12 && (
                            <Badge variant="outline" className="font-normal">
                                +{missingFields.length - 12}
                            </Badge>
                        )}
                    </div>
                </div>
            )}
            {missingMigrationFiles.length > 0 && (
                <div className="mt-3">
                    <div className="mb-2 text-xs font-medium uppercase text-muted-foreground">
                        {t('Missing migration files')}
                    </div>
                    <div className="flex flex-wrap gap-2">
                        {missingMigrationFiles.slice(0, 12).map(name => (
                            <Badge key={name} variant="destructive" className="font-normal">{name}</Badge>
                        ))}
                        {missingMigrationFiles.length > 12 && (
                            <Badge variant="outline" className="font-normal">
                                +{missingMigrationFiles.length - 12}
                            </Badge>
                        )}
                    </div>
                </div>
            )}
        </section>
    );
}

function LaunchProofPanel({
    projectId,
    launchProof,
    latestRun,
    runHistory,
    onOpen,
    onRunProof,
    proofRunning,
    t,
}: {
    projectId: string;
    launchProof: SupportLaunchProof;
    latestRun: SupportLaunchProofRunResult | null;
    runHistory: SupportLaunchProofRunResult[];
    onOpen: (path: string) => void;
    onRunProof: () => void;
    proofRunning: boolean;
    t: (value: string) => string;
}) {
    const blockedChannels = launchProof.channels.items.filter(channel => channel.required && !channel.ready);
    const channelLedgerItems = channelReadinessLedgerItems(launchProof);
    const runnableBlockers = launchProofRunnableBlockers(launchProof);
    const runnableWarnings = launchProofRunnableWarnings(launchProof);
    const canRunProof = blockedChannels.length > 0 || runnableBlockers.length > 0 || runnableWarnings.length > 0;
    const ticketEvidence = launchProofTicketEvidence(launchProof);
    const initialProviderProof = launchProofInitialProviderCounts(launchProof);
    const ticketCreationProof = launchProofTicketCreationCounts(launchProof);
    const replyRouteProof = launchProofReplyRouteCounts(launchProof);
    const channelAutopilotProof = launchProofChannelAutopilotCounts(launchProof);
    const knowledgeAssistProof = launchProofKnowledgeAssistCounts(launchProof);
    const accountIntelligenceProof = launchProofAccountIntelligenceCounts(launchProof);
    const humanLoopProof = launchProofHumanLoopCounts(launchProof);
    const ticketWorkflowProof = launchProofTicketWorkflowCounts(launchProof);
    const channelBacklogItems = launchProof.channelBacklog?.items ?? [];
    const bundleHref = launchProofBundleHref(projectId, launchProof, latestRun, runHistory);

    return (
        <section className="rounded-md border bg-background p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2">
                    {launchProof.status === 'ready'
                        ? <CheckCircle2 className="size-4 text-emerald-600" />
                        : <Rocket className="size-4 text-muted-foreground" />}
                    <h2 className="text-sm font-medium">{t('Launch proof')}</h2>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                    {canRunProof && (
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="h-8 gap-1.5 px-2.5"
                            data-run-launch-proof
                            onClick={onRunProof}
                            disabled={proofRunning}
                        >
                            {proofRunning
                                ? <Loader className="size-3.5 animate-spin" />
                                : <Rocket className="size-3.5" />}
                            {t('Run proof')}
                        </Button>
                    )}
                    <Button type="button" variant="outline" size="sm" className="h-8 gap-1.5 px-2.5" asChild>
                        <a
                            href={bundleHref}
                            download={`support-launch-proof-${projectId}.json`}
                            data-support-launch-proof-download
                        >
                            <Download className="size-3.5" />
                            {t('Export proof')}
                        </a>
                    </Button>
                    <Badge variant={readinessVariant(launchProof.status)} className="font-normal">
                        {t(readinessLabel(launchProof.status))}
                    </Badge>
                </div>
            </div>
            <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-12">
                <div>
                    <div className="text-xs font-medium uppercase text-muted-foreground">{t('Schema')}</div>
                    <div className="mt-1 text-lg font-semibold">
                        {launchProof.schema.ready ? t('Ready') : t('Blocked')}
                    </div>
                </div>
                <div>
                    <div className="text-xs font-medium uppercase text-muted-foreground">{t('Active channels')}</div>
                    <div className="mt-1 text-lg font-semibold">{launchProof.channels.active.toLocaleString()}</div>
                </div>
                <div>
                    <div className="text-xs font-medium uppercase text-muted-foreground">{t('Proof required')}</div>
                    <div className="mt-1 text-lg font-semibold">{launchProof.channels.required.toLocaleString()}</div>
                </div>
                <div>
                    <div className="text-xs font-medium uppercase text-muted-foreground">{t('Proof ready')}</div>
                    <div className="mt-1 text-lg font-semibold">{launchProof.channels.ready.toLocaleString()}</div>
                </div>
                <div>
                    <div className="text-xs font-medium uppercase text-muted-foreground">{t('Blocked channels')}</div>
                    <div className="mt-1 text-lg font-semibold">{launchProof.channels.blocked.toLocaleString()}</div>
                </div>
                <div>
                    <div className="text-xs font-medium uppercase text-muted-foreground">{t('Backlog')}</div>
                    <div className="mt-1 text-lg font-semibold">
                        {(launchProof.channelBacklog?.total ?? 0).toLocaleString()}
                    </div>
                </div>
                <div>
                    <div className="text-xs font-medium uppercase text-muted-foreground">{t('Initial providers')}</div>
                    <div className="mt-1 text-lg font-semibold">
                        {initialProviderProof.ready.toLocaleString()}/{initialProviderProof.total.toLocaleString()}
                    </div>
                </div>
                <div>
                    <div className="text-xs font-medium uppercase text-muted-foreground">{t('Reply-route ready')}</div>
                    <div className="mt-1 text-lg font-semibold">{replyRouteProof.ready.toLocaleString()}</div>
                </div>
                <div>
                    <div className="text-xs font-medium uppercase text-muted-foreground">{t('Human-loop proof')}</div>
                    <div className="mt-1 text-lg font-semibold">{humanLoopProof.ready ? t('Ready') : t('Blocked')}</div>
                </div>
                <div>
                    <div className="text-xs font-medium uppercase text-muted-foreground">{t('Autopilot ready')}</div>
                    <div className="mt-1 text-lg font-semibold">{channelAutopilotProof.ready.toLocaleString()}</div>
                </div>
                <div>
                    <div className="text-xs font-medium uppercase text-muted-foreground">{t('Knowledge assist')}</div>
                    <div className="mt-1 text-lg font-semibold">{knowledgeAssistProof.ready ? t('Ready') : t('Blocked')}</div>
                </div>
                <div>
                    <div className="text-xs font-medium uppercase text-muted-foreground">{t('Account intel')}</div>
                    <div className="mt-1 text-lg font-semibold">{accountIntelligenceProof.ready ? t('Ready') : t('Blocked')}</div>
                </div>
                <div>
                    <div className="text-xs font-medium uppercase text-muted-foreground">{t('Ticket workflow')}</div>
                    <div className="mt-1 text-lg font-semibold">{ticketWorkflowProof.ready ? t('Ready') : t('Blocked')}</div>
                </div>
            </div>
            <div
                className="mt-4 rounded-md border bg-muted/20 p-3"
                data-analytics-initial-provider-proof
                data-analytics-initial-provider-proof-total={initialProviderProof.total}
                data-analytics-initial-provider-proof-ready={initialProviderProof.ready}
                data-analytics-initial-provider-proof-blocked={initialProviderProof.blocked}
            >
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <div>
                        <div className="text-xs font-medium uppercase text-muted-foreground">{t('Initial provider wave')}</div>
                        <div className="mt-1 text-sm font-medium">{t('Email, web chat, Slack, and Discord')}</div>
                    </div>
                    <Badge variant={initialProviderProof.blocked === 0 ? 'secondary' : 'destructive'} className="font-normal">
                        {initialProviderProof.ready.toLocaleString()}/{initialProviderProof.total.toLocaleString()} {t('ready')}
                    </Badge>
                </div>
                <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
                    {initialProviderProof.items.map(item => (
                        <Button
                            key={`initial-provider:${item.surfaceType}`}
                            type="button"
                            variant="outline"
                            className="h-auto min-w-0 flex-col items-stretch gap-2 bg-background px-3 py-2 text-left"
                            data-analytics-initial-provider-row
                            data-analytics-initial-provider-row-surface={item.surfaceType}
                            data-analytics-initial-provider-row-ready={item.ready ? 'true' : 'false'}
                            data-analytics-initial-provider-row-status={item.status}
                            data-analytics-initial-provider-row-channel={item.channelKey || item.channelId}
                            data-analytics-initial-provider-row-proof-kind={item.proofKind}
                            onClick={() => onOpen(initialProviderRoute(item))}
                        >
                            <span className="flex min-w-0 items-center justify-between gap-2">
                                <span className="min-w-0 truncate text-sm font-medium">
                                    {t(item.surfaceLabel || item.name || item.surfaceType)}
                                </span>
                                <Badge variant={item.ready ? 'secondary' : 'outline'} className="font-normal">
                                    {item.ready ? t('Ready') : t(item.status || 'Blocked')}
                                </Badge>
                            </span>
                            <span className="line-clamp-2 text-xs font-normal text-muted-foreground">
                                {t(item.detail || item.proofKind || item.status)}
                            </span>
                            <span className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                                <span>{item.passed.toLocaleString()}/{item.checks.toLocaleString()}</span>
                                <ExternalLink className="size-3.5 shrink-0" />
                            </span>
                        </Button>
                    ))}
                </div>
            </div>
            {channelBacklogItems.length > 0 && (
                <div
                    className="mt-4 rounded-md border bg-muted/20 p-3"
                    data-channel-backlog-ledger
                    data-channel-backlog-ledger-count={channelBacklogItems.length}
                    data-channel-backlog-ledger-types={(launchProof.channelBacklog?.types ?? []).join(',')}
                >
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                        <div>
                            <div className="text-xs font-medium uppercase text-muted-foreground">{t('Channel backlog')}</div>
                            <div className="mt-1 text-sm font-medium">{t('Paused omnichannel surfaces')}</div>
                        </div>
                        <Badge variant="outline" className="font-normal">
                            {channelBacklogItems.length.toLocaleString()} {t('paused')}
                        </Badge>
                    </div>
                    <div className="grid gap-2 md:grid-cols-2">
                        {channelBacklogItems.map(channel => (
                            <Button
                                key={channel.channelId || channel.channelKey || channel.type}
                                type="button"
                                variant="outline"
                                className="h-auto min-w-0 justify-between gap-3 bg-background px-3 py-2 text-left text-sm"
                                data-channel-backlog-row
                                data-channel-backlog-row-key={channel.channelKey || channel.channelId}
                                data-channel-backlog-row-type={channel.type}
                                data-channel-backlog-row-status={channel.status}
                                onClick={() => onOpen(channelBacklogRoute(channel))}
                            >
                                <span className="min-w-0">
                                    <span className="block truncate font-medium">
                                        {channel.name || channel.channelKey || channel.type}
                                    </span>
                                    <span className="block truncate text-xs text-muted-foreground">
                                        {channel.channelKey || channel.channelId || channel.type}
                                    </span>
                                </span>
                                <span className="flex shrink-0 items-center gap-1.5">
                                    <Badge variant="outline" className="font-normal">
                                        {t(channel.status || 'paused')}
                                    </Badge>
                                    <Badge variant="secondary" className="font-normal">
                                        {channel.type || t('channel')}
                                    </Badge>
                                    <ExternalLink className="size-3.5 text-muted-foreground" />
                                </span>
                            </Button>
                        ))}
                    </div>
                </div>
            )}
            <div
                className="mt-4 rounded-md border bg-muted/20 p-3"
                data-analytics-ticket-creation-proof
                data-analytics-ticket-creation-proof-total={ticketCreationProof.total}
                data-analytics-ticket-creation-proof-ready={ticketCreationProof.ready}
                data-analytics-ticket-creation-proof-blocked={ticketCreationProof.blocked}
            >
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <div>
                        <div className="text-xs font-medium uppercase text-muted-foreground">{t('Ticket creation proof')}</div>
                        <div className="mt-1 text-sm font-medium">{t('New message equals new ticket')}</div>
                    </div>
                    <Badge variant={ticketCreationProof.blocked === 0 ? 'secondary' : 'destructive'} className="font-normal">
                        {ticketCreationProof.ready.toLocaleString()}/{ticketCreationProof.total.toLocaleString()} {t('ready')}
                    </Badge>
                </div>
                <div className="grid gap-2 md:grid-cols-2">
                    {channelLedgerItems.map(channel => {
                        const check = channelTicketCreationCheck(channel);
                        const ready = channelTicketCreationReady(channel);
                        return (
                            <div
                                key={`ticket-mode:${channel.channelId || channel.channelKey || channel.type}`}
                                className="flex min-w-0 items-center justify-between gap-2 rounded-md border bg-background px-2 py-1.5 text-xs"
                                data-analytics-ticket-creation-row
                                data-analytics-ticket-creation-row-key={channel.channelKey || channel.channelId}
                                data-analytics-ticket-creation-row-type={channel.type}
                                data-analytics-ticket-creation-row-ready={ready ? 'true' : 'false'}
                                data-analytics-ticket-creation-row-mode={check?.runStatus || ''}
                            >
                                <span className="min-w-0 truncate">{channel.name || channel.channelKey || channel.type}</span>
                                <Badge variant={ready ? 'secondary' : 'outline'} className="font-normal">
                                    {ready ? t('Every message') : t('Thread updates')}
                                </Badge>
                            </div>
                        );
                    })}
                </div>
            </div>
            <div
                className="mt-4 rounded-md border bg-muted/20 p-3"
                data-analytics-reply-route-proof
                data-analytics-reply-route-proof-total={replyRouteProof.total}
                data-analytics-reply-route-proof-ready={replyRouteProof.ready}
                data-analytics-reply-route-proof-blocked={replyRouteProof.blocked}
            >
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <div>
                        <div className="text-xs font-medium uppercase text-muted-foreground">{t('Reply-route proof')}</div>
                        <div className="mt-1 text-sm font-medium">{t('Answer from app route')}</div>
                    </div>
                    <Badge variant={replyRouteProof.blocked === 0 ? 'secondary' : 'destructive'} className="font-normal">
                        {replyRouteProof.ready.toLocaleString()}/{replyRouteProof.total.toLocaleString()} {t('ready')}
                    </Badge>
                </div>
                <div className="grid gap-2 md:grid-cols-2">
                    {channelLedgerItems.map(channel => {
                        const check = channelReplyRouteCheck(channel);
                        const ready = channelReplyRouteReady(channel);
                        return (
                            <div
                                key={`reply-route:${channel.channelId || channel.channelKey || channel.type}`}
                                className="flex min-w-0 items-center justify-between gap-2 rounded-md border bg-background px-2 py-1.5 text-xs"
                                data-analytics-reply-route-row
                                data-analytics-reply-route-row-key={channel.channelKey || channel.channelId}
                                data-analytics-reply-route-row-type={channel.type}
                                data-analytics-reply-route-row-ready={ready ? 'true' : 'false'}
                                data-analytics-reply-route-row-proof-key={check?.key || ''}
                            >
                                <span className="min-w-0 truncate">{channel.name || channel.channelKey || channel.type}</span>
                                <Badge variant={ready ? 'secondary' : 'outline'} className="font-normal">
                                    {ready ? t('Can answer') : t('No route proof')}
                                </Badge>
                            </div>
                        );
                    })}
                </div>
            </div>
            <div
                className="mt-4 rounded-md border bg-muted/20 p-3"
                data-analytics-human-loop-proof
                data-analytics-human-loop-proof-ready={humanLoopProof.ready ? 'true' : 'false'}
                data-analytics-human-loop-proof-rules={humanLoopProof.rules}
                data-analytics-human-loop-proof-runs={humanLoopProof.successfulRuns}
                data-analytics-human-loop-proof-pending={humanLoopProof.pendingApprovals}
            >
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <div>
                        <div className="text-xs font-medium uppercase text-muted-foreground">{t('Human-loop proof')}</div>
                        <div className="mt-1 text-sm font-medium">{t('Agent prepares, editor approves')}</div>
                    </div>
                    <Badge variant={humanLoopProof.ready ? 'secondary' : 'destructive'} className="font-normal">
                        {humanLoopProof.ready ? t('Ready') : t('Blocked')}
                    </Badge>
                </div>
                <div className="grid gap-2 text-xs md:grid-cols-3">
                    <div className="rounded-md border bg-background px-2 py-1.5">
                        <div className="text-muted-foreground">{t('Approval automations')}</div>
                        <div className="font-medium">{humanLoopProof.rules.toLocaleString()}</div>
                    </div>
                    <div className="rounded-md border bg-background px-2 py-1.5">
                        <div className="text-muted-foreground">{t('Proof runs')}</div>
                        <div className="font-medium">{humanLoopProof.successfulRuns.toLocaleString()}</div>
                    </div>
                    <div className="rounded-md border bg-background px-2 py-1.5">
                        <div className="text-muted-foreground">{t('Pending approvals')}</div>
                        <div className="font-medium">{humanLoopProof.pendingApprovals.toLocaleString()}</div>
                    </div>
                </div>
                {humanLoopProof.items.length > 0 && (
                    <div className="mt-2 grid gap-2 md:grid-cols-2">
                        {humanLoopProof.items.slice(0, 4).map(item => (
                            <div
                                key={`human-loop:${item.issueId || item.runId || item.replyId}`}
                                className="flex min-w-0 items-center justify-between gap-2 rounded-md border bg-background px-2 py-1.5 text-xs"
                                data-analytics-human-loop-row
                                data-analytics-human-loop-row-issue={item.issueId || ''}
                                data-analytics-human-loop-row-reply={item.replyId || ''}
                                data-analytics-human-loop-row-run={item.runId || ''}
                            >
                                <span className="min-w-0 truncate">{item.detail || item.label || t('Approval draft prepared')}</span>
                                <Badge variant="outline" className="font-normal">{item.replyId || item.runId || t('proof')}</Badge>
                            </div>
                        ))}
                    </div>
                )}
            </div>
            <div
                className="mt-4 rounded-md border bg-muted/20 p-3"
                data-analytics-channel-autopilot-proof
                data-analytics-channel-autopilot-proof-total={channelAutopilotProof.total}
                data-analytics-channel-autopilot-proof-ready={channelAutopilotProof.ready}
                data-analytics-channel-autopilot-proof-blocked={channelAutopilotProof.blocked}
            >
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <div>
                        <div className="text-xs font-medium uppercase text-muted-foreground">{t('Channel autopilot proof')}</div>
                        <div className="mt-1 text-sm font-medium">{t('Channel agent prepares review package')}</div>
                    </div>
                    <Badge variant={channelAutopilotProof.blocked === 0 ? 'secondary' : 'destructive'} className="font-normal">
                        {channelAutopilotProof.ready.toLocaleString()}/{channelAutopilotProof.total.toLocaleString()} {t('ready')}
                    </Badge>
                </div>
                <div className="grid gap-2 md:grid-cols-2">
                    {channelAutopilotProof.items.map(item => (
                        <div
                            key={`channel-autopilot:${item.channelId || item.channelKey || item.type}`}
                            className="flex min-w-0 items-center justify-between gap-2 rounded-md border bg-background px-2 py-1.5 text-xs"
                            data-analytics-channel-autopilot-row
                            data-analytics-channel-autopilot-row-key={item.channelKey || item.channelId}
                            data-analytics-channel-autopilot-row-type={item.type}
                            data-analytics-channel-autopilot-row-ready={item.ready ? 'true' : 'false'}
                            data-analytics-channel-autopilot-row-proof-key={item.proofKey || ''}
                            data-analytics-channel-autopilot-row-reply={item.replyId || ''}
                            data-analytics-channel-autopilot-row-run={item.runId || ''}
                        >
                            <span className="min-w-0 truncate">{item.name || item.channelKey || item.type}</span>
                            <Badge variant={item.ready ? 'secondary' : 'outline'} className="font-normal">
                                {item.ready ? t('Prepared') : t('No prep proof')}
                            </Badge>
                        </div>
                    ))}
                </div>
            </div>
            <div
                className="mt-4 rounded-md border bg-muted/20 p-3"
                data-analytics-knowledge-assist-proof
                data-analytics-knowledge-assist-proof-ready={knowledgeAssistProof.ready ? 'true' : 'false'}
                data-analytics-knowledge-assist-proof-runs={knowledgeAssistProof.successfulRuns}
                data-analytics-knowledge-assist-proof-citations={knowledgeAssistProof.citationRuns}
                data-analytics-knowledge-assist-proof-gaps={knowledgeAssistProof.gapRuns}
                data-analytics-knowledge-assist-proof-open-gaps={knowledgeAssistProof.openGaps}
            >
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <div>
                        <div className="text-xs font-medium uppercase text-muted-foreground">{t('Knowledge assist proof')}</div>
                        <div className="mt-1 text-sm font-medium">{t('Agent answers cite KB or record gaps')}</div>
                    </div>
                    <Badge variant={knowledgeAssistProof.ready ? 'secondary' : 'destructive'} className="font-normal">
                        {knowledgeAssistProof.ready ? t('Ready') : t('Blocked')}
                    </Badge>
                </div>
                <div className="grid gap-2 text-xs md:grid-cols-4">
                    <div className="rounded-md border bg-background px-2 py-1.5">
                        <div className="text-muted-foreground">{t('Assist runs')}</div>
                        <div className="font-medium">{knowledgeAssistProof.successfulRuns.toLocaleString()}</div>
                    </div>
                    <div className="rounded-md border bg-background px-2 py-1.5">
                        <div className="text-muted-foreground">{t('Citation runs')}</div>
                        <div className="font-medium">{knowledgeAssistProof.citationRuns.toLocaleString()}</div>
                    </div>
                    <div className="rounded-md border bg-background px-2 py-1.5">
                        <div className="text-muted-foreground">{t('Gap runs')}</div>
                        <div className="font-medium">{knowledgeAssistProof.gapRuns.toLocaleString()}</div>
                    </div>
                    <div className="rounded-md border bg-background px-2 py-1.5">
                        <div className="text-muted-foreground">{t('Open gaps')}</div>
                        <div className="font-medium">{knowledgeAssistProof.openGaps.toLocaleString()}</div>
                    </div>
                </div>
                {knowledgeAssistProof.items.length > 0 && (
                    <div className="mt-2 grid gap-2 md:grid-cols-2">
                        {knowledgeAssistProof.items.slice(0, 4).map(item => (
                            <div
                                key={`knowledge-assist:${item.issueId || item.runId || item.replyId}`}
                                className="flex min-w-0 items-center justify-between gap-2 rounded-md border bg-background px-2 py-1.5 text-xs"
                                data-analytics-knowledge-assist-row
                                data-analytics-knowledge-assist-row-issue={item.issueId || ''}
                                data-analytics-knowledge-assist-row-run={item.runId || ''}
                                data-analytics-knowledge-assist-row-citations={item.citationCount ?? 0}
                                data-analytics-knowledge-assist-row-gap={item.knowledgeGapId || ''}
                            >
                                <span className="min-w-0 truncate">{item.detail || item.label || t('Knowledge-backed answer')}</span>
                                <Badge variant="outline" className="font-normal">
                                    {(item.citationCount ?? 0) > 0 ? t('cited') : item.knowledgeGapId ? t('gap') : t('proof')}
                                </Badge>
                            </div>
                        ))}
                    </div>
                )}
            </div>
            <div
                className="mt-4 rounded-md border bg-muted/20 p-3"
                data-analytics-account-intelligence-proof
                data-analytics-account-intelligence-proof-ready={accountIntelligenceProof.ready ? 'true' : 'false'}
                data-analytics-account-intelligence-proof-accounts={accountIntelligenceProof.accounts}
                data-analytics-account-intelligence-proof-actions={accountIntelligenceProof.actions}
                data-analytics-account-intelligence-proof-risks={accountIntelligenceProof.openRisks}
                data-analytics-account-intelligence-proof-features={accountIntelligenceProof.featureRequests}
                data-analytics-account-intelligence-proof-sync-failures={accountIntelligenceProof.failedSyncRuns}
            >
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <div>
                        <div className="text-xs font-medium uppercase text-muted-foreground">{t('Account intelligence proof')}</div>
                        <div className="mt-1 text-sm font-medium">{t('Account health, risk, and demand signals')}</div>
                    </div>
                    <Badge variant={accountIntelligenceProof.ready ? 'secondary' : 'destructive'} className="font-normal">
                        {accountIntelligenceProof.ready ? t('Ready') : t('Blocked')}
                    </Badge>
                </div>
                <div className="grid gap-2 text-xs md:grid-cols-5">
                    <div className="rounded-md border bg-background px-2 py-1.5">
                        <div className="text-muted-foreground">{t('Accounts')}</div>
                        <div className="font-medium">{accountIntelligenceProof.accounts.toLocaleString()}</div>
                    </div>
                    <div className="rounded-md border bg-background px-2 py-1.5">
                        <div className="text-muted-foreground">{t('Actions')}</div>
                        <div className="font-medium">{accountIntelligenceProof.actions.toLocaleString()}</div>
                    </div>
                    <div className="rounded-md border bg-background px-2 py-1.5">
                        <div className="text-muted-foreground">{t('Open risks')}</div>
                        <div className="font-medium">{accountIntelligenceProof.openRisks.toLocaleString()}</div>
                    </div>
                    <div className="rounded-md border bg-background px-2 py-1.5">
                        <div className="text-muted-foreground">{t('Feature requests')}</div>
                        <div className="font-medium">{accountIntelligenceProof.featureRequests.toLocaleString()}</div>
                    </div>
                    <div className="rounded-md border bg-background px-2 py-1.5">
                        <div className="text-muted-foreground">{t('Sync failures')}</div>
                        <div className="font-medium">{accountIntelligenceProof.failedSyncRuns.toLocaleString()}</div>
                    </div>
                </div>
                {accountIntelligenceProof.items.length > 0 && (
                    <div className="mt-2 grid gap-2 md:grid-cols-2">
                        {accountIntelligenceProof.items.slice(0, 4).map(item => (
                            <div
                                key={`account-intelligence:${item.accountId || item.actionKind || item.occurredAt}`}
                                className="flex min-w-0 items-center justify-between gap-2 rounded-md border bg-background px-2 py-1.5 text-xs"
                                data-analytics-account-intelligence-row
                                data-analytics-account-intelligence-row-account={item.accountId || ''}
                                data-analytics-account-intelligence-row-action={item.actionKind || ''}
                                data-analytics-account-intelligence-row-health={item.healthStatus || ''}
                                data-analytics-account-intelligence-row-risks={item.openRisks ?? 0}
                            >
                                <span className="min-w-0 truncate">{item.accountName || item.domain || item.accountKey || item.detail || t('Account action')}</span>
                                <Badge variant="outline" className="font-normal">
                                    {item.actionLabel || item.actionKind || item.healthStatus || t('action')}
                                </Badge>
                            </div>
                        ))}
                    </div>
                )}
            </div>
            <div
                className="mt-4 rounded-md border bg-muted/20 p-3"
                data-analytics-ticket-workflow-proof
                data-analytics-ticket-workflow-proof-ready={ticketWorkflowProof.ready ? 'true' : 'false'}
                data-analytics-ticket-workflow-proof-transitions={ticketWorkflowProof.transitions}
                data-analytics-ticket-workflow-proof-ongoing={ticketWorkflowProof.ongoingTransitions}
                data-analytics-ticket-workflow-proof-done={ticketWorkflowProof.doneTransitions}
                data-analytics-ticket-workflow-proof-issues={ticketWorkflowProof.successfulIssues}
            >
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <div>
                        <div className="text-xs font-medium uppercase text-muted-foreground">{t('Ticket workflow proof')}</div>
                        <div className="mt-1 text-sm font-medium">{t('Open to ongoing to done')}</div>
                    </div>
                    <Badge variant={ticketWorkflowProof.ready ? 'secondary' : 'destructive'} className="font-normal">
                        {ticketWorkflowProof.ready ? t('Ready') : t('Blocked')}
                    </Badge>
                </div>
                <div className="grid gap-2 text-xs md:grid-cols-4">
                    <div className="rounded-md border bg-background px-2 py-1.5">
                        <div className="text-muted-foreground">{t('Transitions')}</div>
                        <div className="font-medium">{ticketWorkflowProof.transitions.toLocaleString()}</div>
                    </div>
                    <div className="rounded-md border bg-background px-2 py-1.5">
                        <div className="text-muted-foreground">{t('Ongoing')}</div>
                        <div className="font-medium">{ticketWorkflowProof.ongoingTransitions.toLocaleString()}</div>
                    </div>
                    <div className="rounded-md border bg-background px-2 py-1.5">
                        <div className="text-muted-foreground">{t('Done')}</div>
                        <div className="font-medium">{ticketWorkflowProof.doneTransitions.toLocaleString()}</div>
                    </div>
                    <div className="rounded-md border bg-background px-2 py-1.5">
                        <div className="text-muted-foreground">{t('Proven tickets')}</div>
                        <div className="font-medium">{ticketWorkflowProof.successfulIssues.toLocaleString()}</div>
                    </div>
                </div>
                {ticketWorkflowProof.items.length > 0 && (
                    <div className="mt-2 grid gap-2 md:grid-cols-2">
                        {ticketWorkflowProof.items.slice(0, 4).map(item => (
                            <div
                                key={`ticket-workflow:${item.issueId || item.runId || item.occurredAt}`}
                                className="flex min-w-0 items-center justify-between gap-2 rounded-md border bg-background px-2 py-1.5 text-xs"
                                data-analytics-ticket-workflow-row
                                data-analytics-ticket-workflow-row-issue={item.issueId || ''}
                                data-analytics-ticket-workflow-row-events={(item.eventIds ?? []).join(',')}
                            >
                                <span className="min-w-0 truncate">{item.detail || item.label || t('Ticket moved through board')}</span>
                                <Badge variant="outline" className="font-normal">{item.issueId || t('ticket')}</Badge>
                            </div>
                        ))}
                    </div>
                )}
            </div>
            <div
                className="mt-4 border-t pt-3"
                data-channel-readiness-ledger
                data-channel-readiness-ledger-count={channelLedgerItems.length}
                data-channel-readiness-ledger-ready={launchProof.channels.ready}
                data-channel-readiness-ledger-blocked={launchProof.channels.blocked}
                data-channel-readiness-ticket-creation-ready={ticketCreationProof.ready}
                data-channel-readiness-ticket-creation-blocked={ticketCreationProof.blocked}
                data-channel-readiness-reply-route-ready={replyRouteProof.ready}
                data-channel-readiness-reply-route-blocked={replyRouteProof.blocked}
                data-channel-readiness-channel-autopilot-ready={channelAutopilotProof.ready}
                data-channel-readiness-channel-autopilot-blocked={channelAutopilotProof.blocked}
            >
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <div className="text-xs font-medium uppercase text-muted-foreground">
                        {t('Channel readiness ledger')}
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                        <Badge variant="outline" className="font-normal">
                            {launchProof.channels.required.toLocaleString()} {t('required')}
                        </Badge>
                        <Badge variant="secondary" className="font-normal">
                            {launchProof.channels.ready.toLocaleString()} {t('ready')}
                        </Badge>
                        {launchProof.channels.blocked > 0 && (
                            <Badge variant="destructive" className="font-normal">
                                {launchProof.channels.blocked.toLocaleString()} {t('blocked')}
                            </Badge>
                        )}
                    </div>
                </div>
                {channelLedgerItems.length === 0 ? (
                    <div data-channel-readiness-ledger-empty className="text-sm text-muted-foreground">
                        {t('No channel proof required yet')}
                    </div>
                ) : (
                    <div className="divide-y rounded-md border">
                        {channelLedgerItems.map(channel => (
                            <Button
                                key={channel.channelId || channel.channelKey || channel.type}
                                type="button"
                                variant="ghost"
                                className="h-auto w-full min-w-0 items-start justify-start gap-3 rounded-none px-3 py-2 text-left text-sm whitespace-normal hover:bg-muted/50"
                                data-channel-readiness-row
                                data-channel-readiness-row-key={channel.channelKey || channel.channelId}
                                data-channel-readiness-row-type={channel.type}
                                data-channel-readiness-row-ready={channel.ready ? 'true' : 'false'}
                                data-channel-readiness-row-required={channel.required ? 'true' : 'false'}
                                data-channel-readiness-row-proof-kind={channel.proofKind}
                                data-channel-readiness-row-ticket-mode={channelTicketCreationCheck(channel)?.runStatus || ''}
                                data-channel-readiness-row-ticket-creation-ready={channelTicketCreationReady(channel) ? 'true' : 'false'}
                                data-channel-readiness-row-reply-route-ready={channelReplyRouteReady(channel) ? 'true' : 'false'}
                                data-channel-readiness-row-reply-route-proof-key={channelReplyRouteCheck(channel)?.key || ''}
                                data-channel-readiness-row-channel-autopilot-ready={channelAutopilotReady(channel) ? 'true' : 'false'}
                                data-channel-readiness-row-channel-autopilot-proof-key={channelAutopilotCheck(channel)?.key || ''}
                                onClick={() => onOpen(channelLaunchProofRoute(channel))}
                            >
                                <div className="min-w-0 flex-1">
                                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                                        <span className="min-w-0 truncate font-medium">
                                            {channel.name || channel.channelKey || channel.type}
                                        </span>
                                        <Badge variant={channelReadinessVariant(channel)} className="font-normal">
                                            {t(channelReadinessLabel(channel))}
                                        </Badge>
                                        <Badge variant="outline" className="font-normal">
                                            {channel.passed.toLocaleString()}/{channel.checks.toLocaleString()}
                                        </Badge>
                                    </div>
                                    <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                                        {channelReadinessDetail(channel)}
                                    </div>
                                </div>
                                <div className="flex shrink-0 flex-col items-end gap-1 text-xs text-muted-foreground">
                                    <span>{channel.proofKind || channel.type}</span>
                                    <ExternalLink className="size-3.5" />
                                </div>
                            </Button>
                        ))}
                    </div>
                )}
                {launchProof.channels.items.length > channelLedgerItems.length && (
                    <div className="mt-2 text-xs text-muted-foreground">
                        +{launchProof.channels.items.length - channelLedgerItems.length} {t('more channels')}
                    </div>
                )}
            </div>
            {blockedChannels.length > 0 && (
                <div className="mt-3">
                    <div className="mb-2 text-xs font-medium uppercase text-muted-foreground">
                        {t('Channel proof blockers')}
                    </div>
                    <div className="grid gap-2 md:grid-cols-2">
                        {blockedChannels.slice(0, 6).map(channel => (
                            <Button
                                key={channel.channelId}
                                type="button"
                                variant="outline"
                                className="h-auto min-w-0 flex-col items-stretch gap-1.5 bg-muted/20 p-2 text-left text-sm"
                                onClick={() => onOpen(channelLaunchProofRoute(channel))}
                            >
                                <div className="mb-1 flex items-center justify-between gap-2">
                                    <span className="min-w-0 truncate font-medium">{channel.name || channel.channelKey || channel.type}</span>
                                    <div className="flex shrink-0 items-center gap-1.5">
                                        <Badge variant="outline" className="font-normal">
                                        {channel.passed}/{channel.checks}
                                        </Badge>
                                        <ExternalLink className="size-3.5 text-muted-foreground" />
                                    </div>
                                </div>
                                <div className="truncate text-xs text-muted-foreground">
                                    {(channel.blockers[0]?.detail || channel.blockers[0]?.label || channel.type)}
                                </div>
                            </Button>
                        ))}
                    </div>
                    {blockedChannels.length > 6 && (
                        <div className="mt-2 text-xs text-muted-foreground">
                            +{blockedChannels.length - 6} {t('more')}
                        </div>
                    )}
                </div>
            )}
            {launchProof.blockers.length > 0 && (
                <div className="mt-3">
                    <div className="mb-2 text-xs font-medium uppercase text-muted-foreground">
                        {t('Launch proof blockers')}
                    </div>
                    <div className="grid gap-2 md:grid-cols-2">
                        {launchProof.blockers.slice(0, 6).map(item => {
                            const runnable = runnableLaunchProofBlockerKeys.has(item.key);
                            const route = readinessRoute(item.key);
                            return (
                                <div
                                    key={item.key}
                                    data-launch-proof-blocker
                                    data-launch-proof-blocker-key={item.key}
                                    className="rounded-md border bg-muted/20 px-2.5 py-2 text-sm"
                                >
                                    <div className="flex min-w-0 items-center justify-between gap-2">
                                        <span className="min-w-0 truncate font-medium">{t(item.label || item.key)}</span>
                                        <div className="flex shrink-0 items-center gap-1.5">
                                            <Badge variant="outline" className="font-normal">
                                                {item.count.toLocaleString()}
                                            </Badge>
                                            {runnable && (
                                                <Badge variant="secondary" className="font-normal">
                                                    {t('Runnable')}
                                                </Badge>
                                            )}
                                        </div>
                                    </div>
                                    <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                                        {item.count.toLocaleString()} {t('affected')}
                                    </div>
                                    {(runnable || route) && (
                                        <div className="mt-2 flex flex-wrap justify-end gap-1.5">
                                            {runnable && (
                                                <Button
                                                    type="button"
                                                    variant="outline"
                                                    size="sm"
                                                    className="h-7 gap-1 px-2"
                                                    onClick={onRunProof}
                                                    disabled={proofRunning}
                                                >
                                                    {proofRunning
                                                        ? <Loader className="size-3.5 animate-spin" />
                                                        : <Rocket className="size-3.5" />}
                                                    {t('Run proof')}
                                                </Button>
                                            )}
                                            {route && (
                                                <Button
                                                    type="button"
                                                    variant="ghost"
                                                    size="sm"
                                                    className="h-7 gap-1 px-2"
                                                    onClick={() => onOpen(route)}
                                                >
                                                    {t('Open')}
                                                    <ExternalLink className="size-3.5" />
                                                </Button>
                                            )}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                    {launchProof.blockers.length > 6 && (
                        <div className="mt-2 text-xs text-muted-foreground">
                            +{launchProof.blockers.length - 6} {t('more')}
                        </div>
                    )}
                </div>
            )}
            {(launchProof.warnings ?? []).length > 0 && (
                <div className="mt-3">
                    <div className="mb-2 text-xs font-medium uppercase text-muted-foreground">
                        {t('Launch proof warnings')}
                    </div>
                    <div className="grid gap-2 md:grid-cols-2">
                        {(launchProof.warnings ?? []).slice(0, 6).map(item => {
                            const runnable = runnableLaunchProofWarningKeys.has(item.key);
                            const route = readinessRoute(item.key);
                            return (
                                <div
                                    key={item.key}
                                    data-launch-proof-warning
                                    data-launch-proof-warning-key={item.key}
                                    className="rounded-md border bg-muted/20 px-2.5 py-2 text-sm"
                                >
                                    <div className="flex min-w-0 items-center justify-between gap-2">
                                        <span className="min-w-0 truncate font-medium">{t(item.label || item.key)}</span>
                                        <div className="flex shrink-0 items-center gap-1.5">
                                            <Badge variant="outline" className="font-normal">
                                                {item.count.toLocaleString()}
                                            </Badge>
                                            {runnable && (
                                                <Badge variant="secondary" className="font-normal">
                                                    {t('Runnable')}
                                                </Badge>
                                            )}
                                        </div>
                                    </div>
                                    <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                                        {item.count.toLocaleString()} {t('affected')}
                                    </div>
                                    {(runnable || route) && (
                                        <div className="mt-2 flex flex-wrap justify-end gap-1.5">
                                            {runnable && (
                                                <Button
                                                    type="button"
                                                    variant="outline"
                                                    size="sm"
                                                    className="h-7 gap-1 px-2"
                                                    onClick={onRunProof}
                                                    disabled={proofRunning}
                                                >
                                                    {proofRunning
                                                        ? <Loader className="size-3.5 animate-spin" />
                                                        : <Rocket className="size-3.5" />}
                                                    {t('Run proof')}
                                                </Button>
                                            )}
                                            {route && (
                                                <Button
                                                    type="button"
                                                    variant="ghost"
                                                    size="sm"
                                                    className="h-7 gap-1 px-2"
                                                    onClick={() => onOpen(route)}
                                                >
                                                    {t('Open')}
                                                    <ExternalLink className="size-3.5" />
                                                </Button>
                                            )}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                    {(launchProof.warnings ?? []).length > 6 && (
                        <div className="mt-2 text-xs text-muted-foreground">
                            +{(launchProof.warnings ?? []).length - 6} {t('more')}
                        </div>
                    )}
                </div>
            )}
            {ticketEvidence.length > 0 && (
                <div className="mt-4 border-t pt-3">
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                        <div className="text-xs font-medium uppercase text-muted-foreground">
                            {t('Evidence tickets')}
                        </div>
                        <Badge variant="outline" className="font-normal">
                            {ticketEvidence.length.toLocaleString()}
                        </Badge>
                    </div>
                    <div className="grid gap-2 md:grid-cols-2">
                        {ticketEvidence.map(item => (
                            <Button
                                key={item.key}
                                type="button"
                                variant="outline"
                                className="h-auto min-w-0 flex-col items-stretch gap-1.5 bg-muted/20 p-2 text-left text-sm"
                                onClick={() => onOpen(item.kind === 'account' ? accountProofRoute(item.accountId) : ticketProofRoute(item.issueId))}
                            >
                                <div className="flex min-w-0 items-center justify-between gap-2">
                                    <span className="min-w-0 truncate font-medium">
                                        {t(item.label)}
                                    </span>
                                    <div className="flex shrink-0 items-center gap-1.5">
                                        <Badge variant={item.status === 'done' ? 'secondary' : 'outline'} className="font-normal">
                                            {t(item.kind === 'workflow' ? 'Workflow' : item.kind === 'automation' ? 'Automation' : item.kind === 'knowledge' ? 'Knowledge' : item.kind === 'account' ? 'Account' : 'Channel')}
                                        </Badge>
                                        <ExternalLink className="size-3.5 text-muted-foreground" />
                                    </div>
                                </div>
                                <div className="truncate text-xs text-muted-foreground">
                                    {[item.channelName, item.detail].filter(Boolean).join(' · ')}
                                </div>
                                <div className="flex flex-wrap gap-1.5 text-xs text-muted-foreground">
                                    {item.issueId && (
                                        <Badge variant="outline" className="font-normal">
                                            {t('Ticket')}: {item.issueId}
                                        </Badge>
                                    )}
                                    {item.accountId && (
                                        <Badge variant="outline" className="font-normal">
                                            {t('Account')}: {item.accountName || item.accountId}
                                        </Badge>
                                    )}
                                    {item.replyId && (
                                        <Badge variant="outline" className="font-normal">
                                            {t('Reply')}: {item.replyId}
                                        </Badge>
                                    )}
                                    {item.runId && (
                                        <Badge variant="outline" className="font-normal">
                                            {t('Run')}: {item.runId}
                                        </Badge>
                                    )}
                                    {item.source && (
                                        <Badge variant="outline" className="font-normal">
                                            {item.source}
                                        </Badge>
                                    )}
                                </div>
                            </Button>
                        ))}
                    </div>
                </div>
            )}
            {latestRun && (
                <div className="mt-4 border-t pt-3">
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                        <div className="text-xs font-medium uppercase text-muted-foreground">
                            {t('Latest proof run')}
                        </div>
                        <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                            <span>{latestRun.ran.toLocaleString()} {t('ran')}</span>
                            <span>·</span>
                            <span>{latestRun.failed.toLocaleString()} {t('failed')}</span>
                            <span>·</span>
                            <span>{latestRun.skipped.toLocaleString()} {t('skipped')}</span>
                            <Badge variant={readinessVariant(latestRun.launchReadiness.status)} className="font-normal">
                                {t(readinessLabel(latestRun.launchReadiness.status))}
                            </Badge>
                        </div>
                    </div>
                    {latestRun.actions.length === 0 ? (
                        <div className="text-sm text-muted-foreground">{t('No automated proof steps ran')}</div>
                    ) : (
                        <div className="grid gap-2 md:grid-cols-2">
                            {latestRun.actions.map(action => {
                                const detail = launchActionDetail(action);
                                const route = launchActionRoute(action);
                                return (
                                    <div
                                        key={action.key}
                                        data-launch-proof-action
                                        data-launch-proof-action-key={action.key}
                                        className="rounded-md border bg-muted/20 px-2.5 py-2 text-sm"
                                    >
                                        <div className="flex min-w-0 items-center justify-between gap-2">
                                            <span className="min-w-0 truncate font-medium">{t(action.label || action.key)}</span>
                                            <Badge variant={launchActionVariant(action.status)} className="shrink-0 font-normal">
                                                {t(action.status || 'unknown')}
                                            </Badge>
                                        </div>
                                        {detail && (
                                            <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                                                {detail}
                                            </div>
                                        )}
                                        {route && (
                                            <div className="mt-2 flex justify-end">
                                                <Button
                                                    type="button"
                                                    variant="ghost"
                                                    size="sm"
                                                    className="h-7 gap-1 px-2"
                                                    onClick={() => onOpen(route)}
                                                >
                                                    {t('Open evidence')}
                                                    <ExternalLink className="size-3.5" />
                                                </Button>
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    )}
                    {runHistory.length > 1 && (
                        <div className="mt-3">
                            <div className="mb-2 text-xs font-medium uppercase text-muted-foreground">
                                {t('Recent proof history')}
                            </div>
                            <div className="space-y-1.5">
                                {runHistory.slice(1, 6).map((run, index) => {
                                    const key = run.id || `${run.startedAt || run.completedAt || index}`;
                                    return (
                                        <div key={key} className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/10 px-2.5 py-2 text-xs">
                                            <Badge variant={readinessVariant(run.launchReadiness.status)} className="font-normal">
                                                {t(readinessLabel(run.launchReadiness.status))}
                                            </Badge>
                                            <span className="text-muted-foreground">{proofRunTime(run) || t('Unknown time')}</span>
                                            <span className="ml-auto text-muted-foreground">
                                                {run.ran.toLocaleString()} {t('ran')} · {run.failed.toLocaleString()} {t('failed')} · {run.skipped.toLocaleString()} {t('skipped')}
                                            </span>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </section>
    );
}

export function Analytics({ projectId }: AnalyticsProps) {
    const { tenantId } = useParams<{ tenantId: string }>();
    const navigate = useNavigate();
    const { t } = useI18n();
    const [summary, setSummary] = useState<SupportAnalytics | null>(null);
    const [schemaHealth, setSchemaHealth] = useState<SupportSchemaHealth | null>(null);
    const [loading, setLoading] = useState(false);
    const [runningWorkflowProof, setRunningWorkflowProof] = useState(false);
    const [runningAutomationProof, setRunningAutomationProof] = useState(false);
    const [runningLaunchProof, setRunningLaunchProof] = useState(false);
    const [lastLaunchProofRun, setLastLaunchProofRun] = useState<SupportLaunchProofRunResult | null>(null);
    const [launchProofRuns, setLaunchProofRuns] = useState<SupportLaunchProofRunResult[]>([]);
    const projectPath = tenantId ? `/${tenantId}/${projectId}` : '';

    const openRoute = useCallback((path: string) => {
        if (!projectPath) return;
        void navigate(`${projectPath}${path}`);
    }, [navigate, projectPath]);

    const loadSummary = useCallback(() => {
        setLoading(true);
        void Promise.all([
            api.getSupportAnalytics(projectId),
            api.getSupportSchemaHealth(projectId),
            api.getSupportLaunchProofRuns(projectId, 10),
        ]).then(([analyticsRes, schemaRes, runsRes]) => {
            if (analyticsRes.error || !analyticsRes.data) {
                toast.error(analyticsRes.error || t('Could not load analytics'));
            } else {
                setSummary(analyticsRes.data);
            }
            if (schemaRes.error || !schemaRes.data) {
                toast.error(schemaRes.error || t('Could not load schema health'));
                return;
            }
            setSchemaHealth(schemaRes.data);
            if (runsRes.error || !runsRes.data) {
                toast.error(runsRes.error || t('Could not load proof history'));
            } else {
                setLaunchProofRuns(runsRes.data.items);
            }
        }).finally(() => setLoading(false));
    }, [projectId, t]);

    const runWorkflowProof = useCallback(async () => {
        if (runningWorkflowProof) return;
        setRunningWorkflowProof(true);
        const res = await api.runSupportWorkflowProof(projectId);
        setRunningWorkflowProof(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not run workflow proof'));
            return;
        }
        toast.success(
            `${t('Workflow proof')} ${res.data.successfulWorkflowLifecycleProofs.toLocaleString()}`
        );
        loadSummary();
    }, [loadSummary, projectId, runningWorkflowProof, t]);

    const runAutomationProof = useCallback(async () => {
        if (runningAutomationProof) return;
        setRunningAutomationProof(true);
        const res = await api.runSupportAutomationProof(projectId);
        setRunningAutomationProof(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not run automation proof'));
            return;
        }
        toast.success(
            `${t('Human-loop proofs')} ${res.data.successfulHumanLoopAutomationRuns.toLocaleString()}`
        );
        loadSummary();
    }, [loadSummary, projectId, runningAutomationProof, t]);

    const runLaunchProof = useCallback(async () => {
        if (runningLaunchProof) return;
        setRunningLaunchProof(true);
        const res = await api.runSupportLaunchProof(projectId);
        setRunningLaunchProof(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not run launch proof'));
            return;
        }
        const proofRun = res.data;
        setLastLaunchProofRun(proofRun);
        setLaunchProofRuns(prev => [
            proofRun,
            ...prev.filter(run => !run.id || run.id !== proofRun.id),
        ].slice(0, 10));
        const passed = Math.max(0, proofRun.ran - proofRun.failed);
        if (proofRun.failed > 0) {
            toast.warning(`${t('Launch proof steps')} ${passed.toLocaleString()}/${proofRun.ran.toLocaleString()}`);
        } else {
            toast.success(`${t('Launch proof steps')} ${proofRun.ran.toLocaleString()}`);
        }
        loadSummary();
    }, [loadSummary, projectId, runningLaunchProof, t]);

    useEffect(() => {
        const timer = window.setTimeout(() => loadSummary(), 0);
        return () => window.clearTimeout(timer);
    }, [loadSummary]);

    if (loading && !summary) {
        return (
            <div className="flex min-h-64 items-center justify-center text-muted-foreground">
                <Loader className="mr-2 size-4 animate-spin" />
                {t('Loading')}
            </div>
        );
    }

    if (!summary) {
        return (
            <div className="w-full max-w-6xl space-y-5">
                <div className="flex items-center justify-between gap-3">
                    <div>
                        <h1 className="text-xl font-semibold">{t('Analytics')}</h1>
                    </div>
                    {loading && <Loader className="size-4 animate-spin text-muted-foreground" />}
                </div>
                {schemaHealth && <SchemaHealthPanel schemaHealth={schemaHealth} t={t} />}
                <div className="flex min-h-64 items-center justify-center text-muted-foreground">
                    {t('No analytics')}
                </div>
            </div>
        );
    }

    const latestLaunchProofRun = lastLaunchProofRun ?? summary.latestLaunchProofRun ?? launchProofRuns[0] ?? null;
    const latestLaunchProofRunId = latestLaunchProofRun?.id || '';
    const launchProofRunHistory = latestLaunchProofRun
        ? [
            latestLaunchProofRun,
            ...launchProofRuns.filter(run => (run.id || '') !== latestLaunchProofRunId),
        ].slice(0, 10)
        : launchProofRuns;
    const reportHref = analyticsReportHref(summary);

    return (
        <div className="w-full max-w-6xl space-y-5">
            <div className="flex items-center justify-between gap-3">
                <div>
                    <h1 className="text-xl font-semibold">{t('Analytics')}</h1>
                </div>
                <div className="flex items-center gap-2">
                    <Button type="button" size="sm" variant="outline" asChild>
                        <a
                            href={reportHref}
                            download={`support-report-${projectId}.csv`}
                            data-support-report-download
                        >
                            <Download className="size-4" />
                            {t('Export CSV')}
                        </a>
                    </Button>
                    {loading && <Loader className="size-4 animate-spin text-muted-foreground" />}
                </div>
            </div>
            {summary.launchReadiness && (
                <section className="rounded-md border bg-background p-4">
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                        <div className="flex min-w-0 items-center gap-2">
                            {summary.launchReadiness.status === 'ready'
                                ? <CheckCircle2 className="size-4 text-emerald-600" />
                                : <AlertTriangle className="size-4 text-destructive" />}
                            <h2 className="text-sm font-medium">{t('Launch readiness')}</h2>
                        </div>
                        <Badge variant={readinessVariant(summary.launchReadiness.status)} className="font-normal">
                            {t(readinessLabel(summary.launchReadiness.status))}
                        </Badge>
                    </div>
                    <div className="grid gap-3 md:grid-cols-2">
                        <div>
                            <div className="mb-2 text-xs font-medium uppercase text-muted-foreground">{t('Blockers')}</div>
                            {summary.launchReadiness.blockers.length === 0 ? (
                                <div className="text-sm text-muted-foreground">{t('None')}</div>
                            ) : (
                                <div className="space-y-1.5">
                                    {summary.launchReadiness.blockers.map(item => (
                                        <ReadinessItemRow
                                            key={item.key}
                                            item={item}
                                            badgeVariant="destructive"
                                            onOpen={openRoute}
                                            onRunWorkflowProof={runWorkflowProof}
                                            onRunAutomationProof={runAutomationProof}
                                            onRunLaunchProof={runLaunchProof}
                                            workflowProofRunning={runningWorkflowProof}
                                            automationProofRunning={runningAutomationProof}
                                            launchProofRunning={runningLaunchProof}
                                            t={t}
                                        />
                                    ))}
                                </div>
                            )}
                        </div>
                        <div>
                            <div className="mb-2 text-xs font-medium uppercase text-muted-foreground">{t('Warnings')}</div>
                            {summary.launchReadiness.warnings.length === 0 ? (
                                <div className="text-sm text-muted-foreground">{t('None')}</div>
                            ) : (
                                <div className="space-y-1.5">
                                    {summary.launchReadiness.warnings.map(item => (
                                        <ReadinessItemRow
                                            key={item.key}
                                            item={item}
                                            badgeVariant="outline"
                                            onOpen={openRoute}
                                            onRunWorkflowProof={runWorkflowProof}
                                            onRunAutomationProof={runAutomationProof}
                                            onRunLaunchProof={runLaunchProof}
                                            workflowProofRunning={runningWorkflowProof}
                                            automationProofRunning={runningAutomationProof}
                                            launchProofRunning={runningLaunchProof}
                                            t={t}
                                        />
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                </section>
            )}
            {summary.launchProof && (
                <LaunchProofPanel
                    projectId={projectId}
                    launchProof={summary.launchProof}
                    latestRun={latestLaunchProofRun}
                    runHistory={launchProofRunHistory}
                    onOpen={openRoute}
                    onRunProof={runLaunchProof}
                    proofRunning={runningLaunchProof}
                    t={t}
                />
            )}
            {schemaHealth && <SchemaHealthPanel schemaHealth={schemaHealth} t={t} />}
            <SupportHealthInsights
                items={summary.supportHealthInsights}
                onOpen={openRoute}
                t={t}
            />
            <ChannelRemediationPanel
                items={summary.latestChannelRemediations}
                onOpen={openRoute}
                t={t}
            />
            <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
                <QueueAction
                    label={t('Open tickets')}
                    value={summary.openIssues}
                    icon={InboxIcon}
                    onClick={() => openRoute('/inbox?filter=open')}
                />
                <QueueAction
                    label={t('Needs approval')}
                    value={summary.issuesNeedingApproval}
                    icon={AlertTriangle}
                    onClick={() => openRoute('/inbox?filter=approvals')}
                />
                <QueueAction
                    label={t('Needs response')}
                    value={summary.issuesNeedingResponse}
                    icon={AlertTriangle}
                    onClick={() => openRoute('/inbox?filter=needs-response')}
                />
                <QueueAction
                    label={t('Needs assignee')}
                    value={summary.unassignedIssues}
                    icon={AlertTriangle}
                    onClick={() => openRoute('/inbox?filter=unassigned')}
                />
                <QueueAction
                    label={t('Owner capacity')}
                    value={summary.queueOwnersAtCapacity}
                    icon={Users}
                    onClick={() => openRoute('/channels')}
                />
                <QueueAction
                    label={t('Overdue SLA')}
                    value={summary.overdueSlaEvents}
                    icon={AlertTriangle}
                    onClick={() => openRoute('/inbox?filter=overdue-sla')}
                />
                <QueueAction
                    label={t('SLA due soon')}
                    value={summary.dueSoonSlaEvents}
                    icon={AlertTriangle}
                    onClick={() => openRoute('/inbox?filter=due-soon-sla')}
                />
                <QueueAction
                    label={t('Knowledge gaps')}
                    value={summary.openKnowledgeGaps}
                    icon={BookOpen}
                    onClick={() => openRoute('/knowledge')}
                />
                <QueueAction
                    label={t('Accounts')}
                    value={summary.accountsNeedingAction}
                    icon={Building2}
                    onClick={() => openRoute('/accounts')}
                />
                <QueueAction
                    label={t('Failed automations')}
                    value={summary.failedAutomationRuns}
                    icon={Workflow}
                    onClick={() => openRoute('/automations')}
                />
                <QueueAction
                    label={t('Failed delivery')}
                    value={summary.failedDeliveryRuns + summary.failedOutboundMessages}
                    icon={Send}
                    onClick={() => openRoute('/inbox?filter=failed-delivery')}
                />
                <QueueAction
                    label={t('Channel events')}
                    value={summary.failedChannelSyncRuns + summary.failedChannelWebhookEvents + summary.unmatchedChannelWebhookEvents}
                    icon={BarChart3}
                    onClick={() => openRoute('/channels')}
                />
                <QueueAction
                    label={t('Provider validation')}
                    value={summary.activeChannelsMissingProviderValidation + summary.failedChannelValidationRuns}
                    icon={AlertTriangle}
                    onClick={() => openRoute('/channels')}
                />
                <QueueAction
                    label={t('Channel remediation')}
                    value={summary.channelRemediationItems}
                    icon={AlertTriangle}
                    onClick={() => openRoute('/channels')}
                />
                <QueueAction
                    label={t('Channel smoke')}
                    value={
                        summary.activeChannelsMissingSmoke
                        + summary.failedChannelSmokeRuns
                        + summary.activeChannelsMissingOutboundSmoke
                        + summary.failedOutboundChannelSmokeRuns
                        + summary.activeChannelsMissingLifecycleSmoke
                        + summary.failedLifecycleChannelSmokeRuns
                    }
                    icon={AlertTriangle}
                    onClick={() => openRoute('/channels')}
                />
            </div>
            <section className="space-y-3">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                        <Users className="size-4 text-muted-foreground" />
                        <h2 className="text-sm font-medium">{t('Support workload')}</h2>
                    </div>
                    <Badge variant="secondary" className="font-normal">
                        {summary.openWorkloadIssues.toLocaleString()} {t('active tickets')}
                    </Badge>
                </div>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <Metric label={t('Active tickets')} value={summary.openWorkloadIssues} icon={InboxIcon} />
                    <Metric label={t('Needs assignee')} value={summary.unassignedIssues} icon={AlertTriangle} />
                    <Metric label={t('Needs approval')} value={summary.issuesNeedingApproval} icon={AlertTriangle} />
                    <Metric label={t('Needs response')} value={summary.issuesNeedingResponse} icon={AlertTriangle} />
                    <Metric label={t('Oldest response wait h')} value={summary.oldestNeedsResponseHours} icon={Clock} />
                    <Metric label={t('Owners at capacity')} value={summary.queueOwnersAtCapacity} icon={Users} />
                    <Metric label={t('Overdue SLA')} value={summary.overdueSlaEvents} icon={AlertTriangle} />
                </div>
                <div className="grid gap-3 lg:grid-cols-3">
                    <WorkloadBreakdown
                        title={t('By queue')}
                        items={summary.openQueueBreakdown}
                        icon={Workflow}
                        onOpen={openRoute}
                        routeFor={item => inboxRoute({ queue: item.key })}
                        t={t}
                    />
                    <WorkloadBreakdown
                        title={t('By assignee')}
                        items={summary.openAssigneeBreakdown}
                        icon={Users}
                        onOpen={openRoute}
                        routeFor={item => item.key === '__unassigned__'
                            ? inboxRoute({ filter: 'unassigned' })
                            : inboxRoute({ assignee: item.key })}
                        t={t}
                    />
                    <WorkloadBreakdown
                        title={t('By channel')}
                        items={summary.openChannelBreakdown}
                        icon={BarChart3}
                        onOpen={openRoute}
                        routeFor={item => inboxRoute({ channel: item.key })}
                        t={t}
                    />
                </div>
                <QueueCapacityPanel
                    items={summary.queueOwnerCapacityItems}
                    onOpen={openRoute}
                    t={t}
                />
            </section>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Metric label={t('Total issues')} value={summary.totalIssues} icon={InboxIcon} />
                <Metric label={t('Open issues')} value={summary.openIssues} icon={BarChart3} />
                <Metric label={t('Ongoing issues')} value={summary.ongoingIssues} icon={BarChart3} />
                <Metric label={t('Done issues')} value={summary.doneIssues} icon={BarChart3} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
                <Metric label={t('Channels')} value={summary.channels} icon={BarChart3} />
                <Metric label={t('Active channels')} value={summary.activeChannels} icon={CheckCircle2} />
                <Metric label={t('Channel backlog')} value={summary.channelBacklogSurfaces} icon={AlertTriangle} />
                <Metric label={t('Every-message ticketing')} value={Math.max(summary.activeChannels - summary.activeChannelsWrongTicketMode, 0)} icon={CheckCircle2} />
                <Metric label={t('Wrong ticket mode')} value={summary.activeChannelsWrongTicketMode} icon={AlertTriangle} />
                <Metric label={t('Smoke passed')} value={summary.activeChannelsWithSmoke} icon={CheckCircle2} />
                <Metric label={t('Smoke missing')} value={summary.activeChannelsMissingSmoke} icon={AlertTriangle} />
                <Metric label={t('Outbound smoke passed')} value={summary.activeChannelsWithOutboundSmoke} icon={CheckCircle2} />
                <Metric label={t('Outbound smoke missing')} value={summary.activeChannelsMissingOutboundSmoke} icon={AlertTriangle} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Metric label={t('Accounts')} value={summary.accounts} icon={Building2} />
                <Metric label={t('Knowledge articles')} value={summary.knowledgeArticles} icon={BookOpen} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Metric label={t('Urgent issues')} value={summary.urgentIssues} icon={AlertTriangle} />
                <Metric label={t('High priority')} value={summary.highPriorityIssues} icon={AlertTriangle} />
                <Metric label={t('SLA due soon')} value={summary.dueSoonSlaEvents} icon={AlertTriangle} />
                <Metric label={t('Overdue SLA')} value={summary.overdueSlaEvents} icon={AlertTriangle} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Metric label={t('Account insights')} value={summary.accountInsights} icon={Building2} />
                <Metric label={t('Account actions')} value={summary.accountsNeedingAction} icon={Building2} />
                <Metric label={t('Open account risks')} value={summary.openAccountRisks} icon={AlertTriangle} />
                <Metric label={t('Feature requests')} value={summary.featureRequests} icon={BookOpen} />
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
                <Metric label={t('External objects')} value={summary.externalObjects} icon={Building2} />
                <Metric label={t('External sync runs')} value={summary.externalSyncRuns} icon={BarChart3} />
                <Metric label={t('Failed external sync runs')} value={summary.failedExternalSyncRuns} icon={AlertTriangle} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Metric label={t('CRM connectors')} value={summary.crmConnectors} icon={Building2} />
                <Metric label={t('Active CRM connectors')} value={summary.activeCrmConnectors} icon={Building2} />
                <Metric label={t('CRM sync runs')} value={summary.crmSyncRuns} icon={BarChart3} />
                <Metric label={t('Failed CRM sync runs')} value={summary.failedCrmSyncRuns} icon={AlertTriangle} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
                <Metric label={t('CRM webhook events')} value={summary.crmWebhookEvents} icon={BarChart3} />
                <Metric label={t('Failed CRM webhook events')} value={summary.failedCrmWebhookEvents} icon={AlertTriangle} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
                <Metric label={t('Knowledge gaps')} value={summary.knowledgeGaps} icon={BookOpen} />
                <Metric label={t('Open knowledge gaps')} value={summary.openKnowledgeGaps} icon={AlertTriangle} />
            </div>
            <section className="space-y-3">
                <div className="flex items-center gap-2">
                    <BarChart3 className="size-4 text-muted-foreground" />
                    <h2 className="text-sm font-medium">{t('SLA performance')}</h2>
                </div>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <Metric label={t('SLA events')} value={summary.slaEvents} icon={BarChart3} />
                    <Metric label={t('SLA met')} value={summary.metSlaEvents} icon={CheckCircle2} />
                    <Metric label={t('SLA pending')} value={summary.pendingSlaEvents} icon={BarChart3} />
                    <Metric label={t('SLA due soon')} value={summary.dueSoonSlaEvents} icon={AlertTriangle} />
                    <Metric label={t('SLA breached')} value={summary.breachedSlaEvents} icon={AlertTriangle} />
                    <Metric label={t('Avg first response min')} value={summary.averageFirstResponseMinutes} icon={BarChart3} />
                    <Metric label={t('P90 first response min')} value={summary.p90FirstResponseMinutes} icon={BarChart3} />
                    <Metric label={t('Avg resolution hours')} value={summary.averageResolutionHours} icon={BarChart3} />
                    <Metric label={t('P90 resolution hours')} value={summary.p90ResolutionHours} icon={BarChart3} />
                </div>
            </section>
            <div className="grid gap-3 sm:grid-cols-2">
                <Metric label={t('CSAT responses')} value={summary.csatFeedback} icon={Star} />
                <Metric label={t('Avg CSAT')} value={summary.averageCsatRating} icon={Star} />
                <Metric label={t('Low CSAT')} value={summary.lowCsatFeedback} icon={AlertTriangle} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
                <Metric label={t('AI runs')} value={summary.aiRuns} icon={BarChart3} />
                <Metric label={t('AI needs human')} value={summary.aiRunsNeedingHuman} icon={AlertTriangle} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
                <Metric label={t('Action executions')} value={summary.actionExecutions} icon={BarChart3} />
                <Metric label={t('Successful actions')} value={summary.successfulActionExecutions} icon={BarChart3} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Metric label={t('Automation rules')} value={summary.automationRules} icon={Workflow} />
                <Metric label={t('Active automation rules')} value={summary.activeAutomationRules} icon={Workflow} />
                <Metric label={t('Agent automations')} value={summary.agentAutomationRules} icon={Sparkles} />
                <Metric label={t('Human-in-loop automations')} value={summary.humanLoopAutomationRules} icon={Workflow} />
                <Metric label={t('Automation runs')} value={summary.automationRuns} icon={Workflow} />
                <Metric label={t('Human-loop proofs')} value={summary.successfulHumanLoopAutomationRuns} icon={CheckCircle2} />
                <Metric label={t('Channel prep proofs')} value={summary.successfulChannelAutopilotPrepPackages} icon={Sparkles} />
                <Metric label={t('Workflow proofs')} value={summary.successfulWorkflowLifecycleProofs} icon={Workflow} />
                <Metric label={t('Failed automation runs')} value={summary.failedAutomationRuns} icon={AlertTriangle} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
                <Metric label={t('Workflow transitions')} value={summary.workflowTransitionEvents} icon={Workflow} />
                <Metric label={t('Activity events')} value={summary.activityEvents} icon={BarChart3} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Metric label={t('Outbound messages')} value={summary.outboundMessages} icon={Send} />
                <Metric label={t('Queued outbound')} value={summary.queuedOutboundMessages} icon={Send} />
                <Metric label={t('Sent outbound')} value={summary.sentOutboundMessages} icon={Send} />
                <Metric label={t('Failed outbound')} value={summary.failedOutboundMessages} icon={AlertTriangle} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
                <Metric label={t('Channel sync runs')} value={summary.channelSyncRuns} icon={BarChart3} />
                <Metric label={t('Failed sync runs')} value={summary.failedChannelSyncRuns} icon={AlertTriangle} />
                <Metric label={t('Provider validations')} value={summary.channelValidationRuns} icon={CheckCircle2} />
                <Metric label={t('Missing provider validation')} value={summary.activeChannelsMissingProviderValidation} icon={AlertTriangle} />
                <Metric label={t('Remediation runs')} value={summary.channelRemediationRuns} icon={AlertTriangle} />
                <Metric label={t('Remediation items')} value={summary.channelRemediationItems} icon={AlertTriangle} />
                <Metric label={t('Live smoke target')} value={summary.activeChannelsWithLiveSmokeTarget} icon={CheckCircle2} />
                <Metric label={t('Missing live smoke target')} value={summary.activeChannelsMissingLiveSmokeTarget} icon={AlertTriangle} />
                <Metric label={t('Channel smoke runs')} value={summary.channelSmokeRuns} icon={BarChart3} />
                <Metric label={t('Failed smoke')} value={summary.failedChannelSmokeRuns} icon={AlertTriangle} />
                <Metric label={t('Outbound smoke runs')} value={summary.outboundChannelSmokeRuns} icon={BarChart3} />
                <Metric label={t('Failed outbound smoke')} value={summary.failedOutboundChannelSmokeRuns} icon={AlertTriangle} />
                <Metric label={t('Lifecycle smoke runs')} value={summary.lifecycleChannelSmokeRuns} icon={BarChart3} />
                <Metric label={t('Failed lifecycle smoke')} value={summary.failedLifecycleChannelSmokeRuns} icon={AlertTriangle} />
                <Metric label={t('Attachment lifecycle proof')} value={summary.activeChannelsWithAttachmentLifecycleSmoke} icon={CheckCircle2} />
                <Metric label={t('Missing attachment lifecycle proof')} value={summary.activeChannelsMissingAttachmentLifecycleSmoke} icon={AlertTriangle} />
                <Metric label={t('Failed attachment lifecycle proof')} value={summary.failedAttachmentLifecycleChannelSmokeRuns} icon={AlertTriangle} />
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
                <Metric label={t('Channel webhook events')} value={summary.channelWebhookEvents} icon={BarChart3} />
                <Metric label={t('Failed channel webhook events')} value={summary.failedChannelWebhookEvents} icon={AlertTriangle} />
                <Metric label={t('Unmatched channel webhook events')} value={summary.unmatchedChannelWebhookEvents} icon={AlertTriangle} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Metric label={t('Email sync proof')} value={summary.activeEmailChannelsWithSync} icon={CheckCircle2} />
                <Metric label={t('Missing email sync proof')} value={summary.activeEmailChannelsMissingSync} icon={AlertTriangle} />
                <Metric label={t('Failed email sync proof')} value={summary.failedEmailChannelSyncRuns} icon={AlertTriangle} />
                <Metric label={t('Email delivery proof')} value={summary.activeEmailChannelsWithDelivery} icon={CheckCircle2} />
                <Metric label={t('Missing email delivery proof')} value={summary.activeEmailChannelsMissingDelivery} icon={AlertTriangle} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Metric label={t('Web chat sessions')} value={summary.webChatSessions} icon={InboxIcon} />
                <Metric label={t('Open web chat sessions')} value={summary.openWebChatSessions} icon={InboxIcon} />
                <Metric label={t('Web chat session proof')} value={summary.activeWebChatChannelsWithSession} icon={CheckCircle2} />
                <Metric label={t('Missing web chat session proof')} value={summary.activeWebChatChannelsMissingSession} icon={AlertTriangle} />
                <Metric label={t('Failed web chat session proof')} value={summary.failedWebChatChannelSessionProofs} icon={AlertTriangle} />
                <Metric label={t('Web chat delivery proof')} value={summary.activeWebChatChannelsWithDelivery} icon={CheckCircle2} />
                <Metric label={t('Missing web chat delivery proof')} value={summary.activeWebChatChannelsMissingDelivery} icon={AlertTriangle} />
                <Metric label={t('Failed web chat delivery proof')} value={summary.failedWebChatChannelDeliveryProofs} icon={AlertTriangle} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
                <Metric label={t('Delivery runs')} value={summary.deliveryRuns} icon={Send} />
                <Metric label={t('Failed delivery runs')} value={summary.failedDeliveryRuns} icon={AlertTriangle} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
                <Metric label={t('Portal sessions')} value={summary.portalSessions} icon={InboxIcon} />
                <Metric label={t('Active portal sessions')} value={summary.activePortalSessions} icon={InboxIcon} />
            </div>
            <div className="grid gap-3 lg:grid-cols-2">
                <CountList title={t('Status')} counts={summary.statusCounts} />
                <CountList title={t('Priority')} counts={summary.priorityCounts} />
            </div>
            <div className="grid gap-3 lg:grid-cols-3">
                <CountList title={t('Channels')} counts={summary.channelCounts} />
                <CountList title={t('Queues')} counts={summary.queueCounts} />
                <CountList title={t('Assignees')} counts={summary.assigneeCounts} />
            </div>
        </div>
    );
}
