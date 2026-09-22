"""
Superficie de CONTROL-PLANE que a instancia expoe ao Console Alavank.
Tudo sob /api/control/*, autenticado por X-Control-Token (kind='control', scope control:*).
Enderecamento por CHAVE ESTAVEL (ibge_code), nunca pelo id autoincrement interno.

Municipio NAO tem delecao (decisao do usuario) — no maximo desativar via PATCH.
"""
import os
import base64
import json as _json
import secrets as pysecrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from database import get_db
from models import Municipio
from models.user import User
from models.cofre import CofreSenha
from models.audit import AuditLog
from models.service_token import ServiceToken
from services.control_auth import require_control_scope, ControlPrincipal
from services.auth import hash_password, create_sso_token
from services.service_auth import hash_token
from services import users_admin, crypto
from services.telas_catalog import TELAS_CATALOG, TELAS_TODAS
from services.audit import registrar, registrar_critico

router = APIRouter(prefix="/api/control", tags=["control"])


# Cabecalhos com que o Console identifica a PESSOA por tras da chamada. Ficam em
# ordem de preferencia; o primeiro que parecer e-mail vale.
_HEADERS_ATOR = ("x-control-actor", "x-operator-email", "x-actor-email")

# NOTA sobre a chave `integracao` nos `details` daqui: ela guarda `p.name`, o
# nome do control token (ex.: "console-alavank"), e ANTES se chamava "token".
# O sanitizador de `services/audit.py` redige por SUBSTRING qualquer chave que
# contenha "token" — corretamente, porque em 99% dos casos ali dentro estaria um
# segredo. Com o nome antigo, a unica identificacao da origem virava "[oculto]".


def _ator(request: Request, p: ControlPrincipal) -> str:
    """Quem, do lado da Alavank, esta agindo — para o campo indexado `user_email`.

    Todo evento `control.*` gravava `user_email` NULO: sobrava o nome do token em
    `details`, que identifica a INTEGRACAO, nao a pessoa. "Quem da Alavank revelou
    a senha do gov.br desta prefeitura" simplesmente nao existia como pergunta
    respondivel, e e exatamente o tipo de acesso que a LGPD manda rastrear.

    O Console envia o tecnico logado num destes cabecalhos. Quando nao envia (ou
    e uma automacao sem gente na frente), o responsavel possivel e o TOKEN — e ai
    grava-se `control-token:<nome>`.

    ⚠️ OS DOIS VALORES SAO SEMPRE PREFIXADOS, e o prefixo nao e enfeite. O
    cabecalho e uma AFIRMACAO de quem detem o control token: nada aqui prova que
    o tecnico e aquele. Gravado como e-mail cru, um Console comprometido (ou com
    bug) escreveria `admin@montesiao.mg.gov.br` no campo indexado e a trilha
    apontaria o servidor da prefeitura como autor de um ato que so o canal da
    Alavank consegue praticar — envenenar a prova justamente no incidente em que
    ela serve. Com `control:` na frente, um evento do canal externo nunca se
    confunde com o login de uma pessoa do tenant, e continua achavel na busca por
    e-mail (que e `ilike '%termo%'`, nao igualdade). O ator VERIFICADO — o token
    autenticado — vai em `details.integracao` nas 13 chamadas, sempre."""
    for h in _HEADERS_ATOR:
        v = (request.headers.get(h) or "").strip().lower()
        if v and "@" in v and len(v) <= 200:
            return f"control:{v}"
    return f"control-token:{p.name}"[:255]


def _mun(m: Municipio) -> dict:
    return {"ibge_code": m.ibge_code, "nome": m.nome, "uf": m.uf,
            "active": bool(m.active), "fns_code": m.fns_code,
            "cnpj": m.cnpj, "corede": m.corede,
            "tce_orgao_codigo": m.tce_orgao_codigo,
            "fundo_reconstrucao": m.fundo_reconstrucao,
            "fundo_reconstrucao_obs": m.fundo_reconstrucao_obs,
            "calamidade_ate": m.calamidade_ate.isoformat() if m.calamidade_ate else None}


class MunicipioIn(BaseModel):
    ibge_code: str
    nome: str
    # ⚠️ SEM default. Municipio criado sem UF nascia "MG" e todo filtro por
    # estado passava a mentir — Minas e mais um estado, nao o padrao.
    uf: str
    fns_code: str | None = None
    # ⭐ O CNPJ nao e enfeite de cadastro: e o unico parametro do coletor do
    # cadastro estadual gaucho (CHE). Ate 08/2026 ele era inferido de dado ja
    # coletado, o que so funciona onde a coleta estadual existe — em MG.
    cnpj: str | None = None
    corede: str | None = None
    tce_orgao_codigo: str | None = None


class MunicipioPatch(BaseModel):
    nome: str | None = None
    uf: str | None = None
    active: bool | None = None
    fns_code: str | None = None
    cnpj: str | None = None
    corede: str | None = None
    tce_orgao_codigo: str | None = None
    fundo_reconstrucao: bool | None = None
    fundo_reconstrucao_obs: str | None = None
    # ISO (AAAA-MM-DD) ou "" para limpar.
    calamidade_ate: str | None = None


def _cnpj_valido(bruto: str) -> str | None:
    """14 digitos, sem mascara — o formato que as APIs de governo aceitam.

    Devolve None para string vazia (limpar o campo e uma acao legitima) e
    levanta 400 para qualquer coisa que nao seja vazio nem 14 digitos: CNPJ
    truncado nao "quase funciona", ele consulta a entidade ERRADA."""
    if bruto is None:
        return None
    d = "".join(ch for ch in bruto if ch.isdigit())
    if not d:
        return None
    if len(d) != 14:
        raise HTTPException(status_code=400,
                            detail="cnpj deve ter 14 dígitos (com ou sem máscara)")
    return d


# --- Municipios ---
@router.get("/municipios")
async def list_municipios(
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:municipios:read")),
):
    """Lista TODOS os municipios, inclusive inativos (difere do GET de usuario)."""
    rows = (await db.execute(select(Municipio).order_by(Municipio.nome))).scalars().all()
    return [_mun(m) for m in rows]


@router.post("/municipios")
async def upsert_municipio(
    body: MunicipioIn, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:municipios:write")),
):
    """Upsert por ibge_code (reativa se estiver inativo)."""
    ibge = (body.ibge_code or "").strip()
    nome = (body.nome or "").strip()
    uf = (body.uf or "").strip().upper()[:2]
    if len(ibge) != 7 or not ibge.isdigit():
        raise HTTPException(status_code=400, detail="ibge_code deve ter 7 dígitos")
    if not nome:
        raise HTTPException(status_code=400, detail="nome obrigatório")
    if len(uf) != 2 or not uf.isalpha():
        raise HTTPException(status_code=400, detail="uf obrigatória (sigla de 2 letras)")

    fns = None
    if body.fns_code is not None:
        fns = "".join(ch for ch in body.fns_code if ch.isdigit())[:6] or None
    cnpj = _cnpj_valido(body.cnpj) if body.cnpj is not None else None
    m = (await db.execute(select(Municipio).where(Municipio.ibge_code == ibge))).scalar_one_or_none()
    created = m is None
    if m is None:
        m = Municipio(nome=nome, ibge_code=ibge, uf=uf, active=True, fns_code=fns,
                      cnpj=cnpj, corede=(body.corede or None),
                      tce_orgao_codigo=(body.tce_orgao_codigo or None))
        db.add(m)
    else:
        m.nome = nome
        m.uf = uf
        m.active = True
        if body.fns_code is not None:
            m.fns_code = fns
        # Só sobrescreve o que veio no corpo: o upsert é chamado para reativar
        # município, e apagar o CNPJ nessa hora desligaria o coletor estadual.
        if body.cnpj is not None:
            m.cnpj = cnpj
        if body.corede is not None:
            m.corede = body.corede or None
        if body.tce_orgao_codigo is not None:
            m.tce_orgao_codigo = body.tce_orgao_codigo or None
    await db.commit()
    await db.refresh(m)
    if created:
        # MUNICIPIO NOVO PRECISA CHEGAR A ALGUEM — senao ele nasce invisivel.
        #
        # Ate este incremento nao havia o que fazer aqui: `role == "admin"`
        # zerava `allowed_municipio_ids`, entao a cidade recem-cadastrada ja
        # aparecia para os administradores do cliente no primeiro F5. Com o papel
        # virado rotulo, quem nao tem LINHA em `user_municipios` leva
        # "Voce nao tem acesso a este municipio" — e o municipio novo nao tem
        # linha para ninguem. A assessoria assinaria a cidade nova pelo Console e
        # o cliente nao a veria, sem erro nenhum que explicasse.
        #
        # O criterio NAO e o papel (ele nao concede mais nada): e COBERTURA. Quem
        # ja tinha TODOS os outros municipios continua com todos — o admin de uma
        # prefeitura, o gestor da assessoria que cuida da carteira inteira. Quem
        # estava limitado a 2 de 5 segue limitado a 2 de 6, que e o ponto do
        # incremento: ninguem ganha alcance por efeito colateral de cadastro.
        #
        # Fora do alcance, explicitamente:
        #  · quem nao tem municipio NENHUM — sem isto, "tem todos os outros"
        #    seria verdade VAZIA para uma conta sem acesso, e ela ganharia a
        #    cidade nova sem nunca ter tido nada;
        #  · as contas de QUIOSQUE (links publicos de TV). Elas espelham o dono
        #    na emissao e nao podem crescer sozinhas depois — um link colado numa
        #    TV passaria a mostrar uma cidade que nao existia quando foi gerado.
        await db.execute(text("""
            INSERT INTO user_municipios (user_id, municipio_id)
            SELECT u.id, :novo
              FROM users u
             WHERE u.active
               AND NOT u.kiosk
               AND u.email NOT LIKE '%@painel.local'
               AND EXISTS (SELECT 1 FROM user_municipios um WHERE um.user_id = u.id)
               AND NOT EXISTS (
                     SELECT 1 FROM municipios m2
                      WHERE m2.id <> :novo
                        AND NOT EXISTS (
                              SELECT 1 FROM user_municipios um2
                               WHERE um2.user_id = u.id AND um2.municipio_id = m2.id))
            ON CONFLICT DO NOTHING
        """), {"novo": m.id})
        await db.commit()
    await registrar(db, action="control.municipio.upsert", request=request,
                    user_email=_ator(request, p), municipio_id=m.id,
                    target_type="municipio", target_id=ibge, alvo_nome=f"{nome}/{uf}",
                    details={"nome": nome, "uf": uf, "created": created, "integracao": p.name})
    return _mun(m)


@router.patch("/municipios/{ibge_code}")
async def patch_municipio(
    ibge_code: str, body: MunicipioPatch, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:municipios:write")),
):
    """Renomear / mudar UF / ativar-desativar. Municipio NAO deleta (sem DELETE)."""
    m = (await db.execute(select(Municipio).where(Municipio.ibge_code == ibge_code))).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Município não encontrado")
    changed = []
    if body.nome is not None and body.nome.strip():
        m.nome = body.nome.strip(); changed.append("nome")
    if body.uf is not None and body.uf.strip():
        uf_nova = body.uf.strip().upper()[:2]
        # Mesma regra do POST: uf agora dirige coletor (CAGEC, Acordo FES) e
        # filtro de tela — "MI" truncado de "Minas" desligaria tudo em silencio.
        if len(uf_nova) != 2 or not uf_nova.isalpha():
            raise HTTPException(status_code=400, detail="uf inválida (sigla de 2 letras)")
        m.uf = uf_nova; changed.append("uf")
    if body.active is not None:
        m.active = bool(body.active); changed.append("active")
    if body.fns_code is not None:
        m.fns_code = "".join(ch for ch in body.fns_code if ch.isdigit())[:6] or None
        changed.append("fns_code")
    if body.cnpj is not None:
        m.cnpj = _cnpj_valido(body.cnpj); changed.append("cnpj")
    if body.corede is not None:
        m.corede = body.corede.strip() or None; changed.append("corede")
    if body.tce_orgao_codigo is not None:
        m.tce_orgao_codigo = body.tce_orgao_codigo.strip() or None
        changed.append("tce_orgao_codigo")
    if body.fundo_reconstrucao is not None:
        m.fundo_reconstrucao = bool(body.fundo_reconstrucao)
        changed.append("fundo_reconstrucao")
    if body.fundo_reconstrucao_obs is not None:
        m.fundo_reconstrucao_obs = body.fundo_reconstrucao_obs.strip() or None
        changed.append("fundo_reconstrucao_obs")
    if body.calamidade_ate is not None:
        bruto = body.calamidade_ate.strip()
        if not bruto:
            m.calamidade_ate = None
        else:
            from datetime import date as _date
            try:
                m.calamidade_ate = _date.fromisoformat(bruto)
            except ValueError:
                raise HTTPException(status_code=400,
                                    detail="calamidade_ate deve ser AAAA-MM-DD (ou vazio)")
        changed.append("calamidade_ate")
    await db.commit()
    await db.refresh(m)
    await registrar(db, action="control.municipio.patch", request=request,
                    user_email=_ator(request, p), municipio_id=m.id,
                    target_type="municipio", target_id=ibge_code, alvo_nome=f"{m.nome}/{m.uf}",
                    details={"changed": changed, "active": m.active, "integracao": p.name})
    return _mun(m)


# --- Status/identidade (o Console confirma que fala com o tenant certo) ---
@router.get("/status")
async def control_status(
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:status:read")),
):
    async def _count(sql: str):
        try:
            return (await db.execute(text(sql))).scalar()
        except Exception:
            await db.rollback()
            return None

    return {
        "instance_slug": os.getenv("INSTANCE_SLUG", ""),
        "env": os.getenv("ENV", ""),
        "db_ok": True,
        "counts": {
            "municipios": await _count("SELECT COUNT(*) FROM municipios"),
            "municipios_ativos": await _count("SELECT COUNT(*) FROM municipios WHERE active = true"),
            "users": await _count("SELECT COUNT(*) FROM users"),
            "cofre_senhas": await _count("SELECT COUNT(*) FROM cofre_senhas"),
            # fontes de dados
            "convenios_estadual": await _count("SELECT COUNT(*) FROM convenios_estadual"),
            "transferegov_propostas": await _count("SELECT COUNT(*) FROM transferegov_propostas"),
            "emendas_estaduais": await _count("SELECT COUNT(*) FROM emendas_estaduais"),
            "cauc_situacao": await _count("SELECT COUNT(*) FROM cauc_situacao"),
            "acordofes_credor": await _count("SELECT COUNT(*) FROM acordofes_credor"),
            "siconv_federal": await _count("SELECT COUNT(*) FROM siconv_federal"),
        },
        "control_token": p.name,
    }


# --- Ingestao por fonte (ingestion_log) — a Central monitora a carga de cada fonte ---
@router.get("/ingestion")
async def control_ingestion(
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:data:read")),
):
    """Ultimas execucoes por fonte (source, status, registros, quando). Isto e o
    historico real de ingestao — cada script grava aqui."""
    try:
        rows = (await db.execute(text(
            # inserted+updated na MESMA chave que a Central ja le: o sigcon
            # passou a gravar as duas colunas separadas, e em regime estavel
            # (quase tudo update) o inserted cru viraria 0 e pareceria coleta
            # quebrada no console. LIMIT 80: o lote horario adiciona 24
            # linhas/dia e com 40 o historico encolhia para ~1 dia.
            "SELECT source, status, "
            "records_inserted + coalesce(records_updated, 0) AS records_inserted, "
            "to_char(finished_at, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS finished_at "
            "FROM ingestion_log ORDER BY id DESC LIMIT 80"
        ))).mappings().all()
        # ⭐ A ULTIMA RODADA DE CADA FONTE, sem depender da janela. As 80 linhas
        # acima sao um HISTORICO, e historico tem janela: numa hora de coleta
        # intensa (o sigcon reloga cauc/acordofes/simec a cada rodada) as fontes
        # diarias somem das 80 linhas e quem le conclui "fonte parada" — foi
        # exatamente o falso-positivo de uma auditoria em 17/08 (42 municipios
        # acusados por uma fonte que tinha rodado 1h antes). DISTINCT ON e a
        # resposta certa da pergunta "quando cada fonte rodou pela ultima vez".
        ultimos = (await db.execute(text(
            "SELECT DISTINCT ON (source) source, status, "
            "records_inserted + coalesce(records_updated, 0) AS records_inserted, "
            "to_char(finished_at, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS finished_at "
            "FROM ingestion_log ORDER BY source, id DESC"
        ))).mappings().all()
        return {"log": [dict(r) for r in rows],
                "ultimo_por_fonte": {r["source"]: {
                    "status": r["status"], "records": r["records_inserted"],
                    "finished_at": r["finished_at"]} for r in ultimos}}
    except Exception:
        await db.rollback()
        return {"log": [], "error": "tabela ingestion_log indisponível"}


# ⭐ COBERTURA POR MUNICIPIO — a pergunta que o /fontes nao responde.
#
# O `/fontes` conta o TENANT inteiro: "2405 convenios estaduais" nao diz se os 60
# municipios do Freitas tem dado ou se 2405 sao de tres deles. Auditar cobertura
# exigia abrir o banco a mao, municipio por municipio, toda vez.
#
# ⚠️ A LISTA E CURADA, e nao um SELECT no information_schema por `municipio_id`.
# Varredura automatica traria `user_municipios`, `gestao_anotacoes`,
# `documentos_gerados` — coisas que o CLIENTE cria, nao que a coleta traz. Zero
# ali e trabalho nao feito, nao fonte parada, e misturar as duas leituras faria a
# auditoria mentir nos dois sentidos.
#
# Tabela que nao existe naquele tenant e omitida em silencio (cada consulta cai
# no seu proprio try), que e o comportamento certo: `consulta_popular_rs` so
# existe onde a migration do RS rodou.
_COBERTURA_TABELAS = [
    # (tabela, rotulo legivel, area)
    ("emendas_estaduais",    "Emendas estaduais",            "Estadual"),
    ("repasses_estaduais",   "Repasses estaduais",           "Estadual"),
    ("cofinanciamento_saude", "Cofinanciamento saúde",       "Estadual"),
    ("consulta_popular_rs",  "Consulta Popular (RS)",        "Estadual"),
    ("cauc_situacao",        "CAUC (regularidade federal)",  "Regularidade"),
    ("contas_irregulares",   "Contas irregulares",           "Regularidade"),
    ("transferegov_propostas", "TransfereGov (voluntárias)", "Federal"),
    ("transferegov_pac",     "TransfereGov PAC",             "Federal"),
    ("transferegov_te",      "Transferências Especiais",     "Federal"),
    ("sismob_obras",         "SISMOB (obras de saúde)",      "Saúde"),
    ("acordofes_credor",     "Acordo FES",                   "Saúde"),
    ("simec_par_liberacoes", "SIMEC-PAR (educação)",         "Educação"),
    # O INSTRUMENTO, nao o pagamento. Um municipio pode ter Termo de Compromisso
    # vigente com ZERO liberacao — contar so as liberacoes esconderia
    # exatamente esse caso, que e o que a auditoria de cobertura existe para
    # achar. Vai na lista simples (mono-fonte: a migration nao tem coluna
    # `fonte`, entao o CASE de _COBERTURA_POR_FONTE nao se aplica) e o rotulo e
    # distinto de proposito: `m["fontes"]` e dict indexado pelo rotulo, e
    # repetir a string sobrescreveria a contagem das liberacoes em silencio.
    ("simec_termos",         "SIMEC-PAR (termos de compromisso)", "Educação"),
]

# ⚠️ DUAS TABELAS SAO MULTI-FONTE, e contar o total mentiria dos dois lados.
# `convenios_estadual` guarda SIGCON-MG, FNS, GConv-ES e CAGE-RS na mesma
# tabela, discriminados pela coluna `fonte` (o mesmo criterio do freshness.py);
# `cagec_situacao` guarda CAGEC-MG e CHE-RS. Um municipio goiano com 40
# propostas FNS apareceria com "40 convenios estaduais" — e um mineiro sem
# nenhum convenio SIGCON ficaria escondido atras das propostas FNS dele.
# O CASE abaixo separa no SQL, uma linha por (municipio, fonte).
_COBERTURA_POR_FONTE = [
    ("convenios_estadual", """
        CASE WHEN fonte ILIKE '%FNS%'   THEN 'FNS (propostas)'
             WHEN fonte ILIKE '%GCONV%' THEN 'Convênios GConv-ES'
             WHEN fonte = 'CAGE-RS'     THEN 'Convênios CAGE-RS'
             WHEN fonte = 'SIT-PR'      THEN 'Convênios SIT-PR'
             ELSE 'Convênios SIGCON-MG' END""",
     {"FNS (propostas)": "Saúde", "Convênios GConv-ES": "Estadual",
      "Convênios CAGE-RS": "Estadual", "Convênios SIT-PR": "Estadual",
      "Convênios SIGCON-MG": "Estadual"}),
    ("cagec_situacao", """
        CASE WHEN fonte = 'CHE-RS' THEN 'CHE-RS (habilitação)'
             ELSE 'CAGEC-MG (habilitação)' END""",
     {"CHE-RS (habilitação)": "Regularidade",
      "CAGEC-MG (habilitação)": "Regularidade"}),
]


@router.get("/cobertura")
async def control_cobertura(
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:data:read")),
):
    """Quantas linhas cada município tem em cada fonte + a última coleta dele.

    Uma consulta POR TABELA agrupando por `municipio_id` — nunca uma por
    município. Com 60 municípios e 14 tabelas, o laço ingênuo seriam 840 idas ao
    banco; assim são 14. `scraper_municipio_coleta` responde a outra metade da
    pergunta: quando cada município foi visitado por cada fonte, e com que erro.
    """
    muns = (await db.execute(text(
        "SELECT id, nome, upper(coalesce(uf,'')) AS uf, ibge_code, cnpj, active "
        "FROM municipios ORDER BY uf, nome"))).mappings().all()
    saida = {m["id"]: {"id": m["id"], "nome": m["nome"], "uf": m["uf"],
                       "ibge": m["ibge_code"], "cnpj": m["cnpj"],
                       "ativo": bool(m["active"]), "fontes": {}, "coletas": {}}
             for m in muns}

    for tabela, rotulo, area in _COBERTURA_TABELAS:
        try:
            rows = (await db.execute(text(
                f"SELECT municipio_id, COUNT(*) AS n FROM {tabela} "
                f"WHERE municipio_id IS NOT NULL GROUP BY municipio_id"))).mappings().all()
        except Exception:
            # Tabela ausente neste tenant (ou sem municipio_id): não é erro, é
            # uma fonte que aquele cliente não tem. Segue sem registrar a chave.
            await db.rollback()
            continue
        for m in saida.values():
            m["fontes"][rotulo] = {"area": area, "n": 0}
        for r in rows:
            alvo = saida.get(r["municipio_id"])
            if alvo is not None:
                alvo["fontes"][rotulo]["n"] = r["n"]

    # As tabelas multi-fonte: uma consulta por tabela, o CASE separa os rotulos.
    for tabela, case_sql, areas in _COBERTURA_POR_FONTE:
        try:
            rows = (await db.execute(text(
                f"SELECT municipio_id, {case_sql} AS rotulo, COUNT(*) AS n "
                f"FROM {tabela} WHERE municipio_id IS NOT NULL "
                f"GROUP BY 1, 2"))).mappings().all()
        except Exception:
            await db.rollback()
            continue
        for m in saida.values():
            for rot, area in areas.items():
                m["fontes"][rot] = {"area": area, "n": 0}
        for r in rows:
            alvo = saida.get(r["municipio_id"])
            if alvo is not None and r["rotulo"] in alvo["fontes"]:
                alvo["fontes"][r["rotulo"]]["n"] = r["n"]

    try:
        coletas = (await db.execute(text(
            "SELECT fonte, municipio_id, "
            "to_char(ultima_coleta_em, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS ultima, "
            "to_char(ultimo_erro_em,  'YYYY-MM-DD\"T\"HH24:MI:SS') AS erro_em, "
            "left(coalesce(ultimo_erro, ''), 200) AS erro, tentativas "
            "FROM scraper_municipio_coleta"))).mappings().all()
        for c in coletas:
            alvo = saida.get(c["municipio_id"])
            if alvo is not None:
                alvo["coletas"][c["fonte"]] = {
                    "ultima": c["ultima"], "erro_em": c["erro_em"],
                    "erro": c["erro"] or None, "tentativas": c["tentativas"],
                }
    except Exception:
        await db.rollback()

    return {"instance_slug": os.getenv("INSTANCE_SLUG", ""),
            "municipios": list(saida.values())}


# --- Coleta assistida de Transferencias Especiais -------------------------
class TeLoteIn(BaseModel):
    planos: list[dict] = []
    # Presente = fecha a rodada: grava a linha do ingestion_log com este status.
    registrar_rodada: dict | None = None   # {"status": "success|partial", "obs": "..."}


@router.post("/te/lote")
async def control_te_lote(
    body: TeLoteIn, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:data:write")),
):
    """Recebe planos de acao da API 'especiais' coletados por um IP EXTERNO.

    ⭐ POR QUE ISTO EXISTE: a API do TransfereGov Especiais aplica quota por IP
    com penalidade estendida por martelada (INFRA.md §5) — e em 17/08 o IP da
    VPS ficou banido por horas, com a API respondendo 200 normalmente a
    qualquer outro IP. Este endpoint fecha o circuito: a Alavank coleta de um
    IP limpo e entrega pelos canais ja autenticados, com o MESMO mapeamento de
    campos e o MESMO upsert do coletor (`ingestion/transferegov_te.py::
    plano_para_linha` / `UPSERT_SQL_NOMEADO` — um lugar so; drift impossivel).

    O casamento plano->municipio reusa `_casa_municipio` do coletor, contra a
    carteira DESTE tenant. Idempotente por plano_acao_id: reenviar e inofensivo.
    """
    from ingestion.transferegov_te import (
        UPSERT_SQL_NOMEADO, _casa_municipio, _norm, plano_para_linha,
    )

    pares_rows = (await db.execute(text(
        "SELECT id, nome FROM municipios WHERE uf IS NOT NULL"))).all()
    pares = sorted(((_norm(n), i) for i, n in pares_rows if n),
                   key=lambda x: len(x[0]), reverse=True)

    recebidos, gravados, casados = len(body.planos), 0, 0
    for it in body.planos:
        mid = _casa_municipio(_norm(it.get("beneficiarioNome") or ""), pares)
        linha = plano_para_linha(it, mid)
        if linha is None:
            continue
        await db.execute(text(UPSERT_SQL_NOMEADO), linha)
        gravados += 1
        if mid is not None:
            casados += 1
    await db.commit()

    if body.registrar_rodada:
        st = str(body.registrar_rodada.get("status") or "success")[:20]
        obs = str(body.registrar_rodada.get("obs") or "coleta assistida (IP externo)")[:480]
        await db.execute(text(
            "INSERT INTO ingestion_log (source, status, records_inserted, error_message, finished_at) "
            "VALUES ('transferegov_te', :st, :n, :obs, NOW())"),
            {"st": st, "n": casados, "obs": obs})
        await db.commit()

    await registrar(db, action="control.te.lote", request=request,
                    user_email=_ator(request, p),
                    target_type="scraper", target_id="transferegov_te",
                    alvo_nome="TE (coleta assistida)",
                    details={"recebidos": recebidos, "gravados": gravados,
                             "casados": casados, "integracao": p.name,
                             "rodada": bool(body.registrar_rodada)})
    return {"recebidos": recebidos, "gravados": gravados, "casados": casados}


# Catalogo de fontes p/ o Monitor da Central: tabela contada (escopada por municipio
# ativo = o que o cliente REALMENTE ve) + nomes que cada scraper grava no ingestion_log.
_FONTES_MONITOR = [
    {"key": "convenios_estadual", "sources": ["sigcon_scraper", "sigcon_ckan_backfill"]},
    {"key": "transferegov_propostas", "sources": ["transferegov_voluntarias", "transferegov_lote",
                                                  "siconv_licitacao"]},
    {"key": "emendas_estaduais", "sources": ["emendas_estaduais"]},
    {"key": "cauc_situacao", "sources": ["cauc"]},
    {"key": "acordofes_credor", "sources": ["acordofes"]},
    {"key": "siconv_federal", "sources": ["siconv_federal", "siconv_convenio_backfill", "siconv_emenda_backfill"]},
]


@router.get("/fontes")
async def control_fontes(
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:data:read")),
):
    """Saude por fonte p/ o Monitor: contagem ESCOPADA pelos municipios ATIVOS (o que o
    cliente realmente ve, ao contrario do /status que conta a tabela crua) + a ultima
    execucao (ingestion_log). So leitura. Fail-safe: cada consulta cai em None."""
    async def _scoped_count(table: str):
        # 1) so o que pertence a municipio ATIVO; 2) fallback contagem crua (tabela sem
        # municipio_id); None se a tabela nao existir. Retorna (n, escopado?).
        scoped_sql = (f"SELECT COUNT(*) FROM {table} t "
                      f"JOIN municipios m ON m.id = t.municipio_id WHERE m.active = true")
        try:
            return (await db.execute(text(scoped_sql))).scalar(), True
        except Exception:
            await db.rollback()
        try:
            return (await db.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar(), False
        except Exception:
            await db.rollback()
            return None, False

    async def _last_run(sources: list):
        if not sources:
            return None, None
        names = {f"s{i}": s for i, s in enumerate(sources)}
        inclause = ", ".join(f":{k}" for k in names)
        try:
            row = (await db.execute(text(
                f"SELECT status, to_char(finished_at, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS finished_at "
                f"FROM ingestion_log WHERE source IN ({inclause}) ORDER BY id DESC LIMIT 1"
            ), names)).mappings().first()
            return (row["status"], row["finished_at"]) if row else (None, None)
        except Exception:
            await db.rollback()
            return None, None

    out = []
    for f in _FONTES_MONITOR:
        registros, escopado = await _scoped_count(f["key"])
        status, finished_at = await _last_run(f["sources"])
        out.append({
            "key": f["key"], "registros": registros, "escopo_ativo": escopado,
            "ultimo_status": status, "ultima_coleta": finished_at,
        })
    return {"fontes": out, "instance_slug": os.getenv("INSTANCE_SLUG", "")}


# --- Ingestao de dados (povoar/testar pela Central) ---
class RefreshIn(BaseModel):
    source: str = "sigcon"


@router.post("/refresh")
async def control_refresh(
    body: RefreshIn, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:data:write")),
):
    """Enfileira um job de scraping (mesma fila do refresh on-demand da UI). Dedup:
    nao enfileira se ja houver pending/running do mesmo tipo. Consumido pelo Worker
    (Scheduled Task -> ingestion/run_queue_sigcon.py). Hoje: 'sigcon' (dados abertos,
    sem credencial)."""
    source = (body.source or "sigcon").strip().lower()
    if source != "sigcon":
        raise HTTPException(status_code=400, detail="fonte nao suportada (use: sigcon)")
    row = (await db.execute(text(
        "INSERT INTO scraper_jobs (tipo, status) "
        "SELECT :t, 'pending' "
        "WHERE NOT EXISTS (SELECT 1 FROM scraper_jobs WHERE tipo = :t AND status IN ('pending','running')) "
        "RETURNING id"
    ), {"t": source})).first()
    await db.commit()
    await registrar(db, action="control.refresh", request=request,
                    user_email=_ator(request, p),
                    target_type="scraper", target_id=source, alvo_nome="SIGCON-MG",
                    details={"queued": row is not None, "integracao": p.name,
                             "job_id": row[0] if row else None})
    if row is None:
        return {"status": "already_queued", "source": source,
                "message": "Já existe uma atualização na fila ou em execução."}
    return {"status": "triggered", "source": source, "job_id": row[0],
            "message": "Job enfileirado. O Worker processa em ~1-2min."}


@router.get("/jobs")
async def control_jobs(
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:data:read")),
):
    """Ultimos jobs de scraping (status pending|running|done|error) p/ a Central
    acompanhar a ingestao."""
    try:
        rows = (await db.execute(text(
            "SELECT id, tipo, status, "
            "to_char(requested_at, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS requested_at, "
            "to_char(started_at,   'YYYY-MM-DD\"T\"HH24:MI:SS') AS started_at, "
            "to_char(finished_at,  'YYYY-MM-DD\"T\"HH24:MI:SS') AS finished_at, "
            "error "
            "FROM scraper_jobs ORDER BY id DESC LIMIT 15"
        ))).mappings().all()
        return {"jobs": [dict(r) for r in rows]}
    except Exception:
        await db.rollback()
        return {"jobs": [], "error": "tabela scraper_jobs indisponível"}


# --- Auditoria (audit_log) — a Central LE o que foi feito nesta instancia ---
def _audit_out(a: AuditLog) -> dict:
    return {
        "id": a.id,
        "user_email": a.user_email,
        "action": a.action,
        "target_type": a.target_type,
        "target_id": a.target_id,
        "ip": a.ip,
        "user_agent": a.user_agent,
        "details": a.details,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@router.get("/audit")
async def control_audit(
    action: str | None = None,
    user_email: str | None = None,
    target_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:audit:read")),
):
    """Eventos do audit_log desta instancia p/ a aba Auditoria da Central. SOMENTE
    LEITURA — o audit_log ja e gravado por varias acoes (login, cofre, user, etc.),
    aqui so lemos. Filtros opcionais: action (prefixo), user_email (substring),
    target_type (exato). Ordena por id DESC (mais recentes primeiro). Sem escopo novo:
    o control token e control:* — control:audit:read ja passa."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    stmt = select(AuditLog)
    if action and action.strip():
        stmt = stmt.where(AuditLog.action.ilike(action.strip() + "%"))
    if user_email and user_email.strip():
        stmt = stmt.where(AuditLog.user_email.ilike("%" + user_email.strip() + "%"))
    if target_type and target_type.strip():
        stmt = stmt.where(AuditLog.target_type == target_type.strip())
    stmt = stmt.order_by(AuditLog.id.desc()).limit(limit).offset(offset)
    try:
        rows = (await db.execute(stmt)).scalars().all()
    except Exception:
        await db.rollback()
        return []
    return [_audit_out(a) for a in rows]


# --- Cofre de credenciais (gerido pela Central; o scraper le localmente) ---
class CofreIn(BaseModel):
    municipio_ibge: str | None = None       # escopo (opcional; None = instancia)
    sistema: str
    url: str | None = None
    usuario: str | None = None
    senha: str | None = None                # texto claro -> cifrado no tenant
    automation_key: str | None = None       # ex: fns, govbr, simec...
    categoria: str | None = None
    observacao: str | None = None


class CofrePatch(BaseModel):
    municipio_ibge: str | None = None
    sistema: str | None = None
    url: str | None = None
    usuario: str | None = None
    senha: str | None = None
    automation_key: str | None = None
    categoria: str | None = None
    observacao: str | None = None


async def _mun_id_by_ibge(db, ibge: str | None):
    if not ibge:
        return None
    return (await db.execute(select(Municipio.id).where(Municipio.ibge_code == ibge))).scalar_one_or_none()


async def _ibge_by_mun_id(db, mid):
    if not mid:
        return None
    return (await db.execute(select(Municipio.ibge_code).where(Municipio.id == mid))).scalar_one_or_none()


def _cofre_mask(clear: str) -> str:
    if not clear:
        return ""
    s = clear.strip()
    if s.startswith("{") and '"cookies"' in s:   # blob de sessao capturada (extensao)
        return "[sessão capturada]"
    n = len(clear)
    return "*" * n if n <= 4 else clear[0] + "*" * (n - 2) + clear[-1]


async def _cofre_out(db, it: CofreSenha) -> dict:
    clear = crypto.decrypt(it.senha_encrypted) if it.senha_encrypted else ""
    return {
        "id": it.id,
        "municipio_ibge": await _ibge_by_mun_id(db, it.municipio_id),
        "sistema": it.sistema, "url": it.url, "usuario": it.usuario,
        "senha_mascarada": _cofre_mask(clear), "tem_senha": bool(it.senha_encrypted),
        "automation_key": it.automation_key, "categoria": it.categoria,
        "observacao": it.observacao,
        "updated_at": it.updated_at.isoformat() if it.updated_at else None,
    }


@router.get("/cofre")
async def list_cofre(
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:cofre:read")),
):
    rows = (await db.execute(
        select(CofreSenha).order_by(CofreSenha.categoria, CofreSenha.sistema))).scalars().all()
    return [await _cofre_out(db, i) for i in rows]


@router.post("/cofre")
async def create_cofre(
    body: CofreIn, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:cofre:write")),
):
    sistema = (body.sistema or "").strip()
    if not sistema:
        raise HTTPException(status_code=400, detail="sistema obrigatório")
    mun_id = await _mun_id_by_ibge(db, body.municipio_ibge)
    if body.municipio_ibge and mun_id is None:
        raise HTTPException(status_code=400, detail="município (ibge) não encontrado")
    it = CofreSenha(
        municipio_id=mun_id, sistema=sistema, url=body.url, usuario=body.usuario,
        senha_encrypted=crypto.encrypt(body.senha) if body.senha else None,
        automation_key=(body.automation_key or None), categoria=body.categoria,
        observacao=body.observacao,
    )
    db.add(it)
    await db.commit()
    await db.refresh(it)
    await registrar(db, action="control.cofre.create", request=request,
                    user_email=_ator(request, p), municipio_id=it.municipio_id,
                    target_type="cofre_senha", target_id=it.id, alvo_nome=sistema,
                    details={"sistema": sistema, "integracao": p.name,
                             "automation_key": it.automation_key})
    return await _cofre_out(db, it)


@router.patch("/cofre/{item_id}")
async def patch_cofre(
    item_id: int, body: CofrePatch, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:cofre:write")),
):
    it = await db.get(CofreSenha, item_id)
    if not it:
        raise HTTPException(status_code=404, detail="entrada não encontrada")
    fields = body.model_dump(exclude_unset=True)
    if "municipio_ibge" in fields:
        ibge = fields.pop("municipio_ibge")
        mid = await _mun_id_by_ibge(db, ibge) if ibge else None
        if ibge and mid is None:   # nao rebaixa p/ escopo geral por typo de IBGE
            raise HTTPException(status_code=400, detail="município (ibge) não encontrado")
        it.municipio_id = mid
    if "senha" in fields:                       # so re-cifra se veio senha
        senha = fields.pop("senha")
        it.senha_encrypted = crypto.encrypt(senha) if senha else None
    for k, v in fields.items():
        setattr(it, k, v)
    await db.commit()
    await db.refresh(it)
    await registrar(db, action="control.cofre.patch", request=request,
                    user_email=_ator(request, p), municipio_id=it.municipio_id,
                    target_type="cofre_senha", target_id=it.id,
                    alvo_nome=it.sistema,
                    # Quais campos foram tocados (NUNCA o valor: da senha fica so
                    # a marca de que houve troca). `exclude_unset` ja separa
                    # "mandou vazio" de "nem mandou". `senha_changed` e o nome
                    # exato que o sanitizador do audit reconhece como METRICA e
                    # deixa passar — qualquer outro nome com "senha" viraria
                    # "[oculto]" e a marca se perderia.
                    details={"sistema": it.sistema, "integracao": p.name,
                             "campos": sorted(body.model_dump(exclude_unset=True).keys()),
                             "senha_changed": "senha" in body.model_fields_set})
    return await _cofre_out(db, it)


@router.get("/cofre/{item_id}/reveal")
async def reveal_cofre(
    item_id: int, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:cofre:read")),
):
    it = await db.get(CofreSenha, item_id)
    if not it:
        raise HTTPException(status_code=404, detail="entrada não encontrada")
    # Registro ANTES da revelacao: se a trilha nao gravar, a senha nao sai. Nos
    # outros endpoints deste arquivo falhar o registro depois do commit so
    # mentiria sobre um ato ja consumado; neste, falhar de proposito EVITA a
    # divulgacao — a unica ordem em que "critico" e honesto. Revelar credencial
    # de prefeitura sem deixar quem e quando e o pior evento desta superficie.
    # (`services/audit.py` ja promoveria `*.reveal` a critico mesmo por
    # `registrar`; a chamada explicita aqui e para nao depender disso.)
    await registrar_critico(db, action="control.cofre.reveal", request=request,
                            user_email=_ator(request, p), municipio_id=it.municipio_id,
                            target_type="cofre_senha", target_id=it.id,
                            alvo_nome=it.sistema,
                            # `it.usuario` (o LOGIN do portal) fica de fora: no
                            # gov.br ele E o CPF de um servidor. A trilha nao se
                            # apaga por 5 anos e sai do sistema em PDF/Excel —
                            # copiar o CPF para ca multiplicaria dado pessoal
                            # sem responder nada que `sistema` + `target_id` +
                            # `automation_key` ja nao respondam (qual entrada do
                            # cofre foi exposta). E o mesmo recorte que o reveal
                            # do lado do cliente ja usa (routers/cofre.py):
                            # dois eventos do MESMO ato guardando conjuntos
                            # diferentes de dado pessoal seria incoerencia
                            # dificil de defender numa auditoria de LGPD.
                            details={"sistema": it.sistema,
                                     "automation_key": it.automation_key, "integracao": p.name})
    return {"senha": crypto.decrypt(it.senha_encrypted) if it.senha_encrypted else ""}


@router.delete("/cofre/{item_id}")
async def delete_cofre(
    item_id: int, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:cofre:write")),
):
    it = await db.get(CofreSenha, item_id)
    if not it:
        raise HTTPException(status_code=404, detail="entrada não encontrada")
    sistema = it.sistema
    mun_id = it.municipio_id       # some junto com a linha; copiado antes do delete
    await db.delete(it)
    await db.commit()
    await registrar(db, action="control.cofre.delete", request=request,
                    user_email=_ator(request, p), municipio_id=mun_id,
                    target_type="cofre_senha", target_id=item_id, alvo_nome=sistema,
                    details={"sistema": sistema, "integracao": p.name})
    return {"status": "deleted"}


# --- Sessao gov.br + token da extensao de captura ---
@router.get("/session/status")
async def control_session_status(
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:session:read")),
):
    """Status REAL da sessao gov.br capturada (do Cofre): valida/expirada + minutos
    restantes (decodifica o exp do JWT user-id). Insumo p/ FNS/TransfereGov. A captura
    em si e manual (extensao) — o Console so monitora."""
    row = (await db.execute(text("""
        -- ⚠️ `municipio_id IS NULL`: mesmo recorte de `govbr_renew._load_govbr`
        -- e do keepalive. Este endpoint responde "a sessao esta viva?" — se ele
        -- olhar uma linha diferente da que o renovador usa, passa a responder
        -- sobre outra sessao, e o Console fica dizendo que esta tudo bem sobre
        -- uma credencial que ninguem usa. Um monitor que observa o objeto errado
        -- e pior que monitor nenhum, porque cala a suspeita.
        SELECT id, municipio_id, updated_at, observacao, senha_hash
        FROM cofre_senhas
        WHERE automation_key='govbr' AND length(senha_hash) > 1000
          AND municipio_id IS NULL
        ORDER BY updated_at DESC LIMIT 1
    """))).first()
    if not row:
        return {"has_session": False, "message": "Nenhuma sessao gov.br capturada"}
    age_h = (datetime.now(timezone.utc) - row[2]).total_seconds() / 3600 if row[2] else None
    base: dict = {"has_session": True, "municipio_id": row[1],
                  "updated_at": row[2].isoformat() if row[2] else None,
                  "age_hours": round(age_h, 2) if age_h is not None else None,
                  "observacao": row[3]}
    try:
        data = _json.loads(crypto.decrypt(row[4]) or "")
        uid = next((c for c in data.get("cookies", []) if c.get("name") == "user-id"), None)
        if uid:
            parts = (uid.get("value") or "").split(".")
            if len(parts) >= 2:
                pb = parts[1] + "=" * (-len(parts[1]) % 4)
                payload = _json.loads(base64.urlsafe_b64decode(pb))
                exp_ts = payload.get("exp")
                if exp_ts:
                    mins = (exp_ts - datetime.now(timezone.utc).timestamp()) / 60
                    base["exp_minutes"] = round(mins, 1)
                    base["expired"] = mins <= 0
                    base["expira_em"] = datetime.fromtimestamp(exp_ts, tz=timezone.utc).isoformat()
                    return base
    except Exception as e:
        base["decode_error"] = str(e)[:80]
    base["expired"] = (age_h or 1) > 0.33   # fallback pela idade da captura (~20min)
    return base


@router.post("/session/token")
async def control_session_token(
    request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:session:write")),
):
    """Emite (ou rotaciona) o service token da EXTENSAO de captura (scope session:write,
    kind scraper). Mostrado UMA vez; o operador configura na extensao do navegador."""
    name = "extensao-captura"
    raw = "pactha_st_" + pysecrets.token_urlsafe(40)
    existing = (await db.execute(
        select(ServiceToken).where(ServiceToken.name == name))).scalar_one_or_none()
    if existing:
        existing.token_hash = hash_token(raw)
        existing.token_prefix = raw[:12]
        existing.scopes = ["session:write"]
        existing.kind = "scraper"
        existing.active = True
        existing.last_used_at = None
        existing.last_used_ip = None
        tok, action = existing, "control.session_token.rotate"
    else:
        tok = ServiceToken(name=name, token_hash=hash_token(raw), token_prefix=raw[:12],
                           scopes=["session:write"], kind="scraper", active=True)
        db.add(tok)
        action = "control.session_token.create"
    await db.commit()
    await db.refresh(tok)
    await registrar(db, action=action, request=request, user_email=_ator(request, p),
                    target_type="service_token", target_id=tok.id, alvo_nome=name,
                    details={"name": name, "integracao": p.name, "prefix": tok.token_prefix})
    return {"token": raw, "name": name, "scopes": ["session:write"], "prefix": tok.token_prefix,
            "warning": "Anote agora — não será mostrado de novo. Configure na extensão de captura."}


# --- SSO tecnico: a Central pede uma sessao de suporte p/ um tecnico Alavank ---
class SsoIn(BaseModel):
    tech_email: str
    tech_name: str | None = None


@router.post("/sso")
async def control_sso(
    body: SsoIn, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:sso:write")),
):
    """Cria/atualiza um usuario de SUPORTE (Alavank) e devolve um token de uso unico
    (2 min) que o aceitador /api/auth/sso-login troca por uma sessao. A senha do
    tecnico nunca sai da Central — o usuario local so serve p/ carregar a sessao."""
    email = (body.tech_email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="email inválido")
    # Email NAMESPACED: nunca colide com um usuario real do tenant. Antes, casar pelo
    # email cru permitia sequestrar (e reativar) a conta de um usuario legitimo que
    # tivesse o mesmo email. O prefixo "alavank-sso." garante identidade de suporte
    # separada e estavel (o mesmo tecnico reusa sempre o mesmo usuario de suporte).
    local, _, domain = email.partition("@")
    support_email = f"alavank-sso.{local}@{domain}"
    u = (await db.execute(select(User).where(User.email == support_email))).scalar_one_or_none()
    if u is None:
        u = User(email=support_email, name=("[Suporte Alavank] " + (body.tech_name or email))[:200],
                 password_hash=hash_password(pysecrets.token_urlsafe(24)),
                 role="admin", active=True, must_change_password=False)
        db.add(u)
        await db.commit()
        await db.refresh(u)
    elif not u.active:
        u.active = True
        await db.commit()
    # ⚠️ O ESCOPO DO SUPORTE, ESCRITO — e não herdado do papel.
    #
    # Esta conta nascia só com `role="admin"`, e isso bastava: `load_user_scopes`
    # zerava os dois limites de todo admin. Não zera mais (o papel virou rótulo),
    # e a conta de suporte NÃO é super-admin — o e-mail é `alavank-sso.<local>@…`,
    # que não está em `SUPER_ADMIN_EMAILS` nem foi semeado na coluna. Sem estas
    # duas concessões, o técnico da Alavank entraria pelo SSO num tenant e veria
    # menu vazio e 403 em tudo: o backfill da migration só alcançou as contas de
    # suporte que JÁ EXISTIAM no dia do deploy, e cada técnico novo (ou cada
    # tenant novo) cria a sua depois.
    #
    # A CADA emissão, e não só na criação: é o mesmo motivo de `_ensure_kiosk_user`
    # reescrever o escopo do quiosque — conta sintética não tem dono humano para
    # ajustar permissão, então nada aqui desfaz decisão de ninguém. E é o que
    # cura sozinho o município cadastrado DEPOIS da última sessão de suporte.
    #
    # Não vira `super_admin = TRUE` de propósito: isso daria ao suporte mais do
    # que ele tinha ontem (Sessões, Service Tokens, poder sobre as contas donas).
    # Aqui só se repõe, como dado, o que o papel concedia por desvio.
    for _tela in TELAS_TODAS:
        await db.execute(text(
            "INSERT INTO user_telas (user_id, tela) VALUES (:u, :t) ON CONFLICT DO NOTHING"
        ), {"u": u.id, "t": _tela})
    await db.execute(text(
        "INSERT INTO user_municipios (user_id, municipio_id) "
        "SELECT :u, id FROM municipios ON CONFLICT DO NOTHING"
    ), {"u": u.id})
    await db.commit()
    token = create_sso_token(u.id)
    # Aqui o proprio corpo diz quem e o tecnico que vai entrar no sistema do
    # cliente — melhor identificacao que qualquer cabecalho. Se o Console mandar
    # o ator, ele vence (pode ser um coordenador abrindo sessao para outro); o
    # e-mail do tecnico fica sempre em `details` para os dois casos casarem.
    ator = _ator(request, p)
    await registrar(db, action="control.sso.mint", request=request,
                    # Mesmo prefixo de `_ator` no fallback: o e-mail do corpo
                    # tambem e afirmacao de quem tem o token, e um ato do canal
                    # externo nao pode aparecer no filtro como login local.
                    user_email=(ator if "@" in ator else f"control:{email}"[:255]),
                    target_type="user", target_id=email,
                    alvo_nome=(body.tech_name or email),
                    details={"tech": email, "tech_nome": body.tech_name,
                             "usuario_suporte": support_email, "integracao": p.name})
    return {"sso_token": token, "path": "/api/auth/sso-login"}


# --- Usuarios do cliente (users do tenant), geridos pela Central via canal ---
class ControlUserIn(BaseModel):
    email: str
    name: str
    role: str = "analyst"                  # default analyst (nao admin/"deus")
    telas: list[str] | None = None         # keys de telas/modulos
    municipios: list[str] | None = None    # ibge_codes do escopo


class ControlUserPatch(BaseModel):
    name: str | None = None
    role: str | None = None
    active: bool | None = None
    telas: list[str] | None = None
    municipios: list[str] | None = None


async def _user_out(db, u: User) -> dict:
    _ll = getattr(u, "last_login_at", None)
    _cr = getattr(u, "created_at", None)
    return {
        "email": u.email, "name": u.name, "role": u.role, "active": bool(u.active),
        "must_change_password": bool(u.must_change_password),
        "last_login_at": _ll.isoformat() if _ll else None,
        "created_at": _cr.isoformat() if _cr else None,
        "telas": await users_admin.get_user_telas(db, u.id),
        "municipios": await users_admin.get_user_ibges(db, u.id),
    }


async def _active_admin_count(db) -> int:
    # Exclui usuarios de SUPORTE da Alavank (alavank-sso.*): a senha deles nunca sai da
    # Central (o cliente nao autentica como eles), entao NAO contam como "o cliente ainda
    # tem admin". Sem isso, a trava de "unico admin" (do PATCH e do DELETE) era burlavel.
    return (await db.execute(text(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = true "
        "AND email NOT LIKE 'alavank-sso.%'"))).scalar() or 0


@router.get("/telas-catalog")
async def telas_catalog(p: ControlPrincipal = Depends(require_control_scope("control:users:read"))):
    return {"telas": TELAS_CATALOG}


@router.get("/users")
async def list_control_users(
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:users:read")),
):
    rows = (await db.execute(select(User).order_by(User.name))).scalars().all()
    return [await _user_out(db, u) for u in rows]


@router.post("/users")
async def create_control_user(
    body: ControlUserIn, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:users:write")),
):
    email = (body.email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Email inválido")
    if body.role not in users_admin.ROLES:
        raise HTTPException(status_code=400, detail="Role inválida (admin|analyst|user)")
    dup = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=400, detail="Email já cadastrado")
    senha = users_admin.gen_senha()
    u = User(email=email, name=(body.name or "").strip(), password_hash=hash_password(senha),
             role=body.role, active=True, must_change_password=True)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    if body.telas is not None:
        await users_admin.set_user_telas(db, u.id, body.telas)
    if body.municipios is not None:
        await users_admin.set_user_municipios_by_ibge(db, u.id, body.municipios)
    await db.commit()
    await registrar(db, action="control.user.create", request=request,
                    user_email=_ator(request, p),
                    target_type="user", target_id=email, alvo_nome=u.name,
                    details={"role": body.role, "integracao": p.name,
                             "telas": sorted(body.telas or []),
                             "municipios": sorted(body.municipios or [])})
    out = await _user_out(db, u)
    out["senha_temporaria"] = senha
    return out


@router.patch("/users/{email}")
async def patch_control_user(
    email: str, body: ControlUserPatch, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:users:write")),
):
    u = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    if body.role is not None and body.role not in users_admin.ROLES:
        raise HTTPException(status_code=400, detail="Role inválida")
    # Nao deixar o cliente sem NENHUM admin
    demoting = body.role is not None and body.role != "admin" and u.role == "admin"
    deactivating = body.active is False and u.active and u.role == "admin"
    if (demoting or deactivating) and await _active_admin_count(db) <= 1:
        raise HTTPException(status_code=409, detail="Não é possível deixar o cliente sem administrador")

    # Mesmo "antes/depois" do PATCH da tela de usuarios: este canal tambem concede
    # e retira acesso, e ate agora gravava apenas o nome do token — ou seja, que
    # ALGO foi editado, sem dizer o que. Escopo aqui vem por ibge_code (chave
    # estavel do canal), nao por id interno.
    antes = {"name": u.name, "role": u.role, "active": bool(u.active),
             "telas": await users_admin.get_user_telas(db, u.id),
             "municipios": await users_admin.get_user_ibges(db, u.id)}
    if body.name is not None:
        u.name = body.name.strip()
    if body.role is not None:
        u.role = body.role
    if body.active is not None:
        u.active = body.active
    if body.telas is not None:
        await users_admin.set_user_telas(db, u.id, body.telas)
    if body.municipios is not None:
        await users_admin.set_user_municipios_by_ibge(db, u.id, body.municipios)
    await db.commit()
    await db.refresh(u)
    depois = {"name": u.name, "role": u.role, "active": bool(u.active),
              "telas": await users_admin.get_user_telas(db, u.id),
              "municipios": await users_admin.get_user_ibges(db, u.id)}
    permissao = {}
    for campo in ("telas", "municipios"):
        a, d = set(antes[campo]), set(depois[campo])
        if a != d:
            permissao[campo] = {"concedidos": sorted(d - a), "retirados": sorted(a - d)}
    await registrar(db, action="control.user.patch", request=request,
                    user_email=_ator(request, p),
                    target_type="user", target_id=email, alvo_nome=u.name,
                    # Snapshots completos: o audit reduz sozinho ao que mudou.
                    valor_antes=antes, valor_depois=depois,
                    details={"permissao": permissao or None, "integracao": p.name})
    return await _user_out(db, u)


@router.post("/users/{email}/reset-password")
async def reset_control_user_password(
    email: str, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:users:write")),
):
    u = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    senha = users_admin.gen_senha()
    u.password_hash = hash_password(senha)
    u.must_change_password = True
    await db.commit()
    await registrar(db, action="control.user.reset_password", request=request,
                    user_email=_ator(request, p),
                    target_type="user", target_id=email, alvo_nome=u.name,
                    details={"integracao": p.name})
    return {"email": u.email, "senha_temporaria": senha}


@router.delete("/users/{email}")
async def delete_control_user(
    email: str, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:users:write")),
):
    """Remove DEFINITIVAMENTE um usuario do tenant (limpeza de entulho de seed).
    Trava: nao remove o UNICO admin ativo. A trilha fica INTACTA: audit_log nao e
    tocada (nao tem mais FK para users e e append-only desde o Incremento 3) — as
    linhas continuam com user_id, user_email e usuario_nome do instante do ato.
    Zera as FKs sem ON DELETE (cofre_senhas, edital_acompanhamento,
    prestacao_contas/documentos); user_telas/user_municipios/telegram_* somem por
    ON DELETE CASCADE. Falha de forma atomica (rollback)."""
    u = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    # Usuario de SUPORTE da Alavank (alavank-sso.*) nao e removivel por aqui: e sintetico,
    # o SSO o recria, e deletar no meio de uma sessao derruba o tecnico (401). Some so via SSO.
    if (u.email or "").startswith("alavank-sso."):
        raise HTTPException(status_code=409, detail="Usuário de suporte Alavank não é removível por este canal")
    if u.role == "admin" and u.active and await _active_admin_count(db) <= 1:
        raise HTTPException(status_code=409, detail="Não é possível remover o único administrador ativo")
    uid, uname, urole = u.id, u.name, u.role
    # user_telas/user_municipios somem por ON DELETE CASCADE: se nao forem
    # copiados AGORA, "que acessos essa conta tinha quando foi removida" fica sem
    # resposta para sempre. E a pergunta que uma auditoria faz primeiro.
    utelas = await users_admin.get_user_telas(db, uid)
    umuns = await users_admin.get_user_ibges(db, uid)

    # ⭐ A LIMPEZA DE FKs MUDOU DE ENDEREÇO: mora em
    # services/users_admin.py::limpar_fks_do_usuario, compartilhada com o canal
    # do produto (routers/users.py::delete_user, criado em 11/08/2026). As duas
    # listas viviam separadas e divergiram uma vez — as tabelas do Painel
    # chegaram depois desta rotina e ninguem veio somar aqui; o sintoma foi 409
    # sem remedio. A historia toda (audit_log fora da lista de proposito, o que
    # zera vs o que apaga) esta documentada la, num lugar so.
    await users_admin.limpar_fks_do_usuario(db, uid)
    try:
        await db.delete(u)
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=409,
                            detail=f"Não foi possível remover (referências pendentes: {type(e).__name__})")
    await registrar(db, action="control.user.delete", request=request,
                    user_email=_ator(request, p),
                    target_type="user", target_id=email, alvo_nome=uname,
                    details={"name": uname, "role": urole, "integracao": p.name,
                             "telas": utelas, "municipios": umuns})
    return {"status": "deleted", "email": email}


# ⭐ RESUMO DA COLETA — a leitura que um vigia EXTERNO precisa fazer.
#
# Existe porque o watchdog de dentro do worker nao consegue relatar a propria
# morte: se o container cair ou a Scheduled Task nao disparar, ele nao roda e nao
# alerta, e o silencio fica identico a saude. Quem pergunta "voces coletaram
# ontem?" tem de estar FORA — hoje e o resumo diario no GitHub Actions
# (`scripts/resumo_coleta.py`), que chama esta rota nos cinco tenants.
#
# Por que uma rota nova em vez de reusar `/ingestion`:
#
#   1. **`error_message` nao sai por lugar nenhum.** A coluna existe no
#      `ingestion_log` desde sempre (setup_db.py) e nenhuma rota a devolve — ou
#      seja, o PORQUE da falha esta gravado e ninguem le. Era o pedido literal do
#      dono: "detalhar quais deram erro, qual municipio, por que, pra eu ir na
#      fonte e ver o que ta acontecendo".
#   2. **Os achados do watchdog ja estao prontos e presos.** `watchdog_historico`
#      recebe municipio defasado, credencial recusada e processo travado com
#      mensagem em portugues, e so sai por `routers/freshness.py`, que exige
#      permissao de USUARIO — inalcancavel para um chamador de fora.
#   3. **Volume nao e vigiado por ninguem** (lacuna E da auditoria da coleta):
#      nenhuma query do watchdog le `records_*`, oito coletores gravam 'success'
#      na mao, e `simec_par` gravou success com ZERO registros 3x em 24/08 sem
#      ninguem ver. Verde e vazio e indistinguivel de verde e cheio.
#
# ⚠️ A comparacao de volume e SEMPRE da fonte contra ELA MESMA, nunca entre
# fontes: a semantica das contagens e inconsistente de proposito (o sigcon grava
# so `updated`, o cagec conta MUNICIPIOS). Mediana entre fontes seria um numero
# com cara de metrica e sem significado nenhum.
@router.get("/resumo-coleta")
async def control_resumo_coleta(
    horas: int = 24,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:data:read")),
):
    """Tudo que um resumo diario precisa, numa chamada. So leitura.

    Fail-safe por bloco: uma tabela ausente (banco novo, migration atrasada)
    devolve o bloco vazio e uma nota em `erros`, nunca 500 — o resumo tem de sair
    dizendo o que sabe, porque quem le esta longe do servidor."""
    janela = max(1, min(int(horas or 24), 168))
    out: dict = {"instance_slug": os.getenv("INSTANCE_SLUG", ""),
                 "janela_horas": janela, "erros": []}

    async def _q(nome: str, sql: str, params: dict | None = None):
        try:
            return (await db.execute(text(sql), params or {})).mappings().all()
        except Exception as e:
            await db.rollback()
            out["erros"].append(f"{nome}: {str(e)[:120]}")
            return []

    # 1) Quantas rodadas, e como terminaram. ⚠️ O vocabulario de status e
    # inconsistente entre coletores (success/ok, parcial/partial, erro/error/failed)
    # — a auditoria de 29/08 mediu os tres dialetos convivendo no mesmo banco.
    # Normalizar aqui, e nao no leitor, evita que cada consumidor invente o seu.
    out["rodadas"] = [dict(r) for r in await _q("rodadas", """
        SELECT lower(status) AS status, COUNT(*) AS n
        FROM ingestion_log
        WHERE finished_at > NOW() - make_interval(hours => :h)
        GROUP BY lower(status) ORDER BY n DESC
    """, {"h": janela})]

    # 2) A ultima rodada de CADA fonte — com o porque, quando houver.
    # DISTINCT ON e nao "as N ultimas linhas": em hora de coleta intensa a fonte
    # diaria some da janela e parece parada (falso-positivo que ja atrapalhou a
    # auditoria de 17/08 duas vezes).
    out["fontes"] = [dict(r) for r in await _q("fontes", """
        SELECT DISTINCT ON (source)
               source,
               lower(status) AS status,
               records_processed,
               records_inserted + coalesce(records_updated, 0) AS registros,
               to_char(finished_at, 'YYYY-MM-DD"T"HH24:MI:SS') AS finished_at,
               round(EXTRACT(EPOCH FROM (NOW() - finished_at)) / 3600.0, 1) AS horas_desde,
               left(coalesce(error_message, ''), 400) AS error_message
        FROM ingestion_log
        ORDER BY source, id DESC
    """)]

    # 3) O que o watchdog achou na janela: municipio defasado, credencial
    # recusada, processo travado — ja em portugues, com o municipio no `chave`.
    #
    # ⚠️ DEDUPLICADO POR (tipo, chave), e isso nao e cosmetica. O watchdog roda a
    # cada 30 min com cooldown de 180, entao um problema que dura o dia inteiro
    # deixa ~7 linhas identicas: medido no banco do novapalma em 08/09/2026 —
    # `tce_rs_portal` 7x, `transferegov_lote` 7x, `simec_par` 4x, `cauc` 3x, ou
    # seja **21 linhas para 4 problemas**. Um resumo diario com essa repeticao
    # deixa de ser lido na segunda semana, e aí o vigia volta a ser decorativo.
    # A contagem vira INFORMACAO: 7x em 24h diz "persistente", 1x diz "piscou".
    out["achados"] = [dict(r) for r in await _q("achados", """
        SELECT * FROM (
            SELECT DISTINCT ON (tipo, chave)
                   tipo, chave, left(mensagem, 500) AS mensagem,
                   to_char(criado_em, 'YYYY-MM-DD"T"HH24:MI:SS') AS criado_em,
                   COUNT(*) OVER (PARTITION BY tipo, chave) AS repeticoes
            FROM watchdog_historico
            WHERE criado_em > NOW() - make_interval(hours => :h)
            ORDER BY tipo, chave, criado_em DESC
        ) x
        ORDER BY x.repeticoes DESC, x.chave LIMIT 50
    """, {"h": janela})]

    # 4) Queda de volume: ultima rodada boa contra a mediana das 30 anteriores da
    # MESMA fonte. Exige >=5 amostras para nao acusar fonte recem-nascida, e so
    # reporta quem caiu abaixo da metade — o objetivo e pegar o zero silencioso,
    # nao discutir variacao normal.
    out["volume"] = [dict(r) for r in await _q("volume", """
        WITH ranked AS (
            SELECT source, finished_at,
                   records_inserted + coalesce(records_updated, 0) AS n,
                   ROW_NUMBER() OVER (PARTITION BY source ORDER BY id DESC) AS rn
            FROM ingestion_log
            WHERE lower(status) IN ('success', 'ok')
        ),
        -- ⚠️ SO FONTE QUE AINDA RODA. Sem o corte de 72h o aviso de volume
        -- ressuscita COLETOR APOSENTADO: em 09/09/2026 o resumo acusou
        -- `sigcon_full` ("trouxe 0, mediana 518") e `editais_pncp` ("43,
        -- mediana 342") — as duas ultimas rodadas eram de MAIO, 116 dias
        -- antes. Fonte que parou de rodar e problema de FRESCOR, e o watchdog
        -- ja cobra isso; aqui a pergunta e outra: "rodou agora e veio vazia?".
        -- 72h cobre qualquer fonte diaria com folga e mata o defunto.
        ultima AS (SELECT source, n FROM ranked
                    WHERE rn = 1 AND finished_at > NOW() - INTERVAL '72 hours'),
        historico AS (
            SELECT source,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY n) AS mediana,
                   COUNT(*) AS amostras
            FROM ranked WHERE rn BETWEEN 2 AND 31 GROUP BY source
        )
        SELECT u.source, u.n AS ultimo, round(h.mediana) AS mediana, h.amostras
        FROM ultima u JOIN historico h ON h.source = u.source
        WHERE h.amostras >= 5 AND h.mediana > 0 AND u.n < h.mediana * 0.5
        ORDER BY h.mediana - u.n DESC
    """)]

    return out
