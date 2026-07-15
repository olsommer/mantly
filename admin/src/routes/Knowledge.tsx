import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, BookOpen, CheckCircle2, Copy, ExternalLink, Globe2, History, Loader, Plus, Search, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';

import { api } from '@/api/endpoints';
import type { KnowledgeArticle, KnowledgeArticleRevision, KnowledgeGap } from '@/api/endpoints';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { UserRole } from '@/components/app-sidebar';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useI18n } from '@/lib/i18n-context';
import { settings } from '@/settings';

interface KnowledgeProps {
    projectId: string;
    userRole: UserRole;
}

function articleSearchText(article: KnowledgeArticle) {
    return [article.title, article.body, article.status, article.visibility, article.sourceUrl, article.tags.join(' ')].join(' ').toLowerCase();
}

function gapVariant(severity: string): 'destructive' | 'secondary' | 'outline' {
    if (severity === 'high' || severity === 'urgent') return 'destructive';
    if (severity === 'normal') return 'secondary';
    return 'outline';
}

function publicKnowledgeUrl(projectId: string) {
    return `${settings.apiBaseUrl.replace(/\/+$/, '')}/support/knowledge/${encodeURIComponent(projectId)}`;
}

function publicKnowledgeApiUrl(projectId: string) {
    return `${settings.apiBaseUrl.replace(/\/+$/, '')}/api/support/knowledge/${encodeURIComponent(projectId)}/articles`;
}

function articleIsPublishedPublic(article: KnowledgeArticle) {
    return article.status === 'published' && (article.public || article.visibility === 'public');
}

function articleHasSource(article: KnowledgeArticle) {
    const sourceGapId = typeof article.metadata?.sourceGapId === 'string'
        ? article.metadata.sourceGapId
        : typeof article.metadata?.source_gap_id === 'string' ? article.metadata.source_gap_id : '';
    return Boolean(article.sourceUrl?.trim() || article.sourceIssueId?.trim() || sourceGapId.trim());
}

function articleRevisions(article: KnowledgeArticle | null): KnowledgeArticleRevision[] {
    return [...(article?.revisions ?? [])]
        .sort((a, b) => (b.revision || 0) - (a.revision || 0))
        .slice(0, 5);
}

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

function articleReviewStatus(article: KnowledgeArticle) {
    return article.reviewStatus || (article.status === 'published' ? 'needs_review' : 'draft');
}

function articleReviewLabel(status: string) {
    if (status === 'needs_review') return 'Needs review';
    if (status === 'reviewed') return 'Reviewed';
    if (status === 'stale') return 'Stale';
    if (status === 'draft') return 'Draft';
    return status || 'Needs review';
}

function articleReviewVariant(status: string): 'destructive' | 'secondary' | 'outline' {
    if (status === 'stale' || status === 'needs_review') return 'destructive';
    if (status === 'reviewed') return 'secondary';
    return 'outline';
}

function articleNeedsReview(article: KnowledgeArticle) {
    const status = articleReviewStatus(article);
    return article.needsReview || status === 'needs_review' || status === 'stale';
}

function revisionActionLabel(action: string) {
    return action.replace(/_/g, ' ') || 'updated';
}

function EmptyState({ label }: { label: string }) {
    return (
        <div className="flex h-full min-h-64 flex-col items-center justify-center text-center text-muted-foreground">
            <BookOpen className="mb-3 size-9" />
            <div className="text-sm">{label}</div>
        </div>
    );
}

export function Knowledge({ projectId, userRole }: KnowledgeProps) {
    const { tenantId, articleId } = useParams<{ tenantId: string; articleId?: string }>();
    const navigate = useNavigate();
    const { t } = useI18n();
    const [articles, setArticles] = useState<KnowledgeArticle[]>([]);
    const [gaps, setGaps] = useState<KnowledgeGap[]>([]);
    const [selectedArticle, setSelectedArticle] = useState<KnowledgeArticle | null>(null);
    const [query, setQuery] = useState('');
    const [statusFilter, setStatusFilter] = useState('all');
    const [loadingList, setLoadingList] = useState(false);
    const [loadingDetail, setLoadingDetail] = useState(false);
    const [saving, setSaving] = useState(false);
    const [reviewingArticle, setReviewingArticle] = useState(false);
    const [title, setTitle] = useState('');
    const [body, setBody] = useState('');
    const [status, setStatus] = useState('draft');
    const [tags, setTags] = useState('');
    const [sourceIssueId, setSourceIssueId] = useState('');
    const [sourceUrl, setSourceUrl] = useState('');
    const [visibility, setVisibility] = useState('public');
    const [automationAllowed, setAutomationAllowed] = useState(true);
    const [savingGapId, setSavingGapId] = useState('');
    const [creatingArticleFromGapId, setCreatingArticleFromGapId] = useState('');
    const canManagePrivate = userRole === 'root' || userRole === 'admin';

    const basePath = tenantId ? `/${tenantId}/${projectId}/knowledge` : '';

    const loadArticles = useCallback(() => {
        setLoadingList(true);
        void api.getKnowledgeArticles(projectId, statusFilter).then((res) => {
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not load knowledge'));
                return;
            }
            setArticles(res.data.items);
        }).finally(() => setLoadingList(false));
    }, [projectId, statusFilter, t]);

    const loadGaps = useCallback(() => {
        void api.getKnowledgeGaps(projectId, 'open').then((res) => {
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not load knowledge gaps'));
                return;
            }
            setGaps(res.data.items);
        });
    }, [projectId, t]);

    useEffect(() => {
        const timer = window.setTimeout(() => loadArticles(), 0);
        return () => window.clearTimeout(timer);
    }, [loadArticles]);

    useEffect(() => {
        const timer = window.setTimeout(() => loadGaps(), 0);
        return () => window.clearTimeout(timer);
    }, [loadGaps]);

    useEffect(() => {
        if (!articleId) {
            const resetTimer = window.setTimeout(() => {
                setSelectedArticle(null);
                setTitle('');
                setBody('');
                setStatus('draft');
                setTags('');
                setSourceIssueId('');
                setSourceUrl('');
                setVisibility('public');
                setAutomationAllowed(true);
                setLoadingDetail(false);
            }, 0);
            return () => window.clearTimeout(resetTimer);
        }

        let cancelled = false;
        const loadTimer = window.setTimeout(() => {
            setLoadingDetail(true);
            void api.getKnowledgeArticle(projectId, articleId).then((res) => {
                if (cancelled) return;
                if (res.error || !res.data) {
                    toast.error(res.error || t('Could not load article'));
                    return;
                }
                setSelectedArticle(res.data);
                setTitle(res.data.title);
                setBody(res.data.body);
                setStatus(res.data.status || 'draft');
                setTags(res.data.tags.join(', '));
                setSourceIssueId(res.data.sourceIssueId || '');
                setSourceUrl(res.data.sourceUrl || '');
                setVisibility(res.data.visibility || 'public');
                setAutomationAllowed(res.data.automationAllowed === true);
            }).finally(() => {
                if (!cancelled) setLoadingDetail(false);
            });
        }, 0);

        return () => {
            cancelled = true;
            window.clearTimeout(loadTimer);
        };
    }, [articleId, projectId, t]);

    const filteredArticles = useMemo(() => {
        const needle = query.trim().toLowerCase();
        if (!needle) return articles;
        return articles.filter(article => articleSearchText(article).includes(needle));
    }, [articles, query]);
    const publicArticles = useMemo(() => articles.filter(articleIsPublishedPublic), [articles]);
    const internalArticles = useMemo(
        () => articles.filter(article => article.visibility === 'internal' || article.visibility === 'private' || article.public === false),
        [articles],
    );
    const sourceLinkedArticles = useMemo(() => articles.filter(articleHasSource), [articles]);
    const reviewQueueArticles = useMemo(() => articles.filter(articleNeedsReview), [articles]);
    const staleArticles = useMemo(() => articles.filter(article => articleReviewStatus(article) === 'stale'), [articles]);
    const selectedArticleRevisions = useMemo(() => articleRevisions(selectedArticle), [selectedArticle]);
    const nextGap = useMemo(() => {
        const severityRank = (severity: string) => {
            if (severity === 'urgent') return 4;
            if (severity === 'high') return 3;
            if (severity === 'normal') return 2;
            return 1;
        };
        return [...gaps].sort((a, b) => severityRank(b.severity) - severityRank(a.severity))[0] ?? null;
    }, [gaps]);
    const helpCenterUrl = publicKnowledgeUrl(projectId);
    const helpCenterApiUrl = publicKnowledgeApiUrl(projectId);

    const saveArticle = async (overrides: Partial<Pick<KnowledgeArticle, 'status' | 'visibility' | 'public'>> = {}) => {
        setSaving(true);
        const parsedTags = tags.split(',').map(tag => tag.trim()).filter(Boolean);
        const nextStatus = overrides.status ?? status;
        const nextVisibility = overrides.visibility ?? visibility;
        const res = selectedArticle
            ? await api.updateKnowledgeArticle(projectId, selectedArticle.id, {
                title,
                body,
                status: nextStatus,
                tags: parsedTags,
                sourceIssueId: sourceIssueId.trim(),
                sourceUrl: sourceUrl.trim(),
                visibility: nextVisibility,
                public: overrides.public,
                automationAllowed,
            })
            : await api.createKnowledgeArticle(projectId, {
                title,
                body,
                status: nextStatus,
                tags: parsedTags,
                sourceIssueId: sourceIssueId || undefined,
                sourceUrl: sourceUrl.trim() || undefined,
                visibility: nextVisibility,
                automationAllowed,
            });
        setSaving(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not save article'));
            return;
        }
        setSelectedArticle(res.data);
        setStatus(res.data.status || nextStatus);
        setVisibility(res.data.visibility || nextVisibility);
        setAutomationAllowed(res.data.automationAllowed === true);
        setSourceIssueId(res.data.sourceIssueId || sourceIssueId.trim());
        setSourceUrl(res.data.sourceUrl || sourceUrl.trim());
        setTags(res.data.tags.join(', '));
        toast.success(t('Saved'));
        loadArticles();
        loadGaps();
        if (!selectedArticle && basePath) {
            void navigate(`${basePath}/${res.data.id}`, { replace: true });
        }
    };

    const draftFromGap = (gap: KnowledgeGap) => {
        if (basePath) void navigate(basePath);
        setSelectedArticle(null);
        setTitle(gap.suggestedArticleTitle || gap.title.replace(/^Knowledge gap:\s*/i, ''));
        setBody(gap.evidence || gap.title);
        setStatus('draft');
        setTags('support-gap');
        setSourceIssueId(gap.issueId);
        setSourceUrl('');
        setVisibility('internal');
        setAutomationAllowed(false);
    };

    const copyValue = async (value: string) => {
        try {
            await navigator.clipboard.writeText(value);
            toast.success(t('Copied'));
        } catch {
            toast.error(t('Could not copy'));
        }
    };

    const openTicket = (issueId: string) => {
        if (!tenantId || !issueId) return;
        void navigate(`/${tenantId}/${projectId}/inbox/${issueId}`);
    };

    const updateGapStatus = async (gap: KnowledgeGap, nextStatus: string) => {
        setSavingGapId(gap.id);
        const res = await api.updateKnowledgeGap(projectId, gap.id, { status: nextStatus });
        setSavingGapId('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not update knowledge gap'));
            return;
        }
        setGaps(prev => prev.filter(item => item.id !== res.data?.id));
    };

    const createArticleFromGap = async (gap: KnowledgeGap) => {
        setCreatingArticleFromGapId(gap.id);
        const res = await api.createArticleFromKnowledgeGap(projectId, gap.id, 'draft');
        setCreatingArticleFromGapId('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not create article'));
            return;
        }
        toast.success(t('Draft article created'));
        setGaps(prev => prev.filter(item => item.id !== gap.id));
        loadArticles();
        if (basePath) {
            void navigate(`${basePath}/${res.data.id}`);
        }
    };

    const markArticleReviewed = async () => {
        if (!selectedArticle || reviewingArticle) return;
        setReviewingArticle(true);
        const res = await api.updateKnowledgeArticle(projectId, selectedArticle.id, { reviewStatus: 'reviewed' });
        setReviewingArticle(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not mark reviewed'));
            return;
        }
        setSelectedArticle(res.data);
        const reviewedArticle = res.data;
        setArticles(prev => prev.map(article => article.id === reviewedArticle.id ? reviewedArticle : article));
        toast.success(t('Article reviewed'));
    };

    return (
        <div className="flex min-h-0 flex-1 overflow-hidden rounded-md border bg-background">
            <aside className="flex w-[24rem] shrink-0 flex-col border-r">
                <div className="space-y-3 border-b p-4">
                    <div className="flex items-center justify-between gap-3">
                        <div>
                            <h2 className="text-base font-semibold">{t('Knowledge')}</h2>
                            <p className="text-xs text-muted-foreground">{articles.length} {t('articles')}</p>
                        </div>
                        <Button size="sm" variant="outline" onClick={() => basePath && navigate(basePath)}>
                            <Plus className="size-4" />
                            {t('New')}
                        </Button>
                    </div>
                    <div className="flex gap-2">
                        <div className="relative flex-1">
                            <Search className="pointer-events-none absolute left-2 top-2.5 size-3.5 text-muted-foreground" />
                            <Input
                                value={query}
                                onChange={event => setQuery(event.target.value)}
                                placeholder={t('Search')}
                                className="h-9 pl-7"
                            />
                        </div>
                        <Select value={statusFilter} onValueChange={setStatusFilter}>
                            <SelectTrigger className="h-9 w-32">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="all">{t('All')}</SelectItem>
                                <SelectItem value="draft">{t('Draft')}</SelectItem>
                                <SelectItem value="published">{t('Published')}</SelectItem>
                            </SelectContent>
                        </Select>
                    </div>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto">
                    {loadingList ? (
                        <EmptyState label={t('Loading')} />
                    ) : filteredArticles.length === 0 ? (
                        <EmptyState label={t('No articles')} />
                    ) : (
                        filteredArticles.map(article => (
                            <button
                                key={article.id}
                                type="button"
                                data-knowledge-article={article.id}
                                className={[
                                    'w-full border-b px-4 py-3 text-left transition-colors',
                                    article.id === articleId ? 'bg-muted/60' : 'bg-background hover:bg-muted/40',
                                ].join(' ')}
                                onClick={() => basePath && navigate(`${basePath}/${article.id}`)}
                            >
                                <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
                                    <span className="truncate text-sm font-medium">{article.title}</span>
                                    <Badge variant="outline" className="font-normal">{article.status}</Badge>
                                </div>
                                <div className="line-clamp-2 text-xs text-muted-foreground">{article.body}</div>
                                <div className="mt-2 flex flex-wrap gap-1.5">
                                    <Badge variant={article.public ? 'secondary' : 'outline'} className="font-normal">
                                        {article.visibility || (article.public ? 'public' : 'internal')}
                                    </Badge>
                                    <Badge variant={articleReviewVariant(articleReviewStatus(article))} className="font-normal">
                                        {t(articleReviewLabel(articleReviewStatus(article)))}
                                    </Badge>
                                    {article.sourceUrl && (
                                        <Badge variant="outline" className="max-w-full truncate font-normal">
                                            {article.sourceUrl}
                                        </Badge>
                                    )}
                                </div>
                            </button>
                        ))
                    )}
                </div>
            </aside>

            <section className="min-w-0 flex-1 overflow-y-auto">
                {loadingDetail ? (
                    <div className="flex h-full items-center justify-center text-muted-foreground">
                        <Loader className="mr-2 size-4 animate-spin" />
                        {t('Loading')}
                    </div>
                ) : (
                    <div className="mx-auto max-w-3xl space-y-4 px-6 py-5">
                        <section data-knowledge-operations className="rounded-md border p-4">
                            <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                                <div className="min-w-0">
                                    <div className="flex min-w-0 items-center gap-2 text-sm font-medium">
                                        <Globe2 className="size-4 text-muted-foreground" />
                                        <span className="truncate">{t('Knowledge operations')}</span>
                                    </div>
                                    <p className="mt-1 text-xs text-muted-foreground">
                                        {t('Public help center and knowledge-gap readiness for support replies.')}
                                    </p>
                                </div>
                                <Badge variant={gaps.length > 0 ? 'outline' : 'secondary'} className="font-normal">
                                    {gaps.length > 0 ? `${gaps.length} ${t('open gaps')}` : t('Ready')}
                                </Badge>
                            </div>
                            <div className="mb-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
                                <div className="rounded-md border bg-muted/20 p-2 text-xs">
                                    <div className="font-medium">{publicArticles.length}</div>
                                    <div className="text-muted-foreground">{t('public articles')}</div>
                                </div>
                                <div className="rounded-md border bg-muted/20 p-2 text-xs">
                                    <div className="font-medium">{internalArticles.length}</div>
                                    <div className="text-muted-foreground">{t('internal/private')}</div>
                                </div>
                                <div className="rounded-md border bg-muted/20 p-2 text-xs">
                                    <div className="font-medium">{sourceLinkedArticles.length}/{articles.length}</div>
                                    <div className="text-muted-foreground">{t('source linked')}</div>
                                </div>
                                <div className="rounded-md border bg-muted/20 p-2 text-xs" data-knowledge-review-queue>
                                    <div className="font-medium" data-knowledge-review-queue-count>{reviewQueueArticles.length}</div>
                                    <div className="text-muted-foreground">{t('review queue')}</div>
                                </div>
                                <div className="rounded-md border bg-muted/20 p-2 text-xs">
                                    <div className="font-medium">{gaps.length}</div>
                                    <div className="text-muted-foreground">{t('open gaps')}</div>
                                </div>
                            </div>
                            <div className="grid gap-3 lg:grid-cols-2">
                                <div data-help-center-link className="rounded-md border bg-muted/20 p-2">
                                    <div className="mb-1 text-xs font-medium">{t('Help center')}</div>
                                    <div className="flex min-w-0 items-center gap-2">
                                        <code className="min-w-0 flex-1 truncate rounded border bg-background px-2 py-1.5 text-xs">
                                            {helpCenterUrl}
                                        </code>
                                        <Button type="button" size="sm" variant="outline" onClick={() => void copyValue(helpCenterUrl)}>
                                            <Copy className="size-3.5" />
                                            {t('Copy')}
                                        </Button>
                                        <Button type="button" size="sm" variant="outline" onClick={() => window.open(helpCenterUrl, '_blank', 'noopener,noreferrer')}>
                                            <ExternalLink className="size-3.5" />
                                            {t('Open')}
                                        </Button>
                                    </div>
                                </div>
                                <div data-help-center-api-link className="rounded-md border bg-muted/20 p-2">
                                    <div className="mb-1 text-xs font-medium">{t('Articles API')}</div>
                                    <div className="flex min-w-0 items-center gap-2">
                                        <code className="min-w-0 flex-1 truncate rounded border bg-background px-2 py-1.5 text-xs">
                                            {helpCenterApiUrl}
                                        </code>
                                        <Button type="button" size="sm" variant="outline" onClick={() => void copyValue(helpCenterApiUrl)}>
                                            <Copy className="size-3.5" />
                                            {t('Copy')}
                                        </Button>
                                    </div>
                                </div>
                            </div>
                            {nextGap && (
                                <div data-next-knowledge-gap className="mt-3 rounded-md border bg-background p-2 text-sm">
                                    <div className="mb-1 flex min-w-0 items-center justify-between gap-2">
                                        <span className="min-w-0 truncate font-medium">{nextGap.suggestedArticleTitle || nextGap.title}</span>
                                        <Badge variant={gapVariant(nextGap.severity)} className="shrink-0 font-normal">
                                            {nextGap.severity}
                                        </Badge>
                                    </div>
                                    {nextGap.evidence && (
                                        <div className="line-clamp-2 text-xs text-muted-foreground">{nextGap.evidence}</div>
                                    )}
                                    <div className="mt-2 flex flex-wrap justify-end gap-2">
                                        {nextGap.issueId && tenantId && (
                                            <Button type="button" size="sm" variant="outline" onClick={() => openTicket(nextGap.issueId)}>
                                                <ExternalLink className="size-3.5" />
                                                {t('Open ticket')}
                                            </Button>
                                        )}
                                        <Button type="button" size="sm" variant="outline" data-next-knowledge-gap-draft onClick={() => draftFromGap(nextGap)}>
                                            <BookOpen className="size-3.5" />
                                            {t('Draft article')}
                                        </Button>
                                        <Button
                                            type="button"
                                            size="sm"
                                            data-next-knowledge-gap-create={nextGap.id}
                                            onClick={() => void createArticleFromGap(nextGap)}
                                            disabled={creatingArticleFromGapId === nextGap.id}
                                        >
                                            {creatingArticleFromGapId === nextGap.id
                                                ? <Loader className="size-3.5 animate-spin" />
                                                : <BookOpen className="size-3.5" />}
                                            {t('Create draft')}
                                        </Button>
                                    </div>
                                </div>
                            )}
                        </section>
                        <section className="rounded-md border p-4">
                            <div className="mb-3 flex items-center justify-between gap-3">
                                <h2 className="text-sm font-medium">{t('Knowledge gaps')}</h2>
                                <Badge variant="outline" className="font-normal">{gaps.length}</Badge>
                            </div>
                            {gaps.length === 0 ? (
                                <div className="text-sm text-muted-foreground">{t('No knowledge gaps')}</div>
                            ) : (
                                <div className="space-y-3">
                                    {gaps.map(gap => (
                                        <div key={gap.id} data-knowledge-gap={gap.id} className="rounded-md border bg-muted/20 p-3">
                                            <div className="mb-2 flex items-start justify-between gap-3">
                                                <div className="flex min-w-0 gap-2">
                                                    <AlertTriangle className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                                                    <div className="min-w-0">
                                                        <div className="truncate text-sm font-medium">{gap.title}</div>
                                                        <div className="mt-1 flex flex-wrap gap-1.5">
                                                            <Badge variant={gapVariant(gap.severity)} className="font-normal">{gap.severity}</Badge>
                                                            <Badge variant="outline" className="font-normal">{gap.status}</Badge>
                                                        </div>
                                                    </div>
                                                </div>
                                                <div className="flex shrink-0 gap-1.5">
                                                    {gap.issueId && tenantId && (
                                                        <Button
                                                            type="button"
                                                            size="sm"
                                                            variant="outline"
                                                            onClick={() => openTicket(gap.issueId)}
                                                        >
                                                            <ExternalLink className="size-4" />
                                                            {t('Open ticket')}
                                                        </Button>
                                                    )}
                                                    <Button
                                                        type="button"
                                                        size="sm"
                                                        variant="outline"
                                                        data-knowledge-gap-draft={gap.id}
                                                        onClick={() => draftFromGap(gap)}
                                                    >
                                                        {t('Draft article')}
                                                    </Button>
                                                    <Button
                                                        type="button"
                                                        size="sm"
                                                        data-knowledge-gap-create={gap.id}
                                                        onClick={() => void createArticleFromGap(gap)}
                                                        disabled={creatingArticleFromGapId === gap.id}
                                                    >
                                                        {creatingArticleFromGapId === gap.id ? <Loader className="size-4 animate-spin" /> : <BookOpen className="size-4" />}
                                                        {t('Create draft')}
                                                    </Button>
                                                    <Button
                                                        type="button"
                                                        size="sm"
                                                        variant="ghost"
                                                        onClick={() => void updateGapStatus(gap, 'ignored')}
                                                        disabled={savingGapId === gap.id}
                                                    >
                                                        {savingGapId === gap.id ? <Loader className="size-4 animate-spin" /> : t('Ignore')}
                                                    </Button>
                                                </div>
                                            </div>
                                            {gap.evidence && (
                                                <p className="line-clamp-3 text-sm leading-6 text-muted-foreground">
                                                    {gap.evidence}
                                                </p>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </section>

                        <div>
                            <h1 className="text-xl font-semibold">
                                {selectedArticle ? t('Article') : t('New article')}
                            </h1>
                            {selectedArticle && (
                                <div className="mt-1 text-xs text-muted-foreground">
                                    {t('Revision')} {selectedArticle.revision || selectedArticleRevisions[0]?.revision || 1}
                                </div>
                            )}
                        </div>
                        {selectedArticle && (
                            <section
                                data-knowledge-review-panel
                                data-knowledge-review-status={articleReviewStatus(selectedArticle)}
                                data-knowledge-freshness-status={selectedArticle.freshnessStatus || ''}
                                className="rounded-md border bg-muted/20 p-3"
                            >
                                <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
                                    <div className="flex min-w-0 items-center gap-2 text-sm font-medium">
                                        <ShieldCheck className="size-4 text-muted-foreground" />
                                        <span>{t('Article trust')}</span>
                                    </div>
                                    <div className="flex flex-wrap gap-1.5">
                                        <Badge variant={articleReviewVariant(articleReviewStatus(selectedArticle))} className="font-normal">
                                            {t(articleReviewLabel(articleReviewStatus(selectedArticle)))}
                                        </Badge>
                                        {selectedArticle.freshnessStatus && (
                                            <Badge variant={selectedArticle.freshnessStatus === 'fresh' ? 'secondary' : 'outline'} className="font-normal">
                                                {selectedArticle.freshnessStatus}
                                            </Badge>
                                        )}
                                    </div>
                                </div>
                                <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-3">
                                    <div>
                                        <div className="font-medium text-foreground">{t('Last reviewed')}</div>
                                        <div data-knowledge-last-reviewed>{formatTime(selectedArticle.lastReviewedAt)}</div>
                                    </div>
                                    <div>
                                        <div className="font-medium text-foreground">{t('Reviewed by')}</div>
                                        <div className="truncate">{selectedArticle.reviewedBy || '-'}</div>
                                    </div>
                                    <div>
                                        <div className="font-medium text-foreground">{t('Next review')}</div>
                                        <div data-knowledge-review-due>{formatTime(selectedArticle.reviewDueAt)}</div>
                                    </div>
                                </div>
                                {selectedArticle.freshnessReason && (
                                    <div className="mt-2 text-xs text-muted-foreground">{t(selectedArticle.freshnessReason)}</div>
                                )}
                                {staleArticles.length > 0 && (
                                    <div className="mt-2 flex items-center gap-1.5 text-xs text-amber-700">
                                        <AlertTriangle className="size-3.5" />
                                        {staleArticles.length} {t('stale articles need review')}
                                    </div>
                                )}
                                <div className="mt-3 flex justify-end">
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant="outline"
                                        data-knowledge-mark-reviewed
                                        onClick={() => void markArticleReviewed()}
                                        disabled={reviewingArticle}
                                    >
                                        {reviewingArticle ? <Loader className="size-3.5 animate-spin" /> : <CheckCircle2 className="size-3.5" />}
                                        {t('Mark reviewed')}
                                    </Button>
                                </div>
                            </section>
                        )}
                        <div className="space-y-1.5">
                            <Label htmlFor="article-title">{t('Title')}</Label>
                            <Input id="article-title" data-knowledge-article-title value={title} onChange={event => setTitle(event.target.value)} />
                        </div>
                        <div className="grid gap-3 sm:grid-cols-[12rem_12rem_14rem_1fr]">
                            <div className="space-y-1.5">
                                <Label>{t('Status')}</Label>
                                <Select value={status} onValueChange={setStatus}>
                                    <SelectTrigger data-knowledge-article-status>
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="draft">{t('Draft')}</SelectItem>
                                        <SelectItem value="published">{t('Published')}</SelectItem>
                                    </SelectContent>
                                </Select>
                            </div>
                            <div className="space-y-1.5">
                                <Label>{t('Visibility')}</Label>
                                <Select value={visibility} onValueChange={setVisibility}>
                                    <SelectTrigger data-knowledge-article-visibility>
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="public">{t('Public')}</SelectItem>
                                        <SelectItem value="internal">{t('Internal')}</SelectItem>
                                        {canManagePrivate && <SelectItem value="private">{t('Private')}</SelectItem>}
                                    </SelectContent>
                                </Select>
                                <div className="text-xs text-muted-foreground">
                                    {visibility === 'public'
                                        ? t('Customers, project members, and automation can use this article.')
                                        : visibility === 'private'
                                            ? t('Only project admins can use this article unless automation access is configured.')
                                            : t('Project members can use this article. Automation access is separate.')}
                                </div>
                            </div>
                            <div className="space-y-1.5">
                                <Label htmlFor="article-automation-access">{t('Automation access')}</Label>
                                <div className="flex min-h-9 items-center gap-2 rounded-md border px-3">
                                    <Switch
                                        id="article-automation-access"
                                        data-knowledge-article-automation-access
                                        checked={automationAllowed}
                                        onCheckedChange={setAutomationAllowed}
                                    />
                                    <span className="text-sm">{automationAllowed ? t('Allowed') : t('Blocked')}</span>
                                </div>
                                <div className="text-xs text-muted-foreground">
                                    {t('Allows the company automation identity to use this source. Customer-facing answers still require grounding and runbook review policy.')}
                                </div>
                            </div>
                            <div className="space-y-1.5">
                                <Label htmlFor="article-tags">{t('Tags')}</Label>
                                <Input id="article-tags" data-knowledge-article-tags value={tags} onChange={event => setTags(event.target.value)} />
                            </div>
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="article-source-url">{t('Source URL')}</Label>
                            <div className="flex gap-2">
                                <Input
                                    id="article-source-url"
                                    data-knowledge-article-source-url
                                    type="url"
                                    value={sourceUrl}
                                    onChange={event => setSourceUrl(event.target.value)}
                                    placeholder="https://docs.example.com/article"
                                />
                                <Button
                                    type="button"
                                    variant="outline"
                                    onClick={() => window.open(sourceUrl.trim(), '_blank', 'noopener,noreferrer')}
                                    disabled={!sourceUrl.trim()}
                                >
                                    <ExternalLink className="size-4" />
                                    {t('Open source')}
                                </Button>
                            </div>
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="article-source-ticket">{t('Source ticket')}</Label>
                            <div className="flex gap-2">
                                <Input
                                    id="article-source-ticket"
                                    data-knowledge-article-source-ticket
                                    value={sourceIssueId}
                                    onChange={event => setSourceIssueId(event.target.value)}
                                    placeholder={t('Issue ID')}
                                />
                                <Button
                                    type="button"
                                    variant="outline"
                                    onClick={() => openTicket(sourceIssueId.trim())}
                                    disabled={!sourceIssueId.trim() || !tenantId}
                                >
                                    <ExternalLink className="size-4" />
                                    {t('Open ticket')}
                                </Button>
                            </div>
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="article-body">{t('Body')}</Label>
                            <Textarea
                                id="article-body"
                                data-knowledge-article-body
                                value={body}
                                onChange={event => setBody(event.target.value)}
                                rows={16}
                            />
                        </div>
                        {selectedArticle && selectedArticleRevisions.length > 0 && (
                            <section data-knowledge-revisions className="rounded-md border bg-muted/20 p-3">
                                <div className="mb-2 flex items-center justify-between gap-3">
                                    <div className="flex min-w-0 items-center gap-2 text-sm font-medium">
                                        <History className="size-4 text-muted-foreground" />
                                        <span>{t('Revision history')}</span>
                                    </div>
                                    <Badge variant="outline" className="font-normal">
                                        {selectedArticle.revision || selectedArticleRevisions[0]?.revision || selectedArticleRevisions.length}
                                    </Badge>
                                </div>
                                <div className="space-y-2">
                                    {selectedArticleRevisions.map(revision => (
                                        <div
                                            key={`${revision.revision}-${revision.at}`}
                                            data-knowledge-revision={revision.revision}
                                            className="rounded-md border bg-background p-2 text-xs"
                                        >
                                            <div className="flex flex-wrap items-center justify-between gap-2">
                                                <div className="font-medium">
                                                    {t('Revision')} {revision.revision} · {t(revisionActionLabel(revision.action))}
                                                </div>
                                                <div className="text-muted-foreground">
                                                    {revision.actorEmail || 'system'}{revision.at ? ` · ${revision.at}` : ''}
                                                </div>
                                            </div>
                                            <div className="mt-1 text-muted-foreground">
                                                {(revision.changedFields ?? []).join(', ') || t('No field changes recorded')}
                                            </div>
                                            {revision.bodyPreview && (
                                                <div className="mt-1 line-clamp-2 text-muted-foreground">
                                                    {revision.bodyPreview}
                                                </div>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </section>
                        )}
                        <div className="flex flex-wrap justify-end gap-2">
                            <Button
                                type="button"
                                variant="outline"
                                data-knowledge-publish-public
                                onClick={() => void saveArticle({ status: 'published', visibility: 'public', public: true })}
                                disabled={saving || !title.trim() || !body.trim()}
                            >
                                {saving ? <Loader className="size-4 animate-spin" /> : <Globe2 className="size-4" />}
                                {t('Publish public')}
                            </Button>
                            <Button type="button" data-knowledge-save onClick={() => void saveArticle()} disabled={saving || !title.trim() || !body.trim()}>
                                {saving ? <Loader className="size-4 animate-spin" /> : null}
                                {t('Save')}
                            </Button>
                        </div>
                    </div>
                )}
            </section>
        </div>
    );
}
