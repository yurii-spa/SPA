# Frontend Stack: Next.js vs Astro для Fintech Landing + Dashboard

> Исследование: 18 июня 2026  
> Источников проверено: 50+  
> Метод: fan-out поиск по 5 углам → adversarial verification → синтез

---

## TL;DR — Итоговые рекомендации

| Сценарий | Фреймворк | UI Kit | Charts | State | Auth |
|---|---|---|---|---|---|
| **A: Landing** | **Astro 4** | shadcn/ui | Recharts | TanStack Query | — (нет auth) |
| **B: Admin SPA** | **Vite + React** (или Next.js static export) | shadcn/ui | LW Charts + Recharts | TanStack Query v5 + Zustand | Custom JWT (PyJWT) |

Backend: Python FastAPI. Нет Node.js в production. Cloudflare Pages для обоих.

---

## СЦЕНАРИЙ A: Landing Page earn-defi.com

### 1. Фреймворк: **Astro 4** ✅ (Next.js — нет)

**Решение: Astro 4.**

#### Количественное сравнение

| Метрика | Astro 4 (static) | Next.js 14 (static export) |
|---|---|---|
| JS bundle — главная страница | ~8 KB gzip | ~85 KB gzip |
| Lighthouse Performance | **100** | ~88 |
| FCP на Slow 4G | ~0.5 с | 1.0–1.5 с |
| Build time (1,000 pages) | ~18 с | ~52 с |
| Lighthouse на Slow 4G | 95+ | ~75 |
| Zero JS по умолчанию | ✅ | ❌ |

Разрыв 8 KB vs 85 KB подтверждён в независимых тестах (eastondev.com, Dec 2025): идентичные страницы на одном хосте. Разница обусловлена тем, что Next.js всегда шипит React runtime + роутер, даже с `output: 'export'`.

#### Cloudflare Pages

- **Astro**: официально поддерживается. Cloudflare — спонсор Astro. Адаптер `@astrojs/cloudflare` поддерживает KV, D1, R2, Workers. Команда деплоя: `npm run build`, output dir `dist`. Один `npm create cloudflare@latest` скаффолдит всё.
- **Next.js на Cloudflare Pages**: официальная документация (апр 2026) открывается предупреждением: *"Do not use this guide unless you have a specific use case for static exports."* Ограничения: нет ISR, `images.unoptimized: true` обязателен, нет Server Components в runtime, нет поддержки `next/image` оптимизации. Для полного Next.js на Cloudflare нужен OpenNext + Workers (не Pages).

#### «Live stats» блок (60-секундное обновление)

Astro **Islands Architecture** — именно правильный инструмент:

```astro
<!-- src/pages/index.astro -->
---
import HeroSection from '../components/HeroSection.astro';   // 0 KB JS
import LiveStatsWidget from '../components/LiveStats.jsx';    // React island
---

<HeroSection />                               <!-- Pure HTML -->
<LiveStatsWidget client:visible />            <!-- Гидрируется при скролле -->
<CTASection />                                <!-- Pure HTML -->
```

| Директива | Когда JS загружается |
|---|---|
| `client:load` | Сразу при загрузке страницы |
| `client:idle` | Когда браузер простаивает |
| `client:visible` | Когда компонент входит в viewport |
| `client:only` | Только client-side, без SSR |

Для stats блока: `client:visible`. Остальная страница — чистый HTML, 0 KB JS. Итоговый бандл страницы: ~10–20 KB. Lighthouse: 98–100.

#### SEO

- Astro генерирует чистый HTML, не требующий JS для индексации
- `@astrojs/sitemap` — официальная интеграция, добавляется одной командой
- `astro-seo` пакет для meta/OG тегов
- 60% Astro сайтов проходят Core Web Vitals vs 38% у Gatsby/WordPress

#### Developer Experience для не-frontend специалиста

| Аспект | Astro | Next.js |
|---|---|---|
| Порог входа | HTML + CSS достаточно | Нужен React + App Router |
| Формат файлов | `.astro` — как HTML с frontmatter | JSX/TSX + React paradigms |
| Markdown | Встроенный | Нужен `@next/mdx` + конфиг |
| Роутинг | Файловый, автоматический | Файловый, но layouts/loading/error |
| Время до «Hello World» | ~10 мин | ~10 мин + дни на App Router mental model |

#### Стартовые GitHub репо для Scenario A

| Шаблон | Ссылка | Stars | Описание |
|---|---|---|---|
| **Astroship** | [surjithctly/astroship](https://github.com/surjithctly/astroship) | 1.9k | Astro + TailwindCSS, SaaS/startup, free (Pro $49) |
| **Cash Bank Landing** | [Lostovayne/Landing-Page-Cash-Bank-con-Astro](https://github.com/Lostovayne/Landing-Page-Cash-Bank-con-Astro) | — | Astro 4 + Cloudflare, finance-themed |
| **astro-landing-page** | [swiing/astro-landing-page](https://github.com/swiing/astro-landing-page) | — | Astro v5 + TypeScript + Tailwind v4 |
| **Mainline** (fintech) | [astro.build/themes](https://astro.build/themes/details/mainline/) | — | shadcn/ui + Tailwind, finance-oriented |

**Рекомендация:** Стартовая точка — **Astroship**. Деплой: Cloudflare Pages, статическая сборка. Live stats блок: React компонент с `client:visible`, polling через `setInterval` или `refetchInterval` от TanStack Query.

---

### 2. UI Kit для Landing A: **shadcn/ui** + Tailwind

Для статической landing с live stats блоком: shadcn/ui идеален. Компоненты копируются в проект, бандл только для использованных элементов (2–8 KB gzip на компонент). Astro поддерживает React + Tailwind через официальные интеграции.

---

### 3. Charts для Landing A: **Recharts**

Для equity curve / APY stats блока: Recharts достаточен и имеет лучшую DX для React. SVG рендеринг пригоден для 60-секундного polling (данные обновляются редко). Bundle: ~136 KB gzip (большой, но это island — не блокирует остальную страницу). Альтернатива: Tremor (основан на Recharts + Tailwind, 35+ финансовых компонентов, Apache 2.0).

---

## СЦЕНАРИЙ B: Admin Panel + Investor Cabinet (SPA)

### 1. Фреймворк: **Vite + React** ✅ (Next.js — только если нужен SSR)

**Решение: Vite + React SPA** (не Next.js, не Astro).

#### Обоснование

- Сценарий B — **SPA**: много state, transitions, protected routes, реалтайм данные. Next.js избыточен: App Router, RSC, SSR — всё это overhead для приложения, которое и так является SPA.
- **Cloudflare Pages static export + API на Mac Mini** — это именно архитектура SPA + отдельный API. Vite строит чистый SPA без серверного компонента.
- **Astro** плохо подходит для SPA: Islands хороши для частичной гидрации, но admin panel с глубоким state — это полностью client-side приложение. Astro придётся превратить в `client:only` на каждом компоненте, что теряет смысл.

#### Если выбрать Next.js для B

Если хочется единого стека (A + B в одном репо): **Next.js 15 со static export** (`output: 'export'`). Но:
- Необходим Cloudflare Workers вместо Pages для полных фич
- Нет ISR, нет Server Components в runtime
- Плюс: единый React экосистема, App Router, более богатый шаблонный рынок

**Итоговый выбор:** Vite + React для чистого SPA. Next.js — если нужен единый репо с landing.

#### Стартовые репо для Scenario B

| Шаблон | Ссылка | Описание |
|---|---|---|
| **shadcn-fintech** | [abderrahimghazali/shadcn-fintech](https://github.com/abderrahimghazali/shadcn-fintech) | 11 страниц, MIT, candlestick charts, crypto, drag-drop. [Live demo](https://shadcn-fintech.vercel.app) |
| **Buuntu/fastapi-react** | [Buuntu/fastapi-react](https://github.com/Buuntu/fastapi-react) | Cookiecutter FastAPI + React + JWT auth + PostgreSQL |
| **Fortress** (trading desk) | [fortress-shadcn.dashboardpack.com](https://fortress-shadcn.dashboardpack.com) | Institutional: Order Management, Risk, VaR, yield curves |
| **Vault** (Robinhood-style) | [dashboardpack.com](https://dashboardpack.com) | Next.js 16 + shadcn/ui + Tailwind v4 |
| **Tremor** | [tremor.so](https://www.tremor.so) | 35+ financial chart/dashboard компонентов, Apache 2.0, Vercel |

---

### 2. UI Kit для Admin Panel B: **shadcn/ui** ✅

#### Сравнение библиотек

| Библиотека | GitHub Stars | NPM weekly | Bundle | Fintech templates |
|---|---|---|---|---|
| **shadcn/ui** | 112k+ (Apr 2026) | 150k–560k | 2–8 KB/компонент | Dominant |
| MUI v7 | 98k | 6.74M | 80–150 KB | Много |
| Chakra UI v3 | ~38k | ~500k | ~45 KB | Мало |
| Radix UI | ~17k | Очень высокий | 30 KB | Нет готовых |

#### Ключевые данные (проверено)

- **Bundle**: MUI 91.7 KB vs shadcn/ui 2.3 KB начального JS на тесте с 20 полями (asepalazhari.com)
- **Accessibility**: shadcn/ui (через Radix) — лучший структурный WAI-ARIA compliance; EAA обязателен для финтех с июня 2025
- **TypeScript**: shadcn/ui — первоклассный (вы владеете `.tsx` файлами)
- **Customization**: shadcn/ui — максимальная (правите исходник), MUI — борьба с Material Design
- **Шаблоны**: экосистема шаблонов сконвергировала на shadcn/ui в 2025–2026

#### Стек для Admin Panel

```
shadcn/ui                    — базовые компоненты (Button, Input, Card, Dialog...)
TanStack Table               — сложные data grids (сортировка, фильтр, виртуализация)
React Hook Form + Zod        — формы с валидацией (финансовые данные)
Recharts / TradingView LW    — графики (см. ниже)
```

**Не рекомендуется:**
- **Chakra UI v3**: миграция с v2 сломала API, тонкая экосистема fintech шаблонов
- **Bare Radix UI**: только если есть designer с готовой design system
- **MUI**: выбирать только если нужен MUI X Data Grid (advanced grids с группировкой/агрегацией) и есть MUI expertise

---

### 3. Charts для Admin Panel B: **Recharts + TradingView Lightweight Charts**

#### Сравнение библиотек

| Метрика | Recharts v3.8 | Chart.js v4.5 | TradingView LW Charts v5.2 |
|---|---|---|---|
| Bundle (gzip) | ~136 KB | ~92 KB (25–35 KB с tree-shaking) | **~45 KB** |
| Candlestick native | ❌ | ❌ (плагин) | ✅ |
| React integration | ✅ Native JSX | Wrapper (react-chartjs-2) | ❌ (нужен useEffect wrapper) |
| Real-time updates | SVG (ок для 60с) | Canvas (хорошо) | Canvas (отлично) |
| Large datasets | ⚠️ >3k точек медленно | ✅ до 100k | ✅ сотни тысяч баров |
| SSR | ✅ | ❌ (`use client`) | ❌ (`use client`) |
| License | MIT | MIT | Apache 2.0 (attribution!) |
| GitHub stars | 27k+ | 66k+ | 16.1k |
| npm weekly | 48M+ | 13M | ~606k |

#### Важно про лицензию TradingView

Apache 2.0 требует атрибуции. Библиотека по умолчанию отображает логотип TradingView на графике (`attributionLogo: true`). Можно оставить лого или добавить текстовую атрибуцию и скрыть лого.

#### Рекомендация по использованию

| Тип графика | Библиотека | Причина |
|---|---|---|
| Equity curve / Portfolio | **Recharts** | Лучший React DX, `<AreaChart>` с gradient fill, brush/zoom |
| Candlestick / OHLC | **LW Charts** | Native support, 45 KB, real-time perf |
| APY bar charts, pie | **Recharts** | Declarative JSX, shadcn/ui совместим |
| 60-секундный WebSocket | **LW Charts** или Chart.js | Canvas > SVG для частых обновлений |

**Практическое решение:** Recharts для общей аналитики (bar, area, pie) + TradingView Lightweight Charts для финансовых панелей (candlestick, portfolio). Обе библиотеки в одном проекте — нормально.

**Альтернатива:** [Tremor](https://www.tremor.so) — 35+ финансовых компонентов (основан на Recharts + Tailwind), Vercel, Apache 2.0 free. Идеально интегрируется с shadcn/ui стеком.

---

### 4. State Management: **TanStack Query v5 + Zustand**

#### Ключевое понимание

Эти библиотеки не конкурируют — они решают разные задачи:

- **TanStack Query** → server state (данные с сервера, кэш, SWR)
- **Zustand** → client state (UI, модалки, фильтры, WebSocket connection)
- **Jotai** → atomic state (редко нужен для dashboard-стиля приложений)

#### TanStack Query v5

| Возможность | Поддержка |
|---|---|
| Stale-while-revalidate | ✅ (`staleTime`, `gcTime`) |
| Background refetch | ✅ `refetchOnWindowFocus`, `refetchInterval` |
| 60-секундный polling | `refetchInterval: 60_000` |
| WebSocket push → cache | `queryClient.setQueryData(key, newData)` |
| Bundle (gzip) | ~11–13 KB |
| DevTools | ✅ (`@tanstack/react-query-devtools`) |

**Дефолтные настройки для FastAPI dashboard:**
```ts
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,       // 30s — считать данные свежими
      gcTime:    5 * 60_000,   // 5 мин — хранить в памяти
      refetchOnWindowFocus: true,
    },
  },
});
```

#### Zustand vs Jotai

**Выбрать Zustand когда:**
- Нужно обновлять state из WebSocket callbacks (вне React) — store на уровне модуля, импортируется везде
- Есть централизованный UI state (sidebar, активный таб, modals, user preferences)
- Redux mental model без boilerplate

**Выбрать Jotai когда:**
- Fine-grained reactivity критична (компоненты подписаны на отдельные атомы)
- Сложный derived state (атом A зависит от B и C)
- Нужна native Suspense интеграция

**Для SPA с FastAPI:** Zustand — правильный выбор из-за возможности обновлять state из WebSocket handlers вне React.

#### Паттерн FastAPI + WebSocket → TanStack Query

```ts
// WebSocket → Zustand → TanStack Query cache
const ws = new WebSocket('wss://api.earn-defi.com/ws');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'position_update') {
    // Прямой push в TanStack кэш — компоненты перерендерятся автоматически
    queryClient.setQueryData(['positions'], data.payload);
  }
};
```

#### Типобезопасная интеграция с FastAPI

```bash
# Генерация TypeScript типов + TanStack Query hooks из FastAPI OpenAPI схемы
npm install -D @hey-api/openapi-ts

npx openapi-ts \
  --input http://localhost:8000/openapi.json \
  --output src/api \
  --plugins @tanstack/react-query
```

GitHub: [hey-api/openapi-ts](https://github.com/hey-api/openapi-ts). Автогенерирует интерфейсы + `useQuery`/`useMutation` хуки для каждого FastAPI endpoint.

#### Breaking changes TanStack Query v5 (важно при миграции с v4)

| Изменение | Детали |
|---|---|
| Single-object API | Только `useQuery({ queryKey, queryFn })`, нет positional overloads |
| `isLoading` переименован | Теперь `isPending`; `isLoading` = `isPending && isFetching` |
| Callbacks удалены | `onSuccess`, `onError` удалены из `useQuery` (остались в `useMutation`) |
| `keepPreviousData` удалён | `placeholderData: keepPreviousData` helper |
| React 18 required | Использует `useSyncExternalStore` |

---

### 5. Auth: **Custom JWT (PyJWT)** ✅

#### Сравнение подходов

| | Next-Auth | Clerk | Custom JWT |
|---|---|---|---|
| Cloudflare Pages (static) | ❌ НЕСОВМЕСТИМ | ✅ | ✅ |
| Требует Node.js | Да (API routes) | Нет | Нет |
| Цена (5–10 users) | — | Free (<50k MRU) | Бесплатно |
| Vendor dependency | — | Да | Нет |
| Данные пользователей | — | У Clerk | У вас |
| Сложность | — | Низкая | Средняя |
| FastAPI интеграция | — | JWKS verification | Нативная |

#### Next-Auth — ИСКЛЮЧЁН

Next-Auth требует server-side runtime (Node.js API routes). Чистый статический Cloudflare Pages деплой — несовместим. Официальный GitHub discussion `#8547` подтверждает: обходные пути хрупкие и ломаются между версиями Next.js. **Не использовать.**

#### Clerk — только если нужен managed auth

Технически работает (FastAPI верифицирует Clerk JWT через JWKS endpoint). Бесплатно до 50k Monthly Retained Users. Но для семейного фонда из 5–10 известных пользователей — избыточно. Пользовательские данные хранятся у Clerk (важно для финансового портала).

#### Custom JWT — рекомендация

**Библиотека: PyJWT 2.8+. Не python-jose (заброшен с 2021, 8 CVE на PyPI).**

**Архитектура хранения токенов:**

```
Access Token  → React state (память) → 15 минут TTL
Refresh Token → httpOnly Secure SameSite=Lax cookie → 7 дней TTL
```

XSS не может прочитать ни один из токенов (access в памяти, refresh в httpOnly cookie).

**FastAPI auth endpoints:**
```python
from datetime import datetime, timedelta
import jwt
from fastapi import APIRouter, Response, Cookie, Header, HTTPException
from passlib.context import CryptContext

SECRET_KEY = "load-from-env-var"      # os.environ["SECRET_KEY"]
ALGORITHM = "HS256"
ACCESS_TTL = 15    # минут
REFRESH_TTL = 7    # дней

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
router = APIRouter(prefix="/auth")

def make_access_token(user_id: str) -> str:
    return jwt.encode(
        {"sub": user_id, "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TTL)},
        SECRET_KEY, algorithm=ALGORITHM
    )

def make_refresh_token(user_id: str) -> str:
    return jwt.encode(
        {"sub": user_id, "exp": datetime.utcnow() + timedelta(days=REFRESH_TTL),
         "token_type": "refresh"},
        SECRET_KEY, algorithm=ALGORITHM
    )

@router.post("/login")
async def login(credentials: LoginRequest, response: Response):
    user = authenticate_user(credentials.email, credentials.password)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    response.set_cookie(
        key="refresh_token", value=make_refresh_token(user.id),
        httponly=True, secure=True, samesite="lax",
        max_age=60 * 60 * 24 * REFRESH_TTL
    )
    return {"access_token": make_access_token(user.id), "token_type": "bearer"}

@router.post("/refresh")
async def refresh(response: Response, refresh_token: str = Cookie(None)):
    if not refresh_token:
        raise HTTPException(401)
    try:
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("token_type") != "refresh":
            raise HTTPException(401)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Refresh expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401)
    return {"access_token": make_access_token(payload["sub"]), "token_type": "bearer"}

def get_current_user(authorization: str = Header(...)):
    token = authorization.removeprefix("Bearer ")
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(403, "Invalid token")
```

**CORS (обязателен для Cloudflare Pages + FastAPI):**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://earn-defi.com"],
    allow_credentials=True,   # Обязателен для cookies
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**React: ProtectedRoute + AuthContext:**
```jsx
// AuthContext.jsx
const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [accessToken, setAccessToken] = useState(null); // В памяти
  const [loading, setLoading] = useState(true);

  // При загрузке страницы — восстановить сессию через refresh cookie
  useEffect(() => {
    fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' })
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data?.access_token) setAccessToken(data.access_token); })
      .finally(() => setLoading(false));
  }, []);

  const login = async (email, password) => {
    const res = await fetch('/api/auth/login', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    setAccessToken(data.access_token);
  };

  return (
    <AuthContext.Provider value={{ accessToken, loading, login }}>
      {children}
    </AuthContext.Provider>
  );
}

// ProtectedRoute.jsx
export function ProtectedRoute({ children }) {
  const { accessToken, loading } = useAuth();
  if (loading) return <Spinner />;
  if (!accessToken) return <Navigate to="/login" replace />;
  return children;
}
```

**Важно:** `<ProtectedRoute>` — UX convenience, не security boundary. Настоящая безопасность — FastAPI возвращает 401 на любой защищённый эндпоинт без валидного токена.

#### Security checklist

| Угроза | Митигация |
|---|---|
| XSS крадёт access token | Хранить в памяти React, не localStorage |
| XSS крадёт refresh token | httpOnly cookie — JS не может читать |
| CSRF атака через cookie | SameSite=Lax + проверка `Origin` заголовка |
| Подделка токена | PyJWT с явным `algorithms=["HS256"]`; никогда `alg=none` |
| Необратимость компрометации | Short-lived access token (15 мин) + refresh rotation |
| MITM | Cloudflare Tunnel даёт HTTPS end-to-end; `Secure=True` на cookies |
| PII в JWT | JWT base64-encoded, не зашифрован — никогда не класть чувствительные данные |

---

## Итоговая матрица стека

### Сценарий A: Landing earn-defi.com

```
Фреймворк:    Astro 4
Деплой:       Cloudflare Pages (static, 0 конфига)
Стиль:        Tailwind CSS v4
UI Kit:       shadcn/ui (React islands)
Live stats:   React компонент с client:visible + refetchInterval: 60_000
Charts:       Recharts или Tremor (в island)
State:        TanStack Query (только в island, polling)
Auth:         Нет (публичная страница)
Старт:        github.com/surjithctly/astroship
```

### Сценарий B: Admin Panel + Investor Cabinet

```
Фреймворк:    Vite + React 19 (чистый SPA)
Деплой:       Cloudflare Pages (статическая сборка)
API:          Python FastAPI на Mac Mini (Cloudflare Tunnel)
Стиль:        Tailwind CSS v4
UI Kit:       shadcn/ui
Tables:       TanStack Table (headless, shadcn styling)
Forms:        React Hook Form + Zod
Charts:       Recharts (line, bar, area) + TradingView LW Charts (candlestick)
State:        TanStack Query v5 (server state) + Zustand (client/UI state)
Auth:         Custom JWT: PyJWT 2.8+ на FastAPI + httpOnly cookie refresh
Protected:    React Router v6 + <ProtectedRoute>
Type-safety:  hey-api/openapi-ts (генерация из FastAPI /openapi.json)
Старт:        github.com/abderrahimghazali/shadcn-fintech
              github.com/Buuntu/fastapi-react (FastAPI + React + JWT)
```

---

## Ключевые GitHub репо и ресурсы

### Шаблоны

| Репо | URL | Сценарий |
|---|---|---|
| Astroship | [github.com/surjithctly/astroship](https://github.com/surjithctly/astroship) | A |
| Cash Bank Astro | [github.com/Lostovayne/Landing-Page-Cash-Bank-con-Astro](https://github.com/Lostovayne/Landing-Page-Cash-Bank-con-Astro) | A |
| shadcn-fintech (MIT) | [github.com/abderrahimghazali/shadcn-fintech](https://github.com/abderrahimghazali/shadcn-fintech) | B |
| fastapi-react cookiecutter | [github.com/Buuntu/fastapi-react](https://github.com/Buuntu/fastapi-react) | B (auth) |
| FastAPI JWT auth | [github.com/testdrivenio/fastapi-jwt](https://github.com/testdrivenio/fastapi-jwt) | B (auth) |
| Tremor components | [tremor.so](https://www.tremor.so) | A + B |
| hey-api/openapi-ts | [github.com/hey-api/openapi-ts](https://github.com/hey-api/openapi-ts) | B (types) |

### Документация

- Astro Cloudflare Pages: [developers.cloudflare.com/pages/framework-guides/deploy-an-astro-site/](https://developers.cloudflare.com/pages/framework-guides/deploy-an-astro-site/)
- Astro Islands: [docs.astro.build/en/concepts/islands/](https://docs.astro.build/en/concepts/islands/)
- TanStack Query v5 migration: [tanstack.com/query/latest/docs/framework/react/guides/migrating-to-v5](https://tanstack.com/query/latest/docs/framework/react/guides/migrating-to-v5)
- TradingView LW Charts React: [tradingview.github.io/lightweight-charts/tutorials/react/simple](https://tradingview.github.io/lightweight-charts/tutorials/react/simple)
- FastAPI JWT tutorial: [fastapi.tiangolo.com/tutorial/security/oauth2-jwt/](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)

---

## Источники

1. [Astro vs Next.js: The Technical Truth Behind 40% Faster Static Site Performance — eastondev.com (Dec 2025)](https://eastondev.com/blog/en/posts/dev/20251202-astro-vs-nextjs-comparison/)
2. [Next.js vs. Astro in 2025 — makersden.io](https://makersden.io/blog/nextjs-vs-astro-in-2025-which-framework-best-for-your-marketing-website)
3. [Deploy an Astro Site to Cloudflare Pages — developers.cloudflare.com (Apr 2026)](https://developers.cloudflare.com/pages/framework-guides/deploy-an-astro-site/)
4. [Deploy a Static Next.js Site — Cloudflare Pages Docs (Apr 2026)](https://developers.cloudflare.com/pages/framework-guides/nextjs/deploy-a-static-nextjs-site/)
5. [Islands Architecture — Astro Docs](https://docs.astro.build/en/concepts/islands/)
6. [AdminLTE: shadcn/ui vs MUI vs Ant Design 2026](https://adminlte.io/blog/shadcn-ui-vs-mui-vs-ant-design/)
7. [shadcn-fintech template — GitHub](https://github.com/abderrahimghazali/shadcn-fintech)
8. [shadcn/ui vs Chakra vs MUI Component Battle 2025 — asepalazhari.com](https://asepalazhari.com/blog/shadcn-ui-vs-chakra-ui-vs-material-ui-component-battle-2025)
9. [Best React chart libraries 2026 — LogRocket](https://blog.logrocket.com/best-react-chart-libraries-2026/)
10. [lightweight-charts — GitHub (16.1k stars)](https://github.com/tradingview/lightweight-charts)
11. [Chart.js vs Recharts — pkgpulse.com](https://www.pkgpulse.com/compare/chart.js-vs-recharts)
12. [TanStack Query docs — does this replace client state?](https://tanstack.com/query/v5/docs/framework/react/guides/does-this-replace-client-state)
13. [Announcing TanStack Query v5 — tanstack.com](https://tanstack.com/blog/announcing-tanstack-query-v5)
14. [TanStack Query + WebSockets — LogRocket](https://blog.logrocket.com/tanstack-query-websockets-real-time-react-data-fetching/)
15. [Zustand vs TanStack Query — helloadel.com](https://helloadel.com/blog/zustand-vs-tanstack-query-maybe-both/)
16. [JWT or Clerk? Choosing the Right Auth — medium.com (Apr 2026)](https://medium.com/@akildikshan01/jwt-or-clerk-choosing-the-right-authentication-for-your-next-project-681f2aa763a7)
17. [NextAuth failed on Cloudflare Pages — GitHub Discussion #8547](https://github.com/nextauthjs/next-auth/discussions/8547)
18. [PyJWT vs python-jose — iamdevbox.com](https://www.iamdevbox.com/posts/pyjwt-vs-python-jose-choosing-the-right-python-jwt-library/)
19. [Bulletproof JWT Authentication in FastAPI — medium.com (May 2025)](https://medium.com/@ancilartech/bulletproof-jwt-authentication-in-fastapi-a-complete-guide-2c5602a38b4f)
20. [FastAPI JWT Auth — testdrivenio/fastapi-jwt](https://github.com/testdrivenio/fastapi-jwt)
21. [hey-api/openapi-ts — GitHub](https://github.com/hey-api/openapi-ts)
22. [Tremor component library — tremor.so](https://www.tremor.so)
23. [Radix UI primitives](https://www.radix-ui.com/primitives)
24. [React state management in 2025 — makersden.io](https://makersden.io/blog/react-state-management-in-2025)
25. [Protected Routes in React Router — react.wiki (Jan 2026)](https://react.wiki/router/protected-routes/)

---

*Дата исследования: 2026-06-18. Данные актуальны на момент написания; npm stats и GitHub stars меняются.*
