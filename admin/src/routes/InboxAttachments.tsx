import { ExternalLink, Paperclip } from 'lucide-react';

import { Badge } from '@/components/ui/badge';

type TranslateFn = (key: string, params?: Record<string, string | number>) => string;

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function textFrom(value: unknown): string {
    if (typeof value === 'string') return value.trim();
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
    return '';
}

function attachmentField(attachment: unknown, keys: string[]): string {
    if (typeof attachment === 'string') return attachment;
    if (!isRecord(attachment)) return '';
    for (const key of keys) {
        const value = attachment[key];
        const text = textFrom(value).trim();
        if (text) return text;
    }
    return '';
}

function attachmentName(attachment: unknown, index: number): string {
    return attachmentField(attachment, ['filename', 'fileName', 'name', 'title']) || `Attachment ${index + 1}`;
}

function attachmentUrl(attachment: unknown): string {
    return attachmentField(attachment, ['url', 'href', 'downloadUrl', 'download_url', 'fileUrl', 'file_url']);
}

function attachmentSize(attachment: unknown): number | null {
    if (!isRecord(attachment)) return null;
    const raw = attachment.size ?? attachment.sizeBytes ?? attachment.size_bytes ?? attachment.bytes;
    if (typeof raw === 'number' && Number.isFinite(raw) && raw >= 0) return raw;
    if (typeof raw === 'string') {
        const parsed = Number(raw);
        if (Number.isFinite(parsed) && parsed >= 0) return parsed;
    }
    return null;
}

function formatBytes(value: number): string {
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function attachmentDetail(attachment: unknown): string {
    const size = attachmentSize(attachment);
    const parts = [
        attachmentField(attachment, ['contentType', 'content_type', 'mimeType', 'mime_type', 'type']),
        size !== null ? formatBytes(size) : '',
    ].filter(Boolean);
    return parts.join(' - ');
}

export function InboxAttachments({ attachments, t }: { attachments: unknown[]; t: TranslateFn }) {
    if (attachments.length === 0) return null;
    return (
        <div className="mt-3 rounded-md border bg-background p-2">
            <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
                <Paperclip className="size-3.5" />
                <span>{t('Attachments')}</span>
                <Badge variant="outline" className="font-normal">{attachments.length}</Badge>
            </div>
            <div className="grid gap-1.5">
                {attachments.map((attachment, index) => {
                    const name = attachmentName(attachment, index);
                    const detail = attachmentDetail(attachment);
                    const url = attachmentUrl(attachment);
                    const body = (
                        <>
                            <Paperclip className="size-3.5 shrink-0 text-muted-foreground" />
                            <span className="min-w-0 flex-1 truncate">{name}</span>
                            {detail && <span className="shrink-0 text-muted-foreground">{detail}</span>}
                            {url && <ExternalLink className="size-3.5 shrink-0 text-muted-foreground" />}
                        </>
                    );
                    return url ? (
                        <a
                            key={`${name}:${index}`}
                            href={url}
                            target="_blank"
                            rel="noreferrer"
                            className="flex min-w-0 items-center gap-2 rounded border bg-muted/20 px-2 py-1.5 text-xs hover:bg-muted/40"
                        >
                            {body}
                        </a>
                    ) : (
                        <div key={`${name}:${index}`} className="flex min-w-0 items-center gap-2 rounded border bg-muted/20 px-2 py-1.5 text-xs">
                            {body}
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
