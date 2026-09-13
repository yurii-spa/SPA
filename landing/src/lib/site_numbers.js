// site_numbers.js — ЕДИНСТВЕННЫЙ адрес, откуда страница берёт любое число (ADR-365).
//
// Установка владельца 12.09 (ADR-357 п. 5): «все цифры на сайте должны браться
// консолидированно с одного и того же места… и тогда вы мне не будете каждый раз
// спрашивать одно и то же по этим цифрам». Повторяющийся вопрос агентов был следствием
// того, что у чисел не было одного адреса, — а не того, что владелец не отвечал.
//
// ЭТО НЕ ТРЕТИЙ ИСТОЧНИК. Источников по-прежнему два, и делит их природа числа: замер
// устаревает за сутки, порог не устаревает вовсе (`.claude/rules/site-numbers.md`).
// Здесь — ВИТРИНА: проекция обоих в один адрес чтения, собираемая
// `scripts/build_site_numbers.py`. Своего числа у неё нет ни одного.
//
// Три правила, которые живут здесь, а не в страницах:
//   1. НЕТ ЗНАЧЕНИЯ — НЕТ ЧИСЛА. Возвращается null, страница печатает «данные
//      недоступны». Последнее известное число не печатается никогда: именно так строка
//      «~3,3 % фактических» простояла в шестнадцати файлах два месяца (ADR-293).
//   2. СТАВКА ВСЕГДА ГОДОВАЯ и помечена как годовая. «Годовая» без метода — намерение,
//      а не число, поэтому метод назван в самой витрине (`annualisation`).
//   3. ХВОСТ ИДЁТ РЯДОМ СО СТАВКОЙ. Инвариант #8 и `site-copy.md`: для книги показывается
//      просадка вместе с доходностью. `rateWithTail()` возвращает обе сразу — чтобы
//      «забыть хвост» требовало усилия, а не случалось само.

import NUMBERS from '../data/site_numbers.json';

export default NUMBERS;

/** Когда снят замер (наблюдение ежедневное) и когда опубликовано (такт недельный). */
export function dates() {
  return {
    measured: NUMBERS.measured_at || null,
    published: NUMBERS.published_at || null,
    next: NUMBERS.next_publication || null,
    cadence: NUMBERS.cadence || null,
  };
}

/** Значение поля витрины или null. Никогда не возвращает устаревшее. */
export function value(fig) {
  const v = fig && fig.value;
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

/** Причина, по которой значения нет, — чтобы страница могла сказать её вслух. */
export function unavailable(fig) {
  return (fig && fig.unavailable_reason) || null;
}

/** «5,0 %» / «5.0%» — одна цифра после запятой; null-safe. */
export function pct(fig, ru = false, digits = 1) {
  const n = value(fig);
  if (n == null) return ru ? 'данные недоступны' : 'data unavailable';
  const s = n.toFixed(digits);
  return (ru ? s.replace('.', ',') : s) + '%';
}

/** «$101 256» — null-safe. */
export function usd(fig, ru = false) {
  const n = value(fig);
  if (n == null) return ru ? 'данные недоступны' : 'data unavailable';
  return '$' + Math.round(n).toLocaleString(ru ? 'ru-RU' : 'en-US');
}

/** Головная годовая ставка трека. */
export function headlineApy() {
  return NUMBERS.headline && NUMBERS.headline.apy;
}

/** Книга по имени: conservative | balanced | aggressive. */
export function book(id) {
  return (NUMBERS.books && NUMBERS.books[id]) || null;
}

/** Порог-РЕШЕНИЕ по имени. Нет такого — null, а не выдуманное число. */
export function threshold(name) {
  return (NUMBERS.thresholds && NUMBERS.thresholds[name]) || null;
}

/**
 * Ставка и хвост ОДНОЙ строкой — форма, в которой их нельзя разнести.
 *
 * Возвращает `{ apy, drawdown, text }`; `text` уже несёт обе величины и слово
 * «годовых», потому что ставка без периода и без хвоста — это половина правды,
 * а половина правды на странице о доходности читается как обещание.
 */
export function rateWithTail(id, ru = false) {
  const b = book(id);
  if (!b) return { apy: null, drawdown: null, text: ru ? 'данные недоступны' : 'data unavailable' };
  const a = value(b.apy);
  if (a == null) {
    const why = unavailable(b.apy);
    return { apy: null, drawdown: value(b.drawdown), text: ru ? (why || 'данные недоступны') : 'data unavailable' };
  }
  const dd = value(b.drawdown);
  const ddText = dd == null
    ? (ru ? 'просадка не измерена' : 'drawdown not measured')
    : (ru ? `просадка ${pct(b.drawdown, true)}` : `drawdown ${pct(b.drawdown)}`);
  return {
    apy: a,
    drawdown: dd,
    text: ru ? `${pct(b.apy, true)} годовых · ${ddText}` : `${pct(b.apy)} annualised · ${ddText}`,
  };
}
