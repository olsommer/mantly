"""Fail Python startup before Mantly runs in an unsupported topology.

Python imports ``sitecustomize`` during interpreter startup when the backend root
is on ``sys.path`` (the repository, CI, and production image execution model).
Using ``SystemExit`` is intentional: ``site`` reports ordinary exceptions and
continues, while an unsupported topology must not accept traffic or run jobs.
"""

from __future__ import annotations

try:
    from automail.core.runtime_topology import validate_runtime_topology

    validate_runtime_topology()
except RuntimeError as exc:
    raise SystemExit(f"Mantly startup blocked: {exc}") from exc
