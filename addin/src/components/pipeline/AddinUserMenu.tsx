import { useEffect, useMemo, useState } from "react";
import { BarChart3, ExternalLink, LogIn, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { settings } from "@/settings";
import { useOffice } from "@/hooks/use-office";
import { t } from "@/lib/i18n";

interface SessionInfo {
    email: string;
    tenantId: string;
    isAuthenticated: boolean;
}

const decodeJwtPayload = (token: string | null): Record<string, unknown> | null => {
    if (!token) return null;

    try {
        const [, payload] = token.split(".");
        if (!payload) return null;
        const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
        const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
        return JSON.parse(window.atob(padded)) as Record<string, unknown>;
    } catch {
        return null;
    }
};

const readSession = (): SessionInfo => {
    const token = localStorage.getItem("auth_token");
    const payload = decodeJwtPayload(token);
    const exp = typeof payload?.exp === "number" ? payload.exp : 0;
    const isExpired = exp > 0 && exp * 1000 <= Date.now();
    const email = typeof payload?.email === "string" ? payload.email : localStorage.getItem("auth_email") ?? "";
    const tenantId = typeof payload?.tenant_id === "string" ? payload.tenant_id : "";

    return {
        email: isExpired ? "" : email,
        tenantId: isExpired ? "" : tenantId,
        isAuthenticated: !!token && !isExpired && !!email,
    };
};

const compactEmail = (email: string | null): string => {
    if (!email) return t("pipeline.user");
    if (email.length <= 24) return email;
    const [name, domain] = email.split("@");
    if (!domain) return `${email.slice(0, 21)}...`;
    return `${name.slice(0, 10)}...@${domain}`;
};

const openExternal = (url: string) => {
    if (typeof Office !== "undefined" && Office.context?.ui?.openBrowserWindow) {
        Office.context.ui.openBrowserWindow(url);
        return;
    }

    window.open(url, "_blank", "noopener,noreferrer");
};

export const AddinUserMenu = () => {
    const { user } = useOffice();
    const [session, setSession] = useState<SessionInfo>(() => readSession());

    useEffect(() => {
        const syncSession = () => setSession(readSession());
        window.addEventListener("auth:session-changed", syncSession);
        window.addEventListener("storage", syncSession);
        return () => {
            window.removeEventListener("auth:session-changed", syncSession);
            window.removeEventListener("storage", syncSession);
        };
    }, []);

    const adminBaseUrl = settings.adminBaseUrl.replace(/\/+$/, "");
    const email = session.email || user || "";
    const accountLabel = session.isAuthenticated ? email : t("pipeline.notSignedIn");
    const urls = useMemo(() => ({
        login: `${adminBaseUrl}/?view=login`,
        admin: adminBaseUrl,
        usage: session.tenantId ? `${adminBaseUrl}/${session.tenantId}/billing` : adminBaseUrl,
    }), [adminBaseUrl, session.tenantId]);

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 max-w-[11rem] gap-1.5 px-2"
                >
                    <User className="size-3.5 shrink-0" />
                    <span className="truncate text-xs">{compactEmail(email)}</span>
                </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" side="top" className="w-48">
                <DropdownMenuLabel className="truncate text-xs font-normal text-muted-foreground">
                    {accountLabel}
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                {!session.isAuthenticated && (
                    <DropdownMenuItem onSelect={() => openExternal(urls.login)}>
                        <LogIn className="size-3.5" />
                        {t("pipeline.login")}
                    </DropdownMenuItem>
                )}
                <DropdownMenuItem onSelect={() => openExternal(urls.admin)}>
                    <ExternalLink className="size-3.5" />
                    {t("pipeline.openAdmin")}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => openExternal(urls.usage)} disabled={!session.isAuthenticated || !session.tenantId}>
                    <BarChart3 className="size-3.5" />
                    {t("pipeline.usage")}
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    );
};
