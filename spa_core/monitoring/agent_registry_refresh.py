"""agent_registry_refresh — производитель `data/agent_registry.json` в РАСПИСАНИИ.

Находка ADR-066 (`B2:stale:data/agent_registry.json`, сторож `architecture_conformance`):
реестр флота протух на 478 часов при SLO 26. Разбор показал не «сломанный производитель»,
а **отсутствие производителя как события**: `scripts/build_agent_registry.py` написан,
детерминирован и покрыт тестами (`test_build_agent_registry.py`), но во всём дереве его не
зовёт НИКТО — ни launchd, ни цикл, ни другой монитор. Последний запуск — руками 2026-07-17.
Манифест это честно и записал: `"producer": null`.

Класс дефекта повторяется в репозитории: **код доставлен, но никогда не вызывается** (ср.
site-freshness humanize, WS1.2 riskwire). Тест на самом производителе такого не ловит —
он проверяет, что функция работает, а не что её кто-то запускает. Поэтому здесь тест
«агент реально зовёт рефрешер» (`test_hourly_monitor_actually_calls_refresh`) — часть приёмки.

**Почему внутри agent_health, а не отдельным агентом.** Деплой агентов owner-gated
(автономный мандат, `.claude/rules/deployment.md`), а `com.spa.agent_health` уже ходит раз в
час ровно в те же источники (`launchctl list` + `~/Library/LaunchAgents`), из которых реестр
и собирается. Новая сущность не нужна — нужен вызов.

Три правила, каждое написано против конкретного способа соврать:

1. **Сторож не убивает то, что охраняет.** Любая ошибка сборки реестра остаётся внутри:
   пульс флота важнее свежести реестра, и падение здесь не имеет права уронить `agent_health`.
2. **Молчаливого «всё хорошо» нет.** Результат — словарь со статусом, он уезжает в
   `agent_health.json`: по нему видно, что рефреш вообще случился и чем кончился.
   Неудача, о которой никто не узнал, — тот самый fail-OPEN класс (#29/#31/#35–#38).
3. **Неизвестный возраст = протух** (fail-CLOSED). Нет файла, битый JSON, нечитаемая
   отметка — это причина пересобрать, а не считать свежим.

stdlib-only · атомарная запись · без сети · LLM запрещён (monitoring-домен).
"""
from __future__ import annotations

import importlib.util
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parents[2]
_BUILDER = _REPO / "scripts" / "build_agent_registry.py"

REGISTRY_FILENAME = "agent_registry.json"

# SLO реестра в манифесте — 26ч. Порог пересборки берём с большим запасом: агент ходит раз
# в час, и при 6ч у него есть ~20 попыток внутри SLO, прежде чем сторож имеет право краснеть.
# Чинить «ровно к дедлайну» — значит краснеть при первом же пропущенном запуске.
DEFAULT_MAX_AGE_HOURS = 6.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _load_builder():
    """Импорт производителя ПО ПУТИ К ФАЙЛУ — `scripts/` не пакет.

    Тот же приём уже используют `spa_core/api/routers/agents.py` и
    `test_build_agent_registry.py`; повторяем его, а не заводим третий способ."""
    spec = importlib.util.spec_from_file_location("build_agent_registry", _BUILDER)
    if spec is None or spec.loader is None:  # pragma: no cover — защита от пустого spec
        raise ImportError(f"не удалось загрузить производителя: {_BUILDER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def registry_age_hours(path: Path, now: Optional[datetime] = None) -> Optional[float]:
    """Возраст реестра по `generated_at` внутри файла. `None` ⇒ возраст НЕИЗВЕСТЕН.

    `generated_at`, а не mtime: mtime лжёт при синхронизации дерева и `git checkout` —
    ровно так же его читает и сторож `architecture_conformance`, иначе мы чинили бы одно
    число, а сторож смотрел бы на другое.

    `None` возвращается для «нет файла / битый JSON / нечитаемая отметка» и означает
    «пересобрать», а не «наверное свежий» — см. правило 3 в docstring модуля."""
    now = now or _utcnow()
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ts = raw.get("generated_at") if isinstance(raw, dict) else None
    if not isinstance(ts, str):
        return None
    try:
        parsed = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (now - parsed).total_seconds() / 3600.0


def refresh_if_stale(data_dir: Path | str,
                     now: Optional[datetime] = None,
                     max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
                     builder: Optional[Callable[[], dict]] = None) -> dict:
    """Пересобрать реестр, если он протух. НИКОГДА не бросает исключение.

    Возвращает словарь-отчёт (он же уезжает в `agent_health.json`):
      * `status`: `refreshed` · `fresh` (пересборка не требовалась) · `failed`;
      * `age_hours_before`: возраст до пересборки, `None` = не измерен (⇒ пересобирали);
      * `max_age_hours`: порог, по которому принято решение;
      * `error`: текст ошибки, только при `failed`.

    `now`/`builder` — входы, а не окружение: тест фиксирует обе стороны и не протухает от
    сдвига календаря (`.claude/rules/deployment.md`, «время в тестах»).
    """
    now = now or _utcnow()
    path = Path(data_dir) / REGISTRY_FILENAME
    age = registry_age_hours(path, now=now)
    report: dict = {
        "checked_at": now.isoformat(),
        "age_hours_before": None if age is None else round(age, 2),
        "max_age_hours": max_age_hours,
    }

    if age is not None and age < max_age_hours:
        report["status"] = "fresh"
        return report

    try:
        build = builder or _load_builder().build
        registry = build()
        if not isinstance(registry, dict) or not registry.get("generated_at"):
            raise ValueError("производитель вернул реестр без generated_at")
        from spa_core.utils.atomic import atomic_save
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        atomic_save(registry, str(path))
        report["status"] = "refreshed"
        report["total_known"] = registry.get("total_known")
        report["total_loaded"] = registry.get("total_loaded")
    except Exception as exc:  # noqa: BLE001 — правило 1: сторож не роняет то, что охраняет
        log.warning("agent_registry refresh failed: %s", exc)
        report["status"] = "failed"
        report["error"] = str(exc)
    return report
