import { useCallback, useEffect, useState } from 'react';
import { Eye, EyeOff, Loader, Save, ShieldCheck, ShieldAlert, ShieldX } from 'lucide-react';
import { toast } from 'sonner';

import { api } from '@/api/endpoints';
import type { TenantLlmProvider, TenantSettings, LicenseStatus } from '@/api/endpoints';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { SecretsEditor } from '@/components/secrets-editor';
import { settings as appSettings } from '@/settings';
import { useTopBar } from '@/TopBarContext';
import { useI18n } from '@/lib/i18n-context';

interface OrgSettingsProps {
    /** Called after a successful save so the parent can refresh cached values. */
    onSettingsChanged?: () => void;
    isDemoAccount?: boolean;
}

const KNOWN_GEMINI_MODELS = [
    'gemini-3-flash-preview',
    'gemini-2.5-flash',
    'gemini-2.5-pro',
    'gemini-2.0-flash',
    'gemini-1.5-pro',
];

const DEFAULT_ADDIN_PRIMARY_COLOR = '#18181B';
const HEX_COLOR_RE = /^#[0-9A-Fa-f]{6}$/;
const DEFAULT_LLM_PROVIDER: TenantLlmProvider = appSettings.isSaas ? 'managed' : 'gemini';
type OrgLlmMode = 'managed' | 'byok';

export const OrgSettings = ({ onSettingsChanged, isDemoAccount = false }: OrgSettingsProps) => {
    const [settings, setSettings] = useState<TenantSettings>({
        supportEmail: '',
        feedbackEmail: '',
        orgName: '',
        orgDescription: '',
        addinPrimaryColor: '',
        llmProvider: DEFAULT_LLM_PROVIDER,
        llmModel: '',
        llmApiKey: '',
        llmCustomBaseUrl: '',
        llmCustomModel: '',
        phishingMonitoringEnabled: false,
        promptInjectionMonitoringEnabled: false,
        allowSignups: false,
    });
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [showApiKey, setShowApiKey] = useState(false);
    const [licenseStatus, setLicenseStatus] = useState<LicenseStatus | null>(null);
    const { setActions } = useTopBar();
    const { t } = useI18n();

    const load = useCallback(() => {
        void api.getTenantSettings().then(res => {
            if (res.data) {
                setSettings({
                    supportEmail: res.data.supportEmail ?? '',
                    feedbackEmail: res.data.feedbackEmail ?? '',
                    orgName: res.data.orgName ?? '',
                    orgDescription: res.data.orgDescription ?? '',
                    addinPrimaryColor: res.data.addinPrimaryColor ?? '',
                    llmProvider: res.data.llmProvider || DEFAULT_LLM_PROVIDER,
                    llmModel: res.data.llmModel ?? '',
                    llmApiKey: res.data.llmApiKey ?? '',
                    llmCustomBaseUrl: res.data.llmCustomBaseUrl ?? '',
                    llmCustomModel: res.data.llmCustomModel ?? '',
                    phishingMonitoringEnabled: res.data.phishingMonitoringEnabled ?? false,
                    promptInjectionMonitoringEnabled: res.data.promptInjectionMonitoringEnabled ?? false,
                    allowSignups: res.data.allowSignups ?? false,
                });
            }
            setLoading(false);
        });
        // Load license status (on-prem only)
        if (!appSettings.isSaas) {
            void api.getLicenseStatus().then(res => {
                if (res.data?.required) setLicenseStatus(res.data);
            });
        }
    }, []);

    useEffect(() => {
        load();
    }, [load]);

    const update = (patch: Partial<TenantSettings>) => {
        setSettings(prev => ({ ...prev, ...patch }));
    };

    const llmMode: OrgLlmMode = settings.llmProvider === 'managed' ? 'managed' : 'byok';

    const updateLlmMode = (mode: OrgLlmMode) => {
        if (mode === 'managed') {
            update({
                llmProvider: 'managed',
                llmModel: '',
                llmApiKey: '',
                llmCustomBaseUrl: '',
                llmCustomModel: '',
            });
            return;
        }
        update({
            llmProvider: 'gemini',
            llmCustomBaseUrl: '',
            llmCustomModel: '',
        });
    };

    const handleSave = useCallback(async () => {
        const trimmedColor = settings.addinPrimaryColor.trim();
        if (trimmedColor && !HEX_COLOR_RE.test(trimmedColor)) {
            toast.error(t('Use color format #RRGGBB'));
            return;
        }
        setSaving(true);
        const llmSettings = llmMode === 'managed'
            ? {
                llmProvider: 'managed' as const,
                llmModel: '',
                llmApiKey: '',
                llmCustomBaseUrl: '',
                llmCustomModel: '',
            }
            : {
                llmProvider: 'gemini' as const,
                llmModel: settings.llmModel,
                llmApiKey: settings.llmApiKey,
                llmCustomBaseUrl: '',
                llmCustomModel: '',
            };
        const res = await api.updateTenantSettings({
            ...settings,
            ...llmSettings,
            addinPrimaryColor: trimmedColor,
        });
        if (res.error) {
            toast.error(res.error);
        } else {
            toast.success(t('Organisation settings saved'));
            onSettingsChanged?.();
        }
        setSaving(false);
    }, [llmMode, onSettingsChanged, settings, t]);

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
            <div className="flex items-center gap-2 text-sm text-muted-foreground p-8">
                <Loader className="size-4 animate-spin" /> {t('Loading')}...
            </div>
        );
    }

    return (
        <div className="space-y-6 max-w-lg mx-auto">
            <div>
                <h2 className="text-lg font-semibold mb-1">{t('Organisation Settings')}</h2>
                <p className="text-sm text-muted-foreground">
                    {isDemoAccount
                        ? t('Demo workspaces can change the same organisation-level configuration as a normal account.')
                        : t('Configure organisation-wide defaults. Projects inherit these unless they enable custom overrides.')}
                </p>
            </div>

            {/* ── License Status (on-prem only) ── */}
            {licenseStatus && (
                <Card>
                    <CardHeader>
                        <div className="flex items-center gap-2">
                            {licenseStatus.valid ? (
                                <ShieldCheck className="size-5 text-green-600" />
                            ) : licenseStatus.withinGracePeriod ? (
                                <ShieldAlert className="size-5 text-yellow-600" />
                            ) : (
                                <ShieldX className="size-5 text-red-600" />
                            )}
                            <h3 className="text-base font-semibold">{t('License')}</h3>
                            <Badge variant={licenseStatus.valid ? 'default' : licenseStatus.withinGracePeriod ? 'secondary' : 'destructive'}>
                                {licenseStatus.valid ? t('Active') : licenseStatus.withinGracePeriod ? t('Grace Period') : t('Invalid')}
                            </Badge>
                        </div>
                    </CardHeader>
                    <CardContent>
                        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                            {licenseStatus.maxUsers != null && (
                                <>
                                    <span className="text-muted-foreground">{t('Seats')}</span>
                                    <span>{licenseStatus.currentUsers ?? '?'} / {licenseStatus.maxUsers}</span>
                                </>
                            )}
                            <span className="text-muted-foreground">{t('Expires')}</span>
                            <span>{licenseStatus.expiresAt ? new Date(licenseStatus.expiresAt).toLocaleDateString() : t('No expiry')}</span>
                            {licenseStatus.lastCheck != null && licenseStatus.lastCheck > 0 && (
                                <>
                                    <span className="text-muted-foreground">{t('Last validated')}</span>
                                    <span>{new Date(licenseStatus.lastCheck * 1000).toLocaleString()}</span>
                                </>
                            )}
                        </div>
                        {licenseStatus.message && !licenseStatus.valid && (
                            <p className="text-xs text-red-600 mt-3">{licenseStatus.message}</p>
                        )}
                    </CardContent>
                </Card>
            )}

            {/* ── Org Identity ── */}
            <Card>
                <CardHeader>
                    <h3 className="text-base font-semibold">{t('Organisation identity')}</h3>
                    <p className="text-sm text-muted-foreground">
                        {t('Injected into every agent prompt as context. Projects inherit these values by default.')}
                    </p>
                </CardHeader>
                <CardContent className="space-y-4">
                    <div className="space-y-1.5">
                        <Label htmlFor="orgName">{t('Organisation name')}</Label>
                            <Input
                                id="orgName"
                                value={settings.orgName}
                                onChange={e => update({ orgName: e.target.value })}
                                placeholder={t('My Organisation')}
                            />
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="orgDescription">{t('Organisation description')}</Label>
                            <Textarea
                                id="orgDescription"
                                value={settings.orgDescription}
                                onChange={e => update({ orgDescription: e.target.value })}
                                placeholder={t('Describe what the organisation does and who its customers are...')}
                                rows={4}
                        />
                    </div>
                </CardContent>
            </Card>

            {/* ── Add-in Branding ── */}
            <Card>
                <CardHeader>
                    <h3 className="text-base font-semibold">{t('Add-in branding')}</h3>
                    <p className="text-sm text-muted-foreground">
                        {t('Primary color used for main buttons inside the Outlook add-in.')}
                    </p>
                </CardHeader>
                <CardContent className="space-y-4">
                    <div className="space-y-1.5">
                        <Label htmlFor="addinPrimaryColor">{t('Primary button color')}</Label>
                        <div className="flex items-center gap-2">
                            <Input
                                id="addinPrimaryColorPicker"
                                type="color"
                                value={HEX_COLOR_RE.test(settings.addinPrimaryColor) ? settings.addinPrimaryColor : DEFAULT_ADDIN_PRIMARY_COLOR}
                                onChange={e => update({ addinPrimaryColor: e.target.value.toUpperCase() })}
                                className="h-9 w-12 shrink-0 cursor-pointer p-1"
                                aria-label={t('Pick primary button color')}
                            />
                            <Input
                                id="addinPrimaryColor"
                                value={settings.addinPrimaryColor}
                                onChange={e => update({ addinPrimaryColor: e.target.value })}
                                placeholder={DEFAULT_ADDIN_PRIMARY_COLOR}
                                className="font-mono"
                            />
                            <Button
                                type="button"
                                variant="outline"
                                onClick={() => update({ addinPrimaryColor: '' })}
                            >
                                {t('Reset')}
                            </Button>
                        </div>
                        <p className="text-xs text-muted-foreground">
                            {t('Leave empty to use the default Mantly color.')}
                        </p>
                    </div>
                    <div className="flex items-center justify-between gap-3 rounded-md border bg-muted/30 px-3 py-3">
                        <span className="text-sm text-muted-foreground">{t('Preview')}</span>
                        <Button
                            type="button"
                            style={{
                                backgroundColor: HEX_COLOR_RE.test(settings.addinPrimaryColor)
                                    ? settings.addinPrimaryColor
                                    : DEFAULT_ADDIN_PRIMARY_COLOR,
                                color: '#fff',
                            }}
                        >
                            {t('Primary action')}
                        </Button>
                    </div>
                </CardContent>
            </Card>

            {/* ── LLM Provider ── */}
            <Card>
                <CardHeader>
                    <h3 className="text-base font-semibold">{t('LLM Provider')}</h3>
                    <p className="text-sm text-muted-foreground">
                        {t('Default language model for all projects. Projects can override this in their own settings.')}
                    </p>
                </CardHeader>
                <CardContent className="space-y-3">
                    <Tabs
                        value={appSettings.isSaas ? llmMode : 'byok'}
                        onValueChange={v => updateLlmMode(v as OrgLlmMode)}
                    >
                        <TabsList className={appSettings.isSaas ? 'grid w-full grid-cols-2' : 'grid w-full grid-cols-1'}>
                            {appSettings.isSaas && <TabsTrigger value="managed">{t('Managed')}</TabsTrigger>}
                            <TabsTrigger value="byok">{t('BYOK')}</TabsTrigger>
                        </TabsList>

                        {/* Managed tab */}
                        {appSettings.isSaas && (
                            <TabsContent value="managed" className="space-y-3 pt-1">
                                <div className="rounded-md bg-muted/50 border px-3 py-2 text-xs text-muted-foreground">
                                    {t('Use the Mantly-managed LLM key. No provider API key is required here.')}
                                </div>
                                <p className="text-xs text-muted-foreground">
                                    {t('Mantly-managed LLM usage is billed at provider cost x 1.2. BYOK LLM usage has no surcharge.')}
                                </p>
                            </TabsContent>
                        )}

                        {/* BYOK tab */}
                        <TabsContent value="byok" className="space-y-3 pt-1">
                            <div className="rounded-md bg-muted/50 border px-3 py-2 text-xs text-muted-foreground">
                                {t('Use your own LLM key. BYOK usage has no Mantly surcharge.')}
                            </div>
                            <div className="space-y-1.5">
                                <Label htmlFor="llmModel">{t('Model')}</Label>
                                <div className="flex gap-2">
                                    <Input
                                        id="llmModel"
                                        value={settings.llmModel}
                                        onChange={e => update({ llmModel: e.target.value })}
                                        placeholder="gemini-3-flash-preview"
                                        list="known-gemini-models"
                                        className="flex-1"
                                    />
                                    <datalist id="known-gemini-models">
                                        {KNOWN_GEMINI_MODELS.map(m => <option key={m} value={m} />)}
                                    </datalist>
                                </div>
                                <p className="text-xs text-muted-foreground">
                                    {t('Any Gemini model ID. Suggestions: {models}.', { models: KNOWN_GEMINI_MODELS.join(', ') })}
                                </p>
                            </div>

                            <div className="space-y-1.5">
                                <Label htmlFor="geminiApiKey">{t('API Key')}</Label>
                                <div className="flex gap-2">
                                    <Input
                                        id="geminiApiKey"
                                        type={showApiKey ? 'text' : 'password'}
                                        value={settings.llmApiKey}
                                        onChange={e => update({ llmApiKey: e.target.value })}
                                        placeholder={t('Your Google AI API key')}
                                        className="flex-1 font-mono text-sm"
                                    />
                                    <Button
                                        type="button" variant="outline" size="icon"
                                        className="shrink-0"
                                        onClick={() => setShowApiKey(v => !v)}
                                    >
                                        {showApiKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                                    </Button>
                                </div>
                                <p className="text-xs text-muted-foreground">
                                    {t('Google AI API key. Required - get one from')} <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer" className="underline">Google AI Studio</a>.
                                </p>
                            </div>
                        </TabsContent>
                    </Tabs>
                </CardContent>
            </Card>

            {/* ── Security ── */}
            <Card>
                <CardHeader>
                    <h3 className="text-base font-semibold">{t('Security')}</h3>
                    <p className="text-sm text-muted-foreground">
                        {t('Default warning-only risk banners for all projects. Projects can override this in their own settings.')}
                    </p>
                </CardHeader>
                <CardContent className="space-y-4">
                    <div className="flex items-center justify-between gap-4">
                        <div>
                            <h4 className="text-sm font-medium">{t('Phishing monitoring')}</h4>
                            <p className="text-xs text-muted-foreground mt-0.5">
                                {t('Show an add-in warning when an email contains phishing indicators.')}
                            </p>
                        </div>
                        <Switch
                            checked={settings.phishingMonitoringEnabled}
                            onCheckedChange={v => update({ phishingMonitoringEnabled: v })}
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
                            checked={settings.promptInjectionMonitoringEnabled}
                            onCheckedChange={v => update({ promptInjectionMonitoringEnabled: v })}
                        />
                    </div>
                </CardContent>
            </Card>

            {/* ── Contact Emails (on-prem only) ── */}
            {!appSettings.isSaas && (
                <Card>
                    <CardHeader>
                        <h3 className="text-base font-semibold">{t('Contact emails')}</h3>
                        <p className="text-sm text-muted-foreground">
                            {t('These emails appear as Support and Feedback links in the sidebar for all users.')}
                        </p>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        <div className="space-y-1.5">
                            <Label htmlFor="supportEmail">{t('Support email')}</Label>
                            <Input
                                id="supportEmail"
                                type="email"
                                value={settings.supportEmail}
                                onChange={e => update({ supportEmail: e.target.value })}
                                placeholder="support@example.com"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="feedbackEmail">{t('Feedback email')}</Label>
                            <Input
                                id="feedbackEmail"
                                type="email"
                                value={settings.feedbackEmail}
                                onChange={e => update({ feedbackEmail: e.target.value })}
                                placeholder="feedback@example.com"
                            />
                        </div>
                    </CardContent>
                </Card>
            )}

            {/* ── Allow Signups (on-prem only) ── */}
            {!appSettings.isSaas && (
                <Card>
                    <CardHeader>
                        <h3 className="text-base font-semibold">{t('User registration')}</h3>
                        <p className="text-sm text-muted-foreground">
                            {t('Allow new users to self-register via the login page. Registered users are automatically added to all existing projects as viewers.')}
                        </p>
                    </CardHeader>
                    <CardContent>
                        <div className="flex items-center gap-3">
                            <Switch
                                id="allowSignups"
                                checked={settings.allowSignups}
                                onCheckedChange={v => update({ allowSignups: v })}
                            />
                            <Label htmlFor="allowSignups" className="cursor-pointer">
                                {t('Allow signups')}
                            </Label>
                        </div>
                    </CardContent>
                </Card>
            )}

            {/* ── Secrets ── */}
            <SecretsEditor
                title={t('Secrets')}
                description={t('Organisation-wide secrets available to all projects. Use these for API keys and tokens referenced in tool configurations. Project-level secrets override these.')}
                load={() => api.getTenantSecrets()}
                save={(secrets) => api.updateTenantSecrets(secrets)}
            />

        </div>
    );
};
