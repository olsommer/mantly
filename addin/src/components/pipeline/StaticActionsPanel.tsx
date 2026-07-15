import { useCallback, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Sparkles } from "lucide-react";
import { IdentityPanel } from "@/components/pipeline/IdentityPanel";
import { IntentPanel } from "@/components/pipeline/IntentPanel";
import { ActionWidget } from "@/components/pipeline/ActionButton";
import type { IdentityResult, IntentResult } from "@/models/email";
import { t } from "@/lib/i18n";

interface StaticActionsPanelProps {
    identityResult?: IdentityResult;
    intentResult?: IntentResult;
    chatId: string;
    projectId?: string | null;
    responseRevealed: boolean;
    onRevealResponse: () => void;
}

export const StaticActionsPanel = ({
    identityResult,
    intentResult,
    chatId,
    projectId,
    responseRevealed,
    onRevealResponse,
}: StaticActionsPanelProps) => {
    // Action widget values (dropdowns, inputs, calendars) — owned here, passed to buttons as siblingValues
    const [actionValues, setActionValues] = useState<Record<string, string>>(
        () => Object.fromEntries(
            (intentResult?.actions ?? [])
                .filter(a => (a.type ?? 'button') !== 'button')
                .map(a => [a.name, a.initialValue ?? ''])
        )
    );
    const handleActionChange = useCallback(
        (name: string, val: string) => setActionValues(v => ({ ...v, [name]: val })),
        [],
    );

    const actions = intentResult?.actions ?? [];
    const inputActions = actions.filter(a => (a.type ?? 'button') !== 'button');
    const buttonActions = actions.filter(a => (a.type ?? 'button') === 'button');
    const responseEnabled = intentResult?.response?.enabled ?? false;
    const hasIdentityResult =
        !!identityResult &&
        (
            identityResult.customerFound ||
            !!identityResult.error ||
            Object.keys(identityResult.data ?? {}).length > 0 ||
            (identityResult.toolCallsMade ?? []).length > 0
        );
    const hasIntentControls =
        inputActions.length > 0 ||
        buttonActions.length > 0 ||
        (responseEnabled && !responseRevealed);

    return (
        <div className="bg-gray-50">
            {hasIdentityResult && <IdentityPanel identityResult={identityResult} />}
            {intentResult && (
                <IntentPanel intentResult={intentResult} collapsible={hasIntentControls}>
                    {hasIntentControls && (
                        <Card className="gap-2 rounded-md bg-background p-2 shadow-none">
                            <CardHeader className="px-0">
                                <CardTitle className="text-[11px] font-medium text-muted-foreground">
                                    {t('pipeline.actions')}
                                </CardTitle>
                            </CardHeader>
                            <CardContent className="space-y-2 px-0">
                            {inputActions.map(action => (
                                <ActionWidget
                                    key={action.name}
                                    action={action}
                                    chatId={chatId}
                                    projectId={projectId}
                                    value={actionValues[action.name] ?? ''}
                                    onChange={val => handleActionChange(action.name, val)}
                                    siblingValues={actionValues}
                                />
                            ))}
                            {buttonActions.map(action => (
                                <ActionWidget
                                    key={action.name}
                                    action={action}
                                    chatId={chatId}
                                    projectId={projectId}
                                    value=""
                                    onChange={() => {}}
                                    siblingValues={actionValues}
                                />
                            ))}
                            {responseEnabled && !responseRevealed && (
                                <Button variant="outline" size="sm" onClick={onRevealResponse} className="w-full">
                                    <Sparkles className="size-3.5 mr-1" />
                                    {t('pipeline.generateResponse')}
                                </Button>
                            )}
                            </CardContent>
                        </Card>
                    )}
                </IntentPanel>
            )}
        </div>
    );
};
