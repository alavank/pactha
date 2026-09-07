"""FUNDO A FUNDO do Transferegov.br -> tabela `faf_planos_acao`.

⭐ O OUTRO LADO DO ConsultaFNS. O `fns_faf.py` coleta o repasse consolidado por
bloco: **o dinheiro que entra**. Esta fonte traz o que o FNS nao publica — o
PLANO DE ACAO que justifica o repasse: diagnostico, objetivos, vigencia, e a
decomposicao do valor entre emenda, repasse especifico, voluntario, recursos
proprios e rendimentos. Uma nao substitui a outra.

E nao e so saude: em Nova Palma o primeiro plano e do **Ministerio da Cultura**
(Lei Aldir Blanc), com o Fundo Nacional da Cultura como repassador. O modulo
cobre todo fundo a fundo, nao apenas o do SUS.

⚠️ O FILTRO OBVIO ESTA QUEBRADO NA FONTE.
`/planos-acao?codigo_ibge_municipio_ente_recebedor_plano_acao=4313102` devolve
**HTTP 500** — o parametro esta no Swagger e nao funciona (medido em 06 E
07/09/2026, duas vezes, dias diferentes). O caminho que funciona tem dois passos:

    1. /programas-beneficiarios?codigo_ibge_..._beneficiario_programa=4313102
         -> 5 beneficiarios, cada um com `cnpj_beneficiario_programa`
    2. /planos-acao?cnpj_ente_recebedor_plano_acao=<cnpj>
         -> 4 planos, com os valores batendo com os beneficiarios

⚠️ E O CNPJ NAO PODE SER ADIVINHADO. Aqui o ente recebedor e a PREFEITURA
(88488358000156 em Nova Palma); no modulo de Parcerias as propostas do mesmo
municipio sao todas do FUNDO MUNICIPAL DA SAUDE (12240183000100). Assumir
qualquer um dos dois erraria em um dos modulos — e erraria calado, devolvendo
lista vazia como se o municipio nao tivesse nada. Por isso o passo 1 existe: a
fonte diz quem recebe.

Custo medido: 2 requisicoes por municipio, mais 1 por plano para os relatorios
de gestao. No freitas (42 municipios ativos) sao ~84 requisicoes de base.

Rodar:  python -u ingestion/faf_planos.py
        python -u ingestion/faf_planos.py --dry
"""
from __future__ import annotations
import json
import logging
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("faf_planos")

# ⚠️ `api-publica`, e nao `api` — a mesma pegadinha dos outros modulos.
BASE = os.getenv("FAF_BASE",
                 "https://api-publica.transferegov.gestao.gov.br/fundoafundo")
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0 dados abertos Transferegov)",
      "Accept": "application/json"}
TIMEOUT = 60
TAMANHO_PAGINA = 200
PAUSA_S = float(os.getenv("FAF_PAUSA_S", "0.2") or "0.2")
TETO_PAGINAS = int(os.getenv("FAF_TETO_PAGINAS", "200") or "200")
BUDGET_S = float(os.getenv("FAF_BUDGET_S", "900") or "900")
MIN_INTERVAL_H = int(os.getenv("FAF_MIN_INTERVAL_H", "20") or "20")


def _pagina(client: httpx.Client, caminho: str, params: dict, n: int) -> dict | None:
    p = {**params, "pagina": n, "tamanho_da_pagina": TAMANHO_PAGINA}
    try:
        r = client.get(f"{BASE}/{caminho}", params=p, headers=UA, timeout=TIMEOUT)
    except Exception as e:
        log.warning("  %s %s: %s", caminho, params, str(e)[:90])
        return None
    if r.status_code != 200:
        # ⚠️ O 500 do `codigo_ibge_..._recebedor` mora aqui. O log traz o caminho
        # E os parametros para que um filtro novo que a fonte quebre apareca
        # nomeado, em vez de virar "coletou zero" sem explicacao.
        log.warning("  %s %s: HTTP %s", caminho, params, r.status_code)
        return None
    try:
        return r.json()
    except ValueError:
        return None


def buscar(client: httpx.Client, caminho: str, params: dict) -> list[dict] | None:
    """Todas as paginas. `None` quando a PRIMEIRA falhou; `[]` e ausencia real."""
    d = _pagina(client, caminho, params, 1)
    if d is None:
        return None
    itens = list(d.get("data") or [])
    total = min(int(d.get("total_pages") or 1), TETO_PAGINAS)
    for n in range(2, total + 1):
        time.sleep(PAUSA_S)
        d = _pagina(client, caminho, params, n)
        if d is None:
            break
        itens.extend(d.get("data") or [])
    return itens


def cnpjs_do_municipio(client: httpx.Client, ibge: str) -> list[str]:
    """CNPJs que recebem fundo a fundo neste municipio, ditos PELA FONTE.

    ⚠️ E o passo que substitui o filtro quebrado. Ver o cabecalho do modulo: o
    `codigo_ibge_..._recebedor` de `/planos-acao` devolve 500, e adivinhar entre
    a prefeitura e o fundo municipal erraria em um dos dois modulos da familia.
    """
    itens = buscar(client, "programas-beneficiarios",
                   {"codigo_ibge_municipio_ente_beneficiario_programa": ibge})
    if not itens:
        return []
    vistos, fora = set(), []
    for b in itens:
        c = "".join(ch for ch in str(b.get("cnpj_beneficiario_programa") or "")
                    if ch.isdigit())
        if len(c) == 14 and c not in vistos:
            vistos.add(c)
            fora.append(c)
    return fora


def _num(v):
    return v if isinstance(v, (int, float)) else None


def _data(v):
    s = str(v or "").strip()
    return s[:10] if s else None


def linha(municipio_id: int, plano: dict, relatorios: list[dict] | None) -> dict | None:
    """Traduz UM plano de acao para as colunas. Funcao PURA e testavel."""
    pid = plano.get("id_plano_acao")
    if pid in (None, ""):
        return None
    return {
        "mid": municipio_id,
        "id_plano": str(pid),
        "codigo": plano.get("codigo_plano_acao"),
        "id_programa": (str(plano["id_programa"])
                        if plano.get("id_programa") is not None else None),
        "situacao": plano.get("situacao_plano_acao"),
        "dt_ini": _data(plano.get("data_inicio_vigencia_plano_acao")),
        "dt_fim": _data(plano.get("data_fim_vigencia_plano_acao")),
        "diagnostico": plano.get("diagnostico_plano_acao"),
        "objetivos": plano.get("objetivos_plano_acao"),
        "vl_total": _num(plano.get("valor_total_plano_acao")),
        "vl_emenda": _num(plano.get("valor_repasse_emenda_plano_acao")),
        "vl_especifico": _num(plano.get("valor_repasse_especifico_plano_acao")),
        "vl_voluntario": _num(plano.get("valor_repasse_voluntario_plano_acao")),
        "vl_proprios": _num(plano.get("valor_recursos_proprios_plano_acao")),
        "vl_rendimentos": _num(plano.get("valor_rendimentos_aplicacao_plano_acao")),
        "vl_custeio": _num(plano.get("valor_total_custeio_plano_acao")),
        "vl_investimento": _num(plano.get("valor_total_investimento_plano_acao")),
        "vl_saldo": _num(plano.get("valor_saldo_disponivel_plano_acao")),
        "orgao": plano.get("nome_orgao_repassador_plano_acao"),
        "sigla_orgao": plano.get("sigla_orgao_repassador_plano_acao"),
        "fundo": plano.get("nome_fundo_repassador_plano_acao"),
        "cnpj_ente": (plano.get("cnpj_ente_recebedor_plano_acao") or "")[:14] or None,
        "nome_ente": plano.get("nome_ente_recebedor_plano_acao"),
        "tipo_unidade": plano.get("tipo_unidade_recebedora_plano_acao"),
        # ⚠️ NULO quando nao ha relatorio, e nunca `[]`: lista vazia no banco
        # seria indistinguivel de "coletei e nao ha", e a diferenca entre "nao
        # medido" e "nao existe" e a mesma disciplina do resto do repo.
        "relatorios": (json.dumps(relatorios, ensure_ascii=False)
                       if relatorios else None),
        "raw": json.dumps(plano, ensure_ascii=False),
    }


_SQL = """
INSERT INTO faf_planos_acao (
    municipio_id, id_plano_acao, codigo_plano_acao, id_programa, situacao,
    data_inicio_vigencia, data_fim_vigencia, diagnostico, objetivos,
    valor_total, valor_repasse_emenda, valor_repasse_especifico,
    valor_repasse_voluntario, valor_recursos_proprios, valor_rendimentos,
    valor_custeio, valor_investimento, valor_saldo_disponivel,
    orgao_repassador, sigla_orgao_repassador, fundo_repassador,
    cnpj_ente_recebedor, nome_ente_recebedor, tipo_unidade_recebedora,
    relatorios_gestao, raw_data, atualizado_em)
VALUES (%(mid)s, %(id_plano)s, %(codigo)s, %(id_programa)s, %(situacao)s,
        %(dt_ini)s, %(dt_fim)s, %(diagnostico)s, %(objetivos)s, %(vl_total)s,
        %(vl_emenda)s, %(vl_especifico)s, %(vl_voluntario)s, %(vl_proprios)s,
        %(vl_rendimentos)s, %(vl_custeio)s, %(vl_investimento)s, %(vl_saldo)s,
        %(orgao)s, %(sigla_orgao)s, %(fundo)s, %(cnpj_ente)s, %(nome_ente)s,
        %(tipo_unidade)s, %(relatorios)s::jsonb, %(raw)s::jsonb, NOW())
ON CONFLICT (municipio_id, id_plano_acao) DO UPDATE SET
    codigo_plano_acao = EXCLUDED.codigo_plano_acao,
    id_programa = EXCLUDED.id_programa, situacao = EXCLUDED.situacao,
    data_inicio_vigencia = EXCLUDED.data_inicio_vigencia,
    data_fim_vigencia = EXCLUDED.data_fim_vigencia,
    diagnostico = EXCLUDED.diagnostico, objetivos = EXCLUDED.objetivos,
    valor_total = EXCLUDED.valor_total,
    valor_repasse_emenda = EXCLUDED.valor_repasse_emenda,
    valor_repasse_especifico = EXCLUDED.valor_repasse_especifico,
    valor_repasse_voluntario = EXCLUDED.valor_repasse_voluntario,
    valor_recursos_proprios = EXCLUDED.valor_recursos_proprios,
    valor_rendimentos = EXCLUDED.valor_rendimentos,
    valor_custeio = EXCLUDED.valor_custeio,
    valor_investimento = EXCLUDED.valor_investimento,
    valor_saldo_disponivel = EXCLUDED.valor_saldo_disponivel,
    orgao_repassador = EXCLUDED.orgao_repassador,
    sigla_orgao_repassador = EXCLUDED.sigla_orgao_repassador,
    fundo_repassador = EXCLUDED.fundo_repassador,
    cnpj_ente_recebedor = EXCLUDED.cnpj_ente_recebedor,
    nome_ente_recebedor = EXCLUDED.nome_ente_recebedor,
    tipo_unidade_recebedora = EXCLUDED.tipo_unidade_recebedora,
    -- ⚠️ COALESCE no relatorio: a rodada que nao conseguiu buscar os relatorios
    -- (orcamento estourado, fonte lenta) NAO pode apagar os que ja estavam la.
    relatorios_gestao = coalesce(EXCLUDED.relatorios_gestao,
                                 faf_planos_acao.relatorios_gestao),
    raw_data = EXCLUDED.raw_data, atualizado_em = NOW()
"""


def _municipios(cur) -> list[dict]:
    """Municipios ATIVOS com IBGE — `WHERE active` pelo motivo que a
    Transferencia Especial aprendeu em producao (07/09/2026)."""
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
            "error_message, finished_at) VALUES ('faf_planos', %s, %s, %s, NOW())",
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
            if not dry and os.getenv("FAF_FORCE") != "1":
                cur.execute("SELECT max(finished_at) FROM ingestion_log "
                            "WHERE source = 'faf_planos' AND status IN ('success','ok')")
                ultimo = (cur.fetchone() or [None])[0]
                if ultimo:
                    horas = (datetime.now(ultimo.tzinfo) - ultimo).total_seconds() / 3600
                    if horas < MIN_INTERVAL_H:
                        log.info("ultima coleta ha %.1fh (< %dh) — pulando. "
                                 "FAF_FORCE=1 forca.", horas, MIN_INTERVAL_H)
                        return 0

            municipios = _municipios(cur)
            if not municipios:
                msg = "nenhum municipio ativo com IBGE na carteira"
                log.warning(msg)
                if not dry:
                    _log_ingest(cur, conn, "success", 0, msg)
                return 0

            gravados = com_plano = com_emenda = falhas = atendidos = 0
            completo = True
            log.info("FaF: %d municipio(s) na carteira (orcamento %.0fs)",
                     len(municipios), BUDGET_S)
            with httpx.Client(follow_redirects=True) as client:
                for m in municipios:
                    if (time.time() - t0) >= BUDGET_S:
                        completo = False
                        log.warning("orcamento estourado apos %d municipio(s)", atendidos)
                        break
                    atendidos += 1
                    cnpjs = cnpjs_do_municipio(client, m["ibge"])
                    if not cnpjs:
                        continue
                    planos: list[dict] = []
                    for cnpj in cnpjs:
                        time.sleep(PAUSA_S)
                        achados = buscar(client, "planos-acao",
                                         {"cnpj_ente_recebedor_plano_acao": cnpj})
                        if achados is None:
                            falhas += 1
                            continue
                        planos.extend(achados)
                    if not planos:
                        continue
                    com_plano += 1
                    for plano in planos:
                        time.sleep(PAUSA_S)
                        rel = buscar(client, "relatorios-gestao",
                                     {"id_plano_acao": plano.get("id_plano_acao")})
                        l = linha(m["id"], plano, rel)
                        if l is None:
                            continue
                        if (l["vl_emenda"] or 0) > 0:
                            com_emenda += 1
                        if dry:
                            continue
                        cur.execute(_SQL, l)
                        gravados += 1
                    conn.commit()
                    log.info("  %s: %d plano(s) de acao (%d CNPJ)",
                             m["nome"], len(planos), len(cnpjs))

            if dry:
                log.info("DRY: %d municipio(s), %d com plano", atendidos, com_plano)
                return 0
            log.info("=== FaF: %d plano(s) gravado(s), %d com repasse de emenda, "
                     "%d municipio(s) com plano, %d falha(s) em %.0fs ===",
                     gravados, com_emenda, com_plano, falhas, time.time() - t0)

            # Municipio sem plano fundo a fundo e estado legitimo. O que denuncia
            # defeito e a fonte nao responder a ninguem — ou o filtro por CNPJ
            # comecar a devolver 500 como o de IBGE ja devolve.
            if falhas and not gravados:
                _log_ingest(cur, conn, "error", 0,
                            "a fonte nao respondeu a nenhum municipio")
            elif falhas or not completo:
                _log_ingest(cur, conn, "partial", gravados,
                            f"{falhas} consulta(s) sem resposta" if falhas
                            else "orcamento estourado; retoma na proxima rodada")
            else:
                _log_ingest(cur, conn, "success", gravados)
            return gravados
        except Exception as e:
            conn.rollback()
            log.error("FaF falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ingest(dry="--dry" in sys.argv)
