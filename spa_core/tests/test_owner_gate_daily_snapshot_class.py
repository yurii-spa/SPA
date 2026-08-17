"""Класс «ежедневный снимок трека» в owner-gate (ADR-070 п.3, решение владельца 2026-08-07).

АВАРИЯ, которую воспроизводят эти тесты (замер цикла #221, коммит `575e504a7`):
воркфлоу `owner-gate` покраснел на `main` из-за того, что СОБСТВЕННАЯ ежедневная
автоматика Site Custodian сдвинула `end_equity`/`nav_usd` на ОДИН ЦЕНТ:

    [B] landing/src/data/track_snapshot.json:0 snapshot.number () — end_equity: 100863.44 → 100863.45
    [B] landing/src/data/track_snapshot.json:0 snapshot.number () — nav_usd:    100863.44 → 100863.45
    RESULT: GATED — 2 owner-gated change(s) → route to owner card.   (exit 2)

Байтовая custodian-проверка (`_snapshot_is_custodian_equivalent`) в CI не срабатывала
ПО ПОСТРОЕНИЮ: в режиме `git-range` она была прибита к `False`. Значит гейт краснел на
каждом штатном дневном цикле — а сторож, краснеющий ежедневно на честной работе, будет
отключён людьми ровно до того, как покраснеет на настоящем нарушении.

Разрешение УЗКОЕ и держится на двух независимых условиях сразу, поэтому тесты идут
В ОБЕ СТОРОНЫ — каждый «пропускает» имеет парный «заворачивает»:

  ПРОПУСК   штатный дневной цикл (5 полей + канон `data/*.json` того же коммита);
  ЗАВОРОТ   ручная правка того же поля (канон её не воспроизводит);
  ЗАВОРОТ   поле вне пятёрки — `gates_passed` / `real_track_days` / `packages.*` (тиры);
  ЗАВОРОТ   канона в коммите нет (fail-CLOSED, не «раз не знаем — значит можно»);
  ЗАВОРОТ   нейминг тиров / legal / solicitation — гейт не ослаблен нигде вне снимка.

Герметично и офлайн: каждый end-to-end кейс поднимает одноразовый `git init` под
`tmp_path` (реальные `data/` и `landing/` репозитория не читаются и не пишутся), время
ниоткуда не берётся — сравниваются только детерминированные поля снимка. Инвариант #16
соблюдён: ни один существующий тест не ослаблен и не удалён, это добавочный файл.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_MOD = _REPO / "scripts" / "check_owner_gate.py"
_GEN = _REPO / "scripts" / "generate_track_snapshot.py"

_TRACK_SNAPSHOT = "landing/src/data/track_snapshot.json"
_TIER_BANDS = "landing/src/lib/tier_bands.json"


def _load_gate():
    spec = importlib.util.spec_from_file_location("check_owner_gate_daily_mod", _MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _load_gate()


# ── одноразовый репозиторий ─────────────────────────────────────────────────
def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True,
                   capture_output=True, text=True)


def _bars(days: int, step_usd: float) -> list[dict]:
    """Детерминированная книга эквити: `days` evidenced-баров с шагом `step_usd`."""
    out = []
    eq = 100000.0
    for i in range(days):
        eq = round(eq + step_usd, 2)
        out.append({
            "date": f"2026-06-{22 + i:02d}",
            "equity": eq,
            "close_equity": eq,
            "drawdown_pct": 0.0,
            "evidenced": True,
            "source": "cycle",
        })
    return out


def _canon(days: int, step_usd: float) -> dict[str, dict]:
    bars = _bars(days, step_usd)
    return {
        "data/golive_status.json": {
            "real_track_days": days, "total": 29, "passed": 29,
            "target_date": "2026-07-21", "evidenced_anchor": "2026-06-22",
            "min_track_days": 30,
        },
        "data/equity_curve_daily.json": {"bars": bars},
        "data/paper_trading_status.json": {"current_equity": bars[-1]["equity"]},
    }


def _write(repo: Path, rel: str, payload) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        payload if isinstance(payload, str) else json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def _build_snapshot_for(repo: Path) -> dict:
    """Снимок, который выдал бы ежедневный генератор на каноне ИЗ ЭТОГО репозитория."""
    spec = importlib.util.spec_from_file_location(
        f"_gen_ts_{repo.name}", repo / "scripts" / "generate_track_snapshot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build_snapshot(
        golive_path=repo / "data" / "golive_status.json",
        equity_path=repo / "data" / "equity_curve_daily.json",
        pts_path=repo / "data" / "paper_trading_status.json",
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Репозиторий с ОДНИМ базовым коммитом: канон 3 дня + сгенерированный снимок."""
    r = tmp_path / "repo"
    (r / "scripts").mkdir(parents=True)
    shutil.copy2(_GEN, r / "scripts" / "generate_track_snapshot.py")
    _git(r.parent, "init", "-q", str(r))
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")

    for rel, payload in _canon(days=3, step_usd=10.0).items():
        _write(r, rel, payload)
    _write(r, _TRACK_SNAPSHOT, _build_snapshot_for(r))
    _write(r, _TIER_BANDS, {"conservative": {"key": "conservative", "en": "Preserve",
                                             "band_en": "4-6% net APY"}})
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    return r


def _run(repo: Path, commit_message: str | None = None) -> dict:
    return G.check_owner_gate(
        diff_mode="git-range", base="HEAD~1", head="HEAD",
        commit_message=commit_message, repo_root=repo,
    )


def _snapshot_violations(report: dict) -> list[dict]:
    return [v for v in report["violations"] if v["file"] == _TRACK_SNAPSHOT]


# ── ПРОПУСК: штатный дневной цикл ───────────────────────────────────────────
def test_daily_cycle_commit_is_not_gated(repo: Path):
    """Канон и снимок уехали вместе, как их двигает цикл → CLEAN (было: GATED).

    Замер по 53 реальным коммитам снимка: ежедневно двигаются `end_equity`/`nav_usd`
    (27), `paper_apy_pct` (25), `total_return_pct` (17) — ровно то, что закрывает
    пятёрка. Фикстура двигает книгу эквити, не длину трека.
    """
    for rel, payload in _canon(days=3, step_usd=10.5).items():
        _write(repo, rel, payload)
    _write(repo, _TRACK_SNAPSHOT, _build_snapshot_for(repo))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm",
         "chore(site-custodian): auto-deploy fresh track_snapshot after daily cycle")

    report = _run(repo)
    assert _snapshot_violations(report) == []
    assert report["ok"] is True
    # Разрешение обязано быть ВИДНЫМ, а не молчаливым.
    assert set(report["snapshot_daily_fields_reproduced"]) >= {"end_equity", "nav_usd"}


def test_one_cent_move_is_not_gated(repo: Path):
    """Дословная авария цикла #221: сдвиг на один цент больше не тревога."""
    for rel, payload in _canon(days=3, step_usd=10.01).items():
        _write(repo, rel, payload)
    _write(repo, _TRACK_SNAPSHOT, _build_snapshot_for(repo))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "daily cycle")

    before = json.loads(subprocess.run(
        ["git", "show", f"HEAD~1:{_TRACK_SNAPSHOT}"], cwd=str(repo),
        capture_output=True, text=True).stdout)
    after = json.loads((repo / _TRACK_SNAPSHOT).read_text(encoding="utf-8"))
    assert before["end_equity"] != after["end_equity"], "фикстура обязана двигать число"

    assert _snapshot_violations(_run(repo)) == []


# ── ЗАВОРОТ: то же поле, но правил человек ──────────────────────────────────
def test_hand_edited_number_still_gates(repo: Path):
    """Канон НЕ двигали, число в снимке подменили руками → GATED (гейт не ослаблен)."""
    snap = json.loads((repo / _TRACK_SNAPSHOT).read_text(encoding="utf-8"))
    snap["end_equity"] = 142000.0
    snap["nav_usd"] = 142000.0
    _write(repo, _TRACK_SNAPSHOT, snap)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "chore(site-custodian): auto-deploy fresh track_snapshot")

    report = _run(repo)
    gated = {v["matched_text"].split(":")[0] for v in _snapshot_violations(report)}
    assert {"end_equity", "nav_usd"} <= gated
    assert report["ok"] is False
    # Подменённые поля разрешения НЕ получили (нетронутые — могли, они и не в диффе).
    assert not {"end_equity", "nav_usd"} & set(report["snapshot_daily_fields_reproduced"])


def test_hand_edited_apy_on_top_of_a_real_daily_cycle_still_gates(repo: Path):
    """Самый коварный случай: настоящий дневной коммит, а внутри него подкручен APY.

    Честные поля разрешение получают, подкрученное — нет. Разрешение поштучное,
    а не «весь файл целиком».
    """
    for rel, payload in _canon(days=4, step_usd=10.0).items():
        _write(repo, rel, payload)
    snap = _build_snapshot_for(repo)
    snap["paper_apy_pct"] = 30.0          # ← рука человека
    _write(repo, _TRACK_SNAPSHOT, snap)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "daily cycle")

    report = _run(repo)
    gated = {v["matched_text"].split(":")[0] for v in _snapshot_violations(report)}
    assert "paper_apy_pct" in gated
    assert "end_equity" not in gated and "nav_usd" not in gated
    assert report["ok"] is False


# ── ЗАВОРОТ: поля ВНЕ пятёрки ───────────────────────────────────────────────
def test_fields_outside_the_five_still_gate(repo: Path):
    """`gates_passed` / `real_track_days` — вехи go-live, под ADR-070 п.3 не подпадают."""
    canon = _canon(days=5, step_usd=10.0)
    canon["data/golive_status.json"]["passed"] = 20
    canon["data/golive_status.json"]["total"] = 40
    for rel, payload in canon.items():
        _write(repo, rel, payload)
    _write(repo, _TRACK_SNAPSHOT, _build_snapshot_for(repo))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "daily cycle")

    gated = {v["matched_text"].split(":")[0] for v in _snapshot_violations(_run(repo))}
    assert {"real_track_days", "gates_passed", "gates_total"} <= gated


def test_tier_package_numbers_still_gate(repo: Path):
    """`packages.*` — числа карточек тиров, owner-gated по site-copy. Вложенные поля
    разрешения не получают НИКОГДА, даже если названы `apy_pct`."""
    _write(repo, "data/tier1_packages.json",
           {"packages": {"conservative": {"blended_net_apy_pct": 12.0, "worst_dd_pct": -1.0}}})
    _write(repo, _TRACK_SNAPSHOT, _build_snapshot_for(repo))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "daily cycle")

    gated = {v["matched_text"].split(":")[0] for v in _snapshot_violations(_run(repo))}
    assert "packages.conservative.apy_pct" in gated


# ── ЗАВОРОТ: канона нет → fail-CLOSED ───────────────────────────────────────
def test_missing_canon_gates_as_before(repo: Path):
    """Канон удалён из коммита — разрешение не выдаётся (не «раз не знаем, значит можно»)."""
    for rel, payload in _canon(days=4, step_usd=10.0).items():
        _write(repo, rel, payload)
    _write(repo, _TRACK_SNAPSHOT, _build_snapshot_for(repo))
    _git(repo, "rm", "-q", "-f", "data/equity_curve_daily.json")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "daily cycle")

    report = _run(repo)
    assert report["snapshot_daily_fields_reproduced"] == []
    assert {"end_equity", "nav_usd"} <= {
        v["matched_text"].split(":")[0] for v in _snapshot_violations(report)}


def test_missing_generator_gates_as_before(repo: Path):
    """Нет `generate_track_snapshot.py` — пересчитать нечем, значит гейт как раньше."""
    (repo / "scripts" / "generate_track_snapshot.py").unlink()
    assert G._canon_reproduced_fields(repo, "HEAD", {"end_equity": 1.0}) == frozenset()


# ── ЗАВОРОТ: гейт не ослаблен ВНЕ снимка ────────────────────────────────────
def test_tier_naming_and_solicitation_still_gate(repo: Path):
    """Положительный контроль «не сломали остальное»: нейминг тира (класс C) и
    solicitation-строка (класс A) заворачиваются, как и до правки."""
    bands = json.loads((repo / _TIER_BANDS).read_text(encoding="utf-8"))
    bands["conservative"]["en"] = "Guaranteed Income"
    _write(repo, _TIER_BANDS, bands)
    _write(repo, "landing/src/pages/offer.astro",
           "<p>Minimum investment 10 000 USDC, withdrawals within 3 days.</p>\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "copy")

    report = _run(repo)
    klasses = {v["klass"] for v in report["violations"]}
    assert "C" in klasses and "A" in klasses
    assert report["ok"] is False


# ── единица: сам фильтр разрешения ──────────────────────────────────────────
def test_reproduced_default_keeps_old_behaviour():
    """Без набора `reproduced` функция ведёт себя ровно как до правки."""
    assert G._track_snapshot_violations(
        {"end_equity": 1.0}, {"end_equity": 2.0}, exempt=False) != []


def test_reproduced_only_covers_the_five_declared_fields():
    """Разрешение не расширяется подсовыванием чужого имени в `reproduced`."""
    assert G._TS_DAILY_CYCLE_FIELDS == frozenset(
        {"end_equity", "nav_usd", "paper_apy_pct", "max_drawdown_pct", "total_return_pct"}
    )
    v = G._track_snapshot_violations(
        {"real_track_days": 10}, {"real_track_days": 11},
        exempt=False, reproduced=("real_track_days", "gates_passed"),
    )
    assert len(v) == 1 and "real_track_days" in v[0]["matched_text"]
