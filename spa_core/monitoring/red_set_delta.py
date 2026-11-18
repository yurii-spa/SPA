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


# ──────────────────────────────── сама дельта ────────────────────────────────

class Transition(NamedTuple):
    """Один переход: имя, его род и документ, у которого род спрошен."""

    nodeid: str
    identity: str
    rod: str
    #: ``prev`` у ушедшего, ``curr`` у пришедшего — чей это род
    rod_from: str


class Delta(NamedTuple):
    status: str
    reason: str | None
    prev: Roster
    curr: Roster
    arrived: tuple[Transition, ...]
    departed: tuple[Transition, ...]

    @property
    def measured(self) -> bool:
        return self.status in (MEASURED, MEASURED_EMPTY)

    def by_rod(self, rows: Iterable[Transition]) -> dict[str, list[Transition]]:
        """Переходы, разложенные по родам. Сумма равна числу переходов."""
        out: dict[str, list[Transition]] = {rod: [] for rod in RODS}
        for row in rows:
            out[row.rod].append(row)
        return out

    @property
    def defect_arrivals(self) -> tuple[Transition, ...]:
        """ЕДИНСТВЕННОЕ, за чем стоит гнаться: пришло и вердикт о нём ЕСТЬ."""
        return tuple(r for r in self.arrived if r.rod == ROD_DEFECT)

    @property
    def has_findings(self) -> bool:
        return self.status == UNMEASURED or bool(self.defect_arrivals)


def delta(prev_doc, curr_doc) -> Delta:
    """Дельта двух ``report.json`` ПО РОДАМ.

    Немочь ЛЮБОГО из двух ростеров делает дельту :data:`UNMEASURED` с названной
    причиной: половина дельты — не дельта, и объявить её «пришло 0» значило бы
    ровно то смешение, против которого прибор написан.
    """
    prev = roster_of(prev_doc, label="прежний документ")
    curr = roster_of(curr_doc, label="текущий документ")
    if not prev.measured or not curr.measured:
        why = "; ".join(r.reason for r in (prev, curr) if r.reason)
        return Delta(status=UNMEASURED, reason=why, prev=prev, curr=curr,
                     arrived=(), departed=())

    arrived = tuple(
        Transition(nodeid=curr.names[k], identity=k,
                   rod=curr.rods.get(k, ROD_UNMEASURED), rod_from="curr")
        for k in sorted(set(curr.names) - set(prev.names)))
    departed = tuple(
        Transition(nodeid=prev.names[k], identity=k,
                   rod=prev.rods.get(k, ROD_UNMEASURED), rod_from="prev")
        for k in sorted(set(prev.names) - set(curr.names)))

    status = MEASURED if (arrived or departed) else MEASURED_EMPTY
    return Delta(status=status, reason=None, prev=prev, curr=curr,
                 arrived=arrived, departed=departed)


# ─────────────────────────────────── отчёт ───────────────────────────────────

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
        for rod in RODS:
            for row in groups[rod]:
                mark = {ROD_DEFECT: "•", ROD_WALLCLOCK: "⏱",
                        ROD_RUNNER_ENV: "⚙", ROD_UNMEASURED: "?"}[rod]
                lines.append(f"     {mark} [{rod}] {row.nodeid}")
    if any(r.rod == ROD_WALLCLOCK for r in d.departed):
        lines.append("  ⏱ УШЕДШЕЕ ИМЯ РОДА ЧАСОВ НЕ ПОЧИНЕНО: сторож лишь успел "
                     "дойти до вердикта — порог поднимать запрещено (инв. #16)")
    if any(r.rod == ROD_WALLCLOCK for r in d.arrived):
        lines.append("  ⏱ ПРИШЕДШЕЕ ИМЯ РОДА ЧАСОВ РЕГРЕССИЕЙ НЕ ЯВЛЯЕТСЯ: "
                     "вердикта о нём прогон не вынес ни в одну сторону")
    lines.append(f"  → гнаться стои́т за {len(d.defect_arrivals)} именем(ами): "
                 "пришло И вердикт о нём ЕСТЬ")
    return lines
