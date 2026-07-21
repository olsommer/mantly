import { BookOpenCheck, Inbox, Workflow } from "lucide-react";
import { useTranslation } from "@/i18n/useTranslation";
import type { TranslationKey } from "@/i18n/translations";

const pillars = [
  {
    icon: Inbox,
    title: "pillars.1.title",
    copy: "pillars.1.copy",
  },
  {
    icon: Workflow,
    title: "pillars.2.title",
    copy: "pillars.2.copy",
  },
  {
    icon: BookOpenCheck,
    title: "pillars.3.title",
    copy: "pillars.3.copy",
  },
] satisfies Array<{
  icon: typeof Inbox;
  title: TranslationKey;
  copy: TranslationKey;
}>;

export function ProductPillarsSection() {
  const { t } = useTranslation();

  return (
    <section className="bg-muted/40 py-24 sm:py-32">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-primary">
            {t("pillars.tagline")}
          </p>
          <h2 className="mt-4 text-[2.5rem] leading-tight sm:text-[3rem] lg:text-[3.5rem]">
            {t("pillars.title")}
          </h2>
        </div>

        <div className="mt-16 grid gap-6 sm:grid-cols-3">
          {pillars.map((item) => (
            <div
              key={item.title}
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
