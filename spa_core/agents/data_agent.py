"""
SPA Data Agent (M4)

Модель: Gemini Flash-Lite (в реальном деплое)
Роль:   Получает данные APY/TVL с DeFiLlama, сохраняет в БД, публикует MARKET_DATA.

Логика:
  1. Вызывает DeFiLlamaFetcher (уже реализован в data_pipeline/defillama_fetcher.py)
  2. Публикует MARKET_DATA с snapshot данными
  3. При ошибке публикует MARKET_DATA с пустым списком и флагом error
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.base import BaseAgent
from message_bus.bus import MessageBus
from message_bus.topics import Priority, Topic, market_data_payload


class DataAgent(BaseAgent):
    """
    Агент данных — обёртка над DeFiLlamaFetcher.
    Получает рыночные данные и публикует их в шину.
    """

    AGENT_ID = "data_agent"

    def __init__(self, bus: MessageBus, db_path: Path | None = None):
        super().__init__(bus, db_path)

    def run(self) -> list[str]:
        """Получить данные с DeFiLlama и опубликовать MARKET_DATA."""
        self._run_count += 1
        self.log.info("Run #%d — fetching market data", self._run_count)

        snapshots, error = self._fetch()

        payload = market_data_payload(snapshots)
        if error:
            payload["error"] = error
            payload["fetch_ok"] = False
        else:
            payload["fetch_ok"] = True

        priority = Priority.HIGH if error else Priority.NORMAL
        msg_id   = self.publish(Topic.MARKET_DATA, payload, priority=priority)

        self.log.info(
            "Published MARKET_DATA: %d protocols, fetch_ok=%s, id=%s",
            len(snapshots), not bool(error), msg_id[:8],
        )
        return [msg_id]

    # ── Private ───────────────────────────────────────────────────────────────

    def _fetch(self) -> tuple[list[dict], str | None]:
        """Запустить fetcher. Возвращает (snapshots, error_or_None).

        BL-008 Phase 2 — removed unused `import sqlite3`. The shared
        `get_connection` from `database.init_db` now delegates to the
        dual-driver abstraction (SQLite default, PostgreSQL via env).
        """
        try:
            from database.init_db import get_connection
            from data_pipeline.defillama_fetcher import collect_once

            with get_connection(self.db_path) as conn:
                collect_once(conn)
                conn.commit()

            return self._load_latest_from_db(), None

        except Exception as exc:
            self.log.error("Fetch failed: %s", exc, exc_info=True)
            # Fallback: читаем последние снапшоты из БД (если есть)
            return self._load_latest_from_db(), str(exc)

    def _load_latest_from_db(self) -> list[dict]:
        """Загрузить последние снапшоты из БД как fallback."""
        try:
            from database.init_db import get_connection
            with get_connection(self.db_path) as conn:
                rows = conn.execute("""
                    SELECT s.*, p.tier
                    FROM apy_snapshots s
                    JOIN protocols p ON s.protocol_key = p.key
                    WHERE s.id IN (
                        SELECT MAX(id) FROM apy_snapshots
                        GROUP BY protocol_key
                    )
                    ORDER BY s.apy_total DESC
                """).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            self.log.error("DB fallback failed: %s", e)
            return []
