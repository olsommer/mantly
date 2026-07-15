import { useTranslation } from "@/i18n/useTranslation";
import { Clock, ShieldAlert, AlertTriangle } from "lucide-react";

export function ProblemSection() {
  const { t } = useTranslation();
  const subtitle = t("problem.subtitle");

  const painPoints = [
    {
      icon: Clock,
      title: t("problem.pain1.title"),
      desc: t("problem.pain1.desc"),
    },
    {
      icon: ShieldAlert,
      title: t("problem.pain2.title"),
      desc: t("problem.pain2.desc"),
    },
    {
      icon: AlertTriangle,
      title: t("problem.pain3.title"),
      desc: t("problem.pain3.desc"),
    },
  ];

  return (
    <section className="py-24 sm:py-32">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        {/* Section header */}
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-primary">
            {t("problem.tagline")}
          </p>
          <h2 className="mt-4 text-[2.5rem] leading-tight sm:text-[3rem] lg:text-[3.5rem]">
            {t("problem.title")}
          </h2>
          {subtitle && (
            <p className="mt-5 text-lg text-muted-foreground">{subtitle}</p>
          )}
        </div>

        {/* Pain points */}
        <div className="mt-20 grid gap-6 sm:grid-cols-3 sm:gap-8">
          {painPoints.map((point) => (
            <div
              key={point.title}
              className="rounded-2xl border border-border/60 bg-background p-8 text-center transition-shadow hover:shadow-md"
            >
              <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-xl bg-destructive/8">
                <point.icon className="h-5 w-5 text-destructive" />
              </div>
              <h3 className="text-[2rem] leading-tight">{point.title}</h3>
              <p className="mt-3 text-base text-muted-foreground leading-relaxed">
                {point.desc}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
