# Security Action Items (2026-06-21)

## ⚠️ IMMEDIATE: Rotate Cloudflare Tunnel Token
**Why:** Token was stored in plaintext in scripts/cf_install_token.command.
Although the file is gitignored and never committed, treat as potentially exposed.

**How:**
1. Go to Cloudflare Zero Trust Dashboard → Networks → Tunnels
2. Find tunnel named "spa"
3. Click "..." → Rotate token
4. Copy new token
5. Update Keychain: `security add-generic-password -a spa -s CF_TUNNEL_TOKEN_SPA -w "NEW_TOKEN" -U`
6. Re-run cf_install_token.command to reinstall the daemon with new token

**Priority:** HIGH — do this week

## ⚠️ BEFORE LIVE TRADING: Rotate Family Fund Demo Credentials
**Why:** Default bcrypt credentials in spa_core/family_fund/users.json
**How:**
1. `python3 -m spa_core.family_fund.manage_users set --user owner --password-env OWNER_PW`
2. Repeat for admin, investor, readonly users
3. Delete or comment out demo account entries

**Priority:** HIGH — must do before any external access

## ✅ Clean (no action needed)
- No private keys hardcoded anywhere ✅
- No API keys in code ✅
- All subprocess calls use list form (no shell injection) ✅
- TLS verification enabled on all HTTP calls ✅
- JWT timing-safe comparison ✅
- GitHub PAT read from Keychain ✅
