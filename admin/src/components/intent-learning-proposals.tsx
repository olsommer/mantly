import { useState } from 'react';
import { AlertTriangle, CheckCircle2, ExternalLink, FlaskConical, Loader, Send, XCircle } from 'lucide-react';
import { Link } from 'react-router-dom';
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import type { EvalSet, IntentLearningProposal } from '@/api/endpoints';
import { useI18n } from '@/lib/i18n-context';
import { cn } from '@/lib/utils';

interface IntentLearningProposalsProps {
    proposals: IntentLearningProposal[];
    evalSets: EvalSet[];
    evaluationPath: string;
    canEdit: boolean;
    canPublish: boolean;
    busyProposalId: string | null;
    onEvaluate: (proposalId: string, evalSetId: string, minimumScore: number) => Promise<void>;
    onPublish: (proposalId: string) => Promise<void>;
    onReject: (proposalId: string, reason: string) => Promise<void>;
}

type Confirmation = { action: 'publish' | 'reject'; proposal: IntentLearningProposal } | null;

const statusStyles: Record<IntentLearningProposal['status'], string> = {
    proposed: 'border-blue-200 bg-blue-50 text-blue-700',
    evaluating: 'border-amber-200 bg-amber-50 text-amber-700',
    evaluated: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    eval_failed: 'border-red-200 bg-red-50 text-red-700',
    published: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    rejected: 'border-slate-200 bg-slate-50 text-slate-600',
};

function ProposalDiff({ proposal }: { proposal: IntentLearningProposal }) {
    return (
        <div className="overflow-hidden rounded-md border bg-muted/30 font-mono text-[11px] leading-relaxed">
            {(proposal.operation === 'update' || proposal.operation === 'delete') && (
                <pre className="whitespace-pre-wrap border-b border-red-100 bg-red-50 px-3 py-2 text-red-800">
                    <span className="select-none text-red-500">- </span>{proposal.before_learning}
                </pre>
            )}
            {(proposal.operation === 'create' || proposal.operation === 'update') && (
                <pre className="whitespace-pre-wrap bg-emerald-50 px-3 py-2 text-emerald-800">
                    <span className="select-none text-emerald-600">+ </span>{proposal.proposed_learning}
                </pre>
            )}
        </div>
    );
}

export function IntentLearningProposals({
    proposals,
    evalSets,
    evaluationPath,
    canEdit,
    canPublish,
    busyProposalId,
    onEvaluate,
    onPublish,
    onReject,
}: IntentLearningProposalsProps) {
    const { t } = useI18n();
    const [evalSetByProposal, setEvalSetByProposal] = useState<Record<string, string>>({});
    const [minimumScoreByProposal, setMinimumScoreByProposal] = useState<Record<string, number>>({});
    const [confirmation, setConfirmation] = useState<Confirmation>(null);
    const [rejectionReason, setRejectionReason] = useState('');

    if (proposals.length === 0) {
        return (
            <div className="rounded-md border border-dashed px-3 py-4 text-center">
                <p className="text-xs font-medium">{t('No learning proposals')}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                    {t('Choose Learn this on feedback or propose a change to an active rule.')}
                </p>
            </div>
        );
    }

    const handleConfirmedAction = async () => {
        if (!confirmation || busyProposalId === confirmation.proposal.id) return;
        if (confirmation.action === 'publish') {
            await onPublish(confirmation.proposal.id);
        } else {
            await onReject(confirmation.proposal.id, rejectionReason.trim());
        }
        setConfirmation(null);
        setRejectionReason('');
    };

    return (
        <>
            <div className="space-y-2">
                {proposals.map(proposal => {
                    const isBusy = busyProposalId === proposal.id;
                    const selectedEvalSet = evalSetByProposal[proposal.id] ?? (proposal.eval_set_id || evalSets[0]?.id || '');
                    const minimumScore = minimumScoreByProposal[proposal.id] ?? Math.max(80, proposal.minimum_score || 80);
                    const rawSummary = proposal.eval_summary;
                    const summary = rawSummary && typeof rawSummary.total === 'number' && rawSummary.total > 0
                        ? rawSummary
                        : null;
                    const canEvaluate = canEdit && (proposal.status === 'proposed' || proposal.status === 'eval_failed');
                    const canApprove = proposal.status === 'evaluated' && Boolean(summary?.passed) && (summary?.failed ?? 0) === 0;
                    const canReject = ['proposed', 'evaluated', 'eval_failed'].includes(proposal.status);

                    return (
                        <Card key={proposal.id} className="shadow-none">
                            <CardHeader className="gap-2 pb-2">
                                <div className="flex flex-wrap items-start justify-between gap-2">
                                    <div className="flex flex-wrap items-center gap-1.5">
                                        <Badge variant="outline" className="text-[10px] capitalize">
                                            {t(proposal.operation)}
                                        </Badge>
                                        <Badge
                                            variant="outline"
                                            className={cn('text-[10px] capitalize', statusStyles[proposal.status])}
                                        >
                                            {proposal.status === 'evaluating' && <Loader className="mr-1 size-2.5 animate-spin" />}
                                            {t(proposal.status.replace('_', ' '))}
                                        </Badge>
                                        {proposal.affected_stages.map(stage => (
                                            <Badge key={stage} variant="secondary" className="text-[10px]">{stage}</Badge>
                                        ))}
                                    </div>
                                    <span className="text-[10px] text-muted-foreground">
                                        {new Date(proposal.updated || proposal.created).toLocaleString()}
                                    </span>
                                </div>
                                <ProposalDiff proposal={proposal} />
                            </CardHeader>

                            <CardContent className="space-y-2">
                                {summary && (
                                    <div className={cn(
                                        'flex items-start gap-2 rounded-md border px-2.5 py-2 text-xs',
                                        summary.passed && (summary.failed ?? 0) === 0
                                            ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                                            : 'border-red-200 bg-red-50 text-red-800',
                                    )}>
                                        {summary.passed && (summary.failed ?? 0) === 0
                                            ? <CheckCircle2 className="mt-0.5 size-3.5 shrink-0" />
                                            : <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />}
                                        <div>
                                            <p className="font-medium">
                                                {t('{completed}/{total} cases completed · {score}% score', {
                                                    completed: summary.completed ?? 0,
                                                    total: summary.total ?? 0,
                                                    score: summary.overallScore ?? 0,
                                                })}
                                            </p>
                                            <p className="mt-0.5 opacity-80">
                                                {t('{failed} failed · minimum {minimum}%', {
                                                    failed: summary.failed ?? 0,
                                                    minimum: summary.minimumScore ?? 0,
                                                })}
                                            </p>
                                            {summary.affectedDimension && (
                                                <p className="mt-0.5 opacity-80">
                                                    {t('{dimension} coverage: {score}% · {status}', {
                                                        dimension: summary.affectedDimension,
                                                        score: summary.affectedScore ?? 0,
                                                        status: summary.affectedCoveragePassed ? t('passed') : t('failed'),
                                                    })}
                                                </p>
                                            )}
                                        </div>
                                    </div>
                                )}

                                {proposal.error && (
                                    <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-2.5 py-2 text-xs text-red-800">
                                        <XCircle className="mt-0.5 size-3.5 shrink-0" />
                                        <span>{proposal.error}</span>
                                    </div>
                                )}

                                {proposal.status === 'rejected' && proposal.rejection_reason && (
                                    <div className="rounded-md border bg-muted/30 px-2.5 py-2 text-xs text-muted-foreground">
                                        <span className="font-medium text-foreground">{t('Rejection reason')}:</span>{' '}
                                        {proposal.rejection_reason}
                                    </div>
                                )}

                                {canEvaluate && (
                                    evalSets.length > 0 ? (
                                        <div className="grid gap-2 rounded-md border bg-muted/20 p-2 sm:grid-cols-[minmax(0,1fr)_5.5rem_auto] sm:items-end">
                                            <div className="space-y-1">
                                                <Label className="text-[10px] text-muted-foreground">{t('Evaluation set')}</Label>
                                                <Select
                                                    value={selectedEvalSet}
                                                    onValueChange={value => setEvalSetByProposal(current => ({ ...current, [proposal.id]: value }))}
                                                >
                                                    <SelectTrigger className="h-8 text-xs">
                                                        <SelectValue />
                                                    </SelectTrigger>
                                                    <SelectContent>
                                                        {evalSets.map(evalSet => (
                                                            <SelectItem key={evalSet.id} value={evalSet.id}>
                                                                {evalSet.name} ({evalSet.caseCount})
                                                            </SelectItem>
                                                        ))}
                                                    </SelectContent>
                                                </Select>
                                            </div>
                                            <div className="space-y-1">
                                                <Label className="text-[10px] text-muted-foreground">{t('Minimum %')}</Label>
                                                <Input
                                                    type="number"
                                                    min={80}
                                                    max={100}
                                                    value={minimumScore}
                                                    className="h-8 text-xs"
                                                    onChange={event => setMinimumScoreByProposal(current => ({
                                                        ...current,
                                                        [proposal.id]: Math.min(100, Math.max(80, Number(event.target.value) || 80)),
                                                    }))}
                                                />
                                            </div>
                                            <Button
                                                type="button"
                                                size="sm"
                                                className="h-8 text-xs"
                                                disabled={!selectedEvalSet || isBusy}
                                                onClick={() => void onEvaluate(proposal.id, selectedEvalSet, minimumScore)}
                                            >
                                                {isBusy ? <Loader className="size-3 animate-spin" /> : <FlaskConical className="size-3" />}
                                                {t('Run evaluation')}
                                            </Button>
                                        </div>
                                    ) : (
                                        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-2 text-xs text-amber-800">
                                            <span>{t('Create an evaluation set before testing this proposal.')}</span>
                                            <Button asChild type="button" variant="outline" size="sm" className="h-7 bg-white text-xs">
                                                <Link to={evaluationPath}>
                                                    {t('Open evaluation')} <ExternalLink className="size-3" />
                                                </Link>
                                            </Button>
                                        </div>
                                    )
                                )}

                                {canEdit && canReject && (
                                    <div className="flex flex-wrap items-center justify-end gap-1.5">
                                        {canPublish ? (
                                            <>
                                                <Button
                                                    type="button"
                                                    variant="outline"
                                                    size="sm"
                                                    className="h-7 text-xs"
                                                    disabled={isBusy}
                                                    onClick={() => setConfirmation({ action: 'reject', proposal })}
                                                >
                                                    {t('Reject')}
                                                </Button>
                                                <Button
                                                    type="button"
                                                    size="sm"
                                                    className="h-7 text-xs"
                                                    disabled={!canApprove || isBusy}
                                                    onClick={() => setConfirmation({ action: 'publish', proposal })}
                                                >
                                                    {isBusy ? <Loader className="size-3 animate-spin" /> : <Send className="size-3" />}
                                                    {t('Publish learning')}
                                                </Button>
                                            </>
                                        ) : (
                                            <span className="text-[10px] text-muted-foreground">
                                                {t('Project admin approval required to publish or reject.')}
                                            </span>
                                        )}
                                    </div>
                                )}
                            </CardContent>
                        </Card>
                    );
                })}
            </div>

            <AlertDialog
                open={confirmation !== null}
                onOpenChange={open => {
                    if (!open) {
                        setConfirmation(null);
                        setRejectionReason('');
                    }
                }}
            >
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>
                            {confirmation?.action === 'publish' ? t('Publish learning?') : t('Reject learning proposal?')}
                        </AlertDialogTitle>
                        <AlertDialogDescription>
                            {confirmation?.action === 'publish'
                                ? t('Publishing changes live agent behavior for this runbook. The evaluated diff must still match production.')
                                : t('Rejection keeps live agent behavior unchanged.')}
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    {confirmation?.action === 'reject' && (
                        <div className="space-y-1.5">
                            <Label htmlFor="learning-rejection-reason">{t('Reason (optional)')}</Label>
                            <Textarea
                                id="learning-rejection-reason"
                                value={rejectionReason}
                                onChange={event => setRejectionReason(event.target.value)}
                                rows={3}
                                placeholder={t('Explain why this proposal should not be published')}
                            />
                        </div>
                    )}
                    <AlertDialogFooter>
                        <AlertDialogCancel>{t('Cancel')}</AlertDialogCancel>
                        <AlertDialogAction
                            variant={confirmation?.action === 'reject' ? 'destructive' : 'default'}
                            disabled={Boolean(confirmation && busyProposalId === confirmation.proposal.id)}
                            onClick={event => {
                                event.preventDefault();
                                void handleConfirmedAction();
                            }}
                        >
                            {confirmation && busyProposalId === confirmation.proposal.id && (
                                <Loader className="size-3 animate-spin" />
                            )}
                            {confirmation?.action === 'publish' ? t('Publish') : t('Reject')}
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </>
    );
}
