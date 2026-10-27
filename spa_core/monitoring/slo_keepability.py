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
import importlib.util
import json
import re
import statistics
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.monitoring import artifact_io_scan  # noqa: E402
from spa_core.monitoring import call_provenance  # noqa: E402
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
#:
#: **Литерал ОДИН** (ADR-818): правило это до сегодня исполняла только соседняя
#: ось (`measure` ниже), а ОБЪЯВЛЕННАЯ ось про `intent` не спрашивала вовсе и
#: судила сроки отставных агентов — 9 пар из 231. Теперь его спрашивают оба,
#: через единственную дверь `slo_proposal.producer_standing`, и своей копии
#: литерала здесь больше нет.
ACTIVE = slo_proposal.PRODUCER_ACTIVE

#: Совпадает ли ОБЪЯВЛЕННОЕ со-производство с ДЕЙСТВИТЕЛЬНЫМ (ADR-817, заказ
#: G816 п. 2). Предмет — ПРЕДПОСЫЛКА воздержания ADR-816, а НЕ срок годности:
#: воздержание говорит «артефакт объявлен за несколькими производителями, такт
#: ОДНОГО про файл не отвечает», и если в действительности идёт один, то
#: предпосылка ложна, а поагентное отрицание было ВЕРНО.
CO_PRODUCTION_CONFIRMED = "declared_co_production_confirmed"
CO_PRODUCTION_NOMINAL = "declared_co_production_nominal_only"
CO_PRODUCTION_NONE_RUNNING = "declared_co_production_no_producer_running"
CO_PRODUCTION_UNMEASURED = "declared_co_production_unmeasured"

#: Ключи, которые суть ОТМЕТКА ЗАПИСИ артефакта — вторая проба вопроса ADR-819
#: («пишет ли файл ещё кто-то»). Перечень ЗАМКНУТ намеренно: угадывать по имени
#: ключа значило бы выдавать предметную дату за время записи.
WRITE_STAMP_KEYS = ("generated_at", "updated_at", "last_updated", "written_at",
                    "measured_at", "timestamp")

#: ПРЕДМЕТНЫЕ даты, исключённые из второй пробы НАМЕРЕННО, и исключение это
#: ИЗМЕРЕНО, а не предположено: `data/dfb/pools.json` несёт
#: `generated_at=2026-08-30` рядом с `as_of=2026-06-25` — **66 суток** между
#: «когда записали» и «про когда это». Принять `as_of` за отметку записи значило
#: бы объявить живой файл беспризорным (или наоборот) по дате, которая про
#: запись не говорит вовсе. Перечень существует, чтобы причина была НАЗВАНА, а не
#: чтобы по нему что-то искали.
DOMAIN_DATE_KEYS = ("as_of", "as_of_utc", "asof", "day", "date")

#: Отметка, называющая ТОЧКУ ВХОДА прогона, — единственный канал атрибуции,
#: найденный замером 26.10 (ADR-820, заказ G819 п. 1). Поле вложенное
#: (``invoked_by.entry``), схема ``call_provenance.v1``, и значение снимается у
#: самого процесса в момент записи, а не печатается литералом.
ATTRIBUTION_ENTRY_KEY = "invoked_by"
ATTRIBUTION_ENTRY_FIELD = "entry"

#: Отметки, называющие КОД (модуль, скрипт, роль), — перечень ЗАМКНУТ и
#: ИЗМЕРЕН, а не угадан. Замер 26.10 по 231 артефакту конституции (ключи
#: верхнего уровня, значения прочитаны глазами): ``generated_by`` 20 ·
#: ``agent`` 11 (роль аналитика внутри `investment_os`) · ``source`` 8 ·
#: ``module`` 3 · ``producer`` 2 · ``writers`` 2 · ``monitor`` 2 · ``runner`` 2 ·
#: ``engine`` 2. Ни одна из них атрибуцией НЕ является (см.
#: :func:`slo_proposal.write_attribution`): это литерал пишущего кода, и он один
#: и тот же, кто бы код ни позвал. Перечень существует, чтобы причина была
#: НАЗВАНА — чтобы «похожая на имя писавшего строка» отличалась от «ничего нет».
ATTRIBUTION_CODE_KEYS = ("generated_by", "producer", "module", "monitor",
                         "runner", "source", "engine", "writers", "agent")

#: Воздержание ПЕРЕПИСИ (не двери): артефакт объявлен ещё и за ИДУЩИМ
#: производителем. Тогда «файл свежий» объясняется им, и находка «объявлен не тот
#: производитель» была бы НЕОБОСНОВАННОЙ — верное чтение здесь «лишнее отставное
#: объявление», а это другой вопрос с другим автором. Население случая ИЗМЕРЕНО
#: циклом #942 и равно НУЛЮ (0 из 224), и ветка написана не про запас: без неё
#: первый же такой артефакт родил бы ложную находку молча.
TRACE_ACTIVE_PRODUCER = "write_trace_abstains_active_producer_declared"

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
    # Пары ОТСТАВНЫХ производителей — своё число (ADR-818), и сложить его с
    # воздержаниями со-производства нельзя: они о разных предметах, и ровно это
    # смешение девять пар до сегодня и прятало внутри «срок не ниже пола».
    # Ключа нет ⇒ «НЕ ИЗМЕРЕНО»: прибор старой версии и прибор без населения
    # обязаны быть различимы (инв. #17).
    not_running = section.get("not_running")
    return ("slo_keepability, объявленная ось (пара «агент × артефакт» по расписанию): "
            f"население {section.get('population')} · срок не ниже пола "
            f"{'НЕ ИЗМЕРЕНО' if above is None else above} · находок "
            f"{'НЕ ИЗМЕРЕНО' if findings is None else len(findings)} · ВОЗДЕРЖАНИЙ "
            f"{'НЕ ИЗМЕРЕНО' if abstained is None else len(abstained)} "
            "(артефакт за несколькими производителями — такт ОДНОГО про файл не отвечает)"
            " · агент НЕ ИДЁТ "
            f"{'НЕ ИЗМЕРЕНО' if not_running is None else len(not_running)} "
            "(такта нет по построению — срок судить не о чем ни в одну сторону)")


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
                slo, schedule, medians.get(art), declared_producers,
                intent=agent.get("intent"))
            tally[axis] = tally.get(axis, 0) + 1
            pairs.append({"agent": agent.get("label"), "artifact": art,
                          "slo_hours": slo, "schedule": schedule,
                          "intent": agent.get("intent"),
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
        # ОТДЕЛЬНЫЙ перечень, а не строка в `abstained` (ADR-818). Делит их
        # ПРЕДМЕТ воздержания, а не его знак: `abstained` есть население вопроса
        # ADR-817 («существует ли объявленное со-производство в
        # действительности»), и пара отставного агента в нём стала бы вопросом,
        # которого никто не задавал, — у неё со-производства нет по построению.
        # Перечисляется ПОИМЁННО по той же причине, что и `abstained`: пара,
        # просто исчезнувшая из отчёта, неотличима от пары, которой не было.
        "not_running": [r for r in pairs if r["declared_vs_floor"] in (
            slo_proposal.DECLARED_PRODUCER_NOT_RUNNING,
            slo_proposal.DECLARED_PRODUCER_STANDING_UNMEASURED)],
    }


def parse_write_stamp(raw) -> Optional[datetime]:
    """Отметка записи из артефакта — или ``None``, если её НЕ РАЗОБРАЛИ.

    Две формы, обе встречены в живых артефактах: строка ISO (с дробными
    секундами и без, с ``Z`` и со смещением) и ЧИСЛО epoch —
    `data/basis_trade_opportunities.json` несёт `generated_at` числом, а
    `timestamp` строкой в одном и том же файле. Не разобрали ⇒ ``None``, и это
    «второй пробы нет», а не «файл старый»: подстановка любого числа здесь
    родила бы вердикт из отсутствия наблюдения (инв. #17).
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(raw, str) or not raw:
        return None
    text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return _parse_stamp(raw)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def artifact_file(artifact: str, root: Path, data_dir: Path) -> Path:
    """Где лежит артефакт конституции. ЕДИНСТВЕННОЕ место этого правила.

    Путь в конституции объявлен от КОРНЯ репозитория (`data/...`, `logs/...`), а
    живой каталог данных может лежать и ВНЕ дерева: замер из worktree обязан
    спрашивать `data/` прод-дерева, иначе ответ «артефакта нет» получается по
    построению, а не по делу (ровно урок ADR-364, `--data-dir`). Поэтому
    префикс ``data/`` переадресуется на ``data_dir``, а всё прочее — на корень.
    """
    rel = str(artifact)
    if rel.startswith("data/"):
        return Path(data_dir) / rel[len("data/"):]
    return Path(root) / rel


def write_trace_observation(path: Path, *, now: Optional[datetime] = None,
                            dir_readable: bool = True) -> dict:
    """ДВЕ пробы возраста записи одного артефакта + причина, если их нет.

    ``dir_readable=False`` ⇒ ВСЕ пробы отсутствуют с названной причиной, и это не
    перестраховка: каталог данных, которого нет, превратил бы каждый артефакт в
    «отсутствует», то есть выдал бы НЕ ИЗМЕРЕНО за измеренный ответ целой
    переписью сразу — тот самый fail-OPEN, что тише красного.
    """
    if not dir_readable:
        return {"present": None, "mtime_age_hours": None, "stamp_age_hours": None,
                "stamp_key": None,
                "why": "каталог данных НЕ ПРОЧИТАН — про запись не сказано ничего"}
    moment = _now(now)
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {"present": False, "mtime_age_hours": None, "stamp_age_hours": None,
                "stamp_key": None, "why": f"файла нет по пути {path}"}
    except OSError as exc:
        return {"present": None, "mtime_age_hours": None, "stamp_age_hours": None,
                "stamp_key": None,
                "why": f"файл не опрошен ({type(exc).__name__}) — {path}"}
    mtime_age = (moment.timestamp() - stat.st_mtime) / 3600.0
    stamp_age, stamp_key, why = None, None, ""
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        why = (f"вторая проба недоступна: артефакт не разобран как JSON "
               f"({type(exc).__name__})")
        doc = None
    if isinstance(doc, dict):
        for key in WRITE_STAMP_KEYS:
            parsed = parse_write_stamp(doc.get(key)) if key in doc else None
            if parsed is not None:
                stamp_age = (moment - parsed).total_seconds() / 3600.0
                stamp_key = key
                break
        if stamp_key is None:
            present_domain = [k for k in DOMAIN_DATE_KEYS if k in doc]
            why = ("вторая проба недоступна: отметки записи в артефакте нет"
                   + (f"; предметные даты {present_domain} за отметку записи НЕ "
                      f"принимаются" if present_domain else ""))
    elif doc is not None:
        why = (f"вторая проба недоступна: корень артефакта — "
               f"{type(doc).__name__}, не объект")
    return {"present": True, "mtime_age_hours": mtime_age,
            "stamp_age_hours": stamp_age, "stamp_key": stamp_key, "why": why}


def producer_reality_census(declared_axis: dict, agents: list, root: Path,
                            data_dir: Path, *, now: Optional[datetime] = None) -> dict:
    """Перепись ПРАВДИВОСТИ конституции у пар, снятых с суда за отставку.

    **Население — пары из ``not_running``**, и выбор назван: воздержание ADR-818
    ВЕРНО («такта нет — срок судить не о чем»), но ровно внутри него прячется
    второй вопрос, и вред от его отсутствия односторонний — артефакт, который
    система пишет каждые сутки, числится за агентом, которого не запускают, и
    никто этого не говорит. Пары со ``..._standing_unmeasured`` из населения НЕ
    выпадают: там не прочитан ярлык, значит и про запись судить нельзя — третий
    исход с причиной, а не строка, которой в отчёте не стало.

    **Единица населения — ПАРА, а не артефакт**, в отличие от
    :func:`co_production_census`. Делит их предмет: там предпосылка одна на файл,
    здесь обещание дано ПАРОЙ и порогом служит её собственный ``slo_hours``.
    Взяв артефакт единицей, пришлось бы придумывать правило сведения двух разных
    сроков в один порог — то есть второе правило свежести. Число артефактов
    печатается РЯДОМ, а не вместо: оба о разном и не складываются.

    Вердикт объявленной оси эта перепись НЕ ПЕРЕПИСЫВАЕТ ни одной парой, и в
    ``tally``/``verdict`` замера не входит ни одним числом — тот же порядок, что
    у ADR-816/817, и по той же причине (заказ G815 п. 2).
    """
    not_running = observed(declared_axis, "not_running", kind=list)
    if not_running is None:
        return {"status": slo_proposal.TRACE_UNMEASURED,
                "cause": ("в объявленной оси нет перечня пар с неидущим "
                          "производителем (`not_running`)"),
                "population": None, "artifacts": None, "tally": None, "rows": None}
    dd = Path(data_dir)
    dir_readable = dd.is_dir()
    active = {a.get("label") for a in agents if isinstance(a, dict)
              and a.get("intent") == ACTIVE}
    seen: dict = {}
    rows: list = []
    tally: dict = {}
    for pair in not_running:
        if not isinstance(pair, dict):
            continue
        artifact = pair.get("artifact")
        if not artifact:
            continue
        if artifact not in seen:
            seen[artifact] = write_trace_observation(
                artifact_file(artifact, Path(root), dd), now=now,
                dir_readable=dir_readable)
        obs = seen[artifact]
        # Воздержание ПЕРЕПИСИ спрашивается РАНЬШЕ двери: артефакт, объявленный
        # ещё и за ИДУЩИМ производителем, свежесть объясняет им, и находка
        # «объявлен не тот» была бы необоснованной. Население ИЗМЕРЕНО и равно
        # нулю (цикл #942) — ветка против ПЕРВОГО такого случая, не про запас.
        alive = sorted(set(declared_producer_labels(agents, artifact)) & active)
        if alive:
            kind, why = TRACE_ACTIVE_PRODUCER, (
                f"артефакт объявлен ещё и за идущим производителем ({', '.join(alive)}) "
                f"— свежесть объясняется им, и «объявлен не тот производитель» из "
                f"неё не следует")
        elif pair.get("declared_vs_floor") == (
                slo_proposal.DECLARED_PRODUCER_STANDING_UNMEASURED):
            kind, why = slo_proposal.TRACE_UNMEASURED, (
                "ярлык состояния производителя НЕ ПРОЧИТАН — пока неизвестно, "
                "идёт он или выведен, про запись судить нельзя")
        else:
            kind, why = slo_proposal.write_trace(
                obs.get("mtime_age_hours"), obs.get("stamp_age_hours"),
                pair.get("slo_hours"), present=obs.get("present"))
            if obs.get("why"):
                why = f"{why}; {obs['why']}"
        tally[kind] = tally.get(kind, 0) + 1
        rows.append({
            "agent": pair.get("agent"), "artifact": artifact,
            "intent": pair.get("intent"), "slo_hours": pair.get("slo_hours"),
            "mtime_age_hours": obs.get("mtime_age_hours"),
            "stamp_age_hours": obs.get("stamp_age_hours"),
            "stamp_key": obs.get("stamp_key"),
            "write_trace": kind, "note": why,
        })
    return {
        "status": "OK",
        "population": len(rows),
        "artifacts": len(seen),
        "data_dir": str(dd),
        "data_dir_readable": dir_readable,
        "tally": tally,
        # Находка — ТОЛЬКО свежий след при неидущем производителе. «Не пишет
        # никто» находкой оси НЕ является: это вопрос к КУРАЦИИ со своим
        # автором (правка конституции), и выдать его за находку прибора значило
        # бы предложить чистку, которую заказ G818 п. 1 запрещает предлагать
        # прежде замера.
        "findings": [r for r in rows if r["write_trace"] == slo_proposal.TRACE_MISDECLARED],
        # Беспризорные перечисляются ПОИМЁННО по той же причине, что и
        # воздержания ADR-816: пара, просто исчезнувшая из отчёта, неотличима от
        # пары, которой не было.
        "unmaintained": [r for r in rows if r["write_trace"] in (
            slo_proposal.TRACE_UNMAINTAINED, slo_proposal.TRACE_ABSENT)],
        "rows": rows,
    }


def producer_reality_line(doc: dict) -> str:
    """Строка ПРАВДИВОСТИ конституции для шага 0-офис. Единственная её форма.

    Живёт здесь по той же причине, что :func:`declared_axis_line` и
    :func:`co_production_line`: инлайн-печать внутри ``findings_bridge.main``
    лежит за ступенью переписей, идущей на живом Маке часами, проверить её
    отдельно НЕЧЕМ, и любая опечатка ушла бы в ``except`` моста как «перепись
    пропущена» — молча.
    """
    section = observed(doc, "declared_producer_reality", kind=dict)
    if section is None:
        return ("slo_keepability, правдивость конституции: НЕ ИЗМЕРЕНО — секции "
                "`declared_producer_reality` в замере нет")
    if section.get("status") != "OK":
        return ("slo_keepability, правдивость конституции: НЕ ИЗМЕРЕНО — "
                f"{section.get('cause') or 'причина не названа'}")
    tally = observed(section, "tally", kind=dict) or {}
    findings = section.get("findings")
    unmaintained = section.get("unmaintained")
    population = section.get("population")
    artifacts = section.get("artifacts")
    names = ", ".join(f"{r.get('artifact')} ← {r.get('agent')}"
                      for r in (findings or []))
    return ("slo_keepability, правдивость конституции (пару снял с суда отставной "
            "производитель — а файл пишет кто-то?): пар "
            f"{'НЕ ИЗМЕРЕНО' if population is None else population} на "
            f"{'НЕ ИЗМЕРЕНО' if artifacts is None else artifacts} артефакт(ов) · "
            f"ОБЪЯВЛЕН НЕ ТОТ ПРОИЗВОДИТЕЛЬ "
            f"{'НЕ ИЗМЕРЕНО' if findings is None else len(findings)}"
            f"{f' ({names})' if names else ''} · никто не пишет "
            f"{'НЕ ИЗМЕРЕНО' if unmaintained is None else len(unmaintained)} "
            "(вопрос к КУРАЦИИ — правка конституции, не находка прибора) · "
            f"пробы разошлись {tally.get(slo_proposal.TRACE_DISPUTED, 0)} · "
            f"не измерено {tally.get(slo_proposal.TRACE_UNMEASURED, 0)}")


def write_attribution_observation(path: Path, *, dir_readable: bool = True) -> dict:
    """Какие отметки о писавшем несёт ОДИН артефакт — и почему, если никаких.

    Две РАЗНЫЕ находки под одной крышей, и смешивать их нельзя (ADR-820):
    ``entry`` — точка входа прогона, снятая у процесса; ``code_keys`` — имена
    КОДА, которые на имя писавшего похожи, но им не являются.

    ``dir_readable=False`` ⇒ все пробы отсутствуют с названной причиной, по той
    же причине, что у :func:`write_trace_observation`: каталог данных, которого
    нет, превратил бы каждый артефакт в «канала нет», то есть выдал бы НЕ
    ИЗМЕРЕНО за измеренный ответ целой переписью сразу.
    """
    if not dir_readable:
        return {"present": None, "entry": None, "code_keys": None,
                "why": "каталог данных НЕ ПРОЧИТАН — про канал атрибуции не "
                       "сказано ничего"}
    try:
        exists = path.is_file()
    except OSError as exc:
        return {"present": None, "entry": None, "code_keys": None,
                "why": f"файл не опрошен ({type(exc).__name__}) — {path}"}
    if not exists:
        return {"present": False, "entry": None, "code_keys": None,
                "why": f"файла нет по пути {path}"}
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return {"present": True, "entry": None, "code_keys": None,
                "why": f"артефакт не разобран как JSON ({type(exc).__name__}) — "
                       f"отметки читать нечем"}
    if not isinstance(doc, dict):
        return {"present": True, "entry": None, "code_keys": None,
                "why": f"корень артефакта — {type(doc).__name__}, не объект: "
                       f"отметки верхнего уровня у него не существует"}
    stamp = doc.get(ATTRIBUTION_ENTRY_KEY)
    entry = None
    why = ""
    if isinstance(stamp, dict):
        # Отметка на месте, а поля входа в ней нет — это НЕ «канала нет»:
        # носитель объявлен, и пустота внутри него есть своя причина.
        entry = stamp.get(ATTRIBUTION_ENTRY_FIELD)
        if entry is None:
            why = (f"отметка `{ATTRIBUTION_ENTRY_KEY}` есть, поля "
                   f"`{ATTRIBUTION_ENTRY_FIELD}` в ней нет")
    elif stamp is not None:
        entry = ""  # дверь прочтёт это как «отметка есть, но не разобрана»
        why = (f"отметка `{ATTRIBUTION_ENTRY_KEY}` — {type(stamp).__name__}, "
               f"не объект")
    return {"present": True, "entry": entry,
            "code_keys": [key for key in ATTRIBUTION_CODE_KEYS if key in doc],
            "why": why}


def write_attribution_census(producer_reality: dict, agents: list, root: Path,
                             data_dir: Path) -> dict:
    """Перепись КАНАЛА АТРИБУТАЦИИ там, где вопрос «кто записал» имеет предмет.

    **Заказ G819 п. 1 запретил искать прибор прежде замера**, и замер отвечает
    на свой вопрос: есть ли вообще наблюдаемый канал, приписывающий запись
    запущенному. Поэтому здесь ДВА разных числа, и они не складываются:

    ``population``
        артефакты, у которых вопрос «кто записал» ИМЕЕТ ПРЕДМЕТ: кандидатов
        больше одного. Дома два, и каждый считается ОТДЕЛЬНО
        (``population_homes``): **со-производимый** артефакт (≥2 объявленных
        производителя — ровно тот
        случай, который ADR-819 назвал неразрешимым по построению) и
        **артефакт с находкой ADR-819** (свежая запись при неидущем
        производителе ⇒ писал кто-то, в конституции не названный).
    ``inventory``
        перепись ВСЕЙ конституции — сколько артефактов вообще несут отметку. Это
        про НАЛИЧИЕ канала в системе, а не про вопрос; выдать одно за другое
        значило бы ответить «канал есть» там, где у вопроса его нет.

    Пересечение этих двух чисел и есть ответ заказа: канал, существующий в
    системе, но отсутствующий у населения вопроса, вопроса не решает.

    Второй дом берётся из секции ``declared_producer_reality`` (ADR-819). Её
    статус НЕ ``OK`` ⇒ дом даёт **НЕ ИЗМЕРЕНО с причиной**, а не ноль: ноль
    здесь означал бы «находок нет», то есть ответ на вопрос, которого не
    задавали. Вердикты сроков эта перепись не переписывает ни одним числом — тот
    же порядок, что у ADR-816/817/819 (заказ G815 п. 2).
    """
    dd = Path(data_dir)
    dir_readable = dd.is_dir()
    prod: dict = {}
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        label = str(agent.get("label") or "")
        if not label:
            continue
        for produced in (agent.get("produces") or []):
            if isinstance(produced, dict) and produced.get("artifact"):
                prod.setdefault(str(produced["artifact"]), set()).add(label)
    if not prod:
        return {"status": slo_proposal.ATTRIBUTION_UNMEASURED,
                "cause": "в конституции нет ни одного объявленного артефакта — "
                         "населения у вопроса нет",
                "population": None, "inventory": None, "tally": None,
                "rows": None, "findings": None}

    seen: dict = {}

    def _observe(artifact: str) -> dict:
        if artifact not in seen:
            seen[artifact] = write_attribution_observation(
                artifact_file(artifact, Path(root), dd), dir_readable=dir_readable)
        return seen[artifact]

    def _verdict(obs: dict) -> tuple[str, str]:
        kind, why = slo_proposal.write_attribution(
            obs.get("entry"), obs.get("code_keys"), present=obs.get("present"))
        return kind, (f"{why}; {obs['why']}" if obs.get("why") else why)

    # Перепись ВСЕЙ конституции — отдельное число про наличие канала в системе.
    inventory: dict = {}
    for artifact in sorted(prod):
        kind, _why = _verdict(_observe(artifact))
        inventory[kind] = inventory.get(kind, 0) + 1

    # Дом №1 — со-производство: кандидатов больше одного ПО КОНСТИТУЦИИ.
    rows: list = []
    for artifact in sorted(prod):
        labels = sorted(prod[artifact])
        if len(labels) < 2:
            continue
        obs = _observe(artifact)
        kind, why = _verdict(obs)
        rows.append({"artifact": artifact, "home": "co_produced",
                     "candidates": labels, "attribution": kind,
                     "code_keys": obs.get("code_keys"),
                     "entry": obs.get("entry"), "note": why})

    # Дом №2 — находка ADR-819: писал кто-то, в конституции не названный.
    misdeclared_home: Optional[int] = None
    cause = None
    section = observed(producer_reality, "status", kind=str) if isinstance(
        producer_reality, dict) else None
    if section != "OK":
        cause = ("дом «находка ADR-819» НЕ ИЗМЕРЕН: секция "
                 "`declared_producer_reality` не дала замера"
                 + (f" ({producer_reality.get('cause')})"
                    if isinstance(producer_reality, dict)
                    and producer_reality.get("cause") else ""))
    else:
        findings = observed(producer_reality, "findings", kind=list)
        if findings is None:
            cause = ("дом «находка ADR-819» НЕ ИЗМЕРЕН: перечня находок в секции "
                     "`declared_producer_reality` нет")
        else:
            misdeclared_home = 0
            known = {row["artifact"] for row in rows}
            for finding in findings:
                if not isinstance(finding, dict) or not finding.get("artifact"):
                    continue
                artifact = str(finding["artifact"])
                if artifact in known:
                    continue
                misdeclared_home += 1
                obs = _observe(artifact)
                kind, why = _verdict(obs)
                rows.append({"artifact": artifact, "home": "misdeclared",
                             "candidates": [finding.get("agent")],
                             "attribution": kind,
                             "code_keys": obs.get("code_keys"),
                             "entry": obs.get("entry"), "note": why})

    tally: dict = {}
    for row in rows:
        tally[row["attribution"]] = tally.get(row["attribution"], 0) + 1
    return {
        "status": "OK",
        "population": len(rows),
        "population_homes": {
            "co_produced": len([r for r in rows if r["home"] == "co_produced"]),
            "misdeclared": misdeclared_home,
        },
        "population_cause": cause,
        "inventory": inventory,
        "inventory_population": len(prod),
        "data_dir": str(dd),
        "data_dir_readable": dir_readable,
        "tally": tally,
        # НАХОДКА — отметка, которая на атрибуцию ПОХОЖА, а ею не является:
        # читатель принимает литерал пишущего кода за имя писавшего. «Канала
        # нет вовсе» находкой НЕ является: это ответ заказа (третий исход), а
        # не дефект, который чинится правкой.
        "findings": [r for r in rows
                     if r["attribution"] == slo_proposal.ATTRIBUTION_CODE_ONLY],
        "rows": rows,
    }


def carrier_root(path: Path) -> tuple:
    """Какой КОРЕНЬ у носителя — то есть есть ли куда положить отметку.

    Условие ВТОРОЕ и от двери НЕЗАВИСИМОЕ. ``atomic_save`` принимает ``Any`` и
    кладёт на диск что дали: штамп, положенный внутрь неё, доходит только до
    документа-ОБЪЕКТА. Поэтому «дверь одна» само по себе покрытия НЕ означает,
    и вопрос о корне задаётся отдельно.

    Возвращается ``(род, причина)``; род ``None`` — НЕ ИЗМЕРЕНО (инв. #17), и
    это не то же, что «корень не объект»: нечитаемый файл не доказывает ни
    способности нести штамп, ни неспособности.
    """
    try:
        if not path.exists():
            return None, f"носителя нет на месте ({path}) — корень не измерен"
    except OSError as exc:
        return None, f"наличие носителя не прочитано ({exc.__class__.__name__})"
    if path.suffix == ".jsonl":
        return "лента строк", ("носитель — лента строк: документа верхнего уровня "
                               "у неё нет вовсе, и отметка легла бы в каждую строку")
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as exc:
        return None, f"носитель не разобран ({exc.__class__.__name__}) — корень НЕ ИЗМЕРЕН"
    if isinstance(doc, dict):
        return slo_proposal.CARRIER_OBJECT, "корень — объект: отметка верхнего уровня помещается"
    return type(doc).__name__, (f"корень — {type(doc).__name__}, не объект: "
                                f"отметку верхнего уровня положить некуда")


#: Слепок прошлого обхода дерева: ключ — (корень, число файлов, самая свежая
#: отметка, суммарный размер). Нужен не ради скорости как таковой: прибор
#: зовётся в одном процессе десятки раз (только соседний набор тестов — 60), и
#: каждый обход стои́т 14,2 с, то есть ЧЕТВЕРТЬ ЧАСА на прогон.
#:
#: **Ключ несёт отметки, а не только путь, и это существенно.** Слепок по одному
#: пути отвечал бы о дереве, КАКИМ ОНО БЫЛО при первом зове, и правка кода
#: внутри процесса осталась бы невидимой — то есть прибор утверждал бы о
#: моменте, которого не видел. Снять отметки дёшево (``stat`` без разбора),
#: поэтому платить за честность нечем.
_DOORS_CACHE: dict = {}


def _tree_fingerprint(folders: list) -> tuple:
    """(число файлов, самая свежая отметка, суммарный размер) — дёшево и честно."""
    count = 0
    newest = 0
    total = 0
    for folder in folders:
        for module in folder.rglob("*.py"):
            text = str(module)
            if "/tests/" in text or module.name.startswith("test_"):
                continue
            try:
                stat = module.stat()
            except OSError:
                continue
            count += 1
            total += stat.st_size
            newest = max(newest, stat.st_mtime_ns)
    return count, newest, total


def write_doors_by_artifact(root: Path, scan_dirs=("spa_core", "scripts")) -> tuple:
    """{имя файла артефакта: {двери}} и {имя: [модули, пишущие СВОЕЙ дверью]}.

    Обход дерева стои́т **14,2 с** на 2488 файлах (замер 26.10) — это названо
    вслух, потому что прибор зовётся шагом цикла, а не руками.

    Каталог кода нечитаем ⇒ ``(None, None)``, то есть **НЕ ИЗМЕРЕНО с
    причиной**, а не пустой словарь: пустой словарь дал бы 231 вердикт
    «писателя не нашли», то есть fail-OPEN, который тише красного — ровно
    дефект, названный в `.claude/rules/deployment.md`.
    """
    base = Path(root)
    folders = [base / name for name in scan_dirs if (base / name).is_dir()]
    if not folders:
        return None, None
    key = (str(base.resolve()), tuple(scan_dirs)) + _tree_fingerprint(folders)
    cached = _DOORS_CACHE.get(key)
    if cached is not None:
        return cached
    found = False
    doors: dict = {}
    own_writers: dict = {}
    for folder in folders:
        found = True
        for module in sorted(folder.rglob("*.py")):
            text = str(module)
            if "/tests/" in text or module.name.startswith("test_"):
                continue
            try:
                src = module.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for artifact, kinds in artifact_io_scan.write_doors(src).items():
                # Ключ — литерал КАК НАЙДЕН. Сворачивать его к имени файла
                # здесь нельзя: полный путь есть ТОЧНОЕ разрешение, и потеряв
                # его, перепись спутала бы шесть разных `status.json`.
                doors.setdefault(artifact, set()).update(kinds)
                if artifact_io_scan.DOOR_OWN in kinds:
                    own_writers.setdefault(artifact, []).append(
                        str(module.relative_to(base)))
    if not found:
        return None, None
    _DOORS_CACHE[key] = (doors, own_writers)
    return doors, own_writers


def write_stamp_price_census(write_attribution: dict, agents: list, root: Path,
                             data_dir: Path) -> dict:
    """ЦЕНА штампа атрибуции — ШЕСТАЯ секция (ADR-821, заказ G820 п. 1).

    ADR-820 ответил, что канал атрибуции в системе ЕСТЬ, а у населения вопроса
    его нет ЦЕЛИКОМ. Заказ запретил предлагать правку писателей прежде, чем
    спрошено, сколько она стои́т, и назвал проверяемую догадку: «если дверь одна,
    штамп стоит одной правки, а не 36».

    **Замер догадку ПОДТВЕРЖДАЕТ в целом и ОПРОВЕРГАЕТ там, где живёт вопрос.**
    По 231 артефакту конституции (26.10): одной правки хватило бы **158**; своя
    правка нужна **35** (89 мест в 35 модулях); писатель не найден у **28**;
    дверь части писателей не разобрана у **9**; и у **одного** дверь общая, а
    корень — массив, то есть правка одна, а положить её некуда. У населения
    вопроса (8 со-производимых артефактов) одной правкой покрылись бы **6 из
    8**, а два остатка — ``defi_engine/status.json`` и ``kill_switch_active.json``
    — требуют своей, причём второй есть money-path, и правка его за мандатом
    автономного цикла.

    **Дверь одна не потому, что её так написали, а потому, что её ДОСТИГАЮТ
    транзитивно.** В дереве 304 определения локальных помощников
    ``_atomic_write*``, и две трети зовут ``atomic_save`` сами. Остановись разбор
    на первом шаге — ответ был бы 142 вместо 158; спроси он имя вызова без
    владельца — 12 вместо 159 (``str.replace`` неотличим от ``os.replace`` по
    имени). Оба промаха сдвигали цену в ОДНУ сторону: завышали.

    Вердикты сроков эта перепись не переписывает ни одним числом — тот же
    порядок, что у ADR-816/817/819/820 (заказ G815 п. 2). Население вопроса
    берётся ССЫЛКОЙ у ПЯТОЙ секции и заново не считается; её «НЕ ИЗМЕРЕНО»
    остаётся «НЕ ИЗМЕРЕНО», а не превращается в ноль.
    """
    doors_by_art, own_writers = write_doors_by_artifact(Path(root))
    if doors_by_art is None:
        return {"status": slo_proposal.STAMP_PRICE_UNMEASURED,
                "cause": (f"каталога кода нет в дереве {root} — двери писателей "
                          f"НЕ ИЗМЕРЕНЫ ни у одного артефакта"),
                "inventory": None, "population": None, "population_cause": None,
                "tally": None, "price_modules": None, "rows": None, "findings": None}
    dd = Path(data_dir)
    declared: dict = {}
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        label = str(agent.get("label") or "")
        if not label:
            continue
        for produced in (agent.get("produces") or []):
            if isinstance(produced, dict) and produced.get("artifact"):
                declared.setdefault(str(produced["artifact"]), set()).add(label)
    if not declared:
        return {"status": slo_proposal.STAMP_PRICE_UNMEASURED,
                "cause": "в конституции нет ни одного объявленного артефакта — "
                         "цену штампа не на чем мерить",
                "inventory": None, "population": None, "population_cause": None,
                "tally": None, "price_modules": None, "rows": None, "findings": None}

    # СПОРНОЕ имя: путь собран из констант ⇒ у двери видно только имя файла.
    # Имя считается спорным, если его носит больше одного артефакта
    # конституции ЛИБО если в дереве есть ПОЛНЫЙ путь с тем же именем, но
    # другой. Замер 26.10: таких артефактов 11 из 231.
    by_basename: dict = {}
    for artifact in declared:
        by_basename.setdefault(artifact.split("/")[-1], set()).add(artifact)
    for literal in doors_by_art:
        if "/" in literal:
            by_basename.setdefault(literal.split("/")[-1], set()).add(literal)

    rows: list = []
    inventory: dict = {}
    own_modules: set = set()
    for artifact in sorted(declared):
        key = artifact.split("/")[-1]
        exact = artifact in doors_by_art
        contested = not exact and len(by_basename.get(key) or ()) > 1
        kinds = doors_by_art.get(artifact if exact else key, set())
        carrier, carrier_why = carrier_root(artifact_file(artifact, Path(root), dd))
        price, why = slo_proposal.write_stamp_price(
            kinds, carrier, name_contested=contested)
        inventory[price] = inventory.get(price, 0) + 1
        modules = (sorted(own_writers.get(artifact if exact else key) or [])
                    if price == slo_proposal.STAMP_OWN_EDIT_NEEDED else [])
        own_modules.update(modules)
        rows.append({"artifact": artifact, "price": price, "doors": sorted(kinds),
                     "carrier": carrier, "own_writers": modules,
                     "resolved_exactly": exact, "name_contested": contested,
                     "note": f"{why}; {carrier_why}"})

    by_artifact = {row["artifact"]: row for row in rows}
    # Население ВОПРОСА берётся ССЫЛКОЙ у ПЯТОЙ секции (ADR-820) — там он и
    # измерен. Пересчитать его здесь значило бы завести ВТОРОЕ определение
    # одного населения, и разойдясь, две копии дали бы разные ответы про один
    # артефакт.
    population: Optional[list] = None
    population_cause = None
    section = write_attribution if isinstance(write_attribution, dict) else {}
    if section.get("status") != "OK" or not isinstance(section.get("rows"), list):
        population_cause = ("население вопроса НЕ ИЗМЕРЕНО — пятая секция "
                            "(`declared_write_attribution`) его не дала: "
                            f"{section.get('cause') or section.get('status') or 'секции нет'}")
    else:
        population = []
        for row in section["rows"]:
            if not isinstance(row, dict) or not row.get("artifact"):
                continue
            mine = by_artifact.get(str(row["artifact"]))
            population.append({
                "artifact": str(row["artifact"]),
                "home": row.get("home"),
                "attribution": row.get("attribution"),
                "price": (mine or {}).get("price") or slo_proposal.STAMP_PRICE_UNMEASURED,
                "own_writers": (mine or {}).get("own_writers") or [],
            })

    tally: dict = {}
    for row in (population or []):
        tally[row["price"]] = tally.get(row["price"], 0) + 1
    return {
        "status": "OK",
        "inventory": inventory,
        "inventory_population": len(declared),
        "population": None if population is None else len(population),
        "population_cause": population_cause,
        "population_rows": population,
        "tally": tally,
        # ЦЕНА в правках: модули, которые пришлось бы тронуть по отдельности.
        "price_modules": len(own_modules),
        "price_modules_named": sorted(own_modules)[:12],
        "data_dir": str(dd),
        # НАХОДКА — артефакт, который ВЫГЛЯДИТ покрытым одной правкой и не
        # покрыт: дверь у него общая, а корень отметку верхнего уровня не
        # несёт. Читатель, считающий «дверь одна ⇒ штамп придёт», ошибётся
        # именно здесь. «Нужна своя правка» находкой НЕ является — это
        # честная цена, а не дефект.
        "findings": [row for row in rows
                     if row["price"] == slo_proposal.STAMP_CARRIER_CANNOT_HOLD],
        "rows": rows,
    }


def write_stamp_price_line(doc: dict) -> str:
    """Строка ЦЕНЫ штампа. Единственная её форма, читатель — :func:`report`.

    Тот же выбор читателя, что у :func:`write_attribution_line`, и по той же
    измеренной причине (ADR-820): строка, которую печатает только
    ``findings_bridge``, уходит в лог агента, а не в вывод шага 0-офис.
    """
    section = observed(doc, "declared_write_stamp_price", kind=dict)
    if section is None:
        return ("  цена штампа атрибуции: НЕ ИЗМЕРЕНО — секции "
                "`declared_write_stamp_price` в замере нет (отчёт написан "
                "производителем ДО ADR-821)")
    if section.get("status") != "OK":
        return ("  цена штампа атрибуции: НЕ ИЗМЕРЕНО — "
                f"{section.get('cause') or 'причина не названа'}")
    inventory = observed(section, "inventory", kind=dict) or {}
    tally = observed(section, "tally", kind=dict) or {}
    findings = section.get("findings") or []
    names = ", ".join(f"{row.get('artifact')} (корень {row.get('carrier')})"
                      for row in findings)
    population = section.get("population")
    return (
        "  цена штампа атрибуции (ADR-821, в сумму вердиктов НЕ входит): по ВСЕЙ "
        f"конституции ({section.get('inventory_population')} артефакт(ов)) ОДНОЙ "
        f"правки общей двери хватило бы "
        f"{inventory.get(slo_proposal.STAMP_ONE_EDIT, 0)} · своя правка нужна "
        f"{inventory.get(slo_proposal.STAMP_OWN_EDIT_NEEDED, 0)} "
        f"({section.get('price_modules')} модул(ей)) · дверь общая, а корень "
        f"штамп НЕ несёт {inventory.get(slo_proposal.STAMP_CARRIER_CANNOT_HOLD, 0)}"
        f"{f' ({names})' if names else ''} · писатель НЕ НАЙДЕН "
        f"{inventory.get(slo_proposal.STAMP_WRITER_NOT_FOUND, 0)} · имя артефакта "
        f"СПОРНО {inventory.get(slo_proposal.STAMP_NAME_CONTESTED, 0)} · НЕ ИЗМЕРЕНО "
        f"{inventory.get(slo_proposal.STAMP_PRICE_UNMEASURED, 0)}; у НАСЕЛЕНИЯ "
        f"ВОПРОСА ("
        f"{'НЕ ИЗМЕРЕНО' if population is None else str(population) + ' артефакт(ов)'}"
        f") одной правкой покрылось бы "
        f"{tally.get(slo_proposal.STAMP_ONE_EDIT, 0)}, своя правка нужна "
        f"{tally.get(slo_proposal.STAMP_OWN_EDIT_NEEDED, 0)} — цена и ПОКРЫТИЕ "
        "это РАЗНЫЕ числа")


#: ИМЯ файла-пробы, которым спрашивается читатель штампа (ADR-822). Отметка
#: собирается НАСТОЯЩИМ производителем (:func:`call_provenance.call_provenance`)
#: на этом файле, а не складывается руками: собранная руками отметка проверяла
#: бы СВОЙ словарь, а не проводку — ровно та ошибка, которую положительный
#: контроль ADR-820/821 пережил дважды (мутация «секция под другим именем»).
STAMP_READER_PROBE_NAME = "spa_stamp_reader_probe_entry.py"

#: Загруженная дверь чтения. Ключ — (путь, отметка файла, размер): ключ по
#: одному пути отвечал бы о двери, какой она была при первом зове, и правка
#: читателя внутри процесса осталась бы невидимой (тот же выбор и та же
#: причина, что у :data:`_DOORS_CACHE`).
_READER_DOOR_CACHE: dict = {}


def stamp_reader_probe(root: Optional[Path] = None, *, provenance=None) -> tuple:
    """Отметка-ПРОБА, собранная настоящим производителем. ``(отметка, причина)``.

    ``None`` в первом элементе — НЕ ИЗМЕРЕНО с причиной (инв. #17): без
    отметки спросить читателя нечем, и «читателя нет» из этого не следует.

    **``provenance`` — ПРОИЗВОДИТЕЛЬ ВХОДОМ, а не окружением** (тот же приём,
    что у часов и у живости процесса в `.claude/rules/deployment.md`).
    Умолчание читает настоящего (:func:`call_provenance.call_provenance`), и
    он на существующем файле всегда отвечает ``measured=True`` — поэтому
    отказные ветки этой двери БЕЗ инъекции недостижимы по построению, а
    недостижимая ветка есть ветка непроверенная. Найдено своим же мутационным
    прогоном: мутация «отметка-проба принимается НЕИЗМЕРЕННОЙ» пережила первый
    прогон именно потому, что подставить молчащего производителя было нечем.
    """
    produce = provenance or call_provenance.call_provenance
    with tempfile.TemporaryDirectory(prefix="spa_stamp_reader_") as folder:
        probe = Path(folder) / STAMP_READER_PROBE_NAME
        try:
            probe.write_text("# проба читателя штампа (ADR-822)\n", encoding="utf-8")
        except OSError as exc:
            return None, (f"файл-пробу не создать ({type(exc).__name__}) — "
                          f"отметку собирать нечем")
        try:
            stamp = produce(
                tree_root=Path(root) if root is not None else None,
                main_file=str(probe), argv=[])
        except Exception as exc:  # производитель чужой — его отказ не наш вердикт
            return None, (f"производитель отметки отказал "
                          f"({type(exc).__name__}: {exc})")
    if not isinstance(stamp, dict) or not stamp.get("measured"):
        return None, (f"производитель отметки не назвал входа: "
                      f"{(stamp or {}).get('reason') if isinstance(stamp, dict) else stamp!r}")
    entry = stamp.get(ATTRIBUTION_ENTRY_FIELD)
    if not isinstance(entry, str) or not entry:
        return None, "производитель отметки вернул вход не строкой — искать нечего"
    return stamp, ""


def stamp_reader_door(root: Path) -> tuple:
    """ИЗМЕРЕННАЯ дверь чтения артефакта. ``(дверь, причина)``.

    Дверь ОДНА и выбрана ЗАМЕРОМ, а не вкусом: ``scripts/consume_office_reports.py``
    — единственный читатель, про которого ИЗМЕРЕНО, что его вывод доходит до
    цикла (ADR-820; прочие строки печатает мост, чей stdout уходит в лог
    агента). В конституции он же объявлен потребителем **141** артефакта из
    161 — остальные 20 имён принадлежат двадцати артефактам и НЕ ИЗМЕРЕНЫ.

    Берётся ``_summarize_json`` — ветка отрисовки ОДНОГО артефакта, а не
    ``main()``: ``main()`` пишет квитанции потребления на диск, и спросить им
    читателя значило бы изменить состояние системы вопросом о ней. Имя приватно
    намеренно: вопрос заказа — что делает НАСТОЯЩИЙ читатель, а не что про него
    объявлено, и публичной двери к его отрисовке в скрипте нет.
    """
    path = Path(root) / "scripts" / "consume_office_reports.py"
    try:
        stat = path.stat()
    except OSError as exc:
        return None, (f"читателя нет в дереве ({path}): {type(exc).__name__} — "
                      f"про читателя штампа не сказано ничего")
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    cached = _READER_DOOR_CACHE.get(key)
    if cached is not None:
        return cached, ""
    spec = importlib.util.spec_from_file_location(
        "spa_stamp_reader_door_consume_office_reports", path)
    if spec is None or spec.loader is None:
        return None, f"читатель {path} не загружается как модуль"
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # чужой модуль — его отказ не наш вердикт
        return None, (f"читатель {path} не загрузился "
                      f"({type(exc).__name__}: {exc})")
    for name in ("_summarize_json", "office_targets"):
        if not callable(getattr(module, name, None)):
            return None, (f"у читателя {path} нет двери `{name}` — спросить его "
                          f"нечем")
    _READER_DOOR_CACHE[key] = module
    return module, ""


def stamp_reader_observation(door, stamp: dict, path: Path, *,
                             root: Path, artifact_root: Path,
                             now: Optional[datetime] = None) -> dict:
    """ДИФФЕРЕНЦИАЛЬНЫЙ замер: меняется ли вывод читателя от ПОЯВЛЕНИЯ отметки.

    Один и тот же документ отрисовывается ДВАЖДЫ — без отметки и с отметкой, —
    и сравниваются ВЫВОДЫ. Это и есть «мерить исходом, не структурой» (заказ
    G821 п. 1): объявление поля читаемым краснеет на ОТСУТСТВИИ отметки и
    ничего не обещает про её ПОЯВЛЕНИЕ, а разница выводов есть наблюдение.

    Направление замера — ПОЯВЛЕНИЕ, и это существенно. Отметка снимается с
    документа ПЕРЕД первой отрисовкой: иначе у пятнадцати артефактов, уже
    несущих её, «без отметки» означало бы «с настоящей отметкой», и вопрос
    «если появится» подменился бы вопросом «если сменится значение».
    """
    try:
        if not path.is_file():
            return {"differs": None, "entry_printed": None,
                    "why": f"носителя нет на месте ({path}) — читателя "
                           f"спросить нечем"}
    except OSError as exc:
        return {"differs": None, "entry_printed": None,
                "why": f"наличие носителя не прочитано ({type(exc).__name__})"}
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as exc:
        return {"differs": None, "entry_printed": None,
                "why": f"носитель не разобран как JSON ({type(exc).__name__}) — "
                       f"отрисовать его читателю нечем"}
    if not isinstance(doc, dict):
        return {"differs": None, "entry_printed": None,
                "why": f"корень носителя — {type(doc).__name__}, не объект: "
                       f"отметки верхнего уровня у него не существует, и вопрос "
                       f"о её читателе предмета не имеет"}
    without = dict(doc)
    without.pop(ATTRIBUTION_ENTRY_KEY, None)
    with_stamp = dict(without)
    with_stamp[ATTRIBUTION_ENTRY_KEY] = stamp
    try:
        before = door._summarize_json(str(path), without, now=now,
                                      root=str(root), artifact_root=str(artifact_root))
        after = door._summarize_json(str(path), with_stamp, now=now,
                                     root=str(root), artifact_root=str(artifact_root))
    except Exception as exc:  # отказ ЧУЖОГО читателя — третий исход, не вердикт
        return {"differs": None, "entry_printed": None,
                "why": f"читатель отказал на отрисовке "
                       f"({type(exc).__name__}: {exc})"}
    needle = str(stamp.get(ATTRIBUTION_ENTRY_FIELD))
    printed = any(needle in str(line) for line in (after or []))
    return {"differs": [str(line) for line in (before or [])]
                       != [str(line) for line in (after or [])],
            "entry_printed": printed, "why": ""}


def stamp_reader_census(write_stamp_price: dict, agents: list, root: Path,
                        data_dir: Path, *, manifest: Optional[dict] = None,
                        now: Optional[datetime] = None,
                        provenance=None) -> dict:
    """КТО ПРОЧТЁТ штамп атрибуции — СЕДЬМАЯ секция (ADR-822, заказ G821 п. 1).

    ADR-821 назвал ЦЕНУ: одна правка внутри общей двери донесла бы штамп до
    153 артефактов из 231. Заказ запретил предлагать эту правку прежде, чем
    спрошено у ЧИТАТЕЛЯ:

        «кто вообще прочтёт ``invoked_by.entry``, если он появится? ADR-820
        назвал канал единственным найденным, а читателей его не мерил ВОВСЕ.
        Штамп без читателя есть ровно тот класс „у записки нет читателя“,
        который закрывали пять ADR подряд. Мерить ИСХОДОМ, не структурой.»

    **Здесь ДВА числа, и они не складываются** — тот же порядок, что у ADR-820
    и ADR-821:

    ``inventory``
        перепись ВСЕЙ конституции: сколько артефактов имеют читателя штампа.
        Это про НАЛИЧИЕ читателя в системе.
    ``population``
        артефакты, которым штамп ДОСТАЛСЯ БЫ от одной правки — то есть строки
        ШЕСТОЙ секции с ценой :data:`slo_proposal.STAMP_ONE_EDIT`, взятые
        ССЫЛКОЙ, а не посчитанные заново. Это и есть население ВОПРОСА: про
        артефакт, которому штамп не придёт, вопрос о его читателе задан не был.

    Замер 26.10 (231 артефакт, прод-каталог ``data/``): вход НАЗВАН у **11**,
    замечено только ОТСУТСТВИЕ у **4**, читатель НЕМ у **123**, двери не
    адресовано **69**, имя СПОРНО у **1**, НЕ ИЗМЕРЕНО **24** (носителя нет 10
    · носитель — лента строк или не объект 14). У населения вопроса (153
    артефакта, которым штамп пришёл бы) прочитан был бы **11**.

    **Ответ заказа: правку предлагать НЕ НАДО.** Одна правка дёшева (ADR-821) и
    молча: 142 штампа из 153 пришли бы туда, где их никто не читает. «Дешевле,
    чем кажется» и «есть кому прочесть» — разные утверждения, и второе измерено
    отрицательно.

    Вердикты сроков эта перепись не переписывает ни одним числом — тот же
    порядок, что у ADR-816/817/819/820/821 (заказ G815 п. 2).
    """
    stamp, why = stamp_reader_probe(root, provenance=provenance)
    if stamp is None:
        return {"status": slo_proposal.READER_UNMEASURED,
                "cause": f"отметка-проба НЕ СОБРАНА: {why}",
                "door": None, "inventory": None, "inventory_population": None,
                "population": None, "population_cause": None,
                "population_rows": None, "tally": None, "rows": None,
                "findings": None}
    door, why = stamp_reader_door(Path(root))
    if door is None:
        return {"status": slo_proposal.READER_UNMEASURED,
                "cause": f"измеренная дверь чтения НЕ ОПРОШЕНА: {why}",
                "door": None, "inventory": None, "inventory_population": None,
                "population": None, "population_cause": None,
                "population_rows": None, "tally": None, "rows": None,
                "findings": None}
    declared: dict = {}
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        label = str(agent.get("label") or "")
        if not label:
            continue
        for produced in (agent.get("produces") or []):
            if isinstance(produced, dict) and produced.get("artifact"):
                declared.setdefault(str(produced["artifact"]), set()).add(label)
    if not declared:
        return {"status": slo_proposal.READER_UNMEASURED,
                "cause": "в конституции нет ни одного объявленного артефакта — "
                         "читателя штампа не на чем мерить",
                "door": str(Path(root) / "scripts" / "consume_office_reports.py"),
                "inventory": None, "inventory_population": None,
                "population": None, "population_cause": None,
                "population_rows": None, "tally": None, "rows": None,
                "findings": None}

    # АДРЕСНОСТЬ спрашивается у ЕДИНСТВЕННОГО читателя правила отбора
    # (`office_targets`, ADR-502): своя копия «что офис обязан прочитать»
    # разошлась бы молча, и перепись мерила бы НЕ ТОТ операнд, которым
    # работает шаг. Манифест не передан ⇒ адресность НЕ ИЗМЕРЕНА у ВСЕХ, а
    # не False: False означал бы «дверь его не читает», то есть ответ.
    addressed: Optional[set] = None
    addressed_cause = ""
    if isinstance(manifest, dict):
        try:
            addressed = {str(item) for item in door.office_targets(manifest)}
        except Exception as exc:
            addressed_cause = (f"перечень адресованного двери не получен "
                               f"({type(exc).__name__}: {exc})")
    else:
        addressed_cause = "конституция в перепись не передана"

    # Спорность имени — ДЛЯ ЧИТАТЕЛЯ, и мера у неё своя: ветки отрисовки
    # выбираются по `os.path.basename`, поэтому спорным имя делает другой
    # ОБЪЯВЛЕННЫЙ артефакт с тем же именем файла. Это НЕ та же мера, что в
    # шестой секции (там спорность считается по литералам путей у дверей
    # записи): вопросы разные, и одна мера на два вопроса ответила бы на один.
    by_basename: dict = {}
    for artifact in declared:
        by_basename.setdefault(artifact.split("/")[-1], set()).add(artifact)

    dd = Path(data_dir)
    rows: list = []
    inventory: dict = {}
    for artifact in sorted(declared):
        is_addressed = None if addressed is None else (artifact in addressed)
        contested = len(by_basename.get(artifact.split("/")[-1]) or ()) > 1
        obs = {"differs": None, "entry_printed": None, "why": addressed_cause}
        if is_addressed and not contested:
            obs = stamp_reader_observation(
                door, stamp, artifact_file(artifact, Path(root), dd),
                root=Path(root), artifact_root=dd.parent, now=now)
        kind, why = slo_proposal.stamp_reader(
            obs.get("differs"), obs.get("entry_printed"),
            addressed=is_addressed, name_contested=contested)
        inventory[kind] = inventory.get(kind, 0) + 1
        rows.append({"artifact": artifact, "reader": kind,
                     "addressed": is_addressed, "name_contested": contested,
                     "differs": obs.get("differs"),
                     "entry_printed": obs.get("entry_printed"),
                     "note": f"{why}; {obs['why']}" if obs.get("why") else why})

    by_artifact = {row["artifact"]: row for row in rows}
    # Население ВОПРОСА берётся ССЫЛКОЙ у ШЕСТОЙ секции: там измерено, КОМУ
    # штамп достанется от одной правки. Пересчитать его здесь значило бы
    # завести ВТОРОЕ определение одного населения.
    population: Optional[list] = None
    population_cause = None
    section = write_stamp_price if isinstance(write_stamp_price, dict) else {}
    if section.get("status") != "OK" or not isinstance(section.get("rows"), list):
        population_cause = (
            "население вопроса НЕ ИЗМЕРЕНО — шестая секция "
            "(`declared_write_stamp_price`) его не дала: "
            f"{section.get('cause') or section.get('status') or 'секции нет'}")
    else:
        population = []
        for row in section["rows"]:
            if not isinstance(row, dict) or not row.get("artifact"):
                continue
            if row.get("price") != slo_proposal.STAMP_ONE_EDIT:
                continue
            mine = by_artifact.get(str(row["artifact"]))
            population.append({
                "artifact": str(row["artifact"]),
                "price": row.get("price"),
                "reader": (mine or {}).get("reader") or slo_proposal.READER_UNMEASURED,
            })

    tally: dict = {}
    for row in (population or []):
        tally[row["reader"]] = tally.get(row["reader"], 0) + 1
    return {
        "status": "OK",
        "door": str(Path(root) / "scripts" / "consume_office_reports.py"),
        "probe_entry": stamp.get(ATTRIBUTION_ENTRY_FIELD),
        "inventory": inventory,
        "inventory_population": len(declared),
        "population": None if population is None else len(population),
        "population_cause": population_cause,
        "population_rows": population,
        "tally": tally,
        "data_dir": str(dd),
        # НАХОДКА — артефакт, чья отметка ОБЪЯВЛЕНА читаемой и чей читатель
        # умеет пожаловаться только на её ОТСУТСТВИЕ. «Читатель нем» находкой
        # НЕ является: это ответ заказа (штамп без читателя), а не дефект
        # проводки — чинится он решением не платить, а не правкой.
        "findings": [row for row in rows
                     if row["reader"] == slo_proposal.READER_ABSENCE_ONLY],
        "rows": rows,
    }


def stamp_reader_line(doc: dict) -> str:
    """Строка ЧИТАТЕЛЯ штампа. Единственная её форма, читатель — :func:`report`.

    Тот же выбор читателя и та же измеренная причина, что у
    :func:`write_attribution_line` и :func:`write_stamp_price_line` (ADR-820):
    строка, которую печатает только ``findings_bridge``, уходит в лог агента, а
    не в вывод шага 0-офис.
    """
    section = observed(doc, "declared_stamp_reader", kind=dict)
    if section is None:
        return ("  читатель штампа атрибуции: НЕ ИЗМЕРЕНО — секции "
                "`declared_stamp_reader` в замере нет (отчёт написан "
                "производителем ДО ADR-822)")
    if section.get("status") != "OK":
        return ("  читатель штампа атрибуции: НЕ ИЗМЕРЕНО — "
                f"{section.get('cause') or 'причина не названа'}")
    inventory = observed(section, "inventory", kind=dict) or {}
    tally = observed(section, "tally", kind=dict) or {}
    findings = section.get("findings") or []
    names = ", ".join(str(row.get("artifact")) for row in findings)
    population = section.get("population")
    read = tally.get(slo_proposal.READER_ENTRY_NAMED, 0)
    return (
        "  читатель штампа атрибуции (ADR-822, в сумму вердиктов НЕ входит): по "
        f"ВСЕЙ конституции ({section.get('inventory_population')} артефакт(ов)) "
        f"вход НАЗВАЛ БЫ читатель у {inventory.get(slo_proposal.READER_ENTRY_NAMED, 0)}"
        f" · замечено только ОТСУТСТВИЕ у "
        f"{inventory.get(slo_proposal.READER_ABSENCE_ONLY, 0)}"
        f"{f' ({names})' if names else ''} · читатель НЕМ у "
        f"{inventory.get(slo_proposal.READER_MUTE, 0)} · измеренной двери НЕ "
        f"адресовано {inventory.get(slo_proposal.READER_NOT_ADDRESSED, 0)} · имя "
        f"СПОРНО {inventory.get(slo_proposal.READER_NAME_CONTESTED, 0)} · НЕ "
        f"ИЗМЕРЕНО {inventory.get(slo_proposal.READER_UNMEASURED, 0)}; у НАСЕЛЕНИЯ "
        f"ВОПРОСА ("
        f"{'НЕ ИЗМЕРЕНО' if population is None else str(population) + ' артефакт(ов), которым штамп пришёл бы от ОДНОЙ правки'}"
        f") прочитан был бы {read}"
        + ("" if population is None else
           f", остальные {population - read} пришли бы НЕМЫМИ")
        + " — ЦЕНА и ЧИТАТЕЛЬ это РАЗНЫЕ числа, и дешёвая правка молчит так же "
          "дорого")


#: Строка-ПРОБА для вопроса «дойдёт ли до цикла строка отчёта» (ADR-823).
#:
#: Литерал, а не случайная строка: обе стороны сравнения обязаны быть
#: закреплены, иначе тест сравнивает своё с несвоим. Форма выбрана так, чтобы
#: в выводе двери её не мог напечатать никто другой.
#:
#: **ПУСТАЯ проба сделала бы вердикт ЗЕЛЁНЫМ при любом значении** — ``"" in
#: что_угодно`` истинно всегда, и перепись объявила бы прочитанными все 139
#: артефактов, ничего не измерив. Это ровно тот класс «проверка зелёная при
#: любом значении», который мутационный прогон ADR-822 нашёл в своём же
#: контроле; поэтому непустота пробы проверяется ВХОДОМ переписи, а не
#: предполагается.
REPORT_LINE_PROBE = "⟦SPA-ПРОБА-СТРОКИ-ОТЧЁТА-ADR-823⟧"

#: Куда кладётся проба в отрисовке производителя: ВТОРОЙ строкой.
#:
#: Это не вкус, а МЕСТО ПРЕДЛАГАЕМОЙ ПРАВКИ: у всех одиннадцати производителей,
#: чей отчёт уже называет звавшего, строка ``[ЗВАВШИЙ] provenance_line(...)``
#: стои́т вторым элементом списка — сразу за строкой состояния (образец —
#: ``truncated_input_census.report``). Мерить в другом месте значило бы
#: отвечать про правку, которой никто не предлагал.
#:
#: **Чего мера НЕ утверждает:** что место безразлично. Отрисовка производителя
#: вправе фильтровать свои строки сама (``foreign_markup_reader_census``
#: пересобирает их в три группы), и вердикт здесь — про ЭТО место. Замер 26.10
#: по четвёрке ADR-822 сравнил три места (голова, вторая строка, хвост) и
#: расхождений не нашёл — но население «место решает» ОСТАЛОСЬ НЕ ИЗМЕРЕННЫМ по
#: всей конституции, и выдавать четыре артефакта за 139 нельзя.
REPORT_LINE_POSITION = 1


class _RenderingSpy(types.ModuleType):
    """Подставной модуль производителя: ЗАПИСЫВАЕТ, о чём спросила дверь.

    Нужен потому, что вопрос «спросила ли дверь у производителя отрисовку»
    обязан меряться ИСХОДОМ. Разбор текста двери (AST её ветвей) ответил бы на
    СОСЕДНИЙ вопрос — «написана ли ветка», — и ошибся бы в обе стороны: ветка
    бывает написана и недостижима, а зов бывает не в ветке.

    Доступ к атрибуту и ЗОВ атрибута — тоже разные наблюдения, и оба
    записываются: дверь может взять у производителя константу и не звать его
    отрисовку вовсе. Проба вкладывается ТОЛЬКО в возврат, похожий на текст
    (строка либо последовательность строк); возврат иной формы отмечается в
    ``non_text`` и зовом отрисовки НЕ считается — иначе «позвала помощника,
    отдающего число» читалось бы как «позвала отрисовку и уронила строку».
    """

    def __init__(self, real, probe: str, position: int = REPORT_LINE_POSITION):
        super().__init__(getattr(real, "__name__", "spa_rendering_spy"))
        self.__dict__["_real"] = real
        self.__dict__["_probe"] = probe
        self.__dict__["_position"] = position
        self.__dict__["accessed"] = []
        self.__dict__["invoked"] = []
        self.__dict__["non_text"] = []

    def __getattr__(self, name):
        real = self.__dict__["_real"]
        value = getattr(real, name)
        if name.startswith("__"):
            return value
        self.__dict__["accessed"].append(name)
        if not callable(value):
            return value
        probe = self.__dict__["_probe"]
        position = self.__dict__["_position"]
        spy = self

        def rendering(*args, **kwargs):
            result = value(*args, **kwargs)
            if isinstance(result, str):
                spy.__dict__["invoked"].append(name)
                head, sep, rest = result.partition("\n")
                return head + "\n" + probe + (sep + rest if sep else "")
            if isinstance(result, (list, tuple)) and all(
                    isinstance(item, str) for item in result):
                spy.__dict__["invoked"].append(name)
                lines = list(result)
                lines.insert(min(position, len(lines)), probe)
                return lines
            spy.__dict__["non_text"].append(name)
            return result

        return rendering


def report_line_producer(door, artifact: str) -> tuple:
    """Модуль производителя ПО ВЕРСИИ САМОЙ ДВЕРИ. ``(имя модуля, причина)``.

    Берётся ``_PRODUCER`` измеренной двери — её СОБСТВЕННАЯ карта «артефакт →
    модуль». Своя копия этой карты была бы вторым определением одного имени
    («одно имя — один объект», `.claude/rules/adapters.md`) и разошлась бы с
    дверью молча, после чего перепись мерила бы модуль, которого дверь не
    зовёт.

    Имя приватно у двери намеренно, и это НЕ обход: вопрос переписи — что
    делает НАСТОЯЩИЙ читатель, а публичной карты производителей у него нет.
    Нет карты вовсе либо нет в ней этого артефакта ⇒ НЕ ИЗМЕРЕНО с причиной
    (инв. #17), а не «производителя нет».
    """
    table = getattr(door, "_PRODUCER", None)
    if not isinstance(table, dict):
        return None, ("у измеренной двери нет карты `_PRODUCER` — какой модуль "
                      "она зовёт для артефакта, сказать нечем")
    path = table.get(artifact.split("/")[-1])
    if not isinstance(path, str) or not path.endswith(".py"):
        return None, ("измеренная дверь не называет производителя этого "
                      "артефакта в своей карте `_PRODUCER` — её ветка могла бы "
                      "звать его и мимо карты, и это НЕ «отрисовки нет»")
    return path[:-3].replace("/", "."), ""


def report_line_observation(door, module_name: str, path: Path, *,
                            root: Path, artifact_root: Path,
                            probe: str = REPORT_LINE_PROBE,
                            now: Optional[datetime] = None) -> dict:
    """ИСХОД: дойдёт ли до вывода двери строка, вложенная в отрисовку.

    Один прогон НАСТОЯЩЕЙ двери (та же ветка ``_summarize_json``, что у
    :func:`stamp_reader_observation`, и по той же причине: ``main()`` пишет
    квитанции, и спросить им читателя значило бы изменить состояние системы
    вопросом о ней). У вывода спрашиваются ДВА вопроса:

    ``as_line``
        проба нашлась ОТДЕЛЬНОЙ строкой — ровно то, чем правка будет для
        читателя;
    ``anywhere``
        проба нашлась в СКЛЕЙКЕ всех строк — то есть её буквы доехали, а
        строка нет. Между двумя ответами живёт измеренный дефект
        ``out.extend(<строка>)``.

    Подстановка модуля снимается в ``finally``: подставной модуль, оставшийся в
    ``sys.modules``, отвечал бы вместо настоящего всем последующим вопросам
    этого же процесса.
    """
    if not probe:
        return {"as_line": None, "anywhere": None, "asked": None,
                "why": "строка-проба ПУСТА — поиск её в любом выводе истинен "
                       "всегда, и перепись не измерила бы ничего"}
    try:
        if not path.is_file():
            return {"as_line": None, "anywhere": None, "asked": None,
                    "why": f"носителя нет на месте ({path}) — дверь нечем "
                           f"позвать"}
    except OSError as exc:
        return {"as_line": None, "anywhere": None, "asked": None,
                "why": f"наличие носителя не прочитано ({type(exc).__name__})"}
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as exc:
        return {"as_line": None, "anywhere": None, "asked": None,
                "why": f"носитель не разобран как JSON ({type(exc).__name__}) — "
                       f"отрисовать его дверью нечем"}
    try:
        real = importlib.import_module(module_name)
    except Exception as exc:  # чужой модуль — его отказ не наш вердикт
        return {"as_line": None, "anywhere": None, "asked": None,
                "why": f"модуль производителя `{module_name}` не ввозится "
                       f"({type(exc).__name__}: {exc})"}
    spy = _RenderingSpy(real, probe)
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = spy
    try:
        out = door._summarize_json(str(path), doc, now=now, root=str(root),
                                   artifact_root=str(artifact_root)) or []
    except Exception as exc:  # отказ ЧУЖОЙ двери — третий исход, не вердикт
        return {"as_line": None, "anywhere": None, "asked": None,
                "why": f"дверь отказала на отрисовке ({type(exc).__name__}: {exc})"}
    finally:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
    lines = [str(line) for line in out]
    return {"as_line": any(probe in line for line in lines),
            "anywhere": probe in "".join(lines),
            "asked": bool(spy.invoked),
            "rendering": sorted(set(spy.invoked)) or None,
            "accessed": sorted(set(spy.accessed)) or None,
            "non_text": sorted(set(spy.non_text)) or None,
            "door_lines": len(lines), "why": ""}


def report_line_census(stamp_reader: dict, root: Path, data_dir: Path, *,
                       probe: str = REPORT_LINE_PROBE,
                       now: Optional[datetime] = None) -> dict:
    """ДОЙДЁТ ЛИ СТРОКА ОТЧЁТА до цикла — ВОСЬМАЯ секция (ADR-823, заказ G822).

    ADR-822 ответил про штамп: канал дёшев (одна правка — 153 артефакта), а
    читателя у него нет (144 из 153 пришли бы немыми). И нашёл четвёрку, чей
    читатель умеет пожаловаться только на ОТСУТСТВИЕ штампа. Заказ G822
    запретил платить за эту четвёрку прежде, чем спрошена цена ЕЁ строки:

        «Правка выглядит как одна строка ``provenance_line(...)`` в каждом
        ``report()`` — но прежде замерить то же, что замерил этот цикл про
        общую дверь: есть ли у СТРОКИ отчёта этих четырёх читатель, доходящий
        до цикла. У одиннадцати читающих он измерен, у этих четырёх — НЕ
        ИЗМЕРЕН ни разу. Четыре правки, читателя у которых нет, суть тот же
        класс, что 144 немых штампа, только дешевле и потому соблазнительнее.»

    **Здесь ТРИ числа, и они не складываются** — тот же порядок, что у
    ADR-820/821/822:

    ``inventory``
        перепись по ВСЕЙ конституции: дойдёт ли строка у каждого артефакта.
    ``population_absence_only``
        четвёрка ADR-822, взятая ССЫЛКОЙ у СЕДЬМОЙ секции (её ``findings``) —
        это и есть население вопроса G822 п. 1.
    ``population_mute``
        «читатель НЕМ» СЕДЬМОЙ секции, взятое ССЫЛКОЙ, — население вопроса
        G822 п. 2, где заказ требовал разделить немоту по причине ТОЛЬКО после
        замера населения.

    **ОТВЕТ G822 п. 1 (замер 26.10): цена ПОЛОЖИТЕЛЬНА, и это противоположно
    ответу про штамп.** У трёх из четырёх строка приходит в вывод шага 0-офис
    ОТДЕЛЬНОЙ строкой ⇒ правка будет прочитана. У четвёртого
    (``data/vacuous_advice_census.json``) она приходит ПОСИМВОЛЬНО: его
    ``format_report`` отдаёт ОДНУ строку (его CLI её печатает), а ветка двери
    делала ``out.extend(...)`` — и отчёт стоял в выводе цикла столбиком из
    **731** одиночной буквы. Это НАХОДКА, а не ответ: канал есть, сообщения
    нет, и ни один сторож об этом не сказал.

    **ОТВЕТ G822 п. 2: немота делится замером, и одно из состояний — ноль.**
    «Дверь не спросила отрисовку вовсе» — **34** артефакта из 139
    адресованных: их дверь печатает СВОИМИ строками, и правка в отрисовке
    производителя была бы нема при любом содержании. «Спросила и уронила» —
    **0**: население пусто, и делить его дальше не на чем (G820 п. 2).

    Вердикты сроков эта перепись не переписывает ни одним числом — тот же
    порядок, что у ADR-816/817/819/820/821/822 (заказ G815 п. 2).
    """
    section = stamp_reader if isinstance(stamp_reader, dict) else {}
    if section.get("status") != "OK" or not isinstance(section.get("rows"), list):
        return {"status": slo_proposal.REPORT_LINE_UNMEASURED,
                "cause": ("адресность артефактов НЕ ИЗМЕРЕНА — седьмая секция "
                          "(`declared_stamp_reader`) не дала строк: "
                          f"{section.get('cause') or section.get('status') or 'секции нет'}"),
                "door": None, "inventory": None, "inventory_population": None,
                "population_absence_only": None, "population_mute": None,
                "absence_only_tally": None, "mute_tally": None,
                "rows": None, "findings": None}
    door, why = stamp_reader_door(Path(root))
    if door is None:
        return {"status": slo_proposal.REPORT_LINE_UNMEASURED,
                "cause": f"измеренная дверь чтения НЕ ОПРОШЕНА: {why}",
                "door": None, "inventory": None, "inventory_population": None,
                "population_absence_only": None, "population_mute": None,
                "absence_only_tally": None, "mute_tally": None,
                "rows": None, "findings": None}
    dd = Path(data_dir)
    rows: list = []
    inventory: dict = {}
    for source in section["rows"]:
        if not isinstance(source, dict) or not source.get("artifact"):
            continue
        artifact = str(source["artifact"])
        # Адресность берётся ССЫЛКОЙ у СЕДЬМОЙ секции: там она измерена у
        # ЕДИНСТВЕННОГО читателя правила отбора (`office_targets`). Второе
        # определение адресности разошлось бы с первым молча.
        addressed = source.get("addressed")
        obs = {"as_line": None, "anywhere": None, "asked": None, "why": ""}
        module_name = None
        if addressed is True:
            module_name, why = report_line_producer(door, artifact)
            if module_name is None:
                obs["why"] = why
            else:
                obs = report_line_observation(
                    door, module_name, artifact_file(artifact, Path(root), dd),
                    root=Path(root), artifact_root=dd.parent, probe=probe,
                    now=now)
        kind, why = slo_proposal.report_line(
            obs.get("as_line"), obs.get("anywhere"),
            addressed=addressed, asked=obs.get("asked"))
        inventory[kind] = inventory.get(kind, 0) + 1
        rows.append({"artifact": artifact, "line": kind,
                     "addressed": addressed, "producer": module_name,
                     "as_line": obs.get("as_line"),
                     "anywhere": obs.get("anywhere"),
                     "asked": obs.get("asked"),
                     "rendering": obs.get("rendering"),
                     "accessed": obs.get("accessed"),
                     "door_lines": obs.get("door_lines"),
                     "note": f"{why}; {obs['why']}" if obs.get("why") else why})

    by_artifact = {row["artifact"]: row for row in rows}

    def _population(source_rows, label):
        """Население вопроса — ССЫЛКОЙ у седьмой секции, не счётом заново."""
        out = []
        for source in source_rows or []:
            if not isinstance(source, dict) or not source.get("artifact"):
                continue
            mine = by_artifact.get(str(source["artifact"]))
            out.append({
                "artifact": str(source["artifact"]),
                "stamp_reader": source.get("reader"),
                "line": (mine or {}).get("line") or slo_proposal.REPORT_LINE_UNMEASURED,
                "rendering": (mine or {}).get("rendering"),
            })
        return out

    absence_only = _population(section.get("findings"), "absence_only")
    mute = _population([row for row in section["rows"]
                        if isinstance(row, dict)
                        and row.get("reader") == slo_proposal.READER_MUTE], "mute")
    absence_tally: dict = {}
    for row in absence_only:
        absence_tally[row["line"]] = absence_tally.get(row["line"], 0) + 1
    mute_tally: dict = {}
    for row in mute:
        mute_tally[row["line"]] = mute_tally.get(row["line"], 0) + 1
    return {
        "status": "OK",
        "door": str(Path(root) / "scripts" / "consume_office_reports.py"),
        "probe": probe,
        "probe_position": REPORT_LINE_POSITION,
        "inventory": inventory,
        "inventory_population": len(rows),
        "population_absence_only": len(absence_only),
        "population_absence_only_rows": absence_only,
        "absence_only_tally": absence_tally,
        "population_mute": len(mute),
        "mute_tally": mute_tally,
        "data_dir": str(dd),
        # НАХОДКА — отчёт, доезжающий до цикла ПОСИМВОЛЬНО. «Дверь не спросила»
        # находкой НЕ является: это ОТВЕТ заказа про немоту (правка там будет
        # нема), а не дефект проводки — у двери свои строки, и она их печатает.
        "findings": [row for row in rows
                     if row["line"] == slo_proposal.REPORT_LINE_SHREDDED],
        "rows": rows,
    }


def report_line_line(doc: dict) -> str:
    """Строка ЦЕНЫ СТРОКИ ОТЧЁТА. Единственная её форма, читатель — :func:`report`.

    Тот же выбор читателя и та же измеренная причина, что у
    :func:`stamp_reader_line` и родни (ADR-820): строка, которую печатает
    только ``findings_bridge``, уходит в лог агента, а не в вывод шага 0-офис.
    """
    section = observed(doc, "declared_report_line_reader", kind=dict)
    if section is None:
        return ("  цена строки отчёта: НЕ ИЗМЕРЕНО — секции "
                "`declared_report_line_reader` в замере нет (отчёт написан "
                "производителем ДО ADR-823)")
    if section.get("status") != "OK":
        return ("  цена строки отчёта: НЕ ИЗМЕРЕНО — "
                f"{section.get('cause') or 'причина не названа'}")
    inventory = observed(section, "inventory", kind=dict) or {}
    absence = observed(section, "absence_only_tally", kind=dict) or {}
    mute = observed(section, "mute_tally", kind=dict) or {}
    findings = section.get("findings") or []
    names = ", ".join(str(row.get("artifact")) for row in findings)
    return (
        "  цена строки отчёта (ADR-823, в сумму вердиктов НЕ входит): по ВСЕЙ "
        f"конституции ({section.get('inventory_population')} артефакт(ов)) "
        f"строка ДОШЛА БЫ у {inventory.get(slo_proposal.REPORT_LINE_READ, 0)}"
        f" · дошла бы ПОСИМВОЛЬНО у "
        f"{inventory.get(slo_proposal.REPORT_LINE_SHREDDED, 0)}"
        f"{f' ({names})' if names else ''} · дверь отрисовку НЕ СПРАШИВАЕТ у "
        f"{inventory.get(slo_proposal.REPORT_RENDERING_NOT_ASKED, 0)} · спросила "
        f"и УРОНИЛА у {inventory.get(slo_proposal.REPORT_LINE_DROPPED, 0)} · "
        f"двери НЕ адресовано "
        f"{inventory.get(slo_proposal.REPORT_LINE_NOT_ADDRESSED, 0)} · НЕ "
        f"ИЗМЕРЕНО {inventory.get(slo_proposal.REPORT_LINE_UNMEASURED, 0)}; у "
        f"ЧЕТВЁРКИ ADR-822 ({section.get('population_absence_only')}) дошла бы у "
        f"{absence.get(slo_proposal.REPORT_LINE_READ, 0)}, посимвольно у "
        f"{absence.get(slo_proposal.REPORT_LINE_SHREDDED, 0)}; у НЕМОТЫ "
        f"({section.get('population_mute')}) дверь не спрашивает отрисовку у "
        f"{mute.get(slo_proposal.REPORT_RENDERING_NOT_ASKED, 0)}, уронила у "
        f"{mute.get(slo_proposal.REPORT_LINE_DROPPED, 0)} — ЧИТАТЕЛЬ ШТАМПА и "
        "ЧИТАТЕЛЬ СТРОКИ это РАЗНЫЕ вопросы, и второй отвечает «да» там, где "
        "первый ответил «нет»")

def write_attribution_line(doc: dict) -> str:
    """Строка КАНАЛА АТРИБУЦИИ. Единственная её форма.

    Живёт здесь по той же причине, что :func:`declared_axis_line` и родня, но
    читателя получает ДРУГОГО: не инлайн-печать `findings_bridge.main`, а
    :func:`report` — то есть тот самый вывод шага 0-офис, который цикл читает.
    Замер 26.10 (ADR-820): четыре строки ADR-816…819 объявлены «строкой шага
    0-офис», а зовёт их ровно один не-тестовый вызывающий — `findings_bridge`,
    чей stdout уходит в лог агента `com.spa.decision_loop`; `report()` не несёт
    ни одной из них, и в выводе шага 0-офис их НЕТ. Класс чужой (четыре ADR со
    своими авторами) и заведён карточкой; своя строка его не пополняет.
    """
    section = observed(doc, "declared_write_attribution", kind=dict)
    if section is None:
        return ("  канал атрибуции записи: НЕ ИЗМЕРЕНО — секции "
                "`declared_write_attribution` в замере нет (отчёт написан "
                "производителем ДО ADR-820)")
    if section.get("status") != "OK":
        return ("  канал атрибуции записи: НЕ ИЗМЕРЕНО — "
                f"{section.get('cause') or 'причина не названа'}")
    inventory = observed(section, "inventory", kind=dict) or {}
    tally = observed(section, "tally", kind=dict) or {}
    findings = section.get("findings")
    homes = observed(section, "population_homes", kind=dict) or {}
    names = ", ".join(f"{r.get('artifact')} ({', '.join(r.get('code_keys') or [])})"
                      for r in (findings or []))
    return (
        "  канал атрибуции записи (ADR-820, в сумму вердиктов НЕ входит): у "
        f"вопроса «кто записал» население {section.get('population')} артефакт(ов) "
        f"(со-производимых {homes.get('co_produced')} · с находкой ADR-819 "
        f"{'НЕ ИЗМЕРЕНО' if homes.get('misdeclared') is None else homes['misdeclared']})"
        f" — из них точку входа прогона несут "
        f"{tally.get(slo_proposal.ATTRIBUTION_ENTRY_NAMED, 0)} · имя КОДА вместо "
        f"атрибуции {tally.get(slo_proposal.ATTRIBUTION_CODE_ONLY, 0)}"
        f"{f' ({names})' if names else ''} · ничего "
        f"{tally.get(slo_proposal.ATTRIBUTION_ABSENT, 0)} · носителя нет "
        f"{tally.get(slo_proposal.ATTRIBUTION_CARRIER_ABSENT, 0)} · НЕ ИЗМЕРЕНО "
        f"{tally.get(slo_proposal.ATTRIBUTION_UNMEASURED, 0)}; по ВСЕЙ конституции "
        f"({section.get('inventory_population')} артефакт(ов)) точку входа несут "
        f"{inventory.get(slo_proposal.ATTRIBUTION_ENTRY_NAMED, 0)} — канал в "
        "системе есть, у населения вопроса его может не быть, и это РАЗНЫЕ числа")


def measure(manifest_path: Optional[Path] = None, *, log_dir: Path = Path("/tmp"),
            scripts_dir: Optional[Path] = None, now: Optional[datetime] = None,
            window_hours: float = WINDOW_HOURS, root: Optional[Path] = None,
            data_dir: Optional[Path] = None) -> dict:
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
    # Каталог ДАННЫХ — отдельный вход, а не производное от корня (ADR-819).
    # Замер из worktree обязан спрашивать живой `data/` прод-дерева: иначе
    # «артефакта нет» получается ПО ПОСТРОЕНИЮ, и перепись правдивости
    # конституции отвечает про своё дерево, а не про систему (урок ADR-364).
    data = Path(data_dir) if data_dir is not None else base / "data"
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
        # Та же дверь, что и у объявленной оси (ADR-818): прежде здесь жил свой
        # `intent != ACTIVE`, и правило существовало в двух копиях — одна
        # исполнялась, вторая (на объявленной оси) отсутствовала вовсе.
        runs, _why_runs = slo_proposal.producer_standing(intent)
        if runs is not True:
            if declares:
                # Ярлык НАЗЫВАЕТСЯ как он есть, а «не прочитан» — отдельным
                # ведром: прежняя редакция клала под `intent_absent` любой
                # незнакомый ярлык, то есть `paused` докладывался как
                # «состояние не объявлено». Замер 26.10: `paused` объявлен у
                # одного агента, пар со сроком у него НОЛЬ, поэтому ни одно
                # число этой правкой не двинулось — дефект закрыт до появления
                # населения, а не после.
                key = intent if isinstance(intent, str) and intent else "intent_absent"
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
    # Замер ЧЕТВЁРТОЙ секции считается ОДИН раз: её находки суть второй дом
    # населения ПЯТОЙ (ADR-820), и второй независимый прогон той же переписи
    # дал бы два разных ответа на один вопрос при любом сдвиге часов.
    _reality_section = producer_reality_census(
        declared_section, agents, base, data, now=now)
    # Замер ПЯТОЙ секции тоже считается ОДИН раз: её строки суть население
    # вопроса для ШЕСТОЙ (ADR-821), и второй независимый прогон дал бы два
    # разных ответа про один артефакт при любом сдвиге содержимого файла.
    _attribution_section = write_attribution_census(
        _reality_section, agents, base, data)
    # Замер ШЕСТОЙ секции тоже считается ОДИН раз: её строки с ценой «одна
    # правка» суть население вопроса для СЕДЬМОЙ (ADR-822), и второй
    # независимый прогон дал бы два разных ответа про один артефакт при любом
    # сдвиге дерева кода.
    _price_section = write_stamp_price_census(
        _attribution_section, agents, base, data)
    # Замер СЕДЬМОЙ секции тоже считается ОДИН раз: её строки суть население
    # вопроса для ВОСЬМОЙ (ADR-823) и источник её адресности, и второй
    # независимый прогон дал бы два разных ответа про один артефакт при любом
    # сдвиге содержимого файла.
    _reader_section = stamp_reader_census(
        _price_section, agents, base, data, manifest=payload, now=now)
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
        # ПРАВДИВОСТЬ КОНСТИТУЦИИ — ЧЕТВЁРТАЯ секция (ADR-819, заказ G818 п. 1).
        # Как и две предыдущие, в `tally`/`verdict` не входит ни одним числом:
        # предмет у неё не срок и не пара, а то, НАЗВАН ЛИ В КОНСТИТУЦИИ тот,
        # кто файл действительно пишет. Сложить её с вердиктами о сроках значило
        # бы ответить на пятый, никем не заданный вопрос.
        "declared_producer_reality": _reality_section,
        # КАНАЛ АТРИБУЦИИ — ПЯТАЯ секция (ADR-820, заказ G819 п. 1). Как и
        # четыре предыдущие, в `tally`/`verdict` не входит ни одним числом:
        # предмет у неё не срок и не правдивость конституции, а то, СУЩЕСТВУЕТ
        # ли наблюдаемый канал, приписывающий запись запущенному. Секция
        # ЧЕТВЁРТАЯ подаётся ей входом (второй дом населения — её находки), и
        # её «НЕ ИЗМЕРЕНО» остаётся «НЕ ИЗМЕРЕНО», а не превращается в ноль.
        "declared_write_attribution": _attribution_section,
        # ЦЕНА ШТАМПА — ШЕСТАЯ секция (ADR-821, заказ G820 п. 1). Как и пять
        # предыдущих, в `tally`/`verdict` не входит ни одним числом: предмет у
        # неё не срок и не канал, а то, ЧЕГО СТОИЛА БЫ правка, дающая канал.
        # ПЯТАЯ секция подаётся ей входом (население вопроса берётся ССЫЛКОЙ, а
        # не считается заново), и её «НЕ ИЗМЕРЕНО» остаётся «НЕ ИЗМЕРЕНО».
        "declared_write_stamp_price": _price_section,
        # ЧИТАТЕЛЬ ШТАМПА — СЕДЬМАЯ секция (ADR-822, заказ G821 п. 1). Как и
        # шесть предыдущих, в `tally`/`verdict` не входит ни одним числом:
        # предмет у неё не срок, не канал и не цена, а то, ПРОЧТЁТ ЛИ кто-нибудь
        # штамп, если правка его принесёт. ШЕСТАЯ секция подаётся ей входом
        # (население вопроса — её строки с ценой «одна правка», взятые ССЫЛКОЙ),
        # и её «НЕ ИЗМЕРЕНО» остаётся «НЕ ИЗМЕРЕНО», а не превращается в ноль.
        "declared_stamp_reader": _reader_section,
        # ЦЕНА СТРОКИ ОТЧЁТА — ВОСЬМАЯ секция (ADR-823, заказ G822 пп. 1–2).
        # Как и семь предыдущих, в `tally`/`verdict` не входит ни одним числом:
        # предмет у неё не срок, не канал, не цена штампа и не его читатель, а
        # то, ДОЙДЁТ ЛИ ДО ЦИКЛА одна строка, добавленная в отрисовку
        # производителя. СЕДЬМАЯ секция подаётся ей входом: оба населения
        # вопроса (четвёрка «замечено только отсутствие» и немота) берутся
        # ССЫЛКОЙ, а адресность — измеренной ею же, и её «НЕ ИЗМЕРЕНО»
        # остаётся «НЕ ИЗМЕРЕНО», а не превращается в ноль.
        "declared_report_line_reader": report_line_census(
            _reader_section, base, data, now=now),
        "rows": rows,
        "findings": findings,
        "measured_from": {"manifest": str(manifest), "log_dir": str(log_dir),
                          "scripts_dir": str(scripts), "data_dir": str(data)},
        "not_reported": [
            "моменты ЗАПИСИ артефакта (период мерится СТАРТ→СТАРТ прогона)",
            "вторая запись о прогонах (launchctl runs — без отметок времени)",
            "верность самого срока (цену опоздания назначают две роли, ADR-158)",
            "производитель вне конституции",
            "КТО именно записал артефакт (ADR-819): свежая запись при "
            "неидущем объявленном производителе доказывает, что писал КТО-ТО "
            "ДРУГОЙ, но имени его не называет — для имени нужна атрибуция, "
            "которой у `mtime` нет. С ADR-820 про САМ КАНАЛ атрибуции "
            "докладывает пятая секция (`declared_write_attribution`): имени "
            "писавшего она по-прежнему не называет, но ОТСУТСТВИЕ канала у "
            "населения вопроса называет числом, а не молчанием",
            "сводится ли НАЗВАННАЯ точка входа к ЯРЛЫКУ агента (ADR-820): в "
            "конституции у агента объявлена только обёртка (`program`), правила "
            "«обёртка → цель» здесь нет ни строкой — `write_attribution_entry_named` "
            "означает «канал к запущенному существует», а не «агент назван»",
            "ЧИТАТЕЛЕЙ штампа БОЛЬШЕ ОДНОЙ двери (ADR-822): измеренная "
            "дверь одна — отрисовка шага 0-офис (`_summarize_json`), и выбрана "
            "она потому, что про её вывод ИЗМЕРЕНО, что он доходит до цикла. "
            "Прочие объявленные потребители (20 имён на 20 артефактов против "
            "141 у `orchestrator_protocol`) НЕ ИЗМЕРЕНЫ, и "
            "`stamp_reader_door_not_addressed` означает «измеренная дверь его "
            "не зовёт», а не «читателя нет вовсе»",
            "читателя МАРКДАУН-артефакта (ADR-822): у шага 0-офис своя дверь "
            "`_summarize_md`, и спрошена она не была — `docs/SYSTEM_BRIEFING.md` "
            "остаётся третьим исходом с названной причиной, а не «читателя нет»",
            "НАДО ЛИ делать правку (ADR-822): перепись отвечает, сколько "
            "штампов пришло бы НЕМЫМИ, а решение платить или нет — предмет с "
            "автором; прибор только ЧИТАЕТ",
            "запись ПРОГОНОВ как канал атрибуции (ADR-820): обёртка пишет в лог "
            "баннеры START/EXIT с именем агента и pid, но про записи ФАЙЛОВ в "
            "нём нет ни строки; связать запись с прогоном по времени значило бы "
            "допустить, что файл пишет только прогон, — а ADR-819 ровно это и "
            "опроверг (снимок писал библиотечный зов из ДРУГОГО процесса)",
            "С КАКИМ ТАКТОМ пишут артефакт (ADR-819): `mtime` есть ОДНА точка, "
            "а не история, поэтому «свежее срока сегодня» не означает «срок "
            "будет выдержан» — вердикт переписи правдивости говорит о "
            "КОНСТИТУЦИИ, а не о выдерживании срока",
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
        doc = measure(root=base, log_dir=Path(log_dir), now=now,
                      data_dir=source, **kw)
    except Unmeasured as exc:
        doc = {"status": "UNMEASURED", "reason": str(exc), "generated_at": _stamp(now)}
    if write:
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(doc, str(target))
    return {"measured": True, "doc": doc, "artifact": str(target)}


def measured_from_line(doc: dict) -> str:
    """Строка ВХОДОВ замера: по какому каталогу данных получены числа ниже.

    **Предмет — не свежесть и не население, а АДРЕС замера.** Замер 26.10
    (цикл #948, хвост ADR-823): тот же код, то же дерево, РАЗНЫЕ каталоги
    данных дают разные числа у всех четырёх строк семейства ADR-820…823 —
    живой прод-``data/`` «дошла бы 89 · НЕ ИЗМЕРЕНО 14», замороженная
    git-копия ``data/`` в worktree «0 · 137». Fail-OPEN при этом НЕТ и
    инвариант #17 соблюдён: пропажа носителя честно уходит в третий исход. Но
    у «НЕ ИЗМЕРЕНО» не названа ПРИЧИНА — каталог записан в ``measured_from`` и
    в ``data_dir`` каждой секции, а в ЧИТАЕМУЮ циклом строку не попадает ни
    разу (замер этого цикла: **0** строк из 27 называют каталог при том, что
    **четыре** секции из пяти несут его в JSON). Читатель строки не отличает
    «система такова» от «прогон был слеп».

    **Почему строка ОДНА, а не по одной в каждой из четырёх.** Цена измерена
    дифференциально: ``measured_from`` лежит на ВЕРХНЕМ уровне замера, поэтому
    одна строка отвечает за весь отчёт — все 27 строк и все пять секций,
    включая те, которых ещё нет. Подстрока в каждой из четырёх стоила бы
    четыре правки и покрыла бы четыре строки, а пятую (``ADR-819``,
    ``declared_producer_reality``) заказ G824 не назвал вовсе — его счёт был
    «четыре», замер дал ПЯТЬ носителей ``data_dir``.

    **Читатель измерен, а не предположён** (тот же порядок, что G821 п. 1 →
    ADR-822 и G822 п. 1 → ADR-823): проба, вложенная в отрисовку этого
    производителя, приходит в вывод измеренной двери ОТДЕЛЬНОЙ строкой —
    вердикт :data:`slo_proposal.REPORT_LINE_READ` у
    ``data/slo_keepability.json``. То есть правка будет ПРОЧИТАНА, и это
    противоположно ответу про штамп атрибуции (144 из 153 пришли бы немыми).

    **Файловую систему эта строка НЕ спрашивает — и не вправе.** Отрисовка
    идёт над ДОКУМЕНТОМ, измеренным в другом процессе и, вообще говоря, на
    другой машине; спросить здесь ``Path(data_dir).is_dir()`` значило бы
    ответить про дерево ЧИТАТЕЛЯ, а выдать ответ за дерево ЗАМЕРА. Читаемость
    каталога берётся ССЫЛКОЙ у секций, которые её наблюдали (``data_dir_readable``,
    ADR-819/820), и её отсутствие остаётся «НЕ ИЗМЕРЕНО», а не «читаем».

    Три исхода различимы (инв. #17): адрес НАЗВАН · ``measured_from`` есть, а
    каталога в нём нет · секции ``measured_from`` в замере нет вовсе (отчёт
    написан производителем ДО ADR-824).
    """
    inputs = observed(doc, "measured_from", kind=dict)
    if inputs is None:
        return ("  ИЗМЕРЕНО ПО: НЕ ИЗМЕРЕНО — секции `measured_from` в замере "
                "нет (отчёт написан производителем ДО ADR-824); по какому "
                "каталогу данных получены числа ниже, сказать НЕЧЕМ, и "
                "отнести их к системе нельзя")
    data_dir = observed(inputs, "data_dir", kind=str)
    manifest = observed(inputs, "manifest", kind=str)
    log_dir = observed(inputs, "log_dir", kind=str)
    # Читаемость каталога — ССЫЛКОЙ у тех секций, которые её НАБЛЮДАЛИ. Своё
    # наблюдение здесь было бы наблюдением дерева ЧИТАТЕЛЯ (см. docstring), а
    # второе определение одного имени разошлось бы с первым молча.
    readable = None
    for key in ("declared_producer_reality", "declared_write_attribution",
                "declared_write_stamp_price", "declared_stamp_reader"):
        section = observed(doc, key, kind=dict)
        if section is None:
            continue
        seen = observed(section, "data_dir_readable", kind=bool)
        if seen is not None:
            readable = seen
            break
    state = ("ЧИТАЕМ" if readable is True else
             "НЕ ЧИТАЕТСЯ" if readable is False else
             "читаемость НЕ ИЗМЕРЕНА")
    if data_dir is None:
        return ("  ИЗМЕРЕНО ПО: каталог данных НЕ ИЗМЕРЕН — в `measured_from` "
                f"его нет (конституция {manifest or 'НЕ ИЗМЕРЕНА'}, записи "
                f"прогонов {log_dir or 'НЕ ИЗМЕРЕНЫ'}); «НЕ ИЗМЕРЕНО» ниже "
                "отнести НЕ К ЧЕМУ")
    return (
        f"  ИЗМЕРЕНО ПО: каталог данных {data_dir} ({state}) · конституция "
        f"{manifest or 'НЕ ИЗМЕРЕНА'} · записи прогонов "
        f"{log_dir or 'НЕ ИЗМЕРЕНЫ'} — все числа ниже судят об ЭТОМ каталоге, "
        "а не о системе: при одном и том же коде замер по живому `data/` "
        "прод-дерева и по замороженной git-копии в worktree даёт РАЗНЫЕ числа "
        "(замер #948: «дошла бы 89 · НЕ ИЗМЕРЕНО 14» против «0 · 137»), и "
        "спросить про живой каталог из worktree можно флагом `--data-dir`"
    )


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
    # АДРЕС ЗАМЕРА — строка ЗДЕСЬ и ПЕРВОЙ после заголовка (ADR-824, заказ
    # G824 п. 1). Место выбрано предметом, а не вкусом: строка не добавляет
    # числа, она КВАЛИФИЦИРУЕТ все числа ниже, и прочитанная после них она
    # опоздала бы ровно на тот разбор, который и должна предотвратить.
    lines.append(measured_from_line(doc))
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
    # КАНАЛ АТРИБУЦИИ — строка ЗДЕСЬ, а не только в `findings_bridge` (ADR-820).
    # Причина измерена: четыре строки ADR-816…819 объявлены «строкой шага
    # 0-офис», а печатает их только мост, чей stdout уходит в лог агента;
    # `report()` — вывод, который цикл читает НА САМОМ ДЕЛЕ.
    lines.append(write_attribution_line(doc))
    # ЦЕНА ШТАМПА — строка ЗДЕСЬ по той же измеренной причине (ADR-820): то,
    # что печатает только мост, цикл не читает.
    lines.append(write_stamp_price_line(doc))
    # ЧИТАТЕЛЬ ШТАМПА — строка ЗДЕСЬ по той же измеренной причине (ADR-820).
    lines.append(stamp_reader_line(doc))
    # ЦЕНА СТРОКИ ОТЧЁТА — строка ЗДЕСЬ по той же измеренной причине (ADR-820),
    # и для ЭТОЙ секции причина не просто унаследована: её предмет — судьба
    # строки отчёта в выводе шага 0-офис, и жить ей в выводе, которого цикл не
    # читает, значило бы мерить себя мимо себя.
    lines.append(report_line_line(doc))
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
    # Каталог ДАННЫХ входом CLI (ADR-824). `measure` принимает его с ADR-819,
    # а СПРОСИТЬ извне было нечем: любой прогон из worktree мерил замороженную
    # git-копию `data/` и об этом не говорил ни строкой. Умолчание прежнее —
    # `data/` своего дерева, поэтому поведение живого агента не меняется.
    parser.add_argument("--data-dir", default=None,
                        help="каталог данных (по умолчанию `data/` своего дерева; "
                             "из worktree живой замер требует каталог прод-дерева)")
    parser.add_argument("--window-hours", type=float, default=WINDOW_HOURS)
    parser.add_argument("--out", default=None, help="куда записать артефакт (по умолчанию не писать)")
    parser.add_argument("--json", action="store_true", help="печатать замер как JSON")
    args = parser.parse_args(argv)
    try:
        doc = measure(Path(args.manifest) if args.manifest else None,
                      log_dir=Path(args.log_dir),
                      scripts_dir=Path(args.scripts_dir) if args.scripts_dir else None,
                      data_dir=Path(args.data_dir) if args.data_dir else None,
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
