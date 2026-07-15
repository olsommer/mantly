interface Brand {
    name: string;
    shortName: string;
    adminTitle: string;
    addinDisplayName: string;
    providerName: string;
    description: string;
    descriptionDe: string;
    supportEmail: string;
    supportUrl: string;
}

declare const __APP_BRAND__: Brand;

export const brand = __APP_BRAND__;
