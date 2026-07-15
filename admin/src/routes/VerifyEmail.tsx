import { useEffect, useRef, useState } from 'react';
import { Mail, CheckCircle, XCircle, Loader } from 'lucide-react';
import { confirmVerification } from '@/api/endpoints';
import { Card, CardContent } from '@/components/ui/card';
import { useI18n } from '@/lib/i18n-context';

export const VerifyEmail = () => {
    const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
    const [message, setMessage] = useState('');
    const didRun = useRef(false);
    const { t } = useI18n();

    useEffect(() => {
        if (didRun.current) return;
        didRun.current = true;

        const params = new URLSearchParams(window.location.search);
        const token = params.get('token');

        const run = async () => {
            if (!token) {
                setStatus('error');
                setMessage(t('No verification token found in the URL.'));
                return;
            }

            // PocketBase's confirm-verification endpoint
            const result = await confirmVerification(token);
            if (result.error) {
                setStatus('error');
                setMessage(result.error || t('Verification failed. The link may have expired.'));
                return;
            }
            setStatus('success');
            setMessage(t('Your email has been verified. You can now log in.'));
        };

        void run();
    }, [t]);

    return (
        <div className="flex items-center justify-center min-h-screen bg-muted/30">
            <Card className="w-full max-w-sm text-center">
                <CardContent className="p-8">
                <Mail className="size-10 mx-auto mb-4 text-muted-foreground" />
                <h1 className="text-xl font-bold mb-2">{t('Email Verification')}</h1>

                {status === 'loading' && (
                    <div className="flex flex-col items-center gap-3 mt-4 text-muted-foreground">
                        <Loader className="size-6 animate-spin" />
                        <p className="text-sm">{t('Verifying your email...')}</p>
                    </div>
                )}

                {status === 'success' && (
                    <div className="flex flex-col items-center gap-3 mt-4">
                        <CheckCircle className="size-8 text-primary" />
                        <p className="text-sm text-muted-foreground">{message}</p>
                        <a
                            href="/"
                            className="mt-2 text-sm font-medium text-blue-600 hover:underline"
                        >
                            {t('Sign in')}
                        </a>
                    </div>
                )}

                {status === 'error' && (
                    <div className="flex flex-col items-center gap-3 mt-4">
                        <XCircle className="size-8 text-destructive" />
                        <p className="text-sm text-destructive">{message}</p>
                        <a
                            href="/"
                            className="mt-2 text-sm font-medium text-blue-600 hover:underline"
                        >
                            {t('Back to Admin')}
                        </a>
                    </div>
                )}
                </CardContent>
            </Card>
        </div>
    );
};
