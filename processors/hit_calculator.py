"""
Compatibility shim over processors/reachability.py.

The hit score it used to compute is gone (see reachability's module docstring).
This module survives only so the three runners keep one import path while they
are migrated in Task 22; it adds no logic of its own.
"""
import logging

from processors.reachability import apply_reachability

logger = logging.getLogger(__name__)


def score_all_leads(leads: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Split leads into (reachable, unreachable, pending)."""
    reachable, unreachable, pending = apply_reachability(leads)
    logger.info(
        f"Reachability: {len(reachable)} reachable / {len(unreachable)} unreachable "
        f"/ {len(pending)} pending quota"
    )
    return reachable, unreachable, pending
