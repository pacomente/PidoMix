"""Rutas gratis con respaldo: si el OSRM principal no responde se usa el de OpenStreetMap o OpenRouteService."""

import httpx

from app.services import routing

A, B = (-38.7183, -62.2663), (-38.7262, -62.2745)
OSRM_OK = {'code': 'Ok', 'routes': [{'distance': 1500, 'duration': 300, 'geometry': {'coordinates': [[-62.2663, -38.7183], [-62.2745, -38.7262]]},
                                     'legs': [{'steps': [{'maneuver': {'type': 'depart', 'location': [-62.2663, -38.7183]}, 'name': 'Alem', 'distance': 800},
                                                         {'maneuver': {'type': 'turn', 'modifier': 'right', 'location': [-62.27, -38.72]}, 'name': 'Alsina', 'distance': 700},
                                                         {'maneuver': {'type': 'arrive', 'location': [-62.2745, -38.7262]}, 'name': '', 'distance': 0}]}]}]}
ORS_OK = {'type': 'FeatureCollection', 'features': [{'geometry': {'coordinates': [[-62.2663, -38.7183], [-62.27, -38.72], [-62.2745, -38.7262]]},
          'properties': {'summary': {'distance': 1620, 'duration': 330}, 'segments': [{'steps': [
              {'type': 11, 'name': 'Alem', 'distance': 800, 'way_points': [0, 1]},
              {'type': 7, 'exit_number': 2, 'name': 'Alsina', 'distance': 820, 'way_points': [1, 2]},
              {'type': 10, 'name': '-', 'distance': 0, 'way_points': [2, 2]}]}]}}]}


def transport(log, fail_hosts=()):
    def handler(req: httpx.Request):
        log.append((req.url.host, dict(req.headers)))
        if req.url.host in fail_hosts:
            return httpx.Response(503, json={'code': 'Error'})
        if req.url.host == 'api.openrouteservice.org':
            return httpx.Response(200, json=ORS_OK)
        return httpx.Response(200, json=OSRM_OK)
    return httpx.MockTransport(handler)


def chain(log, fail_hosts=(), clock=None, ors=False):
    t = transport(log, fail_hosts)
    ps = [routing.OSRMProvider('https://router.project-osrm.org', 2, transport=t),
          routing.OSRMProvider('https://routing.openstreetmap.de/routed-car', 2, transport=t)]
    if ors:
        ps.append(routing.ORSProvider('clave-secreta', 2, transport=t))
    return routing.ChainProvider(ps, **({'clock': clock} if clock else {}))


def test_principal_caido_usa_el_de_openstreetmap_y_lo_saltea_un_rato():
    now = [1000.0]
    log = []
    c = chain(log, fail_hosts={'router.project-osrm.org'}, clock=lambda: now[0])
    r = c.route(A, B)
    assert r.km == 1.5 and r.source == 'osrm'
    assert [h for h, _ in log] == ['router.project-osrm.org', 'routing.openstreetmap.de']
    assert all(hd['user-agent'].startswith('Trappi/') for _, hd in log)  # politica de uso de OpenStreetMap
    log.clear()
    d = c.directions(A, B)  # el caido se saltea: no se espera su timeout
    assert [h for h, _ in log] == ['routing.openstreetmap.de'] and d['steps'][1]['text'] == 'Doblá a la derecha por Alsina'
    now[0] += routing.COOLDOWN_SECONDS + 1
    log.clear()
    c.route(A, B)  # pasado el rato se vuelve a probar el principal
    assert log[0][0] == 'router.project-osrm.org'


def test_openrouteservice_como_ultimo_respaldo_con_indicaciones_en_castellano():
    log = []
    c = chain(log, fail_hosts={'router.project-osrm.org', 'routing.openstreetmap.de'}, ors=True)
    d = c.directions(A, B)
    assert d['source'] == 'ors' and d['km'] == 1.62 and len(d['geometry']) == 3
    assert [s['text'] for s in d['steps']] == ['Salí por Alem', 'En la rotonda, tomá la 2ª salida hacia Alsina', 'Llegaste']
    assert d['steps'][1]['lng'] == -62.27  # la maniobra queda en el punto del recorrido
    ors_headers = next(hd for h, hd in log if h == 'api.openrouteservice.org')
    assert ors_headers['authorization'] == 'clave-secreta'
    assert all('clave-secreta' not in h for h, _ in log)  # la clave no va en la URL
    assert c.route(A, B).source == 'ors'


def test_si_fallan_todos_avisa_y_el_envio_se_estima():
    log = []
    c = chain(log, fail_hosts={'router.project-osrm.org', 'routing.openstreetmap.de'})
    svc = routing.RoutingService(c)
    assert svc.route(A, B).source == 'estimate'
    assert svc.directions(A, B) is None
    log.clear()
    svc.route(A, B)  # si estan todos caidos se vuelven a probar todos (no se queda sin rutas para siempre)
    assert {h for h, _ in log} == {'router.project-osrm.org', 'routing.openstreetmap.de'}


def test_configuracion_por_defecto_arma_la_cadena(monkeypatch):
    monkeypatch.setattr(routing.settings, 'routing_provider', 'osrm')
    monkeypatch.setattr(routing.settings, 'routing_url', 'https://router.project-osrm.org')
    monkeypatch.setattr(routing.settings, 'routing_fallback_urls', 'https://routing.openstreetmap.de/routed-car, http://inseguro.test')
    monkeypatch.setattr(routing.settings, 'ors_api_key', 'k')
    p = routing._default_provider()
    assert [type(x).__name__ for x in p.providers] == ['OSRMProvider', 'OSRMProvider', 'ORSProvider']  # el http:// se ignora
    monkeypatch.setattr(routing.settings, 'routing_fallback_urls', '')
    monkeypatch.setattr(routing.settings, 'ors_api_key', '')
    assert isinstance(routing._default_provider(), routing.OSRMProvider)
