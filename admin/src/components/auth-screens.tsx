import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { CheckCircle2, ExternalLink, Loader, Mail } from 'lucide-react';
import { toast } from 'sonner';

import { api, getLoginMethod, requestPasswordReset } from '@/api/endpoints';
import type { AuthResponse } from '@/api/endpoints';
import { brand } from '@/brand';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useI18n } from '@/lib/i18n-context';

const MUST_CHANGE_PASSWORD_KEY = 'admin_must_change_password';

interface LoginProps {
    onAuthenticated: (session: AuthResponse) => void;
    onSwitchToSignup: () => void;
    allowSignups: boolean;
    initialEmail?: string;
    intro?: ReactNode;
}

export const AdminLogin = ({ onAuthenticated, onSwitchToSignup, allowSignups, initialEmail = '', intro }: LoginProps) => {
    const [email, setEmail] = useState(initialEmail);
    const [password, setPassword] = useState('');
    const [loginCode, setLoginCode] = useState('');
    const [loginMethod, setLoginMethod] = useState<'email' | 'password' | 'code'>('email');
    const [isSubmitting, setIsSubmitting] = useState(false);
    const { t, setLocale } = useI18n();

    useEffect(() => {
        if (initialEmail && !email) {
            setEmail(initialEmail);
        }
    }, [email, initialEmail]);

    const completeAuthentication = (session: AuthResponse) => {
        localStorage.setItem('admin_auth_token', session.token);
        setLocale(session.language ?? 'en');
        if (session.mustChangePassword) {
            localStorage.setItem(MUST_CHANGE_PASSWORD_KEY, '1');
        } else {
            localStorage.removeItem(MUST_CHANGE_PASSWORD_KEY);
        }
        onAuthenticated(session);
    };

    const handleSubmit = async (e: FormEvent) => {
        e.preventDefault();
        setIsSubmitting(true);
        try {
            if (loginMethod === 'email') {
                const result = await getLoginMethod(email);
                if (result.error || !result.data) {
                    toast.error(result.error || t('Login failed.'));
                    return;
                }
                if (result.data.method === 'password') {
                    setLoginMethod('password');
                    return;
                }
                const codeResult = await api.requestLoginCode(email);
                if (codeResult.error) {
                    toast.error(codeResult.error);
                    return;
                }
                setLoginMethod('code');
                toast.success(t('Login code sent. Check your inbox.'));
                return;
            }

            if (loginMethod === 'password') {
                const result = await api.login(email, password);
                if (result.error || !result.data) {
                    toast.error(result.error || t('Invalid email or password.'));
                    return;
                }
                completeAuthentication(result.data);
                return;
            }

            const result = await api.verifyLoginCode(email, loginCode);
            if (result.error || !result.data) {
                toast.error(result.error || t('Invalid or expired login code.'));
                return;
            }
            completeAuthentication(result.data);
        } catch {
            toast.error(t('Login failed.'));
        } finally {
            setIsSubmitting(false);
        }
    };

    const handleForgotPassword = async () => {
        if (!email) {
            toast.error(t('Enter your email address first.'));
            return;
        }
        const result = await requestPasswordReset(email);
        if (result.error) {
            toast.error(result.error);
        } else {
            toast.success(t('Password reset email sent. Check your inbox.'));
        }
    };

    return (
        <div className="flex items-center justify-center min-h-screen bg-gray-50">
            <div className="w-full max-w-sm bg-white rounded-xl shadow-sm border p-8">
                <div className="text-center mb-6">
                    <Mail className="size-10 mx-auto mb-3 text-gray-400" />
                    <h1 className="font-display text-2xl font-normal not-italic">{brand.adminTitle}</h1>
                    <p className="text-sm text-muted-foreground mt-1">{t('Sign in to your account')}</p>
                </div>
                {intro}

                <form onSubmit={handleSubmit} className="space-y-4">
                    <div className="space-y-1">
                        <Label htmlFor="email">{t('Email')}</Label>
                        <Input
                            id="email"
                            type="email"
                            autoComplete="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            required
                            placeholder="email@mantly.io"
                            disabled={loginMethod !== 'email'}
                        />
                    </div>
                    {loginMethod === 'password' ? (
                        <div className="space-y-2">
                            <div className="flex items-center justify-between">
                                <Label htmlFor="password">{t('Password')}</Label>
                                <Button
                                    type="button"
                                    variant="link"
                                    size="xs"
                                    onClick={handleForgotPassword}
                                    className="h-auto p-0 text-xs text-muted-foreground"
                                >
                                    {t('Forgot password?')}
                                </Button>
                            </div>
                            <Input
                                id="password"
                                type="password"
                                autoComplete="current-password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                required
                                placeholder="********"
                            />
                        </div>
                    ) : loginMethod === 'code' ? (
                        <div className="space-y-1">
                            <Label htmlFor="loginCode">{t('Login code')}</Label>
                            <Input
                                id="loginCode"
                                inputMode="numeric"
                                autoComplete="one-time-code"
                                value={loginCode}
                                onChange={(e) => setLoginCode(e.target.value)}
                                required
                                placeholder="123456"
                            />
                            <p className="text-xs text-muted-foreground">
                                {t('Enter the 6-digit code we sent to {email}.', { email })}
                            </p>
                        </div>
                    ) : null}
                    <Button type="submit" className="w-full" disabled={isSubmitting}>
                        {isSubmitting && <Loader className="size-4 animate-spin mr-2" />}
                        {loginMethod === 'email' ? t('Continue') : loginMethod === 'password' ? t('Sign in') : t('Verify code')}
                    </Button>
                </form>
                <div className="mt-4 flex justify-center gap-3 text-sm">
                    {loginMethod !== 'email' && (
                        <Button
                            type="button"
                            variant="link"
                            size="xs"
                            onClick={() => {
                                setLoginMethod('email');
                                setLoginCode('');
                                setPassword('');
                            }}
                            className="h-auto p-0 text-muted-foreground"
                        >
                            {t('Use another email')}
                        </Button>
                    )}
                </div>

                {allowSignups && (
                    <p className="text-center text-sm text-muted-foreground mt-4">
                        {t("Don't have an account?")}{' '}
                        <Button
                            type="button"
                            variant="link"
                            size="xs"
                            onClick={onSwitchToSignup}
                            className="h-auto p-0 text-foreground"
                        >
                            {t('Create one')}
                        </Button>
                    </p>
                )}
            </div>
        </div>
    );
};

interface SignupProps {
    onAuthenticated: (session: AuthResponse) => void;
    onSwitchToLogin: () => void;
    isSaas: boolean;
    initialEmail?: string;
    intro?: ReactNode;
}

export const AdminSignup = ({ onSwitchToLogin, isSaas, initialEmail = '', intro }: SignupProps) => {
    const [companyName, setCompanyName] = useState('');
    const [email, setEmail] = useState(initialEmail);
    const [password, setPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [verificationSent, setVerificationSent] = useState(false);
    const { t, locale } = useI18n();
    const termsUrl = locale === 'de' ? 'https://mantly.io/nutzungsbedingungen' : 'https://mantly.io/terms';

    useEffect(() => {
        if (initialEmail && !email) {
            setEmail(initialEmail);
        }
    }, [email, initialEmail]);

    const handleSubmit = async (e: FormEvent) => {
        e.preventDefault();
        if (password.length < 8) {
            toast.error(t('Password must be at least 8 characters.'));
            return;
        }
        if (password !== confirmPassword) {
            toast.error(t('Passwords do not match.'));
            return;
        }
        setIsSubmitting(true);
        try {
            const result = await api.signup(isSaas ? companyName.trim() : '', email.trim(), password);
            if (result.error || !result.data) {
                toast.error(result.error || t('Signup failed.'));
                return;
            }

            if (result.data.verificationRequired) {
                setVerificationSent(true);
            } else {
                toast.success(t('Account created. You can now sign in.'));
                onSwitchToLogin();
            }
        } catch {
            toast.error(t('Signup failed.'));
        } finally {
            setIsSubmitting(false);
        }
    };

    if (verificationSent) {
        return (
            <div className="flex items-center justify-center min-h-screen bg-gray-50">
                <div className="w-full max-w-sm bg-white rounded-xl shadow-sm border p-8 text-center">
                    <Mail className="size-10 mx-auto mb-4 text-gray-400" />
                    <h1 className="font-display text-2xl font-normal not-italic mb-2">{t('Check your inbox')}</h1>
                    <p className="text-sm text-muted-foreground mt-2">
                        {t('We sent a verification link to {email}. Click the link to activate your account.', { email })}
                    </p>
                    <p className="text-center text-sm text-muted-foreground mt-6">
                        {t('Already verified?')}{' '}
                        <Button
                            type="button"
                            variant="link"
                            size="xs"
                            onClick={onSwitchToLogin}
                            className="h-auto p-0 text-foreground"
                        >
                            {t('Sign in')}
                        </Button>
                    </p>
                </div>
            </div>
        );
    }

    return (
        <div className="flex items-center justify-center min-h-screen bg-gray-50">
            <div className="w-full max-w-sm bg-white rounded-xl shadow-sm border p-8">
                <div className="text-center mb-6">
                    <Mail className="size-10 mx-auto mb-3 text-gray-400" />
                    <h1 className="font-display text-2xl font-normal not-italic">{t('Create Account')}</h1>
                    <p className="text-sm text-muted-foreground mt-1">
                        {isSaas ? t('Set up your organisation') : t('Join the organisation')}
                    </p>
                </div>
                {intro}

                <form onSubmit={handleSubmit} className="space-y-4">
                    {isSaas && (
                        <div className="space-y-1">
                            <Label htmlFor="companyName">{t('Organisation name')}</Label>
                            <Input
                                id="companyName"
                                value={companyName}
                                onChange={(e) => setCompanyName(e.target.value)}
                                required
                                placeholder={t('My Law Firm')}
                            />
                        </div>
                    )}
                    <div className="space-y-1">
                        <Label htmlFor="signupEmail">{t('Email')}</Label>
                        <Input
                            id="signupEmail"
                            type="email"
                            autoComplete="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            required
                            placeholder="email@mantly.io"
                        />
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="signupPassword">{t('Password')}</Label>
                        <Input
                            id="signupPassword"
                            type="password"
                            autoComplete="new-password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            required
                            minLength={8}
                            placeholder="********"
                        />
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="signupConfirmPassword">{t('Confirm password')}</Label>
                        <Input
                            id="signupConfirmPassword"
                            type="password"
                            autoComplete="new-password"
                            value={confirmPassword}
                            onChange={(e) => setConfirmPassword(e.target.value)}
                            required
                            minLength={8}
                            placeholder="********"
                        />
                    </div>
                    <Button type="submit" className="w-full" disabled={isSubmitting}>
                        {isSubmitting && <Loader className="size-4 animate-spin mr-2" />}
                        {t('Create account')}
                    </Button>
                    <p className="text-center text-xs leading-relaxed text-muted-foreground">
                        {t('By signing up, you accept the')}{' '}
                        <a
                            href={termsUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="font-medium text-foreground underline-offset-4 hover:underline"
                        >
                            {t('Terms and Conditions')}
                        </a>
                        .
                    </p>
                </form>

                <p className="text-center text-sm text-muted-foreground mt-4">
                    {t('Already have an account?')}{' '}
                    <Button
                        type="button"
                        variant="link"
                        size="xs"
                        onClick={onSwitchToLogin}
                        className="h-auto p-0 text-foreground"
                    >
                        {t('Sign in')}
                    </Button>
                </p>
            </div>
        </div>
    );
};

export const GmailConnectIntro = ({ gmailEmail }: { gmailEmail: string }) => {
    const { t } = useI18n();

    return (
        <div className="mb-5 rounded-md border bg-muted/40 p-3 text-sm">
            <div className="flex items-start gap-2">
                <Mail className="mt-0.5 size-4 text-muted-foreground" />
                <div className="min-w-0 space-y-1">
                    <p className="font-medium text-foreground">{t('Connect Gmail to Mantly')}</p>
                    <p className="text-muted-foreground">
                        {gmailEmail
                            ? t('Sign in with {email} or ask your admin to invite that address.', { email: gmailEmail })
                            : t('Sign in with the same email you use in Gmail.')}
                    </p>
                </div>
            </div>
        </div>
    );
};

export const GmailConnectStatus = ({
    gmailEmail,
    tenantName,
    userEmail,
    onOpenWorkspace,
    onSignOut,
}: {
    gmailEmail: string;
    tenantName: string;
    userEmail: string;
    onOpenWorkspace: () => void;
    onSignOut: () => void;
}) => {
    const { t } = useI18n();
    const hasMismatch = Boolean(gmailEmail && userEmail && gmailEmail.toLowerCase() !== userEmail.toLowerCase());

    return (
        <div className="flex min-h-screen items-center justify-center bg-gray-50 px-6 py-8">
            <div className="w-full max-w-md rounded-xl border bg-white p-8 shadow-sm">
                <div className="mb-6 text-center">
                    <CheckCircle2 className="mx-auto mb-3 size-10 text-emerald-600" />
                    <h1 className="font-display text-2xl font-normal not-italic">{t('Gmail connection')}</h1>
                    <p className="mt-1 text-sm text-muted-foreground">
                        {hasMismatch
                            ? t('This Mantly session uses a different email than Gmail.')
                            : t('Mantly is ready for Gmail.')}
                    </p>
                </div>

                <div className="space-y-3 rounded-md border bg-muted/40 p-4 text-sm">
                    {gmailEmail && (
                        <div className="flex justify-between gap-4">
                            <span className="text-muted-foreground">{t('Gmail account')}</span>
                            <span className="truncate font-medium">{gmailEmail}</span>
                        </div>
                    )}
                    <div className="flex justify-between gap-4">
                        <span className="text-muted-foreground">{t('Mantly account')}</span>
                        <span className="truncate font-medium">{userEmail}</span>
                    </div>
                    {tenantName && (
                        <div className="flex justify-between gap-4">
                            <span className="text-muted-foreground">{t('Workspace')}</span>
                            <span className="truncate font-medium">{tenantName}</span>
                        </div>
                    )}
                </div>

                <p className="mt-4 text-sm text-muted-foreground">
                    {hasMismatch
                        ? t('Sign out and use the Gmail email, or ask your admin to invite that Google account.')
                        : t('Return to Gmail and reload the Mantly add-on.')}
                </p>

                <div className="mt-6 flex flex-col gap-2">
                    {!hasMismatch && (
                        <Button asChild className="w-full">
                            <a href="https://mail.google.com/" target="_blank" rel="noreferrer">
                                <ExternalLink className="size-4" />
                                {t('Open Gmail')}
                            </a>
                        </Button>
                    )}
                    <Button type="button" variant="outline" className="w-full" onClick={onOpenWorkspace}>
                        {t('Open Mantly workspace')}
                    </Button>
                    <Button type="button" variant="ghost" className="w-full" onClick={onSignOut}>
                        {t('Sign out')}
                    </Button>
                </div>
            </div>
        </div>
    );
};

export const ChangePasswordGate = ({
    onComplete,
    onSignOut,
    userEmail,
}: {
    onComplete: () => void;
    onSignOut: () => void;
    userEmail: string;
}) => {
    const [oldPassword, setOldPassword] = useState('');
    const [newPassword, setNewPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [isSubmitting, setIsSubmitting] = useState(false);
    const { t } = useI18n();

    const handleSubmit = async (e: FormEvent) => {
        e.preventDefault();

        if (newPassword.length < 8) {
            toast.error(t('Password must be at least 8 characters.'));
            return;
        }
        if (newPassword !== confirmPassword) {
            toast.error(t('New passwords do not match.'));
            return;
        }

        setIsSubmitting(true);
        try {
            const result = await api.changePassword(oldPassword, newPassword);
            if (result.error || !result.data) {
                toast.error(result.error || t('Password change failed.'));
                return;
            }

            localStorage.setItem('admin_auth_token', result.data.token);
            localStorage.removeItem(MUST_CHANGE_PASSWORD_KEY);
            toast.success(t('Password updated.'));
            onComplete();
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="flex items-center justify-center min-h-screen bg-gray-50 px-6">
            <div className="w-full max-w-sm bg-white rounded-xl shadow-sm border p-8">
                <div className="text-center mb-6">
                    <Mail className="size-10 mx-auto mb-3 text-gray-400" />
                    <h1 className="text-xl font-bold">{t('Change password')}</h1>
                    <p className="text-sm text-muted-foreground mt-1">
                        {t('Your administrator issued a temporary password. Set a new one to continue.')}
                    </p>
                </div>

                <form onSubmit={handleSubmit} className="space-y-4">
                    <input
                        type="email"
                        name="username"
                        autoComplete="username"
                        value={userEmail}
                        readOnly
                        tabIndex={-1}
                        aria-hidden="true"
                        className="sr-only"
                    />
                    <div className="space-y-1">
                        <Label htmlFor="currentPassword">{t('Current password')}</Label>
                        <Input
                            id="currentPassword"
                            type="password"
                            autoComplete="current-password"
                            value={oldPassword}
                            onChange={(e) => setOldPassword(e.target.value)}
                            required
                        />
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="newPassword">{t('New password')}</Label>
                        <Input
                            id="newPassword"
                            type="password"
                            autoComplete="new-password"
                            value={newPassword}
                            onChange={(e) => setNewPassword(e.target.value)}
                            required
                            minLength={8}
                        />
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="confirmPassword">{t('Confirm new password')}</Label>
                        <Input
                            id="confirmPassword"
                            type="password"
                            autoComplete="new-password"
                            value={confirmPassword}
                            onChange={(e) => setConfirmPassword(e.target.value)}
                            required
                            minLength={8}
                        />
                    </div>
                    <Button type="submit" className="w-full" disabled={isSubmitting}>
                        {isSubmitting && <Loader className="size-4 animate-spin mr-2" />}
                        {t('Update password')}
                    </Button>
                </form>

                <Button
                    type="button"
                    variant="ghost"
                    className="w-full mt-3 text-muted-foreground"
                    onClick={onSignOut}
                >
                    {t('Sign out')}
                </Button>
            </div>
        </div>
    );
};
