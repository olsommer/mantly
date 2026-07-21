import { useTranslation } from "@/i18n/useTranslation";
import { CircleCheckBig, GitMerge, ShieldCheck } from "lucide-react";

export function ProblemSection() {
  const { t } = useTranslation();
  const subtitle = t("problem.subtitle");

  const outcomes = [
    {
      icon: CircleCheckBig,
      title: t("problem.pain1.title"),
      desc: t("problem.pain1.desc"),
    },
    {
      icon: ShieldCheck,
      title: t("problem.pain2.title"),
      desc: t("problem.pain2.desc"),
    },
    {
      icon: GitMerge,
      title: t("problem.pain3.title"),
      desc: t("problem.pain3.desc"),
    },
  ];

  return (
    <section className="py-14 sm:py-32">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        {/* Section header */}
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-primary">
            {t("problem.tagline")}
          </p>
          <h2 className="mt-3 text-[2rem] leading-tight sm:mt-4 sm:text-[3rem] lg:text-[3.5rem]">
            {t("problem.title")}
          </h2>
          {subtitle && (
            <p className="mt-3 text-base text-muted-foreground sm:mt-5 sm:text-lg">{subtitle}</p>
          )}
        </div>

        {/* Outcomes */}
        <div className="mt-9 grid gap-3 sm:mt-20 sm:grid-cols-3 sm:gap-8">
          {outcomes.map((point) => (
            <div
              key={point.title}
              className="rounded-2xl border border-border/60 bg-background p-4 text-left transition-shadow hover:shadow-md sm:p-8 sm:text-center"
            >
              <div className="flex items-start gap-4 sm:block">
                <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/8 sm:mx-auto sm:mb-5 sm:size-12">
                  <point.icon className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <h3 className="text-xl leading-tight sm:text-[2rem]">{point.title}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground sm:mt-3 sm:text-base">
                    {point.desc}
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
