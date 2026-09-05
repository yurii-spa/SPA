#!/usr/bin/env python3
# LLM_FORBIDDEN
"""
measure_pin_placement_effect — сколько кэша РАЗМЕЩАЕТ один пин пула.

ЗАЧЕМ. Шаг (3) карточки `inbox-ozhivit-fidy-vne-ethereum-put-k-snyatiyu`
(«замерить, сколько кэша размещается после каждого шага») с 08.08 не был исполнен
НИ РАЗУ — четыре цикла подряд (#489, #490, #494 и предшественники) записывали его
как неисполненный. Причина каждый раз была своя и честная: то ни одного пина ещё
не сделано, то артефакт старше доставки пина, то фид не отвечает. Общего у них
одно: у замера не было ИНСТРУМЕНТА, поэтому каждый заход начинался с нуля и
кончался прозой в карточке.

Здесь инструмент. Он отвечает ровно на один вопрос и отвечает числом:
**на сколько долларов меняется РАЗМЕЩЁННЫЙ капитал оттого, что ключ X запинён.**

КАК МЕРИТ (дифференциально, на ОДНОМ снимке фида). Два прогона настоящего
денежного пути — `adapter_status_generator.generate()` → `StrategyAllocator.allocate()`
→ `_apply_risk_policy_gate()`, — отличающиеся РОВНО одной строкой таблицы
`_POOL_ID_LOOKUP`:

    рука A: пин на месте (дерево как есть)
    рука B: пин ключа X убран

Оба видят БАЙТ-В-БАЙТ один и тот же снимок фида, одно и то же состояние и один
и тот же капитал. Поэтому разница в размещении относится к пину, а не к тому, что
рынок между двумя прогонами сдвинулся. Снимок либо передаётся файлом (`--feed`,
воспроизводимо), либо снимается один раз и делится обеими руками.

ПОЧЕМУ НЕ ПРОСТО «ПОСМОТРЕТЬ adapter_status.json». Потому что производителей
ДВА, и решение о заморозке принимает НЕ тот, в котором живёт пин. Пин правит
`data/adapter_status.json`; ADR-053-заморозку («нет живого TVL ⇒ свежего капитала
нет») применяет `_apply_risk_policy_gate` по снимку ОРКЕСТРАТОРА
(`adapter_orchestrator_status.json`, 11 опрашиваемых ключей). Замер 05.09:
`spark_susds` в снимке оркестратора отсутствует вовсе. Глядя в один файл, на
вопрос «сколько денег это разместило» ответить нельзя по построению — только
прогоном обоих потребителей.

ПЕСОЧНИЦА ОБЯЗАТЕЛЬНА. Прогон аллокатора и гейта пишет состояние; в боевом дереве
там живёт трек. Инструмент НИКОГДА не пишет в каталог-источник: он копирует
состояние в свою временную песочницу и работает только в ней (тот же порядок, что
у `cycle_analytics_audit.py`). Источник открывается на чтение.

⚠️ ЛОВУШКА, НА КОТОРОЙ ЗАМЕР ОДИН РАЗ УЖЕ СОВРАЛ (цикл #495, поймано в тот же
заход). Гейт класса адаптера `_adapter_class_gate()` СОЗДАЁТ настоящий адаптер, а
тот разрешает свой каталог состояния сам — и без `SPA_DATA_DIR` берёт `data/`
СВОЕГО дерева, а не песочницу. В worktree это замороженный канон origin, где нет
gsm-полей, поэтому первый прогон этого замера получил `spark_susds:
gsm_not_confirmed` и «пин не двигает ничего» — вердикт ЧУЖОГО дерева, а не
измеряемого снимка. Класс описан в `spa_core/utils/data_dir.py`. Поэтому здесь
`SPA_DATA_DIR` выставляется на песочницу руки ЯВНО и проверяется тестом: замер,
у которого часть читателей смотрит в другое дерево, отвечает не на свой вопрос.

ТРЕТИЙ ИСХОД. Фид не ответил ⇒ это НЕ ноль и НЕ пропуск, а `unmeasured` с
названной причиной и кодом 2. Ровно этот случай остановил цикл #494 (17:44Z
`yields.llama.fi/pools` отдавал 8 байт `GET,HEAD` с кодом 200), и записать его
нулём значило бы сказать «пин ничего не размещает», не измерив ничего.

КОДЫ ВОЗВРАТА:
  0 — замерено (разница может быть и нулевой — это РЕЗУЛЬТАТ, а не отказ);
  2 — не измерено: фид не ответил / песочница не создана / пина нет в таблице.

ПРИМЕРЫ:
  python3 scripts/measure_pin_placement_effect.py --pin spark_susds \\
      --data-dir ~/Documents/SPA_Claude/data --feed /tmp/pools.json
  python3 scripts/measure_pin_placement_effect.py --pin spark_susds --json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Капитал книги. Не выдумка: paper-мандат — виртуальные $100 000 USDC (CLAUDE.md).
DEFAULT_CAPITAL_USD = 100_000.0

EXIT_MEASURED = 0
EXIT_UNMEASURED = 2


class Unmeasured(Exception):
    """Замер не состоялся, и причина названа. Никогда не превращается в число."""


def load_feed(
    feed_path: Optional[Path] = None,
    fetcher: Optional[Callable[[], Any]] = None,
) -> list:
    """Один снимок фида на ОБЕ руки.

    Пустой/мусорный ответ — ``Unmeasured``, а не пустой список: «фид отдал ноль
    пулов» и «фид не отвечает» это разные факты, и второй нельзя записывать
    первым (авария 05.09 17:44Z — HTTP 200 с телом ``GET,HEAD``).
    """
    if feed_path is not None:
        try:
            raw = json.loads(Path(feed_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise Unmeasured(f"снимок фида {feed_path} не читается: {exc}") from exc
    else:
        if fetcher is None:
            from spa_core.monitoring.adapter_status_generator import _fetch_defillama
            fetcher = _fetch_defillama
        raw = fetcher()

    pools = raw.get("data", raw) if isinstance(raw, dict) else raw
    if not isinstance(pools, list) or not pools:
        size = len(pools) if isinstance(pools, (list, dict, str)) else "н/д"
        raise Unmeasured(
            "фид не отдал списка пулов "
            f"(получено {type(pools).__name__}, длина {size}) — "
            "это НЕ «нулевой эффект пина», это отсутствие данных"
        )
    return pools


def _run_arm(
    *,
    arm_name: str,
    drop_pin: Optional[str],
    pools: list,
    source_data_dir: Path,
    sandbox_root: Path,
    capital_usd: float,
) -> dict:
    """Один прогон настоящего денежного пути в собственной песочнице руки."""
    import spa_core.monitoring.adapter_status_generator as gen

    ddir = sandbox_root / arm_name
    if ddir.exists():
        shutil.rmtree(ddir)
    try:
        shutil.copytree(source_data_dir, ddir)
    except OSError as exc:
        raise Unmeasured(f"песочница {ddir} не создана: {exc}") from exc

    # См. «ЛОВУШКА» в шапке: без этого часть читателей судит по ДРУГОМУ дереву.
    prev_env = os.environ.get("SPA_DATA_DIR")
    os.environ["SPA_DATA_DIR"] = str(ddir)

    prev_fetch = gen._fetch_defillama
    saved_pins = dict(gen._POOL_ID_LOOKUP)
    try:
        gen._fetch_defillama = lambda timeout=0: pools
        if drop_pin is not None:
            gen._POOL_ID_LOOKUP.pop(drop_pin, None)

        doc = gen.generate(
            registry_path=ddir / "adapter_registry.json",
            output_path=ddir / "adapter_status.json",
        )
        (ddir / "adapter_status.json").write_text(
            json.dumps(doc, indent=2), encoding="utf-8"
        )

        from spa_core.allocator.allocator import StrategyAllocator
        from spa_core.paper_trading.risk_gate import _apply_risk_policy_gate

        allocator = StrategyAllocator(
            status_path=str(ddir / "adapter_orchestrator_status.json"),
            adapter_status_path=str(ddir / "adapter_status.json"),
            strategy_loop_enabled=False,
        )
        result = allocator.allocate()
        target = {
            str(k): float(v)
            for k, v in (getattr(result, "target_usd", {}) or {}).items()
        }

        orch = json.loads(
            (ddir / "adapter_orchestrator_status.json").read_text(encoding="utf-8")
        )
        held = _held_map(ddir)
        gate = _apply_risk_policy_gate(
            dict(target), capital_usd, orch.get("adapters") or [],
            ddir=ddir, current_positions=held,
        )
    finally:
        gen._fetch_defillama = prev_fetch
        gen._POOL_ID_LOOKUP.clear()
        gen._POOL_ID_LOOKUP.update(saved_pins)
        if prev_env is None:
            os.environ.pop("SPA_DATA_DIR", None)
        else:
            os.environ["SPA_DATA_DIR"] = prev_env

    post = {str(k): float(v) for k, v in (gate.get("target_usd") or {}).items()}
    deployed = sum(post.values())
    return {
        "arm": arm_name,
        "pin_dropped": drop_pin,
        "target_pre_gate": {k: round(v, 2) for k, v in target.items() if v > 0},
        "target_pre_total": round(sum(target.values()), 2),
        "book_post_gate": {k: round(v, 2) for k, v in post.items() if v > 0},
        "deployed_usd": round(deployed, 2),
        "cash_usd": round(capital_usd - deployed, 2),
        "cash_pct": round(100.0 * (capital_usd - deployed) / capital_usd, 4),
        "tvl_unverified": list(gate.get("tvl_unverified") or []),
        "approved": bool(gate.get("approved")),
        "blocked": dict(getattr(allocator, "_blocked", {}) or {}),
    }


def _held_map(ddir: Path) -> dict[str, float]:
    """Что книга держит СЕЙЧАС — заморозка ADR-053 режет до held, а не до нуля."""
    try:
        doc = json.loads((ddir / "current_positions.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    positions = doc.get("positions", {})
    if not isinstance(positions, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in positions.items():
        amount = value.get("amount_usd") if isinstance(value, dict) else value
        if isinstance(amount, (int, float)) and not isinstance(amount, bool):
            out[str(key)] = float(amount)
    return out


def measure(
    *,
    pin_key: str,
    source_data_dir: Path,
    sandbox_root: Path,
    pools: list,
    capital_usd: float = DEFAULT_CAPITAL_USD,
) -> dict:
    """Дифференциальный замер: рука с пином против руки без него.

    Отсутствие ключа в таблице пинов — ``Unmeasured``: сравнивать «с пином» и
    «без пина» нечего, и молча вернуть нулевую разницу значило бы отчитаться
    об измерении, которого не было.
    """
    import spa_core.monitoring.adapter_status_generator as gen

    if pin_key not in gen._POOL_ID_LOOKUP:
        raise Unmeasured(
            f"ключ {pin_key!r} не запинён в _POOL_ID_LOOKUP — "
            "разницы «с пином / без пина» не существует"
        )

    source_data_dir = Path(source_data_dir).resolve()
    sandbox_root = Path(sandbox_root).resolve()
    if sandbox_root == source_data_dir or source_data_dir in sandbox_root.parents:
        raise Unmeasured(
            f"песочница {sandbox_root} лежит внутри источника {source_data_dir} — "
            "прогон писал бы в живое состояние"
        )

    with_pin = _run_arm(
        arm_name="with_pin", drop_pin=None, pools=pools,
        source_data_dir=source_data_dir, sandbox_root=sandbox_root,
        capital_usd=capital_usd,
    )
    without_pin = _run_arm(
        arm_name="without_pin", drop_pin=pin_key, pools=pools,
        source_data_dir=source_data_dir, sandbox_root=sandbox_root,
        capital_usd=capital_usd,
    )

    placed = with_pin["deployed_usd"] - without_pin["deployed_usd"]
    return {
        "status": "measured",
        "pin_key": pin_key,
        "capital_usd": capital_usd,
        "feed_pools": len(pools),
        "with_pin": with_pin,
        "without_pin": without_pin,
        "placed_usd": round(placed, 2),
        "cash_pct_delta": round(
            with_pin["cash_pct"] - without_pin["cash_pct"], 4
        ),
        "target_pre_delta_on_key": round(
            with_pin["target_pre_gate"].get(pin_key, 0.0)
            - without_pin["target_pre_gate"].get(pin_key, 0.0), 2
        ),
    }


def pins_invisible_to_the_gate(data_dir: Path) -> dict:
    """Пины, которые НЕ МОГУТ повлиять на финансирование — дешёвый вопрос.

    Найдено замером #495 и стоит отдельного сторожа, потому что состояние
    СТОЯЧЕЕ и молчаливое. Пин правит `adapter_status.json`, который читает
    аллокатор; заморозку ADR-053 применяет `_apply_risk_policy_gate` по снимку
    ОРКЕСТРАТОРА. Ключ, которого в снимке оркестратора нет, гейт отклоняет как
    `TVL unverified (missing)` — **при любом пине и любом живом TVL**. Проверено
    контролем: при пине `spark_susds` (`tvl_source: live`, $242.5 млн)
    принудительная заявка на $10 000 всё равно отклонена.

    Практический смысл: решение владельца о том, ЧТО означает ключ (ADR-232 —
    «`spark_susds` для нас кредитный рынок»), записано в одном производителе и
    невидимо тому гейту, который решает о деньгах. Само по себе это не авария —
    ключ может быть и не нужен книге (для `spark_susds` замерено: не нужен), —
    но об этом надо ЗНАТЬ, а не обнаруживать через месяц.

    Два файла, никаких прогонов и сети. Третий исход обязателен: файл не
    прочитан ⇒ ``unmeasured`` с причиной, а не пустой список «всё в порядке».
    """
    import spa_core.monitoring.adapter_status_generator as gen

    ddir = Path(data_dir)
    try:
        orch = json.loads(
            (ddir / "adapter_orchestrator_status.json").read_text(encoding="utf-8")
        )
        polled = {
            str(a.get("protocol"))
            for a in (orch.get("adapters") or [])
            if isinstance(a, dict) and a.get("protocol")
        }
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        return {"unmeasured": f"снимок оркестратора не прочитан: {exc}",
                "checked": 0, "invisible": []}
    if not polled:
        return {"unmeasured": "в снимке оркестратора нет ни одного протокола — "
                              "«пинов не видно» и «спрашивать нечего» это разные "
                              "факты", "checked": 0, "invisible": []}

    pinned = sorted(gen._POOL_ID_LOOKUP)
    return {
        "unmeasured": None,
        "checked": len(pinned),
        "polled": len(polled),
        "invisible": [k for k in pinned if k not in polled],
    }


def gate_visibility_report_lines(result: dict) -> list[str]:
    """Строки для обязательного шага 0-офис (ADR-236)."""
    head = "— пины против гейта финансирования (ADR-236) —"
    if result.get("unmeasured"):
        return [head, f"   [НЕ ИЗМЕРЕНО] {result['unmeasured']}"]
    invisible = result.get("invisible") or []
    if not invisible:
        return [head, f"   ✅ все {result['checked']} запинённых ключа есть в снимке "
                      f"оркестратора — пин способен повлиять на финансирование"]
    return [head, (
        f"   ⚠️ {len(invisible)} из {result['checked']} запинённых ключей НЕТ в снимке "
        f"оркестратора ({result['polled']} опрашиваемых): гейт отклонит их как "
        f"`TVL unverified (missing)` при любом пине — "
        + ", ".join(invisible)
    ), "      пин задаёт СМЫСЛ ключа для аллокатора, но финансирование решает "
       "снимок оркестратора; это разные производители"]


def _render(out: dict) -> str:
    w, b = out["with_pin"], out["without_pin"]
    key = out["pin_key"]
    lines = [
        f"— размещение от пина `{key}` (дифференциально, один снимок фида: "
        f"{out['feed_pools']} пулов) —",
        f"  с пином   : размещено ${w['deployed_usd']:,.2f} · "
        f"кэш ${w['cash_usd']:,.2f} ({w['cash_pct']:.2f} %)",
        f"  без пина  : размещено ${b['deployed_usd']:,.2f} · "
        f"кэш ${b['cash_usd']:,.2f} ({b['cash_pct']:.2f} %)",
        f"  ⇒ пин размещает ${out['placed_usd']:,.2f} "
        f"(кэш {out['cash_pct_delta']:+.2f} пп)",
    ]
    if out["target_pre_delta_on_key"]:
        lines.append(
            f"  до гейта аллокатор просил на сам ключ "
            f"{out['target_pre_delta_on_key']:+,.2f} — а гейт "
            f"{'заморозил' if key in b['tvl_unverified'] else 'пропустил'} его"
        )
    if key in b["tvl_unverified"] and key not in w["tvl_unverified"]:
        lines.append(
            f"  без пина ключ попадает в tvl_unverified (ADR-053) — "
            "заявка была обречена, и её бюджет падал в кэш"
        )
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:  # noqa: D103
    parser = argparse.ArgumentParser(
        description="Сколько кэша размещает один пин пула (дифференциально)."
    )
    parser.add_argument("--pin", default="spark_susds", help="ключ пина")
    parser.add_argument(
        "--data-dir",
        default=str(Path.home() / "Documents" / "SPA_Claude" / "data"),
        help="ОТКУДА копировать состояние (только чтение)",
    )
    parser.add_argument("--feed", help="файл снимка фида (иначе — живой запрос)")
    parser.add_argument("--sandbox-root", help="куда класть песочницу")
    parser.add_argument(
        "--capital", type=float, default=DEFAULT_CAPITAL_USD, help="капитал книги"
    )
    parser.add_argument("--json", action="store_true", help="машинный вывод")
    args = parser.parse_args(argv)

    tmp_root: Optional[str] = None
    try:
        pools = load_feed(Path(args.feed) if args.feed else None)
        if args.sandbox_root:
            sandbox_root = Path(args.sandbox_root)
            sandbox_root.mkdir(parents=True, exist_ok=True)
        else:
            tmp_root = tempfile.mkdtemp(prefix="spa_pin_effect_")
            sandbox_root = Path(tmp_root)
        out = measure(
            pin_key=args.pin,
            source_data_dir=Path(args.data_dir),
            sandbox_root=sandbox_root,
            pools=pools,
            capital_usd=args.capital,
        )
    except Unmeasured as exc:
        payload = {"status": "unmeasured", "pin_key": args.pin, "reason": str(exc)}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"⚠️ НЕ ИЗМЕРЕНО: {exc}")
        return EXIT_UNMEASURED
    finally:
        if tmp_root:
            shutil.rmtree(tmp_root, ignore_errors=True)

    print(json.dumps(out, ensure_ascii=False, indent=2) if args.json else _render(out))
    return EXIT_MEASURED


if __name__ == "__main__":
    raise SystemExit(main())
