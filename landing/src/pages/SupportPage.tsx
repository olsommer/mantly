import { useTranslation } from "@/i18n/useTranslation";

type SupportSection = {
  title: string;
  body: string[];
};

type SupportContent = {
  title: string;
  intro: string;
  emailLabel: string;
  emailHref: string;
  sections: SupportSection[];
};

const content: Record<"de" | "en", SupportContent> = {
  de: {
    title: "Mantly Support",
    intro:
      "Bei Fragen, technischen Problemen oder Abrechnungsanliegen zu Mantly hilft der Support weiter.",
    emailLabel: "support@mantly.io",
    emailHref: "mailto:support@mantly.io",
    sections: [
      {
        title: "Kontakt",
        body: [
          "Support-Anfragen können per E-Mail an support@mantly.io gesendet werden.",
          "Bitte keine Passwörter, API-Schlüssel oder andere Geheimnisse per E-Mail senden.",
        ],
      },
      {
        title: "Hilfreiche Angaben",
        body: [
          "Bitte nennen Sie die verwendete E-Mail-Adresse, Organisation, eine kurze Beschreibung des Problems, den Zeitpunkt des Auftretens und relevante Fehlermeldungen.",
          "Bei Outlook-Problemen helfen außerdem Outlook-Version, Browser oder Desktop-App, Betriebssystem und die Schritte, mit denen sich das Problem reproduzieren lässt.",
        ],
      },
      {
        title: "Konto, Abrechnung und Kündigung",
        body: [
          "Für Fragen zu Konto, Plan, Rechnungen, Nutzungslimits oder Kündigung bitte die betroffene Organisation und Rechnungs-E-Mail angeben.",
        ],
      },
      {
        title: "Sicherheitsrelevante Hinweise",
        body: [
          "Bei Sicherheitsproblemen oder vermuteten Schwachstellen bitte SECURITY in den Betreff schreiben und keine öffentlich ausnutzbaren Details teilen, bevor wir geantwortet haben.",
        ],
      },
    ],
  },
  en: {
    title: "Mantly Support",
    intro:
      "For questions, technical issues, or billing questions about Mantly, contact support.",
    emailLabel: "support@mantly.io",
    emailHref: "mailto:support@mantly.io",
    sections: [
      {
        title: "Contact",
        body: [
          "Support requests can be sent by email to support@mantly.io.",
          "Please do not send passwords, API keys, or other secrets by email.",
        ],
      },
      {
        title: "What to Include",
        body: [
          "Please include the email address you use with Mantly, your organization, a short description of the issue, when it happened, and any relevant error messages.",
          "For Outlook issues, also include the Outlook version, browser or desktop app, operating system, and the steps needed to reproduce the issue.",
        ],
      },
      {
        title: "Account, Billing, and Cancellation",
        body: [
          "For account, plan, invoice, usage limit, or cancellation questions, include the affected organization and billing email address.",
        ],
      },
      {
        title: "Security Reports",
        body: [
          "For security issues or suspected vulnerabilities, include SECURITY in the subject line and avoid sharing publicly exploitable details before we respond.",
        ],
      },
    ],
  },
};

export function SupportPage() {
  const { lang } = useTranslation();
  const page = content[lang];

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
        <a
          href={page.emailHref}
          className="mt-8 inline-flex text-lg font-medium text-foreground underline-offset-4 hover:underline"
        >
          {page.emailLabel}
        </a>

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
