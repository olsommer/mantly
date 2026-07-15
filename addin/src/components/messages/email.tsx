import { Button } from '@/components/ui/button';
import { X, Paperclip, ArrowUpLeft, AlertCircle, Upload } from 'lucide-react';
import { Editor } from '@/components/editor';
import { useMemo, useState, useRef } from "react";
import type { EmailResponse, Message } from "@/models/email";
import { useEmailAutomation } from "@/hooks/use-email-automation";
import { useOffice } from "@/hooks/use-office";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { toast } from "sonner";

type Props = {
    index: number;
    message: Message;
    isNewChat?: boolean;
    onDirtyChange?: (dirty: boolean) => void;
    onResponseChange?: (content: EmailResponse) => void;
    chatId?: string;
    demoMode?: boolean;
};

const sanitizeGeneratedMarkdown = (markdown: string) =>
    markdown.replace(/^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/gm, '').trim();

export const EmailMessage = ({ index, message: _message, isNewChat = false, onDirtyChange, onResponseChange, demoMode = false }: Props) => {
    const { updateMessage, chat } = useEmailAutomation();
    const { applyEmail } = useOffice();
    const [message, setMessage] = useState<Message>(_message);

    // Safely extract email content with validation
    const emailContent = message.content as EmailResponse;
    const emailBody = typeof emailContent?.emailBody === 'string'
        ? sanitizeGeneratedMarkdown(emailContent.emailBody)
        : '';
    const emailAttachments = emailContent?.emailAttachments || [];
    const requiresHuman = emailContent?.requiresHuman ?? false;
    const requiresHumanReason = emailContent?.requiresHumanReason;

    // Track original body so we can detect unsaved edits
    const originalBodyRef = useRef(emailBody);
    const fileInputRef = useRef<HTMLInputElement>(null);

    const commitResponseMessage = (updatedMessage: Message) => {
        setMessage(updatedMessage);
        onResponseChange?.(updatedMessage.content as EmailResponse);
    };

    const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = Array.from(e.target.files ?? []);
        const MAX_SIZE = 10 * 1024 * 1024; // 10 MB
        files.forEach(file => {
            if (file.size > MAX_SIZE) {
                toast.error(t('email.fileTooLarge', { name: file.name }));
                return;
            }
            const reader = new FileReader();
            reader.onload = () => {
                const base64 = (reader.result as string).split(',')[1];
                setMessage(prev => {
                    const updatedMessage: Message = {
                        ...prev,
                        role: 'response',
                        user: 'response',
                        content: {
                        ...prev.content as EmailResponse,
                        emailAttachments: [
                            ...((prev.content as EmailResponse).emailAttachments ?? []),
                            { filename: file.name, base64, contentType: file.type || 'application/octet-stream' },
                        ],
                        },
                    };
                    onResponseChange?.(updatedMessage.content);
                    return updatedMessage;
                });
            };
            reader.readAsDataURL(file);
        });
        // Reset so the same file can be re-added after removal
        e.target.value = '';
    };
    const canApply = useMemo(() => {
        if (chat) {
            // Find last email by searching from the end
            const emailIndex = [...chat].reverse().findIndex(m => m.user === "email");
            const lastEmailIndex = emailIndex !== -1 ? chat.length - 1 - emailIndex : -1;

            // If there's an email after this email, can't apply
            if (lastEmailIndex !== -1 && lastEmailIndex > index) {
                return false;
            }
        }
        return !demoMode;
    }, [chat, demoMode, index]);


    const handleApply = () => {
        const email = message.content as EmailResponse;
        updateMessage(message, index);
        try {
            applyEmail(email.emailBody, email.emailAttachments ?? []);
            toast.success(t('email.applySuccess'));
            onDirtyChange?.(false);
            originalBodyRef.current = email.emailBody;
        } catch {
            // applyEmail logs errors internally; toast is best-effort
            toast.error(t('email.applyError'));
        }
    }

    const setMarkdown = (markdown: string) => {
        const updatedMessage: Message = {
            ...message,
            role: 'response',
            user: 'response',
            content: {
                ...message.content as EmailResponse,
                emailBody: markdown,
            }
        };
        commitResponseMessage(updatedMessage);
        const dirty = markdown !== originalBodyRef.current;
        onDirtyChange?.(dirty);
    };

    const handleRemoveAttachment = (attIndex: number) => {
        const updatedAttachments = emailAttachments?.filter((_, i) => i !== attIndex) || [];
        const updatedMessage: Message = {
            ...message,
            role: 'response',
            user: 'response',
            content: {
                ...message.content as EmailResponse,
                emailAttachments: updatedAttachments,
            }
        };
        commitResponseMessage(updatedMessage);
    }

    // If this email requires human intervention, show a special message
    if (requiresHuman) {
        return (
            <div className={cn(
                "flex min-h-0 w-full flex-1 items-center justify-center bg-muted/50 px-4 py-6",
                isNewChat
                    ? "h-full"
                    : "m-2 min-h-80 rounded-lg border"
            )}>
                <div className="flex max-w-md flex-col items-center space-y-3 text-center">
                    <div className="rounded-full border border-amber-200 bg-amber-100 p-2.5">
                        <AlertCircle className="size-5 text-amber-600" />
                    </div>
                    <div className="space-y-1.5">
                        <h3 className="text-base font-medium">{t('email.humanReview')}</h3>
                        <p className="text-sm leading-relaxed text-muted-foreground">
                            {requiresHumanReason || t('email.humanReviewDesc')}
                        </p>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className={cn(
            isNewChat
                ? "flex h-full min-h-0 flex-col bg-gray-50 p-2"
                : "m-2 overflow-hidden rounded-lg border bg-gray-50 p-2"
        )}>
            <div className={cn(
                "rounded-md border bg-white p-2",
                isNewChat
                    ? "flex min-h-0 flex-1 flex-col"
                    : "space-y-2"
            )}>
                {/* Attachments section */}
                {emailAttachments && (
                    <>
                        {/* Hidden file input */}
                        <input
                            type="file"
                            ref={fileInputRef}
                            className="hidden"
                            multiple
                            onChange={handleFileUpload}
                        />

                        {/* Attachment Header */}
                        <div className="border-b pb-2">
                            <div className="flex min-h-7 items-center gap-2">
                                <Paperclip className="size-3.5 text-muted-foreground" />
                                <span className="text-xs font-medium">
                                    {t('email.attachments')} ({emailAttachments.length})
                                </span>
                                {canApply && (
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        className="ml-auto h-7 gap-1 px-2 text-xs"
                                        onClick={() => fileInputRef.current?.click()}
                                    >
                                        <Upload className="size-3" />
                                        {t('email.addAttachment')}
                                    </Button>
                                )}
                            </div>


                            {/* Attachment List */}
                            <div className={cn("grid min-w-0 max-w-full grid-cols-1 gap-2 overflow-hidden sm:max-w-64", { "mt-2": emailAttachments.length > 0 })}>
                                {emailAttachments.map((attachment, attIndex) => (
                                    <Button
                                        variant="outline"
                                        size={"sm"}
                                        className="w-full min-w-0 justify-start gap-1.5 overflow-hidden"
                                        onClick={() => handleRemoveAttachment(attIndex)}
                                        disabled={!canApply}
                                        key={attIndex}
                                        title={attachment.filename}
                                    >
                                        <span className="block min-w-0 flex-1 truncate text-left text-sm">{attachment.filename}</span>
                                        <X className="size-4 shrink-0" />
                                    </Button>

                                ))}
                            </div>
                        </div>
                    </>
                )}

                {/* Email editor */}
                <div
                    className={cn(
                        "isolated prose max-w-none",
                        { "min-h-0 flex-1 overflow-y-auto": isNewChat },
                        emailAttachments ? "pt-2" : null
                    )}
                >
                    <div className={!canApply ? 'pointer-events-none' : ''}>
                        <Editor
                            markdown={emailBody}
                            setMarkdown={setMarkdown}
                            readOnly={!canApply}
                        />
                    </div>
                </div>

                {/* Apply button */}
                {canApply
                    ? <div className="shrink-0 pt-2">
                        <Button className="w-full" onClick={handleApply}>
                            <ArrowUpLeft className="size-4" /> {t('email.apply')}
                        </Button>
                    </div>
                    : null}
            </div>
        </div>

    );
};
