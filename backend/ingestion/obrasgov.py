"""
Obras.gov.br / CIPI — obras federais no municipio, sem login e sem token.

O Cadastro Integrado de Projetos de Investimento reune as obras federais com
execucao fisica, fontes de recurso, tomador e executor. Complementa o SISMOB (so
saude) e o SIMEC (so educacao): aqui entra o resto — mobilidade, saneamento,
habitacao, seguranca.

⚠️⚠️ **ESTA API NAO TEM FILTRO POR MUNICIPIO.** Lido no OpenAPI em 02/09/2026
(`/obrasgov/api/api-obrasgov-docs`, que fica atras de um `configUrl` proprio e
nao no `/v3/api-docs` de sempre), os unicos parametros de
`/projeto-investimento` sao:

    idUnico · situacao · codigoOrganizacao · nomeOrganizacao · uf ·
    dataCadastro · natureza · pagina · tamanhoDaPagina

Nao ha `codigoIbge`. E o mais perigoso: **passar um parametro desconhecido nao
da erro** — o Spring ignora em silencio. Uma consulta com `codigoIbge=4313102`
devolve HTTP 200 com uma obra do **Amapa**. Medido. Por isso o recorte de
municipio e feito AQUI, pelo CNPJ do tomador/executor, e nunca delegado a fonte.

AS ARMADILHAS, todas medidas em 02/09/2026:

1. ⚠️ **A PAGINACAO MENTE, E MENTE PARA O LADO PERIGOSO.** `last` volta `true`
   em TODA pagina, e `totalPages`/`totalElements` sao calculados a partir da
   pagina pedida (com `tamanhoDaPagina=200`, a pagina 0 informa
   `totalElements: 200, totalPages: 1`; a pagina 1 informa `400` e `2`). Um
   coletor que confiasse em `last` pararia na primeira pagina e afirmaria ter
   todas as obras do estado. A parada e por CONTEUDO: pagina vazia, ou duas
   paginas seguidas sem `idUnico` novo.

2. ⚠️ **AS PAGINAS SE SOBREPOEM.** Medido: 41 dos 200 itens da pagina 1 ja
   estavam na pagina 0 — a ordenacao nao e estavel. Sem dedup por `idUnico`, a
   contagem infla e o upsert reescreve a mesma linha varias vezes.

3. ⚠️⚠️ **429 VEM COM CORPO VAZIO**, e `size_download=0` e indistinguivel de
   "nenhuma obra" para quem so olha o tamanho da resposta. O rate limit e
   apertado: em medicao, requisicoes espacadas de 3s levaram 429 e so passaram
   com 20-45s de espera. Aqui o 429 tem backoff proprio e NUNCA e tratado como
   resultado.

4. ⚠️ **O PROJETO NAO DIZ ONDE FICA, na maioria das vezes.** De 397 projetos do
   RS medidos, so 96 tinham `cep` ou `endereco`; 240 tinham CNPJ de 14 digitos
   em `tomadores`/`executores`. O CNPJ e o caminho — e por isso este coletor
   depende de `municipios.cnpj` estar preenchido (o `ingestion/siconfi.py`
   preenche sozinho, a partir do cadastro de entes do Tesouro).

5. ⚠️ `codigoOrganizacao` E `nomeOrganizacao` NAO SERVEM PARA ISSO.
   `nomeOrganizacao=NOVA PALMA` devolveu obras do Amapa e de Santa Catarina (e
   ignorado, como o `codigoIbge`); `codigoOrganizacao` com CNPJ de tomador
   conhecido devolveu ZERO. Ele filtra por outra coisa — nao pelo tomador.

Rodavel por Scheduled Task em qualquer worker, ou a mao:
    python -u ingestion/obrasgov.py            # coleta de verdade
    python -u ingestion/obrasgov.py --dry      # varre e mostra, sem gravar
"""
import json
import logging
import os
import re
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("obrasgov")

BASE = "https://api.obrasgov.gestao.gov.br/obrasgov/api"
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0 dados abertos Obras.gov.br)",
      "Accept": "application/json"}
FONTE = "OBRASGOV"
TIMEOUT = 90

TAMANHO_PAGINA = int(os.getenv("OBRASGOV_TAMANHO_PAGINA", "200") or "200")
# Armadilha 3: o rate limit e apertado. 8s e o meio-termo entre a medicao (3s
# levou 429; 20s passou) e o orcamento de uma rodada noturna.
PAUSA_S = float(os.getenv("OBRASGOV_PAUSA_S", "8") or "8")
TETO_PAGINAS = int(os.getenv("OBRASGOV_TETO_PAGINAS", "60") or "60")
# Armadilha 1: duas paginas seguidas sem nada novo = fim.
SECAS_PARA_PARAR = 2
MIN_INTERVAL_H = int(os.getenv("OBRASGOV_MIN_INTERVAL_H", "44") or "44")


def _so_digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def pagina(client: httpx.Client, uf: str, n: int) -> dict | None:
    """Uma pagina, com backoff no 429 (armadilha 3).

    Devolve None quando desiste — e `None` NAO significa "acabou": quem chama
    tem de distinguir, senao uma rodada punida por rate limit vira "o estado nao
    tem obras"."""
    params = {"uf": uf, "pagina": n, "tamanhoDaPagina": TAMANHO_PAGINA}
    for espera in (0, 30, 60, 120):
        if espera:
            log.info("    429 — aguardando %ds", espera)
            time.sleep(espera)
        r = client.get(f"{BASE}/projeto-investimento", params=params,
                       headers=UA, timeout=TIMEOUT)
        if r.status_code == 429:
            continue
        r.raise_for_status()
        return r.json()
    return None


def varrer_uf(client: httpx.Client, uf: str) -> tuple[dict, bool]:
    """Todos os projetos da UF, deduplicados por `idUnico`.

    Devolve (projetos, completo). `completo=False` quando a varredura parou por
    rate limit ou pelo teto — e nesse caso a rodada NAO pode marcar obra como
    ausente, porque a ausencia pode ser nossa."""
    por_id: dict[str, dict] = {}
    secas = 0
    for n in range(TETO_PAGINAS):
        d = pagina(client, uf, n)
        if d is None:
            log.warning("  %s: varredura interrompida por rate limit na pagina %d "
                        "(%d projeto(s) ate aqui) — resultado PARCIAL", uf, n, len(por_id))
            return por_id, False
        conteudo = d.get("content") or []
        if not conteudo:
            return por_id, True
        novos = 0
        for x in conteudo:
            uid = x.get("idUnico")
            if uid and uid not in por_id:
                por_id[uid] = x
                novos += 1
        log.info("  %s pagina %d: %d itens, %d novos (acumulado %d)",
                 uf, n, len(conteudo), novos, len(por_id))
        # Armadilha 1: `last`/`totalPages` sao ignorados de proposito.
        secas = secas + 1 if novos == 0 else 0
        if secas >= SECAS_PARA_PARAR:
            return por_id, True
        time.sleep(PAUSA_S)
    log.warning("  %s: teto de %d paginas — resultado PARCIAL", uf, TETO_PAGINAS)
    return por_id, False


def cnpjs_do_projeto(p: dict) -> set[str]:
    """CNPJs de 14 digitos em tomadores e executores (armadilha 4).

    Ente municipal aparece com CNPJ; orgao federal aparece com codigo SIAFI/UG
    curto (36210, 26419), que nao casa com CNPJ nenhum e por isso e descartado
    naturalmente pelo teste de comprimento."""
    out = set()
    for lista in ("tomadores", "executores"):
        for x in (p.get(lista) or []):
            c = _so_digitos(x.get("codigo"))
            if len(c) == 14:
                out.add(c)
    return out


def _alvos(cur) -> dict[str, list[dict]]:
    """{uf: [municipios]} com os CNPJs conhecidos de cada um.

    Mesma descoberta do `che_rs.py`: a prefeitura vem de `municipios.cnpj` e as
    demais entidades (tipicamente o Fundo Municipal de Saude) saem das fontes
    federais ja coletadas."""
    cur.execute("""
        SELECT id, nome, upper(coalesce(uf,'')),
               regexp_replace(coalesce(cnpj,''), '\\D', '', 'g')
          FROM municipios
         WHERE active AND coalesce(uf,'') <> ''
         ORDER BY nome
    """)
    municipios = [{"id": r[0], "nome": r[1], "uf": r[2], "cnpjs": set()}
                  for r in cur.fetchall()]
    cur.execute("""
        SELECT id, regexp_replace(coalesce(cnpj,''), '\\D', '', 'g')
          FROM municipios WHERE active
    """)
    proprio = {r[0]: r[1] for r in cur.fetchall()}
    ids = [m["id"] for m in municipios]
    if ids:
        cur.execute("""
            SELECT DISTINCT municipio_id, cnpj FROM (
                SELECT s.municipio_id,
                       regexp_replace(coalesce(s.nu_cnpj,''), '\\D', '', 'g') AS cnpj
                  FROM sismob_obras s WHERE s.municipio_id = ANY(%s)
                UNION
                SELECT p.municipio_id,
                       regexp_replace(coalesce(p.cnpj,''), '\\D', '', 'g')
                  FROM transferegov_pac p WHERE p.municipio_id = ANY(%s)
            ) t WHERE length(cnpj) = 14
        """, (ids, ids))
        extras: dict[int, set[str]] = {}
        for mid, cnpj in cur.fetchall():
            extras.setdefault(mid, set()).add(cnpj)
    else:
        extras = {}

    por_uf: dict[str, list[dict]] = {}
    for m in municipios:
        if len(proprio.get(m["id"]) or "") == 14:
            m["cnpjs"].add(proprio[m["id"]])
        m["cnpjs"] |= extras.get(m["id"], set())
        if m["cnpjs"]:
            por_uf.setdefault(m["uf"], []).append(m)
        else:
            log.info("  %s/%s: sem CNPJ conhecido — nao da para reconhecer as "
                     "obras dele (rode ingestion/siconfi.py, que preenche)",
                     m["nome"], m["uf"])
    return por_uf


_SQL = """
INSERT INTO obrasgov_projetos (
    municipio_id, id_unico, nome, descricao, funcao_social, meta_global,
    natureza, especie, situacao, uf, cep, endereco,
    data_inicial_prevista, data_final_prevista, data_inicial_efetiva,
    data_final_efetiva, data_situacao, data_cadastro,
    populacao_beneficiada, empregos_gerados, valor_investimento_previsto,
    origens_recurso, eixos, tipos, tomadores, executores, repassadores,
    raw_data, atualizado_em)
VALUES (%(mid)s, %(uid)s, %(nome)s, %(desc)s, %(social)s, %(meta)s,
        %(natureza)s, %(especie)s, %(situacao)s, %(uf)s, %(cep)s, %(end)s,
        %(dt_ini_prev)s, %(dt_fim_prev)s, %(dt_ini_efe)s, %(dt_fim_efe)s,
        %(dt_sit)s, %(dt_cad)s, %(pop)s, %(empregos)s, %(valor)s,
        %(origens)s, %(eixos)s, %(tipos)s, %(tomadores)s, %(executores)s,
        %(repassadores)s, %(raw)s::jsonb, NOW())
ON CONFLICT (id_unico) DO UPDATE SET
    municipio_id = EXCLUDED.municipio_id, nome = EXCLUDED.nome,
    descricao = EXCLUDED.descricao, funcao_social = EXCLUDED.funcao_social,
    meta_global = EXCLUDED.meta_global, natureza = EXCLUDED.natureza,
    especie = EXCLUDED.especie, situacao = EXCLUDED.situacao, uf = EXCLUDED.uf,
    cep = EXCLUDED.cep, endereco = EXCLUDED.endereco,
    data_inicial_prevista = EXCLUDED.data_inicial_prevista,
    data_final_prevista = EXCLUDED.data_final_prevista,
    data_inicial_efetiva = EXCLUDED.data_inicial_efetiva,
    data_final_efetiva = EXCLUDED.data_final_efetiva,
    data_situacao = EXCLUDED.data_situacao, data_cadastro = EXCLUDED.data_cadastro,
    populacao_beneficiada = EXCLUDED.populacao_beneficiada,
    empregos_gerados = EXCLUDED.empregos_gerados,
    valor_investimento_previsto = EXCLUDED.valor_investimento_previsto,
    origens_recurso = EXCLUDED.origens_recurso, eixos = EXCLUDED.eixos,
    tipos = EXCLUDED.tipos, tomadores = EXCLUDED.tomadores,
    executores = EXCLUDED.executores, repassadores = EXCLUDED.repassadores,
    raw_data = EXCLUDED.raw_data, atualizado_em = NOW()
"""


def _nomes(lista) -> list[str]:
    return [str(x.get("nome") or x.get("descricao") or "").strip()
            for x in (lista or []) if x]


def linha(municipio_id: int, p: dict) -> dict:
    fontes = p.get("fontesDeRecurso") or []
    # Soma das fontes: a API traz uma linha por origem (Federal, Estadual...).
    valor = None
    for f in fontes:
        v = f.get("valorInvestimentoPrevisto")
        if isinstance(v, (int, float)):
            valor = (valor or 0) + v
    return {
        "mid": municipio_id,
        "uid": p.get("idUnico"),
        "nome": (p.get("nome") or "").strip() or None,
        "desc": (p.get("descricao") or "").strip() or None,
        "social": (p.get("funcaoSocial") or "").strip() or None,
        "meta": (p.get("metaGlobal") or "").strip() or None,
        "natureza": p.get("natureza"),
        "especie": p.get("especie"),
        "situacao": p.get("situacao"),
        "uf": p.get("uf"),
        "cep": p.get("cep"),
        "end": p.get("endereco"),
        "dt_ini_prev": p.get("dataInicialPrevista") or None,
        "dt_fim_prev": p.get("dataFinalPrevista") or None,
        "dt_ini_efe": p.get("dataInicialEfetiva") or None,
        "dt_fim_efe": p.get("dataFinalEfetiva") or None,
        "dt_sit": p.get("dataSituacao") or None,
        "dt_cad": p.get("dataCadastro") or None,
        "pop": p.get("populacaoBeneficiada"),
        "empregos": p.get("qdtEmpregosGerados"),
        "valor": valor,
        "origens": [str(f.get("origem") or "") for f in fontes],
        "eixos": _nomes(p.get("eixos")),
        "tipos": _nomes(p.get("tipos")),
        "tomadores": _nomes(p.get("tomadores")),
        "executores": _nomes(p.get("executores")),
        "repassadores": _nomes(p.get("repassadores")),
        "raw": json.dumps(p, ensure_ascii=False),
    }


def _log_ingest(cur, conn, status: str, n: int, erro: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES ('obrasgov', %s, %s, %s, NOW())",
            (status, n, erro))
        conn.commit()
    except Exception as e:
        log.warning("ingestion_log falhou: %s", str(e)[:120])


def ingest(dry: bool = False) -> int:
    from datetime import datetime

    from ingestion._resilience import get_sync_db_url, neon_connect

    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            if not dry and os.getenv("OBRASGOV_FORCE") != "1":
                cur.execute("SELECT max(finished_at) FROM ingestion_log "
                            "WHERE source = 'obrasgov' AND status IN ('success','ok')")
                ultimo = (cur.fetchone() or [None])[0]
                if ultimo:
                    horas = (datetime.now(ultimo.tzinfo) - ultimo).total_seconds() / 3600
                    if horas < MIN_INTERVAL_H:
                        log.info("ultima coleta ha %.1fh (< %dh) — pulando. "
                                 "OBRASGOV_FORCE=1 forca.", horas, MIN_INTERVAL_H)
                        return 0

            por_uf = _alvos(cur)
            if not por_uf:
                log.info("nenhum municipio com CNPJ conhecido — nada a reconhecer")
                if not dry:
                    _log_ingest(cur, conn, "success", 0)
                return 0

            gravados = 0
            parciais = []
            with httpx.Client(follow_redirects=True) as client:
                for uf, municipios in sorted(por_uf.items()):
                    log.info("UF %s: %d municipio(s) na carteira", uf, len(municipios))
                    projetos, completo = varrer_uf(client, uf)
                    if not completo:
                        parciais.append(uf)
                    # Indice CNPJ -> municipio, montado uma vez.
                    de_quem: dict[str, dict] = {}
                    for m in municipios:
                        for c in m["cnpjs"]:
                            de_quem[c] = m
                    achados = 0
                    for p in projetos.values():
                        donos = {de_quem[c]["id"] for c in cnpjs_do_projeto(p)
                                 if c in de_quem}
                        for mid in donos:
                            achados += 1
                            if dry:
                                continue
                            cur.execute(_SQL, linha(mid, p))
                            gravados += 1
                    log.info("  %s: %d projeto(s) varrido(s), %d da carteira",
                             uf, len(projetos), achados)
                    if dry:
                        for p in list(projetos.values())[:3]:
                            log.info("      %s  %s", p.get("idUnico"),
                                     (p.get("nome") or "")[:60])

            if dry:
                return 0
            conn.commit()
            log.info("=== Obras.gov.br: %d linha(s) gravada(s)%s ===", gravados,
                     f", PARCIAL em {', '.join(parciais)}" if parciais else "")
            if parciais:
                # ⚠️ Varredura interrompida por rate limit NAO e sucesso: a
                # ausencia de uma obra pode ser nossa, nao da fonte.
                _log_ingest(cur, conn, "partial", gravados,
                            "varredura interrompida por rate limit (429) em: "
                            + ", ".join(parciais))
            else:
                _log_ingest(cur, conn, "success", gravados)
            return gravados
        except Exception as e:
            conn.rollback()
            log.error("Obras.gov.br falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ingest(dry="--dry" in sys.argv)
