"""cio_kill_switch_controls.py — §42 ТЗ «Portfolio CIO»: сколько органов
остановки у владельца есть на самом деле и что каждый из них ДЕЛАЕТ.

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §42 «Kill switch»::

    Обязательно:
    PAUSE CIO
    PAUSE AUTO EXECUTION
    EMERGENCY STOP
    Owner должен иметь возможность остановить execution без остановки
    monitoring/reporting.

Три органа названы ВЛАДЕЛЬЦЕМ, а не нами; порядок и формулировки — его. И
требований здесь ДВА, а не одно: «органов должно быть три» и «остановка
исполнения не должна гасить наблюдение». Их легко слить в один вопрос и
ответить «стоп-кран есть» — а это ответ не на то.

Ответ на «мерил ли кто-нибудь» — НЕТ, и это не то же самое, что «крана нет»
==========================================================================
Стоп-кран у нас есть и он проверен со своей стороны: двухступенчатая лестница
просадки (ADR-034/048) закрыта тестами, тревога владельцу доставляется
(``test_killswitch_alert_reaches_owner``), состояние переживает восстановление
дерева (``test_halt_state_survives_tree_restore``). Все эти проверки отвечают
на вопрос «работает ли кран, когда сработал». §42 спрашивает другое: **сколько
у владельца РУЧЕК, что каждая делает с книгой, и что при этом остаётся живым.**
Такого замера не делал никто, и чтением кода его не получить — только опытом
над настоящим путём решения.

Дверь ищется в канале ВЛАДЕЛЬЦА, а не в дереве
===============================================
«Орган остановки» — это не функция в модуле, а то, что владелец может нажать.
Поэтому поверхность перечисляется не списком из головы, а разбором карты
«команда → метод» внутри ``_dispatch`` (``spa_core/telegram/bot.py``, разбор
дерева, не подстрока), и для каждой команды измеряется, пишет ли она файл
состояния и КАКОЙ.

**Поправка 13.10 (ADR-712): перечислялось не то, что сказано здесь.** До этой
даты набор снимался с ``TelegramBot._COMMANDS``, а строка выше утверждала, что
это «то, что бот ПУБЛИКУЕТ владельцу как меню». Публикует бот другое — нагрузку
``setMyCommands`` (16 команд против 13), и ``_COMMANDS`` был побайтовой КОПИЕЙ
ключей карты ``_dispatch``, которую в самом боте не читал никто. Копия снята;
перечисление идёт по САМОЙ карте, потому что по ней идёт настоящая отправка.
Вердикты от поправки не изменились ни одним полем — множества были равны, и это
ИЗМЕРЕНО, а не предположено.

**Что здесь перечисляется и что НЕТ.** Карта диспетчера — это кнопки панели
(``_dispatch`` зовётся из ветви ``callback_query``; набранный текст уходит в
Router и сюда не попадает никогда). Это ровно та поверхность, где живут
``/pause`` и ``/resume``, то есть предмет §42. Набранные команды и меню ☰ —
соседние вопросы, и их согласие мерит отдельный прибор
``owner_command_surfaces`` (ADR-712): равнять их с этой картой значило бы
вытереть аварийную остановку из переписи органов — её в меню ☰ нет намеренно.

Дальше — главное: **чем дверь ОКАЗАЛАСЬ, решает опыт, а не её название.**
Извлечённая полезная нагрузка подставляется настоящему пути решения, и эффект
меряется по книге. Кнопка, подписанная «⏸ Пауза», может делать что угодно;
подпись — не измерение. (Именно эта подпись и была исправлена по ADR-286 §3 на
«🛑 Аварийная остановка» — но вердикт CONFLATED держится не на ней, а на ИМЕНИ
КОМАНДЫ `/pause`, из которого выводится претензия на орган PAUSE CIO. Снимет
его только шаг 2 — появление настоящей паузы, — а не косметика подписи.)

Саму ручку модуль НЕ дёргает НИКОГДА
=====================================
``cmd_pause`` вызвать нельзя: его ``KILL_SWITCH_FILE`` связан с боевым
``data/`` в момент импорта, и «проверить, нажав» означало бы РЕАЛЬНО взвести
боевой стоп-кран — ровно тот класс, где проверка исполняет запрещённое.
Поэтому нагрузка двери снимается разбором дерева (что именно она пишет), а
подставляется — во ВРЕМЕННЫЙ каталог состояния. Живой ``data/`` этим модулем
не читается и не пишется ни разу: иначе вердикт зависел бы от хоста.

Четыре исхода на орган, и третий — самостоятельный
===================================================
``PRESENT``
    дверь есть, и измеренный эффект соответствует тому, что обещает её имя.
``CONFLATED``
    дверь есть, но её измеренный эффект — эффект ДРУГОГО органа. Владелец
    нажимает одно имя и получает другое. Это не «есть»: слить в отчёте
    «кран есть» и «кран есть, но он другой» значит потерять ровно ту разницу,
    ради которой владелец назвал три имени, а не одно.
``ABSENT``
    двери нет ни одной.
``UNCHECKED``
    измерить не удалось (причина названа). Не ноль и не скип.

Положительный контроль — условие ВСЕГО отчёта, а не украшение
==============================================================
«После двери книга опустела» ничего не значит, если она была пуста и до неё; а
«наблюдение пережило дверь» ничего не значит, если дверь ни на что не
подействовала. Поэтому счёт читается, только если выполнены ОБА условия:

1. на здоровой сцене (двери нет) путь решения оставляет капитал развёрнутым;
2. хотя бы одна перечисленная дверь ДОКАЗАННО меняет путь решения.

Не выполнено — ``control.passed = False``, ``overall = UNCHECKED``, и счёт по
органам читать нельзя. Второе условие важнее первого: без него ответ
«monitoring пережил остановку» произносился бы и в мире, где остановки не
произошло вовсе.

Проверено и НЕ находка
======================
Список all-cash строится из ФИДА (``adapter_status.json`` → орк-снимок), а не
из книги, поэтому напрашивается вопрос: не останется ли профинансированным
пул, которого сегодня нет в фиде? Измерено настоящими функциями
(``_allocation_diff_usd``, ``one_sided_turnover``): отсутствие ключа в цели
эквивалентно явному нулю — обе формы дают тот же оборот и ту же итоговую
книгу. Находки здесь нет, и сказано это вслух, чтобы её не «нашли» второй раз.

Две оси, добавленные #1105 (ADR-988): артефакт моложе правки может описывать мир ДО неё
======================================================================================
ADR-249 и артефакт 29.10 судили дверь на ДВУХ ступенях цикла (Step 2c override ·
Step 2c-soft). С 28.10 (ADR-850) в цикле стои́т Step 2e'' — урезание хода до
допустимого РАЗМЕРА, — и оно стои́т ПОСЛЕ стоп-крана. Аварийный выход — тоже
ход, и вопрос «не дозирует ли трим аварийный выход до 15 % капитала за цикл»
до #1105 не задавался никому. Ось ``trim_under_door`` зовёт НАСТОЯЩИЙ
``apply_admissible_trim`` над книгой, которую оставил стоп-кран; положительный
контроль — перетасовка той же сцены ТЕМ ЖЕ тримом урезается (k < 1), иначе
«выход не урезан» ничего не доказывает.

Вторая ось — ``pause_auto_execution_candidate``: единственный переключатель в
дереве, похожий на орган «PAUSE AUTO EXECUTION», — взвод CIO
(``cio_arming.ARMED_BOOKS``, ADR-324/328). Прибор меряет, (а) где живёт его
состояние (разбор дерева: литерал в коде, файлов и окружения модуль не
читает), (б) пишет ли туда хоть одна дверь владельца, (в) что СДЕЛАЛ БЫ снятый
взвод — настоящим ``trade_allowed`` над перетасовкой: невзведённая книга
отвечает ``UNARMED`` и ход ПРОПУСКАЕТ (решает прежнее правило цикла), то есть
снятие взвода не держит книгу, а возвращает её прежнему исполнителю. Это НЕ
орган паузы, и сказано это измерением, а не чтением.

ADVISORY. Ни один орган этим модулем не строится и не двигается: добавить
владельцу ручку, которая останавливает движение денег, — money-path и решение
владельца, а не строка замера.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from spa_core.utils.observation import observed, observed_number

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/cio_kill_switch_controls.json"

#: Файл канала владельца — единственное место, где ручка становится нажимаемой.
OWNER_CHANNEL_REL = "spa_core/telegram/bot.py"

PRESENT = "PRESENT"
CONFLATED = "CONFLATED"
ABSENT = "ABSENT"
UNCHECKED = "UNCHECKED"

#: Измеренные эффекты двери на книгу. Имена описывают ПОВЕДЕНИЕ, а не намерение.
EFFECT_ALL_CASH = "ALL_CASH"        # книга опустошается: все позиции в ноль
EFFECT_HOLD_ONLY = "HOLD_ONLY"      # книга сохраняется, новое/увеличение закрыто
EFFECT_NO_EFFECT = "NO_EFFECT"      # путь решения не изменился
EFFECT_UNMEASURED = "UNMEASURED"

#: Три органа §42 в порядке ТЗ. Поля: ключ · дословная формулировка владельца ·
#: что имя обещает · ожидаемый ЭФФЕКТ · откуда взят этот эффект · слова, по
#: которым дверь ПРЕТЕНДУЕТ на этот орган.
#:
#: Ожидаемый эффект НЕ назначен модулем — он взят у собственной лестницы
#: остановки системы, утверждённой владельцем (ADR-034/048): `SOFT_DERISK`
#: там дословно «halt new / no INCREASE, НЕ ликвидирует» — это и есть пауза;
#: `HARD_KILL` — «full kill → all-cash». Придумай модуль свою шкалу, вердикт
#: спорил бы с конституцией вместо того, чтобы её мерить.
#:
#: `claim_words` разделяют «двери нет вовсе» и «дверь есть, но делает другое».
#: Дверь претендует на орган, если ВСЕ слова встречаются в том, что владелец о
#: ней видит (команда · имя обработчика · текст, который она пишет). Без этого
#: любой существующий кран засчитывался бы подменой любому органу.
OWNER_CONTROLS: tuple[tuple[str, str, str, str, str, tuple[str, ...]], ...] = (
    ("pause_cio", "PAUSE CIO",
     "CIO перестаёт решать о книге; книга остаётся такой, какая есть",
     EFFECT_HOLD_ONLY,
     "ADR-034/048, ступень SOFT_DERISK: «halt new / no INCREASE, НЕ ликвидирует»",
     ("pause",)),
    ("pause_auto_execution", "PAUSE AUTO EXECUTION",
     "CIO продолжает предлагать, но предложенное не исполняется само",
     EFFECT_HOLD_ONLY,
     "ADR-034/048, ступень SOFT_DERISK: «halt new / no INCREASE, НЕ ликвидирует»",
     ("pause", "execution")),
    ("emergency_stop", "EMERGENCY STOP",
     "аварийная остановка: система немедленно снимает экспозицию",
     EFFECT_ALL_CASH,
     "ADR-034/048, ступень HARD_KILL: «full kill → all-cash»",
     ("kill",)),
)

#: Капитал сцены. Не порог и ничего не решает — доли ниже выводятся из него же,
#: поэтому число можно менять, не меняя смысла ни одной пробы.
_SCENE_CAPITAL_USD = 100_000.0

#: Файл взвода CIO — единственный переключатель дерева, похожий на орган
#: «PAUSE AUTO EXECUTION» (ADR-324/328). Разбирается деревом, не импортом
#: умолчания: реестр читается в момент вызова (урок #1103).
ARMING_REL = "spa_core/paper_trading/cio_arming.py"

#: Исходы оси «аварийный выход под тримом» (ADR-850 · ADR-988).
TRIM_EXEMPT = "EXEMPT"        # трим выход не тронул, и причина НАЗВАНА дверью демпфера
TRIM_DOSED = "DOSED"          # трим урезал аварийный выход — выход растянут на циклы
#: Исходы оси «кандидат органа PAUSE AUTO EXECUTION».
CANDIDATE_NOT_THE_ORGAN = "NOT_THE_ORGAN"   # снятый взвод ход ПРОПУСКАЕТ, а не держит
CANDIDATE_WOULD_HOLD = "WOULD_HOLD"         # снятый взвод держит книгу — кандидат годен


# ───────────────────────────── канал владельца ──────────────────────────────

def _module_state_files(tree: ast.Module) -> dict[str, str]:
    """Модульные константы вида ``NAME = DATA_DIR / "имя.json"`` → имя файла.

    Разбор дерева, а не поиск подстроки: подстрока нашла бы имя и в docstring.
    """
    out: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        value = node.value
        if (isinstance(target, ast.Name)
                and isinstance(value, ast.BinOp)
                and isinstance(value.op, ast.Div)
                and isinstance(value.right, ast.Constant)
                and isinstance(value.right.value, str)):
            out[target.id] = value.right.value
    return out


def _literal_payload(node: ast.AST) -> tuple[dict, list[str]]:
    """Литеральная часть словаря-нагрузки + имена ключей, которые НЕ литералы.

    Нелитеральные значения (``datetime.now(...)``) сознательно отбрасываются, а
    их ключи называются: подставлять в пробу выдуманное время значило бы мерить
    свою выдумку. Читателю двери важны ``active``/``reason`` — они литералы.
    """
    payload: dict[str, Any] = {}
    dropped: list[str] = []
    if not isinstance(node, ast.Dict):
        return payload, dropped
    for key, value in zip(node.keys, node.values):
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            continue
        if isinstance(value, ast.Constant):
            payload[key.value] = value.value
        else:
            dropped.append(key.value)
    return payload, dropped


def _owner_doors(root: str) -> dict:
    """Что владельцу ОПУБЛИКОВАНО как меню и какие из этих команд пишут состояние.

    Возвращает ``{"commands": [...], "doors": [...], "unchecked": str|None}``.
    Дверь — команда, которая пишет файл состояния; её нагрузка снята дословно.
    """
    path = Path(root) / OWNER_CHANNEL_REL
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"commands": [], "doors": [],
                "unchecked": f"канал владельца не разобран ({path}): "
                             f"{type(exc).__name__}: {exc}"}

    state_files = _module_state_files(tree)
    commands: list[str] = []
    doors: list[dict] = []

    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        # Карта «команда → метод»: словарь, чьи ключи — команды, а значения —
        # `self.<метод>`. Форма вызова, а не имя переменной: переименование
        # `handlers` не должно ослеплять замер.
        #
        # ЭТА КАРТА И ЕСТЬ ПЕРЕЧЕНЬ (ADR-712). До 13.10 перечень брался из
        # отдельного кортежа `_COMMANDS`, а карта читалась только ради имени
        # метода — то есть одно и то же множество снималось ДВАЖДЫ, и второй
        # раз с копии, которую в боте не читал никто. Копия снята; множества
        # были равны, поэтому ни один вердикт от поправки не изменился.
        handlers: dict[str, str] = {}
        for node in ast.walk(cls):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if (isinstance(key, ast.Constant) and isinstance(key.value, str)
                        and key.value.startswith("/") and len(key.value) > 1
                        and isinstance(value, ast.Attribute)):
                    handlers[key.value] = value.attr
        if not handlers:
            continue
        published = sorted(handlers)
        commands.extend(published)

        methods = {f.name: f for f in cls.body if isinstance(f, ast.FunctionDef)}
        for command in published:
            fn = methods.get(handlers.get(command, ""))
            if fn is None:
                continue
            for call in [c for c in ast.walk(fn) if isinstance(c, ast.Call)]:
                fname = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
                if fname != "_atomic_write_json" or not call.args:
                    continue
                var = getattr(call.args[0], "id", None)
                filename = state_files.get(var or "")
                if not filename:
                    continue
                payload, dropped = _literal_payload(
                    call.args[1] if len(call.args) > 1 else ast.Constant(None))
                doors.append({
                    "command": command,
                    "handler": fn.name,
                    "state_file": filename,
                    "payload": payload,
                    "payload_keys_not_literal": dropped,
                })
    return {"commands": commands, "doors": doors, "unchecked": None}


# ──────────────────────────── сцена пути решения ────────────────────────────

def _scene() -> dict:
    """Здоровая книга: развёрнуто больше половины капитала в двух пулах.

    Ни одна доля здесь ничего не решает — проба смотрит на ПЕРЕХОД (было
    развёрнуто → стало иначе), а не на конкретное число.
    """
    cap = _SCENE_CAPITAL_USD
    return {
        "capital_usd": cap,
        "held": {"aave_v3": 0.40 * cap, "pendle": 0.20 * cap},
        "target": {"aave_v3": 0.40 * cap, "pendle": 0.20 * cap},
    }


def _apply_doors(state_dir: Path, scene: dict) -> dict:
    """Настоящий путь решения над подставленным каталогом состояния.

    Зовутся те самые функции, которыми живой дневной цикл решает о книге:
    ``run_kill_switch_check`` (читает файл двери) и обе ступени
    ``cycle_gates``. Каталог передаётся явно — живой ``data/`` не участвует.
    """
    from spa_core.governance.kill_switch import run_kill_switch_check, run_derisk_check
    from spa_core.paper_trading.cycle_gates import (
        apply_kill_switch_override,
        apply_soft_derisk_gate,
    )

    kill = run_kill_switch_check(equity_curve=[], data_dir=state_dir)
    derisk = run_derisk_check(equity_curve=[], data_dir=state_dir)
    notes: list[str] = []
    target = dict(scene["target"])
    target = apply_kill_switch_override(
        target,
        ks_triggered=bool(kill.get("triggered")),
        ks_allocation=dict(kill.get("allocation") or {}),
        capital_usd=scene["capital_usd"],
        notes=notes,
    )
    target = apply_soft_derisk_gate(
        target,
        current_positions=dict(scene["held"]),
        derisk_active=bool(derisk.get("triggered")),
        notes=notes,
    )
    return {
        "triggered": bool(kill.get("triggered")),
        "reason": str(kill.get("reason") or ""),
        "target": target,
        "notes": notes,
    }


def _classify_effect(scene: dict, outcome: dict) -> str:
    """Эффект двери на книгу — по ДЕНЬГАМ, а не по записке в ``notes``.

    Развёрнутая сумма считается по объединению ключей: отсутствие ключа в цели
    эквивалентно нулю (это измерено отдельно, см. docstring модуля), поэтому
    судить надо по сумме, а не по составу словаря.
    """
    held = scene["held"]
    target = outcome["target"]
    deployed_before = sum(float(v) for v in held.values())
    deployed_after = sum(
        float(target.get(k, 0.0)) for k in set(held) | set(target))
    if deployed_after <= 0.01:
        return EFFECT_ALL_CASH
    if abs(deployed_after - deployed_before) <= 0.01:
        # Книга цела. «Новое закрыто» отличается от «ничего не произошло» тем,
        # что путь решения вообще что-то сказал.
        return EFFECT_HOLD_ONLY if outcome["notes"] else EFFECT_NO_EFFECT
    return EFFECT_HOLD_ONLY


def _measure_door(door: dict, scene: dict) -> dict:
    """Эффект ОДНОЙ двери: нагрузка подставляется во временный каталог."""
    with tempfile.TemporaryDirectory(prefix="cio_ks_") as tmp:
        state_dir = Path(tmp)
        (state_dir / door["state_file"]).write_text(
            json.dumps(door["payload"], ensure_ascii=False), encoding="utf-8")
        outcome = _apply_doors(state_dir, scene)
    return {
        "command": door["command"],
        "state_file": door["state_file"],
        "payload": door["payload"],
        "triggered": outcome["triggered"],
        "reason": outcome["reason"],
        "effect": _classify_effect(scene, outcome),
        "target_after": {k: round(float(v), 2) for k, v in outcome["target"].items()},
        "notes": outcome["notes"],
    }


def _healthy_effect(scene: dict) -> dict:
    """Положительный контроль №1: без двери капитал остаётся развёрнутым."""
    with tempfile.TemporaryDirectory(prefix="cio_ks_ok_") as tmp:
        outcome = _apply_doors(Path(tmp), scene)
    return {
        "triggered": outcome["triggered"],
        "reason": outcome["reason"],
        "effect": _classify_effect(scene, outcome),
        "target_after": {k: round(float(v), 2) for k, v in outcome["target"].items()},
    }


# ───────────────── продолжает ли CIO РЕШАТЬ при взведённой двери ────────────

def _decision_still_runs(door: dict, scene: dict) -> dict:
    """Останавливает ли дверь сам CIO — или только переписывает его ответ.

    Зовётся настоящий гейт допустимости. Если при взведённой двери он
    по-прежнему одобряет цель, значит «PAUSE CIO» не состоялся: слой решения
    отработал полностью, а его вывод затёрли ступенью ниже.
    """
    from spa_core.paper_trading.risk_gate import _apply_risk_policy_gate
    from spa_core.risk.policy import RiskConfig

    cfg = RiskConfig()
    floor = float(cfg.min_tvl_usd)
    adapters = [
        {"protocol": "aave_v3", "apy_pct": 2.7, "tvl_usd": floor * 180.0,
         "tier": "T1", "apy_source": "live", "tvl_source": "live"},
        {"protocol": "pendle", "apy_pct": 9.0, "tvl_usd": floor * 16.0,
         "tier": "T2", "apy_source": "live", "tvl_source": "live"},
    ]
    with tempfile.TemporaryDirectory(prefix="cio_ks_dec_") as tmp:
        state_dir = Path(tmp)
        (state_dir / door["state_file"]).write_text(
            json.dumps(door["payload"], ensure_ascii=False), encoding="utf-8")
        gate = _apply_risk_policy_gate(
            dict(scene["target"]), scene["capital_usd"], adapters,
            ddir=state_dir, current_positions=dict(scene["held"]),
        )
    approved = bool(gate.get("approved")) and gate.get("error") is None
    target_out = observed(gate, "target_usd", kind=dict)
    if target_out is None:
        # Ноль предложенного — это вердикт «гейт не пустил ни доллара»; на ответе
        # БЕЗ цели он был бы подстановкой, а не замером (инвариант #17).
        return {"approved": approved, "proposed_usd": None,
                "unmeasured": "гейт не вернул target_usd"}
    proposed = sum(float(v) for v in target_out.values())
    return {"approved": approved, "proposed_usd": round(proposed, 2)}


# ──────────────────────── переживают ли наблюдение и отчёт ──────────────────

def _seed_scene(state_dir: Path, now: dt.datetime) -> None:
    """Герметичная сцена состояния для наблюдающих и отчитывающихся.

    Собирается из литералов, а НЕ копируется из живого ``data/``: иначе вердикт
    отвечал бы на вопрос о сегодняшнем хосте, а не о двери. Числа здесь ничего
    не решают — сравниваются два прогона над ОДНОЙ сценой.

    Отметка снимка берётся от ПЕРЕДАННОГО ``now``, а не вшита литералом: сцена
    с литеральной датой протухала бы сама собой. Свежесть при этом судит
    канонический читатель по СВОИМ часам, поэтому при замороженном ``now``
    снимок честно окажется протухшим — и это пробе не мешает: сравниваются два
    прогона над ОДНОЙ сценой, а протухание одинаково в обоих.
    """
    (state_dir / "agent_health.json").write_text(json.dumps({
        "timestamp": now.isoformat(),
        "overall_status": "OK",
        "agents": [],
        "critical_count": 0,
    }), encoding="utf-8")
    (state_dir / "current_positions.json").write_text(json.dumps({
        "capital_usd": _SCENE_CAPITAL_USD,
        "cash_usd": 0.40 * _SCENE_CAPITAL_USD,
        "deployed_usd": 0.60 * _SCENE_CAPITAL_USD,
        "positions": {"aave_v3": 0.40 * _SCENE_CAPITAL_USD,
                      "pendle": 0.20 * _SCENE_CAPITAL_USD},
    }), encoding="utf-8")
    # `evidence_level: "L5"` отсюда УБРАН (2026-09-10). Поле не читал никто — ни этот
    # модуль, ни настоящий писатель кривой его не пишет вовсе, — а линтер дерева
    # (`spa_core/tests/test_evidence_level_claims.py`) запрещает заявку L4+ где бы то ни
    # было: L4 по канону означает исполнение РЕАЛЬНЫМ капиталом, которого не было ни разу.
    # Два красных теста держались на украшении в синтетической сцене.
    (state_dir / "equity_curve_daily.json").write_text(json.dumps({"daily": [
        {"date": "2026-01-01", "close_equity": _SCENE_CAPITAL_USD},
        {"date": "2026-01-02", "close_equity": _SCENE_CAPITAL_USD * 1.005},
    ]}), encoding="utf-8")
    (state_dir / "adapter_orchestrator_status.json").write_text(json.dumps({
        "adapters": [
            {"protocol": "aave_v3", "apy_pct": 2.7, "tier": "T1"},
            {"protocol": "pendle", "apy_pct": 9.0, "tier": "T2"},
        ]}), encoding="utf-8")


def _probe_monitoring(state_dir: Path) -> str:
    from spa_core.monitoring.portfolio_health import run_health_check
    report = run_health_check(data_dir=state_dir)
    return (f"summary_level={report.get('summary_level')} "
            f"overall_score={report.get('overall_score')}")


def _probe_reporting(state_dir: Path) -> str:
    from spa_core.reporting.daily_telegram_report import build_report_data
    report = build_report_data(data_dir=state_dir)
    return f"fields={len(report)} equity_usd={report.get('equity_usd')}"


def _probe_owner_warnings(state_dir: Path) -> str:
    """Owner-facing экран предупреждений: НАЗЫВАЕТ ли он взведённую дверь.

    Каталог у этого экрана — модульная константа, поэтому подменяется на время
    пробы и возвращается в ``finally``. Экран только читает; путь решения через
    него не идёт.
    """
    from spa_core.telegram.views import _base as base
    previous = base.DATA_DIR
    base.DATA_DIR = state_dir
    try:
        from spa_core.telegram.views import warnings as warnings_view
        keys = sorted(str(w.get("key")) for w in warnings_view._active_warnings())
        return f"warnings={keys}"
    finally:
        base.DATA_DIR = previous


_SEPARABILITY_PROBES: tuple[tuple[str, str, Any], ...] = (
    ("portfolio_health", "monitoring", _probe_monitoring),
    ("daily_telegram_report", "reporting", _probe_reporting),
    ("telegram_warnings_view", "reporting", _probe_owner_warnings),
)


def _separability(door: dict, now: dt.datetime) -> dict:
    """Гасит ли дверь наблюдение и отчёт — прогоном настоящих производителей.

    Каждый производитель зовётся ДВАЖДЫ над одной и той же сценой: без двери и
    с ней. Исход ``PRODUCES`` = произвёл в обоих прогонах; ``STOPS`` = перестал
    производить при взведённой двери.
    """
    probes: list[dict] = []
    for name, layer, fn in _SEPARABILITY_PROBES:
        record: dict[str, Any] = {"probe": name, "layer": layer}
        results: dict[str, str | None] = {}
        for label, armed in (("without_door", False), ("with_door", True)):
            with tempfile.TemporaryDirectory(prefix="cio_ks_sep_") as tmp:
                state_dir = Path(tmp)
                _seed_scene(state_dir, now)
                if armed:
                    (state_dir / door["state_file"]).write_text(
                        json.dumps(door["payload"], ensure_ascii=False),
                        encoding="utf-8")
                try:
                    results[label] = fn(state_dir)
                except Exception as exc:  # noqa: BLE001 — упавшая проба это UNCHECKED
                    results[label] = None
                    record["unchecked_reason"] = (
                        f"{label}: {type(exc).__name__}: {exc}")
        record.update(results)
        if results["without_door"] is None:
            record["outcome"] = UNCHECKED
        elif results["with_door"] is None:
            record["outcome"] = "STOPS"
        else:
            record["outcome"] = "PRODUCES"
        record["output_identical"] = results["without_door"] == results["with_door"]
        probes.append(record)

    stopped = [p for p in probes if p["outcome"] == "STOPS"]
    unmeasured = [p for p in probes if p["outcome"] == UNCHECKED]
    # «Наблюдение пережило дверь» и «наблюдение О ДВЕРИ СКАЗАЛО» — разные
    # утверждения, и второе меряется, а не заявляется: производитель называет
    # взведённую дверь, если его вывод при ней ОТЛИЧАЕТСЯ. Молчаливое
    # выживание — тоже выживание, но владельцу от него пользы меньше.
    names_door = [p["probe"] for p in probes
                  if p["outcome"] == "PRODUCES" and not p["output_identical"]]
    if unmeasured and not stopped:
        verdict, reason = UNCHECKED, (
            "не измерено: " + "; ".join(
                f"{p['probe']} — {p.get('unchecked_reason')}" for p in unmeasured))
    elif stopped:
        verdict, reason = "NOT_SEPARABLE", (
            "дверь гасит: " + ", ".join(f"{p['probe']} ({p['layer']})"
                                        for p in stopped))
    else:
        verdict, reason = "SEPARABLE", (
            f"все {len(probes)} производителя наблюдения и отчёта продолжают "
            f"производить при взведённой двери")
    return {"verdict": verdict, "reason": reason, "probes": probes,
            "producers_naming_the_door": names_door}


# ───────────── аварийный выход под тримом (ADR-850 · ADR-988) ───────────────

def _scene_adapters() -> list[dict]:
    """Фид сцены для переспроса RiskPolicy: живые TVL выше пола, тиры T1/T2."""
    from spa_core.risk.policy import RiskConfig
    floor = float(RiskConfig().min_tvl_usd)
    return [
        {"protocol": "aave_v3", "apy_pct": 2.7, "tvl_usd": floor * 180.0,
         "tier": "T1", "apy_source": "live", "tvl_source": "live"},
        {"protocol": "compound_v3", "apy_pct": 3.1, "tvl_usd": floor * 120.0,
         "tier": "T1", "apy_source": "live", "tvl_source": "live"},
        {"protocol": "pendle", "apy_pct": 9.0, "tvl_usd": floor * 16.0,
         "tier": "T2", "apy_source": "live", "tvl_source": "live"},
    ]


def _run_trim(target: dict, scene: dict, state_dir: Path, now: dt.datetime,
              trim: Any) -> tuple[dict, dict]:
    """Один зов настоящего Step 2e'' над книгой сцены: ``(цель после, запись)``."""
    notes: list[str] = []
    final, record = trim(
        dict(target),
        current_positions=dict(scene["held"]),
        capital_usd=scene["capital_usd"],
        notes=notes,
        adapters=_scene_adapters(),
        ddir=state_dir,
        trades=[],
        now=now,
    )
    if not isinstance(record, dict):
        record = {"verdict": EFFECT_UNMEASURED, "why": "запись трима не словарь"}
    return dict(final), record


def _trim_under_door(door: dict, scene: dict, now: dt.datetime, *,
                     trim: Any = None) -> dict:
    """Дозирует ли урезание хода (Step 2e'', ADR-850) аварийный выход.

    Порядок тот же, что у живого цикла: стоп-кран переписывает цель (Step 2c),
    затем ТОТ ЖЕ трим, что судит перетасовки, получает эту книгу. Три исхода:

    ``EXEMPT`` — цель после трима равна цели после крана (все позиции в ноль),
    и запись трима НАЗЫВАЕТ причину (``NOT_A_RESHUFFLE`` от двери демпфера);
    ``DOSED`` — трим изменил книгу: выход растянут на несколько циклов;
    ``UNCHECKED`` — трим не ответил, либо положительный контроль не пройден.

    Положительный контроль — перетасовка той же сцены ТЕМ ЖЕ тримом урезается
    (``TRIMMED_TO_ADMISSIBLE``, k < 1). Без него «выход не урезан» было бы
    верно и для трима, который не урезает ничего.
    """
    if trim is None:
        from spa_core.paper_trading.admissible_trim import apply_admissible_trim as trim
    out: dict[str, Any] = {"verdict": UNCHECKED, "door": door.get("command"),
                           "adr": "ADR-850", "control": {}}
    try:
        with tempfile.TemporaryDirectory(prefix="cio_ks_trim_") as tmp:
            state_dir = Path(tmp)
            (state_dir / door["state_file"]).write_text(
                json.dumps(door["payload"], ensure_ascii=False), encoding="utf-8")
            after_door = _apply_doors(state_dir, scene)
            exit_target = dict(after_door["target"])
            exit_final, exit_rec = _run_trim(exit_target, scene, state_dir, now, trim)

            # Контроль: перетасовка ровно тех же денег в ту же сцену. Оборот
            # выводится из капитала сцены и заведомо больше любого потолка
            # размера, которым трим урезает (иначе контроль мерил бы потолок,
            # а не трим).
            cap = scene["capital_usd"]
            reshuffle = {"aave_v3": 0.20 * cap, "pendle": 0.20 * cap,
                         "compound_v3": 0.20 * cap}
            ctl_final, ctl_rec = _run_trim(reshuffle, scene, Path(tmp), now, trim)
    except Exception as exc:  # noqa: BLE001 — трим не ответил ⇒ не измерено
        out["unchecked_reason"] = f"трим не ответил: {type(exc).__name__}: {exc}"
        return out

    k = ctl_rec.get("k")
    control_ok = (ctl_rec.get("verdict") == "TRIMMED_TO_ADMISSIBLE"
                  and isinstance(k, (int, float)) and 0.0 < float(k) < 1.0)
    out["control"] = {
        "passed": bool(control_ok),
        "reshuffle_verdict": ctl_rec.get("verdict"),
        "k": k,
        "why": ctl_rec.get("why"),
    }
    out["exit_target_after_door"] = {p: round(float(v), 2) for p, v in exit_target.items()}
    out["exit_target_after_trim"] = {p: round(float(v), 2) for p, v in exit_final.items()}
    out["exit_trim_verdict"] = exit_rec.get("verdict")
    out["exit_damper_reason"] = exit_rec.get("damper_reason")
    out["exit_why"] = exit_rec.get("why")
    if not control_ok:
        out["unchecked_reason"] = (
            "положительный контроль не пройден: перетасовка той же сцены тримом "
            f"не урезана ({ctl_rec.get('verdict')}, k={k!r}) — «выход не урезан» "
            "доказать нечем")
        return out

    deployed_door = sum(float(v) for v in exit_target.values())
    deployed_trim = sum(float(exit_final.get(p, 0.0)) for p in set(exit_target) | set(exit_final))
    if abs(deployed_trim - deployed_door) > 0.01:
        out["verdict"] = TRIM_DOSED
        out["detail"] = (
            f"трим изменил книгу после стоп-крана: развёрнуто ${deployed_door:,.2f} → "
            f"${deployed_trim:,.2f} (вердикт трима {exit_rec.get('verdict')}, "
            f"k={exit_rec.get('k')!r}) — аварийный выход растянут на несколько циклов")
        return out
    if exit_rec.get("verdict") != "NOT_A_RESHUFFLE":
        # Книга цела, но причина НЕ названа дверью демпфера: «не тронул, потому
        # что не смог» и «не тронул, потому что это де-риск» — разные миры.
        out["unchecked_reason"] = (
            f"книга после трима равна книге после крана, но причина не названа "
            f"родом хода (вердикт трима {exit_rec.get('verdict')!r}): освобождение "
            f"не доказано дверью")
        return out
    out["verdict"] = TRIM_EXEMPT
    out["detail"] = (
        f"аварийный выход трим не дозирует: род хода `{exit_rec.get('damper_reason')}` "
        f"(дверь демпфера ADR-168) выводит его из предмета урезания; книга после "
        f"крана и после трима одна (${deployed_door:,.2f} развёрнуто)")
    return out


# ──────── кандидат органа PAUSE AUTO EXECUTION — взвод CIO (ADR-324) ────────

def _arming_declaration(root: str) -> dict:
    """Где живёт состояние взвода: разбор ``cio_arming.py`` деревом.

    Возвращает ``books`` (ключи литерала ``ARMED_BOOKS``), ``state_lives_in``
    (``code_constant`` — литерал словаря в модуле; иначе ``not_a_literal``) и
    ``reads_at_runtime`` — зовёт ли модуль хоть одну дверь к файлу/окружению
    (``open`` · ``_read_json`` · ``Path(...)`` · ``os.environ``): если нет, то и
    снять взвод снаружи нечем — только доставкой кода.
    """
    path = Path(root) / ARMING_REL
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"unchecked": f"файл взвода не разобран ({path}): "
                             f"{type(exc).__name__}: {exc}"}
    books: list[str] = []
    lives_in = "absent"
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        for t in targets:
            if isinstance(t, ast.Name) and t.id == "ARMED_BOOKS":
                if isinstance(value, ast.Dict):
                    lives_in = "code_constant"
                    books = sorted(k.value for k in value.keys
                                   if isinstance(k, ast.Constant)
                                   and isinstance(k.value, str))
                else:
                    lives_in = "not_a_literal"
    runtime_doors: list[str] = []
    for call in [n for n in ast.walk(tree) if isinstance(n, ast.Call)]:
        fname = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
        if fname in ("open", "_read_json", "read_text", "load", "loads", "getenv", "environ"):
            runtime_doors.append(fname)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and node.attr == "environ"):
            runtime_doors.append("os.environ")
    return {"unchecked": None, "books": books, "state_lives_in": lives_in,
            "reads_at_runtime": sorted(set(runtime_doors))}


def _pause_auto_execution_candidate(root: str, scene: dict, channel: dict, *,
                                    trade_allowed: Any = None) -> dict:
    """Является ли снятие взвода CIO органом «PAUSE AUTO EXECUTION».

    Орган владельца обещает ``HOLD_ONLY``: «CIO продолжает предлагать, но
    предложенное не исполняется само». Единственный переключатель дерева с
    похожим именем — взвод (ADR-324/328). Три вопроса, все измерением:

    1. где состояние — разбор дерева (``_arming_declaration``);
    2. пишет ли туда дверь владельца — ни одна дверь канала не пишет файл,
       который этот модуль читал бы (он не читает файлов вовсе);
    3. что сделал бы СНЯТЫЙ взвод — настоящий ``trade_allowed`` над
       перетасовкой сцены для невзведённой книги: ``UNARMED`` + ход пропущен
       ⇒ ``NOT_THE_ORGAN``; ход удержан ⇒ ``WOULD_HOLD``.
    """
    if trade_allowed is None:
        from spa_core.paper_trading.cio_arming import trade_allowed
    decl = _arming_declaration(root)
    out: dict[str, Any] = {"candidate": "cio_arming.ARMED_BOOKS", "adr": "ADR-324/328",
                           "verdict": UNCHECKED, "declaration": decl}
    if decl.get("unchecked"):
        out["unchecked_reason"] = decl["unchecked"]
        return out

    # Дверь владельца к взводу: файл, который взвод читает, и который пишет
    # хоть одна дверь канала. Взвод файлов не читает ⇒ пересечение пусто
    # ПО ПОСТРОЕНИЮ, и это печатается, а не подразумевается.
    door_files = sorted({str(d.get("state_file")) for d in channel.get("doors", [])})
    out["owner_door"] = None
    out["owner_channel_state_files"] = door_files
    out["arming_runtime_doors"] = decl.get("reads_at_runtime")

    cap = scene["capital_usd"]
    reshuffle = {"aave_v3": 0.20 * cap, "pendle": 0.20 * cap, "compound_v3": 0.20 * cap}
    books_obs = decl.get("books")
    books = list(books_obs) if isinstance(books_obs, list) else []
    unarmed_book = "scene_book_not_armed"
    try:
        armed_probe = None
        if books:
            armed_probe = trade_allowed(books[0], None, dict(scene["held"]),
                                        dict(reshuffle), damper_reason="within_limits")
        unarmed_probe = trade_allowed(unarmed_book, None, dict(scene["held"]),
                                      dict(reshuffle), damper_reason="within_limits")
    except Exception as exc:  # noqa: BLE001
        out["unchecked_reason"] = f"дверь взвода не ответила: {type(exc).__name__}: {exc}"
        return out

    def _rec(p: Any) -> dict | None:
        if not (isinstance(p, tuple) and len(p) == 3):
            return None
        return {"allowed": bool(p[0]), "decision": str(p[1]), "why": str(p[2])}

    out["armed_book_reshuffle"] = _rec(armed_probe) if armed_probe is not None else None
    unarmed = _rec(unarmed_probe)
    out["unarmed_book_reshuffle"] = unarmed
    if unarmed is None:
        out["unchecked_reason"] = "ответ двери взвода не разобран"
        return out
    if unarmed["allowed"]:
        out["verdict"] = CANDIDATE_NOT_THE_ORGAN
        out["detail"] = (
            f"снятый взвод не держит книгу: невзведённая книга отвечает "
            f"`{unarmed['decision']}` и перетасовку ПРОПУСКАЕТ (решает прежнее "
            f"правило цикла, ADR-168) — это не HOLD_ONLY; состояние взвода — "
            f"{decl['state_lives_in']} ({len(books)} книг(и): {', '.join(books) or '—'}), "
            f"двери владельца к нему нет")
    else:
        out["verdict"] = CANDIDATE_WOULD_HOLD
        out["detail"] = (
            f"снятый взвод держит книгу (`{unarmed['decision']}`) — кандидат годен "
            f"как орган, но двери владельца к нему нет: состояние — {decl['state_lives_in']}")
    return out


# ───────────────────────────── сборка вердикта ──────────────────────────────

def _door_text(door: dict) -> str:
    """Всё, что владелец видит об этой двери: команда, обработчик, её текст."""
    parts = [str(door.get("command") or ""), str(door.get("handler") or "")]
    parts += [str(v) for v in (door.get("payload") or {}).values()
              if isinstance(v, str)]
    return " ".join(parts).lower()


def _control_outcome(promised: str, claim_words: tuple[str, ...],
                     doors_measured: list[dict]) -> tuple[str, dict | None, str]:
    """Исход ОДНОГО названного владельцем органа.

    Порядок вопросов важен и он такой: сначала «есть ли дверь с ЭТИМ эффектом»
    (измерение), и только если нет — «есть ли дверь, ПРЕТЕНДУЮЩАЯ на этот орган
    именем» (тоже измерение, по тексту, который видит владелец).

    Разделение не косметическое. `ABSENT` — «ручки нет, владелец это заметит».
    `CONFLATED` — «ручка есть, подписана этим именем, а делает другое»: владелец
    её нажмёт, ожидая обещанного. Второе опаснее первого, и слить их в отчёте о
    стоп-кранах значит потерять именно опасную половину.
    """
    for measured in doors_measured:
        if measured["effect"] == promised:
            return PRESENT, measured, ""
    for measured in doors_measured:
        if measured["effect"] in (EFFECT_NO_EFFECT, EFFECT_UNMEASURED):
            continue
        text = _door_text(measured)
        if all(word in text for word in claim_words):
            return CONFLATED, measured, (
                f"дверь `{measured['command']}` носит это имя, но её измеренный "
                f"эффект — {measured['effect']}, а не {promised}")
    return ABSENT, None, (
        "ни одна опубликованная владельцу команда не даёт этого эффекта и ни "
        "одна не носит этого имени")


def run(root: str = REPO_ROOT, *, write: bool = True,
        now: dt.datetime | None = None) -> dict:
    """Замер §42. Живой ``data/`` не читается и не пишется (кроме отчёта)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    scene = _scene()

    channel = _owner_doors(root)
    healthy: dict[str, Any] = {}
    doors_measured: list[dict] = []
    decision: dict[str, Any] = {}
    separability: dict[str, Any] = {
        "verdict": UNCHECKED, "reason": "двери не измерены", "probes": []}
    trim_axis: dict[str, Any] = {
        "verdict": UNCHECKED, "door": None,
        "unchecked_reason": "двери не измерены — выход под тримом судить нечем"}
    candidate: dict[str, Any] = {"candidate": "cio_arming.ARMED_BOOKS", "verdict": UNCHECKED}
    control_ok = False
    control_reason = channel.get("unchecked") or ""

    if not control_reason:
        try:
            healthy = _healthy_effect(scene)
        except Exception as exc:  # noqa: BLE001
            control_reason = (f"здоровая сцена не установлена: "
                              f"{type(exc).__name__}: {exc}")

    if not control_reason and healthy.get("effect") != EFFECT_NO_EFFECT:
        control_reason = (
            f"на здоровой сцене путь решения уже не оставляет книгу в покое "
            f"(эффект {healthy.get('effect')}) — переход после двери показать нечем")

    if not control_reason:
        for door in channel["doors"]:
            try:
                doors_measured.append(_measure_door(door, scene))
            except Exception as exc:  # noqa: BLE001
                doors_measured.append({
                    "command": door["command"], "state_file": door["state_file"],
                    "payload": door["payload"], "effect": EFFECT_UNMEASURED,
                    "reason": f"{type(exc).__name__}: {exc}",
                    "target_after": {}, "notes": [],
                })
        acting = [d for d in doors_measured
                  if d["effect"] not in (EFFECT_NO_EFFECT, EFFECT_UNMEASURED)]
        if not acting:
            control_reason = (
                "ни одна опубликованная владельцу дверь не изменила путь решения — "
                "утверждать, что наблюдение «пережило остановку», нечем")
        else:
            control_ok = True
            strongest = acting[0]
            try:
                decision = _decision_still_runs(strongest, scene)
            except Exception as exc:  # noqa: BLE001
                decision = {"unchecked_reason": f"{type(exc).__name__}: {exc}"}
            separability = _separability(strongest, now)
            try:
                trim_axis = _trim_under_door(strongest, scene, now)
            except Exception as exc:  # noqa: BLE001
                trim_axis = {"verdict": UNCHECKED, "door": strongest.get("command"),
                             "unchecked_reason": f"{type(exc).__name__}: {exc}"}

    try:
        candidate = _pause_auto_execution_candidate(root, scene, channel)
    except Exception as exc:  # noqa: BLE001
        candidate = {"candidate": "cio_arming.ARMED_BOOKS", "verdict": UNCHECKED,
                     "unchecked_reason": f"{type(exc).__name__}: {exc}"}

    controls: list[dict] = []
    for key, wording, promise, promised_effect, source, claim_words in OWNER_CONTROLS:
        base = {
            "control": key, "owner_wording": wording, "promise": promise,
            "promised_effect": promised_effect, "promise_source": source,
            "claim_words": list(claim_words),
        }
        if not control_ok:
            controls.append({**base, "outcome": UNCHECKED, "door": None,
                             "measured_effect": EFFECT_UNMEASURED, "detail": "",
                             "unchecked_reason": control_reason})
            continue
        outcome, door, detail = _control_outcome(
            promised_effect, claim_words, doors_measured)
        controls.append({**base, "outcome": outcome,
                         "door": door["command"] if door else None,
                         "measured_effect": door["effect"] if door
                                            else EFFECT_UNMEASURED,
                         "detail": detail, "unchecked_reason": ""})

    findings, unchecked = _findings(
        controls, channel, decision, separability, control_ok, control_reason,
        trim_axis=trim_axis, candidate=candidate)
    counts = {
        "critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
        "warn": sum(1 for f in findings if f["severity"] == "WARN"),
        "info": sum(1 for f in findings if f["severity"] == "INFO"),
        "unchecked": len(unchecked),
    }
    overall = ("UNCHECKED" if not control_ok
               else "CRITICAL" if counts["critical"]
               else "WARN" if counts["warn"]
               else "UNCHECKED" if counts["unchecked"]
               else "OK")
    tally = {o: sum(1 for c in controls if c["outcome"] == o)
             for o in (PRESENT, CONFLATED, ABSENT, UNCHECKED)}

    doc = {
        "generated_at": now.isoformat(),
        "overall": overall,
        "counts": counts,
        "owner_criterion": (
            "§42 ТЗ «Portfolio CIO»: обязательны PAUSE CIO · PAUSE AUTO "
            "EXECUTION · EMERGENCY STOP; владелец должен иметь возможность "
            "остановить execution без остановки monitoring/reporting"),
        "controls_total": len(OWNER_CONTROLS),
        "tally": tally,
        "control": {"passed": control_ok, "reason": control_reason,
                    "healthy_scene": healthy},
        "owner_channel": {
            "source": OWNER_CHANNEL_REL,
            # ADR-712: имя названо по ТОМУ, что измерено. «Опубликовано»
            # означало бы нагрузку `setMyCommands` (меню ☰, 16 команд), а
            # здесь перечень кнопочной поверхности — карта `_dispatch`.
            "commands_on_the_button_surface": channel["commands"],
            "doors": [{"command": d["command"], "state_file": d["state_file"],
                       "payload": d["payload"],
                       "payload_keys_not_literal": d["payload_keys_not_literal"]}
                      for d in channel["doors"]],
        },
        "doors_measured": doors_measured,
        "controls": controls,
        "decision_layer_under_door": decision,
        "separability": separability,
        "trim_under_door": trim_axis,
        "pause_auto_execution_candidate": candidate,
        "findings": findings,
        "unchecked": unchecked,
        "advisory": (
            "ADVISORY: ни один орган остановки этим модулем не строится и не "
            "двигается — дать владельцу ручку, которая меняет движение денег, "
            "это money-path и решение владельца"),
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, os.path.join(root, REPORT_REL))
    return doc


def _findings(controls: list[dict], channel: dict,
              decision: dict, separability: dict,
              control_ok: bool, control_reason: str, *,
              trim_axis: dict | None = None,
              candidate: dict | None = None) -> tuple[list[dict], list[str]]:
    findings: list[dict] = []
    unchecked: list[str] = []

    if not control_ok:
        unchecked.append(
            f"положительный контроль не пройден — {control_reason}; счёт по "
            f"органам остановки читать нельзя")
        return findings, unchecked

    # ── ось ADR-988 №1: аварийный выход под тримом ADR-850 ──────────────────
    if isinstance(trim_axis, dict):
        tv = trim_axis.get("verdict")
        if tv == TRIM_DOSED:
            findings.append({
                "severity": "CRITICAL",
                "code": "emergency_exit_dosed_by_trim",
                "message": (
                    f"аварийный выход ДОЗИРУЕТСЯ урезанием хода (Step 2e'', ADR-850): "
                    f"{trim_axis.get('detail')} — «EMERGENCY STOP» перестаёт быть "
                    f"all-cash за один цикл, и орган подменён размером"),
            })
        elif tv == TRIM_EXEMPT:
            findings.append({
                "severity": "INFO",
                "code": "emergency_exit_survives_trim",
                "message": (
                    f"четвёртая поверхность решения выход не трогает: "
                    f"{trim_axis.get('detail')}; контроль — перетасовка той же сцены "
                    f"урезана (k={(trim_axis.get('control') if isinstance(trim_axis.get('control'), dict) else {}).get('k')})"),
            })
        else:
            unchecked.append(
                f"аварийный выход под тримом: "
                f"{trim_axis.get('unchecked_reason') or 'причина не названа'}")

    # ── ось ADR-988 №2: кандидат органа PAUSE AUTO EXECUTION ─────────────────
    if isinstance(candidate, dict):
        cv = candidate.get("verdict")
        if cv == CANDIDATE_NOT_THE_ORGAN:
            findings.append({
                "severity": "WARN",
                "code": "pause_auto_execution_candidate_is_not_the_organ",
                "message": (
                    f"единственный переключатель дерева с похожим именем — взвод CIO "
                    f"({candidate.get('candidate')}, {candidate.get('adr')}) — органом "
                    f"«PAUSE AUTO EXECUTION» не является: {candidate.get('detail')}"),
            })
        elif cv == CANDIDATE_WOULD_HOLD:
            findings.append({
                "severity": "WARN",
                "code": "pause_auto_execution_candidate_has_no_owner_door",
                "message": (
                    f"взвод CIO ({candidate.get('candidate')}) держал бы книгу, но двери "
                    f"владельца к нему нет: {candidate.get('detail')}"),
            })
        else:
            unchecked.append(
                f"кандидат органа PAUSE AUTO EXECUTION: "
                f"{candidate.get('unchecked_reason') or 'причина не названа'}")

    absent = [c for c in controls if c["outcome"] == ABSENT]
    conflated = [c for c in controls if c["outcome"] == CONFLATED]
    present = [c for c in controls if c["outcome"] == PRESENT]

    for c in conflated:
        findings.append({
            "severity": "CRITICAL",
            "code": f"conflated:{c['control']}",
            "message": (
                f"орган «{c['owner_wording']}»: {c['detail']}. Ожидаемый эффект "
                f"взят не отсюда, а у {c['promise_source']}. Владелец нажимает "
                f"кнопку с этим именем и получает другое последствие"),
        })
    for c in absent:
        findings.append({
            "severity": "WARN",
            "code": f"absent:{c['control']}",
            "message": (
                f"органа «{c['owner_wording']}» у владельца нет: {c['detail']} "
                f"(ожидался эффект {c['promised_effect']} по {c['promise_source']})"),
        })

    if absent or conflated:
        findings.append({
            "severity": "CRITICAL" if conflated else "WARN",
            "code": "coverage",
            "message": (
                f"из {len(OWNER_CONTROLS)} названных владельцем органов остановки "
                f"есть {len(present)}; подменены другим эффектом {len(conflated)}; "
                f"отсутствуют {len(absent)}. Всего команд на КНОПОЧНОЙ "
                f"поверхности (карта `_dispatch`) {len(channel['commands'])}, "
                f"из них пишут состояние {len(channel['doors'])}"),
        })

    if decision.get("approved"):
        findings.append({
            "severity": "WARN",
            "code": "decision_layer_not_paused",
            "message": (
                f"при взведённой двери слой решения продолжает работать: гейт "
                f"допустимости по-прежнему одобряет цель на "
                f"${decision.get('proposed_usd')}, и её затирает ступень ниже. "
                f"«Остановить CIO» и «затереть ответ CIO» — разные вещи, и у "
                f"владельца есть только вторая"),
        })
    elif decision.get("unchecked_reason"):
        unchecked.append(
            f"работает ли слой решения при взведённой двери: "
            f"{decision['unchecked_reason']}")

    verdict = separability.get("verdict")
    if verdict == "NOT_SEPARABLE":
        findings.append({
            "severity": "CRITICAL",
            "code": "separability",
            "message": (
                f"требование §42 «остановить execution без остановки "
                f"monitoring/reporting» НЕ выполнено: {separability.get('reason')}"),
        })
    elif verdict == UNCHECKED:
        unchecked.append(f"отделимость наблюдения от остановки: "
                         f"{separability.get('reason')}")
    else:
        naming = separability.get("producers_naming_the_door") or []
        findings.append({
            "severity": "INFO",
            "code": "separability_holds",
            "message": (
                f"вторая половина §42 ВЫПОЛНЕНА: {separability.get('reason')}; "
                + (f"взведённую дверь при этом НАЗЫВАЮТ: {', '.join(naming)}"
                   if naming else
                   "но НИ ОДИН из них взведённую дверь не называет — вывод при "
                   "ней совпадает с выводом без неё")),
        })
        if not naming:
            findings.append({
                "severity": "WARN",
                "code": "silent_survival",
                "message": (
                    "наблюдение и отчёт переживают остановку МОЛЧА: их вывод "
                    "не меняется от того, взведён кран или нет — владелец "
                    "видит те же числа в обоих мирах"),
            })

    if present:
        findings.append({
            "severity": "INFO",
            "code": "controls_that_exist",
            "message": ("органы, которые есть и делают обещанное: "
                        + ", ".join(f"«{c['owner_wording']}» ({c['door']})"
                                    for c in present)),
        })
    return findings, unchecked


def _main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    doc = run(root=args.root, write=not args.no_write)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0
    c = doc["counts"]
    print(f"cio_kill_switch_controls: {doc['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} "
          f"unchecked={c['unchecked']})")
    if not doc["control"]["passed"]:
        print(f"  [НЕ ИЗМЕРЕНО] положительный контроль не пройден — "
              f"{doc['control']['reason']}")
        return 0
    for ctl in doc["controls"]:
        print(f"  {ctl['outcome']:9s} «{ctl['owner_wording']}» — "
              f"{ctl['detail'] or ctl['promise']}")
    for f in doc["findings"]:
        print(f"  [{f['severity']}] {f['message']}")
    for u in doc["unchecked"]:
        print(f"  [НЕ ИЗМЕРЕНО] {u}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
