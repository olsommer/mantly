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
    <section id="faq" className="py-24 sm:py-32">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        {/* Section header */}
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-primary">
            {t("faq.tagline")}
          </p>
          <h2 className="mt-4 text-[2.5rem] leading-tight sm:text-[3rem] lg:text-[3.5rem]">
            {t("faq.title")}
          </h2>
        </div>

        {/* Accordion */}
        <div className="mt-14 mx-auto max-w-2xl">
          <Accordion type="single" collapsible className="w-full">
            {faqKeys.map((num) => (
              <AccordionItem key={num} value={`faq-${num}`} className="border-border/60">
                <AccordionTrigger className="py-6 text-left text-[2rem] font-normal leading-tight hover:no-underline">
                  {t(`faq.q${num}` as TranslationKey)}
                </AccordionTrigger>
                <AccordionContent className="pb-6 text-base text-muted-foreground leading-relaxed">
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
