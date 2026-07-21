import { BookOpenCheck, Inbox, Workflow } from "lucide-react";
import { useTranslation } from "@/i18n/useTranslation";
import type { TranslationKey } from "@/i18n/translations";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";

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
    <section className="bg-muted/40 py-14 sm:py-32">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-primary">
            {t("pillars.tagline")}
          </p>
          <h2 className="mt-3 text-[2rem] leading-tight sm:mt-4 sm:text-[3rem] lg:text-[3.5rem]">
            {t("pillars.title")}
          </h2>
        </div>

        <div className="mt-8 sm:hidden">
          <Accordion type="single" collapsible className="w-full">
            {pillars.map((item, index) => (
              <AccordionItem key={item.title} value={`pillar-${index}`} className="border-border/60">
                <AccordionTrigger className="min-h-12 py-3 hover:no-underline">
                  <span className="flex items-center gap-3 pr-2 text-left">
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-background">
                      <item.icon className="size-4 text-primary" />
                    </span>
                    <span className="text-lg font-normal leading-tight">{t(item.title)}</span>
                  </span>
                </AccordionTrigger>
                <AccordionContent className="pb-4 pl-12 pr-3 text-sm leading-relaxed text-muted-foreground">
                  {t(item.copy)}
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </div>

        <div className="mt-16 hidden gap-6 sm:grid sm:grid-cols-3">
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
