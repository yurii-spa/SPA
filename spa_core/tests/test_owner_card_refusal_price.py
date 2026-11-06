"""Карточка владельцу обязана нести ИЗМЕРЕННУЮ цену отказа, а совет — её знать.

Положительный контроль — авария 2026-11-06 (цикл #1045), воспроизведённая целиком.
`scripts/safe_site_push.py` печатал в карточке `Отклонить (рекомендую)` КОНСТАНТОЙ и
описывал последствие отказа словами «owner-gated поверхность остаётся неизменной».
Замер того дня: живая `/track-record/` несла `as of 2026-10-21` (383 ч, 120 дней трека),
витрина, собранная прибором 29.10, ждала ответа СЕДЬМОЙ день, а сторож
`com.spa.site_freshness` выходил кодом 1 каждые шесть часов и причину называл верно
(`SHELF_NOT_DELIVERED`). То есть совет рекомендовал ровно то, что заморозило публичные
числа, и цену этого владельцу не называл — ни в одну сторону.

Предмет здесь НЕ «какое решение верно»: публичные числа остаются предметом №2 границы
ADR-285 и решаются владельцем. Предмет — что КАРТОЧКА несёт цену, а рекомендация без
измеренной цены не печатается вовсе (инв. #17: измерено · измерено и равно нулю ·
НЕ ИЗМЕРЕНО).

**Контракт УЖЕ прежнего, и это нашёл сторож, а не автор.** Первая редакция двери
советовала «Одобрить» там, где отказ стои́т дорого, и покраснела у
`test_safe_site_push_card_options.py::test_the_safe_option_is_the_recommended_one`:
карточка едет владельцу КНОПКАМИ, и совет «одобрить» значит, что owner-gated числа
уезжают в live ОДНИМ ТАПОМ (инв. #8). Сторож был прав; лечение — не ослабление
сторожа, а сужение контракта до ``recommend ∈ {"refuse", None}``. Совет «Одобрить»
не возвращается НИКОГДА, и это закреплено ниже отдельной проверкой.

FROZEN-DATE-OK: injected-clock — якорь сцены `_ANCHOR` (литерал) связывается с именем,
от него происходят и отметка отчёта `ts`, и момент суждения, который передаётся
`_price_of_refusing(..., now=…)` аргументом. Стенных часов ни одна сцена не спрашивает.
"""
# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — якорь сцены `_ANCHOR` (литерал) связывается с
# именем, и от него происходят ОБЕ стороны каждого сравнения: отметка отчёта
# сторожа (`_report()['ts'] = _ANCHOR - 2ч`) и момент суждения, который уезжает
# в `_price_of_refusing(..., now=…)` аргументом. Стенных часов не спрашивает ни
# одна сцена: умолчание `now=None` в этом файле не используется нигде.
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_PUSHER = _REPO / "scripts" / "safe_site_push.py"

#: Якорь сцены. От него происходит ВСЁ время в этом файле (см. FROZEN-DATE-OK выше).
_ANCHOR = dt.datetime(2026, 11, 6, 1, 0, 0, tzinfo=dt.timezone.utc)

#: Объявленный срок годности отчёта сторожа. Сцена объявляет его САМА (минимальный
#: манифест), чтобы мерить ДВЕРЬ, а не сегодняшнее содержимое конституции; что
#: конституция и правда его объявляет, проверяет отдельный тест ниже.
_SLO_H = 13


def _module():
    spec = importlib.util.spec_from_file_location("ssp_under_test", _PUSHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _scene(tmp_path: Path, *, report: dict | None, slo_hours: object = _SLO_H) -> Path:
    """Одноразовый корень: отчёт сторожа + манифест, объявляющий его срок годности."""
    root = tmp_path / "scene"
    (root / "data").mkdir(parents=True)
    (root / "architecture").mkdir(parents=True)
    manifest: dict = {"artifacts": [], "agents": []}
    if slo_hours is not None:
        manifest["artifacts"].append(
            {"path": "data/site_freshness_report.json",
             "producer": "com.spa.site_freshness", "slo_hours": slo_hours})
    (root / "architecture" / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8")
    if report is not None:
        (root / "data" / "site_freshness_report.json").write_text(
            json.dumps(report), encoding="utf-8")
    return root


def _report(**over) -> dict:
    """Отчёт сторожа ровно той формы, что был снят 2026-11-05T23:05:52Z."""
    doc = {
        "ts": (_ANCHOR - dt.timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
        "ok": False,
        "fails": [{"code": "SHELF_NOT_DELIVERED", "severity": "CRITICAL"}],
        "site_as_of": "2026-10-21",
        "site_as_of_age_h": 383.1,
        "shelf_as_of": "2026-10-21",
        "shelf_overdue_days": 7,
        "shelf_built_not_delivered": True,
        "shelf_cadence_leg": "measured",
    }
    doc.update(over)
    return doc


def _price(root: Path, approves: list[str], *, now: dt.datetime | None = None):
    return _module()._price_of_refusing(approves, root=root, now=now or _ANCHOR)


def _shelf(mod=None) -> str:
    return (mod or _module())._SHELF_REL


# ── 1. Авария 2026-11-06, воспроизведённая: цена ЕСТЬ и она не ноль ───────────

def test_non_zero_price_is_measured_and_named(tmp_path):
    mod = _module()
    outcome, lines, recommend = mod._price_of_refusing(
        [mod._SHELF_REL], root=_scene(tmp_path, report=_report()), now=_ANCHOR)
    assert outcome == "measured"
    text = "\n".join(lines)
    # Числа НАЗВАНЫ — именно их отсутствие и было аварией.
    assert "2026-10-21" in text, text
    assert "383" in text, text
    assert "7 дн" in text, text


def test_non_zero_price_gives_no_recommendation_and_says_why_in_both_directions(tmp_path):
    """Дорогой отказ ⇒ совета НЕТ, и названы ОБЕ причины, почему его нет."""
    mod = _module()
    outcome, lines, recommend = mod._price_of_refusing(
        [mod._SHELF_REL], root=_scene(tmp_path, report=_report()), now=_ANCHOR)
    assert outcome == "measured"
    assert recommend is None
    text = "\n".join(lines)
    assert "не рекомендую здесь ни один вариант" in text.lower(), text
    assert "#8" in text, text                 # почему не «одобрить»
    assert "заморозку" in text, text          # почему не «отклонить»


def test_the_door_never_recommends_approving(tmp_path):
    """Инв. #8, закреплённый ЗНАЧЕНИЕМ: карточка едет кнопками.

    Положительный контроль сторожа `test_safe_site_push_card_options.py`: совет
    «одобрить» означал бы публикацию owner-gated чисел одним тапом с телефона.
    Проверяются ВСЕ сцены двери, а не одна.
    """
    mod = _module()
    scenes = [
        ([mod._SHELF_REL], _report()),
        ([mod._SHELF_REL], _report(shelf_built_not_delivered=False,
                                   shelf_overdue_days=0)),
        ([mod._SHELF_REL], _report(shelf_cadence_leg="unmeasured")),
        (["landing/src/pages/index.astro"], _report()),
    ]
    for n, (approves, report) in enumerate(scenes):
        _, lines, recommend = mod._price_of_refusing(
            approves, root=_scene(tmp_path / f"s{n}", report=report), now=_ANCHOR)
        assert recommend in ("refuse", None), (n, recommend)
        assert "Рекомендация: **Одобрить**" not in "\n".join(lines), (n, lines)


def test_the_marker_on_the_option_line_is_derived_not_constant(tmp_path):
    """Пометка «(рекомендую)» ПРОИЗВОДНАЯ — две сцены, вердикты друг против друга.

    Пометка обязана стоять ИМЕННО в строке варианта: `parse_options` ставит
    владельцу звезду у рекомендованной КНОПКИ, и совет, живущий только в прозе
    ниже, до кнопок не доходит (сторож `test_safe_site_push_card_options.py` —
    он и поймал первую редакцию этого цикла). Поэтому мерится не исходник, а
    РАЗНИЦА поведения: где отказ безопасен — пометка есть; где он стои́т
    шестнадцать дней публичных чисел — её нет.

    Первая редакция этой проверки читала ИСХОДНИК («в печатаемых строках нет
    слова рекомендую») и стала неверна по построению, как только пометка стала
    производной: в источнике теперь обе ветки. Замена объявлена здесь и в
    журнале (инв. #16).
    """
    mod = _module()

    def option_two(approves, report, label):
        body = "\n".join(mod._card_lines(
            approves,
            [{"klass": "P", "file": approves[0], "rule": "publication.gate",
              "matched_text": "x"}],
            approves, "m",
            root=_scene(tmp_path / label, report=report), now=_ANCHOR))
        line = [ln for ln in body.splitlines()
                if ln.lstrip().startswith("2.") and "Отклонить" in ln]
        assert line, body
        return line[0]

    safe = option_two(["landing/src/pages/index.astro"], _report(), "safe")
    costly = option_two([mod._SHELF_REL], _report(), "costly")
    assert "рекоменд" in safe.lower(), safe
    assert "рекоменд" not in costly.lower(), costly


def test_refusal_consequence_no_longer_claims_the_surface_stays_unchanged(tmp_path):
    """Мерится ПРЕТЕНЗИЯ, а не соседнее слово.

    Первая редакция этого теста утверждала одно, а проверяла другое: она искала
    слово «ОТСТАЁТ» и пропускала мутанта, который возвращал ложную претензию
    «Поверхность остаётся неизменной.» и оставлял «ОТСТАЁТ» в той же фразе
    (мутация M7, выжила). Поэтому проверяется ровно то, что заявлено: фраза про
    неизменность допустима ТОЛЬКО как цитата под отрицанием.
    """
    mod = _module()
    _, lines, _ = mod._price_of_refusing(
        [mod._SHELF_REL], root=_scene(tmp_path, report=_report()), now=_ANCHOR)
    text = "\n".join(lines)
    assert "ОТСТАЁТ" in text, text
    claim = "поверхность остаётся неизменной"
    for match in re.finditer(claim, text, flags=re.IGNORECASE):
        before = text[max(0, match.start() - 4):match.start()]
        assert "НЕ «" in before, (
            "фраза про неизменность напечатана как ПРЕТЕНЗИЯ, а не как "
            "отрицаемая цитата: " + text[max(0, match.start() - 60):match.end() + 20])


# ── 2. Обратное направление: цена измерена и равна НУЛЮ ───────────────────────

def test_zero_price_is_distinguishable_and_recommends_refusing(tmp_path):
    """«Измерено и равно нулю» — самостоятельный исход, а не частный случай замера."""
    mod = _module()
    root = _scene(tmp_path, report=_report(
        shelf_built_not_delivered=False, shelf_overdue_days=0))
    outcome, lines, recommend = mod._price_of_refusing(
        [mod._SHELF_REL], root=root, now=_ANCHOR)
    assert outcome == "measured_zero"
    assert recommend == "refuse"
    assert "ноль, и это измерено" in "\n".join(lines)


# ── 3. НЕ ИЗМЕРЕНО: причина названа, рекомендации НЕТ ─────────────────────────

@pytest.mark.parametrize("name,report,slo,approves,needle", [
    ("отчёта нет", None, _SLO_H, None, "нет в дереве"),
    ("срок не объявлен", _report(), None, None, "не объявлен либо оспорен"),
    ("нет отметки", _report(ts=None), _SLO_H, None, "нет отметки"),
    ("отметка не разбирается", _report(ts="вчера"), _SLO_H, None, "не разбирается"),
    ("такт не измерен", _report(shelf_cadence_leg="unmeasured"), _SLO_H, None,
     "такт витрины неизмеренным"),
])
def test_unmeasured_price_names_its_reason_and_gives_no_advice(
        tmp_path, name, report, slo, approves, needle):
    mod = _module()
    root = _scene(tmp_path, report=report, slo_hours=slo)
    outcome, lines, recommend = mod._price_of_refusing(
        approves or [mod._SHELF_REL], root=root, now=_ANCHOR)
    text = "\n".join(lines)
    assert outcome == "unmeasured", (name, outcome, text)
    assert recommend is None, (name, recommend)
    assert needle in text, (name, text)
    # Главное: совета нет ВООБЩЕ — иначе «не измерено» снова стало бы советом.
    assert "Рекомендация:" not in text, (name, text)


def test_an_edit_without_the_shelf_falls_back_to_refusing_WITH_a_reason(tmp_path):
    """Безопасное умолчание остаётся, но у него теперь есть ПРИЧИНА, а не привычка.

    Это и есть то, чего требует сторож `test_safe_site_push_card_options.py`:
    разовая правка страницы ничего не замораживает, поэтому отказ здесь —
    безопасное умолчание по инв. #8, и так и сказано.
    """
    mod = _module()
    outcome, lines, recommend = mod._price_of_refusing(
        ["landing/src/pages/index.astro"],
        root=_scene(tmp_path, report=_report()), now=_ANCHOR)
    text = "\n".join(lines)
    assert outcome == "unmeasured", text
    assert recommend == "refuse", recommend
    assert "в этой правке нет" in text, text
    assert "Рекомендация: **Отклонить**" in text, text
    assert "#8" in text, text


def test_a_stale_watchdog_report_is_not_a_measurement(tmp_path):
    """Отчёт старше объявленного срока — замер ДРУГОГО дня, а не этот ответ."""
    mod = _module()
    root = _scene(tmp_path, report=_report())
    fresh = mod._price_of_refusing([mod._SHELF_REL], root=root, now=_ANCHOR)
    late = mod._price_of_refusing(
        [mod._SHELF_REL], root=root,
        now=_ANCHOR + dt.timedelta(hours=_SLO_H + 1))
    assert fresh[0] == "measured"
    assert late[0] == "unmeasured", late
    assert "замер ДРУГОГО дня" in "\n".join(late[1])
    assert late[2] is None


@pytest.mark.parametrize("field", [
    "site_as_of", "site_as_of_age_h", "shelf_overdue_days",
    "shelf_built_not_delivered",
])
def test_an_absent_observation_is_not_a_zero(tmp_path, field):
    """Инв. #17 у КАЖДОГО операнда цены: поля нет ⇒ НЕ ИЗМЕРЕНО, не ноль."""
    mod = _module()
    doc = _report()
    doc.pop(field)
    outcome, lines, recommend = mod._price_of_refusing(
        [mod._SHELF_REL], root=_scene(tmp_path, report=doc), now=_ANCHOR)
    assert outcome == "unmeasured", (field, outcome)
    assert recommend is None
    assert field in "\n".join(lines), (field, lines)


# ── 3б. КНОПКИ: звезда владельца не имеет права уехать не туда ───────────────

def test_the_star_goes_to_refusing_or_nowhere_never_elsewhere(tmp_path):
    r"""Разбор кнопок — ВТОРОЙ читатель этого текста, и он ошибся на первой правке.

    `owner_decisions.parse_options` вычитает отрицание шаблоном
    ``\bне\s+рекоменд\w*``. Фраза «Рекомендации здесь нет» под него НЕ
    попадает, поэтому слово «рекомендац» в блоке цены досталось ХВОСТУ
    последнего варианта, и звезда уехала «Отложить» — подсказка владельцу
    перевернулась. Лечено НЕ правкой чужого сторожа, а формулировкой, которую
    он понимает; закреплено здесь ЗНАЧЕНИЕМ.
    """
    from spa_core.telegram.owner_decisions import parse_options

    mod = _module()

    def stars(approves, report, label):
        body = "\n".join(mod._card_lines(
            approves,
            [{"klass": "P", "file": approves[0], "rule": "publication.gate",
              "matched_text": "x"}],
            approves, "m",
            root=_scene(tmp_path / label, report=report), now=_ANCHOR))
        return {o.label.lower(): o.recommended for o in parse_options(body)}

    costly = stars([mod._SHELF_REL], _report(), "costly")
    safe = stars(["landing/src/pages/index.astro"], _report(), "safe")

    assert costly, "кнопок нет вовсе — это другая поломка"
    assert not any(costly.values()), (
        "у дорогого отказа рекомендации нет, а звезда кому-то досталась: " + repr(costly))
    assert safe.get("отклонить") is True, repr(safe)
    assert safe.get("одобрить") is False, repr(safe)
    assert safe.get("отложить") is False, repr(safe)


# ── 4. Проводка: функция есть — и её ЗОВЁТ сборщик карточки ───────────────────

@pytest.mark.parametrize("caller,callee", [
    ("_route_to_owner_card", "_card_lines"),
    ("_card_lines", "_price_of_refusing"),
])
def test_the_chain_from_the_router_to_the_price_door_is_whole(caller, callee):
    """Половина починки — функция без читателя. Цепь двухзвенная, мерится AST."""
    import ast

    tree = ast.parse(_PUSHER.read_text(encoding="utf-8"))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == caller), None)
    assert fn is not None, f"{caller} переименован — перемерить проводку"
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert callee in called, (caller, callee, sorted(called))


def test_the_card_text_itself_carries_the_measured_price(tmp_path):
    """Предмет приёмки — ТЕКСТ, который читает владелец, а не только дверь."""
    mod = _module()
    body = "\n".join(mod._card_lines(
        ["landing/src/data/site_numbers.json"],
        [{"klass": "P", "file": mod._SHELF_REL, "rule": "publication.gate",
          "matched_text": "backtest value changed"}],
        [mod._SHELF_REL], "chore(site numbers): weekly shelf",
        root=_scene(tmp_path, report=_report()), now=_ANCHOR))
    assert "2026-10-21" in body, body
    assert "383" in body, body
    # Строка варианта «Отклонить» не несёт совета — он живёт у измеренной цены.
    option = [ln for ln in body.splitlines()
              if ln.lstrip().startswith("2.") and "Отклонить" in ln]
    assert option, body
    assert not any("рекоменд" in ln.lower() for ln in option), option
    assert "Рекомендация: **Одобрить**" not in body, body
    for match in re.finditer("поверхность остаётся неизменной", body,
                             flags=re.IGNORECASE):
        assert "НЕ «" in body[max(0, match.start() - 4):match.start()], body


def test_the_card_text_says_unmeasured_when_the_price_is_unmeasured(tmp_path):
    """Цена не измерена ⇒ сказано вслух; совет остаётся безопасным и с причиной."""
    mod = _module()
    body = "\n".join(mod._card_lines(
        ["landing/src/pages/index.astro"],
        [{"klass": "P", "file": "landing/src/pages/index.astro",
          "rule": "legal.copy", "matched_text": "whatever"}],
        ["landing/src/pages/index.astro"], "fix(site): copy",
        root=_scene(tmp_path, report=_report()), now=_ANCHOR))
    assert "НЕ ИЗМЕРЕНО" in body, body
    assert "Рекомендация: **Отклонить**" in body, body
    assert "Рекомендация: **Одобрить**" not in body, body


def test_the_card_text_gives_no_recommendation_when_refusing_is_costly(tmp_path):
    """Дорогой отказ ⇒ в ТЕЛЕ карточки совета нет, и сказано почему."""
    mod = _module()
    body = "\n".join(mod._card_lines(
        ["landing/src/data/site_numbers.json"],
        [{"klass": "P", "file": mod._SHELF_REL, "rule": "publication.gate",
          "matched_text": "backtest value changed"}],
        [mod._SHELF_REL], "chore(site numbers): weekly shelf",
        root=_scene(tmp_path, report=_report()), now=_ANCHOR))
    assert "не рекомендую здесь ни один вариант" in body.lower(), body
    assert "Рекомендация: **Одобрить**" not in body, body
    assert "Рекомендация: **Отклонить**" not in body, body


def test_the_threshold_has_no_second_home_in_the_pusher():
    """Срок годности отчёта берётся у объявления, а не литералом рядом."""
    src = _PUSHER.read_text(encoding="utf-8")
    assert "declared_slo_hours" in src
    # Свой литерал порога в часах рядом с ценой был бы вторым домом — тот самый
    # класс «два срока», который шаг 0-офис печатает находкой каждый цикл.
    assert "_PRICE_REPORT_MAX_AGE_H" not in src


def test_the_constitution_really_declares_the_watchdog_report_slo():
    """Сцены объявляют срок сами; здесь спрашивается НАСТОЯЩАЯ конституция."""
    from spa_core.monitoring.rebalance_cost_evidence import declared_slo_hours

    def _read(path: str):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    hours, provenance = declared_slo_hours(
        str(_REPO), _read, "data/site_freshness_report.json")
    assert hours is not None, provenance
    assert hours > 0, (hours, provenance)
    assert "site_freshness" in provenance, provenance
