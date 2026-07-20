"""Read-only lookup for deterministic E2E persona tool fixtures."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml  # pyright: ignore[reportMissingModuleSource]

from automail.core.sensitive_values import contains_sensitive_credential

_PERSONA_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]+$")
_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]+$")
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024


def e2e_fixture_runtime_enabled() -> bool:
    """Keep synthetic live fixtures opt-in outside the offline loader/tests."""
    return os.getenv("ENABLE_E2E_FIXTURES", "false").strip().lower() == "true"
_MAX_EVIDENCE_CHUNKS = 16
_MAX_EVIDENCE_CHARS = 200
_EVIDENCE_BLOCKED_CONTAINERS = frozenset(
    {"headers", "input", "payload", "received", "request"}
)
_EVIDENCE_SECRET_FRAGMENTS = (
    "authorization",
    "base64",
    "cookie",
    "credential",
    "fingerprint",
    "lastfour",
    "password",
    "privatekey",
    "secret",
    "token",
)


class E2EFixtureLookupError(RuntimeError):
    """Base error for fixture lookup failures that must never fall through to HTTP."""


class E2EFixtureNotFound(E2EFixtureLookupError):
    """Raised when no fixture matches the requested persona, tool, and input."""


class E2EFixtureManifestError(E2EFixtureLookupError):
    """Raised when fixture manifests are missing, unsafe, or malformed."""


def _default_personas_dir() -> Path:
    # Source checkout: <root>/backend/automail/demo/e2e_fixtures.py
    # Container:       /app/backend/automail/demo/e2e_fixtures.py
    return Path(__file__).resolve().parents[3] / "e2e" / "personas"


def merge_e2e_tool_input(
    query_items: Iterable[tuple[str, str]],
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Preserve repeated query keys as lists, then apply body/tool arguments."""
    merged: dict[str, Any] = {}
    for key, value in query_items:
        existing = merged.get(key)
        if existing is None:
            merged[key] = value
        elif isinstance(existing, list):
            existing.append(value)
        else:
            merged[key] = [existing, value]
    if payload:
        merged.update(payload)
    return merged


def _canonical_json(value: Any, *, context: str) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise E2EFixtureManifestError(
            f"{context} must contain only JSON-compatible values"
        ) from exc


def _normalized_evidence_key(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _safe_evidence_path(path: tuple[str, ...]) -> bool:
    for segment in path:
        if segment.isdigit():
            continue
        normalized = _normalized_evidence_key(segment)
        if normalized in _EVIDENCE_BLOCKED_CONTAINERS:
            return False
        if any(fragment in normalized for fragment in _EVIDENCE_SECRET_FRAGMENTS):
            return False
    return True


def _render_evidence_value(value: Any) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value, allow_nan=False)
    if not isinstance(value, str):
        return None
    rendered = " ".join(value.split())
    if contains_sensitive_credential(rendered):
        return None
    if len(rendered) > _MAX_EVIDENCE_CHARS:
        return None
    return rendered


def _fixture_evidence(result: Mapping[str, Any]) -> list[str]:
    """Create bounded, synthetic-only facts for the persisted tool audit."""
    evidence: list[str] = []

    def _visit(value: Any, path: tuple[str, ...], depth: int) -> None:
        if len(evidence) >= _MAX_EVIDENCE_CHUNKS or depth > 5:
            return
        if isinstance(value, dict):
            for raw_key, child in value.items():
                if len(evidence) >= _MAX_EVIDENCE_CHUNKS:
                    break
                if not isinstance(raw_key, str):
                    continue
                child_path = (*path, raw_key)
                if _safe_evidence_path(child_path):
                    _visit(child, child_path, depth + 1)
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                if len(evidence) >= _MAX_EVIDENCE_CHUNKS:
                    break
                _visit(child, (*path, str(index)), depth + 1)
            return
        if not path:
            return
        rendered_value = _render_evidence_value(value)
        if rendered_value is None:
            return
        rendered_path = ".".join(
            f"[{segment}]" if segment.isdigit() else segment
            for segment in path
        ).replace(".[", "[")
        chunk = f"{rendered_path}: {rendered_value}"
        if len(chunk) <= _MAX_EVIDENCE_CHARS:
            evidence.append(chunk)

    _visit(dict(result), (), 0)
    return evidence


def _with_fixture_evidence(result: Mapping[str, Any]) -> dict[str, Any]:
    detached = json.loads(json.dumps(result, allow_nan=False, ensure_ascii=False))
    if "fixture_evidence" in detached:
        raise E2EFixtureManifestError(
            "Tool fixture result uses reserved fixture_evidence field"
        )
    evidence = _fixture_evidence(detached)
    if evidence:
        # `result` is an existing response-fact allowlist key. Keeping evidence
        # under this synthetic wrapper makes it persist without widening the
        # allowlist for arbitrary external tool responses.
        detached["fixture_evidence"] = {"result": evidence}
    return detached


def _load_persona_manifests(personas_dir: Path) -> list[dict[str, Any]]:
    root = personas_dir.resolve()
    if not root.is_dir():
        raise E2EFixtureManifestError("E2E persona manifest directory is unavailable")

    manifests: list[dict[str, Any]] = []
    seen_persona_ids: set[str] = set()
    for path in sorted(root.glob("*.yaml")):
        if (
            path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(root)
        ):
            raise E2EFixtureManifestError("E2E persona manifests must be regular local files")
        try:
            if path.stat().st_size > _MAX_MANIFEST_BYTES:
                raise E2EFixtureManifestError(
                    f"E2E persona manifest is too large: {path.name}"
                )
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except E2EFixtureManifestError:
            raise
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise E2EFixtureManifestError(
                f"Unable to safely read E2E persona manifest: {path.name}"
            ) from exc
        if not isinstance(document, dict):
            raise E2EFixtureManifestError(
                f"E2E persona manifest must contain an object: {path.name}"
            )
        persona_id = document.get("id")
        if not isinstance(persona_id, str) or not _PERSONA_ID_PATTERN.fullmatch(persona_id):
            raise E2EFixtureManifestError(f"Invalid persona id in manifest: {path.name}")
        if persona_id in seen_persona_ids:
            raise E2EFixtureManifestError(f"Duplicate E2E persona id: {persona_id}")
        seen_persona_ids.add(persona_id)
        manifests.append(document)

    if not manifests:
        raise E2EFixtureManifestError("No E2E persona manifests are available")
    return manifests


def lookup_e2e_tool_fixture(
    persona_id: str,
    tool_name: str,
    supplied_input: Mapping[str, Any],
    *,
    personas_dir: Path | None = None,
) -> dict[str, Any]:
    """Return one exact static fixture result without executing external state."""
    if not _PERSONA_ID_PATTERN.fullmatch(persona_id):
        raise E2EFixtureNotFound("Invalid E2E persona id")
    if not _TOOL_NAME_PATTERN.fullmatch(tool_name):
        raise E2EFixtureNotFound("Invalid E2E tool name")

    manifests = _load_persona_manifests(personas_dir or _default_personas_dir())
    persona = next((item for item in manifests if item["id"] == persona_id), None)
    if persona is None:
        raise E2EFixtureNotFound(f"E2E persona not found: {persona_id}")

    seed = persona.get("seed")
    fixtures = seed.get("tool_fixtures") if isinstance(seed, dict) else None
    if not isinstance(fixtures, list):
        raise E2EFixtureManifestError(
            f"Persona {persona_id} has no valid tool_fixtures list"
        )

    requested_input = _canonical_json(
        dict(supplied_input),
        context="Supplied fixture input",
    )
    tool_exists = False
    matches: list[dict[str, Any]] = []
    seen_fixture_ids: set[str] = set()
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise E2EFixtureManifestError(
                f"Persona {persona_id} contains an invalid tool fixture"
            )
        fixture_id = fixture.get("id")
        fixture_tool = fixture.get("tool")
        fixture_input = fixture.get("input")
        result = fixture.get("result")
        if (
            not isinstance(fixture_id, str)
            or not _PERSONA_ID_PATTERN.fullmatch(fixture_id)
            or not isinstance(fixture_tool, str)
            or not _TOOL_NAME_PATTERN.fullmatch(fixture_tool)
            or not isinstance(fixture_input, dict)
            or not isinstance(result, dict)
        ):
            raise E2EFixtureManifestError(
                f"Persona {persona_id} contains an invalid tool fixture"
            )
        if fixture_id in seen_fixture_ids:
            raise E2EFixtureManifestError(
                f"Persona {persona_id} contains duplicate fixture id: {fixture_id}"
            )
        seen_fixture_ids.add(fixture_id)
        canonical_input = _canonical_json(
            fixture_input,
            context=f"Fixture input for {persona_id}/{fixture_tool}",
        )
        _canonical_json(
            result,
            context=f"Fixture result for {persona_id}/{fixture_tool}",
        )
        if fixture_tool != tool_name:
            continue
        tool_exists = True
        if canonical_input == requested_input:
            matches.append(result)

    if len(matches) > 1:
        raise E2EFixtureManifestError(
            f"Ambiguous exact fixture match for {persona_id}/{tool_name}"
        )
    if matches:
        return _with_fixture_evidence(matches[0])
    if not tool_exists:
        raise E2EFixtureNotFound(
            f"E2E tool fixture not found: {persona_id}/{tool_name}"
        )
    raise E2EFixtureNotFound(
        f"No exact E2E fixture input match for {persona_id}/{tool_name}"
    )
