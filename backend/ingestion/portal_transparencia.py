"""
Emendas parlamentares FEDERAIS — carteira (TransfereGov) + execucao (CGU).

⭐ O BURACO QUE ISTO FECHA. O PACTHA nao tinha tela de emenda federal: ela
aparecia de raspao como Transferencia Especial em «Especiais» e como selo `TE`
na lista de Convenios, sempre pelo mesmo caminho — a emenda que virou PROPOSTA.
Medido em 06/09/2026 no dump `siconv_emenda.zip`: **45% das emendas de Nova
Palma e 43% das de Monte Siao tem `ID_PROPOSTA` VAZIO**. Quase metade da
carteira era invisivel, e so o filtro por CNPJ do beneficiario a alcanca.

DUAS FASES, e a separacao e o que torna isto barato e reversivel:

  FASE 1 — CARTEIRA. Le `siconv_emenda.zip` (dado ABERTO, 8,3 MB) e casa
  `BENEFICIARIO_EMENDA` (CNPJ de 14 digitos em 298.107 das 298.114 linhas) com
  os CNPJs que ja conhecemos. NAO precisa de chave nenhuma, roda nos cinco
  tenants, e entrega autor, tipo, impositividade, orgao, ano e valor. E ela e
  COMMITADA antes de a fase 2 — incerta — ser tentada.

  FASE 2 — EXECUCAO. Pergunta a CGU, por codigo de emenda, quanto foi
  empenhado/liquidado/pago e quais documentos existem. So roda com
  `PORTAL_TRANSPARENCIA_API_KEY`.

⚠️ A CHAVE E DE PESSOA FISICA, e isso e uma decisao, nao um detalhe tecnico.
Ela sai de `portaldatransparencia.gov.br/api-de-dados/cadastrar-email` com conta
gov.br Prata ou Ouro e fica vinculada ao CPF de quem cadastrou. Num produto com
cinco tenants isso e um passivo: a chave de uma pessoa responde pelas consultas
de todas as prefeituras. Por isso ela nao e pedida ao cliente, e por isso a
decisao de 06/09/2026 foi liga-la so em `novapalma-rs` e `montesiao-mg`.

⚠️⚠️ A HIPOTESE QUE AINDA NAO FOI CONFIRMADA CONTRA A CGU. O `codigoEmenda` de
12 digitos e derivado: ano (posicoes 5:9 de COD_PROGRAMA_EMENDA, que tem 13 =
orgao SIAFI 5 + ano 4 + seq 4) + NR_EMENDA (8 = codigo do autor 4 + seq 4).
2023 + 32980002 = 202332980002. A consistencia do codigo do autor entre anos foi
conferida (Heitor Schuch = 3298 em 2016/2020/2023/2025; Paulo Pimenta = 1986 em
2011/2015), mas isso NAO e a CGU concordando. Ver `--verificar` e o PLANO B
abaixo.

⭐ O PLANO B JA ESTA IMPLEMENTADO, e custa a mesma requisicao: `/emendas` aceita
`ano` E `numeroEmenda` separadamente, e a resposta traz o `codigoEmenda`
VERDADEIRO. `PT_ESTRATEGIA=ano_numero` nao depende da hipotese; `auto` (padrao)
comeca pelo codigo e troca sozinho se a amostra reprovar EM MASSA. Divergencia
de autor isolada e resolvida POR EMENDA (`_confere_autor`: plano B so para ela,
ou ela e pulada e anotada) — desde 11/09/2026, quando UMA divergencia em 20
abortava a fase 2 do tenant inteiro, toda noite. Codigo confirmado uma vez vira
dado (`codigo_confirmado`), e nunca mais e derivado.

⚠️ O QUE ESTA API **NAO** TEM: filtro por municipio em `/emendas`. Os parametros
sao `codigoEmenda`, `numeroEmenda`, `nomeAutor`, `tipoEmenda`, `ano`,
`codigoFuncao`, `codigoSubfuncao` — nenhum territorial. Varrer o Brasil seria
caro e desnecessario: o territorio vem do dump, por CNPJ.

⚠️ `/convenios` NAO tem campo de emenda (`ConvenioDTO`, conferido no Swagger em
06/09 e de novo em 22/09/2026) — nao procure o vinculo convenio<->emenda la. Mas
"redundante" (auditoria de 29/08) estava ERRADO: ela traz o que o TransfereGov nao
tem (as transferencias legais da Defesa Civil e o historico anterior a 2009). Quem
coleta e `ingestion/cgu_convenios.py`, pela PLANILHA aberta — sem token.

CONTRATO DA API, conferido no `/v3/api-docs` (167 KB) em 06/09/2026:
    cabecalho `chave-api-dados: <chave>`  (securityScheme apiKey, confirmado)
    paginacao por `pagina` (comeca em 1); pagina vazia = fim
    401 sem chave, corpo {"Erro na API":"Chave de API invalida!"} (medido)
    cotas: 700 req/min 00:00-05:59 · 400 req/min 06:00-23:59
           180 req/min nas APIs RESTRITAS · estourar suspende o token por 8h
    ⚠️ `/emendas` e `/emendas/documentos` NAO estao na lista de restritas.

Uso:
    python -u ingestion/portal_transparencia.py            # rodada normal
    python -u ingestion/portal_transparencia.py --dry      # nao grava nada
    python -u ingestion/portal_transparencia.py --verificar # so testa a hipotese
"""
import json
import logging
import os
import re
import sys
import time
import unicodedata
from datetime import datetime

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("portal_transparencia")

BASE = "https://api.portaldatransparencia.gov.br/api-de-dados"
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0 Portal da Transparencia/CGU)",
      "Accept": "application/json"}
TIMEOUT = 60

FONTE = "portal_transparencia"
DUMP = "siconv_emenda.zip"

# As 10 colunas do dump. ⚠️ CONFERIDAS A CADA RODADA: cabecalho errado hoje
# produz "zero em silencio", que e o modo de falha mais caro deste repo (o
# comentario esta em `transferegov_opendata.py`, escrito depois de acontecer).
COLUNAS_DUMP = (
    "ID_PROPOSTA", "QUALIF_PROPONENTE", "COD_PROGRAMA_EMENDA", "NR_EMENDA",
    "NOME_PARLAMENTAR", "BENEFICIARIO_EMENDA", "IND_IMPOSITIVO",
    "TIPO_PARLAMENTAR", "VALOR_REPASSE_PROPOSTA_EMENDA", "VALOR_REPASSE_EMENDA")

# A CGU limita por minuto e a janela e mais apertada fora da madrugada. 700ms
# entre chamadas da ~86 req/min — folgado ate na faixa RESTRITA de 180/min, que
# nao sei se se aplica a `/emendas`. Por isso o valor fica: ele respeita o pior
# caso com 2x de margem, e a economia de baixa-lo seria de minutos.
PAUSA_S = float(os.getenv("PORTAL_TRANSPARENCIA_PAUSA_S", "0.7") or "0.7")

# Fase 1 ligada por padrao: e dado aberto, nao usa a chave de ninguem, e e ela
# que faz a tela nascer util nos tres tenants sem chave. `=0` volta ao inerte
# total de antes de 06/09/2026.
CARTEIRA_LIGADA = os.getenv("PORTAL_TRANSPARENCIA_CARTEIRA", "1") != "0"

MIN_INTERVAL_H = int(os.getenv("PT_MIN_INTERVAL_H", "20") or "20")
ORCAMENTO_S = float(os.getenv("PT_ORCAMENTO_S", "1400") or "1400")
MAX_REQ = int(os.getenv("PT_MAX_REQ", "1800") or "1800")
# Quantos codigos testar antes de persistir qualquer coisa da CGU.
AMOSTRA = int(os.getenv("PT_AMOSTRA", "20") or "20")
# Abaixo desta taxa de acerto a rodada passa ao plano B (ano + numero).
TAXA_MINIMA = float(os.getenv("PT_TAXA_MINIMA", "0.25") or "0.25")
# Autor divergente ACIMA desta fracao dos encontrados na amostra = a derivacao do
# codigo quebrou EM MASSA, e a rodada inteira passa ao plano B. Abaixo, e caso
# isolado, e quem resolve e a conferencia POR EMENDA do laco (`_confere_autor`).
DIVERGENCIA_MAXIMA = float(os.getenv("PT_DIVERGENCIA_MAXIMA", "0.25") or "0.25")
# auto | codigo | ano_numero
ESTRATEGIA = (os.getenv("PT_ESTRATEGIA", "auto") or "auto").strip().lower()


def chave() -> str:
    """A chave da CGU, sem as aspas que o painel deixa passar.

    ⚠️ ISTO JA CUSTOU TRES DIAS DE COLETA, EM SILENCIO. Em 06/09/2026 a chave
    foi gravada no Coolify COM aspas simples em volta (`'33f7...'`) em
    `montesiao-mg` e `novapalma-rs`. O `.strip()` sozinho nao tira aspas: o
    header saia `chave-api-dados: '33f7...'` e a CGU respondia 401 em toda
    requisicao. Medido em 09/09/2026 contra a API: a MESMA chave sem as aspas
    responde 200. A fase 2 (execucao das emendas) ficou morta nos dois tenants
    e nada apitou, porque coletor sem chave e um estado PREVISTO aqui — o
    inerte por decisao e o 401 se parecem de fora.

    Aspas em volta de env var nao sao erro de quem digitou: em `.env` e em
    docker-compose elas fazem parte da sintaxe e somem; num campo de painel,
    ficam. Aceitar as duas formas custa uma linha."""
    return (os.getenv("PORTAL_TRANSPARENCIA_API_KEY") or "").strip().strip("'\"").strip()


def habilitado() -> bool:
    return bool(chave())


def _cabecalhos() -> dict:
    return {**UA, "chave-api-dados": chave()}


class Bloqueado(Exception):
    """429 da CGU. ⚠️ NAO E RETENTADO — ver `paginar`."""


class Orcamento:
    """Teto de TEMPO e de REQUISICOES da rodada.

    ⚠️ ELE EXISTE POR CAUSA DE UM ACIDENTE QUE JA ACONTECEU NESTE PROJETO. O
    INFRA.md §8 registra uma Scheduled Task que ficou em `* * * * *` por 34
    horas — ~1.440 execucoes. Com este coletor isso seria o teto diario inteiro
    da CGU e o token suspenso por 8h, repetidamente. O orcamento e contado em
    codigo justamente para a explosao ser impossivel por construcao, e nao
    depender de alguem ter olhado o cron."""

    def __init__(self, segundos: float, requisicoes: int) -> None:
        self.fim = time.monotonic() + segundos
        self.restantes = requisicoes
        self.gastas = 0
        self.estourou = False

    def pode(self) -> bool:
        if self.restantes <= 0 or time.monotonic() >= self.fim:
            self.estourou = True
            return False
        return True

    def gasta(self) -> None:
        self.restantes -= 1
        self.gastas += 1


# ---------------------------------------------------------------------------
# Funcoes PURAS — sao elas que os testes cobrem (o repo nao tem Postgres de
# teste, entao a regra e o que precisa de teste).
# ---------------------------------------------------------------------------
_ANO_MIN, _ANO_MAX = 1998, 2100


def codigo_emenda(cod_programa: str, nr: str) -> str | None:
    """Os 12 digitos que a CGU chama de `codigoEmenda`: ano + NR_EMENDA.

    ⚠️ DEVOLVE None EM VEZ DE ADIVINHAR, e cada caso tem um motivo medido:

      - NR_EMENDA VAZIO (7.059 das 298.114 linhas): a linha da carteira continua
        VALENDO — tem parlamentar, valor e beneficiario. Ela so nunca entra na
        fila da CGU. Emitir '2023' + '' = '2023' produziria um codigo de 4
        digitos que a API rejeita ou, pior, casa com outra coisa.
      - NR_EMENDA de 4 DIGITOS (444 linhas): e o formato antigo. ⚠️ NUNCA
        `zfill`: '1234'.zfill(8) = '00001234' e um codigo VALIDO e DE OUTRA
        EMENDA. Um numero plausivel e errado nao tem como ser percebido depois.
      - NR_EMENDA de 9 DIGITOS (1 linha): fora do contrato.
      - COD_PROGRAMA_EMENDA sem 13 digitos: o ano sairia truncado.
      - ano fora de [1998, 2100]: o layout mudou, e sair calado seria pior.

    ⚠️ E A PARTE NAO VERIFICADA E O ANO. A consistencia conferida (codigo do
    autor estavel entre anos) valida os digitos 5-8 do NR_EMENDA — o AUTOR —, e
    nao o ano, que vem do PROGRAMA e pode nao ser o ano da emenda. Ver o
    `--verificar` e a estrategia `ano_numero`.
    """
    cp = (cod_programa or "").strip()
    n = (nr or "").strip()
    if len(n) != 8 or not n.isdigit():
        return None
    if len(cp) != 13 or not cp.isdigit():
        return None
    ano = cp[5:9]
    if not (_ANO_MIN <= int(ano) <= _ANO_MAX):
        return None
    return ano + n


def ano_do_programa(cod_programa: str) -> int | None:
    """O ano nas posicoes 5:9 de COD_PROGRAMA_EMENDA, ou None."""
    cp = (cod_programa or "").strip()
    if len(cp) != 13 or not cp.isdigit():
        return None
    ano = int(cp[5:9])
    return ano if _ANO_MIN <= ano <= _ANO_MAX else None


def orgao_do_programa(cod_programa: str) -> str | None:
    """Os 5 primeiros digitos = orgao SIAFI (36000 = Saude, 56000 = Cidades)."""
    cp = (cod_programa or "").strip()
    return cp[:5] if len(cp) == 13 and cp.isdigit() else None


def cnpj14(v) -> str | None:
    """CNPJ so com digitos, completado a 14.

    ⚠️ O `zfill` AQUI E CERTO, ao contrario do de `NR_EMENDA`: sao 7 linhas do
    dump em que o zero a esquerda foi comido pelo CSV, e o numero continua sendo
    o mesmo CNPJ. No numero da emenda o zero a esquerda mudaria a IDENTIDADE.
    """
    s = "".join(c for c in str(v or "") if c.isdigit())
    if not s or len(s) > 14:
        return None
    return s.zfill(14) if len(s) >= 13 else None


def valor_dump(linha: dict) -> float | None:
    """O valor da emenda, com o fallback que vale R$ 4,45 mi em Nova Palma.

    ⚠️ `VALOR_REPASSE_EMENDA` VEM VAZIO EM 113.658 DAS 298.114 LINHAS (38%).
    Sem cair para `VALOR_REPASSE_PROPOSTA_EMENDA`, Nova Palma sai como
    R$ 9,23 mi em vez de R$ 13,68 mi — um terco do dinheiro some, e some
    silenciosamente, porque o numero menor tambem parece plausivel.

    ⚠️ E a conversao e a de `transferegov_opendata._money`, que e CONDICIONAL
    (`if "," in s`). O `_money` de `siconv_emenda_backfill` faz
    `replace(".", "")` sem condicional: '1234567.89' viraria 123456789 — cem
    vezes maior, sem excecao e sem log. Nao usar aquele.
    """
    from ingestion.transferegov_opendata import _money
    v = _money(linha.get("VALOR_REPASSE_EMENDA"))
    if v is None:
        v = _money(linha.get("VALOR_REPASSE_PROPOSTA_EMENDA"))
    return v


def linha_carteira(l: dict, alvo: dict) -> dict:
    """Traduz UMA linha do dump para as colunas de `emendas_federais_carteira`.

    Funcao PURA e importavel de fora, pelo mesmo motivo do
    `transferegov_te.plano_para_linha`: se um campo mudar de nome no dump, muda
    AQUI e o coletor e os testes acompanham juntos.
    """
    from ingestion.transferegov_opendata import _money
    cp = (l.get("COD_PROGRAMA_EMENDA") or "").strip()
    nr = (l.get("NR_EMENDA") or "").strip()
    imp = (l.get("IND_IMPOSITIVO") or "").strip().upper()
    return {
        "municipio_id": alvo["municipio_id"],
        "id_proposta": (l.get("ID_PROPOSTA") or "").strip(),
        "cod_programa_emenda": cp,
        "nr_emenda": nr,
        "ano": ano_do_programa(cp),
        "codigo_emenda": codigo_emenda(cp, nr),
        "beneficiario_cnpj": alvo["cnpj"],
        "beneficiario_nome": alvo.get("nome"),
        "vinculo": alvo.get("vinculo"),
        "e_prefeitura": alvo.get("vinculo") == "prefeitura",
        "parlamentar": (l.get("NOME_PARLAMENTAR") or "").strip() or None,
        # ⚠️ Vazio vira NULL, nunca um valor. `TIPO_PARLAMENTAR` vem vazio em
        # 10.654 linhas; um COALESCE para 'INDIVIDUAL' INVENTARIA classificacao.
        "tipo_parlamentar": (l.get("TIPO_PARLAMENTAR") or "").strip() or None,
        # 'SIM'/'NAO' na fonte. Qualquer outra coisa vira NULL — nao chutar.
        "impositiva": True if imp == "SIM" else (False if imp.startswith("N") else None),
        "qualif_proponente": (l.get("QUALIF_PROPONENTE") or "").strip() or None,
        "orgao_siafi": orgao_do_programa(cp),
        "valor_repasse_proposta": _money(l.get("VALOR_REPASSE_PROPOSTA_EMENDA")),
        "valor_repasse_emenda": valor_dump(l),
        "raw_data": json.dumps(l, ensure_ascii=False),
    }


def linha_cgu(x: dict) -> dict:
    """Traduz um `ConsultaEmendasDTO` para `emendas_federais_cgu`.

    ⚠️ TODOS OS VALORES CHEGAM COMO STRING (conferido no Swagger). E
    `localidadeDoGasto` e guardada como TEXTO INFORMATIVO — esta funcao nao tem
    e nao pode ter `municipio_id`, para que ninguem seja tentado a casar
    municipio por aquele campo.
    """
    from ingestion.transferegov_opendata import _money
    ano = x.get("ano")
    try:
        ano = int(ano) if ano is not None else None
    except (TypeError, ValueError):
        ano = None
    return {
        "codigo_emenda": (x.get("codigoEmenda") or "").strip(),
        "ano": ano,
        "tipo_emenda": (x.get("tipoEmenda") or "").strip() or None,
        "autor": (x.get("autor") or "").strip() or None,
        "nome_autor": (x.get("nomeAutor") or "").strip() or None,
        "numero_emenda": (x.get("numeroEmenda") or "").strip() or None,
        "localidade_gasto": (x.get("localidadeDoGasto") or "").strip(),
        "funcao": (x.get("funcao") or "").strip(),
        "subfuncao": (x.get("subfuncao") or "").strip(),
        "valor_empenhado": _money(x.get("valorEmpenhado")),
        "valor_liquidado": _money(x.get("valorLiquidado")),
        "valor_pago": _money(x.get("valorPago")),
        "valor_resto_inscrito": _money(x.get("valorRestoInscrito")),
        "valor_resto_cancelado": _money(x.get("valorRestoCancelado")),
        "valor_resto_pago": _money(x.get("valorRestoPago")),
        "raw_data": json.dumps(x, ensure_ascii=False),
    }


def linha_documento(codigo: str, x: dict) -> dict | None:
    """Traduz um `DocumentoRelacionadoEmendaDTO`.

    ⚠️ SEM CAMPO DE VALOR, e isso e a fonte e nao esquecimento: o DTO responde
    QUANDO e EM QUE FASE, jamais QUANTO.
    """
    did = x.get("id")
    if did is None:
        return None
    d = (x.get("data") or "").strip()
    data = None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            data = datetime.strptime(d, fmt).date()
            break
        except ValueError:
            continue
    return {
        "codigo_emenda": codigo,
        "documento_id": int(did),
        "data": data,
        "fase": (x.get("fase") or "").strip() or None,
        "codigo_documento": (x.get("codigoDocumento") or "").strip() or None,
        "codigo_documento_resumido": (x.get("codigoDocumentoResumido") or "").strip() or None,
        "especie_tipo": (x.get("especieTipo") or "").strip() or None,
        "tipo_emenda": (x.get("tipoEmenda") or "").strip() or None,
        "raw_data": json.dumps(x, ensure_ascii=False),
    }


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
# Tamanho de pagina APRENDIDO na rodada, nunca chutado.
_TAM_PAGINA: int | None = None
# Quantas requisicoes a rodada ja fez. So existe para o freio entre
# codigos — ver `paginar`. Zerado por rodada, nao por chamada.
_REQUISICOES = 0


def paginar(client: httpx.Client, caminho: str, params: dict,
            teto_paginas: int = 50,
            orcamento: "Orcamento | None" = None) -> tuple[list[dict], bool]:
    """Percorre `pagina=1..N`. Devolve (itens, completo).

    ⚠️ DEVOLVE `completo`, e nao so a lista. A versao anterior registrava o teto
    em log e devolvia dado truncado com a rodada seguindo como sucesso — para
    `/emendas/documentos` isso seria "pagamentos faltando" com luz verde. Quem
    chama decide o status a partir do segundo elemento. Mesmo desenho de
    `obrasgov.varrer_uf`.

    ⭐ PARADA CURTA AUTO-APRENDIDA — metade da cota sai daqui. Como a condicao de
    parada era "pagina vazia", uma consulta com 1 resultado custava DUAS
    requisicoes. A parada curta so liga DEPOIS que a rodada VIU uma pagina
    cheia: chutar o tamanho e a CGU mudar truncaria em silencio, que e pior que
    gastar a requisicao.

    ⚠️⚠️ 429 NAO E RETENTADO, e isto e o OPOSTO do `obrasgov.pagina()`, de
    proposito. A medicao de 17/08/2026 na API `especiais` do TransfereGov
    (INFRA.md §5) mostrou que REQUISICAO REJEITADA TAMBEM RENOVA A PENA: as
    proprias retentativas do backoff mantiveram o IP em 403 por mais de 6 horas.
    A CGU suspende o TOKEN por 8h, e o token e o mesmo nos cinco tenants — um
    backoff aqui derrubaria a fonte inteira, no ambiente inteiro, por uma noite e
    meia. Rodada curta e barata; token suspenso nao e.
    """
    global _TAM_PAGINA
    out: list[dict] = []
    for pagina in range(1, teto_paginas + 1):
        if orcamento is not None and not orcamento.pode():
            return out, False
        # ⚠️⚠️ A PAUSA VALE ENTRE TODAS AS REQUISICOES DA RODADA, e nao so
        # entre paginas do mesmo codigo. A versao anterior tinha
        # `if pagina > 1 or out`, e como quase toda consulta resolve em uma
        # pagina, cada codigo novo entrava com `pagina=1` e `out=[]` — ou seja,
        # NAO HAVIA PAUSA ENTRE CODIGOS e o throttle so valia dentro de um.
        #
        # Medido em 06/09/2026: Nova Palma fez 112 requisicoes em ~50s (134
        # req/min) e Monte Siao 265 em ~133s (120 req/min), contra os ~86 que o
        # desenho prometia. Nao estourou porque `/emendas` esta na faixa de
        # 400/700, mas o freio estava pela metade — e a faixa RESTRITA e 180.
        #
        # O contador e de MODULO porque o freio e da RODADA: `paginar` e
        # chamado uma vez por codigo, e um contador local zeraria a cada
        # chamada, que e exatamente o defeito que isto conserta.
        global _REQUISICOES
        if _REQUISICOES:
            time.sleep(PAUSA_S)
        _REQUISICOES += 1
        r = client.get(f"{BASE}{caminho}", params={**params, "pagina": pagina},
                       headers=_cabecalhos(), timeout=TIMEOUT)
        if orcamento is not None:
            orcamento.gasta()
        if r.status_code == 401:
            raise PermissionError(
                "chave-api-dados recusada (401). A chave e vinculada ao CPF de "
                "quem a cadastrou e pode ter sido revogada — ou o token esta "
                "suspenso por 8h por estouro de cota.")
        if r.status_code == 429:
            raise Bloqueado(
                "429 da CGU — cota por minuto estourada. A fase para AQUI, sem "
                "retentativa: requisicao rejeitada tambem renova a pena.")
        r.raise_for_status()
        try:
            lote = r.json() or []
        except ValueError:
            # ⚠️ HTTP 200 com corpo que nao e JSON: pagina de manutencao, WAF ou
            # HTML de erro. Nao e fim de paginacao — e falha, e a rodada tem de
            # saber (`completo=False` faz o chamador marcar `partial`).
            log.warning("%s: resposta 200 nao-JSON (pagina %d)", caminho, pagina)
            return out, False
        if not isinstance(lote, list):
            # ⚠️ E SE A CGU PASSAR A DEVOLVER UM ENVELOPE (`{"data": [...]}`),
            # tratar como "acabou" zeraria a fonte em silencio — o modo de falha
            # mais caro deste repo. `completo=False` -> `partial`.
            log.warning("%s: resposta 200 com %s no lugar de lista — contrato "
                        "mudou?", caminho, type(lote).__name__)
            return out, False
        if not lote:
            return out, True
        out.extend(lote)
        if _TAM_PAGINA is None or len(lote) > _TAM_PAGINA:
            _TAM_PAGINA = len(lote)
        elif len(lote) < _TAM_PAGINA:
            # Pagina curta com o tamanho JA conhecido = ultima pagina.
            return out, True
    log.warning("%s: teto de %d paginas atingido — resultado TRUNCADO",
                caminho, teto_paginas)
    return out, False


def agregado_da_emenda(client: httpx.Client, codigo: str,
                       orcamento: "Orcamento | None" = None) -> list[dict]:
    """`GET /emendas?codigoEmenda=` — os valores agregados da emenda.

    ⚠️ O QUE VOLTA E NACIONAL: e a emenda INTEIRA, nao a fatia do municipio. Uma
    emenda de bancada de R$ 30 mi que passou por Nova Palma com R$ 250 mil
    devolve R$ 30 mi. Por isso `emendas_federais_cgu` nao tem `municipio_id`.
    """
    itens, _ = paginar(client, "/emendas", {"codigoEmenda": codigo},
                       teto_paginas=10, orcamento=orcamento)
    return itens


def agregado_por_ano_numero(client: httpx.Client, ano: int, numero: str,
                            orcamento: "Orcamento | None" = None) -> list[dict]:
    """O PLANO B: `?ano=&numeroEmenda=`, que NAO depende da hipotese.

    ⭐ Mesma 1 requisicao, e a resposta traz o `codigoEmenda` VERDADEIRO — que
    gravamos com `codigo_confirmado = TRUE` e nunca mais derivamos. Trocar uma
    derivacao permanente por uma descoberta unica e o melhor negocio disponivel.
    """
    itens, _ = paginar(client, "/emendas", {"ano": ano, "numeroEmenda": numero},
                       teto_paginas=10, orcamento=orcamento)
    return itens


# ⚠️ MEDIDO NA CARGA REAL, e o primeiro valor estava errado. Com `teto=20` a
# rodada de Nova Palma truncou QUATRO emendas: a maior tem **300 documentos**
# (2.810 no total das 44), e 300/15 por pagina = exatamente 20 paginas. O teto
# batia no limite e cortava justamente as emendas mais executadas — as que mais
# interessam. 60 paginas = ~900 documentos, tres vezes o pior caso medido.
TETO_DOCUMENTOS = int(os.getenv("PT_TETO_DOCUMENTOS", "60") or "60")

# ⚠️⚠️ EMENDA DE COLEGIADO NAO TEM LINHA DO TEMPO — e a medicao e brutal.
# Monte Siao, 06/09/2026, primeira rodada com chave:
#
#     COMISSAO      4 emendas -> 3.600 documentos (TODAS truncadas no teto)
#     INDIVIDUAL   27 emendas ->    15 documentos
#
# Emenda de comissao/bancada e NACIONAL: atende o pais inteiro, e os 900+
# documentos dela sao de outros municipios. Buscar isso custou 240 requisicoes
# — quase toda a cota da noite — para gravar 3.600 linhas que ninguem vai ler e
# que nao dizem nada sobre o municipio.
#
# O AGREGADO dessas emendas continua sendo buscado (1 requisicao, e e ele que
# alimenta os valores da tela). O que se pula e so a linha do tempo.
#
# ⚠️ E a tela DIZ isso na gaveta, em vez de mostrar vazio: gaveta vazia sem
# explicacao seria lida como "nao houve execucao".
TIPOS_COLEGIADO = ("COMISSAO", "BANCADA", "RELATOR GERAL")


def documentos_da_emenda(client: httpx.Client, codigo: str,
                         orcamento: "Orcamento | None" = None) -> tuple[list[dict], bool]:
    """Empenho, liquidacao e pagamento de UMA emenda — sem valor (o DTO nao traz).

    Devolve `(itens, completo)`. ⚠️ QUEM CHAMA TEM DE OLHAR O `completo`: uma
    emenda truncada e "pagamentos faltando" na tela, e sem isso a rodada sairia
    `success` por cima de dado incompleto."""
    return paginar(client, f"/emendas/documentos/{codigo}", {},
                   teto_paginas=TETO_DOCUMENTOS, orcamento=orcamento)


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------
def alvos(cur) -> dict[str, dict]:
    """{cnpj14: {municipio_id, nome, vinculo}} — quem o coletor reconhece.

    ⚠️ 1. O MUNICIPIO SAI DO CNPJ, NUNCA DO NOME. Diretriz do dono (04/09/2026),
    depois de casar por nome ter trazido 379 obras da UFSM como se fossem da
    prefeitura de Santa Maria, e Santa Maria do Herval como se fosse Santa
    Maria. O `BENEFICIARIO_EMENDA` do dump e CNPJ em 298.107 das 298.114 linhas.

    ⚠️⚠️ 2. `transferegov_te` NAO SEMEIA CNPJ AQUI, e isso e deliberado. O
    `municipio_id` daquela tabela vem de casamento por SUBSTRING DE NOME
    (`transferegov_te.py:152-168`), e a contaminacao esta medida: 628 de 890
    linhas com CNPJ divergente na base trust, R$ 318,7 mi no municipio errado
    (`services/bi_abas.py`). Puxar o CNPJ dela LAVARIA um casamento por nome em
    casamento por CNPJ — o erro voltaria com selo de qualidade e ninguem teria
    como perceber. (O CODIGO da emenda da TE continua sendo usado na fila: ele e
    campo da fonte, nao inferencia nossa.)

    As QUATRO fontes que entram, e por que sao confiaveis:
      municipios.cnpj          'prefeitura' <- preenchido por ingestion/siconfi.py
                                               do cadastro de entes do Tesouro,
                                               POR IBGE. E a origem canonica.
      municipio_entidades.cnpj 'entidade'   <- cadastro EXPLICITO de quem
                                               provisiona (hospital, fundo,
                                               associacao). Ver abaixo.
      sismob_obras.nu_cnpj     'sismob'     <- o coletor consulta por municipio
                                               (codigo FNS), nao por nome.
      transferegov_pac.cnpj    'pac'        <- idem, por municipio.

    ⭐ `municipio_entidades` ENTROU EM 06/09/2026 POR CAUSA DE UM NUMERO. A
    primeira carga real de Nova Palma trouxe 69 das 77 linhas do dump: as 8 que
    faltavam sao da Associacao Hospital Nossa Senhora da Piedade — R$ 1,2 milhao
    em emendas que existem, sao do municipio, e nao apareciam. Hospital
    filantropico nao aparece em obra do SISMOB nem em proposta do PAC, entao as
    tres fontes antigas nunca o alcancariam.

    ⚠️ E A SAIDA FACIL ERA A PROIBIDA: dava para achar o CNPJ casando o NOME do
    municipio no dump `siconv_proponentes.zip`. E exatamente a regra que o dono
    cravou em 04/09/2026. O CNPJ tem de ter ORIGEM, nao deducao — por isso ele
    e CADASTRADO, e a coluna `origem` diz por quem.
    """
    out: dict[str, dict] = {}
    cur.execute("""
        SELECT id, nome, regexp_replace(coalesce(cnpj,''), '\\D', '', 'g')
          FROM municipios WHERE active
    """)
    for mid, nome, cnpj in cur.fetchall():
        if len(cnpj or "") == 14:
            out[cnpj] = {"municipio_id": mid, "nome": f"MUNICÍPIO DE {nome}",
                         "vinculo": "prefeitura"}
    ids = [a["municipio_id"] for a in out.values()]
    if not ids:
        return out
    for sql, vinculo in (
        # ⚠️ PRIMEIRO na ordem: cadastro explicito vence garimpo. Se o mesmo CNPJ
        # aparecer aqui e no SISMOB, fica o nome que alguem escreveu — e nao o
        # rotulo que a API de obras usa.
        ("""SELECT municipio_id, regexp_replace(coalesce(cnpj,''), '\\D', '', 'g'),
                   max(nome)
              FROM municipio_entidades WHERE municipio_id = ANY(%s)
             GROUP BY 1, 2""", "entidade"),
        ("""SELECT municipio_id, regexp_replace(coalesce(nu_cnpj,''), '\\D', '', 'g'),
                   max(entidade)
              FROM sismob_obras WHERE municipio_id = ANY(%s)
             GROUP BY 1, 2""", "sismob"),
        ("""SELECT municipio_id, regexp_replace(coalesce(cnpj,''), '\\D', '', 'g'),
                   max(proponente)
              FROM transferegov_pac WHERE municipio_id = ANY(%s)
             GROUP BY 1, 2""", "pac"),
    ):
        try:
            cur.execute(sql, (ids,))
        except Exception as e:
            # Tabela pode nao existir num tenant novo. Uma fonte de CNPJ a menos
            # nao pode derrubar a coleta inteira.
            log.warning("alvos/%s indisponivel: %s", vinculo, str(e)[:100])
            continue
        for mid, cnpj, nome in cur.fetchall():
            if len(cnpj or "") == 14 and cnpj not in out:
                out[cnpj] = {"municipio_id": mid, "nome": nome, "vinculo": vinculo}
    return out


_SQL_CARTEIRA = """
INSERT INTO emendas_federais_carteira
  (municipio_id, id_proposta, cod_programa_emenda, nr_emenda, ano, codigo_emenda,
   beneficiario_cnpj, beneficiario_nome, vinculo, e_prefeitura, parlamentar,
   tipo_parlamentar, impositiva, qualif_proponente, orgao_siafi,
   valor_repasse_proposta, valor_repasse_emenda, raw_data, visto_em)
VALUES
  (%(municipio_id)s, %(id_proposta)s, %(cod_programa_emenda)s, %(nr_emenda)s,
   %(ano)s, %(codigo_emenda)s, %(beneficiario_cnpj)s, %(beneficiario_nome)s,
   %(vinculo)s, %(e_prefeitura)s, %(parlamentar)s, %(tipo_parlamentar)s,
   %(impositiva)s, %(qualif_proponente)s, %(orgao_siafi)s,
   %(valor_repasse_proposta)s, %(valor_repasse_emenda)s,
   %(raw_data)s::jsonb, NOW())
ON CONFLICT (municipio_id, id_proposta, cod_programa_emenda, nr_emenda,
             beneficiario_cnpj) DO UPDATE SET
  ano = EXCLUDED.ano,
  codigo_emenda = EXCLUDED.codigo_emenda,
  beneficiario_nome = COALESCE(EXCLUDED.beneficiario_nome,
                               emendas_federais_carteira.beneficiario_nome),
  vinculo = EXCLUDED.vinculo,
  e_prefeitura = EXCLUDED.e_prefeitura,
  parlamentar = EXCLUDED.parlamentar,
  tipo_parlamentar = EXCLUDED.tipo_parlamentar,
  impositiva = EXCLUDED.impositiva,
  qualif_proponente = EXCLUDED.qualif_proponente,
  orgao_siafi = EXCLUDED.orgao_siafi,
  valor_repasse_proposta = EXCLUDED.valor_repasse_proposta,
  valor_repasse_emenda = EXCLUDED.valor_repasse_emenda,
  raw_data = EXCLUDED.raw_data,
  -- ⚠️ `visto_em` SEMPRE avanca, mesmo quando nada mais mudou: e dele que o
  -- monitor de frescor le. Sem esta linha a fonte envelheceria no painel com o
  -- coletor rodando todo dia.
  visto_em = NOW()
"""

_SQL_CGU = """
INSERT INTO emendas_federais_cgu
  (codigo_emenda, ano, tipo_emenda, autor, nome_autor, numero_emenda,
   localidade_gasto, funcao, subfuncao, valor_empenhado, valor_liquidado,
   valor_pago, valor_resto_inscrito, valor_resto_cancelado, valor_resto_pago,
   raw_data, visto_em)
VALUES
  (%(codigo_emenda)s, %(ano)s, %(tipo_emenda)s, %(autor)s, %(nome_autor)s,
   %(numero_emenda)s, %(localidade_gasto)s, %(funcao)s, %(subfuncao)s,
   %(valor_empenhado)s, %(valor_liquidado)s, %(valor_pago)s,
   %(valor_resto_inscrito)s, %(valor_resto_cancelado)s, %(valor_resto_pago)s,
   %(raw_data)s::jsonb, NOW())
ON CONFLICT (codigo_emenda, localidade_gasto, funcao, subfuncao) DO UPDATE SET
  ano = EXCLUDED.ano, tipo_emenda = EXCLUDED.tipo_emenda,
  autor = EXCLUDED.autor, nome_autor = EXCLUDED.nome_autor,
  numero_emenda = EXCLUDED.numero_emenda,
  valor_empenhado = EXCLUDED.valor_empenhado,
  valor_liquidado = EXCLUDED.valor_liquidado,
  valor_pago = EXCLUDED.valor_pago,
  valor_resto_inscrito = EXCLUDED.valor_resto_inscrito,
  valor_resto_cancelado = EXCLUDED.valor_resto_cancelado,
  valor_resto_pago = EXCLUDED.valor_resto_pago,
  raw_data = EXCLUDED.raw_data, visto_em = NOW()
"""

_SQL_DOC = """
INSERT INTO emendas_federais_documentos
  (codigo_emenda, documento_id, data, fase, codigo_documento,
   codigo_documento_resumido, especie_tipo, tipo_emenda, raw_data, visto_em)
VALUES
  (%(codigo_emenda)s, %(documento_id)s, %(data)s, %(fase)s,
   %(codigo_documento)s, %(codigo_documento_resumido)s, %(especie_tipo)s,
   %(tipo_emenda)s, %(raw_data)s::jsonb, NOW())
ON CONFLICT (codigo_emenda, documento_id) DO UPDATE SET
  data = EXCLUDED.data, fase = EXCLUDED.fase,
  codigo_documento = EXCLUDED.codigo_documento,
  codigo_documento_resumido = EXCLUDED.codigo_documento_resumido,
  especie_tipo = EXCLUDED.especie_tipo, tipo_emenda = EXCLUDED.tipo_emenda,
  raw_data = EXCLUDED.raw_data, visto_em = NOW()
"""


def carteira(cur, conn, dry: bool = False) -> dict:
    """FASE 1 — le o dump e grava a carteira do municipio. Sem chave nenhuma.

    Devolve um relatorio com os numeros que o log precisa dizer. ⚠️ A EQUACAO
    TEM DE FECHAR: `lidas_do_municipio = gravadas + sem_codigo`, e a rodada diz
    os tres. Coleta truncada em silencio e pior que coleta que falha.
    """
    from ingestion.transferegov_opendata import _linhas
    import psycopg2.extras

    rel = {"linhas": 0, "do_municipio": 0, "gravadas": 0, "sem_codigo": 0,
           "codigos": set(), "sem_cnpj": [], "colisoes": 0}

    por_cnpj = alvos(cur)
    if not por_cnpj:
        return rel
    cur.execute("SELECT nome FROM municipios WHERE active "
                "AND length(coalesce(regexp_replace(cnpj, '\\D', '', 'g'), '')) <> 14")
    rel["sem_cnpj"] = [r[0] for r in cur.fetchall()]

    vistas: set[tuple] = set()
    linhas: list[dict] = []
    cabecalho_conferido = False
    for l in _linhas(DUMP):
        rel["linhas"] += 1
        if not cabecalho_conferido:
            faltando = [c for c in COLUNAS_DUMP if c not in l]
            if faltando:
                # ⚠️ ABORTA, nao segue com zero. Cabecalho errado hoje produz
                # "zero em silencio" — a ingestao "conclui" trazendo nada e a
                # tela esvazia sem nenhum erro em log.
                raise RuntimeError(
                    f"{DUMP}: layout mudou — colunas ausentes: {faltando}")
            cabecalho_conferido = True
        cnpj = cnpj14(l.get("BENEFICIARIO_EMENDA"))
        alvo = por_cnpj.get(cnpj) if cnpj else None
        if not alvo:
            continue
        rel["do_municipio"] += 1
        alvo = {**alvo, "cnpj": cnpj}
        linha = linha_carteira(l, alvo)
        # Dedup em memoria ANTES de gravar. ⚠️ A colisao e CONTADA e vira aviso,
        # nao decisao silenciosa: se a tripla do dump nao for unica, quero
        # descobrir por um WARNING e nao por uma sobrescrita.
        k = (linha["municipio_id"], linha["id_proposta"],
             linha["cod_programa_emenda"], linha["nr_emenda"],
             linha["beneficiario_cnpj"])
        if k in vistas:
            rel["colisoes"] += 1
            continue
        vistas.add(k)
        if linha["codigo_emenda"]:
            rel["codigos"].add(linha["codigo_emenda"])
        else:
            rel["sem_codigo"] += 1
        linhas.append(linha)

    if not cabecalho_conferido and rel["linhas"] == 0:
        raise RuntimeError(f"{DUMP}: nenhuma linha lida")

    # Guarda de volume: queda brusca e layout mudado ou download cortado.
    cur.execute("SELECT count(*) FROM emendas_federais_carteira")
    antes = int((cur.fetchone() or [0])[0] or 0)
    if antes and len(linhas) < antes * 0.5:
        raise RuntimeError(
            f"dump suspeito: {len(linhas)} linhas do municipio contra {antes} "
            "ja gravadas (queda > 50%) — nada foi alterado")

    if dry:
        rel["gravadas"] = len(linhas)
        return rel
    psycopg2.extras.execute_batch(cur, _SQL_CARTEIRA, linhas, page_size=200)
    # O selo «Atualizado em» da tela sai daqui — ver `marcar_coleta`.
    marcar_coleta(cur, sorted({l["municipio_id"] for l in linhas}))
    conn.commit()
    rel["gravadas"] = len(linhas)
    return rel


def marcar_coleta(cur, municipio_ids: "list[int]") -> None:
    """Carimba `scraper_municipio_coleta`, que e de onde a TELA le o «Atualizado em».

    ⚠️ SEM ISTO O SELO DE FRESCOR E CODIGO MORTO. O router chama
    `frescor_coleta(db, mun, ("portal_transparencia",))`, que le esta tabela — e
    o coletor nunca escrevia nela. Resultado: `coleta_em` sempre None e a tela
    nunca mostrava a data, num modulo cujo argumento inteiro e honestidade sobre
    quando o dado foi visto.

    ⚠️ `tentativas = 0` porque quem chega aqui coletou. A regra de
    `services/coleta.py` e que so se DATA quando `tentativas = 0`: pos-#159 o
    carimbo acontece tambem no erro (anti-starvation do rodizio), entao datar
    uma rodada que falhou mostraria a hora do ultimo ERRO.
    """
    if not municipio_ids:
        return
    try:
        cur.execute("""
            INSERT INTO scraper_municipio_coleta
                   (fonte, municipio_id, ultima_coleta_em, tentativas)
            SELECT 'portal_transparencia', m, NOW(), 0 FROM unnest(%s::int[]) m
            ON CONFLICT (fonte, municipio_id) DO UPDATE
               SET ultima_coleta_em = NOW(), tentativas = 0
        """, (list(municipio_ids),))
    except Exception as e:
        # Contabilidade nunca derruba a coleta — mesma regra do `_log_ingest`.
        log.warning("marcar_coleta falhou: %s", str(e)[:120])


def semear_fila(cur, cnpjs: "list[str] | None" = None) -> int:
    """Poe na fila da CGU todo codigo conhecido, das DUAS origens.

    ⭐ Os da `transferegov_te` sao o GRUPO DE CONTROLE: `codigoEmendaFormatado`
    e '202341760002-Nome do Parlamentar', ou seja, os 12 digitos vem FORMATADOS
    PELO PROPRIO GOVERNO. Se eles responderem e os derivados nao, o problema e a
    derivacao; se nem eles responderem, o problema e a chave ou o endpoint — e
    nao se mexe na formula. Sem esse grupo, um resultado de 0% e ininterpretavel
    e a reacao natural (mexer na formula) seria a errada.

    ⚠️⚠️ A TE E FILTRADA POR CNPJ, e a versao anterior NAO filtrava — foi um
    defeito meu, medido na primeira rodada com chave em Monte Siao: a fila
    nasceu com **545 codigos** em vez dos 31 da carteira, um fator de 17.

    A causa: `transferegov_te` guarda os planos do ESTADO inteiro, e o
    `municipio_id` dela vem de casamento por SUBSTRING DE NOME
    (`transferegov_te.py:152-168`), com contaminacao medida — 628 de 890 linhas
    com CNPJ divergente na base trust. Semear tudo gastava cota consultando
    emenda de outro municipio.

    ⚠️ Nao CORROMPE nada (a tabela `emendas_federais_cgu` e nacional por
    desenho, e a tela so mostra o que da JOIN com a carteira), mas gasta o
    orcamento da noite com o que ninguem vai ler.

    O filtro e por CNPJ do beneficiario, a mesma disciplina de
    `services/bi_abas.py:431-443`. ⚠️ E o `OR ... IS NULL` no fim NAO e
    descuido: TE sem CNPJ do beneficiario cairia fora, e ela nao tem como ser
    recuperada pelo dump (Transferencia Especial vive em outro sistema e nao
    esta no `siconv_emenda.zip`). Perder emenda legitima para economizar
    requisicao seria o pior dos dois erros.
    """
    n = 0
    cur.execute("""
        INSERT INTO emendas_federais_consulta (codigo_emenda, origem, ano)
        SELECT DISTINCT codigo_emenda, 'siconv', max(ano)
          FROM emendas_federais_carteira
         WHERE codigo_emenda IS NOT NULL
         GROUP BY codigo_emenda
        ON CONFLICT (codigo_emenda) DO NOTHING
    """)
    n += cur.rowcount or 0
    try:
        cur.execute("""
            INSERT INTO emendas_federais_consulta (codigo_emenda, origem, ano)
            SELECT DISTINCT split_part(te.emenda, '-', 1), 'transferegov_te',
                   NULLIF(substr(coalesce(te.programa_codigo, ''), 5, 4), '')::int
              FROM transferegov_te te
             WHERE te.emenda ~ '^[0-9]{12}-'
               AND (regexp_replace(coalesce(te.beneficiario_cnpj, ''),
                                   '\\D', '', 'g') = ANY(%s)
                    OR coalesce(te.beneficiario_cnpj, '') = '')
            ON CONFLICT (codigo_emenda) DO NOTHING
        """, (list(cnpjs or []),))
        n += cur.rowcount or 0
    except Exception as e:
        log.warning("semear_fila/te indisponivel: %s", str(e)[:100])
    return n


def limpar_fila_orfa(cur, cnpjs: "list[str] | None" = None) -> int:
    """Tira da fila o codigo que nao pertence mais a este municipio.

    ⚠️ POR QUE ISTO EXISTE, e por que o filtro da semeadura nao bastou. A fila e
    uma tabela PERSISTENTE: o filtro por CNPJ acrescentado em 06/09/2026 impede
    codigo novo de entrar, mas nao remove os que ja tinham entrado. Medido no
    mesmo dia: Nova Palma seguia com **283 codigos** na fila para uma carteira de
    44, e Monte Siao com 545 para 31 — todos herdados da primeira rodada.

    ⚠️⚠️ E O ORFAO ESCAPAVA TAMBEM DO FILTRO DE COLEGIADO. Aquele decide pelo
    `tipo_parlamentar` da CARTEIRA; codigo que nao esta na carteira tem tipo
    NULL, nao e reconhecido como colegiado, e volta a puxar as centenas de
    documentos que o filtro existe para evitar. Os dois consertos so funcionam
    juntos.

    ⚠️ APAGA SO A FILA, que e CONTROLE. O que ja foi coletado em
    `emendas_federais_cgu` e `..._documentos` FICA: aquelas tabelas sao nacionais
    por desenho, nao aparecem na tela sem o JOIN com a carteira, e apagar dado
    ja pago em requisicao seria trocar espaco em disco por cota da proxima noite.

    Autocurativo: roda a cada rodada e converge sozinho nos cinco tenants, sem
    migration de limpeza.
    """
    try:
        cur.execute("""
            DELETE FROM emendas_federais_consulta q
             WHERE NOT EXISTS (SELECT 1 FROM emendas_federais_carteira c
                                WHERE c.codigo_emenda = q.codigo_emenda)
               AND NOT EXISTS (
                     SELECT 1 FROM transferegov_te te
                      WHERE te.emenda ~ '^[0-9]{12}-'
                        AND split_part(te.emenda, '-', 1) = q.codigo_emenda
                        AND (regexp_replace(coalesce(te.beneficiario_cnpj, ''),
                                            '\\D', '', 'g') = ANY(%s)
                             OR coalesce(te.beneficiario_cnpj, '') = ''))
        """, (list(cnpjs or []),))
        return cur.rowcount or 0
    except Exception as e:
        log.warning("limpar_fila_orfa falhou: %s", str(e)[:120])
        return 0


def fila(cur, limite: int) -> list[tuple]:
    """O rodizio: nunca consultado primeiro, depois o mais velho.

    O ano corrente e o anterior sao reconsultados todo dia (e onde a execucao
    ainda anda); o resto, uma vez por mes. Codigo que a CGU nao conhece cai para
    uma tentativa por semana e para de vez depois de 3 — sem isso ele custaria
    duas requisicoes por noite, para sempre.
    """
    cur.execute("""
        SELECT q.codigo_emenda, q.ano, q.origem,
               (SELECT max(c.tipo_parlamentar) FROM emendas_federais_carteira c
                 WHERE c.codigo_emenda = q.codigo_emenda) AS tipo
          FROM emendas_federais_consulta q
         WHERE consultado_em IS NULL
            OR (ano >= EXTRACT(year FROM now())::int - 1
                AND consultado_em < now() - INTERVAL '20 hours')
            OR (coalesce(achou_agregado, true)
                AND consultado_em < now() - INTERVAL '30 days')
            OR (achou_agregado = false AND tentativas < 3
                AND consultado_em < now() - INTERVAL '7 days')
         ORDER BY consultado_em NULLS FIRST, ano DESC NULLS LAST
         LIMIT %s
    """, (limite,))
    return list(cur.fetchall())


def _consulta_um(client, codigo: str, ano, estrategia: str,
                 orc: Orcamento) -> tuple[list[dict], bool]:
    """(itens, confirmado). `confirmado` = o codigo veio da propria CGU."""
    if estrategia == "ano_numero" and ano and len(codigo) == 12:
        itens = agregado_por_ano_numero(client, int(ano), codigo[4:], orc)
        return itens, True
    return agregado_da_emenda(client, codigo, orc), False


# Titulos que um lado escreve e o outro nao — e que nao identificam ninguem.
_TITULOS_AUTOR = frozenset({"DEP", "DEPUTADO", "DEPUTADA", "SEN", "SENADOR", "SENADORA"})


def _norm_autor(nome) -> str:
    """Nome de autor comparavel: maiusculas, sem acento, sem pontuacao, sem titulo."""
    t = unicodedata.normalize("NFKD", str(nome or "").upper())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^A-Z0-9]+", " ", t)
    return " ".join(p for p in t.split() if p not in _TITULOS_AUTOR)


def mesmo_autor(autor_dump, nomes_cgu) -> "bool | None":
    """O autor do dump e o da CGU sao a mesma pessoa? None = nao ha como comparar.

    ⚠️ A COMPARACAO ANTIGA ERA SO `upper()` + "um contem o outro": "JOSÉ" contra
    "JOSE" contava como OUTRO deputado, e UMA divergencia na amostra abortava a
    fase de execucao do tenant inteiro. Foi o que parou freitas e trust em
    11/09/2026 ("autor bate em 19, diverge em 1"). Agora compara sem acento,
    pontuacao e titulo, e por PALAVRA INTEIRA — "ANA" nao pode casar com
    "JULIANA", que a regra antiga (substring cru) deixava passar."""
    alvo = _norm_autor(autor_dump)
    nomes = {_norm_autor(n) for n in nomes_cgu} - {""}
    if not alvo or not nomes:
        return None
    return any(f" {alvo} " in f" {n} " or f" {n} " in f" {alvo} " for n in nomes)


def estrategia_pela_amostra(v: dict) -> str:
    """'codigo' (derivar) ou 'ano_numero' (plano B), pelo veredito da amostra.

    Divergencia ISOLADA nao muda a estrategia — nem para a rodada, como fazia o
    veto antigo: a conferencia por emenda (`_confere_autor`) trata aquela emenda
    e deixa as outras seguirem."""
    if v["taxa"] < TAXA_MINIMA:
        return "ano_numero"
    if v["achou"] and v["autor_diverge"] / v["achou"] > DIVERGENCIA_MAXIMA:
        return "ano_numero"
    return "codigo"


def _confere_autor(client, codigo: str, ano, itens: list[dict], confirmado: bool,
                   autor_dump, estrategia: str,
                   orc: Orcamento) -> "tuple[list[dict], bool, dict | None]":
    """(itens, confirmado, divergencia) — a conferencia de autor POR EMENDA.

    - autor bate, ou nao ha como comparar: segue como veio;
    - diverge no codigo DERIVADO: pergunta o codigo oficial a CGU (plano B,
      ano + numero) so para esta emenda; se ai o autor bater, usa o verdadeiro;
    - diverge mesmo assim: devolve itens VAZIOS e a divergencia. A emenda e
      pulada — nada dela e gravado — e anotada com os dois nomes, para se saber
      qual foi. Numero plausivel de OUTRO deputado continua sendo o pior
      desfecho, so que agora ele barra UMA emenda, e nao a noite inteira."""
    if mesmo_autor(autor_dump, (i.get("nomeAutor") for i in itens)) is not False:
        return itens, confirmado, None
    if estrategia != "ano_numero" and ano and len(codigo) == 12:
        oficiais = agregado_por_ano_numero(client, int(ano), codigo[4:], orc)
        if oficiais and mesmo_autor(autor_dump, (i.get("nomeAutor") for i in oficiais)):
            log.info("  %s: autor divergia no codigo derivado; o plano B achou a "
                     "emenda certa", codigo)
            return oficiais, True, None
    nomes_cgu = sorted({(i.get("nomeAutor") or "").strip() for i in itens} - {""})
    return [], False, {"codigo": codigo, "dump": (autor_dump or "").strip(),
                       "cgu": ", ".join(nomes_cgu)[:80]}


def validar_hipotese(client: httpx.Client, amostra: list[tuple],
                     orc: Orcamento) -> dict:
    """Testa `AMOSTRA` codigos SEM GRAVAR NADA. Devolve o veredito.

    ⚠️ AS FALHAS DA AMOSTRA NAO SAO PERSISTIDAS. Marcar 2.400 codigos como
    "inexistentes" por causa de um defeito NOSSO os enterraria no backoff por um
    mes — o erro ficaria caro justamente por ter sido detectado.
    """
    achou = 0
    autor_bate = 0
    autor_diverge = 0
    for codigo, ano, _origem, autor_dump in amostra:
        if not orc.pode():
            break
        try:
            itens = agregado_da_emenda(client, codigo, orc)
        except (Bloqueado, httpx.HTTPError):
            break
        if not itens:
            continue
        achou += 1
        bate = mesmo_autor(autor_dump, (i.get("nomeAutor") for i in itens))
        if bate is True:
            autor_bate += 1
        elif bate is False:
            autor_diverge += 1
    total = max(1, len(amostra))
    return {"testados": len(amostra), "achou": achou,
            "taxa": achou / total, "autor_bate": autor_bate,
            "autor_diverge": autor_diverge}


def execucao(cur, conn, client: httpx.Client, orc: Orcamento,
             dry: bool = False) -> dict:
    """FASE 2 — pergunta a CGU sobre cada codigo da fila."""
    rel = {"consultados": 0, "achou": 0, "documentos": 0, "pendentes": 0,
           "bloqueado": False, "estrategia": ESTRATEGIA, "truncados": [],
           "autor_divergente": [], "colegiado_sem_documentos": 0}
    cnpjs = list(alvos(cur).keys())
    # ⚠️ LIMPAR ANTES DE SEMEAR: a fila e persistente, e o filtro da
    # semeadura so vale para codigo NOVO. Sem isto, o orfao da rodada
    # anterior continua consumindo a cota para sempre.
    removidos = limpar_fila_orfa(cur, cnpjs)
    if removidos:
        log.info("  fila: -%d codigo(s) orfao(s) removido(s)", removidos)
    semeados = semear_fila(cur, cnpjs)
    if not dry:
        conn.commit()
    log.info("  fila: +%d codigo(s) novo(s)", semeados)

    pendentes = fila(cur, MAX_REQ)
    if not pendentes:
        return rel

    # O autor do dump de CADA codigo da fila: e o criterio da conferencia por
    # emenda no laco abaixo, e nao so da amostra.
    cur.execute("""SELECT codigo_emenda, max(parlamentar)
                     FROM emendas_federais_carteira
                    WHERE codigo_emenda = ANY(%s) GROUP BY 1""",
                ([p[0] for p in pendentes],))
    autores = dict(cur.fetchall())

    # ⚠️ A AMOSTRA ESCOLHE A ESTRATEGIA, E NAO PARA MAIS A RODADA. Ate
    # 11/09/2026 UMA divergencia de autor em 20 abortava a fase 2 inteira — e,
    # como a fila poe primeiro quem nunca foi consultado e o aborto nao consultava
    # ninguem, a MESMA amostra voltava na noite seguinte: o veto se renovava
    # sozinho, para sempre. Freitas e trust pararam assim ("autor bate em 19,
    # diverge em 1"). O pior desfecho (numero plausivel de OUTRO deputado)
    # continua barrado, agora POR EMENDA, em `_confere_autor`.
    estrategia = ESTRATEGIA
    if estrategia == "auto":
        amostra = [(p[0], p[1], p[2], autores.get(p[0])) for p in pendentes[:AMOSTRA]]
        v = validar_hipotese(client, amostra, orc)
        log.info("  amostra: %d/%d encontrados (taxa %.0f%%), autor bate em %d, "
                 "diverge em %d", v["achou"], v["testados"], v["taxa"] * 100,
                 v["autor_bate"], v["autor_diverge"])
        estrategia = estrategia_pela_amostra(v)
        if estrategia == "ano_numero":
            log.warning("  amostra reprovou a derivacao (taxa %.0f%%, %d divergente[s]) "
                        "— rodada inteira no plano B, ano+numeroEmenda",
                        v["taxa"] * 100, v["autor_diverge"])
    rel["estrategia"] = estrategia

    lote_cgu: list[dict] = []
    lote_doc: list[dict] = []
    marcas: list[tuple] = []
    for codigo, ano, _origem, tipo in pendentes:
        if not orc.pode():
            rel["pendentes"] = len(pendentes) - rel["consultados"]
            break
        try:
            itens, confirmado = _consulta_um(client, codigo, ano, estrategia, orc)
            divergencia = None
            if itens:
                itens, confirmado, divergencia = _confere_autor(
                    client, codigo, ano, itens, confirmado, autores.get(codigo),
                    estrategia, orc)
        except Bloqueado as e:
            log.warning("  %s", e)
            rel["bloqueado"] = True
            break
        except httpx.HTTPError as e:
            # ⚠️ `None`, E NAO `False`. `False` significa "perguntamos e a CGU
            # NAO CONHECE este codigo" — uma AFIRMACAO, que a tela imprime como
            # «Sem registro na CGU». Timeout, 500 e 503 nao afirmam nada sobre a
            # emenda: sao ausencia NOSSA. Gravar False aqui trocava um problema
            # de rede por uma acusacao ao dado, e ainda queimava uma das tres
            # tentativas do backoff.
            marcas.append((codigo, None, 0, str(e)[:200]))
            continue
        rel["consultados"] += 1
        if divergencia:
            # Pulada e ANOTADA: nada desta emenda e gravado. `None` no achou,
            # como no erro de rede — nao afirmamos nada sobre ela —, e o
            # carimbo de consulta tira o codigo da frente da fila, que era o que
            # fazia o veto antigo se repetir toda noite.
            log.warning("  %s: autor divergente — dump '%s', CGU '%s' — emenda "
                        "PULADA (nada gravado)", codigo, divergencia["dump"],
                        divergencia["cgu"])
            rel["autor_divergente"].append(divergencia)
            marcas.append((codigo, None, 0,
                           f"autor divergente: dump '{divergencia['dump']}', "
                           f"CGU '{divergencia['cgu']}'"[:200]))
            continue
        docs: list[dict] = []
        # ⚠️ O CODIGO DA CGU, QUANDO ELA O DEU. Com o plano B o codigo oficial
        # pode diferir do derivado — e buscar a linha do tempo pelo DERIVADO
        # traria os pagamentos da emenda de OUTRO deputado. Enquanto derivado e
        # oficial coincidiam este caminho era no-op; a conferencia por emenda o
        # tornou real.
        cod_cgu = ((itens[0].get("codigoEmenda") or "").strip() or codigo
                   if confirmado and itens else codigo)
        if itens:
            rel["achou"] += 1
            for x in itens:
                linha = linha_cgu(x)
                if not linha["codigo_emenda"]:
                    linha["codigo_emenda"] = cod_cgu
                lote_cgu.append(linha)
            colegiado = (tipo or "").strip().upper() in TIPOS_COLEGIADO
            if colegiado:
                rel["colegiado_sem_documentos"] += 1
            if orc.pode() and not colegiado:
                try:
                    brutos, completo = documentos_da_emenda(client, cod_cgu, orc)
                    docs = [d for d in (linha_documento(cod_cgu, b) for b in brutos) if d]
                    lote_doc.extend(docs)
                    rel["documentos"] += len(docs)
                    # ⚠️ TRUNCOU = A RODADA E `partial`, e nao `success`. Sem
                    # isto, uma emenda cortada no teto vira "pagamentos
                    # faltando" com luz verde no monitor — que e o modo de falha
                    # que este repo mais paga caro. Medido: com o teto de 20,
                    # QUATRO emendas de Nova Palma truncaram em silencio.
                    if not completo:
                        rel["truncados"].append(cod_cgu)
                except Bloqueado:
                    rel["bloqueado"] = True
                    break
                except httpx.HTTPError:
                    pass
        marcas.append((codigo, bool(itens), len(docs), None))
        if confirmado and itens and not dry:
            # ⚠️⚠️ O PLANO B SÓ FUNCIONA SE ELE CORRIGIR A CARTEIRA. A estratégia
            # `ano_numero` existe para descobrir o `codigoEmenda` VERDADEIRO
            # quando o derivado estiver errado — mas gravava o agregado sob o
            # verdadeiro e deixava a carteira com o derivado, e aí o JOIN da tela
            # nunca casaria: a noite inteira de requisições produziria uma tela
            # idêntica à de antes.
            #
            # Hoje a hipótese está confirmada (20/20 na amostra), então derivado
            # e verdadeiro coincidem e este UPDATE é no-op. Ele existe para o dia
            # em que deixarem de coincidir — que é o único dia em que o plano B
            # importa.
            verdadeiro = (itens[0].get("codigoEmenda") or "").strip()
            if verdadeiro and verdadeiro != codigo:
                log.info("  %s -> codigo verdadeiro %s (plano B corrigiu a "
                         "carteira)", codigo, verdadeiro)
                cur.execute("UPDATE emendas_federais_carteira "
                            "SET codigo_emenda = %s, codigo_confirmado = TRUE "
                            "WHERE codigo_emenda = %s", (verdadeiro, codigo))
                cur.execute("UPDATE emendas_federais_consulta "
                            "SET codigo_emenda = %s WHERE codigo_emenda = %s "
                            "  AND NOT EXISTS (SELECT 1 FROM "
                            "      emendas_federais_consulta z "
                            "      WHERE z.codigo_emenda = %s)",
                            (verdadeiro, codigo, verdadeiro))
                # A marca acima foi feita sob o DERIVADO, e o UPDATE acabou de
                # renomear a linha da fila: sem esta segunda marca o carimbo se
                # perde e o codigo volta ao topo da fila na noite seguinte.
                marcas.append((verdadeiro, True, len(docs), None))
            else:
                cur.execute("UPDATE emendas_federais_carteira "
                            "SET codigo_confirmado = TRUE "
                            "WHERE codigo_emenda = %s", (codigo,))
        if not dry and len(marcas) >= 50:
            _gravar(cur, conn, lote_cgu, lote_doc, marcas)
            lote_cgu, lote_doc, marcas = [], [], []

    if not dry:
        _gravar(cur, conn, lote_cgu, lote_doc, marcas)
    return rel


def _gravar(cur, conn, lote_cgu, lote_doc, marcas) -> None:
    import psycopg2.extras
    if lote_cgu:
        psycopg2.extras.execute_batch(cur, _SQL_CGU, lote_cgu, page_size=100)
    if lote_doc:
        psycopg2.extras.execute_batch(cur, _SQL_DOC, lote_doc, page_size=200)
    for codigo, achou, ndocs, erro in marcas:
        cur.execute("""
            UPDATE emendas_federais_consulta
               SET consultado_em = NOW(),
                   agregados_em = CASE WHEN %s THEN NOW() ELSE agregados_em END,
                   documentos_em = CASE WHEN %s > 0 THEN NOW() ELSE documentos_em END,
                   achou_agregado = %s, n_documentos = %s,
                   tentativas = CASE WHEN %s THEN 0 ELSE tentativas + 1 END,
                   ultimo_erro = %s
             WHERE codigo_emenda = %s
        """, (achou, ndocs, achou, ndocs, achou, erro, codigo))
    conn.commit()


def _log_ingest(cur, conn, status: str, n: int, erro: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) "
            "VALUES (%s, %s, %s, %s, NOW())", (FONTE, status, n, erro))
        conn.commit()
    except Exception as e:
        log.warning("ingestion_log falhou: %s", str(e)[:120])


def _recente_demais(cur) -> bool:
    """Auto-limite de 20h, no molde do `obrasgov`.

    ⚠️ A RODADA INERTE NAO CONTA COMO COLETA. Ela grava `success` com a nota
    "sem chave" — e sem este filtro, no dia em que a chave for preenchida a
    PRIMEIRA rodada de verdade seria pulada por causa de uma linha que nao
    coletou nada. Um dia de atraso, em silencio, justamente no unico dia em que
    alguem esta olhando.
    """
    if os.getenv("PT_FORCE") == "1":
        return False
    cur.execute(
        "SELECT max(finished_at) FROM ingestion_log "
        # ⚠️ `partial` CONTA como rodada. Ele e o estado PERMANENTE de qualquer
        # tenant com municipio sem CNPJ — e ignora-lo aqui faria a fonte rodar em
        # TODA janela do cron, para sempre, gastando dump e cota por um estado
        # que nao muda sozinho.
        "WHERE source = %s AND status IN ('success','ok','partial','parcial') "
        "  AND coalesce(error_message, '') NOT LIKE 'sem PORTAL%%'", (FONTE,))
    ultimo = (cur.fetchone() or [None])[0]
    if not ultimo:
        return False
    horas = (datetime.now(ultimo.tzinfo) - ultimo).total_seconds() / 3600
    if horas < MIN_INTERVAL_H:
        log.info("ultima coleta ha %.1fh (< %dh) — pulando. PT_FORCE=1 forca.",
                 horas, MIN_INTERVAL_H)
        return True
    return False


NOTA_SEM_CHAVE = (
    "sem PORTAL_TRANSPARENCIA_API_KEY — coletor inerte por decisao. A chave sai "
    "de portaldatransparencia.gov.br/api-de-dados/cadastrar-email com conta "
    "gov.br Prata/Ouro e fica vinculada ao CPF de quem a cadastrou.")


def ingest(dry: bool = False) -> int:
    """Fase 1 sempre (se ligada); fase 2 so com chave.

    ⚠️ O INERTE CONTINUA VALENDO quando as duas estao desligadas: sai como
    `success`, NAO como erro. Fonte que ninguem ligou nao e fonte quebrada, e
    marca-la assim faria o watchdog alarmar para sempre sobre uma escolha
    deliberada. Mesmo desenho do `fpe_rs.py`.
    """
    from ingestion._resilience import get_sync_db_url, neon_connect

    if not CARTEIRA_LIGADA and not habilitado():
        log.info("Portal da Transparencia: %s", NOTA_SEM_CHAVE)
        if not dry:
            with neon_connect(get_sync_db_url()) as conn:
                cur = conn.cursor()
                try:
                    _log_ingest(cur, conn, "success", 0, NOTA_SEM_CHAVE)
                finally:
                    cur.close()
        return 0

    status, nota, gravadas = "success", None, 0
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            if not dry and _recente_demais(cur):
                return 0

            # ---- FASE 1 -------------------------------------------------
            rel = {"gravadas": 0, "sem_cnpj": [], "sem_codigo": 0, "codigos": set(),
                   "do_municipio": 0, "linhas": 0, "colisoes": 0}
            if CARTEIRA_LIGADA:
                rel = carteira(cur, conn, dry)
                gravadas = rel["gravadas"]
                log.info("carteira: %d linha(s) do dump, %d do municipio, %d "
                         "gravada(s), %d sem codigo, %d codigo(s) distinto(s)",
                         rel["linhas"], rel["do_municipio"], rel["gravadas"],
                         rel["sem_codigo"], len(rel["codigos"]))
                if rel["colisoes"]:
                    log.warning("  %d colisao(oes) na chave natural do dump — a "
                                "tripla pode nao ser unica; conferir", rel["colisoes"])
                if not alvos(cur):
                    _log_ingest(cur, conn, "partial", 0,
                                "nenhum municipio ativo com CNPJ conhecido — rode "
                                "ingestion/siconfi.py, que preenche municipios.cnpj "
                                "do cadastro de entes do Tesouro")
                    return 0
                if rel["sem_cnpj"]:
                    status = "partial"
                    nota = ("sem CNPJ cadastrado (a emenda e reconhecida por ele): "
                            + ", ".join(rel["sem_cnpj"][:5]))

            # ---- FASE 2 -------------------------------------------------
            if not habilitado():
                if status == "success":
                    nota = (f"carteira: {gravadas} linha(s); execucao CGU nao "
                            "coletada (sem PORTAL_TRANSPARENCIA_API_KEY)")
                if not dry:
                    _log_ingest(cur, conn, status, gravadas, nota)
                return gravadas

            # Freio e tamanho-de-pagina sao estado de RODADA, nao de processo:
            # um processo que rode duas vezes nao pode herdar o freio da
            # primeira nem o tamanho de pagina aprendido em outro endpoint.
            globals()["_REQUISICOES"] = 0
            globals()["_TAM_PAGINA"] = None
            orc = Orcamento(ORCAMENTO_S, MAX_REQ)
            with httpx.Client(follow_redirects=True) as client:
                ex = execucao(cur, conn, client, orc, dry)
            log.info("execucao: %d consultado(s), %d encontrado(s), %d "
                     "documento(s), estrategia=%s, %d requisicao(oes); "
                     "%d de colegiado sem linha do tempo (por desenho)",
                     ex["consultados"], ex["achou"], ex["documentos"],
                     ex["estrategia"], orc.gastas,
                     ex["colegiado_sem_documentos"])
            partes = []
            if ex["bloqueado"]:
                partes.append("429 da CGU — fase de execucao interrompida SEM retentativa")
            if ex["truncados"]:
                # ⚠️ `partial`, e a lista vai na nota: emenda truncada e
                # PAGAMENTO FALTANDO na tela. Deixar passar como `success` seria
                # exatamente o "coleta truncada em silencio" que o proprio
                # `paginar` existe para impedir.
                partes.append(f"{len(ex['truncados'])} emenda(s) com documentos "
                              f"TRUNCADOS no teto de {TETO_DOCUMENTOS} paginas: "
                              + ", ".join(ex["truncados"][:5])
                              + " — suba PT_TETO_DOCUMENTOS")
            if ex["autor_divergente"]:
                # Emenda PULADA e execucao faltando na tela: `partial`, com os
                # dois nomes na nota — e o que permite resolver sem abrir log.
                partes.append(f"{len(ex['autor_divergente'])} emenda(s) com autor "
                              "divergente na CGU, nao gravadas: "
                              + "; ".join(f"{d['codigo']} (dump '{d['dump']}', "
                                          f"CGU '{d['cgu']}')"
                                          for d in ex["autor_divergente"][:3]))
            if partes:
                status, nota = "partial", " | ".join(partes)[:400]
            elif ex["pendentes"]:
                # ⚠️ `success`, e nao `partial`: a primeira carga de um tenant
                # grande leva tres madrugadas e isso NAO e defeito. E o desenho
                # do `tce_rs_portal`; marca-la degradada faria a fonte nascer
                # eternamente vermelha e ensinaria a ignorar a cor.
                nota = (f"orcamento esgotado: {ex['pendentes']} codigo(s) "
                        "pendente(s) para a proxima rodada")
        except PermissionError as e:
            status, nota = "error", str(e)[:400]
            log.error("Portal da Transparencia: %s", nota)
        except Exception as e:
            conn.rollback()
            status = "error"
            nota = f"{type(e).__name__}: {str(e)[:380]}"
            log.error("Portal da Transparencia: %s", nota)
        finally:
            if not dry:
                _log_ingest(cur, conn, status, gravadas, nota)
            cur.close()
    return gravadas


def verificar() -> int:
    """`--verificar`: testa a hipotese do codigo SEM gravar nada.

    A leitura do resultado, escrita antes de rodar para nao virar racionalizacao:

      controle (TE) responde · derivados respondem  -> hipotese CONFIRMADA
      controle responde      · derivados 0%         -> o FORMATO esta certo, a
                                                       DERIVACAO nao: use
                                                       PT_ESTRATEGIA=ano_numero
      controle 0%                                   -> nao e a hipotese: e a
                                                       chave, o endpoint ou o
                                                       parametro. NAO mexer na
                                                       formula.
    """
    from ingestion._resilience import get_sync_db_url, neon_connect
    if not habilitado():
        log.error("--verificar precisa de PORTAL_TRANSPARENCIA_API_KEY")
        return 1
    orc = Orcamento(300, 80)
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            semear_fila(cur, list(alvos(cur).keys()))
            conn.commit()
            with httpx.Client(follow_redirects=True) as client:
                for origem in ("transferegov_te", "siconv"):
                    cur.execute("""
                        SELECT c.codigo_emenda, c.ano, c.origem,
                               (SELECT max(parlamentar) FROM emendas_federais_carteira
                                 WHERE codigo_emenda = c.codigo_emenda)
                          FROM emendas_federais_consulta c
                         WHERE c.origem = %s LIMIT 5""", (origem,))
                    amostra = list(cur.fetchall())
                    if not amostra:
                        log.info("%s: nenhum codigo para testar", origem)
                        continue
                    v = validar_hipotese(client, amostra, orc)
                    log.info("%s (%s): %d/%d encontrados, autor bate %d, diverge %d",
                             origem,
                             "GRUPO DE CONTROLE — formatado pelo Governo"
                             if origem == "transferegov_te" else "derivado por nos",
                             v["achou"], v["testados"], v["autor_bate"],
                             v["autor_diverge"])
        finally:
            cur.close()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    if "--verificar" in sys.argv:
        sys.exit(verificar())
    ingest(dry="--dry" in sys.argv)
