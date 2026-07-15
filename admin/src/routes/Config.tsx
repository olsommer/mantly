import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Switch } from '@/components/ui/switch';
import { AlertCircle, CheckCircle2, Clock, Download, Eye, EyeOff, Inbox, Loader, Plus, Save, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { api } from '@/api/endpoints';
import type { AdminConfigData, SupportCustomFieldDefinition, SupportCustomFieldType, SupportSlaEscalationRun, SupportSlaPolicy } from '@/api/endpoints';
import { settings } from '@/settings';
import { SecretsEditor } from '@/components/secrets-editor';
import { useTopBar } from '@/TopBarContext';
import { useI18n } from '@/lib/i18n-context';
import type { Locale } from '@/lib/i18n-core';

const KNOWN_GEMINI_MODELS = [
    'gemini-3-flash-preview',
    'gemini-2.5-flash',
    'gemini-2.5-pro',
    'gemini-2.0-flash',
    'gemini-1.5-pro',
];

const DEFAULT_SECURITY_SETTINGS = {
    phishingMonitoringEnabled: false,
    promptInjectionMonitoringEnabled: false,
};

const DEFAULT_SLA_POLICY: Pick<
    SupportSlaPolicy,
    'name' | 'active' | 'firstResponseMinutes' | 'resolutionMinutes' | 'businessHours' | 'metadata'
> = {
    name: 'Default',
    active: true,
    firstResponseMinutes: 240,
    resolutionMinutes: 2880,
    businessHours: {},
    metadata: {},
};

type BusinessHours = {
    enabled: boolean;
    timezone: string;
    start: string;
    end: string;
    days: number[];
};

const BUSINESS_DAY_OPTIONS = [
    { value: 0, label: 'Mon' },
    { value: 1, label: 'Tue' },
    { value: 2, label: 'Wed' },
    { value: 3, label: 'Thu' },
    { value: 4, label: 'Fri' },
    { value: 5, label: 'Sat' },
    { value: 6, label: 'Sun' },
];

const CUSTOM_FIELD_TYPES: SupportCustomFieldType[] = ['text', 'number', 'select', 'boolean', 'date', 'url'];

function customFieldKey(value: string) {
    return value
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '')
        .slice(0, 64);
}

function stringFromUnknown(value: unknown) {
    if (typeof value === 'string') return value;
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
    return '';
}

function customFieldDefinitionsFromMetadata(metadata: Record<string, unknown>): SupportCustomFieldDefinition[] {
    const raw = Array.isArray(metadata.customFields)
        ? metadata.customFields
        : Array.isArray(metadata.custom_fields)
            ? metadata.custom_fields
            : [];
    return raw
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
        .map((item) => {
            const key = customFieldKey(stringFromUnknown(item.key) || stringFromUnknown(item.label));
            const rawType = (stringFromUnknown(item.type) || 'text') as SupportCustomFieldType;
            const type = CUSTOM_FIELD_TYPES.includes(rawType) ? rawType : 'text';
            const options = Array.isArray(item.options)
                ? item.options.map(option => stringFromUnknown(option).trim()).filter(Boolean)
                : stringFromUnknown(item.options).split(',').map(option => option.trim()).filter(Boolean);
            return {
                key,
                label: (stringFromUnknown(item.label) || stringFromUnknown(item.key)).trim() || key,
                type,
                required: item.required === true,
                options,
            };
        })
        .filter(item => item.key);
}

function localTimezone() {
    try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    } catch {
        return 'UTC';
    }
}

function booleanFromBusinessHours(value: unknown): boolean {
    if (typeof value === 'boolean') return value;
    if (typeof value === 'number') return value !== 0;
    if (typeof value === 'string') return ['1', 'true', 'yes', 'on', 'enabled'].includes(value.trim().toLowerCase());
    return false;
}

function textFromBusinessHours(value: unknown, fallback: string) {
    return typeof value === 'string' && value.trim() ? value.trim() : fallback;
}

function daysFromBusinessHours(value: unknown): number[] {
    if (!Array.isArray(value)) return [0, 1, 2, 3, 4];
    const days = value
        .map(item => typeof item === 'number' ? item : Number.parseInt(String(item), 10))
        .filter(day => Number.isInteger(day) && day >= 0 && day <= 6);
    return [...new Set(days)].sort((a, b) => a - b);
}

function businessHoursFrom(value: Record<string, unknown> | undefined): BusinessHours {
    const source = value ?? {};
    return {
        enabled: booleanFromBusinessHours(source.enabled),
        timezone: textFromBusinessHours(source.timezone, localTimezone()),
        start: textFromBusinessHours(source.start ?? source.startTime ?? source.start_time, '09:00'),
        end: textFromBusinessHours(source.end ?? source.endTime ?? source.end_time, '17:00'),
        days: daysFromBusinessHours(source.days ?? source.weekdays),
    };
}

function minutesLabel(minutes: number) {
    if (minutes >= 1440 && minutes % 1440 === 0) return `${minutes / 1440}d`;
    if (minutes >= 60 && minutes % 60 === 0) return `${minutes / 60}h`;
    return `${minutes}m`;
}

export const Config = ({
    projectId,
    canDownloadManifest = true,
    canManageProjectSecrets = true,
    canEditProjectConfig = true,
    isDemoAccount = false,
}: {
    projectId: string;
    canDownloadManifest?: boolean;
    canManageProjectSecrets?: boolean;
    canEditProjectConfig?: boolean;
    isDemoAccount?: boolean;
}) => {
    const navigate = useNavigate();
    const { tenantId } = useParams<{ tenantId: string }>();
    const [config, setConfig] = useState<Pick<
        AdminConfigData,
        'orgName' | 'orgDescription' | 'useCustomOrg' |
        'llmModel' | 'llmProvider' | 'llmApiKey' |
        'llmCustomBaseUrl' | 'llmCustomModel' | 'useCustomLlm' |
        'useCustomSecurity' | 'phishingMonitoringEnabled' | 'promptInjectionMonitoringEnabled'
    >>({
        orgName: '', orgDescription: '', useCustomOrg: false,
        llmModel: '', llmProvider: 'gemini',
        llmApiKey: '', llmCustomBaseUrl: '', llmCustomModel: '',
        useCustomLlm: false,
        useCustomSecurity: false,
        phishingMonitoringEnabled: false,
        promptInjectionMonitoringEnabled: false,
    });
    const [tenantSecurity, setTenantSecurity] = useState(DEFAULT_SECURITY_SETTINGS);
    const [slaPolicy, setSlaPolicy] = useState(DEFAULT_SLA_POLICY);
    const [profileName, setProfileName] = useState('');
    const [profileLanguage, setProfileLanguage] = useState<Locale>('en');
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const [runningSlaEscalation, setRunningSlaEscalation] = useState(false);
    const [lastSlaRun, setLastSlaRun] = useState<SupportSlaEscalationRun | null>(null);
    const [downloading, setDownloading] = useState(false);
    const [showApiKey, setShowApiKey] = useState(false);
    const [manifestBaseUrl, setManifestBaseUrl] = useState('');
    const { setActions } = useTopBar();
    const { setLocale, t } = useI18n();
    const businessHours = businessHoursFrom(slaPolicy.businessHours);

    const setBusinessHours = (patch: Partial<BusinessHours>) => {
        setSlaPolicy(policy => ({
            ...policy,
            businessHours: {
                ...businessHoursFrom(policy.businessHours),
                ...patch,
            },
        }));
    };

    const toggleBusinessDay = (day: number) => {
        const current = new Set(businessHours.days);
        if (current.has(day)) current.delete(day);
        else current.add(day);
        setBusinessHours({ days: [...current].sort((a, b) => a - b) });
    };

    const setCustomFieldDefinitions = (definitions: SupportCustomFieldDefinition[]) => {
        setSlaPolicy(policy => ({
            ...policy,
            metadata: {
                ...policy.metadata,
                customFields: definitions.map(definition => ({
                    key: customFieldKey(definition.key || definition.label),
                    label: definition.label.trim() || customFieldKey(definition.key),
                    type: definition.type,
                    required: definition.required,
                    options: definition.type === 'select' ? definition.options.map(option => option.trim()).filter(Boolean) : [],
                })).filter(definition => definition.key),
            },
        }));
    };

    const updateCustomFieldDefinition = (index: number, patch: Partial<SupportCustomFieldDefinition>) => {
        const current = customFieldDefinitionsFromMetadata(slaPolicy.metadata);
        const next = current.map((definition, idx) => idx === index ? { ...definition, ...patch } : definition);
        setCustomFieldDefinitions(next);
    };

    const addCustomFieldDefinition = () => {
        const current = customFieldDefinitionsFromMetadata(slaPolicy.metadata);
        const nextIndex = current.length + 1;
        setCustomFieldDefinitions([
            ...current,
            {
                key: `field_${nextIndex}`,
                label: `Field ${nextIndex}`,
                type: 'text',
                required: false,
                options: [],
            },
        ]);
    };

    const removeCustomFieldDefinition = (index: number) => {
        setCustomFieldDefinitions(customFieldDefinitionsFromMetadata(slaPolicy.metadata).filter((_definition, idx) => idx !== index));
    };

    useEffect(() => {
        void (async () => {
            const [res, tenantRes, profileRes, slaRes] = await Promise.all([
                api.getAdminConfig(projectId),
                api.getTenantSettings(),
                api.getCurrentUser(),
                api.getSlaPolicy(projectId),
            ]);
            if (profileRes.data) {
                setProfileName(profileRes.data.name ?? '');
                setProfileLanguage(profileRes.data.language ?? 'en');
                setLocale(profileRes.data.language ?? 'en');
            }
            if (tenantRes.data) {
                setTenantSecurity({
                    phishingMonitoringEnabled: tenantRes.data.phishingMonitoringEnabled ?? false,
                    promptInjectionMonitoringEnabled: tenantRes.data.promptInjectionMonitoringEnabled ?? false,
                });
            }
            if (slaRes.data) {
                setSlaPolicy({
                    name: slaRes.data.name || 'Default',
                    active: slaRes.data.active,
                    firstResponseMinutes: slaRes.data.firstResponseMinutes || 240,
                    resolutionMinutes: slaRes.data.resolutionMinutes || 2880,
                    businessHours: slaRes.data.businessHours || {},
                    metadata: slaRes.data.metadata || {},
                });
            }
            if (res.data) {
                setConfig({
                    orgName: res.data.orgName ?? '',
                    orgDescription: res.data.orgDescription ?? '',
                    useCustomOrg: res.data.useCustomOrg ?? false,
                    llmModel: res.data.llmModel ?? '',
                    llmProvider: res.data.llmProvider ?? 'gemini',
                    llmApiKey: res.data.llmApiKey ?? '',
                    llmCustomBaseUrl: res.data.llmCustomBaseUrl ?? '',
                    llmCustomModel: res.data.llmCustomModel ?? '',
                    useCustomLlm: res.data.useCustomLlm ?? false,
                    useCustomSecurity: res.data.useCustomSecurity ?? false,
                    phishingMonitoringEnabled: res.data.phishingMonitoringEnabled ?? false,
                    promptInjectionMonitoringEnabled: res.data.promptInjectionMonitoringEnabled ?? false,
                });
            } else {
                setLoadError('Could not reach the backend. Is it running?');
            }
            setLoading(false);
        })();
    }, [projectId, setLocale]);

    const handleDownloadManifest = async () => {
        setDownloading(true);
        try {
            await api.downloadManifest(projectId, manifestBaseUrl || undefined);
            toast.success(t('Manifest downloaded'));
        } catch {
            toast.error(t('Manifest download failed'));
        } finally {
            setDownloading(false);
        }
    };

    const handleSave = useCallback(async () => {
        const name = profileName.trim();
        if (!name) {
            toast.error(t('Name is required.'));
            return;
        }

        setSaving(true);
        const profileRes = await api.updateCurrentUser({ name, language: profileLanguage });
        if (profileRes.error) {
            toast.error(t('Save failed: {error}', { error: profileRes.error }));
            setSaving(false);
            return;
        }

        if (canEditProjectConfig) {
            if (slaPolicy.resolutionMinutes < slaPolicy.firstResponseMinutes) {
                toast.error(t('Resolution SLA must be greater than or equal to first response SLA.'));
                setSaving(false);
                return;
            }
            const nextBusinessHours = businessHoursFrom(slaPolicy.businessHours);
            if (nextBusinessHours.enabled) {
                if (nextBusinessHours.start >= nextBusinessHours.end) {
                    toast.error(t('Business hours end time must be after start time.'));
                    setSaving(false);
                    return;
                }
                if (nextBusinessHours.days.length === 0) {
                    toast.error(t('Select at least one business day.'));
                    setSaving(false);
                    return;
                }
            }
            const res = await api.updateAdminConfig(projectId, config);
            if (res.error) {
                toast.error(t('Save failed: {error}', { error: res.error }));
                setSaving(false);
                return;
            }
            const slaRes = await api.updateSlaPolicy(projectId, slaPolicy);
            if (slaRes.error) {
                toast.error(t('Save failed: {error}', { error: slaRes.error }));
                setSaving(false);
                return;
            }
        }

        setProfileName(name);
        setLocale(profileLanguage);
        toast.success(t('Settings saved'));
        setSaving(false);
    }, [canEditProjectConfig, config, profileLanguage, profileName, projectId, setLocale, slaPolicy, t]);

    const runSlaEscalationScan = useCallback(async () => {
        if (!canEditProjectConfig || runningSlaEscalation) return;
        setRunningSlaEscalation(true);
        const res = await api.runSlaEscalations(projectId);
        setRunningSlaEscalation(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not run SLA scan'));
            return;
        }
        setLastSlaRun(res.data);
        if (res.data.failed > 0) {
            toast.error(t('SLA scan completed with failures'));
            return;
        }
        toast.success(t('SLA scan complete'));
    }, [canEditProjectConfig, projectId, runningSlaEscalation, t]);

    useEffect(() => {
        if (loading) {
            setActions(null);
            return;
        }

        setActions(
            <Button size="sm" onClick={handleSave} disabled={saving}>
                {saving ? <Loader className="size-4 animate-spin" /> : <Save className="size-4" />}
                {t('Save changes')}
            </Button>
        );

        return () => setActions(null);
    }, [handleSave, loading, saving, setActions, t]);

    if (loading) {
        return (
            <div className="flex items-center gap-2 text-muted-foreground">
                <Loader className="size-4 animate-spin" /> {t('Loading')}...
            </div>
        );
    }

    const manifestSection = canDownloadManifest && (
        <div className="pt-4 border-t space-y-3">
            <h3 className="text-sm font-medium">{t('Outlook Add-in')}</h3>
            <p className="text-sm text-muted-foreground">
                {t('Download the manifest and upload it to Microsoft 365 Admin Centre to deploy the add-in.')}
            </p>
            {!settings.isSaas && (
                <div className="space-y-1.5">
                    <Label htmlFor="manifestBaseUrl">{t('Backend URL')}</Label>
                    <Input
                        id="manifestBaseUrl"
                        type="url"
                        value={manifestBaseUrl}
                        onChange={e => setManifestBaseUrl(e.target.value)}
                        placeholder={window.location.origin}
                    />
                    <p className="text-xs text-muted-foreground">
                        {t('The public URL where the backend is reachable (e.g. an ngrok or Tailscale Funnel URL for testing). Leave blank to use the current origin.')}
                    </p>
                </div>
            )}
            <Button variant="outline" onClick={handleDownloadManifest} disabled={downloading}>
                {downloading
                    ? <Loader className="size-4 animate-spin mr-2" />
                    : <Download className="size-4 mr-2" />}
                {t('Download manifest.xml')}
            </Button>
        </div>
    );
    const effectiveSecurity = config.useCustomSecurity ? config : tenantSecurity;
    const defaultAssigneeEmail = typeof slaPolicy.metadata.defaultAssigneeEmail === 'string'
        ? slaPolicy.metadata.defaultAssigneeEmail
        : typeof slaPolicy.metadata.default_assignee_email === 'string'
            ? slaPolicy.metadata.default_assignee_email
            : '';
    const defaultQueueKey = typeof slaPolicy.metadata.defaultQueueKey === 'string'
        ? slaPolicy.metadata.defaultQueueKey
        : typeof slaPolicy.metadata.default_queue_key === 'string'
            ? slaPolicy.metadata.default_queue_key
            : '';
    const defaultQueueName = typeof slaPolicy.metadata.defaultQueueName === 'string'
        ? slaPolicy.metadata.defaultQueueName
        : typeof slaPolicy.metadata.default_queue_name === 'string'
            ? slaPolicy.metadata.default_queue_name
            : '';
    const customFieldDefinitions = customFieldDefinitionsFromMetadata(slaPolicy.metadata);
    const supportFieldCount = customFieldDefinitions.length;
    const requiredSupportFieldCount = customFieldDefinitions.filter(field => field.required).length;
    const supportDefaultsReady = Boolean(slaPolicy.active && defaultQueueKey && defaultQueueName && defaultAssigneeEmail && supportFieldCount > 0);
    const supportSettingsWarnings = [
        !slaPolicy.active ? t('SLA inactive') : '',
        !defaultQueueKey || !defaultQueueName ? t('Default queue missing') : '',
        !defaultAssigneeEmail ? t('Default assignee missing') : '',
        supportFieldCount === 0 ? t('No ticket fields') : '',
    ].filter(Boolean);
    const supportNextAction = supportSettingsWarnings[0] || t('Run SLA scan');

    const applySupportDefaults = () => {
        if (!canEditProjectConfig) return;
        setSlaPolicy(policy => ({
            ...policy,
            active: true,
            firstResponseMinutes: policy.firstResponseMinutes || 240,
            resolutionMinutes: Math.max(policy.resolutionMinutes || 2880, policy.firstResponseMinutes || 240),
            metadata: {
                ...policy.metadata,
                defaultQueueKey: defaultQueueKey || 'support',
                defaultQueueName: defaultQueueName || 'Support',
                defaultAssigneeEmail: defaultAssigneeEmail || 'agent@example.com',
                customFields: supportFieldCount === 0
                    ? [
                        { key: 'plan', label: 'Plan', type: 'text', required: false, options: [] },
                        { key: 'severity_reason', label: 'Severity reason', type: 'text', required: false, options: [] },
                    ]
                    : policy.metadata.customFields ?? policy.metadata.custom_fields,
            },
        }));
    };

    return (
        <div className="space-y-6 max-w-lg">
            {loadError && (
                <div className="rounded-md bg-destructive/10 border border-destructive/20 px-4 py-2 text-sm text-destructive flex items-center gap-2">
                    <AlertCircle className="size-4 shrink-0" />
                    {t(loadError)}
                </div>
            )}
            <div>
                <h2 className="text-lg font-semibold mb-1">{t('Project Configuration')}</h2>
                <p className="text-sm text-muted-foreground">
                    {isDemoAccount
                        ? t('Demo workspaces can change the same project-level configuration as a normal account.')
                        : t('By default this project inherits organisation-wide settings. Enable overrides below to customise per-project.')}
                </p>
            </div>

            <section data-support-settings-operations className="space-y-3 rounded-lg border p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                        <div className="flex min-w-0 items-center gap-2 text-sm font-semibold">
                            <CheckCircle2 className="size-4 text-muted-foreground" />
                            <span className="truncate">{t('Support operations')}</span>
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">
                            {t('Ticket defaults, SLA policy, and structured fields for new support work.')}
                        </p>
                    </div>
                    <div className={[
                        'rounded-full border px-2 py-0.5 text-xs',
                        supportDefaultsReady ? 'bg-muted/40 text-muted-foreground' : 'border-destructive/30 bg-destructive/5 text-destructive',
                    ].join(' ')}>
                        {supportDefaultsReady ? t('Ready') : supportNextAction}
                    </div>
                </div>
                <div className="grid gap-2 sm:grid-cols-4">
                    <div className="rounded-md border bg-muted/20 p-2 text-xs">
                        <div className="font-medium">{slaPolicy.active ? minutesLabel(slaPolicy.firstResponseMinutes) : '-'}</div>
                        <div className="text-muted-foreground">{t('first response')}</div>
                    </div>
                    <div className="rounded-md border bg-muted/20 p-2 text-xs">
                        <div className="font-medium">{slaPolicy.active ? minutesLabel(slaPolicy.resolutionMinutes) : '-'}</div>
                        <div className="text-muted-foreground">{t('resolution')}</div>
                    </div>
                    <div className="rounded-md border bg-muted/20 p-2 text-xs">
                        <div className="truncate font-medium">{defaultQueueName || defaultQueueKey || '-'}</div>
                        <div className="text-muted-foreground">{t('default queue')}</div>
                    </div>
                    <div className="rounded-md border bg-muted/20 p-2 text-xs">
                        <div className="font-medium">{supportFieldCount}/{requiredSupportFieldCount}</div>
                        <div className="text-muted-foreground">{t('fields/required')}</div>
                    </div>
                </div>
                <div data-support-settings-next-action className="rounded-md border bg-muted/20 p-3">
                    <div className="mb-2 flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                            <div className="truncate text-sm font-medium">{supportDefaultsReady ? t('Support defaults configured') : supportNextAction}</div>
                            <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                                {supportDefaultsReady
                                    ? t('New tickets have owner routing, queue defaults, SLA clocks, and structured field definitions.')
                                    : t('Apply defaults or fill missing fields before treating this workspace as support-ready.')}
                            </div>
                        </div>
                        <div className="text-xs text-muted-foreground">
                            {businessHours.enabled ? `${businessHours.start}-${businessHours.end}` : t('24/7')}
                        </div>
                    </div>
                    {supportSettingsWarnings.length > 0 && (
                        <div className="mb-2 flex flex-wrap gap-1.5">
                            {supportSettingsWarnings.map(warning => (
                                <span key={warning} className="rounded-full border border-destructive/30 bg-destructive/5 px-2 py-0.5 text-xs text-destructive">
                                    {warning}
                                </span>
                            ))}
                        </div>
                    )}
                    <div className="flex flex-wrap justify-end gap-2">
                        <Button type="button" size="sm" variant="outline" onClick={applySupportDefaults} disabled={!canEditProjectConfig}>
                            <CheckCircle2 className="size-3.5" />
                            {t('Apply defaults')}
                        </Button>
                        <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => tenantId && navigate(`/${tenantId}/${projectId}/analytics`)}
                            disabled={!tenantId}
                        >
                            <AlertCircle className="size-3.5" />
                            {t('Open SLA analytics')}
                        </Button>
                        <Button
                            type="button"
                            size="sm"
                            onClick={() => void runSlaEscalationScan()}
                            disabled={!canEditProjectConfig || runningSlaEscalation}
                        >
                            {runningSlaEscalation ? <Loader className="size-3.5 animate-spin" /> : <Inbox className="size-3.5" />}
                            {t('Run SLA scan')}
                        </Button>
                    </div>
                </div>
            </section>

            {/* ── Personal Settings ── */}
            <div className="space-y-4 rounded-lg border p-4">
                <div>
                    <h3 className="text-sm font-semibold">{t('Personal settings')}</h3>
                    <p className="text-xs text-muted-foreground mt-0.5">
                        {t('This name is used when Mantly drafts replies on your behalf.')}
                    </p>
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor="profileName">{t('Name')}</Label>
                    <Input
                        id="profileName"
                        value={profileName}
                        onChange={e => setProfileName(e.target.value)}
                        placeholder="Max Müller"
                    />
                </div>
                <div className="space-y-2">
                    <div>
                        <Label>{t('Language')}</Label>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                            {t('Choose your preferred language for the admin UI and Outlook add-in.')}
                        </p>
                    </div>
                    <Tabs
                        value={profileLanguage}
                        onValueChange={(value) => {
                            const next = value as Locale;
                            setProfileLanguage(next);
                            setLocale(next);
                        }}
                    >
                        <TabsList>
                            <TabsTrigger value="en">{t('English')}</TabsTrigger>
                            <TabsTrigger value="de">{t('German')}</TabsTrigger>
                        </TabsList>
                    </Tabs>
                </div>
            </div>

            {/* ── Support SLA ── */}
            <div className="space-y-4 rounded-lg border p-4">
                <div className="flex items-center justify-between gap-4">
                    <div>
                        <h3 className="text-sm font-semibold">{t('Support SLA')}</h3>
                        <p className="text-xs text-muted-foreground mt-0.5">
                            {t('Set the clocks used when new support issues are created.')}
                        </p>
                    </div>
                    <Switch
                        checked={slaPolicy.active}
                        disabled={!canEditProjectConfig}
                        onCheckedChange={v => setSlaPolicy(policy => ({ ...policy, active: v }))}
                    />
                </div>
                <div className="grid grid-cols-2 gap-3 border-t pt-4">
                    <div className="space-y-1.5">
                        <Label htmlFor="firstResponseMinutes">{t('First response minutes')}</Label>
                        <Input
                            id="firstResponseMinutes"
                            type="number"
                            min={1}
                            value={slaPolicy.firstResponseMinutes}
                            disabled={!canEditProjectConfig}
                            onChange={e => setSlaPolicy(policy => ({
                                ...policy,
                                firstResponseMinutes: Math.max(1, Number(e.target.value) || 1),
                            }))}
                        />
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="resolutionMinutes">{t('Resolution minutes')}</Label>
                        <Input
                            id="resolutionMinutes"
                            type="number"
                            min={1}
                            value={slaPolicy.resolutionMinutes}
                            disabled={!canEditProjectConfig}
                            onChange={e => setSlaPolicy(policy => ({
                                ...policy,
                                resolutionMinutes: Math.max(1, Number(e.target.value) || 1),
                            }))}
                        />
                    </div>
                    <div className="col-span-2 space-y-3 border-t pt-3">
                        <div className="flex items-center justify-between gap-3">
                            <div className="flex items-center gap-2 text-sm font-medium">
                                <Clock className="size-4" />
                                {t('Business hours')}
                            </div>
                            <Switch
                                checked={businessHours.enabled}
                                disabled={!canEditProjectConfig}
                                onCheckedChange={enabled => setBusinessHours({ enabled })}
                            />
                        </div>
                        <div className="grid gap-3 sm:grid-cols-3">
                            <div className="space-y-1.5 sm:col-span-3">
                                <Label htmlFor="sla-business-timezone">{t('Timezone')}</Label>
                                <Input
                                    id="sla-business-timezone"
                                    value={businessHours.timezone}
                                    disabled={!canEditProjectConfig || !businessHours.enabled}
                                    placeholder="Europe/Zurich"
                                    onChange={e => setBusinessHours({ timezone: e.target.value.trim() })}
                                />
                            </div>
                            <div className="space-y-1.5">
                                <Label htmlFor="sla-business-start">{t('Start')}</Label>
                                <Input
                                    id="sla-business-start"
                                    type="time"
                                    value={businessHours.start}
                                    disabled={!canEditProjectConfig || !businessHours.enabled}
                                    onChange={e => setBusinessHours({ start: e.target.value })}
                                />
                            </div>
                            <div className="space-y-1.5">
                                <Label htmlFor="sla-business-end">{t('End')}</Label>
                                <Input
                                    id="sla-business-end"
                                    type="time"
                                    value={businessHours.end}
                                    disabled={!canEditProjectConfig || !businessHours.enabled}
                                    onChange={e => setBusinessHours({ end: e.target.value })}
                                />
                            </div>
                            <div className="space-y-1.5">
                                <Label>{t('Days')}</Label>
                                <div className="flex flex-wrap gap-1.5">
                                    {BUSINESS_DAY_OPTIONS.map(day => {
                                        const selected = businessHours.days.includes(day.value);
                                        return (
                                            <Button
                                                key={day.value}
                                                type="button"
                                                size="sm"
                                                variant={selected ? 'default' : 'outline'}
                                                className="h-9 px-2 text-xs"
                                                aria-pressed={selected}
                                                disabled={!canEditProjectConfig || !businessHours.enabled}
                                                onClick={() => toggleBusinessDay(day.value)}
                                            >
                                                {t(day.label)}
                                            </Button>
                                        );
                                    })}
                                </div>
                            </div>
                        </div>
                    </div>
                    <div className="col-span-2 space-y-1.5">
                        <Label htmlFor="defaultAssigneeEmail">{t('Default ticket assignee')}</Label>
                        <Input
                            id="defaultAssigneeEmail"
                            type="email"
                            value={defaultAssigneeEmail}
                            disabled={!canEditProjectConfig}
                            placeholder="agent@example.com"
                            onChange={e => setSlaPolicy(policy => ({
                                ...policy,
                                metadata: {
                                    ...policy.metadata,
                                    defaultAssigneeEmail: e.target.value.trim(),
                                },
                            }))}
                        />
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="defaultQueueKey">{t('Default queue key')}</Label>
                        <Input
                            id="defaultQueueKey"
                            value={defaultQueueKey}
                            disabled={!canEditProjectConfig}
                            placeholder="support"
                            onChange={e => setSlaPolicy(policy => ({
                                ...policy,
                                metadata: {
                                    ...policy.metadata,
                                    defaultQueueKey: e.target.value.trim(),
                                },
                            }))}
                        />
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="defaultQueueName">{t('Default queue name')}</Label>
                        <Input
                            id="defaultQueueName"
                            value={defaultQueueName}
                            disabled={!canEditProjectConfig}
                            placeholder="Support"
                            onChange={e => setSlaPolicy(policy => ({
                                ...policy,
                                metadata: {
                                    ...policy.metadata,
                                    defaultQueueName: e.target.value.trim(),
                                },
                            }))}
                        />
                    </div>
                    <div className="col-span-2 space-y-3 border-t pt-3" data-custom-fields-settings>
                        <div className="flex items-center justify-between gap-3">
                            <div>
                                <div className="text-sm font-medium">{t('Ticket custom fields')}</div>
                                <p className="mt-0.5 text-xs text-muted-foreground">
                                    {t('Define structured attributes agents can fill on each support ticket.')}
                                </p>
                            </div>
                            <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                disabled={!canEditProjectConfig}
                                onClick={addCustomFieldDefinition}
                            >
                                <Plus className="size-4" />
                                {t('Add field')}
                            </Button>
                        </div>
                        {customFieldDefinitions.length === 0 ? (
                            <div className="rounded-md border border-dashed px-3 py-4 text-sm text-muted-foreground">
                                {t('No custom fields yet.')}
                            </div>
                        ) : (
                            <div className="space-y-3">
                                {customFieldDefinitions.map((field, index) => (
                                    <div key={`${field.key}-${index}`} className="rounded-md border p-3">
                                        <div className="grid gap-3 sm:grid-cols-2">
                                            <div className="space-y-1.5">
                                                <Label htmlFor={`custom-field-label-${index}`}>{t('Label')}</Label>
                                                <Input
                                                    id={`custom-field-label-${index}`}
                                                    value={field.label}
                                                    disabled={!canEditProjectConfig}
                                                    onChange={e => {
                                                        const label = e.target.value;
                                                        updateCustomFieldDefinition(index, {
                                                            label,
                                                            key: field.key.startsWith('field_') ? customFieldKey(label) || field.key : field.key,
                                                        });
                                                    }}
                                                />
                                            </div>
                                            <div className="space-y-1.5">
                                                <Label htmlFor={`custom-field-key-${index}`}>{t('Key')}</Label>
                                                <Input
                                                    id={`custom-field-key-${index}`}
                                                    value={field.key}
                                                    disabled={!canEditProjectConfig}
                                                    onChange={e => updateCustomFieldDefinition(index, { key: customFieldKey(e.target.value) })}
                                                />
                                            </div>
                                            <div className="space-y-1.5">
                                                <Label>{t('Type')}</Label>
                                                <Select
                                                    value={field.type}
                                                    disabled={!canEditProjectConfig}
                                                    onValueChange={value => updateCustomFieldDefinition(index, {
                                                        type: value as SupportCustomFieldType,
                                                        options: value === 'select' ? field.options : [],
                                                    })}
                                                >
                                                    <SelectTrigger>
                                                        <SelectValue />
                                                    </SelectTrigger>
                                                    <SelectContent>
                                                        {CUSTOM_FIELD_TYPES.map(type => (
                                                            <SelectItem key={type} value={type}>{t(type)}</SelectItem>
                                                        ))}
                                                    </SelectContent>
                                                </Select>
                                            </div>
                                            <div className="flex items-end justify-between gap-3">
                                                <div className="flex items-center gap-2 pb-2">
                                                    <Switch
                                                        checked={field.required}
                                                        disabled={!canEditProjectConfig}
                                                        onCheckedChange={required => updateCustomFieldDefinition(index, { required })}
                                                    />
                                                    <Label>{t('Required')}</Label>
                                                </div>
                                                <Button
                                                    type="button"
                                                    size="icon"
                                                    variant="ghost"
                                                    aria-label={t('Remove field')}
                                                    disabled={!canEditProjectConfig}
                                                    onClick={() => removeCustomFieldDefinition(index)}
                                                >
                                                    <Trash2 className="size-4" />
                                                </Button>
                                            </div>
                                            {field.type === 'select' && (
                                                <div className="space-y-1.5 sm:col-span-2">
                                                    <Label htmlFor={`custom-field-options-${index}`}>{t('Options')}</Label>
                                                    <Input
                                                        id={`custom-field-options-${index}`}
                                                        value={field.options.join(', ')}
                                                        disabled={!canEditProjectConfig}
                                                        placeholder={t('Bug, Billing, Feature request')}
                                                        onChange={e => updateCustomFieldDefinition(index, {
                                                            options: e.target.value.split(',').map(option => option.trim()).filter(Boolean),
                                                        })}
                                                    />
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
                <p className="text-xs text-muted-foreground">
                    {t('Defaults are 240 minutes for first response and 2880 minutes for resolution. New issues use the current policy; existing issue clocks are not rewritten.')}
                </p>
                <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-3">
                    <div className="min-w-0">
                        <div className="text-sm font-medium">{t('SLA breach scan')}</div>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                            {t('Find overdue pending SLA events, notify owners, and trigger SLA automation rules.')}
                        </p>
                        {lastSlaRun && (
                            <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
                                <span>{t('Processed')}: {lastSlaRun.processed}</span>
                                <span>{t('Escalated')}: {lastSlaRun.escalated}</span>
                                <span>{t('Skipped')}: {lastSlaRun.skipped}</span>
                                <span>{t('Failed')}: {lastSlaRun.failed}</span>
                            </div>
                        )}
                    </div>
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={!canEditProjectConfig || runningSlaEscalation}
                        onClick={() => void runSlaEscalationScan()}
                    >
                        {runningSlaEscalation ? <Loader className="size-4 animate-spin" /> : <AlertCircle className="size-4" />}
                        {t('Run SLA scan')}
                    </Button>
                </div>
            </div>

            {/* ── Security Override ── */}
            <div className="space-y-4 rounded-lg border p-4">
                <div className="flex items-center justify-between gap-4">
                    <div>
                        <h3 className="text-sm font-semibold">{t('Security')}</h3>
                        <p className="text-xs text-muted-foreground mt-0.5">
                            {t('Override the organisation-level security defaults for this project.')}
                        </p>
                    </div>
                    <Switch
                        checked={config.useCustomSecurity}
                        disabled={!canEditProjectConfig}
                        onCheckedChange={v => setConfig(c => ({ ...c, useCustomSecurity: v }))}
                    />
                </div>
                <div className="flex items-center justify-between gap-4 border-t pt-4">
                    <div>
                        <h4 className="text-sm font-medium">{t('Phishing monitoring')}</h4>
                        <p className="text-xs text-muted-foreground mt-0.5">
                            {t('Show an add-in warning when an email contains phishing indicators.')}
                        </p>
                    </div>
                    <Switch
                        checked={effectiveSecurity.phishingMonitoringEnabled}
                        disabled={!canEditProjectConfig || !config.useCustomSecurity}
                        onCheckedChange={v => setConfig(c => ({ ...c, phishingMonitoringEnabled: v }))}
                    />
                </div>
                <div className="flex items-center justify-between gap-4 border-t pt-4">
                    <div>
                        <h4 className="text-sm font-medium">{t('Prompt injection monitoring')}</h4>
                        <p className="text-xs text-muted-foreground mt-0.5">
                            {t('Show an add-in warning when an email tries to manipulate the agent or contains hidden instructions.')}
                        </p>
                    </div>
                    <Switch
                        checked={effectiveSecurity.promptInjectionMonitoringEnabled}
                        disabled={!canEditProjectConfig || !config.useCustomSecurity}
                        onCheckedChange={v => setConfig(c => ({ ...c, promptInjectionMonitoringEnabled: v }))}
                    />
                </div>
                {!config.useCustomSecurity && (
                    <p className="border-t pt-3 text-xs text-muted-foreground">
                        {t('Using organisation settings. Enable override to change these warnings for this project.')}
                    </p>
                )}
            </div>

            {/* ── Organisation Identity Override ── */}
            <div className="space-y-4 rounded-lg border p-4">
                <div className="flex items-center justify-between">
                    <div>
                        <h3 className="text-sm font-semibold">{t('Organisation identity')}</h3>
                        <p className="text-xs text-muted-foreground mt-0.5">
                            {t('Override the org-level name and description for this project.')}
                        </p>
                    </div>
                    <Switch
                        checked={config.useCustomOrg}
                        disabled={!canEditProjectConfig}
                        onCheckedChange={v => setConfig(c => ({ ...c, useCustomOrg: v }))}
                    />
                </div>
                {config.useCustomOrg && (
                    <div className="space-y-3 border-t pt-4">
                        <div className="space-y-1.5">
                            <Label htmlFor="orgName">{t('Organisation name')}</Label>
                            <Input
                                id="orgName"
                                value={config.orgName}
                                disabled={!canEditProjectConfig}
                                onChange={e => setConfig(c => ({ ...c, orgName: e.target.value }))}
                                placeholder="My Organisation"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="orgDescription">{t('Organisation description')}</Label>
                            <Textarea
                                id="orgDescription"
                                value={config.orgDescription}
                                disabled={!canEditProjectConfig}
                                onChange={e => setConfig(c => ({ ...c, orgDescription: e.target.value }))}
                                placeholder={t('Describe what the organisation does...')}
                                rows={4}
                            />
                        </div>
                    </div>
                )}
            </div>

            {/* ── LLM Provider Override ── */}
            <div className="space-y-4 rounded-lg border p-4">
                <div className="flex items-center justify-between">
                    <div>
                        <h3 className="text-sm font-semibold">{t('LLM Provider')}</h3>
                        <p className="text-xs text-muted-foreground mt-0.5">
                            {t('Override the org-level LLM provider for this project.')}
                        </p>
                    </div>
                    <Switch
                        checked={config.useCustomLlm}
                        disabled={!canEditProjectConfig}
                        onCheckedChange={v => setConfig(c => ({ ...c, useCustomLlm: v }))}
                    />
                </div>
                {config.useCustomLlm && (
                    <div className="space-y-3 border-t pt-4">
                        <Tabs
                            value={config.llmProvider}
                            onValueChange={v => {
                                if (canEditProjectConfig) setConfig(c => ({ ...c, llmProvider: v as 'gemini' | 'custom' }));
                            }}
                        >
                            <TabsList>
                                <TabsTrigger value="gemini" disabled={!canEditProjectConfig}>Gemini</TabsTrigger>
                                <TabsTrigger value="custom" disabled={!canEditProjectConfig}>Custom</TabsTrigger>
                            </TabsList>

                            {/* Gemini tab */}
                            <TabsContent value="gemini" className="space-y-3 pt-1">
                                <div className="space-y-1.5">
                                    <Label htmlFor="llmModel">{t('Model')}</Label>
                                    <div className="flex gap-2">
                                        <Input
                                            id="llmModel"
                                            value={config.llmModel}
                                            disabled={!canEditProjectConfig}
                                            onChange={e => setConfig(c => ({ ...c, llmModel: e.target.value }))}
                                            placeholder="gemini-3-flash-preview"
                                            list="known-gemini-models"
                                            className="flex-1"
                                        />
                                        <datalist id="known-gemini-models">
                                            {KNOWN_GEMINI_MODELS.map(m => <option key={m} value={m} />)}
                                        </datalist>
                                    </div>
                                    <p className="text-xs text-muted-foreground">
                                        Any Gemini model ID. Suggestions: {KNOWN_GEMINI_MODELS.join(', ')}.
                                    </p>
                                </div>

                                <div className="space-y-1.5">
                                    <Label htmlFor="geminiApiKey">{t('API Key')}</Label>
                                    <div className="flex gap-2">
                                        <Input
                                            id="geminiApiKey"
                                            type={showApiKey ? 'text' : 'password'}
                                            value={config.llmApiKey}
                                            disabled={!canEditProjectConfig}
                                            onChange={e => setConfig(c => ({ ...c, llmApiKey: e.target.value }))}
                                            placeholder={t('Project-specific Google AI API key')}
                                            className="flex-1 font-mono text-sm"
                                        />
                                        <Button
                                            type="button" variant="outline" size="icon"
                                            className="shrink-0"
                                            disabled={!canEditProjectConfig}
                                            onClick={() => setShowApiKey(v => !v)}
                                        >
                                            {showApiKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                                        </Button>
                                    </div>
                                    <p className="text-xs text-muted-foreground">
                                        {t('Google AI API key for this project. Leave blank to inherit the organisation-level LLM settings.')}
                                    </p>
                                </div>
                            </TabsContent>

                            {/* Custom (OpenAI-compatible) tab */}
                            <TabsContent value="custom" className="space-y-3 pt-1">
                                <div className="rounded-md bg-muted/50 border px-3 py-2 text-xs text-muted-foreground">
                                    {t('Connect to any OpenAI-compatible API gateway (e.g. Azure OpenAI, Ollama, vLLM, LiteLLM, or your own proxy).')}
                                </div>

                                <div className="space-y-1.5">
                                    <Label htmlFor="customBaseUrl">{t('Base URL')}</Label>
                                    <Input
                                        id="customBaseUrl"
                                        value={config.llmCustomBaseUrl}
                                        disabled={!canEditProjectConfig}
                                        onChange={e => setConfig(c => ({ ...c, llmCustomBaseUrl: e.target.value }))}
                                        placeholder="https://api.openai.com/v1"
                                        className="font-mono text-sm"
                                    />
                                    <p className="text-xs text-muted-foreground">
                                        {t('The base URL of your OpenAI-compatible endpoint (without /chat/completions).')}
                                    </p>
                                </div>

                                <div className="space-y-1.5">
                                    <Label htmlFor="customModel">{t('Model')}</Label>
                                    <Input
                                        id="customModel"
                                        value={config.llmCustomModel}
                                        disabled={!canEditProjectConfig}
                                        onChange={e => setConfig(c => ({ ...c, llmCustomModel: e.target.value }))}
                                        placeholder="gpt-4o"
                                        className="font-mono text-sm"
                                    />
                                </div>

                                <div className="space-y-1.5">
                                    <Label htmlFor="customApiKey">{t('API Key')}</Label>
                                    <div className="flex gap-2">
                                        <Input
                                            id="customApiKey"
                                            type={showApiKey ? 'text' : 'password'}
                                            value={config.llmApiKey}
                                            disabled={!canEditProjectConfig}
                                            onChange={e => setConfig(c => ({ ...c, llmApiKey: e.target.value }))}
                                            placeholder="sk-..."
                                            className="flex-1 font-mono text-sm"
                                        />
                                        <Button
                                            type="button" variant="outline" size="icon"
                                            className="shrink-0"
                                            disabled={!canEditProjectConfig}
                                            onClick={() => setShowApiKey(v => !v)}
                                        >
                                            {showApiKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                                        </Button>
                                    </div>
                                </div>
                            </TabsContent>
                        </Tabs>
                    </div>
                )}
            </div>

            {/* ── Project Secrets ── */}
            <div id="project-secrets">
                {canManageProjectSecrets ? (
                    <SecretsEditor
                        title={t('Project secrets')}
                        description={t('Project-specific secrets that override organisation-wide values. Use these for API keys and tokens referenced in tool configurations.')}
                        load={() => api.getProjectSecrets(projectId)}
                        save={(secrets) => api.updateProjectSecrets(projectId, secrets)}
                    />
                ) : (
                    <div className="rounded-lg border p-4 space-y-2">
                        <h3 className="text-base font-semibold">{t('Project secrets')}</h3>
                        <p className="text-sm text-muted-foreground">
                            {t('Project-specific secrets are available in this settings page for accounts with project-secret management permission.')}
                        </p>
                        <p className="text-xs text-muted-foreground">
                            {t('Reference secrets in customer identification headers, body, or URL as')}{' '}
                            <code className="bg-muted px-1 rounded">{'{KEY_NAME}'}</code>.
                        </p>
                    </div>
                )}
            </div>

            {manifestSection}
        </div>
    );
};
