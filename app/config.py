from pydantic import AliasChoices, Field
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
    # ---- rutas (distancia real por calle para el costo de envio de la flota) ----
    routing_provider: str = 'osrm'  # osrm | none (none = siempre estimado)
    routing_url: str = 'https://router.project-osrm.org'  # servidor OSRM (el publico es de demostracion: conviene uno propio)
    routing_api_key: str = ''  # por si el servidor de rutas pide clave (se manda solo desde el backend)
    routing_timeout_seconds: float = 4.0
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

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
