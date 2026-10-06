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
        raise EmailError(type(exc).__name__) from exc


def _check(r: httpx.Response) -> None:
    if r.status_code >= 300:
        # el detalle va al log (sin la clave); al cliente se le muestra un mensaje generico
        log.error('El proveedor de email respondio %s: %s', r.status_code, r.text[:300])
        raise EmailError(f'HTTP {r.status_code}')


def _html(text: str) -> str:
    from markupsafe import escape
    body = '<br>'.join(escape(line) for line in text.splitlines())
    return f'<div style="font-family:Arial,sans-serif;font-size:16px;line-height:1.5;color:#1d1b2c">{body}</div>'


def set_outbox(outbox: list | None) -> None:
    global _outbox
    _outbox = outbox
