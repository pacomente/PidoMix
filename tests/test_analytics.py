"""Analítica de clientes y comercios: nuevos, recurrentes, retención, en riesgo, tendencia y búsquedas sin resultado."""
from datetime import datetime, timedelta
from decimal import Decimal

from tests.test_recommendations import env, make_account  # noqa: F401  (misma base de prueba)


def order(db, acct, name, days_ago, status="ENTREGADO"):
    from tests.test_recommendations import make_order
    return make_order(db, acct, [name], days_ago=days_ago, hour_utc=23, status=status)


def test_analitica(env):
    from app.db import SessionLocal
    from app.models import SearchLog
    from app.services import analytics, profit
    with SessionLocal() as db:
        vieja = make_account(db, "vieja@a.com")       # pidió antes y volvió
        for d in (50, 40, 5):
            order(db, vieja, "Fugazzeta", d)
        nueva = make_account(db, "nueva@a.com")       # primer pedido en el período
        order(db, nueva, "Muzzarella grande", 3)
        order(db, nueva, "Fugazzeta", 2)
        riesgo = make_account(db, "riesgo@a.com")     # repetía y hace 45 días que no pide
        for d in (80, 60, 45):
            order(db, riesgo, "Hamburguesa Clásica", d)
        order(db, nueva, "Coca Cola", 1, status="CANCELADO")
        for term, n in (("sushi", 0), ("sushi", 0), ("pizza", 3)):
            db.add(SearchLog(term=term, results=n, created_at=datetime.utcnow() - timedelta(days=1)))
        db.commit()
        r = analytics.build(db, profit.period("30d"))
        keys = {c.key for c in r.top_customers}
        assert f"a{vieja.id}" in keys and f"a{nueva.id}" in keys and f"a{riesgo.id}" not in keys
        assert r.customers_new >= 1 and r.customers_returning >= 1 and r.customers_repeat >= 1
        assert any(c.key == f"a{riesgo.id}" for c in r.at_risk) and all(c.key != f"a{vieja.id}" for c in r.at_risk)
        assert all("•••@" in c.email for c in r.top_customers if c.email)  # enmascarado
        pz = next(s for s in r.stores if s.store.slug == "pizzeria-la-esquina")
        assert pz.orders >= 3 and pz.new_customers >= 1
        assert r.heat and r.peak
        assert r.searches_empty[0][0] == "sushi" and r.searches_empty[0][1] == 2 and r.searches_empty_total == 2
        db.rollback()


def test_pantalla_solo_superadmin(env):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    assert c.get("/admin/analitica", follow_redirects=False).status_code in (302, 303)
    assert c.post("/admin/login", data={"email": "admin@test.local", "password": "TestOnly-123!"}, follow_redirects=False).status_code == 303
    page = c.get("/admin/analitica?periodo=90d").text
    assert "Analítica de clientes y comercios" in page and "En riesgo de no volver" in page and "Lo que buscan y no encuentran" in page
