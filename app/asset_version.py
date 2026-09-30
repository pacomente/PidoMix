"""Token que cambia en cada arranque del proceso (= cada deploy).

Se agrega como '?v=...' a los links de CSS/JS/manifest para forzar al
navegador a pedir el archivo nuevo en vez de servir una copia vieja
cacheada, sin tener que pedirle al usuario que borre el cache a mano.
"""
import time

ASSET_VERSION = str(int(time.time()))
