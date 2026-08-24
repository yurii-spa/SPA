# LLM_FORBIDDEN
"""
analytics_audit_freshness — сторож ЕЖЕДНЕВНОГО аудита протокол-слепоты.

ЗАЧЕМ (аудит #3, 20.08; карточка `inbox-u-ezhednevnogo-audita-90-net-storozha-on`).
У владельца есть директива 03.08: аналитический слой обязан работать на ~90 %, и
дифференциальный аудит (`scripts/audit_protocol_blindness.py`) обязан мерить это каждый день.
20.08 обнаружилось, что **сам аудит молча стоял 13 суток** (последняя отметка 07.08), и цена
простоя измерена: метрика не сдвинулась ни на один модуль — поклассовое совпадение с замером
07.08, число в число. Никто не заметил ни того, что слой стоит, ни того, что измеритель молчит:
**у самого аудита сторожа не было**. Это наш известный класс «сторож честно отвечает на свой
вопрос, а нужный вопрос не задаёт никто» (`.claude/rules/deployment.md`).

ЧТО ИМЕННО СУДИТСЯ. Не «здоров ли аналитический слой» (на это отвечают Tier-A/B/C прогоны в
цикле) и не «верна ли метрика 90 %» — а РОВНО ОДИН вопрос: **мерили ли протокол-слепоту за
последние сутки, и видно ли это в проде.** Предмет замера — отметка `AUDIT_GENERATED_AT` в
`spa_core/analytics/_protocol_blindness.py`: её ставит САМ аудит при `--emit-markup`, файл —
код, а значит доезжает в прод обычным синком (`spa_core/`), без нового агента и без деплоя.
Ровно поэтому сторож ЗЕЛЁНЫМ бывает достижимо: сессия, прогнавшая аудит и доставившая разметку,
двигает отметку (последняя — цикл #366, 24.08 09:13Z).

ЧЕСТНЫЕ ГРАНИЦЫ (называем вслух, чтобы не переопределить метрику владельца):

  * отметка покрывает **Tier B** — только он потребляет разметку; у Tier-C вердикт считается
    in-situ каждый прогон (`signal_aggregator.run_tier_c` → `_meta.protocol_differentiation`);
  * поэтому `metric_90pct` здесь — **всегда `None`**: знаменатель 736 охватывает все тиры, и
    выдать частичный замер за метрику владельца было бы ровно тем подлогом, который карточка
    запрещает. Частичное никогда не подаётся как целое (fail-CLOSED);
  * аудит, прогнанный, но НЕ доставленный на origin, прода не двигает — и это верно:
    доставка = код работает в проде, а не «пуш состоялся» (`.claude/rules/deployment.md`).

ОТКУДА ВЗЯТ ТАКТ. Сутки (директива владельца) + запас на цикл = 30 ч, как у остальных
суточных артефактов реестра. Число — вход, а не окружение: `budget_hours` инъектируется, а
поверх него, как и для всех артефактов, действует конституция (`architecture/manifest.json`).

ПОЧЕМУ У ДОКУМЕНТА `as_of`, А НЕ `generated_at` — И ЭТО НЕ МЕЛОЧЬ. Артефакт пишется на КАЖДОМ
прогоне сторожа свежести, поэтому его собственные часы («когда вывели») о предмете не говорят
ничего: реестр, прочитав их, был бы вечно зелёным — украшение, а не проверка. Часы предмета —
отметка АУДИТА, и она кладётся в `as_of`, который `ARTIFACT_REGISTRY` читает первым из
присутствующих (`generated_at` мы намеренно не пишем), а `allow_mtime=False` не даёт
перезаписи файла подделать свежесть через mtime. Часы писателя живут отдельным полем
`derived_at` — видно, но на вердикт не влияет.

Инварианты: stdlib-only · детерминированно · LLM запрещён · read-only по чужим файлам
(пишет только свой артефакт, атомарно) · `now` — вход · advisory: НИКОГДА не гейтит
исполнение, RiskPolicy и стоп-кран.
"""
# LLM_FORBIDDEN

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Словарь статусов — тот же, что у реестра свежести: чистый проход только FRESH.
FRESH = "FRESH"
STALE = "STALE"
MISSING = "MISSING"
UNCHECKED = "UNCHECKED"

STATUS_FILENAME = "analytics_90pct_status.json"
MARKUP_REL = "spa_core/analytics/_protocol_blindness.py"

# сутки (директива владельца 03.08) + запас на цикл
DEFAULT_BUDGET_HOURS = 30.0

AUDIT_COMMAND = "python3 scripts/audit_protocol_blindness.py --tier B --emit-markup"

# Отметка из БУДУЩЕГО — это испорченные часы или чужой часовой пояс, а не «только что»
# (#291: общий `_hours_since` зажимал возраст в 0.0 и делал такое зелёным). Допуск —
# на дрейф часов между машинами, дальше — UNCHECKED, никогда не FRESH.
FUTURE_TOLERANCE_H = 0.05


def repo_root() -> Path:
    """Корень дерева, В КОТОРОМ ЖИВЁТ этот модуль — то есть судимого дерева.

    Именно то, что нужно: в проде синк кладёт сюда `spa_core/` с origin, и сторож судит
    доставленную разметку, а не чью-то чужую копию.
    """
    return Path(__file__).resolve().parents[2]


def _parse_ts(raw: object) -> Optional[datetime]:
    """ISO-8601 → datetime, fail-CLOSED: всё непарсящееся даёт None, а не «сейчас»."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def read_markup(markup_path) -> dict:
    """Прочитать отметку и классы разметки БЕЗ импорта модуля.

    Разбор через `ast`: у файла-разметки нет побочных эффектов, но импортировать произвольный
    путь ради одной строки — значит пускать чужой код в сторожа и терять возможность подсунуть
    фикстуру. Возвращает `{"exists", "stamp_raw", "counts", "reason"}`; ничего не бросает.
    """
    path = Path(markup_path)
    out = {"exists": False, "stamp_raw": None, "counts": {}, "reason": ""}
    try:
        src = path.read_text(encoding="utf-8")
    except OSError as exc:
        out["reason"] = f"разметка не прочитана: {type(exc).__name__}"
        return out
    out["exists"] = True
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        out["reason"] = f"разметка не разобрана: SyntaxError line {exc.lineno}"
        return out

    detail: dict = {}
    wide: list = []
    for node in tree.body:
        targets = []
        value = None
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
            value = node.value
        if not targets or value is None:
            continue
        name = targets[0]
        if name == "AUDIT_GENERATED_AT":
            try:
                out["stamp_raw"] = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                out["stamp_raw"] = None
        elif name == "PROTOCOL_BLIND_DETAIL":
            try:
                got = ast.literal_eval(value)
                if isinstance(got, dict):
                    detail = got
            except (ValueError, SyntaxError):
                pass
        elif name == "WIDE_OK_MODULES":
            # `frozenset({...})` — вызов, литералом целиком не берётся: разбираем аргумент.
            arg = value.args[0] if isinstance(value, ast.Call) and value.args else value
            try:
                got = ast.literal_eval(arg)
                if isinstance(got, (set, frozenset, list, tuple)):
                    wide = list(got)
            except (ValueError, SyntaxError):
                pass

    counts: dict = {"blind_total": len(detail), "wide_ok": len(wide)}
    for subtype in sorted({str(v) for v in detail.values()}):
        counts[subtype] = sum(1 for v in detail.values() if str(v) == subtype)
    out["counts"] = counts
    return out


def build_status(markup_path=None, *, now: Optional[datetime] = None,
                 budget_hours: float = DEFAULT_BUDGET_HOURS) -> dict:
    """Вердикт о свежести аудита — чистая функция от (файл разметки, `now`, такт).

    fail-CLOSED: файла нет → MISSING · отметки нет / не парсится / из будущего → UNCHECKED ·
    возраст больше такта → STALE. FRESH — только присутствующая, разобранная отметка в окне.
    """
    now = now or datetime.now(timezone.utc)
    path = Path(markup_path) if markup_path is not None else repo_root() / MARKUP_REL
    markup = read_markup(path)

    doc: dict = {
        "llm_forbidden": True,
        "deterministic": True,
        "advisory": True,
        # ЧАСЫ ПРЕДМЕТА (их читает ARTIFACT_REGISTRY) появляются ниже только вместе с отметкой
        "derived_at": now.isoformat(),          # часы ПИСАТЕЛЯ — намеренно не `generated_at`
        "subject": "audit_protocol_blindness (--emit-markup)",
        "source": MARKUP_REL,
        "tier": "B",
        "audit_command": AUDIT_COMMAND,
        "max_age_hours": float(budget_hours),
        "age_hours": None,
        "counts": markup["counts"],
        # Метрика владельца НЕ переопределяется: знаменатель 736 охватывает все тиры,
        # разметка — Tier B. Частичное не выдаётся за целое.
        "metric_90pct": None,
        "metric_unmeasured_reason": (
            "знаменатель 736 (директива владельца 03.08) охватывает все тиры; "
            "отметка разметки покрывает только Tier B — частичный замер метрикой не называем"
        ),
    }

    if not markup["exists"]:
        doc["status"] = MISSING
        doc["reason"] = markup["reason"] or f"файла разметки нет: {MARKUP_REL}"
        return doc

    stamp = _parse_ts(markup["stamp_raw"])
    if stamp is None:
        doc["status"] = UNCHECKED
        doc["reason"] = markup["reason"] or "AUDIT_GENERATED_AT отсутствует или не разобран"
        return doc

    age_h = (now - stamp).total_seconds() / 3600.0
    if age_h < -FUTURE_TOLERANCE_H:
        doc["status"] = UNCHECKED
        doc["age_hours"] = round(age_h, 2)
        doc["reason"] = (
            f"отметка аудита из будущего на {abs(age_h):.2f}ч — испорченные часы "
            "или чужой часовой пояс; «только что» из этого не следует"
        )
        return doc

    doc["as_of"] = stamp.isoformat()            # ← часы ПРЕДМЕТА, по ним судит реестр
    doc["age_hours"] = round(age_h, 2)
    doc["status"] = FRESH if age_h <= float(budget_hours) else STALE
    doc["reason"] = (
        "аудит мерили в окне такта" if doc["status"] == FRESH else
        f"аудит не мерили {age_h:.1f}ч при такте {float(budget_hours):.0f}ч — "
        "измеритель молчит, метрика 90% не двигается"
    )
    return doc


def write_status(data_dir, *, markup_path=None, now: Optional[datetime] = None,
                 budget_hours: float = DEFAULT_BUDGET_HOURS) -> dict:
    """Собрать вердикт и атомарно записать `data/analytics_90pct_status.json`.

    Никогда не бросает: сторож свежести не имеет права падать из-за своего же артефакта.
    """
    doc = build_status(markup_path, now=now, budget_hours=budget_hours)
    try:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(Path(data_dir) / STATUS_FILENAME))
    except Exception:  # pragma: no cover — запись отчёта не валит вызывающего
        pass
    return doc
