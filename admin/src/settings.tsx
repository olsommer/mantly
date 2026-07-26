export interface AppSettings {
    apiBaseUrl: string;
    pbBaseUrl: string;
    addinBaseUrl: string;
    environment: 'development' | 'production';
    isMockMode: boolean;
    requireAuth: boolean;
    enablePreview: boolean;
    enableDemoMode: boolean;
    isSaas: boolean;
    sourceUrl: string;
}

const getApiBaseUrl = (): string => {
    const isDevelopment = import.meta.env.DEV || import.meta.env.MODE === 'development';
    const envOverride = readEnvString('VITE_API_URL');
    if (envOverride) {
        return envOverride;
    }
    if (isDevelopment) {
        return 'http://localhost:8080';
    } else {
        return typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8080';
    }
};

const getPbBaseUrl = (): string => {
    const isDevelopment = import.meta.env.DEV || import.meta.env.MODE === 'development';
    if (isDevelopment) {
        return readEnvString('VITE_PB_URL') ?? 'http://localhost:8090';
    } else {
        return readEnvString('VITE_PB_URL') ?? 'http://localhost:8090';
    }
};

const getAddinBaseUrl = (): string => {
    const envOverride = readEnvString('VITE_ADDIN_URL');
    if (envOverride) {
        return envOverride.replace(/\/+$/, '');
    }

    if (import.meta.env.DEV) {
        const protocol = typeof window !== 'undefined' ? window.location.protocol : 'http:';
        const host = typeof window !== 'undefined' ? window.location.hostname || 'localhost' : 'localhost';
        return `${protocol}//${host}:5173`;
    }

    return typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8080';
};

const readEnvString = (key: string): string | undefined => {
    const value = (import.meta.env as Record<string, unknown>)[key];
    return typeof value === 'string' ? value : undefined;
};

export const settings: AppSettings = {
    apiBaseUrl: getApiBaseUrl(),
    pbBaseUrl: getPbBaseUrl(),
    addinBaseUrl: getAddinBaseUrl(),
    environment: (import.meta.env.DEV || import.meta.env.MODE === 'development')
        ? 'development'
        : 'production',
    isMockMode: false,
    requireAuth: import.meta.env.VITE_REQUIRE_AUTH === 'true',
    // Preview is an authenticated admin workflow and should stay available
    // outside local dev unless it is explicitly disabled at build time.
    enablePreview: import.meta.env.VITE_ENABLE_ADMIN_PREVIEW !== 'false',
    enableDemoMode: import.meta.env.VITE_ENABLE_DEMO_MODE === 'true',
    isSaas: import.meta.env.VITE_IS_SAAS === 'true',
    sourceUrl: readEnvString('VITE_SOURCE_URL') ?? 'https://github.com/olsommer/mantly',
};
