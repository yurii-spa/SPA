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

## Пять исходов

| Состояние | Вердикт |
|---|---|
| перепись НАЗВАНА бегуном в `censuses.attempted`, артефакта нет | **находка** (+ причина из `skipped`) |
| не названа, отчёт бегуна СТАРШЕ производителя в дереве | ⏳ **ЕЩЁ НЕ ПРОИЗВОДИЛСЯ** — не находка |
| не названа, отчёт бегуна МОЛОЖЕ производителя | **находка**: бегун отработал и ступени не позвал (форма ADR-259) |
| артефакт не объявлен НИ ОДНОЙ переписью | **находка**, `НЕ ИЗМЕРЕНО`: своего бегуна спросить нечем |
| спросить нечем (нет модуля, отчёт нечитаем, у отчёта нет часов) | **находка**, `НЕ ИЗМЕРЕНО` |

Третий исход **не вечен**: он закрывается следующим прогоном бегуна САМ, без
правки кода и без записи в базу. Это не `UNCHECKED`, который никогда не станет
`CHECKED`.

Время — ВХОД (`.claude/rules/deployment.md`): `now` принимается параметром,
собственных стенных часов у вердикта нет. Объявление переписи тоже вход
(`products=`), чтобы сцена могла нарушать ТОЛЬКО своё ограничение.

Только stdlib. LLM здесь запрещён (инвариант #3): это monitoring.
"""
from __future__ import annotations

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


def verdict(artifact_rel: str, *, root: str, now: dt.datetime,
            data_dir: str | None = None,
            products: dict | None = None,
            runner_report_rel: str = RUNNER_REPORT_REL) -> Absence:
    """Вердикт об отсутствующем артефакте. Пять исходов, см. шапку модуля.

    `now` — вход, а не окружение. `products` — вход затем, чтобы сцена
    нарушала ТОЛЬКО своё ограничение (иначе тест про «не объявлен» пришлось бы
    ставить на живой состав переписи и он краснел бы от чужой правки).
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

    ran = _parse_ts(report.get("generated_at"))
    if ran is None:
        return Absence(
            artifact=artifact_rel, kind=UNMEASURED_REPORT_HAS_NO_CLOCK,
            is_finding=True, stage=stage, module=module,
            reason=(f"у отчёта бегуна нет собственного времени ⇒ «успел ли он "
                    f"увидеть {module}» {UNMEASURED}; строка остаётся находкой"))

    born = dt.datetime.fromtimestamp(os.path.getmtime(module_full),
                                     dt.timezone.utc)
    if ran < born:
        return Absence(
            artifact=artifact_rel, kind=NOT_YET, is_finding=False,
            stage=stage, module=module,
            module_age_h=round((now - born).total_seconds() / 3600.0, 2),
            runner_ran_at=report.get("generated_at"),
            reason=(f"производитель {module} приехал в дерево ПОСЛЕ последнего "
                    f"прогона своего бегуна"))

    return Absence(
        artifact=artifact_rel, kind=DECLARED_WITHOUT_CALL, is_finding=True,
        stage=stage, module=module, runner_ran_at=report.get("generated_at"),
        reason=(f"производитель {module} в дереве есть, бегун отработал ПОСЛЕ "
                f"его прихода ({report.get('generated_at')}) и ступень "
                f"{stage!r} не назвал — объявленный артефакт без производящего "
                f"вызова (форма ADR-259)"))
