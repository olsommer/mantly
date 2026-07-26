import { useTranslation } from "@/i18n/useTranslation";
import { Button } from "@/components/ui/button";
import { ArrowRight, BookOpen, Github, Play } from "lucide-react";

export function HeroSection() {
  const { t } = useTranslation();

  const openDemo = () => {
    window.dispatchEvent(new Event("mantly:open-demo"));
  };

  return (
    <section className="relative overflow-hidden pb-14 pt-20 sm:pb-32 sm:pt-40 lg:pt-44">
      {/* Background decoration */}
      <div className="absolute inset-0 -z-10">
        <div className="absolute inset-0 bg-gradient-to-b from-primary/[0.04] via-transparent to-transparent" />
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[600px] bg-primary/[0.03] rounded-full blur-3xl" />
      </div>

      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl text-center">
          {/* Badge */}
          <div className="mb-4 inline-flex max-w-full items-center gap-1.5 rounded-full border border-border bg-background/80 px-3 py-1.5 text-xs text-muted-foreground backdrop-blur-sm animate-fade-in-up sm:mb-8 sm:gap-2 sm:px-4 sm:text-base">
            <span className="inline-block h-2 w-2 rounded-full bg-primary animate-pulse" />
            {t("hero.badge")}
          </div>

          {/* Headline */}
          <h1 className="text-[2.1rem] font-semibold leading-[1.02] text-foreground animate-fade-in-up delay-100 min-[380px]:text-[2.35rem] min-[380px]:leading-[0.98] sm:text-[3.6rem] sm:leading-none lg:text-[4.35rem]">
            {t("hero.title")}
          </h1>

          {/* Subheadline */}
          <p className="mx-auto mt-5 max-w-2xl text-base leading-relaxed text-muted-foreground animate-fade-in-up delay-200 sm:mt-8 sm:text-xl">
            {t("hero.subtitle")}
          </p>
          <p className="mt-3 text-sm font-medium text-primary animate-fade-in-up delay-200 sm:mt-5 sm:text-base">
            {t("hero.builtFor")}
          </p>

          {/* CTAs */}
          <div className="mt-6 grid grid-cols-2 items-center justify-center gap-3 animate-fade-in-up delay-300 sm:mt-12 sm:flex sm:gap-4">
            <Button
              asChild
              size="lg"
              data-testid="hero-primary-cta"
              className="col-span-2 h-12 rounded-lg px-8 text-base shadow-lg shadow-primary/25 sm:col-auto"
            >
              <a href={t("hero.ctaHref")}>
                {t("hero.cta")}
                <ArrowRight className="ml-2 h-4 w-4" />
              </a>
            </Button>
            <Button asChild variant="outline" size="lg" className="h-11 px-3 text-sm sm:h-12 sm:px-8 sm:text-base">
              <a href={t("hero.secondaryHref")}>
                <Github className="mr-2 h-4 w-4" />
                {t("hero.secondaryCta")}
              </a>
            </Button>
            <Button
              type="button"
              variant="outline"
              size="lg"
              data-testid="hero-demo-trigger"
              className="h-11 px-2 text-xs sm:h-12 sm:px-6 sm:text-base"
              onClick={openDemo}
            >
              <Play className="h-4 w-4" />
              {t("hero.demoCta")}
            </Button>
          </div>
          <a
            href="https://github.com/olsommer/mantly/blob/main/docs/deploy-community.md"
            className="mt-3 inline-flex min-h-11 items-center gap-2 text-sm text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline animate-fade-in-up delay-300 sm:mt-5"
          >
            <BookOpen className="h-4 w-4" />
            {t("hero.selfHostCta")}
          </a>
        </div>

      </div>
    </section>
  );
}
