"""Menú en 3D ("Ver en tu mesa"): el superadmin lo habilita por comercio, el local sube el modelo de cada plato
(se revisa antes de guardarlo) y el cliente ve el botón 3D solo en los platos con modelo."""
import io
import json
import os
import struct
import sys
import zipfile

import pytest

ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}
OWNER = {"email": "dueno-3d@test.local", "password": "Dueno-1234"}


def make_glb(extra: dict | None = None, length_fix: int = 0) -> bytes:
    """Un .glb de verdad (un triangulo) para las pruebas."""
    pos = struct.pack('<9f', 0, 0, 0, 0.1, 0, 0, 0, 0.1, 0)
    gltf = {"asset": {"version": "2.0"}, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
            "buffers": [{"byteLength": len(pos)}], "bufferViews": [{"buffer": 0, "byteLength": len(pos)}],
            "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": [0, 0, 0], "max": [0.1, 0.1, 0]}]}
    gltf.update(extra or {})
    js = json.dumps(gltf).encode()
    js += b' ' * (-len(js) % 4)
    body = struct.pack('<II', len(js), 0x4E4F534A) + js + struct.pack('<II', len(pos), 0x004E4942) + pos
    return b'glTF' + struct.pack('<II', 2, 12 + len(body) + length_fix) + body


def make_usdz(first='scene.usdc', compress=zipfile.ZIP_STORED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr(zipfile.ZipInfo(first), b'PXR-USDC' + b'\0' * 64, compress_type=compress)
        z.writestr(zipfile.ZipInfo('0/texture.png'), b'\x89PNG' + b'\0' * 32, compress_type=compress)
    return buf.getvalue()


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("m3d") / "m3d.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.models import Role, Store, User
    from app.services.auth import hash_password
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = ADMIN["email"]
    seed.settings.admin_password = ADMIN["password"]
    seed.run_seed()
    with SessionLocal() as db:
        mix = db.query(Store).filter_by(slug="burger-mix").one()
        db.add(User(email=OWNER["email"], password_hash=hash_password(OWNER["password"]), role=Role.STORE_ADMIN, store_id=mix.id, active=True))
        db.commit()
    yield
    engine.dispose()


@pytest.fixture()
def cloud(monkeypatch):
    """Cloudinary de mentira: guarda lo que se sube y lo que se borra."""
    from app.services import cloudinary_service
    log = {"up": [], "del": []}

    def upload_raw(data, folder, public_id):
        log["up"].append((folder, public_id, len(data)))
        return f"https://res.cloudinary.com/demo/raw/upload/v1/{folder}/{public_id}", f"{folder}/{public_id}"
    monkeypatch.setattr(cloudinary_service, "configured", lambda: True)
    monkeypatch.setattr(cloudinary_service, "upload_raw", upload_raw)
    monkeypatch.setattr(cloudinary_service, "delete", lambda pid, resource_type="image": log["del"].append((pid, resource_type)) or True)
    return log


def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def login(who):
    c = client()
    assert c.post("/admin/login", data=who, follow_redirects=False).status_code == 303
    return c


def _store_and_products(db, slug):
    from app.models import Product, Store
    s = db.query(Store).filter_by(slug=slug).one()
    return s, db.query(Product).filter(Product.store_id == s.id, Product.deleted.is_(False)).order_by(Product.id).all()


def test_revisa_los_archivos_antes_de_guardarlos(env):
    from app.services import menu3d
    assert menu3d.check_glb(make_glb()) == {"meshes": 1, "textures": 0}
    bad = [
        (b"", "vacío"),
        (b"PK\x03\x04" + b"\0" * 40, "no es un modelo .glb"),
        (make_glb(length_fix=4), "incompleto"),
        (make_glb({"extensionsUsed": ["KHR_draco_mesh_compression"], "extensionsRequired": ["KHR_draco_mesh_compression"]}), "Draco"),
        (make_glb({"extensionsUsed": ["EXT_meshopt_compression"]}), "Meshopt"),
        (make_glb({"images": [{"uri": "https://otro-sitio.com/textura.png"}]}), "archivos aparte"),
        (make_glb({"meshes": []}), "ningún objeto"),
        (b"glTF" + struct.pack("<II", 2, menu3d.MAX_BYTES + 100) + b"\0" * (menu3d.MAX_BYTES + 88), "máximo es 10 MB"),
    ]
    for data, why in bad:
        with pytest.raises(menu3d.Model3DError, match=why):
            menu3d.check_glb(data)
    # las texturas metidas adentro del archivo (data:) estan bien
    assert menu3d.check_glb(make_glb({"images": [{"uri": "data:image/png;base64,iVBORw0KGgo="}]}))["textures"] == 1

    assert menu3d.check_usdz(make_usdz()) == {"files": 2}
    for data, why in [(b"no soy un zip", "no es un modelo .usdz"), (make_usdz(first="leeme.txt"), "escena 3D al principio"),
                      (make_usdz(compress=zipfile.ZIP_DEFLATED), "comprimido"), (make_usdz(first="../scene.usdc"), "nombres inválidos")]:
        with pytest.raises(menu3d.Model3DError, match=why):
            menu3d.check_usdz(data)


def test_sin_habilitar_el_local_no_ve_nada(env, cloud):
    from app.db import SessionLocal
    with SessionLocal() as db:
        _, prods = _store_and_products(db, "burger-mix")
        pid = prods[0].id
    owner = login(OWNER)
    assert "/admin/menu-3d" not in owner.get("/admin").text
    for url in ("/admin/menu-3d", f"/admin/menu-3d/producto/{pid}"):
        assert owner.get(url, follow_redirects=False).headers["location"] == ("/admin" if url == "/admin/menu-3d" else "/admin/menu-3d")
    r = owner.post(f"/admin/menu-3d/producto/{pid}/subir", files={"glb": ("plato.glb", make_glb(), "model/gltf-binary")}, follow_redirects=False)
    assert r.headers["location"] == "/admin/menu-3d" and cloud["up"] == []
    # el local no se lo puede habilitar solo
    from app.db import SessionLocal as S
    with S() as db:
        sid = _store_and_products(db, "burger-mix")[0].id
    assert owner.post("/admin/menu-3d/habilitar", data={"store_id": sid, "on": "1"}, follow_redirects=False).headers["location"] == "/admin"
    with S() as db:
        assert not _store_and_products(db, "burger-mix")[0].ar_enabled


def test_el_local_sube_el_plato_y_el_cliente_lo_ve_en_3d(env, cloud):
    from app.db import SessionLocal
    from app.models import AuditLog, Product
    with SessionLocal() as db:
        store, prods = _store_and_products(db, "burger-mix")
        sid, pid, pid2 = store.id, prods[0].id, prods[1].id
        other = db.query(Product).filter(Product.store_id != sid).first()
        if other is None:  # el seed tiene un solo local: se arma otro
            from app.models import Store
            o = Store(name="Otro local", slug="otro-local-3d")
            db.add(o); db.flush()
            other = Product(name="Plato ajeno", price=1000, store_id=o.id)
            db.add(other); db.commit()
        other_pid = other.id
    admin = login(ADMIN)
    page = admin.get("/admin/menu-3d").text
    assert "Burger Mix" in page and "Habilitar" in page
    assert admin.post("/admin/menu-3d/habilitar", data={"store_id": sid, "on": "1"}, follow_redirects=False).headers["location"] == "/admin/menu-3d?ok=enabled"
    with SessionLocal() as db:
        assert db.query(AuditLog).filter_by(action="menu3d.enable", entity_id=sid).count() == 1

    owner = login(OWNER)
    assert "/admin/menu-3d" in owner.get("/admin").text
    lst = owner.get("/admin/menu-3d").text
    assert "Subir 3D" in lst and f"/admin/menu-3d/producto/{pid}" in lst
    # primero va el .glb; un .usdz solo no alcanza
    r = owner.post(f"/admin/menu-3d/producto/{pid}/subir", files={"usdz": ("plato.usdz", make_usdz(), "model/vnd.usdz+zip")})
    assert "Primero subí el .glb" in r.text and cloud["up"] == []
    # un archivo que no sirve: no se guarda nada y se explica por qué
    r = owner.post(f"/admin/menu-3d/producto/{pid}/subir",
                   files={"glb": ("plato.glb", make_glb({"extensionsRequired": ["KHR_draco_mesh_compression"]}), "model/gltf-binary")})
    assert "comprimido con Draco" in r.text and cloud["up"] == []
    r = owner.post(f"/admin/menu-3d/producto/{pid}/subir", files={"glb": ("plato.glb", make_glb(), "model/gltf-binary"),
                                                                   "usdz": ("plato.usdz", make_usdz(), "model/vnd.usdz+zip")})
    assert "Modelo guardado" in r.text and "<model-viewer" in r.text and "/static/vendor/model-viewer/model-viewer.min.js" in r.text
    assert [u[1].split("-")[0] for u in cloud["up"]] == [f"p{pid}", f"p{pid}"] and cloud["up"][0][1].endswith(".glb") and cloud["up"][1][1].endswith(".usdz")
    assert all(u[0] == "pidomix/models" for u in cloud["up"])
    with SessionLocal() as db:
        p = db.get(Product, pid)
        assert p.model_url.endswith(".glb") and p.model_ios_url.endswith(".usdz") and p.model_visible
        first_glb = p.model_public_id

    # el cliente ve el boton 3D solo en ese plato
    menu = client().get("/tienda/burger-mix").text
    assert menu.count('class="m3d-btn"') == 1 and f'data-ar="{p.model_url}"' in menu and f'data-ar-ios="{p.model_ios_url}"' in menu
    assert "Ver en tu mesa" in menu
    # el visor esta en Trappi (nada de otros sitios)
    js = client().get("/static/vendor/model-viewer/model-viewer.min.js")
    assert js.status_code == 200 and 'customElements.define("model-viewer"' in js.text

    # reemplazar el .glb borra el anterior de Cloudinary
    owner.post(f"/admin/menu-3d/producto/{pid}/subir", files={"glb": ("plato2.glb", make_glb(), "model/gltf-binary")})
    assert (first_glb, "raw") in cloud["del"]

    # ocultarlo del menu
    assert owner.post(f"/admin/menu-3d/producto/{pid}/visible", data={"on": ""}, follow_redirects=False).status_code == 303
    assert 'class="m3d-btn"' not in client().get("/tienda/burger-mix").text
    owner.post(f"/admin/menu-3d/producto/{pid}/visible", data={"on": "1"})
    assert 'class="m3d-btn"' in client().get("/tienda/burger-mix").text

    # no puede tocar platos de otro local
    assert owner.get(f"/admin/menu-3d/producto/{other_pid}", follow_redirects=False).headers["location"] == "/admin/menu-3d"
    owner.post(f"/admin/menu-3d/producto/{other_pid}/subir", files={"glb": ("x.glb", make_glb(), "model/gltf-binary")})
    with SessionLocal() as db:
        assert db.get(Product, other_pid).model_url is None

    # si Trappi lo deshabilita, el cliente deja de verlo (los archivos quedan)
    admin.post("/admin/menu-3d/habilitar", data={"store_id": sid, "on": ""})
    assert 'class="m3d-btn"' not in client().get("/tienda/burger-mix").text
    assert owner.get("/admin/menu-3d", follow_redirects=False).headers["location"] == "/admin"
    admin.post("/admin/menu-3d/habilitar", data={"store_id": sid, "on": "1"})

    # borrar el de iPhone deja el .glb; borrar todo saca el 3D
    owner.post(f"/admin/menu-3d/producto/{pid}/borrar", data={"kind": "usdz"})
    with SessionLocal() as db:
        p = db.get(Product, pid)
        assert p.model_url and p.model_ios_url is None
    owner.post(f"/admin/menu-3d/producto/{pid}/borrar", data={})
    with SessionLocal() as db:
        p = db.get(Product, pid)
        assert p.model_url is None and p.model_public_id is None
        assert db.query(AuditLog).filter_by(action="menu3d.upload", entity_id=pid).count() == 2
    assert 'class="m3d-btn"' not in client().get("/tienda/burger-mix").text
    assert pid2  # el otro plato nunca tuvo 3D
