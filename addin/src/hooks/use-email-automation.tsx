/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, type ReactNode } from 'react';
import { useEmail } from './use-email';
import { useOffice } from './use-office';
import { api } from '@/api/endpoints';
import type { Email, Message } from '@/models/email';
import { t } from '@/lib/i18n';
import { useProjectSelection } from './use-project-selection';

// Context state interface
interface Context {
    isLoading: boolean;
    error: string | null;
    email: Email | null;
    chat: Message[] | null;
    activatedIntent: string | null;
    updateMessage: (message: Message, index: number) => void;
    analyzeEmail: () => Promise<string>;
    loadChat: (chatId: string, silent?: boolean) => Promise<void>;
}

// Create context
const EmailAutomationContext = createContext<Context | undefined>(undefined);

// Provider props
interface ProviderProps {
    children: ReactNode;
}

// Provider component
export const EmailAutomationProvider: React.FC<ProviderProps> = ({ children }) => {
    const [isLoading, setLoading] = useState<boolean>(false);
    const [error, setError] = useState<string | null>(null);
    const [chat, setChat] = useState<Message[] | null>(null);
    const [activatedIntent, setActivatedIntent] = useState<string | null>(null);
    const { email: email } = useEmail();
    const { user } = useOffice();
    const { resolveProjectId } = useProjectSelection();

    const analyzeEmail = async (): Promise<string> => {
        if (!email) {
            throw new Error('No email loaded for ticket context');
        }

        if (!user) {
            throw new Error('No user loaded from Office');
        }

        setLoading(true);
        setError(null);

        try {
            const projectId = await resolveProjectId();
            const response = await api.process({
                email,
                creator: user,
                action: 'respond',
                ...(projectId ? { projectId } : {}),
            });

            if (response.error) {
                setError(response.error);
                throw new Error(response.error);
            }

            if (!response.data) {
                setError('No data received from API');
                throw new Error('No data received from API');
            }

            // Set chat to the returned messages
            setChat(response.data);

            return email.id;

        } catch (err) {
            console.error('Ticket context error:', err);
            setError(t('toast.chatApiFailed'));
            throw err;

        } finally {
            setLoading(false);
        }
    };

    const loadChat = async (chatId: string, silent?: boolean) => {
        if (!silent) setLoading(true);
        setError(null);

        try {
            const projectId = await resolveProjectId();
            const response = await api.getChat(chatId, projectId);

            if (response.error) {
                setError(response.error);
                return;
            }

            if (!response.data) {
                await analyzeEmail();
                // Reload from DB so we get activatedIntent and full chat state
                const fresh = await api.getChat(chatId, projectId);
                if (fresh.data) {
                    setChat(fresh.data.messages);
                    setActivatedIntent(fresh.data.activatedIntent ?? null);
                }
                return;
            }

            // Set chat to the returned messages
            setChat(response.data.messages);

            // Set activated intent (may be null for emails with no match)
            setActivatedIntent(response.data.activatedIntent ?? null);

        } catch (err) {
            console.error('Failed to load ticket context:', err);
            setError(t('toast.chatApiFailed'));
        } finally {
            if (!silent) setLoading(false);
        }
    };

    const updateMessage = (message: Message, index: number) => {
        if (index < 0) {
            setChat(prev => {
                if (!prev) return [message];
                return [...prev, message];
            });
        } else {
            setChat(prev => {
                if (!prev) return [message];
                const updated = [...prev];
                updated[index] = message;
                return updated;
            });
        }
    };

    const value: Context = {
        isLoading,
        error,
        email,
        chat,
        activatedIntent,
        updateMessage,
        analyzeEmail,
        loadChat,
    };

    return (
        <EmailAutomationContext.Provider value={value}>
            {children}
        </EmailAutomationContext.Provider>
    );
};

// Custom hook to use the email automation context
export const useEmailAutomation = (): Context => {
    const context = useContext(EmailAutomationContext);
    if (context === undefined) {
        throw new Error('useEmailAutomation must be used within an EmailAutomationProvider');
    }
    return context;
};
