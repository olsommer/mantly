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
    <section id="how-it-works" className="py-24 sm:py-32 bg-muted/40">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        {/* Section header */}
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-primary">
            {t("how.tagline")}
          </p>
          <h2 className="mt-4 text-[2.5rem] leading-tight sm:text-[3rem] lg:text-[3.5rem]">
            {t("how.title")}
          </h2>
          {subtitle && (
            <p className="mt-5 text-lg text-muted-foreground">{subtitle}</p>
          )}
        </div>

        {/* Steps */}
        <div className="mt-20 grid gap-12 sm:grid-cols-2 lg:grid-cols-4 sm:gap-8">
          {steps.map((step) => (
            <div key={step.num} className="relative">
              <div className="flex flex-col items-center text-center">
                {/* Step number */}
                <span className="text-xs font-mono font-semibold text-muted-foreground/40 mb-4 tracking-wider">
                  {step.num}
                </span>
                <div
                  className={`mb-6 flex h-14 w-14 items-center justify-center rounded-2xl ${step.color}`}
                >
                  <step.icon className="h-6 w-6" />
                </div>
                <h3 className="text-[2rem] leading-tight">{step.title}</h3>
                <p className="mt-3 text-base text-muted-foreground leading-relaxed max-w-[280px]">
                  {step.desc}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
