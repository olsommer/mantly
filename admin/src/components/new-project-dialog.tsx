import { Loader } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useI18n } from '@/lib/i18n-context';

interface NewProjectDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    name: string;
    onNameChange: (name: string) => void;
    creating: boolean;
    onConfirm: () => void;
}

export const NewProjectDialog = ({
    open,
    onOpenChange,
    name,
    onNameChange,
    creating,
    onConfirm,
}: NewProjectDialogProps) => {
    const { t } = useI18n();
    const canSubmit = Boolean(name.trim());

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-md">
                <DialogHeader>
                    <DialogTitle>{t('New project')}</DialogTitle>
                    <DialogDescription>
                        {t('Give your project a name. You can change it later in project settings.')}
                    </DialogDescription>
                </DialogHeader>
                <div className="space-y-2">
                    <Label htmlFor="new-project-name">{t('Project name')}</Label>
                    <Input
                        id="new-project-name"
                        value={name}
                        onChange={(e) => onNameChange(e.target.value)}
                        placeholder={t('e.g. Marketing, Legal, Support')}
                        autoFocus
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && canSubmit) {
                                onConfirm();
                            }
                        }}
                    />
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        {t('Cancel')}
                    </Button>
                    <Button
                        onClick={onConfirm}
                        disabled={creating || !canSubmit}
                    >
                        {creating && <Loader className="size-4 animate-spin" />}
                        {t('Create project')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};
