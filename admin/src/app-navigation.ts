import { matchPath } from 'react-router-dom';
import type { LucideIcon } from 'lucide-react';
import { FlaskConical, Search, Tag } from 'lucide-react';
import type { Section } from './components/app-sidebar';

export const TENANT_ONLY_SEGMENTS = new Set(['users', 'billing', 'org']);

export const SECTION_TO_PATH: Record<string, string> = {
    inbox: 'inbox',
    accounts: 'accounts',
    knowledge: 'knowledge',
    channels: 'channels',
    automations: 'automations',
    analytics: 'analytics',
    monitor: 'monitor',
    pipeline: 'support-setup',
    tools: 'customer-identity',
    intents: 'runbooks',
    settings: 'settings',
    demo: 'preview',
    eval: 'eval',
    members: 'members',
};

export const SECTION_LABELS: Record<Section, string> = {
    inbox: 'Inbox',
    accounts: 'Accounts',
    knowledge: 'Knowledge',
    channels: 'Channel setup',
    automations: 'Workflow rules',
    analytics: 'Analytics',
    monitor: 'Monitor',
    pipeline: 'AI setup',
    tools: 'Identity rules',
    intents: 'AI runbooks',
    settings: 'Settings',
    users: 'Users',
    demo: 'Preview & Publish',
    eval: 'Evaluation',
    members: 'Members',
    billing: 'Billing',
    org: 'Organisation',
};

export const PIPELINE_STEPS: {
    id: Section;
    step: number;
    icon: LucideIcon;
    title: string;
    description: string;
}[] = [
    {
        id: 'tools',
        step: 1,
        icon: Search,
        title: 'Identity rules',
        description: 'Data sources that match senders to accounts and contacts before ticket triage.',
    },
    {
        id: 'intents',
        step: 2,
        icon: Tag,
        title: 'AI runbooks',
        description: 'Instructions, tools, and actions the agent uses to classify tickets and prepare replies.',
    },
    {
        id: 'eval',
        step: 3,
        icon: FlaskConical,
        title: 'Evaluation',
        description: 'Test your setup against example emails and compare results to expected outcomes.',
    },
];

export function getProjectIdFromPath(pathname: string): string | null {
    const match = matchPath('/:tenantId/:projectId/*', pathname);
    const id = match?.params.projectId;
    if (!id || TENANT_ONLY_SEGMENTS.has(id)) return null;
    if (!match) {
        const exact = matchPath('/:tenantId/:projectId', pathname);
        const eid = exact?.params.projectId;
        if (eid && !TENANT_ONLY_SEGMENTS.has(eid)) return eid;
    }
    return id ?? null;
}

export function getSectionFromPath(pathname: string): Section | null {
    if (matchPath('/:t/users', pathname)) return 'users';
    if (matchPath('/:t/billing', pathname)) return 'billing';
    if (matchPath('/:t/org', pathname)) return 'org';
    if (matchPath('/:t/:p/inbox', pathname) || matchPath('/:t/:p/inbox/*', pathname)) return 'inbox';
    if (matchPath('/:t/:p/accounts', pathname) || matchPath('/:t/:p/accounts/*', pathname)) return 'accounts';
    if (matchPath('/:t/:p/knowledge', pathname) || matchPath('/:t/:p/knowledge/*', pathname)) return 'knowledge';
    if (matchPath('/:t/:p/channels', pathname)) return 'channels';
    if (matchPath('/:t/:p/automations', pathname)) return 'automations';
    if (matchPath('/:t/:p/analytics', pathname)) return 'analytics';
    if (matchPath('/:t/:p/monitor', pathname)) return 'monitor';
    if (matchPath('/:t/:p/support-setup', pathname) || matchPath('/:t/:p/pipeline', pathname)) return 'pipeline';
    if (matchPath('/:t/:p/customer-identity', pathname) || matchPath('/:t/:p/customer', pathname)) return 'tools';
    if (matchPath('/:t/:p/runbooks', pathname) || matchPath('/:t/:p/runbooks/*', pathname)) return 'intents';
    if (matchPath('/:t/:p/intents', pathname) || matchPath('/:t/:p/intents/*', pathname)) return 'intents';
    if (matchPath('/:t/:p/settings', pathname)) return 'settings';
    if (matchPath('/:t/:p/preview', pathname)) return 'demo';
    if (matchPath('/:t/:p/eval', pathname) || matchPath('/:t/:p/eval/*', pathname)) return 'eval';
    if (matchPath('/:t/:p/members', pathname)) return 'members';
    return null;
}

export function getIntentNameFromPath(pathname: string): string | null {
    const match = matchPath('/:tenantId/:projectId/runbooks/:intentName', pathname)
        ?? matchPath('/:tenantId/:projectId/intents/:intentName', pathname);
    return match?.params.intentName ?? null;
}
