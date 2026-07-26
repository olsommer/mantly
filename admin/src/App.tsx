import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { Routes, Route, Navigate, useLocation, useNavigate, matchPath } from 'react-router-dom';
import { Loader } from 'lucide-react';
import { toast } from 'sonner';
import { Separator } from './components/ui/separator';
import { SidebarInset, SidebarProvider, SidebarTrigger } from './components/ui/sidebar';
import { TooltipProvider } from './components/ui/tooltip';
import {
    Breadcrumb,
    BreadcrumbItem,
    BreadcrumbList,
    BreadcrumbPage,
} from './components/ui/breadcrumb';
import type { SidebarIntent, UserRole } from './components/app-sidebar';
import { api } from './api/endpoints';
import type { AccountCapabilities, AuthResponse, AuthConfig, BillingStatus, Project } from './api/endpoints';
import { DEFAULT_ACCOUNT_CAPABILITIES } from './api/endpoints';
import { settings } from './settings';
import { useI18n } from './lib/i18n-context';
import {
    SECTION_LABELS,
    getIntentNameFromPath,
    getProjectIdFromPath,
    getSectionFromPath,
} from './app-navigation';

const MUST_CHANGE_PASSWORD_KEY = 'admin_must_change_password';
const ACTIVE_PROJECT_KEY = 'admin_active_project_id';
const ACCOUNT_CAPABILITIES_KEY = 'admin_account_capabilities';
const ACCOUNT_CAPABILITY_KEYS = Object.keys(DEFAULT_ACCOUNT_CAPABILITIES) as (keyof AccountCapabilities)[];

import { TopBarContext } from './TopBarContext';
import type { TopBarContextValue } from './TopBarContext';

const AdminLogin = lazy(() => import('./components/auth-screens').then(({ AdminLogin }) => ({ default: AdminLogin })));
const AdminSignup = lazy(() => import('./components/auth-screens').then(({ AdminSignup }) => ({ default: AdminSignup })));
const GmailConnectIntro = lazy(() => import('./components/auth-screens').then(({ GmailConnectIntro }) => ({ default: GmailConnectIntro })));
const GmailConnectStatus = lazy(() => import('./components/auth-screens').then(({ GmailConnectStatus }) => ({ default: GmailConnectStatus })));
const ChangePasswordGate = lazy(() => import('./components/auth-screens').then(({ ChangePasswordGate }) => ({ default: ChangePasswordGate })));
const Onboarding = lazy(() => import('./routes/Onboarding').then(({ Onboarding }) => ({ default: Onboarding })));
const VerifyEmail = lazy(() => import('./routes/VerifyEmail').then(({ VerifyEmail }) => ({ default: VerifyEmail })));
const Inbox = lazy(() => import('./routes/Inbox').then(({ Inbox }) => ({ default: Inbox })));
const Accounts = lazy(() => import('./routes/Accounts').then(({ Accounts }) => ({ default: Accounts })));
const Knowledge = lazy(() => import('./routes/Knowledge').then(({ Knowledge }) => ({ default: Knowledge })));
const Channels = lazy(() => import('./routes/Channels').then(({ Channels }) => ({ default: Channels })));
const Automations = lazy(() => import('./routes/Automations').then(({ Automations }) => ({ default: Automations })));
const Analytics = lazy(() => import('./routes/Analytics').then(({ Analytics }) => ({ default: Analytics })));
const Monitor = lazy(() => import('./routes/Monitor').then(({ Monitor }) => ({ default: Monitor })));
const Tools = lazy(() => import('./routes/Tools').then(({ Tools }) => ({ default: Tools })));
const Intents = lazy(() => import('./routes/Intents').then(({ Intents }) => ({ default: Intents })));
const Config = lazy(() => import('./routes/Config').then(({ Config }) => ({ default: Config })));
const Evaluation = lazy(() => import('./routes/Evaluation').then(({ Evaluation }) => ({ default: Evaluation })));
const ProjectMembers = lazy(() => import('./routes/ProjectMembers').then(({ ProjectMembers }) => ({ default: ProjectMembers })));
const PipelineOverview = lazy(() => import('./routes/PipelineOverview').then(({ PipelineOverview }) => ({ default: PipelineOverview })));
const Demo = lazy(() => import('./routes/Demo').then(({ Demo }) => ({ default: Demo })));
const Users = lazy(() => import('./routes/Users').then(({ Users }) => ({ default: Users })));
const Billing = lazy(() => import('./routes/Billing').then(({ Billing }) => ({ default: Billing })));
const OrgSettings = lazy(() => import('./routes/OrgSettings').then(({ OrgSettings }) => ({ default: OrgSettings })));
const DemoTopBarActions = lazy(() => import('./components/demo-top-bar-actions').then(({ DemoTopBarActions }) => ({ default: DemoTopBarActions })));
const AppSidebar = lazy(() => import('./components/app-sidebar').then(({ AppSidebar }) => ({ default: AppSidebar })));
const NewProjectDialog = lazy(() => import('./components/new-project-dialog').then(({ NewProjectDialog }) => ({ default: NewProjectDialog })));

const RouteLoading = () => {
    const { t } = useI18n();

    return (
        <div className="flex min-h-64 w-full items-center justify-center text-sm text-muted-foreground">
            <Loader className="mr-2 size-4 animate-spin" />
            {t('Loading')}
        </div>
    );
};

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Decode a JWT payload without verification (the backend already verified it). */
function decodeJwtPayload(token: string): {
    email?: string;
    is_root?: boolean;
    is_platform_admin?: boolean;
    tenant_id?: string;
    tenant_name?: string;
    tenant_account_type?: 'normal' | 'demo';
} | null {
    try {
        const parts = token.split('.');
        if (parts.length !== 3) return null;
        const payload: unknown = JSON.parse(atob(parts[1]));
        if (!isRecord(payload)) return null;
        return {
            email: typeof payload.email === 'string' ? payload.email : undefined,
            is_root: typeof payload.is_root === 'boolean' ? payload.is_root : undefined,
            is_platform_admin: typeof payload.is_platform_admin === 'boolean' ? payload.is_platform_admin : undefined,
            tenant_id: typeof payload.tenant_id === 'string' ? payload.tenant_id : undefined,
            tenant_name: typeof payload.tenant_name === 'string' ? payload.tenant_name : undefined,
            tenant_account_type: payload.tenant_account_type === 'demo' ? 'demo' : 'normal',
        };
    } catch {
        return null;
    }
}

/** Read user info from the stored JWT token. */
function readStoredCapabilities(): AccountCapabilities {
    try {
        const raw = localStorage.getItem(ACCOUNT_CAPABILITIES_KEY);
        if (!raw) return DEFAULT_ACCOUNT_CAPABILITIES;
        const parsed: unknown = JSON.parse(raw);
        if (!isRecord(parsed)) return DEFAULT_ACCOUNT_CAPABILITIES;
        const capabilities: AccountCapabilities = { ...DEFAULT_ACCOUNT_CAPABILITIES };
        for (const key of ACCOUNT_CAPABILITY_KEYS) {
            if (typeof parsed[key] === 'boolean') {
                capabilities[key] = parsed[key];
            }
        }
        return capabilities;
    } catch {
        return DEFAULT_ACCOUNT_CAPABILITIES;
    }
}

/** Read user info from the stored JWT token. */
function restoreUserFromToken(): {
    email: string;
    isRoot: boolean;
    isPlatformAdmin: boolean;
    tenantId: string;
    tenantName: string;
    tenantAccountType: 'normal' | 'demo';
} {
    const token = localStorage.getItem('admin_auth_token');
    if (!token) {
        return {
            email: '',
            isRoot: false,
            isPlatformAdmin: false,
            tenantId: '',
            tenantName: '',
            tenantAccountType: 'normal',
        };
    }
    const payload = decodeJwtPayload(token);
    return {
        email: payload?.email ?? '',
        isRoot: payload?.is_root ?? false,
        isPlatformAdmin: payload?.is_platform_admin ?? false,
        tenantId: payload?.tenant_id ?? '',
        tenantName: payload?.tenant_name ?? '',
        tenantAccountType: payload?.tenant_account_type ?? 'normal',
    };
}

const ProjectHome = ({
    tenantId,
    projectId,
}: {
    tenantId: string;
    projectId: string;
}) => {
    return <Navigate to={`/${tenantId}/${projectId}/inbox`} replace />;
};

const LegacyIntentsRedirect = () => {
    const location = useLocation();
    const pathname = location.pathname.replace('/intents', '/runbooks');
    return <Navigate to={`${pathname}${location.search}${location.hash}`} replace />;
};

const LegacyProjectRouteRedirect = ({ from, to }: { from: string; to: string }) => {
    const location = useLocation();
    const pathname = location.pathname.replace(from, to);
    return <Navigate to={`${pathname}${location.search}${location.hash}`} replace />;
};

// ── Main app ─────────────────────────────────────────────────────────────────

const AdminApp = () => {
    const location = useLocation();
    const navigate = useNavigate();
    const { t, setLocale } = useI18n();
    const restoredUser = restoreUserFromToken();
    const [userEmail, setUserEmail] = useState(restoredUser.email);
    const [isRoot, setIsRoot] = useState(restoredUser.isRoot);
    const [isPlatformAdmin, setIsPlatformAdmin] = useState(restoredUser.isPlatformAdmin);
    const [tenantId, setTenantId] = useState(restoredUser.tenantId);
    const [tenantName, setTenantName] = useState(restoredUser.tenantName);
    const [tenantAccountType, setTenantAccountType] = useState<'normal' | 'demo'>(restoredUser.tenantAccountType);
    const [accountCapabilities, setAccountCapabilities] = useState<AccountCapabilities>(() => readStoredCapabilities());
    const [sidebarIntents, setSidebarIntents] = useState<SidebarIntent[]>([]);
    const [isAuthenticated, setIsAuthenticated] = useState<boolean>(
        !settings.requireAuth || !!localStorage.getItem('admin_auth_token')
    );
    const [mustChangePassword, setMustChangePassword] = useState<boolean>(
        settings.requireAuth && localStorage.getItem(MUST_CHANGE_PASSWORD_KEY) === '1'
    );
    const [showWizard, setShowWizard] = useState(false);
    const [authView, setAuthView] = useState<'login' | 'signup'>(() => {
        const params = new URLSearchParams(window.location.search);
        return params.get('view') === 'signup' ? 'signup' : 'login';
    });
    const [authConfig, setAuthConfig] = useState<AuthConfig | null>(null);
    const isGmailConnectRoute = location.pathname === '/gmail/connect';
    const gmailConnectEmail = useMemo(() => {
        const params = new URLSearchParams(location.search);
        return (params.get('email') ?? '').trim().toLowerCase();
    }, [location.search]);

    // ── Top bar slot state (child routes can inject breadcrumb + actions) ────
    const [topBarBreadcrumb, setTopBarBreadcrumb] = useState<React.ReactNode | null>(null);
    const [topBarActions, setTopBarActions] = useState<React.ReactNode | null>(null);
    const topBarCtx = useMemo<TopBarContextValue>(() => ({
        setBreadcrumb: setTopBarBreadcrumb,
        setActions: setTopBarActions,
    }), []);

    // ── Project state ───────────────────────────────────────────────────────
    const [projects, setProjects] = useState<Project[]>([]);
    const [newProjectDialogOpen, setNewProjectDialogOpen] = useState(false);
    const [newProjectName, setNewProjectName] = useState('');
    const [creatingProject, setCreatingProject] = useState(false);

    // ── Billing state (SaaS only) ───────────────────────────────────────────
    const [billing, setBilling] = useState<BillingStatus | null>(null);

    // ── Tenant email settings (for sidebar Support/Feedback links) ─────────
    const [supportEmail, setSupportEmail] = useState('');
    const [feedbackEmail, setFeedbackEmail] = useState('');

    const loadTenantSettings = useCallback(() => {
        void api.getTenantSettings().then(res => {
            if (res.data) {
                setSupportEmail(res.data.supportEmail);
                setFeedbackEmail(res.data.feedbackEmail);
            }
        });
    }, []);

    // ── Derive activeProjectId from URL + localStorage fallback ─────────────
    const urlProjectId = getProjectIdFromPath(location.pathname);
    const storedProjectId = localStorage.getItem(ACTIVE_PROJECT_KEY);

    const activeProjectId = useMemo(() => {
        const preferred = urlProjectId ?? storedProjectId;
        if (projects.length === 0) return preferred;
        if (preferred && projects.some(p => p.id === preferred)) return preferred;
        return projects[0]?.id ?? null;
    }, [urlProjectId, storedProjectId, projects]);

    const activeProject = projects.find(p => p.id === activeProjectId) ?? null;

    /** Effective role: root users get 'root'; others read from project membership. */
    const isEffectiveRoot = isRoot || isPlatformAdmin;
    const isDemoAccount = tenantAccountType === 'demo';
    const effectiveAccountCapabilities = useMemo<AccountCapabilities>(() => {
        if (!isDemoAccount) return accountCapabilities;
        return { ...accountCapabilities, canPublish: true };
    }, [accountCapabilities, isDemoAccount]);
    const canDownloadManifest = effectiveAccountCapabilities.canDownloadManifest;
    const userRole: UserRole = isEffectiveRoot
        ? 'root'
        : (activeProject?.role as UserRole | undefined) ?? 'viewer';

    const applyAuthenticatedSession = useCallback((session: AuthResponse) => {
        const capabilities = { ...DEFAULT_ACCOUNT_CAPABILITIES, ...(session.capabilities ?? {}) };
        setLocale(session.language ?? 'en');
        setUserEmail(session.email);
        setIsRoot(session.isRoot);
        setIsPlatformAdmin(session.isPlatformAdmin);
        setTenantId(session.tenantId);
        setTenantName(session.tenantName);
        setTenantAccountType(session.tenantAccountType ?? 'normal');
        setAccountCapabilities(capabilities);
        localStorage.setItem(ACCOUNT_CAPABILITIES_KEY, JSON.stringify(capabilities));
        setIsAuthenticated(true);
    }, [setLocale]);

    // ── Persist active project to localStorage ──────────────────────────────
    useEffect(() => {
        if (activeProjectId) {
            localStorage.setItem(ACTIVE_PROJECT_KEY, activeProjectId);
        }
    }, [activeProjectId]);

    // ── Derive section & intent name from URL ───────────────────────────────
    const rawSection = useMemo(() => getSectionFromPath(location.pathname), [location.pathname]);
    const currentSection = rawSection === 'demo' && !settings.enablePreview ? null : rawSection;

    const selectedIntentName = useMemo(
        () => getIntentNameFromPath(location.pathname),
        [location.pathname],
    );

    // ── Load projects ───────────────────────────────────────────────────────
    const loadProjects = useCallback(() => {
        void api.listProjects().then(res => {
            if (res.data) {
                setProjects(res.data);
            }
        });
    }, []);

    const handleCreateProject = useCallback(() => {
        // In SaaS Free plan, block and redirect to billing
        if (settings.isSaas && (!billing || billing.plan === 'free')) {
            toast.error(t('The Cloud Sandbox is limited to 1 project. Upgrade to Cloud to create more.'));
            void navigate(`/${tenantId}/billing`);
            return;
        }
        setNewProjectName('');
        setNewProjectDialogOpen(true);
    }, [billing, navigate, tenantId, t]);

    const handleCreateProjectConfirm = useCallback(async () => {
        const name = newProjectName.trim();
        if (!name) return;
        setCreatingProject(true);
        const res = await api.createProject(name, '');
        setCreatingProject(false);
        if (res.error) {
            toast.error(res.error);
            return;
        }
        toast.success(t('Project created'));
        setNewProjectDialogOpen(false);
        loadProjects();
        if (res.data) {
            localStorage.setItem(ACTIVE_PROJECT_KEY, res.data.id);
            void navigate(`/${tenantId}/${res.data.id}`);
        }
    }, [newProjectName, loadProjects, navigate, tenantId, t]);

    // Load intent list for sidebar (needs active project)
    const loadSidebarIntents = useCallback(() => {
        if (!activeProjectId) return;
        void api.getIntents(activeProjectId).then(res => {
            if (res.data) {
                setSidebarIntents(res.data.map(i => ({
                    name: i.name,
                    active: i.active,
                })));
            }
        });
    }, [activeProjectId]);

    // Listen for 401/403 events from the API client interceptor
    useEffect(() => {
        const handleUnauthorized = () => {
            localStorage.removeItem(MUST_CHANGE_PASSWORD_KEY);
            localStorage.removeItem(ACCOUNT_CAPABILITIES_KEY);
            setMustChangePassword(false);
            setIsAuthenticated(false);
        };
        window.addEventListener('admin:unauthorized', handleUnauthorized);
        return () => window.removeEventListener('admin:unauthorized', handleUnauthorized);
    }, []);

    // Fetch auth config (public, pre-auth) so login page knows if signup is available
    useEffect(() => {
        if (isAuthenticated) return;
        let cancelled = false;
        void api.getAuthConfig().then(res => {
            if (!cancelled && res.data) setAuthConfig(res.data);
        });
        return () => { cancelled = true; };
    }, [isAuthenticated]);

    // After authentication, load projects + tenant settings (runs once)
    useEffect(() => {
        if (!isAuthenticated) return;
        loadProjects();
        loadTenantSettings();
        void api.getCurrentUser().then(res => {
            if (res.data?.language) {
                setLocale(res.data.language);
            }
        });
        if (settings.isSaas) {
            void api.getBillingStatus().then(res => {
                if (res.data) setBilling(res.data);
            });
        }
    }, [isAuthenticated, loadProjects, loadTenantSettings, setLocale]);

    // Load sidebar intents whenever the active project changes
    useEffect(() => {
        if (!isAuthenticated) return;
        loadSidebarIntents();
    }, [isAuthenticated, loadSidebarIntents]);

    // Onboarding wizard: check for empty intents after project is available
    useEffect(() => {
        if (!isAuthenticated || !activeProjectId || isDemoAccount) return;
        if (localStorage.getItem('admin_onboarding_done')) return;

        let cancelled = false;
        api.getIntents(activeProjectId).then(res => {
            if (cancelled) return;
            if (res.data && res.data.length === 0) {
                setShowWizard(true);
            }
        }).catch(() => {
            // Ignore — wizard check is best-effort
        });
        return () => { cancelled = true; };
    }, [isAuthenticated, activeProjectId, isDemoAccount]);

    // Refresh sidebar intents when drafts change or project changes
    useEffect(() => {
        const handler = () => loadSidebarIntents();
        window.addEventListener('admin:intents-changed', handler);
        window.addEventListener('admin:draft-changed', handler);
        return () => {
            window.removeEventListener('admin:intents-changed', handler);
            window.removeEventListener('admin:draft-changed', handler);
        };
    }, [loadSidebarIntents]);

    // ── Redirect to valid project after projects load ───────────────────────
    useEffect(() => {
        if (projects.length === 0 || !tenantId || !isAuthenticated) return;

        const p = location.pathname;

        // Don't redirect on tenant-scoped routes
        if (p === '/gmail/connect') return;
        if (matchPath('/:t/users', p) || matchPath('/:t/billing', p) || matchPath('/:t/org', p)) return;

        // Check for root or invalid project
        const urlProjId = getProjectIdFromPath(p);
        const validProject = urlProjId && projects.some(proj => proj.id === urlProjId);

        if (!validProject) {
            const fallback = activeProjectId ?? projects[0]?.id;
            if (fallback) {
                void navigate(`/${tenantId}/${fallback}`, { replace: true });
            }
        }
    }, [projects, tenantId, isAuthenticated, location.pathname, navigate, activeProjectId]);

    const dismissWizard = () => {
        localStorage.setItem('admin_onboarding_done', '1');
        setShowWizard(false);
    };

    const handleSignOut = () => {
        localStorage.removeItem('admin_auth_token');
        localStorage.removeItem(MUST_CHANGE_PASSWORD_KEY);
        localStorage.removeItem(ACCOUNT_CAPABILITIES_KEY);
        setMustChangePassword(false);
        setIsAuthenticated(false);
        setIsPlatformAdmin(false);
        setTenantAccountType('normal');
        setAccountCapabilities(DEFAULT_ACCOUNT_CAPABILITIES);
        setProjects([]);
        void navigate('/');
    };

    // Public route: email verification — no auth required (checked after all hooks)
    // PocketBase handles the verification; after success, user logs in normally.
    if (location.pathname.endsWith('/verify-email')) {
        return (
            <Suspense fallback={<RouteLoading />}>
                <VerifyEmail />
            </Suspense>
        );
    }

    if (!isAuthenticated) {
        const allowSignups = authConfig?.allowSignups ?? settings.isSaas;
        const isSaas = authConfig?.isSaas ?? settings.isSaas;
        const gmailIntro = isGmailConnectRoute ? <GmailConnectIntro gmailEmail={gmailConnectEmail} /> : undefined;

        if (authView === 'signup' && allowSignups) {
            return (
                <Suspense fallback={<RouteLoading />}>
                    <AdminSignup
                        onAuthenticated={(session) => {
                            applyAuthenticatedSession(session);
                            setMustChangePassword(false);
                        }}
                        onSwitchToLogin={() => setAuthView('login')}
                        isSaas={isSaas}
                        initialEmail={isGmailConnectRoute ? gmailConnectEmail : ''}
                        intro={gmailIntro}
                    />
                </Suspense>
            );
        }
        return (
            <Suspense fallback={<RouteLoading />}>
                <AdminLogin
                    onAuthenticated={(session) => {
                        applyAuthenticatedSession(session);
                        setMustChangePassword(session.mustChangePassword);
                    }}
                    onSwitchToSignup={() => setAuthView('signup')}
                    allowSignups={allowSignups}
                    initialEmail={isGmailConnectRoute ? gmailConnectEmail : ''}
                    intro={gmailIntro}
                />
            </Suspense>
        );
    }

    if (mustChangePassword) {
        return (
            <Suspense fallback={<RouteLoading />}>
                <ChangePasswordGate
                    onComplete={() => setMustChangePassword(false)}
                    onSignOut={handleSignOut}
                    userEmail={userEmail}
                />
            </Suspense>
        );
    }

    if (isGmailConnectRoute) {
        return (
            <Suspense fallback={<RouteLoading />}>
                <GmailConnectStatus
                    gmailEmail={gmailConnectEmail}
                    tenantName={tenantName}
                    userEmail={userEmail}
                    onOpenWorkspace={() => {
                        if (tenantId && activeProjectId) {
                            void navigate(`/${tenantId}/${activeProjectId}`);
                        } else {
                            void navigate('/');
                        }
                    }}
                    onSignOut={handleSignOut}
                />
            </Suspense>
        );
    }

    if (showWizard && activeProjectId) {
        return (
            <Suspense fallback={<RouteLoading />}>
                <Onboarding projectId={activeProjectId} onComplete={dismissWizard} onDismiss={dismissWizard} />
            </Suspense>
        );
    }

    return (
        <TooltipProvider>
            <SidebarProvider className="h-screen min-h-0 overflow-hidden">
                <Suspense fallback={null}>
                    <AppSidebar
                        tenantId={tenantId}
                        activeProjectId={activeProjectId}
                        activeSection={currentSection}
                        selectedIntentName={selectedIntentName}
                        intents={sidebarIntents}
                        enablePreview={settings.enablePreview}
                        requireAuth={settings.requireAuth}
                        isSaas={settings.isSaas}
                        onSignOut={handleSignOut}
                        userEmail={userEmail}
                        tenantName={tenantName}
                        activeProject={activeProject}
                        projects={projects}
                        onCreateProject={isEffectiveRoot && effectiveAccountCapabilities.canManageProjectSettings ? handleCreateProject : undefined}
                        isFreePlan={settings.isSaas && (!billing || billing.plan === 'free')}
                        userRole={userRole}
                        capabilities={effectiveAccountCapabilities}
                        tenantAccountType={tenantAccountType}
                        supportEmail={supportEmail}
                        feedbackEmail={feedbackEmail}
                    />
                </Suspense>
                <SidebarInset className="h-screen min-h-0 overflow-hidden">
                    {/* ── Top bar: trigger + breadcrumb + actions ── */}
                    <header className="sticky top-0 z-10 flex h-16 shrink-0 items-center gap-2 border-b bg-background px-4">
                        <SidebarTrigger className="-ml-1" />
                        <Separator
                            orientation="vertical"
                            className="mr-2 h-4"
                        />
                        {topBarBreadcrumb ?? (
                            <Breadcrumb>
                                <BreadcrumbList>
                                    <BreadcrumbItem>
                                        <BreadcrumbPage>
                                            {currentSection ? t(SECTION_LABELS[currentSection]) : t('Overview')}
                                        </BreadcrumbPage>
                                    </BreadcrumbItem>
                                </BreadcrumbList>
                            </Breadcrumb>
                        )}
                        <div className="ml-auto flex items-center gap-2">
                            {topBarActions}
                            {currentSection === 'demo' && (
                                <Suspense fallback={null}>
                                    <DemoTopBarActions
                                        projectId={activeProjectId}
                                        canDownloadManifest={canDownloadManifest}
                                        canPublish={effectiveAccountCapabilities.canPublish}
                                    />
                                </Suspense>
                            )}
                        </div>
                    </header>

                    {/* ── Main content ── */}
                    <TopBarContext.Provider value={topBarCtx}>
                    <main className={
                        !currentSection
                            ? 'flex-1 min-h-0 flex flex-col items-center justify-center overflow-hidden px-6 py-6'
                            : currentSection === 'demo'
                                ? 'flex-1 min-h-0 flex overflow-hidden'
                                : currentSection === 'inbox'
                                    ? 'flex-1 min-h-0 flex overflow-hidden px-6 py-6'
                                    : currentSection === 'accounts' || currentSection === 'knowledge' || currentSection === 'channels' || currentSection === 'automations'
                                        ? 'flex-1 min-h-0 flex overflow-hidden px-6 py-6'
                                        : currentSection === 'analytics'
                                            ? 'flex-1 min-h-0 flex flex-col overflow-y-auto px-6 py-6'
                                : currentSection === 'intents'
                                    ? 'flex-1 min-h-0 flex flex-col overflow-hidden px-6 py-6'
                                    : currentSection === 'monitor'
                                        ? 'flex-1 min-h-0 flex flex-col overflow-hidden px-6 py-6'
                                        : 'flex-1 overflow-y-auto px-6 py-8'
                    }>
                        <Suspense fallback={<RouteLoading />}>
                        <Routes>
                            {/* Pipeline overview */}
                            <Route path="/:tenantId/:projectId" element={
                                activeProjectId && tenantId
                                    ? (
                                        <ProjectHome
                                            tenantId={tenantId}
                                            projectId={activeProjectId}
                                        />
                                    )
                                    : null
                            } />
                            <Route path="/:tenantId/:projectId/monitor" element={
                                activeProjectId ? <Monitor projectId={activeProjectId} isDemoAccount={isDemoAccount} /> : null
                            } />
                            <Route path="/:tenantId/:projectId/inbox" element={
                                activeProjectId ? <Inbox projectId={activeProjectId} /> : null
                            } />
                            <Route path="/:tenantId/:projectId/inbox/:issueId" element={
                                activeProjectId ? <Inbox projectId={activeProjectId} /> : null
                            } />
                            <Route path="/:tenantId/:projectId/accounts" element={
                                activeProjectId ? <Accounts projectId={activeProjectId} /> : null
                            } />
                            <Route path="/:tenantId/:projectId/accounts/:accountId" element={
                                activeProjectId ? <Accounts projectId={activeProjectId} /> : null
                            } />
                            <Route path="/:tenantId/:projectId/knowledge" element={
                                activeProjectId ? <Knowledge projectId={activeProjectId} userRole={userRole} /> : null
                            } />
                            <Route path="/:tenantId/:projectId/knowledge/:articleId" element={
                                activeProjectId ? <Knowledge projectId={activeProjectId} userRole={userRole} /> : null
                            } />
                            <Route path="/:tenantId/:projectId/channels" element={
                                activeProjectId ? <Channels projectId={activeProjectId} /> : null
                            } />
                            <Route path="/:tenantId/:projectId/automations" element={
                                activeProjectId ? <Automations projectId={activeProjectId} /> : null
                            } />
                            <Route path="/:tenantId/:projectId/analytics" element={
                                activeProjectId ? <Analytics projectId={activeProjectId} /> : null
                            } />
                            <Route path="/:tenantId/:projectId/support-setup" element={
                                activeProjectId && tenantId
                                    ? (
                                        <PipelineOverview
                                            tenantId={tenantId}
                                            projectId={activeProjectId}
                                            canDownloadManifest={canDownloadManifest}
                                        />
                                    )
                                    : null
                            } />
                            <Route
                                path="/:tenantId/:projectId/pipeline"
                                element={<LegacyProjectRouteRedirect from="/pipeline" to="/support-setup" />}
                            />

                            {/* Project-scoped routes */}
                            <Route path="/:tenantId/:projectId/customer-identity" element={
                                activeProjectId ? <Tools projectId={activeProjectId} /> : null
                            } />
                            <Route
                                path="/:tenantId/:projectId/customer"
                                element={<LegacyProjectRouteRedirect from="/customer" to="/customer-identity" />}
                            />
                            <Route path="/:tenantId/:projectId/runbooks/*" element={
                                activeProjectId ? <Intents projectId={activeProjectId} userRole={userRole} /> : null
                            } />
                            <Route path="/:tenantId/:projectId/intents/*" element={<LegacyIntentsRedirect />} />
                            <Route path="/:tenantId/:projectId/settings" element={
                                activeProjectId ? (
                                    <div className="w-full max-w-lg mx-auto">
                                        <Config
                                            projectId={activeProjectId}
                                            canDownloadManifest={canDownloadManifest}
                                            canManageProjectSecrets={effectiveAccountCapabilities.canManageProjectSecrets}
                                            canEditProjectConfig={effectiveAccountCapabilities.canEditProjectConfig}
                                            isDemoAccount={isDemoAccount}
                                        />
                                    </div>
                                ) : null
                            } />
                            <Route path="/:tenantId/:projectId/eval" element={
                                activeProjectId ? <Evaluation projectId={activeProjectId} /> : null
                            } />
                            <Route path="/:tenantId/:projectId/eval/:setId" element={
                                activeProjectId ? <Evaluation projectId={activeProjectId} /> : null
                            } />
                            <Route path="/:tenantId/:projectId/eval/:setId/runs/:runId" element={
                                activeProjectId ? <Evaluation projectId={activeProjectId} /> : null
                            } />
                            <Route path="/:tenantId/:projectId/members" element={
                                activeProjectId && (effectiveAccountCapabilities.canManageMembers || isDemoAccount)
                                    ? <ProjectMembers projectId={activeProjectId} userEmail={userEmail} isDemoAccount={isDemoAccount} />
                                    : null
                            } />
                            {settings.enablePreview && (
                                <Route path="/:tenantId/:projectId/preview" element={
                                    activeProjectId ? <Demo projectId={activeProjectId} isDemoAccount={isDemoAccount} /> : null
                                } />
                            )}

                            {/* Tenant-scoped routes */}
                            {isEffectiveRoot && (effectiveAccountCapabilities.canManageMembers || isDemoAccount) && (
                                <Route path="/:tenantId/users" element={
                                    <Users isDemoAccount={isDemoAccount} userEmail={userEmail} projects={projects} />
                                } />
                            )}
                            {settings.isSaas && isEffectiveRoot && (effectiveAccountCapabilities.canManageBilling || isDemoAccount) && (
                                <Route path="/:tenantId/billing" element={<Billing isDemoAccount={isDemoAccount} />} />
                            )}
                            {isEffectiveRoot && (effectiveAccountCapabilities.canManageOrgSettings || isDemoAccount) && (
                                <Route path="/:tenantId/org" element={
                                    <OrgSettings onSettingsChanged={loadTenantSettings} isDemoAccount={isDemoAccount} />
                                } />
                            )}

                            {/* Catch-all: redirect to default project overview */}
                            <Route path="*" element={
                                tenantId && activeProjectId
                                    ? <Navigate to={`/${tenantId}/${activeProjectId}`} replace />
                                    : null
                            } />
                        </Routes>
                        </Suspense>
                    </main>
                    </TopBarContext.Provider>
                </SidebarInset>
            </SidebarProvider>

            {newProjectDialogOpen && (
                <Suspense fallback={null}>
                    <NewProjectDialog
                        open={newProjectDialogOpen}
                        onOpenChange={setNewProjectDialogOpen}
                        name={newProjectName}
                        onNameChange={setNewProjectName}
                        creating={creatingProject}
                        onConfirm={() => void handleCreateProjectConfirm()}
                    />
                </Suspense>
            )}
        </TooltipProvider>
    );
};

export default AdminApp;
