export type SeoLanguage = "en" | "de";

export type LandingPage = "home" | "privacy" | "imprint" | "terms" | "support" | "pilot";

export const landingRoutes: Record<LandingPage, Record<SeoLanguage, string>> = {
  home: { en: "/en/", de: "/de/" },
  privacy: { en: "/en/privacy", de: "/de/datenschutz" },
  imprint: { en: "/en/imprint", de: "/de/impressum" },
  terms: { en: "/en/terms", de: "/de/nutzungsbedingungen" },
  support: { en: "/en/support", de: "/de/hilfe" },
  pilot: { en: "/en/page", de: "/de/page" },
};

export const landingMetadata: Record<
  SeoLanguage,
  Record<LandingPage, { title: string; description: string }>
> = {
  en: {
    home: {
      title: "Mantly — Open-Source Agentic Customer Support",
      description:
        "Mantly is an open-source agentic customer support platform for connected channels. Self-host it or use Mantly Cloud.",
    },
    privacy: {
      title: "Privacy Policy — Mantly",
      description: "How IsarAI processes personal data when providing Mantly services.",
    },
    imprint: {
      title: "Imprint — Mantly",
      description: "Provider and legal contact information for Mantly.",
    },
    terms: {
      title: "Terms of Use — Mantly",
      description: "Terms governing Mantly Cloud and services operated by IsarAI.",
    },
    support: {
      title: "Support — Mantly",
      description: "Contact Mantly support for product, account, billing, or security questions.",
    },
    pilot: {
      title: "Pilot Playbook — Mantly",
      description: "A focused operating plan for proving one agentic support workflow with Mantly.",
    },
  },
  de: {
    home: {
      title: "Mantly — Open-Source-Kundensupport mit KI-Agenten",
      description:
        "Mantly ist eine Open-Source-Plattform für agentenbasierten Kundensupport über verbundene Kanäle. Self-hosted oder in der Mantly Cloud.",
    },
    privacy: {
      title: "Datenschutz — Mantly",
      description: "Informationen zur Verarbeitung personenbezogener Daten bei Mantly-Diensten.",
    },
    imprint: {
      title: "Impressum — Mantly",
      description: "Anbieterkennzeichnung und rechtliche Kontaktinformationen für Mantly.",
    },
    terms: {
      title: "Nutzungsbedingungen — Mantly",
      description: "Bedingungen für Mantly Cloud und von IsarAI betriebene Dienste.",
    },
    support: {
      title: "Support — Mantly",
      description: "Mantly Support für Produkt-, Konto-, Abrechnungs- und Sicherheitsfragen.",
    },
    pilot: {
      title: "Pilot Playbook — Mantly",
      description: "Ein fokussierter Plan für den Nachweis eines agentischen Support-Workflows mit Mantly.",
    },
  },
};
