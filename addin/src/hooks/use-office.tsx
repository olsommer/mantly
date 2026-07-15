/* eslint-disable react-refresh/only-export-components */
import { useState, useEffect, createContext, useContext } from 'react';
import type { ReactNode } from 'react';
import { useDemo } from './use-demo';
import { settings } from '@/settings';

// Simple markdown to HTML converter (basic version)
const convertMarkdownToHtml = (md: string): string => {
    // This is a basic converter - you might want to use a library like 'marked' for production
    return md
        .replace(/^### (.*$)/gim, '<h3>$1</h3>')
        .replace(/^## (.*$)/gim, '<h2>$1</h2>')
        .replace(/^# (.*$)/gim, '<h1>$1</h1>')
        .replace(/\*\*(.*)\*\*/gim, '<strong>$1</strong>')
        .replace(/\*(.*)\*/gim, '<em>$1</em>')
        .replace(/\n/gim, '<br>');
};

interface OfficeState {
    isOfficeReady: boolean;
    isOutlook: boolean;
    isDemoMode: boolean;
    user: string | null;
    applyEmail: (email: string, attachments: { filename: string; base64: string; }[]) => void;
}

// Create context
const OfficeContext = createContext<OfficeState | undefined>(undefined);

const DEV_MOCK_USER = 'local.user@example.com';

const getMockUser = (demoUser: string | null): string | null => {
    if (demoUser) {
        return demoUser;
    }

    const sessionUser = localStorage.getItem('auth_email');
    if (sessionUser) {
        return sessionUser;
    }

    return settings.requireAuth ? null : DEV_MOCK_USER;
};

// Provider component
export const OfficeProvider = ({ children }: { children: ReactNode }) => {
    const [runtimeOfficeState, setOffice] = useState<Omit<OfficeState, 'isDemoMode' | 'applyEmail'>>({
        isOfficeReady: false,
        isOutlook: false,
        user: null,
    });
    const { isDemoMode, demoUser } = useDemo();

    useEffect(() => {
        if (settings.isMockMode) {
            const syncMockOfficeState = () => {
                setOffice({
                    isOfficeReady: true,
                    isOutlook: true,
                    user: getMockUser(demoUser),
                });
            };

            syncMockOfficeState();
            window.addEventListener('auth:session-changed', syncMockOfficeState);
            return () => window.removeEventListener('auth:session-changed', syncMockOfficeState);
        }

        if (isDemoMode) {
            return;
        }

        // Check if Office is available
        if (typeof Office === 'undefined') {
            console.error('Office.js is not available');
            return;
        }

        void Office.onReady(({ host }) => {
            const isOutlook = host === Office.HostType.Outlook;
            const user = isOutlook
                ? (Office.context?.mailbox?.userProfile?.emailAddress ?? null)
                : null;
            setOffice({
                isOfficeReady: true,
                isOutlook,
                user,
            });
        });
    }, [isDemoMode, demoUser]);

    const applyEmail = (email: string, attachments: { filename: string; base64: string; }[]) => {
        if (officeState.isOutlook && typeof Office !== 'undefined' && Office.context?.mailbox?.item) {
            // Create reply with the markdown content and attachments
            const attachmentsToAdd = attachments.map(attachment => {
                // Remove data:type;base64, prefix if present
                const base64Data = attachment.base64.includes(',')
                    ? attachment.base64.split(',')[1]
                    : attachment.base64;

                return {
                    type: 'file' as const,
                    name: attachment.filename,
                    url: `data:application/octet-stream;base64,${base64Data}`
                };
            });

            Office.context.mailbox.displayNewMessageForm({
                toRecipients: [Office.context.mailbox.item.from?.emailAddress || ''],
                subject: `Re: ${Office.context.mailbox.item.subject || ''}`,
                htmlBody: convertMarkdownToHtml(email),
                attachments: attachmentsToAdd
            });
        }
    };

    const officeState: OfficeState = settings.isMockMode
        ? {
            ...runtimeOfficeState,
            isDemoMode,
            applyEmail,
        }
        : isDemoMode
        ? {
            isOfficeReady: true,
            isOutlook: true,
            isDemoMode: true,
            user: demoUser,
            applyEmail,
        }
        : {
            ...runtimeOfficeState,
            isDemoMode: false,
            applyEmail,
        };

    return (
        <OfficeContext.Provider value={{ ...officeState, applyEmail }}>
            {children}
        </OfficeContext.Provider>
    );
};

// Hook to use Office context
export const useOffice = (): OfficeState => {
    const context = useContext(OfficeContext);
    if (context === undefined) {
        throw new Error('useOffice must be used within an OfficeProvider');
    }
    return context;
};
