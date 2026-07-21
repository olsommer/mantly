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
      <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6 sm:py-12 lg:px-8">
        <div className="flex flex-col items-start justify-between gap-5 sm:flex-row sm:items-center sm:gap-6">
          {/* Brand */}
          <div>
            <a href={homeHref} className="flex min-h-11 items-center gap-1.5">
              <span className="font-display text-2xl font-normal leading-tight tracking-tight">{t("brand.name")}</span>
              
            </a>
            <p className="mt-2 text-base text-muted-foreground max-w-xs">
              {t("footer.tagline")}
            </p>
          </div>

          {/* Links */}
          <div className="flex flex-wrap items-center gap-x-6 text-base text-muted-foreground sm:gap-y-2">
            <a href="https://github.com/olsommer/mantly" className="inline-flex min-h-11 items-center transition-colors hover:text-foreground">
              {t("footer.github")}
            </a>
            <a
              href="https://github.com/olsommer/mantly/blob/main/docs/deploy-community.md"
              className="inline-flex min-h-11 items-center transition-colors hover:text-foreground"
            >
              {t("footer.docs")}
            </a>
            <a
              href="mailto:support@mantly.io?subject=Mantly%20Enterprise"
              className="inline-flex min-h-11 items-center transition-colors hover:text-foreground"
            >
              {t("footer.sales")}
            </a>
            <a
              href={legalLinks.support}
              className="inline-flex min-h-11 items-center transition-colors hover:text-foreground"
            >
              {t("footer.support")}
            </a>
            <a
              href={legalLinks.privacy}
              className="inline-flex min-h-11 items-center transition-colors hover:text-foreground"
            >
              {t("footer.privacy")}
            </a>
            <a
              href={legalLinks.terms}
              className="inline-flex min-h-11 items-center transition-colors hover:text-foreground"
            >
              {t("footer.terms")}
            </a>
            <a
              href={legalLinks.imprint}
              className="inline-flex min-h-11 items-center transition-colors hover:text-foreground"
            >
              {t("footer.imprint")}
            </a>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={toggleLang}
              className="h-11 px-0 text-base text-muted-foreground hover:text-foreground"
              aria-label={t(lang === "en" ? "a11y.switchToGerman" : "a11y.switchToEnglish")}
            >
              <Globe className="h-3.5 w-3.5" />
              {lang === "en" ? "DE" : "EN"}
            </Button>
          </div>
        </div>

        <Separator className="my-8 bg-border/50" />

        <p className="text-xs text-muted-foreground text-center">
          &copy; {new Date().getFullYear()} {t("brand.name")}. {t("footer.rights")}
        </p>
      </div>
    </footer>
  );
}
