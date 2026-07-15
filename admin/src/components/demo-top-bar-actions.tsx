import { useCallback, useEffect, useState } from 'react';
import { Download, Loader, Rocket } from 'lucide-react';
import { toast } from 'sonner';

import { api } from '@/api/endpoints';
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { useI18n } from '@/lib/i18n-context';

const DownloadManifestButton = ({ projectId }: { projectId: string | null }) => {
    const [downloading, setDownloading] = useState(false);
    const { t } = useI18n();

    const handleDownload = () => {
        if (!projectId) return;
        setDownloading(true);
        api.downloadManifest(projectId).then(() => {
            toast.success(t('Manifest downloaded'));
        }).catch(() => {
            toast.error(t('Manifest download failed'));
        }).finally(() => {
            setDownloading(false);
        });
    };

    return (
        <Button
            variant="ghost"
            size="sm"
            disabled={downloading || !projectId}
            className="text-muted-foreground"
            onClick={handleDownload}
        >
            {downloading ? <Loader className="size-4 animate-spin" /> : <Download className="size-4" />}
            {t('Download manifest')}
        </Button>
    );
};

const PublishButton = ({ projectId }: { projectId: string | null }) => {
    const [dirty, setDirty] = useState(false);
    const [publishing, setPublishing] = useState(false);
    const { t } = useI18n();

    const checkStatus = useCallback(() => {
        if (!projectId) return;
        void api.getPublishStatus(projectId).then(res => {
            if (res.data) setDirty(res.data.hasUnpublishedChanges);
        });
    }, [projectId]);

    useEffect(() => {
        checkStatus();
        const id = setInterval(checkStatus, 15_000);
        const onDraftChanged = () => checkStatus();
        window.addEventListener('admin:draft-changed', onDraftChanged);
        return () => {
            clearInterval(id);
            window.removeEventListener('admin:draft-changed', onDraftChanged);
        };
    }, [checkStatus]);

    const handlePublish = async () => {
        if (!projectId) return;
        setPublishing(true);
        try {
            const res = await api.publish(projectId);
            if (res.error) {
                toast.error(res.error);
            } else {
                toast.success(t('Published successfully'));
                setDirty(false);
            }
        } finally {
            setPublishing(false);
        }
    };

    const disabled = publishing || !dirty || !projectId;

    return (
        <AlertDialog>
            <AlertDialogTrigger asChild>
                <Button
                    variant="ghost"
                    size="sm"
                    disabled={disabled}
                    className="text-muted-foreground relative"
                >
                    {publishing ? <Loader className="size-4 animate-spin" /> : <Rocket className="size-4" />}
                    {t('Publish')}
                    {dirty && (
                        <span className="absolute top-1 right-1 size-2 rounded-full bg-orange-400" />
                    )}
                </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>{t('Publish changes')}</AlertDialogTitle>
                    <AlertDialogDescription>
                        {t('This will publish all draft changes to the live support setup. Incoming messages will immediately be processed with the updated configuration.')}
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogCancel>{t('Cancel')}</AlertDialogCancel>
                    <AlertDialogAction onClick={handlePublish}>{t('Publish')}</AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
};

export const DemoTopBarActions = ({
    projectId,
    canDownloadManifest,
    canPublish,
}: {
    projectId: string | null;
    canDownloadManifest: boolean;
    canPublish: boolean;
}) => (
    <>
        {canDownloadManifest && (
            <DownloadManifestButton projectId={projectId} />
        )}
        {canPublish && (
            <PublishButton projectId={projectId} />
        )}
    </>
);
