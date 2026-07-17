
// Email interface
export interface Email {
    id: string;
    fromAddress: string;
    subject: string;
    body: string;
    bodyHtml?: string;
    threadId?: string;
    messageId?: string;
    internetMessageId?: string;
    inReplyTo?: string;
    references?: string[];
    attachments?: { filename: string; base64: string }[];
}

// ── v3 pipeline types ────────────────────────────────────────────────────────

export interface IntentAction {
    name: string;
    label: string;
    type?: 'dropdown' | 'calendar' | 'input' | 'button';
    description?: string;
    options?: string[];
    separateCall?: boolean;
    webhook?: string;
    method: string;
    payload?: Record<string, unknown>;
    query?: Record<string, unknown>;
    body?: Record<string, unknown>;
    headers?: Record<string, string>;
    initialValue?: string | null;
}

export interface IntentResponseConfig {
    enabled: boolean;
    auto: boolean;
}

export interface RunbookOutcome {
    concernId: string;
    concernSummary?: string;
    matched: boolean;
    intentName?: string;
    actions: IntentAction[];
}

export interface IdentityResult {
    customerFound: boolean;
    data: Record<string, unknown>;
    toolCallsMade: string[];
    error?: string;
}

export interface IntentResult {
    matched: boolean;
    intentName?: string;
    actions: IntentAction[];
    response?: IntentResponseConfig;
    concerns?: RunbookOutcome[];
    error?: string;
}

export interface PhishingResult {
    enabled: boolean;
    riskLevel: 'none' | 'low' | 'medium' | 'high';
    score: number;
    indicators: string[];
    reason: string;
    checkedAt: string;
    error?: string;
}

export interface PromptInjectionResult {
    enabled: boolean;
    riskLevel: 'none' | 'low' | 'medium' | 'high';
    score: number;
    indicators: string[];
    reason: string;
    checkedAt: string;
    error?: string;
}

export interface TokenUsageCall {
    stage: string;
    provider: string;
    model: string;
    inputTokens: number | null;
    outputTokens: number | null;
    cachedInputTokens: number | null;
    totalTokens: number | null;
    metadataAvailable: boolean;
    rawUsage?: Record<string, unknown>;
}

export interface TokenUsage {
    inputTokens: number | null;
    outputTokens: number | null;
    cachedInputTokens: number | null;
    totalTokens: number | null;
    calls: TokenUsageCall[];
    metadataAvailable: boolean;
}

// ─────────────────────────────────────────────────────────────────────────────

export interface EmailResponse {
    emailBody: string;
    emailAttachments?: { filename: string; base64: string; contentType?: string }[];
    requiresHuman: boolean;
    requiresHumanReason?: string;
    // v3 pipeline results (optional — absent in cached v2 chats)
    identityResult?: IdentityResult;
    intentResult?: IntentResult;
    phishingResult?: PhishingResult;
    promptInjectionResult?: PromptInjectionResult;
    tokenUsage?: TokenUsage;
    activatedIntent?: string;
}

export interface ChatMember {
    email: string;
    name: string;
    role: 'supervisor' | 'user';
}

export type Message = ({
    role: 'email' | 'ai' | 'user';
    user: string;
    content: string;
} | {
    role: 'response';
    user: 'response';
    content: EmailResponse;
})
