#!/usr/bin/env python3
"""Причина провала фазы `call` — перепись по junit-записи прогона (заказ G108 п. 1).

**Зачем (цикл #812, 2026-10-09, ADR-675; заказ поставлен ADR-534 01.10, лежал остатком
восемь суток).** ADR-534 измерил, КУДА уходит время шага тестов, и попутно назвал
население провалов: **61 на фазе `call` и 19 «ошибок»**. Вторую половину он закрыл сам —
девятнадцать «ошибок» оказались ЧЕТЫРЬМЯ сломанными `setUpClass`, то есть число
дефектов там в пять раз меньше числа провалов. Первая половина осталась словом:

> «у провалов фазы `call` общего класса нет, и свести их к числу ДЕФЕКТОВ можно только
> по причине — а она живёт в junit-записи (полный `longrepr`), не в потоковой (там
> первая строка). Мерить надо у junit, когда он есть, и объявлять НЕ ИЗМЕРЕНО, когда
> сессия оборвана».

Почему это не арифметика: «80 провалов» читается как «80 поломок», и на этом числе
принимают решение — брать ли красный набор в работу и сколько это стоит. Замер ниже
говорит, что множитель между провалами и дефектами существует и на фазе `call` тоже.

**Что меряет прибор — ровно одно:** население провалов junit-записи, разложенное по
ТРЁМ закрытым наборам исходов (фаза · опознание причины · опознание места), и число
ПРИЧИН среди провалов фазы `call`. Сумма каждого набора равна населению (инв. #17):
без тождества «свести к причине» отвечается долей от доли, а остаток исчезает молча.

**Ответом служит ВИЛКА, а не одно число.** Механический ключ причины односторонен в
ОБЕ стороны, и обе названы:

* **слияние занижает.** Два `KeyError: 'identity'` из несвязанных модулей ключ склеит
  в одну причину. Поэтому нижний край — не число ключей, а число СВЯЗНЫХ КОМПОНЕНТ
  графа, где ребро ставит либо равенство причины, либо общий НАЗВАННЫЙ след в тексте
  исключения (`<путь>.py:<строка>` внутри самого сообщения). Компонент не больше, чем
  ключей, — значит это нижний край.
* **дробление завышает.** Одна поломка, предъявленная из двух разных тестов, даёт два
  места и два ключа `причина+место`. Поэтому верхний край — число ключей
  `причина+место`.

Ни один край не теорема, и это сказано вслух: причина, предъявленная ДВУМЯ разными
типами исключения и без общего следа, разойдётся на два компонента, то есть нижний
край может оказаться выше истины. Прибор печатает, сколько провалов склеило именно
ребро следа (`merged_by_evidence`) — чтобы цена слияния была числом, а не допущением.

**Фаза `<error>` читается ПРЕФИКСОМ, который печатает сам pytest, и СВЕРЯЕТСЯ со
второй записью.** В junit-XML машинного поля фазы нет вовсе: `<failure>` пишется для
`call`, `<error>` — для установки, разборки и сбора, а что именно случилось, стои́т в
атрибуте `message` литеральным префиксом писателя (`failed on setup with`, …). Разбор
прозы подстрокой запрещён правилом — поэтому префикс здесь не последнее слово: при
переданной потоковой записи (`--stream`) фаза берётся из её МАШИННОГО поля `w`, а
чтение префикса становится проверяемым утверждением (печатаются согласие, расхождение
и «в потоковой записи нет»). Префикс, не совпавший ни с одним известным, даёт
НАЗВАННЫЙ третий исход `phase_unnamed`, а не догадку.

**Нет junit-записи ⇒ НЕ ИЗМЕРЕНО, и это сам ответ.** junit пишется В КОНЦЕ сессии;
оборванная сессия своей записи не оставляет никогда (ADR-474). Замер 08.10 на прогоне
5853 поймал это живьём: у ноги 3.12 `junit-spa_core.xml` есть, у ноги 3.11 его нет —
одна и та же команда, два разных исхода, и выдать второй за «провалов не было» значило
бы нарушить инв. #17 внутри прибора, который этот класс и ловит.

**Ноль провалов — измерено и равно нулю, а не «не измерено».** Запись есть, случаи в
ней есть, провалов нет: третий исход сюда не относится, и различие печатается словами.

Прибор только ЧИТАЕТ: ни одного теста, порога, базы храповика или воркфлоу он не
трогает. Коды возврата: **0** — измерено (в том числе ноль провалов) · **2** — НЕ
ИЗМЕРЕНО с названной причиной. Только stdlib (инв. #4).
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, NamedTuple

# --- исходы чтения записи (контракт, читается тестами) --------------------------
READ_OK = "read"
READ_ABSENT = "record_absent"
READ_UNREADABLE = "record_unreadable"
READ_NO_SUITE = "no_testsuite"
READ_NO_CASES = "no_testcases"

# --- закрытый набор фаз --------------------------------------------------------
PHASE_CALL = "call"
PHASE_SETUP = "setup"
PHASE_TEARDOWN = "teardown"
PHASE_COLLECT = "collect"
PHASE_UNNAMED = "phase_unnamed"
#: Обморок САМОЙ сессии pytest — не фаза теста, а его отсутствие: тест не доигран ни
#: в одной фазе, потому что сессия, которая его гоняла, умерла. Род объявлен ОТДЕЛЬНЫМ
#: именем ровно поэтому: до ADR-892 запись обморока получала `phase_unnamed` и стояла
#: среди провалов тестов, а «тип не назван» у неё читалось как «причину не нашли».
PHASE_SESSION = "session_death"
PHASES = (PHASE_CALL, PHASE_SETUP, PHASE_TEARDOWN, PHASE_COLLECT, PHASE_SESSION,
          PHASE_UNNAMED)

#: Имя, которым писатель junit (`_pytest/junitxml.py`) называет ВНУТРЕННЮЮ смерть
#: сессии: `<testcase classname="pytest" name="internal">`. Литерал ЧУЖОГО кода, не
#: проза отчёта. Тестом эта запись не является вовсе, и считать её «падением, которого
#: отчёт не числит упавшим» значит утверждать спор там, где записи СОГЛАСНЫ.
SESSION_RECORD = "pytest::internal"

#: Метка, которой `run_shard` (`scripts/ci_control.py`) помечает поле `w` потоковой
#: записи у теста, ПОД КОТОРЫМ сессия умерла. Это вторая, МАШИННАЯ дверь к тому же
#: событию: она называет ЖЕРТВУ, тогда как junit называет сам обморок.
STREAM_INTERNAL = "internal"

# Префиксы, которые печатает САМ писатель junit у элемента <error>. Это литералы
# чужого кода, не проза отчёта; несовпадение даёт PHASE_UNNAMED, а не догадку.
_ERROR_PREFIXES = (
    ("failed on setup", PHASE_SETUP),
    ("test setup failure", PHASE_SETUP),
    ("failed on teardown", PHASE_TEARDOWN),
    ("test teardown failure", PHASE_TEARDOWN),
    ("collection failure", PHASE_COLLECT),
    ("collection error", PHASE_COLLECT),
)

# --- закрытый набор исходов опознания причины ----------------------------------
CAUSE_NAMED = "cause_named"
CAUSE_NO_TYPE = "cause_no_exception_type"
CAUSE_NO_MESSAGE = "cause_no_message"
CAUSE_CLASSES = (CAUSE_NAMED, CAUSE_NO_TYPE, CAUSE_NO_MESSAGE)

# --- РОД «обморок по стенным часам» (ADR-910) ---------------------------------
# Провал по `pytest-timeout` НЕ ЕСТЬ дефект предмета теста — это свойство СТЕННЫХ
# ЧАСОВ, и его состав РОТИРУЕТСЯ при постоянном числе. Замер цикла #1024 на двух
# живых прогонах контрольного набора:
#
#   | прогон                      | всего | род часов | дефектная часть |
#   |-----------------------------|-------|-----------|-----------------|
#   | 41707593049 (`7cb79c8c6`)   |  65   |     4     |       61        |
#   | 41653552215 (`76c050ab4`)   |  65   |     4     |       61        |
#
# Нетто-число не изменилось, а ПО ИМЕНАМ дельта есть: одно имя пришло, одно ушло,
# и ОБА лежат в роде часов. У дефектной части симметричная разность ПУСТА в обе
# стороны — то есть весь наблюдаемый сдвиг красного набора произвела загрузка
# машины, а не код. До ADR-910 эти четыре имени стояли ВНУТРИ вилки дефектов
# (`population=65`, `upper=65`), и читатель, решающий «брать ли набор в работу»,
# считал лотерею загрузки четырьмя поломками.
#
# Род объявлен ОТДЕЛЬНЫМ именем по тому же праву, что и обморок сессии (ADR-892):
# у жертвы причина ЕСТЬ, и причина эта — не дефект теста. Это НЕ значит «не
# дефект вовсе»: ADR-894 измерил случай, идущий 433.46 с против предела 180 с, —
# он не может пройти на шарде ПО ПОСТРОЕНИЮ, и это дефект ДЛИТЕЛЬНОСТИ. Поэтому
# род не выбрасывается, а НАЗЫВАЕТСЯ ПОИМЁННО рядом с вилкой: смешивать его с
# дефектами предмета значит отвечать одним числом на два разных вопроса.
#
#: Дословный шаблон САМОГО pytest-timeout: `pytest_timeout.PYTEST_FAILURE_MESSAGE
#: = "Timeout (>%ss) from pytest-timeout."`. Литерал ЧУЖОГО кода, а не проза
#: отчёта: его печатает производитель срока, и совпадение с ним есть улика, а не
#: догадка по слову «timeout».
_TIMEOUT_SENTENCE = re.compile(r"Timeout \(>\d+(?:\.\d+)?s\) from pytest-timeout\.")

#: Обёртки, которыми ЧУЖОЙ текст оборачивают писатель junit и сам pytest. Перечень
#: ЗАКРЫТ намеренно: снимается ровно то, что печатает чужой код, — иначе правило
#: превратилось бы в «всё до двоеточия», и `AssertionError: …` с фразой внутри
#: стал бы родом часов.
_ROD_UNWRAPS = (
    re.compile(r'^failed on (?:setup|teardown) with "(?P<inner>.*)"$'),
    re.compile(r'^test (?:setup|teardown) failure:?\s*(?P<inner>.*)$'),
    re.compile(r"^Failed:\s*(?P<inner>.*)$"),
)

ROD_TIMEOUT = "wallclock_timeout"
ROD_NONE = "not_wallclock"
#: Сообщения нет вовсе ⇒ вопрос «это род часов?» НЕ ОТВЕЧЕН. Записать здесь
#: `ROD_NONE` значило бы выдать «не измерено» за «измерено и нет» (инв. #17), а
#: это ровно та подмена, против которой заведён сам род.
ROD_UNMEASURED = "rod_unmeasured"
ROD_CLASSES = (ROD_TIMEOUT, ROD_NONE, ROD_UNMEASURED)


def timeout_rod_of(message: str) -> str:
    """Род провала по стенным часам — один из :data:`ROD_CLASSES`.

    Правило — РАВЕНСТВО остатка предложению производителя, а НЕ вхождение
    подстроки (ADR-333). Разница существенна и измерена: в этом наборе есть тесты,
    чей предмет — сам сторож зависаний, и их собственные сообщения фразу
    упоминают. Проверка на вхождение объявила бы их родом часов и вынесла
    настоящий дефект из вилки — то есть ослабила бы вердикт, прикрывшись
    усилением (инв. #16).

    Обёртки снимаются по ЗАКРЫТОМУ перечню (:data:`_ROD_UNWRAPS`) и до неподвижной
    точки: писатель junit у фазы `setup` оборачивает текст дважды
    (``failed on setup with "Failed: Timeout (>180.0s) from pytest-timeout."``).

    **Чего мера НЕ различает, и это сказано вслух.** Случай, который сам зовёт
    ``pytest.fail`` с ДОСЛОВНЫМ предложением производителя, неотличим от
    настоящего срока: сообщение байт в байт одно. Замер цикла #1024 по всему
    дереву (`spa_core`, `scripts`, `tests`, `studio_shell`, `research`): таких
    вызовов **НОЛЬ** — фраза встречается только в комментариях и в фикстурах
    этой же батареи. Цена правила сегодня измерена и равна нулю.
    """
    text = (message or "").strip()
    head = text.splitlines()[0] if text else ""
    if not head:
        return ROD_UNMEASURED
    body = head.strip()
    for _ in range(len(_ROD_UNWRAPS) + 1):
        for pattern in _ROD_UNWRAPS:
            hit = pattern.match(body)
            if hit:
                body = hit.group("inner").strip()
                break
        else:
            break
    return ROD_TIMEOUT if _TIMEOUT_SENTENCE.fullmatch(body) else ROD_NONE


# --- закрытый набор исходов опознания места ------------------------------------
SITE_REPO = "site_repo_frame"
SITE_FOREIGN = "site_only_foreign_frames"
SITE_NONE = "site_no_frames"
SITE_CLASSES = (SITE_REPO, SITE_FOREIGN, SITE_NONE)

# Кадр `--tb=short`: «путь:строка: in имя».
_FRAME = re.compile(r"^(?P<file>[^\s][^:]*):(?P<line>\d+): in (?P<func>.+)$")

# Строку текста исключения pytest помечает `E` в первой позиции. Её надо отбросить
# ДО разбора кадров, и это не украшение: в этом наборе полно тестов, которые гоняют
# дочерний pytest и судят по его выводу, а вывод несёт кадры ЧУЖОГО прогона. Якорь
# `^` их не отсекает — `[^:]*` съедает и `E`, и пробелы, поэтому `E   a/b.py:9: in f`
# разбирается как кадр с «файлом» `E   a/b.py` (замер цикла #812 на собственном
# контроле). Место провала тогда берётся у чужого прогона, и верхний край вилки
# дробится по ложному признаку.
_ERROR_TEXT_LINE = re.compile(r"^E(\s|$)")

# Чужой кадр: интерпретатор и его пакеты. Путь репозитория относителен по построению
# (pytest печатает его от rootdir), чужой — абсолютен либо лежит в site-packages.
_FOREIGN = ("/site-packages/", "/hostedtoolcache/", "/lib/python", "<frozen ")

# Тип исключения в голове сообщения: «Имя: …» либо «пакет.Имя: …».
_EXC_HEAD = re.compile(r"^(?P<kind>[A-Za-z_][\w.]*(?:\.[A-Za-z_]\w*)*)\s*:\s")

# Названный след внутри САМОГО сообщения исключения (не в кадрах): место, на которое
# жалуется проваленное утверждение. Ребро графа ставится именно по нему.
_EVIDENCE = re.compile(r"[\w./-]*[\w-]\.py:\d+")

# Нормализация сообщения в скелет причины. ДВА набора, и различие между ними — это
# и есть измеренная цена слияния: кавычки несут ИМЯ (у `KeyError: \'identity\'` имя ключа
# и есть причина), поэтому грубый скелет их стирает и склеивает, а точный сохраняет.
# Порядок внутри набора существен: кавычки сперва, иначе путь внутри кавычек уже
# заменён и перестаёт быть путём.
_SUBS_LITERALS = (
    (re.compile(r"'[^']*'"), "'…'"),
    (re.compile(r'"[^"]*"'), '"…"'),
)
_SUBS_COMMON = (
    (re.compile(r"[\w./-]*[\w-]\.(?:py|json|jsonl|md|yml|yaml|xml|sh|txt)\b"), "<путь>"),
    (re.compile(r"\b[0-9a-f]{8,}\b"), "<hash>"),
    (re.compile(r"\d+(?:[.,]\d+)?"), "#"),
)
_SKELETON_MAX = 120


class Failure(NamedTuple):
    """Один провал записи. ``kind`` = ``None`` ⇒ тип исключения не опознан."""

    classname: str
    name: str
    tag: str                    # failure | error
    phase: str                  # из PHASES
    message: str                # атрибут message, как есть
    kind: str | None            # тип исключения
    skeleton: str               # точный скелет сообщения (кавычки сохранены)
    coarse: str                 # грубый скелет (кавычки стёрты) — ключ слияния
    site: str | None            # глубочайший кадр репозитория «файл:строка»
    frames: int                 # сколько кадров разобрано
    foreign_frames: int
    evidence: frozenset[str]    # названные следы внутри сообщения

    @property
    def nodeid(self) -> str:
        return f"{self.classname}::{self.name}" if self.classname else self.name

    @property
    def is_session_death(self) -> bool:
        """Эта запись — обморок САМОЙ сессии, а не провал теста (ADR-892)."""
        return self.nodeid == SESSION_RECORD

    @property
    def timeout_rod(self) -> str:
        """Род «обморок по стенным часам» (ADR-910) — один из :data:`ROD_CLASSES`.

        Стои́т рядом с :attr:`is_session_death` по тому же праву: оба отвечают не
        «какая причина», а «причина КАКОГО РОДА», и оба выводят своё население из
        вилки дефектов предмета.
        """
        return timeout_rod_of(self.message)

    @property
    def cause_class(self) -> str:
        if not self.message.strip():
            return CAUSE_NO_MESSAGE
        return CAUSE_NAMED if self.kind else CAUSE_NO_TYPE

    @property
    def site_class(self) -> str:
        if self.site:
            return SITE_REPO
        return SITE_FOREIGN if self.foreign_frames else SITE_NONE

    @property
    def cause_key(self) -> tuple[str, str]:
        return (self.kind or "«тип не назван»", self.skeleton)

    @property
    def coarse_key(self) -> tuple[str, str]:
        return (self.kind or "«тип не назван»", self.coarse)

    @property
    def cause_site_key(self) -> tuple[str, str, str]:
        return (*self.cause_key, self.site or "«место не названо»")


class Census(NamedTuple):
    """Итог переписи одной junit-записи. ``read != READ_OK`` ⇒ числа бессмысленны."""

    read: str
    reason: str
    path: str
    collected: int                        # <testcase> всего
    failures: tuple[Failure, ...]
    # сверка фазы со второй записью
    stream_agreed: int
    stream_disagreed: int
    stream_absent_for: int
    stream_read: str | None
    #: junit-имена тестов, под которыми СЕССИЯ умерла (поле `w` == STREAM_INTERNAL).
    #: Пустой набор при прочитанной потоковой записи есть «измерено и равно нулю»;
    #: при `stream_read is None` — «не спрошено», и различает их `stream_read`.
    session_victims: tuple[str, ...] = ()

    # --- тождества учёта (инв. #17) ---
    @property
    def population(self) -> int:
        return len(self.failures)

    @property
    def session_record(self) -> "Failure | None":
        """Запись обморока сессии, если она в этом junit есть. Свойство, не поле:
        второе поле с тем же содержимым разошлось бы с `failures` молча."""
        for failure in self.failures:
            if failure.is_session_death:
                return failure
        return None

    def by_phase(self) -> Counter:
        return Counter(f.phase for f in self.failures)

    def by_cause_class(self) -> Counter:
        return Counter(f.cause_class for f in self.failures)

    def by_site_class(self) -> Counter:
        return Counter(f.site_class for f in self.failures)

    def identities_hold(self) -> bool:
        """Сумма ОБЪЯВЛЕННЫХ имён набора равна населению.

        Сумма значений самого счётчика равнялась бы населению ВСЕГДА — такое
        тождество неопровержимо, то есть не является проверкой. Считать надо по
        перечню имён, который печатается читателю: род, в перечень не попавший,
        исчезает из строки молча, и именно это обязано краснеть.
        """
        n = self.population
        phase, cause, site = self.by_phase(), self.by_cause_class(), self.by_site_class()
        return (sum(phase.get(k, 0) for k in PHASES) == n
                and sum(cause.get(k, 0) for k in CAUSE_CLASSES) == n
                and sum(site.get(k, 0) for k in SITE_CLASSES) == n)

    @property
    def call(self) -> tuple[Failure, ...]:
        return tuple(f for f in self.failures if f.phase == PHASE_CALL)

    @property
    def measured(self) -> bool:
        return self.read == READ_OK


# --- РОД «ОКРУЖЕНИЕ РАННЕРА» (ADR-915, заказ G905 п. 1) ------------------------
# Второй род того же семейства, что и род стенных часов выше, и заводится он по той
# же причине и тем же способом. Замер #1027 (ADR-913) прогнал дефектную часть
# (56 имён) ПОИМЁННО на чистом дереве того же коммита: **19 из 56 ЗЕЛЕНЫ у себя**,
# двумя независимыми наблюдениями, 19 из 19. Эти имена дефектами кода не являются —
# их краснота есть свойство МАШИНЫ (PID-пространство, `ps`, права, контейнер, набор
# инструментов), и держать их в вилке дефектов значит завышать её.
#
# **Опубликованная вилка противоречила САМА СЕБЕ, и это измерено.** Прибор печатал
# «дефектов НЕ МЕНЬШЕ 42 и НЕ БОЛЬШЕ 56», а дефектная часть после вычета
# девятнадцати — 37: `42 > 37`. Нижний край считан по ВСЕМУ набору, и девятнадцать
# имён, падающих от свойств машины, дали прибору девятнадцать «причин дефекта».
# Лечение — то же, что у ADR-910: вывод рода стои́т у ЕДИНСТВЕННОЙ двери `fork_of`,
# а не у каждого из трёх читателей вилки.
#
# **Чем этот род отличается от рода часов — своим источником.** Род часов опознаётся
# по СООБЩЕНИЮ самого провала (литерал производителя срока). Здесь сообщения не
# хватает: «зелен на своём дереве» не написано в тексте исключения и не может быть
# там написано — это вердикт ЗАМЕРА, а не свойство строки. Поэтому источник — ВНЕШНЕЕ
# ОБЪЯВЛЕНИЕ, то самое, которое доставил ADR-913 и которое держит сторож
# `spa_core/tests/test_ci_only_red_class_ratchet.py`.
#
# **Отсюда третий исход, и он fail-CLOSED (дословно правило ADR-910).** Объявления
# нет / не разбирается / схема чужая / имя члена не строка ⇒ род НЕ ИЗМЕРЕН, и
# НИ ОДНО падение из вилки не выносится. Недоказанный род не вправе уменьшать число
# дефектов: иначе «объявление потерялось» работало бы как оправдание (инв. #17).

#: Файл ОБЪЯВЛЕНИЯ класса. Одна копия пути на всю систему.
ENV_DECLARATION = (Path(__file__).resolve().parents[2]
                   / "spa_core" / "tests" / "ci_only_red_class_baseline.json")

#: Схема объявления. Писателя-модуля у неё нет (замер делается разовым прибором
#: цикла, ADR-913 §5); читателей ДВА — этот и сторож объявления, — и их согласие
#: закреплено проверкой паритета, а не надеждой (`test_runner_env_rod_subtraction`).
ENV_SCHEMA = "ci-only-red-class/1"

ENV_READ_OK = "env_declaration_read"
ENV_ABSENT = "env_declaration_absent"
ENV_UNREADABLE = "env_declaration_unreadable"
ENV_BAD_SCHEMA = "env_declaration_foreign_schema"
ENV_NO_MEMBERS = "env_declaration_without_members"
ENV_BAD_MEMBER = "env_declaration_member_without_name"
ENV_NAME_COLLISION = "env_declaration_names_collapsed"
#: Рода НЕ СПРАШИВАЛИ вовсе — состояние руками собранной :class:`Fork`. Отличается
#: от «спросили и объявления не нашли» и от «вычли»: три разных ответа, три имени.
ENV_NOT_ASKED = "env_declaration_not_asked"
ENV_CLASSES = (ENV_READ_OK, ENV_ABSENT, ENV_UNREADABLE, ENV_BAD_SCHEMA,
               ENV_NO_MEMBERS, ENV_BAD_MEMBER, ENV_NAME_COLLISION, ENV_NOT_ASKED)


class EnvDeclaration(NamedTuple):
    """Прочитанное объявление класса «красен в CI, зелен на своём дереве».

    ``names`` — имена В ФОРМЕ junit-записи, то есть уже приведённые единственной
    дверью :func:`junit_name`. Объявление пишет `nodeid` в форме pytest
    (`путь/к/файлу.py::Класс::тест`), а провал записи несёт форму junit
    (`путь.к.файлу.Класс::тест`); сверка двух форм без канонизации дала бы ПУСТОЕ
    пересечение и прочиталась бы как «класса в наборе нет» (дословный урок цикла
    #1026: артефакт канонизатора подделал дельту «пришло 47 / ушло 43» вместо 1 и 2).
    """

    read: str
    reason: str
    path: str
    names: frozenset[str] = frozenset()
    declared: int = 0

    @property
    def measured(self) -> bool:
        return self.read == ENV_READ_OK


def env_declaration(path: Path | None = None) -> EnvDeclaration:
    """Прочитать объявление рода «окружение раннера». Только ЧИТАЕТ.

    Путь берётся аргументом, а умолчание разрешается ВНУТРИ, а не значением по
    умолчанию в подписи: значение по умолчанию привязывается в момент определения
    функции, поэтому подмена модульного :data:`ENV_DECLARATION` на него НЕ
    ДЕЙСТВОВАЛА БЫ — сцена контроля молча мерила бы боевой файл и зеленела бы,
    ничего не проверив (дословно урок `load_declaration` сторожа объявления).

    Любая невозможность прочитать даёт НАЗВАННЫЙ исход и ПУСТОЙ набор имён, и
    этого достаточно для fail-CLOSED: пустой набор не выносит из вилки ничего.
    Пустое объявление при этом НЕ выдаётся за «класс пуст» — на это отвечает поле
    :attr:`EnvDeclaration.read`, а не размер набора.
    """
    path = ENV_DECLARATION if path is None else path
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return EnvDeclaration(read=ENV_ABSENT, path=str(path),
                              reason=f"файла объявления нет: {path}")
    except OSError as exc:
        return EnvDeclaration(read=ENV_UNREADABLE, path=str(path),
                              reason=f"объявление не прочитано: {path}: {exc}")
    try:
        doc = json.loads(raw)
    except ValueError as exc:
        return EnvDeclaration(read=ENV_UNREADABLE, path=str(path),
                              reason=f"объявление не разбирается: {path}: {exc}")
    if not isinstance(doc, dict):
        return EnvDeclaration(read=ENV_BAD_SCHEMA, path=str(path),
                              reason=f"объявление не словарь: {type(doc).__name__}")
    if doc.get("schema") != ENV_SCHEMA:
        return EnvDeclaration(
            read=ENV_BAD_SCHEMA, path=str(path),
            reason=(f"схема объявления {doc.get('schema')!r} != {ENV_SCHEMA!r} — "
                    "читатель и писатель разошлись, и молчать об этом нельзя"))
    members = doc.get("members")
    if not isinstance(members, list):
        return EnvDeclaration(
            read=ENV_NO_MEMBERS, path=str(path),
            reason=(f"поля `members` нет или оно не список: "
                    f"{type(members).__name__}"))
    raw_names = []
    for member in members:
        nodeid = member.get("nodeid") if isinstance(member, dict) else None
        if not isinstance(nodeid, str) or not nodeid.strip():
            return EnvDeclaration(
                read=ENV_BAD_MEMBER, path=str(path),
                reason=("у члена объявления нет поля `nodeid` строкой — объявление "
                        "разобрано НЕ ЦЕЛИКОМ, и вычитать по его части нельзя"))
        raw_names.append(junit_name(nodeid.strip()))
    names = frozenset(raw_names)
    # Предпосылка сверки объявлена: имён обязано выйти столько, сколько членов.
    # Схлопнулись два имени в одно ⇒ канонизатор или объявление неисправны, и
    # вычитать по такому набору значило бы вынести из вилки неизвестно что.
    if len(names) != len(raw_names):
        return EnvDeclaration(
            read=ENV_NAME_COLLISION, path=str(path),
            reason=(f"объявлено членов {len(raw_names)}, а различных имён вышло "
                    f"{len(names)} — предпосылка сверки НЕ ВЫПОЛНЕНА"))
    return EnvDeclaration(read=ENV_READ_OK, path=str(path),
                          reason="объявление прочитано", names=names,
                          declared=len(raw_names))


class Fork(NamedTuple):
    """Вилка числа дефектов по населению одной фазы. Края НАЗВАНЫ, не выведены."""

    population: int             # ДЕФЕКТНОЕ население: род стенных часов СЮДА НЕ ВХОДИТ
    cause_groups: int           # ключей «тип + точный скелет»
    coarse_groups: int          # ключей «тип + грубый скелет» (кавычки стёрты)
    lower: int                  # связные компоненты (слияние)
    upper: int                  # ключи «причина+место» (дробление)
    merged_by_evidence: int     # провалов, склеенных ребром следа сверх равенства причин
    largest_component: int
    groups: tuple[tuple[tuple[str, str], int], ...]
    # --- род стенных часов (ADR-910): выведен из вилки и НАЗВАН ----------------
    wallclock_timeouts: int = 0
    wallclock_names: tuple[str, ...] = ()
    #: Провалов, у которых вопрос о роде НЕ ОТВЕЧЕН (сообщения нет вовсе). Они
    #: остаются В ДЕФЕКТНОМ населении — fail-CLOSED: недоказанный род часов не
    #: вправе выносить провал из вилки, иначе «не измерено» работало бы как
    #: оправдание (инв. #17).
    rod_unmeasured: int = 0
    # --- род окружения раннера (ADR-915): выведен из вилки и НАЗВАН ----------
    #: Провалов, вынесенных из вилки по ОБЪЯВЛЕНИЮ одиннадцатой двери (ADR-913):
    #: имя красно в контрольном прогоне CI и ЗЕЛЕНО на своём дереве той же вершины.
    runner_environment: int = 0
    runner_environment_names: tuple[str, ...] = ()
    #: Исход чтения объявления — один из :data:`ENV_CLASSES`. Умолчание —
    #: ``ENV_NOT_ASKED``, то есть «род НЕ ИЗМЕРЕН»: руками собранная вилка не
    #: вправе утверждать вычитание, которого не делала (инв. #17).
    runner_env_read: str = ENV_NOT_ASKED
    runner_env_reason: str = "род окружения раннера не спрашивали"

    @property
    def measured_runner_env(self) -> bool:
        """Объявление рода окружения прочитано. Нет ⇒ род НЕ ИЗМЕРЕН (fail-CLOSED)."""
        return self.runner_env_read == ENV_READ_OK

    @property
    def accounting_holds(self) -> bool:
        """``population + wallclock_timeouts + runner_environment == given``.

        Тождество печатается читателями, а не считается ими: род, забытый одним из
        трёх печатающих мест, исчезал бы из его строки молча (класс ADR-220).
        """
        return (self.population + self.wallclock_timeouts
                + self.runner_environment == self.given)
    #: Сколько провалов ПОДАНО на вход. Тождество учёта:
    #: ``population + wallclock_timeouts + runner_environment == given``. Без него
    #: род, забытый читателем, исчезал бы из печатаемой строки молча (урок ADR-675).
    given: int = 0


def _unreadable(kind: str, reason: str, path: str) -> Census:
    return Census(read=kind, reason=reason, path=path, collected=0, failures=(),
                  stream_agreed=0, stream_disagreed=0, stream_absent_for=0,
                  stream_read=None)


def skeleton_of(message: str, *, erase_literals: bool = False) -> str:
    """Скелет сообщения: пути, хэши и числа заменены на род.

    ``erase_literals=True`` стирает ещё и содержимое кавычек — это ГРУБЫЙ скелет,
    которым ставится ребро слияния. Он склеивает `KeyError: \'identity\'` с
    `KeyError: \'verdict\'`, то есть заведомо занижает; цена этого склеивания и есть
    то, что печатается вилкой, а не прячется в выборе одного ключа.

    Берётся ПЕРВАЯ строка: дальше у `--tb=short` идёт развёрнутое сравнение, и оно
    меняется у каждого случая, из-за чего один дефект разошёлся бы на столько причин,
    сколько у него проваленных утверждений.
    """
    head = (message or "").strip().splitlines()[0] if (message or "").strip() else ""
    body = head
    exc = _EXC_HEAD.match(body)
    if exc:
        body = body[exc.end():]
    for pattern, placeholder in (_SUBS_LITERALS if erase_literals else ()) + _SUBS_COMMON:
        body = pattern.sub(placeholder, body)
    body = re.sub(r"\s+", " ", body).strip()
    return body[:_SKELETON_MAX]


def kind_of(message: str) -> str | None:
    """Тип исключения из головы сообщения. Нет головы ⇒ ``None``, а не «unknown»."""
    head = (message or "").strip().splitlines()[0] if (message or "").strip() else ""
    exc = _EXC_HEAD.match(head)
    return exc.group("kind") if exc else None


def phase_of(tag: str, message: str) -> str:
    """Фаза провала по элементу junit.

    ``<failure>`` писатель junit ставит ТОЛЬКО фазе `call`; у ``<error>`` фазу несёт
    литеральный префикс сообщения. Неизвестный префикс ⇒ PHASE_UNNAMED.
    """
    if tag == "failure":
        return PHASE_CALL
    low = (message or "").strip().lower()
    for prefix, phase in _ERROR_PREFIXES:
        if low.startswith(prefix):
            return phase
    return PHASE_UNNAMED


def frames_of(text: str) -> tuple[list[tuple[str, int]], int]:
    """Кадры `--tb=short`: (кадры репозитория, число чужих кадров)."""
    mine: list[tuple[str, int]] = []
    foreign = 0
    for line in (text or "").splitlines():
        if _ERROR_TEXT_LINE.match(line):
            continue
        hit = _FRAME.match(line.rstrip())
        if not hit:
            continue
        path = hit.group("file")
        if any(mark in path for mark in _FOREIGN) or path.startswith("/"):
            foreign += 1
        else:
            mine.append((path, int(hit.group("line"))))
    return mine, foreign


def evidence_of(message: str) -> frozenset[str]:
    """Названные следы внутри сообщения исключения.

    Кадры сюда не попадают по построению: читается атрибут ``message``, а кадры
    живут в теле элемента. Иначе ребро графа ставил бы путь самого теста, и граф
    склеил бы всё, что упало в одном файле.
    """
    return frozenset(_EVIDENCE.findall(message or ""))


def exception_tail(text: str) -> str:
    """Последняя строка тела записи, несущая тип исключения. Нет такой ⇒ ``""``.

    Нужна РОВНО одному роду — обмороку сессии (ADR-892). У него атрибут ``message``
    есть литерал ``internal error`` и типа не несёт ВОВСЕ, а настоящее исключение
    стои́т в ХВОСТЕ трассы (замер прогона 41318580149, шард 7: ``TypeError:
    unsupported operand type(s) for -: 'NoneType' and 'int'`` в ``_pytest/_code/
    code.py:214``). Брать ГОЛОВУ тела нельзя: голова — кадры `pluggy`, а не причина;
    отсюда и «последняя», а не «первая».

    Строка текста исключения (`E ...`) отбрасывается той же мерой, что в
    :func:`frames_of`: у обморока её не бывает, но правило одно на оба читателя.
    """
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if not line or _ERROR_TEXT_LINE.match(line):
            continue
        if _EXC_HEAD.match(line):
            return line
    return ""


def _failure_from(classname: str, name: str, tag: str, message: str, text: str) -> Failure:
    mine, foreign = frames_of(text)
    nodeid = f"{classname}::{name}" if classname else name
    # Обморок сессии: причину несёт ХВОСТ тела, а не `message` (см. exception_tail).
    # Фаза ему тоже не присваивается разбором префикса — у события нет фазы теста.
    session = nodeid == SESSION_RECORD
    source = exception_tail(text) if session else (message or "")
    return Failure(
        classname=classname, name=name, tag=tag,
        phase=(PHASE_SESSION if session else phase_of(tag, message)),
        message=message or "",
        kind=kind_of(source), skeleton=skeleton_of(source),
        coarse=skeleton_of(source, erase_literals=True),
        site=(f"{mine[-1][0]}:{mine[-1][1]}" if mine else None),
        frames=len(mine), foreign_frames=foreign,
        evidence=evidence_of(source),
    )


def census_from_path(path: Path, *, stream: Path | None = None) -> Census:
    """Перепись одной junit-записи. Файла нет ⇒ READ_ABSENT (это сам ответ)."""
    if not path.exists():
        return _unreadable(READ_ABSENT, f"junit-записи нет по пути {path}", str(path))
    try:
        root = ET.parse(str(path)).getroot()
    except ET.ParseError as exc:
        return _unreadable(READ_UNREADABLE, f"junit-запись не разобрана: {exc}", str(path))
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites:
        return _unreadable(READ_NO_SUITE, "в записи нет ни одного <testsuite>", str(path))
    collected = 0
    failures: list[Failure] = []
    for suite in suites:
        for case in suite.iter("testcase"):
            collected += 1
            for child in case:
                if child.tag not in ("failure", "error"):
                    continue
                failures.append(_failure_from(
                    case.attrib.get("classname", ""), case.attrib.get("name", ""),
                    child.tag, child.attrib.get("message", ""), child.text or "",
                ))
    if collected == 0:
        return _unreadable(READ_NO_CASES, "в записи нет ни одного <testcase>", str(path))
    agreed = disagreed = absent_for = 0
    stream_read: str | None = None
    victims: tuple[str, ...] = ()
    if stream is not None:
        phases, stream_read = stream_phases(stream)
        victims = tuple(sorted(n for n, w in phases.items() if w == STREAM_INTERNAL))
        for failure in failures:
            # Обморок сессии в сверку фаз НЕ входит: потоковой строки у него нет ПО
            # ПОСТРОЕНИЮ (он не тест, и `run_shard` строки `fail` ему не пишет).
            # Считать его «провалом, которого во второй записи нет» значило бы
            # смешать ожидаемое отсутствие с настоящей дырой записи.
            if failure.is_session_death:
                continue
            observed = phases.get(failure.nodeid)
            if observed is None:
                absent_for += 1
            elif observed == failure.phase:
                agreed += 1
            else:
                disagreed += 1
    return Census(read=READ_OK, reason="запись прочитана", path=str(path),
                  collected=collected, failures=tuple(failures),
                  stream_agreed=agreed, stream_disagreed=disagreed,
                  stream_absent_for=absent_for, stream_read=stream_read,
                  session_victims=victims)


def stream_phases(path: Path) -> tuple[dict[str, str], str]:
    """Фаза провала из МАШИННОГО поля `w` потоковой записи, ключ — junit-имя.

    Имя потоковой записи (`путь/файл.py::Класс::тест`) приводится к паре
    junit (`пакет.файл.Класс`, `тест`): сверять надо одно и то же имя, иначе
    «в записи нет» получалось бы у каждого провала и сверка молча опустела бы.
    """
    if not path.exists():
        return {}, READ_ABSENT
    out: dict[str, str] = {}
    seen = 0
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict) or event.get("e") != "fail":
                    continue
                seen += 1
                nodeid, phase = event.get("n"), event.get("w")
                if not isinstance(nodeid, str) or not isinstance(phase, str):
                    continue
                out[_junit_name(nodeid)] = phase
    except OSError as exc:
        return {}, f"{READ_UNREADABLE}: {exc}"
    return out, (READ_OK if seen else READ_NO_CASES)


def _junit_name(nodeid: str) -> str:
    parts = nodeid.split("::")
    module = parts[0]
    if module.endswith(".py"):
        module = module[:-3]
    module = module.replace("/", ".")
    if len(parts) == 1:
        return module
    classname = ".".join([module, *parts[1:-1]])
    return f"{classname}::{parts[-1]}"


#: ПУБЛИЧНОЕ имя той же двери: перевод `nodeid` pytest → имя junit-записи. Читатели
#: берут ЕЁ, а не пишут свою копию: вторая копия перевода разошлась бы с первой молча
#: (класс ADR-220), и причина уехала бы к ЧУЖОМУ падению, что хуже отсутствия причины.
junit_name = _junit_name



def fork_of(failures: Iterable[Failure], *,
             env: "EnvDeclaration | None" = None) -> Fork:
    """Вилка числа дефектов: компоненты графа … ключи «причина+место».

    **Род стенных часов в вилку НЕ ВХОДИТ (ADR-910).** Провал по `pytest-timeout`
    есть свойство загрузки машины, и его состав ротируется при постоянном числе
    (замер — у :data:`_TIMEOUT_SENTENCE`). Вывод рода стои́т ЗДЕСЬ, у единственной
    двери, а не у каждого читателя: вилку печатают три разных места
    (`format_census`, json-полезная нагрузка, `ci_control.cause_line`), и
    забывший вычесть род читатель разошёлся бы с остальными молча (класс ADR-220).

    **Род ОКРУЖЕНИЯ РАННЕРА в вилку тоже НЕ ВХОДИТ (ADR-915).** Источник у него не
    сообщение провала, а ВНЕШНЕЕ объявление (:func:`env_declaration`): «зелен на
    своём дереве» есть вердикт замера, а не свойство строки. Объявление не
    прочитано ⇒ род НЕ ИЗМЕРЕН и из вилки НЕ ВЫЧИТАЕТСЯ НИЧЕГО — fail-CLOSED.

    **Порядок вычитания объявлен, и он существен.** Род часов снимается ПЕРВЫМ;
    среди оставшихся снимается род окружения. Имя, попавшее под оба (род часов в CI
    и зелень у себя), учитывается РОВНО ОДИН раз — в роде часов, — иначе тождество
    учёта сломалось бы двойным счётом, а читатель получил бы два объяснения одному
    падению.

    Выброшенное население НАЗВАНО полями, а не потеряно: ``wallclock_timeouts`` /
    ``wallclock_names``, ``runner_environment`` / ``runner_environment_names``, и
    тождество ``population + wallclock_timeouts + runner_environment == given``.

    ``env`` — ВХОД, а не окружение: умолчание ``None`` разрешается ВНУТРИ зовом
    :func:`env_declaration`, поэтому боевой путь не меняется ни одним вызовом, а
    сцена контроля подменяет объявление, не трогая боевой файл.
    """
    given = list(failures)
    rods = [f for f in given if f.timeout_rod == ROD_TIMEOUT]
    unmeasured = sum(1 for f in given if f.timeout_rod == ROD_UNMEASURED)
    rest = [f for f in given if f.timeout_rod != ROD_TIMEOUT]
    decl = env_declaration() if env is None else env
    if decl.measured:
        env_hits = [f for f in rest if f.nodeid in decl.names]
        items = [f for f in rest if f.nodeid not in decl.names]
    else:
        env_hits = []
        items = rest
    n = len(items)
    cause_groups = Counter(f.cause_key for f in items)
    upper = len({f.cause_site_key for f in items})

    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> bool:
        ra, rb = find(a), find(b)
        if ra == rb:
            return False
        parent[rb] = ra
        return True

    by_coarse: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, failure in enumerate(items):
        by_coarse[failure.coarse_key].append(i)
    for members in by_coarse.values():
        for other in members[1:]:
            union(members[0], other)

    by_token: dict[str, list[int]] = defaultdict(list)
    for i, failure in enumerate(items):
        for token in failure.evidence:
            by_token[token].append(i)
    merged = 0
    for members in by_token.values():
        for other in members[1:]:
            if union(members[0], other):
                merged += 1

    components: Counter = Counter(find(i) for i in range(n))
    return Fork(
        population=n, cause_groups=len(cause_groups), coarse_groups=len(by_coarse),
        lower=len(components), upper=upper, merged_by_evidence=merged,
        largest_component=(max(components.values()) if components else 0),
        groups=tuple(cause_groups.most_common()),
        wallclock_timeouts=len(rods),
        wallclock_names=tuple(f.nodeid for f in rods),
        rod_unmeasured=unmeasured, given=len(given),
        runner_environment=len(env_hits),
        runner_environment_names=tuple(f.nodeid for f in env_hits),
        runner_env_read=decl.read, runner_env_reason=decl.reason,
    )


def format_census(census: Census, *, shown: int = 12,
                  env: "EnvDeclaration | None" = None) -> str:
    if not census.measured:
        return (f"НЕ ИЗМЕРЕНО · {census.path}\n"
                f"   причина: {census.reason}\n"
                "   «провалов не найдено» здесь НЕ утверждается (инв. #17)")
    lines = [f"ИЗМЕРЕНО · {census.path}: случаев {census.collected}, "
             f"провалов {census.population}"]
    if census.population == 0:
        lines.append("   провалов НЕТ — измерено и равно нулю (не то же, что НЕ ИЗМЕРЕНО)")
        return "\n".join(lines)
    phase = census.by_phase()
    lines.append("   фазы (сумма = населению): " + " · ".join(
        f"{name} {phase.get(name, 0)}" for name in PHASES))
    cause = census.by_cause_class()
    lines.append("   опознание причины (сумма = населению): " + " · ".join(
        f"{name} {cause.get(name, 0)}" for name in CAUSE_CLASSES))
    site = census.by_site_class()
    lines.append("   опознание места (сумма = населению): " + " · ".join(
        f"{name} {site.get(name, 0)}" for name in SITE_CLASSES))
    lines.append(f"   тождества учёта: {'ДЕРЖАТСЯ' if census.identities_hold() else 'НЕ ДЕРЖАТСЯ'}")
    if census.stream_read is None:
        lines.append("   сверка фазы со второй записью: НЕ СПРОШЕНА (--stream не передан)")
    elif census.stream_read != READ_OK:
        lines.append(f"   сверка фазы со второй записью: НЕ ИЗМЕРЕНА — {census.stream_read}")
    else:
        lines.append(f"   сверка фазы со второй записью: согласие {census.stream_agreed} · "
                     f"расхождение {census.stream_disagreed} · "
                     f"в потоковой записи нет {census.stream_absent_for}")
    death = census.session_record
    if death is not None:
        lines.append(f"   ОБМОРОК СЕССИИ: запись `{SESSION_RECORD}` есть — "
                     f"{death.kind or '«тип не назван»'}: {death.skeleton or '«сообщения нет»'}")
    if census.stream_read is None:
        lines.append("   жертвы обморока: НЕ СПРОШЕНЫ (--stream не передан)")
    elif census.session_victims:
        lines.append(f"   жертвы обморока ({len(census.session_victims)}) НАЗВАНЫ "
                     f"потоковой записью: {', '.join(census.session_victims[:5])}")
    else:
        lines.append("   жертв обморока нет — измерено и равно нулю")
    fork = fork_of(census.call, env=env)
    # Род стенных часов печатается ДО раннего возврата намеренно: набор, у которого
    # ВСЕ провалы фазы `call` суть род часов, даёт `population == 0`, и строка
    # «провалов нет» без этой печати прочиталась бы как зелёная фаза.
    if fork.wallclock_timeouts:
        lines.append(f"   ОБМОРОК ПО СТЕННЫМ ЧАСАМ: {fork.wallclock_timeouts} "
                     f"провал(ов) — род `pytest-timeout`, в ВИЛКУ ДЕФЕКТОВ НЕ входит "
                     f"(ADR-910). Поимённо: {', '.join(fork.wallclock_names[:5])}")
    else:
        lines.append("   обморока по стенным часам нет — измерено и равно нулю")
    if fork.rod_unmeasured:
        lines.append(f"   род часов НЕ ИЗМЕРЕН у {fork.rod_unmeasured} провал(ов) "
                     f"(сообщения нет вовсе) — они ОСТАЮТСЯ в вилке дефектов")
    # РОД ОКРУЖЕНИЯ РАННЕРА печатается по тому же праву, что и род часов выше:
    # у жертвы причина ЕСТЬ, и причина эта — не дефект предмета теста. Печатается
    # ВСЕГДА, в том числе исход «НЕ ИЗМЕРЕН»: молчание выдало бы «объявления не
    # нашли» за «измерено и равно нулю» (инв. #17).
    if not fork.measured_runner_env:
        lines.append(f"   род ОКРУЖЕНИЯ РАННЕРА НЕ ИЗМЕРЕН ({fork.runner_env_read}): "
                     f"{fork.runner_env_reason} — из вилки НЕ вычтено НИ ОДНО "
                     f"падение, и «рода здесь нет» НЕ утверждается")
    elif fork.runner_environment:
        lines.append(f"   ОКРУЖЕНИЕ РАННЕРА: {fork.runner_environment} провал(ов) — "
                     f"род `runner_environment` (ADR-913/915), красны в CI и ЗЕЛЕНЫ "
                     f"на своём дереве, в ВИЛКУ ДЕФЕКТОВ НЕ входят. Поимённо: "
                     f"{', '.join(fork.runner_environment_names[:5])}")
    else:
        lines.append("   рода окружения раннера в наборе нет — измерено и равно нулю")
    if fork.population == 0:
        lines.append("   фаза `call`: провалов вне рода часов нет — вилка не считается")
        return "\n".join(lines)
    call_cause = Counter(f.cause_class for f in census.call)
    lines.append("   из них опознание причины: " + " · ".join(
        f"{name} {call_cause.get(name, 0)}" for name in CAUSE_CLASSES))
    lines.append(f"   фаза `call`: провалов {fork.population} · ПРИЧИН (ключей) {fork.cause_groups}"
                 f" · грубых ключей {fork.coarse_groups}")
    lines.append(f"   ВИЛКА ДЕФЕКТОВ: НЕ МЕНЬШЕ {fork.lower} и НЕ БОЛЬШЕ {fork.upper}"
                 f" (склеено ребром следа {fork.merged_by_evidence} · "
                 f"крупнейший компонент {fork.largest_component} · "
                 + ("род окружения раннера ВЫЧТЕН)" if fork.measured_runner_env
                    else "БЕЗ вычитания рода окружения раннера — он НЕ ИЗМЕРЕН)"))
    for (kind, skel), count in fork.groups[:shown]:
        mark = "✖" if count > 1 else "·"
        lines.append(f"   {mark} {count:3d}  {kind}: {skel}")
    if fork.cause_groups > shown:
        lines.append(f"   … и ещё {fork.cause_groups - shown} причин(а) по одному провалу")
    return "\n".join(lines)


def as_json(census: Census, *, env: "EnvDeclaration | None" = None) -> dict:
    payload = {
        "read": census.read, "reason": census.reason, "path": census.path,
        "collected": census.collected, "population": census.population,
        "by_phase": dict(census.by_phase()),
        "by_cause_class": dict(census.by_cause_class()),
        "by_site_class": dict(census.by_site_class()),
        "identities_hold": census.identities_hold(),
        "stream_read": census.stream_read,
        "stream_agreed": census.stream_agreed,
        "stream_disagreed": census.stream_disagreed,
        "stream_absent_for": census.stream_absent_for,
        "session_record": (None if census.session_record is None else {
            "kind": census.session_record.kind,
            "skeleton": census.session_record.skeleton,
            "message": census.session_record.message,
        }),
        "session_victims": list(census.session_victims),
    }
    if census.measured:
        fork = fork_of(census.call, env=env)
        payload["call"] = {
            "population": fork.population, "cause_groups": fork.cause_groups,
            "coarse_groups": fork.coarse_groups,
            "defects_not_less_than": fork.lower, "defects_not_more_than": fork.upper,
            "merged_by_evidence": fork.merged_by_evidence,
            "largest_component": fork.largest_component,
            # Род стенных часов (ADR-910): выведен из вилки и НАЗВАН, не потерян.
            "wallclock_timeouts": fork.wallclock_timeouts,
            "wallclock_names": list(fork.wallclock_names),
            "rod_unmeasured": fork.rod_unmeasured, "given": fork.given,
            # Род окружения раннера (ADR-915): выведен из вилки и НАЗВАН, не
            # потерян. Исход чтения объявления кладётся ВСЕГДА — ключ, а не
            # значение, отвечает на вопрос «спрашивали ли вообще» (урок ADR-911).
            "runner_environment": fork.runner_environment,
            "runner_environment_names": list(fork.runner_environment_names),
            "runner_env_read": fork.runner_env_read,
            "runner_env_reason": fork.runner_env_reason,
            "groups": [{"kind": k, "skeleton": s, "failures": c}
                       for (k, s), c in fork.groups],
        }
    return payload


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Причина провала фазы `call` по junit-записи (заказ G108 п. 1, ADR-675). "
                    "Только ЧИТАЕТ.",
    )
    parser.add_argument("record", nargs="+", type=Path, help="junit-XML прогона")
    parser.add_argument("--stream", type=Path, default=None,
                        help="потоковая запись того же прогона — вторая, МАШИННАЯ "
                             "дверь к фазе провала")
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    measured = 0
    payloads = []
    for path in args.record:
        census = census_from_path(path, stream=args.stream)
        payloads.append(as_json(census))
        if not args.json:
            print(format_census(census, shown=args.top))
        if census.measured:
            measured += 1
    if args.json:
        print(json.dumps(payloads, ensure_ascii=False, indent=2))
    # Хотя бы одна запись не прочитана ⇒ 2: «часть измерена» не есть «измерено».
    return 0 if measured == len(args.record) else 2


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
