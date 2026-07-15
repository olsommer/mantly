import { Check, Mail, ShieldCheck, Sparkles, Building2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
} from "@/components/ui/card";
import { useTranslation } from "@/i18n/useTranslation";
import type { TranslationKey } from "@/i18n/translations";

type PlanCopy = {
  name: TranslationKey;
  price: TranslationKey;
  desc: TranslationKey;
  cta: TranslationKey;
  features: TranslationKey[];
};

export function PricingSection() {
  const { t } = useTranslation();
  const subtitle = t("pricing.subtitle");
  const plans: Array<PlanCopy & { icon: typeof Sparkles; href: string; featured: boolean; isCustom?: boolean }> = [
    {
      name: "pricing.free.name",
      price: "pricing.free.price",
      desc: "pricing.free.desc",
      cta: "pricing.free.cta",
      features: [
        "pricing.free.feature1",
        "pricing.free.feature2",
        "pricing.free.feature3",
        "pricing.free.feature4",
        "pricing.free.feature5",
        "pricing.free.feature6",
      ],
      icon: Sparkles,
      href: "https://app.mantly.io?view=signup",
      featured: false,
    },
    {
      name: "pricing.pro.name",
      price: "pricing.pro.price",
      desc: "pricing.pro.desc",
      cta: "pricing.pro.cta",
      features: [
        "pricing.pro.feature1",
        "pricing.pro.feature2",
        "pricing.pro.feature3",
        "pricing.pro.feature4",
        "pricing.pro.feature5",
        "pricing.pro.feature6",
        "pricing.pro.feature7",
        "pricing.pro.feature8",
      ],
      icon: ShieldCheck,
      href: "https://app.mantly.io?view=signup",
      featured: false,
    },
    {
      name: "pricing.business.name",
      price: "pricing.business.price",
      desc: "pricing.business.desc",
      cta: "pricing.business.cta",
      features: [
        "pricing.business.feature1",
        "pricing.business.feature2",
        "pricing.business.feature3",
        "pricing.business.feature4",
        "pricing.business.feature5",
        "pricing.business.feature6",
        "pricing.business.feature7",
        "pricing.business.feature8",
        "pricing.business.feature9",
        "pricing.business.feature10",
        "pricing.business.feature11",
        "pricing.business.feature12",
        "pricing.business.feature13",
      ],
      icon: Mail,
      href: "https://app.mantly.io?view=signup",
      featured: true,
    },
    {
      name: "pricing.enterprise.name",
      price: "pricing.enterprise.price",
      desc: "pricing.enterprise.desc",
      cta: "pricing.enterprise.cta",
      features: [
        "pricing.enterprise.feature1",
        "pricing.enterprise.feature2",
        "pricing.enterprise.feature3",
        "pricing.enterprise.feature4",
        "pricing.enterprise.feature5",
        "pricing.enterprise.feature6",
      ],
      icon: Building2,
      href: "mailto:support@mantly.io",
      featured: false,
      isCustom: true,
    },
  ];

  return (
    <section id="pricing" className="py-24 sm:py-32 bg-muted/40">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-primary">
            {t("pricing.tagline")}
          </p>
          <h2 className="mt-4 text-[2.5rem] leading-tight sm:text-[3rem] lg:text-[3.5rem]">
            {t("pricing.title")}
          </h2>
          {subtitle && (
            <p className="mt-5 text-lg text-muted-foreground">{subtitle}</p>
          )}
        </div>

        <div className="mt-16 grid gap-5 md:grid-cols-2 xl:grid-cols-4">
          {plans.map((plan) => (
            <Card
              key={plan.name}
              className={
                plan.featured
                  ? "relative flex h-full flex-col border-primary/50 shadow-lg shadow-primary/10"
                  : "flex h-full flex-col border-border/60 shadow-none"
              }
            >
              <CardHeader className="grid min-h-[18.5rem] grid-rows-[1.5rem_2.5rem_3.5rem_4rem_auto] pr-6">
                <div className="flex justify-end">
                  {plan.featured && (
                    <span className="rounded-full bg-primary px-3 py-1 text-xs font-medium leading-none text-primary-foreground">
                      {t("pricing.popular")}
                    </span>
                  )}
                </div>
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 self-start">
                  <plan.icon className="h-5 w-5 text-primary" />
                </div>
                <h3 className="self-start text-[2rem] leading-tight">
                  {t(plan.name)}
                </h3>
                <CardDescription className="self-start">{t(plan.desc)}</CardDescription>
                <div className="self-end">
                  <span className="text-4xl font-semibold">{t(plan.price)}</span>
                  {!plan.isCustom && (
                    <span className="ml-1 text-base text-muted-foreground">{t("pricing.month")}</span>
                  )}
                </div>
              </CardHeader>
              <CardContent>
                <ul className="space-y-3">
                  {plan.features.map((feature) => (
                    <li key={feature} className="flex gap-3 text-base text-muted-foreground">
                      <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                      <span>{t(feature)}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
              <CardFooter className="mt-auto">
                <Button
                  asChild
                  variant={plan.featured ? "default" : "outline"}
                  className="w-full rounded-lg"
                >
                  <a href={plan.href}>{t(plan.cta)}</a>
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}
