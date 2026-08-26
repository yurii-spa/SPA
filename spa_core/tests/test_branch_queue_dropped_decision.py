"""«Прочитано и осознанно НЕ везём» — третий исход `branch_queue`.

КАЖДЫЙ тест — положительный контроль реальной аварии, тянувшейся с **23.08.2026**
(карточка `inbox-storozh-voprosy-vladeltsa-na-vetke-ne-zn`, замер цикла #356):

    цикл #355 в тот же день ЗАКОНЧИЛ разбор ветки `origin/claude/work-status-check-xfnbew`
    и отчитался «18 оставшихся вопросов владельца: 8 перенесено / 7 повтор / 3 устарело»,
    а сторож `owner_decision_pending.branch_queue` продолжал предъявлять **12** карточек
    как «вопросы владельцу, которые ни задать, ни закрыть». К 25.08 их оставалось **3**,
    и все три названы поимённо в теле карточки-разбора: два решены шире (ADR-125 / ADR-116),
    один — дубль `own-red-team-nablyudennaya-ugroza-ne-doezzhaet`.

Противоречия не было — была слепота. У сторожа существовало ровно ДВА имени: «потеряно»
и «убрано с базы» (`ever_on_base`). Карточка, которую сессия ПРОЧИТАЛА на ветке и осознанно
решила не везти, на базе не лежала НИКОГДА ⇒ `ever_on_base = False` ⇒ она в счёте навсегда.
Число не могло дойти до нуля даже после полной работы, и следующая сессия читала его как
приглашение переделать разбор — тот самый механизм, которым глохнут сторожа.

**Обратный контроль здесь важнее прямого.** «Решено не везти» без автора закрывает что
угодно, поэтому объявление без автора, даты или основания объявлением НЕ считается, карточка
остаётся потерей, а бракованная строка называется вслух. Проверяется и это.

Фикстуры — настоящие крошечные git-репозитории без сети (`git update-ref refs/remotes/...`):
проверяется ЭФФЕКТ на git, а не подменённая заглушка. Литеральных дат в фикстурах нет там,
где вердикт от календаря зависит; дата ВНУТРИ объявления — предмет проверки, а не окружение.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

from spa_core.monitoring import owner_decision_pending as odp
from spa_core.owner_queue import origin_view
from spa_core.owner_queue.origin_view import (DROPPED_MARKER, branch_only_cards,
                                              dropped_registry,
                                              parse_dropped_declarations)

ROOT = Path(__file__).resolve().parents[2]
BRANCH = "claude/work-status-check-xfnbew"

#: Три настоящих имени с той ветки — чтобы фикстура называла аварию, а не абстракцию.
TRIAGED = ("owner-decision-razvedka-krichit-critical-na-nashu-zhe-o",
           "owner-decision-storozh-saita-krasneet-kazhduyu-noch-na",
           "owner-decision-sbalansirovannyi-paket-ne-pokupaet-niche")


def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


def _card(title="карточка", status="needs-owner", ctype="owner-decision", body="тело"):
    return (f"---\ntrackerStatus:\n  type: {ctype}\ntitle: \"{title}\"\n"
            f"status: {status}\n---\n\n{body}\n")


def _decl(card, *, by="цикл #372 (пачка 3)", date="2026-08-24",
          reason="дубль уже разобранного, замер приложен к карточке на main",
          branch=f"origin/{BRANCH}", omit=()):
    """Строка объявления. `omit` выкидывает поле — так строится обратный контроль."""
    parts = [("card", card), ("branch", branch), ("by", by), ("date", date)]
    head = "; ".join(f"{k}={v}" for k, v in parts if k not in omit)
    tail = "" if "reason" in omit else f"; reason={reason}"
    return f"{DROPPED_MARKER} {head}{tail}"


def _triage_card(*decls, body_note="Разбор ветки закончен."):
    return _card(title="Разобрать 52 карточки с ветки", status="new", ctype="inbox",
                 body=body_note + "\n\n" + "\n\n".join(decls) + "\n")


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / origin_view.TRACKER_REL).mkdir(parents=True)
    _run(root.parent, "init", "-q", "-b", "main", str(root))
    _run(root, "config", "user.email", "t@example.com")
    _run(root, "config", "user.name", "test")
    return root


def _tracker(root: Path) -> Path:
    return root / origin_view.TRACKER_REL


def _write(root: Path, name: str, text: str) -> Path:
    p = _tracker(root) / f"{name}.md"
    p.write_text(text, encoding="utf-8")
    return p


def _commit(root: Path, msg="c"):
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "--allow-empty", "-m", msg)


def _publish(root: Path, remote_branch: str, local: str = "HEAD"):
    _run(root, "update-ref", f"refs/remotes/{remote_branch}", _run(root, "rev-parse", local).strip())


def _base_with(root: Path, **cards: str) -> None:
    for name, text in cards.items():
        _write(root, name, text)
    _commit(root, "base")
    _publish(root, "origin/main")
    for name in cards:
        (_tracker(root) / f"{name}.md").unlink()
    _tracker(root).mkdir(parents=True, exist_ok=True)


def _branch_with(root: Path, branch: str, **cards: str) -> None:
    for name, text in cards.items():
        _write(root, name, text)
    _commit(root, f"branch {branch}")
    _publish(root, f"origin/{branch}")
    _run(root, "reset", "-q", "--hard", "HEAD~1")
    for name in cards:
        path = _tracker(root) / f"{name}.md"
        if path.exists():
            path.unlink()
    _tracker(root).mkdir(parents=True, exist_ok=True)


def _the_accident(root, *, declared=TRIAGED, extra_branch_cards=()):
    """Ровно 25.08: ветка разобрана, база несёт карточку-разбор с объявлениями.

    Дерево остаётся ПУСТЫМ намеренно: это состояние CI-чекаута и прод-дерева, куда
    `nimbalyst-local/` не возит никто (урок #193). Читатель обязан находить объявление
    на базе; вариант «объявление лежит в дереве» проверяется отдельным тестом.
    `_branch_with` возвращает дерево к базовому коммиту, поэтому чистим после него.
    """
    _base_with(root, **{"inbox-razobrat-52-kartochki-s-vetki-work-statu":
                        _triage_card(*[_decl(c) for c in declared])})
    on_branch = {c: _card(title=c) for c in (*TRIAGED, *extra_branch_cards)}
    _branch_with(root, BRANCH, **on_branch)
    for path in _tracker(root).glob("*.md"):
        path.unlink()


def _scan(root):
    return odp._scan_branch_queue(_tracker(root))


# ── прямой контроль: разобранная ветка обязана уйти в ноль ────────────────────

def test_triaged_branch_reaches_zero(repo):
    """Авария 23.08 в её итоговом виде: три разобранные карточки — НЕ находка."""
    _the_accident(repo)
    got = _scan(repo)
    assert got["measured"] is True
    assert got["count"] == 0, f"разобранная ветка обязана уйти в 0, получено: {got['cards']}"
    assert got["dropped_count"] == 3
    assert {d["card_id"] for d in got["dropped"]} == set(TRIAGED)


def test_dropped_row_carries_author_reason_and_date(repo):
    """Решение без автора и основания закрывает что угодно — оба обязаны доехать в отчёт."""
    _the_accident(repo)
    row = _scan(repo)["dropped"][0]
    assert row["by"] == "цикл #372 (пачка 3)"
    assert row["date"] == "2026-08-24"
    assert "дубль" in row["reason"]
    assert row["declared_in"] == "inbox-razobrat-52-kartochki-s-vetki-work-statu"
    assert row["branches"] == [f"origin/{BRANCH}"]


def test_dropped_card_is_not_counted_as_removed_from_base(repo):
    """Три исхода обязаны остаться ТРЕМЯ: «не везём» ≠ «убрано с базы»."""
    _the_accident(repo)
    got = _scan(repo)
    assert got["dropped_count"] == 3
    assert got["removed_on_base_count"] == 0


# ── обратный контроль: без записанного решения карточка ОСТАЁТСЯ потерей ──────

def test_undeclared_card_is_still_lost(repo):
    """Главный обратный контроль: молчание — не решение."""
    _the_accident(repo, extra_branch_cards=("own-poteryannyi-vopros-vladeltsa",))
    got = _scan(repo)
    assert got["count"] == 1
    assert [c["card_id"] for c in got["cards"]] == ["own-poteryannyi-vopros-vladeltsa"]
    assert got["dropped_count"] == 3


@pytest.mark.parametrize("field", ["by", "date", "reason"])
def test_declaration_without_a_required_field_is_not_a_declaration(repo, field):
    """Автор · дата · основание — не украшение: без любого из них решения нет."""
    _the_accident(repo, declared=())
    _write(repo, "inbox-razobrat-52-kartochki-s-vetki-work-statu",
           _triage_card(_decl(TRIAGED[0], omit=(field,))))
    got = _scan(repo)
    assert TRIAGED[0] in {c["card_id"] for c in got["cards"]}, "карточка обязана остаться потерей"
    assert got["dropped_count"] == 0
    issues = " ".join(i["reason"] for i in got["declaration_issues"])
    assert field in issues, f"брак обязан быть НАЗВАН, получено: {got['declaration_issues']}"


def test_declaration_with_a_free_form_date_is_refused(repo):
    """«Когда решили» либо есть, либо его нет: свободная форма даты — это её отсутствие."""
    _the_accident(repo, declared=())
    _write(repo, "inbox-razobrat-52-kartochki-s-vetki-work-statu",
           _triage_card(_decl(TRIAGED[0], date="на прошлой неделе")))
    got = _scan(repo)
    assert got["dropped_count"] == 0
    assert TRIAGED[0] in {c["card_id"] for c in got["cards"]}
    assert any("YYYY-MM-DD" in i["reason"] for i in got["declaration_issues"])


def test_broken_declaration_is_never_dropped_silently(repo):
    """Строка с меткой, которую сторож не принял, обязана быть слышна.

    Иначе автор считает, что решение записано, сторож — что его нет, и обе стороны
    уверены, что всё в порядке. Ровно этот класс мы уже ловили у `--dropped` шага 0a.
    """
    _the_accident(repo, declared=())
    _write(repo, "inbox-razobrat-52-kartochki-s-vetki-work-statu",
           _triage_card(_decl(TRIAGED[0], omit=("by", "reason"))))
    got = _scan(repo)
    assert len(got["declaration_issues"]) == 1
    where = got["declaration_issues"][0]["where"]
    assert where.startswith("inbox-razobrat-52-kartochki-s-vetki-work-statu:"), where


# ── реестр обязан читаться ОБОИМИ источниками ────────────────────────────────

def test_declaration_living_only_in_the_live_tree_counts(repo):
    """`nimbalyst-local/` не возит ни автосинк, ни CI-чекаут (урок #193).

    Объявление, сделанное циклом и ещё не доехавшее на origin, обязано работать —
    иначе прод-сторож сутки предъявляет как потерю то, что уже разобрано.
    """
    _base_with(repo)  # база БЕЗ карточки-разбора
    _branch_with(repo, BRANCH, **{c: _card(title=c) for c in TRIAGED})
    _write(repo, "inbox-razobrat-52-kartochki-s-vetki-work-statu",
           _triage_card(*[_decl(c) for c in TRIAGED]))
    got = _scan(repo)
    assert got["count"] == 0
    assert got["dropped_count"] == 3


def test_declaration_on_base_counts_without_the_tree(repo):
    """Зеркало: дерево пустое (типичный CI-чекаут), объявление лежит на `origin/main`."""
    _the_accident(repo)
    assert not list(_tracker(repo).glob("*.md")), "фикстура: дерево обязано быть пустым"
    assert _scan(repo)["count"] == 0


# ── гигиена самого реестра ───────────────────────────────────────────────────

def test_stale_declaration_is_named_and_changes_no_verdict(repo):
    """Реестр, из которого ничего не уходит, через год состоит из мусора."""
    _the_accident(repo, declared=(*TRIAGED, "own-etoi-kartochki-net-ni-na-odnoi-vetke"))
    got = _scan(repo)
    assert got["count"] == 0
    assert got["dropped_count"] == 3
    assert any("own-etoi-kartochki-net-ni-na-odnoi-vetke" == i["where"]
               for i in got["declaration_issues"])


def test_conflicting_declarations_are_named(repo):
    """Два разных основания об одном решении — расхождение; выбирать за читателя нельзя."""
    _the_accident(repo, declared=())
    _write(repo, "inbox-razobrat-52-kartochki-s-vetki-work-statu",
           _triage_card(_decl(TRIAGED[0], reason="дубль"),
                        _decl(TRIAGED[0], reason="устарело", by="цикл #99")))
    got = _scan(repo)
    assert got["dropped_count"] == 1, "исход не меняется: обе стороны говорят «не везём»"
    assert any(i["where"] == TRIAGED[0] and "дважды" in i["reason"]
               for i in got["declaration_issues"])


def test_unreadable_branch_suppresses_the_stale_verdict(repo):
    """Fail-CLOSED: нечитаемая ветка не имеет права превращать живое объявление в мусор."""
    _the_accident(repo)
    # Ref, указывающий на BLOB вместо коммита: объект существует (значит ветка попадёт
    # в `for-each-ref` — сломанный ref git молча пропустил бы, и тест проверял бы
    # фикстуру), а `ls-tree` по нему честно возвращает ненулевой код.
    blob = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
                          input="не коммит", capture_output=True, text=True).stdout.strip()
    (repo / ".git" / "refs" / "remotes" / "origin" / "oborvannaya").write_text(
        blob + "\n", encoding="utf-8")
    scan = branch_only_cards(_tracker(repo), tracker_type="owner-decision", status="needs-owner")
    assert scan.unreadable, "фикстура: ветка обязана быть нечитаемой"
    assert scan.dropped_stale == ()


# ── разбор строки: тупой, построчный, без наследуемого состояния ─────────────

def test_reason_keeps_separators_it_contains():
    """Основание — свободный текст; резать его по `;`/`=` значило бы терять смысл."""
    rows, bad = parse_dropped_declarations(
        _decl("own-x", reason="решено шире: ADR-116; поле=real_track_days"), "карточка")
    assert not bad
    assert rows[0].reason == "решено шире: ADR-116; поле=real_track_days"


@pytest.mark.parametrize("prefix", ["", "  ", "- ", "* ", "> ", ">  - "])
def test_declaration_survives_markdown_list_and_quote_prefixes(prefix):
    """Объявление живёт в markdown: отступ, маркер списка и цитата решения не отменяют."""
    rows, bad = parse_dropped_declarations(f"{prefix}{_decl('own-x')}", "карточка")
    assert [r.card_id for r in rows] == ["own-x"] and not bad


def test_prose_about_the_mechanism_is_not_a_declaration():
    """Положительный контроль аварии цикла #376, пойманной своим же шагом 0-офис ДО пуша.

    Карточка, ОПИСЫВАЮЩАЯ этот механизм, лежит в том каталоге, который механизм читает.
    Её строка «объявление живёт в теле карточки-разбора, строкой `DROPPED-FROM-BRANCH:`»
    немедленно приехала в отчёт как бракованное объявление — сторож начал кормиться
    собственным описанием (тот же класс, что докстринг про `notify_channel`). Объявление
    — это СТРОКА, начинающаяся с метки; упоминание метки внутри фразы — рассказ.
    """
    prose = ("| «хранить там, где решение принимается» | объявление живёт в теле "
             "карточки-разбора, строкой `" + DROPPED_MARKER + "` — видимой в markdown |")
    rows, bad = parse_dropped_declarations(prose, "карточка")
    assert rows == [] and bad == [], "проза про механизм не имеет права стать объявлением"


def test_prose_without_the_marker_is_not_a_declaration_either():
    """Признак, который можно поставить словами «мы это не везём», закрыл бы что угодно."""
    rows, bad = parse_dropped_declarations(
        "Эту карточку мы прочитали и осознанно не везём — дубль.", "карточка")
    assert rows == [] and bad == []


TRIAGE_CARD = "inbox-razobrat-52-kartochki-s-vetki-work-statu"


def _real_cards():
    """Карточки ЭТОГО дерева. Каталога нет ⇒ `skip`: `nimbalyst-local/` не возит ни
    автосинк, ни CI-чекаут (урок #193), и «файла нет» здесь — свойство дерева, а не
    системы. Судить о системе по нему значит красить прод по построению."""
    tracker = ROOT / origin_view.TRACKER_REL
    if not tracker.is_dir():
        pytest.skip("каталога очереди нет в этом дереве")
    return sorted(tracker.glob("*.md"))


def test_no_real_card_produces_a_broken_declaration():
    """Положительный контроль аварии #376 на НАСТОЯЩИХ файлах, а не на фикстуре.

    Именно эта проверка ловит «сторож кормится собственным описанием»: любая карточка,
    рассказывающая о механизме, немедленно даст бракованную строку, если граница
    «код против прозы» ослабнет.
    """
    broken = []
    for card in _real_cards():
        broken.extend(parse_dropped_declarations(card.read_text(encoding="utf-8"), card.stem)[1])
    assert broken == [], f"бракованные строки в реальных карточках: {broken}"


def test_the_triage_card_declares_the_three_branch_cards():
    """Приёмка карточки: три вердикта пачки 3 записаны машиночитаемо и с провенансом."""
    cards = {c.stem: c for c in _real_cards()}
    if TRIAGE_CARD not in cards:
        pytest.skip(f"карточки {TRIAGE_CARD} нет в этом дереве (урок #193)")
    rows, bad = parse_dropped_declarations(
        cards[TRIAGE_CARD].read_text(encoding="utf-8"), TRIAGE_CARD)
    assert bad == []
    assert {r.card_id for r in rows} == set(TRIAGED), sorted(r.card_id for r in rows)
    assert all(r.by and r.date and r.reason for r in rows)


def test_registry_is_readable_and_empty_on_a_clean_repo(repo):
    """Пустой реестр — законный ответ, и он ОТЛИЧИМ от «посмотреть не смогли»."""
    _base_with(repo)
    reg = dropped_registry(_tracker(repo))
    assert reg.by_card == {} and reg.broken == () and reg.conflicts == ()


# ── шаг 0-офис: решение обязано быть ВИДНО, брак — тоже ──────────────────────

def _office():
    path = ROOT / "scripts" / "consume_office_reports.py"
    spec = importlib.util.spec_from_file_location("_test_office_dropped", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _office_lines(branch_queue):
    return _office()._summarize_json("owner_decision_pending.json", {
        "status": "OK", "origin_queue": {"measured": True, "count": 0,
                                         "ref": "origin/main", "ref_sha": "abc123456"},
        "branch_queue": branch_queue})


def test_office_prints_the_decision_with_its_author_and_reason():
    """Основание, которого не видно, читателю проверить нечем."""
    lines = _office_lines({"measured": True, "branches_read": 36, "count": 0,
                           "dropped_count": 1, "cards": [],
                           "dropped": [{"card_id": "owner-decision-x", "branches": [],
                                        "by": "цикл #372", "date": "2026-08-24",
                                        "reason": "решено шире ADR-116"}]})
    row = [ln for ln in lines if "осознанно НЕ везём" in ln]
    assert row, lines
    assert "цикл #372" in row[0] and "2026-08-24" in row[0] and "ADR-116" in row[0]


def test_office_prints_registry_breakage_as_a_finding():
    lines = _office_lines({"measured": True, "branches_read": 36, "count": 0,
                           "dropped_count": 0, "cards": [], "dropped": [],
                           "declaration_issues": [{"where": "карточка:12",
                                                   "reason": "объявление без поля by"}]})
    row = [ln for ln in lines if "реестр «не везём» с браком" in ln]
    assert row and "карточка:12" in row[0], lines


def test_office_stays_silent_when_nothing_was_dropped():
    """Пустая строка каждый цикл приучает пролистывать — того же класса дефект."""
    lines = _office_lines({"measured": True, "branches_read": 36, "count": 0,
                           "dropped_count": 0, "cards": [], "dropped": [],
                           "declaration_issues": []})
    assert not [ln for ln in lines if "осознанно НЕ везём" in ln]
    assert not [ln for ln in lines if "реестр «не везём»" in ln]
