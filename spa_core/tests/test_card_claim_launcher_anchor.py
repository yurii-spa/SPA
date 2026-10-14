"""ЯКОРЬ ЗАПУСКАТЕЛЯ обязан доезжать до карточки, а не браться взаймы (цикл #869, ADR-725).

Что измерено, и почему это НЕ форма ярлыка
------------------------------------------------------------------------------
Заказ G724 п. 2 (#868) назвал причиной неберущейся карточки ФОРМУ ярлыка:
`SPA_SESSION_ID=cycle-$$` несёт цифры, но не токен `pid`, и ось ЗАПУСКАТЕЛЯ его не
измеряет — у 138 из 192 захватов живого трекера (перемерено #869: 54 · 138 · 192, форма
`cycle-N` — 127 из 138). Число верное; как ПРИЧИНА оно замера не выдержало. Одна и та же
сцена на чистой вершине `48fc93873`, прогнанная обеими формами:

    ярлык                    якорь в журнале   `ps`     вердикт
    cycle-75896              нет               мёртв    claimed
    cycle-75896-pid75896     нет               мёртв    claimed   ← то же самое
    cycle-75896              ЕСТЬ              мёртв    stale
    cycle-75896              ЕСТЬ              жив      claimed

Форма ярлыка не меняет вердикт ни в одну сторону, и это не недосмотр читателя, а его
объявленное сужение: `durable_process_gone` дословно — «это НЕ „`ps` не нашёл pid“»,
потому что `session` по умолчанию есть pid ОДНОКРАТНОЙ CLI-команды, мёртвый ВСЕГДА, и
живая сессия стала бы неотличима от осиротевшей. Ровно на этом стоит окно ожидания.

Настоящий рычаг — ОБЪЯВЛЕННЫЙ якорь (`session_pid` + `session_pid_start`). Писатель
захвата его ИЗМЕРЯЕТ и без него работать ОТКАЗЫВАЕТСЯ (`measure_self_anchor` ⇒
`UnmeasurableClaim`) — а потом ВЫБРАСЫВАЕТ: читателю оставался заём из журнала по ярлыку
держателя. Заём опирается на то, чего у карточки нет по построению — **карточка уезжает
на `origin`, журнал объявлений НЕТ**, и это сказано вслух в том же писателе, там, где он
объясняет, зачем `claim_takeover_reason` живёт в карточке.

ЗАМЕР 14.10 (живой трекер + общий журнал, 2724 записи): якорь не доезжает до **48 из
192** захватов (25.0 %), на ОТКРЫТЫХ карточках — до **6 из 15** (40.0 %).

Асимметрия и есть дефект: ADR-721 довёл до frontmatter метку РАБОТНИКА
(`claimed_run_id`), якорь ЗАПУСКАТЕЛЯ туда не доехал никогда ⇒ из двух объявленных
равноправными осей измерима из карточки ровно одна.

Что проверяется, и почему в ОБЕ стороны
------------------------------------------------------------------------------
* якорь в карточке + смерть ИЗМЕРЕНА ⇒ `stale` (карточка поднимается) — это и есть правка;
* якоря в карточке НЕТ ⇒ вердикт прежний БАЙТ В БАЙТ (190+ существующих захватов);
* якорь в карточке + запускатель ЖИВ ⇒ `claimed`: измеренная жизнь сильнее, новой двери
  к «свободна» не появляется;
* ПОЛОВИНА пары ⇒ личностью не является ⇒ заём, как до правки (pid переиспользуется ОС);
* `pid <= 1` ⇒ то же: это не процесс сессии;
* старт ПОЗЖЕ захвата ⇒ `pid занят ДРУГИМ процессом` — защита не выдаётся чужому живому
  процессу по совпадению номера;
* СВОЙ якорь сильнее ЗАЁМНОГО: карточка и журнал спорят ⇒ решает карточка (её пару
  написал ТОТ ЖЕ захват);
* `stale` ≠ `free`: `claim` на нём по-прежнему ОТКАЗЫВАЕТ без `--takeover` с непустой
  письменной причиной, а с причиной — поднимает (иначе правка не разблокировала бы
  очередь, а только переименовала отказ);
* якорь СНИМАЕТСЯ вместе с захватом (`_CLAIM_KEYS`): чужая пара, уцелевшая после
  подъёма, измерялась бы как личность НОВОГО держателя — ложная занятость вместо ложной
  свободы, но всё равно ложь.

Время и живость — ВХОДЫ, а не окружение
------------------------------------------------------------------------------
Литеральных дат в файле нет ни одной: все отметки выведены из якоря `NOW`, он же идёт
измерителю аргументом `now=`. Живость запускателя ИНЪЕКТИРОВАНА (`ps=`): сторож,
спрашивающий настоящую ОС, менял бы вердикт от того, кто сегодня занял номер
(`.claude/rules/deployment.md` § «ЛИЧНОСТЬ ПРОЦЕССА»). Единственный литеральный номер —
`DEAD_PID`/`OTHER_PID`: живым процессом они не притворяются, их сравнивают только с
такими же парами ВНУТРИ сцены, а ответ ОС за них даёт инъекция.
"""
import importlib.util
import json

import shutil
from datetime import timedelta
from pathlib import Path

import pytest

from spa_core.monitoring.card_acceptance import (NOT_SATISFIED, PROBES, SATISFIED,
                                                 UNMEASURED)
from spa_core.tests._freshness import now_utc

ROOT = Path(__file__).resolve().parents[2]

PROBE_NAME = "card_claim_carries_the_launcher_anchor"

#: Якорь времени — РЕАЛЬНЫЕ часы: предмет файла — свежесть захвата, и литеральная дата
#: начала бы падать от сдвига календаря, а не от кода. Часы инъектированы (`now=`), обе
#: стороны сравнения выведены отсюда. Доли секунды отрезаны намеренно: отметки карточки
#: печатаются до секунды (`_fmt_ts`), и у якоря с микросекундами обратный разбор дал бы
#: мгновение РАНЬШЕ — проверка «внутри окна» мерила бы другое утверждение.
NOW = now_utc().replace(microsecond=0)

HOLDER = "cycle-869000"
#: Номера сцены. Литерал безопасен: живость за них отвечает инъекция (`ps=`), а живым
#: процессом они не притворяются нигде.
DEAD_PID, OTHER_PID = 869_001, 869_002

#: Старт запускателя — ЗАВЕДОМО раньше захвата, иначе сцена «жив» мерила бы
#: переиспользованный номер (это ОТДЕЛЬНОЕ звено ниже).
START = (NOW - timedelta(hours=2)).astimezone().strftime("%a %b %d %H:%M:%S %Y")
#: Старт ПОЗЖЕ захвата — сцена переиспользованного ОС номера.
LATER = (NOW + timedelta(hours=1)).astimezone().strftime("%a %b %d %H:%M:%S %Y")

DEAD = lambda _pid: (1, "")                                          # noqa: E731
ALIVE = lambda _pid: (0, START)                                      # noqa: E731


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load("_c869_card_claim", ROOT / "scripts" / "check_card_claim.py")


@pytest.fixture(scope="module")
def sibling(guard):
    return guard.load_sibling()


@pytest.fixture()
def tracker(tmp_path):
    d = tmp_path / "tracker"
    d.mkdir()
    return d


@pytest.fixture()
def empty_log(tmp_path):
    """Журнал ПУСТ — заём личности невозможен.

    Это не искусственная бедность сцены, а дословное состояние читателя на `origin`:
    карточка туда уезжает, журнал объявлений — нет (так сказано в самом писателе).
    """
    p = tmp_path / "session_changes.jsonl"
    p.write_text("", encoding="utf-8")
    return p


def _fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _card(tracker, guard, anchor=None, age_hours=None):
    """Карточка с захватом ВНУТРИ окна свежести; `anchor` — пара полей якоря или None."""
    inside = guard.DEFAULT_GRACE_HOURS / 2.0 if age_hours is None else age_hours
    at = _fmt(NOW - timedelta(hours=inside))
    rows = ["---\n", "trackerStatus:\n", "  type: inbox\n", "title: сцена\n",
            "status: in-progress\n", f"claimed_by: {HOLDER}\n", f"claimed_at: {at}\n"]
    for key, value in (anchor or {}).items():
        rows.append(f"{key}: {value}\n")
    rows += ["---\n", "\nтело\n"]
    (tracker / "inbox-scene.md").write_text("".join(rows), encoding="utf-8")
    return at


def _report(guard, sibling, tracker, log, ps=DEAD):
    return guard.gather("inbox-scene", log=log, tracker_dir=tracker, sibling=sibling,
                        self_session="cycle-mine-869", now=NOW, ps=ps,
                        self_anchor=None, shared_trees=())


def _anchor(guard, pid, start):
    return dict(zip(guard.CLAIM_ANCHOR_KEYS, (pid, start)))


def _front(report):
    rows = [c for c in (report.get("claims") or []) if c.get("source") == "frontmatter"]
    return rows[0] if len(rows) == 1 else None


# ── вокабуляр: перевод имён — РОВНО ОДНА копия ───────────────────────────────

def test_claim_anchor_keys_match_the_step_0a_vocabulary(guard, sibling):
    """Пара полей карточки обязана соответствовать вокабуляру якоря шага 0a.

    Разошлись бы длины — `card_claim_anchor` молча угадывал бы имена, то есть читал бы
    якорь не тем словарём, которым его меряет `_durable_state`.
    """
    assert len(guard.CLAIM_ANCHOR_KEYS) == len(sibling.DURABLE_KEYS)


def test_claim_anchor_keys_are_cleaned_together_with_the_claim(guard):
    """Якорь обязан сниматься вместе с захватом: иначе чужая пара измеряется как своя."""
    for key in guard.CLAIM_ANCHOR_KEYS:
        assert key in guard._CLAIM_KEYS


def test_a_diverged_vocabulary_is_not_guessed(guard, sibling):
    """Вокабуляр якоря разошёлся ⇒ None, а не угаданные имена.

    Сцену не собрать карточкой: у живого кода длины СОВПАДАЮТ, и ветка молчит всегда.
    Поэтому сосед подменяется одноразовым объектом — иначе условие держалось бы только
    тем, что его никто не нарушал (замер мутациями #869: снятие ветки не ловилось ничем).
    """
    class _OneKey:
        DURABLE_KEYS = ("session_pid",)

    meta = dict(zip(guard.CLAIM_ANCHOR_KEYS, (DEAD_PID, START)))
    assert guard.card_claim_anchor(meta, sibling=_OneKey()) is None
    assert guard.card_claim_anchor(meta, sibling=sibling) is not None


@pytest.mark.parametrize("meta", [None, "строка", 17, []])
def test_an_unreadable_frontmatter_is_not_an_anchor(guard, sibling, meta):
    """Карточка не прочиталась ⇒ якоря нет, и это не исключение внутри сторожа."""
    assert guard.card_claim_anchor(meta, sibling=sibling) is None


# ── читатель: вердикт у ОБЕИХ сторон ────────────────────────────────────────

def test_measured_death_of_the_launcher_reaches_the_verdict(guard, sibling, tracker,
                                                            empty_log):
    """ПРЕДМЕТ ПРАВКИ: якорь в карточке + смерть измерена ⇒ карточка поднимается."""
    _card(tracker, guard, _anchor(guard, DEAD_PID, START))
    report = _report(guard, sibling, tracker, empty_log, ps=DEAD)
    assert report["verdict"] == guard.STALE
    rec = _front(report)
    assert rec is not None and rec["state"] == "stale"
    assert rec["orphaned"] is True


def test_a_claim_without_an_anchor_keeps_the_previous_verdict(guard, sibling, tracker,
                                                              empty_log):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ «дополняюще»: без якоря всё как до правки.

    Это 190+ существующих захватов живого трекера: правка обязана их не трогать.
    """
    _card(tracker, guard, None)
    report = _report(guard, sibling, tracker, empty_log, ps=DEAD)
    assert report["verdict"] == guard.CLAIMED
    assert _front(report) is None or _front(report)["state"] == "fresh"


def test_a_measured_alive_launcher_still_holds_the_card(guard, sibling, tracker,
                                                        empty_log):
    """Измеренная ЖИЗНЬ сильнее: новой двери к «свободна» правка не открывает."""
    _card(tracker, guard, _anchor(guard, DEAD_PID, START))
    report = _report(guard, sibling, tracker, empty_log, ps=ALIVE)
    assert report["verdict"] == guard.CLAIMED


def test_a_reused_pid_gets_no_protection(guard, sibling, tracker, empty_log):
    """Старт ПОЗЖЕ захвата ⇒ «занят ДРУГИМ процессом», а не живой держатель."""
    _card(tracker, guard, _anchor(guard, DEAD_PID, LATER))
    report = _report(guard, sibling, tracker, empty_log, ps=ALIVE)
    assert report["verdict"] == guard.STALE
    rec = _front(report)
    assert rec is not None and "занят ДРУГИМ процессом" in rec["session_state"]


@pytest.mark.parametrize("kept", [0, 1])
def test_half_a_pair_is_not_an_identity(guard, sibling, tracker, empty_log, kept):
    """ПОЛОВИНА пары личностью не является ⇒ заём, то есть прежнее поведение.

    Обе половины проверяются поимённо: pid без старта (номер переиспользуется ОС) и
    старт без pid (мерить нечего).
    """
    key = guard.CLAIM_ANCHOR_KEYS[kept]
    value = (DEAD_PID, START)[kept]
    _card(tracker, guard, {key: value})
    report = _report(guard, sibling, tracker, empty_log, ps=DEAD)
    assert report["verdict"] == guard.CLAIMED


@pytest.mark.parametrize("pid", [0, 1])
def test_pid_zero_and_one_are_not_a_session_process(guard, sibling, tracker, empty_log,
                                                   pid):
    """`pid0`/`pid1` — не процесс сессии: `ps` по ним ответил бы утвердительно."""
    _card(tracker, guard, _anchor(guard, pid, START))
    report = _report(guard, sibling, tracker, empty_log, ps=DEAD)
    assert report["verdict"] == guard.CLAIMED


def test_the_cards_own_anchor_beats_the_borrowed_one(guard, sibling, tracker, tmp_path):
    """СВОЙ якорь сильнее ЗАЁМНОГО — его написал ТОТ ЖЕ захват.

    Сцена-спор: журнал под тем же ярлыком знает ДРУГОЙ (живой) номер, карточка называет
    свой — мёртвый. До правки решал журнал, то есть личность, найденная по совпадению
    ярлыка. Живость инъектирована ПОИМЁННО, иначе утверждение мерило бы не ту ось.
    """
    at = _card(tracker, guard, _anchor(guard, DEAD_PID, START))
    log = tmp_path / "log_conflict.jsonl"
    log.write_text(json.dumps({
        "ts": at, "session": HOLDER, "summary": "голос держателя", "files": [],
        "session_pid": OTHER_PID, "session_pid_start": START}, ensure_ascii=False) + "\n",
        encoding="utf-8")

    def ps(pid):
        return (0, START) if pid == OTHER_PID else (1, "")

    report = _report(guard, sibling, tracker, log, ps=ps)
    assert report["verdict"] == guard.STALE
    rec = _front(report)
    assert rec is not None and str(DEAD_PID) in rec["session_state"]


# ── `stale` ≠ `free`: подъём остаётся РУЧНЫМ, но он ВОЗМОЖЕН ────────────────

def test_stale_still_refuses_a_claim_without_a_written_reason(guard, sibling, tracker,
                                                              empty_log):
    """Измеренная смерть не отдаёт карточку сама: `claim` без причины ОТКАЗЫВАЕТ."""
    _card(tracker, guard, _anchor(guard, DEAD_PID, START))
    with pytest.raises(guard.ClaimError):
        guard.claim_card("inbox-scene", log=empty_log, session="cycle-mine-869",
                         tracker_dir=tracker, now=NOW, sibling=sibling, ps=DEAD,
                         self_anchor=(OTHER_PID, START))


def test_takeover_lifts_the_card_and_restamps_the_anchor(guard, sibling, tracker,
                                                         empty_log):
    """С письменной причиной подъём проходит — иначе правка лишь переименовала отказ.

    И сразу вторая сторона: якорь на карточке становится якорем НОВОГО держателя. Пара
    прежнего, уцелев, измерялась бы как его личность.
    """
    _card(tracker, guard, _anchor(guard, DEAD_PID, START))
    guard.claim_card("inbox-scene", log=empty_log, session="cycle-mine-869",
                     tracker_dir=tracker, now=NOW, sibling=sibling, ps=DEAD,
                     self_anchor=(OTHER_PID, START), takeover_reason="сверено прогоном")
    meta = guard.frontmatter((tracker / "inbox-scene.md").read_text(encoding="utf-8"))
    assert meta["claimed_by"] == "cycle-mine-869"
    assert str(meta[guard.CLAIM_ANCHOR_KEYS[0]]) == str(OTHER_PID)
    assert str(meta[guard.CLAIM_ANCHOR_KEYS[1]]) == START


# ── писатель ────────────────────────────────────────────────────────────────

def test_the_writer_stamps_the_anchor_it_measured(guard, sibling, tracker, empty_log):
    """Писатель кладёт в карточку ту пару, которую ИЗМЕРИЛ (и без которой отказывает)."""
    (tracker / "inbox-fresh.md").write_text(
        "---\ntrackerStatus:\n  type: inbox\ntitle: сцена\nstatus: new\n---\n\nтело\n",
        encoding="utf-8")
    guard.claim_card("inbox-fresh", log=empty_log, session="cycle-mine-869",
                     tracker_dir=tracker, now=NOW, sibling=sibling, ps=DEAD,
                     self_anchor=(OTHER_PID, START))
    meta = guard.frontmatter((tracker / "inbox-fresh.md").read_text(encoding="utf-8"))
    assert str(meta[guard.CLAIM_ANCHOR_KEYS[0]]) == str(OTHER_PID)
    assert str(meta[guard.CLAIM_ANCHOR_KEYS[1]]) == START


def test_release_removes_the_anchor(guard, sibling, tracker, empty_log):
    """Снятие захвата убирает и якорь: иначе он описывает держателя, которого нет."""
    (tracker / "inbox-fresh.md").write_text(
        "---\ntrackerStatus:\n  type: inbox\ntitle: сцена\nstatus: new\n---\n\nтело\n",
        encoding="utf-8")
    guard.claim_card("inbox-fresh", log=empty_log, session="cycle-mine-869",
                     tracker_dir=tracker, now=NOW, sibling=sibling, ps=DEAD,
                     self_anchor=(OTHER_PID, START))
    guard.release_card("inbox-fresh", log=empty_log, session="cycle-mine-869",
                       tracker_dir=tracker, sibling=sibling)
    meta = guard.frontmatter((tracker / "inbox-fresh.md").read_text(encoding="utf-8"))
    for key in guard.CLAIM_ANCHOR_KEYS:
        assert key not in meta


def test_the_start_is_written_verbatim_including_double_spaces(guard):
    """Старт сохраняется ДОСЛОВНО — находка на собственной правке #869.

    `ps lstart` печатает день месяца через `%e`: для дней 1–9 это ДВА пробела
    (`Sat Aug  1 13:37:28 2026`). Первая редакция правки собирала значение заново
    (`" ".join(value.split())`) и пробел съедала. Вреда в тот день не было — измерено:
    `_parse_lstart` разбирает обе формы в один и тот же момент, — но личность процесса
    опиралась бы на СНИСХОДИТЕЛЬНОСТЬ парсера, и при его ужесточении якорь стал бы
    неизмерим в дни 1–9 КАЖДОГО месяца. Это тот же класс, что фиксированная дата в
    фикстуре (`.claude/rules/deployment.md` § «ВРЕМЯ В ТЕСТАХ»), только со стороны
    писателя: ошибка, ждущая своего числа в календаре.
    """
    verbatim = "Sat Aug  1 13:37:28 2026"   # FROZEN-DATE-OK: предмет — ФОРМА строки `ps`
    out = guard._set_claim_fields("---\ntitle: сцена\n---\n\nтело\n", {
        "claimed_by": HOLDER, "claimed_at": _fmt(NOW),
        guard.CLAIM_ANCHOR_KEYS[0]: OTHER_PID,
        guard.CLAIM_ANCHOR_KEYS[1]: verbatim})
    assert f"{guard.CLAIM_ANCHOR_KEYS[1]}: {verbatim}" in out.splitlines()


@pytest.mark.parametrize("kept", [0, 1])
def test_the_writer_never_emits_half_a_pair(guard, kept):
    """Половина пары не выводится НИ В ОДНОЙ ветке: читатель принял бы её за третий исход."""
    text = "---\ntitle: сцена\n---\n\nтело\n"
    values = {"claimed_by": HOLDER, "claimed_at": _fmt(NOW),
              guard.CLAIM_ANCHOR_KEYS[kept]: (OTHER_PID, START)[kept]}
    out = guard._set_claim_fields(text, values)
    for key in guard.CLAIM_ANCHOR_KEYS:
        assert f"{key}:" not in out


# ── контроль САМОЙ ПРОБЫ: зелена на контуре, красна на каждом порванном звене ─

#: Звенья контура. Каждое — (имя, что рвём, чем подменяем): замена ОБЯЗАНА найтись,
#: иначе «мутация» ничего не мутирует и контроль молча зеленеет на пустом месте.
_LINKS = {
    "писатель не кладёт якорь в поля захвата": (
        "        fields.update(dict(zip(CLAIM_ANCHOR_KEYS, (",
        "        _dropped = (dict(zip(CLAIM_ANCHOR_KEYS, ("),
    "писатель не печатает пару во frontmatter": (
        "        for key, value in zip(CLAIM_ANCHOR_KEYS, anchor):",
        "        for key, value in zip((), ()):"),
    "писатель печатает ПОЛОВИНУ пары": (
        "    if all(anchor):",
        "    if any(anchor):\n        anchor = [anchor[0], '']"),
    "читатель не предпочитает свой якорь заёмному": (
        "                              card_claim_anchor(meta, sibling=sibling)\n"
        "                              or _anchor_for(holder, at_raw),",
        "                              _anchor_for(holder, at_raw),"),
    "вокабуляра пары у читателя нет": (
        'CLAIM_ANCHOR_KEYS = ("claimed_pid", "claimed_pid_start")',
        "CLAIM_ANCHOR_KEYS = ()"),
}


@pytest.fixture()
def disposable_tree(tmp_path):
    """Одноразовая копия ТРЁХ файлов проводки: живое дерево не трогается.

    Больше не нужно: `ROOT` у шага 0b выводится из пути самого файла, а сосед и
    объявитель адресуются от него же — все трое stdlib-only.
    """
    def _make():
        tree = tmp_path / f"tree{len(list(tmp_path.glob('tree*')))}"
        (tree / "scripts").mkdir(parents=True)
        for name in ("check_card_claim.py", "check_undelivered_work.py",
                     "log_session_change.py"):
            shutil.copy2(ROOT / "scripts" / name, tree / "scripts" / name)
        return tree
    return _make


def test_the_probe_is_green_on_the_whole_contour(disposable_tree):
    verdict, why = PROBES[PROBE_NAME](None, repo_root=str(disposable_tree()))
    assert verdict == SATISFIED, why


@pytest.mark.parametrize("link", sorted(_LINKS))
def test_the_probe_is_red_on_every_broken_link(disposable_tree, link):
    """У каждого звена СВОЁ имя: «красная на чём-нибудь» проба ничего не доказывает."""
    old, new = _LINKS[link]
    tree = disposable_tree()
    path = tree / "scripts" / "check_card_claim.py"
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"звено {link!r} не найдено — мутация ничего не рвёт"
    path.write_text(text.replace(old, new), encoding="utf-8")
    verdict, why = PROBES[PROBE_NAME](None, repo_root=str(tree))
    assert verdict in (NOT_SATISFIED, UNMEASURED), f"{link}: проба осталась {verdict} — {why}"


def test_the_probe_reports_a_missing_reader_as_unmeasured(disposable_tree):
    """Читателя НЕТ — это третий исход, а не «не выполнено» и не «чисто» (инв. #17)."""
    tree = disposable_tree()
    (tree / "scripts" / "check_card_claim.py").unlink()
    verdict, why = PROBES[PROBE_NAME](None, repo_root=str(tree))
    assert verdict == UNMEASURED, why


def test_the_probe_does_not_pass_by_substring(disposable_tree):
    """ADR-333: проба меряет ИСХОД у читателя, а не наличие слов в файле.

    Контроль: имена полей объявлены, писатель и читатель порваны — текст про якорь в
    файле остаётся весь, а вердикт обязан быть красным.
    """
    tree = disposable_tree()
    path = tree / "scripts" / "check_card_claim.py"
    text = path.read_text(encoding="utf-8")
    old, new = _LINKS["писатель не кладёт якорь в поля захвата"]
    assert text.count(old) == 1
    path.write_text(text.replace(old, new), encoding="utf-8")
    assert "claimed_pid_start" in path.read_text(encoding="utf-8")
    verdict, _why = PROBES[PROBE_NAME](None, repo_root=str(tree))
    assert verdict == NOT_SATISFIED
