import { useTranslation } from "@/i18n/useTranslation";

type LegalPageKind = "privacy" | "imprint" | "terms";

type LegalSection = {
  title: string;
  body: string[];
};

type LegalPageContent = {
  title: string;
  intro: string;
  sections: LegalSection[];
};

const content: Record<"de" | "en", Record<LegalPageKind, LegalPageContent>> = {
  de: {
    privacy: {
      title: "Datenschutz",
      intro:
        "Diese Datenschutzerklärung informiert darüber, wie Mantly personenbezogene Daten auf der öffentlichen Website, in der Admin-Anwendung, im Outlook-Add-in und in den angebundenen Backend-Diensten verarbeitet.",
      sections: [
        {
          title: "Stand",
          body: ["19. Mai 2026"],
        },
        {
          title: "Verantwortliche Stelle",
          body: [
            "IsarAI UG (haftungsbeschränkt)",
            "Breitensteinstr. 6",
            "82031 Grünwald",
            "E-Mail: info@isarai.de",
            "Produkt- und Datenschutzanfragen können auch an support@mantly.io gerichtet werden.",
          ],
        },
        {
          title: "Arten der verarbeiteten Daten",
          body: [
            "Beim Besuch der öffentlichen Website verarbeiten wir technische Nutzungsdaten wie IP-Adresse, Browser, Gerätedaten, Datum und Uhrzeit des Zugriffs, Referrer und aufgerufene Seiten.",
            "Bei der Nutzung von Mantly verarbeiten wir Konto- und Organisationsdaten wie E-Mail-Adresse, Name, Unternehmen, Passwort- und Authentifizierungsstatus, Rollen, Projekte und Workspace-Zuordnungen.",
            "Im Outlook-Add-in und in der Admin-Anwendung können E-Mail-Inhalte und Metadaten verarbeitet werden, insbesondere Absender, Empfänger, Betreff, Body, Anhänge, technische E-Mail-Metadaten und vom Nutzer ausgelöste Analyse- oder Vorschau-Runs.",
            "Darüber hinaus verarbeiten wir Konfigurationen für Kundenidentifikation, Anliegenerkennung, Pipeline, Aktionen, Tools, Antwortregeln, Instruktionen, Vorlagen, Evaluation-Sets, Test-E-Mails, Evaluationsergebnisse, Feedback, Learnings, Monitoring-Logs, Risikoergebnisse für Phishing und Prompt Injection sowie Token- und Nutzungsdaten.",
            "Für Abrechnung und Vertragsverwaltung verarbeiten wir Plan-, Zahlungs-, Rechnungs-, Subscription- und Usage-Daten.",
          ],
        },
        {
          title: "Zwecke der Verarbeitung",
          body: [
            "Wir verarbeiten personenbezogene Daten zur Bereitstellung der Website, zur Kontoerstellung und Anmeldung, zur Bereitstellung der Mantly-SaaS-Dienste, der Admin-Anwendung und des Outlook-Add-ins.",
            "E-Mail- und Workflow-Daten werden verarbeitet, um Kunden zu identifizieren, Anliegen zu erkennen, Antworten vorzubereiten, Aktionen und Tools auszuführen, Vorschauen zu erzeugen, Veröffentlichungen vorzubereiten und Evaluationen durchzuführen.",
            "Weitere Zwecke sind Sicherheit, Missbrauchs- und Betrugsprävention, Phishing- und Prompt-Injection-Warnungen, Monitoring, Fehleranalyse, Support, Produktverbesserung, Nutzungslimits, Token-Metering, Abrechnung und Erfüllung gesetzlicher Pflichten.",
          ],
        },
        {
          title: "Rechtsgrundlagen",
          body: [
            "Die Verarbeitung zur Bereitstellung von Mantly, zur Konto- und Projektverwaltung, zur Analyse von E-Mails, zur Durchführung von Workflows und zur Abrechnung erfolgt regelmäßig zur Erfüllung eines Vertrags oder zur Durchführung vorvertraglicher Maßnahmen.",
            "Sicherheits-, Fehleranalyse-, Missbrauchspräventions-, Monitoring- und Produktverbesserungszwecke beruhen auf berechtigten Interessen, soweit nicht überwiegende Interessen der betroffenen Personen entgegenstehen.",
            "Rechnungs- und steuerrelevante Daten werden verarbeitet, soweit dies zur Erfüllung gesetzlicher Pflichten erforderlich ist.",
            "Analyse der öffentlichen Landingpage erfolgt zur Produktverbesserung auf Grundlage berechtigter Interessen, soweit nicht überwiegende Interessen der betroffenen Personen entgegenstehen.",
          ],
        },
        {
          title: "Hosting und Infrastruktur",
          body: [
            "Mantly wird auf Infrastruktur der Hetzner Online GmbH, www.hetzner.com, betrieben. Hetzner verarbeitet technische Nutzungsdaten, Server-Logs und auf der Infrastruktur gespeicherte Anwendungs- und Datenbankdaten, soweit dies für Hosting, Verfügbarkeit, Sicherheit und Betrieb erforderlich ist.",
            "Die Datenbank und Anwendungsspeicher werden durch IsarAI selbst betrieben. PocketBase wird selbst gehostet und ist kein eigenständiger externer Cloud-Dienst.",
          ],
        },
        {
          title: "Zahlung und Abrechnung",
          body: [
            "Für Zahlungsabwicklung, Checkout, Abonnements, Rechnungen, Kundenportal und nutzungsbasierte Abrechnung setzen wir Stripe ein.",
            "Dabei können insbesondere E-Mail-Adresse, Kundendaten, Rechnungsdaten, Zahlungsmetadaten, Stripe-Kunden- und Subscription-IDs sowie abrechnungsrelevante Nutzungsereignisse verarbeitet werden.",
          ],
        },
        {
          title: "LLM-Anbieter",
          body: [
            "Für KI-Funktionen kann Mantly Google Gemini oder OpenAI verwenden. Je nach Konfiguration werden E-Mail-Inhalte, Metadaten, Projektkonfigurationen, Kunden- und Intent-Kontext, Aktionen, Tools, Instruktionen, Evaluationen, Feedback, Learnings und generierte Ausgaben an den jeweiligen Anbieter übermittelt.",
            "Die Verarbeitung erfolgt zur E-Mail-Analyse, Kundenidentifikation, Anliegenerkennung, Antworterstellung, Evaluation, Sicherheitsprüfung und Erfassung von Token-Nutzungsmetadaten.",
            "Wenn ein Kunde eigene LLM-Zugangsdaten oder einen eigenen Provider konfiguriert, verarbeitet dieser Anbieter Daten nach der jeweiligen Kundenkonfiguration.",
          ],
        },
        {
          title: "E-Mail-Kommunikation",
          body: [
            "Für transaktionale E-Mails, E-Mail-Verifizierung, Passwort-Zurücksetzung, Support-Kommunikation und E-Mail-Routing setzen wir Google Workspace und Cloudflare Email Routing ein.",
            "Dabei können E-Mail-Adressen, Namen, Unternehmensangaben, Nachrichteninhalte und technische E-Mail-Metadaten verarbeitet werden.",
          ],
        },
        {
          title: "Analyse auf der öffentlichen Landingpage",
          body: [
            "Auf der öffentlichen Landingpage kann PostHog im Cookieless-Modus eingesetzt werden, um Nutzung, Seitenaufrufe, Interaktionen und technische Kennzahlen zu verstehen.",
            "Diese Analyse betrifft derzeit nur die öffentliche Landingpage, nicht die Admin-Anwendung und nicht das Outlook-Add-in.",
            "PostHog wird ohne Cookies und ohne persistente Browser-Identifikation betrieben.",
          ],
        },
        {
          title: "Cookies, lokale Speicherung und Tracker",
          body: [
            "Mantly verwendet technisch notwendige Speicherung, insbesondere für Spracheinstellungen, Authentifizierung, aktive Projekte, UI-Zustände und Sitzungsverwaltung.",
            "Die öffentliche Landingpage nutzt PostHog im Cookieless-Modus ohne Cookies und ohne persistente Browser-Identifikation.",
            "Sie können Browser-Speicher und Cookies in Ihrem Browser löschen oder blockieren. Dies kann die Funktionalität der Anwendung einschränken.",
          ],
        },
        {
          title: "Datenübermittlung in Drittländer",
          body: [
            "Bei der Nutzung von Stripe, Google, OpenAI, Microsoft oder anderen globalen Dienstleistern kann es zu Übermittlungen in Länder außerhalb der EU oder des EWR kommen.",
            "Soweit erforderlich, stützen wir solche Übermittlungen auf geeignete Garantien wie Angemessenheitsbeschlüsse, Standardvertragsklauseln oder vergleichbare Schutzmaßnahmen.",
          ],
        },
        {
          title: "Speicherdauer",
          body: [
            "Personenbezogene Daten werden nur so lange verarbeitet, wie es für die jeweiligen Zwecke erforderlich ist oder gesetzliche Aufbewahrungspflichten bestehen.",
            "Konto- und Workspace-Daten werden grundsätzlich bis zur Löschung des Kontos oder Vertragsendes gespeichert. Rechnungs- und steuerrelevante Daten werden entsprechend gesetzlicher Aufbewahrungsfristen gespeichert.",
            "Monitoring-Runs, Evaluationsergebnisse, Feedback, Learnings und LLM-Nutzungsdaten werden entsprechend Produktkonfiguration, Plan, Löschanforderung oder betrieblicher Erforderlichkeit gespeichert.",
            "E-Mail- und Workflow-Daten können durch Nutzer in der Anwendung gelöscht werden, soweit keine gesetzlichen oder vertraglichen Aufbewahrungspflichten entgegenstehen.",
          ],
        },
        {
          title: "Empfänger und Dienstleister",
          body: [
            "Empfänger personenbezogener Daten können interne berechtigte Personen von IsarAI sowie sorgfältig ausgewählte Dienstleister für Hosting, Datenbankbetrieb, Zahlungsabwicklung, E-Mail-Kommunikation, LLM-Verarbeitung, Sicherheit, Support und technische Infrastruktur sein.",
            "Soweit erforderlich, werden Auftragsverarbeitungsverträge oder vergleichbare Datenschutzvereinbarungen geschlossen.",
          ],
        },
        {
          title: "Ihre Rechte in der EU",
          body: [
            "Sie haben im gesetzlich vorgesehenen Umfang das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung der Verarbeitung, Datenübertragbarkeit, Widerspruch sowie das Recht, eine erteilte Einwilligung jederzeit zu widerrufen.",
            "Sie haben außerdem das Recht, Beschwerde bei einer zuständigen Datenschutzaufsichtsbehörde einzulegen.",
            "Anfragen richten Sie bitte an info@isarai.de oder support@mantly.io.",
          ],
        },
        {
          title: "Weitere Informationen für Nutzer in der Schweiz",
          body: [
            "Nutzer in der Schweiz können im Rahmen des anwendbaren Schweizer Datenschutzrechts insbesondere Auskunft, Berichtigung, Löschung, Einschränkung, Widerspruch und Herausgabe oder Übertragung personenbezogener Daten verlangen.",
            "Anfragen richten Sie bitte an info@isarai.de oder support@mantly.io.",
          ],
        },
        {
          title: "Änderungen dieser Datenschutzerklärung",
          body: [
            "Wir können diese Datenschutzerklärung anpassen, wenn sich Mantly, eingesetzte Dienstleister oder rechtliche Anforderungen ändern. Die jeweils aktuelle Fassung ist auf dieser Seite abrufbar.",
          ],
        },
      ],
    },
    terms: {
      title: "Nutzungsbedingungen",
      intro:
        "Diese Nutzungsbedingungen regeln die Nutzung von Mantly, einschließlich der öffentlichen Website, der Admin-Anwendung, des Outlook-Add-ins, der APIs und angebundener Dienste.",
      sections: [
        {
          title: "Stand",
          body: ["20. Mai 2026"],
        },
        {
          title: "Anbieter und Geltungsbereich",
          body: [
            "Mantly ist ein Angebot der IsarAI UG (haftungsbeschränkt), Breitensteinstr. 6, 82031 Grünwald.",
            "Diese Bedingungen gelten für Unternehmen, Organisationen und Verbraucher, soweit sie Mantly nutzen, ein Konto erstellen, einen Plan buchen oder auf Mantly-Dienste zugreifen.",
            "Abweichende Vereinbarungen, Auftragsverarbeitungsverträge oder individuelle Verträge gehen diesen Bedingungen vor, soweit sie ausdrücklich etwas anderes regeln.",
          ],
        },
        {
          title: "Konto und Berechtigung",
          body: [
            "Nutzer müssen richtige und aktuelle Angaben machen und Zugangsdaten vertraulich behandeln.",
            "Wer Mantly für ein Unternehmen oder eine Organisation nutzt, bestätigt, zur Nutzung und Verwaltung des jeweiligen Workspace berechtigt zu sein.",
            "Verbraucher dürfen Mantly nur nutzen, wenn sie geschäftsfähig sind oder die erforderliche Zustimmung eines gesetzlichen Vertreters vorliegt.",
          ],
        },
        {
          title: "Leistung und KI-Funktionen",
          body: [
            "Mantly unterstützt bei der Bearbeitung wiederkehrender E-Mail-Anliegen. Dazu gehören insbesondere Kunden- und Anliegenerkennung, Entwurf von Antworten, Vorschauen, Evaluationen, Monitoring, konfigurierte Aktionen und Tool-Aufrufe.",
            "Mantly nutzt KI-Modelle und Drittanbieter, um Inhalte zu analysieren, zu klassifizieren, zusammenzufassen, vorzubereiten oder zu generieren. KI-Ausgaben können falsch, unvollständig oder unpassend sein.",
            "Mantly ersetzt keine rechtliche, medizinische, finanzielle, steuerliche, sicherheitsbezogene oder sonstige professionelle Beratung.",
          ],
        },
        {
          title: "Prüfung und Verantwortung",
          body: [
            "Nutzer bleiben für E-Mails, Eingaben, Konfigurationen, Freigaben, gesendete Nachrichten, ausgeführte Aktionen und die Verwendung von KI-Ausgaben verantwortlich.",
            "Vor dem Senden, Veröffentlichen oder Ausführen müssen Nutzer prüfen, ob Inhalte richtig, vollständig, zulässig und für den jeweiligen Zweck geeignet sind.",
            "Besondere Vorsicht ist erforderlich, wenn Inhalte rechtliche, medizinische, finanzielle, HR-, Versicherungs-, Sicherheits- oder sonstige erhebliche Auswirkungen haben können.",
          ],
        },
        {
          title: "Daten und sensible Inhalte",
          body: [
            "Nutzer sind verantwortlich dafür, dass sie E-Mails, Anhänge, personenbezogene Daten, Geschäftsgeheimnisse und sonstige Inhalte rechtmäßig in Mantly verarbeiten dürfen.",
            "Besondere Kategorien personenbezogener Daten, Gesundheitsdaten, Daten über Straftaten, Ausweisdaten, Zahlungsdaten, Kinder-Daten, Passwörter, Geheimnisse oder vergleichbar sensible Daten dürfen nur verarbeitet werden, wenn der Nutzer hierzu berechtigt ist und Mantly dafür geeignet konfiguriert wurde.",
            "Nutzer müssen eigene Prüf-, Lösch-, Aufbewahrungs- und Freigabeprozesse einhalten.",
          ],
        },
        {
          title: "Zulässige Nutzung",
          body: [
            "Mantly darf nicht für rechtswidrige Inhalte, Spam, Phishing, Malware, Credential Theft, Umgehung von Sicherheitsmaßnahmen, Verletzung geistiger Eigentumsrechte, belästigende Inhalte, täuschende Aktivitäten oder missbräuchliche Automatisierung genutzt werden.",
            "Nutzer dürfen keine Systeme überlasten, Limits umgehen, Zugänge weiterverkaufen, Sicherheitsprüfungen umgehen, fremde Daten unbefugt verarbeiten oder Mantly in einer Weise nutzen, die Verfügbarkeit, Sicherheit oder Integrität des Dienstes beeinträchtigt.",
            "IsarAI kann Inhalte, Workspaces oder Zugänge einschränken oder sperren, wenn ein begründeter Verdacht auf Missbrauch, Sicherheitsrisiken oder Verstöße gegen diese Bedingungen besteht.",
          ],
        },
        {
          title: "Pläne, Testphasen, Preise und Zahlung",
          body: [
            "Mantly kann kostenlose Pläne, Testphasen, kostenpflichtige Abonnements und nutzungsbasierte Abrechnung anbieten.",
            "Preise, enthaltene Kontingente, Nutzungslimits, Verlängerung, Kündigung, Steuern und zusätzliche Gebühren werden im Checkout, in der Admin-Abrechnung oder in einem individuellen Angebot angezeigt.",
            "Zahlungen, Rechnungen, Kundenportal und Abonnementverwaltung können über Stripe abgewickelt werden. Kostenpflichtige Pläne verlängern sich, soweit angezeigt, bis sie gekündigt werden.",
            "Kostenlose Pläne oder Testphasen können eingeschränkt, geändert oder beendet werden, soweit dies rechtlich zulässig ist.",
          ],
        },
        {
          title: "Verfügbarkeit und Änderungen",
          body: [
            "IsarAI bemüht sich um einen stabilen Betrieb von Mantly, garantiert jedoch keine ununterbrochene oder fehlerfreie Verfügbarkeit.",
            "Wartung, Sicherheitsmaßnahmen, Anbieterprobleme, Updates oder höhere Gewalt können zu Einschränkungen führen.",
            "Mantly kann Funktionen ändern, erweitern oder entfernen, wenn dies für Sicherheit, Betrieb, Produktentwicklung, rechtliche Anforderungen oder technische Gründe erforderlich ist.",
          ],
        },
        {
          title: "Drittanbieter und Integrationen",
          body: [
            "Mantly kann mit Diensten wie Microsoft, Google, OpenAI, Stripe, Hosting-Anbietern, E-Mail-Diensten und vom Nutzer konfigurierten Tools oder LLM-Providern verbunden werden.",
            "Für Drittanbieter können zusätzliche Bedingungen, Datenschutzregeln, Verfügbarkeiten, Kosten und technische Grenzen gelten.",
            "Nutzer sind verantwortlich für die Rechtmäßigkeit, Sicherheit und Konfiguration eigener Zugangsdaten, Integrationen, Tools und Provider.",
          ],
        },
        {
          title: "Rechte an Inhalten und Software",
          body: [
            "Nutzer behalten ihre Rechte an eigenen Inhalten. Sie räumen IsarAI die Rechte ein, diese Inhalte zu verarbeiten, soweit dies zur Bereitstellung, Sicherung, Verbesserung und Abrechnung von Mantly erforderlich ist.",
            "Mantly, die Software, Oberflächen, Marken, Designs, Dokumentation und Systemlogik bleiben Eigentum von IsarAI oder den jeweiligen Rechteinhabern.",
            "Nutzer dürfen Mantly nicht kopieren, dekompilieren, zurückentwickeln, weiterverkaufen oder in nicht autorisierter Weise zugänglich machen, soweit dies nicht gesetzlich zwingend erlaubt ist.",
          ],
        },
        {
          title: "Laufzeit und Kündigung",
          body: [
            "Nutzer können Mantly entsprechend dem gebuchten Plan und den angezeigten Kündigungsoptionen kündigen.",
            "Die Kündigung kostenpflichtiger Abonnements wirkt regelmäßig zum Ende des aktuellen Abrechnungszeitraums, sofern im Checkout oder Vertrag nichts anderes geregelt ist.",
            "IsarAI kann Zugänge aus wichtigem Grund sperren oder beenden, insbesondere bei Sicherheitsrisiken, Zahlungsverzug, Rechtsverstößen oder erheblichen Verstößen gegen diese Bedingungen.",
          ],
        },
        {
          title: "Gewährleistung und Haftung",
          body: [
            "Für Verbraucher gelten die gesetzlichen Gewährleistungsrechte.",
            "Bei kostenpflichtiger Nutzung durch Unternehmen haftet IsarAI unbeschränkt bei Vorsatz, grober Fahrlässigkeit, Verletzung von Leben, Körper oder Gesundheit sowie nach zwingender gesetzlicher Haftung.",
            "Bei leichter Fahrlässigkeit haftet IsarAI nur bei Verletzung wesentlicher Vertragspflichten und beschränkt auf den vertragstypischen, vorhersehbaren Schaden, soweit gesetzlich zulässig.",
            "Eine Haftung für vom Nutzer geprüfte, freigegebene oder gesendete Inhalte, fehlerhafte Nutzerkonfigurationen, Drittanbieter, eigene Integrationen oder nicht erkannte Fehler in KI-Ausgaben ist ausgeschlossen, soweit gesetzlich zulässig.",
          ],
        },
        {
          title: "Datenschutz",
          body: [
            "Informationen zur Verarbeitung personenbezogener Daten enthält die Datenschutzerklärung von Mantly.",
            "Soweit Mantly im Auftrag eines Kunden personenbezogene Daten verarbeitet, können ergänzende Auftragsverarbeitungsbedingungen gelten.",
          ],
        },
        {
          title: "Verbraucherstreitbeilegung",
          body: [
            "IsarAI ist nicht verpflichtet und nicht bereit, an Streitbeilegungsverfahren vor einer Verbraucherschlichtungsstelle teilzunehmen, soweit keine gesetzliche Pflicht besteht.",
            "Die frühere EU-Plattform zur Online-Streitbeilegung wurde eingestellt.",
          ],
        },
        {
          title: "Recht und Gerichtsstand",
          body: [
            "Es gilt deutsches Recht unter Ausschluss des UN-Kaufrechts. Für Verbraucher bleiben zwingende Verbraucherschutzvorschriften des Aufenthaltsstaates unberührt.",
            "Gerichtsstand ist Berlin, soweit dies rechtlich zulässig ist.",
          ],
        },
        {
          title: "Änderungen dieser Bedingungen",
          body: [
            "IsarAI kann diese Bedingungen ändern, wenn Mantly, die rechtlichen Anforderungen, die Abrechnung oder technische Abläufe angepasst werden.",
            "Die jeweils aktuelle Fassung ist auf dieser Seite abrufbar. Bei wesentlichen Änderungen können Nutzer zusätzlich informiert werden.",
          ],
        },
        {
          title: "Kontakt",
          body: ["Fragen zu diesen Bedingungen können an info@isarai.de oder support@mantly.io gerichtet werden."],
        },
      ],
    },
    imprint: {
      title: "Impressum",
      intro: "Angaben zum Anbieter von Mantly.",
      sections: [
        {
          title: "Angaben gemäß § 5 TMG",
          body: [
            "IsarAI UG (haftungsbeschränkt)",
            "Breitensteinstr. 6",
            "82031 Grünwald",
            "Handelsregister Amtsgericht München HRB 273699",
            "UST-ID: DE457541055",
          ],
        },
        {
          title: "Kontakt",
          body: ["E-Mail: info@isarai.de"],
        },
        {
          title: "Vertreten durch",
          body: ["Bruno Polster"],
        },
      ],
    },
  },
  en: {
    privacy: {
      title: "Privacy Policy",
      intro:
        "This privacy policy explains how Mantly processes personal data on the public website, in the admin application, in the Outlook add-in, and in connected backend services.",
      sections: [
        {
          title: "Last Updated",
          body: ["May 19, 2026"],
        },
        {
          title: "Controller",
          body: [
            "IsarAI UG (limited liability)",
            "Breitensteinstr. 6",
            "82031 Grünwald",
            "Email: info@isarai.de",
            "Product and privacy requests can also be sent to support@mantly.io.",
          ],
        },
        {
          title: "Types of Data We Process",
          body: [
            "When you visit the public website, we process technical usage data such as IP address, browser, device data, access time, referrer, and requested pages.",
            "When you use Mantly, we process account and organization data such as email address, name, company, password and authentication status, roles, projects, and workspace assignments.",
            "In the Outlook add-in and admin application, email content and metadata may be processed, including sender, recipient, subject, body, attachments, technical email metadata, and user-triggered analysis or preview runs.",
            "We also process configurations for customer identification, intent detection, pipelines, actions, tools, response rules, instructions, templates, evaluation sets, test emails, evaluation results, feedback, learnings, monitoring logs, phishing and prompt-injection risk results, and token and usage data.",
            "For billing and contract management, we process plan, payment, invoice, subscription, and usage data.",
          ],
        },
        {
          title: "Purposes",
          body: [
            "We process personal data to provide the website, create and manage accounts, operate the Mantly SaaS service, admin application, and Outlook add-in.",
            "Email and workflow data is processed to identify customers, detect intents, prepare replies, execute actions and tools, generate previews, prepare publishing, and run evaluations.",
            "Additional purposes include security, abuse and fraud prevention, phishing and prompt-injection warnings, monitoring, error analysis, support, product improvement, usage limits, token metering, billing, and compliance with legal obligations.",
          ],
        },
        {
          title: "Legal Bases",
          body: [
            "Processing for providing Mantly, managing accounts and projects, analyzing emails, running workflows, and billing is generally based on contract performance or pre-contractual measures.",
            "Security, error analysis, abuse prevention, monitoring, and product improvement are based on legitimate interests, unless overridden by the interests of affected persons.",
            "Invoice and tax-related data is processed where necessary to comply with legal obligations.",
            "Analytics on the public landing page are used for product improvement on the basis of legitimate interests, unless overridden by the interests of affected persons.",
          ],
        },
        {
          title: "Hosting and Infrastructure",
          body: [
            "Mantly is hosted on infrastructure provided by Hetzner Online GmbH, www.hetzner.com. Hetzner processes technical usage data, server logs, and application and database data stored on the infrastructure where required for hosting, availability, security, and operation.",
            "The database and application storage are operated by IsarAI. PocketBase is self-hosted and is not a separate external cloud service.",
          ],
        },
        {
          title: "Payments and Billing",
          body: [
            "We use Stripe for payment processing, checkout, subscriptions, invoices, customer portal, and usage-based billing.",
            "This may include email address, customer data, invoice data, payment metadata, Stripe customer and subscription IDs, and billing-relevant usage events.",
          ],
        },
        {
          title: "LLM Providers",
          body: [
            "For AI features, Mantly may use Google Gemini or OpenAI. Depending on configuration, email content, metadata, project configurations, customer and intent context, actions, tools, instructions, evaluations, feedback, learnings, and generated outputs may be sent to the relevant provider.",
            "Processing is used for email analysis, customer identification, intent detection, reply drafting, evaluation, security checks, and token usage metadata.",
            "If a customer configures their own LLM credentials or provider, that provider processes data according to the customer's configuration.",
          ],
        },
        {
          title: "Email Communication",
          body: [
            "We use Google Workspace and Cloudflare Email Routing for transactional emails, email verification, password resets, support communication, and email routing.",
            "This may include email addresses, names, company information, message content, and technical email metadata.",
          ],
        },
        {
          title: "Analytics on the Public Landing Page",
          body: [
            "On the public landing page, we may use PostHog in cookieless mode to understand usage, page views, interactions, and technical metrics.",
            "This analytics use currently applies only to the public landing page, not to the admin application and not to the Outlook add-in.",
            "PostHog is operated without cookies and without persistent browser identification.",
          ],
        },
        {
          title: "Cookies, Local Storage, and Trackers",
          body: [
            "Mantly uses technically necessary storage, especially for language preferences, authentication, active projects, UI state, and session management.",
            "The public landing page uses PostHog in cookieless mode without cookies and without persistent browser identification.",
            "You can delete or block browser storage and cookies in your browser. This may limit application functionality.",
          ],
        },
        {
          title: "International Transfers",
          body: [
            "When using Stripe, Google, OpenAI, Microsoft, or other global providers, data may be transferred to countries outside the EU or EEA.",
            "Where required, we rely on appropriate safeguards such as adequacy decisions, standard contractual clauses, or comparable protective measures.",
          ],
        },
        {
          title: "Retention",
          body: [
            "Personal data is processed only for as long as required for the relevant purposes or as required by legal retention obligations.",
            "Account and workspace data is generally stored until account deletion or contract termination. Invoice and tax-related data is stored according to statutory retention periods.",
            "Monitoring runs, evaluation results, feedback, learnings, and LLM usage data are stored according to product configuration, plan, deletion request, or operational necessity.",
            "Email and workflow data can be deleted by users in the application unless legal or contractual retention obligations apply.",
          ],
        },
        {
          title: "Recipients and Providers",
          body: [
            "Recipients of personal data may include authorized IsarAI personnel and carefully selected service providers for hosting, database operation, payment processing, email communication, LLM processing, security, support, and technical infrastructure.",
            "Where required, data processing agreements or comparable privacy agreements are concluded.",
          ],
        },
        {
          title: "Your Rights in the EU",
          body: [
            "Within the limits provided by law, you have the right to access, rectification, erasure, restriction of processing, data portability, objection, and withdrawal of consent.",
            "You also have the right to lodge a complaint with a competent data protection supervisory authority.",
            "Please send requests to info@isarai.de or support@mantly.io.",
          ],
        },
        {
          title: "Additional Information for Users in Switzerland",
          body: [
            "Users in Switzerland may exercise rights under applicable Swiss data protection law, including access, rectification, erasure, restriction, objection, and receiving or transferring personal data.",
            "Please send requests to info@isarai.de or support@mantly.io.",
          ],
        },
        {
          title: "Changes to This Privacy Policy",
          body: [
            "We may update this privacy policy if Mantly, the providers we use, or legal requirements change. The current version is available on this page.",
          ],
        },
      ],
    },
    terms: {
      title: "Terms of Use",
      intro:
        "These Terms of Use govern your use of Mantly, including the public website, admin application, Outlook add-in, APIs, and connected services.",
      sections: [
        {
          title: "Effective Date",
          body: ["May 20, 2026"],
        },
        {
          title: "Provider and Scope",
          body: [
            "Mantly is provided by IsarAI UG (limited liability), Breitensteinstr. 6, 82031 Grünwald, Germany.",
            "These terms apply to businesses, organizations, and consumers who use Mantly, create an account, subscribe to a plan, or access Mantly services.",
            "Separate agreements, data processing agreements, or individual contracts prevail over these terms where they expressly provide different rules.",
          ],
        },
        {
          title: "Account and Authority",
          body: [
            "Users must provide accurate and current information and keep login credentials confidential.",
            "If you use Mantly for a company or organization, you confirm that you are authorized to use and administer the relevant workspace.",
            "Consumers may use Mantly only if they have legal capacity or the required consent of a legal representative.",
          ],
        },
        {
          title: "Service and AI Features",
          body: [
            "Mantly helps process recurring email cases. This may include customer and intent detection, reply drafting, previews, evaluations, monitoring, configured actions, and tool calls.",
            "Mantly uses AI models and third-party providers to analyze, classify, summarize, prepare, or generate content. AI outputs may be inaccurate, incomplete, or unsuitable.",
            "Mantly does not replace legal, medical, financial, tax, security, or other professional advice.",
          ],
        },
        {
          title: "Review and Responsibility",
          body: [
            "Users remain responsible for emails, inputs, configurations, approvals, sent messages, executed actions, and use of AI outputs.",
            "Before sending, publishing, or executing anything, users must check that content is accurate, complete, lawful, and suitable for the relevant purpose.",
            "Special care is required where content may have legal, medical, financial, HR, insurance, security, or other significant effects.",
          ],
        },
        {
          title: "Data and Sensitive Content",
          body: [
            "Users are responsible for ensuring they may lawfully process emails, attachments, personal data, trade secrets, and other content in Mantly.",
            "Special categories of personal data, health data, criminal data, identity documents, payment data, children's data, passwords, secrets, or similarly sensitive data may be processed only if the user is legally allowed to do so and Mantly has been configured appropriately.",
            "Users must follow their own review, deletion, retention, and approval processes.",
          ],
        },
        {
          title: "Acceptable Use",
          body: [
            "Mantly may not be used for illegal content, spam, phishing, malware, credential theft, bypassing security measures, infringement of intellectual property rights, harassment, deceptive activity, or abusive automation.",
            "Users must not overload systems, bypass limits, resell access, circumvent security checks, process third-party data without authorization, or use Mantly in a way that harms the availability, security, or integrity of the service.",
            "IsarAI may restrict or suspend content, workspaces, or access where there is a reasonable suspicion of abuse, security risk, or violation of these terms.",
          ],
        },
        {
          title: "Plans, Trials, Pricing, and Payment",
          body: [
            "Mantly may offer free plans, trials, paid subscriptions, and usage-based billing.",
            "Prices, included quotas, usage limits, renewal, cancellation, taxes, and additional fees are shown in checkout, admin billing, or an individual offer.",
            "Payments, invoices, customer portal, and subscription management may be handled through Stripe. Paid plans renew, where shown, until canceled.",
            "Free plans or trials may be limited, changed, or ended where legally permitted.",
          ],
        },
        {
          title: "Availability and Changes",
          body: [
            "IsarAI works to keep Mantly stable, but does not guarantee uninterrupted or error-free availability.",
            "Maintenance, security measures, provider issues, updates, or force majeure may cause limitations.",
            "Mantly may change, add, or remove features where required for security, operations, product development, legal requirements, or technical reasons.",
          ],
        },
        {
          title: "Third-Party Providers and Integrations",
          body: [
            "Mantly may connect to services such as Microsoft, Google, OpenAI, Stripe, hosting providers, email services, and user-configured tools or LLM providers.",
            "Third-party services may have their own terms, privacy rules, availability, costs, and technical limits.",
            "Users are responsible for the legality, security, and configuration of their own credentials, integrations, tools, and providers.",
          ],
        },
        {
          title: "Content and Software Rights",
          body: [
            "Users keep their rights in their own content. Users grant IsarAI the rights needed to process that content for providing, securing, improving, and billing Mantly.",
            "Mantly, its software, interfaces, trademarks, designs, documentation, and system logic remain owned by IsarAI or the relevant rights holders.",
            "Users must not copy, decompile, reverse engineer, resell, or make Mantly available in an unauthorized way unless mandatory law allows it.",
          ],
        },
        {
          title: "Term and Termination",
          body: [
            "Users may cancel Mantly according to the subscribed plan and displayed cancellation options.",
            "Cancellation of paid subscriptions usually takes effect at the end of the current billing period unless checkout or a contract states otherwise.",
            "IsarAI may suspend or terminate access for cause, especially in case of security risks, payment default, unlawful conduct, or material breach of these terms.",
          ],
        },
        {
          title: "Warranty and Liability",
          body: [
            "Consumers retain their statutory warranty rights.",
            "For paid business use, IsarAI has unlimited liability for intent, gross negligence, injury to life, body, or health, and mandatory statutory liability.",
            "For slight negligence, IsarAI is liable only for breach of essential contractual duties and limited to typical, foreseeable damage where legally permitted.",
            "Liability for user-reviewed, approved, or sent content, incorrect user configuration, third-party providers, user integrations, or undetected errors in AI outputs is excluded where legally permitted.",
          ],
        },
        {
          title: "Privacy",
          body: [
            "Information on personal data processing is provided in the Mantly Privacy Policy.",
            "Where Mantly processes personal data on behalf of a customer, additional data processing terms may apply.",
          ],
        },
        {
          title: "Consumer Dispute Resolution",
          body: [
            "IsarAI is not obligated and not willing to participate in dispute resolution proceedings before a consumer arbitration board unless legally required.",
            "The former EU online dispute resolution platform has been discontinued.",
          ],
        },
        {
          title: "Governing Law and Venue",
          body: [
            "German law applies, excluding the UN Convention on Contracts for the International Sale of Goods. Mandatory consumer protection laws of the consumer's country of residence remain unaffected.",
            "Venue is Berlin where legally permitted.",
          ],
        },
        {
          title: "Changes to These Terms",
          body: [
            "IsarAI may update these terms if Mantly, legal requirements, billing, or technical processes change.",
            "The current version is available on this page. Users may receive additional notice for material changes.",
          ],
        },
        {
          title: "Contact",
          body: ["Questions about these terms can be sent to info@isarai.de or support@mantly.io."],
        },
      ],
    },
    imprint: {
      title: "Imprint",
      intro: "Provider information for Mantly.",
      sections: [
        {
          title: "Information pursuant to Section 5 TMG",
          body: [
            "IsarAI UG (limited liability)",
            "Breitensteinstr. 6",
            "82031 Grünwald",
            "Commercial register: Local Court of Munich, HRB 273699",
            "VAT ID: DE457541055",
          ],
        },
        {
          title: "Contact",
          body: ["Email: info@isarai.de"],
        },
        {
          title: "Represented by",
          body: ["Bruno Polster"],
        },
      ],
    },
  },
};

export function LegalPage({ kind }: { kind: LegalPageKind }) {
  const { lang } = useTranslation();
  const page = content[lang][kind];

  return (
    <main className="pt-32 pb-20 sm:pt-40">
      <div className="mx-auto max-w-3xl px-4 sm:px-6 lg:px-8">
        <p className="text-xs font-semibold uppercase tracking-widest text-primary">
          Mantly
        </p>
        <h1 className="mt-4 text-[2.5rem] leading-tight sm:text-[3rem] lg:text-[3.5rem]">
          {page.title}
        </h1>
        <p className="mt-5 text-lg leading-relaxed text-muted-foreground">
          {page.intro}
        </p>

        <div className="mt-12 space-y-10">
          {page.sections.map((section) => (
            <section key={section.title} className="border-t border-border/60 pt-6">
              <h2 className="text-2xl font-normal">{section.title}</h2>
              <div className="mt-4 space-y-3 text-base leading-relaxed text-muted-foreground">
                {section.body.map((paragraph) => (
                  <p key={paragraph}>{paragraph}</p>
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>
    </main>
  );
}
