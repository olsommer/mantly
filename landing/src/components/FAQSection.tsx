import { useTranslation } from "@/i18n/useTranslation";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import type { TranslationKey } from "@/i18n/translations";

const faqKeys = [1, 2, 3, 4, 5, 6] as const;

export function FAQSection() {
  const { t } = useTranslation();

  return (
    <section id="faq" className="scroll-mt-16 py-14 sm:py-32">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        {/* Section header */}
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-primary">
            {t("faq.tagline")}
          </p>
          <h2 className="mt-3 text-[1.85rem] font-semibold leading-tight sm:mt-4 sm:text-[2.85rem] lg:text-[3.35rem]">
            {t("faq.title")}
          </h2>
        </div>

        {/* Accordion */}
        <div className="mx-auto mt-8 max-w-2xl sm:mt-14">
          <Accordion type="single" collapsible className="w-full">
            {faqKeys.map((num) => (
              <AccordionItem key={num} value={`faq-${num}`} className="border-border/60">
                <AccordionTrigger className="min-h-12 py-4 text-left text-lg font-normal leading-tight hover:no-underline sm:py-6 sm:text-[2rem]">
                  {t(`faq.q${num}` as TranslationKey)}
                </AccordionTrigger>
                <AccordionContent className="pb-5 text-sm leading-relaxed text-muted-foreground sm:pb-6 sm:text-base">
                  {t(`faq.a${num}` as TranslationKey)}
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </div>
      </div>
    </section>
  );
}
