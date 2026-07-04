# 07 — DATA PIPELINE & PAPER TEST

Canonical deep source: `AUDIT_06_DATA_PIPELINE_AND_PAPER_TEST.md`.

- **Paper day (truth) = `data/golive_status.json:real_track_days`** (date-derived from evidenced anchor 2026-06-22; NOT a manual counter).
- Site-visible: build-time static `landing/src/data/track_snapshot.json` (regenerated post-cycle by `deploy_site_snapshot.py`, committed to `main`) + runtime live via `api.earn-defi.com` (JS overrides static).
- Two lag points cause "site shows older day": snapshot-not-pushed OR CF-build-lag. Do not change the paper-test source of truth without updating docs + `test_doc_drift.py`.
