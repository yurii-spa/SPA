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

/**
 * Округление ВНИЗ до `digits` знаков — решение владельца 2026-10-04, вариант 1
 * (ADR-563, предмет №2 границы ADR-285).
 *
 * Зачем отдельно от `pct`. Округление к ближайшему на одном знаке добавляет до
 * +0,05 п.п., и 4,9637 % печаталось как 5,0 % — то есть сайт показывал БОЛЬШЕ
 * измеренного (инв. #8). Вниз ошибка всегда в нашу невыгодную сторону, а это
 * единственная безопасная сторона для числа о доходности.
 *
 * Почему `pct` не переделан целиком: вниз округляется СТАВКА. У просадки
 * безопасная сторона обратная (вниз она занижала бы убыток), и менять её
 * заодно значило бы выдать свою догадку за решение владельца.
 *
 * Зачем эпсилон. Двоичная дробь 2.9 лежит в памяти как 2.8999999999999996, и
 * `Math.floor(2.9 * 10) / 10` дало бы 2,8 — то есть «вниз» срезало бы знак у
 * числа, которое УЖЕ ровно. Эпсилон меньше любой десятой доли процентного
 * пункта и сдвигает только значения, отличающиеся от ровной десятой на
 * погрешность представления.
 */
export function floorTo(n, digits = 1) {
  if (!Number.isFinite(n)) return null;
  const scale = Math.pow(10, digits);
  return Math.floor(n * scale + 1e-9) / scale;
}

/** Ставка, округлённая ВНИЗ: «4,9%» — никогда больше измеренного. */
export function pctDown(fig, ru = false, digits = 1) {
  const n = value(fig);
  if (n == null) return ru ? 'данные недоступны' : 'data unavailable';
  const floored = floorTo(n, digits);
  if (floored == null) return ru ? 'данные недоступны' : 'data unavailable';
  const s = floored.toFixed(digits);
  return (ru ? s.replace('.', ',') : s) + '%';
}

/**
 * Политика владельца 2026-10-08 (ADR-660, заменяет округление вниз ADR-563): процент —
 * РОВНО два знака, ROUND_HALF_UP на третьем знаке, по-русски «4,89 %», по-английски «4.89%».
 *
 * Округляется ДЕСЯТИЧНАЯ запись числа, а не его двоичная дробь: 2.675 лежит в памяти как
 * 2.67499999…, и `toFixed(2)` дал бы 2.67 — политика требует 2.68. `String(n)` в JS — самая
 * короткая запись, возвращающая то же число (как `repr` в Python), поэтому округляется то,
 * что производитель числа написал. Близнец — `spa_core/utils/presentation.py::fmt_pct`;
 * совпадение двух копий меряет `spa_core/tests/test_owner_presentation_policy_js.py`.
 *
 * Нет числа ⇒ null (страница говорит «данные недоступны»), никогда «0,00 %». Ненулевое
 * число, округлившееся в ноль, печатается с оговоркой «<0,01 %», а не как точный ноль.
 */
function _plainDecimal(abs) {
  const s = String(abs);
  const m = /^(\d+)(?:\.(\d+))?e([+-]\d+)$/i.exec(s);
  if (!m) return s;
  const digits = m[1] + (m[2] || '');
  const point = m[1].length + Number(m[3]);
  if (point <= 0) return '0.' + '0'.repeat(-point) + digits;
  if (point >= digits.length) return digits + '0'.repeat(point - digits.length);
  return digits.slice(0, point) + '.' + digits.slice(point);
}

/** Сотые доли процента как BigInt (ROUND_HALF_UP по десятичной записи) или null. */
export function centsHalfUp(n) {
  if (typeof n !== 'number' || !Number.isFinite(n)) return null;
  const neg = n < 0;
  const [ip, fp = ''] = _plainDecimal(Math.abs(n)).split('.');
  const d3 = (fp + '000').slice(0, 3);
  let cents = BigInt(ip) * 100n + BigInt(d3.slice(0, 2));
  if (d3[2] >= '5') cents += 1n;
  return neg ? -cents : cents;
}

export function fmtPct2(n, ru = false, signed = false) {
  const c = centsHalfUp(n);
  if (c == null) return null;
  const suffix = ru ? '\u00a0%' : '%';
  const num = (x) => {
    const a = x < 0n ? -x : x;
    const s = (a / 100n).toString() + '.' + (a % 100n).toString().padStart(2, '0');
    return ru ? s.replace('.', ',') : s;
  };
  if (c === 0n) {
    if (n === 0) return num(0n) + suffix;
    return n > 0 ? '<' + num(1n) + suffix : '>-' + num(1n) + suffix;
  }
  const sign = c < 0n ? '-' : (signed ? '+' : '');
  return sign + num(c) + suffix;
}

/** Поле витрины → «4,89 %» / «4.89%»; нет значения — «данные недоступны». */
export function pct2(fig, ru = false, signed = false) {
  const s = fmtPct2(value(fig), ru, signed);
  return s == null ? (ru ? 'данные недоступны' : 'data unavailable') : s;
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
    // Ставка — ВНИЗ (решение владельца, ADR-563); просадка — к ближайшему.
    text: ru ? `${pctDown(b.apy, true)} годовых · ${ddText}` : `${pctDown(b.apy)} annualised · ${ddText}`,
  };
}
