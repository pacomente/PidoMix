export function money(value: number | null | undefined): string {
  const n = Math.round(Number(value || 0));
  return (n < 0 ? '-$' : '$') + String(Math.abs(n)).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
}

export const km = (v: number | null | undefined) => (v === null || v === undefined ? '' : v < 1 ? `${Math.round(v * 1000 / 50) * 50} m` : `${v.toFixed(1).replace('.', ',')} km`);

export function timeOf(iso: string) {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}
