# TRUSTED_BOOTSTRAP_OWNER_CUTOVER_PACKAGE

Root install is NOT authorized from a non-canonical candidate tree. This package closes the three ARB
requirements (canonical-first, installer/launcher pinned, ACTIVE measured not marker-trusted) and hands you a
verified, checkpointed cutover. **No sudo, no fleet restart, no daily-cycle re-enable, no Telegram, no capital,
no RiskPolicy — nothing executed here.**

## DAILY_CYCLE_STATE
`com.spa.daily_cycle` is **PAUSED** (`launchctl bootout gui/501/com.spa.daily_cycle`, session-scoped). The plist
is present and **not** disabled (`RunAtLoad=false`, no `Disabled` key), so **logout/reboot WOULD reload it**.
→ **`DO_NOT_REBOOT_BEFORE_CUTOVER=YES`**. To make the pause reboot-proof (optional, your call — a production
action I did not take): `launchctl disable gui/501/com.spa.daily_cycle` (re-enable: `launchctl enable …`).

## CANONICAL_WRITER_RACE
The autonomous origin/main writer is **`com.spa.mission_tick`** — `/bin/bash …/studio-os-scratch/v03/scripts/
shadow/mission_tick_agent.sh`, **StartInterval 900 s (15 min)**, which spawns `claude` delivery sessions that
allocate ADR numbers and push "feat(G##)" commits (it took ADR-498 and ADR-499 mid-task). It is the ONLY
launchd agent whose entrypoint is outside the autosync tree. **Serialization procedure (needs your
authorization — I did NOT pause it):**
```
launchctl bootout gui/501/com.spa.mission_tick          # PAUSE the writer (reversible)
#   → agent: git fetch origin; allocate next-free ADR; renumber ADR-500 if taken; promote; verify origin/main
launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.spa.mission_tick.plist   # RESUME the writer
```
No permanent ADR-allocation redesign here (that is the filed P1). Just a bounded window.

## CANONICAL_PROMOTION
**NOT done — blocked on two owner authorizations:** (1) authorize the `com.spa.mission_tick` pause above (to
stop the ADR race during the window); (2) the `docs/decisions/INDEX.md` is **>1 MB**, forcing
`push_to_github.py` into `--allow-overwrite` — **I am NOT inferring authorization from the earlier one-time
exception**; the additive diff is INDEX **+1 row** (ADR-500) / −0, base == current remote, and I request a
**new narrow authorization** for that single overwrite. Net deliverable (only the reviewed boundary work):
`ADR-500`, `release_state.py`, `release_activation.py`, `release_launcher.py`, `install_trusted_bootstrap.sh`,
the 3 boundary test files, `repo_status.py` release block, `studio_core.js` CODE SYNC UI, the boundary
reports + manifest, the P1 note. Re-fetch immediately before push; expected-base/fail-closed; no force-push.

## CANONICAL_COMMIT
**PENDING_PROMOTION** (candidate `7c0a370d` + the canary commit; the canonical SHA is stamped after the push).

## ADR_NUMBER
**ADR-500** (accepted architecture). May require re-allocation to the next free number at promotion under the
serialization window — the race already consumed 498/499.

## ARTIFACT_MANIFEST
`docs/studio_shell_visual_review/CUTOVER_ARTIFACT_MANIFEST.json` (machine-readable). Human-readable:
- APPROVED_RELEASE_SHA = `5b65257784441f61568e6c3bd22e9d0a1e928c83`
- INSTALLER_PATH = `scripts/install_trusted_bootstrap.sh` · INSTALLER_SHA256 = `8cf04b6d0488b643b4e3079218f3431f50aa4ef38f31a1e1077d94b5ddfe55e9`
- LAUNCHER_PATH = `spa_core/studio_os/release_launcher.py` · LAUNCHER_SHA256 = `eeefadbac44fe67646721c7fc6be1712736e326c76480718b9fb87d922a0d6ff`
- TRUSTED_PYTHON_PATH = `/Library/Application Support/StudioOS/toolchains/base/bin/python3` (SHA measured at install)
- EXPECTED_RELEASE_PATH = `/Library/Application Support/StudioOS/releases/5b652577…/`
- EXPECTED_APPROVAL_FILE = `/Library/Application Support/StudioOS/approved_release.json`
- CANARY_SERVICE = `canary` → `spa_core.monitoring.deployment_acceptance` (benign, non-money, exits)

## INSTALLER_TRUST
Never `sudo scripts/install_trusted_bootstrap.sh` from the mutable tree. Verify-then-stage-then-verify-then-run
with fixed system binaries; you compare hashes BEFORE granting root (Checkpoint A). No curl/download; no network
beyond the already-verified local git state.

## ACTIVE_MEASUREMENT
Corrected (ARB §6): `release_state.active_from_process()` measures ACTIVE from **process cwd → root-owned
`releases/<sha>` → `.release_sha` verified**, exposing `active_sha`, `active_verified`, `active_evidence`. The
user-writable `active_release.json` is demoted to `active_marker_hint` and **never overrides measurement**.
Live now: `active_sha=UNKNOWN, active_verified=False` (launcher not wired — honest). **`ACTIVE_MEASUREMENT_TRUSTWORTHY=YES`.**

## INSTALLER_DRY_RUN
Passed from current candidate bytes (verifies launcher SHA + approved object present, then temp→verify→atomic
rename→root-owned read-only release→approval-SHA-only→permission proof; fail-closes on any mismatch — shown
live when a stale SHA was rejected). Re-run from the POST-PROMOTION canonical bytes at Checkpoint A.

## CANARY_SELECTED
`com.spa.<a benign non-money agent>` repointed to launcher service **`canary`** (= `deployment_acceptance`,
verified 0 money-path imports in 5b652577, runs and exits). NOT the money-path daily cycle.

## OWNER_COMMAND_BLOCK  (run sequentially; STOP at any mismatch. `<CANON>` = the promoted canonical commit)
```
# A. VERIFY canonical commit + artifact hashes (NO root yet)
git -C ~/Documents/SPA_Claude fetch origin && git -C ~/Documents/SPA_Claude cat-file -e <CANON>^{commit}
/usr/bin/shasum -a 256 <verified-tree>/scripts/install_trusted_bootstrap.sh   # EXPECT 8cf04b6d…55e9
/usr/bin/shasum -a 256 <verified-tree>/spa_core/studio_os/release_launcher.py # EXPECT eeefadba…d6ff
#   EXPECTED_RESULT: both hashes match the manifest. STOP_CONDITION: any mismatch. ROLLBACK: none (nothing changed).
# A2. stage the verified bytes with fixed tools, verify again
/bin/mkdir -p /tmp/tb-stage && /bin/cp <verified-tree>/scripts/install_trusted_bootstrap.sh /tmp/tb-stage/ \
  && /bin/cp <verified-tree>/spa_core/studio_os/release_launcher.py /tmp/tb-stage/
/usr/bin/shasum -a 256 /tmp/tb-stage/*                                        # EXPECT the same two hashes
#   STOP_CONDITION: staged hash differs. ROLLBACK: rm -rf /tmp/tb-stage.
# B/C/D/E. INSTALL trusted plane (installs launcher root:wheel 0444; materialises 5b652577 read-only; writes approval; proves user cannot write)
sudo /bin/bash /tmp/tb-stage/install_trusted_bootstrap.sh \
  --launcher /tmp/tb-stage/release_launcher.py --launcher-sha256 eeefadbac44fe67646721c7fc6be1712736e326c76480718b9fb87d922a0d6ff \
  --repo ~/Documents/SPA_Claude --approved 5b65257784441f61568e6c3bd22e9d0a1e928c83
#   EXPECTED_RESULT: "permission proof: … cannot write launcher/approval/release ✓". STOP_CONDITION: any FAIL-CLOSED line.
#   ROLLBACK: sudo rm -rf "/Library/Application Support/StudioOS/releases/5b652577…" "…/approved_release.json" "…/bin/release_launcher-eeefadba….py"
# F/G. pick ONE benign non-money agent as canary; back up + repoint its plist to the launcher service `canary`
cp ~/Library/LaunchAgents/com.spa.<canary>.plist /tmp/tb-stage/<canary>.plist.bak   # BACKUP
#   edit ProgramArguments →  /bin/bash -c '"/Library/Application Support/StudioOS/toolchains/base/bin/python3" "/Library/Application Support/StudioOS/bin/release_launcher-eeefadba….py" canary'
#   STOP_CONDITION: plist invalid (plutil -lint). ROLLBACK: cp the .bak back.
# H. reload ONLY the canary
launchctl bootout gui/501/com.spa.<canary>; launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.spa.<canary>.plist
#   EXPECTED_RESULT: canary runs via the launcher. STOP_CONDITION: crash loop. ROLLBACK: restore .bak + reload.
# I. VERIFY ACTIVE from process evidence (not the marker)
python3 -c "from spa_core.studio_os.release_state import active_from_process as a; print(a('/Library/Application Support/StudioOS/releases'))"
#   EXPECTED_RESULT: active_verified=True, active_sha=5b652577…  (staged 96c8ba… did NOT run). STOP_CONDITION: verified=False or a different sha.
# J. NEGATIVE control: point approval at an unapproved sha → launcher must FAIL CLOSED
sudo /bin/bash -c 'printf "{\"approved_sha\":\"deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\"}" > "/Library/Application Support/StudioOS/approved_release.json"'
launchctl bootout gui/501/com.spa.<canary>; launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.spa.<canary>.plist
#   EXPECTED_RESULT: canary FAIL_CLOSED (exit 3), nothing executes. Then RESTORE approval to 5b652577… (sudo, as in E).
#   STOP_CONDITION: anything executes. ROLLBACK: restore approval + .bak plist.
# K. STOP and report. Do NOT touch the daily cycle or the fleet until I confirm the canary result.
```

## ROLLBACK
Every checkpoint carries its ROLLBACK above. Whole-cutover rollback: restore each `.bak` plist + `launchctl`
reload; `sudo rm -rf` the release dir / approval / launcher; the mutable tree and all agents are then exactly
as before. Production rollback of a bad *release* (post-cutover) = re-approve the prior SHA (no git rewrite).

## REMAINING_RISKS
- **Not canonical yet** → root install correctly withheld. Promotion needs your two authorizations (writer
  pause + narrow `--allow-overwrite`).
- **Reboot reloads the daily cycle** (DO_NOT_REBOOT flag) until either the launcher protects it or you
  `launchctl disable` it.
- **ADR-number race is live** (P1) — the promoted ADR number may need last-second re-allocation in the window.
- Agent-restart paths remain unprotected until the fleet migration (Phase 8, after canary + daily-cycle proof).
- Telegram deferred (separate).

## Final flags
```
TRUSTED_BOOTSTRAP_CANONICAL     = NO   (promotion pending: writer-pause + narrow --allow-overwrite authorizations)
INSTALLER_PINNED                = YES  (sha 8cf04b6d…; verified before sudo in Checkpoint A)
LAUNCHER_PINNED                 = YES  (sha eeefadba…; content-addressed install, verified by the installer)
ACTIVE_MEASUREMENT_TRUSTWORTHY  = YES  (measured from process→releases/<sha>→.release_sha; marker demoted to hint)
DAILY_CYCLE_PAUSED              = YES  (bootout; reboot would reload → DO_NOT_REBOOT_BEFORE_CUTOVER)
READY_FOR_OWNER_SUDO_CUTOVER    = NO   (not canonical; root install not authorized from a non-canonical tree)
```
No production changes beyond the earlier reversible daily-cycle pause. STOP.
