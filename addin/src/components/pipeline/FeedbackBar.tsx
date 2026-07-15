import { useCallback, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
    Field,
    FieldContent,
    FieldLabel,
    FieldTitle,
} from "@/components/ui/field";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Textarea } from "@/components/ui/textarea";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Megaphone, Loader, Check } from "lucide-react";
import type { IdentityResult, IntentResult } from "@/models/email";
import { useOffice } from "@/hooks/use-office";
import { api } from "@/api/endpoints";
import { toast } from "sonner";
import { t } from "@/lib/i18n";

interface FeedbackBarProps {
    projectId: string;
    chatId: string;
    identityResult?: IdentityResult;
    intentResult?: IntentResult;
    userOverride?: string | null;
}

type FeedbackState = "idle" | "submitting" | "submitted";

export const FeedbackBar = ({
    projectId,
    chatId,
    identityResult,
    intentResult,
    userOverride,
}: FeedbackBarProps) => {
    const { user } = useOffice();
    const feedbackUser = userOverride ?? user;
    const [state, setState] = useState<FeedbackState>("idle");
    const [feedbackOpen, setFeedbackOpen] = useState(false);
    const [selectedStage, setSelectedStage] = useState("");
    const [feedbackText, setFeedbackText] = useState("");
    const hasFeedbackText = feedbackText.trim().length > 0;

    // Build dynamic stage options from pipeline results
    const stageOptions = useMemo(() => {
        const options: { value: string; label: string }[] = [];

        if (identityResult) {
            options.push({
                value: "customer_identification",
                label: t("feedback.stageCustomer"),
            });
        }

        if (intentResult) {
            options.push({
                value: "intent_identification",
                label: t("feedback.stageIntent"),
            });

            for (const action of intentResult.actions) {
                options.push({
                    value: `action:${action.name}`,
                    label: action.label,
                });
            }

            if (intentResult.response?.enabled) {
                options.push({
                    value: "response_text",
                    label: t("feedback.stageResponse"),
                });
            }
        }

        return options;
    }, [identityResult, intentResult]);

    const handleFeedbackSubmit = useCallback(() => {
        if (!feedbackUser || !projectId || !chatId || !selectedStage || !feedbackText.trim()) return;
        setState("submitting");
        void api.submitFeedback(projectId, chatId, feedbackUser, "dislike", [selectedStage], feedbackText.trim()).then(resp => {
            if (resp.data) {
                setState("submitted");
                setFeedbackOpen(false);
                toast.success(t("feedback.success"));
            } else {
                setState("idle");
                toast.error(t("feedback.error"));
            }
        });
    }, [projectId, chatId, feedbackUser, selectedStage, feedbackText]);

    if (state === "submitted") {
        return (
            <div className="flex items-center justify-start gap-1.5 text-xs text-muted-foreground">
                <Check className="size-3.5" />
                {t("feedback.thankYou")}
            </div>
        );
    }

    return (
        <div className="flex items-center justify-start gap-2">
            <Button
                variant="ghost"
                size="sm"
                className="h-7 gap-1.5 px-2 text-muted-foreground hover:text-foreground"
                onClick={() => setFeedbackOpen(true)}
                disabled={state === "submitting" || !feedbackUser || !projectId || !chatId}
                title={t("feedback.thankYou")}
                aria-label={t("feedback.thankYou")}
            >
                {state === "submitting" ? (
                    <Loader className="size-3.5 animate-spin" />
                ) : (
                    <Megaphone className="size-3.5" />
                )}
                <span>{t("feedback.thankYou")}</span>
            </Button>

            <Dialog open={feedbackOpen} onOpenChange={setFeedbackOpen}>
                <DialogContent>
                    <DialogHeader className="text-left">
                        <DialogTitle>{t("feedback.title")}</DialogTitle>
                        <DialogDescription>{t("feedback.description")}</DialogDescription>
                    </DialogHeader>

                    <RadioGroup value={selectedStage} onValueChange={setSelectedStage}>
                        {stageOptions.map(option => (
                            <FieldLabel key={option.value} htmlFor={`stage-${option.value}`}>
                                <Field orientation="horizontal">
                                    <FieldContent>
                                        <FieldTitle>{option.label}</FieldTitle>
                                    </FieldContent>
                                    <RadioGroupItem id={`stage-${option.value}`} value={option.value} />
                                </Field>
                            </FieldLabel>
                        ))}
                    </RadioGroup>

                    <div className="space-y-1.5">
                        <Label htmlFor="feedback-text" className="text-sm">
                            {t("feedback.additionalDetails")}
                        </Label>
                        <Textarea
                            id="feedback-text"
                            placeholder={t("feedback.detailsPlaceholder")}
                            value={feedbackText}
                            onChange={e => setFeedbackText(e.target.value)}
                            required
                            rows={3}
                        />
                    </div>

                    <DialogFooter>
                        <Button
                            onClick={handleFeedbackSubmit}
                            disabled={state === "submitting" || !selectedStage || !hasFeedbackText}
                        >
                            {state === "submitting" ? (
                                <><Loader className="size-4 animate-spin" /> {t("feedback.submitting")}</>
                            ) : (
                                t("feedback.submit")
                            )}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
};
