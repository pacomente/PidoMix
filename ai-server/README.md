# Servidor de IA de Trappi (tu servidor + Cloudflare)

El modelo de Trappi AI corre en **tu** servidor (un VPS, Oracle Cloud gratis o tu PC) y Cloudflare lo publica de forma segura:

```
Trappi (Render) ──HTTPS──▶ Cloudflare Access (pide el token) ──Tunnel──▶ tu servidor: Ollama + modelo
```

- **Cloudflare Tunnel**: tu servidor no abre ningún puerto ni necesita IP fija; `cloudflared` se conecta hacia Cloudflare y vos tenés HTTPS.
- **Cloudflare Access**: solo pasa quien manda el token de servicio, es decir, Trappi. Ollama no tiene contraseña propia, así que **no lo publiques sin Access**.
- No pagás por consulta: solo el servidor (o nada, si usás uno gratis o tu PC).

## Qué necesitás
- **Un dominio en Cloudflare** (por ejemplo `trappi.com.ar`). El túnel publica el servidor en un subdominio (`ia.trappi.com.ar`). Si todavía no tenés, se compra en cualquier registrador (o en Cloudflare Registrar) y se agrega a Cloudflare con el plan gratis.
- **Un servidor con Docker y 8 GB de RAM o más** para `qwen2.5:7b` (o 4 GB para `qwen2.5:3b`, que es más rápido pero se equivoca más). Linux, Windows o Mac. Con placa de video NVIDIA responde mucho más rápido; sin placa, tarda varios segundos por respuesta.
  - Oracle Cloud "Always Free" (servidores ARM de hasta 24 GB, gratis; a veces no hay lugar y hay que reintentar).
  - Un VPS de 8–16 GB (Hetzner, Contabo, DigitalOcean…).
  - Tu PC (si la apagás, el asistente deja de responder y Trappi contesta en "modo básico").

## Paso a paso

### 1. Crear el túnel
1. En Cloudflare: **Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared**. Nombre: `trappi-ia`.
2. En "Install and run a connector" elegí **Docker** y copiá el token (lo que viene después de `--token`).
3. En **Public Hostname** agregá:
   - Subdomain `ia`, Domain el tuyo.
   - Service: **HTTP** y URL **`ollama:11434`**.
   - En *Additional application settings → HTTP Settings*, **HTTP Host Header**: `localhost:11434` (Ollama lo necesita).

### 2. Protegerlo con Access (que solo entre Trappi)
1. **Zero Trust → Access → Service Auth → Service Tokens → Create Service Token**. Nombre `trappi-render`. Copiá el **Client ID** y el **Client Secret** (el secreto se ve una sola vez).
2. **Zero Trust → Access → Applications → Add an application → Self-hosted**: dominio `ia.tu-dominio`.
3. Agregá una política con **Action: Service Auth**, regla **Include → Service Token → `trappi-render`**. No agregues ninguna otra regla.

### 3. Levantar el servidor
En el servidor, con esta carpeta del repositorio:
```sh
cd ai-server
cp .env.example .env      # pegá el TUNNEL_TOKEN (y el modelo, si querés otro)
sh install.sh             # instala Docker si falta, levanta todo y descarga el modelo
```
Para ver cómo va: `docker compose ps` y `docker compose logs -f`. Para actualizar: `docker compose pull && docker compose up -d`.

### 4. Conectar Trappi (variables en Render)
```
AI_PROVIDER=ollama
AI_BASE_URL=https://ia.tu-dominio
AI_MODEL=qwen2.5:7b
AI_CF_ACCESS_CLIENT_ID=<Client ID del paso 2>
AI_CF_ACCESS_CLIENT_SECRET=<Client Secret del paso 2>
AI_TIMEOUT_SECONDS=90
```
Redesplegá y probá en `/asistente` ("Buscame hamburguesas cerca"). Si contesta "El asistente no está disponible", mirá los logs de Render: dice si el servidor no respondió o si Cloudflare Access rechazó el token.

## Seguridad
- Los tokens (`TUNNEL_TOKEN`, Client ID/Secret) van en el `.env` del servidor y en Render, **nunca en el repositorio**.
- Ollama no tiene puertos publicados (`docker-compose.yml` no tiene `ports`): solo se llega por el túnel, y el túnel solo deja pasar el token de servicio.
- Si un token se filtra: en Cloudflare, borralo y creá otro (Service Tokens), y actualizá Render.
- El modelo solo recibe lo que Trappi le manda (mensajes y datos de comercios y productos); nunca nombre, teléfono, dirección ni coordenadas de los clientes.
