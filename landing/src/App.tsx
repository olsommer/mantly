import { lazy, Suspense } from "react";
import { Header } from "@/components/Header";
import { HeroSection } from "@/components/HeroSection";
import { ProblemSection } from "@/components/ProblemSection";
import { HowItWorks } from "@/components/HowItWorks";
import { FeaturesSection } from "@/components/FeaturesSection";
import { TestimonialsSection } from "@/components/TestimonialsSection";
import { PricingSection } from "@/components/PricingSection";
import { FAQSection } from "@/components/FAQSection";
import { CTASection } from "@/components/CTASection";
import { Footer } from "@/components/Footer";
import { LegalPage } from "@/pages/LegalPage";
import { SupportPage } from "@/pages/SupportPage";
import { stripLanguagePrefix } from "@/i18n/language-routing";

const PilotPlaybookPage = lazy(() =>
  import("@/pages/PilotPlaybookPage").then((module) => ({
    default: module.PilotPlaybookPage,
  }))
);

function getPage() {
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

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Header />
      {page === "privacy" ? (
        <LegalPage kind="privacy" />
      ) : page === "imprint" ? (
        <LegalPage kind="imprint" />
      ) : page === "terms" ? (
        <LegalPage kind="terms" />
      ) : page === "support" ? (
        <SupportPage />
      ) : page === "pilot" ? (
        <Suspense fallback={<main className="min-h-screen bg-white" />}>
          <PilotPlaybookPage />
        </Suspense>
      ) : (
        <main>
          <HeroSection />
          <ProblemSection />
          <HowItWorks />
          <FeaturesSection />
          <TestimonialsSection />
          <PricingSection />
          <FAQSection />
          <CTASection />
        </main>
      )}
      <Footer />
    </div>
  );
}
