"""spa_core/monitoring/target_stability.py — НАСКОЛЬКО надо сдвинуть ставку,
чтобы сдвинулась ЦЕЛЬ, и бывает ли такой сдвиг сам по себе (заказ цикла #534 по
карточке CIO, гэп G5→G6).

Цикл #534 (ADR-271) измерил, что предложение тени огромно: медиана хода — 35 %
капитала при потолке на ход 15 %, а сама цель переставляется на медиану 20 %
капитала в день, и якорь в $40 тыс. скачет ``aave_v3`` ↔ ``compound_v3`` через
день. Он же назвал следующий вопрос и отказался отвечать на него догадкой:
**откуда берётся неустойчивость — из мира или из оптимизатора.**

Заказ был буквально таким: «прогнать ``optimized_yield`` на ЗАМОРОЖЕННЫХ входах
двух соседних дней и сравнить цели». Замер по этому рецепту дал ответ, которого
в самом рецепте не было, — и обе половины важны.

**Половина первая: производитель ДЕТЕРМИНИРОВАН.** Те же входы дают ту же цель,
бит в бит (контроль ``determinism`` ниже гоняется каждый прогон). То есть буква
заказа («если при неизменных ставках цель всё равно переставляется — причина
внутри оптимизатора») отвечает НЕТ, и остановись замер здесь, вывод был бы
«причина снаружи, в мире» — неверный.

**Половина вторая: цель — СТУПЕНЧАТАЯ функция входа, и ступень размером с
потолок.** ``optimized_yield_breakdown`` — жадный рюкзак: он сортирует протоколы
по счёту и наливает каждому победителю ПОЛНЫЙ потолок концентрации
(``room = min(cap, budget_left)``). Величина, на которую победитель обошёл
соседа, в размер порции не входит вовсе. Значит сколь угодно малое изменение
ставки, меняющее ПОРЯДОК двух соседей, переставляет между ними до 40 %
капитала. Неустойчивость не «внутри оптимизатора» в смысле недетерминизма — она
внутри его ФОРМЫ: он усиливает шум входа до хода размером с потолок.

**Что меряет этот модуль.** Один вопрос, которого не задаёт ни один
существующий сторож: **МАРЖА** — наименьшее изменение ставки одного протокола,
при котором цель сдвигается хотя бы на ``MATERIAL_FRAC`` капитала, — и рядом
**СОБСТВЕННЫЙ дневной ход этой же ставки**, наблюдённый в журнале решений.
Вердикт выносится не сравнением с медианой, а ЧАСТОТОЙ: на скольких из
наблюдённых дней дневной ход этой ставки был больше маржи, решающей её деньги.

Замер с хоста 2026-09-09 (``origin/main`` 209de5c25, живой снимок):

===================  ========  =========  ==========================================
протокол             в цели $  маржа pp   дневных ходов ставки ≥ маржи
===================  ========  =========  ==========================================
``compound_v3``        37 895    1.0354    **9 из 25** (36 %), макс ход 4.7117 pp
``maple``              18 947    0.6870    0 из 33 (0 %), макс ход 0.0954 pp
``fluid_fusdc``        18 947    0.8494    НЕ ИЗМЕРЕНО — истории ставки в журнале нет
``morpho_blue``         9 474    0.0001    **7 из 7** (100 %)
``aave_v3``             4 737    0.6807    **7 из 21** (33 %), макс ход 1.7394 pp
``morpho_steakhouse``       0    0.0001    **20 из 20** (100 %) — чтобы ВОЙТИ в книгу
``morpho_blue_base``        0    0.0109    **8 из 10** (80 %) — чтобы ВОЙТИ в книгу
===================  ========  =========  ==========================================

Итого **$52 106 из $100 000** стоят на маржах, которые решающая их ставка сама
пересекает на трети наблюдённых дней и чаще. Это прямой ответ на вопрос №1 ТЗ
CIO («как в текущих условиях должен выглядеть оптимальный portfolio
allocation»): сегодня у этого вопроса нет устойчивого ответа — «оптимум» на
половине капитала есть round-off решающей пары, а не вывод о доходности.

И это же замыкает причинную цепь к #534, не переоткрывая её: ход в 35 %
капитала — не аппетит и не дефект демпфера, а АРИФМЕТИКА ступени. Анти-чёрн
отказывает на следствии; предмет починки лежит на ступень выше.

Три ловушки, названные заранее и разобранные ЗАМЕРОМ, а не фразой.

1. **«Половина инъекции» — та же бомба (урок #453).** Ранжируемая ставка могла
   приходить в аллокатор ДВУМЯ дверями: ``live_apy_provider`` и файл
   ``adapter_status.json``. Подмени одну — и замер отвечал бы на свой вопрос,
   а не на нужный. Двери сосчитаны дифференциально, а не глазами: правка
   ТОЛЬКО файла оставляет цель бит в бит прежней, правка ТОЛЬКО провайдера
   даёт ровно ту же цель, что правка обоих. Дверь одна — провайдер; поэтому
   возмущение идёт через него, и это ИЗМЕРЕНО (``injection_doors`` в отчёте).
2. **Частная производная — не мир.** Маржа меряется сдвигом ОДНОЙ ставки при
   остальных замороженных. Настоящий день двигает все сразу, и совместный ход
   может как отменить перестановку, так и усилить её. Поэтому модуль НЕ
   утверждает «цель сменится с вероятностью p»; он утверждает ровно
   измеренное: маржа меньше собственного дневного хода этой ставки, наблюдённого
   столько-то раз из стольких-то.
3. **«Не измерено» — третий исход, а не ноль.** Протокол без истории ставки в
   журнале (``fluid_fusdc``) попадает в ``unmeasured`` и НАЗЫВАЕТСЯ; ноль
   наблюдений не выдаётся за «шума нет». Отдельно назван и предел самого
   журнала: его ``apy_evidenced_pct`` — НЕПОЛНАЯ перепись входов
   (``morpho_steakhouse`` держал в цели $40 000, не появляясь в ней ни разу),
   поэтому воспроизвести по журналу ЦЕЛОЕ решение нельзя, и модуль этого не
   делает: журнал даёт только наблюдённый ход ставки, а цель считает ЖИВОЙ
   производитель.

**ADVISORY.** Модуль ничего не гейтит и не двигает капитал: он читает снимок,
считает цель в ПЕСОЧНИЦЕ (копия снимка, живое ``data/`` не меняется) и пишет
число. Пороги RiskPolicy v1.0, ``TriggerParams``, потолки концентрации и демпфер
``churn_damper`` не тронуты — их правка есть money-path и решение владельца.
Ветка ``except Exception`` демпфера ловушкой названа в заказе #534 отдельно и
здесь НЕ трогается: она к устойчивости цели отношения не имеет, и починить её
заодно значило бы верно ответить не на тот вопрос.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from spa_core.utils.observation import observed

log = logging.getLogger("spa.monitoring.target_stability")

VERSION = "target-stability-v1"
OUTPUT_FILENAME = "target_stability.json"

#: Доля капитала, с которой сдвиг цели считается СУЩЕСТВЕННЫМ. Ниже — округление
#: остатка, а не смена решения. Порог наш собственный (прибор), к RiskPolicy
#: отношения не имеет и ничего не гейтит.
MATERIAL_FRAC = 0.01

#: Границы двоичного поиска маржи, в процентных пунктах ставки. Верхняя взята
#: с запасом над всем наблюдённым диапазоном ставок книги (макс ≈ 14 pp).
_MARGIN_HI_PP = 12.0
_MARGIN_ITERS = 34

#: Файлы снимка, которые копируются в песочницу. Живое ``data/`` не открывается
#: на запись НИКОГДА: производитель цели читает пути, которые мы ему передаём.
_SANDBOX_FILES = (
    "adapter_orchestrator_status.json",
    "adapter_status.json",
    "risk_scores.json",
    "adapter_registry.json",
    "strategy_shadow_comparison.json",
)

HISTORY_FILENAME = "allocation_rationale_history.jsonl"

STATUS_OK = "OK"
STATUS_CRITICAL = "CRITICAL"
STATUS_WARNING = "WARNING"
STATUS_UNMEASURED = "UNMEASURED"

#: Доля наблюдённых дней, с которой «ставка сама пересекает свою маржу»
#: перестаёт быть единичным случаем. Порог прибора, не политики.
_NOISE_DECIDED_FRAC = 1.0 / 3.0


# ──────────────────────────────────────────────────────────────────────────
# входы
# ──────────────────────────────────────────────────────────────────────────
def _read_json(path: Path) -> Tuple[Optional[dict], str]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except Exception as exc:  # noqa: BLE001 — причина уезжает в отчёт словами
        return None, f"{type(exc).__name__}: {exc}"


def live_apy_map(status_doc: dict) -> Dict[str, float]:
    """{протокол: ставка в ДОЛЯХ} из наблюдений ``adapter_status.json``.

    Контракт провайдера аллокатора — доли, а в файле проценты; пересчёт здесь
    единственный и явный. ``live_apy is None`` означает «производитель не
    наблюдал» (ADR-061) и в карту НЕ попадает: подставить туда литерал
    ``fallback_apy`` значило бы измерять устойчивость выдуманного входа.
    """
    out: Dict[str, float] = {}
    adapters = (status_doc or {}).get("adapters")
    items = (adapters.items() if isinstance(adapters, dict)
             else ((str((a or {}).get("protocol")), a) for a in (adapters or [])))
    for name, entry in items:
        if not isinstance(entry, dict):
            continue
        v = entry.get("live_apy")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            try:
                fv = float(v)
            except Exception:  # noqa: BLE001
                continue
            if fv == fv and abs(fv) != float("inf"):
                out[str(name)] = fv / 100.0
    return out


def observed_daily_moves(data_dir: Path) -> Tuple[Dict[str, List[float]], str, int]:
    """{протокол: [|Δ ставки| между соседними днями, pp]} из журнала решений.

    Это НАБЛЮДЕНИЕ, а не реконструкция: ``apy_evidenced_pct`` записан самим
    писателем решения в тот день. Перепись входов в журнале НЕПОЛНА (см. шапку),
    поэтому отсутствие протокола здесь — «не измерено», а не «ход нулевой».
    """
    path = Path(data_dir) / HISTORY_FILENAME
    rows: List[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:  # noqa: BLE001 — битая строка не рушит перепись
                    continue
    except Exception as exc:  # noqa: BLE001
        return {}, f"{type(exc).__name__}: {exc}", 0
    rows.sort(key=lambda r: (str(r.get("cycle_date") or ""),
                             str(r.get("generated_at") or "")))
    series: Dict[str, List[float]] = {}
    for r in rows:
        for proto, val in (observed(r, "apy_evidenced_pct", kind=dict) or {}).items():
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                series.setdefault(str(proto), []).append(float(val))
    moves = {p: [abs(s[i] - s[i - 1]) for i in range(1, len(s))]
             for p, s in series.items() if len(s) > 1}
    return moves, "", len(rows)


# ──────────────────────────────────────────────────────────────────────────
# производитель цели — живой, в песочнице
# ──────────────────────────────────────────────────────────────────────────
def _default_target_producer(sandbox: Path) -> Callable[[Dict[str, float]], Dict[str, float]]:
    """Возвращает функцию {ставки в долях} → {протокол: $ цели}.

    Зовёт НАСТОЯЩИЙ money-path-производитель (``StrategyAllocator`` с моделью
    ``optimized_yield``) — тот же класс, который зовёт дневной цикл. Второй
    реализации целевой функции здесь нет намеренно: измерять надо потребителя,
    а не свою копию его правил.

    ``allocate()`` в файлы НЕ пишет (пишет только ``save()``, который мы не
    зовём), и все пути ему передаются в песочницу.
    """
    from spa_core.allocator.allocator import StrategyAllocator

    def produce(provider: Dict[str, float]) -> Dict[str, float]:
        res = StrategyAllocator(
            status_path=sandbox / "adapter_orchestrator_status.json",
            adapter_status_path=sandbox / "adapter_status.json",
            risk_scores_path=sandbox / "risk_scores.json",
            registry_path=sandbox / "adapter_registry.json",
            comparison_path=sandbox / "strategy_shadow_comparison.json",
            strategy_loop_enabled=False,
            allocation_model="optimized_yield",
            live_apy_provider=dict(provider),
        ).allocate()
        return {str(k): float(v) for k, v in (res.target_usd or {}).items()}

    return produce


def one_sided_move(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Односторонний сдвиг между двумя целями, $ (столько денег переезжает)."""
    keys = set(a) | set(b)
    return sum(abs(float(a.get(k, 0.0)) - float(b.get(k, 0.0))) for k in keys) / 2.0


def find_margin(produce: Callable[[Dict[str, float]], Dict[str, float]],
                base_target: Dict[str, float],
                base_provider: Dict[str, float],
                protocol: str,
                direction: int,
                *,
                capital_usd: float,
                material_frac: float = MATERIAL_FRAC) -> Optional[float]:
    """Наименьший |Δ| ставки ``protocol`` (pp), двигающий цель на ≥ порога.

    ``None`` ⇒ цель не двигается в эту сторону во всём диапазоне поиска — это
    ОТВЕТ («запас больше диапазона»), а не отказ измерять.
    """
    threshold = max(0.0, float(material_frac)) * float(capital_usd)
    base_pp = float(base_provider.get(protocol, 0.0)) * 100.0

    def moved(delta_pp: float) -> bool:
        prov = dict(base_provider)
        prov[protocol] = max(1e-9, (base_pp + direction * delta_pp) / 100.0)
        try:
            return one_sided_move(produce(prov), base_target) >= threshold
        except Exception as exc:  # noqa: BLE001 — падение прогона ≠ «не сдвинулось»
            log.warning("target_stability: прогон %s Δ=%+.4f не удался (%s)",
                        protocol, direction * delta_pp, exc)
            return False

    if not moved(_MARGIN_HI_PP):
        return None
    lo, hi = 0.0, _MARGIN_HI_PP
    for _ in range(_MARGIN_ITERS):
        mid = (lo + hi) / 2.0
        if moved(mid):
            hi = mid
        else:
            lo = mid
    return hi


def measure_injection_doors(produce: Callable[[Dict[str, float]], Dict[str, float]],
                            sandbox: Path,
                            base_provider: Dict[str, float],
                            base_target: Dict[str, float],
                            probe: Optional[str]) -> dict:
    """Сколько дверей у ранжируемой ставки — ИЗМЕРЕНО, а не предположено.

    Урок #453: инъекция обязана доходить до проводки, и «половина инъекции» —
    та же бомба, что её отсутствие. Поэтому вопрос «достаточно ли править
    провайдера» здесь не решается чтением кода: правится ТОЛЬКО файл, ТОЛЬКО
    провайдер и оба, и вердикты сравниваются.

    Возврат: ``{"verdict": "provider_is_the_only_door" | "file_also_moves_target"
    | "unmeasured", ...}``. Отсутствие пригодной пробы ⇒ третий исход.

    **Проба обязана СДВИГАТЬ цель, иначе она не различает двери**, и искать
    сдвиг надо ОБЕИМИ дверями. Две ошибки первых редакций, обе измерены:

    * брать якорь книги и ПОДНИМАТЬ его ставку — якорь уже налит по потолок,
      подъём не двигает ничего, и обе двери честно молчали (замер 09.09);
    * искать направление ТОЛЬКО провайдером — если файл провайдера
      перекрывает, ни одно направление не сдвинет цель, и самый опасный
      случай («провайдер вообще не дверь») выдал бы ``unmeasured``, то есть
      прибор промолчал бы ровно там, где обязан кричать.

    Поэтому направление ищется сперва провайдером, затем файлом, и только
    молчание ОБЕИХ дверей есть третий исход.
    """
    out: dict = {"verdict": "unmeasured", "probe": probe, "note": ""}
    if not probe or probe not in base_provider:
        out["note"] = "нет пригодного протокола для пробы (пустая карта наблюдений)"
        return out

    base_pp = float(base_provider[probe]) * 100.0
    eps = 0.5  # доллара: округление сериализации, не смена решения
    status_path = sandbox / "adapter_status.json"
    try:
        original = status_path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        out["note"] = f"снимок наблюдений нечитаем ({type(exc).__name__}: {exc})"
        return out
    try:
        original_doc = json.loads(original)
        entry = (original_doc.get("adapters") or {}).get(probe)
        if not isinstance(entry, dict):
            out["note"] = f"в снимке наблюдений нет записи {probe!r}"
            return out
    except Exception as exc:  # noqa: BLE001
        out["note"] = f"снимок наблюдений неразбираем ({type(exc).__name__}: {exc})"
        return out

    def _with_file_bumped(bumped_pp: float) -> None:
        doc = json.loads(original)
        doc["adapters"][probe]["live_apy"] = bumped_pp
        doc["adapters"][probe]["apy"] = bumped_pp
        status_path.write_text(json.dumps(doc), encoding="utf-8")

    def _restore() -> None:
        try:
            status_path.write_text(original, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 — песочница одноразовая
            log.warning("target_stability: песочница не восстановлена (%s)", exc)

    def _moves(candidate: float, *, via_file: bool) -> bool:
        bumped = base_pp + candidate
        prov = dict(base_provider)
        if not via_file:
            prov[probe] = bumped / 100.0
        try:
            if via_file:
                _with_file_bumped(bumped)
            return one_sided_move(produce(prov), base_target) > eps
        except Exception as exc:  # noqa: BLE001
            log.warning("target_stability: проба дверей %+.1f pp не удалась (%s)",
                        candidate, exc)
            return False
        finally:
            if via_file:
                _restore()

    delta_pp: Optional[float] = None
    for via_file in (False, True):
        for candidate in (3.0, -3.0):
            if base_pp + candidate <= 0.0:
                continue
            if _moves(candidate, via_file=via_file):
                delta_pp = candidate
                break
        if delta_pp is not None:
            break
    if delta_pp is None:
        out["note"] = (f"ни +3, ни −3 pp по {probe!r} цель не двигают НИ ОДНОЙ "
                       "дверью — различить двери на этом входе нельзя")
        return out

    bumped_pp = base_pp + delta_pp
    prov_only = dict(base_provider)
    prov_only[probe] = bumped_pp / 100.0
    try:
        _with_file_bumped(bumped_pp)
        t_file_only = produce(dict(base_provider))
        t_both = produce(prov_only)
    except Exception as exc:  # noqa: BLE001
        out["note"] = f"проба дверей не удалась ({type(exc).__name__}: {exc})"
        return out
    finally:
        _restore()
    try:
        t_prov_only = produce(prov_only)
    except Exception as exc:  # noqa: BLE001
        out["note"] = f"проба дверей не удалась ({type(exc).__name__}: {exc})"
        return out

    file_moved = one_sided_move(t_file_only, base_target) > eps
    prov_moved = one_sided_move(t_prov_only, base_target) > eps
    agree = one_sided_move(t_prov_only, t_both) <= eps
    out.update({
        "delta_pp": delta_pp,
        "file_only_moved_usd": round(one_sided_move(t_file_only, base_target), 2),
        "provider_only_moved_usd": round(one_sided_move(t_prov_only, base_target), 2),
        "provider_equals_both": bool(agree),
    })
    if prov_moved and not file_moved and agree:
        out["verdict"] = "provider_is_the_only_door"
        out["note"] = ("правка только файла цель не двигает, правка только "
                       "провайдера равна правке обоих ⇒ возмущение полное")
    elif file_moved:
        out["verdict"] = "file_also_moves_target"
        out["note"] = ("файл двигает цель сам по себе ⇒ возмущение через один "
                       "провайдер НЕПОЛНО, маржи считать нельзя")
    else:
        out["verdict"] = "unmeasured"
        out["note"] = ("проба не сдвинула цель ни одной дверью — различить "
                       "двери на этом входе нельзя")
    return out


# ──────────────────────────────────────────────────────────────────────────
# замер
# ──────────────────────────────────────────────────────────────────────────
def measure(data_dir: Path,
            *,
            now: Optional[datetime] = None,
            producer_factory: Optional[Callable[[Path], Callable[[Dict[str, float]],
                                                                 Dict[str, float]]]] = None,
            capital_usd: float = 100000.0,
            material_frac: float = MATERIAL_FRAC) -> dict:
    """Полный замер. Никогда не поднимает исключение; отказ = третий исход."""
    now = now or datetime.now(timezone.utc)
    data_dir = Path(data_dir)
    doc: dict = {
        "schema": VERSION,
        "generated_at": now.isoformat(),
        "mode": "advisory",
        "note": ("маржа устойчивости цели: наименьший сдвиг ставки, двигающий цель, "
                 "против собственного дневного хода этой ставки. Ничего не гейтит."),
        "material_frac": float(material_frac),
        "capital_usd": float(capital_usd),
        "status": STATUS_UNMEASURED,
        "determinism": "unmeasured",
        "injection_doors": {"verdict": "unmeasured", "note": "замер не дошёл до пробы"},
        "protocols": [],
        "unmeasured": [],
        "findings": [],
        "history_rows": 0,
    }

    status_doc, err = _read_json(data_dir / "adapter_status.json")
    if status_doc is None:
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] снимок наблюдений adapter_status.json нечитаем ({err})")
        return doc
    provider = live_apy_map(status_doc)
    if not provider:
        doc["findings"].append(
            "[НЕ ИЗМЕРЕНО] ни одной наблюдённой ставки в снимке — "
            "возмущать нечего (это находка о производителе, не о цели)")
        return doc

    moves, hist_err, hist_rows = observed_daily_moves(data_dir)
    doc["history_rows"] = hist_rows
    if hist_err:
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] журнал решений нечитаем ({hist_err}) — "
            "собственный ход ставок сравнить не с чем")

    sandbox = Path(tempfile.mkdtemp(prefix="spa_target_stability_"))
    try:
        for name in _SANDBOX_FILES:
            src = data_dir / name
            if src.exists():
                shutil.copyfile(src, sandbox / name)
        produce = (producer_factory or _default_target_producer)(sandbox)

        try:
            base_target = produce(dict(provider))
        except Exception as exc:  # noqa: BLE001
            doc["findings"].append(
                f"[НЕ ИЗМЕРЕНО] производитель цели не отработал "
                f"({type(exc).__name__}: {exc})")
            return doc
        doc["base_target_usd"] = {k: round(v, 2) for k, v in base_target.items()}

        # Контроль детерминизма — буква заказа #534 и одновременно положительный
        # контроль на сам стенд: недетерминированный производитель обесценил бы
        # любую маржу ниже, и молчать об этом нельзя.
        try:
            again = produce(dict(provider))
            doc["determinism"] = ("reproduced" if again == base_target else "DIVERGED")
        except Exception as exc:  # noqa: BLE001
            doc["determinism"] = "unmeasured"
            doc["findings"].append(
                f"[НЕ ИЗМЕРЕНО] повтор прогона не удался ({type(exc).__name__}: {exc})")
        if doc["determinism"] == "DIVERGED":
            doc["status"] = STATUS_CRITICAL
            doc["findings"].append(
                "[CRITICAL] производитель цели НЕДЕТЕРМИНИРОВАН: те же входы дали "
                "разные цели — маржи ниже недействительны, чинить надо это")
            return doc

        probe = (max(base_target, key=lambda k: base_target[k]) if base_target
                 else next(iter(sorted(provider)), None))
        doc["injection_doors"] = measure_injection_doors(
            produce, sandbox, provider, base_target, probe)
        if doc["injection_doors"]["verdict"] == "file_also_moves_target":
            doc["status"] = STATUS_UNMEASURED
            doc["findings"].append(
                "[НЕ ИЗМЕРЕНО] у ранжируемой ставки БОЛЬШЕ ОДНОЙ двери — "
                "возмущение через провайдер неполно, маржи не считаются "
                "(«половина инъекции» — та же бомба, урок #453)")
            return doc

        # Население: всё, что стои́т в цели, плюс незалитые соседи, БЛИЖАЙШИЕ ПО
        # СТАВКЕ к нижней границе залитого. У них маржа отвечает на вопрос
        # «сколько до ВХОДА в книгу» — та же ступень, вид с другой стороны.
        #
        # Отбирать соседей по АБСОЛЮТНОЙ ставке (первая редакция) — неверно:
        # верх списка занимают протоколы, отсечённые не ставкой, а TVL-полом
        # MP-011, и им маржа честно равна «не двигается вовсе». Ничьи же живут
        # ВПРИТЫК к границе залитого, и именно их надо мерить.
        funded = [p for p, v in base_target.items() if v > 0]
        frontier = min((float(provider[p]) for p in funded if p in provider),
                       default=None)
        rivals = [p for p in provider if p not in base_target]
        if frontier is not None:
            rivals.sort(key=lambda p: (abs(float(provider[p]) - frontier), p))
        else:
            rivals.sort(key=lambda p: -float(provider.get(p, 0.0)))
        population = funded + rivals[:4]

        rows: List[dict] = []
        for proto in population:
            if proto not in provider:
                continue
            up = find_margin(produce, base_target, provider, proto, +1,
                             capital_usd=capital_usd, material_frac=material_frac)
            down = find_margin(produce, base_target, provider, proto, -1,
                               capital_usd=capital_usd, material_frac=material_frac)
            candidates = [x for x in (up, down) if x is not None]
            margin = min(candidates) if candidates else None
            own = moves.get(proto)
            row = {
                "protocol": proto,
                "apy_pp": round(float(provider[proto]) * 100.0, 4),
                "target_usd": round(float(base_target.get(proto, 0.0)), 2),
                "margin_up_pp": (round(up, 4) if up is not None else None),
                "margin_down_pp": (round(down, 4) if down is not None else None),
                "margin_pp": (round(margin, 4) if margin is not None else None),
                "observed_days": (len(own) if own else 0),
                "observed_max_pp": (round(max(own), 4) if own else None),
                "observed_median_pp": (round(statistics.median(own), 4) if own else None),
                "days_exceeding_margin": None,
                "verdict": "unmeasured",
            }
            if margin is None:
                row["verdict"] = "no_move_in_range"
            elif not own:
                row["verdict"] = "unmeasured"
                doc["unmeasured"].append(proto)
            else:
                n = sum(1 for x in own if x >= margin)
                row["days_exceeding_margin"] = n
                frac = n / len(own)
                row["verdict"] = ("noise_decided" if frac >= _NOISE_DECIDED_FRAC
                                  else "margin_holds")
            rows.append(row)
        rows.sort(key=lambda r: -r["target_usd"])
        doc["protocols"] = rows

        noisy = [r for r in rows if r["verdict"] == "noise_decided"]
        at_risk = sum(r["target_usd"] for r in noisy)
        doc["capital_on_noise_decided_usd"] = round(at_risk, 2)
        doc["capital_on_noise_decided_frac"] = (
            round(at_risk / capital_usd, 6) if capital_usd else None)

        for r in noisy:
            where = ("держит" if r["target_usd"] > 0 else "входит в книгу за")
            doc["findings"].append(
                f"[CRITICAL] {r['protocol']}: цель {where} ${r['target_usd']:,.0f} "
                f"на марже {r['margin_pp']} pp, а собственный дневной ход этой "
                f"ставки был больше маржи на {r['days_exceeding_margin']} из "
                f"{r['observed_days']} наблюдённых дней "
                f"(макс {r['observed_max_pp']} pp) — решает шум, не доходность")
        for proto in doc["unmeasured"]:
            row = next((r for r in rows if r["protocol"] == proto), None)
            doc["findings"].append(
                f"[НЕ ИЗМЕРЕНО] {proto}: маржа "
                f"{row['margin_pp'] if row else '?'} pp измерена, но собственного "
                f"хода ставки в журнале решений НЕТ — перепись входов там неполна, "
                f"и ноль наблюдений за «шума нет» не выдаётся")

        if noisy:
            doc["status"] = STATUS_CRITICAL
            doc["findings"].insert(0, (
                f"[CRITICAL] ${at_risk:,.0f} из ${capital_usd:,.0f} "
                f"({at_risk / capital_usd:.1%} капитала) стоят на маржах, которые "
                f"решающая их ставка сама пересекает на трети наблюдённых дней и "
                f"чаще: жадный рюкзак наливает победителю ПОЛНЫЙ потолок, поэтому "
                f"перестановка соседей размером с шум переставляет деньги размером "
                f"с потолок. Число — ПОЛ, а не потолок: в него входят только "
                f"протоколы, чей собственный ход измерен и превысил маржу на "
                f"трети дней; неизмеренные и пограничные в него НЕ добавлены"))
        elif doc["unmeasured"]:
            doc["status"] = STATUS_WARNING
        else:
            doc["status"] = STATUS_OK
        return doc
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


# ──────────────────────────────────────────────────────────────────────────
# отчёт / проводка
# ──────────────────────────────────────────────────────────────────────────
def format_report(doc: dict) -> List[str]:
    """Строки для обязательного шага 0-офис."""
    out: List[str] = []
    status = doc.get("status", STATUS_UNMEASURED)
    det = doc.get("determinism", "unmeasured")
    det_ru = {"reproduced": "воспроизведён (те же входы → та же цель)",
              "DIVERGED": "РАСХОДИТСЯ",
              "unmeasured": "НЕ ИЗМЕРЕН"}.get(det, det)
    out.append(f"   устойчивость цели (заказ CIO G5→G6): {status} · "
               f"детерминизм производителя: {det_ru}")
    doors = doc.get("injection_doors") or {}
    if doors.get("verdict") != "provider_is_the_only_door":
        out.append(f"   двери ранжируемой ставки: {doors.get('verdict')} — "
                   f"{doors.get('note')}")
    frac = doc.get("capital_on_noise_decided_frac")
    if frac:
        out.append(f"   [ШУМ РЕШАЕТ] ${doc.get('capital_on_noise_decided_usd', 0):,.0f} "
                   f"({frac:.1%} капитала) стоят на марже меньше собственного "
                   f"дневного хода решающей ставки")
    for line in (doc.get("findings") or [])[:6]:
        out.append(f"   {line}")
    extra = len(doc.get("findings") or []) - 6
    if extra > 0:
        out.append(f"   … и ещё {extra} строк(и) — полный список в артефакте")
    out.append("   ADVISORY: пороги RiskPolicy v1.0, потолки концентрации и демпфер "
               "НЕ трогаются — правка целевой функции money-path, решение владельца")
    return out


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        write: bool = True, **kwargs) -> dict:
    """Форма, которую ждут ступень переписей ``findings_bridge`` и шаг 0-офис."""
    from spa_core.utils.atomic import atomic_save

    root = root or str(Path(__file__).resolve().parents[2])
    data_dir = Path(root) / "data"
    doc = measure(data_dir, now=now, **kwargs)
    findings = list(doc.get("findings") or [])
    doc["overall"] = doc["status"]
    doc["counts"] = {
        "critical": sum(1 for f in findings if f.startswith("[CRITICAL]")),
        "warn": 0,
        "info": 0,
        # «не измерено» считается ОТДЕЛЬНО: растворив его в нулях, мы сделали бы
        # молчание прибора неотличимым от чистого прогона.
        "unchecked": (1 if doc["status"] == STATUS_UNMEASURED else 0)
                     + len(observed(doc, "unmeasured", kind=list) or []),
    }
    if write:
        atomic_save(doc, str(data_dir / OUTPUT_FILENAME))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="маржа устойчивости цели против собственного хода ставки (заказ CIO G5→G6)")
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    data_dir = (Path(args.data_dir) if args.data_dir
                else Path(os.environ.get("SPA_DATA_DIR")
                          or (Path(__file__).resolve().parents[2] / "data")))
    doc = measure(data_dir)
    if not args.no_write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(Path(data_dir) / OUTPUT_FILENAME))
    for line in format_report(doc):
        print(line)
    return 0 if doc["status"] in (STATUS_OK, STATUS_WARNING) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
