/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import type { Email } from '@/models/email';

const DEFAULT_DEMO_USER = 'zenfulfillment@mantly.io';
const DEMO_SCENARIOS_ENABLED =
    import.meta.env.DEV
    && (
        import.meta.env.VITE_ENABLE_DEMO_MODE === 'true'
        || import.meta.env.VITE_ENABLE_DEMO_SCENARIOS === 'true'
    );

interface DemoState {
    isDemoMode: boolean;
    demoUser: string | null;
    demoEmail: Email | null;
    setDemoData: (user: string, email: Email) => void;
    resetDemo: () => void;
}

const DemoContext = createContext<DemoState | undefined>(undefined);

export const DemoProvider = ({ children }: { children: ReactNode }) => {
    const [demoUser, setDemoUser] = useState<string | null>(null);
    const [demoEmail, setDemoEmail] = useState<Email | null>(null);

    const loadDefaultDemo = async () => {
        if (!DEMO_SCENARIOS_ENABLED) {
            setDemoUser(null);
            setDemoEmail(null);
            return;
        }

        const { DEMO_EMAILS } = await import('@/demo/emails');
        setDemoUser(DEFAULT_DEMO_USER);
        setDemoEmail(DEMO_EMAILS[0] ?? null);
    };

    useEffect(() => {
        void loadDefaultDemo();
    }, []);

    const setDemoData = (user: string, email: Email) => {
        setDemoUser(user);
        setDemoEmail(email);
    };

    const resetDemo = () => {
        void loadDefaultDemo();
    };

    const value: DemoState = {
        isDemoMode: demoUser !== null && demoEmail !== null,
        demoUser,
        demoEmail,
        setDemoData,
        resetDemo,
    };

    return <DemoContext.Provider value={value}>{children}</DemoContext.Provider>;
};

export const useDemo = (): DemoState => {
    const context = useContext(DemoContext);
    if (context === undefined) {
        throw new Error('useDemo must be used within a DemoProvider');
    }
    return context;
};
