import { Fragment, useState } from "react";
import { User, ChevronDown, ChevronRight, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { IdentityResult } from "@/models/email";
import { t } from "@/lib/i18n";

interface Props {
    identityResult: IdentityResult;
}

export const IdentityPanel = ({ identityResult }: Props) => {
    const [open, setOpen] = useState(false);
    const dataEntries = Object.entries(identityResult.data ?? {});

    return (
        <div className="border-b">
            <Button
                type="button"
                variant="ghost"
                onClick={() => setOpen(o => !o)}
                className="h-auto w-full justify-start gap-2 rounded-none px-2 py-2 text-sm has-[>svg]:px-2"
            >
                {open ? (
                    <ChevronDown className="size-3.5 text-muted-foreground shrink-0" />
                ) : (
                    <ChevronRight className="size-3.5 text-muted-foreground shrink-0" />
                )}
                <User className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="font-medium text-muted-foreground">{t('pipeline.customer')}</span>
                <span
                    role="status"
                    aria-label={identityResult.error ? t('pipeline.error') : identityResult.customerFound ? t('pipeline.found') : t('pipeline.notFound')}
                    className={cn(
                        "ml-auto size-2.5 rounded-full",
                        identityResult.error
                            ? "bg-red-500"
                            : identityResult.customerFound
                                ? "bg-green-500"
                                : "bg-amber-400"
                    )}
                />
            </Button>

            {open && (
                <div className="px-2 pb-3 space-y-1.5">
                    {identityResult.error && (
                        <div className="flex items-center gap-1.5 text-xs text-destructive">
                            <AlertCircle className="size-3" />
                            <span>{identityResult.error}</span>
                        </div>
                    )}
                    {dataEntries.length > 0 ? (
                        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                            {dataEntries.map(([key, value]) => (
                                <Fragment key={key}>
                                    <dt className="text-muted-foreground font-medium capitalize">
                                        {key.replace(/_/g, " ")}
                                    </dt>
                                    <dd className="truncate">
                                        {String(value)}
                                    </dd>
                                </Fragment>
                            ))}
                        </dl>
                    ) : (
                        <p className="text-xs text-muted-foreground italic">{t('pipeline.noCustomerData')}</p>
                    )}
                </div>
            )}
        </div>
    );
};
