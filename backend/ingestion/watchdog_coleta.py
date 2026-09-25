"""Watchdog da saude da coleta -- torna VISIVEL o que hoje e silencioso.

MOTIVACAO (incidente de 2026-07-23): um scraper do TransfereGov ficou pendurado
por 4h49m sem que ninguem soubesse. O `ingestion_log` so grava DEPOIS que a
execucao termina (sempre com finished_at preenchido), entao uma execucao travada
nao aparece em lugar nenhum -- nem no log, nem no painel. E fontes que pararam de
atualizar (o SIGCON ficou 26h sem ingerir) tambem passavam despercebidas.

Este cron roda a cada ~30 min e detecta DUAS condicoes que hoje ninguem ve:

  1. SCRAPER TRAVADO: um processo `ingestion/*.py` ou um `chrome-headless-shell`
     vivo ha mais tempo que o teto (o reaper ja mata, mas aqui a gente ALERTA
     antes/alem disso -- defesa em profundidade).
  2. FONTE PARADA: uma fonte cujo ultimo `success` no ingestion_log e mais velho
     que o esperado para a frequencia dela (ex.: sigcon deveria rodar 4x/dia;
     se o ultimo sucesso tem >18h, algo travou).

Alerta sempre vai para o LOG e para a tabela `watchdog_historico` (que vira a
aba Status dos Dados); se `WATCHDOG_WEBHOOK_URL` estiver configurada, tambem sai
num POST JSON generico, e se `WATCHDOG_TELEGRAM_TOKEN` + `WATCHDOG_TELEGRAM_CHAT_ID`
estiverem setadas, vai para o Telegram do operador. Nunca falha o processo por
causa do alerta.

E, na direcao contraria, `WATCHDOG_HEARTBEAT_URL` recebe um GET no fim de cada
rodada completa. Esse e o unico sinal que cobre a morte DESTE processo: se o
worker cair ou a Scheduled Task nao disparar, nada aqui roda e nada aqui alerta
— quem tem de reclamar e um servico de fora, pela ausencia do pulso. Ver
`_heartbeat()`.

Anti-spam: nao repete o mesmo alerta dentro de WATCHDOG_COOLDOWN_MIN (default
180 min) -- estado guardado na tabela watchdog_alertas.

Uso: python -m ingestion.watchdog_coleta
"""
import logging
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("watchdog_coleta")

# Idade maxima esperada do ultimo SUCCESS por fonte, em horas. Fontes fora deste
# mapa nao sao cobradas por frescor (so entram na deteccao de processo travado).
# Derivado das Scheduled Tasks reais + folga.
#
# ⚠️ O QUE E NACIONAL FICA AQUI; O QUE E DE UM ESTADO FICA EM
# `FRESCOR_HORAS_POR_UF`. O catalogo era global aos tenants e constante no
# codigo — entao um tenant sem municipio de MG era cobrado por `sigcon_scraper`,
# `cagec` e `acordofes`, fontes que ali NUNCA vao rodar. Hoje o unico motivo de
# isso nao gritar e o ramo "so cobra fonte que ja tem linha no log" logo abaixo;
# bastava alguem criar a task uma vez para o alarme virar eterno. O padrao certo
# ja existia ao lado, em routers/freshness.py (_SOURCES_POR_UF + _ufs_do_tenant)
# — este modulo so tinha ficado para tras.
FRESCOR_HORAS_NACIONAL = {
    "transferegov_opendata": 30,     # 1x/dia -> 24h + folga
    "transferegov_voluntarias": 30,
    "transferegov_pac": 30,
    "fns": 30,                       # 1x/dia
    # ⭐ MEDIDO CONTRA O CRON EM 09/09/2026, NOS SEIS WORKERS. Os prazos abaixo
    # foram escritos quando estas fontes rodavam vezes ao dia; hoje TODAS rodam
    # 1x/dia (ou com um vao de 20h, no caso do CAUC), e o prazo menor que a
    # cadencia fazia a fonte nascer ATRASADA todo santo dia — inclusive as 07h
    # BRT, que e a hora do resumo diario. O relatorio de 09/09 saiu com quatro
    # itens que eram so isso, e o dono leu o conjunto como catastrofe.
    #
    #   cauc            `25 10-14 * * *`  -> 5 rodadas de manha e um vao de 20h
    #   simec_par       dentro do run_all do cron `sigcon` em MG (1x/dia);
    #                   Scheduled Task propria diaria no RS
    #   (o `acordofes` tem a mesma cadencia, mas e so de MG: o prazo dele mora
    #   em FRESCOR_HORAS_POR_UF — ver la por que ele saiu daqui)
    #
    # Alarme que toca todo dia nao e alarme: e ruido que esconde o dia ruim.
    # 30h = a cadencia real + folga, a mesma conta das outras diarias.
    "cauc": 30,
    "simec_par": 30,
    # Termos de Compromisso do SIMEC/PAR (PR #258). MESMO caso do `sismob` logo
    # abaixo — e por isso o MESMO numero: entra pendurado no
    # run_dadosabertos_cron.run_all() (que o cron do sigcon chama 4x/dia), mas o
    # proprio ingest() se auto-limita a 1x/dia
    # (SIMEC_TERMOS_MIN_INTERVAL_H=20). A cadencia REAL, portanto, e diaria, e
    # 30h = um dia + folga. Nao confunda com o irmao 'simec_par' (12h): aquele
    # roda em toda janela do run_all.
    # NACIONAL: o run() varre todo municipio ATIVO com ibge_code e manda a UF
    # como PARAMETRO do POST (estuf), sem recorte de estado — entao o lugar e
    # aqui, nunca no mapa por UF.
    # ⚠️ ISTO SO VIGIA DE VERDADE PORQUE, no mesmo PR, o coletor passou a gravar
    # ingestion_log com source='simec_termos' e status de STATUS_SUCESSO.
    # Enquanto nao houvesse linha nenhuma, o ramo "so cobra fonte que ja tem
    # linha no log" (mais abaixo) deixaria a chave dormindo.
    "simec_termos": 30,              # 1x/dia (auto-throttle no proprio ingest)
    "siconv_convenio_backfill": 30,
    # Licitacoes por dado aberto (PR de 09/09/2026). Pendurada no run()
    # diario do transferegov_voluntarias -> 1x/dia; 30h = um dia + folga.
    # ⚠️ Entra no catalogo NO MESMO PR que a fonte: vigia que se adiciona
    # "depois" e o vigia que nunca chega, e o dado atras do login ja ficou
    # sete dias parado sem ninguem ver.
    "siconv_licitacao": 30,
    "sismob": 30,                    # 1x/dia (auto-throttle no proprio ingest)
    # ⚠️ CAGEC ENTRA COM O VOCABULARIO CORRIGIDO (ver STATUS_SUCESSO abaixo).
    # Ele nunca grava 'success' — grava 'ok'/'parcial'/'erro'. Enquanto o filtro
    # era `status = 'success'`, por-lo aqui faria o watchdog acusar
    # "nunca teve sucesso" para sempre, e por isso ele ficou de fora. Era a
    # unica fonte em cron sem vigilancia nenhuma: a Freitas passou nove dias com
    # o CAGEC falhando todo dia e nada apitou.
    # 4x/dia -> 6h entre rodadas; 30h = quase cinco janelas perdidas.
    # Lote do TransfereGov (PR #158): fonte PROPRIA no ingestion_log, separada do
    # run() diario — um nao pode esconder a falha do outro.
    # ⚠️ NAO E MAIS HORARIO, e o comentario anterior jurava que era. Medido nos
    # seis workers em 09/09/2026: uma Scheduled Task por tenant, 1x/dia
    # (freitas 03:25, trust 04:10, montesiao 04:25, santamaria 05:15,
    # novapalma 05:45, bgk 05:52 UTC). Com o prazo de 6h a fonte ficava
    # "parada" ~18 das 24 horas — e era o item que mais aparecia no resumo.
    # Desde 10/09/2026 freitas e trust rodam 4x/dia: com uma rodada so, a fila
    # de ~60 municipios do freitas (4 por rodada) levava ~15 dias para dar a
    # volta. Os outros quatro seguem 1x/dia, e e por eles que o prazo fica 30h.
    "transferegov_lote": 30,
    # FUNDO A FUNDO da saude (ConsultaFNS, publico). Scheduled Task propria, 1x
    # por dia -> 30h = um dia + folga, o mesmo numero das outras diarias.
    # ⚠️ NAO confundir com o irmao `fns` logo acima: aquele e a PROPOSTA
    # (convenios_estadual, fonte='FNS'), este e o repasse ORDINARIO por bloco.
    # Sao fontes diferentes, com coletores diferentes, e uma parada nao diz nada
    # sobre a outra.
    "fns_faf": 30,
    # SALDO DAS CONTAS do Fundo Municipal (arquivo anual do Portal FNS). A rodada
    # e diaria e quase sempre so confere a pagina ("ja carregado") e grava
    # `success`: o que se vigia e a RODADA; a idade do arquivo esta na tela.
    "fns_saldo": 30,
    # RADAR DE CAPTACAO (siconv_programa.zip). Pendurado no
    # run_dadosabertos_cron.run_all(), que o cron do sigcon chama 4x/dia -> 6h
    # entre rodadas. 30h = quase cinco janelas perdidas, o mesmo criterio do
    # CAGEC. ⚠️ Ele grava 'error' quando a rodada volta VAZIA (zero programa
    # aberto no Brasil nao e resultado plausivel), entao um arquivo que mudou de
    # layout aparece aqui como fonte parada, e nao como sucesso silencioso.
    "programas_captacao": 30,
    # A FICHA do radar (18/09/2026): mesma chamada, linha PROPRIA no log e
    # auto-limite de 20h (PROGRAMAS_FICHA_MIN_INTERVAL_H) -> cadencia real
    # diaria, 30h = um dia + folga. 'partial' (apoiadores ilegiveis) nao conta
    # como sucesso aqui, entao um dia inteiro assim tambem apita.
    "programas_captacao_ficha": 30,
    # CADASTRO DE PARLAMENTARES (Camara/Senado/ALMG). Mesmo cron do radar e
    # auto-limite de 20h, como o SICONFI: cadencia real diaria, 30h = um dia +
    # folga. Casa fora do ar grava 'partial'; as tres fora, 'error'.
    "parlamentares_cadastro": 30,
    # SICONFI/Tesouro (contas entregues + CAPAG). MESMO desenho do `sismob` e do
    # `simec_termos`: o proprio ingest() se auto-limita
    # (SICONFI_MIN_INTERVAL_H=20), entao a cadencia REAL e diaria e 30h = um dia
    # + folga. NACIONAL: varre todo municipio ativo com ibge_code, sem recorte
    # de estado — o lugar e aqui, nunca no mapa por UF.
    "siconfi": 30,
    # DOU federal (22/09/2026): task diaria em todo worker, NACIONAL (todo
    # municipio ativo, sem recorte de UF). 30h = um dia + folga. Busca que falhou
    # ou estouro de orcamento gravam 'partial', que aqui nao conta como sucesso.
    "dou_federal": 30,
    # CGU / convênios pela planilha (23/09/2026): task diária em todo worker; o
    # arquivo da CGU muda poucas vezes por mês, mas a rodada que o acha igual
    # grava `success` do mesmo jeito — então 30h continua medindo a TASK.
    "cgu_convenios": 30,
    # CGU / recursos recebidos por pasta (24/09/2026): task diária em todo worker
    # (relê o mês corrente e o anterior toda noite). Mês não publicado ou carga
    # inicial que não coube gravam 'partial', que aqui não conta como sucesso.
    "cgu_transferencias": 30,
    # Obras.gov.br/CIPI. Cadencia REAL de 2 dias (auto-limite de 44h no proprio
    # ingest): a varredura e cara — uma pagina a cada 8s por causa do rate
    # limit — e o CIPI muda devagar. 54h = dois dias + folga.
    "obrasgov": 54,
    # Portal da Transparencia / CGU — emendas parlamentares FEDERAIS (carteira do
    # dump SICONV por CNPJ + execucao da CGU). ⭐ ENTROU EM 06/09/2026, junto com
    # a decisao de ligar; ate aqui este bloco dizia "NAO ENTRA AQUI de proposito"
    # porque a fonte era um scaffold inerte sem Scheduled Task. Agora tem task
    # propria (escada 03:35 -> 05:35 UTC, lock /tmp/portal_transparencia.lock),
    # entao cobrar frescor dela deixou de ser cobrar de fonte que ninguem ligou.
    #
    # 30h = 1x/dia + folga, o mesmo numero das outras diarias.
    #
    # ⚠️ SEM `PORTAL_TRANSPARENCIA_API_KEY` A FASE 2 (execucao) CONTINUA INERTE,
    # e isso NAO faz esta chave alarmar: a FASE 1 (carteira) e dado ABERTO e roda
    # nos cinco, gravando `success` com a nota de que a execucao nao foi
    # coletada. Fonte parcialmente desligada por decisao nao e fonte quebrada —
    # e e por isso que a carteira ficou ligada por padrao: com ela desligada, a
    # linha nasceria "Fresco" com zero registros, que e a pior combinacao.
    #
    # ⚠️ NACIONAL, nunca no mapa por UF: a carteira sai do CNPJ do municipio, sem
    # recorte de estado. Emenda federal existe nos cinco tenants.
    "portal_transparencia": 30,
    # TRANSFERENCIA ESPECIAL / Emenda Pix (task `transferegov-te`, 1x/dia nos
    # seis). Estava no Frescor desde 06/09/2026 e fora DAQUI — o item O2 do
    # BACKLOG_POR_ESTADO. Entrou em 14/09/2026, no PR que levou a coleta para a
    # API oficial inteira: a rodada passou a gravar UMA linha somando listagem e
    # arvore do plano (`status_da_rodada`), entao `partial` aqui quer dizer
    # planos que ficaram sem resposta ou fora do orcamento, e diz quantos.
    # 30h = 1x/dia + folga, o mesmo numero das outras diarias. NACIONAL: a
    # carteira entra pelo CNPJ do municipio.
    "transferegov_te": 30,
    # GESTAO DE PARCERIAS (task `parcerias`, 1x/dia, com auto-limite de 20h no
    # proprio ingest). Estava no Frescor desde 07/09/2026 e fora DAQUI — mesma
    # lacuna da TE. Entrou em 15/09/2026, no PR que levou a coleta para a API
    # inteira: a rodada grava UMA linha somando listagem, emendas indicadas e
    # arvore da proposta. NACIONAL: a carteira entra pelo IBGE do municipio.
    "parcerias": 30,
    # FUNDO A FUNDO (task `faf-planos`, 1x/dia, auto-limite de 20h no ingest).
    # No Frescor desde 07/09/2026 e fora DAQUI — a mesma lacuna das duas acima.
    # Entrou em 15/09/2026, no PR da API inteira: UMA linha somando listagem,
    # beneficiarios de programa e arvore do plano (com as contas). NACIONAL.
    "faf_planos": 30,
    # VOLUNTARIAS — A ARVORE PELOS DUMPS (task `transferegov-arvore`, 1x/dia,
    # auto-limite de 20h no ingest). Entrou no MESMO commit do coletor
    # (15/09/2026): UMA linha por rodada, `partial` dizendo qual arquivo falhou.
    # NACIONAL: a carteira sao as propostas que o `transferegov_opendata` ja
    # gravou, e as canceladas entram pelo IBGE.
    "transferegov_arvore": 30,
}

# Fontes que so existem para certas UFs. A chave e a UF do TENANT (ha municipio
# ativo daquele estado?), nao a do municipio selecionado — este vigia e do
# ambiente inteiro. Espelha routers/freshness.py::_SOURCES_POR_UF.
FRESCOR_HORAS_POR_UF = {
    "MG": {
        # ⚠️ Tambem nao roda mais 4x/dia: a task `sigcon` e diaria nos tres
        # tenants de MG (freitas 05:45, trust 06:30, montesiao 06:45 UTC),
        # medido em 09/09/2026. 18h < 24h fazia o alarme tocar toda tarde.
        "sigcon_scraper": 30,
        # Empenhos/pagamentos estaduais pelo CSV da SEGOV (15/09/2026). Pendurado
        # no cron `sigcon` (diario, ver acima) com auto-throttle de 20h no
        # proprio ingest(): cadencia REAL diaria, 30h = um dia + folga. So MG:
        # o ingest() sai antes de baixar em tenant sem municipio mineiro e nao
        # grava log — por isso mora AQUI, e nao no catalogo nacional.
        # ⚠️ Entra no MESMO PR que a fonte (a regra do `siconv_licitacao`).
        "segov_pagamentos": 30,
        # Data/nº da OB pelos dumps da CGE (Fase 2, 15/09/2026): mesmo cron,
        # mesmo throttle de 20h, so MG. Grava em transparencia_mg_empenhos com
        # source proprio no ingestion_log.
        "cge_despesa_ob": 30,
        "cagec": 30,                 # 4x/dia -> 6h; 30h = quase cinco janelas
        # ⚠️ ESTA LINHA ERA A QUE VALIA, e ninguem via. O acordofes roda dentro
        # do run_all() do cron `sigcon` — 1x/dia — e o conserto de 09/09 subiu o
        # prazo para 30h no catalogo NACIONAL. Mas `frescor_esperado()` aplica o
        # mapa da UF POR CIMA (`update`), entao nos tres tenants de MG o prazo
        # continuou 12h: o alarme tocou toda tarde, com a fonte em 15-17h de
        # idade, em freitas, trust e montesiao ate 10/09/2026. Fonte de UM
        # estado tem prazo em UM lugar — `test_frescor_vs_cron.py` agora reprova
        # a mesma fonte nos dois mapas.
        "acordofes": 30,
        # Emendas estaduais da SEGOV pelo dados.mg.gov.br, 1x/dia. O
        # que se vigia aqui é a RODADA; a idade dos DADOS (a planilha do site parou
        # em maio de 2026) vira `partial` com a data na nota, pelo próprio coletor.
        "emendas_mg": 30,
    },
    "ES": {"gconv_es": 30},
    "GO": {"transfvol_go": 30, "cofin_ses_go": 30, "tcm_go": 30},
    "RS": {
        "che_rs": 30,          # 3x/dia; 30h = cinco janelas perdidas
        # CADIN/RS + CFIL/RS (certidao publica da CAGE). Roda 1x/dia junto do
        # CHE; 30h = um dia + folga. ⚠️ Aqui o frescor vale MAIS que nas outras
        # fontes: a certidao NAO TEM VALIDADE — ela afirma a situacao "na data
        # de", e so. Uma coleta parada nao envelhece um prazo, ela deixa de
        # responder a pergunta.
        "cadin_rs": 30,
        "convenios_rs": 30,    # 1x/dia (a CAGE republica o dump esporadicamente)
        # ⚠️ 1x/dia e SO de segunda a sabado (o FPE fecha aos domingos e fora do
        # horario comercial). 54h cobre o fim de semana sem alarme falso: a
        # rodada de sabado 9h35 so tem a proxima na segunda 9h35, ~48h depois.
        "fpe_rs": 54,
        # semanal: 8 dias de folga (a fonte muda 1x/ano, apos a votacao)
        "consulta_popular_rs": 192,
        # TCE-RS/LicitaCon: o TCE republica os ZIPs por orgao com cadencia
        # semanal (o de Nova Palma foi atualizado em 31/08/2026, um domingo), e
        # a rodada e diaria com HTTP condicional — quase toda ela responde 304.
        # 30h porque o que se vigia e a RODADA, nao a mudanca da fonte: 304 e
        # sucesso e carimba o log igual.
        "tce_rs": 30,
        # TCE-RS pelo portal (portal.tce.rs.gov.br). Rodada diaria; 30h = quase
        # cinco janelas perdidas, o mesmo criterio dos vizinhos.
        #
        # ⚠️ A PRIMEIRA CARGA LEVA VARIAS NOITES e isso NAO e defeito: o valor do
        # contrato so existe no endpoint de detalhe, uma requisicao por contrato,
        # e Santa Maria tem 6.213. O coletor gasta um orcamento de tempo por
        # rodada e continua de onde parou — cada uma dessas rodadas grava
        # `success`, entao o frescor fica em dia desde a primeira.
        "tce_rs_portal": 30,
    },
    "PR": {
        # TCE-PR pelo PIT (22/09/2026). Rodada diária; quase toda ela é um HEAD
        # por ano com o ETag de sempre (os zips antigos são congelados) e grava
        # `success` igual. 30h = um dia + folga, o critério dos vizinhos.
        "tce_pr": 30,
        # Convênios do Estado pelo Portal da Transparência (SIT). O Estado regera
        # os arquivos todo dia ~08:12 UTC e a rodada é diária: 30h, a regra.
        "convenios_pr": 30,
        # Certidões do Estado (SEFA + Liberatória do TCE-PR), 1x/dia. A
        # Liberatória não tem validade — vale na data da consulta —, então aqui o
        # frescor É o dado: 30h parado é regularidade que deixou de ser afirmada.
        "regularidade_pr": 30,
    },
    "TO": {
        # Convênios do Estado pelo TRANSFERE.TO (pesquisa externa, 23/09/2026).
        # Rodada diária que varre todos os ids (~25 min da VPS): 30h, a regra.
        "convenios_to": 30,
    },
}


def _ufs_do_tenant(cur) -> set[str]:
    """UFs com municipio ATIVO. Mesma consulta de routers/freshness.py.

    ⚠️ FAIL-OPEN: erro devolve conjunto vazio, ou seja, so o catalogo nacional.
    Vigia com catalogo curto e melhor que vigia que nao roda — e o oposto do
    fail-closed que vale para as LEITURAS de deteccao."""
    try:
        cur.execute("SELECT DISTINCT upper(coalesce(uf, '')) FROM municipios "
                    "WHERE active")
        return {r[0] for r in cur.fetchall() if r[0]}
    except Exception:
        return set()


def frescor_esperado(cur) -> dict:
    """O catalogo que vale NESTE tenant: o nacional + o das UFs presentes."""
    esperado = dict(FRESCOR_HORAS_NACIONAL)
    for uf in _ufs_do_tenant(cur):
        esperado.update(FRESCOR_HORAS_POR_UF.get(uf, {}))
    return esperado

# Teto de idade (horas) da ultima coleta BOA por MUNICIPIO, por fonte do
# scraper_municipio_coleta. E o alerta que faltava: o frescor por FONTE acima
# fica verde com a fonte rodando, mesmo que municipios especificos passem dias
# sem dado (rodizio lento, portal recusando um convenente, etc.) — foi assim
# que a Freitas chegou a 21/40 municipios defasados sem nada apitar.
# sigcon 48h: meta e <24h, mas 48h evita flapping enquanto o fatiamento por
# rodada curta faz a fila baixar. transferegov 36h: ciclo real e <24h + folga.
# cagec 48h: 4 rodadas/dia cobrem a carteira em 1-2 passadas com o rodizio;
# 48h = o MESMO municipio perdeu duas janelas inteiras.
STALENESS_MUNICIPIO_H = {"sigcon": 48, "transferegov": 36, "cagec": 48}

# ⚠️ SUCESSO E SO SUCESSO. Cada coletor escreve a palavra na sua lingua:
# cauc/gconv_es/sismob/simec_par gravam 'success', o cagec_scraper grava 'ok'.
# Filtrar por 'success' literal — como estava — excluia o CAGEC inteiro, e por
# isso ele nunca pode ser vigiado. Nao vale "padronizar o coletor e pronto": o
# historico ja gravado continuaria em 'ok' e a fonte ficaria cega por mais 30h.
#
# ⚠️ E 'partial'/'parcial' FICAM DE FORA, de proposito. O 'parcial' do CAGEC foi
# inventado em 01/08/2026 exatamente para este painel NAO ficar verde: naquele
# dia o coletor gravou 'ok' sem o CRC, o frescor ficou verde e a tela do gestor
# perdeu 28 obrigacoes sem ninguem ver. Aceita-lo aqui como sucesso desfaria a
# correcao — e hoje, com o portal do Estado recusando emitir CRC, TODA rodada do
# CAGEC e 'parcial': a vigilancia nasceria desligada justo no estado degradado.
# Para as outras fontes isto tambem NAO afrouxa nada: na main o filtro ja era
# `status = 'success'`, logo o 'partial' delas nunca contou como sucesso.
STATUS_SUCESSO = ("success", "ok")

# Acima desta idade (segundos) um processo de ingestao/Chromium e considerado
# travado. Alinhado ao teto dos crons (timeout -k 30 3000 = 50 min) + margem.
IDADE_TRAVADO_S = int(os.getenv("WATCHDOG_MAX_PROC_S", "3900") or "3900")


def _db_url() -> str:
    return (os.getenv("DATABASE_URL_SYNC", "")
            .replace("&channel_binding=require", "").replace("?channel_binding=require", ""))


def _instancia() -> str:
    return os.getenv("INSTANCE_SLUG") or os.getenv("HOSTNAME") or "pactha"


# --------------------------------------------------------------- deteccao ---

def _fontes_paradas(cur, esperado: dict | None = None) -> list[dict]:
    """Fontes cujo ultimo SUCCESS e mais velho que o limite da fonte.

    `esperado` e o catalogo ja recortado pelas UFs do tenant (frescor_esperado).
    O default existe so para chamada avulsa em teste/console."""
    if esperado is None:
        esperado = frescor_esperado(cur)
    cur.execute("""
        SELECT source, max(finished_at) AS ultimo
        FROM ingestion_log
        WHERE lower(coalesce(status, '')) = ANY(%s)
        GROUP BY source
    """, (list(STATUS_SUCESSO),))
    achados = []
    for source, ultimo in cur.fetchall():
        limite_h = esperado.get(source)
        if limite_h is None or ultimo is None:
            continue
        cur.execute("SELECT EXTRACT(EPOCH FROM (now() - %s)) / 3600.0", (ultimo,))
        idade_h = float(cur.fetchone()[0])
        if idade_h > limite_h:
            achados.append({
                "tipo": "fonte_parada",
                "chave": source,
                "detalhe": f"ultimo sucesso ha {idade_h:.1f}h (limite {limite_h}h)",
            })
    # Fontes ESPERADAS que ja REGISTRARAM alguma execucao mas nunca um sucesso.
    # Fonte sem NENHUMA linha fica de fora: task nao configurada neste tenant
    # (lote horario e por-tenant no Coolify; SISMOB pode estar desligado) nao
    # pode virar alarme eterno — e a mesma armadilha ja documentada no INFRA.md
    # (caso SISMOB_ENABLED=0), que este ramo reproduzia para toda fonte nova.
    cur.execute("SELECT DISTINCT source FROM ingestion_log")
    com_linha = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT DISTINCT source FROM ingestion_log "
                "WHERE lower(coalesce(status, '')) = ANY(%s)", (list(STATUS_SUCESSO),))
    com_sucesso = {r[0] for r in cur.fetchall()}
    for source in esperado:
        if source in com_linha and source not in com_sucesso:
            achados.append({
                "tipo": "fonte_parada",
                "chave": source,
                "detalhe": "nenhum sucesso registrado ainda",
            })
    # ⚠️ ITEM 6 (auditoria 11/09): fonte CRITICA que nunca deixou UMA linha.
    # O ramo acima ignora de proposito fonte sem linha (task opcional por tenant,
    # ex.: SISMOB desligado) — nao pode virar alarme eterno. MAS estas duas SAO
    # federais/nacionais, deveriam rodar em TODO tenant, e a auditoria as pegou
    # orfas (sem Scheduled Task, sem log). Aqui viram um achado PROPRIO e explicito
    # ("nunca executada") em vez de sumirem no silencio que este watchdog existe
    # para acabar. Ao ganharem task e a 1a linha, o ramo de frescor acima assume.
    # 15/09/2026 (PR 4 da §1.26): `siconv_empenho_aberto` SAIU daqui e entrou
    # `transferegov_arvore`. A task `empenho-aberto` foi desativada (reserva): a
    # arvore le o mesmo `siconv_empenho.zip` e grava a mesma coluna, e e ela que
    # tem de existir em todo tenant.
    _CRITICAS_SEMPRE = {"siconv_federal", "transferegov_arvore"}
    for source in sorted(_CRITICAS_SEMPRE - com_linha):
        achados.append({
            "tipo": "fonte_nunca_executada",
            "chave": source,
            "detalhe": "fonte critica federal sem NENHUMA execucao — Scheduled Task nao criada?",
        })
    return achados


def _municipios_defasados(cur) -> list[dict]:
    """Municipios cuja ultima coleta BOA e mais velha que o teto da fonte.

    Pos-#159 o carimbo de `ultima_coleta_em` acontece TAMBEM no erro (para o
    rodizio nao sofrer starvation), entao o carimbo sozinho nao significa "dado
    novo". Dado bom = carimbo com tentativas=0 (a streak zera no 1o sucesso).
    Municipio em falha persistente (tentativas>0) e problema de credencial ou
    de portal: entra como NOTA agregada no texto do alerta, nunca como alarme
    proprio — credencial quebrada nao trava (nem polui) o jogo.

    Um alerta AGREGADO por fonte (chave = fonte), com contagem + piores casos,
    para o cooldown valer por fonte e nao virar spam por municipio.
    """
    achados = []
    # O MESMO teto do coletor (sigcon_scraper::_list_credentials). Se mudar la,
    # muda aqui — o watchdog e quem conta ao dono o que o coletor desistiu de
    # tentar, e as duas contas discordando fariam o aviso mentir.
    TETO_LOGIN = max(1, int(os.getenv("SIGCON_MAX_TENTATIVAS_LOGIN", "3") or "3"))
    for fonte, limite_h in STALENESS_MUNICIPIO_H.items():
        try:
            cur.execute("""
                SELECT m.nome,
                       EXTRACT(EPOCH FROM (now() - sc.ultima_coleta_em)) / 3600.0 AS idade_h,
                       coalesce(sc.tentativas, 0)
                FROM scraper_municipio_coleta sc
                JOIN municipios m ON m.id = sc.municipio_id
                -- so municipios ATIVOS: contrato encerrado mantem a linha do
                -- rodizio (historico), mas nao pode inflar a nota de 'falha
                -- persistente' nem virar defasado (visto 09/08: 9 ex-clientes
                -- da freitas contando como falha de credencial no log).
                WHERE sc.fonte = %s AND coalesce(m.active, true)
                ORDER BY sc.ultima_coleta_em ASC
            """, (fonte,))
            rows = cur.fetchall()
        except Exception as e:
            # Tabela do rodizio ausente (worker subiu antes da migration) nao
            # pode abortar o watchdog inteiro; rollback para nao envenenar a
            # transacao dos checks seguintes (_deve_alertar usa a mesma conexao).
            try:
                cur.connection.rollback()
            except Exception:
                pass
            logger.debug(f"  staleness {fonte} indisponivel: {e}")
            continue
        if not rows:
            continue  # fonte sem rastreio neste tenant (ex.: sem credencial SIGCON)
        defasados = []
        com_erro = 0
        for nome, idade, tent in rows:
            if tent > 0:
                com_erro += 1     # falha persistente = credencial/portal -> nota, nao alarme
            elif idade is None:
                defasados.append((nome, None))   # linha existe mas nunca coletou (legado pre-#159)
            elif idade > limite_h:
                defasados.append((nome, idade))
        if com_erro:
            logger.info(f"  {fonte}: {com_erro} municipio(s) em falha persistente "
                        f"(credencial/portal) — nota, nao alarme")
        # ⭐ CREDENCIAL RECUSADA E DESISTIDA — este SOBE de nota para ALERTA.
        #
        # A partir de 11/08/2026 o coletor PARA de tentar login depois de 3
        # recusas (ordem do dono: insistir arrisca bloqueio da conta no portal).
        # Parar e o certo — mas parar CALADO trocaria o risco de bloqueio pelo
        # risco de um municipio ficar meses sem coleta sem ninguem notar. Aqui
        # ele vira linha visivel, com o nome e o caminho de volta.
        try:
            cur.execute(
                "SELECT m.nome, coalesce(sc.tentativas,0) "
                "FROM scraper_municipio_coleta sc "
                "JOIN municipios m ON m.id = sc.municipio_id "
                "WHERE sc.fonte = %s AND coalesce(sc.tentativas,0) >= %s "
                "  AND coalesce(sc.ultimo_erro,'') ILIKE %s "
                "  AND coalesce(m.active, true) ORDER BY m.nome",
                (fonte, TETO_LOGIN, "%login%"))
            travados = cur.fetchall()
        except Exception:
            try:
                cur.connection.rollback()
            except Exception:
                pass
            travados = []
        if travados:
            nomes = ", ".join(f"{n} ({t}x)" for n, t in travados[:5])
            if len(travados) > 5:
                nomes += " ..."
            achados.append({
                "tipo": "credencial_recusada", "chave": fonte,
                "detalhe": (f"{len(travados)} municipio(s) com CREDENCIAL RECUSADA pelo portal — "
                            f"coleta SUSPENSA para nao arriscar bloqueio da conta: {nomes}. "
                            f"Corrigir a senha no Cofre religa automaticamente."),
            })
        if defasados:
            defasados.sort(key=lambda t: float("inf") if t[1] is None else t[1], reverse=True)
            piores = ", ".join(("%s (nunca)" % n if i is None else "%s (%.0fh)" % (n, i))
                               for n, i in defasados[:5])
            detalhe = f"{len(defasados)} municipio(s) sem coleta boa ha >{limite_h}h: {piores}"
            if len(defasados) > 5:
                detalhe += " ..."
            if com_erro:
                detalhe += f" | nota: {com_erro} municipio(s) em falha persistente (credencial?)"
            achados.append({"tipo": "municipio_defasado", "chave": fonte, "detalhe": detalhe})
    return achados


# LOGIN gov.br EXPIRADO. Gravado por `govbr_renew._registra_sso` (a cada renovacao
# horaria). O nome e a frase sao repetidos aqui, e nao importados, de proposito:
# o `govbr_renew` puxa Playwright e `services.crypto`, e o vigia nao pode deixar
# de rodar porque um desses nao importou. `test_watchdog_sessao_govbr.py` garante
# que os dois lados continuam iguais.
SOURCE_SSO = "govbr_sso"
FRASE_SEM_SESSAO = "nenhuma sessao gov.br no Cofre"
# 3h = tres renovacoes horarias seguidas falhando. Uma so pode ser o portal fora
# do ar por minutos (o renew le isso como "nao autenticado"); tres e o SSO.
SESSAO_LIMITE_H = float(os.getenv("WATCHDOG_SESSAO_H", "3") or "3")
# ⚠️ COOLDOWN PROPRIO, mais longo que o padrao (180 min). Sessao caida so volta
# com uma PESSOA fazendo login — repetir a cada 3h nos seis tenants seriam 48
# mensagens por dia, e alarme que enche o canal ensina a silenciar o canal.
SESSAO_COOLDOWN_MIN = int(os.getenv("WATCHDOG_SESSAO_COOLDOWN_MIN", "720") or "720")


def _sessao_govbr_caida(cur) -> list[dict]:
    """O login gov.br deste tenant expirou ha mais de SESSAO_LIMITE_H.

    ⭐ POR QUE EXISTE: de 14 a 17/09/2026 a sessao morreu nos SEIS tenants e
    ninguem soube por ~2 dias. O `govbr-renew` escrevia `needs_recapture` toda hora
    — no log do container. E o `govbr_sessao` do keepalive, que ESTA no banco, nao
    serve de gatilho: ele mede o /private/ das mandatarias, caido quase sempre
    mesmo com o SSO bom. Sem sessao param o detalhe dos convenios, NEs, Termos de
    Notificacao, Projeto Basico e os anexos do TransfereGov — e so uma pessoa
    resolve (o login tem reCAPTCHA).

    Nao alarma: tenant sem nenhuma linha (task nao existe) e tenant que NUNCA
    capturou sessao (`FRASE_SEM_SESSAO`) — cobrar recaptura de quem nunca capturou
    e o alarme eterno que este modulo evita em todo lugar."""
    cur.execute("SELECT status, error_message FROM ingestion_log "
                "WHERE source = %s ORDER BY id DESC LIMIT 1", (SOURCE_SSO,))
    ult = cur.fetchone()
    if not ult or (ult[0] or "").lower() in STATUS_SUCESSO or ult[1] == FRASE_SEM_SESSAO:
        return []
    # Desde quando: a ultima renovacao boa; sem nenhuma, a primeira linha da
    # fonte. ⚠️ O segundo ramo e o do DEPLOY DESTE VIGIA: em 17/09/2026 os seis
    # tenants ja estavam sem sessao, entao `govbr_sso` nasce sem um unico success
    # — exigir um sucesso anterior deixaria o alarme mudo exatamente agora.
    cur.execute("""
        SELECT EXTRACT(EPOCH FROM (now() - t)) / 3600.0,
               to_char(t AT TIME ZONE 'America/Sao_Paulo', 'DD/MM HH24:MI'),
               ok
        FROM (
          SELECT coalesce(
                   max(finished_at) FILTER (WHERE lower(coalesce(status, '')) = ANY(%s)),
                   min(finished_at)) AS t,
                 bool_or(lower(coalesce(status, '')) = ANY(%s)) AS ok
          FROM ingestion_log WHERE source = %s
        ) x
    """, (list(STATUS_SUCESSO), list(STATUS_SUCESSO), SOURCE_SSO))
    idade_h, quando, teve_ok = cur.fetchone()
    if idade_h is None or float(idade_h) < SESSAO_LIMITE_H:
        return []
    desde = (f"ultima renovacao ok em {quando} (Brasilia)" if teve_ok
             else f"sem renovacao ok desde que o vigia passou a medir, {quando} (Brasilia)")
    return [{
        "tipo": "sessao_govbr_caida",
        "chave": SOURCE_SSO,
        "detalhe": (f"Login gov.br expirado ha {float(idade_h):.0f}h — {desde}.\n"
                    "Parado: detalhe dos convenios, NEs, Termos de Notificacao, "
                    "Projeto Basico e anexos do TransfereGov.\n"
                    # ⚠️ O ROTEIRO INTEIRO, e nao "abrir o TransfereGov": sao QUATRO
                    # portas com sessao propria, e logar so na primeira deixava
                    # /private/, execucao e prestacao fora do jar. O botao da
                    # extensao (>= 2.4.0) abre as quatro na mesma aba.
                    "Resolver (2 min): no Chrome, clique no icone da extensao do PACTHA > "
                    "\"Captura completa (abre as 4 portas)\", faca o login gov.br "
                    "quando pedir e espere a aba passar pelas quatro. "
                    "Nao clique em Sair depois."),
    }]


def _processos_travados() -> list[dict]:
    """Processos de ingestao / Chromium vivos ha mais que IDADE_TRAVADO_S.

    Le a arvore de processos do PROPRIO container (o watchdog roda como um
    `docker exec` no worker, entao ve os processos dos scrapers). Best-effort:
    se ps/pgrep faltarem, retorna vazio sem quebrar."""
    achados = []
    try:
        # etimes = segundos de vida; args = linha de comando
        out = subprocess.run(
            ["ps", "-eo", "etimes,args"],
            capture_output=True, text=True, timeout=15,
        ).stdout
    except Exception as e:
        logger.debug(f"  ps indisponivel: {e}")
        return achados

    for linha in out.splitlines()[1:]:
        linha = linha.strip()
        if not linha:
            continue
        parte = linha.split(None, 1)
        if len(parte) != 2:
            continue
        try:
            idade = int(parte[0])
        except ValueError:
            continue
        cmd = parte[1]
        eh_ingestao = "ingestion/" in cmd or "ingestion." in cmd
        eh_chrome = "chrome-headless-shell" in cmd or "ms-playwright" in cmd
        if (eh_ingestao or eh_chrome) and idade > IDADE_TRAVADO_S:
            achados.append({
                "tipo": "processo_travado",
                "chave": cmd[:60],
                "detalhe": f"vivo ha {idade // 60} min (teto {IDADE_TRAVADO_S // 60} min)",
            })
    return achados


# --------------------------------------------------------------- anti-spam --

def _garante_tabela(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS watchdog_alertas (
            tipo         VARCHAR(30)  NOT NULL,
            chave        VARCHAR(120) NOT NULL,
            ultimo_envio TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (tipo, chave)
        )
    """)


def _sessao_govbr_vencendo(cur) -> list[dict]:
    """O login gov.br esta VIVO mas vai vencer — avisar ANTES, com hora e acao.

    ⭐ POR QUE (23/09/2026): a sessao caiu nos seis ~24h depois do login sem que
    ninguem gravasse por cima (audit_log): a vida e a do proprio SSO. O alarme de
    sessao caida chega DEPOIS do estrago (a noite de coleta ja rodou sem login).
    Este chega 3h antes, com a hora prevista, para o dono logar de novo e o login
    novo se propagar sozinho (candidata -> promovida). Hora do login = a captura
    gravada na `observacao` da linha `govbr` (`services.sessao_govbr`).

    Nao alarma: sem linha, sem marca de captura, login ja medido como caido (ai e o
    outro alarme), ou fora da janela [21h, 27h) desde o login."""
    from services.sessao_govbr import (login_em_da_observacao, sessao_esta_viva, texto_do_aviso,
                                       vencimento)
    cur.execute("SELECT observacao FROM cofre_senhas WHERE automation_key='govbr' "
                "AND municipio_id IS NULL ORDER BY updated_at DESC LIMIT 1")
    row = cur.fetchone()
    login_em = login_em_da_observacao(row[0] if row else None)
    if login_em is None:
        return []
    # So login MEDIDO VIVO (success recente) — a mesma regua da rota de saude.
    # Nunca medido, caido ou medicao velha (worker parado): nao e "vencendo".
    cur.execute("SELECT status, EXTRACT(EPOCH FROM (now() - finished_at)) / 60.0 "
                "FROM ingestion_log WHERE source = %s ORDER BY id DESC LIMIT 1", (SOURCE_SSO,))
    ult = cur.fetchone()
    if not ult or not sessao_esta_viva(ult[0], ult[1]):
        return []
    if not vencimento(login_em)["vencendo"]:
        return []
    return [{"tipo": "sessao_govbr_vencendo", "chave": SOURCE_SSO,
             "detalhe": texto_do_aviso(login_em)}]


def _deve_alertar(cur, tipo: str, chave: str, cooldown_min: int) -> bool:
    """True se este alerta nao foi enviado dentro do cooldown. Registra o envio."""
    cur.execute(
        "SELECT EXTRACT(EPOCH FROM (now() - ultimo_envio)) / 60.0 "
        "FROM watchdog_alertas WHERE tipo = %s AND chave = %s",
        (tipo, chave))
    row = cur.fetchone()
    if row is not None and float(row[0]) < cooldown_min:
        return False
    cur.execute(
        "INSERT INTO watchdog_alertas (tipo, chave, ultimo_envio) VALUES (%s, %s, now()) "
        "ON CONFLICT (tipo, chave) DO UPDATE SET ultimo_envio = now()",
        (tipo, chave))
    return True


# --------------------------------------------------------------- envio ------

def _telegram(mensagem: str) -> None:
    """Canal 4 — manda o alerta para o Telegram do operador. Best-effort.

    Precisa das DUAS envs (`WATCHDOG_TELEGRAM_TOKEN`, `WATCHDOG_TELEGRAM_CHAT_ID`);
    faltando qualquer uma, sai calado — é o mesmo desenho do webhook, e é o que
    permite ligar o canal num tenant sem tocar nos outros quatro.

    ⚠️ O TEXTO VAI EM TEXTO PURO, E ISSO É DELIBERADO. A mensagem montada no
    `main()` usa `*negrito*` e crase — resto da época em que este canal falava
    Markdown legado do Telegram. Mandar com `parse_mode` de volta parece uma
    melhora de meia linha e é uma armadilha: no Markdown legado o `_` abre
    itálico, e os nomes das nossas fontes são `transferegov_opendata`,
    `sigcon_scraper`, `simec_par`. Um `_` sozinho na mensagem faz a API devolver
    **400 «can't parse entities»** e o alerta some — justamente no dia em que
    uma fonte quebrou. Um vigia não pode ter um modo de falhar que depende do
    nome do que ele está vigiando. Por isso os marcadores são REMOVIDOS aqui e
    a hierarquia fica por conta do emoji, que não precisa de parser.

    ⚠️ E o corte em 4.000 caracteres não é folclore: o limite da API é 4.096, e
    `municipios_defasados` concatena um alerta por município — a carteira da
    Freitas tem 44. Estourar o limite é outro 400, com o mesmo efeito de sumiço.
    """
    token = (os.getenv("WATCHDOG_TELEGRAM_TOKEN") or "").strip()
    chat_id = (os.getenv("WATCHDOG_TELEGRAM_CHAT_ID") or "").strip()
    if not (token and chat_id):
        return
    try:
        import json as _json
        import urllib.request
        texto = mensagem.replace("*", "").replace("`", "")[:4000]
        corpo = _json.dumps({"chat_id": chat_id, "text": texto,
                             "disable_web_page_preview": True}).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=corpo, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            logger.info(f"  telegram: HTTP {r.status}")
    except Exception as e:
        # ⚠️ O TOKEN VAI NA URL, E O urllib POE A URL NA MENSAGEM DO ERRO.
        # A primeira versao disto confiava no corte em 120 caracteres — o mesmo
        # que o webhook usa — e o teste mostrou que nao protege nada: a URL
        # COMECA pelo token, entao ele cabe inteiro nos 120. Um 401 (token
        # errado, que e o erro mais provavel no dia de ligar o canal) escreveria
        # a credencial no log do worker, que fica no Coolify. Trocar antes de
        # cortar e o que resolve; a ordem importa.
        detalhe = str(e).replace(token, "<token>")[:120]
        logger.warning(f"  falha no telegram: {type(e).__name__}: {detalhe}")


def _heartbeat() -> None:
    """Pulso para um vigia EXTERNO — o único canal que sobrevive à nossa morte.

    Todo o resto deste arquivo detecta coisa parada e avisa. Nada disso funciona
    no caso que já aconteceu: o worker cair, ou a Scheduled Task não disparar.
    Aí o watchdog não roda, não alerta, e **o silêncio fica idêntico à saúde** —
    foi essa a forma dos 6 dias de regularidade estadual travada sem ninguém
    notar (CONTINUAR.md §1.18).

    A inversão é a correção: um serviço de fora (healthchecks.io, cron-job.org)
    espera este GET a cada rodada e alarma pela AUSÊNCIA dele. Sem env setada,
    nada acontece — como todos os canais opcionais daqui.

    Chamado só quando a rodada chega ao fim: pulso é "eu rodei inteiro", não
    "eu comecei". Achado não impede o pulso — quem conta o achado é o canal 4.
    """
    url = (os.getenv("WATCHDOG_HEARTBEAT_URL") or "").strip()
    if not url:
        return
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=10) as r:
            logger.info(f"  heartbeat: HTTP {r.status}")
    except Exception as e:
        logger.warning(f"  falha no heartbeat: {type(e).__name__}: {str(e)[:120]}")


def _alerta(mensagem: str, cur=None, tipo: str = "", chave: str = "") -> None:
    """Entrega o alerta em TODOS os canais disponiveis. Sempre loga.

    ⚠️ ATE 11/08/2026 ESTA FUNCAO PODIA NAO ENTREGAR NADA. O Telegram foi
    desligado por decisao do dono (09/08) e o WhatsApp ainda nao existe: o
    watchdog detectava, montava a frase certa e terminava com "(Telegram nao
    configurado -- alerta so no log)". Um vigia que grita para uma sala vazia e
    pior que nenhum, porque ele passa a sensacao de que alguem esta olhando.
    Foi por isso que o canal 2 (banco) nasceu, e e por isso que ele nao depende
    de env nenhuma. Em 05/09/2026 o Telegram saiu de vez — e em 08/09/2026
    voltou, porque o dono escolheu esse canal e desta vez o token está setado.
    A lição sobreviveu à volta e vale para qualquer canal que vier: **canal que
    depende de credencial é o último da fila, nunca o primeiro.** O que decide
    se o vigia serve não é o canal bonito; é o canal que funciona sem ninguém
    configurar nada.

    Ordem dos canais, do que sempre funciona ao que depende de configuracao:
      1. LOG — sempre.
      2. BANCO (`watchdog_historico`) — vira a aba Status dos Dados. Nao depende
         de credencial nenhuma: o operador abre o sistema e ve. E o canal que
         resolve HOJE.
      3. WEBHOOK (`WATCHDOG_WEBHOOK_URL`) — um POST JSON generico, para n8n,
         Zapier, Make ou um endpoint nosso.
         ⚠️ Este docstring dizia que para Slack e Discord "e so preencher a env,
         do nosso lado nao muda nada". **É falso**, e a promessa vencida custa
         uma tarde: o corpo vai com a chave `texto`, o Slack lê `text` e o
         Discord lê `content`. Os dois respondem sem erro visível e não
         renderizam nada. Apontar direto para eles exige mudar as chaves aqui.
      4. TELEGRAM (`WATCHDOG_TELEGRAM_TOKEN` + `WATCHDOG_TELEGRAM_CHAT_ID`) —
         voltou em 08/09/2026, por escolha do dono e desta vez **com token de
         verdade nas envs**. Ver `_telegram()`.
    Cada canal e best-effort e isolado: falhar num nao pode impedir os outros
    (o alerta ja e a noticia ruim; nao pode virar duas)."""
    logger.warning(f"ALERTA: {mensagem}")

    # 2. Banco — o canal que nao depende de ninguem.
    if cur is not None:
        try:
            cur.execute(
                "INSERT INTO watchdog_historico (tipo, chave, mensagem) VALUES (%s,%s,%s)",
                (tipo or "alerta", chave or "-", mensagem[:2000]))
            cur.connection.commit()
        except Exception as e:
            try:
                cur.connection.rollback()
            except Exception:
                pass
            logger.warning(f"  historico do alerta nao gravado: {str(e)[:120]}")

    # 3. Webhook generico.
    url = (os.getenv("WATCHDOG_WEBHOOK_URL") or "").strip()
    if url:
        try:
            import json as _json
            import urllib.request
            corpo = _json.dumps({"texto": mensagem, "tipo": tipo, "chave": chave,
                                 "instancia": _instancia()}).encode("utf-8")
            req = urllib.request.Request(
                url, data=corpo, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                logger.info(f"  webhook: HTTP {r.status}")
        except Exception as e:
            logger.warning(f"  falha no webhook: {str(e)[:120]}")

    # 4. Telegram. Por ultimo de proposito: depende de credencial, e uma falha
    #    aqui nao pode engolir os canais que ja entregaram acima.
    _telegram(mensagem)


def main() -> None:
    import psycopg2
    url = _db_url()
    if not url:
        logger.error("DATABASE_URL_SYNC ausente")
        return
    cooldown = int(os.getenv("WATCHDOG_COOLDOWN_MIN", "180") or "180")
    inst = _instancia()

    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        _garante_tabela(cur)
        conn.commit()

        # O catalogo e resolvido UMA vez por rodada, contra as UFs deste tenant:
        # cobrar frescor de fonte que nao existe aqui e como cobrar coleta de um
        # estado onde nao temos cliente.
        esperado = frescor_esperado(cur)
        logger.info("frescor esperado neste tenant: %s",
                    ", ".join(sorted(esperado)) or "(nenhuma fonte)")
        achados = (_fontes_paradas(cur, esperado) + _municipios_defasados(cur)
                   + _sessao_govbr_caida(cur) + _sessao_govbr_vencendo(cur)
                   + _processos_travados())
        if not achados:
            logger.info("coleta saudavel: nenhuma fonte parada, nenhum municipio defasado, nenhum processo travado")
        else:
            _ICONES = {"processo_travado": "\U0001F534", "fonte_parada": "\U0001F7E0",
                       "municipio_defasado": "\U0001F7E1",
                       # Chave: e acao de PESSOA (trocar a senha), nao de maquina.
                       "credencial_recusada": "\U0001F511",
                       # Mesma natureza: so uma pessoa faz o login.
                       "sessao_govbr_caida": "\U0001F511",
                       # Antes de cair: relogio, nao chave — ainda da tempo.
                       "sessao_govbr_vencendo": "⏰"}
            _TITULOS = {"processo_travado": "processo travado", "fonte_parada": "fonte parada",
                        "municipio_defasado": "municipios defasados",
                        "credencial_recusada": "credencial recusada — coleta suspensa",
                        "sessao_govbr_caida": "sessao gov.br caida — recapturar",
                        "sessao_govbr_vencendo": "sessao gov.br vence em breve — logar de novo"}
            enviados = 0
            for a in achados:
                # Os dois alarmes de sessao pedem uma PESSOA: cooldown longo (12h),
                # senao viram spam que ensina a silenciar o canal.
                cd = (SESSAO_COOLDOWN_MIN if a["tipo"] in ("sessao_govbr_caida", "sessao_govbr_vencendo")
                      else cooldown)
                if _deve_alertar(cur, a["tipo"], a["chave"], cd):
                    conn.commit()
                    icone = _ICONES.get(a["tipo"], "\U0001F7E0")
                    titulo = _TITULOS.get(a["tipo"], a["tipo"])
                    _alerta(f"{icone} *PACTHA {inst}* — {titulo}\n`{a['chave']}`\n{a['detalhe']}",
                            cur=cur, tipo=a["tipo"], chave=a["chave"])
                    enviados += 1
                else:
                    logger.info(f"  (em cooldown, nao reenviado): {a['tipo']} {a['chave']}")
            logger.info(f"watchdog: {len(achados)} achado(s), {enviados} alerta(s) enviado(s)")

        # ⚠️ O `return` que existia no ramo saudavel virou `else` POR CAUSA DESTA
        # LINHA. Rodada saudavel e a rodada MAIS COMUM — se ela sai antes daqui,
        # o pulso so acontece quando ha problema, e o vigia externo passa a
        # alarmar todo dia em que esta tudo bem: exatamente o alarme invertido.
        _heartbeat()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
