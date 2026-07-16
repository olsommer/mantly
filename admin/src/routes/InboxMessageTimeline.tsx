import { Loader, Scissors } from 'lucide-react';

import type { SupportIssueMessage } from '@/api/endpoints';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { InboxAttachments } from './InboxAttachments';

type TranslateFn = (key: string, params?: Record<string, string | number>) => string;

type InboxMessageTimelineProps = {
    messages: SupportIssueMessage[];
    variant?: 'compact' | 'full';
    splittingMessageId: string;
    t: TranslateFn;
    onSplitMessage: (message: SupportIssueMessage) => void;
};

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function textFrom(value: unknown): string {
    if (typeof value === 'string') return value.trim();
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
    return '';
}

function messageText(message: SupportIssueMessage): string {
    if (message.body) return message.body;
    if (typeof message.content === 'string') return message.content;
    if (isRecord(message.content)) {
        const body = textFrom(message.content.emailBody) || textFrom(message.content.email_body);
        if (body) return body;
    }
    return '';
}

function messagePlaceholder(message: SupportIssueMessage, t: TranslateFn): string {
    if (message.direction === 'ai' || message.user === 'response') {
        return t('No customer-facing draft was produced.');
    }
    return t('No message text available.');
}

function messageLabel(message: SupportIssueMessage) {
    if (message.direction === 'ai' || message.user === 'response') return 'AI draft';
    if (message.direction === 'customer' || message.user === 'email') return 'Customer email';
    if (message.direction === 'agent') return 'Agent reply';
    return 'Internal note';
}

function messageKey(message: SupportIssueMessage, index: number) {
    return message.id || message.sourceMessageId || `${message.user || message.direction || 'message'}-${index}`;
}

function messageIdentifier(message: SupportIssueMessage): string {
    return message.id || message.sourceMessageId || '';
}

function canSplitTimelineMessage(message: SupportIssueMessage, totalMessages: number): boolean {
    if (totalMessages <= 1 || !messageIdentifier(message)) return false;
    const direction = (message.direction || message.user || '').toLowerCase();
    const kind = (message.messageKind || message.role || '').toLowerCase();
    return direction !== 'ai' && direction !== 'response' && !kind.includes('outbound');
}

function attachmentItems(message: SupportIssueMessage): unknown[] {
    if (Array.isArray(message.attachments) && message.attachments.length > 0) return message.attachments;
    if (isRecord(message.content)) {
        const raw = message.content.emailAttachments ?? message.content.email_attachments;
        return Array.isArray(raw) ? raw : [];
    }
    return [];
}

export function InboxMessageTimeline({
    messages,
    variant = 'full',
    splittingMessageId,
    t,
    onSplitMessage,
}: InboxMessageTimelineProps) {
    const compact = variant === 'compact';
    return (
        <section className={compact ? 'rounded-md border p-3' : 'space-y-3'}>
            <div className={`${compact ? 'mb-3' : ''} flex items-center justify-between gap-2`}>
                {compact ? (
                    <div className="text-sm font-medium">{t('Message timeline')}</div>
                ) : (
                    <h2 className="text-sm font-medium">{t('Message timeline')}</h2>
                )}
                <Badge variant="outline" className="font-normal">
                    {compact ? messages.length : `${messages.length} ${t('messages')}`}
                </Badge>
            </div>
            {messages.length === 0 ? (
                <div className={compact ? 'text-sm text-muted-foreground' : 'rounded-md border p-4 text-sm text-muted-foreground'}>
                    {compact ? '-' : t('No messages')}
                </div>
            ) : (
                <div className={compact ? 'space-y-2' : 'contents'}>
                    {messages.map((message, index) => (
                        <div key={messageKey(message, index)} className={`rounded-md border ${compact ? 'bg-muted/20 p-2' : 'p-4'}`}>
                            <div className={`${compact ? 'mb-1' : 'mb-2'} flex items-center justify-between gap-3`}>
                                <div className={compact ? 'text-xs font-medium' : 'text-sm font-medium'}>
                                    {t(messageLabel(message))}
                                </div>
                                <div className="flex shrink-0 items-center gap-1.5">
                                    <Badge variant="outline" className="font-normal">
                                        {message.messageKind || message.role || message.direction || 'message'}
                                    </Badge>
                                    {canSplitTimelineMessage(message, messages.length) && (
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="ghost"
                                            className="h-7 px-2"
                                            data-ticket-split-message={messageIdentifier(message)}
                                            onClick={() => onSplitMessage(message)}
                                            disabled={Boolean(splittingMessageId)}
                                        >
                                            {splittingMessageId === messageIdentifier(message)
                                                ? <Loader className="size-3.5 animate-spin" />
                                                : <Scissors className="size-3.5" />}
                                            {t('Split')}
                                        </Button>
                                    )}
                                </div>
                            </div>
                            <pre className={`${compact ? 'max-h-32' : 'max-h-80'} overflow-auto whitespace-pre-wrap text-sm leading-6 text-muted-foreground`}>
                                {messageText(message) || messagePlaceholder(message, t)}
                            </pre>
                            <InboxAttachments attachments={attachmentItems(message)} t={t} />
                        </div>
                    ))}
                </div>
            )}
        </section>
    );
}
