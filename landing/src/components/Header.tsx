import { useState, useEffect } from "react";
import { useTranslation } from "@/i18n/useTranslation";
import { Button } from "@/components/ui/button";
import { Github, Menu, X } from "lucide-react";
import { localizedPath } from "@/i18n/language-routing";

export function Header() {
  const { t, lang } = useTranslation();
  const [scrolled, setScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const homePath = localizedPath("/", lang);
  const mobileMenuId = "mobile-navigation";

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 10);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const navLinks = [
    { href: `${homePath}#pricing`, label: t("nav.pricing") },
    { href: `${homePath}#features`, label: t("nav.product") },
    {
      href: "https://github.com/olsommer/mantly/blob/main/docs/deploy-community.md",
      label: t("nav.docs"),
    },
  ];

  return (
    <header
      className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${
        scrolled
          ? "bg-background/80 backdrop-blur-xl border-b border-border/50 shadow-sm"
          : "bg-transparent"
      }`}
    >
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between">
          {/* Logo */}
          <a href={homePath} className="group flex min-h-11 items-center gap-1.5">
            <span className="font-display text-2xl font-normal leading-tight tracking-tight text-foreground">
              {t("brand.name")}
            </span>
          </a>

          {/* Desktop nav */}
          <nav className="hidden lg:flex items-center gap-7">
            {navLinks.map((link) => (
              <a
                key={link.href}
                href={link.href}
                className="text-base text-muted-foreground hover:text-foreground transition-colors"
              >
                {link.label}
              </a>
            ))}
          </nav>

          {/* Desktop actions */}
          <div className="hidden lg:flex items-center gap-2">
            <Button asChild variant="ghost" size="sm">
              <a href="https://github.com/olsommer/mantly">
                <Github className="h-4 w-4" />
                {t("nav.github")}
              </a>
            </Button>
            <Button asChild size="sm">
              <a href="https://app.mantly.io?view=signup">{t("nav.cloud")}</a>
            </Button>
          </div>

          {/* Mobile menu toggle */}
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-11 lg:hidden text-muted-foreground hover:text-foreground"
            onClick={() => setMobileOpen(!mobileOpen)}
            aria-label={t(mobileOpen ? "a11y.closeMenu" : "a11y.openMenu")}
            aria-expanded={mobileOpen}
            aria-controls={mobileMenuId}
          >
            {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </Button>
        </div>

        {/* Mobile nav */}
        {mobileOpen && (
          <div
            id={mobileMenuId}
            className="lg:hidden border-t border-border/50 pb-4 pt-3 bg-background/95 backdrop-blur-xl"
          >
            <nav className="flex flex-col gap-1">
              {navLinks.map((link) => (
                <a
                  key={link.href}
                  href={link.href}
                  className="flex min-h-11 items-center px-1 text-base text-muted-foreground transition-colors hover:text-foreground"
                  onClick={() => setMobileOpen(false)}
                >
                  {link.label}
                </a>
              ))}
              <div className="grid grid-cols-2 gap-2 pt-3 mt-2 border-t border-border/50">
                <Button asChild variant="ghost" size="sm" className="h-11">
                  <a href="https://github.com/olsommer/mantly">
                    <Github className="h-4 w-4" />
                    {t("nav.github")}
                  </a>
                </Button>
                <Button asChild size="sm" className="h-11">
                  <a href="https://app.mantly.io?view=signup">{t("nav.cloud")}</a>
                </Button>
              </div>
            </nav>
          </div>
        )}
      </div>
    </header>
  );
}
