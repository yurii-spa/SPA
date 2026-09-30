"""test_site_number_operand_page.py — с КАКОЙ страницы взят операнд сверки (заказ G86 п. 1).

Заказ поставлен ADR-475 (25.09) и с тех пор лежал остатком, перевыставленный
шестнадцатью заказами подряд. Его предмет назван в самом ADR-475: «Сверка ДНЕЙ у
кустодиана слепа на той странице, где число есть».

ЗАМЕР 30.09, живым запросом к earn-defi.com, а не чтением исходников:

| что ищет сторож | что на главной | что на /track-record |
|---|---|---|
| `sl-day`   | элемента НЕТ | — |
| `sl-apy`   | элемента НЕТ | — |
| `sl-gates` | элемента НЕТ | — |
| —          | `m-days`=96, `m-apy`=~4.9%, `m-gates`=29/29 | `tr-days-2`=96, `tr-apy`=~4.9%, `tr-equity`=$101,425 |

В `landing/src/pages/index.astro` от трёх `sl-*` остались только вызовы
`setText('sl-day', …)`, а `setText` защищён `if(el)` и потому молча не делает ничего.
Итог в отчёте кустодиана до правки: `site_home = {evidenced_days: null,
paper_apy_pct: null, gates_passed: null, end_equity: null}` — и обе сверки `cmp_int`,
получая `None`, пропускались БЕЗ СЛЕДА. «Не измерено» было неотличимо от «равно»
(инв. #17), а прогон объявлялся чистым (`ok: true, n_fails: 0` — замер 30.09 на живых
входах).

ОДНОСТОРОННОСТЬ НАЗВАНА ЗАРАНЕЕ. Сторож читает серверный HTML через urllib:
  · число НАЙДЕНО   ⇒ страница его несёт — утверждение сильное;
  · число НЕ найдено ⇒ доказано только то, что сторож его отсюда не видит. Посетитель
    может видеть его прекрасно — `/track-record` отдаёт `id="tr-gates-pass">—</span>`
    и дорисовывает `29` клиентом.
Поэтому ненайденное число НИКОГДА не читается ни как «равно», ни как «на сайте числа
нет»: это третий исход, и он громкий.

Каждый тест ниже — либо положительный контроль на сцену 25.09 (89 на сайте против 94
в витрине, не пойманные сверкой дней), либо контроль в обратную сторону: объявление
источника НЕ ИМЕЕТ ПРАВА погасить настоящее расхождение, выдать заглушку за число или
объявить измеренным то, чего не видел.
"""
# FROZEN-DATE-OK: injected-clock — якорь NOW уходит входом в evaluate(now=NOW), и все
# даты фикстур вычисляются ОТ НЕГО арифметикой timedelta (`_day`); стенных часов в
# файле нет ни одного вызова.
import datetime
import importlib.util
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "site_freshness_monitor", _ROOT / "scripts" / "site_freshness_monitor.py")
mon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mon)

NOW = datetime.datetime(2026, 9, 25, 17, 6, 0, tzinfo=datetime.timezone.utc)
PIN = "c" * 64


def _day(days_ago=0):
    return (NOW - datetime.timedelta(days=days_ago)).date().isoformat()


# ── фикстуры: форма разметки, ИЗМЕРЕННАЯ на живом сайте 30.09 ────────────────
def _home(asof, *, days=94, apy="4.9", gates=29, legacy=False):
    """Главная. `legacy=True` — разметка ДО перехода на `m-*` (её несёт старая сборка
    на CDN, и сторож обязан читать и её: вопрос задан живому сайту, а не исходникам)."""
    pre = "sl" if legacy else "m"
    ids = {"days": f"{pre}-day" if legacy else "m-days",
           "apy": f"{pre}-apy" if legacy else "m-apy",
           "gates": f"{pre}-gates" if legacy else "m-gates"}
    parts = [f'<span class="src" id="sl-asof">as of {asof}</span>']
    if days is not None:
        parts.append(f'<div class="val" id="{ids["days"]}">{days}</div>')
    if apy is not None:
        parts.append(f'<div class="val teal" id="{ids["apy"]}">~{apy}%</div>')
    if gates is not None:
        parts.append(f'<div class="val" id="{ids["gates"]}">{gates}/29</div>')
    return "".join(parts)


def _track(asof, *, days=94, apy="4.9", equity="101,425", gates_placeholder=True):
    parts = [f'<p id="tr-equity">${equity}</p>', f'<p id="tr-apy">~{apy}%</p>',
             f'<span id="tr-days-2">{days}</span>' if days is not None else "",
             f'<p id="tr-asof">static snapshot as of {asof}</p>']
    if gates_placeholder:
        # ровно как в landing/src/pages/track-record.astro:301 — заглушка, которую
        # заполняет JS; серверный HTML несёт её, а не число
        parts.append('<span id="tr-gates-pass">&mdash;</span>')
    return "".join(parts)


def _snap(asof, days=94, apy=4.9386, gates=29):
    return {"as_of": asof, "real_track_days": days, "paper_apy_pct": apy,
            "gates_passed": gates, "end_equity": 101401.72}


def _shelf(measured, *, days=94, gates=29, apy=4.9386, next_pub=None):
    return {"measured_at": measured, "published_at": measured, "cadence": "weekly",
            "next_publication": next_pub if next_pub is not None else _day(-2),
            "headline": {"apy": {"value": apy}, "evidenced_days": {"value": days},
                         "gates": {"passed": gates, "total": 29}}}


def _api(days=94, apy=4.9386):
    return {"evidenced_days": days, "paper_apy_pct": apy, "gates_passed": 29,
            "end_equity": 101401.72, "last_bar": _day(0), "apy_source": "evidenced_chain"}


def _ev(*, home_html=None, track_html=None, shelf=None, snap_asof=None, api=None):
    asof = snap_asof or _day(0)
    return mon.evaluate(
        snapshot=_snap(asof),
        home_html=_home(asof) if home_html is None else home_html,
        track_html=_track(asof) if track_html is None else track_html,
        api=api if api is not None else _api(),
        sitemap_statuses={"https://earn-defi.com/": 200},
        verifier_sha=PIN, pin_sha=PIN, now=NOW, prev_report=None,
        site_numbers=_shelf(asof) if shelf is None else shelf)


def _codes(r):
    return [f["code"] for f in r["fails"]]


def _detail(r, code):
    return [f["detail"] for f in r["fails"] if f["code"] == code]


# ── положительный контроль: сцена 25.09, которую сверка дней не поймала ───────
def test_the_day_divergence_of_25_09_is_caught_on_the_page_that_carries_the_number():
    """89 на сайте против 94 в витрине. Число есть только на /track-record — сторож
    обязан взять операнд ОТТУДА, а не молчать из-за главной."""
    asof = _day(5)
    r = _ev(home_html=_home(asof, days=None, apy=None, gates=None),
            track_html=_track(asof, days=89), snap_asof=asof,
            shelf=_shelf(_day(0), days=94))
    behind = _detail(r, "SITE_BEHIND_SNAPSHOT")
    days_hit = [d for d in behind if "evidenced_days" in d]
    assert len(days_hit) == 1, behind
    assert "89" in days_hit[0] and "94" in days_hit[0]
    # и операнд НАЗЫВАЕТ свою страницу и свой id — иначе на вопрос заказа не ответить
    assert "track#tr-days-2" in days_hit[0], days_hit[0]
    assert r["number_legs"]["evidenced_days"] == "measured:track#tr-days-2=89"


def test_the_same_divergence_is_caught_when_the_number_sits_on_the_home_page():
    """Зеркальная сцена: число на главной под нынешним id `m-days`. До 30.09 сторож
    искал на ней `sl-day`, которого в разметке нет вовсе."""
    asof = _day(5)
    r = _ev(home_html=_home(asof, days=89), track_html=_track(asof, days=None),
            snap_asof=asof, shelf=_shelf(_day(0), days=94))
    days_hit = [d for d in _detail(r, "SITE_BEHIND_SNAPSHOT") if "evidenced_days" in d]
    assert len(days_hit) == 1, _codes(r)
    assert "home#m-days" in days_hit[0], days_hit[0]


def test_the_legacy_ids_of_an_old_cdn_build_are_still_read():
    """Вопрос задан ЖИВОМУ САЙТУ, а не текущим исходникам: застрявшая сборка несёт
    `sl-day`, и молчать о ней значило бы ослепнуть ровно там, где отставание и живёт."""
    asof = _day(5)
    r = _ev(home_html=_home(asof, days=89, legacy=True), track_html=_track(asof, days=None),
            snap_asof=asof, shelf=_shelf(_day(0), days=94))
    days_hit = [d for d in _detail(r, "SITE_BEHIND_SNAPSHOT") if "evidenced_days" in d]
    assert len(days_hit) == 1, _codes(r)
    assert "home#sl-day" in days_hit[0], days_hit[0]


def test_a_divergence_on_one_page_is_not_silenced_by_agreement_on_the_other():
    """Опрашиваются ВСЕ объявленные страницы. «На одной сошлось» не есть ответ про другую."""
    asof = _day(5)
    r = _ev(home_html=_home(asof, days=94), track_html=_track(asof, days=89),
            snap_asof=asof, shelf=_shelf(_day(0), days=94))
    days_hit = [d for d in _detail(r, "SITE_BEHIND_SNAPSHOT") if "evidenced_days" in d]
    assert len(days_hit) == 1, days_hit
    assert "track#tr-days-2" in days_hit[0]
    assert "home#m-days=94" in r["number_legs"]["evidenced_days"]


# ── третий исход: не найдено ≠ равно ──────────────────────────────────────────
def test_a_comparison_without_an_operand_is_loud_not_silent():
    """Дословно прежнее состояние главной: ни одного числа. Прежний код молчал и
    объявлял прогон чистым; теперь это НАЗВАННЫЙ третий исход."""
    asof = _day(0)
    r = _ev(home_html=_home(asof, days=None, apy=None, gates=None),
            track_html=_track(asof, days=None, gates_placeholder=False), snap_asof=asof)
    assert "COMPARISON_NOT_MEASURED" in _codes(r)
    assert r["ok"] is False
    leg = r["number_legs"]["evidenced_days"]
    assert leg.startswith("unmeasured:site:"), leg


def test_the_third_outcome_names_every_declared_source_and_its_fate():
    """След обязан перечислить ВСЕ объявленные источники — иначе «с какой страницы»
    снова остаётся без ответа, только теперь под словом «не измерено»."""
    asof = _day(0)
    r = _ev(home_html=_home(asof, days=None, apy=None, gates=None),
            track_html=_track(asof, days=None, gates_placeholder=False), snap_asof=asof)
    leg = r["number_legs"]["evidenced_days"]
    for page, elem_id, _pat, _why in mon.SITE_NUMBER_SOURCES["evidenced_days"]:
        assert f"{page}#{elem_id}" in leg, (page, elem_id, leg)


def test_not_found_is_never_reported_as_agreement():
    """Сцена, где сайт РЕАЛЬНО отстал, но числа не видно: вердикт обязан остаться
    «не измерено», а не превратиться в зелёный."""
    asof = _day(5)
    r = _ev(home_html=_home(asof, days=None, apy=None, gates=None),
            track_html=_track(asof, days=None, gates_placeholder=False),
            snap_asof=asof, shelf=_shelf(_day(0), days=94))
    assert "COMPARISON_NOT_MEASURED" in _codes(r)
    assert not [d for d in _detail(r, "SITE_BEHIND_SNAPSHOT") if "evidenced_days" in d]
    assert r["number_legs"]["evidenced_days"].startswith("unmeasured:site:")


def test_a_placeholder_is_a_different_outcome_from_a_missing_id():
    """`tr-gates-pass` отдаётся строкой `—` и заполняется клиентом. Свалить это в
    «id отсутствует» значило бы стереть единственную улику, что число там ЕСТЬ."""
    hits, probes = mon.locate_site_number(
        "gates_passed", {"home": "<div class=\"val\">29/29</div>",
                         "track": '<span id="tr-gates-pass">&mdash;</span>'})
    assert hits == []
    fate = {f"{p}#{i}": leg for p, i, leg in probes}
    assert fate["track#tr-gates-pass"] == mon.SOURCE_LEG_PLACEHOLDER
    assert fate["home#m-gates"] == mon.SOURCE_LEG_ID_ABSENT
    assert mon.SOURCE_LEG_PLACEHOLDER != mon.SOURCE_LEG_ID_ABSENT


def test_a_page_that_was_never_fetched_is_its_own_outcome():
    """«Страницу не скачали» и «на странице нет id» — разные беды с разными лекарствами."""
    _hits, probes = mon.locate_site_number("evidenced_days", {"track": '<span id="tr-days-2">96</span>'})
    fate = {f"{p}#{i}": leg for p, i, leg in probes}
    assert fate["home#m-days"] == "unmeasured:page_not_fetched"
    assert fate["track#tr-days-2"] == mon.SOURCE_LEG_MEASURED


def test_the_shelf_side_of_the_comparison_has_its_own_third_outcome():
    """У сверки ДВА операнда. Отсутствие второго — тоже «не измерено», и сказано,
    что молчит именно ВИТРИНА, а не сайт."""
    asof = _day(0)
    shelf = _shelf(asof)
    shelf["headline"]["evidenced_days"] = {}
    r = _ev(snap_asof=asof, shelf=shelf)
    got = _detail(r, "COMPARISON_NOT_MEASURED")
    assert any("evidenced_days" in d and "ВИТРИН" in d.upper() for d in got), got
    assert r["number_legs"]["evidenced_days"].startswith("unmeasured:shelf_has_no_value|")


# ── контроли в обратную сторону ───────────────────────────────────────────────
def test_numbers_that_agree_produce_no_finding_and_name_their_page():
    asof = _day(0)
    r = _ev(snap_asof=asof)
    assert not [d for d in _detail(r, "SITE_BEHIND_SNAPSHOT") if "evidenced_days" in d]
    assert "COMPARISON_NOT_MEASURED" not in _codes(r), _codes(r)
    assert r["number_legs"] == {"evidenced_days": "measured:home#m-days=94, track#tr-days-2=94",
                                "gates_passed": "measured:home#m-gates=29"}


def test_the_home_parser_no_longer_borrows_an_id_from_the_track_page():
    """Регрессия ровно того дефекта: `parse_site_numbers` брала `tr-days-2` вторым
    вариантом и на ГЛАВНОЙ тоже — порядок `or` внутри парсера решал, чья это страница."""
    track_only = '<span id="tr-days-2">96</span>'
    assert mon.parse_site_numbers(track_only, page="home").get("evidenced_days") is None
    assert mon.parse_site_numbers(track_only, page="track").get("evidenced_days") == 96.0


def test_the_as_of_label_is_still_read_on_both_pages():
    """Объявление источников чисел не имеет права тронуть метку `as of` — именно она
    поймала аварию 25.09, когда сверка дней молчала."""
    assert mon.parse_site_numbers('<span>as of 2026-09-20</span>', page="home")["as_of"] == "2026-09-20"
    assert mon.parse_site_numbers(
        '<p>static snapshot as of 2026-09-20</p>', page="track")["as_of"] == "2026-09-20"


def test_the_kill_rule_policy_is_untouched_by_a_new_number_finding():
    """Новая находка НЕ заводит нового триггера деградации публичного сайта (это был бы
    предмет №2 границы ADR-285): стоп-кран по-прежнему только завышенный снимок и 48 ч."""
    asof = _day(5)
    r = _ev(home_html=_home(asof, days=None, apy=None, gates=None),
            track_html=_track(asof, days=89), snap_asof=asof, shelf=_shelf(_day(0), days=94))
    assert "COMPARISON_NOT_MEASURED" in _codes(r) or "SITE_BEHIND_SNAPSHOT" in _codes(r)
    assert r["degrade_triggered"] is False
    assert r["snapshot_overstated"] is False


# ── сам реестр: объявление обязано быть объявлением, а не набором регекспов ───
def test_every_declared_source_says_why_that_page():
    """«Почему именно с неё» — часть вопроса заказа. Причина обязана быть записана."""
    for label, sources in mon.SITE_NUMBER_SOURCES.items():
        assert sources, label
        for page, elem_id, pattern, why in sources:
            assert page in ("home", "track"), (label, page)
            assert isinstance(why, str) and len(why.strip()) >= 20, (label, elem_id, why)
            assert isinstance(pattern, str) and pattern


def test_the_declared_id_is_the_id_the_pattern_actually_looks_for():
    """Защита от опечатки «объявили m-days, ищем sl-day»: объявление и есть то, что
    исполняется, иначе таблица снова станет украшением."""
    for label, sources in mon.SITE_NUMBER_SOURCES.items():
        for _page, elem_id, pattern, _why in sources:
            assert f'id="{elem_id}"' in pattern, (label, elem_id, pattern)


def test_the_pattern_capture_group_survives_a_trailing_attribute_free_tag():
    """Живая разметка пишет id последним атрибутом, но это не гарантия. Регексп обязан
    допускать атрибуты ПОСЛЕ id, иначе один рефакторинг вернёт молчание."""
    hits, _ = mon.locate_site_number(
        "evidenced_days", {"home": '<div id="m-days" class="val">96</div>', "track": ""})
    assert [v for _p, _i, v in hits] == [96.0]


def test_the_measured_ids_of_30_09_are_declared():
    """Замер 30.09 живым запросом. Если разметка снова уедет, тест обязан упасть —
    молчание сверки было именно следствием незамеченного переезда id."""
    declared = {(p, i) for srcs in mon.SITE_NUMBER_SOURCES.values() for p, i, _pat, _w in srcs}
    for pair in (("home", "m-days"), ("home", "m-apy"), ("home", "m-gates"),
                 ("track", "tr-days-2"), ("track", "tr-apy"), ("track", "tr-equity")):
        assert pair in declared, pair


def test_the_source_table_is_the_only_place_ids_are_spelled():
    """Второй копии списка id в модуле быть не должно: разъехавшись, они вернут ровно
    тот дефект, ради которого таблица заведена."""
    src = (_ROOT / "scripts" / "site_freshness_monitor.py").read_text()
    body = src.split("SITE_NUMBER_SOURCES = {", 1)[1].split("\n}\n", 1)[1]
    for elem_id in ("m-days", "m-apy", "m-gates", "tr-days-2", "tr-apy", "sl-day", "sl-gates"):
        assert not re.search(r'id="%s"' % re.escape(elem_id), body), elem_id


# ── закрепление СВОДКИ: текст находки и есть ответ на вопрос заказа ───────────
# Добавлено по мутационному замеру: 21 из 67 мутаций выжили, и почти все сидели в
# строках, которые ОБЪЯВЛЕНЫ, но не закреплены ни одним тестом. Число, чьё имя не
# описывает содержимого, — ровно тот дефект, против которого написан весь шаг; не
# закрепить его формулировку значило бы повторить его внутри самого шага.
def test_the_divergence_finding_spells_both_sides_and_the_element():
    """Находка обязана назвать: какая страница, какой id, что на сайте, что в витрине.
    Без любого из четырёх на вопрос «с какой страницы взят операнд» ответа нет."""
    asof = _day(5)
    r = _ev(home_html=_home(asof, days=89), track_html=_track(asof, days=None),
            snap_asof=asof, shelf=_shelf(_day(0), days=94))
    d = [x for x in _detail(r, "SITE_BEHIND_SNAPSHOT") if "evidenced_days" in x][0]
    # Текст закреплён ЦЕЛИКОМ, а не по кускам: подстрока «=89» проходит и в «=89.0»,
    # то есть проверка по кускам не заметила бы потери формата `:g` — а человек в
    # тревоге читает именно «89», а не «89.0» (мутационный замер 30.09).
    assert d == "site evidenced_days=89 (home#m-days) != витрина evidenced_days=94", d


def test_the_third_outcome_text_says_not_measured_and_shows_the_page_id_leg_form():
    """След обязан читаться как `страница#id:исход`, а не как список слов."""
    asof = _day(0)
    r = _ev(home_html=_home(asof, days=None, apy=None, gates=None),
            track_html=_track(asof, days=None, gates_placeholder=False), snap_asof=asof)
    d = [x for x in _detail(r, "COMPARISON_NOT_MEASURED") if "evidenced_days" in x][0]
    assert d.startswith("сверка «evidenced_days» НЕ ИЗМЕРЕНА:"), d
    assert "home#m-days:unmeasured:id_absent" in d, d
    assert "третий исход" in d, d
    # след РАЗДЕЛЁН: склеенный в одну строку перечень нечитаем, а именно он и есть
    # ответ на вопрос «с какой страницы»
    assert "unmeasured:id_absent, home#sl-day" in d, d


def test_the_shelf_side_finding_names_the_shelf_and_what_the_site_did_give():
    asof = _day(0)
    shelf = _shelf(asof)
    shelf["headline"]["evidenced_days"] = {}
    r = _ev(snap_asof=asof, shelf=shelf)
    d = [x for x in _detail(r, "COMPARISON_NOT_MEASURED") if "evidenced_days" in x][0]
    assert d.startswith("сверка «evidenced_days» НЕ ИЗМЕРЕНА со стороны ВИТРИНЫ:"), d
    assert "home#m-days=94" in d, d
    assert "сравнивать не с чем" in d, d


def test_an_empty_source_table_says_so_instead_of_an_empty_trail():
    """Пустой перечень источников — тоже третий исход, и он обязан назвать себя,
    иначе в отчёте окажется `unmeasured:site:` без единого слова о причине."""
    hits, probes = mon.locate_site_number("evidenced_days", {"home": "x"}, sources={})
    assert (hits, probes) == ([], [])
    asof = _day(0)
    saved = mon.SITE_NUMBER_SOURCES
    try:
        mon.SITE_NUMBER_SOURCES = {"evidenced_days": (), "gates_passed": ()}
        r = _ev(snap_asof=asof)
    finally:
        mon.SITE_NUMBER_SOURCES = saved
    d = [x for x in _detail(r, "COMPARISON_NOT_MEASURED") if "evidenced_days" in x][0]
    assert "источников не объявлено" in d, d


# ── поведенческие контроли, найденные мутациями ──────────────────────────────
def test_the_id_is_matched_as_an_attribute_not_as_a_bare_substring():
    """`setText('m-days', …)` в скрипте страницы — это УПОМИНАНИЕ id, а не элемент.
    Считать его присутствием значило бы объявить заглушкой страницу, где числа нет
    вовсе: вместо «id отсутствует» отчёт сказал бы «значение не читается»."""
    def fate(html):
        _hits, probes = mon.locate_site_number("evidenced_days", {"home": html, "track": "x"})
        return {f"{p}#{i}": leg for p, i, leg in probes}["home#m-days"]
    # имя id в скрипте — в одинарных кавычках…
    assert fate("<script>setText('m-days', 96);</script>") == mon.SOURCE_LEG_ID_ABSENT
    # …и в двойных: совпадение обязано требовать ИМЕННО атрибут `id="…"`
    assert fate('<script>var k = "m-days";</script>') == mon.SOURCE_LEG_ID_ABSENT
    # и чужой id, начинающийся так же, не есть наш: без закрывающей кавычки
    # `id="m-days-total"` читался бы как присутствие `m-days`
    assert fate('<div id="m-days-total">96</div>') == mon.SOURCE_LEG_ID_ABSENT
    assert fate('<div id="m-days">96</div>') == mon.SOURCE_LEG_MEASURED


def test_an_empty_page_yields_a_mapping_not_none():
    """`parse_site_numbers` возвращает СЛОВАРЬ и на пустой странице: вызывающий
    делает `.get(...)`, и `None` здесь означал бы падение сторожа вместо находки."""
    assert mon.parse_site_numbers("", page="home") == {}
    assert mon.parse_site_numbers(None, page="home") == {}


def test_without_a_page_name_both_pages_are_consulted():
    """`page=None` — старое поведение «любой объявленный источник». Оно осталось для
    вызовов, которым страница неизвестна, и обязано опрашивать ОБЕ страницы: иначе
    половина реестра станет недостижимой молча."""
    assert mon.parse_site_numbers('<div id="m-days">96</div>')["evidenced_days"] == 96.0
    assert mon.parse_site_numbers('<span id="tr-days-2">96</span>')["evidenced_days"] == 96.0
