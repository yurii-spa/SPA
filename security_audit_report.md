# SPA — Security Audit Report

**Date:** 2026-06-21
**Scope:** `spa_core/` (Python runtime), `scripts/`, root tooling, committed config
**Auditor:** Claude Code (automated security review)
**Method:** secrets scan, injection review, path-traversal review, network/JSON
hardening review, private-key exposure review, logging-safety review.

---

## Summary

| Severity | Found | Fixed | Open |
|----------|-------|-------|------|
| CRITICAL | 1 | 1 | 0 |
| HIGH     | 0 | 0 | 0 |
| MEDIUM   | 2 | 1 | 1 |
| LOW      | 2 | 0 | 2 |

**All CRITICAL and HIGH findings are fixed.** One MEDIUM (committed default
credentials) and two LOW findings are documented below with recommendations
that require an operator decision (credential rotation) rather than a code edit.

Overall the codebase has a strong security posture: Keychain-based secret
handling, deterministic (LLM-forbidden) risk/execution domains, atomic writes,
timing-safe JWT verification, no `shell=True`, no TLS-verification bypass, and
network JSON parsing wrapped in `try/except`.

---

## CRITICAL

### C1 — Hardcoded Cloudflare Tunnel Token in `scripts/cf_install_token.command` — FIXED

- **File:** `scripts/cf_install_token.command:11` (pre-fix)
- **Issue:** A live Cloudflare Tunnel Token (`eyJhIjoiYjY1…`, JWT-encoded
  account/tunnel/secret) was hardcoded in plaintext. This token alone authorizes
  running the `spa` tunnel, which fronts the local dashboard (`localhost:8765`).
  This violates the project SECRETS POLICY ("never write tokens/keys to any file").
- **Exposure assessment:** The file is in `.gitignore` (line 35) and
  `git log --all -S` confirms the token was **never committed** to the repo, so it
  did not leak to GitHub. The exposure was local-disk plaintext only.
- **Fix applied:** Removed the hardcoded token. The script now resolves the token
  from, in order: (1) env `CF_TUNNEL_TOKEN_SPA`, (2) Keychain
  `CF_TUNNEL_TOKEN_SPA` (where the script already stores it and where the running
  `com.spa.cloudflared` wrapper reads it), (3) interactive `read -rsp` prompt
  (no echo, not saved to shell history). Functionality is preserved because the
  token is already present in the Keychain for the running tunnel.
- **Action still required by operator:** **ROTATE this Cloudflare Tunnel Token.**
  Because it sat in plaintext on disk, treat it as compromised. In Cloudflare
  Zero Trust → Networks → Connectors → `spa`, refresh the connector token, then
  re-run the (now token-free) script to store the new value in Keychain.

---

## MEDIUM

### M1 — Committed default credentials in `spa_core/family_fund/users.json` — OPEN (operator action)

- **File:** `spa_core/family_fund/users.json` (git-tracked)
- **Issue:** Ships four default accounts (`owner`, `admin`, `investor`,
  `readonly`) with bcrypt password hashes and a self-described `"DEV DEFAULTS"`
  comment. The investor portal (`:8766`) is capital-adjacent. Predictable
  usernames + default passwords known to anyone with repo access could allow
  authentication once the portal is publicly exposed.
- **Mitigating factors:** Passwords are stored as bcrypt cost-12 hashes (not
  plaintext); a hash is not itself a secret. `manage_users.py` correctly takes
  the password from an env var and never writes plaintext.
- **Why not auto-fixed:** Rewriting the hashes would lock the operator out of
  the owner account and requires choosing new passwords — an operator decision.
- **Recommendation:** Before any public exposure, rotate all four passwords:
  `python -m spa_core.family_fund.manage_users set --username owner --password-env NEW_PW`
  (repeat per user). Consider removing the `admin`/`investor`/`readonly` demo
  accounts from the committed file entirely and provisioning them at deploy time.

### M2 — `github_pusher.py` accepted the PAT only via CLI/env — FIXED

- **File:** `spa_core/tools/github_pusher.py`
- **Issue:** The alternate pusher resolved the GitHub PAT only from `--token`
  (visible in `ps` output and shell history) or `GITHUB_TOKEN`, diverging from
  the project policy of reading the PAT from the macOS Keychain at runtime. The
  docstring and `--help` examples advertised `--token ghp_xxx`, nudging users
  toward the leak-prone path.
- **Fix applied:** Added `_token_from_keychain()` (reads `GITHUB_PAT_SPA` via
  `security find-generic-password`, never logs the value). Token resolution is
  now Keychain → `GITHUB_TOKEN` env → `--token` (the last marked DISCOURAGED).
  Updated docstring, epilog, and `--help` text to stop advertising CLI tokens.

---

## LOW

### L1 — `~/.github_pat` plaintext fallback in legacy push scripts — OPEN

- **Files:** numerous `scripts/push_*.sh` (e.g. `push_v818.sh`, `push_design_v1.sh`)
- **Issue:** Several legacy push scripts fall back to reading a PAT from a
  plaintext `~/.github_pat` file. The primary runtime path (`push_to_github.py`)
  correctly uses the Keychain; these scripts are manual, one-off helpers.
- **Recommendation:** Prefer the Keychain in these helpers too, or delete the
  large backlog of obsolete `push_v*.sh` scripts. If `~/.github_pat` exists,
  ensure `chmod 600` and rotate the PAT periodically. Low risk (local, manual).

### L2 — `--token` CLI exposure remains available — OPEN (by design)

- **File:** `spa_core/tools/github_pusher.py`
- **Issue:** The `--token` argument is retained for backward compatibility even
  after M2. Passing it still exposes the PAT to `ps`/history.
- **Recommendation:** It is now last-priority and clearly marked DISCOURAGED;
  consider removing it in a future cleanup once no caller depends on it.

---

## Checks performed — clean (no findings)

1. **Secrets scan** — No hardcoded API keys, PATs, or private keys in `spa_core/`
   runtime code. Telegram/JWT/GitHub secrets are read from Keychain at runtime
   (`security find-generic-password`). The only embedded secret in the whole repo
   was C1 (fixed). `.env` files committed (`cabinet/.env.*`, `*.env.example`)
   contain only public config (API URLs, feature flags) — no secrets.
2. **Injection (eval/exec/os.system/subprocess)** — No `eval()`/`exec()` on
   external data. No `os.system`. All `subprocess.run` calls use list-form args
   (no `shell=True` anywhere) with static argv (`security`, `git`, `launchctl`),
   so no shell-injection surface.
3. **Path traversal** — No file paths are built from untrusted network input in
   runtime paths; data files use fixed `data/` locations with atomic
   `tmp + os.replace`. `--data-dir` is operator-supplied, not external.
4. **Network requests** — 84 `urllib` call sites; the live APY/TVL feed
   (`adapters/defillama_feed.py`) wraps `json.loads` of responses in `try/except`
   and never raises (graceful fallback). No `verify=False`, no
   `ssl._create_unverified_context`, no `CERT_NONE`.
5. **JSON parsing** — External/network JSON parsing is guarded; the DeFiLlama
   feed and Telegram responses degrade gracefully on malformed input.
6. **Private-key exposure** — No signing keys, mnemonics, or seed phrases in
   source. `spa_core/execution/eth_signer.py` uses `eth_account` and takes the
   private key as a runtime argument (never hardcoded). Read-only adapter/paper
   code does **not** import `execution/`; the only bridge
   (`paper_trading/engine.py`) is lazy-imported and gated behind a
   `self.live_execution` flag. Test files use well-known public Anvil/Hardhat
   test keys only.
7. **Logging safety** — No secrets are logged. The Telegram modules log
   "no token found" diagnostics without the value; `db_factory.py` masks DB
   passwords in logs; `whitelabel_api.py` prints a generated API key exactly once
   to stdout by design and stores only its sha256 (correct practice).
8. **JWT (investor portal)** — `family_fund/api/auth.py` verifies with
   `hmac.compare_digest` (timing-safe), is HMAC-only (no `alg=none`/algorithm-
   confusion surface), and enforces expiry + JTI revocation. Secret read from
   Keychain (`FAMILY_FUND_JWT_SECRET`).

---

## Remediation checklist for the operator

- [ ] **Rotate the Cloudflare Tunnel Token** (C1) — treat the old one as
      compromised; refresh in Cloudflare Zero Trust and re-run the script.
- [ ] **Rotate Family Fund default passwords** (M1) before public exposure;
      consider dropping demo accounts from the committed file.
- [ ] (Optional) Migrate legacy `push_*.sh` off the `~/.github_pat` fallback or
      delete obsolete push scripts (L1).
