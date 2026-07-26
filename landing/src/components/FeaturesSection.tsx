import {
  BookOpenCheck,
  CloudCog,
  FileSearch,
  GitBranch,
  Github,
  ShieldCheck,
  LayoutDashboard,
  MessagesSquare,
  MessageSquareText,
  PlugZap,
  TestTube2,
} from "lucide-react";
import { useTranslation } from "@/i18n/useTranslation";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";

export function FeaturesSection() {
  const { t } = useTranslation();
  const subtitle = t("features.subtitle");

  const features = [
    { icon: Github, title: t("features.1.title"), desc: t("features.1.desc") },
    { icon: MessagesSquare, title: t("features.2.title"), desc: t("features.2.desc") },
    { icon: GitBranch, title: t("features.3.title"), desc: t("features.3.desc") },
    { icon: MessageSquareText, title: t("features.4.title"), desc: t("features.4.desc") },
    { icon: BookOpenCheck, title: t("features.5.title"), desc: t("features.5.desc") },
    { icon: PlugZap, title: t("features.6.title"), desc: t("features.6.desc") },
    { icon: ShieldCheck, title: t("features.7.title"), desc: t("features.7.desc") },
    { icon: TestTube2, title: t("features.8.title"), desc: t("features.8.desc") },
    { icon: CloudCog, title: t("features.9.title"), desc: t("features.9.desc") },
  ];

  const adminTabs = [
    { icon: GitBranch, label: t("features.admin.tab.intents") },
    { icon: TestTube2, label: t("features.admin.tab.responses") },
    { icon: FileSearch, label: t("features.admin.tab.attachments") },
  ];

  return (
    <section id="features" className="scroll-mt-16 py-14 sm:py-32">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        {/* Section header */}
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-primary">
            {t("features.tagline")}
          </p>
          <h2 className="mt-3 text-[1.85rem] font-semibold leading-tight sm:mt-4 sm:text-[2.85rem] lg:text-[3.35rem]">
            {t("features.title")}
          </h2>
          {subtitle && (
            <p className="mt-3 text-base text-muted-foreground sm:mt-5 sm:text-lg">{subtitle}</p>
          )}
        </div>

        {/* Compact mobile feature index */}
        <div className="mt-8 sm:hidden">
          <Accordion type="single" collapsible className="w-full">
            {features.map((feature, i) => (
              <AccordionItem key={feature.title} value={`feature-${i}`} className="border-border/60">
                <AccordionTrigger className="min-h-12 py-3 hover:no-underline">
                  <span className="flex items-center gap-3 pr-2 text-left">
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/8">
                      <feature.icon className="size-4 text-primary" />
                    </span>
                    <span className="text-lg font-normal leading-tight">{feature.title}</span>
                  </span>
                </AccordionTrigger>
                <AccordionContent className="pb-4 pl-12 pr-3 text-sm leading-relaxed text-muted-foreground">
                  {feature.desc}
                </AccordionContent>
              </AccordionItem>
            ))}
            <AccordionItem value="admin-preview" className="border-border/60">
              <AccordionTrigger className="min-h-12 py-3 hover:no-underline">
                <span className="flex items-center gap-3 pr-2 text-left">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/8">
                    <LayoutDashboard className="size-4 text-primary" />
                  </span>
                  <span className="text-lg font-normal leading-tight">{t("features.screenshotAlt")}</span>
                </span>
              </AccordionTrigger>
              <AccordionContent className="pb-4 pt-1">
                <div className="rounded-xl border border-border/60 bg-muted/25 p-4">
                  <p className="text-sm font-semibold">{t("features.admin.intentName")}</p>
                  <p className="mt-1 text-sm text-muted-foreground">{t("features.admin.intentDesc")}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {adminTabs.map(({ icon: Icon, label }) => (
                      <span key={label} className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-background px-2.5 text-xs text-muted-foreground">
                        <Icon className="size-3.5" />
                        {label}
                      </span>
                    ))}
                  </div>
                </div>
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        </div>

        {/* Feature grid */}
        <div className="mt-20 hidden gap-4 sm:grid sm:grid-cols-2 lg:grid-cols-3">
          {features.map((feature, i) => (
            <div
              key={i}
              className="group rounded-2xl border border-border/60 bg-background p-7 transition-all hover:shadow-md hover:border-border"
            >
              <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl bg-primary/8">
                <feature.icon className="h-5 w-5 text-primary" />
              </div>
              <h3 className="text-[2rem] leading-tight">{feature.title}</h3>
              <p className="mt-3 text-base text-muted-foreground leading-relaxed">
                {feature.desc}
              </p>
            </div>
          ))}
        </div>

        {/* Admin preview */}
        <div className="mx-auto mt-20 hidden max-w-4xl sm:block">
          <div className="rounded-2xl border border-border/60 bg-gradient-to-b from-muted/40 to-muted/10 p-1 shadow-lg shadow-black/[0.03]">
            <div className="overflow-hidden rounded-xl bg-background/90">
              <div className="flex items-center gap-3 border-b border-border/60 px-5 py-4">
                <LayoutDashboard className="h-5 w-5 text-primary" />
                <div>
                  <p className="text-base font-semibold">{t("features.screenshotAlt")}</p>
                  <p className="text-xs text-muted-foreground">
                    {t("features.admin.subtitle")}
                  </p>
                </div>
              </div>
              <div className="grid gap-0 md:grid-cols-[240px_1fr]">
                <div className="border-b border-border/60 bg-muted/25 p-4 md:border-b-0 md:border-r">
                  {adminTabs.map(({ icon: Icon, label }) => (
                    <div
                      key={label}
                      className="mb-2 flex items-center gap-2 rounded-lg px-3 py-2 text-base text-muted-foreground first:bg-background first:text-foreground first:shadow-sm"
                    >
                      <Icon className="h-4 w-4" />
                      {label}
                    </div>
                  ))}
                </div>
                <div className="p-5">
                  <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <p className="text-base font-semibold">
                        {t("features.admin.intentName")}
                      </p>
                      <p className="text-base text-muted-foreground">
                        {t("features.admin.intentDesc")}
                      </p>
                    </div>
                    <span className="w-fit rounded-full bg-emerald-500/10 px-3 py-1 text-xs font-medium text-emerald-700">
                      {t("features.admin.status")}
                    </span>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    {[
                      t("features.admin.card1"),
                      t("features.admin.card2"),
                      t("features.admin.card3"),
                      t("features.admin.card4"),
                    ].map((label) => (
                      <div key={label} className="rounded-lg border border-border/70 p-4">
                        <p className="text-base font-medium">{label}</p>
                        <div className="mt-3 space-y-2">
                          <div className="h-2 rounded bg-muted" />
                          <div className="h-2 w-3/4 rounded bg-muted" />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
