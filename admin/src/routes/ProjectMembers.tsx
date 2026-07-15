import { useCallback, useEffect, useState } from 'react';
import { Loader, RefreshCcw, Trash2, UserPlus, Zap } from 'lucide-react';
import { toast } from 'sonner';

import { api } from '@/api/endpoints';
import type { BillingStatus, ProjectMember, TenantUser } from '@/api/endpoints';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { settings as appSettings } from '@/settings';
import { useI18n } from '@/lib/i18n-context';

// ── Types ─────────────────────────────────────────────────────────────────────

interface ProjectMembersProps {
    projectId: string;
    /** Current user's email — used to prevent adding self. */
    userEmail: string;
    isDemoAccount?: boolean;
}

type Role = 'admin' | 'editor' | 'viewer';

const ROLES: { value: Role; label: string; description: string }[] = [
    { value: 'admin', label: 'Admin', description: 'Full project access including member management' },
    { value: 'editor', label: 'Editor', description: 'Can edit runbooks, support setup, and publish' },
    { value: 'viewer', label: 'Viewer', description: 'Read-only access to project data' },
];

function roleBadgeVariant(role: string): 'default' | 'secondary' | 'outline' {
    if (role === 'admin') return 'default';
    if (role === 'editor') return 'secondary';
    return 'outline';
}

// ── Component ─────────────────────────────────────────────────────────────────

export const ProjectMembers = ({ projectId, userEmail, isDemoAccount = false }: ProjectMembersProps) => {
    const [members, setMembers] = useState<ProjectMember[]>([]);
    const [tenantUsers, setTenantUsers] = useState<TenantUser[]>([]);
    const [loading, setLoading] = useState(true);
    const [deletingId, setDeletingId] = useState<string | null>(null);
    const [adding, setAdding] = useState(false);
    const [addDialogOpen, setAddDialogOpen] = useState(false);
    const [selectedUserId, setSelectedUserId] = useState('');
    const [selectedRole, setSelectedRole] = useState<Role>('viewer');
    const [billing, setBilling] = useState<BillingStatus | null>(null);
    const { t } = useI18n();

    const loadMembers = useCallback(async () => {
        if (isDemoAccount) {
            setMembers([{
                id: 'demo-current-member',
                userId: 'demo-current-user',
                email: userEmail || 'demo@mantly.io',
                isRoot: true,
                role: 'admin',
                projectId,
                created: '',
            }]);
            return;
        }
        const res = await api.listMembers(projectId);
        if (res.data) setMembers(res.data);
    }, [isDemoAccount, projectId, userEmail]);

    const loadTenantUsers = useCallback(async () => {
        if (isDemoAccount) {
            setTenantUsers([{
                id: 'demo-current-user',
                email: userEmail || 'demo@mantly.io',
                name: 'Demo User',
                language: 'en',
                isRoot: true,
                mustChangePassword: false,
                passwordLoginEnabled: true,
                defaultProject: projectId,
                created: '',
            }]);
            return;
        }
        const res = await api.getUsers();
        if (res.data) setTenantUsers(res.data);
    }, [isDemoAccount, projectId, userEmail]);

    useEffect(() => {
        let cancelled = false;
        if (isDemoAccount) {
            void Promise.resolve().then(() => {
                if (cancelled) return;
                setMembers([{
                    id: 'demo-current-member',
                    userId: 'demo-current-user',
                    email: userEmail || 'demo@mantly.io',
                    isRoot: true,
                    role: 'admin',
                    projectId,
                    created: '',
                }]);
                setTenantUsers([{
                    id: 'demo-current-user',
                    email: userEmail || 'demo@mantly.io',
                    name: 'Demo User',
                    language: 'en',
                    isRoot: true,
                    mustChangePassword: false,
                    passwordLoginEnabled: true,
                    defaultProject: projectId,
                    created: '',
                }]);
                setBilling({
                    plan: 'business',
                    subscriptionStatus: 'active',
                    cancelAtPeriodEnd: false,
                    currentPeriodStart: '',
                    currentPeriodEnd: '',
                    usage: {
                        emailsThisPeriod: 0,
                        projects: 1,
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
                cancelled = true;
            };
        }
        const promises: Promise<unknown>[] = [
            api.listMembers(projectId),
            api.getUsers(),
        ];
        if (appSettings.isSaas) promises.push(api.getBillingStatus());

        void Promise.all(promises).then((results) => {
            if (cancelled) return;
            const [membersRes, usersRes, billingRes] = results as [
                Awaited<ReturnType<typeof api.listMembers>>,
                Awaited<ReturnType<typeof api.getUsers>>,
                Awaited<ReturnType<typeof api.getBillingStatus>> | undefined,
            ];
            if (membersRes.data) setMembers(membersRes.data);
            if (usersRes.data) setTenantUsers(usersRes.data);
            if (billingRes?.data) setBilling(billingRes.data);
            setLoading(false);
        });
        return () => {
            cancelled = true;
        };
    }, [isDemoAccount, projectId, userEmail]);

    // Users not yet added as members — also exclude the current user
    const memberUserIds = new Set(members.map((m) => m.userId));
    const availableUsers = tenantUsers.filter(
        (u) => !memberUserIds.has(u.id) && u.email !== userEmail,
    );

    const plan = billing?.plan ?? 'free';
    const usersLimit = billing?.limits.users ?? 1;
    const canAddMembers = !appSettings.isSaas || plan !== 'free';

    const handleAdd = async () => {
        if (isDemoAccount) return;
        if (!selectedUserId) return;
        setAdding(true);
        const res = await api.addMember(projectId, selectedUserId, selectedRole);
        if (res.error) {
            toast.error(res.error);
        } else {
            toast.success(t('Member added'));
            setSelectedUserId('');
            setSelectedRole('viewer');
            setAddDialogOpen(false);
            void loadMembers();
        }
        setAdding(false);
    };

    const handleRoleChange = async (memberId: string, newRole: Role) => {
        if (isDemoAccount) return;
        const res = await api.updateMemberRole(projectId, memberId, newRole);
        if (res.error) {
            toast.error(res.error);
        } else {
            toast.success(t('Role updated'));
            void loadMembers();
        }
    };

    const handleRemove = async (memberId: string) => {
        if (isDemoAccount) return;
        if (!confirm(t('Remove this member from the project?'))) return;
        setDeletingId(memberId);
        const res = await api.removeMember(projectId, memberId);
        if (res.error) {
            toast.error(res.error);
        } else {
            toast.success(t('Member removed'));
            setMembers((prev) => prev.filter((m) => m.id !== memberId));
        }
        setDeletingId(null);
    };

    // Resolve user email — backend enriches members with email directly
    const getUserEmail = (member: ProjectMember): string => {
        return member.email || member.userId;
    };

    return (
        <div className="w-full max-w-2xl mx-auto space-y-6">
            <div>
                <h2 className="text-lg font-semibold mb-1">{t('Project Members')}</h2>
                <p className="text-sm text-muted-foreground">
                    {isDemoAccount
                        ? t('Demo accounts show project member management as a read-only product surface.')
                        : t('Manage who has access to this project and their permission level.')}
                </p>
            </div>

            <Card>
                <CardHeader>
                    <div className="flex items-center justify-between gap-3">
                        <div>
                            <h3 className="text-base font-semibold">{t('Members')}</h3>
                            <p className="text-sm text-muted-foreground">
                                {members.length} {members.length === 1 ? t('member') : t('members')}
                            </p>
                        </div>
                        <div className="flex shrink-0 items-center gap-2">
                            <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
                                <DialogTrigger asChild>
                                    <Button size="sm" disabled={isDemoAccount}>
                                        <UserPlus className="size-4" />
                                        {t('Add member')}
                                    </Button>
                                </DialogTrigger>
                                <DialogContent>
                                    <DialogHeader>
                                        <DialogTitle>{t('Add member')}</DialogTitle>
                                        <DialogDescription>
                                            {canAddMembers
                                                ? t('Select a tenant user and assign a project role.')
                                                : t('The Free plan is limited to {count} {unit}. Upgrade to Pro to add team members to projects.', {
                                                    count: usersLimit,
                                                    unit: usersLimit === 1 ? t('user') : t('users'),
                                                })}
                                        </DialogDescription>
                                    </DialogHeader>
                                    {canAddMembers ? (
                                        <div className="space-y-4">
                                            <div className="space-y-1.5">
                                                <Label htmlFor="member-user">{t('User')}</Label>
                                                <Select
                                                    value={selectedUserId}
                                                    onValueChange={setSelectedUserId}
                                                >
                                                    <SelectTrigger id="member-user" className="w-full">
                                                        <SelectValue placeholder={t('Select a user...')} />
                                                    </SelectTrigger>
                                                    <SelectContent>
                                                        {availableUsers.map((u) => (
                                                            <SelectItem key={u.id} value={u.id}>
                                                                {u.email}
                                                            </SelectItem>
                                                        ))}
                                                    </SelectContent>
                                                </Select>
                                                {availableUsers.length === 0 && !loading && (
                                                    <p className="text-xs text-muted-foreground">
                                                        {t('All tenant users are already members of this project.')}
                                                    </p>
                                                )}
                                            </div>
                                            <div className="space-y-1.5">
                                                <Label htmlFor="member-role">{t('Role')}</Label>
                                                <RadioGroup value={selectedRole} onValueChange={(value) => setSelectedRole(value as Role)} className="space-y-2">
                                                    {ROLES.map((r) => (
                                                        <Label
                                                            key={r.value}
                                                            className={`flex items-start gap-3 rounded-lg border p-3 cursor-pointer transition-colors ${
                                                                selectedRole === r.value
                                                                    ? 'border-foreground/30 bg-muted/50'
                                                                    : 'hover:bg-muted/30'
                                                            }`}
                                                        >
                                                            <RadioGroupItem
                                                                value={r.value}
                                                                className="mt-0.5"
                                                            />
                                                            <div>
                                                                <div className="text-sm font-medium flex items-center gap-2">
                                                                    {t(r.label)}
                                                                    <Badge variant={roleBadgeVariant(r.value)} className="text-[10px]">
                                                                        {r.value}
                                                                    </Badge>
                                                                </div>
                                                                <p className="text-xs text-muted-foreground mt-0.5">
                                                                    {t(r.description)}
                                                                </p>
                                                            </div>
                                                        </Label>
                                                    ))}
                                                </RadioGroup>
                                            </div>
                                            <Button
                                                className="w-full"
                                                onClick={handleAdd}
                                                disabled={adding || !selectedUserId}
                                            >
                                                {adding ? (
                                                    <Loader className="size-4 animate-spin" />
                                                ) : (
                                                    <UserPlus className="size-4" />
                                                )}
                                                {t('Add member')}
                                            </Button>
                                        </div>
                                    ) : (
                                        <Button
                                            variant="default"
                                            className="w-full"
                                            onClick={() => window.location.assign(`/${window.location.pathname.split('/')[1]}/billing`)}
                                        >
                                            <Zap className="size-4" />
                                            {t('Upgrade to Pro')}
                                        </Button>
                                    )}
                                </DialogContent>
                            </Dialog>
                            <Button
                                variant="outline"
                                size="icon-sm"
                                aria-label={t('Refresh')}
                                onClick={() => {
                                    void loadMembers();
                                    void loadTenantUsers();
                                }}
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
                            {t('Loading members...')}
                        </div>
                    ) : members.length === 0 ? (
                        <div className="rounded-lg border border-dashed px-4 py-8 text-sm text-muted-foreground text-center">
                            {t('No members yet. Add users from your tenant.')}
                        </div>
                    ) : (
                        <div className="overflow-x-auto rounded-lg border">
                            <div className="min-w-[420px]">
                                <div className="grid grid-cols-[minmax(0,1.3fr)_140px_88px] gap-3 border-b bg-muted/30 px-4 py-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                                    <div>{t('User')}</div>
                                    <div>{t('Role')}</div>
                                    <div className="text-right">{t('Action')}</div>
                                </div>
                                {members.map((member) => (
                                    <div
                                        key={member.id}
                                        className="grid grid-cols-[minmax(0,1.3fr)_140px_88px] gap-3 border-b last:border-b-0 px-4 py-3 text-sm items-center"
                                    >
                                        <div className="min-w-0">
                                            <div className="truncate font-medium">
                                                {getUserEmail(member)}
                                                {member.email === userEmail && (
                                                    <span className="ml-2 text-xs text-muted-foreground">{t('(you)')}</span>
                                                )}
                                            </div>
                                        </div>
                                        <div>
                                            <Select
                                                value={member.role}
                                                disabled={isDemoAccount}
                                                onValueChange={(value) =>
                                                    handleRoleChange(
                                                        member.id,
                                                        value as Role,
                                                    )
                                                }
                                            >
                                                <SelectTrigger data-size="sm" className="h-8 w-[140px] text-xs">
                                                    <SelectValue />
                                                </SelectTrigger>
                                                <SelectContent>
                                                    {ROLES.map((r) => (
                                                        <SelectItem key={r.value} value={r.value}>
                                                            {t(r.label)}
                                                        </SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                        </div>
                                        <div className="flex justify-end">
                                            <Button
                                                variant="ghost"
                                                size="sm"
                                                onClick={() => handleRemove(member.id)}
                                                disabled={isDemoAccount || deletingId === member.id}
                                                className="text-muted-foreground"
                                            >
                                                {deletingId === member.id ? (
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
