#!/usr/bin/env python3
"""spa_core/monitoring/red_set_delta.py — ДЕЛЬТА КРАСНОГО НАБОРА ПО РОДАМ.

# LLM_FORBIDDEN

Вопрос, на который отвечает прибор
----------------------------------
«Какие имена ПРИШЛИ и какие УШЛИ между двумя контрольными прогонами — и к
какому РОДУ принадлежит каждый переход: к дефекту, к обмороку по стенным
часам или к окружению раннера?»

Откуда взят вопрос
------------------
Из обязательного чтения, которое заказ ставит КАЖДОМУ циклу (G1042 п. 0,
дословно):

    «читать ПО `report.json` АРТЕФАКТА … и сличить с 44287563961 (63 имени)
     ПОИМЁННО. Нетто сравнивать нельзя. Пришло что-то в `test_absence_*` ⇒
     это МОЯ регрессия, а не окружение.»

Чтение верное и вопрос нужный. Дефект — в том, над ЧЕМ оно идёт: над
неразделённым ростером `failures`. А в ТОМ ЖЕ документе лежит ось, которая
роды уже различает (`cause_axis.fork`, ADR-910/915): имя могло покраснеть
(`AssertionError` — ИЗМЕРЕНО) либо не дойти до вердикта вовсе
(`wallclock_timeout` — НЕ ИЗМЕРЕНО). В ростере оба несут одно слово `failed`,
и дельта над ростером складывает их в одно число.

Замер, ради которого прибор написан (цикл #1194, 2026-11-18)
------------------------------------------------------------
Четыре подряд контрольных прогона `main`, роды взяты у самого документа:

    прогон        имён  обморок  окружение  вилка дефектов
    44234848871     64       16         11          30…37
    44246906015     56       10         11          28…35
    44287563961     63        7         11          34…45
    44302538342     65       11         11          32…43

Три дельты, КАЖДЫЙ переход отнесён к роду:

    848871→906015:  пришло 2 (обморок 2)              ушло 10 (обморок 8, дефект 2)
    906015→563961:  пришло 10 (дефект 10)             ушло  3 (обморок 3)
    563961→538342:  пришло 4 (**обморок 4, дефект 0**) ушло  2 (дефект 2)

Итого **17 переходов из 31 (55 %) — обморок по стенным часам**, то есть имена,
о которых прогон вердикта НЕ ВЫНЕС ни в одну сторону. А в последней дельте —
той самой, которую заказ велел прочитать, — обмороком является **4 из 4**
пришедших имён: `test_child_env_census::test_every_outcome_the_doors_return_is_declared`
и три имени `test_known_member_probe_census`. Предписанное чтение выдало бы их
следующему циклу как четыре регрессии.

ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ замера, снятый до прибора: все четыре имени ЗЕЛЕНЫ на
Маке — `89 passed, 15 subtests passed in 241.20s` на `origin/main` 7c78cef92;
а `test_child_env_census::test_every_outcome_the_doors_return_is_declared`
приходило, уходило и приходило снова через четыре прогона, не изменившись ни
одним байтом (последнее касание файла — `9562b45c7`, цикл #1180).

Почему это не арифметика
------------------------
«Пришло 4» читается как «я сломал четыре вещи», и на этом числе цикл решает,
брать ли их в работу. Обморок же означает, что сторож не дошёл до вердикта:
чинить там нечего, а гасить нечем — порог `--timeout` поднимать запрещено
(инв. #16, `CLAUDE.md`). Разные роды чинятся РАЗНЫМ, и сложенные в одно число
они приглашают гнаться за фантомом.

Идентичность имени в документе ДВЕ, и прибор переводит её ЗАКРЫТЫМ правилом
------------------------------------------------------------------------------
Ростер несёт путь pytest (`spa_core/tests/test_x.py::C::test_y`), ось родов —
идентичность junit (`spa_core.tests.test_x.C::test_y`). Соединения документ не
даёт, поэтому правило перевода объявлено здесь ОДИН раз
(:func:`junit_identity`) и ПРОВЕРЕНО на всех четырёх живых документах: 248
имён, не соединилось **0**, столкновений ключей **0**. Имя оси, не соединённое
с ростером, — НАЗВАННЫЙ третий исход, а не догадка.

Три исхода, перечень ЗАКРЫТ (инв. #17)
--------------------------------------
``measured``        оба документа прочитаны, переходы есть и отнесены к родам.
``measured_empty``  оба прочитаны, переходов НЕТ — это ЗАМЕР, равный нулю.
``unmeasured``      документ не прочитан / не разобран / оси родов в нём нет /
                    имя оси не соединилось с ростером. Причина НАЗВАНА.

Сумма переходов по родам равна числу переходов — без тождества «свести к роду»
остаток исчезал бы молча.

Род перехода — свойство ТОГО прогона, где имя присутствовало
------------------------------------------------------------
У ПРИШЕДШЕГО имени род берётся у текущего документа, у УШЕДШЕГО — у прежнего.
Иначе о ушедшем имени род спрашивался бы у документа, в котором его нет.

Ось ПЕРЕЕЗДА (шард) — второй вопрос, и он НЕ про род (ADR-1077, цикл #1222)
---------------------------------------------------------------------------
Контрольный прогон идёт по ШАРДАМ (`scripts/ci_control.py plan`, 12 процессов
`pytest`), и состав шарда пересчитывается КАЖДЫЙ раз по весам. Добавление
ОДНОГО тест-файла тасует население: замер #1222 на живой паре 45091782823 →
45108124169 (цикл #1218 добавил `test_derived_artifact_census.py`) —
**ПЕРЕЕХАЛО 1570 файлов из 3011**, то есть больше половины. Все ТРИ настоящих
«пришедших» имени той дельты переехали (`test_hermetic_launchd_door` 8 → 11,
`test_tb_sanitizer_probe` 11 → 6 дважды), а ушедшее
`test_script_path_launch_imports` переехало 1 → 11 И было починено
СОДЕРЖАНИЕМ — то есть «переехал» не отвечает ни «регрессия», ни «не
регрессия».

Поэтому ось переезда даёт имени ЧЕТЫРЕ исхода (:data:`SHARD_VERDICTS`), и
измеренным является ровно ОДИН — :data:`SHARD_SAME`. «Переехал» есть ТРЕТИЙ
исход (заказ G1064 п. 2, дословно: «"переехал" обязан быть третьим исходом
(`unmeasured`), а не "не регрессия" — иначе ось врёт в сторону "чисто"»).

Карты шардов приходят ВХОДАМИ (:func:`shard_map_of`), как и документы: сети у
прибора нет по построению. Карту добывает дверь
`scripts/ci_control_verdict.py::manifest_of_run` из артефакта `ctl-manifest`,
и у неё СВОЙ срок хранения — **30 дней против 90 у отчёта**, поэтому «отчёт
есть, карты нет» — штатное состояние, а не поломка: оно даёт
:data:`SHARD_UNMEASURED` с названной причиной и НЕ рушит дельту целиком.

Чего прибор НЕ доказывает
-------------------------
* Ушедшее имя рода ``wallclock_timeout`` НЕ ПОЧИНЕНО: сторож просто успел
  дойти до вердикта. Это сказано словами в отчёте, а не оставлено читателю.
* Род ``defect_fork`` не означает «настоящий дефект»: вилка прибора причин
  (ADR-913/915) — сама ВИЛКА, и часть её населения зелена на своём дереве
  (19 из 56, замер #1027). Прибор отвечает на вопрос «о чём вердикт ЕСТЬ», а
  не «что сломано».
* Прибор НЕ ходит в сеть и документов не добывает: оба приходят ВХОДАМИ. Дверь
  к сети живёт у `scripts/ci_control_verdict.py` (`report_of_run`), и второй
  её копии здесь нет намеренно.

ADVISORY: прибор только ЧИТАЕТ. Ни байта не правит, ни подпроцесса не
поднимает, о свежести не судит — значит ни одной двери к календарю и к номерам
процессов у него нет по построению.
"""
from __future__ import annotations

from typing import Iterable, NamedTuple

# ───────────────────────────── объявленные исходы ────────────────────────────

MEASURED = "measured"
MEASURED_EMPTY = "measured_empty"
UNMEASURED = "unmeasured"
#: Перечень ЗАКРЫТ: исход вне него есть дефект прибора, а не новое состояние.
STATUSES: tuple[str, ...] = (MEASURED, MEASURED_EMPTY, UNMEASURED)

ROD_DEFECT = "defect_fork"
ROD_WALLCLOCK = "wallclock_timeout"
ROD_RUNNER_ENV = "runner_environment"
#: Имя в ростере, о роде которого ось не сказала ничего. Это НЕ «дефект»:
#: записать его дефектом значило бы выдать «не измерено» за «измерено».
ROD_UNMEASURED = "rod_unmeasured"
RODS: tuple[str, ...] = (ROD_DEFECT, ROD_WALLCLOCK, ROD_RUNNER_ENV, ROD_UNMEASURED)

#: Человеческие имена родов — для отчёта. Словарь ЗАКРЫТ теми же ключами.
ROD_LABEL: dict[str, str] = {
    ROD_DEFECT: "дефект (вилка причин)",
    ROD_WALLCLOCK: "обморок по стенным часам — вердикта НЕТ",
    ROD_RUNNER_ENV: "окружение раннера",
    ROD_UNMEASURED: "РОД НЕ ИЗМЕРЕН",
}


# ────────────────────────── ось ПЕРЕЕЗДА (шард прогона) ──────────────────────

SHARD_SAME = "shard_same"
SHARD_MOVED = "shard_moved"
SHARD_ABSENT = "shard_absent"
SHARD_UNMEASURED = "shard_unmeasured"
#: Перечень ЗАКРЫТ, и измеренным является РОВНО ОДИН исход — :data:`SHARD_SAME`.
#: Остальные три — три РАЗНЫЕ немочи, и свести их в одно слово значило бы
#: повторить тот самый дефект, против которого написан сам прибор.
SHARD_VERDICTS: tuple[str, ...] = (SHARD_SAME, SHARD_MOVED, SHARD_ABSENT,
                                   SHARD_UNMEASURED)

#: Человеческие имена исходов оси. Словарь ЗАКРЫТ теми же ключами.
SHARD_LABEL: dict[str, str] = {
    SHARD_SAME: "шард ТОТ ЖЕ — соседство не менялось",
    SHARD_MOVED: "ПЕРЕЕХАЛ — вердикта о содержании НЕТ",
    SHARD_ABSENT: "файла нет в населении одного из прогонов",
    SHARD_UNMEASURED: "карта шардов НЕ ПРОЧИТАНА",
}

#: Причина, когда карту вовсе не подали. Библиотечный зов без карт законен
#: (так зовёт батарея, которой предмет — роды), и МОЛЧАНИЕ здесь сделало бы
#: «ось не спрашивали» неотличимым от «ось сказала: тот же шард».
NO_SHARD_MAP_REASON = (
    "карта шардов вызывающим НЕ ПОДАНА — ось переезда не спрашивалась; "
    "её добывает дверь `scripts/ci_control_verdict.py::manifest_of_run`")


# ───────────────────────────── перевод идентичности ──────────────────────────

def junit_identity(nodeid: str) -> str:
    """Путь pytest → идентичность junit. Правило ЗАКРЫТО и проверено замером.

    ``spa_core/tests/test_x.py::C::test_y`` → ``spa_core.tests.test_x.C::test_y``
    ``spa_core/tests/test_x.py::test_y``    → ``spa_core.tests.test_x::test_y``

    Соединять ростер с осью родов приходится потому, что документ несёт ДВЕ
    идентичности одного имени и моста между ними не даёт. Правило живёт здесь
    в единственной копии: вторая означала бы два ответа на один вопрос.
    """
    path, _, tail = nodeid.partition("::")
    module = path[:-3] if path.endswith(".py") else path
    module = module.replace("/", ".")
    parts = [p for p in tail.split("::") if p]
    if not parts:
        return module
    return ".".join([module] + parts[:-1]) + "::" + parts[-1]


# ─────────────────────────────── ростер прогона ──────────────────────────────

class Roster(NamedTuple):
    """Красный набор ОДНОГО документа: имена и род каждого имени.

    ``status`` — :data:`MEASURED` либо :data:`UNMEASURED`. Пустой красный набор
    есть ИЗМЕРЕНИЕ (``names == {}`` при ``status == MEASURED``), а не немочь:
    зелёный прогон — ответ, а не отсутствие ответа.
    """

    status: str
    reason: str | None
    run: str | None
    sha: str | None
    #: идентичность junit → nodeid, как его печатает ростер
    names: dict[str, str]
    #: идентичность junit → род из :data:`RODS`
    rods: dict[str, str]

    @property
    def measured(self) -> bool:
        return self.status == MEASURED


def _unmeasured_roster(reason: str, *, run=None, sha=None) -> Roster:
    return Roster(status=UNMEASURED, reason=reason, run=run, sha=sha,
                  names={}, rods={})


def roster_of(doc, *, label: str = "документ") -> Roster:
    """Ростер и роды ОДНОГО ``report.json``. Любая немочь — названная причина.

    Отказ fail-CLOSED по каждому из пяти поводов: документ не словарь · нет
    списка ``failures`` · запись без ``nodeid`` · столкновение идентичностей ·
    нет оси ``cause_axis.fork``. Последний повод отделён нарочно: документ без
    оси родов читается, но ответить о родах нечем, и выдать тогда «все имена —
    дефекты» значило бы подставить догадку (инв. #17).
    """
    if not isinstance(doc, dict):
        return _unmeasured_roster(
            f"{label} не словарь, а {type(doc).__name__} — ростера в нём нет")
    # `run` у этого документа — ОБЪЕКТ (`{"id": …, "attempt": …, "url": …}`),
    # а не строка: напечатать его целиком значило бы выдать заголовок дельты за
    # свалку метаданных. Номера нет ⇒ `None`, и в отчёте станет `?` — не
    # выдуманная строка.
    raw_run = doc.get("run")
    if isinstance(raw_run, dict):
        raw_run = raw_run.get("id")
    run = str(raw_run) if raw_run is not None else None
    sha = doc.get("sha")
    sha = str(sha) if sha is not None else None

    raw = doc.get("failures")
    if not isinstance(raw, list):
        return _unmeasured_roster(
            f"{label} не несёт списка `failures` "
            f"(там {type(raw).__name__}) — красный набор не прочитан",
            run=run, sha=sha)

    names: dict[str, str] = {}
    for row in raw:
        nodeid = row.get("nodeid") if isinstance(row, dict) else None
        if not isinstance(nodeid, str) or not nodeid:
            return _unmeasured_roster(
                f"{label}: запись ростера без `nodeid` — имена не прочитаны",
                run=run, sha=sha)
        key = junit_identity(nodeid)
        if key in names and names[key] != nodeid:
            return _unmeasured_roster(
                f"{label}: две разные записи ростера дают одну идентичность "
                f"`{key}` ({names[key]} и {nodeid}) — соединить с осью родов "
                f"нечем, и выбрать одну из двух прибор не вправе",
                run=run, sha=sha)
        names[key] = nodeid

    fork = ((doc.get("cause_axis") or {}).get("fork")
            if isinstance(doc.get("cause_axis"), dict) else None)
    if not isinstance(fork, dict):
        return _unmeasured_roster(
            f"{label} несёт {len(names)} имён, но оси родов "
            f"(`cause_axis.fork`) в нём нет — о роде перехода сказать нечем, а "
            f"назвать все имена дефектами значило бы выдать догадку за замер",
            run=run, sha=sha)

    rods: dict[str, str] = {key: ROD_DEFECT for key in names}
    for axis, rod in (("wallclock_names", ROD_WALLCLOCK),
                      ("runner_environment_names", ROD_RUNNER_ENV)):
        listed = fork.get(axis)
        if listed is None:
            # Поля нет ⇒ об этом роде документ молчит. Это не «рода нет»:
            # имена, которые к нему принадлежали бы, останутся `defect_fork`,
            # и ошибка пойдёт в сторону БОЛЬШЕГО числа дефектов — то есть в
            # сторону лишнего кандидата, а не объявленной законченной работы.
            continue
        if not isinstance(listed, list):
            return _unmeasured_roster(
                f"{label}: `cause_axis.fork.{axis}` не список, а "
                f"{type(listed).__name__} — род не прочитан",
                run=run, sha=sha)
        for item in listed:
            # fail-CLOSED: имя оси, не соединённое с ростером, ОПРОВЕРГАЕТ
            # правило перевода идентичности; соединять «по похожести» запрещено.
            if not isinstance(item, str) or item not in names:
                return _unmeasured_roster(
                    f"{label}: ось родов называет `{item}`, которого в ростере "
                    f"нет — правило перевода идентичности опровергнуто этим "
                    f"документом",
                    run=run, sha=sha)
            rods[item] = rod

    return Roster(status=MEASURED, reason=None, run=run, sha=sha,
                  names=names, rods=rods)


# ──────────────────────────── карта шардов прогона ───────────────────────────

class ShardMap(NamedTuple):
    """Карта файл → номер шарда ОДНОГО прогона (`ctl-manifest/manifest.json`).

    ``status`` — :data:`MEASURED` либо :data:`UNMEASURED`; третьего у КАРТЫ не
    бывает, потому что «карта пустая» производитель не выпускает вовсе
    (`ci_control.cmd_plan` отказывает на нулевом населении — инв. #17 у него).
    """

    status: str
    reason: str | None
    run: str | None
    #: путь файла, как его печатает ростер pytest → номер шарда
    by_file: dict[str, int]

    @property
    def measured(self) -> bool:
        return self.status == MEASURED


def unmeasured_shard_map(reason: str, *, run=None) -> ShardMap:
    """Карта, которой НЕТ, с НАЗВАННОЙ причиной. Пустой картой не притворяется."""
    return ShardMap(status=UNMEASURED, reason=reason, run=run, by_file={})


def shard_map_of(doc, *, label: str = "манифест") -> ShardMap:
    """Карта шардов ОДНОГО манифеста. Любая немочь — названная причина.

    Отказ fail-CLOSED по каждому поводу: документ не словарь · нет списка
    ``shards`` · запись без номера шарда · ``files`` не список · элемент не
    путь · ОДИН файл в ДВУХ шардах · населения нет вовсе. Последний повод
    отделён нарочно: карта без файлов ответила бы :data:`SHARD_ABSENT` о
    КАЖДОМ имени, и «манифест не разобран» стало бы неотличимо от «файл
    новый».

    Столкновение номеров тоже отделено: взять молча последний значило бы
    ответить о соседстве, которого прибор не мерил, — выбрать один из двух он
    не вправе.
    """
    if not isinstance(doc, dict):
        return unmeasured_shard_map(
            f"{label} не словарь, а {type(doc).__name__} — карты шардов в нём нет")
    rows = doc.get("shards")
    sha = doc.get("sha")
    run = str(sha) if sha is not None else None
    if not isinstance(rows, list):
        return unmeasured_shard_map(
            f"{label} не несёт списка `shards` (там {type(rows).__name__}) — "
            f"карта шардов не прочитана", run=run)
    by_file: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict) or "shard" not in row:
            return unmeasured_shard_map(
                f"{label}: запись `shards` без номера шарда — карта не прочитана",
                run=run)
        number = row["shard"]
        files = row.get("files")
        if not isinstance(files, list):
            return unmeasured_shard_map(
                f"{label}: шард {number!r} не несёт списка `files` (там "
                f"{type(files).__name__}) — карта не прочитана", run=run)
        for item in files:
            if not isinstance(item, str) or not item:
                return unmeasured_shard_map(
                    f"{label}: шард {number!r} называет файл {item!r} — это не "
                    f"путь, и карта не прочитана", run=run)
            if item in by_file and by_file[item] != number:
                return unmeasured_shard_map(
                    f"{label}: файл `{item}` объявлен сразу в шардах "
                    f"{by_file[item]!r} и {number!r} — выбрать один из двух "
                    f"прибор не вправе", run=run)
            by_file[item] = number
    if not by_file:
        return unmeasured_shard_map(
            f"{label} не называет ни одного файла — населения в нём нет, а "
            f"«файла нет в населении» о каждом имени было бы ответом о "
            f"манифесте, а не о переезде", run=run)
    return ShardMap(status=MEASURED, reason=None, run=run, by_file=by_file)


def _as_shard_map(given, *, side: str) -> ShardMap:
    """ВХОД оси — именно :class:`ShardMap`, а не сырой манифест.

    Разобрать сырой словарь здесь было бы удобно и неверно: тогда у вопроса
    «кто разбирает манифест» стало бы два ответа, и второй расходился бы с
    первым молча (класс ADR-220). Поэтому сырой документ — НАЗВАННЫЙ отказ.
    """
    if isinstance(given, ShardMap):
        return given
    if given is None:
        return unmeasured_shard_map(NO_SHARD_MAP_REASON)
    return unmeasured_shard_map(
        f"карта шардов {side} подана как {type(given).__name__}, а не "
        f"`ShardMap` — разбирать манифест второй раз прибор не вправе, "
        f"дверь одна: `shard_map_of`")


def _shard_verdict(nodeid: str, prev: ShardMap, curr: ShardMap):
    """Переезд ОДНОГО имени: исход, два номера и причина немочи.

    Спрашивается ПО ФАЙЛУ: шард назначается файлу целиком
    (`ci_control.make_plan` раскладывает файлы, не отдельные тесты), и
    спрашивать его у nodeid значило бы выдумать соседство внутри файла.
    """
    path = nodeid.partition("::")[0]
    for side, chart in (("прежнего прогона", prev), ("текущего прогона", curr)):
        if not chart.measured:
            return (SHARD_UNMEASURED, None, None,
                    f"карта шардов {side} не прочитана: {chart.reason}")
    was, now_ = prev.by_file.get(path), curr.by_file.get(path)
    if was is None or now_ is None:
        if was is None and now_ is None:
            missing = "обоих прогонов"
        elif was is None:
            missing = "прежнего прогона"
        else:
            missing = "текущего прогона"
        return (SHARD_ABSENT, was, now_,
                f"файла `{path}` нет в населении {missing} — соседство сравнить "
                f"нечем; «файл новый» и «население разошлось» этой картой "
                f"неразличимы")
    if was == now_:
        return (SHARD_SAME, was, now_, None)
    return (SHARD_MOVED, was, now_,
            f"файл `{path}` шёл шардом {was}, а стал шардом {now_} — вердикт о "
            f"его СОДЕРЖАНИИ этой дельтой НЕ ИЗМЕРЕН")


# ──────────────────────────────── сама дельта ────────────────────────────────

class Transition(NamedTuple):
    """Один переход: имя, его род, чей это род — и ось ПЕРЕЕЗДА.

    Две оси у одного перехода независимы и ни одна не отвечает на вопрос
    другой: род говорит «вынес ли прогон вердикт об этом имени», ось переезда —
    «о том же ли соседстве этот вердикт». Умолчание оси —
    :data:`SHARD_UNMEASURED`: переход, построенный без карт, об оси молчать не
    вправе (инв. #17).
    """

    nodeid: str
    identity: str
    rod: str
    #: ``prev`` у ушедшего, ``curr`` у пришедшего — чей это род
    rod_from: str
    #: один из :data:`SHARD_VERDICTS`
    shard: str = SHARD_UNMEASURED
    shard_prev: int | None = None
    shard_curr: int | None = None
    shard_why: str | None = NO_SHARD_MAP_REASON

    @property
    def shard_measured(self) -> bool:
        """ТОЛЬКО :data:`SHARD_SAME` означает, что соседство то же."""
        return self.shard == SHARD_SAME


class Delta(NamedTuple):
    status: str
    reason: str | None
    prev: Roster
    curr: Roster
    arrived: tuple[Transition, ...]
    departed: tuple[Transition, ...]
    #: карты шардов обоих прогонов — ВХОДЫ, а не добыча прибора
    prev_shards: ShardMap = ShardMap(UNMEASURED, NO_SHARD_MAP_REASON, None, {})
    curr_shards: ShardMap = ShardMap(UNMEASURED, NO_SHARD_MAP_REASON, None, {})

    @property
    def measured(self) -> bool:
        return self.status in (MEASURED, MEASURED_EMPTY)

    def by_rod(self, rows: Iterable[Transition]) -> dict[str, list[Transition]]:
        """Переходы, разложенные по родам. Сумма равна числу переходов."""
        out: dict[str, list[Transition]] = {rod: [] for rod in RODS}
        for row in rows:
            out[row.rod].append(row)
        return out

    def by_shard(self, rows: Iterable[Transition]) -> dict[str, list[Transition]]:
        """Переходы, разложенные по оси переезда. Сумма равна числу переходов."""
        out: dict[str, list[Transition]] = {v: [] for v in SHARD_VERDICTS}
        for row in rows:
            out[row.shard].append(row)
        return out

    @property
    def defect_arrivals(self) -> tuple[Transition, ...]:
        """Пришло, и вердикт о РОДЕ есть. Ось переезда здесь НЕ спрошена.

        Свойство оставлено как было: оно отвечает ровно на вопрос рода, и
        сужать его осью переезда значило бы сменить смысл имени молча. За чем
        гнаться — :attr:`chase`.
        """
        return tuple(r for r in self.arrived if r.rod == ROD_DEFECT)

    @property
    def chase(self) -> tuple[Transition, ...]:
        """ЕДИНСТВЕННОЕ, за чем стои́т гнаться: род ДЕФЕКТ **и** шард ТОТ ЖЕ."""
        return tuple(r for r in self.defect_arrivals if r.shard == SHARD_SAME)

    @property
    def shard_blind_arrivals(self) -> tuple[Transition, ...]:
        """Пришло, род дефект, а ось переезда НЕ ИЗМЕРЕНА — ТРЕТИЙ исход.

        Ни «гнаться», ни «чисто». Назвать их вторым значило бы соврать в
        сторону «чисто» (ровно запрет заказа G1064 п. 2), первым — отдать
        следующему циклу имя, которого он не воспроизведёт: замер #1222 нашёл
        дельту, где таких имён 3 из 3.
        """
        return tuple(r for r in self.defect_arrivals if r.shard != SHARD_SAME)

    @property
    def moved_departures(self) -> tuple[Transition, ...]:
        """УШЛО и ПЕРЕЕХАЛО. «Переехал» ≠ «не починен» и ≠ «починен»."""
        return tuple(r for r in self.departed if r.shard == SHARD_MOVED)

    @property
    def shard_axis_measured(self) -> bool:
        """Обе карты прочитаны. Одна немочь делает ось слепой целиком."""
        return self.prev_shards.measured and self.curr_shards.measured

    @property
    def has_findings(self) -> bool:
        return self.status == UNMEASURED or bool(self.defect_arrivals)


def delta(prev_doc, curr_doc, *, prev_shards=None, curr_shards=None) -> Delta:
    """Дельта двух ``report.json`` ПО РОДАМ и ПО ОСИ ПЕРЕЕЗДА.

    Немочь ЛЮБОГО из двух ростеров делает дельту :data:`UNMEASURED` с названной
    причиной: половина дельты — не дельта, и объявить её «пришло 0» значило бы
    ровно то смешение, против которого прибор написан.

    Немочь КАРТЫ ШАРДОВ дельту НЕ рушит, и это РАЗНИЦА ПО ПРЕДМЕТУ, а не
    снисхождение: ростер отвечает «какие имена красны», карта — «о том же ли
    соседстве». Срок хранения у карты 30 дней против 90 у отчёта, поэтому
    «отчёт есть, карты нет» штатно; слепая ось становится
    :data:`SHARD_UNMEASURED` У КАЖДОГО перехода с названной причиной, а не
    молчанием.

    ``prev_shards`` / ``curr_shards`` — :class:`ShardMap` (их отдаёт
    :func:`shard_map_of`). Сырой манифест здесь ОТКАЗЫВАЕТ: второй разбор
    разошёлся бы с первым молча.
    """
    prev = roster_of(prev_doc, label="прежний документ")
    curr = roster_of(curr_doc, label="текущий документ")
    prev_map = _as_shard_map(prev_shards, side="прежнего прогона")
    curr_map = _as_shard_map(curr_shards, side="текущего прогона")
    if not prev.measured or not curr.measured:
        why = "; ".join(r.reason for r in (prev, curr) if r.reason)
        return Delta(status=UNMEASURED, reason=why, prev=prev, curr=curr,
                     arrived=(), departed=(),
                     prev_shards=prev_map, curr_shards=curr_map)

    def _move(nodeid: str, identity: str, rod: str, rod_from: str) -> Transition:
        verdict, was, now_, why = _shard_verdict(nodeid, prev_map, curr_map)
        return Transition(nodeid=nodeid, identity=identity, rod=rod,
                          rod_from=rod_from, shard=verdict, shard_prev=was,
                          shard_curr=now_, shard_why=why)

    arrived = tuple(
        _move(curr.names[k], k, curr.rods.get(k, ROD_UNMEASURED), "curr")
        for k in sorted(set(curr.names) - set(prev.names)))
    departed = tuple(
        _move(prev.names[k], k, prev.rods.get(k, ROD_UNMEASURED), "prev")
        for k in sorted(set(prev.names) - set(curr.names)))

    status = MEASURED if (arrived or departed) else MEASURED_EMPTY
    return Delta(status=status, reason=None, prev=prev, curr=curr,
                 arrived=arrived, departed=departed,
                 prev_shards=prev_map, curr_shards=curr_map)


# ─────────────────────────────────── отчёт ───────────────────────────────────

def shard_tag(row: Transition) -> str:
    """Ось переезда ОДНОЙ строки отчёта. Четыре исхода — четыре РАЗНЫХ слова."""
    if row.shard == SHARD_SAME:
        return f"шард {row.shard_prev} (тот же)"
    if row.shard == SHARD_MOVED:
        return f"ПЕРЕЕХАЛ шард {row.shard_prev} → {row.shard_curr}"
    if row.shard == SHARD_ABSENT:
        return f"НЕТ В НАСЕЛЕНИИ (шард {row.shard_prev} → {row.shard_curr})"
    return "ШАРД НЕ ИЗМЕРЕН"


def format_delta(d: Delta) -> list[str]:
    """Строки отчёта. Три исхода различимы СЛОВАМИ, а не только числом."""
    if d.status == UNMEASURED:
        return ["⛔ ДЕЛЬТА КРАСНОГО НАБОРА — НЕ ИЗМЕРЕНО",
                f"   причина: {d.reason}",
                "   «пришло 0» здесь НЕ печатается: половина дельты дельтой не является"]

    head = (f"ДЕЛЬТА КРАСНОГО НАБОРА ПО РОДАМ · прежний {d.prev.run or '?'} "
            f"({len(d.prev.names)} имён) → текущий {d.curr.run or '?'} "
            f"({len(d.curr.names)} имён)")
    if d.status == MEASURED_EMPTY:
        return [head,
                "✅ ИЗМЕРЕНО И РАВНО НУЛЮ: ни одно имя не пришло и не ушло — "
                "это замер, а не отсутствие замера"]

    lines = [head]
    for title, rows in (("ПРИШЛО", d.arrived), ("УШЛО", d.departed)):
        if not rows:
            lines.append(f"  {title}: 0 — измерено и равно нулю")
            continue
        groups = d.by_rod(rows)
        parts = ", ".join(f"{ROD_LABEL[rod]} {len(v)}"
                          for rod, v in groups.items() if v)
        lines.append(f"  {title}: {len(rows)} — {parts}")
        shard_parts = ", ".join(f"{SHARD_LABEL[v]} {len(g)}"
                                for v, g in d.by_shard(rows).items() if g)
        lines.append(f"     ось переезда: {shard_parts}")
        for rod in RODS:
            for row in groups[rod]:
                mark = {ROD_DEFECT: "•", ROD_WALLCLOCK: "⏱",
                        ROD_RUNNER_ENV: "⚙", ROD_UNMEASURED: "?"}[rod]
                lines.append(f"     {mark} [{rod}] {row.nodeid} ⟂ {shard_tag(row)}")
    if any(r.rod == ROD_WALLCLOCK for r in d.departed):
        lines.append("  ⏱ УШЕДШЕЕ ИМЯ РОДА ЧАСОВ НЕ ПОЧИНЕНО: сторож лишь успел "
                     "дойти до вердикта — порог поднимать запрещено (инв. #16)")
    if any(r.rod == ROD_WALLCLOCK for r in d.arrived):
        lines.append("  ⏱ ПРИШЕДШЕЕ ИМЯ РОДА ЧАСОВ РЕГРЕССИЕЙ НЕ ЯВЛЯЕТСЯ: "
                     "вердикта о нём прогон не вынес ни в одну сторону")
    if not d.shard_axis_measured:
        # две карты могут быть слепы по ОДНОЙ причине (карту не подали вовсе), и
        # печатать её дважды значило бы выдать одно наблюдение за два.
        why = "; ".join(dict.fromkeys(
            m.reason for m in (d.prev_shards, d.curr_shards) if m.reason))
        lines.append(f"  ⟂ ОСЬ ПЕРЕЕЗДА СЛЕПА ЦЕЛИКОМ: {why}")
    if d.shard_blind_arrivals:
        lines.append(
            f"  ⟂ {len(d.shard_blind_arrivals)} пришедшее(их) имя(ён) рода дефекта "
            "стоят на НЕИЗМЕРЕННОЙ оси переезда: это ТРЕТИЙ исход — не «гнаться» "
            "и не «чисто»")
    if d.moved_departures:
        lines.append(
            f"  ⟂ {len(d.moved_departures)} ушедшее(их) имя(ён) ПЕРЕЕХАЛО, и "
            "починенным это их НЕ объявляет: `test_script_path_launch_imports` "
            "19.11 переехал И был починен содержанием — одна ось двух ответов "
            "не даёт")
    lines.append(f"  → гнаться стои́т за {len(d.chase)} именем(ами): пришло · "
                 "вердикт о роде ЕСТЬ · шард НЕ менялся")
    return lines
