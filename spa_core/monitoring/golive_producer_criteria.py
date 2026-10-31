"""Спрашивают ли три критерия go-live ПИСАТЕЛЯ — замер в обе стороны (ADR-878).

Решение ВЛАДЕЛЬЦА 31.10 (вариант 1, карточка
`inbox-tri-kriteriya-go-live-perepisat-na-nasto`) по находке ADR-876: три места
начисляли готовность к живым деньгам за ПРИСУТСТВИЕ файла.

    spa_core/analytics/golive_readiness_report.assess_data_sources — 6 баллов
        из 10 за присутствие четырёх git-tracked ИСХОДНИКОВ;
    spa_core/golive/checklist.check_wallet_ready — «wallet infrastructure
        confirmed by owner» за присутствие `data/wallet_ready.sentinel`;
    scripts/cycle_dry_run.check_files — `n_pass` за присутствие И РАЗМЕР.

Присутствие наблюдением не является: git-tracked путь выкладывает `git checkout`,
а размер — свойство байтов, а не свидетельство о том, что кто-то их СЕГОДНЯ
написал. Сила утверждения «переписано» держится не на том, что новый код зелен, а
на том, что он КРАСЕН там, где писателя нет, — поэтому мера здесь ОДНА и
двусторонняя: две одноразовые сцены, различие между которыми РОВНО наличие
писателя.

**Сцена «мёртвая» — это не «файлов нет».** Все четыре git-tracked ИСХОДНИКА в ней
лежат (их и выкладывает `git checkout`), и обязательные `data/*.json` в ней тоже
лежат — с отметками двухмесячной давности, дословно как в свежем worktree. Разница
только в том, писал ли кто-нибудь артефакты СВОЕГО прогона. Сцена, в которой
просто нет файлов, доказывала бы другое утверждение — «код падает без входа», — и
именно поэтому прежняя батарея (`tests/test_evidence_infrastructure.py`, три теста
«…_gives_2pts») была зелёной на дефекте: она удаляла ИСХОДНИК и видела −2 балла.

Только stdlib. Прибор ничего не чинит и не пишет за пределами своего каталога-сцены.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import contextlib
import io
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

#: Исходы меры. Различимы (инвариант #17): «сцена не поднялась» никогда не
#: выдаётся за «мера слепа» и наоборот.
DRIVE_OK = "measured"
DRIVE_BLIND = "blind"
DRIVE_UNMEASURED = "unmeasured"

#: Четыре git-tracked ИСХОДНИКА, за присутствие которых начислялись баллы до
#: ADR-878. В обеих сценах они лежат ОДИНАКОВО — иначе мера отвечала бы на
#: прежний вопрос «а файл есть?».
_TRACKED_SOURCES = (
    "spa_core/utils/defillama.py",
    "spa_core/adapters/defillama_feed.py",
    "spa_core/analytics/t1_data_verifier.py",
    "spa_core/analytics/strategy_promoter.py",
    "promotion_engine.py",
)

#: Обязательные артефакты `cycle_dry_run` и то, чем в них отмечается писатель.
#: Копия объявления намеренно НЕ делается: словарь импортируется у самой двери.
_STALE_H = 24.0 * 90.0


def _write(root: Path, rel: str, payload: Any) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _scene(root: Path, *, writer_alive: bool, now: datetime) -> None:
    """Выложить сцену. ``writer_alive`` — ЕДИНСТВЕННОЕ различие между двумя."""
    for rel in _TRACKED_SOURCES:
        _write(root, rel, "# git-tracked источник: его выкладывает `git checkout`\n")

    # ≥5 CLEAN источников — два балла, судящие СОДЕРЖИМОЕ; одинаковы в обеих
    # сценах, иначе разница в счёте пришла бы не от писателя.
    _write(root, "data/backtest/source_pipeline.json",
           {"sources": {f"s{i}": "clean_included" for i in range(5)}})

    fresh = now - timedelta(hours=1.0)
    stale = now - timedelta(hours=_STALE_H)
    stamp = (fresh if writer_alive else stale).isoformat()

    # Обязательные артефакты лежат В ОБЕИХ сценах: в мёртвой они несут отметку
    # двухмесячной давности — дословно канон `data/` в git (заморожен 04.08).
    _write(root, "data/golive_status.json", {"timestamp": stamp, "ready": False})
    _write(root, "data/tournament_ranking.json", {"timestamp": stamp, "strategies": []})
    _write(root, "data/adapter_status.json", {
        "generated_at": stamp,
        "feed_reachable": True,
        "live_apy_enabled": True,
        "adapters": {"aave_v3": {"live_apy": 5.39, "live_apy_fresh": True,
                                 "live_apy_as_of": stamp}},
    })
    _write(root, "data/paper_evidence.json", {
        "days": [{"date": (fresh if writer_alive else stale).date().isoformat(),
                  "strategy_id": "S7", "apy_pct": 5.6}],
    })

    if writer_alive:
        # Артефакты СВОИХ прогонов — их не бывает от `git checkout`.
        _write(root, "data/t1_verification.json",
               {"verified_at": fresh.isoformat(), "results": [], "all_pass": True})
        _write(root, "data/promotion_decisions.json",
               [{"strategy_id": "S7", "decision": "HOLD",
                 "timestamp": fresh.isoformat()}])
        # Подпись владельца — ЗАПИСАННАЯ (кто и когда).
        _write(root, "data/wallet_ready_approved.json",
               {"approved": True, "approved_by": "@yurii",
                "approved_at": fresh.isoformat()})
    else:
        # Мёртвая сцена: вместо подписи — МЕТКА активации, то есть ровно то, что
        # кладёт `touch`. Присутствие метки подписью владельца не является.
        _write(root, "data/wallet_ready.sentinel", stale.isoformat())


def _measure_scene(root: Path, *, now: datetime) -> dict:
    """Три числа одной сцены: баллы писателя · вердикт кошелька · PASS у файлов."""
    from spa_core.analytics.golive_readiness_report import GoLiveReadinessReport
    from spa_core.golive import checklist

    category = GoLiveReadinessReport(base_dir=str(root)).assess_data_sources(now=now)
    wallet = checklist.check_wallet_ready(data_dir=str(root / "data"))

    import importlib.util
    here = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "_cdr_scene", str(here / "scripts" / "cycle_dry_run.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("scripts/cycle_dry_run.py не ввозится как модуль")
    cdr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cdr)
    cdr.ROOT = str(root)
    # Сцена — измерительная, а не докладывающая: печать `check_files` пошла бы в
    # stdout зовущего (шаг 0-офис читает его глазами), и четыре строки про
    # заведомо мёртвую сцену читались бы как находка о боевом дереве.
    noise = io.StringIO()
    with contextlib.redirect_stdout(noise):
        files_pass, files_fail, files_unmeasured = cdr.check_files(now=now)

    return {
        # Из десяти баллов два за ≥5 CLEAN и два за ≥50 % CLEAN одинаковы в
        # обеих сценах — предмет меры РОВНО остаток, те шесть, что были
        # константой.
        "data_sources_score": category.score,
        "writer_points": category.score - 4.0,
        "data_sources_unmeasured": len(category.items_unmeasured),
        "wallet_status": wallet["status"],
        "wallet_value": wallet["value"],
        "files_pass": files_pass,
        "files_fail": files_fail,
        "files_unmeasured": files_unmeasured,
    }


def drive_both_directions(now: datetime | None = None) -> dict:
    """Две сцены, различие РОВНО наличие писателя. → вердикт меры.

    ``DRIVE_OK`` — у всех трёх дверей ответы ПРОТИВОПОЛОЖНЫЕ; ``DRIVE_BLIND`` —
    хоть одна дверь ответила одинаково (значит присутствие она всё ещё читает как
    наблюдение, и её зелёный ничего не доказывает); ``DRIVE_UNMEASURED`` — сцену
    поднять не удалось, и это НЕ «слепа».
    """
    at = now or datetime.now(timezone.utc)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)

    try:
        with tempfile.TemporaryDirectory(prefix="adr878_live_") as live, \
                tempfile.TemporaryDirectory(prefix="adr878_dead_") as dead:
            live_root, dead_root = Path(live), Path(dead)
            _scene(live_root, writer_alive=True, now=at)
            _scene(dead_root, writer_alive=False, now=at)
            alive = _measure_scene(live_root, now=at)
            gone = _measure_scene(dead_root, now=at)
    except Exception as exc:                                        # noqa: BLE001
        return {"kind": DRIVE_UNMEASURED,
                "reason": f"сцена не поднялась: {type(exc).__name__}: {exc}"}

    same: list[str] = []
    if alive["writer_points"] <= gone["writer_points"]:
        same.append(
            f"баллы за писателя не упали: живая сцена {alive['writer_points']}, "
            f"мёртвая {gone['writer_points']} — присутствие исходника всё ещё "
            f"начисляет балл")
    if not (alive["wallet_status"] == "PASS" and gone["wallet_status"] != "PASS"):
        same.append(
            f"вердикт кошелька не различает подпись и метку: по подписи "
            f"{alive['wallet_status']}, по метке {gone['wallet_status']}")
    if not (alive["files_pass"] > 0 and gone["files_pass"] == 0):
        same.append(
            f"обязательные файлы судятся присутствием: PASS при живом писателе "
            f"{alive['files_pass']}, при молчащем {gone['files_pass']}")

    verdict = {"kind": DRIVE_BLIND if same else DRIVE_OK,
               "live": alive, "dead": gone, "same_answers": same}
    if same:
        verdict["reason"] = "; ".join(same)
    return verdict


if __name__ == "__main__":                                          # pragma: no cover
    import sys
    report = drive_both_directions()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit({DRIVE_OK: 0, DRIVE_BLIND: 1, DRIVE_UNMEASURED: 2}[report["kind"]])
