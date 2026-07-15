import {
    Building2,
    Activity,
    ChevronRight,
    CreditCard,
    Eye,
    FlaskConical,
    FolderKanban,
    Inbox,
    BookOpen,
    ChartNoAxesColumn,
    Cable,
    LifeBuoy,
    LogOut,
    Search,
    Send,
    Settings2,
    Tag,
    Users as UsersIcon,
    UsersRound,
    Workflow,
    ChevronsUpDown,
    Check,
    Lock,
    Plus,
    type LucideIcon,
} from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';

import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
    Sidebar,
    SidebarContent,
    SidebarFooter,
    SidebarGroup,
    SidebarGroupContent,
    SidebarGroupLabel,
    SidebarHeader,
    SidebarMenu,
    SidebarMenuAction,
    SidebarMenuButton,
    SidebarMenuItem,
    SidebarMenuSub,
    SidebarMenuSubButton,
    SidebarMenuSubItem,
    useSidebar,
} from '@/components/ui/sidebar';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { brand } from '@/brand';
import { useI18n } from '@/lib/i18n-context';

import type { AccountCapabilities, Project } from '@/api/endpoints';

// ── Types ────────────────────────────────────────────────────────────────────

export type Section = 'inbox' | 'accounts' | 'knowledge' | 'channels' | 'automations' | 'analytics' | 'monitor' | 'pipeline' | 'tools' | 'intents' | 'settings' | 'users' | 'demo' | 'eval' | 'members' | 'billing' | 'org';

/** Effective role for the current user in the active project. */
export type UserRole = 'root' | 'admin' | 'editor' | 'viewer';

export interface SidebarIntent {
    name: string;
    active: boolean;
}

interface AppSidebarProps extends React.ComponentProps<typeof Sidebar> {
    /** Tenant ID for constructing navigation URLs. */
    tenantId: string;
    /** Active project ID for constructing navigation URLs. */
    activeProjectId: string | null;
    /** Active section derived from URL (for active-state styling). */
    activeSection: Section | null;
    /** Currently selected intent name derived from URL (for sub-item highlight). */
    selectedIntentName?: string | null;
    intents: SidebarIntent[];
    enablePreview: boolean;
    requireAuth: boolean;
    isSaas: boolean;
    onSignOut: () => void;
    userEmail: string;
    /** Tenant / organisation display name. */
    tenantName: string;
    /** Active project (shown in footer switcher). */
    activeProject: Project | null;
    /** All projects accessible by the current user. */
    projects: Project[];
    /** Callback when "New Project" is clicked (root only). */
    onCreateProject?: () => void;
    /** Whether the tenant is on the free plan (SaaS). */
    isFreePlan?: boolean;
    /** Current user's effective role. */
    userRole: UserRole;
    capabilities: AccountCapabilities;
    tenantAccountType: 'normal' | 'demo';
    /** Support email for the sidebar link (from tenant settings). */
    supportEmail?: string;
    /** Feedback email for the sidebar link (from tenant settings). */
    feedbackEmail?: string;
}

// ── Secondary nav items ──────────────────────────────────────────────────────

/** Default fallback for SaaS deployments. */
const DEFAULT_SAAS_EMAIL = brand.supportEmail;

// ── Role helpers ─────────────────────────────────────────────────────────────

function hasMinRole(current: UserRole, required: UserRole): boolean {
    const hierarchy: UserRole[] = ['root', 'admin', 'editor', 'viewer'];
    return hierarchy.indexOf(current) <= hierarchy.indexOf(required);
}

// ── Component ────────────────────────────────────────────────────────────────

export function AppSidebar({
    tenantId,
    activeProjectId,
    activeSection,
    selectedIntentName,
    intents,
    enablePreview,
    requireAuth,
    isSaas,
    onSignOut,
    userEmail,
    tenantName,
    activeProject,
    projects,
    onCreateProject,
    isFreePlan,
    userRole,
    capabilities,
    tenantAccountType,
    supportEmail,
    feedbackEmail,
    ...props
}: AppSidebarProps) {
    const { isMobile } = useSidebar();
    const navigate = useNavigate();
    const { t } = useI18n();

    const initials = userEmail
        ? userEmail.slice(0, 2).toUpperCase()
        : 'AD';

    const isRoot = userRole === 'root';
    const isDemoAccount = tenantAccountType === 'demo';
    const canManageMembers = hasMinRole(userRole, 'admin') && capabilities.canManageMembers;

    /** Build a project-scoped path, or '#' when no project is active. */
    const projectPath = (sub?: string) =>
        activeProjectId
            ? `/${tenantId}/${activeProjectId}${sub ? `/${sub}` : ''}`
            : '#';

    return (
        <Sidebar collapsible="icon" {...props}>
            {/* ── Header: product branding ── */}
            <SidebarHeader>
                <SidebarMenu>
                    <SidebarMenuItem>
                        <SidebarMenuButton
                            asChild
                            size="lg"
                            tooltip={brand.shortName}
                        >
                            <Link to={projectPath()}>
                                <span className="flex min-w-0 items-center gap-2">
                                    <span className="truncate font-display text-xl font-normal not-italic">{brand.shortName}</span>
                                </span>
                            </Link>
                        </SidebarMenuButton>
                    </SidebarMenuItem>
                </SidebarMenu>
            </SidebarHeader>

            <SidebarContent>
                {/* ── Top items: Monitor, Preview & Evaluation ── */}
                <SidebarGroup>
                    <SidebarGroupContent>
                        <SidebarMenu>
                            <SidebarMenuItem>
                                <SidebarMenuButton
                                    asChild
                                    isActive={activeSection === 'inbox'}
                                    tooltip={t('Inbox')}
                                >
                                    <Link to={projectPath('inbox')}>
                                        <Inbox />
                                        <span>{t('Inbox')}</span>
                                    </Link>
                                </SidebarMenuButton>
                            </SidebarMenuItem>
                            <SidebarMenuItem>
                                <SidebarMenuButton
                                    asChild
                                    isActive={activeSection === 'accounts'}
                                    tooltip={t('Accounts')}
                                >
                                    <Link to={projectPath('accounts')}>
                                        <Building2 />
                                        <span>{t('Accounts')}</span>
                                    </Link>
                                </SidebarMenuButton>
                            </SidebarMenuItem>
                            <SidebarMenuItem>
                                <SidebarMenuButton
                                    asChild
                                    isActive={activeSection === 'knowledge'}
                                    tooltip={t('Knowledge')}
                                >
                                    <Link to={projectPath('knowledge')}>
                                        <BookOpen />
                                        <span>{t('Knowledge')}</span>
                                    </Link>
                                </SidebarMenuButton>
                            </SidebarMenuItem>
                            <SidebarMenuItem>
                                <SidebarMenuButton
                                    asChild
                                    isActive={activeSection === 'analytics'}
                                    tooltip={t('Analytics')}
                                >
                                    <Link to={projectPath('analytics')}>
                                        <ChartNoAxesColumn />
                                        <span>{t('Analytics')}</span>
                                    </Link>
                                </SidebarMenuButton>
                            </SidebarMenuItem>
                            <SidebarMenuItem>
                                <SidebarMenuButton
                                    asChild
                                    isActive={activeSection === 'automations'}
                                    tooltip={t('Workflow rules')}
                                >
                                    <Link to={projectPath('automations')}>
                                        <Workflow />
                                        <span>{t('Workflow rules')}</span>
                                    </Link>
                                </SidebarMenuButton>
                            </SidebarMenuItem>
                            <SidebarMenuItem>
                                <SidebarMenuButton
                                    asChild
                                    isActive={activeSection === 'channels'}
                                    tooltip={t('Channel setup')}
                                >
                                    <Link to={projectPath('channels')}>
                                        <Cable />
                                        <span>{t('Channel setup')}</span>
                                    </Link>
                                </SidebarMenuButton>
                            </SidebarMenuItem>
                            <SidebarMenuItem>
                                <SidebarMenuButton
                                    asChild
                                    isActive={activeSection === 'monitor'}
                                    tooltip={t('Monitor')}
                                >
                                    <Link to={projectPath('monitor')}>
                                        <Activity />
                                        <span>{t('Monitor')}</span>
                                    </Link>
                                </SidebarMenuButton>
                            </SidebarMenuItem>
                            {enablePreview && (
                                <SidebarMenuItem>
                                    <SidebarMenuButton
                                        asChild
                                        isActive={activeSection === 'demo'}
                                        tooltip={t('Preview & Publish')}
                                    >
                                        <Link to={projectPath('preview')}>
                                            <Eye />
                                            <span>{t('Preview & Publish')}</span>
                                        </Link>
                                    </SidebarMenuButton>
                                </SidebarMenuItem>
                            )}
                            <SidebarMenuItem>
                                <SidebarMenuButton
                                    asChild
                                    isActive={activeSection === 'eval'}
                                    tooltip={t('Evaluation')}
                                >
                                    <Link to={projectPath('eval')}>
                                        <FlaskConical />
                                        <span>{t('Evaluation')}</span>
                                    </Link>
                                </SidebarMenuButton>
                            </SidebarMenuItem>
                        </SidebarMenu>
                    </SidebarGroupContent>
                </SidebarGroup>

                {/* ── Group: AI setup ── */}
                <SidebarGroup className="flex-1 min-h-0">
                    <SidebarGroupLabel>{t('AI setup')}</SidebarGroupLabel>
                    <SidebarGroupContent>
                        <SidebarMenu>
                            {/* Identity rules */}
                            <SidebarMenuItem>
                                <SidebarMenuButton
                                    asChild
                                    isActive={activeSection === 'tools'}
                                    tooltip={t('Identity rules')}
                                >
                                    <Link to={projectPath('customer-identity')}>
                                        <Search />
                                        <span>{t('Identity rules')}</span>
                                    </Link>
                                </SidebarMenuButton>
                            </SidebarMenuItem>

                            {/* AI runbooks - collapsible with sub-items */}
                            <Collapsible defaultOpen>
                                <SidebarMenuItem>
                                    <SidebarMenuButton
                                        asChild
                                        isActive={activeSection === 'intents'}
                                        tooltip={t('AI runbooks')}
                                    >
                                        <Link to={projectPath('runbooks')}>
                                            <Tag />
                                            <span>{t('AI runbooks')}</span>
                                        </Link>
                                    </SidebarMenuButton>
                                    <CollapsibleTrigger asChild>
                                        <SidebarMenuAction
                                            className="left-2 bg-sidebar-accent text-sidebar-accent-foreground data-[state=open]:rotate-90"
                                            showOnHover
                                        >
                                            <ChevronRight />
                                        </SidebarMenuAction>
                                    </CollapsibleTrigger>
                                    <CollapsibleContent>
                                        <SidebarMenuSub>
                                            {intents.filter(i => i.name !== '_else').map(intent => (
                                                <SidebarMenuSubItem key={intent.name}>
                                                    <SidebarMenuSubButton
                                                        asChild
                                                        className="cursor-pointer"
                                                        isActive={selectedIntentName === intent.name}
                                                    >
                                                        <Link to={projectPath(`runbooks/${intent.name}`)}>
                                                            <span>{intent.name}</span>
                                                        </Link>
                                                    </SidebarMenuSubButton>
                                                </SidebarMenuSubItem>
                                            ))}
                                            {intents.filter(i => i.name !== '_else').length === 0 && (
                                                <SidebarMenuSubItem>
                                                    <SidebarMenuSubButton
                                                        asChild
                                                        className="text-muted-foreground italic"
                                                    >
                                                        <Link to={projectPath('runbooks')}>
                                                            <span>{t('No runbooks yet')}</span>
                                                        </Link>
                                                    </SidebarMenuSubButton>
                                                </SidebarMenuSubItem>
                                            )}
                                        </SidebarMenuSub>
                                    </CollapsibleContent>
                                </SidebarMenuItem>
                            </Collapsible>
                        </SidebarMenu>
                    </SidebarGroupContent>
                </SidebarGroup>

                {/* ── Secondary nav (pushed to bottom) ── */}
                <SidebarGroup className="mt-auto">
                    <SidebarGroupContent>
                        <SidebarMenu>
                            {(() => {
                                const effectiveSupport = supportEmail || (isSaas ? DEFAULT_SAAS_EMAIL : '');
                                const effectiveFeedback = feedbackEmail || (isSaas ? DEFAULT_SAAS_EMAIL : '');
                                const items: { title: string; href: string; icon: LucideIcon }[] = [];
                                if (effectiveSupport) items.push({ title: 'Support', href: `mailto:${effectiveSupport}`, icon: LifeBuoy });
                                if (effectiveFeedback) items.push({ title: 'Feedback', href: `mailto:${effectiveFeedback}`, icon: Send });
                                return items.map(item => (
                                    <SidebarMenuItem key={item.title}>
                                        <SidebarMenuButton asChild size="sm" tooltip={t(item.title)}>
                                            <a href={item.href}>
                                                <item.icon />
                                                <span>{t(item.title)}</span>
                                            </a>
                                        </SidebarMenuButton>
                                    </SidebarMenuItem>
                                ));
                            })()}
                        </SidebarMenu>
                    </SidebarGroupContent>
                </SidebarGroup>
            </SidebarContent>

            {/* ── Footer: User menu with project switcher ── */}
            <SidebarFooter>
                <SidebarMenu>
                    <SidebarMenuItem>
                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <SidebarMenuButton
                                    size="lg"
                                    className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
                                >
                                    <Avatar className="h-8 w-8 rounded-lg">
                                        <AvatarFallback className="rounded-lg">{initials}</AvatarFallback>
                                    </Avatar>
                                    <div className="grid flex-1 text-left text-sm leading-tight">
                                        <span className="truncate font-medium">{userEmail || 'Admin'}</span>
                                        <span className="truncate text-xs text-muted-foreground">{activeProject?.name || t('No project')}</span>
                                    </div>
                                    <ChevronsUpDown className="ml-auto size-4" />
                                </SidebarMenuButton>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent
                                className="w-[--radix-dropdown-menu-trigger-width] min-w-56 rounded-lg"
                                side={isMobile ? 'bottom' : 'top'}
                                align="end"
                                sideOffset={4}
                            >
                                {/* ── Org / Projects ── */}
                                <DropdownMenuLabel className="text-xs text-muted-foreground">
                                    {tenantName || t('Organisation')}
                                </DropdownMenuLabel>
                                {projects.map((proj) => (
                                    <DropdownMenuItem
                                        key={proj.id}
                                        onClick={() => navigate(`/${tenantId}/${proj.id}`)}
                                        className="gap-2 p-2"
                                    >
                                        <FolderKanban className="size-4 shrink-0" />
                                        {proj.name}
                                        {activeProject?.id === proj.id && (
                                            <Check className="ml-auto size-4" />
                                        )}
                                    </DropdownMenuItem>
                                ))}
                                {isRoot && onCreateProject && capabilities.canManageProjectSettings && (
                                    <DropdownMenuItem onClick={onCreateProject} className="gap-2 p-2">
                                        {isFreePlan
                                            ? <Lock className="size-4 shrink-0 text-muted-foreground" />
                                            : <Plus className="size-4 shrink-0" />}
                                        <span className="text-muted-foreground">{t('New project')}</span>
                                        {isFreePlan && (
                                            <span className="ml-auto text-[10px] font-medium text-muted-foreground bg-muted rounded px-1.5 py-0.5">{t('Pro')}</span>
                                        )}
                                    </DropdownMenuItem>
                                )}
                                <DropdownMenuSeparator />

                                {/* ── Org group (root only) ── */}
                                {isRoot && (
                                    <>
                                        <DropdownMenuLabel className="text-xs text-muted-foreground">
                                            {tenantName || t('Organisation')}
                                        </DropdownMenuLabel>
                                        <DropdownMenuGroup>
                                            {(capabilities.canManageMembers || isDemoAccount) && (
                                                <DropdownMenuItem onClick={() => navigate(`/${tenantId}/users`)}>
                                                    <UsersIcon />
                                                    {t('Users')}
                                                </DropdownMenuItem>
                                            )}
                                            {isSaas && (capabilities.canManageBilling || isDemoAccount) && (
                                                <DropdownMenuItem onClick={() => navigate(`/${tenantId}/billing`)}>
                                                    <CreditCard />
                                                    {t('Billing')}
                                                </DropdownMenuItem>
                                            )}
                                            {(capabilities.canManageOrgSettings || isDemoAccount) && (
                                                <DropdownMenuItem onClick={() => navigate(`/${tenantId}/org`)}>
                                                    <Building2 />
                                                    {t('Organisation')}
                                                </DropdownMenuItem>
                                            )}
                                        </DropdownMenuGroup>
                                        <DropdownMenuSeparator />
                                    </>
                                )}

                                {/* ── Project group ── */}
                                <DropdownMenuLabel className="text-xs text-muted-foreground">
                                    {activeProject?.name || t('Project')}
                                </DropdownMenuLabel>
                                <DropdownMenuGroup>
                                    <DropdownMenuItem onClick={() => navigate(projectPath('settings'))}>
                                        <Settings2 />
                                        {t('Settings')}
                                    </DropdownMenuItem>
                                    {(canManageMembers || isDemoAccount) && (
                                        <DropdownMenuItem onClick={() => navigate(projectPath('members'))}>
                                            <UsersRound />
                                            {t('Members')}
                                        </DropdownMenuItem>
                                    )}
                                </DropdownMenuGroup>
                                {requireAuth && (
                                    <>
                                        <DropdownMenuSeparator />
                                        <DropdownMenuItem onClick={onSignOut}>
                                            <LogOut />
                                            {t('Sign out')}
                                        </DropdownMenuItem>
                                    </>
                                )}
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </SidebarMenuItem>
                </SidebarMenu>
            </SidebarFooter>
        </Sidebar>
    );
}
