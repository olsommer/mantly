import { useState } from 'react';
import { Lightbulb, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useI18n } from '@/lib/i18n-context';

interface HintBannerProps {
    storageKey: string;
    title: string;
    children: React.ReactNode;
}

export const HintBanner = ({ storageKey, title, children }: HintBannerProps) => {
    const { t } = useI18n();
    const lsKey = `hint_dismissed_${storageKey}`;
    const [visible, setVisible] = useState(() => !localStorage.getItem(lsKey));

    if (!visible) return null;

    const dismiss = () => {
        localStorage.setItem(lsKey, '1');
        setVisible(false);
    };

    return (
        <div className="rounded-lg border border-primary/20 bg-primary/5 px-4 py-3 flex items-start gap-3">
            <Lightbulb className="size-4 shrink-0 text-primary mt-0.5" />
            <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-foreground">{title}</p>
                <div className="text-sm text-muted-foreground mt-0.5">{children}</div>
            </div>
            <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                onClick={dismiss}
                className="shrink-0 text-muted-foreground"
                title={t('Dismiss')}
            >
                <X className="size-4" />
            </Button>
        </div>
    );
};
