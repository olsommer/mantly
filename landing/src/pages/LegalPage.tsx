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
        "Diese Datenschutzerklärung informiert darüber, wie IsarAI personenbezogene Daten auf der öffentlichen Website und bei der Bereitstellung von Mantly Cloud einschließlich Admin-Anwendung, verbundenen Supportkanälen und Backend-Diensten verarbeitet.",
      sections: [
        {
          title: "Stand",
          body: ["21. Juli 2026"],
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
            "Bei der Nutzung von Mantly Cloud verarbeiten wir Konto- und Organisationsdaten wie E-Mail-Adresse, Name, Unternehmen, Passwort- und Authentifizierungsstatus, Rollen, Projekte und Workspace-Zuordnungen.",
            "In Mantly Cloud können Inhalte und Metadaten aus verbundenen Supportkanälen verarbeitet werden, etwa Absender oder Teilnehmer, Empfänger, Betreff, Nachrichtentext, Anhänge, kanalbezogene technische Metadaten sowie ausgelöste Analyse- oder Vorschau-Runs. Dazu können insbesondere E-Mail-, Webchat- und weitere konfigurierte Kanalnachrichten gehören.",
            "Darüber hinaus verarbeiten wir Konfigurationen für Kunden- und Anliegenerkennung, Pipelines, Aktionen, Tools, Antwortregeln, Instruktionen, Vorlagen, Evaluation-Sets, Testnachrichten, Evaluationsergebnisse, Feedback, Learnings, Monitoring-Logs, Risikoergebnisse für Phishing und Prompt Injection sowie Token- und Nutzungsdaten.",
            "Für Abrechnung und Vertragsverwaltung von Mantly Cloud verarbeiten wir Plan-, Zahlungs-, Rechnungs-, Subscription- und Usage-Daten.",
          ],
        },
        {
          title: "Zwecke der Verarbeitung",
          body: [
            "Wir verarbeiten personenbezogene Daten zur Bereitstellung der Website sowie zur Kontoerstellung, Anmeldung und Bereitstellung von Mantly Cloud, der Admin-Anwendung und verbundenen Supportkanälen.",
            "Supportnachrichten und Workflow-Daten werden verarbeitet, um Kunden zu identifizieren, Anliegen zu erkennen, Antworten vorzubereiten, Aktionen und Tools auszuführen, Vorschauen zu erzeugen, Veröffentlichungen vorzubereiten und Evaluationen durchzuführen.",
            "Weitere Zwecke sind Sicherheit, Missbrauchs- und Betrugsprävention, Phishing- und Prompt-Injection-Warnungen, Monitoring, Fehleranalyse, Support, Produktverbesserung, Nutzungslimits, Token-Metering, Abrechnung und Erfüllung gesetzlicher Pflichten.",
          ],
        },
        {
          title: "Rechtsgrundlagen",
          body: [
            "Die Verarbeitung zur Bereitstellung von Mantly Cloud, zur Konto- und Projektverwaltung, zur Analyse von Supportnachrichten, zur Durchführung von Workflows und zur Abrechnung erfolgt regelmäßig zur Erfüllung eines Vertrags oder zur Durchführung vorvertraglicher Maßnahmen.",
            "Sicherheits-, Fehleranalyse-, Missbrauchspräventions-, Monitoring- und Produktverbesserungszwecke beruhen auf berechtigten Interessen, soweit nicht überwiegende Interessen der betroffenen Personen entgegenstehen.",
            "Rechnungs- und steuerrelevante Daten werden verarbeitet, soweit dies zur Erfüllung gesetzlicher Pflichten erforderlich ist.",
            "Analyse der öffentlichen Landingpage erfolgt zur Produktverbesserung auf Grundlage berechtigter Interessen, soweit nicht überwiegende Interessen der betroffenen Personen entgegenstehen.",
          ],
        },
        {
          title: "Hosting und Infrastruktur",
          body: [
            "Die öffentliche Website und Mantly Cloud werden auf Infrastruktur der Hetzner Online GmbH, www.hetzner.com, betrieben. Hetzner verarbeitet technische Nutzungsdaten, Server-Logs und dort gespeicherte Anwendungs- und Datenbankdaten, soweit dies für Hosting, Verfügbarkeit, Sicherheit und Betrieb erforderlich ist.",
            "Die Cloud-Datenbank und Anwendungsspeicher werden durch IsarAI betrieben. PocketBase wird von IsarAI selbst gehostet und ist kein eigenständiger externer Cloud-Dienst.",
          ],
        },
        {
          title: "Self-hosted Community Edition",
          body: [
            "Bei einer selbst betriebenen Mantly Community-Instanz bestimmt der jeweilige Betreiber, welche Daten verarbeitet werden, wo die Instanz läuft und welche Anbieter oder Integrationen angebunden sind. IsarAI verarbeitet Daten dieser Instanz nicht allein dadurch, dass die Open-Source-Software eingesetzt wird.",
            "Daten einer Community-Instanz erreichen IsarAI nur, wenn der Betreiber oder Nutzer einen separaten IsarAI-Dienst verwendet, Support kontaktiert oder ausdrücklich eine von IsarAI betriebene Integration konfiguriert. Für selbst gewählte LLM-, Kanal- und Infrastruktur-Anbieter ist der Betreiber verantwortlich.",
          ],
        },
        {
          title: "Zahlung und Abrechnung",
          body: [
            "Für Zahlungsabwicklung, Checkout, Abonnements, Rechnungen, Kundenportal und nutzungsbasierte Abrechnung von Mantly Cloud setzen wir Stripe ein.",
            "Dabei können insbesondere E-Mail-Adresse, Kundendaten, Rechnungsdaten, Zahlungsmetadaten, Stripe-Kunden- und Subscription-IDs sowie abrechnungsrelevante Nutzungsereignisse verarbeitet werden.",
          ],
        },
        {
          title: "LLM-Anbieter",
          body: [
            "Für KI-Funktionen in Mantly Cloud kann IsarAI Google Gemini oder OpenAI verwenden. Je nach Konfiguration werden Supportnachrichten, Metadaten, Projektkonfigurationen, Kunden- und Anliegenkontext, Aktionen, Tools, Instruktionen, Evaluationen, Feedback, Learnings und generierte Ausgaben an den jeweiligen Anbieter übermittelt.",
            "Die Verarbeitung erfolgt zur Nachrichtenanalyse, Kundenidentifikation, Anliegenerkennung, Antworterstellung, Evaluation, Sicherheitsprüfung und Erfassung von Token-Nutzungsmetadaten.",
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
            "Diese Analyse betrifft derzeit nur die öffentliche Landingpage, nicht die Admin-Anwendung und nicht Inhalte aus verbundenen Supportkanälen.",
            "PostHog wird ohne Cookies und ohne persistente Browser-Identifikation betrieben.",
          ],
        },
        {
          title: "Cookies, lokale Speicherung und Tracker",
          body: [
            "Mantly verwendet technisch notwendige Speicherung, insbesondere für Spracheinstellungen, Authentifizierung, aktive Projekte, UI-Zustände und Sitzungsverwaltung.",
            "Die öffentliche Landingpage nutzt PostHog im Cookieless-Modus ohne Cookies und ohne persistente Browser-Identifikation.",
            "Du kannst Browser-Speicher und Cookies in deinem Browser löschen oder blockieren. Dies kann die Funktionalität der Anwendung einschränken.",
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
            "Konto- und Workspace-Daten in Mantly Cloud werden grundsätzlich bis zur Löschung des Kontos oder Vertragsendes gespeichert. Rechnungs- und steuerrelevante Daten werden entsprechend gesetzlicher Aufbewahrungsfristen gespeichert.",
            "Monitoring-Runs, Evaluationsergebnisse, Feedback, Learnings und LLM-Nutzungsdaten werden entsprechend Produktkonfiguration, Plan, Löschanforderung oder betrieblicher Erforderlichkeit gespeichert.",
            "Supportnachrichten und Workflow-Daten können durch Nutzer in der Anwendung gelöscht werden, soweit keine gesetzlichen oder vertraglichen Aufbewahrungspflichten entgegenstehen.",
          ],
        },
        {
          title: "Empfänger und Dienstleister",
          body: [
            "Bei der Bereitstellung von Mantly Cloud können Empfänger personenbezogener Daten interne berechtigte Personen von IsarAI sowie sorgfältig ausgewählte Dienstleister für Hosting, Datenbankbetrieb, Zahlungsabwicklung, Nachrichtenkommunikation, LLM-Verarbeitung, Sicherheit, Support und technische Infrastruktur sein.",
            "Soweit erforderlich, werden Auftragsverarbeitungsverträge oder vergleichbare Datenschutzvereinbarungen geschlossen.",
          ],
        },
        {
          title: "Deine Rechte in der EU",
          body: [
            "Du hast im gesetzlich vorgesehenen Umfang das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung der Verarbeitung, Datenübertragbarkeit, Widerspruch sowie das Recht, eine erteilte Einwilligung jederzeit zu widerrufen.",
            "Du hast außerdem das Recht, Beschwerde bei einer zuständigen Datenschutzaufsichtsbehörde einzulegen.",
            "Richte Anfragen bitte an info@isarai.de oder support@mantly.io.",
          ],
        },
        {
          title: "Weitere Informationen für Nutzer in der Schweiz",
          body: [
            "Nutzer in der Schweiz können im Rahmen des anwendbaren Schweizer Datenschutzrechts insbesondere Auskunft, Berichtigung, Löschung, Einschränkung, Widerspruch und Herausgabe oder Übertragung personenbezogener Daten verlangen.",
            "Richte Anfragen bitte an info@isarai.de oder support@mantly.io.",
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
        "Diese Nutzungsbedingungen regeln Mantly Cloud und andere von IsarAI betriebene Dienste, einschließlich der öffentlichen Website, der gehosteten Admin-Anwendung, APIs und angebundener Dienste.",
      sections: [
        {
          title: "Stand",
          body: ["21. Juli 2026"],
        },
        {
          title: "Anbieter und Geltungsbereich",
          body: [
            "Mantly ist ein Angebot der IsarAI UG (haftungsbeschränkt), Breitensteinstr. 6, 82031 Grünwald.",
            "Diese Bedingungen gelten für Unternehmen, Organisationen und Verbraucher, soweit sie Mantly Cloud oder andere von IsarAI betriebene Dienste nutzen, ein gehostetes Konto erstellen, einen Plan buchen oder auf solche Dienste zugreifen.",
            "Der Quellcode der Mantly Community Edition wird unabhängig von diesen Bedingungen unter der GNU Affero General Public License Version 3 bereitgestellt. Für Nutzung, Vervielfältigung, Änderung und Verbreitung dieses Codes gilt ausschließlich diese Open-Source-Lizenz; diese Bedingungen schränken die dort gewährten Rechte nicht ein.",
            "Abweichende Vereinbarungen, Auftragsverarbeitungsverträge oder individuelle Verträge gehen diesen Bedingungen vor, soweit sie ausdrücklich etwas anderes regeln.",
          ],
        },
        {
          title: "Konto und Berechtigung",
          body: [
            "Nutzer müssen richtige und aktuelle Angaben machen und Zugangsdaten vertraulich behandeln.",
            "Wer Mantly Cloud für ein Unternehmen oder eine Organisation nutzt, bestätigt, zur Nutzung und Verwaltung des jeweiligen gehosteten Workspace berechtigt zu sein.",
            "Verbraucher dürfen die von IsarAI betriebenen Dienste nur nutzen, wenn sie geschäftsfähig sind oder die erforderliche Zustimmung eines gesetzlichen Vertreters vorliegt.",
          ],
        },
        {
          title: "Leistung und KI-Funktionen",
          body: [
            "Mantly Cloud unterstützt bei der Bearbeitung wiederkehrender Supporttickets über verbundene Kanäle. Dazu gehören insbesondere Kunden- und Anliegenerkennung, Antworterstellung, Evaluationen, Monitoring, konfigurierte Aktionen und Tool-Aufrufe.",
            "Mantly Cloud nutzt KI-Modelle und Drittanbieter, um Inhalte zu analysieren, zu klassifizieren, zusammenzufassen, vorzubereiten oder zu generieren. KI-Ausgaben können falsch, unvollständig oder unpassend sein.",
            "Mantly Cloud ersetzt keine rechtliche, medizinische, finanzielle, steuerliche, sicherheitsbezogene oder sonstige professionelle Beratung.",
          ],
        },
        {
          title: "Prüfung und Verantwortung",
          body: [
            "Nutzer bleiben für Eingaben, Konfigurationen, Freigaberichtlinien, gesendete Nachrichten, ausgeführte Aktionen und die Verwendung von KI-Ausgaben verantwortlich.",
            "Nutzer müssen angemessene Prüf- und Freigaberichtlinien konfigurieren. Automatisches Senden darf nur aktiviert werden, wenn der Nutzer dies nach Bewertung der damit verbundenen Risiken für angemessen hält; konfigurierte Freigabeschritte werden von Mantly Cloud nicht umgangen.",
            "Vor der Freigabe sensibler Ergebnisse oder der Aktivierung automatisierter Aktionen müssen Nutzer prüfen, ob Inhalte und Aktionen richtig, vollständig, zulässig und für den jeweiligen Zweck geeignet sind. Besondere Vorsicht ist bei rechtlichen, medizinischen, finanziellen, HR-, Versicherungs-, Sicherheits- oder sonstigen erheblichen Auswirkungen erforderlich.",
          ],
        },
        {
          title: "Daten und sensible Inhalte",
          body: [
            "Nutzer sind verantwortlich dafür, dass sie Supportnachrichten, Anhänge, personenbezogene Daten, Geschäftsgeheimnisse und sonstige Inhalte rechtmäßig in Mantly Cloud verarbeiten dürfen.",
            "Besondere Kategorien personenbezogener Daten, Gesundheitsdaten, Daten über Straftaten, Ausweisdaten, Zahlungsdaten, Kinder-Daten, Passwörter, Geheimnisse oder vergleichbar sensible Daten dürfen nur verarbeitet werden, wenn der Nutzer hierzu berechtigt ist und Mantly dafür geeignet konfiguriert wurde.",
            "Nutzer müssen eigene Prüf-, Lösch-, Aufbewahrungs- und Freigabeprozesse einhalten.",
          ],
        },
        {
          title: "Zulässige Nutzung",
          body: [
            "Mantly Cloud und andere von IsarAI betriebene Dienste dürfen nicht für rechtswidrige Inhalte, Spam, Phishing, Malware, Credential Theft, Umgehung von Sicherheitsmaßnahmen, Verletzung geistiger Eigentumsrechte, belästigende Inhalte, täuschende Aktivitäten oder missbräuchliche Automatisierung genutzt werden.",
            "Bei Mantly Cloud dürfen Nutzer keine Systeme überlasten, Limits umgehen, gehostete Zugänge ohne entsprechende Vereinbarung weiterverkaufen, Sicherheitsprüfungen umgehen, fremde Daten unbefugt verarbeiten oder den Dienst in einer Weise nutzen, die seine Verfügbarkeit, Sicherheit oder Integrität beeinträchtigt. Rechte aus der Open-Source-Lizenz der Community Edition bleiben unberührt.",
            "IsarAI kann gehostete Inhalte, Workspaces oder Zugänge einschränken oder sperren, wenn ein begründeter Verdacht auf Missbrauch, Sicherheitsrisiken oder Verstöße gegen diese Bedingungen besteht. Rechte aus der Open-Source-Lizenz der Community Edition bleiben davon unberührt.",
          ],
        },
        {
          title: "Pläne, Testphasen, Preise und Zahlung",
          body: [
            "Mantly Cloud kann kostenlose Pläne, Testphasen, kostenpflichtige Abonnements und nutzungsbasierte Abrechnung anbieten.",
            "Preise, enthaltene Kontingente, Nutzungslimits, Verlängerung, Kündigung, Steuern und zusätzliche Gebühren werden im Checkout, in der Admin-Abrechnung oder in einem individuellen Angebot angezeigt.",
            "Zahlungen, Rechnungen, Kundenportal und Abonnementverwaltung können über Stripe abgewickelt werden. Kostenpflichtige Pläne verlängern sich, soweit angezeigt, bis sie gekündigt werden.",
            "Kostenlose Pläne oder Testphasen können eingeschränkt, geändert oder beendet werden, soweit dies rechtlich zulässig ist.",
          ],
        },
        {
          title: "Verfügbarkeit und Änderungen",
          body: [
            "IsarAI bemüht sich um einen stabilen Betrieb von Mantly Cloud, garantiert jedoch keine ununterbrochene oder fehlerfreie Verfügbarkeit.",
            "Wartung, Sicherheitsmaßnahmen, Anbieterprobleme, Updates oder höhere Gewalt können zu Einschränkungen führen.",
            "IsarAI kann Funktionen seiner gehosteten Dienste ändern, erweitern oder entfernen, wenn dies für Sicherheit, Betrieb, Produktentwicklung, rechtliche Anforderungen oder technische Gründe erforderlich ist.",
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
            "Nutzer behalten ihre Rechte an eigenen Inhalten. Für Inhalte, die sie an Mantly Cloud übermitteln, räumen sie IsarAI die Rechte ein, diese Inhalte zu verarbeiten, soweit dies zur Bereitstellung, Sicherung, Verbesserung und Abrechnung des gehosteten Dienstes erforderlich ist.",
            "Urheberrechte, Marken, Designs und nicht unter einer Open-Source-Lizenz veröffentlichte Bestandteile bleiben bei IsarAI oder den jeweiligen Rechteinhabern.",
            "Der Quellcode der Community Edition darf im Umfang der GNU Affero General Public License Version 3 genutzt, untersucht, geändert und verbreitet werden. Für Mantly Cloud, Marken und proprietäre Bestandteile gelten ergänzend diese Bedingungen und gegebenenfalls individuelle Verträge.",
          ],
        },
        {
          title: "Laufzeit und Kündigung",
          body: [
            "Nutzer können Mantly Cloud entsprechend dem gebuchten Plan und den angezeigten Kündigungsoptionen kündigen.",
            "Die Kündigung kostenpflichtiger Abonnements wirkt regelmäßig zum Ende des aktuellen Abrechnungszeitraums, sofern im Checkout oder Vertrag nichts anderes geregelt ist.",
            "IsarAI kann gehostete Zugänge aus wichtigem Grund sperren oder beenden, insbesondere bei Sicherheitsrisiken, Zahlungsverzug, Rechtsverstößen oder erheblichen Verstößen gegen diese Bedingungen.",
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
            "Informationen zur Verarbeitung personenbezogener Daten durch IsarAI enthält die Datenschutzerklärung von Mantly.",
            "Soweit IsarAI über Mantly Cloud im Auftrag eines Kunden personenbezogene Daten verarbeitet, können ergänzende Auftragsverarbeitungsbedingungen gelten.",
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
            "IsarAI kann diese Bedingungen ändern, wenn die von IsarAI betriebenen Dienste, rechtliche Anforderungen, die Abrechnung oder technische Abläufe angepasst werden.",
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
        "This privacy policy explains how IsarAI processes personal data on the public website and when providing Mantly Cloud, including the admin application, connected support channels, and backend services.",
      sections: [
        {
          title: "Last Updated",
          body: ["July 21, 2026"],
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
            "When you use Mantly Cloud, we process account and organization data such as email address, name, company, password and authentication status, roles, projects, and workspace assignments.",
            "Mantly Cloud may process content and metadata from connected support channels, such as senders or participants, recipients, subjects, message bodies, attachments, channel-specific technical metadata, and user-triggered analysis or preview runs. This may include email, web chat, and other configured channel messages.",
            "We also process configurations for customer and concern detection, pipelines, actions, tools, response rules, instructions, templates, evaluation sets, test messages, evaluation results, feedback, learnings, monitoring logs, phishing and prompt-injection risk results, and token and usage data.",
            "For Mantly Cloud billing and contract management, we process plan, payment, invoice, subscription, and usage data.",
          ],
        },
        {
          title: "Purposes",
          body: [
            "We process personal data to provide the website and to create accounts, manage sign-in, and operate Mantly Cloud, the admin application, and connected support channels.",
            "Support messages and workflow data are processed to identify customers, detect concerns, prepare replies, execute actions and tools, generate previews, prepare publishing, and run evaluations.",
            "Additional purposes include security, abuse and fraud prevention, phishing and prompt-injection warnings, monitoring, error analysis, support, product improvement, usage limits, token metering, billing, and compliance with legal obligations.",
          ],
        },
        {
          title: "Legal Bases",
          body: [
            "Processing for providing Mantly Cloud, managing accounts and projects, analyzing support messages, running workflows, and billing is generally based on contract performance or pre-contractual measures.",
            "Security, error analysis, abuse prevention, monitoring, and product improvement are based on legitimate interests, unless overridden by the interests of affected persons.",
            "Invoice and tax-related data is processed where necessary to comply with legal obligations.",
            "Analytics on the public landing page are used for product improvement on the basis of legitimate interests, unless overridden by the interests of affected persons.",
          ],
        },
        {
          title: "Hosting and Infrastructure",
          body: [
            "The public website and Mantly Cloud are hosted on infrastructure provided by Hetzner Online GmbH, www.hetzner.com. Hetzner processes technical usage data, server logs, and application and database data stored there where required for hosting, availability, security, and operation.",
            "Cloud database and application storage are operated by IsarAI. PocketBase is self-hosted by IsarAI and is not a separate external cloud service.",
          ],
        },
        {
          title: "Self-Hosted Community Edition",
          body: [
            "For a self-hosted Mantly Community instance, the operator determines what data is processed, where the instance runs, and which providers or integrations are connected. IsarAI does not process that instance's data merely because the open-source software is used.",
            "Data from a Community instance reaches IsarAI only when the operator or user uses a separate IsarAI service, contacts support, or explicitly configures an IsarAI-operated integration. The operator is responsible for self-selected LLM, channel, and infrastructure providers.",
          ],
        },
        {
          title: "Payments and Billing",
          body: [
            "We use Stripe for Mantly Cloud payment processing, checkout, subscriptions, invoices, customer portal, and usage-based billing.",
            "This may include email address, customer data, invoice data, payment metadata, Stripe customer and subscription IDs, and billing-relevant usage events.",
          ],
        },
        {
          title: "LLM Providers",
          body: [
            "For AI features in Mantly Cloud, IsarAI may use Google Gemini or OpenAI. Depending on configuration, support messages, metadata, project configurations, customer and concern context, actions, tools, instructions, evaluations, feedback, learnings, and generated outputs may be sent to the relevant provider.",
            "Processing is used for message analysis, customer identification, concern detection, reply drafting, evaluation, security checks, and token usage metadata.",
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
            "This analytics use currently applies only to the public landing page, not to the admin application or content from connected support channels.",
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
            "Mantly Cloud account and workspace data is generally stored until account deletion or contract termination. Invoice and tax-related data is stored according to statutory retention periods.",
            "Monitoring runs, evaluation results, feedback, learnings, and LLM usage data are stored according to product configuration, plan, deletion request, or operational necessity.",
            "Support messages and workflow data can be deleted by users in the application unless legal or contractual retention obligations apply.",
          ],
        },
        {
          title: "Recipients and Providers",
          body: [
            "When providing Mantly Cloud, recipients of personal data may include authorized IsarAI personnel and carefully selected service providers for hosting, database operation, payment processing, message communication, LLM processing, security, support, and technical infrastructure.",
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
        "These Terms of Use govern Mantly Cloud and other services operated by IsarAI, including the public website, hosted admin application, APIs, and connected services.",
      sections: [
        {
          title: "Effective Date",
          body: ["July 21, 2026"],
        },
        {
          title: "Provider and Scope",
          body: [
            "Mantly is provided by IsarAI UG (limited liability), Breitensteinstr. 6, 82031 Grünwald, Germany.",
            "These terms apply to businesses, organizations, and consumers who use Mantly Cloud or other services operated by IsarAI, create a hosted account, subscribe to a plan, or access those services.",
            "The source code of Mantly Community Edition is provided separately under the GNU Affero General Public License version 3. Use, copying, modification, and distribution of that code are governed exclusively by the open-source license; these terms do not limit rights granted by that license.",
            "Separate agreements, data processing agreements, or individual contracts prevail over these terms where they expressly provide different rules.",
          ],
        },
        {
          title: "Account and Authority",
          body: [
            "Users must provide accurate and current information and keep login credentials confidential.",
            "If you use Mantly Cloud for a company or organization, you confirm that you are authorized to use and administer the relevant hosted workspace.",
            "Consumers may use services operated by IsarAI only if they have legal capacity or the required consent of a legal representative.",
          ],
        },
        {
          title: "Service and AI Features",
          body: [
            "Mantly Cloud helps process recurring support tickets across connected channels. This may include customer and concern detection, response composition, evaluations, monitoring, configured actions, and tool calls.",
            "Mantly Cloud uses AI models and third-party providers to analyze, classify, summarize, prepare, or generate content. AI outputs may be inaccurate, incomplete, or unsuitable.",
            "Mantly Cloud does not replace legal, medical, financial, tax, security, or other professional advice.",
          ],
        },
        {
          title: "Review and Responsibility",
          body: [
            "Users remain responsible for inputs, configurations, approval policies, sent messages, executed actions, and use of AI outputs.",
            "Users must configure appropriate review and approval policies. Auto-send may be enabled only where the user determines it is appropriate after assessing the associated risks; Mantly Cloud does not bypass configured approval steps.",
            "Before approving sensitive results or enabling automated actions, users must check that content and actions are accurate, complete, lawful, and suitable for the relevant purpose. Special care is required where they may have legal, medical, financial, HR, insurance, security, or other significant effects.",
          ],
        },
        {
          title: "Data and Sensitive Content",
          body: [
            "Users are responsible for ensuring they may lawfully process support messages, attachments, personal data, trade secrets, and other content in Mantly Cloud.",
            "Special categories of personal data, health data, criminal data, identity documents, payment data, children's data, passwords, secrets, or similarly sensitive data may be processed only if the user is legally allowed to do so and Mantly has been configured appropriately.",
            "Users must follow their own review, deletion, retention, and approval processes.",
          ],
        },
        {
          title: "Acceptable Use",
          body: [
            "Mantly Cloud and other services operated by IsarAI may not be used for illegal content, spam, phishing, malware, credential theft, bypassing security measures, infringement of intellectual property rights, harassment, deceptive activity, or abusive automation.",
            "For Mantly Cloud, users must not overload systems, bypass limits, resell hosted access without an appropriate agreement, circumvent security checks, process third-party data without authorization, or use the service in a way that harms its availability, security, or integrity. Rights granted by the Community Edition open-source license remain unaffected.",
            "IsarAI may restrict or suspend hosted content, workspaces, or access where there is a reasonable suspicion of abuse, security risk, or violation of these terms. Rights granted by the Community Edition open-source license remain unaffected.",
          ],
        },
        {
          title: "Plans, Trials, Pricing, and Payment",
          body: [
            "Mantly Cloud may offer free plans, trials, paid subscriptions, and usage-based billing.",
            "Prices, included quotas, usage limits, renewal, cancellation, taxes, and additional fees are shown in checkout, admin billing, or an individual offer.",
            "Payments, invoices, customer portal, and subscription management may be handled through Stripe. Paid plans renew, where shown, until canceled.",
            "Free plans or trials may be limited, changed, or ended where legally permitted.",
          ],
        },
        {
          title: "Availability and Changes",
          body: [
            "IsarAI works to keep Mantly Cloud stable, but does not guarantee uninterrupted or error-free availability.",
            "Maintenance, security measures, provider issues, updates, or force majeure may cause limitations.",
            "IsarAI may change, add, or remove features of its hosted services where required for security, operations, product development, legal requirements, or technical reasons.",
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
            "Users keep their rights in their own content. For content submitted to Mantly Cloud, users grant IsarAI the rights needed to process that content for providing, securing, improving, and billing the hosted service.",
            "Copyrights, trademarks, designs, and components not released under an open-source license remain owned by IsarAI or the relevant rights holders.",
            "Community Edition source code may be used, studied, modified, and distributed under the GNU Affero General Public License version 3. These terms and any individual contracts additionally govern Mantly Cloud, trademarks, and proprietary components.",
          ],
        },
        {
          title: "Term and Termination",
          body: [
            "Users may cancel Mantly Cloud according to the subscribed plan and displayed cancellation options.",
            "Cancellation of paid subscriptions usually takes effect at the end of the current billing period unless checkout or a contract states otherwise.",
            "IsarAI may suspend or terminate hosted access for cause, especially in case of security risks, payment default, unlawful conduct, or material breach of these terms.",
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
            "Information on personal data processing by IsarAI is provided in the Mantly Privacy Policy.",
            "Where IsarAI processes personal data through Mantly Cloud on behalf of a customer, additional data processing terms may apply.",
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
            "IsarAI may update these terms if services operated by IsarAI, legal requirements, billing, or technical processes change.",
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
