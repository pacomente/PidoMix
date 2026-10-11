import { createAudioPlayer, setAudioModeAsync, type AudioPlayer } from 'expo-audio';
import { Vibration } from 'react-native';

// Sonidos dentro de la app (con la app abierta). Con la app en segundo plano suena la notificación del canal "viajes_nuevos".
// trappi_repartidor_nuevo: tres notas agudas, x2 (~2 s): se repite hasta que acepte o rechace la oferta.
// trappi_repartidor_aceptado: "ding" corto que confirma la acción.

const REPEAT_MS = 4000;  // ~2 s de sonido + 2 s de pausa, como la comandera

let ready: Promise<void> | null = null;
let offer: AudioPlayer | null = null;
let done: AudioPlayer | null = null;
let timer: ReturnType<typeof setInterval> | null = null;

function setup() {
  ready ??= setAudioModeAsync({ playsInSilentMode: true, shouldPlayInBackground: false, interruptionMode: 'duckOthers' })
    .catch(() => {})
    .then(() => {
      offer = createAudioPlayer(require('../../assets/sounds/trappi_repartidor_nuevo.wav'));
      done = createAudioPlayer(require('../../assets/sounds/trappi_repartidor_aceptado.wav'));
    })
    .catch(() => {});
  return ready;
}

function play(p: AudioPlayer | null) {
  if (!p) return;
  try {
    p.seekTo(0);
    p.play();
  } catch { /* sin audio: queda la vibración */ }
}

/** Oferta nueva: suena y vibra ahora y cada 4 s, hasta stopOfferAlarm(). */
export async function startOfferAlarm() {
  await setup();
  stopOfferAlarm();
  const ring = () => {
    play(offer);
    Vibration.vibrate([0, 500, 250, 500, 250, 500]);
  };
  ring();
  timer = setInterval(ring, REPEAT_MS);
}

export function stopOfferAlarm() {
  if (timer) clearInterval(timer);
  timer = null;
  try { offer?.pause(); } catch { /* nada */ }
  Vibration.cancel();
}

/** Confirmación corta: aceptó el viaje, retiró o entregó. */
export async function playConfirm() {
  await setup();
  play(done);
}
