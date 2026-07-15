import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Loader, Mail } from 'lucide-react';
import { toast } from 'sonner';
import { api } from '@/api/endpoints';
import type { AuthResponse } from '@/api/endpoints';
import { t } from '@/lib/i18n';

interface Props {
    onAuthenticated: (session: AuthResponse) => void;
}

const MUST_CHANGE_PASSWORD_KEY = 'auth_must_change_password';

const Login = ({ onAuthenticated }: Props) => {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [isSubmitting, setIsSubmitting] = useState(false);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();

        setIsSubmitting(true);
        try {
            const result = await api.login(email, password);
            if (result.error || !result.data) {
                toast.error(result.error || t('auth.loginError'));
                return;
            }

            localStorage.setItem('auth_token', result.data.token);
            localStorage.setItem('auth_email', result.data.email);
            window.dispatchEvent(new Event('auth:session-changed'));
            if (result.data.mustChangePassword) {
                localStorage.setItem(MUST_CHANGE_PASSWORD_KEY, '1');
            } else {
                localStorage.removeItem(MUST_CHANGE_PASSWORD_KEY);
            }
            onAuthenticated(result.data);
        } catch {
            toast.error(t('auth.loginError'));
        } finally {
            setIsSubmitting(false);
        }
    };

    const handleForgotPassword = async () => {
        if (!email) {
            toast.error(t('auth.enterEmailFirst'));
            return;
        }

        const result = await api.requestPasswordReset(email);
        if (result.error) {
            toast.error(result.error);
            return;
        }

        toast.success(t('auth.passwordResetSent'));
    };

    return (
        <div className="flex min-h-screen items-center justify-center bg-gray-50 px-3 py-4">
            <div className="w-full max-w-sm rounded-xl border bg-white p-6 shadow-sm sm:p-8">
                <div className="text-center mb-6">
                    <Mail className="size-10 mx-auto mb-3 text-gray-400" />
                    <h1 className="text-xl font-bold">{t('home.title')}</h1>
                    <p className="text-sm text-muted-foreground mt-1">{t('auth.loginOnlyDescription')}</p>
                </div>

                <form onSubmit={handleSubmit} className="space-y-4">
                    <div className="space-y-1">
                        <Label htmlFor="email">{t('auth.email')}</Label>
                        <Input
                            id="email"
                            type="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            required
                            placeholder="email@mantly.io"
                        />
                    </div>

                    <div className="space-y-1">
                        <div className="flex items-center justify-between gap-3">
                            <Label htmlFor="password">{t('auth.password')}</Label>
                            <Button
                                type="button"
                                variant="link"
                                size="sm"
                                onClick={handleForgotPassword}
                                className="h-auto p-0 text-xs text-muted-foreground"
                            >
                                {t('auth.forgotPassword')}
                            </Button>
                        </div>
                        <Input
                            id="password"
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            required
                        />
                    </div>

                    <Button type="submit" className="w-full" disabled={isSubmitting}>
                        {isSubmitting ? <Loader className="size-4 animate-spin mr-2" /> : null}
                        {t('auth.loginButton')}
                    </Button>
                </form>
            </div>
        </div>
    );
};

export { Login };
