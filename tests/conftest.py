import os

# los tests nunca salen a internet: sin proveedor de rutas real (cada test pone uno falso si lo necesita)
os.environ.setdefault("ROUTING_PROVIDER", "none")
os.environ.setdefault("MERCADOPAGO_API_URL", "https://mp.invalid")
