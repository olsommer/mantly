import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Inbox, Loader, AlertCircle } from 'lucide-react';
import { api } from '@/api/endpoints';
import type { Email, EmailResponse, Message } from '@/models/email';
import { EmailMessage } from '@/components/messages/email';
import { StaticActionsPanel } from '@/components/pipeline/StaticActionsPanel';
import { ResponsePanel } from '@/components/pipeline/ResponsePanel';
import { SecurityRiskBanner } from '@/components/pipeline/SecurityRiskBanner';
import { FeedbackBar } from '@/components/pipeline/FeedbackBar';
import { syncLanguage, t } from '@/lib/i18n';
import { getInteractiveDemoScenario } from '@demo/interactive-scenarios';

type EmbedStatus = 'idle' | 'processing' | 'done' | 'error';
type EmbedMode = 'admin-preview' | 'landing-demo';

const ADMIN_PREVIEW_ORIGINS = [
    'https://app.mantly.io',
    'http://localhost:5174',
    'http://127.0.0.1:5174',
];

const SAAS_ADDIN_HOSTS = ['addin.mantly.io'];

const CUSTOM_ADMIN_PREVIEW_ORIGINS = (
    typeof import.meta.env.VITE_EMBED_ADMIN_ORIGINS === 'string'
        ? import.meta.env.VITE_EMBED_ADMIN_ORIGINS
        : ''
)
    .split(',')
    .map((origin) => origin.trim())
    .filter(Boolean);

const LANDING_DEMO_ORIGINS = [
    'https://mantly.io',
    'https://www.mantly.io',
    'http://localhost:5175',
    'http://127.0.0.1:5175',
];

function getEmbedMode(): EmbedMode {
    return new URLSearchParams(window.location.search).get('embed') === 'landing-demo'
        ? 'landing-demo'
        : 'admin-preview';
}

function isSaasAddinHost(): boolean {
    return SAAS_ADDIN_HOSTS.includes(window.location.hostname);
}

function isAdminPreviewOrigin(origin: string): boolean {
    if (ADMIN_PREVIEW_ORIGINS.includes(origin)) return true;
    if (isSaasAddinHost()) return false;
    return origin === window.location.origin || CUSTOM_ADMIN_PREVIEW_ORIGINS.includes(origin);
}

function isLandingDemoOrigin(origin: string): boolean {
    return LANDING_DEMO_ORIGINS.includes(origin);
}

function allowedReadyTarget(mode: EmbedMode): string | null {
    if (!document.referrer) return null;
    try {
        const origin = new URL(document.referrer).origin;
        if (mode === 'landing-demo' && isLandingDemoOrigin(origin)) return origin;
        if (mode === 'admin-preview' && isAdminPreviewOrigin(origin)) return origin;
    } catch {
        return null;
    }
    return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isEmail(value: unknown): value is Email {
    return (
        isRecord(value)
        && typeof value.id === 'string'
        && typeof value.fromAddress === 'string'
        && typeof value.subject === 'string'
        && typeof value.body === 'string'
    );
}

function decodeJwtEmail(token?: string): string | null {
    if (!token) return null;
    const [, payload] = token.split('.');
    if (!payload) return null;
    try {
        const normalized = payload.replace(/-/g, '+').replace(/_/g, '/');
        const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=');
        const decoded = JSON.parse(decodeURIComponent(escape(atob(padded)))) as unknown;
        if (!isRecord(decoded)) return null;
        const email = decoded.email;
        return typeof email === 'string' && email ? email : null;
    } catch {
        return null;
    }
}

function previewChatId(projectId: string | undefined, emailId: string, draft = false): string {
    return draft && projectId ? `preview:${projectId}:${emailId}` : emailId;
}

function decodePreviewPayload(): { draft?: boolean; projectId?: string; email?: Email; authToken?: string; authEmail?: string | null } | null {
    const encoded = new URLSearchParams(window.location.search).get('preview');
    if (!encoded) return null;

    try {
        const json = decodeURIComponent(escape(atob(encoded)));
        const parsed: unknown = JSON.parse(json);
        if (!isRecord(parsed) || !isEmail(parsed.email)) return null;

        // Store the admin auth token so the API client can use it for /api/admin/* calls
        if (typeof parsed.authToken === 'string') {
            localStorage.setItem('admin_auth_token', parsed.authToken);
        }

        const authToken = typeof parsed.authToken === 'string' ? parsed.authToken : undefined;
        return {
            draft: typeof parsed.draft === 'boolean' ? parsed.draft : undefined,
            projectId: typeof parsed.projectId === 'string' ? parsed.projectId : undefined,
            email: parsed.email,
            authToken,
            authEmail: decodeJwtEmail(authToken),
        };
    } catch {
        return null;
    }
}

export const Embed = () => {
    const mode = getEmbedMode();
    const isLandingDemo = mode === 'landing-demo';
    const trustedParentOrigin = allowedReadyTarget(mode);
    const blockedByParent = document.referrer !== '' && !trustedParentOrigin;
    const [status, setStatus] = useState<EmbedStatus>('idle');
    const [error, setError] = useState<string | null>(null);
    const [messages, setMessages] = useState<Message[]>([]);
    const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
    const [activeChatId, setActiveChatId] = useState('');
    const [previewUser, setPreviewUser] = useState<string | null>(null);
    const [revealOverride, setRevealOverride] = useState(false);
    const [, setLocaleVersion] = useState(0);
    const abortRef = useRef<AbortController | null>(null);
    const demoTimerRef = useRef<number | null>(null);

    // Notify parent of status changes
    const postStatus = useCallback((origin: string, s: EmbedStatus, err?: string) => {
        window.parent.postMessage(
            { type: 'embed-status', status: s, ...(err ? { error: err } : {}) },
            origin,
        );
    }, []);

    const applyLocale = useCallback((value: unknown) => {
        const locale = syncLanguage(value);
        setLocaleVersion(version => version + 1);
        return locale;
    }, []);

    // Process an email through the real or draft pipeline
    const analyze = useCallback(async (
        email: Email,
        draft = false,
        projectId?: string,
        userEmail?: string | null,
        parentOrigin?: string,
    ) => {
        if (isLandingDemo) return;
        // Abort any in-flight request
        abortRef.current?.abort();
        const ctrl = new AbortController();
        abortRef.current = ctrl;
        const targetOrigin = parentOrigin ?? allowedReadyTarget('admin-preview');

        setStatus('processing');
        setError(null);
        setMessages([]);
        setActiveProjectId(projectId ?? null);
        setActiveChatId(previewChatId(projectId, email.id, draft));
        setPreviewUser(userEmail ?? null);
        if (targetOrigin) postStatus(targetOrigin, 'processing');

        try {
            const request = {
                email,
                action: 'respond',
                creator: userEmail ?? 'demo@mantly.io',
                ...(projectId ? { projectId } : {}),
            } as const;
            const res = draft
                ? await api.previewProcess(projectId ?? '', request)
                : await api.process(request);

            if (ctrl.signal.aborted) return;

            if (res.error || !res.data) {
                const errMsg = res.error ?? 'Unknown backend error';
                setError(errMsg);
                setStatus('error');
                if (targetOrigin) postStatus(targetOrigin, 'error', errMsg);
                return;
            }

            setMessages(res.data);
            setStatus('done');
            if (targetOrigin) postStatus(targetOrigin, 'done');
        } catch (err) {
            if (ctrl.signal.aborted) return;
            const errMsg = err instanceof Error ? err.message : 'Request failed';
            setError(errMsg);
            setStatus('error');
            if (targetOrigin) postStatus(targetOrigin, 'error', errMsg);
        }
    }, [isLandingDemo, postStatus]);

    const runCachedDemo = useCallback((scenarioId: string | null | undefined, localeValue: unknown, origin: string) => {
        if (!isLandingDemo || !isLandingDemoOrigin(origin)) return;

        abortRef.current?.abort();
        if (demoTimerRef.current) window.clearTimeout(demoTimerRef.current);

        const locale = applyLocale(localeValue);
        const scenario = getInteractiveDemoScenario(locale, scenarioId);
        setStatus('processing');
        setError(null);
        setMessages([]);
        setActiveProjectId(null);
        setActiveChatId(`landing-demo:${scenario.id}`);
        setPreviewUser(null);
        setRevealOverride(false);
        postStatus(origin, 'processing');

        demoTimerRef.current = window.setTimeout(() => {
            const message: Message = {
                role: 'response',
                user: 'response',
                content: scenario.response,
            };
            setMessages([message]);
            setStatus('done');
            postStatus(origin, 'done');
        }, 1200);
    }, [applyLocale, isLandingDemo, postStatus]);

    // Reset to idle
    const reset = useCallback(() => {
        abortRef.current?.abort();
        if (demoTimerRef.current) window.clearTimeout(demoTimerRef.current);
        setStatus('idle');
        setError(null);
        setMessages([]);
        setActiveChatId('');
        setPreviewUser(null);
        setRevealOverride(false);
    }, []);

    // Listen for postMessage from admin
    useEffect(() => {
        let acked = false;

        const handler = (event: MessageEvent) => {
            const data = isRecord(event.data) ? event.data : {};
            const { type } = data;

            if (type === 'analyze-email') {
                if (mode !== 'admin-preview' || !isAdminPreviewOrigin(event.origin)) return;
                const email = data.email;
                if (!isEmail(email)) return;
                const draft = data.draft === true;
                const authEmail = typeof data.authToken === 'string' ? decodeJwtEmail(data.authToken) : null;
                if (typeof data.authToken === 'string') {
                    localStorage.setItem('admin_auth_token', data.authToken);
                }
                void analyze(email, draft, typeof data.projectId === 'string' ? data.projectId : undefined, authEmail, event.origin);
            } else if (type === 'run-cached-demo') {
                if (mode !== 'landing-demo' || !isLandingDemoOrigin(event.origin)) return;
                runCachedDemo(typeof data.scenarioId === 'string' ? data.scenarioId : null, data.locale, event.origin);
            } else if (type === 'set-locale') {
                if (mode !== 'landing-demo' || !isLandingDemoOrigin(event.origin)) return;
                applyLocale(data.locale);
            } else if (type === 'reset') {
                if (mode === 'landing-demo' && !isLandingDemoOrigin(event.origin)) return;
                if (mode === 'admin-preview' && !isAdminPreviewOrigin(event.origin)) return;
                reset();
            } else if (type === 'embed-ack') {
                if (mode === 'landing-demo' && !isLandingDemoOrigin(event.origin)) return;
                if (mode === 'admin-preview' && !isAdminPreviewOrigin(event.origin)) return;
                acked = true;
            }
        };

        window.addEventListener('message', handler);

        // Signal ready to parent, retrying until acknowledged
        const targetOrigin = allowedReadyTarget(mode);
        const signalReady = () => {
            if (targetOrigin) {
                window.parent.postMessage({ type: 'embed-ready', mode }, targetOrigin);
            }
        };
        signalReady();
        const interval = setInterval(() => { if (!acked) signalReady(); }, 500);

        return () => {
            window.removeEventListener('message', handler);
            clearInterval(interval);
        };
    }, [analyze, applyLocale, mode, reset, runCachedDemo]);

    useEffect(() => {
        if (isLandingDemo) return;
        const preview = decodePreviewPayload();
        if (preview?.email) {
            const { email } = preview;
            const timer = window.setTimeout(() => {
                void analyze(email, preview.draft ?? false, preview.projectId, preview.authEmail ?? null);
            }, 0);
            return () => window.clearTimeout(timer);
        }
    }, [analyze, isLandingDemo]);

    // Extract pipeline results from the latest response message
    const latestResponse = useMemo(() => {
        for (let i = messages.length - 1; i >= 0; i--) {
            if (messages[i].user === 'response') return messages[i];
        }
        return null;
    }, [messages]);

    const latestContent = latestResponse?.content as EmailResponse | undefined;
    const identityResult = latestContent?.identityResult;
    const intentResult = latestContent?.intentResult;
    const phishingResult = latestContent?.phishingResult;
    const promptInjectionResult = latestContent?.promptInjectionResult;
    const requiresHuman = latestContent?.requiresHuman ?? false;
    const responseEnabled = intentResult?.response?.enabled ?? false;
    const hasComposedResponse = Boolean(latestContent?.emailBody?.trim());
    const showActionsPanel = !requiresHuman && (!!identityResult || !!intentResult);

    // Derived: auto-reveal unless response config has auto=false and user hasn't clicked reveal
    const responseRevealed = revealOverride || intentResult?.response?.auto !== false;

    if (blockedByParent) {
        return null;
    }

    // ── Idle ──
    if (status === 'idle') {
        return (
            <div className="flex flex-col items-center justify-center h-full text-center gap-3 p-6">
                <Inbox className="size-10 text-muted-foreground/30" />
                <p className="text-sm text-muted-foreground">
                    {isLandingDemo ? t('embed.landingReady') : t('embed.dropEmail')}
                </p>
            </div>
        );
    }

    // ── Processing ──
    if (status === 'processing') {
        return (
            <div className="flex flex-col items-center justify-center h-full text-center gap-3 p-6">
                <Loader className="size-8 animate-spin text-muted-foreground/50" />
            </div>
        );
    }

    // ── Error ──
    if (status === 'error') {
        return (
            <div className="flex items-start justify-center p-6 pt-12">
                <div className="rounded-md bg-destructive/10 border border-destructive/20 px-4 py-3 text-sm text-destructive flex items-start gap-2">
                    <AlertCircle className="size-4 shrink-0 mt-0.5" />
                    <div>
                        <p className="font-medium">{t('embed.backendError')}</p>
                        <p className="mt-0.5 text-xs">{error}</p>
                    </div>
                </div>
            </div>
        );
    }

    // ── Done — render real add-in UI ──
    return (
        <div className="h-full flex flex-col">
            <SecurityRiskBanner
                phishingResult={phishingResult}
                promptInjectionResult={promptInjectionResult}
            />
            {showActionsPanel && (
                <StaticActionsPanel
                    identityResult={identityResult}
                    intentResult={intentResult}
                    chatId="embed-preview"
                    projectId={activeProjectId}
                    responseRevealed={responseRevealed}
                    hasComposedResponse={hasComposedResponse}
                    onRevealResponse={() => setRevealOverride(true)}
                />
            )}

            <div className={requiresHuman ? "flex flex-1 overflow-y-auto" : "flex min-h-0 flex-1 flex-col overflow-y-auto"}>
                {messages.map((message, index) => {
                    if (message.user !== 'response') return null;

                    const isLatest = message === latestResponse;
                    if (
                        isLatest
                        && !hasComposedResponse
                        && showActionsPanel
                        && (!responseEnabled || !responseRevealed)
                    ) {
                        return null;
                    }

                    return (
                        <ResponsePanel key={index}>
                            <div className={isLatest && requiresHuman ? "flex min-h-full flex-1 overflow-y-auto" : "min-h-0 flex-1"}>
                                <EmailMessage
                                    message={message}
                                    index={index}
                                    isNewChat={true}
                                    chatId="embed-preview"
                                    demoMode={isLandingDemo}
                                />
                            </div>
                        </ResponsePanel>
                    );
                })}
            </div>
            {showActionsPanel && (
                <div className="flex shrink-0 items-center justify-start bg-white px-2 py-2">
                    {isLandingDemo ? (
                        <p className="px-1 text-xs text-muted-foreground">
                            {t('embed.demoDisclaimer')}
                        </p>
                    ) : (
                        <FeedbackBar
                            projectId={activeProjectId ?? ''}
                            chatId={activeChatId}
                            identityResult={identityResult}
                            intentResult={intentResult}
                            userOverride={previewUser}
                        />
                    )}
                </div>
            )}
        </div>
    );
};
