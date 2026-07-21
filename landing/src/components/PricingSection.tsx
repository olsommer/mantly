import { Building2, Check, Cloud, Github, ShieldCheck } from "lucide-react";
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
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";

type PlanCopy = {
  name: TranslationKey;
  price: TranslationKey;
  desc: TranslationKey;
  cta: TranslationKey;
  features: TranslationKey[];
};

type Plan = PlanCopy & {
  icon: typeof Cloud;
  href: string;
  featured: boolean;
  hidePeriod?: boolean;
};

export function PricingSection() {
  const { t } = useTranslation();
  const subtitle = t("pricing.subtitle");
  const plans: Plan[] = [
    {
      name: "pricing.community.name",
      price: "pricing.community.price",
      desc: "pricing.community.desc",
      cta: "pricing.community.cta",
      features: [
        "pricing.community.feature1",
        "pricing.community.feature2",
        "pricing.community.feature3",
        "pricing.community.feature4",
        "pricing.community.feature5",
        "pricing.community.feature6",
      ],
      icon: Github,
      href: "https://github.com/olsommer/mantly",
      featured: false,
      hidePeriod: true,
    },
    {
      name: "pricing.cloud.name",
      price: "pricing.cloud.price",
      desc: "pricing.cloud.desc",
      cta: "pricing.cloud.cta",
      features: [
        "pricing.cloud.feature1",
        "pricing.cloud.feature2",
        "pricing.cloud.feature3",
        "pricing.cloud.feature4",
        "pricing.cloud.feature5",
        "pricing.cloud.feature6",
        "pricing.cloud.feature7",
        "pricing.cloud.feature8",
      ],
      icon: Cloud,
      href: "https://app.mantly.io?view=signup",
      featured: true,
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
      ],
      icon: ShieldCheck,
      href: "mailto:support@mantly.io?subject=Mantly%20Business",
      featured: false,
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
      href: "mailto:support@mantly.io?subject=Mantly%20Enterprise",
      featured: false,
      hidePeriod: true,
    },
  ];
  const mobilePlans: Plan[] = [plans[1], plans[0], plans[2], plans[3]];

  return (
    <section id="pricing" className="scroll-mt-16 bg-muted/40 py-14 sm:py-32">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-primary">
            {t("pricing.tagline")}
          </p>
          <h2 className="mt-3 text-[2rem] leading-tight sm:mt-4 sm:text-[3rem] lg:text-[3.5rem]">
            {t("pricing.title")}
          </h2>
          {subtitle && (
            <p className="mt-3 text-base text-muted-foreground sm:mt-5 sm:text-lg">{subtitle}</p>
          )}
        </div>

        <div className="mt-8 grid gap-3 md:hidden">
          <Button asChild size="lg" className="h-12 w-full rounded-lg">
            <a href={plans[1].href}>{t(plans[1].cta)}</a>
          </Button>
          <Button asChild variant="outline" size="lg" className="h-12 w-full rounded-lg">
            <a href={plans[0].href}>
              <Github className="size-4" />
              {t(plans[0].cta)}
            </a>
          </Button>
        </div>

        <div className="mt-6 md:hidden">
          <Accordion type="single" collapsible className="w-full">
            {mobilePlans.map((plan) => (
              <AccordionItem key={plan.name} value={plan.name} className="border-border/60">
                <AccordionTrigger className="min-h-[4.5rem] py-3 hover:no-underline">
                  <span className="flex min-w-0 flex-1 items-center gap-3 pr-2 text-left">
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-background">
                      <plan.icon className="size-4 text-primary" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="text-lg font-normal leading-tight">{t(plan.name)}</span>
                        {plan.featured && (
                          <span className="rounded-full bg-primary px-2 py-1 text-[0.65rem] font-medium leading-none text-primary-foreground">
                            {t("pricing.popular")}
                          </span>
                        )}
                      </span>
                      <span className="mt-1 block text-xs font-normal text-muted-foreground">
                        {t(plan.desc)}
                      </span>
                    </span>
                    <span className="shrink-0 text-right text-lg font-semibold">
                      {t(plan.price)}
                      {!plan.hidePeriod && (
                        <span className="block text-[0.65rem] font-normal text-muted-foreground">{t("pricing.month")}</span>
                      )}
                    </span>
                  </span>
                </AccordionTrigger>
                <AccordionContent className="pb-5 pl-12 pr-3">
                  <ul className="space-y-2">
                    {plan.features.map((feature) => (
                      <li key={feature} className="flex gap-2 text-sm leading-relaxed text-muted-foreground">
                        <Check className="mt-0.5 size-4 shrink-0 text-primary" />
                        <span>{t(feature)}</span>
                      </li>
                    ))}
                  </ul>
                  <Button
                    asChild
                    variant={plan.featured ? "default" : "outline"}
                    className="mt-5 h-11 w-full rounded-lg"
                  >
                    <a href={plan.href}>{t(plan.cta)}</a>
                  </Button>
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </div>

        <div className="mt-16 hidden gap-5 md:grid md:grid-cols-2 xl:grid-cols-4">
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
                  {!plan.hidePeriod && (
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
                  className="h-11 w-full rounded-lg"
                >
                  <a href={plan.href}>{t(plan.cta)}</a>
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
        <p className="mx-auto mt-6 max-w-3xl text-center text-xs leading-relaxed text-muted-foreground sm:mt-10 sm:text-sm">
          {t("pricing.runDefinition")}
        </p>
        <p className="mx-auto mt-3 max-w-3xl text-center text-xs leading-relaxed text-muted-foreground sm:text-sm">
          {t("pricing.usageNote")}
        </p>
      </div>
    </section>
  );
}
