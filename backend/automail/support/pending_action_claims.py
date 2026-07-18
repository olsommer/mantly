"""Deterministic guard for customer-facing claims about pending actions."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

PENDING_ACTION_CLAIM_REASON_CODE = "pending_action_claim"
PENDING_ACTION_REPAIR_NOTICE = (
    "Any requested action that requires human review is pending and is not "
    "confirmed as started or completed."
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
    r"arranging",
    r"scheduling",
    r"issuing",
    r"refunding",
    r"cancell?ing",
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
    r"forwarding",
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
    r"arranged",
    r"scheduled",
    r"issued",
    r"refunded",
    r"cancelled",
    r"canceled",
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
    r"arrange",
    r"schedule",
    r"issue",
    r"refund",
    r"cancel",
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
    r"forward",
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
)
_ACTION_STATE_SUBJECT_PATTERN = (
    rf"(?:[a-z][a-z0-9-]*\s+){{0,3}}(?:{'|'.join(_ACTION_STATE_SUBJECTS)})"
)
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
    r"subscription",
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
)

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
_PROGRESSIVE_ACTION_PATTERN = re.compile(
    rf"\b(?:we\s+are|we['’]re|i\s+am|i['’]m)\s+"
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
_PASSIVE_ACTION_PATTERN = re.compile(
    rf"\b(?:a|an|the|this|your|our)\s+{_ACTION_STATE_SUBJECT_PATTERN}\b"
    rf"[^.!?\n]{{0,100}}?\b"
    rf"(?:has|have|is|are|was|were)\s+(?:(?:already|successfully|now|currently)\s+)*"
    rf"(?:been\s+|being\s+)?(?:{'|'.join(_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_LIFECYCLE_PASSIVE_ACTION_PATTERN = re.compile(
    rf"\b(?:a|an|the|this|your|our)\s+(?:{'|'.join(_LIFECYCLE_STATE_SUBJECTS)})\b"
    rf"[^.!?\n]{{0,100}}?\b"
    rf"(?:has|have|is|are|was|were)\s+(?:(?:already|successfully|now|currently)\s+)*"
    rf"(?:been\s+|being\s+)?(?:{'|'.join(_LIFECYCLE_COMPLETED_ACTIONS)})\b",
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
_ACTION_COMPLETION_STATE_PATTERN = re.compile(
    rf"\b(?:a|an|the|this|your|our)\s+{_ACTION_STATE_SUBJECT_PATTERN}\b"
    r"[^.!?\n,;:]{0,80}?\b(?:is|are|was|were)\s+"
    r"(?:(?:already|successfully|now)\s+)*(?:complete|completed|done)\b",
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
    rf"\b(?:we\s+will|we['’]ll|i\s+will|i['’]ll)\s+"
    rf"(?:(?:soon|shortly|now|immediately)\s+)*(?:{'|'.join(_FUTURE_ACTIONS)})\b",
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
    r"(?:our|the)\s+operations(?:\s+team)?|(?:a|the|our)\s+support\s+representative)"
)
_CONTROLLED_SUPPORT_ACTOR_CONFIRM_PATTERN = re.compile(
    rf"\b{_CONTROLLED_SUPPORT_ACTOR_PATTERN}\s+(?:will|shall)\s+"
    rf"(?!(?:not|never)\b){_ACTION_MODIFIER_PATTERN}confirm\s+"
    rf"(?:(?:a|an|the|this|your|our)\s+)?"
    rf"{_CONFIRMATION_ACTION_STATE_SUBJECT_PATTERN}\b",
    re.IGNORECASE,
)
_FUTURE_UPDATE_PROMISE_PATTERN = re.compile(
    rf"\b(?:(?:we|i)\s+will|(?:we|i)['’]ll|"
    rf"{_CONTROLLED_SUPPORT_ACTOR_PATTERN}\s+(?:will|shall))\s+"
    r"(?:be\s+able\s+to\s+)?(?:"
    r"(?:provide|send|share|give)\s+"
    r"(?:(?:you|the\s+customer)\s+(?:with\s+)?)?"
    r"(?:an?\s+)?(?:(?:further|additional)\s+)?updates?|"
    r"keep\s+(?:you|the\s+customer)\s+(?:updated|informed))\b",
    re.IGNORECASE,
)
_FUTURE_CONTACT_PROMISE_PATTERN = re.compile(
    rf"\b(?:(?:we|i)\s+will|(?:we|i)['’]ll|"
    rf"{_CONTROLLED_SUPPORT_ACTOR_PATTERN}\s+(?:will|shall))\s+"
    r"(?:be|get)\s+in\s+touch\b",
    re.IGNORECASE,
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
_ANSWER_UNIT_PATTERN = re.compile(r"[^.!?\n]+(?:[.!?]+|(?=\n)|$)")
_CLAIM_PATTERNS = (
    _PROGRESSIVE_ACTION_PATTERN,
    _PERFECT_ACTION_PATTERN,
    _COORDINATED_PERFECT_ACTION_PATTERN,
    _PAST_ACTION_PATTERN,
    _PASSIVE_ACTION_PATTERN,
    _LIFECYCLE_PASSIVE_ACTION_PATTERN,
    _ACTIVE_STATE_PATTERN,
    _ACTIVE_INTERNAL_REVIEW_STATE_PATTERN,
    _ACTION_COMPLETION_STATE_PATTERN,
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
)
_FUTURE_CLAIM_PATTERNS = (
    _FUTURE_ACTION_PATTERN,
    _FUTURE_NECESSITY_ACTION_PATTERN,
    _CONTROLLED_SUPPORT_ACTOR_FUTURE_ACTION_PATTERN,
    _OPERATIONS_FUTURE_ACTION_PATTERN,
    _FUTURE_PASSIVE_ACTION_PATTERN,
    _FUTURE_LIFECYCLE_PASSIVE_ACTION_PATTERN,
    _GERMAN_FUTURE_PATTERN,
    _GERMAN_FUTURE_PASSIVE_PATTERN,
    _FRENCH_FUTURE_PATTERN,
    _FRENCH_FUTURE_PASSIVE_PATTERN,
    _SPANISH_FUTURE_PATTERN,
    _SPANISH_FUTURE_PASSIVE_PATTERN,
    _ITALIAN_FUTURE_PATTERN,
    _ITALIAN_FUTURE_PASSIVE_PATTERN,
    _FUTURE_CONFIRM_ACTION_STATE_PATTERN,
    _FUTURE_PASSIVE_CONFIRM_ACTION_STATE_PATTERN,
    _CONTROLLED_SUPPORT_ACTOR_CONFIRM_PATTERN,
    _CAN_CONFIRM_ACTION_STATE_PATTERN,
    _FUTURE_CONTACT_PROMISE_PATTERN,
)
_CONDITION_MARKERS = (
    r"after",
    r"before",
    r"if",
    r"once",
    r"until",
    r"when",
    r"nachdem",
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
    r"dopo\s+che",
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
    r"bestätig\w*",
    r"geprüf\w*",
    r"überprüf\w*",
    r"approuv\w*",
    r"autoris\w*",
    r"confirm\w*",
    r"vérifi\w*",
    r"examin\w*",
    r"aprobad\w*",
    r"autorizad\w*",
    r"confirmad\w*",
    r"revisad\w*",
    r"verificad\w*",
    r"approvat\w*",
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
    r"\bsubject\s+to\s+(?:approval|authorization|confirmation|review|verification)"
    r"[^.!?\n]{0,40}$)",
    re.IGNORECASE,
)
_FUTURE_CONTINGENCY_SUFFIX_PATTERN = re.compile(
    rf"^\s*(?P<scope>[^.!?\n]{{0,80}}?)"
    rf"(?P<condition>\b(?:{'|'.join(_CONDITION_MARKERS)})\b)[^.!?\n]{{0,120}}"
    rf"\b(?:{'|'.join(_CONTINGENCY_TERMS)})\b",
    re.IGNORECASE,
)
_UNRELATED_CLAUSE_PATTERN = re.compile(
    r"[,;:]|\b(?:and|but|then|while|whereas|und|aber|dann|et|mais|puis|y|pero|entonces|e|ma|poi)\b",
    re.IGNORECASE,
)
_NEGATIVE_PROMISE_PREFIX_PATTERN = re.compile(
    r"\b(?:we|i)\s+(?:(?:are|am)\s+(?:unable|not\s+able)\s+to\s+|"
    r"cannot\s+|can['’]t\s+|will\s+not\s+|won['’]t\s+)"
    r"(?:promise|guarantee|confirm)\s*$",
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
_TRACKING_ID_FACT_PATHS = frozenset({
    "tracking",
    "trackingid",
    "trackingnumber",
    "trackingcode",
})
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


@dataclass(frozen=True)
class PendingActionClaimCheck:
    """Result consumed before a generated customer draft is accepted."""

    pending_actions: tuple[str, ...] = ()
    claims: tuple[str, ...] = ()

    @property
    def blocked(self) -> bool:
        return bool(self.pending_actions and self.claims)


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
        name = str(
            tool.get("name") or tool.get("toolName") or tool.get("tool_name") or ""
        ).strip()
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
            identifier = (
                str(value).strip()
                if isinstance(value, (str, int)) and not isinstance(value, bool)
                else ""
            )
            if (
                _normalized_fact_path(path) in _TRACKING_ID_FACT_PATHS
                and identifier
                and identifier not in identifiers
            ):
                identifiers.append(identifier[:240])
    return tuple(identifiers[:20])


def _has_pending_tracking_read(
    runbook_actions: Iterable[Mapping[str, Any]],
) -> bool:
    for action in runbook_actions:
        status = str(action.get("status") or "").strip().lower().replace("-", "_")
        if status != "pending_approval":
            continue
        action_text = " ".join(
            str(action.get(key) or "") for key in ("name", "label")
        ).replace("_", " ").replace("-", " ")
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
    if _TRACKING_CHECK_OBJECT_PATTERN.search(unit[match.end():]) is None:
        return False
    if _COORDINATED_ACTION_TAIL_PATTERN.search(unit[match.end():]):
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
    units = [match.group(0).strip() for match in _ANSWER_UNIT_PATTERN.finditer(answer) if match.group(0).strip()]
    return tuple(units or ([answer.strip()] if answer.strip() else []))


def _has_scoped_future_contingency(*, prefix: str, suffix: str) -> bool:
    prefix_match = _FUTURE_CONTINGENCY_PREFIX_PATTERN.search(prefix)
    if prefix_match is not None:
        condition_scope = prefix_match.group(0)
        if not any(pattern.search(condition_scope) for pattern in _FUTURE_CLAIM_PATTERNS):
            return True

    suffix_match = _FUTURE_CONTINGENCY_SUFFIX_PATTERN.search(suffix)
    if suffix_match is None:
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
    tail = unit[match.end():]
    pending_match = (
        _PENDING_CONFIRMATION_DIRECT_TAIL_PATTERN.match(tail)
        or _PENDING_CONFIRMATION_COORDINATED_TAIL_PATTERN.match(tail)
    )
    if pending_match is None:
        return False
    return _PENDING_CONFIRMATION_REVERSAL_PATTERN.search(
        tail[pending_match.end():]
    ) is None


def _has_unsafe_claim(
    unit: str,
    *,
    tracking_identifiers: tuple[str, ...] = (),
) -> bool:
    """Ignore completed grammar that belongs to an explicit future condition."""
    for pattern in _CLAIM_PATTERNS:
        for match in pattern.finditer(unit):
            if _FUTURE_CONDITION_PREFIX_PATTERN.search(unit[:match.start()]):
                continue
            if (
                pattern is _BARE_CONFIRMING_ACTION_STATE_PATTERN
                and _bare_confirmation_is_safely_pending(unit, match)
            ):
                continue
            if (
                pattern in {
                    _CONFIRMED_ACTION_STATE_PATTERN,
                    _PERFECT_CONFIRMED_ACTION_STATE_PATTERN,
                }
                and unit.lstrip().lower().startswith("no ")
                and not _NEGATIVE_CONFIRMATION_SCOPE_BREAK_PATTERN.search(
                    unit[:match.end()]
                )
            ):
                continue
            if (
                pattern is _ACTION_COMPLETION_STATE_PATTERN
                and _NEGATIVE_PROMISE_PREFIX_PATTERN.search(unit[:match.start()])
            ):
                continue
            if _is_evidence_backed_tracking_check(
                pattern=pattern,
                match=match,
                unit=unit,
                tracking_identifiers=tracking_identifiers,
            ):
                continue
            return True
    # A definite promise to provide a later update is itself an unsupported
    # customer-facing commitment while the underlying action awaits approval.
    # Keep this distinct from ordinary conditional action grammar: phrases such
    # as "once reviewed, a human agent will be able to provide updates" must not
    # survive merely because the promised update has a future condition.
    if _FUTURE_UPDATE_PROMISE_PATTERN.search(unit):
        return True
    for pattern in _FUTURE_CLAIM_PATTERNS:
        for match in pattern.finditer(unit):
            prefix = unit[max(0, match.start() - 180):match.start()]
            suffix = unit[match.end():match.end() + 180]
            if _has_scoped_future_contingency(prefix=prefix, suffix=suffix):
                continue
            return True
    return False


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
        ()
        if _has_pending_tracking_read(action_records)
        else _successful_readonly_tracking_identifiers(tool_evidence)
    )

    claims: list[str] = []
    for unit in _answer_units(answer):
        if (
            _has_unsafe_claim(unit, tracking_identifiers=tracking_identifiers)
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
    unsafe_spans = [
        match.span()
        for match in _ANSWER_UNIT_PATTERN.finditer(answer)
        if (unit := match.group(0).strip())
        and _has_unsafe_claim(unit, tracking_identifiers=tracking_identifiers)
    ]

    cursor = 0
    preserved_parts: list[str] = []
    for start, end in unsafe_spans:
        preserved_parts.append(answer[cursor:start])
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
