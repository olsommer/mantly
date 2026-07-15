import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, CheckCircle2, ChevronDown, Copy, Database, Download, ExternalLink, Hash, Loader, Plus, RefreshCw, Save, Send } from 'lucide-react';
import { toast } from 'sonner';

import { api } from '@/api/endpoints';
import type {
    SupportChannel,
    SupportChannelActivationAdapterRow,
    SupportChannelActivationBacklog,
    SupportChannelCursor,
    SupportChannelLaunch,
    SupportChannelLaunchCheck,
    SupportChannelLaunchPlaybookStep,
    SupportChannelLifecycleSmokeResult,
    SupportChannelLifecycleSmokeRun,
    SupportChannelOutboundSmokeRun,
    SupportChannelOutboundSmokeResult,
    SupportChannelPreset,
    SupportChannelProviderRunbook,
    SupportChannelRemediationStep,
    SupportChannelSmokeRun,
    SupportChannelSmokeResult,
    SupportChannelSyncRunRecord,
    SupportChannelTestMessageResult,
    SupportChannelValidation,
    SupportChannelWebhookEvent,
    SupportCrmConnector,
    SupportCrmSyncRunRecord,
    SupportCrmValidation,
    SupportCrmWebhookEvent,
    SupportDeliveryRunRecord,
    SupportQueue,
    SupportWebChatSession,
} from '@/api/endpoints';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useI18n } from '@/lib/i18n-context';

interface ChannelsProps {
    projectId: string;
}

type QueueRoutingMode = 'static' | 'least_open';

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

function numberFrom(value: unknown): number {
    return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function recordText(record: Record<string, unknown> | undefined, key: string): string {
    const value = record?.[key];
    return typeof value === 'string' ? value : '';
}

function recordObject(record: Record<string, unknown> | undefined, key: string): Record<string, unknown> | undefined {
    const value = record?.[key];
    return value && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, unknown>
        : undefined;
}

function resolverProofFrom(result: Record<string, unknown> | undefined): Record<string, unknown> | undefined {
    return recordObject(result, 'resolver') ?? recordObject(result, 'resolverProof');
}

function remediationSeverity(value: unknown): SupportChannelRemediationStep['severity'] {
    if (value === 'critical' || value === 'warning' || value === 'info') return value;
    return 'warning';
}

function remediationStepsFrom(value: unknown): SupportChannelRemediationStep[] {
    if (!Array.isArray(value)) return [];
    return value
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
        .map(item => ({
            key: textValue(item.key),
            label: textValue(item.label, textValue(item.key)),
            detail: textValue(item.detail),
            severity: remediationSeverity(item.severity),
            action: textValue(item.action),
            runAction: textValue(item.runAction ?? item.run_action),
            copyLabel: textValue(item.copyLabel ?? item.copy_label),
            copyValue: textValue(item.copyValue ?? item.copy_value),
        }))
        .filter(item => item.key || item.label || item.detail);
}

type TicketCreationMode = 'per_message' | 'per_thread';
type OutboundPayloadMode = 'provider' | 'generic';
type OutboundTransport = '' | 'webhook' | 'bot' | 'provider_api';
type ChannelSaveOverrides = {
    status?: string;
    ticketCreationMode?: TicketCreationMode;
    autoPrepareTriage?: boolean;
    autoPrepareCustomFields?: boolean;
    autoPrepareAgentReply?: boolean;
    autoPrepareAgentReplyOnUpdate?: boolean;
    agentAutoSend?: boolean;
    defaultAssigneeEmail?: string;
    defaultQueueKey?: string;
    defaultQueueName?: string;
};

const supportModeChannelOverrides: ChannelSaveOverrides = {
    ticketCreationMode: 'per_message',
    autoPrepareTriage: true,
    autoPrepareCustomFields: true,
    autoPrepareAgentReply: true,
    autoPrepareAgentReplyOnUpdate: true,
    agentAutoSend: false,
};

type CrmProviderPreset = {
    provider: string;
    label: string;
    defaultName: string;
    defaultKey: string;
    config: Record<string, unknown>;
    envVars: Array<{ name: string; required: boolean; description: string }>;
    note: string;
};

const defaultChannelConfig = () => JSON.stringify({
    ticketCreationMode: 'per_message',
    autoPrepareTriage: true,
    autoPrepareCustomFields: true,
    autoPrepareAgentReply: true,
    autoPrepareAgentReplyOnUpdate: true,
    agentAutoSend: false,
    includeFeedbackLink: true,
}, null, 2);
const NO_DEFAULT_QUEUE_VALUE = '__no_default_queue__';

const crmProviderPresets: CrmProviderPreset[] = [
    {
        provider: 'hubspot',
        label: 'HubSpot',
        defaultName: 'HubSpot',
        defaultKey: 'hubspot-main',
        config: {
            adapter: 'hubspot',
            privateAppTokenEnv: 'HUBSPOT_PRIVATE_APP_TOKEN',
            portalId: '',
        },
        envVars: [
            {
                name: 'HUBSPOT_PRIVATE_APP_TOKEN',
                required: true,
                description: 'Private app token used for company and contact polling.',
            },
        ],
        note: 'Polls companies and contacts with HubSpot CRM search and stores cursor by hs_lastmodifieddate.',
    },
    {
        provider: 'salesforce',
        label: 'Salesforce',
        defaultName: 'Salesforce',
        defaultKey: 'salesforce-main',
        config: {
            adapter: 'salesforce',
            accessTokenEnv: 'SALESFORCE_ACCESS_TOKEN',
            instanceUrlEnv: 'SALESFORCE_INSTANCE_URL',
            apiVersion: 'v61.0',
        },
        envVars: [
            {
                name: 'SALESFORCE_ACCESS_TOKEN',
                required: true,
                description: 'OAuth access token for REST SOQL polling.',
            },
            {
                name: 'SALESFORCE_INSTANCE_URL',
                required: true,
                description: 'Salesforce instance base URL, for example https://acme.my.salesforce.com.',
            },
        ],
        note: 'Polls Account and Contact records with SOQL and stores cursor by SystemModstamp.',
    },
    {
        provider: 'custom',
        label: 'HTTP',
        defaultName: 'Custom CRM',
        defaultKey: 'crm-main',
        config: {
            adapter: 'http',
            endpointUrl: 'https://crm.example.com/api/support/accounts',
            tokenEnv: 'CRM_HTTP_TOKEN',
            recordsPath: 'items',
            cursorParam: 'cursor',
            limitParam: 'limit',
        },
        envVars: [
            {
                name: 'CRM_HTTP_TOKEN',
                required: true,
                description: 'API token for the custom CRM endpoint. Remove tokenEnv from JSON for public/internal endpoints.',
            },
        ],
        note: 'Polls a custom HTTPS endpoint that returns account/contact records and stores the cursor from each record.',
    },
];

function crmProviderPreset(provider: string): CrmProviderPreset {
    return crmProviderPresets.find(preset => preset.provider === provider) ?? crmProviderPresets[0];
}

function ticketCreationModeFromConfig(config: Record<string, unknown> | undefined): TicketCreationMode {
    const value = config?.ticketCreationMode ?? config?.ticket_creation_mode;
    const raw = typeof value === 'string' ? value.trim() : '';
    return raw === 'per_thread' ? 'per_thread' : 'per_message';
}

function outboundPayloadModeFromConfig(config: Record<string, unknown> | undefined): OutboundPayloadMode {
    const value = config?.outboundPayloadMode ?? config?.outbound_payload_mode ?? config?.payloadMode ?? config?.payload_mode;
    const raw = typeof value === 'string' ? value.trim() : '';
    return raw === 'generic' ? 'generic' : 'provider';
}

function providerApiOutboundSupported(channelType: string) {
    return ['line', 'viber', 'whatsapp', 'messenger', 'instagram', 'twitter', 'sms'].includes(channelType);
}

function providerApiTokenEnvSupported(channelType: string) {
    return ['line', 'viber', 'whatsapp', 'messenger', 'instagram', 'twitter'].includes(channelType);
}

function providerApiTransportValues(channelType: string) {
    if (channelType === 'line') return ['line', 'line_messaging', 'line_messaging_api', 'provider_api'];
    if (channelType === 'viber') return ['viber', 'viber_bot', 'provider_api'];
    if (channelType === 'whatsapp') return ['whatsapp', 'whatsapp_api', 'whatsapp_cloud', 'whatsapp_cloud_api', 'cloud_api', 'provider_api'];
    if (channelType === 'messenger') return ['messenger', 'messenger_api', 'facebook_messenger', 'facebook_messenger_api', 'provider_api'];
    if (channelType === 'instagram') return ['instagram', 'instagram_messaging', 'instagram_graph', 'instagram_graph_api', 'provider_api'];
    if (channelType === 'twitter') return ['twitter', 'x', 'x_dm', 'twitter_dm', 'x_api', 'provider_api'];
    if (channelType === 'sms') return ['sms', 'twilio', 'twilio_sms', 'provider_api'];
    return ['provider_api'];
}

function outboundTransportFromConfig(config: Record<string, unknown> | undefined, channelType = ''): OutboundTransport {
    const value = config?.outboundTransport ?? config?.outbound_transport ?? config?.transport;
    const raw = typeof value === 'string' ? value.trim().toLowerCase() : '';
    if (providerApiOutboundSupported(channelType) && providerApiTransportValues(channelType).includes(raw)) return 'provider_api';
    if (['bot', 'slack_bot', 'teams_bot', 'discord_bot', 'telegram_bot', 'bot_api', 'provider_api'].includes(raw)) return 'bot';
    if (['webhook', 'adapter', 'http'].includes(raw)) return 'webhook';
    return '';
}

function outboundTransportConfigValue(value: OutboundTransport, channelType: string) {
    if (value === 'provider_api' && channelType === 'sms') return 'twilio';
    if (value === 'provider_api' && channelType === 'line') return 'line';
    if (value === 'provider_api' && channelType === 'viber') return 'viber';
    if (value === 'provider_api' && channelType === 'whatsapp') return 'whatsapp';
    if (value === 'provider_api' && channelType === 'messenger') return 'messenger';
    if (value === 'provider_api' && channelType === 'instagram') return 'instagram';
    if (value === 'provider_api' && channelType === 'twitter') return 'twitter';
    return value;
}

function usesWebhookOutbound(value: OutboundTransport) {
    return value !== 'bot' && value !== 'provider_api';
}

function usesOutboundTokenEnv(value: OutboundTransport, channelType: string) {
    return usesWebhookOutbound(value) || (value === 'provider_api' && providerApiTokenEnvSupported(channelType));
}

function boolFromConfig(config: Record<string, unknown> | undefined, key: string, snakeKey: string, fallback: boolean) {
    const value = config?.[key] ?? config?.[snakeKey];
    if (typeof value === 'boolean') return value;
    if (typeof value === 'string') {
        const raw = value.trim().toLowerCase();
        if (['1', 'true', 'yes', 'on', 'enabled'].includes(raw)) return true;
        if (['0', 'false', 'no', 'off', 'disabled'].includes(raw)) return false;
    }
    return fallback;
}

function textFromConfig(config: Record<string, unknown> | undefined, key: string, snakeKey: string) {
    const value = config?.[key] ?? config?.[snakeKey];
    return typeof value === 'string' ? value : '';
}

function textValue(value: unknown, fallback = ''): string {
    if (typeof value === 'string') return value;
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
    if (value === null || value === undefined) return fallback;
    return fallback;
}

function textArrayFrom(value: unknown): string[] {
    if (!Array.isArray(value)) return [];
    return value
        .map(item => textValue(item).trim())
        .filter(Boolean);
}

function channelProviderRunbookFrom(record: Record<string, unknown>): SupportChannelProviderRunbook | null {
    const value = recordObject(record, 'providerRunbook');
    if (!value || textValue(value.kind) !== 'support_channel_provider_runbook') return null;
    const secretEnvVars = Array.isArray(value.secretEnvVars)
        ? value.secretEnvVars
            .map(item => item && typeof item === 'object' && !Array.isArray(item) ? item as Record<string, unknown> : null)
            .filter((item): item is Record<string, unknown> => Boolean(item))
            .map(item => ({
                name: textValue(item.name),
                purpose: textValue(item.purpose),
                required: item.required === true,
                configured: item.configured === true,
            }))
            .filter(item => item.name)
        : [];
    const proofActions = Array.isArray(value.proofActions)
        ? value.proofActions
            .map(item => item && typeof item === 'object' && !Array.isArray(item) ? item as Record<string, unknown> : null)
            .filter((item): item is Record<string, unknown> => Boolean(item))
            .map(item => ({
                key: textValue(item.key),
                label: textValue(item.label),
                status: textValue(item.status),
                detail: textValue(item.detail),
                action: textValue(item.action),
                runId: textValue(item.runId),
            }))
            .filter(item => item.key)
        : [];
    const commands = Array.isArray(value.commands)
        ? value.commands
            .map(item => item && typeof item === 'object' && !Array.isArray(item) ? item as Record<string, unknown> : null)
            .filter((item): item is Record<string, unknown> => Boolean(item))
            .map(item => ({
                key: textValue(item.key),
                label: textValue(item.label),
                command: textValue(item.command),
            }))
            .filter(item => item.key || item.command)
        : [];
    return {
        kind: 'support_channel_provider_runbook',
        surfaceType: textValue(value.surfaceType),
        surfaceLabel: textValue(value.surfaceLabel),
        launchWave: textValue(value.launchWave),
        initialProvider: value.initialProvider === true,
        channelId: textValue(value.channelId),
        channelKey: textValue(value.channelKey),
        channelStatus: textValue(value.channelStatus),
        ready: value.ready === true,
        phase: textValue(value.phase),
        providerSteps: textArrayFrom(value.providerSteps),
        secretEnvVars,
        requiredMissingEnvVars: textArrayFrom(value.requiredMissingEnvVars),
        liveTargets: Array.isArray(value.liveTargets)
            ? value.liveTargets.filter(item => item && typeof item === 'object' && !Array.isArray(item)) as Array<Record<string, unknown>>
            : [],
        missingLiveTargets: textArrayFrom(value.missingLiveTargets),
        proofActions,
        commands,
        setupPackageKeys: textArrayFrom(value.setupPackageKeys),
        blockers: textArrayFrom(value.blockers),
    };
}

function firstTextValue(...values: unknown[]) {
    for (const value of values) {
        const clean = textValue(value).trim();
        if (clean) return clean;
    }
    return '';
}

function cleanEnvVarName(value: unknown): string {
    const clean = textValue(value).trim();
    return /^[A-Za-z_][A-Za-z0-9_]*$/.test(clean) ? clean : '';
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

function queueRoutingModeFrom(queue: SupportQueue | null): QueueRoutingMode {
    const metadata = queue?.metadata ?? {};
    const raw = textValue(
        metadata.assignmentMode
        ?? metadata.assignment_mode
        ?? metadata.routingMode
        ?? metadata.routing_mode
        ?? '',
    ).toLowerCase();
    const clean = raw.replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
    return ['least_open', 'least_active', 'least_loaded', 'load_balanced'].includes(clean)
        ? 'least_open'
        : 'static';
}

function positiveIntegerFrom(value: unknown): number {
    if (typeof value === 'number' && Number.isFinite(value)) return Math.max(0, Math.floor(value));
    if (typeof value === 'string' && value.trim()) {
        const parsed = Number.parseInt(value.trim(), 10);
        return Number.isFinite(parsed) ? Math.max(0, parsed) : 0;
    }
    return 0;
}

function queueOwnerCapacity(queue: SupportQueue | null): number {
    const metadata = queue?.metadata ?? {};
    return positiveIntegerFrom(
        metadata.ownerCapacity
        ?? metadata.owner_capacity
        ?? metadata.maxOpenTicketsPerOwner
        ?? metadata.max_open_tickets_per_owner
        ?? metadata.maxActiveTicketsPerOwner
        ?? metadata.max_active_tickets_per_owner
        ?? metadata.maxActiveTickets
        ?? metadata.max_active_tickets
        ?? metadata.capacity,
    );
}

function defaultWebhookTokenEnv(channelType: string) {
    if (channelType === 'slack') return 'SUPPORT_SLACK_WEBHOOK_TOKEN';
    if (channelType === 'teams') return 'SUPPORT_TEAMS_WEBHOOK_TOKEN';
    if (channelType === 'discord') return 'SUPPORT_DISCORD_WEBHOOK_TOKEN';
    if (channelType === 'telegram') return 'SUPPORT_TELEGRAM_WEBHOOK_TOKEN';
    if (channelType === 'viber') return 'SUPPORT_VIBER_WEBHOOK_TOKEN';
    if (channelType === 'whatsapp') return 'SUPPORT_WHATSAPP_WEBHOOK_TOKEN';
    if (channelType === 'messenger') return 'SUPPORT_MESSENGER_WEBHOOK_TOKEN';
    if (channelType === 'instagram') return 'SUPPORT_INSTAGRAM_WEBHOOK_TOKEN';
    if (channelType === 'twitter') return 'SUPPORT_X_WEBHOOK_TOKEN';
    if (channelType === 'sms') return 'SUPPORT_TWILIO_WEBHOOK_TOKEN';
    return 'SUPPORT_CHANNEL_WEBHOOK_TOKEN';
}

function defaultSignatureSecretEnv(channelType: string, channelKey: string) {
    if (channelType === 'slack') return 'SUPPORT_SLACK_SIGNING_SECRET';
    if (channelType === 'viber') return 'SUPPORT_VIBER_AUTH_TOKEN';
    if (channelType === 'whatsapp') return 'SUPPORT_WHATSAPP_APP_SECRET';
    if (channelType === 'messenger') return 'SUPPORT_MESSENGER_APP_SECRET';
    if (channelType === 'instagram') return 'SUPPORT_INSTAGRAM_APP_SECRET';
    if (channelType === 'twitter') return 'SUPPORT_X_CONSUMER_SECRET';
    if (channelType === 'sms') return 'SUPPORT_TWILIO_SIGNING_SECRET';
    const cleanKey = (channelKey || `${channelType}-main`).toUpperCase().replace(/[: -]/g, '_');
    return `SUPPORT_CHANNEL_${cleanKey}_SIGNING_SECRET`;
}

function defaultSignatureHeader(channelType: string) {
    if (channelType === 'viber') return 'X-Viber-Content-Signature';
    if (channelType === 'whatsapp' || channelType === 'messenger' || channelType === 'instagram') return 'X-Hub-Signature-256';
    if (channelType === 'twitter') return 'x-twitter-webhooks-signature';
    return 'X-Support-Signature';
}

function defaultOutboundTokenEnv(channelType: string) {
    if (channelType === 'whatsapp') return 'SUPPORT_WHATSAPP_ACCESS_TOKEN';
    if (channelType === 'messenger') return 'SUPPORT_MESSENGER_PAGE_ACCESS_TOKEN';
    if (channelType === 'instagram') return 'SUPPORT_INSTAGRAM_ACCESS_TOKEN';
    if (channelType === 'twitter') return 'SUPPORT_X_USER_ACCESS_TOKEN';
    if (channelType === 'viber') return 'SUPPORT_VIBER_AUTH_TOKEN';
    return 'SUPPORT_OUTBOUND_WEBHOOK_TOKEN';
}

function nativeBotSupported(channelType: string) {
    return ['slack', 'teams', 'discord', 'telegram'].includes(channelType);
}

function supportsProviderLifecycle(channelType: string) {
    return !['email', 'chat', 'web_chat'].includes(channelType);
}

function usesLiveProofPrimaryTarget(channelType: string) {
    return ['slack', 'discord', 'telegram'].includes(channelType);
}

function usesLiveProofThreadTarget(channelType: string) {
    return ['slack', 'discord'].includes(channelType);
}

function usesLiveProofRecipientTarget(channelType: string) {
    return ['line', 'viber', 'whatsapp', 'messenger', 'instagram', 'twitter', 'sms', 'twilio'].includes(channelType);
}

interface LiveProofTargetRequirement {
    key: string;
    label: string;
    configKey: string;
    copyValue: string;
    value: string;
    required: boolean;
    configured: boolean;
}

const smokeTargetPlaceholders = new Set([
    'c0123456789',
    '1710000000.000100',
    'channel-id',
    'thread-id',
    'message-id',
    'conversation-id',
    'activity-id',
    'whatsapp-phone-number-id',
    'messenger-page-id',
    'messenger-customer',
    'viber-user-id',
    'instagram-scoped-user-id',
    'x-user-id',
    'smxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
]);

function liveProofTargetValueConfigured(value: string) {
    const clean = value.trim();
    if (!clean) return false;
    const normalized = clean.toLowerCase();
    if (smokeTargetPlaceholders.has(normalized)) return false;
    if (normalized.startsWith('admin-smoke')) return false;
    if (normalized.startsWith('+1555') || normalized.startsWith('1555')) return false;
    return true;
}

function liveProofTargetConfigured(
    channelType: string,
    target: {
        channelId: string;
        threadId: string;
        toAddress: string;
        conversationId: string;
        serviceUrl: string;
    },
) {
    if (channelType === 'teams') {
        return liveProofTargetValueConfigured(target.serviceUrl) && liveProofTargetValueConfigured(target.conversationId);
    }
    if (usesLiveProofRecipientTarget(channelType)) return liveProofTargetValueConfigured(target.toAddress);
    if (channelType === 'discord') {
        return liveProofTargetValueConfigured(target.channelId) || liveProofTargetValueConfigured(target.threadId);
    }
    if (usesLiveProofPrimaryTarget(channelType)) return liveProofTargetValueConfigured(target.channelId);
    return false;
}

function isLaunchConfigFix(action: string) {
    return action === 'support_mode' || action === 'ticket_mode' || action === 'auto_prepare' || action === 'owner_routing';
}

function liveProofTargetRequirements(
    channelType: string,
    target: {
        channelId: string;
        threadId: string;
        toAddress: string;
        conversationId: string;
        replyToId: string;
        serviceUrl: string;
    },
): LiveProofTargetRequirement[] {
    const type = channelType.trim().toLowerCase();
    const row = (
        key: string,
        label: string,
        configKey: string,
        value: string,
        required = true,
        copyValue = configKey.split(' ')[0],
    ): LiveProofTargetRequirement => ({
        key,
        label,
        configKey,
        copyValue,
        value,
        required,
        configured: liveProofTargetValueConfigured(value),
    });
    if (type === 'slack') {
        return [
            row('smokeChannelId', 'Slack channel ID', 'smokeChannelId', target.channelId),
            row('smokeThreadTs', 'Slack thread TS', 'smokeThreadTs', target.threadId, false),
        ];
    }
    if (type === 'teams') {
        return [
            row('smokeServiceUrl', 'Teams service URL', 'smokeServiceUrl', target.serviceUrl),
            row('smokeConversationId', 'Teams conversation target', 'smokeConversationId', target.conversationId),
            row('smokeReplyToId', 'Teams reply activity', 'smokeReplyToId', target.replyToId, false),
        ];
    }
    if (type === 'discord') {
        const value = target.channelId || target.threadId;
        return [
            row('discordTarget', 'Discord channel or thread', 'smokeChannelId or smokeThreadId', value, true, 'smokeChannelId'),
        ];
    }
    if (type === 'telegram') {
        return [row('smokeChatId', 'Telegram chat ID', 'smokeChatId', target.channelId)];
    }
    if (type === 'line') {
        return [row('smokeToAddress', 'LINE user/group/room ID', 'smokeToAddress', target.toAddress)];
    }
    if (type === 'viber') {
        return [row('smokeToAddress', 'Viber subscriber ID', 'smokeToAddress', target.toAddress)];
    }
    if (type === 'whatsapp') {
        return [row('smokeToAddress', 'WhatsApp recipient', 'smokeToAddress', target.toAddress)];
    }
    if (type === 'messenger') {
        return [row('smokeToAddress', 'Messenger PSID', 'smokeToAddress', target.toAddress)];
    }
    if (type === 'sms' || type === 'twilio') {
        return [row('smokeToAddress', 'SMS recipient', 'smokeToAddress', target.toAddress)];
    }
    return [];
}

function liveProofEvidenceRows(channel: SupportChannel | null): SupportChannelLaunchCheck[] {
    const checklist = channel?.setup?.launchChecklist ?? channel?.setup?.launch?.checklist ?? [];
    const evidenceKeys = new Set([
        'live_smoke_target',
        'provider_validation',
        'channel_autopilot',
        'human_approved_real_channel_reply',
        'real_channel_reply',
        'real_channel_handoff',
        'inbound_ticket_event',
        'inbound_smoke',
        'outbound_smoke',
        'lifecycle_smoke',
        'attachment_lifecycle_smoke',
    ]);
    return checklist.filter(step => evidenceKeys.has(step.key));
}

function defaultBotTokenEnv(channelType: string) {
    if (channelType === 'slack') return 'SUPPORT_SLACK_BOT_TOKEN';
    if (channelType === 'discord') return 'SUPPORT_DISCORD_BOT_TOKEN';
    if (channelType === 'telegram') return 'SUPPORT_TELEGRAM_BOT_TOKEN';
    return '';
}

function defaultTeamsAppIdEnv() {
    return 'SUPPORT_TEAMS_APP_ID';
}

function defaultTeamsAppPasswordEnv() {
    return 'SUPPORT_TEAMS_APP_PASSWORD';
}

function outboundTransportLabel(value: string) {
    if (value === 'bot') return 'Native bot';
    if (value === 'provider_api') return 'Provider API';
    if (value === 'webhook') return 'Webhook adapter';
    return 'Automatic';
}

function setupStatusLabel(status: string) {
    if (status === 'done') return 'Ready';
    if (status === 'warning') return 'Check';
    if (status === 'manual') return 'Manual';
    return 'Missing';
}

function setupStatusVariant(status: string): 'secondary' | 'destructive' | 'outline' {
    if (status === 'done') return 'secondary';
    if (status === 'missing') return 'destructive';
    return 'outline';
}

function setupHealthLabel(status: string | undefined) {
    if (status === 'ready') return 'Ready';
    if (status === 'degraded') return 'Degraded';
    return 'Needs setup';
}

function setupHealthVariant(status: string | undefined): 'secondary' | 'destructive' | 'outline' {
    if (status === 'ready') return 'secondary';
    if (status === 'degraded') return 'outline';
    return 'destructive';
}

function webhookEventStatusVariant(status: string): 'secondary' | 'destructive' | 'outline' {
    if (status === 'processed') return 'secondary';
    if (status === 'failed' || status === 'unmatched') return 'destructive';
    return 'outline';
}

function setupStatusIcon(status: string) {
    if (status === 'done') return <CheckCircle2 className="size-3.5 text-emerald-600" />;
    if (status === 'missing') return <AlertTriangle className="size-3.5 text-destructive" />;
    return <AlertTriangle className="size-3.5 text-muted-foreground" />;
}

function presetTicketCreationMode(value: string): TicketCreationMode {
    return value === 'per_thread' ? 'per_thread' : 'per_message';
}

function presetOutboundPayloadMode(value: string): OutboundPayloadMode {
    return value === 'generic' ? 'generic' : 'provider';
}

function presetSupportSteps(preset: SupportChannelPreset): string[] {
    const configured = preset.supportDefaults?.autopilotPrep;
    if (Array.isArray(configured) && configured.length > 0) return configured;
    return preset.autoPrepareAgentReply ? ['triage', 'custom_fields', 'approval_draft'] : [];
}

function presetSupportStepLabel(step: string) {
    if (step === 'triage') return 'Triage';
    if (step === 'custom_fields') return 'Fields';
    if (step === 'approval_draft') return 'Approval draft';
    return step;
}

function channelTypeFromPreset(preset: SupportChannelPreset) {
    return preset.type === 'web_chat' ? 'chat' : preset.type;
}

function setupConfigFromPreset(preset: SupportChannelPreset, ownerEmail: string) {
    const config: Record<string, unknown> = { ...preset.config };
    const configuredOwner = textFromConfig(config, 'defaultAssigneeEmail', 'default_assignee_email');
    const nextOwner = configuredOwner || ownerEmail.trim();
    config.ticketCreationMode = presetTicketCreationMode(preset.ticketCreationMode);
    config.outboundPayloadMode = presetOutboundPayloadMode(preset.outboundPayloadMode);
    config.autoPrepareTriage = boolFromConfig(config, 'autoPrepareTriage', 'auto_prepare_triage', true);
    config.autoPrepareCustomFields = boolFromConfig(config, 'autoPrepareCustomFields', 'auto_prepare_custom_fields', true);
    config.autoPrepareAgentReply = preset.autoPrepareAgentReply;
    config.autoPrepareAgentReplyOnUpdate = preset.autoPrepareAgentReplyOnUpdate;
    config.agentAutoSend = typeof preset.agentAutoSend === 'boolean'
        ? preset.agentAutoSend
        : boolFromConfig(config, 'agentAutoSend', 'agent_auto_send', false);
    config.includeFeedbackLink = boolFromConfig(
        config,
        'includeFeedbackLink',
        'include_feedback_link',
        boolFromConfig(config, 'agentIncludeFeedbackLink', 'agent_include_feedback_link', true),
    );
    if (nextOwner) config.defaultAssigneeEmail = nextOwner;
    if (preset.defaultQueueKey) config.defaultQueueKey = preset.defaultQueueKey;
    if (preset.defaultQueueName) config.defaultQueueName = preset.defaultQueueName;
    return config;
}

function currentEmailFromToken() {
    if (typeof localStorage === 'undefined') return '';
    const token = localStorage.getItem('admin_auth_token') || '';
    const payloadPart = token.split('.')[1];
    if (!payloadPart) return '';
    try {
        const normalized = payloadPart.replace(/-/g, '+').replace(/_/g, '/');
        const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=');
        const payload = JSON.parse(atob(padded)) as { email?: unknown };
        return typeof payload.email === 'string' ? payload.email : '';
    } catch {
        return '';
    }
}

const channelSurfaceTargets = [
    { type: 'email', label: 'Email' },
    { type: 'chat', label: 'Web chat' },
    { type: 'slack', label: 'Slack' },
    { type: 'discord', label: 'Discord' },
    { type: 'teams', label: 'Teams' },
    { type: 'telegram', label: 'Telegram' },
    { type: 'line', label: 'LINE' },
    { type: 'viber', label: 'Viber' },
    { type: 'whatsapp', label: 'WhatsApp' },
    { type: 'messenger', label: 'Messenger' },
    { type: 'instagram', label: 'Instagram DM' },
    { type: 'twitter', label: 'X DM' },
    { type: 'sms', label: 'SMS' },
    { type: 'webhook', label: 'Webhook' },
] as const;

interface ChannelSurfaceRow {
    type: string;
    label: string;
    channel: SupportChannel | null;
    ticketMode: string;
    inboundReady: boolean;
    outboundReady: boolean;
    autoTriage: boolean;
    autoFields: boolean;
    autoDraft: boolean;
    autoFollowUp: boolean;
    humanReview: boolean;
    everyMessage: boolean;
    ownerRouting: boolean;
    launchRequired: boolean;
    launchReady: boolean;
    launchBlockers: SupportChannelLaunch['blockers'];
    ready: boolean;
    blockers: string[];
}

interface ChannelSurfaceNextAction {
    row: ChannelSurfaceRow;
    kind: 'create' | 'select' | 'fix' | 'run';
    title: string;
    detail: string;
    buttonLabel: string;
    runAction?: string;
}

type ChannelActivationNextAction = NonNullable<SupportChannelActivationBacklog['nextActions']>[number];

function channelActivationPhaseLabel(phase: string) {
    if (phase === 'create') return 'Create';
    if (phase === 'secrets') return 'Secrets';
    if (phase === 'targets') return 'Targets';
    if (phase === 'config') return 'Config';
    if (phase === 'activate') return 'Activate';
    if (phase === 'proof') return 'Proof';
    return phase || 'Next';
}

function liveProofTargetsForChannel(channel: SupportChannel): LiveProofTargetRequirement[] {
    const config = channel.config;
    return liveProofTargetRequirements(normalizedChannelType(channel.type), {
        channelId: textFromConfig(config, 'smokeChannelId', 'smoke_channel_id')
            || textFromConfig(config, 'smokeChatId', 'smoke_chat_id'),
        threadId: textFromConfig(config, 'smokeThreadTs', 'smoke_thread_ts')
            || textFromConfig(config, 'smokeThreadId', 'smoke_thread_id'),
        toAddress: textFromConfig(config, 'smokeToAddress', 'smoke_to_address'),
        conversationId: textFromConfig(config, 'smokeConversationId', 'smoke_conversation_id'),
        replyToId: textFromConfig(config, 'smokeReplyToId', 'smoke_reply_to_id'),
        serviceUrl: textFromConfig(config, 'smokeServiceUrl', 'smoke_service_url'),
    });
}

function channelActivationEnvVars(channel: SupportChannel | null, preset: SupportChannelPreset | undefined) {
    if (channel?.setup?.envVars?.length) return channel.setup.envVars;
    return [
        ...(preset?.authEnvVars ?? []),
        ...(preset?.outboundEnvVars ?? []),
    ].map(env => ({
        name: env.name,
        purpose: env.purpose,
        required: env.required,
        configured: false,
    }));
}

function channelActivationInstallPackage(setup: SupportChannel['setup'] | undefined) {
    if (!setup) return null;
    return {
        installPackage: setup.installPackage ?? null,
        slackManifest: setup.slackManifest ?? null,
        teamsBridgeConfig: setup.teamsBridgeConfig ?? null,
        discordBridgeConfig: setup.discordBridgeConfig ?? null,
        metaBridgeConfig: setup.metaBridgeConfig ?? null,
        telegramWebhookConfig: setup.telegramWebhookConfig ?? null,
        lineWebhookConfig: setup.lineWebhookConfig ?? null,
        viberWebhookConfig: setup.viberWebhookConfig ?? null,
        whatsappWebhookConfig: setup.whatsappWebhookConfig ?? null,
        messengerWebhookConfig: setup.messengerWebhookConfig ?? null,
        instagramWebhookConfig: setup.instagramWebhookConfig ?? null,
        twitterWebhookConfig: setup.twitterWebhookConfig ?? null,
        twitterBridgeConfig: setup.twitterBridgeConfig ?? null,
        twilioWebhookConfig: setup.twilioWebhookConfig ?? null,
    };
}

function buildChannelActivationAdapterMatrix(
    surfaces: Array<Record<string, unknown>>,
    nextActions: ChannelActivationNextAction[],
): SupportChannelActivationAdapterRow[] {
    const nextBySurface = new Map<string, ChannelActivationNextAction>();
    for (const action of nextActions) {
        if (action.surfaceType && !nextBySurface.has(action.surfaceType)) {
            nextBySurface.set(action.surfaceType, action);
        }
    }
    return surfaces
        .map(item => {
            const surface = recordObject(item, 'surface');
            const channel = recordObject(item, 'channel');
            const ticketing = recordObject(item, 'ticketing');
            const automation = recordObject(item, 'automation');
            const inbound = recordObject(item, 'inbound');
            const outbound = recordObject(item, 'outbound');
            const environment = recordObject(item, 'environment');
            const launch = recordObject(item, 'launch');
            const surfaceType = textValue(surface?.type);
            const nextAction = nextBySurface.get(surfaceType);
            return {
                surfaceType,
                surfaceLabel: textValue(surface?.label, surfaceType),
                configured: surface?.configured === true,
                ready: surface?.ready === true,
                channelId: textValue(channel?.id),
                channelKey: textValue(channel?.key),
                channelStatus: textValue(channel?.status, channel ? 'configured' : 'missing'),
                providerName: textValue(channel?.providerName),
                inbound: {
                    adapter: surfaceType,
                    ready: inbound?.ready === true,
                    path: firstTextValue(
                        inbound?.providerWebhookUrl,
                        inbound?.smsWebhookUrl,
                        inbound?.webChatUrl,
                        inbound?.webhookUrl,
                        inbound?.webChatEmbedScriptUrl,
                    ),
                },
                outbound: {
                    adapter: firstTextValue(
                        outbound?.transport,
                        outbound?.payloadMode,
                        surfaceType,
                    ),
                    ready: outbound?.ready === true,
                    target: firstTextValue(
                        outbound?.webhookUrl,
                        outbound?.webhookUrlEnv,
                        outbound?.webhookTokenEnv,
                        outbound?.botTokenEnv,
                    ),
                },
                ticketing: {
                    everyMessage: ticketing?.everyMessage === true,
                    ownerRouting: ticketing?.ownerRouting === true,
                },
                automation: {
                    autoPrepareAgentReply: automation?.autoPrepareAgentReply === true,
                    autoPrepareAgentReplyOnUpdate: automation?.autoPrepareAgentReplyOnUpdate === true,
                    humanReview: automation?.humanReview === true,
                },
                requiredMissingEnvVars: textArrayFrom(environment?.requiredMissing),
                missingLiveTargets: textArrayFrom(launch?.missingLiveTargets),
                nextAction: nextAction
                    ? {
                        phase: nextAction.phase,
                        title: nextAction.title,
                        detail: nextAction.detail,
                        action: nextAction.action,
                    }
                    : null,
            };
        })
        .filter(row => row.surfaceType);
}

function buildChannelActivationBacklog(
    projectId: string,
    rows: ChannelSurfaceRow[],
    presets: SupportChannelPreset[],
): SupportChannelActivationBacklog {
    const items = rows.map(row => {
        const channel = row.channel;
        const preset = presets.find(item => normalizedChannelType(item.type) === row.type);
        const setup = channel?.setup;
        const envVars = channelActivationEnvVars(channel, preset);
        const missingEnvVars = envVars
            .filter(env => !env.configured)
            .map(env => env.name);
        const requiredMissingEnvVars = envVars
            .filter(env => env.required && !env.configured)
            .map(env => env.name);
        const liveTargets = channel ? liveProofTargetsForChannel(channel) : [];
        const missingLiveTargets = liveTargets
            .filter(target => target.required && !target.configured)
            .map(target => target.configKey);
        const checklist = setup?.launchChecklist ?? setup?.launch?.checklist ?? [];
        const setupChecklist = setup?.setupChecklist ?? [];
        const blockers = [
            ...row.blockers.map(detail => ({
                key: 'channel_surface',
                label: detail,
                detail,
                status: 'missing',
                action: '',
            })),
            ...(setup?.launch?.blockers ?? []),
            ...checklist
                .filter(step => step.status !== 'done')
                .map(step => ({
                    key: step.key,
                    label: step.label,
                    detail: step.detail,
                    status: step.status,
                    action: step.action,
                    runId: step.runId,
                })),
            ...setupChecklist
                .filter(step => step.status !== 'done')
                .map(step => ({
                    key: step.key,
                    label: step.label,
                    detail: step.detail,
                    status: step.status,
                    action: '',
                })),
        ];
        return {
            surface: {
                type: row.type,
                label: row.label,
                ready: row.ready,
                configured: Boolean(channel),
                blockers: row.blockers,
            },
            channel: channel
                ? {
                    id: channel.id,
                    key: channel.channelKey,
                    name: channel.name,
                    type: channel.type,
                    status: channel.status,
                    providerName: setup?.providerName ?? preset?.providerName ?? '',
                }
                : null,
            ticketing: {
                ticketCreationMode: row.ticketMode,
                everyMessage: row.everyMessage,
                ownerRouting: row.ownerRouting,
                defaultAssigneeEmail: channel ? textFromConfig(channel.config, 'defaultAssigneeEmail', 'default_assignee_email') : '',
                defaultQueueKey: channel ? textFromConfig(channel.config, 'defaultQueueKey', 'default_queue_key') : preset?.defaultQueueKey ?? '',
                defaultQueueName: channel ? textFromConfig(channel.config, 'defaultQueueName', 'default_queue_name') : preset?.defaultQueueName ?? '',
            },
            automation: {
                autoPrepareTriage: row.autoTriage,
                autoPrepareCustomFields: row.autoFields,
                autoPrepareAgentReply: row.autoDraft,
                autoPrepareAgentReplyOnUpdate: row.autoFollowUp,
                agentAutoSend: !row.humanReview,
                humanReview: row.humanReview,
            },
            inbound: {
                ready: row.inboundReady,
                webhookUrl: setup?.inboundWebhookUrl ?? '',
                providerWebhookUrl: setup?.providerWebhookUrl ?? '',
                smsWebhookUrl: setup?.smsWebhookUrl ?? '',
                webChatUrl: setup?.webChatUrl ?? '',
                webChatEmbedScriptUrl: setup?.webChatEmbedScriptUrl ?? '',
            },
            outbound: {
                ready: row.outboundReady,
                transport: setup?.outboundTransport ?? (channel ? outboundTransportFromConfig(channel.config, channel.type) : ''),
                payloadMode: channel ? outboundPayloadModeFromConfig(channel.config) : presetOutboundPayloadMode(preset?.outboundPayloadMode ?? ''),
                webhookUrl: setup?.outboundWebhookUrl ?? '',
                webhookUrlEnv: setup?.outboundWebhookUrlEnv ?? preset?.outboundWebhookUrlEnv ?? '',
                webhookTokenEnv: setup?.outboundWebhookTokenEnv ?? preset?.outboundWebhookTokenEnv ?? '',
                botTokenEnv: setup?.outboundBotTokenEnv ?? '',
            },
            environment: {
                configured: envVars.filter(env => env.configured).length,
                total: envVars.length,
                missing: missingEnvVars,
                requiredMissing: setup?.health?.requiredMissingEnvVars?.length
                    ? setup.health.requiredMissingEnvVars
                    : requiredMissingEnvVars,
                vars: envVars,
            },
            launch: {
                required: row.launchRequired,
                ready: row.launchReady,
                summary: setup?.launch
                    ? {
                        checks: setup.launch.checks,
                        passed: setup.launch.passed,
                        missing: setup.launch.missing,
                        failed: setup.launch.failed,
                        lastCheckedAt: setup.launch.lastCheckedAt,
                    }
                    : null,
                liveTargets: liveTargets.map(target => ({
                    key: target.key,
                    label: target.label,
                    configKey: target.configKey,
                    required: target.required,
                    configured: target.configured,
                    value: target.value,
                })),
                missingLiveTargets,
                checklist,
                blockers,
                playbook: setup?.launchPlaybook ?? [],
                commands: (setup?.launchPlaybook ?? [])
                    .filter(step => Boolean(step.smokeCommand))
                    .map(step => ({
                        key: step.key,
                        label: step.label,
                        command: step.smokeCommand,
                    })),
            },
            setupPackage: channelActivationInstallPackage(setup),
        };
    });
    const backlog = items.filter(item => !item.surface.ready || item.channel?.status !== 'active');
    const nextActions: ChannelActivationNextAction[] = backlog
        .map((item, index) => {
            const base = {
                surfaceType: item.surface.type,
                surfaceLabel: item.surface.label,
                channelId: item.channel?.id ?? '',
                channelKey: item.channel?.key ?? '',
            };
            if (!item.channel) {
                return {
                    ...base,
                    phase: 'create',
                    priority: 10 + index,
                    title: `Create ${item.surface.label} channel`,
                    detail: `Apply the ${item.surface.label} preset so incoming messages can become tickets.`,
                    action: 'create_channel',
                    envVars: [],
                    liveTargets: [],
                };
            }
            const requiredMissing = Array.from(new Set(item.environment.requiredMissing));
            if (requiredMissing.length > 0) {
                const shown = requiredMissing.slice(0, 3).join(', ');
                const suffix = requiredMissing.length > 3
                    ? ` and ${requiredMissing.length - 3} more`
                    : '';
                return {
                    ...base,
                    phase: 'secrets',
                    priority: 20 + index,
                    title: `Configure ${item.surface.label} secrets`,
                    detail: `Add required runtime secrets: ${shown}${suffix}.`,
                    action: 'configure_secrets',
                    envVars: requiredMissing,
                    liveTargets: [],
                };
            }
            if (item.launch.missingLiveTargets.length > 0) {
                return {
                    ...base,
                    phase: 'targets',
                    priority: 30 + index,
                    title: `Set ${item.surface.label} smoke target`,
                    detail: `Configure live proof target keys: ${item.launch.missingLiveTargets.join(', ')}.`,
                    action: 'configure_smoke_target',
                    envVars: [],
                    liveTargets: item.launch.missingLiveTargets,
                };
            }
            const configGaps = [
                item.ticketing.everyMessage ? '' : 'ticketCreationMode',
                item.ticketing.ownerRouting ? '' : 'ownerRouting',
                item.automation.autoPrepareTriage ? '' : 'autoPrepareTriage',
                item.automation.autoPrepareCustomFields ? '' : 'autoPrepareCustomFields',
                item.automation.autoPrepareAgentReply ? '' : 'autoPrepareAgentReply',
                item.automation.autoPrepareAgentReplyOnUpdate ? '' : 'autoPrepareAgentReplyOnUpdate',
                item.automation.humanReview ? '' : 'approvalRequired',
            ].filter(Boolean);
            if (configGaps.length > 0) {
                return {
                    ...base,
                    phase: 'config',
                    priority: 40 + index,
                    title: `Fix ${item.surface.label} ticket defaults`,
                    detail: `Set ${configGaps.join(', ')} before launch proof.`,
                    action: 'ticket_defaults',
                    envVars: [],
                    liveTargets: [],
                };
            }
            if (item.channel.status !== 'active') {
                return {
                    ...base,
                    phase: 'activate',
                    priority: 50 + index,
                    title: `Activate ${item.surface.label} channel`,
                    detail: 'Set channel status to active after secrets, targets, and ticket defaults are ready.',
                    action: 'activate_channel',
                    envVars: [],
                    liveTargets: [],
                };
            }
            const firstBlocker = item.launch.blockers.find(blocker => blocker && typeof blocker === 'object');
            const firstCommand = item.launch.commands[0];
            return {
                ...base,
                phase: 'proof',
                priority: 60 + index,
                title: `Run ${item.surface.label} launch proof`,
                detail: firstBlocker?.detail || firstBlocker?.label || 'Run provider validation and lifecycle smoke.',
                action: firstBlocker?.action || 'launch_proof',
                runAction: firstBlocker?.action,
                command: firstCommand?.command || '',
                envVars: [],
                liveTargets: [],
            };
        })
        .sort((left, right) => left.priority - right.priority);
    const nextActionPhases = ['create', 'secrets', 'targets', 'config', 'activate', 'proof']
        .reduce<Record<string, number>>((acc, phase) => {
            acc[phase] = nextActions.filter(action => action.phase === phase).length;
            return acc;
        }, {});
    const adapterMatrix = buildChannelActivationAdapterMatrix(items as Array<Record<string, unknown>>, nextActions);
    return {
        kind: 'support_channel_activation_backlog',
        generatedAt: new Date().toISOString(),
        projectId,
        summary: {
            totalSurfaces: rows.length,
            configuredSurfaces: rows.filter(row => row.channel).length,
            activeSurfaces: rows.filter(row => row.channel?.status === 'active').length,
            readySurfaces: rows.filter(row => row.ready).length,
            backlogSurfaces: backlog.length,
            missingSurfaces: rows.filter(row => !row.channel).length,
            requiredMissingEnvVars: Array.from(new Set(backlog.flatMap(item => item.environment.requiredMissing))).sort(),
            missingLiveTargets: Array.from(new Set(backlog.flatMap(item => item.launch.missingLiveTargets))).sort(),
            nextActionCount: nextActions.length,
            nextActionPhases,
            adapterMatrixRows: adapterMatrix.length,
            adapterMatrixReady: adapterMatrix.filter(row => row.ready).length,
            adapterMatrixBlocked: adapterMatrix.filter(row => !row.ready).length,
        },
        channels: backlog,
        surfaces: items as Array<Record<string, unknown>>,
        adapterMatrix,
        nextActions,
    };
}

function normalizedChannelType(type: string) {
    const clean = type.trim().toLowerCase();
    return clean === 'web_chat' ? 'chat' : clean;
}

function channelRequiresLaunchSmoke(type: string) {
    return !['email', 'chat', 'web_chat'].includes(type.trim().toLowerCase());
}

function channelSetupBool(channel: SupportChannel, key: 'inboundReady' | 'outboundReady' | 'authConfigured') {
    const healthValue = channel.setup?.health?.[key];
    if (typeof healthValue === 'boolean') return healthValue;
    return channel.setup?.[key] === true;
}

function channelAutoDraftEnabled(channel: SupportChannel) {
    if (typeof channel.setup?.autoPrepareAgentReply === 'boolean') return channel.setup.autoPrepareAgentReply;
    return boolFromConfig(channel.config, 'autoPrepareAgentReply', 'auto_prepare_agent_reply', false);
}

function queueProvidesOwnerRouting(queue: SupportQueue | null | undefined) {
    return Boolean(queue?.defaultAssigneeEmail?.trim() || (queueRoutingModeFrom(queue ?? null) === 'least_open' && queueOwnerEmails(queue ?? null).length > 0));
}

function channelOwnerRoutingEnabled(channel: SupportChannel, queues: SupportQueue[]) {
    const checks = [
        ...(channel.setup?.launchChecklist ?? []),
        ...(channel.setup?.launch?.checklist ?? []),
        ...(channel.setup?.setupChecklist ?? []),
    ];
    const ownerCheck = checks.find(check => check.key === 'owner_routing');
    if (ownerCheck) return ownerCheck.status === 'done';
    if ((channel.setup?.launch?.blockers ?? []).some(blocker => blocker.key === 'owner_routing')) return false;
    if (textFromConfig(channel.config, 'defaultAssigneeEmail', 'default_assignee_email').trim()) return true;
    const queueKey = textFromConfig(channel.config, 'defaultQueueKey', 'default_queue_key').trim();
    const queue = queues.find(item => item.queueKey === queueKey);
    return queueProvidesOwnerRouting(queue);
}

function webChatSessionIssueIds(session: SupportWebChatSession): string[] {
    const ids = Array.isArray(session.issueIds) ? session.issueIds : [];
    const ordered = [...ids, session.latestIssueId || '', session.issueId || '']
        .map(value => value.trim())
        .filter(Boolean);
    return Array.from(new Set(ordered));
}

function webChatSessionLatestIssueId(session: SupportWebChatSession): string {
    return session.latestIssueId?.trim() || session.issueId?.trim() || webChatSessionIssueIds(session).at(-1) || '';
}

export function Channels({ projectId }: ChannelsProps) {
    const { t } = useI18n();
    const navigate = useNavigate();
    const location = useLocation();
    const { tenantId } = useParams<{ tenantId: string }>();
    const requestedChannelRef = useMemo(() => {
        const params = new URLSearchParams(location.search);
        return (params.get('channel') || params.get('channelId') || '').trim();
    }, [location.search]);
    const requestedLaunchAction = useMemo(() => {
        const params = new URLSearchParams(location.search);
        return (params.get('action') || '').trim();
    }, [location.search]);
    const [channels, setChannels] = useState<SupportChannel[]>([]);
    const [serverChannelActivationBacklog, setServerChannelActivationBacklog] = useState<SupportChannelActivationBacklog | null>(null);
    const [channelPresets, setChannelPresets] = useState<SupportChannelPreset[]>([]);
    const [channelCursors, setChannelCursors] = useState<SupportChannelCursor[]>([]);
    const [syncRuns, setSyncRuns] = useState<SupportChannelSyncRunRecord[]>([]);
    const [channelWebhookEvents, setChannelWebhookEvents] = useState<SupportChannelWebhookEvent[]>([]);
    const [deliveryRuns, setDeliveryRuns] = useState<SupportDeliveryRunRecord[]>([]);
    const [supportQueues, setSupportQueues] = useState<SupportQueue[]>([]);
    const [webChatSessions, setWebChatSessions] = useState<SupportWebChatSession[]>([]);
    const [crmConnectors, setCrmConnectors] = useState<SupportCrmConnector[]>([]);
    const [crmSyncRuns, setCrmSyncRuns] = useState<SupportCrmSyncRunRecord[]>([]);
    const [crmWebhookEvents, setCrmWebhookEvents] = useState<SupportCrmWebhookEvent[]>([]);
    const [crmValidation, setCrmValidation] = useState<SupportCrmValidation | null>(null);
    const [currentUserEmail, setCurrentUserEmail] = useState(() => currentEmailFromToken());
    const [selectedKey, setSelectedKey] = useState('');
    const [selectedQueueKey, setSelectedQueueKey] = useState('');
    const [selectedCrmKey, setSelectedCrmKey] = useState('');
    const [loading, setLoading] = useState(false);
    const [saving, setSaving] = useState(false);
    const [savingQueue, setSavingQueue] = useState(false);
    const [savingCrm, setSavingCrm] = useState(false);
    const [deliveryRunMode, setDeliveryRunMode] = useState<'' | 'queued' | 'failed'>('');
    const [syncingChannel, setSyncingChannel] = useState('');
    const [testingChannel, setTestingChannel] = useState('');
    const [smokingChannel, setSmokingChannel] = useState('');
    const [smokingOutboundChannel, setSmokingOutboundChannel] = useState('');
    const [smokingLifecycleChannel, setSmokingLifecycleChannel] = useState('');
    const [smokingAllChannels, setSmokingAllChannels] = useState(false);
    const [smokingOutboundAllChannels, setSmokingOutboundAllChannels] = useState(false);
    const [smokingLifecycleAllChannels, setSmokingLifecycleAllChannels] = useState(false);
    const [rematchingWebhookEvent, setRematchingWebhookEvent] = useState('');
    const [validatingSetup, setValidatingSetup] = useState('');
    const [installingSlack, setInstallingSlack] = useState(false);
    const [settingTelegramWebhook, setSettingTelegramWebhook] = useState(false);
    const [setupValidation, setSetupValidation] = useState<SupportChannelValidation | null>(null);
    const [creatingSurfaceType, setCreatingSurfaceType] = useState('');
    const [bootstrappingSurfaces, setBootstrappingSurfaces] = useState(false);
    const [activatingReadySurfaces, setActivatingReadySurfaces] = useState(false);
    const [syncingCrm, setSyncingCrm] = useState('');
    const [validatingCrm, setValidatingCrm] = useState('');
    const [type, setType] = useState('email');
    const [name, setName] = useState('');
    const [status, setStatus] = useState('active');
    const [channelKey, setChannelKey] = useState('');
    const [ticketCreationMode, setTicketCreationMode] = useState<TicketCreationMode>('per_message');
    const [outboundPayloadMode, setOutboundPayloadMode] = useState<OutboundPayloadMode>('provider');
    const [autoPrepareTriage, setAutoPrepareTriage] = useState(true);
    const [autoPrepareCustomFields, setAutoPrepareCustomFields] = useState(true);
    const [autoPrepareAgentReply, setAutoPrepareAgentReply] = useState(true);
    const [autoPrepareAgentReplyOnUpdate, setAutoPrepareAgentReplyOnUpdate] = useState(true);
    const [agentAutoSend, setAgentAutoSend] = useState(false);
    const [includeFeedbackLink, setIncludeFeedbackLink] = useState(true);
    const [agentQuestion, setAgentQuestion] = useState('');
    const [defaultAssigneeEmail, setDefaultAssigneeEmail] = useState('');
    const [defaultQueueKey, setDefaultQueueKey] = useState('');
    const [defaultQueueName, setDefaultQueueName] = useState('');
    const [webhookTokenEnv, setWebhookTokenEnv] = useState('');
    const [signatureSecretEnv, setSignatureSecretEnv] = useState('');
    const [signatureHeader, setSignatureHeader] = useState('');
    const [outboundTransport, setOutboundTransport] = useState<OutboundTransport>('');
    const [outboundWebhookUrl, setOutboundWebhookUrl] = useState('');
    const [outboundWebhookUrlEnv, setOutboundWebhookUrlEnv] = useState('');
    const [outboundWebhookTokenEnv, setOutboundWebhookTokenEnv] = useState('');
    const [outboundBotTokenEnv, setOutboundBotTokenEnv] = useState('');
    const [teamsAppIdEnv, setTeamsAppIdEnv] = useState('');
    const [teamsAppPasswordEnv, setTeamsAppPasswordEnv] = useState('');
    const [smokeTargetChannelId, setSmokeTargetChannelId] = useState('');
    const [smokeTargetThreadId, setSmokeTargetThreadId] = useState('');
    const [smokeTargetProviderMessageId, setSmokeTargetProviderMessageId] = useState('');
    const [smokeTargetToAddress, setSmokeTargetToAddress] = useState('');
    const [smokeTargetConversationId, setSmokeTargetConversationId] = useState('');
    const [smokeTargetReplyToId, setSmokeTargetReplyToId] = useState('');
    const [smokeTargetServiceUrl, setSmokeTargetServiceUrl] = useState('');
    const [configJson, setConfigJson] = useState(defaultChannelConfig);
    const [queueKey, setQueueKey] = useState('');
    const [queueName, setQueueName] = useState('');
    const [queueStatus, setQueueStatus] = useState('active');
    const [queueDefaultAssigneeEmail, setQueueDefaultAssigneeEmail] = useState('');
    const [queueOwnerEmailsDraft, setQueueOwnerEmailsDraft] = useState('');
    const [queueRoutingMode, setQueueRoutingMode] = useState<QueueRoutingMode>('static');
    const [queueOwnerCapacityDraft, setQueueOwnerCapacityDraft] = useState('');
    const [queueDescription, setQueueDescription] = useState('');
    const [testMessageBody, setTestMessageBody] = useState('Customer test message from channel setup.');
    const [testAuthorName, setTestAuthorName] = useState('Test customer');
    const [testAuthorEmail, setTestAuthorEmail] = useState('customer@example.com');
    const [testChannelId, setTestChannelId] = useState('');
    const [testThreadId, setTestThreadId] = useState('');
    const [testProviderMessageId, setTestProviderMessageId] = useState('');
    const [outboundSmokeBody, setOutboundSmokeBody] = useState('Thanks for reaching out. Testing outbound delivery from channel setup.');
    const [lifecycleAttachmentOnly, setLifecycleAttachmentOnly] = useState(false);
    const [testMessageResult, setTestMessageResult] = useState<SupportChannelTestMessageResult | null>(null);
    const [smokeResult, setSmokeResult] = useState<SupportChannelSmokeResult | null>(null);
    const [outboundSmokeResult, setOutboundSmokeResult] = useState<SupportChannelOutboundSmokeResult | null>(null);
    const [lifecycleSmokeResult, setLifecycleSmokeResult] = useState<SupportChannelLifecycleSmokeResult | null>(null);
    const [smokeRun, setSmokeRun] = useState<SupportChannelSmokeRun | null>(null);
    const [outboundSmokeRun, setOutboundSmokeRun] = useState<SupportChannelOutboundSmokeRun | null>(null);
    const [lifecycleSmokeRun, setLifecycleSmokeRun] = useState<SupportChannelLifecycleSmokeRun | null>(null);
    const [smokeAllTransport, setSmokeAllTransport] = useState<'direct' | 'http'>('http');
    const [crmProvider, setCrmProvider] = useState('hubspot');
    const [crmName, setCrmName] = useState('');
    const [crmStatus, setCrmStatus] = useState('active');
    const [crmConnectorKey, setCrmConnectorKey] = useState('');
    const [crmConfigJson, setCrmConfigJson] = useState('{}');

    const selectedChannel = useMemo(
        () => channels.find(channel => channel.channelKey === selectedKey) ?? null,
        [channels, selectedKey],
    );
    const selectedChannelSupportsOutboundSmoke = Boolean(
        selectedChannel && supportsProviderLifecycle(selectedChannel.type),
    );
    const liveProofTargetRows = liveProofTargetRequirements(type, {
        channelId: smokeTargetChannelId,
        threadId: smokeTargetThreadId,
        toAddress: smokeTargetToAddress,
        conversationId: smokeTargetConversationId,
        replyToId: smokeTargetReplyToId,
        serviceUrl: smokeTargetServiceUrl,
    });
    const requiredLiveProofTargetRows = liveProofTargetRows.filter(row => row.required);
    const configuredLiveProofTargetRows = requiredLiveProofTargetRows.filter(row => row.configured);
    const liveProofConfigured = liveProofTargetConfigured(type, {
        channelId: smokeTargetChannelId,
        threadId: smokeTargetThreadId,
        toAddress: smokeTargetToAddress,
        conversationId: smokeTargetConversationId,
        serviceUrl: smokeTargetServiceUrl,
    });
    const liveProofEvidence = liveProofEvidenceRows(selectedChannel);
    const liveProofRequired = Boolean(
        (selectedChannel?.setup?.launchChecklist ?? selectedChannel?.setup?.launch?.checklist ?? [])
            .some(step => step.key === 'live_smoke_target'),
    );
    const missingLiveProofTargets = requiredLiveProofTargetRows
        .filter(row => !row.configured)
        .map(row => row.configKey);
    const selectedSupportModeSteps = useMemo(() => [
        {
            key: 'ticket_mode',
            label: t('New message = ticket'),
            ready: ticketCreationMode === 'per_message',
        },
        {
            key: 'triage',
            label: t('AI triage'),
            ready: autoPrepareTriage,
        },
        {
            key: 'fields',
            label: t('AI fields'),
            ready: autoPrepareCustomFields,
        },
        {
            key: 'draft',
            label: t('AI draft'),
            ready: autoPrepareAgentReply,
        },
        {
            key: 'follow_up',
            label: t('AI follow-up'),
            ready: autoPrepareAgentReplyOnUpdate,
        },
        {
            key: 'approval',
            label: t('Approval required'),
            ready: !agentAutoSend,
        },
    ], [agentAutoSend, autoPrepareAgentReply, autoPrepareAgentReplyOnUpdate, autoPrepareCustomFields, autoPrepareTriage, t, ticketCreationMode]);
    const selectedSupportModeReady = Boolean(selectedChannel && selectedSupportModeSteps.every(step => step.ready));
    const selectedSupportModeMissing = selectedSupportModeSteps.filter(step => !step.ready);

    const selectedPreset = useMemo(
        () => channelPresets.find(preset => preset.type === type || (type === 'chat' && preset.type === 'web_chat')) ?? null,
        [channelPresets, type],
    );

    const selectedQueue = useMemo(
        () => supportQueues.find(queue => queue.queueKey === selectedQueueKey) ?? null,
        [selectedQueueKey, supportQueues],
    );
    const selectedQueueIsVirtual = selectedQueue?.metadata?.virtual === true;
    const selectedDefaultQueue = useMemo(
        () => supportQueues.find(queue => queue.queueKey === defaultQueueKey.trim()) ?? null,
        [defaultQueueKey, supportQueues],
    );
    const routingPreview = useMemo(() => {
        const channelOwner = defaultAssigneeEmail.trim().toLowerCase();
        const queueOwner = (selectedDefaultQueue?.defaultAssigneeEmail || '').trim().toLowerCase();
        const queueOwners = queueOwnerEmails(selectedDefaultQueue);
        const queueMode = queueRoutingModeFrom(selectedDefaultQueue);
        const queueKeyLabel = defaultQueueKey.trim();
        const queueLabel = defaultQueueName.trim() || selectedDefaultQueue?.name || queueKeyLabel;
        if (channelOwner) {
            return {
                ready: true,
                status: 'Channel owner',
                assignment: channelOwner,
                queue: queueLabel || 'Support',
                detail: queueLabel ? `New tickets route to ${queueLabel}.` : 'New tickets use the default support queue.',
            };
        }
        if (queueMode === 'least_open' && queueOwners.length > 0) {
            return {
                ready: true,
                status: 'Least-open queue owner',
                assignment: queueOwners.join(', '),
                queue: queueLabel || queueKeyLabel,
                detail: queueLabel
                    ? `New tickets route through ${queueLabel} to the least-loaded owner.`
                    : 'New tickets route to the least-loaded queue owner.',
            };
        }
        if (queueOwner) {
            return {
                ready: true,
                status: 'Queue owner',
                assignment: queueOwner,
                queue: queueLabel || queueKeyLabel,
                detail: queueLabel
                    ? `New tickets route through ${queueLabel}.`
                    : 'New tickets route through the selected queue.',
            };
        }
        if (queueKeyLabel) {
            return {
                ready: false,
                status: 'Queue needs owner',
                assignment: '-',
                queue: queueLabel || queueKeyLabel,
                detail: 'Set a queue default assignee or channel default assignee.',
            };
        }
        return {
            ready: false,
            status: 'Needs owner',
            assignment: '-',
            queue: 'Support',
            detail: 'Set a default owner before launch.',
        };
    }, [defaultAssigneeEmail, defaultQueueKey, defaultQueueName, selectedDefaultQueue]);

    const selectedCrmConnector = useMemo(
        () => crmConnectors.find(connector => connector.connectorKey === selectedCrmKey) ?? null,
        [crmConnectors, selectedCrmKey],
    );
    const selectedCrmPreset = useMemo(
        () => crmProviderPreset(crmProvider),
        [crmProvider],
    );

    const loadChannelActivationBacklog = useCallback(() => {
        setServerChannelActivationBacklog(null);
        void api.getChannelActivationBacklog(projectId).then((res) => {
            if (res.error || !res.data) {
                return;
            }
            setServerChannelActivationBacklog(res.data);
        });
    }, [projectId]);

    const loadChannels = useCallback(() => {
        setLoading(true);
        void api.getChannels(projectId).then((res) => {
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not load channels'));
                return;
            }
            setChannels(res.data.items);
            loadChannelActivationBacklog();
        }).finally(() => setLoading(false));
    }, [loadChannelActivationBacklog, projectId, t]);

    const loadChannelPresets = useCallback(() => {
        void api.getChannelPresets(projectId).then((res) => {
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not load channel presets'));
                return;
            }
            setChannelPresets(res.data.items);
        });
    }, [projectId, t]);

    const loadSyncRuns = useCallback((channelId = '') => {
        void api.getChannelSyncRuns(projectId, channelId).then((res) => {
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not load sync runs'));
                return;
            }
            setSyncRuns(res.data.items);
        });
    }, [projectId, t]);

    const loadChannelCursors = useCallback((channelId = '') => {
        void api.getChannelCursors(projectId, channelId).then((res) => {
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not load channel cursors'));
                return;
            }
            setChannelCursors(res.data.items);
        });
    }, [projectId, t]);

    const loadChannelWebhookEvents = useCallback((channelId = '') => {
        void api.getChannelWebhookEvents(projectId, channelId).then((res) => {
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not load channel webhook events'));
                return;
            }
            setChannelWebhookEvents(res.data.items);
        });
    }, [projectId, t]);

    const loadDeliveryRuns = useCallback(() => {
        void api.getSupportDeliveryRuns(projectId).then((res) => {
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not load delivery runs'));
                return;
            }
            setDeliveryRuns(res.data.items);
        });
    }, [projectId, t]);

    const loadQueues = useCallback(() => {
        void api.getSupportQueues(projectId, 'all').then((res) => {
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not load queues'));
                return;
            }
            setSupportQueues(res.data.items);
            setSelectedQueueKey(prev => {
                if (prev && res.data?.items.some(queue => queue.queueKey === prev)) return prev;
                return res.data?.items[0]?.queueKey ?? '';
            });
        });
    }, [projectId, t]);

    const loadWebChatSessions = useCallback((channelId = '') => {
        void api.getWebChatSessions(projectId, channelId).then((res) => {
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not load web chat sessions'));
                return;
            }
            setWebChatSessions(res.data.items);
        });
    }, [projectId, t]);

    const loadCrmConnectors = useCallback(() => {
        void api.getCrmConnectors(projectId).then((res) => {
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not load CRM connectors'));
                return;
            }
            setCrmConnectors(res.data.items);
        });
    }, [projectId, t]);

    const loadCrmSyncRuns = useCallback((connectorId = '') => {
        void api.getCrmSyncRuns(projectId, connectorId).then((res) => {
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not load CRM sync runs'));
                return;
            }
            setCrmSyncRuns(res.data.items);
        });
    }, [projectId, t]);

    const loadCrmWebhookEvents = useCallback((connectorId = '') => {
        void api.getCrmWebhookEvents(projectId, connectorId).then((res) => {
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not load CRM webhook events'));
                return;
            }
            setCrmWebhookEvents(res.data.items);
        });
    }, [projectId, t]);

    useEffect(() => {
        const timer = window.setTimeout(() => loadChannels(), 0);
        return () => window.clearTimeout(timer);
    }, [loadChannels]);

    useEffect(() => {
        const timer = window.setTimeout(() => loadChannelPresets(), 0);
        return () => window.clearTimeout(timer);
    }, [loadChannelPresets]);

    useEffect(() => {
        const timer = window.setTimeout(() => loadSyncRuns(selectedChannel?.id ?? ''), 0);
        return () => window.clearTimeout(timer);
    }, [loadSyncRuns, selectedChannel?.id]);

    useEffect(() => {
        const timer = window.setTimeout(() => loadChannelCursors(selectedChannel?.id ?? ''), 0);
        return () => window.clearTimeout(timer);
    }, [loadChannelCursors, selectedChannel?.id]);

    useEffect(() => {
        const timer = window.setTimeout(() => loadChannelWebhookEvents(selectedChannel?.id ?? ''), 0);
        return () => window.clearTimeout(timer);
    }, [loadChannelWebhookEvents, selectedChannel?.id]);

    useEffect(() => {
        const timer = window.setTimeout(() => loadDeliveryRuns(), 0);
        return () => window.clearTimeout(timer);
    }, [loadDeliveryRuns]);

    useEffect(() => {
        const timer = window.setTimeout(() => loadQueues(), 0);
        return () => window.clearTimeout(timer);
    }, [loadQueues]);

    useEffect(() => {
        let cancelled = false;
        void api.getCurrentUser().then((res) => {
            if (!cancelled && res.data?.email) {
                setCurrentUserEmail(res.data.email);
            } else if (!cancelled) {
                setCurrentUserEmail(prev => prev || currentEmailFromToken());
            }
        });
        return () => { cancelled = true; };
    }, []);

    useEffect(() => {
        const timer = window.setTimeout(() => loadWebChatSessions(selectedChannel?.id ?? ''), 0);
        return () => window.clearTimeout(timer);
    }, [loadWebChatSessions, selectedChannel?.id]);

    useEffect(() => {
        const timer = window.setTimeout(() => loadCrmConnectors(), 0);
        return () => window.clearTimeout(timer);
    }, [loadCrmConnectors]);

    useEffect(() => {
        const timer = window.setTimeout(() => loadCrmSyncRuns(selectedCrmConnector?.id ?? ''), 0);
        return () => window.clearTimeout(timer);
    }, [loadCrmSyncRuns, selectedCrmConnector?.id]);

    useEffect(() => {
        const timer = window.setTimeout(() => loadCrmWebhookEvents(selectedCrmConnector?.id ?? ''), 0);
        return () => window.clearTimeout(timer);
    }, [loadCrmWebhookEvents, selectedCrmConnector?.id]);

    useEffect(() => {
        const timer = window.setTimeout(() => {
            if (!selectedChannel) {
                setType('email');
                setName('');
                setStatus('active');
                setChannelKey('');
                setTicketCreationMode('per_message');
                setOutboundPayloadMode('provider');
                setAutoPrepareTriage(true);
                setAutoPrepareCustomFields(true);
                setAutoPrepareAgentReply(true);
                setAutoPrepareAgentReplyOnUpdate(true);
                setAgentAutoSend(false);
                setIncludeFeedbackLink(true);
                setAgentQuestion('');
                setDefaultAssigneeEmail(currentUserEmail);
                setDefaultQueueKey('');
                setDefaultQueueName('');
                setWebhookTokenEnv('');
                setSignatureSecretEnv('');
                setSignatureHeader('');
                setOutboundTransport('');
                setOutboundWebhookUrl('');
                setOutboundWebhookUrlEnv('');
                setOutboundWebhookTokenEnv('');
                setOutboundBotTokenEnv('');
                setTeamsAppIdEnv('');
                setTeamsAppPasswordEnv('');
                setSmokeTargetChannelId('');
                setSmokeTargetThreadId('');
                setSmokeTargetProviderMessageId('');
                setSmokeTargetToAddress('');
                setSmokeTargetConversationId('');
                setSmokeTargetReplyToId('');
                setSmokeTargetServiceUrl('');
                setConfigJson(defaultChannelConfig());
                return;
            }
            setType(selectedChannel.type || 'email');
            setName(selectedChannel.name);
            setStatus(selectedChannel.status || 'active');
            setChannelKey(selectedChannel.channelKey);
            setTicketCreationMode(ticketCreationModeFromConfig(selectedChannel.config));
            setOutboundPayloadMode(outboundPayloadModeFromConfig(selectedChannel.config));
            setAutoPrepareTriage(boolFromConfig(selectedChannel.config, 'autoPrepareTriage', 'auto_prepare_triage', true));
            setAutoPrepareCustomFields(boolFromConfig(selectedChannel.config, 'autoPrepareCustomFields', 'auto_prepare_custom_fields', true));
            setAutoPrepareAgentReply(boolFromConfig(selectedChannel.config, 'autoPrepareAgentReply', 'auto_prepare_agent_reply', false));
            setAutoPrepareAgentReplyOnUpdate(boolFromConfig(selectedChannel.config, 'autoPrepareAgentReplyOnUpdate', 'auto_prepare_agent_reply_on_update', false));
            setAgentAutoSend(boolFromConfig(
                selectedChannel.config,
                'agentAutoSend',
                'agent_auto_send',
                boolFromConfig(selectedChannel.config, 'autoSendAgentReply', 'auto_send_agent_reply', false),
            ));
            setIncludeFeedbackLink(boolFromConfig(
                selectedChannel.config,
                'includeFeedbackLink',
                'include_feedback_link',
                boolFromConfig(selectedChannel.config, 'agentIncludeFeedbackLink', 'agent_include_feedback_link', false),
            ));
            setAgentQuestion(textFromConfig(selectedChannel.config, 'agentQuestion', 'agent_question'));
            setDefaultAssigneeEmail(textFromConfig(selectedChannel.config, 'defaultAssigneeEmail', 'default_assignee_email'));
            setDefaultQueueKey(textFromConfig(selectedChannel.config, 'defaultQueueKey', 'default_queue_key'));
            setDefaultQueueName(textFromConfig(selectedChannel.config, 'defaultQueueName', 'default_queue_name'));
            setWebhookTokenEnv(
                textFromConfig(selectedChannel.config, 'webhookTokenEnv', 'webhook_token_env')
                || textFromConfig(selectedChannel.config, 'providerTokenEnv', 'provider_token_env'),
            );
            setSignatureSecretEnv(
                textFromConfig(selectedChannel.config, 'slackSigningSecretEnv', 'slack_signing_secret_env')
                || textFromConfig(selectedChannel.config, 'viberAuthTokenEnv', 'viber_auth_token_env')
                || textFromConfig(selectedChannel.config, 'authTokenEnv', 'auth_token_env')
                || textFromConfig(selectedChannel.config, 'whatsappSigningSecretEnv', 'whatsapp_signing_secret_env')
                || textFromConfig(selectedChannel.config, 'messengerSigningSecretEnv', 'messenger_signing_secret_env')
                || textFromConfig(selectedChannel.config, 'instagramSigningSecretEnv', 'instagram_signing_secret_env')
                || textFromConfig(selectedChannel.config, 'twitterConsumerSecretEnv', 'twitter_consumer_secret_env')
                || textFromConfig(selectedChannel.config, 'xConsumerSecretEnv', 'x_consumer_secret_env')
                || textFromConfig(selectedChannel.config, 'consumerSecretEnv', 'consumer_secret_env')
                || textFromConfig(selectedChannel.config, 'appSecretEnv', 'app_secret_env')
                || textFromConfig(selectedChannel.config, 'twilioSigningSecretEnv', 'twilio_signing_secret_env')
                || textFromConfig(selectedChannel.config, 'smsSigningSecretEnv', 'sms_signing_secret_env')
                || textFromConfig(selectedChannel.config, 'signatureSecretEnv', 'signature_secret_env')
                || textFromConfig(selectedChannel.config, 'webhookSignatureSecretEnv', 'webhook_signature_secret_env'),
            );
            setSignatureHeader(textFromConfig(selectedChannel.config, 'signatureHeader', 'signature_header'));
            setOutboundTransport(
                outboundTransportFromConfig(selectedChannel.config, selectedChannel.type)
                || (
                    selectedChannel.setup?.outboundTransport === 'provider_api' && providerApiOutboundSupported(selectedChannel.type)
                        ? 'provider_api'
                        : selectedChannel.setup?.outboundTransport === 'bot' ? 'bot' : ''
                ),
            );
            setOutboundWebhookUrl(textFromConfig(selectedChannel.config, 'outboundWebhookUrl', 'outbound_webhook_url'));
            setOutboundWebhookUrlEnv(textFromConfig(selectedChannel.config, 'outboundWebhookUrlEnv', 'outbound_webhook_url_env'));
            setOutboundWebhookTokenEnv(textFromConfig(selectedChannel.config, 'outboundWebhookTokenEnv', 'outbound_webhook_token_env'));
            setOutboundBotTokenEnv(
                textFromConfig(selectedChannel.config, 'slackBotTokenEnv', 'slack_bot_token_env')
                || textFromConfig(selectedChannel.config, 'discordBotTokenEnv', 'discord_bot_token_env')
                || textFromConfig(selectedChannel.config, 'telegramBotTokenEnv', 'telegram_bot_token_env')
                || textFromConfig(selectedChannel.config, 'botTokenEnv', 'bot_token_env')
                || selectedChannel.setup?.outboundBotTokenEnv
                || '',
            );
            setTeamsAppIdEnv(textFromConfig(selectedChannel.config, 'teamsAppIdEnv', 'teams_app_id_env'));
            setTeamsAppPasswordEnv(textFromConfig(selectedChannel.config, 'teamsAppPasswordEnv', 'teams_app_password_env'));
            setSmokeTargetChannelId(
                textFromConfig(selectedChannel.config, 'smokeChannelId', 'smoke_channel_id')
                || textFromConfig(selectedChannel.config, 'smokeChatId', 'smoke_chat_id'),
            );
            setSmokeTargetThreadId(
                textFromConfig(selectedChannel.config, 'smokeThreadTs', 'smoke_thread_ts')
                || textFromConfig(selectedChannel.config, 'smokeThreadId', 'smoke_thread_id'),
            );
            setSmokeTargetProviderMessageId(
                textFromConfig(selectedChannel.config, 'smokeProviderMessageId', 'smoke_provider_message_id')
                || textFromConfig(selectedChannel.config, 'smokeMessageId', 'smoke_message_id'),
            );
            setSmokeTargetToAddress(textFromConfig(selectedChannel.config, 'smokeToAddress', 'smoke_to_address'));
            setSmokeTargetConversationId(textFromConfig(selectedChannel.config, 'smokeConversationId', 'smoke_conversation_id'));
            setSmokeTargetReplyToId(textFromConfig(selectedChannel.config, 'smokeReplyToId', 'smoke_reply_to_id'));
            setSmokeTargetServiceUrl(textFromConfig(selectedChannel.config, 'smokeServiceUrl', 'smoke_service_url'));
            setConfigJson(JSON.stringify(selectedChannel.config || {}, null, 2));
        }, 0);
        return () => window.clearTimeout(timer);
    }, [currentUserEmail, selectedChannel]);

    useEffect(() => {
        const timer = window.setTimeout(() => {
            if (!selectedCrmConnector) {
                const preset = crmProviderPreset('hubspot');
                setCrmProvider(preset.provider);
                setCrmName('');
                setCrmStatus('active');
                setCrmConnectorKey(preset.defaultKey);
                setCrmConfigJson(JSON.stringify(preset.config, null, 2));
                setCrmValidation(null);
                return;
            }
            setCrmProvider(selectedCrmConnector.provider || 'hubspot');
            setCrmName(selectedCrmConnector.name);
            setCrmStatus(selectedCrmConnector.status || 'active');
            setCrmConnectorKey(selectedCrmConnector.connectorKey);
            setCrmConfigJson(JSON.stringify(selectedCrmConnector.config || {}, null, 2));
            setCrmValidation(null);
        }, 0);
        return () => window.clearTimeout(timer);
    }, [selectedCrmConnector]);

    useEffect(() => {
        const timer = window.setTimeout(() => {
            if (!selectedQueue) {
                setQueueKey('');
                setQueueName('');
                setQueueStatus('active');
                setQueueDefaultAssigneeEmail('');
                setQueueOwnerEmailsDraft('');
                setQueueRoutingMode('static');
                setQueueOwnerCapacityDraft('');
                setQueueDescription('');
                return;
            }
            setQueueKey(selectedQueue.queueKey);
            setQueueName(selectedQueue.name);
            setQueueStatus(selectedQueue.status || 'active');
            setQueueDefaultAssigneeEmail(selectedQueue.defaultAssigneeEmail || '');
            setQueueOwnerEmailsDraft(queueOwnerEmails(selectedQueue).join(', '));
            setQueueRoutingMode(queueRoutingModeFrom(selectedQueue));
            setQueueOwnerCapacityDraft(queueOwnerCapacity(selectedQueue) ? String(queueOwnerCapacity(selectedQueue)) : '');
            setQueueDescription(selectedQueue.description || '');
        }, 0);
        return () => window.clearTimeout(timer);
    }, [selectedQueue]);

    const startNew = () => {
        setSelectedKey('');
        setType('email');
        setName('');
        setStatus('active');
        setChannelKey('');
        setTicketCreationMode('per_message');
        setOutboundPayloadMode('provider');
        setAutoPrepareAgentReply(true);
        setAutoPrepareAgentReplyOnUpdate(true);
        setIncludeFeedbackLink(true);
        setAgentQuestion('');
        setDefaultAssigneeEmail(currentUserEmail);
        setDefaultQueueKey('');
        setDefaultQueueName('');
        setWebhookTokenEnv('');
        setSignatureSecretEnv('');
        setSignatureHeader('');
        setOutboundWebhookUrl('');
        setOutboundWebhookUrlEnv('');
        setOutboundWebhookTokenEnv('');
        setOutboundBotTokenEnv('');
        setTeamsAppIdEnv('');
        setTeamsAppPasswordEnv('');
        setSmokeTargetChannelId('');
        setSmokeTargetThreadId('');
        setSmokeTargetProviderMessageId('');
        setSmokeTargetToAddress('');
        setSmokeTargetConversationId('');
        setSmokeTargetReplyToId('');
        setSmokeTargetServiceUrl('');
        setConfigJson(defaultChannelConfig());
        setTestChannelId('');
        setTestThreadId('');
        setTestProviderMessageId('');
        setTestMessageResult(null);
        setSmokeResult(null);
        setOutboundSmokeResult(null);
        setLifecycleSmokeResult(null);
        setSetupValidation(null);
    };

    const applyChannelPreset = (preset: SupportChannelPreset) => {
        const nextType = channelTypeFromPreset(preset);
        const presetDefaultAssignee = textFromConfig(preset.config, 'defaultAssigneeEmail', 'default_assignee_email');
        setType(nextType);
        setTicketCreationMode(presetTicketCreationMode(preset.ticketCreationMode));
        setOutboundPayloadMode(presetOutboundPayloadMode(preset.outboundPayloadMode));
        setAutoPrepareTriage(boolFromConfig(preset.config, 'autoPrepareTriage', 'auto_prepare_triage', true));
        setAutoPrepareCustomFields(boolFromConfig(preset.config, 'autoPrepareCustomFields', 'auto_prepare_custom_fields', true));
        setAutoPrepareAgentReply(preset.autoPrepareAgentReply);
        setAutoPrepareAgentReplyOnUpdate(preset.autoPrepareAgentReplyOnUpdate);
        setAgentAutoSend(boolFromConfig(preset.config, 'agentAutoSend', 'agent_auto_send', false));
        setIncludeFeedbackLink(boolFromConfig(
            preset.config,
            'includeFeedbackLink',
            'include_feedback_link',
            boolFromConfig(preset.config, 'agentIncludeFeedbackLink', 'agent_include_feedback_link', true),
        ));
        setAgentQuestion(textFromConfig(preset.config, 'agentQuestion', 'agent_question'));
        setDefaultAssigneeEmail(presetDefaultAssignee || defaultAssigneeEmail || currentUserEmail);
        setDefaultQueueKey(preset.defaultQueueKey);
        setDefaultQueueName(preset.defaultQueueName);
        setWebhookTokenEnv(textFromConfig(preset.config, 'webhookTokenEnv', 'webhook_token_env'));
        setSignatureSecretEnv(
            textFromConfig(preset.config, 'slackSigningSecretEnv', 'slack_signing_secret_env')
            || textFromConfig(preset.config, 'viberAuthTokenEnv', 'viber_auth_token_env')
            || textFromConfig(preset.config, 'authTokenEnv', 'auth_token_env')
            || textFromConfig(preset.config, 'whatsappSigningSecretEnv', 'whatsapp_signing_secret_env')
            || textFromConfig(preset.config, 'messengerSigningSecretEnv', 'messenger_signing_secret_env')
            || textFromConfig(preset.config, 'instagramSigningSecretEnv', 'instagram_signing_secret_env')
            || textFromConfig(preset.config, 'twitterConsumerSecretEnv', 'twitter_consumer_secret_env')
            || textFromConfig(preset.config, 'xConsumerSecretEnv', 'x_consumer_secret_env')
            || textFromConfig(preset.config, 'consumerSecretEnv', 'consumer_secret_env')
            || textFromConfig(preset.config, 'appSecretEnv', 'app_secret_env')
            || textFromConfig(preset.config, 'twilioSigningSecretEnv', 'twilio_signing_secret_env')
            || textFromConfig(preset.config, 'smsSigningSecretEnv', 'sms_signing_secret_env')
            || textFromConfig(preset.config, 'signatureSecretEnv', 'signature_secret_env'),
        );
        setSignatureHeader(textFromConfig(preset.config, 'signatureHeader', 'signature_header'));
        setOutboundTransport(outboundTransportFromConfig(preset.config, nextType));
        setOutboundWebhookUrl(preset.outboundWebhookUrl || textFromConfig(preset.config, 'outboundWebhookUrl', 'outbound_webhook_url'));
        setOutboundWebhookUrlEnv(preset.outboundWebhookUrlEnv || textFromConfig(preset.config, 'outboundWebhookUrlEnv', 'outbound_webhook_url_env'));
        setOutboundWebhookTokenEnv(preset.outboundWebhookTokenEnv || textFromConfig(preset.config, 'outboundWebhookTokenEnv', 'outbound_webhook_token_env'));
        setOutboundBotTokenEnv(
            textFromConfig(preset.config, 'slackBotTokenEnv', 'slack_bot_token_env')
            || textFromConfig(preset.config, 'discordBotTokenEnv', 'discord_bot_token_env')
            || textFromConfig(preset.config, 'telegramBotTokenEnv', 'telegram_bot_token_env')
            || textFromConfig(preset.config, 'botTokenEnv', 'bot_token_env'),
        );
        setTeamsAppIdEnv(textFromConfig(preset.config, 'teamsAppIdEnv', 'teams_app_id_env'));
        setTeamsAppPasswordEnv(textFromConfig(preset.config, 'teamsAppPasswordEnv', 'teams_app_password_env'));
        setSmokeTargetChannelId(
            textFromConfig(preset.config, 'smokeChannelId', 'smoke_channel_id')
            || textFromConfig(preset.config, 'smokeChatId', 'smoke_chat_id')
            || preset.testMessage.channelId
            || '',
        );
        setSmokeTargetThreadId(
            textFromConfig(preset.config, 'smokeThreadTs', 'smoke_thread_ts')
            || textFromConfig(preset.config, 'smokeThreadId', 'smoke_thread_id')
            || preset.testMessage.threadId
            || '',
        );
        setSmokeTargetProviderMessageId(
            textFromConfig(preset.config, 'smokeProviderMessageId', 'smoke_provider_message_id')
            || textFromConfig(preset.config, 'smokeMessageId', 'smoke_message_id'),
        );
        setSmokeTargetToAddress(textFromConfig(preset.config, 'smokeToAddress', 'smoke_to_address'));
        setSmokeTargetConversationId(textFromConfig(preset.config, 'smokeConversationId', 'smoke_conversation_id'));
        setSmokeTargetReplyToId(textFromConfig(preset.config, 'smokeReplyToId', 'smoke_reply_to_id'));
        setSmokeTargetServiceUrl(textFromConfig(preset.config, 'smokeServiceUrl', 'smoke_service_url'));
        setConfigJson(JSON.stringify(preset.config, null, 2));
        if (!selectedChannel && !name.trim()) setName(preset.name);
        if (!selectedChannel && !channelKey.trim()) setChannelKey(preset.channelKey);
        if (preset.testMessage.body) setTestMessageBody(preset.testMessage.body);
        if (preset.testMessage.channelId) setTestChannelId(preset.testMessage.channelId);
        if (preset.testMessage.threadId) setTestThreadId(preset.testMessage.threadId);
        setTestMessageResult(null);
        setSmokeResult(null);
        setOutboundSmokeResult(null);
        setLifecycleSmokeResult(null);
        setSetupValidation(null);
        toast.success(t('Preset applied'));
    };

    const selectChannel = useCallback((key: string) => {
        if (key !== selectedKey) {
            setTestMessageResult(null);
            setSmokeResult(null);
            setOutboundSmokeResult(null);
            setLifecycleSmokeResult(null);
            setSetupValidation(null);
        }
        setSelectedKey(key);
    }, [selectedKey]);

    useEffect(() => {
        if (!requestedChannelRef || channels.length === 0) return;
        const timer = window.setTimeout(() => {
            const match = channels.find(channel => (
                channel.channelKey === requestedChannelRef
                || channel.id === requestedChannelRef
            ));
            if (match && match.channelKey !== selectedKey) selectChannel(match.channelKey);
        }, 0);
        return () => window.clearTimeout(timer);
    }, [channels, requestedChannelRef, selectedKey, selectChannel]);

    const startNewCrm = () => {
        const preset = crmProviderPreset('hubspot');
        setSelectedCrmKey('');
        setCrmProvider(preset.provider);
        setCrmName(preset.defaultName);
        setCrmStatus('active');
        setCrmConnectorKey(preset.defaultKey);
        setCrmConfigJson(JSON.stringify(preset.config, null, 2));
        setCrmValidation(null);
    };

    const applyCrmProviderPreset = (provider = crmProvider, forceName = false) => {
        const preset = crmProviderPreset(provider);
        setCrmProvider(preset.provider);
        if (forceName || !crmName.trim()) setCrmName(preset.defaultName);
        if (forceName || !crmConnectorKey.trim()) setCrmConnectorKey(preset.defaultKey);
        setCrmConfigJson(JSON.stringify(preset.config, null, 2));
    };

    const changeCrmProvider = (provider: string) => {
        if (selectedCrmConnector) {
            setCrmProvider(provider);
            return;
        }
        applyCrmProviderPreset(provider, true);
    };

    const startNewQueue = () => {
        setSelectedQueueKey('');
        setQueueKey('');
        setQueueName('');
        setQueueStatus('active');
        setQueueDefaultAssigneeEmail('');
        setQueueOwnerEmailsDraft('');
        setQueueRoutingMode('static');
        setQueueOwnerCapacityDraft('');
        setQueueDescription('');
    };

    const saveChannelWithOverrides = async (
        overrides: ChannelSaveOverrides = {},
        successMessage = t('Saved'),
    ) => {
        let parsedConfig: Record<string, unknown>;
        try {
            parsedConfig = JSON.parse(configJson) as Record<string, unknown>;
        } catch {
            toast.error(t('Invalid JSON'));
            return;
        }
        const nextStatus = overrides.status ?? status;
        const nextTicketCreationMode = overrides.ticketCreationMode ?? ticketCreationMode;
        const nextAutoPrepareTriage = overrides.autoPrepareTriage ?? autoPrepareTriage;
        const nextAutoPrepareCustomFields = overrides.autoPrepareCustomFields ?? autoPrepareCustomFields;
        const nextAutoPrepareAgentReply = overrides.autoPrepareAgentReply ?? autoPrepareAgentReply;
        const nextAutoPrepareAgentReplyOnUpdate = overrides.autoPrepareAgentReplyOnUpdate ?? autoPrepareAgentReplyOnUpdate;
        const nextAgentAutoSend = overrides.agentAutoSend ?? agentAutoSend;
        let nextDefaultAssigneeEmail = overrides.defaultAssigneeEmail ?? defaultAssigneeEmail;
        const nextDefaultQueueKey = overrides.defaultQueueKey ?? defaultQueueKey;
        const nextDefaultQueueName = overrides.defaultQueueName ?? defaultQueueName;
        const nextDefaultQueue = supportQueues.find(queue => queue.queueKey === nextDefaultQueueKey.trim()) ?? null;
        const ownerRouted = Boolean(nextDefaultAssigneeEmail.trim()) || queueProvidesOwnerRouting(nextDefaultQueue);
        if (!ownerRouted && nextStatus === 'active' && currentUserEmail.trim()) {
            nextDefaultAssigneeEmail = currentUserEmail.trim();
        }
        if (nextStatus === 'active' && !nextDefaultAssigneeEmail.trim() && !queueProvidesOwnerRouting(nextDefaultQueue)) {
            toast.error(t('Default assignee is required for active channels.'));
            return;
        }
        parsedConfig.ticketCreationMode = nextTicketCreationMode;
        parsedConfig.outboundPayloadMode = outboundPayloadMode;
        parsedConfig.autoPrepareTriage = nextAutoPrepareTriage;
        parsedConfig.autoPrepareCustomFields = nextAutoPrepareCustomFields;
        parsedConfig.autoPrepareAgentReply = nextAutoPrepareAgentReply;
        parsedConfig.autoPrepareAgentReplyOnUpdate = nextAutoPrepareAgentReplyOnUpdate;
        parsedConfig.agentAutoSend = nextAgentAutoSend;
        parsedConfig.includeFeedbackLink = includeFeedbackLink;
        if (agentQuestion.trim()) {
            parsedConfig.agentQuestion = agentQuestion.trim();
        } else {
            delete parsedConfig.agentQuestion;
            delete parsedConfig.agent_question;
        }
        if (nextDefaultAssigneeEmail.trim()) {
            parsedConfig.defaultAssigneeEmail = nextDefaultAssigneeEmail.trim();
        } else {
            delete parsedConfig.defaultAssigneeEmail;
            delete parsedConfig.default_assignee_email;
        }
        if (nextDefaultQueueKey.trim()) {
            parsedConfig.defaultQueueKey = nextDefaultQueueKey.trim();
        } else {
            delete parsedConfig.defaultQueueKey;
            delete parsedConfig.default_queue_key;
        }
        if (nextDefaultQueueName.trim()) {
            parsedConfig.defaultQueueName = nextDefaultQueueName.trim();
        } else {
            delete parsedConfig.defaultQueueName;
            delete parsedConfig.default_queue_name;
        }
        if (webhookTokenEnv.trim()) {
            parsedConfig.webhookTokenEnv = webhookTokenEnv.trim();
        } else {
            delete parsedConfig.webhookTokenEnv;
            delete parsedConfig.webhook_token_env;
            delete parsedConfig.providerTokenEnv;
            delete parsedConfig.provider_token_env;
        }
        if (signatureSecretEnv.trim()) {
            if (type === 'slack') {
                parsedConfig.slackSigningSecretEnv = signatureSecretEnv.trim();
                delete parsedConfig.slack_signing_secret_env;
                delete parsedConfig.viberAuthTokenEnv;
                delete parsedConfig.viber_auth_token_env;
                delete parsedConfig.authTokenEnv;
                delete parsedConfig.auth_token_env;
                delete parsedConfig.whatsappSigningSecretEnv;
                delete parsedConfig.whatsapp_signing_secret_env;
                delete parsedConfig.messengerSigningSecretEnv;
                delete parsedConfig.messenger_signing_secret_env;
                delete parsedConfig.appSecretEnv;
                delete parsedConfig.app_secret_env;
                delete parsedConfig.signatureSecretEnv;
                delete parsedConfig.signature_secret_env;
                delete parsedConfig.webhookSignatureSecretEnv;
            } else if (type === 'viber') {
                parsedConfig.viberAuthTokenEnv = signatureSecretEnv.trim();
                delete parsedConfig.viber_auth_token_env;
                delete parsedConfig.authTokenEnv;
                delete parsedConfig.auth_token_env;
                delete parsedConfig.slackSigningSecretEnv;
                delete parsedConfig.slack_signing_secret_env;
                delete parsedConfig.whatsappSigningSecretEnv;
                delete parsedConfig.whatsapp_signing_secret_env;
                delete parsedConfig.messengerSigningSecretEnv;
                delete parsedConfig.messenger_signing_secret_env;
                delete parsedConfig.appSecretEnv;
                delete parsedConfig.app_secret_env;
                delete parsedConfig.twilioSigningSecretEnv;
                delete parsedConfig.twilio_signing_secret_env;
                delete parsedConfig.smsSigningSecretEnv;
                delete parsedConfig.sms_signing_secret_env;
                delete parsedConfig.signatureSecretEnv;
                delete parsedConfig.signature_secret_env;
                delete parsedConfig.webhookSignatureSecretEnv;
            } else if (type === 'whatsapp') {
                parsedConfig.whatsappSigningSecretEnv = signatureSecretEnv.trim();
                delete parsedConfig.whatsapp_signing_secret_env;
                delete parsedConfig.viberAuthTokenEnv;
                delete parsedConfig.viber_auth_token_env;
                delete parsedConfig.authTokenEnv;
                delete parsedConfig.auth_token_env;
                delete parsedConfig.appSecretEnv;
                delete parsedConfig.app_secret_env;
                delete parsedConfig.twilioSigningSecretEnv;
                delete parsedConfig.twilio_signing_secret_env;
                delete parsedConfig.smsSigningSecretEnv;
                delete parsedConfig.sms_signing_secret_env;
                delete parsedConfig.messengerSigningSecretEnv;
                delete parsedConfig.messenger_signing_secret_env;
                delete parsedConfig.signatureSecretEnv;
                delete parsedConfig.signature_secret_env;
                delete parsedConfig.webhookSignatureSecretEnv;
                delete parsedConfig.slackSigningSecretEnv;
                delete parsedConfig.slack_signing_secret_env;
            } else if (type === 'messenger') {
                parsedConfig.messengerSigningSecretEnv = signatureSecretEnv.trim();
                delete parsedConfig.messenger_signing_secret_env;
                delete parsedConfig.appSecretEnv;
                delete parsedConfig.app_secret_env;
                delete parsedConfig.twilioSigningSecretEnv;
                delete parsedConfig.twilio_signing_secret_env;
                delete parsedConfig.smsSigningSecretEnv;
                delete parsedConfig.sms_signing_secret_env;
                delete parsedConfig.signatureSecretEnv;
                delete parsedConfig.signature_secret_env;
                delete parsedConfig.webhookSignatureSecretEnv;
                delete parsedConfig.slackSigningSecretEnv;
                delete parsedConfig.slack_signing_secret_env;
                delete parsedConfig.viberAuthTokenEnv;
                delete parsedConfig.viber_auth_token_env;
                delete parsedConfig.authTokenEnv;
                delete parsedConfig.auth_token_env;
                delete parsedConfig.whatsappSigningSecretEnv;
                delete parsedConfig.whatsapp_signing_secret_env;
            } else if (type === 'instagram') {
                parsedConfig.instagramSigningSecretEnv = signatureSecretEnv.trim();
                delete parsedConfig.instagram_signing_secret_env;
                delete parsedConfig.appSecretEnv;
                delete parsedConfig.app_secret_env;
                delete parsedConfig.signatureSecretEnv;
                delete parsedConfig.signature_secret_env;
                delete parsedConfig.webhookSignatureSecretEnv;
            } else if (type === 'twitter') {
                parsedConfig.twitterConsumerSecretEnv = signatureSecretEnv.trim();
                delete parsedConfig.twitter_consumer_secret_env;
                delete parsedConfig.xConsumerSecretEnv;
                delete parsedConfig.x_consumer_secret_env;
                delete parsedConfig.consumerSecretEnv;
                delete parsedConfig.consumer_secret_env;
                delete parsedConfig.signatureSecretEnv;
                delete parsedConfig.signature_secret_env;
                delete parsedConfig.webhookSignatureSecretEnv;
            } else if (type === 'sms') {
                parsedConfig.twilioSigningSecretEnv = signatureSecretEnv.trim();
                delete parsedConfig.twilio_signing_secret_env;
                delete parsedConfig.smsSigningSecretEnv;
                delete parsedConfig.sms_signing_secret_env;
                delete parsedConfig.signatureSecretEnv;
                delete parsedConfig.signature_secret_env;
                delete parsedConfig.webhookSignatureSecretEnv;
                delete parsedConfig.slackSigningSecretEnv;
                delete parsedConfig.slack_signing_secret_env;
                delete parsedConfig.viberAuthTokenEnv;
                delete parsedConfig.viber_auth_token_env;
                delete parsedConfig.authTokenEnv;
                delete parsedConfig.auth_token_env;
                delete parsedConfig.whatsappSigningSecretEnv;
                delete parsedConfig.whatsapp_signing_secret_env;
                delete parsedConfig.messengerSigningSecretEnv;
                delete parsedConfig.messenger_signing_secret_env;
                delete parsedConfig.appSecretEnv;
                delete parsedConfig.app_secret_env;
            } else {
                parsedConfig.signatureSecretEnv = signatureSecretEnv.trim();
                delete parsedConfig.signature_secret_env;
                delete parsedConfig.webhookSignatureSecretEnv;
                delete parsedConfig.slackSigningSecretEnv;
                delete parsedConfig.slack_signing_secret_env;
                delete parsedConfig.viberAuthTokenEnv;
                delete parsedConfig.viber_auth_token_env;
                delete parsedConfig.authTokenEnv;
                delete parsedConfig.auth_token_env;
                delete parsedConfig.whatsappSigningSecretEnv;
                delete parsedConfig.whatsapp_signing_secret_env;
                delete parsedConfig.messengerSigningSecretEnv;
                delete parsedConfig.messenger_signing_secret_env;
                delete parsedConfig.appSecretEnv;
                delete parsedConfig.app_secret_env;
                delete parsedConfig.twilioSigningSecretEnv;
                delete parsedConfig.twilio_signing_secret_env;
                delete parsedConfig.smsSigningSecretEnv;
                delete parsedConfig.sms_signing_secret_env;
            }
        } else {
            delete parsedConfig.signatureSecretEnv;
            delete parsedConfig.signature_secret_env;
            delete parsedConfig.webhookSignatureSecretEnv;
            delete parsedConfig.slackSigningSecretEnv;
            delete parsedConfig.slack_signing_secret_env;
            delete parsedConfig.viberAuthTokenEnv;
            delete parsedConfig.viber_auth_token_env;
            delete parsedConfig.authTokenEnv;
            delete parsedConfig.auth_token_env;
            delete parsedConfig.whatsappSigningSecretEnv;
            delete parsedConfig.whatsapp_signing_secret_env;
            delete parsedConfig.messengerSigningSecretEnv;
            delete parsedConfig.messenger_signing_secret_env;
            delete parsedConfig.appSecretEnv;
            delete parsedConfig.app_secret_env;
            delete parsedConfig.twilioSigningSecretEnv;
            delete parsedConfig.twilio_signing_secret_env;
            delete parsedConfig.smsSigningSecretEnv;
            delete parsedConfig.sms_signing_secret_env;
            delete parsedConfig.instagramSigningSecretEnv;
            delete parsedConfig.instagram_signing_secret_env;
            delete parsedConfig.twitterConsumerSecretEnv;
            delete parsedConfig.twitter_consumer_secret_env;
            delete parsedConfig.xConsumerSecretEnv;
            delete parsedConfig.x_consumer_secret_env;
            delete parsedConfig.consumerSecretEnv;
            delete parsedConfig.consumer_secret_env;
        }
        if (type !== 'instagram') {
            delete parsedConfig.instagramSigningSecretEnv;
            delete parsedConfig.instagram_signing_secret_env;
        }
        if (type !== 'twitter') {
            delete parsedConfig.twitterConsumerSecretEnv;
            delete parsedConfig.twitter_consumer_secret_env;
            delete parsedConfig.xConsumerSecretEnv;
            delete parsedConfig.x_consumer_secret_env;
            delete parsedConfig.consumerSecretEnv;
            delete parsedConfig.consumer_secret_env;
        }
        if (signatureHeader.trim() && type !== 'slack') {
            parsedConfig.signatureHeader = signatureHeader.trim();
        } else {
            delete parsedConfig.signatureHeader;
            delete parsedConfig.signature_header;
        }
        if (outboundTransport) {
            parsedConfig.outboundTransport = outboundTransportConfigValue(outboundTransport, type);
        } else {
            delete parsedConfig.outboundTransport;
            delete parsedConfig.outbound_transport;
            delete parsedConfig.transport;
        }
        if (outboundTransport === 'bot') {
            delete parsedConfig.outboundWebhookUrl;
            delete parsedConfig.outbound_webhook_url;
            delete parsedConfig.outboundWebhookUrlEnv;
            delete parsedConfig.outbound_webhook_url_env;
            delete parsedConfig.outboundWebhookTokenEnv;
            delete parsedConfig.outbound_webhook_token_env;
            if (type === 'slack') {
                parsedConfig.slackBotTokenEnv = outboundBotTokenEnv.trim() || defaultBotTokenEnv(type);
                delete parsedConfig.botTokenEnv;
                delete parsedConfig.bot_token_env;
            } else if (type === 'discord') {
                parsedConfig.discordBotTokenEnv = outboundBotTokenEnv.trim() || defaultBotTokenEnv(type);
                delete parsedConfig.botTokenEnv;
                delete parsedConfig.bot_token_env;
            } else if (type === 'telegram') {
                parsedConfig.botTokenEnv = outboundBotTokenEnv.trim() || defaultBotTokenEnv(type);
                delete parsedConfig.telegramBotTokenEnv;
                delete parsedConfig.telegram_bot_token_env;
            } else {
                delete parsedConfig.slackBotTokenEnv;
                delete parsedConfig.slack_bot_token_env;
                delete parsedConfig.discordBotTokenEnv;
                delete parsedConfig.discord_bot_token_env;
                delete parsedConfig.telegramBotTokenEnv;
                delete parsedConfig.telegram_bot_token_env;
                delete parsedConfig.botTokenEnv;
                delete parsedConfig.bot_token_env;
            }
            if (type === 'teams') {
                parsedConfig.teamsAppIdEnv = teamsAppIdEnv.trim() || defaultTeamsAppIdEnv();
                parsedConfig.teamsAppPasswordEnv = teamsAppPasswordEnv.trim() || defaultTeamsAppPasswordEnv();
            } else {
                delete parsedConfig.teamsAppIdEnv;
                delete parsedConfig.teams_app_id_env;
                delete parsedConfig.teamsAppPasswordEnv;
                delete parsedConfig.teams_app_password_env;
            }
        } else {
            delete parsedConfig.slackBotTokenEnv;
            delete parsedConfig.slack_bot_token_env;
            delete parsedConfig.discordBotTokenEnv;
            delete parsedConfig.discord_bot_token_env;
            delete parsedConfig.telegramBotTokenEnv;
            delete parsedConfig.telegram_bot_token_env;
            delete parsedConfig.botTokenEnv;
            delete parsedConfig.bot_token_env;
            delete parsedConfig.teamsAppIdEnv;
            delete parsedConfig.teams_app_id_env;
            delete parsedConfig.teamsAppPasswordEnv;
            delete parsedConfig.teams_app_password_env;
        }
        if (usesWebhookOutbound(outboundTransport) && outboundWebhookUrl.trim()) {
            parsedConfig.outboundWebhookUrl = outboundWebhookUrl.trim();
        } else {
            delete parsedConfig.outboundWebhookUrl;
            delete parsedConfig.outbound_webhook_url;
        }
        if (usesWebhookOutbound(outboundTransport) && outboundWebhookUrlEnv.trim()) {
            parsedConfig.outboundWebhookUrlEnv = outboundWebhookUrlEnv.trim();
        } else {
            delete parsedConfig.outboundWebhookUrlEnv;
            delete parsedConfig.outbound_webhook_url_env;
        }
        if (usesOutboundTokenEnv(outboundTransport, type) && outboundWebhookTokenEnv.trim()) {
            parsedConfig.outboundWebhookTokenEnv = outboundWebhookTokenEnv.trim();
        } else {
            delete parsedConfig.outboundWebhookTokenEnv;
            delete parsedConfig.outbound_webhook_token_env;
        }
        if (usesLiveProofPrimaryTarget(type) && smokeTargetChannelId.trim()) {
            if (type === 'telegram') {
                parsedConfig.smokeChatId = smokeTargetChannelId.trim();
                delete parsedConfig.smoke_chat_id;
                delete parsedConfig.smokeChannelId;
                delete parsedConfig.smoke_channel_id;
            } else {
                parsedConfig.smokeChannelId = smokeTargetChannelId.trim();
                delete parsedConfig.smoke_channel_id;
                delete parsedConfig.smokeChatId;
                delete parsedConfig.smoke_chat_id;
            }
        } else {
            delete parsedConfig.smokeChannelId;
            delete parsedConfig.smoke_channel_id;
            delete parsedConfig.smokeChatId;
            delete parsedConfig.smoke_chat_id;
        }
        if (usesLiveProofThreadTarget(type) && smokeTargetThreadId.trim()) {
            if (type === 'slack') {
                parsedConfig.smokeThreadTs = smokeTargetThreadId.trim();
                delete parsedConfig.smoke_thread_ts;
                delete parsedConfig.smokeThreadId;
                delete parsedConfig.smoke_thread_id;
            } else {
                parsedConfig.smokeThreadId = smokeTargetThreadId.trim();
                delete parsedConfig.smoke_thread_id;
                delete parsedConfig.smokeThreadTs;
                delete parsedConfig.smoke_thread_ts;
            }
        } else {
            delete parsedConfig.smokeThreadId;
            delete parsedConfig.smoke_thread_id;
            delete parsedConfig.smokeThreadTs;
            delete parsedConfig.smoke_thread_ts;
        }
        if (smokeTargetProviderMessageId.trim()) {
            parsedConfig.smokeProviderMessageId = smokeTargetProviderMessageId.trim();
            delete parsedConfig.smoke_provider_message_id;
            delete parsedConfig.smokeMessageId;
            delete parsedConfig.smoke_message_id;
        } else {
            delete parsedConfig.smokeProviderMessageId;
            delete parsedConfig.smoke_provider_message_id;
            delete parsedConfig.smokeMessageId;
            delete parsedConfig.smoke_message_id;
        }
        if (smokeTargetToAddress.trim()) {
            parsedConfig.smokeToAddress = smokeTargetToAddress.trim();
            delete parsedConfig.smoke_to_address;
        } else {
            delete parsedConfig.smokeToAddress;
            delete parsedConfig.smoke_to_address;
        }
        if (smokeTargetConversationId.trim()) {
            parsedConfig.smokeConversationId = smokeTargetConversationId.trim();
            delete parsedConfig.smoke_conversation_id;
        } else {
            delete parsedConfig.smokeConversationId;
            delete parsedConfig.smoke_conversation_id;
        }
        if (smokeTargetReplyToId.trim()) {
            parsedConfig.smokeReplyToId = smokeTargetReplyToId.trim();
            delete parsedConfig.smoke_reply_to_id;
        } else {
            delete parsedConfig.smokeReplyToId;
            delete parsedConfig.smoke_reply_to_id;
        }
        if (smokeTargetServiceUrl.trim()) {
            parsedConfig.smokeServiceUrl = smokeTargetServiceUrl.trim();
            delete parsedConfig.smoke_service_url;
        } else {
            delete parsedConfig.smokeServiceUrl;
            delete parsedConfig.smoke_service_url;
        }
        setSaving(true);
        const res = await api.saveChannel(projectId, {
            type,
            name,
            status: nextStatus,
            channelKey,
            config: parsedConfig,
        });
        setSaving(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not save channel'));
            return;
        }
        setStatus(nextStatus);
        setTicketCreationMode(nextTicketCreationMode);
        setAutoPrepareTriage(nextAutoPrepareTriage);
        setAutoPrepareCustomFields(nextAutoPrepareCustomFields);
        setAutoPrepareAgentReply(nextAutoPrepareAgentReply);
        setAutoPrepareAgentReplyOnUpdate(nextAutoPrepareAgentReplyOnUpdate);
        setAgentAutoSend(nextAgentAutoSend);
        setDefaultAssigneeEmail(nextDefaultAssigneeEmail);
        setDefaultQueueKey(nextDefaultQueueKey);
        setDefaultQueueName(nextDefaultQueueName);
        setConfigJson(JSON.stringify(parsedConfig, null, 2));
        toast.success(successMessage);
        selectChannel(res.data.channelKey);
        setSetupValidation(null);
        setSmokeResult(null);
        setOutboundSmokeResult(null);
        setLifecycleSmokeResult(null);
        loadChannels();
    };

    const saveChannel = async () => {
        await saveChannelWithOverrides();
    };

    const saveQueue = async (statusOverride?: string) => {
        const nextName = queueName.trim();
        const nextKey = queueKey.trim() || selectedQueue?.queueKey || nextName;
        if (!nextName || !nextKey) {
            toast.error(t('Queue name is required'));
            return;
        }
        const allowedAssigneeEmails = emailListFrom(queueOwnerEmailsDraft);
        const defaultAssignee = queueDefaultAssigneeEmail.trim().toLowerCase();
        if (allowedAssigneeEmails.length > 0 && defaultAssignee && !allowedAssigneeEmails.includes(defaultAssignee)) {
            toast.error(t('Default assignee must be a queue owner'));
            return;
        }
        if (queueRoutingMode === 'least_open' && allowedAssigneeEmails.length === 0) {
            toast.error(t('Queue owners are required for least-open assignment'));
            return;
        }
        const ownerCapacity = queueOwnerCapacityDraft.trim()
            ? Number.parseInt(queueOwnerCapacityDraft.trim(), 10)
            : 0;
        if (queueOwnerCapacityDraft.trim() && (!Number.isFinite(ownerCapacity) || ownerCapacity < 1)) {
            toast.error(t('Owner capacity must be at least 1'));
            return;
        }
        const metadata = { ...(selectedQueue?.metadata ?? {}) };
        delete metadata.allowedAssigneeEmails;
        delete metadata.allowed_assignee_emails;
        delete metadata.assigneeEmails;
        delete metadata.assignee_emails;
        delete metadata.ownerEmails;
        delete metadata.owner_emails;
        delete metadata.owners;
        delete metadata.assignmentMode;
        delete metadata.assignment_mode;
        delete metadata.routingMode;
        delete metadata.routing_mode;
        delete metadata.ownerCapacity;
        delete metadata.owner_capacity;
        delete metadata.maxOpenTicketsPerOwner;
        delete metadata.max_open_tickets_per_owner;
        delete metadata.maxActiveTicketsPerOwner;
        delete metadata.max_active_tickets_per_owner;
        delete metadata.maxActiveTickets;
        delete metadata.max_active_tickets;
        delete metadata.capacity;
        metadata.allowedAssigneeEmails = allowedAssigneeEmails;
        metadata.assignmentMode = queueRoutingMode;
        if (ownerCapacity > 0) metadata.ownerCapacity = ownerCapacity;
        setSavingQueue(true);
        const res = await api.saveSupportQueue(projectId, {
            queueKey: nextKey,
            name: nextName,
            description: queueDescription.trim(),
            defaultAssigneeEmail: defaultAssignee,
            status: statusOverride || queueStatus,
            metadata,
        });
        setSavingQueue(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not save queue'));
            return;
        }
        toast.success(statusOverride === 'archived' ? t('Queue archived') : t('Saved'));
        setSelectedQueueKey(res.data.queueKey);
        loadQueues();
    };

    const saveCrmConnector = async () => {
        let parsedConfig: Record<string, unknown>;
        try {
            parsedConfig = JSON.parse(crmConfigJson) as Record<string, unknown>;
        } catch {
            toast.error(t('Invalid JSON'));
            return;
        }
        setSavingCrm(true);
        const res = await api.saveCrmConnector(projectId, {
            provider: crmProvider,
            name: crmName,
            status: crmStatus,
            connectorKey: crmConnectorKey,
            config: parsedConfig,
        });
        setSavingCrm(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not save CRM connector'));
            return;
        }
        toast.success(t('Saved'));
        setCrmValidation(null);
        setSelectedCrmKey(res.data.connectorKey);
        loadCrmConnectors();
    };

    const runDelivery = async (retryFailed = false) => {
        setDeliveryRunMode(retryFailed ? 'failed' : 'queued');
        const res = await api.runSupportDelivery(projectId, 25, retryFailed);
        setDeliveryRunMode('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not run delivery'));
            return;
        }
        const label = retryFailed ? t('Failed delivery retry') : t('Delivery run');
        const blocked = res.data.blocked ?? 0;
        const message = label + `: ${res.data.sent} ${t('sent')}, ${res.data.failed} ${t('failed')}, ${res.data.deferred ?? 0} ${t('deferred')}, ${blocked} ${t('blocked')}`;
        if (res.data.error || res.data.failed > 0 || blocked > 0) {
            toast.error(res.data.error ? `${message} - ${res.data.error}` : message);
        } else {
            toast.success(message);
        }
        loadDeliveryRuns();
        loadChannels();
    };

    const syncAll = async () => {
        setSyncingChannel('all');
        const res = await api.syncChannels(projectId);
        setSyncingChannel('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not sync channels'));
            return;
        }
        toast.success(t('Sync run') + `: ${res.data.processed} ${t('processed')}, ${res.data.failed} ${t('failed')}`);
        loadChannels();
        loadSyncRuns(selectedChannel?.id ?? '');
        loadChannelCursors(selectedChannel?.id ?? '');
        loadChannelWebhookEvents(selectedChannel?.id ?? '');
        loadWebChatSessions(selectedChannel?.id ?? '');
    };

    const syncSelected = async () => {
        if (!selectedChannel) return;
        setSyncingChannel(selectedChannel.id);
        const res = await api.syncChannel(projectId, selectedChannel.id);
        setSyncingChannel('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not sync channel'));
            return;
        }
        toast.success(t('Sync run') + `: ${res.data.processed} ${t('processed')}, ${res.data.failed} ${t('failed')}`);
        loadChannels();
        loadSyncRuns(selectedChannel.id);
        loadChannelCursors(selectedChannel.id);
        loadChannelWebhookEvents(selectedChannel.id);
        loadWebChatSessions(selectedChannel.id);
    };

    const validateSelectedChannel = async () => {
        if (!selectedChannel) return;
        setValidatingSetup(selectedChannel.id);
        const res = await api.validateChannelSetup(projectId, selectedChannel.id);
        setValidatingSetup('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not validate setup'));
            return;
        }
        setSetupValidation(res.data);
        toast.success(res.data.ready ? t('Setup ready') : t('Setup needs work'));
        loadSyncRuns(selectedChannel.id);
        loadChannelCursors(selectedChannel.id);
        loadChannels();
    };

    const installSlack = async () => {
        const nextKey = channelKey.trim() || selectedChannel?.channelKey || 'slack-main';
        const nextName = name.trim() || selectedChannel?.name || 'Slack';
        setInstallingSlack(true);
        const res = await api.createSlackInstallUrl(projectId, {
            channelKey: nextKey,
            name: nextName,
        });
        setInstallingSlack(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not start Slack install'));
            return;
        }
        window.location.assign(res.data.installUrl);
    };

    const setTelegramWebhook = async () => {
        if (!selectedChannel) return;
        setSettingTelegramWebhook(true);
        const res = await api.configureTelegramWebhook(projectId, selectedChannel.id);
        setSettingTelegramWebhook(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not set Telegram webhook'));
            return;
        }
        toast.success(t('Telegram webhook set'));
        setSetupValidation(null);
        loadChannels();
    };

    const runTestMessage = async () => {
        if (!selectedChannel || !testMessageBody.trim()) return;
        setTestingChannel(selectedChannel.id);
        const channelTarget = testChannelId.trim() || smokeTargetChannelId.trim();
        const threadTarget = testThreadId.trim() || smokeTargetThreadId.trim();
        const messageTarget = testProviderMessageId.trim() || smokeTargetProviderMessageId.trim();
        const res = await api.testChannelMessage(projectId, selectedChannel.id, {
            body: testMessageBody.trim(),
            authorName: testAuthorName.trim() || undefined,
            authorEmail: testAuthorEmail.trim() || undefined,
            channelId: channelTarget || undefined,
            threadId: threadTarget || undefined,
            messageId: messageTarget || undefined,
        });
        setTestingChannel('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not create test message'));
            return;
        }
        setTestMessageResult(res.data);
        toast.success(t('Test message processed') + `: ${res.data.processed} ${t('processed')}`);
        loadChannelCursors(selectedChannel.id);
        loadChannelWebhookEvents(selectedChannel.id);
        loadChannels();
    };

    const runSmoke = async (transport: 'direct' | 'http' = 'http') => {
        if (!selectedChannel || !testMessageBody.trim()) return;
        setSmokingChannel(`${selectedChannel.id}:${transport}`);
        const channelTarget = testChannelId.trim() || smokeTargetChannelId.trim();
        const threadTarget = testThreadId.trim() || smokeTargetThreadId.trim();
        const messageTarget = testProviderMessageId.trim() || smokeTargetProviderMessageId.trim();
        const res = await api.smokeChannel(projectId, selectedChannel.id, {
            body: testMessageBody.trim(),
            authorName: testAuthorName.trim() || undefined,
            authorEmail: testAuthorEmail.trim() || undefined,
            channelId: channelTarget || undefined,
            threadId: threadTarget || undefined,
            messageId: messageTarget || undefined,
            transport,
        });
        setSmokingChannel('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not run provider smoke'));
            return;
        }
        setSmokeResult(res.data);
        setSetupValidation(res.data.validation);
        toast.success(t('Provider smoke') + `: ${res.data.processed} ${t('processed')}`);
        loadSyncRuns(selectedChannel.id);
        loadChannelCursors(selectedChannel.id);
        loadChannelWebhookEvents(selectedChannel.id);
        loadChannels();
    };

    const runOutboundSmoke = async () => {
        if (!selectedChannel || !outboundSmokeBody.trim()) return;
        setSmokingOutboundChannel(selectedChannel.id);
        const channelTarget = testChannelId.trim() || smokeTargetChannelId.trim();
        const threadTarget = testThreadId.trim() || smokeTargetThreadId.trim();
        const messageTarget = testProviderMessageId.trim() || smokeTargetProviderMessageId.trim();
        const res = await api.smokeChannelOutbound(projectId, selectedChannel.id, {
            body: outboundSmokeBody.trim(),
            channelId: channelTarget || undefined,
            threadId: threadTarget || undefined,
            providerMessageId: messageTarget || undefined,
            toAddress: smokeTargetToAddress.trim() || channelTarget || undefined,
            conversationId: smokeTargetConversationId.trim() || undefined,
            replyToId: smokeTargetReplyToId.trim() || undefined,
            serviceUrl: smokeTargetServiceUrl.trim() || undefined,
            subject: 'Support reply smoke',
        });
        setSmokingOutboundChannel('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not send outbound smoke'));
            return;
        }
        setOutboundSmokeResult(res.data);
        setSetupValidation(res.data.validation);
        if (res.data.failed) {
            toast.error(t('Outbound smoke') + `: ${res.data.error || res.data.status}`);
        } else if (res.data.deferred) {
            toast.error(t('Outbound smoke deferred'));
        } else {
            toast.success(t('Outbound smoke sent'));
        }
        loadSyncRuns(selectedChannel.id);
        loadChannelCursors(selectedChannel.id);
        loadDeliveryRuns();
        loadChannels();
    };

    const runLifecycleSmoke = async (options?: { attachmentOnly?: boolean }) => {
        const attachmentOnly = options?.attachmentOnly ?? lifecycleAttachmentOnly;
        if (!selectedChannel || (!testMessageBody.trim() && !attachmentOnly) || !outboundSmokeBody.trim()) return;
        setSmokingLifecycleChannel(selectedChannel.id);
        const attachments = attachmentOnly
            ? [{
                filename: 'admin-lifecycle-smoke.txt',
                contentType: 'text/plain',
                size: 42,
            }]
            : undefined;
        const channelTarget = testChannelId.trim() || smokeTargetChannelId.trim();
        const threadTarget = testThreadId.trim() || smokeTargetThreadId.trim();
        const messageTarget = testProviderMessageId.trim() || smokeTargetProviderMessageId.trim();
        const res = await api.smokeChannelLifecycle(projectId, selectedChannel.id, {
            body: attachmentOnly ? '' : testMessageBody.trim(),
            replyBody: outboundSmokeBody.trim(),
            authorName: testAuthorName.trim() || undefined,
            authorEmail: testAuthorEmail.trim() || undefined,
            channelId: channelTarget || undefined,
            threadId: threadTarget || undefined,
            messageId: messageTarget || undefined,
            attachments,
            transport: 'http',
        });
        setSmokingLifecycleChannel('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not run lifecycle smoke'));
            return;
        }
        setLifecycleSmokeResult(res.data);
        setSetupValidation(res.data.validation);
        if (res.data.failed) {
            toast.error(t('Lifecycle smoke') + `: ${res.data.error || res.data.status}`);
        } else if (res.data.deferred) {
            toast.error(t('Lifecycle smoke deferred'));
        } else {
            toast.success(t('Lifecycle smoke sent'));
        }
        loadSyncRuns(selectedChannel.id);
        loadChannelCursors(selectedChannel.id);
        loadChannelWebhookEvents(selectedChannel.id);
        loadDeliveryRuns();
        loadChannels();
    };

    const canRunLaunchProof = (action: string) => {
        if (!selectedChannel) return false;
        if (action === 'support_mode') return !saving && !selectedSupportModeReady;
        if (action === 'ticket_mode') return !saving && ticketCreationMode !== 'per_message';
        if (action === 'auto_prepare') {
            return !saving && (!autoPrepareTriage || !autoPrepareCustomFields || !autoPrepareAgentReply || !autoPrepareAgentReplyOnUpdate || agentAutoSend);
        }
        if (action === 'owner_routing') return !saving && (routingPreview.ready || Boolean(currentUserEmail.trim()));
        if (action === 'activate_channel') return !saving && status !== 'active' && (routingPreview.ready || Boolean(currentUserEmail.trim()));
        if (action === 'provider_validation') return !validatingSetup;
        if (action === 'channel_autopilot') return Boolean(testMessageBody.trim());
        if (action === 'email_sync') return !syncingChannel;
        if (action === 'email_delivery' || action === 'web_chat_delivery') return !deliveryRunMode;
        if (action === 'web_chat_session') return Boolean(selectedChannel.setup?.webChatUrl);
        if (action === 'inbound_smoke') return Boolean(testMessageBody.trim());
        if (action === 'outbound_smoke') {
            return Boolean(outboundSmokeBody.trim()) && selectedChannelSupportsOutboundSmoke;
        }
        if (action === 'lifecycle_smoke') {
            return Boolean(testMessageBody.trim() && outboundSmokeBody.trim()) && selectedChannelSupportsOutboundSmoke;
        }
        if (action === 'attachment_lifecycle_smoke') {
            return Boolean(outboundSmokeBody.trim()) && selectedChannelSupportsOutboundSmoke;
        }
        return false;
    };

    const launchProofRunning = (action: string) => {
        if (!selectedChannel) return false;
        if (isLaunchConfigFix(action) || action === 'activate_channel') return saving;
        if (action === 'provider_validation') return validatingSetup === selectedChannel.id;
        if (action === 'email_sync') return syncingChannel === selectedChannel.id;
        if (action === 'email_delivery' || action === 'web_chat_delivery') return deliveryRunMode === 'queued';
        if (action === 'channel_autopilot') return smokingChannel === `${selectedChannel.id}:http`;
        if (action === 'inbound_smoke') return smokingChannel === `${selectedChannel.id}:http`;
        if (action === 'outbound_smoke') return smokingOutboundChannel === selectedChannel.id;
        if (action === 'lifecycle_smoke' || action === 'attachment_lifecycle_smoke') return smokingLifecycleChannel === selectedChannel.id;
        return false;
    };

    const runLaunchProof = async (action: string) => {
        if (action === 'support_mode') {
            await saveChannelWithOverrides(
                supportModeChannelOverrides,
                t('Support mode enabled'),
            );
            return;
        }
        if (action === 'ticket_mode') {
            await saveChannelWithOverrides(
                { ticketCreationMode: 'per_message' },
                t('Ticket mode fixed'),
            );
            return;
        }
        if (action === 'auto_prepare') {
            await saveChannelWithOverrides(
                supportModeChannelOverrides,
                t('AI prep enabled'),
            );
            return;
        }
        if (action === 'owner_routing') {
            const ownerEmail = defaultAssigneeEmail.trim() || (routingPreview.ready ? '' : currentUserEmail.trim());
            await saveChannelWithOverrides(
                {
                    defaultAssigneeEmail: ownerEmail,
                    defaultQueueKey: defaultQueueKey.trim(),
                    defaultQueueName: defaultQueueName.trim() || selectedDefaultQueue?.name || '',
                },
                t('Default owner saved'),
            );
            return;
        }
        if (action === 'activate_channel') {
            await saveChannelWithOverrides(
                { status: 'active' },
                t('Channel activated'),
            );
            return;
        }
        if (action === 'provider_validation') {
            await validateSelectedChannel();
            return;
        }
        if (action === 'channel_autopilot') {
            await runSmoke('http');
            return;
        }
        if (action === 'email_sync') {
            await syncSelected();
            return;
        }
        if (action === 'email_delivery' || action === 'web_chat_delivery') {
            await runDelivery();
            return;
        }
        if (action === 'web_chat_session') {
            const url = selectedChannel?.setup?.webChatUrl;
            if (url) window.open(url, '_blank', 'noopener,noreferrer');
            return;
        }
        if (action === 'inbound_smoke') {
            await runSmoke('http');
            return;
        }
        if (action === 'outbound_smoke') {
            await runOutboundSmoke();
            return;
        }
        if (action === 'lifecycle_smoke') {
            await runLifecycleSmoke();
            return;
        }
        if (action === 'attachment_lifecycle_smoke') {
            await runLifecycleSmoke({ attachmentOnly: true });
        }
    };

    const runSmokeAll = async () => {
        if (!testMessageBody.trim()) return;
        setSmokingAllChannels(true);
        const res = await api.smokeChannels(projectId, {
            body: testMessageBody.trim(),
            authorName: testAuthorName.trim() || undefined,
            authorEmail: testAuthorEmail.trim() || undefined,
            transport: smokeAllTransport,
        });
        setSmokingAllChannels(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not run channel smoke'));
            return;
        }
        setSmokeRun(res.data);
        if (res.data.failed > 0) {
            toast.error(t('Channel smoke') + `: ${res.data.failed} ${t('failed')}`);
        } else {
            toast.success(t('Channel smoke') + `: ${res.data.processed} ${t('processed')}`);
        }
        loadSyncRuns(selectedChannel?.id ?? '');
        loadChannelCursors(selectedChannel?.id ?? '');
        loadChannelWebhookEvents(selectedChannel?.id ?? '');
        loadChannels();
    };

    const runOutboundSmokeAll = async () => {
        if (!outboundSmokeBody.trim()) return;
        setSmokingOutboundAllChannels(true);
        const res = await api.smokeChannelsOutbound(projectId, {
            body: outboundSmokeBody.trim(),
            channelId: testChannelId.trim() || undefined,
            threadId: testThreadId.trim() || undefined,
            providerMessageId: testProviderMessageId.trim() || undefined,
            toAddress: testChannelId.trim() || undefined,
            subject: 'Support reply smoke',
        });
        setSmokingOutboundAllChannels(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not send outbound smoke'));
            return;
        }
        setOutboundSmokeRun(res.data);
        if (res.data.failed > 0) {
            toast.error(t('Outbound smoke') + `: ${res.data.failed} ${t('failed')}`);
        } else if (res.data.deferred > 0) {
            toast.error(t('Outbound smoke deferred'));
        } else {
            toast.success(t('Outbound smoke') + `: ${res.data.sent} ${t('sent')}`);
        }
        loadSyncRuns(selectedChannel?.id ?? '');
        loadChannelCursors(selectedChannel?.id ?? '');
        loadDeliveryRuns();
        loadChannels();
    };

    const runLifecycleSmokeAll = async (options?: { attachmentOnly?: boolean }) => {
        const attachmentOnly = options?.attachmentOnly ?? false;
        if ((!testMessageBody.trim() && !attachmentOnly) || !outboundSmokeBody.trim()) return;
        const attachments = attachmentOnly
            ? [{
                filename: 'admin-lifecycle-smoke.txt',
                contentType: 'text/plain',
                size: 42,
            }]
            : undefined;
        setSmokingLifecycleAllChannels(true);
        const res = await api.smokeChannelsLifecycle(projectId, {
            body: attachmentOnly ? '' : testMessageBody.trim(),
            replyBody: outboundSmokeBody.trim(),
            authorName: testAuthorName.trim() || undefined,
            authorEmail: testAuthorEmail.trim() || undefined,
            channelId: testChannelId.trim() || undefined,
            threadId: testThreadId.trim() || undefined,
            messageId: testProviderMessageId.trim() || undefined,
            attachments,
            transport: smokeAllTransport,
        });
        setSmokingLifecycleAllChannels(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not run lifecycle smoke'));
            return;
        }
        setLifecycleSmokeRun(res.data);
        if (res.data.failed > 0) {
            toast.error(t('Lifecycle smoke') + `: ${res.data.failed} ${t('failed')}`);
        } else if (res.data.deferred > 0) {
            toast.error(t('Lifecycle smoke deferred'));
        } else {
            toast.success(t('Lifecycle smoke') + `: ${res.data.sent} ${t('sent')}`);
        }
        loadSyncRuns(selectedChannel?.id ?? '');
        loadChannelCursors(selectedChannel?.id ?? '');
        loadChannelWebhookEvents(selectedChannel?.id ?? '');
        loadDeliveryRuns();
        loadChannels();
    };

    const retryWebhookMatch = async (event: SupportChannelWebhookEvent) => {
        setRematchingWebhookEvent(event.id);
        const res = await api.rematchChannelWebhookEvent(projectId, event.id);
        setRematchingWebhookEvent('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not retry webhook match'));
            return;
        }
        const updatedEvent = res.data;
        setChannelWebhookEvents(items => items.map(item => item.id === event.id ? updatedEvent : item));
        if (updatedEvent.status === 'processed') {
            toast.success(t('Receipt matched'));
        } else {
            toast.error(t('Still unmatched'));
        }
    };

    const syncAllCrm = async () => {
        setSyncingCrm('all');
        const res = await api.syncCrmConnectors(projectId);
        setSyncingCrm('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not sync CRM connectors'));
            return;
        }
        toast.success(t('CRM sync run') + `: ${res.data.processed} ${t('processed')}, ${res.data.failed} ${t('failed')}`);
        loadCrmConnectors();
        loadCrmSyncRuns(selectedCrmConnector?.id ?? '');
        loadCrmWebhookEvents(selectedCrmConnector?.id ?? '');
    };

    const syncSelectedCrm = async () => {
        if (!selectedCrmConnector) return;
        setSyncingCrm(selectedCrmConnector.id);
        const res = await api.syncCrmConnector(projectId, selectedCrmConnector.id);
        setSyncingCrm('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not sync CRM connector'));
            return;
        }
        toast.success(t('CRM sync run') + `: ${res.data.processed} ${t('processed')}, ${res.data.failed} ${t('failed')}`);
        loadCrmConnectors();
        loadCrmSyncRuns(selectedCrmConnector.id);
        loadCrmWebhookEvents(selectedCrmConnector.id);
    };

    const validateSelectedCrm = async () => {
        if (!selectedCrmConnector) return;
        setValidatingCrm(selectedCrmConnector.id);
        const res = await api.validateCrmConnector(projectId, selectedCrmConnector.id);
        setValidatingCrm('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not validate CRM connector'));
            return;
        }
        setCrmValidation(res.data);
        if (res.data.ready) {
            toast.success(t('CRM connector ready'));
        } else {
            toast.error(res.data.error || t('CRM connector needs setup'));
        }
    };

    const copyValue = async (value: string) => {
        if (!value) return;
        try {
            await navigator.clipboard.writeText(value);
            toast.success(t('Copied'));
        } catch {
            toast.error(t('Could not copy'));
        }
    };

    const copyLaunchProofBundle = async () => {
        if (!selectedChannel) return;
        const setup = selectedChannel.setup;
        if (!setup) return;
        const bundle = {
            generatedAt: new Date().toISOString(),
            projectId,
            channel: {
                id: selectedChannel.id,
                key: selectedChannel.channelKey,
                name: selectedChannel.name,
                type: selectedChannel.type,
                status: selectedChannel.status,
            },
            launch: setup.launch ?? null,
            liveTargets: liveProofTargetRows.map(row => ({
                key: row.key,
                label: row.label,
                configKey: row.configKey,
                required: row.required,
                configured: row.configured,
                value: row.value,
            })),
            evidence: liveProofEvidence.map(row => ({
                key: row.key,
                label: row.label,
                status: row.status,
                detail: row.detail,
                runId: row.runId,
                source: row.source,
                runStatus: row.runStatus,
                transport: row.transport,
                issueId: row.issueId,
                replyId: row.replyId,
                providerMessageId: row.providerMessageId,
                startedAt: row.startedAt,
                completedAt: row.completedAt,
            })),
            blockers: setup.launch?.blockers ?? [],
            checklist: setup.launchChecklist ?? setup.launch?.checklist ?? [],
            playbook: setup.launchPlaybook ?? [],
            commands: (setup.launchPlaybook ?? [])
                .filter(step => Boolean(step.smokeCommand))
                .map(step => ({
                    key: step.key,
                    label: step.label,
                    command: step.smokeCommand,
                })),
            setup: {
                inboundWebhookUrl: setup.inboundWebhookUrl,
                providerWebhookUrl: setup.providerWebhookUrl,
                webChatUrl: setup.webChatUrl,
                outboundTransport: setup.outboundTransport,
                outboundPayloadMode: outboundPayloadModeFromConfig(selectedChannel.config),
                inboundReady: setup.inboundReady,
                outboundReady: setup.outboundReady,
                autoPrepareTriage: setup.autoPrepareTriage,
                autoPrepareCustomFields: setup.autoPrepareCustomFields,
                autoPrepareAgentReply: setup.autoPrepareAgentReply,
                autoPrepareAgentReplyOnUpdate: setup.autoPrepareAgentReplyOnUpdate,
                agentAutoSend: setup.agentAutoSend,
                authConfigured: setup.authConfigured,
                health: setup.health,
            },
        };
        await copyValue(JSON.stringify(bundle, null, 2));
    };

    const copyButton = (value: string) => (
        <Button type="button" size="sm" variant="outline" onClick={() => void copyValue(value)}>
            <Copy className="size-3.5" />
            {t('Copy')}
        </Button>
    );

    const playbookActionLabel = (step: SupportChannelLaunchPlaybookStep) => {
        if (step.action === 'install_slack') return t('Install');
        if (step.action === 'set_telegram_webhook') return t('Set webhook');
        if (step.action === 'open_url') return t('Open');
        if (step.action === 'copy') return t('Copy');
        if (isLaunchConfigFix(step.runAction)) return t('Fix');
        if (step.runAction === 'provider_validation') return t('Validate');
        return t('Run');
    };

    const playbookActionIcon = (step: SupportChannelLaunchPlaybookStep) => {
        const running = step.action === 'install_slack'
            ? installingSlack
            : step.action === 'set_telegram_webhook'
                ? settingTelegramWebhook
                : step.runAction
                    ? launchProofRunning(step.runAction)
                    : false;
        if (running) return <Loader className="size-3.5 animate-spin" />;
        if (step.action === 'copy') return <Copy className="size-3.5" />;
        if (step.action === 'open_url' || step.action === 'install_slack') return <ExternalLink className="size-3.5" />;
        if (step.action === 'set_telegram_webhook') return <Send className="size-3.5" />;
        if (isLaunchConfigFix(step.runAction)) return <Save className="size-3.5" />;
        return <RefreshCw className="size-3.5" />;
    };

    const canRunPlaybookStep = (step: SupportChannelLaunchPlaybookStep) => {
        if (step.action === 'copy') return Boolean(step.copyValue);
        if (step.action === 'install_slack') return !installingSlack;
        if (step.action === 'set_telegram_webhook') return !settingTelegramWebhook;
        if (step.action === 'open_url') return Boolean(step.targetUrl);
        if (step.runAction) return canRunLaunchProof(step.runAction) && !launchProofRunning(step.runAction);
        return false;
    };

    const runPlaybookStep = async (step: SupportChannelLaunchPlaybookStep) => {
        if (step.action === 'copy') {
            await copyValue(step.copyValue);
            return;
        }
        if (step.action === 'install_slack') {
            await installSlack();
            return;
        }
        if (step.action === 'set_telegram_webhook') {
            await setTelegramWebhook();
            return;
        }
        if (step.action === 'open_url') {
            window.open(step.targetUrl, '_blank', 'noopener,noreferrer');
            return;
        }
        if (step.runAction) {
            await runLaunchProof(step.runAction);
        }
    };

    const remediationVariant = (severity: string): 'secondary' | 'destructive' | 'outline' => {
        if (severity === 'critical') return 'destructive';
        if (severity === 'info') return 'secondary';
        return 'outline';
    };

    const canRunRemediation = (step: SupportChannelRemediationStep) => {
        if (step.action === 'copy') return Boolean(step.copyValue);
        if (step.runAction) return canRunLaunchProof(step.runAction) && !launchProofRunning(step.runAction);
        return false;
    };

    const runRemediation = async (step: SupportChannelRemediationStep) => {
        if (step.action === 'copy') {
            await copyValue(step.copyValue);
            return;
        }
        if (step.runAction) {
            await runLaunchProof(step.runAction);
        }
    };

    const remediationButtonLabel = (step: SupportChannelRemediationStep) => {
        if (step.action === 'copy') return t('Copy');
        if (step.runAction === 'provider_validation') return t('Validate');
        if (isLaunchConfigFix(step.runAction)) return t('Fix');
        return t('Run');
    };

    const remediationButtonIcon = (step: SupportChannelRemediationStep) => {
        if (step.action === 'copy') return <Copy className="size-3.5" />;
        if (launchProofRunning(step.runAction)) return <Loader className="size-3.5 animate-spin" />;
        if (step.runAction === 'provider_validation') return <CheckCircle2 className="size-3.5" />;
        if (isLaunchConfigFix(step.runAction)) return <Save className="size-3.5" />;
        return <RefreshCw className="size-3.5" />;
    };

    const remediationList = (items: SupportChannelRemediationStep[] | undefined) => {
        const visible = items ?? [];
        if (visible.length === 0) return null;
        return (
            <div className="mt-3 rounded-md border bg-background p-2">
                <div className="mb-2 text-xs font-medium">{t('Remediation')}</div>
                <div className="space-y-1.5">
                    {visible.map(step => (
                        <div key={step.key} className="flex min-w-0 items-start gap-2 rounded-md border bg-muted/20 px-2 py-1.5 text-xs">
                            <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                            <div className="min-w-0 flex-1">
                                <div className="mb-0.5 flex min-w-0 items-center gap-2">
                                    <span className="truncate font-medium">{t(textValue(step.label, step.key))}</span>
                                    <Badge variant={remediationVariant(step.severity)} className="font-normal">
                                        {t(step.severity || 'warning')}
                                    </Badge>
                                </div>
                                <div className="line-clamp-2 text-muted-foreground">{t(textValue(step.detail))}</div>
                                {step.copyLabel && (
                                    <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
                                        {t(step.copyLabel)}: {step.copyValue || '-'}
                                    </div>
                                )}
                            </div>
                            {(step.action || step.runAction) && (
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    className="h-7 shrink-0 px-2"
                                    onClick={() => void runRemediation(step)}
                                    disabled={!canRunRemediation(step)}
                                >
                                    {remediationButtonIcon(step)}
                                    {remediationButtonLabel(step)}
                                </Button>
                            )}
                        </div>
                    ))}
                </div>
            </div>
        );
    };

    const openTicket = (issueId: string) => {
        if (!tenantId || !issueId) return;
        void navigate(`/${tenantId}/${projectId}/inbox/${issueId}`);
    };

    const channelSurfaceRows = useMemo<ChannelSurfaceRow[]>(() => channelSurfaceTargets.map(target => {
        const candidates = channels.filter(channel => normalizedChannelType(channel.type) === target.type);
        const channel = candidates.find(item => item.status === 'active') ?? candidates[0] ?? null;
        const preset = channelPresets.find(item => normalizedChannelType(item.type) === target.type);
        const ticketMode = channel
            ? (channel.setup?.ticketCreationMode || ticketCreationModeFromConfig(channel.config))
            : preset
                ? presetTicketCreationMode(preset.ticketCreationMode)
                : 'per_message';
        const inboundReady = channel ? channelSetupBool(channel, 'inboundReady') : false;
        const outboundReady = channel ? channelSetupBool(channel, 'outboundReady') : false;
        const autoTriage = channel
            ? boolFromConfig(channel.config, 'autoPrepareTriage', 'auto_prepare_triage', true)
            : boolFromConfig(preset?.config, 'autoPrepareTriage', 'auto_prepare_triage', true);
        const autoFields = channel
            ? boolFromConfig(channel.config, 'autoPrepareCustomFields', 'auto_prepare_custom_fields', true)
            : boolFromConfig(preset?.config, 'autoPrepareCustomFields', 'auto_prepare_custom_fields', true);
        const autoDraft = channel ? channelAutoDraftEnabled(channel) : preset?.autoPrepareAgentReply === true;
        const autoFollowUp = channel
            ? boolFromConfig(channel.config, 'autoPrepareAgentReplyOnUpdate', 'auto_prepare_agent_reply_on_update', false)
            : preset?.autoPrepareAgentReplyOnUpdate === true;
        const humanReview = !(channel
            ? boolFromConfig(channel.config, 'agentAutoSend', 'agent_auto_send', false)
            : preset?.agentAutoSend === true);
        const everyMessage = ticketMode === 'per_message';
        const ownerRouting = channel ? channelOwnerRoutingEnabled(channel, supportQueues) : false;
        const launchRequired = channel ? Boolean(channel.setup?.launch?.required ?? channelRequiresLaunchSmoke(channel.type)) : false;
        const launchReady = !launchRequired || channel?.setup?.launch?.ready === true;
        const launchBlockers = channel?.setup?.launch?.blockers ?? [];
        const launchBlockerDetail = launchBlockers
            .map(blocker => blocker.detail || blocker.label)
            .find(Boolean);
        const supportModeReady = everyMessage && autoTriage && autoFields && autoDraft && autoFollowUp && humanReview;
        const ready = Boolean(channel && channel.status === 'active' && inboundReady && outboundReady && supportModeReady && ownerRouting && launchReady);
        const blockers = [
            !channel ? t('Missing') : '',
            channel && channel.status !== 'active' ? t('Paused') : '',
            channel && !inboundReady ? t('No inbound') : '',
            channel && !outboundReady ? t('No outbound') : '',
            channel && !everyMessage ? t('Thread updates') : '',
            channel && !autoTriage ? t('Manual triage') : '',
            channel && !autoFields ? t('Manual fields') : '',
            channel && !autoDraft ? t('Manual prep') : '',
            channel && !autoFollowUp ? t('Manual follow-up') : '',
            channel && !humanReview ? t('No approval gate') : '',
            channel && !ownerRouting ? t('No default owner') : '',
            channel && !launchReady ? t(launchBlockerDetail || 'No launch smoke') : '',
        ].filter(Boolean);
        return {
            ...target,
            channel,
            ticketMode,
            inboundReady,
            outboundReady,
            autoTriage,
            autoFields,
            autoDraft,
            autoFollowUp,
            humanReview,
            everyMessage,
            ownerRouting,
            launchRequired,
            launchReady,
            launchBlockers,
            ready,
            blockers,
        };
    }), [channels, channelPresets, supportQueues, t]);

    const localChannelActivationBacklog = useMemo(
        () => buildChannelActivationBacklog(projectId, channelSurfaceRows, channelPresets),
        [channelPresets, channelSurfaceRows, projectId],
    );
    const channelActivationBacklog = serverChannelActivationBacklog ?? localChannelActivationBacklog;
    const channelActivationBacklogJson = useMemo(
        () => JSON.stringify(channelActivationBacklog, null, 2),
        [channelActivationBacklog],
    );
    const channelActivationBacklogHref = useMemo(
        () => `data:application/json;charset=utf-8,${encodeURIComponent(channelActivationBacklogJson)}`,
        [channelActivationBacklogJson],
    );
    const copyChannelActivationBacklog = async () => {
        await copyValue(channelActivationBacklogJson);
    };

    const channelActivationSummary = channelActivationBacklog.summary;
    const totalSurfaceCount = channelActivationSummary.totalSurfaces || channelSurfaceRows.length;
    const readySurfaceCount = channelActivationSummary.readySurfaces;
    const configuredSurfaceCount = channelActivationSummary.configuredSurfaces;
    const channelActivationNextActions = useMemo(
        () => [...(channelActivationBacklog.nextActions ?? [])],
        [channelActivationBacklog],
    );
    const channelActivationAdapterMatrix = useMemo(
        () => channelActivationBacklog.adapterMatrix?.length
            ? channelActivationBacklog.adapterMatrix
            : buildChannelActivationAdapterMatrix(channelActivationBacklog.surfaces, channelActivationNextActions),
        [channelActivationBacklog, channelActivationNextActions],
    );
    const channelActivationAdapterReadyCount = channelActivationAdapterMatrix.filter(row => row.ready).length;
    const channelActivationAdapterBlockedCount = channelActivationAdapterMatrix.length - channelActivationAdapterReadyCount;
    const channelActivationNextActionPhases = channelActivationSummary.nextActionPhases ?? {};
    const visibleChannelActivationNextActions = channelActivationNextActions.slice(0, 3);
    const visibleChannelActivationPhases = Object.entries(channelActivationNextActionPhases)
        .filter(([, count]) => count > 0)
        .slice(0, 4);
    const channelProviderLaunchRows = useMemo(() => channelSurfaceRows.map(row => {
        const action = channelActivationNextActions.find(item => normalizedChannelType(item.surfaceType) === row.type) ?? null;
        const matrix = channelActivationAdapterMatrix.find(item => normalizedChannelType(item.surfaceType) === row.type) ?? null;
        const readyChecks = [
            Boolean(row.channel),
            row.inboundReady,
            row.outboundReady,
            row.everyMessage,
            row.autoDraft,
            row.ownerRouting,
            row.humanReview,
            row.launchReady,
        ].filter(Boolean).length;
        const blockedChecks = Math.max(8 - readyChecks, 0);
        return {
            row,
            action,
            matrix,
            readyChecks,
            blockedChecks,
            phase: row.ready ? 'ready' : action?.phase ?? (row.channel ? 'proof' : 'create'),
            blocker: action?.detail || row.blockers[0] || '',
        };
    }), [channelActivationAdapterMatrix, channelActivationNextActions, channelSurfaceRows]);
    const channelProviderLaunchReadyCount = channelProviderLaunchRows.filter(item => item.row.ready).length;
    const channelProviderLaunchBlockedCount = channelProviderLaunchRows.length - channelProviderLaunchReadyCount;
    const channelProviderRunbookRows = useMemo(
        () => channelActivationBacklog.surfaces
            .map(item => channelProviderRunbookFrom(item))
            .filter((item): item is SupportChannelProviderRunbook => Boolean(item)),
        [channelActivationBacklog.surfaces],
    );
    const channelProviderRunbookReadyCount = channelProviderRunbookRows.filter(item => item.ready).length;
    const channelProviderRunbookBlockedCount = channelProviderRunbookRows.length - channelProviderRunbookReadyCount;
    const channelProviderRunbookInitialRows = channelProviderRunbookRows.filter(item => item.initialProvider);
    const channelProviderRunbookInitialReadyCount = channelProviderRunbookInitialRows.filter(item => item.ready).length;
    const channelProviderRunbookInitialBlockedCount = channelProviderRunbookInitialRows.length - channelProviderRunbookInitialReadyCount;
    const channelProviderRunbookMissingSecretCount = channelProviderRunbookRows.reduce((count, item) => count + item.requiredMissingEnvVars.length, 0);
    const channelProviderRunbookMissingTargetCount = channelProviderRunbookRows.reduce((count, item) => count + item.missingLiveTargets.length, 0);
    const channelProviderRunbookProofActionCount = channelProviderRunbookRows.reduce((count, item) => count + item.proofActions.length, 0);
    const channelActivationSecretGroups = useMemo(
        () => channelActivationNextActions
            .filter(action => action.action === 'configure_secrets')
            .map(action => {
                const seen = new Set<string>();
                const envVars = (action.envVars ?? [])
                    .map(cleanEnvVarName)
                    .filter(name => {
                        if (!name || seen.has(name)) return false;
                        seen.add(name);
                        return true;
                    });
                return {
                    surfaceLabel: action.surfaceLabel || action.surfaceType || t('Channel'),
                    surfaceType: action.surfaceType,
                    envVars,
                };
            })
            .filter(group => group.envVars.length > 0),
        [channelActivationNextActions, t],
    );
    const channelActivationSecretNames = useMemo(
        () => Array.from(new Set(channelActivationSecretGroups.flatMap(group => group.envVars))),
        [channelActivationSecretGroups],
    );
    const channelActivationSecretTemplate = useMemo(
        () => channelActivationSecretGroups
            .map(group => [
                `# ${group.surfaceLabel}`,
                ...group.envVars.map(name => `${name}=`),
            ].join('\n'))
            .join('\n\n'),
        [channelActivationSecretGroups],
    );
    const copyChannelActivationSecretTemplate = async () => {
        await copyValue(channelActivationSecretTemplate);
    };
    const channelActivationPlan = useMemo(() => {
        const surfaces = channelActivationBacklog.surfaces.map(item => {
            const surface = recordObject(item, 'surface');
            const channel = recordObject(item, 'channel');
            const ticketing = recordObject(item, 'ticketing');
            const automation = recordObject(item, 'automation');
            const inbound = recordObject(item, 'inbound');
            const outbound = recordObject(item, 'outbound');
            const environment = recordObject(item, 'environment');
            const launch = recordObject(item, 'launch');
            const setupPackage = recordObject(item, 'setupPackage');
            const providerRunbook = channelProviderRunbookFrom(item);
            const surfaceType = textValue(surface?.type);
            return {
                surfaceType,
                surfaceLabel: textValue(surface?.label, surfaceType),
                channelKey: textValue(channel?.key),
                channelStatus: textValue(channel?.status, channel ? 'configured' : 'missing'),
                ready: surface?.ready === true,
                blockers: textArrayFrom(surface?.blockers),
                requiredMissingEnvVars: textArrayFrom(environment?.requiredMissing),
                missingLiveTargets: textArrayFrom(launch?.missingLiveTargets),
                nextActions: channelActivationNextActions.filter(action => action.surfaceType === surfaceType),
                ticketing: {
                    ticketCreationMode: textValue(ticketing?.ticketCreationMode),
                    everyMessage: ticketing?.everyMessage === true,
                    ownerRouting: ticketing?.ownerRouting === true,
                    defaultAssigneeEmail: textValue(ticketing?.defaultAssigneeEmail),
                    defaultQueueKey: textValue(ticketing?.defaultQueueKey),
                    defaultQueueName: textValue(ticketing?.defaultQueueName),
                },
                automation: {
                    autoPrepareTriage: automation?.autoPrepareTriage === true,
                    autoPrepareCustomFields: automation?.autoPrepareCustomFields === true,
                    autoPrepareAgentReply: automation?.autoPrepareAgentReply === true,
                    autoPrepareAgentReplyOnUpdate: automation?.autoPrepareAgentReplyOnUpdate === true,
                    humanReview: automation?.humanReview === true,
                    agentAutoSend: automation?.agentAutoSend === true,
                },
                inbound: {
                    ready: inbound?.ready === true,
                    webhookUrl: textValue(inbound?.webhookUrl),
                    providerWebhookUrl: textValue(inbound?.providerWebhookUrl),
                    webChatUrl: textValue(inbound?.webChatUrl),
                    webChatEmbedScriptUrl: textValue(inbound?.webChatEmbedScriptUrl),
                },
                outbound: {
                    ready: outbound?.ready === true,
                    transport: textValue(outbound?.transport),
                    payloadMode: textValue(outbound?.payloadMode),
                    webhookUrlEnv: textValue(outbound?.webhookUrlEnv),
                    webhookTokenEnv: textValue(outbound?.webhookTokenEnv),
                    botTokenEnv: textValue(outbound?.botTokenEnv),
                },
                liveTargets: Array.isArray(launch?.liveTargets) ? launch.liveTargets : [],
                setupCommands: Array.isArray(launch?.commands) ? launch.commands : [],
                setupPackage,
                providerRunbook,
            };
        });
        return {
            kind: 'support_channel_activation_plan',
            generatedAt: channelActivationBacklog.generatedAt,
            projectId,
            source: serverChannelActivationBacklog ? 'api' : 'local',
            summary: channelActivationBacklog.summary,
            nextActions: channelActivationNextActions,
            secrets: {
                missingEnvVars: channelActivationSecretNames,
                groups: channelActivationSecretGroups,
                template: channelActivationSecretTemplate,
            },
            surfaces,
            adapterMatrix: channelActivationAdapterMatrix,
        };
    }, [
        channelActivationAdapterMatrix,
        channelActivationBacklog,
        channelActivationNextActions,
        channelActivationSecretGroups,
        channelActivationSecretNames,
        channelActivationSecretTemplate,
        projectId,
        serverChannelActivationBacklog,
    ]);
    const channelActivationPlanJson = useMemo(
        () => JSON.stringify(channelActivationPlan, null, 2),
        [channelActivationPlan],
    );
    const channelActivationPlanHref = useMemo(
        () => `data:application/json;charset=utf-8,${encodeURIComponent(channelActivationPlanJson)}`,
        [channelActivationPlanJson],
    );
    const channelActivationSecretTemplateHref = useMemo(
        () => `data:text/plain;charset=utf-8,${encodeURIComponent(channelActivationSecretTemplate)}`,
        [channelActivationSecretTemplate],
    );
    const channelSurfaceNextAction = useMemo<ChannelSurfaceNextAction | null>(() => {
        const row = channelSurfaceRows.find(item => !item.ready);
        if (!row) return null;
        if (!row.channel) {
            return {
                row,
                kind: 'create',
                title: t('Add channel surface'),
                detail: t('Apply the provider preset so this surface can create tickets.'),
                buttonLabel: t('Add'),
            };
        }
        if (row.channel.channelKey !== selectedKey) {
            return {
                row,
                kind: 'select',
                title: t('Open channel setup'),
                detail: row.blockers[0] || t('Open this channel and fix the first blocker.'),
                buttonLabel: t('Open setup'),
            };
        }
        if (row.channel.status !== 'active') {
            return {
                row,
                kind: 'select',
                title: t('Activate channel'),
                detail: t('Set the channel active before it can receive support traffic.'),
                buttonLabel: t('Open setup'),
            };
        }
        if (!row.everyMessage) {
            return {
                row,
                kind: 'fix',
                title: t('Fix ticket mode'),
                detail: t('Switch this channel to new message equals new ticket.'),
                buttonLabel: t('Fix'),
                runAction: 'ticket_mode',
            };
        }
        if (!row.autoDraft) {
            return {
                row,
                kind: 'fix',
                title: t('Enable AI prep'),
                detail: t('Let agents prepare triage, fields, and approval drafts for this surface.'),
                buttonLabel: t('Fix'),
                runAction: 'auto_prepare',
            };
        }
        if (!row.ownerRouting) {
            return {
                row,
                kind: 'fix',
                title: t('Set default owner'),
                detail: t('Add a default assignee or queue owner so each new ticket has an owner.'),
                buttonLabel: t('Save'),
                runAction: 'owner_routing',
            };
        }
        if (!row.inboundReady) {
            return {
                row,
                kind: 'select',
                title: t('Configure inbound'),
                detail: t('Finish inbound setup before messages can create tickets.'),
                buttonLabel: t('Open setup'),
            };
        }
        if (!row.outboundReady) {
            return {
                row,
                kind: 'select',
                title: t('Configure outbound'),
                detail: t('Finish outbound setup before agents can answer from the app.'),
                buttonLabel: t('Open setup'),
            };
        }
        if (!row.launchReady) {
            const blocker = row.launchBlockers[0];
            const action = blocker?.action || blocker?.key || '';
            return {
                row,
                kind: action ? 'run' : 'select',
                title: t(blocker?.label || 'Run launch proof'),
                detail: t(blocker?.detail || 'Run launch proof for this channel.'),
                buttonLabel: action === 'provider_validation'
                    ? t('Validate')
                    : isLaunchConfigFix(action)
                        ? t('Fix')
                        : t('Run'),
                runAction: action || undefined,
            };
        }
        return {
            row,
            kind: 'select',
            title: t('Open channel setup'),
            detail: row.blockers[0] || t('Open this channel and fix the first blocker.'),
            buttonLabel: t('Open setup'),
        };
    }, [channelSurfaceRows, selectedKey, t]);

    const canRunChannelSurfaceNextAction = (action: ChannelSurfaceNextAction) => {
        if (action.kind === 'create') return !creatingSurfaceType;
        if (!action.row.channel) return false;
        if (action.row.channel.channelKey !== selectedKey) return true;
        if (!action.runAction) return true;
        return canRunLaunchProof(action.runAction) && !launchProofRunning(action.runAction);
    };

    const channelSurfaceNextActionIcon = (action: ChannelSurfaceNextAction) => {
        if (action.kind === 'create') {
            return creatingSurfaceType === action.row.type
                ? <Loader className="size-3.5 animate-spin" />
                : <Plus className="size-3.5" />;
        }
        if (!action.row.channel) return <ExternalLink className="size-3.5" />;
        if (action.row.channel.channelKey !== selectedKey || !action.runAction) return <ExternalLink className="size-3.5" />;
        if (launchProofRunning(action.runAction)) return <Loader className="size-3.5 animate-spin" />;
        if (isLaunchConfigFix(action.runAction)) return <Save className="size-3.5" />;
        if (action.runAction === 'provider_validation') return <CheckCircle2 className="size-3.5" />;
        return <RefreshCw className="size-3.5" />;
    };

    const createChannelSurfaceSetup = async (row: ChannelSurfaceRow) => {
        if (creatingSurfaceType) return;
        const preset = channelPresets.find(item => normalizedChannelType(item.type) === row.type);
        if (!preset) {
            startNew();
            return;
        }
        setCreatingSurfaceType(row.type);
        const res = await api.saveChannel(projectId, {
            type: channelTypeFromPreset(preset),
            name: preset.name,
            status: 'paused',
            channelKey: preset.channelKey,
            config: setupConfigFromPreset(preset, currentUserEmail),
        });
        setCreatingSurfaceType('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not add channel setup'));
            return;
        }
        toast.success(t('Channel setup added'));
        selectChannel(res.data.channelKey);
        loadChannels();
    };

    const bootstrapChannelSurfaceSetups = async () => {
        if (bootstrappingSurfaces) return;
        setBootstrappingSurfaces(true);
        const res = await api.bootstrapChannelActivationBacklog(projectId, { status: 'paused' });
        setBootstrappingSurfaces(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not add channel setups'));
            return;
        }
        const result = res.data;
        setServerChannelActivationBacklog(result.activationBacklog);
        if (result.items.length > 0) {
            setChannels(prev => {
                const byKey = new Map(prev.map(channel => [channel.channelKey, channel]));
                for (const channel of result.items) byKey.set(channel.channelKey, channel);
                return [...byKey.values()].sort((a, b) => a.type.localeCompare(b.type) || a.name.localeCompare(b.name));
            });
            selectChannel(result.items[0].channelKey);
            toast.success(`${result.created} ${t('channel setups added')}`);
        } else {
            toast.success(t('Channel setups already exist'));
        }
        loadChannels();
    };

    const activateReadyChannelSurfaceSetups = async () => {
        if (activatingReadySurfaces) return;
        setActivatingReadySurfaces(true);
        const res = await api.activateReadyChannelActivationBacklog(projectId);
        setActivatingReadySurfaces(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not activate channel setups'));
            return;
        }
        const result = res.data;
        setServerChannelActivationBacklog(result.activationBacklog);
        if (result.items.length > 0) {
            setChannels(prev => {
                const byKey = new Map(prev.map(channel => [channel.channelKey, channel]));
                for (const channel of result.items) byKey.set(channel.channelKey, channel);
                return [...byKey.values()].sort((a, b) => a.type.localeCompare(b.type) || a.name.localeCompare(b.name));
            });
            selectChannel(result.items[0].channelKey);
            toast.success(`${result.activated} ${t('channel setups activated')}`);
        } else {
            toast.success(t('No ready channel setups to activate'));
        }
        loadChannels();
    };

    const runChannelSurfaceNextAction = async (action: ChannelSurfaceNextAction) => {
        if (!action.row.channel) {
            await createChannelSurfaceSetup(action.row);
            return;
        }
        if (action.row.channel.channelKey !== selectedKey) {
            selectChannel(action.row.channel.channelKey);
            return;
        }
        if (action.runAction) {
            await runLaunchProof(action.runAction);
            return;
        }
        selectChannel(action.row.channel.channelKey);
    };

    const channelActivationRowFor = (action: ChannelActivationNextAction) => (
        channelSurfaceRows.find(row => row.type === normalizedChannelType(action.surfaceType))
        ?? channelSurfaceRows.find(row => row.channel?.channelKey === action.channelKey)
        ?? null
    );

    const channelActivationConfigFixAction = (row: ChannelSurfaceRow | null) => {
        if (!row) return '';
        if (!row.everyMessage || !row.autoTriage || !row.autoFields || !row.autoDraft || !row.autoFollowUp || !row.humanReview) {
            return 'support_mode';
        }
        if (!row.ownerRouting) return 'owner_routing';
        return '';
    };

    const channelActivationRunnableAction = (action: ChannelActivationNextAction) => {
        const row = channelActivationRowFor(action);
        if (action.action === 'ticket_defaults') return channelActivationConfigFixAction(row);
        if (action.action === 'activate_channel') return 'activate_channel';
        return action.runAction || action.action;
    };

    const channelActivationNextActionRunning = (action: ChannelActivationNextAction) => {
        const row = channelActivationRowFor(action);
        if (action.action === 'create_channel') return creatingSurfaceType === row?.type;
        if (!row?.channel || row.channel.channelKey !== selectedKey) return false;
        const runnableAction = channelActivationRunnableAction(action);
        return Boolean(runnableAction) && launchProofRunning(runnableAction);
    };

    const canRunChannelActivationNextAction = (action: ChannelActivationNextAction) => {
        const row = channelActivationRowFor(action);
        if (!row) return false;
        if (action.action === 'create_channel') return !creatingSurfaceType;
        if (!row.channel) return false;
        if (row.channel.channelKey !== selectedKey) return true;
        if (action.action === 'configure_secrets' || action.action === 'configure_smoke_target') return true;
        const runnableAction = channelActivationRunnableAction(action);
        if (!runnableAction || runnableAction === 'launch_proof') return true;
        return canRunLaunchProof(runnableAction) && !launchProofRunning(runnableAction);
    };

    const channelActivationNextActionLabel = (action: ChannelActivationNextAction) => {
        const row = channelActivationRowFor(action);
        if (action.action === 'create_channel') return t('Add');
        if (row?.channel && row.channel.channelKey !== selectedKey) return t('Open');
        if (action.action === 'configure_secrets' || action.action === 'configure_smoke_target') return t('Open');
        if (action.action === 'ticket_defaults') return t('Fix');
        if (action.action === 'activate_channel') return t('Activate');
        const runnableAction = channelActivationRunnableAction(action);
        if (runnableAction === 'provider_validation') return t('Validate');
        if (runnableAction && runnableAction !== 'launch_proof') return t('Run');
        return t('Open');
    };

    const channelActivationNextActionIcon = (action: ChannelActivationNextAction) => {
        if (channelActivationNextActionRunning(action)) return <Loader className="size-3.5 animate-spin" />;
        const row = channelActivationRowFor(action);
        if (action.action === 'create_channel') return <Plus className="size-3.5" />;
        if (row?.channel && row.channel.channelKey !== selectedKey) return <ExternalLink className="size-3.5" />;
        if (action.action === 'configure_secrets' || action.action === 'configure_smoke_target') return <ExternalLink className="size-3.5" />;
        if (action.action === 'ticket_defaults' || action.action === 'activate_channel') return <Save className="size-3.5" />;
        const runnableAction = channelActivationRunnableAction(action);
        if (runnableAction === 'provider_validation') return <CheckCircle2 className="size-3.5" />;
        return <RefreshCw className="size-3.5" />;
    };

    const runChannelActivationNextAction = async (action: ChannelActivationNextAction) => {
        const row = channelActivationRowFor(action);
        if (!row) return;
        if (action.action === 'create_channel') {
            await createChannelSurfaceSetup(row);
            return;
        }
        if (!row.channel) return;
        if (row.channel.channelKey !== selectedKey) {
            selectChannel(row.channel.channelKey);
            return;
        }
        if (action.action === 'configure_secrets' || action.action === 'configure_smoke_target') {
            selectChannel(row.channel.channelKey);
            return;
        }
        const runnableAction = channelActivationRunnableAction(action);
        if (!runnableAction || runnableAction === 'launch_proof') {
            selectChannel(row.channel.channelKey);
            return;
        }
        await runLaunchProof(runnableAction);
    };

    return (
        <div className="flex min-h-0 flex-1 overflow-hidden rounded-md border bg-background">
            <aside className="flex w-[24rem] shrink-0 flex-col border-r">
                <div className="flex items-start justify-between gap-3 border-b p-4">
                    <div>
                        <h2 className="text-base font-semibold">{t('Channel setup')}</h2>
                        <p className="text-xs text-muted-foreground">{channels.length} {t('connected channels')}</p>
                    </div>
                    <div className="flex flex-wrap items-center justify-end gap-2">
                        <Button size="sm" variant="outline" onClick={() => void syncAll()} disabled={Boolean(syncingChannel)}>
                            {syncingChannel === 'all' ? <Loader className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
                            {t('Sync')}
                        </Button>
                        <Button size="sm" variant="outline" onClick={startNew}>
                            <Plus className="size-4" />
                            {t('Add')}
                        </Button>
                    </div>
                </div>
                <Collapsible className="border-b bg-muted/10 p-3">
                    <CollapsibleTrigger asChild>
                        <Button type="button" size="sm" variant="ghost" className="w-full justify-between px-2">
                            <span className="flex items-center gap-2">
                                <CheckCircle2 className="size-4" />
                                {t('Advanced checks')}
                            </span>
                            <ChevronDown className="size-4" />
                        </Button>
                    </CollapsibleTrigger>
                    <CollapsibleContent className="mt-2 flex flex-wrap gap-2">
                        <Select value={smokeAllTransport} onValueChange={value => setSmokeAllTransport(value as 'direct' | 'http')}>
                            <SelectTrigger className="h-8 w-24 text-xs">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="direct">{t('Direct')}</SelectItem>
                                <SelectItem value="http">{t('HTTP')}</SelectItem>
                            </SelectContent>
                        </Select>
                        <Button size="sm" variant="outline" onClick={() => void runSmokeAll()} disabled={smokingAllChannels || !testMessageBody.trim()}>
                            {smokingAllChannels ? <Loader className="size-4 animate-spin" /> : <CheckCircle2 className="size-4" />}
                            {t('Smoke')}
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => void runOutboundSmokeAll()} disabled={smokingOutboundAllChannels || !outboundSmokeBody.trim()}>
                            {smokingOutboundAllChannels ? <Loader className="size-4 animate-spin" /> : <Send className="size-4" />}
                            {t('Outbound smoke')}
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => void runLifecycleSmokeAll()} disabled={smokingLifecycleAllChannels || !testMessageBody.trim() || !outboundSmokeBody.trim()}>
                            {smokingLifecycleAllChannels ? <Loader className="size-4 animate-spin" /> : <CheckCircle2 className="size-4" />}
                            {t('Lifecycle smoke')}
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => void runLifecycleSmokeAll({ attachmentOnly: true })} disabled={smokingLifecycleAllChannels || !outboundSmokeBody.trim()}>
                            {smokingLifecycleAllChannels ? <Loader className="size-4 animate-spin" /> : <CheckCircle2 className="size-4" />}
                            {t('Attachment lifecycle')}
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => void runDelivery()} disabled={Boolean(deliveryRunMode)}>
                            {deliveryRunMode === 'queued' ? <Loader className="size-4 animate-spin" /> : <Send className="size-4" />}
                            {t('Run delivery')}
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => void runDelivery(true)} disabled={Boolean(deliveryRunMode)}>
                            {deliveryRunMode === 'failed' ? <Loader className="size-4 animate-spin" /> : <AlertTriangle className="size-4" />}
                            {t('Retry failed')}
                        </Button>
                    </CollapsibleContent>
                </Collapsible>
                {smokeRun && (
                    <div className="border-b bg-muted/20 p-3 text-xs">
                        <div className="mb-2 flex items-center justify-between gap-2">
                            <div className="font-medium">{t('Channel smoke')}</div>
                            <div className="flex items-center gap-1.5">
                                <Badge variant="outline" className="font-normal">
                                    {smokeRun.transport === 'http' ? t('HTTP') : t('Direct')}
                                </Badge>
                                <Badge variant={smokeRun.failed > 0 ? 'destructive' : 'secondary'} className="font-normal">
                                    {smokeRun.status}
                                </Badge>
                            </div>
                        </div>
                        <div className="grid grid-cols-4 gap-2">
                            <div>
                                <div className="font-medium">{smokeRun.ready}/{smokeRun.channels}</div>
                                <div className="text-muted-foreground">{t('ready')}</div>
                            </div>
                            <div>
                                <div className="font-medium">{smokeRun.processed}</div>
                                <div className="text-muted-foreground">{t('processed')}</div>
                            </div>
                            <div>
                                <div className="font-medium">{smokeRun.failed}</div>
                                <div className="text-muted-foreground">{t('failed')}</div>
                            </div>
                            <div>
                                <div className="font-medium">{smokeRun.skipped}</div>
                                <div className="text-muted-foreground">{t('skipped')}</div>
                            </div>
                        </div>
                        {smokeRun.failures.length > 0 && (
                            <div className="mt-2 space-y-1">
                                {smokeRun.failures.slice(0, 3).map(failure => (
                                    <div key={`${failure.channelId}:${failure.channelKey}`} className="truncate text-destructive">
                                        {failure.channelKey || failure.channelId}: {failure.error}
                                    </div>
                                ))}
                            </div>
                        )}
                        {smokeRun.items.length > 0 && (
                            <div className="mt-2 space-y-1">
                                {smokeRun.items.slice(0, 3).map(item => (
                                    <div key={`${item.channelId}:${item.eventId}`} className="flex min-w-0 items-center justify-between gap-2">
                                        <span className="truncate">{item.channelKey}</span>
                                        <span className="shrink-0 text-muted-foreground">{item.processed} / {item.failed}</span>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}
                {outboundSmokeRun && (
                    <div className="border-b bg-muted/20 p-3 text-xs">
                        <div className="mb-2 flex items-center justify-between gap-2">
                            <div className="font-medium">{t('Outbound smoke')}</div>
                            <Badge variant={outboundSmokeRun.failed > 0 ? 'destructive' : outboundSmokeRun.deferred > 0 ? 'outline' : 'secondary'} className="font-normal">
                                {outboundSmokeRun.status}
                            </Badge>
                        </div>
                        <div className="grid grid-cols-4 gap-2">
                            <div>
                                <div className="font-medium">{outboundSmokeRun.ready}/{outboundSmokeRun.channels}</div>
                                <div className="text-muted-foreground">{t('ready')}</div>
                            </div>
                            <div>
                                <div className="font-medium">{outboundSmokeRun.sent}</div>
                                <div className="text-muted-foreground">{t('sent')}</div>
                            </div>
                            <div>
                                <div className="font-medium">{outboundSmokeRun.deferred}</div>
                                <div className="text-muted-foreground">{t('deferred')}</div>
                            </div>
                            <div>
                                <div className="font-medium">{outboundSmokeRun.failed}</div>
                                <div className="text-muted-foreground">{t('failed')}</div>
                            </div>
                        </div>
                        {outboundSmokeRun.failures.length > 0 && (
                            <div className="mt-2 space-y-1">
                                {outboundSmokeRun.failures.slice(0, 3).map(failure => (
                                    <div key={`${failure.channelId}:${failure.channelKey}`} className="truncate text-destructive">
                                        {failure.channelKey || failure.channelId}: {failure.error}
                                    </div>
                                ))}
                            </div>
                        )}
                        {outboundSmokeRun.items.length > 0 && (
                            <div className="mt-2 space-y-1">
                                {outboundSmokeRun.items.slice(0, 3).map(item => (
                                    <div key={`${item.channelId}:${item.messageId}`} className="flex min-w-0 items-center justify-between gap-2">
                                        <span className="truncate">{item.channelKey}</span>
                                        <span className="shrink-0 text-muted-foreground">{item.status}</span>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}
                {lifecycleSmokeRun && (
                    <div className="border-b bg-muted/20 p-3 text-xs">
                        <div className="mb-2 flex items-center justify-between gap-2">
                            <div className="font-medium">{t('Lifecycle smoke')}</div>
                            <Badge variant={lifecycleSmokeRun.failed > 0 ? 'destructive' : lifecycleSmokeRun.deferred > 0 ? 'outline' : 'secondary'} className="font-normal">
                                {lifecycleSmokeRun.status}
                            </Badge>
                        </div>
                        <div className="grid grid-cols-4 gap-2">
                            <div>
                                <div className="font-medium">{lifecycleSmokeRun.ready}/{lifecycleSmokeRun.channels}</div>
                                <div className="text-muted-foreground">{t('ready')}</div>
                            </div>
                            <div>
                                <div className="font-medium">{lifecycleSmokeRun.sent}</div>
                                <div className="text-muted-foreground">{t('sent')}</div>
                            </div>
                            <div>
                                <div className="font-medium">{lifecycleSmokeRun.deferred}</div>
                                <div className="text-muted-foreground">{t('deferred')}</div>
                            </div>
                            <div>
                                <div className="font-medium">{lifecycleSmokeRun.failed}</div>
                                <div className="text-muted-foreground">{t('failed')}</div>
                            </div>
                        </div>
                        {lifecycleSmokeRun.failures.length > 0 && (
                            <div className="mt-2 space-y-1">
                                {lifecycleSmokeRun.failures.slice(0, 3).map(failure => (
                                    <div key={`${failure.channelId}:${failure.channelKey}`} className="truncate text-destructive">
                                        {failure.channelKey || failure.channelId}: {failure.error}
                                    </div>
                                ))}
                            </div>
                        )}
                        {lifecycleSmokeRun.items.length > 0 && (
                            <div className="mt-2 space-y-1">
                                {lifecycleSmokeRun.items.slice(0, 3).map(item => (
                                    <div key={`${item.channelId}:${item.replyId || item.messageId}`} className="flex min-w-0 items-center justify-between gap-2">
                                        <span className="truncate">{item.channelKey}</span>
                                        <span className="shrink-0 text-muted-foreground">{item.status}</span>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}
                <div className="border-b p-3">
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                        <div className="text-xs font-medium uppercase text-muted-foreground">{t('Connect channels')}</div>
                        <div className="flex flex-wrap items-center justify-end gap-1.5">
                            <Badge variant={readySurfaceCount === totalSurfaceCount ? 'secondary' : 'outline'} className="font-normal">
                                {readySurfaceCount}/{totalSurfaceCount} {t('ready')}
                            </Badge>
                            <Button
                                type="button"
                                size="xs"
                                variant="outline"
                                data-channel-bootstrap-surfaces
                                data-channel-bootstrap-missing={channelActivationSummary.missingSurfaces}
                                onClick={() => void bootstrapChannelSurfaceSetups()}
                                disabled={bootstrappingSurfaces || channelActivationSummary.missingSurfaces === 0}
                            >
                                {bootstrappingSurfaces
                                    ? <Loader className="size-3 animate-spin" />
                                    : <Plus className="size-3" />}
                                {t('Add providers')}
                            </Button>
                            <Button
                                type="button"
                                size="xs"
                                variant="outline"
                                data-channel-activation-activate-ready
                                data-channel-activation-ready-count={channelActivationNextActionPhases.activate || 0}
                                onClick={() => void activateReadyChannelSurfaceSetups()}
                                disabled={activatingReadySurfaces || (channelActivationNextActionPhases.activate || 0) === 0}
                            >
                                {activatingReadySurfaces
                                    ? <Loader className="size-3 animate-spin" />
                                    : <CheckCircle2 className="size-3" />}
                                {t('Activate')}
                            </Button>
                            <Button
                                type="button"
                                size="xs"
                                variant="outline"
                                data-channel-activation-backlog-copy
                                data-channel-activation-backlog-count={channelActivationBacklog.channels.length}
                                data-channel-activation-backlog-source={serverChannelActivationBacklog ? 'api' : 'local'}
                                onClick={() => void copyChannelActivationBacklog()}
                            >
                                <Copy className="size-3" />
                                {t('Copy backlog')}
                            </Button>
                            <Button asChild size="xs" variant="outline">
                                <a
                                    href={channelActivationBacklogHref}
                                    download={`support-channel-activation-backlog-${projectId}.json`}
                                    data-channel-activation-backlog-download
                                    data-channel-activation-backlog-count={channelActivationBacklog.channels.length}
                                    data-channel-activation-backlog-source={serverChannelActivationBacklog ? 'api' : 'local'}
                                >
                                    <Download className="size-3" />
                                    {t('Download')}
                                </a>
                            </Button>
                            <Button asChild size="xs" variant="outline">
                                <a
                                    href={channelActivationPlanHref}
                                    download={`support-channel-activation-plan-${projectId}.json`}
                                    data-channel-activation-plan-download
                                    data-channel-activation-plan-kind="support_channel_activation_plan"
                                    data-channel-activation-plan-actions={channelActivationNextActions.length}
                                    data-channel-activation-plan-secret-count={channelActivationSecretNames.length}
                                    data-channel-activation-plan-adapter-count={channelActivationAdapterMatrix.length}
                                    data-channel-activation-plan-source={serverChannelActivationBacklog ? 'api' : 'local'}
                                >
                                    <Download className="size-3" />
                                    {t('Plan')}
                                </a>
                            </Button>
                        </div>
                    </div>
                    <div className="mb-2 grid grid-cols-4 gap-2 text-xs">
                        <div className="rounded-md border bg-muted/20 p-2">
                            <div className="font-medium">{configuredSurfaceCount}</div>
                            <div className="text-muted-foreground">{t('connected')}</div>
                        </div>
                        <div className="rounded-md border bg-muted/20 p-2">
                            <div className="font-medium">{channelSurfaceRows.filter(row => row.everyMessage).length}</div>
                            <div className="text-muted-foreground">{t('new tickets')}</div>
                        </div>
                        <div className="rounded-md border bg-muted/20 p-2">
                            <div className="font-medium">{channelSurfaceRows.filter(row => row.autoDraft).length}</div>
                            <div className="text-muted-foreground">{t('AI drafts')}</div>
                        </div>
                        <div className="rounded-md border bg-muted/20 p-2">
                            <div className="font-medium">{channelSurfaceRows.filter(row => row.ownerRouting).length}</div>
                            <div className="text-muted-foreground">{t('owner set')}</div>
                        </div>
                    </div>
                    <Collapsible className="mt-3">
                        <CollapsibleTrigger asChild>
                            <Button type="button" size="sm" variant="ghost" className="w-full justify-between px-2">
                                <span className="flex items-center gap-2">
                                    <Database className="size-4" />
                                    {t('Launch details')}
                                </span>
                                <ChevronDown className="size-4" />
                            </Button>
                        </CollapsibleTrigger>
                        <CollapsibleContent className="mt-2 space-y-2">
                            <div
                                className="rounded-md border bg-background p-2 text-xs"
                                data-channel-provider-launch-board
                                data-channel-provider-launch-board-total={channelProviderLaunchRows.length}
                                data-channel-provider-launch-board-ready={channelProviderLaunchReadyCount}
                                data-channel-provider-launch-board-blocked={channelProviderLaunchBlockedCount}
                                data-channel-provider-launch-board-actions={channelActivationNextActions.length}
                                data-channel-provider-launch-board-source={serverChannelActivationBacklog ? 'api' : 'local'}
                            >
                        <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
                            <div className="min-w-0">
                                <div className="truncate font-medium">{t('Provider launch')}</div>
                                <div className="truncate text-muted-foreground">{t('Inbound, outbound, tickets, and human review per surface')}</div>
                            </div>
                            <Badge
                                variant={channelProviderLaunchBlockedCount === 0 ? 'secondary' : 'outline'}
                                className="shrink-0 font-normal"
                            >
                                {channelProviderLaunchReadyCount}/{channelProviderLaunchRows.length} {t('ready')}
                            </Badge>
                        </div>
                        <div className="space-y-1">
                            {channelProviderLaunchRows.map(item => {
                                const row = item.row;
                                const action = item.action;
                                const actionDisabled = action
                                    ? !canRunChannelActivationNextAction(action)
                                    : !row.channel && Boolean(creatingSurfaceType);
                                return (
                                    <div
                                        key={row.type}
                                        className="rounded-md border bg-muted/20 px-2 py-1.5"
                                        data-channel-provider-launch-row={row.type}
                                        data-channel-provider-launch-row-ready={row.ready ? 'true' : 'false'}
                                        data-channel-provider-launch-row-configured={row.channel ? 'true' : 'false'}
                                        data-channel-provider-launch-row-inbound={row.inboundReady ? 'true' : 'false'}
                                        data-channel-provider-launch-row-outbound={row.outboundReady ? 'true' : 'false'}
                                        data-channel-provider-launch-row-ticketing={row.everyMessage ? 'true' : 'false'}
                                        data-channel-provider-launch-row-autopilot={row.autoDraft ? 'true' : 'false'}
                                        data-channel-provider-launch-row-owner={row.ownerRouting ? 'true' : 'false'}
                                        data-channel-provider-launch-row-review={row.humanReview ? 'true' : 'false'}
                                        data-channel-provider-launch-row-launch={row.launchReady ? 'true' : 'false'}
                                        data-channel-provider-launch-row-phase={item.phase}
                                        data-channel-provider-launch-row-action={action?.action ?? ''}
                                        data-channel-provider-launch-row-channel={row.channel?.channelKey ?? ''}
                                    >
                                        <div className="mb-1 flex min-w-0 items-center justify-between gap-2">
                                            <div className="min-w-0">
                                                <div className="truncate font-medium">{t(row.label)}</div>
                                                <div className="truncate text-[11px] text-muted-foreground">
                                                    {row.channel?.channelKey || t('Missing')} · {t(channelActivationPhaseLabel(item.phase))}
                                                </div>
                                            </div>
                                            <Button
                                                type="button"
                                                size="xs"
                                                variant="outline"
                                                className="h-7 shrink-0 px-2"
                                                data-channel-provider-launch-run={row.type}
                                                data-channel-provider-launch-run-action={action?.action ?? (row.channel ? 'open' : 'create_channel')}
                                                disabled={actionDisabled}
                                                onClick={() => {
                                                    if (action) {
                                                        void runChannelActivationNextAction(action);
                                                        return;
                                                    }
                                                    if (row.channel) {
                                                        selectChannel(row.channel.channelKey);
                                                        return;
                                                    }
                                                    void createChannelSurfaceSetup(row);
                                                }}
                                            >
                                                {action
                                                    ? channelActivationNextActionIcon(action)
                                                    : row.channel
                                                        ? <ExternalLink className="size-3.5" />
                                                        : creatingSurfaceType === row.type
                                                            ? <Loader className="size-3.5 animate-spin" />
                                                            : <Plus className="size-3.5" />}
                                                {action
                                                    ? channelActivationNextActionLabel(action)
                                                    : row.channel
                                                        ? t('Open')
                                                        : t('Add')}
                                            </Button>
                                        </div>
                                        <div className="mb-1 flex flex-wrap gap-1">
                                            <Badge variant={row.inboundReady ? 'secondary' : 'outline'} className="font-normal">
                                                {t('In')}
                                            </Badge>
                                            <Badge variant={row.outboundReady ? 'secondary' : 'outline'} className="font-normal">
                                                {t('Out')}
                                            </Badge>
                                            <Badge variant={row.everyMessage ? 'secondary' : 'outline'} className="font-normal">
                                                {t('Ticket')}
                                            </Badge>
                                            <Badge variant={row.autoDraft ? 'secondary' : 'outline'} className="font-normal">
                                                {t('AI prep')}
                                            </Badge>
                                            <Badge variant={row.humanReview ? 'secondary' : 'outline'} className="font-normal">
                                                {t('Review')}
                                            </Badge>
                                        </div>
                                        <div className="truncate text-[11px] text-muted-foreground">
                                            {item.readyChecks}/8 {t('checks')} {item.blocker ? `· ${t(item.blocker)}` : ''}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                    {channelProviderRunbookRows.length > 0 && (
                        <div
                            className="mb-2 rounded-md border bg-background p-2 text-xs"
                            data-channel-provider-runbook
                            data-channel-provider-runbook-total={channelProviderRunbookRows.length}
                            data-channel-provider-runbook-ready={channelProviderRunbookReadyCount}
                            data-channel-provider-runbook-blocked={channelProviderRunbookBlockedCount}
                            data-channel-provider-runbook-initial-total={channelProviderRunbookInitialRows.length}
                            data-channel-provider-runbook-initial-ready={channelProviderRunbookInitialReadyCount}
                            data-channel-provider-runbook-initial-blocked={channelProviderRunbookInitialBlockedCount}
                            data-channel-provider-runbook-missing-secrets={channelProviderRunbookMissingSecretCount}
                            data-channel-provider-runbook-missing-targets={channelProviderRunbookMissingTargetCount}
                            data-channel-provider-runbook-proof-actions={channelProviderRunbookProofActionCount}
                            data-channel-provider-runbook-source={serverChannelActivationBacklog ? 'api' : 'local'}
                        >
                            <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
                                <div className="min-w-0">
                                    <div className="truncate font-medium">{t('Provider runbook')}</div>
                                    <div className="truncate text-muted-foreground">{t('Initial: Email, Web chat, Slack, Discord')}</div>
                                </div>
                                <div className="flex shrink-0 flex-wrap justify-end gap-1">
                                    <Badge
                                        variant={channelProviderRunbookInitialBlockedCount === 0 ? 'secondary' : 'outline'}
                                        className="font-normal"
                                    >
                                        {channelProviderRunbookInitialReadyCount}/{channelProviderRunbookInitialRows.length} {t('initial')}
                                    </Badge>
                                    <Badge
                                        variant={channelProviderRunbookBlockedCount === 0 ? 'secondary' : 'outline'}
                                        className="font-normal"
                                    >
                                        {channelProviderRunbookReadyCount}/{channelProviderRunbookRows.length} {t('all')}
                                    </Badge>
                                </div>
                            </div>
                            <div className="grid grid-cols-3 gap-2 pb-2">
                                <div className="rounded border bg-muted/20 px-2 py-1">
                                    <div className="text-[10px] uppercase text-muted-foreground">{t('Secrets')}</div>
                                    <div className="font-semibold">{channelProviderRunbookMissingSecretCount}</div>
                                </div>
                                <div className="rounded border bg-muted/20 px-2 py-1">
                                    <div className="text-[10px] uppercase text-muted-foreground">{t('Targets')}</div>
                                    <div className="font-semibold">{channelProviderRunbookMissingTargetCount}</div>
                                </div>
                                <div className="rounded border bg-muted/20 px-2 py-1">
                                    <div className="text-[10px] uppercase text-muted-foreground">{t('Proof')}</div>
                                    <div className="font-semibold">{channelProviderRunbookProofActionCount}</div>
                                </div>
                            </div>
                            <div className="space-y-1">
                                {channelProviderRunbookRows.map(runbook => {
                                    const surfaceRow = channelSurfaceRows.find(row => row.type === normalizedChannelType(runbook.surfaceType));
                                    const actionLabel = runbook.channelKey ? t('Open') : t('Add');
                                    return (
                                        <div
                                            key={runbook.surfaceType}
                                            className="rounded-md border bg-muted/20 px-2 py-1.5"
                                            data-channel-provider-runbook-row={runbook.surfaceType}
                                            data-channel-provider-runbook-row-ready={runbook.ready ? 'true' : 'false'}
                                            data-channel-provider-runbook-row-phase={runbook.phase}
                                            data-channel-provider-runbook-row-wave={runbook.launchWave}
                                            data-channel-provider-runbook-row-initial={runbook.initialProvider ? 'true' : 'false'}
                                            data-channel-provider-runbook-row-channel={runbook.channelKey}
                                            data-channel-provider-runbook-row-status={runbook.channelStatus}
                                            data-channel-provider-runbook-row-missing-secrets={runbook.requiredMissingEnvVars.length}
                                            data-channel-provider-runbook-row-missing-targets={runbook.missingLiveTargets.length}
                                            data-channel-provider-runbook-row-proof-actions={runbook.proofActions.length}
                                            data-channel-provider-runbook-row-commands={runbook.commands.length}
                                            data-channel-provider-runbook-row-package-keys={runbook.setupPackageKeys.join(',')}
                                        >
                                            <div className="mb-1 flex min-w-0 items-center justify-between gap-2">
                                                <div className="min-w-0">
                                                    <div className="truncate font-medium">{t(runbook.surfaceLabel || runbook.surfaceType)}</div>
                                                    <div className="truncate text-[11px] text-muted-foreground">
                                                        {runbook.initialProvider ? t('Initial') : t('Later')} · {runbook.channelKey || t('Missing')} · {t(channelActivationPhaseLabel(runbook.phase))}
                                                    </div>
                                                </div>
                                                <Button
                                                    type="button"
                                                    size="xs"
                                                    variant="outline"
                                                    className="h-7 shrink-0 px-2"
                                                    data-channel-provider-runbook-open={runbook.surfaceType}
                                                    disabled={!runbook.channelKey && (!surfaceRow || Boolean(creatingSurfaceType))}
                                                    onClick={() => {
                                                        if (runbook.channelKey) {
                                                            selectChannel(runbook.channelKey);
                                                            return;
                                                        }
                                                        if (surfaceRow) void createChannelSurfaceSetup(surfaceRow);
                                                    }}
                                                >
                                                    {runbook.channelKey
                                                        ? <ExternalLink className="size-3.5" />
                                                        : creatingSurfaceType === surfaceRow?.type
                                                            ? <Loader className="size-3.5 animate-spin" />
                                                            : <Plus className="size-3.5" />}
                                                    {actionLabel}
                                                </Button>
                                            </div>
                                            <div className="mb-1 flex flex-wrap gap-1">
                                                <Badge variant={runbook.requiredMissingEnvVars.length === 0 ? 'secondary' : 'destructive'} className="font-normal">
                                                    {runbook.requiredMissingEnvVars.length} {t('secrets')}
                                                </Badge>
                                                <Badge variant={runbook.missingLiveTargets.length === 0 ? 'secondary' : 'outline'} className="font-normal">
                                                    {runbook.missingLiveTargets.length} {t('targets')}
                                                </Badge>
                                                <Badge variant={runbook.proofActions.some(action => action.status !== 'done') ? 'outline' : 'secondary'} className="font-normal">
                                                    {runbook.proofActions.length} {t('proof')}
                                                </Badge>
                                                {runbook.commands.length > 0 && (
                                                    <Badge variant="outline" className="font-normal">
                                                        {runbook.commands.length} {t('commands')}
                                                    </Badge>
                                                )}
                                            </div>
                                            <div className="truncate text-[11px] text-muted-foreground">
                                                {runbook.providerSteps[0] || runbook.blockers[0] || t('Review provider setup.')}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                    <div
                        className="mb-2 rounded-md border bg-background p-2 text-xs"
                        data-channel-ticket-creation-proof
                        data-channel-ticket-creation-proof-total={channelSurfaceRows.length}
                        data-channel-ticket-creation-proof-ready={channelSurfaceRows.filter(row => row.everyMessage).length}
                        data-channel-ticket-creation-proof-thread-updates={channelSurfaceRows.filter(row => !row.everyMessage).length}
                        data-channel-ticket-creation-proof-active={channelSurfaceRows.filter(row => row.channel?.status === 'active').length}
                    >
                        <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
                            <div className="min-w-0">
                                <div className="truncate font-medium">{t('Ticket creation proof')}</div>
                                <div className="truncate text-muted-foreground">{t('New message equals new ticket')}</div>
                            </div>
                            <Badge
                                variant={channelSurfaceRows.every(row => row.everyMessage) ? 'secondary' : 'destructive'}
                                className="font-normal"
                            >
                                {channelSurfaceRows.filter(row => row.everyMessage).length}/{channelSurfaceRows.length}
                            </Badge>
                        </div>
                        <div className="space-y-1">
                            {channelSurfaceRows.map(row => (
                                <div
                                    key={row.type}
                                    className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2"
                                    data-channel-ticket-creation-row={row.type}
                                    data-channel-ticket-creation-mode={row.ticketMode}
                                    data-channel-ticket-creation-every-message={row.everyMessage ? 'true' : 'false'}
                                    data-channel-ticket-creation-status={row.channel?.status ?? 'missing'}
                                    data-channel-ticket-creation-channel={row.channel?.channelKey ?? ''}
                                >
                                    <span className="truncate">{t(row.label)}</span>
                                    <Badge variant={row.everyMessage ? 'secondary' : 'outline'} className="font-normal">
                                        {row.everyMessage ? t('New ticket per message') : t('Thread updates')}
                                    </Badge>
                                </div>
                            ))}
                        </div>
                    </div>
                    {channelActivationAdapterMatrix.length > 0 && (
                        <div
                            className="mb-2 rounded-md border bg-background p-2 text-xs"
                            data-channel-adapter-matrix
                            data-channel-adapter-matrix-total={channelActivationAdapterMatrix.length}
                            data-channel-adapter-matrix-ready={channelActivationAdapterReadyCount}
                            data-channel-adapter-matrix-blocked={channelActivationAdapterBlockedCount}
                            data-channel-adapter-matrix-source={serverChannelActivationBacklog ? 'api' : 'local'}
                        >
                            <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
                                <div className="min-w-0 font-medium">{t('Adapters')}</div>
                                <div className="flex shrink-0 flex-wrap justify-end gap-1">
                                    <Badge
                                        variant={channelActivationAdapterBlockedCount === 0 ? 'secondary' : 'outline'}
                                        className="font-normal"
                                    >
                                        {channelActivationAdapterReadyCount}/{channelActivationAdapterMatrix.length} {t('ready')}
                                    </Badge>
                                    {channelActivationAdapterBlockedCount > 0 && (
                                        <Badge variant="destructive" className="font-normal">
                                            {channelActivationAdapterBlockedCount} {t('blocked')}
                                        </Badge>
                                    )}
                                </div>
                            </div>
                            <div className="space-y-1">
                                {channelActivationAdapterMatrix.map(row => {
                                    const blockers = [
                                        row.requiredMissingEnvVars.length > 0
                                            ? `${row.requiredMissingEnvVars.length} ${t('env vars')}`
                                            : '',
                                        row.missingLiveTargets.length > 0
                                            ? `${row.missingLiveTargets.length} ${t('targets')}`
                                            : '',
                                        row.nextAction?.title ?? '',
                                    ].filter(Boolean);
                                    return (
                                        <button
                                            key={row.surfaceType}
                                            type="button"
                                            disabled={!row.channelKey}
                                            className={[
                                                'w-full rounded-md border px-2 py-1.5 text-left transition-colors',
                                                row.channelKey && row.channelKey === selectedKey ? 'border-primary bg-primary/5' : 'bg-background hover:bg-muted/40',
                                                !row.channelKey ? 'opacity-80' : '',
                                            ].join(' ')}
                                            data-channel-adapter-row={row.surfaceType}
                                            data-channel-adapter-row-channel={row.channelKey}
                                            data-channel-adapter-row-status={row.channelStatus}
                                            data-channel-adapter-row-ready={row.ready ? 'true' : 'false'}
                                            data-channel-adapter-row-inbound-ready={row.inbound.ready ? 'true' : 'false'}
                                            data-channel-adapter-row-outbound-ready={row.outbound.ready ? 'true' : 'false'}
                                            data-channel-adapter-row-action={row.nextAction?.action ?? ''}
                                            data-channel-adapter-row-phase={row.nextAction?.phase ?? ''}
                                            onClick={() => {
                                                if (row.channelKey) selectChannel(row.channelKey);
                                            }}
                                        >
                                            <div className="mb-1 flex min-w-0 items-center justify-between gap-2">
                                                <div className="min-w-0">
                                                    <div className="truncate font-medium">{t(row.surfaceLabel)}</div>
                                                    <div className="truncate text-[11px] text-muted-foreground">
                                                        {row.channelKey || t('Missing')} / {row.providerName || row.surfaceType}
                                                    </div>
                                                </div>
                                                <Badge variant={row.ready ? 'secondary' : 'outline'} className="font-normal">
                                                    {row.ready ? t('Ready') : t(channelActivationPhaseLabel(row.nextAction?.phase ?? 'Next'))}
                                                </Badge>
                                            </div>
                                            <div className="flex flex-wrap gap-1">
                                                <Badge variant={row.inbound.ready ? 'secondary' : 'outline'} className="font-normal">
                                                    {t('In')} {row.inbound.adapter}
                                                </Badge>
                                                <Badge variant={row.outbound.ready ? 'secondary' : 'outline'} className="font-normal">
                                                    {t('Out')} {row.outbound.adapter || row.surfaceType}
                                                </Badge>
                                                <Badge variant={row.ticketing.everyMessage ? 'secondary' : 'outline'} className="font-normal">
                                                    {row.ticketing.everyMessage ? t('New ticket per message') : t('Thread updates')}
                                                </Badge>
                                                <Badge variant={row.automation.humanReview ? 'secondary' : 'outline'} className="font-normal">
                                                    {row.automation.humanReview ? t('Review') : t('Auto-send')}
                                                </Badge>
                                            </div>
                                            {blockers.length > 0 && (
                                                <div className="mt-1 truncate text-[11px] text-muted-foreground">
                                                    {blockers.join(' / ')}
                                                </div>
                                            )}
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                    {channelActivationNextActions.length > 0 && (
                        <div
                            className="mb-2 rounded-md border bg-background p-2 text-xs"
                            data-channel-activation-next-actions
                            data-channel-activation-next-action-count={channelActivationNextActions.length}
                        >
                            <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
                                <div className="min-w-0 font-medium">{t('Activation next')}</div>
                                <div className="flex shrink-0 flex-wrap justify-end gap-1">
                                    {visibleChannelActivationPhases.map(([phase, count]) => (
                                        <Badge
                                            key={phase}
                                            variant={phase === 'secrets' || phase === 'targets' ? 'destructive' : 'outline'}
                                            className="font-normal"
                                            data-channel-activation-phase={phase}
                                            data-channel-activation-phase-count={count}
                                        >
                                            {count} {t(channelActivationPhaseLabel(phase))}
                                        </Badge>
                                    ))}
                                </div>
                            </div>
                            <div className="space-y-1">
                                {visibleChannelActivationNextActions.map(action => (
                                    <div
                                        key={`${action.phase}:${action.surfaceType}:${action.channelId || action.channelKey}`}
                                        className="grid min-w-0 grid-cols-[4.5rem_minmax(0,1fr)_auto] items-center gap-2"
                                        data-channel-activation-next-action
                                        data-channel-activation-next-action-phase={action.phase}
                                        data-channel-activation-next-action-surface={action.surfaceType}
                                        data-channel-activation-next-action-command={action.action}
                                        data-channel-activation-next-action-env-vars={(action.envVars ?? []).join(',')}
                                    >
                                        <span className="truncate text-muted-foreground">{t(channelActivationPhaseLabel(action.phase))}</span>
                                        <span className="truncate">{action.surfaceLabel}: {action.title}</span>
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            className="h-7 shrink-0 px-2 text-xs"
                                            data-channel-activation-next-action-run={action.action}
                                            data-channel-activation-next-action-target={action.surfaceType}
                                            disabled={!canRunChannelActivationNextAction(action)}
                                            onClick={() => void runChannelActivationNextAction(action)}
                                        >
                                            {channelActivationNextActionIcon(action)}
                                            {channelActivationNextActionLabel(action)}
                                        </Button>
                                    </div>
                                ))}
                            </div>
                            {channelActivationSecretTemplate && (
                                <div
                                    className="mt-2 border-t pt-2"
                                    data-channel-activation-secret-template
                                    data-channel-activation-secret-count={channelActivationSecretNames.length}
                                >
                                    <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
                                        <div className="min-w-0">
                                            <div className="truncate font-medium">{t('Missing secret template')}</div>
                                            <div className="truncate text-muted-foreground">
                                                {channelActivationSecretNames.length} {t('env vars')} · {t('blank values only')}
                                            </div>
                                        </div>
                                        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                                            <Button
                                                type="button"
                                                size="sm"
                                                variant="outline"
                                                className="h-7 px-2 text-xs"
                                                data-channel-activation-secret-copy
                                                onClick={() => void copyChannelActivationSecretTemplate()}
                                            >
                                                <Copy className="size-3.5" />
                                                {t('Copy')}
                                            </Button>
                                            <Button asChild size="sm" variant="outline" className="h-7 px-2 text-xs">
                                                <a
                                                    href={channelActivationSecretTemplateHref}
                                                    download={`support-channel-activation-secrets-${projectId}.env`}
                                                    data-channel-activation-secret-template-download
                                                    data-channel-activation-secret-count={channelActivationSecretNames.length}
                                                >
                                                    <Download className="size-3.5" />
                                                    {t('.env')}
                                                </a>
                                            </Button>
                                            {tenantId && (
                                                <Button
                                                    type="button"
                                                    size="sm"
                                                    variant="outline"
                                                    className="h-7 px-2 text-xs"
                                                    onClick={() => void navigate(`/${tenantId}/${projectId}/settings#project-secrets`)}
                                                >
                                                    <ExternalLink className="size-3.5" />
                                                    {t('Project secrets')}
                                                </Button>
                                            )}
                                        </div>
                                    </div>
                                    <pre className="max-h-32 overflow-auto rounded border bg-muted/20 p-2 font-mono text-[11px] leading-5">
                                        {channelActivationSecretTemplate}
                                    </pre>
                                </div>
                            )}
                        </div>
                    )}
                        </CollapsibleContent>
                    </Collapsible>
                    {channelSurfaceNextAction && (
                        <div
                            data-channel-surface-next-action
                            data-channel-surface-next-action-kind={channelSurfaceNextAction.kind}
                            data-channel-surface-next-action-target={channelSurfaceNextAction.row.type}
                            className="mb-2 rounded-md border bg-background p-2 text-xs"
                        >
                            <div className="mb-1 flex min-w-0 items-center justify-between gap-2">
                                <div className="min-w-0">
                                    <div className="flex min-w-0 items-center gap-1.5">
                                        <AlertTriangle className="size-3.5 shrink-0 text-muted-foreground" />
                                        <span className="truncate font-medium">{t(channelSurfaceNextAction.row.label)}</span>
                                    </div>
                                    <div className="mt-1 truncate text-muted-foreground">{channelSurfaceNextAction.title}</div>
                                </div>
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    className="h-7 shrink-0 px-2 text-xs"
                                    disabled={!canRunChannelSurfaceNextAction(channelSurfaceNextAction)}
                                    data-channel-surface-create={channelSurfaceNextAction.kind === 'create' ? channelSurfaceNextAction.row.type : undefined}
                                    onClick={() => void runChannelSurfaceNextAction(channelSurfaceNextAction)}
                                >
                                    {channelSurfaceNextActionIcon(channelSurfaceNextAction)}
                                    {channelSurfaceNextAction.buttonLabel}
                                </Button>
                            </div>
                            <div className="line-clamp-2 text-muted-foreground">
                                {channelSurfaceNextAction.detail}
                            </div>
                        </div>
                    )}
                    <div className="space-y-1.5">
                        {channelSurfaceRows.map(row => (
                            <button
                                key={row.type}
                                type="button"
                                disabled={Boolean(creatingSurfaceType)}
                                data-channel-surface-row={row.type}
                                className={[
                                    'w-full rounded-md border px-2 py-1.5 text-left text-xs transition-colors',
                                    row.channel?.channelKey === selectedKey ? 'border-primary bg-primary/5' : 'bg-background hover:bg-muted/40',
                                    creatingSurfaceType ? 'opacity-80' : '',
                                ].join(' ')}
                                onClick={() => {
                                    if (row.channel) {
                                        selectChannel(row.channel.channelKey);
                                    } else {
                                        void createChannelSurfaceSetup(row);
                                    }
                                }}
                            >
                                <div className="mb-1 flex items-center justify-between gap-2">
                                    <span className="truncate font-medium">{t(row.label)}</span>
                                    <Badge variant={row.ready ? 'secondary' : row.channel ? 'outline' : 'destructive'} className="font-normal">
                                        {creatingSurfaceType === row.type ? t('Adding') : row.ready ? t('Ready') : row.channel ? t('Needs setup') : t('Missing')}
                                    </Badge>
                                </div>
                                <div className="flex flex-wrap gap-1">
                                    <Badge variant={row.everyMessage ? 'secondary' : 'outline'} className="font-normal">
                                        {row.everyMessage ? t('New ticket per message') : t('Thread updates')}
                                    </Badge>
                                    <Badge variant={row.inboundReady ? 'secondary' : 'outline'} className="font-normal">
                                        {t('Inbound')}
                                    </Badge>
                                    <Badge variant={row.outboundReady ? 'secondary' : 'outline'} className="font-normal">
                                        {t('Outbound')}
                                    </Badge>
                                    <Badge variant={row.autoDraft ? 'secondary' : 'outline'} className="font-normal">
                                        {t('AI draft')}
                                    </Badge>
                                    <Badge variant={row.ownerRouting ? 'secondary' : 'outline'} className="font-normal">
                                        {t('Default owner')}
                                    </Badge>
                                    {row.launchRequired && (
                                        <Badge variant={row.launchReady ? 'secondary' : 'outline'} className="font-normal">
                                            {t('Launch')}
                                        </Badge>
                                    )}
                                </div>
                                {row.blockers.length > 0 && (
                                    <div className="mt-1 truncate text-[11px] text-muted-foreground">
                                        {row.blockers.join(' · ')}
                                    </div>
                                )}
                            </button>
                        ))}
                    </div>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto">
                    {loading ? (
                        <div className="flex h-full items-center justify-center text-muted-foreground">
                            <Loader className="mr-2 size-4 animate-spin" />
                            {t('Loading')}
                        </div>
                    ) : channels.length === 0 ? (
                        <div className="flex h-full items-center justify-center text-muted-foreground">{t('No channels')}</div>
                    ) : (
                        channels.map((channel) => {
                            const health = channel.setup?.health;
                            return (
                                <button
                                    key={channel.id}
                                    type="button"
                                    data-channel-row={channel.channelKey}
                                    className={[
                                        'w-full border-b px-4 py-3 text-left transition-colors',
                                        channel.channelKey === selectedKey ? 'bg-muted/60' : 'bg-background hover:bg-muted/40',
                                    ].join(' ')}
                                    onClick={() => selectChannel(channel.channelKey)}
                                >
                                    <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
                                        <span className="truncate text-sm font-medium">{channel.name}</span>
                                        <div className="flex shrink-0 items-center gap-1.5">
                                            {health && (
                                                <Badge variant={setupHealthVariant(health.status)} className="font-normal">
                                                    {t(setupHealthLabel(health.status))}
                                                </Badge>
                                            )}
                                            <Badge variant="outline" className="font-normal">{channel.status}</Badge>
                                        </div>
                                    </div>
                                    <div className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
                                        <Hash className="size-3.5 shrink-0" />
                                        <span>{channel.type}</span>
                                        <span className="truncate">{channel.channelKey}</span>
                                    </div>
                                    {health && (
                                        <div className="mt-2 flex flex-wrap gap-1.5">
                                            <Badge variant={health.inboundReady ? 'secondary' : 'destructive'} className="font-normal">
                                                {health.inboundReady ? t('Inbound') : t('No inbound')}
                                            </Badge>
                                            <Badge variant={health.outboundReady ? 'secondary' : 'outline'} className="font-normal">
                                                {health.outboundReady ? t('Outbound') : t('No outbound')}
                                            </Badge>
                                            {health.envMissing > 0 && (
                                                <Badge variant="outline" className="font-normal">
                                                    {health.envMissing} {t('env missing')}
                                                </Badge>
                                            )}
                                            {channel.setup?.launch?.required && (
                                                <Badge variant={channel.setup.launch.ready ? 'secondary' : 'outline'} className="font-normal">
                                                    {channel.setup.launch.passed}/{channel.setup.launch.checks} {t('launch')}
                                                </Badge>
                                            )}
                                        </div>
                                    )}
                                </button>
                            );
                        })
                    )}
                </div>
            </aside>

            <section className="min-w-0 flex-1 overflow-y-auto">
                <div className="mx-auto max-w-3xl space-y-4 px-6 py-5">
                    <div className="flex items-start justify-between gap-3">
                        <div>
                            <h1 className="text-xl font-semibold">{selectedChannel ? selectedChannel.name : t('Add channel')}</h1>
                            {selectedChannel && (
                                <p className="text-sm text-muted-foreground">{formatTime(selectedChannel.lastSyncAt)}</p>
                            )}
                        </div>
                        {selectedChannel && (
                            <Button
                                type="button"
                                variant="outline"
                                onClick={() => void syncSelected()}
                                disabled={Boolean(syncingChannel)}
                            >
                                {syncingChannel === selectedChannel.id
                                    ? <Loader className="size-4 animate-spin" />
                                    : <RefreshCw className="size-4" />}
                                {t('Sync inbound')}
                            </Button>
                        )}
                    </div>
                    {selectedPreset && (
                        <section className="rounded-md border bg-muted/20 p-3">
                            <div className="mb-3 flex items-center justify-between gap-3">
                                <div className="flex min-w-0 items-center gap-2">
                                    <Badge variant="outline" className="font-normal">{t('Preset')}</Badge>
                                    <span className="truncate text-sm font-medium">{selectedPreset.providerName}</span>
                                </div>
                                <Button type="button" size="sm" variant="outline" onClick={() => applyChannelPreset(selectedPreset)}>
                                    <CheckCircle2 className="size-4" />
                                    {t('Apply preset')}
                                </Button>
                            </div>
                            <div className="mb-3 flex flex-wrap gap-1.5">
                                <Badge variant="secondary" className="font-normal">
                                    {presetTicketCreationMode(selectedPreset.ticketCreationMode) === 'per_message'
                                        ? t('New message = new ticket')
                                        : t('Thread updates')}
                                </Badge>
                                {presetSupportSteps(selectedPreset).map(step => (
                                    <Badge key={step} variant="secondary" className="font-normal">
                                        {t(presetSupportStepLabel(step))}
                                    </Badge>
                                ))}
                                {selectedPreset.supportDefaults?.humanReview !== false && (
                                    <Badge variant="outline" className="font-normal">{t('Human review')}</Badge>
                                )}
                            </div>
                            <div className="grid gap-2 md:grid-cols-2">
                                <div className="rounded-md border bg-background p-2">
                                    <div className="mb-1 text-xs font-medium">{t('Auth env')}</div>
                                    <div className="flex flex-wrap gap-1.5">
                                        {selectedPreset.authEnvVars.length === 0 ? (
                                            <span className="text-xs text-muted-foreground">-</span>
                                        ) : selectedPreset.authEnvVars.map(env => (
                                            <Badge key={`${env.name}:${env.purpose}`} variant={env.required ? 'secondary' : 'outline'} className="font-mono font-normal">
                                                {env.name}
                                            </Badge>
                                        ))}
                                    </div>
                                </div>
                                <div className="rounded-md border bg-background p-2">
                                    <div className="mb-1 text-xs font-medium">{t('Outbound env')}</div>
                                    <div className="flex flex-wrap gap-1.5">
                                        {selectedPreset.outboundEnvVars.length === 0 ? (
                                            <span className="text-xs text-muted-foreground">-</span>
                                        ) : selectedPreset.outboundEnvVars.map(env => (
                                            <Badge key={`${env.name}:${env.purpose}`} variant={env.required ? 'secondary' : 'outline'} className="font-mono font-normal">
                                                {env.name}
                                            </Badge>
                                        ))}
                                    </div>
                                </div>
                            </div>
                        </section>
                    )}
                    {selectedChannel && (
                        <section
                            className="rounded-md border bg-muted/20 p-3"
                            data-channel-support-mode
                            data-channel-support-mode-ready={selectedSupportModeReady ? 'true' : 'false'}
                            data-channel-ticket-mode={ticketCreationMode}
                        >
                            <div className="flex flex-wrap items-start justify-between gap-3">
                                <div className="min-w-0">
                                    <h2 className="text-sm font-medium">{t('Support mode')}</h2>
                                    <div className="mt-1 flex flex-wrap gap-1.5">
                                        <Badge
                                            variant={ticketCreationMode === 'per_message' ? 'secondary' : 'destructive'}
                                            className="font-normal"
                                            data-channel-ticket-mode={ticketCreationMode}
                                        >
                                            {ticketCreationMode === 'per_message' ? t('New message = ticket') : t('Thread updates')}
                                        </Badge>
                                        <Badge
                                            variant={selectedSupportModeReady ? 'secondary' : 'outline'}
                                            className="font-normal"
                                            data-channel-support-mode-ready={selectedSupportModeReady ? 'true' : 'false'}
                                        >
                                            {selectedSupportModeReady ? t('Ready') : `${selectedSupportModeMissing.length} ${t('open')}`}
                                        </Badge>
                                    </div>
                                </div>
                                <Button
                                    type="button"
                                    size="sm"
                                    variant={selectedSupportModeReady ? 'outline' : 'default'}
                                    disabled={saving || selectedSupportModeReady}
                                    data-channel-enable-support-mode
                                    onClick={() => void runLaunchProof('support_mode')}
                                >
                                    {saving
                                        ? <Loader className="size-4 animate-spin" />
                                        : <CheckCircle2 className="size-4" />}
                                    {selectedSupportModeReady ? t('Enabled') : t('Enable support mode')}
                                </Button>
                            </div>
                            <div className="mt-3 grid gap-2 sm:grid-cols-3">
                                {selectedSupportModeSteps.map(step => (
                                    <div
                                        key={step.key}
                                        className="flex min-w-0 items-center gap-2 rounded-md border bg-background px-2 py-1.5 text-xs"
                                        data-channel-support-mode-step={step.key}
                                        data-channel-support-mode-step-ready={step.ready ? 'true' : 'false'}
                                    >
                                        {step.ready
                                            ? <CheckCircle2 className="size-3.5 shrink-0 text-emerald-600" />
                                            : <AlertTriangle className="size-3.5 shrink-0 text-amber-600" />}
                                        <span className="truncate">{step.label}</span>
                                    </div>
                                ))}
                            </div>
                        </section>
                    )}
                    <div className="grid gap-3 sm:grid-cols-4">
                        <div className="space-y-1.5">
                            <Label>{t('Type')}</Label>
                            <Select value={type} onValueChange={setType}>
                                <SelectTrigger>
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="email">{t('Email')}</SelectItem>
                                    <SelectItem value="slack">Slack</SelectItem>
                                    <SelectItem value="teams">Teams</SelectItem>
                                    <SelectItem value="discord">Discord</SelectItem>
                                    <SelectItem value="telegram">Telegram</SelectItem>
                                    <SelectItem value="line">LINE</SelectItem>
                                    <SelectItem value="viber">Viber</SelectItem>
                                    <SelectItem value="whatsapp">WhatsApp</SelectItem>
                                    <SelectItem value="messenger">Messenger</SelectItem>
                                    <SelectItem value="instagram">Instagram DM</SelectItem>
                                    <SelectItem value="twitter">X DM</SelectItem>
                                    <SelectItem value="sms">SMS</SelectItem>
                                    <SelectItem value="chat">{t('Chat')}</SelectItem>
                                    <SelectItem value="webhook">Webhook</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="space-y-1.5">
                            <Label>{t('Ticket creation')}</Label>
                            <Select value={ticketCreationMode} onValueChange={value => setTicketCreationMode(value as TicketCreationMode)}>
                                <SelectTrigger>
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="per_message">{t('New ticket per message')}</SelectItem>
                                    <SelectItem value="per_thread">{t('Thread updates')}</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="space-y-1.5">
                            <Label>{t('Outbound payload')}</Label>
                            <Select value={outboundPayloadMode} onValueChange={value => setOutboundPayloadMode(value as OutboundPayloadMode)}>
                                <SelectTrigger>
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="provider">{t('Provider')}</SelectItem>
                                    <SelectItem value="generic">{t('Generic adapter')}</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="space-y-1.5">
                            <Label>{t('AI triage')}</Label>
                            <div className="flex h-9 items-center rounded-md border px-3" data-channel-autopilot-policy data-channel-autopilot-triage={autoPrepareTriage ? 'true' : 'false'}>
                                <Switch checked={autoPrepareTriage} onCheckedChange={setAutoPrepareTriage} />
                            </div>
                        </div>
                        <div className="space-y-1.5">
                            <Label>{t('AI fields')}</Label>
                            <div className="flex h-9 items-center rounded-md border px-3" data-channel-autopilot-fields={autoPrepareCustomFields ? 'true' : 'false'}>
                                <Switch checked={autoPrepareCustomFields} onCheckedChange={setAutoPrepareCustomFields} />
                            </div>
                        </div>
                        <div className="space-y-1.5">
                            <Label>{t('AI draft')}</Label>
                            <div className="flex h-9 items-center rounded-md border px-3" data-channel-autopilot-draft={autoPrepareAgentReply ? 'true' : 'false'}>
                                <Switch checked={autoPrepareAgentReply} onCheckedChange={setAutoPrepareAgentReply} />
                            </div>
                        </div>
                        <div className="space-y-1.5">
                            <Label>{t('AI follow-up')}</Label>
                            <div className="flex h-9 items-center rounded-md border px-3" data-channel-autopilot-updates={autoPrepareAgentReplyOnUpdate ? 'true' : 'false'}>
                                <Switch checked={autoPrepareAgentReplyOnUpdate} onCheckedChange={setAutoPrepareAgentReplyOnUpdate} />
                            </div>
                        </div>
                        <div className="space-y-1.5">
                            <Label>{t('Queue safe replies')}</Label>
                            <div className="flex h-9 items-center rounded-md border px-3" data-channel-autopilot-auto-send={agentAutoSend ? 'true' : 'false'}>
                                <Switch checked={agentAutoSend} onCheckedChange={setAgentAutoSend} />
                            </div>
                        </div>
                        <div className="space-y-1.5">
                            <Label>{t('CSAT link')}</Label>
                            <div className="flex h-9 items-center rounded-md border px-3">
                                <Switch checked={includeFeedbackLink} onCheckedChange={setIncludeFeedbackLink} />
                            </div>
                        </div>
                        <div className="space-y-1.5">
                            <Label>{t('Status')}</Label>
                            <Select value={status} onValueChange={setStatus}>
                                <SelectTrigger>
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="active">{t('Active')}</SelectItem>
                                    <SelectItem value="paused">{t('Paused')}</SelectItem>
                                    <SelectItem value="disabled">{t('Disabled')}</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="channel-key">{t('Key')}</Label>
                            <Input id="channel-key" value={channelKey} onChange={event => setChannelKey(event.target.value)} />
                        </div>
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="channel-name">{t('Name')}</Label>
                        <Input id="channel-name" value={name} onChange={event => setName(event.target.value)} />
                    </div>
                    <section className="rounded-md border p-3" data-channel-owner-routing>
                        <div className="mb-3 flex items-center justify-between gap-2">
                            <div className="text-sm font-medium">{t('Default owner')}</div>
                            <Badge variant={routingPreview.ready ? 'secondary' : 'outline'} className="font-normal">
                                {t(routingPreview.status)}
                            </Badge>
                        </div>
                        <div className="grid gap-3 lg:grid-cols-2">
                            <div className="space-y-1.5">
                                <Label htmlFor="channel-default-assignee">{t('Default assignee')}</Label>
                                <Input
                                    id="channel-default-assignee"
                                    type="email"
                                    value={defaultAssigneeEmail}
                                    onChange={event => setDefaultAssigneeEmail(event.target.value)}
                                    placeholder="agent@example.com"
                                />
                            </div>
                            <div className="space-y-1.5">
                                <Label>{t('Default queue')}</Label>
                                <Select
                                    value={defaultQueueKey.trim() || NO_DEFAULT_QUEUE_VALUE}
                                    onValueChange={(value) => {
                                        if (value === NO_DEFAULT_QUEUE_VALUE) {
                                            setDefaultQueueKey('');
                                            setDefaultQueueName('');
                                            return;
                                        }
                                        const queue = supportQueues.find(item => item.queueKey === value);
                                        setDefaultQueueKey(value);
                                        setDefaultQueueName(queue?.name || value);
                                    }}
                                >
                                    <SelectTrigger id="channel-default-queue-key">
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value={NO_DEFAULT_QUEUE_VALUE}>{t('No queue')}</SelectItem>
                                        {defaultQueueKey.trim() && !selectedDefaultQueue && (
                                            <SelectItem value={defaultQueueKey.trim()}>
                                                {defaultQueueName.trim() || defaultQueueKey.trim()}
                                            </SelectItem>
                                        )}
                                        {supportQueues.map(queue => (
                                            <SelectItem key={queue.queueKey} value={queue.queueKey}>
                                                {queue.name || queue.queueKey}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                        </div>
                        <div className="mt-3 grid gap-2 text-xs text-muted-foreground sm:grid-cols-3">
                            <div className="rounded-md border bg-muted/20 p-2">
                                <div className="mb-1 text-foreground">{t('Queue')}</div>
                                <div className="truncate">{routingPreview.queue}</div>
                            </div>
                            <div className="rounded-md border bg-muted/20 p-2">
                                <div className="mb-1 text-foreground">{t('Assignee')}</div>
                                <div className="truncate">{routingPreview.assignment}</div>
                            </div>
                            <div className="rounded-md border bg-muted/20 p-2">
                                <div className="mb-1 text-foreground">{t('Rule')}</div>
                                <div className="truncate" title={routingPreview.detail}>{t(routingPreview.detail)}</div>
                            </div>
                        </div>
                    </section>
                    <div className="space-y-1.5">
                        <Label htmlFor="channel-agent-question">{t('Agent instruction')}</Label>
                        <Textarea
                            id="channel-agent-question"
                            value={agentQuestion}
                            onChange={event => setAgentQuestion(event.target.value)}
                            rows={3}
                            placeholder={t('Draft an approval-ready response from this channel message and cite relevant knowledge.')}
                        />
                    </div>
                    <div className="rounded-md border p-3">
                        <div className="mb-3 flex items-center justify-between gap-2">
                            <div className="text-sm font-medium">{t('Inbound auth')}</div>
                            <Badge variant={webhookTokenEnv || signatureSecretEnv ? 'secondary' : 'outline'} className="font-normal">
                                {webhookTokenEnv || signatureSecretEnv ? t('Configured') : t('Default')}
                            </Badge>
                        </div>
                        <div className="grid gap-3 lg:grid-cols-3">
                            <div className="space-y-1.5">
                                <Label htmlFor="channel-webhook-token-env">{t('Token key')}</Label>
                                <Input
                                    id="channel-webhook-token-env"
                                    value={webhookTokenEnv}
                                    onChange={event => setWebhookTokenEnv(event.target.value)}
                                    placeholder={defaultWebhookTokenEnv(type)}
                                />
                            </div>
                            <div className="space-y-1.5">
                                <Label htmlFor="channel-signature-secret-env">{t('Signature key')}</Label>
                                <Input
                                    id="channel-signature-secret-env"
                                    value={signatureSecretEnv}
                                    onChange={event => setSignatureSecretEnv(event.target.value)}
                                    placeholder={defaultSignatureSecretEnv(type, channelKey)}
                                />
                            </div>
                            {type !== 'slack' && (
                                <div className="space-y-1.5">
                                    <Label htmlFor="channel-signature-header">{t('Signature header')}</Label>
                                    <Input
                                        id="channel-signature-header"
                                        value={signatureHeader}
                                        onChange={event => setSignatureHeader(event.target.value)}
                                        placeholder={defaultSignatureHeader(type)}
                                    />
                                </div>
                            )}
                        </div>
                    </div>
                    <div className="rounded-md border p-3">
                        <div className="mb-3 flex items-center justify-between gap-2">
                            <div className="text-sm font-medium">{t('Outbound replies')}</div>
                            <Badge
                                variant={outboundTransport === 'bot' || outboundTransport === 'provider_api' || outboundWebhookUrl || outboundWebhookUrlEnv ? 'secondary' : 'outline'}
                                className="font-normal"
                            >
                                {outboundTransport === 'bot'
                                    ? t('Native bot')
                                    : outboundTransport === 'provider_api'
                                        ? t('Provider API')
                                    : outboundWebhookUrl || outboundWebhookUrlEnv ? t('Configured') : t('Not configured')}
                            </Badge>
                        </div>
                        <div className="grid gap-3 lg:grid-cols-3">
                            {(nativeBotSupported(type) || providerApiOutboundSupported(type)) && (
                                <div className="space-y-1.5">
                                    <Label htmlFor="channel-outbound-transport">{t('Transport')}</Label>
                                    <Select
                                        value={outboundTransport || '__automatic__'}
                                        onValueChange={value => setOutboundTransport(value === '__automatic__' ? '' : value as OutboundTransport)}
                                    >
                                        <SelectTrigger id="channel-outbound-transport">
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="__automatic__">{t(outboundTransportLabel(''))}</SelectItem>
                                            {nativeBotSupported(type) && (
                                                <SelectItem value="bot">{t('Native bot')}</SelectItem>
                                            )}
                                            {providerApiOutboundSupported(type) && (
                                                <SelectItem value="provider_api">{t('Provider API')}</SelectItem>
                                            )}
                                            <SelectItem value="webhook">{t('Webhook adapter')}</SelectItem>
                                        </SelectContent>
                                    </Select>
                                </div>
                            )}
                            {outboundTransport === 'bot' && type !== 'teams' && (
                                <div className="space-y-1.5 lg:col-span-2">
                                    <Label htmlFor="channel-outbound-bot-token-env">{t('Bot token env')}</Label>
                                    <Input
                                        id="channel-outbound-bot-token-env"
                                        value={outboundBotTokenEnv}
                                        onChange={event => setOutboundBotTokenEnv(event.target.value)}
                                        placeholder={defaultBotTokenEnv(type)}
                                    />
                                </div>
                            )}
                            {outboundTransport === 'bot' && type === 'teams' && (
                                <>
                                    <div className="space-y-1.5">
                                        <Label htmlFor="channel-teams-app-id-env">{t('Teams app ID env')}</Label>
                                        <Input
                                            id="channel-teams-app-id-env"
                                            value={teamsAppIdEnv}
                                            onChange={event => setTeamsAppIdEnv(event.target.value)}
                                            placeholder={defaultTeamsAppIdEnv()}
                                        />
                                    </div>
                                    <div className="space-y-1.5">
                                        <Label htmlFor="channel-teams-app-password-env">{t('Teams app password env')}</Label>
                                        <Input
                                            id="channel-teams-app-password-env"
                                            value={teamsAppPasswordEnv}
                                            onChange={event => setTeamsAppPasswordEnv(event.target.value)}
                                            placeholder={defaultTeamsAppPasswordEnv()}
                                        />
                                    </div>
                                </>
                            )}
                            {usesWebhookOutbound(outboundTransport) && (
                                <>
                                    <div className="space-y-1.5 lg:col-span-2">
                                        <Label htmlFor="channel-outbound-webhook-url">{t('Webhook URL')}</Label>
                                        <Input
                                            id="channel-outbound-webhook-url"
                                            value={outboundWebhookUrl}
                                            onChange={event => setOutboundWebhookUrl(event.target.value)}
                                            placeholder="https://adapter.example.com/support/reply"
                                        />
                                    </div>
                                    <div className="space-y-1.5">
                                        <Label htmlFor="channel-outbound-webhook-url-env">{t('URL env')}</Label>
                                        <Input
                                            id="channel-outbound-webhook-url-env"
                                            value={outboundWebhookUrlEnv}
                                            onChange={event => setOutboundWebhookUrlEnv(event.target.value)}
                                            placeholder="SUPPORT_OUTBOUND_WEBHOOK_URL"
                                        />
                                    </div>
                                </>
                            )}
                            <div className="space-y-1.5">
                                <Label htmlFor="channel-outbound-webhook-token-env">{t('Token env')}</Label>
                                <Input
                                    id="channel-outbound-webhook-token-env"
                                    value={outboundWebhookTokenEnv}
                                    onChange={event => setOutboundWebhookTokenEnv(event.target.value)}
                                    placeholder={defaultOutboundTokenEnv(type)}
                                    disabled={!usesOutboundTokenEnv(outboundTransport, type)}
                                />
                            </div>
                        </div>
                    </div>
                    {supportsProviderLifecycle(type) && (
                        <div
                            className="rounded-md border p-3"
                            data-channel-live-target-proof
                            data-channel-live-target-provider={type}
                            data-channel-live-target-required={liveProofRequired ? 'true' : 'false'}
                            data-channel-live-target-ready={liveProofConfigured ? 'true' : 'false'}
                            data-channel-live-target-missing={missingLiveProofTargets.join(',')}
                        >
                            <div className="mb-3 flex items-center justify-between gap-2">
                                <div className="text-sm font-medium">{t('Live proof target')}</div>
                                <Badge variant={liveProofConfigured ? 'secondary' : liveProofRequired ? 'destructive' : 'outline'} className="font-normal">
                                    {liveProofConfigured ? t('Configured') : liveProofRequired ? t('Required') : t('Optional')}
                                </Badge>
                            </div>
                                <div className="grid gap-3 lg:grid-cols-3">
                                    {usesLiveProofPrimaryTarget(type) && (
                                        <div className="space-y-1.5">
                                        <Label htmlFor="channel-smoke-channel-id">
                                            {type === 'telegram' ? t('Chat ID') : t('Channel ID')}
                                        </Label>
                                        <Input
                                            id="channel-smoke-channel-id"
                                            value={smokeTargetChannelId}
                                            onChange={event => setSmokeTargetChannelId(event.target.value)}
                                            placeholder={type === 'slack' ? 'C0123456789' : type === 'telegram' ? '123456789' : 'channel-id'}
                                        />
                                    </div>
                                )}
                                {usesLiveProofThreadTarget(type) && (
                                    <div className="space-y-1.5">
                                        <Label htmlFor="channel-smoke-thread-id">
                                            {type === 'slack' ? t('Thread TS') : t('Thread ID')}
                                        </Label>
                                        <Input
                                            id="channel-smoke-thread-id"
                                            value={smokeTargetThreadId}
                                            onChange={event => setSmokeTargetThreadId(event.target.value)}
                                            placeholder={type === 'slack' ? '1710000000.000100' : 'thread-id'}
                                        />
                                    </div>
                                )}
                                {usesLiveProofRecipientTarget(type) && (
                                    <div className="space-y-1.5">
                                        <Label htmlFor="channel-smoke-to-address">
                                            {type === 'whatsapp'
                                                ? t('Recipient phone')
                                                : type === 'messenger'
                                                    ? t('Messenger PSID')
                                                    : type === 'viber'
                                                        ? t('Viber subscriber ID')
                                                        : type === 'line'
                                                            ? t('LINE user/group/room ID')
                                                            : type === 'instagram'
                                                                ? t('Instagram scoped user ID')
                                                                : type === 'twitter'
                                                                    ? t('X user ID')
                                                                    : t('Recipient number')}
                                        </Label>
                                        <Input
                                            id="channel-smoke-to-address"
                                            value={smokeTargetToAddress}
                                            onChange={event => setSmokeTargetToAddress(event.target.value)}
                                            placeholder={type === 'whatsapp'
                                                ? '4915112345678'
                                                : type === 'messenger'
                                                    ? 'customer-psid'
                                                    : type === 'viber'
                                                        ? 'viber-user-id'
                                                        : type === 'line'
                                                            ? 'line-user-id'
                                                            : type === 'instagram'
                                                                ? 'instagram-scoped-user-id'
                                                                : type === 'twitter'
                                                                    ? 'x-user-id'
                                                                    : '+14155550123'}
                                        />
                                    </div>
                                )}
                                {type === 'teams' && (
                                    <>
                                        <div className="space-y-1.5 lg:col-span-3">
                                            <Label htmlFor="channel-smoke-service-url">{t('Service URL')}</Label>
                                            <Input
                                                id="channel-smoke-service-url"
                                                value={smokeTargetServiceUrl}
                                                onChange={event => setSmokeTargetServiceUrl(event.target.value)}
                                                placeholder="https://smba.trafficmanager.net/emea/"
                                            />
                                        </div>
                                        <div className="space-y-1.5">
                                            <Label htmlFor="channel-smoke-conversation-id">{t('Conversation ID')}</Label>
                                            <Input
                                                id="channel-smoke-conversation-id"
                                                value={smokeTargetConversationId}
                                                onChange={event => setSmokeTargetConversationId(event.target.value)}
                                                placeholder="conversation-id"
                                            />
                                        </div>
                                        <div className="space-y-1.5">
                                            <Label htmlFor="channel-smoke-reply-to-id">{t('Reply activity')}</Label>
                                            <Input
                                                id="channel-smoke-reply-to-id"
                                                value={smokeTargetReplyToId}
                                                onChange={event => setSmokeTargetReplyToId(event.target.value)}
                                                placeholder="activity-id"
                                            />
                                        </div>
                                    </>
                                    )}
                                </div>
                                {liveProofTargetRows.length > 0 && (
                                    <div
                                        data-live-proof-target-summary
                                        className="mt-3 rounded-md border bg-muted/20 p-2 text-xs"
                                    >
                                        <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
                                            <div className="min-w-0 font-medium">{t('Required target')}</div>
                                            <Badge
                                                variant={liveProofConfigured ? 'secondary' : liveProofRequired ? 'destructive' : 'outline'}
                                                className="font-normal"
                                            >
                                                {configuredLiveProofTargetRows.length}/{requiredLiveProofTargetRows.length || liveProofTargetRows.length}
                                            </Badge>
                                        </div>
                                        <div className="grid gap-2 lg:grid-cols-2">
                                            {liveProofTargetRows.map(row => (
                                                <div
                                                    key={row.key}
                                                    data-channel-live-target-field
                                                    data-channel-live-target-field-key={row.key}
                                                    data-channel-live-target-field-required={row.required ? 'true' : 'false'}
                                                    data-channel-live-target-field-ready={row.configured ? 'true' : 'false'}
                                                    data-live-proof-target-row
                                                    data-live-proof-target-key={row.key}
                                                    className="rounded-md border bg-background p-2"
                                                >
                                                    <div className="mb-1 flex min-w-0 items-center justify-between gap-2">
                                                        <span className="truncate font-medium">{t(row.label)}</span>
                                                        <Badge
                                                            variant={row.configured ? 'secondary' : row.required ? 'destructive' : 'outline'}
                                                            className="font-normal"
                                                        >
                                                            {row.configured ? t('Set') : row.required ? t('Missing') : t('Optional')}
                                                        </Badge>
                                                    </div>
                                                    <div className="mb-1 truncate text-muted-foreground">
                                                        {t('Config')}: <code>{row.configKey}</code>
                                                    </div>
                                                    <div className="flex min-w-0 items-center justify-between gap-2">
                                                        <span className="min-w-0 truncate text-muted-foreground">
                                                            {row.value.trim() || '-'}
                                                        </span>
                                                        <Button
                                                            type="button"
                                                            size="sm"
                                                            variant="outline"
                                                            className="h-7 shrink-0 px-2"
                                                            onClick={() => void copyValue(row.copyValue)}
                                                        >
                                                            <Copy className="size-3.5" />
                                                            {t('Copy key')}
                                                        </Button>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}
                    <div className="space-y-1.5">
                        <Label htmlFor="channel-config">{t('Config')}</Label>
                        <Textarea id="channel-config" value={configJson} onChange={event => setConfigJson(event.target.value)} rows={12} />
                    </div>
                    {selectedChannel?.setup && (
                        <section className="rounded-md border p-4">
                            <div className="mb-3 flex items-center justify-between gap-2">
                                <div>
                                    <h2 className="text-sm font-medium">{selectedChannel.setup.providerName || t('Setup')}</h2>
                                    <p className="text-xs text-muted-foreground">{selectedChannel.type}</p>
                                </div>
                                <div className="flex items-center gap-2">
                                    {selectedChannel.setup.health && (
                                        <Badge variant={setupHealthVariant(selectedChannel.setup.health.status)} className="font-normal">
                                            {t(setupHealthLabel(selectedChannel.setup.health.status))}
                                        </Badge>
                                    )}
                                    <Badge variant={selectedChannel.setup.inboundReady ? 'secondary' : 'destructive'} className="font-normal">
                                        {selectedChannel.setup.inboundReady ? t('Inbound ready') : t('Needs setup')}
                                    </Badge>
                                    {selectedChannel.type === 'slack' && (
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            onClick={() => void installSlack()}
                                            disabled={installingSlack}
                                        >
                                            {installingSlack ? <Loader className="size-4 animate-spin" /> : <ExternalLink className="size-4" />}
                                            {t('Install Slack')}
                                        </Button>
                                    )}
                                    {selectedChannel.type === 'telegram' && (
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            onClick={() => void setTelegramWebhook()}
                                            disabled={settingTelegramWebhook}
                                        >
                                            {settingTelegramWebhook ? <Loader className="size-4 animate-spin" /> : <Send className="size-4" />}
                                            {t('Set Telegram webhook')}
                                        </Button>
                                    )}
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant="outline"
                                        onClick={() => void validateSelectedChannel()}
                                        disabled={validatingSetup === selectedChannel.id}
                                    >
                                        {validatingSetup === selectedChannel.id
                                            ? <Loader className="size-4 animate-spin" />
                                            : <CheckCircle2 className="size-4" />}
                                        {t('Validate setup')}
                                    </Button>
                                </div>
                            </div>
                            <div className="space-y-3">
                                {selectedChannel.setup.health && (
                                    <div className="grid gap-2 rounded-md border bg-muted/20 p-3 text-xs sm:grid-cols-4">
                                        <div>
                                            <div className="font-medium">{selectedChannel.setup.health.checks}</div>
                                            <div className="text-muted-foreground">{t('checks')}</div>
                                        </div>
                                        <div>
                                            <div className="font-medium">{selectedChannel.setup.health.missing}</div>
                                            <div className="text-muted-foreground">{t('missing')}</div>
                                        </div>
                                        <div>
                                            <div className="font-medium">{selectedChannel.setup.health.warnings}</div>
                                            <div className="text-muted-foreground">{t('warnings')}</div>
                                        </div>
                                        <div>
                                            <div className="font-medium">
                                                {selectedChannel.setup.health.envConfigured}/{selectedChannel.setup.health.envTotal}
                                            </div>
                                            <div className="text-muted-foreground">{t('env set')}</div>
                                        </div>
                                        {(selectedChannel.setup.health.requiredMissingEnvVars ?? []).length > 0 && (
                                            <div className="min-w-0 sm:col-span-4">
                                                <div className="mb-1 font-medium text-destructive">{t('Required env missing')}</div>
                                                <div className="truncate text-muted-foreground">
                                                    {(selectedChannel.setup.health.requiredMissingEnvVars ?? []).join(', ')}
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                )}
                                {(selectedChannel.setup.launchPlaybook ?? []).length > 0 && (
                                    <div className="rounded-md border bg-muted/20 p-3">
                                        <div className="mb-3 flex items-center justify-between gap-2">
                                            <div className="text-xs font-medium">{t('Launch playbook')}</div>
                                            <Badge variant="outline" className="font-normal">
                                                {(selectedChannel.setup.launchPlaybook ?? []).filter(step => step.status === 'done').length}/{(selectedChannel.setup.launchPlaybook ?? []).length}
                                            </Badge>
                                        </div>
                                        <div className="grid gap-2 lg:grid-cols-2">
                                            {(selectedChannel.setup.launchPlaybook ?? []).map(step => {
                                                const hasAction = Boolean(step.action || step.runAction);
                                                return (
                                                    <div key={step.key} className="flex min-w-0 items-start gap-2 rounded-md border bg-background p-2 text-xs">
                                                        <div className="mt-0.5 shrink-0">{setupStatusIcon(step.status)}</div>
                                                        <div className="min-w-0 flex-1">
                                                            <div className="mb-1 flex min-w-0 items-center gap-2">
                                                                <span className="truncate font-medium">{t(textValue(step.label, step.key))}</span>
                                                                <Badge variant={setupStatusVariant(step.status)} className="font-normal">
                                                                    {t(setupStatusLabel(step.status))}
                                                                </Badge>
                                                            </div>
                                                            <div className="line-clamp-2 text-muted-foreground">
                                                                {t(textValue(step.detail))}
                                                            </div>
                                                            {step.copyLabel && (
                                                                <div className="mt-1 truncate text-[11px] text-muted-foreground">
                                                                    {t(step.copyLabel)}: {step.copyValue || '-'}
                                                                </div>
                                                            )}
                                                            {step.smokeCommand && (
                                                                <div className="mt-2 flex min-w-0 items-center gap-2 rounded-md border bg-muted/30 px-2 py-1 font-mono text-[11px] text-muted-foreground">
                                                                    <span className="truncate">{step.smokeCommand}</span>
                                                                    <Button
                                                                        type="button"
                                                                        size="sm"
                                                                        variant="ghost"
                                                                        className="h-6 shrink-0 px-1.5"
                                                                        data-channel-smoke-command-copy
                                                                        onClick={() => void copyValue(step.smokeCommand || '')}
                                                                    >
                                                                        <Copy className="size-3.5" />
                                                                    </Button>
                                                                </div>
                                                            )}
                                                        </div>
                                                        {hasAction && (
                                                            <Button
                                                                type="button"
                                                                size="sm"
                                                                variant="outline"
                                                                className="h-7 shrink-0 px-2"
                                                                onClick={() => void runPlaybookStep(step)}
                                                                disabled={!canRunPlaybookStep(step)}
                                                            >
                                                                {playbookActionIcon(step)}
                                                                {playbookActionLabel(step)}
                                                            </Button>
                                                        )}
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    </div>
                                )}
                                {(selectedChannel.setup.setupChecklist ?? []).length > 0 && (
                                    <div className="grid gap-2 lg:grid-cols-5">
                                        {(selectedChannel.setup.setupChecklist ?? []).map(step => (
                                            <div key={step.key} className="min-w-0 rounded-md border bg-muted/20 p-2">
                                                <div className="mb-2 flex items-center justify-between gap-2">
                                                    <div className="flex min-w-0 items-center gap-1.5">
                                                        {setupStatusIcon(step.status)}
                                                        <span className="truncate text-xs font-medium">{t(textValue(step.label, step.key))}</span>
                                                    </div>
                                                    <Badge variant={setupStatusVariant(step.status)} className="font-normal">
                                                        {t(setupStatusLabel(step.status))}
                                                    </Badge>
                                                </div>
                                                {step.detail && (
                                                    <div className="truncate text-xs text-muted-foreground">{t(textValue(step.detail))}</div>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                )}
                                {selectedChannel.setup.launch?.required && (
                                    <div className="rounded-md border bg-muted/20 p-3">
                                        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                                            <div>
                                                <div className="text-xs font-medium uppercase text-muted-foreground">{t('Launch proof')}</div>
                                                <div className="mt-1 text-sm font-medium">
                                                    {selectedChannel.setup.launch.passed}/{selectedChannel.setup.launch.checks} {t('passed')}
                                                </div>
                                            </div>
                                            <div className="flex flex-wrap items-center gap-2">
                                                <Button
                                                    type="button"
                                                    size="sm"
                                                    variant="outline"
                                                    data-channel-launch-proof-copy
                                                    onClick={() => void copyLaunchProofBundle()}
                                                >
                                                    <Copy className="size-3.5" />
                                                    {t('Copy proof')}
                                                </Button>
                                                <Badge variant={selectedChannel.setup.launch.ready ? 'secondary' : 'outline'} className="font-normal">
                                                    {selectedChannel.setup.launch.ready ? t('Ready') : t('Needs smoke')}
                                                </Badge>
                                            </div>
                                        </div>
                                            {liveProofEvidence.length > 0 && (
                                                <div
                                                    data-live-proof-evidence
                                                    className="mb-3 rounded-md border bg-background p-2"
                                                >
                                                    <div className="mb-2 flex min-w-0 items-center justify-between gap-2 text-xs">
                                                        <span className="font-medium">{t('Proof evidence')}</span>
                                                        <Badge variant="outline" className="font-normal">
                                                            {liveProofEvidence.filter(step => step.status === 'done').length}/{liveProofEvidence.length}
                                                        </Badge>
                                                    </div>
                                                    <div className="grid gap-2 lg:grid-cols-2">
                                                        {liveProofEvidence.map(step => (
                                                            <div
                                                                key={step.key}
                                                                data-live-proof-evidence-row
                                                                data-live-proof-evidence-key={step.key}
                                                                className="min-w-0 rounded-md border bg-muted/20 p-2 text-xs"
                                                            >
                                                                <div className="mb-1 flex min-w-0 items-center justify-between gap-2">
                                                                    <span className="truncate font-medium">{t(textValue(step.label, step.key))}</span>
                                                                    <Badge variant={setupStatusVariant(step.status)} className="font-normal">
                                                                        {t(setupStatusLabel(step.status))}
                                                                    </Badge>
                                                                </div>
                                                                <div className="line-clamp-2 text-muted-foreground">
                                                                    {step.detail ? t(textValue(step.detail)) : '-'}
                                                                </div>
                                                                {(step.runId || step.issueId || step.replyId || step.aiRunId || step.approvedBy || step.providerMessageId) && (
                                                                    <div className="mt-1 flex min-w-0 flex-wrap gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
                                                                        {step.runId && <span className="truncate">{step.transport || step.source || step.runStatus}</span>}
                                                                        {step.issueId && <span className="truncate">{t('Ticket')}: {step.issueId}</span>}
                                                                        {step.replyId && <span className="truncate">{t('Reply')}: {step.replyId}</span>}
                                                                        {step.aiRunId && <span className="truncate">{t('AI')}: {step.aiRunId}</span>}
                                                                        {step.approvedBy && <span className="truncate">{t('Approved')}: {step.approvedBy}</span>}
                                                                        {step.approvedAt && <span className="truncate">{step.approvedAt}</span>}
                                                                        {step.inboundProviderMessageId && <span className="truncate">{t('Inbound')}: {step.inboundProviderMessageId}</span>}
                                                                        {step.providerMessageId && <span className="truncate">{t('Provider')}: {step.providerMessageId}</span>}
                                                                    </div>
                                                                )}
                                                            </div>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}
                                            {(selectedChannel.setup.launch.blockers ?? []).length > 0 && (
                                                <div className="mb-3 grid gap-1.5">
                                                {(selectedChannel.setup.launch.blockers ?? []).map(blocker => {
                                                    const action = blocker.action || blocker.key;
                                                    const configFix = isLaunchConfigFix(action);
                                                    const running = launchProofRunning(action);
                                                    const targeted = Boolean(requestedLaunchAction && (requestedLaunchAction === action || requestedLaunchAction === blocker.key));
                                                    let actionIcon = <RefreshCw className="size-3.5" />;
                                                    if (configFix) actionIcon = <Save className="size-3.5" />;
                                                    if (running) actionIcon = <Loader className="size-3.5 animate-spin" />;
                                                    return (
                                                        <div
                                                            key={blocker.key}
                                                            className={[
                                                                'flex min-w-0 items-center gap-2 rounded-md border px-2 py-1.5 text-xs',
                                                                targeted ? 'border-primary bg-primary/5' : 'bg-background',
                                                            ].join(' ')}
                                                        >
                                                            {setupStatusIcon(blocker.status)}
                                                            <span className="shrink-0 font-medium">{t(textValue(blocker.label, blocker.key || 'Launch blocker'))}</span>
                                                            <span className="min-w-0 truncate text-muted-foreground">{t(textValue(blocker.detail || blocker.status))}</span>
                                                            <Button
                                                                type="button"
                                                                size="sm"
                                                                variant="outline"
                                                                className="ml-auto h-7 shrink-0 px-2 text-xs"
                                                                onClick={() => void runLaunchProof(action)}
                                                                disabled={!canRunLaunchProof(action) || running}
                                                            >
                                                                {actionIcon}
                                                                {configFix ? t('Fix') : t('Run')}
                                                            </Button>
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        )}
                                        <div className="grid gap-2 lg:grid-cols-3">
                                            {(selectedChannel.setup.launchChecklist ?? selectedChannel.setup.launch.checklist ?? []).map(step => (
                                                <div key={step.key} className="min-w-0 rounded-md border bg-background p-2">
                                                    <div className="mb-2 flex items-center justify-between gap-2">
                                                        <div className="flex min-w-0 items-center gap-1.5">
                                                            {setupStatusIcon(step.status)}
                                                            <span className="truncate text-xs font-medium">{t(textValue(step.label, step.key))}</span>
                                                        </div>
                                                        <Badge variant={setupStatusVariant(step.status)} className="font-normal">
                                                            {t(setupStatusLabel(step.status))}
                                                        </Badge>
                                                    </div>
                                                    <div className="truncate text-xs text-muted-foreground">
                                                        {step.detail ? t(textValue(step.detail)) : '-'}
                                                    </div>
                                                    {(step.issueId || step.replyId || step.providerMessageId) && (
                                                        <div className="mt-1 flex min-w-0 flex-wrap gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
                                                            {step.issueId && (
                                                                <span className="min-w-0 truncate">
                                                                    {t('Ticket')}: {step.issueId}
                                                                </span>
                                                            )}
                                                            {step.replyId && (
                                                                <span className="min-w-0 truncate">
                                                                    {t('Reply')}: {step.replyId}
                                                                </span>
                                                            )}
                                                            {step.providerMessageId && (
                                                                <span className="min-w-0 truncate">
                                                                    {t('Provider message')}: {step.providerMessageId}
                                                                </span>
                                                            )}
                                                        </div>
                                                    )}
                                                    {step.runId && (
                                                        <div className="mt-1 flex min-w-0 items-center justify-between gap-2 text-[11px] text-muted-foreground">
                                                            <span className="truncate">
                                                                {[step.transport ? step.transport.toUpperCase() : '', step.source || step.runStatus]
                                                                    .filter(Boolean)
                                                                    .join(' · ')}
                                                            </span>
                                                            <span className="shrink-0">{formatTime(step.startedAt)}</span>
                                                        </div>
                                                    )}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                                {setupValidation && setupValidation.channelId === selectedChannel.id && (
                                    <div className="rounded-md border bg-muted/20 p-3">
                                        <div className="mb-2 flex items-center justify-between gap-2">
                                            <div className="text-xs font-medium">{t('Last validation')}</div>
                                            <Badge variant={setupValidation.ready ? 'secondary' : 'destructive'} className="font-normal">
                                                {setupValidation.ready ? t('Ready') : t('Needs setup')}
                                            </Badge>
                                        </div>
                                        <div className="grid gap-2 text-xs sm:grid-cols-5">
                                            <div>
                                                <div className="font-medium">{setupValidation.summary.checks}</div>
                                                <div className="text-muted-foreground">{t('checks')}</div>
                                            </div>
                                            <div>
                                                <div className="font-medium">{setupValidation.summary.missing}</div>
                                                <div className="text-muted-foreground">{t('missing')}</div>
                                            </div>
                                            <div>
                                                <div className="font-medium">{setupValidation.summary.warnings}</div>
                                                <div className="text-muted-foreground">{t('warnings')}</div>
                                            </div>
                                            <div>
                                                <div className="font-medium">{setupValidation.summary.envConfigured}</div>
                                                <div className="text-muted-foreground">{t('env set')}</div>
                                            </div>
                                            <div>
                                                <div className="font-medium">{formatTime(setupValidation.checkedAt)}</div>
                                                <div className="text-muted-foreground">{t('checked')}</div>
                                            </div>
                                        </div>
                                        {setupValidation.providerValidation && (
                                            <div className="mt-3 rounded-md border bg-background p-2">
                                                <div className="mb-1 flex min-w-0 items-center justify-between gap-2">
                                                    <div className="truncate text-xs font-medium">
                                                        {t('Provider credentials')} · {setupValidation.providerValidation.provider}
                                                    </div>
                                                    <Badge
                                                        variant={
                                                            setupValidation.providerValidation.status === 'ready'
                                                                ? 'secondary'
                                                                : setupValidation.providerValidation.status === 'failed'
                                                                    ? 'destructive'
                                                                    : 'outline'
                                                        }
                                                        className="font-normal"
                                                    >
                                                        {setupValidation.providerValidation.status}
                                                    </Badge>
                                                </div>
                                                <div className="truncate text-xs text-muted-foreground">
                                                    {setupValidation.providerValidation.detail}
                                                </div>
                                                {(setupValidation.providerValidation.envVars ?? []).length > 0 && (
                                                    <div className="mt-1 truncate text-xs text-muted-foreground">
                                                        {t('Required env')}: {(setupValidation.providerValidation.envVars ?? []).join(', ')}
                                                    </div>
                                                )}
                                                {setupValidation.providerValidation.identity && Object.keys(setupValidation.providerValidation.identity).length > 0 && (
                                                    <div className="mt-1 truncate text-xs text-muted-foreground">
                                                        {Object.entries(setupValidation.providerValidation.identity)
                                                            .map(([key, value]) => `${key}: ${String(value)}`)
                                                            .join(' · ')}
                                                    </div>
                                                )}
                                            </div>
                                        )}
                                        {remediationList(setupValidation.remediation)}
                                    </div>
                                )}
                                <div className="space-y-1.5">
                                    <Label>{t('Inbound webhook')}</Label>
                                    <div className="flex min-w-0 items-center gap-2">
                                        <code className="min-w-0 flex-1 truncate rounded border bg-muted/40 px-2 py-1.5 text-xs">
                                            {selectedChannel.setup.inboundWebhookUrl}
                                        </code>
                                        {copyButton(selectedChannel.setup.inboundWebhookUrl)}
                                    </div>
                                </div>
                                {selectedChannel.setup.providerWebhookUrl && (
                                    <div className="space-y-1.5">
                                        <Label>{t('Provider webhook')}</Label>
                                        <div className="flex min-w-0 items-center gap-2">
                                            <code className="min-w-0 flex-1 truncate rounded border bg-muted/40 px-2 py-1.5 text-xs">
                                                {selectedChannel.setup.providerWebhookUrl}
                                            </code>
                                            {copyButton(selectedChannel.setup.providerWebhookUrl)}
                                        </div>
                                    </div>
                                )}
                                {selectedChannel.setup.smsWebhookUrl && (
                                    <div className="space-y-1.5">
                                        <Label>{t('SMS webhook')}</Label>
                                        <div className="flex min-w-0 items-center gap-2">
                                            <code className="min-w-0 flex-1 truncate rounded border bg-muted/40 px-2 py-1.5 text-xs">
                                                {selectedChannel.setup.smsWebhookUrl}
                                            </code>
                                            {copyButton(selectedChannel.setup.smsWebhookUrl)}
                                        </div>
                                    </div>
                                )}
                                {selectedChannel.setup.webChatUrl && (
                                    <div className="space-y-1.5">
                                        <Label>{t('Web chat')}</Label>
                                        <div className="flex min-w-0 items-center gap-2">
                                            <code className="min-w-0 flex-1 truncate rounded border bg-muted/40 px-2 py-1.5 text-xs">
                                                {selectedChannel.setup.webChatUrl}
                                            </code>
                                            {copyButton(selectedChannel.setup.webChatUrl)}
                                        </div>
                                    </div>
                                )}
                                {selectedChannel.setup.webChatEmbedScriptUrl && (
                                    <div className="space-y-1.5">
                                        <Label>{t('Web chat script')}</Label>
                                        <div className="flex min-w-0 items-center gap-2">
                                            <code className="min-w-0 flex-1 truncate rounded border bg-muted/40 px-2 py-1.5 text-xs">
                                                {selectedChannel.setup.webChatEmbedScriptUrl}
                                            </code>
                                            {copyButton(selectedChannel.setup.webChatEmbedScriptUrl)}
                                        </div>
                                    </div>
                                )}
                                {selectedChannel.setup.webChatEmbedSnippet && (
                                    <div className="space-y-1.5">
                                        <Label>{t('Web chat snippet')}</Label>
                                        <div className="flex min-w-0 items-center gap-2">
                                            <code className="min-w-0 flex-1 truncate rounded border bg-muted/40 px-2 py-1.5 text-xs">
                                                {selectedChannel.setup.webChatEmbedSnippet}
                                            </code>
                                            {copyButton(selectedChannel.setup.webChatEmbedSnippet)}
                                        </div>
                                    </div>
                                )}
                                {(selectedChannel.setup.providerSteps ?? []).length > 0 && (
                                    <div className="rounded-md border bg-muted/20 p-3">
                                        <div className="mb-2 text-xs font-medium">{t('Install steps')}</div>
                                        <ol className="space-y-1 text-xs text-muted-foreground">
                                            {(selectedChannel.setup.providerSteps ?? []).map((step, index) => (
                                                <li key={`${index}:${step}`} className="flex gap-2">
                                                    <span className="shrink-0 tabular-nums">{index + 1}.</span>
                                                    <span>{t(step)}</span>
                                                </li>
                                            ))}
                                        </ol>
                                    </div>
                                )}
                                {selectedChannel.setup.slackManifest && (
                                    <div className="space-y-1.5">
                                        <div className="flex items-center justify-between gap-2">
                                            <Label>{t('Slack app manifest')}</Label>
                                            {copyButton(JSON.stringify(selectedChannel.setup.slackManifest, null, 2))}
                                        </div>
                                        <pre className="max-h-56 overflow-auto rounded-md border bg-muted/20 p-2 text-xs">
                                            {JSON.stringify(selectedChannel.setup.slackManifest, null, 2)}
                                        </pre>
                                    </div>
                                )}
                                {selectedChannel.setup.teamsBridgeConfig && (
                                    <div className="space-y-1.5">
                                        <div className="flex items-center justify-between gap-2">
                                            <Label>{t('Teams bridge config')}</Label>
                                            {copyButton(JSON.stringify(selectedChannel.setup.teamsBridgeConfig, null, 2))}
                                        </div>
                                        <pre className="max-h-56 overflow-auto rounded-md border bg-muted/20 p-2 text-xs">
                                            {JSON.stringify(selectedChannel.setup.teamsBridgeConfig, null, 2)}
                                        </pre>
                                    </div>
                                )}
                                {selectedChannel.setup.discordBridgeConfig && (
                                    <div className="space-y-1.5">
                                        <div className="flex items-center justify-between gap-2">
                                            <Label>{t('Discord bridge config')}</Label>
                                            {copyButton(JSON.stringify(selectedChannel.setup.discordBridgeConfig, null, 2))}
                                        </div>
                                        <pre className="max-h-56 overflow-auto rounded-md border bg-muted/20 p-2 text-xs">
                                            {JSON.stringify(selectedChannel.setup.discordBridgeConfig, null, 2)}
                                        </pre>
                                    </div>
                                )}
                                {selectedChannel.setup.metaBridgeConfig && (
                                    <div className="space-y-1.5">
                                        <div className="flex items-center justify-between gap-2">
                                            <Label>{t('Meta bridge config')}</Label>
                                            {copyButton(JSON.stringify(selectedChannel.setup.metaBridgeConfig, null, 2))}
                                        </div>
                                        <pre className="max-h-56 overflow-auto rounded-md border bg-muted/20 p-2 text-xs">
                                            {JSON.stringify(selectedChannel.setup.metaBridgeConfig, null, 2)}
                                        </pre>
                                    </div>
                                )}
                                {selectedChannel.setup.telegramWebhookConfig && (
                                    <div className="space-y-1.5">
                                        <div className="flex items-center justify-between gap-2">
                                            <Label>{t('Telegram webhook config')}</Label>
                                            {copyButton(JSON.stringify(selectedChannel.setup.telegramWebhookConfig, null, 2))}
                                        </div>
                                        <pre className="max-h-56 overflow-auto rounded-md border bg-muted/20 p-2 text-xs">
                                            {JSON.stringify(selectedChannel.setup.telegramWebhookConfig, null, 2)}
                                        </pre>
                                    </div>
                                )}
                                {selectedChannel.setup.lineWebhookConfig && (
                                    <div className="space-y-1.5">
                                        <div className="flex items-center justify-between gap-2">
                                            <Label>{t('LINE webhook config')}</Label>
                                            {copyButton(JSON.stringify(selectedChannel.setup.lineWebhookConfig, null, 2))}
                                        </div>
                                        <pre className="max-h-56 overflow-auto rounded-md border bg-muted/20 p-2 text-xs">
                                            {JSON.stringify(selectedChannel.setup.lineWebhookConfig, null, 2)}
                                        </pre>
                                    </div>
                                )}
                                {selectedChannel.setup.viberWebhookConfig && (
                                    <div className="space-y-1.5">
                                        <div className="flex items-center justify-between gap-2">
                                            <Label>{t('Viber webhook config')}</Label>
                                            {copyButton(JSON.stringify(selectedChannel.setup.viberWebhookConfig, null, 2))}
                                        </div>
                                        <pre className="max-h-56 overflow-auto rounded-md border bg-muted/20 p-2 text-xs">
                                            {JSON.stringify(selectedChannel.setup.viberWebhookConfig, null, 2)}
                                        </pre>
                                    </div>
                                )}
                                {selectedChannel.setup.whatsappWebhookConfig && (
                                    <div className="space-y-1.5">
                                        <div className="flex items-center justify-between gap-2">
                                            <Label>{t('WhatsApp webhook config')}</Label>
                                            {copyButton(JSON.stringify(selectedChannel.setup.whatsappWebhookConfig, null, 2))}
                                        </div>
                                        <pre className="max-h-56 overflow-auto rounded-md border bg-muted/20 p-2 text-xs">
                                            {JSON.stringify(selectedChannel.setup.whatsappWebhookConfig, null, 2)}
                                        </pre>
                                    </div>
                                )}
                                {selectedChannel.setup.messengerWebhookConfig && (
                                    <div className="space-y-1.5">
                                        <div className="flex items-center justify-between gap-2">
                                            <Label>{t('Messenger webhook config')}</Label>
                                            {copyButton(JSON.stringify(selectedChannel.setup.messengerWebhookConfig, null, 2))}
                                        </div>
                                        <pre className="max-h-56 overflow-auto rounded-md border bg-muted/20 p-2 text-xs">
                                            {JSON.stringify(selectedChannel.setup.messengerWebhookConfig, null, 2)}
                                        </pre>
                                    </div>
                                )}
                                {selectedChannel.setup.instagramWebhookConfig && (
                                    <div className="space-y-1.5">
                                        <div className="flex items-center justify-between gap-2">
                                            <Label>{t('Instagram webhook config')}</Label>
                                            {copyButton(JSON.stringify(selectedChannel.setup.instagramWebhookConfig, null, 2))}
                                        </div>
                                        <pre className="max-h-56 overflow-auto rounded-md border bg-muted/20 p-2 text-xs">
                                            {JSON.stringify(selectedChannel.setup.instagramWebhookConfig, null, 2)}
                                        </pre>
                                    </div>
                                )}
                                {selectedChannel.setup.twitterWebhookConfig && (
                                    <div className="space-y-1.5">
                                        <div className="flex items-center justify-between gap-2">
                                            <Label>{t('X webhook config')}</Label>
                                            {copyButton(JSON.stringify(selectedChannel.setup.twitterWebhookConfig, null, 2))}
                                        </div>
                                        <pre className="max-h-56 overflow-auto rounded-md border bg-muted/20 p-2 text-xs">
                                            {JSON.stringify(selectedChannel.setup.twitterWebhookConfig, null, 2)}
                                        </pre>
                                    </div>
                                )}
                                {selectedChannel.setup.twitterBridgeConfig && (
                                    <div className="space-y-1.5">
                                        <div className="flex items-center justify-between gap-2">
                                            <Label>{t('X bridge config')}</Label>
                                            {copyButton(JSON.stringify(selectedChannel.setup.twitterBridgeConfig, null, 2))}
                                        </div>
                                        <pre className="max-h-56 overflow-auto rounded-md border bg-muted/20 p-2 text-xs">
                                            {JSON.stringify(selectedChannel.setup.twitterBridgeConfig, null, 2)}
                                        </pre>
                                    </div>
                                )}
                                {selectedChannel.setup.twilioWebhookConfig && (
                                    <div className="space-y-1.5">
                                        <div className="flex items-center justify-between gap-2">
                                            <Label>{t('Twilio webhook config')}</Label>
                                            {copyButton(JSON.stringify(selectedChannel.setup.twilioWebhookConfig, null, 2))}
                                        </div>
                                        <pre className="max-h-56 overflow-auto rounded-md border bg-muted/20 p-2 text-xs">
                                            {JSON.stringify(selectedChannel.setup.twilioWebhookConfig, null, 2)}
                                        </pre>
                                    </div>
                                )}
                                {selectedChannel.setup.installPackage && (
                                    <div className="space-y-1.5">
                                        <div className="flex items-center justify-between gap-2">
                                            <Label>{t('Install package')}</Label>
                                            {copyButton(JSON.stringify(selectedChannel.setup.installPackage, null, 2))}
                                        </div>
                                        <pre className="max-h-56 overflow-auto rounded-md border bg-muted/20 p-2 text-xs">
                                            {JSON.stringify(selectedChannel.setup.installPackage, null, 2)}
                                        </pre>
                                    </div>
                                )}
                                {(selectedChannel.setup.envVars ?? []).length > 0 && (
                                    <div className="rounded-md border bg-muted/20 p-3">
                                        <div className="mb-2 flex items-center justify-between gap-2">
                                            <div className="text-xs font-medium">{t('Environment')}</div>
                                            <Badge variant="outline" className="font-normal">
                                                {(selectedChannel.setup.envVars ?? []).filter(env => env.configured).length}/{(selectedChannel.setup.envVars ?? []).length}
                                            </Badge>
                                        </div>
                                        <div className="space-y-2">
                                            {(selectedChannel.setup.envVars ?? []).map(env => (
                                                <div key={`${env.name}:${env.purpose}`} className="grid gap-2 rounded border bg-background p-2 text-xs sm:grid-cols-[minmax(0,1fr)_auto]">
                                                    <div className="min-w-0">
                                                        <div className="truncate font-mono">{env.name}</div>
                                                        <div className="truncate text-muted-foreground">{t(textValue(env.purpose))}</div>
                                                    </div>
                                                    <div className="flex items-center gap-2">
                                                        {env.required && <Badge variant="outline" className="font-normal">{t('Required')}</Badge>}
                                                        <Badge variant={env.configured ? 'secondary' : 'outline'} className="font-normal">
                                                            {env.configured ? t('Set') : t('Unset')}
                                                        </Badge>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                                <div className="grid gap-2 sm:grid-cols-2">
                                    <div className="rounded-md border bg-muted/20 p-2 text-xs">
                                        <div className="mb-1 font-medium">{t('Auth')}</div>
                                        <div className={selectedChannel.setup.authConfigured ? 'text-emerald-600' : 'text-destructive'}>
                                            {selectedChannel.setup.authConfigured ? t('Configured') : t('Not configured')}
                                        </div>
                                        <div className="text-muted-foreground">{selectedChannel.setup.tokenHeader}</div>
                                        <div className="text-muted-foreground">{selectedChannel.setup.providerTokenEnv || selectedChannel.setup.tokenEnv}</div>
                                        {selectedChannel.setup.signatureEnv && (
                                            <div className="text-muted-foreground">{selectedChannel.setup.signatureEnv}</div>
                                        )}
                                        {selectedChannel.setup.signatureHeader && (
                                            <div className="text-muted-foreground">{selectedChannel.setup.signatureHeader}</div>
                                        )}
                                        {selectedChannel.setup.signatureConfigKey && (
                                            <div className="text-muted-foreground">{selectedChannel.setup.signatureConfigKey}</div>
                                        )}
                                        {selectedChannel.setup.providerSecretHeader && (
                                            <div className="text-muted-foreground">{selectedChannel.setup.providerSecretHeader}</div>
                                        )}
                                        {selectedChannel.setup.providerSecretEnv && (
                                            <div className="text-muted-foreground">{selectedChannel.setup.providerSecretEnv}</div>
                                        )}
                                        {selectedChannel.setup.providerSignatureConfigKey && (
                                            <div className="text-muted-foreground">{selectedChannel.setup.providerSignatureConfigKey}</div>
                                        )}
                                        {selectedChannel.setup.signatureTimestampHeader && (
                                            <div className="text-muted-foreground">{selectedChannel.setup.signatureTimestampHeader}</div>
                                        )}
                                        {selectedChannel.setup.signatureTimestampRequired && (
                                            <div className="text-muted-foreground">
                                                {t('Replay protected')} · {selectedChannel.setup.signatureToleranceSeconds ?? 300}s
                                            </div>
                                        )}
                                        <div className="text-muted-foreground">{selectedChannel.setup.fallbackTokenEnv}</div>
                                    </div>
                                    <div className="rounded-md border bg-muted/20 p-2 text-xs">
                                        <div className="mb-1 font-medium">{t('Outbound')}</div>
                                        <div className={selectedChannel.setup.outboundReady ? 'text-emerald-600' : 'text-muted-foreground'}>
                                            {selectedChannel.setup.outboundReady
                                                ? t('Ready')
                                                : selectedChannel.setup.outboundTransport === 'bot'
                                                    ? t('Missing credentials')
                                                    : selectedChannel.setup.outboundWebhookConfigured ? t('Configured') : t('Not configured')}
                                        </div>
                                        {selectedChannel.setup.outboundTransport && (
                                            <div className="font-medium text-muted-foreground">
                                                {t(outboundTransportLabel(selectedChannel.setup.outboundTransport))}
                                            </div>
                                        )}
                                        {selectedChannel.setup.outboundWebhookUrl && (
                                            <div className="truncate text-muted-foreground">{selectedChannel.setup.outboundWebhookUrl}</div>
                                        )}
                                        {selectedChannel.setup.outboundWebhookUrlEnv && (
                                            <div className="text-muted-foreground">{selectedChannel.setup.outboundWebhookUrlEnv}</div>
                                        )}
                                        {selectedChannel.setup.outboundWebhookUrlTemplate && (
                                            <div className="truncate text-muted-foreground">{selectedChannel.setup.outboundWebhookUrlTemplate}</div>
                                        )}
                                        {selectedChannel.setup.outboundWebhookTokenEnv && (
                                            <div className="text-muted-foreground">{selectedChannel.setup.outboundWebhookTokenEnv}</div>
                                        )}
                                        {selectedChannel.setup.outboundBotTokenEnv && (
                                            <div className="text-muted-foreground">
                                                {t('Bot token')}: {selectedChannel.setup.outboundBotTokenEnv}
                                            </div>
                                        )}
                                        {(selectedChannel.setup.outboundBotCredentialEnvVars ?? []).length > 0 && (
                                            <div className="text-muted-foreground">
                                                {t('Bot credentials')}: {(selectedChannel.setup.outboundBotCredentialEnvVars ?? []).join(', ')}
                                            </div>
                                        )}
                                        {selectedChannel.setup.outboundTokenRequired && (
                                            <div className="text-muted-foreground">{t('Token required')}</div>
                                        )}
                                        {(selectedChannel.setup.outboundConfigKeys ?? []).map(key => (
                                            <div key={key} className="text-muted-foreground">{key}</div>
                                        ))}
                                    </div>
                                    <div className="rounded-md border bg-muted/20 p-2 text-xs">
                                        <div className="mb-1 font-medium">{t('Ticketing')}</div>
                                        <div className="text-muted-foreground">{selectedChannel.setup.ticketCreationConfigKey}</div>
                                        <div className="text-muted-foreground">{selectedChannel.setup.ticketCreationMode}</div>
                                    </div>
                                    <div className="rounded-md border bg-muted/20 p-2 text-xs">
                                        <div className="mb-1 font-medium">{t('AI prep')}</div>
                                        {(selectedChannel.setup.autoPrepareConfigKeys ?? []).map(key => (
                                            <div key={key} className="text-muted-foreground">{key}</div>
                                        ))}
                                        <div className="text-muted-foreground">
                                            {selectedChannel.setup.autoPrepareTriage ? t('AI triage') : t('Manual triage')}
                                        </div>
                                        <div className="text-muted-foreground">
                                            {selectedChannel.setup.autoPrepareCustomFields ? t('AI fields') : t('Manual fields')}
                                        </div>
                                        <div className="text-muted-foreground">
                                            {selectedChannel.setup.autoPrepareAgentReply ? t('AI draft') : t('Manual prep')}
                                        </div>
                                        <div className="text-muted-foreground">
                                            {selectedChannel.setup.autoPrepareAgentReplyOnUpdate ? t('AI follow-up') : t('Manual follow-up')}
                                        </div>
                                        <div className="text-muted-foreground">
                                            {selectedChannel.setup.agentAutoSend ? t('Queue safe replies') : t('Approval required')}
                                        </div>
                                    </div>
                                </div>
                                <div className="grid gap-2 lg:grid-cols-2">
                                    <div className="space-y-1.5">
                                        <div className="flex items-center justify-between gap-2">
                                            <Label>{t('Message payload')}</Label>
                                            {copyButton(JSON.stringify(selectedChannel.setup.messagePayloadExample, null, 2))}
                                        </div>
                                        <pre className="max-h-40 overflow-auto rounded-md border bg-muted/20 p-2 text-xs">
                                            {JSON.stringify(selectedChannel.setup.messagePayloadExample, null, 2)}
                                        </pre>
                                    </div>
                                    <div className="space-y-1.5">
                                        <div className="flex items-center justify-between gap-2">
                                            <Label>{t('Receipt payload')}</Label>
                                            {copyButton(JSON.stringify(selectedChannel.setup.receiptPayloadExample, null, 2))}
                                        </div>
                                        <pre className="max-h-40 overflow-auto rounded-md border bg-muted/20 p-2 text-xs">
                                            {JSON.stringify(selectedChannel.setup.receiptPayloadExample, null, 2)}
                                        </pre>
                                    </div>
                                </div>
                            </div>
                        </section>
                    )}
                    {selectedChannel && (
                        <section className="rounded-md border p-4">
                            <div className="mb-3 flex items-center justify-between gap-3">
                                <h2 className="text-sm font-medium">{t('Test inbound message')}</h2>
                                <div className="flex flex-wrap items-center justify-end gap-2">
                                    <Button
                                        type="button"
                                        variant="outline"
                                        size="sm"
                                        onClick={() => void runSmoke('http')}
                                        disabled={Boolean(smokingChannel) || !testMessageBody.trim()}
                                    >
                                        {smokingChannel === `${selectedChannel.id}:http`
                                            ? <Loader className="size-4 animate-spin" />
                                            : <ExternalLink className="size-4" />}
                                        {t('HTTP smoke')}
                                    </Button>
                                    <Button
                                        type="button"
                                        variant="outline"
                                        size="sm"
                                        onClick={() => void runSmoke('direct')}
                                        disabled={Boolean(smokingChannel) || !testMessageBody.trim()}
                                    >
                                        {smokingChannel === `${selectedChannel.id}:direct`
                                            ? <Loader className="size-4 animate-spin" />
                                            : <CheckCircle2 className="size-4" />}
                                        {t('Direct smoke')}
                                    </Button>
                                    <Button
                                        type="button"
                                        variant="outline"
                                        size="sm"
                                        onClick={() => void runTestMessage()}
                                        disabled={Boolean(testingChannel) || !testMessageBody.trim()}
                                    >
                                        {testingChannel === selectedChannel.id
                                            ? <Loader className="size-4 animate-spin" />
                                            : <Send className="size-4" />}
                                        {t('Send test')}
                                    </Button>
                                </div>
                            </div>
                            <div className="grid gap-3 sm:grid-cols-2">
                                <div className="space-y-1.5">
                                    <Label htmlFor="channel-test-author-name">{t('Name')}</Label>
                                    <Input
                                        id="channel-test-author-name"
                                        value={testAuthorName}
                                        onChange={event => setTestAuthorName(event.target.value)}
                                    />
                                </div>
                                <div className="space-y-1.5">
                                    <Label htmlFor="channel-test-author-email">{t('Email')}</Label>
                                    <Input
                                        id="channel-test-author-email"
                                        type="email"
                                        value={testAuthorEmail}
                                        onChange={event => setTestAuthorEmail(event.target.value)}
                                    />
                                </div>
                            </div>
                            <div className="mt-3 space-y-1.5">
                                <Label htmlFor="channel-test-message">{t('Message')}</Label>
                                <Textarea
                                    id="channel-test-message"
                                    value={testMessageBody}
                                    onChange={event => setTestMessageBody(event.target.value)}
                                    rows={4}
                                />
                            </div>
                            <div className="mt-3 grid gap-3 sm:grid-cols-3">
                                <div className="space-y-1.5">
                                    <Label htmlFor="channel-test-channel-id">{t('Channel ID')}</Label>
                                    <Input
                                        id="channel-test-channel-id"
                                        value={testChannelId}
                                        onChange={event => setTestChannelId(event.target.value)}
                                    />
                                </div>
                                <div className="space-y-1.5">
                                    <Label htmlFor="channel-test-thread-id">{t('Thread ID')}</Label>
                                    <Input
                                        id="channel-test-thread-id"
                                        value={testThreadId}
                                        onChange={event => setTestThreadId(event.target.value)}
                                    />
                                </div>
                                <div className="space-y-1.5">
                                    <Label htmlFor="channel-test-provider-message-id">{t('Provider message')}</Label>
                                    <Input
                                        id="channel-test-provider-message-id"
                                        value={testProviderMessageId}
                                        onChange={event => setTestProviderMessageId(event.target.value)}
                                    />
                                </div>
                            </div>
                            {testMessageResult && (
                                <div className="mt-3 rounded-md border bg-muted/20 p-2 text-sm">
                                    <div className="mb-1 flex items-center justify-between gap-2">
                                        <Badge variant="outline" className="font-normal">{testMessageResult.status}</Badge>
                                        <span className="text-xs text-muted-foreground">
                                            {testMessageResult.processed} {t('processed')} · {testMessageResult.failed} {t('failed')} · {testMessageResult.skipped} {t('skipped')}
                                        </span>
                                    </div>
                                    {(testMessageResult.items ?? []).slice(0, 3).map((item, index) => (
                                        <div key={`${item.eventId || index}`} className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
                                            <span className="shrink-0">{item.kind || item.status || '-'}</span>
                                            <span className="min-w-0 flex-1 truncate">{item.issueId || item.messageId || item.error || item.eventId || '-'}</span>
                                            {item.issueId && tenantId && (
                                                <Button
                                                    type="button"
                                                    size="sm"
                                                    variant="outline"
                                                    className="h-7 shrink-0 px-2 text-xs"
                                                    onClick={() => openTicket(item.issueId || '')}
                                                >
                                                    <ExternalLink className="size-3.5" />
                                                    {t('Open ticket')}
                                                </Button>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            )}
                            {smokeResult && smokeResult.channelId === selectedChannel.id && (
                                <div className="mt-3 rounded-md border bg-muted/20 p-2 text-sm">
                                    <div className="mb-1 flex items-center justify-between gap-2">
                                        <div className="flex min-w-0 items-center gap-2">
                                            <Badge variant={smokeResult.ready ? 'secondary' : 'outline'} className="font-normal">
                                                {smokeResult.ready ? t('Setup ready') : t('Setup needs work')}
                                            </Badge>
                                            <span className="truncate text-xs text-muted-foreground">
                                                {smokeResult.provider} · {smokeResult.transport || 'direct'}
                                                {smokeResult.attachmentCount ? ` · ${smokeResult.attachmentCount} ${t('attachments')}` : ''}
                                                {smokeResult.fileOnly ? ` · ${t('file-only')}` : ''}
                                            </span>
                                        </div>
                                        <span className="text-xs text-muted-foreground">
                                            {smokeResult.processed} {t('processed')} · {smokeResult.failed} {t('failed')} · {smokeResult.skipped} {t('skipped')}
                                        </span>
                                    </div>
                                    <div className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
                                        <span className="shrink-0">{smokeResult.status}</span>
                                        <span className="min-w-0 flex-1 truncate">
                                            {smokeResult.issueId || smokeResult.messageId || smokeResult.eventId}
                                        </span>
                                        {smokeResult.issueId && tenantId && (
                                            <Button
                                                type="button"
                                                size="sm"
                                                variant="outline"
                                                className="h-7 shrink-0 px-2 text-xs"
                                                onClick={() => openTicket(smokeResult.issueId || '')}
                                            >
                                                <ExternalLink className="size-3.5" />
                                                {t('Open ticket')}
                                            </Button>
                                        )}
                                    </div>
                                    {remediationList(smokeResult.remediation)}
                                </div>
                            )}
                            <div className="mt-4 border-t pt-4">
                                <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                                    <h3 className="text-sm font-medium">{t('Test outbound reply')}</h3>
                                    <div className="flex shrink-0 flex-wrap items-center gap-2">
                                        <div className="flex items-center gap-2">
                                            <Switch
                                                id="channel-lifecycle-attachment-only"
                                                checked={lifecycleAttachmentOnly}
                                                onCheckedChange={setLifecycleAttachmentOnly}
                                            />
                                            <Label htmlFor="channel-lifecycle-attachment-only" className="text-xs text-muted-foreground">
                                                {t('Attachment-only')}
                                            </Label>
                                        </div>
                                        <Button
                                            type="button"
                                            variant="outline"
                                            size="sm"
                                            onClick={() => void runOutboundSmoke()}
                                            disabled={
                                                Boolean(smokingOutboundChannel)
                                                || !outboundSmokeBody.trim()
                                                || !selectedChannelSupportsOutboundSmoke
                                            }
                                        >
                                            {smokingOutboundChannel === selectedChannel.id
                                                ? <Loader className="size-4 animate-spin" />
                                                : <Send className="size-4" />}
                                            {t('Send smoke')}
                                        </Button>
                                        <Button
                                            type="button"
                                            variant="outline"
                                            size="sm"
                                            data-channel-run-lifecycle-smoke
                                            onClick={() => void runLifecycleSmoke()}
                                            disabled={
                                                Boolean(smokingLifecycleChannel)
                                                || (!testMessageBody.trim() && !lifecycleAttachmentOnly)
                                                || !outboundSmokeBody.trim()
                                                || !selectedChannelSupportsOutboundSmoke
                                            }
                                        >
                                            {smokingLifecycleChannel === selectedChannel.id
                                                ? <Loader className="size-4 animate-spin" />
                                                : <CheckCircle2 className="size-4" />}
                                            {t('Run lifecycle')}
                                        </Button>
                                    </div>
                                </div>
                                <div className="space-y-1.5">
                                    <Label htmlFor="channel-outbound-smoke-message">{t('Reply')}</Label>
                                    <Textarea
                                        id="channel-outbound-smoke-message"
                                        value={outboundSmokeBody}
                                        onChange={event => setOutboundSmokeBody(event.target.value)}
                                        rows={3}
                                    />
                                </div>
                                {outboundSmokeResult && outboundSmokeResult.channelId === selectedChannel.id && (
                                    <div className="mt-3 rounded-md border bg-muted/20 p-2 text-sm">
                                        <div className="mb-1 flex items-center justify-between gap-2">
                                            <div className="flex min-w-0 items-center gap-2">
                                                <Badge
                                                    variant={
                                                        outboundSmokeResult.sent
                                                            ? 'secondary'
                                                            : outboundSmokeResult.failed ? 'destructive' : 'outline'
                                                    }
                                                    className="font-normal"
                                                >
                                                    {outboundSmokeResult.status}
                                                </Badge>
                                                <span className="truncate text-xs text-muted-foreground">
                                                    {outboundSmokeResult.provider}
                                                </span>
                                            </div>
                                            <span className="shrink-0 text-xs text-muted-foreground">
                                                {outboundSmokeResult.ready ? t('Setup ready') : t('Setup needs work')}
                                            </span>
                                        </div>
                                        <div className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
                                            <span className="shrink-0">{outboundSmokeResult.messageId}</span>
                                            <span className="min-w-0 flex-1 truncate">
                                                {outboundSmokeResult.providerMessageId || outboundSmokeResult.error || '-'}
                                            </span>
                                        </div>
                                        {outboundSmokeResult.error && (
                                            <div className="mt-1 text-xs text-destructive">{outboundSmokeResult.error}</div>
                                        )}
                                        {remediationList(outboundSmokeResult.remediation)}
                                    </div>
                                )}
                                {lifecycleSmokeResult && lifecycleSmokeResult.channelId === selectedChannel.id && (
                                    <div className="mt-3 rounded-md border bg-muted/20 p-2 text-sm">
                                        <div className="mb-1 flex items-center justify-between gap-2">
                                            <div className="flex min-w-0 items-center gap-2">
                                                <Badge
                                                    variant={
                                                        lifecycleSmokeResult.sent
                                                            ? 'secondary'
                                                            : lifecycleSmokeResult.failed ? 'destructive' : 'outline'
                                                    }
                                                    className="font-normal"
                                                >
                                                    {lifecycleSmokeResult.status}
                                                </Badge>
                                                <span className="truncate text-xs text-muted-foreground">
                                                    {lifecycleSmokeResult.provider || lifecycleSmokeResult.type}
                                                    {lifecycleSmokeResult.attachmentCount
                                                        ? ` · ${lifecycleSmokeResult.attachmentCount} ${t('attachments')}`
                                                        : ''}
                                                    {lifecycleSmokeResult.fileOnly ? ` · ${t('file-only')}` : ''}
                                                </span>
                                            </div>
                                            <span className="shrink-0 text-xs text-muted-foreground">
                                                {lifecycleSmokeResult.ready ? t('Setup ready') : t('Setup needs work')}
                                            </span>
                                        </div>
                                        <div className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
                                            <span className="shrink-0">{lifecycleSmokeResult.replyId || lifecycleSmokeResult.messageId}</span>
                                            <span className="min-w-0 flex-1 truncate">
                                                {lifecycleSmokeResult.providerMessageId || lifecycleSmokeResult.error || lifecycleSmokeResult.issueId || '-'}
                                            </span>
                                            {lifecycleSmokeResult.issueId && tenantId && (
                                                <Button
                                                    type="button"
                                                    size="sm"
                                                    variant="outline"
                                                    className="h-7 shrink-0 px-2 text-xs"
                                                    onClick={() => openTicket(lifecycleSmokeResult.issueId)}
                                                >
                                                    <ExternalLink className="size-3.5" />
                                                    {t('Open ticket')}
                                                </Button>
                                            )}
                                        </div>
                                        {lifecycleSmokeResult.error && (
                                            <div className="mt-1 text-xs text-destructive">{lifecycleSmokeResult.error}</div>
                                        )}
                                        {remediationList(lifecycleSmokeResult.remediation)}
                                    </div>
                                )}
                            </div>
                        </section>
                    )}
                    <section className="rounded-md border p-4">
                        <div className="mb-3 flex items-center justify-between gap-2">
                            <h2 className="text-sm font-medium">{t('Current cursors')}</h2>
                            <Badge variant="outline" className="font-normal">{channelCursors.length}</Badge>
                        </div>
                        {channelCursors.length === 0 ? (
                            <div className="text-sm text-muted-foreground">-</div>
                        ) : (
                            <div className="space-y-2">
                                {channelCursors.map(cursor => (
                                    <div key={cursor.id} className="rounded-md border bg-muted/20 p-2 text-sm">
                                        <div className="flex items-center justify-between gap-2">
                                            <div className="flex min-w-0 items-center gap-2">
                                                <Badge
                                                    variant={cursor.lastError ? 'destructive' : cursor.status === 'success' ? 'secondary' : 'outline'}
                                                    className="font-normal"
                                                >
                                                    {cursor.status || t('unknown')}
                                                </Badge>
                                                <span className="truncate font-medium">{cursor.cursorKey || '-'}</span>
                                            </div>
                                            <span className="shrink-0 text-xs text-muted-foreground">{formatTime(cursor.lastSyncedAt)}</span>
                                        </div>
                                        <div className="mt-1 truncate text-xs text-muted-foreground">
                                            {cursor.cursorValue || '-'}
                                        </div>
                                        {cursor.lastError && (
                                            <div className="mt-1 line-clamp-2 text-xs text-destructive">{cursor.lastError}</div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </section>
                    <section className="rounded-md border p-4">
                        <div className="mb-3 flex items-center justify-between gap-2">
                            <h2 className="text-sm font-medium">{t('Sync history')}</h2>
                            <Badge variant="outline" className="font-normal">{syncRuns.length}</Badge>
                        </div>
                        {syncRuns.length === 0 ? (
                            <div className="text-sm text-muted-foreground">-</div>
                        ) : (
                            <div className="space-y-2">
                                {syncRuns.map(run => {
                                    const cursorKey = recordText(run.result, 'cursorKey');
                                    const cursorValue = recordText(run.result, 'cursorValue');
                                    const providerValidation = recordObject(run.result, 'providerValidation');
                                    const proof = recordObject(run.result, 'proof');
                                    const remediation = remediationStepsFrom(run.result?.remediation);
                                    const provider = recordText(providerValidation, 'provider');
                                    const providerStatus = recordText(providerValidation, 'status');
                                    const providerDetail = recordText(providerValidation, 'detail');
                                    const proofKind = recordText(proof, 'kind');
                                    const proofRemediationCount = numberFrom(proof?.remediationCount);
                                    return (
                                        <div key={run.id} className="rounded-md border bg-muted/20 p-2 text-sm">
                                            <div className="flex items-center justify-between gap-2">
                                                <div className="flex min-w-0 items-center gap-2">
                                                    <Badge variant="outline" className="font-normal">{run.status}</Badge>
                                                    <span className="truncate">{run.source || t('Sync')}</span>
                                                </div>
                                                <span className="shrink-0 text-xs text-muted-foreground">{formatTime(run.startedAt)}</span>
                                            </div>
                                            <div className="mt-1 text-xs text-muted-foreground">
                                                {run.processed} {t('processed')} · {run.failed} {t('failed')} · {run.skipped} {t('skipped')}
                                            </div>
                                            {(cursorKey || cursorValue) && (
                                                <div className="mt-1 truncate text-xs text-muted-foreground">
                                                    {t('Cursor')}: {cursorKey || '-'} {cursorValue ? `· ${cursorValue}` : ''}
                                                </div>
                                            )}
                                            {providerValidation && (
                                                <div className="mt-2 rounded-md border bg-background px-2 py-1.5 text-xs">
                                                    <div className="flex flex-wrap items-center gap-2">
                                                        <Badge variant={providerStatus === 'ready' ? 'secondary' : 'outline'} className="font-normal">
                                                            {providerStatus || t('unknown')}
                                                        </Badge>
                                                        <span className="font-medium">{t('Provider validation')}</span>
                                                        <span className="text-muted-foreground">{provider || '-'}</span>
                                                    </div>
                                                    {providerDetail && (
                                                        <div className="mt-1 line-clamp-2 text-muted-foreground">{providerDetail}</div>
                                                    )}
                                                </div>
                                            )}
                                            {proofKind && (
                                                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                                                    <span>{t('Proof')}: {proofKind}</span>
                                                    <span>·</span>
                                                    <span>{proofRemediationCount.toLocaleString()} {t('remediation')}</span>
                                                </div>
                                            )}
                                            {remediationList(remediation)}
                                            {run.error && <div className="mt-1 text-xs text-destructive">{run.error}</div>}
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </section>
                    <section className="rounded-md border p-4">
                        <div className="mb-3 flex items-center justify-between gap-2">
                            <h2 className="text-sm font-medium">{t('Channel webhook inbox')}</h2>
                            <Badge variant="outline" className="font-normal">{channelWebhookEvents.length}</Badge>
                        </div>
                        {channelWebhookEvents.length === 0 ? (
                            <div className="text-sm text-muted-foreground">-</div>
                        ) : (
                            <div className="space-y-2">
                                {channelWebhookEvents.map(event => {
                                    const outboundMessageId = event.outboundMessageId || recordText(event.result, 'outboundMessageId');
                                    const issueId = recordText(event.result, 'issueId');
                                    const isInboundMessage = recordText(event.result, 'kind') === 'inbound_message';
                                    const resolver = resolverProofFrom(event.result);
                                    const resolverAction = recordText(resolver, 'resolverAction');
                                    const resolverMode = recordText(resolver, 'ticketCreationMode');
                                    const resolverTicketKey = recordText(resolver, 'externalTicketKey') || recordText(resolver, 'sourceIssueId');
                                    const resolverMessageKey = recordText(resolver, 'externalMessageKey') || recordText(resolver, 'sourceMessageId');
                                    const canRetryMatch = !isInboundMessage && ['failed', 'received', 'unmatched'].includes(event.status);
                                    const isRematching = rematchingWebhookEvent === event.id;
                                    return (
                                        <div
                                            key={event.id}
                                            className="rounded-md border bg-muted/20 p-2 text-sm"
                                            data-channel-webhook-event={event.id}
                                        >
                                            <div className="flex items-center justify-between gap-2">
                                                <div className="flex min-w-0 items-center gap-2">
                                                    <Badge variant={webhookEventStatusVariant(event.status)} className="font-normal">{event.status}</Badge>
                                                    <span className="truncate">{event.eventType || t('Webhook')}</span>
                                                </div>
                                                <span className="shrink-0 text-xs text-muted-foreground">{formatTime(event.receivedAt)}</span>
                                            </div>
                                            <div className="mt-1 flex min-w-0 gap-2 text-xs text-muted-foreground">
                                                <span>{event.provider || '-'}</span>
                                                <span className="truncate">{event.providerMessageId || event.eventId}</span>
                                            </div>
                                            {outboundMessageId && (
                                                <div className="mt-1 truncate text-xs text-muted-foreground">
                                                    {t('Outbound')}: {outboundMessageId}
                                                </div>
                                            )}
                                            {resolver && (
                                                <div className="mt-2 rounded-md border bg-background/70 p-2 text-xs">
                                                    <div className="flex flex-wrap items-center gap-2">
                                                        <span className="font-medium">{t('Resolver')}</span>
                                                        {resolverAction && <Badge variant="outline" className="font-normal">{resolverAction}</Badge>}
                                                        {resolverMode && <Badge variant="secondary" className="font-normal">{resolverMode}</Badge>}
                                                    </div>
                                                    {resolverTicketKey && (
                                                        <div className="mt-1 truncate text-muted-foreground">
                                                            {t('Ticket key')}: {resolverTicketKey}
                                                        </div>
                                                    )}
                                                    {resolverMessageKey && (
                                                        <div className="mt-1 truncate text-muted-foreground">
                                                            {t('Message key')}: {resolverMessageKey}
                                                        </div>
                                                    )}
                                                </div>
                                            )}
                                            {(canRetryMatch || issueId) && (
                                                <div className="mt-2 flex flex-wrap items-center gap-2">
                                                    {canRetryMatch && (
                                                        <Button
                                                            type="button"
                                                            size="sm"
                                                            variant="outline"
                                                            onClick={() => void retryWebhookMatch(event)}
                                                            disabled={Boolean(rematchingWebhookEvent)}
                                                            data-channel-webhook-retry={event.id}
                                                        >
                                                            {isRematching ? <Loader className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
                                                            {t('Retry match')}
                                                        </Button>
                                                    )}
                                                    {issueId && (
                                                        <Button
                                                            type="button"
                                                            size="sm"
                                                            variant="outline"
                                                            onClick={() => openTicket(issueId)}
                                                            data-channel-webhook-ticket={event.id}
                                                        >
                                                            <ExternalLink className="size-3.5" />
                                                            {t('Ticket')}
                                                        </Button>
                                                    )}
                                                </div>
                                            )}
                                            {event.error && <div className="mt-1 text-xs text-destructive">{event.error}</div>}
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </section>
                    <section className="rounded-md border p-4">
                        <div className="mb-3 flex items-center justify-between gap-2">
                            <h2 className="text-sm font-medium">{t('Web chat sessions')}</h2>
                            <Badge variant="outline" className="font-normal">{webChatSessions.length}</Badge>
                        </div>
                        {webChatSessions.length === 0 ? (
                            <div className="text-sm text-muted-foreground">-</div>
                        ) : (
                            <div className="space-y-2">
                                {webChatSessions.map(session => {
                                    const issueIds = webChatSessionIssueIds(session);
                                    const latestIssueId = webChatSessionLatestIssueId(session);
                                    return (
                                        <div key={session.id} data-web-chat-session={session.id} className="rounded-md border bg-muted/20 p-2 text-sm">
                                            <div className="flex items-center justify-between gap-2">
                                                <div className="flex min-w-0 items-center gap-2">
                                                    <Badge variant="outline" className="font-normal">{session.status}</Badge>
                                                    <span className="truncate">{session.visitorName || session.visitorEmail || session.visitorId || t('Visitor')}</span>
                                                </div>
                                                <span className="shrink-0 text-xs text-muted-foreground">{formatTime(session.lastMessageAt)}</span>
                                            </div>
                                            <div className="mt-1 flex min-w-0 gap-2 text-xs text-muted-foreground">
                                                <span className="truncate">{session.pageUrl || session.sessionKey}</span>
                                            </div>
                                            <div className="mt-2 flex flex-wrap items-center gap-1.5">
                                                <Badge variant="secondary" className="font-normal" data-web-chat-session-ticket-count={session.id}>
                                                    {issueIds.length} {issueIds.length === 1 ? t('ticket') : t('tickets')}
                                                </Badge>
                                                <Badge variant="outline" className="font-normal" data-web-chat-session-message-count={session.id}>
                                                    {session.messageCount || 0} {t('messages')}
                                                </Badge>
                                                {latestIssueId && (
                                                    <Button
                                                        type="button"
                                                        size="sm"
                                                        variant="outline"
                                                        className="h-7 gap-1.5 px-2 text-xs"
                                                        data-web-chat-session-latest-ticket={session.id}
                                                        onClick={() => openTicket(latestIssueId)}
                                                    >
                                                        <ExternalLink className="size-3.5" />
                                                        {t('Latest ticket')}
                                                    </Button>
                                                )}
                                            </div>
                                            {issueIds.length > 0 && (
                                                <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
                                                    {issueIds.slice(0, 4).map(issueId => (
                                                        <Button
                                                            key={issueId}
                                                            type="button"
                                                            size="sm"
                                                            variant="outline"
                                                            className="h-6 max-w-full truncate px-1.5 text-xs font-normal text-muted-foreground hover:text-foreground"
                                                            data-web-chat-session-ticket={issueId}
                                                            onClick={() => openTicket(issueId)}
                                                        >
                                                            {issueId}
                                                        </Button>
                                                    ))}
                                                    {issueIds.length > 4 && (
                                                        <span className="rounded border bg-background px-1.5 py-0.5 text-muted-foreground">
                                                            +{issueIds.length - 4}
                                                        </span>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </section>
                    <section className="rounded-md border p-4">
                        <div className="mb-3 flex items-center justify-between gap-2">
                            <h2 className="text-sm font-medium">{t('Delivery history')}</h2>
                            <Badge variant="outline" className="font-normal">{deliveryRuns.length}</Badge>
                        </div>
                        {deliveryRuns.length === 0 ? (
                            <div className="text-sm text-muted-foreground">-</div>
                        ) : (
                            <div className="space-y-2">
                                {deliveryRuns.map(run => {
                                    const deferred = numberFrom(run.result?.deferred);
                                    return (
                                    <div key={run.id} className="rounded-md border bg-muted/20 p-2 text-sm">
                                        <div className="flex items-center justify-between gap-2">
                                            <div className="flex min-w-0 items-center gap-2">
                                                <Badge variant="outline" className="font-normal">{run.status}</Badge>
                                                <span className="truncate">{run.source || t('Delivery')}</span>
                                            </div>
                                            <span className="shrink-0 text-xs text-muted-foreground">{formatTime(run.startedAt)}</span>
                                        </div>
                                        <div className="mt-1 text-xs text-muted-foreground">
                                            {run.processed} {t('processed')} · {run.sent} {t('sent')} · {run.failed} {t('failed')}
                                            {deferred > 0 ? <> · {deferred} {t('deferred')}</> : null}
                                        </div>
                                        {run.error && <div className="mt-1 text-xs text-destructive">{run.error}</div>}
                                    </div>
                                    );
                                })}
                            </div>
                        )}
                    </section>
                    <section className="rounded-md border p-4">
                        <div className="mb-4 flex items-center justify-between gap-3">
                            <div>
                                <h2 className="text-sm font-medium">{t('Queues')}</h2>
                                <p className="text-xs text-muted-foreground">{supportQueues.length} {t('queues')}</p>
                            </div>
                            <Button size="sm" variant="outline" onClick={startNewQueue}>
                                <Plus className="size-4" />
                                {t('New')}
                            </Button>
                        </div>
                        <div className="grid gap-4 lg:grid-cols-[16rem_minmax(0,1fr)]">
                            <div className="min-h-40 rounded-md border">
                                {supportQueues.length === 0 ? (
                                    <div className="flex min-h-40 items-center justify-center text-sm text-muted-foreground">
                                        {t('No queues')}
                                    </div>
                                ) : (
                                    supportQueues.map(queue => (
                                        <button
                                            key={`${queue.id}:${queue.queueKey}`}
                                            type="button"
                                            className={[
                                                'w-full border-b px-3 py-2 text-left transition-colors last:border-b-0',
                                                queue.queueKey === selectedQueueKey ? 'bg-muted/60' : 'bg-background hover:bg-muted/40',
                                            ].join(' ')}
                                            onClick={() => setSelectedQueueKey(queue.queueKey)}
                                        >
                                            <div className="mb-1 flex min-w-0 items-center justify-between gap-2">
                                                <span className="truncate text-sm font-medium">{queue.name}</span>
                                                <Badge variant={queue.status === 'active' ? 'secondary' : 'outline'} className="font-normal">
                                                    {queue.status}
                                                </Badge>
                                            </div>
                                            <div className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
                                                <Hash className="size-3.5 shrink-0" />
                                                <span className="truncate">{queue.queueKey}</span>
                                            </div>
                                        </button>
                                    ))
                                )}
                            </div>
                            <div className="space-y-4">
                                <div className="grid gap-3 sm:grid-cols-3">
                                    <div className="space-y-1.5">
                                        <Label htmlFor="queue-key">{t('Key')}</Label>
                                        <Input
                                            id="queue-key"
                                            value={queueKey}
                                            disabled={Boolean(selectedQueue && !selectedQueueIsVirtual)}
                                            onChange={event => setQueueKey(event.target.value)}
                                            placeholder="support"
                                        />
                                    </div>
                                    <div className="space-y-1.5">
                                        <Label htmlFor="queue-name">{t('Name')}</Label>
                                        <Input
                                            id="queue-name"
                                            value={queueName}
                                            onChange={event => setQueueName(event.target.value)}
                                            placeholder="Support"
                                        />
                                    </div>
                                    <div className="space-y-1.5">
                                        <Label>{t('Status')}</Label>
                                        <Select value={queueStatus} onValueChange={setQueueStatus}>
                                            <SelectTrigger>
                                                <SelectValue />
                                            </SelectTrigger>
                                            <SelectContent>
                                                <SelectItem value="active">{t('Active')}</SelectItem>
                                                <SelectItem value="archived">{t('Archived')}</SelectItem>
                                            </SelectContent>
                                        </Select>
                                    </div>
                                </div>
                                <div className="space-y-1.5">
                                    <Label htmlFor="queue-default-assignee">{t('Default assignee')}</Label>
                                    <Input
                                        id="queue-default-assignee"
                                        type="email"
                                        value={queueDefaultAssigneeEmail}
                                        onChange={event => setQueueDefaultAssigneeEmail(event.target.value)}
                                        placeholder="agent@example.com"
                                    />
                                </div>
                                <div className="space-y-1.5">
                                    <Label>{t('Assignment mode')}</Label>
                                    <Select value={queueRoutingMode} onValueChange={value => setQueueRoutingMode(value as QueueRoutingMode)}>
                                        <SelectTrigger>
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="static">{t('Static owner')}</SelectItem>
                                            <SelectItem value="least_open">{t('Least open owner')}</SelectItem>
                                        </SelectContent>
                                    </Select>
                                    <p className="text-xs text-muted-foreground">
                                        {queueRoutingMode === 'least_open'
                                            ? t('New tickets go to the queue owner with the fewest open tickets.')
                                            : t('New tickets use the default assignee when one is set.')}
                                    </p>
                                </div>
                                <div className="space-y-1.5">
                                    <Label htmlFor="queue-owner-capacity">{t('Owner capacity')}</Label>
                                    <Input
                                        id="queue-owner-capacity"
                                        type="number"
                                        min={1}
                                        inputMode="numeric"
                                        value={queueOwnerCapacityDraft}
                                        onChange={event => setQueueOwnerCapacityDraft(event.target.value)}
                                        placeholder={t('No cap')}
                                    />
                                    <p className="text-xs text-muted-foreground">
                                        {t('Least-open routing skips owners at or above this active ticket count.')}
                                    </p>
                                </div>
                                <div className="space-y-1.5">
                                    <Label htmlFor="queue-owner-emails">{t('Queue owners')}</Label>
                                    <Textarea
                                        id="queue-owner-emails"
                                        value={queueOwnerEmailsDraft}
                                        onChange={event => setQueueOwnerEmailsDraft(event.target.value)}
                                        rows={2}
                                        placeholder="agent@example.com, lead@example.com"
                                    />
                                    <p className="text-xs text-muted-foreground">
                                        {t('When set, only these agents can be assigned tickets in this queue.')}
                                    </p>
                                </div>
                                <div className="space-y-1.5">
                                    <Label htmlFor="queue-description">{t('Description')}</Label>
                                    <Textarea
                                        id="queue-description"
                                        value={queueDescription}
                                        onChange={event => setQueueDescription(event.target.value)}
                                        rows={3}
                                    />
                                </div>
                                <div className="flex flex-wrap justify-end gap-2">
                                    {selectedQueue && !selectedQueueIsVirtual && (
                                        <Button
                                            type="button"
                                            variant="outline"
                                            onClick={() => void saveQueue(selectedQueue.status === 'archived' ? 'active' : 'archived')}
                                            disabled={savingQueue}
                                        >
                                            {selectedQueue.status === 'archived' ? t('Restore') : t('Archive')}
                                        </Button>
                                    )}
                                    <Button
                                        type="button"
                                        onClick={() => void saveQueue()}
                                        disabled={savingQueue || !queueName.trim()}
                                    >
                                        {savingQueue ? <Loader className="size-4 animate-spin" /> : null}
                                        {t('Save queue')}
                                    </Button>
                                </div>
                            </div>
                        </div>
                    </section>
                    <section className="rounded-md border p-4">
                        <div className="mb-4 flex items-center justify-between gap-3">
                            <div>
                                <h2 className="text-sm font-medium">{t('CRM connectors')}</h2>
                                <p className="text-xs text-muted-foreground">{crmConnectors.length} {t('connectors')}</p>
                            </div>
                            <div className="flex items-center gap-2">
                                <Button size="sm" variant="outline" onClick={() => void syncAllCrm()} disabled={Boolean(syncingCrm)}>
                                    {syncingCrm === 'all' ? <Loader className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
                                    {t('Sync')}
                                </Button>
                                <Button size="sm" variant="outline" onClick={startNewCrm}>
                                    <Plus className="size-4" />
                                    {t('New')}
                                </Button>
                            </div>
                        </div>
                        <div className="grid gap-4 lg:grid-cols-[16rem_minmax(0,1fr)]">
                            <div className="min-h-40 rounded-md border">
                                {crmConnectors.length === 0 ? (
                                    <div className="flex min-h-40 items-center justify-center text-sm text-muted-foreground">
                                        {t('No CRM connectors')}
                                    </div>
                                ) : (
                                    crmConnectors.map(connector => (
                                        <button
                                            key={connector.id}
                                            type="button"
                                            className={[
                                                'w-full border-b px-3 py-2 text-left transition-colors last:border-b-0',
                                                connector.connectorKey === selectedCrmKey ? 'bg-muted/60' : 'bg-background hover:bg-muted/40',
                                            ].join(' ')}
                                            onClick={() => setSelectedCrmKey(connector.connectorKey)}
                                        >
                                            <div className="mb-1 flex min-w-0 items-center justify-between gap-2">
                                                <span className="truncate text-sm font-medium">{connector.name}</span>
                                                <Badge variant="outline" className="font-normal">{connector.status}</Badge>
                                            </div>
                                            <div className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
                                                <Database className="size-3.5 shrink-0" />
                                                <span>{connector.provider}</span>
                                                <span className="truncate">{connector.connectorKey}</span>
                                            </div>
                                        </button>
                                    ))
                                )}
                            </div>
                            <div className="space-y-4">
                                <div className="flex items-start justify-between gap-3">
                                    <div>
                                        <h3 className="text-sm font-medium">
                                            {selectedCrmConnector ? t('CRM connector') : t('New CRM connector')}
                                        </h3>
                                        {selectedCrmConnector && (
                                            <p className="text-xs text-muted-foreground">{formatTime(selectedCrmConnector.lastSyncAt)}</p>
                                        )}
                                    </div>
                                    {selectedCrmConnector && (
                                        <div className="flex items-center gap-2">
                                            <Button
                                                type="button"
                                                variant="outline"
                                                size="sm"
                                                onClick={() => void validateSelectedCrm()}
                                                disabled={Boolean(validatingCrm || syncingCrm)}
                                            >
                                                {validatingCrm === selectedCrmConnector.id
                                                    ? <Loader className="size-4 animate-spin" />
                                                    : <CheckCircle2 className="size-4" />}
                                                {t('Validate')}
                                            </Button>
                                            <Button
                                                type="button"
                                                variant="outline"
                                                size="sm"
                                                onClick={() => void syncSelectedCrm()}
                                                disabled={Boolean(syncingCrm || validatingCrm)}
                                            >
                                                {syncingCrm === selectedCrmConnector.id
                                                    ? <Loader className="size-4 animate-spin" />
                                                    : <RefreshCw className="size-4" />}
                                                {t('Sync CRM')}
                                            </Button>
                                        </div>
                                    )}
                                </div>
                                <div className="grid gap-3 sm:grid-cols-3">
                                    <div className="space-y-1.5">
                                        <Label>{t('Provider')}</Label>
                                        <Select value={crmProvider} onValueChange={changeCrmProvider}>
                                            <SelectTrigger>
                                                <SelectValue />
                                            </SelectTrigger>
                                            <SelectContent>
                                                {crmProviderPresets.map(preset => (
                                                    <SelectItem key={preset.provider} value={preset.provider}>
                                                        {preset.label}
                                                    </SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                    </div>
                                    <div className="space-y-1.5">
                                        <Label>{t('Status')}</Label>
                                        <Select value={crmStatus} onValueChange={setCrmStatus}>
                                            <SelectTrigger>
                                                <SelectValue />
                                            </SelectTrigger>
                                            <SelectContent>
                                                <SelectItem value="active">{t('Active')}</SelectItem>
                                                <SelectItem value="paused">{t('Paused')}</SelectItem>
                                                <SelectItem value="disabled">{t('Disabled')}</SelectItem>
                                            </SelectContent>
                                        </Select>
                                    </div>
                                    <div className="space-y-1.5">
                                        <Label htmlFor="crm-key">{t('Key')}</Label>
                                        <Input
                                            id="crm-key"
                                            value={crmConnectorKey}
                                            onChange={event => setCrmConnectorKey(event.target.value)}
                                        />
                                    </div>
                                </div>
                                <div className="space-y-1.5">
                                    <Label htmlFor="crm-name">{t('Name')}</Label>
                                    <Input id="crm-name" value={crmName} onChange={event => setCrmName(event.target.value)} />
                                </div>
                                <div className="rounded-md border bg-muted/20 p-3">
                                    <div className="mb-2 flex items-center justify-between gap-3">
                                        <div className="flex items-center gap-2 text-sm font-medium">
                                            <Database className="size-4" />
                                            {selectedCrmPreset.label}
                                        </div>
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            onClick={() => applyCrmProviderPreset(crmProvider, true)}
                                        >
                                            {t('Apply preset')}
                                        </Button>
                                    </div>
                                    <p className="text-xs leading-5 text-muted-foreground">
                                        {selectedCrmPreset.note}
                                    </p>
                                    {selectedCrmPreset.envVars.length > 0 && (
                                        <div className="mt-3 space-y-2">
                                            <div className="text-xs font-medium uppercase text-muted-foreground">{t('Required env')}</div>
                                            <div className="grid gap-2 sm:grid-cols-2">
                                                {selectedCrmPreset.envVars.map(envVar => (
                                                    <div key={envVar.name} className="rounded-md border bg-background p-2">
                                                        <div className="mb-1 flex items-center gap-2">
                                                            <Badge variant={envVar.required ? 'secondary' : 'outline'} className="font-normal">
                                                                {envVar.required ? t('Required') : t('Optional')}
                                                            </Badge>
                                                            <code className="truncate text-xs">{envVar.name}</code>
                                                        </div>
                                                        <p className="text-xs leading-5 text-muted-foreground">{envVar.description}</p>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>
                                {crmValidation && (
                                    <div className="rounded-md border p-3">
                                        <div className="mb-3 flex items-center justify-between gap-2">
                                            <div className="flex items-center gap-2 text-sm font-medium">
                                                {crmValidation.ready
                                                    ? <CheckCircle2 className="size-4 text-emerald-600" />
                                                    : <AlertTriangle className="size-4 text-destructive" />}
                                                {t('CRM validation')}
                                            </div>
                                            <Badge variant={crmValidation.ready ? 'secondary' : 'destructive'} className="font-normal">
                                                {crmValidation.status}
                                            </Badge>
                                        </div>
                                        <div className="space-y-2">
                                            {crmValidation.checks.map(check => (
                                                <div key={check.key} className="rounded-md border bg-muted/20 p-2 text-sm">
                                                    <div className="flex items-center justify-between gap-2">
                                                        <div className="min-w-0 truncate font-medium">{check.label}</div>
                                                        <Badge variant={setupStatusVariant(check.status)} className="font-normal">
                                                            {setupStatusLabel(check.status)}
                                                        </Badge>
                                                    </div>
                                                    {check.detail && (
                                                        <div className="mt-1 text-xs text-muted-foreground">{check.detail}</div>
                                                    )}
                                                    {typeof check.count === 'number' && (
                                                        <div className="mt-1 text-xs text-muted-foreground">
                                                            {check.count} {t('sample records')}
                                                        </div>
                                                    )}
                                                </div>
                                            ))}
                                        </div>
                                        {crmValidation.envVars.length > 0 && (
                                            <div className="mt-3 flex flex-wrap gap-1.5">
                                                {crmValidation.envVars.map(envVar => (
                                                    <Badge
                                                        key={envVar.name}
                                                        variant={envVar.configured ? 'secondary' : 'destructive'}
                                                        className="font-normal"
                                                    >
                                                        {envVar.name}
                                                    </Badge>
                                                ))}
                                            </div>
                                        )}
                                        {crmValidation.error && (
                                            <div className="mt-3 rounded-md border bg-muted/20 p-2 text-xs text-destructive">
                                                {crmValidation.error}
                                            </div>
                                        )}
                                    </div>
                                )}
                                <div className="space-y-1.5">
                                    <div className="flex items-center justify-between gap-2">
                                        <Label htmlFor="crm-config">{t('Config')}</Label>
                                        <Badge variant="outline" className="font-normal">{t('JSON')}</Badge>
                                    </div>
                                    <Textarea
                                        id="crm-config"
                                        value={crmConfigJson}
                                        onChange={event => setCrmConfigJson(event.target.value)}
                                        rows={8}
                                        spellCheck={false}
                                    />
                                </div>
                                <div className="rounded-md border p-3">
                                    <div className="mb-3 flex items-center justify-between gap-2">
                                        <h3 className="text-sm font-medium">{t('CRM sync history')}</h3>
                                        <Badge variant="outline" className="font-normal">{crmSyncRuns.length}</Badge>
                                    </div>
                                    {crmSyncRuns.length === 0 ? (
                                        <div className="text-sm text-muted-foreground">-</div>
                                    ) : (
                                        <div className="space-y-2">
                                            {crmSyncRuns.map(run => (
                                                <div key={run.id} className="rounded-md border bg-muted/20 p-2 text-sm">
                                                    <div className="flex items-center justify-between gap-2">
                                                        <div className="flex min-w-0 items-center gap-2">
                                                            <Badge variant="outline" className="font-normal">{run.status}</Badge>
                                                            <span className="truncate">{run.source || t('CRM sync')}</span>
                                                        </div>
                                                        <span className="shrink-0 text-xs text-muted-foreground">{formatTime(run.startedAt)}</span>
                                                    </div>
                                                    <div className="mt-1 text-xs text-muted-foreground">
                                                        {run.processed} {t('processed')} · {run.objectsSeen} {t('objects')} · {run.failed} {t('failed')}
                                                    </div>
                                                    {run.error && <div className="mt-1 text-xs text-destructive">{run.error}</div>}
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                                <div className="rounded-md border p-3">
                                    <div className="mb-3 flex items-center justify-between gap-2">
                                        <h3 className="text-sm font-medium">{t('CRM webhook inbox')}</h3>
                                        <Badge variant="outline" className="font-normal">{crmWebhookEvents.length}</Badge>
                                    </div>
                                    {crmWebhookEvents.length === 0 ? (
                                        <div className="text-sm text-muted-foreground">-</div>
                                    ) : (
                                        <div className="space-y-2">
                                            {crmWebhookEvents.map(event => (
                                                <div key={event.id} className="rounded-md border bg-muted/20 p-2 text-sm">
                                                    <div className="flex items-center justify-between gap-2">
                                                        <div className="flex min-w-0 items-center gap-2">
                                                            <Badge variant="outline" className="font-normal">{event.status}</Badge>
                                                            <span className="truncate">{event.eventType || t('Webhook')}</span>
                                                        </div>
                                                        <span className="shrink-0 text-xs text-muted-foreground">{formatTime(event.receivedAt)}</span>
                                                    </div>
                                                    <div className="mt-1 flex min-w-0 gap-2 text-xs text-muted-foreground">
                                                        <span>{event.objectType || '-'}</span>
                                                        <span className="truncate">{event.externalId || event.eventId}</span>
                                                    </div>
                                                    {event.error && <div className="mt-1 text-xs text-destructive">{event.error}</div>}
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                                <div className="flex justify-end">
                                    <Button
                                        onClick={() => void saveCrmConnector()}
                                        disabled={savingCrm || !crmName.trim() || !crmProvider.trim()}
                                    >
                                        {savingCrm ? <Loader className="size-4 animate-spin" /> : null}
                                        {t('Save CRM')}
                                    </Button>
                                </div>
                            </div>
                        </div>
                    </section>
                    <div className="flex justify-end gap-2">
                        {type === 'slack' && !selectedChannel && (
                            <Button type="button" variant="outline" onClick={() => void installSlack()} disabled={installingSlack || !name.trim()}>
                                {installingSlack ? <Loader className="size-4 animate-spin" /> : <ExternalLink className="size-4" />}
                                {t('Install Slack')}
                            </Button>
                        )}
                        <Button onClick={() => void saveChannel()} disabled={saving || !name.trim() || !type.trim()}>
                            {saving ? <Loader className="size-4 animate-spin" /> : null}
                            {t('Save')}
                        </Button>
                    </div>
                </div>
            </section>
        </div>
    );
}
