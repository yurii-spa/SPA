"""Перепись списков БЕЗ личности в ответах питоньих читателей.

Заказ **G34, п. 1** приказа владельца «Portfolio CIO» (хвост ADR-409).

## Вопрос, на который прибор отвечает

`element_identity` (ADR-409, `run_identity_key_price`) выбирает поле, которым
элементы списка называют СЕБЯ, и имеет три исхода. Третий — «годного поля нет»
— честно оставляет обход позиционным: координата вида ``.findings[8].severity``
заговорит о ДРУГОЙ находке, стоит набору сменить длину, не изменив ни буквы в
своём имени. Заказ спрашивает ЗАМЕР, а не догадку:

1. сколько списков в ответах читателей попадают СЕЙЧАС в третий исход;
2. у скольких из них есть **годное** поле-кандидат, которого нет в
   ``_IDENTITY_FIELDS``.

Второе число и есть цена нынешнего списка имён: список назван на глаз, и
дописывать в него имена дальше на глаз — ровно та догадка, против которой
написан сам приём. Перепись превращает «кажется, надо добавить `label`» в
«`label` годен у N списков из M, и вот они поимённо».

## Чего перепись НЕ доказывает

* **Годность ≠ верность.** Поле, уникальное на сегодняшнем ответе, завтра может
  повториться. Прибор меряет СОСТАВ одного наблюдённого ответа, а не обещание
  писателя; поэтому вывод односторонний: «годного поля нет» — свойство, «поле
  годно» — наблюдение.
* **Список из ОДНОГО элемента годен тривиально**: любое скалярное поле в нём
  уникально по построению — это совпадение, а не свойство (тот же довод, по
  которому `element_identity` исключает ``bool``). Поэтому синглтоны считаются
  ОТДЕЛЬНО и в число-находку не входят.
* Читатель, которого нельзя позвать, уходит в **не измерено** с названной
  причиной, а не в ноль (инв. #17).
* Обход упёрся в потолок узлов ⇒ строка читателя помечается усечённой и в
  знаменатель находки не идёт: «не досмотрели» не имеет права читаться как
  «не нашли».

Прибор только ЧИТАЕТ: капитал не двигается, живой трек и ``data/`` не
трогаются, зов идёт против КОПИИ-стенда, ``write=False`` проводится там, где
параметр есть (правилом ``module_driver``, а не своей копией правила).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import _list_identity_probe as probe  # noqa: E402
from spa_core.monitoring.call_provenance import call_provenance  # noqa: E402
from spa_core.monitoring.call_provenance import describe as provenance_line  # noqa: E402,E501
from spa_core.monitoring.python_reader_clock_doors import (  # noqa: E402
    measurement_due, population,
)
from spa_core.monitoring.run_identity_key_price import (  # noqa: E402
    build_stands, ensure_faithful_stand,
)
# Заказ G113 п. 2. Правило «ряд ли это» живёт у себя; здесь только свод и печать.
from spa_core.monitoring.list_day_axis import report as day_axis_report  # noqa: E402,E501
from spa_core.monitoring.list_day_axis import tally as day_axis_tally  # noqa: E402
# Заказ G113 п. 1. Признак РОДА живёт у себя (ADR-539); здесь только свод и
# печать — вторая копия правила рода расходилась бы с первой молча.
from spa_core.monitoring import identity_field_kind as field_kind  # noqa: E402
# Заказ G114 п. 1. Правило «сколько РАЗНЫХ читателей подпирают имя» живёт у
# себя: его вторая копия уже существовала бы (сосед `list_day_axis` считает
# читателей у СВОЕГО населения), и разойдись они — «читателей один» значило бы
# в двух разделах одного отчёта разное.
from spa_core.monitoring import field_readers  # noqa: E402
# Заказ G115 п. 3. Правило разницы «поле ЕСТЬ» против «поле ГОДНО» живёт у себя:
# у него ДВА операнда разной природы, и вторая копия расходилась бы с первой
# молча — ровно тот класс, который эта семья ловит у читателей.
from spa_core.monitoring import candidate_denominator as cand_denom  # noqa: E402,E501
# Заказ G115 п. 1. Правило «чем разрешается находка — именем или местом» живёт
# у себя: население уезжает туда ВХОДОМ (готовой осью соседа), и вторая копия
# правила населения здесь расходилась бы с первой молча.
from spa_core.monitoring import finding_address_price as addr_price  # noqa: E402,E501
# Заказ G115 п. 2. Население класса «модульная числовая постоянная как операнд»
# живёт у себя и мерится ПОДСТАНОВКОЙ в настоящую ось: правила «что здесь
# арифметика» здесь нет ни строки — вторая копия расходилась бы с осью молча.
from spa_core.monitoring import modular_constant_operand as const_operand  # noqa: E402,E501
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils import live_paths  # noqa: E402
from spa_core.utils.observation import observed, observed_number  # noqa: E402

SCHEMA = "list_identity_census.v1"
ARTIFACT = "list_identity_census.json"
#: Какой МОДУЛЬ собрал документ. Отвечает не на тот вопрос, что `invoked_by`
#: (кто его позвал), и держать их рядом — единственный способ не спутать:
#: у соседа G33 одно лишь `generated_by` и создало впечатление записанного
#: провенанса там, где записана константа.
PRODUCER = "spa_core/monitoring/list_identity_census.py"

#: Такт переписи. Зов каждого читателя стоит секунды, всё население — минуты;
#: ответ на вопрос «как устроены списки» меняется со скоростью кода, а не дня,
#: поэтому такт недельный и срок решает ФАЙЛ (тот же приём, что у соседа G33).
MEASUREMENT_TACT_DAYS = 7

#: Потолок времени на зов всего населения. Превышен ⇒ НЕ ИЗМЕРЕНО с причиной.
PROBE_TIMEOUT_S = 1800

#: Исходы, у которых вопрос заказа ОСМЫСЛЕН: элементы — словари, а значит могли
#: бы назвать себя полем. Список скаляров сюда не входит: он не назван полем не
#: оттого, что списку имён недостаёт имени.
_DICT_OUTCOMES = ("unnamed_candidate_outside", "unnamed_no_candidate")


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def run_probe(names: Sequence[str], stand: Path, tree_root: Path,
              moment: dt.datetime) -> Tuple[Optional[dict], str]:
    """Один зов населения — отдельным процессом.

    Отдельный процесс здесь не ради пина часов (его нет вовсе), а ради импорта:
    перепись втягивает под сотню читателей, и побочные эффекты их импорта не
    имеют права оседать в процессе, который потом пишет артефакт.
    """
    ensure_faithful_stand(stand, tree_root)
    with tempfile.TemporaryDirectory(prefix="spa_g34_") as tmp:
        mods = Path(tmp) / "modules.json"
        out = Path(tmp) / "answer.json"
        mods.write_text(json.dumps(list(names)), encoding="utf-8")
        env = dict(os.environ)
        env[probe.STAND_ENV] = str(stand)
        env[probe.CLOCK_ENV] = moment.isoformat()
        # C8(b) ADR-580 (INC-1, F8 REVIEW_1 amendment): этот харнесс — тот же
        # стенд + PYTHONPATH-форма, что у `python_reader_clock_doors` — делил с
        # ним дыру до фикса (SPA_SANDBOX/SPA_DATA_DIR/SPA_LIVE_ROOT не стояли
        # вовсе, и читатель без параметра падал бы на умолчании `live_paths`
        # прямо в прод). `ensure_faithful_stand` выше делает стенд полным
        # деревом для чтения, не трогая изоляцию `data/`.
        env[live_paths.SANDBOX_ENV] = "1"
        env[live_paths.LIVE_ROOT_ENV] = str(stand)
        env[live_paths.DATA_DIR_ENV] = str(Path(stand) / "data")
        env["PYTHONPATH"] = os.pathsep.join(
            [str(tree_root)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "spa_core.monitoring._list_identity_probe",
                 str(mods), str(out)],
                cwd=str(tree_root), env=env, capture_output=True,
                timeout=PROBE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return None, f"зов населения не уложился в {PROBE_TIMEOUT_S} с"
        if proc.returncode != 0 or not out.exists():
            tail = (proc.stderr or b"").decode("utf-8", "replace").strip()[-300:]
            return None, f"зонд вышел кодом {proc.returncode}: {tail}"
        try:
            return json.loads(out.read_text(encoding="utf-8")), ""
        except (OSError, ValueError) as exc:
            return None, f"ответ зонда не прочитан: {type(exc).__name__}"


#: Имена, которых у публичной поверхности этого модуля быть НЕ ДОЛЖНО.
#: Прибор отвечает на вопрос «сколько имён берёт каждая пара порогов», а не
#: «годно ли имя»: порог не назначен ни один, и выбрать его вправе только
#: решение. Состав пина — тот же приём, что у соседа (ADR-539): правило
#: «гейта нет» проверяется СОСТАВОМ имён модуля, иначе гейт однажды появится
#: тихой правкой, а прозаическая оговорка в докстринге останется.
_NO_GATE_NAMES = ("apply_threshold", "chosen_pair", "reject_field", "is_fit",
                  "admit_field", "unfit_for_identity", "threshold_gate",
                  # Заказ G113 п. 1: у оси РОДА свои запрещённые имена. Правило
                  # «род ⇒ годность» отвергнуто ЗАМЕРОМ (ADR-539, обе стороны
                  # с названным примером на живом коде), и пин СОСТАВА — то
                  # единственное, что покраснеет, если гейт однажды вернут
                  # тихой правкой под новым именем.
                  "kind_gate", "admit_by_kind", "reject_by_kind",
                  "fit_by_kind",
                  # Заказ G114 п. 1: у оси ЧИТАТЕЛЕЙ свои запрещённые имена.
                  # Правило «много читателей ⇒ годно» не отвергнуто замером и не
                  # принято — оно не ставилось вовсе: заказ велел ЗАМЕРИТЬ ось,
                  # а не назначить по ней порог. Пин состава — то единственное,
                  # что покраснеет, если гейт однажды завести тихой правкой.
                  "readers_gate", "admit_by_readers", "reject_by_readers",
                  "fit_by_readers",
                  # Заказ G115 п. 3: у разницы «ЕСТЬ против ГОДНО» свои
                  # запрещённые имена, и запрет здесь нужнее, чем у соседей.
                  # Разница УВЕЛИЧИВАЕТ число у имени, то есть выглядит доводом
                  # ЗА него, — и половина этой разницы (`present − eligible`)
                  # свидетельствует ПРОТИВ. Гейт, заведённый по широкому числу,
                  # продвигал бы имя наблюдением, которое его опровергает.
                  "denominator_gate", "admit_by_denominator",
                  "reject_by_denominator", "fit_by_denominator",
                  "admit_by_presence", "reject_by_presence")

#: Исходы оси ЧАСОВ и оси АРИФМЕТИКИ признака рода. Перечни берутся у самого
#: признака (ADR-539), а не перепечатываются: вторая копия состава исходов
#: разошлась бы с первой молча, и «не измерено» тихо выпало бы из суммы.
_CLOCK_VERDICTS = (field_kind.NOT_DERIVED, field_kind.WALL_CLOCK,
                   field_kind.CLOCK_NAMED_READ, field_kind.UNMEASURED)
_ARITH_VERDICTS = (field_kind.NOT_ARITH, field_kind.ARITH_DERIVED,
                   field_kind.ARITH_FORMATTED, field_kind.UNMEASURED)


def _ranked_by_length(freq: Dict[str, int],
                      strength: Dict[str, int]) -> List[Tuple[str, int]]:
    """Порядок по ДЛИНЕ подпирающего списка — то есть по силе свидетельства.

    Правило порядка (ADR-410) держится ОДНОЙ копией намеренно. До заказа G113
    п. 1 оно жило замыканием внутри ``report``, и это было безвредно, пока
    порядок читал один перечень. Теперь их два — перечень кандидатов и строки
    оси РОДА, — и оба укорачиваются одним и тем же числом; разойдись порядки,
    читатель, видящий только головы, получил бы ДВА разных утверждения о том,
    какое свидетельство сильнее. Вторая копия правила порядка расходится с
    первой молча — ровно тот класс, который эта семья ловит у читателей.
    """
    def _key(item: Tuple[str, int]):
        field, pop = item
        length = observed_number(strength, field)
        # НЕИЗМЕРЕННАЯ длина — не нулевая (инв. #17): такое поле уходит в хвост
        # ОТДЕЛЬНОЙ группой, а не притворяется слабейшим из измеренных, иначе
        # «силы нет» и «сила мала» слились бы в одно.
        return (0 if length is not None else 1,
                -length if length is not None else 0, -pop, field)

    return sorted(freq.items(), key=_key)


def _ranked_by_population(freq: Dict[str, int],
                          strength: Dict[str, int]) -> List[Tuple[str, int]]:
    """Порядок по НАСЕЛЕНИЮ имени — вторая половина пары, не замена первой.

    Заказ G91 п. 2 начинается словами «население имени — РЯДОМ с длиной, а не
    вместо неё», и это не стилистика. Печать уже несла обе половины
    (``имя×N (макс. длина L)``), но УКОРОЧЕНИЕ перечня в отчёте офиса резало
    хвост по ОДНОЙ оси — по длине. Замер 02.10 на живом артефакте: при
    ``max_fields=8`` восьмёрка по длине кончается на ``journal_pp`` (длина 9,
    ×1), а ``forward_date`` — самое населённое имя переписи (×11) и один из двух
    примеров, которыми заказ и обосновал пару, — в отчёт офиса не попадает
    ВОВСЕ. Голова по населению печатается рядом ровно поэтому; складывать две
    головы в один порядок нельзя — взвешенный балл был бы тем самым «на глаз».
    """
    def _key(item: Tuple[str, int]):
        field, pop = item
        length = observed_number(strength, field)
        # Длина НЕ ИЗМЕРЕНА ⇒ имя уходит в хвост своей группы по населению, и
        # ОТДЕЛЬНОГО члена-флага для этого здесь НЕ НУЖНО — в отличие от
        # порядка по длине (`_rank`), где длина есть ПЕРВЫЙ ключ и флаг
        # обязателен. Разница измерена мутацией (цикл #753): флаг в этом ключе
        # оказался мутационно-эквивалентным, то есть не менял ни одного
        # порядка, — а член без наблюдаемого следствия есть украшение, и держать
        # его «для симметрии» значило бы оставить в наборе утверждение, которое
        # никакой контроль не в силах опровергнуть.
        return (-pop, -length if length is not None else 0, field)

    return sorted(freq.items(), key=_key)


def kind_axis(freq: Dict[str, int], strength: Dict[str, int],
              tree_root: Optional[Path] = None) -> dict:
    """РОД кандидата — ТРЕТЬЕ число рядом с населением и длиной (G113 п. 1).

    Заказ дословно: «``list_identity_census`` печатает кандидату длину и
    население; рода у него нет, а решение о дописывании имени принимается по
    всем трём». Здесь ровно свод и ничего больше: правило рода живёт у себя
    (``identity_field_kind``, ADR-539), и спрашивается оно у КОДА производителя,
    а не у значения.

    Чего этот свод НЕ доказывает — и названо это не из осторожности, а потому
    что каждое из трёх измерено или измеримо:

    * **Род спрошен у ДЕРЕВА, а не у производителя ЭТОГО списка.** Признак
      находит каждое присвоение имени в ``spa_core``/``scripts``; список же
      пришёл из ответа одного читателя, и кто написал его элементы, здесь не
      измеряется ВОВСЕ. Поэтому вывод односторонний: «род у имени один» —
      наблюдение о дереве, а не об этом списке.
    * **Ярлык имени СКРЫВАЕТ расхождение площадок.** Вердикт признака выбран
      СТАРШИНСТВОМ (стенные часы → чтение имени часов → не производное), и имя,
      у которого разные производители дают разный род, получает один ярлык.
      Расхождение поэтому считается ОТДЕЛЬНЫМ числом: без него «род известен»
      читалось бы там, где родов два.
    * **Гейта нет ни одного.** Правило «род ⇒ годность» ОТВЕРГНУТО замером
      (ADR-539, обе стороны с названным примером на живом коде), и его вердикт
      везётся В ДОКУМЕНТ, а не остаётся в чужом ADR: потребитель, не прочитавший
      причину, иначе возьмёт ось за гейт. Состав публичных имён этого модуля
      пинится (``_NO_GATE_NAMES``).

    Три исхода у самого свода различимы (инв. #17): кандидатов нет · дерево не
    названо · дерево названо и не разобрано. Ни один из них не есть «род ни у
    кого не измерен», и ни один не выдаётся за ноль.
    """
    if not freq:
        return {"status": "UNMEASURED",
                "reason": ("кандидатов нет — род спрашивать не у чего; это не "
                           "«род ни у кого не измерен»")}
    if tree_root is None:
        return {"status": "UNMEASURED",
                "reason": ("дерево не названо: род есть утверждение о КОДЕ "
                           "производителя, и без дерева спросить его не у кого")}
    # Порядок имён — тот же, что у перечня кандидатов (`_ranked_by_length`):
    # оба перечня укорачиваются одним числом, и разный порядок дал бы две
    # разные головы под одним утверждением о силе свидетельства.
    names = [name for name, _ in _ranked_by_length(freq, strength)]
    try:
        doc = field_kind.census(names, Path(tree_root))
    except OSError as exc:
        return {"status": "UNMEASURED",
                "reason": f"род не спрошен: дерево не прочитано ({type(exc).__name__})"}
    parsed = observed_number(doc, "files_parsed")
    if parsed is None:
        return {"status": "UNMEASURED",
                "reason": ("признак рода не сказал, сколько файлов разобрал — "
                           "судить о родах по такому ответу нельзя")}
    # Число НЕРАЗОБРАННЫХ файлов: перечня нет вовсе ⇒ число есть `None`, а не
    # ноль (инв. #17). `… or {}` здесь давало бы «не разобрано 0» на ответе,
    # который об этом не сказал ни слова, — и храповик класса верно покраснел
    # на этой самой строке.
    unparsed = observed(doc, "files_unmeasured", kind=dict)
    unparsed_count = None if unparsed is None else len(unparsed)
    if not int(parsed):
        return {"status": "UNMEASURED",
                "reason": ("ни один файл дерева не разобран — род не измерен ни "
                           "у одного имени, и четыре нуля читались бы как ответ"),
                "files_unmeasured": unparsed_count}

    fields = observed(doc, "fields", kind=dict) or {}
    rows: List[dict] = []
    by_clock: Dict[str, int] = {v: 0 for v in _CLOCK_VERDICTS}
    by_arith: Dict[str, int] = {v: 0 for v in _ARITH_VERDICTS}
    causes: Dict[str, int] = {}
    disagreeing: List[str] = []
    disagreement_unmeasured: List[str] = []
    for name in names:
        info = observed(fields, name, kind=dict)
        length = observed_number(strength, name)
        if info is None:
            # Признак не вернул строку по имени, которое ему НАЗВАЛИ. Живой
            # признак так не делает (`census` заводит ключ каждому имени), но
            # сложить такое имя «никуда» значило бы дать ему исчезнуть из обоих
            # перечней молча — а именно так выглядит расхождение признака со
            # сводом, если оно однажды случится.
            clock = arith = field_kind.UNMEASURED
            why = "признак рода не вернул строку по названному имени"
            sites: Dict[str, Optional[int]] = {v: None for v in
                                               (field_kind.WALL_CLOCK,
                                                field_kind.CLOCK_NAMED_READ,
                                                field_kind.NOT_DERIVED)}
        else:
            clock = str(info.get("verdict"))
            arith = str(info.get("arithmetic_verdict"))
            why = str(info.get("why_unmeasured") or "")
            sites = {}
            for verdict, key in ((field_kind.WALL_CLOCK, "wall_clock_count"),
                                 (field_kind.CLOCK_NAMED_READ,
                                  "clock_named_read_count"),
                                 (field_kind.NOT_DERIVED, "not_derived_count")):
                seen = observed_number(info, key)
                sites[verdict] = None if seen is None else int(seen)
        # Расхождение площадок. Счётчика НЕТ ⇒ судить нечем, и это третий исход,
        # а не «не расходится»: `or 0` здесь был бы инв. #17 наизнанку.
        if any(v is None for v in sites.values()):
            disagree: Optional[bool] = None
            disagreement_unmeasured.append(name)
        else:
            disagree = sum(1 for v in sites.values() if v) > 1
            if disagree:
                disagreeing.append(name)
        by_clock[clock] = by_clock.get(clock, 0) + 1
        by_arith[arith] = by_arith.get(arith, 0) + 1
        if clock == field_kind.UNMEASURED:
            cause = why or "причина не названа"
            causes[cause] = causes.get(cause, 0) + 1
        rows.append({
            "field": name,
            # ТРИ числа лежат в одной строке намеренно: решение о дописывании
            # имени принимается по всем трём, и разнести их по трём разделам
            # значило бы заставить читателя сшивать их глазами.
            "population": int(freq[name]),
            "max_length": int(length) if length is not None else None,
            "max_length_unmeasured": length is None,
            "clock_verdict": clock,
            "arithmetic_verdict": arith,
            "producer_sites": sites,
            "kinds_disagree": disagree,
            "why_unmeasured": why,
        })
    return {
        "status": "MEASURED",
        "names": len(names),
        "files_parsed": int(parsed),
        "files_unmeasured": unparsed_count,
        "by_clock_verdict": by_clock,
        "by_arithmetic_verdict": by_arith,
        "clock_unmeasured_causes": causes,
        "disagreeing_names": sorted(disagreeing),
        "disagreement_unmeasured": sorted(disagreement_unmeasured),
        "rows": rows,
        # Вердикт правила годности везётся В ДОКУМЕНТ, а не остаётся ссылкой на
        # чужой ADR: потребитель, не прочитавший причину отказа, взял бы ось за
        # гейт. `observed` — потому что отсутствие вердикта есть третий исход,
        # а не «правило принято».
        "fitness_rule": observed(doc, "fitness_rule", kind=dict),
        "what_it_does_not_prove": [
            "род спрошен у ДЕРЕВА, а не у производителя ЭТОГО списка: кто "
            "написал его элементы, здесь не измеряется вовсе",
            "ярлык имени выбран СТАРШИНСТВОМ и скрывает расхождение площадок — "
            "оно считается отдельным числом",
            "ни одно имя не дописано в _IDENTITY_FIELDS и ни один порог не "
            "назначен: ось — наблюдение, а не гейт",
        ],
    }


def threshold_grid(freq: Dict[str, int], strength: Dict[str, int]) -> dict:
    """Сетка порогов по ПАРЕ чисел: сколько имён берёт каждая пара и КАКИЕ.

    Заказ G91 п. 2 дословно: «порог по ПАРЕ чисел не назначать на глаз —
    сначала замерить, сколько имён каждая пара порогов берёт и что среди
    взятых». Отсюда три свойства замера, и каждое держит заказ, а не вкус:

    * **Оси — НАБЛЮДЁННЫЕ значения**, а не круглые числа и не равномерный шаг.
      Выбрать шаг сетки на глаз значит выбрать на глаз и порог, только спрятав
      выбор в оформление. Наблюдённые значения дают ровно те пары, между
      которыми вообще есть разница: между 8 и 9 она есть, между 12 и 13 — нет.
    * **У имени в ячейке ТРИ исхода, и третий назван** (инв. #17). Длина у
      имени может быть не измерена; тогда исход решает другая ось либо не
      решает никто, и в «не взято» такое имя НЕ складывается.
    * **Два прочтения пары, и они не суммируются.** ``both`` — имя обязано
      пройти обе оси, ``either`` — достаточно одной. Разделение не косметика:
      заказ привёл два имени, у каждого из которых одна ось сильна, а другая
      нища, и конъюнкция с дизъюнкцией судят их ПРОТИВОПОЛОЖНО. Одно число на
      две разные ставки было бы ответом, не относящимся ни к одной.

    Вердикт правила (``rule_verdict``) ВЫЧИСЛЯЕТСЯ из замера, а не объявляется
    строкой: он держится на двух наблюдаемых условиях (ниже), и если население
    однажды их не предъявит, вердикт сменится САМ — отказ пересматривается
    решением, а не ветшает молча.

    Гейта здесь нет ни одного: прибор печатает цену каждой пары, выбор пары —
    предмет ADR. Правило «гейта нет» пинится составом публичных имён модуля
    (``_NO_GATE_NAMES``), а не обещанием в этом абзаце.
    """
    names = sorted(freq)
    if not names:
        return {"status": "UNMEASURED",
                "reason": "кандидатов нет — пару порогов мерить не на чем"}
    # Длина — ЧИСЛО ЭЛЕМЕНТОВ, то есть целое. `observed_number` отдаёт float,
    # и печатать «L≥93.0» значило бы предъявить дробный порог там, где дробных
    # значений не бывает. Нецелое значение при этом НЕ приводится к целому
    # молча: такого в документе быть не может, а если оно появилось — документ
    # не то, чем себя называет, и это третий исход с названной причиной
    # (инв. #17), а не «длина 92».
    length_of: Dict[str, Optional[int]] = {}
    not_integral: List[str] = []
    for name in names:
        raw = observed_number(strength, name)
        if raw is None:
            length_of[name] = None
        elif float(raw).is_integer():
            length_of[name] = int(raw)
        else:
            length_of[name] = None
            not_integral.append(name)
    pops = sorted({int(freq[name]) for name in names})
    lens = sorted({v for v in length_of.values() if v is not None})
    if not lens:
        return {"status": "UNMEASURED",
                "reason": ("ни у одного кандидата длина не измерена — второй "
                           "оси у пары нет, и сетка по одной оси была бы "
                           "ответом на другой вопрос")}

    cells: List[dict] = []
    for n_min in pops:
        for l_min in lens:
            both_taken, both_unmeasured = [], []
            either_taken, either_unmeasured = [], []
            for name in names:
                pop = int(freq[name])
                length = length_of[name]
                # КОНЪЮНКЦИЯ. Ось населения решает первой: не прошла — исход
                # решён и длина не нужна. Прошла, а длина не измерена — исход
                # решала бы ИМЕННО она, значит «не измерено», а не «не взято».
                if pop >= n_min:
                    if length is None:
                        both_unmeasured.append(name)
                    elif length >= l_min:
                        both_taken.append(name)
                # ДИЗЪЮНКЦИЯ. Достаточно одной оси, поэтому неизмеренная длина
                # мешает только тогда, когда население УЖЕ не прошло.
                if pop >= n_min or (length is not None and length >= l_min):
                    either_taken.append(name)
                elif length is None:
                    either_unmeasured.append(name)
            cells.append({
                "n_min": n_min, "l_min": l_min,
                "both": {"taken": len(both_taken), "names": both_taken,
                         "length_unmeasured": len(both_unmeasured)},
                "either": {"taken": len(either_taken), "names": either_taken,
                           "length_unmeasured": len(either_unmeasured)},
            })

    # ЧЕМПИОНЫ осей — множества, а не по одному имени: ничья на оси длины
    # наблюдена (два имени при 93), и взять из неё одно «первое» значило бы
    # скрыть ровно то совпадение, вокруг которого крутится вердикт.
    top_pop = max(int(freq[name]) for name in names)
    top_len = max(lens)
    champions = {
        "by_population": {
            "value": top_pop,
            "names": sorted(n for n in names if int(freq[n]) == top_pop)},
        "by_max_length": {
            "value": top_len,
            "names": sorted(n for n in names if length_of[n] == top_len)},
    }
    all_champions = set(champions["by_population"]["names"]) | set(
        champions["by_max_length"]["names"])
    # Ячейки, где конъюнкция берёт ОБОИХ чемпионов. Если такие есть только при
    # поле на полу своей оси — порог по этой оси не делает работы вовсе.
    champion_cells = [c for c in cells
                      if all_champions <= set(c["both"]["names"])]
    population_axis_idle = bool(champion_cells) and all(
        c["n_min"] == pops[0] for c in champion_cells)
    length_axis_idle = bool(champion_cells) and all(
        c["l_min"] == lens[0] for c in champion_cells)

    # СЛЕПОЕ ПЯТНО пары. Имена с ОДИНАКОВОЙ координатой ``(население, длина)``
    # неразличимы любым порогом по этим двум числам — это свойство пары, а не
    # наблюдение дня, и именно оно решает вердикт.
    coords: Dict[Tuple[int, int], List[str]] = {}
    for name in names:
        length = length_of[name]
        if length is None:
            continue
        coords.setdefault((int(freq[name]), int(length)), []).append(name)
    collisions = [{"population": pop, "max_length": length,
                   "names": sorted(group)}
                  for (pop, length), group in sorted(coords.items())
                  if len(group) > 1]
    blind_names = sorted(n for c in collisions for n in c["names"])
    coordinate_unmeasured = sorted(n for n in names if length_of[n] is None)

    reasons: List[str] = []
    if blind_names:
        reasons.append(
            f"у {len(blind_names)} имён координата ПОВТОРЯЕТСЯ "
            f"({len(collisions)} класс(ов) совпадения): порог по этой паре "
            f"чисел не различает их ни при каком значении")
    if population_axis_idle:
        reasons.append(
            f"оба чемпиона осей конъюнкция берёт только при n_min={pops[0]}, "
            f"то есть на полу оси населения — порог по населению не делает "
            f"работы вовсе")
    if length_axis_idle:
        reasons.append(
            f"оба чемпиона осей конъюнкция берёт только при l_min={lens[0]} — "
            f"порог по длине не делает работы вовсе")
    if not champion_cells:
        reasons.append("ни одна пара не берёт оба чемпиона осей сразу")
    return {
        "status": "MEASURED",
        "axes": {"population": pops, "max_length": lens},
        "axes_source": ("наблюдённые значения населения переписи — шаг сетки на "
                        "глаз не выбран ни по одной оси"),
        "readings": ["both", "either"],
        "pairs": len(cells),
        "cells": cells,
        "champions": champions,
        "champion_cells": [{"n_min": c["n_min"], "l_min": c["l_min"]}
                           for c in champion_cells],
        "population_axis_idle": population_axis_idle,
        "length_axis_idle": length_axis_idle,
        "collisions": collisions,
        "blind_names": blind_names,
        "coordinate_unmeasured": coordinate_unmeasured,
        "coordinate_not_integral": sorted(not_integral),
        "rule_verdict": "REFUSED" if reasons else "NOT_REFUTED",
        "rule_verdict_reasons": reasons,
        "what_it_does_not_prove": [
            "ни один порог НЕ назначен и ни один гейт не заведён — прибор "
            "называет цену каждой пары, выбор пары есть решение",
            "«не опровергнуто» (NOT_REFUTED) не значит «правило годно»: это "
            "лишь отсутствие двух названных улик на СЕГОДНЯШНЕМ населении",
            "обе оси — наблюдения одного ответа читателей, а не обещание "
            "писателя: население и длина меняются со скоростью кода",
        ],
    }


def distinct_taken_sets(grid: dict, reading: str = "both") -> List[dict]:
    """Различные наборы взятых имён — и СИЛЬНЕЙШАЯ пара, дающая каждый.

    Пар в сетке десятки, а различных ОТВЕТОВ у них единицы: печатать все пары
    значило бы утопить ответ заказа («что среди взятых») в таблице. Выбор
    представителя не на глаз: среди пар с одинаковым набором берётся
    сильнейшая — наибольшая по ``(n_min, l_min)``, то есть та, которая этот
    набор удерживает при самых строгих порогах.
    """
    cells = (grid or {}).get("cells")
    if not cells:
        return []
    best: Dict[Tuple[str, ...], dict] = {}
    for cell in cells:
        side = cell.get(reading) or {}
        key = tuple(side.get("names") or ())
        prev = best.get(key)
        here = (int(cell["n_min"]), int(cell["l_min"]))
        if prev is None or here > (int(prev["n_min"]), int(prev["l_min"])):
            best[key] = {"n_min": cell["n_min"], "l_min": cell["l_min"],
                         "taken": side.get("taken"), "names": list(key),
                         "length_unmeasured": side.get("length_unmeasured")}
    return sorted(best.values(), key=lambda row: (-int(row["taken"] or 0),
                                                 row["n_min"], row["l_min"]))


def reader_axis(freq: Dict[str, int], strength: Dict[str, int],
                readers: Optional[Dict[str, dict]],
                grid: Optional[dict]) -> dict:
    """ТРЕТЬЯ ось кандидата — число РАЗНЫХ ЧИТАТЕЛЕЙ (заказ G114 пп. 1, 2).

    Заказ дословно: «население сегодня считает списки; ``message×3`` может
    означать три находки одного прибора и три разных подсистемы, и это разные
    свидетельства. Замерить, у скольких имён население собрано из одного
    читателя, — и только после замера решать, нужна ли ось». Поэтому вердикт
    ``axis_verdict`` ВЫЧИСЛЯЕТСЯ из двух наблюдаемых условий (ниже), а не
    объявляется строкой: исчезнут условия — он сменится сам, и нужда в оси будет
    пересмотрена решением, а не истлеет молча. Тот же приём, что у
    ``rule_verdict`` соседней сетки (ADR-540).

    Второе условие — заказ G114 п. 2: «класс совпадения — предмет, а не побочный
    счёт. Замерить, сколько классов РАСПАДАЕТСЯ, если в координату добавить
    третью ось». Класс берётся у сетки (``collisions``), а не пересчитывается
    здесь: вторая копия правила «одинаковая координата» разошлась бы с первой
    молча, и «распалось» считалось бы по другим классам, чем те, о которых
    сетка печатает вердикт.

    Население у оси РОВНО то же, что у оси населения: те же вклады тех же
    ответивших читателей, включая усечённых. Считать читателей по одному
    населению, а списки по другому значило бы напечатать два числа об разных
    предметах под одной координатой.

    Чего ось НЕ доказывает — и названо это не из осторожности:

    * **Разные читатели ≠ разные подсистемы** (полностью — в докстринге
      ``field_readers``): измеряется число разных МОДУЛЕЙ.
    * **Ось не закрывает слепое пятно пары.** Сколько имён остаётся
      неразличимыми ПОСЛЕ добавления третьего числа — отдельная величина
      (``names_still_blind``), и без неё «ось распадается» читалось бы как
      «слепого пятна больше нет».
    * **Правила «много читателей ⇒ годно» нет.** Ось — наблюдение, а не гейт;
      запрет пинится составом публичных имён модуля (``_NO_GATE_NAMES``).
    """
    if not freq:
        return {"status": "UNMEASURED",
                "reason": ("кандидатов нет — читателей считать не у чего; это "
                           "не «у всех имён по одному читателю»")}
    if not isinstance(readers, dict):
        return {"status": "UNMEASURED",
                "reason": ("свода читателей нет вовсе — число читателей не "
                           "измерено НИ У ОДНОГО имени, и единицы читались бы "
                           "как замер")}
    # Порядок строк — ОДНОЙ копией (`_ranked_by_length`), той же, что у перечня
    # кандидатов и у оси РОДА: все три укорачиваются одним числом, и разойдись
    # порядки, читатель, видящий только головы, получил бы разные утверждения о
    # том, какое свидетельство сильнее. Длина поэтому и есть ВХОД этой оси, хотя
    # сама она длину не считает: своя копия порядка здесь (хоть бы и «по
    # населению») дала бы третью голову под тем же утверждением.
    names = [name for name, _ in _ranked_by_length(freq, strength)]
    rows: List[dict] = []
    single: List[str] = []
    multi: List[str] = []
    unmeasured: List[dict] = []
    overstated: List[dict] = []
    count_of: Dict[str, Optional[int]] = {}
    for name in names:
        seen = field_readers.readers_of(readers, name)
        count_of[name] = seen
        raw = readers.get(name)
        row: dict = raw if isinstance(raw, dict) else {}
        nameless = int(row.get(field_readers.NAMELESS_KEY) or 0)
        population = int(freq[name])
        if seen is None:
            # Третий исход у ИМЕНИ. Причина называется той же мерой, которая её
            # произвела: «вкладов без названного читателя N» есть наблюдение, а
            # «читателей 0» было бы выдумкой.
            why = (f"вкладов без названного читателя: {nameless} — названных "
                   f"читателей {len(row.get('readers') or [])}, и это нижняя "
                   f"граница, а не замер"
                   if nameless else
                   "имени не пришло ни одного вклада — в своде читателей его нет")
            unmeasured.append({"field": name, "why": why})
        elif seen == 1:
            single.append(name)
            # ВОТ ответ заказа: население больше единицы, а читатель один ⇒ эти
            # N списков суть N находок ОДНОГО прибора. Пара «население × длина»
            # об этом молчит по построению.
            if population > 1:
                overstated.append({"field": name, "population": population,
                                   "readers": 1})
        else:
            multi.append(name)
        rows.append({
            "field": name,
            "population": population,
            "readers": seen,
            "readers_unmeasured": seen is None,
            "reader_names": list(row.get("readers") or []),
            "contributions_nameless": nameless,
        })

    classes = _split_classes(grid, count_of)
    reasons: List[str] = []
    split = classes.get("classes_split")
    if split:
        reasons.append(
            f"третья ось РАЗБИВАЕТ {split} из {classes.get('classes_total')} "
            f"класс(ов) совпадающей координаты и делает различимыми "
            f"{len(classes.get('names_freed') or [])} имён — работу, которой "
            f"пара чисел не делает ни при каком пороге")
    if overstated:
        reasons.append(
            f"у {len(overstated)} имён население больше единицы, а читатель "
            f"ОДИН (сильнейшее: "
            f"{max(overstated, key=lambda r: r['population'])['field']}×"
            f"{max(r['population'] for r in overstated)}) — ось населения "
            f"называет шириной свидетельства то, что шириной не является")
    return {
        "status": "MEASURED",
        "names": len(names),
        # Главное число заказа: «у скольких имён население собрано из ОДНОГО
        # читателя». Печатается рядом со знаменателем всегда.
        "single_reader_names": single,
        "multi_reader_names": multi,
        "readers_unmeasured": unmeasured,
        "population_overstated": overstated,
        "rows": rows,
        "classes": classes,
        "axis_verdict": "NEEDED" if reasons else "NOT_NEEDED",
        "axis_verdict_reasons": reasons,
        "what_it_does_not_prove": [
            "читатель — питоний МОДУЛЬ, а не подсистема: два модуля одной "
            "подсистемы считаются двумя, и числа подсистем здесь нет вовсе",
            "ось не закрывает слепое пятно пары: сколько имён остаётся "
            "неразличимыми ПОСЛЕ третьего числа — отдельная величина",
            "число читателей — наблюдение ОДНОГО ответа, как население и "
            "длина: оно меняется со скоростью кода",
            "ни одно имя не дописано в _IDENTITY_FIELDS и ни один порог не "
            "назначен: ось — наблюдение, а не гейт",
        ],
    }


def _split_classes(grid: Optional[dict],
                   count_of: Dict[str, Optional[int]]) -> dict:
    """Распадается ли класс совпадающей координаты от третьего числа (G114 п. 2).

    Классы берутся у сетки, а не пересчитываются: правило «одинаковая
    координата» живёт одной копией. Исходов у класса ТРИ, и третий назван —
    класс, в котором у хотя бы одного имени число читателей не измерено, не
    есть ни «распался», ни «цел»: судить о нём нечем.

    «Распался» значит, что имена класса разошлись по числу читателей хотя бы на
    две группы. «Освобождено» — имя, оставшееся в группе ОДНО: только оно стало
    различимым третьим числом от ВСЕХ прочих имён класса. Имя, ушедшее в группу
    из двух, различимо от одной половины класса и по-прежнему слепо к другой —
    считать его освобождённым значило бы завысить работу оси.
    """
    if not isinstance(grid, dict) or str(grid.get("status")) != "MEASURED":
        return {"status": "UNMEASURED",
                "reason": ("сетки пары чисел нет или она не измерена — классов "
                           "совпадения не из чего брать, и «распалось 0» "
                           "читалось бы как замер")}
    collisions = observed(grid, "collisions", kind=list)
    if collisions is None:
        return {"status": "UNMEASURED",
                "reason": ("перечня классов совпадения в сетке нет вовсе — это "
                           "не «совпадающих координат нет»")}
    rows: List[dict] = []
    freed: List[str] = []
    still_blind: List[str] = []
    split = intact = unmeasured = 0
    for cls in collisions:
        names = sorted(str(n) for n in (cls.get("names") or []))
        groups: Dict[int, List[str]] = {}
        seen_of: Dict[str, int] = {}
        blind_here = False
        for name in names:
            seen = count_of.get(name)
            if seen is None:
                blind_here = True
                break
            seen_of[name] = int(seen)
            groups.setdefault(int(seen), []).append(name)
        if blind_here:
            unmeasured += 1
            rows.append({"population": cls.get("population"),
                         "max_length": cls.get("max_length"),
                         "names": names, "verdict": "unmeasured",
                         "why": "у имени класса число читателей не измерено"})
            continue
        splits = len(groups) > 1
        here_freed = sorted(n for g in groups.values() if len(g) == 1 for n in g)
        here_blind = sorted(n for g in groups.values() if len(g) > 1 for n in g)
        freed.extend(here_freed)
        still_blind.extend(here_blind)
        if splits:
            split += 1
        else:
            intact += 1
        rows.append({"population": cls.get("population"),
                     "max_length": cls.get("max_length"),
                     "names": names,
                     "readers_by_name": seen_of,
                     "groups": [groups[k] for k in sorted(groups)],
                     "verdict": "split" if splits else "intact",
                     "names_freed": here_freed})
    return {
        "status": "MEASURED",
        "classes_total": len(collisions),
        "classes_split": split,
        "classes_intact": intact,
        "classes_unmeasured": unmeasured,
        "names_freed": sorted(freed),
        "names_still_blind": sorted(still_blind),
        "rows": rows,
    }


def tally(rows: Dict[str, dict], *,
          tree_root: Optional[Path] = None) -> dict:
    """Свод по СПИСКАМ, а не по читателям: предмет заказа — список.

    ``tree_root`` — вход оси РОДА (заказ G113 п. 1): род есть утверждение о КОДЕ
    производителя, и спросить его можно только у дерева. Дерева не дали ⇒ ось
    честно отвечает «НЕ ИЗМЕРЕНО» с названной причиной, а не нулями по четырём
    исходам — звать свод без дерева вправе кто угодно, выдавать это за замер
    родов не вправе никто (инв. #17).

    Знаменатель находки назван явно и он УЖЕ полного населения: из него
    вычтены синглтоны (годность в них тривиальна) и списки не-словарей (полем
    себя не называют по построению). Складывать их в один знаменатель значило
    бы развести находку водой.
    """
    outcomes: Dict[str, int] = {}
    candidate_fields: Dict[str, int] = {}
    strength: Dict[str, int] = {}
    named_fields: Dict[str, int] = {}
    singletons = 0
    truncated_readers: List[str] = []
    finding_rows: List[dict] = []
    # Заказ G114 п. 1: ВКЛАДЫ, а не сразу счётчик. Разница между «сколько
    # списков подпёрли имя» и «сколько РАЗНЫХ читателей их дали» теряется, если
    # свернуть вход в число до замера, — а она и есть предмет заказа.
    reader_contributions: List[Tuple[str, Optional[str]]] = []
    # Заказ G115 п. 3: строки СЛОВАРНЫХ списков с их составом. Отбирает их сам
    # сосед (`DICT_OUTCOMES`) — его перечень шире нашего `_DICT_OUTCOMES` ровно
    # на `named`, и эта разница есть предмет заказа; решать её здесь значило бы
    # завести вторую копию правила отбора.
    denominator_rows: List[dict] = []
    total_lists = 0
    readers_measured = 0
    unmeasured: Dict[str, int] = {}

    for module, row in sorted(rows.items()):
        cause = row.get("cause")
        if cause:
            unmeasured[str(cause)] = unmeasured.get(str(cause), 0) + 1
            continue
        readers_measured += 1
        if row.get("truncated"):
            truncated_readers.append(module)
        for item in (row.get("lists") or []):
            total_lists += 1
            outcome = str(item.get("outcome"))
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            denominator_rows.append(dict(item, module=module))
            if int(item.get("n") or 0) == 1:
                singletons += 1
            if outcome == "named":
                named_fields[str(item.get("field"))] = (
                    named_fields.get(str(item.get("field")), 0) + 1)
            if outcome == "unnamed_candidate_outside" and int(item.get("n") or 0) > 1:
                for field in (item.get("candidates") or []):
                    candidate_fields[str(field)] = candidate_fields.get(str(field), 0) + 1
                    # Сила свидетельства — ДЛИНА списка, на котором поле
                    # оказалось уникальным. На двух элементах уникальность
                    # почти неизбежна и потому мало что говорит; на сорока
                    # трёх — говорит много. Хранится максимум: он и есть
                    # лучшее наблюдение в пользу поля.
                    prev = strength.get(str(field), 0)
                    strength[str(field)] = max(prev, int(item.get("n") or 0))
                    # Вклад записывается РЯДОМ с инкрементом населения — тем же
                    # условием и в том же проходе: ось читателей обязана стоять
                    # на ТОМ ЖЕ населении, что ось списков, иначе два числа
                    # координаты говорили бы о разных предметах.
                    reader_contributions.append((str(field), module or None))
                finding_rows.append({"module": module,
                                     "coord": item.get("coord"),
                                     "n": item.get("n"),
                                     "candidates": item.get("candidates")})

    # Ось дня (заказ G113 п. 2) — свод по тем же спискам, но СВОИМ прибором.
    # Население берётся ТОЛЬКО у читателей, чей обход дошёл до конца и кого
    # удалось позвать: доля, посчитанная от недосмотренного населения, есть
    # «не измерено», выданное за ответ (тот же довод, что у знаменателя ниже).
    # Исключённые читатели СЧИТАЮТСЯ, а не отбрасываются молча.
    day_axis_rows: List[dict] = []
    day_axis_excluded = 0
    for module, row in sorted(rows.items()):
        if row.get("cause"):
            continue
        if row.get("truncated"):
            day_axis_excluded += 1
            continue
        for item in (row.get("lists") or []):
            axis = item.get("day_axis")
            if not isinstance(axis, dict):
                # Строка без оси. Живой зонд её не производит (`classify_list`
                # ставит ось всегда), но сложить такую строку «никуда» значило бы
                # дать ей исчезнуть из свода молча — а именно так выглядит
                # расхождение зонда со сводом, если оно однажды случится.
                day_axis_rows.append({"outcome": "unmeasured", "n": item.get("n"),
                                      "reason": "зонд не поставил ось дня",
                                      "module": module,
                                      "coord": item.get("coord")})
                continue
            day_axis_rows.append(dict(axis, module=module,
                                      coord=item.get("coord")))
    day_axis = day_axis_tally(day_axis_rows)
    day_axis["readers_excluded_truncated"] = day_axis_excluded

    # Знаменатель считается ТОЛЬКО по читателям, чей обход дошёл до конца.
    # Усечённый обход даёт находки (они наблюдены), но не даёт знаменателя:
    # доля, посчитанная от недосмотренного населения, есть «не измерено»,
    # выданное за ответ.
    #
    # И только по СЛОВАРЯМ длиннее одного. Первая редакция брала сюда всякий
    # исход, начинающийся на `unnamed_`, — то есть и списки СКАЛЯРОВ, которых
    # в населении большинство. Знаменатель раздувался вчетверо, а подпись под
    # ним говорила «словари»: ровно то расхождение имени с населением, ради
    # которого весь этот прибор и написан.
    unnamed_dicts_multi = sum(
        1 for row in rows.values()
        if not row.get("cause") and not row.get("truncated")
        for item in (row.get("lists") or [])
        if int(item.get("n") or 0) > 1
        and str(item.get("outcome")) in _DICT_OUTCOMES)
    # Списки СКАЛЯРОВ длиннее одного. Заказ G35 п. 3 (он же G37 п. 4) исполнен:
    # элемент в них называет себя СВОИМ ЗНАЧЕНИЕМ, и правило это теперь не в
    # тексте комментария, а в `element_identity`. Поэтому число разложено на три,
    # а не оставлено одним: слитое `scalar_lists_multi` после правила означало бы
    # уже не то, что означало до неё, и упало бы с 640 до остатка МОЛЧА.
    #
    # И заодно исправлен знаменатель: прежняя редакция считала здесь ВСЁ
    # `unnamed_not_dicts` (>1), то есть вместе со списками списков и смешанными —
    # под подписью «списки скаляров». Теперь состав спрашивается у причины отказа.
    def _count(pred) -> int:
        return sum(
            1 for row in rows.values()
            if not row.get("cause") and not row.get("truncated")
            for item in (row.get("lists") or [])
            if int(item.get("n") or 0) > 1 and pred(item))

    named_by_value = _count(
        lambda item: str(item.get("outcome")) == "named_by_value")
    scalar_not_unique = _count(
        lambda item: str(item.get("outcome")) == "unnamed_not_dicts"
        and str(item.get("scalar_refused")) == "not_unique")
    not_scalar_at_all = _count(
        lambda item: str(item.get("outcome")) == "unnamed_not_dicts"
        and str(item.get("scalar_refused")) == "not_scalar")
    # Строка без названной причины. Живой зонд её не производит (`classify_list`
    # ставит причину всегда), но сложить такую строку «никуда» значило бы дать ей
    # исчезнуть из ВСЕХ трёх чисел молча — а именно так выглядит расхождение
    # зонда со сводом, если оно однажды случится. Третий исход назван (инв. #17).
    cause_unmeasured = _count(
        lambda item: str(item.get("outcome")) == "unnamed_not_dicts"
        and str(item.get("scalar_refused")) not in ("not_unique", "not_scalar"))
    # Сетка считается ОДИН раз и уезжает в ДВА ключа: ось читателей берёт классы
    # совпадения у неё, а не пересчитывает их (G114 п. 2). Второй зов дал бы
    # второй объект, и «распалось» считалось бы по классам, о которых сетка
    # вердикта не печатала.
    grid = threshold_grid(candidate_fields, strength)
    readers_by_field = field_readers.tally_readers(reader_contributions)
    # Разница «поле ЕСТЬ против поле ГОДНО» считается ОДИН раз и уезжает в ДВА
    # ключа: раздел знаменателя печатает её читателю, а раздел адреса (заказ
    # G115 п. 1) судит по ней, подпёрто ли ИМЯ населением. Второй зов дал бы
    # второй объект — и вердикт адреса относился бы к числу, которого в отчёте
    # нет.
    denominator_axis = cand_denom.tally(denominator_rows, candidate_fields)
    return {
        # Списки ОДНИХ скаляров: получившие личность плюс отказанные за
        # повтор значений. Смешанные и вложенные сюда не входят — они не
        # списки скаляров, и считать их здесь значило бы разводить число водой.
        "scalar_lists_multi": named_by_value + scalar_not_unique,
        "scalar_named_by_value": named_by_value,
        "scalar_not_unique": scalar_not_unique,
        "not_scalar_lists_multi": not_scalar_at_all,
        "scalar_cause_unmeasured": cause_unmeasured,
        "lists_total": total_lists,
        "outcomes": outcomes,
        "singletons": singletons,
        "readers_measured": readers_measured,
        "unmeasured_causes": unmeasured,
        "truncated_readers": sorted(truncated_readers),
        "named_fields": named_fields,
        "candidate_fields_outside": candidate_fields,
        "candidate_field_strength": strength,
        # Заказ G91 п. 2: ПАРА чисел («население × длина»), замеренная сеткой
        # наблюдённых значений. Складывать её в одно число с полями выше
        # нельзя — это ответ на другой вопрос: не «какие поля годны», а «что
        # взяла бы каждая пара порогов, если бы её назначили».
        "threshold_grid": grid,
        # Заказ G114 п. 1: кто именно подпёр каждое имя. Перечень лежит РЯДОМ со
        # сводом оси намеренно — свод печатает числа, а спор об имени решается
        # поимённым составом его читателей.
        "candidate_readers": readers_by_field,
        "denominator_of_finding": unnamed_dicts_multi,
        "finding_rows": finding_rows,
        # Заказ G113 п. 2: «ряд ли это». Отдельный ключ, а не слагаемое чисел
        # выше — это ответ на ДРУГОЙ вопрос: не «назвал ли себя элемент полем»,
        # а «различает ли его ДЕНЬ». Правила «ряд ⇒ годность» здесь нет.
        "day_axis": day_axis,
        # Заказ G113 п. 1: РОД кандидата — третье число рядом с населением и
        # длиной. Отдельный ключ, а не слагаемое: это ответ о КОДЕ производителя
        # имени, тогда как население и длина суть наблюдения ОТВЕТА читателей.
        # Правила «род ⇒ годность» здесь нет — оно отвергнуто замером (ADR-539).
        "candidate_kind": kind_axis(candidate_fields, strength, tree_root),
        # Заказ G114 пп. 1, 2: ЧИСЛО РАЗНЫХ ЧИТАТЕЛЕЙ — третья ось рядом с
        # населением и длиной, и замер, сколько классов совпадающей координаты
        # от неё распадается. Отдельный ключ, а не слагаемое: сложить число
        # читателей с числом списков значило бы выбрать вес на глаз — ровно то,
        # что заказ G91 п. 2 запретил паре (ADR-540).
        "candidate_reader_axis": reader_axis(candidate_fields, strength,
                                             readers_by_field, grid),
        # Заказ G115 п. 3: РАЗНИЦА между «поле ЕСТЬ» и «поле ГОДНО». Отдельный
        # ключ, а не поправка к населению выше: население печатается читателю
        # как есть (оно и есть мерило ADR-503), а широкое число отвечает на
        # вопрос «не узко ли мерило», и подменить одно другим значило бы
        # напечатать два разных утверждения под одним именем. Население уезжает
        # ВХОДОМ — пересчёт был бы второй копией правила.
        "candidate_denominator": denominator_axis,
        # Заказ G115 п. 1: чем разрешается находка — дописанным ИМЕНЕМ или
        # адресом МЕСТА, и чего стои́л бы второй адрес читателям. Отдельный
        # ключ, а не поправка к числам выше: те отвечают «какие поля годны», а
        # этот — «какой КООРДИНАТОЙ находка адресуема».
        #
        # Ось населения уезжает сюда ВХОДОМ и считается ОДИН раз (тот же приём,
        # что у сетки порогов): второй зов дал бы ВТОРОЙ объект, и напечатанная
        # разница могла бы разойтись с той, по которой вынесен вердикт адреса,
        # — то есть два утверждения уехали бы под одним именем.
        "finding_address": addr_price.tally(
            denominator_rows, denominator_axis, probe.IDENTITY_FIELDS,
            # Дерева не дали ⇒ цена читателям остаётся ТРЕТЬИМ ИСХОДОМ с
            # причиной (её меряет AST дерева, и выдумать её нельзя), а не
            # нулевой ценой: тот же довод, что у оси РОДА строкой выше.
            price=(addr_price.reader_price(Path(tree_root))
                   if tree_root is not None else None),
            # РОД спрашивается у того же прибора, что и ось рода выше
            # (``identity_field_kind``), и ВХОДОМ-вызываемым: имена, у которых
            # род нужно спросить, известны только ПОСЛЕ разбора находок, а
            # вторая копия правила рода расходилась бы с первой молча. Дерева
            # нет ⇒ род остаётся третьим исходом с причиной.
            kind_census=((lambda names: field_kind.census(names,
                                                          Path(tree_root)))
                         if tree_root is not None else None)),
        # Заказ G115 п. 2: НАСЕЛЕНИЕ третьей односторонности оси рода —
        # модульной числовой постоянной в роли операнда. Отдельный ключ, а не
        # поправка к оси рода: ось печатает род ИМЕНИ, а этот раздел отвечает,
        # сколько МЕСТ кода ось не видит вовсе и задето ли ими хоть одно имя из
        # тех, о которых перепись спрашивает. Если не задето ни одно — заказ
        # велел записать это и закрыть, а не расширять ось на всякий случай, и
        # число здесь — единственное, чем такое решение проверяемо.
        #
        # Перечень кандидатов и список имён уезжают ВХОДОМ (тот же приём, что у
        # сетки порогов и адреса находки): пересчёт был бы второй копией
        # правила. Дерева нет ⇒ население остаётся ТРЕТЬИМ ИСХОДОМ с причиной.
        "constant_operand": const_operand.tally(
            candidate_fields, probe.IDENTITY_FIELDS,
            Path(tree_root) if tree_root is not None else None),
    }


def measure(data_dir: Path, tree_root: Path, *,
            now: Optional[dt.datetime] = None) -> dict:
    """Перепись целиком. Любое незакрытое звено ⇒ ``UNMEASURED`` с причиной."""
    moment = now if now is not None else _utcnow()
    doc: dict = {
        "schema": SCHEMA,
        "generated_at": moment.isoformat(),
        # Заказ G36 п. 1. `generated_at` — часы, а не звавший: отметка сменится
        # одинаково, позвала ли перепись ступень моста или рука цикла, набравшая
        # `python3 -m`. Без этого поля наблюдение 25.09 односторонне — оно может
        # ОПРОВЕРГНУТЬ проводку ступени и не может её подтвердить.
        "invoked_by": call_provenance(tree_root=Path(tree_root)),
        "generated_by": PRODUCER,
        "question": ("сколько списков в ответах питоньих читателей не называют "
                     "себя полем (третий исход element_identity) и у скольких "
                     "есть годное поле-кандидат вне _IDENTITY_FIELDS"),
        "what_it_does_not_prove": [
            "годность поля наблюдена на ОДНОМ ответе — это не обещание писателя",
            "синглтон годен тривиально: уникальность в списке из одного элемента "
            "есть совпадение, а не свойство — синглтоны вынесены из знаменателя",
            "усечённый обход в знаменатель находки не идёт: «не досмотрели» не "
            "есть «не нашли»",
            "перепись НЕ дописывает имена в _IDENTITY_FIELDS и не меняет ни одной "
            "координаты — она только называет цену нынешнего списка",
        ],
        "advisory": ("_IDENTITY_FIELDS, element_identity, координаты соседних "
                     "приборов, пороги RiskPolicy v1.0, стоп-кран и живой трек "
                     "НЕ трогаются — прибор только ЧИТАЕТ"),
        "identity_fields_today": list(probe.IDENTITY_FIELDS),
    }

    names, pop_stats = population(Path(tree_root))
    doc["population"] = pop_stats
    if not names:
        doc["status"] = "UNMEASURED"
        doc["reason"] = "питонья ветвь населения переписи пуста — звать некого"
        return doc

    with tempfile.TemporaryDirectory(prefix="spa_g34_stand_") as tmp:
        stands, why = build_stands(Path(data_dir), Path(tmp))
        if stands is None:
            doc["status"] = "UNMEASURED"
            doc["reason"] = f"стенд не построен: {why}"
            return doc
        doc["stand"] = {"day": stands.get("day"), "donor_day": stands.get("donor_day")}
        answer, why = run_probe(names, Path(stands["s1"]), Path(tree_root), moment)
        if answer is None:
            doc["status"] = "UNMEASURED"
            doc["reason"] = f"население не позвано: {why}"
            return doc

    rows = answer.get("__modules__") or {}
    doc["readers"] = rows
    doc["counts"] = tally(rows, tree_root=Path(tree_root))
    if not doc["counts"]["readers_measured"]:
        doc["status"] = "UNMEASURED"
        doc["reason"] = ("ни один читатель не позван — знаменателя нет, и ноль "
                         "находок читался бы как ответ")
        return doc
    finding = len(doc["counts"]["finding_rows"])
    doc["status"] = "FINDING" if finding else "CLEAN"
    doc["reason"] = (
        f"списков без личности с годным полем ВНЕ списка имён: {finding}"
        if finding else
        "ни один список без личности не имеет годного поля вне _IDENTITY_FIELDS")
    return doc


def grid_report(grid: dict, *, max_cells: int = 12) -> List[str]:
    """Строки сетки порогов. Знаменатель пары — рядом с числителем, как везде."""
    axes = grid.get("axes") or {}
    pops = axes.get("population") or []
    lens = axes.get("max_length") or []
    out = [f"[ПАРА ЧИСЕЛ · ОСИ] население: {', '.join(str(x) for x in pops)} · "
           f"макс. длина: {', '.join(str(x) for x in lens)} ⇒ пар "
           f"{grid.get('pairs')}. {grid.get('axes_source')}"]
    champ = grid.get("champions") or {}
    by_pop = champ.get("by_population") or {}
    by_len = champ.get("by_max_length") or {}
    out.append(f"[ПАРА ЧИСЕЛ · ЧЕМПИОНЫ] по населению ×{by_pop.get('value')}: "
               f"{', '.join(by_pop.get('names') or [])} · по длине "
               f"{by_len.get('value')}: {', '.join(by_len.get('names') or [])}")
    for reading, title in (("both", "КОНЪЮНКЦИЯ (обе оси)"),
                           ("either", "ДИЗЪЮНКЦИЯ (любая ось)")):
        rows = distinct_taken_sets(grid, reading=reading)
        out.append(f"[ПАРА ЧИСЕЛ · {title}] различных ответов у "
                   f"{grid.get('pairs')} пар: {len(rows)} — ниже сильнейшая "
                   f"пара каждого ответа")
        for row in rows[:max_cells]:
            names = ", ".join(row.get("names") or []) or "— ничего"
            # `or 0` здесь был бы ровно инв. #17 наизнанку: ячейка, у которой
            # счётчика неизмеренных НЕТ, напечаталась бы как «неизмеренных
            # ноль». Поймано храповиком класса на этой самой строке.
            unmeasured = observed_number(row, "length_unmeasured")
            if unmeasured is None:
                tail = ("; скольким именам длина не измерена — НЕ СКАЗАНО, и "
                        "это не ноль")
            elif unmeasured:
                tail = f"; длина не измерена у {int(unmeasured)}"
            else:
                tail = ""
            out.append(f"   n≥{row.get('n_min')} и L≥{row.get('l_min')}: "
                       f"взято {row.get('taken')} — {names}{tail}")
        if len(rows) > max_cells:
            out.append(f"   … ещё {len(rows) - max_cells} ответ(ов) — полный "
                       f"перечень в {ARTIFACT}")
    # Перечень классов совпадения НЕСЁТ вердикт, поэтому его отсутствие — не
    # «пятна нет», а отсутствие замера: пустой список и отсутствующий ключ
    # отвечают на разные вопросы (инв. #17).
    collisions = observed(grid, "collisions", kind=list)
    if collisions is None:
        out.append("[ПАРА ЧИСЕЛ · НЕ ИЗМЕРЕНО] перечня классов совпадения в "
                   "сетке нет вовсе — это не «совпадающих координат нет»")
        collisions = []
    elif collisions:
        shown = "; ".join(
            f"({c.get('population')}, {c.get('max_length')}): "
            f"{', '.join(c.get('names') or [])}" for c in collisions[:max_cells])
        out.append(f"[ПАРА ЧИСЕЛ · СЛЕПОЕ ПЯТНО] координата повторяется у "
                   f"{len(grid.get('blind_names') or [])} имён в "
                   f"{len(collisions)} класс(ах): {shown} — внутри класса пара "
                   f"порогов не различает имена НИ ПРИ КАКОМ значении")
    else:
        out.append("[ПАРА ЧИСЕЛ · СЛЕПОЕ ПЯТНО] совпадающих координат нет — "
                   "пара различает все имена населения")
    if grid.get("coordinate_not_integral"):
        out.append(f"[ПАРА ЧИСЕЛ · НЕ ИЗМЕРЕНО] длина НЕ ЦЕЛАЯ у "
                   f"{len(grid['coordinate_not_integral'])} имён: "
                   f"{', '.join(grid['coordinate_not_integral'])} — число "
                   f"элементов дробным не бывает, и округлять его значило бы "
                   f"выдать поправку за наблюдение")
    if grid.get("coordinate_unmeasured"):
        out.append(f"[ПАРА ЧИСЕЛ · НЕ ИЗМЕРЕНО] длины нет у "
                   f"{len(grid['coordinate_unmeasured'])} имён: "
                   f"{', '.join(grid['coordinate_unmeasured'])} — они не "
                   f"сложены в «не взято» ни в одной ячейке")
    verdict = grid.get("rule_verdict")
    reasons = grid.get("rule_verdict_reasons") or []
    out.append(f"[ПАРА ЧИСЕЛ · ВЕРДИКТ ПРАВИЛА] {verdict}"
               + (": " + " · ".join(reasons) if reasons else
                  " — названных улик против пары на СЕГОДНЯШНЕМ населении нет; "
                  "это не «правило годно»"))
    out.append("[ПАРА ЧИСЕЛ · ГЕЙТА НЕТ] ни один порог не назначен и ни одно "
               "имя не дописано в _IDENTITY_FIELDS: выбор пары — предмет ADR, "
               "а не прибора")
    return out


def kind_axis_report(axis: dict, *, max_rows: Optional[int] = None) -> List[str]:
    """Строки оси РОДА (заказ G113 п. 1). Знаменатель — рядом с числителем.

    Укорочение перечня строк идёт ТЕМ ЖЕ числом, которым укорочен перечень
    кандидатов, и в ТОМ ЖЕ порядке: два перечня об одних и тех же именах,
    укороченные по-разному, читались бы как два разных ответа.
    """
    if str(axis.get("status")) != "MEASURED":
        return [f"НЕ ИЗМЕРЕНО: {axis.get('reason')}"]
    unparsed = observed_number(axis, "files_unmeasured")
    out = [f"кандидатов, у которых спрошен род: {axis.get('names')} · файлов "
           f"дерева разобрано {axis.get('files_parsed')}, не разобрано "
           f"{int(unparsed) if unparsed is not None else 'НЕ ИЗМЕРЕНО'}"]
    for title, key in (("ось ЧАСОВ", "by_clock_verdict"),
                       ("ось АРИФМЕТИКИ", "by_arithmetic_verdict")):
        by = observed(axis, key, kind=dict)
        if by is None:
            out.append(f"{title}: НЕ ИЗМЕРЕНО — перечня исходов нет вовсе, и "
                       f"это не «исходов ноль»")
            continue
        shown = " · ".join(f"{name}: {num}" for name, num in sorted(by.items()))
        total = sum(int(num) for num in by.values())
        # Сумма печатается РЯДОМ с перечнем: перечень закрыт, и расхождение
        # суммы с числом кандидатов есть дефект свода, а не оттенок печати.
        out.append(f"{title}: {shown} (перечень закрыт, сумма {total} из "
                   f"{axis.get('names')})")
    rows = observed(axis, "rows", kind=list)
    if rows is None:
        out.append("НЕ ИЗМЕРЕНО: перечня строк у оси нет вовсе, а кандидаты "
                   "есть — это не «родов ноль»")
        rows = []
    shown_rows = rows if max_rows is None else rows[:max_rows]
    for row in shown_rows:
        length = row.get("max_length")
        disagree = row.get("kinds_disagree")
        mark = ("" if disagree is False else
                " · РОД РАСХОДИТСЯ у площадок" if disagree else
                " · расхождение площадок НЕ ИЗМЕРЕНО")
        out.append(f"   {row.get('field')}×{row.get('population')} "
                   f"(макс. длина "
                   f"{length if length is not None else 'НЕ ИЗМЕРЕНА'}, "
                   f"род: {row.get('clock_verdict')} / "
                   f"{row.get('arithmetic_verdict')}){mark}")
    if len(shown_rows) < len(rows):
        out.append(f"   … ещё {len(rows) - len(shown_rows)} имён(и) — полный "
                   f"перечень в {ARTIFACT}")
    disagreeing = observed(axis, "disagreeing_names", kind=list)
    if disagreeing is None:
        out.append("НЕ ИЗМЕРЕНО: перечня имён с расхождением площадок нет "
                   "вовсе — это не «род нигде не расходится»")
    elif disagreeing:
        out.append(f"РАСХОЖДЕНИЕ ПЛОЩАДОК: у {len(disagreeing)} имён род РАЗНЫЙ "
                   f"у разных производителей ({', '.join(disagreeing)}) — "
                   f"ярлык имени выбран старшинством и это скрывает")
    else:
        out.append("РАСХОЖДЕНИЕ ПЛОЩАДОК: ни у одного имени род у разных "
                   "производителей не расходится")
    blind = observed(axis, "disagreement_unmeasured", kind=list)
    if blind is None:
        out.append("НЕ ИЗМЕРЕНО: перечня имён, у которых расхождение площадок "
                   "нечем судить, в документе нет вовсе — это не «таких имён "
                   "ноль»")
        blind = []
    if blind:
        out.append(f"НЕ ИЗМЕРЕНО: расхождение площадок нечем судить у "
                   f"{len(blind)} имён ({', '.join(blind)}) — счётчика площадок "
                   f"признак не дал")
    causes = observed(axis, "clock_unmeasured_causes", kind=dict)
    if causes is None:
        out.append("НЕ ИЗМЕРЕНО: перечня причин у имён без измеренного рода в "
                   "документе нет — их отсутствие не есть «род измерен у всех»")
        causes = {}
    for cause, num in sorted(causes.items()):
        out.append(f"НЕ ИЗМЕРЕНО: {cause}: {num} имён(и)")
    rule = observed(axis, "fitness_rule", kind=dict)
    if rule is None:
        out.append("ГЕЙТА НЕТ · НЕ ИЗМЕРЕНО: вердикта правила годности в "
                   "документе нет вовсе — а без него ось читается как гейт")
    else:
        out.append(f"ГЕЙТА НЕТ: правило «род ⇒ годность» — {rule.get('verdict')}"
                   f" ({rule.get('why')}); ни одно имя не дописано в "
                   f"_IDENTITY_FIELDS, выбор имени есть решение")
    return out


def reader_axis_report(axis: dict, *,
                       max_rows: Optional[int] = None) -> List[str]:
    """Строки оси ЧИТАТЕЛЕЙ. Знаменатель — рядом с числителем, как везде.

    ``max_rows`` укорачивает ОДИН перечень — поимённые строки; числа и вердикт
    печатаются всегда и целиком. Перечни «население завышено» и «классы
    распались» не укорачиваются вовсе: в них единицы имён, и спрятать хвост
    значило бы спрятать находку.
    """
    if not isinstance(axis, dict) or not axis:
        return ["ось ЧИТАТЕЛЕЙ: НЕ ИЗМЕРЕНО — свода нет вовсе"]
    if str(axis.get("status")) != "MEASURED":
        return [f"ось ЧИТАТЕЛЕЙ · НЕ ИЗМЕРЕНО: {axis.get('reason')}"]
    # `or 0` здесь было бы инв. #17 наизнанку: свод без числа имён напечатал бы
    # «имён 0», то есть выдумку. Нашла это МУТАЦИЯ (мутант `0 → 1` выжил, ибо
    # ветку не исполняла ни одна сцена) — и правка чинит ЧТЕНИЕ, как в #753.
    total = observed_number(axis, "names")
    if total is None:
        return ["ось ЧИТАТЕЛЕЙ · НЕ ИЗМЕРЕНО: свод не сказал, скольким именам "
                "он отвечает — «имён 0» тут было бы выдумкой"]
    single = observed(axis, "single_reader_names", kind=list)
    multi = observed(axis, "multi_reader_names", kind=list)
    unmeasured = observed(axis, "readers_unmeasured", kind=list)
    if single is None or multi is None or unmeasured is None:
        return ["ось ЧИТАТЕЛЕЙ · НЕ ИЗМЕРЕНО: свод не назвал все три исхода "
                "имени — доля по такому ответу была бы выдумкой"]
    out = [f"ось ЧИТАТЕЛЕЙ (заказ G114 п. 1): имён {int(total)} · население собрано "
           f"из ОДНОГО читателя у {len(single)} · из нескольких у {len(multi)} "
           f"· НЕ ИЗМЕРЕНО у {len(unmeasured)}"]
    overstated = observed(axis, "population_overstated", kind=list)
    if overstated is None:
        out.append("  НЕ ИЗМЕРЕНО: перечня имён с завышенным населением в своде "
                   "нет вовсе — это не «таких имён ноль»")
    elif overstated:
        out.append("  НАСЕЛЕНИЕ НАЗЫВАЕТ ШИРИНОЙ НЕ ШИРИНУ: " + " · ".join(
            f"{row.get('field')}×{row.get('population')} списк. у ОДНОГО "
            f"читателя" for row in overstated))
    else:
        out.append("  имён, у которых население больше единицы при одном "
                   "читателе, не нашлось — на ЭТОМ ответе ось населения "
                   "ширину свидетельства не завышает")
    for row in unmeasured:
        out.append(f"  НЕ ИЗМЕРЕНО у {row.get('field')}: {row.get('why')}")
    classes = observed(axis, "classes", kind=dict)
    if classes is None:
        out.append("  КЛАССЫ (G114 п. 2) · НЕ ИЗМЕРЕНО: раздела классов в своде "
                   "нет вовсе — это не «ни один класс не распался»")
    elif str(classes.get("status")) != "MEASURED":
        out.append(f"  КЛАССЫ (G114 п. 2) · НЕ ИЗМЕРЕНО: {classes.get('reason')}")
    else:
        # Перечни освобождённых и оставшихся слепыми читаются ТРЕТЬИМ исходом:
        # `or []` печатало бы «различимыми стали 0 · слепыми 0» на своде, который
        # об этом не сказал ни слова, — и ровно эти две подстановки переживали
        # мутацию, потому что сцены с их отсутствием не было.
        freed = observed(classes, "names_freed", kind=list)
        blind = observed(classes, "names_still_blind", kind=list)
        if freed is None or blind is None:
            out.append("  КЛАССЫ (G114 п. 2) · НЕ ИЗМЕРЕНО: свод классов не "
                       "назвал, какие имена стали различимыми и какие остались "
                       "слепыми — доля без них была бы выдумкой")
        else:
            out.append(
                f"  КЛАССЫ (G114 п. 2): классов совпадающей координаты "
                f"{classes.get('classes_total')} ⇒ РАСПАЛОСЬ "
                f"{classes.get('classes_split')} · цело "
                f"{classes.get('classes_intact')} · НЕ ИЗМЕРЕНО "
                f"{classes.get('classes_unmeasured')}; различимыми стали "
                f"{len(freed)} имён, СЛЕПЫМИ ОСТАЛИСЬ {len(blind)}")
        class_rows = observed(classes, "rows", kind=list)
        if class_rows is None:
            out.append("  КЛАССЫ (G114 п. 2) · НЕ ИЗМЕРЕНО: поимённых строк "
                       "классов в своде нет вовсе — это не «классов ноль»")
            class_rows = []
        for row in class_rows:
            if str(row.get("verdict")) == "intact":
                continue
            names_here = observed(row, "names", kind=list)
            out.append(f"    ({row.get('population')}, {row.get('max_length')}) "
                       f"{row.get('verdict')}: "
                       + (", ".join(names_here) if names_here is not None
                          else "состав класса НЕ ИЗМЕРЕН")
                       + (f" ⇒ читателей {row.get('readers_by_name')}"
                          if row.get("readers_by_name") else
                          f" — {row.get('why')}"))
    rows = observed(axis, "rows", kind=list)
    if rows is None:
        out.append("  НЕ ИЗМЕРЕНО: поимённых строк оси в своде нет вовсе, а "
                   "имена есть — свод неполон")
    else:
        shown = rows if max_rows is None else rows[:max_rows]
        out.append("  поимённо (порядок — тот же, что у перечня кандидатов): "
                   + " · ".join(
                       f"{row.get('field')}×{row.get('population')} у "
                       + (f"{row.get('readers')} читател."
                          if row.get("readers") is not None else "НЕ ИЗМЕРЕНО")
                       for row in shown)
                   + ("" if len(shown) == len(rows) else
                      f"; … ещё {len(rows) - len(shown)} — полный перечень "
                      f"в {ARTIFACT}"))
    # Причин НЕТ ВОВСЕ и причин НОЛЬ — разные ответы: второе есть вердикт
    # NOT_NEEDED (ни одно условие не предъявлено), первое — отсутствие замера.
    # `or` склеивал их в одну строку, и подмена ключа оставалась невидимой.
    why_list = observed(axis, "axis_verdict_reasons", kind=list)
    if why_list is None:
        tail = "; перечня причин у вердикта нет вовсе — это НЕ «причин ноль»"
    elif why_list:
        tail = "".join(f"; {why}" for why in why_list)
    else:
        tail = "; ни одно из двух условий не предъявлено этим населением"
    out.append(f"  ВЕРДИКТ ОСИ (вычислен, не объявлен): "
               f"{axis.get('axis_verdict')}{tail}")
    out.append("  ГЕЙТА НЕТ: порог по числу читателей не назначен, ни одно имя "
               "не дописано в _IDENTITY_FIELDS; и читатель здесь — питоний "
               "МОДУЛЬ, а не подсистема")
    return out


def report(doc: dict, *, max_rows: int = 20,
           max_fields: Optional[int] = None,
           max_cells: int = 12) -> List[str]:
    """Отчёт. Знаменатель печатается рядом с числителем — всегда."""
    out = [f"Перепись личности списков (G34 п. 1) — {doc.get('status')}"]
    # Звавший печатается ДО раннего возврата намеренно: на документе UNMEASURED
    # вопрос «кто это позвал» не менее интересен, чем на измеренном, — именно
    # так выглядел бы прогон, который ступень моста завела, а стенд не построила.
    # Запись, которую никто не читает, — это ADR-259, и заводить её второй раз,
    # зная о классе, значило бы его воспроизвести.
    out.append(f"[ЗВАВШИЙ] {provenance_line(observed(doc, 'invoked_by', kind=dict))}")
    if doc.get("status") == "UNMEASURED":
        out.append(f"[НЕ ИЗМЕРЕНО] {doc.get('reason')}")
        return out
    # Счётчиков нет ВООБЩЕ — документ не является замером, и подставлять
    # пустой словарь значит печатать нули там, где не мерили (инв. #17).
    # Найдено храповиком `test_absent_observation_ratchet` на этом самом файле:
    # он приехал на origin вчера (#626) уже красным — база класса этих двух мест
    # не знает. Погашено ЧИНКОЙ чтения, а не дописью в базу (база только
    # уменьшается, `.claude/rules/deployment.md`).
    c = observed(doc, "counts", kind=dict)
    if c is None:
        out.append("[НЕ ИЗМЕРЕНО] у документа нет счётчиков вовсе — это не "
                   "«ноль находок», а отсутствие замера")
        return out
    named = int((c.get("outcomes") or {}).get("named") or 0)
    out.append(f"[ОТВЕТ] списков в ответах: {c.get('lists_total')} · "
               f"называют себя полем: {named} · "
               f"третий исход (личности нет): {c.get('lists_total', 0) - named}")
    out.append(f"[ЗНАМЕНАТЕЛЬ] списков без личности, где вопрос ОСМЫСЛЕН "
               f"(словари, длина > 1): {c.get('denominator_of_finding')}; "
               f"синглтонов всего {c.get('singletons')} — их годность тривиальна "
               f"и в знаменатель не входит")
    out.append(f"[РЯДОМ, НЕ В ЗНАМЕНАТЕЛЕ] списков СКАЛЯРОВ длиннее одного: "
               f"{c.get('scalar_lists_multi')} — полем себя не называют по "
               f"построению, но обходятся позиционно, а элемент в них назван "
               f"своим значением; это соседний вопрос, не этот")
    called = c.get("readers_measured")
    out.append(f"[ПОЗВАНО] читателей ответило: "
               f"{called if called is not None else 'НЕ ИЗМЕРЕНО'} — "
               f"неотвечавшие названы ниже ПРИЧИНОЙ, а не нулём (инв. #17)")
    # Заказ G113 п. 2 — «ряд ли это». Печатается ОТДЕЛЬНЫМ блоком, а не
    # вмешивается в числа выше: вопрос другой, и сложить его с годностью
    # значило бы напечатать ответ, не относящийся ни к одному из двух.
    day_axis = observed(c, "day_axis", kind=dict)
    if day_axis is None:
        out.append("[ОСЬ ДНЯ] НЕ ИЗМЕРЕНО: у документа нет раздела оси дня "
                   "(заказ G113 п. 2) — отчёт СТАРОГО ОБРАЗЦА, а не «рядов "
                   "ноль»")
    else:
        for line in day_axis_report(day_axis):
            out.append(f"[ОСЬ ДНЯ] {line}")
        excluded = day_axis.get("readers_excluded_truncated")
        if excluded:
            out.append(f"[ОСЬ ДНЯ] читателей вне населения оси (обход усечён): "
                       f"{excluded} — их списки в знаменатель НЕ идут")
    for key in sorted(c.get("outcomes") or {}):
        out.append(f"[ПО ИСХОДАМ] {key}: {(c.get('outcomes') or {})[key]}")
    # Заказ G113 п. 1. Строки оси РОДА собираются ОДИН раз и печатаются в
    # ОБЕИХ ветках ниже: на документе без кандидатов ось отвечает «кандидатов
    # нет» — это её собственный третий исход, и промолчать о нём значило бы
    # сделать отсутствие раздела неотличимым от отсутствия кандидатов.
    kind = observed(c, "candidate_kind", kind=dict)
    if kind is None:
        kind_lines = ["[РОД] НЕ ИЗМЕРЕНО: раздела рода у документа нет вовсе "
                      "(заказ G113 п. 1) — отчёт СТАРОГО ОБРАЗЦА, а не «род ни "
                      "у кого не спрошен»"]
    else:
        kind_lines = [f"[РОД] {line}"
                      for line in kind_axis_report(kind, max_rows=max_fields)]
    # Заказ G114 пп. 1, 2. Строки оси ЧИТАТЕЛЕЙ собираются ОДИН раз и печатаются
    # в ОБЕИХ ветках ниже — по тому же доводу, что у оси РОДА: на документе без
    # кандидатов ось отвечает «кандидатов нет», и промолчать о нём значило бы
    # сделать отсутствие раздела неотличимым от отсутствия кандидатов.
    readers = observed(c, "candidate_reader_axis", kind=dict)
    if readers is None:
        reader_lines = ["[ЧИТАТЕЛИ] НЕ ИЗМЕРЕНО: раздела читателей у документа "
                        "нет вовсе (заказ G114 п. 1) — отчёт СТАРОГО ОБРАЗЦА, а "
                        "не «у всех имён по одному читателю»"]
    else:
        reader_lines = [f"[ЧИТАТЕЛИ] {line}"
                        for line in reader_axis_report(readers,
                                                       max_rows=max_fields)]
    # Заказ G115 п. 3. Строки разницы собираются ОДИН раз и печатаются в ОБЕИХ
    # ветках ниже — по тому же доводу, что у осей РОДА и ЧИТАТЕЛЕЙ: на документе
    # без кандидатов разница отвечает своим третьим исходом, и промолчать о нём
    # значило бы сделать отсутствие раздела неотличимым от отсутствия разницы.
    denom = observed(c, "candidate_denominator", kind=dict)
    if denom is None:
        denom_lines = ["[ЗНАМЕНАТЕЛЬ ИМЕНИ] НЕ ИЗМЕРЕНО: раздела разницы «поле "
                       "ЕСТЬ против поле ГОДНО» у документа нет вовсе (заказ "
                       "G115 п. 3) — отчёт СТАРОГО ОБРАЗЦА, а не «разницы нет»"]
    else:
        denom_lines = [f"[ЗНАМЕНАТЕЛЬ ИМЕНИ] {line}"
                       for line in cand_denom.report(denom,
                                                     max_rows=max_fields)]
    # Заказ G115 п. 1. Строки АДРЕСА собираются ОДИН раз и печатаются в ОБЕИХ
    # ветках ниже — по тому же доводу, что у осей РОДА, ЧИТАТЕЛЕЙ и
    # ЗНАМЕНАТЕЛЯ: на документе без кандидатов адрес отвечает своим третьим
    # исходом, и промолчать о нём значило бы сделать отсутствие раздела
    # неотличимым от «местом не разрешается ничего».
    address = observed(c, "finding_address", kind=dict)
    if address is None:
        address_lines = ["[АДРЕС НАХОДКИ] НЕ ИЗМЕРЕНО: раздела «место против "
                         "имени» у документа нет вовсе (заказ G115 п. 1) — "
                         "отчёт СТАРОГО ОБРАЗЦА, а не «местом не разрешается "
                         "ни одна находка»"]
    else:
        address_lines = [f"[АДРЕС НАХОДКИ] {line}"
                         for line in addr_price.report(address,
                                                       max_rows=max_fields)]
    # Заказ G115 п. 2. Строки НАСЕЛЕНИЯ односторонности собираются ОДИН раз и
    # печатаются в ОБЕИХ ветках ниже — тот же довод, что у четырёх разделов
    # выше: на документе без кандидатов население отвечает своим третьим
    # исходом, и промолчать о нём значило бы сделать отсутствие раздела
    # неотличимым от «ось не видит ни одного места».
    const_block = observed(c, "constant_operand", kind=dict)
    if const_block is None:
        const_lines = ["[ПОСТОЯННАЯ-ОПЕРАНД] НЕ ИЗМЕРЕНО: раздела населения "
                       "третьей односторонности оси у документа нет вовсе "
                       "(заказ G115 п. 2) — отчёт СТАРОГО ОБРАЗЦА, а не «ось "
                       "не пропускает ни одного места»"]
    else:
        const_lines = [f"[ОСЬ·ОДНОСТОРОННОСТЬ] {line}"
                       for line in const_operand.report(const_block,
                                                        max_rows=max_fields)]
    fields = c.get("candidate_fields_outside") or {}
    if fields:
        strength = c.get("candidate_field_strength") or {}
        # Порядок — по ДЛИНЕ, а не по частоте (ADR-410): уникальность на двух
        # элементах почти неизбежна, поэтому частотный чемпион в укороченном
        # перечне возглавил бы список, свидетельствуя слабее любого из
        # отброшенных. Пока перечень печатался ЦЕЛИКОМ, порядок был косметикой;
        # как только у него появился читатель с укорочением (`max_fields`,
        # заказ G35 п. 5), порядок стал утверждением — и он обязан совпадать с
        # тем, что сам же прибор говорит про силу свидетельства.
        # Правило порядка — ОДНОЙ копией (`_ranked_by_length`): тем же порядком
        # печатаются строки оси РОДА (заказ G113 п. 1), и расхождение двух
        # копий сделало бы две головы перечней разными утверждениями.
        ranked = _ranked_by_length(fields, strength)
        shown = ranked if max_fields is None else ranked[:max_fields]
        named_fields = ", ".join(
            f"{k}×{v} (макс. длина {strength.get(k, '?')})" for k, v in shown)
        tail = ("" if len(shown) == len(ranked) else
                f"; … ещё {len(ranked) - len(shown)} пол(я) — полный перечень "
                f"в {ARTIFACT}")
        out.append(f"[НАХОДКА] годные поля ВНЕ _IDENTITY_FIELDS "
                   f"(по убыванию ДЛИНЫ подпирающего списка): "
                   f"{named_fields}{tail}")
        out.append("[СИЛА СВИДЕТЕЛЬСТВА] «макс. длина» — длиннейший список, на "
                   "котором поле оказалось уникальным. На двух элементах "
                   "уникальность почти неизбежна и свидетельствует слабо; "
                   "дописывать имя в список по строке с длиной 2 значило бы "
                   "вернуть ту самую догадку")
        # Вторая голова — по НАСЕЛЕНИЮ (заказ G91 п. 2). Печатается РЯДОМ и
        # всегда, а не вместо и не «когда перечень укорочен»: порядок по одной
        # оси при укорочении хвоста выбрасывает чемпиона другой оси, и замер
        # 02.10 это предъявил на живом артефакте (`forward_date` ×11 — за
        # восьмёркой по длине). Два порядка НЕ складываются в один балл:
        # взвесить оси значило бы назначить порог на глаз, что заказ запрещает.
        by_pop = _ranked_by_population(fields, strength)
        pop_shown = by_pop if max_fields is None else by_pop[:max_fields]
        hidden = [k for k, _ in pop_shown if k not in {k2 for k2, _ in shown}]
        pop_line = ", ".join(
            f"{k}×{v} (макс. длина {strength.get(k, '?')})" for k, v in pop_shown)
        out.append(f"[РЯДОМ, ПО НАСЕЛЕНИЮ] те же поля в порядке населения: "
                   f"{pop_line}"
                   + (f"; порядком по длине скрыто: {', '.join(hidden)}"
                      if hidden else "; голова та же, что по длине"))
        # РОД печатается РЯДОМ с кандидатом — там, где его читают вместе с
        # населением и длиной (заказ G113 п. 1), а не отдельным разделом в
        # хвосте: решение о дописывании имени принимается по всем трём числам.
        out.extend(kind_lines)
        # И ЧИСЛО ЧИТАТЕЛЕЙ — там же (заказ G114 п. 1): оно поправляет ровно то
        # население, которое напечатано двумя строками выше, и разнести их
        # значило бы заставить читателя сшивать поправку с числом глазами.
        out.extend(reader_lines)
        # И РАЗНИЦА ЗНАМЕНАТЕЛЯ — там же (заказ G115 п. 3): она про ТО ЖЕ
        # население и отвечает на вопрос, не узко ли оно считано. Унести её в
        # хвост значило бы дать прочитать население как замер, не узнав, что у
        # того же предиката на широком знаменателе число другое.
        out.extend(denom_lines)
        # И АДРЕС НАХОДКИ — там же (заказ G115 п. 1): он отвечает, разрешима ли
        # находка дописанным ИМЕНЕМ (решение, которое читатель и принимает по
        # трём числам выше) или только адресом МЕСТА, которому населения не
        # нужно вовсе. Унести это в хвост значило бы дать принять решение о
        # дописывании имени, не узнав, что у части находок имя тут ни при чём.
        out.extend(address_lines)
        # И НАСЕЛЕНИЕ ОДНОСТОРОННОСТИ — там же (заказ G115 п. 2): оно отвечает,
        # сколько мест ось рода выше не видит ВООБЩЕ и задето ли ими хоть одно
        # из имён, о которых идёт спор. Унести это в хвост значило бы дать
        # прочитать род как полный ответ о коде, не узнав цены его слепоты.
        out.extend(const_lines)

        rows = observed(c, "finding_rows", kind=list)
        if rows is None:
            out.append("[НЕ ИЗМЕРЕНО] перечня строк-находок у документа нет "
                       "вовсе, а поля-кандидаты есть — документ неполон, и "
                       "пустой перечень тут читался бы как «находок нет»")
            rows = []
        for row in rows[:max_rows]:
            out.append(f"   {row.get('module')} {row.get('coord')} "
                       f"(элементов {row.get('n')}): {', '.join(row.get('candidates') or [])}")
        if len(rows) > max_rows:
            out.append(f"   … ещё {len(rows) - max_rows} строк(и) — полный "
                       f"перечень в {ARTIFACT}")
        # Сетка порогов печатается ПОСЛЕ строк-находок намеренно: она отвечает
        # не на «какие поля годны», а на «что взяла бы пара порогов, если её
        # назначить», и вклинивать её между полями и их строками значило бы
        # разорвать один ответ надвое.
        grid = observed(c, "threshold_grid", kind=dict)
        if grid is None:
            out.append("[НЕ ИЗМЕРЕНО] сетки порогов по паре чисел в документе "
                       "нет вовсе — это не «пара ничего не берёт»")
        elif str(grid.get("status")) != "MEASURED":
            out.append(f"[НЕ ИЗМЕРЕНО] пара порогов: {grid.get('reason')}")
        else:
            out.extend(grid_report(grid, max_cells=max_cells))
    else:
        out.append("[ОПОРА] годных полей вне списка имён не нашлось — нынешний "
                   "список имён не занижает личность ни у одного списка населения")
        out.extend(kind_lines)
        out.extend(reader_lines)
        out.extend(denom_lines)
        out.extend(address_lines)
        out.extend(const_lines)
    if c.get("truncated_readers"):
        out.append(f"[НЕ ДОСМОТРЕНО] обход упёрся в потолок у читателей: "
                   f"{', '.join(c['truncated_readers'])} — их списки в знаменатель "
                   f"находки не включены")
    causes = observed(c, "unmeasured_causes", kind=dict)
    if causes is None:
        out.append("[НЕ ИЗМЕРЕНО] перечня причин у непозванных читателей в "
                   "документе нет — их отсутствие не есть «позваны все»")
    else:
        for cause, num in sorted(causes.items()):
            out.append(f"[НЕ ИЗМЕРЕНО] {cause}: {num} читател(ей)")
    out.append(f"ADVISORY: {doc.get('advisory')}")
    return out


def format_report(doc: dict, *, max_rows: int = 5,
                  max_fields: int = 8, max_cells: int = 6) -> List[str]:
    """Строки для ЧИТАТЕЛЯ переписи — обязательного шага 0-офис (заказ G35 п. 5).

    Второй копии правила отрисовки здесь НЕТ намеренно: ветка шага 0-офис
    делегирует сюда, а эта функция — в ``report``, поэтому расхождение «в
    консоли одно, в отчёте другое» невозможно по построению. Отличий ровно два,
    и оба — про читателя, а не про предмет: находка помечается знаком, на
    который у офиса заведено правило «красные строки = действовать», и перечни
    укорачиваются (строк-находок и полей-кандидатов; полный перечень лежит в
    артефакте, и строка об укорочении это говорит). Укорочение — единственная
    причина, по которой ПОРЯДОК полей стал утверждением, а не косметикой:
    режется хвост, значит голова обязана быть сильнейшим свидетельством, то
    есть самым ДЛИННЫМ списком, а не самым частым именем.
    """
    lines = report(doc, max_rows=max_rows, max_fields=max_fields,
                   max_cells=max_cells)
    if str(doc.get("status")) == "FINDING":
        lines[0] = f"⚠️ {lines[0]}"
    return lines


def run(root: str | Path = _ROOT, *, data_dir: Optional[Path] = None,
        dest: Optional[Path] = None, write: bool = True, if_due: bool = True,
        now: Optional[dt.datetime] = None,
        tact_days: int = MEASUREMENT_TACT_DAYS) -> dict:
    """Один ТАКТ переписи для ступени моста: мерить, только если срок пришёл.

    Зачем эта обёртка, если есть ``measure``. У ступени переписей
    (``findings_bridge.CENSUS_STAGE``) объявленная форма вызова — ``<модуль>.run(
    root=args.root)``, и она не прихоть: ровно по этой форме сторожа
    (`test_cio_acceptance_guards_are_wired`, `_orphan_producer`) отвечают на
    вопрос «а есть ли на свете вызов, который этот артефакт пишет». Заказ G35
    п. 5 — про то, что у числа не было ни ЧИТАТЕЛЯ, ни автоматического
    производителя: ступень (1ж) соседа живёт СТРОКОЙ В ПРОМПТЕ, а строка не
    есть вызов (замер 18.09: автоматического зова не наблюдалось ни одного).

    **«Не мерили» и «измерено» — РАЗНЫЕ исходы** (инв. #17), поэтому внутри
    такта возвращается ``{"measured": False, "reason": …}`` и НЕ выдумывается
    вердикт переписи: ``CLEAN`` в этой ветке был бы утверждением о населении,
    которого никто не смотрел. Срок решает ФАЙЛ (``measurement_due``), а не
    расписание бегуна: иначе «раз в неделю» держалось бы на том, что никто не
    менял такт агента.
    """
    root = Path(root)
    source = Path(data_dir) if data_dir is not None else root / "data"
    target = Path(dest) if dest is not None else source / ARTIFACT
    if if_due:
        due, why = measurement_due(target, now=now, tact_days=tact_days)
        if not due:
            return {"measured": False, "reason": why, "artifact": str(target)}
    doc = measure(source, root, now=now)
    if write:
        atomic_save(doc, str(target))
    return {"measured": True, "doc": doc, "artifact": str(target)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="перепись списков без личности в ответах питоньих читателей (G34 п. 1)")
    ap.add_argument("--data-dir", default=str(_ROOT / "data"),
                    help="каталог data/, с которого строится стенд (КОПИЯ, не правится)")
    ap.add_argument("--tree-root", default=str(_ROOT))
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--if-due", action="store_true",
                    help=f"мерить, только если со дня прошлого замера прошло "
                         f"{MEASUREMENT_TACT_DAYS} дн")
    args = ap.parse_args(argv)

    dest = Path(args.out) if args.out else Path(args.data_dir) / ARTIFACT
    # Гейт такта живёт в ОДНОМ месте (`run`) — вторая его копия здесь означала
    # бы, что ступень моста и рука владельца судят о сроке по разным правилам.
    outcome = run(Path(args.tree_root), data_dir=Path(args.data_dir), dest=dest,
                  write=not args.no_write, if_due=args.if_due)
    if not outcome["measured"]:
        print(f"замер не назначен: {outcome['reason']}")
        return 0
    doc = outcome["doc"]
    for line in report(doc):
        print(line)
    return {"UNMEASURED": 2, "FINDING": 1}.get(str(doc.get("status")), 0)


if __name__ == "__main__":
    raise SystemExit(main())
