"""Allocation Auditor: соответствует ли СЕГОДНЯШНЯЯ книга записанной политике?

# LLM_FORBIDDEN

Задача AI1-1.1. Вопрос, на который до сих пор не отвечал ни один сторож.

``RiskPolicy.check_new_position`` судит СДЕЛКУ в момент входа и после этого молчит;
книга дрейфует за потолки сама — от изменения цен, доходностей и тиров, — и заметить
это некому. ``check_portfolio_health`` смотрит на здоровье, а не на соответствие
правилам. ``deployment_acceptance`` отвечает «способен ли флот стартовать».
Ни один не отвечает: **не разошлась ли книга с правилами, записанными в
``docs/allocation_logic_explicit.md``**.

Каждая находка ссылается на ID правила ИЗ ТОГО ЖЕ документа, а числа берутся из
``RiskConfig`` — то есть аудитор и документ не могут разъехаться молча
(``spa_core/tests/test_allocation_logic_explicit.py`` держит вторую половину связи).

Три исхода, а не два. «Не измерено» — самостоятельный вердикт ``UNCHECKED``
с названной причиной, и он НИКОГДА не схлопывается в «нарушений нет»: сторож,
у которого нет третьего исхода, отвечает «всё в порядке» на отсутствие данных
(инвариант 2, fail-CLOSED).

Аудитор ничего не двигает. Он читает и сообщает. Капитал, RiskPolicy, kill-switch,
флот — не его дело; он не импортирует ``spa_core/execution/``.

Только stdlib. Атомарная запись. Часы и все пути инъектируются.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from spa_core.risk.policy import RiskConfig
from spa_core.utils.atomic import atomic_save

#: Контракт агента (ADR-154/158): что этот агент ПРОИЗВОДИТ.
#: Объявление, а не вывод из кода.
PRODUCES = (
    "data/allocation_audit_daily.json",
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_POSITIONS_PATH = _REPO_ROOT / "data" / "current_positions.json"
_ORCHESTRATOR_PATH = _REPO_ROOT / "data" / "adapter_orchestrator_status.json"
_DEFAULT_OUT = _REPO_ROOT / "data" / "allocation_audit_daily.json"

OK = "OK"
VIOLATION = "VIOLATION"
UNCHECKED = "UNCHECKED"

_L2_CHAINS = {"arbitrum", "base", "optimism"}
_EPS = 1e-9


@dataclass(frozen=True)
class Finding:
    """Один ответ на одно правило. ``observed``/``limit`` — доли капитала."""
    rule_id: str
    verdict: str
    subject: str
    detail: str
    observed: Optional[float] = None
    limit: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AuditResult:
    generated_at: str
    verdict: str = UNCHECKED
    book_as_of: Optional[str] = None
    capital_usd: Optional[float] = None
    findings: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["findings"] = [f.to_dict() if isinstance(f, Finding) else f for f in self.findings]
        return d


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def _read_json(path: Path) -> tuple[Optional[dict], Optional[str]]:
    """JSON-объект или (None, причина). Никогда не бросает — причина есть всегда."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"файла нет: {path}"
    except Exception as exc:  # noqa: BLE001 — вход из мира, причина важнее типа
        return None, f"нечитаемый {path}: {exc}"
    if not isinstance(doc, dict):
        return None, f"{path}: валидный JSON, но не объект ({type(doc).__name__})"
    return doc, None


def _finite_positive(v: object) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) and f > 0 else None


def _canonical_tier(protocol: str) -> Optional[str]:
    """Канонический тир или None, если сказать нечем (fail-CLOSED, не 'T2 по умолчанию')."""
    try:
        from spa_core.adapters.tier_map import tier_of
        t = tier_of(protocol)
    except Exception:  # noqa: BLE001 — недоступная карта тиров = «не измерено»
        return None
    if not isinstance(t, str) or not t.strip():
        return None
    return t.strip().upper()


class AllocationAuditor:
    """Ежедневная сверка книги с ``docs/allocation_logic_explicit.md``."""

    def __init__(
        self,
        positions_path: os.PathLike | str | None = None,
        orchestrator_path: os.PathLike | str | None = None,
        config: Optional[RiskConfig] = None,
        chain_map_provider: Optional[Callable[[], dict]] = None,
        tier_provider: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        self.positions_path = Path(positions_path) if positions_path else _POSITIONS_PATH
        self.orchestrator_path = Path(orchestrator_path) if orchestrator_path else _ORCHESTRATOR_PATH
        self.config = config or RiskConfig()
        self._chain_map_provider = chain_map_provider
        self._tier_provider = tier_provider or _canonical_tier

    # ── входы ────────────────────────────────────────────────────────────
    def _chain_map(self) -> tuple[dict, Optional[str]]:
        try:
            if self._chain_map_provider is not None:
                m = self._chain_map_provider()
            else:
                from spa_core.risk.chain_limits import get_default_chain_map
                m = get_default_chain_map()
        except Exception as exc:  # noqa: BLE001
            return {}, f"карта цепочек недоступна: {exc}"
        if not isinstance(m, dict):
            return {}, f"карта цепочек не отображение ({type(m).__name__})"
        return m, None

    def _declared_tiers(self) -> tuple[dict, Optional[str]]:
        """``{protocol: tier}`` из снимка оркестратора — ВТОРОЕ объявление тира."""
        doc, err = _read_json(self.orchestrator_path)
        if err:
            return {}, err
        rows = doc.get("adapters")
        if isinstance(rows, dict):
            rows = list(rows.values())
        if not isinstance(rows, list):
            return {}, f"{self.orchestrator_path}: нет списка adapters"
        out: dict[str, str] = {}
        for r in rows:
            if isinstance(r, dict) and isinstance(r.get("protocol"), str) \
                    and isinstance(r.get("tier"), str):
                out[r["protocol"]] = r["tier"].strip().upper()
        return out, None

    def _tvl_sources(self) -> tuple[dict, Optional[str]]:
        doc, err = _read_json(self.orchestrator_path)
        if err:
            return {}, err
        rows = doc.get("adapters")
        if isinstance(rows, dict):
            rows = list(rows.values())
        if not isinstance(rows, list):
            return {}, f"{self.orchestrator_path}: нет списка adapters"
        return {
            r["protocol"]: r.get("tvl_source")
            for r in rows
            if isinstance(r, dict) and isinstance(r.get("protocol"), str)
        }, None

    # ── проверки ─────────────────────────────────────────────────────────
    def _cap_for(self, tier: Optional[str]) -> Optional[float]:
        if tier == "T1":
            return self.config.max_concentration_t1
        if tier in ("T2", "T3"):
            return self.config.max_concentration_t2
        return None

    def _check_concentration(self, shares: dict, tiers: dict) -> list[Finding]:
        out: list[Finding] = []
        for proto in sorted(shares):
            tier = tiers.get(proto)
            cap = self._cap_for(tier)
            if cap is None:
                out.append(Finding(
                    "CAP-01/02", UNCHECKED, proto,
                    "тир протокола не установлен — потолок 40 % или 20 % назвать нечем; "
                    "подстановка «по умолчанию T2» запрещена (занижает концентрацию)",
                    observed=shares[proto],
                ))
                continue
            rule = "CAP-01" if tier == "T1" else "CAP-02"
            over = shares[proto] > cap + _EPS
            out.append(Finding(
                rule, VIOLATION if over else OK, proto,
                f"{tier}: доля {shares[proto]:.1%} против потолка {cap:.0%}"
                + (" — ПРЕВЫШЕН" if over else ""),
                observed=round(shares[proto], 6), limit=cap,
            ))
        return out

    def _check_tier_totals(self, shares: dict, tiers: dict) -> list[Finding]:
        out: list[Finding] = []
        unknown = sorted(p for p in shares if tiers.get(p) not in ("T1", "T2", "T3"))
        for rule, want, cap in (
            ("CAP-04", "T2", self.config.max_total_t2_allocation),
            ("CAP-05", "T3", self.config.max_total_t3_allocation),
        ):
            total = sum(v for p, v in shares.items() if tiers.get(p) == want)
            if unknown:
                out.append(Finding(
                    rule, UNCHECKED, f"{want} совокупно",
                    f"тир неизвестен у {unknown} — совокупная доля {want} не может быть "
                    f"названа: неучтённый протокол занижает её молча",
                    observed=round(total, 6), limit=cap,
                ))
                continue
            over = total > cap + _EPS
            out.append(Finding(
                rule, VIOLATION if over else OK, f"{want} совокупно",
                f"{total:.1%} против потолка {cap:.0%}" + (" — ПРЕВЫШЕН" if over else ""),
                observed=round(total, 6), limit=cap,
            ))
        return out

    def _check_count(self, shares: dict) -> Finding:
        n = len([p for p, v in shares.items() if v > 0])
        lim = int(self.config.max_protocols)
        return Finding(
            "CAP-06", VIOLATION if n > lim else OK, "книга",
            f"профинансировано {n} протоколов против потолка {lim} (ALLOC-002)",
            observed=float(n), limit=float(lim),
        )

    def _check_cash(self, cash_pct: Optional[float]) -> Finding:
        floor = self.config.min_cash_pct
        if cash_pct is None:
            return Finding("CAP-08", UNCHECKED, "кэш",
                           "денежный буфер не вычисляется: нет капитала или размещённой суммы",
                           limit=floor)
        low = cash_pct < floor - _EPS
        return Finding(
            "CAP-08", VIOLATION if low else OK, "кэш",
            f"буфер {cash_pct:.1%} против пола {floor:.0%}" + (" — НИЖЕ ПОЛА" if low else ""),
            observed=round(cash_pct, 6), limit=floor,
        )

    def _check_chains(self, shares: dict) -> list[Finding]:
        chain_map, err = self._chain_map()
        if err:
            return [Finding("CAP-13/14", UNCHECKED, "цепочки", err)]
        unknown = sorted(p for p in shares if not chain_map.get(p))
        if unknown:
            return [Finding(
                "CAP-13/14", UNCHECKED, "цепочки",
                f"цепочка не объявлена у {unknown} — потолки «одна цепочка ≤ 90 %» и "
                f"«L2 ≤ 50 %» посчитать нечем; подстановка ethereum была бы выдумкой",
            )]
        by_chain: dict[str, float] = {}
        for proto, share in shares.items():
            by_chain[str(chain_map[proto]).lower()] = \
                by_chain.get(str(chain_map[proto]).lower(), 0.0) + share
        out: list[Finding] = []
        cap = self.config.max_single_chain_allocation
        for chain in sorted(by_chain):
            over = by_chain[chain] > cap + _EPS
            out.append(Finding(
                "CAP-13", VIOLATION if over else OK, chain,
                f"{by_chain[chain]:.1%} на цепочке против потолка {cap:.0%}"
                + (" — ПРЕВЫШЕН" if over else ""),
                observed=round(by_chain[chain], 6), limit=cap,
            ))
        l2 = sum(v for c, v in by_chain.items() if c in _L2_CHAINS)
        l2_cap = self.config.max_l2_total_allocation
        out.append(Finding(
            "CAP-14", VIOLATION if l2 > l2_cap + _EPS else OK, "L2 совокупно",
            f"{l2:.1%} против потолка {l2_cap:.0%}",
            observed=round(l2, 6), limit=l2_cap,
        ))
        return out

    def _check_class_gate(self, shares: dict) -> list[Finding]:
        try:
            from spa_core.allocator.allocator import _adapter_class_gate
        except Exception as exc:  # noqa: BLE001
            return [Finding("ADM-05/06", UNCHECKED, "классовый гейт",
                            f"гейт недоступен: {exc}")]
        out: list[Finding] = []
        for proto in sorted(shares):
            try:
                allowed, reason = _adapter_class_gate(proto)
            except Exception as exc:  # noqa: BLE001
                out.append(Finding("ADM-05/06", UNCHECKED, proto,
                                   f"гейт бросил исключение: {exc}"))
                continue
            out.append(Finding(
                "ADM-05/06", OK if allowed else VIOLATION, proto,
                "допущен к финансированию" if allowed
                else f"НЕ ДОПУЩЕН к финансированию ({reason}), но держит {shares[proto]:.1%}",
                observed=round(shares[proto], 6),
            ))
        return out

    def _check_tvl_evidence(self, shares: dict) -> list[Finding]:
        sources, err = self._tvl_sources()
        if err:
            return [Finding("ADM-07/08", UNCHECKED, "живой TVL", err)]
        out: list[Finding] = []
        for proto in sorted(shares):
            src = sources.get(proto)
            if src is None:
                out.append(Finding("ADM-07/08", UNCHECKED, proto,
                                   "протокола нет в снимке оркестратора — источник TVL неизвестен"))
            elif src != "live":
                out.append(Finding(
                    "ADM-07/08", VIOLATION, proto,
                    f"TVL-источник «{src}», не live: пол $5M на литерале НЕ верифицирован "
                    f"(ADR-053), а протокол держит {shares[proto]:.1%}",
                    observed=round(shares[proto], 6)))
            else:
                out.append(Finding("ADM-07/08", OK, proto, "TVL наблюдается живым фидом"))
        return out

    def _check_below_median(self, usd: dict, apy: dict, capital: Optional[float],
                            tiers: dict) -> list[Finding]:
        if capital is None:
            return [Finding("ECON-10", UNCHECKED, "книга", "капитал неизвестен")]
        priced = {p: apy[p] for p in usd if p in apy}
        if len(priced) < 3:
            return [Finding("ECON-10", UNCHECKED, "книга",
                            f"доходность известна у {len(priced)} пулов из {len(usd)} — "
                            f"медиана по менее чем трём это шум, не сигнал")]
        try:
            from spa_core.allocator.rebalance_economics import below_median_cap_violations
            caps = {p: self._cap_for(tiers.get(p)) or 0.0 for p in usd}
            rows = below_median_cap_violations(
                positions=usd, apy_pct=apy, tier_caps=caps,
                capital_usd=capital, evidenced=set(priced),
            )
        except Exception as exc:  # noqa: BLE001
            return [Finding("ECON-10", UNCHECKED, "книга", f"проверка недоступна: {exc}")]
        if not rows:
            return [Finding("ECON-10", OK, "книга",
                            "нет протокола с доходностью ниже медианы, занимающего "
                            "больше половины своего тир-потолка")]
        return [Finding(
            "ECON-10", VIOLATION, r["protocol"],
            f"доходность {r['apy_pct']:.2f} % ниже медианы {r['median_apy_pct']:.2f} %, "
            f"а доля {r['share']:.1%} больше половины тир-потолка ({r['allowed_share']:.1%})",
            observed=r["share"], limit=r["allowed_share"],
        ) for r in rows]

    def _check_tier_agreement(self, shares: dict, canonical: dict) -> list[Finding]:
        """ДВА объявления тира на один протокол — расхождение двигает потолок вдвое."""
        declared, err = self._declared_tiers()
        if err:
            return [Finding("TIER-01", UNCHECKED, "объявления тира", err)]
        out: list[Finding] = []
        for proto in sorted(shares):
            a, b = canonical.get(proto), declared.get(proto)
            if a is None or b is None:
                out.append(Finding("TIER-01", UNCHECKED, proto,
                                   f"сравнивать нечем: канон={a!r}, снимок={b!r}"))
            elif a != b:
                out.append(Finding(
                    "TIER-01", VIOLATION, proto,
                    f"тир объявлен ДВАЖДЫ и по-разному: канон tier_map={a}, "
                    f"снимок оркестратора={b}. Потолок протокола зависит от того, кого "
                    f"читать ({self._cap_for(a):.0%} против {self._cap_for(b):.0%}), "
                    f"и совокупные доли тиров разъезжаются вместе с ним",
                    observed=round(shares[proto], 6)))
            else:
                out.append(Finding("TIER-01", OK, proto, f"оба источника говорят {a}"))
        return out

    # ── прогон ───────────────────────────────────────────────────────────
    def audit(self, now: Optional[datetime] = None) -> AuditResult:
        res = AuditResult(generated_at=_now(now).isoformat())

        book, err = _read_json(self.positions_path)
        if err:
            res.findings.append(Finding("BOOK", UNCHECKED, "книга", err))
            return self._finalize(res)

        res.book_as_of = book.get("generated_at") if isinstance(book.get("generated_at"), str) else None
        capital = _finite_positive(book.get("capital_usd"))
        res.capital_usd = capital
        positions = book.get("positions")
        if not isinstance(positions, dict):
            res.findings.append(Finding("BOOK", UNCHECKED, "книга",
                                        "в снимке нет объекта positions"))
            return self._finalize(res)
        if capital is None:
            res.findings.append(Finding("BOOK", UNCHECKED, "книга",
                                        f"capital_usd не положительное число: "
                                        f"{book.get('capital_usd')!r} — доли не вычисляются"))
            return self._finalize(res)

        usd: dict[str, float] = {}
        for proto, v in positions.items():
            amount = _finite_positive(v)
            if amount is None:
                if isinstance(v, (int, float)) and not isinstance(v, bool) \
                        and math.isfinite(float(v)) and float(v) == 0.0:
                    continue   # ноль — это не позиция
                res.findings.append(Finding("BOOK", UNCHECKED, str(proto),
                                            f"нечисловая/нефинитная сумма: {v!r}"))
                continue
            usd[str(proto)] = amount

        shares = {p: v / capital for p, v in usd.items()}
        tiers = {p: self._tier_provider(p) for p in usd}

        detail = book.get("positions_detail")
        apy: dict[str, float] = {}
        if isinstance(detail, dict):
            for proto, row in detail.items():
                if isinstance(row, dict):
                    a = row.get("apy_pct")
                    if isinstance(a, (int, float)) and not isinstance(a, bool) \
                            and math.isfinite(float(a)):
                        apy[str(proto)] = float(a)

        deployed = sum(usd.values())
        cash_pct = (capital - deployed) / capital

        res.findings += self._check_concentration(shares, tiers)
        res.findings += self._check_tier_totals(shares, tiers)
        res.findings.append(self._check_count(shares))
        res.findings.append(self._check_cash(cash_pct))
        res.findings += self._check_chains(shares)
        res.findings += self._check_class_gate(shares)
        res.findings += self._check_tvl_evidence(shares)
        res.findings += self._check_below_median(usd, apy, capital, tiers)
        res.findings += self._check_tier_agreement(shares, tiers)
        return self._finalize(res)

    @staticmethod
    def _finalize(res: AuditResult) -> AuditResult:
        counts = {OK: 0, VIOLATION: 0, UNCHECKED: 0}
        for f in res.findings:
            counts[f.verdict] = counts.get(f.verdict, 0) + 1
        res.counts = counts
        # Порядок намеренный: нарушение важнее «не измерено», но «не измерено»
        # НИКОГДА не схлопывается в OK — иначе сторож отвечает «всё в порядке»
        # на отсутствие данных.
        if counts[VIOLATION]:
            res.verdict = VIOLATION
        elif counts[UNCHECKED]:
            res.verdict = UNCHECKED
        elif counts[OK]:
            res.verdict = OK
        else:
            res.verdict = UNCHECKED   # ноль проверок — это не чистый проход
        return res

    def save(self, res: AuditResult, out_path: os.PathLike | str | None = None) -> Path:
        p = Path(out_path) if out_path else _DEFAULT_OUT
        atomic_save(res.to_dict(), str(p))
        return p


_EXIT = {OK: 0, UNCHECKED: 1, VIOLATION: 2}


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Allocation Auditor — сверка книги с политикой")
    ap.add_argument("--positions", default=None)
    ap.add_argument("--orchestrator", default=None)
    ap.add_argument("--out", default=None, help="куда писать артефакт (по умолчанию data/)")
    ap.add_argument("--no-write", action="store_true", help="ничего не писать, только отчёт")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    res = AllocationAuditor(positions_path=a.positions, orchestrator_path=a.orchestrator).audit()
    if not a.no_write:
        self_path = AllocationAuditor().save(res, a.out)
    else:
        self_path = None

    if a.json:
        print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"Allocation Auditor — {res.verdict} "
              f"(нарушений {res.counts.get(VIOLATION, 0)}, "
              f"не измерено {res.counts.get(UNCHECKED, 0)}, "
              f"в норме {res.counts.get(OK, 0)}); книга от {res.book_as_of}")
        for f in res.findings:
            if f.verdict != OK:
                print(f"  [{f.verdict}] {f.rule_id} · {f.subject}: {f.detail}")
        if self_path:
            print(f"артефакт: {self_path}")
    return _EXIT.get(res.verdict, 1)


if __name__ == "__main__":
    raise SystemExit(main())
