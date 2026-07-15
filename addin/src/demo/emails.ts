import type { Email } from '@/models/email';
import emails from '@demo/emails/emails.json';

export const DEMO_EMAILS: Email[] = emails.map((email) => ({
    ...email,
    attachments: email.attachments ?? [],
}));
