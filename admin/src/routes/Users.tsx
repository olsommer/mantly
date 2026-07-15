import { useCallback, useEffect, useState } from 'react';
import { Loader, RefreshCcw, Trash2, UserPlus, Zap } from 'lucide-react';
import { toast } from 'sonner';

import { api } from '@/api/endpoints';
import type { BillingStatus, Project, TenantUser } from '@/api/endpoints';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { settings as appSettings } from '@/settings';
import { useI18n } from '@/lib/i18n-context';
import type { Locale } from '@/lib/i18n-core';

function formatCreated(value: string, locale: Locale, t: (key: string) => string) {
    if (!value) return t('Unknown');

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;

    return new Intl.DateTimeFormat(locale === 'de' ? 'de-DE' : 'en-US', {
        dateStyle: 'medium',
        timeStyle: 'short',
    }).format(date);
}

export const Users = ({
    isDemoAccount = false,
    userEmail = '',
    projects: demoProjects = [],
}: {
    isDemoAccount?: boolean;
    userEmail?: string;
    projects?: Project[];
}) => {
    const [users, setUsers] = useState<TenantUser[]>([]);
    const [projects, setProjects] = useState<Project[]>([]);
    const [loading, setLoading] = useState(true);
    const [isCreating, setIsCreating] = useState(false);
    const [addDialogOpen, setAddDialogOpen] = useState(false);
    const [deletingUserId, setDeletingUserId] = useState<string | null>(null);
    const [savingDefaultProject, setSavingDefaultProject] = useState<string | null>(null);
    const [savingPasswordLogin, setSavingPasswordLogin] = useState<string | null>(null);

    // On-prem form state
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [isRoot, setIsRoot] = useState(false);

    // SaaS invite-by-email form state
    const [inviteEmail, setInviteEmail] = useState('');

    // Billing (SaaS only)
    const [billing, setBilling] = useState<BillingStatus | null>(null);
    const { locale, t } = useI18n();

    const loadUsers = useCallback(async () => {
        if (isDemoAccount) {
            setUsers([{
                id: 'demo-current-user',
                email: userEmail || 'demo@mantly.io',
                name: 'Demo User',
                language: 'en',
                isRoot: true,
                mustChangePassword: false,
                passwordLoginEnabled: true,
                defaultProject: demoProjects[0]?.id ?? null,
                created: '',
            }]);
            return;
        }
        const result = await api.getUsers();
        if (result.error || !result.data) {
            toast.error(result.error || t('Failed to load users.'));
            setUsers([]);
            return;
        }
        setUsers(result.data);
    }, [demoProjects, isDemoAccount, t, userEmail]);

    useEffect(() => {
        let isActive = true;
        if (isDemoAccount) {
            void Promise.resolve().then(() => {
                if (!isActive) return;
                setUsers([{
                    id: 'demo-current-user',
                    email: userEmail || 'demo@mantly.io',
                    name: 'Demo User',
                    language: 'en',
                    isRoot: true,
                    mustChangePassword: false,
                    passwordLoginEnabled: true,
                    defaultProject: demoProjects[0]?.id ?? null,
                    created: '',
                }]);
                setProjects(demoProjects);
                setBilling({
                    plan: 'business',
                    subscriptionStatus: 'active',
                    cancelAtPeriodEnd: false,
                    currentPeriodStart: '',
                    currentPeriodEnd: '',
                    usage: {
                        emailsThisPeriod: 0,
                        projects: demoProjects.length,
                        users: 1,
                        evalRunsThisPeriod: 0,
                        evalSets: 0,
                    },
                    llmUsage: {
                        eventCount: 0,
                        managedEventCount: 0,
                        reportedEventCount: 0,
                        rawCostUsdMicros: 0,
                        billedCostUsdMicros: 0,
                        rawCostUsd: 0,
                        billedCostUsd: 0,
                    },
                    syncedAddons: {},
                    limits: {
                        emailsPerMonth: 1000,
                        projects: 1,
                        users: 5,
                        evalRunsPerMonth: Number.POSITIVE_INFINITY,
                        evalSets: Number.POSITIVE_INFINITY,
                        evalCasesPerSet: Number.POSITIVE_INFINITY,
                        retentionDays: 90,
                    },
                    features: {
                        feedback_learnings: true,
                        security_monitoring: true,
                        byok_llm: true,
                        custom_llm_gateway: true,
                    },
                });
                setLoading(false);
            });
            return () => {
                isActive = false;
            };
        }
        const promises: Promise<unknown>[] = [api.getUsers(), api.listProjects()];
        if (appSettings.isSaas) promises.push(api.getBillingStatus());

        void Promise.all(promises).then((results) => {
            if (!isActive) return;
            const [usersRes, projectsRes, billingRes] = results as [
                Awaited<ReturnType<typeof api.getUsers>>,
                Awaited<ReturnType<typeof api.listProjects>>,
                Awaited<ReturnType<typeof api.getBillingStatus>> | undefined,
            ];
            if (usersRes.error || !usersRes.data) {
                toast.error(usersRes.error || t('Could not load users.'));
            } else {
                setUsers(usersRes.data);
            }
            if (projectsRes.data) {
                setProjects(projectsRes.data);
            }
            if (billingRes?.data) {
                setBilling(billingRes.data);
            }
            setLoading(false);
        });
        return () => {
            isActive = false;
        };
    }, [demoProjects, isDemoAccount, t, userEmail]);

    // ── On-prem: create user with temp password ──────────────────────────────

    const handleCreateUser = async (e: React.FormEvent) => {
        e.preventDefault();
        if (isDemoAccount) return;

        if (password.length < 8) {
            toast.error(t('Password must be at least 8 characters.'));
            return;
        }

        setIsCreating(true);
        try {
            const result = await api.createUser(email.trim(), password, isRoot);
            if (result.error || !result.data) {
                toast.error(result.error || t('Failed to create user.'));
                return;
            }

            toast.success(t('User created.'));
            setEmail('');
            setPassword('');
            setIsRoot(false);
            setAddDialogOpen(false);
            await loadUsers();
        } finally {
            setIsCreating(false);
        }
    };

    // ── SaaS: invite user by email ───────────────────────────────────────────

    const handleInviteByEmail = async (e: React.FormEvent) => {
        e.preventDefault();
        if (isDemoAccount) return;
        const trimmed = inviteEmail.trim().toLowerCase();
        if (!trimmed) return;

        setIsCreating(true);
        try {
            const result = await api.addUserByEmail(trimmed);
            if (result.error || !result.data) {
                toast.error(result.error || t('Failed to add user.'));
                return;
            }
            toast.success(t('User added to your organisation.'));
            setInviteEmail('');
            setAddDialogOpen(false);
            await loadUsers();
        } finally {
            setIsCreating(false);
        }
    };

    const handleDeleteUser = async (user: TenantUser) => {
        if (isDemoAccount) return;
        if (!window.confirm(t('Delete {email}?', { email: user.email }))) return;

        setDeletingUserId(user.id);
        try {
            const result = await api.deleteUser(user.id);
            if (result.error) {
                toast.error(result.error);
                return;
            }

            toast.success(t('User deleted.'));
            setUsers((current) => current.filter((candidate) => candidate.id !== user.id));
        } finally {
            setDeletingUserId(null);
        }
    };

    const handleDefaultProjectChange = async (userId: string, projectId: string) => {
        if (isDemoAccount) return;
        setSavingDefaultProject(userId);
        try {
            const result = await api.setUserDefaultProject(userId, projectId || null);
            if (result.error) {
                toast.error(result.error);
                return;
            }
            setUsers((current) =>
                current.map((u) =>
                    u.id === userId ? { ...u, defaultProject: projectId || null } : u,
                ),
            );
            toast.success(t('Default project updated.'));
        } finally {
            setSavingDefaultProject(null);
        }
    };

    const handlePasswordLoginChange = async (userId: string, enabled: boolean) => {
        if (isDemoAccount) return;
        setSavingPasswordLogin(userId);
        try {
            const result = await api.setUserPasswordLogin(userId, enabled);
            if (result.error) {
                toast.error(result.error);
                return;
            }
            setUsers((current) =>
                current.map((u) =>
                    u.id === userId ? { ...u, passwordLoginEnabled: enabled } : u,
                ),
            );
            toast.success(enabled ? t('Password login enabled.') : t('Password login disabled.'));
        } finally {
            setSavingPasswordLogin(null);
        }
    };

    const plan = billing?.plan ?? 'free';
    const canAddUsers = !appSettings.isSaas || !billing || plan !== 'free';
    const usersLimit = billing?.limits.users ?? 1;
    const includedSeatCopy = usersLimit === 1
        ? t('1 user is included')
        : t('{count} users are included', { count: usersLimit });
    const seatBillingCopy = billing
        ? t('{included} in {plan}. Extra users are added as paid seats.', { included: includedSeatCopy, plan })
        : t('Plan limits are loading. The backend will enforce seat limits before saving.');

    const addUserLabel = appSettings.isSaas ? t('Add team member') : t('Add user');

    return (
        <div className="w-full max-w-2xl mx-auto space-y-6">
            <div>
                <h2 className="text-lg font-semibold mb-1">{t('Users')}</h2>
                <p className="text-sm text-muted-foreground">
                    {appSettings.isSaas
                        ? isDemoAccount
                            ? t('Demo accounts show user management as a read-only product surface.')
                            : t('Manage users in your organisation. Users must create their own account first.')
                        : t('Create tenant users with an initial password. They will be forced to change it after their first login.')}
                </p>
            </div>

            <Card>
                <CardHeader>
                    <div className="flex items-center justify-between gap-3">
                        <div>
                            <h3 className="text-base font-semibold">{t('Provisioned users')}</h3>
                            <p className="text-sm text-muted-foreground">
                                {t('Only users in your current tenant are listed here.')}
                            </p>
                        </div>
                        <div className="flex shrink-0 items-center gap-2">
                            <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
                                <DialogTrigger asChild>
                                    <Button size="sm" disabled={isDemoAccount}>
                                        <UserPlus className="size-4" />
                                        {addUserLabel}
                                    </Button>
                                </DialogTrigger>
                                <DialogContent>
                                    <DialogHeader>
                                        <DialogTitle>{addUserLabel}</DialogTitle>
                                        <DialogDescription>
                                            {appSettings.isSaas
                                                ? canAddUsers
                                                    ? t('Enter the email of an existing user. They must have created their own account first.')
                                                    : t('The Free plan is limited to 1 user. Upgrade to Pro to add team members to your organisation.')
                                                : t('This password is temporary. Share it securely with the user.')}
                                        </DialogDescription>
                                    </DialogHeader>
                                    {appSettings.isSaas ? (
                                        canAddUsers ? (
                                            <form onSubmit={handleInviteByEmail} className="space-y-4">
                                                <div className="space-y-1.5">
                                                    <Label htmlFor="invite-email">{t('Email address')}</Label>
                                                    <Input
                                                        id="invite-email"
                                                        type="email"
                                                        value={inviteEmail}
                                                        onChange={(e) => setInviteEmail(e.target.value)}
                                                        placeholder="user@example.com"
                                                        required
                                                    />
                                                    <p className="text-xs text-muted-foreground">
                                                        {t('This links the existing account to your organisation.')} {seatBillingCopy}
                                                    </p>
                                                </div>
                                                <Button type="submit" className="w-full" disabled={isCreating}>
                                                    {isCreating ? <Loader className="size-4 animate-spin" /> : <UserPlus className="size-4" />}
                                                    {t('Add to organisation')}
                                                </Button>
                                            </form>
                                        ) : (
                                            <Button variant="default" className="w-full" onClick={() => window.location.assign(`/${window.location.pathname.split('/')[1]}/billing`)}>
                                                <Zap className="size-4" />
                                                {t('Upgrade to Pro')}
                                            </Button>
                                        )
                                    ) : (
                                        <form onSubmit={handleCreateUser} className="space-y-4">
                                            <div className="space-y-1.5">
                                                <Label htmlFor="new-user-email">{t('Email')}</Label>
                                                <Input
                                                    id="new-user-email"
                                                    type="email"
                                                    value={email}
                                                    onChange={(e) => setEmail(e.target.value)}
                                                    placeholder="user@example.com"
                                                    required
                                                />
                                            </div>
                                            <div className="space-y-1.5">
                                                <Label htmlFor="new-user-password">{t('Initial password')}</Label>
                                                <Input
                                                    id="new-user-password"
                                                    type="password"
                                                    value={password}
                                                    onChange={(e) => setPassword(e.target.value)}
                                                    minLength={8}
                                                    required
                                                />
                                                <p className="text-xs text-muted-foreground">
                                                    {t('Minimum 8 characters.')}
                                                </p>
                                            </div>
                                            <div className="flex items-start justify-between gap-3 rounded-lg border p-3">
                                                <div>
                                                    <Label htmlFor="new-user-admin">{t('Root access')}</Label>
                                                    <p className="text-xs text-muted-foreground mt-1">
                                                        {t('Root users can manage all projects and tenant-level settings.')}
                                                    </p>
                                                </div>
                                                <Switch
                                                    id="new-user-admin"
                                                    checked={isRoot}
                                                    onCheckedChange={setIsRoot}
                                                />
                                            </div>
                                            <Button type="submit" className="w-full" disabled={isCreating}>
                                                {isCreating ? <Loader className="size-4 animate-spin" /> : <UserPlus className="size-4" />}
                                                {t('Create user')}
                                            </Button>
                                        </form>
                                    )}
                                </DialogContent>
                            </Dialog>
                            <Button
                                variant="outline"
                                size="icon-sm"
                                aria-label={t('Refresh')}
                                onClick={() => { setLoading(true); void loadUsers().finally(() => setLoading(false)); }}
                                disabled={loading}
                            >
                                {loading ? <Loader className="size-4 animate-spin" /> : <RefreshCcw className="size-4" />}
                            </Button>
                        </div>
                    </div>
                </CardHeader>
                <CardContent>
                    {loading ? (
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                            <Loader className="size-4 animate-spin" />
                            {t('Loading users...')}
                        </div>
                    ) : users.length === 0 ? (
                        <div className="rounded-lg border border-dashed px-4 py-8 text-sm text-muted-foreground">
                            {t('No users created yet.')}
                        </div>
                    ) : (
                        <div className="overflow-x-auto rounded-lg border">
                            <div className="min-w-[820px]">
                                <div className="grid grid-cols-[minmax(0,1.3fr)_100px_180px_140px_130px_72px] items-center gap-3 border-b bg-muted/30 px-4 py-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                                    <div>{t('Email')}</div>
                                    <div>{t('Role')}</div>
                                    <div>{t('Default project')}</div>
                                    <div>{t('Created')}</div>
                                    <div>{t('Password login')}</div>
                                    <div className="text-right">{t('Action')}</div>
                                </div>
                                {users.map((user) => (
                                    <div
                                        key={user.id}
                                        className="grid grid-cols-[minmax(0,1.3fr)_100px_180px_140px_130px_72px] items-center gap-3 border-b last:border-b-0 px-4 py-3 text-sm"
                                    >
                                        <div className="min-w-0">
                                            <div className="truncate font-medium">{user.name || user.email}</div>
                                            {user.name && (
                                                <div className="truncate text-xs text-muted-foreground">{user.email}</div>
                                            )}
                                            {user.mustChangePassword && (
                                                <div className="mt-1">
                                                    <Badge variant="outline">{t('Password change required')}</Badge>
                                                </div>
                                            )}
                                        </div>
                                        <div>
                                            <Badge variant={user.isRoot ? 'default' : 'secondary'}>
                                                {user.isRoot ? t('Root') : t('User')}
                                            </Badge>
                                        </div>
                                        <div>
                                            <Select
                                                value={user.defaultProject || '__none__'}
                                                onValueChange={(value) => void handleDefaultProjectChange(user.id, value === '__none__' ? '' : value)}
                                                disabled={isDemoAccount || savingDefaultProject === user.id}
                                            >
                                                <SelectTrigger data-size="sm" className="h-8 w-full text-xs">
                                                    <SelectValue placeholder={t('None')} />
                                                </SelectTrigger>
                                                <SelectContent>
                                                    <SelectItem value="__none__">{t('None')}</SelectItem>
                                                    {projects.map((proj) => (
                                                        <SelectItem key={proj.id} value={proj.id}>
                                                            {proj.name}
                                                        </SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                        </div>
                                        <div className="text-xs text-muted-foreground">{formatCreated(user.created, locale, t)}</div>
                                        <div className="flex items-center gap-2">
                                            <Switch
                                                checked={user.passwordLoginEnabled}
                                                onCheckedChange={(enabled) => void handlePasswordLoginChange(user.id, enabled)}
                                                disabled={isDemoAccount || savingPasswordLogin === user.id}
                                            />
                                            {savingPasswordLogin === user.id && <Loader className="size-3 animate-spin text-muted-foreground" />}
                                        </div>
                                        <div className="flex justify-end">
                                            <Button
                                                variant="ghost"
                                                size="sm"
                                                onClick={() => void handleDeleteUser(user)}
                                                disabled={isDemoAccount || deletingUserId === user.id}
                                                className="text-muted-foreground"
                                            >
                                                {deletingUserId === user.id ? (
                                                    <Loader className="size-4 animate-spin" />
                                                ) : (
                                                    <Trash2 className="size-4" />
                                                )}
                                            </Button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </CardContent>
            </Card>
        </div>
    );
};
