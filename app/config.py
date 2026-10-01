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
    admin_email: str = 'admin@pidomix.local'
    admin_password: str = 'change-me'
    # centro del mapa cuando todavia no sabemos donde esta el cliente (lat,lng)
    map_default_center: str = '-38.7183,-62.2663'
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

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
