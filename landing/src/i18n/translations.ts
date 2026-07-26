export type Language = "en" | "de";

const en = {
  "brand.name": "Mantly",

  "nav.product": "Product",
  "nav.pricing": "Pricing",
  "nav.docs": "Docs",
  "nav.github": "GitHub",
  "nav.cloud": "Cloud",
  "a11y.openMenu": "Open navigation menu",
  "a11y.closeMenu": "Close navigation menu",
  "a11y.switchToGerman": "Switch language to German",
  "a11y.switchToEnglish": "Switch language to English",
  "a11y.skipToContent": "Skip to main content",

  "hero.title": "Support that runs itself. Your rules.",
  "hero.subtitle":
    "Messages from connected channels become governed tickets. Mantly handles each concern with your runbooks, sourced knowledge, and tools. One ticket. One grounded reply.",
  "hero.cta": "Cloud",
  "hero.ctaHref": "https://app.mantly.io?view=signup",
  "hero.secondaryCta": "GitHub",
  "hero.secondaryHref": "https://github.com/olsommer/mantly",
  "hero.selfHostCta": "Docs",
  "hero.demoCta": "Demo",
  "hero.badge": "Open source · Self-hosted · Cloud",
  "hero.builtFor": "Connected channels · Your runbooks · One reply",

  "problem.tagline": "Outcomes",
  "problem.title": "Handle the whole case.",
  "problem.subtitle":
    "Triage, research, permitted actions, and replies stay in one governed workflow.",
  "problem.pain1.title": "Full-case handling",
  "problem.pain1.desc":
    "Keep context, permitted actions, and communication in one ticket.",
  "problem.pain2.title": "Your rules",
  "problem.pain2.desc":
    "Runbooks define the work, allowed tools, and approval gates.",
  "problem.pain3.title": "One reply",
  "problem.pain3.desc":
    "Handle concerns separately, then combine their results into one reply.",

  "how.tagline": "How it works",
  "how.title": "One message. One outcome.",
  "how.subtitle":
    "One inbound message becomes one ticket—even with several concerns.",
  "how.step1.title": "Create ticket",
  "how.step1.desc":
    "Messages from connected channels open one Inbox ticket.",
  "how.step2.title": "Match runbooks",
  "how.step2.desc":
    "Detected concerns activate their company-defined runbooks.",
  "how.step3.title": "Research and act",
  "how.step3.desc":
    "Knowledge provides sourced facts; tools perform permitted actions.",
  "how.step4.title": "Write one reply",
  "how.step4.desc":
    "The Inbox combines every result for approval or automatic delivery.",

  "features.tagline": "Product",
  "features.title": "The support system you control.",
  "features.subtitle":
    "Open infrastructure. Explicit workflows. Grounded replies. Reviewable history.",
  "features.1.title": "Open source",
  "features.1.desc":
    "Inspect, adapt, and run Mantly on infrastructure you control.",
  "features.2.title": "One Inbox",
  "features.2.desc":
    "Bring messages from connected channels into one ticket system.",
  "features.3.title": "Concern runbooks",
  "features.3.desc":
    "Handle each concern independently without splitting the customer reply.",
  "features.4.title": "One composer",
  "features.4.desc":
    "Combine runbook results, evidence, and actions into one reply.",
  "features.5.title": "Grounded knowledge",
  "features.5.desc":
    "Use ticket-scoped knowledge with reviewable citations.",
  "features.6.title": "Tools and actions",
  "features.6.desc":
    "Look up data, update systems, and hand off permitted work.",
  "features.7.title": "Approval control",
  "features.7.desc":
    "Choose manual, approval-based, or automatic execution by policy.",
  "features.8.title": "Evaluations",
  "features.8.desc":
    "Test repeatable cases before publishing changes.",
  "features.9.title": "Self-host or Cloud",
  "features.9.desc":
    "Run Mantly yourself or use the managed Cloud.",
  "features.screenshotAlt": "Mantly Admin",
  "features.admin.subtitle": "Review concerns, evidence, actions, and replies",
  "features.admin.tab.intents": "Runbooks",
  "features.admin.tab.responses": "Evaluations",
  "features.admin.tab.attachments": "Execution history",
  "features.admin.intentName": "Support automation",
  "features.admin.intentDesc": "Concerns, evidence, actions, one reply",
  "features.admin.status": "Active",
  "features.admin.card1": "Concerns",
  "features.admin.card2": "Knowledge & tools",
  "features.admin.card3": "Actions",
  "features.admin.card4": "Reply",

  "pricing.tagline": "Pricing",
  "pricing.title": "Open source. Or Cloud.",
  "pricing.subtitle":
    "Run Mantly yourself, or use the managed Cloud.",
  "pricing.month": "/mo",
  "pricing.popular": "Recommended",
  "pricing.community.name": "Community",
  "pricing.community.price": "Free",
  "pricing.community.desc": "Run Mantly on your infrastructure.",
  "pricing.community.cta": "GitHub",
  "pricing.community.feature1": "Self-hosted Mantly",
  "pricing.community.feature2": "Open-source core platform",
  "pricing.community.feature3": "No Mantly limit on agent runs",
  "pricing.community.feature4": "Bring your own model keys",
  "pricing.community.feature5": "Runbooks, knowledge, and tools",
  "pricing.community.feature6": "Community support",
  "pricing.cloud.name": "Cloud",
  "pricing.cloud.price": "19 €",
  "pricing.cloud.desc": "Managed Mantly for support teams.",
  "pricing.cloud.cta": "Cloud",
  "pricing.cloud.feature1": "Managed Mantly Cloud",
  "pricing.cloud.feature2": "150 agent runs/month",
  "pricing.cloud.feature3": "1 project included",
  "pricing.cloud.feature4": "Unlimited team members",
  "pricing.cloud.feature5": "Managed updates",
  "pricing.cloud.feature6": "5 evaluation sets",
  "pricing.cloud.feature7": "Run tracking and feedback learnings",
  "pricing.cloud.feature8": "Bring your own model keys",
  "pricing.business.name": "Business",
  "pricing.business.price": "199 €",
  "pricing.business.desc": "More volume, control, and governance.",
  "pricing.business.cta": "Sales",
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
  "pricing.enterprise.desc": "Custom deployment, procurement, and integrations.",
  "pricing.enterprise.cta": "Sales",
  "pricing.enterprise.feature1": "Everything in Business",
  "pricing.enterprise.feature2": "Cloud, dedicated, or self-hosted deployment",
  "pricing.enterprise.feature3": "Custom volume and retention",
  "pricing.enterprise.feature4": "Security and deployment review",
  "pricing.enterprise.feature5": "Invoice billing and procurement support",
  "pricing.enterprise.feature6": "Custom integration planning and priority onboarding",
  "pricing.runDefinition":
    "One inbound customer message equals one agent run—even with several concerns, runbooks, knowledge searches, or tools.",
  "pricing.usageNote":
    "Managed LLM usage is billed at provider cost × 1.2. Bring your own key with no Mantly surcharge. Applicable taxes appear at checkout.",

  "faq.tagline": "FAQ",
  "faq.title": "Common questions.",
  "faq.q1": "What is Mantly?",
  "faq.a1":
    "Mantly is an open-source agentic support platform with one Inbox, company-defined runbooks, ticket-scoped knowledge, tools, permitted actions, and one reply composer.",
  "faq.q2": "What is the difference between Community and Cloud?",
  "faq.a2":
    "Community is the open-source core you run on your infrastructure. Cloud manages the application and includes a monthly agent-run allowance.",
  "faq.q3": "What counts as one agent run?",
  "faq.a3":
    "One inbound customer message equals one agent run—even when it contains several concerns and invokes several runbooks, knowledge searches, or tools.",
  "faq.q4": "Can Mantly send answers automatically?",
  "faq.a4":
    "Yes, when policy permits it. Keep sensitive workflows manual or require human approval.",
  "faq.q5": "What happens when one message has several concerns?",
  "faq.a5":
    "Mantly runs the relevant runbooks per concern, collects their structured results, and composes one coherent reply.",
  "faq.q6": "Where do the application, data, and models run?",
  "faq.a6":
    "Self-host the application with your own model keys, or choose managed Mantly Cloud. Your deployment choice determines where the application runs.",

  "cta.title": "Mantly. Your way.",
  "cta.subtitle":
    "Use the managed Cloud or deploy the open-source core.",
  "cta.button": "Cloud",
  "cta.github": "GitHub",
  "cta.selfHost": "Docs",
  "cta.sales": "Sales",

  "footer.tagline": "Open-source support. Your rules.",
  "footer.github": "GitHub",
  "footer.docs": "Docs",
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

  "nav.product": "Produkt",
  "nav.pricing": "Preise",
  "nav.docs": "Docs",
  "nav.github": "GitHub",
  "nav.cloud": "Cloud",
  "a11y.openMenu": "Navigationsmenü öffnen",
  "a11y.closeMenu": "Navigationsmenü schließen",
  "a11y.switchToGerman": "Sprache auf Deutsch umstellen",
  "a11y.switchToEnglish": "Sprache auf Englisch umstellen",
  "a11y.skipToContent": "Zum Hauptinhalt springen",

  "hero.title": "Support, der nach deinen Regeln arbeitet.",
  "hero.subtitle":
    "Mantly macht Nachrichten aus verbundenen Kanälen zu Tickets und bearbeitet jedes Anliegen mit deinen Runbooks, Wissen mit Quellen und Tools. Ein Ticket. Eine fundierte Antwort.",
  "hero.cta": "Cloud",
  "hero.ctaHref": "https://app.mantly.io?view=signup",
  "hero.secondaryCta": "GitHub",
  "hero.secondaryHref": "https://github.com/olsommer/mantly",
  "hero.selfHostCta": "Docs",
  "hero.demoCta": "Demo",
  "hero.badge": "Open Source · Self-hosted · Cloud",
  "hero.builtFor": "Verbundene Kanäle · Deine Runbooks · Eine Antwort",

  "problem.tagline": "Ergebnisse",
  "problem.title": "Der ganze Supportfall.",
  "problem.subtitle":
    "Triage, Recherche, erlaubte Aktionen und Antworten bleiben in einem kontrollierten Workflow.",
  "problem.pain1.title": "Komplette Bearbeitung",
  "problem.pain1.desc":
    "Kontext, erlaubte Aktionen und Kommunikation bleiben in einem Ticket.",
  "problem.pain2.title": "Deine Regeln",
  "problem.pain2.desc":
    "Runbooks definieren Arbeit, erlaubte Tools und Freigaben.",
  "problem.pain3.title": "Eine Antwort",
  "problem.pain3.desc":
    "Anliegen werden getrennt bearbeitet und in einer Antwort zusammengeführt.",

  "how.tagline": "So funktioniert es",
  "how.title": "Eine Nachricht. Ein Ergebnis.",
  "how.subtitle":
    "Eine eingehende Nachricht wird zu einem Ticket – auch mit mehreren Anliegen.",
  "how.step1.title": "Ticket",
  "how.step1.desc":
    "Nachrichten aus verbundenen Kanälen landen als Ticket in der Inbox.",
  "how.step2.title": "Runbooks",
  "how.step2.desc":
    "Erkannte Anliegen aktivieren die passenden Runbooks des Unternehmens.",
  "how.step3.title": "Recherche",
  "how.step3.desc":
    "Wissen mit Quellen liefert Fakten; Tools führen erlaubte Aktionen aus.",
  "how.step4.title": "Antwort",
  "how.step4.desc":
    "Die Inbox bündelt alle Ergebnisse für Freigabe oder automatischen Versand.",

  "features.tagline": "Produkt",
  "features.title": "Support unter deiner Kontrolle.",
  "features.subtitle":
    "Offene Infrastruktur. Klare Workflows. Fundierte Antworten. Prüfbarer Verlauf.",
  "features.1.title": "Open Source",
  "features.1.desc":
    "Mantly prüfen, anpassen und auf eigener Infrastruktur betreiben.",
  "features.2.title": "Eine Inbox",
  "features.2.desc":
    "Nachrichten verbundener Kanäle in einem Ticketsystem bündeln.",
  "features.3.title": "Runbooks",
  "features.3.desc":
    "Jedes Anliegen separat bearbeiten, ohne die Kundenantwort aufzuteilen.",
  "features.4.title": "Eine Antwort",
  "features.4.desc":
    "Runbook-Ergebnisse, Belege und Aktionen in einer Antwort bündeln.",
  "features.5.title": "Wissen mit Quellen",
  "features.5.desc":
    "Ticketbezogenes Wissen mit prüfbaren Quellen nutzen.",
  "features.6.title": "Tools und Aktionen",
  "features.6.desc":
    "Daten abfragen, Systeme aktualisieren und erlaubte Arbeit übergeben.",
  "features.7.title": "Freigaben",
  "features.7.desc":
    "Je nach Richtlinie manuell, mit Freigabe oder automatisch ausführen.",
  "features.8.title": "Evaluationen",
  "features.8.desc":
    "Wiederholbare Fälle vor der Veröffentlichung testen.",
  "features.9.title": "Self-hosted oder Cloud",
  "features.9.desc":
    "Mantly selbst betreiben oder die verwaltete Cloud nutzen.",
  "features.screenshotAlt": "Mantly Admin",
  "features.admin.subtitle": "Anliegen, Belege, Aktionen und Antworten prüfen",
  "features.admin.tab.intents": "Runbooks",
  "features.admin.tab.responses": "Evaluationen",
  "features.admin.tab.attachments": "Ausführungsverlauf",
  "features.admin.intentName": "Support-Automatisierung",
  "features.admin.intentDesc": "Anliegen, Belege, Aktionen, eine Antwort",
  "features.admin.status": "Aktiv",
  "features.admin.card1": "Anliegen",
  "features.admin.card2": "Wissen & Tools",
  "features.admin.card3": "Aktionen",
  "features.admin.card4": "Antwort",

  "pricing.tagline": "Preise",
  "pricing.title": "Open Source. Oder Cloud.",
  "pricing.subtitle":
    "Betreibe Mantly selbst oder nutze die verwaltete Cloud.",
  "pricing.month": "/Monat",
  "pricing.popular": "Empfohlen",
  "pricing.community.name": "Community",
  "pricing.community.price": "Kostenlos",
  "pricing.community.desc": "Mantly auf eigener Infrastruktur betreiben.",
  "pricing.community.cta": "GitHub",
  "pricing.community.feature1": "Self-hosted Mantly",
  "pricing.community.feature2": "Open-Source-Kernplattform",
  "pricing.community.feature3": "Kein Mantly-Limit für Agent-Runs",
  "pricing.community.feature4": "Eigene Modellschlüssel verwenden",
  "pricing.community.feature5": "Runbooks, Wissen und Tools",
  "pricing.community.feature6": "Community-Support",
  "pricing.cloud.name": "Cloud",
  "pricing.cloud.price": "19 €",
  "pricing.cloud.desc": "Verwaltetes Mantly für Supportteams.",
  "pricing.cloud.cta": "Cloud",
  "pricing.cloud.feature1": "Verwaltete Mantly Cloud",
  "pricing.cloud.feature2": "150 Agent-Runs/Monat",
  "pricing.cloud.feature3": "1 Projekt inklusive",
  "pricing.cloud.feature4": "Unbegrenzte Teammitglieder",
  "pricing.cloud.feature5": "Verwaltete Updates",
  "pricing.cloud.feature6": "5 Evaluations-Sets",
  "pricing.cloud.feature7": "Run-Tracking und Feedback-Erkenntnisse",
  "pricing.cloud.feature8": "Eigene Modellschlüssel verwenden",
  "pricing.business.name": "Business",
  "pricing.business.price": "199 €",
  "pricing.business.desc": "Mehr Volumen, Kontrolle und Governance.",
  "pricing.business.cta": "Kontakt",
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
  "pricing.enterprise.desc": "Individuelle Anforderungen an Betrieb, Einkauf und Integrationen.",
  "pricing.enterprise.cta": "Kontakt",
  "pricing.enterprise.feature1": "Alles aus Business",
  "pricing.enterprise.feature2": "Cloud, dediziert oder selbst gehostet",
  "pricing.enterprise.feature3": "Individuelles Volumen und Aufbewahrung",
  "pricing.enterprise.feature4": "Security- und Deployment-Review",
  "pricing.enterprise.feature5": "Rechnungszahlung und Unterstützung im Einkauf",
  "pricing.enterprise.feature6": "Individuelle Integrationsplanung und priorisiertes Onboarding",
  "pricing.runDefinition":
    "Eine eingehende Kundennachricht entspricht einem Agent-Run – auch mit mehreren Anliegen, Runbooks, Wissenssuchen oder Tools.",
  "pricing.usageNote":
    "Für verwaltete LLM-Nutzung berechnen wir Anbieterkosten × 1,2. Für eigene Modellschlüssel fällt kein Mantly-Aufschlag an. Steuern werden im Checkout ausgewiesen.",

  "faq.tagline": "FAQ",
  "faq.title": "Häufige Fragen.",
  "faq.q1": "Was ist Mantly?",
  "faq.a1":
    "Mantly ist eine Open-Source-Plattform für agentischen Support mit einer Inbox, firmeneigenen Runbooks, ticketbezogenem Wissen, Tools, erlaubten Aktionen und einer gemeinsamen Antwort.",
  "faq.q2": "Was ist der Unterschied zwischen Community und Cloud?",
  "faq.a2":
    "Community ist der Open-Source-Kern, den du auf deiner Infrastruktur betreibst. Cloud verwaltet die Anwendung und enthält ein monatliches Agent-Run-Kontingent.",
  "faq.q3": "Was zählt als ein Agent-Run?",
  "faq.a3":
    "Eine eingehende Kundennachricht entspricht einem Agent-Run – auch mit mehreren Anliegen, Runbooks, Wissenssuchen oder Tools.",
  "faq.q4": "Kann Mantly Antworten automatisch versenden?",
  "faq.a4":
    "Ja, wenn deine Richtlinie das erlaubt. Sensible Workflows können manuell bleiben oder eine menschliche Freigabe erfordern.",
  "faq.q5": "Was passiert, wenn eine Nachricht mehrere Anliegen enthält?",
  "faq.a5":
    "Mantly führt pro Anliegen das passende Runbook aus, sammelt strukturierte Ergebnisse und erstellt eine schlüssige Antwort.",
  "faq.q6": "Wo laufen Anwendung, Daten und Modelle?",
  "faq.a6":
    "Hoste die Anwendung selbst mit eigenen Modellschlüsseln oder wähle die verwaltete Mantly Cloud. Deine Deployment-Wahl bestimmt, wo die Anwendung läuft.",

  "cta.title": "Mantly. Deine Wahl.",
  "cta.subtitle":
    "Nutze die verwaltete Cloud oder betreibe den Open-Source-Kern selbst.",
  "cta.button": "Cloud",
  "cta.github": "GitHub",
  "cta.selfHost": "Docs",
  "cta.sales": "Kontakt",

  "footer.tagline": "Open-Source-Support. Deine Regeln.",
  "footer.github": "GitHub",
  "footer.docs": "Docs",
  "footer.sales": "Kontakt",
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
