#!/usr/bin/env python3
"""Генератор данных страницы /protection-lab для сайта.

Единственный источник чисел — движок Protection Lab (ADR-120): скрипт прогоняет
библиотеку и adversarial-набор и пишет `landing/src/data/protection_lab.json`.
Руками числа в JSON не вносятся НИКОГДА — правка чисел = перегенерация.

Проводка (иначе храповик неподключённых скриптов прав, что скрипт мёртв): режим
`--check` в `.github/workflows/generated-docs-integrity.yml` краснеет, если
закоммиченный JSON разошёлся с выводом движка — то есть если кто-то правил числа
руками или менял сценарии/движок, не перегенерировав страницу.

Запуск:
    python3 scripts/build_protection_lab_site_data.py           # записать JSON
    python3 scripts/build_protection_lab_site_data.py --check   # только сверить (CI)
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from spa_core.stress.protection_lab import (  # noqa: E402
    build_synthetic_scenario,
    load_all_scenarios,
    run_replay,
)
from spa_core.stress.protection_lab.synthetic import ADVERSARIAL_SPECS  # noqa: E402

OUT = REPO / "landing" / "src" / "data" / "protection_lab.json"

# Короткие двуязычные тексты для сайта (копирайт-слой; факты — в датасете репо).
COPY = {
    "H03_covid_black_thursday_2020": {
        "en": ("COVID Black Thursday", "BTC −52% and ETH −55% in ~26 hours; gas at 200–400 gwei; "
               "MakerDAO auctions cleared at zero bids. Stablecoin pegs held."),
        "ru": ("COVID · Чёрный четверг", "BTC −52% и ETH −55% за ~26 часов; gas 200–400 gwei; "
               "аукционы MakerDAO уходили по нулевым ставкам. Пеги стейблов держали."),
        "note_en": "None of today's venues existed in 2020 — mapped to period analogs, assumptions documented per scenario.",
        "note_ru": "Площадок книги в 2020 не существовало — маппинг на аналоги эпохи, допущения записаны в сценарии.",
    },
    "H04_may_2021_cascade": {
        "en": ("May 2021 cascade", "BTC −30% intraday, $8–9B liquidated in 24h, >60% of futures "
               "open interest destroyed. Pegs held — a pure market-crash control."),
        "ru": ("Каскад 19 мая 2021", "BTC −30% за день, $8–9B ликвидаций за сутки, >60% открытого "
               "интереса уничтожено. Пеги держали — чистый контроль «рыночный крах»."),
        "note_en": "A stable-denominated book sails through price crashes; the damage channel is future yield, not NAV.",
        "note_ru": "Стейбл-книга проходит ценовые крахи; канал урона — будущая доходность, не NAV.",
    },
    "H05_terra_ust_luna_2022": {
        "en": ("Terra / UST / LUNA", "UST $1→$0.10, LUNA −99.99%, ~$50B destroyed in days. USDC held "
               "with a premium. This book never touched UST — refusal-first whitelisting."),
        "ru": ("Terra / UST / LUNA", "UST $1→$0.10, LUNA −99.99%, ~$50B за считанные дни. USDC держал "
               "пег с премией. Книга не касалась UST — вайтлист, refusal-first."),
        "note_en": "Anchor's 19.5% would have passed a <30% APY cap — the whitelist, not thresholds, was the protection.",
        "note_ru": "Anchor с 19.5% прошёл бы APY-порог <30% — защитой был вайтлист, а не пороги.",
    },
    "H06_celsius_3ac_stETH_june_2022": {
        "en": ("Celsius / 3AC / stETH", "Nine weeks of hidden leverage unwinding: Celsius froze, 3AC "
               "defaulted, stETH traded at a 7–8% discount. Blue-chip DeFi took zero bad debt."),
        "ru": ("Celsius / 3AC / stETH", "Девять недель вскрытия скрытого плеча: Celsius заморозил "
               "выводы, 3AC дефолтнул, stETH торговался с дисконтом 7–8%. Blue-chip DeFi — ноль bad debt."),
        "note_en": "Damage came through credit, liquidity and freezes — channels a USDC=1 model cannot see.",
        "note_ru": "Урон шёл через кредит, ликвидность и заморозки — каналы, которых модель USDC=1 не видит.",
    },
    "H07_ftx_november_2022": {
        "en": ("FTX collapse", "A $6B bank run in 72 hours; BTC −24%. On-chain DeFi worked while CeFi "
               "froze. The tail for this book: Orthogonal's default in Maple on day 33 — no price signal."),
        "ru": ("Крах FTX", "Bank run $6B за 72 часа; BTC −24%. On-chain DeFi работал, CeFi замерз. "
               "Хвост для книги: дефолт Orthogonal в Maple на 33-й день — без ценового сигнала."),
        "note_en": "Models a diversified Maple loss (−30%); the concentrated single-pool reality is scenario H13.",
        "note_ru": "Моделирует диверсифицированную потерю Maple (−30%); концентрированная реальность одного пула — сценарий H13.",
    },
    "H08_usdc_svb_depeg_2023": {
        "en": ("USDC depeg (SVB)", "USDC $1→$0.87 in ~4 hours after Circle's SVB disclosure; repegged "
               "in ~65 hours. The one historical depeg of this book's own cash asset."),
        "ru": ("Депег USDC (SVB)", "USDC $1→$0.87 за ~4 часа после раскрытия Circle про SVB; пег "
               "вернулся за ~65 часов. Единственный исторический депег кэш-актива книги."),
        "note_en": "Protection sells the bottom and pays exit costs while cash IS USDC — passive holding beat it. Shown as-is.",
        "note_ru": "Защита продаёт на дне и платит за выход, а кэш — тот же USDC; пассив оказался лучше. Показано как есть.",
    },
    "H09_curve_vyper_july_2023": {
        "en": ("Curve / Vyper exploit", "~$70M drained via a compiler bug; Curve TVL −47%. The systemic "
               "near-miss: CRV-backed loans on Aave almost socialized bad debt onto USDC suppliers."),
        "ru": ("Взлом Curve / Vyper", "~$70M через баг компилятора; TVL Curve −47%. Системный near-miss: "
               "CRV-займы на Aave едва не социализировали bad debt на USDC-саплаеров."),
        "note_en": "No loss reached this book; the scenario documents the near-miss chain that could have.",
        "note_ru": "До книги потери не дошли; сценарий фиксирует цепочку near-miss, которая могла дойти.",
    },
    "H10_aug_2024_yen_carry": {
        "en": ("Yen carry unwind", "Nikkei −12.4%, VIX 16→65, BTC −30% in a week with zero crypto-native "
               "failure. Pegs near-perfect; Aave processed record liquidations with no bad debt."),
        "ru": ("Разворот yen carry", "Nikkei −12.4%, VIX 16→65, BTC −30% за неделю без единого "
               "крипто-отказа. Пеги идеальны; Aave провёл рекордные ликвидации без bad debt."),
        "note_en": "Macro-shock control: protection has nothing to do, and honestly does nothing.",
        "note_ru": "Макро-контроль: защите нечего делать, и она честно ничего не делает.",
    },
    "H11_bybit_hack_feb_2025": {
        "en": ("Bybit $1.5B hack", "The largest theft in crypto history — yet withdrawals stayed open, "
               "solvency held, and the panic burned out in 72 hours. No DeFi venue was touched."),
        "ru": ("Взлом Bybit $1.5B", "Крупнейшая кража в истории крипты — но выводы не закрывались, "
               "платёжеспособность устояла, паника выгорела за 72 часа. DeFi не тронут."),
        "note_en": "Custody hack without insolvency is not a bank run — the distinction matters for risk models.",
        "note_ru": "Custody-hack без инсолвентности — не bank run; для риск-моделей различие принципиально.",
    },
    "H12_oct_10_2025_cascade": {
        "en": ("October 10, 2025", "The largest liquidation cascade ever: $19B in 24h, BTC −10% in 20 "
               "minutes, USDe at $0.65 on one venue. On-chain USDC rails came through unbroken."),
        "ru": ("Каскад 10 октября 2025", "Крупнейший каскад ликвидаций: $19B за сутки, BTC −10% за 20 "
               "минут, USDe $0.65 на одной площадке. On-chain USDC-рельсы прошли без повреждений."),
        "note_en": "Intraday speed beats a daily cycle by construction — the lab shows this instead of smoothing it.",
        "note_ru": "Внутридневная скорость быстрее дневного цикла по построению — лаборатория показывает это, а не сглаживает.",
    },
    "H13_maple_orthogonal_dec_2022": {
        "en": ("Orthogonal / Maple default", "A borrower concealed insolvency for ~4 weeks, then ~80% of "
               "the M11 USDC pool was written down in one block. Lockups barred exit even beforehand."),
        "ru": ("Дефолт Orthogonal в Maple", "Заёмщик ~4 недели скрывал инсолвентность, затем ~80% пула "
               "M11 USDC списано одним блоком. Локапы запирали выход даже заранее."),
        "note_en": "Private-credit default has no on-chain price signal — the flagship uncovered channel of this book.",
        "note_ru": "У кредитного дефолта нет ценового сигнала on-chain — флагманский незакрытый канал книги.",
    },
    "H14_stream_xusd_nov_2025": {
        "en": ("Stream / xUSD curator crisis", "A vault manager lost $93M off-chain, froze withdrawals "
               "FIRST, then xUSD collapsed 77%. ~$285M of exposure ran through curated lending vaults."),
        "ru": ("Stream / xUSD: кризис кураторов", "Управляющий потерял $93M вне цепочки, СНАЧАЛА заморозил "
               "выводы, потом xUSD рухнул на 77%. ~$285M экспозиции шло через кураторные хранилища."),
        "note_en": "This book's curated vault was not exposed in the historical event — one curator over, it would have been.",
        "note_ru": "Кураторное хранилище книги исторически не пострадало — одним куратором в сторону было бы иначе.",
    },
    "H15_euler_mar_2023": {
        "en": ("Euler: hack and full recovery", "$197M drained in 20 minutes from an audited lender — then "
               "fully returned within 22 days. Panic-selling frozen claims locked −85%; patience got 100%."),
        "ru": ("Euler: взлом и полный возврат", "$197M за 20 минут из аудированного протокола — и полный "
               "возврат за 22 дня. Паническая продажа замороженных требований фиксировала −85%; терпение вернуло 100%."),
        "note_en": "Deliberate counterfactual mapping (documented): tests mark-to-zero vs mark-to-recovery accounting.",
        "note_ru": "Осознанный контрфакт (задокументирован): тест учёта mark-to-zero против mark-to-recovery.",
    },
    "H16_aave_capo_mar_2026": {
        "en": ("Aave CAPO oracle incident", "A risk-provider misconfiguration liquidated 34 healthy "
               "positions (~$27M) with no market move. Zero bad debt; suppliers lost nothing."),
        "ru": ("Aave CAPO: авария оракула", "Ошибка конфигурации риск-провайдера ликвидировала 34 "
               "здоровые позиции (~$27M) без движения рынка. Ноль bad debt; саплаеры не потеряли ничего."),
        "note_en": "Oracle risk includes configuration failure by professionals — a venue-operational class, not credit.",
        "note_ru": "Оракульный риск включает ошибку конфигурации у профессионалов — операционный класс площадки, не кредит.",
    },
    "SYN_S01_stablecoin_contagion": {
        "en": ("Stablecoin contagion", "Synthetic: USDC to $0.78 with a correlated PT discount; recovery "
               "by day 12. Cash is USDC — there is nowhere to run."),
        "ru": ("Каскадный депег", "Синтетика: USDC до $0.78 с коррелированным PT-дисконтом; восстановление "
               "к дню 12. Кэш — USDC: бежать некуда."),
        "note_en": "Synthetic parameters, not facts; same deterministic engine as historical replays.",
        "note_ru": "Параметры синтетики, не факты; тот же детерминированный движок, что и у истории.",
    },
    "SYN_S02_private_credit_default": {
        "en": ("Private-credit default", "Synthetic: −35% principal on the credit sleeve with NO market "
               "signal the day before; pool frozen to day 20 — Orthogonal-style."),
        "ru": ("Кредитный дефолт", "Синтетика: −35% принципала кредитного рукава БЕЗ рыночного сигнала "
               "накануне; пул заморожен до дня 20 — стиль Orthogonal."),
        "note_en": "Synthetic parameters, not facts.", "note_ru": "Параметры синтетики, не факты.",
    },
    "SYN_S03_lending_death_spiral": {
        "en": ("Lending death spiral", "Synthetic: vault bad debt −12%, the largest venue pinned at 100% "
               "utilization for 3 days, 2% exit haircut."),
        "ru": ("Спираль lending", "Синтетика: bad debt хранилища −12%, крупнейшая площадка запинена на "
               "100% утилизации 3 дня, haircut выхода 2%."),
        "note_en": "Synthetic parameters, not facts.", "note_ru": "Параметры синтетики, не факты.",
    },
    "SYN_S04_double_shock": {
        "en": ("Double shock", "Synthetic: USDC to $0.85 while the largest venue halts entirely for 3 "
               "days; gas ×20."),
        "ru": ("Двойной удар", "Синтетика: USDC до $0.85, крупнейшая площадка полностью стоит 3 дня; "
               "gas ×20."),
        "note_en": "Synthetic parameters, not facts.", "note_ru": "Параметры синтетики, не факты.",
    },
    "SYN_S05_pt_dislocation": {
        "en": ("PT dislocation", "Synthetic: fixed-yield PT trades at 0.85 for ten days with NO default, "
               "then returns to par. A trap: exiting at the discount locks a loss patience avoids."),
        "ru": ("PT-дислокация", "Синтетика: PT торгуется по 0.85 десять дней БЕЗ дефолта, потом возврат "
               "к пару. Ловушка: выход по дисконту фиксирует убыток, которого нет при удержании."),
        "note_en": "Synthetic parameters, not facts.", "note_ru": "Параметры синтетики, не факты.",
    },
    "SYN_S06_oct10_x2": {
        "en": ("October 10 × 2", "Synthetic: the largest liquidation cascade in history, doubled — deeper "
               "PT discount, 5% exit haircut, vault marks."),
        "ru": ("10.10 × 2", "Синтетика: крупнейший каскад ликвидаций, удвоенный — глубже PT-дисконт, "
               "haircut выхода 5%, уценки хранилища."),
        "note_en": "Synthetic parameters, not facts.", "note_ru": "Параметры синтетики, не факты.",
    },
    "SYN_S07_utilization_pin": {
        "en": ("Utilization pin", "Synthetic: withdrawals unavailable for 3 days while NAV never drops a "
               "cent. Question: does the protection see it? (It does not — and says so.)"),
        "ru": ("Utilization-пин", "Синтетика: вывод недоступен 3 дня, а NAV не падает ни на цент. Вопрос: "
               "видит ли это защита? (Не видит — и говорит об этом.)"),
        "note_en": "Synthetic parameters, not facts.", "note_ru": "Параметры синтетики, не факты.",
    },
}


def verdict_key(m: dict, fails: int) -> str:
    if m["bench_final"] < 96000 and m["det"] is None:
        return "uncovered"
    if fails > 0:
        return "unexecutable"
    if m["saved"] < -100:
        return "costly"
    if m["saved"] == 0 and m["det"] is None:
        return "quiet"
    return "worked"


def pack(sid: str, name_en_full: str, window: str, rep, synthetic: bool) -> dict:
    c = COPY[sid]
    m = {
        "bench_final": rep.benchmark.final_equity,
        "prot_final": rep.protected.final_equity,
        "bench_dd": rep.benchmark.max_drawdown_pct,
        "prot_dd": rep.protected.max_drawdown_pct,
        "saved": rep.capital_saved_usd,
        "det": rep.detection_day,
    }
    return {
        "id": sid,
        "nameEn": c["en"][0], "nameRu": c["ru"][0],
        "blurbEn": c["en"][1], "blurbRu": c["ru"][1],
        "noteEn": c["note_en"], "noteRu": c["note_ru"],
        "fullName": name_en_full,
        "window": window[:10] if window else "",
        "synthetic": synthetic,
        "bench": [b["close_equity"] for b in rep.benchmark.bars],
        "prot": [b["close_equity"] for b in rep.protected.bars],
        "dates": [b["date"] for b in rep.protected.bars],
        "actions": [{"day": a["day"], "kind": a["kind"]}
                    for a in rep.protected.actions if a["kind"] != "exit_executed"],
        "fails": len(rep.protected.execution_failures),
        "metrics": m,
        "verdict": verdict_key(m, len(rep.protected.execution_failures)),
    }


def build_payload(generated: str) -> dict:
    out = {"generated": generated,
           "provenance": "spa_core.stress.protection_lab (ADR-120); "
                         "regenerate: python3 scripts/build_protection_lab_site_data.py",
           "capital_usd": 100000, "historical": [], "synthetic": []}
    scs = load_all_scenarios()
    for sid, sc in sorted(scs.items(), key=lambda kv: kv[1].window_utc.get("start", "")):
        if not sc.has_replay or sid not in COPY:
            continue
        rep = run_replay(sc)
        out["historical"].append(pack(sid, sc.name, sc.window_utc.get("start", ""), rep, False))
    for spec in ADVERSARIAL_SPECS:
        sc = build_synthetic_scenario(spec)
        if sc.id not in COPY:
            continue
        rep = run_replay(sc)
        out["synthetic"].append(pack(sc.id, spec.description, "", rep, True))

    n_hist_total = len(scs)  # включая dataset-only H01/H02
    out["summary"] = {
        "library": n_hist_total,
        "replayed": len(out["historical"]),
        "survived_hard": sum(1 for s in out["historical"]
                             if s["metrics"]["prot_dd"] < 10.0),
        "worst_prot_dd": max(s["metrics"]["prot_dd"] for s in out["historical"]),
    }
    return out


def _comparable(payload: dict) -> dict:
    """Копия без волатильной даты генерации — сверять только числа/структуру."""
    return {k: v for k, v in payload.items() if k != "generated"}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    check = "--check" in argv

    if check:
        if not OUT.is_file():
            print(f"НЕТ ФАЙЛА {OUT} — запусти генератор без --check", file=sys.stderr)
            return 1
        committed = json.loads(OUT.read_text(encoding="utf-8"))
        fresh = build_payload(generated=committed.get("generated", ""))
        if _comparable(committed) != _comparable(fresh):
            print("РАСХОЖДЕНИЕ: landing/src/data/protection_lab.json разошёлся с движком "
                  "Protection Lab. Числа страницы правятся ТОЛЬКО перегенерацией:\n"
                  "  python3 scripts/build_protection_lab_site_data.py", file=sys.stderr)
            return 1
        print(f"OK: {OUT.name} совпадает с движком "
              f"(hist {len(fresh['historical'])} · syn {len(fresh['synthetic'])})")
        return 0

    out = build_payload(generated=date.today().isoformat())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f"wrote {OUT} · hist {len(out['historical'])} · syn {len(out['synthetic'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
