import { useState } from 'react';
import { ArrowRight, Download, Loader } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { api } from '@/api/endpoints';
import { PIPELINE_STEPS, SECTION_TO_PATH } from '@/app-navigation';
import { HintBanner } from '@/components/hint-banner';
import { Button } from '@/components/ui/button';
import { useI18n } from '@/lib/i18n-context';

export const PipelineOverview = ({
    tenantId,
    projectId,
    canDownloadManifest = true,
}: {
    tenantId: string;
    projectId: string;
    canDownloadManifest?: boolean;
}) => {
    const navigate = useNavigate();
    const [downloading, setDownloading] = useState(false);
    const { t } = useI18n();

    const handleDownloadManifest = () => {
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
        <div className="w-full max-w-4xl">
            <HintBanner storageKey="pipeline-overview" title={t('How support setup works')}>
                {t('Inbound messages become tickets, then customer identity and runbooks prepare triage, replies, actions, and evaluation proof across channels.')}
            </HintBanner>

            <div className="mb-6 mt-4">
                <h2 className="text-lg font-semibold mb-1">{t('AI setup')}</h2>
                <p className="text-sm text-muted-foreground">
                    {t('Configure identity rules, AI runbooks, and evaluation for ticket automation.')}
                </p>
            </div>
            <div className="flex items-stretch gap-3">
                {PIPELINE_STEPS.map((step, i) => (
                    <div key={step.id} className="flex items-center gap-3 flex-1">
                        <Button
                            type="button"
                            variant="outline"
                            onClick={() => navigate(`/${tenantId}/${projectId}/${SECTION_TO_PATH[step.id] ?? step.id}`)}
                            className="flex-1 h-full whitespace-normal flex-col items-start justify-start gap-0 rounded-xl bg-white p-5 text-left hover:border-foreground/30 hover:bg-white hover:shadow-sm group"
                        >
                            <div className="flex items-center gap-2 mb-3">
                                <span className="text-xs font-medium text-muted-foreground bg-muted rounded-full px-2 py-0.5">
                                    {step.step}
                                </span>
                                <step.icon className="size-4 text-muted-foreground group-hover:text-foreground transition-colors" />
                            </div>
                            <div className="font-semibold text-sm mb-1">{t(step.title)}</div>
                            <div className="text-xs text-muted-foreground leading-relaxed">
                                {t(step.description)}
                            </div>
                        </Button>
                        {i < PIPELINE_STEPS.length - 1 && (
                            <ArrowRight className="size-5 text-muted-foreground/40 shrink-0" />
                        )}
                    </div>
                ))}
            </div>

            {canDownloadManifest && (
                <div className="mt-8 pt-6 border-t">
                    <h3 className="text-sm font-medium mb-1">{t('Outlook Add-in')}</h3>
                    <p className="text-sm text-muted-foreground mb-3">
                        {t('Download the manifest and upload it to Microsoft 365 Admin Centre to deploy the add-in.')}
                    </p>
                    <Button variant="outline" onClick={handleDownloadManifest} disabled={downloading}>
                        {downloading
                            ? <Loader className="size-4 animate-spin" />
                            : <Download className="size-4" />}
                        {t('Download manifest.xml')}
                    </Button>
                </div>
            )}
        </div>
    );
};
