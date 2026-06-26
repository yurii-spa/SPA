"""spa_core/telegram/reports — the two canonical scheduled digests (Tier 2).

Phase 2 of the Telegram rebuild collapses the four+ duplicate daily-report code
paths (daily_telegram_report / morning_digest / daily_paper_report /
telegram_daily_digest / cpa_daily / tier1_digest) into ONE daily digest, and the
weekly variants into ONE weekly digest.

These builders PROMOTE the already-clean read-only builders in
``spa_core/reporting/`` (``daily_telegram_report`` / ``weekly_telegram_report``)
and additionally fold in any events that ``push_policy`` demoted to the digest
queue, plus a date-stamp idempotency guard so a double-firing launchd agent can
never send twice for the same UTC date.
"""
from . import daily, weekly  # noqa: F401
