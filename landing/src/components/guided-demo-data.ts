import type { Language } from "@/i18n/translations"

export type GuidedDemoScenarioId = "logistics" | "ecommerce" | "legal"

export type GuidedDemoChannel = "email" | "web_chat"

export type GuidedDemoEvidenceKind = "knowledge" | "tool"

export interface GuidedDemoEvidence {
  kind: GuidedDemoEvidenceKind
  title: string
  detail: string
  status: string
}

export interface GuidedDemoAction {
  label: string
  detail: string
  status: string
  state: "pending" | "not_required"
}

export interface GuidedDemoConcern {
  id: string
  title: string
  question: string
  runbook: string
  evidence: GuidedDemoEvidence[]
  action: GuidedDemoAction
}

export interface GuidedDemoScenario {
  id: GuidedDemoScenarioId
  label: string
  eyebrow: string
  channel: GuidedDemoChannel
  channelLabel: string
  sender: string
  subject: string
  body: string
  ticketId: string
  concerns: GuidedDemoConcern[]
  obligationCount: number
  composerStatus: string
  response: string
}

export interface GuidedDemoCopy {
  launcher: string
  close: string
  simulationLabel: string
  title: string
  description: string
  customerTab: string
  agentTab: string
  chooseMessage: string
  chooseMessageHint: string
  from: string
  subject: string
  runReplay: string
  replay: string
  replayProgress: string
  replayReady: string
  replayReadyDetail: string
  simulationDisclosure: string
  detectedConcerns: string
  runbook: string
  customerQuestion: string
  evidenceAndActions: string
  knowledge: string
  tool: string
  action: string
  oneComposer: string
  composerDetail: string
  concernsCovered: string
  questionsCovered: string
  groundingPassed: string
  oneResponse: string
  stages: readonly [string, string, string, string, string]
  stageCurrent: string
  stageComplete: string
  stageWaiting: string
  scenarios: Record<GuidedDemoScenarioId, GuidedDemoScenario>
}

export const GUIDED_DEMO_SCENARIO_IDS: GuidedDemoScenarioId[] = [
  "logistics",
  "ecommerce",
  "legal",
]

export const guidedDemoCopy = {
  en: {
    launcher: "Demo",
    close: "Close guided simulation",
    simulationLabel: "Guided product simulation",
    title: "Watch Mantly handle one ticket",
    description:
      "Replay a predefined example. No live model, tool, ticket, or customer data is used.",
    customerTab: "Customer",
    agentTab: "Agent run",
    chooseMessage: "Choose a sample customer message",
    chooseMessageHint:
      "Choose the example. Mantly—not the visitor—detects its concerns.",
    from: "From",
    subject: "Subject",
    runReplay: "Run",
    replay: "Replay",
    replayProgress: "Guided replay progress",
    replayReady: "Ready to replay",
    replayReadyDetail:
      "Start the guided run to see one message become one ticket, multiple runbook outcomes, and one reply.",
    simulationDisclosure: "Prebuilt example · no tools run · no data sent",
    detectedConcerns: "Detected concerns",
    runbook: "Runbook",
    customerQuestion: "Customer asks",
    evidenceAndActions: "Evidence and action state",
    knowledge: "Knowledge",
    tool: "Tool evidence",
    action: "Action",
    oneComposer: "One Inbox composer",
    composerDetail:
      "The composer receives every runbook outcome and writes one evidence-grounded answer.",
    concernsCovered: "concerns covered",
    questionsCovered: "questions covered",
    groundingPassed: "Grounding check passed",
    oneResponse: "One customer response",
    stages: ["Inbound", "Concerns", "Evidence", "Composer", "Response"],
    stageCurrent: "Current",
    stageComplete: "Complete",
    stageWaiting: "Waiting",
    scenarios: {
      logistics: {
        id: "logistics",
        label: "Logistics",
        eyebrow: "Two requests in one email",
        channel: "email",
        channelLabel: "Email",
        sender: "maya@alpine-bikes.example",
        subject: "Replace duplicate booking and plan week 24",
        body:
          "Hello, booking BK-318 is a duplicate—please cancel it. We also need a new plan for 18 pallets from Hamburg to Munich, delivered by Thursday at 14:00. Can you confirm capacity and create the new plan?",
        ticketId: "TKT-24018",
        obligationCount: 3,
        composerStatus: "Ready for human approval",
        concerns: [
          {
            id: "C-01",
            title: "Cancel duplicate booking BK-318",
            question: "Can booking BK-318 be cancelled?",
            runbook: "Cancel transport booking",
            evidence: [
              {
                kind: "tool",
                title: "Booking lookup",
                detail: "BK-318 exists and is still cancellable.",
                status: "Successful lookup",
              },
              {
                kind: "knowledge",
                title: "Cancellation policy",
                detail: "Dispatch cancellations require approval before execution.",
                status: "Reviewed source",
              },
            ],
            action: {
              label: "Cancel BK-318",
              detail: "The cancellation has not run.",
              status: "Pending human approval",
              state: "pending",
            },
          },
          {
            id: "C-02",
            title: "Plan a new 18-pallet shipment",
            question: "Is capacity available, and can a new plan be created?",
            runbook: "Plan transport",
            evidence: [
              {
                kind: "tool",
                title: "Capacity lookup",
                detail: "18 pallet spaces are available for the requested window.",
                status: "Successful lookup",
              },
            ],
            action: {
              label: "Create transport plan",
              detail: "The plan has not been created.",
              status: "Pending human approval",
              state: "pending",
            },
          },
        ],
        response:
          "Hello Maya,\n\nWe verified that booking BK-318 exists and is still cancellable. Cancelling it remains pending human approval.\n\nWe also verified capacity for 18 pallets from Hamburg to Munich in the requested window. Creating the new transport plan remains pending human approval.\n\nKind regards,",
      },
      ecommerce: {
        id: "ecommerce",
        label: "E-commerce",
        eyebrow: "Product issue and return question",
        channel: "web_chat",
        channelLabel: "Web chat",
        sender: "Jordan Lee",
        subject: "Order #54192",
        body:
          "Order #54192 arrived today, but the smart lamp is cracked. Can I get a replacement, and what exactly do I need to include in the return parcel?",
        ticketId: "TKT-54192",
        obligationCount: 2,
        composerStatus: "Ready for human approval",
        concerns: [
          {
            id: "C-01",
            title: "Replace the damaged smart lamp",
            question: "Is a replacement available?",
            runbook: "Damaged item replacement",
            evidence: [
              {
                kind: "tool",
                title: "Order lookup",
                detail: "Order #54192 contains one smart lamp delivered today.",
                status: "Successful lookup",
              },
            ],
            action: {
              label: "Create replacement order",
              detail: "No replacement order has been created.",
              status: "Pending human approval",
              state: "pending",
            },
          },
          {
            id: "C-02",
            title: "Explain the return contents",
            question: "What must be included in the parcel?",
            runbook: "Damaged item return",
            evidence: [
              {
                kind: "knowledge",
                title: "Damaged-goods return checklist",
                detail: "Include the lamp, its power adapter, and the printed return slip.",
                status: "Reviewed source",
              },
            ],
            action: {
              label: "No operational action",
              detail: "The reviewed checklist answers this concern.",
              status: "Not required",
              state: "not_required",
            },
          },
        ],
        response:
          "Hello Jordan,\n\nWe verified that order #54192 contains one smart lamp delivered today. Creating a replacement order remains pending human approval.\n\nFor the return parcel, please include the lamp, its power adapter, and the printed return slip.\n\nKind regards,",
      },
      legal: {
        id: "legal",
        label: "Legal",
        eyebrow: "Matter closure and retention guidance",
        channel: "email",
        channelLabel: "Email",
        sender: "alex.morgan@northstar.example",
        subject: "Close matter M-1042 and confirm retention",
        body:
          "Please close matter M-1042. Before you do, can you confirm how long the signed documents and correspondence will be retained?",
        ticketId: "TKT-1042",
        obligationCount: 2,
        composerStatus: "Human review required",
        concerns: [
          {
            id: "C-01",
            title: "Close matter M-1042",
            question: "Can the matter be closed?",
            runbook: "Matter closure",
            evidence: [
              {
                kind: "tool",
                title: "Matter lookup",
                detail: "M-1042 is open and has no outstanding client balance.",
                status: "Successful lookup",
              },
            ],
            action: {
              label: "Close matter M-1042",
              detail: "The matter remains open.",
              status: "Pending lawyer approval",
              state: "pending",
            },
          },
          {
            id: "C-02",
            title: "Confirm document retention",
            question: "How long are the file materials retained?",
            runbook: "File retention guidance",
            evidence: [
              {
                kind: "knowledge",
                title: "Client-file retention policy",
                detail: "Signed documents: 10 years. General correspondence: 7 years.",
                status: "Reviewed source",
              },
            ],
            action: {
              label: "No operational action",
              detail: "The reviewed policy answers this concern.",
              status: "Not required",
              state: "not_required",
            },
          },
        ],
        response:
          "Hello Alex,\n\nWe verified that matter M-1042 is open with no outstanding client balance. Closing it remains pending lawyer approval.\n\nUnder the reviewed retention policy, signed documents are retained for 10 years and general correspondence for 7 years.\n\nKind regards,",
      },
    },
  },
  de: {
    launcher: "Demo",
    close: "Geführte Simulation schließen",
    simulationLabel: "Geführte Produktsimulation",
    title: "So bearbeitet Mantly ein Ticket",
    description:
      "Spielen Sie ein vorbereitetes Beispiel ab. Es werden kein Live-Modell, keine Tools, keine Tickets und keine Kundendaten verwendet.",
    customerTab: "Kunde",
    agentTab: "Agent-Run",
    chooseMessage: "Beispielnachricht auswählen",
    chooseMessageHint:
      "Wählen Sie das Beispiel. Mantly – nicht der Besucher – erkennt die Anliegen.",
    from: "Von",
    subject: "Betreff",
    runReplay: "Start",
    replay: "Nochmal",
    replayProgress: "Fortschritt der geführten Simulation",
    replayReady: "Bereit zur Wiedergabe",
    replayReadyDetail:
      "Starten Sie den Ablauf und sehen Sie, wie aus einer Nachricht ein Ticket, mehrere Runbook-Ergebnisse und eine Antwort werden.",
    simulationDisclosure: "Vorbereitetes Beispiel · keine Tools · keine Datenübertragung",
    detectedConcerns: "Erkannte Anliegen",
    runbook: "Runbook",
    customerQuestion: "Kundenfrage",
    evidenceAndActions: "Nachweise und Aktionsstatus",
    knowledge: "Wissen",
    tool: "Tool-Nachweis",
    action: "Aktion",
    oneComposer: "Ein Inbox Composer",
    composerDetail:
      "Der Composer erhält jedes Runbook-Ergebnis und verfasst eine einzige fundierte Antwort.",
    concernsCovered: "Anliegen abgedeckt",
    questionsCovered: "Fragen abgedeckt",
    groundingPassed: "Faktenprüfung bestanden",
    oneResponse: "Eine Kundenantwort",
    stages: ["Eingang", "Anliegen", "Nachweise", "Composer", "Antwort"],
    stageCurrent: "Aktuell",
    stageComplete: "Fertig",
    stageWaiting: "Ausstehend",
    scenarios: {
      logistics: {
        id: "logistics",
        label: "Logistik",
        eyebrow: "Zwei Anfragen in einer E-Mail",
        channel: "email",
        channelLabel: "E-Mail",
        sender: "maya@alpine-bikes.example",
        subject: "Doppelbuchung ersetzen und Woche 24 planen",
        body:
          "Hallo, die Buchung BK-318 ist doppelt – bitte stornieren. Zusätzlich brauchen wir einen neuen Plan für 18 Paletten von Hamburg nach München mit Lieferung bis Donnerstag um 14:00 Uhr. Können Sie die Kapazität bestätigen und den neuen Plan erstellen?",
        ticketId: "TKT-24018",
        obligationCount: 3,
        composerStatus: "Bereit zur menschlichen Freigabe",
        concerns: [
          {
            id: "C-01",
            title: "Doppelbuchung BK-318 stornieren",
            question: "Kann die Buchung BK-318 storniert werden?",
            runbook: "Transportbuchung stornieren",
            evidence: [
              {
                kind: "tool",
                title: "Buchungsabfrage",
                detail: "BK-318 existiert und kann noch storniert werden.",
                status: "Abfrage erfolgreich",
              },
              {
                kind: "knowledge",
                title: "Stornierungsrichtlinie",
                detail: "Stornierungen nach Disposition benötigen vor der Ausführung eine Freigabe.",
                status: "Geprüfte Quelle",
              },
            ],
            action: {
              label: "BK-318 stornieren",
              detail: "Die Stornierung wurde nicht ausgeführt.",
              status: "Menschliche Freigabe ausstehend",
              state: "pending",
            },
          },
          {
            id: "C-02",
            title: "Neue Sendung mit 18 Paletten planen",
            question: "Ist Kapazität verfügbar und kann ein neuer Plan erstellt werden?",
            runbook: "Transport planen",
            evidence: [
              {
                kind: "tool",
                title: "Kapazitätsabfrage",
                detail: "Für das angefragte Zeitfenster sind 18 Palettenplätze verfügbar.",
                status: "Abfrage erfolgreich",
              },
            ],
            action: {
              label: "Transportplan erstellen",
              detail: "Der Plan wurde nicht erstellt.",
              status: "Menschliche Freigabe ausstehend",
              state: "pending",
            },
          },
        ],
        response:
          "Hallo Maya,\n\nwir haben bestätigt, dass die Buchung BK-318 existiert und noch storniert werden kann. Die Stornierung wartet auf menschliche Freigabe.\n\nAußerdem haben wir die Kapazität für 18 Paletten von Hamburg nach München im gewünschten Zeitfenster bestätigt. Die Erstellung des neuen Transportplans wartet ebenfalls auf menschliche Freigabe.\n\nFreundliche Grüße",
      },
      ecommerce: {
        id: "ecommerce",
        label: "E-Commerce",
        eyebrow: "Produktschaden und Rücksendefrage",
        channel: "web_chat",
        channelLabel: "Webchat",
        sender: "Jordan Lee",
        subject: "Bestellung #54192",
        body:
          "Die Bestellung #54192 ist heute angekommen, aber die Smart-Lampe ist gesprungen. Kann ich Ersatz bekommen und was muss genau ins Rücksendepaket?",
        ticketId: "TKT-54192",
        obligationCount: 2,
        composerStatus: "Bereit zur menschlichen Freigabe",
        concerns: [
          {
            id: "C-01",
            title: "Beschädigte Smart-Lampe ersetzen",
            question: "Ist ein Ersatz verfügbar?",
            runbook: "Ersatz für beschädigten Artikel",
            evidence: [
              {
                kind: "tool",
                title: "Bestellabfrage",
                detail: "Bestellung #54192 enthält eine heute gelieferte Smart-Lampe.",
                status: "Abfrage erfolgreich",
              },
            ],
            action: {
              label: "Ersatzbestellung erstellen",
              detail: "Es wurde keine Ersatzbestellung erstellt.",
              status: "Menschliche Freigabe ausstehend",
              state: "pending",
            },
          },
          {
            id: "C-02",
            title: "Inhalt der Rücksendung erklären",
            question: "Was muss ins Paket?",
            runbook: "Rücksendung beschädigter Artikel",
            evidence: [
              {
                kind: "knowledge",
                title: "Checkliste für beschädigte Ware",
                detail: "Lampe, Netzteil und gedruckten Rücksendeschein beilegen.",
                status: "Geprüfte Quelle",
              },
            ],
            action: {
              label: "Keine operative Aktion",
              detail: "Die geprüfte Checkliste beantwortet dieses Anliegen.",
              status: "Nicht erforderlich",
              state: "not_required",
            },
          },
        ],
        response:
          "Hallo Jordan,\n\nwir haben bestätigt, dass Bestellung #54192 eine heute gelieferte Smart-Lampe enthält. Die Erstellung einer Ersatzbestellung wartet auf menschliche Freigabe.\n\nBitte legen Sie für die Rücksendung die Lampe, das Netzteil und den gedruckten Rücksendeschein ins Paket.\n\nFreundliche Grüße",
      },
      legal: {
        id: "legal",
        label: "Recht",
        eyebrow: "Mandatsabschluss und Aufbewahrung",
        channel: "email",
        channelLabel: "E-Mail",
        sender: "alex.morgan@northstar.example",
        subject: "Akte M-1042 schließen und Aufbewahrung bestätigen",
        body:
          "Bitte schließen Sie die Akte M-1042. Können Sie vorher bestätigen, wie lange die unterzeichneten Dokumente und die Korrespondenz aufbewahrt werden?",
        ticketId: "TKT-1042",
        obligationCount: 2,
        composerStatus: "Anwaltliche Prüfung erforderlich",
        concerns: [
          {
            id: "C-01",
            title: "Akte M-1042 schließen",
            question: "Kann die Akte geschlossen werden?",
            runbook: "Mandatsabschluss",
            evidence: [
              {
                kind: "tool",
                title: "Aktenabfrage",
                detail: "M-1042 ist offen und weist keinen ausstehenden Mandantensaldo auf.",
                status: "Abfrage erfolgreich",
              },
            ],
            action: {
              label: "Akte M-1042 schließen",
              detail: "Die Akte bleibt offen.",
              status: "Anwaltliche Freigabe ausstehend",
              state: "pending",
            },
          },
          {
            id: "C-02",
            title: "Dokumentenaufbewahrung bestätigen",
            question: "Wie lange werden die Akteninhalte aufbewahrt?",
            runbook: "Hinweise zur Aktenaufbewahrung",
            evidence: [
              {
                kind: "knowledge",
                title: "Richtlinie zur Aktenaufbewahrung",
                detail: "Unterzeichnete Dokumente: 10 Jahre. Allgemeine Korrespondenz: 7 Jahre.",
                status: "Geprüfte Quelle",
              },
            ],
            action: {
              label: "Keine operative Aktion",
              detail: "Die geprüfte Richtlinie beantwortet dieses Anliegen.",
              status: "Nicht erforderlich",
              state: "not_required",
            },
          },
        ],
        response:
          "Hallo Alex,\n\nwir haben bestätigt, dass die Akte M-1042 offen ist und keinen ausstehenden Mandantensaldo aufweist. Der Abschluss der Akte wartet auf anwaltliche Freigabe.\n\nGemäß der geprüften Aufbewahrungsrichtlinie werden unterzeichnete Dokumente 10 Jahre und allgemeine Korrespondenz 7 Jahre aufbewahrt.\n\nFreundliche Grüße",
      },
    },
  },
} satisfies Record<Language, GuidedDemoCopy>
