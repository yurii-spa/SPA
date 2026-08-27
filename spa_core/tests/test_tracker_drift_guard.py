"""Сторож дрейфа трекера (`scripts/check_tracker_drift.py`) + сверка очереди с origin.

**Каждый тест здесь — воспроизведение настоящей аварии цикла #147.** Проверка, никогда не
видевшая живой поломки, — украшение (правило `.claude/rules/deployment.md`).

Что случилось 2026-08-07. `orchestrator_queue.py list` (шаг 1 протокола) читает трекер ТОГО
дерева, чья копия скрипта запущена. Циклы работают в изолированных worktree и пушат прямо на
origin — хост-дерево не обновляется никогда, и никто эти два набора карточек не сверял. Живой
замер на хост-дереве: **260 карточек против 281 на origin**, 33 расхождения. Очередь выдала
**5 карточек `inbox/new`**, из которых на origin закрыты 4, и НЕ показала **21** карточку,
включая **три вопроса владельца в `needs-owner`**; в очереди владельца три УЖЕ отвеченных
вопроса числились ждущими ответа. Список был неверен в обе стороны одновременно.

Литеральных дат здесь нет: всё время инъектируется через содержимое фикстур, календарь на
эти тесты не влияет (правило про фиксированные даты — `.claude/rules/deployment.md`).

**Что приёмка мутациями НЕ поймала, записано честно.** Снятие ОДНОГО стража `ref` (проверка
`rev-parse` в `origin_snapshot`) вердикт не меняет: «не измерено» при отсутствующем ref держат
ТРИ независимые точки (`rev-parse` · код `ls-tree` · код `rev-list` в `historical_blobs`), и
мутант эквивалентен. Тест `test_missing_ref_is_unmeasured_not_clean` краснеет, когда сняты все
три (проверено) либо когда `main()` отдаёт на «не измерено» код 0 вместо 2 (проверено) — то
есть он держит СВОЙСТВО fail-CLOSED, а не конкретную строку. Это разница между «проверка
слабая» и «свойство не принадлежит одной строке»; вторая формулировка — верная.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"
for _p in (str(_REPO_ROOT), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import check_tracker_drift as drift  # noqa: E402
from spa_core.owner_queue.queue import load_card, load_card_text  # noqa: E402

REF = "main"


def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


def _card(title="карточка", status="new", body="тело", extra=""):
    return (f"---\ntrackerStatus:\n  type: inbox\ntitle: \"{title}\"\nstatus: {status}\n"
            f"{extra}---\n\n{body}\n")


@pytest.fixture()
def repo(tmp_path):
    """Крошечный репозиторий с каталогом трекера и веткой-«origin». Без сети."""
    root = tmp_path / "repo"
    (root / drift.TRACKER_REL).mkdir(parents=True)
    _run(root.parent, "init", "-q", "-b", REF, str(root))
    _run(root, "config", "user.email", "t@example.com")
    _run(root, "config", "user.name", "test")
    return root


def _tracker(root: Path) -> Path:
    return root / drift.TRACKER_REL


def _write(root: Path, name: str, text: str) -> Path:
    p = _tracker(root) / f"{name}.md"
    p.write_text(text, encoding="utf-8")
    return p


def _commit(root: Path, msg="c"):
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", msg)


# --------------------------------------------------------------------------------------
# Авария №1 (ядро дефекта): карточка ЗАКРЫТА на origin, в дереве лежит прежняя копия.
# Именно так очередь четыре дня подряд выдавала сделанное как новое.
# --------------------------------------------------------------------------------------

def test_closed_on_origin_stale_in_tree_is_reported_stale_with_origin_status(repo):
    _write(repo, "inbox-x", _card(status="new"))
    _commit(repo)
    stale_text = (_tracker(repo) / "inbox-x.md").read_text(encoding="utf-8")
    _write(repo, "inbox-x", _card(status="done", body="тело\n\n## Резолюция"))
    _commit(repo, "закрыта")
    # дерево откатываем к прежней версии — ровно состояние хост-дерева
    _write(repo, "inbox-x", stale_text)

    report = drift.analyze(_tracker(repo), REF)
    stale = report.of_kind(drift.KIND_STALE)
    assert [f.card_id for f in stale] == ["inbox-x"]
    assert stale[0].tree_status == "new"
    assert stale[0].origin_status == "done", "статус ДОЛЖЕН читаться с origin, иначе очередь врёт"


def test_stale_card_is_not_emitted_as_new_by_the_queue(repo, capsys):
    """Критерий приёмки карточки дословно: «закрытая на origin не выдаётся очередью как new»."""
    import orchestrator_queue as oq

    _write(repo, "inbox-x", _card(title="закрытая", status="new"))
    _commit(repo)
    stale_text = (_tracker(repo) / "inbox-x.md").read_text(encoding="utf-8")
    _write(repo, "inbox-x", _card(title="закрытая", status="done"))
    _write(repo, "inbox-live", _card(title="живая", status="new"))
    _commit(repo)
    _write(repo, "inbox-x", stale_text)

    args = oq.build_parser().parse_args(
        ["list", "--type", "inbox", "--status", "new", "--tracker-dir", str(_tracker(repo)), "--ref", REF])
    oq.cmd_list(args)
    out = capsys.readouterr()
    assert "inbox-x" not in out.out, "закрытая на origin карточка снова выдана как новая"
    assert "inbox-live" in out.out, "живую карточку сторож выбрасывать не смеет"


def test_no_origin_check_reproduces_the_defect(repo, capsys):
    """Положительный контроль: со снятой сверкой дефект возвращается ДОСЛОВНО."""
    import orchestrator_queue as oq

    _write(repo, "inbox-x", _card(status="new"))
    _commit(repo)
    stale_text = (_tracker(repo) / "inbox-x.md").read_text(encoding="utf-8")
    _write(repo, "inbox-x", _card(status="done"))
    _commit(repo)
    _write(repo, "inbox-x", stale_text)

    args = oq.build_parser().parse_args(
        ["list", "--type", "inbox", "--status", "new",
         "--tracker-dir", str(_tracker(repo)), "--no-origin-check", "--ref", REF])
    oq.cmd_list(args)
    assert "inbox-x" in capsys.readouterr().out


# --------------------------------------------------------------------------------------
# Авария №2: карточка есть на origin, а файла в дереве нет — задание НЕВИДИМО.
# Живьём так пропали 21 карточка, включая ТРИ вопроса владельца в needs-owner.
# --------------------------------------------------------------------------------------

def test_card_only_on_origin_is_reported_hidden_not_silence(repo):
    _write(repo, "inbox-hidden", _card(title="вопрос владельцу", status="new"))
    _commit(repo)
    (_tracker(repo) / "inbox-hidden.md").unlink()

    report = drift.analyze(_tracker(repo), REF)
    hidden = report.of_kind(drift.KIND_HIDDEN)
    assert [f.card_id for f in hidden] == ["inbox-hidden"]
    assert hidden[0].origin_status == "new"
    assert hidden[0].tracker_type == "inbox", "тип обязан читаться с origin — по нему фильтр"


def test_hidden_cards_are_named_out_loud_by_the_queue(repo, capsys):
    """НАМЕРЕННОЕ изменение проверки (инв. #16), цикл #395 — обоснование ниже.

    Прежняя редакция требовала `"inbox-hidden" not in out.out` с доводом «файла нет —
    путь-фантом сломал бы set-status». Довод оказался дороже беды, от которой защищал:
    невидимая карточка не попадала в машинный контракт ВООБЩЕ, а его читают шаги 1 и 2
    протокола. Замер 27.08 (циклы #393/#395) на живом прод-дереве: `inbox/new` = **42**
    при **89** на origin; `owner-done` = **0** при **2**. Решение владельца могло ждать
    инжеста сутками, и заметить это было некому.

    «Путь-фантом сломал бы set-status» — не сломал бы МОЛЧА: `set-status` по
    несуществующему файлу отказывает ГРОМКО и кодом 1 (закреплено отдельным тестом в
    `test_orchestrator_queue_hidden_cards.py`), а это и есть верный ответ — править надо
    из worktree на origin/main. Проверка не ослаблена, а ПЕРЕВЁРНУТА на новый контракт и
    УСИЛЕНА: теперь она требует и stderr-строку, и присутствие в stdout, и вердикт
    `hidden_read_from_origin` в машинном поле, чего прежняя не проверяла.
    """
    import orchestrator_queue as oq

    _write(repo, "inbox-hidden", _card(status="new"))
    _write(repo, "inbox-here", _card(status="new"))
    _commit(repo)
    (_tracker(repo) / "inbox-hidden.md").unlink()

    args = oq.build_parser().parse_args(
        ["list", "--type", "inbox", "--status", "new", "--json",
         "--tracker-dir", str(_tracker(repo)), "--ref", REF])
    oq.cmd_list(args)
    out = capsys.readouterr()
    assert "inbox-hidden" in out.err, "невидимая карточка обязана быть НАЗВАНА, а не пропущена молча"
    rows = {c["id"]: c for c in __import__("json").loads(out.out)}
    assert "inbox-hidden" in rows, "невидимая карточка обязана ВОЙТИ в список — её читает шаг 2"
    assert rows["inbox-hidden"]["origin_check"] == oq.VERDICT_HIDDEN, (
        "в машинном контракте обязано стоять «прочитана с origin», а не «совпало»")
    assert "inbox-here" in rows, "живую карточку сторож выбрасывать не смеет"


# --------------------------------------------------------------------------------------
# Авария №3: карточка отличается ТОЛЬКО полями захвата. Без нормализации она навсегда
# «разошедшаяся» — так три из пяти закрытых карточек продолжали числиться новыми.
# --------------------------------------------------------------------------------------

def test_claim_fields_alone_do_not_hide_that_the_tree_is_behind(repo):
    _write(repo, "inbox-x", _card(status="new"))
    _commit(repo)
    _write(repo, "inbox-x", _card(status="done"))
    _commit(repo)
    _write(repo, "inbox-x", _card(status="new", extra="claimed_by: cycle-1\nclaimed_at: T\n"))

    report = drift.analyze(_tracker(repo), REF)
    assert [f.card_id for f in report.of_kind(drift.KIND_STALE)] == ["inbox-x"]
    assert not report.of_kind(drift.KIND_DIVERGED)


def test_strip_claim_keys_touches_only_top_level_frontmatter_keys():
    text = ("---\ntrackerStatus:\n  type: inbox\n  claimed_by: вложенный\n"
            "status: new\nclaimed_by: cycle-1\nclaimed_at: T\n---\n\nclaimed_by: в теле\n")
    out = drift.strip_claim_keys(text)
    assert "cycle-1" not in out and "claimed_at: T" not in out
    assert "  claimed_by: вложенный" in out, "вложенный ключ — не захват, трогать нельзя"
    assert "claimed_by: в теле" in out, "тело карточки неприкосновенно"


def test_file_without_frontmatter_is_returned_byte_for_byte():
    text = "просто текст\nclaimed_by: не frontmatter\n"
    assert drift.strip_claim_keys(text) == text


# --------------------------------------------------------------------------------------
# Обратная сторона: СВОЮ правку дерева переписывать нельзя. Массовый checkout стёр бы
# карточки, живущие только в рабочем дереве, — поэтому недоказанное остаётся недоказанным.
# --------------------------------------------------------------------------------------

def test_genuine_local_edit_is_diverged_and_never_silently_overridden(repo, capsys):
    import orchestrator_queue as oq

    _write(repo, "inbox-x", _card(status="new"))
    _commit(repo)
    _write(repo, "inbox-x", _card(status="done"))
    _commit(repo)
    _write(repo, "inbox-x", _card(status="new", body="СВОЯ правка, которой на origin нет"))

    report = drift.analyze(_tracker(repo), REF)
    assert [f.card_id for f in report.of_kind(drift.KIND_DIVERGED)] == ["inbox-x"]
    assert not report.of_kind(drift.KIND_STALE)

    args = oq.build_parser().parse_args(
        ["list", "--type", "inbox", "--status", "new", "--tracker-dir", str(_tracker(repo)), "--ref", REF])
    oq.cmd_list(args)
    out = capsys.readouterr()
    assert "inbox-x" in out.out, "недоказанное устаревание — не повод выбросить карточку"
    assert "inbox-x" in out.err, "…но расхождение обязано быть названо"


def test_card_only_in_tree_is_undelivered(repo):
    _write(repo, "inbox-old", _card())
    _commit(repo)
    _write(repo, "inbox-local", _card(title="создана в дереве"))
    report = drift.analyze(_tracker(repo), REF)
    assert [f.card_id for f in report.of_kind(drift.KIND_UNDELIVERED)] == ["inbox-local"]


def test_card_deleted_on_origin_is_told_apart_from_undelivered(repo):
    _write(repo, "inbox-gone", _card())
    _commit(repo)
    gone = (_tracker(repo) / "inbox-gone.md").read_text(encoding="utf-8")
    (_tracker(repo) / "inbox-gone.md").unlink()
    _commit(repo, "удалена на origin")
    _write(repo, "inbox-gone", gone)

    report = drift.analyze(_tracker(repo), REF)
    assert [f.card_id for f in report.of_kind(drift.KIND_DELETED)] == ["inbox-gone"]
    assert not report.of_kind(drift.KIND_UNDELIVERED)


def test_identical_trees_produce_no_findings_and_exit_zero(repo):
    _write(repo, "inbox-x", _card())
    _commit(repo)
    report = drift.analyze(_tracker(repo), REF)
    assert report.findings == []
    assert drift.main(["--tracker-dir", str(_tracker(repo)), "--ref", REF]) == 0


def test_board_index_is_not_treated_as_a_card(repo):
    """`_BOARD.md` расходится ВСЕГДА (регенерится из своего дерева) — вечная находка приучила
    бы пролистывать вывод сторожа мимо настоящих."""
    _write(repo, "_BOARD", "# доска origin\n")
    _commit(repo)
    _write(repo, "_BOARD", "# доска дерева\n")
    report = drift.analyze(_tracker(repo), REF)
    assert [f.card_id for f in report.findings] == []


# --------------------------------------------------------------------------------------
# Fail-CLOSED: «не измерено» никогда не должно читаться как «расхождений нет».
# --------------------------------------------------------------------------------------

def test_missing_ref_is_unmeasured_not_clean(repo):
    _write(repo, "inbox-x", _card())
    _commit(repo)
    with pytest.raises(drift.Unmeasured):
        drift.analyze(_tracker(repo), "no-such-ref")
    assert drift.main(["--tracker-dir", str(_tracker(repo)), "--ref", "no-such-ref"]) == 2


def test_missing_tracker_dir_is_unmeasured_not_clean(repo):
    _commit_root = repo / "seed.txt"
    _commit_root.write_text("x", encoding="utf-8")
    _commit(repo)
    with pytest.raises(drift.Unmeasured):
        drift.analyze(repo / "nimbalyst-local" / "nope", REF)
    assert drift.main(["--tracker-dir", str(repo / "nimbalyst-local" / "nope"), "--ref", REF]) == 2


def test_findings_exit_one(repo):
    _write(repo, "inbox-x", _card())
    _commit(repo)
    _write(repo, "inbox-local", _card())
    assert drift.main(["--tracker-dir", str(_tracker(repo)), "--ref", REF]) == 1


def test_unmeasured_queue_says_so_and_does_not_pretend_the_list_is_verified(repo, capsys, monkeypatch):
    import orchestrator_queue as oq

    _write(repo, "inbox-x", _card(status="new"))
    _commit(repo)

    def _boom(*a, **kw):
        raise drift.Unmeasured("зонд не выполнился")

    monkeypatch.setattr(drift, "analyze", _boom)
    args = oq.build_parser().parse_args(
        ["list", "--type", "inbox", "--status", "new", "--tracker-dir", str(_tracker(repo)), "--ref", REF])
    oq.cmd_list(args)
    out = capsys.readouterr()
    assert "НЕ ИЗМЕРЕНА" in out.err
    assert "inbox-x" in out.out, "молчаливо ослеплять очередь тоже нельзя — но и молчать о том, "\
                                 "что она не подтверждена, запрещено"


# --------------------------------------------------------------------------------------
# Границы инструмента, закреплённые намеренно.
# --------------------------------------------------------------------------------------

def test_guard_never_touches_the_network(repo, monkeypatch):
    """`git fetch` не вызывается НИКОГДА (как и в шаге 0a): сторож сверяется с той копией
    origin, что уже есть локально, и обязан честно печатать её sha, а не ходить в сеть."""
    _write(repo, "inbox-x", _card())
    _commit(repo)
    seen = []
    real = drift._git

    def _spy(root, args, stdin_text=None):
        seen.append(list(args))
        return real(root, args, stdin_text)

    monkeypatch.setattr(drift, "_git", _spy)
    drift.analyze(_tracker(repo), REF)
    assert seen, "зонд обязан хоть что-то спросить у git"
    forbidden = {"fetch", "pull", "remote", "ls-remote", "clone"}
    assert not [a for a in seen if a and a[0] in forbidden], f"сторож пошёл в сеть: {seen}"


def test_ref_sha_is_always_reported(repo):
    """«Сверено с origin» нельзя читать как «сверено с самой свежей версией origin»."""
    _write(repo, "inbox-x", _card())
    _commit(repo)
    report = drift.analyze(_tracker(repo), REF)
    assert len(report.ref_sha) == 40
    assert report.ref_sha[:9] in drift.format_report(report)


def test_blob_sha_matches_git(repo):
    p = _write(repo, "inbox-x", _card())
    expected = _run(repo, "hash-object", str(p)).strip()
    assert drift.blob_sha(p.read_bytes()) == expected


def test_claim_key_names_come_from_the_writer_not_a_local_copy():
    """Если в захват добавят третье поле, сторож обязан узнать об этом ОТТУДА, где его пишут."""
    import check_card_claim

    assert drift._CLAIM_KEYS is check_card_claim._CLAIM_KEYS


# --------------------------------------------------------------------------------------
# Один парсер на обоих читателей (урок #143–#145: вторая копия правила = невидимые карточки).
# --------------------------------------------------------------------------------------

def test_load_card_text_and_load_card_agree_field_for_field(tmp_path):
    text = _card(title="один парсер", status="in-progress", extra="priority: high\n")
    p = tmp_path / "inbox-y.md"
    p.write_text(text, encoding="utf-8")
    from_disk, from_text = load_card(p), load_card_text(text, p.name)
    for field in ("tracker_type", "title", "status", "priority", "owner", "legacy_id", "body"):
        assert getattr(from_disk, field) == getattr(from_text, field), field
    assert from_disk.fields == from_text.fields


def test_load_card_text_resolves_type_by_filename_when_undeclared():
    card = load_card_text("---\ntitle: x\nstatus: backlog\n---\n\nтело\n", "agent-foo.md")
    assert card.tracker_type == "agent-task"


def test_origin_card_keeps_the_local_path_so_set_status_still_works(repo, capsys):
    """Карточка читается с origin, но путь остаётся местный — иначе `set-status` из вывода
    очереди писал бы в никуда."""
    import orchestrator_queue as oq

    _write(repo, "inbox-x", _card(status="new"))
    _commit(repo)
    stale = (_tracker(repo) / "inbox-x.md").read_text(encoding="utf-8")
    _write(repo, "inbox-x", _card(status="in-progress"))
    _commit(repo)
    _write(repo, "inbox-x", stale)

    args = oq.build_parser().parse_args(
        ["list", "--type", "inbox", "--status", "in-progress", "--json",
         "--tracker-dir", str(_tracker(repo)), "--ref", REF])
    oq.cmd_list(args)
    import json as _json
    payload = _json.loads(capsys.readouterr().out)
    assert [c["id"] for c in payload] == ["inbox-x"]
    assert Path(payload[0]["path"]) == _tracker(repo) / "inbox-x.md"
    assert os.path.exists(payload[0]["path"])
