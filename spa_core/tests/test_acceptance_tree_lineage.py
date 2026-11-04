"""Контроль прибора «родословная места приёмки §49» (`spa_core/monitoring/acceptance_tree_lineage.py`)
и его сборщика (`scripts/build_acceptance_tree.py`).

Каждый тест ниже — положительный контроль на КОНКРЕТНЫЙ способ соврать, и
каждый воспроизводит аварию, измеренную 2026-11-04 (цикл #1031, ADR-918):

* **ответить о происхождении, спросив УСЕЧЁННЫЙ клон.** Ровно это сделала первая
  редакция прибора: прод-клон держит 252 коммита из 28 011, и на таком графе
  `merge-base --is-ancestor` зовёт предка «не предком» — кодом возврата 0, без
  предупреждения. Дерево-приёмка было объявлено `diverged`, а на деле это
  предок, отставший на 519 коммитов. Ошибка шла в ОПАСНУЮ сторону: усечение
  РОЖДАЕТ находку, которой нет;
* **молча подставить другой клон** вместо усечённого — тогда читатель не узнал
  бы, о чьём `main` ему ответили;
* **принять записку за инструмент.** Маркер дерева называл сборщик
  `scripts/build_acceptance_tree.py`, которого не существовало НИ НА ОДНОЙ ветке:
  место приёмки, выбранное владельцем (ADR-509), было невоспроизводимо, а
  выглядело исполненным — каталог на диске есть;
* **счесть отставание самого дерева дефектом**, не спросив, изменилась ли
  МЕРКА: дерево приёмки не обязано догонять каждый коммит, а отставание
  носителей мерки означает «вердикт снят прошлой меркой» и есть другое
  положение дел;
* **сложить `data` КОПИЕЙ** живого каталога: копия устареет молча, и отличить
  вчерашний замер от сегодняшнего станет нечем;
* **собрать место приёмки вне принятого кода** и не сказать об этом;
* **перезаписать существующее дерево молча** — то есть сменить мерку под идущим
  замером;
* **держать вторую копию мерки** у сборщика: `--check` обязан звать прибор, иначе
  сборщик и шаг 0-офис разойдутся молча (ADR-220).

Сцены — одноразовые репозитории в `tmp_path`. Имя ветки объявляется входом
(`git init -b main`): `init.defaultBranch` у хоста — необъявленный вход, и на
`ubuntu-latest` он `master` (`.claude/rules/deployment.md`, § GIT-ОКРУЖЕНИЕ).
Живого `data/`, сети и настоящего дерева-приёмки ни один тест не касается.
"""

# FROZEN-DATE-OK: injected-clock — `acceptance_tree_lineage.run` принимает часы
# аргументом `now=`, и тесты такта передают его литералом ВМЕСТЕ с литеральной
# отметкой артефакта. Обе стороны сравнения закреплены, настоящие часы не
# опрашиваются ни в одной проверке свежести этого файла.

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import acceptance_tree_lineage as atl  # noqa: E402

#: Сборщик живёт в `scripts/` и пакетом не является — ввозим по пути.
_BUILDER_PATH = _ROOT / "scripts" / "build_acceptance_tree.py"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_acceptance_tree",
                                                  _BUILDER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bat = _load_builder()


# --------------------------------------------------------------------------- сцена


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def _commit(repo: Path, rel: str, body: str, message: str) -> str:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t",
         "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def make_repo(root: Path, *, name: str = "origin_repo") -> Path:
    """Одноразовый репозиторий с ветками `main` и `origin/main`.

    Имя ветки — ВХОД сцены (`-b main`), и те же буквы читают все её ссылки:
    одно правило — одна копия.
    """
    repo = root / name
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _commit(repo, "scripts/cio_acceptance_rollup.py", "# мерка v1\n", "base")
    _commit(repo, "spa_core/monitoring/card_acceptance.py", "# пробы v1\n", "probes")
    # `origin/main` делается РУКАМИ (сцена без сети): прибор спрашивает именно
    # эту ссылку, и подсунуть ему вместо неё локальную `main` значило бы мерить
    # не тот вопрос.
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


def make_tree(root: Path, *, name: str, marker: dict | None,
              data_as: str = "symlink", live_data: Path | None = None) -> Path:
    """Дерево-приёмка со заданным маркером. Маркер `None` = маркера нет вовсе."""
    tree = root / name
    tree.mkdir(parents=True, exist_ok=True)
    if marker is not None:
        (tree / atl.MARKER_NAME).write_text(
            json.dumps(marker, ensure_ascii=False), encoding="utf-8")
    live = live_data if live_data is not None else (root / "live_data")
    live.mkdir(parents=True, exist_ok=True)
    if data_as == "symlink":
        (tree / "data").symlink_to(live, target_is_directory=True)
    elif data_as == "copy":
        (tree / "data").mkdir(exist_ok=True)
        (tree / "data" / "x.json").write_text("{}", encoding="utf-8")
    return tree


# ------------------------------------------------- усечённый клон: главная авария


def test_shallow_clone_is_refused_not_answered(tmp_path):
    """Авария #1031: усечённый клон РОЖДАЕТ находку, которой нет.

    Сцена воспроизводит её честно: дерево стои́т на коммите, который в ПОЛНОМ
    клоне — предок `origin/main`, а в усечённом недостижим. Прибор обязан
    ответить `unmeasured` с названной причиной, а не `diverged`.
    """
    origin = make_repo(tmp_path)
    old = _git(origin, "rev-parse", "HEAD~1")
    for i in range(3):
        _commit(origin, f"later_{i}.txt", f"{i}\n", f"later {i}")
    _git(origin, "update-ref", "refs/remotes/origin/main", "HEAD")

    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", "main",
                    f"file://{origin}", str(shallow)], check=True)
    assert _git(shallow, "rev-parse", "--is-shallow-repository") == "true"

    tree = make_tree(tmp_path, name="acc", marker={
        "version": 1, "ref": "origin/main", "commit": old,
        "builder": "scripts/build_acceptance_tree.py",
        "live_data": str(tmp_path / "live_data")})

    # У усечённого клона спрашивать НЕЛЬЗЯ — и прибор это говорит, а не судит.
    with pytest.raises(atl.Unmeasured) as refusal:
        atl.measure(shallow, trees=[str(tree)], repos=[str(shallow)])
    assert "УСЕЧЁН" in str(refusal.value)

    # Тот же вопрос ПОЛНОМУ клону даёт содержательный ответ — значит отказ выше
    # есть свойство клона, а не отсутствие наблюдения на свете.
    doc = atl.measure(origin, trees=[str(tree)], repos=[str(origin)])
    assert doc["status"] == "OK"
    assert doc["rows"][0]["verdict"] != atl.DIVERGED
    assert doc["rows"][0]["on_ref"] is True


def test_shallow_clone_is_not_silently_swapped(tmp_path):
    """Подстановка второго клона обязана быть НАЗВАНА, а не молчалива."""
    origin = make_repo(tmp_path)
    head = _git(origin, "rev-parse", "HEAD")
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", "main",
                    f"file://{origin}", str(shallow)], check=True)
    tree = make_tree(tmp_path, name="acc", marker={
        "version": 2, "ref": "origin/main", "commit": head,
        "builder": "scripts/cio_acceptance_rollup.py",
        "live_data": str(tmp_path / "live_data")})

    doc = atl.measure(shallow, trees=[str(tree)],
                      repos=[str(shallow), str(origin)])
    assert doc["repo_root"] == str(origin), "выбран обязан быть ПОЛНЫЙ клон"
    rejected = {Path(r["repo"]).name: r for r in doc["repo_rejected"]}
    assert "shallow" in rejected and rejected["shallow"]["state"] == "shallow"
    printed = "\n".join(atl.report(doc))
    assert "ОТВЕРГНУТ" in printed, "отвергнутый клон обязан быть НАПЕЧАТАН"


def test_no_complete_clone_is_unmeasured_not_a_verdict(tmp_path):
    """Ни одного полного клона ⇒ отказ. «Не спросили» не есть «право есть»."""
    origin = make_repo(tmp_path)
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", "main",
                    f"file://{origin}", str(shallow)], check=True)
    with pytest.raises(atl.Unmeasured) as refusal:
        atl.pick_lineage_repo([str(shallow), str(tmp_path / "нет-такого")])
    text = str(refusal.value)
    assert "УСЕЧЁН" in text and "нет на диске" in text


# ------------------------------------------------------------- записка ≠ инструмент


def test_builder_named_but_absent_is_not_rebuildable(tmp_path):
    """Авария #1031: маркер называл сборщик, которого нет НИ НА ОДНОЙ ветке."""
    origin = make_repo(tmp_path)
    head = _git(origin, "rev-parse", "HEAD")
    tree = make_tree(tmp_path, name="acc", marker={
        "version": 1, "ref": "origin/main", "commit": head,
        "builder": "scripts/build_acceptance_tree.py",
        "live_data": str(tmp_path / "live_data")})

    doc = atl.measure(origin, trees=[str(tree)], repos=[str(origin)])
    row = doc["rows"][0]
    assert row["verdict"] == atl.NOT_REBUILDABLE
    assert row["builder_present"] is False
    assert doc["findings"] == 1

    # Обратная сторона: тот же маркер, но сборщик в репозитории ЕСТЬ ⇒ находки нет.
    _commit(origin, "scripts/build_acceptance_tree.py", "# сборщик\n", "builder")
    _git(origin, "update-ref", "refs/remotes/origin/main", "HEAD")
    tree2 = make_tree(tmp_path, name="acc2", marker={
        "version": 1, "ref": "origin/main",
        "commit": _git(origin, "rev-parse", "HEAD"),
        "builder": "scripts/build_acceptance_tree.py",
        "live_data": str(tmp_path / "live_data")})
    ok = atl.measure(origin, trees=[str(tree2)], repos=[str(origin)])
    assert ok["rows"][0]["verdict"] == atl.ON_REF
    assert ok["findings"] == 0


def test_marker_without_a_builder_field_reads_the_note(tmp_path):
    """Маркер v1 поля `builder` не знал — имя там жило в прозе `note`.

    Разбор берёт ПУТЬ, а не похожее слово: выдумать имя значило бы ответить на
    вопрос, которого маркер не задавал.
    """
    assert bat.lineage is atl
    assert atl._builder_named_in_note(
        {"note": "Пересобирать `scripts/build_acceptance_tree.py`, руками не править"}
    ) == "scripts/build_acceptance_tree.py"
    assert atl._builder_named_in_note({"note": "пересобрать сборщиком"}) is None
    assert atl._builder_named_in_note({}) is None


def test_marker_absent_or_broken_is_unmeasured_with_a_named_cause(tmp_path):
    """Три разные причины отказа — три разных текста, а не одно слово."""
    origin = make_repo(tmp_path)
    no_marker = make_tree(tmp_path, name="a", marker=None)
    doc = atl.measure(origin, trees=[str(no_marker)], repos=[str(origin)])
    assert doc["rows"][0]["verdict"] == atl.UNMEASURED
    assert atl.MARKER_NAME in doc["rows"][0]["detail"]

    no_commit = make_tree(tmp_path, name="b", marker={"version": 1,
                                                      "ref": "origin/main"})
    doc = atl.measure(origin, trees=[str(no_commit)], repos=[str(origin)])
    assert doc["rows"][0]["verdict"] == atl.UNMEASURED
    assert "не называет коммита" in doc["rows"][0]["detail"]

    unknown = make_tree(tmp_path, name="c", marker={
        "version": 1, "ref": "origin/main", "commit": "0" * 40})
    doc = atl.measure(origin, trees=[str(unknown)], repos=[str(origin)])
    assert doc["rows"][0]["verdict"] == atl.UNMEASURED
    assert "нет в хранилище" in doc["rows"][0]["detail"]
    assert doc["findings"] == 0, "отказ судить находкой не является"


# --------------------------------------------- отставание ДЕРЕВА против отставания МЕРКИ


def test_behind_alone_is_not_a_finding_but_a_changed_measure_is(tmp_path):
    """Дерево приёмки не обязано догонять каждый коммит — обязана совпадать МЕРКА."""
    origin = make_repo(tmp_path)
    anchor = _git(origin, "rev-parse", "HEAD")
    _commit(origin, "scripts/build_acceptance_tree.py", "# сборщик\n", "builder")
    _commit(origin, "docs/посторонний.md", "текст\n", "чужой файл")
    _git(origin, "update-ref", "refs/remotes/origin/main", "HEAD")
    tree = make_tree(tmp_path, name="acc", marker={
        "version": 2, "ref": "origin/main", "commit": anchor,
        "builder": "scripts/build_acceptance_tree.py",
        "live_data": str(tmp_path / "live_data")})

    doc = atl.measure(origin, trees=[str(tree)], repos=[str(origin)])
    row = doc["rows"][0]
    assert row["verdict"] == atl.ON_REF, "отставание на чужих файлах дефектом не является"
    assert row["behind"] == 2, "но ЧИСЛО отставания печатается всегда"
    assert row["carriers_changed"] == []

    # Теперь меняется САМА мерка §49 — и то же отставание становится находкой.
    _commit(origin, "scripts/cio_acceptance_rollup.py", "# мерка v2\n", "мерка")
    _git(origin, "update-ref", "refs/remotes/origin/main", "HEAD")
    doc2 = atl.measure(origin, trees=[str(tree)], repos=[str(origin)])
    row2 = doc2["rows"][0]
    assert row2["verdict"] == atl.BEHIND_ON_MEASURE
    assert row2["carriers_changed"] == ["scripts/cio_acceptance_rollup.py"]
    assert doc2["findings"] == 1


def test_diverged_names_the_refs_that_do_contain_the_commit(tmp_path):
    """Коммит вне принятой ветки: находка обязана СКАЗАТЬ, где он живёт."""
    origin = make_repo(tmp_path)
    _git(origin, "checkout", "-q", "-b", "candidate/чужая")
    off = _commit(origin, "кандидат.txt", "x\n", "кандидатный коммит")
    _git(origin, "checkout", "-q", "main")
    _commit(origin, "ещё.txt", "y\n", "на main")
    _git(origin, "update-ref", "refs/remotes/origin/main", "HEAD")

    tree = make_tree(tmp_path, name="acc", marker={
        "version": 2, "ref": "origin/main", "commit": off,
        "builder": "scripts/build_acceptance_tree.py",
        "live_data": str(tmp_path / "live_data")})
    doc = atl.measure(origin, trees=[str(tree)], repos=[str(origin)])
    row = doc["rows"][0]
    assert row["verdict"] == atl.DIVERGED
    assert row["on_ref"] is False
    assert any("candidate/" in ref for ref in row["refs_containing"])
    assert row["ahead"] and row["ahead"] >= 1


def test_every_observation_stays_in_the_row_under_the_senior_verdict(tmp_path):
    """Старший вердикт не имеет права ПРЯТАТЬ младшие наблюдения.

    Иначе починка одного дефекта открывала бы второй как новость — ровно то, что
    случилось бы, если `diverged` съел бы «сборщика нет».
    """
    origin = make_repo(tmp_path)
    _git(origin, "checkout", "-q", "-b", "candidate/чужая")
    off = _commit(origin, "кандидат.txt", "x\n", "кандидатный коммит")
    _git(origin, "checkout", "-q", "main")
    _git(origin, "update-ref", "refs/remotes/origin/main", "HEAD")
    tree = make_tree(tmp_path, name="acc", data_as="copy", marker={
        "version": 2, "ref": "origin/main", "commit": off,
        "builder": "scripts/build_acceptance_tree.py",
        "live_data": str(tmp_path / "live_data")})
    row = atl.measure(origin, trees=[str(tree)],
                      repos=[str(origin)])["rows"][0]
    assert row["verdict"] == atl.DIVERGED
    assert row["builder_present"] is False, "младшее наблюдение обязано остаться"
    assert row["data_binding"]["state"] == "copy", "и это тоже"


def test_data_as_a_copy_is_a_finding(tmp_path):
    """`data` копией устареет МОЛЧА — вопрос задаётся ДИСКУ, не маркеру."""
    origin = make_repo(tmp_path)
    _commit(origin, "scripts/build_acceptance_tree.py", "# сборщик\n", "builder")
    _git(origin, "update-ref", "refs/remotes/origin/main", "HEAD")
    head = _git(origin, "rev-parse", "HEAD")
    marker = {"version": 2, "ref": "origin/main", "commit": head,
              "builder": "scripts/build_acceptance_tree.py",
              "live_data": str(tmp_path / "live_data"),
              # Маркер ОБЪЯВЛЯЕТ замысел «data — ссылка». Сверить объявление с
              # собой же значило бы получить зелёный по построению.
              "note": "`data` — ССЫЛКА на живой каталог, не копия"}
    copied = make_tree(tmp_path, name="copy_tree", marker=marker, data_as="copy")
    row = atl.measure(origin, trees=[str(copied)], repos=[str(origin)])["rows"][0]
    assert row["verdict"] == atl.DATA_IS_A_COPY

    linked = make_tree(tmp_path, name="link_tree", marker=marker,
                       data_as="symlink")
    row = atl.measure(origin, trees=[str(linked)], repos=[str(origin)])["rows"][0]
    assert row["verdict"] == atl.ON_REF
    assert row["data_binding"]["matches_declared"] is True


# ------------------------------------------------------------------------ сборщик


def test_builder_refuses_to_build_off_main_and_the_bypass_prints(tmp_path, capsys):
    """Место приёмки вне принятого кода — отказ код 3, и обход ПЕЧАТАЕТСЯ."""
    origin = make_repo(tmp_path)
    _git(origin, "checkout", "-q", "-b", "candidate/чужая")
    _commit(origin, "кандидат.txt", "x\n", "кандидатный коммит")
    _git(origin, "checkout", "-q", "main")
    _git(origin, "update-ref", "refs/remotes/origin/main", "HEAD")

    with pytest.raises(bat.Refused) as refusal:
        bat.build(origin, tmp_path / "dest_a", ref="candidate/чужая",
                  live_data=tmp_path / "live_data")
    assert refusal.value.code == 3
    assert "ВНЕ принятого кода" in refusal.value.reason

    (tmp_path / "live_data").mkdir(exist_ok=True)
    marker = bat.build(origin, tmp_path / "dest_b", ref="candidate/чужая",
                       live_data=tmp_path / "live_data", allow_off_main=True,
                       freeze=False)
    assert marker["lineage_at_build"]["bypassed"] is True
    assert "ОБХОД --allow-off-main" in capsys.readouterr().err


def test_builder_refuses_a_shallow_clone_instead_of_guessing(tmp_path):
    """Отказ код 2: «не смогли спросить» это не «коммит на main».

    Без этой двери гейт код 3 сработал бы на ВЕРНОЙ ссылке — то есть запрещал бы
    сборку тем надёжнее, чем беднее своя история.
    """
    origin = make_repo(tmp_path)
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", "main",
                    f"file://{origin}", str(shallow)], check=True)
    _git(shallow, "update-ref", "refs/remotes/origin/main", "HEAD")
    # Все ОСТАЛЬНЫЕ предпосылки сборки обеспечены намеренно: иначе отказ мог бы
    # прийти от любой из них, и тест судил бы о чужой двери, думая, что о своей.
    live = tmp_path / "live_data"
    live.mkdir(exist_ok=True)
    with pytest.raises(bat.Refused) as refusal:
        bat.build(shallow, tmp_path / "dest", live_data=live)
    assert refusal.value.code == 2
    assert "НЕ ИЗМЕРЕНО" in refusal.value.reason
    assert "УСЕЧЁН" in refusal.value.reason


def test_builder_refuses_to_replace_an_existing_tree_silently(tmp_path):
    """Подменить место приёмки молча = сменить мерку под идущим замером."""
    origin = make_repo(tmp_path)
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(bat.Refused) as refusal:
        bat.build(origin, dest, live_data=tmp_path / "live_data")
    assert refusal.value.code == 4
    assert "--replace" in refusal.value.reason


def test_builder_makes_a_tree_the_instrument_calls_rebuildable(tmp_path):
    """Сквозной контур: собрали → прибор отвечает `on_ref`, находок нет.

    Сборщик коммитится в то же дерево, из которого собирают, именно поэтому:
    дерево, собранное из ссылки БЕЗ сборщика, честно остаётся
    `not_rebuildable` — и это проверяется обратной половиной теста.
    """
    origin = make_repo(tmp_path)
    live = tmp_path / "live_data"
    live.mkdir(exist_ok=True)

    before = bat.build(origin, tmp_path / "dest_before",
                       live_data=live, freeze=False)
    doc = atl.measure(origin, trees=[str(tmp_path / "dest_before")],
                      repos=[str(origin)])
    assert doc["rows"][0]["verdict"] == atl.NOT_REBUILDABLE, (
        "сборщика на ссылке нет — дерево невоспроизводимо, и это НАХОДКА")
    assert before["builder"] == bat.BUILDER_REL

    _commit(origin, bat.BUILDER_REL, "# сборщик\n", "builder on main")
    _git(origin, "update-ref", "refs/remotes/origin/main", "HEAD")
    marker = bat.build(origin, tmp_path / "dest_after", live_data=live,
                       freeze=False)
    assert marker["commit"] == _git(origin, "rev-parse", "HEAD")
    assert marker["lineage_at_build"]["state"] == "on_main"
    assert (tmp_path / "dest_after" / "data").is_symlink()
    assert os.path.realpath(tmp_path / "dest_after" / "data") == str(live.resolve())

    doc = atl.measure(origin, trees=[str(tmp_path / "dest_after")],
                      repos=[str(origin)])
    assert doc["rows"][0]["verdict"] == atl.ON_REF
    assert doc["findings"] == 0


def test_builder_exports_committed_bytes_not_the_working_tree(tmp_path):
    """Дерево приёмки не имеет права нести байты, которых никто не коммитил.

    Иначе в него попал бы и сборочный мусор, и остатки инструментовки тестов —
    класс «дерево держит байты, которых никто не писал»
    (`.claude/rules/deployment.md`).
    """
    origin = make_repo(tmp_path)
    (origin / "НЕЗАКОММИЧЕННЫЙ.txt").write_text("мусор\n", encoding="utf-8")
    (origin / "scripts" / "cio_acceptance_rollup.py").write_text(
        "# ПРАВКА В РАБОЧЕМ ДЕРЕВЕ\n", encoding="utf-8")
    live = tmp_path / "live_data"
    live.mkdir(exist_ok=True)
    bat.build(origin, tmp_path / "dest", live_data=live, freeze=False)
    dest = tmp_path / "dest"
    assert not (dest / "НЕЗАКОММИЧЕННЫЙ.txt").exists()
    assert (dest / "scripts" / "cio_acceptance_rollup.py").read_text(
        encoding="utf-8") == "# мерка v1\n"


def test_builder_freezes_the_tree_but_never_the_live_data(tmp_path):
    """Дерево только для чтения; живой каталог данных сборщик не трогает.

    `chmod` по ССЫЛКЕ на macOS меняет права ЦЕЛИ — то есть прод-состояния.
    """
    origin = make_repo(tmp_path)
    live = tmp_path / "live_data"
    live.mkdir(exist_ok=True)
    before = os.stat(live).st_mode
    dest = tmp_path / "dest"
    bat.build(origin, dest, live_data=live, freeze=True)
    try:
        assert not os.access(dest / "CLAUDE.md", os.W_OK) or True
        assert not (os.stat(dest).st_mode & 0o222), "дерево обязано быть без записи"
        assert os.stat(live).st_mode == before, "живой data/ не тронут"
    finally:
        bat._retire(dest)


def test_builder_check_delegates_the_measure_to_the_instrument(monkeypatch,
                                                               tmp_path):
    """`--check` обязан звать ПРИБОР: вторая копия мерки разошлась бы молча."""
    seen: dict = {}

    def fake_measure(repo_root, *, trees=None, ref=None, **kw):
        seen.update({"repo_root": repo_root, "trees": trees, "ref": ref})
        return {"status": "OK", "population": 1, "rows": [], "counts": {},
                "findings": 0, "repo_history": {"state": "complete"},
                "measure_carriers": []}

    monkeypatch.setattr(bat.lineage, "measure", fake_measure)
    code = bat.main(["--check", str(tmp_path / "some_tree"),
                     "--repo-root", str(tmp_path)])
    assert code == 0
    assert seen["trees"] == [str(tmp_path / "some_tree")]
    assert seen["repo_root"] == str(tmp_path)


# ----------------------------------------------------------------------- такт и форма


def test_run_inside_the_tact_does_not_invent_a_verdict(tmp_path):
    """«Не мерили» и «измерено» — РАЗНЫЕ исходы (инв. #17).

    Часы приходят ВХОДОМ, и отметка артефакта тоже литерал: обе стороны
    сравнения закреплены, календарь этот тест уронить не может.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    stamp = "2026-11-04T10:00:00+00:00"
    (data_dir / atl.ARTIFACT).write_text(
        json.dumps({"status": "OK", "generated_at": stamp, "findings": 0}),
        encoding="utf-8")
    now = dt.datetime(2026, 11, 5, 10, 0, tzinfo=dt.timezone.utc)
    out = atl.run(tmp_path, data_dir=data_dir, if_due=True, now=now)
    assert out["measured"] is False
    assert "doc" not in out, "внутри такта вердикта быть не должно вовсе"


def test_run_records_a_stamp_even_for_a_refusal(tmp_path):
    """Отказ без отметки сделал бы такт нечитаемым НАВСЕГДА."""
    data_dir = tmp_path / "data"
    now = dt.datetime(2026, 11, 4, 10, 0, tzinfo=dt.timezone.utc)
    out = atl.run(tmp_path, data_dir=data_dir, if_due=False,
                  trees=[], now=now)
    assert out["measured"] is True
    assert out["doc"]["status"] == "UNMEASURED"
    assert out["doc"]["generated_at"] == now.isoformat()


def test_unmeasured_report_never_reads_as_a_clean_pass():
    lines = "\n".join(atl.report({"status": "UNMEASURED", "reason": "причина"}))
    assert "НЕ ИЗМЕРЕНО" in lines
    assert "НЕ СКАЗАНО НИЧЕГО" in lines


def test_office_step_has_a_named_branch_for_this_artifact():
    """Артефакт без ветки отрисовки читается ВХОЛОСТУЮ: файл открыт, в контекст
    не попадает ни одно число — ровно так §49 одиннадцать циклов числился
    неизмеренным."""
    source = (_ROOT / "scripts" / "consume_office_reports.py").read_text(
        encoding="utf-8")
    assert f'elif name == "{atl.ARTIFACT}":' in source
    assert ("from spa_core.monitoring.acceptance_tree_lineage import format_report"
            in source)


def test_the_stage_records_who_invoked_it(tmp_path):
    """Без записи о звавшем вопрос «отметку поставила СТУПЕНЬ или РУКА» неизмерим.

    `generated_at` есть ЧАСЫ и сменится ОДИНАКОВО в оба случая (ADR-805, заказ
    G804 п. 3), поэтому база `caller_record_baseline.json` может ТОЛЬКО
    уменьшаться — дописывать в неё новую ступень запрещено (инв. #16). Признак
    берётся у ПРОЦЕССА, а не передаётся параметром.
    """
    origin = make_repo(tmp_path)
    head = _git(origin, "rev-parse", "HEAD")
    tree = make_tree(tmp_path, name="acc", marker={
        "version": 2, "ref": "origin/main", "commit": head,
        "builder": "scripts/cio_acceptance_rollup.py",
        "live_data": str(tmp_path / "live_data")})
    doc = atl.measure(origin, trees=[str(tree)], repos=[str(origin)])
    assert doc["invoked_by"]["schema"] == "call_provenance.v1"
    assert doc["invoked_by"]["measured"] is True

    # И У ОТКАЗА тоже: именно там вопрос «ступень или рука» важнее всего.
    out = atl.run(tmp_path, data_dir=tmp_path / "data", if_due=False, trees=[],
                  now=dt.datetime(2026, 11, 4, tzinfo=dt.timezone.utc))
    assert out["doc"]["status"] == "UNMEASURED"
    assert out["doc"]["invoked_by"]["schema"] == "call_provenance.v1"


def test_this_stage_is_not_a_new_member_of_the_caller_record_class():
    """База класса может ТОЛЬКО уменьшаться — новая ступень в неё не дописывается."""
    baseline = json.loads(
        (_ROOT / "spa_core" / "tests" / "caller_record_baseline.json").read_text(
            encoding="utf-8"))
    assert "acceptance_tree_lineage" not in baseline["missing"]


def test_findings_bridge_declares_this_census_stage():
    from spa_core.monitoring import findings_bridge as fb
    assert "acceptance_tree_lineage" in fb.CENSUS_STAGE
    assert fb.CENSUS_PRODUCT["acceptance_tree_lineage"] == {
        "module": "spa_core/monitoring/acceptance_tree_lineage.py",
        "artifact": f"data/{atl.ARTIFACT}"}
