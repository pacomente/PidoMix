/**
 * Links de la web que abre la app (App Links de trappi.com.ar, por ejemplo el QR del menú de un local):
 * /tienda/slug → el local en la app · /puntos/... → el escáner de puntos con ese QR.
 */
export function webLinkTarget(path: string): string | null {
  const url = path.replace(/^https?:\/\/(www\.)?trappi\.com\.ar/i, '');
  const store = url.match(/^\/tienda\/([a-z0-9-]+)/i);
  if (store) return `/store/${store[1].toLowerCase()}`;
  if (/^\/puntos\/(q|local)\//i.test(url)) return `/scan?url=${encodeURIComponent('https://trappi.com.ar' + url.split('#')[0])}`;
  return null;
}

/** El slug del local si el texto es un link o QR de su menú (trappi.com.ar/tienda/slug). */
export function storeSlugFrom(text: string): string | null {
  const m = (text || '').trim().match(/^https?:\/\/(www\.)?trappi\.com\.ar\/tienda\/([a-z0-9-]+)/i);
  return m ? m[2].toLowerCase() : null;
}
