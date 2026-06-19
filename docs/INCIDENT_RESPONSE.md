# Incident Response Process

Version: 1.0 | Date: 2026-06-19

## Severity Levels

**P0 — Critical** (respond within 1 hour)
- Live funds at risk
- Smart contract exploit detected
- Frontend serving wrong contract addresses
- Kill switch triggered unexpectedly

**P1 — High** (respond within 4 hours)
- API down > 30 minutes
- Dashboard not loading
- Incorrect data displayed
- GoLiveChecker failures

**P2 — Medium** (respond within 24 hours)
- Paper trading data anomaly
- Build failure
- Minor UI issues

## Response Process

### Step 1: Detection
Sources: Telegram bot alert / User report / Monitoring dashboard

### Step 2: Triage (within 15 min for P0)
- Assess: real funds at risk? (paper trading = no)
- Activate kill switch if drawdown gate not already triggered
- Document: what happened, when, impact

### Step 3: Containment
- Kill switch → portfolio to cash buffer
- If frontend compromised: publish official statement on GitHub immediately
- Do NOT post unofficial channels

### Step 4: Communication (P0: within 4h, P1: within 24h)
- Email: yuriycooleshov@gmail.com
- GitHub: open incident issue in yurii-spa/SPA repo
- Update /emergency-withdrawal page if needed

### Step 5: Resolution
- Fix root cause
- Test fix
- Re-deploy via normal deployment process
- Verify fix in production

### Step 6: Post-Mortem (within 72h for P0/P1)
- Document in docs/INCIDENTS/ directory
- What happened, timeline, root cause, fix, prevention
- Publish summary publicly if live funds were affected

## Official Channels
- Email: yuriycooleshov@gmail.com
- GitHub: github.com/yurii-spa/SPA
- No Telegram group, no Discord
