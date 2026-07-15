import type { Email, Message } from '@/models/email';
import { apiClient } from './client';
import type { ApiResponse } from './client';
import { settings } from '@/settings';
import type { Locale } from '@/lib/i18n';

const pathParam = (value: string) => encodeURIComponent(value);

interface ProcessEmailRequest {
    email: Email;
    action: 'respond';
    creator: string;
    projectId?: string;
}

/**
 * API Endpoints
 * All endpoints automatically use the correct base URL from settings
 */
export interface AuthResponse {
    token: string;
    email: string;
    language: Locale;
    tenantId: string;
    tenantName?: string;
    isRoot?: boolean;
    isAdmin?: boolean;
    isPlatformAdmin?: boolean;
    tenantAccountType?: 'normal' | 'demo';
    capabilities?: Record<string, boolean>;
    mustChangePassword: boolean;
}

export interface ProjectSummary {
    id: string;
    name: string;
    description?: string;
    tenant: string;
    role?: string;
}

export interface MeResponse {
    id: string;
    email: string;
    name: string;
    language: Locale;
    defaultProject: string | null;
    projects: ProjectSummary[];
    branding?: {
        primaryColor?: string;
    };
}

export interface SupportIssueSummary {
    id: string;
    sourceEmailId: string;
    chatId: string;
    subject: string;
    status: string;
    workflowStatus?: string;
    priority: string;
    assigneeEmail: string;
    accountName: string;
    contactEmail: string;
    fromAddress: string;
    channel: string;
    requiresHuman: boolean;
    needsResponse?: boolean;
    latestMessageDirection?: string;
    latestCustomerMessageAt?: string;
    pendingApprovalCount: number;
    hasPendingApproval: boolean;
    failedDeliveryCount?: number;
    hasFailedDelivery?: boolean;
    pendingDeliveryCount?: number;
    hasPendingDelivery?: boolean;
    hasOverdueSla?: boolean;
    nextSlaTargetAt?: string;
    nextSlaEventType?: string;
    messageCount: number;
}

export interface SupportBulkApproveSendResult {
    processed: number;
    approved?: number;
    sent: number;
    failed: Array<{ id: string; replyId?: string; error: string }>;
    issues: SupportIssueSummary[];
}

export interface SupportOutboundMessage {
    id: string;
    issue?: string;
    subject?: string;
    body: string;
    status: string;
    metadata?: Record<string, unknown>;
    attachments?: unknown[];
}

// ── PocketBase direct auth helpers ────────────────────────────────────────────

async function pbFetch<T>(path: string, options: RequestInit = {}): Promise<ApiResponse<T>> {
    try {
        const resp = await fetch(`${settings.pbBaseUrl}${path}`, {
            headers: { 'Content-Type': 'application/json', ...options.headers },
            ...options,
        });
        const text = await resp.text();
        const data = text ? JSON.parse(text) as T | { message?: string; error?: string } : null;
        if (!resp.ok) {
            const message = (
                data
                && typeof data === 'object'
                && ('message' in data || 'error' in data)
            )
                ? data.message || data.error || `HTTP ${resp.status}`
                : `HTTP ${resp.status}`;
            return { data: null, error: message, status: resp.status };
        }
        return { data: data as T | null, error: null, status: resp.status };
    } catch (err) {
        return { data: null, error: err instanceof Error ? err.message : 'Network error', status: 0 };
    }
}

export const api = {
    /**
     * Log in via PocketBase, then exchange the PB token for a FastAPI JWT.
     */
    login: async (email: string, password: string): Promise<ApiResponse<AuthResponse>> => {
        const pbResult = await pbFetch<{ token: string }>('/api/collections/users/auth-with-password', {
            method: 'POST',
            body: JSON.stringify({ identity: email, password }),
        });
        if (pbResult.error || !pbResult.data) {
            return { data: null, error: pbResult.error || 'Login failed', status: pbResult.status };
        }
        return apiClient.post('/api/auth/exchange', { pb_token: pbResult.data.token });
    },

    /**
     * Change the current user's password and clear the forced reset flag.
     */
    changePassword: async (oldPassword: string, newPassword: string): Promise<ApiResponse<{ token: string; email: string }>> => {
        return apiClient.post('/api/auth/change-password', {
            old_password: oldPassword,
            new_password: newPassword,
        });
    },

    /**
     * Request a password-reset email from PocketBase.
     */
    requestPasswordReset: async (email: string): Promise<ApiResponse<unknown>> => {
        return pbFetch('/api/collections/users/request-password-reset', {
            method: 'POST',
            body: JSON.stringify({ email }),
        });
    },

    /**
     * Process an email
     * 
     * Development: http://localhost:3000/api/process-email
     * Production: https://api.example.com/api/process-email
     */
    process: async (
        request: ProcessEmailRequest
    ): Promise<ApiResponse<Message[]>> => {
        return apiClient.post<Message[]>('/api/process', request);
    },

    getMe: async (): Promise<ApiResponse<MeResponse>> => {
        return apiClient.get<MeResponse>('/api/admin/me');
    },

    /**
     * Health check endpoint
     */
    healthCheck: async (): Promise<ApiResponse<{ status: string; timestamp: string }>> => {
        return apiClient.get('/api/health');
    },

    /**
     * Get a specific chat by ID
     * Returns the original email and message history
     */
    getChat: async (
        id: string,
        projectId?: string | null,
    ): Promise<ApiResponse<{ messages: Message[]; members: string[]; creator: string; activatedIntent?: string | null }>> => {
        const query = projectId ? `?projectId=${pathParam(projectId)}` : '';
        return apiClient.get(`/api/chat/${pathParam(id)}${query}`);
    },

    getIssueByChat: async (
        projectId: string,
        chatId: string,
    ): Promise<ApiResponse<SupportIssueSummary>> => {
        return apiClient.get(`/api/admin/projects/${pathParam(projectId)}/issues/by-chat/${pathParam(chatId)}`);
    },

    updateIssue: async (
        projectId: string,
        issueId: string,
        data: { assigneeEmail?: string; status?: string; workflowSource?: string },
    ): Promise<ApiResponse<SupportIssueSummary>> => {
        return apiClient.patch(`/api/admin/projects/${pathParam(projectId)}/issues/${pathParam(issueId)}`, data);
    },

    bulkApproveIssueReplies: async (
        projectId: string,
        issueIds: string[],
    ): Promise<ApiResponse<SupportBulkApproveSendResult>> => {
        return apiClient.post(`/api/admin/projects/${pathParam(projectId)}/issues/replies/bulk-approve`, { issueIds });
    },

    bulkApproveSendIssueReplies: async (
        projectId: string,
        issueIds: string[],
    ): Promise<ApiResponse<SupportBulkApproveSendResult>> => {
        return apiClient.post(`/api/admin/projects/${pathParam(projectId)}/issues/replies/bulk-approve-send`, { issueIds });
    },

    bulkRetryFailedIssueReplies: async (
        projectId: string,
        issueIds: string[],
    ): Promise<ApiResponse<SupportBulkApproveSendResult>> => {
        return apiClient.post(`/api/admin/projects/${pathParam(projectId)}/issues/replies/bulk-retry-failed`, { issueIds });
    },

    bulkRequestIssueReplyChanges: async (
        projectId: string,
        issueIds: string[],
        note = '',
    ): Promise<ApiResponse<SupportBulkApproveSendResult>> => {
        return apiClient.post(`/api/admin/projects/${pathParam(projectId)}/issues/replies/bulk-changes`, { issueIds, note });
    },

    createIssueReply: async (
        projectId: string,
        issueId: string,
        body: string,
        status = 'draft',
        approvalRequired = false,
        includeFeedbackLink = false,
        attachments?: Array<Record<string, unknown>>,
    ): Promise<ApiResponse<SupportOutboundMessage>> => {
        return apiClient.post(`/api/admin/projects/${pathParam(projectId)}/issues/${pathParam(issueId)}/replies`, {
            body,
            status,
            approvalRequired,
            includeFeedbackLink,
            attachments,
        });
    },

    /**
     * Submit structured like/dislike feedback on a pipeline result
     */
    submitFeedback: async (
        projectId: string,
        chatId: string,
        user: string,
        rating: 'like' | 'dislike',
        affectedStages?: string[],
        feedbackText?: string,
    ): Promise<ApiResponse<{ status: string; id: string }>> => {
        return apiClient.post('/api/feedback', {
            projectId,
            chatId,
            user,
            rating,
            affectedStages: affectedStages ?? [],
            feedbackText: feedbackText ?? '',
        });
    },

    /**
     * Process an email against DRAFT config (preview mode).
     * Called from the embed route when the admin preview sends draft: true.
     */
    previewProcess: async (
        projectId: string,
        request: ProcessEmailRequest
    ): Promise<ApiResponse<Message[]>> => {
        return apiClient.post<Message[]>(`/api/admin/projects/${projectId}/preview`, request);
    },

    // ── Admin ────────────────────────────────────────────────────────────────

    /**
     * Trigger an intent action webhook via the backend proxy.
     * Keeps webhook URLs server-side; the browser never sees them.
     */
    triggerAction: async (
        projectId: string,
        webhook: string,
        method: string,
        payload: Record<string, unknown>,
        headers: Record<string, string> = {},
        query: Record<string, unknown> = {},
        body: Record<string, unknown> = {},
    ): Promise<ApiResponse<unknown>> => {
        if (!projectId) {
            return { data: null, error: 'No project selected for action.', status: 0 };
        }
        return apiClient.post(`/api/admin/projects/${pathParam(projectId)}/actions/trigger`, {
            webhook, method, payload, headers, query, body,
        });
    },


};

// Export for easy access
export default api;
