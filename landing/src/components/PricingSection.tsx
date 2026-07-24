import { Building2, Check, Cloud, Github, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { useTranslation } from "@/i18n/useTranslation";
import type { TranslationKey } from "@/i18n/translations";
import { cn } from "@/lib/utils";

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

type Translator = ReturnType<typeof useTranslation>["t"];

function PlanFeatures({
  plan,
  t,
  className,
}: {
  plan: Plan;
  t: Translator;
  className?: string;
}) {
  return (
    <ul className={cn("grid gap-x-6 gap-y-2.5", className)}>
      {plan.features.map((feature) => (
        <li key={feature} className="flex gap-2.5 text-sm leading-relaxed text-muted-foreground">
          <Check className="mt-0.5 size-4 shrink-0 text-primary" />
          <span>{t(feature)}</span>
        </li>
      ))}
    </ul>
  );
}

function PaidPlanPanel({ plan }: { plan: Plan }) {
  const { t } = useTranslation();

  return (
    <div className="flex h-full flex-col px-4 pb-5 pt-5 sm:px-5 md:px-7 md:pb-7 md:pt-6 lg:px-8">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10">
            <plan.icon className="size-5 text-primary" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-2xl leading-tight">{t(plan.name)}</h3>
              {plan.featured && (
                <span className="rounded-full bg-primary px-2.5 py-1 text-[0.65rem] font-medium leading-none text-primary-foreground">
                  {t("pricing.popular")}
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <span className="text-2xl font-semibold leading-none sm:text-3xl">{t(plan.price)}</span>
          {!plan.hidePeriod && (
            <span className="mt-1 block text-xs text-muted-foreground">{t("pricing.month")}</span>
          )}
        </div>
      </div>

      <p className="mt-4 max-w-xl text-sm leading-relaxed text-muted-foreground sm:text-base">
        {t(plan.desc)}
      </p>

      <PlanFeatures plan={plan} t={t} className="mt-6 md:grid-cols-2" />

      <Button
        asChild
        variant={plan.featured ? "default" : "outline"}
        className="mt-7 h-12 w-full rounded-lg sm:w-fit sm:min-w-44"
      >
        <a href={plan.href}>{t(plan.cta)}</a>
      </Button>
    </div>
  );
}

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
  const [community, cloud, business, enterprise] = plans;

  return (
    <section id="pricing" className="scroll-mt-16 bg-muted/40 py-14 sm:py-32">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-primary">
            {t("pricing.tagline")}
          </p>
          <h2 className="mt-3 text-[1.85rem] font-semibold leading-tight sm:mt-4 sm:text-[2.85rem] lg:text-[3.35rem]">
            {t("pricing.title")}
          </h2>
          {subtitle && (
            <p className="mt-3 text-base text-muted-foreground sm:mt-5 sm:text-lg">{subtitle}</p>
          )}
        </div>

        {/* Purpose-built mobile pricing */}
        <div className="mt-8 space-y-4 md:hidden">
          <div className="grid gap-2.5">
            <Button asChild size="lg" className="h-12 w-full rounded-lg">
              <a href={cloud.href}>{t(cloud.cta)}</a>
            </Button>
            <Button asChild variant="outline" size="lg" className="h-12 w-full rounded-lg bg-background">
              <a href={community.href}>
                <Github className="size-4" />
                {t(community.cta)}
              </a>
            </Button>
          </div>

          <div className="overflow-hidden rounded-2xl border border-primary/25 bg-background shadow-lg shadow-primary/[0.06]">
            <Tabs defaultValue="cloud">
              <div className="border-b border-border/60 bg-primary/[0.035] p-3">
                <TabsList aria-label={`${t(cloud.name)} / ${t(business.name)}`}>
                  <TabsTrigger value="cloud">
                    <Cloud className="size-4" />
                    {t(cloud.name)}
                  </TabsTrigger>
                  <TabsTrigger value="business">
                    <ShieldCheck className="size-4" />
                    {t(business.name)}
                  </TabsTrigger>
                </TabsList>
              </div>
              <TabsContent value="cloud" className="mt-0">
                <PaidPlanPanel plan={cloud} />
              </TabsContent>
              <TabsContent value="business" className="mt-0">
                <PaidPlanPanel plan={business} />
              </TabsContent>
            </Tabs>
          </div>

          <Accordion
            type="single"
            collapsible
            className="rounded-2xl border border-border/70 bg-background px-4"
          >
            {[community, enterprise].map((plan) => (
              <AccordionItem key={plan.name} value={plan.name} className="border-border/60">
                <AccordionTrigger className="min-h-[4.5rem] py-3 hover:no-underline">
                  <span className="flex min-w-0 flex-1 items-center gap-3 pr-2 text-left">
                    <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10">
                      <plan.icon className="size-4 text-primary" />
                    </span>
                    <span className="min-w-0 flex-1 text-lg font-normal leading-tight">
                      {t(plan.name)}
                    </span>
                    <span className="shrink-0 text-base font-semibold">{t(plan.price)}</span>
                  </span>
                </AccordionTrigger>
                <AccordionContent className="pb-5 pl-[3.25rem] pr-2">
                  <p className="text-sm leading-relaxed text-muted-foreground">{t(plan.desc)}</p>
                  <PlanFeatures plan={plan} t={t} className="mt-5" />
                  <Button asChild variant="outline" className="mt-5 h-11 w-full rounded-lg">
                    <a href={plan.href}>{t(plan.cta)}</a>
                  </Button>
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </div>

        {/* Community + managed plans on tablet and desktop */}
        <div className="mx-auto mt-14 hidden max-w-6xl overflow-hidden rounded-3xl border border-border/70 bg-background shadow-xl shadow-black/[0.04] md:grid md:grid-cols-[minmax(0,0.85fr)_minmax(0,1.35fr)]">
          <article className="flex min-w-0 flex-col p-6 lg:p-8">
            <div className="flex items-start justify-between gap-4">
              <div className="flex size-11 items-center justify-center rounded-xl bg-primary/10">
                <community.icon className="size-5 text-primary" />
              </div>
              <span className="text-3xl font-semibold">{t(community.price)}</span>
            </div>
            <h3 className="mt-6 text-3xl leading-tight">{t(community.name)}</h3>
            <p className="mt-3 text-base leading-relaxed text-muted-foreground">
              {t(community.desc)}
            </p>
            <PlanFeatures plan={community} t={t} className="mt-7" />
            <Button asChild variant="outline" className="mt-auto h-12 w-full rounded-lg">
              <a href={community.href}>
                <Github className="size-4" />
                {t(community.cta)}
              </a>
            </Button>
          </article>

          <div className="min-w-0 border-l border-primary/15 bg-primary/[0.035]">
            <Tabs defaultValue="cloud" className="h-full">
              <div className="border-b border-primary/15 p-4 lg:px-6 lg:py-5">
                <TabsList aria-label={`${t(cloud.name)} / ${t(business.name)}`}>
                  <TabsTrigger value="cloud">
                    <Cloud className="size-4" />
                    {t(cloud.name)}
                  </TabsTrigger>
                  <TabsTrigger value="business">
                    <ShieldCheck className="size-4" />
                    {t(business.name)}
                  </TabsTrigger>
                </TabsList>
              </div>
              <TabsContent value="cloud" className="mt-0">
                <PaidPlanPanel plan={cloud} />
              </TabsContent>
              <TabsContent value="business" className="mt-0">
                <PaidPlanPanel plan={business} />
              </TabsContent>
            </Tabs>
          </div>
        </div>

        <article className="mx-auto mt-4 hidden max-w-6xl rounded-2xl border border-primary/20 bg-background p-5 md:block lg:p-6">
          <div className="grid items-center gap-5 md:grid-cols-[minmax(0,1fr)_auto]">
            <div className="flex min-w-0 items-start gap-4">
              <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary/10">
                <enterprise.icon className="size-5 text-primary" />
              </div>
              <div className="min-w-0">
                <h3 className="text-2xl leading-tight">{t(enterprise.name)}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground sm:text-base">
                  {t(enterprise.desc)}
                </p>
              </div>
            </div>
            <div className="flex items-center justify-end gap-4">
              <span className="text-2xl font-semibold">{t(enterprise.price)}</span>
              <Button asChild variant="outline" className="h-11 rounded-lg bg-background px-5">
                <a href={enterprise.href}>{t(enterprise.cta)}</a>
              </Button>
            </div>
          </div>
          <PlanFeatures plan={enterprise} t={t} className="mt-5 md:grid-cols-2 xl:grid-cols-3" />
        </article>

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
