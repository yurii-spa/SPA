"""ИЗМЕРЕННОЕ отсутствие работника обязано доезжать до вердикта (цикл #868, ADR-724).

Что найдено, и чем это отличается от ADR-721
------------------------------------------------------------------------------
ADR-721 дал шагу 0b ось РАБОТНИКА: метка владения (`claimed_run_id`) во frontmatter,
живой носитель ⇒ карточка ЗАНЯТА, и живая работа перестала выдаваться второй сессии.
Обратная сторона той же оси — измеренное ОТСУТСТВИЕ носителя — в вердикт не попадала
вовсе. В коде это было сказано вслух и обосновано: «своего исхода не вводится
намеренно: ось ЗАПУСКАТЕЛЯ ниже и так решит (и чаще всего скажет `stale`)».

**«Чаще всего» — ИЗМЕРЕНО, и неверно.** Живой трекер 14.10: из **192** захватов во
frontmatter ярлык пид-измерим у **54** и НЕИЗМЕРИМ у **138**. Неизмерим он именно у той
формы, которую пишет сам оркестратор — `SPA_SESSION_ID=cycle-$$`
(`agent_orchestrator.sh`): цифры в ярлыке есть, токена `pid` нет, и `pid_from_label`
честно отдаёт «активность не измерена». Ось ЗАПУСКАТЕЛЯ в этом случае не решает НИЧЕГО,
а свежий СИЛЬНЫЙ захват блокирует карточку ветвью ВЫШЕ оси работника.

Цена измерена НА ПРИКАЗЕ ВЛАДЕЛЬЦА, до правки
------------------------------------------------------------------------------
14.10 19:45Z, `inbox-task-portfolio-cio-dynamic-capital-alloc`, держатель `cycle-79433`
(цикл #867), захвату 2.79ч:

    ось ЗАПУСКАТЕЛЯ   ps -p 79433 → rc=1; ярлык пид-неизмерим
    ось РАБОТНИКА     живых носителей `orchestrator-79433-…` — 0 (окружение читаемо у 73)
    вердикт шага 0b   ⛔ ЗАНЯТА — НЕ бери эту карточку

Шаг 0a-ГОЛОД требовал взять приказ ПЕРВЫМ; инструмент отказывал. Циклы идут раз в час,
окно свежести — 3ч ⇒ так заперт КАЖДЫЙ цикл, стартовавший раньше трёх часов после
мёртвого предшественника. Направление ошибки — ПОТЕРЯ ХОДА, а не кража работы.

Цикл #803 оставил «свежий безымянный захват = `claimed`» ВЕРНО: активность тогда не мог
измерить никто, а «не измерено» не повод отдать карточку (инв. #17). ADR-721 дал прибор,
измерение состоялось — носителей ноль, — и ответ прибора прятался от вердикта.

Что проверяется, и почему в ОБЕ стороны
------------------------------------------------------------------------------
* метку измеренно не несёт никто ⇒ `stale`, то есть КАНДИДАТ НА РУЧНОЙ ПОДЪЁМ. Это
  предмет файла;
* `free` не говорится НИ НА ОДНОЙ сцене: новой двери к авто-захвату правка не открывает,
  `claim` без `--takeover` с письменной причиной по-прежнему отказывает;
* живой носитель метки ⇒ `claimed`, как после ADR-721. Без этой стороны правка была бы
  не защитой, а возвратом аварии #864;
* ось НЕ ИЗМЕРЕНА ⇒ третий исход `unchecked` и ни «ждать некого», ни «занята» (инв. #17);
* метки в записи НЕТ ⇒ всё байт в байт как до правки (это 190 из 192 захватов живого
  трекера, то есть почти всё поведение неизменно);
* захват СТАРШЕ бюджета работника ⇒ ось не решает НИ в одну сторону. Граница проверена
  с ДВУХ сторон — ровно на бюджете и одной секундой за ним;
* ось ЗАПУСКАТЕЛЯ измерила ЖИЗНЬ ⇒ она сильнее измеренного отсутствия соседней оси:
  карточка остаётся ЗАНЯТОЙ (иначе отдали бы работу из-под живого якоря);
* СЛАБЫЙ признак (обмолвка о карточке в свободном тексте) НЕ поднимается до находки
  никаким состоянием оси — починка #61 (`agent-weak-mention-locks-card-forever`) не
  отменяется;
* прозa вердикта называет ОБА измерения, а не одно: отчёт не вправе выдать вывод оси за
  замер pid, которого никто не делал.

Предпосылка про ОКНО названа, а не подразумевается
------------------------------------------------------------------------------
Окно свежести шага 0b (3.00ч) КОРОЧЕ бюджета работника (4.17ч) — это открытая находка
цикла #867 (карточка `inbox-okno-svezhesti-koroche-byudzheta-rabotni`). Следствие для
ЭТОГО файла: сцена «захват старше бюджета» внутри окна по умолчанию НЕДОСТИЖИМА, и
проверки границы зовутся с ПОДНЯТЫМ окном (`grace_hours=`). Соотношение закреплено
отдельной проверкой: разойдись оно в другую сторону — и две проверки границы молча
мерили бы не то, что обещают.

Время и живость — ВХОДЫ, а не окружение
------------------------------------------------------------------------------
Литеральных дат в файле нет: все отметки выведены из якоря `NOW`, он же передаётся
измерителю аргументом `now=`. Живость запускателя инъектируется (`ps=`), живость
работника — пробой (`worker=`). Сторож, спрашивающий настоящую ОС, менял бы вердикт от
того, кто сегодня занял номер (`.claude/rules/deployment.md` § «ЛИЧНОСТЬ ПРОЦЕССА»).
Контроль ЖИВЫМ носителем метки невозможен по ИЗМЕРЕННОЙ причине: прибор ищет метку в
выводе `ps -A -Ewww`, где окружение читается не у всех процессов (замер 14.10: 76 строк
из 644 на рабочем Маке), и у специально поднятого процесса её не видно.
"""
import importlib.util
import json
from datetime import timedelta, timezone
from pathlib import Path

import pytest

from spa_core.tests._freshness import now_utc

ROOT = Path(__file__).resolve().parents[2]

#: Якорь времени — РЕАЛЬНЫЕ часы, инъектированные измерителю: предмет файла — свежесть
#: захвата и бюджет работника, и литеральная дата начала бы падать от сдвига календаря,
#: а не от кода. Доли секунды отрезаны НАМЕРЕННО: отметки печатаются с точностью до
#: секунды (`_fmt_ts`), и у якоря с микросекундами обратный разбор даёт мгновение РАНЬШЕ
#: — проверка «ровно бюджет» мерила бы бюджет плюс доли секунды.
NOW = now_utc().replace(microsecond=0)

#: Ярлык и метка держателя из аварии 14.10 — дословно. Ярлык НАМЕРЕННО без токена `pid`:
#: это форма `SPA_SESSION_ID=cycle-$$`, и ровно на ней ось ЗАПУСКАТЕЛЯ неизмерима.
INCIDENT_LABEL = "cycle-79433"
INCIDENT_RUN_ID = "orchestrator-79433-0F38E743606F4B0686D460BA02840097"

#: Личность МОЕЙ сессии: чужие записи иначе опознались бы как свои (`selves`).
SELF_ANCHOR = (41868, (NOW - timedelta(hours=9)).astimezone().strftime(
    "%a %b %d %H:%M:%S %Y"))

#: Номер ЖИВОГО якоря чужой сессии. Литерал безопасен: живым процессом он не
#: притворяется — его живость ИНЪЕКТИРУЕТСЯ (`ALIVE` ниже), а не спрашивается у ОС.
FOREIGN_PID = 79433

DEAD = lambda pid: (1, "")                                           # noqa: E731

#: Проза сцены НАМЕРЕННО не содержит самих слов оси: иначе проверка поля прошла бы
#: подстрокой в прозе (ADR-333).
SCENE_WHY = "состояние носителя метки задано входом сцены"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load("_c868_card_claim", "scripts/check_card_claim.py")


@pytest.fixture(scope="module")
def lock():
    return _load("_c868_cycle_lock", "scripts/orchestrator_cycle_lock.py")


@pytest.fixture(scope="module")
def sibling(guard):
    return guard.load_sibling()


def _fmt(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ttl(lock):
    """Бюджет работника — У ПРИБОРА, а не литералом: копия разошлась бы молча."""
    return float(lock.DEFAULT_WORKER_TTL_SEC)


def _ask(axis, ttl):
    """Проба оси РАБОТНИКА: состояние — ВХОД сцены, а не живая ОС."""
    def _probe(run_id):
        if not str(run_id or "").strip():
            return "not_declared", "метки нет", None
        return axis, SCENE_WHY, ttl
    return _probe


def _card(tracker, *, age_s, run_id=INCIDENT_RUN_ID, status="in-progress"):
    """Карточка с захватом во frontmatter. Возраст задаётся ВХОДОМ."""
    at = _fmt(NOW - timedelta(seconds=age_s))
    rows = ["---\n", "trackerStatus:\n", "  type: inbox\n", "title: сцена\n",
            f"status: {status}\n", f"claimed_by: {INCIDENT_LABEL}\n",
            f"claimed_at: {at}\n"]
    if run_id:
        rows.append(f"claimed_run_id: {run_id}\n")
    rows += ["---\n", "\n## Тело\n\nстрока\n"]
    (tracker / "inbox-scene.md").write_text("".join(rows), encoding="utf-8")
    return at


def _journal(tmp_path, *, voice_age_s=None, weak_age_s=None):
    """Журнал сцены.

    `voice_age_s` — запись держателя с ЖИВЫМ якорем (ось ЗАПУСКАТЕЛЯ измерит ЖИЗНЬ).
    `weak_age_s` — СЛАБЫЙ признак: карточка упомянута только в тексте (ни поля `card:`,
    ни файла карточки во владении), то есть обмолвка, а не захват.
    """
    log = tmp_path / "session_changes.jsonl"
    rows = []
    if voice_age_s is not None:
        at = NOW - timedelta(seconds=voice_age_s)
        rows.append({
            "ts": _fmt(at), "session": INCIDENT_LABEL, "summary": "голос держателя",
            "files": [], "session_pid": FOREIGN_PID,
            # Старт РАНЬШЕ записи: иначе личность не признаётся (сужение соседа), и
            # сцена мерила бы отказ опознания вместо оси запускателя.
            "session_pid_start": (at - timedelta(hours=2)).astimezone().strftime(
                "%a %b %d %H:%M:%S %Y"),
        })
    if weak_age_s is not None:
        at = NOW - timedelta(seconds=weak_age_s)
        rows.append({
            "ts": _fmt(at), "session": "cycle-55555",
            "summary": "по дороге заглянул в inbox-scene, работы не брал",
            "files": ["/abs/tree/unrelated.py"], "verified": "",
            "session_run_id": "orchestrator-55555-WEAK",
        })
    log.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                   encoding="utf-8")
    return log


def _verdict(guard, sibling, tracker, log, axis, ttl, *, grace_hours=None,
             ps=DEAD):
    kwargs = {} if grace_hours is None else {"grace_hours": grace_hours}
    return guard.gather("inbox-scene", log=str(log), tracker_dir=str(tracker),
                        sibling=sibling, self_session="probe-c868", now=NOW,
                        ps=ps, self_anchor=SELF_ANCHOR, shared_trees=(),
                        worker=_ask(axis, ttl), **kwargs)


def _front(report):
    rows = [c for c in (report.get("claims") or [])
            if c.get("source") == "frontmatter"]
    assert len(rows) == 1, f"ожидалась ровно одна находка по frontmatter: {rows}"
    return rows[0]


@pytest.fixture()
def scene(tmp_path):
    tracker = tmp_path / "tracker"
    tracker.mkdir()
    return tracker


# ── ПРЕДМЕТ: измеренное отсутствие работника внутри окна ─────────────────────

def test_measured_absence_inside_the_window_is_stale(guard, lock, sibling, scene,
                                                     tmp_path):
    """Авария 14.10 19:45Z дословно: держатель мёртв, а карточка не отдаётся."""
    inside = guard.DEFAULT_GRACE_HOURS * 3600.0 / 2.0
    _card(scene, age_s=inside)
    rep = _verdict(guard, sibling, scene, _journal(tmp_path), guard.W_GONE, _ttl(lock))
    assert rep["verdict"] == guard.STALE, rep
    rec = _front(rep)
    assert rec["state"] == "stale"
    # Предпосылка сцены — ВНУТРИ окна и БЕЗ измерения смерти запускателем: иначе
    # вердикт пришёл бы от ветки, закрытой задолго до этой правки.
    assert rec["fresh"] is True
    assert rec["orphaned"] is False


def test_measured_absence_never_says_free(guard, lock, sibling, scene, tmp_path):
    """`stale` — кандидат на РУЧНОЙ подъём; авто-захвата правка не открывает."""
    inside = guard.DEFAULT_GRACE_HOURS * 3600.0 / 2.0
    _card(scene, age_s=inside)
    rep = _verdict(guard, sibling, scene, _journal(tmp_path), guard.W_GONE, _ttl(lock))
    assert rep["verdict"] != guard.FREE, rep
    assert rep["claims"], "находка обязана остаться находкой, а не исчезнуть"


def test_the_absence_finding_carries_the_axis_as_a_field(guard, lock, sibling, scene,
                                                         tmp_path):
    """Ответ обязан быть ПОЛЕМ, а не прозой: разбор подстрокой запрещён (ADR-333)."""
    inside = guard.DEFAULT_GRACE_HOURS * 3600.0 / 2.0
    _card(scene, age_s=inside)
    rec = _front(_verdict(guard, sibling, scene, _journal(tmp_path), guard.W_GONE,
                          _ttl(lock)))
    assert rec["worker_axis"] == guard.W_GONE
    assert rec["worker_run_id"] == INCIDENT_RUN_ID
    assert rec["worker_over_budget"] is False
    assert guard.W_GONE not in str(rec["worker_detail"])


def test_the_absence_verdict_names_both_axes(guard, lock, sibling, scene, tmp_path):
    """Отчёт не вправе выдать вывод оси за замер pid, которого никто не делал.

    Каждое утверждение прозы — отдельное: что измерила ось РАБОТНИКА, что НЕ смогла
    измерить ось ЗАПУСКАТЕЛЯ, что ждать здесь НЕКОГО (это не «не измерено», а снятый
    замер), в каком СРОКЕ это верно и каким порядком карточка поднимается. Мутант,
    стирающий любое из них, обязан быть убит: иначе читатель получает вердикт без
    основания, а основание — единственное, чем он может его поверить."""
    inside = guard.DEFAULT_GRACE_HOURS * 3600.0 / 2.0
    _card(scene, age_s=inside)
    rec = _front(_verdict(guard, sibling, scene, _journal(tmp_path), guard.W_GONE,
                          _ttl(lock)))
    why = str(rec["session_state"])
    assert SCENE_WHY in why, f"измерение оси РАБОТНИКА не названо: {why}"
    assert "не измерена" in why, f"неизмеримость оси ЗАПУСКАТЕЛЯ не названа: {why}"
    assert "НЕКОГО" in why, f"вывод «ждать некого» не назван: {why}"
    assert f"{_ttl(lock) / 3600.0:.2f}" in why, f"срок, в котором вывод верен, не назван: {why}"
    assert "--takeover" in why, f"порядок подъёма не назван: {why}"


# ── ОБРАТНЫЕ СТОРОНЫ: каждое звено порвано отдельно и НАЗВАНО ───────────────

def test_live_worker_inside_the_window_still_holds_the_card(guard, lock, sibling,
                                                            scene, tmp_path):
    """Порвано звено «живой носитель держит» ⇒ возврат аварии #864 (ADR-721)."""
    inside = guard.DEFAULT_GRACE_HOURS * 3600.0 / 2.0
    _card(scene, age_s=inside)
    rep = _verdict(guard, sibling, scene, _journal(tmp_path), guard.W_ALIVE, _ttl(lock))
    assert rep["verdict"] == guard.CLAIMED, rep
    assert _front(rep)["state"] == "fresh"


def test_unmeasured_axis_inside_the_window_stays_unchecked(guard, lock, sibling,
                                                           scene, tmp_path):
    """Порвано звено «третий исход» ⇒ неизмеримость выдана за ответ (инв. #17)."""
    inside = guard.DEFAULT_GRACE_HOURS * 3600.0 / 2.0
    _card(scene, age_s=inside)
    rep = _verdict(guard, sibling, scene, _journal(tmp_path), guard.W_UNMEASURED,
                   _ttl(lock))
    assert rep["verdict"] == guard.UNCHECKED, rep
    assert rep["unmeasured"], "причина третьего исхода обязана быть НАЗВАНА"


def test_claim_without_the_mark_behaves_exactly_as_before(guard, lock, sibling, scene,
                                                          tmp_path):
    """Порвано звено «правка дополняющая» ⇒ меняется 190 захватов из 192."""
    inside = guard.DEFAULT_GRACE_HOURS * 3600.0 / 2.0
    _card(scene, age_s=inside, run_id=None)
    rep = _verdict(guard, sibling, scene, _journal(tmp_path), guard.W_GONE, _ttl(lock))
    assert rep["verdict"] == guard.CLAIMED, rep
    rec = _front(rep)
    assert rec["worker_axis"] == guard.W_NOT_DECLARED
    assert rec["state"] == "fresh"


def test_the_live_launcher_axis_outranks_the_absent_worker(guard, lock, sibling, scene,
                                                           tmp_path):
    """Порвано звено `state != ACTIVE` ⇒ карточка отдана из-под ЖИВОГО якоря.

    Якорь жив И сессия подавала голос в окне — это ровно та сцена, где измеренная ЖИЗНЬ
    обязана быть сильнее измеренного отсутствия соседней оси."""
    inside = guard.DEFAULT_GRACE_HOURS * 3600.0 / 2.0
    _card(scene, age_s=inside)
    log = _journal(tmp_path, voice_age_s=inside)
    start = (NOW - timedelta(seconds=inside) - timedelta(hours=2)).astimezone().strftime(
        "%a %b %d %H:%M:%S %Y")
    rep = _verdict(guard, sibling, scene, log, guard.W_GONE, _ttl(lock),
                   ps=lambda _pid: (0, start))
    assert rep["verdict"] == guard.CLAIMED, rep


def test_a_weak_mention_is_not_promoted_by_the_absent_worker(guard, lock, sibling,
                                                             scene, tmp_path):
    """Порвано звено `strength == STRONG` ⇒ обмолвка снова запирает карточку (#61).

    Карточка БЕЗ захвата, а в журнале — упоминание её идентификатора в свободном тексте.
    Это слабый признак, и он обязан остаться ИСТОРИЕЙ при ЛЮБОМ состоянии оси."""
    (scene / "inbox-scene.md").write_text(
        "---\ntrackerStatus:\n  type: inbox\ntitle: сцена\nstatus: in-progress\n"
        "---\n\n## Тело\n\nстрока\n", encoding="utf-8")
    inside = guard.DEFAULT_GRACE_HOURS * 3600.0 / 2.0
    log = _journal(tmp_path, weak_age_s=inside)
    rep = _verdict(guard, sibling, scene, log, guard.W_GONE, _ttl(lock))
    assert rep["verdict"] == guard.FREE, rep
    assert not rep["claims"], "обмолвка поднята до находки — починка #61 отменена"
    assert rep["history"], "обмолвка обязана остаться в истории"


# ── ГРАНИЦА БЮДЖЕТА: с ДВУХ сторон, и с НАЗВАННОЙ предпосылкой ──────────────

def test_the_default_window_is_shorter_than_the_worker_budget(guard, lock):
    """ПРЕДПОСЫЛКА двух проверок ниже, названная вслух (находка #867).

    Окно свежести (3.00ч) короче бюджета работника (4.17ч) ⇒ сцена «захват старше
    бюджета» на умолчаниях НЕДОСТИЖИМА: такой захват не свеж, и вердикт приходит от
    другой ветки. Поэтому границы бюджета меряются с ПОДНЯТЫМ окном. Разойдись
    соотношение в другую сторону — и две проверки ниже мерили бы не то, что обещают,
    молча (карточка `inbox-okno-svezhesti-koroche-byudzheta-rabotni`)."""
    assert guard.DEFAULT_GRACE_HOURS * 3600.0 < _ttl(lock)


def test_exactly_at_the_worker_budget_the_axis_still_decides(guard, lock, sibling,
                                                             scene, tmp_path):
    """Сравнение СТРОГОЕ: ровно бюджет — ещё не «старше бюджета»."""
    ttl = _ttl(lock)
    _card(scene, age_s=ttl)
    grace = ttl / 3600.0 + 1.0            # окно ПОДНЯТО: см. предпосылку выше
    rep = _verdict(guard, sibling, scene, _journal(tmp_path), guard.W_GONE, ttl,
                   grace_hours=grace)
    assert rep["verdict"] == guard.STALE, rep
    assert _front(rep)["worker_over_budget"] is False


def test_one_second_past_the_budget_the_axis_does_not_decide(guard, lock, sibling,
                                                             scene, tmp_path):
    """За своим сроком ось не решает НИ в одну сторону — иначе она вечный замок."""
    ttl = _ttl(lock)
    _card(scene, age_s=ttl + 1.0)
    grace = ttl / 3600.0 + 1.0
    rep = _verdict(guard, sibling, scene, _journal(tmp_path), guard.W_GONE, ttl,
                   grace_hours=grace)
    rec = _front(rep)
    assert rec["worker_over_budget"] is True
    # Вердикт приходит от ветки свежести, а не от оси: внутри поднятого окна свежий
    # СИЛЬНЫЙ захват без измеренной смерти запускателя по-прежнему блокирует.
    assert rep["verdict"] == guard.CLAIMED, rep
    assert rec["state"] == "fresh"


# ── ТЕРМИНАЛЬНЫЙ СТАТУС: правка не оживляет закрытую карточку ───────────────

def test_a_terminal_card_is_not_resurrected_by_the_axis(guard, lock, sibling, scene,
                                                        tmp_path):
    """Захват на закрытой карточке не действует — ни одной осью."""
    inside = guard.DEFAULT_GRACE_HOURS * 3600.0 / 2.0
    _card(scene, age_s=inside, status="done")
    rep = _verdict(guard, sibling, scene, _journal(tmp_path), guard.W_GONE, _ttl(lock))
    assert rep["verdict"] == guard.FREE, rep
    assert not rep["claims"]
