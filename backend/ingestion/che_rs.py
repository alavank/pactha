"""
CHE — Cadastro de Habilitação em Convênios do Estado (RIO GRANDE DO SUL).

O equivalente gaúcho do CAGEC mineiro: sem CHE válido o ente não celebra
convênio com a Administração Pública Estadual do RS. Gerido pela CAGE/SEFAZ-RS,
base legal IN CAGE nº 01/2006. Grava em `cagec_situacao` com `fonte='CHE-RS'`
— a tabela é do CADASTRO ESTADUAL, não do CAGEC (ver add_cadastro_estadual_rs.sql).

⭐ E MUITO MAIS BARATO QUE O CAGEC. O portal (che.sefaz.rs.gov.br, "SISCHE") e
uma SPA Angular servida por uma API REST JSON **publica**: duas requisicoes HTTP
por CNPJ, sem login, sem Playwright, sem parse de PDF. O CAGEC precisa de
Chromium + ZK Framework + leitura de PDF para chegar na mesma informacao.

    GET /api/Entidade/Consultar?entidadeCnpj=<14 digitos>
        -> {"listaEntidadeXDocumento": [...], "listaAvaliacao": [...]}
           cada documento com dataValidade, dataAtualizacao e o nome da exigencia
    GET /api/Entidade/ConsultarAutoComplete?termo=<texto>
        -> [{entidadeId, nome, cnpj}]  (busca por nome — ver armadilha 4)

AS ARMADILHAS, todas medidas contra o portal em 16/08/2026:

1. ⚠️ **O PORTAL NAO TEM 404.** CNPJ fora do cadastro devolve **HTTP 200 com o
   index.html do Angular** (`text/html`, 1249 bytes) — igualzinho ao que ele
   devolve quando o CNPJ vai COM MASCARA (a barra quebra a rota). Duas causas,
   um sintoma so. A separacao esta em `consultar()`: mascara e barrada na
   entrada (defeito nosso, falha alto) e o que sobra e "nao cadastrado" (fato do
   Estado, vira `None` e NAO conta como falha). Confundir os dois faz o coletor
   ou marcar toda rodada como `partial` para sempre, ou afirmar em silencio que
   um municipio habilitado nao tem cadastro estadual.

2. ⚠️ `GerarCertificado?habilitacaoId=0&cnpj=...` devolve o PDF do certificado
   **mesmo para quem nao tem habilitacao**. Isso e o INVERSO do CAGEC, onde o
   CRC e a fonte da verdade. Aqui o PDF e anexo, nunca evidencia: a regularidade
   sai da leitura das validades, e so.

3. ⚠️ `ConsultarHabilitacao`, `ConsultarCadastro` e `ListarEntidadesDocumentos`
   respondem **401** (a SPA os chama com cookie de sessao). Nao construa nada em
   cima deles — e 401 jamais vira "irregular".

4. ⚠️ `ConsultarAutoComplete` casa por NOME e **nao tem coluna de municipio**:
   "SANTA MARIA" traz tambem "SANTA MARIA DO HERVAL". A trava que o
   `cagec_scraper.descobrir_entidades` tem (comparar a coluna Municipio) nao
   existe aqui. Por isso este coletor **so entra por CNPJ conhecido**.

5. ⚠️ So responde em **https://che.sefaz.rs.gov.br** (sem `www`). O
   `http://www.che.sefaz.rs.gov.br` devolve 503.

6. ⚠️ A validade vai para `itens[].validade` em **dd/mm/aaaa**, e nao no ISO que
   a API devolve. `services/bi_abas.py::_FORMATOS_DATA` e o `venceu()` da tela
   `/dashboard/cauc` so entendem dd/mm/aaaa: gravar ISO faz `prazos_dos_itens`
   descartar 100% dos itens e o alerta de vencimento **nunca disparar**, sem
   erro em log nenhum.

Rodavel por Scheduled Task no worker de tenant com municipio do RS, ou a mao:
    python -u ingestion/che_rs.py            # coleta de verdade
    python -u ingestion/che_rs.py --dry      # consulta e mostra, sem gravar
"""
import json
import logging
import os
import re
import sys
from datetime import date, datetime

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("che_rs")

BASE = "https://che.sefaz.rs.gov.br/api/Entidade"
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0 consulta publica CHE/SEFAZ-RS)",
      "Accept": "application/json"}
FONTE = "CHE-RS"
UF = "RS"
TIMEOUT = 30

# ⭐ CODIGO ESTAVEL POR `documentoId`, NUNCA PELO ROTULO. O codigo e a chave de
# `painel_alertas_enviados.ref` e das faixas de 30/15/7 dias: se ele mudasse
# porque a SEFAZ reescreveu um texto, TODO alerta re-dispararia do zero. O
# documentoId e numerico e estavel; o rotulo, nao.
#
# FGTS, CNDT e CNPJ repetem de proposito os codigos usados no CAGEC-MG: e a
# MESMA obrigacao federal, e um cliente que um dia tenha municipio nos dois
# estados deve ver o mesmo codigo para a mesma certidao.
CODIGOS: dict[int, tuple[str, str]] = {
    # documentoId: (codigo, grupo)
    145: ("CNPJ", "Regularidade federal"),
    146: ("PREVIDENCIA", "Regularidade federal"),
    147: ("FGTS", "Regularidade federal"),
    154: ("CNDT", "Regularidade federal"),
    148: ("STN-CONTAS", "Contas e responsabilidade fiscal"),
    149: ("TCE-ASPS", "Contas e responsabilidade fiscal"),
    150: ("TCE-MDE", "Contas e responsabilidade fiscal"),
    151: ("TCE-LRF", "Contas e responsabilidade fiscal"),
    153: ("LRF-ART11", "Contas e responsabilidade fiscal"),
    152: ("ADESAO-PROG", "Adesão a programas estaduais"),
}
GRUPO_PADRAO = "Exigências do CHE"


def _so_digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _mascara_cnpj(cnpj: str) -> str:
    """00.000.000/0000-00 — a tabela guarda mascarado (como o CAGEC), porque a
    chave e (municipio_id, cnpj) e misturar formatos na mesma coluna obrigaria
    `regexp_replace` em todo join futuro."""
    d = _so_digitos(cnpj)
    if len(d) != 14:
        return cnpj
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def _data_br(iso: str | None) -> str | None:
    """'2027-01-16T00:00:00' -> '16/01/2027'. Ver armadilha 6 no cabecalho."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso)[:19]).strftime("%d/%m/%Y")
    except ValueError:
        return None


def _data_iso(iso: str | None) -> date | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso)[:19]).date()
    except ValueError:
        return None


def consultar(client: httpx.Client, cnpj14: str) -> dict | None:
    """A consulta publica. `None` = CNPJ que o CHE nao conhece.

    ⚠️ O PORTAL NAO TEM 404, E ISSO E A ARMADILHA CENTRAL DESTE MODULO. Para
    qualquer CNPJ fora do cadastro ele responde **HTTP 200 com o index.html do
    Angular** (1249 bytes, `text/html`). Medido em 16/08/2026 com o CNPJ do
    Fundo Municipal de Saude de Santa Maria, com `00000000000000` e com
    `99999999999999`: resposta identica nos tres.

    Duas causas produzem exatamente o mesmo sintoma, e por isso a defesa e em
    duas camadas:

      (a) CNPJ **com mascara** — a barra quebra a rota e cai no index.html.
          Prevenido na ENTRADA (o assert abaixo): quem chama tem de mandar 14
          digitos. Isso e defeito NOSSO e nao pode ser confundido com o item (b).
      (b) CNPJ que o Estado nao cadastrou — resposta legitima, e a unica que
          sobra depois de (a). Vira `None`, e o chamador registra "sem cadastro".

    Sem essa separacao o coletor faria uma de duas besteiras: tratar entidade
    sem cadastro como FALHA (marcando toda rodada como `partial` para sempre, e
    o watchdog cobrando uma fonte saudavel), ou tratar bug de formatacao como
    "nao cadastrado" e gravar silenciosamente que um municipio habilitado nao
    tem cadastro estadual."""
    if len(cnpj14) != 14 or not cnpj14.isdigit():
        # Defeito de chamada, nao da fonte: falha alto.
        raise ValueError(f"CNPJ deve ter 14 digitos sem mascara, recebi {cnpj14!r}")
    r = client.get(f"{BASE}/Consultar", params={"entidadeCnpj": cnpj14},
                   headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    if "json" not in (r.headers.get("content-type") or "").lower():
        return None
    return r.json()


def itens_do_payload(payload: dict, hoje: date) -> list[dict]:
    """Converte a resposta do CHE para o formato de `itens` do CAUC:
    [{codigo, grupo, label, valor, status, tipo, validade}].

    `tipo` in ('regular','pendente','na') e o que a tela pinta. A regra aqui e
    a unica honesta com o que a fonte entrega: **so validade no futuro e
    regular**. O CHE nao publica um rotulo "Regular/Irregular" por exigencia
    como o CRC mineiro — publica a data ate quando cada uma vale."""
    itens: list[dict] = []
    for reg in payload.get("listaEntidadeXDocumento") or []:
        doc = reg.get("documento") or {}
        doc_id = doc.get("documentoId")
        codigo, grupo = CODIGOS.get(doc_id, (f"CHE-{doc_id}", GRUPO_PADRAO))
        validade = _data_iso(reg.get("dataValidade"))
        validade_br = _data_br(reg.get("dataValidade"))
        # Adesao a programas estaduais e informativa: nao habilita nem trava,
        # entao nao pode contar como pendencia (tipo 'na', como o MANDATO do CRC).
        if codigo == "ADESAO-PROG":
            tipo = "na"
        elif validade is None:
            tipo = "pendente"
        else:
            tipo = "regular" if validade > hoje else "pendente"
        rotulo = (doc.get("nome") or "").strip() or f"Exigência {doc_id}"
        itens.append({
            "codigo": codigo,
            "grupo": grupo,
            "label": rotulo,
            "valor": validade_br or "—",
            "status": ("Vigente" if tipo == "regular"
                       else "Informativo" if tipo == "na"
                       else "Vencido" if validade else "Sem registro"),
            "tipo": tipo,
            "validade": validade_br,
        })
    itens.sort(key=lambda i: (i["grupo"], i["label"]))
    return itens


def _proxima_validade(itens: list[dict]) -> date | None:
    """A data mais proxima entre as exigencias ainda vigentes — o proximo prazo
    que o gestor precisa segurar. Mesma semantica do CAGEC: NAO e a validade do
    certificado (o CHE tambem nao tem uma)."""
    datas = []
    for i in itens:
        if i.get("tipo") == "regular" and i.get("validade"):
            try:
                datas.append(datetime.strptime(i["validade"], "%d/%m/%Y").date())
            except ValueError:
                continue
    return min(datas) if datas else None


def _alvos(cur) -> list[dict]:
    """Entidades a consultar: municipios ATIVOS do RS com CNPJ conhecido.

    A prefeitura vem de `municipios.cnpj` (coluna propria desde
    add_municipio_identificadores.sql) e e a `principal`. As demais entidades do
    mesmo municipio — tipicamente o Fundo Municipal de Saude — sao descobertas
    nas fontes FEDERAIS ja coletadas (sismob_obras, transferegov_pac), que
    trazem municipio_id + CNPJ.

    ⚠️ NUNCA por nome (armadilha 4). No CHE, cada entidade tem cadastro proprio
    e trava o SEU convenio: prefeitura habilitada nao destrava o convenio da
    saude se o fundo estiver com pendencia."""
    cur.execute("""
        SELECT id, nome, uf, regexp_replace(coalesce(cnpj,''), '\\D', '', 'g')
          FROM municipios
         WHERE active AND upper(coalesce(uf,'')) = %s
         ORDER BY nome
    """, (UF,))
    municipios = [{"id": r[0], "nome": r[1], "uf": r[2], "cnpj": r[3]}
                  for r in cur.fetchall()]
    if not municipios:
        return []

    ids = [m["id"] for m in municipios]
    # CNPJs das demais entidades, vindos do que ja foi coletado. `HAVING` nao e
    # necessario aqui porque o municipio_id vem da propria linha da fonte.
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

    alvos = []
    for m in municipios:
        vistos = set()
        if len(m["cnpj"] or "") == 14:
            alvos.append({**m, "cnpj14": m["cnpj"], "principal": True})
            vistos.add(m["cnpj"])
        else:
            log.warning("  %s/%s: sem CNPJ em `municipios` — a prefeitura nao "
                        "sera consultada (preencha em /api/control/municipios)",
                        m["nome"], m["uf"])
        for cnpj in sorted(extras.get(m["id"], set()) - vistos):
            alvos.append({**m, "cnpj14": cnpj, "principal": False})
    return alvos


_SQL = """
INSERT INTO cagec_situacao (municipio_id, nome, uf, cnpj, tipo, principal,
                            situacao, regular, validade, itens, pendencias,
                            pendencias_codigos, data_pesquisa, fonte, raw_data,
                            crc_em, crc_erro, atualizado_em)
VALUES (%(mid)s, %(nome)s, %(uf)s, %(cnpj)s, %(tipo)s, %(principal)s,
        %(situacao)s, %(regular)s, %(validade)s, %(itens)s::jsonb, %(pend)s,
        %(pend_cods)s, %(hoje)s, %(fonte)s, %(raw)s::jsonb,
        %(hoje)s, NULL, NOW())
ON CONFLICT (municipio_id, cnpj) DO UPDATE SET
    nome = EXCLUDED.nome, uf = EXCLUDED.uf, tipo = EXCLUDED.tipo,
    principal = EXCLUDED.principal,
    situacao = EXCLUDED.situacao, regular = EXCLUDED.regular,
    validade = EXCLUDED.validade, itens = EXCLUDED.itens,
    pendencias = EXCLUDED.pendencias,
    pendencias_codigos = EXCLUDED.pendencias_codigos,
    data_pesquisa = EXCLUDED.data_pesquisa,
    fonte = EXCLUDED.fonte, raw_data = EXCLUDED.raw_data,
    crc_em = EXCLUDED.crc_em, crc_erro = NULL,
    -- ⚠️ `itens_negativos` (CADIN/CFIL) NAO aparece aqui de proposito: ele e
    -- escrito por OUTRO coletor, em outra rodada. Toca-lo neste upsert apagaria
    -- a consulta negativa em silencio — o municipio apareceria limpo com uma
    -- inscricao no CADIN travando o repasse dele.
    atualizado_em = NOW()
"""


def _salvar(cur, alvo: dict, payload: dict, itens: list[dict], hoje: date) -> None:
    pendentes = [i["codigo"] for i in itens if i.get("tipo") == "pendente"]
    entidade = ((payload.get("listaEntidadeXDocumento") or [{}])[0]
                .get("entidade") or {})
    nome_entidade = (entidade.get("nome") or "").strip() or alvo["nome"]
    cur.execute(_SQL, {
        "mid": alvo["id"],
        "nome": nome_entidade,
        "uf": alvo["uf"],
        "cnpj": _mascara_cnpj(alvo["cnpj14"]),
        # O CHE nao classifica a natureza da entidade; o rotulo honesto e o que
        # sabemos por construcao do alvo.
        "tipo": "Município" if alvo["principal"] else "Entidade do município",
        "principal": alvo["principal"],
        # ⚠️ "Habilitado"/"Com pendencia(s)" e NAO "Regular"/"Irregular": este
        # ultimo e o vocabulario do CAGEC, e usa-lo aqui convidaria o gestor a
        # comparar duas coisas que nao sao a mesma.
        "situacao": "Habilitado" if not pendentes else "Com pendência(s)",
        "regular": not pendentes,
        "validade": _proxima_validade(itens),
        "itens": json.dumps(itens, ensure_ascii=False),
        "pend": len(pendentes),
        "pend_cods": pendentes,
        "hoje": hoje,
        "fonte": FONTE,
        "raw": json.dumps(payload, ensure_ascii=False),
    })


def _limpar_sumidos(cur, municipio_id: int, cnpjs: list[str]) -> int:
    """Apaga entidade do CHE que nao foi mais vista neste municipio.

    ⚠️ Filtra por `fonte` — sem isso, uma rodada do CHE apagaria a linha do
    CAGEC de um tenant que tivesse os dois estados."""
    if not cnpjs:
        return 0
    cur.execute("DELETE FROM cagec_situacao WHERE municipio_id = %s "
                "AND fonte = %s AND NOT (cnpj = ANY(%s))",
                (municipio_id, FONTE, cnpjs))
    return cur.rowcount or 0


def _log_ingest(cur, conn, status: str, inseridos: int, erro: str | None = None):
    """Uma linha final em ingestion_log (source='che_rs'), como os demais."""
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES ('che_rs', %s, %s, %s, NOW())",
            (status, inseridos, erro))
        conn.commit()
    except Exception as e:  # a contabilidade nunca derruba a coleta
        log.warning("ingestion_log falhou: %s", str(e)[:120])


def ingest(dry: bool = False) -> int:
    hoje = date.today()
    from ingestion._resilience import get_sync_db_url, neon_connect
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            alvos = _alvos(cur)
            if not alvos:
                # Nenhum municipio do RS com CNPJ: a fonte NAO SE APLICA a este
                # tenant. Mesmo criterio do CAGEC fora de MG — e `success`, nao
                # falha, senao o watchdog cobraria para sempre uma fonte que
                # nunca deveria rodar aqui.
                log.info("nenhum municipio do RS com CNPJ conhecido — "
                         "CHE nao se aplica a este tenant")
                if not dry:
                    _log_ingest(cur, conn, "success", 0)
                return 0

            log.info("CHE-RS: %d entidade(s) a consultar", len(alvos))
            gravados = falhas = 0
            por_municipio: dict[int, list[str]] = {}
            with httpx.Client(follow_redirects=True) as client:
                for a in alvos:
                    rotulo = f"{a['nome']}/{a['uf']} {_mascara_cnpj(a['cnpj14'])}"
                    try:
                        payload = consultar(client, a["cnpj14"])
                    except Exception as e:
                        falhas += 1
                        log.warning("  %s: %s: %s", rotulo, type(e).__name__, str(e)[:120])
                        continue
                    itens = itens_do_payload(payload or {}, hoje)
                    if payload is None or not itens:
                        # ⚠️ NAO E FALHA. Entidade sem cadastro no CHE e um fato
                        # sobre o Estado, nao um erro nosso — e contar isso como
                        # falha marcaria toda rodada como `partial`, com o
                        # watchdog cobrando eternamente uma fonte saudavel.
                        # (Medido: o Fundo Municipal de Saude de Santa Maria nao
                        # tem cadastro no CHE, e o autocomplete confirma.)
                        # Tambem nao se grava linha vazia: ela diria ao gestor
                        # que a entidade esta habilitada com zero exigencias.
                        log.info("  %s: sem cadastro no CHE", rotulo)
                        continue
                    pend = [i for i in itens if i["tipo"] == "pendente"]
                    log.info("  %s: %d exigência(s), %d pendente(s)%s",
                             rotulo, len(itens), len(pend),
                             "" if not pend else " -> " + ", ".join(i["codigo"] for i in pend))
                    if dry:
                        continue
                    _salvar(cur, a, payload, itens, hoje)
                    gravados += 1
                    por_municipio.setdefault(a["id"], []).append(_mascara_cnpj(a["cnpj14"]))

            if dry:
                return 0
            for mid, cnpjs in por_municipio.items():
                n = _limpar_sumidos(cur, mid, cnpjs)
                if n:
                    log.info("  municipio %s: %d entidade(s) fora do CHE removida(s)", mid, n)
            conn.commit()
            log.info("=== CHE-RS: %d entidade(s) gravada(s), %d falha(s) ===",
                     gravados, falhas)
            _log_ingest(cur, conn, "success" if not falhas else "partial", gravados)
            return gravados
        except Exception as e:
            conn.rollback()
            log.error("CHE-RS falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ingest(dry="--dry" in sys.argv)
