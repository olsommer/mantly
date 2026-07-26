import { useEffect } from "react";
import { useTranslation } from "@/i18n/useTranslation";
import {
  landingMetadata,
  landingRoutes,
  type LandingPage,
} from "../../seo-metadata";

export type { LandingPage } from "../../seo-metadata";

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
    const pageMetadata = landingMetadata[lang][page];
    const canonicalUrl = `https://mantly.io${landingRoutes[page][lang]}`;
    const englishUrl = `https://mantly.io${landingRoutes[page].en}`;
    const germanUrl = `https://mantly.io${landingRoutes[page].de}`;

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
