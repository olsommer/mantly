import { useTranslation } from "@/i18n/useTranslation";
import { BriefcaseBusiness, FileText, Headset } from "lucide-react";
import type { TranslationKey } from "@/i18n/translations";

const useCases = [
  {
    icon: BriefcaseBusiness,
    title: "testimonials.1.title",
    copy: "testimonials.1.copy",
  },
  {
    icon: FileText,
    title: "testimonials.2.title",
    copy: "testimonials.2.copy",
  },
  {
    icon: Headset,
    title: "testimonials.3.title",
    copy: "testimonials.3.copy",
  },
] satisfies Array<{ icon: typeof BriefcaseBusiness; title: TranslationKey; copy: TranslationKey }>;

export function TestimonialsSection() {
  const { t } = useTranslation();

  return (
    <section className="py-24 sm:py-32 bg-muted/40">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        {/* Section header */}
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-primary">
            {t("testimonials.tagline")}
          </p>
          <h2 className="mt-4 text-[2.5rem] leading-tight sm:text-[3rem] lg:text-[3.5rem]">
            {t("testimonials.title")}
          </h2>
        </div>

        {/* Use-case cards */}
        <div className="mt-16 grid gap-6 sm:grid-cols-3">
          {useCases.map((item, i) => (
            <div
              key={i}
              className="rounded-2xl border border-border/60 bg-background p-7 transition-shadow hover:shadow-md"
            >
              <item.icon className="mb-5 h-6 w-6 text-primary" />
              <h3 className="text-[2rem] leading-tight">{t(item.title)}</h3>
              <p className="mt-3 text-base leading-relaxed text-muted-foreground">
                {t(item.copy)}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
