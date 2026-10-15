// pct_format.js — ОДИН форматтер процентов сайта (ADR-660), без единого числа внутри.
//
// Вынесен из site_numbers.js 2026-10-08 (P1, волна 2): живые встроенные скрипты страниц
// (is:inline — обновление чисел с api.earn-defi.com в браузере) тоже печатают проценты, и
// им нужен ТОТ ЖЕ форматтер, а не своя копия на `toFixed`. Подключать site_numbers.js в
// общий бандл значило бы тащить витрину (21 КБ) на каждую страницу; этот файл — только
// арифметика. Layout.astro кладёт его в `window.spaFmtPct2` для встроенных скриптов.
// site_numbers.js реэкспортирует его — для страниц путь импорта прежний.

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
    return n > 0 ? '<' + num(1n) + suffix : '>\u2212' + num(1n) + suffix;
  }
  // Public site typography (P1 Wave 2 r2): a negative value prints the minus sign U+2212, not the
  // hyphen-minus; the NUMBER is the same as the Python twin's (parity compares after this one glyph).
  const sign = c < 0n ? '\u2212' : (signed ? '+' : '');
  return sign + num(c) + suffix;
}


/**
 * Percentages INSIDE prose we do not write ourselves (generated reason strings, scenario blurbs from the
 * stress library, audited verdict notes): «PT fixed rate (5.146 %)» → «5.15%» / «5,15 %». Same rule, same
 * arithmetic; the words around the number are untouched. A range «2–6%» becomes «2.00–6.00%».
 * Non-string ⇒ returned as is.
 */
const _PROSE_PCT = /(^|[^\w.,/#{}$[\]])(\d{1,4}(?:[.,]\d+)?)(\s?[–—-]\s?)?(\d{1,4}(?:[.,]\d+)?)?(?:\s| )?%/g;
export function pctText(str, ru = false) {
  if (typeof str !== 'string') return str;
  return str.replace(_PROSE_PCT, (all, pre, a, sep, b) => {
    const one = (x) => {
      const s = fmtPct2(parseFloat(x.replace(',', '.')), ru);
      return s == null ? null : s.replace(/ ?%$/, '');
    };
    const suffix = ru ? ' %' : '%';
    if (b != null && sep != null) {
      const fa = one(a), fb = one(b);
      return fa == null || fb == null ? all : `${pre}${fa}${sep}${fb}${suffix}`;
    }
    if (b != null) return all;   // «12 5%» — not a single number; leave the prose alone
    const fa = one(a);
    return fa == null ? all : `${pre}${fa}${suffix}`;
  });
}
