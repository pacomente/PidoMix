"""Carteles con QR en PDF (A5, para imprimir): el QR del menú y el QR de Puntos Trappi del mostrador.

El PDF se arma a mano, sin dependencias: texto con Helvetica (viene en todos los lectores de PDF, con tildes y ñ) y el QR
dibujado en vectores, así se imprime nítido en cualquier tamaño.
"""
from __future__ import annotations

import re
import unicodedata

import segno

W, H = 419.53, 595.28  # A5 en puntos
INK, PURPLE, GRAY, LINE = (0.106, 0.071, 0.188), (0.424, 0.169, 0.851), (0.431, 0.404, 0.522), (0.906, 0.882, 0.945)

_REG = ('278 278 355 556 556 889 667 191 333 333 389 584 278 333 278 278 556 556 556 556 556 556 556 556 556 556 278 278 584 584 584 556 '
        '1015 667 667 722 722 667 611 778 722 278 500 667 556 833 722 778 667 778 722 667 611 722 667 944 667 667 611 278 278 278 469 556 '
        '333 556 556 500 556 556 278 556 556 222 222 500 222 833 556 556 556 556 333 500 278 556 500 722 500 500 500 334 260 334 584')
_BOLD = ('278 333 474 556 556 889 722 238 333 333 389 584 278 333 278 278 556 556 556 556 556 556 556 556 556 556 333 333 584 584 584 611 '
         '975 722 722 722 722 667 611 778 722 278 556 722 611 833 722 778 667 778 722 667 611 722 667 944 667 667 611 333 278 333 584 556 '
         '333 556 611 556 611 556 333 611 611 278 278 556 278 889 611 611 611 611 389 556 333 611 556 778 556 556 500 389 280 389 584')
WIDTHS = {'F1': [int(x) for x in _REG.split()], 'F2': [int(x) for x in _BOLD.split()]}


def _clean(text: str) -> str:
    return (text.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'").replace('—', '-').replace('–', '-')
            .replace('…', '...').replace(' ', ' '))


def _width(text: str, font: str, size: float) -> float:
    table, total = WIDTHS[font], 0
    for ch in text:
        base = unicodedata.normalize('NFD', ch)[0]
        o = ord(base)
        total += table[o - 32] if 32 <= o <= 126 else 556
    return total * size / 1000


def _enc(text: str) -> str:
    raw = _clean(text).encode('cp1252', 'replace').decode('latin-1')
    return raw.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


class _Page:
    def __init__(self):
        self.ops: list[str] = []

    def color(self, rgb, stroke=False):
        self.ops.append('%.3f %.3f %.3f %s' % (*rgb, 'RG' if stroke else 'rg'))

    def text(self, x, y, s, font='F1', size=12, rgb=INK):
        self.color(rgb)
        self.ops.append(f'BT /{font} {size} Tf {x:.2f} {y:.2f} Td ({_enc(s)}) Tj ET')

    def center(self, y, s, font='F1', size=12, rgb=INK):
        self.text((W - _width(s, font, size)) / 2, y, s, font, size, rgb)

    def round_rect(self, x, y, w, h, r, fill=None, stroke=None, lw=1.5):
        k = r * 0.5523
        p = [f'{x + r:.2f} {y:.2f} m', f'{x + w - r:.2f} {y:.2f} l',
             f'{x + w - r + k:.2f} {y:.2f} {x + w:.2f} {y + r - k:.2f} {x + w:.2f} {y + r:.2f} c', f'{x + w:.2f} {y + h - r:.2f} l',
             f'{x + w:.2f} {y + h - r + k:.2f} {x + w - r + k:.2f} {y + h:.2f} {x + w - r:.2f} {y + h:.2f} c', f'{x + r:.2f} {y + h:.2f} l',
             f'{x + r - k:.2f} {y + h:.2f} {x:.2f} {y + h - r + k:.2f} {x:.2f} {y + h - r:.2f} c', f'{x:.2f} {y + r:.2f} l',
             f'{x:.2f} {y + r - k:.2f} {x + r - k:.2f} {y:.2f} {x + r:.2f} {y:.2f} c', 'h']
        if fill:
            self.color(fill)
        if stroke:
            self.color(stroke, stroke=True)
            self.ops.append(f'{lw} w')
        self.ops += p
        self.ops.append('B' if fill and stroke else 'f' if fill else 'S')

    def qr(self, url, x, y, size):
        q = segno.make(url, error='q')
        rows = list(q.matrix)
        n = len(rows)
        m = size / n
        self.color(INK)
        for r, row in enumerate(rows):
            c = 0
            while c < n:
                if row[c]:
                    start = c
                    while c < n and row[c]:
                        c += 1
                    self.ops.append(f'{x + start * m:.3f} {y + size - (r + 1) * m:.3f} {(c - start) * m + 0.02:.3f} {m + 0.02:.3f} re')
                else:
                    c += 1
        self.ops.append('f')


def _wrap_rich(parts: list[tuple[str, str]], size: float, max_w: float) -> list[list[tuple[str, str]]]:
    """parts = [(fuente, texto)] -> renglones de [(fuente, pedazo)]. Corta solo en los espacios (lo pegado queda pegado)."""
    tokens = [(f, t) for f, text in parts for t in re.findall(r'\S+|\s+', text.replace('\n', ' '))]
    lines, line, used = [], [], 0.0
    for f, t in tokens:
        w = _width(t, f, size)
        if t.isspace():
            if line:
                line.append((f, ' '))
                used += _width(' ', f, size)
            continue
        if line and used + w > max_w:
            while line and line[-1][1] == ' ':
                line.pop()
            lines.append(line)
            line, used = [], 0.0
        line.append((f, t))
        used += w
    if line:
        lines.append(line)
    return lines


def _rich(text: str) -> list[tuple[str, str]]:
    """'Poné el **código** acá' -> [(F1, 'Poné el '), (F2, 'código'), (F1, ' acá')]."""
    out = []
    for i, chunk in enumerate(text.split('**')):
        if chunk:
            out.append(('F2' if i % 2 else 'F1', chunk))
    return out


def poster(title: list[str], sub: str, url: str, steps: list[str], store: str, shown_url: str) -> bytes:
    pg = _Page()
    # marca
    bw = 26 + 8 + _width('Trappi', 'F2', 22)
    bx = (W - bw) / 2
    pg.round_rect(bx, 532, 26, 26, 7, fill=PURPLE)
    pg.text(bx + 13 - _width('T', 'F2', 16) / 2, 539.5, 'T', 'F2', 16, (1, 1, 1))
    pg.text(bx + 34, 537, 'Trappi', 'F2', 22, PURPLE)
    # titulo y bajada
    y = 494
    for line in title:
        pg.center(y, line, 'F2', 28)
        y -= 31
    pg.center(y + 6, sub, 'F1', 12.5, GRAY)
    # QR
    qs, pad = 188, 17
    qy = y - 22 - qs
    pg.round_rect((W - qs) / 2 - pad, qy - pad, qs + 2 * pad, qs + 2 * pad, 14, fill=(1, 1, 1), stroke=LINE, lw=2)
    pg.qr(url, (W - qs) / 2, qy, qs)
    # pasos
    y = qy - pad - 26
    left, size = 52, 11.5
    for i, step in enumerate(steps, 1):
        lines = _wrap_rich(_rich(step), size, W - left - 46)
        pg.text(left - 16, y, f'{i}.', 'F2', size, PURPLE)
        for line in lines:
            x = left
            for f, w in line:
                pg.text(x, y, w, f, size)
                x += _width(w, f, size)
            y -= size * 1.45
        y -= 3
    # local
    pg.center(46, store[:48], 'F2', 16)
    shown = shown_url if len(shown_url) <= 80 else shown_url[:77] + '...'
    pg.center(30, shown, 'F1', 8, GRAY)
    return _document('\n'.join(pg.ops), title=f'{" ".join(title)} - {store}')


def _document(content: str, title: str) -> bytes:
    stream = content.encode('latin-1')
    objs = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>'.encode(),
        b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>',
        f'<< /Title ({_enc(title)}) /Creator (Trappi) >>'.encode('latin-1'),
    ]
    out, offsets = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n'), []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f'{i} 0 obj\n'.encode() + body + b'\nendobj\n'
    xref = len(out)
    out += f'xref\n0 {len(objs) + 1}\n0000000000 65535 f \n'.encode()
    for off in offsets:
        out += f'{off:010d} 00000 n \n'.encode()
    out += f'trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info {len(objs)} 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    return bytes(out)


def menu_poster(store_name: str, url: str) -> bytes:
    return poster(['Mirá el menú', 'y pedí acá'], 'Delivery o para retirar, sin hacer fila', url,
                  ['Escaneá este QR con la cámara del celular o con la app Trappi.',
                   f'Si tenés la app, se abre el menú de **{store_name}** ahí mismo. Si no, en la web.',
                   'Elegí, pagá como quieras y seguí tu pedido en vivo.'],
                  store_name, url.split('?')[0])


def points_poster(store_name: str, url: str) -> bytes:
    return poster(['Pagá con tus', 'Puntos Trappi'], 'Tus puntos son un descuento en esta compra', url,
                  ['Pedile al cajero **"pagar con Puntos Trappi"**.',
                   'Escaneá este QR con la cámara o con la app Trappi.',
                   'Poné el **código de 4 números** que aparece en la caja y confirmá.'],
                  store_name, url)
