import { useState, useEffect, useCallback } from 'react';
import { apiSend, ApiError } from './api.js';

/*
 * SiweBinder — Sign-In With Ethereum wallet binding (module M1).
 *
 * Two paths, NO new npm deps (pure EIP-1193 window.ethereum):
 *   injected — eth_requestAccounts → personal_sign(message) → verify
 *   manual   — no wallet in the browser: paste address → get message → sign it
 *              in your wallet elsewhere → paste the signature → verify
 *
 * The server MINTS the exact EIP-4361 message (nonce endpoint), so we only sign
 * what it returns — no client-side domain/chain assembly. On success we call
 * onVerified(address); ModuleRunner then marks the module verified.
 *
 * Props: csrf (required), onVerified(address), lang
 */

const T = {
  bind: { ru: 'Привязать кошелёк', en: 'Bind wallet' },
  binding: { ru: 'Подпись…', en: 'Signing…' },
  manualToggle: { ru: 'Подписать вручную (без расширения)', en: 'Sign manually (no extension)' },
  injectedToggle: { ru: 'Использовать расширение кошелька', en: 'Use a wallet extension' },
  addressLabel: { ru: 'Адрес кошелька (0x…, 42 символа)', en: 'Wallet address (0x…, 42 chars)' },
  getMessage: { ru: 'Получить сообщение для подписи', en: 'Get the message to sign' },
  messageLabel: { ru: 'Сообщение — подпишите его в кошельке', en: 'Message — sign it in your wallet' },
  copy: { ru: 'Скопировать', en: 'Copy' },
  copied: { ru: 'Скопировано', en: 'Copied' },
  sigLabel: { ru: 'Вставьте подпись (0x…)', en: 'Paste the signature (0x…)' },
  verifySig: { ru: 'Проверить подпись', en: 'Verify signature' },
  verifying: { ru: 'Проверка…', en: 'Verifying…' },
  bound: { ru: 'Кошелёк привязан ✅', en: 'Wallet bound ✅' },
  errRejected: { ru: 'Подпись отклонена в кошельке.', en: 'Signature rejected in the wallet.' },
  errNoAcct: { ru: 'Не удалось получить адрес из кошелька.', en: 'Could not get an address from the wallet.' },
  errAddr: { ru: 'Адрес должен начинаться с 0x и быть длиной 42 символа.', en: 'Address must start with 0x and be 42 chars long.' },
  errAlreadyBound: { ru: 'Этот адрес уже привязан к другому аккаунту.', en: 'This address is already bound to another account.' },
  errSiwe: { ru: 'Проверка подписи не прошла. Повторите.', en: 'Signature verification failed. Try again.' },
  errOffline: { ru: 'API недоступен. Попробуйте позже.', en: 'API unavailable. Try again later.' },
  hint: { ru: 'Подпись бесплатна и не двигает средства — это не транзакция.', en: 'Signing is free and moves no funds — it is not a transaction.' },
};

function isAddr(a) {
  return typeof a === 'string' && /^0x[0-9a-fA-F]{40}$/.test(a.trim());
}

export default function SiweBinder({ csrf, onVerified, lang = 'ru' }) {
  const tr = (k) => (T[k] ? T[k][lang] ?? T[k].ru : k);
  const [hasInjected, setHasInjected] = useState(false);
  const [manual, setManual] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);

  // manual-flow state
  const [address, setAddress] = useState('');
  const [message, setMessage] = useState('');
  const [signature, setSignature] = useState('');
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const injected = typeof window !== 'undefined' && !!window.ethereum;
    setHasInjected(injected);
    setManual(!injected);
  }, []);

  const mapErr = useCallback((e) => {
    if (e && e.code === 4001) return tr('errRejected');
    if (e instanceof ApiError) {
      if (e.isOffline) return tr('errOffline');
      if (e.status === 409) return tr('errAlreadyBound');
      if (e.status === 400) return tr('errSiwe');
      if (typeof e.detail === 'string') return e.detail;
    }
    return tr('errOffline');
  }, [lang]); // eslint-disable-line react-hooks/exhaustive-deps

  async function getNonce(addr) {
    const res = await apiSend('/wallet/siwe/nonce', { method: 'POST', body: { address: addr }, csrf });
    if (!res || !res.message) throw new ApiError(0, 'no message');
    return res.message;
  }

  async function verify(addr, msg, sig) {
    const res = await apiSend('/wallet/siwe/verify', {
      method: 'POST', body: { address: addr, message: msg, signature: sig }, csrf,
    });
    if (!res || !res.ok) throw new ApiError(0, 'verify failed');
    return res.address || addr;
  }

  /* injected: one click → request account → nonce → personal_sign → verify */
  async function bindInjected() {
    setBusy(true); setError(null);
    try {
      const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' });
      const addr = accounts && accounts[0];
      if (!isAddr(addr)) throw new ApiError(0, tr('errNoAcct'));
      const msg = await getNonce(addr);
      const sig = await window.ethereum.request({ method: 'personal_sign', params: [msg, addr] });
      const bound = await verify(addr, msg, sig);
      setDone(true);
      if (onVerified) onVerified(bound);
    } catch (e) {
      setError(e instanceof ApiError && e.message === tr('errNoAcct') ? tr('errNoAcct') : mapErr(e));
    } finally {
      setBusy(false);
    }
  }

  /* manual step 1: fetch the message for a pasted address */
  async function manualGetMessage() {
    setError(null);
    const addr = address.trim();
    if (!isAddr(addr)) { setError(tr('errAddr')); return; }
    setBusy(true);
    try {
      const msg = await getNonce(addr);
      setMessage(msg);
    } catch (e) {
      setError(mapErr(e));
    } finally {
      setBusy(false);
    }
  }

  /* manual step 2: verify the pasted signature */
  async function manualVerify() {
    setError(null);
    if (!signature.trim()) return;
    setBusy(true);
    try {
      const bound = await verify(address.trim(), message, signature.trim());
      setDone(true);
      if (onVerified) onVerified(bound);
    } catch (e) {
      setError(mapErr(e));
    } finally {
      setBusy(false);
    }
  }

  function copyMessage() {
    try {
      navigator.clipboard.writeText(message).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      });
    } catch { /* clipboard unavailable */ }
  }

  if (done) return <div style={okBox}>{tr('bound')}</div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <p style={hint}>{tr('hint')}</p>

      {!manual && (
        <>
          <button type="button" disabled={busy} onClick={bindInjected} style={primaryBtn}>
            {busy ? tr('binding') : tr('bind')}
          </button>
          <button type="button" onClick={() => setManual(true)} style={linkBtn}>{tr('manualToggle')}</button>
        </>
      )}

      {manual && (
        <>
          <label style={fieldLabel}>{tr('addressLabel')}</label>
          <input value={address} onChange={(e) => setAddress(e.target.value)} placeholder="0x…" style={input} />

          {!message && (
            <button type="button" disabled={busy || !address.trim()} onClick={manualGetMessage} style={primaryBtn}>
              {busy ? tr('verifying') : tr('getMessage')}
            </button>
          )}

          {message && (
            <>
              <label style={fieldLabel}>{tr('messageLabel')}</label>
              <textarea readOnly value={message} rows={9} style={{ ...input, fontFamily: 'var(--font-mono)', fontSize: 12 }} />
              <button type="button" onClick={copyMessage} style={ghostBtn}>{copied ? tr('copied') : tr('copy')}</button>

              <label style={fieldLabel}>{tr('sigLabel')}</label>
              <textarea value={signature} onChange={(e) => setSignature(e.target.value)} rows={3} placeholder="0x…" style={{ ...input, fontFamily: 'var(--font-mono)', fontSize: 12 }} />
              <button type="button" disabled={busy || !signature.trim()} onClick={manualVerify} style={primaryBtn}>
                {busy ? tr('verifying') : tr('verifySig')}
              </button>
            </>
          )}

          {hasInjected && (
            <button type="button" onClick={() => { setManual(false); setMessage(''); setSignature(''); }} style={linkBtn}>
              {tr('injectedToggle')}
            </button>
          )}
        </>
      )}

      {error && <div style={dangerBox} role="alert">{error}</div>}
    </div>
  );
}

/* ── styles ───────────────────────────────────────────────────────────────── */
const fieldLabel = { fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' };
const input = { padding: '10px 12px', borderRadius: 'var(--r-sm)', border: '1px solid var(--border-strong)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 14, fontFamily: 'var(--font-sans)', resize: 'vertical', width: '100%', boxSizing: 'border-box' };
const primaryBtn = { padding: '11px 18px', borderRadius: 'var(--r-sm)', border: '1px solid var(--accent-border)', background: 'var(--accent-bg)', color: 'var(--accent)', fontSize: 15, fontWeight: 700, cursor: 'pointer', fontFamily: 'var(--font-sans)', alignSelf: 'flex-start' };
const ghostBtn = { background: 'transparent', border: '1px solid var(--border-strong)', borderRadius: 'var(--r-sm)', color: 'var(--text-secondary)', padding: '7px 14px', cursor: 'pointer', fontSize: 13, fontFamily: 'var(--font-sans)', alignSelf: 'flex-start' };
const linkBtn = { background: 'transparent', border: 'none', color: 'var(--text-muted)', textDecoration: 'underline', cursor: 'pointer', fontSize: 13, alignSelf: 'flex-start', padding: 0, fontFamily: 'var(--font-sans)' };
const okBox = { background: 'var(--ok-bg)', border: '1px solid var(--ok-border)', borderRadius: 'var(--r-md)', padding: '14px 16px', color: 'var(--ok)', fontSize: 15, fontWeight: 600 };
const dangerBox = { background: 'var(--danger-bg)', border: '1px solid var(--danger-border)', borderRadius: 'var(--r-md)', padding: '12px 16px', color: 'var(--danger)', fontSize: 13.5, lineHeight: 1.5 };
const hint = { fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.5, margin: 0 };
