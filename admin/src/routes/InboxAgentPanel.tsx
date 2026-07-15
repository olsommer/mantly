import type { ReactNode, RefObject } from 'react';
import { BookOpen, Copy, ExternalLink, Loader, MessageSquare, Plus, Send, Sparkles, TriangleAlert } from 'lucide-react';

import type { KnowledgeArticle, KnowledgeGap, SupportAgentAnswer, SupportAgentMessage, SupportAiRun, SupportIssue } from '@/api/endpoints';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';

type TranslateFn = (key: string, params?: Record<string, string | number>) => string;

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
    reviewStatus: string;
    freshnessStatus: string;
    needsReview: boolean;
    score?: number;
    evidence: Array<{
        path: string;
        contentSha256: string;
        bodySha256: string;
        excerpt: string;
        chunkIndex: number;
        chunkCount: number;
    }>;
};

export type AgentArticleSource = {
    key?: string;
    title?: string;
    run?: SupportAiRun;
    answer?: string;
    tags?: string[];
};

type InboxAgentPanelProps = {
    variant?: 'compact' | 'full';
    issue: SupportIssue;
    quickActions: AgentQuickAction[];
    questionRef: RefObject<HTMLTextAreaElement | null>;
    question: string;
    onQuestionChange: (value: string) => void;
    asking: boolean;
    runningActionKey: string;
    answer: SupportAgentAnswer | null;
    runs: SupportAiRun[];
    messages: SupportAgentMessage[];
    creatingKnowledgeArticle: string;
    t: TranslateFn;
    onAsk: (questionOverride?: string, createDraft?: boolean, actionKey?: string, autoSend?: boolean) => void | Promise<void>;
    onCreateKnowledgeArticle: (source: AgentArticleSource) => void | Promise<void>;
    onApplyAnswerToReply: (mode: 'replace' | 'append') => void;
    onApplyRunToReply: (run: SupportAiRun, mode: 'replace' | 'append') => void;
    onStartFollowUp: (run: SupportAiRun) => void;
    renderKnowledgeGap: (gap: KnowledgeGap | null | undefined, compact?: boolean) => ReactNode;
};

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function textFrom(value: unknown): string {
    if (typeof value === 'string') return value.trim();
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
    return '';
}

function textListFrom(value: unknown): string[] {
    if (!Array.isArray(value)) return [];
    return [...new Set(value.map(textFrom).filter(Boolean))].slice(0, 10);
}

function formatTime(value: string) {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
}

function knowledgeVisibilityLabel(visibility: string, isPublic?: boolean): string {
    if (isPublic) return 'Public';
    if (visibility === 'internal') return 'Internal';
    if (visibility === 'private') return 'Private';
    return visibility || 'Internal';
}

function knowledgeSourceUrl(value: Pick<KnowledgeArticle, 'sourceUrl'> | AgentCitationPreview): string {
    return textFrom(value.sourceUrl);
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
    const evidence = Array.isArray(value.evidence)
        ? value.evidence.filter(isRecord).map(item => ({
            path: textFrom(item.path),
            contentSha256: textFrom(item.contentSha256 ?? item.content_sha256),
            bodySha256: textFrom(item.bodySha256 ?? item.body_sha256),
            excerpt: textFrom(item.excerpt),
            chunkIndex: Number(item.chunkIndex ?? item.chunk_index ?? 0),
            chunkCount: Number(item.chunkCount ?? item.chunk_count ?? 0),
        })).filter(item => item.path)
        : [];
    return {
        id,
        title: title || id,
        body: textFrom(value.body),
        status: textFrom(value.status),
        tags,
        sourceUrl: textFrom(value.sourceUrl ?? value.source_url ?? metadata.sourceUrl ?? metadata.source_url ?? metadata.url),
        visibility: textFrom(value.visibility ?? metadata.visibility ?? metadata.access),
        public: value.public === true || metadata.public === true,
        reviewStatus: textFrom(value.reviewStatus ?? value.review_status ?? metadata.reviewStatus ?? metadata.review_status),
        freshnessStatus: textFrom(value.freshnessStatus ?? value.freshness_status ?? metadata.freshnessStatus ?? metadata.freshness_status),
        needsReview: value.needsReview === true
            || value.needs_review === true
            || metadata.needsReview === true
            || metadata.needs_review === true,
        score: rawScore,
        evidence,
    };
}

function agentRunQuestion(run: SupportAiRun): string {
    return textFrom(run.metadata.question);
}

function agentRunAnswer(run: SupportAiRun): string {
    return textFrom(run.metadata.answer) || run.summary;
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

function agentRunPriorCount(run: SupportAiRun): number {
    const ids = run.metadata.priorAgentRunIds;
    return Array.isArray(ids) ? ids.length : 0;
}

function agentRunKnowledgeToolCalls(run: SupportAiRun): Array<Record<string, unknown>> {
    const metadataCalls = run.metadata.knowledgeToolCalls;
    if (Array.isArray(metadataCalls)) {
        return metadataCalls.filter(isRecord);
    }
    return (run.toolCalls ?? []).filter(
        (call): call is Record<string, unknown> => isRecord(call) && textFrom(call.type) === 'knowledge_bash',
    );
}

function agentAccountContextStatus(value: unknown): string {
    if (!isRecord(value)) return '';
    const health = isRecord(value.health) ? value.health : {};
    return textFrom(health.status ?? value.healthStatus);
}

function agentAccountContextOpenSignals(value: unknown): number {
    if (!isRecord(value) || !Array.isArray(value.openSignals)) return 0;
    return value.openSignals.length;
}

function agentConversationContextCounts(value: unknown): { issues: number; messages: number } | null {
    if (!isRecord(value)) return null;
    const issues = typeof value.issueCount === 'number' ? value.issueCount : Number(value.issueCount || 0);
    const messages = typeof value.messageCount === 'number' ? value.messageCount : Number(value.messageCount || 0);
    if (!Number.isFinite(issues) && !Number.isFinite(messages)) return null;
    if (issues <= 0 && messages <= 0) return null;
    return {
        issues: Number.isFinite(issues) ? issues : 0,
        messages: Number.isFinite(messages) ? messages : 0,
    };
}

function agentAnswerAccountContext(answer: SupportAgentAnswer | null): Record<string, unknown> | null {
    return isRecord(answer?.accountContext) ? answer.accountContext : null;
}

function agentRunAccountContext(run: SupportAiRun): Record<string, unknown> | null {
    return isRecord(run.metadata.accountContext) ? run.metadata.accountContext : null;
}

function agentAnswerConversationContext(answer: SupportAgentAnswer | null): Record<string, unknown> | null {
    return isRecord(answer?.conversationContext) ? answer.conversationContext : null;
}

function agentRunConversationContext(run: SupportAiRun): Record<string, unknown> | null {
    return isRecord(run.metadata.conversationContext) ? run.metadata.conversationContext : null;
}

function generationModeLabel(value: string | undefined): string {
    if (!value) return '';
    if (value === 'llm') return 'LLM';
    if (value === 'knowledge_agent') return 'Knowledge agent';
    if (value === 'deterministic_fallback') return 'Fallback';
    return value;
}

function agentMessageRoleLabel(role: string): string {
    if (role === 'assistant') return 'Agent';
    if (role === 'user') return 'You';
    return role || 'Message';
}

function AgentMessageTranscript({ messages, compact, t }: { messages: SupportAgentMessage[]; compact: boolean; t: TranslateFn }) {
    if (messages.length === 0) return null;
    const visibleMessages = messages.slice(compact ? -6 : -12);
    return (
        <div className="space-y-2" data-ticket-agent-chat data-ticket-agent-chat-count={messages.length}>
            <div className="flex items-center justify-between gap-2 text-xs font-medium uppercase text-muted-foreground">
                <span className="flex items-center gap-1.5">
                    <MessageSquare className="size-3.5" />
                    {t('Agent chat')}
                </span>
                <Badge variant="outline" className="font-normal">{messages.length}</Badge>
            </div>
            <div className={`${compact ? 'max-h-64' : 'max-h-96'} space-y-2 overflow-auto pr-1`}>
                {visibleMessages.map(message => {
                    const role = textFrom(message.role).toLowerCase();
                    const assistant = role === 'assistant';
                    const metadata = isRecord(message.metadata) ? message.metadata : {};
                    const confidence = textFrom(metadata.confidence);
                    return (
                        <div
                            key={message.id}
                            className={`rounded-md border p-2 text-sm ${assistant ? 'bg-muted/20' : 'bg-background'}`}
                            data-ticket-agent-chat-message={message.id}
                            data-ticket-agent-chat-role={role}
                        >
                            <div className="mb-1 flex min-w-0 items-center justify-between gap-2">
                                <div className="min-w-0 truncate text-xs font-medium">
                                    {t(agentMessageRoleLabel(role))}
                                    {message.authorEmail ? <span className="font-normal text-muted-foreground"> · {message.authorEmail}</span> : null}
                                </div>
                                <div className="flex shrink-0 items-center gap-1.5">
                                    {confidence && (
                                        <Badge variant="outline" className="font-normal">
                                            {confidence}
                                        </Badge>
                                    )}
                                    {message.replyId && (
                                        <Badge variant="secondary" className="font-normal">
                                            {t('Draft')}
                                        </Badge>
                                    )}
                                    <span className="text-[11px] text-muted-foreground">
                                        {formatTime(message.occurredAt || message.created)}
                                    </span>
                                </div>
                            </div>
                            <div className="whitespace-pre-wrap text-muted-foreground">
                                {message.body}
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

function AgentCitationCards({ citations, compact = false, t }: { citations: AgentCitationPreview[]; compact?: boolean; t: TranslateFn }) {
    if (citations.length === 0) return null;
    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between gap-2 text-xs font-medium uppercase text-muted-foreground">
                <span>{t('Knowledge sources')}</span>
                <Badge variant="outline" className="font-normal">{citations.length}</Badge>
            </div>
            <div className="grid gap-2">
                {citations.slice(0, compact ? 2 : 4).map(citation => (
                    <div key={citation.id || citation.title} className="rounded-md border bg-background p-2 text-sm">
                        <div className="mb-1 flex min-w-0 items-center justify-between gap-2">
                            <span className="min-w-0 truncate font-medium">{citation.title}</span>
                            <div className="flex shrink-0 items-center gap-1.5">
                                {knowledgeSourceUrl(citation) && (
                                    <Button type="button" size="icon-xs" variant="ghost" asChild title={t('Open source')}>
                                        <a href={knowledgeSourceUrl(citation)} target="_blank" rel="noreferrer" aria-label={t('Open source')}>
                                            <ExternalLink className="size-3" />
                                        </a>
                                    </Button>
                                )}
                                {typeof citation.score === 'number' && (
                                    <Badge variant="secondary" className="font-normal">
                                        {Math.round(citation.score * 100)}%
                                    </Badge>
                                )}
                            </div>
                        </div>
                        {citation.body && (
                            <div className={`${compact ? 'line-clamp-1' : 'line-clamp-2'} text-xs text-muted-foreground`}>
                                {citation.body}
                            </div>
                        )}
                        {citation.evidence.length > 0 && !compact && (
                            <div className="mt-2 space-y-1 rounded-md border bg-muted/20 p-2 text-[11px] text-muted-foreground" data-agent-citation-evidence={citation.id}>
                                {citation.evidence.map(item => (
                                    <div key={`${citation.id}:${item.path}`} className="min-w-0">
                                        <div className="truncate font-mono" title={item.path}>{item.path}</div>
                                        <div className="truncate font-mono" title={item.contentSha256}>
                                            {item.chunkCount > 1 ? `${t('Chunk')} ${item.chunkIndex}/${item.chunkCount} · ` : ''}
                                            sha256:{item.contentSha256.slice(0, 12)}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                        {(citation.status || citation.visibility || citation.reviewStatus || citation.freshnessStatus || citation.needsReview || citation.tags.length > 0) && (
                            <div className="mt-2 flex flex-wrap gap-1.5">
                                {citation.status && (
                                    <Badge variant="outline" className="font-normal">
                                        {citation.status}
                                    </Badge>
                                )}
                                {(citation.visibility || citation.public) && (
                                    <Badge variant={citation.public ? 'secondary' : 'outline'} className="font-normal">
                                        {t(knowledgeVisibilityLabel(citation.visibility, citation.public))}
                                    </Badge>
                                )}
                                {(citation.needsReview
                                    || (citation.reviewStatus && citation.reviewStatus !== 'reviewed')
                                    || (citation.freshnessStatus && citation.freshnessStatus !== 'fresh')) && (
                                    <Badge variant="destructive" className="font-normal">
                                        {t('Needs review')}
                                    </Badge>
                                )}
                                {citation.reviewStatus && (
                                    <Badge variant={citation.reviewStatus === 'reviewed' ? 'secondary' : 'outline'} className="font-normal">
                                        {t('Review')}: {citation.reviewStatus.split('_').join(' ')}
                                    </Badge>
                                )}
                                {citation.freshnessStatus && (
                                    <Badge variant={citation.freshnessStatus === 'fresh' ? 'secondary' : 'outline'} className="font-normal">
                                        {t('Freshness')}: {citation.freshnessStatus.split('_').join(' ')}
                                    </Badge>
                                )}
                                {citation.tags.slice(0, 3).map(tag => (
                                    <Badge key={`${citation.id || citation.title}:${tag}`} variant="outline" className="font-normal">
                                        {tag}
                                    </Badge>
                                ))}
                            </div>
                        )}
                    </div>
                ))}
            </div>
        </div>
    );
}

function AgentMissingInformation({ items, t }: { items: string[]; t: TranslateFn }) {
    if (items.length === 0) return null;
    return (
        <div
            className="rounded-md border border-amber-500/40 bg-amber-500/5 p-2.5"
            data-ticket-agent-missing-information
            role="status"
            aria-live="polite"
            aria-atomic="true"
        >
            <div className="mb-1 text-xs font-medium uppercase text-muted-foreground">
                {t('Missing information')}
            </div>
            <ul className="list-disc space-y-1 pl-4 text-sm text-muted-foreground">
                {items.map(item => <li key={item}>{item}</li>)}
            </ul>
        </div>
    );
}

function AgentGroundingWarning({
    verified,
    issues,
    error,
    gate,
    t,
}: {
    verified: unknown;
    issues: unknown;
    error: unknown;
    gate: unknown;
    t: TranslateFn;
}) {
    const gateRecord = isRecord(gate) ? gate : {};
    const status = textFrom(gateRecord.status);
    const reason = textFrom(gateRecord.reasonCode ?? gateRecord.reason_code);
    const details = textListFrom([
        ...textListFrom(issues),
        ...textListFrom(gateRecord.unsupportedClaims ?? gateRecord.unsupported_claims),
        ...textListFrom(gateRecord.contradictions),
    ]);
    const cleanError = textFrom(error) || textFrom(gateRecord.error);
    const passed = verified === true && status === 'passed';
    if (passed || (!status && !reason && details.length === 0 && !cleanError)) return null;
    return (
        <div
            className="rounded-md border border-destructive/40 bg-destructive/5 p-2.5"
            data-ticket-agent-grounding-warning
            role="alert"
        >
            <div className="flex items-center gap-2 text-sm font-medium text-destructive">
                <TriangleAlert className="size-4 shrink-0" />
                {t('Automatic send blocked')}
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
                {reason ? reason.split('_').join(' ') : t('Answer needs grounding review before sending.')}
            </div>
            {details.length > 0 && (
                <ul className="mt-2 list-disc space-y-1 pl-4 text-sm text-muted-foreground">
                    {details.map(item => <li key={item}>{item}</li>)}
                </ul>
            )}
            {cleanError && <div className="mt-2 text-xs text-muted-foreground">{cleanError}</div>}
        </div>
    );
}

function AgentAnswerCard({
    answer,
    issue,
    compact,
    creatingKnowledgeArticle,
    t,
    renderKnowledgeGap,
    onCreateKnowledgeArticle,
    onApplyAnswerToReply,
}: Pick<InboxAgentPanelProps, 'answer' | 'issue' | 'creatingKnowledgeArticle' | 't' | 'renderKnowledgeGap' | 'onCreateKnowledgeArticle' | 'onApplyAnswerToReply'> & { compact: boolean }) {
    if (!answer) return null;
    const citations = agentAnswerCitationPreviews(answer);
    const context = agentAnswerAccountContext(answer);
    const status = agentAccountContextStatus(context);
    const signalCount = agentAccountContextOpenSignals(context);
    const conversationCounts = agentConversationContextCounts(agentAnswerConversationContext(answer));
    const missingInformation = textListFrom(answer.missingInformation);
    const researchStepCount = answer.knowledgeToolCalls?.length ?? 0;
    return (
        <div className={`${compact ? 'mt-3' : ''} space-y-3 rounded-md border bg-muted/20 p-3`}>
            {citations.length > 0 && <AgentCitationCards citations={citations} compact={compact} t={t} />}
            <div className="flex flex-wrap gap-2">
                {(answer.priorAgentRunIds?.length ?? 0) > 0 && (
                    <Badge variant="outline" className="w-fit font-normal">
                        {t('Context used')}: {answer.priorAgentRunIds?.length}
                    </Badge>
                )}
                {context && (
                    <Badge variant="secondary" className="w-fit font-normal" data-agent-account-context>
                        {t('Account context')}: {status || t('used')}{signalCount > 0 ? ` · ${signalCount} ${t('signals')}` : ''}
                    </Badge>
                )}
                {conversationCounts && (
                    <Badge
                        variant="outline"
                        className="w-fit font-normal"
                        data-agent-conversation-context
                        data-agent-conversation-issues={conversationCounts.issues}
                        data-agent-conversation-messages={conversationCounts.messages}
                    >
                        {t('Conversation context')}: {conversationCounts.issues} {t('tickets')} · {conversationCounts.messages} {t('messages')}
                    </Badge>
                )}
                {researchStepCount > 0 && (
                    <Badge variant="outline" className="w-fit font-normal" data-agent-knowledge-tool-count={researchStepCount}>
                        {t('Research steps')}: {researchStepCount}
                    </Badge>
                )}
            </div>
            <AgentGroundingWarning
                verified={answer.groundingVerified}
                issues={answer.groundingIssues}
                error={answer.groundingError}
                gate={answer.groundingGate}
                t={t}
            />
            <AgentMissingInformation items={missingInformation} t={t} />
            <pre className={`${compact ? 'max-h-44' : 'max-h-72'} overflow-auto whitespace-pre-wrap text-sm leading-6 text-muted-foreground`}>
                {answer.answer}
            </pre>
            <div className="text-xs text-muted-foreground">
                {answer.reply ? t('Approval draft ready.') : t('Answer saved to agent chat.')}
            </div>
            {answer.knowledgeGap && renderKnowledgeGap(answer.knowledgeGap, compact)}
            <div className="flex flex-wrap justify-end gap-2">
                <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => void onCreateKnowledgeArticle({
                        key: 'agent-current',
                        title: issue.subject ? `Agent answer: ${issue.subject}` : t('Agent answer'),
                        answer: answer.answer,
                        tags: ['agent-answer'],
                    })}
                    disabled={Boolean(creatingKnowledgeArticle)}
                >
                    {creatingKnowledgeArticle === 'agent-current'
                        ? <Loader className="size-3.5 animate-spin" />
                        : <BookOpen className="size-3.5" />}
                    {t('Save article')}
                </Button>
                <Button type="button" size="sm" variant="outline" onClick={() => onApplyAnswerToReply('append')}>
                    <Plus className="size-3.5" />
                    {t(compact ? 'Append' : 'Append to reply')}
                </Button>
                <Button type="button" size="sm" onClick={() => onApplyAnswerToReply('replace')}>
                    <Copy className="size-3.5" />
                    {t(compact ? 'Use as reply' : 'Use as reply')}
                </Button>
            </div>
            {answer.generationError && (
                <div className="rounded-md border bg-background p-2 text-xs text-muted-foreground">
                    {answer.generationError}
                </div>
            )}
        </div>
    );
}

function AgentRunCard({
    run,
    issue,
    compact,
    creatingKnowledgeArticle,
    t,
    onCreateKnowledgeArticle,
    onStartFollowUp,
    onApplyRunToReply,
}: Pick<InboxAgentPanelProps, 'issue' | 'creatingKnowledgeArticle' | 't' | 'onCreateKnowledgeArticle' | 'onStartFollowUp' | 'onApplyRunToReply'> & { run: SupportAiRun; compact: boolean }) {
    const runCitations = agentRunCitationPreviews(run);
    const context = agentRunAccountContext(run);
    const status = agentAccountContextStatus(context);
    const signalCount = agentAccountContextOpenSignals(context);
    const conversationCounts = agentConversationContextCounts(agentRunConversationContext(run));
    const missingInformation = textListFrom(run.metadata.missingInformation ?? run.metadata.missing_information);
    const knowledgeToolCalls = agentRunKnowledgeToolCalls(run);
    const generationError = textFrom(run.metadata.generationError ?? run.metadata.generation_error);
    const groundingGate = run.metadata.groundingGate ?? run.metadata.grounding_gate;
    const groundingVerified = run.metadata.groundingVerified ?? run.metadata.grounding_verified;
    const groundingIssues = run.metadata.groundingIssues ?? run.metadata.grounding_issues;
    const groundingError = run.metadata.groundingError ?? run.metadata.grounding_error;
    return (
        <div className="rounded-md border bg-muted/20 p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
                <div className="min-w-0 truncate text-xs text-muted-foreground">
                    {compact ? agentRunQuestion(run) || formatTime(run.completedAt || run.created) : formatTime(run.completedAt || run.created)}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                    {!compact && agentRunPriorCount(run) > 0 && (
                        <Badge variant="outline" className="font-normal">
                            {t('Context')}: {agentRunPriorCount(run)}
                        </Badge>
                    )}
                    {context && (
                        <Badge variant="secondary" className="font-normal" data-agent-run-account-context={run.id}>
                            {t(compact ? 'Account' : 'Account')}: {status || t('used')}{signalCount > 0 ? ` · ${signalCount}` : ''}
                        </Badge>
                    )}
                    {conversationCounts && (
                        <Badge
                            variant="outline"
                            className="font-normal"
                            data-agent-run-conversation-context={run.id}
                            data-agent-run-conversation-issues={conversationCounts.issues}
                            data-agent-run-conversation-messages={conversationCounts.messages}
                        >
                            {t(compact ? 'Conversation' : 'Conversation')}: {conversationCounts.issues} · {conversationCounts.messages}
                        </Badge>
                    )}
                    {generationModeLabel(textFrom(run.metadata.generationMode)) && (
                        <Badge variant="secondary" className="font-normal">
                            {generationModeLabel(textFrom(run.metadata.generationMode))}
                        </Badge>
                    )}
                    {knowledgeToolCalls.length > 0 && (
                        <Badge variant="outline" className="font-normal" data-agent-run-knowledge-tool-count={knowledgeToolCalls.length}>
                            {t('Research steps')}: {knowledgeToolCalls.length}
                        </Badge>
                    )}
                    <Badge variant="outline" className="font-normal">
                        {textFrom(run.metadata.confidence) || run.status}
                    </Badge>
                </div>
            </div>
            {!compact && agentRunQuestion(run) && (
                <div className="mb-2 rounded-md border bg-background p-2 text-sm">
                    {agentRunQuestion(run)}
                </div>
            )}
            <AgentGroundingWarning
                verified={groundingVerified}
                issues={groundingIssues}
                error={groundingError}
                gate={groundingGate}
                t={t}
            />
            <AgentMissingInformation items={missingInformation} t={t} />
            {generationError && (
                <div className="mb-2 rounded-md border bg-background p-2 text-xs text-muted-foreground" data-ticket-agent-generation-error>
                    {generationError}
                </div>
            )}
            <pre className={`${compact ? 'max-h-36' : 'max-h-72'} overflow-auto whitespace-pre-wrap text-sm leading-6 text-muted-foreground`}>
                {agentRunAnswer(run)}
            </pre>
            {runCitations.length > 0 && (
                <div className="mt-3">
                    <AgentCitationCards citations={runCitations} compact={compact} t={t} />
                </div>
            )}
            <div className="mt-3 flex flex-wrap justify-end gap-2">
                <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => void onCreateKnowledgeArticle({
                        key: `agent-run:${run.id}`,
                        title: agentRunQuestion(run) || issue.subject || t('Agent answer'),
                        run,
                        tags: ['agent-answer'],
                    })}
                    disabled={Boolean(creatingKnowledgeArticle)}
                >
                    {creatingKnowledgeArticle === `agent-run:${run.id}`
                        ? <Loader className="size-3.5 animate-spin" />
                        : <BookOpen className="size-3.5" />}
                    {t('Save article')}
                </Button>
                <Button type="button" size="sm" variant="outline" onClick={() => onStartFollowUp(run)}>
                    <Sparkles className="size-3.5" />
                    {t('Follow up')}
                </Button>
                <Button type="button" size="sm" variant="outline" onClick={() => onApplyRunToReply(run, 'append')}>
                    <Plus className="size-3.5" />
                    {t(compact ? 'Append' : 'Append')}
                </Button>
                <Button type="button" size="sm" variant="outline" onClick={() => onApplyRunToReply(run, 'replace')}>
                    <Copy className="size-3.5" />
                    {t('Use as reply')}
                </Button>
            </div>
        </div>
    );
}

export function InboxAgentPanel({
    variant = 'full',
    issue,
    quickActions,
    questionRef,
    question,
    onQuestionChange,
    asking,
    runningActionKey,
    answer,
    runs,
    messages,
    creatingKnowledgeArticle,
    t,
    onAsk,
    onCreateKnowledgeArticle,
    onApplyAnswerToReply,
    onApplyRunToReply,
    onStartFollowUp,
    renderKnowledgeGap,
}: InboxAgentPanelProps) {
    const compact = variant === 'compact';
    const visibleRuns = compact ? runs.slice(0, 3) : runs;
    return (
        <section className={`rounded-md border ${compact ? 'p-3' : 'p-4'}`}>
            <div className="mb-3 flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                    <Sparkles className="size-4" />
                    {t('Ask agent')}
                </div>
                {answer ? (
                    <div className="flex items-center gap-2">
                        {generationModeLabel(answer.generationMode) && (
                            <Badge variant="secondary" className="font-normal">
                                {generationModeLabel(answer.generationMode)}
                            </Badge>
                        )}
                        <Badge variant="outline" className="font-normal">
                            {answer.confidence}
                        </Badge>
                    </div>
                ) : asking ? (
                    <Loader className="size-4 animate-spin text-muted-foreground" />
                ) : null}
            </div>
            <div className="space-y-3">
                <div className={`grid gap-2 ${compact ? 'grid-cols-2' : 'sm:grid-cols-4'}`}>
                    {quickActions.map(action => (
                        <Button
                            key={action.key}
                            type="button"
                            variant={action.createDraft ? 'default' : 'outline'}
                            size="sm"
                            onClick={() => void onAsk(action.question, action.createDraft, action.key)}
                            disabled={asking}
                            data-ticket-agent-quick-action={action.key}
                        >
                            {runningActionKey === action.key
                                ? <Loader className="size-3.5 animate-spin" />
                                : <Sparkles className="size-3.5" />}
                            {t(action.label)}
                        </Button>
                    ))}
                </div>
                <Textarea
                    ref={questionRef}
                    value={question}
                    onChange={event => onQuestionChange(event.target.value)}
                    rows={3}
                    placeholder={t('Ask for an answer, next step, or customer reply')}
                />
                <div className="flex flex-wrap justify-end gap-2">
                    <Button type="button" size={compact ? 'sm' : 'default'} variant="outline" onClick={() => void onAsk(undefined, false)} disabled={asking}>
                        {asking ? <Loader className="size-4 animate-spin" /> : <Send className="size-4" />}
                        {t('Ask only')}
                    </Button>
                    <Button type="button" size={compact ? 'sm' : 'default'} onClick={() => void onAsk(undefined, true)} disabled={asking}>
                        {asking ? <Loader className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
                        {t('Prepare draft')}
                    </Button>
                </div>
                <AgentAnswerCard
                    answer={answer}
                    issue={issue}
                    compact={compact}
                    creatingKnowledgeArticle={creatingKnowledgeArticle}
                    t={t}
                    renderKnowledgeGap={renderKnowledgeGap}
                    onCreateKnowledgeArticle={onCreateKnowledgeArticle}
                    onApplyAnswerToReply={onApplyAnswerToReply}
                />
                <AgentMessageTranscript messages={messages} compact={compact} t={t} />
            </div>
            {visibleRuns.length > 0 && (
                <div className={compact ? 'mt-3 space-y-2' : 'mt-5 space-y-3'}>
                    <div className="flex items-center justify-between gap-3">
                        <div className={`${compact ? 'text-xs font-medium uppercase text-muted-foreground' : 'flex items-center gap-2 text-sm font-medium'}`}>
                            {!compact && <Sparkles className="size-4" />}
                            {t('Answer history')}
                        </div>
                        <Badge variant="outline" className="font-normal">
                            {runs.length}
                        </Badge>
                    </div>
                    <div className="space-y-3">
                        {visibleRuns.map(run => (
                            <AgentRunCard
                                key={run.id}
                                run={run}
                                issue={issue}
                                compact={compact}
                                creatingKnowledgeArticle={creatingKnowledgeArticle}
                                t={t}
                                onCreateKnowledgeArticle={onCreateKnowledgeArticle}
                                onStartFollowUp={onStartFollowUp}
                                onApplyRunToReply={onApplyRunToReply}
                            />
                        ))}
                    </div>
                </div>
            )}
        </section>
    );
}
