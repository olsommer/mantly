import { brand } from '@/brand';

export type Locale = 'en' | 'de';

const STORAGE_KEY = 'mantly_locale';
const LOCALE_EVENT = 'mantly:locale-changed';

const en: Record<string, string> = {
  // Home
  'home.title': brand.shortName,
  'home.noUser': 'No user loaded',
  'home.welcome': `Welcome to ${brand.shortName}`,
  'home.analyzeEmail': 'Open/create issue',
  'home.newDemo': 'New scenario',
  'home.resetDb': 'Reset database',
  'home.loading': 'Loading...',
  'home.error': 'Error',
  'home.productionHint': 'In production this is the start screen.',

  // Ticket surface
  'chat.noChat': 'No ticket context loaded',
  'chat.loading': 'Loading...',
  'chat.error': 'Error',
  'embed.dropEmail': 'Choose an email to start the preview.',
  'embed.backendError': 'Backend error',
  'embed.landingReady': 'Ready for the example demo',
  'embed.demoDisclaimer': 'Example demo: no data is stored or sent.',

  // Demo
  'demo.title': `${brand.shortName} Demo`,
  'demo.description': 'Choose an account and a demo email to start the simulation',
  'demo.selectAccount': 'Choose demo account',
  'demo.chooseAccount': 'Choose account...',
  'demo.selectEmail': 'Choose demo email',
  'demo.chooseEmail': 'Choose scenario...',
  'demo.preview': 'Preview',
  'demo.subject': 'Subject:',
  'demo.from': 'From:',
  'demo.start': 'Start demo',
  'demo.info': 'Demo mode - no real emails are sent. This screen is hidden in production.',
  'demo.attachments': 'Attachments',
  'demo.emailSource': 'Demo email',
  'demo.predefinedEmail': 'Predefined email',
  'demo.customEmail': 'Custom email',
  'demo.customSubject': 'Subject',
  'demo.customSubjectPlaceholder': 'Enter email subject...',
  'demo.customFrom': 'Sender',
  'demo.customFromPlaceholder': 'sender@example.com',
  'demo.customBody': 'Message',
  'demo.customBodyPlaceholder': 'Enter email text...',
  'demo.addAttachments': 'Add attachments',
  'demo.fileTooLarge': 'File exceeds 10 MB limit',
  'demo.productionHint': 'Note: This demo screen is only visible in the test environment and is hidden in production.',
  'demo.dbReset': 'Database was reset',

  // Email message
  'email.humanReview': 'Human review required',
  'email.humanReviewDesc': 'This email requires human attention and cannot be processed automatically right now. Please review and respond manually.',
  'email.attachments': 'Attachments',
  'email.addAttachment': 'Add file',
  'email.fileTooLarge': '{name} is too large (max 10 MB)',
  'email.apply': 'Apply',
  'email.applySuccess': 'Draft opened in Outlook',
  'email.applyError': 'Failed to apply draft',
  'email.unsavedWarning': 'You have unsaved changes. Do you really want to go back? Your changes will be lost.',

  // Original email
  'email.original': 'Original email',

  // App
  'app.notOutlook': 'Not opened in Outlook',
  'app.notOutlookDesc': 'This add-in must run in Microsoft Outlook.',
  'app.mockMode': 'To test in the browser, enable mock mode with ',
  'app.mockModeEnd': ' in the .env file.',

  // Toasts
  'toast.chatApiFailed': 'Ticket context could not be opened',

  // Feedback
  'feedback.title': 'What was wrong?',
  'feedback.description': 'Choose the affected area and optionally describe the problem.',
  'feedback.stageCustomer': 'Customer identification',
  'feedback.stageIntent': 'Intent recognition',
  'feedback.stageResponse': 'Response text',
  'feedback.additionalDetails': 'Feedback',
  'feedback.detailsPlaceholder': 'What exactly was wrong?',
  'feedback.submit': 'Submit',
  'feedback.submitting': 'Submitting...',
  'feedback.success': 'Feedback saved',
  'feedback.error': 'Feedback could not be sent',
  'feedback.thankYou': 'Feedback',

  // Auth
  'auth.login': 'Log in',
  'auth.signup': 'Sign up',
  'auth.email': 'Email',
  'auth.password': 'Password',
  'auth.firmName': 'Firm name',
  'auth.loginButton': 'Log in',
  'auth.signupButton': 'Register firm',
  'auth.switchToSignup': 'No account yet? Sign up',
  'auth.switchToLogin': 'Already registered? Log in',
  'auth.loginError': 'Invalid email or password',
  'auth.signupError': 'Registration failed',
  'auth.logout': 'Sign out',
  'auth.passwordMin': 'Password must be at least 8 characters',
  'auth.loginOnlyDescription': 'Sign in with your provided account.',
  'auth.forgotPassword': 'Forgot password?',
  'auth.enterEmailFirst': 'Please enter your email address first.',
  'auth.passwordResetSent': 'Password reset email sent.',
  'auth.changePasswordTitle': 'Change password',
  'auth.changePasswordDescription': 'You are using a temporary password. Set a new password now.',
  'auth.currentPassword': 'Current password',
  'auth.newPassword': 'New password',
  'auth.confirmPassword': 'Confirm new password',
  'auth.updatePassword': 'Update password',
  'auth.passwordMismatch': 'The new passwords do not match.',
  'auth.changePasswordError': 'Password could not be changed.',
  'auth.changePasswordSuccess': 'Password updated.',

  // Pipeline
  'pipeline.actions': 'Actions',
  'pipeline.generateResponse': 'Generate response',
  'pipeline.customer': 'Customer',
  'pipeline.error': 'Error',
  'pipeline.found': 'Found',
  'pipeline.notFound': 'Not found',
  'pipeline.noCustomerData': 'No customer data retrieved.',
  'pipeline.intent': 'Intent',
  'pipeline.noMatch': 'No match',
  'pipeline.noIntentMatch': 'No intent matched - email will require human review.',
  'pipeline.response': 'Response',
  'pipeline.select': '- select -',
  'pipeline.project': 'Project',
  'pipeline.user': 'User',
  'pipeline.notSignedIn': 'Not signed in',
  'pipeline.login': 'Log in',
  'pipeline.openAdmin': 'Open admin panel',
  'pipeline.openIssue': 'Open issue',
  'pipeline.openCreateIssue': 'Open/create issue',
  'pipeline.usage': 'Usage',

  // Ticket
  'ticket.issue': 'Issue',
  'ticket.loading': 'Loading issue...',
  'ticket.notLinked': 'No linked issue yet',
  'ticket.assignee': 'Assignee',
  'ticket.requester': 'Requester',
  'ticket.pendingApproval': '{count} approval pending',
  'ticket.pendingDelivery': '{count} delivery queued',
  'ticket.failedDelivery': '{count} delivery failed',
  'ticket.claim': 'Claim',
  'ticket.claimSuccess': 'Issue claimed',
  'ticket.claimError': 'Could not claim issue',
  'ticket.queueReply': 'Queue approval',
  'ticket.csatLink': 'CSAT link',
  'ticket.queueReplySuccess': 'Reply queued for approval',
  'ticket.queueReplyError': 'Could not queue reply',
  'ticket.retryDelivery': 'Retry delivery',
  'ticket.retryDeliverySuccess': 'Delivery retry queued',
  'ticket.retryDeliveryError': 'Could not retry delivery',
  'ticket.requestChanges': 'Request changes',
  'ticket.requestChangesPlaceholder': 'Tell the agent what to change',
  'ticket.requestChangesDefaultNote': 'Requested from Outlook add-in',
  'ticket.requestChangesSuccess': 'Changes requested',
  'ticket.requestChangesError': 'Could not request changes',
  'ticket.approve': 'Approve',
  'ticket.approveSend': 'Approve & send',
  'ticket.approveSuccess': 'Reply approved',
  'ticket.sendSuccess': 'Reply sent',
  'ticket.approveError': 'Could not approve reply',
  'ticket.createSuccess': 'Issue created',
  'ticket.openCreateError': 'Could not open or create issue',
  'ticket.nextAction': 'Next action',
  'ticket.nextOpenCreate': 'Open/create issue',
  'ticket.nextOpenCreateDetail': 'Link this email to the support queue.',
  'ticket.nextFixDelivery': 'Fix failed delivery',
  'ticket.nextFixDeliveryDetail': '{count} delivery failed. Retry from this surface.',
  'ticket.nextReviewApproval': 'Review approval',
  'ticket.nextReviewApprovalDetail': '{count} approval waits for human review.',
  'ticket.nextAssign': 'Assign owner',
  'ticket.nextAssignDetail': 'Claim this issue before work starts.',
  'ticket.nextQueueReply': 'Queue prepared reply',
  'ticket.nextQueueReplyDetail': 'Send the current draft into human approval.',
  'ticket.nextOverdueSla': 'Handle overdue SLA',
  'ticket.nextOverdueSlaDetail': 'Open the issue and recover the SLA.',
  'ticket.nextReply': 'Reply to customer',
  'ticket.nextReplyDetail': 'Customer is waiting for a response.',
  'ticket.nextMonitorDelivery': 'Monitor queued delivery',
  'ticket.nextMonitorDeliveryDetail': '{count} delivery is still queued.',
  'ticket.nextClose': 'Ready to close',
  'ticket.nextCloseDetail': 'No open blocker detected.',
  'ticket.nextClear': 'No immediate action',
  'ticket.nextClearDetail': 'Issue is clear for now.',
  'ticket.markDone': 'Mark done',
  'ticket.markDoneSuccess': 'Issue closed',
  'ticket.markDoneError': 'Could not close issue',
  'ticket.statusOpen': 'Open',
  'ticket.statusOngoing': 'Ongoing',
  'ticket.statusDone': 'Done',
  'ticket.priorityLow': 'Low',
  'ticket.priorityNormal': 'Normal',
  'ticket.priorityHigh': 'High',
  'ticket.priorityUrgent': 'Urgent',

  // Security
  'security.promptInjection': 'Prompt injection',
  'security.phishingRisk': 'Phishing risk',
  'security.promptRisk': 'Prompt injection risk',
  'security.fallbackReason': 'Suspicious indicators were detected.',
  'security.check': 'Security check:',
  'security.flagged': '{summary} flagged',
  'security.details': 'Details',
  'security.detected': 'Security risk detected',
  'security.warningOnly': 'Warning only. The email response was not blocked or changed.',

  // Misc
  'misc.noSubject': '(No subject)',
  'misc.add': 'Add',
};

const de: Record<string, string> = {
  // Home
  'home.title': brand.shortName,
  'home.noUser': 'Kein Benutzer geladen',
  'home.welcome': `Willkommen bei ${brand.shortName}`,
  'home.analyzeEmail': 'Issue öffnen/erstellen',
  'home.newDemo': 'Neues Szenario',
  'home.resetDb': 'Datenbank zurücksetzen',
  'home.loading': 'Laden...',
  'home.error': 'Fehler',
  'home.productionHint': 'In der Produktivumgebung ist dies der Startbildschirm.',

  // Ticket surface
  'chat.noChat': 'Kein Issue-Kontext geladen',
  'chat.loading': 'Laden...',
  'chat.error': 'Fehler',
  'embed.dropEmail': 'E-Mail wählen, um die Vorschau zu starten.',
  'embed.backendError': 'Backend-Fehler',
  'embed.landingReady': 'Bereit für die Beispieldemo',
  'embed.demoDisclaimer': 'Beispieldemo: keine Daten werden gespeichert oder versendet.',

  // Demo
  'demo.title': `${brand.shortName} Demo`,
  'demo.description': 'Wählen Sie ein Benutzerkonto und eine Demo-E-Mail aus, um die Simulation zu starten',
  'demo.selectAccount': 'Demo-Konto auswählen',
  'demo.chooseAccount': 'Konto auswählen...',
  'demo.selectEmail': 'Demo-E-Mail auswählen',
  'demo.chooseEmail': 'Szenario auswählen...',
  'demo.preview': 'Vorschau',
  'demo.subject': 'Betreff:',
  'demo.from': 'Von:',
  'demo.start': 'Demo starten',
  'demo.info': 'Demo-Modus - es werden keine echten E-Mails versendet. Dieser Bildschirm entfällt in der Produktivumgebung.',
  'demo.attachments': 'Anhänge',
  'demo.emailSource': 'Demo-Mail',
  'demo.predefinedEmail': 'Vordefinierte E-Mail',
  'demo.customEmail': 'Eigene E-Mail',
  'demo.customSubject': 'Betreff',
  'demo.customSubjectPlaceholder': 'E-Mail Betreff eingeben...',
  'demo.customFrom': 'Absender',
  'demo.customFromPlaceholder': 'absender@example.com',
  'demo.customBody': 'Nachricht',
  'demo.customBodyPlaceholder': 'E-Mail Text eingeben...',
  'demo.addAttachments': 'Anhänge hinzufügen',
  'demo.fileTooLarge': 'Datei überschreitet 10 MB Limit',
  'demo.productionHint': 'Hinweis: Dieser Demo-Bildschirm ist nur in der Testumgebung sichtbar und entfällt in der Produktivumgebung.',
  'demo.dbReset': 'Datenbank wurde zurückgesetzt',

  // Email message
  'email.humanReview': 'Manuelle Prüfung erforderlich',
  'email.humanReviewDesc': 'Diese E-Mail erfordert menschliche Aufmerksamkeit und kann derzeit nicht automatisch verarbeitet werden. Bitte prüfen und manuell beantworten.',
  'email.attachments': 'Anhänge',
  'email.addAttachment': 'Datei hinzufügen',
  'email.fileTooLarge': '{name} ist zu groß (max. 10 MB)',
  'email.apply': 'Anwenden',
  'email.applySuccess': 'Entwurf in Outlook geöffnet',
  'email.applyError': 'Fehler beim Anwenden des Entwurfs',
  'email.unsavedWarning': 'Sie haben ungespeicherte Änderungen. Möchten Sie wirklich zurückgehen? Ihre Änderungen gehen verloren.',

  // Original email
  'email.original': 'Original-E-Mail',

  // App
  'app.notOutlook': 'Nicht in Outlook geöffnet',
  'app.notOutlookDesc': 'Dieses Add-in muss in Microsoft Outlook ausgeführt werden.',
  'app.mockMode': 'Um im Browser zu testen, aktivieren Sie den Mock-Modus mit ',
  'app.mockModeEnd': ' in der .env-Datei.',

  // Toasts
  'toast.chatApiFailed': 'Issue-Kontext konnte nicht geöffnet werden',

  // Feedback
  'feedback.title': 'Was war falsch?',
  'feedback.description': 'Wählen Sie den betroffenen Bereich aus und beschreiben Sie optional das Problem.',
  'feedback.stageCustomer': 'Kundenidentifikation',
  'feedback.stageIntent': 'Anliegenerkennung',
  'feedback.stageResponse': 'Antworttext',
  'feedback.additionalDetails': 'Feedback',
  'feedback.detailsPlaceholder': 'Was genau war falsch?',
  'feedback.submit': 'Absenden',
  'feedback.submitting': 'Wird gesendet...',
  'feedback.success': 'Feedback gespeichert',
  'feedback.error': 'Feedback konnte nicht gesendet werden',
  'feedback.thankYou': 'Feedback',

  // Auth
  'auth.login': 'Anmelden',
  'auth.signup': 'Registrieren',
  'auth.email': 'E-Mail',
  'auth.password': 'Passwort',
  'auth.firmName': 'Kanzleiname',
  'auth.loginButton': 'Anmelden',
  'auth.signupButton': 'Kanzlei registrieren',
  'auth.switchToSignup': 'Noch kein Konto? Registrieren',
  'auth.switchToLogin': 'Bereits registriert? Anmelden',
  'auth.loginError': 'Ungültige E-Mail oder Passwort',
  'auth.signupError': 'Registrierung fehlgeschlagen',
  'auth.logout': 'Abmelden',
  'auth.passwordMin': 'Passwort muss mindestens 8 Zeichen lang sein',
  'auth.loginOnlyDescription': 'Melden Sie sich mit Ihrem bereitgestellten Konto an.',
  'auth.forgotPassword': 'Passwort vergessen?',
  'auth.enterEmailFirst': 'Bitte zuerst Ihre E-Mail-Adresse eingeben.',
  'auth.passwordResetSent': 'E-Mail zum Zurücksetzen des Passworts wurde versendet.',
  'auth.changePasswordTitle': 'Passwort ändern',
  'auth.changePasswordDescription': 'Sie verwenden ein temporäres Passwort. Legen Sie jetzt ein neues Passwort fest.',
  'auth.currentPassword': 'Aktuelles Passwort',
  'auth.newPassword': 'Neues Passwort',
  'auth.confirmPassword': 'Neues Passwort bestätigen',
  'auth.updatePassword': 'Passwort aktualisieren',
  'auth.passwordMismatch': 'Die neuen Passwörter stimmen nicht überein.',
  'auth.changePasswordError': 'Passwort konnte nicht geändert werden.',
  'auth.changePasswordSuccess': 'Passwort aktualisiert.',

  // Pipeline
  'pipeline.actions': 'Aktionen',
  'pipeline.generateResponse': 'Antwort generieren',
  'pipeline.customer': 'Kunde',
  'pipeline.error': 'Fehler',
  'pipeline.found': 'Gefunden',
  'pipeline.notFound': 'Nicht gefunden',
  'pipeline.noCustomerData': 'Keine Kundendaten abgerufen.',
  'pipeline.intent': 'Anliegen',
  'pipeline.noMatch': 'Kein Treffer',
  'pipeline.noIntentMatch': 'Kein Anliegen erkannt - E-Mail erfordert manuelle Prüfung.',
  'pipeline.response': 'Antwort',
  'pipeline.select': '- auswählen -',
  'pipeline.project': 'Projekt',
  'pipeline.user': 'Benutzer',
  'pipeline.notSignedIn': 'Nicht angemeldet',
  'pipeline.login': 'Anmelden',
  'pipeline.openAdmin': 'Adminbereich öffnen',
  'pipeline.openIssue': 'Issue öffnen',
  'pipeline.openCreateIssue': 'Issue öffnen/erstellen',
  'pipeline.usage': 'Nutzung',

  // Ticket
  'ticket.issue': 'Issue',
  'ticket.loading': 'Issue wird geladen...',
  'ticket.notLinked': 'Noch kein verknüpftes Issue',
  'ticket.assignee': 'Zuständig',
  'ticket.requester': 'Anfragende Person',
  'ticket.pendingApproval': '{count} Freigabe offen',
  'ticket.pendingDelivery': '{count} Zustellung offen',
  'ticket.failedDelivery': '{count} Zustellung fehlgeschlagen',
  'ticket.claim': 'Übernehmen',
  'ticket.claimSuccess': 'Issue übernommen',
  'ticket.claimError': 'Issue konnte nicht übernommen werden',
  'ticket.queueReply': 'Zur Freigabe',
  'ticket.csatLink': 'CSAT-Link',
  'ticket.queueReplySuccess': 'Antwort zur Freigabe eingereiht',
  'ticket.queueReplyError': 'Antwort konnte nicht eingereiht werden',
  'ticket.retryDelivery': 'Zustellung wiederholen',
  'ticket.retryDeliverySuccess': 'Zustellwiederholung eingereiht',
  'ticket.retryDeliveryError': 'Zustellung konnte nicht wiederholt werden',
  'ticket.requestChanges': 'Änderungen anfordern',
  'ticket.requestChangesPlaceholder': 'Was soll der Agent ändern?',
  'ticket.requestChangesDefaultNote': 'Aus dem Outlook-Add-in angefordert',
  'ticket.requestChangesSuccess': 'Änderungen angefordert',
  'ticket.requestChangesError': 'Änderungen konnten nicht angefordert werden',
  'ticket.approve': 'Freigeben',
  'ticket.approveSend': 'Freigeben & senden',
  'ticket.approveSuccess': 'Antwort freigegeben',
  'ticket.sendSuccess': 'Antwort gesendet',
  'ticket.approveError': 'Antwort konnte nicht freigegeben werden',
  'ticket.createSuccess': 'Issue erstellt',
  'ticket.openCreateError': 'Issue konnte nicht geöffnet oder erstellt werden',
  'ticket.nextAction': 'Nächste Aktion',
  'ticket.nextOpenCreate': 'Issue öffnen/erstellen',
  'ticket.nextOpenCreateDetail': 'Diese E-Mail mit der Support-Queue verknüpfen.',
  'ticket.nextFixDelivery': 'Fehlgeschlagene Zustellung beheben',
  'ticket.nextFixDeliveryDetail': '{count} Zustellung fehlgeschlagen. Von hier erneut versuchen.',
  'ticket.nextReviewApproval': 'Freigabe prüfen',
  'ticket.nextReviewApprovalDetail': '{count} Freigabe wartet auf manuelle Prüfung.',
  'ticket.nextAssign': 'Owner zuweisen',
  'ticket.nextAssignDetail': 'Issue übernehmen, bevor die Bearbeitung startet.',
  'ticket.nextQueueReply': 'Vorbereitete Antwort einreihen',
  'ticket.nextQueueReplyDetail': 'Aktuellen Entwurf in die manuelle Freigabe geben.',
  'ticket.nextOverdueSla': 'Überfällige SLA bearbeiten',
  'ticket.nextOverdueSlaDetail': 'Issue öffnen und SLA wiederherstellen.',
  'ticket.nextReply': 'Kundschaft antworten',
  'ticket.nextReplyDetail': 'Kundschaft wartet auf eine Antwort.',
  'ticket.nextMonitorDelivery': 'Zustellung beobachten',
  'ticket.nextMonitorDeliveryDetail': '{count} Zustellung ist noch eingereiht.',
  'ticket.nextClose': 'Bereit zum Schließen',
  'ticket.nextCloseDetail': 'Kein offener Blocker erkannt.',
  'ticket.nextClear': 'Keine direkte Aktion',
  'ticket.nextClearDetail': 'Issue ist aktuell klar.',
  'ticket.markDone': 'Erledigt markieren',
  'ticket.markDoneSuccess': 'Issue geschlossen',
  'ticket.markDoneError': 'Issue konnte nicht geschlossen werden',
  'ticket.statusOpen': 'Offen',
  'ticket.statusOngoing': 'Laufend',
  'ticket.statusDone': 'Erledigt',
  'ticket.priorityLow': 'Niedrig',
  'ticket.priorityNormal': 'Normal',
  'ticket.priorityHigh': 'Hoch',
  'ticket.priorityUrgent': 'Dringend',

  // Security
  'security.promptInjection': 'Prompt Injection',
  'security.phishingRisk': 'Phishing-Risiko',
  'security.promptRisk': 'Prompt-Injection-Risiko',
  'security.fallbackReason': 'Verdächtige Hinweise wurden erkannt.',
  'security.check': 'Sicherheitsprüfung:',
  'security.flagged': '{summary} markiert',
  'security.details': 'Details',
  'security.detected': 'Sicherheitsrisiko erkannt',
  'security.warningOnly': 'Nur Warnung. Die E-Mail-Antwort wurde nicht blockiert oder verändert.',

  // Misc
  'misc.noSubject': '(Kein Betreff)',
  'misc.add': 'Hinzufügen',
};

let currentLocale: Locale = getStoredLocale();

function browserLocale(): Locale {
  if (typeof navigator !== 'undefined' && navigator.language.toLowerCase().startsWith('de')) {
    return 'de';
  }
  return 'en';
}

export function normalizeLocale(value: unknown): Locale {
  return value === 'de' || value === 'en' ? value : browserLocale();
}

export function getStoredLocale(): Locale {
  if (typeof localStorage === 'undefined') return browserLocale();
  return normalizeLocale(localStorage.getItem(STORAGE_KEY));
}

export function setLanguage(locale: Locale): void {
  currentLocale = locale;
  localStorage.setItem(STORAGE_KEY, locale);
  window.dispatchEvent(new CustomEvent(LOCALE_EVENT, { detail: locale }));
}

export function syncLanguage(value: unknown): Locale {
  const locale = normalizeLocale(value);
  setLanguage(locale);
  return locale;
}

export function t(key: string, values: Record<string, string | number> = {}): string {
  const dict = currentLocale === 'de' ? de : en;
  const template = dict[key] ?? en[key] ?? key;
  return template.replace(/\{(\w+)\}/g, (_, name: string) => String(values[name] ?? `{${name}}`));
}

if (typeof window !== 'undefined') {
  window.addEventListener('storage', event => {
    if (event.key === STORAGE_KEY) currentLocale = normalizeLocale(event.newValue);
  });
  window.addEventListener(LOCALE_EVENT, event => {
    currentLocale = normalizeLocale((event as CustomEvent<unknown>).detail);
  });
}
