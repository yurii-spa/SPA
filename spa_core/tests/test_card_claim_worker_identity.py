"""ЗАХВАТ КАРТОЧКИ обязан мерить РАБОТНИКА, а не запускателя (цикл #865, ADR-721).

Живая авария, ради которой правка и сделана
------------------------------------------------------------------------------
Замер 14.10 (цикл #864, ADR-720), дословно — одна карточка, один день:

    claimed_by в карточке приказа Portfolio CIO   cycle-69075
    pid 69075 (ЗАПУСКАТЕЛЬ цикла #863)            МЁРТВ (`ps -p` rc=1)
    его РАБОТНИК, `claude` pid 69661              ЖИВ, ppid=1, pgid=sid=69661
    что работник делал                            правил /tmp/spa_c863/spa_core/tests/*
                                                   за 4 с до замера
    вердикт шага 0a-ГОЛОД                          `stale` — «держателя НЕТ»

То есть голодающий ПРИКАЗ ВЛАДЕЛЬЦА был выдан ВТОРОЙ сессии, пока первая его
исполняла. Корень один: ярлык сессии производен от pid ЗАПУСКАТЕЛЯ
(`SPA_SESSION_ID=cycle-$$` в `agent_orchestrator.sh`), а работу делает работник,
поднятый `start_new_session=True`, — он ЛИДЕР СВОЕЙ СЕССИИ и переживает запускателя
по построению. ADR-720 закрыл эту ось у ЗАМКА цикла; вторая защита — захват карточки —
осталась на прежней, мёртвой оси.

Что проверяется, и почему в ОБЕ стороны
------------------------------------------------------------------------------
* ось РАБОТНИКА жива ⇒ `claimed` («ЗАНЯТА»), подъём запрещён — это и есть защита;
* ось РАБОТНИКА измеренно пуста ⇒ `stale`, карточка отдаётся, как и раньше. Без этой
  стороны правка была бы не защитой, а вечным замком;
* ось НЕ ИЗМЕРЕНА (окружение процессов не читается, прибор не ввезён) ⇒ третий исход
  `unchecked`, и он НЕ выдаётся ни за «держателя нет», ни за «занята» (инв. #17);
* метки нет (карточка старого образца) ⇒ всё как до правки, байт в байт;
* захват СТАРШЕ бюджета работника ⇒ ось не решает: повисший работник не вправе запирать
  очередь дольше своего срока (то же рассуждение, что у `worker_ttl` ADR-720).
  Граница проверена с ДВУХ сторон одной секундой.

Время и живость — ВХОДЫ, а не окружение
------------------------------------------------------------------------------
Литеральных дат в файле нет: все отметки выведены из якоря `NOW`, он же передаётся
измерителю аргументом `now=`. Живость запускателя инъектируется (`ps=`), живость
работника — пробой (`worker=`): сторож, спрашивающий настоящую ОС, менял бы вердикт от
того, кто сегодня занял номер (`.claude/rules/deployment.md` § «ЛИЧНОСТЬ ПРОЦЕССА»).

ОГОВОРКА, ИЗМЕРЕННАЯ ЗДЕСЬ ЖЕ, и почему контроль живым процессом НЕВОЗМОЖЕН: прибор
ищет метку в выводе `ps -A -Ewww`, а окружение там читается не у всех процессов
(замер на этом Маке: 74 строки из 644). Поднятый специально `/bin/sleep` с меткой в
окружении в `ps -E` её НЕ показывает — то есть «живой носитель метки» сценой не
воспроизводится, зато у настоящего работника (`claude`) метка видна (замер: 4 живых
pid). Поэтому ось инъектируется, а её неизмеримость — отдельный проверяемый исход.
"""
import importlib.util
import json
import os
from datetime import timedelta, timezone
from pathlib import Path

import pytest

from spa_core.tests._freshness import now_utc

ROOT = Path(__file__).resolve().parents[2]

#: Якорь времени — РЕАЛЬНЫЕ часы, а не литеральная дата: предмет файла — свежесть
#: захвата и бюджет работника, и литерал начал бы падать от сдвига календаря, а не от
#: кода. Часы ИНЪЕКТИРОВАНЫ: обе стороны сравнения выведены из этого якоря.
#: Пометки `injected-clock` здесь НЕТ намеренно: оправдывать нечего — литеральной даты
#: в файле нет ни одной, а записка без якоря была бы претензией без предмета (сторож
#: претензии `test_injected_clock_claim.py` меряет её по AST и честно сказал бы
#: «НЕ ИЗМЕРЕНО»).
#:
#: Доли секунды отрезаны НАМЕРЕННО, и это предпосылка, а не косметика: отметки карточки
#: печатаются с точностью до секунды (`_fmt_ts`), поэтому у якоря с микросекундами
#: обратный разбор даёт мгновение РАНЬШЕ — и проверка границы бюджета «ровно ttl»
#: мерила бы ttl+0.9с, то есть совсем другое утверждение.
NOW = now_utc().replace(microsecond=0)

#: Ярлык и метка из аварии 14.10 — дословно (ярлык производен от pid ЗАПУСКАТЕЛЯ).
INCIDENT_LABEL = "cycle-69075"
INCIDENT_RUN_ID = "orchestrator-69075-7F3C1A0B4E5D4A2C9B8E6D1F0A3C5E79"

#: Якорь личности сцены: пара (номер, «старт verbatim»). Номер литеральный безопасно —
#: живым процессом он не притворяется, его сравнивают только с такими же парами внутри
#: сцены. Время старта литералом НЕ пишется: оно выведено из `NOW`.
SELF_START = (NOW - timedelta(hours=9)).astimezone().strftime("%a %b %d %H:%M:%S %Y")
SELF_ANCHOR = (41865, SELF_START)

DEAD = lambda pid: (1, "")                                           # noqa: E731


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load("_c865_card_claim", "scripts/check_card_claim.py")


@pytest.fixture(scope="module")
def lock():
    return _load("_c865_cycle_lock", "scripts/orchestrator_cycle_lock.py")


@pytest.fixture(scope="module")
def sibling(guard):
    return guard.load_sibling()


@pytest.fixture()
def tracker(tmp_path):
    d = tmp_path / "tracker"
    d.mkdir()
    return d


@pytest.fixture()
def log(tmp_path):
    """Пустой журнал объявлений: ось ЗАПУСКАТЕЛЯ не подтверждает жизнь ничем.

    Это дословное состояние живой очереди: ярлык вида `cycle-69075` pid в себе НЕ несёт
    (`pid_from_label` его не достаёт), поэтому захват таких держателей и уходит в `stale`
    по ADR-647 — «личность не объявлена НИГДЕ, ждать НЕКОГО». Ровно тот вердикт, который
    14.10 выдал ЖИВОЙ приказ владельца второй сессии.
    """
    p = tmp_path / "session_changes.jsonl"
    p.write_text("", encoding="utf-8")
    return p


@pytest.fixture()
def dead_launcher_log(tmp_path):
    """Вторая дорога оси ЗАПУСКАТЕЛЯ: его смерть ИЗМЕРЕНА, а не просто не объявлена.

    Запись делается тем же полем, что пишет `log_session_change.durable_process`, а
    живость её pid инъектируется (`ps=DEAD`). Две дороги к `stale` проверяются обе:
    у правки не должно быть пути, на котором живой работник не перебивает мёртвого
    запускателя.
    """
    p = tmp_path / "session_changes_dead.jsonl"
    p.write_text(json.dumps({
        "ts": _fmt(NOW - timedelta(hours=STALE_AGE_H)),
        "session": INCIDENT_LABEL,
        "summary": "[check_card_claim] захват карточки inbox-prikaz",
        "files": [], "card": "inbox-prikaz", "card_state": "claim",
        "session_pid": 69075,
        "session_pid_start": (NOW - timedelta(hours=5)).astimezone().strftime(
            "%a %b %d %H:%M:%S %Y"),
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def _fmt(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


#: Возраст захвата по умолчанию — СТАРШЕ окна свежести шага 0b (3ч), как в аварии 14.10:
#: захват 09:40:50Z, замер 12:47Z. Внутри окна СИЛЬНЫЙ захват блокирует и без оси
#: РАБОТНИКА (`claimed`), то есть сцена отвечала бы на другой вопрос.
STALE_AGE_H = 3.5


def _card(tracker, *, holder: "str | None" = INCIDENT_LABEL, age_h=STALE_AGE_H,
          age_s: "float | None" = None, run_id: "str | None" = INCIDENT_RUN_ID,
          status="in-progress", cid="inbox-prikaz"):
    """Карточка с захватом во frontmatter. `run_id=None` — запись СТАРОГО образца.

    `age_s` — возраст захвата в СЕКУНДАХ, и он не роскошь: граница бюджета сравнивается
    в секундах, а `ttl/3600 * 3600` в двоичной арифметике даёт 15000.000000000002, то
    есть «ровно бюджет» превращалось бы в «бюджет плюс чуть-чуть» — проверка границы
    отвечала бы не на свой вопрос.
    """
    lines = ["---\n", "trackerStatus:\n", "  type: inbox\n",
             "title: Приказ владельца\n", f"status: {status}\n", "priority: critical\n"]
    if holder:
        lines.append(f"claimed_by: {holder}\n")
        delta = (timedelta(seconds=age_s) if age_s is not None
                 else timedelta(hours=age_h))
        lines.append(f"claimed_at: {_fmt(NOW - delta)}\n")
        if run_id:
            lines.append(f"claimed_run_id: {run_id}\n")
    lines += ["---\n", "\n## Тело\n\nстрока\n"]
    p = tracker / f"{cid}.md"
    p.write_text("".join(lines), encoding="utf-8")
    return p


#: Бюджет работника берётся У ПРИБОРА, а не литералом: порог «сколько работник вправе
#: держать карточку» обязан быть ОДНИМ числом с тем, по которому таймаут прогона
#: работника его завершает. Литерал здесь разошёлся бы с ним молча.
def _ttl(lock):
    return float(lock.DEFAULT_WORKER_TTL_SEC)


def _probe(axis, ttl, *, calls=None, why=None):
    """Проба оси РАБОТНИКА как ВХОД. `calls` — список, куда пишутся запрошенные метки."""
    def _ask(run_id):
        if calls is not None:
            calls.append(run_id)
        if not str(run_id or "").strip():
            return "not_declared", "метки нет — ось НЕ МЕРИЛАСЬ", None
        return axis, why or f"сцена: ось РАБОТНИКА = {axis}", ttl
    return _ask


def _verdict(guard, sibling, tracker, log, *, worker=None, now=None):
    return guard.gather("inbox-prikaz", log=log, tracker_dir=tracker, sibling=sibling,
                        self_session="cycle-865", now=now or NOW, ps=DEAD,
                        self_anchor=SELF_ANCHOR, shared_trees=(), worker=worker)


def _front(report):
    rows = [c for c in report["claims"] if c["source"] == "frontmatter"]
    assert len(rows) == 1, f"ожидалась ровно одна находка по frontmatter, получено: {rows}"
    return rows[0]


# ── ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: дословная сцена 14.10 ───────────────────────────────


def test_a_live_worker_holds_the_card_even_though_the_launcher_is_dead(
        guard, lock, sibling, tracker, log):
    """Авария 14.10: запускатель МЁРТВ, работник ЖИВ ⇒ `claimed`, а не `stale`.

    Это звено и есть предмет карточки: до правки тот же вход давал `stale` «держателя
    НЕТ», и шаг 0a-ГОЛОД выдавал живой приказ владельца второй сессии.
    """
    _card(tracker)
    report = _verdict(guard, sibling, tracker, log,
                      worker=_probe(guard.W_ALIVE, _ttl(lock)))
    assert report["verdict"] == guard.CLAIMED, (
        f"вердикт {report['verdict']!r}: живая работа снова отдаётся второй сессии; "
        f"находки: {report['claims']}, не измерено: {report['unmeasured']}")
    rec = _front(report)
    assert rec["state"] == "fresh", rec
    assert rec["worker_axis"] == guard.W_ALIVE, rec
    assert rec["worker_run_id"] == INCIDENT_RUN_ID, rec
    assert rec["worker_over_budget"] is False, rec


def test_the_worker_wins_over_a_launcher_whose_death_is_measured(
        guard, lock, sibling, tracker, dead_launcher_log):
    """Вторая дорога к `stale`: смерть запускателя ИЗМЕРЕНА (`durable_process_gone`).

    Дорог две, и обе обязаны уступать живому работнику. Проверено и наоборот: без оси
    РАБОТНИКА эта же сцена остаётся `stale` — то есть сцена различает правку, а не
    зеленеет сама по себе.
    """
    _card(tracker)
    alive = _verdict(guard, sibling, tracker, dead_launcher_log,
                     worker=_probe(guard.W_ALIVE, _ttl(lock)))
    assert alive["verdict"] == guard.CLAIMED, alive["verdict"]
    assert _front(alive)["worker_axis"] == guard.W_ALIVE
    gone = _verdict(guard, sibling, tracker, dead_launcher_log,
                    worker=_probe(guard.W_GONE, _ttl(lock)))
    assert gone["verdict"] == guard.STALE, gone["verdict"]
    assert _front(gone)["orphaned"] is True, _front(gone)


def test_the_verdict_says_which_axis_spoke_and_which_one_died(guard, lock, sibling,
                                                              tracker, log):
    """Исход обязан НАЗВАТЬ обе оси: мёртвый запускатель и живого работника.

    Иначе `claimed` здесь неотличим от `claimed` по живому запускателю — а это разные
    утверждения, и читателю нечем проверить вывод.
    """
    _card(tracker)
    rec = _front(_verdict(guard, sibling, tracker, log,
                          worker=_probe(guard.W_ALIVE, _ttl(lock))))
    why = rec["session_state"]
    assert "ось ЗАПУСКАТЕЛЯ" in why, why
    assert "ось РАБОТНИКА" in why, why
    assert "подъём запрещён" in why, why
    # Бюджет назван ЧИСЛОМ, а не словом «бюджет»: читателю нужен порог, по которому
    # карточка освободится сама, иначе отказ выглядит бессрочным.
    assert f"{_ttl(lock) / 3600.0:.2f}ч" in why, why


def test_takeover_is_refused_while_the_worker_is_alive(guard, lock, sibling, tracker,
                                                       log, monkeypatch):
    """ДЕНЬГИ правки: `claim --takeover` на живом работнике ОТКАЗЫВАЕТ.

    Подъём разрешён только на `stale`; стал `claimed` — значит кражи работы не будет
    даже с письменной причиной.
    """
    monkeypatch.setenv("SPA_SESSION_ID", "cycle-865")
    card = _card(tracker)
    before = card.read_text(encoding="utf-8")
    with pytest.raises(guard.ClaimError) as exc:
        guard.claim_card("inbox-prikaz", log=log, session="cycle-865",
                         tracker_dir=tracker, now=NOW, sibling=sibling, ps=DEAD,
                         self_anchor=SELF_ANCHOR,
                         worker=_probe(guard.W_ALIVE, _ttl(lock)),
                         takeover_reason="сверил шагом 0a: работы в деревьях нет")
    assert "claimed" in str(exc.value)
    assert card.read_text(encoding="utf-8") == before, "карточка изменена при отказе"


# ── ОБРАТНАЯ СТОРОНА: работника НЕТ ⇒ карточка отдаётся, как и раньше ────────────


def test_a_measured_absence_of_the_worker_still_hands_the_card_over(
        guard, lock, sibling, tracker, log):
    """Ось РАБОТНИКА измеренно пуста ⇒ `stale`: правка не стала вечным замком."""
    _card(tracker)
    report = _verdict(guard, sibling, tracker, log,
                      worker=_probe(guard.W_GONE, _ttl(lock)))
    assert report["verdict"] == guard.STALE, (
        f"вердикт {report['verdict']!r} при измеренно мёртвом работнике — "
        f"не измерено: {report['unmeasured']}")
    rec = _front(report)
    assert rec["state"] == "stale", rec
    assert rec["worker_axis"] == guard.W_GONE, rec


def test_takeover_succeeds_once_the_worker_is_measurably_gone(guard, lock, sibling,
                                                              tracker, log, monkeypatch):
    """На той же сцене, но без работника, подъём проходит и доезжает до КАРТОЧКИ."""
    monkeypatch.setenv("SPA_SESSION_ID", "cycle-865")
    monkeypatch.setenv(guard.RUN_ID_VAR, "orchestrator-865-NEWMARK")
    card = _card(tracker)
    out = guard.claim_card("inbox-prikaz", log=log, session="cycle-865",
                           tracker_dir=tracker, now=NOW, sibling=sibling, ps=DEAD,
                           self_anchor=SELF_ANCHOR,
                           worker=_probe(guard.W_GONE, _ttl(lock)),
                           takeover_reason="сверил шагом 0a: работы в деревьях нет")
    assert out["claimed_by"] == "cycle-865"
    assert INCIDENT_LABEL in out["takeover_from"]
    text = card.read_text(encoding="utf-8")
    assert "claimed_by: cycle-865" in text
    # Чужая метка не уцелела: иначе следующий читатель принял бы мёртвого работника
    # предыдущего держателя за живого — ложная занятость, но всё равно ложь.
    assert INCIDENT_RUN_ID not in text, text
    assert "claimed_run_id: orchestrator-865-NEWMARK" in text, text


# ── ТРЕТИЙ ИСХОД: ось НЕ ИЗМЕРЕНА (инв. #17) ────────────────────────────────────


def test_an_unmeasured_worker_axis_is_not_an_absent_holder(guard, lock, sibling,
                                                           tracker, log):
    """Окружение не читается ⇒ `unchecked`, и ни «занята», ни «держателя нет»."""
    _card(tracker)
    report = _verdict(guard, sibling, tracker, log,
                      worker=_probe(guard.W_UNMEASURED, _ttl(lock),
                                    why="окружение не читается ни у одного процесса"))
    assert report["verdict"] == guard.UNCHECKED, (
        f"вердикт {report['verdict']!r}: неизмеримость выдана за ответ; "
        f"находки: {report['claims']}")
    assert report["unmeasured"], report
    reason = " ".join(u["reason"] for u in report["unmeasured"])
    assert "НЕ ИЗМЕРЕНА" in reason, reason
    assert INCIDENT_RUN_ID in reason, reason
    assert "инв. #17" in reason, reason


def test_an_unmeasured_axis_refuses_the_takeover_too(guard, lock, sibling, tracker, log,
                                                     monkeypatch):
    """`unchecked` подъём не снимает — это прежнее правило, и оно не ослаблено."""
    monkeypatch.setenv("SPA_SESSION_ID", "cycle-865")
    card = _card(tracker)
    before = card.read_text(encoding="utf-8")
    with pytest.raises(guard.ClaimError):
        guard.claim_card("inbox-prikaz", log=log, session="cycle-865",
                         tracker_dir=tracker, now=NOW, sibling=sibling, ps=DEAD,
                         self_anchor=SELF_ANCHOR,
                         worker=_probe(guard.W_UNMEASURED, _ttl(lock)),
                         takeover_reason="сверил руками")
    assert card.read_text(encoding="utf-8") == before


def test_a_missing_instrument_is_named_but_does_not_lock_the_queue_forever(
        guard, sibling, tracker, log):
    """Прибора нет ⇒ бюджета нет ⇒ ось НАЗВАНА `unmeasured`, но вердикт прежний.

    Неограниченный отказ — ровно та вечная блокировка, которую этот сторож снимал
    трижды (#61 слабое упоминание, #412 живой якорь, #803 безымянный захват). Поэтому
    без бюджета ось говорит вслух и не решает: сказать — обязана, запирать навсегда —
    нет.
    """
    _card(tracker)
    report = _verdict(guard, sibling, tracker, log,
                      worker=_probe(guard.W_UNMEASURED, None,
                                    why="прибор оси РАБОТНИКА не ввезён"))
    assert report["verdict"] == guard.STALE, report["verdict"]
    rec = _front(report)
    assert rec["worker_axis"] == guard.W_UNMEASURED, rec
    assert rec["worker_over_budget"] is None, rec
    assert "не ввезён" in rec["worker_detail"], rec


def test_measure_worker_reports_the_missing_instrument_as_the_third_outcome(guard):
    """Та же неизмеримость — у САМОГО прибора, а не только у его вызывающего."""
    def _boom(_path):
        raise ImportError("нет прибора оси РАБОТНИКА: /nope/orchestrator_cycle_lock.py")

    axis, why, ttl = guard.measure_worker("orchestrator-1-ABC", loader=_boom)
    assert axis == guard.W_UNMEASURED, (axis, why)
    assert ttl is None, ttl
    assert "НЕ ИЗМЕРЕНА" in why, why


# ── ОСЬ НЕ ОБЪЯВЛЕНА: прежнее поведение, байт в байт ────────────────────────────


def test_a_card_without_the_mark_behaves_exactly_as_before(guard, lock, sibling,
                                                           tracker, log):
    """Запись старого образца ⇒ `not_declared`, решает ось ЗАПУСКАТЕЛЯ.

    И про живость работника при этом НЕ СПРАШИВАЮТ: вопрос без предмета получил бы
    ответ «работника нет», то есть неизмеримость превратилась бы в измерение.
    """
    _card(tracker, run_id=None)
    calls = []
    report = _verdict(guard, sibling, tracker, log,
                      worker=_probe(guard.W_ALIVE, _ttl(lock), calls=calls))
    assert report["verdict"] == guard.STALE, report["verdict"]
    rec = _front(report)
    assert rec["worker_axis"] == guard.W_NOT_DECLARED, rec
    assert rec["worker_run_id"] is None, rec
    assert [c for c in calls if str(c or "").strip()] == [], calls


def test_the_old_format_verdict_is_byte_identical_to_the_axis_being_absent(
        guard, lock, sibling, tracker, log):
    """Сцена без метки и сцена с НЕДОСТУПНЫМ прибором дают один и тот же текст отказа.

    Утверждение сильное намеренно: «правка строго дополняющая» проверяется сравнением
    прозы, а не обещанием в комментарии.
    """
    _card(tracker, run_id=None)
    a = _front(_verdict(guard, sibling, tracker, log,
                        worker=_probe(guard.W_ALIVE, _ttl(lock))))["session_state"]
    _card(tracker, run_id=INCIDENT_RUN_ID)
    b = _front(_verdict(guard, sibling, tracker, log,
                        worker=_probe(guard.W_UNMEASURED, None)))["session_state"]
    assert a == b, f"ось без предмета изменила текст отказа:\n{a!r}\n{b!r}"


# ── ГРАНИЦА БЮДЖЕТА РАБОТНИКА: обе стороны одной секундой ───────────────────────


def test_the_worker_holds_the_card_right_up_to_its_budget(guard, lock, sibling,
                                                          tracker, log):
    """Захват РОВНО возрастом бюджета — ещё держит (`<=`, как у замка)."""
    ttl = _ttl(lock)
    _card(tracker, age_s=ttl)
    report = _verdict(guard, sibling, tracker, log, worker=_probe(guard.W_ALIVE, ttl))
    assert report["verdict"] == guard.CLAIMED, report["verdict"]
    assert _front(report)["worker_over_budget"] is False


def test_a_hung_worker_does_not_lock_the_queue_past_its_budget(guard, lock, sibling,
                                                               tracker, log):
    """Секундой позже бюджета ось не решает ⇒ карточка снова берётся подъёмом.

    Это п. 4 карточки: границы, чтобы не заморозить очередь. Без неё повисший работник
    держал бы приказ владельца вечно — и мы заменили бы одну аварию другой.
    """
    ttl = _ttl(lock)
    _card(tracker, age_s=ttl + 1.0)
    report = _verdict(guard, sibling, tracker, log, worker=_probe(guard.W_ALIVE, ttl))
    assert report["verdict"] == guard.STALE, report["verdict"]
    rec = _front(report)
    assert rec["worker_over_budget"] is True, rec
    # Ось всё равно НАЗВАНА: «живой работник за бюджетом» и «работника нет» — разные
    # факты, и читателю видно, какой из них перед ним.
    assert rec["worker_axis"] == guard.W_ALIVE, rec


def test_an_unmeasured_axis_past_the_budget_stops_blocking_too(guard, lock, sibling,
                                                               tracker, log):
    """И неизмеримость ограничена сроком: за бюджетом она больше не даёт `unchecked`."""
    ttl = _ttl(lock)
    _card(tracker, age_s=ttl + 1.0)
    report = _verdict(guard, sibling, tracker, log,
                      worker=_probe(guard.W_UNMEASURED, ttl))
    assert report["verdict"] == guard.STALE, report["verdict"]
    assert not report["unmeasured"], report["unmeasured"]


# ── ПИСАТЕЛЬ: метка попадает во frontmatter и снимается вместе с захватом ────────


def test_the_claim_writes_the_worker_mark_from_the_environment(guard, lock, sibling,
                                                               tracker, log, monkeypatch):
    """Читать ось нечем, если её никто не пишет: `claim` кладёт метку в карточку."""
    monkeypatch.setenv("SPA_SESSION_ID", "cycle-865")
    monkeypatch.setenv(guard.RUN_ID_VAR, "orchestrator-865-DEADBEEF")
    card = _card(tracker, holder=None)
    out = guard.claim_card("inbox-prikaz", log=log, session="cycle-865",
                           tracker_dir=tracker, now=NOW, sibling=sibling, ps=DEAD,
                           self_anchor=SELF_ANCHOR,
                           worker=_probe(guard.W_GONE, _ttl(lock)))
    assert out["worker_run_id"] == "orchestrator-865-DEADBEEF", out
    assert "claimed_run_id: orchestrator-865-DEADBEEF" in card.read_text(encoding="utf-8")


def test_without_the_environment_mark_the_field_is_absent_not_empty(guard, lock, sibling,
                                                                    tracker, log,
                                                                    monkeypatch):
    """Метки в окружении нет ⇒ поля НЕТ. Пустое значение превратило бы третий исход
    в молчание: читатель отличает «ось не мерилась» от «метку назвали» по НАЛИЧИЮ."""
    monkeypatch.setenv("SPA_SESSION_ID", "cycle-865")
    monkeypatch.delenv(guard.RUN_ID_VAR, raising=False)
    card = _card(tracker, holder=None)
    out = guard.claim_card("inbox-prikaz", log=log, session="cycle-865",
                           tracker_dir=tracker, now=NOW, sibling=sibling, ps=DEAD,
                           self_anchor=SELF_ANCHOR,
                           worker=_probe(guard.W_GONE, _ttl(lock)))
    assert out["worker_run_id"] is None, out
    assert "claimed_run_id" not in card.read_text(encoding="utf-8")


def test_releasing_the_card_removes_the_mark(guard, lock, sibling, tracker, log,
                                             monkeypatch):
    """Отпустили карточку — метки не остаётся: иначе на ней жил бы держатель без захвата."""
    monkeypatch.setenv("SPA_SESSION_ID", "cycle-865")
    monkeypatch.setenv(guard.RUN_ID_VAR, "orchestrator-865-DEADBEEF")
    card = _card(tracker, holder=None)
    guard.claim_card("inbox-prikaz", log=log, session="cycle-865", tracker_dir=tracker,
                     now=NOW, sibling=sibling, ps=DEAD, self_anchor=SELF_ANCHOR,
                     worker=_probe(guard.W_GONE, _ttl(lock)))
    guard.release_card("inbox-prikaz", log=log, session="cycle-865",
                       tracker_dir=tracker, sibling=sibling, self_anchor=SELF_ANCHOR)
    assert "claimed_run_id" not in card.read_text(encoding="utf-8")


# ── ОДНА КОПИЯ ПРИБОРА (а не второй расходящийся ответ на тот же вопрос) ────────


def test_the_mark_name_is_the_same_string_as_the_locks(guard, lock):
    """Имя переменной окружения сверено С ПРИБОРОМ, а не объявлено рядом.

    Разошлись бы — захват писал бы одну метку, а замок искал другую, и обе защиты
    молча перестали бы говорить об одном работнике.
    """
    assert guard.RUN_ID_VAR == lock.RUN_ID_VAR, (guard.RUN_ID_VAR, lock.RUN_ID_VAR)


def test_the_liveness_question_is_delegated_to_the_lock_not_reimplemented(guard, lock):
    """`measure_worker` спрашивает ИМЕННО `lock.worker_axis` и берёт бюджет оттуда же."""
    asked = []

    class _Fake:
        RUN_ID_KEY = lock.RUN_ID_KEY
        WORKER_ALIVE = lock.WORKER_ALIVE
        WORKER_GONE = lock.WORKER_GONE
        WORKER_UNMEASURED = lock.WORKER_UNMEASURED
        DEFAULT_WORKER_TTL_SEC = 1234.0

        @staticmethod
        def worker_axis(holder):
            asked.append(holder)
            return lock.WORKER_ALIVE, "подменённый прибор ответил"

    axis, why, ttl = guard.measure_worker("orchestrator-7-XYZ",
                                          loader=lambda _p: _Fake)
    assert asked == [{lock.RUN_ID_KEY: "orchestrator-7-XYZ"}], asked
    assert (axis, why, ttl) == (guard.W_ALIVE, "подменённый прибор ответил", 1234.0)


def _fake_lock(lock, answer, *, ttl=15000.0):
    """Подменённый прибор, отвечающий ЗАДАННЫМ состоянием из вокабуляра замка."""
    class _Fake:
        RUN_ID_KEY = lock.RUN_ID_KEY
        WORKER_ALIVE = lock.WORKER_ALIVE
        WORKER_GONE = lock.WORKER_GONE
        WORKER_UNMEASURED = lock.WORKER_UNMEASURED
        DEFAULT_WORKER_TTL_SEC = ttl

        @staticmethod
        def worker_axis(_holder):
            return answer, "подменённый прибор ответил"
    return _Fake


@pytest.mark.parametrize("answer_attr,expected_attr", [
    ("WORKER_ALIVE", "W_ALIVE"),
    ("WORKER_GONE", "W_GONE"),
    ("WORKER_UNMEASURED", "W_UNMEASURED"),
])
def test_every_state_of_the_instrument_maps_to_its_own_word(guard, lock, answer_attr,
                                                            expected_attr):
    """Перевод словаря ПРИБОРА в словарь ЧИТАТЕЛЯ проверен НА КАЖДОМ состоянии.

    Дыру нашёл контроль мутациями: мутант «`WORKER_GONE` переводится в `alive`» ВЫЖИЛ —
    все остальные звенья инъектируют ось готовым словом читателя и до перевода не
    доходят, а у `measure_worker` спрашивали только `alive` и незнакомое состояние.
    Цена мутанта реальная: измеренно мёртвый работник читался бы живым, то есть карточка
    запиралась бы на 4.17 ч без держателя.
    """
    answer = getattr(lock, answer_attr)
    expected = getattr(guard, expected_attr)
    axis, why, ttl = guard.measure_worker(
        "orchestrator-9-ZZZ", loader=lambda _p: _fake_lock(lock, answer))
    assert axis == expected, (answer_attr, axis, why)
    assert ttl == 15000.0, ttl


def test_an_unknown_answer_from_the_instrument_is_unmeasured_not_free(guard, lock):
    """Незнакомое состояние прибора ⇒ `unmeasured`. Перечень закрыт У ЧИТАТЕЛЯ."""
    class _Fake:
        RUN_ID_KEY = lock.RUN_ID_KEY
        WORKER_ALIVE = lock.WORKER_ALIVE
        WORKER_GONE = lock.WORKER_GONE
        WORKER_UNMEASURED = lock.WORKER_UNMEASURED
        DEFAULT_WORKER_TTL_SEC = 15000.0

        @staticmethod
        def worker_axis(_holder):
            return "worker_schroedinger", "состояние, которого читатель не знает"

    axis, _why, ttl = guard.measure_worker("orchestrator-7-XYZ", loader=lambda _p: _Fake)
    assert axis == guard.W_UNMEASURED, axis
    assert ttl == 15000.0


def test_the_readers_axis_vocabulary_is_closed_and_traversed(guard):
    """Вокабуляр оси собирается ОБХОДОМ и значение — его точный член (ADR-333).

    Проверка подстрокой здесь была бы бессмысленна: `alive` входит в `not_declared`?
    нет, но `gone` входит в прозу почти любого ответа. Поэтому сверяется ЧЛЕНСТВО.
    """
    names = {v for k, v in vars(guard).items()
             if k.startswith("W_") and isinstance(v, str)}
    assert names == set(guard.WORKER_AXES), (names, guard.WORKER_AXES)
    assert len(names) == 4, names


def test_the_axis_word_is_not_findable_in_the_prose_of_the_same_record(guard, lock,
                                                                      sibling, tracker,
                                                                      log):
    """Поле обязано НЕСТИ ответ, а не повторять его прозой: разбор подстрокой запрещён."""
    _card(tracker)
    rec = _front(_verdict(guard, sibling, tracker, log,
                          worker=_probe(guard.W_ALIVE, _ttl(lock),
                                        why="сцена: носитель метки жив")))
    assert rec["worker_axis"] == guard.W_ALIVE
    assert guard.W_ALIVE not in rec["worker_detail"], rec["worker_detail"]


# ── СОСЕДНИЕ СВОЙСТВА, КОТОРЫЕ ПРАВКА ОБЯЗАНА СОХРАНИТЬ ────────────────────────


def test_my_own_claim_is_still_not_a_finding(guard, lock, sibling, tracker, log):
    """Собственный захват остаётся собственным: ось РАБОТНИКА до него не доходит."""
    _card(tracker, holder="cycle-865")
    report = _verdict(guard, sibling, tracker, log,
                      worker=_probe(guard.W_ALIVE, _ttl(lock)))
    assert report["verdict"] == guard.FREE, report["verdict"]
    assert report["self_claims"], report
    assert not report["claims"], report["claims"]


def test_a_terminal_status_still_releases_the_card(guard, lock, sibling, tracker, log):
    """Закрытая карточка не «занята» живым работником: статус решает раньше оси."""
    _card(tracker, status="done")
    report = _verdict(guard, sibling, tracker, log,
                      worker=_probe(guard.W_ALIVE, _ttl(lock)))
    assert report["verdict"] == guard.FREE, report["verdict"]
    assert any(h.get("state") == "released" for h in report["history"]), report["history"]


def test_the_report_prints_the_worker_axis_even_when_it_changed_nothing(
        guard, lock, sibling, tracker, log):
    """Ось печатается и когда вердикта не изменила: молчание читалось бы как «чисто»."""
    _card(tracker)
    text = guard.render(_verdict(guard, sibling, tracker, log,
                                 worker=_probe(guard.W_GONE, _ttl(lock))))
    assert "ось РАБОТНИКА [gone]" in text, text
    _card(tracker, age_s=_ttl(lock) + 1.0)
    over = guard.render(_verdict(guard, sibling, tracker, log,
                                 worker=_probe(guard.W_ALIVE, _ttl(lock))))
    assert "СТАРШЕ бюджета работника" in over, over


def test_the_real_default_probe_is_the_one_used_without_injection(guard, tracker, log,
                                                                  sibling, monkeypatch):
    """Без инъекции зовётся НАСТОЯЩИЙ `measure_worker`, а не тишина.

    Проводка — отдельное утверждение от самой оси: у прибора может быть всё верно, а у
    умолчания — `None`, и тогда живой цикл мерил бы ось ровно никогда (урок #863 о
    звеньях, зелёных при полностью ослеплённом приборе).
    """
    seen = []

    def _spy(run_id, **kw):
        seen.append(run_id)
        return guard.W_GONE, "шпион ответил", 15000.0

    monkeypatch.setattr(guard, "measure_worker", _spy)
    _card(tracker)
    report = guard.gather("inbox-prikaz", log=log, tracker_dir=tracker, sibling=sibling,
                          self_session="cycle-865", now=NOW, ps=DEAD,
                          self_anchor=SELF_ANCHOR, shared_trees=())
    assert INCIDENT_RUN_ID in seen, seen
    assert _front(report)["worker_detail"] == "шпион ответил"


def test_the_instrument_lives_outside_the_tree_it_measures(guard):
    """Путь к прибору объявлен и указывает на замок цикла, а не на копию рядом."""
    assert Path(guard.LOCK).name == "orchestrator_cycle_lock.py", guard.LOCK
    assert Path(guard.LOCK).exists(), guard.LOCK
    # Собственной реализации поиска метки в процессах у шага 0b нет: это и есть
    # «одна копия». Признак — отсутствие обращения к имени переменной в тексте модуля
    # где-либо кроме объявления и чтения окружения.
    src = Path(guard.__file__ or (ROOT / "scripts" / "check_card_claim.py")).read_text(
        encoding="utf-8")
    assert "ps -A" not in src and "-Ewww" not in src, (
        "шаг 0b завёл свою пробу процессов — второй расходящийся ответ на тот же вопрос")
    assert f'{guard.RUN_ID_VAR}=' not in src.replace(f'RUN_ID_VAR = "{guard.RUN_ID_VAR}"',
                                                     ""), (
        "шаг 0b сам ищет метку в тексте процесса — это копия прибора")


def test_the_claim_keys_cover_the_mark_so_it_cannot_outlive_the_claim(guard):
    """Метка объявлена строкой захвата: ставится и снимается вместе с ним."""
    assert "claimed_run_id" in guard._CLAIM_KEYS, guard._CLAIM_KEYS


def test_os_environ_is_the_only_source_of_my_own_mark(guard, monkeypatch):
    """Своя метка берётся из ОКРУЖЕНИЯ — единственной личности, переживающей запускателя."""
    monkeypatch.setenv(guard.RUN_ID_VAR, "orchestrator-42-FROM-ENV")
    assert os.environ[guard.RUN_ID_VAR] == "orchestrator-42-FROM-ENV"
    text = guard._set_claim_fields(
        "---\nstatus: in-progress\n---\n\nтело\n",
        # Отметка выведена из якоря `NOW`, а не вписана литералом: предмет проверки —
        # ОТКУДА берётся метка, но литеральная дата рядом с понятием свежести завела бы
        # файл в класс храповика замороженных дат, где ему делать нечего.
        {"claimed_by": "cycle-42", "claimed_at": _fmt(NOW),
         "claimed_run_id": os.environ[guard.RUN_ID_VAR]})
    assert "claimed_run_id: orchestrator-42-FROM-ENV" in text, text
