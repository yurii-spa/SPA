#!/usr/bin/env python3
"""spa_core/monitoring/probe_absence_cause_census.py — ПОЧЕМУ У ПРИБОРА НЕТ ПРОБЫ.

# LLM_FORBIDDEN

Вопрос, на который отвечает прибор
----------------------------------
«У каждого из членов класса "прибор без пробы ИЗВЕСТНЫЙ ЧЛЕН" (ADR-1041) —
пробы ДЕЙСТВИТЕЛЬНО нет, или она есть, а ДЕТЕКТОР её не узнаёт?»

Откуда взят вопрос
------------------
Заказ **G1030 п. 3** приказа владельца «Portfolio CIO», дословно:

    «РАЗБИЕНИЕ 46 членов по причинам НЕ ИЗМЕРЕНО и нулём не считается. У кого
     формы не хватает (настоящая проба в неузнанном виде) против кого
     настоящей пробы нет — разные работы и разная цена. Мерить ПРОБОЙ
     (приписать по одному живой зов и посмотреть, меняется ли исход), а не
     чтением глазами.»

Соседний прибор (`known_member_probe_census`, ADR-1041) напечатал ЧИСЛО — 46
из 90 — и сам назвал его ВЕРХНЕЙ границей: форма пробы закрыта перечнями, и
настоящая проба в неузнанной форме попадает в «пробы нет». То есть число
отвечает на вопрос «кого форма не нашла», а не на вопрос «у кого пробы нет», и
разница между этими двумя вопросами и есть предмет здесь.

Как мерится — ЗАСЕВОМ, а не чтением
------------------------------------
Форма пробы, которую узнаёт детектор, есть КОНЪЮНКЦИЯ трёх условий:

    1. батарея НАЙДЕНА (дверь: импорт прибора либо его путь строкой);
    2. в тест-области есть ЖИВОЙ зов прибора (ответ «отравлен» живым корнем);
    3. утверждение о живом ответе предъявляет ИЗВЕСТНОГО члена в узнаваемой
       форме (`ITEM_FORMS`).

Прибор дописывает в батарею члена ЧЕТЫРЕ засева — один канонический (все три
условия) и три ДЕФЕКТНЫХ, каждый без ровно одного условия, — и спрашивает тем
же читателем (`known_member_probe_census.probes_in_battery`), меняется ли
исход. Засев композируется ПО ТОМУ, ЧТО БАТАРЕЯ УЖЕ ВВЕЗЛА (своего импорта
засев не приносит): иначе он отвечал бы на вопрос «узнаёт ли детектор мой
собственный засев», а не «достаёт ли он до этого прибора».

Три исхода и ЧЕТВЁРТЫЙ, перечень ЗАКРЫТ (инв. #17)
--------------------------------------------------
``probe_absent``    канонический засев ИЗМЕНИЛ исход, ни один дефектный — нет.
                    Детектор до прибора ДОСТАЁТ ⇒ «пробы нет» о нём — правда,
                    и работа здесь: НАПИСАТЬ пробу.
``detector_blind``  канонический засев исхода НЕ изменил ни в одной батарее.
                    Детектор до прибора НЕ достаёт ⇒ о наличии пробы у него не
                    известно ничего, и работа здесь ДРУГАЯ: починить ФОРМУ.
``detector_loose``  ДЕФЕКТНЫЙ засев исход изменил. Детектор шире своей
                    докстроки ⇒ его ответ о ЭТОМ приборе не надёжен и с другой
                    стороны (сторона ``has_probe`` умеет быть ложной).
``unmeasured``      засев не составить или батарея не прочитана — с НАЗВАННОЙ
                    причиной. Это НЕ «пробы нет» и НЕ «детектор слеп».

Старшинство исходов НАЗВАНО, а не случайно: ``unmeasured`` → ``detector_loose``
→ ``detector_blind`` → ``probe_absent``. Ненадёжность детектора важнее
собственного вердикта о приборе: пока она не снята, остальное про него — ответ
прибора о самом себе.

ВТОРАЯ ОСЬ — ДИСТАНЦИЯ, и без неё первая почти ничего не говорит
----------------------------------------------------------------
Канонический засев приносит СВОЙ живой зов и СВОЁ имя члена, поэтому отвечает
он ровно на один вопрос: «достаёт ли детектор до этого прибора». О МАТЕРИАЛЕ
батареи — то есть о второй половине вопроса заказа, «настоящая проба в
неузнанном виде», — он не говорит ничего. Поэтому рядом стоит вторая ось, и
мерится она засевом ТОЛЬКО недостающего конъюнкта: в УЖЕ СУЩЕСТВУЮЩИЙ тест
батареи дописывается ОДНО утверждение с именем члена, и больше ничего.

``one_claim_away``  исход изменился ⇒ живой зов прибора в этом тесте УЖЕ ЕСТЬ,
                    и не хватает только имени члена. Это и есть перечень
                    КАНДИДАТОВ на «проба есть, форма не узнаёт»; цена работы
                    здесь — одна строка.
``no_live_call``    не изменился ни в одном тесте ⇒ батарея вообще не
                    спрашивает прибор о живом дереве. Работа другая и дороже.
``unmeasured``      дописать утверждение некуда (ни один тест не связывает
                    имён) либо батарея не разобрана — с названной причиной.

Вывод «живой зов уже есть» законен ровно потому, что засев ``drops_instrument_call``
(утверждение с именем члена БЕЗ зова прибора) исхода НЕ меняет — и это
ИЗМЕРЕНО по каждому члену, а не предположено.

ДВУСТОРОННЯЯ калибровка — требование заказа, а не украшение
------------------------------------------------------------
G1030 п. 2 (урок, купленный пятью опровержениями формы в #1180): «калибровка
обязана быть ДВУСТОРОННЕЙ (известные члены И известные НЕ-члены), потому что
ошибка автора бывает в обе стороны». Поэтому ДО печати разбиения
``calibrate()`` предъявляет:

* ``CALIBRATION_FLIP`` — приборы, у которых канонический засев ОБЯЗАН изменить
  исход (их батарея ввозит прибор импортом — это дословно та форма, которую
  детектор хвалит). Не изменил ⇒ неверна ФОРМА ЗАСЕВА, а не дерево: отказ.
* ``CALIBRATION_NO_FLIP`` — те же приборы с ДЕФЕКТНЫМИ засевами: исход
  меняться НЕ ДОЛЖЕН, и назван конъюнкт, который каждый засев снимает.
  Изменил ⇒ детектор вакуумен, и разбиение смысла не имеет: отказ.

Чего прибор НЕ доказывает — сказано вслух
-----------------------------------------
* **Засев НЕ ИСПОЛНЯЕТСЯ.** Читатель класса (ADR-1041) судит по AST, поэтому и
  засев живёт на уровне AST. Ответ значит «детектор УЗНАЛ БЫ пробу этой формы
  здесь», а не «такую пробу можно написать и она пройдёт».
* **Дверь (условие 1) здесь НЕ под засевом.** Она измерена соседом: у всех 46
  членов батарея НАЙДЕНА (``battery_absent`` = 0), поэтому под засевом стоят
  условия 2 и 3. Появись член с родом ``battery_absent`` — он получает
  ``unmeasured`` с названной причиной, а не ответ.
* ``probe_absent`` не означает «пробу легко написать»: он означает, что ответ
  соседа об этом приборе — о дереве, а не о его собственной слепоте.
* ``one_claim_away`` есть ПЕРЕЧЕНЬ КАНДИДАТОВ, а не находка: настоящая ли
  проба лежит в том тесте в неузнанной форме — следующий вопрос, и он требует
  прочитать его утверждения, чего прибор не делает. Ошибка идёт в сторону
  БОЛЬШЕГО числа кандидатов, и это выбрано нарочно.
* Поверхность наследована целиком: прибор мерит ТОТ перечень, который ему
  названы входом. Своего объявления класса он не держит.

ADVISORY: прибор только ЧИТАЕТ дерево. Байты засева живут в ПАМЯТИ (строка,
переданная читателю), ни один файл дерева не правится — значит окна
мутационного прибора (ADR-772) у него нет по построению, как нет ни двери к
календарю, ни двери к номерам процессов.
"""
from __future__ import annotations

import ast
import json
import pathlib
from dataclasses import dataclass, field
from typing import Iterable, Optional

from spa_core.monitoring import known_member_probe_census as kmp

# ───────────────────────────── объявленные исходы ────────────────────────────

PROBE_ABSENT = "probe_absent"
DETECTOR_BLIND = "detector_blind"
DETECTOR_LOOSE = "detector_loose"
UNMEASURED = "unmeasured"
OUTCOMES: tuple[str, ...] = (PROBE_ABSENT, DETECTOR_BLIND, DETECTOR_LOOSE, UNMEASURED)

#: Старшинство при совпадении признаков. Названо, а не выведено из порядка
#: ветвей: читателю обязано быть видно, какой ответ побеждает и почему.
PRECEDENCE: tuple[str, ...] = (UNMEASURED, DETECTOR_LOOSE, DETECTOR_BLIND, PROBE_ABSENT)

#: Чем засев зовёт прибор. Перечень ЗАКРЫТ и прочитан У БАТАРЕИ, а не выдуман.
BY_MODULE = "module"   #: батарея ввезла модуль — `mod.f(root)`
BY_FUNC = "func"       #: батарея ввезла функцию поимённо — `f(root)`
BY_PATH = "path"       #: батарея называет путь прибора строкой — `run([…], cwd=root)`
SEED_DOORS: tuple[str, ...] = (BY_MODULE, BY_FUNC, BY_PATH)
#: Ярлык строки, у которой двери засева нет вовсе. Нужен отдельным значением:
#: без него ось дверей не покрывала бы население, и «засев составить нечем»
#: стало бы неотличимо от «про дверь не спрашивали» (инв. #17). Строка с
#: НЕСКОЛЬКИМИ дверями несёт их через `+` — это ярлык, а не четвёртая дверь.
DOOR_NOT_COMPOSED = "не составлен"

#: Засевы. Канонический — все три условия; остальные снимают РОВНО ОДНО, и
#: снятое названо: без этого «не изменил исход» нечем отличить от «засев кривой».
SEED_CANONICAL = "canonical"
SEED_NO_LIVE = "drops_live_root"
SEED_NO_MEMBER = "drops_named_member"
SEED_NO_CALL = "drops_instrument_call"
DEFECTIVE_SEEDS: tuple[str, ...] = (SEED_NO_LIVE, SEED_NO_MEMBER, SEED_NO_CALL)
SEEDS: tuple[str, ...] = (SEED_CANONICAL,) + DEFECTIVE_SEEDS

DROPPED_CONJUNCT: dict[str, str] = {
    SEED_CANONICAL: "ничего не снято — все три условия формы",
    SEED_NO_LIVE: "условие 2: корень ОДНОРАЗОВЫЙ, а не живой",
    SEED_NO_MEMBER: "условие 3: утверждение сверяет ответ прибора с ним же",
    SEED_NO_CALL: "условие 2: зова прибора нет вовсе — ответ не отравлен",
}

#: Имя члена, которое засев предъявляет. Это ФОРМА, а не верное утверждение о
#: классе каждого прибора: предметом здесь является узнавание формы детектором.
SEED_ITEM = "spa_core/monitoring/known_member_probe_census.py"

_SEED_PREFIX = "test_ZZZ_probe_absence_cause_seed_"

# ───────────────────────── вторая ось: ДИСТАНЦИЯ до пробы ────────────────────
#: Канонический засев отвечает «достаёт ли детектор до прибора». Он НЕ
#: отвечает на второй вопрос заказа — «настоящая проба в неузнанном виде»:
#: засев приносит свой живой зов и своё имя члена, поэтому про МАТЕРИАЛ
#: батареи он не говорит ничего. Вторая ось спрашивает именно о материале:
#: дописывается ТОЛЬКО недостающий конъюнкт (утверждение с именем члена) в
#: УЖЕ СУЩЕСТВУЮЩИЙ тест батареи, и больше ничего.
ONE_CLAIM_AWAY = "one_claim_away"   #: исход изменился ⇒ живой зов в тесте УЖЕ есть
NO_LIVE_CALL = "no_live_call"       #: не изменился ни в одном тесте ⇒ зова нет
DISTANCE_UNMEASURED = "unmeasured"  #: дописать утверждение некуда / не разобрано
DISTANCES: tuple[str, ...] = (ONE_CLAIM_AWAY, NO_LIVE_CALL, DISTANCE_UNMEASURED)


class Refused(Exception):
    """Предпосылка замера не обеспечена — отказ с названной причиной."""


# ───────────────────────────── составление засева ────────────────────────────


def seed_door(battery_source: str, subject_rel: str) -> tuple[Optional[str], str]:
    """Чем засев способен позвать прибор ИЗ ЭТОЙ батареи, и почему именно так.

    Читается У БАТАРЕИ: привязку приносит она, а не засев. Привязки нет ни
    одной ⇒ `None` с причиной — это `unmeasured`, а не «пробы нет».
    """
    tree = ast.parse(battery_source)
    mods, funcs = kmp.battery_bindings(tree, kmp.subject_keys(subject_rel))
    literals = {node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    if mods:
        return BY_MODULE, f"батарея ввезла модуль как `{sorted(mods)[0]}`"
    if funcs:
        return BY_FUNC, f"батарея ввезла функцию как `{sorted(funcs)[0]}`"
    if subject_rel in literals or pathlib.PurePath(subject_rel).name in literals:
        return BY_PATH, "батарея называет путь прибора строкой"
    return None, ("батарея не ввозит прибор и не называет его путь — засев "
                  "составить нечем, и это НЕ «пробы нет»")


def _call_expr(battery_source: str, subject_rel: str, door: str, root_name: str) -> str:
    tree = ast.parse(battery_source)
    mods, funcs = kmp.battery_bindings(tree, kmp.subject_keys(subject_rel))
    if door == BY_MODULE:
        return f"{sorted(mods)[0]}.measure({root_name})"
    if door == BY_FUNC:
        return f"{sorted(funcs)[0]}({root_name})"
    return (f"__import__('subprocess').run(['python3', {subject_rel!r}], "
            f"cwd={root_name})")


def seed_text(battery_source: str, subject_rel: str, door: str, seed: str) -> str:
    """Текст засева — ОДНА тест-функция, дописываемая в конец батареи."""
    name = _SEED_PREFIX + seed
    if seed == SEED_NO_CALL:
        return (
            f"\n\ndef {name}():\n"
            f"    import pathlib as _zzz_pathlib\n"
            f"    _zzz_root = _zzz_pathlib.Path(__file__).resolve().parents[2]\n"
            f"    assert {SEED_ITEM!r} in str(_zzz_root)\n")
    if seed == SEED_NO_LIVE:
        call = _call_expr(battery_source, subject_rel, door, "_zzz_tmp")
        return (
            f"\n\ndef {name}():\n"
            f"    import tempfile as _zzz_tempfile\n"
            f"    with _zzz_tempfile.TemporaryDirectory() as _zzz_tmp:\n"
            f"        _zzz_answer = {call}\n"
            f"        assert {SEED_ITEM!r} in repr(_zzz_answer)\n")
    call = _call_expr(battery_source, subject_rel, door, "_zzz_root")
    claim = (f"assert {SEED_ITEM!r} in repr(_zzz_answer)"
             if seed == SEED_CANONICAL else "assert _zzz_answer == _zzz_answer")
    return (
        f"\n\ndef {name}():\n"
        f"    import pathlib as _zzz_pathlib\n"
        f"    _zzz_root = _zzz_pathlib.Path(__file__).resolve().parents[2]\n"
        f"    _zzz_answer = {call}\n"
        f"    {claim}\n")


def _stored_names(fn: ast.AST) -> list[str]:
    """Имена, которые тест СВЯЗЫВАЕТ. Утверждение перечисляет их все.

    Перечислить все и дать ответить ДЕТЕКТОРУ — честнее, чем самому решать,
    какое имя происходит от живого ответа: своя копия правил отвечала бы на
    свой вопрос (дословный урок ADR-913 и причина, по которой здесь зовётся
    читатель класса, а не его пересказ).
    """
    out: list[str] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            if node.id not in out and not node.id.startswith("__"):
                out.append(node.id)
    return out


def claim_only_text(fn: ast.AST, source_lines: list[str]) -> Optional[tuple[int, str]]:
    """Строка-утверждение и НОМЕР строки, после которой её дописать.

    Возвращает `None`, если тест не связывает ни одного имени: утверждать тогда
    не о чем, и это НЕ «живого зова нет» — это «дописать некуда».
    """
    names = _stored_names(fn)
    if not names or not getattr(fn, "body", None):
        return None
    first = fn.body[0]
    indent = " " * first.col_offset
    last = fn.body[-1]
    after = getattr(last, "end_lineno", last.lineno)
    if after is None or after > len(source_lines):
        return None
    tup = ", ".join(names)
    return after, f"{indent}assert {SEED_ITEM!r} in repr(({tup},))"


def _seed_claims(battery_source: str, picks) -> Optional[str]:
    """Текст батареи с дописанным утверждением в КАЖДЫЙ из `picks` тестов.

    Вставка идёт СНИЗУ ВВЕРХ: иначе первая же вставка сдвигает номера строк
    остальных, и утверждение уезжает в чужой тест — та же ошибка, что «читать
    состояние один раз при двух писателях».
    """
    lines = battery_source.splitlines()
    made = []
    for fn in picks:
        spot = claim_only_text(fn, lines)
        if spot is not None:
            made.append(spot)
    if not made:
        return None
    for after, claim in sorted(made, key=lambda pair: -pair[0]):
        lines = lines[:after] + [claim] + lines[after:]
    return "\n".join(lines) + "\n"


def claim_trial(repo_root, subject_rel: str, battery_rel: str,
                mat: Optional[Material] = None) -> SeedTrial:
    """Дописать ТОЛЬКО утверждение с именем члена — в тесты батареи.

    Вывод «живой зов в тесте уже есть» законен ровно потому, что засев
    `drops_instrument_call` (утверждение с именем члена БЕЗ зова прибора) не
    меняет исход — и это ИЗМЕРЕНО по каждому члену, а не предположено.

    Порядок двухшаговый НАРОЧНО: сперва один вопрос обо ВСЕЙ батарее (дешёвый),
    и только если он ответил «да» — поимённый поиск теста. Батарей у члена до
    пяти, тестов в батарее до полутора сотен, и поимённый проход по всем ними
    стоил бы минуты там, где ответ «нет» получается за одно чтение.
    """
    mat = mat if mat is not None else material(repo_root, subject_rel, battery_rel)
    if mat.failure:
        return SeedTrial(battery=battery_rel, seed="claim_only", door=None,
                         flipped=None, reason=mat.failure)
    battery_source, subject_source = mat.battery_source, mat.subject_source
    tree = ast.parse(battery_source)
    if mat.already:
        return SeedTrial(battery=battery_rel, seed="claim_only", door=None,
                         flipped=None,
                         reason="проба в батарее УЖЕ есть — дистанцию мерить нечем")
    tests = sorted([node for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name.startswith("test_")], key=lambda n: n.lineno)
    if not tests:
        return SeedTrial(battery=battery_rel, seed="claim_only", door=None,
                         flipped=None, reason="в батарее нет ни одного теста")
    whole = _seed_claims(battery_source, tests)
    if whole is None:
        return SeedTrial(battery=battery_rel, seed="claim_only", door=None,
                         flipped=None,
                         reason=f"ни один из {len(tests)} тестов не связывает имён "
                                "— дописать утверждение некуда")
    try:
        got = kmp.probes_in_battery(whole, battery_rel, subject_rel, subject_source)
    except (SyntaxError, UnicodeDecodeError) as exc:
        return SeedTrial(battery=battery_rel, seed="claim_only", door=None,
                         flipped=None,
                         reason=f"засеянная батарея не разобрана: "
                                f"{type(exc).__name__}: {exc}")
    if not got:
        return SeedTrial(battery=battery_rel, seed="claim_only", door=None,
                         flipped=False,
                         reason=f"утверждение, дописанное во ВСЕ {len(tests)} "
                                "тест(ов), исхода не изменило — живого зова нет")
    named = {p.test for p in got}
    for fn in tests:
        if fn.name not in named:
            continue
        one = _seed_claims(battery_source, [fn])
        if one is None:
            continue
        try:
            solo = kmp.probes_in_battery(one, battery_rel, subject_rel,
                                         subject_source)
        except (SyntaxError, UnicodeDecodeError):
            continue
        if solo:
            return SeedTrial(battery=battery_rel, seed="claim_only", door=None,
                             flipped=True, probe_test=fn.name,
                             probe_form=solo[0].item_form,
                             reason=f"утверждение в `{fn.name}` изменило исход — "
                                    "живой зов прибора в этом тесте УЖЕ есть")
    return SeedTrial(battery=battery_rel, seed="claim_only", door=None, flipped=None,
                     reason="исход изменился при засеве ВСЕХ тестов "
                            f"({sorted(named)}), но ни один тест в одиночку его не "
                            "изменил — назвать виновника нечем")


# ───────────────────────────── один засев ────────────────────────────────────


@dataclass(frozen=True)
class Material:
    """Прочитанное о паре «батарея × прибор» — ОДИН раз на все засевы.

    Кэша здесь нет и быть не должно: объект создаётся на один замер и живёт в
    нём. Модульный кэш пережил бы дерево, и ответ о ВТОРОМ дереве пришёл бы от
    первого — ровно тот класс, против которого написаны приборы рядом.
    """

    battery_source: str
    subject_source: str
    door: Optional[str]
    why: str
    already: bool               #: проба в батарее УЖЕ есть
    failure: Optional[str] = None


def material(repo_root, subject_rel: str, battery_rel: str) -> Material:
    root = pathlib.Path(repo_root)
    try:
        battery_source = (root / battery_rel).read_text(encoding="utf-8")
        subject_source = (root / subject_rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return Material("", "", None, "", False, f"{type(exc).__name__}: {exc}")
    try:
        door, why = seed_door(battery_source, subject_rel)
    except (SyntaxError, UnicodeDecodeError) as exc:
        return Material(battery_source, subject_source, None, "", False,
                        f"батарея не разобрана: {type(exc).__name__}: {exc}")
    try:
        already = bool(kmp.probes_in_battery(battery_source, battery_rel,
                                            subject_rel, subject_source))
    except (SyntaxError, UnicodeDecodeError) as exc:
        return Material(battery_source, subject_source, door, why, False,
                        f"батарея не разобрана: {type(exc).__name__}: {exc}")
    return Material(battery_source, subject_source, door, why, already)


@dataclass(frozen=True)
class SeedTrial:
    """Один засев в одну батарею: изменил ли он исход читателя класса."""

    battery: str
    seed: str
    door: Optional[str]
    flipped: Optional[bool]          #: None = НЕ ИЗМЕРЕНО
    reason: Optional[str] = None
    probe_test: Optional[str] = None
    probe_form: Optional[str] = None


def trial(repo_root, subject_rel: str, battery_rel: str, seed: str,
          mat: Optional[Material] = None) -> SeedTrial:
    """Дописать один засев в одну батарею и спросить ТОТ ЖЕ читатель класса."""
    mat = mat if mat is not None else material(repo_root, subject_rel, battery_rel)
    if mat.failure:
        return SeedTrial(battery=battery_rel, seed=seed, door=mat.door,
                         flipped=None, reason=mat.failure)
    if mat.door is None:
        return SeedTrial(battery=battery_rel, seed=seed, door=None, flipped=None,
                         reason=mat.why)
    if mat.already:
        return SeedTrial(battery=battery_rel, seed=seed, door=mat.door, flipped=None,
                         reason="проба в батарее УЖЕ есть — засевом тут мерить "
                                "нечего, прибор не член класса")
    seeded = mat.battery_source + seed_text(mat.battery_source, subject_rel,
                                            mat.door, seed)
    try:
        after = kmp.probes_in_battery(seeded, battery_rel, subject_rel,
                                      mat.subject_source)
    except (SyntaxError, UnicodeDecodeError) as exc:
        return SeedTrial(battery=battery_rel, seed=seed, door=mat.door, flipped=None,
                         reason=f"засеянная батарея не разобрана: "
                                f"{type(exc).__name__}: {exc}")
    mine = [p for p in after if p.test.startswith(_SEED_PREFIX)]
    alien = [p for p in after if not p.test.startswith(_SEED_PREFIX)]
    if alien:
        return SeedTrial(battery=battery_rel, seed=seed, door=mat.door, flipped=None,
                         reason="засев изменил вердикт о ЧУЖОМ тесте "
                                f"({alien[0].test}) — замер не о засеве")
    return SeedTrial(battery=battery_rel, seed=seed, door=mat.door,
                     flipped=bool(mine),
                     probe_test=mine[0].test if mine else None,
                     probe_form=mine[0].item_form if mine else None)


# ───────────────────────────── перепись ──────────────────────────────────────


@dataclass(frozen=True)
class Row:
    rel: str
    outcome: str
    door: Optional[str] = None
    batteries: tuple[str, ...] = ()
    trials: tuple[SeedTrial, ...] = ()
    reason: Optional[str] = None
    distance: str = DISTANCE_UNMEASURED
    distance_reason: Optional[str] = None
    distance_test: Optional[str] = None


@dataclass
class Census:
    population: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    doors: dict[str, int] = field(default_factory=dict)
    distances: dict[str, int] = field(default_factory=dict)
    rows: list[Row] = field(default_factory=list)
    subjects_source: str = ""


def _distance(claims: Iterable[SeedTrial]) -> tuple[str, Optional[str], Optional[str]]:
    claims = list(claims)
    hit = next((c for c in claims if c.flipped is True), None)
    if hit is not None:
        return ONE_CLAIM_AWAY, hit.reason, hit.probe_test
    measured = [c for c in claims if c.flipped is False]
    if measured:
        return NO_LIVE_CALL, "; ".join(
            f"{c.battery}: {c.reason}" for c in measured), None
    why = next((c.reason for c in claims if c.reason), "причина не названа")
    return DISTANCE_UNMEASURED, why, None


def _verdict(trials: Iterable[SeedTrial]) -> tuple[str, Optional[str]]:
    trials = list(trials)
    canonical = [t for t in trials if t.seed == SEED_CANONICAL]
    defective = [t for t in trials if t.seed in DEFECTIVE_SEEDS]
    loose = [t for t in defective if t.flipped is True]
    if loose:
        t = loose[0]
        return DETECTOR_LOOSE, (
            f"дефектный засев `{t.seed}` ({DROPPED_CONJUNCT[t.seed]}) ИЗМЕНИЛ "
            f"исход в {t.battery} — детектор шире своей докстроки")
    measured = [t for t in canonical if t.flipped is not None]
    if not measured:
        why = next((t.reason for t in canonical if t.reason), "причина не названа")
        return UNMEASURED, f"канонический засев не измерен ни в одной батарее: {why}"
    if any(t.flipped for t in measured):
        return PROBE_ABSENT, None
    return DETECTOR_BLIND, (
        "канонический засев не изменил исход ни в одной из "
        f"{len(measured)} батар(ей) — форма до прибора не достаёт")


def measure(repo_root, subjects: Iterable[str],
            subjects_source: str = "вход") -> Census:
    """Разбиение НАЗВАННОГО перечня приборов по ПРИЧИНЕ отсутствия пробы.

    `subjects` — вход, а не умолчание: перечень есть объявление соседнего
    класса (`spa_core/tests/known_member_probe_baseline.json`), и выдумывать
    его здесь значило бы завести ВТОРОЕ объявление того же класса.
    """
    root = pathlib.Path(repo_root)
    subjects = sorted(set(subjects))
    if not subjects:
        raise Refused(
            "перечень приборов ПУСТ: о причинах отсутствия пробы нечем ответить, "
            "а ноль здесь был бы свойством входа, а не дерева")
    batteries, unparsed = kmp.batteries_of(root, subjects)
    census = Census(population=len(subjects), subjects_source=subjects_source)
    for rel in subjects:
        own = sorted(batteries.get(rel, {}))
        if not own:
            census.rows.append(Row(
                rel=rel, outcome=UNMEASURED,
                reason=("батарея не найдена (род `battery_absent` соседа) — под "
                        "засевом стоят условия 2 и 3, а здесь не обеспечено 1"
                        + (f"; не разобрано {len(unparsed)} файл(ов) батарей"
                           if unparsed else ""))))
            continue
        mats = {battery: material(root, rel, battery) for battery in own}
        trials = tuple(trial(root, rel, battery, seed, mats[battery])
                       for battery in own for seed in SEEDS)
        outcome, reason = _verdict(trials)
        claims = [claim_trial(root, rel, battery, mats[battery]) for battery in own]
        distance, distance_reason, distance_test = _distance(claims)
        doors = {t.door for t in trials if t.door}
        census.rows.append(Row(rel=rel, outcome=outcome,
                               door=sorted(doors)[0] if len(doors) == 1 else
                               ("+".join(sorted(doors)) if doors else None),
                               batteries=tuple(own),
                               trials=trials + tuple(claims), reason=reason,
                               distance=distance, distance_reason=distance_reason,
                               distance_test=distance_test))
    census.counts = {o: sum(1 for r in census.rows if r.outcome == o) for o in OUTCOMES}
    census.distances = {d: sum(1 for r in census.rows if r.distance == d)
                        for d in DISTANCES}
    if sum(census.distances.values()) != census.population:
        raise Refused(
            f"сумма дистанций {sum(census.distances.values())} не равна населению "
            f"{census.population} — вторая ось не замкнута (инв. #17)")
    labels = [r.door or DOOR_NOT_COMPOSED for r in census.rows]
    census.doors = {label: labels.count(label) for label in sorted(set(labels))}
    if sum(census.doors.values()) != census.population:
        raise Refused(
            "ось дверей засева не покрывает население — у строки нет ярлыка "
            "двери, и «не составлен» стал бы неотличим от «не спрошено» (инв. #17)")
    if sum(census.counts.values()) != census.population:
        raise Refused(
            f"сумма исходов {sum(census.counts.values())} не равна населению "
            f"{census.population} — перечень исходов не замкнут (инв. #17)")
    return census


# ───────────────────────────── двусторонняя калибровка ───────────────────────

#: Известные члены стороны «засев ОБЯЗАН изменить исход»: батарея ввозит
#: прибор ИМПОРТОМ, то есть налицо дословно та дверь, которую детектор хвалит.
#: Вычитано руками, адрес двери назван. Не изменил ⇒ неверна форма ЗАСЕВА.
CALIBRATION_FLIP: dict[str, str] = {
    "spa_core/monitoring/delivery_name_loss.py":
        "spa_core/tests/test_delivery_name_loss.py ввозит прибор импортом",
    "spa_core/monitoring/golive_artifact_outcomes.py":
        "spa_core/tests/test_golive_artifact_outcomes.py ввозит прибор импортом",
    "spa_core/tests/_call_wiring.py":
        "spa_core/tests/test_call_wiring.py ввозит помощника импортом",
}

#: Известные НЕ-члены: те же приборы с засевами, снимающими по одному
#: конъюнкту. Исход меняться НЕ ДОЛЖЕН; изменил ⇒ детектор вакуумен.
CALIBRATION_NO_FLIP: tuple[str, ...] = DEFECTIVE_SEEDS


def calibrate(repo_root, subjects: Iterable[str]) -> dict[str, list[str]]:
    """Предъявить известные члены ПО ОБЕ СТОРОНЫ. Потери названы поимённо."""
    root = pathlib.Path(repo_root)
    subjects = set(subjects)
    lost: dict[str, list[str]] = {"flip": [], "no_flip": [], "absent": []}
    for rel, why in sorted(CALIBRATION_FLIP.items()):
        if rel not in subjects:
            lost["absent"].append(f"{rel}: калибровочного прибора нет во входе")
            continue
        batteries = sorted(kmp.batteries_of(root, [rel])[0].get(rel, {}))
        if not batteries:
            lost["absent"].append(f"{rel}: батарей не найдено ({why})")
            continue
        canon = [trial(root, rel, b, SEED_CANONICAL) for b in batteries]
        if not any(t.flipped for t in canon):
            lost["flip"].append(
                f"{rel}: канонический засев исхода НЕ изменил ({why}); "
                + "; ".join(f"{t.battery}: {t.reason or t.flipped}" for t in canon))
        for seed in CALIBRATION_NO_FLIP:
            bad = [t for t in (trial(root, rel, b, seed) for b in batteries)
                   if t.flipped is True]
            if bad:
                lost["no_flip"].append(
                    f"{rel}: дефектный засев `{seed}` "
                    f"({DROPPED_CONJUNCT[seed]}) исход ИЗМЕНИЛ в {bad[0].battery}")
    return lost


def calibrated_measure(repo_root, subjects: Iterable[str],
                       subjects_source: str = "вход") -> Census:
    """Замер, который ОТКАЗЫВАЕТ, пока калибровка не предъявлена целиком."""
    subjects = sorted(set(subjects))
    lost = calibrate(repo_root, subjects)
    if any(lost.values()):
        raise Refused(
            "КАЛИБРОВКА ОПРОВЕРГЛА ФОРМУ ЗАСЕВА — разбиение не печатается:\n  "
            + "\n  ".join(v for key in ("flip", "no_flip", "absent")
                          for v in lost[key]))
    return measure(repo_root, subjects, subjects_source=subjects_source)


# ───────────────────────────── отчёт ─────────────────────────────────────────


def as_json(census: Census) -> dict:
    return {
        "schema": "spa-probe-absence-cause/1",
        "population": census.population,
        "counts": census.counts,
        "doors": census.doors,
        "distances": census.distances,
        "distances_declared": list(DISTANCES),
        "subjects_source": census.subjects_source,
        "outcomes_declared": list(OUTCOMES),
        "precedence": list(PRECEDENCE),
        "seeds_declared": list(SEEDS),
        "rows": [
            {
                "rel": r.rel,
                "outcome": r.outcome,
                "door": r.door,
                "batteries": list(r.batteries),
                "reason": r.reason,
                "distance": r.distance,
                "distance_reason": r.distance_reason,
                "distance_test": r.distance_test,
                "trials": [
                    {"battery": t.battery, "seed": t.seed, "door": t.door,
                     "flipped": t.flipped, "reason": t.reason,
                     "probe_form": t.probe_form}
                    for t in r.trials
                ],
            }
            for r in census.rows
        ],
    }


def format_report(census: Census, limit: int = 60) -> str:
    out = [f"разбиение класса «прибор без пробы ИЗВЕСТНЫЙ ЧЛЕН» по ПРИЧИНЕ "
           f"(население {census.population}, перечень: {census.subjects_source}):"]
    for outcome in OUTCOMES:
        out.append(f"  {outcome}: {census.counts.get(outcome, 0)}")
    out.append("  вторая ось — ДИСТАНЦИЯ до пробы (материал батареи):")
    for distance in DISTANCES:
        out.append(f"    {distance}: {census.distances.get(distance, 0)}")
    near = [r for r in census.rows if r.distance == ONE_CLAIM_AWAY]
    if near:
        out.append(f"  — {ONE_CLAIM_AWAY} ({len(near)}) — живой зов в тесте уже есть, "
                   "нет только имени члена:")
        for r in near[:limit]:
            out.append(f"      {r.rel}: {r.distance_reason}")
    out.append("  двери засева: " + " · ".join(
        f"{d} {n}" for d, n in sorted(census.doors.items()) if n))
    for outcome in (DETECTOR_LOOSE, DETECTOR_BLIND, UNMEASURED):
        named = [r for r in census.rows if r.outcome == outcome]
        if not named:
            continue
        out.append(f"  — {outcome} ({len(named)}):")
        for r in named[:limit]:
            out.append(f"      {r.rel}: {r.reason}")
    absent = [r.rel for r in census.rows if r.outcome == PROBE_ABSENT]
    if absent:
        out.append(f"  — {PROBE_ABSENT} ({len(absent)}): "
                   + ", ".join(absent[:limit])
                   + (" …" if len(absent) > limit else ""))
    out.append("ADVISORY: прибор только ЧИТАЕТ; засев живёт в памяти, байты дерева "
               "не правятся")
    return "\n".join(out)
