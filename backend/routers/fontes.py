"""Status of data source integrations (atualizado 12/05/2026)."""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, text
from database import get_db
from models import IngestionLog, ConvenioFederal, ConvenioEstadual
from services.auth import get_current_user

router = APIRouter(prefix="/api/fontes", tags=["fontes"])


# Catalogo de fontes hoje em producao (15 fontes ativas + 4 bloqueadas)
# id: chave do scraper (= source na ingestion_log) | log_alias: nomes alternativos
FONTES = [
    # ============ FEDERAL convenios ============
    {
        "id": "transferegov",
        "nome": "TransfereGov / SICONV (Federal)",
        "categoria": "Federal - Convenios",
        "url": "http://repositorio.dados.gov.br/seges/detru/",
        "tipo": "Bulk CSV mensal + Range/resume",
        "frequencia": "Mensal (dia 1, 03h BRT)",
        "descricao": "Convenios federais formalizados + propostas pendentes 2025/26 (Festa Ruralista, Pavimentacao, etc). Servidor instavel - retomada automatica de download.",
    },
    {
        "id": "transferegov_proposta",
        "log_alias": ["transferegov"],
        "nome": "TransfereGov - Propostas Pendentes",
        "categoria": "Federal - Convenios",
        "url": "http://repositorio.dados.gov.br/seges/detru/",
        "tipo": "Bulk CSV (extracao customizada)",
        "frequencia": "Mensal",
        "descricao": "Propostas 2025/26 sem convenio formalizado ainda. Cobre o gap de itens em analise no Min. Saude/Fazenda.",
    },
    {
        "id": "portal_transparencia",
        "nome": "Portal da Transparencia (CGU)",
        "categoria": "Federal - Convenios",
        "url": "https://api.portaldatransparencia.gov.br/",
        "tipo": "REST API (PORTAL_TRANSPARENCIA_KEY)",
        "frequencia": "Diario",
        "descricao": "Transferencias federais por IBGE. Filtro reforcado contra cross-IBGE bug (Pirapora→Piracema).",
    },
    {
        "id": "codevasf",
        "nome": "CODEVASF (Doacoes/Maquinas)",
        "categoria": "Federal - Convenios",
        "url": "https://www.codevasf.gov.br/",
        "tipo": "Heuristica sobre TransfereGov",
        "frequencia": "Mensal",
        "descricao": "Doacoes de retroescavadeiras, motoniveladoras, caminhoes via emendas individuais.",
    },
    # ============ FNS (saude com sessao) ============
    {
        "id": "fns",
        "nome": "FNS - Fundo Nacional de Saude",
        "categoria": "Federal - Saude",
        "url": "https://consultafns.saude.gov.br/",
        "tipo": "REST API interna (sessao via bookmarklet PACTA)",
        "frequencia": "Mensal (sessao expira ~7 dias - re-capturar)",
        "descricao": "Incremento PAP/MAC, Custeio SUAS, Equipamentos saude. Cobertura Piracema 49%→99% PDF Freitas apos descoberta da API REST.",
    },
    # ============ ESTADUAL MG ============
    {
        "id": "sigcon_full",
        "log_alias": ["sigcon", "sigcon_real"],
        "nome": "SIGCON-MG (Estadual)",
        "categoria": "Estadual MG",
        "url": "https://dados.mg.gov.br/dataset/convenios-saida",
        "tipo": "Bulk CSV via dados.mg.gov.br",
        "frequencia": "Mensal",
        "descricao": "Transferencias Especiais SES/SEGOV/SEDEC. Bug ano +30 corrigido (138 itens reclassificados de 2050+ para 2020+).",
    },
    {
        "id": "almg",
        "nome": "ALMG (Deputados Estaduais MG)",
        "categoria": "Estadual MG",
        "url": "https://dadosabertos.almg.gov.br/",
        "tipo": "REST API publica",
        "frequencia": "Semanal (segunda 02h BRT)",
        "descricao": "53 deputados MG + emendas estaduais executadas.",
    },
    # ============ EMENDAS ============
    {
        "id": "camara_deputados",
        "nome": "Camara dos Deputados",
        "categoria": "Legislativo Federal",
        "url": "https://dadosabertos.camara.leg.br/",
        "tipo": "REST API publica",
        "frequencia": "Semanal",
        "descricao": "Despesas + emendas individuais 513 deputados. Cobre RP6/RP9 com auto-detect institucional.",
    },
    {
        "id": "senado",
        "nome": "Senado Federal",
        "categoria": "Legislativo Federal",
        "url": "https://legis.senado.leg.br/dadosabertos/",
        "tipo": "REST API publica",
        "frequencia": "Semanal",
        "descricao": "3 senadores MG (Rodrigo Pacheco, Carlos Viana, Cleitinho).",
    },
    {
        "id": "emendas_federais",
        "log_alias": ["emendas_federais"],
        "nome": "Emendas Federais (TransfereGov)",
        "categoria": "Emendas",
        "url": "http://repositorio.dados.gov.br/seges/detru/",
        "tipo": "Bulk CSV (siconv_emenda)",
        "frequencia": "Mensal",
        "descricao": "Vinculacao convenio→emenda→parlamentar autor.",
    },
    {
        "id": "emendas_estaduais",
        "nome": "Emendas Estaduais MG",
        "categoria": "Emendas",
        "url": "https://www.almg.gov.br/",
        "tipo": "Regex sobre objetos SIGCON",
        "frequencia": "Mensal",
        "descricao": "Extrai 'TRANSFERENCIA ESPECIAL: NOME - INDICACAO: NR' do objeto SIGCON.",
    },
    # ============ COMPLIANCE ============
    {
        "id": "ceis_api",
        "nome": "CEIS - Sancoes (CGU)",
        "categoria": "Compliance",
        "url": "https://api.portaldatransparencia.gov.br/",
        "tipo": "REST API CGU",
        "frequencia": "Semanal",
        "descricao": "Empresas sancionadas - cruza com fornecedores dos convenios.",
    },
    {
        "id": "cnes",
        "nome": "CNES (Estabelecimentos Saude)",
        "categoria": "Saude",
        "url": "https://cnes.datasus.gov.br/",
        "tipo": "REST API DataSUS",
        "frequencia": "Semanal",
        "descricao": "120+ UBS/UPAs por municipio. Vincula com Incremento PAP/MAC.",
    },
    {
        "id": "editais_pncp",
        "nome": "PNCP (Editais)",
        "categoria": "Licitacoes",
        "url": "https://pncp.gov.br/",
        "tipo": "REST API publica",
        "frequencia": "Diario (01h BRT)",
        "descricao": "Editais publicados no Portal Nacional de Contratacoes Publicas filtrados por palavra-chave.",
    },
    # ============ ELEITORAL ============
    {
        "id": "tse",
        "nome": "TSE - Dados Eleitorais",
        "categoria": "Eleitoral",
        "url": "https://dadosabertos.tse.jus.br/",
        "tipo": "Bulk CSV",
        "frequencia": "Mensal",
        "descricao": "Votacao por candidato/municipio - cruza com top parlamentares por valor.",
    },
    # ============ FALTANDO CREDENCIAL ============
    {
        "id": "simec",
        "nome": "SIMEC / PAR4 (Educacao)",
        "categoria": "BLOQUEADO - sem credencial",
        "url": "https://simec.mec.gov.br/par/",
        "tipo": "Portal web autenticado (Playwright)",
        "frequencia": "Pendente",
        "descricao": "PAR Plano Acoes Articuladas - construcao escolas + onibus escolar PAR4. Aguarda login do gestor no Cofre via XLSX upload.",
    },
    {
        "id": "sismob",
        "nome": "SISMOB (Obras Saude)",
        "categoria": "BLOQUEADO - sem credencial",
        "url": "https://sismobcidadao.saude.gov.br/",
        "tipo": "Portal web (Playwright)",
        "frequencia": "Pendente",
        "descricao": "Monitoramento de obras de UBS/UPA. Aguarda credencial Freitas.",
    },
    {
        "id": "suas",
        "nome": "Estrutura SUAS",
        "categoria": "BLOQUEADO - sem credencial",
        "url": "https://estruturasuas.mds.gov.br/",
        "tipo": "Portal web (Playwright)",
        "frequencia": "Pendente",
        "descricao": "MDS - infraestrutura assistencia social. Aguarda credencial.",
    },
    {
        "id": "dou_inlabs",
        "nome": "DOU INLABS (Diario Oficial)",
        "categoria": "BLOQUEADO - sem credencial",
        "url": "https://inlabs.in.gov.br/",
        "tipo": "REST API com login (INLABS_USER/INLABS_PASS)",
        "frequencia": "Pendente",
        "descricao": "Atos publicados no DOU filtrados por palavra-chave dos municipios. Sem credencial cadastrada.",
    },
]


def _classify_status(log, has_block_categoria: bool, hours_since: float | None) -> str:
    """ativo / instavel / configuravel (precisa cred) / manual."""
    if has_block_categoria:
        return "configuravel"
    if not log:
        return "manual"
    if log.status == "failed":
        return "instavel"
    if hours_since is not None:
        if hours_since < 48:
            return "ativo"
        if hours_since < 24 * 30:
            return "instavel"
    return "ativo"


@router.get("")
async def list_fontes(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Lista fontes com status real (cron + ingestion_log + counts)."""
    # 1. Ultimo log SUCCESS por source (e last log absoluto p/ ver failures)
    logs_q = select(IngestionLog).order_by(desc(IngestionLog.finished_at)).limit(200)
    logs_result = await db.execute(logs_q)
    last_success = {}
    last_any = {}
    for log in logs_result.scalars().all():
        if log.source not in last_any:
            last_any[log.source] = log
        if log.status == "success" and log.source not in last_success:
            last_success[log.source] = log

    # 2. Counts por fonte real em convenios_*
    counts_fed = {}
    cf_rows = await db.execute(text("SELECT fonte, count(*) FROM convenios_federal WHERE fonte IS NOT NULL GROUP BY fonte"))
    for r in cf_rows.fetchall():
        counts_fed[r[0]] = r[1]
    counts_est = {}
    ce_rows = await db.execute(text("SELECT fonte, count(*) FROM convenios_estadual WHERE fonte IS NOT NULL GROUP BY fonte"))
    for r in ce_rows.fetchall():
        counts_est[r[0]] = r[1]

    # Conta auxiliares
    cofre_n = (await db.execute(text("""
        SELECT automation_key, count(*) FROM cofre_senhas
        WHERE automation_key IS NOT NULL GROUP BY automation_key
    """))).fetchall()
    cofre_map = {r[0]: r[1] for r in cofre_n}

    now = datetime.now(timezone.utc)
    out = []

    for fonte in FONTES:
        info = dict(fonte)
        sources_to_check = [fonte["id"]] + (fonte.get("log_alias") or [])

        # Acha log mais recente entre todos os sources possiveis
        log = None
        for s in sources_to_check:
            lg = last_success.get(s)
            if lg and (not log or lg.finished_at > log.finished_at):
                log = lg

        hours_since = None
        if log and log.finished_at:
            info["ultima_ingestao"] = log.finished_at.isoformat()
            info["ultimo_status"] = log.status
            hours_since = (now - log.finished_at).total_seconds() / 3600
        else:
            info["ultima_ingestao"] = None
            info["ultimo_status"] = None

        info["horas_atras"] = round(hours_since, 1) if hours_since is not None else None

        # Categoria BLOQUEADO -> configuravel
        is_blocked = fonte["categoria"].startswith("BLOQUEADO")
        info["status"] = _classify_status(log, is_blocked, hours_since)

        # Registros: prefere conta direta na tabela; fallback log
        regs = 0
        for s_alias in [fonte["id"]] + (fonte.get("log_alias") or []):
            for src in (counts_fed, counts_est):
                # Tenta match por fonte name proxima ao id
                for k, v in src.items():
                    if k.lower().startswith(s_alias.lower().split("_")[0][:6]):
                        regs = max(regs, v)
        if regs == 0 and log:
            regs = log.records_inserted or 0
        info["registros"] = regs

        # Tem credencial? Marca pra UI
        info["credenciais_cadastradas"] = cofre_map.get(fonte["id"], 0)

        out.append(info)

    return out


@router.get("/resumo")
async def resumo_fontes(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Resumo executivo de status de fontes."""
    fontes = await list_fontes(db)
    return {
        "total": len(fontes),
        "ativas": sum(1 for f in fontes if f["status"] == "ativo"),
        "instaveis": sum(1 for f in fontes if f["status"] == "instavel"),
        "bloqueadas_sem_credencial": sum(1 for f in fontes if f["status"] == "configuravel"),
        "total_registros": sum(f.get("registros", 0) for f in fontes),
    }
