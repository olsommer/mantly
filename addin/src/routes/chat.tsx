import { useEmailAutomation } from '@/hooks/use-email-automation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { AlertTriangle, CheckCircle2, ExternalLink, Loader, RefreshCw, Send, UserCheck } from 'lucide-react';
import type { EmailResponse, Message } from '@/models/email';
import { EmailMessage } from '@/components/messages/email';
import { StaticActionsPanel } from '@/components/pipeline/StaticActionsPanel';
import { ResponsePanel } from '@/components/pipeline/ResponsePanel';
import { FeedbackBar } from '@/components/pipeline/FeedbackBar';
import { AddinUserMenu } from '@/components/pipeline/AddinUserMenu';
import { AddinProjectSelector } from '@/components/pipeline/AddinProjectSelector';
import { SecurityRiskBanner } from '@/components/pipeline/SecurityRiskBanner';
import { useParams } from 'react-router-dom';
import { t } from '@/lib/i18n';
import { useProjectSelection } from '@/hooks/use-project-selection';
import { api } from '@/api/endpoints';
import type { SupportIssueSummary } from '@/api/endpoints';
import { settings } from '@/settings';
import { toast } from 'sonner';

const decodeJwtPayload = (token: string | null): Record<string, unknown> | null => {
    if (!token) return null;
    try {
        const [, payload] = token.split('.');
        if (!payload) return null;
        const normalized = payload.replace(/-/g, '+').replace(/_/g, '/');
        const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=');
        return JSON.parse(window.atob(padded)) as Record<string, unknown>;
    } catch {
        return null;
    }
};

const readTenantId = () => {
    const payload = decodeJwtPayload(localStorage.getItem('auth_token') || localStorage.getItem('admin_auth_token'));
    return typeof payload?.tenant_id === 'string' ? payload.tenant_id : '';
};

const readUserEmail = () => {
    const payload = decodeJwtPayload(localStorage.getItem('auth_token') || localStorage.getItem('admin_auth_token'));
    const payloadEmail = typeof payload?.email === 'string' ? payload.email.trim() : '';
    return payloadEmail || localStorage.getItem('auth_email')?.trim() || '';
};

const openExternal = (url: string) => {
    if (typeof Office !== 'undefined' && Office.context?.ui?.openBrowserWindow) {
        Office.context.ui.openBrowserWindow(url);
        return;
    }
    window.open(url, '_blank', 'noopener,noreferrer');
};

const labelForStatus = (status: string | undefined) => {
    if (status === 'ongoing' || status === 'pending' || status === 'triaged') return t('ticket.statusOngoing');
    if (status === 'done' || status === 'closed') return t('ticket.statusDone');
    return t('ticket.statusOpen');
};

const labelForPriority = (priority: string | undefined) => {
    if (priority === 'urgent') return t('ticket.priorityUrgent');
    if (priority === 'high') return t('ticket.priorityHigh');
    if (priority === 'low') return t('ticket.priorityLow');
    return t('ticket.priorityNormal');
};

const compactValue = (value: string | undefined) => {
    const text = value?.trim();
    return text || '-';
};

type TicketNextActionKind =
    | 'open_create'
    | 'failed_delivery'
    | 'approval'
    | 'assign_owner'
    | 'queue_reply'
    | 'overdue_sla'
    | 'reply_needed'
    | 'pending_delivery'
    | 'ready_to_close'
    | 'clear';

interface TicketNextAction {
    kind: TicketNextActionKind;
    titleKey: string;
    detailKey: string;
    detailValues?: Record<string, string | number>;
    tone: 'default' | 'warning' | 'danger';
}

const countLabelValue = (count: number) => Math.max(count, 1);

const issueHasCustomerWaiting = (issue: SupportIssueSummary) => {
    if (issue.needsResponse === true) return true;
    if (issue.needsResponse === false) return false;
    return issue.latestMessageDirection === 'customer' || issue.latestMessageDirection === 'visitor';
};

const issueCanBeClosedFromAddin = (
    issue: SupportIssueSummary,
    failedDeliveries: number,
    pendingApprovals: number,
    pendingDeliveries: number,
) => {
    const status = issue.workflowStatus || issue.status;
    return status !== 'done'
        && status !== 'closed'
        && !issueHasCustomerWaiting(issue)
        && !issue.hasOverdueSla
        && failedDeliveries === 0
        && pendingApprovals === 0
        && pendingDeliveries === 0
        && Boolean(issue.assigneeEmail?.trim());
};

const Chat = () => {
    const { id } = useParams<{ id: string }>();
    const chatId = useMemo(() => {
        if (!id) return undefined;
        try {
            return decodeURIComponent(id);
        } catch {
            return id;
        }
    }, [id]);
    const { isLoading, error, chat, loadChat } = useEmailAutomation();
    const { selectedProjectId } = useProjectSelection();

    const [messages, setMessages] = useState<Message[]>([]);
    const [issue, setIssue] = useState<SupportIssueSummary | null>(null);
    const [issueLoading, setIssueLoading] = useState(false);
    const [issueActionLoading, setIssueActionLoading] = useState(false);
    const [approvalAction, setApprovalAction] = useState<'' | 'approve' | 'send'>('');
    const [requestingChanges, setRequestingChanges] = useState(false);
    const [changeRequestNote, setChangeRequestNote] = useState('');
    const [retryingDelivery, setRetryingDelivery] = useState(false);
    const [claimingIssue, setClaimingIssue] = useState(false);
    const [queueingIssueReply, setQueueingIssueReply] = useState(false);
    const [includeFeedbackLink, setIncludeFeedbackLink] = useState(true);
    const [closingIssue, setClosingIssue] = useState(false);
    const loadChatRef = useRef(loadChat);

    useEffect(() => {
        loadChatRef.current = loadChat;
    }, [loadChat]);

    // Find the latest response message to extract ticket preparation results for the side panel.
    const latestResponse = useMemo(() => {
        for (let i = messages.length - 1; i >= 0; i--) {
            if (messages[i].user === 'response') return messages[i];
        }
        return null;
    }, [messages]);

    const latestContent = latestResponse?.content as EmailResponse | undefined;
    const [draftResponseContent, setDraftResponseContent] = useState<EmailResponse | null>(latestContent ?? null);
    const identityResult = latestContent?.identityResult;
    const intentResult = latestContent?.intentResult;
    const phishingResult = latestContent?.phishingResult;
    const promptInjectionResult = latestContent?.promptInjectionResult;
    const requiresHuman = latestContent?.requiresHuman ?? false;
    const responseEnabled = intentResult?.response?.enabled ?? false;
    const showActionsPanel = !!identityResult || !!intentResult;

    const [responseRevealed, setResponseRevealed] = useState(true);

    // Reset responseRevealed when latest response changes.
    const responseAutoValue = intentResult?.response?.auto;
    useEffect(() => {
        const timer = window.setTimeout(() => {
            setResponseRevealed(responseAutoValue !== false);
        }, 0);
        return () => window.clearTimeout(timer);
    }, [latestResponse, responseAutoValue]);

    useEffect(() => {
        setDraftResponseContent(latestContent ?? null);
    }, [latestResponse, latestContent]);

    // Load the email thread context that backs the ticket surface.
    useEffect(() => {
        if (chatId) {
            void loadChatRef.current(chatId);
        }
    }, [chatId]);

    // Keep the ticket surface in sync with the latest thread messages.
    useEffect(() => {
        if (chat) {
            const timer = window.setTimeout(() => {
                setMessages(chat);
            }, 0);
            return () => window.clearTimeout(timer);
        }
    }, [chat]);

    const loadIssueSummary = useCallback(async (options?: { showLoading?: boolean; commit?: boolean }) => {
        if (!chatId || !selectedProjectId) return null;
        if (options?.showLoading) setIssueLoading(true);
        try {
            const response = await api.getIssueByChat(selectedProjectId, chatId);
            const nextIssue = response.data ?? null;
            if (options?.commit !== false) setIssue(nextIssue);
            return nextIssue;
        } finally {
            if (options?.showLoading) setIssueLoading(false);
        }
    }, [chatId, selectedProjectId]);

    useEffect(() => {
        if (!chat || !chatId || !selectedProjectId) {
            const resetTimer = window.setTimeout(() => {
                setIssue(null);
                setIssueLoading(false);
            }, 0);
            return () => window.clearTimeout(resetTimer);
        }

        let cancelled = false;
        const lookupTimer = window.setTimeout(() => {
            setIssueLoading(true);
            void loadIssueSummary({ commit: false }).then(nextIssue => {
                if (!cancelled) {
                    setIssue(nextIssue);
                }
            }).finally(() => {
                if (!cancelled) setIssueLoading(false);
            });
        }, 0);

        return () => {
            cancelled = true;
            window.clearTimeout(lookupTimer);
        };
    }, [chat, chatId, loadIssueSummary, selectedProjectId]);

    if (isLoading) {
        return (
            <div className="flex items-center justify-center min-h-screen">
                <Button disabled variant={"outline"}>
                    <Loader className='size-4 animate-spin' /> {t('chat.loading')}
                </Button>
            </div>
        );
    }

    if (error) {
        return (
            <div className="flex items-center justify-center min-h-screen">
                <div className="text-center p-8 max-w-md">
                    <div className="text-red-600 text-5xl mb-4">❌</div>
                    <h2 className="text-2xl font-bold mb-2 text-red-600">{t('chat.error')}</h2>
                    <p className="text-gray-600">{typeof error === 'string' ? error : t('chat.error')}</p>
                </div>
            </div>
        );
    }

    if (!chat) {
        return (
            <div className="flex items-center justify-center min-h-screen">
                <div className="text-center p-8 max-w-md">
                    <p className="text-gray-600">{t('chat.noChat')}</p>
                </div>
            </div>
        );
    }

    const shouldShowResponse = Boolean(latestResponse && (
        requiresHuman
        || !showActionsPanel
        || responseEnabled && responseRevealed
    ));
    const tenantId = readTenantId();
    const issueUrlFor = (nextIssue: SupportIssueSummary | null) => (
        tenantId && selectedProjectId && nextIssue
            ? `${settings.adminBaseUrl.replace(/\/+$/, '')}/${tenantId}/${selectedProjectId}/inbox/${nextIssue.id}`
            : ''
    );
    const issueUrl = issueUrlFor(issue);
    const workflowStatus = issue?.workflowStatus || issue?.status;
    const requester = compactValue(issue?.accountName || issue?.contactEmail || issue?.fromAddress);
    const signedInEmail = readUserEmail();
    const issueAssignee = issue?.assigneeEmail?.trim() || '';
    const assignee = compactValue(issueAssignee);
    const pendingApprovals = issue?.pendingApprovalCount ?? 0;
    const failedDeliveries = issue?.failedDeliveryCount ?? (issue?.hasFailedDelivery ? 1 : 0);
    const pendingDeliveries = issue?.pendingDeliveryCount ?? (issue?.hasPendingDelivery ? 1 : 0);
    const canClaimIssue = Boolean(issue && selectedProjectId && signedInEmail && !issueAssignee);
    const draftReplyBody = (draftResponseContent?.emailBody || latestContent?.emailBody || '').trim();
    const canQueueIssueReply = Boolean(issue && selectedProjectId && draftReplyBody && !issue.hasPendingApproval);
    const canMarkDone = Boolean(issue && selectedProjectId && issueCanBeClosedFromAddin(issue, failedDeliveries, pendingApprovals, pendingDeliveries));
    const nextAction: TicketNextAction = !issue
        ? {
            kind: 'open_create',
            titleKey: 'ticket.nextOpenCreate',
            detailKey: 'ticket.nextOpenCreateDetail',
            tone: 'default',
        }
        : failedDeliveries > 0
            ? {
                kind: 'failed_delivery',
                titleKey: 'ticket.nextFixDelivery',
                detailKey: 'ticket.nextFixDeliveryDetail',
                detailValues: { count: countLabelValue(failedDeliveries) },
                tone: 'danger',
            }
            : pendingApprovals > 0
                ? {
                    kind: 'approval',
                    titleKey: 'ticket.nextReviewApproval',
                    detailKey: 'ticket.nextReviewApprovalDetail',
                    detailValues: { count: countLabelValue(pendingApprovals) },
                    tone: 'warning',
                }
                : canClaimIssue
                    ? {
                        kind: 'assign_owner',
                        titleKey: 'ticket.nextAssign',
                        detailKey: 'ticket.nextAssignDetail',
                        tone: 'default',
                    }
                    : canQueueIssueReply
                        ? {
                            kind: 'queue_reply',
                            titleKey: 'ticket.nextQueueReply',
                            detailKey: 'ticket.nextQueueReplyDetail',
                            tone: 'warning',
                        }
                        : issue.hasOverdueSla
                            ? {
                                kind: 'overdue_sla',
                                titleKey: 'ticket.nextOverdueSla',
                                detailKey: 'ticket.nextOverdueSlaDetail',
                                tone: 'danger',
                            }
                            : issueHasCustomerWaiting(issue)
                                ? {
                                    kind: 'reply_needed',
                                    titleKey: 'ticket.nextReply',
                                    detailKey: 'ticket.nextReplyDetail',
                                    tone: 'warning',
                                }
                                : pendingDeliveries > 0
                                    ? {
                                        kind: 'pending_delivery',
                                        titleKey: 'ticket.nextMonitorDelivery',
                                        detailKey: 'ticket.nextMonitorDeliveryDetail',
                                        detailValues: { count: countLabelValue(pendingDeliveries) },
                                        tone: 'default',
                                    }
                                    : canMarkDone
                                        ? {
                                            kind: 'ready_to_close',
                                            titleKey: 'ticket.nextClose',
                                            detailKey: 'ticket.nextCloseDetail',
                                            tone: 'default',
                                        }
                                        : {
                                            kind: 'clear',
                                            titleKey: 'ticket.nextClear',
                                            detailKey: 'ticket.nextClearDetail',
                                            tone: 'default',
                                        };
    const nextActionToneClass = nextAction.tone === 'danger'
        ? 'border-red-200 bg-red-50 text-red-900'
        : nextAction.tone === 'warning'
            ? 'border-amber-200 bg-amber-50 text-amber-900'
            : 'border-gray-200 bg-gray-50 text-gray-900';
    const nextActionDetailToneClass = nextAction.tone === 'danger'
        ? 'text-red-700'
        : nextAction.tone === 'warning'
            ? 'text-amber-700'
            : 'text-gray-600';
    const openOrCreateIssue = async () => {
        if (issueUrl) {
            openExternal(issueUrl);
            return;
        }
        if (!chatId || !selectedProjectId || issueActionLoading) return;
        setIssueActionLoading(true);
        const nextIssue = await loadIssueSummary({ showLoading: true });
        setIssueActionLoading(false);
        const nextUrl = issueUrlFor(nextIssue);
        if (nextUrl) {
            openExternal(nextUrl);
            return;
        }
        if (nextIssue) {
            toast.success(t('ticket.createSuccess'));
            return;
        }
        toast.error(t('ticket.openCreateError'));
    };
    const claimIssue = async () => {
        if (!selectedProjectId || !issue || !signedInEmail || claimingIssue) return;
        setClaimingIssue(true);
        const response = await api.updateIssue(selectedProjectId, issue.id, {
            assigneeEmail: signedInEmail,
            workflowSource: 'addin_ticket_claim',
        });
        setClaimingIssue(false);
        if (response.error || !response.data) {
            toast.error(response.error || t('ticket.claimError'));
            return;
        }
        setIssue(response.data);
        toast.success(t('ticket.claimSuccess'));
    };
    const queueIssueReply = async () => {
        if (!selectedProjectId || !issue || !draftReplyBody || queueingIssueReply) return;
        const draftAttachments = (draftResponseContent?.emailAttachments || latestContent?.emailAttachments || [])
            .map(attachment => ({
                filename: attachment.filename,
                base64: attachment.base64,
                ...(attachment.contentType ? { contentType: attachment.contentType } : {}),
            }));
        setQueueingIssueReply(true);
        const response = await api.createIssueReply(
            selectedProjectId,
            issue.id,
            draftReplyBody,
            'queued',
            true,
            includeFeedbackLink,
            draftAttachments,
        );
        setQueueingIssueReply(false);
        if (response.error || !response.data) {
            toast.error(response.error || t('ticket.queueReplyError'));
            return;
        }
        await loadIssueSummary();
        toast.success(t('ticket.queueReplySuccess'));
    };
    const runApprovalAction = async (mode: 'approve' | 'send') => {
        if (!selectedProjectId || !issue || approvalAction || requestingChanges) return;
        setApprovalAction(mode);
        const response = mode === 'send'
            ? await api.bulkApproveSendIssueReplies(selectedProjectId, [issue.id])
            : await api.bulkApproveIssueReplies(selectedProjectId, [issue.id]);
        setApprovalAction('');
        if (response.error || !response.data) {
            toast.error(response.error || t('ticket.approveError'));
            return;
        }
        const refreshed = response.data.issues.find(item => item.id === issue.id);
        if (refreshed) {
            setIssue(refreshed);
        } else {
            await loadIssueSummary();
        }
        if (response.data.failed.length > 0) {
            toast.error(response.data.failed[0]?.error || t('ticket.approveError'));
            return;
        }
        toast.success(mode === 'send' ? t('ticket.sendSuccess') : t('ticket.approveSuccess'));
    };
    const requestReplyChanges = async () => {
        if (!selectedProjectId || !issue || requestingChanges || approvalAction) return;
        setRequestingChanges(true);
        const reviewNote = changeRequestNote.trim() || t('ticket.requestChangesDefaultNote');
        const response = await api.bulkRequestIssueReplyChanges(selectedProjectId, [issue.id], reviewNote);
        setRequestingChanges(false);
        if (response.error || !response.data) {
            toast.error(response.error || t('ticket.requestChangesError'));
            return;
        }
        const refreshed = response.data.issues.find(item => item.id === issue.id);
        if (refreshed) {
            setIssue(refreshed);
        } else {
            await loadIssueSummary();
        }
        if (response.data.failed.length > 0) {
            toast.error(response.data.failed[0]?.error || t('ticket.requestChangesError'));
            return;
        }
        setChangeRequestNote('');
        toast.success(t('ticket.requestChangesSuccess'));
    };
    const retryFailedDelivery = async () => {
        if (!selectedProjectId || !issue || retryingDelivery) return;
        setRetryingDelivery(true);
        const response = await api.bulkRetryFailedIssueReplies(selectedProjectId, [issue.id]);
        setRetryingDelivery(false);
        if (response.error || !response.data) {
            toast.error(response.error || t('ticket.retryDeliveryError'));
            return;
        }
        const refreshed = response.data.issues.find(item => item.id === issue.id);
        if (refreshed) {
            setIssue(refreshed);
        } else {
            await loadIssueSummary();
        }
        if (response.data.failed.length > 0) {
            toast.error(response.data.failed[0]?.error || t('ticket.retryDeliveryError'));
            return;
        }
        toast.success(t('ticket.retryDeliverySuccess'));
    };
    const markIssueDone = async () => {
        if (!selectedProjectId || !issue || closingIssue || !canMarkDone) return;
        setClosingIssue(true);
        const response = await api.updateIssue(selectedProjectId, issue.id, {
            status: 'done',
            workflowSource: 'addin_ticket_done',
        });
        setClosingIssue(false);
        if (response.error || !response.data) {
            toast.error(response.error || t('ticket.markDoneError'));
            return;
        }
        setIssue(response.data);
        toast.success(t('ticket.markDoneSuccess'));
    };

    return (
        <div className="h-screen flex flex-col">
            <SecurityRiskBanner
                phishingResult={phishingResult}
                promptInjectionResult={promptInjectionResult}
            />
            {showActionsPanel && (
                <StaticActionsPanel
                    identityResult={identityResult}
                    intentResult={intentResult}
                    chatId={chatId ?? ''}
                    projectId={selectedProjectId}
                    responseRevealed={responseRevealed}
                    onRevealResponse={() => setResponseRevealed(true)}
                />
            )}

            <div className="flex flex-1 overflow-y-auto">
                {shouldShowResponse && latestResponse ? (
                    <ResponsePanel>
                        <div className={requiresHuman ? "flex min-h-full flex-1 overflow-y-auto" : "flex min-h-0 flex-1 flex-col"}>
                            <EmailMessage
                                message={latestResponse}
                                index={messages.indexOf(latestResponse)}
                                isNewChat
                                chatId={chatId}
                                onResponseChange={setDraftResponseContent}
                            />
                        </div>
                    </ResponsePanel>
                ) : null}
            </div>
            <div className="shrink-0 border-t bg-white px-2 py-2">
                <div className="mb-2 space-y-2">
                    <div className="min-w-0 space-y-1">
                        <div className="truncate text-xs font-medium text-gray-900">
                            {issue ? issue.subject || t('ticket.issue') : t('ticket.issue')}
                        </div>
                        <div
                            data-ticket-next-action
                            data-ticket-next-action-kind={nextAction.kind}
                            className={`rounded border px-2 py-1.5 ${nextActionToneClass}`}
                        >
                            <div className="mb-0.5 text-[10px] font-semibold uppercase">
                                {t('ticket.nextAction')}
                            </div>
                            <div className="text-xs font-semibold">{t(nextAction.titleKey)}</div>
                            <div className={`break-words text-[11px] ${nextActionDetailToneClass}`}>
                                {t(nextAction.detailKey, nextAction.detailValues)}
                            </div>
                        </div>
                        <div className="grid min-w-0 gap-1 text-[11px] text-gray-600">
                            {issueLoading ? (
                                <span className="inline-flex items-center gap-1">
                                    <Loader className="size-3 animate-spin" />
                                    {t('ticket.loading')}
                                </span>
                            ) : issue ? (
                                <>
                                    <div className="flex flex-wrap items-center gap-1">
                                        <span className="rounded border px-1.5 py-0.5">{labelForStatus(workflowStatus)}</span>
                                        <span className="rounded border px-1.5 py-0.5">{labelForPriority(issue.priority)}</span>
                                    </div>
                                    <div className="grid gap-0.5">
                                        <span className="break-all">{t('ticket.assignee')}: {assignee}</span>
                                        <span className="break-all">{t('ticket.requester')}: {requester}</span>
                                    </div>
                                    {canClaimIssue && (
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            className="h-7 w-fit gap-1 px-2 text-[11px]"
                                            disabled={claimingIssue}
                                            onClick={() => void claimIssue()}
                                        >
                                            {claimingIssue
                                                ? <Loader className="size-3 animate-spin" />
                                                : <UserCheck className="size-3" />}
                                            <span>{t('ticket.claim')}</span>
                                        </Button>
                                    )}
                                    {canQueueIssueReply && (
                                        <div className="flex flex-wrap items-center gap-1.5">
                                            <Label
                                                htmlFor="ticket-include-feedback-link"
                                                className="flex h-7 w-fit items-center gap-1.5 rounded border bg-white px-2 text-[11px] font-normal text-gray-700"
                                            >
                                                <Checkbox
                                                    id="ticket-include-feedback-link"
                                                    checked={includeFeedbackLink}
                                                    onCheckedChange={checked => setIncludeFeedbackLink(checked === true)}
                                                    className="size-3.5"
                                                />
                                                <span>{t('ticket.csatLink')}</span>
                                            </Label>
                                            <Button
                                                type="button"
                                                size="sm"
                                                className="h-7 w-fit min-w-0 gap-1 px-2 text-[11px]"
                                                disabled={queueingIssueReply}
                                                onClick={() => void queueIssueReply()}
                                            >
                                                {queueingIssueReply
                                                    ? <Loader className="size-3 animate-spin" />
                                                    : <Send className="size-3" />}
                                                <span className="truncate">{t('ticket.queueReply')}</span>
                                            </Button>
                                        </div>
                                    )}
                                    {issue.hasPendingApproval && (
                                        <span className="w-fit rounded border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-amber-800">
                                            {t('ticket.pendingApproval', { count: pendingApprovals })}
                                        </span>
                                    )}
                                    {pendingDeliveries > 0 && (
                                        <span className="w-fit rounded border border-sky-300 bg-sky-50 px-1.5 py-0.5 text-sky-800">
                                            {t('ticket.pendingDelivery', { count: pendingDeliveries })}
                                        </span>
                                    )}
                                    {failedDeliveries > 0 && (
                                        <span className="inline-flex w-fit items-center gap-1 rounded border border-red-300 bg-red-50 px-1.5 py-0.5 text-red-700">
                                            <AlertTriangle className="size-3" />
                                            {t('ticket.failedDelivery', { count: failedDeliveries })}
                                        </span>
                                    )}
                                    {failedDeliveries > 0 && (
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            className="h-7 w-fit min-w-0 gap-1 px-2 text-[11px]"
                                            disabled={retryingDelivery || !selectedProjectId}
                                            onClick={() => void retryFailedDelivery()}
                                        >
                                            {retryingDelivery
                                                ? <Loader className="size-3 animate-spin" />
                                                : <RefreshCw className="size-3" />}
                                            <span className="truncate">{t('ticket.retryDelivery')}</span>
                                        </Button>
                                    )}
                                    {canMarkDone && (
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            className="h-7 w-fit min-w-0 gap-1 px-2 text-[11px]"
                                            disabled={closingIssue || !selectedProjectId}
                                            onClick={() => void markIssueDone()}
                                        >
                                            {closingIssue
                                                ? <Loader className="size-3 animate-spin" />
                                                : <CheckCircle2 className="size-3" />}
                                            <span className="truncate">{t('ticket.markDone')}</span>
                                        </Button>
                                    )}
                                    {issue.hasPendingApproval && (
                                        <div className="mt-1 space-y-1.5">
                                            <Textarea
                                                value={changeRequestNote}
                                                onChange={event => setChangeRequestNote(event.target.value)}
                                                rows={2}
                                                className="min-h-14 text-[11px]"
                                                placeholder={t('ticket.requestChangesPlaceholder')}
                                            />
                                            <div className="grid grid-cols-2 gap-1.5">
                                                <Button
                                                    type="button"
                                                    size="sm"
                                                    variant="outline"
                                                    className="col-span-2 h-7 min-w-0 gap-1 px-2 text-[11px]"
                                                    disabled={Boolean(approvalAction) || requestingChanges || !selectedProjectId}
                                                    onClick={() => void requestReplyChanges()}
                                                >
                                                    {requestingChanges
                                                        ? <Loader className="size-3 animate-spin" />
                                                        : <AlertTriangle className="size-3" />}
                                                    <span className="truncate">{t('ticket.requestChanges')}</span>
                                                </Button>
                                                <Button
                                                    type="button"
                                                    size="sm"
                                                    variant="outline"
                                                    className="h-7 min-w-0 gap-1 px-2 text-[11px]"
                                                    disabled={Boolean(approvalAction) || requestingChanges || !selectedProjectId}
                                                    onClick={() => void runApprovalAction('approve')}
                                                >
                                                    {approvalAction === 'approve'
                                                        ? <Loader className="size-3 animate-spin" />
                                                        : <CheckCircle2 className="size-3" />}
                                                    <span className="truncate">{t('ticket.approve')}</span>
                                                </Button>
                                                <Button
                                                    type="button"
                                                    size="sm"
                                                    className="h-7 min-w-0 gap-1 px-2 text-[11px]"
                                                    disabled={Boolean(approvalAction) || requestingChanges || !selectedProjectId}
                                                    onClick={() => void runApprovalAction('send')}
                                                >
                                                    {approvalAction === 'send'
                                                        ? <Loader className="size-3 animate-spin" />
                                                        : <Send className="size-3" />}
                                                    <span className="truncate">{t('ticket.approveSend')}</span>
                                                </Button>
                                            </div>
                                        </div>
                                    )}
                                </>
                            ) : (
                                <span>{t('ticket.notLinked')}</span>
                            )}
                        </div>
                    </div>
                    <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-7 w-full gap-1.5 px-2 text-xs"
                        disabled={issueLoading || issueActionLoading || !selectedProjectId || (!issue && !chatId)}
                        onClick={() => void openOrCreateIssue()}
                    >
                        {issueLoading || issueActionLoading
                            ? <Loader className="size-3.5 animate-spin" />
                            : <ExternalLink className="size-3.5" />}
                        {issue ? t('pipeline.openIssue') : t('pipeline.openCreateIssue')}
                    </Button>
                </div>
                <div className="flex items-center justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-2">
                        {showActionsPanel && (
                            <FeedbackBar
                                projectId={selectedProjectId ?? ''}
                                chatId={chatId ?? ''}
                                identityResult={identityResult}
                                intentResult={intentResult}
                            />
                        )}
                    </div>
                    <div className="flex min-w-0 items-center gap-2">
                        <AddinProjectSelector />
                        <AddinUserMenu />
                    </div>
                </div>
            </div>
        </div >
    );
};

export { Chat };
