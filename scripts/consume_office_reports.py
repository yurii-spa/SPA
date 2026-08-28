#!/usr/bin/env python3
"""consume_office_reports.py — обязательный шаг цикла оркестратора (ADR-066, Фаза 2).

Читает В КОНТЕКСТ сессии всё, что конституция (architecture/manifest.json)
объявила потребляемым оркестратором: продукты инвест-офиса, отчёт сторожа
соответствия, системный брифинг. Для каждого УСПЕШНО прочитанного артефакта
пишет квитанцию потребления (consumer = "orchestrator_protocol").

Честность:
  - отсутствующий/нечитаемый файл печатается как «❌ НЕ ПРОЧИТАН» и квитанцию
    НЕ получает;
  - отсутствующее поле печатается как «НЕ ИЗМЕРЕНО», НИКОГДА как `None`:
    `None` в выводе читается глазом как «пусто, всё в порядке» — это ровно
    fail-OPEN, сторож молчит утвердительно;
  - у КАЖДОГО артефакта печатается возраст: рекомендация 19-часовой давности
    и рекомендация свежая — разные вещи, и решает это читатель, а не выжимка;
  - скрипт информационный: пока офис ИЗМЕРЕН, exit 0 — красные строки в выводе
    это сигналы ОРКЕСТРАТОРУ действовать (карточки), а не коды выхода;
  - исключение — exit 3 «офис НЕ ИЗМЕРЕН»: в этом дереве нет НИ ОДНОГО
    артефакта офиса (типично — запуск из git-worktree, где они в `.gitignore`).
    Это не состояние офиса, а невозможность его измерить, и печатается ОДНОЙ
    строкой: прежний вывод давал двадцать «❌ НЕ ПРОЧИТАН» под подписью
    «действовать (карточки)» и звал завести двадцать карточек о мёртвом
    инвест-офисе, который жив (цикл #207). Читать чужие артефакты явно —
    `--data-dir <прод>/data`, и вывод НАЗЫВАЕТ, чьи они;
  - ведом манифестом: новый consumer_required-продукт с потребителем
    "orchestrator_protocol" автоматически попадает в этот шаг без правки кода.

LLM_FORBIDDEN (детерминированный экстрактор; выводами занимается сессия).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, REPO_ROOT)

CONSUMER = "orchestrator_protocol"

# Порог, с которого возраст артефакта проговаривается вслух. Это МЕТКА ПЕЧАТИ,
# а не гейт: политика свежести офиса живёт в `investment_os/health.py` и здесь
# не дублируется. Смысл метки — 19.4 ч и 0.2 ч не должны выглядеть одинаково.
STALE_HOURS = 24.0

_UNMEASURED = "НЕ ИЗМЕРЕНО"

# ЧТО каждая именованная ветка читает у производителя — объявлено ДАННЫМИ, а не
# спрятано в теле ветки, и сверяется с настоящим артефактом на каждом прогоне.
#
# Почему так, а не «проверить ветки глазами». Класс «ветка читает поля, которых
# производитель не пишет» рецидивировал в ЭТОМ файле трижды подряд:
#   * `findings_bridge` — читала файл `findings_bridge.json` и `counts.opened/
#     pending`, которых нет ни у одного производителя (починено циклом #170);
#   * `house_view_gap` — читала `overall` / `counts.critical` / `findings`, а
#     производитель пишет `gaps` / `counts.warn|info|unchecked`, и обязательный
#     шаг печатал «вердикт: None» при ДВУХ реальных расхождениях (#176);
#   * `_health` — читала `stale` / `failing` / `unknown` на верхнем уровне, где
#     их нет: протухший аналитик не был бы назван вовсе (найдено тем же замером).
# Каждый раз это находили вручную и по одной ветке. Объявленная схема + строка
# «СХЕМА РАЗОШЛАСЬ» переводят проверку из «посмотреть внимательно» в измерение,
# которое само краснеет на живых файлах в тот цикл, когда производитель уехал.
#
# Путь с точкой — вложенное поле (`house_view.overall_posture`): у house_view
# всё интересное лежит на втором уровне, и проверка только верхнего уровня
# пропустила бы ровно тот дрейф, ради которого она заведена.
_READ_SCHEMA: dict[str, tuple[str, ...]] = {
    "chief_investment.json": ("house_view.overall_posture", "house_view.conflicts",
                              "house_view.top_opportunities"),
    "_health.json": ("overall", "counts.total", "counts.healthy", "counts.stale",
                     "counts.missing", "counts.unknown_or_corrupt", "analysts"),
    "architecture_conformance.json": ("overall", "counts.critical", "counts.warn",
                                      "counts.aged", "counts.unchecked", "findings"),
    "house_view_gap.json": ("gaps", "unchecked", "counts.warn", "counts.info",
                            "counts.unchecked"),
    "findings_bridge_report.json": ("created", "closed", "deferred", "waiting_hysteresis",
                                    "escalated", "sources_unread", "open_cards", "delivery",
                                    "owner_answer_delivery"),
    "loop_retro.json": ("findings", "outcomes_completeness"),
    "loop_health.json": ("open_cards", "recurrences_total", "cards_fate",
                         "latency_finding_to_card", "latency_card_to_close",
                         "note"),
    "adapter_feed_divergence.json": ("overall", "counts.critical", "counts.warn",
                                     "counts.info", "counts.unchecked", "findings",
                                     "unchecked", "compared_protocols"),
}

# Отметка времени в шапке md-артефакта: `Auto-updated: **2026-08-09 05:44 UTC**`.
_MD_TS_RE = re.compile(r"(20\d\d-\d\d-\d\d)[ T](\d\d:\d\d)(?::\d\d)?\s*UTC")


# КТО пишет каждый артефакт — объявлено данными и СВЕРЕНО тестом с исходником
# (`test_declared_schema_matches_the_live_producer`), а не взято на веру.
#
# Зачем производитель вообще нужен проверке схемы. До #248 «поля нет в файле»
# печаталось как «производитель его не пишет» — два РАЗНЫХ утверждения:
# артефакт, произведённый ДО доставки ключа, не может его содержать, и назвать
# это расхождением значит позвать сессию завести карточку на ИСПРАВНОЕ
# состояние. Живой замер 15.08 17:0xZ: `owner_answer_delivery` приехал с ADR-086
# в 16:0xZ, отчёт моста на диске — от 13:03Z, и обязательный шаг напечатал
# «СХЕМА РАЗОШЛАСЬ … читаем НЕ ТОТ файл» о полностью здоровом контуре. Ровно то
# же было в #204/#205 с блоком `debt`; автор #235 капкан уже НАЗВАЛ и обошёл
# руками (поле `house_view` сознательно не внесено в `_READ_SCHEMA`) — то есть
# обход был, а проверки не было, и следующий добавленный ключ повторял аварию.
# Вторая половина цены: настоящее расхождение печаталось ТЕМИ ЖЕ словами, что
# ложное, — читатель учится игнорировать строку, и сигнал теряется.
_PRODUCER: dict[str, str] = {
    "chief_investment.json": "spa_core/investment_os/agents/chief_investment.py",
    "_health.json": "spa_core/investment_os/health.py",
    "architecture_conformance.json": "spa_core/monitoring/architecture_conformance.py",
    "house_view_gap.json": "spa_core/monitoring/house_view_gap.py",
    "findings_bridge_report.json": "spa_core/monitoring/findings_bridge.py",
    "loop_retro.json": "spa_core/monitoring/loop_retro.py",
    "loop_health.json": "spa_core/monitoring/loop_health.py",
    "adapter_feed_divergence.json": "spa_core/monitoring/adapter_feed_divergence.py",
}


# О ЧЁМ вынесен вердикт — предмет проверки, в отличие от `_PRODUCER` (кто её
# написал). Два разных вопроса, и до цикла #337 задавался только первый.
#
# Замер #337, живой. 21.08 07:44Z решение ADR-104 сменило в конституции такт
# `com.spa.io_chief_investment` (`interval:86400s → interval:300s`). В прод-дерево
# `architecture/` правка доехала в 19:21Z, а последний отчёт сторожа был
# произведён в 16:19Z — и обязательный шаг 0-офис три часа печатал
# `вердикт: OK (critical=0 warn=0 aged=0 unchecked=0)`. Строка была ПРАВДОЙ о
# прежней конституции и НЕИЗМЕРЕННОСТЬЮ о текущей; отличить одно от другого
# читателю было нечем. Возраст отчёта (5.1ч) на этот вопрос не отвечает: он
# меряет, давно ли сторож ходил, а не сменился ли под ним ПРЕДМЕТ.
#
# Ровно тот же класс, что #222 закрыл для `house_view_gap` (сверка судила по
# снимкам разных тактов) и #235 — для дом-вью (один бюджет на producers с
# тактами в два порядка). Правило класса: зелёный ответ сторожа на СВОЙ вопрос
# никогда не есть ответ на нужный.
#
# Объявлять сюда только то, что действительно измеримо и действительно является
# предметом: артефакт, «предмет» которого — живая система (`data/*`), сюда НЕ
# годится, иначе каждая запись цикла давала бы находку, и строка обесценится.
_SUBJECT: dict[str, tuple[str, ...]] = {
    "architecture_conformance.json": ("architecture/manifest.json",),
}


def _sha256(path: str) -> str | None:
    import hashlib
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def _subject_drift(name: str, data, *, root: str | None = None,
                   now: dt.datetime | None = None) -> list[str]:
    """Менялся ли ПРЕДМЕТ проверки после того, как вердикт был вынесен.

    Три исхода, и они РАЗНЫЕ:
      * предмет с тех пор не менялся ⇒ молчим (вердикт актуален);
      * предмет изменился ⇒ находка: вердикт вынесен о ПРЕЖНЕЙ конституции,
        о текущей не измерено ничего;
      * предмет или отметка времени не читаются ⇒ «НЕ ИЗМЕРЕНО» вслух
        (fail-CLOSED, инвариант 2), а не молчание.

    Основание сравнения — СОДЕРЖИМОЕ (`sha256` из блока `inputs` отчёта), и
    только при его отсутствии — `mtime`. Перезапись файла байт-в-байт двигает
    mtime, а генератор манифеста идемпотентен по построению: судить по одному
    mtime значило бы печатать находку на каждой холостой перегенерации.
    Основание НАЗЫВАЕТСЯ в самой строке — иначе «сошлось по хэшу» и «сошлось,
    потому что мерить было нечем» выглядят одинаково.
    """
    subjects = _SUBJECT.get(name)
    if not subjects:
        return []
    root = root or REPO_ROOT
    art_ts = _parse_ts(data.get("generated_at"))
    recorded = {r.get("path"): r for r in (data.get("inputs") or [])
                if isinstance(r, dict)}
    lines: list[str] = []
    for rel in subjects:
        path = os.path.join(root, rel)
        prev = recorded.get(rel)
        now_sha = _sha256(path)
        if now_sha is None:
            lines.append(f"   ⚠️ предмет проверки {_UNMEASURED}: {rel} не прочитан — "
                         f"о чём именно вынесен вердикт, сказать нечем.")
            continue
        if isinstance(prev, dict) and prev.get("sha256"):
            if prev["sha256"] == now_sha:
                continue
            lines.append(
                f"   ⚠️ ВЕРДИКТ О ПРЕЖНЕМ ПРЕДМЕТЕ: {rel} изменился ПОСЛЕ замера "
                f"(сверка по содержимому: отчёт мерил {prev['sha256'][:12]}, "
                f"сейчас {now_sha[:12]}) — про ТЕКУЩИЙ {rel} не измерено ничего. "
                f"Это находка (карточка), а не деталь: дождаться такта "
                f"производителя или прогнать сторожа руками.")
            continue
        # Старый отчёт без `inputs` — судим по mtime и говорим это вслух.
        try:
            mtime = dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc)
        except OSError:
            mtime = None
        if art_ts is None or mtime is None:
            why = ("у отчёта нет разобранного generated_at" if art_ts is None
                   else f"у {rel} не измерено время правки")
            lines.append(f"   ⚠️ предмет проверки {_UNMEASURED}: {why}; "
                         f"отчёт старого образца (без блока `inputs`) — "
                         f"сверить по содержимому нечем.")
        elif mtime > art_ts:
            lines.append(
                f"   ⚠️ ВЕРДИКТ О ПРЕЖНЕМ ПРЕДМЕТЕ: {rel} правлен "
                f"{mtime:%Y-%m-%d %H:%M}Z, отчёт произведён "
                f"{art_ts:%Y-%m-%d %H:%M}Z — про ТЕКУЩИЙ {rel} не измерено "
                f"ничего. Сверка по mtime (отчёт старого образца, без `inputs`): "
                f"холостая перегенерация тем же содержимым даёт ту же строку. "
                f"Это находка, а не деталь.")
    return lines


def _has_path(data, path: str) -> bool:
    """Есть ли (возможно вложенное) поле `a.b.c` — именно ЕСТЬ, а не истинно."""
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return True


def _source_keys(path: str):
    """Строковые литералы исходника — или None, если измерить нечем.

    Докстринги и голые строки-выражения ИСКЛЮЧЕНЫ намеренно: капкан #227 —
    там сканер зачёл упоминание в комментарии за проводку, и комментарий,
    объяснявший «этого тут нет», молча снимал вопрос навсегда. Здесь та же
    ошибка дала бы «производитель ключ пишет» по одному лишь абзацу докстринга,
    в котором ключ назван (а он назван — в `owner_answer_delivery.py` именно
    так). None ⇒ «не измерено», НИКОГДА не «в порядке».
    """
    try:
        tree = ast.parse(_read_text(path))
    except (OSError, SyntaxError, ValueError):
        return None
    bare = {id(n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in bare}


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _schema_drift(name: str, data, *, root: str | None = None) -> list[str]:
    """Поля, которые ветка читает, а производитель не пишет — вслух.

    Три РАЗНЫХ ответа вместо одного (см. комментарий к `_PRODUCER`):
      * ключа нет в исходнике производителя ⇒ РАСХОЖДЕНИЕ (находка, карточка);
      * ключ есть, отчёт произведён ПОЗЖЕ кода ⇒ тоже РАСХОЖДЕНИЕ, и раньше
        этот случай не отличался от следующего вовсе;
      * ключ есть, отчёт произведён РАНЬШЕ кода ⇒ отчёт старого образца, ждём
        такта производителя — печатается, но находкой НЕ объявляется;
      * производитель не объявлен / не найден / не разобран / у отчёта нет
        `generated_at` ⇒ «НЕ ИЗМЕРЕНО» громко, как и было (fail-CLOSED).
    Обе стороны сравнения НАЗЫВАЮТСЯ в самой строке (#222): судить о возрасте
    молча — то же самое, что не судить.
    """
    missing = [p for p in _READ_SCHEMA.get(name, ()) if not _has_path(data, p)]
    if not missing:
        return []
    root = root or REPO_ROOT
    rel = _PRODUCER.get(name)
    src = os.path.join(root, rel) if rel else None
    keys = _source_keys(src) if src else None
    try:
        mtime = dt.datetime.fromtimestamp(os.path.getmtime(src), dt.timezone.utc) \
            if src else None
    except OSError:
        mtime = None
    art_ts = _parse_ts(data.get("generated_at"))

    if rel is None:
        why = "производитель не объявлен в _PRODUCER"
    elif keys is None:
        why = f"исходник производителя {rel} не прочитан/не разобран"
    elif mtime is None:
        why = f"у исходника производителя {rel} не измерено время правки"
    else:
        why = None

    drift: list[str] = []
    old: list[str] = []
    unmeasured: list[str] = []
    for p in missing:
        leaf = p.split(".")[-1]
        if why is not None:
            unmeasured.append(p)
        elif leaf not in keys:
            drift.append(p)
        elif art_ts is None:
            unmeasured.append(p)
        elif art_ts < mtime:
            old.append(p)
        else:
            drift.append(p)

    lines: list[str] = []
    if drift:
        bits = []
        if rel:
            bits.append(f"производитель {rel}")
        if mtime is not None:
            bits.append(f"правлен {mtime:%Y-%m-%d %H:%M}Z")
        if art_ts is not None:
            bits.append(f"отчёт {art_ts:%Y-%m-%d %H:%M}Z")
        tail = f" ({' · '.join(bits)})" if bits else ""
        lines.append("   ⚠️ СХЕМА РАЗОШЛАСЬ: производитель не пишет "
                     + ", ".join(drift) + tail
                     + " — выжимка ниже читает НЕ ТОТ файл. Это находка (карточка), а не деталь.")
    if old:
        lines.append("   ℹ️ отчёт СТАРОГО ОБРАЗЦА (не находка): " + ", ".join(old)
                     + f" — производитель {rel} их пишет (правлен "
                     + f"{mtime:%Y-%m-%d %H:%M}Z), а отчёт произведён РАНЬШЕ "
                     + f"({art_ts:%Y-%m-%d %H:%M}Z); ждём следующего такта производителя.")
    if unmeasured:
        reason = why or "у отчёта нет разобранного generated_at"
        lines.append(f"   ⚠️ расхождение схемы {_UNMEASURED}: " + ", ".join(unmeasured)
                     + f" — {reason}; отличить старый образец от расхождения нечем.")
    return lines


def _num(container, key):
    """Счётчик или явное «НЕ ИЗМЕРЕНО».

    Отсутствующий счётчик — это НЕ ноль, а неизмеренная величина (fail-CLOSED).
    """
    if not isinstance(container, dict) or key not in container:
        return _UNMEASURED
    v = container.get(key)
    return _UNMEASURED if v is None else v


def _parse_ts(value):
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _age_line(ts_value, now: dt.datetime) -> str:
    """Возраст артефакта — безусловно, для КАЖДОГО артефакта.

    Отдельная строка, а не свойство generic-ветки: до #176 возраст печатался
    только тем артефактам, у которых не нашлось именованной ветки, и самый
    важный из них — house_view — ехал в контекст оркестратора без единого
    признака возраста (замер: 19.4 ч, и три «возможности» в нём были дофиксовые).
    """
    if ts_value is None:
        return "   ⚠️ возраст НЕ ИЗМЕРЕН: производитель не пишет generated_at"
    parsed = _parse_ts(ts_value)
    if parsed is None:
        return f"   ⚠️ возраст НЕ ИЗМЕРЕН: generated_at не разобран ({ts_value!r})"
    hours = (now - parsed).total_seconds() / 3600.0
    mark = "  ⚠️ старше суток" if hours >= STALE_HOURS else ""
    return f"   generated_at: {ts_value} (возраст {hours:.1f}ч){mark}"


def _summarize_json(path: str, data, *, now: dt.datetime | None = None,
                    root: str | None = None,
                    artifact_root: str | None = None) -> list[str]:
    """Компактная выжимка известных офисных файлов; generic — для остальных.

    Два разных корня, и это не педантизм. `root` — где искать ИСХОДНИК
    производителя (сверка схемы); `artifact_root` — дерево, ЧЕЙ артефакт мы
    сейчас читаем, и значит единственное место, где лежит ПРЕДМЕТ, о котором
    вынесен вердикт. В режиме `--data-dir` (читаем офис прода из worktree) они
    расходятся: сверить прод-отчёт с манифестом СВОЕГО дерева — значит выдумать
    расхождение там, где его нет, ровно тем же способом, каким #267 выдумывал
    «дрейф механики» из границы синхронизации. По умолчанию совпадают.
    """
    name = os.path.basename(path)
    if not isinstance(data, dict):
        return [f"   (не-dict JSON, {type(data).__name__})"]
    now = now or dt.datetime.now(dt.timezone.utc)
    head: list[str] = _schema_drift(name, data, root=root)
    head.append(_age_line(data.get("generated_at"), now))
    # ПОСЛЕ возраста и ДО вердикта: читатель должен узнать, что предмет сменился,
    # раньше, чем прочтёт вердикт о нём.
    head.extend(_subject_drift(name, data, root=(artifact_root or root), now=now))
    out: list[str] = []
    if name == "chief_investment.json":
        hv = data.get("house_view") or {}
        out.append(f"   постура: {hv.get('overall_posture')}")
        for c in (hv.get("conflicts") or [])[:3]:
            out.append(f"   конфликт: {c}")
        for o in (hv.get("top_opportunities") or [])[:3]:
            v = o.get("value") or {}
            out.append(f"   возможность: {v.get('protocol')} {v.get('apy_pct')}% "
                       f"(evidence {o.get('evidence_level')})")
    elif name == "_health.json":
        # Схема ВЫМЕРЕНА по производителю (`investment_os/health.py`): счётчики
        # лежат в `counts`, а строки аналитиков — в `analysts`. Прежняя ветка
        # читала `stale`/`failing`/`unknown` на верхнем уровне: ни одного такого
        # поля нет, поэтому «протух аналитик» шаг 0-офис не сказал бы НИКОГДА —
        # печаталась одна строка «статус офиса», и она читалась как весь ответ.
        c = data.get("counts") or {}
        out.append(f"   статус офиса: {data.get('overall') or data.get('status')}")
        out.append(f"   аналитики: всего {_num(c, 'total')} · здоровы {_num(c, 'healthy')} · "
                   f"протухли {_num(c, 'stale')} · нет файла {_num(c, 'missing')} · "
                   f"нечитаемы {_num(c, 'unknown_or_corrupt')}")
        # ДОМ-ВЬЮ отдельной строкой (#235): «здоровы 11» читалось как ответ про офис
        # целиком, тогда как судим мы каждый цикл именно по дом-вью. Поле НЕ внесено в
        # `_READ_SCHEMA` СОЗНАТЕЛЬНО: производитель дневной, и до его следующего такта
        # живой файл поля не имеет — требование обязательности выдало бы ложную находку
        # «СХЕМА РАЗОШЛАСЬ» на верном состоянии. Нет поля ⇒ честное «не измерено».
        hv = data.get("house_view")
        if isinstance(hv, dict):
            age_h = hv.get("age_s")
            age_txt = f"{age_h / 3600:.1f}ч" if isinstance(age_h, (int, float)) else _UNMEASURED
            max_h = hv.get("max_age_s")
            max_txt = f"{max_h / 3600:.0f}ч" if isinstance(max_h, (int, float)) else _UNMEASURED
            mark = "" if hv.get("status") == "FRESH" else "⚠️ "
            # ПРОИСХОЖДЕНИЕ срока годности (#340). Молчим, когда он ПРОЧИТАН из конституции
            # флота, и говорим вслух, когда это откат на литерал: до #340 срок был списан
            # рукой с такта 16.08, решение владельца ADR-104 сменило такт 21.08, и строка
            # «дом-вью FRESH при сроке 30ч» свидетельствовала В ПОЛЬЗУ здоровья артефакта,
            # который по действующей конституции протух. Число без источника неоспоримо.
            src = hv.get("budget_source")
            src_txt = ("" if src in ("manifest_slo", None)
                       else f" · срок НЕ из конституции ({src}: {hv.get('budget_why', '')})")
            out.append(f"   {mark}дом-вью ({hv.get('agent')}): {hv.get('status')} · "
                       f"возраст {age_txt} при сроке годности {max_txt}{src_txt}")
        else:
            out.append(f"   дом-вью: {_UNMEASURED} (поля `house_view` нет — "
                       f"производитель ещё не переписал файл)")
        for a in (data.get("analysts") or []):
            if not isinstance(a, dict):
                continue
            if a.get("present") and a.get("fresh") and a.get("status") == "ok":
                continue
            out.append(f"   ⚠️ аналитик {a.get('agent')}: present={a.get('present')} "
                       f"fresh={a.get('fresh')} status={a.get('status')}")
    elif name == "architecture_conformance.json":
        c = data.get("counts") or {}
        out.append(f"   вердикт: {data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"aged={_num(c, 'aged')} unchecked={_num(c, 'unchecked')})")
        for f in (data.get("findings") or [])[:8]:
            out.append(f"   [{f.get('severity')}] {f.get('message')}")
        if (data.get("findings") or [])[8:]:
            out.append(f"   … ещё {len(data['findings']) - 8} наход(ок) в отчёте")
        # ПРИЧИНА «не измерено» — не декорация: до цикла #236 счётчик
        # `unchecked=1` печатался голым числом, и читателю шага 0 приходилось
        # лезть в JSON руками, чтобы узнать, ЧТО именно не измерено.
        for u in (data.get("unchecked") or [])[:4]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {u.get('check')}: {u.get('reason')}")
        for p in (data.get("mechanics_from_ref") or [])[:4]:
            out.append(f"   [измерено с {p.get('ref')}] {p.get('label')}: "
                       f"{p.get('plist')} — в прод-дереве файла нет, "
                       f"{'сошлось' if p.get('agrees') else 'РАСХОДИТСЯ'}")
    elif name == "adapter_feed_divergence.json":
        # Сверка ДВУХ артефактов адаптеров об одном протоколе (ADR-060 D6).
        # Рода расхождений печатаются РАЗНЫМИ словами намеренно: «оба фида
        # наблюдают и не сходятся» (инвариант 2, fail-CLOSED) и «одна сторона
        # подставила литерал, потому что не наблюдала» — разные аварии с разной
        # починкой, и одинаковая формулировка увела бы починку не туда.
        c = data.get("counts") or {}
        findings = data.get("findings") or []
        out.append(f"   сверка двух фидов адаптеров: {data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"info={_num(c, 'info')} unchecked={_num(c, 'unchecked')}); "
                   f"протоколов сверено: {len(data.get('compared_protocols') or [])}")
        for f in [x for x in findings if x.get("severity") in ("CRITICAL", "WARN")][:8]:
            out.append(f"   [{f.get('severity')}] {f.get('message')}")
        # INFO-строки (расхождение ПРОВЕНАНСА TVL) не печатаются поимённо: их
        # шесть каждый день, состояние уже названо и решено (ADR-053), и вынос
        # их в обязательный шаг научил бы читателя пролистывать весь блок.
        info_n = sum(1 for x in findings if x.get("severity") == "INFO")
        if info_n:
            out.append(f"   … и {info_n} INFO-строк(и) о провенансе TVL "
                       f"(константа против живого — состояние названо, ADR-053)")
        for u in (data.get("unchecked") or [])[:4]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {u}")
    elif name == "house_view_gap.json":
        # Схема ВЫМЕРЕНА по производителю (`monitoring/house_view_gap.py`):
        # расхождения лежат в `gaps`, счётчики — `warn`/`info`/`unchecked`.
        # Прежняя ветка читала `overall`/`counts.critical`/`findings` — ни одного
        # такого поля производитель не пишет, и обязательный шаг печатал
        # «вердикт: None (critical=None …)» при ДВУХ реальных расхождениях.
        # «None» глазом читается как «пусто, всё в порядке» — тот же fail-OPEN,
        # что уже разбирали соседней веткой в этом же файле.
        c = data.get("counts") or {}
        gaps = data.get("gaps") or []
        out.append(f"   расхождений house_view↔факт: {len(gaps)} "
                   f"(warn={_num(c, 'warn')} info={_num(c, 'info')} "
                   f"unchecked={_num(c, 'unchecked')})")
        for g in gaps[:8]:
            out.append(f"   [{g.get('severity')}] {g.get('message')}")
        if gaps[8:]:
            out.append(f"   … ещё {len(gaps) - 8} расхожден(ий) в отчёте")
        for u in (data.get("unchecked") or [])[:4]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {u.get('check')}: {u.get('reason')}")
    elif name == "findings_bridge_report.json":
        # Имя и схема ВЫМЕРЕНЫ по производителю (`findings_bridge.REPORT_REL`),
        # а не по памяти: ветка звалась `findings_bridge.json` и читала поля
        # `counts.opened/pending` — такого файла нет ни у одного производителя,
        # такой схемы нет ни в одном отчёте. Ветка была мёртвой, и обязательный
        # шаг 0-офис печатал по мосту одну строку `generated_at`, хотя манифест
        # требует «deferred читать ОБЯЗАТЕЛЬНО». Тот же класс, что #144: правка
        # детали при мёртвой проводке зелёная и бесполезная.
        out.append(f"   мост находка→карточка: создано {len(data.get('created') or [])} · "
                   f"закрыто {len(data.get('closed') or [])} · отложено "
                   f"{len(data.get('deferred') or [])} · ждут гистерезиса "
                   f"{len(data.get('waiting_hysteresis') or [])} · "
                   f"открытых карточек {_num(data, 'open_cards')}")
        for f in (data.get("created") or [])[:5]:
            out.append(f"   + [{f.get('severity')}] карточка {f.get('card')}")
        for k in (data.get("deferred") or [])[:5]:
            out.append(f"   ⚠️ ОТЛОЖЕНО rate-limit'ом (карточки НЕТ): {k}")
        for k in (data.get("escalated") or [])[:5]:
            out.append(f"   ⬆️ эскалация WARN→CRITICAL: {k}")
        # Гистерезис ЗАКРЫТИЯ (ADR-161): находка пропала, но ряд молчаливых
        # прогонов ещё не набран. Печатать обязательно — иначе шаг 0-офис
        # показывает «мост ничего не закрыл» там, где мост ЖДЁТ подтверждения,
        # и это ровно та болезнь, которую ADR-161 лечит ВНУТРИ моста: молчаливый
        # порог неотличим от бездействия. Клауза дописывается ТОЛЬКО при >0 и
        # ключ НЕ внесён в `_READ_SCHEMA` намеренно — отчёты, написанные до
        # ADR-161, законно его не имеют, и требовать его значило бы поднять
        # «СХЕМА РАЗОШЛАСЬ» на собственной доставке.
        closing = data.get("closing_hysteresis") or []
        if closing:
            out.append(f"   ⏳ ждут ЗАКРЫТИЯ по гистерезису: {len(closing)} — находка пропала, "
                       f"но ряд молчаливых прогонов не набран (молчание одного прогона не есть починка)")
            for c in closing[:5]:
                out.append(f"      {os.path.basename(str(c.get('card') or '?'))}: "
                           f"{c.get('absent_count')}/{c.get('required')} прогон(а) подряд")
        for src in (data.get("sources_unread") or []):
            out.append(f"   [ИСТОЧНИК НЕ ПРОЧИТАН] {src}")
        # Доставка карточек на origin: `needs-owner` вне origin для очереди
        # владельца не существует, поэтому провал доставки — находка, а не деталь.
        d = data.get("delivery") or {}
        if d:
            st = d.get("status")
            if st in ("DELIVERED", "IDLE"):
                # «Наша правка уже на origin» названо ОТДЕЛЬНО от «доставлено»:
                # иначе прогон, где везти было нечего потому, что всё уже там,
                # читается как прогон, где везти было нечего вообще (#268).
                covered = len(d.get("covered_by_origin") or [])
                # «Origin пришёл к тому же исходу раньше нас» — ТРЕТЬЕ основание
                # «везти нечего», и названо оно отдельно от второго: там origin
                # содержит нашу запись, здесь он записал тот же переход СВОЕЙ
                # строкой (наше закрытие оказалось повторным). Схлопнув их, шаг
                # 0-офис перестал бы отличать «мы отстали» от «мы сделали дважды».
                outcome = len(d.get("same_outcome_on_origin") or [])
                out.append(f"   доставка карточек: {st} ({len(d.get('delivered') or [])} на origin"
                           + (f"; уже на origin, origin ушёл вперёд: {covered}" if covered else "")
                           + (f"; origin закрыл раньше нас (повторное закрытие): {outcome}"
                              if outcome else "")
                           + ")")
            else:
                out.append(f"   ⚠️ ДОСТАВКА КАРТОЧЕК {st}: {d.get('reason')} "
                           f"(пыталось {len(d.get('attempted') or [])})")
            # Долг доставки (ADR-081) — ОТДЕЛЬНАЯ строка, а не хвост статуса.
            # Статус говорит про ЭТОТ прогон, долг — про то, чего на origin нет
            # до сих пор; 12.08 схлопывание этих двух вопросов в один означало,
            # что через два часа `IDLE` покажет зелёную строку при трёх
            # недоставленных карточках, и потеря исчезнет из поля зрения.
            debt = d.get("debt")
            if debt is None:
                out.append("   ⚠️ долг доставки НЕ ИЗМЕРЕН: в квитанции нет блока debt "
                           "(отчёт старого образца — до ADR-081)")
            elif debt.get("unmeasured"):
                out.append(f"   ⚠️ долг доставки НЕ ИЗМЕРЕН: {debt['unmeasured']}")
            elif debt.get("count"):
                age = debt.get("oldest_hours")
                age_s = f"старшему {age}ч" if age is not None else "возраст не датируется"
                out.append(f"   ⚠️ ДОЛГ ДОСТАВКИ: {debt['count']} карточк(и) НЕ на origin "
                           f"({age_s}) — поедут следующим прогоном")
                after = debt.get("stale_after")
                for p in (debt.get("stale") or [])[:5]:
                    out.append(f"   ⛔ не рассасывается повтором "
                               f"(≥{after if after is not None else '?'} попыток), "
                               f"нужен человек: {p}")
                for dr in (debt.get("dropped") or [])[:5]:
                    out.append(f"   ⚠️ снято с долга: {dr.get('path')} — {dr.get('reason')}")
        else:
            out.append("   ⚠️ доставка карточек НЕ ИЗМЕРЕНА: в отчёте нет блока delivery")
        # Доставка СЛЕДА решения владельца (ADR-086) — отдельный вопрос от доставки
        # карточек: мост везёт то, что создал сам, а ответ владельца пишет БОТ, и
        # мост его не создавал никогда. Замер #247: 2 из 9 ответов не были в git
        # ни минуты (с 08.08). Молчание здесь читалось бы как «след на origin».
        oad = data.get("owner_answer_delivery")
        if oad is None:
            out.append("   ⚠️ след решения владельца НЕ ИЗМЕРЕН: в отчёте нет блока "
                       "owner_answer_delivery (отчёт старого образца — до ADR-086)")
        else:
            ost = oad.get("status")
            if ost == "DELIVERED":
                out.append(f"   след решения владельца: доставлен "
                           f"{len(oad.get('delivered') or [])} → origin "
                           f"(коммит {oad.get('commit')})")
            elif ost == "IDLE":
                out.append(f"   след решения владельца: весь на origin "
                           f"({len(oad.get('already_on_origin') or [])} карточк(и))")
            else:
                out.append(f"   ⚠️ СЛЕД РЕШЕНИЯ ВЛАДЕЛЬЦА {ost}: {oad.get('reason')} "
                           f"(недоставлено {len(oad.get('pending') or [])})")
            for c in (oad.get("conflicts") or [])[:5]:
                out.append(f"   ⛔ ДВА РАЗНЫХ ОТВЕТА ВЛАДЕЛЬЦА, нужен человек: "
                           f"{c.get('card')} — {c.get('reason')}")
            for u in (oad.get("unmeasured") or [])[:5]:
                out.append(f"   ⚠️ след НЕ ИЗМЕРЕН: {u.get('card')} — {u.get('reason')}")
    elif name == "loop_retro.json":
        # До этой ветки ретро печаталось как «(пусто)»: generic-ветка ищет
        # status/reason, а у ретро их нет — и ЕГО НАХОДКИ не показывались вовсе.
        # Мост их читает, но обязательный шаг цикла молчал о них, то есть
        # артефакт числился прочитанным, а прочитанного в нём не было ничего.
        fnd = data.get("findings")
        if not isinstance(fnd, list):
            out.append(f"   ⚠️ находки ретро {_UNMEASURED}: в отчёте нет списка findings")
        else:
            out.append(f"   находок ретро: {len(fnd)}")
            for f in fnd[:5]:
                if isinstance(f, dict):
                    out.append(f"   [{f.get('severity') or _UNMEASURED}] "
                               f"{str(f.get('message') or f.get('key'))[:160]}")
            if len(fnd) > 5:
                out.append(f"   … ещё {len(fnd) - 5} (полный список — data/loop_retro.json)")
        # Полнота архива исходов — СУЖДЕНИЕ, а не возраст (#235: возраст решает
        # читатель, а суждение обязан вынести производитель). Возрастной бюджет
        # того же файла живёт в architecture_conformance и отвечает на свой вопрос.
        comp = data.get("outcomes_completeness")
        if not isinstance(comp, dict):
            out.append(f"   ⚠️ полнота архива исходов {_UNMEASURED}: в отчёте нет "
                       "блока outcomes_completeness (отчёт старого образца)")
        elif not comp.get("measured"):
            out.append(f"   ⚠️ полнота архива исходов {_UNMEASURED}: {comp.get('reason')}")
        elif comp.get("missing_days"):
            out.append(f"   🔴 архив исходов НЕПОЛОН: {comp.get('reason')}")
        else:
            out.append(f"   архив исходов полон: {_num(comp, 'expected_days')} закрыт(ых) "
                       f"evidenced-дн(я/ей) с якоря {comp.get('anchor_date')}, дыр нет")
    elif name == "loop_health.json":
        # СИБЛИНГ loop_retro.json, и та же авария — на файле, который её уже
        # объяснил. Ветка ретро заведена со словами «до неё ретро печаталось
        # как (пусто)»; пульс той же петли остался в generic-ветке, а она ищет
        # status/overall/posture/reason/summary, которых loop_health не пишет
        # ни одного. Живой замер 2026-08-28 03:2xZ: артефакт нёс recurrences
        # 3, cards_fate.unreadable 4 и card→close max 66.01ч, обязательный шаг
        # напечатал про него «(пусто)» и засчитал в «прочитано 22, не
        # прочитано 0». Артефакт объявлен в конституции с потребителем
        # `orchestrator` — то есть читать его ОБЯЗАНЫ, а прочитанного в нём не
        # было ничего.
        #
        # Что печатаем и почему именно это (порядок — по цене ошибки):
        #   * `unreadable` — статус карточки НЕ ИЗМЕРЕН: третий исход, который
        #     нельзя складывать ни с «взята», ни с «лежит» (иначе неизмеренное
        #     читается как благополучие);
        #   * `recurrences_total` — производитель сам называет рецидив
        #     СИСТЕМНОЙ причиной, а не случайностью;
        #   * `new` — карточки моста, которые никто не взял: это и есть пульс;
        #   * `note` производителя — его собственная оговорка «медианы по n<5
        #     не интерпретировать»; без неё числа читаются увереннее, чем их
        #     написал автор.
        fate = data.get("cards_fate")
        if not isinstance(fate, dict):
            out.append(f"   ⚠️ судьба карточек петли {_UNMEASURED}: в отчёте нет "
                       "блока cards_fate (отчёт старого образца)")
        else:
            out.append(f"   петля ADR-066: открытых карточек {_num(data, 'open_cards')} · "
                       f"не взято {_num(fate, 'new')} · в работе {_num(fate, 'in_progress')} · "
                       f"закрыто человеком {_num(fate, 'done_by_human')} · "
                       f"автозакрыто {_num(fate, 'auto_closed')}")
            if fate.get("unreadable"):
                out.append(f"   ⚠️ статус {fate['unreadable']} карточк(и) моста "
                           f"{_UNMEASURED}: карточка не прочитана (files-first очередь "
                           "не отдала статус) — это НЕ «взята» и НЕ «лежит»")
        rec = data.get("recurrences_total")
        if rec is None:
            out.append(f"   ⚠️ рецидивы {_UNMEASURED}: в отчёте нет recurrences_total")
        elif rec:
            out.append(f"   🔴 РЕЦИДИВ: {rec} находк(а/и) ВЕРНУЛИСЬ после закрытия — "
                       "по производителю это системная причина, а не случайность")
            # Голое число объявляло причину системной и не называло НИ ОДНОЙ
            # находки: действовать по такой строке нечем, и она возвращалась
            # каждый цикл нетронутой. Производитель теперь называет класс и
            # ключи (loop_health._recurrence_detail) — печатаем их, а если полей
            # нет (отчёт старого образца), говорим это вслух, а не молчим.
            by_class = data.get("recurrences_by_class")
            recurring = data.get("recurring_findings")
            if not isinstance(by_class, dict) or not isinstance(recurring, list):
                out.append(f"      ⚠️ ЧТО именно вернулось {_UNMEASURED}: в отчёте нет "
                           "recurring_findings/recurrences_by_class (отчёт старого "
                           "образца) — действовать по этой строке нечем")
            else:
                if len(by_class) == 1:
                    cls, n = next(iter(by_class.items()))
                    out.append(f"      причина ОДНА, а не пять: весь рецидив из класса "
                               f"`{cls}` ({n}) — чинить класс, а не находки поштучно")
                else:
                    out.append("      по классам: " + " · ".join(
                        f"`{c}` {n}" for c, n in list(by_class.items())[:4]))
                uncarded = [r for r in recurring if not r.get("carded")]
                if uncarded:
                    out.append(f"      🔴 вернулись и карточки СЕЙЧАС НЕТ ({len(uncarded)}): "
                               + " · ".join(f"{r.get('key')} ×{r.get('recurrences')}"
                                            for r in uncarded[:4]))
                for r in recurring[:4]:
                    out.append(f"      - {r.get('key')} ×{r.get('recurrences')} "
                               f"(статус {r.get('status')}, карточка "
                               f"{'есть' if r.get('carded') else 'НЕТ'})")
        for key, label in (("latency_finding_to_card", "находка→карточка"),
                           ("latency_card_to_close", "карточка→закрытие")):
            lat = data.get(key)
            if not isinstance(lat, dict):
                out.append(f"   ⚠️ латентность {label} {_UNMEASURED}: в отчёте нет {key}")
            elif not lat.get("n"):
                out.append(f"   латентность {label}: измерять нечего (n=0)")
            else:
                out.append(f"   латентность {label}: медиана {lat.get('median_h')}ч · "
                           f"максимум {lat.get('max_h')}ч (n={lat.get('n')})")
        if data.get("note"):
            out.append(f"   оговорка производителя: {str(data['note'])[:160]}")
    elif name == "owner_decision_pending.json":
        out.append(f"   статус: {data.get('status')}")
        if data.get("reason"):
            out.append(f"   {str(data['reason'])[:160]}")
        # Полнота очереди: видит ли это дерево ВСЕ вопросы владельца (цикл #270).
        # Отдельной строкой и всегда, по той же причине, что и кнопки ниже: `reason`
        # обрезается до 160 символов, а именно в хвосте стоят идентификаторы карточек,
        # ради которых строка и написана. Молчание тут читалось бы как «очередь полна» —
        # 17.08 ровно так и потерялся `own-34` (needs-owner на origin, файла в проде нет).
        gap = data.get("origin_queue")
        if not isinstance(gap, dict):
            out.append("   ⚠️ полнота очереди НЕ ИЗМЕРЕНА: в отчёте нет блока "
                       "origin_queue (отчёт старого образца)")
        elif not gap.get("measured"):
            out.append(f"   ⚠️ полнота очереди НЕ ИЗМЕРЕНА: {gap.get('reason')}")
        elif gap.get("count"):
            names = ", ".join(str(c.get("card_id")) for c in (gap.get("hidden") or []))
            out.append(f"   ⚠️ очередь дерева НЕПОЛНА: {gap['count']} вопрос(ов) владельцу "
                       f"есть на {gap.get('ref')} ({str(gap.get('ref_sha'))[:9]}), "
                       f"файла в дереве нет — {names}")
        else:
            out.append(f"   очередь полна: невидимых дереву вопросов нет "
                       f"({gap.get('ref')} {str(gap.get('ref_sha'))[:9]})")
        # Третье плечо той же полноты (#351): вопрос владельцу, живущий ТОЛЬКО на
        # ВЕТКЕ. Его не видит ни строка выше (сверяет дерево с `origin/main`), ни
        # отправитель. Печатаем ВСЕГДА и сразу после неё: рядом эти две строки
        # означают «очередь измерена с обеих сторон», а строка выше в одиночку
        # читалась как утверждение о полноте, замера под которым не было.
        bgap = data.get("branch_queue")
        if not isinstance(bgap, dict):
            out.append("   ⚠️ вопросы на ВЕТКАХ НЕ ИЗМЕРЕНЫ: в отчёте нет блока "
                       "branch_queue (отчёт старого образца)")
        elif not bgap.get("measured"):
            out.append(f"   ⚠️ вопросы на ВЕТКАХ НЕ ИЗМЕРЕНЫ: {bgap.get('reason')}")
        else:
            unread = bgap.get("unreadable") or []
            tail = (f"; НЕ ПРОЧИТАНО веток: {len(unread)}" if unread else "")
            if bgap.get("count"):
                names = ", ".join(
                    f"{c.get('card_id')} ({', '.join(c.get('branches') or [])})"
                    for c in (bgap.get("cards") or [])[:3])
                more = (f" (и ещё {bgap['count'] - 3})" if bgap["count"] > 3 else "")
                out.append(f"   ⚠️ вопросов владельцу ТОЛЬКО НА ВЕТКЕ: {bgap['count']} "
                           f"— ни задать, ни закрыть (веток прочитано "
                           f"{bgap.get('branches_read')}){tail}: {names}{more}")
            else:
                out.append(f"   вопросов, живущих только на ветке, нет "
                           f"(веток прочитано {bgap.get('branches_read')}){tail}")
            # Третий исход рядом с «потеряно» и «убрано с базы»: карточку прочитали
            # при разборе ветки и осознанно решили не везти. Печатается ОТДЕЛЬНОЙ
            # строкой и с основанием — «решено не везти» без автора закрыло бы что
            # угодно, а невидимое основание проверить нечем (карточка
            # `inbox-storozh-voprosy-vladeltsa-na-vetke-ne-zn`).
            dropped = bgap.get("dropped") or []
            if dropped:
                names = "; ".join(
                    f"{d.get('card_id')} — {d.get('by')}, {d.get('date')}: {d.get('reason')}"
                    for d in dropped[:3] if isinstance(d, dict))
                more = (f" (и ещё {len(dropped) - 3})" if len(dropped) > 3 else "")
                out.append(f"   🚮 прочитано и осознанно НЕ везём: {len(dropped)} — "
                           f"это РЕШЕНИЕ, а не потеря: {names}{more}")
            # Брак реестра решений — находка о САМОМ реестре. Молчать нельзя: строка
            # с меткой, которую сторож не принял, означает, что автор решение записал,
            # а система его не увидела, и обе стороны считают, что всё в порядке.
            issues = bgap.get("declaration_issues") or []
            if issues:
                names = "; ".join(f"{i.get('where')} — {i.get('reason')}"
                                  for i in issues[:3] if isinstance(i, dict))
                more = (f" (и ещё {len(issues) - 3})" if len(issues) > 3 else "")
                out.append(f"   ⚠️ реестр «не везём» с браком: {len(issues)} — "
                           f"объявлением НЕ считается, карточка остаётся потерей: "
                           f"{names}{more}")
        # Дрейф прод↔origin (цикл #273): отправленная карточка закрыта на origin, а
        # файла в прод-дереве нет. НЕ находка — но и не молчание: до #273 такие
        # строки неделю держали сторожа в WARNING как «не измерено», и именно ради
        # объяснения они оттуда ушли. Объяснение, которого не видно, ничего не стоит.
        closed = data.get("closed_on_origin")
        if isinstance(closed, list) and closed:
            names = ", ".join(f"{c.get('card_id')} (`{c.get('origin_status')}`)"
                              for c in closed if isinstance(c, dict))
            out.append(f"   дрейф прод↔origin: {len(closed)} отправленн(ая/ых) карточк(а/и) "
                       f"ЗАКРЫТЫ на origin, файла в прод-дереве нет — {names}")
        # Принятые поручения (#350): владелец нажал «Принято — беру в работу», и
        # карточка ОСТАЛАСЬ открытой, потому что «принято» — это обещание, а не
        # исполнение. Читатель у обещания ровно один — этот шаг; молчание здесь
        # вернуло бы ровно ту потерю, ради которой статус и заведён.
        # Блока нет вовсе ⇒ говорим «НЕ ИЗМЕРЕНО»: отчёт старого образца не имеет
        # права выглядеть как «принятых поручений нет».
        if "accepted" not in data:
            out.append("   ⚠️ принятые поручения НЕ ИЗМЕРЕНЫ: в отчёте нет блока "
                       "accepted (отчёт старого образца)")
        else:
            accepted = data.get("accepted")
            accepted = accepted if isinstance(accepted, list) else []
            if accepted:
                names = ", ".join(
                    f"{c.get('card_id')} (принято {str(c.get('accepted_at') or 'когда — не записано')[:19]})"
                    for c in accepted if isinstance(c, dict))
                out.append(f"   ⚠️ принято владельцем, НЕ ИСПОЛНЕНО: {len(accepted)} "
                           f"поручени(е/я) ждут агента — {names}")
            else:
                out.append("   принятых и неисполненных поручений нет")
        accepted_origin = data.get("accepted_on_origin")
        if isinstance(accepted_origin, list) and accepted_origin:
            names = ", ".join(str(c.get("card_id")) for c in accepted_origin
                              if isinstance(c, dict))
            out.append(f"   дрейф прод↔origin: {len(accepted_origin)} принят(ое/ых) "
                       f"поручени(е/я) есть на origin, файла в прод-дереве нет — {names}")
        # Канал: уезжали ли владельцу сообщения с вариантами БЕЗ кнопок (жалоба 14.08).
        # Печатаем ОТДЕЛЬНОЙ строкой и всегда: молчание про этот вопрос читалось бы как
        # «кнопки в порядке», а до цикла #229 он был неизмерим по построению.
        ch = data.get("channel_buttons")
        if not isinstance(ch, dict):
            out.append("   ⚠️ кнопки в канале НЕ ИЗМЕРЕНЫ: в отчёте нет блока "
                       "channel_buttons (отчёт старого образца)")
        elif not ch.get("measured"):
            out.append(f"   ⚠️ кнопки в канале НЕ ИЗМЕРЕНЫ: {ch.get('reason')}")
        else:
            # Импорт локальный и защищённый: обязательный шаг 0-офис не имеет права
            # упасть из-за строчки оформления — упавший шаг это НЕ прочитанный офис.
            try:
                from spa_core.telegram.buttonless_audit import summary_line

                line = summary_line(ch)
            except Exception as exc:  # noqa: BLE001
                line = (f"⚠️ кнопки в канале НЕ ИЗМЕРЕНЫ: строку не собрать ({exc})")
            out.append(f"   {line}")
    else:
        status = data.get("status") or data.get("overall") or data.get("posture")
        if status is not None:
            out.append(f"   статус: {status}")
        reason = data.get("reason") or data.get("summary")
        if reason:
            out.append(f"   {str(reason)[:160]}")
    return head + (out or [
        f"{_HOLLOW_MARK}: ни ветки в `_summarize_json`, ни строки в "
        "`_READ_SCHEMA`, а generic-ветка не нашла ни `status`/`overall`/"
        "`posture`, ни `reason`/`summary`. Прочитано НИЧЕГО — это НЕ «пусто, "
        "всё в порядке» и НЕ «в файле ничего нет»: файл разобран не был."])


# Пустой разбор — ТРЕТИЙ исход, а не «прочитано». Четвёртый рецидив класса в этом
# файле (findings_bridge · house_view_gap · _health · loop_retro) прожил дольше
# всех остальных именно потому, что «(пусто)» ЗАСЧИТЫВАЛОСЬ в «прочитано»: 28.08
# шаг напечатал про `data/loop_health.json` «(пусто)», написал за него КВИТАНЦИЮ
# потребления и подвёл итог «прочитано 22, не прочитано 0» — при том, что в
# артефакте лежали 3 рецидива и 4 карточки со статусом «не измерено». Квитанция —
# это утверждение «я это прочитал», и на ней стоит проверка B3 сторожа
# архитектуры; правило самого модуля квитанций сказано прямо: «ресит пишется
# ТОЛЬКО после фактического успешного чтения — иначе B3 превращается в театр».
# Разобрать было нечем ⇒ читать было нечего ⇒ квитанции нет, и в итоге стоит
# отдельное число. Молчаливым «прочитано» этот исход больше не притворяется.
_HOLLOW_MARK = "   ⚠️ РАЗОБРАТЬ НЕЧЕМ"


def _summarize_md(full: str, *, now: dt.datetime | None = None) -> list[str]:
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        with open(full, encoding="utf-8") as f:
            head = [ln.rstrip() for _, ln in zip(range(12), f)]
    except Exception as e:  # noqa: BLE001
        return [f"   (md не прочитан: {e})"]
    stamp = None
    for ln in head:
        m = _MD_TS_RE.search(ln)
        if m:
            stamp = f"{m.group(1)}T{m.group(2)}:00+00:00"
            break
    body = ["   " + ln for ln in head if ln.strip()][:6]
    return [_age_line(stamp, now)] + body


def _resolve(rel: str, *, root: str, data_dir: str | None) -> str:
    """Куда смотреть за артефактом `rel`.

    Без `--data-dir` — как раньше, относительно `--root`.

    С `--data-dir` читается офис ТОГО дерева — целиком, включая
    `docs/SYSTEM_BRIEFING.md`. Первая редакция оставляла брифинг при своём
    дереве («это разные вопросы»), и замер показал, чем это кончается: из
    worktree выходило «прочитано 21, не прочитано 0», где 20 артефактов свежие
    (прод, минуты-часы), а брифинг — git-копия возрастом **1047.7 ч**, и оба
    слагаемых лежали под одним итогом. Смешанная свежесть под одним вердиктом —
    ровно тот дефект, против которого заведена эта правка, только тише.

    Манифест НЕ отсюда: конституция принадлежит дереву, которое проверяем
    (`--root`), а не тому, чьи артефакты читаем.
    """
    if data_dir:
        return os.path.join(os.path.dirname(data_dir), rel)
    return os.path.join(root, rel)


def _main_worktree(root: str) -> str | None:
    """Главное рабочее дерево — ПЕРВАЯ запись `git worktree list` (правило #234).

    Guard'ится целиком: обязательный шаг 0-офис не имеет права упасть из-за
    подсказки в тексте ошибки. Нет git / не репозиторий / что угодно ⇒ None,
    и вызывающий честно скажет «не измерено» вместо выдуманного пути.
    """
    try:
        import subprocess

        out = subprocess.run(["git", "-C", root, "worktree", "list"],
                             capture_output=True, text=True, timeout=10)
        if out.returncode != 0:
            return None
        first = (out.stdout.splitlines() or [""])[0].strip()
        path = first.split(" ")[0] if first else ""
        return path or None
    except Exception:  # noqa: BLE001
        return None


def _office_absent_wholesale(targets: list[str], *, root: str,
                             data_dir: str | None) -> list[str] | None:
    """НИ ОДНОГО артефакта офиса в этом дереве — это ОДНА находка, а не двадцать.

    Почему это отдельная ветка, а не «пусть каждый файл скажет за себя».
    Артефакты офиса пишет ЖИВОЙ флот в прод-дерево, и они в `.gitignore`;
    в git-worktree их нет ПО ПОСТРОЕНИЮ. Прежний вывод давал оттуда двадцать
    строк «❌ НЕ ПРОЧИТАН · файла нет на диске» и подпись «красные строки выше =
    действовать (карточки)». Форма — полноценная находка, текст — прямое
    требование действовать; добросовестная сессия, работающая по §3.4 в
    изолированном worktree, заводит двадцать карточек о мёртвом инвест-офисе,
    которого нет (замер цикла #207 — ровно этот вывод первым же прогоном).

    Разделяющий признак ИЗМЕРЕН, а не угадан: в worktree каталог `data/` есть
    (326 файлов, git-tracked), нет именно РАНТАЙМНЫХ артефактов офиса — поэтому
    признак «нет каталога data/» не годится, а годится «ни один из целевых
    артефактов под data/ не существует». Если хоть один есть — дерево
    производящее, и пропажа соседа это НАСТОЯЩАЯ находка, её печатаем как
    прежде, по одной строке на артефакт.

    Возвращает строки вердикта либо None (обычный ход).
    """
    data_targets = [t for t in targets if t.startswith("data/")]
    if not data_targets:
        return None
    present = [t for t in data_targets
               if os.path.exists(_resolve(t, root=root, data_dir=data_dir))]
    if present:
        return None
    where = data_dir or os.path.join(root, "data")
    main_tree = _main_worktree(root)
    # НЕ подставлять сюда REPO_ROOT: он вычисляется от расположения САМОГО
    # скрипта, то есть из worktree указывает на worktree — совет «гоняйте из
    # прод-дерева (<этот же worktree>)» это выдуманный путь. Либо называем
    # главное дерево по правилу #234 (первая запись `git worktree list`), либо
    # не называем никакого.
    how = (f"гонять шаг 0-офис из ПРОД-дерева ({main_tree}) либо передать "
           f"--data-dir {os.path.join(main_tree, 'data')}"
           if main_tree else
           "гонять шаг 0-офис из ПРОД-дерева (того, куда пишет флот) либо "
           "передать --data-dir <прод>/data; какое дерево главное — здесь НЕ "
           "измерено (`git worktree list` недоступен), путь не выдумываю")
    return [
        f"⚠️ ОФИС НЕ ИЗМЕРЕН: ни одного из {len(data_targets)} артефактов офиса нет "
        f"в этом дереве ({where}).",
        "   Это ОДНА находка, а не "
        f"{len(data_targets)}: артефакты пишет живой флот в прод-дерево, они в "
        "`.gitignore`, и в git-worktree их нет по построению.",
        "   Карточек о «мёртвом инвест-офисе» по этому выводу заводить НЕЛЬЗЯ — "
        "офис не опровергнут, он не измерен.",
        f"   Что сделать: {how}.",
    ]


def _mandate_lines(now: dt.datetime) -> list[str]:
    """Строки о действующем мандате автономии — или честное «не измерено».

    Fail-CLOSED: если модуль не читается (старое дерево, битый импорт), это НЕ
    повод молча продолжать широко. Печатаем УЗКИЙ протокол и называем причину —
    неизмеренная широта полномочий обязана читаться как отсутствие широты.
    """
    try:
        from spa_core.governance.autonomy_mandate import summary_lines
    except Exception as e:  # noqa: BLE001
        return [
            f"⏹ мандат автономии: НЕ ИЗМЕРЕН ({type(e).__name__}: {e})",
            "   режим цикла: ОДНА безопасная задача за цикл (базовый протокол) — "
            "неизмеренная широта полномочий читается как её отсутствие",
        ]
    return summary_lines(now=now)


def main(argv=None, *, now: dt.datetime | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None,
                    help="читать артефакты офиса из ЧУЖОГО дерева (обычно прод): "
                         "<прод>/data. Квитанции потребления уезжают туда же — "
                         "иначе сторож B3 доложит «офис не читают» на прочитанный офис")
    ap.add_argument("--consumer", default=CONSUMER)
    ap.add_argument("--no-receipts", action="store_true",
                    help="только чтение/печать, без квитанций (для проверок)")
    args = ap.parse_args(argv)
    now = now or dt.datetime.now(dt.timezone.utc)

    # ── Ширина собственных полномочий — ПЕРВОЙ строкой шага (ADR-101) ────────
    # Печатается ДО манифеста намеренно: «как мне сегодня работать» не должно
    # зависеть от того, читаются ли артефакты офиса. При `return 1` (нет
    # манифеста) и `return 3` (офис не измерить из этого дерева) ответ всё
    # равно уже произнесён. До ADR-101 срок мандата не знал никто: ADR-078
    # истёк 19.08, и вопрос о продлении задал ЦИКЛ РУКАМИ в последний день.
    for _ln in _mandate_lines(now):
        print(_ln)
    print()

    from spa_core.monitoring.consumption_receipts import write_receipt

    manifest_path = os.path.join(args.root, "architecture", "manifest.json")
    try:
        manifest = json.load(open(manifest_path))
    except Exception as e:  # noqa: BLE001
        print(f"❌ манифест не прочитан ({manifest_path}): {e} — шаг НЕ выполнен")
        return 1

    targets = [a["path"] for a in manifest.get("artifacts", [])
               if a.get("status") == "active" and args.consumer in (a.get("consumers") or [])]
    if not targets:
        print(f"❌ в манифесте нет active-артефактов с потребителем {args.consumer!r} — "
              f"проверить конституцию")
        return 1

    # Куда пишутся квитанции: они отвечают на вопрос «офис ЧИТАЮТ?» (B3), поэтому
    # обязаны лечь в то дерево, чьи артефакты прочитаны. Квитанция о прод-офисе,
    # осевшая в одноразовом worktree, исчезнет вместе с ним, и сторож честно
    # доложит «не читают» про прочитанное — fail-OPEN наизнанку.
    data_dir = os.path.abspath(args.data_dir) if args.data_dir else None
    receipt_root = os.path.dirname(data_dir) if data_dir else args.root

    print(f"— офис и сторожа → контекст оркестратора ({len(targets)} артефактов) —")
    if data_dir:
        print(f"— артефакты офиса читаются ИЗ ЧУЖОГО ДЕРЕВА: {data_dir} "
              f"(квитанции туда же: {receipt_root}) —")

    absent = _office_absent_wholesale(targets, root=args.root, data_dir=data_dir)
    if absent is not None:
        for ln in absent:
            print(ln)
        print("— итог: офис НЕ ИЗМЕРЕН (0 прочитано). Это НЕ «всё хорошо» и НЕ "
              "находка о состоянии офиса — измерять нечем из этого дерева. —")
        return 3

    consumed = failed = hollow = 0
    for rel in sorted(targets):
        full = _resolve(rel, root=args.root, data_dir=data_dir)
        lines: list[str]
        ok = False
        if not os.path.exists(full):
            lines = ["   файла нет на диске"]
        elif rel.endswith(".json"):
            try:
                lines = _summarize_json(rel, json.load(open(full)), now=now,
                                        artifact_root=receipt_root)
                ok = True
            except Exception as e:  # noqa: BLE001
                lines = [f"   JSON не прочитан: {e}"]
        else:
            lines = _summarize_md(full, now=now)
            ok = bool(lines) and not any(
                ln.startswith("   (md не прочитан") for ln in lines)
        if ok and any(ln.startswith(_HOLLOW_MARK) for ln in lines):
            # Ресит НЕ пишется: см. `_HOLLOW_MARK`. Файл открылся и разобрался
            # как JSON — но прочитано из него не было ничего, и утверждать
            # обратное значит кормить проверку B3 собственным эхом.
            mark = "⚠️ ПРОЧИТАН ВХОЛОСТУЮ (ресит НЕ пишется)"
            hollow += 1
        elif ok:
            receipted = True if args.no_receipts else write_receipt(
                rel, args.consumer, root=receipt_root)
            mark = "✅" if receipted else "⚠️ (ресит НЕ записан)"
            consumed += 1
        else:
            mark = "❌ НЕ ПРОЧИТАН"
            failed += 1
        print(f"{mark} {rel}")
        for ln in lines:
            print(ln)
    # Клауза о вхолостую ДОПИСЫВАЕТСЯ, а не переписывает итог: в здоровом
    # состоянии (hollow=0) строка та же, что и была, — соседние тесты сверяют её
    # дословно, и ослаблять их ради нового счётчика было бы нечестно.
    hollow_clause = (f", ⚠️ ВХОЛОСТУЮ {hollow} (разобрать нечем, ресит не "
                     f"записан — артефакт объявлен читаемым, а прочитано "
                     f"ничего)" if hollow else "")
    print(f"— итог: прочитано {consumed}{hollow_clause}, не прочитано {failed}. "
          f"Красные строки выше = действовать (карточки), это не декорация. —")
    return 0


if __name__ == "__main__":
    sys.exit(main())
