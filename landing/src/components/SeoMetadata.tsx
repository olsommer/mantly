import { useEffect } from "react";
import { useTranslation } from "@/i18n/useTranslation";
import type { Language } from "@/i18n/translations";

export type LandingPage = "home" | "privacy" | "imprint" | "terms" | "support" | "pilot";

const routes: Record<LandingPage, Record<Language, string>> = {
  home: { en: "/en/", de: "/de/" },
  privacy: { en: "/en/privacy", de: "/de/datenschutz" },
  imprint: { en: "/en/imprint", de: "/de/impressum" },
  terms: { en: "/en/terms", de: "/de/nutzungsbedingungen" },
  support: { en: "/en/support", de: "/de/hilfe" },
  pilot: { en: "/en/page", de: "/de/page" },
};

const metadata: Record<Language, Record<LandingPage, { title: string; description: string }>> = {
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
      title: "Mantly — Agentischer Open-Source-Kundensupport",
      description:
        "Mantly ist eine Open-Source-Plattform für agentischen Kundensupport über verbundene Kanäle. Self-hosted oder in der Mantly Cloud.",
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

function setMeta(selector: string, attributes: Record<string, string>) {
  let element = document.head.querySelector<HTMLMetaElement>(selector);
  if (!element) {
    element = document.createElement("meta");
    document.head.appendChild(element);
  }
  Object.entries(attributes).forEach(([name, value]) => element?.setAttribute(name, value));
}

function setLink(selector: string, attributes: Record<string, string>) {
  let element = document.head.querySelector<HTMLLinkElement>(selector);
  if (!element) {
    element = document.createElement("link");
    document.head.appendChild(element);
  }
  Object.entries(attributes).forEach(([name, value]) => element?.setAttribute(name, value));
}

export function SeoMetadata({ page }: { page: LandingPage }) {
  const { lang } = useTranslation();

  useEffect(() => {
    const pageMetadata = metadata[lang][page];
    const canonicalUrl = `https://mantly.io${routes[page][lang]}`;
    const englishUrl = `https://mantly.io${routes[page].en}`;
    const germanUrl = `https://mantly.io${routes[page].de}`;

    document.title = pageMetadata.title;
    setMeta('meta[name="description"]', { name: "description", content: pageMetadata.description });
    setMeta('meta[property="og:title"]', { property: "og:title", content: pageMetadata.title });
    setMeta('meta[property="og:description"]', { property: "og:description", content: pageMetadata.description });
    setMeta('meta[property="og:url"]', { property: "og:url", content: canonicalUrl });
    setMeta('meta[property="og:locale"]', { property: "og:locale", content: lang === "de" ? "de_DE" : "en_US" });
    setMeta('meta[name="twitter:title"]', { name: "twitter:title", content: pageMetadata.title });
    setMeta('meta[name="twitter:description"]', { name: "twitter:description", content: pageMetadata.description });
    setLink('link[rel="canonical"]', { rel: "canonical", href: canonicalUrl });
    setLink('link[rel="alternate"][hreflang="en"]', { rel: "alternate", hreflang: "en", href: englishUrl });
    setLink('link[rel="alternate"][hreflang="de"]', { rel: "alternate", hreflang: "de", href: germanUrl });
    setLink('link[rel="alternate"][hreflang="x-default"]', {
      rel: "alternate",
      hreflang: "x-default",
      href: page === "home" ? "https://mantly.io/" : englishUrl,
    });
  }, [lang, page]);

  return null;
}
