export interface AppSettings {
    apiBaseUrl: string;
    adminBaseUrl: string;
    pbBaseUrl: string;
    environment: 'development' | 'production';
    isMockMode: boolean; // Allow running in browser without Outlook
    enableDemoScenarios: boolean; // Explicitly enable scenario-driven demo data
    enableAdminPreview: boolean; // Explicitly enable admin draft preview/embed mode
    requireAuth: boolean; // Show login screen and send JWT on every request
}

const readEnvString = (key: string): string | undefined => {
    const value = (import.meta.env as Record<string, unknown>)[key];
    return typeof value === 'string' ? value : undefined;
};

/**
 * Get API base URL based on environment
 * - Development: Uses localhost
 * - Production: Uses HTTPS endpoint
 */
const getApiBaseUrl = (): string => {
    // Check if we're in development mode
    const isDevelopment = import.meta.env.DEV || import.meta.env.MODE === 'development';
    const envOverride = readEnvString('VITE_API_URL');

    if (envOverride) {
        return envOverride;
    }

    if (isDevelopment) {
        // Use localhost in development
        return 'http://localhost:8080';
    } else {
        // Use production HTTPS endpoint
        return typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8080';
    }
};

const getAdminBaseUrl = (): string => {
    const envOverride = readEnvString('VITE_ADMIN_URL');

    if (envOverride) {
        return envOverride;
    }

    if (isDevelopment) {
        return 'http://localhost:5174';
    }

    if (typeof window !== 'undefined' && window.location.hostname === 'addin.mantly.io') {
        return 'https://app.mantly.io';
    }

    return typeof window !== 'undefined' ? window.location.origin : 'http://localhost:5174';
};

const isDevelopment = import.meta.env.DEV || import.meta.env.MODE === 'development';
const demoModeRequested =
    import.meta.env.VITE_ENABLE_DEMO_MODE === 'true'
    || import.meta.env.VITE_ENABLE_DEMO_SCENARIOS === 'true';

/**
 * Application settings
 * Automatically configures based on environment
 */
export const settings: AppSettings = {
    apiBaseUrl: getApiBaseUrl(),
    adminBaseUrl: getAdminBaseUrl(),
    pbBaseUrl: readEnvString('VITE_PB_URL') ?? 'http://localhost:8090',
    environment: isDevelopment ? 'development' : 'production',
    isMockMode: import.meta.env.VITE_ENABLE_MOCK_MODE === 'true',
    enableDemoScenarios: isDevelopment && demoModeRequested,
    // Keep admin preview available in production-like environments unless it
    // is explicitly disabled. This is separate from demo scenario data.
    enableAdminPreview: import.meta.env.VITE_ENABLE_ADMIN_PREVIEW !== 'false',
    requireAuth: import.meta.env.VITE_REQUIRE_AUTH === 'true',
};

/**
 * Update settings at runtime (useful for testing or dynamic configuration)
 */
export const updateSettings = (newSettings: Partial<AppSettings>) => {
    Object.assign(settings, newSettings);
};

/**
 * Get current settings
 */
export const getSettings = (): Readonly<AppSettings> => {
    return { ...settings };
};
