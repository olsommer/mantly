import { type ReactNode, useState } from "react";
import { ChevronDown, ChevronRight, MessageSquareText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { t } from "@/lib/i18n";

interface Props {
    children: ReactNode;
    defaultOpen?: boolean;
}

export const ResponsePanel = ({ children, defaultOpen = true }: Props) => {
    const [open, setOpen] = useState(defaultOpen);

    return (
        <div className="flex min-h-0 flex-1 flex-col border-b bg-gray-50">
            <Button
                type="button"
                variant="ghost"
                onClick={() => setOpen(o => !o)}
                className="h-auto w-full justify-start gap-2 rounded-none px-2 py-2 text-sm has-[>svg]:px-2"
            >
                {open ? (
                    <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
                ) : (
                    <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
                )}
                <MessageSquareText className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="font-medium text-muted-foreground">{t('pipeline.response')}</span>
            </Button>

            {open ? (
                <div className="flex min-h-0 flex-1 overflow-y-auto">
                    {children}
                </div>
            ) : null}
        </div>
    );
};
