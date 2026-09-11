"""spa_core/monitoring/ranking_tie_census.py — СКОЛЬКО ЕЩЁ пар ключей решают
деньги ничьёй, и сколько капитала на них стои́т (заказ цикла #535 по карточке
CIO, гэп G5→G6).

ADR-279 измерил ФОРМУ оптимизатора: ``optimized_yield_breakdown`` — жадный
рюкзак, он наливает победителю ПОЛНЫЙ потолок концентрации, а величина, на
которую победитель обошёл соседа, в размер порции не входит вовсе. Крайним
случаем там назван ОДИН факт: ``morpho_blue`` и ``morpho_steakhouse`` имеют
ставку, совпадающую до знака, и $9 474 достаются победителю **алфавитного**
тай-брейка. Заказ #535 звучал буквально: проверить дифференциально, СКОЛЬКО ЕЩЁ
пар разрешённых ключей ранжируются на числах, совпадающих **в пределах маржи**,
и сколько капитала стои́т на таких парах суммарно; ответ «ноль пар» тоже годится
и закрывает ветку.

Замер по этому рецепту дал ответ, и обе половины важны
=====================================================

**Половина первая: буква заказа отвечает «восемь пар, НОЛЬ долларов» — и это
верный ответ не на тот вопрос.** «Маржа» ADR-279 — НАИМЕНЬШИЙ сдвиг ставки,
двигающий цель на ≥ 1 % капитала. Значит любая перестановка, которая деньги
двигает, стои́т **не меньше** маржи по построению, и признак «разрыв уложился в
маржу» отбирает почти ровно те пары, которые не двигают НИЧЕГО. Это не догадка:
на живом снимке 09.09 признак отобрал **8 из 13** соседних пар, и у всех восьми
измеренный ход капитала равен **$0**; все **3** пары, которые деньги двигают,
признаком отсеяны. Разделение полное, 8/8 против 0/3.

**Половина вторая: ярлык для «совпадают» у ADR-279 уже есть, и он другой.** Тот
же документ отказался сравнивать маржу с медианой и сравнил её с СОБСТВЕННЫМ
дневным ходом той же ставки, наблюдённым в журнале решений. Тот же ярлык,
поднятый с протокола на пару, отвечает на вопрос, который заказ и имел в виду:
разрыв, решающий порядок пары, меньше того, что эта ставка проходит сама на
трети наблюдённых дней и чаще.

Замер с хоста 2026-09-09 (живой снимок, ``origin/main`` 7f4fdfee3, песочница;
живое ``data/`` не открывается на запись). Ранжируемых ключей 14, пар всего 91,
СОСЕДНИХ по порядку 13. Деньги решает порядок в трёх парах:

=====================================  =========  =========  ==========  =================
пара                                   стоимость  ход денег  изолирован  своим ходом
                                       флипа pp                          ставки, дней
=====================================  =========  =========  ==========  =================
``morpho_blue``/``morpho_steakhouse``     0.0001    $9 474      да        7 из 7 · 20 из 20
``morpho_steakhouse``/``m_blue_base``     0.0824   $11 974     **НЕТ**   12 из 20 · 4 из 11
``aave_v3``/``aave_v3_polygon``           0.2353    $7 237      да        8 из 22
=====================================  =========  =========  ==========  =================

Отрицательный контроль (прогон на шаг НИЖЕ точки перестановки) у всех трёх
двигает **$0** — деньги принадлежат смене ПОРЯДКА, а не сдвигу ставки.

Одну из трёх ADR-279 уже назвал ⇒ **ещё две**, и обе — деньги, которые сегодня
никто не считал стоящими на ничье. Ответ «ноль пар» замером НЕ подтвердился.

Три вещи, названные заранее и разобранные замером
=================================================

1. **Ловушка заказа: тождество пула и ничья — РАЗНЫЕ предметы.** Заказ
   предупредил, что соблазн будет объявить каждую пару находкой
   ``pool_identity_collision`` (ADR-227) и закрыть вопрос ссылкой. Там ОДИН
   контракт под двумя именами (потолок концентрации занижен), здесь ДВА разных
   инструмента с совпавшей ставкой (порядок решает не доходность). Признаки
   меряются ПОРОЗНЬ: тождество — по АДРЕСУ пула, и берётся оно у канонического
   измерителя (артефакт ``data/pool_identity_collision.json``), а не считается
   заново; ничья — по величине разрыва. Все четыре клетки заполнены ЗАМЕРОМ:
   ``morpho_blue``/``morpho_steakhouse`` — ничья И один пул;
   ``aave_v3``/``aave_v3_polygon`` — ничья, пулы РАЗНЫЕ (разные сети);
   ``fluid_fusdc``/``fluid_usdc`` — один пул, но не ничья (второй ключ сегодня
   не ранжируется вовсе); остальные 10 соседних пар — ни то ни другое.
2. **Перестановка обязана быть ИЗОЛИРОВАННОЙ, иначе деньги ей не принадлежат.**
   Сдвиг одной ставки пересекает всех, кто стои́т между. Поэтому население —
   СОСЕДНИЕ пары порядка, и у каждой ПРОВЕРЯЕТСЯ, что относительный порядок
   сменился ровно у одной пары. Пара ``morpho_steakhouse``/``morpho_blue_base``
   контроль не проходит: соседняя ничья ТОЧНАЯ, и сдвиг пересекает
   ``morpho_blue`` и ``morpho_steakhouse`` одним движением — $11 974 названы,
   но паре не приписаны (третий исход ``not_isolable``). Точная ничья сваривает
   два ключа в ОДНУ ступеньку, и это само по себе находка.
3. **У каждого флипа есть отрицательный контроль.** Ход денег меряется не
   «после сдвига», а РАЗНОСТЬЮ: прогон на шаг НИЖЕ точки перестановки обязан
   двигать $0. Без него первая редакция замера дала бы ложные $11 974 у пар,
   где деньги двигал сам сдвиг ставки, а не смена порядка. Контроль не прошёл ⇒
   пара уходит в ``control_failed``, а не в находки.

**Квант ранжируемой ставки ИЗМЕРЯЕТСЯ, а не берётся из кода.** Аллокатор
округляет ставку (``apy_pct = round(live_apy * 100.0, 4)``), поэтому два числа
ближе 1e-4 pp РАВНЫ для порядка ровно, и решает алфавит. Первая редакция замера
возмущала на 1e-6 pp — ниже кванта — и получала «цель не двигается» у ВСЕХ пар,
включая ту, что ADR-279 уже назвал. Модуль поэтому меряет квант у самого
производителя и, не измерив его, ОТКАЗЫВАЕТСЯ считать перепись (третий исход),
а не считает по несуществующему шагу.

**Алфавитный тай-брейк — тоже замер.** Утверждение «при точном равенстве счётов
выигрывает алфавитно первый» проверяется наблюдением: у точной ничьи смотрится,
кто из двоих профинансирован. Точной ничьи в снимке нет ⇒ ``unmeasured``, а не
молчаливое «подтверждено».

**ADVISORY.** Модуль ничего не гейтит и капитал не двигает: читает снимок,
считает цель в песочнице (копия), пишет число. Пороги RiskPolicy v1.0, потолки
концентрации, ``TriggerParams``, kill-switch и живой трек не тронуты. Починка
ступеньки (гистерезис порядка / пропорциональный налив) отдана владельцу
карточкой ``owner-decision-devyat-tysyach-dollarov-dostayutsya-prot`` циклом
#535 и здесь НЕ делается — это money-path. Ветка ``except Exception`` демпфера
``churn_damper``, названная ловушкой в заказе #534, снова НЕ трогается.
"""
from __future__ import annotations

import itertools
import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from spa_core.utils.observation import observed, observed_number

log = logging.getLogger("spa.monitoring.ranking_tie_census")

VERSION = "ranking-tie-census-v1"
OUTPUT_FILENAME = "ranking_tie_census.json"

#: Доля капитала, с которой ход цели считается СУЩЕСТВЕННЫМ. Тот же порог, что
#: у ADR-279 (``target_stability.MATERIAL_FRAC``) — намеренно: два прибора
#: отвечают на соседние вопросы об одной ступеньке, и разные пороги сделали бы
#: их числа несравнимыми. Порог наш собственный, к RiskPolicy отношения не имеет.
MATERIAL_FRAC = 0.01

#: Доля наблюдённых дней, с которой «ставка сама проходит разрыв» перестаёт быть
#: единичным случаем. Тот же ярлык, что у ADR-279, поднятый с протокола на пару.
NOISE_DECIDED_FRAC = 1.0 / 3.0

#: Сетка поиска кванта ранжируемой ставки, pp. Ищется САМЫЙ МЕЛКИЙ шаг, который
#: производитель ещё различает; ниже него два числа для порядка РАВНЫ.
_QUANTUM_GRID: Tuple[float, ...] = (
    1e-1, 1e-2, 1e-3, 1e-4, 1e-5, 1e-6, 1e-7, 1e-8)

#: Предел поиска точки перестановки, pp (с запасом над всем наблюдённым
#: диапазоном ставок книги).
_FLIP_MAX_PP = 12.0

#: Артефакт КАНОНИЧЕСКОГО измерителя тождества пула (ADR-227). Читается, а не
#: пересчитывается: второй измеритель того же факта — это второе имя одного
#: предмета, ровно тот дефект, против которого написан ADR-227.
IDENTITY_ARTIFACT = "pool_identity_collision.json"

STATUS_OK = "OK"
STATUS_CRITICAL = "CRITICAL"
STATUS_WARNING = "WARNING"
STATUS_UNMEASURED = "UNMEASURED"

IDENTITY_SAME = "same_pool"
IDENTITY_DIFFERENT = "different_pool"
IDENTITY_UNMEASURED = "identity_unmeasured"


# ──────────────────────────────────────────────────────────────────────────
# входы
# ──────────────────────────────────────────────────────────────────────────
def _read_json(path: Path) -> Tuple[Optional[dict], str]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")), ""
    except Exception as exc:  # noqa: BLE001 — причина уезжает в отчёт словами
        return None, f"{type(exc).__name__}: {exc}"


def ranked_order(breakdown: Dict[str, dict], universe: Sequence[str]) -> List[str]:
    """Порядок, по которому жадный рюкзак раздаёт потолки.

    Ключ сортировки повторяет ``optimized_yield_breakdown``: убывающий счёт,
    при равенстве — имя. Что тай-брейк действительно алфавитный, здесь НЕ
    предполагается — это отдельный замер (:func:`verify_tie_break`).
    """
    # Ключ БЕЗ счёта не упорядочивается: прежнее чтение давало ему ноль, то есть
    # ставило его в конец так, будто счёт измерен и равен нулю (инвариант #17).
    # Кого не удалось упорядочить, называет :func:`unscored_keys`.
    scored = [(p, observed_number(breakdown.get(p) or {}, "score")) for p in universe
              if p in breakdown]
    return [p for p, sc in sorted(((p, sc) for p, sc in scored if sc is not None),
                                  key=lambda ps: (-ps[1], ps[0]))]


def unscored_keys(breakdown: Dict[str, dict], universe: Sequence[str]) -> List[str]:
    """Ключи разбора, у которых счёта НЕТ: они не упорядочены и не сравнимы."""
    return sorted(p for p in universe if p in breakdown
                  and observed_number(breakdown.get(p) or {}, "score") is None)


def verify_tie_break(breakdown: Dict[str, dict],
                     target: Dict[str, float],
                     universe: Sequence[str]) -> dict:
    """ЗАМЕР утверждения «при точном равенстве счётов выигрывает алфавит».

    Смотрится точная ничья счётов, у которой ровно один из двоих
    профинансирован: победитель наблюдаем. Нет такой пары ⇒ третий исход
    ``unmeasured`` — молчаливое «подтверждено» здесь было бы выдачей
    неизмеренного за ответ.
    """
    scenes: List[dict] = []
    for a, b in itertools.combinations(sorted(universe), 2):
        if a not in breakdown or b not in breakdown:
            continue
        sa = observed_number(breakdown.get(a) or {}, "score")
        sb = observed_number(breakdown.get(b) or {}, "score")
        if sa is None or sb is None:
            continue          # без счёта «точная ничья» не наблюдаема
        if sa != sb:
            continue
        ta, tb = float(target.get(a, 0.0)), float(target.get(b, 0.0))
        if (ta > 0.0) == (tb > 0.0):
            continue  # оба залиты или оба пусты — победитель не наблюдаем
        winner = a if ta > 0.0 else b
        scenes.append({"keys": [a, b], "funded": winner,
                       "alphabetical_first": min(a, b)})
    if not scenes:
        return {"verdict": "unmeasured",
                "note": ("точной ничьи счётов с одним залитым победителем в снимке "
                         "нет — правило тай-брейка наблюдением не проверено"),
                "scenes": []}
    diverged = [s for s in scenes if s["funded"] != s["alphabetical_first"]]
    return {
        "verdict": ("DIVERGED" if diverged else "alphabetical_confirmed"),
        "note": (f"точных ничьих с наблюдаемым победителем: {len(scenes)}; "
                 f"разошлось с алфавитом: {len(diverged)}"),
        "scenes": scenes,
    }


def measure_quantum(produce_scores: Callable[[Dict[str, float]], Dict[str, dict]],
                    provider: Dict[str, float],
                    probe: str) -> Tuple[Optional[float], str]:
    """Самый мелкий сдвиг ставки (pp), который производитель ЕЩЁ различает.

    Ниже кванта два числа для порядка равны, и решает тай-брейк. Квант меряется
    у производителя, а не читается из его исходника: замер, возмущающий ниже
    кванта, отвечает «ничего не двигается» на ЛЮБОЙ вопрос (так и вышло в первой
    редакции этого прибора).
    """
    base = produce_scores(dict(provider))
    if probe not in base:
        return None, f"проба {probe!r} отсутствует в разборе производителя"
    base_score = observed_number(base.get(probe) or {}, "score")
    if base_score is None:
        return None, f"у пробы {probe!r} нет счёта в разборе производителя"
    found: Optional[float] = None
    for step in _QUANTUM_GRID:
        prov = dict(provider)
        prov[probe] = max(1e-12, (float(provider[probe]) * 100.0 + step) / 100.0)
        try:
            got = produce_scores(prov)
        except Exception as exc:  # noqa: BLE001 — падение прогона ≠ «не различает»
            return None, f"прогон пробы не удался ({type(exc).__name__}: {exc})"
        if probe not in got:
            return None, f"проба {probe!r} исчезла из разбора при сдвиге {step} pp"
        got_score = observed_number(got.get(probe) or {}, "score")
        if got_score is None:
            return None, f"счёт пробы {probe!r} исчез из разбора при сдвиге {step} pp"
        if got_score != base_score:
            found = step
        else:
            break
    if found is None:
        return None, ("производитель не различил даже самый крупный шаг сетки "
                      f"({_QUANTUM_GRID[0]} pp) — возмущение до него не доходит")
    return found, ""


def one_sided_move(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Односторонний сдвиг между двумя целями, $ (столько денег переезжает)."""
    keys = set(a) | set(b)
    return sum(abs(float(a.get(k, 0.0)) - float(b.get(k, 0.0))) for k in keys) / 2.0


def changed_pairs(before: Sequence[str], after: Sequence[str]) -> List[Tuple[str, str]]:
    """Пары, у которых сменился ОТНОСИТЕЛЬНЫЙ порядок между двумя прогонами."""
    pos_a = {k: i for i, k in enumerate(before)}
    pos_b = {k: i for i, k in enumerate(after)}
    out: List[Tuple[str, str]] = []
    common = sorted(set(pos_a) & set(pos_b))
    for x, y in itertools.combinations(common, 2):
        if (pos_a[x] < pos_a[y]) != (pos_b[x] < pos_b[y]):
            out.append((x, y))
    return out


def identity_verdict(a: str, b: str, identity_doc: Optional[dict]) -> str:
    """Тождество пула ДВУХ ключей — по АДРЕСУ, у канонического измерителя.

    ``identity_unmeasured`` — полноценный третий исход: ключ, которого нет в
    ``keys_compared``, про адрес НИЧЕГО не сказал, и объявлять его «другим
    пулом» значило бы выдать неизмеренное за ответ (ровно та ошибка, ради
    которой ADR-227 и написан).
    """
    doc = identity_doc or {}
    compared = doc.get("keys_compared")
    if not isinstance(compared, list):
        return IDENTITY_UNMEASURED
    if a not in compared or b not in compared:
        return IDENTITY_UNMEASURED
    for coll in (doc.get("collisions") or []):
        keys = (coll or {}).get("keys")
        if isinstance(keys, list) and a in keys and b in keys:
            return IDENTITY_SAME
    return IDENTITY_DIFFERENT


# ──────────────────────────────────────────────────────────────────────────
# производитель — живой, в песочнице
# ──────────────────────────────────────────────────────────────────────────
def _default_producer(sandbox: Path):
    """{ставки в долях} → (цель $, разбор со счётом, капитал $).

    Зовёт НАСТОЯЩИЙ money-path-производитель (``StrategyAllocator`` с моделью
    ``optimized_yield``) — тот же класс, который зовёт дневной цикл. Счёт и
    множитель берутся из его СОБСТВЕННОГО разбора (``risk_breakdown``): второй
    реализации решающего числа здесь нет намеренно.
    """
    from spa_core.allocator.allocator import StrategyAllocator

    def produce(provider: Dict[str, float]):
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
        target = {str(k): float(v) for k, v in (res.target_usd or {}).items()}
        breakdown = {str(k): dict(v) for k, v in (res.risk_breakdown or {}).items()}
        return target, breakdown, float(getattr(res, "capital_usd", 0.0) or 0.0)

    return produce


def smallest_flip(produce,
                  provider: Dict[str, float],
                  universe: Sequence[str],
                  above: str,
                  below: str,
                  quantum: float) -> Optional[dict]:
    """Наименьший подъём ставки ``below``, при котором пара меняется местами.

    Шаг поиска — ИЗМЕРЕННЫЙ квант производителя: ниже него сдвиг не существует
    для порядка вовсе. Возвращает и точку перестановки, и шаг ПЕРЕД ней —
    отрицательный контроль, без которого ход денег паре не принадлежит.
    """
    base_pp = float(provider[below]) * 100.0
    step = max(quantum, 1e-12)
    delta = step
    control = 0.0
    while delta <= _FLIP_MAX_PP:
        prov = dict(provider)
        prov[below] = max(1e-12, (base_pp + delta) / 100.0)
        try:
            target, breakdown, _cap = produce(prov)
        except Exception as exc:  # noqa: BLE001 — падение прогона ≠ «не переставилось»
            log.warning("ranking_tie_census: прогон %s +%.6f pp не удался (%s)",
                        below, delta, exc)
            return None
        order = ranked_order(breakdown, universe)
        if below in order and above in order and order.index(below) < order.index(above):
            return {"flip_pp": delta, "control_pp": control,
                    "target": target, "order": order}
        control = delta
        delta = (delta + step) if delta < 100 * step else delta * 1.3
    return None


# ──────────────────────────────────────────────────────────────────────────
# замер
# ──────────────────────────────────────────────────────────────────────────
def measure(data_dir: Path,
            *,
            now: Optional[datetime] = None,
            producer_factory=None,
            capital_usd: Optional[float] = None,
            material_frac: float = MATERIAL_FRAC,
            noise_frac: float = NOISE_DECIDED_FRAC) -> dict:
    """Полный замер. Никогда не поднимает исключение; отказ = третий исход."""
    from spa_core.monitoring import target_stability as ts

    now = now or datetime.now(timezone.utc)
    data_dir = Path(data_dir)
    doc: dict = {
        "schema": VERSION,
        "generated_at": now.isoformat(),
        "mode": "advisory",
        "note": ("перепись ничьих ранжирования: сколько ПАР ключей решают деньги "
                 "разрывом меньше собственного дневного хода ставки. Ничего не гейтит."),
        "material_frac": float(material_frac),
        "noise_frac": float(noise_frac),
        "status": STATUS_UNMEASURED,
        "quantum_pp": None,
        "tie_break": {"verdict": "unmeasured", "note": "замер не дошёл до пробы",
                      "scenes": []},
        "universe": [],
        "universe_size": 0,
        "pairs_examined": 0,
        "adjacent_pairs": [],
        "by_yardstick": {},
        "identity_census": {},
        "capital_moved_by_tie_flips_usd": 0.0,
        "findings": [],
        "unmeasured": [],
    }

    status_doc, err = _read_json(data_dir / "adapter_status.json")
    if status_doc is None:
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] снимок наблюдений adapter_status.json нечитаем ({err})")
        return doc
    provider = ts.live_apy_map(status_doc)
    if not provider:
        doc["findings"].append(
            "[НЕ ИЗМЕРЕНО] ни одной наблюдённой ставки в снимке — "
            "ранжировать нечего (находка о производителе, не о ничьих)")
        return doc

    identity_doc, ident_err = _read_json(data_dir / IDENTITY_ARTIFACT)
    if identity_doc is None:
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] канонический измеритель тождества пула нечитаем "
            f"({ident_err}) — признак «один контракт» не спрошен ни у одной пары; "
            f"второй измеритель того же факта здесь НЕ строится (ADR-227)")
    moves, hist_err, hist_rows = ts.observed_daily_moves(data_dir)
    doc["history_rows"] = hist_rows
    if hist_err:
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] журнал решений нечитаем ({hist_err}) — "
            "собственный ход ставок сравнить не с чем")

    sandbox = Path(tempfile.mkdtemp(prefix="spa_ranking_tie_"))
    try:
        for name in ts._SANDBOX_FILES:
            src = data_dir / name
            if src.exists():
                shutil.copyfile(src, sandbox / name)
        produce = (producer_factory or _default_producer)(sandbox)

        try:
            base_target, base_breakdown, producer_capital = produce(dict(provider))
        except Exception as exc:  # noqa: BLE001
            doc["findings"].append(
                f"[НЕ ИЗМЕРЕНО] производитель цели не отработал "
                f"({type(exc).__name__}: {exc})")
            return doc

        cap = float(capital_usd if capital_usd else (producer_capital or 0.0))
        if cap <= 0.0:
            doc["findings"].append(
                "[НЕ ИЗМЕРЕНО] производитель не назвал капитал книги, а подставить "
                "литерал значило бы задать порог существенности из воздуха")
            return doc
        doc["capital_usd"] = round(cap, 2)
        threshold = float(material_frac) * cap

        universe = [p for p in base_breakdown if p in provider]
        order = ranked_order(base_breakdown, universe)
        doc["universe"] = list(order)
        doc["universe_size"] = len(order)
        doc["pairs_examined"] = len(order) * (len(order) - 1) // 2
        # Ключи разбора БЕЗ счёта в порядок не попали вовсе: без этого числа
        # «пар рассмотрено N» читалось бы как «рассмотрены все» (инвариант #17).
        doc["keys_without_score"] = unscored_keys(base_breakdown, universe)
        doc["base_target_usd"] = {k: round(v, 2) for k, v in base_target.items() if v}
        doc["tie_break"] = verify_tie_break(base_breakdown, base_target, order)
        if doc["tie_break"]["verdict"] == "DIVERGED":
            doc["findings"].append(
                "[CRITICAL] тай-брейк производителя НЕ алфавитный: у точной ничьи "
                "профинансирован не алфавитно первый — порядок ниже читать нельзя")
            doc["status"] = STATUS_CRITICAL
            return doc

        if len(order) < 2:
            doc["status"] = STATUS_OK
            doc["findings"].append(
                f"[OK] ранжируемых ключей {len(order)} — пары не из чего составить")
            return doc

        quantum, q_err = measure_quantum(
            lambda pr: produce(pr)[1], provider, order[-1])
        doc["quantum_pp"] = quantum
        if quantum is None:
            doc["status"] = STATUS_UNMEASURED
            doc["findings"].append(
                f"[НЕ ИЗМЕРЕНО] квант ранжируемой ставки не измерен ({q_err}) — "
                f"перепись НЕ считается: возмущение ниже кванта отвечает «ничего "
                f"не двигается» на любой вопрос, и это молчание неотличимо от "
                f"чистого прогона")
            return doc

        _margin_memo: Dict[str, Optional[float]] = {}

        def _margin_of(protocol: str) -> Optional[float]:
            """Маржа ADR-279 для ключа: НАИМЕНЬШИЙ сдвиг его ставки, двигающий
            цель на ≥ material_frac капитала. Считает ЧУЖОЙ прибор, наш только
            подаёт ему тот же производитель в той же песочнице."""
            if protocol in _margin_memo:
                return _margin_memo[protocol]
            def produce_target(pr: Dict[str, float]) -> Dict[str, float]:
                return produce(pr)[0]
            got: List[float] = []
            for direction in (+1, -1):
                try:
                    m = ts.find_margin(produce_target, base_target, provider,
                                       protocol, direction, capital_usd=cap,
                                       material_frac=material_frac)
                except Exception as exc:  # noqa: BLE001 — отказ ≠ «маржи нет»
                    log.warning("ranking_tie_census: маржа %s (%+d) не измерена (%s)",
                                protocol, direction, exc)
                    m = None
                if m is not None:
                    got.append(m)
            _margin_memo[protocol] = min(got) if got else None
            return _margin_memo[protocol]

        rows: List[dict] = []
        pairs_without_score: List[str] = []
        for i in range(len(order) - 1):
            above, below = order[i], order[i + 1]
            score_above = observed_number(base_breakdown.get(above) or {}, "score")
            score_below = observed_number(base_breakdown.get(below) or {}, "score")
            mult_raw = observed_number(base_breakdown.get(below) or {}, "risk_multiplier")
            if score_above is None or score_below is None:
                # Разрыв со стороной без счёта равнялся бы счёту соседа.
                pairs_without_score.append(f"{above}/{below}")
                continue
            gap = score_above - score_below
            mult = 0.0 if mult_raw is None else float(mult_raw)
            row: dict = {
                "above": above,
                "below": below,
                "gap_score": round(gap, 8),
                "swap_cost_pp": (round(gap / mult, 6) if mult > 0 else None),
                "margin_pp": None,
                "within_margin": None,
                "flip_pp": None,
                "control_pp": None,
                "capital_moved_usd": None,
                "control_moved_usd": None,
                "isolated": None,
                "changed_pairs": [],
                "pool_identity": identity_verdict(above, below, identity_doc),
                "own_move": {},
                "days_crossing": None,
                "days_observed": None,
                "verdict": "unmeasured",
            }
            flip = smallest_flip(produce, provider, order, above, below, quantum)
            if flip is None:
                row["verdict"] = "no_flip_in_range"
                rows.append(row)
                continue
            row["flip_pp"] = round(flip["flip_pp"], 6)
            row["control_pp"] = round(flip["control_pp"], 6)
            changed = changed_pairs(order, flip["order"])
            row["changed_pairs"] = [list(p) for p in changed]
            row["isolated"] = (len(changed) == 1)
            moved = one_sided_move(flip["target"], base_target)
            row["capital_moved_usd"] = round(moved, 2)

            prov_ctrl = dict(provider)
            prov_ctrl[below] = max(1e-12, (float(provider[below]) * 100.0
                                           + flip["control_pp"]) / 100.0)
            try:
                ctrl_target, _bd, _c = produce(prov_ctrl)
                ctrl_moved = one_sided_move(ctrl_target, base_target)
            except Exception as exc:  # noqa: BLE001
                row["verdict"] = "control_unmeasured"
                row["control_note"] = f"{type(exc).__name__}: {exc}"
                rows.append(row)
                continue
            row["control_moved_usd"] = round(ctrl_moved, 2)

            # Буква заказа #535 — «разрыв уложился в МАРЖУ». Маржа берётся у
            # ADR-279 (``target_stability.find_margin``), а НЕ считается заново:
            # два измерителя одного числа — это два имени одного предмета.
            # Сравнивать структурным заменителем («флип не двигает денег»)
            # нельзя: замер 09.09 даёт 8 пар против 10, то есть заменитель
            # ответил бы верно НЕ на тот вопрос ровно там, где вопрос и задан.
            margin = _margin_of(below)
            row["margin_pp"] = (round(margin, 6) if margin is not None else None)
            row["within_margin"] = (margin is not None
                                    and flip["flip_pp"] <= margin)

            # собственный ход ставок обеих сторон против стоимости перестановки
            crossing = 0
            observed = 0
            for side in (above, below):
                series = moves.get(side) or []
                row["own_move"][side] = [
                    sum(1 for x in series if x >= flip["flip_pp"]), len(series)]
                if series:
                    n, m = row["own_move"][side]
                    if m and (n / m) > (crossing / observed if observed else -1.0):
                        crossing, observed = n, m
            row["days_crossing"] = crossing if observed else None
            row["days_observed"] = observed or None

            material = moved >= threshold
            if ctrl_moved >= threshold:
                row["verdict"] = "control_failed"
            elif not material:
                row["verdict"] = "no_capital_on_the_pair"
            elif not row["isolated"]:
                row["verdict"] = "not_isolable"
            elif not observed:
                row["verdict"] = "capital_but_move_unmeasured"
                doc["unmeasured"].append(f"{above}/{below}")
            elif (crossing / observed) >= noise_frac:
                row["verdict"] = "noise_decided"
            else:
                row["verdict"] = "gap_holds"
            rows.append(row)

        doc["adjacent_pairs"] = rows

        noisy = [r for r in rows if r["verdict"] == "noise_decided"]
        not_iso = [r for r in rows if r["verdict"] == "not_isolable"]
        ctrl_bad = [r for r in rows if r["verdict"] == "control_failed"]
        unmeas = [r for r in rows if r["verdict"] == "capital_but_move_unmeasured"]
        material_rows = noisy + not_iso + unmeas + [
            r for r in rows if r["verdict"] == "gap_holds"]

        # Буква заказа: «разрыв уложился в маржу». Маржа ADR-279 — НАИМЕНЬШИЙ
        # сдвиг, двигающий ≥ material_frac капитала, поэтому признак меряется
        # прямо здесь и без второго прибора: перестановка дешевле маржи ⇔ она
        # НЕ двигает существенных денег.
        if pairs_without_score:
            doc["pairs_without_score"] = pairs_without_score
        within_margin = [r for r in rows if r.get("within_margin")]
        # `capital_moved_usd is None` — денег НЕ ИЗМЕРЯЛИ; ноль — измерили и он ноль.
        within_unmeasured = [r for r in within_margin
                             if observed_number(r, "capital_moved_usd") is None]
        within_with_money = [r for r in within_margin
                             if (observed_number(r, "capital_moved_usd") or 0.0) >= threshold]
        doc["by_yardstick"] = {
            "within_margin": {
                "pairs": len(within_margin),
                "pairs_with_capital": len(within_with_money),
                "capital_moved_usd": round(
                    sum(observed_number(r, "capital_moved_usd") or 0.0
                        for r in within_margin), 2),
                "pairs_capital_unmeasured": len(within_unmeasured),
                "note": ("буква заказа #535. Маржа — НАИМЕНЬШИЙ сдвиг, двигающий "
                         "≥1 % капитала, поэтому перестановка, которая деньги "
                         "двигает, стои́т НЕ МЕНЬШЕ маржи по построению: признак "
                         "отбирает ровно те пары, на которых денег нет"),
            },
            "own_daily_move": {
                "pairs": len(noisy),
                "capital_moved_usd": round(
                    sum(r["capital_moved_usd"] for r in noisy), 2),
                "note": ("ярлык ADR-279, поднятый с протокола на пару: разрыв, "
                         "решающий порядок, меньше собственного дневного хода "
                         "ставки на трети наблюдённых дней и чаще"),
            },
        }
        doc["capital_moved_by_tie_flips_usd"] = doc["by_yardstick"]["own_daily_move"][
            "capital_moved_usd"]

        cells = {"tie_and_same_pool": [], "tie_only": [],
                 "same_pool_only": [], "neither": [], "identity_unmeasured": []}
        for r in rows:
            tie = r["verdict"] == "noise_decided"
            ident = r["pool_identity"]
            name = f"{r['above']}/{r['below']}"
            if ident == IDENTITY_UNMEASURED:
                cells["identity_unmeasured"].append(name)
            elif tie and ident == IDENTITY_SAME:
                cells["tie_and_same_pool"].append(name)
            elif tie:
                cells["tie_only"].append(name)
            elif ident == IDENTITY_SAME:
                cells["same_pool_only"].append(name)
            else:
                cells["neither"].append(name)
        doc["identity_census"] = {k: sorted(v) for k, v in cells.items()}
        doc["identity_census"]["note"] = (
            "ловушка заказа #535: тождество пула (ADR-227, ОДИН контракт под двумя "
            "именами) и ничья ранжирования (ДВА инструмента с совпавшей ставкой) — "
            "разные предметы. Признаки измерены ПОРОЗНЬ: тождество взято у "
            "канонического измерителя по АДРЕСУ, ничья — по разрыву")

        for r in noisy:
            doc["findings"].append(
                f"[CRITICAL] {r['above']}/{r['below']}: порядок пары решает "
                f"${r['capital_moved_usd']:,.0f}, а стои́т перестановка "
                f"{r['flip_pp']} pp — разрыв, который ставка этой пары сама "
                f"проходит на {r['days_crossing']} из {r['days_observed']} "
                f"наблюдённых дней. Контроль на шаг ниже двигает "
                f"${r['control_moved_usd']:,.0f}; тождество пула: "
                f"{r['pool_identity']}")
        for r in not_iso:
            doc["findings"].append(
                f"[НЕ ИЗМЕРЕНО] {r['above']}/{r['below']}: перестановка двигает "
                f"${r['capital_moved_usd']:,.0f}, но она НЕ изолирована — тем же "
                f"сдвигом меняют порядок пар(ы): "
                f"{', '.join('/'.join(p) for p in r['changed_pairs'])}. Деньги "
                f"названы, паре НЕ приписаны: соседняя ничья точная и сваривает "
                f"ключи в одну ступеньку")
        for r in ctrl_bad:
            doc["findings"].append(
                f"[НЕ ИЗМЕРЕНО] {r['above']}/{r['below']}: отрицательный контроль "
                f"НЕ прошёл — прогон на шаг ниже точки перестановки уже двигает "
                f"${r['control_moved_usd']:,.0f}, значит деньги двигает сдвиг "
                f"ставки, а не смена порядка; паре они не принадлежат")
        for r in unmeas:
            doc["findings"].append(
                f"[НЕ ИЗМЕРЕНО] {r['above']}/{r['below']}: порядок решает "
                f"${r['capital_moved_usd']:,.0f}, но собственного хода НИ ОДНОЙ из "
                f"двух ставок в журнале решений нет — ноль наблюдений за «разрыв "
                f"держит» не выдаётся")
        if doc["tie_break"]["verdict"] == "unmeasured":
            doc["findings"].append(
                "[НЕ ИЗМЕРЕНО] правило тай-брейка наблюдением не проверено: точной "
                "ничьи счётов с одним залитым победителем в снимке нет")

        if noisy:
            doc["status"] = STATUS_CRITICAL
            doc["findings"].insert(0, (
                f"[CRITICAL] порядок решает деньги в {len(material_rows)} парах из "
                f"{len(rows)} соседних (всего пар в разрешённом наборе "
                f"{doc['pairs_examined']}); шум решает в {len(noisy)}, и на них "
                f"переезжает ${doc['capital_moved_by_tie_flips_usd']:,.0f}. "
                f"Признак «разрыв уложился в маржу» (буква заказа) отобрал "
                f"{len(within_margin)} пар(ы), из них с деньгами "
                f"{len(within_with_money)}, всего "
                f"${doc['by_yardstick']['within_margin']['capital_moved_usd']:,.0f} "
                f"— верный ответ НЕ на тот вопрос: перестановка, двигающая деньги, "
                f"по построению стои́т не меньше маржи, поэтому признак отбирает "
                f"пары БЕЗ денег"))
        elif not_iso or ctrl_bad or unmeas or doc["unmeasured"]:
            doc["status"] = STATUS_WARNING
        else:
            doc["status"] = STATUS_OK
            doc["findings"].insert(0, (
                f"[OK] ни одна из {len(rows)} соседних пар не решает деньги "
                f"разрывом меньше собственного дневного хода ставки — ветка заказа "
                f"#535 закрыта ответом «ноль пар»"))
        return doc
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


# ──────────────────────────────────────────────────────────────────────────
# отчёт / проводка
# ──────────────────────────────────────────────────────────────────────────
def format_report(doc: dict) -> List[str]:
    """Строки для обязательного шага 0-офис.

    Порядок строк — порядок вопроса: сперва КВАНТ и тай-брейк (без них перепись
    не число, а украшение), затем ДВА ярлыка рядом — буква заказа и ярлык, на
    который она заменена, — и только потом поимённые находки. Владелец, увидев
    один ярлык, не узнал бы, что второй отвечает на другой вопрос.
    """
    out: List[str] = []
    status = doc.get("status", STATUS_UNMEASURED)
    out.append(f"   ничьи ранжирования (заказ CIO #535): {status} · "
               f"ключей {doc.get('universe_size', 0)} · пар "
               f"{doc.get('pairs_examined', 0)} (соседних "
               f"{len(doc.get('adjacent_pairs') or [])})")
    q = doc.get("quantum_pp")
    tb = (doc.get("tie_break") or {}).get("verdict", "unmeasured")
    out.append(f"   квант ранжируемой ставки: "
               f"{'НЕ ИЗМЕРЕН' if q is None else f'{q} pp'} · "
               f"тай-брейк: {tb}")
    ys = doc.get("by_yardstick") or {}
    wm, od = ys.get("within_margin") or {}, ys.get("own_daily_move") or {}
    if wm or od:
        out.append(f"   [ЯРЛЫК ЗАКАЗА] «разрыв в пределах маржи»: "
                   f"{wm.get('pairs', 0)} пар(ы), из них с деньгами "
                   f"{wm.get('pairs_with_capital', 0)}, "
                   f"${wm.get('capital_moved_usd', 0):,.0f} — маржа есть "
                   f"НАИМЕНЬШИЙ денежный сдвиг, поэтому признак отбирает пары "
                   f"БЕЗ денег")
        out.append(f"   [ЯРЛЫК ADR-279] «разрыв меньше собственного хода ставки»: "
                   f"{od.get('pairs', 0)} пар(ы), "
                   f"${od.get('capital_moved_usd', 0):,.0f} переезжает")
    ic = doc.get("identity_census") or {}
    if ic:
        out.append(f"   тождество пула ОТДЕЛЬНО от ничьи (ловушка ADR-227): "
                   f"ничья+один пул {len(ic.get('tie_and_same_pool') or [])} · "
                   f"только ничья {len(ic.get('tie_only') or [])} · "
                   f"только один пул {len(ic.get('same_pool_only') or [])} · "
                   f"ни то ни другое {len(ic.get('neither') or [])} · "
                   f"тождество НЕ измерено "
                   f"{len(observed(ic, 'identity_unmeasured', kind=list) or [])}")
    for line in (doc.get("findings") or [])[:6]:
        out.append(f"   {line}")
    extra = len(doc.get("findings") or []) - 6
    if extra > 0:
        out.append(f"   … и ещё {extra} строк(и) — полный список в артефакте")
    out.append("   ADVISORY: пороги RiskPolicy v1.0, потолки концентрации и форма "
               "целевой функции НЕ трогаются — починка ступеньки money-path и "
               "решение владельца (карточка заведена циклом #535)")
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
                     + sum(1 for f in findings if f.startswith("[НЕ ИЗМЕРЕНО]")),
    }
    if write:
        atomic_save(doc, str(data_dir / OUTPUT_FILENAME))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="перепись ничьих ранжирования: сколько ПАР решают деньги "
                    "разрывом меньше собственного хода ставки (заказ CIO #535)")
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
