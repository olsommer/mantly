import { lazy, Suspense } from "react";
import { Header } from "@/components/Header";
import { HeroSection } from "@/components/HeroSection";
import { ProblemSection } from "@/components/ProblemSection";
import { HowItWorks } from "@/components/HowItWorks";
import { FeaturesSection } from "@/components/FeaturesSection";
import { PricingSection } from "@/components/PricingSection";
import { FAQSection } from "@/components/FAQSection";
import { CTASection } from "@/components/CTASection";
import { DemoLauncher } from "@/components/DemoLauncher";
import { Footer } from "@/components/Footer";
import { SeoMetadata, type LandingPage } from "@/components/SeoMetadata";
import { LegalPage } from "@/pages/LegalPage";
import { SupportPage } from "@/pages/SupportPage";
import { stripLanguagePrefix } from "@/i18n/language-routing";
import { useTranslation } from "@/i18n/useTranslation";

const PilotPlaybookPage = lazy(() =>
  import("@/pages/PilotPlaybookPage").then((module) => ({
    default: module.PilotPlaybookPage,
  }))
);

function getPage(): LandingPage {
  const path = stripLanguagePrefix(window.location.pathname).replace(/\/+$/, "") || "/";
  if (path === "/datenschutz" || path === "/privacy") return "privacy";
  if (path === "/impressum" || path === "/imprint") return "imprint";
  if (path === "/nutzungsbedingungen" || path === "/terms") return "terms";
  if (path === "/support" || path === "/hilfe") return "support";
  if (path === "/page") return "pilot";
  return "home";
}

export function App() {
  const page = getPage();
  const { t } = useTranslation();

  return (
    <div className="min-h-screen bg-background text-foreground">
      <SeoMetadata page={page} />
      <a
        href="#main-content"
        className="fixed left-4 top-3 z-[60] -translate-y-20 rounded-md bg-background px-4 py-2 text-sm font-medium text-foreground shadow-lg transition-transform focus:translate-y-0 focus:outline-none focus:ring-2 focus:ring-ring"
      >
        {t("a11y.skipToContent")}
      </a>
      <Header />
      {page === "privacy" ? (
        <div id="main-content" tabIndex={-1}><LegalPage kind="privacy" /></div>
      ) : page === "imprint" ? (
        <div id="main-content" tabIndex={-1}><LegalPage kind="imprint" /></div>
      ) : page === "terms" ? (
        <div id="main-content" tabIndex={-1}><LegalPage kind="terms" /></div>
      ) : page === "support" ? (
        <div id="main-content" tabIndex={-1}><SupportPage /></div>
      ) : page === "pilot" ? (
        <div id="main-content" tabIndex={-1}>
          <Suspense fallback={<main className="min-h-screen bg-white" />}>
            <PilotPlaybookPage />
          </Suspense>
        </div>
      ) : (
        <>
          <main id="main-content" tabIndex={-1}>
            <HeroSection />
            <ProblemSection />
            <HowItWorks />
            <FeaturesSection />
            <PricingSection />
            <FAQSection />
            <CTASection />
          </main>
          <DemoLauncher />
        </>
      )}
      <Footer />
    </div>
  );
}
