"""Proveedores de modelos de lenguaje para Trappi AI.

La aplicacion habla siempre con AIProvider.chat(); cambiar de modelo o de proveedor es cambiar
variables de entorno, sin tocar el resto:

    AI_PROVIDER=ollama   AI_BASE_URL=http://mi-servidor:11434     AI_MODEL=qwen2.5:7b
    AI_PROVIDER=openai   AI_BASE_URL=https://api.openai.com/v1    AI_MODEL=...  AI_API_KEY=...
                         (sirve para cualquier API compatible: Groq, OpenRouter, Together, vLLM, LM Studio, Ollama /v1)

Mensajes en un formato neutro (el de "chat con herramientas"):
    {'role': 'system'|'user'|'assistant', 'content': str}
    {'role': 'assistant', 'content': str, 'tool_calls': [{'id': str, 'name': str, 'arguments': dict}]}
    {'role': 'tool', 'tool_call_id': str, 'name': str, 'content': str}
Cada proveedor lo traduce a su API.
"""
import json
import re
from dataclasses import dataclass, field

import httpx

from ..config import settings


class AIUnavailable(Exception):
    """El modelo no respondio (apagado, lento, error): el asistente responde sin IA."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class AIReply:
    text: str = ''
    tool_calls: list[ToolCall] = field(default_factory=list)


_THINK = re.compile(r'<think>.*?</think>', re.S)


def clean_text(text: str | None) -> str:
    """Saca el razonamiento interno que algunos modelos (Qwen3, DeepSeek) devuelven entre <think>."""
    return _THINK.sub('', text or '').strip()


def parse_arguments(raw) -> dict:
    """Los modelos chicos a veces mandan los argumentos como texto JSON, o mal formados."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {}
        except ValueError:
            return {}
    return {}


class AIProvider:
    name = 'base'

    def __init__(self, *, base_url: str, model: str, api_key: str = '', timeout: float = 60.0, temperature: float = 0.2,
                 transport: httpx.BaseTransport | None = None, cf_access_id: str = '', cf_access_secret: str = '', max_tokens: int = 2048):
        self.base_url, self.model, self.api_key, self.max_tokens = base_url.rstrip('/'), model, api_key, max_tokens
        self.timeout, self.temperature, self.transport = timeout, temperature, transport
        self.cf_access = (cf_access_id, cf_access_secret) if cf_access_id and cf_access_secret else None

    def auth_headers(self) -> dict:
        """Clave del proveedor (Bearer) y, si el modelo esta en un servidor propio detras de Cloudflare Access, su token de servicio."""
        headers = {'Authorization': f'Bearer {self.api_key}'} if self.api_key else {}
        if self.cf_access:
            headers.update({'CF-Access-Client-Id': self.cf_access[0], 'CF-Access-Client-Secret': self.cf_access[1]})
        return headers

    def chat(self, messages: list[dict], tools: list[dict]) -> AIReply:
        raise NotImplementedError

    def _post(self, url: str, payload: dict) -> dict:
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                r = client.post(url, json=payload, headers=self.auth_headers())
        except httpx.HTTPError as exc:
            raise AIUnavailable(f'{self.name}: {type(exc).__name__}') from exc
        if r.status_code != 200:
            raise AIUnavailable(f'{self.name}: HTTP {r.status_code} {r.text[:200]}')
        if 'application/json' not in r.headers.get('content-type', ''):  # p. ej. la pagina de login de Cloudflare Access
            raise AIUnavailable(f'{self.name}: respuesta no JSON (¿falta el token de Cloudflare Access?)')
        try:
            return r.json()
        except ValueError as exc:
            raise AIUnavailable(f'{self.name}: respuesta no JSON') from exc


class OllamaProvider(AIProvider):
    """Ollama (modelos abiertos en un servidor propio): POST /api/chat con tools."""
    name = 'ollama'

    def chat(self, messages: list[dict], tools: list[dict]) -> AIReply:
        out = []
        for m in messages:
            if m['role'] == 'tool':
                out.append({'role': 'tool', 'content': m['content'], 'tool_name': m.get('name', '')})
            elif m.get('tool_calls'):
                out.append({'role': 'assistant', 'content': m.get('content') or '',
                            'tool_calls': [{'function': {'name': c['name'], 'arguments': c['arguments']}} for c in m['tool_calls']]})
            else:
                out.append({'role': m['role'], 'content': m.get('content') or ''})
        data = self._post(self.base_url + '/api/chat', {
            'model': self.model, 'messages': out, 'stream': False, 'keep_alive': '15m',
            'tools': [{'type': 'function', 'function': t} for t in tools],
            'options': {'temperature': self.temperature, 'num_predict': self.max_tokens},
        })
        msg = data.get('message') or {}
        calls = [ToolCall(id=f'call_{i}', name=(c.get('function') or {}).get('name', ''), arguments=parse_arguments((c.get('function') or {}).get('arguments')))
                 for i, c in enumerate(msg.get('tool_calls') or [])]
        return AIReply(text=clean_text(msg.get('content')), tool_calls=[c for c in calls if c.name])


class OpenAICompatibleProvider(AIProvider):
    """API estilo OpenAI (/chat/completions con tools): OpenAI, Groq, OpenRouter, Together, vLLM, LM Studio, Ollama /v1."""
    name = 'openai'

    def chat(self, messages: list[dict], tools: list[dict]) -> AIReply:
        out = []
        for m in messages:
            if m['role'] == 'tool':
                out.append({'role': 'tool', 'tool_call_id': m.get('tool_call_id', ''), 'content': m['content']})
            elif m.get('tool_calls'):
                out.append({'role': 'assistant', 'content': m.get('content') or '', 'tool_calls': [  # '' y no null: Workers AI rechaza null
                    {'id': c['id'], 'type': 'function', 'function': {'name': c['name'], 'arguments': json.dumps(c['arguments'], ensure_ascii=False)}}
                    for c in m['tool_calls']]})
            else:
                out.append({'role': m['role'], 'content': m.get('content') or ''})
        data = self._post(self.base_url + '/chat/completions', {
            'model': self.model, 'messages': out, 'temperature': self.temperature, 'max_tokens': self.max_tokens,
            'tools': [{'type': 'function', 'function': t} for t in tools], 'tool_choice': 'auto',
        })
        try:
            msg = data['choices'][0]['message']
        except (KeyError, IndexError, TypeError) as exc:
            raise AIUnavailable('openai: respuesta sin choices') from exc
        if not msg.get('content') and not msg.get('tool_calls') and (data['choices'][0].get('finish_reason') == 'length'):
            raise AIUnavailable('openai: respuesta cortada por el largo máximo (subí AI_MAX_TOKENS)')
        calls = [ToolCall(id=c.get('id') or f'call_{i}', name=(c.get('function') or {}).get('name', ''),
                          arguments=parse_arguments((c.get('function') or {}).get('arguments')))
                 for i, c in enumerate(msg.get('tool_calls') or [])]
        return AIReply(text=clean_text(msg.get('content')), tool_calls=[c for c in calls if c.name])


PROVIDERS = {'ollama': OllamaProvider, 'openai': OpenAICompatibleProvider}
_override: AIProvider | None = None  # para los tests


def configured() -> bool:
    return _override is not None or settings.ai_configured


def get_provider() -> AIProvider | None:
    if _override is not None:
        return _override
    if not settings.ai_configured:
        return None
    cls = PROVIDERS[settings.ai_provider.lower()]
    return cls(base_url=settings.ai_base_url, model=settings.ai_model, api_key=settings.ai_api_key,
               timeout=settings.ai_timeout_seconds, temperature=settings.ai_temperature,
               cf_access_id=settings.ai_cf_access_client_id, cf_access_secret=settings.ai_cf_access_client_secret,
               max_tokens=settings.ai_max_tokens)


def set_override(provider: AIProvider | None) -> None:
    global _override
    _override = provider


def _hint(detail: str) -> str:
    """Que revisar segun el error, en palabras del panel."""
    d = detail.lower()
    if 'connecterror' in d or 'proxyerror' in d or 'connecttimeout' in d or 'name or service' in d:
        return 'Trappi no llega al servidor: revisá AI_BASE_URL (con https://) y que el servidor y el túnel estén prendidos.'
    if 'readtimeout' in d or 'timeout' in d:
        return 'El servidor responde pero el modelo tarda demasiado: subí AI_TIMEOUT_SECONDS (por ejemplo 90) o usá un modelo más chico.'
    if 'no json' in d or 'http 302' in d or 'http 401' in d or 'http 403' in d:
        return ('Rechazo de acceso: revisá la clave (AI_API_KEY) o, si el modelo está detrás de Cloudflare Access, '
                'AI_CF_ACCESS_CLIENT_ID y AI_CF_ACCESS_CLIENT_SECRET y que la política sea "Service Auth".')
    if 'http 404' in d and 'model' in d:
        return 'El servidor no tiene ese modelo: descargalo (ollama pull <modelo>) o corregí AI_MODEL.'
    if 'http 404' in d:
        return 'La dirección no existe: con AI_PROVIDER=ollama, AI_BASE_URL va sin /v1; con AI_PROVIDER=openai, con la ruta que termina en /v1.'
    if 'no route for that uri' in d:
        return 'Cloudflare no conoce esa dirección: AI_BASE_URL tiene que ser https://api.cloudflare.com/client/v4/accounts/<Account ID>/ai/v1.'
    if 'largo máximo' in d:
        return 'El modelo se quedó sin espacio para responder: subí AI_MAX_TOKENS (por ejemplo 4096).'
    if 'http 400' in d and ('tool' in d or 'function' in d):
        return 'El modelo no acepta herramientas: elegí uno con "tools" (qwen2.5, llama3.1, mistral-nemo).'
    if 'http 429' in d:
        return 'El proveedor limitó las consultas (cuota o plan gratis agotado).'
    if 'http 5' in d:
        return 'El servidor del modelo dio un error interno: mirá sus logs (docker compose logs -f ollama).'
    return 'Mirá el detalle y los logs del servidor del modelo.'


def diagnose() -> dict:
    """Prueba real con el modelo configurado (una pregunta corta, con una herramienta), para el panel."""
    import time
    from urllib.parse import urlsplit
    info = {'provider': settings.ai_provider or '—', 'host': urlsplit(settings.ai_base_url).netloc or '—', 'model': settings.ai_model or '—',
            'cf_access': bool(settings.ai_cf_access_client_id and settings.ai_cf_access_client_secret)}
    provider = get_provider()
    if provider is None:
        return {**info, 'ok': False, 'detail': 'Sin configurar.',
                'hint': 'Cargá AI_PROVIDER (ollama u openai), AI_BASE_URL y AI_MODEL en Render y redesplegá.'}
    probe = {'name': 'ping', 'description': 'Prueba de conexión.', 'parameters': {'type': 'object', 'properties': {}}}
    start = time.monotonic()
    try:
        reply = provider.chat([{'role': 'user', 'content': 'Respondé solo: ok'}], [probe])
    except AIUnavailable as exc:
        detail = str(exc)[:300]
        return {**info, 'ok': False, 'seconds': round(time.monotonic() - start, 1), 'detail': detail, 'hint': _hint(detail)}
    answer = reply.text[:120] or (f'pidió la herramienta {reply.tool_calls[0].name}' if reply.tool_calls else '(vacío)')
    return {**info, 'ok': True, 'seconds': round(time.monotonic() - start, 1), 'detail': f'El modelo respondió: {answer}', 'hint': ''}
