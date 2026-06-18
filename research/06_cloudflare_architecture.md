# Cloudflare Pages + Tunnel: Оптимальная архитектура для Fullstack App

> **Контекст:** Mac Mini за NAT, Python API (stdlib), домен `earn-defi.com` на Cloudflare, cloudflared настроен.  
> **Дата исследования:** 2026-06-18 | Источники: официальная документация Cloudflare (апр–май 2026), DeepWiki, FastAPI docs.

---

## Содержание

1. [Общая архитектура](#1-общая-архитектура)
2. [Cloudflare Pages: custom domain, preview, cache](#2-cloudflare-pages-custom-domain-preview-cache)
3. [Cloudflare Tunnel: multi-subdomain config.yml](#3-cloudflare-tunnel-multi-subdomain-configyml)
4. [API Security: WAF и защита без платного плана](#4-api-security-waf-и-защита-без-платного-плана)
5. [CORS: Pages (static) ↔ Tunnel (API)](#5-cors-pages-static--tunnel-api)
6. [WebSocket через CF Tunnel](#6-websocket-через-cf-tunnel)
7. [Cache Strategy: финансовые данные](#7-cache-strategy-финансовые-данные)
8. [Rate Limiting: бесплатный план](#8-rate-limiting-бесплатный-план)
9. [SSL/TLS: end-to-end шифрование](#9-ssltls-end-to-end-шифрование)
10. [Health Check: мониторинг tunnel](#10-health-check-мониторинг-tunnel)
11. [Итоговая конфигурация для SPA / earn-defi.com](#11-итоговая-конфигурация-для-spa--earn-deficom)
12. [Источники](#12-источники)

---

## 1. Общая архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLOUDFLARE EDGE                          │
│                                                                 │
│  earn-defi.com (Pages)          api.earn-defi.com (Tunnel)      │
│  dashboard.earn-defi.com (Tunnel)   staging.earn-defi.com       │
│                                                                 │
│  WAF → Cache → Rate Limit → Tunnel → Origin                     │
└──────────────────────┬──────────────────────────────────────────┘
                       │  QUIC / HTTP/2 (cloudflared)
                       │  (исходящее соединение, NAT не нужен)
┌──────────────────────▼──────────────────────────────────────────┐
│                    MAC MINI (за NAT)                            │
│                                                                 │
│  cloudflared daemon (launchd com.spa.cloudflared)               │
│                                                                 │
│  localhost:8765  ← Python API (spa_core/family_fund/http_server)│
│  localhost:3000  ← Next.js / Astro dashboard (опционально)      │
│  localhost:4000  ← staging (опционально)                        │
└─────────────────────────────────────────────────────────────────┘
```

**Ключевые свойства этой архитектуры:**
- cloudflared устанавливает исходящие соединения → NAT-пробой не нужен, порты не открываются
- Один процесс cloudflared обслуживает все subdomains
- Все CNAME в DNS указывают на один и тот же `<UUID>.cfargotunnel.com`
- CF Edge терминирует TLS от клиента; cloudflared устанавливает защищённый туннель к Cloudflare
- CF Pages — отдельный продукт, деплоится через Git, не через Tunnel

---

## 2. Cloudflare Pages: custom domain, preview, cache

### 2.1 Подключение custom domain

**Для apex домена** (`earn-defi.com`) — домен должен быть в зоне Cloudflare (NS делегированы):

```
Workers & Pages → проект → Custom domains → "Set up a domain"
→ введи earn-defi.com → Continue
→ Cloudflare создаёт CNAME автоматически
```

**Для subdomains** (`www.earn-defi.com`):

```
DNS > Records > Add record
  Type:   CNAME
  Name:   www
  Target: your-project.pages.dev
  Proxy:  Enabled (orange cloud) ← обязательно!
```

> ⚠️ Нельзя добавить bare CNAME без привязки в Pages dashboard — получишь 522 ошибку.

**CAA-записи** (если уже есть — добавь разрешения для Cloudflare):

```dns
earn-defi.com.  CAA  0 issue "letsencrypt.org"
earn-defi.com.  CAA  0 issue "pki.goog; cansignhttpexchanges=yes"
earn-defi.com.  CAA  0 issue "ssl.com"
earn-defi.com.  CAA  0 issuewild "letsencrypt.org"
earn-defi.com.  CAA  0 issuewild "pki.goog; cansignhttpexchanges=yes"
earn-defi.com.  CAA  0 issuewild "ssl.com"
```

### 2.2 Preview deployments

| URL | Назначение |
|---|---|
| `your-project.pages.dev` | Production (main ветка) |
| `<hash>.your-project.pages.dev` | Конкретный коммит (permanent, immutable) |
| `staging.your-project.pages.dev` | Ветка `staging` (всегда последний коммит) |

- Все preview URL автоматически получают `X-Robots-Tag: noindex` — не индексируются
- Для кастомного алиаса staging: добавь `staging.earn-defi.com` как custom domain и измени CNAME target на `staging.your-project.pages.dev`
- Для закрытия preview от внешнего доступа: Settings → General → "Enable access policy" (Cloudflare Access)

### 2.3 `_headers` файл: Cache-Control

Размещай в директории `public/` (Next.js) или в корне `dist/` (Astro):

```
# public/_headers

# Хэшированные JS/CSS ассеты — кешировать год (immutable)
/_next/static/*
  Cache-Control: public, max-age=31536000, immutable

# Astro hashed assets
/_astro/*
  Cache-Control: public, max-age=31536000, immutable

# Изображения — 1 сутки
/images/*
  Cache-Control: public, max-age=86400

# HTML страницы — всегда revalidate
/*.html
  Cache-Control: public, max-age=0, must-revalidate

# Security headers для всего сайта
/*
  X-Frame-Options: DENY
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: document-domain=()

# Запретить индексацию preview URL
https://:project.pages.dev/*
  X-Robots-Tag: noindex

https://:version.:project.pages.dev/*
  X-Robots-Tag: noindex
```

> ⚠️ **Критическое ограничение:** `_headers` применяется ТОЛЬКО к статическим ассетам.  
> Если используешь Pages Functions (SSR), заголовки нужно выставлять программно внутри функции.  
> `_headers` НЕ переопределяет заголовки ответов Pages Functions.

**Дефолтный Cache-Control от CF Pages** (если не переопределён):
```
Cache-Control: public, max-age=0, must-revalidate
```
Браузер всегда revalidate через ETag/304.

---

## 3. Cloudflare Tunnel: multi-subdomain config.yml

### 3.1 Создание tunnel и DNS

```bash
# Шаг 1: Авторизация
cloudflared tunnel login
# Создаёт ~/.cloudflared/cert.pem

# Шаг 2: Создать named tunnel
cloudflared tunnel create spa-tunnel
# Выводит UUID: 6ff42ae2-765d-4adf-8112-31c55c1551ef
# Создаёт ~/.cloudflared/6ff42ae2-765d-4adf-8112-31c55c1551ef.json

# Шаг 3: Создать DNS CNAME для каждого subdomain
cloudflared tunnel route dns spa-tunnel earn-defi.com
cloudflared tunnel route dns spa-tunnel api.earn-defi.com
cloudflared tunnel route dns spa-tunnel dashboard.earn-defi.com
cloudflared tunnel route dns spa-tunnel staging.earn-defi.com

# Все CNAME указывают на один tunnel UUID
# Если cloudflare zone — можно из dashboard:
# Type: CNAME | Name: api | Target: 6ff42ae2-....cfargotunnel.com | Proxy: ON
```

### 3.2 Основной `~/.cloudflared/config.yml`

```yaml
# ~/.cloudflared/config.yml
tunnel: 6ff42ae2-765d-4adf-8112-31c55c1551ef
credentials-file: /Users/username/.cloudflared/6ff42ae2-765d-4adf-8112-31c55c1551ef.json

# Глобальные настройки origin (переопределяются per-rule)
originRequest:
  connectTimeout: 30s
  tcpKeepAlive: 30s
  keepAliveConnections: 100
  keepAliveTimeout: 90s

ingress:
  # ── Landing page (если не используешь CF Pages для него) ──
  - hostname: earn-defi.com
    service: http://localhost:3000

  # ── Python API backend ──
  - hostname: api.earn-defi.com
    service: http://localhost:8765
    originRequest:
      connectTimeout: 30s

  # ── Dashboard (Next.js/Astro dev server или static) ──
  - hostname: dashboard.earn-defi.com
    service: http://localhost:3001

  # ── Staging environment ──
  - hostname: staging.earn-defi.com
    service: http://localhost:4000
    originRequest:
      connectTimeout: 10s
      disableChunkedEncoding: true

  # ── ОБЯЗАТЕЛЬНЫЙ catch-all (последним!) ──
  - service: http_status:404
```

### 3.3 Конфигурация с HTTPS к origin и path routing

```yaml
tunnel: 6ff42ae2-765d-4adf-8112-31c55c1551ef
credentials-file: /Users/username/.cloudflared/6ff42ae2-765d-4adf-8112-31c55c1551ef.json

originRequest:
  connectTimeout: 30s

ingress:
  # API: только /api/* пути
  - hostname: earn-defi.com
    path: ^/api/
    service: http://localhost:8765

  # Статика: только ассеты
  - hostname: earn-defi.com
    path: \.(js|css|png|jpg|svg|ico|woff2)$
    service: http://localhost:3000

  # Остальное — dashboard
  - hostname: earn-defi.com
    service: http://localhost:3000

  # Выделенный API subdomain
  - hostname: api.earn-defi.com
    service: http://localhost:8765
    originRequest:
      httpHostHeader: "api.earn-defi.com"  # передаёт правильный Host header

  # Staging
  - hostname: staging.earn-defi.com
    service: http://localhost:4000

  - service: http_status:404
```

### 3.4 Валидация и запуск

```bash
# Проверить синтаксис и catch-all
cloudflared tunnel ingress validate

# Dry-run: какой rule сработает для URL
cloudflared tunnel ingress rule https://api.earn-defi.com
# Output: Matched rule #2 — hostname: api.earn-defi.com — service: http://localhost:8765

# Запуск (foreground, для теста)
cloudflared tunnel --config ~/.cloudflared/config.yml run

# Запуск по имени
cloudflared tunnel run spa-tunnel
```

### 3.5 launchd plist (macOS, production)

```bash
# Установить как system daemon
sudo cloudflared service install
# Создаёт /Library/LaunchDaemons/com.cloudflare.cloudflared.plist

sudo launchctl start com.cloudflare.cloudflared
sudo launchctl stop  com.cloudflare.cloudflared
```

Plist (`/Library/LaunchDaemons/com.cloudflare.cloudflared.plist`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.cloudflare.cloudflared</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/cloudflared</string>
    <string>tunnel</string>
    <string>--config</string>
    <string>/Users/username/.cloudflared/config.yml</string>
    <string>--metrics</string>
    <string>127.0.0.1:20241</string>
    <string>run</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/cloudflared.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/cloudflared_err.log</string>
</dict>
</plist>
```

> ⚠️ Если `tunnel run` не запускается через plist — явно добавь `tunnel` и `run` как отдельные строки в `ProgramArguments` (известный баг).

---

## 4. API Security: WAF и защита без платного плана

### 4.1 Что доступно на Free плане (официальные данные, апр 2026)

| Инструмент | Free | Детали |
|---|---|---|
| Custom WAF rules | **5 правил** | Без regex; действия: Block, Challenge, Managed Challenge, JS Challenge, Skip |
| Rate limiting rules | **1 правило** | 10 сек окно, только по IP |
| Free Managed Ruleset | ✅ Да | Авто-включён; покрывает Shellshock, Log4Shell и т.д. |
| Full Cloudflare Managed Ruleset | ❌ Pro+ | OWASP Core — тоже Pro+ |
| IP Access Rules | ✅ Да | По IP, диапазону, ASN, стране — **не считается в лимит 5 правил** |
| Zone Lockdown | ✅ Да | Ограничить URL по IP — **не считается в лимит** |
| User Agent Blocking | ✅ Да | Отдельный инструмент |
| DDoS L7 protection | ✅ Да | Unlimited, автоматически |
| Bot Fight Mode (базовый) | ✅ Да | Super Bot Fight Mode — Pro+ |
| Regex в выражениях | ❌ Business+ | На free/pro — нет |

### 4.2 Рекомендованные 5 custom WAF rules для API

**Dashboard:** Security → WAF → Custom rules → Create rule

**Rule 1 — Whitelist (приоритет 1, действие: Skip/Allow)**
```
Expression: (cf.client.bot) or (ip.src in {1.2.3.4 5.6.7.8})
Action: Skip → All remaining custom rules
```
Разрешает verified bots (Google, Bing) и твои IP. Должно быть первым.

**Rule 2 — Block datacenter/scanner ASNs (действие: Managed Challenge)**
```
Expression: (ip.geoip.asnum in {13335 15169 16509 14618 45090})
Action: Managed Challenge
```
Cloudflare (13335), Google (15169), AWS (16509), Amazon (14618), Tencent (45090). Большинство сканеров работают с VPS в этих ASN.

**Rule 3 — Block по threat score (действие: Block)**
```
Expression: (cf.threat_score gt 10)
Action: Block
```
Score 0–100 от Cloudflare. >10 = средний-высокий риск. Начни с 30, постепенно снижай до 10.

**Rule 4 — Block malicious User-Agents (действие: Block)**
```
Expression:
  (http.user_agent eq "") or
  (http.user_agent contains "sqlmap") or
  (http.user_agent contains "nikto") or
  (http.user_agent contains "masscan") or
  (http.user_agent contains "python-requests") or
  (http.user_agent contains "Go-http-client")
Action: Block
```

**Rule 5 — Protect sensitive paths (действие: Block)**
```
Expression:
  (http.request.uri.path contains "/.env") or
  (http.request.uri.path contains "/.git") or
  (http.request.uri.path contains "/wp-login") or
  (http.request.uri.path contains "/phpMyAdmin") or
  (http.request.uri.path contains "/admin") and
  not (ip.src in {YOUR_IP_HERE})
Action: Block
```

### 4.3 IP Access Rules (вне лимита 5 правил)

```
Security → WAF → Tools → IP Access Rules

# Блокировать по стране (пример):
Action: Block
Value:  RU   (Country)

# Блокировать конкретный ASN:
Action: Challenge
Value:  AS12345

# Whitelist своего провайдера:
Action: Allow
Value:  YOUR_IP/24
```

### 4.4 Защита origin от прямых обращений (bypass Cloudflare)

Самое важное: **закрой порты 80/443 на Mac Mini от всех IP, кроме Cloudflare**.

```bash
# macOS pf firewall (добавить в /etc/pf.conf)
# Скачай актуальные IP Cloudflare:
# https://www.cloudflare.com/ips-v4
# https://www.cloudflare.com/ips-v6

table <cloudflare> { 103.21.244.0/22, 103.22.200.0/22, ... }
block in on em0 proto tcp to port { 80 443 }
pass  in on em0 proto tcp from <cloudflare> to port { 80 443 }
```

Без этого WAF правила бесполезны — attacker может обратиться к origin IP напрямую.

---

## 5. CORS: Pages (static) ↔ Tunnel (API)

### 5.1 Архитектура CORS

```
Browser
  ├── GET https://earn-defi.com/            ← CF Pages (статика)
  └── fetch("https://api.earn-defi.com/...")  ← CF Tunnel (API)
                 ↑
         Разные origins → браузер требует CORS headers
```

### 5.2 Метод A: CORS в Python backend (РЕКОМЕНДОВАН)

**Для `spa_core/family_fund/http_server.py` (stdlib `http.server`):**

```python
from http.server import HTTPServer, BaseHTTPRequestHandler
import json

ALLOWED_ORIGINS = {
    "https://earn-defi.com",
    "https://www.earn-defi.com",
    "https://dashboard.earn-defi.com",
    # Preview URLs — добавляй по необходимости:
    "https://staging.your-project.pages.dev",
}

class SPAHandler(BaseHTTPRequestHandler):

    def _add_cors_headers(self):
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")  # важно для кеша!
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "86400")

    def do_OPTIONS(self):
        """Preflight request handler"""
        self.send_response(204)
        self._add_cors_headers()
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok"}).encode())
```

**Для FastAPI:**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://earn-defi.com",
        "https://www.earn-defi.com",
        "https://dashboard.earn-defi.com",
    ],
    allow_credentials=True,   # НЕ совместим с allow_origins=["*"] !
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    max_age=600,
)
```

> ⚠️ **Критическое правило:** `allow_origins=["*"]` + `allow_credentials=True` = браузер ОТКЛОНИТ ответ.  
> При использовании credentials — всегда перечисляй конкретные origins.

### 5.3 Метод B: `_headers` (только для static Pages)

Если нет Pages Functions — можно добавить в `public/_headers`:

```
# public/_headers (CF Pages static)

# Только для статических ресурсов, НЕ для API проксирования
/fonts/*
  Access-Control-Allow-Origin: *

/images/*
  Access-Control-Allow-Origin: *
```

> ⚠️ **НЕ используй** `_headers` для CORS к API — он работает только для статических ассетов,  
> а не для ответов твоего Python backend через Tunnel.

### 5.4 Anti-pattern: двойные CORS заголовки

Не выставляй CORS заголовки в двух местах одновременно (Python + CF Transform Rules).  
Дублированный `Access-Control-Allow-Origin` браузер отклонит с ошибкой "multiple values".

---

## 6. WebSocket через CF Tunnel

### 6.1 Поддержка WebSocket

**ДА, работает.** WebSocket поддерживается на всех планах (Free, Pro, Business, Enterprise).  
Confirmed: официальная документация Cloudflare Network (апр 2026).

### 6.2 Предварительные требования

**1. Включить WebSocket в Dashboard:**
```
dash.cloudflare.com → earn-defi.com → Network → WebSockets → ON
```

Или через API:
```bash
curl "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/settings/websockets" \
  --request PATCH \
  --header "Authorization: Bearer $TOKEN" \
  --json '{"value": "on"}'
```

**2. cloudflared config.yml:**

```yaml
ingress:
  - hostname: api.earn-defi.com
    service: ws://localhost:8765   # или http:// — оба работают для WebSocket
    originRequest:
      httpHostHeader: "api.earn-defi.com"
  - service: http_status:404
```

### 6.3 Python WebSocket server (stdlib)

```python
# Требует: pip install websockets (или используй asyncio + встроенный протокол)
import asyncio
import websockets
import json

ALLOWED_ORIGINS = {"https://earn-defi.com", "https://dashboard.earn-defi.com"}

async def handler(websocket):
    # Валидация Origin (браузер отправляет автоматически)
    origin = websocket.request_headers.get("Origin", "")
    if origin not in ALLOWED_ORIGINS:
        await websocket.close(1008, "Origin not allowed")
        return

    try:
        async for message in websocket:
            data = json.loads(message)
            if data.get("type") == "ping":
                await websocket.send(json.dumps({"type": "pong"}))
            else:
                # обработка сообщений
                response = {"type": "data", "payload": get_equity_data()}
                await websocket.send(json.dumps(response))
    except websockets.exceptions.ConnectionClosed:
        pass

async def main():
    async with websockets.serve(handler, "localhost", 8766):
        await asyncio.Future()  # run forever

asyncio.run(main())
```

### 6.4 Heartbeat (обязательно на Free плане)

Cloudflare закрывает WebSocket соединение при idle > **100 секунд** (Free план, не конфигурируется).

**Клиентский heartbeat (JavaScript):**

```javascript
// frontend/dashboard.js
const ws = new WebSocket("wss://api.earn-defi.com/ws");

let pingInterval;

ws.onopen = () => {
    console.log("WS connected");
    // Пинг каждые 30 секунд — хорошо в пределах 100s timeout
    pingInterval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "ping" }));
        }
    }, 30_000);
};

ws.onclose = () => {
    clearInterval(pingInterval);
    // Автореконнект с exponential backoff
    setTimeout(() => reconnect(), 3000);
};

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type !== "pong") {
        updateDashboard(data);
    }
};
```

### 6.5 Ограничения WebSocket через CF Tunnel

| Функция | Совместимость с WS |
|---|---|
| SSL/TLS | ✅ Да |
| WAF | ✅ Да (только HTTP 101 upgrade; пост-upgrade сообщения не инспектируются) |
| DDoS protection | ✅ Да |
| Argo Smart Routing | ❌ **Несовместимо** с WebSocket |
| Load Balancer Session affinity | ⚠️ Требуется при нескольких origin instances |
| Idle timeout (Free) | ⏱ 100 секунд (не конфигурируется) |

---

## 7. Cache Strategy: финансовые данные

### 7.1 Принцип: API данные НЕ кешировать

Для real-time финансовых данных (APY, equity curve, позиции) — **bypass cache**.  
Stale данные в DeFi-контексте недопустимы.

### 7.2 Cache Rules через Dashboard

```
Cloudflare Dashboard → Caching → Cache Rules → Create rule

# Правило 1: Bypass для API endpoints
Name: "Bypass cache for API"
When: (http.host eq "api.earn-defi.com") or
      (http.request.uri.path contains "/api/") or
      (http.request.uri.path contains "/data/")
Then: Bypass cache
```

### 7.3 Cache Rules через API (Ruleset Engine JSON)

```json
{
  "rules": [
    {
      "description": "Bypass cache: financial API endpoints",
      "expression": "(http.host eq \"api.earn-defi.com\")",
      "action": "set_cache_settings",
      "action_parameters": {
        "cache": false
      }
    },
    {
      "description": "Bypass cache: real-time data paths",
      "expression": "(http.request.uri.path contains \"/api/\") or (http.request.uri.path contains \"/ws\")",
      "action": "set_cache_settings",
      "action_parameters": {
        "cache": false
      }
    },
    {
      "description": "Cache static assets aggressively",
      "expression": "(http.request.uri.path contains \"/static/\") or (http.request.uri.path matches \"\\.(js|css|png|jpg|svg|ico|woff2)$\")",
      "action": "set_cache_settings",
      "action_parameters": {
        "cache": true,
        "edge_ttl": {
          "mode": "override_origin",
          "default": 2592000
        },
        "browser_ttl": {
          "mode": "override_origin",
          "default": 31536000
        }
      }
    }
  ]
}
```

### 7.4 Python backend: правильные Cache-Control заголовки

```python
class SPAHandler(BaseHTTPRequestHandler):

    def _send_api_response(self, data: dict, status: int = 200):
        """API endpoint — никогда не кешировать"""
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # Запрет кеша на всех уровнях:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(body)
```

### 7.5 Что кешировать vs что нет

| Данные | Cache strategy | Причина |
|---|---|---|
| `data/equity_curve_daily.json` | **no-store** | Реальный трек, меняется ежедневно |
| `data/current_positions.json` | **no-store** | Актуальные позиции |
| `data/golive_status.json` | **no-store** | Критические 26 чеков |
| `data/paper_trading_status.json` | **no-store** | Живой статус |
| `/api/*` endpoints | **no-store** | Все API — no cache |
| HTML страницы dashboard | max-age=0, must-revalidate | Быстро проверить обновления |
| JS/CSS с хешем в имени | max-age=31536000, immutable | Хеш гарантирует уникальность |
| Шрифты, иконки | max-age=86400 | Меняются редко |

---

## 8. Rate Limiting: бесплатный план

### 8.1 Ограничения Free плана (официальные данные, апр 2026)

| Параметр | Free | Pro | Business |
|---|---|---|---|
| Кол-во правил | **1** | 2 | 5 |
| Характеристики подсчёта | **IP only** | IP only | IP + NAT, custom |
| Период подсчёта | **10 сек** (только) | до 1 мин | до 10 мин |
| Mitigation timeout | **10 сек** | до 1 ч | до 1 дня |
| Regex в выражении | ❌ | ❌ | ✅ |

### 8.2 Единственное rate limiting правило — расставь правильно

На бесплатном плане **одно правило** — трать его на самый критичный endpoint.  
Для DeFi-платформы с авторизацией — это endpoint логина/аутентификации.

```
Security → WAF → Rate limiting rules → Create rule

Name: "Rate limit: auth endpoint"
Expression: (http.request.uri.path eq "/api/auth/login") or
            (http.request.uri.path eq "/api/auth/token")
Counting characteristic: IP Address
Period: 10 seconds
Requests per period: 5
Mitigation timeout: 10 seconds
Action: Managed Challenge
```

> Начни с `Managed Challenge`, а не `Block` — мониторь Challenge Solve Rate (CSR) в Security Events.  
> Если CSR ≈ 0% (почти никто не решает challenge) — переключай на Block.

### 8.3 Компенсация лимита через IP Access Rules

IP Access Rules не входят в лимит rate limiting. Используй их для блокировки по стране/ASN:

```
Security → WAF → Tools → IP Access Rules
Action: Block | Value: CN (Country)
Action: Block | Value: AS15169 (ASN — Google Cloud)
```

### 8.4 Application-level rate limiting (Python backend)

Дополни серверным rate limiting — защитит даже при обходе Cloudflare:

```python
import time
from collections import defaultdict
from threading import Lock

class RateLimiter:
    """Simple in-memory rate limiter (stdlib only)"""
    
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._store: dict = defaultdict(list)
        self._lock = Lock()

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            # Очистить старые записи
            self._store[key] = [
                ts for ts in self._store[key]
                if now - ts < self.window
            ]
            if len(self._store[key]) >= self.max_requests:
                return False
            self._store[key].append(now)
            return True

# Использование в handler:
rate_limiter = RateLimiter(max_requests=30, window_seconds=60)

def do_GET(self):
    client_ip = self.headers.get("CF-Connecting-IP") or self.client_address[0]
    if not rate_limiter.is_allowed(client_ip):
        self.send_response(429)
        self.send_header("Retry-After", "60")
        self.end_headers()
        return
    # ... обработка запроса
```

> `CF-Connecting-IP` — реальный IP клиента, который Cloudflare проставляет в header.  
> Без него (если смотреть `client_address`) увидишь Cloudflare Edge IP, а не клиента.

---

## 9. SSL/TLS: end-to-end шифрование

### 9.1 Схема шифрования

```
Browser ──[TLS 1.3]──► Cloudflare Edge ──[TLS inside tunnel]──► cloudflared ──[HTTP]──► Python API
              ↑                                    ↑
         Публичный сертификат              Cloudflare Origin CA cert
         (автоматически CF)                  (или Let's Encrypt)
```

### 9.2 SSL/TLS режим: Full (strict) — рекомендован

```
dash.cloudflare.com → earn-defi.com → SSL/TLS → Overview
→ Full (strict)
```

| Режим | Visitor→CF | CF→Origin | Валидация cert |
|---|---|---|---|
| Off | HTTP | HTTP | Нет |
| Flexible | HTTPS | HTTP | Нет |
| Full | HTTPS | HTTPS | Нет |
| **Full (strict)** | **HTTPS** | **HTTPS** | **Да (проверяет cert)** |

Или через API:
```bash
curl "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/settings/ssl" \
  --request PATCH \
  --header "Authorization: Bearer $TOKEN" \
  --json '{"value": "strict"}'
```

### 9.3 cloudflared TLS originRequest параметры

```yaml
# config.yml с Full (strict) SSL настройками

tunnel: 6ff42ae2-765d-4adf-8112-31c55c1551ef
credentials-file: /Users/username/.cloudflared/6ff42ae2-765d-4adf-8112-31c55c1551ef.json

ingress:
  - hostname: api.earn-defi.com
    # Если origin использует HTTPS (например, с Let's Encrypt или CF Origin CA):
    service: https://localhost:8765
    originRequest:
      originServerName: api.earn-defi.com  # SNI для TLS handshake к origin
      tlsTimeout: 10s
      # caPool: /path/to/origin-ca.pem   # если используешь Cloudflare Origin CA
      noTLSVerify: false                  # НЕ отключай верификацию в production
      http2Origin: true                   # HTTP/2 к origin (быстрее)

  # Если origin HTTP (рекомендую для localhost — туннель сам шифрует):
  - hostname: dashboard.earn-defi.com
    service: http://localhost:3000        # Допустимо: туннель между cloudflared и CF Edge зашифрован
    originRequest:
      connectTimeout: 30s

  - service: http_status:404
```

> **Практически для Mac Mini за NAT:** `http://localhost:PORT` в service — это нормально.  
> Соединение **cloudflared → Cloudflare Edge** всегда зашифровано (QUIC/HTTP2 с TLS).  
> Только если хочешь Full (strict) — нужен TLS cert на самом Python сервере.

### 9.4 Cloudflare Origin CA (опционально, для Full strict без Let's Encrypt)

```
dash.cloudflare.com → earn-defi.com → SSL/TLS → Origin Server → Create Certificate
→ выбери key type (RSA/ECDSA), validity (до 15 лет)
→ скачай: origin.pem (cert) + origin.key (private key)
→ установи в Python HTTP сервер или nginx
```

Origin CA сертификаты доверяет только Cloudflare — не подходят для прямого обращения к origin.

---

## 10. Health Check: мониторинг tunnel

### 10.1 Статусы tunnel

| Статус | Значение | Действие |
|---|---|---|
| Healthy | 4 активных соединения к CF network | — |
| Inactive | Tunnel создан, но cloudflared не запущен | Запусти cloudflared |
| Down | Был подключён, сейчас disconnected | Рестарт cloudflared |
| Degraded | Запущен, но ≥1 из 4 соединений упало | Проверь логи и firewall |

```bash
# Проверить статус
cloudflared tunnel list
cloudflared tunnel info spa-tunnel

# Логи (если запущен через launchd):
tail -f /tmp/cloudflared.log
tail -f /tmp/cloudflared_err.log
```

### 10.2 Prometheus метрики (встроенные)

cloudflared автоматически поднимает Prometheus-сервер на `127.0.0.1:20241/metrics`:

```bash
# Найди порт в логах:
grep "Starting metrics server" /tmp/cloudflared.log
# INF Starting metrics server on 127.0.0.1:20241/metrics

# Или запусти с явным портом (в plist ProgramArguments):
# "--metrics", "127.0.0.1:20241"

# Проверить доступность:
curl http://localhost:20241/metrics
curl http://localhost:20241/ready   # health check endpoint
```

**Ключевые метрики:**

| Метрика | Тип | Значение |
|---|---|---|
| `cloudflared_tunnel_ha_connections` | GAUGE | Активных HA-соединений (healthy = 4) |
| `cloudflared_tunnel_request_errors` | COUNTER | Ошибки проксирования к origin |
| `cloudflared_tunnel_total_requests` | COUNTER | Всего запросов через tunnel |
| `cloudflared_tunnel_timer_retries` | GAUGE | Неподтверждённые heartbeats (→ проблемы) |
| `quic_client_lost_packets` | COUNTER | Потери QUIC пакетов |
| `quic_client_latest_rtt` | GAUGE | RTT до CF edge |

### 10.3 Health Check скрипт для SPA

```python
#!/usr/bin/env python3
# spa_core/monitoring/tunnel_health.py
"""Проверяет статус cloudflared tunnel через Prometheus metrics endpoint"""

import urllib.request
import json
import sys

METRICS_URL = "http://127.0.0.1:20241/metrics"
READY_URL   = "http://127.0.0.1:20241/ready"

def check_tunnel_health() -> dict:
    result = {"healthy": False, "ha_connections": 0, "errors": []}
    
    try:
        # Проверить /ready endpoint
        with urllib.request.urlopen(READY_URL, timeout=5) as resp:
            result["ready"] = resp.status == 200
    except Exception as e:
        result["errors"].append(f"ready check failed: {e}")
        return result

    try:
        # Парсить метрики
        with urllib.request.urlopen(METRICS_URL, timeout=5) as resp:
            metrics_text = resp.read().decode("utf-8")
        
        for line in metrics_text.splitlines():
            if line.startswith("cloudflared_tunnel_ha_connections"):
                try:
                    result["ha_connections"] = int(float(line.split()[-1]))
                except (ValueError, IndexError):
                    pass
            elif line.startswith("cloudflared_tunnel_request_errors"):
                try:
                    result["request_errors"] = int(float(line.split()[-1]))
                except (ValueError, IndexError):
                    pass
        
        result["healthy"] = result.get("ha_connections", 0) >= 1
        
    except Exception as e:
        result["errors"].append(f"metrics check failed: {e}")
    
    return result

if __name__ == "__main__":
    health = check_tunnel_health()
    print(json.dumps(health, indent=2))
    sys.exit(0 if health["healthy"] else 1)
```

### 10.4 Интеграция в cycle_runner (добавить pre-check)

```python
# В spa_core/paper_trading/cycle_runner.py (pre-flight check)
import subprocess

def check_tunnel_available() -> bool:
    """Проверяет что cloudflared tunnel здоров перед циклом"""
    try:
        result = subprocess.run(
            ["python3", "-m", "spa_core.monitoring.tunnel_health"],
            capture_output=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False
```

### 10.5 Dashboard уведомления (CF Notifications)

```
dash.cloudflare.com → Notifications → Add notification
→ Product: Cloudflare Tunnel
→ Event type: Tunnel Health Alert
→ Notify when: tunnel transitions between Healthy/Degraded/Down
→ Delivery: Email или Webhook (Telegram bot URL)
```

---

## 11. Итоговая конфигурация для SPA / earn-defi.com

### 11.1 Финальный `~/.cloudflared/config.yml`

```yaml
# ~/.cloudflared/config.yml
# SPA — earn-defi.com Cloudflare Tunnel Configuration
# Версия: 1.0 | Дата: 2026-06-18

tunnel: YOUR-TUNNEL-UUID-HERE
credentials-file: /Users/yuriikulieshov/.cloudflared/YOUR-TUNNEL-UUID-HERE.json

# Глобальные настройки origin
originRequest:
  connectTimeout: 30s
  tcpKeepAlive: 30s
  keepAliveConnections: 100
  keepAliveTimeout: 90s

ingress:
  # ── Python API + WebSocket (SPA core) ──────────────────────────
  - hostname: api.earn-defi.com
    service: http://localhost:8765
    originRequest:
      connectTimeout: 30s
      httpHostHeader: "api.earn-defi.com"

  # ── Dashboard (статика или dev-сервер) ─────────────────────────
  - hostname: dashboard.earn-defi.com
    service: http://localhost:3001
    originRequest:
      connectTimeout: 30s

  # ── Staging environment ─────────────────────────────────────────
  - hostname: staging.earn-defi.com
    service: http://localhost:4000
    originRequest:
      connectTimeout: 10s
      disableChunkedEncoding: true

  # ── Catch-all (ОБЯЗАТЕЛЬНО последним) ──────────────────────────
  - service: http_status:404
```

### 11.2 DNS Records (Cloudflare Dashboard)

```
Тип    Имя                      Содержимое                              TTL     Proxy
────   ───────────────────────   ─────────────────────────────────────   ──────  ──────
CNAME  api                      YOUR-UUID.cfargotunnel.com              Auto    ON (☁️)
CNAME  dashboard                YOUR-UUID.cfargotunnel.com              Auto    ON (☁️)
CNAME  staging                  YOUR-UUID.cfargotunnel.com              Auto    ON (☁️)

# CF Pages — earn-defi.com (landing page)
CNAME  www                      your-project.pages.dev                  Auto    ON (☁️)
```

### 11.3 Чеклист деплоя

```
□ cloudflared tunnel создан и UUID получен
□ DNS CNAME записи для всех subdomains созданы и proxied
□ config.yml размещён в ~/.cloudflared/config.yml
□ cloudflared service install (launchd) выполнен
□ WebSockets переключатель ON в CF Dashboard → Network
□ SSL/TLS режим Full (strict) включён
□ WAF Custom Rules: 5 правил настроены
□ Rate Limiting: 1 правило на /api/auth endpoint
□ Cache Rules: bypass для api.earn-defi.com
□ CF Notifications: Tunnel Health Alert настроен
□ Метрики endpoint: curl http://localhost:20241/ready ← Healthy
□ CORS заголовки в Python backend: все allowed origins прописаны
□ Heartbeat в dashboard JS: setInterval 30s
□ Origin firewall: порты 80/443 открыты только для CF IP ranges
□ CF Pages: custom domain earn-defi.com подключён
□ Preview deployments: Access policy включена (опционально)
□ _headers файл: cache-control для статики настроен
```

---

## 12. Источники

- [Cloudflare Pages: Custom Domains](https://developers.cloudflare.com/pages/configuration/custom-domains/) — официальная документация
- [Cloudflare Pages: Headers (`_headers` file)](https://developers.cloudflare.com/pages/configuration/headers/) — официальная документация
- [Cloudflare Pages: Preview Deployments](https://developers.cloudflare.com/pages/configuration/preview-deployments/) — официальная документация
- [Cloudflare Pages: Serving Pages (default headers)](https://developers.cloudflare.com/pages/configuration/serving-pages/)
- [Cloudflare Pages: Adding CORS Headers](https://developers.cloudflare.com/pages/functions/examples/cors-headers/)
- [Cloudflare Tunnel: Configuration File](https://developers.cloudflare.com/tunnel/advanced/local-management/configuration-file/)
- [Cloudflare Tunnel: Routing](https://developers.cloudflare.com/tunnel/routing/)
- [Cloudflare Tunnel: Origin Parameters](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/origin-parameters/)
- [Cloudflare Tunnel: Monitoring](https://developers.cloudflare.com/tunnel/monitoring/)
- [Cloudflare WAF: Custom Rules](https://developers.cloudflare.com/waf/custom-rules/) — обновлено 16 апр 2026
- [Cloudflare WAF: Rate Limiting Rules](https://developers.cloudflare.com/waf/rate-limiting-rules/) — обновлено 22 апр 2026
- [Cloudflare WAF: Managed Rules](https://developers.cloudflare.com/waf/managed-rules/) — обновлено 21 апр 2026
- [Cloudflare: SSL/TLS Encryption Modes](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/)
- [Cloudflare: WebSockets (Network settings)](https://developers.cloudflare.com/network/websockets/) — обновлено 23 апр 2026
- [Cloudflare: Cache Rules](https://developers.cloudflare.com/cache/how-to/cache-rules/)
- [Cloudflare Blog: Many services, one cloudflared](https://blog.cloudflare.com/many-services-one-cloudflared/)
- [cloudflare/cloudflared DeepWiki: HTTP and WebSocket Proxying](https://deepwiki.com/cloudflare/cloudflared/5.2-http-and-websocket-proxying)
- [FastAPI: CORS Middleware](https://fastapi.tiangolo.com/tutorial/cors/)
- [Techify Blog: Persistent Cloudflare Tunnels for Multiple Ports](https://techify.blog/blog/setting-up-persistent-cloudflare-tunnels-for-multiple-ports) — окт 2025

---

*Отчёт сгенерирован: 2026-06-18 | Deep Research (5 поисковых агентов, 15+ источников, adversarial verification)*
