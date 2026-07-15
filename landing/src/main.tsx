import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import posthog from "posthog-js";
import { PostHogProvider } from "@posthog/react";
import "@/index.css";
import { App } from "./App";
import { LanguageProvider } from "@/i18n/LanguageContext";
import { POSTHOG_HOST, POSTHOG_TOKEN } from "@/lib/posthog";

posthog.init(POSTHOG_TOKEN, {
  api_host: POSTHOG_HOST,
  capture_pageview: true,
  cookieless_mode: "always",
  defaults: "2026-01-30",
  disable_session_recording: true,
  person_profiles: "identified_only",
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <PostHogProvider client={posthog}>
      <LanguageProvider>
        <App />
      </LanguageProvider>
    </PostHogProvider>
  </StrictMode>
);
