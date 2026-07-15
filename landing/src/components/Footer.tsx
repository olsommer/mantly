import { useTranslation } from "@/i18n/useTranslation";
import { Separator } from "@/components/ui/separator";
import { Globe } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Language } from "@/i18n/translations";
import { localizedPath } from "@/i18n/language-routing";

export function Footer() {
  const { t, lang, setLang } = useTranslation();
  const legalLinks =
    lang === "de"
      ? { support: "/de/hilfe", privacy: "/de/datenschutz", terms: "/de/nutzungsbedingungen", imprint: "/de/impressum" }
      : { support: "/en/support", privacy: "/en/privacy", terms: "/en/terms", imprint: "/en/imprint" };

  const toggleLang = () => {
    const nextLang: Language = lang === "en" ? "de" : "en";
    setLang(nextLang);
  };

  const homeHref = localizedPath("/", lang);

  return (
    <footer className="border-t border-border/50 bg-background">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 py-12">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-6">
          {/* Brand */}
          <div>
            <a href={homeHref} className="flex items-baseline gap-1.5">
              <span className="font-display text-2xl font-normal leading-tight tracking-tight">{t("brand.name")}</span>
              
            </a>
            <p className="mt-2 text-base text-muted-foreground/70 max-w-xs">
              {t("footer.tagline")}
            </p>
          </div>

          {/* Links */}
          <div className="flex flex-wrap items-center gap-6 text-base text-muted-foreground/70">
            <a href={homeHref} className="hover:text-foreground transition-colors">
              {t("brand.name")}
            </a>
            <a
              href={legalLinks.support}
              className="hover:text-foreground transition-colors"
            >
              {t("footer.support")}
            </a>
            <a
              href={legalLinks.privacy}
              className="hover:text-foreground transition-colors"
            >
              {t("footer.privacy")}
            </a>
            <a
              href={legalLinks.terms}
              className="hover:text-foreground transition-colors"
            >
              {t("footer.terms")}
            </a>
            <a
              href={legalLinks.imprint}
              className="hover:text-foreground transition-colors"
            >
              {t("footer.imprint")}
            </a>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={toggleLang}
              className="h-auto px-0 text-base text-muted-foreground/70 hover:text-foreground"
              aria-label="Toggle language"
            >
              <Globe className="h-3.5 w-3.5" />
              {lang === "en" ? "DE" : "EN"}
            </Button>
          </div>
        </div>

        <Separator className="my-8 bg-border/50" />

        <p className="text-xs text-muted-foreground/50 text-center">
          &copy; {new Date().getFullYear()} {t("brand.name")}. {t("footer.rights")}
        </p>
      </div>
    </footer>
  );
}
