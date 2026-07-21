export type Language = "en" | "de";

const en = {
  "brand.name": "Mantly",

  "nav.howItWorks": "How it works",
  "nav.product": "Product",
  "nav.pricing": "Pricing",
  "nav.docs": "Docs",
  "nav.github": "GitHub",
  "nav.login": "Sign in",
  "nav.cloud": "Start Cloud",
  "a11y.openMenu": "Open navigation menu",
  "a11y.closeMenu": "Close navigation menu",
  "a11y.switchToGerman": "Switch language to German",
  "a11y.switchToEnglish": "Switch language to English",
  "a11y.skipToContent": "Skip to main content",

  "hero.title": "Customer support that runs itself — under your rules.",
  "hero.subtitle":
    "Mantly turns messages from connected channels into tickets handled under your rules. It detects every concern, follows your runbooks with trusted knowledge and tools, and composes one grounded reply. Self-host it or use Mantly Cloud.",
  "hero.cta": "Start Cloud",
  "hero.ctaHref": "https://app.mantly.io?view=signup",
  "hero.secondaryCta": "View on GitHub",
  "hero.secondaryHref": "https://github.com/olsommer/mantly",
  "hero.selfHostCta": "Read the self-hosting docs",
  "hero.demoCta": "Watch one ticket",
  "hero.badge": "Open source · Self-hosted or Mantly Cloud",
  "hero.builtFor": "One support system · Connected channels · Your policies",

  "problem.tagline": "Outcomes",
  "problem.title": "Automate the whole support case — not only the reply.",
  "problem.subtitle":
    "Mantly keeps triage, research, actions, and the final answer in one governed workflow.",
  "problem.pain1.title": "Full-case execution",
  "problem.pain1.desc":
    "Move from an inbound message to a resolved ticket with context, actions, and communication handled together.",
  "problem.pain2.title": "Company control",
  "problem.pain2.desc":
    "Your runbooks define what the agent should do, which tools it may use, and when a human must approve.",
  "problem.pain3.title": "One coherent answer",
  "problem.pain3.desc":
    "Handle multiple concerns independently, then combine their evidence and outcomes into one customer reply.",

  "how.tagline": "How it works",
  "how.title": "One message in. One governed outcome.",
  "how.subtitle":
    "Each inbound customer message is processed as one agent run, even when it contains several concerns.",
  "how.step1.title": "Create one ticket",
  "how.step1.desc":
    "Messages from connected channels enter the Inbox as a single support ticket.",
  "how.step2.title": "Activate matching runbooks",
  "how.step2.desc":
    "Mantly detects concerns in the message and runs the matching company-defined workflows independently.",
  "how.step3.title": "Gather facts and act",
  "how.step3.desc":
    "Knowledge and tools add trusted evidence, while permitted actions update the systems involved.",
  "how.step4.title": "Compose one answer",
  "how.step4.desc":
    "The Inbox composer combines matched runbook results into one grounded reply for approval or automatic delivery.",

  "features.tagline": "Product",
  "features.title": "The support operating system your team controls.",
  "features.subtitle":
    "Open infrastructure, explicit workflows, grounded answers, and reviewable execution history in one platform.",
  "features.1.title": "Open source",
  "features.1.desc":
    "Inspect, adapt, and operate the core platform on infrastructure you control.",
  "features.2.title": "Omnichannel Inbox",
  "features.2.desc":
    "Bring customer messages into one ticket system instead of running a separate process per channel.",
  "features.3.title": "Multi-concern runbooks",
  "features.3.desc":
    "Match and process detected concerns separately without generating fragmented customer answers.",
  "features.4.title": "One response composer",
  "features.4.desc":
    "Turn matched runbook outcomes, evidence, and actions into one consistent final reply.",
  "features.5.title": "Grounded knowledge",
  "features.5.desc":
    "Research against ticket-scoped knowledge and keep citations available for review.",
  "features.6.title": "Tools and actions",
  "features.6.desc":
    "Connect internal systems for lookups, updates, handoffs, and other permitted work.",
  "features.7.title": "Human control",
  "features.7.desc":
    "Choose manual, approval-based, or automatic execution according to company policy.",
  "features.8.title": "Evaluations before publish",
  "features.8.desc":
    "Test runbook and response behavior against repeatable cases before changes reach customers.",
  "features.9.title": "Self-host or Cloud",
  "features.9.desc":
    "Operate Mantly yourself or let Mantly Cloud manage the application for you.",
  "features.screenshotAlt": "Mantly Admin",
  "features.admin.subtitle": "Inspect concerns, sources, actions, and final answers",
  "features.admin.tab.intents": "Runbooks",
  "features.admin.tab.responses": "Evaluations",
  "features.admin.tab.attachments": "Execution history",
  "features.admin.intentName": "Support automation",
  "features.admin.intentDesc": "Concerns, evidence, actions, and one final reply",
  "features.admin.status": "Active",
  "features.admin.card1": "Concerns",
  "features.admin.card2": "Knowledge & tools",
  "features.admin.card3": "Actions",
  "features.admin.card4": "Final reply",

  "pillars.tagline": "Built as one system",
  "pillars.title": "Inbox, agents, and evidence stay connected.",
  "pillars.1.title": "Inbox",
  "pillars.1.copy":
    "The system of record for tickets, concerns, actions, approvals, and customer responses.",
  "pillars.2.title": "Runbook Agent",
  "pillars.2.copy":
    "Applies your operating procedures concern by concern and returns structured results to the ticket.",
  "pillars.3.title": "Knowledge Agent",
  "pillars.3.copy":
    "Finds ticket-relevant facts, preserves citations, and makes the evidence reviewable by humans.",

  "pricing.tagline": "Pricing",
  "pricing.title": "Open source when you want control. Cloud when you want speed.",
  "pricing.subtitle":
    "Start with the full core platform, then choose managed operations or added governance as your team grows.",
  "pricing.month": "/mo",
  "pricing.popular": "Recommended",
  "pricing.community.name": "Community",
  "pricing.community.price": "Free",
  "pricing.community.desc": "For teams that want to run Mantly themselves.",
  "pricing.community.cta": "View on GitHub",
  "pricing.community.feature1": "Self-hosted Mantly",
  "pricing.community.feature2": "Full core platform",
  "pricing.community.feature3": "Unlimited local agent runs",
  "pricing.community.feature4": "Bring your own model keys",
  "pricing.community.feature5": "Runbooks, knowledge, and tools",
  "pricing.community.feature6": "Community support",
  "pricing.cloud.name": "Cloud",
  "pricing.cloud.price": "19 EUR",
  "pricing.cloud.desc": "For support teams that want Mantly managed for them.",
  "pricing.cloud.cta": "Start Cloud",
  "pricing.cloud.feature1": "Managed Mantly Cloud",
  "pricing.cloud.feature2": "150 agent runs/month",
  "pricing.cloud.feature3": "1 project included",
  "pricing.cloud.feature4": "Unlimited team members",
  "pricing.cloud.feature5": "Managed application updates",
  "pricing.cloud.feature6": "5 evaluation sets",
  "pricing.cloud.feature7": "Run tracking and feedback learnings",
  "pricing.cloud.feature8": "Bring your own model keys",
  "pricing.business.name": "Business",
  "pricing.business.price": "199 EUR",
  "pricing.business.desc": "For teams that need more governance and volume.",
  "pricing.business.cta": "Talk to sales",
  "pricing.business.feature1": "1,000 agent runs/month",
  "pricing.business.feature2": "10 projects included",
  "pricing.business.feature3": "Unlimited team members",
  "pricing.business.feature4": "Unlimited evaluations",
  "pricing.business.feature5": "Roles and approval controls",
  "pricing.business.feature6": "Run tracking with higher retention",
  "pricing.business.feature7": "Phishing and prompt-injection monitoring",
  "pricing.business.feature8": "Feedback proposals",
  "pricing.enterprise.name": "Enterprise",
  "pricing.enterprise.price": "Custom",
  "pricing.enterprise.desc": "For deployment, procurement, and integration requirements.",
  "pricing.enterprise.cta": "Talk to sales",
  "pricing.enterprise.feature1": "Everything in Business",
  "pricing.enterprise.feature2": "Cloud, dedicated, or self-hosted deployment",
  "pricing.enterprise.feature3": "Custom volume and retention",
  "pricing.enterprise.feature4": "Security and deployment review",
  "pricing.enterprise.feature5": "Invoice billing and procurement support",
  "pricing.enterprise.feature6": "Custom integration planning and priority onboarding",
  "pricing.runDefinition":
    "One agent run is one inbound customer message processed by Mantly, regardless of how many concerns, runbooks, knowledge searches, or tools it uses.",
  "pricing.usageNote":
    "Mantly-managed LLM usage is billed separately at provider cost × 1.2. Bring-your-own-key LLM usage has no Mantly surcharge. Applicable taxes are shown at checkout.",

  "faq.tagline": "FAQ",
  "faq.title": "Common questions.",
  "faq.q1": "What is Mantly?",
  "faq.a1":
    "Mantly is an open-source agentic customer support platform. It combines an omnichannel Inbox, company-defined runbooks, ticket-scoped knowledge, tools, actions, and one response composer.",
  "faq.q2": "What is the difference between Community and Cloud?",
  "faq.a2":
    "Community gives you the full core platform to operate on your own infrastructure. Cloud runs the application for you and includes managed operations plus a monthly agent-run allowance.",
  "faq.q3": "What counts as one agent run?",
  "faq.a3":
    "One inbound customer message counts as one agent run. A message still counts as one run when it triggers multiple concerns, runbooks, knowledge searches, or tools.",
  "faq.q4": "Can Mantly send answers automatically?",
  "faq.a4":
    "Yes, when your policy permits it. You can also require human approval or keep a workflow fully manual for sensitive cases.",
  "faq.q5": "What happens when one message has several concerns?",
  "faq.a5":
    "Mantly activates the relevant runbooks per concern, collects their structured results, and gives the Inbox response composer everything it needs to produce one coherent answer.",
  "faq.q6": "Where do the application, data, and models run?",
  "faq.a6":
    "You can self-host the application and use your own model keys or choose Mantly Cloud for managed operation. Your deployment choice determines where the application runs.",

  "cta.title": "Run Mantly your way.",
  "cta.subtitle":
    "Start on the managed cloud today, or inspect the code and deploy the open-source platform on your own infrastructure.",
  "cta.button": "Start Cloud",
  "cta.github": "View on GitHub",
  "cta.selfHost": "Self-hosting docs",
  "cta.sales": "Talk to sales",

  "footer.tagline": "Open-source agentic customer support, under your rules.",
  "footer.github": "GitHub",
  "footer.docs": "Self-host docs",
  "footer.sales": "Sales",
  "footer.support": "Support",
  "footer.privacy": "Privacy Policy",
  "footer.terms": "Terms",
  "footer.imprint": "Imprint",
  "footer.rights": "All rights reserved.",
} satisfies Record<string, string>;

export type TranslationKey = keyof typeof en;

const de: Record<TranslationKey, string> = {
  "brand.name": "Mantly",

  "nav.howItWorks": "So funktioniert es",
  "nav.product": "Produkt",
  "nav.pricing": "Preise",
  "nav.docs": "Docs",
  "nav.github": "GitHub",
  "nav.login": "Anmelden",
  "nav.cloud": "Cloud starten",
  "a11y.openMenu": "Navigationsmenü öffnen",
  "a11y.closeMenu": "Navigationsmenü schließen",
  "a11y.switchToGerman": "Sprache auf Deutsch umstellen",
  "a11y.switchToEnglish": "Sprache auf Englisch umstellen",
  "a11y.skipToContent": "Zum Hauptinhalt springen",

  "hero.title": "Kundensupport, der selbstständig läuft – nach Ihren Regeln.",
  "hero.subtitle":
    "Mantly macht aus Nachrichten verbundener Kanäle Tickets, die nach Ihren Regeln bearbeitet werden. Die Plattform erkennt jedes Anliegen, folgt Ihren Runbooks mit verifiziertem Wissen und Tools und erstellt eine fundierte Antwort. Self-hosted oder in der Mantly Cloud.",
  "hero.cta": "Cloud starten",
  "hero.ctaHref": "https://app.mantly.io?view=signup",
  "hero.secondaryCta": "GitHub ansehen",
  "hero.secondaryHref": "https://github.com/olsommer/mantly",
  "hero.selfHostCta": "Self-Hosting-Dokumentation lesen",
  "hero.demoCta": "Ein Ticket ansehen",
  "hero.badge": "Open Source · Self-hosted oder Mantly Cloud",
  "hero.builtFor": "Ein Supportsystem · Verbundene Kanäle · Ihre Richtlinien",

  "problem.tagline": "Ergebnisse",
  "problem.title": "Den gesamten Supportfall automatisieren – nicht nur die Antwort.",
  "problem.subtitle":
    "Mantly verbindet Triage, Recherche, Aktionen und die finale Antwort in einem kontrollierten Workflow.",
  "problem.pain1.title": "Komplette Fallbearbeitung",
  "problem.pain1.desc":
    "Von der eingehenden Nachricht zum gelösten Ticket: Kontext, Aktionen und Kommunikation werden gemeinsam bearbeitet.",
  "problem.pain2.title": "Kontrolle beim Unternehmen",
  "problem.pain2.desc":
    "Ihre Runbooks bestimmen, was der Agent tun soll, welche Tools er nutzen darf und wann ein Mensch freigeben muss.",
  "problem.pain3.title": "Eine schlüssige Antwort",
  "problem.pain3.desc":
    "Mehrere Anliegen werden getrennt bearbeitet und anschließend mit den relevanten Belegen und Ergebnissen in einer Kundenantwort zusammengeführt.",

  "how.tagline": "So funktioniert es",
  "how.title": "Eine Nachricht rein. Ein kontrolliertes Ergebnis.",
  "how.subtitle":
    "Jede eingehende Kundennachricht wird als ein Agent-Run verarbeitet – auch wenn sie mehrere Anliegen enthält.",
  "how.step1.title": "Ein Ticket erstellen",
  "how.step1.desc":
    "Nachrichten aus verbundenen Kanälen kommen als ein Supportticket im Posteingang an.",
  "how.step2.title": "Passende Runbooks aktivieren",
  "how.step2.desc":
    "Mantly erkennt Anliegen in der Nachricht und führt die passenden, vom Unternehmen definierten Workflows separat aus.",
  "how.step3.title": "Fakten sammeln und handeln",
  "how.step3.desc":
    "Wissen und Tools liefern verlässliche Belege, während erlaubte Aktionen die beteiligten Systeme aktualisieren.",
  "how.step4.title": "Eine Antwort erstellen",
  "how.step4.desc":
    "Der Inbox Composer verbindet die Ergebnisse passender Runbooks zu einer fundierten Antwort – zur Freigabe oder zum automatischen Versand.",

  "features.tagline": "Produkt",
  "features.title": "Das Support-Betriebssystem unter Ihrer Kontrolle.",
  "features.subtitle":
    "Offene Infrastruktur, eindeutige Workflows, fundierte Antworten und ein prüfbarer Ausführungsverlauf in einer Plattform.",
  "features.1.title": "Open Source",
  "features.1.desc":
    "Prüfen, anpassen und betreiben Sie die Kernplattform auf Ihrer eigenen Infrastruktur.",
  "features.2.title": "Omnichannel Inbox",
  "features.2.desc":
    "Bündeln Sie Kundennachrichten in einem Ticketsystem, statt für jeden Kanal einen separaten Prozess zu betreiben.",
  "features.3.title": "Runbooks für mehrere Anliegen",
  "features.3.desc":
    "Bearbeiten Sie erkannte Anliegen separat, ohne fragmentierte Kundenantworten zu erzeugen.",
  "features.4.title": "Ein Response Composer",
  "features.4.desc":
    "Verwandeln Sie passende Runbook-Ergebnisse, Belege und Aktionen in eine konsistente finale Antwort.",
  "features.5.title": "Fundiertes Wissen",
  "features.5.desc":
    "Recherchieren Sie im ticketbezogenen Wissen und halten Sie Quellen für die Prüfung verfügbar.",
  "features.6.title": "Tools und Aktionen",
  "features.6.desc":
    "Binden Sie interne Systeme für Abfragen, Updates, Übergaben und weitere erlaubte Arbeiten an.",
  "features.7.title": "Menschliche Kontrolle",
  "features.7.desc":
    "Wählen Sie je nach Richtlinie zwischen manueller, freigabepflichtiger oder automatischer Ausführung.",
  "features.8.title": "Evaluation vor Veröffentlichung",
  "features.8.desc":
    "Testen Sie Runbook- und Antwortverhalten mit wiederholbaren Fällen, bevor Änderungen Kunden erreichen.",
  "features.9.title": "Self-hosted oder Cloud",
  "features.9.desc":
    "Betreiben Sie Mantly selbst oder lassen Sie die Anwendung von Mantly Cloud verwalten.",
  "features.screenshotAlt": "Mantly Admin",
  "features.admin.subtitle": "Anliegen, Quellen, Aktionen und finale Antworten prüfen",
  "features.admin.tab.intents": "Runbooks",
  "features.admin.tab.responses": "Evaluationen",
  "features.admin.tab.attachments": "Ausführungsverlauf",
  "features.admin.intentName": "Support-Automatisierung",
  "features.admin.intentDesc": "Anliegen, Belege, Aktionen und eine finale Antwort",
  "features.admin.status": "Aktiv",
  "features.admin.card1": "Anliegen",
  "features.admin.card2": "Wissen & Tools",
  "features.admin.card3": "Aktionen",
  "features.admin.card4": "Finale Antwort",

  "pillars.tagline": "Als ein System gebaut",
  "pillars.title": "Posteingang, Agenten und Belege bleiben verbunden.",
  "pillars.1.title": "Inbox",
  "pillars.1.copy":
    "Das führende System für Tickets, Anliegen, Aktionen, Freigaben und Kundenantworten.",
  "pillars.2.title": "Runbook Agent",
  "pillars.2.copy":
    "Wendet Ihre Arbeitsabläufe Anliegen für Anliegen an und gibt strukturierte Ergebnisse an das Ticket zurück.",
  "pillars.3.title": "Knowledge Agent",
  "pillars.3.copy":
    "Findet ticketrelevante Fakten, bewahrt Quellen auf und macht die Belege für Menschen prüfbar.",

  "pricing.tagline": "Preise",
  "pricing.title": "Open Source für Kontrolle. Cloud für Geschwindigkeit.",
  "pricing.subtitle":
    "Starten Sie mit der vollständigen Kernplattform und ergänzen Sie verwalteten Betrieb oder mehr Governance, wenn Ihr Team wächst.",
  "pricing.month": "/Monat",
  "pricing.popular": "Empfohlen",
  "pricing.community.name": "Community",
  "pricing.community.price": "Kostenlos",
  "pricing.community.desc": "Für Teams, die Mantly selbst betreiben möchten.",
  "pricing.community.cta": "Auf GitHub ansehen",
  "pricing.community.feature1": "Self-hosted Mantly",
  "pricing.community.feature2": "Vollständige Kernplattform",
  "pricing.community.feature3": "Unbegrenzte lokale Agent-Runs",
  "pricing.community.feature4": "Eigene Modellschlüssel verwenden",
  "pricing.community.feature5": "Runbooks, Wissen und Tools",
  "pricing.community.feature6": "Community-Support",
  "pricing.cloud.name": "Cloud",
  "pricing.cloud.price": "19 EUR",
  "pricing.cloud.desc": "Für Supportteams, die Mantly verwalten lassen möchten.",
  "pricing.cloud.cta": "Cloud starten",
  "pricing.cloud.feature1": "Verwaltete Mantly Cloud",
  "pricing.cloud.feature2": "150 Agent-Runs/Monat",
  "pricing.cloud.feature3": "1 Projekt inklusive",
  "pricing.cloud.feature4": "Unbegrenzte Teammitglieder",
  "pricing.cloud.feature5": "Verwaltete Anwendungsupdates",
  "pricing.cloud.feature6": "5 Evaluations-Sets",
  "pricing.cloud.feature7": "Run-Tracking und Feedback-Learnings",
  "pricing.cloud.feature8": "Eigene Modellschlüssel verwenden",
  "pricing.business.name": "Business",
  "pricing.business.price": "199 EUR",
  "pricing.business.desc": "Für Teams mit mehr Governance- und Volumenbedarf.",
  "pricing.business.cta": "Vertrieb kontaktieren",
  "pricing.business.feature1": "1.000 Agent-Runs/Monat",
  "pricing.business.feature2": "10 Projekte inklusive",
  "pricing.business.feature3": "Unbegrenzte Teammitglieder",
  "pricing.business.feature4": "Unbegrenzte Evaluationen",
  "pricing.business.feature5": "Rollen und Freigabekontrollen",
  "pricing.business.feature6": "Run-Tracking mit längerer Aufbewahrung",
  "pricing.business.feature7": "Phishing- und Prompt-Injection-Monitoring",
  "pricing.business.feature8": "Feedback-Vorschläge",
  "pricing.enterprise.name": "Enterprise",
  "pricing.enterprise.price": "Individuell",
  "pricing.enterprise.desc": "Für Anforderungen an Deployment, Einkauf und Integrationen.",
  "pricing.enterprise.cta": "Vertrieb kontaktieren",
  "pricing.enterprise.feature1": "Alles aus Business",
  "pricing.enterprise.feature2": "Cloud-, Dedicated- oder Self-hosted-Deployment",
  "pricing.enterprise.feature3": "Individuelles Volumen und Aufbewahrung",
  "pricing.enterprise.feature4": "Security- und Deployment-Review",
  "pricing.enterprise.feature5": "Rechnungszahlung und Unterstützung im Einkauf",
  "pricing.enterprise.feature6": "Individuelle Integrationsplanung und priorisiertes Onboarding",
  "pricing.runDefinition":
    "Ein Agent-Run ist genau eine eingehende Kundennachricht, die Mantly verarbeitet – unabhängig davon, wie viele Anliegen, Runbooks, Wissenssuchen oder Tools dafür verwendet werden.",
  "pricing.usageNote":
    "Die Nutzung von Mantly-verwalteten LLMs wird separat zu Anbieterkosten × 1,2 abgerechnet. Für LLM-Nutzung mit eigenem Schlüssel erhebt Mantly keinen Aufschlag. Anfallende Steuern werden im Checkout ausgewiesen.",

  "faq.tagline": "FAQ",
  "faq.title": "Häufige Fragen.",
  "faq.q1": "Was ist Mantly?",
  "faq.a1":
    "Mantly ist eine Open-Source-Plattform für agentischen Kundensupport. Sie verbindet eine Omnichannel Inbox, firmeneigene Runbooks, ticketbezogenes Wissen, Tools, Aktionen und einen zentralen Response Composer.",
  "faq.q2": "Was ist der Unterschied zwischen Community und Cloud?",
  "faq.a2":
    "Community bietet die vollständige Kernplattform für den Betrieb auf eigener Infrastruktur. In der Cloud betreiben wir die Anwendung für Sie – inklusive verwaltetem Betrieb und monatlichem Agent-Run-Kontingent.",
  "faq.q3": "Was zählt als ein Agent-Run?",
  "faq.a3":
    "Eine eingehende Kundennachricht zählt als ein Agent-Run. Sie bleibt ein Run, auch wenn sie mehrere Anliegen, Runbooks, Wissenssuchen oder Tools auslöst.",
  "faq.q4": "Kann Mantly Antworten automatisch versenden?",
  "faq.a4":
    "Ja, wenn Ihre Richtlinie das erlaubt. Für sensible Fälle können Sie eine menschliche Freigabe verlangen oder den Workflow vollständig manuell halten.",
  "faq.q5": "Was passiert, wenn eine Nachricht mehrere Anliegen enthält?",
  "faq.a5":
    "Mantly aktiviert die relevanten Runbooks pro Anliegen, sammelt ihre strukturierten Ergebnisse und gibt dem Inbox Response Composer den nötigen Kontext für eine einzige schlüssige Antwort.",
  "faq.q6": "Wo laufen Anwendung, Daten und Modelle?",
  "faq.a6":
    "Sie können die Anwendung selbst hosten und eigene Modellschlüssel verwenden oder Mantly Cloud für den verwalteten Betrieb wählen. Ihre Deployment-Wahl bestimmt, wo die Anwendung läuft.",

  "cta.title": "Betreiben Sie Mantly auf Ihre Weise.",
  "cta.subtitle":
    "Starten Sie heute in der verwalteten Cloud oder prüfen Sie den Code und betreiben Sie die Open-Source-Plattform auf Ihrer eigenen Infrastruktur.",
  "cta.button": "Cloud starten",
  "cta.github": "Auf GitHub ansehen",
  "cta.selfHost": "Self-Hosting-Dokumentation",
  "cta.sales": "Vertrieb kontaktieren",

  "footer.tagline": "Open-Source-Kundensupport mit Agenten – nach Ihren Regeln.",
  "footer.github": "GitHub",
  "footer.docs": "Self-Hosting-Docs",
  "footer.sales": "Vertrieb",
  "footer.support": "Support",
  "footer.privacy": "Datenschutz",
  "footer.terms": "Nutzungsbedingungen",
  "footer.imprint": "Impressum",
  "footer.rights": "Alle Rechte vorbehalten.",
};

export const translations: Record<Language, Record<TranslationKey, string>> = {
  en,
  de,
};
