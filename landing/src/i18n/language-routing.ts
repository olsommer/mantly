import type { Language } from "./translations";

const SUPPORTED_LANGUAGES = new Set<Language>(["en", "de"]);

function isLanguage(value: string | null): value is Language {
  return value === "en" || value === "de";
}

export function browserLanguage(): Language {
  if (typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("de")) {
    return "de";
  }
  return "en";
}

export function languageFromUrl(location: Location = window.location): Language | null {
  const queryLanguage = new URLSearchParams(location.search).get("l");
  if (isLanguage(queryLanguage)) return queryLanguage;

  const [firstSegment] = location.pathname.split("/").filter(Boolean);
  return isLanguage(firstSegment) ? firstSegment : null;
}

export function stripLanguagePrefix(pathname: string): string {
  const segments = pathname.split("/").filter(Boolean);
  if (segments.length > 0 && SUPPORTED_LANGUAGES.has(segments[0] as Language)) {
    segments.shift();
  }
  return segments.length > 0 ? `/${segments.join("/")}` : "/";
}

export function localizedPath(pathname: string, language: Language): string {
  const cleanPath = stripLanguagePrefix(pathname);
  return cleanPath === "/" ? `/${language}/` : `/${language}${cleanPath}`;
}
