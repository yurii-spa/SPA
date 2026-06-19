# Monitoring & Alerting

## What is Monitored

### Application Layer
| Monitor | Method | Alert | Threshold |
|---|---|---|---|
| Paper APY | Daily cycle check | Telegram | Outside [2%, 40%] bounds |
| Drawdown | Daily cycle check | Kill switch + Telegram | -5% monthly |
| Risk gate blocks | Per-rebalance check | Telegram | Any blocked rebalance |
| GoLiveChecker | Daily run | Telegram | Any criterion regression |
| API health | Launchd keepalive | Auto-restart | Process crash |

### Infrastructure Layer
| Monitor | Method | Alert |
|---|---|---|
| Site uptime | Cloudflare Analytics | CF dashboard |
| Build failures | CF Pages | Email notification |
| API errors | Log file (familyfund_api.log) | Manual review |

## Alert Channels
- Telegram bot: TELEGRAM_BOT_TOKEN_SPA (stored in Keychain)
- Chat ID: TELEGRAM_CHAT_ID_SPA (stored in Keychain)
- Messages sent by: spa_core/alerts/ modules

## Data Freshness
- Paper metrics: updated daily (00:00 UTC cycle)
- Dashboard: loads from JSON files, staleness shown if >25h since last update
- Protocol status: updated per cycle
