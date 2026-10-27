#!/usr/bin/env python3
"""Какие тесты краснеют от ДЛИТЕЛЬНОСТИ прогона, а не от поведения кода.

Класс найден 12.09 (цикл красного шага 2). Якорь времени вида ``NOW = now_utc()``
на уровне модуля вычисляется на **СБОРЕ** набора — в первые секунды прогона. Субъект
же спрашивает настоящие часы в **момент выполнения**. В одиночном прогоне между этими
мгновениями доли секунды, в полном — полтора часа, и запись, поставленная «120 секунд
назад», оказывается старше получасового окна. Тест краснеет от того, сколько идёт
набор.

**Чем это отличается от уже известной бомбы.** ``.claude/rules/deployment.md`` держит
класс «фиксированная дата», и храповик ``frozen_date_baseline.json`` этот случай **не
видит по построению**: литеральной даты здесь нет вовсе. Фитиль другой — не календарь,
а длительность набора; и чем полнее прогон, тем вернее взрыв, то есть дефект прячется
именно в том режиме, который гейтит CI.

**Почему замер дифференциальный, а не статический.** Якорь на импорте берут 24
тест-файла (замер 12.09), а бомб среди них ТРИ. Статический список назвал бы виновными
все 24 — это не сторож, а машина ложных срабатываний; она учит дописывать в базу.
Поэтому вердикт даёт только состаривание якоря: прогон при задержке 0 и при задержке N
минут, и предметом класса является тест, у которого от этого **меняется вердикт**.
Мерить надо и переход в ``skipped``: исчезнувший тест глазами читается как «всё
в порядке» (урок #465).

**Третий исход обязателен (инв. #17).** Не собрали население, не запустился pytest,
не разобрали вывод ⇒ «НЕ ИЗМЕРЕНО» с названной причиной и ненулевой код возврата.
«Не измерено» никогда не выдаётся за «чисто».

Запуск (замер длится ~2 мин, потому и не живёт внутри набора — второй прогон pytest
в ТОМ ЖЕ дереве столкнулся бы с основным):

    python3 scripts/import_time_anchor_bombs.py [--lag-min 95]

Коды возврата: 0 — бомб нет · 1 — бомбы названы · 2 — НЕ ИЗМЕРЕНО.
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]

#: Имена часов: вызов любого из них на верхнем уровне модуля и есть якорь на импорте.
CLOCKS = {"now_utc", "utcnow", "now", "time"}

#: Где живут тесты, которые гейтит CI (та же четвёрка, что в команде из CLAUDE.md).
TEST_DIRS = ("spa_core/tests", "tests", "scripts/tests", "research/cards")

#: Задержка по умолчанию — фактическая длительность полного прогона (замер 12.09:
#: 94 мин). Меньше брать нельзя: класс тем и опасен, что проявляется только в длинном
#: прогоне.
DEFAULT_LAG_MIN = 95.0

#: Строки короткой сводки (`-rfEs`), несущие ИМЯ не прошедшего теста. `SUBFAILED` —
#: падение под `self.subTest`; сам тест при этом печатается точкой и попадает в
#: «N passed», поэтому без этого слова бомба, чей взрыв живёт под `subTest`, была
#: приборУ неотличима от прошедшего теста НА ОБЕИХ сторонах сравнения (замер #951 на
#: настоящем pytest 9.0.3; тот же дефект найден в `delta_mutation_run._FAILED_LINE`).
#: Суффикс формы `(n=1)` / `(n=1, k='a b')` / `(<subtest>)` / `[метка]` стои́т ВНЕ
#: группы вердикта: в нём бывают пробелы, и имя нельзя брать «вторым словом».
#: Первая редакция правки #951 сужала группу до одного `SUBFAILED` «на всякий случай» —
#: прибор по дельте показал мутанта этого сужения ВЫЖИВШИМ, и выживший оказался
#: ЭКВИВАЛЕНТНЫМ: сужение было украшением. Договор закреплён сценой, а не формой регекса.
#:
#: **`SKIPPED` в этой группе больше НЕТ, и это правка #952 (заказ G827 п. 1).** Короткая
#: сводка имени пропущенного теста не печатает ВООБЩЕ: строка выглядит как
#: `SKIPPED [n] файл:строка: причина`, где `[n]` — РАЗМЕР ГРУППЫ (пропуски сводятся по
#: паре «место + причина»), а не номер и не имя. Пробел перед `[n]` не давал
#: необязательной группе к нему приложиться, поэтому ключом вердикта становился сам
#: счётчик `[1]` — то есть ПОРЯДОК, а не личность. ЗАМЕР на настоящем pytest 9.0.3
#: (цикл #952, две сцены: пропуск «пока прогон короткий» и пропуск «когда прогон
#: длинный»): задержка меняла вердикт ОБОИХ тестов, у обеих сторон ключ выходил `[1]`,
#: сравнение давало равенство, и прибор печатал «Бомб нет» при `__passed__` = 1 на обеих
#: сторонах — окольной улики нет, и ошибка шла в сторону САМОУСПОКОЕНИЯ. На этом ключе
#: стои́т урок #465 про переход в `skipped`, то есть слепым был ровно тот переход, ради
#: которого прибор и мерит обе стороны. Место в строке личностью тоже НЕ является и это
#: измерено: `raise unittest.SkipTest` из простой функции печатает место ВНУТРИ pytest
#: (`_pytest/unittest.py:502`), и четыре разных теста сводятся там к двум группам.
#: Поэтому пропуски читаются ОТДЕЛЬНОЙ дверью — `_skips_from_junit`, по имени теста.
_OUTCOME = re.compile(
    r"^(FAILED|ERROR|SUBFAILED)(?:\([^)]*\)|\[[^\]]*\])?\s+(\S+)", re.M)

#: Итоговая строка pytest. Её ОТСУТСТВИЕ и есть «не смогли измерить».
_SUMMARY = re.compile(r"\d+ (?:passed|failed|error|errors|skipped)", re.I)


class NotMeasured(RuntimeError):
    """Замер не состоялся. Причина обязана быть названа."""


def _skips_from_junit(xml_path: Path, lag_min: float) -> dict[str, str]:
    """Пропущенные тесты ПО ИМЕНИ — то, чего короткая сводка не печатает вовсе.

    Короткая сводка сводит пропуски в группы «место + причина» и печатает РАЗМЕР
    группы (`SKIPPED [3] …`), а не имена. Поэтому вопрос прибора — «у КАКОГО теста
    сменился вердикт» — на ней не разрешим в принципе, и до #952 ключом становился
    счётчик. Отчёт `--junit-xml` (встроенный в pytest, плагин не нужен) несёт
    `classname` + `name` на КАЖДЫЙ тест, в том числе параметризованный, поэтому
    обмен двух пропусков местами перестаёт быть равенством.

    Дверь намеренно УЗКАЯ: имена падений по-прежнему читаются из короткой сводки.
    `SUBFAILED` — понятие `pytest-subtests`, и в junit отдельным исходом не живёт;
    переводить на junit всё означало бы выкинуть договор #951, не измерив замену.
    Это названная граница, а не недосмотр.

    Третий исход обязателен (инв. #17): отчёта нет или он не разобран ⇒ отказ с
    причиной, а не пустой словарь, который был бы неотличим от «пропусков не было».
    """
    if not xml_path.exists():
        raise NotMeasured(f"pytest не оставил junit-отчёт {xml_path} "
                          f"(задержка {lag_min} мин) — какие тесты пропущены, не измерено")
    try:
        tree = ElementTree.parse(xml_path)
    except ElementTree.ParseError as exc:
        raise NotMeasured(f"junit-отчёт не разобран (задержка {lag_min} мин): {exc}") from exc
    skipped: dict[str, str] = {}
    for case in tree.iter("testcase"):
        if case.find("skipped") is None:
            continue
        cls, name = case.get("classname") or "", case.get("name") or ""
        if not name:
            raise NotMeasured(f"junit-отчёт назвал пропуск без имени теста "
                              f"(задержка {lag_min} мин): classname={cls!r}")
        skipped[f"{cls}::{name}" if cls else name] = "SKIPPED"
    return skipped


def anchored_at_import(root: Path = ROOT) -> list[tuple[str, str, int]]:
    """Файлы, берущие якорь времени НА ИМПОРТЕ: (путь, имя якоря, строка).

    Разбирается ТОЛЬКО верхний уровень модуля: тот же вызов внутри функции происходит
    в момент выполнения и бомбой не является. Файл не разобрался ⇒ третий исход,
    а не пропуск: неразобранный файл неотличим от чистого только для того, кто его
    не мерил.
    """
    found: list[tuple[str, str, int]] = []
    unparsed: list[str] = []
    for d in TEST_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("test_*.py")):
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                unparsed.append(f"{p.relative_to(root)}: {exc}")
                continue
            for node in tree.body:
                if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                    continue
                fn = node.value.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
                if name not in CLOCKS:
                    continue
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        found.append((str(p.relative_to(root)), t.id, node.lineno))
    if unparsed:
        raise NotMeasured("не разобраны файлы: " + "; ".join(unparsed[:5]))
    return found


def outcomes(files: list[str], lag_min: float, root: Path = ROOT) -> dict[str, str]:
    """Вердикт КАЖДОГО теста при заданной задержке сбор→выполнение.

    Задержка вносится плагином, который состаривает якорь ПОСЛЕ сбора ровно на
    lag_min минут и не делает больше ничего: он воспроизводит длинный прогон, а не
    изображает поломку.
    """
    # Плагин кладётся ВНЕ дерева: файл, написанный в `scripts/`, сам стал бы
    # подопечным сторожей проводки и мусором в рабочем дереве.
    tmp = tempfile.mkdtemp(prefix="spa_lag_")
    plugin_dir = Path(tmp)
    (plugin_dir / "spa_lag_plugin.py").write_text(_PLUGIN_SRC, encoding="utf-8")
    env = {**os.environ, "SPA_ENV": "ci", "PYTHONHASHSEED": "0",
           "SPA_LAG_MIN": str(lag_min), "SPA_LAG_CLOCKS": ",".join(sorted(CLOCKS)),
           "PYTHONPATH": str(plugin_dir) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    # Отчёт junit кладётся в тот же временный каталог и по той же причине. Он нужен
    # ровно для пропусков: короткая сводка их ИМЁН не печатает (см. `_skips_from_junit`).
    junit = plugin_dir / "outcomes.xml"
    cmd = [sys.executable, "-m", "pytest", *files, "-q", "--tb=no", "-rfEs",
           f"--junit-xml={junit}",
           "-p", "no:randomly", "-p", "no:cacheprovider", "-p", "spa_lag_plugin"]
    try:
        proc = subprocess.run(cmd, cwd=root, env=env, capture_output=True,
                              text=True, timeout=1800)
    except Exception as exc:  # noqa: BLE001
        raise NotMeasured(f"pytest не запустился (задержка {lag_min} мин): {exc}") from exc
    if "= no tests ran" in proc.stdout or proc.returncode >= 4:
        raise NotMeasured(f"pytest не собрал набор (задержка {lag_min} мин), "
                          f"код {proc.returncode}: {proc.stdout[-400:]}")
    # «Побеждает последняя строка» — и это ИЗМЕРЕНО достаточным, а не принято на веру:
    # на одно имя сводка даёт две строки лишь когда тест упал И под `subTest`, И вне
    # него, а pytest печатает отчёты в порядке фаз — `SUBFAILED` (вызов) раньше
    # `FAILED` (вызов) раньше `ERROR` (разборка). Сильнейший исход и так приходит
    # ПОСЛЕДНИМ. Отдельная таблица приоритетов была написана этим же циклом и СНЯТА:
    # прибор по дельте показал её мутанта ВЫЖИВШИМ, и выживший оказался ЭКВИВАЛЕНТНЫМ —
    # ни один достижимый вывод pytest двух правил не различает (урок #949). Предмет
    # закреплён НАБЛЮДАЕМЫМ договором, а не таблицей: смена порядка в будущем pytest
    # краснит `test_a_name_printed_twice_gets_the_outer_failure`.
    verdicts = {m.group(2): m.group(1) for m in _OUTCOME.finditer(proc.stdout)}
    # Итоговая строка есть всегда, а вот слова «passed» в ней может не быть: прогон, где
    # упало ВСЁ, печатает «1 failed in 0.03s». Требовать «N passed» значило бы отвечать
    # «НЕ ИЗМЕРЕНО» на самый информативный исход — тот, ради которого прибор и написан.
    # «Не измерено» обязано означать «не смогли», а не «прошедших ноль» (инв. #17).
    if not _SUMMARY.search(proc.stdout):
        raise NotMeasured(f"вывод pytest не разобран (задержка {lag_min} мин): "
                          f"{proc.stdout[-400:]}")
    passed = re.search(r"(\d+) passed", proc.stdout)
    # Пропуски ПОСЛЕДНИМИ намеренно: имя из junit — единственная личность пропущенного
    # теста, и перекрыть её счётчиком из сводки больше нечем (`SKIPPED` из `_OUTCOME`
    # убран этой же правкой). Столкнуться ключи не могут: junit даёт точечный
    # `модуль.Класс::тест`, сводка — слэшевый `путь/файл.py::тест`.
    skips = _skips_from_junit(junit, lag_min)
    return {"__passed__": passed.group(1) if passed else "0", **verdicts, **skips}


_PLUGIN_SRC = '''"""Двигает НАСТОЯЩИЕ ЧАСЫ вперёд — ровно то, что делает длинный прогон.

Первая редакция состаривала якорь `NOW` самого тест-модуля, и это было НЕВЕРНО:
значения по умолчанию (`def _beacon(..., now=FIXED_NOW)`) связываются на определении
функции, то есть на импорте, и состаривание глобала рассинхронизировало их с якорем.
Тест с ЧЕСТНО инъектированными часами объявлялся бомбой — прибор ИЗГОТАВЛИВАЛ находку
(замер 12.09: 14 ложных из 14).

Верная модель проще и точнее: в длинном прогоне якорь теста НЕ меняется, вперёд уходит
МИР. Часы сдвигаются ПОСЛЕ сбора и СРАЗУ ВСЕМ — и продукту, и тест-помощникам: время
идёт для всех одинаково, и вторая редакция, исключившая тест-модули, объявляла бомбой
верную починку (та берёт якорь в момент утверждения и обязана получить то же «сейчас»,
что и субъект). Отличается не адресат сдвига, а МОМЕНТ: якорь, вычисленный на импорте —
до сдвига, — остаётся старым. Тест, чьи часы инъектированы, сдвига не замечает по
построению — и именно так отличается от бомбы.

Покрытие названо вслух: подменяются `datetime.datetime.now/utcnow` и `time.time` там,
где модуль держит их своим атрибутом. Источник, добытый иначе (`os.stat().st_mtime`,
подпроцесс `date`), этим плагином НЕ покрыт — такой тест прибор назовёт чистым, и это
ограничение прибора, а не свойство теста.
"""
import datetime as _dt
import os
import sys
import time as _time

_LAG_S = float(os.environ.get("SPA_LAG_MIN", "0")) * 60.0
#: Часы сдвигаются ВСЕМ, включая тест-помощники. Исключать тесты НЕЛЬЗЯ (ошибка второй
#: редакции, замер 12.09): в реальности время идёт для всех одинаково, и починка, которая
#: берёт якорь в момент утверждения, обязана получить то же самое «сейчас», что и субъект.
#: Отличается не адресат сдвига, а МОМЕНТ: якорь, вычисленный на импорте — ДО сдвига, —
#: остаётся старым, и ровно в этом состоит воспроизводимое условие длинного прогона.
_PATCHED = ("spa_core", "scripts", "research", "tests")


class _Shifted(_dt.datetime):
    """`datetime` с часами, ушедшими вперёд на задержку прогона."""

    @classmethod
    def now(cls, tz=None):
        return _dt.datetime.now(tz) + _dt.timedelta(seconds=_LAG_S)

    @classmethod
    def utcnow(cls):
        # Наивный UTC без deprecated utcnow(): та же форма, что spa_core.utils.clock.utcnow
        return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) + _dt.timedelta(seconds=_LAG_S)


def _shifted_time():
    return _time.time() + _LAG_S


def pytest_collection_modifyitems(session, config, items):
    if not _LAG_S:
        return
    for name, mod in list(sys.modules.items()):
        if not name.startswith(_PATCHED):
            continue
        d = getattr(mod, "datetime", None)
        if d is _dt.datetime:
            mod.datetime = _Shifted
        elif d is _dt:                      # модуль сделал `import datetime`
            pass                            # трогать общий модуль нельзя: задело бы тесты
        t = getattr(mod, "time", None)
        if t is _time:
            pass
        elif getattr(t, "__name__", None) == "time" and callable(t):
            mod.time = _shifted_time
'''


def changed_verdicts(base: dict[str, str], aged: dict[str, str]) -> list[tuple[str, str, str]]:
    """Тесты, у которых вердикт отличается между двумя прогонами: (тест, было, стало).

    «Прошёл» в разборе отсутствует ПО ПОСТРОЕНИЮ — pytest перечисляет только не
    прошедшие, — отсюда умолчание `passed` у обеих сторон: переход passed→skipped
    ловится так же, как passed→failed (урок #465). С #952 это верно и на деле, а не
    только на словах: до него пропуск приходил под ключом-СЧЁТЧИКОМ, и обмен двух
    пропусков местами давал равенство (см. `_skips_from_junit`).

    Вынесено отдельной функцией, чтобы у сравнения был контроль на НАСТОЯЩИХ словарях
    прибора, а не на собранных руками: рукотворный словарь мерит сам себя.
    """
    changed: list[tuple[str, str, str]] = []
    for test in sorted(set(base) | set(aged)):
        if test == "__passed__":
            continue
        was, now = base.get(test, "passed"), aged.get(test, "passed")
        if was != now:
            changed.append((test, was, now))
    return changed


def bombs(lag_min: float = DEFAULT_LAG_MIN, root: Path = ROOT) -> list[tuple[str, str, str]]:
    """Тесты, у которых вердикт МЕНЯЕТСЯ от одной лишь задержки: (тест, было, стало)."""
    population = anchored_at_import(root)
    if not population:
        raise NotMeasured("население класса пусто — якорей на импорте не найдено ни одного; "
                          "пустое население это отказ инструмента, а не чистый ответ")
    files = sorted({f for f, _, _ in population})
    base = outcomes(files, 0.0, root)
    aged = outcomes(files, lag_min, root)
    changed = changed_verdicts(base, aged)
    if base["__passed__"] == "0" and len(base) == 1:
        raise NotMeasured("базовый прогон (задержка 0) не дал НИ ОДНОГО исхода — "
                          "набор не исполнялся, и сравнивать не с чем")
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lag-min", type=float, default=DEFAULT_LAG_MIN,
                    help="задержка сбор→выполнение в минутах (умолчание — длительность "
                         "полного прогона)")
    args = ap.parse_args(argv)
    try:
        found = bombs(args.lag_min)
    except NotMeasured as exc:
        print(f"НЕ ИЗМЕРЕНО — {exc}")
        return 2
    if not found:
        print(f"Бомб нет: при задержке {args.lag_min:g} мин ни один вердикт не изменился.")
        return 0
    print(f"БОМБЫ ({len(found)}) — краснеют от ДЛИТЕЛЬНОСТИ прогона, не от кода:")
    for test, was, now in found:
        print(f"  {test}: {was} → {now}")
    print("Починка: связывать якорь ПЕРЕД КАЖДЫМ тестом (autouse-фикстура), одним "
          "мгновением на тест. Дописывать в базу запрещено — базы у этой проверки нет.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
