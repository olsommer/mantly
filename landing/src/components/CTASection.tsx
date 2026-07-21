import { useTranslation } from "@/i18n/useTranslation";
import { Button } from "@/components/ui/button";
import { ArrowRight, BookOpen, Github } from "lucide-react";

export function CTASection() {
  const { t } = useTranslation();

  return (
    <section id="get-started" className="py-24 sm:py-32 bg-muted/40">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-xl text-center">
          <h2 className="text-[2.5rem] leading-tight sm:text-[3rem] lg:text-[3.5rem]">
            {t("cta.title")}
          </h2>
          <p className="mt-5 text-lg text-muted-foreground">
            {t("cta.subtitle")}
          </p>
          <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Button asChild size="lg" className="text-base px-8 h-12 rounded-lg shadow-lg shadow-primary/25">
              <a href="https://app.mantly.io?view=signup">
                {t("cta.button")}
                <ArrowRight className="ml-2 h-4 w-4" />
              </a>
            </Button>
            <Button asChild variant="outline" size="lg" className="h-12 px-8 text-base">
              <a href="https://github.com/olsommer/mantly">
                <Github className="mr-2 h-4 w-4" />
                {t("cta.github")}
              </a>
            </Button>
          </div>
          <div className="mt-5 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm text-muted-foreground">
            <a
              href="https://github.com/olsommer/mantly/blob/main/docs/deploy-community.md"
              className="inline-flex items-center gap-2 underline-offset-4 hover:text-foreground hover:underline"
            >
              <BookOpen className="h-4 w-4" />
              {t("cta.selfHost")}
            </a>
            <a
              href="mailto:support@mantly.io?subject=Mantly%20Enterprise"
              className="underline-offset-4 hover:text-foreground hover:underline"
            >
              {t("cta.sales")}
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
