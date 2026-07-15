import { EmailAutomationProvider } from '@/hooks/use-email-automation';
import { useOffice } from '@/hooks/use-office';
import { Routes, Route, useLocation } from 'react-router-dom';
import { Home } from './routes/home';
import { Chat } from './routes/chat';
import { Embed } from './routes/embed';
import { Login } from './routes/login';
import { Loader, Loader2, Mail } from 'lucide-react';
import { settings } from './settings';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { api } from './api/endpoints';
import type { AuthResponse } from './api/endpoints';
import { Button } from './components/ui/button';
import { Input } from './components/ui/input';
import { Label } from './components/ui/label';
import { syncLanguage, t } from './lib/i18n';

const MUST_CHANGE_PASSWORD_KEY = 'auth_must_change_password';

function App() {
  const location = useLocation();

  // Embed mode: bypass all guards (Office.js readiness, auth).
  // Still wrapped in DemoProvider + OfficeProvider from main.tsx so hooks work,
  // but we skip the interactive guards and render directly.
  if (location.pathname === '/embed') {
    if (!settings.enableAdminPreview) {
      return null;
    }

    return (
      <EmailAutomationProvider>
        <Routes>
          <Route path="/embed" element={<Embed />} />
        </Routes>
      </EmailAutomationProvider>
    );
  }

  return <AppGuarded />;
}

interface ChangePasswordGateProps {
  onComplete: () => void;
  onSignOut: () => void;
}

function ChangePasswordGate({ onComplete, onSignOut }: ChangePasswordGateProps) {
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (newPassword.length < 8) {
      toast.error(t('auth.passwordMin'));
      return;
    }
    if (newPassword !== confirmPassword) {
      toast.error(t('auth.passwordMismatch'));
      return;
    }

    setIsSubmitting(true);
    try {
      const result = await api.changePassword(oldPassword, newPassword);
      if (result.error || !result.data) {
        toast.error(result.error || t('auth.changePasswordError'));
        return;
      }

      localStorage.setItem('auth_token', result.data.token);
      localStorage.setItem('auth_email', result.data.email);
      window.dispatchEvent(new Event('auth:session-changed'));
      localStorage.removeItem(MUST_CHANGE_PASSWORD_KEY);
      toast.success(t('auth.changePasswordSuccess'));
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
          <h1 className="text-xl font-bold">{t('auth.changePasswordTitle')}</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {t('auth.changePasswordDescription')}
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="current-password">{t('auth.currentPassword')}</Label>
            <Input
              id="current-password"
              type="password"
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="new-password">{t('auth.newPassword')}</Label>
            <Input
              id="new-password"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              minLength={8}
              required
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="confirm-password">{t('auth.confirmPassword')}</Label>
            <Input
              id="confirm-password"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              minLength={8}
              required
            />
          </div>
          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting ? <Loader className="size-4 animate-spin mr-2" /> : null}
            {t('auth.updatePassword')}
          </Button>
        </form>

        <Button
          type="button"
          variant="ghost"
          className="w-full mt-3 text-muted-foreground"
          onClick={onSignOut}
        >
          {t('auth.logout')}
        </Button>
      </div>
    </div>
  );
}

/** The original guarded app — separated so useOffice/useDemo are only called in non-embed context */
function AppGuarded() {
  const { isOfficeReady, isOutlook } = useOffice();
  const [, setLocaleVersion] = useState(0);
  const [isAuthenticated, setIsAuthenticated] = useState(() => {
    return !settings.requireAuth || !!localStorage.getItem('auth_token');
  });
  const [mustChangePassword, setMustChangePassword] = useState(() => {
    return settings.requireAuth && localStorage.getItem(MUST_CHANGE_PASSWORD_KEY) === '1';
  });

  useEffect(() => {
    const handleUnauthorized = () => {
      localStorage.removeItem('auth_email');
      localStorage.removeItem(MUST_CHANGE_PASSWORD_KEY);
      window.dispatchEvent(new Event('auth:session-changed'));
      setMustChangePassword(false);
      setIsAuthenticated(false);
    };

    window.addEventListener('frontend:unauthorized', handleUnauthorized);
    return () => window.removeEventListener('frontend:unauthorized', handleUnauthorized);
  }, []);

  const applyLanguage = (language: AuthResponse['language']) => {
    syncLanguage(language);
    setLocaleVersion(version => version + 1);
  };

  useEffect(() => {
    if (settings.requireAuth && !isAuthenticated) return;
    void api.getMe().then(result => {
      if (result.data?.language) {
        syncLanguage(result.data.language);
        setLocaleVersion(version => version + 1);
      }
    });
  }, [isAuthenticated]);

  // Auth guard: show login screen if VITE_REQUIRE_AUTH=true and no token
  if (settings.requireAuth && !isAuthenticated) {
    return (
      <Login
        onAuthenticated={(session: AuthResponse) => {
          applyLanguage(session.language);
          setIsAuthenticated(true);
          setMustChangePassword(session.mustChangePassword);
        }}
      />
    );
  }

  if (mustChangePassword) {
    return (
      <ChangePasswordGate
        onComplete={() => setMustChangePassword(false)}
        onSignOut={() => {
          localStorage.removeItem('auth_token');
          localStorage.removeItem('auth_email');
          localStorage.removeItem(MUST_CHANGE_PASSWORD_KEY);
          window.dispatchEvent(new Event('auth:session-changed'));
          setMustChangePassword(false);
          setIsAuthenticated(false);
        }}
      />
    );
  }

  if (!isOfficeReady) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <Loader2 className='size-4 animate-spin' />
        </div>
      </div>
    );
  }

  if (!isOutlook && !settings.isMockMode) {
    window.location.replace('/');
    return null;
  }

  return (
    <>
      <EmailAutomationProvider>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/chat/:id" element={<Chat />} />
        </Routes>
      </EmailAutomationProvider>
    </>
  )
}

export default App
