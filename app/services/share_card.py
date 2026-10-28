"""Imagen para compartir el local (la que muestran WhatsApp, Instagram y Facebook al pegar el link).

1200x630 con el nombre, el rubro, la valoracion y "Pedí acá". Si el local tiene logo en Cloudinary se pone arriba;
solo se descarga de Cloudinary (nunca de otra direccion). Se guarda una hora en memoria por local.
"""
import io
import time
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
VIOLET, VIOLET_DARK, INK, MUTED = (108, 43, 217), (82, 25, 176), (30, 20, 51), (94, 102, 118)
TTL = 3600
_cache: dict[int, tuple[float, tuple, bytes]] = {}


FONTS = Path(__file__).resolve().parent.parent / 'assets' / 'fonts'  # DejaVu Sans (libre): tiene tildes, ñ y ★


def _font(size: int, bold: bool = False):
    try:
        return ImageFont.truetype(str(FONTS / ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')), size)
    except OSError:
        return ImageFont.load_default(size=size)


def _cut(draw, text: str, font, max_w: int) -> str:
    while draw.textlength(text, font=font) > max_w and len(text) > 4:
        text = text[:-2].rstrip() + '…'
    return text


def _fit(draw: ImageDraw.ImageDraw, text: str, max_w: int, size: int = 70, min_size: int = 50) -> tuple[list[str], object]:
    """El nombre en un renglon (achicando la letra) o, si es muy largo, en dos."""
    while size >= min_size:
        if draw.textlength(text, font=_font(size, True)) <= max_w:
            return [text], _font(size, True)
        size -= 4
    font = _font(46, True)
    words, first = text.split(), ''
    while words and draw.textlength((first + ' ' + words[0]).strip(), font=font) <= max_w:
        first = (first + ' ' + words.pop(0)).strip()
    if not first:  # una sola palabra larguisima
        return [_cut(draw, text, font, max_w)], font
    return [first, _cut(draw, ' '.join(words), font, max_w)] if words else [first], font


def _logo(url: str | None) -> Image.Image | None:
    if not url or not url.startswith('https://res.cloudinary.com/'):
        return None
    small = url.replace('/image/upload/', '/image/upload/c_fill,w_220,h_220,f_png/', 1)
    try:
        r = httpx.get(small, timeout=4)
        if r.status_code != 200 or len(r.content) > 2_000_000:
            return None
        return Image.open(io.BytesIO(r.content)).convert('RGBA').resize((180, 180))
    except Exception:
        return None


def render(store, category: str | None, base_url: str) -> bytes:
    key = (store.name, category, store.logo_url, float(store.rating_avg or 0), store.rating_count, store.delivery_enabled)
    hit = _cache.get(store.id)
    if hit and hit[1] == key and time.monotonic() - hit[0] < TTL:
        return hit[2]
    img = Image.new('RGB', (W, H), VIOLET)
    d = ImageDraw.Draw(img)
    for i in range(H):  # degradé suave
        t = i / H
        d.line([(0, i), (W, i)], fill=tuple(int(VIOLET[c] * (1 - t) + VIOLET_DARK[c] * t) for c in range(3)))
    d.rounded_rectangle([60, 60, W - 60, H - 60], radius=40, fill=(255, 255, 255))
    x = 110
    logo = _logo(store.logo_url)
    if logo is not None:
        mask = Image.new('L', logo.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, *logo.size], radius=36, fill=255)
        img.paste(logo, (x, 110), mask)
    else:
        d.rounded_rectangle([x, 110, x + 180, 290], radius=36, fill=(240, 233, 253))
        initials = ''.join(w[0] for w in [w for w in store.name.split() if len(w) > 2][:2]).upper() or store.name[:1].upper() or 'T'
        f = _font(80, True)
        d.text((x + 90, 200), initials, font=f, fill=VIOLET_DARK, anchor='mm')
    tx = x + 220
    lines, f = _fit(d, store.name, W - 110 - tx)
    if len(lines) == 1:
        d.text((tx, 130), lines[0], font=f, fill=INK)
    else:
        d.text((tx, 112), lines[0], font=f, fill=INK)
        d.text((tx, 168), lines[1], font=f, fill=INK)
    sub = ' · '.join(p for p in [category, f'★ {float(store.rating_avg):.1f} ({store.rating_count})'.replace('.', ',') if store.rating_count else None] if p)
    if sub:
        d.text((tx, 230), sub, font=_font(36), fill=MUTED)
    d.text((x, 350), 'Con envío o para retirar' if store.delivery_enabled else 'Para retirar en el local', font=_font(42), fill=INK)
    d.rounded_rectangle([x, 430, x + 420, 520], radius=45, fill=VIOLET)
    d.text((x + 210, 475), 'Pedí acá', font=_font(44, True), fill=(255, 255, 255), anchor='mm')
    host = base_url.split('://', 1)[-1].rstrip('/')
    d.text((W - 110, 475), host, font=_font(32), fill=MUTED, anchor='rm')
    out = io.BytesIO()
    img.save(out, 'PNG', optimize=True)
    data = out.getvalue()
    if len(_cache) > 500:
        _cache.clear()
    _cache[store.id] = (time.monotonic(), key, data)
    return data
