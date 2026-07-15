import { useTranslation } from "@/i18n/useTranslation";
import { Button } from "@/components/ui/button";
import { ArrowRight } from "lucide-react";

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
          <div className="mt-10">
            <Button asChild size="lg" className="text-base px-8 h-12 rounded-lg shadow-lg shadow-primary/25">
              <a href="https://app.mantly.io?view=signup">
                {t("cta.button")}
                <ArrowRight className="ml-2 h-4 w-4" />
              </a>
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}
