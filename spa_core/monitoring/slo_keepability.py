"""Может ли производитель выдержать ОБЪЯВЛЕННЫЙ срок годности — замер по НАБЛЮДЁННОМУ такту.

Заказ **G94** приказа владельца «Portfolio CIO», цена остатка «вернуть
производителя в такт» (замер #723, ADR-506).

## Вопрос, на который прибор отвечает

У артефакта в конституции флота (``architecture/manifest.json``) объявлен
``slo_hours`` — через сколько часов файл считается протухшим. Вопрос прибора
ОДИН: **способен ли производитель этого артефакта такой срок выдержать вообще.**

ADR-506 измерил ответ РУКОЙ у одного агента и нашёл класс: у
``com.spa.decision_loop`` объявлено ``slo_hours: 7``, а наблюдённый такт — восемь
периодов подряд ``6.82 · 6.97 · 7.58 · 7.56 · 7.62 · 7.62 · 7.78 · 7.84`` ч, то
есть семь из восьми ДЛИННЕЕ срока. Причина измерима: ``StartInterval`` 21600 с
(6 ч) отсчитывается launchd от ЗАВЕРШЕНИЯ прогона, а прогон идёт ~1 ч 40 мин.
Такой артефакт протухает почти каждый период ПО ПОСТРОЕНИЮ, и три критерия
приёмки владельца из §49 остались «НЕ ИЗМЕРЕНО» — объявлением это не чинится.

**Порог, который производитель не может выдержать никогда, не отличает здоровье
от болезни.** Сторож свежести на нём краснеет ровно так же, как на настоящей
поломке, — и учит игнорировать себя раньше, чем приносит пользу. Рукой класс
измерен у 1 агента; в конституции таких пар «агент × артефакт» **199**, и прибора
у них не было.

## Что есть ответ, а что — ТРЕТИЙ ИСХОД (инв. #17)

Сравниваются ДВА числа: объявленный ``slo_hours`` и **максимальный наблюдённый
период** между прогонами производителя. Максимум, а не медиана: обещание
«файл свежее N часов» нарушается ОДНИМ длинным разрывом, и медиана его прячет.

``keepable``
    максимальный наблюдённый период ``<=`` объявленного срока И окно наблюдения
    НЕ КОРОЧЕ самого срока.
``unkeepable``
    максимальный наблюдённый период ``>`` объявленного срока. Числа названы оба.
``unmeasured``
    такт не наблюдён, и причина НАЗВАНА (см. ниже). Это не ноль и не «чисто».

## Ось ТАКТА — какое из ДВУХ состояний дало находку (ADR-813, цикл #936)

Вердикт стои́т на МАКСИМУМЕ и этим не двигается: обещание «файл свежее N часов»
нарушил ОДИН разрыв, и это правда о прошлом, которую медиана прячет. Но
**вопрос, объявленный выше, — про СПОСОБНОСТЬ** («способен ли производитель
такой срок выдержать вообще»), а максимум отвечает про ИСТОРИЮ («был ли срок
нарушён хоть раз»). Это два разных вопроса, и до #936 оба печатались одним
словом: строка отчёта говорила «артефакт протухает ПО ПОСТРОЕНИЮ» КАЖДОЙ
находке.

Замер 25.10 на живом флоте: находок **139**, и у **70** из них медиана периода
срок ДЕРЖИТ — то есть «по построению» было сказано про пары, которые по
построению его как раз выдерживают. Семьдесят неверных слов в выводе сторожа и
есть механизм, которым он учит себя игнорировать: разобрать 139 одинаковых
строк дороже, чем 69 настоящих.

Поэтому рядом с вердиктом считается ОСЬ (``cadence_axis``), и в сумму вердиктов
она НЕ входит — как и ось расписания:

``cadence_cannot_keep``
    медиана периода ``>`` срока. Такт НЕ СПОСОБЕН выдержать обещание — класс
    ADR-506, и чинится он сроком либо расписанием.
``cadence_keeps_outlier_broke``
    медиана ``<=`` срока ``<`` максимума. Такт обещание держит, нарушил его
    ОДИН разрыв. Находка остаётся находкой, но лечится она не сроком.
``cadence_keeps``
    максимум ``<=`` срока — находки нет вовсе.
``cadence_unmeasured``
    периодов МЕНЬШЕ ТРЁХ. Порог не выбран, а выведен: при двух периодах
    максимум сам входит в медиану, то есть различать состояния нечем. Это
    третий исход (инв. #17), а не «такт держит».

## ВЫВЕДЕННЫЙ срок — ответ на «а какой тогда?» (ADR-814, цикл #938)

Назвать пару невыдерживаемой и не назвать выдерживаемого числа значит оставить
читателю ровно ту работу, ради которой прибор написан. Поэтому у КАЖДОЙ пары
считается ``derived_slo_hours`` — пол, который наблюдённый такт выдержать
способен, — и ``curated_vs_floor``: ниже ли его объявленный срок.

**Правило считает не этот модуль, а** ``slo_proposal`` (ADR-158): запас поверх
такта там восстановлен по 35 курированным человеком срокам. Новое здесь ОДНО —
**база**: пол берётся от НАБЛЮДЁННОЙ медианы, а не от объявленного расписания,
потому что ADR-506 измерил, что расписание про такт врёт (launchd считает
``StartInterval`` от ЗАВЕРШЕНИЯ прогона).

Печатается выведенный срок только состоянию ``cadence_cannot_keep``: у выброса
причина НЕ измерена, и предложить проглотить его сроком значило бы сделать ровно
то, что ADR-813 запретил.

**Замер 26.10 на живой конституции:** курированных пар со сроком **231**, из них
**82** ниже пола, который даёт правило ``slo_proposal`` по ОБЪЯВЛЕННОМУ
расписанию, и **69** из 82 — одна семья ``com.spa.decision_loop``. Ни об одной
``slo_proposal.propose`` не говорил ничего, и это не промах реализации: при уже
проставленном человеком сроке он возвращает ``already_curated`` и роли срок НЕ
переназначают. Для его вопроса («какой срок назначить, если его нет») это верно;
вопроса «а назначенный — не ниже ли пола» у него не было ПО ПОСТРОЕНИЮ.

**ПРИЧИНУ выброса прибор НЕ меряет** и поэтому не называет её в имени оси.
Хост спал (``launchd.plist(5)``: пропущенное срабатывание не догоняется),
перезагрузка, разовый долгий прогон — всё это разные вещи с разными владельцами,
и записать их одним словом значило бы выдумать замер.

**Почему окно обязано быть не короче срока.** Разрыв длиннее 26 ч не поместится
в окно наблюдения длиной 3 ч: «нарушений не нашлось» там верно ПО ПОСТРОЕНИЮ и
о сроке не говорит ничего (урок ADR-543 — зелёный по построению). Поэтому такой
случай есть ``unmeasured`` с причиной ``window_shorter_than_slo``, а не
``keepable``.

## Причины, по которым такт НЕ наблюдён — пять, и они чинятся разным

``record_form_unrecognised``
    обёртка агента НЕ пользуется каноническим шаблоном (``agent_template.sh``) и
    ведёт свою форму записи прогонов. Прибор читает ОДНУ форму — баннер шаблона
    ``[<ISO>] START agent=<имя>`` — и говорит это вслух, а не выдаёт «форму не
    читаю» за «прогонов нет».
``address_unresolved``
    шаблон используется, но имя агента из обёртки не читается — адрес записи
    назвать нечем.
``record_absent``
    адрес назван, файла записи НЕТ. Замер 03.10: ровно это у
    ``com.spa.decision_loop`` — launchd насчитал ``runs = 11`` за 86 ч с
    загрузки, то есть агент ШЁЛ, а записи о его прогонах не осталось
    (``/tmp`` очищается при перезагрузке и уборкой диска). «Такт не измерен» и
    «агент не идёт» — РАЗНЫЕ положения дел, и путать их нельзя.
``record_unreadable``
    файл есть, прочитать не вышло (права, кодировка).
``fewer_than_two_runs``
    прогон один: периода не существует. Ноль здесь был бы ложью о скорости.

## Ось «расписание против наблюдения» — ПРИЧИНА, а не вердикт

Рядом считается ось: объявленное в манифесте расписание (``interval:3600s``)
против наблюдённой медианы. ``observed_exceeds_declared`` и есть механизм
ADR-506 (launchd считает от завершения). Ось в сумму вердиктов НЕ входит — она
объясняет находку, а не заменяет её.

## Чего прибор НЕ докладывает (назвать слепоту — часть замера)

* **Моменты ЗАПИСИ артефакта.** Период меряется от СТАРТА к старту прогона. Если
  артефакт пишется на разном смещении внутри прогона, период между записями от
  периода между стартами отличается — истории ``mtime`` система не хранит.
* **Вторую запись о прогонах.** У launchd есть свой счётчик (``launchctl print``
  → ``runs``), но в нём нет ОТМЕТОК ВРЕМЕНИ, значит нет и периодов: он отвечает
  на вопрос «сколько раз», а не «с каким разрывом».
* **Верность самого срока.** «Выдерживаем» не значит «срок выбран правильно»:
  цену опоздания назначают две роли (ADR-158, `slo_proposal`), и это другой
  вопрос.
* **Производителя вне манифеста.** Население ОБЪЯВЛЕНО конституцией; кто пишет
  файл помимо объявленного агента, прибору не виден.
* **Запас на один пропуск.** Пол Архитектора (такт × 2, ADR-158) считается
  ОСЬЮ и в вердикт не входит: это существующее правило соседа, а не новый порог.

## Коды возврата

* **0** — замер состоялся, и КАЖДАЯ пара населения измерена и выдерживаема.
* **1** — замер состоялся и есть находка: хоть одна пара невыдерживаема ЛИБО
  хоть у одной такт не наблюдён. «Не измерено» за «чисто» не выдаётся.
* **2** — замера НЕТ ВОВСЕ (конституция не прочитана, население пусто). Про
  сроки при этом НЕ СКАЗАНО НИЧЕГО.

LLM_FORBIDDEN. Только stdlib · ADVISORY: ничего не гасит, ничего не чинит,
risk-логику, стоп-кран, аллокатор, живой трек и ``landing/**`` не трогает.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.monitoring import slo_proposal  # noqa: E402
from spa_core.monitoring.manifest_slo import slo_hours_by_path  # noqa: E402
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

ARTIFACT = "slo_keepability.json"

#: Вердикт ОДНОЙ пары «агент × артефакт».
KEEPABLE = "keepable"
UNKEEPABLE = "unkeepable"
UNMEASURED = "unmeasured"

#: Причины, по которым такт производителя НЕ наблюдён. Каждая чинится своим.
FORM_UNRECOGNISED = "record_form_unrecognised"
ADDRESS_UNRESOLVED = "address_unresolved"
RECORD_ABSENT = "record_absent"
RECORD_UNREADABLE = "record_unreadable"
FEWER_THAN_TWO_RUNS = "fewer_than_two_runs"
PRODUCER_NOT_DECLARED = "producer_not_declared"
#: Состояние, которого прибор объяснить НЕ УМЕЕТ: периода нет, а ни один
#: производитель причины не назвал. Это дефект САМОГО прибора, а не флота, и
#: молчать о нём нельзя — подставлять сюда правдоподобную причину значило бы
#: завести ВТОРУЮ копию правила `run_starts` (ADR-220). Живой замер его не
#: содержит, и это закреплено тестом.
CAUSE_NOT_NAMED = "cause_not_named"
WINDOW_SHORTER_THAN_SLO = "window_shorter_than_slo"
TIMESTAMPS_UNPARSABLE = "timestamps_unparsable"

#: Ось ТАКТА: какое из двух состояний дало находку (ADR-813). НЕ вердикт —
#: вердикт стои́т на максимуме и этой осью не двигается.
CADENCE_CANNOT_KEEP = "cadence_cannot_keep"
CADENCE_OUTLIER = "cadence_keeps_outlier_broke"
CADENCE_KEEPS = "cadence_keeps"
CADENCE_UNMEASURED = "cadence_unmeasured"

#: Сколько периодов нужно, чтобы медиана МОГЛА отличить выброс от такта. Порог
#: не выбран, а ВЫВЕДЕН: при ``n`` периодах один максимум не может быть медианой
#: только начиная с ``n = 3``; при двух он в медиану входит сам, и тогда медиана
#: судила бы о выбросе ПО СЕБЕ. Ниже порога ось = ``cadence_unmeasured``.
CADENCE_MIN_PERIODS = 3

#: Ось «расписание против наблюдения» (ПРИЧИНА находки, не вердикт).
SCHEDULE_WITHIN = "observed_within_declared"
SCHEDULE_EXCEEDS = "observed_exceeds_declared"
SCHEDULE_UNPARSED = "schedule_unparsed"
#: Расписание БЕЗ периода: `daemon` (вечный процесс, который не перезапускается
#: вовсе), `manual`, `event:*`. Это НЕ «не разобрали» — у такого агента периода
#: не существует, и объявлять его значило бы выдумать число.
SCHEDULE_NOT_PERIODIC = "schedule_not_periodic"
#: Расписание прочитано, а НАБЛЮДЕНИЯ нет — третий исход этой оси. Сваливать его
#: в «не разобрали расписание» значило бы обвинить конституцию в том, чего в ней
#: нет: форма объявлена верно, не хватает ЗАПИСИ прогонов.
SCHEDULE_OBSERVATION_ABSENT = "observation_absent"
_NOT_PERIODIC = ("daemon", "manual")

#: Баннер канонической обёртки (`scripts/agent_template.sh`): ОДНА форма записи
#: прогонов, которую прибор умеет читать. Имя агента в баннере сверяется с
#: разрешённым адресом — чужой баннер в общем логе периодом не считается.
#:
#: Слово ``START`` здесь НЕСУЩЕЕ: обёртка печатает рядом ``EXIT agent=<имя>``, и
#: правило «строка с `agent=`» удвоило бы каждый прогон, то есть вдвое занизило
#: бы наблюдённый период — ошибка В СТОРОНУ ЗДОРОВЬЯ.
_BANNER = re.compile(r"^\[([^\]]+)\]\s+START agent=(\S+)")

#: Имя агента в обёртке: `AGENT_NAME="watchdog"` (режим A шаблона, с `export`
#: или без) либо позиционным аргументом шаблона (режим B).
_AGENT_NAME_ASSIGN = re.compile(r'^\s*(?:export\s+)?AGENT_NAME=["\']?([A-Za-z0-9_]+)', re.M)
_TEMPLATE_CALL = re.compile(r"agent_template\.sh\s+([A-Za-z0-9_]+)")
_TEMPLATE_MENTION = "agent_template.sh"

#: Окно наблюдения по умолчанию. ВЫБОР, а не свойство мира: `/tmp` очищается при
#: перезагрузке, поэтому окно шире фактической записи ничего не добавляет, а
#: короче — прячет длинные разрывы.
WINDOW_HOURS = 7 * 24.0

#: Пол Архитектора из ADR-158 («такт × 2» — один пропуск не поднимает тревогу).
#: Считается ОСЬЮ: правило чужое, и вердикт этого прибора на нём не стоит.
MARGIN_FACTOR = 2.0

#: Только идущие агенты. `retired`/`designed` такта не имеют по построению, и
#: судить их сроки значило бы печатать находку о том, чего нет.
ACTIVE = "active"

#: Совпадает ли ОБЪЯВЛЕННОЕ со-производство с ДЕЙСТВИТЕЛЬНЫМ (ADR-817, заказ
#: G816 п. 2). Предмет — ПРЕДПОСЫЛКА воздержания ADR-816, а НЕ срок годности:
#: воздержание говорит «артефакт объявлен за несколькими производителями, такт
#: ОДНОГО про файл не отвечает», и если в действительности идёт один, то
#: предпосылка ложна, а поагентное отрицание было ВЕРНО.
CO_PRODUCTION_CONFIRMED = "declared_co_production_confirmed"
CO_PRODUCTION_NOMINAL = "declared_co_production_nominal_only"
CO_PRODUCTION_NONE_RUNNING = "declared_co_production_no_producer_running"
CO_PRODUCTION_UNMEASURED = "declared_co_production_unmeasured"

#: Причины, при которых прогонов производителя НЕ НАБЛЮДАЛИ ВОВСЕ. Счёт здесь
#: обязан быть ``None``, а не нулём: «лог не найден» и «лог прочитан, прогонов в
#: нём нет» — разные положения дел (инв. #17), и ноль вместо первого превратил бы
#: немого производителя в доказательство того, что со-производство мнимое.
RUNS_UNOBSERVABLE = (ADDRESS_UNRESOLVED, RECORD_ABSENT, RECORD_UNREADABLE,
                     FORM_UNRECOGNISED, TIMESTAMPS_UNPARSABLE)

CAUSE_RU = {
    FORM_UNRECOGNISED: "обёртка ведёт СВОЮ форму записи прогонов — канонического баннера нет",
    ADDRESS_UNRESOLVED: "имя агента в обёртке не объявлено — адрес записи назвать нечем",
    RECORD_ABSENT: "адрес назван, файла записи прогонов НЕТ",
    RECORD_UNREADABLE: "файл записи не прочитан",
    FEWER_THAN_TWO_RUNS: "прогон один — периода не существует",
    WINDOW_SHORTER_THAN_SLO: "окно наблюдения КОРОЧЕ самого срока — нарушение в него не поместится",
    TIMESTAMPS_UNPARSABLE: "баннеры есть, ни одна отметка времени не разобрана",
    PRODUCER_NOT_DECLARED: "срок объявлен, идущего производителя у него нет — обещать некому",
    CAUSE_NOT_NAMED: "периода нет, и ни один производитель причины не назвал — дефект прибора",
}


class Unmeasured(Exception):
    """Замера нет вовсе. Про сроки при этом не сказано НИЧЕГО."""


def _stamp(moment: Optional[datetime] = None) -> str:
    return (moment or datetime.now(timezone.utc)).isoformat()


def _now(moment: Optional[datetime] = None) -> datetime:
    return moment or datetime.now(timezone.utc)


def log_address(program: str, scripts_dir: Path) -> tuple:
    """``(имя агента, причина)`` — где искать запись прогонов.

    Имя читается ИЗ ОБЁРТКИ, а не выводится из ярлыка launchd: совпадение
    ``com.spa.X`` → ``spa_X.log`` есть соглашение, а соглашение — не замер.
    """
    if not program:
        return None, ADDRESS_UNRESOLVED
    script = Path(scripts_dir) / program
    try:
        source = script.read_text(errors="replace")
    except OSError:
        return None, ADDRESS_UNRESOLVED
    found = _AGENT_NAME_ASSIGN.search(source)
    if found:
        return found.group(1), None
    joined = re.sub(r"\\\n\s*", " ", source)
    for line in joined.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        call = _TEMPLATE_CALL.search(stripped)
        if call:
            return call.group(1), None
    # Шаблон не упомянут вовсе ⇒ обёртка ведёт свою запись: это НЕ «адрес не
    # разобран», это другая форма, и чинится она другим.
    if _TEMPLATE_MENTION not in source:
        return None, FORM_UNRECOGNISED
    return None, ADDRESS_UNRESOLVED


def _parse_stamp(raw: str) -> Optional[datetime]:
    for form in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = datetime.strptime(raw, form)
        except ValueError:
            continue
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    return None


def run_starts(path: Path, agent_name: str, *, now: Optional[datetime] = None,
               window_hours: float = WINDOW_HOURS) -> dict:
    """Отметки стартов производителя в окне + счёт отброшенного, с ПРИЧИНОЙ.

    Отброшенное считается, а не замалчивается: чужой баннер в общем логе,
    неразобранная отметка и отметка из будущего (сдвиг часов) — три разных
    события, и каждое печатается своим числом.
    """
    moment = _now(now)
    horizon = moment - timedelta(hours=float(window_hours))
    try:
        text = path.read_text(errors="replace")
    except FileNotFoundError:
        return {"starts": [], "cause": RECORD_ABSENT}
    except OSError:
        return {"starts": [], "cause": RECORD_UNREADABLE}
    starts: list = []
    foreign = unparsable = future = outside = banners = 0
    for line in text.splitlines():
        hit = _BANNER.match(line)
        if not hit:
            continue
        banners += 1
        if hit.group(2) != agent_name:
            foreign += 1
            continue
        stamp = _parse_stamp(hit.group(1))
        if stamp is None:
            unparsable += 1
            continue
        if stamp > moment:
            future += 1
            continue
        if stamp < horizon:
            outside += 1
            continue
        starts.append(stamp)
    starts.sort()
    cause = None
    if not banners:
        cause = FORM_UNRECOGNISED
    elif not starts and unparsable:
        cause = TIMESTAMPS_UNPARSABLE
    elif len(starts) < 2:
        cause = FEWER_THAN_TWO_RUNS
    return {"starts": starts, "cause": cause, "banners": banners,
            "foreign_banners": foreign, "unparsable_banners": unparsable,
            "future_banners": future, "outside_window": outside}


def periods_hours(starts: list) -> list:
    """Периоды СТАРТ→СТАРТ в часах по возрастанию отметок."""
    ordered = sorted(starts)
    return [(ordered[i + 1] - ordered[i]).total_seconds() / 3600.0
            for i in range(len(ordered) - 1)]


def parse_schedule(schedule) -> Optional[float]:
    """Объявленное расписание манифеста в часах — САМЫЙ ДЛИННЫЙ разрыв цикла.

    Для перечня календарных отметок это не «24 / число отметок»: агент с
    отметками ``05:00,06:00`` просыпается дважды в сутки, а ждать между ними
    приходится 23 часа. Разрыв считается по самой широкой соседней паре цикла,
    иначе объявленное расписание врало бы в сторону здоровья.
    """
    if not isinstance(schedule, str):
        return None
    raw = schedule.strip()
    hit = re.match(r"^interval:(\d+(?:\.\d+)?)([sh])$", raw)
    if hit:
        value = float(hit.group(1))
        return value / 3600.0 if hit.group(2) == "s" else value
    if not raw.startswith("calendar:"):
        return None
    cycle, moments = 24.0, []
    for token in raw[len("calendar:"):].split(","):
        token = token.strip()
        if not token:
            continue
        weekday = re.match(r"^wd(\d)[·\-](\d{1,2}):(\d{2})$", token)
        if weekday:
            cycle = 168.0
            moments.append(int(weekday.group(1)) * 24.0
                           + int(weekday.group(2)) + int(weekday.group(3)) / 60.0)
            continue
        clock = re.match(r"^(\d{1,2}):(\d{2})$", token)
        if clock:
            moments.append(int(clock.group(1)) + int(clock.group(2)) / 60.0)
            continue
        return None
    if not moments:
        return None
    moments.sort()
    gaps = [moments[i + 1] - moments[i] for i in range(len(moments) - 1)]
    gaps.append(cycle - moments[-1] + moments[0])
    return max(gaps)


def non_periodic(schedule) -> bool:
    """Расписание без периода: вечный процесс, рука, событие."""
    if not isinstance(schedule, str):
        return False
    raw = schedule.strip()
    return raw in _NOT_PERIODIC or raw.startswith("event:")


def _schedule_axis(declared: Optional[float], median: Optional[float],
                   schedule=None) -> str:
    if non_periodic(schedule):
        return SCHEDULE_NOT_PERIODIC
    if declared is None:
        return SCHEDULE_UNPARSED
    if median is None:
        return SCHEDULE_OBSERVATION_ABSENT
    return SCHEDULE_EXCEEDS if median > declared else SCHEDULE_WITHIN


def _derived(median: Optional[float], declared) -> dict:
    """Какой срок НАБЛЮДЁННЫЙ такт выдержать способен — и ниже ли его объявленный.

    Правило не моё и здесь не живёт: пол считает ``slo_proposal.observed_floor``
    (ADR-158, запас восстановлен по 35 курированным срокам), сравнение —
    ``slo_proposal.audit_curated``. Второй копии правила «какой срок возможен» в
    дереве быть не должно: ровно на двух копиях одного правила стоял ADR-220.

    Три исхода различимы (инв. #17): пол ВЫВЕДЕН · объявленный срок НИЖЕ пола ·
    такта не наблюдали ⇒ пола нет, и причина НАЗВАНА.
    """
    floor, why = slo_proposal.observed_floor(median)
    axis, note = slo_proposal.audit_curated(declared, floor, median)
    # ПРЕДЛОЖЕНИЕ и СУДЬЯ — одно точное значение, округлённое в РАЗНЫЕ стороны
    # (ADR-815). Поле `derived_slo_hours` уезжает в манифест человеком, поэтому
    # оно обязано быть НЕ НИЖЕ физически возможного; сравнение же обязано ошибаться
    # в сторону «возможно», иначе округление само рождает находку.
    offer = None if median is None else slo_proposal.offered_slo(median)
    return {"derived_slo_hours": offer, "derived_slo_basis": why,
            "derived_floor_hours": floor,
            "curated_vs_floor": axis, "curated_vs_floor_note": note}


def declared_axis_line(doc: dict) -> str:
    """Строка ОБЪЯВЛЕННОЙ оси для шага 0-офис. Единственная её форма.

    Живёт здесь, а не в мосте, по той же причине, по которой правило пола живёт
    в ``slo_proposal``: инлайн-печать внутри ``findings_bridge.main`` лежит за
    ступенью переписей, которая на живом Маке идёт часами, и проверить её
    отдельно НЕЧЕМ. Хуже того, любая опечатка в ней ушла бы в ``except`` моста
    как «перепись пропущена» — то есть молча, ровно тем fail-OPEN, против
    которого написан инв. #17.

    Секции нет ⇒ так и сказано («НЕ ИЗМЕРЕНО» с причиной), а не ноль и не
    пустая строка: прибор старой версии и прибор без находок обязаны быть
    различимы.
    """
    section = observed(doc, "declared_axis", kind=dict)
    if section is None:
        return ("slo_keepability, объявленная ось: НЕ ИЗМЕРЕНО — секции "
                "`declared_axis` в замере нет")
    tally = observed(section, "tally", kind=dict) or {}
    above = tally.get(slo_proposal.CURATED_ABOVE)
    findings = section.get("findings")
    abstained = section.get("abstained")
    return ("slo_keepability, объявленная ось (пара «агент × артефакт» по расписанию): "
            f"население {section.get('population')} · срок не ниже пола "
            f"{'НЕ ИЗМЕРЕНО' if above is None else above} · находок "
            f"{'НЕ ИЗМЕРЕНО' if findings is None else len(findings)} · ВОЗДЕРЖАНИЙ "
            f"{'НЕ ИЗМЕРЕНО' if abstained is None else len(abstained)} "
            "(артефакт за несколькими производителями — такт ОДНОГО про файл не отвечает)")


def declared_producer_labels(agents: list, artifact: str) -> list:
    """Кто ОБЪЯВЛЕН производителем артефакта. ЕДИНСТВЕННОЕ место этого счёта.

    Выделено из :func:`declared_axis_census` (ADR-817), потому что спрашивают его
    ДВА читателя: само правомочие (``slo_proposal.declared_axis_standing`` — через
    ЧИСЛО) и :func:`co_production_census` (через ИМЕНА, чтобы спросить у каждого
    производителя его прогоны). Копия счёта рядом с дверью — ровно та форма, на
    которой выжила мутация №2 батареи ADR-814.

    **Считаются РАЗНЫЕ агенты, а не вхождения в** ``produces``. Прежняя редакция
    складывала вхождения, и у неё был латентный дефект того же класса, который
    закрывает весь ADR-817: агент, объявивший один артефакт в ``produces`` ДВАЖДЫ,
    давал ``declared_producers = 2``, то есть выписывал себе воздержание в
    одиночку — находка гасилась опечаткой в конституции. Замер 26.10 на живой
    конституции: таких артефактов **0** из 231 (измерено и равно нулю, инв. #17),
    поэтому ни один вердикт правкой не двинут; дефект закрыт до появления
    населения, а не после.

    Пустое имя агента производителем не считается: обратиться к такому
    производителю за прогонами нечем, а в счёте он поднимал бы правомочие.
    """
    found: set = set()
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        label = str(agent.get("label") or "")
        if not label:
            continue
        for produced in (agent.get("produces") or []):
            if isinstance(produced, dict) and produced.get("artifact") == artifact:
                found.add(label)
    return sorted(found)


def co_production_actual(runs_by_producer: dict) -> tuple[str, str]:
    """Существует ли объявленное со-производство В ДЕЙСТВИТЕЛЬНОСТИ.

    Вопрос ADR-817 (заказ G816 п. 2) и ПРЕДМЕТ его — не срок годности, а
    **предпосылка воздержания** ADR-816. Воздержание говорит дословно: «артефакт
    объявлен за несколькими производителями — такт ОДНОГО из них не есть такт
    артефакта». Если в действительности идёт ОДИН, предпосылка ложна: такт
    артефакта и есть такт этого одного, и поагентное отрицание было ВЕРНО, а
    погасило его воздержание — заслуженно по ФОРМЕ и незаслуженно по СУТИ.

    **Правомочие остаётся конституционным, и эта дверь его не трогает.** Заказ
    G816 п. 2 требует мерить НАБЛЮДЁННЫМ списком производителей и при этом НЕ
    СВОДИТЬ оси. Поэтому здесь не вердикт пары, а ОТДЕЛЬНОЕ утверждение о
    предпосылке: ``slo_proposal.declared_axis_standing`` по-прежнему спрашивает
    только число ОБЪЯВЛЕННЫХ производителей и ответа этой двери не видит.

    **Вход — счёт прогонов по производителю**, ``None`` = НЕ НАБЛЮДАЛИ (причины
    перечислены в :data:`RUNS_UNOBSERVABLE`). Ноль и ``None`` здесь разное: ноль
    есть наблюдение («лог прочитан, своих прогонов в нём нет»), ``None`` —
    отсутствие наблюдения, и подстановка нуля сделала бы немого производителя
    доказательством мнимого со-производства.

    **Правило АСИММЕТРИЧНО — по той же причине, что и правомочие в ADR-816.**
    Двух наблюдённых производителей ДОСТАТОЧНО, чтобы со-производство
    существовало; третий ненаблюдённый ничего не отнимает, и ждать его значило бы
    объявлять «не измерено» там, где ответ уже получен. Обратная сторона
    несимметрична: чтобы сказать «идёт ОДИН», нужны все остальные — хоть один
    ненаблюдённый, и различить «один производитель» от «двух» нечем.

    Четыре исхода, и три последних различимы намеренно (инв. #17).
    """
    if not isinstance(runs_by_producer, dict) or not runs_by_producer:
        return CO_PRODUCTION_UNMEASURED, (
            "производителей не названо — существование со-производства "
            "судить не о чем")
    running: list = []
    silent: list = []
    unobserved: list = []
    for label in sorted(runs_by_producer):
        runs = runs_by_producer[label]
        if isinstance(runs, bool) or not isinstance(runs, int):
            unobserved.append(label)
        elif runs > 0:
            running.append(label)
        else:
            silent.append(label)
    # Асимметрия: ДВУХ свидетелей довольно, и ненаблюдённый третий их не отменяет.
    if len(running) >= 2:
        return CO_PRODUCTION_CONFIRMED, (
            f"прогоны наблюдены у {len(running)} производителей "
            f"({', '.join(running)}) — со-производство действительно, воздержание "
            f"заслуженно и по форме, и по сути")
    if unobserved:
        return CO_PRODUCTION_UNMEASURED, (
            f"прогоны НЕ НАБЛЮДАЛИ у {', '.join(unobserved)}; наблюдены у "
            f"{len(running)} — различить «производитель один» от «их несколько» "
            f"нечем, и ни воздержанием, ни находкой это не выдаётся")
    if len(running) == 1:
        return CO_PRODUCTION_NOMINAL, (
            f"объявлено производителей {len(runs_by_producer)}, прогоны идут у "
            f"ОДНОГО ({running[0]}); молчат {', '.join(silent)} — такт артефакта "
            f"и есть такт этого одного, поагентное отрицание было ВЕРНО, и "
            f"воздержание погасило его незаслуженно")
    return CO_PRODUCTION_NONE_RUNNING, (
        f"ни один из {len(runs_by_producer)} объявленных производителей "
        f"({', '.join(silent)}) прогонов не ведёт — со-производства нет, но нет и "
        f"такта: про СРОК это не говорит ничего")


def co_production_census(declared_axis: dict, agents: list,
                         runs_by_agent: dict) -> dict:
    """Перепись предпосылок ВОЗДЕРЖАНИЙ объявленной оси. Единственная её форма.

    **Население — артефакты, у которых правомочие БЫЛО применено к отрицанию**,
    и выбор этот назван, а не удобен (урок заказа G814 п. 4: прежде чем назвать
    число, спросить, о каком населении речь). Со-производимых артефактов в
    конституции 26.10 — **восемь**; воздержание же выписано ДВУМ, потому что у
    остальных шести пара и так выше пола и гасить было нечего. Вред — только
    погашенная находка, поэтому и меряется ровно то население, где он возможен.
    Восемь и два НЕ СКЛАДЫВАЮТСЯ и ни в одном числе этой секции не смешаны.

    **Единица населения — АРТЕФАКТ, а воздержаний было ЧЕТЫРЕ**, потому что
    воздержание выписывается ПАРЕ «агент × артефакт», а предпосылка одна на файл.
    Оба числа печатаются рядом: 4 пары на 2 артефакта.

    Воздержание вида ``declared_axis_standing_unmeasured`` из населения НЕ
    выпадает: там не посчитаны сами производители, значит и существование
    со-производства не судится — это третий исход с названной причиной, а не
    строка, которой в отчёте не стало.
    """
    abstained = observed(declared_axis, "abstained", kind=list)
    if abstained is None:
        return {"status": CO_PRODUCTION_UNMEASURED,
                "cause": "в объявленной оси нет перечня воздержаний (`abstained`)",
                "population": None, "tally": None, "rows": None}
    rows: list = []
    tally: dict = {}
    for artifact in sorted({r.get("artifact") for r in abstained
                            if isinstance(r, dict) and r.get("artifact")}):
        pairs = [r for r in abstained
                 if isinstance(r, dict) and r.get("artifact") == artifact]
        labels = declared_producer_labels(agents, artifact)
        if any(r.get("declared_vs_floor")
               == slo_proposal.DECLARED_STANDING_UNMEASURED for r in pairs):
            kind, why = CO_PRODUCTION_UNMEASURED, (
                "правомочие объявленной оси НЕ ИЗМЕРЕНО (производители не "
                "посчитаны) — существование со-производства не судится")
            runs = {}
        else:
            runs = {label: runs_by_agent.get(label) for label in labels}
            kind, why = co_production_actual(runs)
        tally[kind] = tally.get(kind, 0) + 1
        rows.append({
            "artifact": artifact,
            "abstained_pairs": len(pairs),
            "declared_producers": labels,
            "observed_runs": runs,
            "co_production": kind,
            "note": why,
        })
    return {
        "status": "OK",
        # ДВА числа, и они о РАЗНОМ: предпосылка одна на файл, а воздержание
        # выписано паре. Одно число на два предмета было бы ответом на третий,
        # никем не заданный вопрос.
        "population": len(rows),
        "abstained_pairs": len(abstained),
        "tally": tally,
        # Находка этой секции — ТОЛЬКО мнимое со-производство: воздержание
        # выписано, а предпосылки под ним нет.
        "findings": [r for r in rows if r["co_production"] in (
            CO_PRODUCTION_NOMINAL, CO_PRODUCTION_NONE_RUNNING)],
        # Каждый артефакт назван ПОИМЁННО со счётом прогонов каждого
        # производителя — тот же порядок, что у воздержаний ADR-816: «находок
        # нет» без имён неотличимо от «население пусто», и доказательство
        # положительного ответа тогда негде прочитать.
        "rows": rows,
    }


def co_production_line(doc: dict) -> str:
    """Строка ПРЕДПОСЫЛКИ воздержаний для шага 0-офис. Единственная её форма.

    Живёт здесь по той же причине, что и :func:`declared_axis_line` (ADR-816):
    инлайн-печать внутри ``findings_bridge.main`` лежит за ступенью переписей,
    которая на живом Маке идёт часами, и проверить её отдельно НЕЧЕМ, а любая
    опечатка в ней ушла бы в ``except`` моста как «перепись пропущена» — то есть
    молча, ровно тем fail-OPEN, против которого написан инв. #17.

    Секции нет ⇒ так и сказано, а не ноль: прибор старой версии и прибор без
    находок обязаны быть различимы.
    """
    section = observed(doc, "declared_co_production", kind=dict)
    if section is None:
        return ("slo_keepability, предпосылка воздержаний: НЕ ИЗМЕРЕНО — секции "
                "`declared_co_production` в замере нет")
    if section.get("status") != "OK":
        return ("slo_keepability, предпосылка воздержаний: НЕ ИЗМЕРЕНО — "
                f"{section.get('cause') or 'причина не названа'}")
    tally = observed(section, "tally", kind=dict) or {}
    findings = section.get("findings")
    population = section.get("population")
    pairs = section.get("abstained_pairs")
    return ("slo_keepability, предпосылка воздержаний объявленной оси "
            "(со-производство действительно?): артефактов "
            f"{'НЕ ИЗМЕРЕНО' if population is None else population} на "
            f"{'НЕ ИЗМЕРЕНО' if pairs is None else pairs} воздержавшихся пар · "
            f"действительно {tally.get(CO_PRODUCTION_CONFIRMED, 'НЕ ИЗМЕРЕНО')} · "
            f"МНИМО {'НЕ ИЗМЕРЕНО' if findings is None else len(findings)} · "
            f"не измерено {tally.get(CO_PRODUCTION_UNMEASURED, 0)} "
            "(мнимое = воздержание выписано, а идёт ОДИН производитель — "
            "поагентная находка погашена незаслуженно)")


def declared_axis_census(agents: list, medians: dict) -> dict:
    """ОБЪЯВЛЕННАЯ ось: пара «АГЕНТ × артефакт» по расписанию из конституции.

    Соседняя ось этого же прибора (всё остальное в модуле) судит АРТЕФАКТ по
    НАБЛЮДЁННОМУ такту. Эта судит АГЕНТА по ОБЪЯВЛЕННОМУ расписанию, и две оси
    живут раздельными секциями НАМЕРЕННО: заказ G815 п. 2 запрещает сводить их в
    одно число, потому что у со-производимого артефакта они расходятся ВЕРНО —
    каждая права о своём предмете.

    Правила здесь своего нет: пара судится единственной дверью
    ``slo_proposal.audit_declared``, которая сама берёт пол у ``architect_floor``,
    сравнение у ``audit_curated``, а правомочие — у числа ОБЪЯВЛЕННЫХ
    производителей. Число это считается ЗДЕСЬ, по конституции, и наблюдённый
    список производителей (``rows[].producers``) для него не трогается: взять его
    оттуда и было бы тем самым сведением осей.

    Медиана передаётся только затем, чтобы различить два состояния «ниже пола»
    (нарушено против «запаса нет»), — ту же роль она играет и у соседней оси.
    Медианы нет ⇒ третий исход у ``audit_curated``, а не подстановка.
    """
    tally: dict = {}
    pairs: list = []
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        schedule = agent.get("schedule")
        for pr in (agent.get("produces") or []):
            if not isinstance(pr, dict):
                continue
            art, slo = pr.get("artifact"), pr.get("slo_hours")
            if not art or not isinstance(slo, (int, float)) or isinstance(slo, bool):
                continue
            declared_producers = len(declared_producer_labels(agents, art))
            axis, note = slo_proposal.audit_declared(
                slo, schedule, medians.get(art), declared_producers)
            tally[axis] = tally.get(axis, 0) + 1
            pairs.append({"agent": agent.get("label"), "artifact": art,
                          "slo_hours": slo, "schedule": schedule,
                          "declared_producers": declared_producers,
                          "declared_vs_floor": axis, "note": note})
    return {
        "population": len(pairs),
        "tally": tally,
        # Находка объявленной оси — только та, у которой есть ПРЕДМЕТ: один
        # объявленный производитель, и он со сроком не справляется.
        "findings": [r for r in pairs if r["declared_vs_floor"] in (
            slo_proposal.CURATED_BELOW, slo_proposal.CURATED_MARGIN_ONLY)],
        # Воздержания печатаются ПОИМЁННО, а не только счётчиком: «ось об этом не
        # отвечает» обязано быть видно, иначе четыре пары просто исчезнут из
        # отчёта и неотличимы станут от «их не было».
        "abstained": [r for r in pairs if r["declared_vs_floor"] in (
            slo_proposal.DECLARED_CO_PRODUCED,
            slo_proposal.DECLARED_STANDING_UNMEASURED)],
    }


def measure(manifest_path: Optional[Path] = None, *, log_dir: Path = Path("/tmp"),
            scripts_dir: Optional[Path] = None, now: Optional[datetime] = None,
            window_hours: float = WINDOW_HOURS, root: Optional[Path] = None) -> dict:
    """Замер по КАЖДОМУ артефакту конституции, у которого объявлен срок годности.

    **Предмет — АРТЕФАКТ, а не агент**, и это не вкусовщина: срок обещан ФАЙЛУ,
    а служить ему могут несколько производителей. ``data/deployment_acceptance.json``
    пишут ДВА суточных агента (`system_health_morning` и `system_health_evening`),
    и по отдельности каждый отстаёт от 15-часового срока вдвое, а вместе — нет.
    Судить такую пару поагентно значило бы печатать находку там, где обещание
    выдерживается.

    Поднимает :class:`Unmeasured`, если замера нет вовсе: конституция не
    прочитана либо населения у вопроса нет.
    """
    base = Path(root) if root is not None else _REPO_ROOT
    manifest = Path(manifest_path) if manifest_path is not None else base / "architecture" / "manifest.json"
    scripts = Path(scripts_dir) if scripts_dir is not None else base / "scripts"
    try:
        payload = json.loads(manifest.read_text())
    except (OSError, ValueError) as exc:
        raise Unmeasured(f"конституция не прочитана ({manifest}): {exc}") from exc
    agents = payload.get("agents")
    if not isinstance(agents, list) or not agents:
        raise Unmeasured(f"в конституции нет перечня агентов ({manifest})")

    # Срок у артефакта живёт в ДВУХ домах конституции: верхний перечень
    # `artifacts[]` и `agents[].produces[]`. Число верхнего дома берётся у
    # ЕДИНСТВЕННОГО читателя (`manifest_slo`, ADR-342) — второй копии правила
    # «какой срок в силе» здесь нет; и он же применяет правило «срок отставного
    # артефакта не в силе».
    top_slo, why = slo_hours_by_path(manifest)
    if why:
        raise Unmeasured(f"срок годности НЕ прочитан: {why}")

    # Окно наблюдения — ПОЛ, а не потолок: окно короче самого длинного
    # объявленного срока сделало бы находку недостижимой ПО ПОСТРОЕНИЮ у тех
    # артефактов, чей срок длиннее (урок ADR-543 — но здесь слепота была бы
    # СВОЕЙ, а не чужой). Поэтому окно РАСШИРЯЕТСЯ до самого длинного срока, и
    # оба числа печатаются: запрошенное и действующее.
    longest = max([float(v) for v in top_slo.values()] + [
        float(pr["slo_hours"]) for agent in agents if isinstance(agent, dict)
        for pr in (agent.get("produces") or [])
        if isinstance(pr, dict) and isinstance(pr.get("slo_hours"), (int, float))] or [0.0])
    effective_window = max(float(window_hours), longest)

    top_producer: dict = {}
    for entry in payload.get("artifacts") or []:
        if isinstance(entry, dict) and entry.get("path"):
            top_producer[str(entry["path"])] = str(entry.get("producer") or "")

    # Обход агентов: кто ЖИВОЙ, что он обещает и где лежит запись его прогонов.
    declared: dict = {}
    excluded = {"retired": 0, "designed": 0, "intent_absent": 0}
    no_slo = 0
    seen_by_agent: dict = {}
    active_labels: set = set()
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        label = str(agent.get("label") or "")
        intent = agent.get("intent")
        produces = [p for p in (agent.get("produces") or []) if isinstance(p, dict)]
        declares = [p for p in produces if isinstance(p.get("slo_hours"), (int, float))]
        no_slo += len(produces) - len(declares)
        if intent != ACTIVE:
            if declares:
                key = intent if intent in ("retired", "designed") else "intent_absent"
                excluded[key] = excluded.get(key, 0) + len(declares)
            continue
        active_labels.add(label)
        for produced in declares:
            path = str(produced.get("artifact") or "")
            if path:
                declared.setdefault(path, []).append(
                    {"agent": label, "slo_hours": float(produced["slo_hours"])})
        if label in seen_by_agent:
            continue
        name, address_cause = log_address(str(agent.get("program") or ""), scripts)
        schedule_hours = parse_schedule(agent.get("schedule"))
        if name is None:
            seen_by_agent[label] = {"starts": [], "cause": address_cause,
                                    "schedule_hours": schedule_hours, "record": None,
                                    "median": None, "schedule": agent.get("schedule")}
            continue
        record = Path(log_dir) / f"spa_{name}.log"
        seen = run_starts(record, name, now=now, window_hours=effective_window)
        spans = periods_hours(seen["starts"])
        seen_by_agent[label] = {
            **seen, "record": str(record), "schedule_hours": schedule_hours,
            "schedule": agent.get("schedule"),
            "median": statistics.median(spans) if spans else None}

    population = sorted(set(declared) | set(top_slo))
    rows: list = []
    for path in population:
        declarations = [{"home": "agents[].produces", **d} for d in declared.get(path, [])]
        if path in top_slo:
            declarations.append({"home": "artifacts[]", "agent": top_producer.get(path, ""),
                                 "slo_hours": float(top_slo[path])})
        hours = sorted({d["slo_hours"] for d in declarations})
        if not hours:
            no_slo += 1
            continue
        # Обещание в силе — САМОЕ КОРОТКОЕ из объявленных (fail-CLOSED): на
        # него читатель вправе опереться, а расхождение домов называется рядом.
        binding = hours[0]
        producers = sorted({d["agent"] for d in declared.get(path, [])})
        if not producers:
            named = top_producer.get(path, "")
            producers = [named] if named in active_labels else []
        shared = {
            "artifact": path, "slo_hours": binding, "slo_declared": hours,
            "slo_disagreement": len(hours) > 1, "declarations": declarations,
            "producers": producers,
        }
        if not producers:
            rows.append({**shared, "verdict": UNMEASURED, "cause": PRODUCER_NOT_DECLARED,
                         "runs": 0, "observed_max_hours": None,
                         "observed_median_hours": None, "span_hours": None,
                         "schedule_axis": SCHEDULE_OBSERVATION_ABSENT, "records": [],
                         "foreign_banners": 0, "unparsable_banners": 0,
                         "future_banners": 0, "cadence_axis": CADENCE_UNMEASURED,
                         "periods": 0, "periods_over_slo": 0,
                         # Производителя нет ⇒ такта нет ⇒ пола нет. Причина
                         # НАЗВАНА, а не подставлена из расписания (инв. #17).
                         **_derived(None, binding)})
            continue
        merged: list = []
        causes: list = []
        records: list = []
        axis_votes: list = []
        ratio = None
        dropped = {"foreign_banners": 0, "unparsable_banners": 0, "future_banners": 0}
        for label in producers:
            seen = seen_by_agent.get(label) or {"starts": [], "cause": ADDRESS_UNRESOLVED}
            merged.extend(seen.get("starts") or [])
            if seen.get("cause"):
                causes.append(seen["cause"])
            if seen.get("record"):
                records.append(seen["record"])
            axis_votes.append(_schedule_axis(seen.get("schedule_hours"), seen.get("median"),
                                             seen.get("schedule")))
            # ВЕЛИЧИНА расхождения, а не только его факт: период launchd всегда
            # не короче «интервал + длительность прогона», поэтому САМ факт почти
            # всегда верен и ничего не говорит. Решает отношение: ADR-506 нашёл
            # ×1.27 (6ч объявлено, 7.6ч наблюдено), а не ×1.001.
            for key in dropped:
                dropped[key] += int(seen.get(key) or 0)
            declared_hours, middle_hours = seen.get("schedule_hours"), seen.get("median")
            if declared_hours and middle_hours is not None:
                here = middle_hours / declared_hours
                ratio = here if ratio is None else max(ratio, here)
        merged.sort()
        spans = periods_hours(merged)
        widest = max(spans) if spans else None
        middle = statistics.median(spans) if spans else None
        span = ((merged[-1] - merged[0]).total_seconds() / 3600.0) if len(merged) >= 2 else None
        # Производителей может быть несколько: находка оси сильнее молчания,
        # а «не разобрали» сильнее «не наблюдали» — иначе один немой
        # производитель прятал бы форму, которую прибор не читает.
        axis = next((vote for vote in (SCHEDULE_EXCEEDS, SCHEDULE_WITHIN,
                                       SCHEDULE_UNPARSED, SCHEDULE_NOT_PERIODIC,
                                       SCHEDULE_OBSERVATION_ABSENT)
                     if vote in axis_votes), SCHEDULE_OBSERVATION_ABSENT)
        # Ось ТАКТА (ADR-813). Считается РЯДОМ с вердиктом и его не меняет:
        # вердикт стои́т на максимуме, ось отвечает, какое из двух состояний
        # его подняло. Ниже `CADENCE_MIN_PERIODS` различать нечем — максимум
        # сам входит в медиану, и это ТРЕТИЙ ИСХОД, а не «такт держит».
        over = sum(1 for value in spans if value > binding)
        if widest is None or middle is None:
            cadence = CADENCE_UNMEASURED
        elif widest <= binding:
            cadence = CADENCE_KEEPS
        elif len(spans) < CADENCE_MIN_PERIODS:
            cadence = CADENCE_UNMEASURED
        elif middle > binding:
            cadence = CADENCE_CANNOT_KEEP
        else:
            cadence = CADENCE_OUTLIER
        shared = {
            **shared, "runs": len(merged), "records": records, "schedule_axis": axis,
            "schedule_ratio": None if ratio is None else round(ratio, 4), **dropped,
            "observed_max_hours": None if widest is None else round(widest, 3),
            "observed_median_hours": None if middle is None else round(middle, 3),
            "span_hours": None if span is None else round(span, 3),
            "producer_causes": sorted(set(causes)),
            "cadence_axis": cadence,
            # Числа, по которым читатель вправе ПЕРЕПРОВЕРИТЬ ось, а не поверить
            # ярлыку: сколько периодов наблюдено и сколько из них срок превысили.
            "periods": len(spans), "periods_over_slo": over,
            # ВЫВЕДЕННЫЙ срок (ADR-814). Считается у КАЖДОЙ пары, а не только у
            # находок: ответ «пол ниже объявленного» тоже ответ, и прятать его
            # означало бы отдавать читателю только половину сравнения.
            **_derived(middle, shared.get("slo_hours")),
        }
        if widest is None:
            # Ни один производитель не дал периода — причина НАЗВАНА, и если
            # производителей несколько, названы все: они чинятся разным.
            rows.append({**shared, "verdict": UNMEASURED,
                         "cause": "+".join(sorted(set(causes))) or CAUSE_NOT_NAMED})
        elif widest > binding:
            rows.append({**shared, "verdict": UNKEEPABLE, "cause": None})
        elif span is not None and span < binding:
            # Зелёный ПО ПОСТРОЕНИЮ (урок ADR-543): разрыв длиннее срока в такое
            # окно не поместится, значит «нарушений нет» тут ничего не утверждает.
            rows.append({**shared, "verdict": UNMEASURED, "cause": WINDOW_SHORTER_THAN_SLO})
        else:
            rows.append({**shared, "verdict": KEEPABLE, "cause": None})

    if not rows:
        raise Unmeasured("населения у вопроса нет: ни одного артефакта с объявленным "
                         "сроком годности в конституции")

    tally = {KEEPABLE: 0, UNKEEPABLE: 0, UNMEASURED: 0}
    causes: dict = {}
    axes = {SCHEDULE_WITHIN: 0, SCHEDULE_EXCEEDS: 0, SCHEDULE_UNPARSED: 0,
            SCHEDULE_NOT_PERIODIC: 0, SCHEDULE_OBSERVATION_ABSENT: 0}
    # Ось такта считается ПО НАХОДКАМ, а не по всему населению: вопрос «какое
    # состояние дало находку» у пары без находки не имеет предмета, и считать
    # там `cadence_keeps` значило бы смешать «находки нет» с «находка от
    # выброса». Полный разрез по населению лежит построчно в `rows`.
    cadence_axes = {CADENCE_CANNOT_KEEP: 0, CADENCE_OUTLIER: 0, CADENCE_UNMEASURED: 0}
    # Разрез «курированный срок против ВЫВЕДЕННОГО пола» (ADR-814) считается по
    # ВСЕМУ населению, а не по находкам: срок ниже пола у пары без находки —
    # тоже ответ (пара просто ещё не успела нарушить обещание).
    curated_axes = {slo_proposal.CURATED_ABOVE: 0, slo_proposal.CURATED_BELOW: 0,
                    slo_proposal.CURATED_MARGIN_ONLY: 0, slo_proposal.CURATED_UNMEASURED: 0}
    no_margin = 0
    disagreements = 0
    worst_ratio: dict = {}
    for row in rows:
        here = row.get("schedule_ratio")
        # `or 0` здесь был бы подстановкой наблюдения (инв. #17): «отношения ещё
        # не было» и «отношение равно нулю» суть разные положения дел, даже когда
        # сравнение их не различает.
        best = worst_ratio.get("ratio")
        if isinstance(here, (int, float)) and (best is None or here > best):
            worst_ratio = {"ratio": here, "artifact": row.get("artifact"),
                           "producers": row.get("producers")}
        tally[row["verdict"]] += 1
        # Причин у артефакта может быть НЕСКОЛЬКО (производителей несколько),
        # поэтому сумма этой оси не обязана равняться числу неизмеренных.
        for cause in (row.get("cause") or "").split("+"):
            if cause:
                causes[cause] = causes.get(cause, 0) + 1
        axes[row["schedule_axis"]] = axes.get(row["schedule_axis"], 0) + 1
        if row["verdict"] == UNKEEPABLE:
            key = row.get("cadence_axis") or CADENCE_UNMEASURED
            cadence_axes[key] = cadence_axes.get(key, 0) + 1
        bucket = row.get("curated_vs_floor") or slo_proposal.CURATED_UNMEASURED
        curated_axes[bucket] = curated_axes.get(bucket, 0) + 1
        if row.get("slo_disagreement"):
            disagreements += 1
        widest = row.get("observed_max_hours")
        if (row["verdict"] == KEEPABLE and isinstance(widest, (int, float))
                and row["slo_hours"] < MARGIN_FACTOR * widest):
            no_margin += 1

    findings = [r for r in rows if r["verdict"] == UNKEEPABLE]
    # Сортировка ДВУХКЛЮЧЕВАЯ: сначала те, чей ТАКТ срок выдержать не способен
    # (их чинят сроком или расписанием), затем нарушенные выбросом. Прежний
    # порядок по одному отношению ставил первыми самые громкие выбросы — то
    # есть ровно те строки, по которым делать нечего.
    _rank = {CADENCE_CANNOT_KEEP: 0, CADENCE_UNMEASURED: 1, CADENCE_OUTLIER: 2}
    findings.sort(key=lambda r: (
        _rank.get(r.get("cadence_axis"), 1),
        -(r["observed_max_hours"] / r["slo_hours"]) if r["slo_hours"] else 0))
    verdict = ("every_declared_slo_keepable"
               if tally[UNKEEPABLE] == 0 and tally[UNMEASURED] == 0
               else "declared_slo_unkeepable" if tally[UNKEEPABLE]
               else "tact_not_observed")
    # Счёт прогонов ПО ПРОИЗВОДИТЕЛЮ — вход вопроса ADR-817. Ноль и `None`
    # здесь разное (инв. #17): ноль есть наблюдение («лог прочитан, своих
    # прогонов нет»), `None` — отсутствие наблюдения. Агент НЕ `active` в
    # `seen_by_agent` не попадает вовсе, и его прогоны остаются `None`: «отставка
    # объявлена» не есть «прогонов не наблюдали», и выдавать объявление за
    # наблюдение значило бы ответить конституцией на вопрос про действительность.
    runs_by_agent = {
        label: (None if (seen.get("cause") in RUNS_UNOBSERVABLE)
                else len(seen.get("starts") or []))
        for label, seen in seen_by_agent.items()}
    declared_section = declared_axis_census(
        agents, {r["artifact"]: r.get("observed_median_hours") for r in rows})
    return {
        "status": "OK",
        "generated_at": _stamp(now),
        "population": len(rows),
        "tally": tally,
        "unmeasured_causes": causes,
        "schedule_axis": axes,
        "cadence_axis": cadence_axes,
        "cadence_min_periods": CADENCE_MIN_PERIODS,
        "curated_vs_floor": curated_axes,
        "worst_schedule_ratio": worst_ratio or None,
        "slo_disagreements": disagreements,
        "no_margin_for_one_miss": no_margin,
        "margin_factor": MARGIN_FACTOR,
        "window_hours": float(window_hours),
        "effective_window_hours": effective_window,
        "excluded_by_intent": excluded,
        "produces_without_slo": no_slo,
        "verdict": verdict,
        # ОБЪЯВЛЕННАЯ ось — ОТДЕЛЬНАЯ секция (ADR-816). В `tally`/`verdict`
        # выше она не входит ни одним числом: предмет у неё другой (агент, а не
        # артефакт), и сложение их было бы ответом на третий, никем не заданный
        # вопрос.
        "declared_axis": declared_section,
        # ПРЕДПОСЫЛКА воздержаний объявленной оси — ТРЕТЬЯ секция, и она тоже не
        # входит в `tally`/`verdict` ни одним числом (ADR-817, заказ G816 п. 2).
        # Предмет у неё не срок и не пара, а ПРАВДИВОСТЬ довода, которым пара
        # была снята с суда; сложить её с вердиктами значило бы ответить на
        # четвёртый, никем не заданный вопрос.
        "declared_co_production": co_production_census(
            declared_section, agents, runs_by_agent),
        "rows": rows,
        "findings": findings,
        "measured_from": {"manifest": str(manifest), "log_dir": str(log_dir),
                          "scripts_dir": str(scripts)},
        "not_reported": [
            "моменты ЗАПИСИ артефакта (период мерится СТАРТ→СТАРТ прогона)",
            "вторая запись о прогонах (launchctl runs — без отметок времени)",
            "верность самого срока (цену опоздания назначают две роли, ADR-158)",
            "производитель вне конституции",
            "ПИШЕТ ли производитель артефакт на самом деле (ADR-817): "
            "существование со-производства меряется ПРОГОНАМИ объявленных "
            "производителей, а истории `mtime` система не хранит — «агент идёт» "
            "и «агент пишет этот файл» разные утверждения",
            "ЧЕРЕДУЮТСЯ ли прогоны со-производителей (ADR-817): два агента, "
            "идущие в один и тот же час, дают такт артефакта не короче своего, и "
            "это предмет СОСЕДНЕЙ оси (наблюдённый такт артефакта) — сводить их "
            "запрещено заказом G815 п. 2",
            "прогоны со-производителя, объявленного НЕ `active` (ADR-817): его "
            "лог не читается вовсе, и счёт остаётся `None` — отставка есть "
            "объявление, а не наблюдение",
            "ПРИЧИНА выброса (хост спал · перезагрузка · разовый долгий прогон) — "
            "ось такта называет СОСТОЯНИЕ, а не причину",
            "ПЕРЕНОСИМОСТЬ потолка запаса на наблюдённую базу (ADR-814/815): "
            "`_MARGIN_HOURS` калиброван по ОБЪЯВЛЕННЫМ тактам, и что он верен поверх "
            "наблюдённой медианы — допущение, а не замер; с ADR-815 потолок связывает "
            "запас только у производителей с тактом длиннее 2 ч",
            "ПОТОЛОК цены опоздания (`slo_proposal.hoi_ceiling`): выведенный пол есть "
            "«что физически возможно», а не «что допустимо»; согласование ролей "
            "(ADR-158) прибор не делает",
        ],
    }


def run(root: str | Path = _REPO_ROOT, *, data_dir: Optional[Path] = None,
        dest: Optional[Path] = None, write: bool = True,
        log_dir: Path = Path("/tmp"), now: Optional[datetime] = None, **kw) -> dict:
    """Один замер для ступени моста (`findings_bridge.CENSUS_STAGE`).

    Такта у ступени НЕТ намеренно: замер есть разбор текстовых логов в одном
    процессе, и платить за него такт значило бы отвечать вчерашним числом там,
    где сегодняшнее стои́т доли секунды.
    """
    base = Path(root)
    source = Path(data_dir) if data_dir is not None else base / "data"
    target = Path(dest) if dest is not None else source / ARTIFACT
    try:
        doc = measure(root=base, log_dir=Path(log_dir), now=now, **kw)
    except Unmeasured as exc:
        doc = {"status": "UNMEASURED", "reason": str(exc), "generated_at": _stamp(now)}
    if write:
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(doc, str(target))
    return {"measured": True, "doc": doc, "artifact": str(target)}


def report(doc: dict, max_rows: int = 12) -> list:
    """Отрисовка для шага 0-офис. Делегирована ПРОИЗВОДИТЕЛЮ (ADR-158)."""
    lines: list = []
    if str(doc.get("status")) != "OK":
        lines.append(f"НЕ ИЗМЕРЕНО: {doc.get('reason', 'причина не названа')}")
        lines.append("  про объявленные сроки НЕ СКАЗАНО НИЧЕГО — выдать это за "
                     "«сроки выдерживаются» нельзя")
        return lines
    tally = observed(doc, "tally", kind=dict) or {}

    def _num(key):
        value = tally.get(key)
        return "НЕ ИЗМЕРЕНО" if not isinstance(value, (int, float)) else int(value)

    lines.append(
        f"Выдерживаем ли объявленный срок годности (заказ G94): ВЫДЕРЖИВАЕМ "
        f"{_num(KEEPABLE)} · НЕ ВЫДЕРЖИВАЕМ {_num(UNKEEPABLE)} · ТАКТ НЕ НАБЛЮДЁН "
        f"{_num(UNMEASURED)} из {doc.get('population')} артефакт(ов) с объявленным сроком")
    cadence = observed(doc, "cadence_axis", kind=dict) or {}
    if tally.get(UNKEEPABLE):
        # Разрез находки ДО перечня: 139 одинаковых строк разбирать дороже, чем
        # 69 настоящих, и до #936 читатель не мог их отличить вовсе.
        lines.append(
            f"  из них ТАКТ не способен выдержать срок: "
            f"{cadence.get(CADENCE_CANNOT_KEEP, 'НЕ ИЗМЕРЕНО')} (чинится сроком или "
            f"расписанием) · срок нарушил ОДИН разрыв при годном такте: "
            f"{cadence.get(CADENCE_OUTLIER, 'НЕ ИЗМЕРЕНО')} · периодов меньше "
            f"{doc.get('cadence_min_periods')}, различать нечем: "
            f"{cadence.get(CADENCE_UNMEASURED, 'НЕ ИЗМЕРЕНО')}")
    #: Слово про КАЖДОЕ состояние — своё. Прежняя строка говорила «протухает ПО
    #: ПОСТРОЕНИЮ» всем находкам подряд, и на замере 25.10 это было неверно у
    #: 70 из 139: у них медиана периода срок ДЕРЖИТ.
    _VERB = {
        CADENCE_CANNOT_KEEP: "артефакт протухает ПО ПОСТРОЕНИЮ — медиана периода "
                             "срок НЕ держит",
        CADENCE_OUTLIER: "такт срок ДЕРЖИТ (медиана внутри) — обещание нарушил ОДИН "
                         "разрыв; причина выброса прибором НЕ измерена",
        CADENCE_UNMEASURED: "периодов меньше порога — отличить выброс от такта НЕЧЕМ "
                            "(не «протухает по построению»)",
        "cadence_axis_absent": "состояние такта НЕ ИЗМЕРЕНО: отчёт написан производителем "
                               "ДО ADR-813 и про ось не говорит ничего",
    }
    for row in (doc.get("findings") or [])[:max_rows]:
        # Ключа НЕТ вовсе ≠ «ось измерена и неразличима»: артефакт, написанный
        # производителем ДО ADR-813, про состояние не говорит ничего, и выдать
        # его молчание за замер значило бы повторить разбираемый дефект на один
        # этаж выше. Эти отчёты переписываются следующим тактом бегуна.
        axis = row.get("cadence_axis") or "cadence_axis_absent"
        lines.append(
            f"  [{UNKEEPABLE}/{axis}] {row.get('artifact')} (пишут: "
            f"{', '.join(row.get('producers') or []) or 'НЕ ИЗМЕРЕНО'}): объявлено "
            f"{row.get('slo_hours')}ч, наблюдённый максимум {row.get('observed_max_hours')}ч "
            f"(медиана {row.get('observed_median_hours')}ч по {row.get('runs')} прогон(ам) "
            f"ВСЕХ производителей; срок превысили {row.get('periods_over_slo')} из "
            f"{row.get('periods')} период(ов)) — "
            + _VERB.get(axis, "состояние такта НЕ НАЗВАНО")
            # ВЫВЕДЕННЫЙ срок печатается только тому состоянию, которое сроком
            # и лечится. У выброса (`cadence_keeps_outlier_broke`) печатать его
            # значило бы предлагать проглотить разрыв, причина которого НЕ
            # измерена, — ровно то, что ADR-813 запретил делать сроком.
            + (f"; срок, который такт выдержать СПОСОБЕН: "
               f"{row.get('derived_slo_hours')}ч ({row.get('derived_slo_basis')})"
               if axis == CADENCE_CANNOT_KEEP else ""))
    extra = len(doc.get("findings") or []) - max_rows
    if extra > 0:
        lines.append(f"  … ещё {extra} пар(ы) того же вида (полный перечень — `--json`)")
    curated = observed(doc, "curated_vs_floor", kind=dict)
    if curated is None:
        lines.append("  курированный срок против ВЫВЕДЕННОГО пола: НЕ ИЗМЕРЕНО — отчёт "
                     "написан производителем ДО ADR-814 и про пол не говорит ничего")
    else:
        lines.append(
            f"  курированный срок против ВЫВЕДЕННОГО пола (ADR-814, в сумму вердиктов НЕ "
            f"входит): ниже пола И медиана его ПРЕВЫШАЕТ "
            f"{curated.get(slo_proposal.CURATED_BELOW, 'НЕ ИЗМЕРЕНО')} (лечится сроком) · "
            f"ниже пола, но такт обещание ДЕРЖИТ "
            f"{curated.get(slo_proposal.CURATED_MARGIN_ONLY, 'НЕ ИЗМЕРЕНО')} (запаса на "
            f"ОДИН ПРОПУСК у срока нет, ADR-815) · не ниже "
            f"{curated.get(slo_proposal.CURATED_ABOVE, 'НЕ ИЗМЕРЕНО')} · пол НЕ ВЫВЕДЕН "
            f"{curated.get(slo_proposal.CURATED_UNMEASURED, 'НЕ ИЗМЕРЕНО')}")
    causes = observed(doc, "unmeasured_causes", kind=dict) or {}
    if causes:
        lines.append("  такт НЕ наблюдён, по причинам: " + " · ".join(
            f"{key} {value}" for key, value in sorted(causes.items())))
    axes = observed(doc, "schedule_axis", kind=dict) or {}
    worst = observed(doc, "worst_schedule_ratio", kind=dict) or {}
    lines.append("  ось «расписание против наблюдения» (в сумму НЕ входит): " + " · ".join(
        f"{key} {value}" for key, value in sorted(axes.items())))
    lines.append(
        "  ВЕЛИЧИНА расхождения (сам факт почти всегда верен — launchd считает от "
        "завершения): худшее отношение "
        + ("НЕ ИЗМЕРЕНО" if not worst else
           f"×{worst.get('ratio')} у {worst.get('artifact')} "
           f"({', '.join(worst.get('producers') or [])})"))
    lines.append(
        f"  срок объявлен ДВАЖДЫ и числа РАЗНЫЕ у {doc.get('slo_disagreements')} артефакт(ов) "
        f"(в силе самое короткое — fail-CLOSED)")
    lines.append(
        f"  запаса на один пропуск нет у {doc.get('no_margin_for_one_miss')} артефакт(ов) "
        f"(пол Архитектора такт × {doc.get('margin_factor')}, ADR-158 — ОСЬ, не вердикт); "
        f"окно наблюдения {doc.get('effective_window_hours')}ч "
        f"(запрошено {doc.get('window_hours')}ч, расширено до самого длинного срока)")
    lines.append("  НЕ ДОКЛАДЫВАЕТ: " + " · ".join(doc.get("not_reported") or []))
    lines.append("  ADVISORY: прибор только ЧИТАЕТ")
    return lines


def format_report(doc: dict, max_rows: int = 8) -> list:
    return ["   " + line for line in report(doc, max_rows=max_rows)]


def main(argv: Optional[list] = None, *, now: Optional[datetime] = None) -> int:
    """CLI. ``now`` — ЧАСЫ ВХОДОМ (`.claude/rules/deployment.md`, приём №1).

    Параметр keyword-only и в проде не передаётся НИКОГДА: его единственный
    вызывающий — тест, которому иначе нечем закрепить обе стороны сравнения.
    До #936 этого параметра не было, и `main` был ЕДИНСТВЕННОЙ дверью модуля
    со стенными часами при том, что `measure` и `run` часы принимают обе. Файл
    набора помечен `FROZEN-DATE-OK: injected-clock`, и для этой двери претензия
    была НЕВЕРНА: отметки стенда считаются от `_ANCHOR` (03.10), окно по
    умолчанию 168 ч, поэтому `test_everything_keepable_exits_zero` обязан был
    покраснеть около 10.10 — и покраснел, от сдвига КАЛЕНДАРЯ, а не кода
    (замер 25.10: красный на чистом `origin/main`). Соседние три теста того же
    класса при этом остались ЗЕЛЁНЫМИ ВХОЛОСТУЮ: вне окна прогонов не видно
    вовсе, вердикт становился `fewer_than_two_runs`, и код 1 они получали не за
    то, что проверяли. Это ровно «та же бомба, только с запиской».
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", default=None, help="путь к architecture/manifest.json")
    parser.add_argument("--log-dir", default="/tmp", help="каталог записей прогонов")
    parser.add_argument("--scripts-dir", default=None, help="каталог обёрток агентов")
    parser.add_argument("--window-hours", type=float, default=WINDOW_HOURS)
    parser.add_argument("--out", default=None, help="куда записать артефакт (по умолчанию не писать)")
    parser.add_argument("--json", action="store_true", help="печатать замер как JSON")
    args = parser.parse_args(argv)
    try:
        doc = measure(Path(args.manifest) if args.manifest else None,
                      log_dir=Path(args.log_dir),
                      scripts_dir=Path(args.scripts_dir) if args.scripts_dir else None,
                      window_hours=args.window_hours, now=now)
    except Unmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}")
        print("  про объявленные сроки НЕ СКАЗАНО НИЧЕГО")
        return 2
    if args.out:
        atomic_save(doc, str(args.out))
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        for line in report(doc):
            print(line)
    tally = doc.get("tally") or {}
    return 1 if (tally.get(UNKEEPABLE) or tally.get(UNMEASURED)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
