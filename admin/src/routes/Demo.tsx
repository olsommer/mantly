import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, CloudUpload, Loader, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from '@/components/ui/select';
import { settings } from '@/settings';
import { toast } from 'sonner';
import { api } from '@/api/endpoints';
import type { EvalCase, EvalSet } from '@/api/endpoints';
import { useI18n } from '@/lib/i18n-context';

// ── URL helpers ──────────────────────────────────────────────────────────────

const getAddinOrigin = () => new URL(settings.addinBaseUrl).origin;

const getAddinUrl = () => `${getAddinOrigin()}/addin`;

function encodePreviewPayload(payload: unknown): string {
    return btoa(unescape(encodeURIComponent(JSON.stringify(payload))));
}

function buildIframeSrc(projectId?: string, eml?: ParsedEml | null): string {
    const baseUrl = `${getAddinUrl()}/?embed=true`;
    if (!eml) return baseUrl;

    const previewPayload = encodePreviewPayload({
        draft: true,
        projectId,
        email: {
            id: eml.id,
            subject: eml.subject,
            fromAddress: eml.from,
            body: eml.body,
            attachments: [],
        },
        // Pass the admin auth token so the iframe can call /api/admin/* preview routes
        authToken: localStorage.getItem('admin_auth_token') ?? undefined,
        nonce: crypto.randomUUID(),
    });

    return `${baseUrl}&preview=${encodeURIComponent(previewPayload)}`;
}

// ── Types ────────────────────────────────────────────────────────────────────

interface ParsedEml {
    id: string;
    subject: string;
    from: string;
    body: string;
}

interface TestMailOption {
    id: string;
    source: 'eval';
    setId: string;
    setName: string;
    caseName: string;
    subject: string;
    fromAddress: string;
    body: string;
}

// ── EML parser ───────────────────────────────────────────────────────────────

function parseEml(raw: string): ParsedEml {
    const lines = raw.split(/\r?\n/);
    let from = '';
    let subject = '';
    const bodyLines: string[] = [];
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
                const m = line.match(/boundary="?([^";]+)"?/i);
                if (m) boundary = m[1].trim();
            }
        } else {
            if (boundary) {
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
    }

    // Decode quoted-printable soft line breaks
    const body = bodyLines
        .join('\n')
        .replace(/=\r?\n/g, '')
        .trim();

    return {
        id: crypto.randomUUID(),
        subject: subject || '(no subject)',
        from: from || 'unknown@example.com',
        body: body || raw.trim(),
    };
}

// ── Main Demo component ──────────────────────────────────────────────────────

export const Demo = ({ projectId, isDemoAccount = false }: { projectId: string; isDemoAccount?: boolean }) => {
    const [parsed, setParsed] = useState<ParsedEml | null>(null);
    const [selectedTestMailId, setSelectedTestMailId] = useState('');
    const [evalSets, setEvalSets] = useState<EvalSet[]>([]);
    const [evalCasesBySet, setEvalCasesBySet] = useState<Record<string, EvalCase[]>>({});
    const [loadingTestMails, setLoadingTestMails] = useState(true);
    const [isDragging, setIsDragging] = useState(false);
    const [processing, setProcessing] = useState(false);
    const [embedReady, setEmbedReady] = useState(false);
    const [iframeSrc, setIframeSrc] = useState(() => buildIframeSrc(projectId));
    const fileInputRef = useRef<HTMLInputElement>(null);
    const iframeRef = useRef<HTMLIFrameElement>(null);
    const { t } = useI18n();
    const visibleEvalSets = isDemoAccount
        ? evalSets.filter(set => set.name !== 'Demo test emails')
        : evalSets;
    const evalMailOptions = visibleEvalSets.flatMap((set): TestMailOption[] =>
        (evalCasesBySet[set.id] ?? []).map(testCase => ({
            id: `eval:${testCase.id}`,
            source: 'eval',
            setId: set.id,
            setName: set.name,
            caseName: testCase.name,
            subject: testCase.emailSubject,
            fromAddress: testCase.emailFrom,
            body: testCase.emailBody,
        })),
    );
    const testMailOptions = evalMailOptions;
    const selectedTestMail = testMailOptions.find(email => email.id === selectedTestMailId);

    const updateIframeSrc = useCallback((nextSrc: string) => {
        if (nextSrc !== iframeSrc) {
            setEmbedReady(false);
        }
        setIframeSrc(nextSrc);
    }, [iframeSrc]);

    const sendReset = useCallback(() => {
        iframeRef.current?.contentWindow?.postMessage(
            { type: 'reset' },
            getAddinOrigin(),
        );
    }, []);

    // ── Listen for messages from the embed iframe ────────────────────────────

    const handleMessage = useCallback((event: MessageEvent) => {
        const addinOrigin = getAddinOrigin();
        // Accept messages from the add-in origin (dev or prod)
        if (event.origin !== addinOrigin && event.origin !== window.location.origin) return;

        const data = typeof event.data === 'object' && event.data !== null
            ? event.data as Record<string, unknown>
            : {};
        const { type } = data;

        if (type === 'embed-ready') {
            setEmbedReady(true);
            // Acknowledge so the iframe stops retrying
            iframeRef.current?.contentWindow?.postMessage({ type: 'embed-ack' }, getAddinOrigin());
        } else if (type === 'embed-status') {
            const { status } = data;
            setProcessing(status === 'processing');
        }
    }, []);

    const handleIframeLoad = useCallback(() => {
        // In local dev the child app can be ready even if the postMessage
        // handshake is dropped during startup. Mark it ready on load so the
        // preview becomes visible and parent->child messages can proceed.
        setEmbedReady(true);
        setProcessing(false);
    }, []);

    useEffect(() => {
        window.addEventListener('message', handleMessage);
        return () => window.removeEventListener('message', handleMessage);
    }, [handleMessage]);

    useEffect(() => {
        let cancelled = false;

        const loadTestMails = async () => {
            setLoadingTestMails(true);
            const setsRes = await api.getEvalSets(projectId);
            if (cancelled) return;

            if (setsRes.error || !setsRes.data) {
                toast.error(t("Couldn't load evaluation test mails: {error}", { error: setsRes.error ?? t('Unknown error') }));
                setEvalSets([]);
                setEvalCasesBySet({});
                setLoadingTestMails(false);
                return;
            }

            setEvalSets(setsRes.data);
            const caseEntries = await Promise.all(
                setsRes.data
                    .filter(set => set.caseCount > 0)
                    .map(async set => {
                        const casesRes = await api.getEvalCases(projectId, set.id);
                        return [set.id, casesRes.data ?? []] as const;
                    }),
            );

            if (cancelled) return;
            setEvalCasesBySet(Object.fromEntries(caseEntries));
            setLoadingTestMails(false);
        };

        void loadTestMails();
        return () => { cancelled = true; };
    }, [projectId, t]);

    // ── EML file handling ────────────────────────────────────────────────────

    const handleFile = (file: File) => {
        if (!file.name.endsWith('.eml') && file.type !== 'message/rfc822') {
            toast.error(t('Please drop an .eml file'));
            return;
        }
        const reader = new FileReader();
        reader.onload = (e) => {
            const text = e.target?.result as string;
            const eml = parseEml(text);
            setParsed(eml);
            setSelectedTestMailId('');
            setProcessing(false);
            updateIframeSrc(buildIframeSrc(projectId));
            sendReset();
        };
        reader.readAsText(file);
    };

    const onDrop = (e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(false);
        const file = e.dataTransfer.files[0];
        if (file) handleFile(file);
    };

    const onDragOver = (e: React.DragEvent) => { e.preventDefault(); setIsDragging(true); };
    const onDragLeave = () => setIsDragging(false);

    const selectTestMail = (id: string) => {
        const email = testMailOptions.find(item => item.id === id);
        if (!email) return;
        setSelectedTestMailId(id);
        setParsed({
            id: email.id,
            subject: email.subject,
            from: email.fromAddress,
            body: email.body,
        });
        setProcessing(false);
        updateIframeSrc(buildIframeSrc(projectId));
        sendReset();
    };

    // ── Analysis ─────────────────────────────────────────────────────────────

    const analyze = () => {
        if (!parsed) return;
        setProcessing(true);
        updateIframeSrc(buildIframeSrc(projectId, parsed));
        window.setTimeout(() => setProcessing(false), 1000);
    };

    const clearEmail = () => {
        setParsed(null);
        setSelectedTestMailId('');
        setProcessing(false);
        updateIframeSrc(buildIframeSrc(projectId));
        sendReset();
    };

    // ── Render ───────────────────────────────────────────────────────────────

    return (
        <div className="flex flex-1 overflow-hidden h-full">

            {/* ── LEFT: Drop zone / parsed preview ── */}
            <div className="flex-1 flex flex-col border-r bg-gray-50 overflow-hidden">

                <div className="flex min-h-0 flex-1 p-6">
                    <div className="flex min-h-0 w-full flex-1 flex-col gap-6">
                        {!parsed ? (
                            <div className="flex flex-1 flex-col gap-5">
                                {(loadingTestMails || testMailOptions.length > 0) && (
                                    <>
                                        <div className="rounded-xl border bg-white p-4">
                                            <Label htmlFor="demoTestMail" className="mb-2">{t('Select email')}</Label>
                                            <Select value={selectedTestMailId} onValueChange={selectTestMail} disabled={loadingTestMails}>
                                                <SelectTrigger id="demoTestMail" className="h-auto min-h-10 w-full bg-white">
                                                    {selectedTestMail ? (
                                                        <div className="flex min-w-0 flex-col items-start gap-0.5 py-0.5 text-left">
                                                            <span className="max-w-full truncate font-medium">{selectedTestMail.subject}</span>
                                                            <span className="max-w-full truncate pl-0 text-xs text-muted-foreground">{selectedTestMail.fromAddress}</span>
                                                        </div>
                                                    ) : (
                                                        <SelectValue placeholder={loadingTestMails ? t('Loading test mails...') : t('Select a test mail')} />
                                                    )}
                                                </SelectTrigger>
                                                <SelectContent>
                                                    {visibleEvalSets.map(set => {
                                                        const options = evalMailOptions.filter(option => option.setId === set.id);
                                                        if (options.length === 0) return null;
                                                        return (
                                                            <SelectGroup key={set.id}>
                                                                <SelectLabel>{set.name}</SelectLabel>
                                                                {options.map(email => (
                                                                    <SelectItem key={email.id} value={email.id} textValue={`${email.caseName} ${email.subject} ${email.fromAddress}`}>
                                                                        <div className="flex min-w-0 flex-col items-start gap-0.5 py-0.5 text-left">
                                                                            <span className="font-medium">{email.caseName}</span>
                                                                            <span className="pl-0 text-xs text-muted-foreground">{email.subject} · {email.fromAddress}</span>
                                                                        </div>
                                                                    </SelectItem>
                                                                ))}
                                                            </SelectGroup>
                                                        );
                                                    })}
                                                </SelectContent>
                                            </Select>
                                        </div>
                                        <div className="text-center text-xs font-medium text-muted-foreground">{t('- OR -')}</div>
                                    </>
                                )}

                                <div
                                    onDrop={onDrop}
                                    onDragOver={onDragOver}
                                    onDragLeave={onDragLeave}
                                    onClick={() => fileInputRef.current?.click()}
                                    className={`flex min-h-64 flex-1 cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed transition-colors
                                        ${isDragging
                                            ? 'border-foreground bg-muted/60'
                                            : 'border-muted-foreground/25 hover:border-muted-foreground/50 hover:bg-muted/20'}`}
                                >
                                    <CloudUpload className={`size-8 mb-3 transition-colors ${isDragging ? 'text-foreground' : 'text-muted-foreground/50'}`} />
                                    <p className="text-sm font-medium text-muted-foreground">{t('Drop an .eml file here')}</p>
                                    <p className="text-xs text-muted-foreground/60 mt-1">{t('or click to browse')}</p>
                                    <input
                                        ref={fileInputRef}
                                        type="file"
                                        accept=".eml,message/rfc822"
                                        className="hidden"
                                        onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
                                    />
                                </div>
                            </div>
                        ) : (
                            /* ── Parsed email card ── */
                            <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border bg-white">
                                <div className="flex shrink-0 items-center justify-between border-b bg-muted/20 px-4 py-3">
                                    <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{t('Parsed email')}</span>
                                    <Button
                                        type="button"
                                        variant="ghost"
                                        size="icon-sm"
                                        onClick={clearEmail}
                                        className="text-muted-foreground hover:text-foreground"
                                    >
                                        <X className="size-4" />
                                    </Button>
                                </div>
                                <div className="flex min-h-0 flex-1 flex-col divide-y text-sm">
                                    <div className="flex shrink-0 gap-3 px-4 py-2.5">
                                        <span className="text-xs text-muted-foreground w-14 shrink-0 pt-0.5">{t('From')}</span>
                                        <span className="text-xs break-all">{parsed.from}</span>
                                    </div>
                                    <div className="flex shrink-0 gap-3 px-4 py-2.5">
                                        <span className="text-xs text-muted-foreground w-14 shrink-0 pt-0.5">{t('Subject')}</span>
                                        <span className="text-xs font-medium">{parsed.subject}</span>
                                    </div>
                                    <div className="flex min-h-0 flex-1 gap-3 px-4 py-2.5">
                                        <span className="text-xs text-muted-foreground w-14 shrink-0 pt-0.5">{t('Body')}</span>
                                        <pre className="min-h-0 flex-1 overflow-y-auto whitespace-pre-wrap rounded-md bg-muted/30 p-3 text-xs leading-relaxed text-muted-foreground">
                                            {parsed.body}
                                        </pre>
                                    </div>
                                </div>
                                <div className="shrink-0 border-t bg-muted/10 px-4 py-3">
                                    <Button
                                        className="w-full"
                                        onClick={analyze}
                                        disabled={processing}
                                        aria-label={processing ? t('Analyzing...') : t('Analyze email')}
                                    >
                                        {processing
                                            ? <><Loader className="size-4 animate-spin" /> {t('Analyzing...')}</>
                                            : <ArrowRight className="size-4" aria-hidden="true" />}
                                    </Button>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {/* ── RIGHT: Add-in preview (iframe) ── */}
            <div className="w-[30%] flex flex-col bg-white overflow-hidden">

                {!embedReady && (
                    <div className="flex flex-col items-center justify-center flex-1 gap-3">
                        <Loader className="size-6 animate-spin text-muted-foreground/40" />
                        <p className="text-xs text-muted-foreground">{t('Loading add-in...')}</p>
                    </div>
                )}

                <iframe
                    ref={iframeRef}
                    src={iframeSrc}
                    onLoad={handleIframeLoad}
                    className={`flex-1 border-0 ${embedReady ? '' : 'invisible'}`}
                    title={t('Add-in preview')}
                />
            </div>

        </div>
    );
};
