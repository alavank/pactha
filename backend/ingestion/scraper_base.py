"""
Classe-base para scrapers que usam Service Token + Cofre.

Padrao seguro:
1. Worker recebe APENAS PACTA_API_URL + PACTA_SERVICE_TOKEN
2. Le credenciais via /api/internal/secrets/{automation_key}
3. Faz scraping (ou chama API do portal se tiver)
4. Faz upsert via /api/internal/upsert/{automation_key}
5. Tudo auditado server-side
"""
import os
import sys
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx

logger = logging.getLogger("scraper")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class ScraperBase(ABC):
    """Classe base para todos os scrapers."""

    automation_key: str = ""  # ex: "fns", "simec", "sismob", "suas"
    name: str = ""

    def __init__(self):
        self.api_url = os.getenv("PACTA_API_URL", "https://pacta-api-production-9c11.up.railway.app/api")
        self.token = os.getenv("PACTA_SERVICE_TOKEN")
        if not self.token:
            raise RuntimeError(
                f"PACTA_SERVICE_TOKEN ausente. Crie via /api/admin/service-tokens "
                f"com scope 'secret:read:{self.automation_key}'."
            )

    # Se o portal usa gov.br SSO, scrapers podem definir uses_govbr=True
    # para tentar credencial gov.br como fallback quando a especifica nao existir
    uses_govbr: bool = False

    async def _fetch_one(self, key: str) -> list[dict]:
        # Retry para lidar com connection drops do Neon (3 tentativas)
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    r = await client.get(
                        f"{self.api_url}/internal/secrets/{key}",
                        headers={"X-Service-Token": self.token},
                    )
                if r.status_code in (403, 404):
                    return []
                if r.status_code >= 500:
                    if attempt < 2:
                        await asyncio.sleep(2)
                        continue
                r.raise_for_status()
                return r.json().get("secrets", [])
            except (httpx.HTTPStatusError, httpx.TransportError):
                if attempt < 2:
                    await asyncio.sleep(2)
                    continue
                raise
        return []

    async def fetch_credentials(self) -> list[dict]:
        """Busca credenciais especificas + fallback gov.br se aplicavel."""
        creds = await self._fetch_one(self.automation_key)
        if creds:
            return creds
        if self.uses_govbr:
            logger.info(f"  Sem credencial '{self.automation_key}' - tentando gov.br SSO compartilhada")
            return await self._fetch_one("govbr")
        return []

    async def upsert(self, items: list[dict]) -> int:
        """Envia items para upsert via endpoint interno."""
        if not items:
            return 0
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{self.api_url}/internal/upsert/{self.automation_key}",
                headers={"X-Service-Token": self.token, "Content-Type": "application/json"},
                json={"items": items},
            )
            if r.status_code != 200:
                logger.error(f"Upsert falhou: {r.status_code} {r.text}")
                return 0
            return r.json().get("inserted", 0)

    @abstractmethod
    async def collect(self, credential: dict) -> list[dict]:
        """Coleta dados usando uma credencial. Retorna lista de items para upsert."""
        ...

    async def run(self):
        logger.info(f"=== {self.name} iniciando ===")
        creds = await self.fetch_credentials()
        if not creds:
            logger.warning(f"Nenhuma credencial cadastrada com automation_key={self.automation_key}")
            return
        logger.info(f"  {len(creds)} credenciais carregadas (cifradas no DB)")

        all_items = []
        for cred in creds:
            try:
                items = await self.collect(cred)
                logger.info(f"  Municipio {cred.get('municipio_id')}: {len(items)} items")
                # Anexa municipio_id em cada item
                for it in items:
                    it.setdefault("municipio_id", cred.get("municipio_id"))
                all_items.extend(items)
            except Exception as e:
                logger.error(f"  Municipio {cred.get('municipio_id')}: ERRO - {e}")

        n = await self.upsert(all_items)
        logger.info(f"=== {self.name} finalizado: {n} items inseridos/atualizados ===")


def cli(scraper_cls):
    """Helper para rodar scraper via CLI."""
    sc = scraper_cls()
    asyncio.run(sc.run())
