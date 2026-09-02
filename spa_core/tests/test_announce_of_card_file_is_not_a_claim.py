"""Объявить ФАЙЛ карточки — не значит взять карточку (цикл #457).

Карточка `inbox-shag-0b-zapiraet-na-3-chasa-kartochki-ko`. Дефект измерен дважды за одни
сутки 02.09: цикл, который довёл работу до конца и оставил СЛЕДУЮЩЕМУ циклу карточки на
названные остатки, объявляет их файлы (он их везёт на origin) — и этим же действием запирает
их на три часа, а циклы идут раз в час.

Запись-виновник целиком (журнал объявлений, `data/session_changes.jsonl`):

    {"ts": "2026-09-02T04:22:01Z", "session": "cycle-84717",
     "files": ["…/inbox-proverka-zhivosti-pid-skipaetsya-kogda-n.md",
               "…/inbox-u-failov-claude-rules-net-ni-odnogo-stor.md"],
     "verified": "пуш d4e1c719, доска со сверкой origin 2828e2ac5"}

Поля `card:` в ней нет НИ КАКОГО — то есть это ровно та форма, которую #262 оставил нетронутой
намеренно («записи БЕЗ поля `card:` не трогаются вовсе»). Шаг 0b прочитал файл карточки во
владении как СИЛЬНЫЙ признак захвата, ярлык `cycle-84717` pid не содержит ⇒ активность не
измерима ⇒ `НЕ ИЗМЕРЕНО`, код 2, «брать нельзя» — и так на ОБЕ карточки. #456 перебил вердикт
руками, #457 получил тот же отказ на второй карточке.

Починка двусторонняя, и обе стороны проверяются здесь:

* **вперёд** — `log_session_change.py` ОТКАЗЫВАЕТ объявить файл карточки трекера без `--card`
  (единственная дверь, где объявления пишутся ⇒ форма больше не появится);
* **назад** — `check_card_claim.entry_hit` спрашивает САМУ карточку: нет `card:` в записи И нет
  `claimed_by` во frontmatter ⇒ признак СЛАБЫЙ (уже написанные 1006 записей разбираются).

Косвенный вывод из `verified` («там sha ⇒ доставлено») проверен в карточке и отвергнут: поле
свободнотекстовое, в той же популяции есть `"verified": "в работе"`.

**Обратный контроль обязателен и стоит здесь же** (`TestNarrowingIsNotDisarming`): признак
ослаблен ровно в одной форме, а подтверждённо живая сессия по-прежнему блокирует, «не
измерено» по-прежнему даёт СИЛЬНЫЙ признак, и пересечение по `--files` не тронуто.

Время подаётся явно с обеих сторон (`now` + фиксированные отметки записей): дата аварии здесь
предмет проверки, а не окружение, — `.claude/rules/deployment.md`, «Время в тестах».
"""
# FROZEN-DATE-OK: injected-clock — `now` подаётся явно в КАЖДОМ прогоне (`run(..., now=)`),
# а все отметки записей выведены из одного якоря `INCIDENT`; календарь на вердикт не влияет.
# Сама дата при этом ещё и является предметом: воспроизводится авария 2026-09-02T04:22:01Z.
import importlib.util
import json
from datetime import datetime, timedelta, timezone

import pytest

from spa_core.tests.test_card_claim_guard import (  # noqa: F401  (фикстуры регистрируются импортом)
    MY_ANCHOR,
    ROOT,
    guard,
    log,
    ps_alive,
    ps_dead,
    sibling,
    tracker,
    write_card,
    write_log,
)

#: Момент аварии — дословно из журнала. Дата ЯВЛЯЕТСЯ предметом (воспроизводим именно эту
#: запись), и обе стороны закреплены: отметки записей ниже и `now` в каждом прогоне.
INCIDENT_TS = "2026-09-02T04:22:01Z"
INCIDENT = datetime(2026, 9, 2, 4, 22, 1, tzinfo=timezone.utc)
#: Час спустя — следующий цикл (циклы идут раз в час, окно свежести 3ч ⇒ запись ещё «свежая»).
NEXT_CYCLE = INCIDENT + timedelta(hours=1)

#: Обе карточки, которые заперла запись, — поимённо.
LEFT = "inbox-proverka-zhivosti-pid-skipaetsya-kogda-n"
RIGHT = "inbox-u-failov-claude-rules-net-ni-odnogo-stor"


def _load(name, rel):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def writer():
    return _load("_test_announce_writer", "scripts/log_session_change.py")


@pytest.fixture()
def repo_tracker(tmp_path):
    """Каталог карточек в РЕАЛЬНОМ написании — `…/nimbalyst-local/tracker/`.

    Отдельно от общей фикстуры `tracker` (просто `tmp_path/tracker`) намеренно: писатель
    опознаёт карточку по написанию пути, и проверять его на пути, которого в проекте не
    бывает, значило бы проверять не то. Читателю (`entry_hit`) достаточно имени файла,
    поэтому там общая фикстура остаётся верной."""
    d = tmp_path / "nimbalyst-local" / "tracker"
    d.mkdir(parents=True)
    return d


def _fmt(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def delivery_entry(tracker_dir, *, session="cycle-84717", ts=INCIDENT_TS, card=None):
    """Объявление ДОСТАВКИ двух карточек — форма записи `cycle-84717` побайтово по схеме."""
    entry = {"ts": ts, "session": session,
             "summary": "цикл довёл работу, карточки на остатки уезжают на origin",
             "files": [str(tracker_dir / f"{LEFT}.md"), str(tracker_dir / f"{RIGHT}.md")],
             "verified": "пуш d4e1c719, доска со сверкой origin 2828e2ac5"}
    if card:
        entry["card"] = card
        entry["card_state"] = "done"
    return entry


def run(guard, tracker, log, card, *, session="cycle-457", ps=None, now=NEXT_CYCLE,
        sibling=None, planned_files=()):
    return guard.gather(card, log=log, tracker_dir=tracker, sibling=sibling,
                        self_session=session, now=now, grace_hours=3.0,
                        planned_files=planned_files, ps=ps, self_anchor=None)


# ── положительный контроль: та самая авария, поимённо ────────────────────────

class TestIncident84717:
    """Воспроизведение записи `cycle-84717` от 2026-09-02T04:22:01Z."""

    @pytest.mark.parametrize("cid", [LEFT, RIGHT])
    def test_delivery_announce_leaves_the_card_free(self, guard, sibling, tracker, log,
                                                    ps_dead, cid):
        write_card(tracker, LEFT, status="new")
        write_card(tracker, RIGHT, status="new")
        write_log(log, [delivery_entry(tracker)])

        r = run(guard, tracker, log, cid, ps=ps_dead, sibling=sibling)

        assert r["verdict"] == guard.FREE, r
        assert guard.exit_code(r) == 0
        assert r["unmeasured"] == [], "«НЕ ИЗМЕРЕНО» и есть тот отказ, из-за которого встала очередь"
        assert r["claims"] == []
        # Признак не исчезает из отчёта — он становится слабым и уезжает в историю.
        assert any(h["strength"] == guard.WEAK for h in r["history"]), r["history"]

    def test_the_defect_is_real_without_the_fix(self, guard, sibling, tracker, log, ps_dead):
        """Прямой замер прежнего поведения: без ответа карточки признак СИЛЬНЫЙ.

        Мутация по координате — единственный вход, который починка добавила
        (`card_claimed`). `None` = «карточку прочитать не удалось» ⇒ прежний СИЛЬНЫЙ признак;
        он же и есть то, что заперло очередь. Тест краснеет, если ветку убрать.
        """
        entry = delivery_entry(tracker)
        assert guard.entry_hit(entry, LEFT, card_claimed=None)[0] == guard.STRONG
        assert guard.entry_hit(entry, LEFT, card_claimed=False)[0] == guard.WEAK

    def test_unreadable_card_keeps_the_old_strong_signal(self, guard, sibling, tracker, log,
                                                         ps_dead):
        """Карточки на диске НЕТ ⇒ занятость не измерена ⇒ код 2 (fail-CLOSED сохранён)."""
        write_log(log, [delivery_entry(tracker)])
        r = run(guard, tracker, log, LEFT, ps=ps_dead, sibling=sibling)
        assert guard.exit_code(r) == 2
        assert r["unmeasured"], "нечитаемая карточка обязана давать «НЕ ИЗМЕРЕНО», а не «свободна»"


# ── обратный контроль: это сужение признака, а не снятие сторожа ─────────────

class TestNarrowingIsNotDisarming:
    def test_live_session_still_blocks(self, guard, sibling, tracker, log, ps_alive):
        """Запись БЕЗ `verified` и без `card_state: done` от ЖИВОЙ сессии — по-прежнему ЗАНЯТА.

        Слабый признак у подтверждённо живой сессии блокирует (та же политика, что у
        упоминания в тексте): сосед, правящий файл моей карточки прямо сейчас, — настоящий
        конфликт, а не фантом.
        """
        write_card(tracker, LEFT, status="new")
        write_log(log, [{"ts": INCIDENT_TS, "session": "pid777", "summary": "работа идёт",
                         "files": [str(tracker / f"{LEFT}.md")], "verified": ""}])

        r = run(guard, tracker, log, LEFT, ps=ps_alive, sibling=sibling)

        assert r["verdict"] == guard.CLAIMED, r
        assert guard.exit_code(r) == 1
        assert r["claims"][0]["session"] == "pid777"

    def test_frontmatter_claim_still_blocks(self, guard, sibling, tracker, log, ps_dead):
        """Настоящий захват пишет `claimed_by` — он и блокирует, независимо от журнала."""
        write_card(tracker, LEFT, status="new", claimed_by="cycle-84717",
                   claimed_at=_fmt(INCIDENT))
        write_log(log, [delivery_entry(tracker)])

        r = run(guard, tracker, log, LEFT, ps=ps_dead, sibling=sibling)

        assert r["verdict"] == guard.CLAIMED, r
        assert guard.exit_code(r) == 1

    def test_claimed_card_keeps_the_file_signal_strong(self, guard, tracker):
        """`card_claimed=True` ⇒ признак остаётся СИЛЬНЫМ (граница проведена узко)."""
        entry = delivery_entry(tracker)
        assert guard.entry_hit(entry, LEFT, card_claimed=True)[0] == guard.STRONG

    def test_file_overlap_is_an_independent_measurement(self, guard, sibling, tracker, log,
                                                        ps_dead):
        """Пересечение по `--files` не тронуто: тот же журнал, но я собираюсь править ТЕ ЖЕ файлы."""
        write_card(tracker, LEFT, status="new")
        write_log(log, [delivery_entry(tracker)])

        r = run(guard, tracker, log, LEFT, ps=ps_dead, sibling=sibling,
                planned_files=[str(tracker / f"{RIGHT}.md")])

        assert r["overlaps"], "конфликт по объявленным файлам обязан остаться видимым"
        assert guard.exit_code(r) != 0

    def test_explicit_card_field_still_strong(self, guard, tracker):
        """Запись С полем `card:` на ЭТУ карточку — прежний СИЛЬНЫЙ признак."""
        entry = delivery_entry(tracker, card=LEFT)
        assert guard.entry_hit(entry, LEFT, card_claimed=False)[0] == guard.STRONG


# ── вперёд: единственная дверь отказывает объявить карточку без `--card` ─────

class TestWriterRefusesCardFileWithoutCard:
    def _files(self, repo_tracker):
        return [str(repo_tracker / f"{LEFT}.md")]

    def test_refuses_and_writes_nothing(self, writer, repo_tracker, log):
        with pytest.raises(writer.CardFileWithoutCard) as exc:
            writer.record("довёз карточку", self._files(repo_tracker), "пуш abc123", log=log)
        assert LEFT in str(exc.value)
        assert log.read_text(encoding="utf-8") == "", "отказ обязан случиться ДО записи"

    def test_cli_exit_code_is_two(self, writer, repo_tracker, log, capsys, monkeypatch):
        """Через CLI — код 2 и внятная причина.

        `_LOG` подменяется НЕ для красоты: у `main` нет `--log`, умолчание разрешается в
        настоящий `data/session_changes.jsonl` того дерева, откуда запущен pytest, — и
        «отказ случается раньше записи» тут обещание проверяемого кода, а не свойство теста.
        Измерено на мутанте (проводка отказа снята): без подмены этот тест дописывает в
        ЖИВОЙ журнал выдуманное объявление. Тест, чья герметичность держится на исправности
        проверяемого им же кода, герметичным не является (класс «тесты пишут в живое
        состояние»)."""
        monkeypatch.setattr(writer, "_LOG", log)
        rc = writer.main(["--summary", "довёз карточку", "--files",
                          *self._files(repo_tracker)])
        assert rc == 2
        assert "--card не назван" in capsys.readouterr().err
        assert log.read_text(encoding="utf-8") == "", "отказ обязан случиться ДО записи"

    def test_named_card_passes(self, writer, repo_tracker, log):
        e = writer.record("довёз карточку", self._files(repo_tracker), "пуш abc123",
                          card=LEFT, card_state="done", log=log)
        assert e["card"] == LEFT and e["card_state"] == "done"
        assert log.read_text(encoding="utf-8").strip()

    def test_naming_one_card_unlocks_the_others(self, guard, sibling, tracker, log, ps_dead):
        """Правило #262 доделывает работу: названа одна — остальные читаются слабым признаком."""
        write_card(tracker, LEFT, status="new")
        write_card(tracker, RIGHT, status="new")
        write_log(log, [delivery_entry(tracker, card=RIGHT)])

        r = run(guard, tracker, log, LEFT, ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.FREE and guard.exit_code(r) == 0

    def test_board_index_is_not_a_card(self, writer, repo_tracker, log):
        """`_BOARD.md` — авто-индекс доски, а не карточка: объявлять его без `--card` законно."""
        board = repo_tracker / "_BOARD.md"
        e = writer.record("перестроил доску", [str(board)], "regen", log=log)
        assert e["files"] == [str(board)]

    def test_ordinary_files_are_untouched(self, writer, log):
        e = writer.record("правка правил", ["/repo/docs/STATE.md", "/repo/spa_core/x.py"],
                          "pytest", log=log)
        assert e["summary"] == "правка правил"

    def test_relative_path_is_recognised_too(self, writer, log):
        with pytest.raises(writer.CardFileWithoutCard):
            writer.record("довёз", [f"nimbalyst-local/tracker/{LEFT}.md"], "", log=log)

    def test_detector_population(self, writer):
        """Что считается файлом карточки — перечислено, а не угадывается читателем."""
        assert writer.tracker_cards_in([f"/r/nimbalyst-local/tracker/{LEFT}.md"])
        assert writer.tracker_cards_in([f"nimbalyst-local/tracker/{LEFT}.md"])
        assert not writer.tracker_cards_in(["/r/nimbalyst-local/tracker/_BOARD.md"])
        assert not writer.tracker_cards_in(["/r/nimbalyst-local/tracker/sub/x.md"])
        assert not writer.tracker_cards_in(["/r/docs/decisions/INDEX.md"])
        assert not writer.tracker_cards_in([f"/r/nimbalyst-local/tracker/{LEFT}.json"])


class TestClaimDoorStillWorks:
    """`check_card_claim.claim` ходит через ту же дверь и всегда несёт `card=` — отказ его не задевает."""

    def test_claim_card_still_announces(self, guard, sibling, tracker, log, ps_dead):
        write_card(tracker, LEFT, status="new")
        res = guard.claim_card(LEFT, log=log, tracker_dir=tracker, sibling=sibling,
                               session="cycle-457", now=NEXT_CYCLE, ps=ps_dead,
                               self_anchor=MY_ANCHOR)
        assert res["claimed_by"] == "cycle-457"
        rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
        assert rows and rows[-1]["card"] == LEFT and rows[-1]["card_state"] == "claim"
