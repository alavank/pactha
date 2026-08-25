import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    DATABASE_URL: str
    DATABASE_URL_SYNC: str = ""
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60  # reduzido de 480 para 60 minutos
    TRANSFEREGOV_BASE_URL: str = "https://api-publica.transferegov.gestao.gov.br/downloads/dadosgov/"
    SIGCON_DATASET_URL: str = "https://dados.mg.gov.br/dataset/convenios-saida"

    FRONTEND_URL: str = ""
    COFRE_KEY: str = ""  # AES-256 key para cofre de senhas

    # Painel de Indicadores - BI (modulo nativo). Default OFF: com a flag desligada
    # o router /api/bi/* nem e montado (404) e o app segue byte-identico. Liga por
    # instancia via env BI_MODULE=true. O frontend usa NEXT_PUBLIC_BI_MODULE (build).
    BI_MODULE: bool = False

    # Control-plane (Console Alavank) — canal /api/control/*
    INSTANCE_SLUG: str = ""              # identidade do tenant (ex.: "montesiao-mg")
    CONTROL_TOKEN_BOOTSTRAP: str = ""    # raw injetado 1x no boot p/ semear o control token
    CONTROL_PLANE_ALLOWED_IPS: str = ""  # CSV opcional de IPs do Console (egress fixo)

    # Rodape do Relatorio de Monitoramento (RM), por TENANT. Sai impresso no pe
    # de toda pagina do relatorio oficial, entao e endereco de quem assina.
    # Vazio por default de proposito: melhor pagina sem rodape do que pagina com
    # o endereco de OUTRO cliente — que foi o que aconteceu enquanto o endereco
    # de uma consultoria estava no DEFAULT da coluna.
    RM_RODAPE: str = ""

    # Logo do cabecalho do RM, por TENANT. Aceita o MESMO valor que o frontend ja
    # usa em NEXT_PUBLIC_CLIENT_LOGO (ex.: "/freitas-logo.jpeg") — o rm_pdf usa so
    # o nome do arquivo e procura em backend/assets/. Tambem aceita caminho
    # absoluto. Vazio = sem logo, pela mesma razao do RM_RODAPE acima: melhor
    # cabecalho vazio do que a marca de OUTRO cliente no relatorio.
    RM_LOGO: str = ""

    # E-mail impresso no cabecalho do RM, a DIREITA, na mesma faixa do logo.
    # Mesma logica de precedencia do RM_RODAPE (ver services/rm_config.py): esta
    # env so vale enquanto NINGUEM tiver salvo nada pela tela.
    #
    # Vazio por default pelo motivo de sempre neste bloco: cabecalho sem e-mail e
    # melhor do que cabecalho com o e-mail de OUTRO cliente. Um contato errado num
    # documento oficial e pior do que contato nenhum — o relatorio circula, e quem
    # o recebe escreve para o endereco impresso.
    RM_EMAIL: str = ""

    # Cidade de emissao do RM ("Brasília/DF, 21 de Agosto de 2026").
    # ⚠️ E a cidade de QUEM ASSINA o relatorio, nao a do municipio monitorado.
    # Antes o default era o proprio municipio ("Araújos/MG"), o que estava errado:
    # o relatorio e emitido pela assessoria, e o documento de referencia do padrao
    # Freitas traz "Brasília/DF" — a mesma cidade do endereco no rodape. Por
    # TENANT, como o RM_RODAPE, para uma assessoria de outra praca ajustar.
    RM_CIDADE: str = "Brasília/DF"

    # Painel Executivo do prefeito — push web (VAPID). Gerar 1x por instancia com
    # web-push generate-vapid-keys (ou py_vapid). A publica tambem vai como build
    # ARG NEXT_PUBLIC_VAPID_PUBLIC_KEY no app painel/.
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_SUBJECT: str = "mailto:contato@pactha.com.br"

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
