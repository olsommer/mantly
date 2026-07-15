import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    ArrowLeft,
    ChevronDown,
    ChevronRight,
    CloudUpload,
    FileText,
    FlaskConical,
    Loader,
    Paperclip,
    Plus,
    Play,
    Save,
    Trash2,
    X,
} from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import {
    Breadcrumb,
    BreadcrumbItem,
    BreadcrumbLink,
    BreadcrumbList,
    BreadcrumbPage,
    BreadcrumbSeparator,
} from '@/components/ui/breadcrumb';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { api } from '@/api/endpoints';
import { cn } from '@/lib/utils';
import type {
    EvalCase,
    EvalEmailAttachment,
    EvalCaseInput,
    EvalRun,
    EvalRunDetail,
    EvalSet,
} from '@/api/endpoints';
import { useTopBar } from '@/TopBarContext';
import { useI18n } from '@/lib/i18n-context';
import type { Locale } from '@/lib/i18n-core';

// ── Score display helpers ─────────────────────────────────────────────────────

function scoreColor(score: number | null | undefined): string {
    if (score == null) return 'text-muted-foreground';
    if (score >= 80) return 'text-green-600';
    if (score >= 60) return 'text-yellow-600';
    return 'text-red-600';
}

function scoreBadgeClass(score: number | null | undefined): string {
    if (score == null) return 'border-border bg-background text-muted-foreground';
    if (score >= 80) return 'border-emerald-200 bg-emerald-50 text-emerald-700';
    if (score >= 60) return 'border-amber-200 bg-amber-50 text-amber-700';
    return 'border-red-200 bg-red-50 text-red-700';
}

function ScoreBadge({ score, label }: { score: number | null | undefined; label?: string }) {
    return (
        <Badge variant="outline" className={cn('tabular-nums font-medium', scoreBadgeClass(score))}>
            {label && <span className="mr-1 opacity-70">{label}</span>}
            {score != null ? `${Math.round(score)}` : '—'}
        </Badge>
    );
}

function runTimestamp(run: EvalRun): number {
    return new Date(run.completedAt ?? run.startedAt ?? run.created).getTime();
}

function formatRunDate(run: EvalRun, locale: Locale, pendingLabel: string): string {
    const value = run.completedAt ?? run.startedAt ?? run.created;
    return value ? new Date(value).toLocaleString(locale === 'de' ? 'de-DE' : 'en-US') : pendingLabel;
}

function isFailedResult(result: { status: string; error?: string; overallScore: number | null }): boolean {
    return result.status === 'failed' || !!result.error || (result.overallScore != null && result.overallScore < 80);
}

interface IntentOption {
    name: string;
    description: string;
    active: boolean;
}

// ── Sets list view ────────────────────────────────────────────────────────────

function SetsList({
    projectId,
    onSelect,
}: {
    projectId: string;
    onSelect: (setId: string) => void;
}) {
    const { t } = useI18n();
    const [sets, setSets] = useState<EvalSet[]>([]);
    const [loading, setLoading] = useState(true);
    const [showCreate, setShowCreate] = useState(false);
    const [newName, setNewName] = useState('');
    const [newDesc, setNewDesc] = useState('');
    const [creating, setCreating] = useState(false);

    const loadSets = useCallback(async () => {
        const res = await api.getEvalSets(projectId);
        if (res.data) setSets(res.data);
        setLoading(false);
    }, [projectId]);

    useEffect(() => {
        let cancelled = false;
        void api.getEvalSets(projectId).then((res) => {
            if (cancelled) return;
            if (res.data) setSets(res.data);
            setLoading(false);
        });
        return () => { cancelled = true; };
    }, [projectId]);

    const handleCreate = async () => {
        if (!newName.trim()) return;
        setCreating(true);
        const res = await api.createEvalSet(projectId, newName.trim(), newDesc.trim());
        if (res.error) {
            toast.error(res.error);
        } else {
            toast.success(t('Eval set created'));
            setNewName('');
            setNewDesc('');
            setShowCreate(false);
            if (res.data?.id) {
                onSelect(res.data.id);
            } else {
                void loadSets();
            }
        }
        setCreating(false);
    };

    const handleDelete = async (e: React.MouseEvent, setId: string) => {
        e.stopPropagation();
        if (!confirm(t('Delete this eval set and all its cases/runs?'))) return;
        const res = await api.deleteEvalSet(projectId, setId);
        if (res.error) toast.error(res.error);
        else void loadSets();
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center py-20">
                <Loader className="size-5 animate-spin text-muted-foreground" />
            </div>
        );
    }

    return (
        <div className="max-w-3xl mx-auto">
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h2 className="text-lg font-semibold">{t('Evaluation Sets')}</h2>
                    <p className="text-sm text-muted-foreground mt-0.5">
                        {t('Test your support setup with predefined messages and expected outcomes.')}
                    </p>
                </div>
                <Button size="sm" onClick={() => setShowCreate(true)}>
                    <Plus className="size-4 mr-1" />
                    {t('New Set')}
                </Button>
            </div>

            {/* Create form */}
            {showCreate && (
                <div className="bg-white border rounded-lg p-4 mb-4 space-y-3">
                    <div className="space-y-1">
                        <Label>{t('Name')}</Label>
                        <Input
                            value={newName}
                            onChange={(e) => setNewName(e.target.value)}
                            placeholder={t('e.g. Regression Tests')}
                            autoFocus
                        />
                    </div>
                    <div className="space-y-1">
                        <Label>{t('Description')}</Label>
                        <Input
                            value={newDesc}
                            onChange={(e) => setNewDesc(e.target.value)}
                            placeholder={t('Optional description')}
                        />
                    </div>
                    <div className="flex gap-2">
                        <Button size="sm" onClick={handleCreate} disabled={creating || !newName.trim()}>
                            {creating && <Loader className="size-3 animate-spin mr-1" />}
                            {t('Create')}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setShowCreate(false)}>{t('Cancel')}</Button>
                    </div>
                </div>
            )}

            {/* Sets table */}
            {sets.length === 0 && !showCreate ? (
                <div className="text-center py-16 text-muted-foreground">
                    <FlaskConical className="size-10 mx-auto mb-3 opacity-40" />
                    <p className="font-medium">{t('No evaluation sets yet')}</p>
                    <p className="text-sm mt-1">{t('Create one to start testing your support setup.')}</p>
                </div>
            ) : (
                <div className="space-y-2">
                    {sets.map((s) => (
                        <Button
                            type="button"
                            variant="outline"
                            key={s.id}
                            onClick={() => onSelect(s.id)}
                            className="h-auto w-full justify-start whitespace-normal rounded-lg bg-white p-4 text-left hover:border-foreground/30 hover:bg-white hover:shadow-sm group"
                        >
                            <div className="flex w-full items-center justify-between gap-4">
                                <div className="flex items-center gap-3 min-w-0">
                                    <div className="min-w-0">
                                        <div className="font-medium text-sm truncate">{s.name}</div>
                                        {s.description && (
                                            <div className="text-xs text-muted-foreground truncate mt-0.5">
                                                {s.description}
                                            </div>
                                        )}
                                    </div>
                                </div>
                                <div className="flex items-center gap-3 shrink-0">
                                    <Badge variant="outline" className="gap-1.5">
                                        <FileText className="size-3" />
                                        {t('{count} {unit}', {
                                            count: s.caseCount,
                                            unit: s.caseCount === 1 ? t('case') : t('cases'),
                                        })}
                                    </Badge>
                                    {s.lastRunScore != null && (
                                        <ScoreBadge score={s.lastRunScore} />
                                    )}
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        className="opacity-0 group-hover:opacity-100"
                                        onClick={(e) => handleDelete(e, s.id)}
                                    >
                                        <Trash2 className="size-3.5" />
                                    </Button>
                                    <ChevronRight className="size-4 text-muted-foreground" />
                                </div>
                            </div>
                        </Button>
                    ))}
                </div>
            )}
        </div>
    );
}

// ── Case editor modal ─────────────────────────────────────────────────────────

function bytesToBase64(bytes: Uint8Array): string {
    let binary = '';
    const chunkSize = 0x8000;
    for (let i = 0; i < bytes.length; i += chunkSize) {
        binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
    }
    return btoa(binary);
}

function textToBase64(value: string): string {
    return bytesToBase64(new TextEncoder().encode(value));
}

function extractHeaderValue(headers: string, name: string): string {
    const unfolded = headers.replace(/\r?\n[ \t]+/g, ' ');
    const match = unfolded.match(new RegExp(`^${name}:\\s*(.+)$`, 'im'));
    return match?.[1]?.trim() ?? '';
}

function extractHeaderParam(value: string, name: string): string {
    const match = value.match(new RegExp(`${name}\\*?=(?:UTF-8''|")?([^";\\r\\n]+)"?`, 'i'));
    return match ? decodeURIComponent(match[1].trim()) : '';
}

function parseEmlFields(raw: string): { subject: string; from: string; body: string; attachments: EvalEmailAttachment[] } {
    const lines = raw.split(/\r?\n/);
    let from = '';
    let subject = '';
    const bodyLines: string[] = [];
    const attachments: EvalEmailAttachment[] = [];
    let inBody = false;
    let boundary: string | null = null;
    let inTextPart = false;
    let skipNextBlank = false;

    for (const line of lines) {
        if (!inBody) {
            if (line.trim() === '') {
                inBody = true;
                continue;
            }

            const lower = line.toLowerCase();
            if (lower.startsWith('from:')) from = line.slice(5).trim();
            else if (lower.startsWith('subject:')) subject = line.slice(8).trim();
            else if (lower.startsWith('content-type:') && lower.includes('boundary=')) {
                const match = line.match(/boundary="?([^";]+)"?/i);
                if (match) boundary = match[1].trim();
            }
        } else if (boundary) {
            if (line.includes(boundary)) {
                inTextPart = false;
                skipNextBlank = true;
                continue;
            }

            if (skipNextBlank && line.trim() === '') {
                skipNextBlank = false;
                continue;
            }

            const lower = line.toLowerCase();
            if (lower.startsWith('content-type: text/plain')) {
                inTextPart = true;
                skipNextBlank = true;
                continue;
            }
            if (lower.startsWith('content-type:') && !lower.startsWith('content-type: text/plain')) {
                inTextPart = false;
            }
            if (inTextPart) bodyLines.push(line);
        } else {
            bodyLines.push(line);
        }
    }

    const body = bodyLines
        .join('\n')
        .replace(/=\r?\n/g, '')
        .trim();

    if (boundary) {
        for (const part of raw.split(`--${boundary}`)) {
            const [headers = '', ...bodyParts] = part.split(/\r?\n\r?\n/);
            const partBody = bodyParts.join('\n\n').trim();
            if (!partBody) continue;

            const contentDisposition = extractHeaderValue(headers, 'content-disposition');
            const contentType = extractHeaderValue(headers, 'content-type');
            const transferEncoding = extractHeaderValue(headers, 'content-transfer-encoding').toLowerCase();
            const filename = (
                extractHeaderParam(contentDisposition, 'filename')
                || extractHeaderParam(contentType, 'name')
            ).replace(/^"|"$/g, '');
            const isAttachment = /attachment/i.test(contentDisposition) || !!filename;
            if (!isAttachment || !filename) continue;

            attachments.push({
                filename,
                base64: transferEncoding === 'base64'
                    ? partBody.replace(/\r?\n/g, '')
                    : textToBase64(partBody),
            });
        }
    }

    return {
        subject: subject || '(no subject)',
        from: from || 'unknown@example.com',
        body: body || raw.trim(),
        attachments,
    };
}

function CaseEditorModal({
    initial,
    intentOptions,
    onSave,
    onCancel,
}: {
    initial?: EvalCase;
    intentOptions: IntentOption[];
    onSave: (data: EvalCaseInput) => Promise<void>;
    onCancel: () => void;
}) {
    const { t } = useI18n();
    const [name, setName] = useState(initial?.name ?? '');
    const [subject, setSubject] = useState(initial?.emailSubject ?? '');
    const [from, setFrom] = useState(initial?.emailFrom ?? '');
    const [body, setBody] = useState(initial?.emailBody ?? '');
    const [customerFound, setCustomerFound] = useState(initial?.expectedCustomerFound ?? false);
    const [intentMatched, setIntentMatched] = useState(initial?.expectedIntentMatched ?? false);
    const [intentName, setIntentName] = useState(initial?.expectedIntentName ?? '');
    const [requiresHuman, setRequiresHuman] = useState(initial?.expectedRequiresHuman ?? false);
    const [expectedResponse, setExpectedResponse] = useState(initial?.expectedResponse ?? '');
    const [attachments, setAttachments] = useState<EvalEmailAttachment[]>(initial?.emailAttachments ?? []);
    const [emailInputMode, setEmailInputMode] = useState<'upload' | 'manual'>(initial ? 'manual' : 'upload');
    const [saving, setSaving] = useState(false);
    const [isDragging, setIsDragging] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const attachmentInputRef = useRef<HTMLInputElement>(null);

    const handleEmailFile = (file: File) => {
        if (!file.name.endsWith('.eml') && file.type !== 'message/rfc822') {
            toast.error(t('Please upload an .eml file'));
            return;
        }

        const reader = new FileReader();
        reader.onload = (event) => {
            const parsed = parseEmlFields(typeof event.target?.result === 'string' ? event.target.result : '');
            setSubject(parsed.subject);
            setFrom(parsed.from);
            setBody(parsed.body);
            if (parsed.attachments.length > 0) {
                setAttachments((current) => [...current, ...parsed.attachments]);
            }
            if (!name.trim()) setName(parsed.subject);
            toast.success(parsed.attachments.length > 0
                ? t('Email imported with {count} attachment(s)', { count: parsed.attachments.length })
                : t('Email imported'));
        };
        reader.readAsText(file);
    };

    const handleAttachmentFiles = async (files: FileList | null) => {
        if (!files?.length) return;
        const items = await Promise.all(Array.from(files).map(async (file) => ({
            filename: file.name,
            base64: bytesToBase64(new Uint8Array(await file.arrayBuffer())),
        })));
        setAttachments((current) => [...current, ...items]);
        toast.success(t('{count} attachment(s) added', { count: items.length }));
    };

    const removeAttachment = (index: number) => {
        setAttachments((current) => current.filter((_, i) => i !== index));
    };

    const handleDrop = (event: React.DragEvent) => {
        event.preventDefault();
        setIsDragging(false);
        const file = event.dataTransfer.files[0];
        if (file) handleEmailFile(file);
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setSaving(true);
        try {
            await onSave({
                name: name.trim(),
                email_subject: subject.trim(),
                email_from: from.trim(),
                email_body: body,
                email_attachments: attachments,
                expected_customer_found: customerFound,
                expected_intent_matched: intentMatched,
                expected_intent_name: intentName.trim(),
                expected_requires_human: requiresHuman,
                expected_response: expectedResponse,
            });
        } finally {
            setSaving(false);
        }
    };

    return (
        <Sheet open onOpenChange={(open) => { if (!open) onCancel(); }}>
            <SheetContent className="w-full gap-0 p-0 sm:max-w-xl">
                <SheetHeader className="border-b px-6 py-3">
                    <SheetTitle className="text-sm">
                        {t(initial ? 'Edit Test Case' : 'New Test Case')}
                    </SheetTitle>
                </SheetHeader>
                <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
                    {/* Case name */}
                    <div className="space-y-1">
                        <Label>{t('Test case name')}</Label>
                        <Input value={name} onChange={(e) => setName(e.target.value)} required placeholder={t('e.g. New client inquiry')} />
                    </div>

                    {/* Email fields */}
                    <div>
                        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">{t('Email')}</h3>
                        <div className="space-y-3">
                            <Tabs value={emailInputMode} onValueChange={(value) => setEmailInputMode(value as 'upload' | 'manual')}>
                                <TabsList className="grid w-full grid-cols-2">
                                    <TabsTrigger value="upload">{t('Upload')}</TabsTrigger>
                                    <TabsTrigger value="manual">{t('Manual')}</TabsTrigger>
                                </TabsList>
                                <TabsContent value="upload" className="mt-3 space-y-3">
                                    <div
                                        onDrop={handleDrop}
                                        onDragOver={(event) => {
                                            event.preventDefault();
                                            setIsDragging(true);
                                        }}
                                        onDragLeave={() => setIsDragging(false)}
                                        onClick={() => fileInputRef.current?.click()}
                                        className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed px-4 py-5 text-center transition-colors ${
                                            isDragging
                                                ? 'border-foreground bg-muted/60'
                                                : 'border-muted-foreground/25 bg-muted/20 hover:border-muted-foreground/50 hover:bg-muted/30'
                                        }`}
                                    >
                                        <CloudUpload className={`mb-2 size-5 ${isDragging ? 'text-foreground' : 'text-muted-foreground/60'}`} />
                                        <p className="text-sm font-medium text-muted-foreground">{t('Drop an .eml file here')}</p>
                                        <p className="mt-1 text-xs text-muted-foreground/70">{t('or click to import subject, sender, and body')}</p>
                                        <input
                                            ref={fileInputRef}
                                            type="file"
                                            accept=".eml,message/rfc822"
                                            className="hidden"
                                            onChange={(event) => {
                                                const file = event.target.files?.[0];
                                                if (file) handleEmailFile(file);
                                                event.target.value = '';
                                            }}
                                        />
                                    </div>
                                    {(subject || from || body) && (
                                        <div className="rounded-md border bg-muted/20 p-3 text-xs">
                                            <div className="mb-2 font-medium">{t('Parsed email')}</div>
                                            <div className="grid gap-1.5">
                                                <div className="grid grid-cols-[4rem_1fr] gap-2">
                                                    <span className="text-muted-foreground">{t('From')}</span>
                                                    <span className="break-all">{from || '-'}</span>
                                                </div>
                                                <div className="grid grid-cols-[4rem_1fr] gap-2">
                                                    <span className="text-muted-foreground">{t('Subject')}</span>
                                                    <span className="break-all">{subject || '-'}</span>
                                                </div>
                                                <div className="grid grid-cols-[4rem_1fr] gap-2">
                                                    <span className="text-muted-foreground">{t('Body')}</span>
                                                    <pre className="max-h-32 overflow-y-auto whitespace-pre-wrap rounded bg-background p-2 text-muted-foreground">
                                                        {body || '-'}
                                                    </pre>
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                </TabsContent>
                                <TabsContent value="manual" className="mt-3 space-y-3">
                                    <div className="space-y-1">
                                        <Label>{t('Subject')}</Label>
                                        <Input value={subject} onChange={(e) => setSubject(e.target.value)} required placeholder={t('Email subject')} />
                                    </div>
                                    <div className="space-y-1">
                                        <Label>{t('From')}</Label>
                                        <Input value={from} onChange={(e) => setFrom(e.target.value)} required placeholder={t('sender@example.com')} />
                                    </div>
                                    <div className="space-y-1">
                                        <Label>{t('Body')}</Label>
                                        <Textarea
                                            value={body}
                                            onChange={(e) => setBody(e.target.value)}
                                            required
                                            rows={6}
                                            placeholder={t('Email body text')}
                                        />
                                    </div>
                                </TabsContent>
                            </Tabs>
                            <div className="space-y-2">
                                <div className="flex items-center justify-between gap-3">
                                    <Label>{t('Attachments')}</Label>
                                    <Button
                                        type="button"
                                        variant="outline"
                                        size="sm"
                                        onClick={() => attachmentInputRef.current?.click()}
                                    >
                                        <Paperclip className="mr-1 size-3" />
                                        {t('Add files')}
                                    </Button>
                                </div>
                                <input
                                    ref={attachmentInputRef}
                                    type="file"
                                    multiple
                                    className="hidden"
                                    onChange={(event) => {
                                        void handleAttachmentFiles(event.target.files);
                                        event.target.value = '';
                                    }}
                                />
                                {attachments.length > 0 ? (
                                    <div className="space-y-1 rounded-md border bg-muted/20 p-2">
                                        {attachments.map((attachment, index) => (
                                            <div key={`${attachment.filename}-${index}`} className="flex items-center justify-between gap-2 rounded-sm px-2 py-1 text-sm">
                                                <div className="flex min-w-0 items-center gap-2">
                                                    <FileText className="size-3.5 shrink-0 text-muted-foreground" />
                                                    <span className="truncate">{attachment.filename}</span>
                                                </div>
                                                <Button type="button" variant="ghost" size="sm" onClick={() => removeAttachment(index)}>
                                                    <Trash2 className="size-3.5" />
                                                </Button>
                                            </div>
                                        ))}
                                    </div>
                                ) : (
                                    <p className="text-xs text-muted-foreground">
                                        {t('Attachments from imported .eml files appear here, or add files manually.')}
                                    </p>
                                )}
                            </div>
                        </div>
                    </div>

                    {/* Expected outcomes */}
                    <div>
                        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">{t('Expected Outcomes')}</h3>
                        <div className="space-y-4">
                            <div className="flex items-center justify-between">
                                <Label>{t('Customer found')}</Label>
                                <Switch checked={customerFound} onCheckedChange={setCustomerFound} />
                            </div>
                            <div className="flex items-center justify-between">
                                <Label>{t('Runbook matched')}</Label>
                                <Switch checked={intentMatched} onCheckedChange={setIntentMatched} />
                            </div>
                            {intentMatched && (
                                <div className="space-y-1">
                                    <Label>{t('Expected runbook name')}</Label>
                                    <Select value={intentName} onValueChange={setIntentName} disabled={intentOptions.length === 0}>
                                        <SelectTrigger>
                                            <SelectValue placeholder={t('Select a runbook')} />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {intentOptions.map((intent) => (
                                                <SelectItem key={intent.name} value={intent.name}>
                                                    {intent.name}
                                                </SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                            )}
                            <div className="flex items-center justify-between">
                                <Label>{t('Requires human attention')}</Label>
                                <Switch checked={requiresHuman} onCheckedChange={setRequiresHuman} />
                            </div>
                            <div className="space-y-1">
                                <Label>{t('Expected response (free-text description)')}</Label>
                                <Textarea
                                    value={expectedResponse}
                                    onChange={(e) => setExpectedResponse(e.target.value)}
                                    rows={3}
                                    placeholder={t("Describe what the response should convey, e.g. 'Should greet the client, ask for company details, and mention the Stammblatt form'")}
                                />
                                <p className="text-xs text-muted-foreground">
                                    {t('Leave empty to skip response scoring. The LLM judge compares semantic meaning, not exact wording.')}
                                </p>
                            </div>
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-2 pt-2 pb-4">
                        <Button
                            type="submit"
                            className="w-full"
                            disabled={saving || !name.trim() || !subject.trim() || !from.trim()}
                            aria-label={t(initial ? 'Save' : 'Create')}
                        >
                            {saving ? (
                                <Loader className="size-4 animate-spin" />
                            ) : initial ? (
                                <Save className="size-4" />
                            ) : (
                                t('Create')
                            )}
                        </Button>
                        <Button
                            type="button"
                            variant="outline"
                            className="w-full"
                            onClick={onCancel}
                            aria-label={t('Cancel')}
                        >
                            {initial ? <X className="size-4" /> : t('Cancel')}
                        </Button>
                    </div>
                </form>
            </SheetContent>
        </Sheet>
    );
}

// ── Run results view ──────────────────────────────────────────────────────────

function RunResultsView({
    run,
    cases,
    onBack,
}: {
    run: EvalRunDetail;
    cases: EvalCase[];
    onBack: () => void;
}) {
    const { t, locale } = useI18n();
    const [expandedResult, setExpandedResult] = useState<string | null>(null);
    const [resultFilter, setResultFilter] = useState<'all' | 'failed' | 'passed'>('all');
    const summary = run.summary;
    const orderedResults = useMemo(() => (
        [...run.results].sort((a, b) => Number(isFailedResult(b)) - Number(isFailedResult(a)))
    ), [run.results]);
    const failedResults = orderedResults.filter(isFailedResult);
    const passedResults = orderedResults.filter(result => !isFailedResult(result));
    const visibleResults = resultFilter === 'failed'
        ? failedResults
        : resultFilter === 'passed'
            ? passedResults
            : orderedResults;

    // Map case IDs to names
    const caseMap = new Map(cases.map((c) => [c.id, c]));

    return (
        <div className="max-w-4xl mx-auto">
            <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={onBack}
                className="mb-4 px-0 text-muted-foreground hover:bg-transparent hover:text-foreground"
            >
                <ArrowLeft className="size-4" />
                {t('Back to set')}
            </Button>

            <div className="flex items-center justify-between mb-6">
                <div>
                    <h2 className="text-lg font-semibold">{t('Run Results')}</h2>
                    <p className="text-xs text-muted-foreground mt-0.5">
                        {run.status === 'running'
                            ? t('Running...')
                            : t('Completed {date}', {
                                date: run.completedAt ? new Date(run.completedAt).toLocaleString(locale === 'de' ? 'de-DE' : 'en-US') : '',
                            })}
                    </p>
                </div>
                {summary && (
                    <div className="flex gap-2">
                        <ScoreBadge score={summary.overallScore} label={t('Overall')} />
                        <ScoreBadge score={summary.identityScore} label={t('Identity')} />
                        <ScoreBadge score={summary.intentScore} label={t('Runbook')} />
                        <ScoreBadge score={summary.actionsScore} label={t('Actions')} />
                        {summary.responseScore != null && (
                            <ScoreBadge score={summary.responseScore} label={t('Response')} />
                        )}
                    </div>
                )}
            </div>

            {run.status === 'running' && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground mb-4">
                    <Loader className="size-4 animate-spin" />
                    {t('Evaluation in progress...')}
                </div>
            )}

            <div className="mb-3 flex items-center gap-1.5">
                <Button
                    type="button"
                    size="sm"
                    variant={resultFilter === 'all' ? 'default' : 'outline'}
                    className="h-7 px-2 text-xs"
                    onClick={() => setResultFilter('all')}
                >
                    {t('All')} ({orderedResults.length})
                </Button>
                <Button
                    type="button"
                    size="sm"
                    variant={resultFilter === 'failed' ? 'default' : 'outline'}
                    className="h-7 px-2 text-xs"
                    onClick={() => setResultFilter('failed')}
                >
                    {t('Failed')} ({failedResults.length})
                </Button>
                <Button
                    type="button"
                    size="sm"
                    variant={resultFilter === 'passed' ? 'default' : 'outline'}
                    className="h-7 px-2 text-xs"
                    onClick={() => setResultFilter('passed')}
                >
                    {t('Passed')} ({passedResults.length})
                </Button>
            </div>

            {/* Results table */}
            <div className="space-y-2">
                {visibleResults.length === 0 ? (
                    <div className="rounded-lg border bg-white py-8 text-center text-sm text-muted-foreground">
                        {t('No results in this filter.')}
                    </div>
                ) : visibleResults.map((result) => {
                    const evalCase = caseMap.get(result.evalCase);
                    const isExpanded = expandedResult === result.id;

                    return (
                        <div key={result.id} className="bg-white border rounded-lg overflow-hidden">
                            <Button
                                type="button"
                                variant="ghost"
                                onClick={() => setExpandedResult(isExpanded ? null : result.id)}
                                className="h-auto w-full justify-between whitespace-normal rounded-none px-4 py-3 text-left hover:bg-gray-50"
                            >
                                <div className="flex items-center gap-3 min-w-0">
                                    {isExpanded ? <ChevronDown className="size-4 shrink-0" /> : <ChevronRight className="size-4 shrink-0" />}
                                    <span className="text-sm font-medium truncate">
                                        {evalCase?.name ?? result.evalCase}
                                    </span>
                                    {result.status === 'running' && <Loader className="size-3 animate-spin text-muted-foreground" />}
                                    {isFailedResult(result) && (
                                        <Badge variant="outline" className="border-red-200 bg-red-50 text-red-700">
                                            {t('Failed')}
                                        </Badge>
                                    )}
                                </div>
                                {result.status === 'completed' && (
                                    <div className="flex gap-2 shrink-0">
                                        <ScoreBadge score={result.overallScore} label={t('Overall')} />
                                        <ScoreBadge score={result.identityScore} label="ID" />
                                        <ScoreBadge score={result.intentScore} label="Run" />
                                        <ScoreBadge score={result.actionsScore} label="Act" />
                                        {result.responseScore != null && (
                                            <ScoreBadge score={result.responseScore} label="Resp" />
                                        )}
                                    </div>
                                )}
                            </Button>
                            {isExpanded && (
                                <div className="border-t px-4 py-4 space-y-4 bg-gray-50/50">
                                    {result.error && (
                                        <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">
                                            {result.error}
                                        </div>
                                    )}
                                    {result.status === 'completed' && (
                                        <>
                                            <DimensionDetail label={t('Identity')} score={result.identityScore} reasoning={result.identityReasoning} />
                                            <DimensionDetail label={t('Runbook')} score={result.intentScore} reasoning={result.intentReasoning} />
                                            <DimensionDetail label={t('Actions')} score={result.actionsScore} reasoning={result.actionsReasoning} />
                                            {result.responseScore != null && (
                                                <DimensionDetail label={t('Response')} score={result.responseScore} reasoning={result.responseReasoning} />
                                            )}
                                            {result.pipelineOutput && (
                                                <details className="text-xs">
                                                    <summary className="cursor-pointer text-muted-foreground hover:text-foreground transition-colors font-medium">
                                                        {t('Raw support setup output')}
                                                    </summary>
                                                    <pre className="mt-2 bg-white border rounded p-3 overflow-x-auto max-h-64 overflow-y-auto">
                                                        {JSON.stringify(result.pipelineOutput, null, 2)}
                                                    </pre>
                                                </details>
                                            )}
                                        </>
                                    )}
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

function DimensionDetail({ label, score, reasoning }: { label: string; score: number | null; reasoning: string }) {
    const { t } = useI18n();

    return (
        <div className="flex items-start gap-3">
            <div className="w-20 shrink-0">
                <span className={`text-xl font-bold tabular-nums ${scoreColor(score)}`}>
                    {score ?? '—'}
                </span>
                <div className="text-xs text-muted-foreground">{label}</div>
            </div>
            <p className="text-sm text-muted-foreground leading-relaxed">{reasoning || t('No reasoning provided.')}</p>
        </div>
    );
}

// ── Set detail view ───────────────────────────────────────────────────────────

function SetDetail({
    projectId,
    evalSet,
    selectedRunId,
    onBack,
    onSelectRun,
    onBackFromRun,
}: {
    projectId: string;
    evalSet: EvalSet;
    selectedRunId?: string;
    onBack: () => void;
    onSelectRun: (runId: string) => void;
    onBackFromRun: () => void;
}) {
    const { t, locale } = useI18n();
    const [cases, setCases] = useState<EvalCase[]>([]);
    const [runs, setRuns] = useState<EvalRun[]>([]);
    const [intentOptions, setIntentOptions] = useState<IntentOption[]>([]);
    const [loading, setLoading] = useState(true);
    const [editingCase, setEditingCase] = useState<EvalCase | 'new' | null>(null);
    const [runDetail, setRunDetail] = useState<EvalRunDetail | null>(null);
    const [runLoadErrorId, setRunLoadErrorId] = useState<string | null>(null);
    const [runningEval, setRunningEval] = useState(false);
    const [casesPage, setCasesPage] = useState(1);
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const { setBreadcrumb, setActions } = useTopBar();
    const sortedRuns = useMemo(() => (
        [...runs].sort((a, b) => runTimestamp(b) - runTimestamp(a))
    ), [runs]);
    const latestRun = sortedRuns[0] ?? null;
    const requireHumanCount = cases.filter(c => c.expectedRequiresHuman).length;
    const casesPerPage = 25;
    const totalCasePages = Math.max(1, Math.ceil(cases.length / casesPerPage));
    const currentCasesPage = Math.min(casesPage, totalCasePages);
    const visibleCases = cases.slice((currentCasesPage - 1) * casesPerPage, currentCasesPage * casesPerPage);

    const loadData = useCallback(async () => {
        const [casesRes, runsRes, intentsRes] = await Promise.all([
            api.getEvalCases(projectId, evalSet.id),
            api.getEvalRuns(projectId, evalSet.id),
            api.getIntents(projectId),
        ]);
        if (casesRes.data) setCases(casesRes.data);
        if (runsRes.data) setRuns(runsRes.data);
        if (intentsRes.data) setIntentOptions(intentsRes.data.filter((intent) => intent.name !== '_else'));
        setLoading(false);
    }, [projectId, evalSet.id]);

    useEffect(() => {
        let cancelled = false;
        void Promise.all([
            api.getEvalCases(projectId, evalSet.id),
            api.getEvalRuns(projectId, evalSet.id),
            api.getIntents(projectId),
        ]).then(([casesRes, runsRes, intentsRes]) => {
            if (cancelled) return;
            if (casesRes.data) setCases(casesRes.data);
            if (runsRes.data) setRuns(runsRes.data);
            if (intentsRes.data) setIntentOptions(intentsRes.data.filter((intent) => intent.name !== '_else'));
            setLoading(false);
        });
        return () => { cancelled = true; };
    }, [projectId, evalSet.id]);

    useEffect(() => {
        let cancelled = false;
        if (!selectedRunId) {
            return () => { cancelled = true; };
        }

        void api.getEvalRun(projectId, selectedRunId).then((res) => {
            if (cancelled) return;
            if (res.data) {
                setRunDetail(res.data);
                setRunLoadErrorId(null);
            } else {
                setRunLoadErrorId(selectedRunId);
            }
        }).catch(() => {
            if (!cancelled) setRunLoadErrorId(selectedRunId);
        });

        return () => { cancelled = true; };
    }, [projectId, selectedRunId]);

    // Clean up polling on unmount
    useEffect(() => {
        return () => {
            if (pollRef.current) clearInterval(pollRef.current);
        };
    }, []);

    const handleSaveCase = async (data: EvalCaseInput) => {
        if (editingCase && editingCase !== 'new') {
            const res = await api.updateEvalCase(projectId, editingCase.id, data);
            if (res.error) { toast.error(res.error); return; }
            toast.success(t('Case updated'));
        } else {
            const res = await api.createEvalCase(projectId, evalSet.id, data);
            if (res.error) { toast.error(res.error); return; }
            toast.success(t('Case created'));
        }
        setEditingCase(null);
        void loadData();
    };

    const handleDeleteCase = async (caseId: string) => {
        if (!confirm(t('Delete this test case?'))) return;
        const res = await api.deleteEvalCase(projectId, caseId);
        if (res.error) toast.error(res.error);
        else void loadData();
    };

    const handleRunEval = async () => {
        setRunningEval(true);
        const res = await api.triggerEvalRun(projectId, evalSet.id);
        if (res.error) {
            toast.error(res.error);
            setRunningEval(false);
            return;
        }

        toast.success(t('Evaluation started'));
        const runId = res.data?.runId;
        if (!runId) { setRunningEval(false); return; }

        // Poll until complete
        pollRef.current = setInterval(async () => {
            const runRes = await api.getEvalRun(projectId, runId);
            if (runRes.data && (runRes.data.status === 'completed' || runRes.data.status === 'failed')) {
                if (pollRef.current) clearInterval(pollRef.current);
                pollRef.current = null;
                setRunningEval(false);
                void loadData();
                onSelectRun(runRes.data.id);
            }
        }, 3000);
    };

    const handleViewRun = (runId: string) => {
        onSelectRun(runId);
    };

    const handleDeleteRun = async (e: React.MouseEvent, runId: string) => {
        e.stopPropagation();
        if (!confirm(t('Delete this run?'))) return;
        const res = await api.deleteEvalRun(projectId, runId);
        if (res.error) toast.error(res.error);
        else void loadData();
    };

    useEffect(() => {
        setBreadcrumb(
            <Breadcrumb>
                <BreadcrumbList>
                    <BreadcrumbItem>
                        <BreadcrumbLink asChild>
                            <button
                                type="button"
                                onClick={onBack}
                                className="text-sm"
                            >
                                {t('Evaluation')}
                            </button>
                        </BreadcrumbLink>
                    </BreadcrumbItem>
                    <BreadcrumbSeparator />
                    <BreadcrumbItem className="min-w-0">
                        <BreadcrumbPage className="block max-w-[28rem] truncate text-sm font-medium">
                            {evalSet.name}
                        </BreadcrumbPage>
                    </BreadcrumbItem>
                    {selectedRunId && (
                        <>
                            <BreadcrumbSeparator />
                            <BreadcrumbItem>
                                <BreadcrumbPage className="text-sm">{t('Run Results')}</BreadcrumbPage>
                            </BreadcrumbItem>
                        </>
                    )}
                </BreadcrumbList>
            </Breadcrumb>
        );

        if (selectedRunId) {
            setActions(null);
        } else {
            setActions(
                <>
                    <Button size="sm" variant="outline" onClick={() => setEditingCase('new')}>
                        <Plus className="size-4 mr-1" />
                        {t('Add Tests')}
                    </Button>
                    <Button size="sm" onClick={handleRunEval} disabled={runningEval || cases.length === 0}>
                        {runningEval ? <Loader className="size-4 animate-spin mr-1" /> : <Play className="size-4 mr-1" />}
                        {t('Run Evaluation')}
                    </Button>
                </>
            );
        }

        return () => {
            setBreadcrumb(null);
            setActions(null);
        };
    });

    const selectedRunDetail = selectedRunId && runDetail?.id === selectedRunId ? runDetail : null;
    const runLoadError = selectedRunId ? runLoadErrorId === selectedRunId : false;

    if (selectedRunId) {
        if (loading || (!selectedRunDetail && !runLoadError)) {
            return (
                <div className="flex items-center justify-center py-20">
                    <Loader className="size-5 animate-spin text-muted-foreground" />
                </div>
            );
        }

        if (runLoadError || !selectedRunDetail) {
            return (
                <div className="mx-auto flex max-w-3xl flex-col items-center justify-center py-20 text-center">
                    <FlaskConical className="mb-3 size-10 text-muted-foreground/50" />
                    <h2 className="text-lg font-semibold">{t('Evaluation run not found')}</h2>
                    <Button variant="outline" size="sm" className="mt-4" onClick={onBackFromRun}>
                        <ArrowLeft className="size-4" />
                        {t('Back to set')}
                    </Button>
                </div>
            );
        }

        return (
            <RunResultsView
                run={selectedRunDetail}
                cases={cases}
                onBack={onBackFromRun}
            />
        );
    }

    if (loading) {
        return (
            <div className="flex items-center justify-center py-20">
                <Loader className="size-5 animate-spin text-muted-foreground" />
            </div>
        );
    }

    return (
        <div className="max-w-3xl mx-auto">
            {evalSet.description && (
                <p className="mb-6 text-sm text-muted-foreground">{evalSet.description}</p>
            )}

            <div className="mb-6 rounded-lg border bg-white p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                    <div>
                        <h3 className="text-sm font-semibold">{t('Latest Run')}</h3>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                            {latestRun ? formatRunDate(latestRun, locale, t('Pending')) : t('No evaluation run yet')}
                        </p>
                    </div>
                    {latestRun?.summary?.overallScore != null ? (
                        <ScoreBadge score={latestRun.summary.overallScore} label={t('Score')} />
                    ) : (
                        <Badge variant="outline">{latestRun?.status ?? t('Not run')}</Badge>
                    )}
                </div>
                <div className="grid grid-cols-3 gap-2 text-xs">
                    <div className="rounded-md border bg-muted/20 px-3 py-2">
                        <div className="text-muted-foreground">{t('Cases')}</div>
                        <div className="mt-1 text-sm font-medium">{cases.length}</div>
                    </div>
                    <div className="rounded-md border bg-muted/20 px-3 py-2">
                        <div className="text-muted-foreground">{t('Completed')}</div>
                        <div className="mt-1 text-sm font-medium">
                            {latestRun?.summary ? `${latestRun.summary.completedCases}/${latestRun.summary.totalCases}` : '—'}
                        </div>
                    </div>
                    <div className="rounded-md border bg-muted/20 px-3 py-2">
                        <div className="text-muted-foreground">{t('Failed')}</div>
                        <div className="mt-1 text-sm font-medium">
                            {latestRun?.summary ? latestRun.summary.failedCases : '—'}
                        </div>
                    </div>
                </div>
            </div>

            <Tabs defaultValue="runs" className="w-full">
                <TabsList>
                    <TabsTrigger value="runs">{t('Runs')} ({runs.length})</TabsTrigger>
                    <TabsTrigger value="cases">{t('Test Cases')} ({cases.length})</TabsTrigger>
                </TabsList>

                <TabsContent value="runs" className="pt-4">
                    {runs.length === 0 ? (
                        <div className="flex items-center justify-between gap-3 rounded-lg border bg-white p-4">
                            <div>
                                <div className="text-sm font-medium">{t('No runs yet')}</div>
                                <p className="mt-0.5 text-xs text-muted-foreground">{t('Run this set to score the current support behavior.')}</p>
                            </div>
                            <Button size="sm" onClick={handleRunEval} disabled={runningEval || cases.length === 0}>
                                {runningEval ? <Loader className="size-4 mr-1 animate-spin" /> : <Play className="size-4 mr-1" />}
                                {t('Run evaluation')}
                            </Button>
                        </div>
                    ) : (
                        <div className="space-y-2">
                            {sortedRuns.map((run) => (
                                <Button
                                    type="button"
                                    variant="outline"
                                    key={run.id}
                                    onClick={() => handleViewRun(run.id)}
                                    className="group h-auto w-full justify-start whitespace-normal rounded-lg bg-white p-4 text-left hover:border-foreground/30 hover:bg-white hover:shadow-sm"
                                >
                                    <div className="flex w-full min-w-0 items-center justify-between gap-3">
                                        <div className="flex min-w-0 items-center gap-3">
                                            {run.status === 'running' && (
                                                <Loader className="size-4 animate-spin text-muted-foreground" />
                                            )}
                                            <div className="min-w-0">
                                                <div className="truncate text-sm font-medium">
                                                    {formatRunDate(run, locale, t('Pending'))}
                                                </div>
                                                <div className="mt-0.5 truncate text-xs text-muted-foreground">
                                                    {run.summary
                                                        ? t('{done}/{total} cases', { done: run.summary.completedCases, total: run.summary.totalCases })
                                                        : run.status}
                                                    {run.summary?.failedCases ? ` · ${t('{count} failed', { count: run.summary.failedCases })}` : ''}
                                                </div>
                                            </div>
                                        </div>
                                        <div className="flex shrink-0 items-center gap-2">
                                            <Badge variant={run.status === 'completed' ? 'secondary' : 'outline'} className="capitalize">
                                                {run.status}
                                            </Badge>
                                            {run.summary?.overallScore != null && (
                                                <ScoreBadge score={run.summary.overallScore} label={t('Score')} />
                                            )}
                                            <Button
                                                variant="ghost"
                                                size="sm"
                                                className="opacity-0 group-hover:opacity-100"
                                                onClick={(e) => handleDeleteRun(e, run.id)}
                                            >
                                                <Trash2 className="size-3.5" />
                                            </Button>
                                            <ChevronRight className="size-4 text-muted-foreground" />
                                        </div>
                                    </div>
                                </Button>
                            ))}
                        </div>
                    )}
                </TabsContent>

                <TabsContent value="cases" className="pt-4">
                    <div className="mb-3 flex items-center justify-between gap-3">
                        <div className="flex items-center gap-1.5">
                            <Badge variant="outline">{t('{count} cases', { count: cases.length })}</Badge>
                            {requireHumanCount > 0 && (
                                <Badge variant="outline">{t('{count} require human', { count: requireHumanCount })}</Badge>
                            )}
                        </div>
                        {cases.length > casesPerPage && (
                            <div className="text-xs text-muted-foreground">
                                {t('Page {page} of {total}', { page: currentCasesPage, total: totalCasePages })}
                            </div>
                        )}
                    </div>

                    {cases.length === 0 ? (
                        <div className="flex items-center justify-between gap-3 rounded-lg border bg-white p-4">
                            <div>
                                <div className="text-sm font-medium">{t('No test cases yet')}</div>
                                <p className="mt-0.5 text-xs text-muted-foreground">{t('Add one email case before running an evaluation.')}</p>
                            </div>
                            <Button size="sm" onClick={() => setEditingCase('new')}>
                                <Plus className="size-4 mr-1" />
                                {t('Add first test case')}
                            </Button>
                        </div>
                    ) : (
                        <>
                            <div className="space-y-2">
                                {visibleCases.map((c) => (
                                    <div
                                        key={c.id}
                                        className="flex flex-col gap-3 rounded-lg border bg-white p-4 sm:flex-row sm:items-center sm:justify-between"
                                    >
                                        <div className="min-w-0">
                                            <div className="text-sm font-medium">{c.name}</div>
                                            <div className="mt-0.5 truncate text-xs text-muted-foreground">
                                                {t('{subject} - from {from}', { subject: c.emailSubject, from: c.emailFrom })}
                                            </div>
                                            <div className="mt-1.5 flex flex-wrap gap-2">
                                                {c.expectedIntentMatched && c.expectedIntentName && (
                                                    <Badge variant="secondary" className="text-[10px]">{t('Intent')}: {c.expectedIntentName}</Badge>
                                                )}
                                                {c.expectedCustomerFound && (
                                                    <Badge variant="secondary" className="text-[10px]">{t('Customer found')}</Badge>
                                                )}
                                                {c.expectedRequiresHuman && (
                                                    <Badge variant="outline" className="text-[10px]">{t('Requires human')}</Badge>
                                                )}
                                                {(c.emailAttachments?.length ?? 0) > 0 && (
                                                    <Badge variant="outline" className="text-[10px]">{t('{count} attachment(s)', { count: c.emailAttachments?.length ?? 0 })}</Badge>
                                                )}
                                            </div>
                                        </div>
                                        <div className="flex w-full shrink-0 items-center gap-1 sm:w-auto">
                                            <Button
                                                variant="ghost"
                                                size="sm"
                                                className="flex-1 sm:flex-none"
                                                onClick={() => setEditingCase(c)}
                                            >
                                                {t('Edit')}
                                            </Button>
                                            <Button
                                                variant="ghost"
                                                size="sm"
                                                className="flex-1 text-red-500 hover:text-red-600 sm:flex-none"
                                                onClick={() => handleDeleteCase(c.id)}
                                                aria-label={t('Delete')}
                                            >
                                                <Trash2 className="size-3.5" />
                                            </Button>
                                        </div>
                                    </div>
                                ))}
                            </div>

                            {cases.length > casesPerPage && (
                                <div className="mt-4 flex items-center justify-between gap-3">
                                    <div className="text-xs text-muted-foreground">
                                        {t('Showing {start}-{end} of {total}', {
                                            start: (currentCasesPage - 1) * casesPerPage + 1,
                                            end: Math.min(currentCasesPage * casesPerPage, cases.length),
                                            total: cases.length,
                                        })}
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <Button
                                            type="button"
                                            variant="outline"
                                            size="sm"
                                            disabled={currentCasesPage <= 1}
                                            onClick={() => setCasesPage(page => Math.max(1, page - 1))}
                                        >
                                            {t('Previous')}
                                        </Button>
                                        <Button
                                            type="button"
                                            variant="outline"
                                            size="sm"
                                            disabled={currentCasesPage >= totalCasePages}
                                            onClick={() => setCasesPage(page => Math.min(totalCasePages, page + 1))}
                                        >
                                            {t('Next')}
                                        </Button>
                                    </div>
                                </div>
                            )}
                        </>
                    )}
                </TabsContent>
            </Tabs>

            {/* Case editor modal */}
            {editingCase && (
                <CaseEditorModal
                    initial={editingCase !== 'new' ? editingCase : undefined}
                    intentOptions={intentOptions}
                    onSave={handleSaveCase}
                    onCancel={() => setEditingCase(null)}
                />
            )}
        </div>
    );
}

// ── Main Evaluation component ─────────────────────────────────────────────────

export function Evaluation({ projectId }: { projectId: string }) {
    const { tenantId, setId, runId } = useParams<{ tenantId: string; setId?: string; runId?: string }>();
    const navigate = useNavigate();
    const { t } = useI18n();
    const [evalSet, setEvalSet] = useState<EvalSet | null>(null);
    const [setLoadErrorId, setSetLoadErrorId] = useState<string | null>(null);
    const basePath = useMemo(() => (
        tenantId ? `/${tenantId}/${projectId}/eval` : `/eval`
    ), [projectId, tenantId]);

    const handleSelectSet = useCallback((nextSetId: string) => {
        void navigate(`${basePath}/${nextSetId}`);
    }, [basePath, navigate]);

    const handleBackToSets = useCallback(() => {
        void navigate(basePath);
    }, [basePath, navigate]);

    const handleSelectRun = useCallback((nextRunId: string) => {
        if (!setId) return;
        void navigate(`${basePath}/${setId}/runs/${nextRunId}`);
    }, [basePath, navigate, setId]);

    const handleBackToSet = useCallback(() => {
        if (setId) {
            void navigate(`${basePath}/${setId}`);
        } else {
            void navigate(basePath);
        }
    }, [basePath, navigate, setId]);

    useEffect(() => {
        let cancelled = false;
        if (!setId) {
            return () => { cancelled = true; };
        }

        void api.getEvalSet(projectId, setId).then((res) => {
            if (cancelled) return;
            if (res.data) {
                setEvalSet(res.data);
                setSetLoadErrorId(null);
            } else {
                setSetLoadErrorId(setId);
            }
        }).catch(() => {
            if (!cancelled) setSetLoadErrorId(setId);
        });

        return () => { cancelled = true; };
    }, [projectId, setId]);

    if (!setId) {
        return <SetsList projectId={projectId} onSelect={handleSelectSet} />;
    }

    const selectedEvalSet = evalSet?.id === setId ? evalSet : null;
    const setLoadError = setLoadErrorId === setId;

    if (!selectedEvalSet && !setLoadError) {
        return (
            <div className="flex items-center justify-center py-20">
                <Loader className="size-5 animate-spin text-muted-foreground" />
            </div>
        );
    }

    if (setLoadError || !selectedEvalSet) {
        return (
            <div className="mx-auto flex max-w-3xl flex-col items-center justify-center py-20 text-center">
                <FlaskConical className="mb-3 size-10 text-muted-foreground/50" />
                <h2 className="text-lg font-semibold">{t('Evaluation set not found')}</h2>
                <Button variant="outline" size="sm" className="mt-4" onClick={handleBackToSets}>
                    <ArrowLeft className="size-4" />
                    {t('Evaluation')}
                </Button>
            </div>
        );
    }

    return (
        <SetDetail
            projectId={projectId}
            evalSet={selectedEvalSet}
            selectedRunId={runId}
            onBack={handleBackToSets}
            onSelectRun={handleSelectRun}
            onBackFromRun={handleBackToSet}
        />
    );
}
