"""LICITAÇÕES dos instrumentos federais pelo DADO ABERTO — sem login gov.br.

⭐ POR QUE ISTO EXISTE. O "Processo de Execução (Licitações)" — a bandeira que
responde *"o município já licitou o convênio que assinou?"* — só vinha da tela
LOGADA do SICONV antigo (`transferegov_http.processo_execucao_lista`). E sessão
gov.br é a peça mais frágil da coleta: ela morreu em 02/09/2026 e ficou sete dias
morta sem ninguém notar, com 153 de 153 leituras atrás do login voltando vazias.

O mesmo dado está PÚBLICO, num arquivo que a própria TransfereGov publica todo
dia (conferido em 09/09/2026: `last-modified` do mesmo dia, 26,7 MB, 972.052
licitações). Os seis campos que a tela logada entregava têm correspondente exato
no CSV — e o dump traz de bônus valor, nº do processo e data de homologação, que
a tela não dava:

    numero          <- NR_LICITACAO
    modalidade      <- MODALIDADE_LICITACAO, ou TP_PROCESSO_COMPRA
    data_publicacao <- DATA_PUBLICACAO_LICITACAO
    situacao        <- STATUS_LICITACAO
    sistema_origem  <- SISTEMA_ORIGEM
    aceite          <- SITUACAO_ACEITE_PROCESSO_EXECU

⚠️ **`MODALIDADE_LICITACAO` VEM VAZIA NA MAIORIA.** Medido no dump inteiro: as
duas maiores fatias são «Cotação Prévia de Preços» (230.911) e «Dispensa de
Licitação» (195.654), e nas duas a modalidade é VAZIA — quem carrega o texto é
`TP_PROCESSO_COMPRA`. Ler só a primeira coluna deixaria 40% das contratações sem
rótulo na tela, parecendo defeito nosso.

⚠️ **O VALOR NÃO TEM SEPARADOR DE MILHAR, E A VÍRGULA É DECIMAL.** 630.998 linhas
vêm inteiras ("6300") e 339.878 com vírgula ("196,32"); ponto não aparece em
nenhuma. Tratar "6300" como 63,00 (ou "196,32" como 19.632) erraria por duas
ordens de grandeza — e um valor plausível e errado não tem como ser percebido
depois.

⚠️ **AUSÊNCIA NO DUMP NÃO APAGA O QUE O LOGIN VIU.** Convênio nosso sem linha
aqui vira `qtd = 0` — que é informação boa e é a bandeira "assinou e não
licitou". Mas SÓ quando ainda não sabíamos nada (`qtd IS NULL`). Se uma captura
anterior já tinha achado licitação, o vazio de hoje é tratado como atraso do
dump (que é diário), não como licitação que sumiu: o erro nessa direção pintaria
de "parado" um município que licitou, que é exatamente o alarme falso mais caro
que este produto pode dar.

Casa por `NR_CONVENIO` = `transferegov_propostas.codigo_instrumento` — o mesmo
join que o `siconv_convenio_backfill` já usa em produção.

Entry: main() / coletar(). Roda pendurado no run() diário do
`transferegov_voluntarias`, junto dos outros dois backfills de dado aberto.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("siconv_licitacao")

URL = "https://api-publica.transferegov.gestao.gov.br/downloads/dadosgov/siconv_licitacao.zip"
_CACHE_DIR = os.getenv("SICONV_CACHE_DIR") or os.path.join(
    os.getenv("TEMP") or os.getenv("TMPDIR") or "/tmp", "siconv_opendata"
)


def _db():
    import psycopg2
    url = os.getenv("DATABASE_URL_SYNC", "")
    url = url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    return psycopg2.connect(url)


def _download(use_cache: bool = True) -> bytes:
    import httpx
    path = os.path.join(_CACHE_DIR, "siconv_licitacao.zip")
    if use_cache and os.path.exists(path) and os.path.getsize(path) > 1000:
        return open(path, "rb").read()
    logger.info(f"  baixando {URL} ...")
    r = httpx.get(URL, timeout=900, verify=False, follow_redirects=True)
    r.raise_for_status()
    if use_cache:
        try:
            os.makedirs(_CACHE_DIR, exist_ok=True)
            open(path, "wb").write(r.content)
        except OSError:
            pass
    logger.info(f"  baixado {len(r.content)} bytes")
    return r.content


def valor(bruto: str):
    """Reais do dump. Vírgula é DECIMAL; separador de milhar não existe.

    Devolve None (nunca 0.0) para vazio e para lixo: zero é uma afirmação — "a
    licitação foi de R$ 0" — e afirmar isso por falta de dado é mentir para
    baixo."""
    s = (bruto or "").strip()
    if not s:
        return None
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def item(g) -> dict:
    """Uma licitação no MESMO formato que a tela logada produzia.

    As seis primeiras chaves são as que o front já sabe desenhar; mexer nelas
    quebraria a tela sem aviso. As de baixo são acréscimo — o dump sabe mais que
    a tela sabia."""
    return {
        "numero": g("NR_LICITACAO") or None,
        # A ordem importa: a modalidade só existe em «Licitação»; nas dispensas,
        # cotações e inexigibilidades quem tem o texto é o tipo de processo.
        "modalidade": g("MODALIDADE_LICITACAO") or g("TP_PROCESSO_COMPRA") or None,
        "data_publicacao": g("DATA_PUBLICACAO_LICITACAO") or None,
        "situacao": g("STATUS_LICITACAO") or None,
        "sistema_origem": g("SISTEMA_ORIGEM") or None,
        "aceite": g("SITUACAO_ACEITE_PROCESSO_EXECU") or None,
        # Acréscimos do dado aberto.
        "tipo_processo": g("TP_PROCESSO_COMPRA") or None,
        "processo": g("NR_PROCESSO_LICITACAO") or None,
        "data_homologacao": g("DATA_HOMOLOGACAO_LICITACAO") or None,
        "valor": valor(g("VALOR_LICITACAO")),
        # De onde veio, para quem for depurar a tela daqui a um ano.
        "fonte": "dado_aberto",
    }


def por_convenio(conteudo: bytes, convenios: set) -> dict:
    """{NR_CONVENIO: [licitações]} apenas para os convênios pedidos.

    Streaming de propósito: são 972 mil linhas e 118 MB descompactados; carregar
    tudo em memória custaria mais que o worker inteiro tem."""
    z = zipfile.ZipFile(io.BytesIO(conteudo))
    nome = z.namelist()[0]
    # ⚠️ `utf-8-sig`, medido nos bytes: o arquivo começa com BOM (EF BB BF) e o
    # corpo é UTF-8 (`Licitação` = ...Ã§Ã£o). Ler como latin-1 — o que
    # este módulo fazia na primeira versão — não dá erro nenhum: grava
    # "Dispensa de LicitaÃ§Ã£o" no banco e o defeito só aparece na tela do
    # cliente. O `-sig` ainda come o BOM, que senão vira `﻿ID_LICITACAO` e
    # desalinha o cabeçalho inteiro.
    rd = csv.reader(io.TextIOWrapper(z.open(nome), encoding="utf-8-sig",
                                     errors="replace", newline=""), delimiter=";")
    cab = [h.strip().lstrip("﻿") for h in next(rd)]
    ix = {h: i for i, h in enumerate(cab)}
    achados: dict[str, list] = {}
    for linha in rd:
        def g(k, _l=linha):
            j = ix.get(k)
            return _l[j].strip() if j is not None and j < len(_l) else ""
        nrc = g("NR_CONVENIO")
        if nrc and nrc in convenios:
            achados.setdefault(nrc, []).append(item(g))
    return achados


def coletar(use_cache: bool = True) -> int:
    """Preenche processo_execucao/qtd das federais. Devolve linhas atualizadas."""
    conn = _db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, codigo_instrumento, processo_execucao_qtd "
                    "FROM transferegov_propostas "
                    "WHERE codigo_instrumento IS NOT NULL AND codigo_instrumento <> ''")
        linhas = cur.fetchall()
        # Um convênio pode aparecer em mais de um município (consórcio) — por
        # isso lista de ids, e não um id só.
        por_codigo: dict[str, list] = {}
        qtd_atual: dict[int, int | None] = {}
        for rid, cod, qtd in linhas:
            por_codigo.setdefault(str(cod).strip(), []).append(rid)
            qtd_atual[rid] = qtd
        if not por_codigo:
            logger.info("siconv_licitacao: nenhum instrumento celebrado — nada a fazer")
            _log(cur, conn, "success", 0)
            return 0

        achados = por_convenio(_download(use_cache=use_cache), set(por_codigo))
        logger.info("siconv_licitacao: %d de %d convenio(s) com licitacao no dump",
                    len(achados), len(por_codigo))

        n = zerados = preservados = 0
        for cod, ids in por_codigo.items():
            lista = achados.get(cod)
            for rid in ids:
                if lista:
                    cur.execute(
                        "UPDATE transferegov_propostas SET processo_execucao = %s::jsonb, "
                        "processo_execucao_qtd = %s WHERE id = %s",
                        (json.dumps(lista, ensure_ascii=False), len(lista), rid))
                    n += cur.rowcount
                elif qtd_atual.get(rid) is None:
                    # Nunca soubemos: "nenhuma licitação registrada" É a notícia.
                    cur.execute(
                        "UPDATE transferegov_propostas SET processo_execucao = '[]'::jsonb, "
                        "processo_execucao_qtd = 0 WHERE id = %s", (rid,))
                    n += cur.rowcount
                    zerados += 1
                else:
                    # Já sabíamos de licitação e o dump não a trouxe hoje: atraso
                    # do arquivo, não licitação que sumiu. Ver o ⚠️ do topo.
                    preservados += 1
        conn.commit()
        logger.info("siconv_licitacao: %d linha(s) atualizadas (%d zeradas por ausencia, "
                    "%d preservadas)", n, zerados, preservados)
        _log(cur, conn, "success", n)
        return n
    except Exception as e:
        conn.rollback()
        logger.error("siconv_licitacao falhou: %s: %s", type(e).__name__, str(e)[:200])
        _log(cur, conn, "erro", 0, f"{type(e).__name__}: {str(e)[:300]}")
        raise
    finally:
        cur.close()
        conn.close()


def _log(cur, conn, status: str, n: int, erro: str | None = None):
    try:
        cur.execute("INSERT INTO ingestion_log (source, status, records_inserted, "
                    "error_message, finished_at) "
                    "VALUES ('siconv_licitacao', %s, %s, %s, NOW())", (status, n, erro))
        conn.commit()
    except Exception as e:
        logger.warning("ingestion_log falhou: %s", str(e)[:120])


def main(use_cache: bool = True):
    logger.info("=== SICONV licitacoes (dado aberto, sem login) ===")
    coletar(use_cache=use_cache)
    logger.info("=== fim ===")


if __name__ == "__main__":
    main(use_cache="--no-cache" not in sys.argv)
