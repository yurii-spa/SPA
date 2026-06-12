"""
SPA Family Fund — stdlib HTTP сервер (Phase 0 / MP-359)
Использует http.server.BaseHTTPRequestHandler + socketserver.TCPServer.
Без внешних зависимостей. Только stdlib.

Эндпоинты:
  GET  /health                      — healthcheck, 200 всегда
  GET  /api/public/fund/summary     — сводка фонда (открытый, CORS: *)
  GET  /api/private/investors       — список инвесторов (требует X-Fund-Token)
  POST /api/private/investor        — добавить инвестора (требует X-Fund-Token)

Конфигурация:
  SPA_FUND_PORT  — порт (по умолчанию 8765)
  SPA_FUND_TOKEN — токен для приватных эндпоинтов

Запуск:
  python3 -m spa_core.family_fund.http_server
"""
from __future__ import annotations

import http.server
import json
import os
import socketserver
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from spa_core.family_fund.models import Investor
from spa_core.family_fund.registry import InvestorRegistry

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

# Порт из переменной окружения, по умолчанию 8765
PORT: int = int(os.environ.get("SPA_FUND_PORT", "8765"))

# Директория с данными — два уровня вверх от этого файла
_DATA_DIR: Path = Path(__file__).resolve().parents[2] / "data"

# Имя переменной окружения с токеном
_TOKEN_ENV: str = "SPA_FUND_TOKEN"


# ---------------------------------------------------------------------------
# Чистые вспомогательные функции (без HTTP-зависимостей, удобны для тестов)
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Возвращает текущее UTC-время в формате ISO 8601 (YYYY-MM-DDTHH:MM:SSZ)."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_paper_status(data_dir: Path) -> dict:
    """
    Загружает paper_trading_status.json из data_dir.
    При отсутствии файла — возвращает пустой dict (graceful fallback).
    """
    path = data_dir / "paper_trading_status.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def check_token(provided_token: Optional[str]) -> bool:
    """
    Проверяет токен из заголовка X-Fund-Token против переменной SPA_FUND_TOKEN.

    Правила:
    - Если SPA_FUND_TOKEN не задан или пуст — доступ всегда запрещён (False).
    - Сравнение регистрозависимое (case-sensitive).
    """
    expected: str = os.environ.get(_TOKEN_ENV, "")
    if not expected:
        # Токен не настроен → все приватные запросы блокируются
        return False
    return provided_token == expected


def build_summary(data_dir: Path, registry: InvestorRegistry) -> dict:
    """
    Строит ответ для GET /api/public/fund/summary.

    Источники данных:
      - investors.json через InvestorRegistry.load()
      - paper_trading_status.json для AUM/APY/last_cycle

    Graceful fallback: при отсутствии файлов возвращает разумные дефолты.
    """
    # Загружаем инвесторов (с защитой от исключений)
    try:
        investors: List[Investor] = registry.load()
    except Exception:
        investors = []

    # Загружаем статус paper-торговли
    status: dict = _load_paper_status(data_dir)

    # AUM: берём current_equity, по умолчанию $100,000
    aum: float = float(status.get("current_equity", 100_000.0))

    # APY: в paper_trading_status хранится в процентах (3.19%),
    # конвертируем в доли (0.0319); если 0 — возвращаем дефолт 3.2%
    apy_pct: float = float(status.get("apy_today_pct", 0.0))
    current_apy: float = round(apy_pct / 100.0, 6) if apy_pct else 0.032

    # Количество дней трека
    paper_start: str = status.get("paper_start_date", "")
    if paper_start:
        try:
            start_dt = datetime.strptime(paper_start, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            paper_days: int = (datetime.now(tz=timezone.utc) - start_dt).days
        except ValueError:
            # Некорректный формат даты — используем days_running
            paper_days = int(status.get("days_running", 0))
    else:
        # paper_start_date отсутствует — берём days_running напрямую
        paper_days = int(status.get("days_running", 0))

    # Временная метка последнего цикла
    last_cycle: str = str(status.get("last_cycle_ts", _now_iso()))

    return {
        "aum_usd": round(aum, 2),
        "num_investors": len(investors),
        "current_apy": current_apy,
        "paper_days": paper_days,
        "status": "paper_trading",
        "last_cycle": last_cycle,
    }


def build_investors_response(
    registry: InvestorRegistry,
    data_dir: Path,
) -> List[dict]:
    """
    Строит список инвесторов для GET /api/private/investors.

    Добавляет pnl_usd = (current_equity * share_pct / 100) - initial_capital_usd.
    При отсутствии данных — pnl_usd вычисляется от 100 000 по умолчанию.
    """
    try:
        investors: List[Investor] = registry.load()
    except Exception:
        investors = []

    status: dict = _load_paper_status(data_dir)
    current_equity: float = float(status.get("current_equity", 100_000.0))

    result: List[dict] = []
    for inv in investors:
        # Текущая стоимость доли инвестора в фонде
        current_value = current_equity * inv.current_share_pct / 100.0
        pnl_usd = round(current_value - inv.initial_capital_usd, 2)
        result.append(
            {
                "id": inv.id,
                "name": inv.name,
                "email": inv.email,
                "wallet_address": inv.wallet_address,
                "joined_at": inv.joined_at,
                "initial_capital_usd": inv.initial_capital_usd,
                "current_share_pct": inv.current_share_pct,
                "pnl_usd": pnl_usd,
                "status": inv.status,
            }
        )
    return result


# ---------------------------------------------------------------------------
# Фабрика обработчика (нужна для тестов с временными директориями)
# ---------------------------------------------------------------------------

def make_handler_class(
    data_dir: Path,
    investors_path: Optional[Path] = None,
) -> type:
    """
    Создаёт subclass FundHTTPHandler с заданным data_dir.
    Используется при тестировании, чтобы изолировать данные в tmp-директории.

    Пример:
        handler_cls = make_handler_class(Path("/tmp/test_data"))
        server = TCPServer(("127.0.0.1", port), handler_cls)
    """

    class _ConfiguredHandler(FundHTTPHandler):
        """Сконфигурированный обработчик с нужными путями к данным."""

    _ConfiguredHandler.data_dir = data_dir  # type: ignore[attr-defined]
    if investors_path is not None:
        _ConfiguredHandler.registry_path = investors_path  # type: ignore[attr-defined]
    return _ConfiguredHandler


# ---------------------------------------------------------------------------
# HTTP-обработчик
# ---------------------------------------------------------------------------

class FundHTTPHandler(http.server.BaseHTTPRequestHandler):
    """
    Обработчик HTTP-запросов для Family Fund API.

    Атрибуты класса переопределяются через make_handler_class():
      data_dir      — директория с JSON-файлами данных
      registry_path — путь к investors.json (None → data_dir/investors.json)
    """

    # Пути к данным — по умолчанию стандартная data/ проекта
    data_dir: Path = _DATA_DIR
    registry_path: Optional[Path] = None

    # ------------------------------------------------------------------ #
    # Внутренние хелперы
    # ------------------------------------------------------------------ #

    def _get_registry(self) -> InvestorRegistry:
        """Создаёт InvestorRegistry с нужным путём к investors.json."""
        path: Path = self.registry_path or (self.data_dir / "investors.json")
        return InvestorRegistry(investors_path=path)

    def _get_token(self) -> Optional[str]:
        """Извлекает значение заголовка X-Fund-Token из запроса."""
        return self.headers.get("X-Fund-Token")

    def _send_json(
        self,
        code: int,
        body: Any,
        cors_public: bool = False,
    ) -> None:
        """
        Отправляет JSON-ответ.

        cors_public=True → добавляет Access-Control-Allow-Origin: *
        (только для публичных /api/public/* эндпоинтов)
        """
        payload: bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        if cors_public:
            # CORS разрешён только для публичных эндпоинтов
            self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def _send_error_json(self, code: int, message: str) -> None:
        """Отправляет стандартизированный JSON с описанием ошибки."""
        self._send_json(code, {"error": message, "status": code})

    def _parse_path(self) -> str:
        """Возвращает путь запроса без query string."""
        return self.path.split("?")[0]

    # ------------------------------------------------------------------ #
    # GET-запросы
    # ------------------------------------------------------------------ #

    def do_GET(self) -> None:  # type: ignore[override]
        """Маршрутизация всех GET-запросов."""
        path = self._parse_path()

        if path == "/health":
            self._handle_health()
        elif path == "/api/public/fund/summary":
            self._handle_public_summary()
        elif path == "/api/private/investors":
            self._handle_private_investors()
        else:
            self._send_error_json(404, f"Not found: {path}")

    def _handle_health(self) -> None:
        """
        GET /health — healthcheck.
        Всегда отвечает 200, не зависит от состояния данных.
        """
        self._send_json(
            200,
            {"status": "ok", "timestamp": _now_iso()},
            cors_public=True,
        )

    def _handle_public_summary(self) -> None:
        """
        GET /api/public/fund/summary — открытый эндпоинт, CORS: *.
        Возвращает сводку фонда на основе paper_trading_status.json
        и количества инвесторов из investors.json.
        """
        try:
            registry = self._get_registry()
            summary = build_summary(self.data_dir, registry)
            self._send_json(200, summary, cors_public=True)
        except Exception as exc:
            self._send_error_json(500, str(exc))

    def _handle_private_investors(self) -> None:
        """
        GET /api/private/investors — приватный эндпоинт.
        Требует заголовок X-Fund-Token. Без CORS.
        Возвращает список инвесторов с share_pct и pnl_usd.
        """
        if not check_token(self._get_token()):
            self._send_error_json(401, "Unauthorized")
            return
        try:
            registry = self._get_registry()
            investors = build_investors_response(registry, self.data_dir)
            self._send_json(200, investors)
        except Exception as exc:
            self._send_error_json(500, str(exc))

    # ------------------------------------------------------------------ #
    # POST-запросы
    # ------------------------------------------------------------------ #

    def do_POST(self) -> None:  # type: ignore[override]
        """Маршрутизация всех POST-запросов."""
        path = self._parse_path()

        if path == "/api/private/investor":
            self._handle_create_investor()
        else:
            self._send_error_json(404, f"Not found: {path}")

    def _handle_create_investor(self) -> None:
        """
        POST /api/private/investor — добавляет нового инвестора.
        Требует X-Fund-Token. Тело: JSON с полями name, email, wallet,
        initial_capital_usd. Возвращает 201 с созданным объектом Investor.
        """
        # Аутентификация
        if not check_token(self._get_token()):
            self._send_error_json(401, "Unauthorized")
            return

        # Читаем тело запроса
        content_length: int = int(self.headers.get("Content-Length", "0"))
        if content_length == 0:
            self._send_error_json(400, "Empty request body")
            return

        try:
            body_bytes: bytes = self.rfile.read(content_length)
            body: dict = json.loads(body_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._send_error_json(400, f"Invalid JSON: {exc}")
            return

        # Проверяем наличие обязательных полей
        required = {"name", "email", "wallet", "initial_capital_usd"}
        missing = required - set(body.keys())
        if missing:
            self._send_error_json(400, f"Missing fields: {sorted(missing)}")
            return

        # Создаём и сохраняем инвестора
        try:
            investor = Investor(
                id=str(uuid.uuid4()),
                name=str(body["name"]),
                email=str(body["email"]),
                wallet_address=str(body.get("wallet", "")),
                joined_at=_now_iso(),
                initial_capital_usd=float(body["initial_capital_usd"]),
                current_share_pct=0.0,
                status="pending",
            )
            registry = self._get_registry()
            registry.add_investor(investor)
            self._send_json(201, investor.to_dict())
        except (ValueError, TypeError) as exc:
            self._send_error_json(400, str(exc))
        except Exception as exc:
            self._send_error_json(500, str(exc))

    # ------------------------------------------------------------------ #
    # Логирование
    # ------------------------------------------------------------------ #

    def log_message(self, format: str, *args: Any) -> None:  # type: ignore[override]
        """
        Подавляем стандартный stdout-лог BaseHTTPRequestHandler.
        При необходимости отладки раскомментируй super().log_message(...).
        """
        pass  # тихий режим; не засоряем stdout в тестах


# ---------------------------------------------------------------------------
# TCPServer с allow_reuse_address для быстрого рестарта после остановки
# ---------------------------------------------------------------------------

class _ReusableTCPServer(socketserver.TCPServer):
    """TCPServer с SO_REUSEADDR — избегаем «Address already in use» при рестарте."""
    allow_reuse_address = True


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def run_server(
    port: int = PORT,
    data_dir: Path = _DATA_DIR,
) -> None:
    """
    Запускает FundHTTPHandler на заданном порту.
    Слушает только localhost (127.0.0.1) — не публичный API.
    """
    handler = make_handler_class(data_dir)
    with _ReusableTCPServer(("127.0.0.1", port), handler) as server:
        print(f"[FundHTTP] Слушаю http://127.0.0.1:{port}/")
        print(f"[FundHTTP] data_dir={data_dir}")
        print("[FundHTTP] Ctrl+C для остановки.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n[FundHTTP] Остановлен.")


if __name__ == "__main__":
    run_server()
