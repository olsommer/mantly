from __future__ import annotations

import json
from contextlib import nullcontext
from typing import Any

import pytest

from automail import llm as llm_module
from automail.core import config as config_module
from automail.llm import usage as usage_module
from automail.pipeline.response.prompt_factory import create_response_system_prompt
from automail.support import issue_agent
from automail.support.issue_agent import (
    AutomationAnswerOutput,
    AutomationGroundingObligationAssessment,
    AutomationGroundingOutput,
    AutomationGroundingUnitAssessment,
)
from automail.support.safety_guidance import (
    LITHIUM_BATTERY_SAFETY_OBLIGATION_ID,
    LITHIUM_BATTERY_SAFETY_POLICY_ID,
    SAFETY_GUIDANCE_MISSING_REASON_CODE,
    assess_lithium_battery_safety,
    lithium_battery_reply_safety_blocked_reason,
    missing_lithium_battery_safety_guidance,
)

_HAZARD_MESSAGES = [
    {
        "direction": "customer",
        "body": (
            "The parcel contains a leaking lithium battery pack. It smells chemical "
            "and is getting hot. What should we do?"
        ),
    }
]
_COMPLETE_GUIDANCE = (
    "Stop handling, using, and charging the item immediately. "
    "Isolate it only if this can be done safely, and keep it away from heat and "
    "flammable materials only if safe. Do not ship or return it until you receive "
    "confirmed hazardous-goods instructions after human review. If smoke, fire, or "
    "unusual heat is present or develops, move away and contact local emergency "
    "services or the local fire authority."
)
_COMPLETE_FRENCH_GUIDANCE = (
    "Ne manipulez pas, n'utilisez pas et ne rechargez pas l'article. "
    "Isolez-le uniquement si cela peut être fait en toute sécurité, et gardez-le "
    "à l'écart de la chaleur et des matières inflammables uniquement si c'est sûr. "
    "Ne l'expédiez pas et ne le retournez pas avant d'avoir reçu d'une personne des "
    "consignes confirmées pour les marchandises dangereuses. En cas de fumée, d'incendie ou "
    "de chaleur inhabituelle, éloignez-vous et contactez les services d'urgence "
    "locaux ou les pompiers."
)
_COMPLETE_GERMAN_GUIDANCE = (
    "Nicht berühren. Nicht benutzen. Nicht laden. "
    "Isolieren Sie den Artikel nur, wenn dies sicher möglich ist, und halten Sie "
    "ihn nur wenn sicher von Hitze und brennbaren Materialien fern. Nicht versenden "
    "oder zurücksenden, bevor Sie von einem Menschen bestätigte Gefahrgut-Anweisungen "
    "erhalten. Wenn "
    "Rauch, Feuer oder ungewöhnliche Hitze auftritt, entfernen Sie sich und "
    "kontaktieren Sie den örtlichen Notdienst oder die Feuerwehr."
)
_COMPLETE_SPANISH_GUIDANCE = (
    "No manipule, use ni cargue el artículo. Aíslelo solo si puede hacerse de forma "
    "segura y manténgalo alejado del calor y de materiales inflamables, solo si es "
    "seguro. No lo envíe ni lo devuelva antes de recibir de una persona instrucciones "
    "confirmadas de seguridad para mercancías peligrosas. Si hay humo, fuego o calor inusual, "
    "aléjese y contacte los servicios de emergencia locales o los bomberos."
)
_COMPLETE_ITALIAN_GUIDANCE = (
    "Non manipoli, non utilizzi e non ricarichi l'articolo. Lo isoli solo se può "
    "farlo in sicurezza e lo tenga lontano dal calore e dai materiali infiammabili, "
    "solo se è sicuro. Non lo spedisca né lo restituisca prima di ricevere da una persona "
    "istruzioni confermate di sicurezza per merci pericolose. In caso di fumo, fuoco o calore "
    "insolito, si allontani e contatti i servizi di emergenza locali o i vigili del "
    "fuoco."
)


@pytest.mark.parametrize(
    "text",
    [
        "A leaking lithium battery pack has a chemical smell.",
        "The damaged battery is swollen and hot.",
        "Der Lithium-Akku ist beschädigt, undicht und heiß.",
    ],
)
def test_damaged_lithium_battery_policy_detection(text: str) -> None:
    assessment = assess_lithium_battery_safety(body=text)

    assert assessment.active is True
    assert assessment.policy_id == LITHIUM_BATTERY_SAFETY_POLICY_ID
    assert assessment.prompt_context()["obligation"]["id"] == (LITHIUM_BATTERY_SAFETY_OBLIGATION_ID)


@pytest.mark.parametrize(
    "text",
    [
        "The battery smells like chemicals.",
        "The battery smells chemical.",
        "The battery smells strongly of chemicals.",
        "The battery has a chemicals smell.",
        "The battery is sparking.",
        "The battery is cracked.",
        "The battery is deformed.",
        "The battery is venting gas.",
        "The battery is extremely warm.",
        "The battery has melted.",
        "The battery is puffed up.",
        "The battery has expanded.",
        "The battery is bloated.",
        "The battery is too warm to touch.",
        "The battery has a strange sweet smell.",
        "The battery casing has split open.",
        "The battery is making popping noises.",
        "The battery is sizzling.",
        "The battery is scorching.",
    ],
)
def test_additional_dangerous_battery_conditions_activate_policy(text: str) -> None:
    assert assess_lithium_battery_safety(body=text).active is True


@pytest.mark.parametrize(
    "text",
    [
        "The battery is neither cracked nor deformed, but sparking.",
        "The battery is free from cracks but still too warm to touch.",
        "The battery is intact rather than cracked, but now sizzling.",
    ],
)
def test_resolved_condition_does_not_hide_another_active_hazard(text: str) -> None:
    assert assess_lithium_battery_safety(body=text).active is True


@pytest.mark.parametrize(
    "text",
    [
        "Where can I buy a replacement battery?",
        "Where is the battery vent shown in the manual?",
        "The battery is neither cracked nor deformed.",
        "The battery is free from cracks and deformation.",
        "The battery is intact rather than cracked.",
        "The battery has ceased sparking.",
        "The battery has an expanded warranty.",
        "We offer expanded battery coverage.",
        "The cardboard box is damaged, but it contains only clothing.",
        "Please send the battery-powered scanner manual.",
    ],
)
def test_normal_battery_or_parcel_messages_do_not_activate_hazard_policy(
    text: str,
) -> None:
    assert assess_lithium_battery_safety(body=text).active is False


@pytest.mark.parametrize(
    "text",
    [
        "The battery works normally, but the outer box is damaged.",
        "The battery works normally and the outer box is damaged.",
        "The damaged outer box contains an intact battery.",
        "The battery is in a damaged outer box and remains intact.",
    ],
)
def test_packaging_damage_does_not_activate_battery_hazard_policy(text: str) -> None:
    assert assess_lithium_battery_safety(body=text).active is False


@pytest.mark.parametrize(
    "resolved_text",
    [
        "The battery is neither cracked nor deformed.",
        "The battery is free from cracks and deformation.",
        "The battery is intact rather than cracked.",
        "The battery has ceased sparking.",
    ],
)
def test_latest_resolved_new_hazard_description_clears_prior_report(
    resolved_text: str,
) -> None:
    assessment = assess_lithium_battery_safety(
        messages=[
            {
                "direction": "customer",
                "body": "The lithium battery was cracked and sparking.",
            },
            {"direction": "customer", "body": resolved_text},
        ]
    )

    assert assessment.active is False


def test_latest_customer_message_overrides_stale_hazard_subject() -> None:
    assessment = assess_lithium_battery_safety(
        subject="Urgent: leaking lithium battery",
        messages=[
            {
                "direction": "customer",
                "body": "The lithium battery was leaking and hot.",
            },
            {
                "direction": "agent",
                "body": "Please confirm whether the situation remains active.",
            },
            {
                "direction": "customer",
                "body": "Resolved. The item was safely disposed of and no issue remains.",
            },
        ],
    )

    assert assessment.active is False


def test_latest_customer_message_can_explicitly_negate_prior_battery_hazard() -> None:
    assessment = assess_lithium_battery_safety(
        subject="Urgent: leaking lithium battery",
        messages=[
            {
                "direction": "customer",
                "body": "The battery leak has stopped and it is no longer hot.",
            }
        ],
    )

    assert assessment.active is False


def test_ordinary_follow_up_does_not_clear_unresolved_battery_hazard() -> None:
    assessment = assess_lithium_battery_safety(
        subject="Order problem",
        messages=[
            {
                "direction": "customer",
                "body": "The lithium battery is leaking and getting hot.",
            },
            {
                "direction": "agent",
                "body": "We are reviewing this now.",
            },
            {
                "direction": "customer",
                "body": "Can you send the replacement today?",
            },
        ],
    )

    assert assessment.active is True


def test_unrelated_order_resolution_does_not_clear_battery_hazard() -> None:
    assessment = assess_lithium_battery_safety(
        messages=[
            {
                "direction": "customer",
                "body": "The lithium battery is leaking and getting hot.",
            },
            {
                "direction": "customer",
                "body": "The replacement order problem is resolved.",
            },
        ],
    )

    assert assessment.active is True


def test_explicit_latest_customer_resolution_clears_prior_battery_hazard() -> None:
    assessment = assess_lithium_battery_safety(
        messages=[
            {
                "direction": "customer",
                "body": "The lithium battery is leaking and getting hot.",
            },
            {
                "direction": "customer",
                "body": ("The battery is no longer leaking or hot and the issue is resolved."),
            },
        ],
    )

    assert assessment.active is False


def test_resolved_leak_does_not_hide_a_separate_current_heat_hazard() -> None:
    assessment = assess_lithium_battery_safety(body="The battery leak has stopped, but it is still unusually hot.")

    assert assessment.active is True


def test_not_only_hot_but_smoking_is_an_active_battery_hazard() -> None:
    assessment = assess_lithium_battery_safety(body="The lithium battery is not only hot, but smoking.")

    assert assessment.active is True


@pytest.mark.parametrize(
    "text",
    [
        "The lithium battery in the parcel is leaking.",
        "The lithium battery, which is leaking, smells chemical.",
        "Der Lithium-Akku im Paket ist undicht.",
        "La batterie dans le colis fuit.",
        "La batería del paquete tiene una fuga.",
        "La batteria, che si trova nel pacco, è gonfia.",
        "The battery inside the cardboard box has started to swell.",
        "The battery, which is inside the cardboard box, has started to swell.",
        "Der Lithium-Akku, der sich im Paket befindet, ist undicht.",
        "La batterie, qui se trouve dans le colis, fuit.",
        "La batería, que está en el paquete, tiene una fuga.",
    ],
)
def test_natural_container_and_relative_clause_battery_hazards_activate(
    text: str,
) -> None:
    assert assess_lithium_battery_safety(body=text).active is True


def test_safety_guidance_checker_requires_every_immediate_policy_element() -> None:
    assert missing_lithium_battery_safety_guidance(_COMPLETE_GUIDANCE) == ()

    missing = missing_lithium_battery_safety_guidance("Please isolate the leaking battery and wait for our team.")

    assert set(missing) == {
        "stop_handling_using_charging",
        "safe_isolation_away_from_heat_and_flammables",
        "no_shipping_or_return_before_hazardous_goods_instructions",
        "smoke_fire_heat_emergency_direction",
    }


def test_plug_prohibition_does_not_replace_general_no_charging_guidance() -> None:
    answer = (
        "Stop handling and using the item. Do not plug it into this charger. "
        "Isolate it only if safe and keep it away from heat and flammable materials. "
        "Do not ship or return it before hazardous-goods instructions. If there is "
        "smoke, fire, or unusual heat, move away and contact local emergency services."
    )

    missing = missing_lithium_battery_safety_guidance(answer)

    assert "stop_handling_using_charging" in missing


def test_compliant_french_ne_verb_pas_guidance_passes() -> None:
    assert missing_lithium_battery_safety_guidance(_COMPLETE_FRENCH_GUIDANCE) == ()


@pytest.mark.parametrize(
    "guidance",
    [
        _COMPLETE_GERMAN_GUIDANCE,
        _COMPLETE_SPANISH_GUIDANCE,
        _COMPLETE_ITALIAN_GUIDANCE,
    ],
)
def test_complete_multilingual_guidance_passes(guidance: str) -> None:
    assert missing_lithium_battery_safety_guidance(guidance) == ()


@pytest.mark.parametrize(
    ("contradiction", "expected_code"),
    [
        (
            "You may continue using and charging it.",
            "contradictory_handling_using_or_charging_guidance",
        ),
        (
            "Do not handle it and continue using or charging it.",
            "contradictory_handling_using_or_charging_guidance",
        ),
        (
            "You may ship or return it now.",
            "contradictory_shipping_or_return_guidance",
        ),
        (
            "You are allowed to charge it.",
            "contradictory_handling_using_or_charging_guidance",
        ),
        (
            "We recommend charging it.",
            "contradictory_handling_using_or_charging_guidance",
        ),
        (
            "Please proceed with charging it.",
            "contradictory_handling_using_or_charging_guidance",
        ),
        (
            "Please plug it into the charger.",
            "contradictory_handling_using_or_charging_guidance",
        ),
        (
            "Feel free to charge it.",
            "contradictory_handling_using_or_charging_guidance",
        ),
        (
            "We advise you to return it now.",
            "contradictory_shipping_or_return_guidance",
        ),
        (
            "Please proceed to ship it back.",
            "contradictory_shipping_or_return_guidance",
        ),
        (
            "Please send the battery back now.",
            "contradictory_shipping_or_return_guidance",
        ),
        (
            "Mail the battery back now.",
            "contradictory_shipping_or_return_guidance",
        ),
        (
            "Wir empfehlen, es zu laden.",
            "contradictory_handling_using_or_charging_guidance",
        ),
        (
            "Nous vous conseillons de le retourner.",
            "contradictory_shipping_or_return_guidance",
        ),
        (
            "Recomendamos enviarlo ahora.",
            "contradictory_shipping_or_return_guidance",
        ),
        (
            "Consigliamo di spedirla.",
            "contradictory_shipping_or_return_guidance",
        ),
        (
            "Isolate it even if unsafe.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
        (
            "Put it beside a heater.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
        (
            "Place it close to a radiator.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
        (
            "Set it next to an open flame.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
        (
            "Place it in a hot oven.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
        (
            "Put it inside a lit fireplace.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
        (
            "Store it in direct sunlight.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
        (
            "Place it on a burning stove.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
        (
            "Set it inside a heater.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
        (
            "Put it on the radiator.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
        (
            "Place it on an open flame.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
        (
            "Legen Sie ihn in einen heißen Ofen.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
        (
            "Placez-le dans un four chaud.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
        (
            "Colóquelo en un horno caliente.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
        (
            "Collocarlo in un forno caldo.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
    ],
)
def test_contradictory_positive_guidance_fails_closed(
    contradiction: str,
    expected_code: str,
) -> None:
    missing = missing_lithium_battery_safety_guidance(_COMPLETE_GUIDANCE + " " + contradiction)

    assert expected_code in missing


@pytest.mark.parametrize(
    "ordinary_storage_guidance",
    [
        "Store the unopened replacement in ordinary cold storage.",
        "Place the paperwork on a cold storage shelf.",
        "Do not place the battery in a hot oven.",
    ],
)
def test_ordinary_cold_storage_and_prohibitions_do_not_trigger_unsafe_placement(
    ordinary_storage_guidance: str,
) -> None:
    assert missing_lithium_battery_safety_guidance(_COMPLETE_GUIDANCE + " " + ordinary_storage_guidance) == ()


def test_unrelated_negative_clause_does_not_prohibit_shipping_or_return() -> None:
    answer = (
        "Do not handle, use, or charge the item. "
        "Isolate it only if safe and keep it away from heat and flammable materials. "
        "Do not touch the packaging. Ship or return it after hazardous-goods instructions. "
        "If there is smoke, fire, or unusual heat, move away and contact local emergency "
        "services or the fire authority."
    )

    missing = missing_lithium_battery_safety_guidance(answer)

    assert "no_shipping_or_return_before_hazardous_goods_instructions" in missing


@pytest.mark.parametrize(
    ("weakened_prohibition", "expected_code"),
    [
        (
            "Stop handling and using the item, but do not charge it unless supervised.",
            "stop_handling_using_charging",
        ),
        (
            "Do not handle, use, or charge the item except in an emergency.",
            "stop_handling_using_charging",
        ),
        (
            "Do not ship or return it unless support approves it.",
            "no_shipping_or_return_before_hazardous_goods_instructions",
        ),
        (
            "Do not ship or return it except when a courier is available.",
            "no_shipping_or_return_before_hazardous_goods_instructions",
        ),
    ],
)
def test_unless_or_except_does_not_satisfy_absolute_prohibition(
    weakened_prohibition: str,
    expected_code: str,
) -> None:
    answer = (
        weakened_prohibition
        + " Isolate it only if safe and keep it away from heat and flammable materials. "
        + "Follow confirmed hazardous-goods instructions after human review. If smoke, "
        + "fire, or unusual heat develops, move away and contact local emergency services."
    )

    assert expected_code in missing_lithium_battery_safety_guidance(answer)


@pytest.mark.parametrize(
    ("weakened_prohibition", "expected_code"),
    [
        (
            "Do not charge it unless supervised.",
            "contradictory_handling_using_or_charging_guidance",
        ),
        (
            "Do not handle it except when wearing gloves.",
            "contradictory_handling_using_or_charging_guidance",
        ),
        (
            "Do not ship it unless a courier accepts it.",
            "contradictory_shipping_or_return_guidance",
        ),
        (
            "Do not return it except during business hours.",
            "contradictory_shipping_or_return_guidance",
        ),
    ],
)
def test_weakened_prohibition_contradicts_otherwise_complete_guidance(
    weakened_prohibition: str,
    expected_code: str,
) -> None:
    missing = missing_lithium_battery_safety_guidance(_COMPLETE_GUIDANCE + " " + weakened_prohibition)

    assert expected_code in missing


@pytest.mark.parametrize(
    ("detached_exception", "expected_code"),
    [
        (
            "Do not charge it. Unless supervised.",
            "contradictory_handling_using_or_charging_guidance",
        ),
        (
            "Do not ship it. Except when a courier accepts it.",
            "contradictory_shipping_or_return_guidance",
        ),
    ],
)
def test_detached_exception_still_weakens_prohibition(
    detached_exception: str,
    expected_code: str,
) -> None:
    assert expected_code in missing_lithium_battery_safety_guidance(_COMPLETE_GUIDANCE + " " + detached_exception)


@pytest.mark.parametrize(
    ("negated_prohibition", "expected_code"),
    [
        (
            "Do not stop handling, using, or charging the item.",
            "contradictory_handling_using_or_charging_guidance",
        ),
        (
            "You are not forbidden from charging the item.",
            "contradictory_handling_using_or_charging_guidance",
        ),
        (
            "There is no ban on charging the item.",
            "contradictory_handling_using_or_charging_guidance",
        ),
        (
            "Do not avoid shipping or returning the item.",
            "contradictory_shipping_or_return_guidance",
        ),
    ],
)
def test_negating_a_prohibition_fails_closed(
    negated_prohibition: str,
    expected_code: str,
) -> None:
    assert expected_code in missing_lithium_battery_safety_guidance(_COMPLETE_GUIDANCE + " " + negated_prohibition)


@pytest.mark.parametrize(
    ("guidance", "unsafe_direction", "expected_code"),
    [
        (
            _COMPLETE_GERMAN_GUIDANCE,
            "Halten Sie ihn nahe an Hitze.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
        (
            _COMPLETE_GERMAN_GUIDANCE,
            "Hören Sie nicht auf, ihn zu laden.",
            "contradictory_handling_using_or_charging_guidance",
        ),
        (
            _COMPLETE_FRENCH_GUIDANCE,
            "Gardez-le près de la chaleur.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
        (
            _COMPLETE_FRENCH_GUIDANCE,
            "Ne cessez pas de le recharger.",
            "contradictory_handling_using_or_charging_guidance",
        ),
        (
            _COMPLETE_SPANISH_GUIDANCE,
            "Manténgalo cerca del calor.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
        (
            _COMPLETE_SPANISH_GUIDANCE,
            "No deje de cargarlo.",
            "contradictory_handling_using_or_charging_guidance",
        ),
        (
            _COMPLETE_ITALIAN_GUIDANCE,
            "Lo tenga vicino al calore.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
        (
            _COMPLETE_ITALIAN_GUIDANCE,
            "Non smetta di ricaricarla.",
            "contradictory_handling_using_or_charging_guidance",
        ),
    ],
)
def test_supported_language_unsafe_variants_fail_closed(
    guidance: str,
    unsafe_direction: str,
    expected_code: str,
) -> None:
    assert expected_code in missing_lithium_battery_safety_guidance(guidance + " " + unsafe_direction)


@pytest.mark.parametrize(
    "instruction_source",
    [
        "an AI provides confirmed hazardous-goods instructions",
        "a bot provides confirmed hazardous-goods instructions",
        "automated confirmed hazardous-goods instructions arrive",
        "a human provides unconfirmed hazardous-goods instructions",
        "a human provides not yet confirmed hazardous-goods instructions",
        "a non-human provides confirmed hazardous-goods instructions",
        "no human provides confirmed hazardous-goods instructions",
        "an AI, not a human, provides confirmed hazardous-goods instructions",
        "someone provides confirmed hazardous-goods instructions",
    ],
)
def test_shipping_waits_for_confirmed_human_instructions(
    instruction_source: str,
) -> None:
    answer = (
        "Do not handle, use, or charge the item. Isolate it only if safe and keep it "
        "away from heat and flammable materials. Do not ship or return it until "
        + instruction_source
        + ". If smoke, fire, or unusual heat develops, move away and contact local "
        "emergency services."
    )

    assert "no_shipping_or_return_before_hazardous_goods_instructions" in (
        missing_lithium_battery_safety_guidance(answer)
    )


@pytest.mark.parametrize(
    "unsafe_placement",
    [
        "Keep it near heat.",
        "Leave it next to flammable materials.",
        "Isolate it near a heater, even if that can be done safely.",
        "Keep it adjacent to a heater.",
        "Keep it alongside flammable materials.",
        "Keep it somewhere warm.",
    ],
)
def test_near_heat_or_flammable_placement_fails_closed(
    unsafe_placement: str,
) -> None:
    missing = missing_lithium_battery_safety_guidance(_COMPLETE_GUIDANCE + " " + unsafe_placement)

    assert "contradictory_unsafe_isolation_or_placement_guidance" in missing


@pytest.mark.parametrize(
    "safe_direction",
    [
        "Keep it away from warm areas.",
        "Keep it far from any warm location.",
        "Move away from the battery immediately.",
        "Move away from it.",
    ],
)
def test_safe_distance_directions_remain_allowed(safe_direction: str) -> None:
    assert missing_lithium_battery_safety_guidance(_COMPLETE_GUIDANCE + " " + safe_direction) == ()


@pytest.mark.parametrize(
    ("unsafe_direction", "expected_code"),
    [
        (
            "Stay beside it while you call emergency services.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
        (
            "Approach the battery and call emergency services.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
        (
            "Go closer to it.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
        (
            "Pick it up with gloves.",
            "contradictory_handling_using_or_charging_guidance",
        ),
        (
            "Hold it carefully.",
            "contradictory_handling_using_or_charging_guidance",
        ),
        (
            "Relocate it to another room.",
            "contradictory_handling_using_or_charging_guidance",
        ),
        (
            "Power it on briefly.",
            "contradictory_handling_using_or_charging_guidance",
        ),
        (
            "Turn it on to check it.",
            "contradictory_handling_using_or_charging_guidance",
        ),
    ],
)
def test_additional_unsafe_directions_fail_closed(
    unsafe_direction: str,
    expected_code: str,
) -> None:
    assert expected_code in missing_lithium_battery_safety_guidance(_COMPLETE_GUIDANCE + " " + unsafe_direction)


def test_negated_isolation_fails_closed() -> None:
    answer = (
        "Do not handle, use, or charge the item. Do not isolate it, even if safe; "
        "keep it away from heat and flammable materials. Do not ship or return it "
        "before hazardous-goods instructions. If smoke, fire, or unusual heat develops, "
        "move away and contact local emergency services."
    )

    missing = missing_lithium_battery_safety_guidance(answer)

    assert "safe_isolation_away_from_heat_and_flammables" in missing
    assert "contradictory_unsafe_isolation_or_placement_guidance" in missing


@pytest.mark.parametrize(
    "negated_isolation",
    [
        "Isolation is not recommended.",
        "Isolating the item is not allowed.",
    ],
)
def test_post_verb_negated_isolation_fails_closed(
    negated_isolation: str,
) -> None:
    missing = missing_lithium_battery_safety_guidance(_COMPLETE_GUIDANCE + " " + negated_isolation)

    assert "safe_isolation_away_from_heat_and_flammables" in missing
    assert "contradictory_unsafe_isolation_or_placement_guidance" in missing


@pytest.mark.parametrize(
    "negated_emergency_direction",
    [
        ("If smoke, fire, or unusual heat develops, do not move away and contact local emergency services."),
        ("If smoke, fire, or unusual heat develops, move away and do not contact local emergency services."),
        ("If smoke develops, move away without contacting local emergency services."),
        ("Moving away is not recommended."),
        ("Contacting emergency services is not recommended."),
    ],
)
def test_negated_emergency_action_fails_closed(
    negated_emergency_direction: str,
) -> None:
    answer = _COMPLETE_GUIDANCE + " " + negated_emergency_direction

    assert "smoke_fire_heat_emergency_direction" in (missing_lithium_battery_safety_guidance(answer))


@pytest.mark.parametrize(
    ("unsafe_imperative", "expected_code"),
    [
        ("Charge it outdoors now.", "contradictory_handling_using_or_charging_guidance"),
        ("Return it now.", "contradictory_shipping_or_return_guidance"),
        ("Please ship it back now.", "contradictory_shipping_or_return_guidance"),
        ("Take it to our store.", "contradictory_shipping_or_return_guidance"),
        ("Rechargez-le dehors maintenant.", "contradictory_handling_using_or_charging_guidance"),
        ("Apportez-le au magasin.", "contradictory_shipping_or_return_guidance"),
        ("Laden Sie es draußen auf.", "contradictory_handling_using_or_charging_guidance"),
        ("Senden Sie die Batterie jetzt.", "contradictory_shipping_or_return_guidance"),
        ("Verschicken Sie die Batterie jetzt.", "contradictory_shipping_or_return_guidance"),
        ("Bringen Sie es zum Laden.", "contradictory_shipping_or_return_guidance"),
        ("Rechargez la batterie maintenant.", "contradictory_handling_using_or_charging_guidance"),
        ("Expédiez la batterie maintenant.", "contradictory_shipping_or_return_guidance"),
        ("Retournez la batterie maintenant.", "contradictory_shipping_or_return_guidance"),
        ("Apportez la batterie au magasin.", "contradictory_shipping_or_return_guidance"),
        ("Cárguela afuera ahora.", "contradictory_handling_using_or_charging_guidance"),
        ("Cárguelo ahora.", "contradictory_handling_using_or_charging_guidance"),
        ("Envíelo ahora.", "contradictory_shipping_or_return_guidance"),
        ("Devuélvalo ahora.", "contradictory_shipping_or_return_guidance"),
        ("Llévela a nuestra tienda.", "contradictory_shipping_or_return_guidance"),
        ("Ricaricala all'aperto ora.", "contradictory_handling_using_or_charging_guidance"),
        ("Ricarichi la batteria ora.", "contradictory_handling_using_or_charging_guidance"),
        ("Spedisca la batteria ora.", "contradictory_shipping_or_return_guidance"),
        ("Restituisca la batteria ora.", "contradictory_shipping_or_return_guidance"),
        ("Portala al nostro negozio.", "contradictory_shipping_or_return_guidance"),
        ("Porti la batteria al negozio.", "contradictory_shipping_or_return_guidance"),
    ],
)
def test_unsafe_multilingual_imperatives_fail_closed(
    unsafe_imperative: str,
    expected_code: str,
) -> None:
    missing = missing_lithium_battery_safety_guidance(_COMPLETE_GUIDANCE + " " + unsafe_imperative)

    assert expected_code in missing


@pytest.mark.parametrize(
    "number_guidance",
    [
        "Call 911.",
        "Call 9-1-1.",
        "Dial (112).",
        "Appelez le 18.",
        "Rufen Sie die Notrufnummer 144 an.",
        "Call one-one-two.",
        "Dial 1 4 4.",
    ],
)
def test_jurisdiction_specific_emergency_number_variants_fail_closed(
    number_guidance: str,
) -> None:
    missing = missing_lithium_battery_safety_guidance(_COMPLETE_GUIDANCE + " " + number_guidance)

    assert "jurisdiction_specific_emergency_number" in missing


@pytest.mark.parametrize(
    "ordinary_reference",
    [
        "Order 112 is ready.",
        "The reference is 1 4 4.",
        "Tracking ID 911 was created.",
    ],
)
def test_plain_order_or_reference_numbers_are_not_emergency_guidance(
    ordinary_reference: str,
) -> None:
    missing = missing_lithium_battery_safety_guidance(_COMPLETE_GUIDANCE + " " + ordinary_reference)

    assert "jurisdiction_specific_emergency_number" not in missing


def test_reply_safety_boundary_uses_latest_customer_message_and_clear_reason() -> None:
    reason = lithium_battery_reply_safety_blocked_reason(
        subject="Leaking lithium battery",
        messages=_HAZARD_MESSAGES,
        answer="Please wait for our team.",
    )

    assert reason.startswith(SAFETY_GUIDANCE_MISSING_REASON_CODE + ":")
    assert "stop_handling_using_charging" in reason
    assert (
        lithium_battery_reply_safety_blocked_reason(
            subject="Leaking lithium battery",
            messages=_HAZARD_MESSAGES,
            answer=_COMPLETE_GUIDANCE,
        )
        == ""
    )


def test_global_response_prompt_contains_non_overridable_battery_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "automail.pipeline.response.prompt_factory.read_config",
        lambda **_kwargs: type("Config", (), {"org_name": "Mantly"})(),
    )

    prompt = create_response_system_prompt()

    assert "Non-overridable damaged lithium battery safety policy" in prompt
    assert "Stop handling, using, and charging" in prompt
    assert "Do not ship, return, or otherwise transport" in prompt
    assert "local emergency services or the local fire authority" in prompt


def _stub_issue_agent_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(
        llm_module,
        "resolve_effective_config",
        lambda config, _tenant, _project: config,
    )
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(
        usage_module,
        "record_usage_from_result",
        lambda *_args, **_kwargs: None,
    )


def test_automatic_answer_retries_missing_safety_and_forces_human_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_issue_agent_runtime(monkeypatch)
    prompts: list[str] = []
    captured_system_prompt = ""

    class FakeAutomationAgent:
        def invoke(
            self,
            inputs: dict[str, Any],
            *,
            config: dict[str, Any],
        ) -> dict[str, Any]:
            assert config["run_name"] == "issue_automation_answer"
            prompts.append(inputs["messages"][0]["content"])
            answer = "Please isolate the parcel and wait for our team." if len(prompts) == 1 else _COMPLETE_GUIDANCE
            return {
                "structured_response": AutomationAnswerOutput(
                    answer=answer,
                    confidence="medium",
                    requires_human=False,
                )
            }

    def fake_create_agent(**kwargs: Any) -> FakeAutomationAgent:
        nonlocal captured_system_prompt
        captured_system_prompt = kwargs["system_prompt"]
        return FakeAutomationAgent()

    monkeypatch.setattr(issue_agent, "create_agent", fake_create_agent)

    result = issue_agent.draft_issue_automation_answer(
        issue={"id": "issue-1", "subject": "Leaking lithium battery"},
        messages=_HAZARD_MESSAGES,
        question="Prepare the safest supported response.",
        articles=[],
        prior_agent_runs=[],
        tenant_id="tenant-1",
        project_id="project-1",
        fallback_answer="Human review required.",
        fallback_confidence="low",
    )

    assert len(prompts) == 2
    assert "Missing policy elements" in prompts[1]
    assert LITHIUM_BATTERY_SAFETY_POLICY_ID in prompts[0]
    assert LITHIUM_BATTERY_SAFETY_OBLIGATION_ID in prompts[0]
    assert "Non-overridable damaged lithium battery safety policy" in captured_system_prompt
    assert result.answer == _COMPLETE_GUIDANCE
    assert result.requires_human is True
    assert "damaged or leaking lithium battery" in result.requires_human_reason
    assert result.citation_ids == ()


@pytest.mark.parametrize("language", ["en", "de", "fr", "es", "it"])
def test_deterministic_battery_fallback_is_complete_localized_and_action_safe(
    language: str,
) -> None:
    answer = issue_agent._battery_safety_failure_answer(language=language)

    assert missing_lithium_battery_safety_guidance(answer) == ()
    assert issue_agent._detected_supported_language(answer) == language
    assert (
        issue_agent.check_pending_action_claims(
            answer=answer,
            runbook_actions=[
                {
                    "name": "open_ticket",
                    "label": "Open safety incident",
                    "status": "pending_approval",
                }
            ],
        ).blocked
        is False
    )


def test_active_hazard_automation_capacity_fallback_replaces_generic_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NoCapacity:
        def acquire(self, *, blocking: bool, timeout: float) -> bool:
            assert blocking is True
            assert timeout == issue_agent.AUTOMATION_AGENT_SLOT_WAIT_SECONDS
            return False

    monkeypatch.setattr(issue_agent, "_AUTOMATION_AGENT_SLOTS", NoCapacity())

    result = issue_agent.draft_issue_automation_answer(
        issue={"id": "issue-1", "subject": "Leaking lithium battery"},
        messages=_HAZARD_MESSAGES,
        question="Prepare the safest supported response.",
        articles=[],
        prior_agent_runs=[],
        tenant_id="tenant-1",
        project_id="project-1",
        fallback_answer="We are reviewing this ticket and will keep you updated.",
        fallback_confidence="low",
    )

    assert result.generation_mode == "deterministic_fallback"
    assert result.answer != "We are reviewing this ticket and will keep you updated."
    assert missing_lithium_battery_safety_guidance(result.answer) == ()
    assert result.requires_human is True


def test_active_hazard_knowledge_capacity_fallback_contains_safety_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NoCapacity:
        def acquire(self, *, blocking: bool) -> bool:
            assert blocking is False
            return False

    monkeypatch.setattr(issue_agent, "_KNOWLEDGE_AGENT_SLOTS", NoCapacity())

    result = issue_agent.draft_issue_agent_answer(
        issue={"id": "issue-1", "subject": "Leaking lithium battery"},
        messages=_HAZARD_MESSAGES,
        question="Prepare the safest supported response.",
        articles=[],
        prior_agent_runs=[],
        tenant_id="tenant-1",
        project_id="project-1",
        fallback_answer="unused",
        fallback_confidence="low",
    )

    assert result.generation_mode == "deterministic_fallback"
    assert missing_lithium_battery_safety_guidance(result.answer) == ()
    assert result.requires_human is True


def test_active_hazard_failed_correction_uses_safe_deterministic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_issue_agent_runtime(monkeypatch)

    class UnsafeAutomationAgent:
        def invoke(
            self,
            _inputs: dict[str, Any],
            *,
            config: dict[str, Any],
        ) -> dict[str, Any]:
            assert config["run_name"] == "issue_automation_answer"
            return {
                "structured_response": AutomationAnswerOutput(
                    answer="We are reviewing this ticket and will keep you updated.",
                    confidence="medium",
                    requires_human=False,
                )
            }

    monkeypatch.setattr(
        issue_agent,
        "create_agent",
        lambda **_kwargs: UnsafeAutomationAgent(),
    )

    result = issue_agent.draft_issue_automation_answer(
        issue={"id": "issue-1", "subject": "Leaking lithium battery"},
        messages=_HAZARD_MESSAGES,
        question="Prepare the safest supported response.",
        articles=[],
        prior_agent_runs=[],
        tenant_id="tenant-1",
        project_id="project-1",
        fallback_answer="We are reviewing this ticket and will keep you updated.",
        fallback_confidence="low",
    )

    assert result.generation_mode == "deterministic_fallback"
    assert result.error.startswith(SAFETY_GUIDANCE_MISSING_REASON_CODE)
    assert missing_lithium_battery_safety_guidance(result.answer) == ()
    assert result.requires_human is True


def test_grounding_fails_closed_before_model_when_safety_guidance_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoked = False

    def fail_create_agent(**_kwargs: Any) -> Any:
        nonlocal invoked
        invoked = True
        raise AssertionError("grounding model must not run")

    monkeypatch.setattr(issue_agent, "create_agent", fail_create_agent)

    result = issue_agent.assess_issue_automation_grounding(
        issue={
            "id": "issue-1",
            "subject": "Leaking lithium battery",
            "actionExecutions": [
                {
                    "type": "runbook_webhook",
                    "status": "pending",
                    "label": "Open safety incident",
                    "metadata": {
                        "source": "runbook",
                        "approvalRequired": True,
                    },
                    "result": {
                        "proposedAction": {
                            "name": "open_ticket",
                            "label": "Open safety incident",
                        }
                    },
                }
            ],
        },
        messages=_HAZARD_MESSAGES,
        answer="We are reviewing this ticket. Please isolate the parcel and wait for our team.",
        articles=[],
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert invoked is False
    assert result.verified is False
    assert result.reason_code == SAFETY_GUIDANCE_MISSING_REASON_CODE
    assert result.answer_obligations[-1]["id"] == LITHIUM_BATTERY_SAFETY_OBLIGATION_ID
    assert result.context_snapshots[-1]["id"] == LITHIUM_BATTERY_SAFETY_POLICY_ID


def test_grounding_accepts_system_safety_policy_with_zero_knowledge_articles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_issue_agent_runtime(monkeypatch)
    answer_units = issue_agent._grounding_answer_units(_COMPLETE_GUIDANCE)
    prompts: list[str] = []

    class FakeGroundingAgent:
        def invoke(
            self,
            inputs: dict[str, Any],
            *,
            config: dict[str, Any],
        ) -> dict[str, Any]:
            assert config["run_name"] == "issue_automation_grounding"
            prompt = inputs["messages"][0]["content"]
            prompts.append(prompt)
            return {
                "structured_response": AutomationGroundingOutput(
                    verdict="grounded",
                    answer_sha256=issue_agent.grounding_text_sha256(_COMPLETE_GUIDANCE),
                    unit_assessments=[
                        AutomationGroundingUnitAssessment(
                            unit_id=unit["id"],
                            unit_sha256=unit["sha256"],
                            supported=True,
                            evidence_ids=[
                                LITHIUM_BATTERY_SAFETY_POLICY_ID,
                                "messages",
                            ],
                        )
                        for unit in answer_units
                    ],
                    obligation_assessments=[
                        AutomationGroundingObligationAssessment(
                            obligation_id=LITHIUM_BATTERY_SAFETY_OBLIGATION_ID,
                            resolution="answered",
                            answer_unit_ids=[unit["id"] for unit in answer_units],
                        )
                    ],
                )
            }

    monkeypatch.setattr(issue_agent, "create_agent", lambda **_kwargs: FakeGroundingAgent())

    result = issue_agent.assess_issue_automation_grounding(
        issue={"id": "issue-1", "subject": "Leaking lithium battery"},
        messages=_HAZARD_MESSAGES,
        answer=_COMPLETE_GUIDANCE,
        articles=[],
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert result.verified is True
    assert result.citation_ids == ()
    assert result.context_snapshots[-1]["id"] == LITHIUM_BATTERY_SAFETY_POLICY_ID
    assert f'"{LITHIUM_BATTERY_SAFETY_POLICY_ID}"' in prompts[0]
    system_policy = prompts[0].split("## System Safety Policy\n", 1)[1]
    system_policy_json = system_policy.split("\n\n## Candidate Answer", 1)[0]
    assert json.loads(system_policy_json)["evidenceId"] == (LITHIUM_BATTERY_SAFETY_POLICY_ID)
