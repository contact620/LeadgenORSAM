"""
Per-provider outcome tracking for a pipeline run.

A run that silently degrades is worse than a run that fails: the operator
ships a CSV without contacts and never learns why. Every enrichment step
records an outcome; a failure on a critical provider stops the run.
"""
from dataclasses import dataclass, field
from typing import Optional

# Providers grouped by the deliverable they serve. A group degrades when one
# member is impaired and fails only when every configured member is down:
# since Dropcontact was removed, no single email provider is load-bearing,
# and reporting a run as failed because one of three finders lost its key
# would be as misleading as reporting it green.
PROVIDER_GROUPS: dict[str, frozenset[str]] = {
    "email": frozenset({"prospeo", "getprospect", "hunter"}),
    # The AI half of the pipeline. Until this group existed, none of its three
    # steps belonged to any group, and impaired_groups() only iterates groups:
    # no AI failure of any size could colour a run.
    "ia": frozenset({"perplexity", "anthropic_facts", "anthropic_angles"}),
}

# Groups whose total failure invalidates the run's core deliverable.
# "ia" is deliberately out: a dead AI still leaves the contacts, which is what
# the operator came for. It degrades a run, it does not invalidate it.
CRITICAL_GROUPS = frozenset({"email"})


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

    def group_status(self, group: str) -> str:
        """Aggregate one group's outcomes into a single status.

        "skipped" members are excluded from the health verdict: a provider the
        operator never configured is not an outage. A group where every member
        is skipped is itself "skipped", not "failed" — nothing broke, nothing
        was ever asked to work.
        """
        members = PROVIDER_GROUPS.get(group, frozenset())
        reported = [self._outcomes[name] for name in members if name in self._outcomes]
        if not reported:
            return "skipped"

        active = [o for o in reported if o.status != "skipped"]
        if not active:
            return "skipped"
        # "failed" requires the whole group to have been heard from. The
        # cascade stops at its first success, so unreported members are the
        # normal case, not an anomaly: concluding total failure from the one
        # member that happened to report would make that member load-bearing
        # again — exactly what removing Dropcontact was meant to end.
        if len(reported) == len(members) and all(
            o.status in ("failed", "degraded") for o in active
        ):
            return "failed"
        if any(o.status in ("failed", "degraded") for o in active):
            return "degraded"
        return "ok"

    def has_critical_failure(self) -> bool:
        """True when a critical group lost every one of its active members."""
        return any(self.group_status(g) == "failed" for g in CRITICAL_GROUPS)

    def impaired_groups(self) -> dict[str, str]:
        """Groups worth reporting to the operator, with their status."""
        return {
            group: status
            for group in PROVIDER_GROUPS
            if (status := self.group_status(group)) in ("degraded", "failed")
        }
