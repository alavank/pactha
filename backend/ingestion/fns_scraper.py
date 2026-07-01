"""
Scraper FNS - Fundo Nacional de Saude.

Usa API REST interna do portal consultafns.saude.gov.br descoberta via
inspecao de XHR:

  GET /recursos/proposta/consultar?ano=YYYY&coMunicipioIbge=XXXXXX&sgUf=MG
       &count=200&page=1

Esse endpoint retorna propostas filtradas por municipio (codigo IBGE FNS de
6 digitos, NAO o IBGE de 7 digitos do Brasil). O scraper:

1. Le sessao capturada via bookmarklet (cookies em cofre_senhas.senha_hash
   cifrado, formato JSON {format:'cookies_full', cookies:[...]})
2. Resolve coMunicipioIbge consultando /recursos/municipios/uf/MG
3. Para cada municipio + ano, pagina os resultados
4. Insere em convenios_federal com fonte='FNS'

NAO usa mais Playwright para coleta - so para captura de sessao via
bookmarklet (handled fora do scraper).

Resultado validado: cobertura Piracema 49% -> 99% PDF Freitas.
"""
import os
import sys
import json
import logging
from datetime import datetime
from typing import Optional

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ingestion.scraper_base import ScraperBase, cli

logger = logging.getLogger("fns_scraper")


# Mapeamento opcional nome_upper -> coMunicipioIbge FNS (6 digitos, sem digito verificador)
# Pode ser resolvido dinamicamente via /recursos/municipios/uf/{uf}, mas cache local
# evita 1 chamada extra por execucao. UF fixo MG.
FNS_CODE_OVERRIDE = {
    "ARAUJOS": "310390",
    "NOVA SERRANA": "314520",
    "BOM DESPACHO": "310740",
    "SAO TIAGO": "316500",
    "TOLEDO": "316910",
    "PIRACEMA": "315060",
}


class FNSScraper(ScraperBase):
    automation_key = "fns"
    name = "FNS Scraper (API REST)"
    uses_govbr = True

    BASE = "https://consultafns.saude.gov.br"

    async def collect(self, credential: dict) -> list[dict]:
        """Coleta propostas FNS para o municipio da credencial.

        credential vem do Cofre via /api/internal/secrets/fns:
        - municipio_id: int  (PACTHA municipio_id)
        - usuario: str       (CPF, opcional - so se for senha-mode)
        - senha: str         (JSON {format:cookies_full,cookies:[]} OU senha SSO)
        - municipio_nome: str (nome do municipio - usado pra resolver codigo FNS)
        - municipio_uf: str  (default MG)
        """
        senha = credential.get("senha") or ""
        mun_id = credential.get("municipio_id")
        mun_nome = (credential.get("municipio_nome") or "").upper().strip()
        mun_uf = credential.get("municipio_uf") or "MG"

        # Detecta sessao capturada (cookies_full JSON)
        cookies_session = None
        if senha.startswith("{") and "cookies_full" in senha[:200]:
            try:
                d = json.loads(senha)
                if d.get("format") == "cookies_full":
                    cookies_session = d.get("cookies", [])
            except Exception:
                pass

        if not cookies_session:
            logger.warning(f"  mun_id={mun_id}: precisa cookies (use bookmarklet)")
            return []

        cookie_jar = {c["name"]: c["value"] for c in cookies_session if "name" in c}

        with httpx.Client(
            cookies=cookie_jar,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Referer": f"{self.BASE}/",
            },
            timeout=60,
        ) as cli_http:
            # Resolve codigo FNS do municipio
            cod_fns = FNS_CODE_OVERRIDE.get(mun_nome)
            if not cod_fns:
                try:
                    r = cli_http.get(f"{self.BASE}/recursos/municipios/uf/{mun_uf}")
                    r.raise_for_status()
                    for m in r.json().get("resultado", []):
                        if m.get("noMunicipio", "").upper().strip() == mun_nome:
                            cod_fns = m["coMunicipioIbge"]
                            break
                except Exception as e:
                    logger.error(f"  Falha ao resolver codigo FNS de {mun_nome}: {e}")
                    return []

            if not cod_fns:
                logger.warning(f"  Codigo FNS nao encontrado para {mun_nome}/{mun_uf}")
                return []

            logger.info(f"  mun={mun_nome} ({mun_uf}) cod_fns={cod_fns}")

            items = []
            ano_atual = datetime.now().year
            for ano in range(2022, ano_atual + 1):
                pagina = 1
                while True:
                    url = (f"{self.BASE}/recursos/proposta/consultar"
                           f"?ano={ano}&coEsfera=&coMunicipioIbge={cod_fns}"
                           f"&count=200&page={pagina}&sgUf={mun_uf}")
                    try:
                        r = cli_http.get(url)
                        if r.status_code == 401 or "login" in r.text[:200].lower():
                            logger.warning(f"  Sessao expirada - re-capture via bookmarklet")
                            return items
                        if r.status_code != 200:
                            logger.warning(f"  HTTP {r.status_code} ano={ano} pag={pagina}")
                            break
                        j = r.json().get("resultado", {})
                        propostas = j.get("itensPagina", []) or []
                        if not propostas:
                            break
                        for p in propostas:
                            items.append(self._normalize(p, ano, mun_id, cod_fns))
                        if len(propostas) < 200:
                            break
                        pagina += 1
                    except Exception as e:
                        logger.error(f"  ano={ano} pag={pagina}: {e}")
                        break

            logger.info(f"  {mun_nome}: {len(items)} propostas FNS coletadas")
            return items

    def _normalize(self, p: dict, ano: int, mun_id: int, cod_fns: str) -> dict:
        """Mapeia proposta FNS -> schema UpsertItem do /internal/upsert."""
        tipo = p.get("coTipoProposta") or "PROPOSTA"
        recurso = p.get("dsTipoRecurso") or ""
        vl_prop = float(p.get("vlProposta") or 0)
        vl_pago = float(p.get("vlPago") or 0)
        vl_pagar = float(p.get("vlPagar") or 0)

        sit = ("Pago" if vl_pago > 0 and vl_pagar == 0
               else "Empenhado" if vl_pagar > 0
               else "Em analise" if vl_prop > 0
               else "Pendente")

        # nr_proposta sintetico estavel + hash anti-colisao (alinhado com
        # run_fns_local.py para que os dois scrapers produzam a MESMA chave)
        import hashlib
        nu_proc = p.get("nuProcesso") or "NA"
        h = hashlib.md5(json.dumps(p, sort_keys=True, default=str).encode()).hexdigest()[:8]
        nr_proposta = f"FNS-{cod_fns}-{ano}-{tipo[:8]}-{recurso[:6]}-{nu_proc[:8]}-{h}".replace(" ", "_")[:60]

        return {
            "municipio_id": mun_id,
            "nr_proposta": nr_proposta,
            "objeto": f"{tipo} - {recurso}".strip(" -")[:500],
            "programa": tipo[:500],
            "tipo_programa": tipo[:100],
            "valor": vl_pago or vl_prop,  # prefere repasse efetivo, fallback proposta
            "situacao": sit,
            "ano": ano,
            "fonte": "FNS",
            "orgao_concedente": "Min. Saude - FNS",
            "raw_data": p,  # destrava tela Parlamentares (le raw_data->>'parlamentares' etc)
        }


if __name__ == "__main__":
    cli(FNSScraper)
