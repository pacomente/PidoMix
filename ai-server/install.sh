#!/usr/bin/env sh
# Instala Docker (si falta) y levanta el servidor de IA de Trappi. Uso: sh install.sh
set -e
cd "$(dirname "$0")"
if ! command -v docker >/dev/null 2>&1; then
  echo "Instalando Docker…"
  curl -fsSL https://get.docker.com | sh
fi
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Completá TUNNEL_TOKEN en ai-server/.env y volvé a correr: sh install.sh"
  exit 1
fi
grep -q '^TUNNEL_TOKEN=.\+' .env || { echo "Falta TUNNEL_TOKEN en .env"; exit 1; }
docker compose up -d
echo "Descargando el modelo (la primera vez tarda unos minutos)…"
docker compose logs -f model || true
docker compose ps
echo "Listo. Probalo desde Trappi (/asistente) después de cargar las variables en Render."
