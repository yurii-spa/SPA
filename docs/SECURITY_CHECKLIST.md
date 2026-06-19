# Frontend & Infrastructure Security Checklist

SPA version: v9.x | Last reviewed: 2026-06-19 | Status: Paper Trading Phase

## Frontend Security
- [x] Content Security Policy configured on Cloudflare Pages
- [x] HTTPS enforced (HTTP → HTTPS redirect)
- [x] HSTS enabled via Cloudflare
- [x] No private keys processed in browser
- [x] No wallet connection in paper trading phase
- [x] React islands: minimal JS footprint (client:visible hydration)
- [ ] CSP header audit — verify no unsafe-inline in production
- [ ] Subresource integrity (SRI) for CDN resources
- [ ] Regular dependency audit (npm audit)

## Domain Security
- [x] Cloudflare Proxy active (WAF + DDoS)
- [x] DNSSEC: enabled (Cloudflare manages)
- [x] earn-defi.com registered through Cloudflare Registrar
- [ ] RegistryLock: verify with registrar
- [ ] CAA records: add before go-live
- [ ] DMARC/SPF/DKIM: add if email sending needed

## Deployment Security
- [x] All deploys via Cloudflare Pages (no manual FTP)
- [x] GitHub main branch → CF Pages auto-build
- [x] Build logs retained on CF Pages
- [ ] Branch protection rules: require PR review before merge to main
- [ ] Secrets: PAT stored in macOS Keychain (not in repo)
- [ ] Environment variables: reviewed in CF Pages dashboard

## Smart Contract Security (Pre-Go-Live Checklist)
- [ ] External audit: engage auditor Q3 2026
- [ ] Deploy only to mainnet after audit complete
- [ ] Multisig: Gnosis Safe, minimum 2-of-3 signers
- [ ] Timelock: 48h minimum for parameter changes
- [ ] Contract addresses: publish in emergency-withdrawal page before deploy
- [ ] Bug bounty: set up on Immunefi before go-live

## Monitoring
- [x] Uptime: Cloudflare Analytics
- [x] Error alerts: Telegram bot (operator)
- [x] Drawdown monitoring: kill switch (automated, -5% monthly)
- [ ] Protocol health monitoring: adapter checks every cycle
- [ ] Alert escalation: define SLA (respond within 1h for P0)
