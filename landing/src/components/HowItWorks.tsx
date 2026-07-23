import { useTranslation } from "@/i18n/useTranslation";
import { Inbox, ListChecks, Send, Wrench } from "lucide-react";

export function HowItWorks() {
  const { t } = useTranslation();
  const subtitle = t("how.subtitle");

  const steps = [
    {
      icon: Inbox,
      title: t("how.step1.title"),
      desc: t("how.step1.desc"),
      color: "bg-blue-500/10 text-blue-600",
      num: "01",
    },
    {
      icon: ListChecks,
      title: t("how.step2.title"),
      desc: t("how.step2.desc"),
      color: "bg-violet-500/10 text-violet-600",
      num: "02",
    },
    {
      icon: Wrench,
      title: t("how.step3.title"),
      desc: t("how.step3.desc"),
      color: "bg-amber-500/10 text-amber-600",
      num: "03",
    },
    {
      icon: Send,
      title: t("how.step4.title"),
      desc: t("how.step4.desc"),
      color: "bg-emerald-500/10 text-emerald-600",
      num: "04",
    },
  ];

  return (
    <section id="how-it-works" className="scroll-mt-16 bg-muted/40 py-14 sm:py-32">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        {/* Section header */}
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-primary">
            {t("how.tagline")}
          </p>
          <h2 className="mt-3 text-[1.85rem] font-semibold leading-tight sm:mt-4 sm:text-[2.85rem] lg:text-[3.35rem]">
            {t("how.title")}
          </h2>
          {subtitle && (
            <p className="mt-3 text-base text-muted-foreground sm:mt-5 sm:text-lg">{subtitle}</p>
          )}
        </div>

        {/* Steps */}
        <div className="mt-9 grid gap-3 sm:mt-20 sm:grid-cols-2 sm:gap-8 lg:grid-cols-4">
          {steps.map((step) => (
            <div key={step.num} className="relative rounded-xl border border-border/60 bg-background/70 p-4 sm:border-0 sm:bg-transparent sm:p-0">
              <div className="flex items-start gap-4 text-left sm:flex-col sm:items-center sm:gap-0 sm:text-center">
                {/* Step number */}
                <div className="flex shrink-0 flex-col items-center gap-1.5 sm:gap-4">
                  <span className="font-mono text-[0.65rem] font-semibold tracking-wider text-muted-foreground/50 sm:text-xs">
                    {step.num}
                  </span>
                  <div
                    className={`flex size-11 items-center justify-center rounded-xl sm:mb-6 sm:size-14 sm:rounded-2xl ${step.color}`}
                  >
                    <step.icon className="h-5 w-5 sm:h-6 sm:w-6" />
                  </div>
                </div>
                <div>
                  <h3 className="text-xl leading-tight sm:text-[2rem]">{step.title}</h3>
                  <p className="mt-1.5 max-w-[280px] text-sm leading-relaxed text-muted-foreground sm:mt-3 sm:text-base">
                    {step.desc}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
