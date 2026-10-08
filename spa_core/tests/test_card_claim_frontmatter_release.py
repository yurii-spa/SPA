"""Шаг 0b: `card_state: done` снимало ДВЕ записи держателя из трёх.

**Авария, которую воспроизводит этот файл** (замерена циклом #808 на ПРИКАЗЕ ВЛАДЕЛЬЦА,
2026-10-08). Один и тот же приговор сессии о себе самой — объявление
``--card-state done`` — читался двумя ветками `check_card_claim.py` и не читался третьей:

| запись держателя | снималась по `done`? |
|---|---|
| журнальный захват (`card:` / файл карточки во владении) | да, ветка `is_release` |
| пересечение по объявленным файлам (`--files`) | да, через `releases_by_session` |
| **`claimed_by` во frontmatter карточки** | **НЕТ — спрашивался только статус карточки** |

Живой замер. `cycle-806` взял `inbox-task-portfolio-cio-dynamic-capital-alloc` (приказ
владельца от 22.08, `priority: critical`) во frontmatter в 15:17:57Z, отработал свой цикл
и ДВАЖДЫ объявил `card_state: done` по ЭТОЙ карточке — 16:18:41Z и 16:22:00Z. Журнальный
захват сняло обоими объявлениями; frontmatter-захват остался стоять. Ярлык `cycle-806` pid
не содержит, а личность процесса в журнале объявлена — поэтому старение безымянного
захвата (ADR-647) к нему НЕ применяется, и ветка `UNKNOWN`+`STRONG` честно отдала
`unmeasured`. `unmeasured` перебивает вердикт в `unchecked`, а подъём (`--takeover`)
разрешён ТОЛЬКО на `stale`.

С 18:17:58Z (последний голос + окно 3.0 ч) приказ владельца стал **неберущимся
инструментом навсегда**: `release` чужой захват не трогает, флага для `unchecked` нет и не
будет, а время не поможет — «не измерено» не стареет по построению. Шаг 0a-голод называл
этот приказ первым и требовал взять его ДО всего остального; цикл #808 выполнил требование,
получил `ОТКАЗ: вердикт unchecked` и пришёл сюда. Замерено на живой карточке: до правки
`check` печатал «❓ НЕ ИЗМЕРЕНО» (код 2), после — «🟡 СТАРЫЙ ЗАХВАТ» (код 1) и
`unmeasured` пуст.

**Направление ошибки не меняется, и нового доверия правка не выдаёт.** `stale` — это не
«свободна»: нужен явный `--takeover` с непустой письменной причиной, и причина уезжает в
журнал и во frontmatter. Та же запись того же вида уже снимает две другие записи той же
сессии; третья начинает читать то, что две читают с самого начала.

Границы измерены тестами В ОБЕ СТОРОНЫ, и каждая из них ловит свой мутант:
* `done` по ДРУГОЙ карточке захват НЕ снимает (card-blind `releases_by_session` здесь был
  бы ровно тем дефектом, который он лечит у соседа);
* `done` РАНЬШЕ захвата захват НЕ снимает (закрыл одну карточку в 10:00 — взял снова в 10:05);
* держатель без `done` ведёт себя как прежде: личность объявлена ⇒ `unmeasured`, личность
  не объявлена нигде ⇒ `stale` (ADR-647 не ослаблен).

Время — ВХОД, а не окружение (`.claude/rules/deployment.md`, преференция №1): `now`
подаётся в `gather`, все отметки выводятся из него же. Литеральных дат в файле нет.
Личность процесса — тоже вход: `ps` подменён, живость объявляется сценой явно.
"""
import importlib.util
import json
from datetime import timedelta, timezone
from pathlib import Path

import pytest

from spa_core.tests._freshness import now_utc

ROOT = Path(__file__).resolve().parents[2]

#: Держатель приказа владельца 08.10 и ОБА его номера процесса. Ярлык `cycle-806`
#: ПЕРЕИСПОЛЬЗОВАН: 05.08 под ним работал pid806, 08.10 — pid86631. Два противоречащих
#: якоря под одним ярлыком и есть причина, по которой `_anchor_for` его личность не
#: заимствует, активность остаётся неизмеренной, а старение ADR-647 не применяется
#: (личность в журнале ОБЪЯВЛЕНА). Сцена воспроизводит это дословно — без второго якоря
#: тест мерил бы совсем другую ветку (`stale` по измеренной смерти, ADR-146).
HOLDER = "cycle-806"
PID_OLD, PID_NEW = 806, 86631
CARD = "inbox-task-portfolio-cio-dynamic-capital-alloc"
OTHER_CARD = "inbox-prover-pryam-seichas-vse-li-ok"
#: Якорь — РЕАЛЬНЫЕ часы: в предмете есть понятие свежести (`grace_hours`), и литеральная
#: дата падала бы от сдвига календаря. Часы при этом ИНЪЕКТИРОВАНЫ — `gather(now=NOW)`, и
#: все отметки сцены выведены из NOW, поэтому обе стороны сравнения закреплены.
NOW = now_utc()
#: Якорь личности ЭТОЙ сессии подаётся явно: умолчание `claim_card` читает
#: `SPA_SESSION_PID` окружения ПРОГОНА, и без явного якоря `UnmeasurableClaim` случился бы
#: на шаг раньше предмета проверки (урок цикла #388, `test_card_claim_takeover`).
SELF_ANCHOR = (41721, "Sat Aug  1 13:37:28 2026")
#: `ps` отвечает «процесса нет». Живость — ВХОД сцены, а не вопрос к настоящей ОС:
#: литеральный pid, чью живость спрашивают у живой машины, есть бомба от другого
#: счётчика (`.claude/rules/deployment.md`, раздел про личность процесса).
DEAD = lambda pid: (1, "")                                          # noqa: E731


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load("_test_card_claim_release", "scripts/check_card_claim.py")


@pytest.fixture(scope="module")
def sibling(guard):
    return guard.load_sibling()


def _fmt(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lstart(dt):
    """`ps -o lstart=` — вербатим-формат, в котором пишется `session_pid_start`."""
    return dt.astimezone().strftime("%a %b %d %H:%M:%S %Y")


@pytest.fixture()
def tracker(tmp_path):
    d = tmp_path / "tracker"
    d.mkdir()
    return d


@pytest.fixture()
def log(tmp_path):
    p = tmp_path / "session_changes.jsonl"
    p.write_text("", encoding="utf-8")
    return p


def _entry(ts, *, card, state, pid, started):
    return {"ts": _fmt(ts), "session": HOLDER, "summary": "работа", "files": [],
            "card": card, "card_state": state, "verified": "",
            "session_pid": pid, "session_pid_start": _lstart(started)}


def _scene(tracker, log, *, done_card=CARD, done_after_claim=True, with_done=True,
           identity=True):
    """Сцена 08.10 дословно: захват во frontmatter + собственное `card_state: done`.

    Пять записей журнала — ровно те, что лежат в живом журнале под ярлыком `cycle-806`:
    два объявления августовского процесса по ДРУГОЙ карточке (они и делают ярлык
    переиспользованным) и три октябрьских по этой — захват и два снятия.
    """
    claimed_at = NOW - timedelta(hours=4.6)
    fm = ["---", "trackerStatus:", "  type: inbox",
          'title: "TASK — Portfolio CIO: приказ владельца"', "status: in-progress",
          "priority: critical", f"claimed_by: {HOLDER}",
          f"claimed_at: {_fmt(claimed_at)}", "---"]
    (tracker / f"{CARD}.md").write_text("\n".join(fm) + "\n\nтело приказа\n",
                                        encoding="utf-8")

    old_start = NOW - timedelta(days=64)
    new_start = NOW - timedelta(hours=4.7)
    rows = []
    if identity:
        rows += [_entry(old_start, card=OTHER_CARD, state="claim",
                        pid=PID_OLD, started=old_start),
                 _entry(old_start + timedelta(minutes=25), card=OTHER_CARD, state="done",
                        pid=PID_OLD, started=old_start)]
    pid, start = (PID_NEW, new_start) if identity else (None, None)

    def row(ts, card, state):
        if identity:
            return _entry(ts, card=card, state=state, pid=pid, started=start)
        e = _entry(ts, card=card, state=state, pid=0, started=NOW)
        e.pop("session_pid"), e.pop("session_pid_start")
        return e

    rows.append(row(claimed_at + timedelta(seconds=1), CARD, "claim"))
    if with_done:
        done_at = (NOW - timedelta(hours=3.5) if done_after_claim
                   else claimed_at - timedelta(hours=1))
        rows.append(row(done_at, done_card, "done"))
    log.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                   encoding="utf-8")
    return claimed_at


def _run(guard, sibling, tracker, log):
    return guard.gather(CARD, log=log, tracker_dir=tracker, sibling=sibling,
                        self_session="cycle-808", now=NOW, grace_hours=3.0,
                        planned_files=(), ps=DEAD, self_anchor=None)


class TestHolderOwnDoneReleasesTheFrontmatterClaim:
    """Положительный контроль: сцена 08.10. На коде origin/main каждый тест КРАСНЫЙ
    (замер дифференциально: PRISTINE verdict=unchecked, exit=2, unmeasured=1)."""

    def test_verdict_is_no_longer_unchecked(self, guard, sibling, tracker, log):
        _scene(tracker, log)
        r = _run(guard, sibling, tracker, log)

        assert r["unmeasured"] == [], (
            "замок остался: frontmatter-захват снова ушёл в «не измерено» — "
            f"{r['unmeasured']}")
        assert r["verdict"] != guard.UNCHECKED
        assert guard.exit_code(r) != 2, (
            "код 2 = «брать нельзя»; именно он и запирал приказ владельца навсегда")

    def test_released_record_names_the_holders_own_words_and_time(
            self, guard, sibling, tracker, log):
        """Запись не исчезает из отчёта — она НАЗЫВАЕТСЯ снятой, с временем снятия.

        Время в причине — не украшение: мутант, снимающий захват по отметке ЧУЖОГО
        объявления (card-слепой `releases_by_session` отдал бы максимум по всем
        карточкам), прошёл бы проверку «state == released» и провалил эту.
        """
        _scene(tracker, log)
        r = _run(guard, sibling, tracker, log)

        fm = [h for h in r["history"] if h.get("source") == "frontmatter"]
        assert len(fm) == 1, f"frontmatter-запись пропала из отчёта: {r['history']}"
        assert fm[0]["state"] == "released" and fm[0]["session"] == HOLDER
        assert "card_state" in fm[0]["detail"] and "ЭТОЙ" in fm[0]["detail"], fm[0]["detail"]
        assert _fmt(NOW - timedelta(hours=3.5)) in fm[0]["detail"], fm[0]["detail"]

    def test_the_owners_order_is_claimable_again(self, guard, sibling, tracker, log):
        """Приказ владельца снова берётся ИНСТРУМЕНТОМ — это и есть предмет правки."""
        _scene(tracker, log)
        card_path = tracker / f"{CARD}.md"
        guard.claim_card(card_path, log=log, tracker_dir=tracker, sibling=sibling,
                         session="cycle-808", now=NOW, grace_hours=3.0, ps=DEAD,
                         self_anchor=SELF_ANCHOR)
        text = card_path.read_text(encoding="utf-8")
        assert "claimed_by: cycle-808" in text, text


class TestBoundariesNotWeakened:
    """Отрицательные контроли: каждый ловит свой мутант правки."""

    def test_done_for_another_card_does_not_release(self, guard, sibling, tracker, log):
        """Card-blind снятие сняло бы захват словами про ДРУГУЮ карточку."""
        _scene(tracker, log, done_card=OTHER_CARD)
        r = _run(guard, sibling, tracker, log)

        assert r["verdict"] == guard.UNCHECKED, (
            "захват снят объявлением о ДРУГОЙ карточке — относимость не измерена")
        assert r["unmeasured"], "снятие признано, а относимость не проверена"

    def test_done_before_the_claim_does_not_release(self, guard, sibling, tracker, log):
        """`done` в 10:00 и повторный `claim` в 10:05 — захват ЖИВ (сравнение времён)."""
        _scene(tracker, log, done_after_claim=False)
        r = _run(guard, sibling, tracker, log)

        assert r["verdict"] == guard.UNCHECKED, (
            "мутант, выбросивший сравнение `done_at >= claimed_at`, снял бы живой захват")

    def test_holder_without_done_behaves_exactly_as_before(
            self, guard, sibling, tracker, log):
        """Нет `done` ⇒ прежний исход: личность объявлена, молчит ⇒ «не измерено»."""
        _scene(tracker, log, with_done=False)
        r = _run(guard, sibling, tracker, log)

        assert r["verdict"] == guard.UNCHECKED, (
            "правка задела держателя, который о себе ничего не говорил")

    def test_adr647_aging_of_a_nameless_holder_is_intact(
            self, guard, sibling, tracker, log):
        """Личность не объявлена НИГДЕ и нет `done` ⇒ `stale` по ADR-647, как и было."""
        _scene(tracker, log, with_done=False, identity=False)
        r = _run(guard, sibling, tracker, log)

        assert r["verdict"] == guard.STALE, (
            "старение безымянного захвата (ADR-647) сломано правкой")
        assert r["unmeasured"] == []


class TestTheWritersDoorMatchesTheVerdict:
    """Вторая дверь замка: `claim_card` перечитывает карточку ПОД ЗАМКОМ.

    Комментарий в самом писателе требует, чтобы правило «держит ли кто-то карточку»
    СОВПАДАЛО с вердиктом `gather` (измерено 31.07 на этой же карточке: вердикт
    «СВОБОДНА», запись «успела взять»). Снятие по собственному `done` вернуло то же
    расхождение другим входом — и ровно на нём `test_the_owners_order_is_claimable_again`
    выше был КРАСНЫМ, пока вторая дверь не прочитала тот же сигнал.
    """

    def test_a_reclaim_racing_the_write_still_refuses(self, guard, sibling, tracker, log,
                                                      monkeypatch):
        """Гонка в её настоящем окне: между вердиктом и правкой под замком.

        `claim_card` снимает вердикт САМ, поэтому перезахват, случившийся раньше, ловит
        ранняя дверь (тест ниже). Здесь открывается то единственное окно, которое
        прикрывает сравнение отметок: карточка перезахвачена тем же ярлыком ПОСЛЕ
        вердикта и ДО записи. Мутант, выбросивший сравнение `claimed_at`, перезаписал бы
        живой чужой захват молча — флаг снятия стал бы отмычкой.
        """
        _scene(tracker, log)
        card_path = tracker / f"{CARD}.md"
        reclaimed = _fmt(NOW - timedelta(minutes=1))
        real_lock = guard._acquire_lock

        def racing_lock(path):
            text = card_path.read_text(encoding="utf-8")
            card_path.write_text("\n".join(
                f"claimed_at: {reclaimed}" if line.startswith("claimed_at:") else line
                for line in text.splitlines()) + "\n", encoding="utf-8")
            return real_lock(path)

        monkeypatch.setattr(guard, "_acquire_lock", racing_lock)
        with pytest.raises(Exception) as exc:
            guard.claim_card(card_path, log=log, tracker_dir=tracker, sibling=sibling,
                             session="cycle-808", now=NOW, grace_hours=3.0, ps=DEAD,
                             self_anchor=SELF_ANCHOR)
        assert "успела взять" in str(exc.value), str(exc.value)
        assert f"claimed_by: {HOLDER}" in card_path.read_text(encoding="utf-8")

    def test_a_reclaim_before_the_verdict_refuses_at_the_early_door(
            self, guard, sibling, tracker, log):
        """Перезахват ДО вердикта ловит ранняя дверь: свежий сильный захват ⇒ `claimed`."""
        _scene(tracker, log)
        card_path = tracker / f"{CARD}.md"
        text = card_path.read_text(encoding="utf-8")
        card_path.write_text("\n".join(
            f"claimed_at: {_fmt(NOW - timedelta(minutes=1))}"
            if line.startswith("claimed_at:") else line
            for line in text.splitlines()) + "\n", encoding="utf-8")

        with pytest.raises(Exception) as exc:
            guard.claim_card(card_path, log=log, tracker_dir=tracker, sibling=sibling,
                             session="cycle-808", now=NOW, grace_hours=3.0, ps=DEAD,
                             self_anchor=SELF_ANCHOR)
        assert "claimed" in str(exc.value), str(exc.value)
        assert f"claimed_by: {HOLDER}" in card_path.read_text(encoding="utf-8")
