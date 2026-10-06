import * as Crypto from 'expo-crypto';
import * as Linking from 'expo-linking';
import * as SecureStore from 'expo-secure-store';
import * as WebBrowser from 'expo-web-browser';

import { API_URL, ApiError, api } from './api';
import type { Account } from './types';

const TOKEN_KEY = 'trappi.client-token';

/** El token de la cuenta se guarda en el almacenamiento seguro del teléfono (Keystore). */
export async function loadToken(): Promise<string | null> {
  try { return await SecureStore.getItemAsync(TOKEN_KEY); } catch { return null; }
}

export async function saveToken(token: string | null): Promise<void> {
  try {
    if (token) await SecureStore.setItemAsync(TOKEN_KEY, token);
    else await SecureStore.deleteItemAsync(TOKEN_KEY);
  } catch {
    // sin almacenamiento seguro: la sesión dura mientras la app esté abierta
  }
}

const toHex = (bytes: Uint8Array) => Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
const base64Url = (b64: string) => b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

/**
 * Entrar con Google: se abre el navegador del sistema en el sitio de Trappi, que hace el ingreso con
 * Google y vuelve a la app (trappi://auth) con un código de un solo uso. La app lo cambia por su token
 * mostrando el "verifier" (PKCE): otra app que intercepte el link no puede usar el código.
 * Devuelve null si el cliente cerró el navegador.
 */
export async function loginWithGoogle(loginPath = '/ingresar/google?app=1'): Promise<{ token: string; account: Account } | null> {
  const verifier = toHex(Crypto.getRandomBytes(48));
  const challenge = base64Url(await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, verifier, { encoding: Crypto.CryptoEncoding.BASE64 }));
  const redirect = Linking.createURL('auth');
  const url = `${API_URL}${loginPath}&challenge=${encodeURIComponent(challenge)}&redirect=${encodeURIComponent(redirect)}`;
  const result = await WebBrowser.openAuthSessionAsync(url, redirect);
  if (result.type !== 'success') return null;
  const params = Linking.parse(result.url).queryParams ?? {};
  const code = typeof params.code === 'string' ? params.code : '';
  const error = typeof params.error === 'string' ? params.error : '';
  if (error === 'cancelado') return null;
  if (!code) throw new ApiError(error || 'No pudimos completar el ingreso. Probá de nuevo.', 400);
  const res = await api.exchange(code, verifier);
  return { token: res.token, account: res.account };
}

export function openWebPage(path: string) {
  return WebBrowser.openBrowserAsync(API_URL + path);
}
