"""Reporte de errores a Sentry. Se activa con SENTRY_DSN; sin esa variable no hace nada.

No se envían datos personales: ni el cuerpo de los pedidos (nombre, teléfono, dirección),
ni cookies, ni el token de seguimiento que viaja en la URL (?t=).
"""
import logging
import re

from ..config import settings

logger = logging.getLogger(__name__)
_TOKEN = re.compile(r'(^|&)(t|token)=[^&]*')


def _scrub(event, hint):
    request = event.get('request') or {}
    if request.get('query_string'):
        request['query_string'] = _TOKEN.sub(r'\1\2=[oculto]', request['query_string'])
    if isinstance(request.get('url'), str):
        request['url'] = re.sub(r'([?&](?:t|token)=)[^&]*', r'\1[oculto]', request['url'])
    request.pop('data', None)
    request.pop('cookies', None)
    return event


def init_sentry() -> bool:
    dsn = settings.sentry_dsn.strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=dsn,
            environment=settings.environment,
            release=settings.release or None,
            send_default_pii=False,
            max_request_body_size='never',
            traces_sample_rate=settings.sentry_traces_sample_rate,
            before_send=_scrub,
        )
    except Exception:  # un DSN mal copiado no puede tirar abajo el servidor
        logger.exception('No se pudo iniciar Sentry')
        return False
    logger.info('Sentry activo (%s)', settings.environment)
    return True
