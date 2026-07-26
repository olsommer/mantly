import {
  CheckCircle2,
  ClipboardCheck,
  MailCheck,
  Settings2,
  ShieldAlert,
  Timer,
  UserCheck,
  XCircle,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { useTranslation } from "@/i18n/useTranslation";

const content = {
  en: {
    eyebrow: "Managed pilot",
    title: "Mantly Pilot Playbook",
    subtitle:
      "A focused operating plan for proving one agentic support workflow before rolling Mantly out wider.",
    intro:
      "The pilot is for teams with recurring client, support, insurance, legal, or back-office requests across their connected channels. It launches one controlled workflow with explicit runbooks, evaluation cases, and weekly tuning.",
    bestFitTitle: "Best-fit workflow",
    bestFitIntro:
      "The first workflow should be narrow, repeated, and valuable enough that faster preparation matters.",
    goodFits: [
      "Classify inbound client requests before a specialist answers.",
      "Prepare standard replies with the right case, CRM, policy, or document context.",
      "Attach recurring documents such as certificates, forms, or confirmations.",
      "Create a clean human handoff when the case needs expert review.",
      "Test concern recognition, runbooks, response copy, and actions against real example messages.",
    ],
    poorFitsTitle: "Poor fits",
    poorFits: [
      "Automatic sending before policies and evaluation cases are defined.",
      "Legal, regulated, payment, or contractual final decisions.",
      "High-volume consumer support without an accountable owner.",
      "Workflows that require hiding AI usage from staff or customers.",
      "Irreversible actions without a review step.",
    ],
    deliverablesTitle: "Pilot deliverables",
    deliverables: [
      { title: "One scoped project", desc: "A single project with one support workflow and clear owner." },
      { title: "Identity source", desc: "Customer, case, policy, or account lookup wired into the pipeline." },
      { title: "3-5 concerns", desc: "The first concern types, each with a matching runbook and expected outcome." },
      { title: "Governed response", desc: "One grounded reply prepared in the Inbox for approval or policy-based delivery." },
      { title: "Evaluation set", desc: "Representative messages with expected concerns, responses, and action outcomes." },
      { title: "Weekly tuning", desc: "Corrections from real usage converted into prompt, rule, or evaluation updates." },
    ],
    proofTitle: "What month one should prove",
    proof: [
      "Less manual triage before a human decides.",
      "Faster response preparation for the chosen workflow.",
      "Fewer missing details in the handoff.",
      "Clear escalation rules for sensitive or complex cases.",
      "Enough measurable value to add the next workflow.",
    ],
    exampleTitle: "Example workflow: omnichannel document request",
    triggerTitle: "Trigger",
    trigger:
      "A customer sends a message asking for a certificate, policy document, contract confirmation, or recurring case update.",
    goalTitle: "Mantly goal",
    goal:
      "Identify the sender and detected concerns, run the matching procedures, collect trusted context, execute permitted actions, and prepare one grounded response.",
    questionsTitle: "Questions Mantly can surface",
    questions: [
      "Which customer, policy, matter, or account does this message belong to?",
      "Which document or confirmation is requested?",
      "Is any required detail missing before a reply can be prepared?",
      "Does the request require legal, payment, security, or expert review?",
      "Which next human action is safest?",
    ],
    escalationTitle: "Escalation criteria",
    escalation: [
      "Legal, compliance, payment, contract, or refund commitments.",
      "Security risks, phishing, prompt injection, secrets, or production access.",
      "Customer frustration, complaint handling, or reputational risk.",
      "Ambiguous identity, unclear intent, or conflicting source data.",
      "Anything that would send, update, or commit data without approval.",
    ],
    handoffTitle: "Handoff summary",
    handoff: [
      "Customer: <name / account / policy / matter>",
      "Fit: routine | review needed | blocked",
      "Concern: <one-sentence request>",
      "Context collected: <facts from source systems>",
      "Missing: <details still needed>",
      "Risk: <legal/security/payment/customer note, if any>",
      "Recommended next human action: <send, edit, ask, escalate, or reject>",
    ],
    rulesTitle: "Operator rules",
    doTitle: "Do",
    doRules: [
      "Prepare facts and drafts, not final commitments.",
      "Keep response copy professional, concise, and source-grounded.",
      "Show what context was used and what is missing.",
      "Escalate sensitive cases early.",
      "Keep a human owner in control wherever policy requires approval.",
    ],
    dontTitle: "Do not",
    dontRules: [
      "Promise legal, compliance, payment, or contract outcomes.",
      "Request secrets, passwords, private keys, or production credentials.",
      "Pretend to be a human.",
      "Send or trigger irreversible actions outside the configured policy.",
      "Guess when source data is missing or contradictory.",
    ],
    demoTitle: "Demo script",
    demo: [
      "Upload or select a representative customer message in Preview & Publish.",
      "Mantly identifies the sender, detected concerns, and the matching runbooks.",
      "The configured tools collect customer or case context.",
      "Mantly executes permitted actions and prepares one grounded response.",
      "The result is approved or delivered according to policy, with feedback captured in the Inbox.",
      "The same message becomes part of the evaluation set before going live.",
    ],
    expansionTitle: "Expansion after the pilot",
    expansion: [
      "Add more concerns and higher-volume workflows.",
      "Connect more source systems and actions.",
      "Move from preview to a production channel rollout.",
      "Add roles, approval controls, self-hosting, or dedicated deployment if needed.",
      "Define monitoring, retention, and response-time targets.",
    ],
  },
  de: {
    eyebrow: "Managed Pilot",
    title: "Mantly Pilot Playbook",
    subtitle:
      "Ein fokussierter Betriebsplan, um einen agentischen Support-Workflow zu beweisen, bevor Mantly breiter ausgerollt wird.",
    intro:
      "Der Pilot ist für Teams mit wiederkehrenden Kunden-, Support-, Versicherungs-, Kanzlei- oder Backoffice-Anliegen aus ihren verbundenen Kanälen. Er bringt einen kontrollierten Workflow mit eindeutigen Runbooks, Evaluationen und wöchentlicher Feinjustierung live.",
    bestFitTitle: "Geeigneter Workflow",
    bestFitIntro:
      "Der erste Workflow sollte eng gefasst, wiederkehrend und wertvoll genug sein, dass schnellere Vorbereitung spürbar hilft.",
    goodFits: [
      "Eingehende Kundenanfragen klassifizieren, bevor Fachpersonen antworten.",
      "Standardantworten mit passendem Kunden-, Akten-, Vertrags- oder Dokumentenkontext vorbereiten.",
      "Wiederkehrende Dokumente wie Bestätigungen, Formulare oder Nachweise anhängen.",
      "Eine klare Übergabe erstellen, wenn ein Anliegen fachliche Prüfung braucht.",
      "Anliegenerkennung, Runbooks, Antworttext und Aktionen mit echten Beispielnachrichten testen.",
    ],
    poorFitsTitle: "Nicht geeignet",
    poorFits: [
      "Automatisches Versenden, bevor Richtlinien und Evaluationsfälle definiert sind.",
      "Juristische, regulierte, zahlungsbezogene oder vertragliche Endentscheidungen.",
      "Hochvolumiger Endkundensupport ohne klare Verantwortung.",
      "Workflows, bei denen KI-Nutzung vor Mitarbeitenden oder Kunden versteckt werden soll.",
      "Irreversible Aktionen ohne Prüfschritt.",
    ],
    deliverablesTitle: "Pilot-Ergebnisse",
    deliverables: [
      { title: "Ein fokussiertes Projekt", desc: "Ein Projekt mit einem Support-Workflow und klarer Verantwortung." },
      { title: "Identitätsquelle", desc: "Kunden-, Akten-, Vertrags- oder Account-Lookup in der Pipeline." },
      { title: "3-5 Anliegen", desc: "Die ersten Anliegen-Typen mit passendem Runbook und erwartetem Ergebnis." },
      { title: "Kontrollierte Antwort", desc: "Eine fundierte Antwort wird im Posteingang zur Freigabe oder richtlinienbasierten Zustellung vorbereitet." },
      { title: "Evaluationsset", desc: "Repräsentative Nachrichten mit erwarteten Anliegen, Antworten und Aktionsergebnissen." },
      { title: "Wöchentliche Feinjustierung", desc: "Korrekturen aus der Nutzung werden in Prompts, Regeln oder Evaluationen übertragen." },
    ],
    proofTitle: "Was Monat eins beweisen soll",
    proof: [
      "Weniger manuelle Vorarbeit, bevor ein Mensch entscheidet.",
      "Schnellere Antwortvorbereitung für den gewählten Workflow.",
      "Weniger fehlende Details in der Übergabe.",
      "Klare Eskalationsregeln für sensible oder komplexe Anliegen.",
      "Genug messbarer Wert, um den nächsten Workflow aufzunehmen.",
    ],
    exampleTitle: "Beispiel-Workflow: Omnichannel-Dokumentenanfrage",
    triggerTitle: "Auslöser",
    trigger:
      "Ein Kunde sendet eine Nachricht und fragt nach einer Bestätigung, einem Vertragsdokument, einer Versicherungsinformation oder einem wiederkehrenden Vorgangsupdate.",
    goalTitle: "Ziel von Mantly",
    goal:
      "Absender und erkannte Anliegen zuordnen, passende Runbooks ausführen, verlässlichen Kontext holen, erlaubte Aktionen ausführen und eine fundierte Antwort vorbereiten.",
    questionsTitle: "Fragen, die Mantly sichtbar machen kann",
    questions: [
      "Zu welchem Kunden, Vertrag, Vorgang oder Account gehört diese Nachricht?",
      "Welches Dokument oder welche Bestätigung wird angefragt?",
      "Fehlt ein Pflichtdetail, bevor eine Antwort vorbereitet werden kann?",
      "Braucht das Anliegen rechtliche, zahlungsbezogene, sicherheitsrelevante oder fachliche Prüfung?",
      "Welche nächste menschliche Aktion ist am sichersten?",
    ],
    escalationTitle: "Eskalationskriterien",
    escalation: [
      "Rechtliche, Compliance-, Zahlungs-, Vertrags- oder Rückerstattungszusagen.",
      "Sicherheitsrisiken, Phishing, Prompt Injection, Secrets oder Produktionszugänge.",
      "Kundenfrust, Beschwerden oder Reputationsrisiko.",
      "Unklare Identität, unklares Anliegen oder widersprüchliche Quelldaten.",
      "Alles, was ohne Freigabe Daten sendet, ändert oder verbindlich macht.",
    ],
    handoffTitle: "Übergabeformat",
    handoff: [
      "Kunde: <Name / Account / Vertrag / Vorgang>",
      "Fit: Routine | Prüfung nötig | blockiert",
      "Anliegen: <Anfrage in einem Satz>",
      "Kontext gesammelt: <Fakten aus Quellsystemen>",
      "Fehlend: <noch benötigte Details>",
      "Risiko: <Recht/Sicherheit/Zahlung/Kundennotiz, falls relevant>",
      "Empfohlene nächste menschliche Aktion: <senden, anpassen, nachfragen, eskalieren oder ablehnen>",
    ],
    rulesTitle: "Operator-Regeln",
    doTitle: "Tun",
    doRules: [
      "Fakten und Entwürfe vorbereiten, keine finalen Zusagen machen.",
      "Antworttexte professionell, knapp und quellenbasiert halten.",
      "Zeigen, welcher Kontext genutzt wurde und was fehlt.",
      "Sensible Fälle früh eskalieren.",
      "Verantwortliche Personen überall einbinden, wo die Richtlinie eine Freigabe verlangt.",
    ],
    dontTitle: "Nicht tun",
    dontRules: [
      "Juristische, Compliance-, Zahlungs- oder Vertragsausgänge versprechen.",
      "Secrets, Passwörter, private Keys oder Produktionszugänge anfragen.",
      "So tun, als wäre die KI ein Mensch.",
      "Außerhalb der konfigurierten Richtlinie senden oder irreversible Aktionen starten.",
      "Raten, wenn Quelldaten fehlen oder widersprüchlich sind.",
    ],
    demoTitle: "Demo-Skript",
    demo: [
      "Eine repräsentative Kundennachricht in Vorschau & Veröffentlichung auswählen oder hochladen.",
      "Mantly erkennt Absender, erkannte Anliegen und die passenden Runbooks.",
      "Konfigurierte Tools holen Kunden- oder Vorgangskontext.",
      "Mantly führt erlaubte Aktionen aus und bereitet eine fundierte Antwort vor.",
      "Das Ergebnis wird gemäß Richtlinie freigegeben oder zugestellt; Feedback bleibt im Posteingang.",
      "Die gleiche Nachricht wird Teil des Evaluationssets, bevor live geschaltet wird.",
    ],
    expansionTitle: "Ausbau nach dem Pilot",
    expansion: [
      "Weitere Anliegen und volumenstärkere Workflows ergänzen.",
      "Mehr Quellsysteme und Aktionen anbinden.",
      "Von der Vorschau in den produktiven Kanal-Rollout wechseln.",
      "Rollen, Freigabekontrollen, Self-Hosting oder dediziertes Deployment ergänzen, falls nötig.",
      "Ziele für Monitoring, Aufbewahrung und Antwortzeiten definieren.",
    ],
  },
};

function BulletList({ items, tone = "neutral" }: { items: string[]; tone?: "neutral" | "good" | "bad" }) {
  const Icon = tone === "bad" ? XCircle : CheckCircle2;
  const iconClass = tone === "bad" ? "text-red-500" : tone === "good" ? "text-emerald-600" : "text-primary";

  return (
    <ul className="space-y-3">
      {items.map((item) => (
        <li key={item} className="flex gap-3 text-base leading-relaxed text-muted-foreground">
          <Icon className={`mt-1 size-4 shrink-0 ${iconClass}`} />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function SectionHeading({ eyebrow, title }: { eyebrow?: string; title: string }) {
  return (
    <div className="mb-8 max-w-2xl">
      {eyebrow ? (
        <p className="mb-2 text-sm font-medium uppercase tracking-[0.18em] text-primary">
          {eyebrow}
        </p>
      ) : null}
      <h2 className="font-heading text-3xl font-normal text-foreground sm:text-4xl">
        {title}
      </h2>
    </div>
  );
}

export function PilotPlaybookPage() {
  const { lang } = useTranslation();
  const copy = content[lang];
  const mockStatus = lang === "de" ? "Menschliche Prüfung" : "Human review";
  const mockTitle = lang === "de" ? "Dokumentenanfrage" : "Document request";
  const mockRows = lang === "de"
    ? [
      ["Identität", "Kunde gefunden"],
      ["Anliegen", "Dokumentenanfrage"],
      ["Kontext", "Vertrag und Bestätigung bereit"],
      ["Antwort", "Entwurf vorbereitet"],
    ]
    : [
      ["Identity", "Customer found"],
      ["Concern", "Policy document request"],
      ["Context", "Policy and certificate ready"],
      ["Response", "Draft prepared"],
    ];

  return (
    <main>
      <section className="border-b bg-white pt-32 pb-16 sm:pt-36 sm:pb-20">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 sm:px-6 lg:grid-cols-[1.05fr_0.95fr] lg:px-8">
          <div className="max-w-3xl">
            <p className="mb-4 text-sm font-medium uppercase tracking-[0.18em] text-primary">
              {copy.eyebrow}
            </p>
            <h1 className="font-heading text-5xl font-normal text-foreground sm:text-6xl">
              {copy.title}
            </h1>
            <p className="mt-6 text-xl leading-relaxed text-muted-foreground">
              {copy.subtitle}
            </p>
            <p className="mt-5 max-w-2xl text-base leading-relaxed text-muted-foreground">
              {copy.intro}
            </p>
          </div>

          <div className="rounded-lg border bg-muted/20 p-5">
            <div className="rounded-md border bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between border-b pb-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Omnichannel Inbox</p>
                  <p className="mt-1 text-sm font-medium">{mockTitle}</p>
                </div>
                <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
                  {mockStatus}
                </span>
              </div>
              <div className="mt-4 space-y-3">
                {mockRows.map(([label, value]) => (
                  <div key={label} className="flex items-center justify-between gap-3 rounded-md border bg-background px-3 py-2">
                    <span className="text-xs text-muted-foreground">{label}</span>
                    <span className="truncate text-sm font-medium">{value}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="border-b bg-background py-16">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <SectionHeading title={copy.bestFitTitle} />
          <div className="grid gap-6 lg:grid-cols-2">
            <div>
              <p className="mb-6 text-base leading-relaxed text-muted-foreground">
                {copy.bestFitIntro}
              </p>
              <BulletList items={copy.goodFits} tone="good" />
            </div>
            <div>
              <h3 className="mb-6 text-lg font-semibold">{copy.poorFitsTitle}</h3>
              <BulletList items={copy.poorFits} tone="bad" />
            </div>
          </div>
        </div>
      </section>

      <section className="border-b bg-white py-16">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <SectionHeading title={copy.deliverablesTitle} />
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {copy.deliverables.map((item, index) => {
              const icons = [Settings2, UserCheck, ClipboardCheck, MailCheck, CheckCircle2, Timer];
              const Icon = icons[index] ?? CheckCircle2;
              return (
                <Card key={item.title} className="rounded-lg shadow-none">
                  <CardHeader>
                    <Icon className="mb-3 size-5 text-primary" />
                    <CardTitle className="text-lg">{item.title}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-base leading-relaxed text-muted-foreground">{item.desc}</p>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </div>
      </section>

      <section className="border-b bg-muted/20 py-16">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 sm:px-6 lg:grid-cols-[0.8fr_1.2fr] lg:px-8">
          <div>
            <SectionHeading title={copy.proofTitle} />
            <BulletList items={copy.proof} />
          </div>
          <div className="rounded-lg border bg-white p-6">
            <h2 className="font-heading text-3xl font-normal">{copy.exampleTitle}</h2>
            <Separator className="my-6" />
            <div className="grid gap-6 sm:grid-cols-2">
              <div>
                <h3 className="mb-2 text-sm font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                  {copy.triggerTitle}
                </h3>
                <p className="text-base leading-relaxed text-muted-foreground">{copy.trigger}</p>
              </div>
              <div>
                <h3 className="mb-2 text-sm font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                  {copy.goalTitle}
                </h3>
                <p className="text-base leading-relaxed text-muted-foreground">{copy.goal}</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="border-b bg-background py-16">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 sm:px-6 lg:grid-cols-2 lg:px-8">
          <div>
            <SectionHeading title={copy.questionsTitle} />
            <BulletList items={copy.questions} />
          </div>
          <div>
            <SectionHeading title={copy.escalationTitle} />
            <BulletList items={copy.escalation} tone="bad" />
          </div>
        </div>
      </section>

      <section className="border-b bg-white py-16">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <SectionHeading title={copy.handoffTitle} />
          <div className="rounded-lg border bg-muted/20 p-4 sm:p-6">
            <pre className="overflow-x-auto whitespace-pre-wrap text-sm leading-relaxed text-foreground">
              {copy.handoff.join("\n")}
            </pre>
          </div>
        </div>
      </section>

      <section className="border-b bg-background py-16">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 sm:px-6 lg:grid-cols-2 lg:px-8">
          <div>
            <SectionHeading title={`${copy.rulesTitle}: ${copy.doTitle}`} />
            <BulletList items={copy.doRules} tone="good" />
          </div>
          <div>
            <SectionHeading title={`${copy.rulesTitle}: ${copy.dontTitle}`} />
            <BulletList items={copy.dontRules} tone="bad" />
          </div>
        </div>
      </section>

      <section className="bg-muted/20 py-16">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 sm:px-6 lg:grid-cols-2 lg:px-8">
          <div>
            <SectionHeading title={copy.demoTitle} />
            <ol className="space-y-3">
              {copy.demo.map((item, index) => (
                <li key={item} className="flex gap-3 text-base leading-relaxed text-muted-foreground">
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-full border bg-white text-sm font-medium text-foreground">
                    {index + 1}
                  </span>
                  <span className="pt-0.5">{item}</span>
                </li>
              ))}
            </ol>
          </div>
          <div>
            <SectionHeading title={copy.expansionTitle} />
            <BulletList items={copy.expansion} />
            <div className="mt-8 flex items-start gap-3 rounded-lg border bg-white p-4">
              <ShieldAlert className="mt-0.5 size-5 shrink-0 text-primary" />
              <p className="text-base leading-relaxed text-muted-foreground">
                {lang === "de"
                  ? "Der Pilot bleibt absichtlich eng. Erst wenn der erste Workflow messbar funktioniert, wird erweitert."
                  : "The pilot stays intentionally narrow. Expansion starts only after the first workflow proves measurable value."}
              </p>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
