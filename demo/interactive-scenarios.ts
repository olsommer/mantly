export type DemoLocale = "en" | "de";
export type DemoScenarioId = "insurance" | "telecom" | "notary" | "logistics";

export const DEFAULT_INTERACTIVE_DEMO_SCENARIO_ID: DemoScenarioId = "logistics";

export type DemoEmail = {
  id: string;
  fromAddress: string;
  subject: string;
  body: string;
  attachments: { filename: string; base64: string }[];
};

export type DemoResponse = {
  emailBody: string;
  emailAttachments: { filename: string; base64: string }[];
  requiresHuman: boolean;
  identityResult: {
    customerFound: boolean;
    data: Record<string, unknown>;
    toolCallsMade: string[];
  };
  intentResult: {
    matched: boolean;
    intentName: string;
    actions: Array<{
      name: string;
      label: string;
      type?: "dropdown" | "calendar" | "input" | "button";
      description?: string;
      options?: string[];
      separateCall?: boolean;
      method: string;
      initialValue?: string | null;
    }>;
    response: {
      enabled: boolean;
      auto: boolean;
    };
  };
  phishingResult?: {
    enabled: boolean;
    riskLevel: "none" | "low" | "medium" | "high";
    score: number;
    indicators: string[];
    reason: string;
    checkedAt: string;
  };
  promptInjectionResult?: {
    enabled: boolean;
    riskLevel: "none" | "low" | "medium" | "high";
    score: number;
    indicators: string[];
    reason: string;
    checkedAt: string;
  };
};

export type DemoScenario = {
  id: DemoScenarioId;
  label: string;
  eyebrow: string;
  description: string;
  email: DemoEmail;
  response: DemoResponse;
};

const checkedAt = "2026-05-18T09:00:00.000Z";

const scenarios: Record<DemoLocale, DemoScenario[]> = {
  en: [
    {
      id: "insurance",
      label: "Insurance",
      eyebrow: "Insurance certificate",
      description: "A customer asks for an updated certificate. Mantly prepares the reply, context, and attachment.",
      email: {
        id: "demo-insurance-confirmation",
        fromAddress: "anna.keller@example.com",
        subject: "Updated insurance certificate",
        body:
          "Hello,\n\nI need an updated insurance certificate for my business liability policy for my bank. Could you please send it to me?\n\nThank you and kind regards,\nAnna Keller",
        attachments: [],
      },
      response: {
        emailBody:
          "Hello Ms Keller,\n\nthank you for your message. We have prepared and attached the updated insurance certificate for your business liability policy.\n\nPlease check the details briefly. If your bank needs different wording, please let us know.\n\nKind regards,",
        emailAttachments: [
          { filename: "Insurance_Certificate_Keller_Business_Liability.pdf", base64: "" },
        ],
        requiresHuman: false,
        identityResult: {
          customerFound: true,
          data: {
            customer: "Anna Keller",
            policy: "Business liability",
            policy_number: "BH-2048-77",
            status: "Active",
          },
          toolCallsMade: ["customer_lookup", "policy_lookup"],
        },
        intentResult: {
          matched: true,
          intentName: "Insurance certificate",
          actions: [],
          response: {
            enabled: true,
            auto: true,
          },
        },
        phishingResult: {
          enabled: true,
          riskLevel: "none",
          score: 0,
          indicators: [],
          reason: "No suspicious sender, links, or patterns detected.",
          checkedAt,
        },
        promptInjectionResult: {
          enabled: true,
          riskLevel: "none",
          score: 0,
          indicators: [],
          reason: "No instructions detected that attempt to manipulate pipeline behavior.",
          checkedAt,
        },
      },
    },
    {
      id: "telecom",
      label: "Telecom Support",
      eyebrow: "Plan and outage request",
      description: "A support email is detected. Mantly prepares customer data, the next step, and the response.",
      email: {
        id: "demo-telecom-support",
        fromAddress: "markus.weber@example.com",
        subject: "Internet slow since yesterday",
        body:
          "Hello Support,\n\nsince yesterday evening my internet has been much slower. I work from home and need a quick solution. Can you check whether there is an outage or a plan issue?\n\nCustomer number: K-88421\n\nThanks,\nMarkus Weber",
        attachments: [],
      },
      response: {
        emailBody:
          "Hello Mr Weber,\n\nthank you for your message. We matched your customer number and prepared a line check for your connection.\n\nNo payment issue is currently visible. The next step is the technical line check. After approval, you will receive feedback with the result and recommended measures.\n\nKind regards,",
        emailAttachments: [],
        requiresHuman: false,
        identityResult: {
          customerFound: true,
          data: {
            customer: "Markus Weber",
            customer_number: "K-88421",
            product: "Fiber 500",
            contract_status: "Active",
          },
          toolCallsMade: ["customer_lookup", "contract_lookup", "outage_check"],
        },
        intentResult: {
          matched: true,
          intentName: "Support: slow internet",
          actions: [
            {
              name: "prepare_ticket",
              label: "Prepare ticket",
              type: "dropdown",
              options: ["Technical check", "Schedule callback", "Check plan"],
              separateCall: false,
              method: "POST",
              initialValue: "Technical check",
            },
          ],
          response: {
            enabled: true,
            auto: true,
          },
        },
        phishingResult: {
          enabled: true,
          riskLevel: "none",
          score: 0,
          indicators: [],
          reason: "No suspicious sender, links, or patterns detected.",
          checkedAt,
        },
        promptInjectionResult: {
          enabled: true,
          riskLevel: "none",
          score: 0,
          indicators: [],
          reason: "No manipulative instructions detected.",
          checkedAt,
        },
      },
    },
    {
      id: "notary",
      label: "Notary",
      eyebrow: "Document and appointment preparation",
      description: "A purchase-contract request is detected. Mantly identifies missing documents and prepares the reply.",
      email: {
        id: "demo-notary-purchase",
        fromAddress: "sophie.baumann@example.com",
        subject: "Documents for purchase contract draft",
        body:
          "Dear Sir or Madam,\n\nwe would like to have a purchase contract draft prepared for the apartment at Seestrasse 12. Which documents do you need from us, and when would an initial appointment be possible?\n\nKind regards,\nSophie Baumann",
        attachments: [],
      },
      response: {
        emailBody:
          "Dear Ms Baumann,\n\nthank you for your message. For the purchase contract draft, we first need the land-register details, information about buyer and seller, the purchase price, and any existing property documents.\n\nWe have prepared the next steps. Please review the list of required documents. Once the information has been received, an appointment to discuss the draft can be coordinated.\n\nKind regards,",
        emailAttachments: [
          { filename: "Purchase_Contract_Draft_Checklist.pdf", base64: "" },
        ],
        requiresHuman: false,
        identityResult: {
          customerFound: true,
          data: {
            client: "Sophie Baumann",
            matter: "Purchase contract draft",
            property: "Seestrasse 12",
            status: "New",
          },
          toolCallsMade: ["client_lookup", "matter_search"],
        },
        intentResult: {
          matched: true,
          intentName: "Prepare purchase contract draft",
          actions: [],
          response: {
            enabled: true,
            auto: true,
          },
        },
        phishingResult: {
          enabled: true,
          riskLevel: "none",
          score: 0,
          indicators: [],
          reason: "No suspicious sender, links, or patterns detected.",
          checkedAt,
        },
        promptInjectionResult: {
          enabled: true,
          riskLevel: "none",
          score: 0,
          indicators: [],
          reason: "No hidden or manipulative instructions detected.",
          checkedAt,
        },
      },
    },
    {
      id: "logistics",
      label: "Logistics",
      eyebrow: "Transport planning and dispatch",
      description: "A customer asks for a new transport plan. Mantly detects the customer, route, and constraints.",
      email: {
        id: "demo-logistics-plan-request",
        fromAddress: "maya.schneider@alpine-bikes.de",
        subject: "New transport plan for week 24",
        body:
          "Hello,\n\nwe need a new transport plan for next week for 18 pallets of spare parts from Hamburg to Munich. Pickup would ideally be Tuesday morning, and delivery must be completed by Thursday at 2:00 p.m.\n\nCan you check capacity and start the planning? Customer number is K-4821.\n\nBest regards,\nMaya Schneider",
        attachments: [],
      },
      response: {
        emailBody:
          "Hello Ms Schneider,\n\nthank you for your message. We identified Alpine Bikes GmbH as the customer and captured the key details for the new transport plan.\n\nCreation of the transport plan has been initiated. Route, volume, pickup window, and delivery deadline have been recorded; our dispatch team is checking capacity and will follow up shortly with the concrete planning details.\n\nKind regards,",
        emailAttachments: [],
        requiresHuman: false,
        identityResult: {
          customerFound: true,
          data: {
            customer: "Alpine Bikes GmbH",
            contact: "Maya Schneider",
            customer_number: "K-4821",
            route: "Hamburg -> Munich",
            volume: "18 pallets of spare parts",
            pickup_window: "Tuesday morning",
            delivery_deadline: "Thursday, 2:00 p.m.",
          },
          toolCallsMade: ["customer_lookup", "route_capacity_check", "planning_context"],
        },
        intentResult: {
          matched: true,
          intentName: "Create transport plan",
          actions: [
            {
              name: "create_transport_plan",
              label: "Create new plan",
              type: "button",
              description: "Create a dispatch transport plan with customer, route, volume, and requested windows.",
              separateCall: false,
              method: "POST",
            },
          ],
          response: {
            enabled: true,
            auto: true,
          },
        },
        phishingResult: {
          enabled: true,
          riskLevel: "none",
          score: 0,
          indicators: [],
          reason: "Known business contact, no suspicious links or patterns detected.",
          checkedAt,
        },
        promptInjectionResult: {
          enabled: true,
          riskLevel: "none",
          score: 0,
          indicators: [],
          reason: "No manipulative instructions detected.",
          checkedAt,
        },
      },
    },
  ],
  de: [
    {
      id: "insurance",
      label: "Versicherung",
      eyebrow: "Versicherungsbestätigung",
      description: "Kunde fragt nach einer aktuellen Bestätigung. Mantly bereitet Antwort, Kontext und Anlage vor.",
      email: {
        id: "demo-insurance-confirmation",
        fromAddress: "anna.keller@example.com",
        subject: "Bitte um aktuelle Versicherungsbestätigung",
        body:
          "Guten Tag\n\nich benötige für meine Bank eine aktuelle Versicherungsbestätigung zu meiner Betriebshaftpflicht. Können Sie mir diese bitte zusenden?\n\nVielen Dank und freundliche Grüße\nAnna Keller",
        attachments: [],
      },
      response: {
        emailBody:
          "Guten Tag Frau Keller,\n\nvielen Dank für Ihre Nachricht. Die aktuelle Versicherungsbestätigung zu Ihrer Betriebshaftpflicht haben wir vorbereitet und beigefügt.\n\nBitte prüfen Sie die Angaben kurz. Falls Ihre Bank eine abweichende Formulierung benötigt, geben Sie uns gerne Bescheid.\n\nFreundliche Grüße",
        emailAttachments: [
          { filename: "Versicherungsbestaetigung_Keller_Betriebshaftpflicht.pdf", base64: "" },
        ],
        requiresHuman: false,
        identityResult: {
          customerFound: true,
          data: {
            customer: "Anna Keller",
            policy: "Betriebshaftpflicht",
            policy_number: "BH-2048-77",
            status: "Aktiv",
          },
          toolCallsMade: ["customer_lookup", "policy_lookup"],
        },
        intentResult: {
          matched: true,
          intentName: "Versicherungsbestätigung",
          actions: [],
          response: {
            enabled: true,
            auto: true,
          },
        },
        phishingResult: {
          enabled: true,
          riskLevel: "none",
          score: 0,
          indicators: [],
          reason: "Keine verdächtigen Absender, Links oder Muster erkannt.",
          checkedAt,
        },
        promptInjectionResult: {
          enabled: true,
          riskLevel: "none",
          score: 0,
          indicators: [],
          reason: "Keine Anweisungen erkannt, die das Verhalten der Pipeline manipulieren sollen.",
          checkedAt,
        },
      },
    },
    {
      id: "telecom",
      label: "Telecom Support",
      eyebrow: "Tarif- und Störungsanfrage",
      description: "Support-Mail wird erkannt. Mantly bereitet Kundendaten, nächsten Schritt und Antwort vor.",
      email: {
        id: "demo-telecom-support",
        fromAddress: "markus.weber@example.com",
        subject: "Internet seit gestern langsam",
        body:
          "Hallo Support\n\nseit gestern Abend ist mein Internet deutlich langsamer. Ich arbeite im Homeoffice und brauche dringend eine Lösung. Könnt ihr prüfen, ob eine Störung oder ein Tarifproblem vorliegt?\n\nKundennummer: K-88421\n\nDanke\nMarkus Weber",
        attachments: [],
      },
      response: {
        emailBody:
          "Hallo Herr Weber,\n\nvielen Dank für Ihre Nachricht. Wir haben Ihre Kundennummer zugeordnet und eine Leitungsprüfung für Ihren Anschluss vorbereitet.\n\nAktuell ist kein Zahlungsthema sichtbar. Der nächste Schritt ist die technische Prüfung des Anschlusses. Sie erhalten nach Freigabe eine Rückmeldung mit dem Ergebnis und den empfohlenen Maßnahmen.\n\nFreundliche Grüße",
        emailAttachments: [],
        requiresHuman: false,
        identityResult: {
          customerFound: true,
          data: {
            customer: "Markus Weber",
            customer_number: "K-88421",
            product: "Fiber 500",
            contract_status: "Aktiv",
          },
          toolCallsMade: ["customer_lookup", "contract_lookup", "outage_check"],
        },
        intentResult: {
          matched: true,
          intentName: "Support: langsames Internet",
          actions: [
            {
              name: "prepare_ticket",
              label: "Ticket vorbereiten",
              type: "dropdown",
              options: ["Technische Prüfung", "Rückruf einplanen", "Tarif prüfen"],
              separateCall: false,
              method: "POST",
              initialValue: "Technische Prüfung",
            },
          ],
          response: {
            enabled: true,
            auto: true,
          },
        },
        phishingResult: {
          enabled: true,
          riskLevel: "none",
          score: 0,
          indicators: [],
          reason: "Keine verdächtigen Absender, Links oder Muster erkannt.",
          checkedAt,
        },
        promptInjectionResult: {
          enabled: true,
          riskLevel: "none",
          score: 0,
          indicators: [],
          reason: "Keine manipulativen Anweisungen erkannt.",
          checkedAt,
        },
      },
    },
    {
      id: "notary",
      label: "Notariat",
      eyebrow: "Dokumenten- und Terminvorbereitung",
      description: "Anfrage zum Kaufvertrag. Mantly erkennt fehlende Unterlagen und bereitet die Antwort vor.",
      email: {
        id: "demo-notary-purchase",
        fromAddress: "sophie.baumann@example.com",
        subject: "Unterlagen für Kaufvertragsentwurf",
        body:
          "Sehr geehrte Damen und Herren\n\nwir möchten einen Kaufvertragsentwurf für die Wohnung an der Seestrasse 12 vorbereiten lassen. Welche Unterlagen benötigen Sie von uns und wann wäre ein erster Termin möglich?\n\nFreundliche Grüße\nSophie Baumann",
        attachments: [],
      },
      response: {
        emailBody:
          "Sehr geehrte Frau Baumann,\n\nvielen Dank für Ihre Nachricht. Für den Kaufvertragsentwurf benötigen wir zunächst die Grundbuchdaten, Angaben zu Käufer und Verkäufer, den Kaufpreis sowie vorhandene Objektunterlagen.\n\nWir haben die nächsten Schritte vorbereitet. Bitte prüfen Sie die Liste der benötigten Unterlagen. Nach Eingang der Daten kann ein Termin für die Besprechung des Entwurfs abgestimmt werden.\n\nFreundliche Grüße",
        emailAttachments: [
          { filename: "Checkliste_Kaufvertragsentwurf.pdf", base64: "" },
        ],
        requiresHuman: false,
        identityResult: {
          customerFound: true,
          data: {
            client: "Sophie Baumann",
            matter: "Kaufvertragsentwurf",
            property: "Seestrasse 12",
            status: "Neu",
          },
          toolCallsMade: ["client_lookup", "matter_search"],
        },
        intentResult: {
          matched: true,
          intentName: "Kaufvertragsentwurf vorbereiten",
          actions: [],
          response: {
            enabled: true,
            auto: true,
          },
        },
        phishingResult: {
          enabled: true,
          riskLevel: "none",
          score: 0,
          indicators: [],
          reason: "Keine verdächtigen Absender, Links oder Muster erkannt.",
          checkedAt,
        },
        promptInjectionResult: {
          enabled: true,
          riskLevel: "none",
          score: 0,
          indicators: [],
          reason: "Keine versteckten oder manipulativen Anweisungen erkannt.",
          checkedAt,
        },
      },
    },
    {
      id: "logistics",
      label: "Logistik",
      eyebrow: "Transportplanung und Disposition",
      description: "Kunde bittet um einen neuen Transportplan. Mantly erkennt Kunde, Route und Vorgaben und bereitet die Plananlage vor.",
      email: {
        id: "demo-logistics-plan-request",
        fromAddress: "maya.schneider@alpine-bikes.de",
        subject: "Neuer Transportplan für KW 24",
        body:
          "Guten Tag\n\nwir brauchen für nächste Woche einen neuen Transportplan für 18 Paletten Ersatzteile von Hamburg nach München. Abholung wäre idealerweise Dienstagvormittag, die Anlieferung muss bis Donnerstag 14:00 Uhr erfolgen.\n\nKönnen Sie die Kapazität prüfen und die Planung starten? Kundennummer ist K-4821.\n\nViele Grüße\nMaya Schneider",
        attachments: [],
      },
      response: {
        emailBody:
          "Guten Tag Frau Schneider,\n\nvielen Dank für Ihre Nachricht. Wir haben Alpine Bikes GmbH als Kunden erkannt und die Eckdaten für den neuen Transportplan übernommen.\n\nDie Erstellung des Transportplans wurde initiiert. Route, Volumen, Abholfenster und Lieferfrist sind erfasst; unsere Disposition prüft die Kapazität und meldet sich in Kürze mit den konkreten Planungsdetails.\n\nFreundliche Grüße",
        emailAttachments: [],
        requiresHuman: false,
        identityResult: {
          customerFound: true,
          data: {
            customer: "Alpine Bikes GmbH",
            contact: "Maya Schneider",
            customer_number: "K-4821",
            route: "Hamburg -> München",
            volume: "18 Paletten Ersatzteile",
            pickup_window: "Dienstagvormittag",
            delivery_deadline: "Donnerstag, 14:00",
          },
          toolCallsMade: ["customer_lookup", "route_capacity_check", "planning_context"],
        },
        intentResult: {
          matched: true,
          intentName: "Transportplan erstellen",
          actions: [
            {
              name: "create_transport_plan",
              label: "Neuen Plan erstellen",
              type: "button",
              description: "Transportplan mit Kunde, Route, Volumen und Wunschfenstern in der Disposition anlegen.",
              separateCall: false,
              method: "POST",
            },
          ],
          response: {
            enabled: true,
            auto: true,
          },
        },
        phishingResult: {
          enabled: true,
          riskLevel: "none",
          score: 0,
          indicators: [],
          reason: "Bekannter Geschäftskontakt, keine verdächtigen Links oder Muster erkannt.",
          checkedAt,
        },
        promptInjectionResult: {
          enabled: true,
          riskLevel: "none",
          score: 0,
          indicators: [],
          reason: "Keine manipulativen Anweisungen erkannt.",
          checkedAt,
        },
      },
    },
  ],
};

export function getInteractiveDemoScenarios(locale: DemoLocale): DemoScenario[] {
  return scenarios[locale];
}

export function getInteractiveDemoScenario(locale: DemoLocale, id: string | null | undefined): DemoScenario {
  return scenarios[locale].find((scenario) => scenario.id === id)
    ?? scenarios[locale].find((scenario) => scenario.id === DEFAULT_INTERACTIVE_DEMO_SCENARIO_ID)
    ?? scenarios[locale][0];
}
