"""Deterministic guard for customer-facing claims about pending actions."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

PENDING_ACTION_CLAIM_REASON_CODE = "pending_action_claim"
PENDING_ACTION_REPAIR_NOTICE = (
    "Any requested action that requires human review is pending and is not confirmed as started or completed."
)

_PROGRESSIVE_ACTIONS = (
    r"initiating",
    r"checking",
    r"escalating",
    r"investigating",
    r"opening",
    r"submitting",
    r"processing",
    r"reviewing",
    r"contacting",
    r"notifying",
    r"arranging",
    r"scheduling",
    r"issuing",
    r"refunding",
    r"cancell?ing",
    r"closing",
    r"terminating",
    r"rescinding",
    r"changing",
    r"updating",
    r"dispatching",
    r"reshipping",
    r"replacing",
    r"creating",
    r"starting",
    r"beginning",
    r"activating",
    r"authorizing",
    r"prioriti[sz]ing",
    r"working\s+on",
    r"looking\s+into",
    r"following\s+up",
    r"reaching\s+out",
    r"taking\s+action",
    r"taking\s+steps\s+to\s+(?:address|advance|handle|progress|resolve)",
    r"forwarding",
    r"recording",
    r"logging",
)
_COMPLETED_ACTIONS = (
    r"initiated",
    r"checked",
    r"escalated",
    r"investigated",
    r"opened",
    r"submitted",
    r"processed",
    r"reviewed",
    r"contacted",
    r"notified",
    r"arranged",
    r"scheduled",
    r"issued",
    r"refunded",
    r"cancelled",
    r"canceled",
    r"closed",
    r"terminated",
    r"rescinded",
    r"changed",
    r"updated",
    r"dispatched",
    r"reshipped",
    r"replaced",
    r"created",
    r"flagged",
    r"marked",
    r"started",
    r"begun",
    r"activated",
    r"authorized",
    r"prioriti[sz]ed",
    r"completed",
    r"finished",
    r"forwarded",
    r"recorded",
    r"logged",
)
_FUTURE_ACTIONS = (
    r"initiate",
    r"check",
    r"escalate",
    r"investigate",
    r"open",
    r"submit",
    r"process",
    r"review",
    r"contact",
    r"notify",
    r"arrange",
    r"schedule",
    r"issue",
    r"refund",
    r"cancel",
    r"close",
    r"terminate",
    r"rescind",
    r"change",
    r"update",
    r"dispatch",
    r"reship",
    r"replace",
    r"create",
    r"start",
    r"begin",
    r"activate",
    r"authorize",
    r"prioriti[sz]e",
    r"flag",
    r"mark",
    r"work\s+on",
    r"look\s+into",
    r"follow\s+up",
    r"reach\s+out",
    r"take\s+action",
    r"take\s+steps\s+to\s+(?:address|advance|handle|progress|resolve)",
    r"forward",
    r"record",
    r"log",
)
_ACTION_STATE_SUBJECTS = (
    r"request",
    r"case",
    r"ticket",
    r"investigation",
    r"escalation",
    r"claim",
    r"refund",
    r"cancellation",
    r"cancelation",
    r"replacement",
    r"return",
    r"review",
    r"incident",
    r"issue",
    r"action",
    r"task",
    r"address\s+change",
    r"order\s+cancell?ation",
    r"order\s+change",
    r"contract\s+cancell?ation",
    r"contract\s+change",
    r"subscription\s+cancell?ation",
    r"subscription\s+change",
    r"carrier\s+redirect",
    r"warehouse\s+ticket",
    r"matter",
    r"triage",
    r"conflict",
)
_ACTION_STATE_SUBJECT_PATTERN = rf"(?:[a-z][a-z0-9-]*\s+){{0,3}}(?:{'|'.join(_ACTION_STATE_SUBJECTS)})"
_CONFIRMATION_ACTION_STATE_MODIFIERS = (
    r"executive",
    r"urgent",
    r"internal",
    r"human",
    r"manual",
    r"warehouse",
    r"support",
    r"delivery",
    r"fulfillment",
    r"customer",
    r"refund",
    r"cancell?ation",
    r"replacement",
    r"return",
    r"address",
    r"order",
    r"contract",
    r"subscription",
    r"carrier",
)
_CONFIRMATION_ACTION_STATE_SUBJECT_PATTERN = (
    rf"(?:(?:{'|'.join(_CONFIRMATION_ACTION_STATE_MODIFIERS)})\s+){{0,2}}"
    rf"(?:{'|'.join(_ACTION_STATE_SUBJECTS)})"
)
_LIFECYCLE_STATE_SUBJECTS = (
    r"order",
    r"contract",
    r"agreement",
    r"subscription",
    r"membership",
    r"address",
    r"billing\s+address",
    r"delivery\s+address",
    r"shipping\s+address",
)
_LIFECYCLE_COMPLETED_ACTIONS = (
    r"cancelled",
    r"canceled",
    r"changed",
    r"updated",
    r"terminated",
    r"rescinded",
)
_EXTENDED_ACTION_TARGET_SUBJECTS = (
    r"deadline",
    r"shipment",
    r"delivery",
    r"order",
    r"contract",
    r"agreement",
    r"subscription",
    r"membership",
)
_TARGET_MUTATION_COMPLETED_ACTIONS = (
    r"initiated",
    r"escalated",
    r"investigated",
    r"opened",
    r"submitted",
    r"contacted",
    r"arranged",
    r"scheduled",
    r"issued",
    r"refunded",
    r"cancelled",
    r"canceled",
    r"terminated",
    r"rescinded",
    r"changed",
    r"updated",
    r"dispatched",
    r"reshipped",
    r"replaced",
    r"created",
    r"flagged",
    r"marked",
    r"activated",
    r"authorized",
    r"prioriti[sz]ed",
    r"forwarded",
    r"recorded",
    r"logged",
)
_CUSTOM_PROGRESSIVE_ACTIONS = (
    r"approving",
    r"archiving",
    r"deleting",
)
_CUSTOM_COMPLETED_ACTIONS = (r"approved", r"archived", r"deleted")

_GERMAN_COMPLETED_ACTIONS = (
    r"eröffnet",
    r"geöffnet",
    r"eskaliert",
    r"storniert",
    r"gekündigt",
    r"geändert",
    r"aktualisiert",
    r"erstattet",
    r"rückerstattet",
    r"zurückerstattet",
)
_GERMAN_FUTURE_ACTIONS = (
    r"eröffnen",
    r"öffnen",
    r"eskalieren",
    r"stornieren",
    r"kündigen",
    r"ändern",
    r"aktualisieren",
    r"erstatten",
    r"rückerstatten",
    r"zurückerstatten",
)
_GERMAN_ACTION_SUBJECTS = (
    r"anfrage",
    r"fall",
    r"ticket",
    r"untersuchung",
    r"eskalation",
    r"reklamation",
    r"rückerstattung",
    r"stornierung",
    r"kündigung",
    r"ersatz",
    r"retoure",
    r"auftrag",
    r"bestellung",
    r"vertrag",
    r"abonnement",
    r"adresse",
    r"adressänderung",
)

_FRENCH_COMPLETED_ACTIONS = (
    r"ouvert(?:e|es|s)?",
    r"escaladé(?:e|es|s)?",
    r"annulé(?:e|es|s)?",
    r"résilié(?:e|es|s)?",
    r"modifié(?:e|es|s)?",
    r"mis(?:e|es)?\s+à\s+jour",
    r"remboursé(?:e|es|s)?",
)
_FRENCH_FUTURE_ACTIONS = (
    r"ouvrir",
    r"escalader",
    r"annuler",
    r"résilier",
    r"modifier",
    r"mettre\s+à\s+jour",
    r"rembourser",
)
_FRENCH_ACTION_SUBJECTS = (
    r"demande",
    r"dossier",
    r"ticket",
    r"enquête",
    r"escalade",
    r"remboursement",
    r"annulation",
    r"remplacement",
    r"retour",
    r"commande",
    r"contrat",
    r"abonnement",
    r"adresse",
)

_SPANISH_COMPLETED_ACTIONS = (
    r"abiert[oa]s?",
    r"escalad[oa]s?",
    r"cancelad[oa]s?",
    r"anulad[oa]s?",
    r"modificad[oa]s?",
    r"actualizad[oa]s?",
    r"reembolsad[oa]s?",
)
_SPANISH_FUTURE_ACTIONS = (
    r"abrir",
    r"escalar",
    r"cancelar",
    r"anular",
    r"modificar",
    r"actualizar",
    r"reembolsar",
)
_SPANISH_ACTION_SUBJECTS = (
    r"solicitud",
    r"caso",
    r"ticket",
    r"investigación",
    r"escalad[oa]",
    r"reembolso",
    r"cancelación",
    r"reemplazo",
    r"devolución",
    r"pedido",
    r"contrato",
    r"suscripción",
    r"dirección",
)

_ITALIAN_COMPLETED_ACTIONS = (
    r"apert[oa]",
    r"escalat[oa]",
    r"annullat[oa]",
    r"cancellat[oa]",
    r"modificat[oa]",
    r"aggiornat[oa]",
    r"rimborsat[oa]",
)
_ITALIAN_FUTURE_ACTIONS = (
    r"aprire",
    r"escalare",
    r"annullare",
    r"cancellare",
    r"modificare",
    r"aggiornare",
    r"rimborsare",
)
_ITALIAN_ACTION_SUBJECTS = (
    r"richiesta",
    r"caso",
    r"ticket",
    r"indagine",
    r"escalation",
    r"rimborso",
    r"annullamento",
    r"sostituzione",
    r"reso",
    r"ordine",
    r"contratto",
    r"abbonamento",
    r"indirizzo",
)

_ACTION_MODIFIER_PATTERN = (
    r"(?:(?:already|currently|now|actively|immediately|promptly|successfully|just|"
    r"also|therefore|further|[a-z]+ly)\s+)*"
)
_DEFINITE_ACTION_MODIFIER_PATTERN = r"(?:definitely|certainly|surely|absolutely)"
_SENSITIVE_NOTE_SUBJECT_PATTERN = (
    r"(?:(?:potential\s+)?conflict|"
    r"(?:marketing\s+)?opt(?:-|\s*)out(?:\s+request)?|"
    r"do(?:-|\s+)not(?:-|\s+)contact(?:\s+request)?|"
    r"request\s+not\s+to\s+be\s+contacted)"
)
_PROGRESSIVE_ACTION_PATTERN = re.compile(
    rf"\b(?:we\s+are|we['’]re|i\s+am|i['’]m)\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}"
    rf"(?:{'|'.join(_PROGRESSIVE_ACTIONS)})\b",
    re.IGNORECASE,
)
_PRE_AUX_PROGRESSIVE_ACTION_PATTERN = re.compile(
    rf"\b(?:we|i)\s+{_DEFINITE_ACTION_MODIFIER_PATTERN}\s+(?:are|am)\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}"
    rf"(?:{'|'.join(_PROGRESSIVE_ACTIONS)})\b",
    re.IGNORECASE,
)
_COORDINATED_PROGRESSIVE_ACTION_PATTERN = re.compile(
    rf"\b(?:"
    rf"(?:(?:we\s+are|we['’]re|i\s+am|i['’]m)\s+[^.!?\n]{{1,140}}?"
    rf"\b(?:and|but)\s+(?:(?:we\s+are|i\s+am)\s+)?)|"
    rf"(?:(?:we|i)\s+[^.!?\n]{{1,140}}?\b(?:and|but)\s+"
    rf"(?:(?:we\s+are|i\s+am|are|am)\s+))"
    rf")"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}"
    rf"(?:{'|'.join(_PROGRESSIVE_ACTIONS)})\b",
    re.IGNORECASE,
)
_PERFECT_ACTION_PATTERN = re.compile(
    rf"\b(?:we\s+have|we['’]ve|i\s+have|i['’]ve)\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}"
    rf"(?:{'|'.join(_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_PRE_AUX_PERFECT_ACTION_PATTERN = re.compile(
    rf"\b(?:we|i)\s+{_DEFINITE_ACTION_MODIFIER_PATTERN}\s+have\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}"
    rf"(?:{'|'.join(_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_COORDINATED_PERFECT_ACTION_PATTERN = re.compile(
    rf"\b(?:we|i)\s+have\s+[^.!?\n]{{1,140}}?\b(?:and|but)\s+have\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}"
    rf"(?:{'|'.join(_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_PAST_ACTION_PATTERN = re.compile(
    rf"\b(?:we|i)\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}"
    rf"(?:{'|'.join(_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_SENSITIVE_NOTE_ACTION_PATTERN = re.compile(
    r"\b(?:"
    r"(?:we|i)(?:\s+have|['’]ve)?\s+(?!(?:not|never)\b)"
    r"(?:(?:already|formally|internally)\s+)*noted\b(?:"
    r"\s*[:,]?\s+(?:(?:a|the|this|your|our)\s+)?"
    rf"{_SENSITIVE_NOTE_SUBJECT_PATTERN}\b|"
    r"[^.!?\n]{1,60}\bas\s+(?:a\s+)?potential\s+conflict\b)|"
    r"(?<!no\s)(?<!not\s)"
    rf"(?:(?:a|the|this|your|our)\s+)?{_SENSITIVE_NOTE_SUBJECT_PATTERN}\b"
    r"[^.!?\n]{0,80}\b(?:has|have|is|was|were)\s+"
    r"(?:(?:already|formally|internally)\s+)*(?:been\s+)?"
    r"(?:noted|recorded|logged)\b"
    r")",
    re.IGNORECASE,
)
_PASSIVE_ACTION_PATTERN = re.compile(
    rf"\b(?:a|an|the|this|your|our)\s+{_ACTION_STATE_SUBJECT_PATTERN}\b"
    rf"[^.!?\n]{{0,100}}?\b"
    rf"(?:has|have|is|are|was|were)\s+(?:(?:already|successfully|now|currently)\s+)*"
    rf"(?:been\s+|being\s+)?(?:{'|'.join(_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_BARE_PASSIVE_ACTION_PATTERN = re.compile(
    rf"^\s*(?:{'|'.join(_ACTION_STATE_SUBJECTS)})\b"
    rf"[^.!?\n]{{0,100}}?\b"
    rf"(?:has|have|is|are|was|were)\s+(?:(?:already|successfully|now|currently)\s+)*"
    rf"(?:been\s+|being\s+)?(?:{'|'.join(_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_BARE_LIFECYCLE_PASSIVE_ACTION_PATTERN = re.compile(
    rf"^\s*(?:{'|'.join(_LIFECYCLE_STATE_SUBJECTS)})\b"
    rf"[^.!?\n]{{0,100}}?\b"
    rf"(?:has|have|is|are|was|were)\s+(?:(?:already|successfully|now|currently)\s+)*"
    rf"(?:been\s+|being\s+)?(?:{'|'.join(_LIFECYCLE_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_BARE_FUTURE_PASSIVE_ACTION_PATTERN = re.compile(
    rf"^\s*(?:{'|'.join(_ACTION_STATE_SUBJECTS)})\b"
    rf"[^.!?\n]{{0,100}}?\b(?:will|shall)\s+"
    rf"(?!(?:not|never)\b)(?:(?:soon|shortly|now|immediately)\s+)*be\s+"
    rf"(?:{'|'.join((*_COMPLETED_ACTIONS, *_LIFECYCLE_COMPLETED_ACTIONS))})\b",
    re.IGNORECASE,
)
_BARE_FUTURE_LIFECYCLE_PASSIVE_ACTION_PATTERN = re.compile(
    rf"^\s*(?:{'|'.join(_LIFECYCLE_STATE_SUBJECTS)})\b"
    rf"[^.!?\n]{{0,100}}?\b(?:will|shall)\s+"
    rf"(?!(?:not|never)\b)(?:(?:soon|shortly|now|immediately)\s+)*be\s+"
    rf"(?:{'|'.join(_LIFECYCLE_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_TARGET_MUTATION_PASSIVE_ACTION_PATTERN = re.compile(
    rf"\b(?:(?:a|an|the|this|your|our)\s+)?"
    rf"(?:{'|'.join(_EXTENDED_ACTION_TARGET_SUBJECTS)})\b"
    rf"[^.!?\n]{{0,100}}?\b(?:has|have|is|are|was|were)\s+"
    rf"(?!(?:not|never)\b)(?:(?:already|successfully|now|currently)\s+)*"
    rf"(?:been\s+|being\s+)?(?:{'|'.join(_TARGET_MUTATION_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_TARGET_MUTATION_FUTURE_PASSIVE_ACTION_PATTERN = re.compile(
    rf"\b(?:(?:a|an|the|this|your|our)\s+)?"
    rf"(?:{'|'.join(_EXTENDED_ACTION_TARGET_SUBJECTS)})\b"
    rf"[^.!?\n]{{0,100}}?\b(?:will|shall)\s+"
    rf"(?!(?:not|never)\b)(?:(?:soon|shortly|now|immediately)\s+)*be\s+"
    rf"(?:{'|'.join(_TARGET_MUTATION_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_LIFECYCLE_PASSIVE_ACTION_PATTERN = re.compile(
    rf"\b(?:a|an|the|this|your|our)\s+"
    rf"(?:{'|'.join(_LIFECYCLE_STATE_SUBJECTS)})\b"
    rf"[^.!?\n]{{0,100}}?\b"
    rf"(?:has|have|is|are|was|were)\s+(?:(?:already|successfully|now|currently)\s+)*"
    rf"(?:been\s+|being\s+)?(?:{'|'.join(_LIFECYCLE_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_NARROW_LIFECYCLE_CANCELLATION_PATTERN = re.compile(
    r"\b(?:"
    r"(?:a|an|the|this|your|our)\s+"
    r"(?:(?:first|second|third|fourth|other|additional)\s+)?"
    r"(?:order|contract|subscription)|"
    r"(?:order|contract|subscription)\s+[a-z0-9][a-z0-9_-]{0,63}"
    r")\s+"
    r"(?:has|have|is|are|was|were)\s+"
    r"(?:(?:already|successfully|now|currently)\s+)*(?:been\s+)?"
    r"(?:cancelled|canceled|terminated)\b",
    re.IGNORECASE,
)
_TERSE_COMPLETED_ACTION_PATTERN = re.compile(
    rf"(?:^|[;:—–]\s*|\b(?:and|but|then)\s+)"
    rf"\s*"
    rf"(?:(?:[-*•✅]|\d+[.)])\s+)?"
    rf"(?:(?:status|result)\s*:\s*)?"
    rf"(?:(?:a|an|the|this|your|our)\s+)?"
    rf"(?:{'|'.join((*_ACTION_STATE_SUBJECTS, *_LIFECYCLE_STATE_SUBJECTS, *_EXTENDED_ACTION_TARGET_SUBJECTS))})\b"
    rf"(?:(?!\b(?:not|never|pending|unconfirmed|unapproved|incomplete|unsuccessful|"
    rf"policy|policies|guidance|instructions?|process|procedure|criteria|"
    rf"eligibility|rules?|typically|generally|will|shall|would|could|may|"
    rf"might|has|have|is|are|was|were)\b)[^.!?\n]){{0,80}}?"
    rf"(?:[,/:—–-]\s*)?(?:(?:already|successfully|now)\s+)*"
    rf"(?:{'|'.join((*_COMPLETED_ACTIONS, *_LIFECYCLE_COMPLETED_ACTIONS, 'complete', 'done', 'successful', 'confirmed'))})\b",
    re.IGNORECASE,
)
_TERSE_ACTION_FIRST_PATTERN = re.compile(
    rf"(?:^|[;:—–]\s*|\b(?:and|but|then)\s+)\s*"
    rf"(?:(?:[-+*•✅>]\s*|\d+[.)]\s*|\|\s*)?)"
    rf"(?:(?:already|successfully|now)\s+)*"
    rf"(?:{'|'.join((*_COMPLETED_ACTIONS, *_LIFECYCLE_COMPLETED_ACTIONS, 'complete', 'done'))})\b"
    rf"(?:\s*[:—–-]\s*|\s+)"
    rf"(?:(?:a|an|the|this|your|our)\s+)?"
    rf"(?:{'|'.join((*_ACTION_STATE_SUBJECTS, *_LIFECYCLE_STATE_SUBJECTS, *_EXTENDED_ACTION_TARGET_SUBJECTS))})\b",
    re.IGNORECASE,
)
_TERSE_PROGRESSIVE_ACTION_FIRST_PATTERN = re.compile(
    rf"(?:^|[;:—–]\s*|\b(?:and|but|then)\s+)\s*"
    rf"(?:(?:[-+*•✅>]\s*|\d+[.)]\s*|\|\s*)?)"
    rf"(?:(?:already|successfully|now)\s+)*"
    rf"(?:{'|'.join(_PROGRESSIVE_ACTIONS)})\b"
    rf"(?:\s*[:—–-]\s*|\s+)"
    rf"(?:(?:a|an|the|this|your|our)\s+)?"
    rf"(?:{'|'.join((*_ACTION_STATE_SUBJECTS, *_LIFECYCLE_STATE_SUBJECTS, *_EXTENDED_ACTION_TARGET_SUBJECTS))})\b",
    re.IGNORECASE,
)
_TERSE_ACTIVE_ACTION_PATTERN = re.compile(
    rf"(?:^|[;:—–]\s*|\b(?:and|but|then)\s+)\s*"
    rf"(?:(?:[-+*•✅>]\s*|\d+[.)]\s*|\|\s*)?)"
    rf"(?:(?:a|an|the|this|your|our)\s+)?"
    rf"(?:{'|'.join((*_ACTION_STATE_SUBJECTS, *_LIFECYCLE_STATE_SUBJECTS, *_EXTENDED_ACTION_TARGET_SUBJECTS))})\b"
    rf"(?:\s+(?:is|are))?\s+"
    rf"(?:being\s+)?(?:{'|'.join(_PROGRESSIVE_ACTIONS)}|underway|in\s+progress|ongoing)\b",
    re.IGNORECASE,
)
_TERSE_STATE_FIRST_PATTERN = re.compile(
    rf"(?:^|[;:—–]\s*)\s*(?:underway|in\s+progress|ongoing|sorted|all\s+set)"
    rf"\s*[:—–-]\s*(?:(?:a|an|the|this|your|our)\s+)?"
    rf"(?:{'|'.join((*_ACTION_STATE_SUBJECTS, *_LIFECYCLE_STATE_SUBJECTS, *_EXTENDED_ACTION_TARGET_SUBJECTS))})\b",
    re.IGNORECASE,
)
_TERSE_COMPLETION_EUPHEMISM_PATTERN = re.compile(
    r"\b(?:consider\s+it\s+done|"
    r"(?:(?:your|this|the)\s+)?(?:request|cancellation|cancelation|case|ticket|task|action)\s+"
    r"(?:is\s+(?!(?:not|never)\b)(?:all\s+set|sorted)|has\s+been\s+handled)|"
    r"(?:that|this|it)\s+has\s+been\s+handled)\b",
    re.IGNORECASE,
)
_COMPLETION_STATE_EUPHEMISM_PATTERN = re.compile(
    r"\b(?:(?:your|this|the|our)\s+)?"
    r"(?:request|cancellation|cancelation|contract|agreement|subscription|"
    r"membership|case|ticket|task|action|refund|return|replacement)\b"
    r"[^.!?\n]{0,60}?\b(?:"
    r"(?:has|have|is|are|was|were)\s+(?:(?:already|now|successfully)\s+)*"
    r"(?:(?:been\s+)?(?:finali[sz]ed|resolved|actioned)|all\s+done|"
    r"taken\s+care\s+of)|"
    r"(?:is|are|was|were)\s+no\s+longer\s+active|"
    r"(?:finali[sz]ed|resolved|actioned)"
    r")\b",
    re.IGNORECASE,
)
_PERFORMATIVE_ACTION_PATTERN = re.compile(
    rf"\b(?:we|i)\s+(?!(?:do\s+not|don['’]t|never)\b)"
    rf"(?:hereby|formally)\s+{_ACTION_MODIFIER_PATTERN}"
    rf"(?:{'|'.join(_FUTURE_ACTIONS)})\b",
    re.IGNORECASE,
)
_GONE_AHEAD_ACTION_PATTERN = re.compile(
    rf"\b(?:we\s+(?:have\s+gone|went)|i(?:\s+have|['’]ve)\s+gone|i\s+went)"
    rf"\s+ahead\s+and\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}"
    rf"(?:{'|'.join(_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_CONSIDER_COMPLETED_ACTION_PATTERN = re.compile(
    rf"\b(?:you\s+can\s+)?consider\s+"
    rf"(?:(?:a|an|the|this|your|our)\s+)?"
    rf"(?:{'|'.join((*_ACTION_STATE_SUBJECTS, *_LIFECYCLE_STATE_SUBJECTS))})\b"
    rf"[^.!?\n]{{0,80}}?\b"
    rf"(?:{'|'.join((*_COMPLETED_ACTIONS, 'complete', 'done'))})\b",
    re.IGNORECASE,
)
_ACTIVE_STATE_PATTERN = re.compile(
    r"\b(?:investigation|escalation|claim|refund|cancellation|cancelation|replacement|return|request|case|ticket|review)"
    r"\s+(?:is|are)\s+(?:(?:already|now|currently)\s+)*(?:underway|in\s+progress|ongoing)\b",
    re.IGNORECASE,
)
_ACTIVE_INTERNAL_REVIEW_STATE_PATTERN = re.compile(
    r"\b(?:this|the|your|our)\s+(?:matter|case|request|ticket|incident|issue)\s+"
    r"(?:is|are)\s+(?:(?:already|now|currently)\s+)*"
    r"(?!(?:not|never)\b)undergoing\s+(?:an?\s+)?internal\s+review(?:\s+process)?\b",
    re.IGNORECASE,
)
_HANDLING_ACTION_STATE_PATTERN = re.compile(
    rf"\b(?:(?:a|an|the|this|your|our)\s+)?"
    rf"(?:{'|'.join((*_ACTION_STATE_SUBJECTS, *_LIFECYCLE_STATE_SUBJECTS))})\b"
    r"[^.!?\n]{0,80}?\b(?:is|are|was|were)\s+"
    r"(?!(?:not|never)\b)being\s+handled\b|"
    rf"\b(?:we|i)\s+(?:are|am)\s+(?!(?:not|never)\b)taking\s+care\s+of\s+"
    rf"(?:(?:a|an|the|this|your|our)\s+)?"
    rf"(?:{'|'.join((*_ACTION_STATE_SUBJECTS, *_LIFECYCLE_STATE_SUBJECTS))})\b",
    re.IGNORECASE,
)
_TAKEN_CARE_ACTION_PATTERN = re.compile(
    rf"\b(?:we|i)\s+(?:(?:have|had)\s+taken|took)\s+care\s+of\s+"
    rf"(?:(?:a|an|the|this|your|our)\s+)?"
    rf"(?:{'|'.join((*_ACTION_STATE_SUBJECTS, *_LIFECYCLE_STATE_SUBJECTS))})\b",
    re.IGNORECASE,
)
_ACTION_COMPLETION_STATE_PATTERN = re.compile(
    rf"\b(?:a|an|the|this|your|our)\s+{_ACTION_STATE_SUBJECT_PATTERN}\b"
    r"[^.!?\n,;:]{0,80}?\b(?:is|are|was|were)\s+"
    r"(?:(?:already|successfully|now)\s+)*(?:complete|completed|done|successful)\b",
    re.IGNORECASE,
)
_GONE_THROUGH_ACTION_STATE_PATTERN = re.compile(
    rf"\b(?:(?:a|an|the|this|your|our)\s+)?"
    rf"(?:{'|'.join((*_ACTION_STATE_SUBJECTS, *_LIFECYCLE_STATE_SUBJECTS))})\b"
    r"[^.!?\n]{0,80}?\b(?:has|have|had)\s+(?!(?:not|never)\b)gone\s+through\b|"
    rf"\b(?:(?:a|an|the|this|your|our)\s+)?"
    rf"(?:{'|'.join((*_ACTION_STATE_SUBJECTS, *_LIFECYCLE_STATE_SUBJECTS))})\b"
    r"[^.!?\n]{0,80}?\b(?!(?:has|have|had)\s+not\b)went\s+through\b",
    re.IGNORECASE,
)
_CONFIRMED_ACTION_STATE_PATTERN = re.compile(
    rf"\b(?:(?:a|an|the|this|your|our)\s+)?"
    rf"{_CONFIRMATION_ACTION_STATE_SUBJECT_PATTERN}\b"
    r"[^.!?\n]{0,80}?\b(?:is|are|was|were)\s+"
    r"(?!(?:not|never)\b)(?:(?:already|successfully|now)\s+)*confirmed\b",
    re.IGNORECASE,
)
_PERFECT_CONFIRMED_ACTION_STATE_PATTERN = re.compile(
    rf"\b(?:(?:a|an|the|this|your|our)\s+)?"
    rf"{_CONFIRMATION_ACTION_STATE_SUBJECT_PATTERN}\b"
    r"[^.!?\n,;:]{0,80}?\b(?:has|have|had)\s+"
    r"(?!(?:not|never)\b)(?:(?:already|successfully|now)\s+)*been\s+"
    r"(?:(?:already|successfully|now)\s+)*confirmed\b",
    re.IGNORECASE,
)
_CONFIRMING_ACTION_STATE_PATTERN = re.compile(
    rf"\b(?:we\s+are|we['’]re|i\s+am|i['’]m)\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}confirming\s+"
    rf"(?:(?:a|an|the|this|your|our)\s+)?"
    rf"{_CONFIRMATION_ACTION_STATE_SUBJECT_PATTERN}\b",
    re.IGNORECASE,
)
_BARE_CONFIRMING_ACTION_STATE_PATTERN = re.compile(
    rf"\bconfirming\s+"
    rf"(?:(?:a|an|the|this|your|our)\s+)?"
    rf"{_CONFIRMATION_ACTION_STATE_SUBJECT_PATTERN}\b",
    re.IGNORECASE,
)
_PENDING_CONFIRMATION_DIRECT_TAIL_PATTERN = re.compile(
    r"^\s+(?:is|are|remain|remains)\s+"
    r"(?:(?:all|both|still)\s+)*(?:pending|awaiting)\b",
    re.IGNORECASE,
)
_PENDING_CONFIRMATION_COORDINATED_TAIL_PATTERN = re.compile(
    r"^(?:\s*,\s*(?:confirming|guaranteeing)\s+[^,;.!?\n]+)+"
    r"\s*,?\s+and\s+(?:confirming|guaranteeing)\s+[^,;.!?\n]+"
    r"\s+(?:are|remain)\s+(?:(?:all|both|still)\s+)*"
    r"(?:pending|awaiting)\b",
    re.IGNORECASE,
)
_PENDING_CONFIRMATION_REVERSAL_PATTERN = re.compile(
    r"\b(?:complete|completed|done|successful|confirmed)\b",
    re.IGNORECASE,
)
_EXPLICIT_NONCOMPLETION_TAIL_PATTERN = re.compile(
    r"^(?P<scope>[^;:.!?\n]{0,180})\b(?:is|are|remain|remains)\s+"
    r"(?:(?:still|currently)\s+)*(?:"
    r"not\s+(?:confirmed|approved|started|completed|done)|"
    r"unconfirmed|unapproved|"
    r"pending(?:\s+(?:(?:human|manual)\s+)?(?:approval|review|confirmation))?|"
    r"awaiting\s+(?:(?:human|manual)\s+)?(?:approval|review|confirmation)"
    r")\b",
    re.IGNORECASE,
)
_NONCOMPLETION_SCOPE_BREAK_PATTERN = re.compile(
    r"\b(?:but|however|though|although|yet|whereas)\b",
    re.IGNORECASE,
)
_CONFIRMING_ACTION_COMPLETION_PATTERN = re.compile(
    rf"\bconfirming\s+"
    rf"(?:(?:a|an|the|this|your|our)\s+)?"
    rf"{_CONFIRMATION_ACTION_STATE_SUBJECT_PATTERN}\b"
    r"[^.!?\n]{0,80}?\b(?:"
    r"(?:is|are|was|were)\s+(?:(?:already|successfully|now)\s+)*"
    r"(?:complete|completed|done|successful|not\s+pending|no\s+longer\s+pending)|"
    r"(?:has|have)\s+(?:(?:already|successfully|now)\s+)*been\s+"
    r"(?:completed|confirmed|successful)"
    r")\b",
    re.IGNORECASE,
)
_PRONOUN_ACTION_COMPLETION_PATTERN = re.compile(
    r"(?:^|;\s*)(?:it|this|that)\s+"
    r"(?:(?!\b(?:after|could|if|may|might|never|not|once|should|unclear|"
    r"unless|until|when|whether|will|would)\b)[^;.!?\n]){0,100}?"
    r"\b(?:complete|completed|done|successful|confirmed)\b",
    re.IGNORECASE,
)
_CAN_CONFIRM_ACTION_STATE_PATTERN = re.compile(
    rf"\b(?:we|i)\s+can\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}confirm\s+"
    rf"(?:(?:a|an|the|this|your|our)\s+)?"
    rf"{_CONFIRMATION_ACTION_STATE_SUBJECT_PATTERN}\b",
    re.IGNORECASE,
)
_CONFIRM_ACTION_STATE_PATTERN = re.compile(
    rf"\b(?:we|i)\s+{_ACTION_MODIFIER_PATTERN}confirm\s+"
    rf"(?:(?:a|an|the|this|your|our)\s+)?"
    rf"{_CONFIRMATION_ACTION_STATE_SUBJECT_PATTERN}\b",
    re.IGNORECASE,
)
_CONFIRMED_BY_SUPPORT_PATTERN = re.compile(
    rf"\b(?:we\s+have|we['’]ve|i\s+have|i['’]ve|we|i)\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}confirmed\s+"
    rf"(?:(?:a|an|the|this|your|our)\s+)?"
    rf"{_CONFIRMATION_ACTION_STATE_SUBJECT_PATTERN}\b",
    re.IGNORECASE,
)
_FUTURE_CONFIRM_ACTION_STATE_PATTERN = re.compile(
    rf"\b(?:we\s+will|we['’]ll|i\s+will|i['’]ll)\s+"
    rf"(?:(?:soon|shortly|now|immediately)\s+)*confirm\s+"
    rf"(?:(?:a|an|the|this|your|our)\s+)?"
    rf"{_CONFIRMATION_ACTION_STATE_SUBJECT_PATTERN}\b",
    re.IGNORECASE,
)
_FUTURE_PASSIVE_CONFIRM_ACTION_STATE_PATTERN = re.compile(
    rf"\b(?:(?:a|an|the|this|your|our)\s+)?"
    rf"{_CONFIRMATION_ACTION_STATE_SUBJECT_PATTERN}\b"
    r"[^.!?\n,;:]{0,80}?\b(?:will|shall)\s+"
    r"(?!(?:not|never)\b)(?:(?:soon|shortly|now|immediately)\s+)*be\s+"
    r"(?:(?:already|successfully|now)\s+)*confirmed\b",
    re.IGNORECASE,
)
_FUTURE_ACTION_PATTERN = re.compile(
    rf"\b(?:we\s+(?:will|shall)|we['’]ll|i\s+(?:will|shall)|i['’]ll|"
    rf"(?:we|i)\s+(?:definitely|certainly|surely|absolutely)\s+"
    rf"(?:will|shall))\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}"
    rf"(?:{'|'.join(_FUTURE_ACTIONS)})\b",
    re.IGNORECASE,
)
_FUTURE_PROGRESSIVE_ACTION_PATTERN = re.compile(
    rf"\b(?:we\s+(?:will|shall)|we['’]ll|i\s+(?:will|shall)|i['’]ll)\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}be\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}"
    rf"(?:{'|'.join(_PROGRESSIVE_ACTIONS)})\b",
    re.IGNORECASE,
)
_GOING_TO_ACTION_PATTERN = re.compile(
    rf"\b(?:we\s+are|we['’]re|i\s+am|i['’]m)\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}going\s+to\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}"
    rf"(?:{'|'.join(_FUTURE_ACTIONS)})\b",
    re.IGNORECASE,
)
_COMMITMENT_ACTION_PATTERN = re.compile(
    rf"\b(?:we|i)\s+(?:"
    rf"promise\s+to\s+(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}"
    rf"(?:{'|'.join(_FUTURE_ACTIONS)})|"
    rf"commit\s+to\s+(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}"
    rf"(?:{'|'.join(_PROGRESSIVE_ACTIONS)})"
    rf")\b",
    re.IGNORECASE,
)
_PLANNED_ACTION_PATTERN = re.compile(
    rf"\b(?:we|i)\s+(?:"
    rf"(?:intend|plan|expect|aim|undertake|agree)\s+to|"
    rf"(?:are|am)\s+(?:set|due|scheduled)\s+to"
    rf")\s+(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}"
    rf"(?:{'|'.join(_FUTURE_ACTIONS)})\b",
    re.IGNORECASE,
)
_COORDINATED_FUTURE_ACTION_PATTERN = re.compile(
    rf"\b(?:we|i)(?:(?:\s+(?:have|are|am)|['’](?:ve|re|m)))?\s+"
    rf"[^.!?\n]{{1,140}}?"
    rf"\b(?:and|but)\s+"
    rf"(?:(?:not\s+only|therefore|definitely|certainly|surely|[a-z]+ly)\s+)*"
    rf"(?:will|shall)\s+"
    rf"(?:(?:not\s+only|soon|shortly|now|immediately|already|currently|"
    rf"actively|promptly|successfully|just|also|therefore|further|[a-z]+ly)\s+)*"
    rf"(?:{'|'.join(_FUTURE_ACTIONS)})\b",
    re.IGNORECASE,
)
_COORDINATED_FUTURE_PROGRESSIVE_ACTION_PATTERN = re.compile(
    rf"\b(?:we|i)(?:(?:\s+(?:have|are|am)|['’](?:ve|re|m)))?\s+"
    rf"[^.!?\n]{{1,140}}?"
    rf"\b(?:and|but)\s+"
    rf"(?:(?:not\s+only|therefore|definitely|certainly|surely|[a-z]+ly)\s+)*"
    rf"(?:will|shall)\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}be\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}"
    rf"(?:{'|'.join(_PROGRESSIVE_ACTIONS)})\b",
    re.IGNORECASE,
)
_FUTURE_NECESSITY_ACTION_PATTERN = re.compile(
    rf"\b(?:we\s+will|we['’]ll|i\s+will|i['’]ll)\s+"
    rf"(?:(?:soon|shortly|now|immediately)\s+)*(?:need|have)\s+to\s+"
    rf"(?:{'|'.join(_FUTURE_ACTIONS)})\b",
    re.IGNORECASE,
)
_CONTROLLED_SUPPORT_ACTOR_PATTERN = (
    r"(?:our\s+team|(?:an?|the|our)\s+agent|(?:a|the)\s+specialist|"
    r"(?:a|the)\s+human\s+agent|"
    r"(?:our|the)\s+(?:case|conflicts?|legal|billing|fulfillment|warehouse|customer\s+service)\s+team|"
    r"(?:our|the)\s+operations(?:\s+team)?|(?:a|the|our)\s+support\s+representative)"
)
_CONTROLLED_SUPPORT_ACTOR_CONFIRM_PATTERN = re.compile(
    rf"\b{_CONTROLLED_SUPPORT_ACTOR_PATTERN}\s+(?:will|shall)\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}confirm\s+"
    rf"(?:(?:a|an|the|this|your|our)\s+)?"
    rf"{_CONFIRMATION_ACTION_STATE_SUBJECT_PATTERN}\b",
    re.IGNORECASE,
)
_CUSTOMER_CONTACT_ACTOR_PATTERN = (
    rf"(?:we|i|support|customer\s+(?:support|service)|"
    r"(?:the|our)\s+(?:(?:customer\s+)?(?:support|service)\s+)?team|"
    rf"{_CONTROLLED_SUPPORT_ACTOR_PATTERN})"
)
_CUSTOMER_CONTACT_MODAL_PATTERN = (
    rf"(?:(?:we|i)['’]ll|{_CUSTOMER_CONTACT_ACTOR_PATTERN}\s+(?:will|shall))"
)
_FUTURE_UPDATE_PROMISE_PATTERN = re.compile(
    rf"\b{_CUSTOMER_CONTACT_MODAL_PATTERN}\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}"
    r"(?:be\s+able\s+to\s+)?(?:"
    r"(?:provide|send|share|give)\s+"
    r"(?:(?:you|the\s+customer)\s+(?:with\s+)?)?"
    r"(?:an?\s+)?(?:(?:further|additional)\s+)?updates?|"
    r"keep\s+(?:you|the\s+customer)\s+(?:updated|informed)|"
    r"update\s+(?:you|the\s+customer))\b",
    re.IGNORECASE,
)
_FUTURE_CONTACT_PROMISE_PATTERN = re.compile(
    rf"\b{_CUSTOMER_CONTACT_MODAL_PATTERN}\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}"
    r"(?:"
    r"(?:be|get)\s+(?:back\s+)?in\s+touch|"
    r"contact\s+(?:you|the\s+customer)|"
    r"follow[\s\-‐‑‒–—]+up(?:\s+with\s+(?:you|the\s+customer)|(?!\s+with\b))|"
    r"reach(?:\s+back)?\s+out(?:\s+to\s+(?:you|the\s+customer)|(?!\s+to\b))"
    r")\b",
    re.IGNORECASE,
)
_FUTURE_RESPONSE_PROMISE_PATTERN = re.compile(
    rf"\b(?:"
    rf"you\s+can\s+expect\s+(?:an?\s+)?(?:update|reply|response)\s+from\s+us|"
    rf"expect\s+to\s+hear\s+from\s+us(?:\s+shortly)?|"
    rf"you\s+will\s+hear\s+from\s+us(?:\s+shortly)?|"
    rf"{_CUSTOMER_CONTACT_MODAL_PATTERN}\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}"
    rf"(?:get\s+back\s+to\s+you|respond(?:\s+to\s+(?:you|the\s+customer))?"
    rf"(?:\s+with\s+(?:an?\s+)?update)?|"
    rf"circle\s+back|keep\s+you\s+posted|respond(?:\s+to\s+you)?\s+shortly|"
    rf"reply(?:\s+to\s+you)?(?:\s+shortly)?|drop\s+you\s+(?:a\s+)?note|"
    rf"be\s+back\s+in\s+touch|"
    rf"let\s+you\s+know|(?:email|message|notify)\s+you|"
    rf"send\s+you\s+(?:an?\s+)?(?:email|message|update))"
    rf")\b",
    re.IGNORECASE,
)
_FUTURE_PASSIVE_CUSTOMER_CONTACT_PROMISE_PATTERN = re.compile(
    rf"\b(?:you['’]ll|(?:you|the\s+customer)\s+(?:will|shall))\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}(?:"
    r"be\s+(?:contacted|notified|updated|informed)|"
    r"(?:receive|get)\s+(?:an?\s+)?(?:(?:further|additional)\s+)?"
    r"(?:update|reply|response|email|message))\b",
    re.IGNORECASE,
)
_GERMAN_CUSTOMER_CONTACT_PROMISE_PATTERN = re.compile(
    r"\b(?:wir\s+werden|werden\s+wir)\s+(?:"
    r"(?=[^.!?\n]{0,120}\bsie\b)(?:(?!\bnicht\b)[^.!?\n]){0,120}?\b"
    r"(?:kontaktieren|informieren|benachrichtigen|auf\s+dem\s+laufenden\s+halten)|"
    r"(?=[^.!?\n]{0,120}\bihnen\b)(?:(?!\bnicht\b)[^.!?\n]){0,120}?\bantworten|"
    r"(?=[^.!?\n]{0,120}\bihnen\b)(?=[^.!?\n]{0,120}\b(?:update|aktualisierung)\b)"
    r"(?:(?!\bnicht\b)[^.!?\n]){0,120}?\b(?:senden|schicken|geben))\b",
    re.IGNORECASE,
)
_FRENCH_CUSTOMER_CONTACT_PROMISE_PATTERN = re.compile(
    r"\bnous\s+vous\s+(?:contacterons|répondrons|informerons|notifierons|"
    r"tiendrons\s+informé(?:e|es|s)?|enverrons\s+(?:une\s+)?mise\s+à\s+jour)\b",
    re.IGNORECASE,
)
_SPANISH_CUSTOMER_CONTACT_PROMISE_PATTERN = re.compile(
    r"(?<!no\s)\b(?:le\s+(?:contactaremos|responderemos|informaremos|notificaremos|"
    r"mantendremos\s+informad[oa]|enviaremos\s+(?:una\s+)?actualización)|"
    r"nos\s+pondremos\s+en\s+contacto\s+con\s+usted)\b",
    re.IGNORECASE,
)
_ITALIAN_CUSTOMER_CONTACT_PROMISE_PATTERN = re.compile(
    r"(?<!non\s)\b(?:(?:la|le)\s+(?:contatteremo|risponderemo|informeremo|"
    r"notificheremo|terremo\s+aggiornat[oa]|invieremo\s+(?:un\s+)?aggiornamento)|"
    r"ci\s+metteremo\s+in\s+contatto\s+con\s+lei)\b",
    re.IGNORECASE,
)
_ACTION_ARTIFACT_PATTERN = (
    r"(?:(?:export|download)\s+)?(?:link|file|report|copy|data|token|document)|"
    r"(?:export|download)"
)
_FUTURE_ACTION_ARTIFACT_DELIVERY_PROMISE_PATTERN = re.compile(
    rf"\b{_CUSTOMER_CONTACT_MODAL_PATTERN}\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}(?:"
    r"(?:provide|send|share|give|deliver|email|message)\s+"
    r"(?:(?:you|the\s+customer)\s+(?:with\s+)?)?"
    r"(?:(?:the|an?|your|requested|generated)\s+)?"
    rf"(?:{_ACTION_ARTIFACT_PATTERN})|"
    r"make\s+(?:(?:the|an?|your|requested|generated)\s+)?"
    rf"(?:{_ACTION_ARTIFACT_PATTERN})\s+available)\b",
    re.IGNORECASE,
)
_FUTURE_PASSIVE_ACTION_ARTIFACT_DELIVERY_PROMISE_PATTERN = re.compile(
    rf"\b(?:"
    rf"(?:you['’]ll|(?:you|the\s+customer)\s+(?:will|shall))\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}(?:receive|get)\s+"
    r"(?:(?:the|an?|your|requested|generated)\s+)?"
    rf"(?:{_ACTION_ARTIFACT_PATTERN})|"
    r"(?:(?:the|your|requested|generated)\s+)?"
    rf"(?:{_ACTION_ARTIFACT_PATTERN})\s+(?:will|shall)\s+"
    r"(?!(?:not|never)\b)(?:be\s+)?(?:provided|sent|shared|delivered|emailed|made\s+available)"
    r")\b",
    re.IGNORECASE,
)
_CONFIRMABLE_COMPLETION_SUBJECT_PATTERN = (
    rf"(?:{_CONFIRMATION_ACTION_STATE_SUBJECT_PATTERN}|"
    r"(?:(?:account|data|workspace|tenant|requested)\s+){0,2}"
    r"(?:deletion|erasure|export)(?:\s+(?:request|job))?)"
)
_FUTURE_ACTION_COMPLETION_CONFIRMATION_PROMISE_PATTERN = re.compile(
    rf"\b(?:(?:we|i)['’]ll|{_CUSTOMER_CONTACT_ACTOR_PATTERN}\s+(?:will|shall|can))\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}(?:be\s+able\s+to\s+)?confirm\s+"
    r"(?!(?:whether|if)\b)(?:that\s+)?"
    rf"(?:(?:a|an|the|this|your|our)\s+)?{_CONFIRMABLE_COMPLETION_SUBJECT_PATTERN}\b"
    r"[^.!?\n]{0,100}?\b(?:"
    r"(?:is|are|was|were)\s+(?!(?:not|never|unverified|unconfirmed)\b)"
    rf"{_ACTION_MODIFIER_PATTERN}(?:complete|completed|done|successful|no\s+longer\s+pending)|"
    r"(?:has|have)\s+(?!(?:not|never)\b)"
    rf"{_ACTION_MODIFIER_PATTERN}been\s+(?:completed|confirmed|successful))\b",
    re.IGNORECASE,
)
_SAFE_NONCOMPLETION_CONFIRMATION_TAIL_PATTERN = re.compile(
    r"^\s+(?:"
    r"(?:is|are|remain|remains)\s+(?:(?:still|currently)\s+)*(?:"
    r"not\s+(?:complete|completed|confirmed|verified)|"
    r"unconfirmed|unverified|pending)|"
    r"(?:has|have)\s+not\s+been\s+(?:completed|confirmed|verified)"
    r")\s*[.!?]*\s*$",
    re.IGNORECASE,
)
_FUTURE_CONFIRMATION_PATTERNS = frozenset(
    {
        _CAN_CONFIRM_ACTION_STATE_PATTERN,
        _FUTURE_CONFIRM_ACTION_STATE_PATTERN,
        _CONTROLLED_SUPPORT_ACTOR_CONFIRM_PATTERN,
    }
)
_CUSTOMER_CONTACT_PROMISE_PATTERNS = (
    _FUTURE_UPDATE_PROMISE_PATTERN,
    _FUTURE_CONTACT_PROMISE_PATTERN,
    _FUTURE_RESPONSE_PROMISE_PATTERN,
    _FUTURE_PASSIVE_CUSTOMER_CONTACT_PROMISE_PATTERN,
    _GERMAN_CUSTOMER_CONTACT_PROMISE_PATTERN,
    _FRENCH_CUSTOMER_CONTACT_PROMISE_PATTERN,
    _SPANISH_CUSTOMER_CONTACT_PROMISE_PATTERN,
    _ITALIAN_CUSTOMER_CONTACT_PROMISE_PATTERN,
)
_NONCONTINGENT_PENDING_ACTION_PROMISE_PATTERNS = (
    *_CUSTOMER_CONTACT_PROMISE_PATTERNS,
    _FUTURE_ACTION_ARTIFACT_DELIVERY_PROMISE_PATTERN,
    _FUTURE_PASSIVE_ACTION_ARTIFACT_DELIVERY_PROMISE_PATTERN,
    _FUTURE_ACTION_COMPLETION_CONFIRMATION_PROMISE_PATTERN,
)
_PASSIVE_CUSTOMER_CONTACT_PROMISE_PATTERNS = frozenset(
    {
        _FUTURE_PASSIVE_CUSTOMER_CONTACT_PROMISE_PATTERN,
        _FUTURE_PASSIVE_ACTION_ARTIFACT_DELIVERY_PROMISE_PATTERN,
    }
)
_CONTROLLED_SUPPORT_ACTOR_FUTURE_ACTION_PATTERN = re.compile(
    rf"\b{_CONTROLLED_SUPPORT_ACTOR_PATTERN}\s+(?:will|shall)\s+"
    rf"(?:(?:soon|shortly|now|immediately)\s+)*(?:{'|'.join(_FUTURE_ACTIONS)})\b",
    re.IGNORECASE,
)
_OPERATIONS_FUTURE_ACTION_PATTERN = re.compile(
    rf"^\s*operations\s+(?:will|shall)\s+"
    rf"(?:(?:soon|shortly|now|immediately)\s+)*(?:{'|'.join(_FUTURE_ACTIONS)})\b",
    re.IGNORECASE,
)
_FUTURE_PASSIVE_ACTION_PATTERN = re.compile(
    rf"\b(?:a|an|the|this|your|our)\s+{_ACTION_STATE_SUBJECT_PATTERN}\b"
    rf"[^.!?\n]{{0,100}}?\b(?:will|shall)\s+"
    rf"(?:(?:soon|shortly|now|immediately)\s+)*be\s+"
    rf"(?:{'|'.join(_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_FUTURE_LIFECYCLE_PASSIVE_ACTION_PATTERN = re.compile(
    rf"\b(?:a|an|the|this|your|our)\s+(?:{'|'.join(_LIFECYCLE_STATE_SUBJECTS)})\b"
    rf"[^.!?\n]{{0,100}}?\b(?:will|shall)\s+"
    rf"(?:(?:soon|shortly|now|immediately)\s+)*be\s+"
    rf"(?:{'|'.join(_LIFECYCLE_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_SUBSTANTIVE_DISCUSSION_ACTIVE_ACTION_PATTERN = re.compile(
    rf"\b(?:"
    rf"(?:(?:we|i)\s+did\s+|{_CONTROLLED_SUPPORT_ACTOR_PATTERN}\s+did\s+)"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}(?:pause|stop)|"
    rf"(?:(?:we|i)\s+(?:(?:have|had)\s+)?|(?:we|i)['’]ve\s+|"
    rf"{_CONTROLLED_SUPPORT_ACTOR_PATTERN}\s+(?:(?:has|have|had)\s+)?)"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}(?:paused|stopped)|"
    rf"(?:(?:we|i)\s+(?:am|are|was|were)\s+|(?:we|i)['’](?:re|m)\s+|"
    rf"{_CONTROLLED_SUPPORT_ACTOR_PATTERN}\s+(?:is|are|was|were)\s+)"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}(?:pausing|stopping)"
    rf")\s+(?:the\s+)?substantive\s+discussions?\b",
    re.IGNORECASE,
)
_SUBSTANTIVE_DISCUSSION_PASSIVE_ACTION_PATTERN = re.compile(
    r"\b(?:the\s+)?substantive\s+discussions?\b[^.!?\n]{0,60}?\b"
    r"(?:has|have|is|are|was|were|remain|remains|remained)\s+"
    r"(?!(?:not|never)\b)"
    rf"{_ACTION_MODIFIER_PATTERN}(?:been\s+|being\s+)?(?:paused|stopped)\b",
    re.IGNORECASE,
)
_SUBSTANTIVE_DISCUSSION_FUTURE_ACTIVE_ACTION_PATTERN = re.compile(
    rf"\b(?:"
    rf"(?:we|i)\s+(?:(?:will|shall)(?:\s+(?:need\s+to|have\s+to|be))?|"
    rf"{_DEFINITE_ACTION_MODIFIER_PATTERN}\s+(?:will|shall)|"
    rf"(?:am|are)\s+(?:(?:going|planning)\s+to|(?:set|due|scheduled)\s+to)|"
    rf"(?:plan|intend|expect|aim|undertake|agree|promise|need)\s+to|commit\s+to)|"
    rf"(?:we|i)['’]ll(?:\s+(?:need\s+to|have\s+to|be))?|"
    rf"(?:we|i)['’]re\s+(?:(?:going|planning)\s+to|(?:set|due|scheduled)\s+to)|"
    rf"{_CONTROLLED_SUPPORT_ACTOR_PATTERN}\s+(?:(?:will|shall)"
    rf"(?:\s+(?:need\s+to|have\s+to|be))?|"
    rf"{_DEFINITE_ACTION_MODIFIER_PATTERN}\s+(?:will|shall)|"
    rf"(?:is|are)\s+(?:(?:going|planning)\s+to|(?:set|due|scheduled)\s+to)|"
    rf"(?:plans?|intends?|expects?|aims?|undertakes?|agrees?|promises?|needs?)\s+to|"
    rf"commits?\s+to)"
    rf")\s+(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}"
    rf"(?:pause|stop|pausing|stopping)\s+"
    rf"(?:the\s+)?substantive\s+discussions?\b",
    re.IGNORECASE,
)
_SUBSTANTIVE_DISCUSSION_FUTURE_PASSIVE_ACTION_PATTERN = re.compile(
    r"\b(?:the\s+)?substantive\s+discussions?\b[^.!?\n]{0,60}?\b"
    r"(?:will|shall)\s+(?!(?:not|never)\b)"
    rf"{_ACTION_MODIFIER_PATTERN}be\s+(?:paused|stopped)\b",
    re.IGNORECASE,
)

_GERMAN_COMPLETED_PATTERN = re.compile(
    rf"\b(?:wir\s+haben|ich\s+habe)\s+"
    rf"(?![^.!?\n]{{0,120}}\bnicht\b)[^.!?\n]{{0,120}}?\b"
    rf"(?:{'|'.join(_GERMAN_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_GERMAN_PASSIVE_PATTERN = re.compile(
    rf"\b(?:{'|'.join(_GERMAN_ACTION_SUBJECTS)})\b"
    rf"(?![^.!?\n]{{0,120}}\bnicht\b)[^.!?\n]{{0,100}}?\b"
    rf"(?:wurde|wurden|ist|sind)\s+(?:(?:bereits|schon|erfolgreich)\s+)*"
    rf"(?:{'|'.join(_GERMAN_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_GERMAN_FUTURE_PATTERN = re.compile(
    rf"\b(?:wir\s+werden|ich\s+werde)\s+"
    rf"(?![^.!?\n]{{0,120}}\bnicht\b)[^.!?\n]{{0,120}}?\b"
    rf"(?:{'|'.join(_GERMAN_FUTURE_ACTIONS)})\b",
    re.IGNORECASE,
)
_GERMAN_FUTURE_PASSIVE_PATTERN = re.compile(
    rf"\b(?:{'|'.join(_GERMAN_ACTION_SUBJECTS)})\b"
    rf"(?![^.!?\n]{{0,120}}\bnicht\b)[^.!?\n]{{0,100}}?\b"
    rf"(?:wird|werden)\s+(?:(?:bald|kurzfristig|sofort)\s+)*"
    rf"(?:{'|'.join(_GERMAN_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_GERMAN_SIMPLE_ACTION_PATTERN = re.compile(
    r"\b(?:wir|ich)\s+"
    r"(?![^.!?\n]{0,120}\bnicht\b)"
    r"(?:eskalier(?:e|en)|stornier(?:e|en)|kündig(?:e|en)|"
    r"änder(?:e|n)|aktualisier(?:e|en)|erstatt(?:e|en))\b",
    re.IGNORECASE,
)

_FRENCH_COMPLETED_PATTERN = re.compile(
    rf"\bnous\s+avons\s+(?![^.!?\n]{{0,80}}\bpas\b)[^.!?\n]{{0,80}}?\b"
    rf"(?:{'|'.join(_FRENCH_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_FRENCH_PASSIVE_PATTERN = re.compile(
    rf"\b(?:{'|'.join(_FRENCH_ACTION_SUBJECTS)})\b"
    rf"(?![^.!?\n]{{0,120}}\b(?:ne|pas)\b)[^.!?\n]{{0,100}}?\b"
    rf"(?:(?:a|ont)\s+été|(?:est|sont))\s+"
    rf"(?:{'|'.join(_FRENCH_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_FRENCH_FUTURE_PATTERN = re.compile(
    rf"\bnous\s+allons\s+(?![^.!?\n]{{0,80}}\bpas\b)[^.!?\n]{{0,60}}?\b"
    rf"(?:{'|'.join(_FRENCH_FUTURE_ACTIONS)})\b",
    re.IGNORECASE,
)
_FRENCH_FUTURE_PASSIVE_PATTERN = re.compile(
    rf"\b(?:{'|'.join(_FRENCH_ACTION_SUBJECTS)})\b"
    rf"(?![^.!?\n]{{0,120}}\b(?:ne|pas)\b)[^.!?\n]{{0,100}}?\b"
    rf"(?:sera|seront)\s+(?:{'|'.join(_FRENCH_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_FRENCH_SIMPLE_ACTION_PATTERN = re.compile(
    r"\b(?:nous\s+(?![^.!?\n]{0,120}\b(?:ne|pas)\b)"
    r"(?:ouvrons|escaladons|annulons|résilions|modifions|"
    r"mettons\s+à\s+jour|remboursons)|"
    r"j['’](?![^.!?\n]{0,120}\bpas\b)(?:ouvre|escalade|annule|résilie|"
    r"modifie|rembourse))\b",
    re.IGNORECASE,
)
_FRENCH_SIMPLE_FUTURE_ACTION_PATTERN = re.compile(
    r"\b(?:nous\s+(?:ouvrirons|escaladerons|annulerons|résilierons|"
    r"modifierons|rembourserons)|(?:je\s+|j['’])(?:ouvrirai|escaladerai|annulerai|"
    r"résilierai|modifierai|rembourserai))\b",
    re.IGNORECASE,
)

_SPANISH_COMPLETED_PATTERN = re.compile(
    rf"(?<!no\s)\b(?:hemos|he)\s+[^.!?\n]{{0,80}}?\b"
    rf"(?:{'|'.join(_SPANISH_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_SPANISH_PASSIVE_PATTERN = re.compile(
    rf"\b(?:{'|'.join(_SPANISH_ACTION_SUBJECTS)})\b"
    rf"(?![^.!?\n]{{0,120}}\bno\b)[^.!?\n]{{0,100}}?\b"
    rf"(?:ha|han)\s+sido\s+(?:{'|'.join(_SPANISH_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_SPANISH_FUTURE_PATTERN = re.compile(
    rf"(?<!no\s)\b(?:vamos\s+a|voy\s+a)\s+[^.!?\n]{{0,60}}?\b"
    rf"(?:{'|'.join(_SPANISH_FUTURE_ACTIONS)})\b",
    re.IGNORECASE,
)
_SPANISH_FUTURE_PASSIVE_PATTERN = re.compile(
    rf"\b(?:{'|'.join(_SPANISH_ACTION_SUBJECTS)})\b"
    rf"(?![^.!?\n]{{0,120}}\bno\b)[^.!?\n]{{0,100}}?\b"
    rf"(?:será|serán)\s+(?:{'|'.join(_SPANISH_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_SPANISH_SIMPLE_ACTION_PATTERN = re.compile(
    r"(?<!no\s)\b(?:abrimos|abro|escalamos|escalo|cancelamos|cancelo|"
    r"anulamos|anulo|modificamos|modifico|actualizamos|actualizo|"
    r"reembolsamos)\b",
    re.IGNORECASE,
)
_SPANISH_SIMPLE_FUTURE_ACTION_PATTERN = re.compile(
    r"(?<!no\s)\b(?:abriremos|abriré|escalaremos|escalaré|cancelaremos|"
    r"cancelaré|anularemos|anularé|modificaremos|modificaré|actualizaremos|"
    r"actualizaré|reembolsaremos|reembolsaré)\b",
    re.IGNORECASE,
)

_ITALIAN_COMPLETED_PATTERN = re.compile(
    rf"(?<!non\s)\b(?:abbiamo|ho)\s+[^.!?\n]{{0,80}}?\b"
    rf"(?:{'|'.join(_ITALIAN_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_ITALIAN_PASSIVE_PATTERN = re.compile(
    rf"\b(?:{'|'.join(_ITALIAN_ACTION_SUBJECTS)})\b"
    rf"(?![^.!?\n]{{0,120}}\bnon\b)[^.!?\n]{{0,100}}?\b"
    rf"(?:è\s+stat[oa]|sono\s+stat[ei])\s+(?:{'|'.join(_ITALIAN_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_ITALIAN_FUTURE_PATTERN = re.compile(
    rf"(?<!non\s)\b(?:stiamo\s+per|sto\s+per)\s+[^.!?\n]{{0,60}}?\b"
    rf"(?:{'|'.join(_ITALIAN_FUTURE_ACTIONS)})\b",
    re.IGNORECASE,
)
_ITALIAN_FUTURE_PASSIVE_PATTERN = re.compile(
    rf"\b(?:{'|'.join(_ITALIAN_ACTION_SUBJECTS)})\b"
    rf"(?![^.!?\n]{{0,120}}\bnon\b)[^.!?\n]{{0,100}}?\b"
    rf"(?:sarà|saranno)\s+(?:{'|'.join(_ITALIAN_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_ITALIAN_SIMPLE_ACTION_PATTERN = re.compile(
    r"(?<!non\s)\b(?:apriamo|apro|escaliamo|escalo|annulliamo|annullo|"
    r"cancelliamo|cancello|modifichiamo|modifico|aggiorniamo|aggiorno|"
    r"rimborsiamo)\b",
    re.IGNORECASE,
)
_ITALIAN_SIMPLE_FUTURE_ACTION_PATTERN = re.compile(
    r"(?<!non\s)\b(?:apriremo|aprirò|escaleremo|escalerò|annulleremo|"
    r"annullerò|cancelleremo|cancellerò|modificheremo|modificherò|"
    r"aggiorneremo|aggiornerò|rimborseremo|rimborserò)\b",
    re.IGNORECASE,
)
_MARKDOWN_TABLE_ACTION_PATTERN = re.compile(
    rf"(?:^|\|)\s*(?:{_ACTION_STATE_SUBJECT_PATTERN})\s*\|\s*"
    rf"(?:(?:has|have|is|are|was|were)\s+)?"
    rf"(?:(?:already|successfully|now|currently)\s+)*"
    rf"(?:been\s+|being\s+)?(?:{'|'.join((*_COMPLETED_ACTIONS, *_PROGRESSIVE_ACTIONS))})\b",
    re.IGNORECASE,
)
_ANSWER_UNIT_PATTERN = re.compile(r"[^.!?\n]+(?:[.!?]+(?:[*_`~\]\)]|</[A-Za-z][^>\n]{0,60}>)*|(?=\n)|$)")
_CLAIM_PATTERNS = (
    _PROGRESSIVE_ACTION_PATTERN,
    _PRE_AUX_PROGRESSIVE_ACTION_PATTERN,
    _COORDINATED_PROGRESSIVE_ACTION_PATTERN,
    _PERFECT_ACTION_PATTERN,
    _PRE_AUX_PERFECT_ACTION_PATTERN,
    _COORDINATED_PERFECT_ACTION_PATTERN,
    _PAST_ACTION_PATTERN,
    _SENSITIVE_NOTE_ACTION_PATTERN,
    _PASSIVE_ACTION_PATTERN,
    _BARE_PASSIVE_ACTION_PATTERN,
    _BARE_LIFECYCLE_PASSIVE_ACTION_PATTERN,
    _TARGET_MUTATION_PASSIVE_ACTION_PATTERN,
    _LIFECYCLE_PASSIVE_ACTION_PATTERN,
    _SUBSTANTIVE_DISCUSSION_ACTIVE_ACTION_PATTERN,
    _SUBSTANTIVE_DISCUSSION_PASSIVE_ACTION_PATTERN,
    _NARROW_LIFECYCLE_CANCELLATION_PATTERN,
    _TERSE_COMPLETED_ACTION_PATTERN,
    _TERSE_ACTION_FIRST_PATTERN,
    _TERSE_PROGRESSIVE_ACTION_FIRST_PATTERN,
    _TERSE_ACTIVE_ACTION_PATTERN,
    _TERSE_STATE_FIRST_PATTERN,
    _TERSE_COMPLETION_EUPHEMISM_PATTERN,
    _COMPLETION_STATE_EUPHEMISM_PATTERN,
    _PERFORMATIVE_ACTION_PATTERN,
    _GONE_AHEAD_ACTION_PATTERN,
    _CONSIDER_COMPLETED_ACTION_PATTERN,
    _ACTIVE_STATE_PATTERN,
    _ACTIVE_INTERNAL_REVIEW_STATE_PATTERN,
    _HANDLING_ACTION_STATE_PATTERN,
    _TAKEN_CARE_ACTION_PATTERN,
    _ACTION_COMPLETION_STATE_PATTERN,
    _GONE_THROUGH_ACTION_STATE_PATTERN,
    _CONFIRMED_ACTION_STATE_PATTERN,
    _PERFECT_CONFIRMED_ACTION_STATE_PATTERN,
    _CONFIRMING_ACTION_STATE_PATTERN,
    _BARE_CONFIRMING_ACTION_STATE_PATTERN,
    _CONFIRMING_ACTION_COMPLETION_PATTERN,
    _PRONOUN_ACTION_COMPLETION_PATTERN,
    _CONFIRM_ACTION_STATE_PATTERN,
    _CONFIRMED_BY_SUPPORT_PATTERN,
    _GERMAN_COMPLETED_PATTERN,
    _GERMAN_PASSIVE_PATTERN,
    _FRENCH_COMPLETED_PATTERN,
    _FRENCH_PASSIVE_PATTERN,
    _SPANISH_COMPLETED_PATTERN,
    _SPANISH_PASSIVE_PATTERN,
    _ITALIAN_COMPLETED_PATTERN,
    _ITALIAN_PASSIVE_PATTERN,
    _MARKDOWN_TABLE_ACTION_PATTERN,
)
_FUTURE_CLAIM_PATTERNS = (
    _FUTURE_ACTION_PATTERN,
    _FUTURE_PROGRESSIVE_ACTION_PATTERN,
    _GOING_TO_ACTION_PATTERN,
    _COMMITMENT_ACTION_PATTERN,
    _PLANNED_ACTION_PATTERN,
    _COORDINATED_FUTURE_ACTION_PATTERN,
    _COORDINATED_FUTURE_PROGRESSIVE_ACTION_PATTERN,
    _FUTURE_NECESSITY_ACTION_PATTERN,
    _CONTROLLED_SUPPORT_ACTOR_FUTURE_ACTION_PATTERN,
    _OPERATIONS_FUTURE_ACTION_PATTERN,
    _FUTURE_PASSIVE_ACTION_PATTERN,
    _FUTURE_LIFECYCLE_PASSIVE_ACTION_PATTERN,
    _BARE_FUTURE_PASSIVE_ACTION_PATTERN,
    _BARE_FUTURE_LIFECYCLE_PASSIVE_ACTION_PATTERN,
    _TARGET_MUTATION_FUTURE_PASSIVE_ACTION_PATTERN,
    _SUBSTANTIVE_DISCUSSION_FUTURE_ACTIVE_ACTION_PATTERN,
    _SUBSTANTIVE_DISCUSSION_FUTURE_PASSIVE_ACTION_PATTERN,
    _GERMAN_FUTURE_PATTERN,
    _GERMAN_FUTURE_PASSIVE_PATTERN,
    _GERMAN_SIMPLE_ACTION_PATTERN,
    _FRENCH_FUTURE_PATTERN,
    _FRENCH_FUTURE_PASSIVE_PATTERN,
    _FRENCH_SIMPLE_ACTION_PATTERN,
    _FRENCH_SIMPLE_FUTURE_ACTION_PATTERN,
    _SPANISH_FUTURE_PATTERN,
    _SPANISH_FUTURE_PASSIVE_PATTERN,
    _SPANISH_SIMPLE_ACTION_PATTERN,
    _SPANISH_SIMPLE_FUTURE_ACTION_PATTERN,
    _ITALIAN_FUTURE_PATTERN,
    _ITALIAN_FUTURE_PASSIVE_PATTERN,
    _ITALIAN_SIMPLE_ACTION_PATTERN,
    _ITALIAN_SIMPLE_FUTURE_ACTION_PATTERN,
    _FUTURE_CONFIRM_ACTION_STATE_PATTERN,
    _FUTURE_PASSIVE_CONFIRM_ACTION_STATE_PATTERN,
    _CONTROLLED_SUPPORT_ACTOR_CONFIRM_PATTERN,
    _CAN_CONFIRM_ACTION_STATE_PATTERN,
    _FUTURE_CONTACT_PROMISE_PATTERN,
    _FUTURE_RESPONSE_PROMISE_PATTERN,
)
_SUCCESS_ELIGIBLE_CLAIM_PATTERNS = frozenset(
    {
        _PERFECT_ACTION_PATTERN,
        _PRE_AUX_PERFECT_ACTION_PATTERN,
        _COORDINATED_PERFECT_ACTION_PATTERN,
        _PAST_ACTION_PATTERN,
        _SENSITIVE_NOTE_ACTION_PATTERN,
        _PASSIVE_ACTION_PATTERN,
        _BARE_PASSIVE_ACTION_PATTERN,
        _BARE_LIFECYCLE_PASSIVE_ACTION_PATTERN,
        _TARGET_MUTATION_PASSIVE_ACTION_PATTERN,
        _LIFECYCLE_PASSIVE_ACTION_PATTERN,
        _NARROW_LIFECYCLE_CANCELLATION_PATTERN,
        _TERSE_COMPLETED_ACTION_PATTERN,
        _TERSE_ACTION_FIRST_PATTERN,
        _TERSE_COMPLETION_EUPHEMISM_PATTERN,
        _GONE_AHEAD_ACTION_PATTERN,
        _CONSIDER_COMPLETED_ACTION_PATTERN,
        _ACTION_COMPLETION_STATE_PATTERN,
        _GONE_THROUGH_ACTION_STATE_PATTERN,
        _TAKEN_CARE_ACTION_PATTERN,
        _CONFIRMED_ACTION_STATE_PATTERN,
        _PERFECT_CONFIRMED_ACTION_STATE_PATTERN,
        _CONFIRMING_ACTION_COMPLETION_PATTERN,
        _PRONOUN_ACTION_COMPLETION_PATTERN,
        _CONFIRMED_BY_SUPPORT_PATTERN,
        _GERMAN_COMPLETED_PATTERN,
        _GERMAN_PASSIVE_PATTERN,
        _FRENCH_COMPLETED_PATTERN,
        _FRENCH_PASSIVE_PATTERN,
        _SPANISH_COMPLETED_PATTERN,
        _SPANISH_PASSIVE_PATTERN,
        _ITALIAN_COMPLETED_PATTERN,
        _ITALIAN_PASSIVE_PATTERN,
        _MARKDOWN_TABLE_ACTION_PATTERN,
    }
)
_CONDITION_MARKERS = (
    r"after",
    r"before",
    r"if",
    r"once",
    r"until",
    r"when",
    r"nachdem",
    r"nach",
    r"sobald",
    r"falls",
    r"wenn",
    r"après",
    r"avant",
    r"si",
    r"lorsque",
    r"une\s+fois",
    r"después\s+de\s+que",
    r"antes\s+de\s+que",
    r"cuando",
    r"una\s+vez",
    r"después\s+de",
    r"dopo\s+che",
    r"dopo",
    r"prima\s+che",
    r"quando",
    r"una\s+volta",
)
_CONTINGENCY_TERMS = (
    r"approv\w*",
    r"authoriz\w*",
    r"availab\w*",
    r"confirm\w*",
    r"review\w*",
    r"verif\w*",
    r"genehmig\w*",
    r"freigegeb\w*",
    r"freigabe\w*",
    r"bestätig\w*",
    r"geprüf\w*",
    r"überprüf\w*",
    r"approuv\w*",
    r"approb\w*",
    r"autoris\w*",
    r"confirm\w*",
    r"vérifi\w*",
    r"examin\w*",
    r"aprobad\w*",
    r"aprobaci\w*",
    r"autorizad\w*",
    r"confirmad\w*",
    r"revisad\w*",
    r"verificad\w*",
    r"approvat\w*",
    r"approvaz\w*",
    r"autorizzat\w*",
    r"confermat\w*",
    r"revisionat\w*",
    r"verificat\w*",
)
_FUTURE_CONDITION_PREFIX_PATTERN = re.compile(
    rf"\b(?:{'|'.join(_CONDITION_MARKERS)})\s*$",
    re.IGNORECASE,
)
_FUTURE_CONTINGENCY_PREFIX_PATTERN = re.compile(
    rf"(?:\b(?:{'|'.join(_CONDITION_MARKERS)})\b[^.!?\n]{{0,120}}"
    rf"\b(?:{'|'.join(_CONTINGENCY_TERMS)})\b[^.!?\n]{{0,40}}$|"
    r"\bsubject\s+to\s+(?:(?:human|final|required)\s+)*"
    r"(?:approval|authorization|confirmation|review|verification)"
    r"[^.!?\n]{0,40}$)",
    re.IGNORECASE,
)
_FUTURE_CONTINGENCY_SUFFIX_PATTERN = re.compile(
    rf"^\s*(?P<scope>[^.!?\n]{{0,80}}?)"
    rf"(?P<condition>\b(?:{'|'.join(_CONDITION_MARKERS)})\b)[^.!?\n]{{0,120}}"
    rf"\b(?:{'|'.join(_CONTINGENCY_TERMS)})\b",
    re.IGNORECASE,
)
_UNSAFE_FUTURE_CONTINGENCY_PATTERN = re.compile(
    r"\b(?:before|until|expir\w*|withdraw\w*|refus\w*|laps\w*|revok\w*|"
    r"rescind\w*|reject\w*|deni\w*|declin\w*|fail\w*|unsuccessful|"
    r"runs?\s+out|cannot\s+be\s+completed|not|never|without|"
    r"unavailable|unapproved|unauthorized|unconfirmed|unverified)\b",
    re.IGNORECASE,
)
_UNRELATED_CLAUSE_PATTERN = re.compile(
    r"[,;:]|\b(?:and|but|then|while|whereas|und|aber|dann|et|mais|puis|y|pero|entonces|e|ma|poi)\b",
    re.IGNORECASE,
)
_SAFE_NEGATIVE_EPISTEMIC_PREFIX_PATTERN = re.compile(
    r"(?:"
    r"\b(?:we|i)\s+(?:"
    r"(?:(?:are|am)\s+(?:unable|not\s+able)\s+to|"
    r"cannot|can['’]t|do\s+not|don['’]t|will\s+not|won['’]t)"
    r"(?:\s+[a-z]+ly){0,3}\s+(?:promise|guarantee|confirm)|"
    r"(?:deny|dispute))"
    r"(?:\s+(?:that|whether|if)|\s*[:,])?|"
    r"\b(?:it\s+is|it['’]s|it\s+remains)\s+"
    r"(?:(?:still|currently)\s+)*unclear\s+whether|"
    r"\bthere\s+is\s+no\s+evidence(?:\s+to\s+(?:show|suggest|confirm))?"
    r"(?:\s+that|\s*[:,])?|"
    r"\b(?:wir|ich)\s+(?:können|kann)\s+nicht\s+"
    r"(?:versprechen|garantieren|bestätigen)\s*,?\s*(?:dass|ob)|"
    r"\b(?:nous\s+ne\s+pouvons|je\s+ne\s+peux)\s+pas\s+"
    r"(?:promettre|garantir|confirmer)\s+(?:que|si)|"
    r"\b(?:no\s+podemos|no\s+puedo)\s+"
    r"(?:prometer|garantizar|confirmar)\s+(?:que|si)|"
    r"\b(?:non\s+possiamo|non\s+posso)\s+"
    r"(?:promettere|garantire|confermare)\s+(?:che|se)"
    r")\s*$",
    re.IGNORECASE,
)
_TRACKING_TOOL_DOMAIN_PATTERN = re.compile(
    r"(?:tracking|shipment|parcel|delivery)",
    re.IGNORECASE,
)
_TRACKING_TOOL_READ_PATTERN = re.compile(
    r"(?:lookup|look[_ -]?up|status|track)",
    re.IGNORECASE,
)
_TRACKING_ID_FACT_PATHS = frozenset(
    {
        "tracking",
        "trackingid",
        "trackingnumber",
        "trackingcode",
    }
)
_TRACKING_CHECK_OBJECT_PATTERN = re.compile(
    r"^\s+(?:(?:the|your|this|our)\s+)?"
    r"(?:(?:order|shipment|parcel|delivery|carrier)\s+)?"
    r"(?:tracking(?:\s+(?:status|details|information|record|number))?|"
    r"shipment\s+status|parcel\s+status|delivery\s+status)\b",
    re.IGNORECASE,
)
_PENDING_TRACKING_READ_PATTERN = re.compile(
    r"(?:\b(?:check|lookup|look\s+up|track|fetch|retrieve)\b[^.!?\n]{0,80}"
    r"\b(?:tracking|shipment\s+status|parcel\s+status|delivery\s+status)\b|"
    r"\b(?:tracking|shipment\s+status|parcel\s+status|delivery\s+status)\b"
    r"[^.!?\n]{0,80}\b(?:check|lookup|look\s+up|track|fetch|retrieve)\b)",
    re.IGNORECASE,
)
_COORDINATED_ACTION_TAIL_PATTERN = re.compile(
    rf"(?:[,;:]?\s*\b(?:and|but|then)\b|[,;:])\s*"
    rf"(?:(?:we|i)(?:['’](?:ve|re))?\s+)?"
    rf"(?:(?:have|are|will)\s+)?{_ACTION_MODIFIER_PATTERN}"
    rf"(?:{'|'.join((*_PROGRESSIVE_ACTIONS, *_COMPLETED_ACTIONS, *_FUTURE_ACTIONS))})\b",
    re.IGNORECASE,
)
_NEGATIVE_CONFIRMATION_SCOPE_BREAK_PATTERN = re.compile(
    r"[;:.!?]|\b(?:but|however|whereas)\b",
    re.IGNORECASE,
)
_POSITIVE_CONTRAST_PATTERN = re.compile(
    r";|\b(?:but|however|whereas|yet)\b",
    re.IGNORECASE,
)
_EXTERNAL_STATE_ATTRIBUTION_PATTERN = re.compile(
    r"\b(?:by\s+(?:the\s+)?(?:customer|client|user|court|judge|carrier|"
    r"shipping\s+(?:carrier|provider)|tracking\s+feed|carrier\s+tracking\s+feed|"
    r"opposing\s+counsel|outside\s+counsel|dhl|ups|fedex|dpd|gls|usps|"
    r"royal\s+mail|merchant|seller|vendor)|"
    r"automatically\s+(?:at|on|upon)\s+(?:expiry|expiration|checkout))\b",
    re.IGNORECASE,
)
_EXTERNAL_CUSTOMER_CONTACT_ATTRIBUTION_PATTERN = re.compile(
    r"^[^.!?\n]{0,100}\b(?:by|from)\s+(?:the\s+)?(?:customer|client|user|court|judge|carrier|"
    r"shipping\s+(?:carrier|provider)|opposing\s+counsel|outside\s+counsel|"
    r"dhl|ups|fedex|dpd|gls|usps|royal\s+mail|merchant|seller|vendor)\b",
    re.IGNORECASE,
)
_EXTERNAL_CUSTOMER_CONTACT_TARGET_PATTERN = re.compile(
    r"\b(?:(?:with|to)\s+(?:the\s+)?(?:carrier|vendor|court)|"
    r"(?:on|about|regarding)\s+(?:the\s+)?(?:carrier|vendor|court)\b)\b",
    re.IGNORECASE,
)
_CUSTOMER_CONTACT_TARGET_PATTERN = re.compile(
    r"\b(?:with|to)\s+(?:you|the\s+customer|customer)\b",
    re.IGNORECASE,
)
_EXTERNAL_STATE_PASSIVE_PATTERNS = frozenset(
    {
        _PASSIVE_ACTION_PATTERN,
        _BARE_PASSIVE_ACTION_PATTERN,
        _BARE_LIFECYCLE_PASSIVE_ACTION_PATTERN,
        _TARGET_MUTATION_PASSIVE_ACTION_PATTERN,
        _LIFECYCLE_PASSIVE_ACTION_PATTERN,
        _NARROW_LIFECYCLE_CANCELLATION_PATTERN,
        _SUBSTANTIVE_DISCUSSION_PASSIVE_ACTION_PATTERN,
    }
)


@dataclass(frozen=True)
class PendingActionClaimCheck:
    """Result consumed before a generated customer draft is accepted."""

    pending_actions: tuple[str, ...] = ()
    claims: tuple[str, ...] = ()

    @property
    def blocked(self) -> bool:
        return bool(self.pending_actions and self.claims)


@dataclass(frozen=True)
class _SuccessfulActionRecord:
    action_token: str
    object_tokens: frozenset[str]
    target_qualifiers: frozenset[str]
    proof_identifiers: tuple[str, ...]
    requires_identifier: bool


_TEXT_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
_HTML_FORMATTING_TAG_PATTERN = re.compile(r"</?[A-Za-z][^>\n]{0,120}>")
_MARKUP_FORMATTING_CHARACTERS = frozenset("*_`~[]")
_MARKDOWN_PRESENTATION_PREFIX_PATTERN = re.compile(
    r"(?m)^\s*(?:(?:>\s*)*(?:[-*+]|\d+[.)]|\d+\s*-?)\s*\[[ xX]\]\s*|"
    r"(?:>\s*)+|#{1,6}\s+|\+\s+|\|\s*)"
)
_ACTION_TOKEN_PATTERNS = (
    (re.compile(r"cancel(?:led|ed|ling|ing|lation|ation)?$"), "cancel"),
    (re.compile(r"terminat(?:e|ed|ing|ion)?$"), "cancel"),
    (re.compile(r"rescind(?:ed|ing)?$"), "cancel"),
    (re.compile(r"approv(?:e|ed|ing|al)?$"), "approve"),
    (re.compile(r"archiv(?:e|ed|ing)?$"), "archive"),
    (re.compile(r"delet(?:e|ed|ing|ion)?$"), "delete"),
    (re.compile(r"escalat(?:e|ed|ing|ion)?$"), "escalate"),
    (re.compile(r"investigat(?:e|ed|ing|ion)?$"), "investigate"),
    (re.compile(r"initiat(?:e|ed|ing|ion)?$"), "initiate"),
    (re.compile(r"check(?:ed|ing)?$"), "check"),
    (re.compile(r"clos(?:e|ed|ing)?$"), "close"),
    (re.compile(r"open(?:ed|ing)?$"), "open"),
    (re.compile(r"submit(?:ted|ting)?$"), "submit"),
    (re.compile(r"process(?:ed|ing)?$"), "process"),
    (re.compile(r"review(?:ed|ing)?$"), "review"),
    (re.compile(r"contact(?:ed|ing)?$"), "contact"),
    (re.compile(r"notif(?:y|ied|ying|ication)?$"), "notify"),
    (re.compile(r"arrang(?:e|ed|ing|ement)?$"), "arrange"),
    (re.compile(r"schedul(?:e|ed|ing)?$"), "schedule"),
    (re.compile(r"issu(?:e|ed|ing)?$"), "issue"),
    (re.compile(r"refund(?:ed|ing)?$"), "refund"),
    (re.compile(r"chang(?:e|ed|ing)?$"), "update"),
    (re.compile(r"updat(?:e|ed|ing)?$"), "update"),
    (re.compile(r"dispatch(?:ed|ing)?$"), "dispatch"),
    (re.compile(r"reship(?:ped|ping)?$"), "reship"),
    (re.compile(r"replac(?:e|ed|ing|ement)?$"), "replace"),
    (re.compile(r"creat(?:e|ed|ing|ion)?$"), "create"),
    (re.compile(r"start(?:ed|ing)?$"), "start"),
    (re.compile(r"beg(?:in|an|un|inning)?$"), "start"),
    (re.compile(r"activat(?:e|ed|ing|ion)?$"), "activate"),
    (re.compile(r"authoriz(?:e|ed|ing|ation)?$"), "authorize"),
    (re.compile(r"prioriti[sz](?:e|ed|ing|ation)?$"), "prioritize"),
    (re.compile(r"forward(?:ed|ing)?$"), "forward"),
    (
        re.compile(
            r"(?:record(?:ed|ing)?|log(?:ged|ging)?|note(?:d|ing)?|"
            r"flag(?:ged|ging)?|mark(?:ed|ing)?)$"
        ),
        "record",
    ),
    (re.compile(r"(?:eroffn(?:en|et)|offn(?:en|et))$"), "open"),
    (re.compile(r"eskalier(?:en|t)$"), "escalate"),
    (re.compile(r"(?:stornier(?:en|t)|kundig(?:en|t))$"), "cancel"),
    (re.compile(r"(?:ander(?:n|t)|aktualisier(?:en|t))$"), "update"),
    (re.compile(r"(?:(?:zu)?ruck)?erstatt(?:en|et)$"), "refund"),
    (re.compile(r"(?:ouvrir|ouvert|ouverte|ouverts|ouvertes)$"), "open"),
    (re.compile(r"escalad(?:er|e|ee|es|ees)$"), "escalate"),
    (re.compile(r"(?:annul|resili)(?:er|e|ee|es|ees)$"), "cancel"),
    (re.compile(r"modifi(?:er|e|ee|es|ees)$"), "update"),
    (re.compile(r"rembours(?:er|e|ee|es|ees)$"), "refund"),
    (re.compile(r"(?:abrir|abiert[oa]s?)$"), "open"),
    (re.compile(r"(?:escalar|escalad[oa]s?)$"), "escalate"),
    (re.compile(r"(?:cancelar|cancelad[oa]s?|anular|anulad[oa]s?)$"), "cancel"),
    (re.compile(r"(?:modificar|modificad[oa]s?|actualizar|actualizad[oa]s?)$"), "update"),
    (re.compile(r"(?:reembolsar|reembolsad[oa]s?)$"), "refund"),
    (re.compile(r"(?:aprire|apert[oa])$"), "open"),
    (re.compile(r"(?:escalare|escalat[oa])$"), "escalate"),
    (re.compile(r"(?:annullare|annullat[oa]|cancellare|cancellat[oa])$"), "cancel"),
    (re.compile(r"(?:modificare|modificat[oa]|aggiornare|aggiornat[oa])$"), "update"),
    (re.compile(r"(?:rimborsare|rimborsat[oa])$"), "refund"),
)
_ACTION_OBJECT_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "agent",
        "action",
        "automatic",
        "automatically",
        "customer",
        "for",
        "human",
        "i",
        "in",
        "of",
        "our",
        "runbook",
        "support",
        "the",
        "this",
        "to",
        "tool",
        "we",
        "webhook",
        "your",
    }
)
_ACTION_OBJECT_ALIASES = {
    "accounts": "account",
    "agreement": "contract",
    "agreements": "contract",
    "appointments": "appointment",
    "bookings": "booking",
    "cases": "case",
    "conflicts": "conflict",
    "contracts": "contract",
    "investigations": "investigation",
    "orders": "order",
    "profiles": "profile",
    "refunds": "refund",
    "requests": "request",
    "reservations": "reservation",
    "subscriptions": "subscription",
    "tickets": "ticket",
    "bestellung": "order",
    "commande": "order",
    "pedido": "order",
    "ordine": "order",
    "konflikt": "conflict",
    "conflit": "conflict",
    "conflicto": "conflict",
    "conflitto": "conflict",
    "frist": "deadline",
    "delai": "deadline",
    "plazo": "deadline",
    "scadenza": "deadline",
}
_ACTION_TARGET_OBJECT_TOKENS = frozenset(
    {
        "address",
        "case",
        "claim",
        "conflict",
        "contract",
        "deadline",
        "delivery",
        "incident",
        "investigation",
        "matter",
        "membership",
        "order",
        "refund",
        "request",
        "return",
        "review",
        "shipment",
        "subscription",
        "ticket",
    }
)
_GENERIC_ACTION_OBJECT_TOKENS = frozenset(
    {
        "case",
        "incident",
        "matter",
        "request",
        "review",
    }
)
_PROOF_IDENTIFIER_KEY_PATTERN = re.compile(
    r"^(?:id|reference|ticket[_-]?reference|"
    r"confirmation[_-]?(?:number|code)|"
    r"(?:ticket|order|case|action)[_-]?id)$",
    re.IGNORECASE,
)
_PROOF_IDENTIFIER_NORMALIZED_KEYS = frozenset(
    {
        "actionid",
        "caseid",
        "confirmationcode",
        "confirmationnumber",
        "id",
        "orderid",
        "reference",
        "ticketid",
        "ticketreference",
    }
)
_PROOF_OPAQUE_VALUE_KEY_PATTERN = re.compile(
    r"^(?:contact|(?:contact[_-]?)?email|receipt[_-]?file|tracking[_-]?(?:code|id|number))$",
    re.IGNORECASE,
)
_BOUNDED_PROOF_VALUE_KEYS = frozenset({"action", "status"})
_TERMINAL_PROOF_VALUE_KEYS = frozenset({"action", "outcome", "result", "state", "status"})
_HTTP_STATUS_PROOF_KEYS = frozenset(
    {
        "httpcode",
        "httpresponsecode",
        "httpstatus",
        "responsecode",
        "responsestatus",
        "responsestatuscode",
        "resultcode",
        "statuscode",
        "httpstatuscode",
    }
)
_STRICT_SCALAR_TERMINAL_PROOF_KEYS = frozenset({"action", "outcome", "state", "status"})
_POSITIVE_TERMINAL_PROOF_VALUE_PATTERN = re.compile(
    r"^(?:ok|success(?:ful)?|complete(?:d)?|done|applied|executed|confirmed|"
    r"clear(?:ed)?|verified|resolved|closed|passed|active|inactive|"
    r"initiated|checked|escalated|investigated|opened|submitted|processed|"
    r"reviewed|contacted|arranged|scheduled|issued|refunded|cancelled|canceled|"
    r"terminated|rescinded|approved|archived|deleted|"
    r"changed|updated|dispatched|reshipped|replaced|created|started|begun|"
    r"activated|authorized|prioritized|prioritised|forwarded|recorded|logged)$",
    re.IGNORECASE,
)
_NEGATIVE_PROOF_KEY_PATTERN = re.compile(
    r"^(?:error|fail|failure|reject|deni|declin|refus)",
    re.IGNORECASE,
)
_FALSE_SUCCESS_PROOF_KEYS = frozenset(
    {
        "applied",
        "completed",
        "confirmed",
        "executed",
        "isapplied",
        "iscompleted",
        "isconfirmed",
        "isexecuted",
        "isok",
        "issuccess",
        "issuccessful",
        "operationsucceeded",
        "applicationapplied",
        "responseok",
        "responsesuccess",
        "succeeded",
        "success",
        "successful",
        "webhookcompleted",
    }
)
_PROOF_SEMANTIC_VALUE_KEYS = frozenset(
    {
        "action",
        "detail",
        "details",
        "message",
        "outcome",
        "reason",
        "result",
        "state",
        "status",
    }
)
_PROOF_PAYLOAD_MAX_DEPTH = 5
_PROOF_PAYLOAD_MAX_ITEMS = 200
_PROOF_PAYLOAD_MAX_STRING_LENGTH = 8_192
_PROOF_PAYLOAD_MAX_TEXT_LENGTH = 65_536
_NEGATIVE_PROOF_VALUE_PATTERN = re.compile(
    r"\b(?:fail(?:ed|ure)?|error|reject(?:ed|ion)?|denied|declined|refused|"
    r"skipped|blocked|pending|queued|processing|attempted|partial|unknown|"
    r"waiting|deferred|accepted|enqueued|retry(?:ing)?(?:[_\s-]+later)?|"
    r"will\b[^.!?\n]{0,40}\blater|not[_\s-]+yet[_\s-]+complete(?:d)?|"
    r"timeout|timed[_\s-]?out|awaiting|requires?[_\s-]+approval|"
    r"in[_\s-]?progress|not[_\s-]?started|not[_\s-]?done|no[_\s-]?action|"
    r"no[_\s-]?op|noop|unconfirmed|invalid|expired|withdrawn|"
    r"not[_\s-]?found|missing|absent|"
    r"unsuccessful|revoked|rescinded|not[_\s-]?(?:ok|applied|completed|"
    r"successful|confirmed|executed)|http[_\s-]?[45][0-9]{2})\b",
    re.IGNORECASE,
)
_PROOF_ACTION_CLAUSE_BOUNDARY_PATTERN = re.compile(
    r"[,;:.!?\n]|\b(?:after|and|before|but|however|then|whereas)\b",
    re.IGNORECASE,
)
_NEGATED_PROOF_ACTION_PREFIX_PATTERN = re.compile(
    r"(?:"
    r"\b(?:did|do|does|will|would|should|could|can|have|has|had|is|are|was|were|may|might)"
    r"\s+not\s+(?!(?:only|just|merely)\b)|"
    r"\b(?:didn|don|doesn|won|wouldn|shouldn|couldn|haven|hasn|hadn|isn|aren|wasn|weren|can)"
    r"['’]t\s+(?!(?:only|just|merely)\b)|"
    r"\b(?:cannot|unable\s+to|failed\s+to|refused\s+to)\b|"
    r"\bnot\s+(?!(?:only|just|merely)\b)|"
    r"\bwithout\b(?!\s+(?:delay|error|failure)\b)|"
    r"\bno\s+(?:action|cancellation|case|change|order|refund|request|ticket)\b|"
    r"\b(?:nobody|no\s+one|neither|never)\b|"
    r"\b(?:nicht|pas|non)\b"
    r")[^,;:.!?\n]{0,100}$",
    re.IGNORECASE,
)
_NEGATED_PROOF_ACTION_CONTINUATION_PATTERN = re.compile(
    r"\bnot\b(?!\s+(?:only|just|merely)\b)"
    r"(?:(?:\s|,)*(?:actually|currently|in\s+fact|presently|really))*(?:\s|,)*$",
    re.IGNORECASE,
)
_NEGATED_PROOF_ACTION_SUFFIX_PATTERN = re.compile(
    r"^\s*(?:"
    r"(?:did|does|do|has|have|had|is|are|was|were)\s+not\s+occur\b|"
    r"(?:didn|doesn|don|hasn|haven|hadn|isn|aren|wasn|weren)['’]t\s+occur\b|"
    r"no\s+(?:ticket|order|refund|action|request|case|change|cancellation)\b|"
    r"(?:was|were|is|are)\s+not\s+(?:done|completed|successful)\b"
    r")",
    re.IGNORECASE,
)
_NONTERMINAL_PROOF_ACTION_PREFIX_PATTERN = re.compile(
    r"(?:"
    r"\b(?:will|would|shall|may|might|can|could|must|should)\b|"
    r"\bought\s+to\b|"
    r"\b(?:is|are|was|were)\s+(?:being|going\s+to\s+be|scheduled\s+to\s+be|"
    r"about\s+to\s+be|expected\s+to\s+be|intended\s+to\s+be|planned\s+to\s+be|"
    r"due\s+to\s+be|set\s+to\s+be|ready\s+to\s+be|queued\s+to\s+be|"
    r"supposed\s+to\s+be|awaiting|in\s+(?:the\s+)?process\s+of\s+being)\b|"
    r"\b(?:expected|intended|planned|due|set|ready|queued|supposed)\s+to\s+be\b|"
    r"\b(?:awaiting|in\s+(?:the\s+)?process\s+of\s+being)\b|"
    r"\b(?:needs?|remains?|has\s+yet)\s+to\s+be\b|"
    r"\b(?:debe|deve|devrait|doit|dovrebbe|k[oö]nnte|muss|podr[ií]a|sera|sar[aà]|"
    r"ser[aàá]|soll|verr[aà]|wird)\b|"
    r"\best\s+en\s+train\s+d['’]?[eê]tre\b|"
    r"\best[aá]\s+siendo\b|"
    r"\bsta\s+per\s+essere\b|"
    r"\bva\s+(?:a\s+ser|[aà]\s+essere|[eê]tre)\b"
    r")[^,;:.!?\n]{0,100}$",
    re.IGNORECASE,
)
_UNCERTAIN_PROOF_ACTION_PREFIX_PATTERN = re.compile(
    r"(?:"
    r"\bto\s+be\b|"
    r"\bplease\s+have\b|"
    r"\b(?:is|are|was|were)\s+(?:currently\s+)?getting\b|"
    r"\b(?:appears?|seems?)\b|"
    r"\b(?:is|are|was|were)\s+(?:apparently\s+)?believed\b|"
    r"\b(?:allegedly|apparently|perhaps|possibly|presumably|purportedly|reportedly|supposedly)\b|"
    r"\blogs?\s+(?:appear\s+to\s+)?suggest\b|"
    r"\b(?:almost|nearly)\b|"
    r"\bprevented\s+from\s+being\b"
    r")[^,;:.!?\n]{0,120}$",
    re.IGNORECASE,
)
_NEGATED_PROOF_RESULT_WORDS = {
    "cancel": re.compile(r"\b(?:uncancelled|uncanceled|unterminated)\b", re.IGNORECASE),
    "issue": re.compile(r"\bunissued\b", re.IGNORECASE),
    "open": re.compile(r"\bunopened\b", re.IGNORECASE),
    "refund": re.compile(r"\bunrefunded\b", re.IGNORECASE),
}
_PROOF_ACTION_REVERSAL_PATTERNS = {
    "activate": re.compile(r"\b(?:deactivated|disabled|frozen|suspended)\b", re.IGNORECASE),
    "cancel": re.compile(
        r"\b(?:reinstated|restored|reactivated|renewed|reversed|rolled\s+back|undone)\b",
        re.IGNORECASE,
    ),
    "close": re.compile(r"\b(?:reopened|restored|undone)\b", re.IGNORECASE),
    "create": re.compile(r"\b(?:deleted|removed|undone)\b", re.IGNORECASE),
    "delete": re.compile(r"\b(?:recovered|restored|undeleted)\b", re.IGNORECASE),
    "issue": re.compile(r"\b(?:cancelled|canceled|recalled|revoked|reversed|retracted|voided)\b", re.IGNORECASE),
    "open": re.compile(
        r"\b(?:archived|closed|deleted|purged|removed|reverted|withdrawn)\b",
        re.IGNORECASE,
    ),
    "refund": re.compile(
        r"\b(?:cancelled|canceled|chargeback|clawed\s+back|recalled|revoked|reversed|"
        r"retracted|rolled\s+back|taken\s+back|voided)\b",
        re.IGNORECASE,
    ),
    "schedule": re.compile(r"\b(?:cancelled|canceled|removed|unscheduled)\b", re.IGNORECASE),
    "update": re.compile(
        r"\b(?:changed\s+back|reset|reverted|restored|rolled\s+back)\b",
        re.IGNORECASE,
    ),
}
_PROOF_ACTION_TARGET_TOKENS = _ACTION_TARGET_OBJECT_TOKENS | frozenset(
    {
        "account",
        "appointment",
        "booking",
        "browser",
        "court",
        "coupon",
        "door",
        "email",
        "invoice",
        "hearing",
        "meeting",
        "payment",
        "profile",
        "reservation",
        "software",
        "voucher",
        "window",
        "workspace",
    }
)
_EXTERNAL_PROOF_ACTOR_PATTERN = re.compile(
    r"(?:^\s*(?:(?:a|an|our|the)\s+)?"
    r"(?P<actor>bank|buyer|carrier|client|consumer|courier|customer|end\s+user|external\s+counsel|"
    r"merchant|opposing\s+counsel|outside\s+counsel|purchaser|recipient|requester|seller|supplier|"
    r"third\s+party|user|vendor|warehouse)\b"
    r"(?:(?:['’]s\s+(?:agent|bot|representative|team)\b)|"
    r"(?!['’]s\b|-requested\b|\s+(?:service|success|support)\b))|"
    r"\bby\s+(?!(?:(?:a|an|the)\s+)?(?:automated\s+workflow|automation|customer\s+support|"
    r"our\s+(?:automated\s+workflow|automation|team)|support(?:\s+(?:agent|team))?|system)\b)"
    r"(?:(?:a|an|the)\s+)?[A-Za-z][A-Za-z0-9_.-]*(?:\s+[A-Za-z][A-Za-z0-9_.-]*){0,3}\b)",
    re.IGNORECASE,
)
_INVALIDATING_PROOF_NARRATIVE_PATTERN = re.compile(
    r"\?\s*no\b|"
    r"\bor\s+(?:perhaps|maybe)\s+not\b|"
    r"(?:—|–|-)\s*not\s+really\b|"
    r"\b(?:but|however)\b[^.!?\n]{0,80}\b(?:cannot|can['’]t|could\s+not|couldn['’]t)\s+confirm\b|"
    r"\b(?:dry[-_\s]*run|preview|sandbox|simulation|simulated)\b[^.!?\n]{0,40}\bonly\b|"
    r"\blocally\b[^.!?\n]{0,80}\bnot\s+(?:persisted|saved|stored)\b|"
    r"\b(?:transaction|operation|result)\b[^.!?\n]{0,50}\brolled\s+back\b",
    re.IGNORECASE,
)
_CONDITIONAL_PROOF_ACTION_PREFIX_PATTERN = re.compile(
    r"(?:^|[.!?]\s*)\s*(?:if|unless|when|assuming|provided\s+that)\b[^.!?\n]{0,180}$",
    re.IGNORECASE,
)
_NEGATING_PROOF_FLAG_PATTERN = re.compile(
    r"^(?:dryrun|mocked|previewonly|rollback|rolledback|sandboxonly|simulation|simulationmode|"
    r"simulated|testmode|reverted|reversed)$|"
    r"^(?:could|may|might|should|would|will)[a-z0-9]+$",
    re.IGNORECASE,
)
_NEUTRAL_PROOF_FLAG_KEYS = frozenset({"debugflag", "featureflag"})
_GENERIC_ACTION_DENIAL_PATTERN = re.compile(
    r"\b(?:nothing|none)\b[^.!?\n]{0,50}\b(?:done|completed|executed|applied)|"
    r"\b(?:action|operation|request)\b[^.!?\n]{0,40}\b(?:did\s+not|didn['’]t)\s+"
    r"(?:happen|occur|succeed)|"
    r"\b(?:cannot|can['’]t|could\s+not|couldn['’]t)\s+confirm\b[^.!?\n]{0,50}"
    r"\b(?:completion|completed|done|executed|applied)\b",
    re.IGNORECASE,
)
_HARMLESS_PROOF_METADATA_PATTERN = re.compile(
    r"^\s*(?:after\s+(?:a\s+)?(?:retry|failed\s+first\s+attempt)|"
    r"no\s+error(?:\s+occurred)?|not\s+pending|"
    r"(?:the\s+)?operation\s+is\s+not\s+pending\s+(?:anymore|any\s+longer)|"
    r"retry\s+(?:attempts?|count)\s*:\s*\d+|without\s+(?:delay|error|failure))\s*[.!]?\s*$",
    re.IGNORECASE,
)
_PROOF_METADATA_URL_PATTERN = re.compile(r"^https?://\S+$", re.IGNORECASE)
_FALSE_SEMANTIC_STRING_VALUES = frozenset(
    {"0", "false", "n", "never", "no", "none", "notcompleted", "notdone", "null", "off"}
)
_FALSE_ACTION_FLAG_PATTERN = re.compile(
    r"(?P<label>[A-Za-z][A-Za-z0-9_ -]{0,80}?)[\"']?\s*[:=]\s*[\"']?"
    r"(?P<value>false|n|null|never|no|0|off|failed|failure|not[_ -]?(?:done|completed|opened))\b",
    re.IGNORECASE,
)
_FALSE_ACTION_FLAG_VALUES = frozenset(
    {
        "0",
        "false",
        "failed",
        "failure",
        "n",
        "never",
        "no",
        "notcompleted",
        "notdone",
        "notopened",
        "off",
    }
)
_TRUE_ACTION_FLAG_VALUES = frozenset(
    {"1", "complete", "completed", "done", "on", "success", "successful", "true", "yes"}
)
_GENERIC_POSITIVE_PROOF_NARRATIVE_PATTERN = re.compile(
    r"\b(?:complete(?:d)?|done|success(?:ful|fully)?|applied|executed|confirmed|resolved)\b",
    re.IGNORECASE,
)
_GENERIC_NONTERMINAL_PROOF_NARRATIVE_PATTERN = re.compile(
    r"\b(?:accepted|after\s+(?:a\s+)?(?:retry|failed\s+first\s+attempt)|awaiting|"
    r"deferred|enqueued|not\s+pending|pending|planned|queued|retry(?:ing)?|scheduled|"
    r"will\b|shall\b|going\s+to|not\s+yet|later|soon|shortly)\b",
    re.IGNORECASE,
)
_PROOF_COMPLETED_ACTION_TOKEN_PATTERN = re.compile(
    rf"(?:{'|'.join((*_COMPLETED_ACTIONS, *_LIFECYCLE_COMPLETED_ACTIONS, *_CUSTOM_COMPLETED_ACTIONS, *_GERMAN_COMPLETED_ACTIONS, *_FRENCH_COMPLETED_ACTIONS, *_SPANISH_COMPLETED_ACTIONS, *_ITALIAN_COMPLETED_ACTIONS))})",
    re.IGNORECASE,
)
_LOCAL_CLAUSE_BOUNDARY_PATTERN = re.compile(
    r",\s*(?:(?:and|but|then|however|yet|while)\s*,?\s*)|"
    r";\s*(?:(?:however|but|yet|while)\s*,?\s*)?|"
    r"\s*[:—–]\s*|"
    r"\s+(?:and|but)\s+(?=(?:we|i)\b)",
    re.IGNORECASE,
)
_INTRA_MATCH_COORDINATOR_PATTERN = re.compile(r"\b(?:and|but)\b", re.IGNORECASE)
_LEADING_ENTITY_QUALIFIER_PATTERN = re.compile(
    r"\b(?:first|second|third|fourth|fifth|last|next|other|previous)\s+$",
    re.IGNORECASE,
)
_COORDINATED_SUCCESS_SCOPE_PATTERNS = frozenset(
    {
        _COORDINATED_PROGRESSIVE_ACTION_PATTERN,
        _COORDINATED_PERFECT_ACTION_PATTERN,
        _COORDINATED_FUTURE_ACTION_PATTERN,
        _COORDINATED_FUTURE_PROGRESSIVE_ACTION_PATTERN,
    }
)
_FUTURE_TAIL_PRIMARY_PATTERNS = frozenset(
    {
        _FUTURE_ACTION_PATTERN,
        _GOING_TO_ACTION_PATTERN,
        _COMMITMENT_ACTION_PATTERN,
        _COORDINATED_FUTURE_ACTION_PATTERN,
        _CONTROLLED_SUPPORT_ACTOR_FUTURE_ACTION_PATTERN,
        _OPERATIONS_FUTURE_ACTION_PATTERN,
    }
)
_FOLLOWUP_COMPLETED_ACTION_PATTERN = re.compile(
    rf"(?:{'|'.join(_COMPLETED_ACTIONS)})",
    re.IGNORECASE,
)
_FOLLOWUP_PROGRESSIVE_ACTION_PATTERN = re.compile(
    rf"(?:{'|'.join(_PROGRESSIVE_ACTIONS)})",
    re.IGNORECASE,
)
_FOLLOWUP_FUTURE_ACTION_PATTERN = re.compile(
    rf"(?:{'|'.join(_FUTURE_ACTIONS)})",
    re.IGNORECASE,
)
_FOLLOWUP_ACTION_PATTERN = re.compile(
    rf"(?P<separator>"
    rf"\s*,\s*(?:(?:and|but|then|while|yet)\s+|however\s*,?\s*)?|"
    rf"\s+(?:and|but|then|before|after|while|yet)\s+|"
    rf"\s*[;:—–]\s*(?:(?:and|but|then|while|yet)\s+|however\s*,?\s*)?"
    rf")"
    rf"(?:(?P<actor>we|i)\s+)?"
    rf"(?:(?P<aux>(?:(?:are|am)\s+going\s+to|promise\s+to|commit\s+to|"
    rf"will|shall|have|has|had|are|am|is|was|were))\s+)?"
    rf"(?:(?:be|been)\s+)?"
    rf"{_ACTION_MODIFIER_PATTERN}"
    rf"(?P<action>{'|'.join((*_PROGRESSIVE_ACTIONS, *_COMPLETED_ACTIONS, *_FUTURE_ACTIONS))})\b",
    re.IGNORECASE,
)


def _action_claim_shadow(value: str) -> str:
    """Remove bounded presentation markup without changing string offsets."""
    characters = list(value)
    for match in _HTML_FORMATTING_TAG_PATTERN.finditer(value):
        characters[match.start() : match.end()] = " " * (match.end() - match.start())
    for match in _MARKDOWN_PRESENTATION_PREFIX_PATTERN.finditer(value):
        characters[match.start() : match.end()] = " " * (match.end() - match.start())
    return "".join(
        " " if character in _MARKUP_FORMATTING_CHARACTERS or character in "\r\n" else character
        for character in characters
    )


def _normalized_token_text(token: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", token.casefold())
        if not unicodedata.combining(character)
    )


def _text_tokens(value: Any) -> tuple[str, ...]:
    text = re.sub(
        r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|"
        r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])",
        " ",
        str(value or ""),
    )
    return tuple(token.casefold() for token in _TEXT_TOKEN_PATTERN.findall(text))


def _canonical_action_token(token: str) -> str:
    token = _normalized_token_text(token)
    for pattern, canonical in _ACTION_TOKEN_PATTERNS:
        if pattern.fullmatch(token):
            return canonical
    return ""


def _normalized_object_token(token: str) -> str:
    normalized = _normalized_token_text(token)
    return _ACTION_OBJECT_ALIASES.get(normalized, normalized)


def _action_signature(action: Mapping[str, Any]) -> tuple[str, frozenset[str]]:
    fallback: tuple[str, frozenset[str]] = ("", frozenset())
    for raw_text in (action.get("name"), action.get("label")):
        tokens = _text_tokens(raw_text)
        for index, token in enumerate(tokens):
            action_token = _canonical_action_token(token)
            if not action_token:
                continue
            object_tokens = frozenset(
                _normalized_object_token(candidate)
                for candidate_index, candidate in enumerate(tokens)
                if candidate_index != index
                and (
                    (candidate not in _ACTION_OBJECT_STOPWORDS and len(candidate) >= 2)
                    or (
                        len(candidate) == 1
                        and candidate.isalnum()
                        and candidate_index > 0
                        and _normalized_object_token(tokens[candidate_index - 1]) in _ACTION_TARGET_OBJECT_TOKENS
                    )
                )
            )
            if object_tokens:
                return action_token, object_tokens
            if not fallback[0]:
                fallback = (action_token, object_tokens)
            break
    return fallback


_ENTITY_QUALIFIER_ALIASES = {
    "a": "first",
    "b": "second",
    "c": "third",
    "1": "first",
    "2": "second",
    "3": "third",
}


def _target_qualifier_tokens(value: Any) -> frozenset[str]:
    """Extract bounded entity qualifiers such as the ``A`` in ``order A``."""
    tokens = _text_tokens(value)
    qualifiers: set[str] = set()
    qualifier_stopwords = _ACTION_OBJECT_STOPWORDS | {
        "are",
        "been",
        "being",
        "confirmation",
        "has",
        "have",
        "is",
        "number",
        "reference",
        "under",
        "was",
        "were",
        "will",
    }
    ordinal_qualifiers = {
        "first",
        "second",
        "third",
        "fourth",
        "fifth",
        "last",
        "next",
        "other",
        "previous",
    }
    for index, token in enumerate(tokens):
        if _normalized_object_token(token) not in _ACTION_TARGET_OBJECT_TOKENS:
            continue
        candidate_indices = [index - 1, index + 1]
        if index + 2 < len(tokens) and _normalized_object_token(tokens[index + 1]) in {
            "id",
            "number",
            "reference",
        }:
            candidate_indices.append(index + 2)
        for candidate_index in candidate_indices:
            if candidate_index < 0 or candidate_index >= len(tokens):
                continue
            candidate = _normalized_object_token(tokens[candidate_index])
            candidate = _ENTITY_QUALIFIER_ALIASES.get(candidate, candidate)
            if candidate_index < index and candidate not in ordinal_qualifiers:
                continue
            if (
                candidate in qualifier_stopwords and not (len(candidate) == 1 and candidate.isalnum())
            ) or candidate in _ACTION_TARGET_OBJECT_TOKENS:
                continue
            if candidate not in _GENERIC_ACTION_OBJECT_TOKENS:
                qualifiers.add(candidate)
    return frozenset(qualifiers)


def _action_target_qualifiers(action: Mapping[str, Any]) -> frozenset[str]:
    qualifiers: set[str] = set()
    for raw_text in (action.get("name"), action.get("label")):
        qualifiers.update(_target_qualifier_tokens(raw_text))
    return frozenset(qualifiers)


def _expected_entity_qualifiers(expected_objects: frozenset[str]) -> frozenset[str]:
    return frozenset(
        _ENTITY_QUALIFIER_ALIASES.get(token, token)
        for token in expected_objects
        if token
        in {
            "first",
            "second",
            "third",
            "fourth",
            "fifth",
            "last",
            "next",
            "other",
            "previous",
        }
        or token.isdigit()
        or (len(token) == 1 and token.isalnum())
    )


def _structured_proof_entity_qualifiers(
    key: Any,
    value: Any,
    *,
    expected_targets: frozenset[str],
) -> frozenset[str]:
    """Extract a target qualifier stored separately from an action-state key."""
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return frozenset()
    key_tokens = frozenset(_normalized_object_token(token) for token in _text_tokens(key))
    if not key_tokens.intersection(expected_targets) and not key_tokens.intersection({"entity", "target"}):
        return frozenset()
    qualifiers = set(_target_qualifier_tokens(value))
    normalized_value = _normalized_object_token(str(value).strip())
    canonical_value = _ENTITY_QUALIFIER_ALIASES.get(normalized_value, normalized_value)
    if (
        canonical_value
        in {
            "first",
            "second",
            "third",
            "fourth",
            "fifth",
            "last",
            "next",
            "other",
            "previous",
        }
        or canonical_value.isdigit()
        or (len(normalized_value) == 1 and normalized_value.isalnum())
    ):
        qualifiers.add(canonical_value)
    return frozenset(qualifiers)


def _proof_identifiers(proof: Any) -> tuple[str, ...]:
    if isinstance(proof, Mapping):
        candidates = (value for key, value in proof.items() if _PROOF_IDENTIFIER_KEY_PATTERN.search(str(key)))
    elif isinstance(proof, (str, int)) and not isinstance(proof, bool):
        candidates = (proof,)
    else:
        return ()
    identifiers: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, (str, int)) or isinstance(candidate, bool):
            continue
        identifier = str(candidate).strip()
        if len(identifier) >= 4 and identifier not in identifiers:
            identifiers.append(identifier[:240])
    return tuple(identifiers[:20])


def _proof_key_requires_true(value: Any) -> bool:
    tokens = tuple(_normalized_token_text(token) for token in _text_tokens(value))
    success_tokens = {
        "applied",
        "complete",
        "completed",
        "confirmed",
        "done",
        "executed",
        "ok",
        "resolved",
        "succeed",
        "succeeded",
        "success",
        "successful",
        "verified",
    }
    return bool(
        tokens
        and (
            tokens[-1] in success_tokens
            or (tokens[-1] == "flag" and any(token in success_tokens for token in tokens[:-1]))
        )
    )


def _negative_proof_key_has_value(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    if isinstance(value, str):
        normalized = re.sub(r"[_ -]+", "", value.strip().casefold())
        return normalized not in {
            "",
            "0",
            "false",
            "n",
            "na",
            "no",
            "noerror",
            "noerroroccurred",
            "nofailuresdetected",
            "none",
            "notapplicable",
            "null",
        }
    if isinstance(value, Mapping):
        return any(_negative_proof_key_has_value(nested) for nested in value.values())
    if isinstance(value, (list, tuple)):
        return any(_negative_proof_key_has_value(nested) for nested in value)
    return bool(value)


def _has_meaningful_bounded_proof(
    proof: Any,
    *,
    action_bound: bool = False,
) -> bool:
    if not isinstance(proof, Mapping) or not proof:
        return False
    stack: list[tuple[Any, int, str, bool]] = [(proof, 0, "", False)]
    seen_containers: set[int] = set()
    inspected_items = 0
    inspected_text_length = 0
    while stack:
        value, depth, parent_key, semantic_context = stack.pop()
        if isinstance(value, str):
            if parent_key in _PROOF_IDENTIFIER_NORMALIZED_KEYS:
                continue
            inspected_text_length += len(value)
            if len(value) > _PROOF_PAYLOAD_MAX_STRING_LENGTH or inspected_text_length > _PROOF_PAYLOAD_MAX_TEXT_LENGTH:
                return False
            if _HARMLESS_PROOF_METADATA_PATTERN.fullmatch(value):
                continue
            normalized_scalar = re.sub(r"[_ -]+", "", value.strip().casefold())
            if semantic_context and normalized_scalar in _FALSE_SEMANTIC_STRING_VALUES:
                return False
            if parent_key not in _TERMINAL_PROOF_VALUE_KEYS and not (
                action_bound and parent_key in _PROOF_SEMANTIC_VALUE_KEYS
            ):
                normalized_value = re.sub(
                    r"[_-]+",
                    " ",
                    re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value),
                )
                if _NEGATIVE_PROOF_VALUE_PATTERN.search(normalized_value):
                    return False
            continue
        if not isinstance(value, (Mapping, list, tuple)):
            if semantic_context and value is False:
                return False
            continue
        if depth > _PROOF_PAYLOAD_MAX_DEPTH or id(value) in seen_containers:
            return False
        seen_containers.add(id(value))
        if isinstance(value, Mapping):
            items = tuple(value.items())
            inspected_items += len(items)
            if inspected_items > _PROOF_PAYLOAD_MAX_ITEMS:
                return False
            for key, nested_value in items:
                raw_key = str(key)
                normalized_key = re.sub(
                    r"[^a-z0-9]",
                    "",
                    raw_key.lower().rsplit(".", 1)[-1],
                )
                if normalized_key in {"isok", "ok"} and nested_value is not True:
                    return False
                http_status_key = normalized_key in _HTTP_STATUS_PROOF_KEYS or (
                    normalized_key == "code"
                    and (
                        parent_key in {"http", "response", "webhookresponse"}
                        or raw_key.lower().startswith(("http.", "response.", "webhookresponse."))
                    )
                )
                if http_status_key:
                    if not isinstance(nested_value, (str, int)) or isinstance(nested_value, bool):
                        return False
                    raw_status_code = str(nested_value).strip()
                    if not raw_status_code.isdigit() or int(raw_status_code) not in {200, 201, 204}:
                        return False
                nested_semantic_context = (
                    semantic_context
                    or normalized_key in (_PROOF_SEMANTIC_VALUE_KEYS | _TERMINAL_PROOF_VALUE_KEYS)
                    or raw_key.casefold().startswith(("result.", "outcome.", "response."))
                )
                if normalized_key == "exitcode":
                    if not isinstance(nested_value, (str, int)) or isinstance(nested_value, bool):
                        return False
                    raw_exit_code = str(nested_value).strip()
                    if not raw_exit_code.isdigit() or int(raw_exit_code) != 0:
                        return False
                if normalized_key in {"exitstatus", "returncode"}:
                    if not isinstance(nested_value, (str, int)) or isinstance(nested_value, bool):
                        return False
                    raw_process_code = str(nested_value).strip()
                    if not raw_process_code.isdigit() or int(raw_process_code) != 0:
                        return False
                if normalized_key == "code" and nested_semantic_context:
                    if not isinstance(nested_value, (str, int)) or isinstance(nested_value, bool):
                        return False
                    raw_result_code = str(nested_value).strip()
                    if not raw_result_code.isdigit() or int(raw_result_code) not in {0, 200, 201, 204}:
                        return False
                if normalized_key == "response" and nested_semantic_context and nested_value is False:
                    return False
                if _NEGATIVE_PROOF_KEY_PATTERN.search(normalized_key) and _negative_proof_key_has_value(nested_value):
                    return False
                if _NEGATING_PROOF_FLAG_PATTERN.fullmatch(normalized_key):
                    if _negative_proof_key_has_value(nested_value):
                        return False
                    continue
                if (
                    normalized_key in _FALSE_SUCCESS_PROOF_KEYS or _proof_key_requires_true(key)
                ) and nested_value is not True:
                    return False
                if normalized_key in _TERMINAL_PROOF_VALUE_KEYS:
                    if isinstance(nested_value, str):
                        normalized_terminal_value = re.sub(r"[_-]+", " ", nested_value.strip())
                        if not _POSITIVE_TERMINAL_PROOF_VALUE_PATTERN.fullmatch(normalized_terminal_value):
                            return False
                    elif isinstance(nested_value, int) and not isinstance(nested_value, bool):
                        if nested_value not in {200, 201, 204}:
                            return False
                    elif normalized_key in _STRICT_SCALAR_TERMINAL_PROOF_KEYS:
                        return False
                    elif not isinstance(nested_value, (Mapping, list, tuple)):
                        return False
                if normalized_key in _PROOF_SEMANTIC_VALUE_KEYS and nested_value is False:
                    return False
                stack.append((nested_value, depth + 1, normalized_key, nested_semantic_context))
        else:
            inspected_items += len(value)
            if inspected_items > _PROOF_PAYLOAD_MAX_ITEMS:
                return False
            stack.extend((nested_value, depth + 1, parent_key, semantic_context) for nested_value in value)
    for key, value in proof.items():
        normalized_key = re.sub(
            r"[^a-z0-9]",
            "",
            str(key).lower().rsplit(".", 1)[-1],
        )
        if _PROOF_IDENTIFIER_KEY_PATTERN.search(str(key)):
            if isinstance(value, (str, int)) and not isinstance(value, bool) and 4 <= len(str(value).strip()) <= 240:
                return True
            continue
        if normalized_key in {"isok", "ok"} and value is True:
            return True
        if normalized_key in _BOUNDED_PROOF_VALUE_KEYS:
            if isinstance(value, str) and 1 <= len(value.strip()) <= 240:
                return True
    return False


_GENERIC_TERMINAL_PROOF_VALUES = frozenset(
    {
        "ok",
        "success",
        "successful",
        "complete",
        "completed",
        "done",
        "applied",
        "executed",
        "confirmed",
        "verified",
        "resolved",
        "closed",
        "passed",
    }
)
_SPECIAL_TERMINAL_PROOF_ACTIONS = {
    "active": "activate",
    "inactive": "activate",
    "clear": "check",
    "cleared": "check",
}


def _proof_semantic_action_is_compatible(
    semantic_action: str,
    *,
    expected_action: str,
    expected_objects: frozenset[str],
) -> bool:
    if semantic_action == expected_action:
        return True
    return bool(expected_action == "issue" and semantic_action == "refund" and "refund" in expected_objects)


def _proof_action_surface_is_compatible(
    value: str,
    *,
    expected_action: str,
    expected_objects: frozenset[str],
) -> bool:
    action, objects = _action_signature({"name": value})
    if not action or not _proof_semantic_action_is_compatible(
        action,
        expected_action=expected_action,
        expected_objects=expected_objects,
    ):
        return False
    expected_targets = expected_objects.intersection(_PROOF_ACTION_TARGET_TOKENS) - _GENERIC_ACTION_OBJECT_TOKENS
    actual_targets = objects.intersection(_PROOF_ACTION_TARGET_TOKENS) - _GENERIC_ACTION_OBJECT_TOKENS
    if expected_targets and actual_targets and expected_targets.isdisjoint(actual_targets):
        return False
    expected_qualifiers = {
        _ENTITY_QUALIFIER_ALIASES.get(token, token)
        for token in expected_objects
        if token
        in {
            "first",
            "second",
            "third",
            "fourth",
            "fifth",
            "last",
            "next",
            "other",
            "previous",
        }
        or token.isdigit()
        or (len(token) == 1 and token.isalnum())
    }
    actual_qualifiers = _target_qualifier_tokens(value)
    return not (expected_qualifiers and actual_qualifiers and expected_qualifiers.isdisjoint(actual_qualifiers))


def _proof_action_clause_is_compatible(
    value: str,
    *,
    semantic_action: str,
    expected_action: str,
    expected_objects: frozenset[str],
) -> bool:
    if not _proof_semantic_action_is_compatible(
        semantic_action,
        expected_action=expected_action,
        expected_objects=expected_objects,
    ):
        return False
    expected_targets = expected_objects.intersection(_PROOF_ACTION_TARGET_TOKENS) - _GENERIC_ACTION_OBJECT_TOKENS
    tokens = _text_tokens(value)
    normalized_tokens = tuple(_normalized_object_token(token) for token in tokens)
    action_indices = tuple(
        index for index, token in enumerate(tokens) if _canonical_action_token(token) == semantic_action
    )
    action_index = action_indices[-1] if action_indices else -1
    before_target_entries = [
        (index, token)
        for index, token in enumerate(normalized_tokens)
        if index < action_index and token in _PROOF_ACTION_TARGET_TOKENS
    ]
    after_target_entries = [
        (index, token)
        for index, token in enumerate(normalized_tokens)
        if index > action_index and token in _PROOF_ACTION_TARGET_TOKENS
    ]
    self_target = (
        normalized_tokens[action_index]
        if 0 <= action_index < len(normalized_tokens) and normalized_tokens[action_index] in _PROOF_ACTION_TARGET_TOKENS
        else ""
    )
    primary_target = before_target_entries[-1][1] if before_target_entries else ""
    for (left_index, left_target), (right_index, _right_target) in zip(
        before_target_entries,
        before_target_entries[1:],
        strict=False,
    ):
        relation_tokens = normalized_tokens[left_index + 1 : right_index]
        if (
            any(token in {"about", "concerning", "for", "regarding"} for token in relation_tokens)
            or "associated" in relation_tokens
            or "connected" in relation_tokens
            or "linked" in relation_tokens
            or "related" in relation_tokens
        ):
            primary_target = left_target
            break
    if not primary_target:
        primary_target = self_target or (after_target_entries[0][1] if after_target_entries else "")
    if expected_targets and primary_target and primary_target not in expected_targets:
        return False

    expected_qualifiers = {
        _ENTITY_QUALIFIER_ALIASES.get(token, token)
        for token in expected_objects
        if token in {"first", "second", "third", "fourth", "fifth", "last", "next", "other", "previous"}
        or token.isdigit()
        or (len(token) == 1 and token.isalnum())
    }
    actual_qualifiers = _target_qualifier_tokens(value)
    return not (expected_qualifiers and actual_qualifiers and expected_qualifiers.isdisjoint(actual_qualifiers))


def _is_false_action_flag_value(value: Any) -> bool:
    if value is False or (isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0):
        return True
    if not isinstance(value, str):
        return False
    normalized = re.sub(r"[_ -]+", "", value.strip().casefold())
    return normalized in {re.sub(r"[_ -]+", "", item) for item in _FALSE_ACTION_FLAG_VALUES}


def _is_positive_action_flag_value(value: Any) -> bool:
    if value is True or (isinstance(value, int) and not isinstance(value, bool) and value == 1):
        return True
    if not isinstance(value, str):
        return False
    normalized = re.sub(r"[_ -]+", "", value.strip().casefold())
    return normalized in _TRUE_ACTION_FLAG_VALUES


def _proof_action_state_key_signature(value: Any) -> tuple[bool, bool, str, frozenset[str]]:
    """Return state-key, negated-key, action, and objects for structured flags."""
    raw_value = str(value or "")
    tokens = _text_tokens(raw_value)
    action, objects = _action_signature({"name": raw_value})
    normalized_tokens = tuple(_normalized_token_text(token) for token in tokens)
    inferred_reversal_action = next(
        (
            reversal_action
            for reversal_action, pattern in _PROOF_ACTION_REVERSAL_PATTERNS.items()
            if any(pattern.fullmatch(token) for token in normalized_tokens)
        ),
        "",
    )
    if not action:
        action = inferred_reversal_action
        objects = frozenset(token for token in normalized_tokens if token in _PROOF_ACTION_TARGET_TOKENS)
    if not action:
        return False, False, "", frozenset()
    reversal_pattern = _PROOF_ACTION_REVERSAL_PATTERNS.get(action)
    reversal = bool(reversal_pattern and any(reversal_pattern.fullmatch(token) for token in normalized_tokens))
    nonterminal = any(
        token
        in {
            "attempt",
            "attempted",
            "attempting",
            "could",
            "may",
            "might",
            "pending",
            "scheduled",
            "should",
            "will",
            "would",
        }
        or re.fullmatch(r"(?:opening|cancelling|canceling|issuing|refunding|updating|closing)", token)
        for token in normalized_tokens
    )
    negated = (
        "not" in normalized_tokens
        or any(token.startswith("un") for token in normalized_tokens)
        or nonterminal
        or reversal
    )
    state_key = (
        negated
        or any(_PROOF_COMPLETED_ACTION_TOKEN_PATTERN.fullmatch(token) for token in normalized_tokens)
        or any(
            token
            in {
                "did",
                "does",
                "has",
                "have",
                "is",
                "outcome",
                "result",
                "state",
                "status",
                "success",
                "successful",
                "succeeded",
                "was",
                "were",
            }
            for token in normalized_tokens
        )
    )
    return state_key, negated, action, objects


def _harmless_negative_proof_signal(value: str, match: re.Match[str]) -> bool:
    token = match.group(0).casefold()
    prefix = value[max(0, match.start() - 80) : match.start()]
    if re.search(r"\b(?:after|without)\b[^.!?\n]{0,60}$", prefix) and re.search(
        r"\b(?:fail(?:ed|ure)?|retry)\b",
        token,
    ):
        return True
    if re.search(r"\b(?:no|without)\s+$", prefix) and "error" in token:
        return True
    if re.search(r"\bnot\s+$", prefix) and "pending" in token:
        return True
    if re.search(r"\b(?:not|never)\s+$", prefix) and any(
        pattern.fullmatch(token) for pattern in _PROOF_ACTION_REVERSAL_PATTERNS.values()
    ):
        return True
    semantic_action = _canonical_action_token(token)
    return bool(semantic_action and _PROOF_COMPLETED_ACTION_TOKEN_PATTERN.fullmatch(token))


def _proof_narrative_action_state(
    value: str,
    *,
    expected_action: str,
    expected_objects: frozenset[str],
    allow_neutral_metadata: bool = False,
) -> bool:
    """Require narrative action evidence to end in a compatible terminal state."""
    if allow_neutral_metadata and (
        _HARMLESS_PROOF_METADATA_PATTERN.fullmatch(value) or _PROOF_METADATA_URL_PATTERN.fullmatch(value)
    ):
        return True
    if _INVALIDATING_PROOF_NARRATIVE_PATTERN.search(value):
        return False
    for flag_match in _FALSE_ACTION_FLAG_PATTERN.finditer(value):
        if _proof_action_surface_is_compatible(
            flag_match.group("label"),
            expected_action=expected_action,
            expected_objects=expected_objects,
        ):
            return False

    events: list[tuple[int, bool]] = []
    for action_token, pattern in _NEGATED_PROOF_RESULT_WORDS.items():
        if not _proof_semantic_action_is_compatible(
            action_token,
            expected_action=expected_action,
            expected_objects=expected_objects,
        ):
            continue
        events.extend((match.start(), False) for match in pattern.finditer(value))
    for action_token, pattern in _PROOF_ACTION_REVERSAL_PATTERNS.items():
        if not _proof_semantic_action_is_compatible(
            action_token,
            expected_action=expected_action,
            expected_objects=expected_objects,
        ):
            continue
        for match in pattern.finditer(value):
            reversal_prefix = value[max(0, match.start() - 40) : match.start()]
            if re.search(
                r"\b(?:not|never)\s*$|\bnot\b[^,;:.!?\n]{0,30}\b(?:or|nor)\s*$",
                reversal_prefix,
                re.IGNORECASE,
            ):
                continue
            events.append((match.start(), False))

    semantic_actions: set[str] = set()
    compatible_action_seen = False
    object_mismatch_seen = False
    for token_match in _TEXT_TOKEN_PATTERN.finditer(value):
        raw_token = token_match.group(0)
        semantic_action = _canonical_action_token(raw_token)
        if not semantic_action:
            continue
        semantic_actions.add(semantic_action)
        if not _proof_semantic_action_is_compatible(
            semantic_action,
            expected_action=expected_action,
            expected_objects=expected_objects,
        ):
            continue
        preceding_boundaries = tuple(_PROOF_ACTION_CLAUSE_BOUNDARY_PATTERN.finditer(value, 0, token_match.start()))
        following_boundary = _PROOF_ACTION_CLAUSE_BOUNDARY_PATTERN.search(value, token_match.end())
        clause_start = preceding_boundaries[-1].end() if preceding_boundaries else 0
        clause_end = following_boundary.start() if following_boundary else len(value)
        clause = value[clause_start:clause_end]
        if not _proof_action_clause_is_compatible(
            clause,
            semantic_action=semantic_action,
            expected_action=expected_action,
            expected_objects=expected_objects,
        ) or _EXTERNAL_PROOF_ACTOR_PATTERN.search(clause):
            object_mismatch_seen = True
            continue
        compatible_action_seen = True
        prefix = value[clause_start : token_match.start()]
        suffix = value[token_match.end() : clause_end]
        negated = bool(
            _NEGATED_PROOF_ACTION_PREFIX_PATTERN.search(prefix)
            or _NEGATED_PROOF_ACTION_CONTINUATION_PATTERN.search(value[: token_match.start()])
            or _NEGATED_PROOF_ACTION_SUFFIX_PATTERN.search(suffix)
        )
        if negated:
            if (
                events
                and events[-1][1]
                and re.search(
                    r"\bafter\b[^.!?\n]{0,80}\b(?:first|initially)\b[^.!?\n]{0,40}$",
                    value[: token_match.start()],
                    re.IGNORECASE,
                )
            ):
                continue
            events.append((token_match.start(), False))
            continue
        if (
            _NONTERMINAL_PROOF_ACTION_PREFIX_PATTERN.search(prefix)
            or _UNCERTAIN_PROOF_ACTION_PREFIX_PATTERN.search(prefix)
            or _CONDITIONAL_PROOF_ACTION_PREFIX_PATTERN.search(value[: token_match.start()])
        ):
            events.append((token_match.start(), False))
            continue
        normalized_token = _normalized_token_text(raw_token)
        completed = bool(
            _PROOF_COMPLETED_ACTION_TOKEN_PATTERN.fullmatch(raw_token)
            or _PROOF_COMPLETED_ACTION_TOKEN_PATTERN.fullmatch(normalized_token)
        )
        if not completed and re.search(
            r"^\s*(?:(?:has|have|is|are|was|were)\s+)?"
            r"(?:(?:already|successfully|now)\s+)*"
            r"(?:complete(?:d)?|done|successful)\b",
            suffix,
            re.IGNORECASE,
        ):
            completed = True
        if not completed and re.search(
            r"\b(?:did\s+not|didn['’]t)\s+(?:only|just|merely)\s*$",
            prefix,
            re.IGNORECASE,
        ):
            completed = True
        if completed:
            events.append((token_match.start(), True))

    for negative_match in _NEGATIVE_PROOF_VALUE_PATTERN.finditer(value):
        if not _harmless_negative_proof_signal(value, negative_match):
            events.append((negative_match.start(), False))
    for denial_match in _GENERIC_ACTION_DENIAL_PATTERN.finditer(value):
        events.append((denial_match.start(), False))

    if events:
        return max(events, key=lambda item: item[0])[1]
    if compatible_action_seen:
        return False
    if object_mismatch_seen:
        return False
    if semantic_actions:
        return any(
            _proof_semantic_action_is_compatible(
                semantic_action,
                expected_action=expected_action,
                expected_objects=expected_objects,
            )
            for semantic_action in semantic_actions
        )
    if _GENERIC_POSITIVE_PROOF_NARRATIVE_PATTERN.search(value):
        expected_targets = expected_objects.intersection(_PROOF_ACTION_TARGET_TOKENS) - _GENERIC_ACTION_OBJECT_TOKENS
        actual_targets = {
            _normalized_object_token(token)
            for token in _text_tokens(value)
            if _normalized_object_token(token) in _PROOF_ACTION_TARGET_TOKENS
        }
        if expected_targets and actual_targets and expected_targets.isdisjoint(actual_targets):
            return False
        return True
    if _GENERIC_NONTERMINAL_PROOF_NARRATIVE_PATTERN.search(value):
        return False
    if _GENERIC_ACTION_DENIAL_PATTERN.search(value):
        return False
    if _NEGATIVE_PROOF_VALUE_PATTERN.search(value):
        return False
    return True


def _proof_semantics_match_action(
    proof: Any,
    expected_action: str,
    expected_objects: frozenset[str] = frozenset(),
) -> bool:
    """Reject positive terminal states that describe a different mutation."""
    if not expected_action:
        return True
    expected_targets = expected_objects.intersection(_PROOF_ACTION_TARGET_TOKENS) - _GENERIC_ACTION_OBJECT_TOKENS
    expected_qualifiers = _expected_entity_qualifiers(expected_objects)
    stack: list[tuple[Any, int, str, bool, bool]] = [(proof, 0, "", False, False)]
    seen: set[int] = set()
    inspected = 0
    while stack:
        value, depth, parent_key, identifier_value, semantic_context = stack.pop()
        if isinstance(value, str):
            if identifier_value:
                continue
            strict_semantic_value = parent_key in (_PROOF_SEMANTIC_VALUE_KEYS | _TERMINAL_PROOF_VALUE_KEYS) or (
                semantic_context and parent_key == "value"
            )
            normalized_scalar = re.sub(r"[_ -]+", "", value.strip().casefold())
            if strict_semantic_value and normalized_scalar in _FALSE_SEMANTIC_STRING_VALUES:
                return False
            if not _proof_narrative_action_state(
                value,
                expected_action=expected_action,
                expected_objects=expected_objects,
                allow_neutral_metadata=not semantic_context
                and parent_key not in (_PROOF_SEMANTIC_VALUE_KEYS | _TERMINAL_PROOF_VALUE_KEYS),
            ):
                return False
            continue
        if not isinstance(value, (Mapping, list, tuple)):
            if not identifier_value:
                strict_semantic_value = parent_key in (_PROOF_SEMANTIC_VALUE_KEYS | _TERMINAL_PROOF_VALUE_KEYS) or (
                    semantic_context and parent_key == "value"
                )
                if strict_semantic_value and (
                    value is None
                    or isinstance(value, bool)
                    or (
                        isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        and not (
                            parent_key in _STRICT_SCALAR_TERMINAL_PROOF_KEYS
                            and isinstance(value, int)
                            and 200 <= value <= 299
                        )
                    )
                ):
                    return False
            continue
        if depth > _PROOF_PAYLOAD_MAX_DEPTH or id(value) in seen:
            return False
        if parent_key == "result" and not value:
            return False
        seen.add(id(value))
        if isinstance(value, Mapping):
            items = tuple(value.items())
            inspected += len(items)
            if inspected > _PROOF_PAYLOAD_MAX_ITEMS:
                return False
            for key, nested_value in items:
                raw_key = str(key)
                normalized_key = re.sub(
                    r"[^a-z0-9]",
                    "",
                    raw_key.lower().rsplit(".", 1)[-1],
                )
                actual_qualifiers = _structured_proof_entity_qualifiers(
                    raw_key,
                    nested_value,
                    expected_targets=expected_targets,
                )
                if expected_qualifiers and actual_qualifiers and expected_qualifiers.isdisjoint(actual_qualifiers):
                    return False
                if normalized_key in _NEUTRAL_PROOF_FLAG_KEYS:
                    state_key, negated_key, key_action, _key_objects = (
                        False,
                        False,
                        "",
                        frozenset(),
                    )
                else:
                    state_key, negated_key, key_action, _key_objects = _proof_action_state_key_signature(raw_key)
                if (
                    key_action
                    and not state_key
                    and (
                        nested_value is None
                        or isinstance(nested_value, (bool, int, float))
                        or _is_false_action_flag_value(nested_value)
                        or _is_positive_action_flag_value(nested_value)
                    )
                ):
                    state_key = True
                if state_key:
                    key_compatible = _proof_action_surface_is_compatible(
                        raw_key,
                        expected_action=expected_action,
                        expected_objects=expected_objects,
                    )
                    positive_value = _is_positive_action_flag_value(nested_value)
                    if key_compatible:
                        if negated_key:
                            if nested_value is False:
                                continue
                            return False
                        if not positive_value:
                            return False
                    elif key_action:
                        return False
                if normalized_key in _TERMINAL_PROOF_VALUE_KEYS and isinstance(nested_value, str):
                    normalized_value = re.sub(r"[_-]+", " ", nested_value.strip().casefold())
                    if normalized_value in _GENERIC_TERMINAL_PROOF_VALUES:
                        pass
                    else:
                        semantic_action = _SPECIAL_TERMINAL_PROOF_ACTIONS.get(
                            normalized_value
                        ) or _canonical_action_token(normalized_value)
                        if semantic_action and not _proof_semantic_action_is_compatible(
                            semantic_action,
                            expected_action=expected_action,
                            expected_objects=expected_objects,
                        ):
                            return False
                stack.append(
                    (
                        nested_value,
                        depth + 1,
                        normalized_key,
                        _PROOF_IDENTIFIER_KEY_PATTERN.search(raw_key) is not None
                        or _PROOF_OPAQUE_VALUE_KEY_PATTERN.search(raw_key) is not None,
                        semantic_context or normalized_key in (_PROOF_SEMANTIC_VALUE_KEYS | _TERMINAL_PROOF_VALUE_KEYS),
                    )
                )
        else:
            inspected += len(value)
            if inspected > _PROOF_PAYLOAD_MAX_ITEMS:
                return False
            stack.extend(
                (
                    nested_value,
                    depth + 1,
                    parent_key,
                    identifier_value,
                    semantic_context,
                )
                for nested_value in value
            )
    return True


def has_meaningful_action_success_proof(
    proof: Any,
    *,
    action: Mapping[str, Any] | str | None = None,
) -> bool:
    """Validate bounded proof and, when supplied, bind it to its action."""
    if action is None:
        return _has_meaningful_bounded_proof(proof)
    action_record: Mapping[str, Any] = {"name": action} if isinstance(action, str) else action
    expected_action, expected_objects = _action_signature(action_record)
    if not _has_meaningful_bounded_proof(proof, action_bound=True):
        return False
    return _proof_semantics_match_action(
        proof,
        expected_action,
        expected_objects,
    )


def _action_signatures_overlap(
    left: tuple[str, frozenset[str]],
    right: tuple[str, frozenset[str]],
) -> bool:
    left_action, left_objects = left
    right_action, right_objects = right
    return bool(
        left_action
        and left_action == right_action
        and (not left_objects or not right_objects or left_objects.intersection(right_objects))
    )


def _successful_action_records(
    runbook_actions: Iterable[Mapping[str, Any]],
) -> tuple[_SuccessfulActionRecord, ...]:
    """Return only actions with complete durable execution proof."""
    action_records = tuple(runbook_actions)
    pending_signatures = tuple(
        signature
        for action in action_records
        if str(action.get("status") or "").strip().lower().replace("-", "_") == "pending_approval"
        and (signature := _action_signature(action))[0]
    )
    candidates: list[tuple[str, frozenset[str], frozenset[str], tuple[str, ...]]] = []
    for action in action_records:
        status = str(action.get("status") or "").strip().lower()
        application = action.get("application")
        application_record = application if isinstance(application, Mapping) else {}
        applied = action.get("applied") if "applied" in action else application_record.get("applied")
        webhook_result = action.get("webhookResult")
        if not isinstance(webhook_result, Mapping):
            webhook_result = application_record.get("webhookResult")
        evidence_id = str(action.get("evidenceId") or "").strip()
        concern_id = str(action.get("concernId") or "").strip()
        proof = action.get("proof")
        if (
            status != "success"
            or applied is not True
            or not isinstance(webhook_result, Mapping)
            or str(webhook_result.get("status") or "").strip().lower() != "ok"
            or not concern_id
            or not evidence_id.startswith("action:")
            or not evidence_id.removeprefix("action:").strip()
            or not _has_meaningful_bounded_proof(proof, action_bound=True)
        ):
            continue
        action_token, object_tokens = _action_signature(action)
        if not action_token or not _proof_semantics_match_action(
            proof,
            action_token,
            object_tokens,
        ):
            continue
        candidates.append(
            (
                action_token,
                object_tokens,
                _action_target_qualifiers(action),
                _proof_identifiers(proof),
            )
        )
    records: list[_SuccessfulActionRecord] = []
    for index, (
        action_token,
        object_tokens,
        target_qualifiers,
        identifiers,
    ) in enumerate(candidates):
        signature = (action_token, object_tokens)
        requires_identifier = any(
            _action_signatures_overlap(signature, pending_signature) for pending_signature in pending_signatures
        ) or any(
            other_index != index
            and _action_signatures_overlap(
                signature,
                (other_action, other_objects),
            )
            for other_index, (
                other_action,
                other_objects,
                _other_qualifiers,
                _other_identifiers,
            ) in enumerate(candidates)
        )
        records.append(
            _SuccessfulActionRecord(
                action_token=action_token,
                object_tokens=object_tokens,
                target_qualifiers=target_qualifiers,
                proof_identifiers=identifiers,
                requires_identifier=requires_identifier,
            )
        )
    return tuple(records[:20])


def _is_success_backed_action_claim(
    *,
    pattern: re.Pattern[str],
    unit: str,
    match: re.Match[str],
    successful_actions: tuple[_SuccessfulActionRecord, ...],
) -> bool:
    if pattern not in _SUCCESS_ELIGIBLE_CLAIM_PATTERNS:
        return False
    matched_action_tokens = [
        (canonical, token_match.start())
        for token_match in _TEXT_TOKEN_PATTERN.finditer(match.group(0))
        if (canonical := _canonical_action_token(token_match.group(0).lower()))
    ]
    if not matched_action_tokens:
        return False
    # The action/state at the end of a claim is the asserted mutation. This is
    # especially important for coordinated sentences containing an earlier,
    # successfully completed action and a different unapproved promise later.
    claimed_action, relative_action_start = matched_action_tokens[-1]
    action_start = match.start() + relative_action_start
    scope_start = match.start()
    scope_end = len(unit)
    if pattern in _COORDINATED_SUCCESS_SCOPE_PATTERNS:
        for boundary in _INTRA_MATCH_COORDINATOR_PATTERN.finditer(
            unit,
            match.start(),
            action_start,
        ):
            scope_start = boundary.end()
    for boundary in _LOCAL_CLAUSE_BOUNDARY_PATTERN.finditer(unit):
        if boundary.start() >= action_start:
            scope_end = boundary.start()
            break
    followup_actions = _followup_action_matches(
        unit=unit,
        primary_pattern=pattern,
        primary_match=match,
    )
    if followup_actions:
        scope_end = min(scope_end, followup_actions[0].start("separator"))
    leading_scope = unit[max(0, scope_start - 40) : scope_start]
    if leading_match := _LEADING_ENTITY_QUALIFIER_PATTERN.search(leading_scope):
        scope_start = max(0, scope_start - 40) + leading_match.start()
    claim_scope = unit[scope_start:scope_end].strip()
    return _successful_action_backs_scope(
        claimed_action=claimed_action,
        claim_scope=claim_scope,
        successful_actions=successful_actions,
    )


def _successful_action_backs_scope(
    *,
    claimed_action: str,
    claim_scope: str,
    successful_actions: tuple[_SuccessfulActionRecord, ...],
) -> bool:
    scope_tokens = {
        _normalized_object_token(token) for token in _text_tokens(claim_scope) if token not in _ACTION_OBJECT_STOPWORDS
    }
    scope_target_objects = {
        token
        for token in scope_tokens.intersection(_ACTION_TARGET_OBJECT_TOKENS)
        if _canonical_action_token(token) != claimed_action
    }
    matching_actions = tuple(action for action in successful_actions if action.action_token == claimed_action)
    if len(scope_target_objects) > 1:
        covered_targets = frozenset(
            target
            for action in matching_actions
            for target in action.object_tokens.intersection(_ACTION_TARGET_OBJECT_TOKENS)
        )
        if scope_target_objects.issubset(covered_targets) and all(
            any(
                target in action.object_tokens
                and (
                    not action.requires_identifier
                    or any(
                        re.search(
                            rf"(?<![A-Za-z0-9_-]){re.escape(identifier)}"
                            rf"(?![A-Za-z0-9_-])",
                            claim_scope,
                            re.IGNORECASE,
                        )
                        for identifier in action.proof_identifiers
                    )
                )
                for action in matching_actions
            )
            for target in scope_target_objects
        ):
            return True
    for action in matching_actions:
        action_target_objects = action.object_tokens.intersection(_ACTION_TARGET_OBJECT_TOKENS)
        if scope_target_objects and action_target_objects and not scope_target_objects.issubset(action_target_objects):
            continue
        qualifier_scope = claim_scope
        for identifier in action.proof_identifiers:
            qualifier_scope = re.sub(
                rf"(?<![A-Za-z0-9_-]){re.escape(identifier)}"
                rf"(?![A-Za-z0-9_-])",
                " ",
                qualifier_scope,
                flags=re.IGNORECASE,
            )
        scope_qualifiers = _target_qualifier_tokens(qualifier_scope)
        if scope_qualifiers and action.target_qualifiers and scope_qualifiers.isdisjoint(action.target_qualifiers):
            continue
        proof_matches = any(
            re.search(
                rf"(?<![A-Za-z0-9_-]){re.escape(identifier)}"
                rf"(?![A-Za-z0-9_-])",
                claim_scope,
                re.IGNORECASE,
            )
            for identifier in action.proof_identifiers
        )
        if proof_matches:
            return True
        if not action.requires_identifier and action.object_tokens.intersection(scope_tokens):
            return True
    return False


def _successful_actions_for_expected_text(
    runbook_actions: Iterable[Mapping[str, Any]],
    expected_action_text: str,
) -> tuple[_SuccessfulActionRecord, ...]:
    expected_action, expected_objects = _action_signature({"name": expected_action_text})
    if not expected_action:
        return ()
    expected_targets = expected_objects.intersection(_ACTION_TARGET_OBJECT_TOKENS) - _GENERIC_ACTION_OBJECT_TOKENS
    expected_qualifiers = _target_qualifier_tokens(expected_action_text)
    candidates = tuple(
        action
        for action in _successful_action_records(runbook_actions)
        if action.action_token == expected_action
        and (not expected_qualifiers or expected_qualifiers.issubset(action.target_qualifiers))
    )
    if expected_targets:
        covered_targets = frozenset(
            target
            for action in candidates
            for target in (
                action.object_tokens.intersection(_ACTION_TARGET_OBJECT_TOKENS) - _GENERIC_ACTION_OBJECT_TOKENS
            )
        )
        if not expected_targets.issubset(covered_targets):
            return ()
        return tuple(
            action
            for action in candidates
            if expected_targets.intersection(
                action.object_tokens.intersection(_ACTION_TARGET_OBJECT_TOKENS) - _GENERIC_ACTION_OBJECT_TOKENS
            )
        )

    matches: list[_SuccessfulActionRecord] = []
    for action in candidates:
        if expected_objects and not expected_objects.intersection(action.object_tokens):
            continue
        matches.append(action)
    return tuple(matches)


def action_record_matches_expected_text(
    action: Mapping[str, Any],
    expected_action_text: str,
) -> bool:
    """Bind one action/tool name to every discriminating object in a question."""
    actual_action, actual_objects = _action_signature(action)
    expected_action, expected_objects = _action_signature({"name": expected_action_text})
    if not actual_action or actual_action != expected_action:
        return False
    expected_targets = expected_objects.intersection(_ACTION_TARGET_OBJECT_TOKENS) - _GENERIC_ACTION_OBJECT_TOKENS
    actual_targets = actual_objects.intersection(_ACTION_TARGET_OBJECT_TOKENS) - _GENERIC_ACTION_OBJECT_TOKENS
    expected_qualifiers = _target_qualifier_tokens(expected_action_text)
    actual_qualifiers = _action_target_qualifiers(action)
    if expected_qualifiers and not expected_qualifiers.issubset(actual_qualifiers):
        return False
    if expected_targets:
        return expected_targets.issubset(actual_targets)
    return not expected_objects or bool(expected_objects.intersection(actual_objects))


def has_durable_action_success(
    *,
    runbook_actions: Iterable[Mapping[str, Any]],
    expected_action_text: str,
) -> bool:
    """Match one same-concern obligation to durable terminal action proof."""
    return bool(
        _successful_actions_for_expected_text(
            runbook_actions,
            expected_action_text,
        )
    )


_ACTION_IMPERATIVE_SURFACES = {
    "cancel": "Cancel",
    "check": "Check",
    "escalate": "Escalate",
    "initiate": "Initiate",
    "investigate": "Investigate",
    "issue": "Issue",
    "notify": "Notify",
    "open": "Open",
    "record": "Record",
    "refund": "Refund",
    "submit": "Submit",
    "update": "Update",
}


def action_obligation_parts(value: str) -> tuple[str, ...]:
    """Split a bounded multi-verb obligation into independently tracked actions."""
    token_matches = tuple(_TEXT_TOKEN_PATTERN.finditer(value))
    action_matches: list[re.Match[str]] = []
    for index, match in enumerate(token_matches):
        if not _canonical_action_token(match.group(0)):
            continue
        if not action_matches:
            action_matches.append(match)
            continue
        previous_token = token_matches[index - 1].group(0).casefold() if index else ""
        separator = value[token_matches[index - 1].end() : match.start()] if index else ""
        if index + 1 < len(token_matches) and (
            previous_token in {"and", "also", "then"} or re.search(r"[,;]", separator)
        ):
            action_matches.append(match)
    if len(action_matches) < 2:
        return (value,)
    shared_targets = tuple(
        dict.fromkeys(
            _normalized_object_token(match.group(0))
            for match in token_matches
            if _normalized_object_token(match.group(0))
            in (_ACTION_TARGET_OBJECT_TOKENS - _GENERIC_ACTION_OBJECT_TOKENS)
        )
    )
    parts: list[str] = []
    for index, action_match in enumerate(action_matches):
        end = action_matches[index + 1].start() if index + 1 < len(action_matches) else len(value)
        part = value[action_match.start() : end].strip(" \t\r\n,;:.!?")
        part = re.sub(r"\b(?:and|also|then)\s*$", "", part, flags=re.IGNORECASE).strip()
        _part_action, part_objects = _action_signature({"name": part})
        if not part_objects and shared_targets:
            rendered = " and ".join(shared_targets)
            part = f"{part} the {rendered}"
        if part:
            parts.append(part[:240] + ".")
    return tuple(parts) or (value,)


def remaining_action_obligation_text(
    *,
    runbook_actions: Iterable[Mapping[str, Any]],
    expected_action_text: str,
) -> str:
    """Return only the still-unproven part of a compound action obligation."""
    records = tuple(runbook_actions)
    if has_durable_action_success(
        runbook_actions=records,
        expected_action_text=expected_action_text,
    ):
        return ""
    expected_action, expected_objects = _action_signature({"name": expected_action_text})
    expected_targets = expected_objects.intersection(_ACTION_TARGET_OBJECT_TOKENS) - _GENERIC_ACTION_OBJECT_TOKENS
    expected_qualifiers = _target_qualifier_tokens(expected_action_text)
    if not expected_action or len(expected_targets) < 2 or expected_qualifiers:
        return expected_action_text
    candidates = tuple(
        record for record in _successful_action_records(records) if record.action_token == expected_action
    )
    covered_targets = frozenset(
        target
        for record in candidates
        for target in (record.object_tokens.intersection(_ACTION_TARGET_OBJECT_TOKENS) - _GENERIC_ACTION_OBJECT_TOKENS)
    )
    missing_targets = sorted(expected_targets - covered_targets)
    if not missing_targets or len(missing_targets) == len(expected_targets):
        return expected_action_text
    action_surface = _ACTION_IMPERATIVE_SURFACES.get(expected_action)
    if not action_surface:
        return expected_action_text
    rendered_targets = missing_targets[0] if len(missing_targets) == 1 else " and ".join(missing_targets)
    return f"{action_surface} the {rendered_targets}."


def has_success_backed_action_claim(
    *,
    answer: str,
    runbook_actions: Iterable[Mapping[str, Any]],
    expected_action_text: str,
) -> bool:
    """Match one terminal answer claim to durable same-concern proof."""

    expected_action, expected_objects = _action_signature({"name": expected_action_text})
    successful_actions = _successful_actions_for_expected_text(
        runbook_actions,
        expected_action_text,
    )
    if not successful_actions:
        return False

    for unit in _answer_units(answer):
        shadow = _action_claim_shadow(unit)
        for pattern in _CLAIM_PATTERNS:
            for match in pattern.finditer(shadow):
                matched_action_tokens = [
                    (canonical, token_match.start())
                    for token_match in _TEXT_TOKEN_PATTERN.finditer(match.group(0))
                    if (canonical := _canonical_action_token(token_match.group(0).lower()))
                ]
                if not matched_action_tokens:
                    continue
                claimed_action, relative_action_start = matched_action_tokens[-1]
                if claimed_action != expected_action:
                    continue
                action_start = match.start() + relative_action_start
                scope_start = match.start()
                scope_end = len(unit)
                if pattern in _COORDINATED_SUCCESS_SCOPE_PATTERNS:
                    for boundary in _INTRA_MATCH_COORDINATOR_PATTERN.finditer(
                        unit,
                        match.start(),
                        action_start,
                    ):
                        scope_start = boundary.end()
                for boundary in _LOCAL_CLAUSE_BOUNDARY_PATTERN.finditer(unit):
                    if boundary.start() >= action_start:
                        scope_end = boundary.start()
                        break
                leading_scope = unit[max(0, scope_start - 40) : scope_start]
                if leading_match := _LEADING_ENTITY_QUALIFIER_PATTERN.search(leading_scope):
                    scope_start = max(0, scope_start - 40) + leading_match.start()
                claim_scope = unit[scope_start:scope_end].strip()
                scope_tokens = {
                    _normalized_object_token(token)
                    for token in _text_tokens(claim_scope)
                    if token not in _ACTION_OBJECT_STOPWORDS
                }
                if expected_objects and not expected_objects.intersection(scope_tokens):
                    continue
                if _is_success_backed_action_claim(
                    pattern=pattern,
                    unit=unit,
                    match=match,
                    successful_actions=successful_actions,
                ):
                    return True
    return False


def _followup_action_matches(
    *,
    unit: str,
    primary_pattern: re.Pattern[str],
    primary_match: re.Match[str],
) -> tuple[re.Match[str], ...]:
    matches: list[re.Match[str]] = []
    shadow = _action_claim_shadow(unit)
    for match in _FOLLOWUP_ACTION_PATTERN.finditer(shadow, primary_match.end()):
        action_text = match.group("action")
        is_completed = _FOLLOWUP_COMPLETED_ACTION_PATTERN.fullmatch(action_text)
        is_progressive = _FOLLOWUP_PROGRESSIVE_ACTION_PATTERN.fullmatch(action_text)
        is_future = _FOLLOWUP_FUTURE_ACTION_PATTERN.fullmatch(action_text)
        if is_completed or is_progressive:
            matches.append(match)
            continue
        if is_future and (
            match.group("aux") or match.group("actor") or primary_pattern in _FUTURE_TAIL_PRIMARY_PATTERNS
        ):
            matches.append(match)
    return tuple(matches)


def _first_unbacked_followup_action(
    *,
    unit: str,
    primary_pattern: re.Pattern[str],
    primary_match: re.Match[str],
    successful_actions: tuple[_SuccessfulActionRecord, ...],
) -> re.Match[str] | None:
    matches = _followup_action_matches(
        unit=unit,
        primary_pattern=primary_pattern,
        primary_match=primary_match,
    )
    for index, match in enumerate(matches):
        action_tokens = [
            canonical for token in _text_tokens(match.group("action")) if (canonical := _canonical_action_token(token))
        ]
        if not action_tokens:
            return match
        scope_end = matches[index + 1].start("separator") if index + 1 < len(matches) else len(unit)
        claim_scope = unit[match.start("action") : scope_end].strip()
        if not _successful_action_backs_scope(
            claimed_action=action_tokens[-1],
            claim_scope=claim_scope,
            successful_actions=successful_actions,
        ):
            return match
    return None


def _pending_action_names(runbook_actions: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    names: list[str] = []
    for action in runbook_actions:
        status = str(action.get("status") or "").strip().lower().replace("-", "_")
        if status != "pending_approval":
            continue
        name = str(action.get("label") or action.get("name") or "pending action").strip()
        if name and name not in names:
            names.append(name[:160])
    return tuple(names[:20])


def _pending_dynamic_subjects(
    runbook_actions: Iterable[Mapping[str, Any]],
) -> tuple[tuple[str, str], ...]:
    subjects: list[tuple[str, str]] = []
    for action in runbook_actions:
        status = str(action.get("status") or "").strip().lower().replace("-", "_")
        if status != "pending_approval":
            continue
        action_token, object_tokens = _action_signature(action)
        if not action_token:
            raw_text = str(action.get("name") or action.get("label") or "")
            tokens = _text_tokens(raw_text)
            if not tokens:
                continue
            action_token = _normalized_object_token(tokens[0])
            object_tokens = frozenset(
                _normalized_object_token(token)
                for token in tokens[1:]
                if token not in _ACTION_OBJECT_STOPWORDS and len(token) >= 2
            )
        for token in sorted(object_tokens):
            subject = (token, action_token)
            if len(token) < 2 or token in _GENERIC_ACTION_OBJECT_TOKENS or subject in subjects:
                continue
            subjects.append(subject)
            if len(subjects) >= 40:
                return tuple(subjects)
    return tuple(subjects)


def _generic_action_forms(action_token: str) -> tuple[str, str, str]:
    """Return bounded base, past-participle, and progressive regex forms."""
    base = re.escape(action_token)
    if action_token.endswith("e") and len(action_token) > 3:
        stem = re.escape(action_token[:-1])
        return base, rf"{stem}ed", rf"{stem}ing"
    if action_token.endswith("y") and len(action_token) > 3:
        stem = re.escape(action_token[:-1])
        return base, rf"{stem}ied", rf"{base}ing"
    return base, rf"{base}ed", rf"{base}ing"


def _normalized_fact_path(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower().rsplit(".", 1)[-1])


def _tool_fact_items(tool: Mapping[str, Any]) -> tuple[tuple[str, Any], ...]:
    raw_facts = tool.get("responseFacts") or tool.get("response_facts") or tool.get("facts")
    if isinstance(raw_facts, Mapping):
        return tuple((str(path), value) for path, value in raw_facts.items())
    if not isinstance(raw_facts, Iterable) or isinstance(raw_facts, (str, bytes)):
        return ()
    facts: list[tuple[str, Any]] = []
    for raw_fact in raw_facts:
        if not isinstance(raw_fact, Mapping):
            continue
        path = str(raw_fact.get("path") or "").strip()
        value = raw_fact.get("value")
        if path:
            facts.append((path, value))
    return tuple(facts)


def _successful_readonly_tracking_identifiers(
    tool_evidence: Iterable[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Require an exact successful GET audit with a tracking identifier fact."""
    identifiers: list[str] = []
    for tool in tool_evidence:
        name = str(tool.get("name") or tool.get("toolName") or tool.get("tool_name") or "").strip()
        method = str(tool.get("method") or "").strip().upper()
        status = str(tool.get("status") or "").strip().lower()
        if (
            method != "GET"
            or status != "success"
            or not _TRACKING_TOOL_DOMAIN_PATTERN.search(name)
            or not _TRACKING_TOOL_READ_PATTERN.search(name)
        ):
            continue
        for path, value in _tool_fact_items(tool):
            identifier = str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
            if _normalized_fact_path(path) in _TRACKING_ID_FACT_PATHS and identifier and identifier not in identifiers:
                identifiers.append(identifier[:240])
    return tuple(identifiers[:20])


def _has_pending_tracking_read(
    runbook_actions: Iterable[Mapping[str, Any]],
) -> bool:
    for action in runbook_actions:
        status = str(action.get("status") or "").strip().lower().replace("-", "_")
        if status != "pending_approval":
            continue
        action_text = (
            " ".join(str(action.get(key) or "") for key in ("name", "label")).replace("_", " ").replace("-", " ")
        )
        if _PENDING_TRACKING_READ_PATTERN.search(action_text):
            return True
    return False


def _is_evidence_backed_tracking_check(
    *,
    pattern: re.Pattern[str],
    match: re.Match[str],
    unit: str,
    tracking_identifiers: tuple[str, ...],
) -> bool:
    if not tracking_identifiers or pattern not in {
        _PERFECT_ACTION_PATTERN,
        _PAST_ACTION_PATTERN,
    }:
        return False
    if not re.search(r"\bchecked\s*$", match.group(0), re.IGNORECASE):
        return False
    if _TRACKING_CHECK_OBJECT_PATTERN.search(unit[match.end() :]) is None:
        return False
    if _COORDINATED_ACTION_TAIL_PATTERN.search(unit[match.end() :]):
        return False
    return any(
        re.search(
            rf"(?<![A-Za-z0-9_-]){re.escape(identifier)}(?![A-Za-z0-9_-])",
            unit,
            re.IGNORECASE,
        )
        is not None
        for identifier in tracking_identifiers
    )


def _answer_units(answer: str) -> tuple[str, ...]:
    segmentation_shadow = re.sub(
        r"(?m)(^\s*\d+)\.(?=\s*(?:\[[ xX]\]\s*)?\S)",
        r"\1 ",
        answer,
    )
    segmentation_shadow = re.sub(r"(?<!\n)\n(?!\n)", " ", segmentation_shadow)
    units = [
        answer[match.start() : match.end()].strip()
        for match in _ANSWER_UNIT_PATTERN.finditer(segmentation_shadow)
        if answer[match.start() : match.end()].strip()
    ]
    return tuple(units or ([answer.strip()] if answer.strip() else []))


def _has_scoped_future_contingency(*, prefix: str, suffix: str) -> bool:
    prefix_match = _FUTURE_CONTINGENCY_PREFIX_PATTERN.search(prefix)
    if prefix_match is not None:
        condition_scope = prefix_match.group(0)
        if _UNSAFE_FUTURE_CONTINGENCY_PATTERN.search(condition_scope) is None and not any(
            pattern.search(condition_scope) for pattern in _FUTURE_CLAIM_PATTERNS
        ):
            return True

    suffix_match = _FUTURE_CONTINGENCY_SUFFIX_PATTERN.search(suffix)
    if suffix_match is None:
        return False
    condition_scope = suffix[suffix_match.start("condition") :][:160]
    if _UNSAFE_FUTURE_CONTINGENCY_PATTERN.search(condition_scope):
        return False
    action_scope = re.sub(r",\s*$", "", suffix_match.group("scope"))
    if _UNRELATED_CLAUSE_PATTERN.search(action_scope):
        return False
    return not any(pattern.search(action_scope) for pattern in _FUTURE_CLAIM_PATTERNS)


def _bare_confirmation_is_safely_pending(
    unit: str,
    match: re.Match[str],
) -> bool:
    """Require pending grammar to bind to the same bare confirmation group."""
    tail = unit[match.end() :]
    pending_match = _PENDING_CONFIRMATION_DIRECT_TAIL_PATTERN.match(
        tail
    ) or _PENDING_CONFIRMATION_COORDINATED_TAIL_PATTERN.match(tail)
    if pending_match is None:
        return False
    return _PENDING_CONFIRMATION_REVERSAL_PATTERN.search(tail[pending_match.end() :]) is None


def _future_confirmation_is_explicitly_noncomplete(
    *,
    pattern: re.Pattern[str],
    unit: str,
    match: re.Match[str],
) -> bool:
    if pattern not in _FUTURE_CONFIRMATION_PATTERNS:
        return False
    return _SAFE_NONCOMPLETION_CONFIRMATION_TAIL_PATTERN.fullmatch(unit[match.end() :]) is not None


def _claim_is_explicitly_not_completed(
    unit: str,
    match: re.Match[str],
) -> bool:
    """Allow a same-clause action subject with an explicit negative state.

    The terse action-first matcher intentionally catches headings such as
    ``Changing the address``. In ordinary prose that same phrase can instead be
    the grammatical subject of ``is not confirmed``. Bind the negative state to
    the matched action before deciding that it is a completion claim. Any later
    positive promise or completion remains visible to the other claim patterns.
    """

    tail = unit[match.end() :]
    pending_match = _EXPLICIT_NONCOMPLETION_TAIL_PATTERN.match(tail)
    if pending_match is None or _NONCOMPLETION_SCOPE_BREAK_PATTERN.search(pending_match.group("scope")):
        return False
    remainder = tail[pending_match.end() :]
    return re.fullmatch(r"\s*[.!?]*\s*", remainder) is not None


def _is_scoped_negative_epistemic_claim(*, prefix: str, claim: str) -> bool:
    return (
        _SAFE_NEGATIVE_EPISTEMIC_PREFIX_PATTERN.search(prefix) is not None
        and _POSITIVE_CONTRAST_PATTERN.search(claim) is None
    )


def _is_external_state_attribution(
    *,
    pattern: re.Pattern[str],
    unit: str,
    match: re.Match[str],
) -> bool:
    """Allow explicit third-party completed facts, never first-party promises."""
    if pattern not in _EXTERNAL_STATE_PASSIVE_PATTERNS:
        return False
    immediate_tail = unit[match.end() : match.end() + 140].lstrip(" ,\t")
    attribution = _EXTERNAL_STATE_ATTRIBUTION_PATTERN.match(immediate_tail)
    if attribution is None:
        return False
    return (
        re.match(
            r"by\s+(?:the\s+)?customer\s+service\s+team\b",
            immediate_tail,
            re.IGNORECASE,
        )
        is None
    )


def _is_external_customer_contact(
    *,
    pattern: re.Pattern[str],
    unit: str,
    match: re.Match[str],
) -> bool:
    """Keep explicit third-party contact facts outside first-party promises."""
    immediate_tail = unit[match.end() : match.end() + 140]
    if pattern in _PASSIVE_CUSTOMER_CONTACT_PROMISE_PATTERNS:
        return _EXTERNAL_CUSTOMER_CONTACT_ATTRIBUTION_PATTERN.match(immediate_tail) is not None
    if (
        re.search(
            r"\b(?:follow[\s\-‐‑‒–—]+up|respond|reply|reach(?:\s+back)?\s+out)\s*$",
            match.group(0),
            re.IGNORECASE,
        )
        is None
    ):
        return False
    boundary = re.search(r"[,;:]|\b(?:and|but|then|while)\b", immediate_tail, re.IGNORECASE)
    target_scope = immediate_tail[: boundary.start()] if boundary else immediate_tail
    if _CUSTOMER_CONTACT_TARGET_PATTERN.search(f"{match.group(0)}{target_scope}"):
        return False
    return _EXTERNAL_CUSTOMER_CONTACT_TARGET_PATTERN.search(target_scope) is not None


def _has_unsafe_dynamic_subject_claim(
    unit: str,
    *,
    dynamic_subjects: tuple[tuple[str, str], ...],
    successful_actions: tuple[_SuccessfulActionRecord, ...],
) -> bool:
    """Cover custom runbook objects without maintaining a fixed noun list."""
    if not dynamic_subjects:
        return False
    shadow = _action_claim_shadow(unit)
    completed = "|".join(
        (
            *_COMPLETED_ACTIONS,
            *_LIFECYCLE_COMPLETED_ACTIONS,
            *_CUSTOM_COMPLETED_ACTIONS,
        )
    )
    progressive = "|".join((*_PROGRESSIVE_ACTIONS, *_CUSTOM_PROGRESSIVE_ACTIONS))
    for subject, pending_action_token in dynamic_subjects:
        subject_pattern = rf"{re.escape(subject)}(?:s)?" if not subject.endswith("s") else re.escape(subject)
        known_action = bool(_canonical_action_token(pending_action_token))
        if known_action:
            subject_completed = completed
            subject_progressive = progressive
            actor_patterns: tuple[re.Pattern[str], ...] = ()
        else:
            base_form, past_form, progressive_form = _generic_action_forms(pending_action_token)
            subject_completed = past_form
            subject_progressive = progressive_form
            actor_patterns = (
                re.compile(
                    rf"\b(?:we|i)\s+(?:(?:have|had)\s+)?"
                    rf"(?:(?:already|successfully|now)\s+)*(?:{past_form})\b"
                    rf"[^.!?\n]{{0,100}}?\b{subject_pattern}\b",
                    re.IGNORECASE,
                ),
                re.compile(
                    rf"\b(?:we|i)\s+(?:will|shall)\s+"
                    rf"(?:(?:soon|shortly|now)\s+)*(?:{base_form})\b"
                    rf"[^.!?\n]{{0,100}}?\b{subject_pattern}\b",
                    re.IGNORECASE,
                ),
                re.compile(
                    rf"\b(?:we\s+are|i\s+am)\s+"
                    rf"(?:(?:already|successfully|now|currently)\s+)*(?:{progressive_form})\b"
                    rf"[^.!?\n]{{0,100}}?\b{subject_pattern}\b",
                    re.IGNORECASE,
                ),
            )
        patterns = (
            re.compile(
                rf"\b{subject_pattern}\b[^.!?\n]{{0,100}}?\b(?:"
                rf"(?:has|have|is|are|was|were)\s+"
                rf"(?:(?:already|successfully|now|currently)\s+)*"
                rf"(?:been\s+|being\s+)?(?:{subject_completed})|"
                rf"(?:will|shall)\s+(?:(?:soon|shortly|now)\s+)*be\s+(?:{subject_completed})|"
                rf"(?:(?:is|are)\s+)?(?:being\s+)?(?:{subject_progressive}|underway|in\s+progress|ongoing)"
                rf")\b",
                re.IGNORECASE,
            ),
            re.compile(
                rf"(?:^|[;:—–]\s*)\s*(?:(?:already|successfully|now)\s+)*"
                rf"(?:{subject_completed}|{subject_progressive})\b(?:\s*[:—–|\-]\s*|\s+)"
                rf"{subject_pattern}\b",
                re.IGNORECASE,
            ),
            *actor_patterns,
        )
        for match in (match for pattern in patterns for match in pattern.finditer(shadow)):
            if _FUTURE_CONDITION_PREFIX_PATTERN.search(shadow[: match.start()]) or _has_scoped_future_contingency(
                prefix=shadow[max(0, match.start() - 180) : match.start()],
                suffix=shadow[match.end() : match.end() + 180],
            ):
                continue
            immediate_tail = unit[match.end() : match.end() + 140].lstrip(" ,\t")
            attribution = _EXTERNAL_STATE_ATTRIBUTION_PATTERN.match(immediate_tail)
            if (
                attribution is not None
                and re.match(
                    r"by\s+(?:the\s+)?customer\s+service\s+team\b",
                    immediate_tail,
                    re.IGNORECASE,
                )
                is None
            ):
                continue
            claimed_actions = [
                canonical for token in _text_tokens(match.group(0)) if (canonical := _canonical_action_token(token))
            ]
            if (
                claimed_actions
                and claimed_actions[-1] in {"approve", "archive", "delete"}
                and claimed_actions[-1] != pending_action_token
            ):
                continue
            if claimed_actions and _successful_action_backs_scope(
                claimed_action=claimed_actions[-1],
                claim_scope=unit[match.start() :],
                successful_actions=successful_actions,
            ):
                continue
            return True
    return False


def _has_unsafe_claim(
    unit: str,
    *,
    tracking_identifiers: tuple[str, ...] = (),
    successful_actions: tuple[_SuccessfulActionRecord, ...] = (),
    dynamic_subjects: tuple[tuple[str, str], ...] = (),
) -> bool:
    """Ignore completed grammar that belongs to an explicit future condition."""
    shadow = _action_claim_shadow(unit)
    for pattern in _CLAIM_PATTERNS:
        for match in pattern.finditer(shadow):
            if _FUTURE_CONDITION_PREFIX_PATTERN.search(shadow[: match.start()]):
                continue
            if _is_scoped_negative_epistemic_claim(
                prefix=shadow[: match.start()],
                claim=match.group(0),
            ):
                continue
            if pattern is _TERSE_PROGRESSIVE_ACTION_FIRST_PATTERN and _claim_is_explicitly_not_completed(unit, match):
                continue
            if pattern is _BARE_CONFIRMING_ACTION_STATE_PATTERN and _bare_confirmation_is_safely_pending(unit, match):
                continue
            if (
                pattern
                in {
                    _CONFIRMED_ACTION_STATE_PATTERN,
                    _PERFECT_CONFIRMED_ACTION_STATE_PATTERN,
                }
                and unit.lstrip().lower().startswith("no ")
                and not _NEGATIVE_CONFIRMATION_SCOPE_BREAK_PATTERN.search(shadow[: match.end()])
            ):
                continue
            if (
                pattern is _SENSITIVE_NOTE_ACTION_PATTERN
                and unit.lstrip().lower().startswith("no ")
                and not _NEGATIVE_CONFIRMATION_SCOPE_BREAK_PATTERN.search(shadow[: match.end()])
            ):
                continue
            if _is_evidence_backed_tracking_check(
                pattern=pattern,
                match=match,
                unit=unit,
                tracking_identifiers=tracking_identifiers,
            ):
                continue
            if _is_external_state_attribution(
                pattern=pattern,
                unit=unit,
                match=match,
            ):
                continue
            if _is_success_backed_action_claim(
                pattern=pattern,
                unit=unit,
                match=match,
                successful_actions=successful_actions,
            ):
                if _first_unbacked_followup_action(
                    unit=unit,
                    primary_pattern=pattern,
                    primary_match=match,
                    successful_actions=successful_actions,
                ):
                    return True
                continue
            return True
    # Definite later customer contact, action-artifact delivery, or confirmation
    # of completion is unsupported while the underlying action awaits approval.
    # Keep these distinct from ordinary conditional action grammar: adding
    # "after review" or "once complete" does not prove the promised outcome.
    for promise_pattern in _NONCONTINGENT_PENDING_ACTION_PROMISE_PATTERNS:
        for match in promise_pattern.finditer(shadow):
            if _is_scoped_negative_epistemic_claim(
                prefix=shadow[: match.start()],
                claim=match.group(0),
            ):
                continue
            if _is_external_customer_contact(
                pattern=promise_pattern,
                unit=unit,
                match=match,
            ):
                continue
            return True
    for pattern in _FUTURE_CLAIM_PATTERNS:
        for match in pattern.finditer(shadow):
            prefix = shadow[max(0, match.start() - 180) : match.start()]
            suffix = shadow[match.end() : match.end() + 180]
            if _is_scoped_negative_epistemic_claim(
                prefix=prefix,
                claim=match.group(0),
            ):
                continue
            if _future_confirmation_is_explicitly_noncomplete(
                pattern=pattern,
                unit=unit,
                match=match,
            ):
                continue
            if _has_scoped_future_contingency(prefix=prefix, suffix=suffix):
                continue
            if _is_external_customer_contact(
                pattern=pattern,
                unit=unit,
                match=match,
            ):
                continue
            if _is_success_backed_action_claim(
                pattern=pattern,
                unit=unit,
                match=match,
                successful_actions=successful_actions,
            ):
                if _first_unbacked_followup_action(
                    unit=unit,
                    primary_pattern=pattern,
                    primary_match=match,
                    successful_actions=successful_actions,
                ):
                    return True
                continue
            return True
    return _has_unsafe_dynamic_subject_claim(
        unit,
        dynamic_subjects=dynamic_subjects,
        successful_actions=successful_actions,
    )


def _preserve_safe_local_clauses(
    unit: str,
    *,
    tracking_identifiers: tuple[str, ...],
    successful_actions: tuple[_SuccessfulActionRecord, ...],
    dynamic_subjects: tuple[tuple[str, str], ...],
) -> str:
    shadow = _action_claim_shadow(unit)
    for pattern in (*_CLAIM_PATTERNS, *_FUTURE_CLAIM_PATTERNS):
        for match in pattern.finditer(shadow):
            if not _is_success_backed_action_claim(
                pattern=pattern,
                unit=unit,
                match=match,
                successful_actions=successful_actions,
            ):
                continue
            unbacked = _first_unbacked_followup_action(
                unit=unit,
                primary_pattern=pattern,
                primary_match=match,
                successful_actions=successful_actions,
            )
            if unbacked is None:
                continue
            preserved = unit[: unbacked.start("separator")].rstrip(" ,;:—–\t\n")
            if not preserved or _has_unsafe_claim(
                preserved,
                tracking_identifiers=tracking_identifiers,
                successful_actions=successful_actions,
                dynamic_subjects=dynamic_subjects,
            ):
                continue
            if preserved[-1] not in ".!?":
                preserved += "."
            return preserved
    boundaries = tuple(_LOCAL_CLAUSE_BOUNDARY_PATTERN.finditer(unit))
    if not boundaries:
        return ""
    clauses: list[str] = []
    cursor = 0
    for boundary in boundaries:
        clauses.append(unit[cursor : boundary.start()].strip(" ,;\t\n"))
        cursor = boundary.end()
    clauses.append(unit[cursor:].strip(" ,;\t\n"))
    unsafe = [
        _has_unsafe_claim(
            clause,
            tracking_identifiers=tracking_identifiers,
            successful_actions=successful_actions,
            dynamic_subjects=dynamic_subjects,
        )
        for clause in clauses
        if clause
    ]
    nonempty_clauses = [clause for clause in clauses if clause]
    if not unsafe or not any(unsafe) or all(unsafe):
        return ""
    preserved_clauses = [
        clause.rstrip(" ,;") for clause, is_unsafe in zip(nonempty_clauses, unsafe, strict=True) if not is_unsafe
    ]
    preserved = " ".join(clause for clause in preserved_clauses if clause).strip()
    if not preserved:
        return ""
    if preserved[0].islower():
        preserved = preserved[0].upper() + preserved[1:]
    if preserved[-1] not in ".!?":
        preserved += "."
    return preserved


def check_pending_action_claims(
    *,
    answer: str,
    runbook_actions: Iterable[Mapping[str, Any]],
    tool_evidence: Iterable[Mapping[str, Any]] = (),
) -> PendingActionClaimCheck:
    """Block definite active, completed, or future action claims awaiting approval.

    Conditional, contingent, negative, and explicit pending wording remains safe.
    """

    action_records = tuple(runbook_actions)
    pending_actions = _pending_action_names(action_records)
    if not pending_actions:
        return PendingActionClaimCheck()

    tracking_identifiers = (
        () if _has_pending_tracking_read(action_records) else _successful_readonly_tracking_identifiers(tool_evidence)
    )
    successful_actions = _successful_action_records(action_records)
    dynamic_subjects = _pending_dynamic_subjects(action_records)

    claims: list[str] = []
    for unit in _answer_units(answer):
        if (
            _has_unsafe_claim(
                unit,
                tracking_identifiers=tracking_identifiers,
                successful_actions=successful_actions,
                dynamic_subjects=dynamic_subjects,
            )
            and unit not in claims
        ):
            claims.append(unit[:500])
    return PendingActionClaimCheck(
        pending_actions=pending_actions,
        claims=tuple(claims[:20]),
    )


def repair_pending_action_claims(
    *,
    answer: str,
    runbook_actions: Iterable[Mapping[str, Any]],
    tool_evidence: Iterable[Mapping[str, Any]] = (),
    repair_notice: str = PENDING_ACTION_REPAIR_NOTICE,
) -> str:
    """Remove only unsafe answer units and state the remaining action status.

    The existing guard remains authoritative: normal answers are returned byte-for-byte,
    while a blocked answer loses only the exact sentence-like units that the guard marks
    unsafe. The neutral replacement is intentionally explicit about both pending and
    unconfirmed state. A final guard pass falls back to that notice alone if joining the
    preserved units ever creates another unsafe reading.
    """

    action_records = tuple(runbook_actions)
    evidence_records = tuple(tool_evidence)
    initial = check_pending_action_claims(
        answer=answer,
        runbook_actions=action_records,
        tool_evidence=evidence_records,
    )
    if not initial.blocked:
        return answer

    tracking_identifiers = (
        ()
        if _has_pending_tracking_read(action_records)
        else _successful_readonly_tracking_identifiers(evidence_records)
    )
    successful_actions = _successful_action_records(action_records)
    dynamic_subjects = _pending_dynamic_subjects(action_records)
    cursor = 0
    preserved_parts: list[str] = []
    segmentation_shadow = re.sub(
        r"(?m)(^\s*\d+)\.(?=\s*(?:\[[ xX]\]\s*)?\S)",
        r"\1 ",
        answer,
    )
    segmentation_shadow = re.sub(r"(?<!\n)\n(?!\n)", " ", segmentation_shadow)
    for match in _ANSWER_UNIT_PATTERN.finditer(segmentation_shadow):
        unit = answer[match.start() : match.end()].strip()
        if not unit or not _has_unsafe_claim(
            unit,
            tracking_identifiers=tracking_identifiers,
            successful_actions=successful_actions,
            dynamic_subjects=dynamic_subjects,
        ):
            continue
        start, end = match.span()
        preserved_parts.append(answer[cursor:start])
        preserved_parts.append(
            _preserve_safe_local_clauses(
                unit,
                tracking_identifiers=tracking_identifiers,
                successful_actions=successful_actions,
                dynamic_subjects=dynamic_subjects,
            )
        )
        cursor = end
    preserved_parts.append(answer[cursor:])
    preserved = "".join(preserved_parts).strip()
    preserved = re.sub(r"[ \t]+\n", "\n", preserved)
    preserved = re.sub(r"\n[ \t]+\n", "\n\n", preserved)
    preserved = re.sub(r"\n{3,}", "\n\n", preserved)
    notice = repair_notice.strip() or PENDING_ACTION_REPAIR_NOTICE
    repaired = f"{preserved}\n\n{notice}" if preserved else notice

    final = check_pending_action_claims(
        answer=repaired,
        runbook_actions=action_records,
        tool_evidence=evidence_records,
    )
    if not final.blocked:
        return repaired
    fallback = check_pending_action_claims(
        answer=notice,
        runbook_actions=action_records,
        tool_evidence=evidence_records,
    )
    return PENDING_ACTION_REPAIR_NOTICE if fallback.blocked else notice
