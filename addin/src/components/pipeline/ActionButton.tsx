import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Loader2, AlertCircle, SendHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api } from "@/api/endpoints";
import type { IntentAction } from "@/models/email";
import { t } from "@/lib/i18n";

interface Props {
    action: IntentAction;
    chatId: string;
    projectId?: string | null;
    value: string;
    onChange: (val: string) => void;
    siblingValues: Record<string, string>;
}

type State = "idle" | "loading" | "success" | "error";

async function fireWebhook(
    projectId: string | null | undefined,
    webhook: string,
    method: string,
    payload: Record<string, unknown>,
    headers: Record<string, string>,
    query: Record<string, unknown> = {},
    body: Record<string, unknown> = {},
): Promise<{ error: string | null }> {
    const result = await api.triggerAction(projectId ?? "", webhook, method, payload, headers, query, body);
    return { error: result.error };
}

export const ActionWidget = ({ action, chatId, projectId, value, onChange, siblingValues }: Props) => {
    const [state, setState] = useState<State>("idle");
    const [errorMsg, setErrorMsg] = useState("");
    const autoTriggeredRef = useRef(false);

    const effectiveType = action.type ?? "button";
    const runsImmediately = action.separateCall !== false;
    const isBusy = state === "loading";
    const isDone = state === "success";
    const isError = state === "error";

    // Fires the action's own webhook (used by button and separate-call elements)
    const triggerSeparate = useCallback(async (overrideValue?: string) => {
        if (!action.webhook) return;
        if (state === "loading" || state === "success") return;
        setState("loading");
        setErrorMsg("");

        const val = overrideValue ?? value;
        const basePayload: Record<string, unknown> = {
            ...(action.payload ?? {}),
            actionName: action.name,
            actionLabel: action.label,
            chatId,
        };

        let payload: Record<string, unknown>;
        if (effectiveType === "button") {
            // Collect all non-separate sibling values plus chatId
            payload = { ...basePayload, ...siblingValues };
        } else {
            // Separate-call element sends only its own value
            payload = { ...basePayload, [action.name]: val };
        }

        const result = await fireWebhook(
            projectId,
            action.webhook,
            action.method,
            payload,
            action.headers ?? {},
            action.query ?? {},
            action.body ?? {},
        );
        if (result.error) {
            setState("error");
            setErrorMsg(result.error);
            setTimeout(() => setState("idle"), 4000);
        } else {
            setState("success");
        }
    }, [
        action.headers,
        action.label,
        action.method,
        action.name,
        action.payload,
        action.query,
        action.body,
        action.webhook,
        chatId,
        effectiveType,
        projectId,
        siblingValues,
        state,
        value,
    ]);

    useEffect(() => {
        if (effectiveType === "button") return;
        if (!runsImmediately || !action.webhook) return;
        if (autoTriggeredRef.current) return;

        autoTriggeredRef.current = true;
        const timer = window.setTimeout(() => {
            void triggerSeparate();
        }, 0);
        return () => window.clearTimeout(timer);
    }, [action.webhook, effectiveType, runsImmediately, triggerSeparate, value]);

    // ── Button ────────────────────────────────────────────────────────────────
    if (effectiveType === "button") {
        return (
            <Button
                variant={isDone ? "outline" : "default"}
                size="sm"
                onClick={() => triggerSeparate()}
                disabled={isBusy || isDone}
                title={isError ? errorMsg : undefined}
                className="h-9 w-full justify-center shadow-sm"
            >
                {isBusy && <Loader2 className="size-3.5 animate-spin" />}
                {isDone && <Check className="size-3.5 text-green-600" />}
                {isError && <AlertCircle className="size-3.5 text-destructive" />}
                {action.label}
            </Button>
        );
    }

    // ── Shared status badge (used by input / dropdown / calendar) ─────────────
    const statusIcon = state === "loading"
        ? <Loader2 className="size-3.5 animate-spin text-muted-foreground" />
        : state === "success"
            ? <Check className="size-3.5 text-green-600" />
            : state === "error"
                ? <span title={errorMsg}><AlertCircle className="size-3.5 text-destructive" /></span>
                : null;

    const trailingControl = !runsImmediately ? (
        <Button
            variant="outline"
            size="default"
            onClick={() => triggerSeparate()}
            disabled={!action.webhook || isBusy || isDone}
            title={isError ? errorMsg : action.label}
            aria-label={action.label}
            className="size-9 shrink-0 justify-center p-0 shadow-xs"
        >
            {isBusy && <Loader2 className="size-3.5 animate-spin" />}
            {isDone && <Check className="size-3.5 text-green-600" />}
            {isError && <AlertCircle className="size-3.5 text-destructive" />}
            {!isBusy && !isDone && !isError && <SendHorizontal className="size-3.5" />}
        </Button>
    ) : statusIcon ? (
        <div className="flex h-9 w-9 shrink-0 items-center justify-center">
            {statusIcon}
        </div>
    ) : null;

    // ── Input ─────────────────────────────────────────────────────────────────
    if (effectiveType === "input") {
        return (
            <div className="space-y-1.5">
                <Label className="text-xs font-medium">{action.label}</Label>
                <div className="flex items-center gap-2">
                    <Input
                        value={value}
                        onChange={e => onChange(e.target.value)}
                        className="h-9 min-w-0 flex-1"
                    />
                    {trailingControl}
                </div>
            </div>
        );
    }

    // ── Dropdown ──────────────────────────────────────────────────────────────
    if (effectiveType === "dropdown") {
        return (
            <div className="space-y-1.5">
                <Label className="text-xs font-medium">{action.label}</Label>
                <div className="flex items-center gap-2 rounded-md">
                    <Select
                        value={value}
                        onValueChange={onChange}
                    >
                        <SelectTrigger className="h-9 min-w-0 flex-1 border-primary/20">
                            <SelectValue placeholder={t('pipeline.select')} />
                        </SelectTrigger>
                        <SelectContent>
                        {(action.options ?? []).map(opt => (
                            <SelectItem key={opt} value={opt}>{opt}</SelectItem>
                        ))}
                        </SelectContent>
                    </Select>
                    {trailingControl}
                </div>
            </div>
        );
    }

    // ── Calendar ──────────────────────────────────────────────────────────────
    const handleDateChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        onChange(e.target.value);
    };
    return (
        <div className="space-y-1.5">
            <Label className="text-xs font-medium">{action.label}</Label>
            <div className="flex items-center gap-2">
                <Input
                    type="date"
                    value={value}
                    onChange={handleDateChange}
                    className="h-9 min-w-0 flex-1"
                />
                {trailingControl}
            </div>
        </div>
    );
};
