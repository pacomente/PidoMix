from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = 'postgresql+psycopg://pidomix:pidomix@localhost:5432/pidomix'
    secret_key: str = 'dev-only-change-me'
    environment: str = 'development'
    allowed_origins: str = ''
    cloudinary_cloud_name: str = ''
    cloudinary_api_key: str = ''
    cloudinary_api_secret: str = ''
    whatsapp_default_number: str = ''
    # JSON de la cuenta de servicio de Firebase (para mandar notificaciones push a la app)
    firebase_service_account: str = ''
    # Sentry: reporte de errores (vacío = desactivado)
    sentry_dsn: str = ''
    sentry_traces_sample_rate: float = 0.05
    # versión desplegada; en Render llega sola como RENDER_GIT_COMMIT
    release: str = Field('', validation_alias=AliasChoices('RELEASE', 'RENDER_GIT_COMMIT'))
    # verificacion en dos pasos obligatoria para el superadmin (vacio: si en produccion, no en desarrollo)
    admin_2fa_required: bool | None = None
    admin_email: str = 'admin@pidomix.local'
    admin_password: str = 'change-me'
    # centro del mapa cuando todavia no sabemos donde esta el cliente (lat,lng)
    map_default_center: str = '-38.7183,-62.2663'
    # URL publica del sitio (para los avisos de Mercado Pago y la vuelta del pago). Vacio: la del request.
    public_base_url: str = ''
    # clave para cifrar tokens y CBU/CVU guardados (Fernet, 32 bytes base64). Vacio: se deriva de SECRET_KEY.
    field_encryption_key: str = ''
    # ---- Mercado Pago (Marketplace + OAuth). Ver README, seccion "Pagos online". ----
    mercadopago_environment: str = 'sandbox'  # sandbox | production
    mercadopago_client_id: str = ''  # APP_ID de la aplicacion de Trappi en Mercado Pago Developers
    mercadopago_client_secret: str = ''
    mercadopago_access_token: str = ''  # el de la cuenta de Trappi (no se usa para cobrar: cobra cada comercio con su token OAuth)
    mercadopago_public_key: str = ''
    mercadopago_redirect_uri: str = ''  # https://<dominio>/admin/pagos/mercadopago/callback (igual al configurado en la aplicacion)
    mercadopago_webhook_secret: str = ''  # "clave secreta" de Webhooks para validar x-signature
    mercadopago_auth_url: str = 'https://auth.mercadopago.com.ar/authorization'
    mercadopago_api_url: str = 'https://api.mercadopago.com'
    # ---- emails (codigo para entrar): brevo | resend | smtp | console (solo desarrollo: lo escribe en el log) ----
    email_provider: str = ''
    email_api_key: str = ''  # brevo o resend; nunca sale del backend
    email_from: str = ''  # remitente verificado en el proveedor (ej: hola@trappi.com.ar)
    email_from_name: str = 'Trappi'
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_user: str = ''
    smtp_password: str = ''
    # ---- Trappi AI: modelo de lenguaje (ver README, "Trappi AI") ----
    ai_provider: str = ''  # ollama | openai (cualquier API compatible: OpenAI, Groq, OpenRouter, vLLM, Ollama /v1) | vacio = apagado
    ai_base_url: str = ''  # ollama: http://servidor:11434 · openai: https://api.openai.com/v1
    ai_model: str = 'qwen2.5:7b'
    ai_api_key: str = ''  # solo para proveedores externos; nunca sale del backend
    # servidor propio detras de Cloudflare Access: token de servicio (Zero Trust -> Access -> Service Auth)
    ai_cf_access_client_id: str = ''
    ai_cf_access_client_secret: str = ''
    ai_timeout_seconds: float = 60.0
    ai_temperature: float = 0.2
    ai_max_tokens: int = 2048  # largo maximo de cada respuesta (algunos proveedores, como Workers AI, traen uno muy corto)
    # ---- rutas (distancia real por calle para el costo de envio de la flota) ----
    routing_provider: str = 'osrm'  # osrm | none (none = siempre estimado)
    routing_url: str = 'https://router.project-osrm.org'  # servidor OSRM (el publico es de demostracion: conviene uno propio)
    routing_api_key: str = ''  # por si el servidor de rutas pide clave (se manda solo desde el backend)
    routing_timeout_seconds: float = 4.0
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    @field_validator('public_base_url', 'field_encryption_key', 'mercadopago_environment', 'mercadopago_client_id', 'mercadopago_client_secret',
                     'mercadopago_access_token', 'mercadopago_public_key', 'mercadopago_redirect_uri', 'mercadopago_webhook_secret',
                     'routing_url', 'routing_api_key',
                     'ai_provider', 'ai_base_url', 'ai_model', 'ai_api_key',
                     'ai_cf_access_client_id', 'ai_cf_access_client_secret',
                     'email_provider', 'email_api_key', 'email_from', 'smtp_host', 'smtp_user', 'smtp_password', mode='before')
    @classmethod
    def _clean(cls, value):
        # lo pegado en el panel de Render a veces trae espacios, saltos de linea o comillas
        if isinstance(value, str):
            value = value.strip().strip('"').strip("'").strip()
        return value

    @field_validator('admin_2fa_required', mode='before')
    @classmethod
    def _blank_is_default(cls, value):
        # vacia en Render = "el valor por defecto" (si en produccion), no un error al arrancar
        if isinstance(value, str) and not value.strip().strip('"').strip("'"):
            return None
        return value

    @property
    def mercadopago_configured(self) -> bool:
        return bool(self.mercadopago_client_id and self.mercadopago_client_secret and self.mercadopago_redirect_uri)

    @property
    def mercadopago_sandbox(self) -> bool:
        return self.mercadopago_environment.lower() != 'production'

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {'production', 'prod'}

    @property
    def ai_configured(self) -> bool:
        return self.ai_provider.lower() in ('ollama', 'openai') and bool(self.ai_base_url and self.ai_model)

    @property
    def email_configured(self) -> bool:
        provider = self.email_provider.lower()
        if provider == 'console':
            return not self.is_production
        if provider in ('brevo', 'resend'):
            return bool(self.email_api_key and self.email_from)
        if provider == 'smtp':
            return bool(self.smtp_host and self.email_from)
        return False

    @property
    def require_admin_2fa(self) -> bool:
        return self.is_production if self.admin_2fa_required is None else self.admin_2fa_required

    @property
    def cors_origins(self) -> list[str]:
        return [x.strip() for x in self.allowed_origins.split(',') if x.strip()]


def validate_production_settings(settings: Settings) -> None:
    if not settings.is_production:
        return

    url = settings.database_url.strip()
    if not url:
        raise RuntimeError("DATABASE_URL es obligatoria en producción.")

    lowered = url.lower()
    if "@localhost" in lowered or "@127.0.0.1" in lowered or "@0.0.0.0" in lowered:
        raise RuntimeError("DATABASE_URL de producción no puede apuntar a localhost/127.0.0.1.")

    if settings.secret_key == "dev-only-change-me":
        raise RuntimeError("SECRET_KEY debe configurarse en producción.")


settings = Settings()
validate_production_settings(settings)
