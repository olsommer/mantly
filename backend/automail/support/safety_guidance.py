"""Deterministic system safety overlays for customer replies."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LITHIUM_BATTERY_SAFETY_POLICY_ID = "system:safety:damaged-lithium-battery:v1"
LITHIUM_BATTERY_SAFETY_OBLIGATION_ID = "system:safety:damaged-lithium-battery:v1:immediate-guidance"
LITHIUM_BATTERY_SAFETY_REASON = "A damaged or leaking lithium battery report requires human safety review."
SAFETY_GUIDANCE_MISSING_REASON_CODE = "safety_guidance_missing"
SAFETY_HUMAN_APPROVAL_REQUIRED_REASON_CODE = "safety_human_approval_required"

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_LITHIUM_BATTERY_SAFETY_POLICY = (
    (_PROMPTS_DIR / "damaged_lithium_battery_safety_policy.md").read_text(encoding="utf-8").strip()
)


@dataclass(frozen=True)
class SafetyGuidanceAssessment:
    """One allowlisted system policy activated from customer-visible text."""

    active: bool = False
    policy_id: str = ""
    policy_text: str = ""
    requires_human_reason: str = ""

    def evidence(self) -> dict[str, str]:
        if not self.active:
            return {}
        return {
            "evidenceId": self.policy_id,
            "policy": self.policy_text,
        }

    def snapshot(self) -> dict[str, str]:
        if not self.active:
            return {}
        return {
            "id": self.policy_id,
            "contextSha256": hashlib.sha256(self.policy_text.encode("utf-8")).hexdigest(),
        }

    def prompt_context(self) -> dict[str, Any]:
        if not self.active:
            return {}
        return {
            "policyId": self.policy_id,
            "requiresHuman": True,
            "obligation": {
                "id": LITHIUM_BATTERY_SAFETY_OBLIGATION_ID,
                "question": (
                    "Provide every immediate damaged-lithium-battery safety instruction "
                    "required by the system safety policy."
                ),
            },
        }

    def answer_obligation(self) -> dict[str, str]:
        if not self.active:
            return {}
        return {
            "id": LITHIUM_BATTERY_SAFETY_OBLIGATION_ID,
            "concernId": "system-safety",
            "question": (
                "Provide every immediate damaged-lithium-battery safety instruction "
                "required by the system safety policy."
            ),
        }


def lithium_battery_safety_system_prompt() -> str:
    """Return trusted policy text loaded from the colocated runtime prompt."""
    return _LITHIUM_BATTERY_SAFETY_POLICY


def _normalized(value: Any) -> str:
    folded = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in folded if not unicodedata.combining(char)).casefold()


_BATTERY_RE = re.compile(
    r"\b(?:lithium(?:[ -]?ion)?|li[ -]?ion|batter(?:y|ies)|battery[ -]?pack|"
    r"akku(?:s)?|batterie(?:n)?|pile(?:s)?[ -]?au[ -]?lithium|"
    r"bateria(?:s)?|pila(?:s)?[ -]?de[ -]?litio|batteria(?:e)?)\b"
)
_HAZARD_RE = re.compile(
    r"\b(?:leak(?:s|ed|ing)?|damag(?:e|ed)|punctur(?:e|ed)|ruptur(?:e|ed)|"
    r"crack(?:s|ed|ing)?|deform(?:s|ed|ing)?|spark(?:s|ed|ing)?|"
    r"vent(?:s|ed|ing)(?:[ -]+gas)?|vent[ -]+gas|melt(?:s|ed|ing)?|"
    r"expand(?:s|ed|ing)?|"
    r"puff(?:s|ed|ing)?[ -]+up|bloat(?:s|ed|ing)?|"
    r"swell(?:s|ing|ollen)?|bulg(?:e|ed|ing)|"
    r"smok(?:e|es|ed|ing)|fire|burn(?:s|ed|ing)?|overheat(?:s|ed|ing)?|hot|"
    r"(?:extremely|too)[ -]+warm(?:[ -]+to[ -]+touch)?|"
    r"hiss(?:es|ed|ing)?|fumes?|popping[ -]+noises?|"
    r"sizzl(?:e|es|ed|ing)|scorch(?:es|ed|ing)?|split(?:ting)?[ -]+open|"
    r"chemical(?:s)?[ -]?(?:smell|odou?r)|"
    r"(?:smell|odor|odour)(?:s|ed|ing)?(?:[ -]+strongly)?[ -]+"
    r"(?:(?:like|of)[ -]+)?chemicals?|"
    r"(?:strange[ -]+)?sweet[ -]+(?:smell|odou?r)|"
    r"auslauf(?:en|end|t)?|undicht|beschadigt|aufgeblaht|rauch(?:t|end)?|feuer|"
    r"uberhitz(?:t|ung)?|heiss|fuite|fuit|endommagee?s?|gonflee?s?|fumee|feu|chaude?s?|"
    r"fuga|derrame|danada?s?|hinchada?s?|humo|fuego|caliente|"
    r"perdita|danneggiata?s?|gonfia|fumo|fuoco|calda)\b"
)
_CLAUSE_BOUNDARY_RE = re.compile(
    r"(?:[,.!?;\n]+|\b(?:but|however|although|while|yet|aber|jedoch|"
    r"mais|cependant|pero|aunque|ma|tuttavia)\b)"
)
_CONTAINER_RE = re.compile(
    r"\b(?:outer[ -]+)?(?:box|parcel|package|packaging|carton|container|case|"
    r"karton|paket|verpackung|boite|colis|emballage|caja|paquete|embalaje|"
    r"scatola|pacco|imballaggio)\b"
)
_NEGATED_HAZARD_BEFORE_RE = re.compile(
    r"(?:\bno[ -]+longer|\bnot(?![ -]+only\b)|n't|\bwithout|\bnever|\bno\b|\bresolved|"
    r"\bstopped|\bceased|\bneither|\bnor|\bfree[ -]+(?:from|of)|"
    r"\brather[ -]+than|\bnicht(?:[ -]+mehr)?|\bohne|\bkein(?:e|en)?|"
    r"\bne\b|\bplus[ -]+de|\bsans|\bya[ -]+no|\bsin|\bnon(?:[ -]+piu)?|\bsenza)"
    r"[^.!?;\n]{0,28}$"
)
_NEGATED_HAZARD_AFTER_RE = re.compile(
    r"^[^.!?;\n]{0,24}(?:\b(?:pas|plus|jamais|mehr|non|no[ -]+more)\b|"
    r"\b(?:has|have|had|is|was|were)[ -]+(?:stopped|resolved)\b)"
)
_DIRECT_HAZARD_BATTERY_GAP_RE = re.compile(
    r"^[\s:'\"()/-]*(?:(?:lithium|li)[ -]?(?:ion)?|rechargeable|"
    r"wiederaufladbar|rechargeable|recargable|ricaricabile)?[\s:'\"()/-]*$"
)
_LOCATION_CONTAINER_FRAGMENT = (
    r"(?:in|inside|within|im|in[ -]+dem|innerhalb[ -]+(?:des|der)|"
    r"dans|a[ -]+l['’]interieur[ -]+de|en|dentro[ -]+de|del|nel|nella|"
    r"all['’]interno[ -]+(?:del|della))\s+"
    r"(?:(?:the|der|dem|des|le|la|un|une|el|los|las|il|lo|i|gli|du)\s+)?"
    r"(?:(?:outer|cardboard|damaged|ausseren|beschadigten|exterieur|endommage|"
    r"exterior|danado|esterno|danneggiato)\s+)*"
    rf"{_CONTAINER_RE.pattern}"
)
_BATTERY_HAZARD_PREDICATE_PREFIX = (
    r"(?:is|was|were|seems|appears|became|becomes|has[ -]+become|"
    r"has[ -]+started[ -]+to|started[ -]+to|has[ -]+begun[ -]+to|began[ -]+to|"
    r"ist|war|scheint|wurde|hat[ -]+angefangen[ -]+zu|"
    r"est|etait|semble|devient|a[ -]+commence[ -]+a|"
    r"esta|estaba|parece|se[ -]+volvio|tiene(?:[ -]+una?)?|"
    r"e|era|sembra|diventa|ha[ -]+iniziato[ -]+a)"
)
_LOCATION_CONTAINER_ONLY_RE = re.compile(rf"^\s*{_LOCATION_CONTAINER_FRAGMENT}\s*$")
_LOCATION_CONTAINER_PREDICATE_RE = re.compile(
    rf"^\s*{_LOCATION_CONTAINER_FRAGMENT}\s+{_BATTERY_HAZARD_PREDICATE_PREFIX}\s*$"
)
_RELATIVE_LOCATION_PREDICATE_RE = re.compile(
    rf"^\s*,?\s*(?:"
    rf"(?:which|that)\s+(?:is|was|sits|sat|is[ -]+located|was[ -]+located)\s+"
    rf"{_LOCATION_CONTAINER_FRAGMENT}|"
    rf"(?:der|die|das)\s+sich\s+{_LOCATION_CONTAINER_FRAGMENT}\s+befindet|"
    rf"qui\s+se\s+trouve\s+{_LOCATION_CONTAINER_FRAGMENT}|"
    rf"que\s+(?:esta|se[ -]+encuentra)\s+{_LOCATION_CONTAINER_FRAGMENT}|"
    rf"che\s+si\s+trova\s+{_LOCATION_CONTAINER_FRAGMENT}"
    rf")\s*,?\s*(?:{_BATTERY_HAZARD_PREDICATE_PREFIX})?\s*$"
)
_SIMPLE_RELATIVE_PREDICATE_RE = re.compile(
    r"^\s*,?\s*(?:"
    r"(?:which|that)\s+(?:is|was|seems|appears|has[ -]+been)|"
    r"(?:qui)\s*(?:est|semble)?|"
    r"(?:que)\s+(?:esta|parece|tiene(?:[ -]+una?)?)|"
    r"(?:che)\s+(?:e|era|sembra)|"
    r"(?:der|die|das)\s+(?:ist|war|scheint)"
    r")\s*$"
)
_DIRECT_PREDICATE_HAZARD_RE = re.compile(
    r"^(?:leak(?:s|ed|ing)?|crack(?:s|ed|ing)?|deform(?:s|ed|ing)?|"
    r"spark(?:s|ed|ing)?|vent(?:s|ed|ing)(?:[ -]+gas)?|vent[ -]+gas|"
    r"melt(?:s|ed|ing)?|"
    r"expand(?:s|ed|ing)?|puff(?:s|ed|ing)?[ -]+up|bloat(?:s|ed|ing)?|"
    r"swell(?:s|ing|ollen)?|"
    r"smok(?:e|es|ed|ing)|burn(?:s|ed|ing)?|overheat(?:s|ed|ing)?|"
    r"hiss(?:es|ed|ing)?|(?:extremely|too)[ -]+warm(?:[ -]+to[ -]+touch)?|"
    r"popping[ -]+noises?|sizzl(?:e|es|ed|ing)|scorch(?:es|ed|ing)?|"
    r"split(?:ting)?[ -]+open|"
    r"auslauf(?:en|end|t)?|fuit|gonflee?s?|fumee|"
    r"fuga|hinchada?s?|humo|perdita|gonfia|fumo)$"
)
_ELLIPTICAL_HAZARD_PREFIX_RE = re.compile(r"^\s*(?:(?:still|now|currently|instead)[ -]+)?$")
_EXPLICIT_HAZARD_RESOLUTION_RE = re.compile(
    r"\b(?:hazard|danger|dangerous[ -]+situation)\b[^.!?\n]{0,32}"
    r"\b(?:resolved|cleared|over|safe)\b|"
    r"\b(?:safely[ -]+disposed|no[ -]+issue[ -]+remains|"
    r"kein[ -]+problem[ -]+mehr|plus[ -]+de[ -]+danger|"
    r"problema[ -]+resuelto|problema[ -]+risolto)\b"
)
_HAZARD_RESOLUTION_MARKER_RE = re.compile(
    r"\b(?:no[ -]+longer|stopped|resolved|not|without|safe|"
    r"ceased|neither|nor|free[ -]+(?:from|of)|intact|rather[ -]+than|"
    r"nicht[ -]+mehr|kein\w*|plus|sans|ya[ -]+no|sin|non[ -]+piu|senza)\b"
)

_NONPHYSICAL_EXPANSION_AFTER_RE = re.compile(
    r"^\s+(?:(?:lithium|li[ -]?ion|battery)[ -]+)?(?:warrant(?:y|ies)|coverage|"
    r"plans?|programs?|options?|capacity|storage|range|selection|catalog)\b"
)

_CUSTOMER_DIRECTIONS = {"customer", "visitor", "inbound", "incoming"}


def _customer_bodies(messages: list[dict[str, Any]] | None) -> list[str]:
    if not isinstance(messages, list):
        return []
    bodies: list[str] = []
    for raw in messages:
        if not isinstance(raw, dict):
            continue
        body = str(raw.get("body") or "").strip()
        if not body:
            continue
        direction = str(raw.get("direction") or "").strip().casefold()
        if direction in _CUSTOMER_DIRECTIONS:
            bodies.append(body)
    return bodies


def _hazard_is_negated(clause: str, hazard: re.Match[str]) -> bool:
    before = clause[max(0, hazard.start() - 48) : hazard.start()]
    after = clause[hazard.end() : hazard.end() + 32]
    if hazard.group(0).startswith("expand") and _NONPHYSICAL_EXPANSION_AFTER_RE.search(after):
        return True
    return bool(_NEGATED_HAZARD_BEFORE_RE.search(before) or _NEGATED_HAZARD_AFTER_RE.search(after))


def _hazard_targets_battery(clause: str) -> bool:
    batteries = tuple(_BATTERY_RE.finditer(clause))
    hazards = tuple(match for match in _HAZARD_RE.finditer(clause) if not _hazard_is_negated(clause, match))
    for battery in batteries:
        for hazard in hazards:
            left, right = sorted((battery.end(), hazard.start()))
            if hazard.end() <= battery.start():
                left, right = hazard.end(), battery.start()
            between = clause[left:right]
            if len(between) > 100 or _CONTAINER_RE.search(between):
                continue
            # "battery in damaged outer box" keeps the container outside the
            # between-span. Reject when the hazard directly modifies packaging.
            after_hazard = clause[hazard.end() : hazard.end() + 36]
            if _CONTAINER_RE.match(after_hazard.lstrip(" :-")):
                continue
            before_hazard = clause[max(0, hazard.start() - 40) : hazard.start()]
            if _CONTAINER_RE.search(before_hazard):
                hazard_to_battery = clause[hazard.end() : battery.start()] if hazard.end() <= battery.start() else ""
                if not _DIRECT_HAZARD_BATTERY_GAP_RE.fullmatch(hazard_to_battery):
                    continue
            return True
    return False


def _has_explicit_battery_hazard_relation(text: str) -> bool:
    """Accept clear predicates that contain a container or relative-clause aside."""
    for battery in _BATTERY_RE.finditer(text):
        for hazard in _HAZARD_RE.finditer(text, battery.end()):
            if _hazard_is_negated(text, hazard):
                continue
            between = text[battery.end() : hazard.start()]
            if len(between) > 140:
                break
            if (
                _LOCATION_CONTAINER_PREDICATE_RE.fullmatch(between)
                or _RELATIVE_LOCATION_PREDICATE_RE.fullmatch(between)
                or _SIMPLE_RELATIVE_PREDICATE_RE.fullmatch(between)
                or (
                    _LOCATION_CONTAINER_ONLY_RE.fullmatch(between)
                    and _DIRECT_PREDICATE_HAZARD_RE.fullmatch(hazard.group(0))
                )
            ):
                return True
    return False


def _has_related_battery_hazard(text: str) -> bool:
    if _has_explicit_battery_hazard_relation(text):
        return True
    clauses = [item.strip() for item in _CLAUSE_BOUNDARY_RE.split(text) if item.strip()]
    previous_had_battery = False
    for clause in clauses:
        if _hazard_targets_battery(clause):
            return True
        hazards = tuple(match for match in _HAZARD_RE.finditer(clause) if not _hazard_is_negated(clause, match))
        if (
            previous_had_battery
            and hazards
            and (
                re.match(r"^(?:it|this[ -]+item|this[ -]+unit|this[ -]+device)\b", clause)
                or any(_ELLIPTICAL_HAZARD_PREFIX_RE.fullmatch(clause[: hazard.start()]) for hazard in hazards)
            )
            and not _CONTAINER_RE.search(clause)
        ):
            return True
        previous_had_battery = bool(_BATTERY_RE.search(clause))
    return False


def _explicitly_resolves_battery_hazard(text: str) -> bool:
    if _EXPLICIT_HAZARD_RESOLUTION_RE.search(text):
        return True
    if not _BATTERY_RE.search(text) or not _HAZARD_RESOLUTION_MARKER_RE.search(text):
        return False
    hazards = tuple(_HAZARD_RE.finditer(text))
    return bool(hazards) and all(_hazard_is_negated(text, hazard) for hazard in hazards)


def assess_lithium_battery_safety(
    *,
    subject: str = "",
    body: str = "",
    messages: list[dict[str, Any]] | None = None,
) -> SafetyGuidanceAssessment:
    """Activate policy only for a battery plus a dangerous physical condition."""
    customer_bodies = _customer_bodies(messages)
    for customer_body in reversed(customer_bodies):
        customer_text = _normalized(customer_body)
        if _has_related_battery_hazard(customer_text):
            break
        if _explicitly_resolves_battery_hazard(customer_text):
            return SafetyGuidanceAssessment()
    else:
        fallback_text = _normalized(body.strip() or subject.strip())
        if not _has_related_battery_hazard(fallback_text):
            return SafetyGuidanceAssessment()
    return SafetyGuidanceAssessment(
        active=True,
        policy_id=LITHIUM_BATTERY_SAFETY_POLICY_ID,
        policy_text=_LITHIUM_BATTERY_SAFETY_POLICY,
        requires_human_reason=LITHIUM_BATTERY_SAFETY_REASON,
    )


_NEGATIVE_DIRECTIVE_RE = re.compile(
    r"\b(?:stop|do[ -]?not|don't|cannot|can't|avoid|refrain|skip|without|"
    r"must[ -]?not|never|nicht|kein(?:e|en)?|vermeiden|ne|evitez|no|non)\b|\bn['’]"
)
_HANDLING_RE = re.compile(
    r"\b(?:handl\w*|touch\w*|mov(?:e|es|ed|ing)\b(?![ -]+away)|"
    r"hold\w*|relocat\w*|lift\w*|"
    r"pick(?:ing|ed|s)?[ -]+(?:it|the[ -]+(?:item|battery|device|unit))[ -]+up|"
    r"anfass\w*|beruhr\w*|beweg\w*|"
    r"manipul\w*|manipol\w*|touch\w*|deplac\w*|tocar\w*|mover\w*|"
    r"toccar\w*|spostar\w*)\b"
)
_USE_RE = re.compile(
    r"\b(?:use|using|"
    r"(?:power|turn|switch)(?:s|ed|ing)?[ -]+"
    r"(?:it|the[ -]+(?:item|battery|device|unit))[ -]+on|"
    r"power(?:s|ed|ing)?[ -]+on[ -]+the[ -]+(?:item|battery|device|unit)|"
    r"benutz\w*|verwend\w*|utilis\w*|usar\w*|utilizz\w*)\b"
)
_CHARGE_RE = re.compile(r"\b(?:charg(?:e|es|ed|ing)|auflad\w*|laden|recharg\w*|carg\w*|ricaric\w*)\b")
_CHARGE_ACTIVITY_RE = re.compile(
    r"\b(?:charg(?:e|es|ed|ing)|plug\w*|auflad\w*|laden|recharg\w*|carg\w*|"
    r"ricaric\w*)\b"
)
_ISOLATE_RE = re.compile(
    r"\b(?:isol\w*|separat\w*|keep[ -]+(?:it[ -]+)?away|"
    r"entfern\w*|isolier\w*|separ\w*|aisl\w*|alej\w*)\b"
)
_SAFE_CONDITION_RE = re.compile(
    r"\b(?:if|only[ -]+if|when)[^.!?\n]{0,60}\bsafe\b|"
    r"\bnur[^.!?\n]{0,60}\bsicher\b|\bwenn[^.!?\n]{0,60}\bsicher\b|"
    r"\bsi[^.!?\n]{0,60}\b(?:sur|securite|segur|sicuro)\w*\b|"
    r"\bse[^.!?\n]{0,60}\b(?:sicur|sicurezza)\w*\b"
)
_HEAT_OR_FLAMMABLE_RE = re.compile(
    r"\b(?:heat|warm|flammable|combustible|warme|hitze|brennbar|chaleur|inflammable|"
    r"calor|inflamable|calore|infiammabil|heater|radiator|heizkorper|radiateur|"
    r"calentador|termosifone|open[ -]+flame|offene[ -]+flamme|flamme[ -]+nue|"
    r"llama[ -]+abierta|fiamma[ -]+libera)\w*\b"
)
_SHIP_RE = re.compile(
    r"\b(?:ship\w*|send[ -]+(?:it|the[ -]+item)[ -]+back|transport\w*|"
    r"send[ -]+(?:the[ -]+)?(?:battery|item|unit|device)[^.!?\n]{0,24}\bback|"
    r"(?:mail|post)\w*[ -]+(?:the[ -]+)?(?:battery|item|unit|device|it)"
    r"[^.!?\n]{0,24}\bback|"
    r"take[ -]+(?:it|the[ -]+item)|bring[ -]+(?:it|the[ -]+item)|carry[ -]+(?:it|the[ -]+item)|"
    r"drop[ -]+(?:it|the[ -]+item)[ -]+off|versend\w*|verschick\w*|"
    r"send(?:en|et|est)\w*|bring\w*|expedi\w*|apport\w*|"
    r"envi\w*|llev\w*|sped\w*|port\w*)\b"
)
_RETURN_RE = re.compile(
    r"\b(?:return\w*|send[ -]+(?:it|the[ -]+item)[ -]+back|zurucksenden|"
    r"zuruckschicken|retourn\w*|devolv\w*|devuelv\w*|restitu\w*)\b"
)
_HAZARDOUS_INSTRUCTIONS_RE = re.compile(
    r"\b(?:hazardous[ -]+goods|dangerous[ -]+goods|safety|shipping|return|"
    r"gefahrgut|sicherheits|versand|rucksende|marchandises[ -]+dangereuses|"
    r"securite|expedition|mercancias[ -]+peligrosas|seguridad|envio|"
    r"merci[ -]+pericolose|sicurezza|spedizione)\w*\b[^.!?\n]{0,80}\b(?:instruction|guidance|"
    r"anweisung|hinweis|instruction|consigne|instruccion|indicacion|istruzion|indicazion)\w*\b|"
    r"\b(?:instruction|guidance|anweisung|hinweis|consigne|instruccion|indicacion|"
    r"istruzion|indicazion)\w*\b[^.!?\n]{0,80}\b(?:hazardous|dangerous|safety|shipping|"
    r"return|gefahrgut|versand|marchandises[ -]+dangereuses|securite|expedition|"
    r"mercancias[ -]+peligrosas|seguridad|envio|merci[ -]+pericolose|sicurezza|spedizione)\w*\b"
)
_HUMAN_PROVIDER_RE = re.compile(r"\b(?:human|person|mensch\w*|person\w*|humain\w*|persona\w*|uman\w*)\b")
_NEGATED_HUMAN_PROVIDER_RE = re.compile(
    r"\b(?:non[ -]+human|no[ -]+human|not[ -]+(?:a[ -]+)?human|"
    r"without[ -]+(?:a[ -]+)?human)\b"
)
_CONFIRMED_RE = re.compile(r"\b(?:confirm\w*|verified|bestatigt\w*|verifiziert\w*|confermat\w*)\b")
_NEGATED_CONFIRMATION_RE = re.compile(
    r"\b(?:unconfirmed|not[ -]+(?:yet[ -]+)?confirm\w*|"
    r"yet[ -]+to[ -]+be[ -]+confirm\w*|nicht[ -]+bestatigt\w*|"
    r"non[ -]+confirm\w*|no[ -]+confirm\w*|non[ -]+confermat\w*)\b"
)
_SMOKE_FIRE_HEAT_RE = re.compile(
    r"\b(?:smok\w*|fire|burn\w*|heat|hot|rauch\w*|feuer|heiss|hitze|fumee|feu|"
    r"incendie|chaleur|chaud\w*|humo|fuego|calor|caliente|fumo|fuoco|calore|cald\w*)\b"
)
_MOVE_AWAY_RE = re.compile(
    r"\b(?:mov(?:e|es|ed|ing)|step|stay|get|keep)[ -]+away\b|"
    r"\bleave[ -]+the[ -]+area\b|"
    r"\b(?:entfern\w*|abstand|weggehen|eloign\w*|alej\w*|allontan\w*)\b"
)
_EMERGENCY_AUTHORITY_RE = re.compile(
    r"\b(?:local[ -]+)?(?:emergency[ -]+services?|fire[ -]+(?:department|service|authority)|"
    r"notdienst|feuerwehr|services?[ -]+d'urgence|pompiers?|servicios?[ -]+de[ -]+emergencia|"
    r"bomberos?|servizi?[ -]+di[ -]+emergenza|vigili[ -]+del[ -]+fuoco)\b"
)
_EMERGENCY_NUMBER_CONTEXT_RE = re.compile(
    r"\b(?:call|dial|ring|phone|wahlen|rufen|anrufen|appeler|appelez|llam\w*|"
    r"chiam\w*|emergency[ -]+number|notrufnummer|numero[ -]+d'urgence|"
    r"numero[ -]+de[ -]+emergencia|numero[ -]+di[ -]+emergenza)\b"
)
_EMERGENCY_DIGIT_SEQUENCE_RE = re.compile(r"(?<!\d)\d(?:[ ().-]*\d){1,5}(?!\d)")
_EMERGENCY_SPELLED_NUMBER_RE = re.compile(
    r"\b(?:one[ -]+one[ -]+two|nine[ -]+one[ -]+one|"
    r"eins[ -]+eins[ -]+zwei|un[ -]+un[ -]+deux|"
    r"uno[ -]+uno[ -]+dos|uno[ -]+uno[ -]+due)\b"
)
_EVIDENCE_COLLECTION_RE = re.compile(
    r"\b(?:attach\w*|collect\w*|email\w*|gather\w*|share\w*|"
    r"tak(?:e|es|ing)|capture\w*|photograph\w*|record\w*|shoot\w*|snap\w*|"
    r"inspect\w*|examin\w*|document\w*|provide\w*|send\w*|upload\w*|"
    r"sammel\w*|aufnehm\w*|fotografier\w*|mach\w*|untersuch\w*|pruf\w*|"
    r"dokumentier\w*|bereitstell\w*|send\w*|recueill\w*|rassembl\w*|pren\w*|envoy\w*|"
    r"photographi\w*|inspect\w*|examin\w*|document\w*|fourn\w*|"
    r"recopil\w*|reun\w*|tom\w*|saqu\w*|fotografi\w*|inspeccion\w*|envi\w*|"
    r"examin\w*|document\w*|proporcion\w*|raccogli\w*|scatt\w*|facci\w*|"
    r"fotograf\w*|ispezion\w*|esamin\w*|document\w*|forn\w*|invi\w*)\b"
    r"[^.!?\n]{0,100}\b"
    r"(?:evidence|proof|photos?|pictures?|images?|videos?|documents?|condition|damage|"
    r"beweis\w*|fotos?|"
    r"nachweis\w*|preuves?|photos?|documents?|pruebas?|fotos?|documentos?|"
    r"prove|foto|documenti|zustand|schaden|etat|dommages?|estado|danos?|"
    r"condizione|danni?)\b|"
    r"\b(?:photos?|pictures?|images?|videos?|fotos?|preuves?|pruebas?|prove|foto)\b"
    r"[^.!?\n]{0,80}\b(?:attach\w*|email\w*|share\w*|record\w*|shoot\w*|"
    r"tak(?:e|es|ing)|capture\w*|snap\w*|send\w*|upload\w*|collect\w*|"
    r"aufnehm\w*|mach\w*|pren\w*|envoy\w*|saqu\w*|tom\w*|envi\w*|"
    r"scatt\w*|facci\w*|invi\w*)\b",
    re.IGNORECASE,
)
_EVIDENCE_COLLECTION_ACTIVITY_RE = re.compile(
    r"\b(?:attach\w*|collect\w*|email\w*|gather\w*|share\w*|"
    r"tak(?:e|es|ing)|capture\w*|photograph\w*|record\w*|shoot\w*|snap\w*|"
    r"inspect\w*|examin\w*|document\w*|provide\w*|send\w*|upload\w*|"
    r"sammel\w*|aufnehm\w*|fotografier\w*|mach\w*|untersuch\w*|pruf\w*|"
    r"dokumentier\w*|bereitstell\w*|send\w*|recueill\w*|rassembl\w*|pren\w*|envoy\w*|"
    r"photographi\w*|inspect\w*|examin\w*|document\w*|fourn\w*|"
    r"recopil\w*|reun\w*|tom\w*|saqu\w*|fotografi\w*|inspeccion\w*|envi\w*|"
    r"proporcion\w*|raccogli\w*|scatt\w*|facci\w*|fotograf\w*|"
    r"ispezion\w*|esamin\w*|forn\w*|invi\w*)\b",
    re.IGNORECASE,
)
_PHYSICAL_EVIDENCE_ACQUISITION_RE = re.compile(
    r"\b(?:tak(?:e|es|ing)|capture\w*|photograph\w*|record\w*|shoot\w*|snap\w*|"
    r"inspect\w*|examin\w*|"
    r"document\w*|aufnehm\w*|fotografier\w*|mach\w*|untersuch\w*|pruf\w*|"
    r"dokumentier\w*|pren\w*|photographi\w*|inspect\w*|examin\w*|"
    r"document\w*|tom\w*|saqu\w*|fotografi\w*|inspeccion\w*|scatt\w*|"
    r"facci\w*|fotograf\w*|ispezion\w*|esamin\w*)\b",
    re.IGNORECASE,
)
_NEW_EVIDENCE_RE = re.compile(
    r"\b(?:new|additional|more|further|extra|weitere?n?|zusatzlich\w*|"
    r"nouvell\w*|supplementair\w*|d['’]autres|nuev\w*|adicional\w*|mas|"
    r"nuov\w*|ulterior\w*|altr\w*)\b",
    re.IGNORECASE,
)
_EVIDENCE_DIRECTIVE_BOUNDARY_RE = re.compile(
    r"(?:"
    r",\s*(?:(?:and\s+)?(?:then|now)|(?:and\s+)?please|and|only)\s+|"
    r"\s+(?:(?:and\s+)?(?:then|now)|and\s+please|before(?:\s+you)?|"
    r"while(?:\s+you)?)\s+"
    r")",
    re.IGNORECASE,
)
_EVIDENCE_COLLECTION_PURPOSE_RE = re.compile(
    r"\b(?:to|pour|para|per|um)\b",
    re.IGNORECASE,
)
_EXISTING_EVIDENCE_RE = re.compile(
    r"\b(?:existing|already\s+(?:available|taken|captured)|currently\s+available)\s+"
    r"(?:evidence|proof|photos?|pictures?|images?|videos?|documents?)\b|"
    r"\b(?:evidence|proof|photos?|pictures?|images?|videos?|documents?)\s+"
    r"(?:already\s+(?:available|taken|captured)|currently\s+available)\b|"
    r"\b(?:vorhanden\w*|bereits\s+(?:vorhanden\w*|aufgenommen\w*))\s+"
    r"(?:beweis\w*|fotos?|nachweis\w*|dokument\w*)\b|"
    r"\b(?:beweis\w*|fotos?|nachweis\w*|dokument\w*)\s+"
    r"(?:bereits\s+(?:vorhanden\w*|aufgenommen\w*)|vorhanden\w*)\b|"
    r"\b(?:existantes?|deja\s+disponibles?)\s+(?:preuves?|photos?|documents?)\b|"
    r"\b(?:preuves?|photos?|documents?)\s+(?:deja\s+(?:disponibles?|prises?)|existantes?)\b|"
    r"\b(?:existentes?|ya\s+disponibles?)\s+(?:pruebas?|fotos?|documentos?)\b|"
    r"\b(?:pruebas?|fotos?|documentos?)\s+(?:ya\s+(?:disponibles?|tomadas?)|existentes?)\b|"
    r"\b(?:esistenti|gia\s+disponibili)\s+(?:prove|foto|documenti)\b|"
    r"\b(?:prove|foto|documenti)\s+(?:gia\s+(?:disponibili|scattate)|esistenti)\b",
    re.IGNORECASE,
)
_EVIDENCE_OBJECT_RE = re.compile(
    r"\b(?:evidence|proof|photos?|pictures?|images?|videos?|documents?|beweis\w*|fotos?|"
    r"nachweis\w*|preuves?|pruebas?|documentos?|prove|foto|documenti)\b",
    re.IGNORECASE,
)
_GUIDANCE_CLAUSE_BOUNDARY_RE = re.compile(
    r"(?:[.!?;\n]+|,\s*(?:but|however|although|while|yet|aber|jedoch|"
    r"mais|cependant|pero|aunque|ma|tuttavia)\s+)"
)
_POST_VERB_NEGATION_RE = re.compile(r"^.{0,32}\b(?:pas|plus|jamais|ni|nicht|kein\w*)\b")
_POST_VERB_NEGATIVE_PREDICATE_RE = re.compile(
    r"^.{0,64}\b(?:is|are|was|were|seems?|remains?)\s+"
    r"(?:not|never)\s+(?:recommended|allowed|advisable|required|necessary|safe)\b"
)
_PROHIBITION_WEAKENER_RE = re.compile(
    r"\b(?:unless|except|ausser|sauf|excepto|salvo|tranne)\b|"
    r"\b(?:a[ -]+menos[ -]+que|a[ -]+meno[ -]+che|es[ -]+sei[ -]+denn)\b"
)
_NEGATED_PROHIBITION_PREFIX_RE = re.compile(
    r"\b(?:do[ -]?not|don't|must[ -]+not|cannot|can't|never)[ -]+"
    r"(?:stop|cease|avoid|refrain|skip|fail|forget|hesitate)\b|"
    r"\bnot[ -]+(?:forbidden|prohibited|barred|disallowed)\b|"
    r"\bno[ -]+(?:ban|prohibition|restriction)\b|"
    r"\bhor\w*[^.!?;\n]{0,24}\bnicht[^.!?;\n]{0,24}\bauf\b|"
    r"\bne[ -]+cess\w*[^.!?;\n]{0,24}\bpas[ -]+de\b|"
    r"\bno[ -]+dej\w*[ -]+de\b|\bnon[ -]+smett\w*[ -]+di\b"
)
_EVIDENCE_NEGATIVE_PREDICATE_RE = re.compile(
    r"(?:\b(?:should|need)[ -]+not|\bshouldn't|"
    r"\bnot[ -]+(?:necessary|required)[ -]+to)\s*$"
)
_EVIDENCE_NEGATION_CONTRAST_RE = re.compile(
    r"\b(?:but|yet|instead|however|mais|cependant|pero|sin[ -]+embargo|"
    r"ma|tuttavia)\b"
)
_EVIDENCE_NEGATION_HARD_BOUNDARY_RE = re.compile(r"[:;—–]|\s[-/]\s")
_POSITIVE_PERMISSION_RE = re.compile(
    r"\b(?:can|may|must|should|safe[ -]+to|okay[ -]+to|ok[ -]+to|continue|keep|resume|"
    r"go[ -]+ahead|feel[ -]+free[ -]+to|allow\w*|permit\w*|recommend\w*|"
    r"advis\w*|proceed\w*|"
    r"konnen|durfen|weiter|erlaub\w*|empfehl\w*|rat\w*|fortfahr\w*|"
    r"pouvez|peut|continuez|reprenez|autoris\w*|recommand\w*|conseill\w*|proced\w*|"
    r"puede|puedes|continua|reanude|permit\w*|recomend\w*|aconsej\w*|proced\w*|"
    r"puo|potete|continua|riprendi|consent\w*|raccomand\w*|consigli\w*|proced\w*)\b"
)
_IMPERATIVE_LEAD_RE = re.compile(
    r"^(?:please|now|immediately|bitte|jetzt|sofort|veuillez|maintenant|"
    r"por[ -]+favor|ahora|per[ -]+favore|ora|lo|la|le)?[ ,:-]*$"
)
_POSITIVE_SCOPE_BREAK_RE = re.compile(
    r"\b(?:and|then|yet|und|et|puis|y|e)[ ,]+(?:you[ -]+|vous[ -]+|"
    r"sie[ -]+|usted[ -]+)?(?:can|may|should|continue|keep|resume|konnen|durfen|"
    r"weiter|pouvez|peut|continuez|reprenez|puede|puedes|continua|reanude|"
    r"puo|potete|riprendi)\b"
)
_UNSAFE_CONDITION_RE = re.compile(
    r"\b(?:unsafe|not[ -]+safe|regardless[ -]+of[ -]+safety|"
    r"unsicher|nicht[ -]+sicher|dangereux|pas[ -]+sur|insegur\w*|"
    r"no[ -]+segur\w*|non[ -]+sicur\w*)\b"
)
_PLACEMENT_RE = re.compile(
    r"\b(?:put|place|store|set|position|keep|leave|leg\w*|stell\w*|platzier\w*|"
    r"halt\w*|plac\w*|gard\w*|mett\w*|pong\w*|coloqu\w*|manteng\w*|"
    r"colloc\w*|teng\w*)\b"
)
_UNSAFE_PROXIMITY_RE = re.compile(
    r"\b(?:beside|next[ -]+to|close[ -]+to|adjacent[ -]+to|alongside|near|against|by|"
    r"neben|nahe|bei|pres|a[ -]+cote|junto|cerca|vicino|accanto)\b"
)
_UNSAFE_WARM_PLACEMENT_RE = re.compile(
    r"\b(?:somewhere|anywhere)[ -]+(?:warm|hot|heated)\b|"
    r"\b(?:in|into|at|to)[ -]+(?:a[ -]+)?(?:warm|hot|heated)\b|"
    r"\bkeep[ -]+(?:it[ -]+)?(?:warm|hot)\b"
)
_STAY_RE = re.compile(r"\b(?:stay|remain|wait)\w*\b")
_ITEM_REFERENCE_RE = re.compile(r"\b(?:it|item|battery|device|unit)\b")
_APPROACH_RE = re.compile(r"\b(?:approach\w*|(?:go|come|step|walk|mov(?:e|ing))[ -]+closer(?:[ -]+to)?)\b")
_UNSAFE_HEAT_SOURCE_PLACEMENT_RE = re.compile(
    r"\b(?:"
    r"(?:in|inside|into|on|onto)(?:[ -]+top[ -]+of)?[ -]+"
    r"(?:(?:a|an|the)[ -]+)?(?:"
    r"(?:hot|heated|running)[ -]+oven|(?:lit|burning)[ -]+fireplace|"
    r"direct[ -]+sunlight|(?:hot|lit|burning)[ -]+stove|"
    r"(?:space[ -]+)?heater|radiator|open[ -]+flame)|"
    r"(?:in|im|auf)(?:[ -]+(?:einen|eine|einem|einer|den|dem|die|der))?[ -]+(?:"
    r"heiss\w*[ -]+ofen|brenn\w*[ -]+kamin|direkt\w*[ -]+sonnenlicht|"
    r"offen\w*[ -]+flamme|heizkorper)|"
    r"(?:dans|sur|a[ -]+l['’]interieur[ -]+de)(?:[ -]+(?:un|une|le|la))?[ -]+(?:"
    r"four[ -]+chaud|cheminee[ -]+allumee|lumiere[ -]+directe[ -]+du[ -]+soleil|"
    r"flamme[ -]+nue|radiateur)|"
    r"(?:en|sobre|dentro[ -]+de)(?:[ -]+(?:un|una|el|la))?[ -]+(?:"
    r"horno[ -]+caliente|chimenea[ -]+encendida|luz[ -]+solar[ -]+directa|"
    r"llama[ -]+abierta|calentador|radiador)|"
    r"(?:in|dentro|su|nel|nella|sul|sulla)(?:[ -]+(?:un|una|il|lo|la))?[ -]+(?:"
    r"forno[ -]+caldo|camino[ -]+acceso|luce[ -]+solare[ -]+diretta|"
    r"fiamma[ -]+libera|stufa|radiatore)"
    r")\b"
)


def _guidance_clauses(text: str) -> tuple[str, ...]:
    return tuple(clause.strip() for clause in _GUIDANCE_CLAUSE_BOUNDARY_RE.split(text) if clause.strip())


def _verb_is_prohibited_in_clause(clause: str, verb_re: re.Pattern[str]) -> bool:
    if _PROHIBITION_WEAKENER_RE.search(clause):
        return False
    return _verb_has_negative_directive_in_clause(clause, verb_re)


def _verb_has_negative_directive_in_clause(
    clause: str,
    verb_re: re.Pattern[str],
) -> bool:
    return any(_verb_match_has_negative_directive(clause, verb) for verb in verb_re.finditer(clause))


def _verb_match_has_negative_directive(
    clause: str,
    verb: re.Match[str],
) -> bool:
    before = clause[max(0, verb.start() - 100) : verb.start()]
    after = clause[verb.end() : verb.end() + 72]
    negative_matches = tuple(_NEGATIVE_DIRECTIVE_RE.finditer(before))
    for negative in reversed(negative_matches):
        scope = before[negative.end() :]
        if _POSITIVE_SCOPE_BREAK_RE.search(scope):
            continue
        # French uses a split construction: "ne manipulez pas". Other
        # supported languages place the prohibition before the verb.
        if re.fullmatch(r"(?:ne|n['’])", negative.group(0)):
            if _POST_VERB_NEGATION_RE.search(after):
                return True
        else:
            return True
    if re.search(r"\b(?:nicht|kein\w*)\b", after):
        return True
    return bool(_POST_VERB_NEGATIVE_PREDICATE_RE.search(after))


def _activity_is_prohibited(text: str, verb_re: re.Pattern[str]) -> bool:
    return any(_verb_is_prohibited_in_clause(clause, verb_re) for clause in _guidance_clauses(text))


def _has_weakened_prohibition(text: str, verb_re: re.Pattern[str]) -> bool:
    clauses = _guidance_clauses(text)
    for index, clause in enumerate(clauses):
        if not _PROHIBITION_WEAKENER_RE.search(clause):
            continue
        if _verb_has_negative_directive_in_clause(clause, verb_re):
            return True
        if index > 0 and _verb_has_negative_directive_in_clause(clauses[index - 1], verb_re):
            return True
    return False


def _has_negated_prohibition(text: str, verb_re: re.Pattern[str]) -> bool:
    return any(
        _NEGATED_PROHIBITION_PREFIX_RE.search(clause[: verb.start()])
        for clause in _guidance_clauses(text)
        for verb in verb_re.finditer(clause)
    )


def _has_positive_guidance(text: str, verb_re: re.Pattern[str]) -> bool:
    for clause in _guidance_clauses(text):
        has_permission = bool(_POSITIVE_PERMISSION_RE.search(clause))
        for verb in verb_re.finditer(clause):
            imperative = bool(_IMPERATIVE_LEAD_RE.fullmatch(clause[: verb.start()]))
            if not has_permission and not imperative:
                continue
            if not _verb_is_prohibited_in_clause(clause, verb_re):
                return True
    return False


def _has_unsafe_positive_isolation(text: str) -> bool:
    return any(
        _UNSAFE_CONDITION_RE.search(clause) and _has_positive_guidance(clause, _ISOLATE_RE)
        for clause in _guidance_clauses(text)
    )


def _has_unsafe_positive_placement(text: str) -> bool:
    return any(
        (
            (_UNSAFE_PROXIMITY_RE.search(clause) and _HEAT_OR_FLAMMABLE_RE.search(clause))
            or _UNSAFE_HEAT_SOURCE_PLACEMENT_RE.search(clause)
            or _UNSAFE_WARM_PLACEMENT_RE.search(clause)
        )
        and (_has_positive_guidance(clause, _PLACEMENT_RE) or _has_positive_guidance(clause, _ISOLATE_RE))
        for clause in _guidance_clauses(text)
    )


def _has_unsafe_stay_near_item(text: str) -> bool:
    return any(
        _UNSAFE_PROXIMITY_RE.search(clause)
        and _ITEM_REFERENCE_RE.search(clause)
        and _has_positive_guidance(clause, _STAY_RE)
        for clause in _guidance_clauses(text)
    )


def _has_unsafe_approach_item(text: str) -> bool:
    return any(
        _ITEM_REFERENCE_RE.search(clause) and _has_positive_guidance(clause, _APPROACH_RE)
        for clause in _guidance_clauses(text)
    )


def _has_safe_isolation_guidance(text: str) -> bool:
    clauses = _guidance_clauses(text)
    if any(
        _ISOLATE_RE.search(clause) and _verb_has_negative_directive_in_clause(clause, _ISOLATE_RE) for clause in clauses
    ):
        return False
    return any(
        _ISOLATE_RE.search(clause) and _SAFE_CONDITION_RE.search(clause) and _HEAT_OR_FLAMMABLE_RE.search(clause)
        for clause in clauses
    )


_EMERGENCY_CONTACT_RE = re.compile(
    r"\b(?:contact\w*|call\w*|notify\w*|alert\w*|phone\w*|"
    r"kontaktier\w*|anruf\w*|benachrichtig\w*|appel\w*|preven\w*|"
    r"llam\w*|avis\w*|contatt\w*|chiam\w*|avvis\w*)\b"
)


def _has_confirmed_human_hazardous_instructions(text: str) -> bool:
    return any(
        _HAZARDOUS_INSTRUCTIONS_RE.search(clause)
        and _HUMAN_PROVIDER_RE.search(clause)
        and not _NEGATED_HUMAN_PROVIDER_RE.search(clause)
        and _CONFIRMED_RE.search(clause)
        and not _NEGATED_CONFIRMATION_RE.search(clause)
        for clause in _guidance_clauses(text)
    )


def _has_emergency_direction(text: str) -> bool:
    clauses = _guidance_clauses(text)
    if any(
        _MOVE_AWAY_RE.search(clause) and _verb_has_negative_directive_in_clause(clause, _MOVE_AWAY_RE)
        for clause in clauses
    ):
        return False
    if any(
        _EMERGENCY_AUTHORITY_RE.search(clause)
        and _EMERGENCY_CONTACT_RE.search(clause)
        and _verb_has_negative_directive_in_clause(clause, _EMERGENCY_CONTACT_RE)
        for clause in clauses
    ):
        return False
    return any(
        _SMOKE_FIRE_HEAT_RE.search(clause)
        and _MOVE_AWAY_RE.search(clause)
        and _EMERGENCY_CONTACT_RE.search(clause)
        and _EMERGENCY_AUTHORITY_RE.search(clause)
        for clause in clauses
    )


def _has_jurisdiction_specific_emergency_number(text: str) -> bool:
    return any(
        _EMERGENCY_NUMBER_CONTEXT_RE.search(clause)
        and (_EMERGENCY_DIGIT_SEQUENCE_RE.search(clause) or _EMERGENCY_SPELLED_NUMBER_RE.search(clause))
        for clause in _guidance_clauses(text)
    )


def _has_unsafe_evidence_collection_request(text: str) -> bool:
    """Reject evidence requests that could make a customer handle the item."""

    clauses = tuple(
        part.strip()
        for clause in _guidance_clauses(text)
        for part in _EVIDENCE_DIRECTIVE_BOUNDARY_RE.split(clause)
        if part.strip()
    )
    for index, clause in enumerate(clauses):
        collection_request = _EVIDENCE_COLLECTION_RE.search(clause)
        physical_matches = tuple(_PHYSICAL_EVIDENCE_ACQUISITION_RE.finditer(clause))
        if collection_request is None and not physical_matches:
            continue
        activity_matches = tuple(_EVIDENCE_COLLECTION_ACTIVITY_RE.finditer(clause))
        if activity_matches and all(
            _evidence_activity_match_is_prohibited(clause, activity) for activity in activity_matches
        ):
            continue
        if _NEW_EVIDENCE_RE.search(clause):
            if _activity_is_prohibited(clause, _HANDLING_RE) and _EVIDENCE_COLLECTION_PURPOSE_RE.search(clause):
                continue
            return True
        if (
            any(not _evidence_activity_match_is_prohibited(clause, activity) for activity in physical_matches)
            and _EXISTING_EVIDENCE_RE.search(clause) is None
        ):
            return True
        if _EXISTING_EVIDENCE_RE.search(clause) and _activity_is_prohibited(text, _HANDLING_RE):
            continue
        window = clauses[max(0, index - 1) : min(len(clauses), index + 2)]
        if any(
            _EXISTING_EVIDENCE_RE.search(item) and _verb_has_negative_directive_in_clause(item, _HANDLING_RE)
            for item in window
        ):
            continue
        combined = " ".join(window)
        if _EXISTING_EVIDENCE_RE.search(combined) and _activity_is_prohibited(combined, _HANDLING_RE):
            continue
        return True
    return False


def _shipping_guidance_without_existing_evidence_transfers(text: str) -> str:
    """Exclude photo-file transfers from hazardous-item shipping grammar."""

    return ". ".join(
        clause
        for clause in _guidance_clauses(text)
        if not (
            _EXISTING_EVIDENCE_RE.search(clause)
            and _EVIDENCE_OBJECT_RE.search(clause)
            and _ITEM_REFERENCE_RE.search(clause) is None
        )
    )


def _evidence_activity_match_is_prohibited(
    clause: str,
    activity: re.Match[str],
) -> bool:
    """Resolve negation for one evidence verb without leaking across a comma."""

    before = clause[max(0, activity.start() - 100) : activity.start()]
    if _EVIDENCE_NEGATIVE_PREDICATE_RE.search(before):
        return True
    if _PROHIBITION_WEAKENER_RE.search(clause) or _has_negated_prohibition(clause, _EVIDENCE_COLLECTION_ACTIVITY_RE):
        return False
    if not _verb_match_has_negative_directive(clause, activity):
        return False
    negative_matches = tuple(_NEGATIVE_DIRECTIVE_RE.finditer(before))
    if not negative_matches:
        return True
    negative = negative_matches[-1]
    scope = before[negative.end() :]
    if negative.group(0).casefold() == "without" and _HANDLING_RE.search(scope):
        return False
    if _EVIDENCE_NEGATION_CONTRAST_RE.search(scope) or _EVIDENCE_NEGATION_HARD_BOUNDARY_RE.search(scope):
        return False
    if "," in scope:
        before_comma, after_comma = scope.rsplit(",", 1)
        prior_activities = tuple(_EVIDENCE_COLLECTION_ACTIVITY_RE.finditer(before_comma.rstrip()))
        coordinated_list = bool(
            prior_activities
            and prior_activities[-1].end() == len(before_comma.rstrip())
            and re.fullmatch(r"\s*(?:(?:or|nor)\s*)?", after_comma)
        )
        if not coordinated_list:
            return False
    return True


def lithium_battery_reply_safety_blocked_reason(
    *,
    subject: str,
    messages: list[dict[str, Any]] | None,
    answer: str,
) -> str:
    """Return stable fail-closed reason for an unsafe active-hazard reply."""
    assessment = assess_lithium_battery_safety(
        subject=subject,
        messages=messages,
    )
    if not assessment.active:
        return ""
    missing = missing_lithium_battery_safety_guidance(answer)
    if not missing:
        return ""
    return SAFETY_GUIDANCE_MISSING_REASON_CODE + ": " + ", ".join(missing)


def missing_lithium_battery_safety_guidance(answer: str) -> tuple[str, ...]:
    """Return required policy concepts absent from customer-facing prose."""
    text = _normalized(answer)
    missing: list[str] = []
    if not (
        _activity_is_prohibited(text, _HANDLING_RE)
        and _activity_is_prohibited(text, _USE_RE)
        and _activity_is_prohibited(text, _CHARGE_RE)
    ):
        missing.append("stop_handling_using_charging")
    if not _has_safe_isolation_guidance(text):
        missing.append("safe_isolation_away_from_heat_and_flammables")
    if not (
        _activity_is_prohibited(text, _SHIP_RE)
        and _activity_is_prohibited(text, _RETURN_RE)
        and _has_confirmed_human_hazardous_instructions(text)
    ):
        missing.append("no_shipping_or_return_before_hazardous_goods_instructions")
    if not _has_emergency_direction(text):
        missing.append("smoke_fire_heat_emergency_direction")
    if _has_jurisdiction_specific_emergency_number(text):
        missing.append("jurisdiction_specific_emergency_number")
    if _has_unsafe_evidence_collection_request(text):
        missing.append("no_handling_to_collect_evidence")
    if (
        _has_unsafe_positive_isolation(text)
        or _has_unsafe_positive_placement(text)
        or _has_unsafe_stay_near_item(text)
        or _has_unsafe_approach_item(text)
        or _activity_is_prohibited(text, _ISOLATE_RE)
        or _has_weakened_prohibition(text, _ISOLATE_RE)
        or _has_negated_prohibition(text, _ISOLATE_RE)
    ):
        missing.append("contradictory_unsafe_isolation_or_placement_guidance")
    if any(
        _has_positive_guidance(text, verb_re)
        or _has_weakened_prohibition(text, verb_re)
        or _has_negated_prohibition(text, verb_re)
        for verb_re in (_HANDLING_RE, _USE_RE, _CHARGE_ACTIVITY_RE)
    ):
        missing.append("contradictory_handling_using_or_charging_guidance")
    shipping_guidance = _shipping_guidance_without_existing_evidence_transfers(text)
    if any(
        _has_positive_guidance(shipping_guidance, verb_re)
        or _has_weakened_prohibition(shipping_guidance, verb_re)
        or _has_negated_prohibition(shipping_guidance, verb_re)
        for verb_re in (_SHIP_RE, _RETURN_RE)
    ):
        missing.append("contradictory_shipping_or_return_guidance")
    return tuple(dict.fromkeys(missing))
