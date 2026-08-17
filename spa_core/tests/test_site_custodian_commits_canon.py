# FROZEN-DATE-OK: даты здесь — СОДЕРЖИМОЕ фикстуры трека (ряд баров с якоря 2026-06-22),
# то есть вход детерминированного `build_snapshot`, а не понятие свежести. Ни один ассерт
# в файле не спрашивает часы и не судит о возрасте: проверяется только «воспроизводится ли
# число снимка из канона того же коммита», а этот ответ от календаря не зависит.
"""Сторож сайта обязан класть канон трека в ТОТ ЖЕ коммит, что и снимок (ADR-070 п.2).

АВАРИЯ, которую воспроизводят эти тесты (замер 2026-08-16, карточка владельца
`owner-decision-storozh-saita-ne-kladet-v-git-dannye-iz`, выбран вариант 1):

* шесть последних коммитов `deploy_site_snapshot.py` содержали НОЛЬ файлов из `data/` —
  уезжал только готовый снимок `landing/src/data/track_snapshot.json`;
* поэтому сайт публиковал `real_track_days: 53` и `gates_passed: 29/29`, а свежайший
  канон в git был от 04.07 с `real_track_days: 13` и `passed: 27/29`. Числа сайта, скорее
  всего, верные — но проверить их из репозитория нельзя, и скептик получает ровно
  «поверьте на слово», ради отказа от которого честный трек и затевался;
* owner-gate при этом краснел КАЖДУЮ НОЧЬ на честной работе. Починка «пересчитать
  изменившееся число из канона и пропустить только совпавшее» (`_canon_reproduced_fields`,
  ADR-070 п.3) уже стояла в коде и БЕЗДЕЙСТВОВАЛА: пересчитывать было не из чего, и по
  fail-CLOSED гейт заворачивал штатную ночную доставку.

Тесты идут В ОБЕ СТОРОНЫ, и второй важнее первого — он доказывает, что гейт ОЖИВИЛИ,
а не ослабили:

  ПРОПУСК   честный ночной коммит (канон + снимок вместе, числа пересчитываются) → CLEAN;
  ЗАВОРОТ   подделка (канон не тронут, число в снимке правлено руками)          → GATED;
  ЗАВОРОТ   доставка БЕЗ канона — дословно вчерашнее поведение кастодиана        → GATED.

Плюс контроль самой доставки: набор файлов пуша закрыт (снимок + ровно три файла канона,
ничего больше из `data/`), список совпадает с входами `build_snapshot` и с
`check_owner_gate._TS_CANON_FILES`, а отсутствие/сдвиг канона отменяет доставку (fail-CLOSED).

Герметично и офлайн: git-репозиторий одноразовый под `tmp_path`, подпроцессы доставки
подменены, реальные `data/` и `landing/` репозитория не читаются и не пишутся.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

_REPO = Path(__file__).resolve().parents[2]
_GEN = _REPO / "scripts" / "generate_track_snapshot.py"
_GATE = _REPO / "scripts" / "check_owner_gate.py"
_DEPLOY = _REPO / "scripts" / "deploy_site_snapshot.py"
_TRACK_SNAPSHOT = "landing/src/data/track_snapshot.json"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DEPLOY = _load("deploy_site_snapshot_canon_mod", _DEPLOY)
GATE = _load("check_owner_gate_canon_mod", _GATE)


# ── фикстуры канона ─────────────────────────────────────────────────────────
def _bars(days: int, step_usd: float) -> list[dict]:
    out, eq = [], 100000.0
    for i in range(days):
        eq = round(eq + step_usd, 2)
        out.append({
            "date": f"2026-06-{22 + i:02d}", "equity": eq, "close_equity": eq,
            "drawdown_pct": 0.0, "evidenced": True, "source": "cycle",
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
        # Четвёртый вход (ADR-093 п.3): из него собираются `packages.*` — net-APY и
        # worst-DD карточек тиров на главной, owner-gated класс «числа доходности».
        "data/tier1_packages.json": {"packages": {
            "conservative": {"blended_net_apy_pct": 4.1, "worst_dd_pct": -0.3},
            "balanced": {"blended_net_apy_pct": 6.2, "worst_dd_pct": -1.4},
            "aggressive": {"blended_net_apy_pct": 9.3, "worst_dd_pct": -4.5},
        }},
    }


def _write(root: Path, rel: str, payload) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(payload if isinstance(payload, str) else json.dumps(payload, indent=2),
                 encoding="utf-8")


# ── часть 1: ДОСТАВКА (что именно уезжает в коммите) ────────────────────────
class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class _Deploy:
    """Прогон `deploy_site_snapshot.main()` с подменёнными подпроцессами."""

    def __init__(self, root: Path):
        self.root = root
        self.calls: list[list[str]] = []
        self.printed: list[str] = []
        self.snap = root / _TRACK_SNAPSHOT

    def run(self, *, origin=None, before_push=None) -> int:
        def fake_run(cmd, *a, **kw):
            self.calls.append([str(c) for c in cmd])
            if str(cmd[1]).endswith("generate_track_snapshot.py"):
                return _Result(0, "regenerated", "")
            return _Result(0, "pushed", "")

        def fake_origin():
            if before_push is not None:
                before_push()
            return origin

        with mock.patch.object(DEPLOY, "_ROOT", self.root), \
             mock.patch.object(DEPLOY, "_SNAP", self.snap), \
             mock.patch.object(DEPLOY.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(DEPLOY, "_origin_snapshot", side_effect=fake_origin), \
             mock.patch("builtins.print",
                        side_effect=lambda *a, **k: self.printed.append(
                            " ".join(str(x) for x in a))):
            return DEPLOY.main()

    @property
    def push_cmd(self) -> list[str]:
        for c in self.calls:
            if not str(c[1]).endswith("generate_track_snapshot.py"):
                return c
        return []

    @property
    def pushed(self) -> list[str]:
        cmd = self.push_cmd
        out: list[str] = []
        for token in cmd[cmd.index("--files") + 1:] if "--files" in cmd else []:
            if token.startswith("--"):
                break
            out.append(token)
        return out

    @property
    def log(self) -> str:
        return "\n".join(self.printed)


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    """Дерево с готовым снимком и полным каноном на диске."""
    root = tmp_path / "tree"
    for rel, payload in _canon(days=3, step_usd=10.0).items():
        _write(root, rel, payload)
    _write(root, _TRACK_SNAPSHOT, {"real_track_days": 3, "end_equity": 100030.0})
    return root


def test_canon_travels_in_the_same_commit(tree: Path):
    """Снимок и три файла канона — ОДИН пуш, значит один коммит (иначе гейт их не свяжет)."""
    d = _Deploy(tree)
    assert d.run() == 0
    pushed = [Path(p).name for p in d.pushed]
    assert pushed[0] == "track_snapshot.json"
    assert set(pushed[1:]) == {Path(rel).name for rel in DEPLOY._CANON}
    pushes = [c for c in d.calls if not str(c[1]).endswith("generate_track_snapshot.py")]
    assert len(pushes) == 1, "два пуша = два коммита; гейту нужна пара «снимок ↔ канон» в одном"
    assert d.push_cmd[1].endswith("scripts/safe_site_push.py"), \
        "landing/** уезжает только через санкционированную обёртку"


def test_nothing_else_from_data_travels(tree: Path):
    """Список закрыт: живой трек целиком в git не возят (цена решения — три файла)."""
    _write(tree, "data/risk_scores.json", {"noise": 1})
    d = _Deploy(tree)
    d.run()
    data_dir = str(tree / "data") + "/"
    extra = [p for p in d.pushed
             if p.replace("\\", "/").startswith(data_dir)
             and not any(p.replace("\\", "/").endswith(rel) for rel in DEPLOY._CANON)]
    assert extra == [], f"в коммит сайта попали лишние файлы из data/: {extra}"


def test_canon_list_matches_the_generator_inputs():
    """Возим РОВНО то, что читает `build_snapshot`, — и то же, что ждёт owner-gate.

    Три списка обязаны совпадать, иначе снова получится «починка, которая бездействует»:
    гейт пересчитывает из одного набора, кастодиан везёт другой.
    """
    gen = _load("generate_track_snapshot_canon_mod", _GEN)
    import inspect

    params = set(inspect.signature(gen.build_snapshot).parameters)
    assert {"golive_path", "equity_path", "pts_path", "packages_path"} <= params
    assert tuple(DEPLOY._CANON) == tuple(rel for _, rel in GATE._TS_CANON_FILES)
    assert DEPLOY._CANON_OPTIONAL == GATE._TS_CANON_OPTIONAL


def _measure_data_reads(gen, root: Path) -> list[str]:
    """Фактические чтения `build_snapshot` из `data/` — перехватом, а не чтением шапки."""
    import builtins

    seen: list[str] = []
    orig_open, orig_rt = builtins.open, Path.read_text

    def rec(target) -> None:
        try:
            rel = Path(target).resolve().relative_to(root)
        except (ValueError, OSError, TypeError):
            return
        if str(rel).startswith("data/") and str(rel) not in seen:
            seen.append(str(rel))

    def open_hook(file, mode="r", *a, **k):
        if "r" in mode and "+" not in mode:
            rec(file)
        return orig_open(file, mode, *a, **k)

    def rt_hook(self, *a, **k):
        rec(self)
        return orig_rt(self, *a, **k)

    try:
        builtins.open, Path.read_text = open_hook, rt_hook
        gen.build_snapshot()
    finally:
        builtins.open, Path.read_text = orig_open, orig_rt
    return seen


def test_canon_list_covers_measured_reads(tmp_path: Path):
    """ХРАПОВИК: состав канона определяется ЗАМЕРОМ чтений, а не документацией.

    Ровно на этом сломалась первая доставка ADR-070 п.2: список канона переписали из
    шапки генератора («Source of truth» — два файла) и из сигнатуры `build_snapshot`,
    а фактических чтений никто не замерил. Мимо прошёл `data/tier1_packages.json` —
    из него собираются `packages.*`, net-APY и worst-DD карточек тиров на главной,
    то есть прямо owner-gated класс «числа доходности». Итог тот же, что и до починки:
    число опубликовано, подтвердить его из репозитория нечем.

    Тест ловит ЛЮБОЙ новый вход из `data/`, не попавший в `_CANON`, — включая
    прочитанный из вложенной функции, мимо параметров `build_snapshot`.
    """
    gen = _load("generate_track_snapshot_measured_mod", _GEN)
    root = tmp_path / "measured"
    for rel, payload in _canon(days=3, step_usd=10.0).items():
        _write(root, rel, payload)
    _write(root, _TRACK_SNAPSHOT, {"degraded": False})
    # Генератор считает пути от собственного ROOT — переселяем его в одноразовое дерево,
    # чтобы замер видел относительные пути и не трогал живой `data/` репозитория.
    for name, value in (("ROOT", root), ("GOLIVE", root / "data" / "golive_status.json"),
                        ("EQUITY", root / "data" / "equity_curve_daily.json"),
                        ("PTS", root / "data" / "paper_trading_status.json"),
                        ("PACKAGES", root / "data" / "tier1_packages.json"),
                        ("OUT", root / _TRACK_SNAPSHOT)):
        setattr(gen, name, value)

    measured = _measure_data_reads(gen, root)
    assert measured, "замер не увидел ни одного чтения — сломан сам перехват, а не канон"
    missed = [rel for rel in measured if rel not in DEPLOY._CANON]
    assert missed == [], (
        f"`build_snapshot` читает из data/ файлы, которых нет в `_CANON`: {missed}. "
        f"Их числа уедут на сайт непроверяемыми — добавить в `_CANON`, "
        f"`check_owner_gate._TS_CANON_FILES` и негацию в `.gitignore`."
    )


def test_measurement_ratchet_catches_a_new_unlisted_input(tmp_path: Path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ самого храповика: подсовываем пятый вход — обязан покраснеть.

    Без этого предыдущий тест — украшение: он бы одинаково молчал и на здоровом
    генераторе, и на сломанном перехвате.
    """
    gen = _load("generate_track_snapshot_regress_mod", _GEN)
    root = tmp_path / "regress"
    for rel, payload in _canon(days=3, step_usd=10.0).items():
        _write(root, rel, payload)
    _write(root, "data/some_new_feed.json", {"apy_pct": 12.5})
    _write(root, _TRACK_SNAPSHOT, {"degraded": False})
    for name, value in (("ROOT", root), ("GOLIVE", root / "data" / "golive_status.json"),
                        ("EQUITY", root / "data" / "equity_curve_daily.json"),
                        ("PTS", root / "data" / "paper_trading_status.json"),
                        ("PACKAGES", root / "data" / "tier1_packages.json"),
                        ("OUT", root / _TRACK_SNAPSHOT)):
        setattr(gen, name, value)
    # ровно то, что сделал бы автор нового поля: тихо дочитать ещё один файл из data/
    original = gen.build_snapshot

    def build_with_new_input(*a, **k):
        snap = original(*a, **k)
        snap["shiny_apy"] = gen._load(root / "data" / "some_new_feed.json").get("apy_pct")
        return snap

    gen.build_snapshot = build_with_new_input
    measured = _measure_data_reads(gen, root)
    assert "data/some_new_feed.json" in measured
    assert [rel for rel in measured if rel not in DEPLOY._CANON] == ["data/some_new_feed.json"]


def test_missing_canon_refuses_delivery(tree: Path):
    """Fail-CLOSED: нечем подтвердить число ⇒ не публикуем вовсе."""
    (tree / "data" / "paper_trading_status.json").unlink()
    d = _Deploy(tree)
    assert d.run() == 1
    assert d.push_cmd == [], "снимок без канона снова стал бы непроверяемым числом"
    assert "канона нет на диске" in d.log


def test_canon_changed_after_generation_refuses(tree: Path):
    """Пара «снимок ↔ канон» обязана быть согласованной: разъехалась — не везём."""
    def touch():
        _write(tree, "data/golive_status.json", {"real_track_days": 999, "total": 29,
                                                 "passed": 29})

    d = _Deploy(tree)
    assert d.run(before_push=touch) == 1
    assert d.push_cmd == []
    assert "канон изменился" in d.log


def test_tier_packages_canon_travels_too(tree: Path):
    """Четвёртый вход едет тем же коммитом — иначе числа карточек тиров непроверяемы."""
    d = _Deploy(tree)
    assert d.run() == 0
    assert "data/tier1_packages.json" in DEPLOY._CANON
    assert any(p.endswith("tier1_packages.json") for p in d.pushed), \
        "packages.* (net-APY карточек тиров) опубликованы без канона в том же коммите"


def test_absent_optional_canon_still_delivers(tree: Path):
    """ПРОПУСК: файла нет ⇒ чисел он не давал (карточки показывают «—») ⇒ везём остальное.

    Требовать его безусловно значило бы глушить публикацию честных чисел трека там, где
    tier-1 пайплайн ещё не отработал, — а выключенный сторож не защищает ни от чего.
    """
    (tree / "data" / "tier1_packages.json").unlink()
    _write(tree, _TRACK_SNAPSHOT, {"real_track_days": 3, "packages": {
        "conservative": {"apy_pct": None, "dd_pct": None}}})
    d = _Deploy(tree)
    assert d.run() == 0, d.log
    assert not any(p.endswith("tier1_packages.json") for p in d.pushed)
    assert any(p.endswith("golive_status.json") for p in d.pushed)


def test_absent_optional_canon_with_a_baked_number_refuses(tree: Path):
    """ЗАВОРОТ: канона нет, а число в снимке ЕСТЬ — ровно непроверяемая цифра, не везём.

    Это контроль на то, что послабление выше не превратилось в дыру: разрешено не
    «отсутствие файла», а «отсутствие числа».
    """
    (tree / "data" / "tier1_packages.json").unlink()
    _write(tree, _TRACK_SNAPSHOT, {"real_track_days": 3, "packages": {
        "aggressive": {"apy_pct": 9.3, "dd_pct": -4.5}}})
    d = _Deploy(tree)
    assert d.run() == 1
    assert d.push_cmd == []
    assert "подтвердить их нечем" in d.log
    assert "packages.aggressive.apy_pct" in d.log


def test_canon_is_not_gitignored():
    """`data/` игнорируется целиком — канону нужна явная негация, иначе он не доедет."""
    for rel in DEPLOY._CANON:
        rc = subprocess.run(["git", "check-ignore", "--no-index", "-q", rel],
                            cwd=str(_REPO), capture_output=True).returncode
        assert rc != 0, f"{rel} игнорируется .gitignore — сторож не сможет его закоммитить"
    rc = subprocess.run(["git", "check-ignore", "--no-index", "-q", "data/some_runtime_state.json"],
                        cwd=str(_REPO), capture_output=True).returncode
    assert rc == 0, "негация не имеет права открыть весь data/ — там живой трек"


# ── часть 2: OWNER-GATE на получившемся коммите (в обе стороны) ─────────────
def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)


def _build_snapshot_for(repo: Path) -> dict:
    mod = _load(f"_gen_ts_{repo.name}", repo / "scripts" / "generate_track_snapshot.py")
    # Каждый вход — явным путём в ЭТОТ репозиторий: иначе генератор возьмёт значение из
    # рабочего дерева настоящего SPA, и тест будет проверять не то, что думает.
    return mod.build_snapshot(
        golive_path=repo / "data" / "golive_status.json",
        equity_path=repo / "data" / "equity_curve_daily.json",
        pts_path=repo / "data" / "paper_trading_status.json",
        packages_path=repo / "data" / "tier1_packages.json",
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Одноразовый репозиторий: базовый коммит = канон 3 дня + сгенерированный снимок."""
    r = tmp_path / "repo"
    (r / "scripts").mkdir(parents=True)
    (r / "scripts" / "generate_track_snapshot.py").write_bytes(_GEN.read_bytes())
    _git(r.parent, "init", "-q", str(r))
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    for rel, payload in _canon(days=3, step_usd=10.0).items():
        _write(r, rel, payload)
    _write(r, _TRACK_SNAPSHOT, _build_snapshot_for(r))
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    return r


def _gate(repo: Path) -> dict:
    return GATE.check_owner_gate(diff_mode="git-range", base="HEAD~1", head="HEAD",
                                commit_message=None, repo_root=repo)


def _snapshot_violations(report: dict) -> list[dict]:
    return [v for v in report["violations"] if v["file"] == _TRACK_SNAPSHOT]


def _nightly(repo: Path, *, days: int, step_usd: float, commit_canon: bool) -> None:
    """Ночной прогон кастодиана: канон двигается, снимок пересобирается из НЕГО.

    `commit_canon=False` — дословно вчерашнее поведение (в коммит уехал только снимок).
    """
    for rel, payload in _canon(days=days, step_usd=step_usd).items():
        _write(repo, rel, payload)
    _write(repo, _TRACK_SNAPSHOT, _build_snapshot_for(repo))
    paths = [_TRACK_SNAPSHOT] + ([*DEPLOY._CANON] if commit_canon else [])
    _git(repo, "add", "--", *paths)
    _git(repo, "commit", "-qm",
         "chore(site-custodian): auto-deploy fresh track_snapshot after daily cycle")


def test_honest_nightly_commit_is_clean(repo: Path):
    """ПРОПУСК: канон и снимок уехали вместе — число пересчиталось и сошлось → CLEAN."""
    _nightly(repo, days=3, step_usd=10.5, commit_canon=True)
    report = _gate(repo)
    assert _snapshot_violations(report) == []
    assert report["ok"] is True
    # Разрешение обязано быть ВИДИМЫМ, а не молчаливым «нарушений нет».
    assert {"end_equity", "nav_usd"} <= set(report["snapshot_daily_fields_reproduced"])


def test_forged_number_is_still_gated(repo: Path):
    """ЗАВОРОТ (важнее первого): канон не тронут, число в снимке правлено руками → GATED."""
    snap = json.loads((repo / _TRACK_SNAPSHOT).read_text(encoding="utf-8"))
    snap["end_equity"] = 142000.0
    snap["nav_usd"] = 142000.0
    snap["paper_apy_pct"] = 30.0
    _write(repo, _TRACK_SNAPSHOT, snap)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm",
         "chore(site-custodian): auto-deploy fresh track_snapshot after daily cycle")

    report = _gate(repo)
    gated = {v["matched_text"].split(":")[0] for v in _snapshot_violations(report)}
    assert {"end_equity", "nav_usd", "paper_apy_pct"} <= gated
    assert report["ok"] is False
    assert not {"end_equity", "nav_usd", "paper_apy_pct"} & set(
        report["snapshot_daily_fields_reproduced"])


def test_forgery_hidden_inside_an_honest_nightly_commit_is_gated(repo: Path):
    """Самый коварный случай: настоящий ночной коммит с каноном, а APY подкручен рукой."""
    for rel, payload in _canon(days=4, step_usd=10.0).items():
        _write(repo, rel, payload)
    snap = _build_snapshot_for(repo)
    snap["paper_apy_pct"] = 30.0
    _write(repo, _TRACK_SNAPSHOT, snap)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "daily cycle")

    report = _gate(repo)
    gated = {v["matched_text"].split(":")[0] for v in _snapshot_violations(report)}
    assert "paper_apy_pct" in gated
    assert "end_equity" not in gated, "честные поля коммита разрешение получают"
    assert report["ok"] is False


def test_reproduction_reads_the_commit_not_the_working_tree(repo: Path):
    """Пересчёт обязан брать канон ИЗ КОММИТА, а не из дерева проверяющей машины.

    До ADR-093 п.3 `_tier_packages` читала модульный `ROOT`, поэтому `packages.*`
    приходили из рабочего дерева независимо от проверяемого коммита: воспроизведение
    ВЫГЛЯДЕЛО герметичным, не будучи им. Здесь канон коммита и дерева расходятся
    намеренно — пересчёт обязан согласиться с коммитом.
    """
    _nightly(repo, days=4, step_usd=11.0, commit_canon=True)
    committed = _build_snapshot_for(repo)
    # дерево уезжает в сторону ПОСЛЕ коммита — на результат пересчёта влиять не должно
    _write(repo, "data/tier1_packages.json", {"packages": {
        "aggressive": {"blended_net_apy_pct": 99.0, "worst_dd_pct": -0.1}}})

    gen = _load("_gen_ts_hermetic", repo / "scripts" / "generate_track_snapshot.py")
    from_commit = GATE._canon_reproduced_fields(repo, "HEAD", committed)
    assert {"end_equity", "nav_usd"} <= set(from_commit)

    forged = dict(committed)
    forged["packages"] = {"aggressive": {"apy_pct": 99.0, "dd_pct": -0.1}}
    rebuilt = gen.build_snapshot(
        golive_path=repo / "data" / "golive_status.json",
        equity_path=repo / "data" / "equity_curve_daily.json",
        pts_path=repo / "data" / "paper_trading_status.json",
        packages_path=repo / "data" / "nonexistent_packages.json",
    )
    assert rebuilt["packages"]["aggressive"] == {"apy_pct": None, "dd_pct": None}, \
        "нет файла ⇒ обязаны быть null'ы, а не подхваченное из дерева число"


def test_delivery_without_canon_is_gated_as_before(repo: Path):
    """ЗАВОРОТ и одновременно доказательство, что чинили именно ДОСТАВКУ.

    Тот же самый честный ночной снимок, но канон в коммит не положили — ровно то, что
    делал кастодиан до ADR-070 п.2. Гейт по fail-CLOSED заворачивает: пересчитывать не
    из чего. Значит зелёный `test_honest_nightly_commit_is_clean` даёт именно доставка
    канона, а не ослабление гейта.
    """
    _nightly(repo, days=3, step_usd=10.5, commit_canon=False)
    report = _gate(repo)
    gated = {v["matched_text"].split(":")[0] for v in _snapshot_violations(report)}
    assert {"end_equity", "nav_usd"} <= gated
    assert report["ok"] is False
    # Разрешения на ДВИНУВШИЕСЯ поля нет — пересчитать их не из чего. (Поле, которое
    # в фикстуре не менялось, например `max_drawdown_pct`, может совпасть и со старым
    # каноном; это не разрешение на публикацию новых чисел, и оно ничего не снимает.)
    assert not {"end_equity", "nav_usd"} & set(report["snapshot_daily_fields_reproduced"])
