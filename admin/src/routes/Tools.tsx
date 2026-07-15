import { useCallback, useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldSet } from '@/components/ui/field';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { AlertCircle, ExternalLink, Loader, Plus, Save, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';
import { api } from '@/api/endpoints';
import type { AdminConfigData, InputSchemaField, ToolConfig } from '@/api/endpoints';
import { Switch } from '@/components/ui/switch';
import { useTopBar } from '@/TopBarContext';
import { HintBanner } from '@/components/hint-banner';
import { useI18n } from '@/lib/i18n-context';

type Translate = (key: string, values?: Record<string, string | number>) => string;

// ── Types ─────────────────────────────────────────────────────────────────────

interface KVPair { key: string; value: string; }
type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH';

interface ToolForm {
    description: string;
    method: HttpMethod;
    urlTemplate: string;
    headers: KVPair[];
    body: KVPair[];
    envVars: string[];
    inputSchema: InputSchemaField[];
}

const EMPTY_FORM: ToolForm = {
    description: '',
    method: 'GET',
    urlTemplate: '',
    headers: [],
    body: [],
    envVars: [],
    inputSchema: [],
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function toolConfigToForm(tool: ToolConfig): ToolForm {
    return {
        description: tool.description,
        method: (tool.method?.toUpperCase() as HttpMethod) ?? 'GET',
        urlTemplate: tool.urlTemplate,
        headers: Object.entries(tool.headers ?? {}).map(([key, value]) => ({ key, value })),
        body: Object.entries(tool.body ?? {}).map(([key, value]) => ({ key, value })),
        envVars: tool.envVars ?? [],
        inputSchema: tool.inputSchema ?? [],
    };
}

function formToToolConfig(form: ToolForm): ToolConfig {
    return {
        name: 'customer-lookup',
        description: form.description,
        method: form.method,
        urlTemplate: form.urlTemplate,
        headers: Object.fromEntries(form.headers.filter(h => h.key).map(h => [h.key, h.value])),
        body: Object.fromEntries(form.body.filter(b => b.key).map(b => [b.key, b.value])),
        envVars: form.envVars,
        inputSchema: form.inputSchema,
    };
}

// ── KV editor ─────────────────────────────────────────────────────────────────

function KVEditor({
    rows,
    onChange,
    t,
    keyPlaceholder = 'Key',
    valuePlaceholder = 'Value',
    addLabel = 'Add row',
}: {
    rows: KVPair[];
    onChange: (rows: KVPair[]) => void;
    t: Translate;
    keyPlaceholder?: string;
    valuePlaceholder?: string;
    addLabel?: string;
}) {
    const update = (i: number, field: keyof KVPair, val: string) =>
        onChange(rows.map((r, idx) => idx === i ? { ...r, [field]: val } : r));
    const remove = (i: number) => onChange(rows.filter((_, idx) => idx !== i));
    const add = () => onChange([...rows, { key: '', value: '' }]);

    return (
        <FieldGroup className="gap-1.5">
            {rows.map((row, i) => (
                <div key={i} className="flex gap-2 items-center">
                    <Input
                        aria-label={t('Header name')}
                        value={row.key}
                        onChange={e => update(i, 'key', e.target.value)}
                        placeholder={t(keyPlaceholder)}
                        className="flex-1 text-sm font-mono"
                    />
                    <Input
                        aria-label={t('Header value')}
                        value={row.value}
                        onChange={e => update(i, 'value', e.target.value)}
                        placeholder={t(valuePlaceholder)}
                        className="flex-[2] text-sm"
                    />
                    <Button variant="ghost" size="icon" onClick={() => remove(i)}
                        className="text-muted-foreground hover:text-destructive shrink-0">
                        <X className="size-4" />
                    </Button>
                </div>
            ))}
            <Button variant="outline" size="sm" onClick={add} type="button">
                <Plus className="size-4" /> {t(addLabel)}
            </Button>
        </FieldGroup>
    );
}

function getPlaceholderParam(value: string): string {
    const match = value.match(/^\{([^}]+)\}$/);
    return match?.[1] ?? '';
}

function BodyParameterEditor({
    rows,
    onChange,
    parameters,
    t,
}: {
    rows: KVPair[];
    onChange: (rows: KVPair[]) => void;
    parameters: string[];
    t: Translate;
}) {
    const options = Array.from(new Set(['sender_email', ...parameters.filter(Boolean)]));
    const updateKey = (i: number, key: string) =>
        onChange(rows.map((r, idx) => idx === i ? { ...r, key } : r));
    const updateParam = (i: number, param: string) =>
        onChange(rows.map((r, idx) => idx === i ? { ...r, value: `{${param}}` } : r));
    const remove = (i: number) => onChange(rows.filter((_, idx) => idx !== i));
    const add = () => onChange([...rows, { key: '', value: `{${options[0]}}` }]);

    return (
        <FieldGroup className="gap-2">
            {rows.length > 0 && (
                <div className="grid grid-cols-[1fr_1fr_2rem] gap-2 items-center text-xs text-muted-foreground px-0.5">
                    <span>{t('Body key')}</span>
                    <span>{t('Input parameter')}</span>
                    <span />
                </div>
            )}
            {rows.map((row, i) => {
                const selected = getPlaceholderParam(row.value);
                const available = selected && !options.includes(selected)
                    ? [...options, selected]
                    : options;

                return (
                    <div key={i} className="grid grid-cols-[1fr_1fr_2rem] gap-2 items-center">
                        <Input
                            aria-label={t('Body key')}
                            value={row.key}
                            onChange={e => updateKey(i, e.target.value)}
                            placeholder="request_field"
                            className="text-sm font-mono"
                        />
                        <Select value={selected || options[0]} onValueChange={value => updateParam(i, value)}>
                            <SelectTrigger aria-label={t('Input parameter')}>
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {available.map(param => (
                                    <SelectItem key={param} value={param}>
                                        {param}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        <Button variant="ghost" size="icon" onClick={() => remove(i)}
                            className="w-8 text-muted-foreground hover:text-destructive shrink-0">
                            <X className="size-4" />
                        </Button>
                    </div>
                );
            })}
            <Button variant="outline" size="sm" onClick={add} type="button">
                <Plus className="size-4" /> {t('Add body parameter')}
            </Button>
        </FieldGroup>
    );
}

// ── Schema editor ─────────────────────────────────────────────────────────────

const FIELD_TYPES: InputSchemaField['type'][] = ['string', 'number', 'integer', 'boolean'];

function SchemaEditor({
    rows,
    onChange,
    t,
}: {
    rows: InputSchemaField[];
    onChange: (rows: InputSchemaField[]) => void;
    t: Translate;
}) {
    const update = <K extends keyof InputSchemaField>(i: number, field: K, val: InputSchemaField[K]) =>
        onChange(rows.map((r, idx) => idx === i ? { ...r, [field]: val } : r));
    const remove = (i: number) => onChange(rows.filter((_, idx) => idx !== i));
    const add = () => onChange([...rows, { key: '', description: '', type: 'string', default: '', required: true }]);

    return (
        <FieldGroup className="gap-2">
            {rows.length > 0 && (
                <div className="flex gap-2 items-center text-xs text-muted-foreground px-0.5">
                    <span className="flex-1">{t('Key')}</span>
                    <span className="flex-[2]">{t('Description')}</span>
                    <span className="w-28">{t('Type')}</span>
                    <span className="w-24">{t('Default')}</span>
                    <span className="w-16 text-center">{t('Required')}</span>
                    <span className="w-8" />
                </div>
            )}
            {rows.map((row, i) => (
                <div key={i} className="flex gap-2 items-center">
                    <Input
                        aria-label={t('Parameter key')}
                        value={row.key}
                        onChange={e => update(i, 'key', e.target.value)}
                        placeholder="param_name"
                        className="flex-1 text-sm font-mono"
                    />
                    <Input
                        aria-label={t('Parameter description')}
                        value={row.description}
                        onChange={e => update(i, 'description', e.target.value)}
                        placeholder={t('What the agent should fill in')}
                        className="flex-[2] text-sm"
                    />
                    <Select
                        value={row.type}
                        onValueChange={value => update(i, 'type', value as InputSchemaField['type'])}
                    >
                        <SelectTrigger className="w-28" aria-label={t('Parameter type')}>
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {FIELD_TYPES.map(t => (
                                <SelectItem key={t} value={t}>
                                    {t}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                    <Input
                        aria-label={t('Parameter default value')}
                        value={row.default ?? ''}
                        onChange={e => update(i, 'default', e.target.value)}
                        placeholder="–"
                        className="w-24 text-sm"
                    />
                    <div className="w-16 flex justify-center">
                        <Switch
                            aria-label={t('Parameter required')}
                            checked={row.required}
                            onCheckedChange={val => update(i, 'required', val)}
                        />
                    </div>
                    <Button variant="ghost" size="icon" onClick={() => remove(i)}
                        className="w-8 text-muted-foreground hover:text-destructive shrink-0">
                        <X className="size-4" />
                    </Button>
                </div>
            ))}
            <Button variant="outline" size="sm" onClick={add} type="button">
                <Plus className="size-4" /> {t('Add parameter')}
            </Button>
        </FieldGroup>
    );
}

// ── Main component ────────────────────────────────────────────────────────────

export const Tools = ({ projectId }: { projectId: string }) => {
    const { tenantId } = useParams();
    const { t } = useI18n();
    const [fullConfig, setFullConfig] = useState<AdminConfigData | null>(null);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [removing, setRemoving] = useState(false);

    const [form, setForm] = useState<ToolForm>(EMPTY_FORM);
    const [isConfigured, setIsConfigured] = useState(false);
    const [enabled, setEnabled] = useState(false);
    const [identityNotes, setIdentityNotes] = useState('');

    useEffect(() => {
        void api.getAdminConfig(projectId).then(res => {
            if (res.data) {
                setFullConfig(res.data);
                setIdentityNotes(res.data.identityNotes ?? '');
                if (res.data.tool) {
                    setForm(toolConfigToForm(res.data.tool));
                    setIsConfigured(true);
                    setEnabled(true);
                }
            } else {
                setLoadError(t('Could not reach the backend. Is it running?'));
            }
            setLoading(false);
        });
    }, [projectId, t]);

    const handleSave = useCallback(async () => {
        if (!form.urlTemplate.trim()) {
            toast.error(t('Endpoint is required'));
            return;
        }
        if (!fullConfig) return;
        setSaving(true);
        const tool = enabled ? formToToolConfig(form) : null;
        const res = await api.updateAdminConfig(projectId, { ...fullConfig, identityNotes, tool });
        if (res.error) {
            toast.error(t('Save failed: {error}', { error: res.error }));
        } else {
            toast.success(t(enabled ? 'Data source saved' : 'Data source disabled'));
            setIsConfigured(enabled);
            setFullConfig(c => c ? { ...c, identityNotes, tool } : c);
        }
        setSaving(false);
    }, [enabled, form, fullConfig, identityNotes, projectId, t]);

    const handleRemove = useCallback(async () => {
        if (!fullConfig) return;
        setRemoving(true);
        const res = await api.updateAdminConfig(projectId, { ...fullConfig, tool: null });
        if (res.error) {
            toast.error(t('Remove failed: {error}', { error: res.error }));
        } else {
            toast.success(t('Data source removed'));
            setForm(EMPTY_FORM);
            setIsConfigured(false);
            setFullConfig(c => c ? { ...c, tool: null } : c);
        }
        setRemoving(false);
    }, [fullConfig, projectId, t]);

    const METHODS: HttpMethod[] = ['GET', 'POST', 'PUT', 'PATCH'];
    const inputParameterKeys = form.inputSchema.map(field => field.key.trim()).filter(Boolean);

    // ── Top bar: inject enabled/disabled toggle ─────────────────────────────
    const { setActions } = useTopBar();

    useEffect(() => {
        setActions(
            <>
                <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setEnabled(prev => !prev)}
                    className="w-[7.5rem] justify-start text-muted-foreground"
                >
                    <span>{t(enabled ? 'Enabled' : 'Disabled')}</span>
                    <Switch checked={enabled} onCheckedChange={setEnabled} className="ml-auto pointer-events-none scale-75" />
                </Button>
                {isConfigured && (
                    <Button size="sm" variant="destructive" onClick={handleRemove} disabled={removing}>
                        {removing ? <Loader className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                        {t('Remove')}
                    </Button>
                )}
                <Button size="sm" onClick={handleSave} disabled={saving || loading}>
                    {saving ? <Loader className="size-4 animate-spin" /> : <Save className="size-4" />}
                    {t('Save')}
                </Button>
            </>
        );
        return () => setActions(null);
    }, [enabled, handleRemove, handleSave, isConfigured, loading, removing, saving, setActions, t]);

    return (
        <div className="space-y-6">
            <HintBanner storageKey="customer-identification" title={t('What are identity rules?')}>
                {t('Identity rules connect a sender to an account or contact before the agent triages the ticket. AI runbooks and workflow rules use that result.')}
            </HintBanner>

            {loadError && (
                <div className="rounded-md bg-destructive/10 border border-destructive/20 px-4 py-2 text-sm text-destructive flex items-center gap-2">
                    <AlertCircle className="size-4 shrink-0" />
                    {loadError}
                </div>
            )}

            {loading ? (
                <div className="flex items-center gap-2 text-muted-foreground text-sm py-8">
                    <Loader className="size-4 animate-spin" /> {t('Loading...')}
                </div>
            ) : (
                <FieldSet className={`rounded-lg border bg-white p-5 gap-5 transition-opacity ${!enabled ? 'opacity-40 pointer-events-none select-none' : ''}`}>

                    {/* Description */}
                    <Field>
                        <FieldLabel htmlFor="toolDesc">{t('Description')}</FieldLabel>
                        <Textarea
                            id="toolDesc"
                            value={form.description}
                            onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                            placeholder={t('Describe what this data source does and when the agent should use it.')}
                            rows={2}
                            className="text-sm"
                        />
                        <FieldDescription className="text-xs">{t('The agent reads this to decide when to call the data source.')}</FieldDescription>
                    </Field>

                    {/* Additional context */}
                    <Field>
                        <FieldLabel htmlFor="identityNotes">{t('Additional Context')}</FieldLabel>
                        <Textarea
                            id="identityNotes"
                            value={identityNotes}
                            onChange={e => setIdentityNotes(e.target.value)}
                            placeholder={t('Tell the agent how to interpret and summarize customer lookup results.')}
                            rows={3}
                            className="text-sm"
                        />
                        <FieldDescription className="text-xs">
                            {t('Used as extra instructions while matching the sender to an account.')}
                        </FieldDescription>
                    </Field>

                    {/* Input schema */}
                    <Field>
                        <FieldLabel>{t('Input Parameters')}</FieldLabel>
                        <FieldDescription className="text-xs">
                            {t('Parameters the agent fills in from the message and sends to the endpoint.')}
                        </FieldDescription>
                        <SchemaEditor
                            rows={form.inputSchema}
                            t={t}
                            onChange={rows => setForm(f => ({ ...f, inputSchema: rows }))}
                        />
                    </Field>

                    {/* Method */}
                    <Field>
                        <FieldLabel>{t('Method')}</FieldLabel>
                        <Tabs
                            value={form.method}
                            onValueChange={value => setForm(f => ({ ...f, method: value as HttpMethod }))}
                        >
                            <TabsList>
                                {METHODS.map(m => (
                                    <TabsTrigger
                                        key={m}
                                        value={m}
                                        className="font-mono text-xs"
                                    >
                                        {m}
                                    </TabsTrigger>
                                ))}
                            </TabsList>
                        </Tabs>
                    </Field>

                    {/* URL */}
                    <Field>
                        <FieldLabel htmlFor="toolUrl">{t('Endpoint')}</FieldLabel>
                        <Input
                            id="toolUrl"
                            value={form.urlTemplate}
                            onChange={e => setForm(f => ({ ...f, urlTemplate: e.target.value }))}
                            placeholder="https://api.example.com/customers?email={sender_email}"
                            className="font-mono text-sm"
                        />
                    </Field>

                    {/* Headers */}
                    <Field>
                        <FieldLabel>{t('Headers')}</FieldLabel>
                        <KVEditor
                            rows={form.headers}
                            t={t}
                            onChange={rows => setForm(f => ({ ...f, headers: rows }))}
                            keyPlaceholder="Header name"
                            valuePlaceholder="Value or {ENV_VAR}"
                            addLabel="Add header"
                        />
                    </Field>

                    {/* Body — POST/PUT/PATCH only */}
                    {form.method !== 'GET' && (
                        <Field>
                            <FieldLabel>{t('Body Parameters')}</FieldLabel>
                            <BodyParameterEditor
                                rows={form.body}
                                t={t}
                                onChange={rows => setForm(f => ({ ...f, body: rows }))}
                                parameters={inputParameterKeys}
                            />
                        </Field>
                    )}

                    {/* Secrets info */}
                    <div className="rounded-md bg-muted/50 border px-4 py-3 space-y-2">
                        <p className="text-sm font-medium">{t('Secrets')}</p>
                        <p className="text-xs text-muted-foreground">
                            {t('Reference secrets in headers, body, or URL as')}{' '}
                            <code className="bg-muted px-1 rounded">{'{KEY_NAME}'}</code>.
                            {' '}{t('Secrets are managed in your settings pages.')}
                        </p>
                        <div className="flex gap-3 text-xs">
                            {tenantId && (
                                <>
                                    <Link
                                        to={`/${tenantId}/org`}
                                        className="inline-flex items-center gap-1 text-primary hover:underline"
                                    >
                                        {t('Organisation Secrets')} <ExternalLink className="size-3" />
                                    </Link>
                                    <Link
                                        to={`/${tenantId}/${projectId}/settings`}
                                        className="inline-flex items-center gap-1 text-primary hover:underline"
                                    >
                                        {t('Project Secrets')} <ExternalLink className="size-3" />
                                    </Link>
                                </>
                            )}
                        </div>
                    </div>

                </FieldSet>
            )}
        </div>
    );
};
