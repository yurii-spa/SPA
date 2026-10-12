"""Объявление офиса, которого площадка соседа НЕ НЕСЁТ: ТРИ ДРУГИЕ двери.

# LLM_FORBIDDEN

Заказ **G698 п. 3** приказа владельца «Portfolio CIO» — дословный хвост
ADR-698:

    «Та же форма у ДРУГОЙ двери — не измерено вовсе. `_schema_drift` — не
    единственное место, где объявленный перечень встречается с документом
    фикстуры: рядом живут `_PRODUCER` (сверка с исходником производителя),
    `_TS_FIELD`/`_TS_UNIT` (поле отметки времени) и манифест артефактов.
    Объявление в любом из них, которого фикстура соседа не несёт, даёт тот же
    вред с тем же почерком, и население этих трёх дверей не спрошено ни разу.»

## Почему это ПЯТЬ дверей, а не три

Заказ назвал три ТАБЛИЦЫ; дверей у них пять, и каждая спрашивает своё:

| дверь | что обязана нести площадка | сила утверждения |
|---|---|---|
| `ts_field_declared` | поле отметки, объявленное в `_TS_FIELD` | **объявление** |
| `ts_field_default` | `generated_at` — умолчание `_produced_at` | **умолчание** |
| `ts_unit` | значение в объявленной `_TS_UNIT` единице | **объявление** |
| `producer` | у артефакта со схемой объявлен `_PRODUCER` | **объявление** |
| `manifest` | такт производителя измерим у ВСЕХ артефактов офиса | **объявление** |

Деление по силе утверждения — не украшение. `_TS_FIELD` есть ОБЪЯВЛЕНИЕ: кто-то
вписал строку, сверил её с исходником производителя, и фикстура, этого поля не
несущая, спорит с объявлением. `generated_at` никто не объявлял — это
умолчание `_produced_at`, и площадка без него спорит не с объявлением, а с
привычкой. Сложить два населения в одно значило бы ответить на третий вопрос,
которого не задавал никто (урок ADR-695).

## Операнд — ОДИН, и он берётся у соседа, а не пересчитывается

Площадки (пара «тест × артефакт» с разрешённым документом) разрешает
`_fixture_schema_gap.measure`, и второй копии этого разбора здесь нет: он стоил
четырёх циклов исправлений (ADR-699/700/701), и расхождение двух копий было бы
молчаливым (урок ADR-502). Меняется только перечень ОБЪЯВЛЕННЫХ ПУТЕЙ, который
прибору передаётся входом: у двери `ts_field_declared` это `{артефакт: (поле,)}`
из `_TS_FIELD`, у `ts_field_default` — `{артефакт: ("generated_at",)}`.

Дверь `manifest` мерится ИНАЧЕ и нарочно: у неё спрашивается САМ офисный
решатель (`consume_office_reports._producer_tick_hours`), а не его копия.
Второй поиск того, что сосед уже раскрывает, расходится молча — урок #820
(ADR-682), где такая копия спрятала 25 площадок из 37. Перечень артефактов
офиса тоже берётся у офиса (`office_targets`), а не отбирается здесь по памяти.

## Три исхода у КАЖДОЙ двери

«Население 0» и «спрашивать было некого» — разные ответы, и свёртка второго в
первый есть ровно инвариант #17 наизнанку. Поэтому у двери три поля:
`population` (объявление есть, площадка его не несёт), `third` (измерить не
удалось — с НАЗВАННОЙ причиной) и `sites` (сколько площадок дверь вообще
видела). Ноль населения при нуле площадок — НЕ «чисто»: это
`no_site_feeds_the_subject`, и дверь говорит это вслух.

## Чего мера НЕ говорит

* **Не говорит, что площадка краснеет сегодня.** Население здесь ЛАТЕНТНОЕ,
  как и у соседа: у двери `ts_field_*` следствие — строка «возраст НЕ ИЗМЕРЕН»
  в выводе офиса на этой площадке, и краснеет она только у сцен, пришпиливающих
  вывод целиком.
* **Про единицу отметки (`ts_unit`) она отвечает ТОЛЬКО о присутствии
  площадки.** Сравнить значение с объявленной единицей нечем: скелет
  `_fixture_schema_gap` кладёт на место листа заглушку (`LEAF`), значение в нём
  не живёт по построению. Это предел ПРИБОРА, и он назван третьим исходом, а не
  выдан за «единица сошлась».
* **Не судит о правдивости объявления.** «Поле объявлено верно» — вопрос
  соседних тестов (`test_ts_field_matches_producer`, `test_ts_unit_matches_producer`),
  и они идут от ИСХОДНИКА производителя, а эта мера — от объявления к фикстурам.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from spa_core.tests import _fixture_schema_gap as gap

#: Пин набора дверей: РАВЕНСТВО, а не вхождение. Новая дверь обязана быть
#: объявлена здесь, исчезнувшая — краснеет. Тот же порядок, что у `DOC_KEYS`
#: соседей.
DOOR_KEYS = ("ts_field_declared", "ts_field_default", "ts_unit",
             "producer", "manifest")

#: Сила утверждения двери — см. таблицу в справке модуля.
DECLARED, DEFAULTED = "объявление", "умолчание"

#: Причина третьего исхода: дверь есть, а спрашивать некого.
NO_SITE = "no_site_feeds_the_subject"

#: Причина третьего исхода: значение листа скелет не хранит по построению.
NO_VALUE = "value_not_kept_by_the_skeleton"


#: Единица операнда двери. У дверей документа это ПЛОЩАДКА (пара «тест ×
#: артефакт»), у дверей объявления — сам АРТЕФАКТ: вопрос «объявлен ли рядом
#: производитель» решается таблицами и фикстуры не требует вовсе. Сложить их в
#: одно число значило бы делить находки на знаменатель другого вопроса.
SITES, ARTIFACTS = "площадки", "артефакты"


@dataclass(frozen=True)
class Door:
    """Одна дверь объявления: что обязано нестись и кто этого не несёт."""

    name: str
    claim: str
    strength: str
    operand: str
    operand_size: int
    subject_artifacts: int
    #: `(где, артефакт, чего не несёт)` — объявление есть, площадка его не несёт.
    population: tuple[tuple[str, str, str], ...] = ()
    #: `(о чём, причина)` — НЕ ИЗМЕРЕНО. Нулём не становится никогда.
    third: tuple[tuple[str, str], ...] = ()
    #: Площадки населения, несущие пометку `# SCHEMA-GAP-OK` СОСЕДНЕЙ двери.
    #: Освобождение дано ДРУГОМУ вопросу, и молча распространять его сюда
    #: нельзя (урок ADR-701 п. 3: освобождение принадлежит площадке и своей
    #: причине). Поэтому они ВХОДЯТ в население и названы отдельной графой.
    exempt_at_the_neighbour: tuple[str, ...] = ()

    @property
    def measured_zero(self) -> bool:
        """Ноль ИЗМЕРЕННЫЙ: операнд был, и ни одна его единица не теряет
        объявления. Ноль при пустом операнде — НЕ этот ответ."""
        return not self.population and self.operand_size > 0


@dataclass
class Doors:
    doors: dict[str, Door] = field(default_factory=dict)
    #: Описание операнда двери манифеста: артефакты офиса, чей объявленный путь
    #: НЕ равен `data/<имя>`. Это не находка, а свойство конституции — но
    #: именно на нём склейка адреса и ломалась.
    addressed_elsewhere: tuple[str, ...] = ()
    targets: int = 0

    def __getitem__(self, key: str) -> Door:
        return self.doors[key]

    @property
    def keys_pin(self) -> tuple[str, ...]:
        return tuple(sorted(self.doors))


def _site_census(office, *, schema, root, test_dirs):
    return gap.measure(schema=schema, has_path=office._has_path, root=root,
                       test_dirs=test_dirs)


def _door_from_census(name: str, claim: str, strength: str, census,
                      subject: dict) -> Door:
    """Дверь документа: население — площадки, потерявшие объявленный путь.

    Освобождения соседа (`# SCHEMA-GAP-OK`) в население ВХОДЯТ: пометка
    выдана под причину двери `_READ_SCHEMA`, и зачесть её здесь значило бы
    освободить площадку от вопроса, которого никто при ней не задавал. Их
    число названо отдельной графой — чтобы цена решения была видна, а не
    спрятана в итоге.
    """
    losing = [s for s in census.sites if s.missing]
    population = tuple((s.file + ":" + str(s.line), s.artifact, ", ".join(s.missing))
                       for s in losing)
    third: list[tuple[str, str]] = []
    if not census.sites:
        third.append((f"дверь {name}", NO_SITE))
    return Door(name=name, claim=claim, strength=strength,
                operand=SITES, operand_size=len(census.sites),
                subject_artifacts=len(subject),
                population=population, third=tuple(third),
                exempt_at_the_neighbour=tuple(
                    s.file + ":" + str(s.line) for s in losing
                    if s.exempt_reason))


def measure(*, office, root: str,
            test_dirs: tuple[str, ...] = gap.DEFAULT_TEST_DIRS,
            consumer: str | None = None) -> Doors:
    """Перепись пяти дверей объявления.

    `office` приезжает ВХОДОМ — это тот самый модуль шага 0-офис, чьи
    объявления и решатели здесь спрашиваются. Копии его правил в приборе нет
    ни одной: таблицы берутся атрибутами, адрес артефакта — его же функцией.
    """
    out = Doors()

    # Дверь 1: объявленное поле отметки времени.
    subject1 = {a: (f,) for a, f in office._TS_FIELD.items()}
    c1 = _site_census(office, schema=subject1, root=root, test_dirs=test_dirs)
    out.doors["ts_field_declared"] = _door_from_census(
        "ts_field_declared", "поле отметки, объявленное в `_TS_FIELD`",
        DECLARED, c1, subject1)

    # Дверь 2: умолчание `generated_at` — у артефактов БЕЗ объявления.
    subject2 = {a: ("generated_at",) for a in office._READ_SCHEMA
                if a not in office._TS_FIELD}
    c2 = _site_census(office, schema=subject2, root=root, test_dirs=test_dirs)
    out.doors["ts_field_default"] = _door_from_census(
        "ts_field_default", "`generated_at` — умолчание `_produced_at`",
        DEFAULTED, c2, subject2)

    # Дверь 3: объявленная ЕДИНИЦА отметки. Площадки берутся у двери 1 — это
    # те же площадки (ключи `_TS_UNIT` входят в `_TS_FIELD`), а значение листа
    # скелет не хранит, поэтому сама единица — третий исход прибора.
    unit_arts = set(office._TS_UNIT)
    unit_sites = [s for s in c1.sites if s.artifact in unit_arts]
    third3: list[tuple[str, str]] = []
    if not unit_sites:
        third3.append((f"артефакты {sorted(unit_arts)}", NO_SITE))
    else:
        third3 += [(s.file + ":" + str(s.line), NO_VALUE) for s in unit_sites]
    out.doors["ts_unit"] = Door(
        name="ts_unit", claim="значение в объявленной `_TS_UNIT` единице",
        strength=DECLARED, operand=SITES, operand_size=len(unit_sites),
        subject_artifacts=len(unit_arts), population=(), third=tuple(third3))

    # Дверь 4: у артефакта объявлена схема, а производитель — нет. Тогда
    # `_schema_drift` теряет свой трёхсторонний ответ: «производитель поля не
    # пишет» и «отчёт старого образца» становятся одной строкой.
    # Операнд здесь — АРТЕФАКТ, а не площадка: вопрос решается двумя
    # таблицами, и фикстура соседа для него не нужна вовсе.
    no_producer = [a for a in office._READ_SCHEMA if a not in office._PRODUCER]
    out.doors["producer"] = Door(
        name="producer", claim="у артефакта со схемой объявлен `_PRODUCER`",
        strength=DECLARED, operand=ARTIFACTS,
        operand_size=len(office._READ_SCHEMA),
        subject_artifacts=len(office._READ_SCHEMA),
        population=tuple((a, a, "`_PRODUCER` не объявлен") for a in no_producer))

    # Дверь 5: такт производителя у ВСЕХ артефактов офиса. Спрашивается САМ
    # решатель офиса; перечень артефактов — его же `office_targets`.
    out.doors["manifest"] = _manifest_door(office, root=root, consumer=consumer,
                                           out=out)
    return out


def _manifest_door(office, *, root: str, consumer: str | None, out: Doors) -> Door:
    mpath = os.path.join(root, "architecture", "manifest.json")
    try:
        with open(mpath, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except Exception as exc:  # noqa: BLE001
        # Конституция не прочитана ⇒ дверь НЕ ИЗМЕРЕНА. Это не «население 0».
        return Door(name="manifest",
                    claim="такт производителя измерим у всех артефактов офиса",
                    strength=DECLARED, operand=ARTIFACTS, operand_size=0,
                    subject_artifacts=0,
                    third=((mpath, f"манифест не прочитан ({type(exc).__name__})"),))
    targets = office.office_targets(manifest, consumer or office.CONSUMER)
    out.targets = len(targets)
    out.addressed_elsewhere = tuple(
        sorted(p for p in targets if p != f"data/{os.path.basename(p)}"))
    population: list[tuple[str, str, str]] = []
    for rel in sorted(targets):
        name = os.path.basename(rel)
        tick, why = office._producer_tick_hours(name, root)
        if tick is None:
            population.append((rel, name, why))
    return Door(name="manifest",
                claim="такт производителя измерим у всех артефактов офиса",
                strength=DECLARED, operand=ARTIFACTS, operand_size=len(targets),
                subject_artifacts=len(targets), population=tuple(population))


def report(doors: Doors) -> list[str]:
    """Строки замера — по одной на дверь, и третий исход виден отдельно."""
    lines = [f"[ОПЕРАНД] артефактов офиса {doors.targets}; объявлены НЕ по адресу "
             f"`data/<имя>` — {len(doors.addressed_elsewhere)}"]
    for key in DOOR_KEYS:
        d = doors[key]
        lines.append(
            f"[ДВЕРЬ {d.name}] {d.strength} · артефактов в предмете "
            f"{d.subject_artifacts} · {d.operand} {d.operand_size} · население "
            f"{len(d.population)} · НЕ ИЗМЕРЕНО {len(d.third)}"
            + (f" · освобождено у СОСЕДА {len(d.exempt_at_the_neighbour)}"
               if d.exempt_at_the_neighbour else "")
            + ("" if d.operand_size else f"  ⚠️ {d.operand} НЕТ — это НЕ «чисто»"))
        for where, artifact, what in d.population:
            lines.append(f"    {where} · {artifact} · не несёт: {what}")
        for about, why in d.third:
            lines.append(f"    [НЕ ИЗМЕРЕНО] {about}: {why}")
    return lines
