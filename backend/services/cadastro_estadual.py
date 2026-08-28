"""O NOME DO CADASTRO ESTADUAL DE CONVENENTES, POR ESTADO — lado servidor.

Espelho de `frontend/src/lib/estadual.ts` (CADASTRO_ESTADUAL / UFS_ACOMPANHADAS).
As duas listas precisam andar juntas: um estado que entre aqui e nao la (ou o
contrario) faz a tela do modulo e o Painel de Indicadores discordarem, na mesma
sessao, sobre se a regularidade estadual daquele municipio e acompanhada.

⚠️ POR QUE ISTO EXISTE. "CAGEC" e o nome do cadastro de MINAS (Decreto
44.293/2006), nao do produto. A tabela `cagec_situacao` guarda o cadastro
estadual de QUALQUER estado que a gente colete — hoje o CAGEC mineiro e o CHE
gaucho — e todo texto que sai do servidor com o nome do cadastro (motivo de
"sem coleta", faixa da IA, push do celular, rotulo do documento vencendo) tem
de vir daqui, nunca de literal. Um cliente de Santa Maria/RS lia "CAGEC" no
proprio painel, e nao existe CAGEC no Rio Grande do Sul.

⚠️ LINHA NOVA SO COM COLETOR NO AR. Entrar aqui e afirmar ao Painel que a
regularidade estadual daquele estado esta acompanhada; entrar sem coletor e
prometer cobertura que nao existe.
"""
from __future__ import annotations

CADASTRO_ESTADUAL: dict[str, dict] = {
    # portalcagec.mg.gov.br — Cadastro Geral de Convenentes. O detalhamento vem
    # do CRC (certificado em PDF), coletado por ingestion/cagec_scraper.py.
    "MG": {
        "sigla": "CAGEC",
        "nome": "Cadastro Geral de Convenentes",
        "fonte": "CAGEC-MG",
        "portal": "www.cagec.mg.gov.br/convenente-web/consultaParceiros",
        # O CRC e onde estao os documentos e validades; sem ele a tela so tem a
        # situacao da consulta publica. Nos outros estados nao ha certificado.
        "certificado": "CRC",
        # O que a irregularidade trava — e diferente por estado, e a diferenca
        # e material: em Minas segura ate a parcela de convenio ja assinado.
        "trava": "impede assinar convênio estadual e a liberação de parcela",
    },
    # che.sefaz.rs.gov.br — Cadastro de Habilitacao em Convenios do Estado,
    # IN CAGE 01/2006. API JSON publica, coletada por ingestion/che_rs.py.
    "RS": {
        "sigla": "CHE",
        "nome": "Cadastro de Habilitação em Convênios do Estado",
        "fonte": "CHE-RS",
        "portal": "che.sefaz.rs.gov.br",
        "certificado": None,
        "trava": "impede celebrar convênio com o Estado",
    },
}

# As UFs cuja regularidade estadual este sistema COLETA. Derivado do catalogo
# para nao existir uma segunda lista para alguem esquecer de atualizar.
UFS_COM_CADASTRO_COLETADO: set[str] = set(CADASTRO_ESTADUAL)

ROTULO_GENERICO = "Cadastro estadual"

_POR_FONTE: dict[str, str] = {c["fonte"]: uf for uf, c in CADASTRO_ESTADUAL.items()}


def _uf(uf: str | None) -> str:
    return (uf or "").strip().upper()


def cadastro_da_uf(uf: str | None) -> dict | None:
    return CADASTRO_ESTADUAL.get(_uf(uf))


def uf_da_fonte(fonte: str | None) -> str | None:
    """'CHE-RS' -> 'RS'. Linha antiga sem `fonte` e do CAGEC (ver
    add_cadastro_estadual_rs.sql, que faz o backfill com 'CAGEC-MG')."""
    return _POR_FONTE.get((fonte or "CAGEC-MG").strip().upper())


def sigla_da_uf(uf: str | None) -> str:
    """'CAGEC', 'CHE' — ou o generico quando nao coletamos aquele estado."""
    c = cadastro_da_uf(uf)
    return c["sigla"] if c else ROTULO_GENERICO


def sigla_da_fonte(fonte: str | None) -> str:
    return sigla_da_uf(uf_da_fonte(fonte))


def rotulo_por_ufs(ufs) -> str:
    """Um estado so -> a sigla dele. Varios (carteira multi-estado) ou nenhum
    -> o generico, que e verdadeiro em qualquer lugar."""
    lista = sorted({_uf(u) for u in (ufs or []) if _uf(u)})
    if len(lista) == 1:
        return sigla_da_uf(lista[0])
    return ROTULO_GENERICO


def trava_da_uf(uf: str | None) -> str:
    c = cadastro_da_uf(uf)
    return c["trava"] if c else "impede celebrar convênio com o Estado"


def motivo_sem_coleta(uf: str | None) -> str:
    """A frase de "ainda nao coletado", com o nome e o portal DO ESTADO do
    municipio. Antes era uma so, mineira, e aparecia no painel gaucho mandando
    o prefeito consultar o portal do CAGEC."""
    c = cadastro_da_uf(uf)
    if not c:
        # Estado que nao coletamos: a frase e a de cobertura (bi_abas), nao
        # esta. Fica um fallback honesto caso alguem chame direto.
        return ("O cadastro estadual de convenentes deste estado ainda não é "
                "acompanhado por este sistema.")
    return (f"O {c['sigla']} deste município ainda não foi coletado. A coleta é "
            f"automática e usa o CNPJ do município; se ele ainda não foi identificado "
            f"nas bases, consulte em {c['portal']}.")
