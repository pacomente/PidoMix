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
                 transport: httpx.BaseTransport | None = None):
        self.base_url, self.model, self.api_key = base_url.rstrip('/'), model, api_key
        self.timeout, self.temperature, self.transport = timeout, temperature, transport

    def chat(self, messages: list[dict], tools: list[dict]) -> AIReply:
        raise NotImplementedError

    def _post(self, url: str, payload: dict, headers: dict | None = None) -> dict:
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                r = client.post(url, json=payload, headers=headers or {})
        except httpx.HTTPError as exc:
            raise AIUnavailable(f'{self.name}: {type(exc).__name__}') from exc
        if r.status_code != 200:
            raise AIUnavailable(f'{self.name}: HTTP {r.status_code} {r.text[:200]}')
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
            'options': {'temperature': self.temperature},
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
                out.append({'role': 'assistant', 'content': m.get('content') or None, 'tool_calls': [
                    {'id': c['id'], 'type': 'function', 'function': {'name': c['name'], 'arguments': json.dumps(c['arguments'], ensure_ascii=False)}}
                    for c in m['tool_calls']]})
            else:
                out.append({'role': m['role'], 'content': m.get('content') or ''})
        headers = {'Authorization': f'Bearer {self.api_key}'} if self.api_key else {}
        data = self._post(self.base_url + '/chat/completions', {
            'model': self.model, 'messages': out, 'temperature': self.temperature,
            'tools': [{'type': 'function', 'function': t} for t in tools], 'tool_choice': 'auto',
        }, headers)
        try:
            msg = data['choices'][0]['message']
        except (KeyError, IndexError, TypeError) as exc:
            raise AIUnavailable('openai: respuesta sin choices') from exc
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
               timeout=settings.ai_timeout_seconds, temperature=settings.ai_temperature)


def set_override(provider: AIProvider | None) -> None:
    global _override
    _override = provider
