import { useCallback, useEffect, useState } from 'react';
import { Building2, CreditCard, ExternalLink, Info, Loader, Mail, Zap } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { api } from '@/api/endpoints';
import type { BillingStatus } from '@/api/endpoints';
import { brand } from '@/brand';
import { useI18n } from '@/lib/i18n-context';
import type { Locale } from '@/lib/i18n-core';

// ── Usage meter ──────────────────────────────────────────────────────────────

function UsageMeter({
    label,
    current,
    limit,
}: {
    label: string;
    current: number;
    limit: number;
}) {
    const { t } = useI18n();
    const isUnlimited = limit < 0;
    const pct = isUnlimited ? 0 : limit > 0 ? Math.min((current / limit) * 100, 100) : 0;
    const isNearLimit = pct >= 80;
    const isAtLimit = pct >= 100;

    return (
        <div className="space-y-1.5">
            <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">{label}</span>
                <span className={isAtLimit ? 'font-medium text-red-600' : isNearLimit ? 'font-medium text-orange-500' : ''}>
                    {current.toLocaleString()} / {isUnlimited ? t('Unlimited') : limit.toLocaleString()}
                </span>
            </div>
            <div className="h-2 rounded-full bg-muted overflow-hidden">
                <div
                    className={`h-full rounded-full transition-all ${
                        isAtLimit ? 'bg-red-500' : isNearLimit ? 'bg-orange-400' : 'bg-primary'
                    }`}
                    style={{ width: `${pct}%` }}
                />
            </div>
        </div>
    );
}

// ── Plan display helpers ─────────────────────────────────────────────────────

const PLAN_META: Record<string, { label: string; description: string }> = {
    free: {
        label: 'Cloud Sandbox',
        description: 'Explore the managed core with limited usage.',
    },
    pro: {
        label: 'Cloud',
        description: 'Managed hosting for operational support teams.',
    },
    business: {
        label: 'Business',
        description: 'Team automation with security controls.',
    },
    enterprise: {
        label: 'Enterprise',
        description: 'Custom deployment and onboarding for regulated teams.',
    },
};

function formatBillingDate(value: string, locale: Locale): string {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return new Intl.DateTimeFormat(locale === 'de' ? 'de-DE' : 'en-US', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
    }).format(date);
}

// ── Billing page ─────────────────────────────────────────────────────────────

export function Billing({ isDemoAccount = false }: { isDemoAccount?: boolean }) {
    const [status, setStatus] = useState<BillingStatus | null>(null);
    const [loading, setLoading] = useState(!isDemoAccount);
    const [checkoutLoading, setCheckoutLoading] = useState<'pro' | 'business' | null>(null);
    const [portalLoading, setPortalLoading] = useState(false);
    const { locale, t } = useI18n();

    const loadStatus = useCallback(() => {
        void api.getBillingStatus().then(res => {
            if (res.data) setStatus(res.data);
            if (res.error) toast.error(res.error);
            setLoading(false);
        });
    }, []);

    useEffect(() => {
        if (isDemoAccount) return;
        loadStatus();
    }, [isDemoAccount, loadStatus]);

    const handleUpgrade = async (targetPlan: 'pro' | 'business' = 'pro') => {
        setCheckoutLoading(targetPlan);
        try {
            const res = await api.createCheckoutSession(
                window.location.href,
                window.location.href,
                targetPlan,
            );
            if (res.error || !res.data) {
                toast.error(res.error || t('Failed to create checkout session'));
                return;
            }
            window.location.href = res.data.url;
        } finally {
            setCheckoutLoading(null);
        }
    };

    const handleManageBilling = async () => {
        setPortalLoading(true);
        try {
            const res = await api.createPortalSession(window.location.href);
            if (res.error || !res.data) {
                toast.error(res.error || t('Failed to open billing portal'));
                return;
            }
            window.location.href = res.data.url;
        } finally {
            setPortalLoading(false);
        }
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center py-20">
                <Loader className="size-6 animate-spin text-muted-foreground" />
            </div>
        );
    }

    if (isDemoAccount) {
        return (
            <div className="w-full max-w-2xl mx-auto space-y-6">
                <Card>
                    <CardHeader>
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-3">
                                <div className="flex size-10 items-center justify-center rounded-lg bg-muted">
                                    <CreditCard className="size-5 text-muted-foreground" />
                                </div>
                                <div>
                                    <h2 className="text-lg font-semibold">{t('Demo Plan')}</h2>
                                    <p className="text-sm text-muted-foreground">
                                        {t('This workspace is configured for guided demo use.')}
                                    </p>
                                </div>
                            </div>
                            <Badge variant="secondary">{t('Demo')}</Badge>
                        </div>
                    </CardHeader>
                    <CardContent>
                        <Button variant="outline" asChild>
                            <a href={`mailto:${brand.supportEmail}`}>
                                <Mail className="size-4 mr-1" />
                                {t('Contact Support for an Update')}
                            </a>
                        </Button>
                    </CardContent>
                </Card>
            </div>
        );
    }

    if (!status) {
        return (
            <div className="text-center py-20 text-muted-foreground">
                {t('Failed to load billing information.')}
            </div>
        );
    }

    const plan = status.plan;
    const meta = PLAN_META[plan] ?? PLAN_META.free;
    const isPastDue = status.subscriptionStatus === 'past_due';
    const cancelDate = status.cancelAtPeriodEnd ? formatBillingDate(status.currentPeriodEnd, locale) : '';

    return (
        <div className="w-full max-w-2xl mx-auto space-y-6">
            {/* Plan card */}
            <Card>
                <CardHeader>
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                            <div className={`flex size-10 items-center justify-center rounded-lg ${
                                plan === 'enterprise'
                                    ? 'bg-violet-100 dark:bg-violet-900/30'
                                    : plan === 'pro' || plan === 'business'
                                        ? 'bg-primary text-primary-foreground'
                                        : 'bg-muted'
                            }`}>
                                {plan === 'enterprise'
                                    ? <Building2 className="size-5 text-violet-600 dark:text-violet-400" />
                                    : plan === 'pro' || plan === 'business'
                                        ? <Zap className="size-5" />
                                        : <CreditCard className="size-5 text-muted-foreground" />}
                            </div>
                            <div>
                                <h2 className="text-lg font-semibold">{t('{plan} Plan', { plan: t(meta.label) })}</h2>
                                <p className="text-sm text-muted-foreground">{t(meta.description)}</p>
                            </div>
                        </div>
                        <Badge variant={plan === 'free' ? 'secondary' : 'default'}>
                            {t(meta.label)}
                        </Badge>
                    </div>
                    {isPastDue && (
                        <div className="mt-3 rounded-md bg-red-50 border border-red-200 p-3 text-sm text-red-700">
                            {t('Your last payment failed. Please update your payment method to avoid service interruption.')}
                        </div>
                    )}
                    {plan === 'pro' && status.cancelAtPeriodEnd && (
                        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                            <div className="font-medium">
                                {cancelDate ? t('Cloud active until {date}.', { date: cancelDate }) : t('Cloud subscription scheduled to cancel.')}
                            </div>
                            <div className="mt-0.5">
                                {t('Your subscription is scheduled to cancel at the end of the billing period.')}
                            </div>
                        </div>
                    )}
                </CardHeader>
                <CardContent>
                    <div className="flex gap-3">
                        {plan === 'free' && (
                            <Button onClick={() => handleUpgrade('pro')} disabled={checkoutLoading !== null}>
                                {checkoutLoading === 'pro' && <Loader className="size-4 animate-spin mr-2" />}
                                <Zap className="size-4 mr-1" />
                                {t('Upgrade to Cloud')}
                            </Button>
                        )}
                        {(plan === 'pro' || plan === 'business') && (
                            <Button variant="outline" onClick={handleManageBilling} disabled={portalLoading}>
                                {portalLoading && <Loader className="size-4 animate-spin mr-2" />}
                                <ExternalLink className="size-4 mr-1" />
                                {t('Manage billing')}
                            </Button>
                        )}
                        {plan === 'enterprise' && (
                            <Button variant="outline" asChild>
                                <a href={`mailto:${brand.supportEmail}`}>
                                    <Mail className="size-4 mr-1" />
                                    {t('Contact support')}
                                </a>
                            </Button>
                        )}
                    </div>
                </CardContent>
            </Card>

            {/* Usage card */}
            <Card>
                <CardHeader>
                    <div className="flex items-start justify-between gap-3">
                        <div>
                            <h3 className="font-semibold">{t('Usage')}</h3>
                            <p className="text-sm text-muted-foreground">
                                {t('Current billing period usage against your plan limits.')}
                            </p>
                        </div>
                        <Dialog>
                            <DialogTrigger asChild>
                                <Button variant="outline" size="sm">
                                    <Info className="size-4 mr-1" />
                                    {t('Billing rules')}
                                </Button>
                            </DialogTrigger>
                            <DialogContent>
                                <DialogHeader>
                                    <DialogTitle>{t('Billing rules')}</DialogTitle>
                                    <DialogDescription>
                                        {t('What is included in your plan and what can create additional invoice items.')}
                                    </DialogDescription>
                                </DialogHeader>
                                <div className="space-y-4 text-sm text-muted-foreground">
                                    <div>
                                        <div className="font-medium text-foreground">{t('Plan limits')}</div>
                                        <p>
                                            {t('Agent runs and projects are included up to the plan limit. One agent run is one inbound customer message, regardless of concerns, runbooks, knowledge searches, tool calls, or response steps.')}
                                        </p>
                                    </div>
                                    <div>
                                        <div className="font-medium text-foreground">{t('Paid add-ons')}</div>
                                        <p>
                                            {t('Extra projects and additional agent-run blocks can be billed as Stripe subscription items. You can manage or cancel the subscription in the Stripe portal.')}
                                        </p>
                                    </div>
                                    <div>
                                        <div className="font-medium text-foreground">{t('LLM keys')}</div>
                                        <p>
                                            {t('BYOK usage is not surcharged. If a paid workspace uses the Mantly-managed LLM key, usage is billed at provider cost multiplied by 1.2.')}
                                        </p>
                                    </div>
                                </div>
                            </DialogContent>
                        </Dialog>
                    </div>
                    <div className="mt-3 flex gap-3 rounded-md border bg-muted/40 p-3 text-sm text-muted-foreground">
                        <Info className="mt-0.5 size-4 shrink-0 text-primary" />
                        <div>
                            {t('Usage above the included project or agent-run limits can create paid add-ons when the related Stripe add-on prices are configured.')}
                        </div>
                    </div>
                </CardHeader>
                <CardContent className="space-y-4">
                    <UsageMeter
                        label={t('Agent runs')}
                        current={status.usage.agentRunsThisPeriod}
                        limit={status.limits.agentRunsPerMonth}
                    />
                    <Separator />
                    <UsageMeter
                        label={t('Projects')}
                        current={status.usage.projects}
                        limit={status.limits.projects}
                    />
                    <Separator />
                    <UsageMeter
                        label={t('Team members')}
                        current={status.usage.users}
                        limit={status.limits.users}
                    />
                    <Separator />
                    <UsageMeter
                        label={t('Evaluation runs')}
                        current={status.usage.evalRunsThisPeriod}
                        limit={status.limits.evalRunsPerMonth}
                    />
                    <Separator />
                    <UsageMeter
                        label={t('Evaluation sets')}
                        current={status.usage.evalSets}
                        limit={status.limits.evalSets}
                    />
                    <Separator />
                    <div className="flex items-center justify-between text-sm">
                        <span className="text-muted-foreground">{t('Data retention')}</span>
                        <span>{t('{count} days', { count: status.limits.retentionDays.toLocaleString() })}</span>
                    </div>
                </CardContent>
            </Card>

            {/* LLM usage card */}
            <Card>
                <CardHeader>
                    <h3 className="font-semibold">{t('LLM usage')}</h3>
                    <p className="text-sm text-muted-foreground">
                        {t('BYOK usage has no Mantly surcharge. Mantly-managed LLM usage is billed at provider cost x 1.2.')}
                    </p>
                    <div className="mt-3 flex gap-3 rounded-md border bg-muted/40 p-3 text-sm text-muted-foreground">
                        <Info className="mt-0.5 size-4 shrink-0 text-primary" />
                        <div>
                            {t('Free workspaces use the Mantly-managed LLM key as included usage. Paid workspaces can add their own key; otherwise Mantly-managed usage appears on the invoice with a 1.2 factor.')}
                        </div>
                    </div>
                </CardHeader>
                <CardContent className="grid gap-4 sm:grid-cols-3">
                    <div>
                        <div className="text-sm text-muted-foreground">{t('Managed calls')}</div>
                        <div className="text-2xl font-semibold">{status.llmUsage.managedEventCount.toLocaleString()}</div>
                        <div className="text-xs text-muted-foreground">
                            {t('{count} reported to Stripe', { count: status.llmUsage.reportedEventCount.toLocaleString() })}
                        </div>
                    </div>
                    <div>
                        <div className="text-sm text-muted-foreground">{t('Provider cost')}</div>
                        <div className="text-2xl font-semibold">${status.llmUsage.rawCostUsd.toFixed(2)}</div>
                    </div>
                    <div>
                        <div className="text-sm text-muted-foreground">{t('Billed cost')}</div>
                        <div className="text-2xl font-semibold">${status.llmUsage.billedCostUsd.toFixed(2)}</div>
                    </div>
                </CardContent>
            </Card>

            {/* Plan comparison (for free and pro users) */}
            {plan !== 'enterprise' && (
                <Card>
                    <CardHeader>
                        <h3 className="font-semibold">{t('Compare plans')}</h3>
                    </CardHeader>
                    <CardContent>
                        <div className="grid grid-cols-5 gap-4 text-sm">
                            <div className="font-medium text-muted-foreground">{t('Feature')}</div>
                            <div className="font-medium text-center">{t('Cloud Sandbox')}</div>
                            <div className="font-medium text-center">{t('Cloud')}</div>
                            <div className="font-medium text-center">{t('Business')}</div>
                            <div className="font-medium text-center">{t('Enterprise')}</div>

                            <div className="text-muted-foreground">{t('Agent runs / month')}</div>
                            <div className="text-center">20</div>
                            <div className="text-center font-medium">150</div>
                            <div className="text-center font-medium">1,000</div>
                            <div className="text-center font-medium">{t('Custom')}</div>

                            <div className="text-muted-foreground">{t('Projects')}</div>
                            <div className="text-center">1</div>
                            <div className="text-center font-medium">1</div>
                            <div className="text-center font-medium">10</div>
                            <div className="text-center font-medium">{t('Custom')}</div>

                            <div className="text-muted-foreground">{t('Team members')}</div>
                            <div className="text-center">1</div>
                            <div className="text-center font-medium">{t('Unlimited')}</div>
                            <div className="text-center font-medium">{t('Unlimited')}</div>
                            <div className="text-center font-medium">{t('Unlimited')}</div>

                            <div className="text-muted-foreground">{t('Eval runs / month')}</div>
                            <div className="text-center">5</div>
                            <div className="text-center font-medium">50</div>
                            <div className="text-center font-medium">{t('Unlimited')}</div>
                            <div className="text-center font-medium">{t('Custom')}</div>

                            <div className="text-muted-foreground">{t('BYOK LLMs')}</div>
                            <div className="text-center text-muted-foreground">--</div>
                            <div className="text-center font-medium">{t('Included')}</div>
                            <div className="text-center font-medium">{t('Included')}</div>
                            <div className="text-center font-medium">{t('Included')}</div>

                            <div className="text-muted-foreground">{t('Security monitoring')}</div>
                            <div className="text-center font-medium">{t('Included')}</div>
                            <div className="text-center font-medium">{t('Included')}</div>
                            <div className="text-center font-medium">{t('Included')}</div>
                            <div className="text-center font-medium">{t('Custom')}</div>

                            <div className="text-muted-foreground">{t('Dedicated support')}</div>
                            <div className="text-center text-muted-foreground">--</div>
                            <div className="text-center text-muted-foreground">--</div>
                            <div className="text-center text-muted-foreground">--</div>
                            <div className="text-center font-medium">{t('Included')}</div>

                            <div className="text-muted-foreground">{t('On-premise deployment')}</div>
                            <div className="text-center text-muted-foreground">--</div>
                            <div className="text-center text-muted-foreground">--</div>
                            <div className="text-center font-medium">{t('Add-on')}</div>
                            <div className="text-center font-medium">{t('Available')}</div>

                            <div className="text-muted-foreground">{t('Price')}</div>
                            <div className="text-center">{t('Free')}</div>
                            <div className="text-center font-medium">19 EUR/mo</div>
                            <div className="text-center font-medium">199 EUR/mo</div>
                            <div className="text-center font-medium">{t('Custom')}</div>

                        </div>
                        <p className="mt-3 text-xs text-muted-foreground">
                            {t('Mantly-managed LLM usage is billed at provider cost x 1.2. BYOK LLM usage has no surcharge.')}
                        </p>
                        <div className="mt-5 flex gap-3">
                            {plan === 'free' && (
                                <Button onClick={() => handleUpgrade('pro')} disabled={checkoutLoading !== null} size="sm">
                                    {checkoutLoading === 'pro' && <Loader className="size-4 animate-spin mr-2" />}
                                    {t('Upgrade to Cloud')}
                                </Button>
                            )}
                            {plan !== 'business' && (
                                <Button
                                    variant="outline"
                                    onClick={() => handleUpgrade('business')}
                                    disabled={checkoutLoading !== null}
                                    size="sm"
                                >
                                    {checkoutLoading === 'business' && <Loader className="size-4 animate-spin mr-2" />}
                                    {t('Upgrade to Business')}
                                </Button>
                            )}
                            <Button variant="outline" size="sm" asChild>
                                <a href={`mailto:${brand.supportEmail}`}>
                                    <Mail className="size-4 mr-1" />
                                    {t('Contact us for Enterprise')}
                                </a>
                            </Button>
                        </div>
                    </CardContent>
                </Card>
            )}
        </div>
    );
}
