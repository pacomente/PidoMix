"""Ingreso de clientes con Google (OpenID Connect, flujo con codigo + PKCE).

1. /ingresar/google arma el pedido a Google con state, nonce y code_challenge guardados en la sesion.
2. Google vuelve a /cuenta/google/callback con un codigo; el servidor lo cambia por el id_token
   (con el client secret, que nunca sale del backend) y valida firma, audiencia, emisor y nonce.
3. Solo se aceptan emails verificados por Google.

Se pide lo minimo: openid, email y profile (nombre y foto).
"""
import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx
import jwt

from ..config import settings

AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
CERTS_URL = 'https://www.googleapis.com/oauth2/v3/certs'
ISSUERS = ('accounts.google.com', 'https://accounts.google.com')
SCOPES = 'openid email profile'
_jwks = None


class GoogleAuthError(Exception):
    pass


def configured() -> bool:
    return settings.google_configured


def new_pkce() -> tuple[str, str]:
    """(verifier, challenge) para PKCE S256."""
    verifier = secrets.token_urlsafe(48)
    return verifier, challenge_of(verifier)


def challenge_of(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')


def authorization_url(*, redirect_uri: str, state: str, nonce: str, challenge: str) -> str:
    return AUTH_URL + '?' + urlencode({
        'client_id': settings.google_client_id, 'redirect_uri': redirect_uri, 'response_type': 'code', 'scope': SCOPES,
        'state': state, 'nonce': nonce, 'code_challenge': challenge, 'code_challenge_method': 'S256',
        'prompt': 'select_account', 'access_type': 'online',
    })


def _keys():
    global _jwks
    if _jwks is None:
        _jwks = jwt.PyJWKClient(CERTS_URL, cache_keys=True, lifespan=3600)
    return _jwks


def verify_id_token(id_token: str, nonce: str) -> dict:
    try:
        key = _keys().get_signing_key_from_jwt(id_token)
        claims = jwt.decode(id_token, key.key, algorithms=['RS256'], audience=settings.google_client_id, issuer=list(ISSUERS),
                            options={'require': ['exp', 'iat', 'sub', 'aud', 'iss']}, leeway=60)
    except jwt.PyJWTError as exc:
        raise GoogleAuthError('No pudimos validar tu cuenta de Google. Probá de nuevo.') from exc
    if not secrets.compare_digest(str(claims.get('nonce') or ''), nonce or ''):
        raise GoogleAuthError('El ingreso venció. Probá de nuevo.')
    return claims


def exchange_code(code: str, *, verifier: str, redirect_uri: str, nonce: str) -> dict:
    """Cambia el codigo por los datos verificados de la cuenta (sub, email, nombre, foto)."""
    try:
        r = httpx.post(TOKEN_URL, data={'code': code, 'client_id': settings.google_client_id, 'client_secret': settings.google_client_secret,
                                        'redirect_uri': redirect_uri, 'grant_type': 'authorization_code', 'code_verifier': verifier}, timeout=10)
    except httpx.HTTPError as exc:
        raise GoogleAuthError('Google no respondió. Probá de nuevo en un momento.') from exc
    if r.status_code != 200:
        raise GoogleAuthError('Google rechazó el ingreso. Probá de nuevo.')
    id_token = (r.json() or {}).get('id_token')
    if not id_token:
        raise GoogleAuthError('Google no mandó los datos de la cuenta. Probá de nuevo.')
    claims = verify_id_token(id_token, nonce)
    if not claims.get('email') or claims.get('email_verified') not in (True, 'true'):
        raise GoogleAuthError('Tu cuenta de Google no tiene el email verificado.')
    return claims
