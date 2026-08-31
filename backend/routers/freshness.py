"""Monitor de FRESCOR das fontes de dados (admin).

Mostra, por fonte: quando os dados foram atualizados pela ultima vez (max
updated_at da tabela) e quando o coletor rodou pela ultima vez (ingestion_log),
com um status fresco/atrasado/critico. Serve p/ ver rapidamente o que esta
desatualizado e agir (ex.: sessao FNS expirada, credencial SIGCON invalida).
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
from services.auth import get_current_user
from services.registro_rotas import exige
from models.user import User

router = APIRouter(prefix="/api/admin/freshness", tags=["admin"])

# ⚠️ VOCABULARIO DE STATUS DIVERGENTE, e ignorar isso deixa fonte quebrada
# passando por saudavel. Os coletores nao falam a mesma lingua no
# `ingestion_log`: cauc/gconv_es/sismob gravam 'success' (e 'partial'), enquanto
# o cagec_scraper grava 'ok'/'parcial'/'erro'. Este monitor lia
# `max(finished_at)` SEM olhar status nenhum — uma rodada que morreu no meio
# contava como coleta e a linha pintava "Fresco". Foi assim que a Freitas passou
# nove dias com o CAGEC falhando todo dia sem ninguem ver.
_SUCESSO = ("success", "ok")
# ⚠️ 'partial'/'parcial' NAO sao sucesso, e essa distincao e o coracao desta
# tela. O 'parcial' do CAGEC foi criado em 01/08/2026 justamente porque um 'ok'
# com o detalhamento faltando deixou este painel VERDE por um dia inteiro
# enquanto a tela do gestor perdia 28 obrigacoes. Hoje, com o portal do Estado
# recusando emitir CRC, TODA rodada do CAGEC e 'parcial' — trata-la como sucesso
# faria a linha nascer "Fresco" exatamente no estado que ela existe para
# denunciar. Os outros coletores usam 'partial' para rodada incompleta
# (transfvol_go quando gravados != achados, sismob e gconv_es idem): tambem nao
# e sucesso, e tambem merece aparecer.
_DEGRADADO = ("partial", "parcial")

# (rotulo, SQL que retorna (max_timestamp, count), source no ingestion_log)
_SOURCES = [
    # ⚠️ `NOT ILIKE '%FNS%'` sozinho tambem varria as linhas do GConv-ES para
    # dentro da contagem do SIGCON: convenio capixaba aparecia creditado a
    # Minas. Cada fonte conta o que e dela.
    ("FNS — Saúde (federal)",
     "SELECT max(updated_at), count(*) FROM convenios_estadual WHERE fonte ILIKE '%FNS%'",
     "fns"),
    ("SISMOB — Obras da Saúde",
     "SELECT max(updated_at), count(*) FROM sismob_obras WHERE ausente_desde IS NULL",
     "sismob"),
    # Duas fontes no ingestion_log: o run() diario ('transferegov_voluntarias')
    # e o lote horario ('transferegov_lote', quem de fato atualiza as propostas
    # ao longo do dia) — sem o lote aqui, um 'erro'/'parcial' persistente dele
    # ficaria invisivel no monitor.
    ("TransfereGov — Voluntárias",
     "SELECT max(updated_at), count(*) FROM transferegov_propostas",
     ("transferegov_voluntarias", "transferegov_lote")),
    ("TransfereGov — PAC (Novo PAC)",
     "SELECT max(updated_at), count(*) FROM transferegov_pac",
     None),
    # ⚠️ FONTE SEM TABELA PROPRIA, e de proposito. A sessao gov.br nao produz
    # linha em lugar nenhum — ela HABILITA a coleta da fatia atras do login
    # (histórico de comunicações, NEs, projeto básico, licitação). Ate 31/08/2026
    # a saude dela so existia no log do container, que e efemero: "há quantas
    # horas a sessão está viva" era uma pergunta sem resposta no banco, e a
    # auditoria mediu a sessão morta 297,5h de 720h sem que nada no produto
    # dissesse isso.
    #
    # O `records_inserted` de cada linha e QUANTOS DOS TRES SPs responderam
    # (private / execucao / prestacao), e nao um numero de registros — os tres
    # contam separado porque foi exatamente por `execucao` e `prestacao`
    # aparecerem como um so que as NEs morriam em silencio.
    ("gov.br — Sessão das mandatárias",
     "SELECT max(finished_at), count(*) FROM ingestion_log WHERE source = 'govbr_sessao'",
     "govbr_sessao"),
    ("CAUC — Regularidade federal",
     "SELECT max(data_pesquisa)::timestamptz, count(*) FROM cauc_situacao",
     "cauc"),
    ("SIMEC-PAR (MEC)",
     "SELECT max(updated_at), count(*) FROM simec_par_liberacoes",
     "simec_par"),
    # O INSTRUMENTO, nao o pagamento: `simec_par_liberacoes` sao as OBs e
    # `simec_termos` e o Termo de Compromisso (processo, vigencia, valor). Fica
    # na lista FIXA, e nao em _SOURCES_POR_UF, porque o coletor varre todo
    # municipio ativo com ibge_code seja qual for o estado — a UF entra so como
    # parametro do POST. `count(*)` sem filtro de `fonte` porque a tabela e
    # exclusiva deste coletor (a migration nao tem essa coluna), diferente de
    # convenios_estadual e cagec_situacao.
    ("SIMEC — Termos de Compromisso (MEC)",
     "SELECT max(updated_at), count(*) FROM simec_termos",
     "simec_termos"),
]

# ⚠️ FONTES QUE SO EXISTEM PARA CERTAS UFs, e por isso nao podem morar na lista
# fixa acima: numa carteira sem municipio de Goias, uma linha "TCM-GO" eternamente
# vazia seria lida como coletor quebrado. A chave e a UF do TENANT (ha municipio
# daquele estado?), NAO o municipio selecionado no seletor: este monitor e do
# ambiente inteiro e nao recebe `municipio_id`.
#
# ⚠️ E OS ROTULOS DIZEM O QUE CADA UMA E. Só MG tem coletor de CADASTRO ESTADUAL
# (o CAGEC). O que existe de ES e GO e outra coisa — convenio, repasse,
# cofinanciamento e conta julgada irregular. Chamar tudo de "cadastro estadual"
# poria na tela a promessa de uma cobertura de regularidade que nao temos fora
# de Minas, que e exatamente o erro que `lib/estadual.ts` existe para impedir.
_SOURCES_POR_UF: dict[str, list[tuple[str, str, str | None]]] = {
    "MG": [
        # ⚠️ SIGCON e Emendas vieram da lista fixa para ca. Sao tao de Minas
        # quanto o CAGEC — o SIGCON e o sistema de convenios do Estado de MG e as
        # emendas saem do texto do objeto DESSES convenios. Ficavam
        # incondicionais so por inercia: num tenant de GO ou TO as duas linhas
        # apareciam eternamente vazias, que e o mesmo defeito que este bloco
        # existe para evitar.
        ("SIGCON — Convênios estaduais (MG)",
         "SELECT max(updated_at), count(*) FROM convenios_estadual "
         "WHERE (fonte IS NULL OR fonte NOT ILIKE '%FNS%') AND coalesce(fonte,'') NOT ILIKE '%GCONV%'",
         "sigcon_scraper"),
        ("Emendas estaduais (MG)",
         "SELECT max(updated_at), count(*) FROM emendas_estaduais",
         None),
        # ⚠️ FILTRA POR FONTE. Desde que `cagec_situacao` passou a guardar o
        # cadastro estadual de outros estados (CHE-RS), contar a tabela inteira
        # aqui creditaria a Minas linha coletada no Rio Grande do Sul — o mesmo
        # defeito que o `NOT ILIKE '%FNS%'` sozinho causava com o GConv-ES.
        ("CAGEC — Cadastro estadual (MG)",
         "SELECT max(atualizado_em), count(*) FROM cagec_situacao "
         "WHERE coalesce(fonte, 'CAGEC-MG') = 'CAGEC-MG'",
         "cagec"),
        # Programa do Estado de MG (SES-MG). Estava na lista FIXA e por isso
        # aparecia no monitor de um cliente gaucho, que nao tem nada com a
        # divida da saude mineira.
        ("Acordo FES — Dívida saúde (MG)",
         "SELECT NULL::timestamptz, count(*) FROM acordofes_credor",
         "acordofes"),
    ],
    "RS": [
        ("CHE — Cadastro estadual (RS)",
         "SELECT max(atualizado_em), count(*) FROM cagec_situacao "
         "WHERE fonte = 'CHE-RS'",
         "che_rs"),
        ("Convênios do Estado (RS)",
         "SELECT max(updated_at), count(*) FROM convenios_estadual "
         "WHERE fonte = 'CAGE-RS'",
         "convenios_rs"),
        ("Consulta Popular / COREDEs (RS)",
         "SELECT max(atualizado_em), count(*) FROM consulta_popular_rs",
         "consulta_popular_rs"),
    ],
    "ES": [
        ("GConv-ES — Convênios estaduais (ES)",
         "SELECT max(updated_at), count(*) FROM convenios_estadual WHERE fonte ILIKE '%GCONV%'",
         "gconv_es"),
    ],
    "GO": [
        ("TransfVol-GO — Repasses estaduais (GO)",
         "SELECT max(updated_at), count(*) FROM repasses_estaduais",
         "transfvol_go"),
        ("SES-GO — Cofinanciamento da saúde (GO)",
         "SELECT max(updated_at), count(*) FROM cofinanciamento_saude",
         "cofin_ses_go"),
        ("TCM-GO — Contas irregulares (GO)",
         "SELECT max(updated_at), count(*) FROM contas_irregulares",
         "tcm_go"),
    ],
}


async def _ufs_do_tenant(db: AsyncSession) -> set[str]:
    """UFs com municipio ativo. Vazio em caso de erro — melhor a lista curta de
    sempre do que uma tela de monitor que nao abre."""
    try:
        r = await db.execute(text(
            "SELECT DISTINCT upper(coalesce(uf, '')) FROM municipios WHERE active"))
        return {x[0] for x in r.fetchall() if x[0]}
    except Exception:
        return set()


def _status(age_days: float | None) -> str:
    if age_days is None:
        return "desconhecido"
    if age_days <= 2:
        return "fresco"
    if age_days <= 7:
        return "atrasado"
    return "critico"


# `frescor.ver` — a chave do catalogo para este monitor ("Monitor de frescor dos
# dados"); o caminho e que ficou com o nome em ingles. A checagem de `role` logo
# abaixo continua valendo e nega SEMPRE, nos dois modos: a permissao e um
# segundo filtro, nao a substituicao dela.
@router.get("", dependencies=[exige("frescor.ver")])
async def freshness(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if current.role != "admin":
        raise HTTPException(403, "Apenas administradores acessam o monitor de frescor")
    now = datetime.now(timezone.utc)
    # Ultima execucao BEM-SUCEDIDA por coletor, e — separadamente — a ultima
    # TENTATIVA com o status dela. Sao coisas diferentes e a tela precisa das
    # duas: fonte que roda de hora em hora e falha ha tres dias tem tentativa
    # recente e sucesso velho, e so a segunda coluna denuncia isso.
    runs: dict[str, datetime] = {}
    tentativas: dict[str, tuple[datetime, str]] = {}
    try:
        r = await db.execute(
            text("SELECT source, max(finished_at) FROM ingestion_log "
                 "WHERE lower(coalesce(status, '')) = ANY(:ok) GROUP BY source"),
            {"ok": list(_SUCESSO)})
        for src, ts in r.fetchall():
            if ts:
                runs[src] = ts
    except Exception:
        pass
    try:
        r = await db.execute(text(
            "SELECT DISTINCT ON (source) source, finished_at, coalesce(status, '?') "
            "FROM ingestion_log WHERE finished_at IS NOT NULL "
            "ORDER BY source, finished_at DESC"))
        for src, ts, st in r.fetchall():
            if ts:
                tentativas[src] = (ts, st)
    except Exception:
        pass

    ufs = await _ufs_do_tenant(db)
    fontes = list(_SOURCES)
    for uf, extras in _SOURCES_POR_UF.items():
        if uf in ufs:
            fontes.extend(extras)

    out = []
    for label, sql, src in fontes:
        last_data = None
        count = None
        try:
            row = (await db.execute(text(sql))).first()
            if row:
                last_data, count = row[0], row[1]
        except Exception:
            pass
        # src pode ser uma string ou uma TUPLA de fontes do ingestion_log (ex.:
        # TransfereGov = run diario + lote horario). Sucesso = o mais recente
        # entre elas; tentativa = a mais recente (e o status dela).
        _srcs = src if isinstance(src, (tuple, list)) else ((src,) if src else ())
        last_run = max((runs[s] for s in _srcs if s in runs), default=None)
        _tents = [tentativas[s] for s in _srcs if s in tentativas]
        tent = max(_tents, key=lambda t: t[0]) if _tents else None
        # frescor = mais recente entre dado gravado e execucao BEM-SUCEDIDA.
        # A tentativa que falhou de proposito NAO entra: era ela que fazia uma
        # fonte morta aparecer verde.
        cands = [t for t in (last_data, last_run) if t is not None]
        last = max(cands) if cands else None
        age_days = ((now - last).total_seconds() / 86400.0) if last else None
        # ⚠️ A SAUDE VEM DO STATUS DA ULTIMA TENTATIVA, nao de comparar
        # carimbos. Comparar `tent[0] > last_run` exigia um sucesso ANTERIOR:
        # fonte que NUNCA deu certo — o pior caso — ficava de fora do sinal e
        # caia no otimismo do `_status(age_days)`.
        st = (tent[1] or "").lower() if tent else ""
        degradada = st in _DEGRADADO
        falhando = bool(tent and st not in _SUCESSO)
        out.append({
            "fonte": label,
            "ultimo_dado": last_data.isoformat() if last_data else None,
            "ultima_coleta": last_run.isoformat() if last_run else None,
            "referencia": last.isoformat() if last else None,
            "idade_dias": round(age_days, 1) if age_days is not None else None,
            "registros": count,
            # A ultima tentativa e o status cru dela — e o que distingue "ninguem
            # tentou" de "tentou e quebrou", indistinguiveis ate agora.
            "ultima_tentativa": tent[0].isoformat() if tent else None,
            "ultimo_status": tent[1] if tent else None,
            "falhando": falhando,
            "degradada": degradada,
            # Rodada degradada nao e "critico" (a fonte respondeu, so veio
            # incompleta) mas tambem nao pode ficar verde.
            "status": ("atrasado" if degradada else "critico") if falhando
                      else _status(age_days),
        })
    # ordena piores primeiro
    ordem = {"critico": 0, "desconhecido": 1, "atrasado": 2, "fresco": 3}
    out.sort(key=lambda x: (ordem.get(x["status"], 9), -(x["idade_dias"] or 0)))

    # ⭐ OS AVISOS DO VIGIA, NA TELA — porque ate 11/08/2026 eles nao tinham
    # para onde ir: o watchdog detectava, escrevia a frase certa e terminava em
    # "(Telegram nao configurado -- alerta so no log)". Com o Telegram desligado
    # por decisao do dono e o WhatsApp ainda por fazer, ESTA e a entrega que nao
    # depende de credencial nenhuma: quem abre Status dos Dados ve o que o
    # sistema tentou contar. (O webhook opcional continua existindo para quem
    # quiser receber fora — ver watchdog_coleta.py::_alerta.)
    avisos: list[dict] = []
    try:
        linhas = (await db.execute(text(
            "SELECT tipo, chave, mensagem, criado_em FROM watchdog_historico "
            "WHERE criado_em > NOW() - INTERVAL '7 days' "
            "ORDER BY criado_em DESC LIMIT 20"))).fetchall()
        avisos = [{"tipo": r[0], "chave": r[1], "mensagem": r[2],
                   "em": r[3].isoformat() if r[3] else None} for r in linhas]
    except Exception:
        # Tabela ainda nao migrada (a API sobe antes do boot que roda o SQL):
        # a tela continua inteira, so sem a lista.
        await db.rollback()
    return {"gerado_em": now.isoformat(), "fontes": out, "avisos": avisos}
