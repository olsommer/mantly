import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import type { PhishingResult, PromptInjectionResult } from "@/models/email";
import { TriangleAlert } from "lucide-react";
import { t } from "@/lib/i18n";

type RiskResult = PhishingResult | PromptInjectionResult;

type RiskItem = {
    kind: "phishing" | "prompt";
    title: string;
    result: RiskResult;
};

type Props = {
    phishingResult?: PhishingResult;
    promptInjectionResult?: PromptInjectionResult;
};

function isRisk(result?: RiskResult): result is RiskResult {
    return !!result?.enabled && result.riskLevel !== "none";
}

function riskTone(level: RiskResult["riskLevel"]): string {
    if (level === "high") return "text-red-700 border-red-200 bg-red-50";
    if (level === "medium") return "text-amber-800 border-amber-200 bg-amber-50";
    return "text-yellow-800 border-yellow-200 bg-yellow-50";
}

function riskLabel(item: RiskItem): string {
    return item.kind === "phishing" ? "Phishing" : t("security.promptInjection");
}

function RiskSection({ item }: { item: RiskItem }) {
    const { result } = item;
    return (
        <div className="rounded-md border p-3">
            <div className="flex items-start justify-between gap-3">
                <div>
                    <h3 className="text-sm font-semibold">{item.title}</h3>
                    <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                        {result.reason || t("security.fallbackReason")}
                    </p>
                </div>
                <span className={cn("shrink-0 rounded-full border px-2 py-0.5 text-xs font-medium", riskTone(result.riskLevel))}>
                    {result.riskLevel} · {result.score}/100
                </span>
            </div>
            {result.indicators.length > 0 && (
                <ul className="mt-3 list-disc space-y-1 pl-4 text-xs text-muted-foreground">
                    {result.indicators.map((indicator, index) => (
                        <li key={`${item.kind}-${indicator}-${index}`}>{indicator}</li>
                    ))}
                </ul>
            )}
        </div>
    );
}

export function SecurityRiskBanner({ phishingResult, promptInjectionResult }: Props) {
    const risks: RiskItem[] = [
        ...(isRisk(phishingResult)
            ? [{ kind: "phishing" as const, title: t("security.phishingRisk"), result: phishingResult }]
            : []),
        ...(isRisk(promptInjectionResult)
            ? [{ kind: "prompt" as const, title: t("security.promptRisk"), result: promptInjectionResult }]
            : []),
    ];

    if (risks.length === 0) return null;

    const summary = risks.map(riskLabel).join(" + ");

    return (
        <Dialog>
            <DialogTrigger asChild>
                <Button
                    type="button"
                    variant="outline"
                    className="h-7 w-full justify-start rounded-none border-0 border-b border-amber-200 bg-amber-50/70 px-0 py-0 text-left text-xs text-amber-950 shadow-none has-[>svg]:px-2 hover:bg-amber-50 hover:text-amber-950"
                >
                    <TriangleAlert className="size-3.5 shrink-0 text-amber-600" />
                    <span className="min-w-0 flex-1 truncate font-normal">
                        <span className="font-medium">{t("security.check")}</span> {t("security.flagged", { summary })}
                    </span>
                    <span className="shrink-0 text-[11px] font-normal text-amber-800">{t("security.details")}</span>
                </Button>
            </DialogTrigger>
            <DialogContent className="max-w-md">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <TriangleAlert className="size-5 text-amber-600" />
                        {t("security.detected")}
                    </DialogTitle>
                    <DialogDescription>
                        {t("security.warningOnly")}
                    </DialogDescription>
                </DialogHeader>
                <div className="space-y-3">
                    {risks.map(item => (
                        <RiskSection key={item.kind} item={item} />
                    ))}
                </div>
            </DialogContent>
        </Dialog>
    );
}
