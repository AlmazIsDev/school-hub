from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    mongo_url: str
    redis_url: str
    jwt_secret: str
    jwt_alg: str = "HS256"
    access_ttl_min: int = 15
    refresh_ttl_days: int = 7
    vk_token: str = ""
    vk_group_id: int = 0
    admin_login: str = "admin"
    admin_password: str = ""  # пусто — админ не создаётся
    admin_name: str = "Администратор"

    model_config = {"env_file": ".env"}

settings = Settings()
