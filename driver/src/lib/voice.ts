import * as Speech from 'expo-speech';
import { useCallback, useEffect, useRef, useState } from 'react';

import { load, save } from './storage';
import type { RouteStep } from './types';

/** La app habla en castellano (Argentina si el teléfono tiene la voz; si no, la que haya en español). */
export function say(text: string) {
  if (!text) return;
  Speech.stop();
  Speech.speak(text, { language: 'es-AR', rate: 1.0, pitch: 1.0 });
}

/** Indicaciones habladas prendidas o apagadas (se recuerda en el teléfono). */
export function useVoicePref() {
  const [on, setOn] = useState(true);
  useEffect(() => { load('voice', true).then(setOn); }, []);
  const set = useCallback((v: boolean) => { setOn(v); save('voice', v); if (!v) Speech.stop(); }, []);
  return [on, set] as const;
}

const SOON_M = 150;  // "En 150 metros, doblá..." y después, al llegar al giro, solo la maniobra

/** Dice cada giro dos veces: un aviso antes (a ~150 m) y al llegar. Nunca repite lo mismo. */
export function useSpokenGuidance(on: boolean, step: RouteStep | null, toStep: number | null, routeKey: string) {
  const said = useRef<Set<string>>(new Set());
  useEffect(() => { said.current = new Set(); }, [routeKey]);
  useEffect(() => {
    if (!on || !step) return;
    const id = `${step.lat},${step.lng},${step.text}`;
    if (step.type === 'arrive') {
      if (toStep !== null && toStep < 60 && !said.current.has(id + ':llego')) { said.current.add(id + ':llego'); say(step.text); }
      return;
    }
    if (!said.current.has(id + ':nuevo')) {  // giro nuevo: lo anuncia con la distancia
      said.current.add(id + ':nuevo');
      if (toStep !== null && toStep > SOON_M) { say(`En ${toStep >= 1000 ? `${(toStep / 1000).toFixed(1).replace('.', ',')} kilómetros` : `${Math.round(toStep / 50) * 50} metros`}, ${step.text.toLowerCase()}`); return; }
    }
    if (toStep !== null && toStep <= SOON_M && !said.current.has(id + ':cerca')) {
      said.current.add(id + ':cerca');
      say(toStep < 40 ? step.text : `En ${Math.max(50, Math.round(toStep / 50) * 50)} metros, ${step.text.toLowerCase()}`);
    }
  }, [on, step, toStep]);
}
