import { useEmailAutomation } from '@/hooks/use-email-automation';
import { Button } from '@/components/ui/button';
import { Loader, Mail } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useEmail } from '@/hooks/use-email';
import { useDemo } from '@/hooks/use-demo';
import { t } from '@/lib/i18n';
import { AddinProjectSelector } from '@/components/pipeline/AddinProjectSelector';
import { AddinUserMenu } from '@/components/pipeline/AddinUserMenu';

const chatPath = (id: string) => `/chat/${encodeURIComponent(id)}`;

const Home = () => {
  const { isLoading, error } = useEmailAutomation();
  const navigate = useNavigate();
  const { email } = useEmail();
  const { isDemoMode } = useDemo();

  const handleCurrentEmail = () => {
    if (email) {
      void navigate(chatPath(email.id));
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Button disabled variant={"outline"}>
          <Loader className='size-4 animate-spin' /> {t('home.loading')}
        </Button>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center p-8 max-w-md">
          <div className="text-red-600 text-5xl mb-4">❌</div>
          <h2 className="text-2xl font-bold mb-2 text-red-600">{t('home.error')}</h2>
          <p className="text-gray-600">{typeof error === 'string' ? error : t('home.error')}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col">

      <div className="flex-1 flex items-center justify-center p-4">
        <div className="w-full max-w-md space-y-4">
          <div className="text-center mb-6">
            <Mail className="size-12 mx-auto mb-4 text-gray-400" />
            <h2 className="text-xl font-semibold mb-2">{t('home.welcome')}</h2>
          </div>

          <Button
            onClick={handleCurrentEmail}
            disabled={isLoading || !email}
            className="w-full"
          >
            {isLoading ? <Loader className="size-4 animate-spin mr-2" /> : null}
            {t('home.analyzeEmail')}
          </Button>

          {isDemoMode && (
            <p className="text-xs text-center text-muted-foreground">
              {t('home.productionHint')}
            </p>
          )}
        </div>
      </div>
      <div className="flex shrink-0 items-center justify-end gap-2 border-t bg-white px-2 py-2">
        <AddinProjectSelector />
        <AddinUserMenu />
      </div>
    </div>
  );
};

export { Home };
