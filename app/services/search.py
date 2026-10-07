"""Búsqueda inteligente de comercios y productos (web, app y Trappi AI).

Entiende lo que escribe la gente, pero solo devuelve cosas reales de Trappi:
  - errores de tipeo ("ambuguesa" -> hamburguesa) contra las palabras del catálogo de su ciudad,
  - plurales y acentos ("pizzas", "café" = "cafe"),
  - sinónimos ("birra" -> cerveza, "coca" -> gaseosa),
  - pedidos en lenguaje natural: "algo dulce por menos de 5000", "abierto ahora", "con envío", "en promo", "barato".
No inventa: si no hay coincidencias, devuelve vacío y, si puede, una sugerencia ("¿Quisiste decir…?").
"""
import difflib
import re
import time
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..models import Category, Product, ProductStatus, Store
from . import cities, plans
from .store_hours import is_open

STOPWORDS = {'de', 'del', 'la', 'las', 'el', 'los', 'con', 'sin', 'y', 'o', 'un', 'una', 'unos', 'unas', 'para', 'por', 'que', 'algo', 'me', 'te',
             'quiero', 'busco', 'buscar', 'mio', 'mi', 'en', 'al', 'lo', 'muy', 'rico', 'rica', 'ricos', 'ricas', 'bueno', 'buena', 'buenos', 'buenas',
             'pedir', 'comer', 'tengo', 'ganas', 'hay', 'donde', 'quien', 'tiene', 'venden', 'vende', 'necesito', 'dame', 'mas', 'menos', 'hasta',
             'precio', 'pesos', 'mil', 'ahora', 'abierto', 'abiertos', 'abierta', 'envio', 'delivery', 'domicilio', 'casa', 'promo', 'promos',
             'promocion', 'promociones', 'oferta', 'ofertas', 'descuento', 'descuentos', 'barato', 'barata', 'baratos', 'economico', 'economica',
             'cerca', 'cercano', 'entre', 'maximo', 'max', 'mas', 'solo', 'hoy', 'noche', 'mediodia', 'tarde',
             'hola', 'buenas', 'buen', 'dia', 'gracias', 'chau', 'hambre', 'recomendas', 'recomendame', 'recomienda', 'sugerencia', 'cual', 'como'}

# palabras de la gente -> palabras del catálogo
SYNONYMS = {
    'birra': ['cerveza'], 'birras': ['cerveza'], 'cerve': ['cerveza'], 'chela': ['cerveza'],
    'coca': ['coca', 'gaseosa'], 'gaseosa': ['gaseosa', 'coca', 'sprite', 'fanta', 'pepsi'], 'refresco': ['gaseosa'],
    'burger': ['hamburguesa'], 'hamburgesa': ['hamburguesa'], 'hambur': ['hamburguesa'],
    'muzza': ['muzzarella', 'mozzarella'], 'muza': ['muzzarella'], 'mozza': ['muzzarella', 'mozzarella'], 'fugazza': ['fugazzeta', 'fugazza'],
    'pizza': ['pizza', 'pizzeria'], 'empa': ['empanada'], 'empanadas': ['empanada'],
    'papas': ['papas', 'fritas'], 'fritas': ['papas', 'fritas'],
    'helado': ['helado', 'heladeria'], 'cafe': ['cafe', 'cafeteria'], 'remedio': ['farmacia'], 'remedios': ['farmacia'],
    'pastillas': ['farmacia'], 'medicamento': ['farmacia'], 'super': ['almacen', 'supermercado'], 'mercado': ['almacen'],
    'sanguche': ['sandwich', 'sanguche'], 'sandwich': ['sandwich', 'sanguche'], 'lomo': ['lomo', 'lomito'], 'lomito': ['lomito', 'lomo'],
    'milanesa': ['milanesa', 'mila'], 'mila': ['milanesa'], 'sushi': ['sushi', 'roll'], 'pancho': ['pancho', 'hot dog'],
    'veggie': ['vegano', 'vegetariano'], 'vegano': ['vegano', 'vegetariano'], 'sano': ['ensalada', 'light', 'saludable'],
}
# antojos -> palabras del catálogo (se buscan juntas, alcanza con una)
CRAVINGS = {
    'dulce': ['postre', 'postres', 'helado', 'torta', 'chocolate', 'alfajor', 'flan', 'brownie', 'dulce', 'medialuna', 'factura', 'budin', 'cookie'],
    'postre': ['postre', 'postres', 'helado', 'torta', 'flan', 'brownie', 'tiramisu'],
    'tomar': ['bebida', 'bebidas', 'gaseosa', 'agua', 'jugo', 'cerveza', 'vino', 'cafe', 'licuado'],
    'bebida': ['bebida', 'bebidas', 'gaseosa', 'agua', 'jugo', 'cerveza'],
    'desayuno': ['cafe', 'medialuna', 'factura', 'tostado', 'licuado', 'desayuno'],
    'merienda': ['cafe', 'medialuna', 'factura', 'torta', 'tostado', 'merienda'],
    'salado': ['pizza', 'empanada', 'hamburguesa', 'tarta', 'sandwich', 'papas'],
    'picada': ['picada', 'fiambre', 'queso', 'papas'],
}
MAX_CANDIDATES = 3000
_vocab_cache: dict = {}  # city_id -> (expira, palabras)


def plain(text: str | None) -> str:
    text = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9$.,\s]', ' ', text)


def stem(word: str) -> str:
    """Plural simple: pizzas -> pizza, empanadas -> empanada, panes -> pan."""
    if len(word) > 4 and word.endswith('es') and word[-3] not in 'aeiou':
        return word[:-2]
    if len(word) > 3 and word.endswith('s'):
        return word[:-1]
    return word


def words_of(text: str | None) -> list[str]:
    return [stem(w) for w in re.findall(r'[a-z0-9]+', plain(text)) if len(w) > 1]


# ---------- lo que pidió la persona ----------

@dataclass
class Query:
    raw: str
    terms: list[str] = field(default_factory=list)       # palabras a buscar (ya corregidas)
    groups: list[list[str]] = field(default_factory=list)  # por cada palabra, sus alternativas (sinónimos, antojos)
    max_price: float | None = None
    min_price: float | None = None
    open_now: bool = False
    delivery: bool = False
    promo: bool = False
    cheap: bool = False
    near: bool = False
    corrected: str | None = None                          # "¿Quisiste decir …?" / "Mostrando resultados para …"
    craving: str | None = None

    @property
    def labels(self) -> list[str]:
        """Lo que se entendió, para mostrarlo como chips."""
        from .formatting import money
        out = []
        if self.craving:
            out.append({'dulce': 'Algo dulce', 'postre': 'Postres', 'tomar': 'Para tomar', 'bebida': 'Bebidas', 'desayuno': 'Desayuno',
                        'merienda': 'Merienda', 'salado': 'Algo salado', 'picada': 'Picada'}.get(self.craving, self.craving.capitalize()))
        if self.min_price and self.max_price:
            out.append(f'Entre {money(self.min_price)} y {money(self.max_price)}')
        elif self.max_price:
            out.append(f'Hasta {money(self.max_price)}')
        elif self.min_price:
            out.append(f'Desde {money(self.min_price)}')
        if self.open_now:
            out.append('Abiertos ahora')
        if self.delivery:
            out.append('Con envío')
        if self.promo:
            out.append('En promoción')
        if self.cheap:
            out.append('Más baratos primero')
        if self.near:
            out.append('Más cerca primero')
        return out

    @property
    def has_filters(self) -> bool:
        return any((self.max_price, self.min_price, self.open_now, self.delivery, self.promo, self.cheap, self.near))


def _amount(num: str, mult: str | None) -> float | None:
    text = num.replace('.', '').replace(',', '.') if re.fullmatch(r'\d{1,3}(\.\d{3})+(,\d+)?', num) else num.replace(',', '.')
    try:
        value = float(text)
    except ValueError:
        return None
    if mult and mult.strip() in ('mil', 'k', 'lucas', 'luca'):
        value *= 1000
    return value


def parse(raw: str, vocab: set[str] | None = None) -> Query:
    q = Query(raw=raw.strip()[:100])
    text = plain(q.raw)
    money_re = r'\$?\s*(\d[\d.,]*)\s*(mil|k|lucas?)?'
    m = re.search(r'entre\s+' + money_re + r'\s+y\s+' + money_re, text)
    if m:
        q.min_price, q.max_price = _amount(m.group(1), m.group(2) or (m.group(4) if (_amount(m.group(1), None) or 0) < 1000 else None)), _amount(m.group(3), m.group(4))
        text = text.replace(m.group(0), ' ')
    m = re.search(r'(?:menos de|hasta|maximo|max|no mas de|por debajo de|<)\s*' + money_re, text)
    if m:
        q.max_price = _amount(m.group(1), m.group(2))
        text = text.replace(m.group(0), ' ')
    m = re.search(r'(?:mas de|desde|arriba de|>)\s*' + money_re, text)
    if m:
        q.min_price = _amount(m.group(1), m.group(2))
        text = text.replace(m.group(0), ' ')
    tokens = re.findall(r'[a-z0-9]+', text)
    q.open_now = any(t in ('abierto', 'abiertos', 'abierta', 'abiertas') for t in tokens) or 'ahora' in tokens
    q.delivery = any(t in ('envio', 'delivery', 'domicilio') for t in tokens) or 'a casa' in text
    q.promo = any(t in ('promo', 'promos', 'promocion', 'promociones', 'oferta', 'ofertas', 'descuento', 'descuentos') for t in tokens)
    q.cheap = any(t in ('barato', 'barata', 'baratos', 'baratas', 'economico', 'economica') for t in tokens)
    q.near = any(t in ('cerca', 'cercano', 'cercanos') for t in tokens)
    corrected_any = False
    shown = []
    for t in tokens:
        if t in STOPWORDS or t.isdigit() or len(t) < 2:
            continue
        base = stem(t)
        if t in CRAVINGS or base in CRAVINGS:
            q.craving = q.craving or (t if t in CRAVINGS else base)
            q.groups.append([stem(w) for w in CRAVINGS[q.craving]])
            continue
        alts = [stem(w) for w in SYNONYMS.get(t, SYNONYMS.get(base, []))]
        fixed = base
        if vocab and base not in vocab and not alts and len(base) >= 4:
            close = difflib.get_close_matches(base, vocab, n=1, cutoff=0.8)
            if close:
                fixed = close[0]
                corrected_any = True
        q.terms.append(fixed)
        shown.append(fixed)
        q.groups.append(sorted({fixed, *alts}))
    if corrected_any:
        q.corrected = ' '.join(shown)
    return q


# ---------- catálogo ----------

def _products(db: Session, city_id):
    return db.scalars(select(Product).options(joinedload(Product.store).selectinload(Store.hours), joinedload(Product.store).selectinload(Store.zones),
                                              joinedload(Product.store).joinedload(Store.store_category), joinedload(Product.category),
                                              selectinload(Product.modifier_groups)).where(
        Product.status == ProductStatus.ACTIVO, Product.deleted.is_(False), plans.visible_product_clause(), cities.product_clause(city_id))
        .order_by(Product.featured.desc(), Product.display_order, Product.id).limit(MAX_CANDIDATES)).unique().all()


def _stores(db: Session, city_id):
    return db.scalars(select(Store).options(joinedload(Store.store_category), selectinload(Store.hours), selectinload(Store.zones)).where(
        plans.visible_clause(), cities.store_clause(city_id)).order_by(Store.featured.desc(), Store.name)).unique().all()


def vocabulary(db: Session, city_id) -> set[str]:
    """Palabras del catálogo de la ciudad (para corregir errores de tipeo). Se guarda 5 minutos."""
    hit = _vocab_cache.get(city_id)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    vocab = set()
    for p in _products(db, city_id):
        vocab.update(words_of(p.name))
        vocab.update(words_of(p.category.name if p.category else ''))
    for s in _stores(db, city_id):
        vocab.update(words_of(s.name))
        vocab.update(words_of(s.store_category.name if s.store_category else ''))
    for c in db.scalars(select(Category).where(Category.active)).all():
        vocab.update(words_of(c.name))
    vocab = {w for w in vocab if len(w) >= 3}
    _vocab_cache[city_id] = (time.monotonic() + 300, vocab)
    return vocab


def _hits(group: list[str], fields: list[tuple[list[str], float]]) -> float:
    """Mejor coincidencia de una palabra (o sus alternativas) en los campos, con su peso."""
    best = 0.0
    for alt in group:
        for words, weight in fields:
            if alt in words:
                best = max(best, weight)
            elif len(alt) >= 4 and any(w.startswith(alt) or (len(w) >= 4 and alt.startswith(w)) for w in words):
                best = max(best, weight * 0.7)
    return best


@dataclass
class Result:
    query: Query
    products: list = field(default_factory=list)
    stores: list = field(default_factory=list)
    categories: list = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.products or self.stores or self.categories)


def run(db: Session, raw: str, city_id=None, loc: dict | None = None, product_limit: int = 60, store_limit: int = 24) -> Result:
    from .geo import coverage
    q = parse(raw, vocabulary(db, city_id))
    res = Result(q)
    if not q.groups and not q.has_filters:
        return res
    scored = []
    for p in _products(db, city_id):
        s = p.store
        if p.stock is not None and p.stock <= 0:
            continue
        price = float(p.price)
        if q.max_price is not None and price > q.max_price or q.min_price is not None and price < q.min_price:
            continue
        promo = bool(p.previous_price and p.previous_price > p.price)
        if q.promo and not promo:
            continue
        if q.open_now and not is_open(s):
            continue
        if q.delivery and not s.delivery_enabled:
            continue
        score = 0.0
        if q.groups:
            fields = [(words_of(p.name), 3.0), (words_of(p.category.name if p.category else ''), 2.0), (words_of(p.description), 1.0),
                      (words_of(s.name), 1.2), (words_of(s.store_category.name if s.store_category else ''), 0.8)]
            hits = [_hits(g, fields) for g in q.groups]
            matched = sum(1 for h in hits if h > 0)
            if matched < max(1, (len(q.groups) + 1) // 2):  # al menos la mitad de lo que pidió
                continue
            score = sum(hits) + matched
        score += (0.4 if p.featured else 0) + (0.3 if promo else 0) + (0.5 if is_open(s) else -0.5)
        if q.delivery and loc and coverage(s, loc).covered is False:
            continue
        scored.append((score, price, p))
    if q.cheap or (q.max_price and not q.groups):
        scored.sort(key=lambda x: (x[1], -x[0]))
    else:
        scored.sort(key=lambda x: (-x[0], x[1]))
    res.products = [p for _, _, p in scored[:product_limit]]

    # comercios: por su nombre o rubro, o porque tienen productos que coinciden
    from_products = {}
    for score, _, p in scored:
        from_products.setdefault(p.store_id, score)
    stores = []
    for s in _stores(db, city_id):
        if q.open_now and not is_open(s) or q.delivery and not s.delivery_enabled:
            continue
        if q.delivery and loc and coverage(s, loc).covered is False:
            continue
        score = 0.0
        if q.groups:
            fields = [(words_of(s.name), 3.0), (words_of(s.store_category.name if s.store_category else ''), 2.0), (words_of(s.description), 1.0)]
            hits = [_hits(g, fields) for g in q.groups]
            if any(hits):
                score = sum(hits) + 2
        if s.id in from_products:
            score = max(score, 1.0 + from_products[s.id] * 0.3)
        if q.promo and s.id not in from_products:
            continue
        if score <= 0 and q.groups:
            continue
        if not q.groups and s.id not in from_products:
            continue
        stores.append((score + (0.5 if is_open(s) else 0), s))
    if q.near and loc:
        stores.sort(key=lambda x: (coverage(x[1], loc).distance is None, coverage(x[1], loc).distance or 0))
    else:
        stores.sort(key=lambda x: -x[0])
    res.stores = [s for _, s in stores[:store_limit]]
    if q.terms:
        cats = db.scalars(select(Category).where(Category.active)).all()
        res.categories = [c for c in cats if any(t in words_of(c.name) for g in q.groups for t in g)]
    return res


def suggestion(db: Session, raw: str, city_id=None) -> str | None:
    """Para "No encontramos nada": la palabra del catálogo más parecida a lo que escribió."""
    vocab = vocabulary(db, city_id)
    for t in words_of(raw):
        if t in STOPWORDS or t in vocab:
            continue
        close = difflib.get_close_matches(t, vocab, n=1, cutoff=0.6)
        if close:
            return close[0]
    return None


def log(db: Session, raw: str, res: 'Result', city_id=None, channel: str = 'web') -> None:
    """Guarda que se buscó y cuántos resultados hubo (sin quién buscó). Nunca rompe la búsqueda."""
    from ..models import SearchLog
    term = ' '.join(re.findall(r'[a-z0-9$]+', plain(raw)))[:100]
    if len(term) < 2:
        return
    try:
        db.add(SearchLog(term=term, results=len(res.products) + len(res.stores), corrected=res.query.corrected, city_id=city_id, channel=channel))
        db.commit()
    except Exception:  # noqa: BLE001 - la estadistica no puede tirar la pagina
        db.rollback()
