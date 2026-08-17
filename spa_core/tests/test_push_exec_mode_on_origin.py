"""
spa_core/tests/test_push_exec_mode_on_origin.py

Сторож на одну вещь: **режим файла можно починить НА ORIGIN, и только явно.**

АВАРИЯ, КОТОРУЮ ЗДЕСЬ ВОСПРОИЗВОДИМ (`.claude/rules/deployment.md` п.3):
режим `100644` у скрипта, который запускает launchd, = агент мёртв (exit 126/78,
инвариант #12), и это НЕ ВИДНО ни по одному пульсу. Правило требует чинить такой
режим на origin, «а не выставлять бит руками после каждого деплоя».

ЧЕМ ЭТО БЫЛО НЕЧЕМ ЧИНИТЬ (карточка `agent-task-prava-na-origin-nechem-pochinit-pusher-p`,
цикл #156): `push_to_github.py::tree_entry_mode` для уже существующего на remote пути
возвращал ЕГО СОБСТВЕННЫЙ режим — намеренно, чтобы пуш никогда молча не снял x-бит с
bash-обёртки. Обратная сторона той же логики: пуш не мог x-бит и ДОБАВИТЬ. `chmod +x` в
worktree ничего не менял — режим брался с remote, а не с диска. Сторож честно отвечал на
СВОЙ вопрос («не снять случайно») и читался как ответ на нужный («режим — часть доставки»).

ВТОРАЯ ПОЛОВИНА той же аварии, найденная здесь замером: у `scripts/agent_morning_digest.sh`
расходятся ТОЛЬКО права, содержимое байт в байт совпадает с origin. Такой файл
`split_unchanged` относит к `unchanged` (по blob-sha он и правда не изменился), и пуш
заканчивался бы «всё содержимое уже на remote — коммит не создаётся» — то есть явное
указание поднять бит дало бы `OK` и НОЛЬ эффекта. Это закрыто `promote_mode_only`.

ГРАНИЦЫ, которые здесь же и пиннятся (иначе починка одного открыла бы другое):
  * без `--exec` поведение прежнее ДО БАЙТА — режим remote сохраняется, x-бит не пропадает;
  * снять x-бит флагом НЕЛЬЗЯ ни при каком значении — только поднять;
  * `--exec` на файл вне набора доставки / неоднозначный → ОТКАЗ (fail-CLOSED), ноль
    запросов и ноль blob'ов;
  * усечённое дерево (режим на remote НЕ ИЗМЕРЕН) → отказ и с `--exec` тоже.

Сеть НЕ ТРОГАЕТСЯ: `_api` подменяется тем же детерминированным фейком GitHub, что и в
`test_push_batch_atomic.py`. Стенные часы не читаются — времени в этом поведении нет.

Запуск: python3 -m pytest spa_core/tests/test_push_exec_mode_on_origin.py -v
"""
from __future__ import annotations

import importlib.util
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Фейковый remote и хелперы живут в тесте batch-пуша — второй копии не заводим
# (копия фикстуры расходится так же, как копия кода).
_batch_spec = importlib.util.spec_from_file_location(
    "_exec_mode_batch_tests", Path(__file__).with_name("test_push_batch_atomic.py"))
_batch_tests = importlib.util.module_from_spec(_batch_spec)
_batch_spec.loader.exec_module(_batch_tests)
FakeGitHub = _batch_tests.FakeGitHub
_write = _batch_tests._write

WRAPPER = "scripts/agent_morning_digest.sh"
WRAPPER_BODY = "#!/bin/bash\nexec python3 -m scripts.morning_work_digest\n"


@pytest.fixture()
def ptg():
    spec = importlib.util.spec_from_file_location(
        "_test_exec_mode_ptg", ROOT / "push_to_github.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_test_exec_mode_ptg"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    return r


def _wire(ptg, repo, monkeypatch, tree, remote_sha_of):
    """Пушер против фейкового remote с заданным деревом `path → (mode, sha)`."""
    gh = FakeGitHub(tree=tree)
    monkeypatch.setattr(ptg, "PROJECT_ROOT", repo)
    monkeypatch.setattr(ptg, "_api", gh.api)
    monkeypatch.setattr(ptg, "get_file_sha",
                        lambda pat, r, path, br="main": remote_sha_of(path))
    return gh


def _modes(gh):
    assert len(gh.trees) == 1, f"ожидалось одно дерево, создано {len(gh.trees)}"
    return {e["path"]: e["mode"] for e in gh.trees[0]["tree"]}


# ═════════════════════════════════════════════════════════════════════════════
# 1. ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: авария «на origin обёртка лежит 644»
# ═════════════════════════════════════════════════════════════════════════════
def test_defect_without_the_flag_mode_stays_644(ptg, repo, monkeypatch):
    """Дословно аварийное состояние: на origin `644`, локально `755`, пушим содержимое.

    Без явного указания режим ОСТАЁТСЯ `644` — это не «плохо работает», а объявленная
    граница инструмента (не снимать x-бит молча). Тест фиксирует её, чтобы следующий
    читатель не искал починку там, где её нет: `chmod +x` в worktree на пуш не влияет.
    """
    gh = _wire(ptg, repo, monkeypatch, {WRAPPER: ("100644", "old")},
               lambda path: "old")
    f = _write(repo, WRAPPER, WRAPPER_BODY + "# правка\n", executable=True)

    ptg.batch_push("pat", [str(f)], "msg", "o/r", "main")

    assert _modes(gh)[WRAPPER] == "100644", (
        "без --exec режим на remote меняться не должен — иначе исчезает защита "
        "«не снять x-бит молча»")


def test_exec_flag_raises_the_bit_on_origin(ptg, repo, monkeypatch):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ ФИЧИ: с `--exec` та же обёртка уезжает как `100755`.

    Сломай/выкинь подъём режима — этот тест краснеет, и правило деплоя п.3 снова
    станет невыполнимым.
    """
    gh = _wire(ptg, repo, monkeypatch, {WRAPPER: ("100644", "old")},
               lambda path: "old")
    f = _write(repo, WRAPPER, WRAPPER_BODY + "# правка\n", executable=True)

    res = ptg.batch_push("pat", [str(f)], "msg", "o/r", "main",
                         exec_files=[WRAPPER])

    assert _modes(gh)[WRAPPER] == "100755", (
        "явный --exec не поднял x-бит: режим на origin починить по-прежнему нечем "
        "(агент, запускаемый напрямую, останется мёртвым с exit 126)")
    assert res["exec_paths"] == [WRAPPER], "отчёт пуша обязан называть поднятые режимы"
    assert len(gh.commits) == 1 and len(gh.ref_updates) == 1


def test_mode_only_change_still_travels(ptg, repo, monkeypatch):
    """Содержимое совпадает с origin, расходятся ТОЛЬКО права — пуш обязан состояться.

    Ровно случай `scripts/agent_morning_digest.sh` (замер цикла #156: «Разошлись именно
    права, содержимое совпадает»). Без `promote_mode_only` файл отсеивался как
    `unchanged`, и явное указание давало `OK` при нулевом эффекте.
    """
    body = WRAPPER_BODY
    f = _write(repo, WRAPPER, body, executable=True)
    same_sha = ptg.git_blob_sha(Path(f).read_bytes())
    gh = _wire(ptg, repo, monkeypatch, {WRAPPER: ("100644", same_sha)},
               lambda path: same_sha)

    res = ptg.batch_push("pat", [str(f)], "msg", "o/r", "main",
                         exec_files=[WRAPPER])

    assert res["count"] == 1 and res["skipped"] == 0, (
        "файл, у которого расходится ТОЛЬКО режим, был отсеян как unchanged — "
        "починка прав на origin молча не состоялась")
    assert _modes(gh)[WRAPPER] == "100755"
    assert len(gh.commits) == 1, "изменение режима — такой же коммит, как изменение байтов"


def test_mode_only_control_without_flag_creates_no_commit(ptg, repo, monkeypatch):
    """Контроль к предыдущему: без `--exec` совпадающее содержимое коммита НЕ создаёт.

    Иначе «пуш ради режима» превратился бы в пустые коммиты на каждом прогоне
    (и лишние сборки CF Pages).
    """
    f = _write(repo, WRAPPER, WRAPPER_BODY, executable=True)
    same_sha = ptg.git_blob_sha(Path(f).read_bytes())
    gh = _wire(ptg, repo, monkeypatch, {WRAPPER: ("100644", same_sha)},
               lambda path: same_sha)

    res = ptg.batch_push("pat", [str(f)], "msg", "o/r", "main")

    assert res["count"] == 0 and gh.commits == []


def test_exec_on_already_executable_file_creates_no_commit(ptg, repo, monkeypatch):
    """`--exec` на файл, который на origin УЖЕ `100755`, — не повод для коммита."""
    f = _write(repo, WRAPPER, WRAPPER_BODY, executable=True)
    same_sha = ptg.git_blob_sha(Path(f).read_bytes())
    gh = _wire(ptg, repo, monkeypatch, {WRAPPER: ("100755", same_sha)},
               lambda path: same_sha)

    res = ptg.batch_push("pat", [str(f)], "msg", "o/r", "main",
                         exec_files=[WRAPPER])

    assert res["count"] == 0 and gh.commits == [], (
        "режим уже верный — пуш обязан быть no-op, а не пустым коммитом")


# ═════════════════════════════════════════════════════════════════════════════
# 2. ГРАНИЦА В ОБРАТНУЮ СТОРОНУ: x-бит не снимается ничем
# ═════════════════════════════════════════════════════════════════════════════
def test_exec_bit_is_never_removed_by_the_flag(ptg, repo, monkeypatch):
    """`--exec` умеет только 644 → 755. Соседний файл в том же пуше x-бит не теряет."""
    gh = _wire(ptg, repo, monkeypatch,
               {WRAPPER: ("100644", "old"),
                "scripts/auto_push.sh": ("100755", "old")},
               lambda path: "old")
    a = _write(repo, WRAPPER, WRAPPER_BODY + "# a\n", executable=False)
    b = _write(repo, "scripts/auto_push.sh", "#!/bin/bash\necho b\n", executable=False)

    ptg.batch_push("pat", [str(a), str(b)], "msg", "o/r", "main",
                   exec_files=[WRAPPER])

    modes = _modes(gh)
    assert modes[WRAPPER] == "100755"
    assert modes["scripts/auto_push.sh"] == "100755", (
        "x-бит соседнего файла снят молча — после такого пуша bash-обёртка launchd "
        "падает exit-78 (инвариант #12)")


def test_no_flag_lowers_a_mode(ptg):
    """Флага «снять x-бит» в CLI нет — и не должно появиться незамеченным.

    Понижение режима — отдельное осознанное решение (мёртвый агент виден только по
    мёртвому агенту), а не опция инструмента доставки.
    """
    src = (ROOT / "push_to_github.py").read_text(encoding="utf-8")
    for forbidden in ('"--no-exec"', "'--no-exec'", '"--unexec"', '"--mode"'):
        assert forbidden not in src, (
            f"в пушере появился {forbidden}: снятие x-бита через флаг доставки "
            f"запрещено (см. шапку этого файла)")


def test_exec_paths_never_yield_blob_mode(ptg):
    """`tree_entry_mode` для названного пути возвращает ТОЛЬКО 100755."""
    for existing in ({}, {WRAPPER: "100644"}, {WRAPPER: "100755"}):
        mode = ptg.tree_entry_mode(WRAPPER, Path("/nonexistent/x.sh"), existing,
                                   False, frozenset({WRAPPER}))
        assert mode == ptg.EXEC_MODE, f"режим {mode} при exec_paths={{{WRAPPER}}}"


# ═════════════════════════════════════════════════════════════════════════════
# 3. FAIL-CLOSED: не ясно, какому файлу поднимать бит → отказ, а не догадка
# ═════════════════════════════════════════════════════════════════════════════
def test_exec_path_outside_the_push_set_refuses_before_any_call(ptg, repo, monkeypatch):
    gh = _wire(ptg, repo, monkeypatch, {}, lambda path: None)
    f = _write(repo, "docs/x.md", "текст\n")

    with pytest.raises(ptg.ExecModeRefused) as e:
        ptg.batch_push("pat", [str(f)], "msg", "o/r", "main",
                       exec_files=["scripts/other.sh"])

    assert "scripts/other.sh" in str(e.value)
    assert gh.calls == [], (
        "отказ обязан быть ДО сети: ошибка в --exec не должна стоить ни запроса, "
        "ни blob'а-сироты")


def test_ambiguous_exec_path_refuses(ptg, repo, monkeypatch):
    """Один и тот же basename в двух каталогах — какому поднимать бит, НЕ ИЗМЕРЕНО."""
    _wire(ptg, repo, monkeypatch, {}, lambda path: None)
    a = _write(repo, "scripts/run.sh", "#!/bin/bash\na\n")
    b = _write(repo, "attic/agents/run.sh", "#!/bin/bash\nb\n")

    with pytest.raises(ptg.ExecModeRefused) as e:
        ptg.batch_push("pat", [str(a), str(b)], "msg", "o/r", "main",
                       exec_files=["run.sh"])

    assert "scripts/run.sh" in str(e.value) and "attic/agents/run.sh" in str(e.value), (
        "отказ обязан называть ВСЕ подходящие пути — иначе решать нечем")


def test_absolute_and_repo_relative_exec_paths_both_hit(ptg, repo, monkeypatch):
    """Положительный контроль к двум отказам выше: однозначное указание РАБОТАЕТ."""
    for arg_kind in ("repo-relative", "absolute"):
        gh = _wire(ptg, repo, monkeypatch, {WRAPPER: ("100644", "old")},
                   lambda path: "old")
        f = _write(repo, WRAPPER, WRAPPER_BODY + f"# {arg_kind}\n")
        arg = WRAPPER if arg_kind == "repo-relative" else str(f)

        ptg.batch_push("pat", [str(f)], "msg", "o/r", "main", exec_files=[arg])

        assert _modes(gh)[WRAPPER] == "100755", f"не сработало указание вида {arg_kind}"


def test_truncated_tree_refuses_even_with_exec(ptg, repo, monkeypatch):
    """Режим на remote НЕ ИЗМЕРЕН (дерево усечено) → отказ, а не «наверное, 644»."""
    gh = FakeGitHub(tree={"other.py": ("100644", "s")}, truncated=True)
    monkeypatch.setattr(ptg, "PROJECT_ROOT", repo)
    monkeypatch.setattr(ptg, "_api", gh.api)
    monkeypatch.setattr(ptg, "get_file_sha", lambda *a, **k: None)
    f = _write(repo, WRAPPER, WRAPPER_BODY, executable=True)

    with pytest.raises(ptg.TreeModeError):
        ptg.batch_push("pat", [str(f)], "msg", "o/r", "main", exec_files=[WRAPPER])

    assert gh.commits == [] and gh.ref_updates == []


# ═════════════════════════════════════════════════════════════════════════════
# 4. CLI: просьба о режиме не имеет права потеряться на пути Contents API
# ═════════════════════════════════════════════════════════════════════════════
def _run_main(ptg, monkeypatch, argv):
    calls = {"batch": [], "push_file": []}

    def fake_batch(pat, files, message, repo, branch, dry_run=False, **kw):
        calls["batch"].append({"files": list(files), "exec": kw.get("exec_files")})
        return {"ok": True, "count": len(files), "commit": "c" * 40, "skipped": 0,
                "files": list(files), "skipped_files": [], "exec_paths": []}

    def fake_push_file(pat, f, message, repo, dry_run=False, branch="main", **kw):
        calls["push_file"].append(f)
        return {"ok": True, "path": str(f), "sha": "abcdef12"}

    monkeypatch.setattr(ptg, "batch_push", fake_batch)
    monkeypatch.setattr(ptg, "push_file", fake_push_file)
    monkeypatch.setattr(ptg, "get_pat", lambda: "pat")
    monkeypatch.setattr(ptg, "enforce_delivery_toolchain", lambda *a, **k: {})
    monkeypatch.setattr(sys, "argv", ["push_to_github.py", *argv])
    with pytest.raises(SystemExit) as exc:
        ptg.main()
    return calls, exc.value.code


def test_cli_single_file_with_exec_uses_the_tree_api(ptg, repo, monkeypatch):
    """ОДИН файл + `--exec` → Git Data API, не Contents API.

    Contents API (одиночный PUT) режима записи дерева не принимает вовсе — просьбу о
    x-бите там некуда положить, и она пропала бы молча под честным `OK`. Ровно тот
    класс, из которого выросла задача.
    """
    f = str(_write(repo, WRAPPER, WRAPPER_BODY, executable=True))
    calls, code = _run_main(ptg, monkeypatch,
                            ["--files", f, "--message", "m", "--exec", WRAPPER])

    assert code == 0
    assert calls["push_file"] == [], (
        "просьба о режиме уехала по Contents API — там она пропадает молча")
    assert len(calls["batch"]) == 1
    assert calls["batch"][0]["exec"] == [WRAPPER], "--exec не доехал до batch_push"


def test_cli_single_file_without_exec_keeps_contents_api(ptg, repo, monkeypatch):
    """Контроль: без `--exec` маршрут одиночного файла не изменился."""
    f = str(_write(repo, "one.py", "1\n"))
    calls, code = _run_main(ptg, monkeypatch, ["--files", f, "--message", "m"])
    assert code == 0 and calls["batch"] == [] and calls["push_file"] == [f]


def test_cli_refusal_has_its_own_exit_code(ptg, repo, monkeypatch):
    """Отказ по `--exec` отличим по коду возврата (8) от прочих провалов пуша."""
    f = str(_write(repo, "one.py", "1\n"))

    def boom(*a, **k):
        raise ptg.ExecModeRefused("нет такого файла в наборе")

    monkeypatch.setattr(ptg, "batch_push", boom)
    monkeypatch.setattr(ptg, "push_file", lambda *a, **k: {"ok": True, "path": f})
    monkeypatch.setattr(ptg, "get_pat", lambda: "pat")
    monkeypatch.setattr(ptg, "enforce_delivery_toolchain", lambda *a, **k: {})
    monkeypatch.setattr(sys, "argv", ["push_to_github.py", "--files", f,
                                      "--message", "m", "--exec", "nope.sh"])
    with pytest.raises(SystemExit) as exc:
        ptg.main()
    assert exc.value.code == 8


def test_both_cli_expose_the_flag(ptg):
    """Оба входа доставки умеют `--exec` — иначе починка есть в одном пушере и нет в другом."""
    for rel in ("push_to_github.py", "push_to_github_batch.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert '"--exec"' in src, f"{rel} не принимает --exec"
        assert "exec_files=args.exec_paths" in src, f"{rel} не передаёт --exec в batch_push"


# ═════════════════════════════════════════════════════════════════════════════
# 5. СТОРОЖ ЖИВОГО РЕПО: то, что launchd запускает НАПРЯМУЮ, обязано быть 100755
# ═════════════════════════════════════════════════════════════════════════════
INTERPRETERS = {"bash", "sh", "zsh", "python", "python3", "env", "caffeinate", "nice"}


def index_modes(root: Path) -> dict:
    """`путь → режим` по git-индексу (то, что уедет/уехало на origin)."""
    out = subprocess.run(["git", "ls-files", "-s"], cwd=root,
                         capture_output=True, text=True)
    if out.returncode != 0:
        pytest.skip(f"git ls-files недоступен: {out.stderr.strip()[:120]}")
    modes = {}
    for line in out.stdout.splitlines():
        meta, _, path = line.partition("\t")
        if path:
            modes[path] = meta.split()[0]
    return modes


def direct_entrypoints(plists: list) -> list:
    """Пути, которые launchd исполняет САМ (без интерпретатора) → x-бит обязателен.

    Через `/bin/bash <script>` бит не нужен, поэтому такие обёртки здесь не судятся:
    сторож обязан краснеть на аварию, а не на живое рабочее состояние.
    """
    found = []
    for p in plists:
        try:
            data = plistlib.loads(Path(p).read_bytes())
        except Exception:
            continue
        args = data.get("ProgramArguments") or []
        for candidate in ([data["Program"]] if data.get("Program") else []) + args[:1]:
            name = Path(str(candidate)).name
            if name in INTERPRETERS or not str(candidate).strip():
                continue
            found.append((str(p), str(candidate)))
    return found


def _to_repo_path(candidate: str, modes: dict) -> str | None:
    c = str(candidate).replace("\\", "/")
    for path in modes:
        if c == path or c.endswith("/" + path):
            return path
    return None


def test_direct_launchd_entrypoints_are_executable_in_the_index() -> None:
    """Живой замер репо: ни один прямой entrypoint launchd не лежит как `644`."""
    modes = index_modes(ROOT)
    offenders = []
    for plist, candidate in direct_entrypoints(sorted((ROOT / "launchd").glob("*.plist"))):
        rel = _to_repo_path(candidate, modes)
        if rel and modes[rel] != "100755":
            offenders.append(f"{Path(plist).name} → {rel} = {modes[rel]}")
    assert not offenders, (
        "launchd исполняет эти файлы САМ, а на origin они не исполняемые — агент "
        "падает exit 126, и это не видно ни по одному пульсу "
        "(.claude/rules/deployment.md п.3). Починка: "
        "`push_to_github.py --files <файл> --exec <файл> --message ...`\n  "
        + "\n  ".join(offenders))


def test_watchdog_itself_sees_the_accident(tmp_path) -> None:
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ сторожа выше: подсунуть ему аварию — он её называет.

    Без этого теста проверка выше могла бы быть зелёной просто потому, что ничего не
    находит по построению (проверка, никогда не видевшая настоящей поломки, — украшение).
    """
    plist = tmp_path / "com.spa.fake.plist"
    plist.write_bytes(plistlib.dumps({
        "Label": "com.spa.fake",
        "ProgramArguments": ["/Users/x/SPA_Claude/scripts/agent_fake.sh"],
    }))
    modes = {"scripts/agent_fake.sh": "100644"}

    found = direct_entrypoints([plist])
    assert found, "прямой entrypoint не распознан — сторож слеп"
    rel = _to_repo_path(found[0][1], modes)
    assert rel == "scripts/agent_fake.sh"
    assert modes[rel] != "100755", "авария 644 у прямого entrypoint должна быть находкой"


def test_watchdog_ignores_wrappers_launched_through_bash(tmp_path) -> None:
    """Контроль в обратную сторону: `/bin/bash <script>` x-бита не требует.

    Иначе сторож краснел бы на верное состояние — и его начали бы обходить
    (`.claude/rules/deployment.md`: гасить мешающую проверку запрещено, но и красить
    её на живом рабочем состоянии нельзя).
    """
    plist = tmp_path / "com.spa.wrapped.plist"
    plist.write_bytes(plistlib.dumps({
        "Label": "com.spa.wrapped",
        "ProgramArguments": ["/bin/bash", "/Users/x/SPA_Claude/scripts/agent_fake.sh"],
    }))
    assert direct_entrypoints([plist]) == []
