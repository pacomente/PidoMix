"""Envio de emails (por ahora, el codigo para entrar). La clave del proveedor queda solo en el backend.

    EMAIL_PROVIDER=brevo   EMAIL_API_KEY=...  EMAIL_FROM=tu-email-verificado      (300 por dia gratis, sin dominio propio)
    EMAIL_PROVIDER=resend  EMAIL_API_KEY=...  EMAIL_FROM=hola@tu-dominio          (3.000 por mes gratis, con dominio)
    EMAIL_PROVIDER=smtp    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM
    EMAIL_PROVIDER=console (solo desarrollo: el email se escribe en el log)
"""
import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

import httpx

from ..config import settings

log = logging.getLogger('pidomix.email')
_outbox: list | None = None  # para los tests: si es una lista, los emails se guardan aca en vez de mandarse


class EmailError(Exception):
    pass


def configured() -> bool:
    return _outbox is not None or settings.email_configured


def send(to: str, subject: str, text: str, html: str | None = None) -> None:
    if _outbox is not None:
        _outbox.append({'to': to, 'subject': subject, 'text': text, 'html': html})
        return
    provider = settings.email_provider.lower()
    sender_name = settings.email_from_name or 'Trappi'
    try:
        if provider == 'console' and not settings.is_production:
            log.warning('Email (desarrollo) a %s: %s\n%s', to, subject, text)
        elif provider == 'brevo':
            _check(httpx.post('https://api.brevo.com/v3/smtp/email', timeout=15, headers={'api-key': settings.email_api_key, 'accept': 'application/json'},
                              json={'sender': {'name': sender_name, 'email': settings.email_from}, 'to': [{'email': to}],
                                    'subject': subject, 'textContent': text, 'htmlContent': html or _html(text)}))
        elif provider == 'resend':
            _check(httpx.post('https://api.resend.com/emails', timeout=15, headers={'Authorization': f'Bearer {settings.email_api_key}'},
                              json={'from': formataddr((sender_name, settings.email_from)), 'to': [to], 'subject': subject, 'text': text,
                                    'html': html or _html(text)}))
        elif provider == 'smtp':
            msg = EmailMessage()
            msg['From'], msg['To'], msg['Subject'] = formataddr((sender_name, settings.email_from)), to, subject
            msg.set_content(text)
            msg.add_alternative(html or _html(text), subtype='html')
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                smtp.starttls()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(msg)
        else:
            raise EmailError('sin proveedor de email')
    except (httpx.HTTPError, smtplib.SMTPException, OSError) as exc:
        raise EmailError(f'{type(exc).__name__}: {str(exc)[:200]}') from exc


def _check(r: httpx.Response) -> None:
    if r.status_code >= 300:
        # el detalle va al log (sin la clave); al cliente se le muestra un mensaje generico
        log.error('El proveedor de email respondio %s: %s', r.status_code, r.text[:300])
        raise EmailError(f'HTTP {r.status_code}: {r.text[:300]}')


def _html(text: str) -> str:
    from markupsafe import escape
    body = '<br>'.join(escape(line) for line in text.splitlines())
    return f'<div style="font-family:Arial,sans-serif;font-size:16px;line-height:1.5;color:#1d1b2c">{body}</div>'


def set_outbox(outbox: list | None) -> None:
    global _outbox
    _outbox = outbox


PROVIDERS = ('brevo', 'resend', 'smtp')


def missing() -> list[str]:
    """Variables que faltan en Render para poder mandar emails (nombres, nunca valores)."""
    provider = settings.email_provider.lower()
    if provider not in PROVIDERS and not (provider == 'console' and not settings.is_production):
        return ['EMAIL_PROVIDER (brevo, resend o smtp)']
    need = {'brevo': [('EMAIL_API_KEY', settings.email_api_key), ('EMAIL_FROM', settings.email_from)],
            'resend': [('EMAIL_API_KEY', settings.email_api_key), ('EMAIL_FROM', settings.email_from)],
            'smtp': [('SMTP_HOST', settings.smtp_host), ('EMAIL_FROM', settings.email_from)]}.get(provider, [])
    return [name for name, value in need if not value]


def _hint(detail: str) -> str:
    d = detail.lower()
    key = settings.email_api_key
    if settings.email_provider.lower() == 'brevo' and key.startswith('xsmtpsib-'):
        return 'Esa es la clave SMTP de Brevo. Generá una clave de API (empieza con xkeysib-) en SMTP & API → API Keys y cargala en EMAIL_API_KEY.'
    if 'unrecognised ip' in d or 'unrecognized ip' in d or 'authorised_ips' in d or 'authorized ip' in d:
        return 'Brevo bloquea las IPs que no conoce (Render cambia de IP): en Brevo → Security → Authorized IPs, desactivá el bloqueo.'
    if 'key not found' in d or 'api key is invalid' in d or 'http 401' in d:
        return 'La clave no es válida: revisá EMAIL_API_KEY (sin espacios ni comillas) o generá una nueva.'
    if 'sender' in d or ('domain' in d and 'verif' in d):
        return 'El remitente no está verificado: EMAIL_FROM tiene que ser exactamente el email (o el dominio) que verificaste en el proveedor.'
    if 'not activated' in d or 'permission_denied' in d or 'http 403' in d:
        return 'El proveedor todavía no habilitó los envíos de la cuenta: completá el perfil de la empresa en Brevo o escribiles a soporte.'
    if 'http 429' in d:
        return 'Llegaste al límite de envíos del plan (Brevo gratis: 300 por día).'
    if 'smtp' in d or 'connect' in d or 'timeout' in d:
        return 'No se pudo conectar con el servidor de correo: revisá SMTP_HOST y SMTP_PORT (o usá Brevo por API, que no usa SMTP).'
    return 'Mirá el detalle y los logs de Render.'


def diagnose(to: str) -> dict:
    """Prueba real para el panel: dice que falta o manda un email de prueba a `to` y muestra que respondio el proveedor."""
    info = {'provider': settings.email_provider or '—', 'sender': settings.email_from or '—', 'to': to}
    lacking = missing()
    if lacking:
        return {**info, 'ok': False, 'detail': 'Faltan en Render: ' + ', '.join(lacking) + '.',
                'hint': 'Cargalas en Render → Environment, guardá con "Save and deploy" y esperá que termine el despliegue.'}
    try:
        send(to, 'Prueba de email de Trappi', 'Si te llegó este email, los códigos para entrar a Trappi se están mandando bien. ✅')
    except EmailError as exc:
        detail = str(exc)[:400]
        return {**info, 'ok': False, 'detail': detail, 'hint': _hint(detail)}
    return {**info, 'ok': True, 'detail': f'El proveedor aceptó el email de prueba para {to}. Fijate que te llegue (también en spam o promociones).', 'hint': ''}
