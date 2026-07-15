import { type ReactNode, useState } from "react";
import { Tag, ChevronDown, ChevronRight, AlertCircle, Minus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { IntentResult } from "@/models/email";
import { t } from "@/lib/i18n";

interface Props {
    intentResult: IntentResult;
    children?: ReactNode;
    collapsible?: boolean;
}

export const IntentPanel = ({ intentResult, children, collapsible = false }: Props) => {
    const [open, setOpen] = useState(() => collapsible);
    const headerContent = (
        <>
            {collapsible ? (
                open ? (
                    <ChevronDown className="size-3.5 text-muted-foreground shrink-0" />
                ) : (
                    <ChevronRight className="size-3.5 text-muted-foreground shrink-0" />
                )
            ) : (
                <Minus className="size-3.5 text-muted-foreground shrink-0" />
            )}
            <Tag className="size-3.5 shrink-0 text-muted-foreground" />
            <span className="font-medium text-muted-foreground">{t('pipeline.intent')}</span>
            <span
                className={cn(
                    "ml-auto rounded-full px-1.5 py-0.5 text-[10px] font-medium leading-none",
                    intentResult.matched
                        ? "bg-blue-100 text-blue-700"
                        : "bg-muted text-muted-foreground"
                )}
            >
                {intentResult.matched && intentResult.intentName
                    ? intentResult.intentName
                    : t('pipeline.noMatch')}
            </span>
        </>
    );
    const headerClassName = "h-auto w-full justify-start gap-2 rounded-none px-2 py-2 text-sm has-[>svg]:px-2";

    return (
        <div className="border-b">
            {collapsible ? (
                <Button
                    type="button"
                    variant="ghost"
                    onClick={() => setOpen(o => !o)}
                    className={headerClassName}
                >
                    {headerContent}
                </Button>
            ) : (
                <div className={cn("flex items-center", headerClassName)}>
                    {headerContent}
                </div>
            )}

            {collapsible && open && (
                <div className="px-2 pb-3 space-y-1.5">
                    {intentResult.error && (
                        <div className="flex items-center gap-1.5 text-xs text-destructive">
                            <AlertCircle className="size-3" />
                            <span>{intentResult.error}</span>
                        </div>
                    )}
                    {!intentResult.matched && !intentResult.error && (
                        <p className="text-xs text-muted-foreground italic">
                            {t('pipeline.noIntentMatch')}
                        </p>
                    )}
                    {children ? (
                        <div className="space-y-3 pt-2">
                            {children}
                        </div>
                    ) : null}
                </div>
            )}
        </div>
    );
};
