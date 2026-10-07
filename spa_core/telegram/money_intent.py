#!/usr/bin/env python3
"""Money-action intent guard for free text / voice (ADR-612). Deterministic, no LLM.

The SPA bot has NO execution path: no exchange client, no wallet, no order. But free text and
voice go to the LLM classifier (``ask_router``), which may call «купи биткоин на 1000» a TASK and
file it into the inbox — where an agent could read it as an order. That would turn a sentence
into an instruction with nobody deciding it (ADR-285 subject №1 is the owner's alone, real
capital is $0).

So before the classifier: text that looks like a command to move money is answered with a plain
refusal and is NOT filed anywhere. The owner keeps the deliberate path: ``/task <текст>`` still
files it as a task (an explicit act, not a guess). Read commands (``/btc``, ``/lab`` …) never
reach here — they are slash commands and only open a view.

False positives are cheap (one explanatory reply; nothing lost — the owner re-sends with /task);
false negatives are what the classifier already did before this module. Stdlib only.
"""
from __future__ import annotations

import re

#: LOOSE money vocabulary — verbs AND noun-like stems («вывод», «положение», «инвестиционный»,
#: «лонги»). Used ONLY by :func:`is_suspected` (the inbox stamp), never to refuse a message:
#: re-review 07.10 found it refusing ordinary questions («какой вывод по пулу aave?»).
_ACTION = re.compile(
    r"(?<![\w])("
    r"(по|до|за|пере|вы|при)?куп\w*|(пере|рас)?прода\w*|отправ\w*|перевед\w*|перевест\w*|переве[сз]\w*|"
    r"(вы|пере)?вед[иу]\w*|вывест\w*|вывод\w*|(пере|по|вы)?лож\w*|закин\w*|кин[уь]\w*|"
    r"обмен\w*|поменя\w*|влож\w*|влей\w*|влить|инвест\w*|(за)?шорт\w*|лонг\w*|"
    r"открой\s+(позицию|сделку)|закрой\s+(позицию|сделку)|зайди\s+в|"
    r"buy\w*|sell\w*|swap\w*|withdraw\w*|deposit\w*|transfer\w*|send|long|short|ape|"
    r"open\s+(a\s+)?position|close\s+(the\s+)?position"
    r")(?![\w])", re.IGNORECASE)

_B, _E = r"(?<![\w])(", r")(?![\w])"
#: IMPERATIVE money verbs (an order to the bot): «купи», «давай купим», «закинь», «зашорти».
_IMPERATIVE = re.compile(_B +
    r"(по|до|за)?куп(и|ите|им|ай|айте)|(рас|пере)?прода(й|йте|дим|вай|вайте)|отправ(ь|ьте|им)|"
    r"перевед(и|ите|ём|ем)|вывед(и|ите|ем)|выводи(те)?|(пере|по|в)лож(и|ите|им)|закин(ь|ьте|ем)|кин(ь|ьте)|"
    r"обменя(й|йте|ем)|поменя(й|йте|ем)|влей(те)?|инвестиру(й|йте|ем)|(за)?шорт(и|ите|ани)|"
    r"залонгу(й|йте)|лонгани|открой(те)?\s+(позицию|сделку|лонг|шорт)|закрой(те)?\s+(позицию|сделку)|"
    r"зайди(те)?\s+в|сними(те)?|снимем|выйди(те)?\s+из|ликвидируй(те)?|распродай(те)?" + _E, re.IGNORECASE)
#: other FINITE/infinitive money verbs — an instruction when not asked as a question
#: («вложить деньги в sUSDe», «надо продать btc»)
_INFINITIVE = re.compile(_B +
    r"(по|до|за)?купить|(рас|пере)?продать|отправить|перевести|вывести|(пере|по|в)ложить|закинуть|"
    r"обменять|поменять|влить|инвестировать|зашортить|снять|ликвидировать" + _E, re.IGNORECASE)
#: English: verbs, and long/short only as the FIRST word («long btc 5x», never «short interest»)
_EN_VERB = re.compile(r"(?<![\w])(buy|sell|swap|withdraw|deposit|transfer|send|go\s+long|go\s+short|"
                      r"open\s+(a\s+)?position|close\s+(the\s+)?position)(?![\w])|^\s*(long|short)\b",
                      re.IGNORECASE)
#: switching ON real-money / live execution is an order even without an asset word
#: («включи live торговлю», «enable live trading») — the bot can never do it (inv. #1, ADR-285 №1)
_GO_LIVE = re.compile(
    r"(?<![\w])(включи(те)?|запусти(те)?|активируй(те)?|переключи(те)?|enable|turn\s+on|start|switch)(?![\w])"
    r".{0,40}(live|лайв|реальн\w*\s+(деньг\w*|торговл\w*|исполнени\w*|капитал\w*)|боев\w*|"
    r"исполнени\w*|торговл\w*|trading|execution)", re.IGNORECASE)
#: a question asks; it does not order — unless it carries an explicit RU imperative («купи btc?»)
_QUESTION_START = re.compile(
    r"^\s*(почему|зачем|как|какой|какая|какое|какие|каков\w*|что|сколько|где|когда|ли|объясни\w*|покажи\w*|"
    r"расскажи\w*|what|why|how|when|where|which|who|is|are|does|do|can|explain|show|tell)\b", re.IGNORECASE)
#: about a report / chart / summary — never money movement («отправь отчёт по портфелю»)
_REPORT = re.compile(r"(отч[её]т\w*|сводк\w*|график\w*|скрин\w*|дайджест\w*|report\w*|summary|chart\w*|digest)",
                     re.IGNORECASE)

#: what the money is (asset / cash / position / amount words)
_ASSET = re.compile(
    r"(btc|биткоин\w*|битк\w*|bitcoin|eth\b|эфир\w*|usdc|usdt|usde|susde|dai|стейбл\w*|доллар\w*|\$|"
    r"капитал\w*|деньг\w*|денег|позици\w*|токен\w*|крипт\w*|монет\w*|портфел\w*|кошел[её]к\w*|кошельк\w*|"
    r"пул\w*|aave|morpho|compound|pendle|на\s+все|всё|все\s+деньги|"
    r"position\w*|coin\w*|token\w*|crypto\w*|money|cash|stable\w*|wallet\w*|pool\w*|"
    r"\d+\s*(k|к|тыс\w*|x|х)\b)",
    re.IGNORECASE)

#: Read-only questions about the same nouns: «что с биткоином», «покажи капитал» — no verb above
#: matches them, and a leading «/» is a command (only opens a view), never an order.

REFUSAL = (
    "🔒 Похоже на поручение двигать деньги. Я его НЕ исполняю и никуда не записываю: "
    "у бота нет права исполнения, реальный капитал $0, live-исполнение не включено.\n"
    "Посмотреть состояние: /capital · /btc · /lab · /oracle · /sherlock.\n"
    "Если это задача для команды (обсудить, исследовать) — пришли <code>/task …</code>, "
    "тогда она попадёт в inbox как задача, а не как приказ.")


#: a short, card-sized mention of an asset with an amount or a money verb — stamped on the
#: inbox card (``money_intent: suspected``) so the reader treats it as a topic, not an order.
_AMOUNT = re.compile(r"\d+\s*(k|к|тыс\w*|\$|usd\w*|btc|eth)|\$\s*\d", re.IGNORECASE)


def is_suspected(text: str) -> bool:
    """Weaker than :func:`is_money_action`: asset named together with a verb OR an amount."""
    s = str(text or "")
    return bool(_ASSET.search(s) and (_ACTION.search(s) or _AMOUNT.search(s)))


def is_question(text: str) -> bool:
    s = str(text or "").strip()
    return s.endswith("?") or bool(_QUESTION_START.match(s))


def is_money_action(text: str) -> bool:
    """True when free text reads like an ORDER to move money or open/close a position.

    Needs an action-verb form (imperative; or infinitive / English verb when not a question)
    together with an asset/amount. A question or a report request is never an order unless it
    carries an explicit Russian imperative («купи btc?»). Noun-like stems («вывод», «положение»,
    «лонги») never refuse anything — they only feed :func:`is_suspected`."""
    s = str(text or "")
    if not s.strip() or s.lstrip().startswith("/"):
        return False
    if _GO_LIVE.search(s) and not is_question(s):
        return True
    if not _ASSET.search(s) or _REPORT.search(s):
        return False
    if _IMPERATIVE.search(s):
        return True
    if is_question(s):
        return False
    return bool(_INFINITIVE.search(s) or _EN_VERB.search(s))
