import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    DATABASE_URL: str
    DATABASE_URL_SYNC: str = ""
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60  # reduzido de 480 para 60 minutos
    TRANSFEREGOV_BASE_URL: str = "http://repositorio.dados.gov.br/seges/detru/"
    SIGCON_DATASET_URL: str = "https://dados.mg.gov.br/dataset/convenios-saida"

    FRONTEND_URL: str = ""
    COFRE_KEY: str = ""  # AES-256 key para cofre de senhas

    class Config:
        env_file = "../.env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # Hardening: rejeita JWT_SECRET fraco em producao
    if os.getenv("ENV", "").lower() == "production":
        weak_markers = ["secret", "changeme", "pactha_secret_key_2026", "test", "dev"]
        if len(s.JWT_SECRET) < 32 or any(m in s.JWT_SECRET.lower() for m in weak_markers):
            raise RuntimeError(
                "JWT_SECRET fraco/previsivel em producao. "
                "Gere com: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
            )
    return s
