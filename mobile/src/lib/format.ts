/** $13.500 (formato argentino, sin decimales salvo que haya centavos). */
export function money(value: number | null | undefined): string {
  const n = Number(value || 0);
  const hasCents = Math.round(n * 100) % 100 !== 0;
  const abs = Math.abs(n).toFixed(hasCents ? 2 : 0);
  const [int, dec] = abs.split('.');
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  return (n < 0 ? '-$' : '$') + grouped + (dec ? ',' + dec : '');
}

export function km(value: number | null | undefined): string {
  if (value === null || value === undefined) return '';
  return value < 1 ? `${Math.round((value * 1000) / 50) * 50} m` : `${value.toFixed(1).replace('.', ',')} km`;
}

/** Color pastel a partir del "hue" que manda el backend para locales y productos sin foto. */
export const placeholderColor = (hue: number) => `hsl(${hue}, 85%, 92%)`;

export function timeOf(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}
