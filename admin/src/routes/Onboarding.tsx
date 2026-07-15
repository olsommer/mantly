import { useState } from 'react';
import { ArrowRight, Check, FlaskConical, Loader, Sparkles, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Separator } from '@/components/ui/separator';
import { api } from '@/api/endpoints';
import { brand } from '@/brand';
import { settings } from '@/settings';
import { DEMO_CRM_TOOL, DEMO_INTENT_NAME, DEMO_INTENT_YAML } from '@/demo/pipeline';
import { useI18n } from '@/lib/i18n-context';

interface OnboardingProps {
    projectId: string;
    onComplete: () => void;
    onDismiss: () => void;
}

type Step = 'welcome' | 'profile' | 'intent' | 'done';

const STEPS: Step[] = ['welcome', 'profile', 'intent', 'done'];

const STEP_LABELS: Record<Step, string> = {
    welcome: 'Welcome',
    profile: 'Organisation',
    intent: 'First runbook',
    done: 'Ready',
};

const stepIndex = (s: Step) => STEPS.indexOf(s);

const yamlString = (value: string) => JSON.stringify(value);

// ── Step: Welcome ─────────────────────────────────────────────────────────────

const WelcomeStep = ({ onNext }: { onNext: () => void }) => {
    const { t } = useI18n();

    return (
        <div className="flex flex-col items-center text-center gap-6">
            <div className="rounded-full bg-indigo-100 p-4">
                <Sparkles className="size-8 text-indigo-600" />
            </div>
            <div>
                <h2 className="text-xl font-bold mb-2">{t('Welcome to {title}', { title: brand.adminTitle })}</h2>
                <p className="text-sm text-muted-foreground max-w-sm">
                    {t("Let's set up your support workspace in two quick steps. It only takes about two minutes.")}
                </p>
            </div>
            <div className="flex flex-col gap-2 w-full max-w-xs text-sm text-left">
                {[
                    { n: 1, label: 'Name your organisation', desc: "So the AI knows who it's representing" },
                    { n: 2, label: 'Create your first runbook', desc: 'Tell the agent when and how to respond' },
                ].map(({ n, label, desc }) => (
                    <div key={n} className="flex items-start gap-3 rounded-lg border bg-white p-3">
                        <span className="shrink-0 size-5 rounded-full bg-indigo-600 text-white text-xs flex items-center justify-center font-medium mt-0.5">
                            {n}
                        </span>
                        <div>
                            <div className="font-medium">{t(label)}</div>
                            <div className="text-xs text-muted-foreground">{t(desc)}</div>
                        </div>
                    </div>
                ))}
            </div>
            <Button onClick={onNext} className="gap-2">
                {t('Get started')} <ArrowRight className="size-4" />
            </Button>
        </div>
    );
};

// ── Step: Org profile ─────────────────────────────────────────────────────────

const ProfileStep = ({ projectId, onNext }: { projectId: string; onNext: () => void }) => {
    const { t } = useI18n();
    const [orgName, setOrgName] = useState('');
    const [orgDescription, setOrgDescription] = useState('');
    const [saving, setSaving] = useState(false);

    const handleNext = async () => {
        if (!orgName.trim()) {
            toast.error(t('Please enter your organisation name.'));
            return;
        }
        setSaving(true);
        const res = await api.updateAdminConfig(projectId, { orgName: orgName.trim(), orgDescription: orgDescription.trim() });
        if (res.error) {
            toast.error(t("Couldn't save: {error}", { error: res.error }));
            setSaving(false);
            return;
        }
        onNext();
    };

    return (
        <div className="flex flex-col gap-6 w-full max-w-sm">
            <div>
                <h2 className="text-xl font-bold mb-1">{t('Name your organisation')}</h2>
                <p className="text-sm text-muted-foreground">
                    {t('The AI uses this as context when writing responses on your behalf.')}
                </p>
            </div>

            <div className="space-y-4">
                <div className="space-y-1.5">
                    <Label htmlFor="onb-orgName">{t('Organisation name')}</Label>
                    <Input
                        id="onb-orgName"
                        value={orgName}
                        onChange={e => setOrgName(e.target.value)}
                        placeholder="Kanzlei Müller & Partner"
                        autoFocus
                    />
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor="onb-orgDesc">
                        {t('What does your organisation do?')}{' '}
                        <span className="font-normal text-muted-foreground">{t('(optional)')}</span>
                    </Label>
                    <Textarea
                        id="onb-orgDesc"
                        value={orgDescription}
                        onChange={e => setOrgDescription(e.target.value)}
                        placeholder="A law firm specialising in corporate law and M&A transactions, serving mid-sized German companies."
                        rows={3}
                    />
                </div>
            </div>

            <Button onClick={handleNext} disabled={saving} className="gap-2 self-start">
                {saving ? <Loader className="size-4 animate-spin" /> : <ArrowRight className="size-4" />}
                {t('Next')}
            </Button>
        </div>
    );
};

// ── Step: Create first runbook ────────────────────────────────────────────────

const IntentStep = ({ projectId, onNext }: { projectId: string; onNext: () => void }) => {
    const { t } = useI18n();
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [instructions, setInstructions] = useState('');
    const [saving, setSaving] = useState(false);
    const [loadingDemo, setLoadingDemo] = useState(false);

    const handleSave = async () => {
        const slug = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
        if (!slug) { toast.error(t('Runbook name is required.')); return; }
        if (!description.trim()) { toast.error(t('Description is required.')); return; }

        const matchDescription = [
            description.trim(),
            'Match tickets where the sender asks for this service, sends a request, asks for next steps, asks what documents are needed, or expects a written reply from the organisation.',
            'Match the meaning of the request, not only exact keywords. Use the examples and wording in the description as the strongest signal.',
            `The internal runbook name "${name.trim()}" is only a label; do not require the sender to use it literally.`,
        ].join(' ');
        const responseRules = [
            instructions.trim() || 'Draft a helpful first response for this ticket type.',
            'Acknowledge the request in the sender’s language.',
            'Summarise what the sender needs in one or two sentences.',
            'Ask for missing context or documents if needed.',
            'State the next step clearly and keep the tone professional.',
            'Do not invent facts, deadlines, prices, or legal advice.',
        ];
        const responseRulesYaml = responseRules.map(rule => `    - ${yamlString(rule)}`).join('\n');
        const body = [
            '# Matching guidance',
            '',
            `Activate this runbook when an incoming ticket fits this situation: ${description.trim()}`,
            '',
            'Typical signals:',
            '- The sender describes the same need in their own words, even if they do not use the runbook name.',
            '- The sender mentions one of the examples, topics, documents, services, or next steps from the description.',
            '- The sender asks what happens next, what information is needed, or whether the organisation can help.',
            '- The email should receive a prepared answer that a human can review before sending.',
            '',
            'Do not activate this runbook for unrelated newsletters, spam, invoices without a request, or internal messages.',
            '',
            '# Response guidance',
            '',
            ...responseRules.map(rule => `- ${rule}`),
        ].join('\n');
        const content = [
            '---',
            `name: ${slug}`,
            `description: ${yamlString(matchDescription)}`,
            'active: true',
            'require_review: false',
            'response:',
            '  enabled: true',
            '  auto: true',
            '  response_rules:',
            responseRulesYaml,
            'actions: []',
            '---',
            '',
            body,
        ].join('\n');

        setSaving(true);
        const res = await api.upsertIntent(projectId, slug, content);
        if (res.error) {
            toast.error(t("Couldn't save runbook: {error}", { error: res.error }));
            setSaving(false);
            return;
        }
        toast.success(t('Runbook created!'));
        onNext();
    };

    const handleLoadDemo = async () => {
        setLoadingDemo(true);

        // 1. Configure the demo CRM tool
        const toolRes = await api.updateAdminConfig(projectId, { tool: DEMO_CRM_TOOL });
        if (toolRes.error) {
            toast.error(t("Couldn't configure demo CRM: {error}", { error: toolRes.error }));
            setLoadingDemo(false);
            return;
        }

        // 2. Create the demo runbook
        const intentRes = await api.upsertIntent(projectId, DEMO_INTENT_NAME, DEMO_INTENT_YAML);
        if (intentRes.error) {
            toast.error(t("Couldn't create demo runbook: {error}", { error: intentRes.error }));
            setLoadingDemo(false);
            return;
        }

        toast.success(t('Demo support setup loaded!'));
        onNext();
    };

    const busy = saving || loadingDemo;

    return (
        <div className="flex flex-col gap-6 w-full max-w-sm">
            <div>
                <h2 className="text-xl font-bold mb-1">{t('Create your first runbook')}</h2>
                <p className="text-sm text-muted-foreground">
                    {t('A runbook tells the agent which tickets to handle and how to respond to them.')}
                </p>
            </div>

            <div className="space-y-4">
                <div className="space-y-1.5">
                    <Label htmlFor="onb-intentName">{t('Runbook name')}</Label>
                    <Input
                        id="onb-intentName"
                        value={name}
                        onChange={e => setName(e.target.value)}
                        placeholder="e.g. company-foundation"
                        autoFocus
                    />
                    <p className="text-xs text-muted-foreground">{t('Used as a slug. Spaces become hyphens.')}</p>
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor="onb-intentDesc">{t('When should this runbook match?')}</Label>
                    <Input
                        id="onb-intentDesc"
                        value={description}
                        onChange={e => setDescription(e.target.value)}
                        placeholder="e.g. Client enquiry about founding a new company"
                    />
                    <p className="text-xs text-muted-foreground">
                        {t('The agent uses this to decide whether a ticket matches this runbook.')}
                    </p>
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor="onb-intentInstr">
                        {t('Response instructions')}{' '}
                        <span className="font-normal text-muted-foreground">{t('(optional - you can edit later)')}</span>
                    </Label>
                    <Textarea
                        id="onb-intentInstr"
                        value={instructions}
                        onChange={e => setInstructions(e.target.value)}
                        placeholder={"Acknowledge the request.\nAsk for missing documents or context.\nExplain the next step and keep the answer short."}
                        rows={4}
                    />
                </div>
            </div>

            <div className="flex items-center gap-2">
                <Button onClick={handleSave} disabled={busy} className="gap-2">
                    {saving ? <Loader className="size-4 animate-spin" /> : <Check className="size-4" />}
                    {t('Create runbook')}
                </Button>
                <Button variant="ghost" onClick={onNext} disabled={busy} className="text-muted-foreground">
                    {t('Skip for now')}
                </Button>
            </div>

            {settings.enableDemoMode && (
                <>
                    <Separator />

                    <div className="rounded-lg border border-dashed bg-muted/30 p-4 space-y-2">
                        <div className="flex items-center gap-2">
                            <FlaskConical className="size-4 text-indigo-500" />
                            <span className="text-sm font-medium">{t('Try with demo data')}</span>
                        </div>
                        <p className="text-xs text-muted-foreground">
                            {t('Creates a working demo support setup with a CRM lookup and a sample legal-intake runbook so you can test the ticket flow immediately.')}
                        </p>
                        <Button variant="outline" size="sm" onClick={handleLoadDemo} disabled={busy} className="gap-2">
                            {loadingDemo ? <Loader className="size-4 animate-spin" /> : <FlaskConical className="size-4" />}
                            {t('Load demo support setup')}
                        </Button>
                    </div>
                </>
            )}
        </div>
    );
};

// ── Step: Done ────────────────────────────────────────────────────────────────

const DoneStep = ({ onComplete }: { onComplete: () => void }) => {
    const { t } = useI18n();

    return (
        <div className="flex flex-col items-center text-center gap-6">
            <div className="rounded-full bg-green-100 p-4">
                <Check className="size-8 text-green-600" />
            </div>
            <div>
                <h2 className="text-xl font-bold mb-2">{t("You're all set!")}</h2>
                <p className="text-sm text-muted-foreground max-w-sm">
                    {t('Your support inbox is ready. You can refine runbooks, customer identity, channels, and approval workflows from the admin app.')}
                </p>
            </div>
            <Button onClick={onComplete} className="gap-2">
                {t('Go to dashboard')} <ArrowRight className="size-4" />
            </Button>
        </div>
    );
};

// ── Wizard shell ──────────────────────────────────────────────────────────────

export const Onboarding = ({ projectId, onComplete, onDismiss }: OnboardingProps) => {
    const { t } = useI18n();
    const [step, setStep] = useState<Step>('welcome');

    const next = () => {
        const idx = stepIndex(step);
        if (idx < STEPS.length - 1) setStep(STEPS[idx + 1]);
    };

    return (
        <div className="fixed inset-0 z-50 bg-gray-50 flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b bg-white">
                <span className="text-sm font-semibold text-gray-900">{t('Setup wizard')}</span>
                <div className="flex items-center gap-4">
                    {/* Progress dots */}
                    <div className="flex items-center gap-1.5">
                        {STEPS.filter(s => s !== 'done').map(s => (
                            <div
                                key={s}
                                className={`size-2 rounded-full transition-colors ${
                                    stepIndex(step) >= stepIndex(s)
                                        ? 'bg-indigo-600'
                                        : 'bg-gray-200'
                                }`}
                                title={t(STEP_LABELS[s])}
                            />
                        ))}
                    </div>
                    {step !== 'done' && (
                        <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            onClick={onDismiss}
                            className="text-muted-foreground hover:text-foreground"
                            title={t('Skip setup')}
                        >
                            <X className="size-4" />
                        </Button>
                    )}
                </div>
            </div>

            {/* Content */}
            <div className="flex-1 flex items-center justify-center px-6 py-12">
                {step === 'welcome' && <WelcomeStep onNext={next} />}
                {step === 'profile' && <ProfileStep projectId={projectId} onNext={next} />}
                {step === 'intent'  && <IntentStep projectId={projectId} onNext={next} />}
                {step === 'done'    && <DoneStep onComplete={onComplete} />}
            </div>
        </div>
    );
};
