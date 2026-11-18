"""Артефакта нет на диске — это находка или производитель ещё не отработал?

ОДИН вердикт на ВСЕХ читателей вопроса. До цикла #525 их было два, и они
отвечали по-разному.

## Почему модуль существует (замер 2026-09-08, цикл #525)

ADR-261 (цикл #524, доставлен тремя часами раньше) нашёл верную форму контроля:
«файла нет на диске» есть находка **только после того, как производитель
отработал», а различающий признак обязан быть ОБЪЯВЛЕННЫМ, не выведенным. И
применил её к ОДНОМУ читателю — `scripts/consume_office_reports.py`, тому, на
котором она нашлась.

Соседний читатель того же вопроса — `architecture_conformance.B2` — остался
нетронутым. Замер 10:17Z, живой прогон:

    [WARN] data/cio_substitution_census.json: активный артефакт отсутствует на диске

при полностью исправном контуре: модуль `cio_substitution_census.py` доставлен
циклом #523 (push 07:42Z, синк в прод-дерево 07:51Z), а его бегун
`com.spa.decision_loop` последний раз отработал в **07:03Z** — ДО прихода кода.
Такт бегуна 6 ч, ответ пришёл бы сам. Тот же сторож уже довёл ОДНУ строку этого
класса до КАРТОЧКИ владельцу (`inbox-nahodka-petli-data-cio-outcome-independe`,
`finding_key: B2:missing:data/cio_outcome_independence.json`) — то есть класс не
теоретический, он доезжает до очереди работ.

Это ровно урок цикла #519, повторённый через шесть циклов: **найдя форму
контроля, применять её ко ВСЕМУ классу, для которого она верна, а не к её
поводу.**

## Два дефекта самой формы, найденные при переносе

Перенос — не копирование: он ЗАМЕРИЛ прежнюю реализацию и нашёл в ней две дыры,
обе созданные тем же приёмом «вывести вместо того, чтобы спросить объявление».

**(Б) Имя ступени ВЫВОДИЛОСЬ из имени файла производителя.** `_absent_verdict`
считал ступень как `basename(producer).rsplit('.')[0]`, а мост ОБЪЯВЛЯЕТ её в
`CENSUS_STAGE`. Для `data/evidence_staleness.json` эти два имени РАЗНЫЕ:
объявлено `evidence_staleness`, выведено `evidence_staleness_monitor` (модуль
называется `evidence_staleness_monitor.py`). Ветка «названа бегуном ⇒ находка»
для этого артефакта не срабатывала НИКОГДА, по построению: реально провалившаяся
перепись с записанной причиной проваливалась в ветку дат — и при недавно правленом
модуле объявлялась «ещё не производился», то есть **fail-OPEN**, направление
опаснее ложной находки. То же у `outcomes` (модуль `outcomes_archive.py`).

**(В) Бегун подставлялся ЧУЖОЙ.** Ветки дат сравнивали отчёт МОСТА с датой
модуля для ЛЮБОГО артефакта карты офиса — включая те пять, которых мост не
запускает вовсе (`architecture_conformance.json`, `chief_investment.json`,
`_health.json`, `code_sync_status.json`, `rebalance_trigger.json`). У них свой
агент и свой такт; ответ моста на вопрос «успел ли ТВОЙ бегун» не отвечает.
Замер: из 31 артефакта карты офиса ступенью моста объявлены 25, у восьми
выведенное имя ступени не совпадает с объявленным.

Оба закрыты одним и тем же способом: **спрашивать объявление, а не выводить.**
Артефакт, которого ни одна перепись не объявляет своим продуктом, получает
честное «НЕ ИЗМЕРЕНО» и остаётся находкой — «не смог измерить» не есть «всё
хорошо», и подставлять ему чужого бегуна значило бы отвечать верно не на тот
вопрос.

## Семь исходов

| Состояние | Вердикт |
|---|---|
| перепись НАЗВАНА бегуном в `censuses.attempted`, артефакта нет | **находка** (+ причина из `skipped`) |
| ВЫЗОВА ступени в модуле бегуна НЕТ (доказано разбором) | **находка**: форма ADR-259; такта ждать бессмысленно |
| не названа, отчёт бегуна СТАРШЕ кода, а бегун запускался В ПРЕДЕЛАХ горизонта артефакта | ⏳ **ЕЩЁ НЕ ПРОИЗВОДИЛСЯ** — не находка |
| то же, но сам БЕГУН молчит дольше объявленного горизонта | **находка** (ADR-1053): отсрочка держится молчанием бегуна и вечна |
| то же, а горизонт артефакта НЕ ОБЪЯВЛЕН | **находка**, `НЕ ИЗМЕРЕНО`: ограничить отсрочку нечем |
| вызов ЕСТЬ, бегун стартовал ПОЗЖЕ и ступень не назвал | **находка**: вызов есть, исполнения нет |
| не названа, отчёт бегуна МОЛОЖЕ, форма вызова не разобрана | **находка** (форма ADR-259 не исключена и не доказана) |
| артефакт не объявлен НИ ОДНОЙ переписью | **находка**, `НЕ ИЗМЕРЕНО`: своего бегуна спросить нечем |
| спросить нечем (нет модуля, отчёт нечитаем, у отчёта нет часов) | **находка**, `НЕ ИЗМЕРЕНО` |

## Поправка ADR-812 (цикл #935): мера прихода стояла на СОСЕДНЕМ файле

Артефакт появляется, когда в дереве лежат ДВА файла: модуль переписи и
**вызов** ступени — а вызов живёт в модуле БЕГУНА. Моментом прихода бралась
дата только первого, и пока доставка правит оба (так было у ADR-811), даты
совпадают и подмена невидима. Как только доставка правит ТОЛЬКО вызывающего —
а это ровно канонический случай ADR-259 — мера встаёт на файл, который не
менялся, и исправная проводка, ждущая такта, объявляется находкой.

У подмены есть и обратная, более тихая сторона: ступень, которую не зовёт
никто, но чей модуль недавно правили, получала «⏳ ещё не производился», то
есть **fail-OPEN** на том самом дефекте, против которого написан ADR-259.
Свежая дата файла прятала отсутствие вызова.

Закрыто одним приёмом: «есть ли вызов» теперь **доказывается разбором кода**
(`_call_state`, AST), а не выводится из дат — и только поэтому дату несущего
файла стало можно брать в меру прихода, не заглушая находку.

## Поправка ADR-1053 (цикл #1191): «не вечен» было УТВЕРЖДЕНИЕМ, и оно неверно

Здесь стояло: «Третий исход **не вечен**: он закрывается следующим прогоном
бегуна САМ… Это не `UNCHECKED`, который никогда не станет `CHECKED`». Фраза
верна про МЕХАНИЗМ закрытия и неверна про его ДОСТИЖИМОСТЬ: закрыть отсрочку
может только прогон бегуна, а будет ли он — вердикт не спрашивал НИ РАЗУ.

Хуже: условие отсрочки (`ran < born`) выполняется тем **вернее**, чем дольше
бегун не запускается. То есть молчание бегуна само продлевает собственное
оправдание — fail-OPEN, и тише красной строки, потому что печатается словами
«это НЕ находка».

Замер 18.11 на живом дереве: бегун ступеней моста (`com.spa.decision_loop`,
во флоте **НЕ загружен**) молчал **481.2 ч** при объявленном горизонте
артефакта **192 ч** — просрочен в 2.5 раза, — и шаг 0-офис печатал про
`data/acceptance_tree_lineage.json`: «⏳ ЕЩЁ НЕ ПРОИЗВОДИЛСЯ (это НЕ находка)…
Ответ будет на следующем прогоне бегуна». Прогона, которого некому сделать.

**Цена названа, а не предположена.** Этот артефакт и есть вердикт о дереве-
приёмке §49 (решение владельца ADR-509, вариант 1). Пока офис печатал «не
находка», дерево отстало от `origin/main` на **790 коммитов**, и среди них
изменились НОСИТЕЛИ мерки §49 (`scripts/cio_acceptance_rollup.py`,
`spa_core/monitoring/card_acceptance.py`): любой §49-вердикт, снятый в том
дереве, снят ПРОШЛОЙ меркой. Ни одному циклу об этом не сказали 34 дня.

Поэтому отсрочка теперь ОГРАНИЧЕНА, и предел не выбран здесь, а **прочитан**:
`slo_hours` того же артефакта (`architecture/manifest.json`) — та же строка, по
которой офис судит возраст уже СУЩЕСТВУЮЩЕГО файла. Горизонта нет ⇒ третий
исход (`UNMEASURED_NO_HORIZON`), а не молчание: «позже» без срока
неопровержимо. Население этой двери на 18.11 — **НОЛЬ** (все 121 артефакт
ступеней несут `slo_hours`), то есть она заперта на будущее, а не красит
сегодняшнее дерево.

**Чего это НЕ закрывает.** Загруженность службы вердикт не спрашивает — он
меряет МОЛЧАНИЕ, а не его причину, и причин у молчания две (служба не
загружена · загружена и висит). Различать их — следующий вопрос, и у него свой
прибор (`agent_health`). Горизонт артефакта не есть такт бегуна: бегун с
тактом 24 ч и артефакт с горизонтом 192 ч оправданы восемью пропущенными
тактами, и это осознанно — мерка взята ОБЪЯВЛЕННАЯ, а не выдуманная под
вопрос.

**ADR-1054 (цикл #1193): «горизонта нет» — это ПЯТЬ состояний, не одно.**
Первая редакция двери возвращала `None` на все пять и утверждала в своей шапке,
что различать их читателю не нужно. Цена утверждения ИЗМЕРЕНА в тот же день:
батарея `test_office_absent_artifact_producer_aware` строит сцену БЕЗ реестра
артефактов, вердикт сказал ей «`architecture/manifest.json`: нет `slo_hours`»,
и ДВА имени упали с причиной, которая причиной не была — реестра в сцене не
было ни одного байта. В бою это направление опаснее: читателю, у которого
пропал манифест, сторож советует вписать строку в пропавший файл. Теперь
состояние объявлено ЗНАЧЕНИЕМ (`Absence.horizon_state`) и у каждого свой
следующий шаг. Это тот же инв. #17, но на ступень ниже: три исхода ВЕРДИКТА
были различимы, а три состояния его ВХОДА — нет.

Время — ВХОД (`.claude/rules/deployment.md`): `now` принимается параметром,
собственных стенных часов у вердикта нет. Объявление переписи тоже вход
(`products=`), чтобы сцена могла нарушать ТОЛЬКО своё ограничение.

Только stdlib. LLM здесь запрещён (инвариант #3): это monitoring.
"""
from __future__ import annotations

import ast
import datetime as dt
import json
import os
from dataclasses import dataclass

#: Отчёт бегуна переписей. Его пишет `com.spa.decision_loop`
#: (`spa_core/monitoring/findings_bridge.py::main`), и только он знает, какие
#: переписи ступень действительно пробовала.
RUNNER_REPORT_REL = "data/findings_bridge_report.json"

#: Слово, которым в этом проекте называется третий исход. Совпадает с
#: `consume_office_reports._UNMEASURED` намеренно: читатель отчётов один.
UNMEASURED = "НЕ ИЗМЕРЕНО"

#: Исходы. `is_finding` у всех, кроме `NOT_YET`.
ATTEMPTED_AND_ABSENT = "attempted_and_absent"
DECLARED_WITHOUT_CALL = "declared_without_call"
NOT_YET = "not_yet_produced"
UNMEASURED_NOT_DECLARED = "unmeasured_not_declared"
UNMEASURED_MODULE_ABSENT = "unmeasured_module_absent"
UNMEASURED_REPORT_UNREADABLE = "unmeasured_report_unreadable"
UNMEASURED_REPORT_HAS_NO_CLOCK = "unmeasured_report_has_no_clock"
#: Вызов ступени в модуле бегуна ЕСТЬ, бегун стартовал ПОСЛЕ его прихода и
#: ступень всё равно не назвал. До ADR-812 этот исход был неотличим от
#: `DECLARED_WITHOUT_CALL`, хотя утверждения разные: «вызова нет» и «вызов есть,
#: а назван не был» требуют разного следующего шага.
CALL_PRESENT_NOT_ATTEMPTED = "call_present_not_attempted"

#: Отсрочка `NOT_YET` опирается на БУДУЩИЙ прогон бегуна — а бегун сам просрочен
#: по горизонту, объявленному для ЭТОГО артефакта. Тогда «ответ будет на
#: следующем прогоне» не отсрочка, а вечное молчание: условие `ran < born`
#: выполняется тем вернее, чем дольше бегун не запускается (ADR-1053).
DEFERRAL_OUTLIVED_THE_RUNNER = "deferral_outlived_the_runner"
#: Горизонт отсрочки НЕ ОБЪЯВЛЕН: ограничить её нечем, и «позже» становится
#: неопровержимым. Третий исход, а не молчание (инв. #17); население на 18.11
#: равно НУЛЮ (все 121 артефакт ступеней несут `slo_hours`), то есть дверь
#: заперта на будущее, а не красит сегодняшнее дерево.
UNMEASURED_NO_HORIZON = "unmeasured_no_horizon"

#: ПОЧЕМУ горизонта нет — РАЗНЫЕ состояния с РАЗНЫМ следующим шагом (ADR-1054).
#: До него `declared_horizon_hours` склеивал их все в `None`, а печаталась ОДНА
#: причина — «`architecture/manifest.json`: нет `slo_hours`», — и читателя
#: отправляли искать строку в файле, которого в дереве могло не быть ВОВСЕ.
#: Замер 18.11 (цикл #1193): в сцене батареи
#: `test_office_absent_artifact_producer_aware` реестра не было ни одного
#: байта, вердикт объявил «нет `slo_hours`», и ДВА имени упали с причиной,
#: которая причиной не была. Это тот же инв. #17, но на ступень ниже: три
#: исхода вердикта были различимы, а три состояния ВХОДА — нет.
HORIZON_DECLARED = "declared"
HORIZON_NO_REGISTRY = "registry_absent"
HORIZON_REGISTRY_UNREADABLE = "registry_unreadable"
HORIZON_ARTIFACT_NOT_IN_REGISTRY = "artifact_not_in_registry"
HORIZON_NO_SLO_HOURS = "entry_without_slo_hours"
HORIZON_BAD_VALUE = "slo_hours_not_a_positive_number"
#: Горизонт выдаёт ВЫЗЫВАЮЩИЙ (`horizon_of=`) и выдал `None`. Спрашивать о нём
#: реестр нельзя: вызывающий мог и не читать его. Отдельное состояние, потому
#: что следующий шаг здесь — к ВЫЗЫВАЮЩЕМУ, а не к манифесту.
HORIZON_NOT_GIVEN_BY_CALLER = "not_given_by_horizon_of"

#: Модуль БЕГУНА — файл, который НЕСЁТ вызовы ступеней. Отдельная константа, а
#: не выведенный путь: вопрос «приехал ли ВЫЗОВ» задаётся именно этому файлу.
RUNNER_MODULE_REL = os.path.join("spa_core", "monitoring", "findings_bridge.py")

#: Состояния вызова. Четыре, и три последних НЕ равны друг другу (инв. #17):
#: «вызова нет» доказано разбором · «форма вызова не разобрана» · «спросить
#: нечем». Подставить первое вместо двух других значило бы выдать неразобранное
#: за опровергнутое.
CALL_PRESENT = "call_present"
CALL_ABSENT = "call_absent"
CALL_FORM_UNPARSED = "call_form_unparsed"
CALL_UNMEASURED = "call_unmeasured"


@dataclass(frozen=True)
class Absence:
    """Почему артефакта нет — и обязывает ли это действовать.

    `is_finding=False` ровно у одного исхода (`NOT_YET`). Все остальные —
    находки, включая все три «не измерено»: сторож, который молчит там, где
    не смог измерить, вреднее отсутствующего сторожа.
    """

    artifact: str
    kind: str
    is_finding: bool
    reason: str
    stage: str | None = None
    module: str | None = None
    module_age_h: float | None = None
    runner_ran_at: str | None = None
    skip_reason: str | None = None
    #: ЧЕМ мерили «успел ли бегун увидеть производителя»: `run_started_at`
    #: (старт процесса — верный момент) либо `generated_at` (последняя фаза
    #: прогона — приближение, завышающее «успел»). Поле объявлено, а не
    #: выведено из текста: читатель вправе знать, на чём стоит вердикт.
    clock_field: str | None = None
    #: Состояние ВЫЗОВА ступени, РАЗОБРАННОЕ в модуле бегуна (см. `_call_state`).
    #: Объявлено, а не выведено из `reason`: на нём стоит выбор ветки, и
    #: читатель вправе знать, доказан вызов или только не опровергнут.
    call_state: str | None = None
    #: Файл, НЕСУЩИЙ вызов (когда он известен). Момент прихода производящей
    #: способности берётся по ПОЗДНЕЙШЕМУ из двух файлов, а не по одному.
    carrier: str | None = None
    #: Горизонт отсрочки в часах — ОБЪЯВЛЕННЫЙ (`slo_hours` артефакта), а не
    #: выбранный здесь. `None` значит «не объявлен», и это отдельный исход.
    horizon_h: float | None = None
    #: Сколько часов назад бегун запускался в последний раз. Отсрочка законна
    #: только пока это число не больше горизонта.
    runner_age_h: float | None = None
    #: ПОЧЕМУ горизонт такой, какой он есть, — ЗНАЧЕНИЕМ, а не прозой `reason`
    #: (ADR-1054). У `None`-горизонта пять разных причин и пять разных
    #: следующих шагов; читатель, которому дали одну, идёт не туда.
    horizon_state: str | None = None

    @property
    def not_yet(self) -> bool:
        return self.kind == NOT_YET


def _products(products):
    """Объявление переписи. По умолчанию — то, что объявил САМ мост.

    Импорт ленивый: `findings_bridge` тянет тяжёлую родню, а вердикт зовут из
    сторожа, который обязан отвечать дёшево. Заодно снимается кольцо импортов
    (`findings_bridge` → `architecture_conformance` → сюда).
    """
    if products is not None:
        return products
    from spa_core.monitoring.findings_bridge import CENSUS_PRODUCT
    return CENSUS_PRODUCT


#: Реестр, в котором объявлен горизонт артефакта. Одно место, а не литерал
#: здесь: срок решает ОБЪЯВЛЕНИЕ, и вторая копия разошлась бы с ним молча.
MANIFEST_REL = "architecture/manifest.json"


@dataclass(frozen=True)
class Horizon:
    """Горизонт отсрочки и — ОТДЕЛЬНО — почему он такой.

    `hours is None` значит «ограничить отсрочку нечем», и у этого ответа ПЯТЬ
    разных оснований (ADR-1054). Прежняя редакция склеивала их в `None` и
    утверждала в своей же шапке, что «отличить их друг от друга читателю не
    нужно — следующий шаг у всех трёх один: объявить горизонт». Утверждение
    ОПРОВЕРГНУТО замером 18.11: у состояния «реестра нет ВОВСЕ» следующий шаг
    не «объявить строку», а «положить реестр» (в бою — тревога о пропавшем
    манифесте, в сцене — выложить его), и названная не та причина отправляет
    читателя править файл, которого нет.
    """

    hours: float | None
    state: str
    #: Что именно измерено — словами, для строки отчёта.
    detail: str
    #: Следующий шаг ЧИТАТЕЛЯ. У каждого состояния свой, и это весь смысл.
    next_step: str

    @property
    def declared(self) -> bool:
        return self.hours is not None


def declared_horizon(artifact_rel: str, *, root: str) -> Horizon:
    """Объявленный горизонт артефакта И состояние его объявления.

    Читается `slo_hours` из реестра артефактов манифеста. Число НЕ выбирается
    этим модулем ни для одного артефакта: вопрос «как долго отсрочка остаётся
    отсрочкой» решает та же строка, по которой офис судит ВОЗРАСТ уже
    существующего файла. Разойдись они — один и тот же артефакт считался бы
    просроченным по одной мерке и свежим по другой.

    Пять состояний «не объявлен» различимы ЗНАЧЕНИЕМ (инв. #17): реестра нет ·
    реестр нечитаем · артефакта в реестре нет · строка есть, а срока в ней нет ·
    срок есть, но это не положительное число. Склеивать их с ОБЪЯВЛЕННЫМ
    горизонтом по-прежнему нельзя — находкой остаются все пять.
    """
    path = os.path.join(root, MANIFEST_REL)
    if not os.path.exists(path):
        return Horizon(
            hours=None, state=HORIZON_NO_REGISTRY,
            detail=(f"реестра артефактов {MANIFEST_REL} в дереве НЕТ — "
                    f"спросить срок не у кого"),
            next_step=(f"положить {MANIFEST_REL} в дерево, о котором задан "
                       f"вопрос: в бою это тревога о пропавшем реестре, в "
                       f"сцене — незаложенная предпосылка сцены"))
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except Exception as exc:                                  # noqa: BLE001
        return Horizon(
            hours=None, state=HORIZON_REGISTRY_UNREADABLE,
            detail=f"реестр {MANIFEST_REL} не читается: {type(exc).__name__}",
            next_step=f"починить {MANIFEST_REL} — разбор падает, срока в нём "
                      f"не видно ни у одного артефакта")
    for item in (doc.get("artifacts") or []):
        if not isinstance(item, dict) or item.get("path") != artifact_rel:
            continue
        if "slo_hours" not in item:
            return Horizon(
                hours=None, state=HORIZON_NO_SLO_HOURS,
                detail=(f"строка артефакта в {MANIFEST_REL} есть, а поля "
                        f"`slo_hours` в ней нет"),
                next_step=f"объявить `slo_hours` этого артефакта в "
                          f"{MANIFEST_REL}")
        value = item.get("slo_hours")
        bad = (isinstance(value, bool)
               or not isinstance(value, (int, float))
               or value <= 0)
        if bad:
            return Horizon(
                hours=None, state=HORIZON_BAD_VALUE,
                detail=(f"`slo_hours` артефакта в {MANIFEST_REL} равно "
                        f"{value!r} — это не положительное число часов"),
                next_step=f"исправить значение `slo_hours` в {MANIFEST_REL}: "
                          f"срока {value!r} не бывает")
        return Horizon(hours=float(value), state=HORIZON_DECLARED,
                       detail=f"объявлено {float(value):.4g}ч",
                       next_step="")
    return Horizon(
        hours=None, state=HORIZON_ARTIFACT_NOT_IN_REGISTRY,
        detail=f"артефакта нет в реестре {MANIFEST_REL} ни одной строкой",
        next_step=f"внести артефакт в {MANIFEST_REL} вместе с его `slo_hours`")


def declared_horizon_hours(artifact_rel: str, *, root: str) -> float | None:
    """Только часы — тонкая дверь над `declared_horizon` (ADR-1054).

    Оставлена байт в байт по ПОВЕДЕНИЮ: `None` у всех пяти состояний. Своего
    разбора у неё нет ни строки — вторая копия разошлась бы с первой молча.
    """
    return declared_horizon(artifact_rel, root=root).hours


def _resolve(rel: str, *, root: str, data_dir: str | None) -> str:
    """Куда смотреть за `rel` — та же семантика, что у шага 0-офис."""
    if data_dir and rel.startswith("data/"):
        return os.path.join(os.path.dirname(data_dir), rel)
    return os.path.join(root, rel)


def _parse_ts(value) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=dt.timezone.utc)


def _stage_of(artifact_rel: str, products: dict) -> tuple[str | None, dict]:
    """Ступень, ОБЪЯВИВШАЯ этот артефакт своим продуктом.

    Именно объявление, а не совпадение имён: дефект (Б) в шапке модуля — это
    ровно попытка вывести ступень из имени файла производителя.
    """
    want = artifact_rel.replace("\\", "/")
    for stage, spec in products.items():
        if str(spec.get("artifact", "")).replace("\\", "/") == want:
            return stage, spec
    return None, {}


@dataclass(frozen=True)
class Call:
    """Приехал ли ВЫЗОВ ступени — и чем это измерено."""

    state: str
    reason: str
    carrier: str | None = None
    carrier_mtime: dt.datetime | None = None


def _imported_module_names(scope) -> set:
    """Имена модулей, ввезённые ВНУТРИ `scope`.

    У `ImportFrom` берётся и сам модуль (`node.module`), и ввезённые имена:
    ступень `outcomes` зовут как `from ...outcomes_archive import
    append_daily_outcome`, и читать только `names` значило бы не увидеть
    модуль, а только символ.
    """
    out: set = set()
    for n in ast.walk(scope):
        if isinstance(n, ast.ImportFrom):
            if n.module:
                out.add(n.module.rsplit(".", 1)[-1])
            out.update(a.name for a in n.names)
        elif isinstance(n, ast.Import):
            out.update(a.name.rsplit(".", 1)[-1] for a in n.names)
    return out


def _call_state(stage: str, spec: dict, *, root: str,
                runner_module_rel: str = RUNNER_MODULE_REL) -> Call:
    """Есть ли в модуле бегуна ВЫЗОВ этой ступени — разбором кода, не датами.

    ЗАЧЕМ (замер цикла #935, ADR-812). Вердикт выше брал моментом прихода
    производящего кода дату ОДНОГО файла — модуля переписи. Но артефакт
    появляется, когда в дереве есть И модуль, И **вызов** ступени, а вызов
    живёт в ДРУГОМ файле — в модуле бегуна. Пока оба файла правятся одной
    доставкой, даты совпадают и подмена не видна; как только доставка правит
    ТОЛЬКО вызывающего (а это ровно канонический случай ADR-259 — «объявленный
    артефакт без производящего вызова»), мера встаёт на файл, который не
    менялся: `ran >= born`, и исправная проводка, ждущая такта, объявляется
    находкой.

    Хуже того, у подмены есть и ОБРАТНАЯ сторона, и она тише: ступень,
    которую не зовёт никто, но чей модуль недавно правили, получала «⏳ ещё не
    производился» — то есть **fail-OPEN** ровно на том дефекте, против
    которого ADR-259 и написан. Свежая дата файла прятала отсутствие вызова.

    Разбор закрывает обе стороны: «вызова нет» теперь ДОКАЗЫВАЕТСЯ кодом, а не
    выводится из дат, и потому дата вызывающего файла может быть взята в меру
    прихода без риска заглушить находку.

    Имя модуля берётся у ОБЪЯВЛЕНИЯ (`spec["module"]`), а не у имени ступени —
    дефект (Б) в шапке модуля ровно про это.

    Четыре исхода, и три последних не слиты в один (инв. #17):

    * `CALL_PRESENT` — модуль ступени ввезён внутри `main()` бегуна;
    * `CALL_ABSENT` — упоминания производителя в модуле бегуна нет вовсе;
    * `CALL_FORM_UNPARSED` — упоминание есть, а форма не разобрана (так
      устроена ступень `no_regression_producer`: её производитель — СКРИПТ,
      запускаемый подпроцессом из функции-помощника, а не импорт в `main()`).
      Назвать это «вызова нет» значило бы выдумать находку;
    * `CALL_UNMEASURED` — исходник бегуна не прочитан / не разобран / в нём нет
      `main()`. Молчать нельзя, но и судить нечем.
    """
    module = str(spec.get("module") or "")
    if not module:
        return Call(CALL_UNMEASURED, "у ступени не объявлен модуль-производитель")
    runner_full = os.path.join(root, runner_module_rel)
    try:
        with open(runner_full, encoding="utf-8") as fh:
            src = fh.read()
        tree = ast.parse(src)
    except Exception as e:  # noqa: BLE001 — любой отказ = «не измерено»
        return Call(CALL_UNMEASURED,
                    f"модуль бегуна {runner_module_rel} не разобран "
                    f"({type(e).__name__})")
    main_fn = next((n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    if main_fn is None:
        return Call(CALL_UNMEASURED,
                    f"в {runner_module_rel} нет функции main() — спросить "
                    f"«зовёт ли она ступень» нечем")
    mtime = dt.datetime.fromtimestamp(os.path.getmtime(runner_full),
                                      dt.timezone.utc)
    modname = os.path.basename(module).removesuffix(".py")
    if modname in _imported_module_names(main_fn):
        return Call(CALL_PRESENT,
                    f"модуль {modname} ввезён внутри main() бегуна",
                    runner_module_rel, mtime)
    if modname in _imported_module_names(tree) or os.path.basename(module) in src:
        return Call(CALL_FORM_UNPARSED,
                    f"производитель {module} в модуле бегуна упомянут, но "
                    f"форма вызова не разобрана (не импорт внутри main()) — "
                    f"это НЕ «вызова нет»",
                    runner_module_rel, mtime)
    return Call(CALL_ABSENT,
                f"в {runner_module_rel} нет ни импорта {modname}, ни упоминания "
                f"{os.path.basename(module)} — вызова ступени {stage!r} нет",
                runner_module_rel, mtime)


def verdict(artifact_rel: str, *, root: str, now: dt.datetime,
            data_dir: str | None = None,
            products: dict | None = None,
            runner_report_rel: str = RUNNER_REPORT_REL,
            runner_module_rel: str = RUNNER_MODULE_REL,
            call_of=None, horizon_of=None) -> Absence:
    """Вердикт об отсутствующем артефакте. Семь исходов, см. шапку модуля.

    `now` — вход, а не окружение. `products` — вход затем, чтобы сцена
    нарушала ТОЛЬКО своё ограничение (иначе тест про «не объявлен» пришлось бы
    ставить на живой состав переписи и он краснел бы от чужой правки). `call_of`
    — та же дверь для пробы ВЫЗОВА (ADR-812): сцена вправе объявить состояние
    вызова, не раскладывая у себя исходник бегуна на 4000 строк. `horizon_of`
    — дверь ОБЪЯВЛЕННОГО горизонта отсрочки (ADR-1053): сцена объявляет предел
    сама, не выкладывая у себя реестр артефактов; `None` у двери и `None` из
    неё — разные вещи (дверь не задана ⇒ спрашивается реестр; дверь ответила
    `None` ⇒ горизонт НЕ ОБЪЯВЛЕН, и это исход).
    """
    products = _products(products)
    stage, spec = _stage_of(artifact_rel, products)

    if stage is None:
        # Дефект (В): подставить сюда отчёт МОСТА значило бы спросить чужого
        # бегуна. Свой — неизвестен, и это говорится вслух.
        return Absence(
            artifact=artifact_rel, kind=UNMEASURED_NOT_DECLARED, is_finding=True,
            reason=(f"артефакт не объявлен продуктом ни одной переписи бегуна "
                    f"⇒ «отработал ли ЕГО производитель» {UNMEASURED}; "
                    f"подставлять сюда чужого бегуна нельзя"))

    module = spec.get("module")
    module_full = _resolve(module, root=root, data_dir=None) if module else None
    if not module_full or not os.path.exists(module_full):
        return Absence(
            artifact=artifact_rel, kind=UNMEASURED_MODULE_ABSENT, is_finding=True,
            stage=stage, module=module,
            reason=(f"и производителя {module} в этом дереве тоже нет — "
                    f"артефакт объявлен, а писать его нечем"))

    runner_full = _resolve(runner_report_rel, root=root, data_dir=data_dir)
    try:
        with open(runner_full, encoding="utf-8") as fh:
            report = json.load(fh)
    except Exception as e:  # noqa: BLE001 — любой отказ чтения = «не измерено»
        return Absence(
            artifact=artifact_rel, kind=UNMEASURED_REPORT_UNREADABLE,
            is_finding=True, stage=stage, module=module,
            reason=(f"отчёт бегуна не прочитан ({type(e).__name__}) ⇒ «пробовал "
                    f"ли он» {UNMEASURED}; строка остаётся находкой, а не тишиной"))

    # Приехал ли ВЫЗОВ (ADR-812). Спрашивается ДО дат, потому что ответ решает,
    # на какой файл вообще ставить меру прихода производящего кода.
    call = (call_of(stage, spec) if call_of is not None
            else _call_state(stage, spec, root=root,
                             runner_module_rel=runner_module_rel))

    censuses = report.get("censuses") or {}
    attempted = set(censuses.get("attempted") or [])
    skipped = censuses.get("skipped") or {}
    if stage in attempted:
        why = skipped.get(stage)
        return Absence(
            artifact=artifact_rel, kind=ATTEMPTED_AND_ABSENT, is_finding=True,
            stage=stage, module=module, skip_reason=why,
            runner_ran_at=report.get("generated_at"),
            reason=(f"производитель {module} назван в составе ступени бегуна "
                    f"({os.path.basename(runner_report_rel)})"))

    # Вызова НЕТ — и это ДОКАЗАНО разбором кода, а не выведено из дат. Даты
    # здесь не спрашиваются вовсе: при отсутствующем вызове ни один такт бегуна
    # артефакта не произведёт, сколько бы их ни прошло. До ADR-812 этот случай
    # при недавно правленом модуле переписи уходил в «⏳ ещё не производился»,
    # то есть fail-OPEN на дефекте ADR-259.
    if call.state == CALL_ABSENT:
        return Absence(
            artifact=artifact_rel, kind=DECLARED_WITHOUT_CALL, is_finding=True,
            stage=stage, module=module, call_state=call.state,
            carrier=call.carrier,
            reason=(f"объявленный артефакт без производящего вызова (форма "
                    f"ADR-259), ДОКАЗАНО разбором кода: {call.reason}; "
                    f"такта ждать бессмысленно"))

    # ЧТО именно спрашивается: «был ли код производителя в дереве РАНЬШЕ, чем
    # процесс бегуна зафиксировал свой код», то есть раньше его СТАРТА. Мост —
    # последняя фаза прогона, и `generated_at` отстоит от старта на часы (замер
    # 02.10: старт 04:46:42Z, `generated_at` 08:10:17Z — 3 ч 24 мин). Поэтому
    # приоритет у `run_started_at`, а `generated_at` остаётся ПРИБЛИЖЕНИЕМ, и
    # сторона его ошибки названа: он завышает «успел увидеть», то есть ошибается
    # в сторону ЛОЖНОЙ НАХОДКИ на исправной проводке (ADR-536, цикл #750).
    started = _parse_ts(report.get("run_started_at"))
    clock_field = "run_started_at" if started is not None else "generated_at"
    ran = started if started is not None else _parse_ts(report.get("generated_at"))
    if ran is None:
        return Absence(
            artifact=artifact_rel, kind=UNMEASURED_REPORT_HAS_NO_CLOCK,
            is_finding=True, stage=stage, module=module,
            reason=(f"у отчёта бегуна нет собственного времени ⇒ «успел ли он "
                    f"увидеть {module}» {UNMEASURED}; строка остаётся находкой"))

    # Момент прихода ПРОИЗВОДЯЩЕЙ СПОСОБНОСТИ — по ПОЗДНЕЙШЕМУ из двух файлов:
    # модуля переписи и файла, несущего её вызов (ADR-812). Артефакт появляется
    # только когда в дереве лежат ОБА, и брать дату одного значило бы судить о
    # приходе пары по одному её члену. Заглушить находку ADR-259 это не может:
    # «вызова нет» отвечено выше РАЗБОРОМ и до всяких дат.
    born = dt.datetime.fromtimestamp(os.path.getmtime(module_full),
                                     dt.timezone.utc)
    carrier_rel = None
    if call.carrier_mtime is not None and call.carrier_mtime > born:
        born, carrier_rel = call.carrier_mtime, call.carrier
    if ran < born:
        later = (f"несущий вызов {carrier_rel}" if carrier_rel
                 else f"производитель {module}")
        born_age_h = round((now - born).total_seconds() / 3600.0, 2)
        # ПЕРЕД тем как отсрочить — спросить, БУДЕТ ли ещё прогон (ADR-1053).
        # Условие `ran < born` выполняется тем вернее, чем дольше бегун не
        # запускается, поэтому отсрочка, опирающаяся на молчащего бегуна, сама
        # себя продлевает вечно. Замер 18.11 (цикл #1191): бегун ступеней моста
        # (`com.spa.decision_loop`, во флоте НЕ загружен) молчал 481.2 ч при
        # объявленном горизонте артефакта 192 ч, и шаг 0-офис печатал
        # «это НЕ находка · ответ будет на следующем прогоне бегуна» — прогона,
        # которого некому сделать. Цена названа: дерево-приёмка §49 (решение
        # владельца ADR-509) отстало на 790 коммитов, и среди них изменились
        # НОСИТЕЛИ мерки §49, а ни одному циклу об этом не сказали.
        # Горизонт приходит СО СВОИМ состоянием (ADR-1054): «не объявлен» это
        # пять разных состояний с пятью разными следующими шагами, и назвать
        # не то отправляет читателя править файл, которого нет.
        if horizon_of is not None:
            given = horizon_of(artifact_rel)
            hz = (Horizon(hours=given, state=HORIZON_DECLARED,
                          detail=f"выдано вызывающим: {float(given):.4g}ч",
                          next_step="")
                  if given is not None else
                  Horizon(hours=None, state=HORIZON_NOT_GIVEN_BY_CALLER,
                          detail="горизонт выдаёт вызывающий (`horizon_of=`), "
                                 "и он ответил «не объявлен»",
                          next_step="спросить ВЫЗЫВАЮЩЕГО: реестр здесь не "
                                    "опрашивался вовсе, и утверждать о нём "
                                    "нечего"))
        else:
            hz = declared_horizon(artifact_rel, root=root)
        horizon = hz.hours
        runner_age_h = round((now - ran).total_seconds() / 3600.0, 2)
        if horizon is None:
            return Absence(
                artifact=artifact_rel, kind=UNMEASURED_NO_HORIZON,
                is_finding=True, stage=stage, module=module,
                clock_field=clock_field, call_state=call.state,
                carrier=call.carrier, module_age_h=born_age_h,
                runner_age_h=runner_age_h, horizon_state=hz.state,
                runner_ran_at=report.get(clock_field),
                reason=(f"{later} приехал ПОСЛЕ последнего прогона бегуна, а "
                        f"горизонт отсрочки для {artifact_rel} НЕ ОБЪЯВЛЕН "
                        f"({hz.detail}) ⇒ «ответ будет позже» опровергнуть "
                        f"нечем, и это {UNMEASURED}, а не отсрочка. "
                        f"Следующий шаг: {hz.next_step}"))
        if runner_age_h > horizon:
            return Absence(
                artifact=artifact_rel, kind=DEFERRAL_OUTLIVED_THE_RUNNER,
                is_finding=True, stage=stage, module=module,
                clock_field=clock_field, call_state=call.state,
                carrier=call.carrier, module_age_h=born_age_h,
                horizon_h=horizon, runner_age_h=runner_age_h,
                horizon_state=hz.state,
                runner_ran_at=report.get(clock_field),
                reason=(f"{later} приехал ПОСЛЕ последнего прогона бегуна, НО "
                        f"сам бегун молчит {runner_age_h:.1f}ч при объявленном "
                        f"горизонте {artifact_rel} {horizon:.4g}ч — отсрочка "
                        f"опирается на прогон, который просрочен в "
                        f"{runner_age_h / horizon:.1f} раз(а); «ответ будет на "
                        f"следующем прогоне» здесь неопровержимо, потому что "
                        f"условие отсрочки держится САМИМ молчанием бегуна"))
        return Absence(
            artifact=artifact_rel, kind=NOT_YET, is_finding=False,
            stage=stage, module=module, clock_field=clock_field,
            call_state=call.state, carrier=call.carrier,
            module_age_h=born_age_h, horizon_state=hz.state,
            horizon_h=horizon, runner_age_h=runner_age_h,
            runner_ran_at=report.get(clock_field),
            reason=(f"{later} приехал в дерево ПОСЛЕ последнего "
                    f"прогона своего бегуна"))

    # Вызов ЕСТЬ, бегун работал после прихода обоих файлов и ступень не назвал.
    # Это НЕ «вызова нет» (ADR-812): следующий шаг другой — искать, почему
    # объявленный и ПРИСУТСТВУЮЩИЙ вызов не исполнился, а не вписывать
    # отсутствующий. Ветка стои́т ВЫШЕ соседней: при `call_present` форма
    # ADR-259 ИСКЛЮЧЕНА разбором, и говорить про неё «не исключена» было бы
    # утверждением лишнего — тем самым, против которого соседний абзац написан.
    if call.state == CALL_PRESENT:
        if clock_field == "generated_at":
            return Absence(
                artifact=artifact_rel, kind=CALL_PRESENT_NOT_ATTEMPTED,
                is_finding=True, stage=stage, module=module,
                clock_field=clock_field, call_state=call.state,
                carrier=call.carrier,
                runner_ran_at=report.get("generated_at"),
                reason=(f"вызов ступени {stage!r} в дереве ЕСТЬ "
                        f"({call.reason}) и назван бегуном не был, но СТАРТ "
                        f"его процесса — {UNMEASURED} (в отчёте нет "
                        f"`run_started_at`): вердикт стои́т на `generated_at` "
                        f"({report.get('generated_at')}), то есть на НАЧАЛЕ "
                        f"ПОСЛЕДНЕЙ ФАЗЫ прогона, а код мог приехать внутрь "
                        f"уже идущего прогона"))
        return Absence(
            artifact=artifact_rel, kind=CALL_PRESENT_NOT_ATTEMPTED,
            is_finding=True, stage=stage, module=module,
            clock_field=clock_field, call_state=call.state,
            carrier=call.carrier, runner_ran_at=report.get("run_started_at"),
            reason=(f"вызов ступени {stage!r} в дереве ЕСТЬ ({call.reason}), "
                    f"процесс бегуна СТАРТОВАЛ ПОСЛЕ прихода и производителя, "
                    f"и несущего вызов ({report.get('run_started_at')}), а "
                    f"ступень не назвал — вызов есть, исполнения нет"))

    # Та же находка, но причина больше не утверждает лишнего: по
    # `generated_at` нельзя сказать «бегун стартовал после прихода кода» —
    # можно лишь «мост начался после». Разница и есть ложная находка 02.10.
    if clock_field == "generated_at":
        return Absence(
            artifact=artifact_rel, kind=DECLARED_WITHOUT_CALL, is_finding=True,
            stage=stage, module=module, clock_field=clock_field,
            call_state=call.state, carrier=call.carrier,
            runner_ran_at=report.get("generated_at"),
            reason=(f"производитель {module} в дереве есть, ступень {stage!r} "
                    f"бегун не назвал, а СТАРТ его процесса — {UNMEASURED} "
                    f"(в отчёте нет `run_started_at`) — вердикт стоит на "
                    f"`generated_at` ({report.get('generated_at')}), то есть на "
                    f"НАЧАЛЕ ПОСЛЕДНЕЙ ФАЗЫ прогона, а код мог приехать внутрь "
                    f"уже идущего прогона; форма ADR-259 не исключена, но и не "
                    f"доказана"))

    return Absence(
        artifact=artifact_rel, kind=DECLARED_WITHOUT_CALL, is_finding=True,
        stage=stage, module=module, clock_field=clock_field,
        call_state=call.state, carrier=call.carrier,
        runner_ran_at=report.get("run_started_at"),
        reason=(f"производитель {module} в дереве есть, процесс бегуна "
                f"СТАРТОВАЛ ПОСЛЕ его прихода "
                f"({report.get('run_started_at')}) и ступень {stage!r} не "
                f"назвал — объявленный артефакт без производящего вызова "
                f"(форма ADR-259); состояние вызова: {call.state} "
                f"({call.reason})"))
