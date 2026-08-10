"""
Per-provider outcome tracking for a pipeline run.

A run that silently degrades is worse than a run that fails: the operator
ships a CSV without contacts and never learns why. Every enrichment step
records an outcome; a failure on a critical provider stops the run.
"""
from dataclasses import dataclass, field
from typing import Optional

# Providers whose failure invalidates the run's core deliverable.
CRITICAL_PROVIDERS = frozenset({"dropcontact"})

# status values: "ok" | "degraded" | "failed" | "skipped"


@dataclass
class StepOutcome:
    """Result of one provider's contribution to a run."""
    provider: str
    status: str
    reason: Optional[str] = None
    leads_affected: int = 0


class ProviderFailure(Exception):
    """Raised when a critical provider cannot deliver — aborts the run."""

    def __init__(self, provider: str, reason: str):
        self.provider = provider
        self.reason = reason
        super().__init__(f"{provider}: {reason}")


@dataclass
class ProviderRegistry:
    """Collects one outcome per provider; the latest record wins."""
    _outcomes: dict[str, StepOutcome] = field(default_factory=dict)

    def record(self, outcome: StepOutcome) -> None:
        self._outcomes[outcome.provider] = outcome

    def to_dict(self) -> dict[str, dict]:
        return {
            name: {
                "status": o.status,
                "reason": o.reason,
                "leads_affected": o.leads_affected,
            }
            for name, o in self._outcomes.items()
        }

    def has_critical_failure(self) -> bool:
        return any(
            o.status == "failed" and name in CRITICAL_PROVIDERS
            for name, o in self._outcomes.items()
        )
