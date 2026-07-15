import { useState, useCallback, useEffect, type ReactNode } from "react";
import { translations, type Language, type TranslationKey } from "./translations";
import { LanguageContext } from "./context";
import { browserLanguage, languageFromUrl, localizedPath } from "./language-routing";

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Language>(() => {
    if (typeof window !== "undefined") {
      return languageFromUrl() ?? browserLanguage();
    }
    return "en";
  });

  const updateLang = useCallback((nextLang: Language) => {
    setLang(nextLang);
    if (typeof window === "undefined") return;

    const nextPath = localizedPath(window.location.pathname, nextLang);
    const params = new URLSearchParams(window.location.search);
    params.delete("l");
    const nextSearch = params.toString();
    const nextUrl = `${nextPath}${nextSearch ? `?${nextSearch}` : ""}${window.location.hash}`;
    if (nextUrl !== `${window.location.pathname}${window.location.search}${window.location.hash}`) {
      window.history.pushState(null, "", nextUrl);
    }
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  useEffect(() => {
    const syncFromUrl = () => setLang(languageFromUrl() ?? browserLanguage());
    window.addEventListener("popstate", syncFromUrl);
    return () => window.removeEventListener("popstate", syncFromUrl);
  }, []);

  const t = useCallback(
    (key: TranslationKey): string => {
      return translations[lang][key] ?? key;
    },
    [lang]
  );

  return (
    <LanguageContext value={{ lang, setLang: updateLang, t }}>
      {children}
    </LanguageContext>
  );
}
