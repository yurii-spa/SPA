# SPA Architecture Evolution v2.0
## Systematic Portfolio Allocator — Platform Architecture Document

**Date:** 2026-06-18  
**Author:** Senior Platform Architect (synthesized from 12 deep research reports + v1 baseline)  
**Status:** Living document — update with each major architectural decision  
**Domain:** earn-defi.com  
**Repository:** github.com/yurii-spa/SPA  

---

## Table of Contents

- [§1 Executive Summary](#1-executive-summary)
- [§2 Infrastructure Architecture](#2-infrastructure-architecture)
- [§3 Landing Page](#3-landing-page)
- [§4 Admin Panel & Investor Cabinet](#4-admin-panel--investor-cabinet)
- [§5 Security & Smart Contracts](#5-security--smart-contracts)
- [§6 Fee Structure](#6-fee-structure)
- [§7 Regulatory & Legal](#7-regulatory--legal)
- [§8 DevOps Pipeline](#8-devops-pipeline)
- [§9 Roadmap](#9-roadmap)
- [§10 Key Decisions Log (ADRs)](#10-key-decisions-log-adrs)

---

## §1 Executive Summary

SPA (Smart Passive Aggregator / Systematic Portfolio Allocator) is an autonomous DeFi yield optimizer running paper-trading with $100,000 virtual USDC since June 10, 2026. The platform executes a deterministic daily cycle: it fetches live APY/TVL data from 8+ whitelisted DeFi protocols, passes candidate allocations through a hard-gated RiskPolicy, and rebalances a virtual portfolio across tiers T1 (Aave V3, Compound V3, Morpho Steakhouse), T2 (Morpho Blue, Yearn V3, Euler V2, Maple), and T3-SPEC (Pendle). A Tournament system (strategies S0–S10) evaluates Sharpe, Calmar, Ulcer, and Rachev metrics in parallel, with the winning strategy's allocations feeding into a StrategyAllocator.

**Mission:** Build a 30-day verified paper track record → go-live with real capital ~August 1, 2026 → attract external family fund AUM in Q4 2026 → scale to institutional management with $1M+/year revenue by 2028.

**Current state (2026-06-18):**
- GoLiveChecker: 16/26 criteria passing (NOT READY)
- Gap monitor: running since June 10, 2026 (8 days of clean track)
- Infrastructure: Mac Mini M4 Pro, launchd, Cloudflare Tunnel, GitHub push

**Key architectural principles established by this document:**

The Mac Mini M4 Pro running macOS with launchd is the primary production compute environment for the foreseeable future. This is a deliberate choice documented in ADR-001: the Apple Silicon efficiency (3–45W idle-to-peak), cost profile ($4.50/month Hetzner cold standby vs $50+/month cloud), and the macOS Keychain for secrets management justify the unconventional choice over a cloud VPS. Research 09 confirmed production inference workloads run 2+ months without downtime on M4 hardware.

The platform separates infrastructure into three clearly bounded domains:

1. **Compute domain (Mac Mini):** cycle_runner, strategy tournament, RiskPolicy gate, paper trading engine, FastAPI family fund API, all launchd-managed daemons
2. **Edge domain (Cloudflare):** TLS termination, WAF, rate limiting (1 rule on free plan), DDoS protection, static asset CDN (Cloudflare Pages), tunnel routing
3. **Standby domain (Hetzner CX22):** rsync cold standby, watchdog, systemd-managed spa-cycle.service for failover

**Go-live financial architecture target:**

| Metric | Value |
|---|---|
| Virtual capital (paper) | $100,000 USDC |
| Target go-live | 2026-08-01 (ADR-002) |
| External AUM seed target | $2M+ (Q4 2026) |
| Smart contract vault deploy | Q2 2027 |
| Revenue breakeven | $5M AUM (~$125K/year) |

**Research sources informing this document:** 01 (competitor analysis), 02 (DevOps), 03 (landing conversion), 04 (investor UX), 05 (regulatory), 06 (Cloudflare), 07 (FastAPI), 08 (smart contracts), 09 (Mac Mini reliability), 10 (fee structure), 11 (frontend stack), 12 (Gnosis Safe).

---

## §2 Infrastructure Architecture

### 2.1 Primary Compute: Mac Mini M4 Pro

**Decision:** Mac Mini M4 Pro as sole production server (see ADR-001).

Research 09 documented real-world production data: M4 Mac Mini runs AI inference workloads for 2+ months without downtime; community reports of 3–11 year continuous server operation on previous Mac Mini generations. The hardware runs at 3–6W idle, peaks at 40–45W under load — dramatically lower than any comparable cloud instance.

**Critical structural risks acknowledged:**

| Risk | Mitigation |
|---|---|
| No ECC memory | Acceptable during paper trading; atomic writes + checksums; revisit before $1M+ live AUM |
| Single PSU | UPS (see §2.3); Hetzner failover |
| No IPMI/iLO | iBoot-G2 AutoPing ($150) + JetKVM ($103) |
| No hot-swap storage | rsync every 15 min to Hetzner; Hetzner VPS failover < 12 min |

**launchd service inventory (as of 2026-06-18):**

| Agent Label | Schedule | Binary | Status |
|---|---|---|---|
| `com.spa.daily_cycle` | Daily 08:00 | `python3 -m spa_core.paper_trading.cycle_runner` | ✅ Active |
| `com.spa.httpserver` | On-boot | `python3 -m spa_core.family_fund.http_server` | ✅ Active |
| `com.spa.cloudflared` | On-boot | `cloudflared tunnel run` | ✅ Active |
| `com.spa.autopush` | Every 90 min | `python3 auto_push.py` | ❌ Not installed (fix: `bash mp009_fix_launchd.command`) |

**Daily cycle flow:**

```
08:00 launchd triggers cycle_runner --verbose
    │
    ├─1. Adapter Orchestrator (read-only)
    │     └── DeFiLlama feed (TTL 300s) + protocol adapters
    │         → live APY/TVL snapshot
    │
    ├─2. multi_strategy_runner → S0–S10 in parallel
    │     └── tournament_evaluator (Sharpe/Calmar/Ulcer/Rachev)
    │         → data/tournament_results.json
    │
    ├─2b. StrategyAllocator
    │     └── target weights (USD per pool)
    │         → respects TVL floor ≥$5M, T2 cap ≤50%, per-protocol caps
    │
    ├─2c. RiskPolicy gate (DETERMINISTIC — LLM FORBIDDEN)
    │     └── approved=True/False
    │         → data/risk_policy_blocks.json (ring-buffer 100)
    │         ⛔ approved=False cannot be overridden by any agent
    │
    ├─3. delta > threshold → virtual rebalance trade
    │     └── data/trades.json (ring-buffer 500, is_demo: false)
    │
    ├─4. daily yield accrual on positions
    │
    ├─5. data/equity_curve_daily.json (ring-buffer 365)
    │
    ├─6. data/current_positions.json, data/paper_trading_status.json
    │
    ├─7. GoLiveChecker → data/golive_status.json (26 criteria)
    │
    └─8. promotion_engine.py → advisory only, read-only
```

**Log locations:**
- `/tmp/spa_cycle.log` — stdout from cycle_runner
- `/tmp/spa_cycle_err.log` — stderr
- `/tmp/spa_health_YYYYMMDD.log` — health_check.sh output (every 15 min)

### 2.2 Cloudflare Architecture

**Decision:** Cloudflare Tunnel + Pages for zero-exposure routing (see ADR-010).

The Mac Mini has no open ports directly exposed to the internet. All inbound traffic flows through `cloudflared`, which establishes an outbound-only persistent connection to Cloudflare's edge. This eliminates the attack surface of port-forwarding and dynamic DNS.

**Production `config.yml` for cloudflared** (informed by Research 06):

```yaml
# /Users/yuriikulieshov/.cloudflared/config.yml
# SECURITY: Do NOT hardcode tunnel UUID or credentials path in public repos
tunnel: YOUR-TUNNEL-UUID-HERE
credentials-file: /Users/yuriikulieshov/.cloudflared/YOUR-TUNNEL-UUID-HERE.json

originRequest:
  connectTimeout: 30s
  tcpKeepAlive: 30s
  keepAliveConnections: 100
  keepAliveTimeout: 90s
  # Do NOT set noTLSVerify: true in production

ingress:
  # FastAPI family fund API (port 8766 for FastAPI, 8765 for stdlib fallback)
  - hostname: api.earn-defi.com
    service: http://localhost:8766
    originRequest:
      connectTimeout: 30s
      httpHostHeader: "api.earn-defi.com"

  # Dashboard / Investor Cabinet (served by FastAPI static or Cloudflare Pages)
  - hostname: dashboard.earn-defi.com
    service: http://localhost:3001
    originRequest:
      connectTimeout: 30s

  # Staging environment (optional)
  - hostname: staging.earn-defi.com
    service: http://localhost:4000

  # Catch-all: return 404 for unmapped hostnames
  - service: http_status:404
```

**Cloudflare WAF rules (free plan: 5 custom rules):**

| Rule # | Name | Condition | Action |
|---|---|---|---|
| 1 | Whitelist office IP | `ip.src == YOUR_OFFICE_IP` | Skip |
| 2 | Block datacenter ASN | `ip.geoip.asnum in {AS14061 AS16509}` | JS Challenge |
| 3 | Block high threat score | `cf.threat_score > 25` | Block |
| 4 | Block malicious UA | `http.user_agent contains "sqlmap" or contains "nikto"` | Block |
| 5 | Protect sensitive paths | `http.request.uri.path in {"/api/admin" "/auth/"}` | Challenge |

> IP Access Rules (country-level geo-block for US/RU/BY/IR etc.) do NOT count toward the 5-rule limit.

**CORS configuration (Research 06 + 07 — critical rules):**

```python
# When allow_credentials=True, NEVER use "*" for allow_origins
# This will be rejected by browsers with a CORS error.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://earn-defi.com",
        "https://dashboard.earn-defi.com",
        "https://family-fund.pages.dev",  # Cloudflare Pages preview
    ],
    allow_credentials=True,   # Required for httpOnly cookie refresh tokens
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,              # Cache preflight for 10 minutes
)
```

**WebSocket considerations (Research 06):**
- WebSocket works on Cloudflare free plan
- Cloudflare's idle timeout is 100 seconds (not configurable)
- Implement 30-second client-side heartbeat to prevent disconnection:

```javascript
// Client-side WebSocket keepalive
const ws = new WebSocket('wss://api.earn-defi.com/ws');
setInterval(() => {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'ping' }));
  }
}, 30_000);
```

**Cloudflare tunnel health metric:**
```bash
# cloudflared exposes metrics at localhost:20241/metrics
# When healthy: cloudflared_tunnel_ha_connections == 4
curl -s localhost:20241/metrics | grep cloudflared_tunnel_ha_connections
```

**Cloudflare Pages deployment (landing + dashboard):**
- Landing: Astro 4 → `npm run build` → `dist/` directory → Cloudflare Pages
- Dashboard SPA: Vite + React → `npm run build` → `dist/` directory → Cloudflare Pages
- Both deploy automatically on push to `main` branch via GitHub Actions (GitHub-hosted runners only — see §8)

### 2.3 Reliability Stack

**Decision:** $365 one-time + $14.50/month for comprehensive reliability (Research 09).

The reliability stack is prioritized as follows:

**P0 — Power (critical, implement first):**

```
CyberPower CP850PFCLCD UPS ($110)
├── 850VA / 510W, pure sine wave (REQUIRED for Active PFC in Apple Silicon)
│   ⚠️  Simulated/stepped sine wave UPS WILL damage Mac Mini M4 PSU
├── ~25-30 minutes runtime at typical 15W Mac Mini load
├── USB integration: CyberPower PowerPanel Personal for macOS
│   → automatic graceful shutdown when battery < 20%
└── Syslog alert when switching to battery (via PowerPanel)
```

**P0 — Network failover:**

```
TP-Link ER605 V2 ($50) + USB LTE modem Huawei E3372 ($30) + SIM ($10/month)
├── 3× Gigabit WAN + 1× USB WAN (USB WAN only in V2 — verify hardware revision!)
├── Automatic failover: "Packet Loss" health check mode
│   ⚠️  NOT "Member Down" mode — ONT stays physically up during ISP outage,
│       Member Down never fires. Use Packet Loss only.
├── Failover detection: ~10-60 seconds (configurable ping interval)
├── SIM: AT&T/T-Mobile 4G, ~$10/month for 1GB failover data
└── Cloudflare Tunnel reconnects automatically after network change
```

**P1 — Cold standby (Hetzner CX22, ~€4/month):**

```
rsync (every 15 min, cron on Mac Mini):
  /Users/yuriikulieshov/Documents/SPA_Claude/data/ → root@hetzner:/srv/spa/data/

Watchdog on Hetzner VPS (every 2 min, cron):
  ping Mac Mini → 3 consecutive failures → trigger failover

Failover sequence:
  1. Hetzner Failover IP reassigned to VPS (90-110 sec via Robot API)
  2. systemctl start spa-cycle.service on VPS
  3. Total failover time: ~10-12 minutes (target < 30 min ✅)
```

**rsync cron entry (Mac Mini's crontab):**

```bash
# /tmp/spa_rsync.log captures all output
*/15 * * * * rsync -az --delete \
  --backup --backup-dir=/srv/spa/data-backup/$(date +%Y%m%d-%H%M) \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/ \
  -e "ssh -i /Users/yuriikulieshov/.ssh/hetzner_spa_key -o StrictHostKeyChecking=no" \
  root@<HETZNER_VPS_IP>:/srv/spa/data/ \
  >> /tmp/spa_rsync.log 2>&1
```

**Hetzner VPS watchdog script:**

```bash
#!/bin/bash
# /srv/spa/watchdog.sh — run every 2 minutes via cron on Hetzner VPS
# ⚠️  SECRETS POLICY: NEVER hardcode credentials in this file.
#     Load from environment variables set via /etc/environment or systemd EnvironmentFile.
PRIMARY_IP="${SPA_PRIMARY_IP}"
FAILURE_COUNT_FILE="/tmp/spa_primary_failures"

if ! ping -c 3 -W 5 "$PRIMARY_IP" > /dev/null 2>&1; then
  count=$(cat "$FAILURE_COUNT_FILE" 2>/dev/null || echo 0)
  count=$((count + 1))
  echo $count > "$FAILURE_COUNT_FILE"
  if [ "$count" -ge 3 ]; then
    echo "$(date): Primary DOWN — activating failover" >> /tmp/spa_failover.log
    # Reassign Hetzner Failover IP via Robot API
    curl -s -u "${ROBOT_USER}:${ROBOT_PASS}" \
      "https://robot-ws.your-server.de/failover/${FAILOVER_IP}" \
      -d "active_server_ip=${STANDBY_IP}" >> /tmp/spa_failover.log 2>&1
    systemctl start spa-cycle.service
    echo 0 > "$FAILURE_COUNT_FILE"
  fi
else
  echo 0 > "$FAILURE_COUNT_FILE"
fi
```

**systemd service on Hetzner VPS (equivalent to launchd):**

```ini
# /etc/systemd/system/spa-cycle.service
[Unit]
Description=SPA Daily Cycle (Standby)
After=network.target

[Service]
Type=oneshot
User=root
WorkingDirectory=/srv/spa/repo
EnvironmentFile=/etc/spa/secrets.env
ExecStart=/usr/bin/python3 -m spa_core.paper_trading.cycle_runner --verbose
StandardOutput=append:/tmp/spa_cycle_vps.log
StandardError=append:/tmp/spa_cycle_err_vps.log

[Install]
WantedBy=multi-user.target
```

**P1 — Remote reboot (iBoot-G2, $150-175):**

```
Dataprobe iBoot-G2 — smart PDU with AutoPing
├── AutoPing: continuously pings Mac Mini IP
├── No response after configurable timeout → power cycle automatically
├── Zero human intervention required for hang/freeze scenarios
└── Web UI for manual control from anywhere
```

**P2 — Thermal monitoring (TG Pro, $10):**

```
TG Pro v2.103 (supports M1–M5 Apple Silicon)
├── Monitors all sensors: CPU per-core, GPU, NVMe SSD, ambient
├── Auto Boost Rules: CPU die > 80°C → fan +30%; > 85°C → fan Max
├── Email alert: CPU die > 90°C (sustained)
└── CSV logging for trend analysis
```

**macOS SSD health monitoring (free, smartmontools):**

```bash
# Install once
brew install smartmontools

# Weekly cron (Monday 09:00):
# 0 9 * * 1 sudo smartctl -a disk0 | grep -E "(SMART overall|Available Spare|Percentage Used|Power On Hours|Unsafe Shutdowns)" >> /tmp/ssd_health_weekly.log

# Alert thresholds:
# Available Spare < 15% → WARNING
# Percentage Used > 80% → WARNING
# Media and Data Integrity Errors > 0 → CRITICAL
```

**Memory pressure monitoring (15-min launchd):**

```bash
#!/bin/bash
# /Users/yuriikulieshov/Documents/SPA_Claude/scripts/health_check.sh
LOG="/tmp/spa_health_$(date +%Y%m%d).log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

MEM_PRESSURE=$(memory_pressure | grep -oP '\d+(?=%)')
SWAP=$(sysctl vm.swapusage | grep -oP 'used = \K[0-9.]+[MG]')
DISK_FREE=$(df -BG / | awk 'NR==2{print $4}' | sed 's/G//')

echo "$TIMESTAMP | mem_pressure=${MEM_PRESSURE}% | swap=${SWAP} | disk_free=${DISK_FREE}GB" >> "$LOG"

if [ "${MEM_PRESSURE:-0}" -gt 70 ]; then
  echo "$TIMESTAMP ALERT: Memory pressure ${MEM_PRESSURE}% > 70%" >> "$LOG"
fi
if [ "${DISK_FREE:-100}" -lt 10 ]; then
  echo "$TIMESTAMP ALERT: Disk free ${DISK_FREE}GB < 10GB" >> "$LOG"
fi
```

**macOS update policy:**
- Disable automatic installation: System Settings → General → Software Update → uncheck "Install macOS updates"
- Keep "Check for updates" enabled (visibility without auto-install)
- Install updates manually on weekends after 09:00 (after daily cycle)
- Pre-download: `sudo softwareupdate --download --recommended`
- MDM option at scale: Mosyle Personal (free ≤5 devices) for up to 90-day defer

### 2.4 Secrets Management

**All secrets are stored in macOS Keychain exclusively. Never in files, environment variables, or code.**

```python
# spa_core/utils/keychain.py
import subprocess
import functools

@functools.lru_cache(maxsize=1)
def get_secret(service_name: str) -> str:
    """
    Read secret from macOS Keychain via subprocess.
    lru_cache ensures single subprocess call per process lifetime.

    Register secret once:
      security add-generic-password -s SERVICE_NAME -a spa -w 'secret_value'
    """
    result = subprocess.run(
        ["security", "find-generic-password", "-s", service_name, "-w"],
        capture_output=True, text=True, timeout=5
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Secret '{service_name}' not found in Keychain. "
            f"Run: security add-generic-password -s {service_name} -a spa -w '<value>'"
        )
    secret = result.stdout.strip()
    if not secret:
        raise ValueError(f"Secret '{service_name}' is empty")
    return secret
```

**Registered Keychain items:**

| Service Name | Purpose |
|---|---|
| `GITHUB_PAT_SPA` | GitHub API token for push_to_github.py |
| `FAMILY_FUND_JWT_SECRET` | JWT signing secret for FastAPI (≥32 chars) |
| `TELEGRAM_BOT_TOKEN` | Telegram alerts |
| `CLOUDFLARE_TUNNEL_TOKEN` | cloudflared authentication |

**SECRETS POLICY (from CLAUDE.md — non-negotiable):**
1. NEVER write tokens/keys/passwords into any file (including CLAUDE.md, docs, .command scripts, generated artifacts). No exceptions.
2. FORBIDDEN to generate `push_*.html` artifacts with embedded credentials.
3. If a secret ends up in a file → immediately revoke on github.com/settings/tokens, purge file and git history.

**On Hetzner VPS (no Keychain):**
```bash
# /etc/spa/secrets.env (permissions: chmod 600, owned by root)
# This file is NOT committed to git
GITHUB_PAT_SPA=...
TELEGRAM_BOT_TOKEN=...
```

---

## §3 Landing Page

### 3.1 Framework Decision: Astro 4

**Decision:** Astro 4 for landing page at earn-defi.com, deployed to Cloudflare Pages (see ADR-006).

Research 11 provides quantitative justification:

| Metric | Astro 4 (static) | Next.js 14 (static export) |
|---|---|---|
| JS bundle — homepage | ~8 KB gzip | ~85 KB gzip |
| Lighthouse Performance | **100** | ~88 |
| FCP on Slow 4G | ~0.5s | 1.0–1.5s |
| Build time (1,000 pages) | ~18s | ~52s |
| Cloudflare Pages support | ✅ Native, sponsored | ⚠️ "Do not use unless specific use case" (CF docs, Apr 2026) |
| Zero JS by default | ✅ | ❌ (React runtime always included) |

The 10× JS bundle difference (8KB vs 85KB) is structurally unavoidable with Next.js: it always ships the React runtime and router even with `output: 'export'`. For a fintech landing page where every millisecond of FCP affects trust signals, Astro is the correct choice.

**Astro Islands Architecture** enables the live stats widget without shipping JS to the rest of the page:

```astro
<!-- src/pages/index.astro -->
---
import HeroSection from '../components/HeroSection.astro';      // 0 KB JS
import LiveStatsWidget from '../components/LiveStats.jsx';       // React island
import HowItWorksSection from '../components/HowItWorks.astro'; // 0 KB JS
import CTASection from '../components/CTA.astro';               // 0 KB JS
---

<HeroSection />
<!-- JS only loads when widget scrolls into viewport — no FCP penalty -->
<LiveStatsWidget client:visible />
<HowItWorksSection />
<CTASection />
```

**Deployment:**
```bash
# Cloudflare Pages build settings:
# Build command: npm run build
# Build output directory: dist
# Node.js version: 20

# Local dev:
npm create cloudflare@latest -- --framework=astro
```

### 3.2 Conversion-Optimized Copy

**Decision based on Research 03:** The hero copy positions SPA on credibility and transparency — not promised returns.

**Hero section — Variant A (recommended):**

```
H1: Institutional-Grade DeFi Yield. Verified Daily.

SUBHEADLINE:
A systematic strategy that monitors 8+ DeFi protocols,
enforces hard risk gates — and shows you everything.
Built for family offices allocating $25K–$250K to
onchain stablecoins.

[Access Dashboard]          [Review Strategy Methodology]
 (Primary CTA)                    (Secondary CTA)
```

**Why this copy works (Research 03):**
- "Institutional-Grade" positions against retail aggregators (Yearn, Morpho) without overclaiming
- "Verified Daily" references the live track record — the primary differentiator vs. all competitors
- "Hard risk gates" speaks directly to family office due diligence concerns (drawdown protection)
- "Shows you everything" addresses opacity concerns that plague hedge funds
- No APY in hero headline — Sharpe ratio and drawdown first, yield second

**What never to include (Research 03 red flags):**

| Anti-pattern | Why it destroys trust |
|---|---|
| "12% guaranteed APY" | Illegal in most jurisdictions; signals scam |
| "AI-powered" without specifics | "AI-washing" — institutional investors ask for architecture docs |
| Anonymous team | Family offices require KYC on fund manager |
| Urgency tactics ("Limited spots") | Creates distrust in financial context |
| Round numbers without explanation | "$100K minimum" without rationale reads as arbitrary |

**Live Stats Block** (below the fold, 60-second polling):

```jsx
// src/components/LiveStats.jsx — React island
import { useQuery } from '@tanstack/react-query';

const METRICS = [
  { key: 'track_days', label: 'Track Days', format: (v) => `${v}d` },
  { key: 'sharpe_30d', label: 'Sharpe (30d)', format: (v) => v.toFixed(2) },
  { key: 'max_drawdown_pct', label: 'Max DD', format: (v) => `-${v.toFixed(2)}%` },
  { key: 'risk_gates_passed', label: 'Risk Gates', format: (v) => `${v}/26` },
  { key: 'ytd_apy_pct', label: 'YTD APY', format: (v) => `${v.toFixed(1)}%` },
];

export default function LiveStatsWidget() {
  const { data } = useQuery({
    queryKey: ['live-stats'],
    queryFn: () => fetch('https://api.earn-defi.com/api/health-public').then(r => r.json()),
    refetchInterval: 60_000,  // Poll every 60 seconds
    staleTime: 30_000,
  });

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-4 p-6 bg-slate-900 rounded-xl">
      {METRICS.map(({ key, label, format }) => (
        <div key={key} className="text-center">
          <div className="text-2xl font-mono font-bold text-emerald-400">
            {data ? format(data[key]) : '—'}
          </div>
          <div className="text-xs text-slate-400 mt-1">{label}</div>
        </div>
      ))}
    </div>
  );
}
```

**Paper trading as feature (Research 03):**
Prominently state the paper trading context and why it matters:
> "74% of family offices conduct 2-3 months of due diligence before committing capital. We built our track record phase to match that timeline — every allocation decision is logged, every risk gate is public, every day of the cycle is verifiable."

This reframes the paper trading phase from a limitation into a feature that speaks directly to institutional due diligence processes.

### 3.3 Page Structure

| Section | Purpose | Research ref |
|---|---|---|
| Hero | Hook + Primary CTA | Research 03 |
| Live Stats Block | Credibility anchor (Sharpe first, not APY) | Research 03 |
| How It Works | 3-step: Monitor → Gate → Rebalance | Research 03 |
| Track Record | Equity curve + drawdown chart | Research 03 |
| Risk Framework | TVL floor, kill switch, policy version | Research 03 |
| Competitor Comparison | Position vs Morpho/Yearn/Maple | Research 01 |
| Team + Contact | Real names, no anonymity | Research 03 |
| Disclaimers | Non-negotiable regulatory text | Research 05 |

### 3.4 Competitor Positioning Table

Informed by Research 01 (competitor analysis) and Research 10 (fee structure):

| Protocol | APY (USDC) | Management Fee | Performance Fee | Lock-up | Differentiator |
|---|---|---|---|---|---|
| **Morpho Steakhouse** | 6–8% | **0%** | **0%** | None | Scale, institutional trust, $10B+ TVL |
| **Yearn V3** | 5–8% | **0%** (YIP-85, temp) | **0%** | None | Brand, automation, DAO governance |
| **Maple syrupUSDC** | 6–10% | 0.7–0.9% all-in | — | Flexible | Real loans to institutions, $4.6B AUM |
| **Ribbon/Aevo** | 10–25% (ETH vol) | 2% | 10% | 1 week | Options premium, higher risk |
| **Enzyme Finance** | Varies | 1–2% (manager sets) | 10–20% | None | On-chain infrastructure, transparent |
| **VaultCraft** | Varies | Varies | Varies | None | ~$100M self-reported, multi-chain |
| **SPA (target)** | **8–12% net** | **1% (Phase 1)** | **15% + HWM** | **None** | Verified track record + deterministic risk |

**SPA's unlocked niche (Research 01):**
1. **Verifiable paper track record** — none of the above built a 30-day+ public paper trading history before launch
2. **Autonomous deterministic system** — no LLM in execution path (LLM_FORBIDDEN), no human discretion in daily rebalancing
3. **Investor portal for family office** — auto-generated PDF statements, Telegram digest, WCAG 2.1 AA dashboard
4. **Positioning gap** — between retail aggregators (Morpho/Yearn, zero fees, no investor relations) and institutional curated vaults (Maple, $1M+ minimums, private credit)

### 3.5 Required Disclaimers (Research 05)

These must appear on the landing page footer and full Risk Disclosure page:

```
⚠️  Risk Warning: DeFi protocols carry significant risks including smart contract 
vulnerabilities, liquidity risks, and total loss of capital. Past performance 
does not guarantee future results.

This platform is not regulated by any financial authority and does not constitute 
investment advice, financial advice, or a solicitation to invest.

Not available to US Persons (as defined under Regulation S of the US Securities Act 
of 1933), residents of Russia, Belarus, Iran, North Korea, Cuba, Syria, or other 
sanctioned jurisdictions.

DeFi risks include: smart contract exploits, protocol insolvency, stablecoin 
de-pegging, oracle manipulation, and regulatory actions. Allocate only capital 
you can afford to lose entirely.

This platform is not covered by any investor compensation scheme.

Privacy: [GDPR Privacy Policy link]
```

---

## §4 Admin Panel & Investor Cabinet

### 4.1 Frontend Stack Decision

**Decision:** Vite + React 19 SPA for dashboard; shadcn/ui + Tailwind CSS v4; TanStack Query v5 + Zustand for state; TradingView Lightweight Charts + Recharts for visualization (see ADR-007).

Research 11 quantified the choice:

**Why Vite + React, not Next.js for the dashboard:**
- The dashboard is a true SPA: deep state, protected routes, real-time data updates, session management
- Next.js App Router, RSC, SSR are all overhead for a client-authenticated dashboard
- Cloudflare Pages static export architecture (`output: 'export'`) loses most of Next.js's value
- Next-Auth is INCOMPATIBLE with pure static Cloudflare Pages (GitHub Discussion #8547 confirmed, Apr 2026)

**Why Astro is wrong for the dashboard:**
- Islands architecture is optimal for pages that are mostly static with a few interactive components
- Admin dashboard is 100% client-side interactive — every component needs JavaScript
- Using Astro here means `client:only` on every component, which eliminates all of Astro's benefits

**Why shadcn/ui over MUI:**

| Metric | shadcn/ui | MUI v7 |
|---|---|---|
| Bundle (20 components) | ~2.3 KB initial JS | ~91.7 KB |
| WCAG WAI-ARIA compliance | ✅ (via Radix primitives) | Partial |
| TypeScript ownership | ✅ You own the .tsx files | ❌ External package |
| Fintech template ecosystem | Dominant (2025–2026) | Moderate |
| Customization | Maximum (edit source) | Fighting Material Design |

EU EAA (European Accessibility Act) took effect June 2025 — WCAG 2.1 AA is now a legal requirement for fintech products serving EU users. Research 04 found only 31% of fintechs are currently compliant. shadcn/ui via Radix primitives provides the strongest structural WAI-ARIA compliance.

**Complete frontend stack:**

```
Framework:    Vite + React 19
Deploy:       Cloudflare Pages (static build)
API:          Python FastAPI on Mac Mini (via Cloudflare Tunnel)
Styling:      Tailwind CSS v4
UI Kit:       shadcn/ui (copy components into project)
Tables:       TanStack Table (headless, shadcn styling)
Forms:        React Hook Form + Zod
Charts:       Recharts (area, bar, pie) + TradingView LW Charts (candlestick)
State:        TanStack Query v5 (server state) + Zustand (client/UI state)
Auth:         Custom JWT: stdlib-based HS256 on FastAPI + httpOnly cookie refresh
Protected:    React Router v6 + <ProtectedRoute>
Type-safety:  hey-api/openapi-ts (auto-generate from FastAPI /openapi.json)
Starter:      github.com/abderrahimghazali/shadcn-fintech (MIT license)
```

### 4.2 FastAPI Backend Architecture

**Project structure (Research 07):**

```
spa_core/family_fund/
├── api/
│   ├── __init__.py
│   ├── app.py              # FastAPI factory (create_app())
│   ├── auth.py             # JWT HS256, in-memory JTI blacklist
│   ├── keychain.py         # macOS Keychain reader (lru_cache)
│   ├── dependencies.py     # get_current_user, require_role, require_min_role
│   ├── middleware.py       # Rate limiting (TokenBucket), Request-ID
│   ├── models.py           # Pydantic v2 schemas (Decimal for finance)
│   ├── file_store.py       # Thread-safe async JSON reader (asyncio.to_thread)
│   └── routes/
│       ├── health.py       # GET /api/health (public)
│       ├── portfolio.py    # GET /api/portfolio/{investor_id}
│       ├── positions.py    # GET /api/positions
│       ├── equity.py       # GET /api/equity-curve
│       ├── tournament.py   # GET /api/tournament
│       └── admin.py        # POST /api/admin/halt (SUPER_ADMIN only)
├── http_server.py          # Existing stdlib TCP server (port 8765, keep as fallback)
└── tests/
    ├── conftest.py         # pytest fixtures, tmp_path data files
    ├── test_auth.py
    └── test_portfolio.py
```

**JWT implementation — why HS256 (not RS256):**

Research 07 documents the decision: RS256 is needed when multiple services verify tokens without sharing a secret. SPA has a single FastAPI instance on a single Mac Mini. HS256 with a 64-byte secret from macOS Keychain is simpler, faster, and equally secure for this topology.

```python
# spa_core/family_fund/api/auth.py (key excerpts)
ACCESS_TOKEN_TTL  = 15 * 60        # 15 minutes
REFRESH_TOKEN_TTL = 7 * 24 * 3600  # 7 days

# JTI blacklist (in-memory, single process, Mac Mini)
_revoked_jti: dict[str, float] = {}  # jti → exp timestamp
_revoked_lock = threading.Lock()

# Pure stdlib JWT — no python-jose (abandoned 2021, 8 CVE),
# no PyJWT as external dep (CLAUDE.md: stdlib only in runtime)
def create_access_token(user_id: str, role: UserRole) -> str:
    secret = get_jwt_secret()  # from macOS Keychain
    now = int(time.time())
    header  = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url_encode(json.dumps({
        "sub": user_id,
        "role": role.value,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + ACCESS_TOKEN_TTL,
        "type": "access",
    }).encode())
    sig = _sign(header, payload, secret)
    return f"{header}.{payload}.{sig}"
```

**RBAC — 4 roles:**

```python
# spa_core/family_fund/api/models.py
class UserRole(str, Enum):
    SUPER_ADMIN  = "super_admin"
    FUND_MANAGER = "fund_manager"
    INVESTOR     = "investor"
    OBSERVER     = "observer"

ROLE_HIERARCHY: dict[UserRole, int] = {
    UserRole.OBSERVER:     0,
    UserRole.INVESTOR:     1,
    UserRole.FUND_MANAGER: 2,
    UserRole.SUPER_ADMIN:  3,
}
```

**Access control matrix:**

| Endpoint | OBSERVER | INVESTOR | FUND_MANAGER | SUPER_ADMIN |
|---|---|---|---|---|
| `GET /api/health` | ✅ public | ✅ | ✅ | ✅ |
| `GET /api/positions` | ✅ | ✅ | ✅ | ✅ |
| `GET /api/equity-curve` | ✅ | ✅ | ✅ | ✅ |
| `GET /api/tournament` | ✅ | ✅ | ✅ | ✅ |
| `GET /api/portfolio/{own_id}` | ❌ | ✅ | ✅ | ✅ |
| `GET /api/portfolio/{other_id}` | ❌ | ❌ | ✅ | ✅ |
| `POST /api/admin/halt` | ❌ | ❌ | ❌ | ✅ |

**Thread-safe async file reading (critical pattern — Research 07):**

FastAPI's async event loop must never be blocked by synchronous disk I/O. The solution uses `asyncio.to_thread()` (Python 3.9+) combined with a TTL cache:

```python
# spa_core/family_fund/api/file_store.py
_CACHE_TTL = 5.0  # seconds

async def read_json_file(path: str) -> Any:
    """Non-blocking JSON read with 5-second TTL cache and path traversal protection."""
    return await asyncio.to_thread(_read_json_sync, path)

def _read_json_sync(path: str) -> Any:
    now = time.monotonic()
    with _cache_lock:
        if path in _cache:
            data, expires_at = _cache[path]
            if now < expires_at:
                return data
    file_path = _allowed_path(path)  # Path traversal check: must be under data/
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    except json.JSONDecodeError:
        data = {}  # Return empty dict (cycle_runner may be mid-write)
    with _cache_lock:
        _cache[path] = (data, now + _CACHE_TTL)
    return data
```

This is safe because the cycle_runner writes atomically (`tmp + os.replace`). The file reader will always see either the complete old state or the complete new state — never a partial write.

**In-memory rate limiter (TokenBucket, no Redis — Research 07):**

```python
# spa_core/family_fund/api/rate_limiter.py
@dataclass
class TokenBucket:
    capacity: int        # max burst
    refill_rate: int     # tokens per refill_interval
    refill_interval: float  # seconds per refill cycle
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def allow(self, cost: int = 1) -> bool:
        with self._lock:
            self._refill()
            if self._tokens >= cost:
                self._tokens -= cost
                return True
            return False

# Rate limits by path:
# /auth/*       → 5 req/min burst 5   (brute-force protection)
# /api/admin/*  → 10 req/sec burst 10
# all others    → 60 req/sec burst 60

# Real IP behind Cloudflare (use CF-Connecting-IP header):
real_ip = request.headers.get("CF-Connecting-IP") or request.client.host
```

**Pydantic v2 — key decision: Decimal for all financial amounts:**

```python
class PositionItem(BaseModel):
    protocol: str = Field(..., min_length=1, max_length=100)
    tier: str = Field(..., pattern=r"^T[123](-\w+)?$")
    # Decimal not float — 0.1 + 0.2 != 0.3 in float
    # Critical for USD amounts and APY percentages
    allocation_usd: Decimal = Field(..., ge=Decimal("0"), le=Decimal("10_000_000"))
    apy_pct: Decimal = Field(..., ge=Decimal("0"), le=Decimal("100"))
    weight_pct: Decimal = Field(..., ge=Decimal("0"), le=Decimal("100"))
```

### 4.3 Investor Cabinet UX

**Information architecture (Research 04):**

```
Dashboard
  ├── Portfolio Overview (5 KPIs above fold)
  ├── Yield & Returns
  ├── Transactions
  ├── Documents
  ├── Notifications
  ├── Account Settings
  └── Support
```

**5 KPIs that must appear above the fold:**

| KPI | Data source | Format |
|---|---|---|
| Total Balance | `paper_trading_status.json → total_value` | `$XXX,XXX.XX` |
| Month Yield | Computed from equity_curve last 30 days | `+$X,XXX.XX` |
| Net APY | Annualized 30-day return | `X.XX%` |
| Allocation (T1/T2/Cash) | `current_positions.json` | Bar chart |
| System Status | Last cycle timestamp + GoLiveChecker | `✅ Running · 2h ago` |

**Yield History component requirements:**
- Default: Chart mode (AreaChart, 30-day range)
- Toggle: Table mode (date, value, daily return %)
- Range selector: 7D / 30D / 90D / YTD / ALL
- CSV export button (generates RFC 4180 compliant CSV)
- Mobile: swipe left/right to change range

**Documents section (Research 04):**
- Tagged PDFs: ISO 32000-1 compliant
- Signed URLs with 60-second expiry (prevents link sharing)
- Audit log of every download (investor_id, timestamp, document_id)
- Document types: Monthly Statement, Annual Report, KYC Confirmation, Risk Disclosure

**Notifications (Research 04):**
- Per-event-type channel selection: Email / Telegram / Push
- Security alerts locked ON (cannot be disabled by investor)
- Event types: Daily Cycle Complete, Rebalance Executed, Risk Gate Blocked, New Document Available

**WCAG 2.1 AA requirements (Research 04):**
- Minimum touch target: 44×44 px (iOS HIG standard)
- Color contrast ratio: ≥4.5:1 for normal text, ≥3:1 for large text
- All charts: text alternative (ARIA `role="img"` + `aria-label` with data summary)
- No pinch-zoom disabled (do not use `user-scalable=no`)
- Biometric authentication support on mobile (WebAuthn / platform authenticator)
- Skip navigation link for keyboard users

**Mobile bottom navigation (5 tabs):**

```
Dashboard | Portfolio | Transactions | Documents | Account
```

### 4.4 TanStack Query + Zustand Integration

**State management boundary (Research 11):**

| Concern | Tool | Reason |
|---|---|---|
| Server data (positions, equity, tournament) | TanStack Query v5 | Stale-while-revalidate, background refetch, cache invalidation |
| UI state (sidebar, active tab, modals) | Zustand | Module-level store, accessible from WebSocket callbacks |
| WebSocket push → cache update | Zustand → `queryClient.setQueryData()` | Bridges WS events to TQ cache without React context |

**QueryClient configuration:**

```typescript
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,         // 30s: data considered fresh
      gcTime:    5 * 60_000,     // 5min: keep in memory after unmount
      refetchOnWindowFocus: true, // Re-fetch when user returns to tab
      retry: 2,                   // 2 retries before error state
    },
  },
});
```

**Type-safe API client generation:**

```bash
# Run after any FastAPI endpoint changes
npx openapi-ts \
  --input https://api.earn-defi.com/openapi.json \
  --output src/api \
  --plugins @tanstack/react-query
```

This generates TypeScript interfaces and `useQuery`/`useMutation` hooks for all FastAPI endpoints, eliminating manual type maintenance.

---

## §5 Security & Smart Contracts

### 5.1 Current Security Posture (Paper Trading Phase)

During the paper trading phase, the execution attack surface is zero — no real capital, no on-chain transactions, no signing keys. The current security concerns are:

1. **Data integrity:** Atomic writes (tmp + os.replace) for all state files
2. **API security:** JWT + RBAC + rate limiting on FastAPI
3. **Infrastructure:** No exposed ports (Cloudflare Tunnel only)
4. **Secrets:** macOS Keychain exclusively
5. **LLM boundary:** LLM_FORBIDDEN_AGENTS = {risk, execution, monitoring}

### 5.2 Smart Contract Vault Architecture (Q4 2026 — Q2 2027)

**Target:** Deploy ERC-4626 compliant USDC yield vault on Ethereum mainnet for external capital management starting Q2 2027.

**ERC-4626 inflation attack protection (Research 08 — critical):**

The inflation attack (First-Depositor Attack) is the most common critical vulnerability in ERC-4626 vaults. The attacker becomes first depositor (1 wei → 1 share), donates a large amount directly to the vault address (bypassing `deposit()`), inflating `totalAssets`. The next legitimate depositor gets 0 shares due to rounding, and the attacker withdraws everything.

**Chosen mitigation: OpenZeppelin Virtual Shares + Decimals Offset**

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/extensions/ERC4626.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

contract SPAVault is ERC4626, ReentrancyGuard {
    // _decimalsOffset = 6 makes inflation attack 1,000,000x more expensive
    // Attacker would need to donate $100M+ to steal $100 from next depositor
    uint8 private constant DECIMALS_OFFSET = 6;

    constructor(IERC20 usdc_) ERC4626(usdc_) ERC20("SPA Yield Vault", "spvUSDC") {}

    function _decimalsOffset() internal pure override returns (uint8) {
        return DECIMALS_OFFSET;
    }

    // nonReentrant on all state-changing functions (Research 08)
    function deposit(uint256 assets, address receiver)
        public override nonReentrant returns (uint256) {
        return super.deposit(assets, receiver);
    }

    function mint(uint256 shares, address receiver)
        public override nonReentrant returns (uint256) {
        return super.mint(shares, receiver);
    }

    function withdraw(uint256 assets, address receiver, address owner)
        public override nonReentrant returns (uint256) {
        return super.withdraw(assets, receiver, owner);
    }

    function redeem(uint256 shares, address receiver, address owner)
        public override nonReentrant returns (uint256) {
        return super.redeem(shares, receiver, owner);
    }
}
```

**MEV sandwich attack protection (Research 08):**

```
Problem: Attacker front-runs harvest() → deposits before → share price rises → withdraws after.

Protection: Smooth yield accrual
  - Do NOT credit all yield in one transaction
  - Linear accrual over 7 days (Morpho Steakhouse pattern)
  - harvest() adds to a pending yield buffer; buffer releases linearly
```

**Additional ERC-4626 security checklist:**

| Vulnerability | Mitigation |
|---|---|
| Inflation attack | OZ ERC4626 with `_decimalsOffset = 6` |
| Re-entrancy | `nonReentrant` on deposit/mint/withdraw/redeem |
| Oracle manipulation | TWAP price feeds; circuit breakers on share price |
| Decimal mismatch | USDC has 6 decimals; normalize in `convertToShares` |
| Fee-on-transfer tokens | Only USDC as underlying (standard ERC20) |
| totalAssets manipulation | Use internal accounting, not `balanceOf(address(this))` |
| Rounding errors | Always round in favor of vault, not depositor |

### 5.3 Gnosis Safe 2/3 Multisig

**Architecture (Research 12):**

```
SPA Fund Safe (2/3 threshold)
├── Owner A: Ledger Nano X / Flex
│     └── Seed: BIP-39 (24 words) on Cryptotag metal plate
│         Passphrase (25th word) stored separately
│
├── Owner B: Trezor Safe 5 / Model T
│     └── Seed: Shamir Backup SLIP-39 (3-of-5 shards)
│         Shards distributed across 5 locations
│
└── Owner C: Coldcard Q (air-gapped, QR-based signing)
      └── Stored at separate physical location (trusted person)
      Note: Different vendor from A (Ledger) and B (Trezor)
            — protects against single-vendor firmware compromise
```

**Why 2/3 (not 3/3 or 2/2):**
- 3/3 creates a single-point-of-failure if one device fails
- 2/2 provides no redundancy — losing one device freezes all operations
- 2/3 is the industry standard for operational multisigs: maximum redundancy with minimum coordination overhead

**Hardware wallet vendor diversity rule (Research 12):**
Never use two devices from the same manufacturer in a 2/3 scheme. If Ledger releases compromised firmware (as happened in 2021 with the data breach), two Ledger owners can simultaneously be phished. The combination Ledger + Trezor + Coldcard (or Keystone) spans three different codebases, supply chains, and security models.

**Safe deployment procedure (Research 12 checklist):**

```bash
# 1. Verify deployed Safe on Etherscan
curl https://safe-transaction-mainnet.safe.global/api/v1/safes/YOUR_SAFE_ADDRESS/ \
  | python3 -m json.tool
# Expected: "owners": ["0xAAA...", "0xBBB...", "0xCCC..."], "threshold": 2

# 2. Remove deployer (MetaMask temp wallet) from owners
# → Safe UI: Settings → Owners → Remove Owner
# → Requires 2 signatures from hardware wallets

# 3. Fund test: send 0.01 ETH, then send 0.005 ETH out with 2 signatures
# NEVER send main capital before testing 2-of-3 with real hardware devices
```

**Security: NEVER use self-hosted GitHub runners on the Mac Mini containing Safe signing keys (Research 02).**
The Shai-Hulud worm (November 2025) used self-hosted GitHub Actions runners as C2 infrastructure. A compromised self-hosted runner on the same machine as Keychain-stored secrets could exfiltrate signing credentials.

### 5.4 Zodiac Roles Module

**Decision:** Zodiac Roles Modifier v4 for autonomous Python operator (see §2.1 cycle_runner) to execute routine rebalances without requiring 2/3 multisig signatures. (Research 08 + 12)

**Architecture:**

```
Gnosis Safe (2/3)
    └── Zodiac Roles Modifier v4 (module)
          └── Role: REBALANCER
                ├── members: [PYTHON_OPERATOR_EOA]
                ├── allow: USDC.approve(Aave_Pool_address)
                ├── allow: USDC.approve(Compound_Comet_address)
                ├── allow: USDC.approve(Morpho_Vault_address)
                ├── allow: AavePool.supply(USDC_address, any_amount, any_receiver, 0)
                ├── allow: AavePool.withdraw(USDC_address, any_amount, any_receiver)
                ├── allow: CompoundComet.supply(USDC_address, any_amount)
                ├── allow: CompoundComet.withdraw(USDC_address, any_amount)
                ├── allow: MorphoVault.deposit(any_amount, any_receiver)
                └── allow: MorphoVault.redeem(any_amount, any_receiver, any_owner)

          EXPLICITLY NOT ALLOWED for operator:
          ├── ❌ USDC.transfer(arbitrary_address) — cannot drain vault
          ├── ❌ Safe.addOwner() — cannot add new signers
          ├── ❌ Safe.removeOwner() — cannot remove signers
          ├── ❌ Safe.changeThreshold() — cannot lower security
          └── ❌ Any ETH value calls — cannot steal gas ETH
```

**⚠️ Critical security warning (Research 12):**
> In May 2026, the **Zodiac Delay Modifier** was exploited in a Gnosis Pay incident (~$3.2M loss). Separately, a SquidRouterModule exploit cost ~$3.2M from Safe users. **Do NOT install Zodiac Delay Modifier without auditing the current version.** Only use Zodiac Roles Modifier (different contract, different code path, not affected).

**Python operator executing transactions via Roles:**

```python
# spa_core/execution/operator.py
# LLM_FORBIDDEN: This module is in the execution domain.
# Do NOT import from read-only code.

from web3 import Web3
from eth_account import Account
import os

ROLES_MODIFIER_ADDRESS = os.environ["ROLES_MODIFIER_ADDRESS"]
REBALANCER_ROLE_KEY = Web3.keccak(text="rebalancer")  # bytes32

def execute_rebalance(to: str, data: bytes) -> str:
    """Execute a whitelisted DeFi operation via Zodiac Roles."""
    w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
    account = Account.from_key(os.environ["OPERATOR_KEY"])

    roles_contract = w3.eth.contract(
        address=ROLES_MODIFIER_ADDRESS,
        abi=ROLES_MODIFIER_ABI
    )
    tx = roles_contract.functions.execTransactionWithRole(
        to,           # Target contract (Aave/Compound/Morpho)
        0,            # ETH value (always 0 for USDC operations)
        data,         # Encoded function call
        0,            # Operation.Call (not delegatecall)
        REBALANCER_ROLE_KEY,
        True          # shouldRevert: yes, fail loudly
    ).build_transaction({
        "from": account.address,
        "gas": 300_000,
        "gasPrice": w3.eth.gas_price,
        "nonce": w3.eth.get_transaction_count(account.address),
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    return tx_hash.hex()
```

### 5.5 Timelock for Critical Operations

**Decision:** OpenZeppelin TimelockController (not Zodiac Delay Modifier — see warning above) for critical operations (see ADR for smart contract security).

```
Timelock delay matrix:
├── DeFi rebalance (routine)          → No timelock needed (Zodiac Roles)
├── Fee parameter changes              → MIN_DELAY = 48 hours
├── Adding/removing whitelisted pools  → MIN_DELAY = 72 hours
├── Changing Safe owners               → MIN_DELAY = 48 hours
├── Contract upgrade (proxy)           → MIN_DELAY = 7 days
└── Emergency pause (circuit breaker)  → Instant, but freeze-only (no withdraw)
```

**TimelockController deployment:**

```bash
# Using OpenZeppelin Hardhat deployment
# MIN_DELAY = 172800 (48 hours in seconds)
# PROPOSERS = [SAFE_ADDRESS]
# EXECUTORS = [SAFE_ADDRESS]
# ADMIN = address(0)  ← renounce admin after setup (no single point of control)
```

### 5.6 On-Chain Proof-of-Track: Merkle Root Decision Log

**Concept (Research 08):** For institutional LPs, verifying that the off-chain optimizer followed the stated RiskPolicy — and cannot retroactively alter decision records — is critical for due diligence.

```
Off-chain SPA Python:
    ├── Each daily cycle: write DecisionRecord
    │     {timestamp, cycle_id, strategy, action, pool, amount,
    │      risk_approved, policy_hash, equity_before, equity_after}
    ├── Batch N records → compute Merkle tree
    └── Anchor root on-chain weekly (via Safe execution)

On-chain DecisionLog contract:
    └── mapping(uint256 batchId → Anchor{root, timestamp, cycleCount, metadataURI})
        emit MerkleAnchor(batchId, root, timestamp, cycleCount)
```

**Solidity anchor contract:**

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/utils/cryptography/MerkleProof.sol";

contract SPADecisionLog {
    struct Anchor {
        bytes32 merkleRoot;
        uint256 timestamp;
        uint256 cycleCount;
        string  metadataURI; // IPFS CID of full batch JSON
    }

    mapping(uint256 => Anchor) public anchors;
    uint256 public batchCount;
    address public immutable safe; // Only SPA Safe can anchor

    event MerkleAnchor(uint256 indexed batchId, bytes32 merkleRoot,
                       uint256 timestamp, uint256 cycleCount);

    modifier onlySafe() {
        require(msg.sender == safe, "Unauthorized");
        _;
    }

    function anchor(bytes32 merkleRoot, uint256 cycleCount,
                    string calldata metadataURI) external onlySafe {
        uint256 batchId = batchCount++;
        anchors[batchId] = Anchor(merkleRoot, block.timestamp, cycleCount, metadataURI);
        emit MerkleAnchor(batchId, merkleRoot, block.timestamp, cycleCount);
    }

    function verify(uint256 batchId, bytes32 leaf,
                    bytes32[] calldata proof) external view returns (bool) {
        return MerkleProof.verify(proof, anchors[batchId].merkleRoot, leaf);
    }
}
```

**Anchoring cadence:** Weekly (7 daily cycle batches), published to IPFS + on-chain root. Cost: ~$0.50–$2 per anchor on Ethereum mainnet = ~$100–200/year.

### 5.7 Smart Contract Audit Plan

Informed by Research 08 market data (2026 audit costs):

| Phase | Firm | Scope | Timeline | Est. Cost |
|---|---|---|---|---|
| Q4 2026 | OpenZeppelin or ChainSecurity | ERC-4626 vault + Zodiac config + TimelockController | 2 engineers × 2 weeks | $80,000–$120,000 |
| Q4 2026 | Re-audit #1 (same firm) | Fix Critical/High findings | 1 engineer × 1 week | $20,000–$30,000 |
| Q1 2027 | Spearbit or Dedaub | Independent second review | 2 engineers × 2 weeks | $65,000–$100,000 |
| Q1 2027 | Re-audit #2 (same firm) | Fix Medium+ findings | 1 engineer × 1 week | $15,000–$25,000 |
| Q1 2027 | Code4rena or Sherlock contest | Crowd audit | Open pool | $37,500–$75,000 |
| Q2 2027 | Immunefi bug bounty launch | Ongoing post-deploy | Escrow | $150,000–$300,000 |

**Formal verification (DIY — no commercial Certora contract):**

Research 08 documents that Certora Prover became open-source in 2025. For $1–5M TVL, commercial FV engagement is cost-prohibitive ($2.39M/year as cited by Aave). Use free alternatives:

```bash
# a16z ERC4626 property tests (mandatory baseline)
git clone https://github.com/a16z/erc4626-tests
# Run against SPAVault before any audit submission

# Foundry invariant testing (included with forge)
forge test --match-contract SPAVaultInvariant

# Echidna fuzzing (Trail of Bits, free)
echidna-test . --contract SPAVaultFuzz --config echidna.config.yml
```

**5 invariants to verify:**

| Invariant | Method |
|---|---|
| `totalSupply > 0 → totalAssets ≥ totalSupply × virtualOffset` | Halmos |
| `deposit(x) → balanceOf += shares; shares > 0` | Echidna |
| `withdraw(shares) → assets ≤ totalAssets` (solvency) | Certora/Halmos |
| No inflation attack after seed | a16z ERC4626 tests |
| Operator cannot call `transfer()` (Zodiac) | Unit tests |

---

## §6 Fee Structure

### 6.1 Market Benchmarks

Research 10 analyzed 5 DeFi protocols and 300+ crypto hedge funds to establish the 2025–2026 fee landscape.

**Competitor fee comparison:**

| Protocol | Management Fee | Performance Fee | HWM | Notes |
|---|---|---|---|---|
| Yearn V3 | **0%** (YIP-85, temp) | **0%** | N/A | Fees disabled for V3 TVL growth |
| Morpho (curators) | **0%** protocol | 0–small curator fee | N/A | Morpho itself takes 0%; curator optional |
| Enzyme Finance | Manager-set 1–2% | Manager-set 10–20% | ✅ | On-chain infrastructure, not direct fund |
| Ribbon/Aevo (Theta) | **2%** | **10%** | No | Weekly crystallization; options vaults |
| Maple Finance | **0.7–0.9%** all-in | — | N/A | Institutional credit, $4.6B AUM |
| Crypto Fund avg (2025) | **1.70%** | **~20%** | ✅ | Crypto Insights Group, 300+ funds |
| TradFi hedge fund (2025) | **1.3–1.7%** | **16–18%** | ✅ | Industry average (down from 2/20) |
| **SPA Phase 1 target** | **1.0%** | **15%** | **✅ + 5% hurdle** | Competitive positioning |

**Key insight from Research 10:**
> "Fee-structure is not a competitive advantage by itself — it's a trust and positioning question. The fund must answer not 'why do we charge 1.5%' but 'why does our 12% net > 12% from Morpho without manager error risk.' The answer is track record, risk framework, compliance, and verifiable automation."

### 6.2 SPA Three-Phase Fee Schedule

**Phase 0: Family Fund / Track Record Builder (current — through go-live)**

| Parameter | Value |
|---|---|
| Management fee | **0%** |
| Performance fee | **10%** with HWM |
| Hurdle rate | None |
| Deposit / withdrawal fee | 0% / 0% |
| Lock-up | None |
| Fee currency | USDC |
| Crystallization | Quarterly |
| Governance token | No |

*Rationale: No point charging fees during paper trading or early family fund. 10% performance fee establishes industry-standard documentation from day one. HWM is absolute requirement — stated from the beginning.*

**Phase 1: Seed External Investors (launch Q4 2026 — $0 to $20M AUM)**

| Parameter | Value |
|---|---|
| Management fee | **1.0% per annum** (daily accrual, quarterly payment) |
| Performance fee | **15%** above hurdle, with HWM |
| Soft hurdle rate | **5%** — performance fee only on excess above 5% APY |
| Deposit fee | 0% |
| Withdrawal fee | 0% (optional: 0.10% for exits within 30 days — anti-hot-money) |
| Lock-up | None mandatory; 7-day notice for withdrawals > $50K |
| Fee currency | USDC |
| Crystallization | Annual (December 31) |
| HWM reset | At annual crystallization |
| Governance token | No |

**Math illustration for Phase 1 investor:**

```
Target gross APY:               12.0%
Hurdle (free zone):             -5.0%
Excess above hurdle:             7.0%
Performance fee (15% × 7%):     -1.05%
Management fee:                  -1.0%
Net APY to investor:            ~9.95%

Benchmark: Morpho USDC ~7.5%
SPA premium:                    +2.45%  ← This is the alpha the investor pays for
```

**Management fee accrual formula:**
```
Daily_fee = AUM × (0.01 / 365)
Quarterly payment = Σ Daily_fee over 91/92 days
```

**Phase 2: Institutional Scale ($20M+ AUM, target 2028)**

| Parameter | Value |
|---|---|
| Management fee | **0.75%** (volume discount from Phase 1) |
| Performance fee | **15–20%** (negotiated per investor; side letters available) |
| Hurdle rate | SOFR + 1% or 5% fixed (investor preference) |
| Minimum investment | $100,000 |
| 7-day notice | For withdrawals > $500K |
| Crystallization | Quarterly (SMAs) / Annual (commingled) |

### 6.3 High-Watermark Implementation

**HWM is non-negotiable** — Research 10 confirms institutional investors categorically reject funds without HWM. Without HWM, the manager could collect performance fees on recovering previous losses.

```python
# spa_core/family_fund/api/fee_calculator.py
# STDLIB ONLY — no external dependencies

from decimal import Decimal
import datetime

def calculate_performance_fee(
    nav_start_of_period: Decimal,
    nav_end_of_period: Decimal,
    high_watermark: Decimal,
    hurdle_rate_annual: Decimal,  # e.g., Decimal("0.05") for 5%
    performance_fee_rate: Decimal,  # e.g., Decimal("0.15") for 15%
    period_days: int,
) -> tuple[Decimal, Decimal]:
    """
    Returns (performance_fee_usdc, new_high_watermark).
    performance_fee = 0 if NAV <= HWM or net gain <= hurdle.
    """
    if nav_end_of_period <= high_watermark:
        return Decimal("0"), high_watermark  # Below HWM, no fee

    # Annualized hurdle → period hurdle
    period_hurdle_rate = hurdle_rate_annual * Decimal(period_days) / Decimal(365)
    hurdle_amount = nav_start_of_period * period_hurdle_rate
    gain_above_hwm = nav_end_of_period - high_watermark

    if gain_above_hwm <= hurdle_amount:
        return Decimal("0"), high_watermark  # Below hurdle, no fee

    excess_gain = gain_above_hwm - hurdle_amount
    fee = excess_gain * performance_fee_rate
    new_hwm = nav_end_of_period - fee  # HWM = NAV after fee extraction

    return fee.quantize(Decimal("0.01")), new_hwm
```

### 6.4 B2B White-Label Channel

**Revenue structure for future B2B partners (Research 10):**

| Tier | AUM Range | SPA Revenue |
|---|---|---|
| API Read-Only | Any | $500/month flat |
| Sub-Advisory | $1M–$10M | 25% of partner's management fee (~0.25% of AUM) |
| Enterprise | $10M+ | $5K–$20K/month + 15% revenue share |

**Governance token decision:** Deferred until $50M+ AUM + DAO-format + regulatory clarity (MiCA + US) + 2+ years of verified track record. Pre-maturity governance token issuance adds regulatory complexity without proportional value.

### 6.5 AUM Breakeven Analysis

Research 10 breakeven model:

| AUM | Revenue/year | Op. Cost/year | Net | Status |
|---|---|---|---|---|
| $1M | $25K | $40K | -$15K | ❌ Subsidy phase |
| $2M | $50K | $40K | +$10K | ⚠️ Barely viable |
| **$5M** | **$125K** | **$60K** | **+$65K** | **✅ Min viable** |
| $10M | $250K | $150K | +$100K | ✅ Small operation |
| $20M | $500K | $250K | +$250K | ✅ Real business |
| $50M | $1.25M | $500K | +$750K | ✅ Full team |

*Assumptions: 10% gross APY, 1% management fee, 15% performance fee on 10% net yield.*

---

## §7 Regulatory & Legal

### 7.1 Jurisdiction Strategy

Research 05 established a three-phase regulatory roadmap:

**Phase 0 — Family Fund (current):**
- **Ukraine TOV (LLC):** ~$500–$2K registration, 1–2 weeks
- Up to 10 participants: no licensing required
- No public marketing permitted
- Mandatory documents: Договір інвестора, Risk Disclosure, KYC form, internal AML policy

**Phase 1 — European seed investors (Q4 2026):**
- **Estonian OÜ** or **Lithuanian UAB:** €700–1,500 registration
- Sub-threshold AIFMD exemption: AUM < €100M = registration only (not full authorization)
- No public marketing to EU retail without UCITS or AIFMD authorization
- Private placement to accredited investors permitted

**Phase 2 — External institutional AUM (2027+):**
- **MiCA CASP Class 1** for portfolio management services: €50K minimum capital, €100–120K/year total cost, 3–6 month process
- Alternative: Sub-Advisory model (SPA manages capital, licensed partner holds client relationship)

### 7.2 Mandatory KYC Checklist

| Requirement | Detail |
|---|---|
| Government ID copy | Passport or national ID |
| OFAC sanctions screening | US Treasury OFAC list |
| EU Consolidated List | European Union sanctions |
| PEP check | Politically Exposed Persons (World-Check or similar) |
| Source of funds declaration | Signed statement |
| Investor suitability | Self-certification as accredited/professional investor |
| AML policy reference | Reference to internal AML policy document |

### 7.3 Mandatory Geo-Blocks

**Blocked jurisdictions (mandatory — no exceptions):**

| Jurisdiction | Reason |
|---|---|
| United States | Securities laws (Regulation S, Investment Adviser Act) |
| Russia | OFAC/EU sanctions |
| Belarus | OFAC/EU sanctions |
| Iran | OFAC primary sanctions |
| North Korea (DPRK) | OFAC primary sanctions |
| Cuba | OFAC primary sanctions |
| Syria | OFAC primary sanctions |

**Recommended additional blocks:**
- Myanmar, Venezuela, Nicaragua (OFAC secondary sanctions risk)

**Cloudflare geo-block implementation:**

```
WAF Rule (IP Access Rules, free, unlimited):
  Field: Country
  Operator: is in
  Value: United States, Russia, Belarus, Iran, North Korea, Cuba, Syria
  Action: Block
```

### 7.4 Regulatory Compliance Checklist

| Requirement | Status | Notes |
|---|---|---|
| Risk Warning on all pages | 🔲 Pending | Must be above fold |
| "Not regulated" disclaimer | 🔲 Pending | Required in all jurisdictions |
| "Not available to US Persons" | 🔲 Pending | Regulation S requirement |
| DeFi risk disclosure | 🔲 Pending | Protocol-specific risks |
| "Not financial advice" | 🔲 Pending | Every communication |
| GDPR Privacy Policy | 🔲 Pending | For EU users (already in scope) |
| Cookie consent | 🔲 Pending | EU ePrivacy Directive |
| KYC onboarding | 🔲 Pending | Before any fund deposit |
| AML policy | 🔲 Pending | Internal document required |
| Investor agreement (Договір) | ✅ In docs/legal/ | Needs legal review |
| Geo-block implementation | 🔲 Pending | Cloudflare WAF |
| Sanctions screening provider | 🔲 Pending | World-Check or Chainalysis |

### 7.5 Smart Contract Regulatory Position

Research 05 notes:
- A smart contract vault **without a public token** = minimal regulatory risk under current MiCA framework
- An operator that **collects fees** = not fully decentralized under MiCA Article 4(1)(4)
- The SPA vault with fee collection by operator = likely qualifies as CASP under MiCA
- Mitigant: Phase 1 uses off-chain investor agreements (Договір) with no on-chain token, reducing regulatory surface area

---

## §8 DevOps Pipeline

### 8.1 CI/CD Architecture

**Decision:** GitHub-hosted runners for all CI/CD. NO self-hosted runners on production Mac Mini (see ADR-011).

Research 02 documented the critical security reason: the Shai-Hulud worm (November 2025) specifically targeted self-hosted GitHub Actions runners as C2 infrastructure. A self-hosted runner on the same machine as the Keychain secrets is a catastrophic attack vector.

**GitHub Actions workflow — CI (tests only):**

```yaml
# .github/workflows/ci.yml
name: SPA CI

on:
  push:
    branches: [main, dev]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest  # GitHub-hosted runner ONLY

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Run unit tests
        run: python3 -m pytest spa_core/tests/ -v --tb=short

      - name: Run integration tests
        run: python3 -m pytest tests/ -v --tb=short

      - name: Check for secrets in code
        run: |
          # Fail if any of these patterns appear in changed files
          git diff HEAD~1 --name-only | xargs grep -l \
            -e "ghp_" -e "github_pat_" -e "sk-" \
            && echo "SECRET DETECTED" && exit 1 || echo "No secrets found"
```

**Production deployment (no CI, manual atomic symlink pattern — Research 02):**

```bash
#!/bin/bash
# /Users/yuriikulieshov/Documents/SPA_Claude/scripts/deploy.sh
# Usage: bash deploy.sh <version>
# Atomic symlink deploy — zero-downtime, instant rollback

set -euo pipefail
VERSION="${1:-$(date +%Y%m%d_%H%M%S)}"
BASE_DIR="/Users/yuriikulieshov/Documents/SPA_Claude"
RELEASES_DIR="$BASE_DIR/releases"
NEW_RELEASE="$RELEASES_DIR/$VERSION"
CURRENT_LINK="$BASE_DIR/current"

echo "Deploying version $VERSION..."

# 1. Create new release directory
mkdir -p "$NEW_RELEASE"
rsync -a --exclude=".git" --exclude="data/" --exclude="releases/" \
  "$BASE_DIR/" "$NEW_RELEASE/"

# 2. Run tests in new release
cd "$NEW_RELEASE"
python3 -m pytest spa_core/tests/ -q --tb=short
echo "Tests passed ✅"

# 3. Atomic symlink swap (the key: os.symlink is atomic on POSIX)
PREVIOUS=$(readlink "$CURRENT_LINK" 2>/dev/null || echo "")
ln -sfn "$NEW_RELEASE" "${CURRENT_LINK}.new"
mv -f "${CURRENT_LINK}.new" "$CURRENT_LINK"  # atomic on macOS

echo "Deployed $VERSION. Previous: $PREVIOUS"
echo "Rollback: ln -sfn '$PREVIOUS' '$CURRENT_LINK'"
```

```bash
#!/bin/bash
# /Users/yuriikulieshov/Documents/SPA_Claude/scripts/rollback.sh
# Usage: bash rollback.sh <previous_version>
set -euo pipefail
PREVIOUS="${1}"
BASE_DIR="/Users/yuriikulieshov/Documents/SPA_Claude"
ln -sfn "$BASE_DIR/releases/$PREVIOUS" "$BASE_DIR/current"
echo "Rolled back to $PREVIOUS"
```

### 8.2 GitHub Push Automation

**push_to_github.py usage (always absolute paths):**

```bash
# Single file push
python3 push_to_github.py --file /abs/path/to/file.py --message "message"

# Multiple files
python3 push_to_github.py \
  --files /abs/path/a.py /abs/path/b.json \
  --message "descriptive message"

# Dry run (verify without pushing)
python3 push_to_github.py --files /abs/path/file.py --message "test" --dry-run
```

**Push dependency rule:** Always push the entire dependency closure of a changed module. If `cycle_runner.py` changes, push it along with all modules it imports.

**autopush launchd** (com.spa.autopush — currently broken, fix: `bash mp009_fix_launchd.command`):
- Schedule: Every 90 minutes
- Pushes: `data/*.json` state files to GitHub
- Required for GoLiveChecker criterion: `autopush_installed: true`

### 8.3 Log Management

Research 02 log retention policy:

| Log type | Retention | Storage |
|---|---|---|
| `trades.json` | **Forever** | Push to GitHub daily |
| `equity_curve_daily.json` | **Forever** | Push to GitHub daily |
| `data/*.json` state files | **Forever** | Push to GitHub via autopush |
| `/tmp/spa_cycle.log` | 90 days | newsyslog rotation |
| `/tmp/spa_health_*.log` | 90 days | newsyslog rotation |
| `/tmp/spa_rsync.log` | 30 days | newsyslog rotation |

**newsyslog configuration for macOS log rotation:**

```
# /etc/newsyslog.d/spa.conf
# logfile                               mode  count size  when  flags
/tmp/spa_cycle.log                      644   90    10000 @T00  JN
/tmp/spa_cycle_err.log                  644   90    10000 @T00  JN
/tmp/spa_health_*.log                   644   90    1000  @T00  JN
```

### 8.4 Monitoring Stack ($0/month)

Research 02 recommended three-layer monitoring:

**Layer 1: External uptime (UptimeRobot free):**
- 50 free monitors, 5-minute check interval
- Monitor `https://api.earn-defi.com/api/health` → HTTP status 200
- Alert channel: Email + Telegram Bot

**Layer 2: Self-hosted uptime (Uptime Kuma on Hetzner VPS):**
- Internal monitoring of Mac Mini services (not dependent on Cloudflare)
- Monitors: port 8765, port 8766, cycle runner last-run timestamp
- Dashboard: `http://hetzner_ip:3001`

**Layer 3: Telegram alerts (SPA-specific):**

```python
# spa_core/monitoring/telegram_notifier.py
# STDLIB ONLY — uses urllib, not requests
import json, urllib.request
from spa_core.utils.keychain import get_secret

def send_alert(message: str, level: str = "INFO") -> None:
    """Send Telegram message via Bot API. Pure stdlib."""
    token = get_secret("TELEGRAM_BOT_TOKEN")
    chat_id = get_secret("TELEGRAM_CHAT_ID")
    emoji = {"INFO": "ℹ️", "WARNING": "⚠️", "CRITICAL": "🚨"}.get(level, "📢")
    payload = json.dumps({
        "chat_id": chat_id,
        "text": f"{emoji} *SPA Alert*\n{message}",
        "parse_mode": "Markdown"
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())
```

**Alert triggers:**

| Event | Level | Action |
|---|---|---|
| Daily cycle failed | CRITICAL | Telegram + Email |
| RiskPolicy blocked rebalance | WARNING | Telegram |
| Gap in equity curve | CRITICAL | Telegram + Email |
| Mac Mini memory pressure > 70% | WARNING | Telegram |
| Mac Mini disk free < 10GB | CRITICAL | Telegram + Email |
| GoLiveChecker status change | INFO | Telegram |
| Hetzner failover activated | CRITICAL | Telegram + Email |
| New Safe pending transaction | WARNING | Telegram (see §5.3) |
| Unknown Safe module detected | CRITICAL | Telegram + Email |
| Gas balance < 0.05 ETH | WARNING | Telegram |

### 8.5 Testing Infrastructure

**Test suite structure:**

```
spa_core/tests/    (~800+ unit tests)
    ├── test_adapters/
    ├── test_allocator/
    ├── test_risk/
    ├── test_paper_trading/
    └── test_strategies/

tests/             (11 integration tests)
    ├── test_cycle_runner.py
    ├── test_golive_checker.py
    └── test_gap_monitor.py
```

**Run all tests:**

```bash
# Unit + integration
python3 -m pytest spa_core/tests/ tests/ -v

# Single module
python3 -m pytest spa_core/tests/test_risk/ -v

# With coverage
python3 -m pytest spa_core/tests/ --cov=spa_core --cov-report=html
```

**FastAPI test pattern (from Research 07 — no mocking FS):**

```python
# spa_core/family_fund/tests/conftest.py
@pytest.fixture
def data_dir(tmp_path: Path, sample_positions: list[dict]) -> Path:
    """Creates real tmp data files, monkeypatches _BASE_DIR in file_store."""
    data = tmp_path / "data"
    data.mkdir()
    (data / "current_positions.json").write_text(
        json.dumps({"positions": sample_positions}), encoding="utf-8"
    )
    import spa_core.family_fund.api.file_store as fs
    original_base = fs._BASE_DIR
    fs._BASE_DIR = tmp_path
    fs.invalidate_cache()
    yield data
    fs._BASE_DIR = original_base
    fs.invalidate_cache()
```

---

## §9 Roadmap

### 9.1 Phase Overview

| Phase | Name | Timeline | Milestone |
|---|---|---|---|
| **0** | Paper Track Record | June 10 — ~Aug 1, 2026 | 30 days clean track + GoLiveChecker 26/26 |
| **1** | Go-Live + Family Fund | Aug 1, 2026 | First real capital cycle executed |
| **2** | Public Landing + Seed AUM | Q4 2026 | earn-defi.com live; first external investor |
| **3** | Smart Contract Vault | Q4 2026 – Q2 2027 | ERC-4626 vault audited + deployed |
| **4** | Institutional | 2028 | $20M+ AUM, full team, MiCA CASP |

### 9.2 Phase 0: Paper Track Record (current)

**Status:** Day 8 of 30-day minimum (as of 2026-06-18)

**Blockers to resolve before go-live (16/26 GoLiveChecker passing):**

```
Failing criteria (estimated):
  ├── autopush_installed           → bash mp009_fix_launchd.command
  ├── gap_monitor_30d              → 22 more days of clean cycles
  ├── min_track_days (30)          → 22 more days
  ├── trades_real (is_demo:false)  → already false — check criterion logic
  ├── Telegram daily alerts        → wire alert_daily.py
  ├── APY threshold check          → verify current equity curve
  └── ... (remaining 10 criteria) → run golive_checker --verbose for full list
```

**Immediate actions:**

```bash
# 1. Fix autopush launchd
bash /Users/yuriikulieshov/Documents/SPA_Claude/mp009_fix_launchd.command

# 2. Verify GoLiveChecker detailed output
python3 -m spa_core.paper_trading.golive_checker --verbose

# 3. Verify gap monitor
python3 -m spa_core.paper_trading.gap_monitor

# 4. Check equity curve continuity
cat data/gap_monitor.json | python3 -m json.tool
```

### 9.3 Phase 1: Go-Live (August 1, 2026)

**ADR-002 go-live transfer rule requirements:**
1. GoLiveChecker: all 26 criteria passing
2. READY status maintained for 7+ consecutive days
3. gap_monitor: 30+ days without gaps
4. Manual review by Owner (Yurii)
5. Execute: `python3 -m spa_core.golive.activate` → enter "I CONFIRM LIVE TRADING"

**Week-by-week execution plan:**

| Week | Dates | Focus |
|---|---|---|
| W1 | June 18–25 | Fix autopush, wire Telegram alerts, verify all data integrity checks |
| W2 | June 25 – July 2 | GoLiveChecker criteria 17–22 |
| W3 | July 2–9 | GoLiveChecker criteria 23–26; 7-day READY streak |
| W4 | July 9–16 | Gap monitor 30-day confirmation (June 10 + 30 = July 10) |
| W5 | July 16–23 | Performance review, manual review |
| W6 | July 23–30 | Go-live preparation: safety checks, backup, documentation |
| — | ~Aug 1 | **GO-LIVE** |

### 9.4 Phase 2: Public Platform (Q4 2026)

**Infrastructure deliverables:**

| Deliverable | Owner | Target |
|---|---|---|
| earn-defi.com landing page (Astro 4) | Frontend | Oct 2026 |
| Dashboard v4.0 (Vite + React) | Frontend | Oct 2026 |
| FastAPI family fund API | Backend | Sep 2026 |
| Cloudflare WAF + geo-blocks | DevOps | Sep 2026 |
| KYC onboarding flow | Legal + Backend | Nov 2026 |
| Investor PDF statements | Backend | Nov 2026 |
| WCAG 2.1 AA audit | Frontend | Nov 2026 |
| Estonian OÜ registration | Legal | Sep 2026 |
| Investor agreement v2 | Legal | Oct 2026 |

**AUM acquisition strategy:**
- Target: Family office contacts, crypto-native HNW individuals, $25K–$250K ticket size
- Channel: Direct relationships only during seed phase (no public marketing before AIFMD sub-threshold registration)
- First external investor target: $200K–$500K by December 2026

### 9.5 Phase 3: Smart Contract Vault (Q4 2026 – Q2 2027)

**Milestone timeline:**

```
June–July 2026:    Write SPAVault.sol (ERC-4626, OZ base, decimalsOffset=6)
                   Write Zodiac Roles configuration
                   Write a16z ERC4626 property tests + Echidna invariants

August 2026:       RFP → select Audit #1 firm (target: OZ or ChainSecurity)
                   Freeze code commit hash for audit

September 2026:    Receive Audit #1 report
                   Fix Critical + High findings
                   Re-audit #1

October–Nov 2026:  RFP → Audit #2 (Spearbit or Dedaub)
                   Audit #2 + re-audit #2

December 2026:     Code4rena or Sherlock contest ($37,500–$75,000 pool)

Jan–Feb 2027:      Fix contest findings
                   Deploy DecisionLog contract (Merkle root anchoring)
                   Deploy TimelockController

March 2027:        Immunefi bug bounty launch (escrow $150K–$300K)
                   Testnet deploy with real LP testing

April–May 2027:    Mainnet launch (TVL cap: $1M for first 30 days)
                   → Raise cap gradually based on performance
```

### 9.6 Phase 4: Institutional (2028+)

**Conditions for Phase 4 activation:**
- AUM > $20M externally managed
- 2+ years verified on-chain track record
- MiCA CASP Class 1 license obtained (or sub-advisory arrangement with licensed partner)
- Full team: 2 engineers, 1 compliance officer, 1 relationship manager
- Smart contract vault with 2 audits + bug bounty live

**Revenue target (Research 10 model at $50M AUM):**
- Management fee (0.75%): $375,000/year
- Performance fee (15% × 10% net yield): $750,000/year
- B2B white-label revenue: $300,000–$600,000/year
- **Total: $1.4M–$1.7M/year** (approaching GRAND_VISION target of $1M/year)

---

## §10 Key Decisions Log (ADRs)

Each ADR captures the decision, the research that informed it, and the date it was made or confirmed by this document.

---

### ADR-001: Mac Mini M4 Pro as Primary Production Server

**Date:** 2026-06-10 (confirmed by this document 2026-06-18)  
**Status:** Accepted  

**Decision:** The Mac Mini M4 Pro running macOS with launchd is the primary production compute environment for all SPA services.

**Context:** The alternatives were a cloud VPS (Hetzner CX32 ~€10/month, Contabo VPS, AWS t3.medium), or a colocation arrangement.

**Research basis (Research 09):**
- 3–6W idle power, 40–45W peak: dramatically more efficient than any cloud VPS equivalent
- Production AI inference workloads: 2+ months without downtime documented (acdigest.substack.com, May 2026)
- Community data: 3–11 year continuous server lifespans on Apple Silicon
- macOS Keychain: native secrets management with no additional infrastructure
- Total cost: $0/month (already owned) vs. $10–50/month for equivalent cloud

**Structural risks accepted:**
- No ECC memory: accepted during paper trading; revisit for $1M+ live AUM
- Single PSU: mitigated by UPS (pure sine wave, CyberPower CP850PFCLCD)
- No IPMI: mitigated by iBoot-G2 AutoPing + JetKVM

**Rejected alternatives:**
- Cloud VPS: Higher cost, SSH-only access, no Keychain, latency for local file operations
- Colocation: Cost and logistics overhead, unnecessary for current scale

---

### ADR-002: Go-Live Transfer Rule (from CLAUDE.md)

**Date:** Originally set in MASTER_PLAN_v1.md  
**Status:** Accepted, governing  

**Decision:** Live trading activation requires: (1) GoLiveChecker 26/26 criteria passing, (2) READY status maintained 7+ consecutive days, (3) gap_monitor 30+ days without gaps, (4) manual review by Owner, (5) explicit confirmation in activate.py ("I CONFIRM LIVE TRADING").

**Rationale:** Protects against premature go-live with insufficient track record. The 30-day gap_monitor requirement ensures continuous operation quality over a full month, not just point-in-time readiness.

**Current estimated go-live date:** ~August 1, 2026 (pending gap_monitor completion July 10 + 7-day READY streak).

---

### ADR-003: Python Standard Library Only in Runtime Code

**Date:** Project inception  
**Status:** Accepted, immutable  

**Decision:** All runtime code (cycle_runner, adapters, allocator, risk, paper_trading) uses only Python standard library. No external dependencies (pip packages) in the execution path.

**Rationale:** Eliminates supply chain attack surface; no pip install required for production; macOS Python 3.11 is the only runtime dependency; simplifies deployment to Hetzner standby.

**Exceptions:** FastAPI + Pydantic for the family fund API (separate domain, not in trading core); pytest for testing infrastructure.

---

### ADR-004: Atomic Writes for All State Files

**Date:** Project inception  
**Status:** Accepted, immutable  

**Decision:** All writes to `data/*.json` state files use the atomic pattern: write to temp file → `os.replace(tmp, target)`. Never use direct `open(..., 'w')` on state files.

**Rationale:** `os.replace` is atomic on POSIX (macOS) — the reader either sees the old file or the new file, never a partially written state. This is critical when cycle_runner writes concurrently with FastAPI reads.

**Code pattern:**
```python
import json, os, tempfile

def atomic_write(path: str, data: dict) -> None:
    dir_ = os.path.dirname(os.path.abspath(path))
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False, suffix=".tmp") as f:
        json.dump(data, f, indent=2)
        tmp = f.name
    os.replace(tmp, path)
```

---

### ADR-005: LLM Forbidden in Risk/Execution/Monitoring

**Date:** Project inception  
**Status:** Accepted, immutable  

**Decision:** `LLM_FORBIDDEN_AGENTS = {risk, execution, monitoring}`. No LLM API calls are permitted in the RiskPolicy gate, execution domain, or monitoring components.

**Rationale:** Prompt injection attacks targeting capital are a critical attack vector. A malicious input in APY data or trade descriptions could manipulate an LLM-based risk assessment. The RiskPolicy is deterministic by design — its behavior is fully predictable and auditable.

**Enforcement:** `approved=False` from RiskPolicy cannot be overridden by any agent, LLM or otherwise.

---

### ADR-006: Astro 4 for Landing Page

**Date:** 2026-06-18 (this document)  
**Status:** Accepted  

**Decision:** Use Astro 4 (not Next.js, not plain HTML) for the earn-defi.com landing page.

**Research basis (Research 11):**
- 8KB vs 85KB JS bundle: Astro's zero-JS-by-default is uniquely suited for mostly-static fintech landing pages
- Lighthouse 100 vs ~88: directly impacts trust signals for institutional visitors
- Cloudflare officially sponsors Astro; Next.js on Pages has documented limitations (Apr 2026)
- Islands architecture (`client:visible`) loads the live stats widget only when scrolled into view — no FCP penalty

**Rejected:** Next.js static export (larger bundle, Cloudflare Pages issues); Plain HTML (no component reuse, no Islands for live stats).

---

### ADR-007: Vite + React SPA for Dashboard

**Date:** 2026-06-18 (this document)  
**Status:** Accepted  

**Decision:** Vite + React 19 as a pure client-side SPA for Admin Panel and Investor Cabinet.

**Research basis (Research 11):**
- Dashboard is 100% client-interactive — Islands architecture (Astro) loses all value
- Next-Auth is incompatible with pure static Cloudflare Pages (GitHub Discussion #8547)
- Next.js App Router/RSC overhead for an authenticated SPA serving pre-fetched JSON
- Custom JWT in FastAPI (stdlib) is simpler and avoids next-auth dependency

---

### ADR-008: JWT HS256 for Single-Instance API

**Date:** 2026-06-18 (this document)  
**Status:** Accepted  

**Decision:** HS256 JWT with 64-byte secret from macOS Keychain, not RS256.

**Research basis (Research 07):**
- RS256 (asymmetric) is needed when multiple independent services verify tokens without sharing a secret
- SPA has exactly one FastAPI instance on one Mac Mini
- HS256 with a strong secret is equally secure and simpler
- Secret stored in macOS Keychain via `security find-generic-password`; never in files

---

### ADR-009: No Governance Token at Launch

**Date:** 2026-06-18 (this document)  
**Status:** Accepted  

**Decision:** No governance token issuance until $50M+ AUM, 2+ year track record, and regulatory clarity (MiCA + US).

**Research basis (Research 10):**
- Pre-maturity tokens add securities law risk (MiCA, US securities laws)
- Institutional investors want USDC yield, not governance tokens
- DAO governance format requires legal structure not yet established
- Market cap of governance token requires liquidity SPA cannot provide at current scale

**Deferred to:** 2028+ (Phase 4), subject to conditions above.

---

### ADR-010: Cloudflare Tunnel — No Direct Port Exposure

**Date:** Project inception  
**Status:** Accepted, governing  

**Decision:** All inbound internet traffic routes through Cloudflare Tunnel (`cloudflared`). No ports are forwarded, no dynamic DNS, no direct exposure of Mac Mini IP.

**Rationale:**
- Eliminates attack surface of open ports
- Cloudflare provides TLS termination, DDoS protection, WAF
- `cloudflared` establishes outbound-only persistent connection to Cloudflare edge
- In case of ISP outage: cloudflared automatically reconnects after 4G failover

---

### ADR-011: GitHub-Hosted Runners Only (No Self-Hosted on Production)

**Date:** 2026-06-18 (this document)  
**Status:** Accepted, security-critical  

**Decision:** All GitHub Actions CI jobs run on GitHub-hosted runners (`ubuntu-latest`). The production Mac Mini is NEVER used as a GitHub Actions self-hosted runner.

**Research basis (Research 02):**
- Shai-Hulud worm (November 2025) specifically targeted self-hosted GitHub Actions runners as C2
- A compromised runner on the same machine as macOS Keychain = full credential exfiltration
- GitHub-hosted runners are ephemeral, isolated, and do not persist between jobs

---

### ADR-012: Pure Sine Wave UPS Required

**Date:** 2026-06-18 (this document)  
**Status:** Accepted, hardware requirement  

**Decision:** Mac Mini M4 requires a pure sine wave (not simulated/stepped) UPS.

**Research basis (Research 09):**
- Mac Mini M4 uses Active PFC (Power Factor Correction) power supply
- Simulated/stepped sine wave UPS output causes: audible PSU noise, overheating, PSU shutdown on battery transfer
- CyberPower CP850PFCLCD ($110): 850VA/510W, pure sine wave, USB integration with CyberPower PowerPanel for macOS (automatic safe shutdown)

---

### ADR-013: OZ ERC4626 with _decimalsOffset=6

**Date:** 2026-06-18 (this document)  
**Status:** Accepted for smart contract vault (Q4 2026 development)  

**Decision:** Use OpenZeppelin's ERC4626 implementation with `_decimalsOffset = 6` as the inflation attack defense.

**Research basis (Research 08):**
- Venus protocol on ZKsync (February 2025): inflation attack exploit, ~86 WETH loss
- decimalsOffset=6 makes inflation attack 1,000,000× more expensive
- Attacker would need to donate $100M+ to steal $100 from the next legitimate depositor
- OZ implementation with this offset is the recommended production approach as of OpenZeppelin documentation 2025

---

### ADR-014: Gnosis Safe 2/3 with Multi-Vendor Hardware Wallets

**Date:** 2026-06-18 (this document)  
**Status:** Accepted for smart contract vault (Q4 2026)  

**Decision:** Three-owner Safe (threshold=2) with Ledger + Trezor + Coldcard Q. Explicitly different hardware manufacturers for all three owners.

**Research basis (Research 12):**
- Single-vendor risk: if one manufacturer releases compromised firmware, all devices from that vendor are simultaneously vulnerable
- Ledger + Trezor = two largest vendors with different codebases and security models
- Coldcard Q: air-gapped, QR-based signing (no USB connection), maximum security for third key stored off-site

---

### ADR-015: No Zodiac Delay Modifier (Exploited May 2026)

**Date:** 2026-06-18 (this document)  
**Status:** Accepted, security-critical  

**Decision:** The Zodiac Delay Modifier is NOT used in SPA's smart contract architecture. Use OZ TimelockController instead for time-delayed critical operations.

**Research basis (Research 12):**
- May 2026: Zodiac Delay Modifier exploit at Gnosis Pay allowed attackers to initiate unauthorized transactions from affected Safe wallets
- Separately: SquidRouterModule exploit (May 2026) cost ~$3.2M from Safe users via trusted module abuse
- OZ TimelockController: well-audited (used by Compound, Uniswap, Aave), no known exploits
- Zodiac Roles Modifier: separate contract from Delay Modifier, not affected by the May 2026 exploit

---

### ADR-016: Decimal over Float for All Financial Amounts

**Date:** 2026-06-18 (this document)  
**Status:** Accepted  

**Decision:** All financial amounts (USD values, APY percentages, fee calculations) use Python `Decimal` type, not `float`.

**Rationale:** `0.1 + 0.2 != 0.3` in IEEE 754 floating point. For financial calculations, rounding errors accumulate and can cause investor reporting discrepancies. `Decimal` provides exact decimal arithmetic.

```python
# Correct (Pydantic v2 model)
allocation_usd: Decimal = Field(..., ge=Decimal("0"), le=Decimal("10_000_000"))
apy_pct: Decimal = Field(..., ge=Decimal("0"), le=Decimal("100"))

# Wrong — never use float for money
allocation_usd: float  # ❌
```

---

### ADR-017: RiskPolicy Version Frozen at v1.0 During Paper Period

**Date:** From CLAUDE.md  
**Status:** Accepted, immutable during paper trading  

**Decision:** `RiskPolicy.version` remains `"v1.0"` for the entire paper trading period. Any change to risk parameters requires a new ADR and a snapshot in `spa_core/risk/versions/`.

**Key RiskPolicy v1.0 limits:**

| Parameter | Value |
|---|---|
| TVL floor | ≥$5M per pool |
| Per-protocol cap (T1) | 40% |
| Per-protocol cap (T2) | 20% |
| T2 total cap | ≤50% |
| APY range for new position | 1% – 30% |
| Minimum cash buffer | ≥5% |
| Kill switch | Portfolio drawdown ≥5% → close all |

---

### ADR-018: Sky/sUSDS at 0% Until On-Chain GSM Pause Delay ≥48h

**Date:** From CLAUDE.md  
**Status:** Accepted  

**Decision:** Sky/sUSDS allocation remains 0% until on-chain confirmation of GSM (Governance Security Module) Pause Delay ≥48 hours.

**Monitor:** `spa_core/data_pipeline/sky_monitor.py`

---

*Document maintained by: SPA Senior Architect*  
*Last updated: 2026-06-18*  
*Version: v2.0*  
*Next review: at Phase 2 launch (Q4 2026) or any major infrastructure change*  
*Change history: v1.0 (Russian, Sprint v1.6) → v2.0 (English, synthesized from 12 research reports)*
