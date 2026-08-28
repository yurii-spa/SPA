"""Одна сессия — ДВА ярлыка в журнале, и смерть, измеренная у одного, обязана дойти до другого.

**Авария, которую проигрывает каждый тест здесь** (18.08.2026, цикл #293, живой замер).
Шаг 0a сказал про сессию #292: «долгоживущий процесс pid71225 завершился, работа осиротела,
поднимай». Шаг 0b про ТУ ЖЕ сессию в ту же минуту сказал `⛔ ЗАНЯТА — НЕ бери эту карточку`,
причём двумя строками ниже НАПЕЧАТАЛ ту же смерть. Подъём осиротевшей работы — то самое
действие, к которому звал протокол, — оказался запрещён сторожем.

**Почему так вышло, и почему это не повторение #238.** Сессия пишет в журнал под двумя
ярлыками, и оба правильные:

- захват — под ярлыком, переданным флагом `--session pidN` (так велит шаг 0b протокола,
  карточка `agent-durable-session-id`);
- объявление владения — под собственным `SPA_SESSION_ID` вида `cycle-N-pidN`.

`log_session_change.record` ставит якорь долгоживущего процесса (`session_pid` +
`session_pid_start`) ТОЛЬКО на запись со своим ярлыком — и это верно, менять там нечего
(карточка `agent-claim-guard-blind-when-session-pid-is-set`: якорь на чужом ярлыке читался бы
как «запись моя»). Значит у записи-захвата якоря нет ПО ПОСТРОЕНИЮ. `borrow_durable` (#265)
одалживал личность строго под ТЕМ ЖЕ ярлыком и до соседнего не дотягивался, поэтому:

- пока захват свеж — `⛔ ЗАНЯТА` (окно свежести меряет ВРЕМЯ, а ждать уже некого). Это и есть
  наблюдавшийся случай: все 6 записей живого замера — голые ярлыки `pidN`;
- у СОСТАВНОГО ярлыка (`cycle-N-pidN` под `_PID_RE` не подходит) — ещё и `unchecked`, код 2,
  когда захват состарится. Форма реальная, но в замере 18.08 не встретилась — сказано как
  теория, а не как наблюдение.

Замок над ПОЗНАВАЕМЫМ фактом: якорь лежал в том же журнале, секундами позже. #238 чинил
случай, где смерть была ИЗМЕРЕНА и не доезжала до вердикта; здесь она не доезжала до самого
измерения.

**Замер, решивший чинить** (журнал 18.08, 996 записей): захватов 430, из них без якоря 116,
и у 6 (5 карточек) якорь сессии лежал в соседнем ярлыке — во всех шести случаях соседний
ярлык был к моменту замера измеримо мёртв.

Тесты герметичны: свой журнал и свой каталог карточек в ``tmp_path``, `ps` подменяется, время
подаётся ВХОДОМ (`now=NOW`). Все отметки журнала и времена старта процессов отсчитываются от
той же точки — обе стороны каждого сравнения закреплены, поэтому файл не привязан к календарю
(правило `.claude/rules/deployment.md`, порядок предпочтения 1). Точка — литерал, а не снимок
часов: первая версия читала `datetime.now()` на уровне модуля и её честно завернул сторож
`test_no_import_time_clock_in_tests` (прогон, пересёкший полночь, покраснел бы неповторимо).
"""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# FROZEN-DATE-OK: время здесь — ВХОД, а не окружение (правило `.claude/rules/deployment.md`,
# порядок предпочтения 1). `now` подаётся сторожу явно, все отметки журнала и времена старта
# процессов отсчитываются от этой же точки ⇒ обе стороны каждого сравнения закреплены и
# смена календаря тест не двигает. Часы на уровне модуля читать нельзя (сторож
# `test_no_import_time_clock_in_tests`: прогон, пересёкший полночь, покраснеет неповторимо),
# поэтому точка — литерал, как и у соседнего `test_card_claim_guard.py`.
NOW = datetime(2026, 8, 18, 19, 33, 0, tzinfo=timezone.utc)


def _load(name, rel):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load("_kin_card_claim", "scripts/check_card_claim.py")


@pytest.fixture(scope="module")
def sibling(guard):
    return guard.load_sibling()


def _fmt(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lstart(dt):
    """Время старта процесса в формате `ps -o lstart=` (локальная зона, как отдаёт сам `ps`)."""
    return dt.astimezone().strftime("%a %b %d %H:%M:%S %Y")


# Личность сессии #292 в терминах фикстуры: процесс стартовал ЗАДОЛГО до своих записей —
# иначе сработало бы сужение `borrow_durable` («родившийся после записи её не писал»), и тест
# краснел бы по причине, к предмету проверки отношения не имеющей.
STARTED = NOW - timedelta(hours=12)
ANCHOR = {"session_pid": 71225, "session_pid_start": _lstart(STARTED)}

CLAIM_LABEL = "pid71239"            # ярлык записи-захвата (передан флагом `--session`)
CYCLE_LABEL = "cycle-292-pid71239"  # ярлык объявления владения (`SPA_SESSION_ID`)


def entry(session, ts, *, anchor=None, card=None, card_state="claim", files=(), summary="работа"):
    e = {"ts": _fmt(ts), "session": session, "summary": summary,
         "files": [str(f) for f in files], "verified": ""}
    if card:
        e["card"], e["card_state"] = card, card_state
    if anchor:
        e.update(anchor)
    return e


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


def write_log(path, entries):
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
                    encoding="utf-8")


def write_card(tracker, cid, *, status="new"):
    p = tracker / f"{cid}.md"
    p.write_text("---\ntrackerStatus:\n  type: inbox\ntitle: Карточка\n"
                 f"status: {status}\n---\n\nтело\n", encoding="utf-8")
    return p


@pytest.fixture()
def ps_dead():
    """`ps` отвечает «процесса нет» — ровно то, что видит следующий цикл после смерти сессии."""
    return lambda pid: (1, "")


@pytest.fixture()
def ps_alive():
    """`ps` показывает ИМЕННО тот процесс, что записан в якоре ⇒ активность ПОДТВЕРЖДЕНА."""
    return lambda pid: (0, _lstart(STARTED)) if pid == ANCHOR["session_pid"] else (1, "")


def run(guard, sibling, tracker, log, card, *, session="cycle-293", ps=None,
        planned_files=()):
    return guard.gather(card, log=log, tracker_dir=tracker, sibling=sibling,
                        self_session=session, now=NOW, grace_hours=3.0,
                        planned_files=planned_files, ps=ps, self_anchor=None)


# ── 1. родство ярлыков: токен `pidN` — КОМПОНЕНТ, а не подстрока ─────────────

class TestPidTokensAreComponents:
    def test_bare_and_composite_labels_yield_the_same_token(self, sibling):
        assert sibling.pid_tokens(CLAIM_LABEL) == {"pid71239"}
        assert sibling.pid_tokens(CYCLE_LABEL) == {"pid71239"}

    def test_a_shorter_pid_is_not_found_inside_a_longer_one(self, sibling):
        """Подстрочная коллизия — отдельный класс аварий (#227): `pid7` внутри `pid71239`
        породнил бы две ЧУЖИЕ сессии, и смерть одной погасила бы захват другой."""
        assert sibling.pid_tokens("cycle-1-pid71239") == {"pid71239"}
        assert "pid7" not in sibling.pid_tokens("cycle-1-pid71239")

    def test_label_without_a_pid_has_no_token(self, sibling):
        assert sibling.pid_tokens("cycle63608") == set()
        assert sibling.pid_tokens("") == set()


class TestKinAnchorOnlyWhenUnambiguous:
    def test_bare_claim_label_borrows_the_anchor_of_its_cycle_label(self, sibling):
        """Главный случай: у записи-захвата якоря нет, у соседнего ярлыка той же сессии — есть."""
        rows = [entry(CLAIM_LABEL, NOW - timedelta(minutes=70), card="agent-x"),
                entry(CYCLE_LABEL, NOW - timedelta(minutes=68), anchor=ANCHOR, card="agent-x")]
        anchors, kin = sibling.anchors_with_kin(rows)
        assert anchors[CLAIM_LABEL] == ANCHOR
        assert kin[CLAIM_LABEL] == CYCLE_LABEL

    def test_own_anchor_always_wins(self, sibling):
        """Свой якорь сильнее родственного: родство — замена отсутствию, а не поправка."""
        mine = {"session_pid": 500, "session_pid_start": _lstart(STARTED)}
        rows = [entry(CLAIM_LABEL, NOW - timedelta(minutes=70), anchor=mine),
                entry(CYCLE_LABEL, NOW - timedelta(minutes=68), anchor=ANCHOR)]
        anchors, kin = sibling.anchors_with_kin(rows)
        assert anchors[CLAIM_LABEL] == mine
        assert CLAIM_LABEL not in kin

    def test_two_anchors_on_one_token_give_no_kin(self, sibling):
        """Неоднозначность = отказ. Угадывать, которая из сессий писала, инструмент не станет."""
        other = {"session_pid": 900, "session_pid_start": _lstart(STARTED)}
        rows = [entry(CLAIM_LABEL, NOW - timedelta(minutes=70)),
                entry(CYCLE_LABEL, NOW - timedelta(minutes=68), anchor=ANCHOR),
                entry("cycle-999-pid71239", NOW - timedelta(minutes=60), anchor=other)]
        anchors, kin = sibling.anchors_with_kin(rows)
        assert CLAIM_LABEL not in anchors and CLAIM_LABEL not in kin

    def test_label_whose_own_anchor_is_ambiguous_gets_no_kin(self, sibling):
        """Правило неоднозначности `durable_by_session` не снимается с чёрного хода."""
        first = {"session_pid": 71225, "session_pid_start": _lstart(STARTED)}
        second = {"session_pid": 71225, "session_pid_start": _lstart(STARTED - timedelta(hours=9))}
        rows = [entry(CLAIM_LABEL, NOW - timedelta(minutes=90), anchor=first),
                entry(CLAIM_LABEL, NOW - timedelta(minutes=80), anchor=second),
                entry(CYCLE_LABEL, NOW - timedelta(minutes=70), anchor=ANCHOR)]
        anchors, kin = sibling.anchors_with_kin(rows)
        assert CLAIM_LABEL not in anchors and CLAIM_LABEL not in kin

    def test_two_tokens_in_one_label_give_no_kin(self, sibling):
        rows = [entry("pid71239-pid900", NOW - timedelta(minutes=70)),
                entry(CYCLE_LABEL, NOW - timedelta(minutes=68), anchor=ANCHOR)]
        _anchors, kin = sibling.anchors_with_kin(rows)
        assert "pid71239-pid900" not in kin

    def test_label_without_a_token_gets_no_kin(self, sibling):
        rows = [entry("cycle63608", NOW - timedelta(minutes=70)),
                entry(CYCLE_LABEL, NOW - timedelta(minutes=68), anchor=ANCHOR)]
        _anchors, kin = sibling.anchors_with_kin(rows)
        assert "cycle63608" not in kin

    def test_no_kin_anywhere_leaves_the_map_exactly_as_before(self, sibling):
        """Обратный контроль: без родни результат побайтово равен `durable_by_session`."""
        rows = [entry("pid4242", NOW - timedelta(minutes=70)),
                entry("cycle-1-pid99", NOW - timedelta(minutes=68), anchor=ANCHOR)]
        anchors, kin = sibling.anchors_with_kin(rows)
        assert anchors == sibling.durable_by_session(rows) and kin == {}


class TestBorrowingStaysNarrowAndSaysWhereFrom:
    def test_a_process_born_after_the_record_is_not_borrowed(self, sibling):
        """Сужение #265 действует и для родни: процесс, родившийся ПОСЛЕ записи, её не писал.
        Без этого переиспользованный ярлык дал бы ложный ACTIVE — fail-OPEN внутри сторожа."""
        late = {"session_pid": 71225, "session_pid_start": _lstart(NOW - timedelta(minutes=5))}
        rows = [entry(CLAIM_LABEL, NOW - timedelta(minutes=70)),
                entry(CYCLE_LABEL, NOW - timedelta(minutes=68), anchor=late)]
        anchors, kin = sibling.anchors_with_kin(rows)
        borrowed, why = sibling.borrow_durable(rows[0], anchors, kin)
        assert sibling.durable_fields(borrowed) == {} and why == ""

    def test_the_explanation_names_the_kin_label(self, sibling):
        """Заимствование НАЗЫВАЕТСЯ вслух: иначе отчёт утверждал бы про запись то, чего в ней
        не написано, — и читатель не смог бы проверить вывод."""
        rows = [entry(CLAIM_LABEL, NOW - timedelta(minutes=70)),
                entry(CYCLE_LABEL, NOW - timedelta(minutes=68), anchor=ANCHOR)]
        anchors, kin = sibling.anchors_with_kin(rows)
        borrowed, why = sibling.borrow_durable(rows[0], anchors, kin)
        assert borrowed["session_pid"] == 71225
        assert CYCLE_LABEL in why and "РОДСТВЕННОМУ" in why


# ── 2. шаг 0b: вердикт про ту же сессию, что и у шага 0a ─────────────────────

class TestStep0bAgreesWithStep0aAboutDeath:
    """Положительные контроли — дословная авария 18.08; обратные — то, что меняться не смело."""

    def _journal(self, log, *, anchor, claim_age_min, card="agent-x", files=()):
        write_log(log, [
            entry(CLAIM_LABEL, NOW - timedelta(minutes=claim_age_min), card=card,
                  summary="[check_card_claim] захват карточки"),
            entry(CYCLE_LABEL, NOW - timedelta(minutes=claim_age_min - 2), anchor=anchor,
                  card=card, files=files, summary="цикл #292: работа осиротела"),
        ])

    def test_fresh_claim_of_a_dead_session_is_stale_not_claimed(self, guard, sibling, tracker,
                                                                log, ps_dead):
        """АВАРИЯ 18.08: свежий захват под голым ярлыком + смерть под соседним ⇒ был `claimed`."""
        write_card(tracker, "agent-x")
        self._journal(log, anchor=ANCHOR, claim_age_min=77)
        r = run(guard, sibling, tracker, log, "agent-x", ps=ps_dead)
        assert r["verdict"] == guard.STALE
        assert guard.exit_code(r) == 1
        holders = {c["session"]: c for c in r["claims"]}
        assert holders[CLAIM_LABEL]["orphaned"] is True
        assert "pid71225" in holders[CLAIM_LABEL]["session_state"]

    def test_old_bare_label_claim_was_already_stale_before(self, guard, sibling, tracker,
                                                           log, ps_dead):
        """ОБРАТНЫЙ контроль, и он же поправка к диагнозу.

        Соблазнительно было записать сюда «вторую половину замка»: мол, состарившись, тот же
        захват давал `unchecked`. ИЗМЕРЕНО — неправда: у ГОЛОГО ярлыка `pidN` активность
        читается прямо из ярлыка (`not_confirmed`), поэтому старый захват уходил в `stale` и
        без родства. Дефект жил ровно в ОКНЕ СВЕЖЕСТИ — и все 6 записей живого замера 18.08
        были именно такими. Родство обязано это поведение сохранить, а не «улучшить»."""
        write_card(tracker, "agent-x")
        self._journal(log, anchor=ANCHOR, claim_age_min=200)
        r = run(guard, sibling, tracker, log, "agent-x", ps=ps_dead)
        assert r["verdict"] == guard.STALE
        assert r["unmeasured"] == []

    def test_old_composite_label_claim_is_no_longer_unchecked(self, guard, sibling, tracker,
                                                              log, ps_dead):
        """Вторая половина замка — она есть, но у СОСТАВНОГО ярлыка: `cycle-292-pid71239` под
        `_PID_RE` не подходит ⇒ `unknown` ⇒ старый сильный захват уходил в «не измерено»
        (код 2, «брать нельзя») над фактом, лежавшим в том же журнале. В живом замере 18.08
        такой формы не встретилось — говорим это вслух, а не выдаём теорию за наблюдение."""
        write_card(tracker, "agent-x")
        write_log(log, [
            entry(CYCLE_LABEL, NOW - timedelta(hours=9), card="agent-x",
                  summary="[check_card_claim] захват карточки"),
            entry(CLAIM_LABEL, NOW - timedelta(hours=9) + timedelta(minutes=2), anchor=ANCHOR,
                  summary="объявление владения"),
        ])
        r = run(guard, sibling, tracker, log, "agent-x", ps=ps_dead)
        assert r["verdict"] == guard.STALE
        assert r["unmeasured"] == []

    def test_a_live_session_still_blocks(self, guard, sibling, tracker, log, ps_alive):
        """Обратный контроль: та же форма журнала, но процесс ЖИВ ⇒ карточку НЕ отдают.

        **Правка намеренная (инвариант #16, цикл #412).** Утверждение о КОДЕ ВОЗВРАТА — то,
        ради чего тест написан, — не тронуто: очередь закрыта, взять карточку нельзя.
        Изменился ярлык исхода: голос сессии в этой фикстуре старше окна (200 мин при окне
        3ч), а живой якорь с 28.08 больше не держит карточку БЕССРОЧНО — иначе якорь-хост
        десктопного приложения запирает карточку навсегда (см. `test_card_claim_host_anchor`).
        Живой И говорящий держатель по-прежнему даёт `claimed` — это проверяет тест ниже."""
        write_card(tracker, "agent-x")
        self._journal(log, anchor=ANCHOR, claim_age_min=200)
        r = run(guard, sibling, tracker, log, "agent-x", ps=ps_alive)
        assert r["verdict"] == guard.STALE
        assert guard.exit_code(r) == 1
        assert r["verdict"] != guard.FREE

    def test_a_live_and_speaking_session_still_blocks(self, guard, sibling, tracker, log,
                                                      ps_alive):
        """Та же фикстура, но захват в окне ⇒ `claimed`, как и до цикла #412."""
        write_card(tracker, "agent-x")
        self._journal(log, anchor=ANCHOR, claim_age_min=30)
        r = run(guard, sibling, tracker, log, "agent-x", ps=ps_alive)
        assert r["verdict"] == guard.CLAIMED
        assert guard.exit_code(r) == 1

    def test_without_kin_the_fresh_claim_still_blocks(self, guard, sibling, tracker, log,
                                                      ps_dead):
        """Обратный контроль: якоря нет НИГДЕ ⇒ поведение прежнее (свежий сильный захват
        блокирует). Родство не открывает дверь захватам, о которых ничего не измерено."""
        write_card(tracker, "agent-x")
        self._journal(log, anchor=None, claim_age_min=77)
        r = run(guard, sibling, tracker, log, "agent-x", ps=ps_dead)
        assert r["verdict"] == guard.CLAIMED

    def test_frontmatter_holder_is_measured_through_its_kin(self, guard, sibling, tracker, log,
                                                            ps_dead):
        """Захват в самой карточке — второй вход в тот же дефект: `claimed_by` несёт ЯРЛЫК,
        и если якорь лежит под родственным, до #293 он до вердикта не доезжал."""
        write_card(tracker, "agent-x")
        (tracker / "agent-x.md").write_text(
            "---\ntrackerStatus:\n  type: inbox\ntitle: Карточка\nstatus: new\n"
            f"claimed_by: {CLAIM_LABEL}\nclaimed_at: {_fmt(NOW - timedelta(minutes=77))}\n"
            "---\n\nтело\n", encoding="utf-8")
        write_log(log, [entry(CYCLE_LABEL, NOW - timedelta(minutes=75), anchor=ANCHOR)])
        r = run(guard, sibling, tracker, log, "agent-x", ps=ps_dead)
        assert r["verdict"] == guard.STALE
        assert [c for c in r["claims"] if c["orphaned"]]

    def test_file_overlap_of_a_dead_session_does_not_block_either(self, guard, sibling, tracker,
                                                                  log, ps_dead):
        """Пересечение по файлам — НЕЗАВИСИМОЕ измерение, и оно судило по голой записи: одна и
        та же мёртвая сессия читалась захватом как осиротевшая, а файлами как живая, а вердикт
        берёт худшее ⇒ снова `ЗАНЯТА`. Починка одного близнеца из двух (#37) — не починка."""
        write_card(tracker, "agent-y")          # другая карточка: работает только пересечение
        write_log(log, [
            entry(CLAIM_LABEL, NOW - timedelta(minutes=77),
                  files=["/tmp/spa_c292/scripts/check_undelivered_work.py"],
                  summary="объявление владения без якоря"),
            entry(CYCLE_LABEL, NOW - timedelta(minutes=75), anchor=ANCHOR),
        ])
        r = run(guard, sibling, tracker, log, "agent-y", ps=ps_dead,
                planned_files=["scripts/check_undelivered_work.py"])
        assert r["verdict"] == guard.STALE
        assert r["overlaps"] and all(o["orphaned"] for o in r["overlaps"])

    def test_live_file_overlap_still_blocks(self, guard, sibling, tracker, log, ps_alive):
        """Обратный контроль к предыдущему: живая сессия по-прежнему держит свои файлы."""
        write_card(tracker, "agent-y")
        write_log(log, [
            entry(CLAIM_LABEL, NOW - timedelta(minutes=77),
                  files=["/tmp/spa_c292/scripts/check_undelivered_work.py"],
                  summary="объявление владения без якоря"),
            entry(CYCLE_LABEL, NOW - timedelta(minutes=75), anchor=ANCHOR),
        ])
        r = run(guard, sibling, tracker, log, "agent-y", ps=ps_alive,
                planned_files=["scripts/check_undelivered_work.py"])
        assert r["verdict"] == guard.CLAIMED
        assert r["overlaps"] and not any(o["orphaned"] for o in r["overlaps"])
