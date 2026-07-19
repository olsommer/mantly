"""Validate all reusable E2E personas without contacting external systems."""

from __future__ import annotations

from pathlib import Path

from .schema import load_personas

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    personas = load_personas(ROOT / "e2e" / "personas")
    case_count = sum(len(persona.cases) for persona in personas)
    print(f"Validated {len(personas)} personas and {case_count} cases.")
    for persona in personas:
        print(
            f"- {persona.id}: {len(persona.cases)} cases, "
            f"{len(persona.seed.knowledge)} knowledge fixtures, "
            f"{len(persona.seed.tool_fixtures)} tool fixtures"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
