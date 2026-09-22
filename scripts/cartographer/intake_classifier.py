#!/usr/bin/env python3
"""Studio · Разбор входящего по предмету. Детерминированно там, где хватает.

Почему стадия важна
===================
Это первый разрыв автономии: предмет объявлен у 64 карточек из 693 (9.2 %), и дальше
всё держится на человеке.

ГЛАВНОЕ ОГРАНИЧЕНИЕ, найденное замером
======================================
Существующее поле ``domain`` — **не словарь, а проза**: 64 карточки, 58 различных
значений, ноль попаданий в предложенный словарь. Оно отвечает на ДРУГОЙ вопрос — «что
трогаем и что НЕ трогаем»:

    money-path (RiskPolicy НЕ трогаем; pre_cutover_gate + ADR-061)

Половина смысла в отрицаниях, и одномерным ярлыком их не выразить. Поэтому новый ярлык
живёт в **отдельном ключе** ``domain_class``, а прозаический ``domain`` не трогается
никогда. Перезапись стёрла бы 64 скоуп-контракта, и один из них измеренно СПАС от
ошибки: карточка про единицы APY прямо пишет «advisory-стратегия, НЕ RiskPolicy и НЕ
money-path», хотя всё остальное в ней кричит про капитал.

Какие сигналы ГОДНЫ, а какие хуже бесполезного
==============================================
Замер против размеченной вручную выборки (базовая линия «всегда CAPITAL» = 22.8 %):

* ``finding_key`` — покрытие 8.9 %, точность **100 %**. Ставится первым;
* ключевые слова заголовка — 66.5 % / 75.2 %; только подсказка;
* пути в теле — 29.7 % / 70.2 %; только подсказка;
* **префикс имени файла — 100 % / 25.9 %**, то есть на 3 п.п. лучше «всегда CAPITAL»;
* **поле ``source`` — 64.6 % / 34.3 %**;
* **``tests/`` → BUILD — 19.6 % / 32.3 %**.

Три последних сигнала здесь НЕ ИСПОЛЬЗУЮТСЯ. Сигнал с большим покрытием и низкой
точностью хуже отсутствующего: он закрывает вопрос неверным ответом и не даёт увидеть,
что ответа нет.

Почему одних правил не хватит — это тоже замер
==============================================
У CAPITAL, INVESTMENT_R&D и PRODUCT **своего словаря нет**: весь проект про доходность.
32.9 % карточек не ссылаются ни на один путь, и больше всего среди них именно CAPITAL.
Лучший детерминированный набор даёт 64.6 % даже при измерении на той же выборке, из
которой лексикон и выведен. Отсюда: правила закрывают то, что закрывают, остальное
уходит в ``UNKNOWN`` — и ``UNKNOWN`` есть законный ответ, а не поражение.

Порог задаёт ЦЕНА ошибки, а не вероятность
==========================================
Пары путаницы несимметричны. ``SECURITY`` → что угодно и ``CAPITAL`` → ``BUILD`` стоят
критично: окно компрометации не отматывается, а торговый цикл в тот же день торгует по
неверно понятой карточке. Поэтому при сомнении между дешёвым и дорогим предметом
выбирается ДОРОГОЙ, и это записывается в основание.

Классификатор НИЧЕГО НЕ РАЗРЕШАЕТ. Он только относит и направляет; исполнение по-прежнему
требует объявленной приёмки и своих гейтов. Только stdlib, LLM не вызывается.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

SCHEMA = 'intake_classification/1'

DOMAINS = ('CAPITAL', 'STUDIO', 'BUILD', 'INVESTMENT_R&D', 'PRODUCT',
           'RELIABILITY', 'SECURITY', 'OPERATIONS', 'UNKNOWN')

#: Ключ, в который пишется ярлык. НЕ ``domain``: там живёт проза скоупа.
LABEL_KEY = 'domain_class'
PROSE_KEY = 'domain'

#: Сигналы, ОТВЕРГНУТЫЕ замером. Список существует, чтобы их не вернули «для покрытия».
REJECTED_SIGNALS = {
    'filename_prefix': 'покрытие 100 %, точность 25.9 % — на 3 п.п. лучше постоянного '
                       'ответа; закрывает вопрос неверно и скрывает, что ответа нет',
    'source_field': 'покрытие 64.6 %, точность 34.3 %',
    'tests_path': 'покрытие 19.6 %, точность 32.3 %: «+N тестов» — форма приёмки, а не '
                  'предмет; о тестах пишут все',
    'landing_glob': 'глоб-формы вроде landing/** — это объявленный список файлов шага '
                    'приёмки, а не предмет карточки; точность падает с 75 % до 25 %',
}

#: Цена ошибки отнесения. Порог доверия берётся отсюда, а не из вероятности.
MISROUTE_COST = {
    'SECURITY': 'CRITICAL',
    'CAPITAL': 'CRITICAL',
    'PRODUCT': 'HIGH',
    'INVESTMENT_R&D': 'HIGH',
    'OPERATIONS': 'MEDIUM',
    'RELIABILITY': 'MEDIUM',
    'STUDIO': 'LOW',
    'BUILD': 'LOW',
    'UNKNOWN': 'MEDIUM',
}
_COST_ORDER = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}

#: Правило с точностью 100 % на замере. Идёт первым и, сработав, закрывает вопрос.
FINDING_KEY_RULES = (
    (re.compile(r'^B\d'), 'RELIABILITY'),
    (re.compile(r'^gap:'), 'CAPITAL'),
)

#: Пути, ОБЪЯВЛЯЮЩИЕ предмет. Только конкретные, без глоб-форм: глоб — это список
#: файлов приёмки, а не предмет.
PATH_RULES = (
    (re.compile(r'\bspa_core/risk/'), 'CAPITAL'),
    (re.compile(r'\bspa_core/governance/kill_switch'), 'CAPITAL'),
    (re.compile(r'\bspa_core/paper_trading/'), 'CAPITAL'),
    (re.compile(r'\bspa_core/strategy_lab/'), 'INVESTMENT_R&D'),
    (re.compile(r'\bspa_core/adapters/'), 'INVESTMENT_R&D'),
    (re.compile(r'\bspa_core/monitoring/'), 'RELIABILITY'),
    (re.compile(r'\bspa_core/telegram/'), 'OPERATIONS'),
    (re.compile(r'\blanding/[a-z0-9_./-]*\.(astro|md|js|json)\b'), 'PRODUCT'),
    (re.compile(r'\barchitecture/manifest\.json\b'), 'STUDIO'),
)

#: Приметы безопасности. Проверяются ОТДЕЛЬНО и раньше прочего словаря: цена пропуска
#: здесь критична и не отматывается.
SECURITY_MARKERS = (
    'утечк', 'секрет', 'token', 'токен', 'pat ', '_key', 'api_key', 'пароль',
    'credential', 'раздавал', 'компромет', 'инъекц', 'injection', 'обход гейта',
    'обход owner-gate', 'приватн', 'экспозиц', 'exposure',
)

_FM = re.compile(r'^---\n(.*?)\n---', re.S)


def _now():
    return datetime.now(timezone.utc)


class Signal:
    """Одно срабатывание: предмет, правило, и КАК оно доказывается."""

    def __init__(self, domain, rule, evidence, precision_measured=None):
        if domain not in DOMAINS:
            raise ValueError(f'предмет {domain!r} вне словаря')
        self.domain = domain
        self.rule = rule
        self.evidence = evidence
        self.precision_measured = precision_measured

    def as_dict(self):
        return {'domain': self.domain, 'rule': self.rule, 'evidence': self.evidence,
                'precision_measured_pct': self.precision_measured}


def _strip_quotes(value):
    """Значение фронтматтера приходит в кавычках.

    Правило `finding_key` было заявлено со точностью 100 % и срабатывало **ноль раз из
    168**: выражение искало `B` в начале строки, а строка начиналась с кавычки. Сигнал
    с идеальной точностью и нулевым срабатыванием выглядит в отчёте так же, как
    отсутствующий, — и отличить их можно только измерив СРАБАТЫВАНИЕ отдельно от
    точности.
    """
    return str(value or '').strip().strip('"').strip("'")


def _finding_key_signal(fields):
    key = _strip_quotes(fields.get('finding_key'))
    for pattern, domain in FINDING_KEY_RULES:
        if pattern.search(key):
            return Signal(domain, 'finding_key', f'finding_key={key}',
                          precision_measured=100.0)
    return None


def _security_signal(title, body):
    """Примета безопасности требует ВЕСА, а не одного упоминания.

    Первая редакция ловила любое вхождение в теле — и объявила безопасностью четыре
    карточки про капитал, которые лишь упоминали «секрет» или «приватный». Это сделало
    приметы главным источником критических ошибок: сдвиг в пользу дорогого предмета
    помогает, только если второй предмет дешевле. Здесь оба критичны, и «страховка»
    просто меняла одну критическую ошибку на другую.
    """
    t = (title or '').lower()
    in_title = [m for m in SECURITY_MARKERS if m in t]
    if in_title:
        return Signal('SECURITY', 'security_marker_in_title',
                      f'в ЗАГОЛОВКЕ встречается «{in_title[0].strip()}»')
    in_body = [m for m in SECURITY_MARKERS if m in (body or '').lower()]
    if len(in_body) >= 2:
        return Signal('SECURITY', 'security_markers_in_body',
                      f'в теле не менее двух примет: {[m.strip() for m in in_body[:3]]}')
    return None


def _path_signals(body):
    out = []
    for pattern, domain in PATH_RULES:
        m = pattern.search(body or '')
        if m:
            out.append(Signal(domain, 'declared_path', f'путь {m.group(0)}',
                              precision_measured=70.2))
    return out


def _keyword_signals(title, lexicon):
    out = []
    low = (title or '').lower()
    for word, domain in (lexicon or {}).items():
        if word in low:
            out.append(Signal(domain, 'title_keyword', f'слово «{word}»',
                              precision_measured=75.2))
    return out


def classify(*, fields, body='', lexicon=None):
    """Отнести карточку. Возвращает ярлык, уверенность и ВСЕ сработавшие правила.

    ``UNKNOWN`` — законный ответ. Он означает «правил не хватило», и это измерение,
    а не поражение: неверно отнесённая карточка едет к неверному владельцу и стоит
    дороже, чем неотнесённая.
    """
    title = str(fields.get('title') or '')
    text = f'{title}\n{body}'
    signals = []

    # 1. Правило со стопроцентной точностью. Сработало — вопрос закрыт.
    strong = _finding_key_signal(fields)
    if strong:
        return _verdict(strong.domain, 'PROVEN', [strong],
                        basis='правило finding_key измерено со точностью 100 %')

    # 2. Безопасность проверяется отдельно и раньше: цена пропуска критична.
    sec = _security_signal(title, body)
    if sec:
        signals.append(sec)

    signals += _path_signals(body)
    signals += _keyword_signals(title, lexicon)

    if not signals:
        return _verdict('UNKNOWN', 'NOT_DERIVABLE', [],
                        basis='ни одно объявленное правило не сработало; относить '
                              'наугад дороже, чем не относить')

    by_domain = {}
    for s in signals:
        by_domain.setdefault(s.domain, []).append(s)

    if len(by_domain) == 1:
        domain = next(iter(by_domain))
        return _verdict(domain, 'HEURISTIC', signals,
                        basis='все сработавшие правила согласны')

    # Разногласие. Сначала — вес правил, потом — ЦЕНА ошибки.
    ranked = sorted(by_domain.items(),
                    key=lambda kv: (-len(kv[1]),
                                    _COST_ORDER.get(MISROUTE_COST.get(kv[0]), 9)))
    top_count = len(ranked[0][1])
    tied = [d for d, ss in ranked if len(ss) == top_count]
    if len(tied) == 1:
        return _verdict(ranked[0][0], 'HEURISTIC', signals,
                        basis=f'правил за «{ranked[0][0]}» больше, чем за остальные')
    costs = sorted({_COST_ORDER.get(MISROUTE_COST.get(d), 9) for d in tied})
    if len(costs) == 1:
        # Оба спорящих предмета стоят одинаково дорого. Сдвиг в пользу одного из них
        # не уменьшает цену ошибки, а лишь меняет её направление: замер показал четыре
        # карточки про капитал, отнесённые к безопасности «на всякий случай», и каждая
        # была КРИТИЧЕСКОЙ ошибкой. Когда выбор между двумя дорогими предметами —
        # честный ответ «не отнесено».
        return _verdict('UNKNOWN', 'CONTESTED', signals,
                        basis=f'правила разошлись между {tied}, и цена ошибки у них '
                              f'одинакова ({MISROUTE_COST.get(tied[0])}): выбор наугад '
                              f'между двумя дорогими предметами хуже отказа',
                        contested=tied)
    chosen = min(tied, key=lambda d: _COST_ORDER.get(MISROUTE_COST.get(d), 9))
    return _verdict(chosen, 'HEURISTIC', signals,
                    basis=f'правила разошлись между {tied}; выбран «{chosen}», потому что '
                          f'цена ошибки у него {MISROUTE_COST.get(chosen)} выше — порог '
                          f'задаёт цена, а не вероятность',
                    contested=tied)


#: Уровни уверенности, которым РАЗРЕШЕНО направлять карточку. Замер на отложенной
#: половине: `PROVEN` — 7 из 7 верно (100 %), `HEURISTIC` — 6 из 19 (31.6 %) при
#: базовой линии 21.4 %. Эвристика, направляющая карточку, ошибается в двух случаях из
#: трёх, и пять её ошибок — критические по цене. Поэтому эвристика ПОДСКАЗЫВАЕТ, а не
#: направляет: её вывод виден человеку и не считается отнесением.
ROUTABLE_CONFIDENCE = ('PROVEN',)


def _verdict(domain, confidence, signals, *, basis, contested=None):
    routable = confidence in ROUTABLE_CONFIDENCE
    return {
        'schema': SCHEMA,
        LABEL_KEY: domain,
        'confidence': confidence,
        'basis': basis,
        'signals': [s.as_dict() for s in signals],
        'signal_count': len(signals),
        'contested_domains': contested or [],
        'misroute_cost': MISROUTE_COST.get(domain),
        # Отнесение и ПОДСКАЗКА — разные вещи. Неотнесённая карточка ждёт человека;
        # неверно отнесённая едет к неверному владельцу и стоит дороже.
        'routable': routable,
        'routed_domain': domain if routable else 'UNKNOWN',
        'suggestion': None if routable else (domain if domain != 'UNKNOWN' else None),
        'suggestion_measured_precision_pct': None if routable else 31.6,
        'routing_note': ('направляет только правило с измеренной точностью; эвристика '
                         'остаётся подсказкой для человека или модели'),
        'authorizes_execution': False,
        'writes_to_key': LABEL_KEY,
        'prose_key_untouched': PROSE_KEY,
        'note': ('классификатор относит и направляет; он ничего не разрешает исполнять '
                 'и не трогает прозаический скоуп карточки'),
    }


def build_lexicon(labelled, *, min_occurrences=2):
    """Лексикон ВЫВОДИТСЯ из обучающей половины, а не вписывается руками.

    Слово попадает в лексикон, только если оно встречается у одного предмета и не
    встречается у других: слово, общее двум предметам, ничего не различает.
    """
    per_domain, seen_all = {}, {}
    for card in labelled:
        domain = card.get('domain')
        if domain not in DOMAINS or domain == 'UNKNOWN':
            continue
        words = {w for w in re.findall(r'[а-яёa-z][а-яёa-z_-]{4,}',
                                       str(card.get('title') or '').lower())}
        for w in words:
            per_domain.setdefault(w, set()).add(domain)
            seen_all[w] = seen_all.get(w, 0) + 1
    lexicon = {}
    for word, domains in per_domain.items():
        if len(domains) == 1 and seen_all[word] >= min_occurrences:
            lexicon[word] = next(iter(domains))
    return lexicon


def backtest(labelled, *, lexicon=None, bodies=None, route_only=False):
    """Замер на размеченной выборке. Считает и покрытие, и точность, и цену ошибок."""
    bodies = bodies or {}
    total = len(labelled)
    answered = correct = unknown = 0
    costly_mistakes, rows = [], []
    for card in labelled:
        truth = card.get('domain')
        out = classify(fields={'title': card.get('title'),
                               'finding_key': card.get('finding_key')},
                       body=bodies.get(card.get('card'), ''), lexicon=lexicon)
        got = out[LABEL_KEY]
        got = out['routed_domain'] if route_only else got
        if got == 'UNKNOWN':
            unknown += 1
        else:
            answered += 1
            if got == truth:
                correct += 1
            elif MISROUTE_COST.get(truth) in ('CRITICAL', 'HIGH'):
                costly_mistakes.append({'card': card.get('card'), 'truth': truth,
                                        'got': got,
                                        'cost': MISROUTE_COST.get(truth)})
        rows.append({'card': card.get('card'), 'truth': truth, 'got': got,
                     'confidence': out['confidence'],
                     'correct': got == truth})
    fired_strong = sum(1 for r in rows if r['confidence'] == 'PROVEN')
    return {
        'schema': 'intake_backtest/1',
        'strong_rule_fired': fired_strong,
        'measured_at': _now().isoformat(),
        'total': total,
        'answered': answered,
        'unknown': unknown,
        'unknown_pct': round(unknown / total * 100, 1) if total else None,
        'coverage_pct': round(answered / total * 100, 1) if total else None,
        'correct': correct,
        'precision_pct': round(correct / answered * 100, 1) if answered else None,
        'accuracy_over_all_pct': round(correct / total * 100, 1) if total else None,
        'costly_mistakes': costly_mistakes,
        'costly_mistake_count': len(costly_mistakes),
        'rows': rows,
        'route_only': route_only,
        'rejected_signals': dict(REJECTED_SIGNALS),
        'baseline_note': ('базовая линия «всегда самый частый предмет» измерена отдельно: '
                          'набор правил обязан её превосходить, иначе он украшение'),
    }


def baseline_always_modal(labelled):
    counts = {}
    for c in labelled:
        counts[c.get('domain')] = counts.get(c.get('domain'), 0) + 1
    if not counts:
        return None
    modal = max(counts, key=counts.get)
    return {'domain': modal,
            'accuracy_pct': round(counts[modal] / len(labelled) * 100, 1)}
