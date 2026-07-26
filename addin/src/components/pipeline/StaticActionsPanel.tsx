import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Sparkles } from "lucide-react";
import { IdentityPanel } from "@/components/pipeline/IdentityPanel";
import { IntentPanel } from "@/components/pipeline/IntentPanel";
import { ActionWidget } from "@/components/pipeline/ActionButton";
import type { IdentityResult, IntentAction, IntentResult } from "@/models/email";
import { t } from "@/lib/i18n";

interface ScopedIntentAction {
    key: string;
    action: IntentAction;
}

interface IntentActionGroup {
    key: string;
    label?: string;
    actions: ScopedIntentAction[];
}

const buildActionGroups = (intentResult?: IntentResult): IntentActionGroup[] => {
    const concernGroups = (intentResult?.concerns ?? []).flatMap((concern, concernIndex) => {
        if (concern.actions.length === 0) return [];

        const concernKey = concern.concernId.trim() || `concern-${concernIndex + 1}`;
        return [{
            key: concernKey,
            label: concern.intentName?.trim() || concern.concernSummary?.trim() || concernKey,
            actions: concern.actions.map((action, actionIndex) => ({
                key: `${concernKey}:${action.name}:${actionIndex}`,
                action,
            })),
        }];
    });

    if (concernGroups.length > 0) return concernGroups;

    const legacyActions = intentResult?.actions ?? [];
    if (legacyActions.length === 0) return [];
    return [{
        key: "legacy",
        actions: legacyActions.map((action, actionIndex) => ({
            key: `legacy:${action.name}:${actionIndex}`,
            action,
        })),
    }];
};

const initialActionValues = (groups: IntentActionGroup[]): Record<string, string> => Object.fromEntries(
    groups.flatMap(group => group.actions)
        .filter(({ action }) => (action.type ?? 'button') !== 'button')
        .map(({ key, action }) => [key, action.initialValue ?? '']),
);

interface StaticActionsPanelProps {
    identityResult?: IdentityResult;
    intentResult?: IntentResult;
    chatId: string;
    projectId?: string | null;
    responseRevealed: boolean;
    hasComposedResponse?: boolean;
    onRevealResponse: () => void;
}

export const StaticActionsPanel = ({
    identityResult,
    intentResult,
    chatId,
    projectId,
    responseRevealed,
    hasComposedResponse = false,
    onRevealResponse,
}: StaticActionsPanelProps) => {
    const actionGroups = useMemo(() => buildActionGroups(intentResult), [intentResult]);

    // Action widget values (dropdowns, inputs, calendars) — owned here, passed to buttons as siblingValues
    const [actionValues, setActionValues] = useState<Record<string, string>>(
        () => initialActionValues(actionGroups),
    );

    useEffect(() => {
        setActionValues(initialActionValues(actionGroups));
    }, [actionGroups]);

    const handleActionChange = useCallback(
        (key: string, val: string) => setActionValues(v => ({ ...v, [key]: val })),
        [],
    );

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
        actionGroups.length > 0 ||
        (responseEnabled && !responseRevealed && !hasComposedResponse);

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
                            {actionGroups.map(group => {
                                const inputActions = group.actions.filter(
                                    ({ action }) => (action.type ?? 'button') !== 'button',
                                );
                                const buttonActions = group.actions.filter(
                                    ({ action }) => (action.type ?? 'button') === 'button',
                                );
                                const siblingValues = Object.fromEntries(
                                    inputActions.map(({ key, action }) => [action.name, actionValues[key] ?? '']),
                                );

                                return (
                                    <div key={group.key} className="space-y-2">
                                        {group.label && (
                                            <p className="text-[11px] font-medium text-muted-foreground">
                                                {group.label}
                                            </p>
                                        )}
                                        {inputActions.map(({ key, action }) => (
                                            <ActionWidget
                                                key={key}
                                                action={action}
                                                chatId={chatId}
                                                projectId={projectId}
                                                value={actionValues[key] ?? ''}
                                                onChange={val => handleActionChange(key, val)}
                                                siblingValues={siblingValues}
                                            />
                                        ))}
                                        {buttonActions.map(({ key, action }) => (
                                            <ActionWidget
                                                key={key}
                                                action={action}
                                                chatId={chatId}
                                                projectId={projectId}
                                                value=""
                                                onChange={() => {}}
                                                siblingValues={siblingValues}
                                            />
                                        ))}
                                    </div>
                                );
                            })}
                            {responseEnabled && !responseRevealed && !hasComposedResponse && (
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
