import { useTranslation } from "@/i18n/useTranslation";
import { Button } from "@/components/ui/button";
import { DemoLauncher } from "@/components/DemoLauncher";
import { ArrowDown, ArrowRight } from "lucide-react";

export function HeroSection() {
  const { t } = useTranslation();

  return (
    <section className="relative pt-32 pb-20 sm:pt-44 sm:pb-32 overflow-hidden">
      {/* Background decoration */}
      <div className="absolute inset-0 -z-10">
        <div className="absolute inset-0 bg-gradient-to-b from-primary/[0.04] via-transparent to-transparent" />
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[600px] bg-primary/[0.03] rounded-full blur-3xl" />
      </div>

      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl text-center">
          {/* Badge */}
          <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-border bg-background/80 backdrop-blur-sm px-4 py-1.5 text-base text-muted-foreground animate-fade-in-up">
            <span className="inline-block h-2 w-2 rounded-full bg-primary animate-pulse" />
            {t("hero.badge")}
          </div>

          {/* Headline */}
          <h1 className="text-5xl leading-none sm:text-6xl lg:text-7xl text-foreground animate-fade-in-up delay-100">
            {t("hero.title")}
          </h1>

          {/* Subheadline */}
          <p className="mt-8 text-lg text-muted-foreground sm:text-xl max-w-2xl mx-auto leading-relaxed animate-fade-in-up delay-200">
            {t("hero.subtitle")}
          </p>
          <p className="mt-5 text-base font-medium text-primary animate-fade-in-up delay-200">
            {t("hero.builtFor")}
          </p>

          {/* CTAs */}
          <div className="mt-12 flex flex-col sm:flex-row items-center justify-center gap-4 animate-fade-in-up delay-300">
            <Button asChild size="lg" className="text-base px-8 h-12 rounded-lg shadow-lg shadow-primary/25">
              <a href={t("hero.ctaHref")}>
                {t("hero.cta")}
                <ArrowRight className="ml-2 h-4 w-4" />
              </a>
            </Button>
            <Button asChild variant="ghost" size="lg" className="text-base px-8 h-12">
              <a href={t("hero.secondaryHref")}>
                {t("hero.secondaryCta")}
                <ArrowDown className="ml-2 h-4 w-4" />
              </a>
            </Button>
          </div>
        </div>

        {/* Product preview */}
        <div id="interactive-demo" className="mx-auto mt-20 max-w-6xl scroll-mt-24 animate-fade-in-up delay-400">
          <DemoLauncher />
        </div>
      </div>
    </section>
  );
}
