"""ПЕРЕСЕЧЕНИЕ ПО ФАЙЛАМ обязано мерить РАБОТНИКА, а не запускателя (цикл #867, ADR-723).

Что найдено, и почему это ТРЕТЬЯ дверь одного класса
------------------------------------------------------------------------------
Захват карточки живёт в ТРЁХ записях. Ось РАБОТНИКА (`SPA_RUN_ID` в ОКРУЖЕНИИ)
доходила до двух:

    `claimed_by` / `claimed_run_id` во frontmatter      ADR-721 (цикл #865)
    строка журнала `card_state: claim`                  ADR-722 (цикл #866)
    **пересечение по объявленным ФАЙЛАМ**               мерило ось ЗАПУСКАТЕЛЯ

Третья судила о живости ТОЛЬКО через `sibling.durable_process_gone`, то есть по pid
ЗАПУСКАТЕЛЯ, и метки работника не спрашивала вовсе. Ярлык сессии производен от pid
запускателя (`SPA_SESSION_ID=cycle-$$` в `agent_orchestrator.sh`), а работу делает
работник, поднятый `start_new_session=True`: он ЛИДЕР СВОЕЙ СЕССИИ и переживает
запускателя по построению (замер 14.10, цикл #864: держатель `cycle-69075` МЁРТВ, его
работник pid 69661 ЖИВ и правил файлы за 4 с до замера).

Цена именно у этой двери: сессия, объявившая ФАЙЛЫ и НЕ взявшая карточку ни одним из
двух захватов, читалась по мёртвой оси. Направление ошибки — не ложная занятость, а
ОТСУТСТВИЕ ЗАЩИТЫ: `orphaned=True` вердикта «ЗАНЯТА» больше не даёт (починка #412),
поэтому две сессии могут править одни файлы, а шаг 0b скажет лишь «осиротевшее
пересечение» в разделе «не находки».

Решение «ЧЬЯ МЕТКА относится к пересечению» — проверяется, а не подразумевается
------------------------------------------------------------------------------
Метка берётся из ТОЙ ЖЕ записи, где объявлены файлы, и ни из какой другой. У этого
решения четыре основания (три — замеры живого журнала, 2721 запись, 14.10), и здесь
закреплено ГЛАВНОЕ его следствие: метка на РОДСТВЕННОЙ записи того же ярлыка
пересечения НЕ оживляет. Иначе переиспользованный ярлык отдал бы живую метку мёртвой
сессии — fail-OPEN внутри fail-CLOSED-сторожа, — а сужения `borrow_durable` «процесс
стартовал НЕ ПОЗЖЕ записи» у метки нет: времени старта у неё не существует.

Что проверяется, и почему в ОБЕ стороны
------------------------------------------------------------------------------
* живой носитель метки ⇒ `claimed` и пересечение НЕ осиротевшее — это и есть защита;
* метки измеренно нет ⇒ `stale` и осиротевшее, как до правки. Без этой стороны правка
  была бы не защитой, а вечным замком на чужих файлах;
* ось НЕ ИЗМЕРЕНА ⇒ третий исход `unchecked`, и он НЕ выдаётся ни за «ждать некого»,
  ни за «занята» (инв. #17);
* метки в записи нет ⇒ всё как до правки, байт в байт (это 2527 записей из 2530);
* объявление СТАРШЕ бюджета работника ⇒ ось не решает. Граница проверена с ДВУХ сторон
  одной минутой И ровно на бюджете;
* `card_state: done` снимает пересечение ДАЖЕ при живой метке — починка
  `agent-card-claim-file-overlap-ignores-done` не отменяется;
* замер оси ЗАПУСКАТЕЛЯ сохраняется (`launcher_orphaned`): вывод оси не вправе
  выглядеть как измерение pid, которого никто не делал.

Оговорка об ОКНЕ, измеренная здесь же (а не предположенная)
------------------------------------------------------------------------------
Пересечение рассматривается ТОЛЬКО внутри окна свежести, и по умолчанию окно (3.00ч)
КОРОЧЕ бюджета работника (4.17ч) ⇒ запись старше бюджета в отчёт не попадает вовсе, и
сцена отдаёт `free`, а не `stale`. Поэтому проверки границы бюджета зовутся с ПОДНЯТЫМ
окном: окно — флаг (`--grace-hours`), значит при поднятом окне бюджет становится
действующим, и сторож обязан ответить ровно на этот случай. Побочное следствие стоит
сказать вслух: «не измерено» у этой двери ограничено ПО ПОСТРОЕНИЮ — оно стареет
вместе с окном и вечным замком стать не может.

Время и живость — ВХОДЫ, а не окружение
------------------------------------------------------------------------------
Литеральных дат в файле нет: все отметки выведены из якоря `NOW`, он же передаётся
измерителю аргументом `now=`. Живость запускателя инъектируется (`ps=`), живость
работника — пробой (`worker=`): сторож, спрашивающий настоящую ОС, менял бы вердикт от
того, кто сегодня занял номер (`.claude/rules/deployment.md` § «ЛИЧНОСТЬ ПРОЦЕССА»).
Контроль ЖИВЫМ носителем метки невозможен по ИЗМЕРЕННОЙ причине: прибор ищет метку в
выводе `ps -A -Ewww`, где окружение читается у 74 строк из 651 (замер 14.10,
`scripts/worker_axis_census.py`), и у специально поднятого `/bin/sleep` её не видно.
"""
import importlib.util
import json
from datetime import timedelta, timezone
from pathlib import Path

import pytest

from spa_core.tests._freshness import now_utc

ROOT = Path(__file__).resolve().parents[2]

#: Якорь времени — РЕАЛЬНЫЕ часы, а не литеральная дата: предмет файла — свежесть
#: объявления и бюджет работника, и литерал начал бы падать от сдвига календаря, а не
#: от кода. Часы ИНЪЕКТИРОВАНЫ: обе стороны сравнения выведены из этого якоря.
#: Доли секунды отрезаны НАМЕРЕННО: отметки печатаются с точностью до секунды
#: (`_fmt_ts`), и у якоря с микросекундами обратный разбор даёт мгновение РАНЬШЕ —
#: проверка «ровно бюджет» мерила бы бюджет плюс доли секунды, то есть другое
#: утверждение.
NOW = now_utc().replace(microsecond=0)

#: Ярлык и метка из аварии 14.10 — дословно (ярлык производен от pid ЗАПУСКАТЕЛЯ).
INCIDENT_LABEL = "cycle-69075"
INCIDENT_RUN_ID = "orchestrator-69075-7F3C1A0B4E5D4A2C9B8E6D1F0A3C5E79"

#: Якорь ЧУЖОЙ сессии, объявившей файлы: номер литеральный безопасно — живым процессом
#: он не притворяется, его живость инъектируется (`ps=DEAD`). Время старта выведено из
#: `NOW`: оно обязано быть РАНЬШЕ записи, иначе `borrow_durable` откажет по своему
#: сужению, и сцена мерила бы отказ заимствования, а не ось работника.
FOREIGN_PID = 69075

#: Личность МОЕЙ сессии: нужна, чтобы чужие записи не опознались как свои (`selves`).
SELF_ANCHOR = (41867, (NOW - timedelta(hours=9)).astimezone().strftime(
    "%a %b %d %H:%M:%S %Y"))

#: Файл, который «я собираюсь править»: абсолютный, как требует протокол объявления.
MINE = "/abs/tree/spa_core/overlap_scene.py"

DEAD = lambda pid: (1, "")                                           # noqa: E731


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load("_c867_card_claim", "scripts/check_card_claim.py")


@pytest.fixture(scope="module")
def lock():
    return _load("_c867_cycle_lock", "scripts/orchestrator_cycle_lock.py")


@pytest.fixture(scope="module")
def writer():
    return _load("_c867_announcer", "scripts/log_session_change.py")


@pytest.fixture(scope="module")
def sibling(guard):
    return guard.load_sibling()


@pytest.fixture()
def tracker(tmp_path):
    d = tmp_path / "tracker"
    d.mkdir()
    # Карточка БЕЗ захвата: предмет файла — объявление ФАЙЛОВ, а не захват. Будь захват,
    # вердикт пришёл бы от него (предмет ADR-721/722), и порванное звено пересечения
    # выглядело бы целым.
    (d / "inbox-scene.md").write_text(
        "---\ntrackerStatus:\n  type: inbox\ntitle: сцена\nstatus: in-progress\n"
        "---\n\n## Тело\n\nстрока\n", encoding="utf-8")
    return d


def _fmt(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


#: Возраст объявления по умолчанию — ВНУТРИ окна свежести (3ч): вне него пересечение не
#: рассматривается вовсе, и сцена отвечала бы на другой вопрос.
FRESH_AGE_S = 60.0


def _ttl(lock):
    """Бюджет работника — У ПРИБОРА, а не литералом.

    Порог «сколько работник вправе держать чужие файлы» обязан быть ОДНИМ числом с тем,
    по которому таймаут прогона работника его завершает. Литерал разошёлся бы молча."""
    return float(lock.DEFAULT_WORKER_TTL_SEC)


def _log(tmp_path, *, age_s=FRESH_AGE_S, run_id=INCIDENT_RUN_ID, files=(MINE,),
         run_id_on_kin=False, card_state=None, name="session_changes.jsonl",
         field="session_run_id", summary="правлю общий модуль"):
    """Журнал с ОДНИМ чужим объявлением файлов (плюс, по заказу, родственная запись).

    Записи НЕ относятся к карточке ни одним признаком: ни поля `card:`, ни файла
    карточки в списке, ни упоминания её идентификатора в тексте. Иначе это был бы
    захват, и вердикт пришёл бы от него.
    """
    at = NOW - timedelta(seconds=age_s)
    entry = {
        "ts": _fmt(at), "session": INCIDENT_LABEL, "summary": summary,
        "files": list(files), "verified": "",
        "session_pid": FOREIGN_PID,
        # Старт РАНЬШЕ записи: иначе `borrow_durable` откажет своим сужением, и сцена
        # мерила бы отказ заимствования вместо оси работника.
        "session_pid_start": (at - timedelta(hours=2)).astimezone().strftime(
            "%a %b %d %H:%M:%S %Y"),
    }
    if card_state:
        entry["card"] = "inbox-scene"
        entry["card_state"] = card_state
    rows = [entry]
    if run_id and run_id_on_kin:
        # Родственная запись ТОГО ЖЕ ярлыка: метка ЖИВАЯ, но файлов не объявляет.
        kin = dict(entry)
        kin["files"] = []
        kin["summary"] = "родственная запись того же ярлыка"
        kin[field] = run_id
        rows.append(kin)
    elif run_id:
        entry[field] = run_id
    p = tmp_path / name
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                 encoding="utf-8")
    return p


def _probe(axis, ttl, *, calls=None, why=None):
    """Проба оси РАБОТНИКА как ВХОД. `calls` — список, куда пишутся запрошенные метки."""
    def _ask(run_id):
        if calls is not None:
            calls.append(run_id)
        if not str(run_id or "").strip():
            return "not_declared", "метки нет — ось НЕ МЕРИЛАСЬ", None
        return axis, why or f"сцена: ось РАБОТНИКА = {axis}", ttl
    return _ask


def _ask(guard, sibling, tracker, log, *, worker, grace_hours=None):
    kw = {} if grace_hours is None else {"grace_hours": grace_hours}
    return guard.gather("inbox-scene", log=log, tracker_dir=tracker, sibling=sibling,
                        self_session="cycle-79433", now=NOW, ps=DEAD,
                        self_anchor=SELF_ANCHOR, shared_trees=(), worker=worker,
                        planned_files=(MINE,), **kw)


def _one(report):
    overlaps = report["overlaps"]
    assert len(overlaps) == 1, f"ожидалось одно пересечение, пришло {overlaps!r}"
    return overlaps[0]


# ── предпосылка сцены: на ней НЕТ захвата, иначе предмет подменён ───────────

def test_the_scene_carries_no_claim_at_all(guard, sibling, tracker, tmp_path, lock):
    """Предпосылка, без которой весь файл мерил бы ADR-721/722, а не свою дверь.

    Если бы запись опознавалась как захват (поле `card:`, файл карточки среди
    объявленных, упоминание идентификатора в тексте), вердикт `claimed` приходил бы
    от неё, и порванное пересечение выглядело бы целым. Проверяется ОТДЕЛЬНО и ПЕРВЫМ:
    тест, не обеспечивший свою предпосылку, обязан сказать это вслух."""
    report = _ask(guard, sibling, tracker,
                  _log(tmp_path), worker=_probe(guard.W_ALIVE, _ttl(lock)))
    assert report["claims"] == [], f"на сцене появился захват: {report['claims']!r}"
    assert report["self_claims"] == []
    assert len(report["overlaps"]) == 1


# ── главное: живой работник ДЕРЖИТ объявленные им файлы ────────────────────

def test_a_live_worker_holds_the_files_it_declared(guard, sibling, tracker, tmp_path,
                                                   lock):
    """Ось РАБОТНИКА жива ⇒ `claimed`, пересечение НЕ осиротевшее. Это и есть защита.

    ДО правки эта же сцена давала `stale`: ось запускателя мёртва (`ps` rc=1), а метку
    никто не спрашивал. Порванное звено: убрать вызов `_overlap_worker` — и тест
    покраснеет здесь."""
    report = _ask(guard, sibling, tracker,
                  _log(tmp_path), worker=_probe(guard.W_ALIVE, _ttl(lock)))
    row = _one(report)
    assert report["verdict"] == guard.CLAIMED, report["verdict"]
    assert row["orphaned"] is False, row
    assert row["worker_axis"] == guard.W_ALIVE
    assert row["worker_run_id"] == INCIDENT_RUN_ID


def test_the_launcher_measurement_is_kept_beside_the_worker_verdict(
        guard, sibling, tracker, tmp_path, lock):
    """Вывод оси РАБОТНИКА не вправе затирать ЗАМЕР оси запускателя.

    `orphaned` читает вердикт, поэтому оживить пересечение можно только им. Но тогда
    отчёт утверждал бы «долгоживущий процесс не опровергнут», хотя `ps` его измеренно
    не нашёл. Замер сохраняется отдельным полем — иначе читателю нечем проверить вывод.
    Порванное звено: не писать `launcher_orphaned`."""
    row = _one(_ask(guard, sibling, tracker, _log(tmp_path),
                    worker=_probe(guard.W_ALIVE, _ttl(lock))))
    assert row["launcher_orphaned"] is True, row
    assert row["orphaned"] is False


def test_the_mark_is_asked_for_the_record_that_declares_the_files(
        guard, sibling, tracker, tmp_path, lock):
    """Прибор спрашивается ровно о метке ЗАПИСИ С ФАЙЛАМИ, а не о чём-то соседнем.

    Порванное звено: спросить метку держателя карточки (её на сцене нет вовсе) — и
    `calls` не будет содержать метку записи."""
    calls = []
    _ask(guard, sibling, tracker, _log(tmp_path),
         worker=_probe(guard.W_ALIVE, _ttl(lock), calls=calls))
    assert INCIDENT_RUN_ID in calls, calls


# ── обратная сторона: работника измеренно НЕТ ⇒ как до правки ──────────────

def test_a_measured_absent_worker_leaves_the_overlap_orphaned(
        guard, sibling, tracker, tmp_path, lock):
    """Метку не несёт ни один живой процесс ⇒ `stale` и осиротевшее, как до правки.

    Без этой стороны правка была бы не защитой, а вечным замком на чужих файлах.
    Порванное звено: оживлять пересечение на ЛЮБОЙ оси, не только `alive`."""
    report = _ask(guard, sibling, tracker, _log(tmp_path),
                  worker=_probe(guard.W_GONE, _ttl(lock)))
    row = _one(report)
    assert report["verdict"] == guard.STALE, report["verdict"]
    assert row["orphaned"] is True, row
    assert row["worker_axis"] == guard.W_GONE


def test_an_unmeasured_axis_is_a_third_outcome_not_an_answer(
        guard, sibling, tracker, tmp_path, lock):
    """Ось НЕ ИЗМЕРЕНА ⇒ `unchecked`, и источник назван поимённо (инв. #17).

    «Ждать некого» здесь не говорится: выдать неизмеримость за измеренное отсутствие
    работника значило бы отдать чужие файлы по причине «прибор не ответил». Порванное
    звено: трактовать `unmeasured` как `gone`."""
    report = _ask(guard, sibling, tracker, _log(tmp_path),
                  worker=_probe(guard.W_UNMEASURED, _ttl(lock)))
    assert report["verdict"] == guard.UNCHECKED, report["verdict"]
    sources = {u["source"] for u in report["unmeasured"]}
    assert "announce-log-files" in sources, report["unmeasured"]
    reason = [u["reason"] for u in report["unmeasured"]
              if u["source"] == "announce-log-files"][0]
    assert INCIDENT_RUN_ID in reason, reason
    assert _one(report)["worker_axis"] == guard.W_UNMEASURED


def test_a_record_without_a_mark_behaves_exactly_as_before(
        guard, sibling, tracker, tmp_path, lock):
    """Метки в записи нет ⇒ ось `not_declared`, решает ось ЗАПУСКАТЕЛЯ, байт в байт.

    Это 2527 записей из 2530 живого журнала, то есть ПОЧТИ ВСЁ поведение. Порванное
    звено: спрашивать прибор на пустой метке — он вернул бы бюджет, и запись старого
    образца начала бы судиться осью, которой в ней нет."""
    report = _ask(guard, sibling, tracker, _log(tmp_path, run_id=None),
                  worker=_probe(guard.W_ALIVE, _ttl(lock)))
    row = _one(report)
    assert report["verdict"] == guard.STALE, report["verdict"]
    assert row["orphaned"] is True, row
    assert row["worker_axis"] == guard.W_NOT_DECLARED
    assert row["worker_run_id"] is None
    assert "launcher_orphaned" not in row, "замер оси запускателя подменён без нужды"


# ── РЕШЕНИЕ «чья метка»: родственная запись пересечения НЕ оживляет ────────

def test_a_mark_on_a_kin_record_does_not_revive_the_overlap(
        guard, sibling, tracker, tmp_path, lock):
    """Метка лежит на РОДСТВЕННОЙ записи того же ярлыка ⇒ пересечение осиротевшее.

    Это и есть названное решение: метка относится к ТОЙ ЖЕ записи, где объявлены файлы.
    Заимствуй её у соседней — и переиспользованный ярлык отдал бы ЖИВУЮ метку мёртвой
    сессии: у метки нет сужения `borrow_durable` «процесс стартовал не позже записи»,
    потому что времени старта у неё не существует. Направление ошибки было бы fail-OPEN
    внутри fail-CLOSED-сторожа.

    Сцена при этом ЗАВЕДОМО способна оживить пересечение — соседний тест на той же
    метке и той же пробе даёт `claimed`; разница ровно в том, НА КАКОЙ записи метка."""
    report = _ask(guard, sibling, tracker, _log(tmp_path, run_id_on_kin=True),
                  worker=_probe(guard.W_ALIVE, _ttl(lock)))
    row = _one(report)
    assert report["verdict"] == guard.STALE, report["verdict"]
    assert row["orphaned"] is True, row
    assert row["worker_axis"] == guard.W_NOT_DECLARED, row


# ── бюджет работника: граница с ДВУХ сторон, и окно поднято НАМЕРЕННО ──────

def test_the_default_window_is_shorter_than_the_worker_budget(guard, lock):
    """Предпосылка двух следующих тестов, ИЗМЕРЕННАЯ, а не предположенная.

    Пересечение рассматривается только внутри окна свежести, и по умолчанию окно
    КОРОЧЕ бюджета работника ⇒ запись старше бюджета в отчёт не попадает вовсе. Поэтому
    граница бюджета и зовётся с поднятым окном. Станет окно длиннее бюджета — этот тест
    покраснеет и скажет, что предпосылка соседей изменилась, вместо того чтобы молча
    превратить их в проверку пустоты."""
    assert float(guard.DEFAULT_GRACE_HOURS) * 3600.0 < _ttl(lock)


def test_a_hung_worker_stops_holding_files_past_its_budget(
        guard, sibling, tracker, tmp_path, lock):
    """Объявление СТАРШЕ бюджета работника ⇒ ось не решает, файлы отпускаются.

    «Не измерено» без срока есть вечный замок, а не порог — то же рассуждение, что у
    `worker_ttl` ADR-720. Порванное звено: убрать сравнение с бюджетом."""
    ttl = _ttl(lock)
    report = _ask(guard, sibling, tracker, _log(tmp_path, age_s=ttl + 1.0),
                  worker=_probe(guard.W_ALIVE, ttl), grace_hours=ttl / 3600.0 + 1.0)
    row = _one(report)
    assert report["verdict"] == guard.STALE, report["verdict"]
    assert row["orphaned"] is True, row
    assert row["worker_over_budget"] is True, row


def test_inside_its_budget_the_same_worker_still_holds(
        guard, sibling, tracker, tmp_path, lock):
    """Та же запись в ТОМ ЖЕ поднятом окне, но внутри бюджета ⇒ держит.

    Без этой половины «за бюджетом ⇒ stale» прошло бы и от того, что ось не работает в
    поднятом окне вовсе: граница была бы проверена с одной стороны."""
    ttl = _ttl(lock)
    report = _ask(guard, sibling, tracker, _log(tmp_path, age_s=ttl - 60.0),
                  worker=_probe(guard.W_ALIVE, ttl), grace_hours=ttl / 3600.0 + 1.0)
    row = _one(report)
    assert report["verdict"] == guard.CLAIMED, report["verdict"]
    assert row["orphaned"] is False, row
    assert row["worker_over_budget"] is False, row


def test_exactly_at_the_budget_the_worker_still_holds(
        guard, sibling, tracker, tmp_path, lock):
    """РОВНО бюджет — ещё не «старше бюджета»: сравнение строгое, и это проверяется.

    Возраст считается В СЕКУНДАХ у разницы отметок, а не обратным переводом из часов:
    `age * 3600` на ровно бюджете даёт 15000.000000000002, и «ровно бюджет» молча
    становилось бы «бюджет плюс чуть-чуть»."""
    ttl = _ttl(lock)
    report = _ask(guard, sibling, tracker, _log(tmp_path, age_s=ttl),
                  worker=_probe(guard.W_ALIVE, ttl), grace_hours=ttl / 3600.0 + 1.0)
    assert _one(report)["worker_over_budget"] is False
    assert report["verdict"] == guard.CLAIMED, report["verdict"]


# ── соседние починки не отменяются ─────────────────────────────────────────

def test_a_declared_done_still_releases_the_files_even_with_a_live_mark(
        guard, sibling, tracker, tmp_path, lock):
    """`card_state: done` снимает пересечение ДАЖЕ при живой метке.

    Сессия, объявившая `done`, работу закончила — ложная занятость учит игнорировать
    вердикт (`agent-card-claim-file-overlap-ignores-done`). Ось РАБОТНИКА эту починку
    не отменяет: до неё дело не доходит вовсе. Порванное звено: спросить ось РАНЬШЕ,
    чем снятие по `done`."""
    report = _ask(guard, sibling, tracker, _log(tmp_path, card_state="done"),
                  worker=_probe(guard.W_ALIVE, _ttl(lock)))
    assert report["overlaps"] == [], report["overlaps"]
    assert report["verdict"] == guard.FREE, report["verdict"]


def test_an_unknown_field_name_is_unchecked_not_a_silent_launcher_axis(
        guard, sibling, tracker, tmp_path, lock):
    """Имя поля метки не спрошено у писателя ⇒ `unchecked`, а не прежнее поведение.

    Молча вернуться к оси ЗАПУСКАТЕЛЯ нельзя: это выглядит как «так и было задумано»,
    то есть «не измерено» выдаётся за ответ (инв. #17, урок `pyflakes` из
    `.claude/rules/deployment.md`)."""
    report = guard.gather(
        "inbox-scene", log=_log(tmp_path), tracker_dir=tracker, sibling=sibling,
        self_session="cycle-79433", now=NOW, ps=DEAD, self_anchor=SELF_ANCHOR,
        shared_trees=(), worker=_probe(guard.W_ALIVE, _ttl(lock)),
        planned_files=(MINE,), field_name=guard.RUN_ID_FIELD_UNKNOWN)
    assert report["verdict"] == guard.UNCHECKED, report["verdict"]
    assert _one(report)["worker_axis"] == guard.W_NOT_DECLARED


def test_the_reader_and_the_writer_name_the_field_once(guard, writer):
    """Имя поля ОДНО: читатель берёт его у писателя, своей копии строки не держит.

    Вторая копия переживёт переименование МОЛЧА и тихо вернёт прежнее поведение, которое
    выглядит как «так и было» (`.claude/rules/adapters.md` § «одно имя — один объект»)."""
    name, why = guard.run_id_field(announcer=writer)
    assert name == writer.RUN_ID_FIELD, (name, writer.RUN_ID_FIELD, why)


def test_the_axis_word_is_a_field_from_a_closed_vocabulary(guard, sibling, tracker,
                                                           tmp_path, lock):
    """Ответ лежит в ПОЛЕ со значением из закрытого перечня, а не в прозе (ADR-333).

    Разбор подстрокой запрещён: проза меняется от редактуры, и сторож на ней молча
    перестаёт мерить. Перечень обходится, а не ищется по совпадению."""
    row = _one(_ask(guard, sibling, tracker, _log(tmp_path),
                    worker=_probe(guard.W_ALIVE, _ttl(lock))))
    assert row["worker_axis"] in guard.WORKER_AXES, row
    assert set(guard.WORKER_AXES) == {guard.W_NOT_DECLARED, guard.W_ALIVE,
                                      guard.W_GONE, guard.W_UNMEASURED}


def test_the_report_text_names_the_axis_for_a_live_overlap(guard, sibling, tracker,
                                                           tmp_path, lock):
    """Читатель-человек обязан видеть, КАКАЯ ось дала «держатся», а не только вердикт.

    Отчёт, печатающий «пересечение держит файлы» без имени оси, заставляет сверять
    вывод по памяти. Порванное звено: не печатать строку оси у живых пересечений."""
    report = _ask(guard, sibling, tracker, _log(tmp_path),
                  worker=_probe(guard.W_ALIVE, _ttl(lock)))
    if not hasattr(guard, "render"):      # имя функции печати могло измениться
        pytest.fail("у шага 0b нет печати отчёта — строку оси проверить нечем")
    text = guard.render(report)
    assert "ось РАБОТНИКА" in text, text
    assert guard.W_ALIVE in text, text
