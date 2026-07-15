import { apiClient } from './client';
import type { ApiResponse } from './client';
import { settings } from '@/settings';
import type { Locale } from '@/lib/i18n-core';

export interface AuthResponse {
    token: string;
    email: string;
    language: Locale;
    tenantId: string;
    tenantName: string;
    isRoot: boolean;
    isPlatformAdmin: boolean;
    tenantAccountType: 'normal' | 'demo';
    capabilities: AccountCapabilities;
    mustChangePassword: boolean;
}

export interface AccountCapabilities {
    canManageOrgSettings: boolean;
    canManageMembers: boolean;
    canDownloadManifest: boolean;
    canManageBilling: boolean;
    canManageTenantSecrets: boolean;
    canManageProjectSecrets: boolean;
    canManageProjectSettings: boolean;
    canEditProjectConfig: boolean;
    canEditIntents: boolean;
    canPublish: boolean;
    canUsePlatformLlm: boolean;
    canAccessDemoEndpoints: boolean;
}

export const DEFAULT_ACCOUNT_CAPABILITIES: AccountCapabilities = {
    canManageOrgSettings: true,
    canManageMembers: true,
    canDownloadManifest: true,
    canManageBilling: true,
    canManageTenantSecrets: true,
    canManageProjectSecrets: true,
    canManageProjectSettings: true,
    canEditProjectConfig: true,
    canEditIntents: true,
    canPublish: true,
    canUsePlatformLlm: false,
    canAccessDemoEndpoints: false,
};

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isIntentFileUpload(value: unknown): value is { filename: string; size: number } {
    return (
        isRecord(value)
        && typeof value.filename === 'string'
        && typeof value.size === 'number'
    );
}

export interface IntentFileInfo {
    filename: string;
    size: number;
    contentType: string;
}

export type IntentLearningProposalStatus =
    | 'proposed'
    | 'evaluating'
    | 'evaluated'
    | 'eval_failed'
    | 'published'
    | 'rejected';

export type IntentLearningProposalOperation = 'create' | 'update' | 'delete';

export interface IntentLearningProposalEvalSummary {
    passed?: boolean;
    failed?: number;
    total?: number;
    completed?: number;
    overallScore?: number | null;
    minimumScore?: number;
    affectedDimension?: string;
    affectedScore?: number | null;
    affectedCoveragePassed?: boolean;
}

export interface IntentLearningProposal {
    id: string;
    status: IntentLearningProposalStatus;
    operation: IntentLearningProposalOperation;
    proposed_learning: string;
    before_learning: string;
    target_learning_id: string;
    affected_stages: string[];
    source_feedback_id: string;
    eval_set_id: string;
    eval_run_id: string;
    eval_summary: IntentLearningProposalEvalSummary | null;
    minimum_score: number;
    error: string;
    rejection_reason: string;
    created: string;
    updated: string;
}

export interface IntentLearningProposalInput {
    operation: IntentLearningProposalOperation;
    proposedLearning?: string;
    targetLearningId?: string;
    sourceFeedbackId?: string;
    affectedStages?: string[];
}

export interface TenantUser {
    id: string;
    email: string;
    name: string;
    language: Locale;
    isRoot: boolean;
    mustChangePassword: boolean;
    passwordLoginEnabled: boolean;
    defaultProject: string | null;
    created: string;
}

export interface CurrentUserProfile {
    id: string;
    email: string;
    name: string;
    language: Locale;
    defaultProject: string | null;
    projects: Project[];
    branding?: {
        primaryColor?: string;
    };
}

export interface Project {
    id: string;
    name: string;
    description: string;
    tenant: string;
    created: string;
    /** Role of the current user on this project (absent for root users). */
    role?: 'admin' | 'editor' | 'viewer';
}

export interface ProjectMember {
    id: string;
    userId: string;
    email: string;
    isRoot: boolean;
    role: 'admin' | 'editor' | 'viewer';
    projectId: string;
    created: string;
}

export interface InputSchemaField {
    key: string;
    description: string;
    type: 'string' | 'number' | 'integer' | 'boolean';
    default?: string;
    required: boolean;
}

export interface ToolConfig {
    name: string;
    description: string;
    method: string;
    urlTemplate: string;
    headers: Record<string, string>;
    body: Record<string, string>;
    envVars: string[];
    inputSchema?: InputSchemaField[];
}

export interface AdminConfigData {
    orgName: string;
    orgDescription: string;
    useCustomOrg: boolean;
    llmModel: string;
    llmProvider: 'gemini' | 'custom';
    llmApiKey: string;
    llmCustomBaseUrl: string;
    llmCustomModel: string;
    useCustomLlm: boolean;
    identityNotes: string;
    tool: ToolConfig | null;
    useCustomSecurity: boolean;
    phishingMonitoringEnabled: boolean;
    promptInjectionMonitoringEnabled: boolean;
}

export type TenantLlmProvider = 'managed' | 'gemini' | 'custom';

// ── PocketBase direct calls (browser → PocketBase, no FastAPI) ─────────────

/**
 * Low-level fetch wrapper for PocketBase API calls.
 * PocketBase runs on a different port (:8090) so we can't use the apiClient.
 */
async function pbFetch<T>(
    path: string,
    options: RequestInit = {},
): Promise<ApiResponse<T>> {
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

/**
 * Full login flow:
 * Password auth is only allowed for accounts that explicitly enable it.
 */
export async function login(
    email: string,
    password: string,
): Promise<ApiResponse<AuthResponse>> {
    return apiClient.post('/api/auth/password-login', { email, password });
}

export async function getLoginMethod(email: string): Promise<ApiResponse<{ method: 'code' | 'password' }>> {
    return apiClient.post('/api/auth/login-method', { email });
}

export async function requestLoginCode(email: string): Promise<ApiResponse<{ status: string }>> {
    return apiClient.post('/api/auth/request-login-code', { email });
}

export async function verifyLoginCode(email: string, code: string): Promise<ApiResponse<AuthResponse>> {
    return apiClient.post('/api/auth/verify-login-code', { email, code });
}

/**
 * Self-service signup (SaaS mode only).
 * Creates a tenant + first admin user and sends a verification email.
 */
export interface SignupResponse {
    verificationRequired: boolean;
    email: string;
    message: string;
}

export async function signup(
    companyName: string,
    email: string,
    password: string,
): Promise<ApiResponse<SignupResponse>> {
    return apiClient.post('/api/auth/signup', {
        companyName,
        email,
        password,
    });
}

/**
 * Change password via FastAPI (verifies old password, sets new one, clears mustChangePassword).
 */
export async function changePassword(
    oldPassword: string,
    newPassword: string,
): Promise<ApiResponse<{ token: string; email: string }>> {
    return apiClient.post('/api/auth/change-password', {
        old_password: oldPassword,
        new_password: newPassword,
    });
}

/**
 * Request a password-reset email from PocketBase.
 * PocketBase handles the email and reset flow entirely.
 */
export async function requestPasswordReset(email: string): Promise<ApiResponse<unknown>> {
    return pbFetch('/api/collections/users/request-password-reset', {
        method: 'POST',
        body: JSON.stringify({ email }),
    });
}

/**
 * Confirm email verification with the token from the verification email.
 * Called by the VerifyEmail route after the user clicks the link.
 */
export async function confirmVerification(token: string): Promise<ApiResponse<unknown>> {
    return apiClient.post('/api/auth/verify-email', { token });
}

/**
 * Public auth config — no authentication required.
 * Used by the login page to decide whether to show signup link.
 */
export interface AuthConfig {
    isSaas: boolean;
    allowSignups: boolean;
}

export async function getAuthConfig(): Promise<ApiResponse<AuthConfig>> {
    return apiClient.get('/api/auth/config');
}

/** Notify PublishButton that the draft has changed. */
function notifyDraftChanged() {
    window.dispatchEvent(new Event('admin:draft-changed'));
}

// ── Evaluation types ──────────────────────────────────────────────────────────

export interface EvalSet {
    id: string;
    name: string;
    description: string;
    caseCount: number;
    lastRunScore: number | null;
    lastRunAt: string | null;
    created: string;
}

export interface EvalCase {
    id: string;
    name: string;
    emailSubject: string;
    emailFrom: string;
    emailBody: string;
    emailAttachments: EvalEmailAttachment[] | null;
    expectedCustomerFound: boolean;
    expectedCustomerData: Record<string, unknown> | null;
    expectedIntentMatched: boolean;
    expectedIntentName: string;
    expectedActions: unknown[] | null;
    expectedRequiresHuman: boolean;
    expectedResponse: string;
    created: string;
}

export interface EvalEmailAttachment {
    filename: string;
    base64: string;
}

export interface EvalCaseInput {
    name: string;
    email_subject: string;
    email_from: string;
    email_body: string;
    email_attachments?: EvalEmailAttachment[];
    expected_customer_found?: boolean;
    expected_customer_data?: Record<string, unknown>;
    expected_intent_matched?: boolean;
    expected_intent_name?: string;
    expected_actions?: unknown[];
    expected_requires_human?: boolean;
    expected_response?: string;
}

export interface EvalRun {
    id: string;
    status: string;
    startedAt: string | null;
    completedAt: string | null;
    summary: EvalRunSummary | null;
    created: string;
}

export interface EvalRunSummary {
    overallScore: number | null;
    identityScore: number | null;
    intentScore: number | null;
    actionsScore: number | null;
    responseScore: number | null;
    totalCases: number;
    completedCases: number;
    failedCases: number;
}

export interface EvalResult {
    id: string;
    evalCase: string;
    status: string;
    pipelineOutput: Record<string, unknown> | null;
    identityScore: number | null;
    identityReasoning: string;
    intentScore: number | null;
    intentReasoning: string;
    actionsScore: number | null;
    actionsReasoning: string;
    responseScore: number | null;
    responseReasoning: string;
    overallScore: number | null;
    error: string;
}

export interface EvalRunDetail extends EvalRun {
    evalSet: string;
    results: EvalResult[];
}

export interface TenantSettings {
    supportEmail: string;
    feedbackEmail: string;
    orgName: string;
    orgDescription: string;
    addinPrimaryColor: string;
    llmProvider: TenantLlmProvider;
    llmModel: string;
    llmApiKey: string;
    llmCustomBaseUrl: string;
    llmCustomModel: string;
    phishingMonitoringEnabled: boolean;
    promptInjectionMonitoringEnabled: boolean;
    allowSignups: boolean;
}

// ── Helper: project-scoped URL prefix ─────────────────────────────────────────

function p(projectId: string): string {
    return `/api/admin/projects/${projectId}`;
}

// ── License status (on-prem) ──────────────────────────────────────────────────

export interface LicenseStatus {
    required: boolean;
    valid?: boolean;
    message?: string;
    expiresAt?: string | null;
    maxUsers?: number | null;
    currentUsers?: number;
    lastCheck?: number;
    withinGracePeriod?: boolean;
}

// ── Billing types ─────────────────────────────────────────────────────────────

export interface BillingStatus {
    plan: 'free' | 'pro' | 'business' | 'enterprise';
    subscriptionStatus: 'none' | 'active' | 'past_due' | 'canceled';
    cancelAtPeriodEnd: boolean;
    currentPeriodStart: string;
    currentPeriodEnd: string;
    usage: {
        emailsThisPeriod: number;
        projects: number;
        users: number;
        evalRunsThisPeriod: number;
        evalSets: number;
    };
    llmUsage: {
        eventCount: number;
        managedEventCount: number;
        reportedEventCount: number;
        rawCostUsdMicros: number;
        billedCostUsdMicros: number;
        rawCostUsd: number;
        billedCostUsd: number;
    };
    syncedAddons: Record<string, number>;
    retention?: Record<string, number>;
    limits: {
        emailsPerMonth: number;
        projects: number;
        users: number;
        evalRunsPerMonth: number;
        evalSets: number;
        evalCasesPerSet: number;
        retentionDays: number;
    };
    features: {
        feedback_learnings: boolean;
        security_monitoring: boolean;
        byok_llm: boolean;
        custom_llm_gateway: boolean;
    };
}

export interface MonitorSummary {
    hasRuns: boolean;
    totalRuns: number;
    requestsToday: number;
    failures: number;
    avgDurationMs: number;
    p95DurationMs: number;
    needsHuman: number;
    actionsTriggered: number;
}

export interface MonitorRun {
    id: string;
    source: string;
    status: string;
    startedAt: string;
    completedAt: string;
    durationMs: number;
    userEmail: string;
    input: Record<string, unknown>;
    output: Record<string, unknown>;
    actions: Array<Record<string, unknown>>;
    feedback?: Record<string, unknown>;
    error: string;
    created: string;
}

export type SupportIssueStatus = 'open' | 'ongoing' | 'done' | 'pending' | 'triaged' | 'closed';
export type SupportIssuePriority = 'low' | 'normal' | 'high' | 'urgent';

export interface SupportIssueActionLog {
    label: string;
    type: string;
    status: string;
}

export interface SupportIssueMessage {
    id?: string;
    sourceMessageId?: string;
    direction?: string;
    sender?: string;
    body?: string;
    messageKind?: string;
    attachments?: unknown[];
    metadata?: Record<string, unknown>;
    occurredAt?: string;
    role?: string;
    user?: string;
    content?: unknown;
}

export interface SupportInternalNote {
    id: string;
    issueId: string;
    authorEmail: string;
    body: string;
    visibility: string;
    metadata: Record<string, unknown>;
    created: string;
    updated: string;
}

export interface SupportAgentMessage {
    id: string;
    issueId: string;
    runId: string;
    replyId: string;
    role: string;
    authorEmail: string;
    body: string;
    metadata: Record<string, unknown>;
    occurredAt: string;
    created: string;
    updated: string;
}

export interface SupportSlaEvent {
    id: string;
    issueId: string;
    eventType: string;
    status: string;
    targetAt: string;
    occurredAt: string;
    metadata: Record<string, unknown>;
    created: string;
    updated: string;
}

export interface SupportSlaPolicy {
    id: string;
    name: string;
    active: boolean;
    firstResponseMinutes: number;
    resolutionMinutes: number;
    businessHours: Record<string, unknown>;
    metadata: Record<string, unknown>;
    created: string;
    updated: string;
}

export type SupportCustomFieldType = 'text' | 'number' | 'select' | 'boolean' | 'date' | 'url';

export interface SupportCustomFieldDefinition {
    key: string;
    label: string;
    type: SupportCustomFieldType;
    required: boolean;
    options: string[];
}

export interface SupportPortalSession {
    id: string;
    issueId: string;
    status: string;
    expiresAt: string;
    lastAccessedAt: string;
    createdBy: string;
    metadata: Record<string, unknown>;
    created: string;
    updated: string;
    url?: string;
    apiUrl?: string;
}

export interface SupportAssignment {
    id: string;
    issueId: string;
    assigneeEmail: string;
    assignedBy: string;
    status: string;
    created: string;
    updated: string;
}

export interface SupportNotification {
    id: string;
    issueId: string;
    recipientEmail: string;
    type: string;
    title: string;
    body: string;
    status: string;
    metadata: Record<string, unknown>;
    created: string;
    updated: string;
    readAt: string;
}

export interface SupportWatcher {
    id: string;
    issueId: string;
    watcherEmail: string;
    addedBy: string;
    source: string;
    status: string;
    metadata: Record<string, unknown>;
    created: string;
    updated: string;
}

export interface SupportOutboundMessage {
    id: string;
    issueId: string;
    channel: string;
    toAddress: string;
    fromAddress: string;
    subject: string;
    body: string;
    status: string;
    provider: string;
    providerMessageId: string;
    error: string;
    createdBy: string;
    sentAt: string;
    metadata: Record<string, unknown>;
    attachments?: unknown[];
    created: string;
    updated: string;
}

export interface SupportAgentAnswer {
    answer: string;
    confidence: string;
    citations: KnowledgeArticle[];
    reply: SupportOutboundMessage | null;
    run?: SupportAiRun;
    userMessage?: SupportAgentMessage;
    assistantMessage?: SupportAgentMessage;
    agentMessages?: SupportAgentMessage[];
    approvalRequired: boolean;
    priorAgentRunIds?: string[];
    includeFeedbackLink?: boolean;
    generationMode?: string;
    generationError?: string;
    knowledgeAgent?: boolean;
    missingInformation?: string[];
    knowledgeToolCalls?: Array<Record<string, unknown>>;
    groundingVerified?: boolean;
    groundingIssues?: string[];
    groundingError?: string;
    groundingGate?: Record<string, unknown>;
    knowledgeGap?: KnowledgeGap | null;
    accountContext?: Record<string, unknown>;
    conversationContext?: SupportIssueConversation;
    automationContext?: Record<string, unknown>;
    revisionContext?: Record<string, unknown>;
    autoSend?: boolean;
    autoSendRequested?: boolean;
    autoSendPolicy?: string;
    autoSendBlockedReason?: string;
}

export interface SupportIssueWorkspaceNextAction {
    kind: string;
    phase: string;
    priority: number;
    title: string;
    detail: string;
    actions: string[];
}

export interface SupportIssueTicketProofCheck {
    key: string;
    label: string;
    ready: boolean;
    detail: string;
    action: string;
}

export interface SupportIssueTicketProof {
    kind: 'support_ticket_operating_proof';
    ready: boolean;
    summary: {
        totalChecks: number;
        readyChecks: number;
        blockedChecks: number;
        blockedKeys: string[];
    };
    checks: SupportIssueTicketProofCheck[];
}

export interface SupportIssueAnswerWorkspace {
    kind: 'support_issue_answer_workspace';
    issueId: string;
    status: 'open' | 'ongoing' | 'done';
    nextAction: SupportIssueWorkspaceNextAction;
    agent: {
        runCount: number;
        messageCount?: number;
        latestMessageId?: string;
        latestAssistantMessageId?: string;
        latestMessagePreview?: string;
        latestRunId: string;
        latestQuestion: string;
        latestAnswerPreview: string;
        confidence: string;
        citationCount: number;
        hasDraft: boolean;
    };
    knowledge: {
        suggestionCount: number;
        openGapCount: number;
        topSuggestionIds: string[];
        topGapId: string;
        covered: boolean;
    };
    reply: {
        draftCount: number;
        queuedCount: number;
        sentCount: number;
        failedCount: number;
        latestReplyId: string;
    };
    humanLoop: {
        pendingApprovalCount: number;
        pendingReplyApprovalCount: number;
        pendingActionApprovalCount: number;
        pendingActionCount: number;
        requiresReview: boolean;
    };
    channel: {
        channel: string;
        source: string;
        canAnswerFromApp: boolean;
    };
    replyReadiness: {
        ready: boolean;
        status: string;
        transport: string;
        provider: string;
        channelKey: string;
        target: Record<string, string>;
        adapter?: {
            channel: string;
            selectedTransport: string;
            selectedProvider: string;
            supportedTransports: string[];
            nativeProvider: boolean;
            webhookAdapter: boolean;
            internal: boolean;
            requiresChannelConfig: boolean;
            channelConfigured: boolean;
            requiresRuntimeSecrets: boolean;
            requiredEnvVars: string[];
            missingEnvVars: string[];
            targetKey: string;
            targetLabel: string;
        };
        blockers: string[];
        missingEnvVars: string[];
    };
    ticketProof: SupportIssueTicketProof;
}

export interface SupportFieldPreparation {
    customFields: Record<string, unknown>;
    confidence: string;
    rationale: string;
    generationMode: string;
    generationError: string;
    actionExecution: SupportActionExecution | null;
    run?: SupportAiRun;
    approvalRequired: boolean;
    automationContext?: Record<string, unknown>;
    issue?: SupportIssue | null;
}

export interface SupportTriagePreparation {
    triage: Record<string, unknown>;
    confidence: string;
    rationale: string;
    generationMode: string;
    generationError: string;
    actionExecution: SupportActionExecution | null;
    run?: SupportAiRun;
    approvalRequired: boolean;
    automationContext?: Record<string, unknown>;
    issue?: SupportIssue | null;
}

export interface SupportAiRun {
    id: string;
    issueId: string;
    runKey: string;
    source: string;
    status: string;
    activatedIntent: string;
    requiresHuman: boolean;
    summary: string;
    identityResult: Record<string, unknown>;
    intentResult: Record<string, unknown>;
    securityResult: Record<string, unknown>;
    tokenUsage: Record<string, unknown>;
    toolCalls: Array<Record<string, unknown>>;
    metadata: Record<string, unknown>;
    startedAt: string;
    completedAt: string;
    created: string;
    updated: string;
}

export interface SupportActionExecution {
    id: string;
    issueId: string;
    actionKey: string;
    label: string;
    type: string;
    status: string;
    requestedBy: string;
    result: Record<string, unknown>;
    error: string;
    metadata: Record<string, unknown>;
    startedAt: string;
    completedAt: string;
    created: string;
    updated: string;
}

export interface SupportActionApprovalResult {
    execution: SupportActionExecution;
    issue: SupportIssue | null;
}

export interface SupportBulkActionApprovalResult {
    processed: number;
    approved?: number;
    rejected?: number;
    failed: Array<{ id: string; executionId?: string; error: string }>;
    items: Array<{
        issueId: string;
        executionId: string;
        status: string;
        error: string;
        execution: SupportActionExecution;
    }>;
    issues: SupportIssue[];
}

export interface SupportIssueActivityEvent {
    id: string;
    issueId: string;
    eventType: string;
    actorEmail: string;
    title: string;
    body: string;
    fromStatus: string;
    toStatus: string;
    fromPriority: string;
    toPriority: string;
    metadata: Record<string, unknown>;
    occurredAt: string;
    created: string;
    updated: string;
}

export interface SupportCsatFeedback {
    id: string;
    issueId: string;
    portalSessionId: string;
    rating: number;
    comment: string;
    customerEmail: string;
    customerName: string;
    source: string;
    metadata: Record<string, unknown>;
    receivedAt: string;
    created: string;
    updated: string;
}

export interface SupportIssueConversationTicket {
    id: string;
    sourceEmailId: string;
    subject: string;
    status: SupportIssueStatus;
    priority: SupportIssuePriority;
    assigneeEmail: string;
    queueName: string;
    channel: string;
    source: string;
    latestMessageAt: string;
    messageCount: number;
    needsResponse: boolean;
    pendingApprovalCount: number;
}

export interface SupportIssueConversationMessage {
    id: string;
    issueId: string;
    sourceMessageId: string;
    direction: string;
    sender: string;
    body: string;
    messageKind: string;
    occurredAt: string;
    ticketSubject: string;
}

export interface SupportIssueConversation {
    key: string;
    label: string;
    source: string;
    channel: string;
    currentIssueId: string;
    issueCount: number;
    messageCount: number;
    openCount: number;
    ongoingCount: number;
    doneCount: number;
    latestMessageAt: string;
    ticketIds: string[];
    tickets: SupportIssueConversationTicket[];
    messages: SupportIssueConversationMessage[];
    threadId?: string;
    conversationId?: string;
    webChatSessionId?: string;
    externalConversationKey?: string;
    externalThreadKey?: string;
}

export interface SupportIssueTicketState {
    kind: 'support_ticket_list_state';
    label: string;
    detail: string;
    nextActionKind: string;
    nextActionPhase: string;
    agentPrepared: boolean;
    humanLoopRequired: boolean;
    knowledgeCovered: boolean;
    canClose: boolean;
    channelLifecycle?: {
        kind: 'support_ticket_channel_lifecycle';
        label: string;
        detail: string;
        channel: string;
        source: string;
        provider: string;
        channelKey: string;
        ticketMode: string;
        resolverAction: string;
        inboundLinked: boolean;
        replyTargeted: boolean;
        ready: boolean;
        blockedKeys: string[];
        sourceProof: {
            sourceIssueId: string;
            sourceMessageId: string;
            externalTicketKey: string;
            externalMessageKey: string;
        };
        replyTarget: {
            key: string;
            label: string;
            channelKey: string;
        };
    };
    counts: {
        agentRuns: number;
        replyDrafts: number;
        queuedReplies: number;
        sentReplies: number;
        failedReplies: number;
        pendingApprovals: number;
        pendingActions: number;
        openKnowledgeGaps: number;
    };
}

export interface SupportIssue {
    id: string;
    accountId: string;
    contactId: string;
    sourceEmailId: string;
    chatRecordId: string;
    chatId: string;
    status: SupportIssueStatus;
    workflowStatus?: 'open' | 'ongoing' | 'done';
    priority: SupportIssuePriority;
    assigneeEmail: string;
    queueKey: string;
    queueName: string;
    tags: string[];
    accountName: string;
    accountDomain: string;
    contactEmail: string;
    contactName: string;
    subject: string;
    fromAddress: string;
    channel: string;
    source: string;
    aiSummary: string;
    activatedIntent: string;
    requiresHuman: boolean;
    pendingApprovalCount: number;
    hasPendingApproval: boolean;
    pendingReplyApprovalCount: number;
    hasPendingReplyApproval: boolean;
    pendingActionApprovalCount: number;
    hasPendingActionApproval: boolean;
    failedDeliveryCount: number;
    hasFailedDelivery: boolean;
    pendingDeliveryCount: number;
    hasPendingDelivery: boolean;
    csatFeedbackCount: number;
    lowCsatFeedbackCount: number;
    hasLowCsatFeedback: boolean;
    latestCsatRating: number;
    latestCsatComment: string;
    latestCsatReceivedAt: string;
    overdueSlaCount: number;
    hasOverdueSla: boolean;
    nextSlaTargetAt: string;
    nextSlaEventType: string;
    needsResponse: boolean;
    latestMessageDirection: string;
    latestCustomerMessageAt: string;
    latestAgentMessageAt: string;
    duplicateSuggestionCount: number;
    topDuplicateScore: number;
    topDuplicateIssueId: string;
    topDuplicateIssueSubject: string;
    duplicateReasons: string[];
    aiRunCount?: number;
    agentRunCount?: number;
    latestAgentRunId?: string;
    draftReplyCount?: number;
    queuedReplyCount?: number;
    sentReplyCount?: number;
    failedReplyCount?: number;
    openKnowledgeGapCount?: number;
    topKnowledgeGapId?: string;
    messageCount: number;
    actionLog: SupportIssueActionLog[];
    metadata: Record<string, unknown>;
    customFields: Record<string, unknown>;
    latestMessageAt: string;
    mergedIntoIssueId: string;
    mergedAt: string;
    mergedBy: string;
    mergeNote: string;
    created: string;
    updated: string;
    messages?: SupportIssueMessage[];
    draftReply?: string;
    notes?: SupportInternalNote[];
    slaEvents?: SupportSlaEvent[];
    portalSessions?: SupportPortalSession[];
    assignmentHistory?: SupportAssignment[];
    watchers?: SupportWatcher[];
    outboundMessages?: SupportOutboundMessage[];
    aiRuns?: SupportAiRun[];
    agentMessages?: SupportAgentMessage[];
    actionExecutions?: SupportActionExecution[];
    activityEvents?: SupportIssueActivityEvent[];
    channelWebhookEvents?: SupportChannelWebhookEvent[];
    csatFeedback?: SupportCsatFeedback[];
    knowledgeGaps?: KnowledgeGap[];
    knowledgeSuggestions?: KnowledgeArticle[];
    conversation?: SupportIssueConversation;
    ticketState?: SupportIssueTicketState;
}

export interface SupportIssueBoardAttention {
    unassigned: number;
    needsResponse: number;
    approvals: number;
    failedDelivery: number;
    overdueSla: number;
    closeBlocked: number;
    attentionCount: number;
}

export interface SupportIssueBoardBreakdownItem {
    key: string;
    label: string;
    count: number;
}

export interface SupportIssueBoardAction {
    kind: string;
    label: string;
    detail: string;
    phase: string;
    lane: string;
    statusFilter: string;
    count: number;
    issueCount: number;
    attentionCount: number;
    blocked: boolean;
}

export interface SupportIssueWorkflowLanePolicy {
    status: 'open' | 'ongoing' | 'done';
    label: string;
    description: string;
    allowedTransitions: Array<'open' | 'ongoing' | 'done'>;
    entryRequirements: string[];
    requiresAssignee: boolean;
    doneGate: boolean;
}

export interface SupportIssueWorkflowPolicy {
    kind: 'support_ticket_workflow_policy';
    version: number;
    lanes: SupportIssueWorkflowLanePolicy[];
    laneOrder: Array<'open' | 'ongoing' | 'done'>;
    assigneeRequiredStatuses: Array<'open' | 'ongoing' | 'done'>;
    doneRequiresNoBlockers: boolean;
    doneBlockers: string[];
    dragDropEnabled: boolean;
    bulkMoveEnabled: boolean;
    claimOnDropStatuses: Array<'open' | 'ongoing' | 'done'>;
}

export interface SupportIssueBoardLane {
    status: 'open' | 'ongoing' | 'done';
    label: string;
    policy?: SupportIssueWorkflowLanePolicy;
    count: number;
    attention: SupportIssueBoardAttention;
    assigneeBreakdown: SupportIssueBoardBreakdownItem[];
    priorityBreakdown: SupportIssueBoardBreakdownItem[];
    channelBreakdown: SupportIssueBoardBreakdownItem[];
    operatingAction?: SupportIssueBoardAction;
    issues: SupportIssue[];
}

export interface SupportIssueBoard {
    kind: 'support_issue_kanban_board';
    status: string;
    queueKey: string;
    accountKey?: string;
    channel?: string;
    assigneeEmail?: string;
    tag?: string;
    query?: string;
    limit: number;
    total: number;
    attention: SupportIssueBoardAttention;
    nextAction?: SupportIssueBoardAction;
    workflow?: SupportIssueWorkflowPolicy;
    lanes: SupportIssueBoardLane[];
}

export interface SupportIssueListFilters {
    accountKey?: string;
    channel?: string;
    assigneeEmail?: string;
    tag?: string;
    query?: string;
}

export interface SupportIssueDuplicateSuggestion {
    issue: SupportIssue;
    score: number;
    reasons: string[];
}

export interface SupportQueue {
    id: string;
    queueKey: string;
    name: string;
    description: string;
    defaultAssigneeEmail: string;
    status: string;
    metadata: Record<string, unknown>;
    ownerWorkloads?: SupportQueueOwnerWorkload[];
    created: string;
    updated: string;
}

export interface SupportQueueOwnerWorkload {
    assigneeEmail: string;
    activeTickets: number;
    capacity: number;
    atCapacity: boolean;
    overBy: number;
}

export interface SupportInboxView {
    id: string;
    name: string;
    visibility: string;
    ownerEmail: string;
    filters: Record<string, unknown>;
    sortOrder: number;
    created: string;
    updated: string;
}

export interface SupportReplyMacro {
    id: string;
    title: string;
    body: string;
    visibility: string;
    ownerEmail: string;
    status: string;
    tags: string[];
    metadata: Record<string, unknown>;
    created: string;
    updated: string;
}

export interface SupportReplyMacroRender {
    macro: SupportReplyMacro;
    issueId: string;
    body: string;
    unresolvedVariables: string[];
}

export interface SupportContact {
    id: string;
    accountId: string;
    contactKey: string;
    email: string;
    name: string;
    externalId: string;
    metadata: Record<string, unknown>;
    issueCount: number;
    latestIssueAt: string;
    created: string;
    updated: string;
}

export interface SupportAccountInsight {
    id: string;
    accountId: string;
    sourceIssueId: string;
    insightKey: string;
    type: string;
    title: string;
    body: string;
    severity: string;
    status: string;
    metadata: Record<string, unknown>;
    firstSeenAt: string;
    lastSeenAt: string;
    created: string;
    updated: string;
}

export interface SupportAccountInsightSummary {
    total: number;
    unresolved: number;
    risks: number;
    openRisks: number;
    featureRequests: number;
    openFeatureRequests: number;
    summaries: number;
    lastInsightAt: string;
}

export interface SupportAccountHealthRollup {
    status: string;
    reason: string;
    nextAction: string;
    openIssues: number;
    urgentIssues: number;
    highPriorityIssues: number;
    openRisks: number;
    openFeatureRequests: number;
    unresolvedSignals: number;
    failedExternalSyncRuns: number;
    lastSignalAt: string;
}

export interface SupportAccountAction {
    score: number;
    kind: string;
    label: string;
    detail: string;
    route: string;
    reasonCodes: string[];
    openIssues?: number;
    urgentIssues?: number;
    highPriorityIssues?: number;
    openRisks?: number;
    openFeatureRequests?: number;
    failedExternalSyncRuns?: number;
    unresolvedSignals?: number;
    latestIssueAt?: string;
    lastSignalAt?: string;
    insightCount?: number;
    issueCount?: number;
    externalSyncRunCount?: number;
}

export interface SupportAccountActionQueueItem {
    accountId: string;
    accountKey: string;
    name: string;
    domain: string;
    healthStatus: string;
    nextAction: string;
    action: SupportAccountAction;
}

export interface SupportAccountActionPackage {
    account: SupportAccount;
    insight: SupportAccountInsight;
    action: SupportAccountAction;
    healthRollup: SupportAccountHealthRollup;
    relatedIssueIds: string[];
    relatedInsightIds: string[];
    failedExternalSyncRunIds: string[];
}

export interface SupportExternalObject {
    id: string;
    accountId: string;
    contactId: string;
    provider: string;
    objectType: string;
    externalId: string;
    externalUrl: string;
    displayName: string;
    raw: Record<string, unknown>;
    lastSeenAt: string;
    created: string;
    updated: string;
}

export interface SupportExternalSyncRun {
    id: string;
    accountId: string;
    sourceIssueId: string;
    provider: string;
    status: string;
    objectsSeen: number;
    error: string;
    result: Record<string, unknown>;
    startedAt: string;
    completedAt: string;
    created: string;
    updated: string;
}

export interface SupportAccount {
    id: string;
    accountKey: string;
    name: string;
    domain: string;
    externalId: string;
    healthStatus: string;
    metadata: Record<string, unknown>;
    issueCount: number;
    latestIssueAt: string;
    insightSummary?: SupportAccountInsightSummary;
    healthRollup?: SupportAccountHealthRollup;
    accountAction?: SupportAccountAction;
    created: string;
    updated: string;
    contacts?: SupportContact[];
    issues?: SupportIssue[];
    insights?: SupportAccountInsight[];
    externalObjects?: SupportExternalObject[];
    externalSyncRuns?: SupportExternalSyncRun[];
}

export interface SupportChannel {
    id: string;
    channelKey: string;
    type: string;
    name: string;
    status: string;
    config: Record<string, unknown>;
    lastSyncAt: string;
    created: string;
    updated: string;
    setup?: SupportChannelSetup;
}

export interface SupportChannelCursor {
    id: string;
    channelId: string;
    cursorKey: string;
    cursorValue: string;
    status: string;
    lastError: string;
    metadata: Record<string, unknown>;
    lastSyncedAt: string;
    created: string;
    updated: string;
}

export interface SupportChannelSetup {
    providerName?: string;
    inboundWebhookUrl: string;
    inboundWebhookPath: string;
    providerWebhookUrl?: string;
    providerWebhookPath?: string;
    smsWebhookUrl?: string;
    smsWebhookPath?: string;
    webChatUrl?: string;
    webChatEmbedScriptUrl?: string;
    webChatEmbedSnippet?: string;
    tokenHeader: string;
    tokenEnv: string;
    fallbackTokenEnv: string;
    providerTokenEnv?: string;
    providerSecretHeader?: string;
    providerSecretEnv?: string;
    providerSignatureConfigKey?: string;
    signatureEnv?: string;
    signatureHeader?: string;
    signatureConfigKey?: string;
    signatureRequired?: boolean;
    signatureTimestampHeader?: string;
    signatureTimestampRequired?: boolean;
    signatureToleranceSeconds?: number;
    ticketCreationMode?: string;
    ticketCreationConfigKey?: string;
    autoPrepareTriage?: boolean;
    autoPrepareCustomFields?: boolean;
    autoPrepareAgentReply?: boolean;
    autoPrepareAgentReplyOnUpdate?: boolean;
    agentAutoSend?: boolean;
    autoPrepareConfigKeys?: string[];
    outboundWebhookUrl?: string;
    outboundWebhookUrlEnv?: string;
    outboundWebhookUrlTemplate?: string;
    outboundWebhookTokenEnv?: string;
    outboundTokenRequired?: boolean;
    outboundWebhookConfigured?: boolean;
    outboundReady?: boolean;
    outboundTransport?: string;
    outboundBotTokenEnv?: string;
    outboundBotCredentialEnvVars?: string[];
    authConfigured?: boolean;
    inboundReady?: boolean;
    outboundConfigKeys: string[];
    health?: SupportChannelSetupHealth;
    envVars?: Array<{
        name: string;
        purpose: string;
        required: boolean;
        configured: boolean;
    }>;
    providerSteps?: string[];
    setupChecklist?: Array<{
        key: string;
        label: string;
        status: string;
        detail: string;
    }>;
    launch?: SupportChannelLaunch;
    launchChecklist?: SupportChannelLaunchCheck[];
    launchPlaybook?: SupportChannelLaunchPlaybookStep[];
    messagePayloadExample: Record<string, unknown>;
    receiptPayloadExample: Record<string, unknown>;
    installPackage?: Record<string, unknown>;
    slackManifest?: Record<string, unknown>;
    teamsBridgeConfig?: Record<string, unknown>;
    discordBridgeConfig?: Record<string, unknown>;
    metaBridgeConfig?: Record<string, unknown>;
    telegramWebhookConfig?: Record<string, unknown>;
    lineWebhookConfig?: Record<string, unknown>;
    viberWebhookConfig?: Record<string, unknown>;
    whatsappWebhookConfig?: Record<string, unknown>;
    messengerWebhookConfig?: Record<string, unknown>;
    instagramWebhookConfig?: Record<string, unknown>;
    twitterWebhookConfig?: Record<string, unknown>;
    twitterBridgeConfig?: Record<string, unknown>;
    twilioWebhookConfig?: Record<string, unknown>;
}

export interface SupportChannelActivationAdapterRow {
    surfaceType: string;
    surfaceLabel: string;
    configured: boolean;
    ready: boolean;
    channelId: string;
    channelKey: string;
    channelStatus: string;
    providerName: string;
    inbound: {
        adapter: string;
        ready: boolean;
        path: string;
    };
    outbound: {
        adapter: string;
        ready: boolean;
        target: string;
    };
    ticketing: {
        everyMessage: boolean;
        ownerRouting: boolean;
    };
    automation: {
        autoPrepareAgentReply: boolean;
        autoPrepareAgentReplyOnUpdate: boolean;
        humanReview: boolean;
    };
    requiredMissingEnvVars: string[];
    missingLiveTargets: string[];
    nextAction?: {
        phase: string;
        title: string;
        detail: string;
        action: string;
    } | null;
}

export interface SupportChannelProviderRunbook {
    kind: 'support_channel_provider_runbook';
    surfaceType: string;
    surfaceLabel: string;
    launchWave: string;
    initialProvider: boolean;
    channelId: string;
    channelKey: string;
    channelStatus: string;
    ready: boolean;
    phase: string;
    providerSteps: string[];
    secretEnvVars: Array<{
        name: string;
        purpose: string;
        required: boolean;
        configured: boolean;
    }>;
    requiredMissingEnvVars: string[];
    liveTargets: Array<Record<string, unknown>>;
    missingLiveTargets: string[];
    proofActions: Array<{
        key: string;
        label: string;
        status: string;
        detail: string;
        action: string;
        runId: string;
    }>;
    commands: Array<{
        key: string;
        label: string;
        command: string;
    }>;
    setupPackageKeys: string[];
    blockers: string[];
}

export interface SupportChannelActivationBacklog {
    kind: string;
    generatedAt: string;
    projectId: string;
    summary: {
        totalSurfaces: number;
        configuredSurfaces: number;
        activeSurfaces: number;
        readySurfaces: number;
        backlogSurfaces: number;
        missingSurfaces: number;
        requiredMissingEnvVars: string[];
        missingLiveTargets: string[];
        nextActionCount?: number;
        nextActionPhases?: Record<string, number>;
        adapterMatrixRows?: number;
        adapterMatrixReady?: number;
        adapterMatrixBlocked?: number;
        providerRunbookRows?: number;
        providerRunbookReady?: number;
        providerRunbookBlocked?: number;
        initialProviderRows?: number;
        initialProviderReady?: number;
        initialProviderBlocked?: number;
    };
    channels: Array<Record<string, unknown>>;
    surfaces: Array<Record<string, unknown>>;
    adapterMatrix?: SupportChannelActivationAdapterRow[];
    nextActions?: Array<{
        surfaceType: string;
        surfaceLabel: string;
        channelId: string;
        channelKey: string;
        phase: string;
        priority: number;
        title: string;
        detail: string;
        action: string;
        runAction?: string;
        command?: string;
        envVars?: string[];
        liveTargets?: string[];
    }>;
}

export interface SupportChannelActivationPlan {
    kind: string;
    generatedAt: string;
    projectId: string;
    source: string;
    summary: SupportChannelActivationBacklog['summary'];
    nextActions: NonNullable<SupportChannelActivationBacklog['nextActions']>;
    secrets: {
        missingEnvVars: string[];
        groups: Array<{
            surfaceLabel: string;
            surfaceType: string;
            envVars: string[];
        }>;
        template: string;
    };
    surfaces: Array<{
        surfaceType: string;
        surfaceLabel: string;
        channelKey: string;
        channelStatus: string;
        ready: boolean;
        blockers: string[];
        requiredMissingEnvVars: string[];
        missingLiveTargets: string[];
        nextActions: NonNullable<SupportChannelActivationBacklog['nextActions']>;
        ticketing: Record<string, unknown>;
        automation: Record<string, unknown>;
        inbound: Record<string, unknown>;
        outbound: Record<string, unknown>;
        liveTargets: unknown[];
        setupCommands: unknown[];
        setupPackage?: Record<string, unknown> | null;
        providerRunbook?: SupportChannelProviderRunbook | null;
    }>;
    adapterMatrix: SupportChannelActivationAdapterRow[];
}

export interface SupportChannelActivationBootstrapResult {
    created: number;
    skipped: Array<{
        surfaceType: string;
        surfaceLabel: string;
        reason: string;
    }>;
    items: SupportChannel[];
    bootstrapRuns: Array<{
        channelId: string;
        channelKey: string;
        surfaceType: string;
        runId: string;
        status: string;
        error: string;
    }>;
    activationBacklog: SupportChannelActivationBacklog;
}

export interface SupportChannelActivationReadyResult {
    activated: number;
    skipped: Array<{
        surfaceType: string;
        surfaceLabel: string;
        channelId: string;
        channelKey: string;
        reason: string;
    }>;
    items: SupportChannel[];
    activationRuns: Array<{
        channelId: string;
        channelKey: string;
        surfaceType: string;
        runId: string;
        status: string;
        error: string;
    }>;
    activationBacklog: SupportChannelActivationBacklog;
}

export interface SupportChannelLaunchPlaybookStep {
    key: string;
    label: string;
    status: string;
    detail: string;
    action: string;
    runAction: string;
    copyLabel: string;
    copyValue: string;
    smokeCommand?: string;
    targetUrl: string;
}

export interface SupportChannelLaunch {
    required: boolean;
    ready: boolean;
    checks: number;
    passed: number;
    missing: number;
    failed: number;
    lastCheckedAt: string;
    blockers: Array<{
        key: string;
        label: string;
        status: string;
        detail: string;
        action: string;
        runId: string;
    }>;
    checklist: SupportChannelLaunchCheck[];
}

export interface SupportChannelLaunchCheck {
    key: string;
    label: string;
    status: string;
    detail: string;
    action: string;
    runId: string;
    source: string;
    runStatus: string;
    processed: number;
    failed: number;
    sent?: number;
    transport: string;
    startedAt: string;
    completedAt: string;
    sessionId?: string;
    provider?: string;
    providerMessageId?: string;
    inboundProviderMessageId?: string;
    deliveryRoute?: Record<string, unknown>;
    providerResponse?: Record<string, unknown>;
    issueId?: string;
    replyId?: string;
    aiRunId?: string;
    approvedBy?: string;
    approvedAt?: string;
    approvalSource?: string;
    approvalEventId?: string;
}

export interface SupportChannelSetupHealth {
    status: string;
    ready: boolean;
    inboundReady: boolean;
    outboundReady: boolean;
    authConfigured: boolean;
    checks: number;
    missing: number;
    warnings: number;
    envConfigured: number;
    envTotal: number;
    envMissing: number;
    missingEnvVars: string[];
    requiredMissingEnvVars: string[];
}

export interface SupportChannelPreset {
    type: string;
    providerName: string;
    name: string;
    channelKey: string;
    ticketCreationMode: string;
    outboundPayloadMode: string;
    autoPrepareTriage?: boolean;
    autoPrepareCustomFields?: boolean;
    autoPrepareAgentReply: boolean;
    autoPrepareAgentReplyOnUpdate: boolean;
    agentAutoSend?: boolean;
    defaultQueueKey: string;
    defaultQueueName: string;
    supportDefaults?: {
        ticketCreation?: string;
        autopilotPrep?: string[];
        humanReview?: boolean;
    };
    outboundWebhookUrl?: string;
    outboundWebhookUrlEnv: string;
    outboundWebhookUrlTemplate?: string;
    outboundWebhookTokenEnv: string;
    authEnvVars: Array<{
        name: string;
        purpose: string;
        required: boolean;
    }>;
    outboundEnvVars: Array<{
        name: string;
        purpose: string;
        required: boolean;
    }>;
    config: Record<string, unknown>;
    testMessage: {
        provider?: string;
        channelId?: string;
        threadId?: string;
        body?: string;
    };
}

export interface SupportChannelValidation {
    channelId: string;
    channelKey: string;
    type: string;
    status: string;
    ready: boolean;
    checkedAt: string;
    summary: {
        checks: number;
        missing: number;
        warnings: number;
        manual: number;
        envConfigured: number;
        envMissing: number;
    };
    checks: Array<{
        key: string;
        label: string;
        status: string;
        detail: string;
    }>;
    envVars: Array<{
        name: string;
        purpose: string;
        required: boolean;
        configured: boolean;
    }>;
    providerValidation?: {
        provider: string;
        status: string;
        checked: boolean;
        detail: string;
        tokenEnv?: string;
        required?: boolean;
        envVars?: string[];
        identity?: Record<string, unknown>;
    };
    remediation?: SupportChannelRemediationStep[];
    setup: SupportChannelSetup;
}

export interface SupportChannelRemediationStep {
    key: string;
    label: string;
    detail: string;
    severity: 'critical' | 'warning' | 'info';
    action: string;
    runAction: string;
    copyLabel: string;
    copyValue: string;
}

export interface SlackInstallUrlResult {
    installUrl: string;
    redirectUri: string;
    scopes: string;
    channelKey: string;
    expiresAt: string;
}

export interface TelegramWebhookResult {
    status: string;
    webhookUrl: string;
    botTokenEnv: string;
    secretTokenEnv: string;
    allowedUpdates: string[];
    telegram: Record<string, unknown>;
}

export interface SupportCrmConnector {
    id: string;
    connectorKey: string;
    provider: string;
    name: string;
    status: string;
    config: Record<string, unknown>;
    lastSyncAt: string;
    created: string;
    updated: string;
}

export interface SupportChannelSyncItem {
    id: string;
    emailId: string;
    subject: string;
    status: string;
    issueId?: string;
    error?: string;
}

export interface SupportChannelSyncResult {
    channelId: string;
    channelKey: string;
    adapter: string;
    status: string;
    processed: number;
    failed: number;
    skipped: number;
    cursorKey: string;
    cursorValue: string;
    items: SupportChannelSyncItem[];
    error: string;
}

export interface SupportChannelTestMessageResult {
    status: string;
    processed: number;
    failed: number;
    skipped: number;
    unmatched?: number;
    payload: Record<string, unknown>;
    items: Array<{
        eventId?: string;
        status?: string;
        kind?: string;
        issueId?: string;
        messageId?: string;
        error?: string;
    }>;
}

export interface SupportChannelSmokeResult extends SupportChannelTestMessageResult {
    channelId: string;
    channelKey: string;
    type: string;
    provider: string;
    transport: string;
    ready: boolean;
    validation: SupportChannelValidation;
    ingestion: Record<string, unknown>;
    http: Record<string, unknown>;
    eventId: string;
    messageId: string;
    issueId?: string;
    attachmentCount?: number;
    fileOnly?: boolean;
    runId?: string;
    remediation?: SupportChannelRemediationStep[];
}

export interface SupportChannelOutboundSmokeResult {
    channelId: string;
    channelKey: string;
    type: string;
    ready: boolean;
    validation: SupportChannelValidation;
    messageId: string;
    provider: string;
    providerMessageId: string;
    status: string;
    sent: boolean;
    deferred: boolean;
    failed: boolean;
    processed: number;
    skipped: number;
    error: string;
    retryAfterSeconds: number;
    metadata: Record<string, unknown>;
    runId?: string;
    remediation?: SupportChannelRemediationStep[];
}

export interface SupportChannelLifecycleSmokeResult {
    channelId: string;
    channelKey: string;
    type: string;
    ready: boolean;
    validation: SupportChannelValidation;
    inbound: SupportChannelSmokeResult | Record<string, unknown>;
    issueId: string;
    replyId: string;
    messageId: string;
    attachmentCount?: number;
    fileOnly?: boolean;
    provider: string;
    providerMessageId: string;
    status: string;
    sent: boolean;
    deferred: boolean;
    failed: boolean;
    processed: number;
    skipped: number;
    error: string;
    approval: Record<string, unknown>;
    delivery: Record<string, unknown>;
    runId?: string;
    remediation?: SupportChannelRemediationStep[];
}

export interface SupportChannelSmokeRun {
    status: string;
    transport: string;
    channels: number;
    ready: number;
    processed: number;
    failed: number;
    skipped: number;
    items: SupportChannelSmokeResult[];
    failures: Array<{
        channelId: string;
        channelKey: string;
        error: string;
    }>;
}

export interface SupportChannelOutboundSmokeRun {
    status: string;
    channels: number;
    ready: number;
    processed: number;
    sent: number;
    deferred: number;
    failed: number;
    skipped: number;
    items: SupportChannelOutboundSmokeResult[];
    failures: Array<{
        channelId: string;
        channelKey: string;
        error: string;
        runId?: string;
        recordingError?: string;
    }>;
}

export interface SupportChannelLifecycleSmokeRun {
    status: string;
    channels: number;
    ready: number;
    processed: number;
    sent: number;
    deferred: number;
    failed: number;
    skipped: number;
    items: SupportChannelLifecycleSmokeResult[];
    failures: Array<{
        channelId: string;
        channelKey: string;
        error: string;
        runId?: string;
        recordingError?: string;
    }>;
}

export interface SupportChannelSyncRunRecord {
    id: string;
    channelId: string;
    source: string;
    status: string;
    processed: number;
    failed: number;
    skipped: number;
    error: string;
    result: Record<string, unknown>;
    startedAt: string;
    completedAt: string;
    created: string;
    updated: string;
}

export interface SupportChannelWebhookEvent {
    id: string;
    channelId: string;
    outboundMessageId: string;
    provider: string;
    eventId: string;
    eventType: string;
    providerMessageId: string;
    status: string;
    error: string;
    payload: Record<string, unknown>;
    result: Record<string, unknown>;
    receivedAt: string;
    processedAt: string;
    created: string;
    updated: string;
}

export interface SupportWebChatSession {
    id: string;
    channelId: string;
    issueId: string;
    issueIds?: string[];
    latestIssueId?: string;
    messageCount?: number;
    sessionKey: string;
    visitorId: string;
    visitorEmail: string;
    visitorName: string;
    pageUrl: string;
    status: string;
    metadata: Record<string, unknown>;
    lastMessageAt: string;
    created: string;
    updated: string;
}

export interface SupportChannelsSyncRun {
    channels: number;
    processed: number;
    failed: number;
    skipped: number;
    items: SupportChannelSyncResult[];
}

export interface SupportCrmSyncItem {
    id: string;
    objectType: string;
    externalId: string;
    status: string;
    accountId?: string;
    contactId?: string;
    objectsSeen?: number;
    error?: string;
}

export interface SupportCrmSyncResult {
    connectorId: string;
    connectorKey: string;
    provider: string;
    adapter: string;
    status: string;
    processed: number;
    failed: number;
    skipped: number;
    objectsSeen: number;
    cursorValue: string;
    items: SupportCrmSyncItem[];
    error: string;
}

export interface SupportCrmValidation {
    connectorId: string;
    connectorKey: string;
    provider: string;
    adapter: string;
    ready: boolean;
    status: string;
    checks: Array<{
        key: string;
        label: string;
        status: string;
        detail: string;
        count?: number;
        skipped?: number;
    }>;
    envVars: Array<{
        name: string;
        required: boolean;
        configured: boolean;
        status: string;
    }>;
    sample: Record<string, number>;
    error: string;
}

export interface SupportCrmSyncRunRecord {
    id: string;
    connectorId: string;
    source: string;
    status: string;
    processed: number;
    failed: number;
    skipped: number;
    objectsSeen: number;
    error: string;
    result: Record<string, unknown>;
    startedAt: string;
    completedAt: string;
    created: string;
    updated: string;
}

export interface SupportCrmWebhookEvent {
    id: string;
    connectorId: string;
    provider: string;
    eventId: string;
    eventType: string;
    objectType: string;
    externalId: string;
    status: string;
    error: string;
    payload: Record<string, unknown>;
    result: Record<string, unknown>;
    receivedAt: string;
    processedAt: string;
    created: string;
    updated: string;
}

export interface SupportCrmConnectorsSyncRun {
    connectors: number;
    processed: number;
    failed: number;
    skipped: number;
    objectsSeen: number;
    items: SupportCrmSyncResult[];
}

export type SupportAutomationTrigger =
    | 'issue_created'
    | 'issue_updated'
    | 'sla_breached'
    | 'reply_approved'
    | 'reply_sent'
    | 'reply_failed'
    | 'reply_deferred'
    | 'any_issue_event'
    | 'manual';

export interface SupportAutomationRule {
    id: string;
    name: string;
    active: boolean;
    trigger: string;
    conditions: Record<string, unknown>;
    actions: Array<Record<string, unknown>>;
    lastRunAt: string;
    created: string;
    updated: string;
}

export interface SupportAutomationRun {
    id: string;
    ruleId: string;
    issueId: string;
    trigger: string;
    status: string;
    actionsApplied: number;
    error: string;
    context: Record<string, unknown>;
    result: Record<string, unknown>;
    startedAt: string;
    completedAt: string;
    created: string;
    updated: string;
}

export interface SupportAutomationsRunResult {
    processed: number;
    failed: number;
    items: SupportAutomationRun[];
}

export interface SupportAutomationBacklogRunItem {
    issueId: string;
    processed: number;
    failed: number;
    skipped: boolean;
    items: SupportAutomationRun[];
}

export interface SupportAutomationBacklogRunResult {
    issues: number;
    processed: number;
    failed: number;
    skipped: number;
    runs: number;
    items: SupportAutomationBacklogRunItem[];
}

export interface SupportAutomationPreviewAction {
    type: string;
    status: string;
    action: Record<string, unknown>;
    assigneeEmail?: string;
    statusValue?: string;
    priority?: string;
    body?: string;
    approvalRequired?: boolean;
    includeFeedbackLink?: boolean;
    question?: string;
    createDraft?: boolean;
    autoSend?: boolean;
    autoSendRequested?: boolean;
    autoSendPolicy?: string;
    autoSendBlockedReason?: string;
    effect?: string;
    directTicketMutation?: boolean;
    createsApprovalWork?: boolean;
    createsCustomerReply?: boolean;
    approvalGate?: string;
    deliveryEffect?: string;
    autoSendBlocked?: boolean;
    ungated?: boolean;
    label?: string;
    actionKey?: string;
    [key: string]: unknown;
}

export interface SupportAutomationPreviewWarning {
    key: string;
    label: string;
    detail: string;
    count: number;
}

export interface SupportAutomationPreviewSummary {
    matchedActions: number;
    approvalActions: number;
    directTicketMutations: number;
    customerReplyActions: number;
    autoSendActions: number;
    autoSendBlocked: number;
    ungatedActions: number;
    warnings: SupportAutomationPreviewWarning[];
}

export interface SupportAutomationPreviewItem {
    rule: SupportAutomationRule;
    matched: boolean;
    conditions: Record<string, unknown>;
    actions: SupportAutomationPreviewAction[];
    summary?: SupportAutomationPreviewSummary;
}

export interface SupportAutomationPreviewResult {
    issueId: string;
    trigger: string;
    rules: number;
    matched: number;
    summary?: SupportAutomationPreviewSummary;
    items: SupportAutomationPreviewItem[];
}

export interface KnowledgeArticleRevision {
    revision: number;
    action: string;
    actorEmail: string;
    at: string;
    changedFields: string[];
    title: string;
    status: string;
    visibility: string;
    public: boolean;
    automationAllowed?: boolean;
    tags: string[];
    sourceIssueId: string;
    sourceUrl: string;
    bodySha256: string;
    bodyPreview: string;
    fromStatus?: string;
    fromVisibility?: string;
}

export interface KnowledgeArticle {
    id: string;
    sourceIssueId: string;
    sourceUrl: string;
    visibility: string;
    public: boolean;
    automationAllowed: boolean;
    title: string;
    body: string;
    status: string;
    reviewStatus: string;
    lastReviewedAt: string;
    reviewedBy: string;
    reviewDueAt: string;
    freshnessStatus: string;
    freshnessReason: string;
    needsReview: boolean;
    tags: string[];
    metadata: Record<string, unknown>;
    revision?: number;
    revisions?: KnowledgeArticleRevision[];
    created: string;
    updated: string;
}

export interface KnowledgeGap {
    id: string;
    issueId: string;
    gapKey: string;
    title: string;
    evidence: string;
    status: string;
    severity: string;
    suggestedArticleTitle: string;
    metadata: Record<string, unknown>;
    firstSeenAt: string;
    lastSeenAt: string;
    created: string;
    updated: string;
}

export interface SupportLaunchReadinessItem {
    key: string;
    label: string;
    count: number;
}

export interface SupportSchemaHealthItem {
    name: string;
    exists: boolean;
    error: string;
    area?: string;
    migration?: string;
}

export interface SupportSchemaFieldHealthItem {
    collection: string;
    field: string;
    exists: boolean;
    error: string;
    area?: string;
    migration?: string;
}

export interface SupportSchemaMigrationHealthItem {
    name: string;
    exists: boolean;
}

export interface SupportSchemaHealth {
    status: string;
    ready: boolean;
    requiredCollections: number;
    presentCollections: number;
    missingCollections: string[];
    requiredFields?: number;
    presentFields?: number;
    missingFields?: string[];
    expectedMigrations?: number;
    presentMigrations?: number;
    missingMigrationFiles?: string[];
    items: SupportSchemaHealthItem[];
    fieldItems?: SupportSchemaFieldHealthItem[];
    migrationItems?: SupportSchemaMigrationHealthItem[];
}

export interface SupportLaunchProofSchema {
    status: string;
    ready: boolean;
    requiredCollections: number;
    presentCollections: number;
    missingCollections: string[];
    requiredFields: number;
    presentFields: number;
    missingFields: string[];
    expectedMigrations: number;
    presentMigrations: number;
    missingMigrationFiles: string[];
}

export interface SupportLaunchProofCheck {
    key: string;
    label: string;
    status: string;
    detail: string;
    runId: string;
    sessionId?: string;
    source: string;
    runStatus: string;
    processed: number;
    failed: number;
    sent: number;
    startedAt: string;
    transport?: string;
    provider?: string;
    providerMessageId?: string;
    deliveryRoute?: Record<string, unknown>;
    providerResponse?: Record<string, unknown>;
    attachmentCount?: number;
    fileOnly?: boolean;
    authMode?: string;
    signatureTimestampHeader?: string;
    issueId?: string;
    replyId?: string;
    aiRunId?: string;
}

export interface SupportLaunchProofEvidenceItem {
    kind: string;
    key?: string;
    label: string;
    detail: string;
    issueId?: string;
    accountId?: string;
    accountKey?: string;
    accountName?: string;
    domain?: string;
    healthStatus?: string;
    actionKind?: string;
    actionLabel?: string;
    route?: string;
    replyId?: string;
    runId?: string;
    eventIds?: string[];
    occurredAt?: string;
    source?: string;
    citationCount?: number;
    knowledgeArticleIds?: string[];
    knowledgeGapId?: string;
    confidence?: string;
    openIssues?: number;
    openRisks?: number;
    openFeatureRequests?: number;
    unresolvedSignals?: number;
    failedExternalSyncRuns?: number;
}

export interface SupportLaunchProofChannel {
    channelId: string;
    channelKey: string;
    name: string;
    type: string;
    surfaceType?: string;
    status: string;
    proofKind: string;
    launchWave?: string;
    initialProvider?: boolean;
    required: boolean;
    ready: boolean;
    checks: number;
    passed: number;
    blocked: number;
    lastCheckedAt: string;
    blockers: Array<{
        key: string;
        label: string;
        status: string;
        detail: string;
        runId: string;
    }>;
    checklist: SupportLaunchProofCheck[];
}

export interface SupportLaunchProofChannelBacklogItem {
    channelId: string;
    channelKey: string;
    name: string;
    type: string;
    status: string;
}

export interface SupportLaunchProofChannelBacklog {
    total: number;
    types: string[];
    items: SupportLaunchProofChannelBacklogItem[];
}

export interface SupportLaunchProofInitialProviderItem {
    surfaceType: string;
    surfaceLabel: string;
    launchWave: string;
    channelId: string;
    channelKey: string;
    name: string;
    type: string;
    status: string;
    ready: boolean;
    checks: number;
    passed: number;
    blocked: number;
    proofKind: string;
    detail: string;
    blockers: Array<{
        key: string;
        label: string;
        status: string;
        detail: string;
        runId: string;
    }>;
}

export interface SupportLaunchProofInitialProviders {
    required: boolean;
    total: number;
    ready: number;
    blocked: number;
    items: SupportLaunchProofInitialProviderItem[];
}

export interface SupportLaunchProofTicketCreationItem {
    channelId: string;
    channelKey: string;
    name: string;
    type: string;
    mode: string;
    ready: boolean;
    detail: string;
}

export interface SupportLaunchProofTicketCreation {
    total: number;
    ready: number;
    blocked: number;
    wrongMode: number;
    items: SupportLaunchProofTicketCreationItem[];
}

export interface SupportLaunchProofReplyRouteItem {
    channelId: string;
    channelKey: string;
    name: string;
    type: string;
    ready: boolean;
    proofKey: string;
    transport: string;
    provider: string;
    providerMessageId: string;
    runId: string;
    issueId: string;
    replyId: string;
    detail: string;
}

export interface SupportLaunchProofReplyRoute {
    total: number;
    ready: number;
    blocked: number;
    items: SupportLaunchProofReplyRouteItem[];
}

export interface SupportLaunchProofChannelAutopilotItem {
    channelId: string;
    channelKey: string;
    name: string;
    type: string;
    ready: boolean;
    proofKey: string;
    runStatus: string;
    runId: string;
    issueId: string;
    replyId: string;
    aiRunId: string;
    detail: string;
}

export interface SupportLaunchProofChannelAutopilot {
    required: boolean;
    total: number;
    ready: number;
    blocked: number;
    items: SupportLaunchProofChannelAutopilotItem[];
}

export interface SupportLaunchProofKnowledgeAssist {
    required: boolean;
    ready: boolean;
    blocked: number;
    articles: number;
    openGaps: number;
    successfulRuns: number;
    citationRuns: number;
    gapRuns: number;
    items: SupportLaunchProofEvidenceItem[];
}

export interface SupportLaunchProofAccountIntelligence {
    required: boolean;
    ready: boolean;
    blocked: number;
    accounts: number;
    actions: number;
    openRisks: number;
    featureRequests: number;
    failedSyncRuns: number;
    items: SupportLaunchProofEvidenceItem[];
}

export interface SupportLaunchProofHumanLoop {
    required: boolean;
    ready: boolean;
    blocked: number;
    rules: number;
    successfulRuns: number;
    pendingApprovals: number;
    items: SupportLaunchProofEvidenceItem[];
}

export interface SupportLaunchProofTicketWorkflow {
    required: boolean;
    ready: boolean;
    blocked: number;
    transitions: number;
    ongoingTransitions: number;
    doneTransitions: number;
    successfulIssues: number;
    items: SupportLaunchProofEvidenceItem[];
}

export interface SupportLaunchProof {
    status: string;
    schema: SupportLaunchProofSchema;
    channels: {
        total: number;
        active: number;
        required: number;
        ready: number;
        blocked: number;
        items: SupportLaunchProofChannel[];
    };
    channelBacklog?: SupportLaunchProofChannelBacklog;
    initialProviders?: SupportLaunchProofInitialProviders;
    ticketCreation?: SupportLaunchProofTicketCreation;
    replyRoute?: SupportLaunchProofReplyRoute;
    channelAutopilot?: SupportLaunchProofChannelAutopilot;
    knowledgeAssist?: SupportLaunchProofKnowledgeAssist;
    accountIntelligence?: SupportLaunchProofAccountIntelligence;
    humanLoop?: SupportLaunchProofHumanLoop;
    ticketWorkflow?: SupportLaunchProofTicketWorkflow;
    blockers: SupportLaunchReadinessItem[];
    warnings: SupportLaunchReadinessItem[];
    checkedAt: string;
    evidence?: {
        workflowLifecycle?: SupportLaunchProofEvidenceItem[];
        humanLoopAutomation?: SupportLaunchProofEvidenceItem[];
        knowledgeAssist?: SupportLaunchProofEvidenceItem[];
        accountIntelligence?: SupportLaunchProofEvidenceItem[];
    };
}

export interface SupportWorkflowProofRunResult {
    issue: SupportIssue;
    launchReadiness: {
        status: string;
        blockers: SupportLaunchReadinessItem[];
        warnings: SupportLaunchReadinessItem[];
        checks: number;
    };
    workflowTransitionEvents: number;
    workflowOngoingTransitions: number;
    workflowDoneTransitions: number;
    successfulWorkflowLifecycleProofs: number;
}

export interface SupportAutomationProofRunResult {
    issue: SupportIssue;
    launchReadiness: {
        status: string;
        blockers: SupportLaunchReadinessItem[];
        warnings: SupportLaunchReadinessItem[];
        checks: number;
    };
    automationRuns: number;
    successfulAutomationRuns: number;
    successfulHumanLoopAutomationRuns: number;
    issuesNeedingApproval: number;
}

export interface SupportHumanLoopAutomationSetupResult extends SupportAutomationProofRunResult {
    createdRule: boolean;
    rule: SupportAutomationRule;
}

export interface SupportLaunchProofRunAction {
    key: string;
    label: string;
    status: string;
    error: string;
    result: Record<string, unknown>;
}

export interface SupportLaunchProofRunResult {
    id?: string;
    status?: string;
    actions: SupportLaunchProofRunAction[];
    ran: number;
    failed: number;
    skipped: number;
    error?: string;
    launchReadiness: {
        status: string;
        blockers: SupportLaunchReadinessItem[];
        warnings: SupportLaunchReadinessItem[];
        checks: number;
    };
    launchProof: SupportLaunchProof;
    startedAt?: string;
    completedAt?: string;
    created?: string;
    updated?: string;
}

export interface SupportLaunchProofRunsResponse {
    items: SupportLaunchProofRunResult[];
}

export interface SupportAnalytics {
    launchReadiness?: {
        status: string;
        blockers: SupportLaunchReadinessItem[];
        warnings: SupportLaunchReadinessItem[];
        checks: number;
    };
    launchProof?: SupportLaunchProof;
    latestLaunchProofRun?: SupportLaunchProofRunResult | null;
    totalIssues: number;
    openIssues: number;
    ongoingIssues: number;
    doneIssues: number;
    pendingIssues: number;
    closedIssues: number;
    unassignedIssues: number;
    openWorkloadIssues: number;
    queueOwnersAtCapacity: number;
    queueOwnerCapacityItems: SupportAnalyticsQueueCapacityItem[];
    openQueueBreakdown: SupportAnalyticsBreakdownItem[];
    openAssigneeBreakdown: SupportAnalyticsBreakdownItem[];
    openChannelBreakdown: SupportAnalyticsBreakdownItem[];
    supportHealthInsights: SupportAnalyticsInsight[];
    issuesNeedingApproval: number;
    issuesNeedingResponse: number;
    oldestNeedsResponseAt: string;
    oldestNeedsResponseHours: number;
    urgentIssues: number;
    highPriorityIssues: number;
    channels: number;
    activeChannels: number;
    channelBacklogSurfaces: number;
    channelBacklogTypes: string[];
    initialProviderSurfaces?: number;
    initialProviderReady?: number;
    initialProviderBlocked?: number;
    accounts: number;
    accountsNeedingAction: number;
    accountActionQueue: SupportAccountActionQueueItem[];
    knowledgeArticles: number;
    knowledgeGaps: number;
    openKnowledgeGaps: number;
    accountInsights: number;
    openAccountRisks: number;
    featureRequests: number;
    externalObjects: number;
    externalSyncRuns: number;
    failedExternalSyncRuns: number;
    crmConnectors: number;
    activeCrmConnectors: number;
    crmSyncRuns: number;
    failedCrmSyncRuns: number;
    crmWebhookEvents: number;
    failedCrmWebhookEvents: number;
    overdueSlaEvents: number;
    dueSoonSlaEvents: number;
    slaEvents: number;
    pendingSlaEvents: number;
    metSlaEvents: number;
    breachedSlaEvents: number;
    averageFirstResponseMinutes: number;
    p90FirstResponseMinutes: number;
    averageResolutionHours: number;
    p90ResolutionHours: number;
    aiRuns: number;
    aiRunsNeedingHuman: number;
    actionExecutions: number;
    successfulActionExecutions: number;
    automationRules: number;
    activeAutomationRules: number;
    agentAutomationRules: number;
    humanLoopAutomationRules: number;
    automationRuns: number;
    successfulAutomationRuns: number;
    successfulHumanLoopAutomationRuns: number;
    successfulKnowledgeAssistRuns: number;
    successfulAccountIntelligenceProofs: number;
    successfulChannelAutopilotPrepPackages: number;
    /** Backward-compatible backend alias. Prefer successfulChannelAutopilotPrepPackages. */
    successfulChannelAutopilotDrafts: number;
    failedAutomationRuns: number;
    workflowTransitionEvents: number;
    workflowOngoingTransitions: number;
    workflowDoneTransitions: number;
    successfulWorkflowLifecycleProofs: number;
    activityEvents: number;
    outboundMessages: number;
    queuedOutboundMessages: number;
    sentOutboundMessages: number;
    failedOutboundMessages: number;
    channelSyncRuns: number;
    failedChannelSyncRuns: number;
    activeEmailChannelsWithSync: number;
    activeEmailChannelsMissingSync: number;
    failedEmailChannelSyncRuns: number;
    activeEmailChannelsWithDelivery: number;
    activeEmailChannelsMissingDelivery: number;
    channelValidationRuns: number;
    failedChannelValidationRuns: number;
    channelRemediationRuns: number;
    channelRemediationItems: number;
    latestChannelRemediations: SupportAnalyticsChannelRemediation[];
    activeChannelsWithProviderValidation: number;
    activeChannelsMissingProviderValidation: number;
    activeChannelsWithLiveSmokeTarget: number;
    activeChannelsMissingLiveSmokeTarget: number;
    channelSmokeRuns: number;
    failedChannelSmokeRuns: number;
    activeChannelsWithSmoke: number;
    activeChannelsMissingSmoke: number;
    outboundChannelSmokeRuns: number;
    failedOutboundChannelSmokeRuns: number;
    activeChannelsWithOutboundSmoke: number;
    activeChannelsMissingOutboundSmoke: number;
    lifecycleChannelSmokeRuns: number;
    failedLifecycleChannelSmokeRuns: number;
    activeChannelsWithLifecycleSmoke: number;
    activeChannelsMissingLifecycleSmoke: number;
    activeChannelsWithAttachmentLifecycleSmoke: number;
    activeChannelsMissingAttachmentLifecycleSmoke: number;
    activeSlackChannelsWithAttachmentLifecycleSmoke: number;
    activeSlackChannelsMissingAttachmentLifecycleSmoke: number;
    failedAttachmentLifecycleChannelSmokeRuns: number;
    activeChannelsWrongTicketMode: number;
    activeChannelsWithoutAutoPrepare: number;
    activeChannelsWithOwnerRouting: number;
    activeChannelsMissingOwnerRouting: number;
    activeChannelsWithAutopilotPrepPackage: number;
    activeChannelsMissingAutopilotPrepPackage: number;
    /** Backward-compatible backend alias. Prefer activeChannelsWithAutopilotPrepPackage. */
    activeChannelsWithAutopilotDraft: number;
    /** Backward-compatible backend alias. Prefer activeChannelsMissingAutopilotPrepPackage. */
    activeChannelsMissingAutopilotDraft: number;
    channelWebhookEvents: number;
    failedChannelWebhookEvents: number;
    unmatchedChannelWebhookEvents: number;
    webChatSessions: number;
    openWebChatSessions: number;
    activeWebChatChannelsWithSession: number;
    activeWebChatChannelsMissingSession: number;
    failedWebChatChannelSessionProofs: number;
    activeWebChatChannelsWithDelivery: number;
    activeWebChatChannelsMissingDelivery: number;
    failedWebChatChannelDeliveryProofs: number;
    deliveryRuns: number;
    failedDeliveryRuns: number;
    portalSessions: number;
    activePortalSessions: number;
    csatFeedback: number;
    averageCsatRating: number;
    lowCsatFeedback: number;
    csatRatingCounts: Record<string, number>;
    statusCounts: Record<string, number>;
    priorityCounts: Record<string, number>;
    channelCounts: Record<string, number>;
    queueCounts: Record<string, number>;
    assigneeCounts: Record<string, number>;
}

export interface SupportAnalyticsChannelRemediation {
    channelId: string;
    channelKey: string;
    channelName: string;
    source: string;
    status: string;
    startedAt: string;
    key: string;
    label: string;
    detail: string;
    severity: 'critical' | 'warning' | 'info';
    action: string;
    runAction: string;
}

export interface SupportAnalyticsBreakdownItem {
    key: string;
    label: string;
    count: number;
}

export interface SupportAnalyticsQueueCapacityItem {
    queueKey: string;
    queueName: string;
    assigneeEmail: string;
    activeTickets: number;
    capacity: number;
    overBy: number;
}

export interface SupportAnalyticsInsight {
    key: string;
    label: string;
    detail: string;
    severity: 'critical' | 'warning' | 'good' | 'neutral';
    route: string;
    value: number;
    target: number;
    unit: string;
}

export interface SupportDeliveryRun {
    processed: number;
    sent: number;
    failed: number;
    deferred?: number;
    blocked?: number;
    retryFailed?: boolean;
    status?: string;
    error?: string;
    items: SupportOutboundMessage[];
}

export interface SupportSlaEscalationRun {
    processed: number;
    escalated: number;
    skipped: number;
    failed: number;
    error?: string;
    items: Array<{
        slaEventId: string;
        issueId: string;
        eventType: string;
        targetAt: string;
        status: string;
        reason: string;
        automation?: {
            processed: number;
            failed: number;
            items: SupportAutomationRun[];
        };
    }>;
}

export interface SupportDeliveryRunRecord {
    id: string;
    source: string;
    status: string;
    processed: number;
    sent: number;
    failed: number;
    error: string;
    result: Record<string, unknown>;
    startedAt: string;
    completedAt: string;
    created: string;
    updated: string;
}

export interface SupportBulkApproveSendResult {
    processed: number;
    approved?: number;
    changesRequested?: number;
    sent: number;
    failed: Array<{ id: string; replyId?: string; error: string }>;
    items: Array<{
        issueId: string;
        replyId: string;
        status: string;
        error: string;
        reply: SupportOutboundMessage;
    }>;
    issues: SupportIssue[];
}

// ── Admin API ─────────────────────────────────────────────────────────────────

export const api = {
    /** Auth */
    login,
    requestLoginCode,
    verifyLoginCode,
    signup,
    changePassword,
    requestPasswordReset,
    confirmVerification,
    getAuthConfig,

    // ── Projects (tenant-level) ─────────────────────────────────────────────

    listProjects: async (): Promise<ApiResponse<Project[]>> => {
        return apiClient.get('/api/admin/projects');
    },
    getProject: async (projectId: string): Promise<ApiResponse<Project>> => {
        return apiClient.get(`/api/admin/projects/${projectId}`);
    },
    createProject: async (name: string, description: string): Promise<ApiResponse<{ id: string; name: string }>> => {
        return apiClient.post('/api/admin/projects', { name, description });
    },
    updateProject: async (projectId: string, data: { name?: string; description?: string }): Promise<ApiResponse<unknown>> => {
        return apiClient.put(`/api/admin/projects/${projectId}`, data);
    },
    deleteProject: async (projectId: string): Promise<ApiResponse<unknown>> => {
        return apiClient.delete(`/api/admin/projects/${projectId}`);
    },

    // ── Project Members ─────────────────────────────────────────────────────

    listMembers: async (projectId: string): Promise<ApiResponse<ProjectMember[]>> => {
        return apiClient.get(`${p(projectId)}/members`);
    },
    addMember: async (projectId: string, userId: string, role: string): Promise<ApiResponse<{ id: string; userId: string; role: string }>> => {
        return apiClient.post(`${p(projectId)}/members`, { userId, role });
    },
    updateMemberRole: async (projectId: string, memberId: string, role: string): Promise<ApiResponse<unknown>> => {
        return apiClient.put(`${p(projectId)}/members/${memberId}`, { role });
    },
    removeMember: async (projectId: string, memberId: string): Promise<ApiResponse<unknown>> => {
        return apiClient.delete(`${p(projectId)}/members/${memberId}`);
    },

    // ── Admin config (project-scoped) ───────────────────────────────────────

    getAdminConfig: async (projectId: string): Promise<ApiResponse<AdminConfigData>> => {
        return apiClient.get(`${p(projectId)}/config`);
    },
    updateAdminConfig: async (projectId: string, config: Partial<AdminConfigData>): Promise<ApiResponse<unknown>> => {
        const res = await apiClient.put(`${p(projectId)}/config`, config);
        if (!res.error) notifyDraftChanged();
        return res;
    },

    /** Email processing (demo / preview) — project-scoped */
    processEmail: async (projectId: string, payload: {
        email: { id: string; subject: string; fromAddress: string; body: string; attachments: [] };
        action: 'respond';
        creator: string;
    }): Promise<ApiResponse<unknown[]>> => {
        return apiClient.post(`${p(projectId)}/preview`, payload);
    },

    // ── Intents CRUD (project-scoped) ───────────────────────────────────────

    getIntents: async (projectId: string): Promise<ApiResponse<Array<{ name: string; description: string; actions: unknown[]; response: unknown; active: boolean }>>> => {
        return apiClient.get(`${p(projectId)}/intents`);
    },
    getIntent: async (projectId: string, name: string): Promise<ApiResponse<{ name: string; content: string }>> => {
        return apiClient.get(`${p(projectId)}/intents/${name}`);
    },
    upsertIntent: async (projectId: string, name: string, content: string): Promise<ApiResponse<unknown>> => {
        const res = await apiClient.put(`${p(projectId)}/intents/${name}`, { content });
        if (!res.error) notifyDraftChanged();
        return res;
    },
    deleteIntent: async (projectId: string, name: string): Promise<ApiResponse<unknown>> => {
        const res = await apiClient.delete(`${p(projectId)}/intents/${name}`);
        if (!res.error) notifyDraftChanged();
        return res;
    },
    renameIntent: async (projectId: string, oldName: string, newName: string): Promise<ApiResponse<{ oldName: string; newName: string }>> => {
        const res = await apiClient.patch<{ oldName: string; newName: string }>(`${p(projectId)}/intents/${oldName}`, { newName });
        if (!res.error) notifyDraftChanged();
        return res;
    },

    // ── Intent files (response attachments) — project-scoped ────────────────

    listIntentFiles: async (projectId: string, intentName: string): Promise<ApiResponse<IntentFileInfo[]>> => {
        return apiClient.get(`${p(projectId)}/intents/${intentName}/files`);
    },
    uploadIntentFile: async (projectId: string, intentName: string, file: File): Promise<ApiResponse<{ filename: string; size: number }>> => {
        const formData = new FormData();
        formData.append('file', file);
        const token = localStorage.getItem('admin_auth_token');
        try {
            const resp = await fetch(`${settings.apiBaseUrl}${p(projectId)}/intents/${intentName}/files`, {
                method: 'POST',
                headers: token ? { Authorization: `Bearer ${token}` } : {},
                body: formData,
            });
            const data: unknown = await resp.json();
            if (!resp.ok) {
                const detail = isRecord(data) && typeof data.detail === 'string' ? data.detail : `HTTP ${resp.status}`;
                return { data: null, error: detail, status: resp.status };
            }
            if (!isIntentFileUpload(data)) {
                return { data: null, error: 'Invalid upload response', status: resp.status };
            }
            notifyDraftChanged();
            return { data, error: null, status: resp.status };
        } catch (err) {
            return { data: null, error: err instanceof Error ? err.message : 'Upload failed', status: 0 };
        }
    },
    deleteIntentFile: async (projectId: string, intentName: string, filename: string): Promise<ApiResponse<unknown>> => {
        const res = await apiClient.delete(`${p(projectId)}/intents/${intentName}/files/${filename}`);
        if (!res.error) notifyDraftChanged();
        return res;
    },

    // ── Intent learnings & feedback (project-scoped) ────────────────────────

    getIntentLearnings: async (projectId: string, intentName: string): Promise<ApiResponse<Array<{ id: string; learning: string; source_feedback_id: string; affected_stages: string[]; created: string }>>> => {
        return apiClient.get(`${p(projectId)}/intents/${intentName}/learnings`);
    },
    updateIntentLearning: async (projectId: string, intentName: string, learningId: string, learning: string): Promise<ApiResponse<unknown>> => {
        return apiClient.put(`${p(projectId)}/intents/${intentName}/learnings/${learningId}`, { learning });
    },
    deleteIntentLearning: async (projectId: string, intentName: string, learningId: string): Promise<ApiResponse<unknown>> => {
        return apiClient.delete(`${p(projectId)}/intents/${intentName}/learnings/${learningId}`);
    },
    getIntentFeedback: async (projectId: string, intentName: string): Promise<ApiResponse<Array<{ id: string; rating: string; affected_stages: string[]; feedback_text: string; user_email: string; created: string }>>> => {
        return apiClient.get(`${p(projectId)}/intents/${intentName}/feedback`);
    },
    deleteIntentFeedback: async (projectId: string, intentName: string, feedbackId: string): Promise<ApiResponse<{ status: string; id?: string; removedLearningCount?: number }>> => {
        return apiClient.delete(`${p(projectId)}/intents/${intentName}/feedback/${feedbackId}`);
    },
    getIntentLearningProposals: async (projectId: string, intentName: string): Promise<ApiResponse<IntentLearningProposal[]>> => {
        return apiClient.get(`${p(projectId)}/intents/${intentName}/learning-proposals`);
    },
    getIntentLearningProposal: async (projectId: string, intentName: string, proposalId: string): Promise<ApiResponse<IntentLearningProposal>> => {
        return apiClient.get(`${p(projectId)}/intents/${intentName}/learning-proposals/${proposalId}`);
    },
    createIntentLearningProposal: async (projectId: string, intentName: string, data: IntentLearningProposalInput): Promise<ApiResponse<IntentLearningProposal>> => {
        return apiClient.post(`${p(projectId)}/intents/${intentName}/learning-proposals`, data);
    },
    createIntentLearningProposalsFromFeedback: async (
        projectId: string,
        intentName: string,
        feedbackId: string,
        learning?: string,
    ): Promise<ApiResponse<{ proposals: IntentLearningProposal[] }>> => {
        return apiClient.post(`${p(projectId)}/intents/${intentName}/feedback/${feedbackId}/learning-proposals`, learning ? { learning } : {});
    },
    evaluateIntentLearningProposal: async (
        projectId: string,
        intentName: string,
        proposalId: string,
        evalSetId: string,
        minimumScore = 80,
    ): Promise<ApiResponse<IntentLearningProposal>> => {
        return apiClient.post(`${p(projectId)}/intents/${intentName}/learning-proposals/${proposalId}/evaluate`, {
            evalSetId,
            minimumScore,
        });
    },
    publishIntentLearningProposal: async (projectId: string, intentName: string, proposalId: string): Promise<ApiResponse<IntentLearningProposal>> => {
        return apiClient.post(`${p(projectId)}/intents/${intentName}/learning-proposals/${proposalId}/publish`, {});
    },
    rejectIntentLearningProposal: async (projectId: string, intentName: string, proposalId: string, reason?: string): Promise<ApiResponse<IntentLearningProposal>> => {
        return apiClient.post(`${p(projectId)}/intents/${intentName}/learning-proposals/${proposalId}/reject`, reason ? { reason } : {});
    },

    // ── Tenant / organisation settings ──────────────────────────────────────

    getTenantSettings: async (): Promise<ApiResponse<TenantSettings>> => {
        return apiClient.get('/api/admin/tenant/settings');
    },
    updateTenantSettings: async (settings: Partial<TenantSettings>): Promise<ApiResponse<TenantSettings>> => {
        return apiClient.patch('/api/admin/tenant/settings', settings);
    },

    // ── Secrets (tenant + project level) ────────────────────────────────────

    getTenantSecrets: async (): Promise<ApiResponse<Record<string, string>>> => {
        return apiClient.get('/api/admin/tenant/secrets');
    },
    updateTenantSecrets: async (secrets: Record<string, string>): Promise<ApiResponse<Record<string, string>>> => {
        return apiClient.patch('/api/admin/tenant/secrets', secrets);
    },
    getProjectSecrets: async (projectId: string): Promise<ApiResponse<Record<string, string>>> => {
        return apiClient.get(`${p(projectId)}/secrets`);
    },
    updateProjectSecrets: async (projectId: string, secrets: Record<string, string>): Promise<ApiResponse<Record<string, string>>> => {
        return apiClient.patch(`${p(projectId)}/secrets`, secrets);
    },

    // ── Users (tenant-level, root only) ─────────────────────────────────────

    getUsers: async (): Promise<ApiResponse<TenantUser[]>> => {
        return apiClient.get('/api/admin/users');
    },
    createUser: async (
        email: string,
        password: string,
        isRoot: boolean,
    ): Promise<ApiResponse<{ id: string; email: string }>> => {
        return apiClient.post('/api/admin/users', { email, password, isRoot });
    },
    /** SaaS: Add an existing user to this tenant by email. */
    addUserByEmail: async (
        email: string,
    ): Promise<ApiResponse<{ id: string; email: string }>> => {
        return apiClient.post('/api/admin/users/add-by-email', { email });
    },
    deleteUser: async (userId: string): Promise<ApiResponse<{ status: string }>> => {
        return apiClient.delete(`/api/admin/users/${userId}`);
    },
    setUserDefaultProject: async (
        userId: string,
        projectId: string | null,
    ): Promise<ApiResponse<{ defaultProject: string | null }>> => {
        return apiClient.put(`/api/admin/users/${userId}/default-project`, { projectId });
    },
    setUserPasswordLogin: async (
        userId: string,
        enabled: boolean,
    ): Promise<ApiResponse<{ id: string; passwordLoginEnabled: boolean }>> => {
        return apiClient.patch(`/api/admin/users/${userId}/password-login`, { enabled });
    },
    getCurrentUser: async (): Promise<ApiResponse<CurrentUserProfile>> => {
        return apiClient.get('/api/admin/me');
    },
    updateCurrentUser: async (
        data: { name?: string; language?: Locale },
    ): Promise<ApiResponse<{ id: string; email: string; name: string; language: Locale }>> => {
        return apiClient.put('/api/admin/me', data);
    },

    // ── Publish (draft → live) — project-scoped ────────────────────────────

    publish: async (projectId: string): Promise<ApiResponse<{ status: string }>> => {
        return apiClient.post(`${p(projectId)}/publish`, {});
    },
    getPublishStatus: async (projectId: string): Promise<ApiResponse<{ hasUnpublishedChanges: boolean }>> => {
        return apiClient.get(`${p(projectId)}/publish/status`);
    },

    // ── Monitor (project-scoped) ───────────────────────────────────────────

    // ── Inbox / Issues (project-scoped) ────────────────────────────────────

    getIssues: async (
        projectId: string,
        status = 'all',
        limit = 100,
        queueKey = '',
        filters: SupportIssueListFilters = {},
    ): Promise<ApiResponse<{ items: SupportIssue[] }>> => {
        const query = new URLSearchParams({ status, limit: String(limit) });
        if (queueKey) query.set('queue_key', queueKey);
        if (filters.accountKey) query.set('account_key', filters.accountKey);
        if (filters.channel) query.set('channel', filters.channel);
        if (filters.assigneeEmail) query.set('assignee_email', filters.assigneeEmail);
        if (filters.tag) query.set('tag', filters.tag);
        if (filters.query) query.set('query', filters.query);
        return apiClient.get(`${p(projectId)}/issues?${query.toString()}`);
    },
    getIssueBoard: async (
        projectId: string,
        status = 'all',
        limit = 200,
        queueKey = '',
        filters: SupportIssueListFilters = {},
    ): Promise<ApiResponse<SupportIssueBoard>> => {
        const query = new URLSearchParams({ status, limit: String(limit) });
        if (queueKey) query.set('queue_key', queueKey);
        if (filters.accountKey) query.set('account_key', filters.accountKey);
        if (filters.channel) query.set('channel', filters.channel);
        if (filters.assigneeEmail) query.set('assignee_email', filters.assigneeEmail);
        if (filters.tag) query.set('tag', filters.tag);
        if (filters.query) query.set('query', filters.query);
        return apiClient.get(`${p(projectId)}/issues/board?${query.toString()}`);
    },
    getIssue: async (projectId: string, issueId: string): Promise<ApiResponse<SupportIssue>> => {
        return apiClient.get(`${p(projectId)}/issues/${encodeURIComponent(issueId)}`);
    },
    getIssueAnswerWorkspace: async (
        projectId: string,
        issueId: string,
    ): Promise<ApiResponse<SupportIssueAnswerWorkspace>> => {
        return apiClient.get(`${p(projectId)}/issues/${encodeURIComponent(issueId)}/answer-workspace`);
    },
    getIssueByChat: async (projectId: string, chatId: string): Promise<ApiResponse<SupportIssue>> => {
        return apiClient.get(`${p(projectId)}/issues/by-chat/${encodeURIComponent(chatId)}`);
    },
    getIssueDuplicateSuggestions: async (
        projectId: string,
        issueId: string,
        limit = 5,
    ): Promise<ApiResponse<{ items: SupportIssueDuplicateSuggestion[] }>> => {
        return apiClient.get(`${p(projectId)}/issues/${encodeURIComponent(issueId)}/duplicate-suggestions?limit=${limit}`);
    },
    getNotifications: async (
        projectId: string,
        status = 'unread',
        limit = 50,
    ): Promise<ApiResponse<{ items: SupportNotification[] }>> => {
        return apiClient.get(`${p(projectId)}/notifications?status=${encodeURIComponent(status)}&limit=${limit}`);
    },
    markNotificationRead: async (
        projectId: string,
        notificationId: string,
    ): Promise<ApiResponse<SupportNotification>> => {
        return apiClient.post(`${p(projectId)}/notifications/${encodeURIComponent(notificationId)}/read`, {});
    },
    createIssue: async (
        projectId: string,
        data: {
            subject?: string;
            fromAddress: string;
            body: string;
            accountId?: string;
            contactId?: string;
            contactName?: string;
            accountName?: string;
            priority?: SupportIssuePriority;
            assigneeEmail?: string;
            queueKey?: string;
            queueName?: string;
        },
    ): Promise<ApiResponse<SupportIssue>> => {
        return apiClient.post(`${p(projectId)}/issues`, data);
    },
    updateIssue: async (
        projectId: string,
        issueId: string,
        data: Partial<Pick<SupportIssue, 'status' | 'priority' | 'assigneeEmail' | 'queueKey' | 'queueName' | 'tags' | 'customFields'>> & { workflowSource?: string },
    ): Promise<ApiResponse<SupportIssue>> => {
        return apiClient.patch(`${p(projectId)}/issues/${encodeURIComponent(issueId)}`, data);
    },
    mergeIssue: async (
        projectId: string,
        sourceIssueId: string,
        targetIssueId: string,
        note = '',
    ): Promise<ApiResponse<SupportIssue>> => {
        return apiClient.post(`${p(projectId)}/issues/${encodeURIComponent(sourceIssueId)}/merge`, { targetIssueId, note });
    },
    splitIssueMessage: async (
        projectId: string,
        sourceIssueId: string,
        data: {
            messageId: string;
            subject?: string;
            note?: string;
            runAutomations?: boolean;
        },
    ): Promise<ApiResponse<SupportIssue>> => {
        return apiClient.post(`${p(projectId)}/issues/${encodeURIComponent(sourceIssueId)}/split-message`, data);
    },
    bulkUpdateIssues: async (
        projectId: string,
        issueIds: string[],
        data: Partial<Pick<SupportIssue, 'status' | 'priority' | 'assigneeEmail' | 'queueKey' | 'queueName' | 'tags' | 'customFields'>> & { workflowSource?: string },
    ): Promise<ApiResponse<{ items: SupportIssue[]; failed: Array<{ id: string; error: string }> }>> => {
        return apiClient.post(`${p(projectId)}/issues/bulk-update`, { issueIds, ...data });
    },
    bulkAddIssueLabels: async (
        projectId: string,
        issueIds: string[],
        tags: string[],
    ): Promise<ApiResponse<{ items: SupportIssue[]; failed: Array<{ id: string; error: string }> }>> => {
        return apiClient.post(`${p(projectId)}/issues/labels/bulk-add`, { issueIds, tags });
    },
    bulkRemoveIssueLabels: async (
        projectId: string,
        issueIds: string[],
        tags: string[],
    ): Promise<ApiResponse<{ items: SupportIssue[]; failed: Array<{ id: string; error: string }> }>> => {
        return apiClient.post(`${p(projectId)}/issues/labels/bulk-remove`, { issueIds, tags });
    },
    bulkApproveIssueReplies: async (
        projectId: string,
        issueIds: string[],
    ): Promise<ApiResponse<SupportBulkApproveSendResult>> => {
        return apiClient.post(`${p(projectId)}/issues/replies/bulk-approve`, { issueIds });
    },
    bulkApproveSendIssueReplies: async (
        projectId: string,
        issueIds: string[],
    ): Promise<ApiResponse<SupportBulkApproveSendResult>> => {
        return apiClient.post(`${p(projectId)}/issues/replies/bulk-approve-send`, { issueIds });
    },
    bulkRequestIssueReplyChanges: async (
        projectId: string,
        issueIds: string[],
        note = '',
    ): Promise<ApiResponse<SupportBulkApproveSendResult>> => {
        return apiClient.post(`${p(projectId)}/issues/replies/bulk-changes`, { issueIds, note });
    },
    bulkApproveIssueActions: async (
        projectId: string,
        issueIds: string[],
    ): Promise<ApiResponse<SupportBulkActionApprovalResult>> => {
        return apiClient.post(`${p(projectId)}/issues/actions/bulk-approve`, { issueIds });
    },
    bulkRejectIssueActions: async (
        projectId: string,
        issueIds: string[],
        note = '',
    ): Promise<ApiResponse<SupportBulkActionApprovalResult>> => {
        return apiClient.post(`${p(projectId)}/issues/actions/bulk-reject`, { issueIds, note });
    },
    bulkRetryFailedIssueReplies: async (
        projectId: string,
        issueIds: string[],
    ): Promise<ApiResponse<SupportBulkApproveSendResult>> => {
        return apiClient.post(`${p(projectId)}/issues/replies/bulk-retry-failed`, { issueIds });
    },
    getSupportQueues: async (projectId: string, status = 'active', includeWorkload = false): Promise<ApiResponse<{ items: SupportQueue[] }>> => {
        const query = new URLSearchParams({ status });
        if (includeWorkload) query.set('include_workload', 'true');
        return apiClient.get(`${p(projectId)}/support/queues?${query.toString()}`);
    },
    saveSupportQueue: async (
        projectId: string,
        data: Pick<SupportQueue, 'name' | 'status'> & {
            queueKey?: string;
            description?: string;
            defaultAssigneeEmail?: string;
            metadata?: Record<string, unknown>;
        },
    ): Promise<ApiResponse<SupportQueue>> => {
        return apiClient.post(`${p(projectId)}/support/queues`, data);
    },
    getInboxViews: async (projectId: string): Promise<ApiResponse<{ items: SupportInboxView[] }>> => {
        return apiClient.get(`${p(projectId)}/support/inbox-views`);
    },
    saveInboxView: async (
        projectId: string,
        data: Pick<SupportInboxView, 'name' | 'visibility'> & {
            id?: string;
            filters?: Record<string, unknown>;
            sortOrder?: number;
        },
    ): Promise<ApiResponse<SupportInboxView>> => {
        return apiClient.post(`${p(projectId)}/support/inbox-views`, data);
    },
    deleteInboxView: async (projectId: string, viewId: string): Promise<ApiResponse<{ status: string }>> => {
        return apiClient.delete(`${p(projectId)}/support/inbox-views/${encodeURIComponent(viewId)}`);
    },
    getReplyMacros: async (
        projectId: string,
        status = 'active',
        limit = 200,
    ): Promise<ApiResponse<{ items: SupportReplyMacro[] }>> => {
        return apiClient.get(`${p(projectId)}/support/reply-macros?status=${encodeURIComponent(status)}&limit=${limit}`);
    },
    saveReplyMacro: async (
        projectId: string,
        data: Pick<SupportReplyMacro, 'title' | 'body' | 'visibility' | 'status'> & {
            id?: string;
            tags?: string[];
            metadata?: Record<string, unknown>;
        },
    ): Promise<ApiResponse<SupportReplyMacro>> => {
        return apiClient.post(`${p(projectId)}/support/reply-macros`, data);
    },
    renderReplyMacro: async (
        projectId: string,
        macroId: string,
        issueId: string,
    ): Promise<ApiResponse<SupportReplyMacroRender>> => {
        return apiClient.post(`${p(projectId)}/support/reply-macros/${encodeURIComponent(macroId)}/render`, { issueId });
    },
    deleteReplyMacro: async (projectId: string, macroId: string): Promise<ApiResponse<SupportReplyMacro>> => {
        return apiClient.delete(`${p(projectId)}/support/reply-macros/${encodeURIComponent(macroId)}`);
    },
    createIssueNote: async (
        projectId: string,
        issueId: string,
        body: string,
    ): Promise<ApiResponse<SupportInternalNote>> => {
        return apiClient.post(`${p(projectId)}/issues/${encodeURIComponent(issueId)}/notes`, { body });
    },
    watchIssue: async (
        projectId: string,
        issueId: string,
    ): Promise<ApiResponse<SupportWatcher>> => {
        return apiClient.post(`${p(projectId)}/issues/${encodeURIComponent(issueId)}/watchers/me`, {});
    },
    unwatchIssue: async (
        projectId: string,
        issueId: string,
    ): Promise<ApiResponse<SupportWatcher>> => {
        return apiClient.delete(`${p(projectId)}/issues/${encodeURIComponent(issueId)}/watchers/me`);
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
        return apiClient.post(`${p(projectId)}/issues/${encodeURIComponent(issueId)}/replies`, {
            body,
            status,
            approvalRequired,
            includeFeedbackLink,
            attachments,
        });
    },
    updateIssueReply: async (
        projectId: string,
        issueId: string,
        replyId: string,
        data: { body?: string; status?: string },
    ): Promise<ApiResponse<SupportOutboundMessage>> => {
        return apiClient.patch(`${p(projectId)}/issues/${encodeURIComponent(issueId)}/replies/${encodeURIComponent(replyId)}`, data);
    },
    sendIssueReply: async (
        projectId: string,
        issueId: string,
        replyId: string,
        forceRetry = false,
    ): Promise<ApiResponse<SupportOutboundMessage>> => {
        return apiClient.post(`${p(projectId)}/issues/${encodeURIComponent(issueId)}/replies/${encodeURIComponent(replyId)}/send`, {
            forceRetry,
        });
    },
    approveIssueReply: async (
        projectId: string,
        issueId: string,
        replyId: string,
    ): Promise<ApiResponse<SupportOutboundMessage>> => {
        return apiClient.post(`${p(projectId)}/issues/${encodeURIComponent(issueId)}/replies/${encodeURIComponent(replyId)}/approve`, {});
    },
    requestIssueReplyChanges: async (
        projectId: string,
        issueId: string,
        replyId: string,
        note: string,
    ): Promise<ApiResponse<SupportOutboundMessage>> => {
        return apiClient.post(`${p(projectId)}/issues/${encodeURIComponent(issueId)}/replies/${encodeURIComponent(replyId)}/changes`, { note });
    },
    reviseIssueReply: async (
        projectId: string,
        issueId: string,
        replyId: string,
        note = '',
        includeFeedbackLink = false,
    ): Promise<ApiResponse<SupportAgentAnswer>> => {
        return apiClient.post(`${p(projectId)}/issues/${encodeURIComponent(issueId)}/replies/${encodeURIComponent(replyId)}/revise`, {
            note,
            includeFeedbackLink,
        });
    },
    createIssueActionExecution: async (
        projectId: string,
        issueId: string,
        data: {
            actionKey: string;
            label: string;
            type?: string;
            status?: string;
            result?: Record<string, unknown>;
            error?: string;
            metadata?: Record<string, unknown>;
        },
    ): Promise<ApiResponse<SupportActionExecution>> => {
        return apiClient.post(`${p(projectId)}/issues/${encodeURIComponent(issueId)}/actions`, data);
    },
    approveIssueActionExecution: async (
        projectId: string,
        issueId: string,
        executionId: string,
    ): Promise<ApiResponse<SupportActionApprovalResult>> => {
        return apiClient.post(`${p(projectId)}/issues/${encodeURIComponent(issueId)}/actions/${encodeURIComponent(executionId)}/approve`, {});
    },
    rejectIssueActionExecution: async (
        projectId: string,
        issueId: string,
        executionId: string,
        note = '',
    ): Promise<ApiResponse<SupportActionApprovalResult>> => {
        return apiClient.post(`${p(projectId)}/issues/${encodeURIComponent(issueId)}/actions/${encodeURIComponent(executionId)}/reject`, { note });
    },
    createIssuePortalSession: async (
        projectId: string,
        issueId: string,
        expiresHours = 168,
    ): Promise<ApiResponse<SupportPortalSession>> => {
        return apiClient.post(`${p(projectId)}/issues/${encodeURIComponent(issueId)}/portal-sessions`, { expiresHours });
    },
    askIssueAgent: async (
        projectId: string,
        issueId: string,
        question: string,
        createDraft = true,
        includeFeedbackLink = false,
        approvalRequired = true,
        autoSend = false,
    ): Promise<ApiResponse<SupportAgentAnswer>> => {
        return apiClient.post(`${p(projectId)}/issues/${encodeURIComponent(issueId)}/agent-chat`, {
            question,
            createDraft,
            includeFeedbackLink,
            approvalRequired,
            autoSend,
        });
    },
    prepareIssueFields: async (
        projectId: string,
        issueId: string,
        approvalRequired = true,
        onlyMissing = true,
    ): Promise<ApiResponse<SupportFieldPreparation>> => {
        return apiClient.post(`${p(projectId)}/issues/${encodeURIComponent(issueId)}/agent-fields`, {
            approvalRequired,
            onlyMissing,
        });
    },
    prepareIssueTriage: async (
        projectId: string,
        issueId: string,
        approvalRequired = true,
    ): Promise<ApiResponse<SupportTriagePreparation>> => {
        return apiClient.post(`${p(projectId)}/issues/${encodeURIComponent(issueId)}/agent-triage`, {
            approvalRequired,
        });
    },

    // ── Accounts (project-scoped) ─────────────────────────────────────────

    getAccounts: async (projectId: string, limit = 100): Promise<ApiResponse<{ items: SupportAccount[] }>> => {
        return apiClient.get(`${p(projectId)}/accounts?limit=${limit}`);
    },
    getAccount: async (projectId: string, accountId: string): Promise<ApiResponse<SupportAccount>> => {
        return apiClient.get(`${p(projectId)}/accounts/${encodeURIComponent(accountId)}`);
    },
    createAccountInsight: async (
        projectId: string,
        accountId: string,
        data: Pick<SupportAccountInsight, 'type' | 'title' | 'body' | 'severity' | 'status'> & {
            sourceIssueId?: string;
            insightKey?: string;
            metadata?: Record<string, unknown>;
        },
    ): Promise<ApiResponse<SupportAccountInsight>> => {
        return apiClient.post(`${p(projectId)}/accounts/${encodeURIComponent(accountId)}/insights`, data);
    },
    generateAccountSummary: async (
        projectId: string,
        accountId: string,
    ): Promise<ApiResponse<SupportAccountInsight>> => {
        return apiClient.post(`${p(projectId)}/accounts/${encodeURIComponent(accountId)}/summary`, {});
    },
    prepareAccountActionPackage: async (
        projectId: string,
        accountId: string,
    ): Promise<ApiResponse<SupportAccountActionPackage>> => {
        return apiClient.post(`${p(projectId)}/accounts/${encodeURIComponent(accountId)}/action-package`, {});
    },
    updateAccountInsight: async (
        projectId: string,
        insightId: string,
        data: Partial<Pick<SupportAccountInsight, 'status' | 'severity' | 'title' | 'body'>>,
    ): Promise<ApiResponse<SupportAccountInsight>> => {
        return apiClient.patch(`${p(projectId)}/accounts/insights/${encodeURIComponent(insightId)}`, data);
    },

    // ── Channels (project-scoped) ─────────────────────────────────────────

    getChannels: async (projectId: string): Promise<ApiResponse<{ items: SupportChannel[] }>> => {
        return apiClient.get(`${p(projectId)}/channels`);
    },
    getChannelActivationBacklog: async (projectId: string): Promise<ApiResponse<SupportChannelActivationBacklog>> => {
        return apiClient.get(`${p(projectId)}/channels/activation-backlog`);
    },
    getChannelActivationPlan: async (projectId: string): Promise<ApiResponse<SupportChannelActivationPlan>> => {
        return apiClient.get(`${p(projectId)}/channels/activation-plan`);
    },
    bootstrapChannelActivationBacklog: async (
        projectId: string,
        data: { surfaces?: string[]; status?: string } = {},
    ): Promise<ApiResponse<SupportChannelActivationBootstrapResult>> => {
        return apiClient.post(`${p(projectId)}/channels/activation-backlog/bootstrap`, data);
    },
    activateReadyChannelActivationBacklog: async (
        projectId: string,
        data: { surfaces?: string[] } = {},
    ): Promise<ApiResponse<SupportChannelActivationReadyResult>> => {
        return apiClient.post(`${p(projectId)}/channels/activation-backlog/activate-ready`, data);
    },
    getChannelPresets: async (projectId: string): Promise<ApiResponse<{ items: SupportChannelPreset[] }>> => {
        return apiClient.get(`${p(projectId)}/channels/presets`);
    },
    saveChannel: async (
        projectId: string,
        data: Pick<SupportChannel, 'type' | 'name' | 'status'> & { channelKey?: string; config?: Record<string, unknown> },
    ): Promise<ApiResponse<SupportChannel>> => {
        return apiClient.post(`${p(projectId)}/channels`, data);
    },
    validateChannelSetup: async (
        projectId: string,
        channelId: string,
    ): Promise<ApiResponse<SupportChannelValidation>> => {
        return apiClient.post(`${p(projectId)}/channels/${encodeURIComponent(channelId)}/validate`, {});
    },
    createSlackInstallUrl: async (
        projectId: string,
        data: { channelKey?: string; name?: string; scopes?: string },
    ): Promise<ApiResponse<SlackInstallUrlResult>> => {
        return apiClient.post(`${p(projectId)}/channels/slack/install-url`, data);
    },
    configureTelegramWebhook: async (
        projectId: string,
        channelId: string,
        data: { allowedUpdates?: string[]; dropPendingUpdates?: boolean } = {},
    ): Promise<ApiResponse<TelegramWebhookResult>> => {
        return apiClient.post(`${p(projectId)}/channels/${encodeURIComponent(channelId)}/telegram/webhook`, data);
    },
    runSupportDelivery: async (
        projectId: string,
        limit = 25,
        retryFailed = false,
    ): Promise<ApiResponse<SupportDeliveryRun>> => {
        return apiClient.post(`${p(projectId)}/support/delivery/run?limit=${limit}&retry_failed=${retryFailed ? 'true' : 'false'}`, {});
    },
    runSlaEscalations: async (projectId: string, limit = 100): Promise<ApiResponse<SupportSlaEscalationRun>> => {
        return apiClient.post(`${p(projectId)}/support/sla/run?limit=${limit}`, {});
    },
    getSupportDeliveryRuns: async (
        projectId: string,
        limit = 25,
    ): Promise<ApiResponse<{ items: SupportDeliveryRunRecord[] }>> => {
        return apiClient.get(`${p(projectId)}/support/delivery/runs?limit=${limit}`);
    },
    syncChannel: async (projectId: string, channelId: string, limit = 25): Promise<ApiResponse<SupportChannelSyncResult>> => {
        return apiClient.post(`${p(projectId)}/channels/${encodeURIComponent(channelId)}/sync?limit=${limit}`, {});
    },
    testChannelMessage: async (
        projectId: string,
        channelId: string,
        data: {
            body: string;
            authorName?: string;
            authorEmail?: string;
            channelId?: string;
            threadId?: string;
            messageId?: string;
            attachments?: Array<Record<string, unknown>>;
        },
    ): Promise<ApiResponse<SupportChannelTestMessageResult>> => {
        return apiClient.post(`${p(projectId)}/channels/${encodeURIComponent(channelId)}/test-message`, data);
    },
    smokeChannel: async (
        projectId: string,
        channelId: string,
        data: {
            body: string;
            authorName?: string;
            authorEmail?: string;
            channelId?: string;
            threadId?: string;
            messageId?: string;
            attachments?: Array<Record<string, unknown>>;
            transport?: 'direct' | 'http';
        },
    ): Promise<ApiResponse<SupportChannelSmokeResult>> => {
        return apiClient.post(`${p(projectId)}/channels/${encodeURIComponent(channelId)}/smoke`, data);
    },
    smokeChannelOutbound: async (
        projectId: string,
        channelId: string,
        data: {
            body: string;
            channelId?: string;
            threadId?: string;
            messageId?: string;
            providerMessageId?: string;
            toAddress?: string;
            fromAddress?: string;
            subject?: string;
            conversationId?: string;
            replyToId?: string;
            serviceUrl?: string;
        },
    ): Promise<ApiResponse<SupportChannelOutboundSmokeResult>> => {
        return apiClient.post(`${p(projectId)}/channels/${encodeURIComponent(channelId)}/outbound-smoke`, data);
    },
    smokeChannelLifecycle: async (
        projectId: string,
        channelId: string,
        data: {
            body: string;
            replyBody: string;
            authorName?: string;
            authorEmail?: string;
            fromAddress?: string;
            channelId?: string;
            threadId?: string;
            messageId?: string;
            eventId?: string;
            attachments?: Array<Record<string, unknown>>;
            transport?: 'direct' | 'http';
        },
    ): Promise<ApiResponse<SupportChannelLifecycleSmokeResult>> => {
        return apiClient.post(`${p(projectId)}/channels/${encodeURIComponent(channelId)}/lifecycle-smoke`, data);
    },
    smokeChannels: async (
        projectId: string,
        data: {
            body: string;
            authorName?: string;
            authorEmail?: string;
            channelId?: string;
            threadId?: string;
            messageId?: string;
            attachments?: Array<Record<string, unknown>>;
            transport?: 'direct' | 'http';
        },
    ): Promise<ApiResponse<SupportChannelSmokeRun>> => {
        return apiClient.post(`${p(projectId)}/channels/smoke/run`, data);
    },
    smokeChannelsOutbound: async (
        projectId: string,
        data: {
            body: string;
            channelId?: string;
            threadId?: string;
            messageId?: string;
            providerMessageId?: string;
            toAddress?: string;
            fromAddress?: string;
            subject?: string;
        },
    ): Promise<ApiResponse<SupportChannelOutboundSmokeRun>> => {
        return apiClient.post(`${p(projectId)}/channels/outbound-smoke/run`, data);
    },
    smokeChannelsLifecycle: async (
        projectId: string,
        data: {
            body: string;
            replyBody: string;
            authorName?: string;
            authorEmail?: string;
            fromAddress?: string;
            channelId?: string;
            threadId?: string;
            messageId?: string;
            eventId?: string;
            attachments?: Array<Record<string, unknown>>;
            transport?: 'direct' | 'http';
        },
    ): Promise<ApiResponse<SupportChannelLifecycleSmokeRun>> => {
        return apiClient.post(`${p(projectId)}/channels/lifecycle-smoke/run`, data);
    },
    syncChannels: async (projectId: string, limit = 25): Promise<ApiResponse<SupportChannelsSyncRun>> => {
        return apiClient.post(`${p(projectId)}/channels/sync/run?limit=${limit}`, {});
    },
    getChannelSyncRuns: async (
        projectId: string,
        channelId = '',
        limit = 25,
    ): Promise<ApiResponse<{ items: SupportChannelSyncRunRecord[] }>> => {
        const query = new URLSearchParams({ limit: String(limit) });
        if (channelId) query.set('channel_id', channelId);
        return apiClient.get(`${p(projectId)}/channels/sync/runs?${query.toString()}`);
    },
    getChannelCursors: async (
        projectId: string,
        channelId = '',
        limit = 100,
    ): Promise<ApiResponse<{ items: SupportChannelCursor[] }>> => {
        const query = new URLSearchParams({ limit: String(limit) });
        if (channelId) query.set('channel_id', channelId);
        return apiClient.get(`${p(projectId)}/channels/cursors?${query.toString()}`);
    },
    getChannelWebhookEvents: async (
        projectId: string,
        channelId = '',
        status = '',
        limit = 25,
    ): Promise<ApiResponse<{ items: SupportChannelWebhookEvent[] }>> => {
        const query = new URLSearchParams({ limit: String(limit) });
        if (channelId) query.set('channel_id', channelId);
        if (status) query.set('status', status);
        return apiClient.get(`${p(projectId)}/channels/webhook-events?${query.toString()}`);
    },
    rematchChannelWebhookEvent: async (
        projectId: string,
        eventId: string,
        data: { outboundMessageId?: string } = {},
    ): Promise<ApiResponse<SupportChannelWebhookEvent>> => {
        return apiClient.post(
            `${p(projectId)}/channels/webhook-events/${encodeURIComponent(eventId)}/rematch`,
            data,
        );
    },
    getWebChatSessions: async (
        projectId: string,
        channelId = '',
        status = '',
        limit = 25,
    ): Promise<ApiResponse<{ items: SupportWebChatSession[] }>> => {
        const query = new URLSearchParams({ limit: String(limit) });
        if (channelId) query.set('channel_id', channelId);
        if (status) query.set('status', status);
        return apiClient.get(`${p(projectId)}/channels/web-chat/sessions?${query.toString()}`);
    },
    getCrmConnectors: async (projectId: string): Promise<ApiResponse<{ items: SupportCrmConnector[] }>> => {
        return apiClient.get(`${p(projectId)}/crm/connectors`);
    },
    saveCrmConnector: async (
        projectId: string,
        data: Pick<SupportCrmConnector, 'provider' | 'name' | 'status'> & {
            connectorKey?: string;
            config?: Record<string, unknown>;
        },
    ): Promise<ApiResponse<SupportCrmConnector>> => {
        return apiClient.post(`${p(projectId)}/crm/connectors`, data);
    },
    syncCrmConnector: async (
        projectId: string,
        connectorId: string,
        limit = 25,
    ): Promise<ApiResponse<SupportCrmSyncResult>> => {
        return apiClient.post(`${p(projectId)}/crm/connectors/${encodeURIComponent(connectorId)}/sync?limit=${limit}`, {});
    },
    validateCrmConnector: async (
        projectId: string,
        connectorId: string,
    ): Promise<ApiResponse<SupportCrmValidation>> => {
        return apiClient.post(`${p(projectId)}/crm/connectors/${encodeURIComponent(connectorId)}/validate`, {});
    },
    syncCrmConnectors: async (projectId: string, limit = 25): Promise<ApiResponse<SupportCrmConnectorsSyncRun>> => {
        return apiClient.post(`${p(projectId)}/crm/connectors/sync/run?limit=${limit}`, {});
    },
    getCrmSyncRuns: async (
        projectId: string,
        connectorId = '',
        limit = 25,
    ): Promise<ApiResponse<{ items: SupportCrmSyncRunRecord[] }>> => {
        const query = new URLSearchParams({ limit: String(limit) });
        if (connectorId) query.set('connector_id', connectorId);
        return apiClient.get(`${p(projectId)}/crm/connectors/sync/runs?${query.toString()}`);
    },
    getCrmWebhookEvents: async (
        projectId: string,
        connectorId = '',
        status = '',
        limit = 25,
    ): Promise<ApiResponse<{ items: SupportCrmWebhookEvent[] }>> => {
        const query = new URLSearchParams({ limit: String(limit) });
        if (connectorId) query.set('connector_id', connectorId);
        if (status) query.set('status', status);
        return apiClient.get(`${p(projectId)}/crm/connectors/webhook-events?${query.toString()}`);
    },

    // ── Automations (project-scoped) ──────────────────────────────────────

    getAutomationRules: async (projectId: string): Promise<ApiResponse<{ items: SupportAutomationRule[] }>> => {
        return apiClient.get(`${p(projectId)}/automations`);
    },
    saveAutomationRule: async (
        projectId: string,
        data: Pick<SupportAutomationRule, 'name' | 'active' | 'trigger' | 'conditions' | 'actions'> & { id?: string },
    ): Promise<ApiResponse<SupportAutomationRule>> => {
        const body = {
            name: data.name,
            active: data.active,
            trigger: data.trigger,
            conditions: data.conditions,
            actions: data.actions,
        };
        if (data.id) {
            return apiClient.patch(`${p(projectId)}/automations/${encodeURIComponent(data.id)}`, body);
        }
        return apiClient.post(`${p(projectId)}/automations`, body);
    },
    getAutomationRuns: async (
        projectId: string,
        ruleId = '',
        issueId = '',
        limit = 50,
    ): Promise<ApiResponse<{ items: SupportAutomationRun[] }>> => {
        const query = new URLSearchParams({ limit: String(limit) });
        if (ruleId) query.set('rule_id', ruleId);
        if (issueId) query.set('issue_id', issueId);
        return apiClient.get(`${p(projectId)}/automations/runs?${query.toString()}`);
    },
    runAutomations: async (
        projectId: string,
        issueId: string,
        trigger: string = 'manual',
    ): Promise<ApiResponse<SupportAutomationsRunResult>> => {
        return apiClient.post(`${p(projectId)}/automations/run`, { issueId, trigger });
    },
    runAutomationBacklog: async (
        projectId: string,
        data: {
            trigger?: string;
            status?: string;
            queueKey?: string;
            limit?: number;
        },
    ): Promise<ApiResponse<SupportAutomationBacklogRunResult>> => {
        return apiClient.post(`${p(projectId)}/automations/run/backlog`, data);
    },
    previewAutomations: async (
        projectId: string,
        issueId: string,
        trigger: string = 'manual',
        previewRule?: Pick<SupportAutomationRule, 'name' | 'active' | 'trigger' | 'conditions' | 'actions'> & { id?: string },
    ): Promise<ApiResponse<SupportAutomationPreviewResult>> => {
        return apiClient.post(`${p(projectId)}/automations/preview`, { issueId, trigger, previewRule });
    },
    setupHumanLoopAutomation: async (projectId: string): Promise<ApiResponse<SupportHumanLoopAutomationSetupResult>> => {
        return apiClient.post(`${p(projectId)}/automations/human-loop/setup`, {});
    },

    // ── Knowledge (project-scoped) ────────────────────────────────────────

    getKnowledgeArticles: async (projectId: string, status = 'all'): Promise<ApiResponse<{ items: KnowledgeArticle[] }>> => {
        return apiClient.get(`${p(projectId)}/knowledge?status=${encodeURIComponent(status)}`);
    },
    getKnowledgeArticle: async (projectId: string, articleId: string): Promise<ApiResponse<KnowledgeArticle>> => {
        return apiClient.get(`${p(projectId)}/knowledge/${encodeURIComponent(articleId)}`);
    },
    getKnowledgeGaps: async (projectId: string, status = 'open'): Promise<ApiResponse<{ items: KnowledgeGap[] }>> => {
        return apiClient.get(`${p(projectId)}/knowledge/gaps?status=${encodeURIComponent(status)}`);
    },
    updateKnowledgeGap: async (
        projectId: string,
        gapId: string,
        data: Partial<Pick<KnowledgeGap, 'status' | 'severity' | 'title' | 'evidence' | 'suggestedArticleTitle'>>,
    ): Promise<ApiResponse<KnowledgeGap>> => {
        return apiClient.patch(`${p(projectId)}/knowledge/gaps/${encodeURIComponent(gapId)}`, data);
    },
    createArticleFromKnowledgeGap: async (
        projectId: string,
        gapId: string,
        status = 'draft',
    ): Promise<ApiResponse<KnowledgeArticle>> => {
        return apiClient.post(`${p(projectId)}/knowledge/gaps/${encodeURIComponent(gapId)}/article`, { status });
    },
    createKnowledgeArticle: async (
        projectId: string,
        data: {
            title: string;
            body: string;
            status?: string;
            sourceIssueId?: string;
            sourceGapId?: string;
            sourceUrl?: string;
            visibility?: string;
            automationAllowed?: boolean;
            tags?: string[];
        },
    ): Promise<ApiResponse<KnowledgeArticle>> => {
        return apiClient.post(`${p(projectId)}/knowledge`, data);
    },
    updateKnowledgeArticle: async (
        projectId: string,
        articleId: string,
        data: Partial<Pick<KnowledgeArticle, 'title' | 'body' | 'status' | 'tags' | 'sourceIssueId' | 'sourceUrl' | 'visibility' | 'public' | 'automationAllowed' | 'reviewStatus' | 'lastReviewedAt' | 'reviewDueAt'>>,
    ): Promise<ApiResponse<KnowledgeArticle>> => {
        return apiClient.patch(`${p(projectId)}/knowledge/${encodeURIComponent(articleId)}`, data);
    },

    // ── Support analytics (project-scoped) ────────────────────────────────

    getSupportAnalytics: async (projectId: string): Promise<ApiResponse<SupportAnalytics>> => {
        return apiClient.get(`${p(projectId)}/support/analytics`);
    },

    getSupportLaunchProof: async (projectId: string): Promise<ApiResponse<SupportLaunchProof>> => {
        return apiClient.get(`${p(projectId)}/support/launch-proof`);
    },

    runSupportWorkflowProof: async (projectId: string): Promise<ApiResponse<SupportWorkflowProofRunResult>> => {
        return apiClient.post(`${p(projectId)}/support/workflow-proof/run`, {});
    },

    runSupportAutomationProof: async (projectId: string): Promise<ApiResponse<SupportAutomationProofRunResult>> => {
        return apiClient.post(`${p(projectId)}/support/automation-proof/run`, {});
    },

    runSupportLaunchProof: async (projectId: string): Promise<ApiResponse<SupportLaunchProofRunResult>> => {
        return apiClient.post(`${p(projectId)}/support/launch-proof/run`, {});
    },

    getSupportLaunchProofRuns: async (projectId: string, limit = 10): Promise<ApiResponse<SupportLaunchProofRunsResponse>> => {
        return apiClient.get(`${p(projectId)}/support/launch-proof/runs?limit=${encodeURIComponent(String(limit))}`);
    },

    getSupportSchemaHealth: async (projectId: string): Promise<ApiResponse<SupportSchemaHealth>> => {
        return apiClient.get(`${p(projectId)}/support/schema-health`);
    },

    getSlaPolicy: async (projectId: string): Promise<ApiResponse<SupportSlaPolicy>> => {
        return apiClient.get(`${p(projectId)}/support/sla-policy`);
    },
    updateSlaPolicy: async (
        projectId: string,
        data: Pick<SupportSlaPolicy, 'name' | 'active' | 'firstResponseMinutes' | 'resolutionMinutes' | 'businessHours' | 'metadata'>,
    ): Promise<ApiResponse<SupportSlaPolicy>> => {
        return apiClient.patch(`${p(projectId)}/support/sla-policy`, data);
    },

    getMonitorSummary: async (projectId: string): Promise<ApiResponse<MonitorSummary>> => {
        return apiClient.get(`${p(projectId)}/monitor/summary`);
    },
    getMonitorRuns: async (projectId: string, limit = 50): Promise<ApiResponse<{ items: MonitorRun[] }>> => {
        return apiClient.get(`${p(projectId)}/monitor/runs?limit=${limit}`);
    },

    // ── Manifest download — project-scoped ──────────────────────────────────

    downloadManifest: async (projectId: string, baseUrl?: string): Promise<void> => {
        const token = localStorage.getItem('admin_auth_token');
        const headers: Record<string, string> = {};
        if (token) headers['Authorization'] = `Bearer ${token}`;
        const params = baseUrl ? `?base_url=${encodeURIComponent(baseUrl)}` : '';
        const response = await fetch(`${settings.apiBaseUrl}${p(projectId)}/manifest${params}`, { headers });
        if (!response.ok) throw new Error(`Failed: ${response.status}`);
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = 'manifest.xml';
        document.body.appendChild(a); a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    },

    // ── Evaluation (project-scoped) ─────────────────────────────────────────

    /** Eval sets */
    getEvalSets: async (projectId: string): Promise<ApiResponse<EvalSet[]>> => {
        return apiClient.get(`${p(projectId)}/eval/sets`);
    },
    getEvalSet: async (projectId: string, setId: string): Promise<ApiResponse<EvalSet>> => {
        return apiClient.get(`${p(projectId)}/eval/sets/${setId}`);
    },
    createEvalSet: async (projectId: string, name: string, description: string): Promise<ApiResponse<{ id: string; name: string }>> => {
        return apiClient.post(`${p(projectId)}/eval/sets`, { name, description });
    },
    updateEvalSet: async (projectId: string, setId: string, data: { name?: string; description?: string }): Promise<ApiResponse<unknown>> => {
        return apiClient.put(`${p(projectId)}/eval/sets/${setId}`, data);
    },
    deleteEvalSet: async (projectId: string, setId: string): Promise<ApiResponse<unknown>> => {
        return apiClient.delete(`${p(projectId)}/eval/sets/${setId}`);
    },

    /** Eval cases */
    getEvalCases: async (projectId: string, setId: string): Promise<ApiResponse<EvalCase[]>> => {
        return apiClient.get(`${p(projectId)}/eval/sets/${setId}/cases`);
    },
    createEvalCase: async (projectId: string, setId: string, data: EvalCaseInput): Promise<ApiResponse<{ id: string; name: string }>> => {
        return apiClient.post(`${p(projectId)}/eval/sets/${setId}/cases`, data);
    },
    updateEvalCase: async (projectId: string, caseId: string, data: Partial<EvalCaseInput>): Promise<ApiResponse<unknown>> => {
        return apiClient.put(`${p(projectId)}/eval/cases/${caseId}`, data);
    },
    deleteEvalCase: async (projectId: string, caseId: string): Promise<ApiResponse<unknown>> => {
        return apiClient.delete(`${p(projectId)}/eval/cases/${caseId}`);
    },

    /** Eval runs */
    getEvalRuns: async (projectId: string, setId: string): Promise<ApiResponse<EvalRun[]>> => {
        return apiClient.get(`${p(projectId)}/eval/runs?set_id=${setId}`);
    },
    getEvalRun: async (projectId: string, runId: string): Promise<ApiResponse<EvalRunDetail>> => {
        return apiClient.get(`${p(projectId)}/eval/runs/${runId}`);
    },
    triggerEvalRun: async (projectId: string, setId: string): Promise<ApiResponse<{ runId: string; status: string }>> => {
        return apiClient.post(`${p(projectId)}/eval/sets/${setId}/run`, {});
    },
    deleteEvalRun: async (projectId: string, runId: string): Promise<ApiResponse<unknown>> => {
        return apiClient.delete(`${p(projectId)}/eval/runs/${runId}`);
    },

    // ── Billing (SaaS only, root only) ──────────────────────────────────────

    getBillingStatus: async (): Promise<ApiResponse<BillingStatus>> => {
        return apiClient.get('/api/admin/billing/status');
    },
    createCheckoutSession: async (
        successUrl: string,
        cancelUrl: string,
        plan: 'pro' | 'business' = 'pro',
    ): Promise<ApiResponse<{ url: string }>> => {
        return apiClient.post('/api/admin/billing/checkout', {
            success_url: successUrl,
            cancel_url: cancelUrl,
            plan,
        });
    },
    createPortalSession: async (returnUrl: string): Promise<ApiResponse<{ url: string }>> => {
        return apiClient.post('/api/admin/billing/portal', {
            return_url: returnUrl,
        });
    },

    // ── License status (on-prem) ────────────────────────────────────────────

    getLicenseStatus: async (): Promise<ApiResponse<LicenseStatus>> => {
        return apiClient.get('/api/admin/license/status');
    },
};

export default api;
