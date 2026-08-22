"""Protection Lab — фаза 7 v2: переборный adversarial-генератор с кластеризацией.

# LLM_FORBIDDEN

Задание владельца (фаза 7): «генератор, цель которого — найти слабости текущей
архитектуры защиты; тысячи правдоподобных комбинаций; похожие отказы кластеризовать
в семейства, а не вываливать тысячи почти одинаковых случаев».

Устройство:
1. **Сетка** — детерминированное перечисление шок-шаблонов по семействам
   (депеги, кредитные потери, заморозки/остановки, ликвидность) + все парные
   комбинации шаблонов из РАЗНЫХ семейств. Никакой случайности: одна сетка —
   всегда один и тот же список сценариев (Monte-Carlo живёт отдельно,
   `backtesting/tier1/monte_carlo.py`, и здесь не дублируется).
2. **Прогон** — каждый сценарий идёт через ТОТ ЖЕ `run_replay` (пороги из
   governance, no-look-ahead, execution-aware) — второй математики нет.
3. **Кластеризация** — детерминированная, по СИГНАТУРЕ ОТКАЗА, а не по метрике
   расстояния: (класс вердикта · когда увидена опасность · были ли отказы
   исполнения · ведро глубины просадки · семейства шоков). Похожие отказы
   складываются в семью; экземпляр семьи — худший по просадке защиты.

Что этот перебор НЕ делает (названо, не спрятано): не подбирает пороги под
библиотеку (запрещено заданием), не оптимизирует «красоту» — его выход это
СПИСОК СЛАБОСТЕЙ, отсортированный по ущербу.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from spa_core.governance.kill_switch import TIER_NONE  # noqa: F401  (семантика ниже)

from .replay import BookPosition, ProtectionReport, run_replay
from .synthetic import DepegSpec, SyntheticSpec, build_synthetic_scenario

DURATION_DAYS = 30

# ── Шаблоны шоков по семействам ───────────────────────────────────────────────
# Каждый шаблон: (family, label, dict-фрагмент SyntheticSpec)

def _depeg_templates() -> List[Tuple[str, str, dict]]:
    out: List[Tuple[str, str, dict]] = []
    for symbol in ("USDC", "PT_USDC"):
        for floor in (0.95, 0.88, 0.80, 0.65):
            for rec_label, rec_day in (("norec", None), ("fast", 8), ("slow", 20)):
                out.append((
                    "depeg",
                    f"depeg:{symbol}@{floor:.2f}:{rec_label}",
                    {"depegs": [DepegSpec(symbol, floor, start_day=1,
                                          trough_day=3, recovery_day=rec_day)]},
                ))
    return out


def _credit_templates() -> List[Tuple[str, str, dict]]:
    out: List[Tuple[str, str, dict]] = []
    for protocol in ("maple", "morpho_steakhouse", "aave_v3"):
        for loss in (0.10, 0.30, 0.60):
            for day in (2, 12):
                out.append((
                    "credit",
                    f"loss:{protocol}@{loss:.0%}:d{day}",
                    {"capital_losses": [{"protocol": protocol, "day": day,
                                         "loss_pct": loss}]},
                ))
    return out


def _freeze_templates() -> List[Tuple[str, str, dict]]:
    out: List[Tuple[str, str, dict]] = []
    for protocol in ("maple", "aave_v3", "morpho_steakhouse", "pendle"):
        for dur, halt in ((3, False), (10, False), (25, False), (10, True)):
            out.append((
                "freeze",
                f"{'halt' if halt else 'freeze'}:{protocol}:{dur}d",
                {"freezes": [{"protocol": protocol, "from_day": 1,
                              "to_day": min(1 + dur, DURATION_DAYS - 1),
                              "halt": halt}]},
            ))
    return out


def _liquidity_templates() -> List[Tuple[str, str, dict]]:
    out: List[Tuple[str, str, dict]] = []
    for haircut, gas in ((0.02, 150.0), (0.05, 400.0)):
        out.append((
            "liquidity",
            f"liq:{haircut:.0%}",
            {"liquidity": {"from_day": 1, "to_day": 10,
                           "exit_haircut_pct": haircut, "gas_cost_usd": gas}},
        ))
    return out


def _merge_fragments(base: dict, frag: dict) -> dict:
    merged = dict(base)
    for key, val in frag.items():
        if isinstance(val, list):
            merged[key] = list(merged.get(key, [])) + list(val)
        else:
            merged[key] = val
    return merged


def generate_grid() -> List[Tuple[str, List[str], SyntheticSpec]]:
    """Сетка: одиночные шаблоны + все пары шаблонов из разных семейств.

    Возвращает [(spec_id, [families], SyntheticSpec)] — детерминированно.
    """
    templates = (_depeg_templates() + _credit_templates()
                 + _freeze_templates() + _liquidity_templates())
    combos: List[Tuple[str, List[str], SyntheticSpec]] = []

    def build(labels: List[str], families: List[str], frags: List[dict]):
        fields: dict = {}
        for frag in frags:
            fields = _merge_fragments(fields, frag)
        sid = "ADV_" + "+".join(labels)
        spec = SyntheticSpec(
            name=sid,
            description="adversarial-сетка: " + " + ".join(labels),
            duration_days=DURATION_DAYS,
            assumptions=["adversarial-перебор (фаза 7 v2): параметры сетки, не факты"],
            **fields,
        )
        combos.append((sid, families, spec))

    for fam, label, frag in templates:
        build([label], [fam], [frag])
    for i, (fam_a, lab_a, frag_a) in enumerate(templates):
        for fam_b, lab_b, frag_b in templates[i + 1:]:
            if fam_a == fam_b:
                continue  # внутрисемейные пары почти дубли — режем комбинаторику
            build([lab_a, lab_b], sorted({fam_a, fam_b}), [frag_a, frag_b])
    return combos


# ── Сигнатура отказа и семейства ─────────────────────────────────────────────


@dataclass
class Failure:
    spec_id: str
    families: List[str]
    report: ProtectionReport


@dataclass
class Family:
    signature: Tuple
    members: List[Failure] = field(default_factory=list)

    @property
    def exemplar(self) -> Failure:
        return max(self.members, key=lambda f: f.report.protected.max_drawdown_pct)

    @property
    def worst_dd(self) -> float:
        return self.exemplar.report.protected.max_drawdown_pct


def _dd_bucket(dd: float) -> str:
    if dd >= 10.0:
        return "hard"
    if dd >= 5.0:
        return "soft"
    if dd >= 2.0:
        return "notable"
    return "minor"


def _det_bucket(det: Optional[int]) -> str:
    if det is None:
        return "never"
    return "early" if det <= 4 else "late"


def signature(f: Failure) -> Tuple:
    r = f.report
    verdict = ("uncovered" if (r.benchmark_loss_usd > 0.02 * r.capital_usd
                               and r.detection_day is None)
               else "unexecutable" if r.protected.execution_failures
               else "costly" if r.capital_saved_usd < -100
               else "quiet" if r.capital_saved_usd == 0 and r.detection_day is None
               else "worked")
    return (verdict,
            _det_bucket(r.detection_day),
            bool(r.protected.execution_failures),
            _dd_bucket(r.protected.max_drawdown_pct),
            tuple(f.families))


def run_sweep(
    book: Optional[List[BookPosition]] = None,
    capital_usd: float = 100_000.0,
    grid: Optional[Iterable[Tuple[str, List[str], SyntheticSpec]]] = None,
) -> Dict[Tuple, Family]:
    """Прогнать сетку и сложить результаты в семейства по сигнатуре отказа."""
    families: Dict[Tuple, Family] = {}
    for sid, fams, spec in (grid if grid is not None else generate_grid()):
        scenario = build_synthetic_scenario(spec)
        report = run_replay(scenario, book=book, capital_usd=capital_usd)
        failure = Failure(spec_id=sid, families=fams, report=report)
        sig = signature(failure)
        families.setdefault(sig, Family(signature=sig)).members.append(failure)
    return families


def format_sweep_report(families: Dict[Tuple, Family], top: int = 15) -> str:
    """Семейства по убыванию ущерба; экземпляр — худший в семье."""
    ordered = sorted(families.values(), key=lambda fam: -fam.worst_dd)
    total = sum(len(f.members) for f in ordered)
    lines = [
        "═══ Adversarial sweep (фаза 7 v2) ═══",
        f"Комбинаций прогнано: {total} · семейств отказов: {len(ordered)}",
        "",
        f"{'сигнатура (вердикт·увидена·отказ-исп·DD·семейства)':<64}{'n':>5}"
        f"{'worst DD%':>11}{'экземпляр':>40}",
    ]
    for fam in ordered[:top]:
        sig = fam.signature
        sig_str = f"{sig[0]}·{sig[1]}·{'fail' if sig[2] else 'ok'}·{sig[3]}·{'+'.join(sig[4])}"
        ex = fam.exemplar
        lines.append(f"{sig_str:<64}{len(fam.members):>5}"
                     f"{fam.worst_dd:>11.2f}{ex.spec_id[:40]:>40}")
    if len(ordered) > top:
        lines.append(f"… ещё {len(ordered) - top} семейств (полный отчёт — JSON)")
    lines.append("")
    worst = ordered[0] if ordered else None
    if worst is not None:
        ex = worst.exemplar.report
        lines.append(
            f"Худшая слабость: {worst.exemplar.spec_id} — защита DD "
            f"{ex.protected.max_drawdown_pct:.2f}% (пассив {ex.benchmark.max_drawdown_pct:.2f}%), "
            f"saved {ex.capital_saved_usd:+,.0f}$, обнаружение "
            f"{'никогда' if ex.detection_day is None else 'день ' + str(ex.detection_day)}")
    return "\n".join(lines) + "\n"


def families_to_dict(families: Dict[Tuple, Family]) -> dict:
    """JSON-представление для отчёта (CLI пишет через atomic_save)."""
    out = []
    for fam in sorted(families.values(), key=lambda f: -f.worst_dd):
        ex = fam.exemplar
        out.append({
            "signature": list(map(str, fam.signature)),
            "count": len(fam.members),
            "worst_dd_pct": round(fam.worst_dd, 4),
            "exemplar": {
                "spec_id": ex.spec_id,
                "prot_final": ex.report.protected.final_equity,
                "bench_final": ex.report.benchmark.final_equity,
                "saved": ex.report.capital_saved_usd,
                "detection_day": ex.report.detection_day,
                "execution_failures": len(ex.report.protected.execution_failures),
            },
            "member_ids": sorted(m.spec_id for m in fam.members)[:50],
        })
    return {"families": out,
            "total_combos": sum(len(f.members) for f in families.values())}
