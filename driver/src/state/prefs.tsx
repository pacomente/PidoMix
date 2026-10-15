import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useColorScheme } from 'react-native';

import { load, save } from '@/lib/storage';
import { palettes, type Palette } from '@/lib/theme';

export type ThemePref = 'auto' | 'light' | 'dark';
/** con qué app navega al tocar "Navegar": Google Maps, Waze o preguntar cada vez */
export type NavApp = 'google' | 'waze' | 'ask';

type Prefs = { theme: ThemePref; navApp: NavApp };
const DEFAULTS: Prefs = { theme: 'auto', navApp: 'ask' };

type Ctx = Prefs & { c: Palette; set: (p: Partial<Prefs>) => void };
const PrefsCtx = createContext<Ctx>({ ...DEFAULTS, c: palettes.light, set: () => {} });

/** Preferencias del repartidor guardadas en el teléfono: tema (claro, oscuro o según el teléfono) y app de navegación. */
export function PrefsProvider({ children }: { children: ReactNode }) {
  const system = useColorScheme();
  const [prefs, setPrefs] = useState<Prefs>(DEFAULTS);
  useEffect(() => { load<Partial<Prefs>>('prefs', {}).then(p => setPrefs(cur => ({ ...cur, ...p }))); }, []);
  const set = useCallback((p: Partial<Prefs>) => setPrefs(cur => { const next = { ...cur, ...p }; save('prefs', next); return next; }), []);
  const isDark = prefs.theme === 'dark' || (prefs.theme === 'auto' && system === 'dark');
  const value = useMemo(() => ({ ...prefs, c: isDark ? palettes.dark : palettes.light, set }), [prefs, isDark, set]);
  return <PrefsCtx.Provider value={value}>{children}</PrefsCtx.Provider>;
}

export const usePrefs = () => useContext(PrefsCtx);
/** la paleta del tema actual */
export const useColors = () => useContext(PrefsCtx).c;
