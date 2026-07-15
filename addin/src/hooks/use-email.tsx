import type { Email } from '@/models/email';
import { useState, useEffect } from 'react';
import { useOffice } from '@/hooks/use-office';
import { useDemo } from '@/hooks/use-demo';
import { t } from '@/lib/i18n';

interface BodyAsyncResult {
    status: Office.AsyncResultStatus;
    value: string;
    error?: unknown;
}

interface AttachmentContentAsyncResult {
    status: Office.AsyncResultStatus;
    value: { content: string };
    error?: unknown;
}

interface AttachmentLike {
    id: string;
    name: string;
    attachmentType: string;
}

interface MailboxItemLike {
    itemId?: string;
    conversationId?: string;
    internetMessageId?: string;
    subject?: string;
    from?: { emailAddress?: string };
    body: {
        getAsync: (coercionType: string, callback: (result: BodyAsyncResult) => void) => void;
    };
    attachments?: AttachmentLike[];
    getAttachmentContentAsync: (
        id: string,
        callback: (result: AttachmentContentAsyncResult) => void,
    ) => void;
}

const useEmail = () => {
    const [officeEmail, setOfficeEmail] = useState<Email | null>(null);
    const { isOfficeReady } = useOffice();
    const { isDemoMode, demoEmail } = useDemo();

    useEffect(() => {
        if (!isOfficeReady) {
            return;
        }

        if (isDemoMode && demoEmail) {
            return;
        }

        if (typeof Office === 'undefined') {
            return;
        }

        const item = Office.context?.mailbox?.item as MailboxItemLike | undefined;

        if (!item) {
            // No item selected — this is normal in embed/preview mode.
            // The embed route manages its own email data via postMessage.
            return;
        }

        // Get email properties
        const email: Email = {
            id: item.itemId || 'current-item',
            threadId: item.conversationId || undefined,
            messageId: item.itemId || undefined,
            internetMessageId: item.internetMessageId || undefined,
            subject: item.subject || t('misc.noSubject'),
            fromAddress: item.from?.emailAddress || '',
            body: '', // Will be loaded asynchronously
            attachments: [], // Will be loaded asynchronously
        };

        let bodyLoaded = false;
        let attachmentsLoaded = false;

        const checkAndSetEmail = () => {
            if (bodyLoaded && attachmentsLoaded) {
                setOfficeEmail(email);
            }
        };

        // Load body asynchronously
        item.body.getAsync('text', (result: BodyAsyncResult) => {
            if (result.status === Office.AsyncResultStatus.Succeeded) {
                email.body = result.value;
            } else {
                console.error('Failed to load email body:', result.error);
            }
            bodyLoaded = true;
            checkAndSetEmail();
        });

        // Load attachments asynchronously
        if (item.attachments && item.attachments.length > 0) {
            const attachmentPromises = item.attachments.map((attachment) => {
                return new Promise<{ filename: string; base64: string } | null>((resolve) => {
                    if (String(attachment.attachmentType) === String(Office.MailboxEnums.AttachmentType.File)) {
                        // Get attachment content
                        item.getAttachmentContentAsync(attachment.id, (result: AttachmentContentAsyncResult) => {
                            if (result.status === Office.AsyncResultStatus.Succeeded) {
                                resolve({
                                    filename: attachment.name,
                                    base64: result.value.content // Already in base64
                                });
                            } else {
                                console.error('Failed to load attachment:', attachment.name, result.error);
                                resolve(null);
                            }
                        });
                    } else {
                        // Skip item attachments (embedded emails, etc.)
                        resolve(null);
                    }
                });
            });

            void Promise.all(attachmentPromises).then(results => {
                email.attachments = results.filter(a => a !== null) as { filename: string; base64: string }[];
                attachmentsLoaded = true;
                checkAndSetEmail();
            });
        } else {
            attachmentsLoaded = true;
            checkAndSetEmail();
        }

    }, [isOfficeReady, isDemoMode, demoEmail]);


    return { email: isDemoMode && demoEmail ? demoEmail : officeEmail };
};


export { useEmail };
