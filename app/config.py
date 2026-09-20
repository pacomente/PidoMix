from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://pidomix:pidomix@localhost:5432/pidomix"
    secret_key: str = "dev-secret-change-me"
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    whatsapp_default_number: str = ""
    admin_email: str = "admin@pidomix.local"
    admin_password: str = "change-me"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
