"""Deterministic system safety overlays for customer replies."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LITHIUM_BATTERY_SAFETY_POLICY_ID = "system:safety:damaged-lithium-battery:v1"
LITHIUM_BATTERY_SAFETY_OBLIGATION_ID = (
    "system:safety:damaged-lithium-battery:v1:immediate-guidance"
)
LITHIUM_BATTERY_SAFETY_REASON = (
    "A damaged or leaking lithium battery report requires human safety review."
)
SAFETY_GUIDANCE_MISSING_REASON_CODE = "safety_guidance_missing"
SAFETY_HUMAN_APPROVAL_REQUIRED_REASON_CODE = "safety_human_approval_required"

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_LITHIUM_BATTERY_SAFETY_POLICY = (
    _PROMPTS_DIR / "damaged_lithium_battery_safety_policy.md"
).read_text(encoding="utf-8").strip()


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
            "contextSha256": hashlib.sha256(
                self.policy_text.encode("utf-8")
            ).hexdigest(),
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
    r"swell(?:s|ing|ollen)?|bulg(?:e|ed|ing)|smok(?:e|es|ed|ing)|fire|burn(?:s|ed|ing)?|"
    r"overheat(?:s|ed|ing)?|hot|hiss(?:es|ed|ing)?|fumes?|chemical[ -]?(?:smell|odor)|"
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
    r"\bstopped|\bnicht(?:[ -]+mehr)?|\bohne|\bkein(?:e|en)?|"
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
_LOCATION_CONTAINER_ONLY_RE = re.compile(
    rf"^\s*{_LOCATION_CONTAINER_FRAGMENT}\s*$"
)
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
    r"^(?:leak(?:s|ed|ing)?|swell(?:s|ing|ollen)?|smok(?:e|es|ed|ing)|"
    r"burn(?:s|ed|ing)?|overheat(?:s|ed|ing)?|hiss(?:es|ed|ing)?|"
    r"auslauf(?:en|end|t)?|fuit|gonflee?s?|fumee|"
    r"fuga|hinchada?s?|humo|perdita|gonfia|fumo)$"
)
_EXPLICIT_HAZARD_RESOLUTION_RE = re.compile(
    r"\b(?:hazard|danger|dangerous[ -]+situation)\b[^.!?\n]{0,32}"
    r"\b(?:resolved|cleared|over|safe)\b|"
    r"\b(?:safely[ -]+disposed|no[ -]+issue[ -]+remains|"
    r"kein[ -]+problem[ -]+mehr|plus[ -]+de[ -]+danger|"
    r"problema[ -]+resuelto|problema[ -]+risolto)\b"
)
_HAZARD_RESOLUTION_MARKER_RE = re.compile(
    r"\b(?:no[ -]+longer|stopped|resolved|not|without|safe|"
    r"nicht[ -]+mehr|kein\w*|plus|sans|ya[ -]+no|sin|non[ -]+piu|senza)\b"
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
    return bool(
        _NEGATED_HAZARD_BEFORE_RE.search(before)
        or _NEGATED_HAZARD_AFTER_RE.search(after)
    )


def _hazard_targets_battery(clause: str) -> bool:
    batteries = tuple(_BATTERY_RE.finditer(clause))
    hazards = tuple(
        match for match in _HAZARD_RE.finditer(clause) if not _hazard_is_negated(clause, match)
    )
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
                hazard_to_battery = (
                    clause[hazard.end() : battery.start()]
                    if hazard.end() <= battery.start()
                    else ""
                )
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
        hazards = tuple(
            match
            for match in _HAZARD_RE.finditer(clause)
            if not _hazard_is_negated(clause, match)
        )
        if (
            previous_had_battery
            and hazards
            and re.match(r"^(?:it|this[ -]+item|this[ -]+unit|this[ -]+device)\b", clause)
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
    r"\b(?:stop|do[ -]?not|don't|cannot|can't|avoid|must[ -]?not|never|nicht|"
    r"kein(?:e|en)?|vermeiden|ne|evitez|no|non)\b|\bn['’]"
)
_HANDLING_RE = re.compile(
    r"\b(?:handl\w*|touch\w*|move\w*|anfass\w*|beruhr\w*|beweg\w*|"
    r"manipul\w*|manipol\w*|touch\w*|deplac\w*|tocar\w*|mover\w*|"
    r"toccar\w*|spostar\w*)\b"
)
_USE_RE = re.compile(
    r"\b(?:use|using|benutz\w*|verwend\w*|utilis\w*|usar\w*|utilizz\w*)\b"
)
_CHARGE_RE = re.compile(
    r"\b(?:charg(?:e|es|ed|ing)|auflad\w*|laden|recharg\w*|carg\w*|ricaric\w*)\b"
)
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
    r"\b(?:heat|flammable|combustible|warme|hitze|brennbar|chaleur|inflammable|"
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
_SMOKE_FIRE_HEAT_RE = re.compile(
    r"\b(?:smok\w*|fire|burn\w*|heat|hot|rauch\w*|feuer|heiss|hitze|fumee|feu|"
    r"incendie|chaleur|chaud\w*|humo|fuego|calor|caliente|fumo|fuoco|calore|cald\w*)\b"
)
_MOVE_AWAY_RE = re.compile(
    r"\b(?:move|step|stay|get|keep)[ -]+away\b|\bleave[ -]+the[ -]+area\b|"
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
_EMERGENCY_DIGIT_SEQUENCE_RE = re.compile(
    r"(?<!\d)\d(?:[ ().-]*\d){1,5}(?!\d)"
)
_EMERGENCY_SPELLED_NUMBER_RE = re.compile(
    r"\b(?:one[ -]+one[ -]+two|nine[ -]+one[ -]+one|"
    r"eins[ -]+eins[ -]+zwei|un[ -]+un[ -]+deux|"
    r"uno[ -]+uno[ -]+dos|uno[ -]+uno[ -]+due)\b"
)
_GUIDANCE_CLAUSE_BOUNDARY_RE = re.compile(
    r"(?:[.!?;\n]+|,\s*(?:but|however|although|while|yet|aber|jedoch|"
    r"mais|cependant|pero|aunque|ma|tuttavia)\s+)"
)
_POST_VERB_NEGATION_RE = re.compile(r"^.{0,32}\b(?:pas|plus|jamais|nicht)\b")
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
    r"por[ -]+favor|ahora|per[ -]+favore|ora)?[ ,:-]*$"
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
    r"\b(?:put|place|store|set|position|leg\w*|stell\w*|platzier\w*|"
    r"plac\w*|mett\w*|pong\w*|coloqu\w*|colloc\w*)\b"
)
_UNSAFE_PROXIMITY_RE = re.compile(
    r"\b(?:beside|next[ -]+to|close[ -]+to|near|against|by|neben|nahe|bei|pres|"
    r"a[ -]+cote|junto|cerca|vicino|accanto)\b"
)
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
    return tuple(
        clause.strip()
        for clause in _GUIDANCE_CLAUSE_BOUNDARY_RE.split(text)
        if clause.strip()
    )


def _verb_is_prohibited_in_clause(clause: str, verb_re: re.Pattern[str]) -> bool:
    for verb in verb_re.finditer(clause):
        before = clause[max(0, verb.start() - 100) : verb.start()]
        after = clause[verb.end() : verb.end() + 36]
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
        if re.search(r"\bnicht\b", after):
            return True
    return False


def _activity_is_prohibited(text: str, verb_re: re.Pattern[str]) -> bool:
    return any(
        _verb_is_prohibited_in_clause(clause, verb_re)
        for clause in _guidance_clauses(text)
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
        _UNSAFE_CONDITION_RE.search(clause)
        and _has_positive_guidance(clause, _ISOLATE_RE)
        for clause in _guidance_clauses(text)
    )


def _has_unsafe_positive_placement(text: str) -> bool:
    return any(
        (
            (
                _UNSAFE_PROXIMITY_RE.search(clause)
                and _HEAT_OR_FLAMMABLE_RE.search(clause)
            )
            or _UNSAFE_HEAT_SOURCE_PLACEMENT_RE.search(clause)
        )
        and _has_positive_guidance(clause, _PLACEMENT_RE)
        for clause in _guidance_clauses(text)
    )


def _has_jurisdiction_specific_emergency_number(text: str) -> bool:
    return any(
        _EMERGENCY_NUMBER_CONTEXT_RE.search(clause)
        and (
            _EMERGENCY_DIGIT_SEQUENCE_RE.search(clause)
            or _EMERGENCY_SPELLED_NUMBER_RE.search(clause)
        )
        for clause in _guidance_clauses(text)
    )


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
    if not (
        _ISOLATE_RE.search(text)
        and _SAFE_CONDITION_RE.search(text)
        and _HEAT_OR_FLAMMABLE_RE.search(text)
    ):
        missing.append("safe_isolation_away_from_heat_and_flammables")
    if not (
        _activity_is_prohibited(text, _SHIP_RE)
        and _activity_is_prohibited(text, _RETURN_RE)
        and _HAZARDOUS_INSTRUCTIONS_RE.search(text)
    ):
        missing.append("no_shipping_or_return_before_hazardous_goods_instructions")
    if not (
        _SMOKE_FIRE_HEAT_RE.search(text)
        and _MOVE_AWAY_RE.search(text)
        and _EMERGENCY_AUTHORITY_RE.search(text)
    ):
        missing.append("smoke_fire_heat_emergency_direction")
    if _has_jurisdiction_specific_emergency_number(text):
        missing.append("jurisdiction_specific_emergency_number")
    if _has_unsafe_positive_isolation(text) or _has_unsafe_positive_placement(text):
        missing.append("contradictory_unsafe_isolation_or_placement_guidance")
    if any(
        _has_positive_guidance(text, verb_re)
        for verb_re in (_HANDLING_RE, _USE_RE, _CHARGE_ACTIVITY_RE)
    ):
        missing.append("contradictory_handling_using_or_charging_guidance")
    if any(
        _has_positive_guidance(text, verb_re)
        for verb_re in (_SHIP_RE, _RETURN_RE)
    ):
        missing.append("contradictory_shipping_or_return_guidance")
    return tuple(dict.fromkeys(missing))
