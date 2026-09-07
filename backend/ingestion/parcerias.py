"""GESTAO DE PARCERIAS do Transferegov.br -> tabela `parcerias_propostas`.

⭐ A FONTE ONDE A EMENDA DE SAUDE PASSOU A VIVER. O modulo de Parcerias foi
publicado no Comunicado no 23/2026 do MGI e **nao substitui o SICONV** — os
convenios discricionarios continuam nos dumps CSV que `transferegov_opendata.py`
le. Ele e onde as transferencias sao processadas de 2024 em diante: dos 176
programas publicados, **144 sao Transferencias Fundo a Fundo da Saude** (medido
em 06/09/2026). Era o unico instrumento federal que a plataforma nao enxergava.

A cadeia, conferida com dado real (Nova Palma, proposta 75376):

    /proposta?cd_ibge_recebedor=4313102 ..... 11 propostas, R$ 2,18 mi
      └─ ds_objeto "AQUISICAO DE EQUIPAMENTO PARA UNIDADE BASICA DE SAUDE"
      └─ /parceria?id_proposta=75376 ........ o instrumento celebrado
      └─ /distribuicao-recurso-proposta ..... emenda 2026.2023.0002,
                                             PAULO PAIM, Individual, GND4,
                                             R$ 299.999

⚠️ O FILTRO TERRITORIAL E DE PRIMEIRA CLASSE, ao contrario do
`/projeto-investimento` do Obras.gov: `cd_ibge_recebedor` filtra no servidor (11
de 89.400 para Nova Palma). Nao ha casamento por CNPJ nem por nome — e portanto
nao ha a classe de erro que o `obrasgov.py` descreve no cabecalho inteiro.

⚠️ QUEM RECEBE RARAMENTE E A PREFEITURA. As 11 propostas de Nova Palma sao TODAS
do FUNDO MUNICIPAL DA SAUDE, com CNPJ proprio (12240183000100, diferente do
88488358000156 da prefeitura). Um coletor que entrasse por `municipios.cnpj` —
como o da Transferencia Especial faz, e com razao la — nao acharia nenhuma.

⚠️ O NUCLEO, E NAO A CADEIA INTEIRA. A execucao financeira (empenho ->
documento habil -> ordem de pagamento -> extrato) fica para depois, por CUSTO
medido: buscar os 8 filhos de cada proposta custaria 4.418 requisicoes no
freitas (27 min) e 5.668 no trust (35 min), contra 1.136 e 1.432 do nucleo. O
`/extrato-bancario` sozinho tem 1.275.217 registros — 6.377 paginas — e nunca
podera ser varrido inteiro.

Rodar:  python -u ingestion/parcerias.py
        python -u ingestion/parcerias.py --dry     (varre e mostra, sem gravar)
"""
from __future__ import annotations
import json
import logging
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("parcerias")

# ⚠️ `api-publica`, e nao `api`. Mesma pegadinha do Obras.gov.br e do modulo de
# Especiais: o host sem o prefixo e o que bloqueia.
BASE = os.getenv("PARCERIAS_BASE",
                 "https://api-publica.transferegov.gestao.gov.br/parcerias")
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0 dados abertos Transferegov)",
      "Accept": "application/json"}
TIMEOUT = 60
# Envelope de todo endpoint: {data, total_pages, total_items, page_number,
# page_size}. `pagina` e 1-based e `tamanho_da_pagina` tem teto 200 (201 -> 422).
TAMANHO_PAGINA = 200
PAUSA_S = float(os.getenv("PARCERIAS_PAUSA_S", "0.2") or "0.2")
TETO_PAGINAS = int(os.getenv("PARCERIAS_TETO_PAGINAS", "400") or "400")
# Orcamento da rodada. Medido: o nucleo custa ~420 s no freitas (547 propostas)
# e ~530 s no trust (706). O teto deixa folga para a fonte estar lenta sem que a
# rodada seja degolada no meio — ela retoma pelo que ficou.
BUDGET_S = float(os.getenv("PARCERIAS_BUDGET_S", "1200") or "1200")
MIN_INTERVAL_H = int(os.getenv("PARCERIAS_MIN_INTERVAL_H", "20") or "20")


def _pagina(client: httpx.Client, caminho: str, params: dict, n: int) -> dict | None:
    """Uma pagina. `None` = a fonte nao respondeu 200 (e NAO "acabou")."""
    p = {**params, "pagina": n, "tamanho_da_pagina": TAMANHO_PAGINA}
    try:
        r = client.get(f"{BASE}/{caminho}", params=p, headers=UA, timeout=TIMEOUT)
    except Exception as e:
        log.warning("  %s %s: %s", caminho, params, str(e)[:90])
        return None
    if r.status_code != 200:
        # ⚠️ HTTP 500 EM FILTRO DOCUMENTADO EXISTE NESTA FAMILIA DE APIs: o
        # modulo `/fundoafundo` devolve 500 para `codigo_ibge_..._recebedor`,
        # que o proprio Swagger publica (medido 06/09/2026). Por isso o log traz
        # o caminho E os parametros — se aparecer aqui, ele diz qual filtro caiu.
        log.warning("  %s %s: HTTP %s", caminho, params, r.status_code)
        return None
    try:
        return r.json()
    except ValueError:
        log.warning("  %s: resposta nao e JSON", caminho)
        return None


def buscar(client: httpx.Client, caminho: str, params: dict) -> list[dict] | None:
    """Todas as paginas de uma consulta. `None` quando a PRIMEIRA falhou.

    A distincao importa: `[]` e "a fonte respondeu e nao ha nada" (municipio sem
    proposta, proposta que nao virou parceria — estados legitimos e comuns),
    enquanto `None` e "nao consegui perguntar". Quem chama usa isso para nao
    gravar silencio como ausencia.
    """
    d = _pagina(client, caminho, params, 1)
    if d is None:
        return None
    itens = list(d.get("data") or [])
    total = min(int(d.get("total_pages") or 1), TETO_PAGINAS)
    for n in range(2, total + 1):
        time.sleep(PAUSA_S)
        d = _pagina(client, caminho, params, n)
        if d is None:
            log.warning("  %s: parou na pagina %d/%d", caminho, n, total)
            break
        itens.extend(d.get("data") or [])
    return itens


def _num(v):
    return v if isinstance(v, (int, float)) else None


def _data(v):
    s = str(v or "").strip()
    return s[:10] if s else None


def linha(municipio_id: int, prop: dict, parceria: dict | None,
          emenda: dict | None) -> dict | None:
    """Traduz UMA proposta (mais o instrumento e a emenda) para as colunas.

    Funcao PURA e testavel: recebe os tres pedacos ja buscados e devolve
    exatamente o que o UPSERT grava.

    ⚠️ `parceria` e `emenda` sao OPCIONAIS de propósito. Proposta em elaboracao
    nao tem instrumento celebrado, e proposta de programa voluntario nao tem
    emenda — os dois sao estado legitimo, e gravar a linha sem eles e melhor do
    que descarta-la: o objeto e o valor ja valem a tela.
    """
    pid = prop.get("id_proposta")
    if pid is None:
        return None
    parceria = parceria or {}
    emenda = emenda or {}
    return {
        "mid": municipio_id,
        "id_proposta": int(pid),
        "id_programa": prop.get("id_programa"),
        "cnpj": (prop.get("cnpj_ente_recebedor") or "")[:14] or None,
        "ente": prop.get("nm_ente_recebedor"),
        "natureza": prop.get("nm_natureza_juridica"),
        "objeto": prop.get("ds_objeto"),
        "problema": prop.get("ds_problema_proposta"),
        "resultado": prop.get("ds_resultado_esperado_proposta"),
        "publico": prop.get("ds_publico_alvo_proposta"),
        "situacao": prop.get("situacao_proposta"),
        # A fonte tem DOIS campos de valor e o preenchido varia: `nr_vlr_total`
        # vem nulo nas propostas que medimos e `vl_total_planejamento_gastos`
        # traz o numero. Tenta os dois, nessa ordem de confianca.
        "valor": _num(prop.get("vl_total_planejamento_gastos")
                      if prop.get("vl_total_planejamento_gastos") is not None
                      else prop.get("nr_vlr_total")),
        "ano": prop.get("ano_proposta"),
        "dt_proposta": _data(prop.get("dt_proposta")),
        "id_parceria": parceria.get("id_parceria"),
        "cd_parceria": (str(parceria["cd_parceria"])
                        if parceria.get("cd_parceria") is not None else None),
        "sit_parceria": parceria.get("in_situacao_parceria"),
        "dt_assinatura": _data(parceria.get("dh_assinatura")),
        "nr_emenda": emenda.get("nr_emenda_proposta"),
        "parlamentar": emenda.get("nm_parlamentar_proposta"),
        "tipo_emenda": emenda.get("in_tipo_emenda_parlamentar_proposta"),
        "vl_emenda": _num(emenda.get("valor_emenda")),
        "raw": json.dumps({**prop, "_parceria": parceria, "_emenda": emenda},
                          ensure_ascii=False),
    }


_SQL = """
INSERT INTO parcerias_propostas (
    municipio_id, id_proposta, id_programa, cnpj_ente_recebedor,
    nome_ente_recebedor, natureza_juridica, objeto, problema,
    resultado_esperado, publico_alvo, situacao, valor_total, ano_proposta,
    data_proposta, id_parceria, codigo_parceria, situacao_parceria,
    data_assinatura, numero_emenda, parlamentar, tipo_emenda, valor_emenda,
    raw_data, atualizado_em)
VALUES (%(mid)s, %(id_proposta)s, %(id_programa)s, %(cnpj)s, %(ente)s,
        %(natureza)s, %(objeto)s, %(problema)s, %(resultado)s, %(publico)s,
        %(situacao)s, %(valor)s, %(ano)s, %(dt_proposta)s, %(id_parceria)s,
        %(cd_parceria)s, %(sit_parceria)s, %(dt_assinatura)s, %(nr_emenda)s,
        %(parlamentar)s, %(tipo_emenda)s, %(vl_emenda)s, %(raw)s::jsonb, NOW())
ON CONFLICT (municipio_id, id_proposta) DO UPDATE SET
    id_programa = EXCLUDED.id_programa,
    cnpj_ente_recebedor = EXCLUDED.cnpj_ente_recebedor,
    nome_ente_recebedor = EXCLUDED.nome_ente_recebedor,
    natureza_juridica = EXCLUDED.natureza_juridica,
    objeto = EXCLUDED.objeto, problema = EXCLUDED.problema,
    resultado_esperado = EXCLUDED.resultado_esperado,
    publico_alvo = EXCLUDED.publico_alvo, situacao = EXCLUDED.situacao,
    valor_total = EXCLUDED.valor_total, ano_proposta = EXCLUDED.ano_proposta,
    data_proposta = EXCLUDED.data_proposta,
    id_parceria = EXCLUDED.id_parceria,
    codigo_parceria = EXCLUDED.codigo_parceria,
    situacao_parceria = EXCLUDED.situacao_parceria,
    data_assinatura = EXCLUDED.data_assinatura,
    numero_emenda = EXCLUDED.numero_emenda, parlamentar = EXCLUDED.parlamentar,
    tipo_emenda = EXCLUDED.tipo_emenda, valor_emenda = EXCLUDED.valor_emenda,
    raw_data = EXCLUDED.raw_data, atualizado_em = NOW()
"""


def _municipios(cur) -> list[dict]:
    """Municipios ATIVOS com IBGE — a chave desta fonte.

    ⚠️ `WHERE active`, pelo mesmo motivo que a Transferencia Especial teve de
    aprender em producao (07/09/2026): sem ele, o coletor gasta requisicao com
    municipio que o cliente nao acompanha mais. No freitas sao 18 dos 60.
    """
    cur.execute("""
        SELECT id, nome, coalesce(ibge_code, '')
          FROM municipios
         WHERE active AND length(coalesce(ibge_code, '')) = 7
         ORDER BY nome
    """)
    return [{"id": r[0], "nome": r[1], "ibge": r[2]} for r in cur.fetchall()]


def _log_ingest(cur, conn, status: str, n: int, erro: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES ('parcerias', %s, %s, %s, NOW())",
            (status, n, (erro[:500] if erro else None)))
        conn.commit()
    except Exception as e:
        log.warning("ingestion_log falhou: %s", str(e)[:120])


def ingest(dry: bool = False) -> int:
    from datetime import datetime

    from ingestion._resilience import get_sync_db_url, neon_connect

    t0 = time.time()
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            if not dry and os.getenv("PARCERIAS_FORCE") != "1":
                cur.execute("SELECT max(finished_at) FROM ingestion_log "
                            "WHERE source = 'parcerias' AND status IN ('success','ok')")
                ultimo = (cur.fetchone() or [None])[0]
                if ultimo:
                    horas = (datetime.now(ultimo.tzinfo) - ultimo).total_seconds() / 3600
                    if horas < MIN_INTERVAL_H:
                        log.info("ultima coleta ha %.1fh (< %dh) — pulando. "
                                 "PARCERIAS_FORCE=1 forca.", horas, MIN_INTERVAL_H)
                        return 0

            municipios = _municipios(cur)
            if not municipios:
                msg = "nenhum municipio ativo com IBGE na carteira"
                log.warning(msg)
                if not dry:
                    _log_ingest(cur, conn, "success", 0, msg)
                return 0

            gravados = com_proposta = com_emenda = falhas = 0
            atendidos = 0
            completo = True
            log.info("Parcerias: %d municipio(s) na carteira (orcamento %.0fs)",
                     len(municipios), BUDGET_S)
            with httpx.Client(follow_redirects=True) as client:
                for m in municipios:
                    if (time.time() - t0) >= BUDGET_S:
                        completo = False
                        log.warning("orcamento estourado apos %d municipio(s); "
                                    "o resto entra na proxima rodada", atendidos)
                        break
                    propostas = buscar(client, "proposta",
                                       {"cd_ibge_recebedor": m["ibge"]})
                    atendidos += 1
                    if propostas is None:
                        falhas += 1
                        continue
                    if not propostas:
                        continue
                    com_proposta += 1
                    for prop in propostas:
                        pid = prop.get("id_proposta")
                        # As duas unicas consultas extras por proposta. A
                        # execucao financeira (empenho/DH/OP/extrato) fica de
                        # fora por custo — ver o cabecalho do modulo.
                        time.sleep(PAUSA_S)
                        parcerias = buscar(client, "parceria", {"id_proposta": pid})
                        time.sleep(PAUSA_S)
                        emendas = buscar(client, "distribuicao-recurso-proposta",
                                         {"id_proposta": pid})
                        l = linha(m["id"], prop,
                                  (parcerias or [None])[0] if parcerias else None,
                                  (emendas or [None])[0] if emendas else None)
                        if l is None:
                            continue
                        if l["nr_emenda"]:
                            com_emenda += 1
                        if dry:
                            continue
                        cur.execute(_SQL, l)
                        gravados += 1
                    conn.commit()   # municipio a municipio: progresso persiste
                    log.info("  %s: %d proposta(s)", m["nome"], len(propostas))

            if dry:
                log.info("DRY: %d municipio(s), %d com proposta", atendidos, com_proposta)
                return 0
            log.info("=== Parcerias: %d proposta(s) gravada(s), %d com emenda, "
                     "%d municipio(s) com proposta, %d falha(s) em %.0fs ===",
                     gravados, com_emenda, com_proposta, falhas, time.time() - t0)

            # ⚠️ O ALARME CERTO NAO E "zero gravados". Municipio sem parceria e
            # estado legitimo e comum — a fonte so tem instrumento de 2024 em
            # diante. O que denuncia defeito e a fonte nao responder a ninguem.
            if falhas and not gravados:
                _log_ingest(cur, conn, "error", 0,
                            "a fonte nao respondeu a nenhum municipio")
            elif falhas or not completo:
                _log_ingest(cur, conn, "partial", gravados,
                            f"{falhas} municipio(s) sem resposta" if falhas
                            else "orcamento estourado; retoma na proxima rodada")
            else:
                _log_ingest(cur, conn, "success", gravados)
            return gravados
        except Exception as e:
            conn.rollback()
            log.error("Parcerias falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    # Sem isto o log da rodada vira lixo: sao ~1.100 requisicoes no maior tenant
    # e o httpx loga cada uma em INFO. Mesmo tratamento de `obrasgov` e `sismob`.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ingest(dry="--dry" in sys.argv)
