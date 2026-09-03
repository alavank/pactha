"""
TCE-RS pelo PORTAL — o mesmo Tribunal, por um host que responde.

O `ingestion/tce_rs.py` baixa os CSV do `dados.tce.rs.gov.br`, e esse host
devolve **403 ao IP da VPS** desde 17/08/2026. Este coletor fala com **outro
host do mesmo Tribunal** — `portal.tce.rs.gov.br` — cuja API responde **sem
autenticacao nenhuma**, e entrega o MESMO acervo:

    Nova Palma   866 licitacoes (2007-2026) e 1.202 contratos
    CKAN         864 licitacoes             e 1.201 contratos

A diferenca sao dois registros novos de 31/08. **Nao e um subconjunto do dump
bloqueado; e o dump** — mais remessa, obra e medicao, que o CSV nao tinha.

⛔⛔ **E ESTE HOST TAMBEM RECUSA O IP DA VPS. A TASK NAO E CRIADA.** Medido em
03/09/2026 11:53 UTC, do proprio servidor: 403 nos quatro enderecos testados
(`qonws` e `obras`), com o **mesmo corpo** (199 bytes, pagina padrao "403
Forbidden") e o **mesmo tempo** (0,08-0,09 s) do CKAN — enquanto o
`che.sefaz.rs.gov.br` respondeu 200 em 0,35 s do mesmo IP no mesmo minuto. Nao
era "um host bloqueado": e **uma regra de borda para o dominio `tce.rs.gov.br`
inteiro**.

Este arquivo entra **pronto e desligado**, como o `tce_rs.py` e o `obrasgov.py`.
Quando a liberacao vier (`docs/fontes-rs/OFICIO-TCE-RS.md`), ligar e uma linha
no Coolify. Se rodar assim mesmo, grava `partial` com a nota — e **nunca trata
403 como "municipio sem licitacao"**.

⚠️ E ele roda de QUALQUER outro ponto: nao depende de credencial, so de IP nao
bloqueado. Uma carga inicial executada de conexao residencial contra o banco do
tenant enche a tela sem esperar o oficio — e as rodadas seguintes voltam a
depender dele.

Roda por Scheduled Task no worker de tenant com municipio do RS, ou a mao:
    python -u ingestion/tce_rs_portal.py           # coleta de verdade
    python -u ingestion/tce_rs_portal.py --dry     # busca e mostra, sem gravar

AS ARMADILHAS, todas medidas contra a fonte em 03/09/2026:

1. ⚠️⚠️ **A REMESSA "LicitaCon WEB" NAO E ENTREGA DO MUNICIPIO — E CARGA DO
   TCE.** Esta era a promessa mais valiosa do reconhecimento de ontem
   (`docs/fontes-rs/TCE-RS-APIS.md`), e ela **caiu na medicao**: nove orgaos de
   OITO tipos diferentes (prefeitura, autarquia, fundacao, consorcio, empresa
   publica, S/A, associacao, Ltda) tem, no mesmo periodo, a mesma data E o mesmo
   horario — 2026/7 e 10/08/2026 entre 05:12 e 05:19 para todos. Nova Palma e
   Santa Maria coincidem nos 19 meses conferidos. Uma prefeitura que atrasasse
   teria a data de uma que nao atrasou.

   A remessa **e-Validador** e envio de verdade (as quatro de Nova Palma em
   agosto/2025 sao de 15, 22, 27 e 29/08, e nenhum outro orgao tem essas datas)
   — mas quem registra direto no LicitaCon Web nao envia nenhuma, e Nova Palma
   parou de enviar em 2026.

   **Pontualidade se mede por outro caminho:** a defasagem entre `DT_ASSINATURA`
   e `DATA_INCLUSAO` do contrato. Medida em 25 contratos recentes de cada
   municipio: mediana de **1 dia** em Nova Palma e **5** em Santa Maria, nenhum
   acima de 30. Os dois estao em dia — e dizer isso e uma boa noticia, nao um
   alarme.

2. ⚠️ **`tp_situacao` e `origem` sao OBRIGATORIOS, e os valores estao no
   Swagger**: `A`=Em Andamento, `E`=Encerradas, `ALL`=Todas; `WEB`=LicitaCon
   Web, `VAL`=eValidador, `ALL`=Todos. O reconhecimento de ontem testou oito
   combinacoes inventadas, todas vazias, e concluiu que o endpoint nao servia.
   Servia: com `ALL/ALL` ele devolve o acervo inteiro.

3. ⚠️ **A LISTA NAO TEM VALOR. So o DETALHE tem** — e e uma requisicao por
   contrato, com 6.213 contratos em Santa Maria. Por isso o orcamento de tempo
   (`_Orcamento`): a rodada gasta ate `TCE_RS_PORTAL_ORCAMENTO_S` segundos
   buscando detalhe do que ainda nao tem, prioriza contrato vigente, e continua
   de onde parou na noite seguinte. Nunca estoura o timeout da task.

   **Medido em 400 detalhes seguidos (03/09/2026): 0,40 s cada, zero falha.**
   Com o orcamento default de 600 s isso da ~1.500 detalhes por rodada — Nova
   Palma (2.068 registros) fecha em duas e Santa Maria (11.503) em oito. A
   contagem e o valor de cada ano JA aparecem na tela desde a primeira rodada;
   o que chega aos poucos e o valor dos contratos antigos.

3b. ⚠️⚠️ **E O QUE TORNA ISSO POSSIVEL: O PORTAL RESPONDE 403 A PARTIR DA 201a
   REQUISICAO NA MESMA CONEXAO TCP.** Nao e o IP, nao e o cookie, nao e janela de
   tempo — e a conexao, e reconectar resolve na hora. A classe `Conexao` cuida
   disso sozinha; o isolamento do achado esta documentado nela.

   A primeira carga real de Nova Palma (03/09, seis passadas) rendeu **so ~180
   detalhes por passada** porque este arquivo classificava aquele 403 como
   bloqueio de IP e abandonava o municipio — seis vezes, cada uma refazendo as
   listas do zero. Com o reciclo, as mesmas 400 requisicoes passam sem um unico
   erro.

4. ⚠️⚠️ **VALOR DE LICITACAO NAO EXISTE NESTA API.** Nem na lista (15 campos),
   nem no detalhe (27), nem em endpoint nenhum do Swagger. `vl_licitacao` e
   `vl_homologado` so o CKAN tem — por isso o UPSERT daqui **nao menciona esses
   dois campos**, nem no INSERT nem no DO UPDATE: se o CKAN um dia for liberado
   e preencher, a rodada deste coletor **nao os apaga**. Os campos que ora vem e
   ora nao (os do detalhe) usam COALESCE pela mesma razao. E por isso os dois
   coletores escrevem na MESMA linha (mesma chave natural) em vez de duplicar.

5. ⚠️ **ORGAO INEXISTENTE DEVOLVE `[]` COM HTTP 200.** Vazio nao e erro — mas
   tambem nao e "o municipio nao licita". A unica leitura honesta de uma lista
   vazia e quando o orgao FOI encontrado no de-para; se nao foi, o municipio e
   pulado com nota, nunca gravado como zero.

6. ⚠️ **O CODIGO DO ORGAO NAO E O IBGE**, e agora tem fonte oficial:
   `licitacon_dominios.orgaos` casa `CD_MUNICIPIO_IBGE` x `CD_ORGAO` x `CNPJ`
   para os 1.344 orgaos do Estado. E melhor que a descoberta por slug que o
   `tce_rs.py` faz (que depende do CKAN bloqueado) e funciona mesmo com ele
   fora. Nova Palma = 53100, Santa Maria = 56900.

   ⚠️ E o filtro por IBGE traz TAMBEM a Camara (53101 / 56901), que **nao e o
   cliente**, e as autarquias (IPLAN, IPASSP em Santa Maria). Este coletor pega
   a **administracao direta do Executivo** — o orgao cujo nome comeca por "PM DE"
   —, a mesma separacao que o SICONFI e o CHE exigem. As demais entidades do
   municipio ficam registradas no log, para a decisao de incluir ou nao ser
   tomada com o numero na mao, e nao por esquecimento.

7. ⚠️ **A OBRA TRAZ A PLANILHA ORCAMENTARIA INTEIRA** — 217 itens, 148 KB, na
   obra 436 de Santa Maria. Ela NAO vai para o `raw_data`: o coletor a remove
   antes de gravar. Guardar 148 KB por obra para nunca ler nenhum item seria
   inflar o banco de cinco tenants por nada.

8. ⚠️ **DOIS PERCENTUAIS DE EXECUCAO, E ELES DIVERGEM.** Na obra 436,
   `PC_FINANCEIRO_EXEC` = 90,6% e `PC_EXECUTADO` (fisico) = 0,0. O orgao mede o
   pagamento e nao alimenta o avanco fisico. Mostrar um pelo outro inventaria
   execucao que ninguem declarou — os dois sao gravados separados.

9. ⚠️ **ZERO OBRA E RESULTADO LEGITIMO.** Santa Maria tem 120; Nova Palma, 0. O
   LicitaCon Obras e de 2024 e municipio pequeno pode nao ter obra sujeita a
   registro. Mesma disciplina do SISMOB.

O que este coletor NAO tenta: os endpoints REST de `/api/obras/v1/**` (dezenas
de chamadas por obra, para medicao, licenca, termo aditivo, foto). O Queryon
entrega tudo isso aninhado em `licitacon_obras.obra`, numa requisicao — e e de
la que sai a ORIGEM DO RECURSO, o elo entre a obra e o convenio que a pagou.
"""
import json
import logging
import os
import sys
import time
from datetime import date, datetime

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("tce_rs_portal")

BASE = "https://portal.tce.rs.gov.br/api/qonws/q"
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0 consulta publica TCE-RS)",
      "Accept": "application/json"}
FONTE = "tce_rs_portal"
UF = "RS"
TIMEOUT = 90

# Pausa entre requisicoes. O Tribunal responde em ~0,2s e nao publica limite;
# meio segundo e um quinto do que ele aguenta e ainda assim cabe no orcamento.
PAUSA = float(os.getenv("TCE_RS_PORTAL_PAUSA_S", "0.5"))
# Teto de tempo gasto com DETALHE (armadilha 3). O default cabe folgado num
# timeout de 1020s da Scheduled Task, junto com listas, remessas e obras.
ORCAMENTO_S = int(os.getenv("TCE_RS_PORTAL_ORCAMENTO_S", "600"))
# ⚠️ SUB-ORCAMENTO DAS OBRAS. O detalhe de UMA obra custa ~4,5 s (o payload traz
# a planilha orcamentaria inteira) contra 0,40 s do contrato — onze vezes mais.
# Sem teto proprio, as 120 obras de Santa Maria comiam nove dos quinze minutos
# de cada rodada e os contratos ficavam sem nada: seis rodadas renderam 84
# detalhes de contrato. Um terco do orcamento e o bastante para as obras
# entrarem em duas ou tres rodadas sem sequestrar as demais.
ORCAMENTO_OBRAS_S = int(os.getenv("TCE_RS_PORTAL_ORCAMENTO_OBRAS_S",
                                  str(max(60, ORCAMENTO_S // 3))))
# Por quantos dias o detalhe de uma obra e considerado fresco. Obra muda
# (medicao, aditivo, paralisacao), mas devagar.
OBRA_FRESCOR_D = int(os.getenv("TCE_RS_PORTAL_OBRA_FRESCOR_D", "7"))
# Nao ha teto de `limit` na fonte (5.000 devolveu 1.202 sem reclamar), mas
# pagina grande demais so aumenta o custo de um retry.
PAGINA = 1000
# Quatro e nao tres por causa da queda de conexao: numa rodada de milhares de
# requisicoes ela acontece, e gastar duas tentativas com ela ainda deixa duas
# para o que for de verdade problema da fonte.
TENTATIVAS = 4
# Quantos exercicios de remessa conferir. Dois cobrem o ano corrente e o
# anterior — o suficiente para dizer por qual via o municipio opera.
ANOS_REMESSA = 2

NOTA_BLOQUEIO = (
    "portal.tce.rs.gov.br recusou este IP com 403, como o dados.tce.rs.gov.br. "
    "Medido do proprio servidor em 03/09/2026: mesmo corpo e mesmo tempo nos "
    "dois hosts, com outros portais estaduais respondendo 200 no mesmo minuto — "
    "e regra de borda do dominio tce.rs.gov.br inteiro. NAO e ausencia de dado: "
    "Nova Palma tem 866 licitacoes e 1.202 contratos publicados. A saida e a "
    "liberacao do IP (docs/fontes-rs/OFICIO-TCE-RS.md), ou coletar de outro "
    "ponto de rede.")


class Bloqueado(Exception):
    """O host recusou o IP (403/451). Nao e falha de parser nem dado ausente."""


class Conexao:
    """Cliente HTTP que se RECICLA — e a peca que torna a coleta grande viavel.

    ⚠️⚠️ **O PORTAL RESPONDE 403 A PARTIR DA 201a REQUISICAO NA MESMA CONEXAO
    TCP.** Medido em 03/09/2026, tres vezes, e isolado assim:

        requisicao 201 da mesma conexao ............ 403
        mesma conexao, logo apos ................... 403
        MESMOS cookies limpos, MESMA conexao ....... 403   <- nao e sessao
        conexao NOVA (mesmo IP, mesmo segundo) ..... 200   <- e a conexao

    Nao e cookie (`JSESSIONID` limpo nao muda nada), nao e o IP (a conexao nova
    responde 200 no mesmo segundo) e nao e janela de tempo (esperar nao
    resolve; reconectar resolve na hora).

    Foi isso que fez a primeira carga de Nova Palma render **so ~180 detalhes
    por rodada**: o coletor tomava o 403, o classificava como bloqueio de IP e
    abandonava o municipio inteiro — seis vezes seguidas, cada uma recomecando
    do zero as listas. Com o reciclo, a mesma carga cabe numa rodada.

    ⚠️ E a distincao com o bloqueio DE VERDADE fica nitida, que e o que importa
    para nao mentir no `ingestion_log`: 403 que SOME ao reconectar e limite de
    conexao; 403 que PERSISTE numa conexao nova e bloqueio de IP (o caso da
    VPS, onde a primeira requisicao ja falha)."""

    # 150 e nao 200: margem para as requisicoes que o `_get` repete por conta de
    # retry, que tambem contam do lado de la.
    LIMITE = int(os.getenv("TCE_RS_PORTAL_REQ_POR_CONEXAO", "150"))

    def __init__(self):
        self.n = 0
        self.reciclos = 0
        self._c = self._novo()

    @staticmethod
    def _novo() -> httpx.Client:
        return httpx.Client(follow_redirects=True, headers=UA, timeout=TIMEOUT)

    def reciclar(self) -> None:
        try:
            self._c.close()
        except Exception:
            pass
        self._c = self._novo()
        self.n = 0
        self.reciclos += 1

    def get(self, url, **kwargs):
        if self.n >= self.LIMITE:
            self.reciclar()
        self.n += 1
        return self._c.get(url, **kwargs)

    def close(self) -> None:
        try:
            self._c.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _get(client: "Conexao", recurso: str, **params):
    """GET no Queryon, com backoff. Devolve lista ou dict ja decodificado.

    ⚠️ 403/451 viram `Bloqueado` e NAO sao retentados: bloqueio de borda nao
    passa com espera (o Obras.gov.br ensinou isso — 429 em 0,05s tres vezes).

    ⚠️⚠️ **O SERVIDOR DERRUBA A CONEXAO EM SEQUENCIA LONGA**, e isso NAO e erro
    de status: e `RemoteProtocolError: Server disconnected without sending a
    response`, medido em 03/09/2026 depois de algumas dezenas de requisicoes na
    mesma conexao keep-alive. Uma rodada real faz milhares delas — sem este
    ramo, a primeira queda mata o municipio inteiro e o log culpa a fonte por
    "estar fora do ar". O retry reabre a conexao, que e o que resolve."""
    url = f"{BASE}/{recurso}.json"
    espera = 2.0
    for tentativa in range(TENTATIVAS):
        try:
            r = client.get(url, params=params, headers=UA, timeout=TIMEOUT)
        except httpx.TransportError as e:
            if tentativa == TENTATIVAS - 1:
                raise
            log.warning("  %s: conexao caiu (%s), reabrindo em %.0fs",
                        recurso, type(e).__name__, espera)
            time.sleep(espera)
            espera *= 2
            continue
        if r.status_code in (403, 451):
            # ⚠️ AQUI MORAM DOIS 403 DIFERENTES, e trata-los igual foi o que
            # fez a carga de 03/09 render um sexto do que podia (ver `Conexao`).
            # O de LIMITE DE CONEXAO some ao reconectar; o de BLOQUEIO DE IP
            # persiste. A unica forma honesta de saber qual e: reconectar e
            # perguntar de novo.
            if hasattr(client, "reciclar") and tentativa < TENTATIVAS - 1:
                log.info("  %s: HTTP %s — reciclando a conexao para distinguir "
                         "limite de conexao de bloqueio de IP", recurso,
                         r.status_code)
                client.reciclar()
                continue
            raise Bloqueado(f"HTTP {r.status_code} em {recurso}")
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504) and tentativa < TENTATIVAS - 1:
            log.warning("  %s: HTTP %s, nova tentativa em %.0fs",
                        recurso, r.status_code, espera)
            time.sleep(espera)
            espera *= 2
            continue
        r.raise_for_status()
    return []


def _pagina_tudo(client: "Conexao", recurso: str, **params) -> list[dict]:
    """Percorre offset ate a fonte devolver menos que uma pagina cheia."""
    fora, offset = [], 0
    while True:
        lote = _get(client, recurso, limit=PAGINA, offset=offset, **params)
        if not isinstance(lote, list):
            break
        fora.extend(lote)
        if len(lote) < PAGINA:
            break
        offset += PAGINA
        time.sleep(PAUSA)
    return fora


# ---------------------------------------------------------------------------
# Conversores. Nao reusa `ingestion/base.py`: aquele arquivo e codigo morto e o
# `parse_decimal_br` dele trata ponto como separador de MILHAR — aqui o JSON ja
# vem com numero nativo.
# ---------------------------------------------------------------------------
def _dec(v):
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v):
    if v is None or str(v).strip() == "":
        return None
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _txt(v, limite=None):
    s = str(v).strip() if v is not None else ""
    if not s:
        return None
    return s[:limite] if limite else s


def _dt(v):
    """'2026-08-31 15:09:50' -> datetime (o formato unico desta API)."""
    if not v or not str(v).strip():
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:len(fmt) + 2].strip(), fmt)
        except ValueError:
            continue
    return None


def _data(v) -> date | None:
    d = _dt(v)
    return d.date() if d else None


def _tp_documento(doc: str | None) -> str | None:
    """J ou F pelo TAMANHO — a API manda o numero sem dizer qual e.

    O CSV do CKAN tinha `TP_DOCUMENTO` proprio; aqui so vem
    `CPF_CNPJ_CONTRATADO`. 14 digitos = CNPJ, 11 = CPF; qualquer outra coisa
    fica NULL em vez de chutar."""
    s = "".join(c for c in (doc or "") if c.isdigit())
    return {14: "J", 11: "F"}.get(len(s))


# ---------------------------------------------------------------------------
# Fonte
# ---------------------------------------------------------------------------
def orgaos_do_municipio(client: "Conexao", ibge: str) -> dict:
    """De-para oficial por IBGE (armadilha 6).

    Devolve {'executivo': {...} | None, 'outros': [...]}. O executivo e a
    administracao direta cujo nome comeca por 'PM DE' — a Camara ('CM DE') tem
    codigo proprio e nao e o cliente."""
    todos = _get(client, "licitacon_dominios.orgaos")
    do_municipio = [o for o in (todos or [])
                    if str(o.get("CD_MUNICIPIO_IBGE") or "") == str(ibge)]
    executivo = None
    outros = []
    for o in do_municipio:
        nome = (o.get("NOME") or "").upper()
        eh_direta = (o.get("TIPO") or "").upper().startswith("ADMINISTRA")
        if eh_direta and nome.startswith("PM DE"):
            # Se houver mais de um (nao ha, nos 1.344 conferidos), fica o ATIVO.
            if executivo is None or o.get("SITUACAO_ORGAO") == "ATIVO":
                executivo = o
        else:
            outros.append(o)
    return {"executivo": executivo, "outros": outros}


def licitacoes(client: "Conexao", cd_orgao: str) -> list[dict]:
    return _pagina_tudo(client, "licitacon.licitacoes", cd_orgao=cd_orgao,
                        tp_situacao="ALL", origem="ALL")


def contratos(client: "Conexao", cd_orgao: str) -> list[dict]:
    return _pagina_tudo(client, "licitacon.contratos", cd_orgao=cd_orgao,
                        tp_situacao="ALL", origem="ALL")


def _um(resposta) -> dict:
    """A API ora devolve o objeto, ora uma lista de um. Normaliza.

    ⚠️ DEVOLVE `{}` E NUNCA `None` quando vem vazio, e a diferenca e o que
    impede um laco eterno. A fonte responde **HTTP 200 com `{}`** para
    registros que ela simplesmente nao detalha — 134 contratos de Santa Maria,
    de 2015 a 2026, situacoes e tipos variados. Isso e uma RESPOSTA, nao uma
    falha: ela diz "perguntei, e nao ha".

    Enquanto `{}` virava `None`, o coletor nao distinguia isso de "ainda nao
    perguntei", nunca gravava `detalhe_da_versao` e os mesmos 134 voltavam a
    fila em toda rodada — "contratos: 0 de 134", quatro rodadas seguidas,
    ~2 min cada, para sempre. Falha de rede continua levantando excecao, entao
    ela nunca chega aqui como vazio."""
    if isinstance(resposta, list):
        return resposta[0] if resposta else {}
    return resposta or {}


def licitacao_detalhe(client, cd_orgao, modalidade, nr, ano) -> dict | None:
    return _um(_get(client, "licitacon.licitacao", cd_orgao=cd_orgao,
                    cd_tipo_modalidade=modalidade, nr_licitacao=nr,
                    ano_licitacao=ano))


def contrato_detalhe(client, cd_orgao, instrumento, nr, ano) -> dict | None:
    return _um(_get(client, "licitacon.contrato", cd_orgao=cd_orgao,
                    tp_instrumento=instrumento, nr_contrato=nr,
                    ano_contrato=ano))


def remessas(client, cd_orgao, ano, periodo) -> list[dict]:
    return _get(client, "licitacon.remessas", cd_orgao=cd_orgao,
                ano_exercicio=ano, periodo=periodo, limit=50) or []


def obras(client, cd_orgao) -> list[dict]:
    return _pagina_tudo(client, "licitacon_obras.obras_por_orgao",
                        cd_orgao=cd_orgao)


def obra_detalhe(client, id_obra) -> dict | None:
    return _um(_get(client, "licitacon_obras.obra", id_obra=id_obra))


def _raw_enxuto(obra: dict) -> dict:
    """Tira a planilha orcamentaria do que vai para `raw_data` (armadilha 7)."""
    copia = dict(obra)
    lotes = []
    for lote in (copia.get("PLANILHA_CONTRATUAL_LOTES") or []):
        magro = {k: v for k, v in lote.items()
                 if k != "PLANILHA_CONTRATUAL_ITENS"}
        magro["QT_ITENS_PLANILHA"] = len(lote.get("PLANILHA_CONTRATUAL_ITENS") or [])
        lotes.append(magro)
    if lotes or "PLANILHA_CONTRATUAL_LOTES" in copia:
        copia["PLANILHA_CONTRATUAL_LOTES"] = lotes
    return copia


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------
# ⚠️ COALESCE em vl_licitacao/vl_homologado (armadilha 4): esta rodada nao tem
# esses valores e nao pode apagar os que o CKAN tenha deixado.
_SQL_LIC = """
INSERT INTO tce_rs_licitacoes (
    municipio_id, cd_orgao, nm_orgao, nr_licitacao, ano_licitacao,
    cd_tipo_modalidade, nr_processo, cd_tipo_fase_atual, ds_objeto,
    dt_abertura, link_licitacon, tp_situacao, ds_situacao, aplic_origem,
    incluido_na_fonte, atualizado_na_fonte, detalhe_da_versao, raw_data,
    atualizado_em)
VALUES (%(mid)s, %(orgao)s, %(nm)s, %(nr)s, %(ano)s, %(mod)s, %(proc)s,
        %(fase)s, %(obj)s, %(dt_ab)s, %(link)s, %(tp_sit)s, %(ds_sit)s,
        %(origem)s, %(incl)s, %(atu)s, %(versao)s, %(raw)s::jsonb, NOW())
ON CONFLICT (cd_orgao, nr_licitacao, ano_licitacao, cd_tipo_modalidade)
DO UPDATE SET
    municipio_id = EXCLUDED.municipio_id,
    nm_orgao = coalesce(EXCLUDED.nm_orgao, tce_rs_licitacoes.nm_orgao),
    nr_processo = coalesce(EXCLUDED.nr_processo, tce_rs_licitacoes.nr_processo),
    cd_tipo_fase_atual = EXCLUDED.cd_tipo_fase_atual,
    ds_objeto = EXCLUDED.ds_objeto,
    dt_abertura = coalesce(EXCLUDED.dt_abertura, tce_rs_licitacoes.dt_abertura),
    link_licitacon = EXCLUDED.link_licitacon,
    tp_situacao = EXCLUDED.tp_situacao, ds_situacao = EXCLUDED.ds_situacao,
    aplic_origem = EXCLUDED.aplic_origem,
    incluido_na_fonte = EXCLUDED.incluido_na_fonte,
    atualizado_na_fonte = EXCLUDED.atualizado_na_fonte,
    detalhe_da_versao = coalesce(EXCLUDED.detalhe_da_versao,
                                 tce_rs_licitacoes.detalhe_da_versao),
    raw_data = EXCLUDED.raw_data,
    atualizado_em = NOW()
"""

_SQL_CON = """
INSERT INTO tce_rs_contratos (
    municipio_id, cd_orgao, nm_orgao, nr_contrato, ano_contrato, tp_instrumento,
    ds_objeto, link_licitacon, tp_situacao, ds_situacao, aplic_origem,
    nm_contratado, tp_documento, nr_documento, vl_contrato, vl_atual,
    dt_assinatura, dt_inicio_vigencia, dt_final_vigencia, licitacao_origem,
    incluido_na_fonte, atualizado_na_fonte, detalhe_da_versao, raw_data,
    atualizado_em)
VALUES (%(mid)s, %(orgao)s, %(nm)s, %(nr)s, %(ano)s, %(tp)s, %(obj)s, %(link)s,
        %(tp_sit)s, %(ds_sit)s, %(origem)s, %(contratado)s, %(tp_doc)s,
        %(nr_doc)s, %(vl)s, %(vl_atual)s, %(dt_ass)s, %(dt_ini)s, %(dt_fim)s,
        %(lic_origem)s, %(incl)s, %(atu)s, %(versao)s, %(raw)s::jsonb, NOW())
ON CONFLICT (cd_orgao, nr_contrato, ano_contrato, tp_instrumento)
DO UPDATE SET
    municipio_id = EXCLUDED.municipio_id,
    nm_orgao = coalesce(EXCLUDED.nm_orgao, tce_rs_contratos.nm_orgao),
    ds_objeto = EXCLUDED.ds_objeto,
    link_licitacon = EXCLUDED.link_licitacon,
    tp_situacao = EXCLUDED.tp_situacao, ds_situacao = EXCLUDED.ds_situacao,
    aplic_origem = EXCLUDED.aplic_origem,
    -- ⚠️ Os campos abaixo so existem no DETALHE. Uma rodada que so atualizou a
    -- lista traz NULL neles, e COALESCE impede que ela apague o valor que a
    -- rodada anterior ja tinha buscado.
    nm_contratado = coalesce(EXCLUDED.nm_contratado,
                             tce_rs_contratos.nm_contratado),
    tp_documento = coalesce(EXCLUDED.tp_documento, tce_rs_contratos.tp_documento),
    nr_documento = coalesce(EXCLUDED.nr_documento, tce_rs_contratos.nr_documento),
    vl_contrato = coalesce(EXCLUDED.vl_contrato, tce_rs_contratos.vl_contrato),
    vl_atual = coalesce(EXCLUDED.vl_atual, tce_rs_contratos.vl_atual),
    dt_assinatura = coalesce(EXCLUDED.dt_assinatura,
                             tce_rs_contratos.dt_assinatura),
    dt_inicio_vigencia = coalesce(EXCLUDED.dt_inicio_vigencia,
                                  tce_rs_contratos.dt_inicio_vigencia),
    dt_final_vigencia = coalesce(EXCLUDED.dt_final_vigencia,
                                 tce_rs_contratos.dt_final_vigencia),
    licitacao_origem = coalesce(EXCLUDED.licitacao_origem,
                                tce_rs_contratos.licitacao_origem),
    incluido_na_fonte = EXCLUDED.incluido_na_fonte,
    atualizado_na_fonte = EXCLUDED.atualizado_na_fonte,
    detalhe_da_versao = coalesce(EXCLUDED.detalhe_da_versao,
                                 tce_rs_contratos.detalhe_da_versao),
    raw_data = EXCLUDED.raw_data,
    atualizado_em = NOW()
"""

_SQL_REM = """
INSERT INTO tce_rs_remessas (
    municipio_id, cd_orgao, ano_exercicio, periodo_mes, tipo_remessa,
    cod_barras_rve, dt_recebimento, cd_situacao, ds_situacao, nome_responsavel,
    cargo_responsavel, raw_data, atualizado_em)
VALUES (%(mid)s, %(orgao)s, %(ano)s, %(periodo)s, %(tipo)s, %(rve)s, %(dt)s,
        %(cd_sit)s, %(ds_sit)s, %(resp)s, %(cargo)s, %(raw)s::jsonb, NOW())
ON CONFLICT (cd_orgao, ano_exercicio, periodo_mes, cod_barras_rve)
DO UPDATE SET
    municipio_id = EXCLUDED.municipio_id,
    tipo_remessa = EXCLUDED.tipo_remessa,
    dt_recebimento = EXCLUDED.dt_recebimento,
    cd_situacao = EXCLUDED.cd_situacao, ds_situacao = EXCLUDED.ds_situacao,
    nome_responsavel = EXCLUDED.nome_responsavel,
    cargo_responsavel = EXCLUDED.cargo_responsavel,
    raw_data = EXCLUDED.raw_data, atualizado_em = NOW()
"""

_SQL_OBRA = """
INSERT INTO tce_rs_obras (
    municipio_id, id_obra, cd_orgao, nm_orgao, ds_objeto, endereco, bairro,
    ds_tipo_obra, tp_situacao_obra, ds_situacao_obra, nr_contrato, ano_contrato,
    tp_instrumento, nm_contratado, nr_doc_contratado, dt_inicio_vigencia,
    dt_fim_vigencia, vl_inicial, vl_atual, vl_total_medido, vl_saldo,
    pc_financeiro_exec, pc_executado, dt_evento_paralisacao,
    ds_motivo_paralisacao, dt_previsao_reinicio, qt_medicoes, dt_ultima_medicao,
    qt_termos_aditivos, raw_data, atualizado_em)
VALUES (%(mid)s, %(id_obra)s, %(orgao)s, %(nm_orgao)s, %(obj)s, %(end)s,
        %(bairro)s, %(tipo)s, %(tp_sit)s, %(ds_sit)s, %(nr_con)s, %(ano_con)s,
        %(tp_inst)s, %(contratado)s, %(doc)s, %(dt_ini)s, %(dt_fim)s, %(vl_ini)s,
        %(vl_atual)s, %(vl_medido)s, %(vl_saldo)s, %(pc_fin)s, %(pc_exec)s,
        %(dt_paral)s, %(motivo)s, %(dt_reinicio)s, %(qt_med)s, %(dt_med)s,
        %(qt_adit)s, %(raw)s::jsonb, NOW())
ON CONFLICT (id_obra) DO UPDATE SET
    municipio_id = EXCLUDED.municipio_id, cd_orgao = EXCLUDED.cd_orgao,
    nm_orgao = coalesce(EXCLUDED.nm_orgao, tce_rs_obras.nm_orgao),
    ds_objeto = EXCLUDED.ds_objeto, endereco = EXCLUDED.endereco,
    bairro = EXCLUDED.bairro, ds_tipo_obra = EXCLUDED.ds_tipo_obra,
    tp_situacao_obra = EXCLUDED.tp_situacao_obra,
    ds_situacao_obra = EXCLUDED.ds_situacao_obra,
    nr_contrato = coalesce(EXCLUDED.nr_contrato, tce_rs_obras.nr_contrato),
    ano_contrato = coalesce(EXCLUDED.ano_contrato, tce_rs_obras.ano_contrato),
    tp_instrumento = coalesce(EXCLUDED.tp_instrumento,
                              tce_rs_obras.tp_instrumento),
    nm_contratado = coalesce(EXCLUDED.nm_contratado, tce_rs_obras.nm_contratado),
    nr_doc_contratado = coalesce(EXCLUDED.nr_doc_contratado,
                                 tce_rs_obras.nr_doc_contratado),
    dt_inicio_vigencia = coalesce(EXCLUDED.dt_inicio_vigencia,
                                  tce_rs_obras.dt_inicio_vigencia),
    dt_fim_vigencia = coalesce(EXCLUDED.dt_fim_vigencia,
                               tce_rs_obras.dt_fim_vigencia),
    vl_inicial = coalesce(EXCLUDED.vl_inicial, tce_rs_obras.vl_inicial),
    vl_atual = coalesce(EXCLUDED.vl_atual, tce_rs_obras.vl_atual),
    vl_total_medido = coalesce(EXCLUDED.vl_total_medido,
                               tce_rs_obras.vl_total_medido),
    vl_saldo = coalesce(EXCLUDED.vl_saldo, tce_rs_obras.vl_saldo),
    pc_financeiro_exec = coalesce(EXCLUDED.pc_financeiro_exec,
                                  tce_rs_obras.pc_financeiro_exec),
    pc_executado = coalesce(EXCLUDED.pc_executado, tce_rs_obras.pc_executado),
    -- ⚠️ Paralisacao SEM coalesce: obra que voltou a andar tem estes campos
    -- limpos na fonte, e mante-los seria acusar de parada uma obra em execucao.
    dt_evento_paralisacao = EXCLUDED.dt_evento_paralisacao,
    ds_motivo_paralisacao = EXCLUDED.ds_motivo_paralisacao,
    dt_previsao_reinicio = EXCLUDED.dt_previsao_reinicio,
    qt_medicoes = coalesce(EXCLUDED.qt_medicoes, tce_rs_obras.qt_medicoes),
    dt_ultima_medicao = coalesce(EXCLUDED.dt_ultima_medicao,
                                 tce_rs_obras.dt_ultima_medicao),
    qt_termos_aditivos = coalesce(EXCLUDED.qt_termos_aditivos,
                                  tce_rs_obras.qt_termos_aditivos),
    raw_data = coalesce(EXCLUDED.raw_data, tce_rs_obras.raw_data),
    atualizado_em = NOW()
"""

_SQL_REC = """
INSERT INTO tce_rs_obras_recursos (
    municipio_id, id_obra, id_origem_recurso, cod_tp_recurso, ds_tp_recurso,
    ds_fonte_recurso, ds_convenio_contrato, data_recurso, vl_recurso,
    vl_contrapartida, raw_data, atualizado_em)
VALUES (%(mid)s, %(id_obra)s, %(id_rec)s, %(cod)s, %(ds_tp)s, %(fonte)s,
        %(convenio)s, %(data)s, %(vl)s, %(contrapartida)s, %(raw)s::jsonb, NOW())
ON CONFLICT (id_obra, id_origem_recurso) DO UPDATE SET
    municipio_id = EXCLUDED.municipio_id,
    cod_tp_recurso = EXCLUDED.cod_tp_recurso,
    ds_tp_recurso = EXCLUDED.ds_tp_recurso,
    ds_fonte_recurso = EXCLUDED.ds_fonte_recurso,
    ds_convenio_contrato = EXCLUDED.ds_convenio_contrato,
    data_recurso = EXCLUDED.data_recurso, vl_recurso = EXCLUDED.vl_recurso,
    vl_contrapartida = EXCLUDED.vl_contrapartida,
    raw_data = EXCLUDED.raw_data, atualizado_em = NOW()
"""


# ---------------------------------------------------------------------------
# Montagem das linhas
# ---------------------------------------------------------------------------
def linha_licitacao(mid: int, orgao_nome: str | None, r: dict,
                    det: dict | None = None) -> dict:
    """Lista + (opcional) detalhe. `nr_processo` e `dt_abertura` so vem no
    detalhe — por isso os dois entram por `det` e ficam NULL sem ele."""
    d = det or {}
    return {
        "mid": mid,
        "orgao": _txt(r.get("CD_ORGAO"), 10),
        "nm": _txt(d.get("ORGAO") or orgao_nome),
        "nr": _txt(r.get("NR_LICITACAO"), 20),
        "ano": _int(r.get("ANO_LICITACAO")),
        "mod": _txt(r.get("CD_TIPO_MODALIDADE"), 10),
        "proc": _txt(d.get("NR_PROCESSO"), 20),
        "fase": _txt(r.get("CD_TIPO_FASE_ATUAL"), 10),
        "obj": _txt(r.get("DS_OBJETO")),
        "dt_ab": _data(d.get("DT_ABERTURA")),
        "link": _txt(r.get("LINK_CIDADAO")),
        "tp_sit": _txt(r.get("TP_SITUACAO"), 4),
        "ds_sit": _txt(r.get("DS_SITUACAO")),
        "origem": _txt(r.get("APLIC_ORIGEM"), 8),
        "incl": _dt(r.get("DATA_INCLUSAO")),
        "atu": _dt(r.get("DATA_ATUALIZACAO")),
        "versao": _dt(r.get("DATA_ATUALIZACAO")) if det is not None else None,
        "raw": json.dumps({**r, **d}, ensure_ascii=False),
    }


def linha_contrato(mid: int, orgao_nome: str | None, r: dict,
                   det: dict | None = None) -> dict:
    d = det or {}
    doc = _txt(d.get("CPF_CNPJ_CONTRATADO"), 20)
    return {
        "mid": mid,
        "orgao": _txt(r.get("CD_ORGAO"), 10),
        "nm": _txt(d.get("DS_ORGAO") or orgao_nome),
        "nr": _txt(r.get("NR_CONTRATO"), 20),
        "ano": _int(r.get("ANO_CONTRATO")),
        "tp": _txt(r.get("TP_INSTRUMENTO"), 4) or "C",
        "obj": _txt(r.get("DS_OBJETO")),
        "link": _txt(r.get("LINK_CIDADAO")),
        "tp_sit": _txt(r.get("TP_SITUACAO_CONTRATO"), 4),
        "ds_sit": _txt(r.get("DS_SITUACAO")),
        "origem": _txt(r.get("APLIC_ORIGEM"), 8),
        "contratado": _txt(d.get("CONTRATADO")),
        "tp_doc": _tp_documento(doc),
        "nr_doc": doc,
        # VALOR_INICIAL vai para `vl_contrato` porque e o que o CSV do CKAN
        # gravava nessa coluna e o que a tela ja soma. O de depois dos aditivos
        # tem coluna propria.
        "vl": _dec(d.get("VALOR_INICIAL")),
        "vl_atual": _dec(d.get("VALOR_ATUAL")),
        "dt_ass": _data(d.get("DT_ASSINATURA")),
        "dt_ini": _data(d.get("DT_INICIO_VIGENCIA")),
        "dt_fim": _data(d.get("DT_FINAL_VIGENCIA")),
        "lic_origem": _txt(d.get("LICITACAO_ORIGEM")),
        "incl": _dt(r.get("DATA_INCLUSAO")),
        "atu": _dt(r.get("DATA_ATUALIZACAO")),
        "versao": _dt(r.get("DATA_ATUALIZACAO")) if det is not None else None,
        "raw": json.dumps({**r, **d}, ensure_ascii=False),
    }


def linha_remessa(mid: int, r: dict) -> dict:
    return {
        "mid": mid,
        "orgao": _txt(r.get("CD_ORGAO"), 10),
        "ano": _int(r.get("ANO_EXERCICIO")),
        "periodo": _int(r.get("PERIODO_MES")),
        "tipo": _txt(r.get("TIPO_REMESSA")) or "?",
        "rve": _txt(r.get("COD_BARRAS_RVE"), 32) or "-",
        "dt": _dt(r.get("DT_RECEBIMENTO")),
        "cd_sit": _txt(r.get("CD_SITUACAO_REMESSA"), 4),
        "ds_sit": _txt(r.get("DS_SITUACAO_REMESSA")),
        "resp": _txt(r.get("NOME_REPONSAVEL_ORGAO")),   # typo e da fonte
        "cargo": _txt(r.get("DS_CARGO_RESPONSAVEL")),
        # As listas LICITACOES/CONTRATOS vieram vazias em todos os 19 meses
        # conferidos nos dois municipios; guardar o objeto inteiro e barato e
        # deixa a porta aberta se um dia vierem preenchidas.
        "raw": json.dumps(r, ensure_ascii=False),
    }


def _contrato_da_obra(o: dict) -> tuple[int | None, int | None, str | None]:
    """'Contrato 122/2024' -> (122, 2024, 'C'). O elo com `tce_rs_contratos`.

    ⚠️ O Queryon manda o contrato como TEXTO ('DS_CONTRATO'), nao como os tres
    campos da chave. Quando o texto nao casa com o formato, os tres voltam NULL
    — a obra entra sem o elo, que e melhor que um elo inventado."""
    ds = (o.get("DS_CONTRATO") or "").strip()
    if not ds:
        return None, None, None
    partes = ds.replace("/", " ").split()
    numeros = [p for p in partes if p.isdigit()]
    if len(numeros) < 2:
        return None, None, None
    nr, ano = _int(numeros[-2]), _int(numeros[-1])
    if not ano or ano < 1990 or ano > 2100:
        return None, None, None
    # A primeira palavra e o tipo por extenso ("Contrato", "Ata"...). So o
    # contrato tem codigo estavel; os demais ficam sem, para nao chutar.
    tp = "C" if ds.upper().startswith("CONTRATO") else None
    return nr, ano, tp


def linha_obra(mid: int, r: dict, det: dict | None = None) -> dict:
    d = det or {}
    nr_con, ano_con, tp_inst = _contrato_da_obra({**r, **d})
    medicoes = d.get("MEDICOES") or []
    datas_med = [_data(m.get("PERIODO_FINAL")) for m in medicoes]
    datas_med = [x for x in datas_med if x]
    return {
        "mid": mid,
        "id_obra": _int(r.get("ID_OBRA")),
        "orgao": _txt(r.get("CD_ORGAO"), 10),
        "nm_orgao": _txt(r.get("NM_ORGAO")),
        "obj": _txt(d.get("DS_OBJETO") or r.get("DS_OBJETO")),
        "end": _txt(d.get("ENDERECO") or r.get("ENDERECO")),
        "bairro": _txt(r.get("BAIRRO")),
        "tipo": _txt(r.get("DS_TIPO_OBRA")),
        "tp_sit": _txt(d.get("TP_SITUACAO_OBRA") or r.get("TP_SITUACAO_OBRA"), 8),
        "ds_sit": _txt(d.get("DS_TP_SITUACAO_OBRA") or r.get("DS_TP_SITUACAO_OBRA")),
        "nr_con": nr_con, "ano_con": ano_con, "tp_inst": tp_inst,
        "contratado": _txt(d.get("NM_CONTRATADO") or r.get("NM_CONTRATADO")),
        "doc": _txt(d.get("NR_DOC_CONTRATADO") or r.get("NR_DOC_CONTRATADO"), 20),
        "dt_ini": _data(d.get("DT_INICIO_VIGENCIA") or r.get("DT_INICIO_EXECUCAO")),
        "dt_fim": _data(d.get("DT_FIM_VIGENCIA") or r.get("DT_TERMINO_EXECUCAO")),
        # ⚠️ `is not None` e nao `or`: valor ZERO e falsy, e um `or` faria a obra
        # de valor zero cair no campo da lista — ou virar NULL — em silencio.
        "vl_ini": _dec(d["VL_INICIAL"] if d.get("VL_INICIAL") is not None
                       else r.get("VL_INICIAL")),
        "vl_atual": _dec(d.get("VL_ATUAL")),
        "vl_medido": _dec(d.get("VL_TOTAL_MEDIDO")),
        "vl_saldo": _dec(d.get("VL_SALDO_CONTRATUAL")),
        "pc_fin": _dec(d.get("PC_FINANCEIRO_EXEC")),
        "pc_exec": _dec(d.get("PC_EXECUTADO")),
        "dt_paral": _data(d.get("DT_EVENTO_PARALISACAO")),
        "motivo": _txt(d.get("DS_MOTIVO_PARALISACAO") or d.get("DS_MOTIVO_OUTRO")),
        "dt_reinicio": _data(d.get("DT_PREVISAO_REINICIO")),
        "qt_med": len(medicoes) if det is not None else None,
        "dt_med": max(datas_med) if datas_med else None,
        "qt_adit": len(d.get("TERMOS_ADITIVOS") or []) if det is not None else None,
        "raw": json.dumps(_raw_enxuto({**r, **d}), ensure_ascii=False) if det is not None else None,
    }


def linha_recurso(mid: int, id_obra: int, r: dict) -> dict:
    return {
        "mid": mid,
        "id_obra": id_obra,
        "id_rec": _int(r.get("ID_ORIGEM_RECURSO")),
        "cod": _txt(r.get("COD_TP_RECURSO"), 8),
        "ds_tp": _txt(r.get("DS_TP_RECURSO")),
        "fonte": _txt(r.get("DS_FONTE_RECURSO")),
        "convenio": _txt(r.get("DS_CONVENIO_CONTRATO")),
        "data": _data(r.get("DATA")),
        "vl": _dec(r.get("VL_RECURSO")),
        "contrapartida": _dec(r.get("VL_CONTRATAPARTIDA")),  # typo e da fonte
        "raw": json.dumps(r, ensure_ascii=False),
    }


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------
def _alvos(cur) -> list[dict]:
    cur.execute("""
        SELECT id, nome, uf, coalesce(ibge_code, ''), coalesce(tce_orgao_codigo, '')
          FROM municipios
         WHERE active AND upper(coalesce(uf, '')) = %s
         ORDER BY nome
    """, (UF,))
    return [{"id": r[0], "nome": r[1], "uf": r[2],
             "ibge": (r[3] or "").strip(), "orgao": (r[4] or "").strip()}
            for r in cur.fetchall()]


def _gravar_em_lote(cur, sql: str, linhas: list[dict], pagina: int = 200) -> None:
    """UPSERT de muitas linhas com poucos ida-e-volta.

    ⚠️ `execute_batch` e nao `executemany`: o do psycopg2 continua mandando uma
    instrucao por linha. Se a extensao nao estiver disponivel, cai no laco
    simples — mais lento, nunca errado."""
    if not linhas:
        return
    try:
        from psycopg2.extras import execute_batch
    except ImportError:
        for linha in linhas:
            cur.execute(sql, linha)
        return
    execute_batch(cur, sql, linhas, page_size=pagina)


def _obras_com_detalhe_fresco(cur, municipio_id: int) -> set:
    """Obras cujo detalhe ja temos e ainda vale — nao precisam ser rebuscadas.

    ⚠️ `raw_data IS NOT NULL` E a marca de "tem detalhe": o coletor so grava o
    raw quando buscou o detalhe (a linha vinda so da lista grava NULL ali). Nao
    precisou de coluna nova para isso.

    ⚠️ E o frescor tem prazo porque OBRA MUDA: medicao nova, aditivo, ordem de
    paralisacao. `TCE_RS_PORTAL_OBRA_FRESCOR_D` dias depois, ela volta para a
    fila — devagar o bastante para nao competir com os contratos, frequente o
    bastante para a tela nao envelhecer."""
    cur.execute("""
        SELECT id_obra FROM tce_rs_obras
         WHERE municipio_id = %s
           AND raw_data IS NOT NULL
           AND atualizado_em > now() - (%s || ' days')::interval
    """, (municipio_id, OBRA_FRESCOR_D))
    return {r[0] for r in cur.fetchall()}


def _versoes_detalhadas(cur, municipio_id: int, tabela: str) -> dict:
    """{(nr, ano, tipo): versao_da_fonte_ja_detalhada} do que esta no banco.

    ⚠️ A comparacao acontece EM MEMORIA, contra o registro que veio da LISTA, e
    nao por SQL contra o que o detalhe devolveu. A diferenca importa: se o
    `DATA_ATUALIZACAO` do detalhe divergisse um segundo do da lista, a pendencia
    nunca fecharia e o coletor rebuscaria o mesmo contrato todas as noites, para
    sempre, gastando o orcamento inteiro sem nunca avancar."""
    if tabela == "contratos":
        cur.execute("""
            SELECT nr_contrato, ano_contrato, tp_instrumento, detalhe_da_versao
              FROM tce_rs_contratos WHERE municipio_id = %s
        """, (municipio_id,))
    else:
        cur.execute("""
            SELECT nr_licitacao, ano_licitacao, cd_tipo_modalidade,
                   detalhe_da_versao
              FROM tce_rs_licitacoes WHERE municipio_id = %s
        """, (municipio_id,))
    return {(str(r[0]), r[1], r[2]): r[3] for r in cur.fetchall()}


# Como cada lista se identifica: (numero, ano, tipo) — a chave natural do
# LicitaCon, e a mesma que a tabela usa no ON CONFLICT.
_CHAVE = {
    "contratos": lambda r: (str(r.get("NR_CONTRATO")),
                            _int(r.get("ANO_CONTRATO")),
                            _txt(r.get("TP_INSTRUMENTO"), 4) or "C"),
    "licitacoes": lambda r: (str(r.get("NR_LICITACAO")),
                             _int(r.get("ANO_LICITACAO")),
                             _txt(r.get("CD_TIPO_MODALIDADE"), 10)),
}
# Situacao "em andamento": e o que o gestor precisa hoje, e por isso vai na
# frente da fila do detalhe. Os dois endpoints usam campos com nomes distintos.
_EM_ANDAMENTO = {
    "contratos": lambda r: r.get("TP_SITUACAO_CONTRATO") == "A",
    "licitacoes": lambda r: r.get("TP_SITUACAO") == "A",
}


def _pendentes_de_detalhe(lista: list[dict], versoes: dict, tabela: str) -> list[dict]:
    """Registros da lista cujo detalhe falta ou ficou velho (armadilha 3).

    Ordem: em andamento primeiro, depois ano decrescente. Assim, mesmo que a
    primeira carga leve varias noites, a primeira noite ja entrega o que vale
    mais."""
    chave, andando = _CHAVE[tabela], _EM_ANDAMENTO[tabela]
    fora = [r for r in lista
            if versoes.get(chave(r), "ausente") != _dt(r.get("DATA_ATUALIZACAO"))]
    fora.sort(key=lambda r: (not andando(r), -(chave(r)[1] or 0)))
    return fora


def _log_ingest(cur, conn, status: str, n: int, erro: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES (%s, %s, %s, %s, NOW())",
            (FONTE, status, n, erro))
        conn.commit()
    except Exception as e:
        log.warning("ingestion_log falhou: %s", str(e)[:120])


class _Orcamento:
    """Teto de tempo para a fase cara. Nunca estoura o timeout da task.

    ⚠️ AS LISTAS NAO CONTAM, e isso nao e detalhe: em Santa Maria elas levam
    SEIS MINUTOS (11.500 registros em paginas de 1.000, ~3,5 MB cada). Com elas
    dentro do orcamento de 900 s, mais os nove minutos das obras, sobrava ZERO
    para os detalhes — a rodada terminava sem buscar um valor sequer. Quem
    percorre lista chama `pausar()`/`retomar()`."""

    def __init__(self, segundos: int):
        self.limite = segundos
        self.inicio = time.monotonic()
        self.pausado_em = None
        self.pausado_total = 0.0

    def pausar(self) -> None:
        if self.pausado_em is None:
            self.pausado_em = time.monotonic()

    def retomar(self) -> None:
        if self.pausado_em is not None:
            self.pausado_total += time.monotonic() - self.pausado_em
            self.pausado_em = None

    def _decorrido(self) -> float:
        agora = self.pausado_em or time.monotonic()
        return (agora - self.inicio) - self.pausado_total

    def sobrou(self) -> bool:
        return self._decorrido() < self.limite

    def gasto(self) -> int:
        return int(self._decorrido())


def ingest(dry: bool = False) -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect

    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            alvos = _alvos(cur)
            if not alvos:
                log.info("nenhum municipio do RS — TCE-RS nao se aplica a este tenant")
                if not dry:
                    _log_ingest(cur, conn, "success", 0)
                return 0

            gravados = 0
            bloqueado = False
            falhas = 0
            orcamento = _Orcamento(ORCAMENTO_S)

            with Conexao() as client:
                for a in alvos:
                    try:
                        gravados += _um_municipio(cur, client, a, orcamento, dry)
                    except Bloqueado as e:
                        bloqueado = True
                        log.error("  %s/%s: %s — %s", a["nome"], a["uf"], e,
                                  NOTA_BLOQUEIO)
                    except Exception as e:
                        falhas += 1
                        log.warning("  %s/%s: %s: %s", a["nome"], a["uf"],
                                    type(e).__name__, str(e)[:160])

            if dry:
                return 0
            conn.commit()
            log.info("=== TCE-RS portal: %d linha(s), %d falha(s), %ds de "
                     "detalhe%s ===", gravados, falhas, orcamento.gasto(),
                     ", BLOQUEADO" if bloqueado else "")
            if bloqueado:
                _log_ingest(cur, conn, "partial", gravados, NOTA_BLOQUEIO)
            else:
                _log_ingest(cur, conn, "success" if not falhas else "partial",
                            gravados)
            return gravados
        except Exception as e:
            conn.rollback()
            log.error("TCE-RS portal falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


def _um_municipio(cur, client: "Conexao", a: dict, orcamento: _Orcamento,
                  dry: bool) -> int:
    """Coleta um municipio. Devolve quantas linhas gravou."""
    nome, mid = a["nome"], a["id"]
    orgao, orgao_nome = a["orgao"], None

    # 1. O codigo do orgao, pelo de-para oficial (armadilha 6).
    if a["ibge"]:
        achado = orgaos_do_municipio(client, a["ibge"])
        exe = achado["executivo"]
        if exe:
            orgao_nome = _txt(exe.get("NOME"))
            codigo = _txt(exe.get("CD_ORGAO"), 10)
            if codigo and codigo != orgao:
                log.info("  %s: orgao no TCE = %s (%s)", nome, codigo, orgao_nome)
                orgao = codigo
                if not dry:
                    cur.execute("UPDATE municipios SET tce_orgao_codigo = %s "
                                "WHERE id = %s", (orgao, mid))
        if achado["outros"]:
            # Nao sao coletados (ver armadilha 6), mas ficam visiveis: a decisao
            # de incluir a autarquia e do dono, com o numero na mao.
            log.info("  %s: outras %d entidade(s) no LicitaCon nao coletadas: %s",
                     nome, len(achado["outros"]),
                     ", ".join(f"{o.get('CD_ORGAO')} {o.get('NOME', '')[:28]}"
                               for o in achado["outros"][:6]))
        time.sleep(PAUSA)

    if not orgao:
        log.info("  %s: sem codigo de orgao no LicitaCon — pulado (nao e "
                 "'municipio sem licitacao')", nome)
        return 0

    gravados = 0

    # 2. Listas — poucas requisicoes, mas NAO baratas em tempo: sao ~3,5 MB por
    # pagina de 1.000 e Santa Maria leva seis minutos para baixar as suas. Ficam
    # FORA do orcamento, que existe para proteger a fase de detalhe (ver
    # `_Orcamento`) — e sao obrigatorias de qualquer modo, porque e delas que sai
    # a fila do que falta detalhar.
    orcamento.pausar()
    lics = licitacoes(client, orgao)
    time.sleep(PAUSA)
    cons = contratos(client, orgao)
    log.info("  %s (%s): %d licitacao(oes), %d contrato(s)", nome, orgao,
             len(lics), len(cons))
    if dry:
        for r in lics[:2]:
            log.info("      LIC %s/%s %s %s", r.get("NR_LICITACAO"),
                     r.get("ANO_LICITACAO"), r.get("DS_SITUACAO"),
                     (r.get("DS_OBJETO") or "")[:50])
        for r in cons[:2]:
            log.info("      CON %s/%s %s %s", r.get("NR_CONTRATO"),
                     r.get("ANO_CONTRATO"), r.get("DS_SITUACAO"),
                     (r.get("DS_OBJETO") or "")[:50])
    else:
        # ⚠️ EM LOTE, e nao um `execute` por linha. Sao 11.505 linhas em Santa
        # Maria, e cada `execute` e um ida-e-volta pela rede: rodando a carga de
        # fora da VPS, por tunel SSH (~30 ms cada), isso custava SEIS MINUTOS
        # so para gravar as listas — mais que o dobro do que a coleta inteira
        # de Nova Palma levou. Em lote sao poucos ida-e-volta.
        _gravar_em_lote(cur, _SQL_LIC,
                        [linha_licitacao(mid, orgao_nome, r) for r in lics])
        _gravar_em_lote(cur, _SQL_CON,
                        [linha_contrato(mid, orgao_nome, r) for r in cons])
        gravados += len(lics) + len(cons)
    # ⚠️ So AGORA o orcamento volta a correr: a gravacao das listas e parte do
    # custo fixo da rodada, nao da fase de detalhe que ele existe para proteger.
    orcamento.retomar()

    # 3. Remessas — por via de operacao, nao por pontualidade (armadilha 1).
    hoje = date.today()
    for ano in range(hoje.year - ANOS_REMESSA + 1, hoje.year + 1):
        for periodo in range(1, 13):
            if ano == hoje.year and periodo > hoje.month:
                break
            for r in remessas(client, orgao, ano, periodo):
                if not dry:
                    cur.execute(_SQL_REM, linha_remessa(mid, r))
                    gravados += 1
            time.sleep(PAUSA)

    # 4. Obras — zero e resultado legitimo (armadilha 9).
    #
    # ⚠️⚠️ A OBRA SO E REBUSCADA QUANDO PRECISA, E TEM ORCAMENTO PROPRIO. Sem as
    # duas coisas a carga de Santa Maria travou: o detalhe de uma obra custa
    # ~4,5 s (o payload traz a planilha inteira) e sao 120 delas, entao cada
    # rodada gastava NOVE MINUTOS rebuscando as MESMAS obras — e sobrava zero
    # para os contratos. Seis rodadas de 15 min renderam 84 detalhes de contrato;
    # Nova Palma, sem obra nenhuma, fez 954 em 70 segundos.
    lista_obras = obras(client, orgao)
    ja_frescas = _obras_com_detalhe_fresco(cur, mid) if not dry else set()
    pendentes_obra = [o for o in lista_obras
                      if _int(o.get("ID_OBRA")) not in ja_frescas]
    log.info("  %s: %d obra(s) no LicitaCon Obras — %d com detalhe a buscar",
             nome, len(lista_obras), len(pendentes_obra))

    # Grava TODAS as da lista primeiro: e barato (nao custa requisicao) e faz a
    # obra aparecer na tela com objeto, situacao e contratado ja na primeira
    # rodada, mesmo antes de o detalhe caro chegar.
    if not dry:
        for o in lista_obras:
            cur.execute(_SQL_OBRA, linha_obra(mid, o))
            gravados += 1

    orcamento_obras = _Orcamento(min(ORCAMENTO_OBRAS_S, ORCAMENTO_S))
    for i, o in enumerate(pendentes_obra):
        if not orcamento_obras.sobrou() or not orcamento.sobrou():
            log.info("  %s: orcamento de obras esgotado; %d ficam para a "
                     "proxima rodada", nome, len(pendentes_obra) - i)
            break
        det = obra_detalhe(client, o.get("ID_OBRA"))
        time.sleep(PAUSA)
        if dry:
            m = linha_obra(mid, o, det)
            log.info("      OBRA %s %s medido=%s de %s (%s%%)", m["id_obra"],
                     (m["ds_sit"] or "")[:20], m["vl_medido"], m["vl_atual"],
                     m["pc_fin"])
            continue
        cur.execute(_SQL_OBRA, linha_obra(mid, o, det))
        gravados += 1
        for rec in ((det or {}).get("ORIGEM_RECURSOS") or []):
            cur.execute(_SQL_REC, linha_recurso(mid, _int(o.get("ID_OBRA")), rec))
            gravados += 1

    if dry:
        return 0

    # 5. Detalhes, ate onde o orcamento deixar (armadilha 3). Contrato antes de
    # licitacao: o VALOR so existe do lado do contrato.
    for tabela, lista, buscar, sql, montar in (
        ("contratos", cons, contrato_detalhe, _SQL_CON, linha_contrato),
        ("licitacoes", lics, licitacao_detalhe, _SQL_LIC, linha_licitacao),
    ):
        pendentes = _pendentes_de_detalhe(
            lista, _versoes_detalhadas(cur, mid, tabela), tabela)
        feitos = vazios = 0
        for r in pendentes:
            if not orcamento.sobrou():
                break
            nr, ano, tipo = _CHAVE[tabela](r)
            det = buscar(client, orgao, tipo, nr, ano)
            time.sleep(PAUSA)
            # ⚠️ SEM `if not det: continue` AQUI. `{}` e a resposta da fonte
            # para registro que ela nao detalha, e pular sem carimbar a versao
            # devolvia esses registros a fila em toda rodada, para sempre. O
            # UPSERT abaixo grava a linha da LISTA com a versao carimbada: os
            # campos do detalhe continuam nulos (COALESCE nao apaga nada), e a
            # pendencia fecha. Se a fonte um dia mudar aquele registro, a
            # `DATA_ATUALIZACAO` muda junto e ele volta a fila sozinho.
            if not det:
                vazios += 1
            # ⚠️ `r` (a LISTA) e a base, e o detalhe so acrescenta. E o que faz
            # `detalhe_da_versao` receber a mesma versao que a proxima rodada vai
            # comparar — ver `_versoes_detalhadas`.
            cur.execute(sql, montar(mid, orgao_nome, r, det))
            feitos += 1
            gravados += 1
        if pendentes:
            # ⚠️ O "sem detalhe na fonte" e reportado SEPARADO do que foi
            # buscado: sao registros que existem na lista e que o Tribunal nao
            # detalha, e ficariam parecendo coleta incompleta. Nao sao.
            log.info("  %s %s: %d de %d detalhe(s) nesta rodada%s%s", nome,
                     tabela, feitos, len(pendentes),
                     f" ({vazios} sem detalhe na fonte)" if vazios else "",
                     "" if feitos == len(pendentes) else " (o resto na proxima)")

    return gravados


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ingest(dry="--dry" in sys.argv)
