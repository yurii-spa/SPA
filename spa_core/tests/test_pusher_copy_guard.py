"""
spa_core/tests/test_pusher_copy_guard.py

Гейт против рецидива: **инструмент доставки, который РАБОТАЕТ, — тот же, что
лежит в дереве отправляемых файлов**.

ЧТО ЛОВИМ (карточка `agent-host-pusher-copy-is-stale`, найдено циклом #53,
закрыто циклом #59). Хост-дерево репозитория дрейфует от `origin` ПО
ПОСТРОЕНИЮ: автономные пуши идут прямо в `origin` через GitHub API, а рабочая
копия остаётся на своей ветке. Измерено 2026-07-31:
`/Users/yuriikulieshov/Documents/SPA_Claude/push_to_github.py` — **379 строк**
против **946** на `origin/main`, `grep -c batch_push` = **0** против **2**, то
есть batch-пути в ней нет вовсе. При этом `CLAUDE.md` инструктировал звать
пушер именно так — `python3 push_to_github.py --files ...` — поэтому сессия,
делавшая ровно то, что написано, получала до-#49 доставку: набор из N файлов
ложился на `main` N коммитами, и промежуточные состояния `main` могли быть
красными (цикл #53 доставил ВОСЕМЬЮ коммитами вместо одного; красным не стало
по везению — порядок коммитов оказался безопасным).

Разовая синхронизация копии лечит симптом: дерево разойдётся снова. Поэтому
здесь пиннится ПОВЕДЕНИЕ: расхождение измеряется и даёт ОТКАЗ (fail-CLOSED,
инвариант #2), а «не измерено» остаётся «не измерено» и НЕ выдаётся за
совпадение (класс дефектов #29/#31/#35–#38/#40) — и при этом не блокирует пуш,
иначе гейт научил бы обходить себя флагом.

Сеть НЕ ТРОГАЕТСЯ ни одним тестом: сверка идёт ДО PAT и до любого запроса —
это тоже проверяется (`test_refusal_happens_before_pat_is_needed`).

Запуск: python3 -m pytest spa_core/tests/test_pusher_copy_guard.py -v
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    """Загрузить модуль пушера по явному пути (как это делает прод-код)."""
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def ptg():
    return _load("_test_toolchain_ptg", "push_to_github.py")


@pytest.fixture()
def batch():
    return _load("_test_toolchain_batch", "push_to_github_batch.py")


def _mktree(tmp_path: Path, name: str, toolchain: dict) -> Path:
    """Настоящее git-дерево с копиями инструмента доставки.

    `toolchain` — {относительный путь: содержимое}; None означает «файла нет».
    """
    top = tmp_path / name
    top.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=top, check=True)
    for rel, text in toolchain.items():
        if text is None:
            continue
        p = top / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return top


def _full(marker: str) -> dict:
    """Полный комплект инструмента доставки с узнаваемым содержимым."""
    return {
        "push_to_github.py": f"# pusher {marker}\n",
        "push_to_github_batch.py": f"# batch {marker}\n",
        "scripts/push_to_github.py": f"# shim {marker}\n",
        "scripts/safe_site_push.py": f"# safe site {marker}\n",
        "scripts/check_owner_gate.py": f"# owner gate {marker}\n",
    }


def _write_file(top: Path, rel: str = "docs/note.md") -> str:
    p = top / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("груз\n", encoding="utf-8")
    return str(p)


# ═════════════════════════════════════════════════════════════════════════════
# 1. Реестр инструмента доставки
# ═════════════════════════════════════════════════════════════════════════════
def test_toolchain_registry_covers_every_delivery_entry_point(ptg):
    """Все ЧЕТЫРЕ входа доставки + owner-gate под сверкой.

    Пушер, batch-CLI и шим — три способа доставить одно и то же; owner-gate
    берётся РЯДОМ с запущенным пушером (`__file__/scripts/check_owner_gate.py`),
    поэтому устаревший инструмент — это ещё и устаревший гейт сайта.
    """
    assert set(ptg.TOOLCHAIN_FILES) == {
        "push_to_github.py",
        "push_to_github_batch.py",
        "scripts/push_to_github.py",
        "scripts/safe_site_push.py",
        "scripts/check_owner_gate.py",
    }


def test_every_registered_file_exists_in_this_repo(ptg):
    """Реестр не должен протухать: несуществующий путь = вечное «не измерено»."""
    missing = [rel for rel in ptg.TOOLCHAIN_FILES if not (ROOT / rel).exists()]
    assert missing == [], f"в реестре пути, которых нет в репо: {missing}"


# ═════════════════════════════════════════════════════════════════════════════
# 2. Измерение расхождения
# ═════════════════════════════════════════════════════════════════════════════
def test_same_tree_has_nothing_to_compare(ptg, tmp_path):
    """Нормальный цикл: пушер и файлы из ОДНОГО дерева ⇒ расхождение невозможно."""
    top = _mktree(tmp_path, "one", _full("A"))
    v = ptg.toolchain_verdict(str(top / "push_to_github.py"), [_write_file(top)])
    assert v["mismatch"] == [] and v["trees"] == [] and v["unchecked"] == []


def test_identical_copies_across_trees_are_not_a_mismatch(ptg, tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: синхронные копии пушем не мешают."""
    runner = _mktree(tmp_path, "runner", _full("A"))
    other = _mktree(tmp_path, "other", _full("A"))
    v = ptg.toolchain_verdict(str(runner / "push_to_github.py"), [_write_file(other)])
    assert v["trees"] == [other.resolve()]
    assert v["mismatch"] == [] and v["unchecked"] == []


def test_stale_pusher_copy_is_named_with_both_sides(ptg, tmp_path):
    """Собственно дефект: запущен один пушер, файлы едут из дерева с другим."""
    runner = _mktree(tmp_path, "runner", _full("НОВЫЙ"))
    other = _mktree(tmp_path, "other", _full("СТАРЫЙ"))
    v = ptg.toolchain_verdict(str(runner / "push_to_github.py"), [_write_file(other)])
    rels = [m["rel"] for m in v["mismatch"]]
    assert "push_to_github.py" in rels
    entry = [m for m in v["mismatch"] if m["rel"] == "push_to_github.py"][0]
    assert entry["runner"].startswith(str(runner)) and entry["tree"].startswith(str(other))
    assert entry["runner_sha"] != entry["tree_sha"], "sha обеих копий обязаны различаться"


def test_stale_owner_gate_alone_is_a_mismatch(ptg, tmp_path):
    """Устаревший ГЕЙТ САЙТА ловится, даже когда оба пушера совпадают.

    Owner-gate уезжает из того же дерева, что и пушер (`safe_site_push.py` →
    `check_owner_gate.py` рядом с ним), поэтому «пушер тот же, а гейт другой» —
    это ровно та дыра, ради которой гейт вообще существует (ADR-OWN-2026-07).
    """
    same = _full("A")
    runner = _mktree(tmp_path, "runner", same)
    stale = dict(same, **{"scripts/check_owner_gate.py": "# owner gate СТАРЫЙ\n"})
    other = _mktree(tmp_path, "other", stale)
    v = ptg.toolchain_verdict(str(runner / "push_to_github.py"), [_write_file(other)])
    assert [m["rel"] for m in v["mismatch"]] == ["scripts/check_owner_gate.py"]


def test_missing_copy_is_unchecked_not_a_mismatch(ptg, tmp_path):
    """Нечего сравнивать ⇒ «не измерено», а не «расхождение» и не «совпало».

    ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ против ложных отказов: чужой/временный репозиторий
    без копий инструмента (так устроены фикстуры соседних сюит) обязан пушиться.
    """
    runner = _mktree(tmp_path, "runner", _full("A"))
    other = _mktree(tmp_path, "other", {})
    v = ptg.toolchain_verdict(str(runner / "push_to_github.py"), [_write_file(other)])
    assert v["mismatch"] == []
    assert len(v["unchecked"]) == len(ptg.TOOLCHAIN_FILES)
    assert all("нечего сравнивать" in r for r in v["unchecked"])
    assert any(str(other) in r for r in v["unchecked"]), "причина обязана называть путь"


def test_path_outside_any_worktree_is_unchecked_verbatim(ptg, tmp_path):
    """Файл вне git-дерева: честная причина, без падения и без вердикта «ок»."""
    runner = _mktree(tmp_path, "runner", _full("A"))
    loose = tmp_path / "loose"
    loose.mkdir()
    stray = loose / "x.md"
    stray.write_text("x\n", encoding="utf-8")
    v = ptg.toolchain_verdict(str(runner / "push_to_github.py"), [str(stray)])
    assert v["mismatch"] == []
    assert any(str(stray) in r for r in v["unchecked"])


def test_unresolvable_runner_tree_is_unchecked(ptg, tmp_path):
    """Дерево самого пушера не определяется — тоже «не измерено», не «ок»."""
    loose = tmp_path / "nowhere"
    loose.mkdir()
    v = ptg.toolchain_verdict(str(loose / "push_to_github.py"), [])
    assert v["runner_top"] is None and v["mismatch"] == [] and v["unchecked"]


def test_each_foreign_tree_is_measured_once(ptg, tmp_path):
    """Много файлов из одного дерева не должны множить одну и ту же находку."""
    runner = _mktree(tmp_path, "runner", _full("A"))
    other = _mktree(tmp_path, "other", _full("B"))
    files = [_write_file(other, f"docs/n{i}.md") for i in range(4)]
    v = ptg.toolchain_verdict(str(runner / "push_to_github.py"), files)
    assert v["trees"] == [other.resolve()]
    assert len(v["mismatch"]) == len(ptg.TOOLCHAIN_FILES)


# ═════════════════════════════════════════════════════════════════════════════
# 3. Решение: отказ (fail-CLOSED) и осознанный обход
# ═════════════════════════════════════════════════════════════════════════════
def test_enforce_refuses_on_measured_mismatch(ptg, tmp_path):
    runner = _mktree(tmp_path, "runner", _full("A"))
    other = _mktree(tmp_path, "other", _full("B"))
    with pytest.raises(ptg.ToolchainMismatch) as exc:
        ptg.enforce_delivery_toolchain([_write_file(other)],
                                       runner_file=str(runner / "push_to_github.py"))
    text = str(exc.value)
    assert "push_to_github.py" in text and str(other) in text
    assert "--allow-toolchain-mismatch" in text, "отказ обязан называть выход из него"


def test_enforce_is_silent_when_copies_match(ptg, tmp_path, capsys):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: на синхронных копиях гейт не шумит и не мешает."""
    runner = _mktree(tmp_path, "runner", _full("A"))
    other = _mktree(tmp_path, "other", _full("A"))
    v = ptg.enforce_delivery_toolchain([_write_file(other)],
                                       runner_file=str(runner / "push_to_github.py"))
    assert v["mismatch"] == []
    assert capsys.readouterr().err == ""


def test_explicit_allow_proceeds_but_still_reports(ptg, tmp_path, capsys):
    """Обход осознанный: пуш продолжается, но расхождение всё равно напечатано."""
    runner = _mktree(tmp_path, "runner", _full("A"))
    other = _mktree(tmp_path, "other", _full("B"))
    v = ptg.enforce_delivery_toolchain([_write_file(other)], allow=True,
                                       runner_file=str(runner / "push_to_github.py"))
    assert v["mismatch"], "разрешение обхода не должно ГАСИТЬ измерение"
    assert "ОТКАЗ" in capsys.readouterr().err


def test_unchecked_is_printed_not_swallowed(ptg, tmp_path, capsys):
    """«Не измерено» обязано быть видно — молчаливого «всё ок» здесь нет."""
    runner = _mktree(tmp_path, "runner", _full("A"))
    other = _mktree(tmp_path, "other", {})
    ptg.enforce_delivery_toolchain([_write_file(other)],
                                   runner_file=str(runner / "push_to_github.py"))
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().err


# ═════════════════════════════════════════════════════════════════════════════
# 4. CLI обоих пушеров: отказ ДО доставки и до сети
# ═════════════════════════════════════════════════════════════════════════════
def _run_cli(mod, monkeypatch, argv, runner_top: Path, module_rel="push_to_github.py"):
    """Прогнать main() с подменённым «где лежит запущенный инструмент»."""
    calls = {"batch": [], "push_file": [], "pat": 0}

    def fake_batch(*a, **k):
        calls["batch"].append(a)
        return {"ok": True, "count": 1, "commit": "c" * 40, "skipped": 0,
                "files": [], "skipped_files": []}

    def fake_push_file(pat, f, *a, **k):
        calls["push_file"].append(f)
        return {"ok": True, "path": str(f), "sha": "abcdef12"}

    def fake_pat():
        calls["pat"] += 1
        return "pat"

    monkeypatch.setattr(mod, "batch_push", fake_batch, raising=False)
    monkeypatch.setattr(mod, "push_file", fake_push_file, raising=False)
    monkeypatch.setattr(mod, "get_pat", fake_pat, raising=False)
    monkeypatch.setattr(mod, "__file__", str(runner_top / module_rel))
    monkeypatch.delenv("SPA_PUSH_ALLOW_TOOLCHAIN_MISMATCH", raising=False)
    monkeypatch.setattr(sys, "argv", [module_rel, *argv])
    with pytest.raises(SystemExit) as exc:
        mod.main()
    return calls, exc.value.code


def test_cli_refuses_and_delivers_nothing(ptg, tmp_path, monkeypatch):
    """Главный пин: устаревший инструмент НЕ доставляет — ни батчем, ни по одному."""
    runner = _mktree(tmp_path, "runner", _full("A"))
    other = _mktree(tmp_path, "other", _full("B"))
    files = [_write_file(other, f"docs/n{i}.md") for i in range(3)]
    calls, code = _run_cli(ptg, monkeypatch, ["--files", *files, "--message", "m"], runner)
    assert code == 5
    assert calls["batch"] == [] and calls["push_file"] == []


def test_refusal_happens_before_pat_is_needed(ptg, tmp_path, monkeypatch):
    """Сверка идёт ДО секрета и до сети — иначе она бы ничего не экономила."""
    runner = _mktree(tmp_path, "runner", _full("A"))
    other = _mktree(tmp_path, "other", _full("B"))
    calls, code = _run_cli(ptg, monkeypatch,
                           ["--files", _write_file(other), "--message", "m"], runner)
    assert code == 5 and calls["pat"] == 0


def test_cli_dry_run_refuses_too(ptg, tmp_path, monkeypatch):
    """`--dry-run` — превью настоящего пуша: оно обязано показывать тот же отказ."""
    runner = _mktree(tmp_path, "runner", _full("A"))
    other = _mktree(tmp_path, "other", _full("B"))
    files = [_write_file(other, f"docs/n{i}.md") for i in range(2)]
    calls, code = _run_cli(ptg, monkeypatch,
                           ["--files", *files, "--message", "m", "--dry-run"], runner)
    assert code == 5 and calls["batch"] == [] and calls["push_file"] == []


def test_cli_flag_allows_conscious_push(ptg, tmp_path, monkeypatch):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: с явным флагом доставка идёт (гейт, а не стена)."""
    runner = _mktree(tmp_path, "runner", _full("A"))
    other = _mktree(tmp_path, "other", _full("B"))
    files = [_write_file(other, f"docs/n{i}.md") for i in range(3)]
    calls, code = _run_cli(ptg, monkeypatch,
                           ["--files", *files, "--message", "m",
                            "--allow-toolchain-mismatch"], runner)
    assert code == 0 and len(calls["batch"]) == 1


def test_cli_env_escape_hatch_matches_the_flag(ptg, tmp_path, monkeypatch):
    runner = _mktree(tmp_path, "runner", _full("A"))
    other = _mktree(tmp_path, "other", _full("B"))
    files = [_write_file(other, f"docs/n{i}.md") for i in range(2)]
    monkeypatch.setenv("SPA_PUSH_ALLOW_TOOLCHAIN_MISMATCH", "1")
    monkeypatch.setattr(ptg, "batch_push",
                        lambda *a, **k: {"ok": True, "count": 2, "commit": "c" * 40,
                                         "skipped": 0, "files": [], "skipped_files": []})
    monkeypatch.setattr(ptg, "get_pat", lambda: "pat")
    monkeypatch.setattr(ptg, "__file__", str(runner / "push_to_github.py"))
    monkeypatch.setattr(sys, "argv", ["push_to_github.py", "--files", *files,
                                      "--message", "m"])
    with pytest.raises(SystemExit) as exc:
        ptg.main()
    assert exc.value.code == 0


def test_cli_same_tree_still_delivers_atomically(ptg, tmp_path, monkeypatch):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: нормальный цикл (пушер из своего дерева) не задет —
    набор по-прежнему уезжает ОДНИМ коммитом."""
    top = _mktree(tmp_path, "one", _full("A"))
    files = [_write_file(top, f"docs/n{i}.md") for i in range(3)]
    calls, code = _run_cli(ptg, monkeypatch, ["--files", *files, "--message", "m"], top)
    assert code == 0
    assert len(calls["batch"]) == 1 and calls["push_file"] == []


def test_batch_cli_refuses_the_same_way(batch, tmp_path, monkeypatch):
    """Второй вход доставки — тот же отказ (близнец = класс дефектов #37/#40)."""
    runner = _mktree(tmp_path, "runner", _full("A"))
    other = _mktree(tmp_path, "other", _full("B"))
    files = [_write_file(other, f"docs/n{i}.md") for i in range(2)]
    calls, code = _run_cli(batch, monkeypatch, ["--files", *files, "--message", "m"],
                           runner, module_rel="push_to_github_batch.py")
    assert code == 5 and calls["batch"] == []


def test_both_clis_share_one_implementation(batch):
    """Реализация ОДНА: чинить сверку в одном пушере и забыть в другом нельзя.

    Сравнение — с ``batch._root_push`` (модулем, который batch грузит сам), а не
    с отдельно загруженной копией: две загрузки одного файла дают РАЗНЫЕ объекты
    функций, и такое сравнение краснело бы всегда, ничего не измеряя (эта
    ошибка была допущена здесь же и исправлена по образцу соседней сюиты
    `test_push_batch_atomic.py`).
    """
    for name in ("enforce_delivery_toolchain", "toolchain_verdict",
                 "ToolchainMismatch", "TOOLCHAIN_FILES"):
        assert getattr(batch, name) is getattr(batch._root_push, name), (
            f"{name} в push_to_github_batch.py — СВОЯ копия; починка в одном "
            f"пушере не доедет до другого (так цикл #37 оставил CI красным)")
    assert Path(batch.enforce_delivery_toolchain.__code__.co_filename).name == \
        "push_to_github.py"


def test_batch_cli_defines_no_toolchain_logic_of_its_own(batch):
    src = (ROOT / "push_to_github_batch.py").read_text(encoding="utf-8")
    for name in ("enforce_delivery_toolchain", "toolchain_verdict", "_tree_top"):
        assert f"def {name}" not in src, (
            f"push_to_github_batch.py снова определяет {name} — вернулся близнец")
