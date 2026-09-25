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
    # ⚠️ ENTROU AQUI NO MESMO COMMIT DO COLETOR, e não depois. Fonte que coleta
    # sem aparecer no monitor é fonte que pode parar por meses sem ninguém ver —
    # foi assim que `siconv_federal` ficou zerado em dois tenants. Federal, então
    # vale para os cinco: fica na lista FIXA, e não numa das listas por UF.
    ("FNS — Fundo a fundo (saúde)",
     "SELECT max(updated_at), count(*) FROM fns_repasse_faf",
     "fns_faf"),
    # ⚠️ A DATA É A DO SALDO (`dt_saldo`), NÃO A DA RODADA: o Portal FNS publica o
    # arquivo uma vez por ano (o de 2025 saiu em 16/01/2026 com saldo de
    # 30/11/2025). A rodada diária carimbaria "hoje" num número de meses atrás.
    ("FNS — Saldo das contas do Fundo Municipal (arquivo anual)",
     "SELECT max(dt_saldo)::timestamptz, count(*) FROM fns_saldo_conta",
     "fns_saldo"),
    # ⚠️ CONTA SÓ OS QUE ESTÃO NO AR. O radar guarda o programa que saiu de
    # cartaz (marcado com `ausente_desde`, e não apagado); somá-los aqui faria o
    # monitor crescer para sempre e nunca acusar um radar que parou de achar
    # programa aberto — que é justamente o defeito a vigiar.
    ("TransfereGov — Radar de captação",
     "SELECT max(visto_em), count(*) FROM programas_captacao "
     "WHERE ausente_desde IS NULL",
     "programas_captacao"),
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
    # ⚠️ ERA A LACUNA QUE O COMENTARIO LA EM CIMA JA DENUNCIAVA: `siconv_federal`
    # tinha coletor, tinha `source` proprio no ingestion_log, e nao aparecia
    # aqui — corrigido em 06/09/2026 junto com a migracao das APIs novas do
    # TransfereGov. NACIONAL (base SICONV do Brasil inteiro, casada por CNPJ,
    # sem `municipio_id`): fica na lista FIXA.
    ("TransfereGov — SICONV federal (por CNPJ)",
     "SELECT max(atualizado_em), count(*) FROM siconv_federal",
     "siconv_federal"),
    # Transferencia Especial / Emenda PIX. Ficava fora do monitor desde que o
    # coletor foi criado — mesmo defeito do item acima, mesmo commit de
    # correcao. NACIONAL: a carteira entra pelo CNPJ do municipio, sem recorte
    # de estado, entao fica na lista FIXA como as demais fontes federais desta
    # secao. Desde 14/09/2026 e tambem a primeira com `fonte_atualizada_em`.
    ("TransfereGov — Transferências Especiais (Emenda Pix)",
     "SELECT max(updated_at), count(*) FROM transferegov_te",
     "transferegov_te"),
    # ⭐ ENTROU AQUI NO MESMO COMMIT DO COLETOR, que e a regra escrita la em
    # cima e que ja custou nove dias de CAGEC quebrado sem ninguem ver.
    # NACIONAL: a Gestao de Parcerias existe nos cinco tenants, e o recorte e
    # por `cd_ibge_recebedor` — nao ha UF envolvida.
    #
    # ⚠️ CONTAGEM ZERO E ESTADO LEGITIMO aqui, mais do que nas outras fontes: o
    # modulo so tem instrumento de 2024 em diante, entao municipio sem parceria
    # recente aparece zerado sem que nada esteja quebrado. O veredito e o
    # `status` da rodada.
    ("TransfereGov — Gestão de Parcerias",
     "SELECT max(atualizado_em), count(*) FROM parcerias_propostas",
     "parcerias"),
    # ⭐ FUNDO A FUNDO: o outro lado do ConsultaFNS. O `fns_faf` conta o
    # repasse que ENTRA; esta conta o PLANO DE ACAO que o justifica, com a
    # decomposicao entre emenda, repasse especifico e voluntario. Nao e so
    # saude: em Nova Palma os quatro planos sao do Ministerio da Cultura.
    #
    # ⚠️ Contagem zero e estado legitimo — municipio sem plano fundo a fundo
    # existe. O veredito e o `status` da rodada.
    ("TransfereGov — Fundo a Fundo (planos de ação)",
     "SELECT max(atualizado_em), count(*) FROM faf_planos_acao",
     "faf_planos"),
    # ⭐ VOLUNTARIAS — A ARVORE PELOS DUMPS (15/09/2026). Execucao financeira,
    # aditivos, plano de trabalho, obras e prestacao de contas de cada proposta,
    # dos zips de Discricionarias — o que antes vinha da raspagem atras da
    # sessao gov.br. A contagem e de propostas COM arvore; `ultimo_dado` e a
    # ultima arvore que MUDOU (o coletor so regrava o que mudou), e a data da
    # propria fonte vem da `data_carga_siconv` (`_FONTE_ATUALIZACAO`).
    ("TransfereGov — Voluntárias: execução e prazos (dump)",
     "SELECT max(arvore_atualizado_em), count(arvore) FROM transferegov_propostas",
     "transferegov_arvore"),
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
    # SICONFI/Tesouro. NACIONAL, como o SIMEC-Termos: o coletor varre todo
    # municipio ativo com ibge_code, sem recorte de estado. Conta as ENTREGAS
    # (uma linha por entregavel x periodo) e nao a CAPAG, porque a CAPAG e uma
    # linha por municipio/ano e ficaria eternamente parecendo pouco — as duas
    # saem da mesma rodada e do mesmo `source`, entao a data e a mesma.
    ("SICONFI — Contas no Tesouro",
     "SELECT max(atualizado_em), count(*) FROM siconfi_entregas",
     "siconfi"),
    # DOU federal (22/09/2026). NACIONAL: todo municipio ativo com ibge_code. A
    # data e a da COBERTURA (ultima busca feita inteira), nao a do ato: semana
    # sem nada no DOU sobre o municipio e resultado, e nao coleta parada. Conta
    # as citacoes, sem as de `cidade` (endereco), que a tela esconde.
    # CGU / Portal da Transparência (23/09/2026). NACIONAL (casa pelo CNPJ da
    # prefeitura). A data é a da CARGA: a planilha da CGU não é diária (a de 11/09
    # ainda era a mais nova em 22/09), e a rodada que acha o mesmo arquivo grava
    # `success` sem regravar — o frescor da fonte é o `arquivo` na tela.
    ("CGU — Convênios fora do TransfereGov (Defesa Civil)",
     "SELECT (SELECT max(carregado_em) FROM cgu_convenios_carga), "
     "(SELECT count(*) FROM cgu_convenios)",
     "cgu_convenios"),
    # Recursos recebidos por pasta (24/09/2026). NACIONAL (código SIAFI do
    # município + CNPJ). A data é a da CARGA do mês mais recente; o mês corrente
    # é parcial por natureza (a tela diz isso), não é coleta parada.
    ("CGU — Recursos recebidos por pasta (transferências)",
     "SELECT (SELECT max(carregado_em) FROM cgu_transferencias_carga), "
     "(SELECT count(*) FROM cgu_transferencias)",
     "cgu_transferencias"),
    ("DOU — Diário Oficial da União",
     "SELECT (SELECT max(atualizado_em) FROM dou_cobertura), "
     "(SELECT count(*) FROM dou_atos_municipio WHERE evidencia <> 'cidade')",
     "dou_federal"),
    # Obras.gov.br/CIPI. NACIONAL: varre por UF da carteira e casa por CNPJ do
    # tomador. ⚠️ Contagem ZERO e estado legitimo (municipio sem obra federal
    # cadastrada) — o veredito e o `status` da rodada, que sai `partial` quando
    # a varredura foi interrompida por rate limit.
    ("Obras.gov.br — Obras federais",
     "SELECT max(atualizado_em), count(*) FROM obrasgov_projetos",
     "obrasgov"),
    # Emendas parlamentares FEDERAIS (carteira do dump SICONV + execucao da CGU).
    # ⚠️ ENTROU NO MESMO COMMIT DO COLETOR, e não depois — a regra escrita lá em
    # cima, que custou nove dias de CAGEC quebrado sem ninguém ver.
    # NACIONAL, então lista FIXA: emenda federal existe nos cinco tenants.
    #
    # ⚠️ CONTA A CARTEIRA, E NÃO A EXECUÇÃO, e a escolha é deliberada.
    # `emendas_federais_carteira` é a única das quatro tabelas que existe SEM a
    # chave da CGU (sai do dump aberto do TransfereGov, casado por CNPJ). Contar
    # `emendas_federais_cgu` faria a linha nascer zerada e parecer coletor
    # quebrado exatamente nos três tenants onde a chave está desligada — que é o
    # estado deliberado de hoje, e não um defeito.
    #
    # ⚠️ E o carimbo é `visto_em`, não uma data de alteração: a emenda de 2011
    # não muda mais, então um `max(atualizado_em)` congelaria e a linha
    # envelheceria sozinha com o coletor rodando todo dia.
    ("Portal da Transparência — Emendas federais",
     "SELECT max(visto_em), count(*) FROM emendas_federais_carteira",
     "portal_transparencia"),
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
        # ⚠️ A DATA É A DA PLANILHA (`execucao_em`), NÃO A DA RODADA: a SEGOV
        # ficou de 12/05 a (pelo menos) 24/09/2026 sem regerar o arquivo, e é
        # isso que a tela precisa mostrar — a rodada diária carimbaria "hoje".
        ("Execução das emendas estaduais — planilha SEGOV (MG)",
         "SELECT max(execucao_em)::timestamptz, count(*) FILTER (WHERE execucao_em IS NOT NULL) "
         "FROM emendas_estaduais",
         "emendas_mg"),
        # Fundo a fundo estadual da saúde (SES-MG, pagamento por Resolução,
        # 24/09/2026). A data é a da última fatia LIDA INTEIRA (`ses_mg_cobertura`):
        # um município sem pagamento no ano não tem linha em `ses_mg_pagamentos`,
        # e ainda assim foi conferido.
        ("SES-MG — Pagamento de Resoluções (fundo a fundo)",
         "SELECT (SELECT max(coletado_em) FROM ses_mg_cobertura), "
         "(SELECT count(*) FROM ses_mg_pagamentos)",
         "ses_mg_resolucoes"),
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
        # Empenhos/pagamentos dos convenios estaduais pelo CSV aberto da SEGOV
        # (15/09/2026): o plano B da Transparencia MG, que da 403 na VPS. Conta
        # so o que casou por SIAFI com um convenio nosso — zero e legitimo em
        # tenant sem convenio estadual com SIAFI.
        ("SEGOV — Empenhos/pagamentos estaduais (MG)",
         "SELECT max(updated_at), count(*) FROM segov_convenios_empenhos",
         "segov_pagamentos"),
        # Data e nº da OB pelos dumps da CGE (15/09/2026): grava na tabela do
        # Joomla com a marca `_fonte` no bloco — conta so as linhas nossas.
        ("CGE — Ordens de pagamento dos convênios (MG)",
         "SELECT max(updated_at), count(*) FROM transparencia_mg_empenhos "
         "WHERE pagamentos->>'_fonte' = 'cge_despesa_ob'",
         "cge_despesa_ob"),
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
        # ⚠️ Esta fonte pode estar BLOQUEADA POR IP (o TCE-RS devolve 403 para
        # faixa de datacenter). Quando esta, o coletor grava `partial` com a
        # nota — entao o monitor mostra "degradado", que e a verdade, e nao
        # "parado" nem "em dia". Conta as licitacoes: os contratos vem da mesma
        # rodada e do mesmo `source`, entao a data e a mesma.
        ("TCE-RS — Licitações e contratos (RS)",
         "SELECT max(atualizado_em), count(*) FROM tce_rs_licitacoes",
         "tce_rs"),
        # ⚠️ MESMAS TABELAS, OUTRO CAMINHO — e por isso esta linha conta as
        # OBRAS, não as licitações: as duas fontes escrevem nas mesmas
        # `tce_rs_licitacoes`/`tce_rs_contratos` (a chave natural do LicitaCon é
        # a mesma pelos dois lados), então contar licitação aqui repetiria o
        # número da linha de cima e as duas pareceriam sempre em dia juntas,
        # mesmo com uma delas parada. `tce_rs_obras` só este coletor preenche.
        #
        # ⚠️ E CONTAGEM ZERO É ESTADO LEGÍTIMO: Nova Palma não tem obra no
        # LicitaCon Obras (sistema de 2024, município de 5,6 mil habitantes),
        # Santa Maria tem 120. O veredito é o `status` da rodada, nunca a
        # contagem — vazio aqui não é coletor quebrado.
        ("TCE-RS — Obras e origem do recurso (RS)",
         "SELECT max(atualizado_em), count(*) FROM tce_rs_obras",
         "tce_rs_portal"),
    ],
    "PR": [
        # ⚠️ A DATA É A DA RODADA, NÃO A DO DADO: `tce_pr_arquivos` só muda quando
        # o TCE regera o zip do ano (semanal no ano corrente). O atraso do próprio
        # dado — o SIM-AM entregue até junho em setembro — está na tela, em
        # `ultimo_envio`, e não é defeito de coleta.
        ("TCE-PR — Convênios, obras, contratos e despesa (PR)",
         "SELECT max(atualizado_em), count(*) FROM tce_pr_arquivos",
         "tce_pr"),
        ("Convênios do Estado (PR)",
         "SELECT max(updated_at), count(*) FROM convenios_estadual "
         "WHERE fonte = 'SIT-PR'",
         "convenios_pr"),
        ("Certidões do Estado — SEFA e TCE-PR (PR)",
         "SELECT max(atualizado_em), count(*) FROM cagec_situacao "
         "WHERE fonte = 'CERTIDOES-PR'",
         "regularidade_pr"),
    ],
    "TO": [
        ("Convênios do Estado — TRANSFERE.TO (TO)",
         "SELECT max(updated_at), count(*) FROM convenios_estadual "
         "WHERE fonte = 'TRANSFERE-TO'",
         "convenios_to"),
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


# ⭐ QUANDO A PROPRIA FONTE SE ATUALIZOU (tabela `fonte_atualizacao`, 14/09/2026).
# E outra coisa que as duas datas acima: `ultimo_dado` e o NOW() do nosso upsert
# e `ultima_coleta` e a hora da nossa rodada — nenhuma das duas percebe uma fonte
# que PAROU DE SE ATUALIZAR, porque o coletor continua rodando e regravando o
# mesmo dado todo dia. As APIs novas do TransfereGov publicam `/data-atualizacao`.
# source do ingestion_log -> chave em `fonte_atualizacao`.
_FONTE_ATUALIZACAO = {
    "transferegov_te": "transferegov_especiais",
    "parcerias": "transferegov_parcerias",
    "faf_planos": "transferegov_fundoafundo",
    # Discricionarias nao tem API: a data vem de `data_carga_siconv.zip`.
    "transferegov_arvore": "transferegov_discricionarias",
}


async def _datas_das_fontes(db: AsyncSession) -> dict[str, datetime]:
    """{chave: data_fonte}. Vazio em erro — a tabela nasce numa migration, e a
    API sobe antes do boot que a roda."""
    try:
        r = await db.execute(text("SELECT fonte, data_fonte FROM fonte_atualizacao"))
        return {f: d for f, d in r.fetchall() if d}
    except Exception:
        await db.rollback()
        return {}


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

    datas_fonte = await _datas_das_fontes(db)
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
        fonte_em = next((datas_fonte[_FONTE_ATUALIZACAO[s]] for s in _srcs
                         if s in _FONTE_ATUALIZACAO
                         and _FONTE_ATUALIZACAO[s] in datas_fonte), None)
        out.append({
            "fonte": label,
            "ultimo_dado": last_data.isoformat() if last_data else None,
            "ultima_coleta": last_run.isoformat() if last_run else None,
            # Quando a FONTE se atualizou (None = a fonte nao publica isso).
            # Informativo: NAO entra no `status` — a data da fonte e da carga
            # dela, e cobrar frescor por ela exigiria saber a cadencia de cada
            # orgao, que ninguem mediu.
            "fonte_atualizada_em": fonte_em.isoformat() if fonte_em else None,
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
