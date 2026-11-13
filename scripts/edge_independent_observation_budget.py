"""
scripts/edge_independent_observation_budget.py — #157 IOB: Independent-Observation Budget.

ИСПОЛНЕНИЕ ЗАКАЗА #155 дословно: «Сколько независимых наблюдений нужно, чтобы „отбор угадал“
перестало быть удачей? У фикстуры один шов. Приёмка — названное число швов/панелей, на которых
правило отбора по скорости восстановления можно проверить НЕ ПОВТОРНО, и честный ответ „их
столько нет“, если столько нет.»

ТРИ ВОПРОСА, и они РАЗНЫЕ — поэтому мерятся раздельно:

  (1) АРИФМЕТИКА. Какова вероятность угадать пару из N книг СЛУЧАЙНО, и сколько независимых
      попаданий подряд нужно, чтобы это перестало объясняться удачей на уровне α? Ответ не
      зависит ни от какой панели — это свойство самого утверждения «отбор угадал».

  (2) СКЛАДКИ ФИКСТУРЫ (leave-one-crisis-out). У фикстуры три кризиса. Правило «две лучшие по
      скорости восстановления» можно обучить на ДВУХ кризисах и проверить на ТРЕТЬЕМ — три
      раза, каждый раз на другом третьем. Это и есть все НЕ ПОВТОРНЫЕ проверки, которые панель
      допускает. Попадание = пара, выбранная по TRAIN-скорости, совпала с парой наименьших
      потерь в удержанном кризисе. Ожидание пересечения при случайном выборе печатается рядом.

  (3) БЮДЖЕТ РЕАЛЬНОЙ ПАНЕЛИ. Сколько у реальной 10-книжной панели (`data/aggressive_lab`,
      блок `phase == backtest`) эпизодов просадки глубже пошлины входа (96 bp, конвенция #149),
      у скольких книг они есть вовсе, и сколько СОВМЕСТНЫХ эпизодов (новые минимумы ≥ 2 книг в
      одном кластере дат) — потому что правило отбора ПО кризису проверяется только на кризисе,
      в котором есть кого сравнивать.

ЧЕСТНАЯ РАМКА. Все числа фикстуры — [bt], детерминированный генератор (`aggressive_lab/fixtures.py`):
его кризисы — АВТОРСКИЕ числа (`window_hits`), а не наблюдения, поэтому три складки — это три
проверки на ОДНОМ генераторе, а не три независимых мира. Реальная панель читается только в блоке
`backtest`; forward-блок наблюдений марки не содержит (#154) и окном OOS не является. Шов, пошлина,
окна кризисов и симулятор ЧИТАЮТСЯ у прибора #153 — своей копии чисел здесь нет.

Третий исход (инв. #17): фикстура не материализована · ряд книги пуст · прибор #153 не ввезён ·
каталог панели не прочитан — всё это ОТКАЗ кодом 2 с названной причиной, никогда не ноль и не
«складок нет».
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

_MODULE_ROOT = Path(__file__).resolve().parents[1]

ALPHA = 0.05          # уровень, на котором «удача» перестаёт быть объяснением
PAIR_SIZE = 2         # правило #153/#155 выбирает ДВЕ книги
BACKTEST_PHASE = "backtest"
JOINT_MIN_BOOKS = 2   # совместный эпизод = НОВОЕ ДНО не меньше чем у двух книг в одном кластере дат
JOINT_GAP_DAYS = 7    # кластер рвётся, если между днями новых минимумов больше недели


class Unmeasured(Exception):
    """Прибор не смог ответить. Не подменяется нулём и не выдаётся за «складок нет»."""


# ── ввоз прибора #153 (одна копия шва, пошлины, окон и симулятора) ─────────────────────────

def load_crp_module():
    path = _MODULE_ROOT / "scripts" / "edge_crisis_recovery_profile.py"
    if not path.is_file():
        raise Unmeasured(f"прибор #153 не найден: {path}")
    spec = importlib.util.spec_from_file_location("edge_crisis_recovery_profile", path)
    if spec is None or spec.loader is None:
        raise Unmeasured(f"прибор #153 не загружается: {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001
        raise Unmeasured(f"прибор #153 не исполнен: {type(exc).__name__}: {exc}") from exc
    return mod


# ── (1) арифметика утверждения «отбор угадал» ─────────────────────────────────────────────

def chance_exact_pair(n_books: int, k: int = PAIR_SIZE) -> float:
    """Вероятность угадать РОВНО ту пару (k из n) случайным выбором."""
    if n_books < k or k <= 0:
        raise ValueError(f"пара из {k} при {n_books} книгах не существует")
    return 1.0 / math.comb(n_books, k)


def chance_overlap_at_least(n_books: int, k: int, m: int) -> float:
    """P(|случайная k-пара ∩ истинная k-пара| ≥ m) — гипергеометрика без параметров."""
    if n_books < k or k <= 0:
        raise ValueError(f"пара из {k} при {n_books} книгах не существует")
    total = math.comb(n_books, k)
    hits = 0
    for j in range(m, k + 1):
        hits += math.comb(k, j) * math.comb(n_books - k, k - j)
    return hits / total


def expected_overlap(n_books: int, k: int = PAIR_SIZE) -> float:
    """Ожидание пересечения двух случайных k-подмножеств: k·k/n."""
    return k * k / n_books


def min_folds_for_alpha(p0: float, alpha: float = ALPHA) -> int:
    """Сколько независимых попаданий ПОДРЯД нужно, чтобы p0^n < alpha. Все складки — попадания."""
    if not (0.0 < p0 < 1.0):
        raise ValueError("p0 обязано лежать в (0, 1)")
    if not (0.0 < alpha < 1.0):
        raise ValueError("alpha обязано лежать в (0, 1)")
    n = 1
    while p0 ** n >= alpha:
        n += 1
    return n


def arithmetic_section(n_books: int, k: int = PAIR_SIZE, alpha: float = ALPHA) -> dict:
    p_exact = chance_exact_pair(n_books, k)
    p_ge1 = chance_overlap_at_least(n_books, k, 1)
    return {
        "n_books": n_books,
        "pair_size": k,
        "alpha": alpha,
        "p_exact_pair_by_chance": p_exact,
        "p_overlap_ge1_by_chance": p_ge1,
        "expected_overlap_by_chance": expected_overlap(n_books, k),
        "min_folds_all_exact_hits": min_folds_for_alpha(p_exact, alpha),
        "min_folds_all_overlap_ge1": min_folds_for_alpha(p_ge1, alpha),
    }


# ── (2) складки leave-one-crisis-out на фикстуре ──────────────────────────────────────────

def velocity_on(CRP, series, crises: Sequence[dict]) -> float:
    """Скорость восстановления ТОЛЬКО по названным кризисам — складка задаёт их сама."""
    rds: List[float] = []
    for c in crises:
        rd = CRP.compute_recovery_days(series, c)
        if rd is not None:
            rds.append(rd)
    if not rds:
        return float("inf")
    mean_rd = sum(rds) / len(rds)
    return 1.0 / mean_rd if mean_rd > 0 else float("inf")


def crisis_loss(series: List[Tuple[datetime.date, float]], crisis: dict) -> Optional[float]:
    """Доля потери от пика перед окном до дна внутри окна. None — окна в ряде нет."""
    eq: Dict[datetime.date, float] = {d: e for d, e in series}
    dates = sorted(eq)
    pre = [d for d in dates if d < crisis["from"]]
    win = [d for d in dates if crisis["from"] <= d <= crisis["to"]]
    if not pre or not win:
        return None
    peak = eq[max(pre)]
    trough = min(eq[d] for d in win)
    return (peak - trough) / peak if peak > 0 else None


def rank_top(scores: Dict[str, float], k: int, *, highest: bool) -> List[str]:
    def key(b: str) -> Tuple[float, str]:
        v = scores[b]
        if v == float("inf"):
            v = 1e18
        return ((-v if highest else v), b)
    return sorted(scores, key=key)[:k]


def loco_folds(CRP, series_map: Dict[str, list], crises: Sequence[dict],
               k: int = PAIR_SIZE) -> List[dict]:
    """Каждая складка держит ОДИН кризис вне обучения. Складок ровно столько, сколько кризисов."""
    books = sorted(series_map)
    folds: List[dict] = []
    for i, held in enumerate(crises):
        train = [c for j, c in enumerate(crises) if j != i]
        vel = {b: velocity_on(CRP, series_map[b], train) for b in books}
        losses = {}
        for b in books:
            loss = crisis_loss(series_map[b], held)
            if loss is None:
                raise Unmeasured(f"окно {held['key']} отсутствует в ряде книги {b}")
            losses[b] = loss
        chosen = rank_top(vel, k, highest=True)
        best = rank_top(losses, k, highest=False)
        overlap = len(set(chosen) & set(best))
        folds.append({
            "held_out": held["key"],
            "train_crises": [c["key"] for c in train],
            "chosen_by_train_velocity": chosen,
            "best_in_held_out": best,
            "overlap": overlap,
            "exact_hit": overlap == k,
            "velocity_x1000": {b: (None if vel[b] == float("inf") else round(vel[b] * 1000, 3))
                               for b in books},
            "held_out_loss_pct": {b: round(losses[b] * 100, 2) for b in books},
        })
    return folds


def fixture_section(CRP, data_dir: Path) -> dict:
    books = list(CRP.ELIGIBLE_BOOKS)
    try:
        series_map = {b: CRP.load_backtest_series(data_dir, b) for b in books}
    except (OSError, ValueError, KeyError) as exc:
        raise Unmeasured(f"панель {data_dir} не прочитана прибором #153 — "
                         f"{type(exc).__name__}: {exc}") from exc
    empty = [b for b, s in series_map.items() if not s]
    if empty:
        raise Unmeasured(f"ряды пусты у книг {empty} — ответ о складках НЕ ВЫДАЁТСЯ")
    crises = list(CRP.CRISIS_WINDOWS)
    folds = loco_folds(CRP, series_map, crises)
    n = len(books)
    return {
        "books": books,
        "n_crises": len(crises),
        "n_folds": len(folds),
        "folds": folds,
        "exact_hits": sum(1 for f in folds if f["exact_hit"]),
        "overlaps": [f["overlap"] for f in folds],
        "mean_overlap": sum(f["overlap"] for f in folds) / len(folds) if folds else None,
        "expected_overlap_by_chance": expected_overlap(n, PAIR_SIZE),
        "generator_note": ("кризисы фикстуры — АВТОРСКИЕ числа window_hits одного генератора; "
                           "три складки = три проверки на одном генераторе, не три мира"),
    }


# ── (3) бюджет реальной панели ────────────────────────────────────────────────────────────

def read_backtest_block(panel_dir: Path, book: str) -> List[Tuple[datetime.date, float]]:
    path = panel_dir / book / "realized_series.jsonl"
    if not path.is_file():
        raise Unmeasured(f"ряда книги нет: {path}")
    out: List[Tuple[datetime.date, float]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("phase") != BACKTEST_PHASE:
                continue
            out.append((datetime.date.fromisoformat(row["date"]), float(row["equity_usd"])))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise Unmeasured(f"ряд {path} не разобран — {type(exc).__name__}: {exc}") from exc
    out.sort()
    return out


def drawdown_episodes(series: List[Tuple[datetime.date, float]], min_depth: float) -> List[dict]:
    """Эпизод = от первого дня ниже пика до возврата на пик; считается, если глубина ≥ min_depth.

    `new_lows` — дни, когда эпизод углублялся (новое дно): это фаза КРИЗИСА, а не всё
    время под водой. Открытый эпизод (не восстановился до конца блока) несёт end=None.
    """
    episodes: List[dict] = []
    peak: Optional[float] = None
    cur: Optional[dict] = None
    for d, e in series:
        if peak is None or e >= peak:
            if cur is not None:
                cur["end"] = d
                if cur["depth"] >= min_depth:
                    episodes.append(cur)
            cur = None
            peak = e
            continue
        dd = (peak - e) / peak
        if cur is None:
            cur = {"start": d, "end": None, "depth": dd, "trough": e, "new_lows": [d]}
        elif e < cur["trough"]:
            cur["trough"] = e
            cur["depth"] = dd
            cur["new_lows"].append(d)
    if cur is not None and cur["depth"] >= min_depth:
        episodes.append(cur)
    return episodes


def joint_episodes(per_book: Dict[str, List[dict]], min_books: int = JOINT_MIN_BOOKS,
                   gap_days: int = JOINT_GAP_DAYS) -> List[dict]:
    """Кластеры дат НОВЫХ МИНИМУМОВ, в которых углублялись не меньше min_books книг.

    «Под водой одновременно» кризисом не является: открытая просадка одной книги длиной в
    два года склеила бы всю панель в один эпизод. Кризис — это когда книги ПАДАЮТ вместе,
    то есть ставят новые минимумы в одни и те же дни (с зазором не больше gap_days)."""
    low_days: Dict[datetime.date, set] = {}
    for book, eps in per_book.items():
        for ep in eps:
            for d in ep["new_lows"]:
                low_days.setdefault(d, set()).add(book)
    clusters: List[dict] = []
    cur: Optional[dict] = None
    for d in sorted(low_days):
        if cur is not None and (d - cur["end"]).days > gap_days:
            clusters.append(cur)
            cur = None
        if cur is None:
            cur = {"start": d, "end": d, "books": set(low_days[d])}
        else:
            cur["end"] = d
            cur["books"] |= low_days[d]
    if cur is not None:
        clusters.append(cur)
    return [{"start": c["start"], "end": c["end"], "books": sorted(c["books"])}
            for c in clusters if len(c["books"]) >= min_books]


def panel_section(panel_dir: Path, toll_bps: float) -> dict:
    if not panel_dir.is_dir():
        raise Unmeasured(f"каталог панели не прочитан: {panel_dir}")
    books = sorted(p.name for p in panel_dir.iterdir()
                   if p.is_dir() and (p / "realized_series.jsonl").is_file())
    if not books:
        raise Unmeasured(f"в {panel_dir} нет ни одного ряда realized_series.jsonl")
    min_depth = toll_bps / 10_000.0
    per_book: Dict[str, List[dict]] = {}
    all_dates: set = set()
    block_span: Dict[str, Tuple[str, str, int]] = {}
    for b in books:
        ser = read_backtest_block(panel_dir, b)
        if not ser:
            raise Unmeasured(f"блок {BACKTEST_PHASE} пуст у книги {b}")
        per_book[b] = drawdown_episodes(ser, min_depth)
        all_dates.update(d for d, _ in ser)
        block_span[b] = (ser[0][0].isoformat(), ser[-1][0].isoformat(), len(ser))
    measurable = [b for b in books if per_book[b]]
    joint = joint_episodes(per_book)
    return {
        "panel_dir": str(panel_dir),
        "phase": BACKTEST_PHASE,
        "min_depth_bps": toll_bps,
        "books": books,
        "block_span": block_span,
        "episodes_per_book": {b: len(per_book[b]) for b in books},
        "measurable_books": measurable,
        "n_measurable_books": len(measurable),
        "joint_episodes": [{"start": j["start"].isoformat(), "end": j["end"].isoformat(),
                            "books": j["books"]} for j in joint],
        "n_joint_episodes": len(joint),
        "forward_note": ("forward-блок панели НЕ читается: наблюдений дневной марки в нём 0 из 10 "
                         "(#154), окном OOS он не является"),
    }


# ── отчёт ─────────────────────────────────────────────────────────────────────────────────

def build_report(fixture_dir: Optional[Path], panel_dir: Optional[Path]) -> dict:
    CRP = load_crp_module()
    toll = float(CRP.ENTRY_TOLL_BPS)
    tmp: Optional[tempfile.TemporaryDirectory] = None
    if fixture_dir is None:
        try:
            if str(_MODULE_ROOT) not in sys.path:
                sys.path.insert(0, str(_MODULE_ROOT))
            from spa_core.strategy_lab.aggressive_lab.fixtures import materialize
        except Exception as exc:  # noqa: BLE001
            raise Unmeasured(f"фикстура не ввезена: {type(exc).__name__}: {exc}") from exc
        tmp = tempfile.TemporaryDirectory(prefix="iob_fixture_")
        fixture_dir = materialize(Path(tmp.name))
    try:
        fixture = fixture_section(CRP, fixture_dir)
        arithmetic = arithmetic_section(len(fixture["books"]))
        panel = panel_section(panel_dir, toll) if panel_dir is not None else None
    finally:
        if tmp is not None:
            tmp.cleanup()

    need = arithmetic["min_folds_all_exact_hits"]
    have_fixture = fixture["n_folds"]
    verdict = {
        "folds_needed_all_exact_hits_at_alpha": need,
        "fixture_folds_available": have_fixture,
        "fixture_exact_hits": fixture["exact_hits"],
        "fixture_rule_survives_loco": fixture["exact_hits"] >= need,
        "panel_joint_episodes": None if panel is None else panel["n_joint_episodes"],
        "panel_measurable_books": None if panel is None else panel["n_measurable_books"],
        "answer": None,
    }
    if fixture["exact_hits"] < need:
        verdict["answer"] = (
            f"нужно ≥{need} независимых точных попаданий подряд (α={ALPHA}); фикстура даёт "
            f"{have_fixture} складки и {fixture['exact_hits']} точных попаданий — «отбор угадал» "
            f"в #155 было ОДНИМ швом, под складками оно не воспроизводится")
    else:
        verdict["answer"] = (
            f"правило выдержало {fixture['exact_hits']} из {have_fixture} складок при пороге {need} — "
            f"на ОДНОМ генераторе; независимым миром это не является")
    return {
        "idea": "#157 IOB — Independent-Observation Budget",
        "order": "#155 п. 1",
        "toll_bps": toll,
        "arithmetic": arithmetic,
        "fixture": fixture,
        "panel": panel,
        "verdict": verdict,
        "is_advisory": True,
        "outside_riskpolicy": True,
    }


def print_report(r: dict) -> None:
    a = r["arithmetic"]
    print("=== #157 IOB — бюджет независимых наблюдений (заказ #155 п. 1) ===")
    print(f"§1 арифметика: n={a['n_books']} книг, пара из {a['pair_size']}: "
          f"P(точная пара случайно)={a['p_exact_pair_by_chance']:.3f}, "
          f"P(пересечение ≥1)={a['p_overlap_ge1_by_chance']:.3f}, "
          f"E[пересечение]={a['expected_overlap_by_chance']:.2f}")
    print(f"   складок с ТОЧНЫМ попаданием подряд при α={a['alpha']}: {a['min_folds_all_exact_hits']}; "
          f"с пересечением ≥1: {a['min_folds_all_overlap_ge1']}")
    f = r["fixture"]
    print(f"§2 фикстура [bt]: кризисов {f['n_crises']} ⇒ складок {f['n_folds']}")
    for fold in f["folds"]:
        print(f"   держим {fold['held_out']:22s} выбор по TRAIN={fold['chosen_by_train_velocity']} "
              f"лучшие в удержанном={fold['best_in_held_out']} пересечение={fold['overlap']}")
    print(f"   точных попаданий {f['exact_hits']} из {f['n_folds']}; среднее пересечение "
          f"{f['mean_overlap']:.2f} против случайного {f['expected_overlap_by_chance']:.2f}")
    print(f"   {f['generator_note']}")
    p = r.get("panel")
    if p is None:
        print("§3 реальная панель: НЕ ИЗМЕРЕНО — каталог не назван (--panel-dir)")
    else:
        print(f"§3 реальная панель ({p['phase']}, глубина ≥{p['min_depth_bps']:.0f} bp): книг {len(p['books'])}, "
              f"измеримых {p['n_measurable_books']} {p['measurable_books']}")
        print(f"   эпизодов по книгам: {p['episodes_per_book']}")
        print(f"   СОВМЕСТНЫХ эпизодов (новые минимумы ≥{JOINT_MIN_BOOKS} книг, зазор ≤{JOINT_GAP_DAYS} дн): {p['n_joint_episodes']}")
        for j in p["joint_episodes"]:
            print(f"     {j['start']} .. {j['end']} {j['books']}")
        print(f"   {p['forward_note']}")
    print("ВЕРДИКТ:", r["verdict"]["answer"])
    print("IS_ADVISORY=True · OUTSIDE_RISKPOLICY=True · RiskPolicy v1.0 не тронута · живой трек не открыт")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="#157 IOB — бюджет независимых наблюдений (заказ #155 п. 1)")
    ap.add_argument("--fixture-dir", type=Path, default=None,
                    help="материализованная фикстура; по умолчанию материализуется во временный каталог")
    ap.add_argument("--panel-dir", type=Path, default=None,
                    help="реальная панель (data/aggressive_lab), только чтение")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        r = build_report(args.fixture_dir, args.panel_dir)
    except Unmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    else:
        print_report(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
