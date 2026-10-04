"""Sentry: apagado sin DSN y sin datos personales en los eventos."""


def test_sentry_disabled_without_dsn():
    from app.services import monitoring
    monitoring.settings.sentry_dsn = ''
    assert monitoring.init_sentry() is False


def test_sentry_scrubs_personal_data():
    from app.services.monitoring import _scrub
    event = {'request': {'url': 'https://trappi/pedido/5?t=abc123&x=1', 'query_string': 't=abc123&x=1',
                         'data': {'phone': '2914000000', 'address': 'Alsina 100'}, 'cookies': {'session': 'zzz'}}}
    req = _scrub(event, {})['request']
    assert req['query_string'] == 't=[oculto]&x=1' and 'abc123' not in req['url']
    assert 'data' not in req and 'cookies' not in req


def test_sentry_bad_dsn_does_not_crash(monkeypatch):
    from app.services import monitoring
    monkeypatch.setattr(monitoring.settings, 'sentry_dsn', 'esto-no-es-un-dsn')
    assert monitoring.init_sentry() is False
