"""Перепись: операнд «предыдущий прогон», взятый из git-tracked артефакта.

Заказ владельца **G86 п. 3** (хвост ADR-475, стои́т остатком с 25.09):

> Сколько ещё сторожей читают «предыдущий прогон» из git-tracked артефакта. Класс шире
> одного файла: любой `prev_*` операнд, который в CI берётся из репозитория, есть
> константа, а не наблюдение. Мерить у ПИСАТЕЛЯ (кто коммитит артефакт обратно), а не
> по имени поля; три исхода обязательны.

Авария, из которой заказ вырос (ADR-475, замер 25.09). Половина стоп-крана кустодиана
читала `prev_report.stale_48h` из `data/site_freshness_report.json`. Файл git-tracked, у
джобы `permissions: contents: read`, обратно его не коммитит НИКТО — значит в CI на месте
«предыдущего прогона» лежал отчёт от 2026-07-04 со `stale_48h: false`, возраст 2000 ч.
Второй операнд «двух прогонов подряд» был КОНСТАНТОЙ из 4 июля, и ветка не срабатывала
ни разу за 83 дня. Тихий fail-OPEN: красного теста нет, красной джобы нет, ноль в отчёте
неотличим от «на прошлом прогоне было чисто».

## Почему перепись мерит у ПИСАТЕЛЯ, а не по имени поля

Имя `prev_*` — привычка автора, а не свойство кода: тот же вред носит `last_report`,
`baseline`, `earlier` и безымянный элемент списка. И наоборот: `prev_apy`, посчитанный
в ЭТОМ прогоне из ряда, никакого вреда не несёт. Вопрос, отвечающий на вред, ровно один:
**кто кладёт этот файл в то дерево, которое сторож прочтёт.** Если файл git-tracked и
обратно его не коммитит никакая ОБЪЯВЛЕННАЯ автоматика, то в CI сторож читает не прошлый
прогон, а последний коммит — то есть константу.

## Что признаётся «предыдущим прогоном» (структурно, без имён)

Модуль ПИШЕТ и ЧИТАЕТ ОДИН И ТОТ ЖЕ путь под `data/`. Чтение своего же вывода и есть
структурная форма «предыдущего прогона»: другого способа получить прошлый прогон у
процесса без памяти нет. Форма не зависит ни от имени переменной, ни от имени поля.

## Исходы (форма ЗАКРЫТА, сумма равна населению, инв. #17)

Ноги спрашиваются в ЭТОМ порядке, и порядок — часть утверждения:

1. ``reader_not_reachable_from_ci`` — ни один воркфлоу не зовёт читателя. На хосте файл
   на диске ЕСТЬ результат прошлого прогона, поэтому операнд там — наблюдение, и вреда
   заказа тут нет. Спрашивать это первым обязательно: иначе перепись объявила бы
   дефектом каждый агентский журнал флота.
2. ``absent_in_ci`` — артефакт НЕ git-tracked. В CI прошлого прогона нет ВОВСЕ, то есть
   операнд ОТСУТСТВУЕТ, а не врёт. Это другая беда и чинится другим (назвать отсутствие
   третьим исходом), поэтому в находку не сливается.
3. ``prior_run_committed_back`` — артефакт git-tracked И объявленная автоматика коммитит
   его обратно. Тогда в CI операнд есть наблюдение (пусть и на шаг старое).
4. ``constant_in_ci_named`` — git-tracked, автоматики нет, но читатель СПРАШИВАЕТ
   ВОЗРАСТ прошлого артефакта (значение из него уходит в разбор времени, а результат
   разбора — в сравнение). Фоссил назван; это состояние кустодиана ПОСЛЕ ADR-475 и
   положительный контроль исхода.
5. ``constant_in_ci_trusted`` — git-tracked, автоматики нет, возраст не спрашивается.
   **Это и есть находка заказа**: операнд — константа, и молчание выдаётся за согласие.
6. ``unmeasured:<причина>`` — громкий третий исход с НАЗВАННОЙ причиной. Недоступный git,
   нечитаемое дерево воркфлоу, неразбираемый файл. Никогда не ноль и никогда не «чисто».

## Односторонность — НАЗВАНА ЗАРАНЕЕ, и каждая клауза есть нижняя граница

- **Читатель чужого вывода в население НЕ входит.** Сторож, читающий прошлый прогон
  ДРУГОГО производителя, несёт тот же вред, и здесь он не измерен ВОВСЕ. Это следующий
  вопрос, а не молчаливое «чисто».
- **Запись видна на один уровень.** Кроме примитивов (`atomic_save`, `open(...,'w')`,
  `.write_text`, `os.replace`) разбирается ОДИН уровень локального помощника: функция
  этого же модуля, у которой параметр уходит в примитив на месте пути. Авария ADR-475
  имеет ровно эту форму (`_atomic_write(_REPORT, report)`), и без уровня помощника
  положительный контроль не нашёлся бы — первый черновик этой переписи дал на нём
  НОЛЬ. Цепочка глубже двух звеньев в население не попадает: население — нижняя граница.
- **Достижимость из CI — по УПОМИНАНИЮ** читателя в `.github/workflows/*.yml`. Читатель,
  позванный окольно (модуль, импортированный скриптом, которого зовёт джоба), считается
  недостижимым. Опять нижняя граница, и опять сказано вслух.
- **Писатель ищется в ОБЪЯВЛЕННОМ радиусе** — воркфлоу и plist'ы флота, — а НЕ в истории
  git. История в CI отсутствует по построению (`fetch-depth: 1`, ADR-479), и прибор,
  спросивший `git log`, отвечал бы на разных машинах разное. Коммит, сделанный руками
  цикла, писателем НЕ считается: у ADR-475 файл был закоммичен именно так, и это его
  фоссилом не сделало менее фоссилом.
- **«Возраст спрашивается» — признак, а не доказательство.** Прибор видит, что читатель
  СПРАШИВАЕТ, когда был прошлый прогон; верен ли порог и верно ли ветвление — вопрос не
  его. Сказано числом, а не словами: исход зовётся ``named``, не ``safe``.

## Вторая ось: ХОСТОВАЯ (заказ G104 п. 2, ADR-621)

Главная ось выше спрашивает про CI, где прошлого прогона нет вовсе. ADR-524 доложил
рядом ИЗМЕРЕННОЕ число — 215 пар, чей читатель из CI недостижим, а артефакт git-tracked,
— и честно НЕ объявил его находкой: на рабочей машине файл на диске ЕСТЬ результат
прошлого прогона. Заказ G104 п. 2 просит у этой цифры то, чего ей не задавали ни одного
дня: **сколько из них заметили бы, что операнд подменён закоммиченным каноном.**

Подменяющая команда — не гипотеза. Авария цикла #361: `git checkout -- data/`, набранная
для одноразового дерева и выполненная в боевом, откатила **116 файлов на три недели**;
из ночного резерва вернулись 114, дыра 19,5 ч осталась навсегда. Трек уцелел случайно —
дневной цикл переписал `equity_curve_daily.json` через три минуты. Советательные журналы
не переписал никто, и НИ ОДИН сторож об этом не сказал.

Исходы хостовой оси (``HOST_OUTCOMES``) — своя ЗАКРЫТАЯ форма, своя сумма, свой третий
исход; в сумму главных исходов она не входит и кода возврата не повышает (почему именно —
в докстринге ``verdict``). Ноги у осей ОДНИ И ТЕ ЖЕ функции: второй копии правила нет.

## Третья ось: АРТЕФАКТНАЯ (заказ G104 п. 3, ADR-622)

Две оси выше считают ПАРЫ «читатель × свой же артефакт»: единица там — читатель, и
писателя спрашивают только у самокарусельных. Заказ G104 п. 3 ставит вопрос о другой
единице — о самом ФАЙЛЕ: сколько git-tracked артефактов производится в рантайме, а
обратно их не кладёт никакая объявленная автоматика. Такой файл есть константа для
ЛЮБОГО своего читателя, а не только для того, кто его же и пишет.

Вред измерен ЭТИМ ЖЕ циклом, и по случайности. Обязательный шаг цикла «вторая запись о
деньгах» (`scripts/book_second_record.py`, ADR-350), запущенный из свежего одноразового
worktree, доложил **«7 ходов»** и расхождение на T007; на боевом дереве тот же код в тот
же день доложил **«34 хода»** и расхождение на T008/T034. Разным был ОПЕРАНД: в worktree
журнал денег — закоммиченный канон (`data/trades.json`, 7 записей, последняя 2026-06-20),
на боевом диске — живой журнал на 34 записи. Прибор напечатал имя каталога и ответил о
деньгах по константе, не сказав об этом ни слова.

Исходы артефактной оси (``ARTIFACT_OUTCOMES``) — своя ЗАКРЫТАЯ форма, своя сумма, свой
третий исход. В суммы двух осей выше она не входит и складыванию с ними НЕ подлежит:
единицы населения разные (пара против пути), и одно дерево попадает в обе.

ADVISORY: прибор только ЧИТАЕТ (`applied=False`). Ни строки risk-логики, стоп-крана
просадки, аллокатора, гейта исполнения, живого трека, `landing/**` или флота он не
меняет и менять не может.
"""

from __future__ import annotations

import argparse
import ast
import collections
import json
import pathlib
import re
import subprocess
import sys

APPLIED = False

#: Каталоги, в которых ищутся читатели. Тесты сюда не входят: тест, читающий свой же
#: артефакт, есть фикстура, а не сторож дерева.
SOURCE_ROOTS = ("spa_core", "scripts")

#: Литерал признаётся путём артефакта данных по РАСШИРЕНИЮ. Путь собирается из кусков
#: (`_ROOT / "data" / "x.json"`), поэтому якорем берётся последний кусок — имя файла.
ARTIFACT_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.(?:json|jsonl)$")

#: Примитивы записи. `os.replace` входит: атомарная запись кончается именно им, и без
#: него локальный помощник вида `tmp.write_text(...); os.replace(tmp, path)` не виден.
WRITE_PRIMITIVES = ("atomic_save", "write_text", "replace", "open", "dump")

#: Вызовы, превращающие значение в ВРЕМЯ. Читатель, приведший операнд к времени,
#: спрашивает «когда был прошлый прогон» — это и есть признак названного фоссила.
TIME_CALL_NAMES = (
    "fromisoformat", "strptime", "utcfromtimestamp", "fromtimestamp",
    "parse_ts", "_parse_ts", "hours_since", "_hours_since", "age_hours",
    "_age_hours", "_hours_since_ts", "hours_since_ts", "total_seconds",
)

#: Вызовы, добывающие наблюдение ЭТОГО прогона извне модуля: сеть, процесс, часы.
#: Операнд «предыдущий прогон» опасен ровно тогда, когда встречается в решении с таким
#: наблюдением: тогда «прошлый раз было чисто» подставляется вместо факта. Сравнение
#: прошлого содержимого с ЛИТЕРАЛОМ — это проверка самого документа, а не решение о мире.
#: Голого `get` здесь НЕТ, и это замер, а не недосмотр: `dict.get` — самая частая форма
#: в этом дереве, и её включение делало `observed` почти всеми именами модуля, то есть
#: гасило ногу «нет решения против наблюдения» целиком. Сетевой случай через `get` при
#: этом ничего не терял: живой запрос кустодиана идёт своим помощником `_get`, а не
#: `requests.get`. Канал наблюдения, на котором нога держится, — чтение ДРУГОГО артефакта,
#: и он проверяется отдельным звеном, а не именем вызова.
OBSERVATION_CALL_NAMES = (
    "urlopen", "request", "urlretrieve", "run", "check_output", "Popen",
    "now", "utcnow", "time", "monotonic", "stat", "st_mtime", "getmtime",
)

OUT_NOT_IN_CI = "reader_not_reachable_from_ci"
OUT_ABSENT_IN_CI = "absent_in_ci"
OUT_COMMITTED_BACK = "prior_run_committed_back"
OUT_PARITY = "parity_with_own_regeneration"
OUT_NO_DECISION = "no_decision_against_a_current_observation"
OUT_CONST_NAMED = "constant_in_ci_named"
OUT_CONST_TRUSTED = "constant_in_ci_trusted"
OUT_UNMEASURED = "unmeasured"

#: Форма исхода ЗАКРЫТА. Сумма по этому перечню обязана равняться населению, и каждый
#: ноль объявляется явно (инв. #17) — «нет такого исхода» и «исход не считался» разные.
OUTCOMES = (
    OUT_NOT_IN_CI,
    OUT_ABSENT_IN_CI,
    OUT_COMMITTED_BACK,
    OUT_PARITY,
    OUT_NO_DECISION,
    OUT_CONST_NAMED,
    OUT_CONST_TRUSTED,
    OUT_UNMEASURED,
)

# ─────────────────────────────────────────────────────────────────────────────────────
# Хостовая ось (заказ G104 п. 2): заметил бы читатель подмену операнда КАНОНОМ
# ─────────────────────────────────────────────────────────────────────────────────────
#
# Главная ось спрашивает про CI, где прошлого прогона нет вовсе. Хостовая — про ту же
# пару на РАБОЧЕЙ машине, где файл на диске есть результат прошлого прогона и вреда
# заказа нет, ПОКА его не подменит закоммиченный канон. Авария цикла #361: одна команда
# `git checkout -- data/`, набранная для одноразового дерева и выполненная в боевом,
# откатила 116 файлов на три недели. Из ночного резерва вернулись 114, дыра 19,5 ч
# осталась навсегда. Ни один сторож об этом не сказал.
#
# ADR-524 доложил размер этого населения (215 пар) и честно НЕ объявил его находкой.
# Заказ G104 п. 2 просит задать ему тот вопрос, который до сих пор не задавали ни разу:
# **сколько из них ЗАМЕТИЛИ БЫ подмену.** Ноги — те же функции, что у главной оси, и
# второй копии правила здесь нет: порядок ADR-460 (одно правило — один читатель).
HOST_UNMEASURED = "host_unmeasured"
HOST_CANON_IS_A_RECENT_RUN = "host_canon_is_a_recent_run"
HOST_PARITY = "host_parity_with_own_regeneration"
HOST_NO_DECISION = "host_no_decision_against_a_current_observation"
HOST_NOTICES_BY_AGE = "host_notices_by_age"
HOST_SILENTLY_TRUSTS = "host_silently_trusts"

#: Форма хостового исхода ЗАКРЫТА так же, как главная: сумма равна хостовому населению,
#: каждый ноль объявлен (инв. #17). Порядок — часть утверждения.
HOST_OUTCOMES = (
    HOST_UNMEASURED,
    HOST_CANON_IS_A_RECENT_RUN,
    HOST_PARITY,
    HOST_NO_DECISION,
    HOST_NOTICES_BY_AGE,
    HOST_SILENTLY_TRUSTS,
)

# ─────────────────────────────────────────────────────────────────────────────────────
# Артефактная ось (заказ G104 п. 3): у скольких git-tracked артефактов НЕТ писателя
# ─────────────────────────────────────────────────────────────────────────────────────
#
# Обе оси выше считают ПАРЫ «читатель × свой же артефакт»: единицей там является
# читатель, а писателя спрашивают только у самокарусельных пар. Заказ G104 п. 3 ставит
# вопрос ШИРЕ и о другой единице — о самом ФАЙЛЕ:
#
#   «Файл, лежащий в репозитории и производимый в рантайме, у которого никакая
#    объявленная автоматика не кладёт результат обратно, есть константа для ЛЮБОГО
#    своего читателя, а не только для того, кто его же и пишет.»
#
# Поэтому населением этой оси служат git-tracked ПУТИ, а не пары, и ноги спрашиваются
# у ПИСАТЕЛЯ — ровно как требует заказ. Самокарусельность здесь не нужна вовсе: вред не
# зависит от того, читает ли файл его собственный производитель.
#
# Вред не гипотеза и измерен ЭТИМ ЖЕ циклом по случайности. Обязательный шаг цикла
# «вторая запись о деньгах» (`scripts/book_second_record.py`, ADR-350), запущенный из
# свежего одноразового worktree, доложил «7 ходов» и расхождение на T007, а на боевом
# дереве — «34 хода» и расхождение на T008/T034. Код один, день один; разным был
# ОПЕРАНД: в worktree журнал денег есть закоммиченный канон (`data/trades.json`, 7
# записей, последняя 2026-06-20), а на диске боевого дерева — живой журнал на 34
# записи. Прибор об этом не сказал ни слова: он напечатал имя каталога и ответил о
# деньгах по константе.
ART_UNMEASURED = "artifact_unmeasured"
ART_NO_RUNTIME_WRITER = "artifact_not_produced_in_runtime"
ART_WRITER_DECLARED = "artifact_writer_declared"
ART_NO_WRITER_UNREAD = "no_declared_writer_and_unread_in_tree"
ART_NO_WRITER_READ = "no_declared_writer_and_read"

#: Форма артефактного исхода ЗАКРЫТА так же, как у двух соседних осей: сумма равна
#: артефактному населению, каждый ноль объявлен (инв. #17). Порядок — часть утверждения,
#: и первым после третьего исхода спрашивается «производится ли файл в рантайме ВООБЩЕ»:
#: без этого вопроса перепись объявила бы дефектом каждый курируемый конфиг в дереве.
ARTIFACT_OUTCOMES = (
    ART_UNMEASURED,
    ART_NO_RUNTIME_WRITER,
    ART_WRITER_DECLARED,
    ART_NO_WRITER_UNREAD,
    ART_NO_WRITER_READ,
)

#: **Ноги «а заметил бы кто-нибудь» у этой оси НЕТ, и это РЕШЕНИЕ с замером, а не
#: недосмотр.** Ось отвечает ровно на вопрос заказа — про ПИСАТЕЛЯ файла. Вопрос «пусть
#: писателя нет, но покраснеет ли объявленная сверка канона с пересборкой» — ДРУГОЙ, и
#: попытка померить его ногой провалилась ИЗМЕРИМО, поэтому нога снята, а не оставлена
#: тихой:
#:
#: · подстрочный признак «в шаге есть `--check`» дал ложное срабатывание на
#:   `scripts/kanban_health.py --check-only`, где флаг значит «не писать», а не «сверить»
#:   (ADR-333: проба не проходит подстрокой);
#: · строгий признак — ``_parity_with_own_regeneration`` у производителя — дал ложный
#:   ПРОПУСК: `scripts/fill_agent_passports.py --check` сверяет паспорта с выводом из
#:   источников и выходит НЕНУЛЕВЫМ на расхождении, но писателем `manifest.json` прибор
#:   его не видит вовсе (запись идёт через `atomic_save_text`, которого нет в
#:   ``WRITE_PRIMITIVES``), а метка прочитанного не доходит до тела цикла `for a in agents`;
#: · ослабление метки (цель `for` — связывание) раздувает её с 5 имён до 58 на том же
#:   модуле и объявляет «сверкой» 35 сравнений из них. Нога, которая тише находки,
#:   опаснее находки: она гасит класс молча.
#:
#: Поэтому известный член исхода ``no_declared_writer_and_read``, у которого расхождение
#: ВСЁ ЖЕ покраснеет, назван РУКАМИ — `architecture/manifest.json` — и живёт в
#: ``not_reported``. Это нижняя граница точности исхода, объявленная вслух.

#: Радиус дословной команды аварии #361. Пара, чей артефакт лежит вне `data/`, подмене
#: ЭТОЙ командой не подвержена — но подвержена `git checkout -- .`, поэтому из населения
#: не исключается, а докладывается отдельным числом.
CANON_SUBSTITUTION_RADIUS = "data/"

#: Формы, которыми объявленная автоматика кладёт артефакт обратно в дерево (YAML/plist).
COMMIT_FORMS = ("git commit", "git-auto-commit", "add-and-commit", "stefanzweifel")

#: Доставщики дерева этого репозитория. Писателем признаётся вызов, ПОЛУЧИВШИЙ путь
#: артефакта аргументом, а не сосед по файлу: третий дефект черновика был ровно здесь —
#: радиус писателя ограничивался воркфлоу и plist'ами, и `landing/src/data/track_snapshot.json`,
#: который кустодиан публикует САМ (`publish_from_fresh_checkout(_SNAP, …)`), получил вердикт
#: «автоматики нет». Со-присутствие в одном файле писателем НЕ является: тот же кустодиан
#: называет и `site_freshness_report.json`, которого не коммитит никто, и «писатель в том же
#: модуле» оправдал бы аварию ADR-475 её же собственным доставщиком.
COMMIT_CALL_NAMES = (
    "publish_from_fresh_checkout", "safe_site_push", "push_to_github",
    "batch_push", "push_files", "commit_and_push", "git_commit",
)

RC_MEASURED = 0
RC_FINDING = 1
RC_UNMEASURED = 2


# ─────────────────────────────────────────────────────────────────────────────────────
# Разрешение имён: какие литералы-артефакты стои́т за выражением
# ─────────────────────────────────────────────────────────────────────────────────────

def _artifact_literals(node):
    """Имена файлов-артефактов, встречающиеся литералами внутри выражения."""
    out = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            tail = sub.value.rsplit("/", 1)[-1]
            if ARTIFACT_NAME_RE.match(tail):
                out.add(tail)
    return out


def _names_in(node):
    return {sub.id for sub in ast.walk(node) if isinstance(sub, ast.Name)}


class _PathResolver:
    """Имя → множество имён артефактов, до неподвижной точки.

    Область НАМЕРЕННО плоская: путь к артефакту в этом коде почти всегда константа
    модуля, а разбор по областям видимости добавил бы вторую копию правила связывания
    ради случая, которого в дереве нет. Цена названа: одноимённые локальные пути в
    разных функциях слились бы — и это подняло бы население (ошибка в сторону находки),
    а не понизило.
    """

    def __init__(self, tree):
        self._direct = collections.defaultdict(set)
        self._via = collections.defaultdict(set)
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
                targets = [node.target]
            for tgt in targets:
                if isinstance(tgt, ast.Name):
                    self._direct[tgt.id] |= _artifact_literals(node.value)
                    self._via[tgt.id] |= _names_in(node.value)

    def resolve(self, node):
        out = _artifact_literals(node)
        for name in _names_in(node):
            out |= self._name(name, set())
        return out

    def _name(self, name, seen):
        if name in seen:
            return set()
        seen.add(name)
        out = set(self._direct.get(name, ()))
        for nxt in self._via.get(name, ()):
            out |= self._name(nxt, seen)
        return out


def _call_name(call):
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _mode_of(call):
    mode = ""
    for arg in call.args[1:]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            mode = arg.value
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            mode = str(kw.value.value)
    return mode


def _primitive_path_slots(call):
    """Выражения этого вызова, стоя́щие на месте ПУТИ у примитива записи/чтения.

    Возвращает ``(write_slots, read_slots)``. Один вызов может не быть ни тем, ни
    другим — тогда оба пусты.
    """
    name = _call_name(call)
    func = call.func
    writes, reads = [], []
    if name == "atomic_save" and len(call.args) >= 2:
        # ADR-порядок: atomic_save(data, path) — данные ПЕРВЫМ аргументом.
        writes.append(call.args[1])
    elif name == "write_text" and isinstance(func, ast.Attribute):
        writes.append(func.value)
    elif name == "replace" and isinstance(func, ast.Attribute) and call.args:
        # os.replace(tmp, path) — целью является ВТОРОЙ аргумент; tmp нас не интересует.
        if len(call.args) >= 2:
            writes.append(call.args[1])
    elif name == "dump" and len(call.args) >= 2:
        writes.append(call.args[1])
    elif name == "open" and call.args:
        mode = _mode_of(call)
        if "w" in mode or "a" in mode or "x" in mode:
            writes.append(call.args[0])
        else:
            reads.append(call.args[0])
    elif name == "read_text" and isinstance(func, ast.Attribute):
        reads.append(func.value)
    elif name == "load" and call.args:
        reads.append(call.args[0])
    elif name == "loads" and call.args:
        reads.append(call.args[0])
    return writes, reads


# ─────────────────────────────────────────────────────────────────────────────────────
# Один уровень локального помощника
# ─────────────────────────────────────────────────────────────────────────────────────

def _parameters(fdef):
    """Параметры функции: позиционные и ТОЛЬКО-ИМЕННЫЕ, одним правилом.

    Возвращает ``(positional, all_names)``. Отдельная функция, а не два обхода на
    месте: пропуск ``kwonlyargs`` был НАСТОЯЩИМ дефектом первого черновика — на
    положительном контроле ADR-475 (`def evaluate(*, …, prev_report=None)`) метка не
    доходила до параметра, и перепись объявляла названный фоссил молчаливой
    константой, то есть выдумывала находку на исправленном коде.
    """
    positional = [a.arg for a in list(fdef.args.posonlyargs) + list(fdef.args.args)]
    names = positional + [a.arg for a in fdef.args.kwonlyargs]
    return positional, names


def _local_functions(tree):
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(node.name, node)
    return out


def _helper_path_slots(tree):
    """Локальные помощники, чей параметр уходит в примитив на месте пути.

    ``{имя функции: {"write": {индексы}, "read": {индексы}}}``. Без этого уровня
    авария ADR-475 не находится: кустодиан пишет отчёт не примитивом, а своим
    ``_atomic_write(_REPORT, report)``. Первый черновик переписи дал на положительном
    контроле НОЛЬ именно поэтому.
    """
    out = {}
    for fname, fdef in _local_functions(tree).items():
        positional, params = _parameters(fdef)
        if not params:
            continue
        index = {p: i for i, p in enumerate(positional)}
        slots = {"write": set(), "read": set(), "write_kw": set(), "read_kw": set()}
        for node in ast.walk(fdef):
            if not isinstance(node, ast.Call):
                continue
            writes, reads = _primitive_path_slots(node)
            for kind, exprs in (("write", writes), ("read", reads)):
                for expr in exprs:
                    for nm in _names_in(expr):
                        if nm in index:
                            slots[kind].add(index[nm])
                        elif nm in params:
                            slots[kind + "_kw"].add(nm)
        if any(slots.values()):
            out[fname] = slots
    return out


def _sites(tree, resolver):
    """Места записи и чтения артефактов: примитивы + ОДИН уровень помощника."""
    helpers = _helper_path_slots(tree)
    writes = collections.defaultdict(set)
    reads = collections.defaultdict(set)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        w_exprs, r_exprs = _primitive_path_slots(node)
        for artifact in {a for e in w_exprs for a in resolver.resolve(e)}:
            writes[artifact].add(node.lineno)
        for artifact in {a for e in r_exprs for a in resolver.resolve(e)}:
            reads[artifact].add(node.lineno)
        name = _call_name(node)
        slots = helpers.get(name)
        if slots:
            for kind, bucket in (("write", writes), ("read", reads)):
                for idx in slots[kind]:
                    if idx < len(node.args):
                        for artifact in resolver.resolve(node.args[idx]):
                            bucket[artifact].add(node.lineno)
                for kwname in slots[kind + "_kw"]:
                    for kw in node.keywords:
                        if kw.arg == kwname:
                            for artifact in resolver.resolve(kw.value):
                                bucket[artifact].add(node.lineno)
    return writes, reads


# ─────────────────────────────────────────────────────────────────────────────────────
# Спрашивает ли читатель ВОЗРАСТ прошлого артефакта
# ─────────────────────────────────────────────────────────────────────────────────────

def _read_bindings(tree, artifact, resolver):
    """Имена, связанные со значением, прочитанным из этого артефакта."""
    tainted = set()
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and isinstance(getattr(node, "target", None), ast.Name):
            targets = [node.target]
        if not targets:
            continue
        # `x: int` БЕЗ значения — объявление типа, а не связывание: `node.value` там
        # `None`, и `ast.walk(None)` падает `AttributeError`. Главная ось этой формы не
        # видела, потому что доходила до ноги на ЧЕТЫРЁХ парах из 586; хостовая ось
        # привела сюда двести, и прибор упал на первой же аннотации. Нечего разбирать —
        # нечего и пометить: это отсутствие связывания, а не отказ замера.
        if node.value is None:
            continue
        for sub in ast.walk(node.value):
            if isinstance(sub, ast.Call):
                _, r_exprs = _primitive_path_slots(sub)
                if any(artifact in resolver.resolve(e) for e in r_exprs):
                    tainted |= {t.id for t in targets}
    return tainted


def _spread(tree, tainted):
    """Разнести метку по связываниям и по ОДНОМУ уровню локального вызова."""
    funcs = _local_functions(tree)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                names = _names_in(node.value)
                if names & tainted:
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name) and tgt.id not in tainted:
                            tainted.add(tgt.id)
                            changed = True
            elif isinstance(node, ast.Call):
                fdef = funcs.get(_call_name(node))
                if fdef is None:
                    continue
                positional, params = _parameters(fdef)
                for idx, arg in enumerate(node.args):
                    if idx < len(positional) and (_names_in(arg) & tainted) and positional[idx] not in tainted:
                        tainted.add(positional[idx])
                        changed = True
                for kw in node.keywords:
                    if kw.arg in params and (_names_in(kw.value) & tainted) and kw.arg not in tainted:
                        tainted.add(kw.arg)
                        changed = True
    return tainted


def _write_data_names(tree):
    """Имена, чьё значение уходит в ДАННЫЕ записи (а не в путь).

    Радиус НАМЕРЕННО грубый — все примитивы записи модуля, без разделения по артефакту:
    модуль, пишущий два артефакта, слил бы их. Цена названа, и она в сторону
    ИСКЛЮЧЕНИЯ из находки, поэтому население остаётся нижней границей, а не раздувается.
    """
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name == "atomic_save" and node.args:
            out |= _names_in(node.args[0]) | _callees_in(node.args[0])
        elif name in ("dump", "write_text", "write") and node.args:
            out |= _names_in(node.args[0]) | _callees_in(node.args[0])
    return out


def _callees_in(node):
    """Имена вызываемых функций внутри выражения — «чьим производством это значение»."""
    out = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            name = _call_name(sub)
            if name:
                out.add("()" + name)
    return out


def _producer_chain(tree, names):
    """Имена и производители, из которых происходят эти имена (до неподвижной точки)."""
    out = set(names)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if targets & out:
                add = (_names_in(node.value) | _callees_in(node.value)) - out
                if add:
                    out |= add
                    changed = True
    return out


def _parity_with_own_regeneration(tree, artifact, resolver):
    """Читанное сравнивается с ПЕРЕСБОРКОЙ того же артефакта в этом же прогоне.

    Идиома `scripts/build_protection_lab_site_data.py --check`: закоммиченный файл
    читается как ПРЕДМЕТ проверки, рядом строится свежий той же функцией, и расхождение
    и есть вердикт. Закоммиченная копия здесь — не «прошлый прогон», а ожидаемое
    значение, ради которого её и коммитят. Объявить это находкой значило бы потребовать
    убрать проверку паритета — обратное тому, ради чего заказ написан.
    """
    prior = _spread(tree, _read_bindings(tree, artifact, resolver))
    if not prior:
        return False
    written = _producer_chain(tree, _write_data_names(tree))
    local = set(_local_functions(tree))
    # Производителем пересборки признаётся ТОЛЬКО функция этого модуля. Без этого
    # условия за пересборку сошёл бы `json.dumps` у любого писателя, и идиома паритета
    # проглотила бы настоящую находку: авария ADR-475 пишет отчёт именно так.
    written_callees = {n for n in written if n.startswith("()") and n[2:] in local}
    if not written_callees:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left] + list(node.comparators)
        if not any(_names_in(o) & prior for o in operands):
            continue
        # Требовать «другой операнд НЕ из прошлого» здесь нельзя: у идиомы паритета
        # пересборка берёт из закоммиченной копии одно поле (`generated`), и метка
        # прошлого честно доходит до ОБОИХ операндов. Спрашивается поэтому не
        # непричастность, а ПРОИСХОЖДЕНИЕ от собственной пересборки.
        for operand in operands:
            chain = _producer_chain(tree, _names_in(operand)) | _callees_in(operand)
            if chain & written_callees:
                return True
    return False


def _meets_a_current_observation(tree, artifact, resolver):
    """Встречается ли прошлый операнд в РЕШЕНИИ с наблюдением этого прогона.

    Наблюдение — чтение ДРУГОГО артефакта, сеть, процесс или часы. Авария ADR-475
    имеет ровно эту форму: ``stale_48 and prev_stale_48``, где `stale_48` посчитан из
    снимка, а `prev_stale_48` взят из фоссила. Сравнение прошлого содержимого с
    литералом или с собственным полем — проверка документа, а не решение о мире, и в
    находку не идёт: иначе переписью стал бы каждый валидатор git-tracked документа
    (`scripts/kanban_health.py` — положительный контроль этого исключения).
    """
    prior = _spread(tree, _read_bindings(tree, artifact, resolver))
    if not prior:
        return False
    seeds = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
        if not targets:
            continue
        for sub in ast.walk(node.value):
            if not isinstance(sub, ast.Call):
                continue
            _, r_exprs = _primitive_path_slots(sub)
            other_read = any(
                a != artifact for e in r_exprs for a in resolver.resolve(e)
            )
            if other_read or _call_name(sub) in OBSERVATION_CALL_NAMES:
                seeds |= targets
    observed = _spread(tree, seeds) - prior
    if not observed:
        return False
    for node in ast.walk(tree):
        operands = None
        if isinstance(node, ast.Compare):
            operands = [node.left] + list(node.comparators)
        elif isinstance(node, ast.BoolOp):
            operands = list(node.values)
        if not operands:
            continue
        reached_prior = any(_names_in(o) & prior for o in operands)
        reached_obs = any(_names_in(o) & observed for o in operands)
        if reached_prior and reached_obs:
            return True
    return False


def _asks_the_age(tree, artifact, resolver):
    """Уходит ли значение из артефакта в разбор ВРЕМЕНИ, а результат — в сравнение.

    Две клаузы, и обе обязательны. Только разбор времени — это «прочитали отметку»;
    только сравнение — это любая проверка поля. Фоссил НАЗВАН, когда читатель спросил,
    КОГДА был прошлый прогон, и СРАВНИЛ ответ с чем-то.
    """
    tainted = _spread(tree, _read_bindings(tree, artifact, resolver))
    if not tainted:
        return False
    aged = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _call_name(node) not in TIME_CALL_NAMES:
            continue
        reached = _names_in(node.func if isinstance(node.func, ast.Attribute) else node)
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            reached |= _names_in(arg)
        if reached & tainted:
            aged.add(node)
    if not aged:
        return False
    aged_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(a in ast.walk(node.value) for a in aged):
            aged_names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    aged_names = _spread(tree, aged_names)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left] + list(node.comparators)
        for operand in operands:
            if _names_in(operand) & aged_names:
                return True
            if any(a in ast.walk(operand) for a in aged):
                return True
    return False


# ─────────────────────────────────────────────────────────────────────────────────────
# Достижимость читателя из CI и объявленный писатель
# ─────────────────────────────────────────────────────────────────────────────────────

def _workflow_texts(root):
    """Тексты воркфлоу. Третий исход: каталога нет / файл нечитаем ⇒ причина НАЗВАНА."""
    wf_dir = root / ".github" / "workflows"
    if not wf_dir.is_dir():
        return None, "workflows_dir_missing"
    out = {}
    for path in sorted(wf_dir.glob("*.yml")) + sorted(wf_dir.glob("*.yaml")):
        try:
            out[path.name] = path.read_text(encoding="utf-8")
        except OSError as exc:
            return None, f"workflow_unreadable:{path.name}:{type(exc).__name__}"
    if not out:
        return None, "workflows_dir_empty"
    return out, None


def _plist_texts(root):
    """plist'ы флота — вторая половина объявленного радиуса писателя."""
    out = {}
    for base in ("launchd", "launchd_plists"):
        d = root / base
        if not d.is_dir():
            continue
        for path in sorted(d.rglob("*.plist")):
            try:
                out[str(path.relative_to(root))] = path.read_text(encoding="utf-8")
            except OSError:
                continue
    return out


def _reader_in_ci(rel_path, workflows):
    """Воркфлоу, упоминающие этого читателя: по пути, по модульному имени, по файлу."""
    stem = pathlib.PurePosixPath(rel_path).stem
    module = rel_path[:-3].replace("/", ".")
    file_re = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(stem) + r"\.py(?![A-Za-z0-9_])")
    hits = []
    for name, text in sorted(workflows.items()):
        if rel_path in text or module in text or file_re.search(text):
            hits.append(name)
    return hits


def _commit_calls(tree, resolver, rel):
    """Вызовы доставщика, получившие путь артефакта аргументом."""
    out = collections.defaultdict(list)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name not in COMMIT_CALL_NAMES:
            continue
        for expr in list(node.args) + [kw.value for kw in node.keywords]:
            for artifact in resolver.resolve(expr):
                out[artifact].append(f"{rel}:{node.lineno}:{name}")
    return out


def _committed_back(artifact, tracked_path, workflows, plists, commit_calls=()):
    """Объявленная автоматика, кладущая артефакт обратно в дерево.

    Ищется КОММИТ, а не упоминание: воркфлоу, печатающий путь в лог, писателем не
    является. Коммит руками цикла писателем тоже не является — у ADR-475 файл был
    закоммичен именно так и от этого фоссилом быть не перестал.
    """
    found = []
    for name, text in sorted(workflows.items()):
        if not any(form in text for form in COMMIT_FORMS):
            continue
        if artifact in text or (tracked_path and tracked_path in text):
            found.append(f"workflow:{name}")
    for name, text in sorted(plists.items()):
        if any(form in text for form in COMMIT_FORMS) and artifact in text:
            found.append(f"plist:{name}")
    found.extend(f"call:{c}" for c in commit_calls)
    # Дедуп обязателен: один вызов может получить путь ДВАЖДЫ (аргументом и через
    # `rel=`), и тогда перечень читался бы как два независимых писателя.
    return sorted(set(found))


def _tracked_data_files(root):
    """`git ls-files` по ВСЕМУ дереву — что именно лежит в репозитории.

    История НЕ спрашивается намеренно: в CI её нет по построению (`fetch-depth: 1`,
    ADR-479), и прибор, опирающийся на `git log`, отвечал бы на разных машинах разное.

    Радиус ВСЁ дерево, а не `data/`: первый черновик спрашивал только про `data/`, и
    `KANBAN.json` — файл В КОРНЕ репозитория, который читает `scripts/kanban_health.py`
    из двух джоб, — получил вердикт «в CI отсутствует» при том, что он git-tracked.
    Знаменатель переписи собирается по ИМЕНИ файла где угодно, значит и вопрос о
    отслеживании обязан идти по всему дереву: иначе вредная клетка гасится молча.
    """
    try:
        proc = subprocess.run(
            ["git", "ls-files"],
            cwd=str(root), capture_output=True, text=True, timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"git_unavailable:{type(exc).__name__}"
    if proc.returncode != 0:
        return None, f"git_ls_files_failed:rc={proc.returncode}"
    paths = [
        line.strip() for line in proc.stdout.splitlines()
        if line.strip() and ARTIFACT_NAME_RE.match(line.strip().rsplit("/", 1)[-1])
    ]
    return paths, None


# ─────────────────────────────────────────────────────────────────────────────────────
# Замер
# ─────────────────────────────────────────────────────────────────────────────────────

#: Сегменты пути, делающие файл ТЕСТОВЫМ ВХОДОМ, а не артефактом дерева.
FIXTURE_SEGMENTS = ("tests", "test", "fixtures", "fixture", "_fixtures", "testdata")


def _addressable(paths):
    """Какие из путей одного имени могут быть адресом, который читает РАНТАЙМ.

    Фикстура — вход теста, а не артефакт дерева: `tests/fixtures/golive_status.json`
    не есть второй адрес для `data/golive_status.json`, и считать его таковым значит
    выдумать неоднозначность. Замер 07.10: ровно это и случилось — хостовая ось дала
    ТРИ пары «НЕ ИЗМЕРЕНО» на `golive_status.json`, и ни одной настоящей
    двусмысленности за ними не стояло. Главная ось дала бы то же самое в тот день,
    когда любой из трёх читателей станет достижим из CI, то есть дефект был общий.

    Сужение НИКОГДА не меняет ответ на вопрос «файл git-tracked?»: если непустой
    остаток пуст, возвращается исходный перечень. Иначе «отслеживается» молча
    превратилось бы в «в CI отсутствует» — другой исход, другая беда.
    """
    kept = [
        rel for rel in paths
        if not (set(pathlib.PurePosixPath(rel).parts[:-1]) & set(FIXTURE_SEGMENTS))
    ]
    return kept or list(paths)


def _population(root):
    """Пары (читатель, артефакт), где модуль ПИШЕТ и ЧИТАЕТ один и тот же путь.

    Отдаёт ЧЕТВЁРТЫМ значением перечень разобранных модулей — по одной записи на файл
    с его деревом, разрешателем и ПОЛНЫМИ наборами мест записи и чтения. Пары есть
    пересечение этих двух наборов, то есть сужение; артефактной оси (заказ G104 п. 3)
    нужны они целиком, потому что её вопрос — о писателе файла, а не о самокарусельном
    читателе. Второго обхода дерева для этого не делается намеренно: два обхода видят
    разные множества молча (урок §49, «обход теста и обход графа»), и расхождение
    читалось бы как свойство дерева.
    """
    pairs = []
    unparsed = []
    modules = []
    commit_calls = collections.defaultdict(list)
    for base in SOURCE_ROOTS:
        base_dir = root / base
        if not base_dir.is_dir():
            continue
        for path in sorted(base_dir.rglob("*.py")):
            rel = str(path.relative_to(root))
            if "/tests/" in rel or path.name.startswith("test_"):
                continue
            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except (OSError, SyntaxError, ValueError, UnicodeDecodeError) as exc:
                unparsed.append({"reader": rel, "reason": f"unparsed:{type(exc).__name__}"})
                continue
            resolver = _PathResolver(tree)
            for artifact, calls in _commit_calls(tree, resolver, rel).items():
                commit_calls[artifact].extend(calls)
            writes, reads = _sites(tree, resolver)
            modules.append({
                "rel": rel,
                "writes": {a: sorted(lines) for a, lines in writes.items()},
                "reads": {a: sorted(lines) for a, lines in reads.items()},
                "_tree": tree,
                "_resolver": resolver,
            })
            for artifact in sorted(set(writes) & set(reads)):
                pairs.append({
                    "reader": rel,
                    "artifact": artifact,
                    "write_lines": sorted(writes[artifact]),
                    "read_lines": sorted(reads[artifact]),
                    "_tree": tree,
                    "_resolver": resolver,
                })
    return pairs, unparsed, commit_calls, modules


def _host_axis(pairs, tracked_by_name, workflows, plists, commit_calls, in_ci):
    """Заметил бы ХОСТОВЫЙ читатель, что операнд подменён закоммиченным каноном.

    Население — пары, у которых читатель НЕ достижим из CI (иначе это предмет главной
    оси) И артефакт git-tracked (иначе подменять нечем). Это ровно та цифра, которую
    ADR-524 доложил рядом и находкой не объявил.

    Ноги спрашиваются в объявленном порядке, и порядок — часть утверждения:

    1. ``host_unmeasured`` — ГРОМКИЙ третий исход с названной причиной. Имя артефакта
       лежит в репозитории по НЕСКОЛЬКИМ путям, и какой из них подменит канон —
       неизвестно; выбрать один значило бы догадаться (имя не есть адрес, ADR-465).
       Правило здесь ДОСЛОВНО то же, что у главной оси, и это не совпадение: ответ
       «не знаю адреса» не зависит от того, в CI мы или на хосте.

       Первая редакция ставила сюда другую причину — «ответ писателя у двух путей
       одного имени РАЗНЫЙ», — и эта ветка была НЕДОСТИЖИМА по построению: `_committed_back`
       признаёт писателя и по имени артефакта тоже, а имя есть подстрока КАЖДОГО своего
       пути, поэтому ответы двух путей совпадают всегда. Ветка, которая не срабатывает
       никогда, есть фальшивый третий исход, и нашёл её не глаз, а попытка написать для
       неё положительный контроль.
    2. ``host_canon_is_a_recent_run`` — объявленная автоматика кладёт артефакт обратно.
       Подмена заменяет наблюдение наблюдением на шаг старше; вреда заказа нет.
    3. ``host_parity_with_own_regeneration`` — читанное сверяется с ПЕРЕСБОРКОЙ в этом
       же прогоне. Подмена проявилась бы расхождением — замечена по построению.
    4. ``host_no_decision_against_a_current_observation`` — прошлый операнд нигде не
       встречается с наблюдением ЭТОГО прогона в решении. Подмена не переворачивает ни
       одного вердикта о мире; исключён с НАЗВАННОЙ причиной, а не зачтён в молчание.
    5. ``host_notices_by_age`` — читатель спрашивает, КОГДА был прошлый прогон, и
       сравнивает ответ. Возраст канона был бы виден.
    6. ``host_silently_trusts`` — **ответ заказа**: решение о мире принимается, пересборки
       нет, возраст не спрашивается. Закоммиченный канон молча становится «прошлым
       прогоном», и ни один сторож этого не скажет.

    Ось в сумму ГЛАВНЫХ исходов не входит и кода возврата не меняет — см. ``verdict``.
    """
    counts = {name: 0 for name in HOST_OUTCOMES}
    reasons = collections.Counter()
    silent, noticed, excluded = [], [], []
    population = 0
    under_radius = 0

    for pair in pairs:
        reader, artifact = pair["reader"], pair["artifact"]
        if in_ci.get(reader):
            continue
        candidates = sorted(tracked_by_name.get(artifact, ()))
        if not candidates:
            continue
        population += 1
        if all(c.startswith(CANON_SUBSTITUTION_RADIUS) for c in candidates):
            under_radius += 1
        row = {
            "reader": reader,
            "artifact": artifact,
            "tracked": candidates,
            "read_lines": pair["read_lines"],
            "write_lines": pair["write_lines"],
        }
        if len(candidates) > 1:
            counts[HOST_UNMEASURED] += 1
            reasons[
                f"artifact_name_ambiguous_in_repo:{artifact}:{len(candidates)}"
            ] += 1
            continue
        if _committed_back(
            artifact, candidates[0], workflows, plists, commit_calls.get(artifact, ()),
        ):
            counts[HOST_CANON_IS_A_RECENT_RUN] += 1
            continue
        tree, resolver = pair["_tree"], pair["_resolver"]
        if _parity_with_own_regeneration(tree, artifact, resolver):
            counts[HOST_PARITY] += 1
            noticed.append(dict(row, why=HOST_PARITY))
            continue
        if not _meets_a_current_observation(tree, artifact, resolver):
            counts[HOST_NO_DECISION] += 1
            excluded.append(dict(row, why=HOST_NO_DECISION))
            continue
        if _asks_the_age(tree, artifact, resolver):
            counts[HOST_NOTICES_BY_AGE] += 1
            noticed.append(dict(row, why=HOST_NOTICES_BY_AGE))
            continue
        counts[HOST_SILENTLY_TRUSTS] += 1
        silent.append(row)

    notes = []
    total = sum(counts.values())
    if total != population:
        notes.append(
            f"сумма хостовых исходов {total} != хостовому населению {population}"
            " — ОТКАЗ формы"
        )
    return {
        "order": "G104.2",
        "population": population,
        "under_substitution_radius": under_radius,
        "outcomes": counts,
        "unmeasured_reasons": dict(reasons),
        "silent": sorted(silent, key=lambda r: (r["reader"], r["artifact"])),
        "noticed_sample": sorted(noticed, key=lambda r: (r["reader"], r["artifact"])),
        "excluded_sample": sorted(excluded, key=lambda r: (r["reader"], r["artifact"])),
        "notes": notes,
    }


def _artifact_axis(modules, tracked_by_name, workflows, plists, commit_calls):
    """У скольких git-tracked артефактов ВООБЩЕ нет объявленного писателя (G104 п. 3).

    Единица населения — git-tracked ПУТЬ, а не пара: заказ спрашивает про файл. Ноги
    в объявленном порядке, и порядок — часть утверждения:

    1. ``artifact_unmeasured`` — ГРОМКИЙ третий исход с названной причиной. Имя лежит в
       репозитории по НЕСКОЛЬКИМ адресуемым путям, и какой из них имеет в виду рантайм —
       неизвестно (имя не есть адрес, ADR-465). Считается по ПУТЯМ, а не по именам:
       иначе сумма исходов перестала бы равняться числу файлов.
    2. ``artifact_not_produced_in_runtime`` — в дереве нет ни одного места записи этого
       файла. Курируемый файл (вайтлист, критерии, фикстура) — законная константа: он
       и не выдаёт себя за результат прогона. Спрашивать это ВТОРЫМ обязательно, иначе
       перепись объявила бы дефектом каждый конфиг репозитория.
    3. ``artifact_writer_declared`` — объявленная автоматика кладёт результат обратно.
       Тогда закоммиченная копия есть наблюдение (пусть на шаг старое) — ровно то, чего
       заказ и хочет от остальных.
    4. ``no_declared_writer_and_unread_in_tree`` — писателя нет, и в дереве файл не
       читает никто. Вред ЛАТЕНТЕН: подменённый канон сегодня не вводит в заблуждение
       ни одного читателя. Назван отдельным исходом, а не слит в находку.
    5. ``no_declared_writer_and_read`` — **ОТВЕТ заказа**: файл производится в рантайме,
       его читают, и обратно не кладёт его никто. В любом дереве, которое производителя
       не запускало — CI, свежий клон, новый worktree, развёрнутый резерв — каждый его
       читатель получает закоммиченные байты, то есть КОНСТАНТУ.

    Имя исхода названо по ЗАМЕРУ, а не по следствию, и это существенно: ось НЕ
    утверждает, что подмену никто бы не заметил. «Заметил бы» — вопрос двух осей выше
    (там он задаётся читателю) и честно названный остаток: известный член исхода, у
    которого расхождение ВСЁ ЖЕ покраснеет, — `architecture/manifest.json`. Почему ноги
    на это у оси нет, сказано замером над ``ARTIFACT_OUTCOMES``.

    Односторонность названа заранее: ``artifact_not_produced_in_runtime`` есть ВЕРХНЯЯ
    граница курируемых файлов, потому что место записи видно на один уровень помощника
    (та же оговорка, что у главной оси) — значит ``no_declared_writer_and_read`` есть
    НИЖНЯЯ граница находки, а не точное число.
    """
    writes_by_name = collections.defaultdict(list)
    reads_by_name = collections.defaultdict(list)
    for mod in modules:
        for artifact, lines in mod["writes"].items():
            writes_by_name[artifact].extend(f"{mod['rel']}:{ln}" for ln in lines)
        for artifact, lines in mod["reads"].items():
            reads_by_name[artifact].extend(f"{mod['rel']}:{ln}" for ln in lines)
    counts = {name: 0 for name in ARTIFACT_OUTCOMES}
    reasons = collections.Counter()
    findings, declared = [], []
    population = 0
    under_radius = 0

    for artifact, paths in sorted(tracked_by_name.items()):
        # Имя БЕЗ адреса — вход, которого `measure` не производит (`_addressable` отдаёт
        # непустой перечень по построению), но ось получает перечень ПАРАМЕТРОМ, а
        # инъектированный вход двери чтения не касается (урок ADR-594). Без этой ветви
        # такой вход давал `IndexError` — то есть прибор падал там, где обязан громко
        # сказать «не измерено». Единица населения при этом ОДНА: имя, которое мы не
        # сумели адресовать, есть один неотвеченный вопрос, а не ноль вопросов.
        if not paths:
            population += 1
            counts[ART_UNMEASURED] += 1
            reasons[f"artifact_name_without_an_address:{artifact}"] += 1
            continue
        population += len(paths)
        if len(paths) > 1:
            counts[ART_UNMEASURED] += len(paths)
            reasons[
                f"artifact_name_ambiguous_in_repo:{artifact}:{len(paths)}"
            ] += len(paths)
            continue
        path = paths[0]
        writers = writes_by_name.get(artifact, [])
        if not writers:
            counts[ART_NO_RUNTIME_WRITER] += 1
            continue
        writer_modules = sorted({w.split(":")[0] for w in writers})
        committed = _committed_back(
            artifact, path, workflows, plists, commit_calls.get(artifact, ()),
        )
        if committed:
            counts[ART_WRITER_DECLARED] += 1
            declared.append({
                "artifact": path, "writers": writer_modules, "declared": committed,
            })
            continue
        readers = sorted({r.split(":")[0] for r in reads_by_name.get(artifact, ())})
        if not readers:
            counts[ART_NO_WRITER_UNREAD] += 1
            continue
        counts[ART_NO_WRITER_READ] += 1
        if path.startswith(CANON_SUBSTITUTION_RADIUS):
            under_radius += 1
        findings.append({
            "artifact": path,
            "writers": writer_modules,
            "readers": readers,
            "reader_count": len(readers),
        })

    notes = []
    # САМОПРОВЕРКА, а не третий исход — и это ИЗМЕРЕНО, а не предположено: прицельный
    # мутант, снимающий эту ветвь целиком, ПЕРЕЖИЛ батарею (ADR-622), потому что по
    # построению каждый путь увеличивает ровно один счётчик и сумма разойтись не может.
    # Ветвь оставлена как тревожная нить против будущей правки и ради единой формы с
    # двумя соседними осями, у которых та же самопроверка. Настоящий третий исход оси —
    # `ART_UNMEASURED`, он достижим и закреплён контролями в обе стороны.
    total = sum(counts.values())
    if total != population:
        notes.append(
            f"сумма артефактных исходов {total} != артефактному населению {population}"
            " — ОТКАЗ формы"
        )
    return {
        "order": "G104.3",
        "population": population,
        "under_substitution_radius": under_radius,
        "outcomes": counts,
        "unmeasured_reasons": dict(reasons),
        "findings": sorted(findings, key=lambda r: (-r["reader_count"], r["artifact"])),
        "declared": sorted(declared, key=lambda r: r["artifact"]),
        "notes": notes,
    }


def measure(root, tracked=None, workflows=None, plists=None):
    """Замер. Внешние двери приходят ВХОДОМ — иначе тест судил бы о живой машине."""
    root = pathlib.Path(root)
    notes = []

    if tracked is None:
        tracked, why = _tracked_data_files(root)
        if tracked is None:
            return {
                "applied": APPLIED,
                "order": "G86.3",
                "population": 0,
                "outcomes": {name: 0 for name in OUTCOMES},
                "unmeasured_reasons": {why: 1},
                "findings": [],
                "named_sample": [],
                "measured": False,
                "why_unmeasured": why,
                "notes": notes,
            }
    # Все пути с этим именем, а НЕ первый попавшийся: `track_snapshot.json` лежит в
    # репозитории дважды (`data/` и `landing/src/data/`), и выбор одного из двух был бы
    # догадкой о том, какой файл имел в виду читатель. Догадка здесь запрещена: имя не
    # есть адрес (ADR-465), поэтому двусмысленность уходит в третий исход ГРОМКО.
    tracked_by_name = collections.defaultdict(list)
    for rel in tracked:
        tracked_by_name[pathlib.PurePosixPath(rel).name].append(rel)
    # Одно правило — один читатель (ADR-460): сужение до адресуемых путей делается ЗДЕСЬ,
    # и обе оси получают один и тот же перечень. Копия этого правила внутри хостовой оси
    # была бы вторым определением «какой путь имел в виду читатель».
    tracked_by_name = {
        name: _addressable(paths) for name, paths in tracked_by_name.items()
    }

    if workflows is None:
        workflows, why = _workflow_texts(root)
        if workflows is None:
            return {
                "applied": APPLIED,
                "order": "G86.3",
                "population": 0,
                "outcomes": {name: 0 for name in OUTCOMES},
                "unmeasured_reasons": {why: 1},
                "findings": [],
                "named_sample": [],
                "measured": False,
                "why_unmeasured": why,
                "notes": notes,
            }
    if plists is None:
        plists = _plist_texts(root)

    pairs, unparsed, commit_calls, modules = _population(root)
    outcomes = {name: 0 for name in OUTCOMES}
    reasons = collections.Counter()
    findings, named_sample, committed_sample, excluded_sample = [], [], [], []

    for item in unparsed:
        outcomes[OUT_UNMEASURED] += 1
        reasons[item["reason"]] += 1

    # Достижимость из CI спрашивается ОДИН раз на читателя и кладётся в кэш: прежняя
    # редакция звала правило дважды — в главном цикле и у хостовой цифры рядом, — и две
    # копии одного правила расходятся молча (порядок ADR-460: одно правило — один
    # читатель). Контроль на это расхождение есть в батарее хостовой оси.
    # Радиус кэша — ВСЕ разобранные модули, а не только читатели пар: артефактной оси
    # (G104 п. 3) нужен ответ про ПРОИЗВОДИТЕЛЯ файла, который самокарусельным читателем
    # быть не обязан. Для пар ответ при этом тот же самый, и это существенно: второй
    # кэш был бы вторым читателем одного правила.
    in_ci_by_reader = {
        mod["rel"]: _reader_in_ci(mod["rel"], workflows) for mod in modules
    }

    for pair in pairs:
        reader, artifact = pair["reader"], pair["artifact"]
        in_ci = in_ci_by_reader[reader]
        if not in_ci:
            outcomes[OUT_NOT_IN_CI] += 1
            continue
        candidates = sorted(tracked_by_name.get(artifact, ()))
        if not candidates:
            outcomes[OUT_ABSENT_IN_CI] += 1
            continue
        if len(candidates) > 1:
            outcomes[OUT_UNMEASURED] += 1
            reasons[f"artifact_name_ambiguous_in_repo:{artifact}:{len(candidates)}"] += 1
            continue
        tracked_path = candidates[0]
        writers = _committed_back(
            artifact, tracked_path, workflows, plists, commit_calls.get(artifact, ()),
        )
        if writers:
            outcomes[OUT_COMMITTED_BACK] += 1
            committed_sample.append({
                "reader": reader, "artifact": tracked_path, "writers": writers,
            })
            continue
        row = {
            "reader": reader,
            "artifact": tracked_path,
            "workflows": in_ci,
            "read_lines": pair["read_lines"],
            "write_lines": pair["write_lines"],
        }
        tree, resolver = pair["_tree"], pair["_resolver"]
        if _parity_with_own_regeneration(tree, artifact, resolver):
            outcomes[OUT_PARITY] += 1
            excluded_sample.append(dict(row, why=OUT_PARITY))
            continue
        if not _meets_a_current_observation(tree, artifact, resolver):
            outcomes[OUT_NO_DECISION] += 1
            excluded_sample.append(dict(row, why=OUT_NO_DECISION))
            continue
        if _asks_the_age(tree, artifact, resolver):
            outcomes[OUT_CONST_NAMED] += 1
            named_sample.append(row)
        else:
            outcomes[OUT_CONST_TRUSTED] += 1
            findings.append(row)

    # ИЗМЕРЕННОЕ число рядом, а не исход: на хосте файл на диске ЕСТЬ прошлый прогон,
    # поэтому вреда заказа здесь нет. Но это ровно то население, которое `git checkout
    # -- data/` молча подменяет закоммиченным каноном (авария цикла #361: одна команда
    # откатила 116 файлов на три недели). Форма исходов остаётся ЗАКРЫТОЙ: цифра
    # докладывается, в сумму не входит и находкой не объявляется.
    #
    # Заказ G104 п. 2 просит у этой цифры то, чего ADR-524 у неё не спросил: сколько из
    # них ЗАМЕТИЛИ БЫ подмену. Ось считается теми же ногами и живёт отдельным разделом.
    host = _host_axis(
        pairs, tracked_by_name, workflows, plists, commit_calls, in_ci_by_reader,
    )
    host_only_but_tracked = host["population"]

    # Третья ось спрашивает про ФАЙЛ, а не про пару: у скольких git-tracked артефактов
    # вообще нет объявленного писателя (заказ G104 п. 3). В суммы двух осей выше она не
    # входит и складыванию с ними НЕ подлежит — у них разные единицы населения (пара
    # против пути), и одно и то же дерево попадает в обе.
    artifact = _artifact_axis(
        modules, tracked_by_name, workflows, plists, commit_calls,
    )

    population = len(pairs) + len(unparsed)
    total = sum(outcomes.values())
    if total != population:
        notes.append(f"сумма исходов {total} != населению {population} — ОТКАЗ формы")

    return {
        "applied": APPLIED,
        "order": "G86.3",
        "population": population,
        "readers": len({p["reader"] for p in pairs}),
        "host_only_but_git_tracked": host_only_but_tracked,
        "host_axis": host,
        "artifact_axis": artifact,
        "outcomes": outcomes,
        "unmeasured_reasons": dict(reasons),
        "findings": sorted(findings, key=lambda r: (r["reader"], r["artifact"])),
        "named_sample": sorted(named_sample, key=lambda r: (r["reader"], r["artifact"])),
        "committed_sample": sorted(committed_sample, key=lambda r: (r["reader"], r["artifact"])),
        "excluded_sample": sorted(excluded_sample, key=lambda r: (r["reader"], r["artifact"])),
        "measured": True,
        "why_unmeasured": None,
        "notes": notes,
        "not_reported": [
            "читатель ЧУЖОГО прошлого прогона — не измерен вовсе, это следующий "
            "вопрос (заказ G104 п. 1)",
            "артефактная ось судит ПИСАТЕЛЯ файла, а не поведение его читателей: "
            "курируемость видна на один уровень помощника, поэтому "
            f"{ART_NO_RUNTIME_WRITER} есть ВЕРХНЯЯ граница, а {ART_NO_WRITER_READ} — "
            "НИЖНЯЯ",
            "артефактная ось НЕ спрашивает «а заметил бы кто-нибудь»: ноги сверки "
            "канона с пересборкой у неё нет, и это решение с ЗАМЕРОМ (комментарий над "
            "ARTIFACT_OUTCOMES). Известные члены исхода "
            f"{ART_NO_WRITER_READ}, у которых расхождение ВСЁ ЖЕ покраснеет, названы "
            "руками: architecture/manifest.json ← scripts/fill_agent_passports.py "
            "--check · landing/src/lib/constitution.json ← scripts/tests/"
            "test_site_constitution_parity.py",
            "хостовая ось видит ПРИЗНАК замечания (пересборка, возраст, встреча с "
            "наблюдением), а не верность порога и ветвления у замечающего",
            "точный радиус подменяющей команды доложен числом под data/; подменить "
            "можно и шире (`git checkout -- .`), поэтому из населения пара не выкинута",
            "верность порога и ветвления у названного фоссила",
            "запись глубже одного локального помощника — население нижняя граница",
            "читатель, позванный окольно из джобы — считается недостижимым",
            "верность самой проверки паритета и самого валидатора документа",
        ],
    }


def verdict(doc):
    """Код возврата: три РАЗЛИЧИМЫХ исхода, и «не измерено» никогда не 0.

    **Хостовая ось кода НЕ повышает до находки, и это РЕШЕНИЕ с названной причиной.**
    На рабочей машине файл на диске ЕСТЬ результат прошлого прогона, то есть операнд
    там наблюдение; вред возникает только от команды, которую `.claude/rules/deployment.md`
    п. 4 уже ЗАПРЕЩАЕТ. Объявить двести хостовых пар находкой значило бы потребовать
    убрать чтение собственного журнала у каждого агента флота — и красный навсегда
    приучил бы гасить прибор. Ось отвечает на другой вопрос: каков радиус поражения
    запрещённой команды и кто из поражённых не скажет об этом ни слова.

    А вот «не измерено» хостовой оси код ПОВЫШАЕТ: неразобранная пара и отказ формы —
    это провал замера, а не свойство дерева (инв. #17).

    **Артефактная ось (G104 п. 3) кода тоже НЕ повышает — и причина у неё СВОЯ, не
    переписанная у соседа.** У хостовой оси причина в том, что вред возникает только от
    запрещённой команды; здесь вред возникает от обычного `git clone` и живёт в дереве
    постоянно. Причина другая: лекарств у каждой клетки ТРИ (объявить писателя · снять
    файл с отслеживания · научить читателя спрашивать возраст), выбор между ними
    по-файлово, а у самых дорогих клеток — `data/equity_curve_daily.json`,
    `data/trades.json` — он задевает предмет №1 границы ADR-285 и принадлежит владельцу.
    Красный навсегда на таком населении приучил бы гасить прибор — ровно то, против чего
    инв. #16. Число докладывается и называется находкой В ОТЧЁТЕ, а не кодом возврата.

    **Её «не измерено» код тоже не повышает, а ОТКАЗ ФОРМЫ — повышает.** Различие
    измеримое, а не вкусовое: артефактное «не измерено» есть свойство ДЕРЕВА — два
    git-tracked файла носят одно имя, и какой из них пишет модуль, по имени неизвестно
    (имя не есть адрес, ADR-465). Таких путей 9 из 475, они посчитаны и названы
    поимённо, и остальные 466 ответов от этого менее измеренными не становятся. Поднять
    на них код значило бы навсегда поставить 2 из-за `package-lock.json` и ЗАМАСКИРОВАТЬ
    тем самым сигнал главной оси: «в дереве появился НОВЫЙ сторож класса ADR-475» (код 1)
    стал бы неотличим от «замер не удался». Отказ формы (сумма != населению) — другое: это
    провал прибора, и он код поднимает.
    """
    if not doc.get("measured"):
        return RC_UNMEASURED
    if doc["outcomes"][OUT_UNMEASURED]:
        return RC_UNMEASURED
    if doc["notes"]:
        return RC_UNMEASURED
    host = doc.get("host_axis")
    if host is None:
        return RC_UNMEASURED
    if host["notes"] or host["outcomes"][HOST_UNMEASURED]:
        return RC_UNMEASURED
    artifact = doc.get("artifact_axis")
    if artifact is None:
        return RC_UNMEASURED
    if artifact["notes"]:
        return RC_UNMEASURED
    return RC_FINDING if doc["outcomes"][OUT_CONST_TRUSTED] else RC_MEASURED


#: Сколько молчаливых пар печатать поимённо. Население хостовой оси — сотни, и полный
#: перечень в шаге 0-офис утопил бы соседние секции; остаток назван ЧИСЛОМ, а не
#: многоточием, и целиком доступен через `--json`.
HOST_SILENT_SAMPLE = 12


def _host_lines(doc):
    """Раздел хостовой оси. Отсутствие раздела — третий исход, а не пустота."""
    host = doc.get("host_axis")
    if host is None:
        return [
            "  [НЕ ИЗМЕРЕНО] хостовая ось (заказ G104 п. 2) не считалась: документ "
            "замера её не несёт"
        ]
    out = host["outcomes"]
    lines = [
        f"  — хостовая ось (заказ G104 п. 2): заметил бы читатель подмену операнда "
        f"ЗАКОММИЧЕННЫМ каноном — население {host['population']} пар(ы), из них в радиусе "
        f"дословной команды аварии #361 (`git checkout -- {CANON_SUBSTITUTION_RADIUS}`) "
        f"{host['under_substitution_radius']}",
        "    " + " · ".join(f"{name} {out[name]}" for name in HOST_OUTCOMES),
    ]
    for row in host["silent"][:HOST_SILENT_SAMPLE]:
        lines.append(
            f"    [МОЛЧА ПРИМЕТ КАНОН ЗА ПРОШЛЫЙ ПРОГОН] {row['reader']} читает "
            f"{row['artifact']} (строки {row['read_lines']}): решение о мире есть, "
            f"пересборки нет, возраст не спрашивается"
        )
    rest = len(host["silent"]) - HOST_SILENT_SAMPLE
    if rest > 0:
        lines.append(
            f"    … ещё {rest} молчаливых пар(ы) того же вида (полный перечень — `--json`)"
        )
    if out[HOST_NO_DECISION]:
        lines.append(
            f"    ЦЕНА ноги «решения нет» НАЗВАНА, а не умолчана: ею исключены "
            f"{out[HOST_NO_DECISION]} пар(ы) — самый населённый исход оси. Нога "
            "спрашивает про РЕШЕНИЕ против наблюдения этого прогона; пара, которая "
            "прочитанное не сравнивает, а ПЕРЕПУБЛИКУЕТ в свой же вывод, подменённый "
            "канон разносит дальше, и этого прибор не спрашивает ни у одной из них"
        )
    for reason, count in sorted(host["unmeasured_reasons"].items()):
        lines.append(f"    [НЕ ИЗМЕРЕНО] {reason}: {count}")
    for note in host["notes"]:
        lines.append(f"    [ОТКАЗ] {note}")
    lines.append(
        "    ось в сумму ГЛАВНЫХ исходов НЕ входит и кода возврата НЕ повышает: на хосте "
        "файл на диске есть прошлый прогон, вред возникает только от команды, запрещённой "
        "`.claude/rules/deployment.md` п. 4"
    )
    return lines


#: Сколько находок артефактной оси печатать поимённо. Население — сотни файлов, и
#: полный перечень утопил бы соседние секции шага 0-офис; остаток назван ЧИСЛОМ, а не
#: многоточием, и целиком доступен через `--json`. Порядок печати — по числу читателей
#: убывающе: дороже всего клетка, чью константу читают из многих мест.
ARTIFACT_SAMPLE = 10


def _artifact_lines(doc):
    """Раздел артефактной оси. Отсутствие раздела — третий исход, а не пустота."""
    art = doc.get("artifact_axis")
    if art is None:
        return [
            "  [НЕ ИЗМЕРЕНО] артефактная ось (заказ G104 п. 3) не считалась: документ "
            "замера её не несёт"
        ]
    out = art["outcomes"]
    lines = [
        f"  — артефактная ось (заказ G104 п. 3): у скольких git-tracked артефактов НЕТ "
        f"объявленного писателя — население {art['population']} файл(ов), находок в "
        f"радиусе дословной команды аварии #361 "
        f"(`git checkout -- {CANON_SUBSTITUTION_RADIUS}`) {art['under_substitution_radius']}",
        "    " + " · ".join(f"{name} {out[name]}" for name in ARTIFACT_OUTCOMES),
    ]
    for row in art["findings"][:ARTIFACT_SAMPLE]:
        lines.append(
            f"    [ПИСАТЕЛЯ НЕ ОБЪЯВЛЕНО, а читают] {row['artifact']} — пишут в рантайме "
            f"{len(row['writers'])}, читают {row['reader_count']}; обратно не кладёт "
            "его никакая объявленная автоматика"
        )
    rest = len(art["findings"]) - ARTIFACT_SAMPLE
    if rest > 0:
        lines.append(
            f"    … ещё {rest} артефакт(ов) того же вида (полный перечень — `--json`)"
        )
    for row in art["declared"]:
        lines.append(
            f"    [писатель ОБЪЯВЛЕН] {row['artifact']} — {row['declared']}"
        )
    for reason, count in sorted(art["unmeasured_reasons"].items()):
        lines.append(f"    [НЕ ИЗМЕРЕНО] {reason}: {count}")
    for note in art["notes"]:
        lines.append(f"    [ОТКАЗ] {note}")
    lines.append(
        "    ось считает ПУТИ, а не пары, и с двумя осями выше складыванию НЕ подлежит: "
        "единицы населения разные, и одно дерево попадает в обе"
    )
    return lines


def format_report(doc):
    lines = []
    if not doc.get("measured"):
        lines.append(f"НЕ ИЗМЕРЕНО: {doc.get('why_unmeasured')}")
        return "\n".join(lines)
    out = doc["outcomes"]
    lines.append(
        f"операнд «предыдущий прогон» из git-tracked артефакта (заказ G86 п. 3): "
        f"население {doc['population']} пар(ы) у {doc.get('readers', 0)} читател(ей)"
    )
    lines.append(
        "  " + " · ".join(f"{name} {out[name]}" for name in OUTCOMES)
    )
    for row in doc["findings"]:
        lines.append(
            f"  [КОНСТАНТА, молчаливо принятая за прошлый прогон] {row['reader']}"
            f" читает {row['artifact']} (строки {row['read_lines']}), джобы "
            f"{row['workflows']}: файл git-tracked, обратно его не коммитит никакая "
            f"объявленная автоматика, возраст прошлого артефакта не спрашивается"
        )
    for row in doc["named_sample"]:
        lines.append(
            f"  [константа, но ФОССИЛ НАЗВАН] {row['reader']} читает {row['artifact']}"
            f" — возраст прошлого артефакта спрашивается"
        )
    lines.extend(_host_lines(doc))
    lines.extend(_artifact_lines(doc))
    for row in doc.get("excluded_sample", ()):
        lines.append(
            f"  [ИСКЛЮЧЁН со причиной] {row['reader']} :: {row['artifact']} — {row['why']}"
        )
    for row in doc["committed_sample"]:
        lines.append(
            f"  [операнд есть наблюдение] {row['reader']} :: {row['artifact']}"
            f" — коммитит обратно {row['writers']}"
        )
    for reason, count in sorted(doc["unmeasured_reasons"].items()):
        lines.append(f"  [НЕ ИЗМЕРЕНО] {reason}: {count}")
    for note in doc["notes"]:
        lines.append(f"  [ОТКАЗ] {note}")
    lines.append("  НЕ ДОКЛАДЫВАЕТ: " + " · ".join(doc["not_reported"]))
    lines.append("  ADVISORY: прибор только ЧИТАЕТ (applied=False)")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="корень дерева репозитория")
    parser.add_argument("--json", action="store_true", help="печатать документ замера")
    args = parser.parse_args(argv)
    doc = measure(pathlib.Path(args.root))
    printable = {k: v for k, v in doc.items() if not k.startswith("_")}
    print(json.dumps(printable, ensure_ascii=False, indent=2) if args.json
          else format_report(doc))
    return verdict(doc)


if __name__ == "__main__":
    sys.exit(main())
