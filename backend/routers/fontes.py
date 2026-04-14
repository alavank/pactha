"""Status of data source integrations."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from database import get_db
from models import IngestionLog, ConvenioFederal, ConvenioEstadual
from services.auth import get_current_user

router = APIRouter(prefix="/api/fontes", tags=["fontes"])


FONTES = [
    {
        "id": "transferegov",
        "nome": "TransfereGov (Federal)",
        "categoria": "Federal",
        "url": "http://repositorio.dados.gov.br/seges/detru/",
        "tipo": "CSV diario (atualizado 9h)",
        "status": "instavel",
        "descricao": "Convenios e propostas federais. Servidor governamental com instabilidade intermitente.",
    },
    {
        "id": "sigcon",
        "nome": "SIGCON-MG (Estadual)",
        "categoria": "Estadual MG",
        "url": "https://dados.mg.gov.br/dataset/convenios-saida",
        "tipo": "CSV diario via dados.mg.gov.br",
        "status": "ativo",
        "descricao": "Convenios estaduais de Minas Gerais. Pipeline funcionando.",
    },
    {
        "id": "transparencia",
        "nome": "Portal da Transparencia (Emendas)",
        "categoria": "Federal",
        "url": "https://api.portaldatransparencia.gov.br/",
        "tipo": "REST API com token",
        "status": "configuravel",
        "descricao": "Emendas parlamentares federais. Requer registro de email para token.",
    },
    {
        "id": "fns",
        "nome": "FNS - Fundo Nacional de Saude / InvestSUS",
        "categoria": "Saude",
        "url": "https://consultafns.saude.gov.br/",
        "tipo": "Portal web (sem API publica)",
        "status": "manual",
        "descricao": "Transferencias do Ministerio da Saude. Requer scraping ou consulta manual.",
    },
    {
        "id": "simec",
        "nome": "SIMEC / PAR (Educacao)",
        "categoria": "Educacao",
        "url": "https://simec.mec.gov.br/par/",
        "tipo": "Portal web autenticado",
        "status": "manual",
        "descricao": "Plano de Acoes Articuladas - Construcao de escolas. Requer login do gestor.",
    },
    {
        "id": "sismob",
        "nome": "SISMOB (Obras de Saude)",
        "categoria": "Saude",
        "url": "https://sismobcidadao.saude.gov.br/",
        "tipo": "Portal web publico",
        "status": "manual",
        "descricao": "Monitoramento de obras de saude (UBS, ampliacoes). Sem API publica.",
    },
    {
        "id": "estrutura_suas",
        "nome": "Estrutura SUAS (Assistencia Social)",
        "categoria": "Assistencia Social",
        "url": "https://estruturasuas.mds.gov.br/",
        "tipo": "Portal web autenticado",
        "status": "manual",
        "descricao": "Sistema do MDS para infraestrutura de assistencia social.",
    },
    {
        "id": "tse",
        "nome": "TSE - Dados Eleitorais",
        "categoria": "Eleitoral",
        "url": "https://dadosabertos.tse.jus.br/",
        "tipo": "CSV download",
        "status": "ativo",
        "descricao": "Resultados eleitorais por municipio (TSE 2022 carregado).",
    },
]


@router.get("")
async def list_fontes(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """List all data sources with their status and last sync."""
    result = []

    # Get last ingestion per source
    logs_q = select(IngestionLog).order_by(desc(IngestionLog.started_at)).limit(50)
    logs_result = await db.execute(logs_q)
    logs_by_source = {}
    for log in logs_result.scalars().all():
        if log.source not in logs_by_source:
            logs_by_source[log.source] = log

    # Counts
    fed_count = (await db.execute(select(func.count()).select_from(ConvenioFederal))).scalar()
    est_count = (await db.execute(select(func.count()).select_from(ConvenioEstadual))).scalar()

    for fonte in FONTES:
        info = dict(fonte)
        log = logs_by_source.get(fonte["id"])
        if log:
            info["ultima_ingestao"] = log.started_at.isoformat() if log.started_at else None
            info["ultimo_status"] = log.status
            info["registros"] = log.records_inserted
        else:
            info["ultima_ingestao"] = None
            info["ultimo_status"] = None
            info["registros"] = 0

        # Override registros for known sources
        if fonte["id"] == "transferegov":
            info["registros"] = fed_count
        elif fonte["id"] == "sigcon":
            info["registros"] = est_count

        result.append(info)

    return result
