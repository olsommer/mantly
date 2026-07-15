import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, Building2, CheckCircle2, Database, ExternalLink, Inbox, Lightbulb, Loader, Mail, RefreshCw, Search } from 'lucide-react';
import { toast } from 'sonner';

import { api } from '@/api/endpoints';
import type {
    SupportAccount,
    SupportAccountHealthRollup,
    SupportAccountInsight,
    SupportAccountInsightSummary,
    SupportCrmConnectorsSyncRun,
    SupportExternalObject,
    SupportExternalSyncRun,
    SupportIssue,
} from '@/api/endpoints';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { Textarea } from '@/components/ui/textarea';
import { useI18n } from '@/lib/i18n-context';

interface AccountsProps {
    projectId: string;
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

function accountLabel(account: SupportAccount) {
    return account.name || account.domain || account.accountKey || 'Unknown account';
}

function accountInboxSearch(account: SupportAccount) {
    return `?account=${encodeURIComponent(`id:${account.id}`)}`;
}

function accountSearchText(account: SupportAccount) {
    return [
        account.name,
        account.domain,
        account.accountKey,
        account.externalId,
        account.healthStatus,
    ].join(' ').toLowerCase();
}

function issueLabel(issue: SupportIssue) {
    return issue.subject || issue.sourceEmailId || issue.id;
}

const emptyInsightSummary: SupportAccountInsightSummary = {
    total: 0,
    unresolved: 0,
    risks: 0,
    openRisks: 0,
    featureRequests: 0,
    openFeatureRequests: 0,
    summaries: 0,
    lastInsightAt: '',
};

function insightIsUnresolved(insight: SupportAccountInsight) {
    return !['resolved', 'closed', 'dismissed'].includes(insight.status);
}

function accountInsightSummary(account: SupportAccount): SupportAccountInsightSummary {
    const insights = account.insights ?? [];
    if (insights.length === 0 && account.insightSummary) return account.insightSummary;
    const risks = insights.filter(insight => insight.type === 'risk');
    const featureRequests = insights.filter(insight => insight.type === 'feature_request');
    return {
        total: insights.length,
        unresolved: insights.filter(insightIsUnresolved).length,
        risks: risks.length,
        openRisks: risks.filter(insightIsUnresolved).length,
        featureRequests: featureRequests.length,
        openFeatureRequests: featureRequests.filter(insightIsUnresolved).length,
        summaries: insights.filter(insight => insight.type === 'summary').length,
        lastInsightAt: insights.map(insight => insight.lastSeenAt || insight.updated).sort().at(-1) ?? '',
    };
}

function insightVariant(severity: string): 'destructive' | 'secondary' | 'outline' {
    if (severity === 'urgent' || severity === 'high' || severity === 'at_risk') return 'destructive';
    if (severity === 'needs_attention') return 'secondary';
    return 'outline';
}

function healthVariant(status: string): 'destructive' | 'secondary' | 'outline' {
    if (status === 'at_risk' || status === 'blocked') return 'destructive';
    if (status === 'needs_attention' || status === 'active') return 'secondary';
    return 'outline';
}

function deriveAccountHealthRollup(account: SupportAccount): SupportAccountHealthRollup {
    const summary = accountInsightSummary(account);
    const insights = account.insights ?? [];
    const issues = account.issues ?? [];
    const syncRuns = account.externalSyncRuns ?? [];
    const unresolvedRisks = insights.filter(insight => insight.type === 'risk' && insightIsUnresolved(insight));
    const highRisks = unresolvedRisks.filter(insight => ['urgent', 'high', 'at_risk', 'blocked'].includes(insight.severity));
    const openIssues = issues.filter(issue => issue.status !== 'done' && issue.status !== 'closed');
    const urgentIssues = openIssues.filter(issue => issue.priority === 'urgent');
    const highPriorityIssues = openIssues.filter(issue => ['urgent', 'high'].includes(issue.priority));
    const failedExternalSyncRuns = syncRuns.filter(run => ['failed', 'partial', 'error'].includes(run.status.toLowerCase()));

    if (urgentIssues.length > 0 || highRisks.length > 0) {
        return {
            status: 'at_risk',
            reason: 'Urgent support signal or high-severity account risk is open.',
            nextAction: 'Assign an owner, confirm the customer update, and close the risk loop.',
            openIssues: openIssues.length,
            urgentIssues: urgentIssues.length,
            highPriorityIssues: highPriorityIssues.length,
            openRisks: summary.openRisks,
            openFeatureRequests: summary.openFeatureRequests,
            unresolvedSignals: summary.unresolved,
            failedExternalSyncRuns: failedExternalSyncRuns.length,
            lastSignalAt: summary.lastInsightAt,
        };
    }
    if (unresolvedRisks.length > 0 || highPriorityIssues.length > 0 || failedExternalSyncRuns.length > 0) {
        return {
            status: 'needs_attention',
            reason: 'Open risk, high-priority ticket, or CRM sync issue needs review.',
            nextAction: failedExternalSyncRuns.length > 0
                ? 'Fix CRM sync before relying on this account context.'
                : unresolvedRisks.length > 0
                    ? 'Review the open risk and decide the next customer-facing step.'
                    : 'Review the high-priority ticket and confirm customer follow-up.',
            openIssues: openIssues.length,
            urgentIssues: urgentIssues.length,
            highPriorityIssues: highPriorityIssues.length,
            openRisks: summary.openRisks,
            openFeatureRequests: summary.openFeatureRequests,
            unresolvedSignals: summary.unresolved,
            failedExternalSyncRuns: failedExternalSyncRuns.length,
            lastSignalAt: summary.lastInsightAt,
        };
    }
    if (openIssues.length > 0 || summary.openFeatureRequests > 0) {
        return {
            status: 'active',
            reason: 'Account has open support work or tracked feature demand.',
            nextAction: 'Keep ticket owner and feature-request follow-up current.',
            openIssues: openIssues.length,
            urgentIssues: urgentIssues.length,
            highPriorityIssues: highPriorityIssues.length,
            openRisks: summary.openRisks,
            openFeatureRequests: summary.openFeatureRequests,
            unresolvedSignals: summary.unresolved,
            failedExternalSyncRuns: failedExternalSyncRuns.length,
            lastSignalAt: summary.lastInsightAt,
        };
    }
    return {
        status: account.healthStatus || 'unknown',
        reason: account.healthRollup?.reason || 'No support account signals yet.',
        nextAction: account.healthRollup?.nextAction || 'Wait for first ticket, CRM record, or manual insight.',
        openIssues: openIssues.length,
        urgentIssues: urgentIssues.length,
        highPriorityIssues: highPriorityIssues.length,
        openRisks: summary.openRisks,
        openFeatureRequests: summary.openFeatureRequests,
        unresolvedSignals: summary.unresolved,
        failedExternalSyncRuns: failedExternalSyncRuns.length,
        lastSignalAt: summary.lastInsightAt,
    };
}

function accountHealthRollup(account: SupportAccount): SupportAccountHealthRollup {
    if ((account.insights?.length ?? 0) > 0 || (account.issues?.length ?? 0) > 0 || (account.externalSyncRuns?.length ?? 0) > 0) {
        return deriveAccountHealthRollup(account);
    }
    return account.healthRollup ?? deriveAccountHealthRollup(account);
}

function syncVariant(status: string): 'destructive' | 'secondary' | 'outline' {
    const normalized = status.toLowerCase();
    if (normalized === 'failed' || normalized === 'partial') return 'destructive';
    if (normalized === 'success' || normalized === 'completed') return 'secondary';
    return 'outline';
}

function providerLabel(provider: string) {
    if (provider === 'hubspot') return 'HubSpot';
    if (provider === 'salesforce') return 'Salesforce';
    if (provider === 'identity') return 'Identity';
    return provider || 'CRM';
}

function syncRunTime(run: SupportExternalSyncRun) {
    return run.completedAt || run.startedAt || run.updated || run.created || '';
}

function syncRunScore(run: SupportExternalSyncRun) {
    const value = Date.parse(syncRunTime(run));
    return Number.isNaN(value) ? 0 : value;
}

function crmProviders(objects: SupportExternalObject[], runs: SupportExternalSyncRun[]) {
    const providers = new Set<string>();
    objects.forEach(object => {
        if (object.provider) providers.add(object.provider);
    });
    runs.forEach(run => {
        if (run.provider) providers.add(run.provider);
    });
    return Array.from(providers).sort();
}

function accountCrmHealth(account: SupportAccount) {
    const externalObjects = account.externalObjects ?? [];
    const syncRuns = account.externalSyncRuns ?? [];
    const failedRuns = syncRuns.filter(run => ['failed', 'partial'].includes(run.status.toLowerCase()));
    const latestRun = syncRuns.slice().sort((a, b) => syncRunScore(b) - syncRunScore(a))[0];
    const providers = crmProviders(externalObjects, syncRuns);
    let variant: 'destructive' | 'secondary' | 'outline' = 'outline';
    let label = 'No CRM records';

    if (failedRuns.length > 0) {
        variant = 'destructive';
        label = 'CRM attention';
    } else if (externalObjects.length > 0) {
        variant = 'secondary';
        label = 'CRM linked';
    } else if (latestRun?.status) {
        variant = syncVariant(latestRun.status);
        label = `CRM ${latestRun.status}`;
    }

    return {
        externalObjects,
        syncRuns,
        failedRuns,
        latestRun,
        providers,
        variant,
        label,
    };
}

function accountOpenRiskCount(account: SupportAccount) {
    return accountInsightSummary(account).openRisks;
}

function accountOpenFeatureRequestCount(account: SupportAccount) {
    return accountInsightSummary(account).openFeatureRequests;
}

function accountFailedCrmSyncCount(account: SupportAccount) {
    const explicitFailedRuns = (account.externalSyncRuns ?? []).filter(run => ['failed', 'partial', 'error'].includes(run.status.toLowerCase())).length;
    return explicitFailedRuns || account.healthRollup?.failedExternalSyncRuns || 0;
}

function accountPriorityScore(account: SupportAccount) {
    if (typeof account.accountAction?.score === 'number') return account.accountAction.score;
    const health = accountHealthRollup(account);
    const statusScore = health.status === 'at_risk' || health.status === 'blocked'
        ? 100
        : health.status === 'needs_attention'
            ? 70
            : health.status === 'active'
                ? 30
                : 0;
    return statusScore
        + (health.urgentIssues * 20)
        + (health.highPriorityIssues * 12)
        + (accountOpenRiskCount(account) * 10)
        + (accountFailedCrmSyncCount(account) * 8)
        + (accountOpenFeatureRequestCount(account) * 3)
        + Math.min(account.issueCount, 20);
}

function accountActionDetail(account: SupportAccount) {
    return account.accountAction?.detail || accountHealthRollup(account).nextAction;
}

function topActionAccount(accounts: SupportAccount[]) {
    return accounts
        .filter(account => accountPriorityScore(account) > 0)
        .slice()
        .sort((a, b) => accountPriorityScore(b) - accountPriorityScore(a))[0] ?? null;
}

function accountActionQueue(accounts: SupportAccount[]) {
    return accounts
        .filter(account => accountPriorityScore(account) > 0)
        .slice()
        .sort((a, b) => accountPriorityScore(b) - accountPriorityScore(a))
        .slice(0, 5);
}

function InsightIcon({ type }: { type: string }) {
    if (type === 'risk') return <AlertTriangle className="size-4 text-destructive" />;
    if (type === 'feature_request') return <Lightbulb className="size-4 text-muted-foreground" />;
    return <CheckCircle2 className="size-4 text-muted-foreground" />;
}

function insightMetadataString(insight: SupportAccountInsight, key: string) {
    const value = insight.metadata?.[key];
    return typeof value === 'string' ? value.trim() : '';
}

function AccountListItem({
    account,
    active,
    onSelect,
}: {
    account: SupportAccount;
    active: boolean;
    onSelect: () => void;
}) {
    const summary = accountInsightSummary(account);
    const health = accountHealthRollup(account);
    return (
        <button
            type="button"
            onClick={onSelect}
            className={[
                'w-full border-b px-4 py-3 text-left transition-colors',
                active ? 'bg-muted/60' : 'bg-background hover:bg-muted/40',
            ].join(' ')}
        >
            <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
                <div className="min-w-0 truncate text-sm font-medium">{accountLabel(account)}</div>
                <Badge variant={healthVariant(health.status)} className="font-normal">
                    {health.status || 'unknown'}
                </Badge>
            </div>
            <div className="mb-2 line-clamp-2 text-xs text-muted-foreground">
                {health.reason}
            </div>
            <div className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
                <Building2 className="size-3.5 shrink-0" />
                <span className="truncate">{account.domain || account.accountKey || '-'}</span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge variant="outline" className="font-normal">
                    {account.issueCount} issues
                </Badge>
                {summary.openRisks > 0 && (
                    <Badge variant="destructive" className="font-normal">
                        {summary.openRisks} risks
                    </Badge>
                )}
                {summary.openFeatureRequests > 0 && (
                    <Badge variant="outline" className="font-normal">
                        {summary.openFeatureRequests} feature requests
                    </Badge>
                )}
                {summary.unresolved > 0 && (
                    <Badge variant="secondary" className="font-normal">
                        {summary.unresolved} signals
                    </Badge>
                )}
            </div>
        </button>
    );
}

function EmptyState({ label }: { label: string }) {
    return (
        <div className="flex h-full min-h-64 flex-col items-center justify-center text-center text-muted-foreground">
            <Building2 className="mb-3 size-9" />
            <div className="text-sm">{label}</div>
        </div>
    );
}

export function Accounts({ projectId }: AccountsProps) {
    const { tenantId, accountId } = useParams<{ tenantId: string; accountId?: string }>();
    const navigate = useNavigate();
    const { t } = useI18n();
    const [accounts, setAccounts] = useState<SupportAccount[]>([]);
    const [selectedAccount, setSelectedAccount] = useState<SupportAccount | null>(null);
    const [query, setQuery] = useState('');
    const [loadingList, setLoadingList] = useState(false);
    const [loadingDetail, setLoadingDetail] = useState(false);
    const [savingInsightId, setSavingInsightId] = useState('');
    const [savingNewInsight, setSavingNewInsight] = useState(false);
    const [generatingSummary, setGeneratingSummary] = useState(false);
    const [preparingActionPackage, setPreparingActionPackage] = useState(false);
    const [syncingCrm, setSyncingCrm] = useState(false);
    const [crmSyncResult, setCrmSyncResult] = useState<SupportCrmConnectorsSyncRun | null>(null);
    const [newInsightType, setNewInsightType] = useState('risk');
    const [newInsightSeverity, setNewInsightSeverity] = useState('high');
    const [newInsightTitle, setNewInsightTitle] = useState('');
    const [newInsightBody, setNewInsightBody] = useState('');

    const basePath = tenantId ? `/${tenantId}/${projectId}/accounts` : '';

    const loadAccounts = useCallback(() => {
        setLoadingList(true);
        void api.getAccounts(projectId).then((res) => {
            if (res.error || !res.data) {
                toast.error(res.error || t('Could not load accounts'));
                return;
            }
            setAccounts(res.data.items);
        }).finally(() => setLoadingList(false));
    }, [projectId, t]);

    useEffect(() => {
        const timer = window.setTimeout(() => loadAccounts(), 0);
        return () => window.clearTimeout(timer);
    }, [loadAccounts]);

    useEffect(() => {
        if (!accountId) {
            const resetTimer = window.setTimeout(() => {
                setSelectedAccount(null);
                setLoadingDetail(false);
            }, 0);
            return () => window.clearTimeout(resetTimer);
        }

        let cancelled = false;
        const loadTimer = window.setTimeout(() => {
            setLoadingDetail(true);
            void api.getAccount(projectId, accountId).then((res) => {
                if (cancelled) return;
                if (res.error || !res.data) {
                    toast.error(res.error || t('Could not load account'));
                    return;
                }
                setSelectedAccount(res.data);
            }).finally(() => {
                if (!cancelled) setLoadingDetail(false);
            });
        }, 0);

        return () => {
            cancelled = true;
            window.clearTimeout(loadTimer);
        };
    }, [accountId, projectId, t]);

    useEffect(() => {
        if (accountId || !basePath || accounts.length === 0) return;
        void navigate(`${basePath}/${accounts[0].id}`, { replace: true });
    }, [accountId, accounts, basePath, navigate]);

    const filteredAccounts = useMemo(() => {
        const needle = query.trim().toLowerCase();
        if (!needle) return accounts;
        return accounts.filter(account => accountSearchText(account).includes(needle));
    }, [accounts, query]);
    const accountOpsSummary = useMemo(() => {
        const atRiskAccounts = accounts.filter(account => {
            const health = accountHealthRollup(account);
            return health.status === 'at_risk' || health.status === 'blocked';
        });
        const needsAttentionAccounts = accounts.filter(account => accountHealthRollup(account).status === 'needs_attention');
        return {
            atRisk: atRiskAccounts.length,
            needsAttention: needsAttentionAccounts.length,
            crmAttention: accounts.filter(account => accountFailedCrmSyncCount(account) > 0).length,
            featureDemand: accounts.reduce((total, account) => total + accountOpenFeatureRequestCount(account), 0),
            topAction: topActionAccount(accounts),
        };
    }, [accounts]);
    const actionQueueAccounts = useMemo(() => accountActionQueue(accounts), [accounts]);
    const navigateAccountAction = (account: SupportAccount) => {
        if (!tenantId) return;
        const actionRoute = account.accountAction?.route;
        if (actionRoute === 'channels') {
            void navigate(`/${tenantId}/${projectId}/channels`);
            return;
        }
        if (actionRoute === 'inbox') {
            void navigate(`/${tenantId}/${projectId}/inbox${accountInboxSearch(account)}`);
            return;
        }
        if (basePath) void navigate(`${basePath}/${account.id}`);
    };

    const updateInsightStatus = async (insight: SupportAccountInsight, status: string) => {
        setSavingInsightId(insight.id);
        const res = await api.updateAccountInsight(projectId, insight.id, { status });
        setSavingInsightId('');
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not update insight'));
            return;
        }
        const updatedInsight = res.data;
        setSelectedAccount(prev => {
            if (!prev) return prev;
            const insights = (prev.insights ?? []).map(item => item.id === updatedInsight.id ? updatedInsight : item);
            const next = {
                ...prev,
                insights,
                insightSummary: accountInsightSummary({ ...prev, insights }),
            };
            const healthRollup = accountHealthRollup(next);
            return { ...next, healthRollup, healthStatus: healthRollup.status };
        });
        loadAccounts();
    };

    const applyInsightTemplate = (type: string) => {
        setNewInsightType(type);
        if (type === 'risk') {
            setNewInsightSeverity('high');
            setNewInsightTitle(t('Risk needs attention'));
            setNewInsightBody(t('Customer signal needs owner review and follow-up.'));
            return;
        }
        if (type === 'feature_request') {
            setNewInsightSeverity('info');
            setNewInsightTitle(t('Feature request'));
            setNewInsightBody(t('Customer asked for product capability. Track demand and follow up when planned.'));
            return;
        }
        setNewInsightSeverity('info');
        setNewInsightTitle(t('Account summary'));
        setNewInsightBody(t('Current account context, open needs, and next best action.'));
    };

    const createInsight = async () => {
        if (!selectedAccount) return;
        const title = newInsightTitle.trim();
        if (!title) {
            toast.error(t('Title required'));
            return;
        }
        setSavingNewInsight(true);
        const res = await api.createAccountInsight(projectId, selectedAccount.id, {
            type: newInsightType,
            title,
            body: newInsightBody,
            severity: newInsightSeverity,
            status: newInsightType === 'summary' ? 'active' : 'open',
        });
        setSavingNewInsight(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not create insight'));
            return;
        }
        const createdInsight = res.data;
        setSelectedAccount(prev => {
            if (!prev) return prev;
            const insights = [createdInsight, ...(prev.insights ?? []).filter(item => item.id !== createdInsight.id)];
            const next = {
                ...prev,
                insights,
                insightSummary: accountInsightSummary({ ...prev, insights }),
            };
            const healthRollup = accountHealthRollup(next);
            return { ...next, healthRollup, healthStatus: healthRollup.status };
        });
        setNewInsightTitle('');
        setNewInsightBody('');
        toast.success(t('Insight added'));
        loadAccounts();
    };

    const generateSummary = async () => {
        if (!selectedAccount) return;
        setGeneratingSummary(true);
        const res = await api.generateAccountSummary(projectId, selectedAccount.id);
        setGeneratingSummary(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not generate summary'));
            return;
        }
        const generatedInsight = res.data;
        setSelectedAccount(prev => {
            if (!prev) return prev;
            const insights = [generatedInsight, ...(prev.insights ?? []).filter(item => item.id !== generatedInsight.id)];
            const next = {
                ...prev,
                insights,
                insightSummary: accountInsightSummary({ ...prev, insights }),
            };
            const healthRollup = accountHealthRollup(next);
            return { ...next, healthRollup, healthStatus: healthRollup.status };
        });
        toast.success(t('Summary generated'));
        loadAccounts();
    };

    const prepareActionPackage = async () => {
        if (!selectedAccount) return;
        setPreparingActionPackage(true);
        const res = await api.prepareAccountActionPackage(projectId, selectedAccount.id);
        setPreparingActionPackage(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not prepare action package'));
            return;
        }
        setSelectedAccount(res.data.account);
        toast.success(t('Action package prepared'));
        loadAccounts();
    };

    const syncCrm = async () => {
        if (!selectedAccount) return;
        setSyncingCrm(true);
        const res = await api.syncCrmConnectors(projectId);
        setSyncingCrm(false);
        if (res.error || !res.data) {
            toast.error(res.error || t('Could not sync CRM connectors'));
            return;
        }
        setCrmSyncResult(res.data);
        toast.success(t('CRM sync run') + `: ${res.data.processed} ${t('processed')}, ${res.data.failed} ${t('failed')}`);
        loadAccounts();
        const accountRes = await api.getAccount(projectId, selectedAccount.id);
        if (accountRes.data && !accountRes.error) {
            setSelectedAccount(accountRes.data);
        }
    };

    const selectedInsightSummary = selectedAccount ? accountInsightSummary(selectedAccount) : emptyInsightSummary;
    const selectedSummaryInsights = selectedAccount?.insights?.filter(insight => insight.type === 'summary') ?? [];
    const selectedActionInsights = selectedAccount?.insights?.filter(insight => insight.type !== 'summary') ?? [];
    const selectedCrmHealth = selectedAccount ? accountCrmHealth(selectedAccount) : null;
    const selectedHealthRollup = selectedAccount ? accountHealthRollup(selectedAccount) : null;

    return (
        <div className="flex min-h-0 flex-1 overflow-hidden rounded-md border bg-background">
            <aside className="flex w-[24rem] shrink-0 flex-col border-r">
                <div className="space-y-3 border-b p-4">
                    <div className="flex items-center justify-between gap-3">
                        <div>
                            <h2 className="text-base font-semibold">{t('Accounts')}</h2>
                            <p className="text-xs text-muted-foreground">{accounts.length} {t('accounts')}</p>
                        </div>
                        {loadingList && <Loader className="size-4 animate-spin text-muted-foreground" />}
                    </div>
                    <div className="relative">
                        <Search className="pointer-events-none absolute left-2 top-2.5 size-3.5 text-muted-foreground" />
                        <Input
                            value={query}
                            onChange={event => setQuery(event.target.value)}
                            placeholder={t('Search')}
                            className="h-9 pl-7"
                        />
                    </div>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto">
                    {filteredAccounts.length === 0 ? (
                        <EmptyState label={loadingList ? t('Loading') : t('No accounts')} />
                    ) : (
                        filteredAccounts.map(account => (
                            <AccountListItem
                                key={account.id}
                                account={account}
                                active={account.id === accountId}
                                onSelect={() => {
                                    if (basePath) void navigate(`${basePath}/${account.id}`);
                                }}
                            />
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
                ) : !selectedAccount ? (
                    <EmptyState label={t('Select an account')} />
                ) : (
                    <div className="mx-auto max-w-5xl px-6 py-5">
                        <section data-account-operations className="mb-5 rounded-md border p-4">
                            <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                                <div className="min-w-0">
                                    <div className="flex min-w-0 items-center gap-2 text-sm font-medium">
                                        <Building2 className="size-4 text-muted-foreground" />
                                        <span className="truncate">{t('Account operations')}</span>
                                    </div>
                                    <p className="mt-1 text-xs text-muted-foreground">
                                        {t('Support health, CRM sync, and feature-demand signals across all accounts.')}
                                    </p>
                                </div>
                                <Badge
                                    variant={accountOpsSummary.atRisk > 0 ? 'destructive' : accountOpsSummary.needsAttention > 0 ? 'secondary' : 'outline'}
                                    className="font-normal"
                                >
                                    {accountOpsSummary.atRisk > 0
                                        ? `${accountOpsSummary.atRisk} ${t('at risk')}`
                                        : accountOpsSummary.needsAttention > 0
                                            ? `${accountOpsSummary.needsAttention} ${t('need attention')}`
                                            : t('Stable')}
                                </Badge>
                            </div>
                            <div className="grid gap-2 sm:grid-cols-4">
                                <div className="rounded-md border bg-muted/20 p-2 text-xs">
                                    <div className="font-medium">{accountOpsSummary.atRisk}</div>
                                    <div className="text-muted-foreground">{t('at-risk accounts')}</div>
                                </div>
                                <div className="rounded-md border bg-muted/20 p-2 text-xs">
                                    <div className="font-medium">{accountOpsSummary.needsAttention}</div>
                                    <div className="text-muted-foreground">{t('needs attention')}</div>
                                </div>
                                <div className="rounded-md border bg-muted/20 p-2 text-xs">
                                    <div className="font-medium">{accountOpsSummary.crmAttention}</div>
                                    <div className="text-muted-foreground">{t('CRM attention')}</div>
                                </div>
                                <div className="rounded-md border bg-muted/20 p-2 text-xs">
                                    <div className="font-medium">{accountOpsSummary.featureDemand}</div>
                                    <div className="text-muted-foreground">{t('feature requests')}</div>
                                </div>
                            </div>
                            {accountOpsSummary.topAction && (
                                <div data-top-account-action className="mt-3 rounded-md border bg-muted/20 p-3">
                                    <div className="mb-2 flex flex-wrap items-start justify-between gap-3">
                                        <div className="min-w-0">
                                            <div className="truncate text-sm font-medium">{accountLabel(accountOpsSummary.topAction)}</div>
                                            <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                                                {accountHealthRollup(accountOpsSummary.topAction).nextAction}
                                            </div>
                                        </div>
                                        <Badge variant={healthVariant(accountHealthRollup(accountOpsSummary.topAction).status)} className="shrink-0 font-normal">
                                            {accountHealthRollup(accountOpsSummary.topAction).status}
                                        </Badge>
                                    </div>
                                    <div className="flex flex-wrap justify-end gap-2">
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            onClick={() => tenantId && navigate(`/${tenantId}/${projectId}/inbox${accountInboxSearch(accountOpsSummary.topAction)}`)}
                                        >
                                            <Inbox className="size-3.5" />
                                            {t('View tickets')}
                                        </Button>
                                        <Button
                                            type="button"
                                            size="sm"
                                            onClick={() => basePath && navigate(`${basePath}/${accountOpsSummary.topAction.id}`)}
                                        >
                                            <Building2 className="size-3.5" />
                                            {t('Open account')}
                                        </Button>
                                    </div>
                                </div>
                            )}
                            {actionQueueAccounts.length > 0 && (
                                <div
                                    data-account-action-queue
                                    data-account-action-queue-count={actionQueueAccounts.length}
                                    className="mt-3 rounded-md border bg-background"
                                >
                                    <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
                                        <div className="text-xs font-medium uppercase text-muted-foreground">{t('Action queue')}</div>
                                        <Badge variant="outline" className="font-normal">{actionQueueAccounts.length}</Badge>
                                    </div>
                                    <div className="divide-y">
                                        {actionQueueAccounts.map(account => {
                                            const health = accountHealthRollup(account);
                                            const action = account.accountAction;
                                            const openRiskCount = accountOpenRiskCount(account);
                                            const featureRequestCount = accountOpenFeatureRequestCount(account);
                                            const failedCrmSyncCount = accountFailedCrmSyncCount(account);
                                            return (
                                                <div
                                                    key={account.id}
                                                    data-account-action-row={account.id}
                                                    data-account-action-score={accountPriorityScore(account)}
                                                    data-account-action-kind={action?.kind || ''}
                                                    data-account-action-health={health.status}
                                                    className="grid min-w-0 gap-2 px-3 py-2 text-sm md:grid-cols-[minmax(0,1fr)_auto]"
                                                >
                                                    <div className="min-w-0">
                                                        <div className="mb-1 flex min-w-0 items-center gap-2">
                                                            <span className="truncate font-medium">{accountLabel(account)}</span>
                                                            <Badge variant={healthVariant(health.status)} className="shrink-0 font-normal">
                                                                {health.status || 'unknown'}
                                                            </Badge>
                                                        </div>
                                                        <div className="line-clamp-2 text-xs text-muted-foreground">{accountActionDetail(account)}</div>
                                                        <div className="mt-2 flex flex-wrap gap-1.5">
                                                            {health.openIssues > 0 && (
                                                                <Badge variant="outline" className="font-normal">{health.openIssues} {t('tickets')}</Badge>
                                                            )}
                                                            {openRiskCount > 0 && (
                                                                <Badge variant="destructive" className="font-normal">{openRiskCount} {t('risks')}</Badge>
                                                            )}
                                                            {featureRequestCount > 0 && (
                                                                <Badge variant="outline" className="font-normal">{featureRequestCount} {t('feature')}</Badge>
                                                            )}
                                                            {failedCrmSyncCount > 0 && (
                                                                <Badge variant="destructive" className="font-normal">{failedCrmSyncCount} {t('CRM')}</Badge>
                                                            )}
                                                        </div>
                                                    </div>
                                                    <div className="flex shrink-0 flex-wrap items-start justify-end gap-1.5">
                                                        <Button
                                                            type="button"
                                                            size="sm"
                                                            data-account-action-primary={account.id}
                                                            onClick={() => navigateAccountAction(account)}
                                                        >
                                                            <CheckCircle2 className="size-3.5" />
                                                            {t(action?.label || 'Review')}
                                                        </Button>
                                                        <Button
                                                            type="button"
                                                            size="sm"
                                                            variant="outline"
                                                            onClick={() => tenantId && navigate(`/${tenantId}/${projectId}/inbox${accountInboxSearch(account)}`)}
                                                        >
                                                            <Inbox className="size-3.5" />
                                                            {t('Tickets')}
                                                        </Button>
                                                        <Button
                                                            type="button"
                                                            size="sm"
                                                            variant={account.id === selectedAccount.id ? 'secondary' : 'outline'}
                                                            onClick={() => basePath && navigate(`${basePath}/${account.id}`)}
                                                        >
                                                            <Building2 className="size-3.5" />
                                                            {t('Account')}
                                                        </Button>
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            )}
                        </section>
                        <div className="mb-5 flex min-w-0 items-start justify-between gap-4">
                            <div className="min-w-0">
                                <div className="mb-2 flex flex-wrap items-center gap-2">
                                    <Badge variant={healthVariant(selectedHealthRollup?.status || selectedAccount.healthStatus)} className="font-normal">
                                        {selectedHealthRollup?.status || selectedAccount.healthStatus || 'unknown'}
                                    </Badge>
                                    <Badge variant="outline" className="font-normal">{selectedAccount.issueCount} {t('issues')}</Badge>
                                    {selectedInsightSummary.openRisks > 0 && (
                                        <Badge variant="destructive" className="font-normal">
                                            {selectedInsightSummary.openRisks} {t('open risks')}
                                        </Badge>
                                    )}
                                    {selectedInsightSummary.openFeatureRequests > 0 && (
                                        <Badge variant="outline" className="font-normal">
                                            {selectedInsightSummary.openFeatureRequests} {t('feature requests')}
                                        </Badge>
                                    )}
                                </div>
                                <h1 className="truncate text-xl font-semibold">{accountLabel(selectedAccount)}</h1>
                                <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted-foreground">
                                    <span>{selectedAccount.domain || '-'}</span>
                                    <span>{formatTime(selectedAccount.latestIssueAt)}</span>
                                </div>
                            </div>
                            <div className="flex shrink-0 flex-wrap justify-end gap-2">
                                <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    onClick={() => tenantId && navigate(`/${tenantId}/${projectId}/inbox${accountInboxSearch(selectedAccount)}`)}
                                >
                                    <Inbox className="size-4" />
                                    {t('View tickets')}
                                </Button>
                                {selectedAccount.domain && (
                                    <Button variant="outline" size="sm" asChild>
                                        <a href={`https://${selectedAccount.domain}`} target="_blank" rel="noreferrer">
                                            <Building2 className="size-4" />
                                            {selectedAccount.domain}
                                        </a>
                                    </Button>
                                )}
                            </div>
                        </div>

                        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
                            <div className="min-w-0 space-y-5">
                                <section className="grid gap-3 sm:grid-cols-4">
                                    <div className="rounded-md border p-3">
                                        <div className="text-xs text-muted-foreground">{t('Open risks')}</div>
                                        <div className="mt-1 text-xl font-semibold">{selectedInsightSummary.openRisks}</div>
                                    </div>
                                    <div className="rounded-md border p-3">
                                        <div className="text-xs text-muted-foreground">{t('Feature requests')}</div>
                                        <div className="mt-1 text-xl font-semibold">{selectedInsightSummary.openFeatureRequests}</div>
                                    </div>
                                    <div className="rounded-md border p-3">
                                        <div className="text-xs text-muted-foreground">{t('Active signals')}</div>
                                        <div className="mt-1 text-xl font-semibold">{selectedInsightSummary.unresolved}</div>
                                    </div>
                                    <div className="rounded-md border p-3">
                                        <div className="text-xs text-muted-foreground">{t('Contacts')}</div>
                                        <div className="mt-1 text-xl font-semibold">{selectedAccount.contacts?.length ?? 0}</div>
                                    </div>
                                </section>

                                {selectedHealthRollup && (
                                    <section className="rounded-md border p-4">
                                        <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                                            <div className="min-w-0">
                                                <h2 className="text-sm font-medium">{t('Health rollup')}</h2>
                                                <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
                                                    {selectedHealthRollup.reason}
                                                </p>
                                            </div>
                                            <Badge variant={healthVariant(selectedHealthRollup.status)} className="font-normal">
                                                {selectedHealthRollup.status}
                                            </Badge>
                                        </div>
                                        <div className="rounded-md border bg-muted/20 p-3 text-sm">
                                            <div className="flex flex-wrap items-start justify-between gap-3">
                                                <div className="min-w-0">
                                                    <div className="mb-1 text-xs font-medium uppercase text-muted-foreground">{t('Next action')}</div>
                                                    <div>{selectedHealthRollup.nextAction}</div>
                                                </div>
                                                <Button
                                                    type="button"
                                                    size="sm"
                                                    variant="outline"
                                                    data-prepare-account-action-package
                                                    onClick={() => void prepareActionPackage()}
                                                    disabled={preparingActionPackage}
                                                >
                                                    {preparingActionPackage ? <Loader className="size-3.5 animate-spin" /> : <CheckCircle2 className="size-3.5" />}
                                                    {t('Prepare action')}
                                                </Button>
                                            </div>
                                        </div>
                                        <div className="mt-3 grid gap-2 text-sm sm:grid-cols-3">
                                            <div className="rounded-md border bg-muted/20 p-2">
                                                <div className="text-xs text-muted-foreground">{t('Open tickets')}</div>
                                                <div className="mt-1 font-semibold">{selectedHealthRollup.openIssues}</div>
                                            </div>
                                            <div className="rounded-md border bg-muted/20 p-2">
                                                <div className="text-xs text-muted-foreground">{t('Open risks')}</div>
                                                <div className="mt-1 font-semibold">{selectedHealthRollup.openRisks}</div>
                                            </div>
                                            <div className="rounded-md border bg-muted/20 p-2">
                                                <div className="text-xs text-muted-foreground">{t('Failed CRM sync')}</div>
                                                <div className="mt-1 font-semibold">{selectedHealthRollup.failedExternalSyncRuns}</div>
                                            </div>
                                        </div>
                                    </section>
                                )}

                                {selectedSummaryInsights.length > 0 && (
                                    <section className="rounded-md border p-4">
                                        <div className="mb-3 text-sm font-medium">{t('Summary')}</div>
                                        <div className="space-y-3">
                                            {selectedSummaryInsights.map(insight => (
                                                <div key={insight.id} className="rounded-md border bg-muted/20 p-3">
                                                    <div className="mb-1 flex min-w-0 items-center justify-between gap-2">
                                                        <div className="truncate text-sm font-medium">{insight.title}</div>
                                                        <Badge variant={insightVariant(insight.severity)} className="font-normal">
                                                            {insight.severity || 'info'}
                                                        </Badge>
                                                    </div>
                                                    <p className="whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
                                                        {insight.body}
                                                    </p>
                                                </div>
                                            ))}
                                        </div>
                                    </section>
                                )}

                                <section className="rounded-md border p-4">
                                    <div className="mb-3 flex items-center justify-between">
                                        <h2 className="text-sm font-medium">{t('Account intelligence')}</h2>
                                        <Badge variant="outline" className="font-normal">
                                            {selectedActionInsights.length}
                                        </Badge>
                                    </div>
                                    <div className="mb-4 border-b pb-4">
                                        <div className="mb-3 flex flex-wrap gap-1.5">
                                            <Button type="button" size="sm" variant="outline" data-account-insight-template="risk" onClick={() => applyInsightTemplate('risk')}>
                                                <AlertTriangle className="size-3.5" />
                                                {t('Risk')}
                                            </Button>
                                            <Button type="button" size="sm" variant="outline" data-account-insight-template="feature_request" onClick={() => applyInsightTemplate('feature_request')}>
                                                <Lightbulb className="size-3.5" />
                                                {t('Feature request')}
                                            </Button>
                                            <Button type="button" size="sm" variant="outline" data-account-insight-template="summary" onClick={() => applyInsightTemplate('summary')}>
                                                <CheckCircle2 className="size-3.5" />
                                                {t('Summary')}
                                            </Button>
                                            <Button
                                                type="button"
                                                size="sm"
                                                onClick={() => void generateSummary()}
                                                disabled={generatingSummary}
                                                data-generate-account-summary
                                            >
                                                {generatingSummary ? <Loader className="size-3.5 animate-spin" /> : <Database className="size-3.5" />}
                                                {t('Generate summary')}
                                            </Button>
                                        </div>
                                        <div className="grid gap-3 sm:grid-cols-[10rem_10rem_1fr]">
                                            <div className="space-y-1.5">
                                                <Label>{t('Type')}</Label>
                                                <Select value={newInsightType} onValueChange={setNewInsightType}>
                                                    <SelectTrigger>
                                                        <SelectValue />
                                                    </SelectTrigger>
                                                    <SelectContent>
                                                        <SelectItem value="risk">{t('Risk')}</SelectItem>
                                                        <SelectItem value="feature_request">{t('Feature request')}</SelectItem>
                                                        <SelectItem value="summary">{t('Summary')}</SelectItem>
                                                    </SelectContent>
                                                </Select>
                                            </div>
                                            <div className="space-y-1.5">
                                                <Label>{t('Severity')}</Label>
                                                <Select value={newInsightSeverity} onValueChange={setNewInsightSeverity}>
                                                    <SelectTrigger>
                                                        <SelectValue />
                                                    </SelectTrigger>
                                                    <SelectContent>
                                                        <SelectItem value="info">{t('Info')}</SelectItem>
                                                        <SelectItem value="normal">{t('Normal')}</SelectItem>
                                                        <SelectItem value="needs_attention">{t('Needs attention')}</SelectItem>
                                                        <SelectItem value="high">{t('High')}</SelectItem>
                                                        <SelectItem value="urgent">{t('Urgent')}</SelectItem>
                                                        <SelectItem value="at_risk">{t('At risk')}</SelectItem>
                                                    </SelectContent>
                                                </Select>
                                            </div>
                                            <div className="space-y-1.5">
                                                <Label htmlFor="account-insight-title">{t('Title')}</Label>
                                                <Input
                                                    id="account-insight-title"
                                                    value={newInsightTitle}
                                                    onChange={event => setNewInsightTitle(event.target.value)}
                                                />
                                            </div>
                                        </div>
                                        <div className="mt-3 space-y-1.5">
                                            <Label htmlFor="account-insight-body">{t('Body')}</Label>
                                            <Textarea
                                                id="account-insight-body"
                                                value={newInsightBody}
                                                onChange={event => setNewInsightBody(event.target.value)}
                                                rows={3}
                                            />
                                        </div>
                                        <div className="mt-3 flex justify-end">
                                            <Button type="button" size="sm" data-account-add-insight onClick={() => void createInsight()} disabled={savingNewInsight}>
                                                {savingNewInsight ? <Loader className="size-4 animate-spin" /> : <Lightbulb className="size-4" />}
                                                {t('Add insight')}
                                            </Button>
                                        </div>
                                    </div>
                                    <div className="space-y-3">
                                        {selectedActionInsights.length === 0 ? (
                                            <div className="py-4 text-sm text-muted-foreground">{t('No account insights')}</div>
                                        ) : (
                                            selectedActionInsights.map(insight => {
                                                const signalCategory = insightMetadataString(insight, 'signalCategory');
                                                const recommendedAction = insightMetadataString(insight, 'recommendedAction');
                                                return (
                                                    <div key={insight.id} className="rounded-md border bg-muted/20 p-3">
                                                        <div className="mb-2 flex items-start justify-between gap-3">
                                                            <div className="flex min-w-0 items-start gap-2">
                                                                <InsightIcon type={insight.type} />
                                                                <div className="min-w-0">
                                                                    <div className="truncate text-sm font-medium">{insight.title}</div>
                                                                    <div className="mt-1 flex flex-wrap gap-1.5">
                                                                        <Badge variant={insightVariant(insight.severity)} className="font-normal">
                                                                            {insight.severity || 'info'}
                                                                        </Badge>
                                                                        <Badge variant="outline" className="font-normal">{insight.type}</Badge>
                                                                        <Badge variant="outline" className="font-normal">{insight.status}</Badge>
                                                                        {signalCategory && (
                                                                            <Badge variant="secondary" className="font-normal" data-account-insight-signal-category={signalCategory}>
                                                                                {signalCategory}
                                                                            </Badge>
                                                                        )}
                                                                    </div>
                                                                </div>
                                                            </div>
                                                            <div className="flex shrink-0 gap-1.5">
                                                                {insight.status === 'open' && (
                                                                    <Button
                                                                        type="button"
                                                                        size="sm"
                                                                        variant="outline"
                                                                        data-account-insight-acknowledge={insight.id}
                                                                        onClick={() => void updateInsightStatus(insight, 'acknowledged')}
                                                                        disabled={savingInsightId === insight.id}
                                                                    >
                                                                        {savingInsightId === insight.id ? <Loader className="size-4 animate-spin" /> : t('Acknowledge')}
                                                                    </Button>
                                                                )}
                                                                {insight.status !== 'resolved' && (
                                                                    <Button
                                                                        type="button"
                                                                        size="sm"
                                                                        variant="ghost"
                                                                        data-account-insight-resolve={insight.id}
                                                                        onClick={() => void updateInsightStatus(insight, 'resolved')}
                                                                        disabled={savingInsightId === insight.id}
                                                                    >
                                                                        {t('Resolve')}
                                                                    </Button>
                                                                )}
                                                                {insight.sourceIssueId && tenantId && (
                                                                    <Button
                                                                        type="button"
                                                                        size="sm"
                                                                        variant="outline"
                                                                        onClick={() => navigate(`/${tenantId}/${projectId}/inbox/${insight.sourceIssueId}${accountInboxSearch(selectedAccount)}`)}
                                                                    >
                                                                        <Inbox className="size-4" />
                                                                        {t('Ticket')}
                                                                    </Button>
                                                                )}
                                                            </div>
                                                        </div>
                                                        {insight.body && (
                                                            <p className="whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
                                                                {insight.body}
                                                            </p>
                                                        )}
                                                        {recommendedAction && (
                                                            <div className="mt-2 rounded-md border bg-background px-3 py-2 text-xs" data-account-insight-recommended-action={insight.id}>
                                                                <div className="mb-0.5 font-medium text-foreground">{t('Recommended action')}</div>
                                                                <div className="text-muted-foreground">{recommendedAction}</div>
                                                            </div>
                                                        )}
                                                        <div className="mt-2 text-xs text-muted-foreground">
                                                            {formatTime(insight.lastSeenAt || insight.updated)}
                                                        </div>
                                                    </div>
                                                );
                                            })
                                        )}
                                    </div>
                                </section>

                                {selectedCrmHealth && (
                                    <section className="rounded-md border p-4">
                                        <div className="mb-3 flex items-center justify-between gap-3">
                                            <div>
                                                <h2 className="text-sm font-medium">{t('CRM health')}</h2>
                                                <p className="mt-1 text-xs text-muted-foreground">
                                                    {selectedCrmHealth.providers.length > 0
                                                        ? selectedCrmHealth.providers.map(providerLabel).join(', ')
                                                        : t('No CRM provider linked')}
                                                </p>
                                            </div>
                                            <Badge variant={selectedCrmHealth.variant} className="font-normal">
                                                {t(selectedCrmHealth.label)}
                                            </Badge>
                                        </div>
                                        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                                            <p className="text-xs text-muted-foreground">
                                                {t('Refresh CRM context before relying on account health, ownership, or external fields.')}
                                            </p>
                                            <Button
                                                type="button"
                                                size="sm"
                                                variant="outline"
                                                onClick={() => void syncCrm()}
                                                disabled={syncingCrm}
                                                data-account-crm-sync
                                            >
                                                {syncingCrm ? <Loader className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
                                                {t('Sync CRM')}
                                            </Button>
                                        </div>
                                        {crmSyncResult && (
                                            <div data-account-crm-sync-result className="mb-3 rounded-md border bg-muted/20 p-3 text-sm">
                                                <div className="font-medium">{t('CRM sync result')}</div>
                                                <div className="mt-1 text-muted-foreground">
                                                    {crmSyncResult.connectors} {t('connectors')} · {crmSyncResult.processed} {t('processed')} · {crmSyncResult.objectsSeen} {t('objects')} · {crmSyncResult.failed} {t('failed')}
                                                </div>
                                            </div>
                                        )}
                                        <div className="grid gap-3 sm:grid-cols-3">
                                            <div className="rounded-md border bg-muted/20 p-3">
                                                <div className="text-xs text-muted-foreground">{t('External records')}</div>
                                                <div className="mt-1 text-lg font-semibold">{selectedCrmHealth.externalObjects.length}</div>
                                            </div>
                                            <div className="rounded-md border bg-muted/20 p-3">
                                                <div className="text-xs text-muted-foreground">{t('Sync runs')}</div>
                                                <div className="mt-1 text-lg font-semibold">{selectedCrmHealth.syncRuns.length}</div>
                                            </div>
                                            <div className="rounded-md border bg-muted/20 p-3">
                                                <div className="text-xs text-muted-foreground">{t('Latest sync')}</div>
                                                <div className="mt-1 truncate text-sm font-medium">
                                                    {selectedCrmHealth.latestRun ? formatTime(syncRunTime(selectedCrmHealth.latestRun)) : '-'}
                                                </div>
                                                {selectedCrmHealth.latestRun && (
                                                    <Badge variant={syncVariant(selectedCrmHealth.latestRun.status)} className="mt-2 font-normal">
                                                        {selectedCrmHealth.latestRun.status || 'unknown'}
                                                    </Badge>
                                                )}
                                            </div>
                                        </div>
                                        {selectedCrmHealth.failedRuns.length > 0 && (
                                            <div className="mt-3 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                                                <div className="font-medium">
                                                    {selectedCrmHealth.failedRuns.length} {t('sync runs need attention')}
                                                </div>
                                                <div className="mt-1 text-xs">
                                                    {selectedCrmHealth.failedRuns[0]?.error || t('Review CRM connector sync logs in Channels.')}
                                                </div>
                                            </div>
                                        )}
                                    </section>
                                )}

                                <section className="rounded-md border p-4">
                                    <div className="mb-3 flex items-center justify-between">
                                        <h2 className="text-sm font-medium">{t('External records')}</h2>
                                        <Badge variant="outline" className="font-normal">
                                            {selectedAccount.externalObjects?.length ?? 0}
                                        </Badge>
                                    </div>
                                    <div className="space-y-3">
                                        {(selectedAccount.externalObjects ?? []).length === 0 ? (
                                            <div className="py-4 text-sm text-muted-foreground">{t('No external records')}</div>
                                        ) : (
                                            (selectedAccount.externalObjects ?? []).map(object => (
                                                <div key={object.id} className="rounded-md border bg-muted/20 p-3">
                                                    <div className="mb-2 flex items-start justify-between gap-3">
                                                        <div className="flex min-w-0 items-start gap-2">
                                                            <Database className="mt-0.5 size-4 text-muted-foreground" />
                                                            <div className="min-w-0">
                                                                <div className="truncate text-sm font-medium">
                                                                    {object.displayName || object.externalId}
                                                                </div>
                                                                <div className="mt-1 flex flex-wrap gap-1.5">
                                                                    <Badge variant="outline" className="font-normal">{providerLabel(object.provider)}</Badge>
                                                                    <Badge variant="secondary" className="font-normal">{object.objectType}</Badge>
                                                                </div>
                                                            </div>
                                                        </div>
                                                        {object.externalUrl && (
                                                            <Button type="button" size="sm" variant="ghost" asChild>
                                                                <a href={object.externalUrl} target="_blank" rel="noreferrer">
                                                                    <ExternalLink className="size-4" />
                                                                    {t('Open')}
                                                                </a>
                                                            </Button>
                                                        )}
                                                    </div>
                                                    <div className="break-all text-xs text-muted-foreground">{object.externalId}</div>
                                                    <div className="mt-2 text-xs text-muted-foreground">
                                                        {t('Last seen')} {formatTime(object.lastSeenAt)}
                                                    </div>
                                                </div>
                                            ))
                                        )}
                                    </div>
                                </section>

                                <section className="rounded-md border p-4">
                                    <div className="mb-3 flex items-center justify-between">
                                        <h2 className="text-sm font-medium">{t('Recent issues')}</h2>
                                        <Badge variant="outline" className="font-normal">
                                            {selectedAccount.issues?.length ?? 0}
                                        </Badge>
                                    </div>
                                    <div className="divide-y">
                                        {(selectedAccount.issues ?? []).length === 0 ? (
                                            <div className="py-6 text-sm text-muted-foreground">{t('No issues')}</div>
                                        ) : (
                                            (selectedAccount.issues ?? []).map(issue => (
                                                <button
                                                    key={issue.id}
                                                    type="button"
                                                    className="flex w-full items-center justify-between gap-4 py-3 text-left hover:text-foreground"
                                                    onClick={() => tenantId && navigate(`/${tenantId}/${projectId}/inbox/${issue.id}${accountInboxSearch(selectedAccount)}`)}
                                                >
                                                    <div className="min-w-0">
                                                        <div className="truncate text-sm font-medium">{issueLabel(issue)}</div>
                                                        <div className="mt-1 flex flex-wrap gap-2 text-xs text-muted-foreground">
                                                            <span>{issue.status}</span>
                                                            <span>{issue.priority}</span>
                                                            <span>{formatTime(issue.latestMessageAt)}</span>
                                                        </div>
                                                    </div>
                                                    <Inbox className="size-4 shrink-0 text-muted-foreground" />
                                                </button>
                                            ))
                                        )}
                                    </div>
                                </section>
                            </div>

                            <aside className="space-y-4">
                                <section className="rounded-md border p-4">
                                    <div className="mb-3 text-sm font-medium">{t('Contacts')}</div>
                                    <div className="space-y-3">
                                        {(selectedAccount.contacts ?? []).length === 0 ? (
                                            <div className="text-sm text-muted-foreground">-</div>
                                        ) : (
                                            (selectedAccount.contacts ?? []).map(contact => (
                                                <div key={contact.id} className="space-y-1 text-sm">
                                                    <div className="font-medium">{contact.name || contact.email || '-'}</div>
                                                    {contact.email && (
                                                        <a className="flex min-w-0 items-center gap-1.5 text-muted-foreground hover:text-foreground" href={`mailto:${contact.email}`}>
                                                            <Mail className="size-3.5 shrink-0" />
                                                            <span className="truncate">{contact.email}</span>
                                                        </a>
                                                    )}
                                                    <div className="text-xs text-muted-foreground">
                                                        {contact.issueCount} {t('issues')}
                                                    </div>
                                                    <Separator className="last:hidden" />
                                                </div>
                                            ))
                                        )}
                                    </div>
                                </section>

                                <section className="rounded-md border p-4">
                                    <div className="mb-3 text-sm font-medium">{t('External sync')}</div>
                                    <div className="space-y-2">
                                        {(selectedAccount.externalSyncRuns ?? []).length === 0 ? (
                                            <div className="text-sm text-muted-foreground">-</div>
                                        ) : (
                                            (selectedAccount.externalSyncRuns ?? []).map(run => (
                                                <div key={run.id} className="space-y-1 rounded-md border bg-muted/20 p-2 text-sm">
                                                    <div className="flex items-center justify-between gap-2">
                                                        <span className="truncate">{providerLabel(run.provider)}</span>
                                                        <Badge variant={syncVariant(run.status)} className="font-normal">{run.status || 'unknown'}</Badge>
                                                    </div>
                                                    <div className="text-xs text-muted-foreground">
                                                        {run.objectsSeen} {t('objects')} · {formatTime(syncRunTime(run))}
                                                    </div>
                                                    {run.error && <div className="text-xs text-destructive">{run.error}</div>}
                                                </div>
                                            ))
                                        )}
                                    </div>
                                </section>

                                <section className="rounded-md border p-4">
                                    <div className="mb-3 text-sm font-medium">{t('Account data')}</div>
                                    <div className="space-y-2 text-sm">
                                        <div>
                                            <div className="text-xs text-muted-foreground">{t('External ID')}</div>
                                            <div>{selectedAccount.externalId || '-'}</div>
                                        </div>
                                        <div>
                                            <div className="text-xs text-muted-foreground">{t('Key')}</div>
                                            <div className="break-all">{selectedAccount.accountKey || '-'}</div>
                                        </div>
                                    </div>
                                </section>
                            </aside>
                        </div>
                    </div>
                )}
            </section>
        </div>
    );
}
