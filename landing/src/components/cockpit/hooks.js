/*
 * cockpit/hooks.js — React hooks shared by the Cockpit primitives.
 *
 * useLang() — mirrors DashboardLive's spa_lang subscription so every primitive is bilingual
 * with zero per-file plumbing. usePrefersReducedMotion() — one source of truth for the motion
 * doctrine (no animated transitions when the OS asks for stillness).
 */
import { useState, useEffect } from 'react';
import { readLang } from './lib.js';

export function useLang() {
  const [lang, setLang] = useState('en');
  useEffect(() => {
    const read = () => setLang(readLang());
    read();
    const prev = window.__renderLive;
    window.__renderLive = () => { read(); if (typeof prev === 'function') try { prev(); } catch {} };
    const onStorage = (e) => { if (e.key === 'spa_lang') read(); };
    window.addEventListener('storage', onStorage);
    const id = setInterval(read, 1000);
    return () => {
      window.removeEventListener('storage', onStorage);
      clearInterval(id);
      if (window.__renderLive) window.__renderLive = prev;
    };
  }, []);
  return lang;
}

export function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const on = () => setReduced(mq.matches);
    on();
    mq.addEventListener ? mq.addEventListener('change', on) : mq.addListener(on);
    return () => { mq.removeEventListener ? mq.removeEventListener('change', on) : mq.removeListener(on); };
  }, []);
  return reduced;
}
