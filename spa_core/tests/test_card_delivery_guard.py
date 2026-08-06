"""Гарантия: карточка, созданная посреди цикла, не может МОЛЧА не доехать до origin.

Дефект (карточка `inbox-kartochka-sozdannaya-posredi-tsikla-ne-d`, найден циклом #139,
механизм перемерен циклом #140):

`scripts/orchestrator_queue.py create` пишет карточку в трекер ТОГО рабочего дерева, чья
копия скрипта запущена. Замер #140 поправляет формулировку карточки («независимо от того,
из какого дерева его позвали»): решает дерево ЗАПУЩЕННОЙ КОПИИ, а `cwd` не влияет вовсе —
копия из worktree пишет в worktree, копия из хост-дерева пишет в хост-дерево, даже когда
её зовут с `cwd` внутри worktree. Протокол §3.4 обязывает работать и пушить из
изолированного worktree, списки файлов на пуш собираются по нему — и карточка, созданная
хост-копией, в них не попадает НИКОГДА.

Живой случай: `inbox-audit-prigodnosti-ne-videl-186-modulei-t` создана в 19:34, уже ПОСЛЕ
финального объявления цикла #138 в 19:18 («ДОСТАВЛЕН» — честного: цикл доставил ровно то,
что было в его дереве). На `origin` карточки не было; она лежала неотслеживаемой в
хост-дереве и нашлась случайной сверкой ИМЁН карточек, а не сторожем.

Это НЕ класс «сессия умерла между сделано и пушем» (пять случаев за неделю): процесс жив,
отчёт честен, карточки в дереве не было никогда. И шаг 0a его не видит по построению —
карточку, созданную посреди цикла, никто не объявлял, а он разбирает объявления.

Закрыто тремя разными по радиусу вещами, и тесты держат каждую:

1. **сторож** (`check_undelivered_work.undelivered_cards`) — карточка в НЕтерминальном
   статусе, лежащая в рабочем дереве и отсутствующая на базовом ref, есть находка.
   Ни на чьей внимательности не держится;
2. **шаг 0b** (`check_card_claim`) читает карточку с базового ref, когда в дереве её нет:
   иначе десять карточек, живущих только на origin, отвечали «НЕ ИЗМЕРЕНО» вечно —
   fail-CLOSED-вердикт над неизвестным, который сам не может рассосаться;
3. **`create --tracker-dir` + громкое предупреждение** в момент дефекта.

Все тесты герметичны: настоящие git-репозитории в ``tmp_path``, сети нет.
"""
import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="нужен настоящий git: сверка карточек идёт против базового ref "
           "(условный skipif — на машине с git тесты выполняются)",
)


def _load(name, rel):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load("_test_card_delivery_guard", "scripts/check_undelivered_work.py")


@pytest.fixture(scope="module")
def claim():
    return _load("_test_card_delivery_claim", "scripts/check_card_claim.py")


# ── хелперы ──────────────────────────────────────────────────────────────────

def _git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "HOME": str(cwd),
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                          text=True, env=env)


def _card(status="new", title="карточка"):
    fm = ["---", "trackerStatus:", "  type: inbox", f'title: "{title}"']
    if status is not None:
        fm.append(f"status: {status}")
    fm += ["---", "", "тело карточки", ""]
    return "\n".join(fm)


def _repo(tmp_path, name="repo", cards=()):
    """Репозиторий с трекером; `cards` — что закоммитить на базу (имя, статус)."""
    root = tmp_path / name
    (root / "nimbalyst-local" / "tracker").mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", "main", str(root))
    for cname, status in cards:
        (root / "nimbalyst-local" / "tracker" / cname).write_text(_card(status), encoding="utf-8")
    (root / "README.md").write_text("x", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


def _base_ref(root):
    """Локальный ref, играющий роль origin/main (сети в тестах нет)."""
    _git(root, "branch", "-f", "base_ref", "HEAD")
    return "base_ref"


# ══ 1. разбор статуса карточки ═══════════════════════════════════════════════

def test_card_status_reads_frontmatter(guard):
    assert guard.card_status(_card("needs-owner")) == "needs-owner"


def test_card_status_ignores_a_status_line_in_the_body(guard):
    """`status:` в ТЕЛЕ карточки статусом не является — иначе рассказ о статусе внутри
    текста («status: done, мы это закрыли») гасил бы находку о недоставленной карточке.

    Опасное направление проверяется ОТДЕЛЬНО и явно: карточка БЕЗ статуса в frontmatter,
    но со строкой `status: done` в теле, обязана остаться без статуса — иначе самая
    дефектная форма карточки получила бы самый мягкий (терминальный) режим. Первая версия
    этого теста мутацию не ловила: при статусе в frontmatter разбор до тела не доходит."""
    assert guard.card_status(_card("new") + "\nstatus: done\n") == "new"
    assert guard.card_status(_card(None) + "\nstatus: done\n") is None


def test_card_status_without_frontmatter_is_none(guard):
    assert guard.card_status("просто текст без frontmatter") is None


# ══ 2. сторож: положительные контроли реального случая #138 ══════════════════

def test_card_created_mid_cycle_and_absent_from_base_is_a_finding(guard, tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ реальной аварии: `inbox-audit-prigodnosti-ne-videl-186-modulei-t`
    создана в 19:34 (после объявления «ДОСТАВЛЕН» в 19:18), на origin её нет."""
    root = _repo(tmp_path, cards=[("inbox-staraya.md", "new")])
    ref = _base_ref(root)
    orphan = root / "nimbalyst-local" / "tracker" / "inbox-audit-prigodnosti-ne-videl-186-modulei-t.md"
    orphan.write_text(_card("new"), encoding="utf-8")

    findings, unmeasured = guard.undelivered_cards(root, ref, [root], git=guard._git)

    assert unmeasured == []
    assert [f["card"] for f in findings] == ["inbox-audit-prigodnosti-ne-videl-186-modulei-t"]
    assert findings[0]["status"] == "new"
    assert str(root) in findings[0]["trees"]
    assert ref in findings[0]["reason"]


def test_card_present_on_base_is_not_a_finding(guard, tmp_path):
    """Обратное плечо: доставленная карточка молчит (иначе «краснеет всегда» — не сторож)."""
    root = _repo(tmp_path, cards=[("inbox-dostavlena.md", "new")])
    findings, unmeasured = guard.undelivered_cards(root, _base_ref(root), [root], git=guard._git)
    assert findings == [] and unmeasured == []


def test_orphan_card_in_a_linked_worktree_is_found(guard, tmp_path):
    """Осиротевшая карточка лежит именно в worktree (§3.4 обязывает там работать) —
    сверка только с хост-деревом её не увидит. Живой прогон #140 нашёл так настоящую
    карточку ВЛАДЕЛЬЦА, 94 часа пролежавшую в `/private/tmp/spa_wt_c92`."""
    root = _repo(tmp_path, cards=[("inbox-staraya.md", "new")])
    ref = _base_ref(root)
    wt = tmp_path / "wt"
    _git(root, "worktree", "add", "-q", "--detach", str(wt), "HEAD")
    (wt / "nimbalyst-local" / "tracker" / "owner-decision-vazhnaya.md").write_text(
        _card("needs-owner"), encoding="utf-8")

    findings, _ = guard.undelivered_cards(root, ref, [root, wt], git=guard._git)

    assert [f["card"] for f in findings] == ["owner-decision-vazhnaya"]
    assert findings[0]["status"] == "needs-owner"


@pytest.mark.parametrize("status", ["done", "ingested", "owner-done", "rejected", "archived"])
def test_terminal_card_absent_from_base_is_not_a_finding(guard, tmp_path, status):
    """Отработанную карточку недоставленной работой звать не за что."""
    root = _repo(tmp_path, cards=[("inbox-staraya.md", "new")])
    ref = _base_ref(root)
    (root / "nimbalyst-local" / "tracker" / "inbox-zakryta.md").write_text(
        _card(status), encoding="utf-8")
    findings, _ = guard.undelivered_cards(root, ref, [root], git=guard._git)
    assert findings == []


def test_card_without_a_status_line_is_a_finding(guard, tmp_path):
    """Карточка без `status:` невидима для КАЖДОГО фильтра статуса — молчать о ней
    значило бы дать самой дефектной форме карточки самый мягкий режим (fail-CLOSED)."""
    root = _repo(tmp_path, cards=[("inbox-staraya.md", "new")])
    ref = _base_ref(root)
    (root / "nimbalyst-local" / "tracker" / "inbox-bez-statusa.md").write_text(
        _card(None), encoding="utf-8")
    findings, _ = guard.undelivered_cards(root, ref, [root], git=guard._git)
    assert [f["card"] for f in findings] == ["inbox-bez-statusa"]
    assert "нет status:" in findings[0]["status"]


def test_terminality_must_be_unanimous_across_trees(guard, tmp_path):
    """Одно дерево говорит `done`, другое `new` — карточка НЕтерминальна: иначе одна
    устаревшая копия гасила бы находку о живой карточке из соседнего дерева."""
    root = _repo(tmp_path, cards=[("inbox-staraya.md", "new")])
    ref = _base_ref(root)
    wt = tmp_path / "wt"
    _git(root, "worktree", "add", "-q", "--detach", str(wt), "HEAD")
    (root / "nimbalyst-local" / "tracker" / "inbox-spornaya.md").write_text(
        _card("done"), encoding="utf-8")
    (wt / "nimbalyst-local" / "tracker" / "inbox-spornaya.md").write_text(
        _card("new"), encoding="utf-8")

    findings, _ = guard.undelivered_cards(root, ref, [root, wt], git=guard._git)

    assert [f["card"] for f in findings] == ["inbox-spornaya"]
    assert set(findings[0]["status"].split("/")) == {"done", "new"}


def test_board_index_is_never_a_finding(guard, tmp_path):
    """`_BOARD.md` — производный индекс, пересобирается целиком; он не карточка."""
    root = _repo(tmp_path, cards=[("inbox-staraya.md", "new")])
    ref = _base_ref(root)
    (root / "nimbalyst-local" / "tracker" / "_BOARD.md").write_text("# доска", encoding="utf-8")
    findings, unmeasured = guard.undelivered_cards(root, ref, [root], git=guard._git)
    assert findings == [] and unmeasured == []


# ══ 3. fail-CLOSED: «не измерил» никогда не сворачивается в «всё доставлено» ══

def test_unresolvable_base_ref_is_unmeasured_not_silence(guard, tmp_path):
    root = _repo(tmp_path, cards=[("inbox-staraya.md", "new")])
    (root / "nimbalyst-local" / "tracker" / "inbox-novaya.md").write_text(
        _card("new"), encoding="utf-8")
    findings, unmeasured = guard.undelivered_cards(root, "net-takogo-ref", [root], git=guard._git)
    assert findings == []
    assert len(unmeasured) == 1 and "НЕ измерен" in unmeasured[0]["reason"]


def test_empty_card_listing_on_base_refuses_instead_of_flagging_everything(guard, tmp_path):
    """Пустой перечень карточек на базе — отказ, а не «на базе их нет»: иначе КАЖДАЯ
    карточка стала бы находкой, и сторож похоронил бы себя шумом в первый же день."""
    root = tmp_path / "pusto"
    (root / "nimbalyst-local" / "tracker").mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", "main", str(root))
    (root / "README.md").write_text("x", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    ref = _base_ref(root)
    (root / "nimbalyst-local" / "tracker" / "inbox-novaya.md").write_text(
        _card("new"), encoding="utf-8")

    findings, unmeasured = guard.undelivered_cards(root, ref, [root], git=guard._git)

    assert findings == []
    assert len(unmeasured) == 1 and "НЕ выполнена" in unmeasured[0]["reason"]


def test_a_checkout_without_a_tracker_raises_no_false_refusal(guard, tmp_path):
    """Чекаут без трекера — законное состояние, и отказ здесь был бы ЛОЖНОЙ тревогой.

    Найдено при первом же прогоне смежных наборов: требование к базе стояло ПЕРЕД вопросом
    «есть ли что сверять», и 15 герметичных тестов шага 0a покраснели — их репозитории
    трекера не содержат вовсе. Недоставленной может быть только карточка, которая ЛЕЖИТ
    в дереве; нет карточек — нечего и терять."""
    root = _repo(tmp_path, cards=[("inbox-staraya.md", "new")])
    ref = _base_ref(root)
    shutil.rmtree(root / "nimbalyst-local")

    cards, problems = guard.scan_tracker_cards([root, tmp_path / "nikakogo-dereva"])
    assert cards == {} and problems == []

    findings, unmeasured = guard.undelivered_cards(root, ref, [root], git=guard._git)
    assert findings == [] and unmeasured == []


def test_empty_tree_does_not_excuse_a_broken_base_when_cards_exist(guard, tmp_path):
    """Обратное плечо к предыдущему: как только карточки в дереве ЕСТЬ, нечитаемая база
    снова обязана давать отказ — послабление «нечего сверять» не должно протечь дальше."""
    root = _repo(tmp_path, cards=[("inbox-staraya.md", "new")])
    (root / "nimbalyst-local" / "tracker" / "inbox-novaya.md").write_text(
        _card("new"), encoding="utf-8")
    findings, unmeasured = guard.undelivered_cards(root, "net-takogo-ref", [root], git=guard._git)
    assert findings == [] and len(unmeasured) == 1


def test_unreadable_card_is_unmeasured_not_skipped(guard, tmp_path, monkeypatch):
    root = _repo(tmp_path, cards=[("inbox-staraya.md", "new")])
    bad = root / "nimbalyst-local" / "tracker" / "inbox-bitaya.md"
    bad.write_text(_card("new"), encoding="utf-8")
    real_read = Path.read_text

    def boom(self, *a, **kw):
        if self.name == "inbox-bitaya.md":
            raise OSError("нечитаема")
        return real_read(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", boom)
    cards, problems = guard.scan_tracker_cards([root])
    assert "inbox-bitaya.md" not in cards
    assert any("НЕ измерен" in p for p in problems)


# ══ 4. встраивание в отчёт шага 0a: код возврата и печать ════════════════════

def _report(guard, root, ref, now=None):
    return guard.build_report(entries=[], root=root, base_ref=ref, self_session="pid1",
                              ps=lambda pid: None, git=guard._git, log_path=None, now=now)


def test_card_finding_alone_makes_the_step_red(guard, tmp_path):
    """Объявлений нет вовсе — а код возврата обязан стать 1: до цикла #140 такой прогон
    печатал «✅ измерено полностью, всё доставлено» при осиротевшей карточке в дереве."""
    root = _repo(tmp_path, cards=[("inbox-staraya.md", "new")])
    ref = _base_ref(root)
    (root / "nimbalyst-local" / "tracker" / "inbox-osirotela.md").write_text(
        _card("new"), encoding="utf-8")

    report = _report(guard, root, ref)

    assert [c["card"] for c in report["card_findings"]] == ["inbox-osirotela"]
    assert report["exit_code"] == 1
    text = guard.render(report)
    assert "КАРТОЧКИ НЕ ДОСТАВЛЕНЫ" in text and "inbox-osirotela" in text
    assert "всё доставлено" not in text


def test_clean_tree_still_reports_everything_delivered(guard, tmp_path):
    root = _repo(tmp_path, cards=[("inbox-staraya.md", "new")])
    report = _report(guard, root, _base_ref(root))
    assert report["card_findings"] == [] and report["exit_code"] == 0
    assert "всё доставлено" in guard.render(report)


# ══ 5. шаг 0b: карточка, живущая только на базе ══════════════════════════════

def test_step_0b_reads_a_card_that_exists_only_on_base(claim, tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: на момент замера #140 десять карточек жили ТОЛЬКО на origin,
    и шаг 0b отвечал о каждой «НЕ ИЗМЕРЕНО» — то есть взять их было нельзя НИКОГДА."""
    root = _repo(tmp_path, cards=[("inbox-tolko-na-origin.md", "new")])
    ref = _base_ref(root)
    tracker = root / "nimbalyst-local" / "tracker"
    (tracker / "inbox-tolko-na-origin.md").unlink()      # в дереве её нет, на базе есть
    log = tmp_path / "session_changes.jsonl"
    log.write_text("", encoding="utf-8")

    report = claim.gather("inbox-tolko-na-origin", log=log, tracker_dir=tracker,
                          self_session="pid1", self_anchor=None, base_ref=ref)

    assert report["verdict"] == claim.FREE
    assert report["unmeasured"] == []
    assert report["card_status"] == "new"
    assert report["card_source"] == f"{ref}:nimbalyst-local/tracker/inbox-tolko-na-origin.md"
    assert "в рабочем дереве её НЕТ" in claim.render(report)


def test_step_0b_still_refuses_when_the_card_exists_nowhere(claim, tmp_path):
    """Обратное плечо: fail-CLOSED не ослаблен — несуществующая карточка НЕ становится свободной."""
    root = _repo(tmp_path, cards=[("inbox-staraya.md", "new")])
    ref = _base_ref(root)
    log = tmp_path / "session_changes.jsonl"
    log.write_text("", encoding="utf-8")

    report = claim.gather("inbox-net-nigde", log=log,
                          tracker_dir=root / "nimbalyst-local" / "tracker",
                          self_session="pid1", self_anchor=None, base_ref=ref)

    assert report["verdict"] == claim.UNCHECKED
    assert report["card_source"] is None
    assert any("ни на" in u["reason"] for u in report["unmeasured"])


def test_tree_copy_wins_over_base_copy(claim, tmp_path):
    """Дерево главнее базы: захват, записанный в рабочем дереве, ещё не запушен — и именно
    он актуален. Иначе шаг 0b объявлял бы «свободна» о только что взятой карточке."""
    root = _repo(tmp_path, cards=[("inbox-spor.md", "new")])
    ref = _base_ref(root)
    tracker = root / "nimbalyst-local" / "tracker"
    (tracker / "inbox-spor.md").write_text(
        _card("new").replace("status: new", "status: new\nclaimed_by: pid777\n"
                             "claimed_at: 2026-08-06T20:00:00Z"), encoding="utf-8")
    log = tmp_path / "session_changes.jsonl"
    log.write_text("", encoding="utf-8")

    report = claim.gather("inbox-spor", log=log, tracker_dir=tracker,
                          self_session="pid1", self_anchor=None, base_ref=ref)

    assert report["card_source"] is None            # прочитана из дерева, не с базы
    assert report["verdict"] != claim.FREE          # чужой захват увиден


def test_read_card_itself_keeps_its_old_contract(claim, tmp_path):
    """`read_card` не менялся: отсутствие файла — по-прежнему причина, а не пустой словарь.
    Запасной источник живёт в отдельной функции, а не подменяет старую семантику."""
    meta, err = claim.read_card(tmp_path / "net.md")
    assert meta is None and "карточки нет" in err


def test_base_fallback_never_touches_the_network(claim, tmp_path):
    """Проверка обязана оставаться офлайновой: `fetch`/`pull`/`remote` не зовутся."""
    calls = []

    def fake_git(cwd, *args):
        calls.append(args)
        if args[:1] == ("rev-parse",):
            return 0, str(tmp_path), ""
        return 128, "", "no such path"

    claim.read_card_from_base(tmp_path / "nimbalyst-local" / "tracker" / "x.md",
                             base_ref="base_ref", git=fake_git)

    assert calls, "git не вызывался вовсе — проверка ничего не измерила"
    assert not any(a[0] in {"fetch", "pull", "remote", "clone"} for a in calls)


def test_claim_of_a_base_only_card_names_the_situation(claim, tmp_path):
    """Взятие правит ФАЙЛ, поэтому карточку с базы оно не материализует молча — но и
    «карточки нет» больше не говорит: это противоречило бы `check`, который её прочёл."""
    root = _repo(tmp_path, cards=[("inbox-tolko-na-origin.md", "new")])
    ref = _base_ref(root)
    tracker = root / "nimbalyst-local" / "tracker"
    (tracker / "inbox-tolko-na-origin.md").unlink()
    log = tmp_path / "session_changes.jsonl"
    log.write_text("", encoding="utf-8")
    _git(root, "branch", "-f", "origin_main_stub", ref)

    class _Sibling:
        _git = staticmethod(claim.load_sibling()._git)

    with pytest.raises(claim.ClaimError) as exc:
        claim.claim_card("inbox-tolko-na-origin", log=log, tracker_dir=tracker,
                         session="pid1", sibling=_Sibling, self_anchor=None)
    # На базовом ref по умолчанию (`origin/main`) карточки в герметичном репозитории нет,
    # поэтому здесь пиннится ровно одно: отказ, и отказ объяснённый.
    assert "карточки нет" in str(exc.value)


# ══ 6. create: своё дерево и громкий сигнал о чужом ══════════════════════════

def _run_create(cwd, title, tracker_dir=None):
    args = [os.environ.get("PYTHON", "python3"), str(ROOT / "scripts" / "orchestrator_queue.py"),
            "create", "--type", "inbox", "--title", title, "--body", "тело"]
    if tracker_dir:
        args += ["--tracker-dir", str(tracker_dir)]
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True)


def test_create_honours_tracker_dir(tmp_path):
    """Карточку можно создать В СВОЁМ дереве — тогда она уезжает вместе с работой."""
    tracker = tmp_path / "moyo-derevo" / "nimbalyst-local" / "tracker"
    tracker.mkdir(parents=True)
    res = _run_create(tmp_path, "зонд своего дерева", tracker)
    assert res.returncode == 0, res.stderr
    created = Path(res.stdout.strip())
    assert created.parent == tracker and created.exists()


def test_create_warns_loudly_when_the_card_lands_in_a_foreign_tree(tmp_path):
    """ГРОМКО и В МОМЕНТ дефекта: карточка легла в другое рабочее дерево, чем текущее."""
    work = _repo(tmp_path, name="rabochee", cards=[("inbox-staraya.md", "new")])
    other = _repo(tmp_path, name="chuzhoe", cards=[("inbox-staraya.md", "new")])
    res = _run_create(work, "зонд чужого дерева", other / "nimbalyst-local" / "tracker")

    assert res.returncode == 0, res.stderr
    assert "ДРУГОМ рабочем дереве" in res.stderr
    assert str(other) in res.stderr
    # stdout — машинный контракт: ТОЛЬКО путь. Предупреждение его не портит.
    assert Path(res.stdout.strip()).exists()
    assert len(res.stdout.strip().splitlines()) == 1


def test_create_in_the_same_tree_is_silent(tmp_path):
    """Обратное плечо: работая в своём дереве, предупреждения быть не должно —
    иначе оно обесценится и его перестанут читать."""
    work = _repo(tmp_path, name="rabochee", cards=[("inbox-staraya.md", "new")])
    res = _run_create(work, "зонд своего же дерева", work / "nimbalyst-local" / "tracker")
    assert res.returncode == 0, res.stderr
    assert "ДРУГОМ рабочем дереве" not in res.stderr
