import { createContext } from "react";
import type { Language, TranslationKey } from "./translations";

export interface LanguageContextType {
  lang: Language;
  setLang: (lang: Language) => void;
  t: (key: TranslationKey) => string;
}

export const LanguageContext = createContext<LanguageContextType | null>(null);
