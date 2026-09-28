"""Studio OS Core — the persistent company brain (ADR-495).

Reuse-first projectors over existing canon (mission-state ledger, docs/decisions, journal, roadmap,
health, research). No new database, no second task/memory/decision authority. The ADR system stays THE
decision authority; the mission ledger stays THE work authority; the Investment Engine owns financial truth.
"""
from .registry import load_registry, get_project, project_ids  # noqa: F401
