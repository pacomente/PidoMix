/**
 * Links que abren la app. trappi://auth es la vuelta del ingreso con código por email: la resuelve
 * WebBrowser.openAuthSessionAsync (lib/auth.ts), así que el router no navega a ningún lado.
 */
function isAuthReturn(path: string): boolean {
  if (/^trappi:\/\/auth([/?#]|$)/i.test(path)) return true;  // trappi://auth?code=...
  const rest = path.replace(/^[a-z][\w+.-]*:\/\/[^/]*/i, '');   // exp://192.168.0.2:8081/--/auth?code=... (Expo Go)
  return /(^|\/)(--\/)?auth([/?#]|$)/.test(rest);
}

export function redirectSystemPath({ path, initial }: { path: string; initial: boolean }) {
  try {
    if (isAuthReturn(path)) return initial ? '/' : null;
    return path;
  } catch {
    return '/';
  }
}
