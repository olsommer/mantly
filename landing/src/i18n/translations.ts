export type Language = "en" | "de";

type TranslationKeys = {
  // Brand
  "brand.name": string;

  // Header
  "nav.howItWorks": string;
  "nav.features": string;
  "nav.pricing": string;
  "nav.faq": string;
  "nav.getStarted": string;
  "nav.login": string;
  "nav.sales": string;

  // Hero
  "hero.title": string;
  "hero.subtitle": string;
  "hero.cta": string;
  "hero.ctaHref": string;
  "hero.secondaryCta": string;
  "hero.secondaryHref": string;
  "hero.screenshotAlt": string;
  "hero.badge": string;
  "hero.builtFor": string;
  "hero.mock.subject": string;
  "hero.mock.intent": string;
  "hero.mock.intentName": string;
  "hero.mock.action": string;
  "hero.mock.attachment": string;
  "hero.mock.review": string;
  "hero.mock.draft": string;
  "hero.mock.insertReply": string;
  "hero.mock.source": string;
  "hero.mock.product": string;

  // Problem
  "problem.tagline": string;
  "problem.title": string;
  "problem.subtitle": string;
  "problem.pain1.title": string;
  "problem.pain1.desc": string;
  "problem.pain2.title": string;
  "problem.pain2.desc": string;
  "problem.pain3.title": string;
  "problem.pain3.desc": string;

  // How it works
  "how.tagline": string;
  "how.title": string;
  "how.subtitle": string;
  "how.step1.title": string;
  "how.step1.desc": string;
  "how.step2.title": string;
  "how.step2.desc": string;
  "how.step3.title": string;
  "how.step3.desc": string;
  "how.step4.title": string;
  "how.step4.desc": string;

  // Features
  "features.tagline": string;
  "features.title": string;
  "features.subtitle": string;
  "features.1.title": string;
  "features.1.desc": string;
  "features.2.title": string;
  "features.2.desc": string;
  "features.3.title": string;
  "features.3.desc": string;
  "features.4.title": string;
  "features.4.desc": string;
  "features.5.title": string;
  "features.5.desc": string;
  "features.6.title": string;
  "features.6.desc": string;
  "features.7.title": string;
  "features.7.desc": string;
  "features.8.title": string;
  "features.8.desc": string;
  "features.9.title": string;
  "features.9.desc": string;
  "features.screenshotAlt": string;
  "features.admin.subtitle": string;
  "features.admin.tab.intents": string;
  "features.admin.tab.responses": string;
  "features.admin.tab.attachments": string;
  "features.admin.intentName": string;
  "features.admin.intentDesc": string;
  "features.admin.status": string;
  "features.admin.card1": string;
  "features.admin.card2": string;
  "features.admin.card3": string;
  "features.admin.card4": string;

  // Testimonials
  "testimonials.tagline": string;
  "testimonials.title": string;
  "testimonials.1.title": string;
  "testimonials.1.copy": string;
  "testimonials.2.title": string;
  "testimonials.2.copy": string;
  "testimonials.3.title": string;
  "testimonials.3.copy": string;

  // Pricing
  "pricing.tagline": string;
  "pricing.title": string;
  "pricing.subtitle": string;
  "pricing.month": string;
  "pricing.popular": string;
  "pricing.free.name": string;
  "pricing.free.price": string;
  "pricing.free.desc": string;
  "pricing.free.cta": string;
  "pricing.free.feature1": string;
  "pricing.free.feature2": string;
  "pricing.free.feature3": string;
  "pricing.free.feature4": string;
  "pricing.free.feature5": string;
  "pricing.free.feature6": string;
  "pricing.pro.name": string;
  "pricing.pro.price": string;
  "pricing.pro.desc": string;
  "pricing.pro.cta": string;
  "pricing.pro.feature1": string;
  "pricing.pro.feature2": string;
  "pricing.pro.feature3": string;
  "pricing.pro.feature4": string;
  "pricing.pro.feature5": string;
  "pricing.pro.feature6": string;
  "pricing.pro.feature7": string;
  "pricing.pro.feature8": string;
  "pricing.business.name": string;
  "pricing.business.price": string;
  "pricing.business.desc": string;
  "pricing.business.cta": string;
  "pricing.business.feature1": string;
  "pricing.business.feature2": string;
  "pricing.business.feature3": string;
  "pricing.business.feature4": string;
  "pricing.business.feature5": string;
  "pricing.business.feature6": string;
  "pricing.business.feature7": string;
  "pricing.business.feature8": string;
  "pricing.business.feature9": string;
  "pricing.business.feature10": string;
  "pricing.business.feature11": string;
  "pricing.business.feature12": string;
  "pricing.business.feature13": string;
  "pricing.enterprise.name": string;
  "pricing.enterprise.price": string;
  "pricing.enterprise.desc": string;
  "pricing.enterprise.cta": string;
  "pricing.enterprise.feature1": string;
  "pricing.enterprise.feature2": string;
  "pricing.enterprise.feature3": string;
  "pricing.enterprise.feature4": string;
  "pricing.enterprise.feature5": string;
  "pricing.enterprise.feature6": string;

  // FAQ
  "faq.tagline": string;
  "faq.title": string;
  "faq.q1": string;
  "faq.a1": string;
  "faq.q2": string;
  "faq.a2": string;
  "faq.q3": string;
  "faq.a3": string;
  "faq.q4": string;
  "faq.a4": string;
  "faq.q5": string;
  "faq.a5": string;
  "faq.q6": string;
  "faq.a6": string;

  // CTA
  "cta.title": string;
  "cta.subtitle": string;
  "cta.button": string;

  // Interactive Demo
  "interactiveDemo.title": string;
  "interactiveDemo.subtitle": string;
  "interactiveDemo.scenario": string;
  "interactiveDemo.chooseScenario": string;
  "interactiveDemo.start": string;
  "interactiveDemo.reset": string;
  "interactiveDemo.from": string;
  "interactiveDemo.subject": string;
  "interactiveDemo.attachments": string;
  "interactiveDemo.noAttachments": string;
  "interactiveDemo.addin": string;
  "interactiveDemo.demoMode": string;
  "interactiveDemo.iframeTitle": string;
  "interactiveDemo.empty": string;
  "interactiveDemo.loading": string;
  "interactiveDemo.status.processing": string;
  "interactiveDemo.status.done": string;
  "interactiveDemo.status.preparing": string;
  "interactiveDemo.status.ready": string;

  // Footer
  "footer.tagline": string;
  "footer.support": string;
  "footer.privacy": string;
  "footer.terms": string;
  "footer.imprint": string;
  "footer.rights": string;
};

export type TranslationKey = keyof TranslationKeys;

export const translations: Record<Language, Record<TranslationKey, string>> = {
  en: {
    // Header
    "brand.name": "Mantly",

    // Header
    "nav.howItWorks": "How It Works",
    "nav.features": "Features",
    "nav.pricing": "Pricing",
    "nav.faq": "FAQ",
    "nav.getStarted": "Get Started",
    "nav.login": "Login",
    "nav.sales": "Talk to sales",

    // Hero
    "hero.title": "Handle requests with AI directly in the mailbox.",
    "hero.subtitle":
      "Mantly reads the email, gathers the needed context, prepares the reply, attaches documents, and triggers the right workflow. Your team reviews instead of switching tools, copying data, and writing every answer from scratch.",
    "hero.cta": "Book a demo",
    "hero.ctaHref": "https://app.mantly.io?view=signup",
    "hero.secondaryCta": "Demo",
    "hero.secondaryHref": "#interactive-demo",
    "hero.screenshotAlt": "Mantly in Outlook — AI email analysis",
    "hero.badge": "For Microsoft Outlook & Google Mail",
    "hero.builtFor": "Built for law firms · insurers · consultancies · back-office teams",
    "hero.mock.subject": "Client request: certificate of coverage",
    "hero.mock.intent": "Intent matched",
    "hero.mock.intentName": "Policy document request",
    "hero.mock.action": "Prepared reply",
    "hero.mock.attachment": "Coverage certificate attached",
    "hero.mock.review": "Ready for human review",
    "hero.mock.draft":
      "Thanks for your message. I attached the current certificate and included the policy details below.",
    "hero.mock.insertReply": "Insert reply",
    "hero.mock.source": "Outlook",
    "hero.mock.product": "Mantly",

    // Problem
    "problem.tagline": "Why teams buy",
    "problem.title": "Routine cases get slow when work is split across tools.",
    "problem.subtitle":
      "Every repeated email becomes slower when teams open multiple systems, copy details by hand, and write the same response again.",
    "problem.pain1.title": "Jumping between systems",
    "problem.pain1.desc":
      "CRM, case files, documents, internal tools, then Outlook again. Mantly keeps the workflow inside the inbox.",
    "problem.pain2.title": "Manual email drafting",
    "problem.pain2.desc":
      "Your team should review good answers, not write every routine email from an empty composer.",
    "problem.pain3.title": "Slow case handling",
    "problem.pain3.desc":
      "Recurring requests that should take minutes turn into long handoffs. Automation shortens the path from email to done.",
    // How it works
    "how.tagline": "How It Works",
    "how.title": "From incoming email to finished case.",
    "how.subtitle":
      "Mantly brings the process into Outlook: context, email copy, documents, workflow triggers, and final review.",
    "how.step1.title": "Read the request",
    "how.step1.desc":
      "The add-in understands what the customer needs directly from the email.",
    "how.step2.title": "Collect context",
    "how.step2.desc":
      "Mantly pulls the needed CRM, case, policy, or document data without making users jump between tools.",
    "how.step3.title": "Prepare reply and actions",
    "how.step3.desc":
      "It writes the email copy, selects attachments, and starts the configured workflow when needed.",
    "how.step4.title": "Review and finish",
    "how.step4.desc":
      "Your team checks the result, adjusts if needed, and finishes the case from Outlook.",

    // Features
    "features.tagline": "Features",
    "features.title": "Automation where the case already starts.",
    "features.subtitle":
      "Less switching, less copying, less manual email writing. More cases finished from one place.",
    "features.1.title": "Prompt-injection guard",
    "features.1.desc":
      "Incoming content is checked for instructions that try to manipulate the assistant or workflow.",
    "features.2.title": "Phishing detection",
    "features.2.desc":
      "Suspicious senders, links, and message patterns are flagged before a workflow continues.",
    "features.3.title": "Evaluations",
    "features.3.desc":
      "Test cases help teams compare outputs, regressions, and prompt quality before changes go live.",
    "features.4.title": "Monitoring and token spend",
    "features.4.desc":
      "Usage, runs, costs, and model activity stay visible in the admin dashboard.",
    "features.5.title": "REST integrations",
    "features.5.desc":
      "Internal systems can be connected through REST actions for lookups, updates, and handoffs.",
    "features.6.title": "Own LLM proxy",
    "features.6.desc":
      "Route model calls through your preferred gateway or proxy when IT requires it.",
    "features.7.title": "Versioning",
    "features.7.desc":
      "Prompts, rules, documents, and workflows can be changed with clearer rollout control.",
    "features.8.title": "Continuous learning",
    "features.8.desc":
      "Feedback loops turn human corrections into better future drafts and decisions.",
    "features.9.title": "On-premise ready",
    "features.9.desc":
      "Mantly can also run on-premise for controlled enterprise environments.",
    "features.screenshotAlt": "Admin Dashboard",
    "features.admin.subtitle": "Control monitor, preview, publishing, and evaluation",
    "features.admin.tab.intents": "Editor",
    "features.admin.tab.responses": "Evaluation",
    "features.admin.tab.attachments": "Monitor",
    "features.admin.intentName": "Pipeline",
    "features.admin.intentDesc": "Customer identification + intent detection + preview",
    "features.admin.status": "Active",
    "features.admin.card1": "Actions",
    "features.admin.card2": "Tools",
    "features.admin.card3": "Response",
    "features.admin.card4": "Instructions",

    // Testimonials
    "testimonials.tagline": "Use cases",
    "testimonials.title": "Best for repetitive cases that start in the inbox.",
    "testimonials.1.title": "Legal and tax services",
    "testimonials.1.copy":
      "Shorten recurring client requests by preparing context, wording, and documents before the expert reviews.",
    "testimonials.2.title": "Insurance and policy teams",
    "testimonials.2.copy":
      "Prepare certificates, coverage replies, and policy updates directly from Outlook.",
    "testimonials.3.title": "Customer operations",
    "testimonials.3.copy":
      "Turn repetitive inbox requests into structured workflows with reviewable AI drafts.",

    // Pricing
    "pricing.tagline": "Pricing",
    "pricing.title": "Start small. Scale when inbox work grows.",
    "pricing.subtitle":
      "Prepared emails, evaluations, feedback learning, and controls scale with each plan.",
    "pricing.month": "/mo",
    "pricing.popular": "Recommended",
    "pricing.free.name": "Free",
    "pricing.free.price": "0 EUR",
    "pricing.free.desc": "Validate Mantly with one small workflow.",
    "pricing.free.cta": "Start free",
    "pricing.free.feature1": "20 emails/month",
    "pricing.free.feature2": "1 project",
    "pricing.free.feature3": "1 user",
    "pricing.free.feature4": "1 evaluation set",
    "pricing.free.feature5": "Run tracking",
    "pricing.free.feature6": "One-click Preview & Publish",
    "pricing.pro.name": "Pro",
    "pricing.pro.price": "19 EUR",
    "pricing.pro.desc": "For individuals who want reliable response generation.",
    "pricing.pro.cta": "Start Pro",
    "pricing.pro.feature1": "150 emails/month",
    "pricing.pro.feature2": "1 project included",
    "pricing.pro.feature3": "1 user included, extra users 9 EUR/month",
    "pricing.pro.feature4": "5 evaluation sets",
    "pricing.pro.feature5": "Feedback learnings",
    "pricing.pro.feature6": "Run tracking",
    "pricing.pro.feature7": "One-click Preview & Publish",
    "pricing.pro.feature8": "BYOK LLMs",
    "pricing.business.name": "Business",
    "pricing.business.price": "199 EUR",
    "pricing.business.desc": "For teams that need control, learning, and security.",
    "pricing.business.cta": "Start Business",
    "pricing.business.feature1": "1,000 emails/month",
    "pricing.business.feature2": "1 project included",
    "pricing.business.feature3": "5 users included",
    "pricing.business.feature4": "Unlimited evaluations",
    "pricing.business.feature5": "Feedback learnings",
    "pricing.business.feature6": "Run tracking and higher retention",
    "pricing.business.feature7": "One-click Preview & Publish",
    "pricing.business.feature8": "BYOK LLMs",
    "pricing.business.feature9": "Phishing monitoring",
    "pricing.business.feature10": "Prompt-injection monitoring",
    "pricing.business.feature11": "SSO and RBAC available",
    "pricing.business.feature12": "On-premise or dedicated deployment available",
    "pricing.business.feature13": "Extra users from 9 EUR/month",
    "pricing.enterprise.name": "Enterprise",
    "pricing.enterprise.price": "Custom",
    "pricing.enterprise.desc": "For regulated teams with procurement, security, or deployment needs.",
    "pricing.enterprise.cta": "Talk to sales",
    "pricing.enterprise.feature1": "Everything in Business",
    "pricing.enterprise.feature2": "SOC 2 and ISO 27001 reports",
    "pricing.enterprise.feature3": "Extended audit logs and retention",
    "pricing.enterprise.feature4": "Uptime and support SLA",
    "pricing.enterprise.feature5": "Invoice billing and vendor onboarding",
    "pricing.enterprise.feature6": "On-premise or dedicated deployment available",

    // FAQ
    "faq.tagline": "FAQ",
    "faq.title": "Common questions.",
    "faq.q1": "What is Mantly?",
    "faq.a1":
      "An Outlook add-in and admin platform that helps teams finish repetitive email cases faster. It reads the message, collects context, drafts the reply, prepares documents, and triggers configured workflow steps.",
    "faq.q2": "How does it integrate with Outlook?",
    "faq.a2":
      "It runs as an Outlook add-in. Users work in a sidebar panel and avoid jumping between systems for routine cases.",
    "faq.q3": "Is my email data secure?",
    "faq.a3":
      "Mantly can run on your own infrastructure and connect to your preferred LLM gateway. That lets your IT team keep data handling aligned with internal security and GDPR requirements.",
    "faq.q4": "How long does setup take?",
    "faq.a4":
      "A focused pilot can start once one repetitive case, sample emails, and target systems are clear. We configure that workflow together with your operations team.",
    "faq.q5": "What languages are supported?",
    "faq.a5":
      "German and English are supported out of the box. Multilingual workflows can be configured per team and use case.",
    "faq.q6": "Do I need technical knowledge?",
    "faq.a6":
      "No coding is required for normal intent, action, prompt, and attachment updates. Technical teams can still control deployment and integrations.",

    // CTA
    "cta.title": "Pick one repetitive case. We shorten it.",
    "cta.subtitle":
      "Choose one high-volume request. We map the workflow, connect the context, automate the reply copy, and show how it can be finished from Outlook.",
    "cta.button": "Book a demo",

    // Interactive Demo
    "interactiveDemo.title": "Interactive demo",
    "interactiveDemo.subtitle": "Choose a case and start the demo",
    "interactiveDemo.scenario": "Scenario",
    "interactiveDemo.chooseScenario": "Choose scenario",
    "interactiveDemo.start": "Start demo",
    "interactiveDemo.reset": "Reset",
    "interactiveDemo.from": "From",
    "interactiveDemo.subject": "Subject",
    "interactiveDemo.attachments": "Attachments",
    "interactiveDemo.noAttachments": "none",
    "interactiveDemo.addin": "MANTLY ADD-IN",
    "interactiveDemo.demoMode": "Demo mode",
    "interactiveDemo.iframeTitle": "Mantly add-in example demo",
    "interactiveDemo.empty": "Choose a scenario on the left and start the demo.",
    "interactiveDemo.loading": "Interactive demo loading",
    "interactiveDemo.status.processing": "Analysis running in the add-in",
    "interactiveDemo.status.done": "Demo result loaded",
    "interactiveDemo.status.preparing": "Add-in preparing",
    "interactiveDemo.status.ready": "Add-in ready",

    // Footer
    "footer.tagline": "Outlook automation for faster client-case handling.",
    "footer.support": "Support",
    "footer.privacy": "Privacy Policy",
    "footer.terms": "Terms",
    "footer.imprint": "Imprint",
    "footer.rights": "All rights reserved.",
  },

  de: {
    // Header
    "brand.name": "Mantly",

    // Header
    "nav.howItWorks": "Lösung",
    "nav.features": "Funktionen",
    "nav.pricing": "Preise",
    "nav.faq": "FAQ",
    "nav.getStarted": "Jetzt starten",
    "nav.login": "Anmelden",
    "nav.sales": "Vertrieb kontaktieren",

    // Hero
    "hero.title": "Anliegen direkt in der Mailbox mit KI bearbeiten",
    "hero.subtitle":
      "Mantly erkennt den Kunden, findet den passenden Vorgang, erstellt Antworten und bereitet Workflows vor. Ohne die Kontrolle zu verlieren. Für maximale Effizienz.",
    "hero.cta": "Loslegen",
    "hero.ctaHref": "https://app.mantly.io?view=signup",
    "hero.secondaryCta": "Demo",
    "hero.secondaryHref": "#interactive-demo",
    "hero.screenshotAlt": "Mantly in Outlook — KI-E-Mail-Analyse",
    "hero.badge": "Für Microsoft Outlook & Google Mail",
    "hero.builtFor": "Für Kanzleien · Versicherungen · Beratungen · Backoffice-Teams",
    "hero.mock.subject": "Kundenanfrage: Versicherungsbestätigung",
    "hero.mock.intent": "Intent erkannt",
    "hero.mock.intentName": "Dokumentenanfrage",
    "hero.mock.action": "Antwort vorbereitet",
    "hero.mock.attachment": "Bestätigung angehängt",
    "hero.mock.review": "Bereit zur Prüfung",
    "hero.mock.draft":
      "Vielen Dank für Ihre Nachricht. Die aktuelle Bestätigung finden Sie im Anhang.",
    "hero.mock.insertReply": "Antwort übernehmen",
    "hero.mock.source": "Outlook",
    "hero.mock.product": "Mantly",

    // Problem
    "problem.tagline": "Problem",
    "problem.title": "Der Workflow rund um E-Mail-Anliegen ist zu verteilt.",
    "problem.subtitle": "",
    "problem.pain1.title": "Wechsel zwischen Systemen",
    "problem.pain1.desc":
      "CRM, Akte, Dokumente, interne Tools, dann zurück zu Outlook. Jedes Anliegen zerfällt in Klicks statt in Ergebnisse.",
    "problem.pain2.title": "Manuelle Routinearbeit",
    "problem.pain2.desc":
      "Immer wieder die gleiche Antwort schreiben, die gleichen Infos nachsehen, die gleichen Dokumente anhängen.",
    "problem.pain3.title": "Einfache Anfragen ziehen sich",
    "problem.pain3.desc":
      "Was in 2 Minuten erledigt sein könnte, kann schnell 15 Minuten dauern – weil Schritte verteilt sind und ständig unterbrochen werden.",
    // How it works
    "how.tagline": "Workflow",
    "how.title": "Im Posteingang zum erledigten Anliegen",
    "how.subtitle": "",
    "how.step1.title": "Kunden überprüfen",
    "how.step1.desc":
      "Erkennt den Absender und gleicht ihn mit den vorhandenen CRM-Daten ab.",
    "how.step2.title": "Anliegen erkennen",
    "how.step2.desc":
      "Analysiert die Anfrage, erkennt relevante Informationen und ergänzt bei Bedarf fehlenden Kontext.",
    "how.step3.title": "Prozesse vorbereiten",
    "how.step3.desc":
      "Erstellt eine Antwort und bereitet die nächsten Schritte vor.",
    "how.step4.title": "Menschliche Kontrolle",
    "how.step4.desc":
      "Keine Antwort wird ohne Prüfung verschickt. Kein Prozess wird ohne Prüfung gestartet",

    // Features
    "features.tagline": "Funktionen",
    "features.title": "Automatisierung dort, wo das Anliegen beginnt.",
    "features.subtitle": "",
    "features.1.title": "Prompt-Injection-Schutz",
    "features.1.desc":
      "Eingehende E-Mails werden auf gefährliche Anweisungen überprüft.",
    "features.2.title": "Phishing-Erkennung",
    "features.2.desc":
      "Es wird vor verdächtigen Absendern, Links und Mustern gewarnt.",
    "features.3.title": "Evaluationen",
    "features.3.desc":
      "Qualität der Pipeline vor dem Deployment kontinuierlich testen.",
    "features.4.title": "Monitoring & Token Spending",
    "features.4.desc":
      "Runs, Nutzung, Kosten und Modellaktivität bleiben im Admin-Dashboard transparent.",
    "features.5.title": "Interne Systeme einfach über REST anbinden",
    "features.5.desc":
      "Lookups, Updates und Übergaben können mit internen Systemen verbunden werden.",
    "features.6.title": "Eigener Proxy für das LLM",
    "features.6.desc":
      "LLMs können über ein eigenes Gateway oder Proxy laufen.",
    "features.7.title": "Versionierung",
    "features.7.desc":
      "Prompts, Regeln, Dokumente und Workflows lassen sich kontrolliert ändern und ausrollen.",
    "features.8.title": "Kontinuierliches Lernen",
    "features.8.desc":
      "Feedback-Schleifen machen menschliche Korrekturen für zukünftige Entwürfe nutzbar.",
    "features.9.title": "On-premise",
    "features.9.desc": "Mantly läuft auch on-premise.",
    "features.screenshotAlt": "Admin-Dashboard",
    "features.admin.subtitle": "Monitor, Vorschau & Veröffentlichung und Evaluation zentral steuern",
    "features.admin.tab.intents": "Editor",
    "features.admin.tab.responses": "Evaluation",
    "features.admin.tab.attachments": "Monitor",
    "features.admin.intentName": "Pipeline",
    "features.admin.intentDesc": "Kundenidentifikation + Anliegenerkennung + Vorschau",
    "features.admin.status": "Aktiv",
    "features.admin.card1": "Aktionen",
    "features.admin.card2": "Tools",
    "features.admin.card3": "Antwort",
    "features.admin.card4": "Instruktionen",

    // Testimonials
    "testimonials.tagline": "Anliegen",
    "testimonials.title": "Für wiederkehrende Anliegen, die im Postfach starten.",
    "testimonials.1.title": "Kanzlei und Steuerberatung",
    "testimonials.1.copy":
      "Wiederkehrende Erstanfragen und Standardrückfragen automatisiert vorbereiten – inklusive Kontext und Dokumenten.",
    "testimonials.2.title": "Versicherungs- und Vertragsteams",
    "testimonials.2.copy":
      "Bestätigungen, Deckungsanfragen und Vertragsupdates vorbereiten lassen – und in der Mailbox nur noch prüfen und versenden.",
    "testimonials.3.title": "Support- & Service-Teams",
    "testimonials.3.copy":
      "Standard-Anfragen automatisch vorbereiten, damit mehr Zeit für komplexe Anliegen bleibt.",

    // Pricing
    "pricing.tagline": "Preise",
    "pricing.title": "Klein starten. Mit dem Postfach wachsen.",
    "pricing.subtitle":
      "E-Mails, Evaluationen, Feedback-Learnings und Kontrollen skalieren mit jedem Plan.",
    "pricing.month": "/Monat",
    "pricing.popular": "Empfohlen",
    "pricing.free.name": "Free",
    "pricing.free.price": "0 EUR",
    "pricing.free.desc": "Einen Workflow mit niedrigem Volumen validieren.",
    "pricing.free.cta": "Kostenlos starten",
    "pricing.free.feature1": "20 E-Mails/Monat",
    "pricing.free.feature2": "1 Projekt",
    "pricing.free.feature3": "1 Nutzer",
    "pricing.free.feature4": "1 Evaluations-Set",
    "pricing.free.feature5": "Run-Tracking",
    "pricing.free.feature6": "One-Click Preview & Publish",
    "pricing.pro.name": "Pro",
    "pricing.pro.price": "19 EUR",
    "pricing.pro.desc": "Für Einzelpersonen, die verlässliche Antwortgenerierung nutzen wollen.",
    "pricing.pro.cta": "Pro starten",
    "pricing.pro.feature1": "150 E-Mails/Monat",
    "pricing.pro.feature2": "1 Projekt inklusive",
    "pricing.pro.feature3": "1 Nutzer inklusive, Zusatznutzer 9 EUR/Monat",
    "pricing.pro.feature4": "5 Evaluations-Sets",
    "pricing.pro.feature5": "Feedback-Learnings",
    "pricing.pro.feature6": "Run-Tracking",
    "pricing.pro.feature7": "One-Click Preview & Publish",
    "pricing.pro.feature8": "BYOK-LLMs",
    "pricing.business.name": "Business",
    "pricing.business.price": "199 EUR",
    "pricing.business.desc": "Für Teams, die Kontrolle, Lernen und Sicherheit brauchen.",
    "pricing.business.cta": "Business starten",
    "pricing.business.feature1": "1.000 E-Mails/Monat",
    "pricing.business.feature2": "1 Projekt inklusive",
    "pricing.business.feature3": "5 Nutzer inklusive",
    "pricing.business.feature4": "Unlimitierte Evaluationen",
    "pricing.business.feature5": "Feedback-Learnings",
    "pricing.business.feature6": "Run-Tracking & höhere Retention",
    "pricing.business.feature7": "One-Click Preview & Publish",
    "pricing.business.feature8": "BYOK-LLMs",
    "pricing.business.feature9": "Phishing-Überwachung",
    "pricing.business.feature10": "Prompt-Injection-Überwachung",
    "pricing.business.feature11": "SSO und RBAC möglich",
    "pricing.business.feature12": "On-premise oder dediziertes Deployment möglich",
    "pricing.business.feature13": "Zusatznutzer ab 9 EUR/Monat",
    "pricing.enterprise.name": "Enterprise",
    "pricing.enterprise.price": "Individuell",
    "pricing.enterprise.desc": "Für regulierte Teams mit Procurement, Security oder Deployment-Anforderungen.",
    "pricing.enterprise.cta": "Sales kontaktieren",
    "pricing.enterprise.feature1": "Alles aus Business",
    "pricing.enterprise.feature2": "SOC 2- und ISO 27001-Reports",
    "pricing.enterprise.feature3": "Erweiterte Audit-Logs und Retention",
    "pricing.enterprise.feature4": "Uptime- und Support-SLA",
    "pricing.enterprise.feature5": "Rechnungskauf und Vendor Onboarding",
    "pricing.enterprise.feature6": "On-premise oder dediziertes Deployment möglich",

    // FAQ
    "faq.tagline": "FAQ",
    "faq.title": "Häufige Fragen.",
    "faq.q1": "Was ist Mantly?",
    "faq.a1":
      "Ein Outlook-Add-in mit Admin-Plattform, das Teams hilft, wiederkehrende E-Mail-Anliegen schneller zu erledigen. Es liest die Nachricht, holt Kontext, schreibt den Antwortentwurf, bereitet Dokumente vor und startet konfigurierte Workflow-Schritte.",
    "faq.q2": "Wie integriert sich Mantly in Outlook?",
    "faq.a2":
      "Mantly läuft als Outlook-Add-in. Nutzer arbeiten in einer Seitenleiste und vermeiden Toolwechsel bei Routinefällen.",
    "faq.q3": "Sind meine Daten sicher?",
    "faq.a3":
      "Mantly kann auf eigener Infrastruktur laufen und an ein bevorzugtes LLM-Gateway angebunden werden. So bleibt die Datenverarbeitung an interne Sicherheits- und DSGVO-Anforderungen angepasst.",
    "faq.q4": "Wie lange dauert die Einrichtung?",
    "faq.a4":
      "Ein fokussierter Pilot kann starten, sobald ein wiederkehrendes Anliegen, Beispiel-E-Mails und Zielsysteme klar sind. Wir konfigurieren diesen Workflow gemeinsam mit dem Operations-Team.",
    "faq.q5": "Welche Sprachen werden unterstützt?",
    "faq.a5":
      "Deutsch und Englisch werden ab Werk unterstützt. Mehrsprachige Workflows können pro Team und Anliegen konfiguriert werden.",
    "faq.q6": "Brauche ich technisches Wissen?",
    "faq.a6":
      "Für normale Intent-, Aktions-, Prompt- und Anlagenpflege ist kein Code nötig. Technische Teams behalten trotzdem Kontrolle über Betrieb und Integrationen.",

    // CTA
    "cta.title": "Wiederkehrende Anliegen? Wir verkürzen es.",
    "cta.subtitle":
      "Wir mappen den Workflow, binden Kontext an, automatisieren den Antworttext und zeigen, wie das Anliegen aus der Mailbox erledigt wird.",
    "cta.button": "Demo buchen",

    // Interactive Demo
    "interactiveDemo.title": "Interaktive Demo",
    "interactiveDemo.subtitle": "Wähle ein Anliegen und starte die Demo",
    "interactiveDemo.scenario": "Szenario",
    "interactiveDemo.chooseScenario": "Szenario auswählen",
    "interactiveDemo.start": "Demo starten",
    "interactiveDemo.reset": "Zurücksetzen",
    "interactiveDemo.from": "Von",
    "interactiveDemo.subject": "Betreff",
    "interactiveDemo.attachments": "Anlagen",
    "interactiveDemo.noAttachments": "keine",
    "interactiveDemo.addin": "MANTLY-ADDIN",
    "interactiveDemo.demoMode": "Demo Modus",
    "interactiveDemo.iframeTitle": "Mantly Add-in Beispieldemo",
    "interactiveDemo.empty": "Wähle links ein Szenario und starte die Demo.",
    "interactiveDemo.loading": "Interaktive Demo wird geladen",
    "interactiveDemo.status.processing": "Analyse läuft im Add-in",
    "interactiveDemo.status.done": "Demo-Ergebnis geladen",
    "interactiveDemo.status.preparing": "Add-in wird vorbereitet",
    "interactiveDemo.status.ready": "Add-in bereit",

    // Footer
    "footer.tagline": "Outlook-Automatisierung für schnellere Kundenanliegen.",
    "footer.support": "Support",
    "footer.privacy": "Datenschutz",
    "footer.terms": "Nutzungsbedingungen",
    "footer.imprint": "Impressum",
    "footer.rights": "Alle Rechte vorbehalten.",
  },
};
