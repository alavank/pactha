from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    DATABASE_URL: str
    DATABASE_URL_SYNC: str = ""
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 480
    TRANSFEREGOV_BASE_URL: str = "http://repositorio.dados.gov.br/seges/detru/"
    SIGCON_DATASET_URL: str = "https://dados.mg.gov.br/dataset/convenios-saida"

    FRONTEND_URL: str = ""

    class Config:
        env_file = "../.env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
