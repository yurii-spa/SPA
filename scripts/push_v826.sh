#!/bin/bash
# SPA Push v8.26
# MP-1170: DeFiProtocolVaultRewardTokenPriceExposureAnalyzer  (168 tests)
# MP-1171: DeFiProtocolVaultMaturityTrackRecordAnalyzer        (174 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v826.sh

set -e

COMMIT_MSG="feat(v8.26): MP-1170 VaultRewardTokenPriceExposureAnalyzer + MP-1171 VaultMaturityTrackRecordAnalyzer | 168+174=342 tests | advisory/read-only | reward-token price exposure: part of a vault APR is paid in a VOLATILE reward token, so the holder realized yield depends on the reward token price move between accrual and sale; base in-kind APR is safe, the reward-denominated portion is exposed (base_apr_pct, reward_share_pct, realized_reward_apr_pct=reward_apr*max(0,1+chg/100), realized_apr_pct, realization_haircut_pct, realization_ratio, effective_loss_from_reward_pct; NO/LOW/MODERATE/HIGH_REWARD_EXPOSURE; higher score=less exposure) [category yield_quality] + vault maturity/track-record: how battle-tested a vault is (age, completed epochs/cycles, audit status, stress-event survival) so the holder can size into proven vaults (vault_age_days, epochs_completed, age_months, audit_count, survived_stress_event, maturity_label; UNPROVEN/EMERGING/ESTABLISHED/BATTLE_TESTED; higher score=more mature) [category protocol_health] | registry Tier-B +2 (B=422, total 614) | pure stdlib, atomic ring-buffer logs, no inf/NaN"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_reward_token_price_exposure_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_maturity_track_record_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_reward_token_price_exposure_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_maturity_track_record_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_reward_token_price_exposure_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_maturity_track_record_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v826.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.26 — MP-1170 + MP-1171 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.26 complete!"
