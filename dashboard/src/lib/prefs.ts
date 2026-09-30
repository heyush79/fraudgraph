import { useCallback, useEffect, useState } from 'react';

/**
 * Per-viewer conveniences only (theme, a dismissed intro). Storage can be
 * missing or throw — private windows, blocked site data, embedded previews —
 * and every caller must work without it, so nothing here ever throws.
 */
export function readPref(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writePref(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: the preference lasts for this page only */
  }
}

export const INTRO_KEY = 'fraudgraph.intro';
const THEME_KEY = 'fraudgraph.theme';

export type Theme = 'dark' | 'light';

function systemTheme(): Theme {
  try {
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  } catch {
    return 'dark';
  }
}

function storedTheme(): Theme | null {
  const v = readPref(THEME_KEY);
  return v === 'dark' || v === 'light' ? v : null;
}

/**
 * The theme follows prefers-color-scheme until the viewer picks one; the pick
 * is stored and set as data-theme on <html>, which tokens.css keys off. The
 * inline script in index.html applies a stored pick before first paint.
 */
export function useTheme(): [Theme, () => void] {
  const [chosen, setChosen] = useState<Theme | null>(storedTheme);
  const [system, setSystem] = useState<Theme>(systemTheme);

  useEffect(() => {
    let mq: MediaQueryList;
    try {
      mq = window.matchMedia('(prefers-color-scheme: light)');
    } catch {
      return undefined;
    }
    const onChange = () => setSystem(mq.matches ? 'light' : 'dark');
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  useEffect(() => {
    if (chosen) document.documentElement.dataset.theme = chosen;
    else delete document.documentElement.dataset.theme;
  }, [chosen]);

  const theme = chosen ?? system;
  const toggle = useCallback(() => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark';
    writePref(THEME_KEY, next);
    setChosen(next);
  }, [theme]);

  return [theme, toggle];
}
