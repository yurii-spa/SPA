import { useState, useEffect } from 'react';

/**
 * WalletCheck — hero entry to the free DeFi Checkup (checkup.earn-defi.com).
 * Paste a wallet / ENS → cross-navigate to the checkup dashboard. Read-only, no wallet connection,
 * NO email. Client-side pre-check only (real resolver runs on the checkup side). Bilingual: follows
 * <html lang> like the other islands (localStorage spa_lang / html.lang + MutationObserver).
 */
const CHECKUP = 'https://checkup.earn-defi.com/check?address=';

const getLang = () => {
  try {
    if (typeof localStorage !== 'undefined') {
      const l = localStorage.getItem('spa_lang');
      if (l === 'en' || l === 'ru') return l;
    }
  } catch (e) { /* ignore */ }
  return (typeof document !== 'undefined' && document.documentElement.lang === 'en') ? 'en' : 'ru';
};

const T = {
  title: { ru: 'Проверьте свою DeFi-стратегию, прежде чем доверять её кому-либо', en: 'Check your DeFi strategy before you trust anyone with it' },
  sub: {
    ru: 'Вставьте адрес кошелька, ENS или ссылку DeBank — мгновенный отчёт: стоимость по ценам выхода, концентрация, экспозиция по стейблам и мостам, и что наша RiskPolicy отклонила бы. Read-only, без подключения кошелька, без email.',
    en: 'Paste a wallet address, ENS, or DeBank URL — an instant report: value at exit prices, concentration, stablecoin & bridge exposure, and what our RiskPolicy would refuse. Read-only, no wallet connection, no email.',
  },
  placeholder: { ru: 'Адрес кошелька (0x…), ENS или ссылка DeBank', en: 'Wallet address (0x…), ENS name, or DeBank URL' },
  button: { ru: 'Проверить кошелёк →', en: 'Check my wallet →' },
  hint: { ru: 'Введите корректный адрес (0x…) или ENS-имя (name.eth).', en: 'Enter a valid address (0x…) or ENS name (name.eth).' },
  micro: { ru: 'Только чтение · публичные ончейн-данные · без подключения кошелька · открывает checkup.earn-defi.com', en: 'Read-only · public onchain data · no wallet connection · opens checkup.earn-defi.com' },
};
const tr = (k, lang) => (T[k] ? (T[k][lang] || T[k].ru) : k);

// permissive client pre-check: 0x + 40 hex, *.eth, or a debank profile url. Real resolve is server-side.
function looksValid(v) {
  const s = v.trim();
  if (/^0x[a-fA-F0-9]{40}$/.test(s)) return true;
  if (/\.eth$/i.test(s)) return true;
  if (/debank\.com\/profile\/0x[a-fA-F0-9]{40}/i.test(s)) return true;
  return false;
}

export default function WalletCheck() {
  const [lang, setLang] = useState('ru');
  const [val, setVal] = useState('');
  const [err, setErr] = useState(false);

  useEffect(() => {
    setLang(getLang());
    const obs = new MutationObserver(() => setLang(getLang()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    return () => obs.disconnect();
  }, []);

  function submit(e) {
    e.preventDefault();
    const s = val.trim();
    if (!looksValid(s)) { setErr(true); return; }
    setErr(false);
    // Pull the bare 0x address out of a DeBank profile URL — the checkup expects
    // an address/ENS, not the full URL (passing the URL raw would fail to resolve).
    const debank = s.match(/debank\.com\/profile\/(0x[a-fA-F0-9]{40})/i);
    const target = debank ? debank[1] : s;
    window.location.href = CHECKUP + encodeURIComponent(target);
  }

  return (
    <div className="walletcheck">
      <h2 className="wc-title">{tr('title', lang)}</h2>
      <p className="wc-sub">{tr('sub', lang)}</p>
      <form className="wc-form" onSubmit={submit}>
        <input
          className="wc-input"
          type="text"
          value={val}
          onChange={(e) => { setVal(e.target.value); if (err) setErr(false); }}
          placeholder={tr('placeholder', lang)}
          aria-label={tr('placeholder', lang)}
          spellCheck={false}
          autoComplete="off"
        />
        <button className="wc-btn" type="submit">{tr('button', lang)}</button>
      </form>
      {err && <p className="wc-hint wc-err">{tr('hint', lang)}</p>}
      <p className="wc-micro">{tr('micro', lang)}</p>
    </div>
  );
}
