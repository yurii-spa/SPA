"""ПОРЯДОК ОТМЕТОК у разошедшейся карточки — вместо глухого «кто новее НЕ измерено».

**Каждый тест здесь воспроизводит настоящий замер 2026-09-04 (цикл #483).** Проверка,
никогда не видевшая живой поломки, — украшение (правило `.claude/rules/deployment.md`).

Что было. Сверка трекера с `origin/main` делит расхождения на классы, и класс `diverged`
(«содержимого дерева нет в истории ref») нёс ОДИН вердикт на всех — `diverged_unmeasured`,
а в stderr печаталась простыня имён под советом «сверьте руками». Живой замер: таких
карточек **132**. Совет на 132 позиции исполнить нельзя; это не сигнал, а шум, которым
сторожа глохнут (урок #243).

При этом мерка порядка в проекте УЖЕ БЫЛА и работала:
`spa_core.owner_queue.status_audit.latest_change_at` читает и след переходов
(`status_trail`, его пишет наш код на каждом `set_status`), и отметку ответа владельца
(`owner_answered_at`, её пишет бот прямо в прод-дерево мимо git). Звал её ОДИН потребитель
— `owner_decision_pending`, и ровно для ЗЕРКАЛЬНОГО случая («открыто здесь, закрыто на
origin»). Здесь она не звалась НИКОГДА: источник без потребителя (класс ADR-209).

Замер того же дня после починки: из 132 порядок устанавливается у **35** (наша новее 29,
ref новее 6), и одна из них — настоящая недоставленная закрытость
`inbox-task-portfolio-cio-dynamic-capital-alloc` (`done` в прод-дереве, `in-progress` на
`origin/main`), ТА САМАЯ карточка, ради которой написан шаг 0a-голод протокола.

**Направление обязано быть ИЗМЕРЕНО, а не предположено.** Прод-дерево — писатель ответов
владельца, поэтому «у нас закрыто, а там открыто» само по себе не значит ничего: поздний
ответ владельца выглядит так же. Соглашения об исходах здесь ДОСЛОВНО те же, что у
`owner_decision_pending` — две мерки одного порядка разошлись бы молча.

Литеральных дат нет: отметки строятся относительно (`_freshness.ts`), а предмет проверки —
ПОРЯДОК двух отметок, а не календарь.
"""

from __future__ import annotations

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
from spa_core.tests._freshness import ts  # noqa: E402

REF = "main"


def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


def _card(*, status="new", title="карточка", trail=(), owner_answered_at=None, body="тело"):
    """Карточка со следом переходов и/или отметкой ответа владельца.

    Обе породы отметок обязательны в фикстуре: одну пишет наш код, другую — бот, и
    мерка `latest_change_at` берёт ПОЗДНЕЙШУЮ из двух. Тест, знающий только про след,
    не увидел бы позднего `ack` владельца — того самого случая, ради которого поле
    `owner_answered_at` в мерку и внесено.
    """
    extra = ""
    if owner_answered_at:
        extra += f"owner_answered_at: {owner_answered_at}\n"
    if trail:
        extra += "status_trail:\n" + "".join(f'  - "{line}"\n' for line in trail)
    return (f"---\ntrackerStatus:\n  type: inbox\ntitle: \"{title}\"\nstatus: {status}\n"
            f"{extra}---\n\n{body}\n")


def _trail(stamp, old, new, source="queue.set_status"):
    return f"{stamp} {old} -> {new} · {source}"


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


def _diverge(root, name, *, origin_text, tree_text):
    """Карточка, разошедшаяся с ref: на ref одна редакция, в дереве СВОЯ (не из истории)."""
    _write(root, name, origin_text)
    _commit(root, f"{name} на ref")
    _write(root, name, tree_text)


def _finding(root, name):
    report = drift.analyze(_tracker(root), REF)
    for f in report.of_kind(drift.KIND_DIVERGED):
        if f.card_id == name:
            return f
    raise AssertionError(f"{name} не попала в класс diverged: "
                         f"{[(x.kind, x.card_id) for x in report.findings]}")


# ---------------------------------------------------------------------------------------
# Авария (ядро): закрытие, которое не доехало. Наша отметка ПОЗЖЕ — порядок установлен.
# ---------------------------------------------------------------------------------------

def test_local_mark_later_than_origin_is_named_tree_newer(repo):
    """`inbox-task-portfolio-cio-dynamic-capital-alloc` в миниатюре: закрыли позже ref'а."""
    _diverge(repo, "inbox-x",
             origin_text=_card(status="in-progress",
                               trail=[_trail(ts(hours_ago=48), "new", "in-progress")]),
             tree_text=_card(status="done",
                             trail=[_trail(ts(hours_ago=48), "new", "in-progress"),
                                    _trail(ts(hours_ago=2), "in-progress", "done")]))
    f = _finding(repo, "inbox-x")
    assert f.order == drift.ORDER_TREE_NEWER, f.order_detail
    assert f.tree_status == "done" and f.origin_status == "in-progress"


def test_origin_mark_later_is_named_origin_newer(repo):
    _diverge(repo, "inbox-x",
             origin_text=_card(status="done", body="и ещё абзац",
                               trail=[_trail(ts(hours_ago=1), "new", "done")]),
             tree_text=_card(status="new", body="своя правка",
                             trail=[_trail(ts(hours_ago=30), "new", "new")]))
    assert _finding(repo, "inbox-x").order == drift.ORDER_ORIGIN_NEWER


def test_our_copy_never_moved_means_origin_is_ahead(repo):
    """Соглашение ДОСЛОВНО как у `owner_decision_pending`: наша копия стои́т, где родилась."""
    _diverge(repo, "inbox-x",
             origin_text=_card(status="done", trail=[_trail(ts(hours_ago=3), "new", "done")]),
             tree_text=_card(status="new", body="своя правка тела"))
    assert _finding(repo, "inbox-x").order == drift.ORDER_ORIGIN_NEWER


def test_owner_answer_stamp_counts_as_a_mark(repo):
    """Поздний ответ владельца пишет БОТ мимо git — и он может быть новее любого следа.

    Читать один только `status_trail` значило бы объявить копию с живым ответом
    владельца отставшей (карточка `inbox-pozdnii-prinyato-voskreshaet-kartochku-z`).
    """
    _diverge(repo, "inbox-x",
             origin_text=_card(status="ingested",
                               trail=[_trail(ts(hours_ago=20), "needs-owner", "ingested")]),
             tree_text=_card(status="owner-done", owner_answered_at=ts(hours_ago=1),
                             trail=[_trail(ts(hours_ago=40), "new", "needs-owner")]))
    f = _finding(repo, "inbox-x")
    assert f.order == drift.ORDER_TREE_NEWER, (
        "отметку ответа владельца мерка обязана учитывать наравне со следом: "
        f"{f.order_detail}")


# ---------------------------------------------------------------------------------------
# ТРЕТИЙ ИСХОД. «Не установлено» — самостоятельный ответ с названной причиной,
# а не молчание и не выбор стороны наугад.
# ---------------------------------------------------------------------------------------

def test_no_mark_on_ref_is_unmeasured_not_we_are_newer(repo):
    """62 карточки из 132 живого замера. Соблазн прочитать это как «мы новее» — неверен.

    Отсутствие следа на ref означает лишь, что ту версию писал код, следа не оставлявший,
    а НЕ что она старше. Догадка здесь стоила бы дороже всей остальной находки.
    """
    _diverge(repo, "inbox-x",
             origin_text=_card(status="new", body="редакция ref"),
             tree_text=_card(status="done",
                             trail=[_trail(ts(hours_ago=2), "new", "done")]))
    f = _finding(repo, "inbox-x")
    assert f.order == drift.ORDER_UNMEASURED
    assert "НЕ значит, что она старше" in f.order_detail, "причина обязана быть НАЗВАНА"


def test_neither_copy_moved_is_unmeasured(repo):
    _diverge(repo, "inbox-x",
             origin_text=_card(status="in-progress", body="редакция ref"),
             tree_text=_card(status="in-progress", body="своя редакция"))
    f = _finding(repo, "inbox-x")
    assert f.order == drift.ORDER_UNMEASURED
    assert f.order_detail, "молчаливое «не измерено» — то же молчание"


def test_identical_stamps_do_not_establish_an_order(repo):
    same = ts(hours_ago=5)
    _diverge(repo, "inbox-x",
             origin_text=_card(status="done", body="ref",
                               trail=[_trail(same, "new", "done")]),
             tree_text=_card(status="done", body="дерево",
                             trail=[_trail(same, "new", "done")]))
    assert _finding(repo, "inbox-x").order == drift.ORDER_UNMEASURED


def test_order_is_asked_only_of_diverged_cards(repo):
    """У `stale` порядок ДОКАЗАН историей, у `undelivered` второй копии нет вовсе.

    Пустая строка `order` означает «этот класс о порядке не спрашивают», и путать её
    с `unmeasured` («спросили и не узнали») нельзя: это разные ответы.
    """
    _write(repo, "inbox-stale", _card(status="new"))
    _commit(repo)
    stale_text = (_tracker(repo) / "inbox-stale.md").read_text(encoding="utf-8")
    _write(repo, "inbox-stale", _card(status="done"))
    _commit(repo)
    _write(repo, "inbox-stale", stale_text)
    _write(repo, "inbox-undelivered", _card(status="new"))

    report = drift.analyze(_tracker(repo), REF)
    for f in report.findings:
        if f.kind != drift.KIND_DIVERGED:
            assert f.order == "" and f.order_detail == "", (
                f"{f.kind}/{f.card_id}: о порядке этот класс не спрашивают")


# ---------------------------------------------------------------------------------------
# ПОТРЕБИТЕЛЬ: очередь. Настоящая форма вызова `cmd_list`, а не подставленный lookup.
# ---------------------------------------------------------------------------------------

def _list(repo, capsys, *extra):
    import orchestrator_queue as oq
    args = oq.build_parser().parse_args(
        ["list", "--tracker-dir", str(_tracker(repo)), "--ref", REF, *extra])
    oq.cmd_list(args)
    return capsys.readouterr()


def _undelivered_closure_repo(repo):
    """Закрыто здесь, открыто на ref, наша отметка позже — живой случай замера."""
    _diverge(repo, "inbox-task-cio",
             origin_text=_card(status="in-progress", title="закрытие не доехало",
                               trail=[_trail(ts(hours_ago=48), "new", "in-progress")]),
             tree_text=_card(status="done", title="закрытие не доехало",
                             trail=[_trail(ts(hours_ago=48), "new", "in-progress"),
                                    _trail(ts(hours_ago=2), "in-progress", "done")]))


def test_queue_names_the_undelivered_closure_by_name(repo, capsys):
    _undelivered_closure_repo(repo)
    out = _list(repo, capsys)
    assert "ЗАКРЫТО ТОЛЬКО ЗДЕСЬ" in out.err, out.err
    assert "inbox-task-cio" in out.err, "единственную группу, где есть что делать, зовут по имени"


def test_queue_verdict_travels_in_the_machine_contract(repo, capsys):
    """Шаги протокола читают JSON: вердикт, живущий только в прозе stderr, невидим им."""
    import json
    _undelivered_closure_repo(repo)
    out = _list(repo, capsys, "--json")
    row = next(r for r in json.loads(out.out) if r["id"] == "inbox-task-cio")
    assert row["origin_check"] == "diverged_tree_newer", row
    assert row["origin_order"] == drift.ORDER_TREE_NEWER
    assert "закрытие есть ТОЛЬКО здесь" in row["origin_check_note"]
    assert "Исходов ДВА" in row["origin_check_note"], (
        "сторож меряет ПОРЯДОК и не выбирает между «довезти» и «закрытие неверно»")


def test_names_are_grouped_by_outcome_and_never_dropped(repo, capsys):
    """Замер: 132 имени лежали в ОДНОЙ куче под советом «сверьте руками».

    Шумом был СОВЕТ, а не имена: расхождение обязано быть названо, и это отдельный
    инвариант соседнего сторожа (`test_genuine_local_edit_is_diverged_and_never_silently_
    overridden`). Поэтому имена остаются, но раскладываются по исходу, а действие
    называется отдельной строкой — на той единственной группе, где оно есть.
    """
    # Все редакции ref — ОДНИМ коммитом: `_diverge` в цикле закоммитил бы правку
    # предыдущей карточки и та перестала бы расходиться (одна находка вместо четырёх).
    for i in range(3):
        _write(repo, f"inbox-quiet-{i}", _card(status="new", body=f"ref {i}"))
    _write(repo, "inbox-moved", _card(status="in-progress", body="ref",
                                      trail=[_trail(ts(hours_ago=40), "new", "in-progress")]))
    _commit(repo, "редакции ref")
    for i in range(3):
        _write(repo, f"inbox-quiet-{i}", _card(status="new", body=f"дерево {i}"))
    _write(repo, "inbox-moved", _card(status="done", body="дерево",
                                      trail=[_trail(ts(hours_ago=40), "new", "in-progress"),
                                             _trail(ts(hours_ago=1), "in-progress", "done")]))
    out = _list(repo, capsys)

    unmeasured = next(ln for ln in out.err.splitlines() if "порядок НЕ УСТАНОВЛЕН" in ln)
    newer = next(ln for ln in out.err.splitlines() if "наша отметка ПОЗЖЕ" in ln)
    assert "(3)" in unmeasured and "(1)" in newer, out.err
    for i in range(3):
        assert f"inbox-quiet-{i}" in unmeasured, "имя не имеет права ПРОПАСТЬ из отчёта"
        assert f"inbox-quiet-{i}" not in newer, "карточка не может стоять в двух исходах"
    assert "inbox-moved" in newer


def test_mirror_case_is_not_called_an_undelivered_closure(repo, capsys):
    """ЗЕРКАЛО: открыто здесь, закрыто на ref. Это не наше закрытие и звать его так нельзя."""
    _diverge(repo, "inbox-mirror",
             origin_text=_card(status="done", body="ref закрыл",
                               trail=[_trail(ts(hours_ago=1), "new", "done")]),
             tree_text=_card(status="new", body="здесь ещё открыта",
                             trail=[_trail(ts(hours_ago=30), "new", "new")]))
    out = _list(repo, capsys)
    assert "ЗАКРЫТО ТОЛЬКО ЗДЕСЬ" not in out.err, out.err


def test_undelivered_closure_needs_a_MEASURED_direction(repo, capsys):
    """Без измеренного порядка «закрыто здесь, открыто там» — НЕ находка, а незнание.

    Прод-дерево пишет ответы владельца мимо git, поэтому один только статус решить
    ничего не может. Тот же порядок судит `owner_decision_pending`.
    """
    _diverge(repo, "inbox-no-order",
             origin_text=_card(status="new", body="ref"),
             tree_text=_card(status="done", body="дерево",
                             trail=[_trail(ts(hours_ago=2), "new", "done")]))
    out = _list(repo, capsys)
    assert "ЗАКРЫТО ТОЛЬКО ЗДЕСЬ" not in out.err, (
        "порядок не установлен ⇒ находкой это называть нельзя:\n" + out.err)


# ---------------------------------------------------------------------------------------
# ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ и ПРОВОДКА. Сторож, который не краснеет на своей аварии, —
# украшение; вердикт, пересчитанный вторым экземпляром мерки, разъедется молча (ADR-220).
# ---------------------------------------------------------------------------------------

def test_removing_the_measure_brings_the_defect_back_verbatim(repo, capsys, monkeypatch):
    """Мутация: мерка всегда отвечает «не установлено» ⇒ находка ИСЧЕЗАЕТ дословно."""
    _undelivered_closure_repo(repo)
    assert "ЗАКРЫТО ТОЛЬКО ЗДЕСЬ" in _list(repo, capsys).err

    monkeypatch.setattr(drift, "mark_order",
                        lambda tree_text, origin_text: (drift.ORDER_UNMEASURED, "мутация"))
    out = _list(repo, capsys)
    assert "ЗАКРЫТО ТОЛЬКО ЗДЕСЬ" not in out.err, (
        "тест не отличает работающую мерку от снятой — он украшение")
    assert "порядок НЕ УСТАНОВЛЕН (1)" in out.err


def test_queue_reads_the_order_from_the_report_and_does_not_recompute_it(repo, capsys):
    """Проводка проверяется ФОРМОЙ: вердикт берётся из отчёта сторожа, а не считается заново.

    Если очередь заведёт СВОЮ копию мерки, этот тест останется зелёным при подменённом
    отчёте — поэтому он подменяет именно отчёт, а не мерку: расходятся молча как раз две
    копии, а не одна.
    """
    import orchestrator_queue as oq
    _undelivered_closure_repo(repo)

    real_analyze = drift.analyze

    def blanked(tracker_dir=None, ref=drift.DEFAULT_REF):
        report = real_analyze(tracker_dir, ref)
        for f in report.findings:
            f.order, f.order_detail = "", ""
        return report

    drift.analyze = blanked
    try:
        args = oq.build_parser().parse_args(
            ["list", "--tracker-dir", str(_tracker(repo)), "--ref", REF])
        oq.cmd_list(args)
    finally:
        drift.analyze = real_analyze
    out = capsys.readouterr()
    assert "ЗАКРЫТО ТОЛЬКО ЗДЕСЬ" not in out.err, (
        "очередь судит о порядке сама — это вторая копия мерки, и она разойдётся молча")


def test_one_measure_is_shared_with_owner_decision_pending():
    """Обе стороны зовут ОДНУ функцию. Вторая копия разъехалась бы молча (ADR-220)."""
    from spa_core.owner_queue import status_audit
    assert drift.latest_change_at is status_audit.latest_change_at
