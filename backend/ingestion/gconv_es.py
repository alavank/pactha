"""
Convenios estaduais do ESPIRITO SANTO (GConv/SIGA, SEGER) -> convenios_estadual.

O equivalente capixaba do SIGCON-MG. A fonte e o dado aberto do Portal da
Transparencia do ES (CKAN dados.es.gov.br, dataset
`portal-da-transparencia-convenios-do-estado`, fonte declarada = SIGEFES),
atualizado diariamente. NAO raspa o GConv-web (JSF) nem a certidao da SEFAZ
(que tem captcha) — so o CSV publico.

Grava com `fonte='GCONV-ES'`: o router de convenios trata fonte desconhecida
como match exato e o filtro "nao-FNS" ja inclui essas linhas na aba Convenios
Estaduais e no BI, sem tocar no frontend (ver routers/convenios.py:207-230).

⚠️ CASAMENTO POR CNPJ, nunca por nome. No CSV, `nomeMunicipio` = "SEM MUNICIPIO
INFORMADO" e `codIBGEMunicipio` vem VAZIO em todas as linhas — casar por nome
pegaria APAE, Pestalozzi, CDL etc. A chave e `cnpjConcedenteConvenente` (o CNPJ
da prefeitura convenente), cruzado com o mapa CNPJ->municipio que montamos das
fontes federais (transferegov_pac, sismob), pois `municipios` nao guarda CNPJ.

Rodavel por Scheduled Task (worker do tenant que tem municipio do ES) ou a mao:
    python -u ingestion/gconv_es.py            # coleta de verdade
    python -u ingestion/gconv_es.py --dry      # so parseia e mostra, sem banco
"""
import csv
import io
import json
import logging
import os
import re
import sys
from datetime import date, datetime

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("gconv_es")

CKAN_PKG = ("https://dados.es.gov.br/api/3/action/package_show"
            "?id=portal-da-transparencia-convenios-do-estado")
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0 coleta de dados abertos ES)"}
FONTE = "GCONV-ES"
# Quantos exercicios para tras varrer. Convenio de 2024 ainda pode estar vigente
# em 2026; menos que isto perderia vigencias em curso.
ANOS_ATRAS = 2

# Situacoes que a UF nao escreve — derivamos das datas, na ordem de prioridade.
_HOJE = None  # injetado em ingest(); modulo nao chama date.today() no import


def _so_digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _parse_valor(s) -> float | None:
    """'900000,00' / '1.321.259,80' -> float. Vazio -> None."""
    t = str(s or "").strip()
    if not t:
        return None
    t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _parse_data(s):
    """'13/05/2026 00:00:00' ou '13/05/2026' -> date. Vazio -> None."""
    t = str(s or "").strip()
    if not t:
        return None
    t = t.split(" ")[0]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def _situacao(row: dict, hoje: date) -> str:
    """A UF nao publica um campo de situacao — deriva das datas.
    Ordem importa: rescisao e conclusao ganham de vigencia."""
    if _parse_data(row.get("dataRescisao")):
        return "Rescindido"
    if _parse_data(row.get("dataCancelamento")):
        return "Cancelado"
    if _parse_data(row.get("dataConclusao")):
        return "Concluído"
    fim = _parse_data(row.get("dataFimVigencia"))
    ini = _parse_data(row.get("dataInicioVigencia"))
    if fim and fim < hoje:
        return "Encerrado"
    if ini and ini > hoje:
        return "A iniciar"
    if ini or fim:
        return "Vigente"
    return "Celebrado"


def _ckan_urls(client: httpx.Client) -> dict[str, dict[str, str]]:
    """Resolve as URLs dos CSVs por ANO a partir do CKAN, por NOME do recurso —
    nunca cravando o id do resource, que muda a cada exercicio."""
    r = client.get(CKAN_PKG, headers=UA, timeout=60)
    r.raise_for_status()
    recursos = r.json()["result"]["resources"]
    por_ano: dict[str, dict[str, str]] = {}
    for x in recursos:
        nome = (x.get("name") or "").lower()
        url = x.get("url")
        if not url:
            continue
        m = re.search(r"(\d{4})", nome)
        if not m:
            continue
        ano = m.group(1)
        if nome.startswith("convenios-"):
            por_ano.setdefault(ano, {})["convenios"] = url
        elif nome.startswith("conveniosexecucaoorcamentaria"):
            por_ano.setdefault(ano, {})["execucao"] = url
    return por_ano


def _baixar_csv(client: httpx.Client, url: str) -> list[dict]:
    """CSV `;`-separado, UTF-8 com BOM. O /download do CKAN responde 302 para
    uma URL S3 pre-assinada — httpx segue com follow_redirects."""
    r = client.get(url, headers=UA, timeout=180, follow_redirects=True)
    r.raise_for_status()
    texto = r.content.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(texto), delimiter=";"))


def _repasses_por_convenio(linhas: list[dict]) -> dict[str, float]:
    """Soma ValorPago por CodigoConvenioConcedido (casa com `cod` do convenio)."""
    out: dict[str, float] = {}
    for r in linhas:
        cod = str(r.get("CodigoConvenioConcedido") or "").strip()
        if not cod:
            continue
        out[cod] = out.get(cod, 0.0) + (_parse_valor(r.get("ValorPago")) or 0.0)
    return out


def _mapa_cnpj_municipio(cur) -> dict[str, int]:
    """{cnpj(14 digitos): municipio_id} para os municipios ATIVOS do ES.

    `municipios` nao tem CNPJ — ele vem das fontes federais ja coletadas
    (transferegov_pac e sismob_obras trazem municipio_id + cnpj). Sem coleta
    federal antes, o mapa fica vazio e o coletor nao tem como casar (dependencia
    analoga a do CAGEC, que infere o CNPJ das emendas).

    ⚠️ CNPJ AMBIGUO NAO ENTRA. Num tenant com varios municipios do ES, um mesmo
    CNPJ pode aparecer ligado a dois municipios nas fontes federais — tipico de
    consorcio, fundo ou autarquia que atende mais de um. Escolher um seria
    gravar o convenio no municipio ERRADO, calado. Entao esse CNPJ e EXCLUIDO do
    mapa e registrado no log: melhor nao coletar aquele convenio do que atribuir
    ao lugar errado. `HAVING count(DISTINCT municipio_id) = 1` faz o corte no
    banco; os ambiguos saem numa segunda consulta so para avisar."""
    base = """
        SELECT cnpj_digitos, min(municipio_id) AS municipio_id FROM (
            SELECT regexp_replace(coalesce(p.cnpj,''), '\\D', '', 'g') AS cnpj_digitos,
                   p.municipio_id
            FROM transferegov_pac p
            JOIN municipios m ON m.id = p.municipio_id
            WHERE m.active AND upper(coalesce(m.uf,'')) = 'ES'
            UNION ALL
            SELECT regexp_replace(coalesce(s.nu_cnpj,''), '\\D', '', 'g'),
                   s.municipio_id
            FROM sismob_obras s
            JOIN municipios m ON m.id = s.municipio_id
            WHERE m.active AND upper(coalesce(m.uf,'')) = 'ES'
        ) t
        WHERE length(cnpj_digitos) = 14
        GROUP BY cnpj_digitos
    """
    cur.execute(base + " HAVING count(DISTINCT municipio_id) = 1")
    mapa = {r[0]: r[1] for r in cur.fetchall()}
    # Os ambiguos, so para o log — nao entram no mapa.
    cur.execute(base + " HAVING count(DISTINCT municipio_id) > 1")
    for cnpj, _ in cur.fetchall():
        log.warning("CNPJ %s liga a mais de um municipio do ES nas fontes "
                    "federais — EXCLUIDO do mapa (nao atribuir convenio a chute)", cnpj)
    return mapa


def _registro(row: dict, municipio_id: int, repasse, hoje: date) -> dict:
    cod = str(row.get("cod") or "").strip()
    v_conc = _parse_valor(row.get("valorConcessao"))
    v_adit = _parse_valor(row.get("valorTotalAditivos")) or 0.0
    v_contra = _parse_valor(row.get("valorContrapartida"))
    # valor_total = repasse do Estado + contrapartida + aditivos (espelha o SIGCON)
    base = (v_conc or 0.0) + v_adit
    v_total = base + (v_contra or 0.0) if (v_conc or v_contra) else v_conc
    celebr = _parse_data(row.get("dataCelebracao"))
    return {
        # GCONV-ES-<cod>: o indice unico de nr_sigcon e GLOBAL — o prefixo evita
        # colisao com um numero identico do SIGCON-MG noutro tenant.
        "nr_sigcon": f"{FONTE}-{cod}"[:50],
        "municipio_id": municipio_id,
        "convenente_nome": (row.get("nomeConcedenteConvenente") or "")[:500] or None,
        "orgao_concedente": (row.get("ugNome") or "").strip()[:500] or None,
        "objeto": (row.get("objeto") or row.get("nome") or "").strip() or None,
        "objetivo": (row.get("objetivo") or "").strip() or None,
        "situacao": _situacao(row, hoje),
        "tp_instrumento": (row.get("nomeTipoTransferencia") or "").strip()[:100] or None,
        "valor_concedente": v_conc,
        "valor_contrapartida": v_contra,
        "valor_total": v_total,
        "valor_repassado": repasse if repasse else None,
        "dt_publicacao": _parse_data(row.get("dataPublicacao")),
        "dt_vigencia_inicial": _parse_data(row.get("dataInicioVigencia")),
        "dt_vigencia_final": _parse_data(row.get("dataFimVigencia")),
        "ano": celebr.year if celebr else None,
        "fonte": FONTE,
        "raw_data": row,
    }


_SQL = """
    INSERT INTO convenios_estadual
        (nr_sigcon, municipio_id, convenente_nome, orgao_concedente, objeto,
         objetivo, situacao, tp_instrumento, valor_concedente,
         valor_contrapartida, valor_total, valor_repassado, dt_publicacao,
         dt_vigencia_inicial, dt_vigencia_final, dt_vigencia_atual, ano, fonte,
         raw_data, created_at, updated_at)
    VALUES
        (%(nr_sigcon)s, %(municipio_id)s, %(convenente_nome)s, %(orgao_concedente)s,
         %(objeto)s, %(objetivo)s, %(situacao)s, %(tp_instrumento)s,
         %(valor_concedente)s, %(valor_contrapartida)s, %(valor_total)s,
         %(valor_repassado)s, %(dt_publicacao)s, %(dt_vigencia_inicial)s,
         %(dt_vigencia_final)s, %(dt_vigencia_final)s, %(ano)s, %(fonte)s,
         %(raw_data)s::jsonb, NOW(), NOW())
    ON CONFLICT (nr_sigcon) DO UPDATE SET
        situacao = EXCLUDED.situacao,
        convenente_nome = COALESCE(EXCLUDED.convenente_nome, convenios_estadual.convenente_nome),
        orgao_concedente = COALESCE(EXCLUDED.orgao_concedente, convenios_estadual.orgao_concedente),
        objeto = COALESCE(EXCLUDED.objeto, convenios_estadual.objeto),
        objetivo = COALESCE(EXCLUDED.objetivo, convenios_estadual.objetivo),
        tp_instrumento = COALESCE(EXCLUDED.tp_instrumento, convenios_estadual.tp_instrumento),
        valor_concedente = COALESCE(EXCLUDED.valor_concedente, convenios_estadual.valor_concedente),
        valor_contrapartida = COALESCE(EXCLUDED.valor_contrapartida, convenios_estadual.valor_contrapartida),
        valor_total = COALESCE(EXCLUDED.valor_total, convenios_estadual.valor_total),
        valor_repassado = COALESCE(EXCLUDED.valor_repassado, convenios_estadual.valor_repassado),
        dt_publicacao = COALESCE(EXCLUDED.dt_publicacao, convenios_estadual.dt_publicacao),
        dt_vigencia_inicial = COALESCE(EXCLUDED.dt_vigencia_inicial, convenios_estadual.dt_vigencia_inicial),
        dt_vigencia_final = COALESCE(EXCLUDED.dt_vigencia_final, convenios_estadual.dt_vigencia_final),
        dt_vigencia_atual = COALESCE(EXCLUDED.dt_vigencia_final, convenios_estadual.dt_vigencia_atual),
        ano = COALESCE(EXCLUDED.ano, convenios_estadual.ano),
        -- fonte NAO entra no UPDATE: uma linha que ja e SIGCON/FNS nunca vira
        -- GCONV por um match de CNPJ acidental. So o INSERT define a fonte.
        raw_data = EXCLUDED.raw_data,
        updated_at = NOW()
"""


def _coletar(cur, mapa: dict[str, int], anos: list[int], client: httpx.Client,
             urls: dict, hoje: date) -> tuple[int, int]:
    achados = gravados = 0
    for ano in anos:
        chave = str(ano)
        blocos = urls.get(chave)
        if not blocos or "convenios" not in blocos:
            log.info("  %s: sem CSV de convenios no CKAN", ano)
            continue
        convenios = _baixar_csv(client, blocos["convenios"])
        repasses = {}
        if blocos.get("execucao"):
            try:
                repasses = _repasses_por_convenio(_baixar_csv(client, blocos["execucao"]))
            except Exception as e:
                log.warning("  %s: execucao falhou (%s) — segue sem repasse", ano, str(e)[:80])
        do_ano = sem_cod = 0
        for row in convenios:
            cnpj = _so_digitos(row.get("cnpjConcedenteConvenente"))
            mid = mapa.get(cnpj)
            if not mid:
                continue
            cod = str(row.get("cod") or "").strip()
            if not cod:
                # Sem `cod` o nr_sigcon vira "GCONV-ES-" para TODA linha assim, e o
                # ON CONFLICT global colapsaria N convenios distintos num registro
                # so — perda calada. Sem chave estavel, nao grava.
                sem_cod += 1
                continue
            achados += 1
            do_ano += 1
            reg = _registro(row, mid, repasses.get(cod), hoje)
            reg["raw_data"] = json.dumps(reg["raw_data"], ensure_ascii=False)
            try:
                cur.execute("SAVEPOINT sp_gconv")
                cur.execute(_SQL, reg)
                cur.execute("RELEASE SAVEPOINT sp_gconv")
                gravados += 1
            except Exception as e:
                cur.execute("ROLLBACK TO SAVEPOINT sp_gconv")
                log.warning("  upsert falhou %s: %s", reg["nr_sigcon"], str(e)[:110])
        if sem_cod:
            log.warning("  %s: %d linha(s) de municipio do ES SEM cod — nao gravadas "
                        "(sem chave estavel)", ano, sem_cod)
        log.info("  %s: %d convenio(s) dos municipios do ES", ano, do_ano)
    return achados, gravados


def ingest() -> int:
    hoje = date.today()
    anos = list(range(hoje.year, hoje.year - ANOS_ATRAS - 1, -1))
    # ⚠️ `neon_connect` e CONTEXT MANAGER (com retry exponencial), nao devolve a
    # conexao — `conn = neon_connect(...)` entrega um _GeneratorContextManager e
    # estoura no primeiro `.cursor()`. O `with` tambem fecha a conexao sozinho,
    # dispensando o finally.
    from ingestion._resilience import get_sync_db_url, neon_connect
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            mapa = _mapa_cnpj_municipio(cur)
            if not mapa:
                # Nenhum municipio do ES neste tenant: fonte nao se aplica. Nao e
                # falha — e o mesmo criterio do CAGEC fora de MG.
                log.info("nenhum municipio do ES com CNPJ conhecido — GConv-ES nao se aplica a este tenant")
                _log_ingest(cur, conn, "success", 0)
                return 0
            log.info("GConv-ES: %d CNPJ(s) de municipio do ES no mapa | anos %s",
                     len(mapa), anos)
            with httpx.Client() as client:
                urls = _ckan_urls(client)
                achados, gravados = _coletar(cur, mapa, anos, client, urls, hoje)
            conn.commit()
            log.info("GConv-ES: %d convenio(s) encontrados, %d gravados", achados, gravados)
            _log_ingest(cur, conn, "success" if gravados == achados else "partial", gravados)
            return gravados
        except Exception as e:
            conn.rollback()
            log.error("GConv-ES falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


def _log_ingest(cur, conn, status: str, inseridos: int, erro: str | None = None):
    """Uma linha final em ingestion_log (source='gconv_es'), como os demais."""
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES (%s, %s, %s, %s, NOW())",
            ("gconv_es", status, inseridos, erro),
        )
        conn.commit()
    except Exception as e:
        log.warning("nao consegui gravar ingestion_log: %s", str(e)[:80])


def _dry():
    """Parseia e mostra o que SERIA gravado, sem tocar no banco. Usa CNPJs fixos
    das 3 cidades para validar o parser contra o CSV real."""
    hoje = date.today()
    anos = list(range(hoje.year, hoje.year - ANOS_ATRAS - 1, -1))
    mapa = {"27142694000158": 1, "27174077000134": 2, "27165190000153": 3}
    nomes = {1: "Anchieta", 2: "Conc.Barra", 3: "Guarapari"}
    with httpx.Client() as client:
        urls = _ckan_urls(client)
        for ano in anos:
            blocos = urls.get(str(ano))
            if not blocos or "convenios" not in blocos:
                print(f"{ano}: sem CSV"); continue
            convenios = _baixar_csv(client, blocos["convenios"])
            repasses = _repasses_por_convenio(_baixar_csv(client, blocos["execucao"])) if blocos.get("execucao") else {}
            hits = [r for r in convenios if _so_digitos(r.get("cnpjConcedenteConvenente")) in mapa]
            print(f"\n=== {ano}: {len(hits)} convenio(s) dos 3 municipios ===")
            for r in hits:
                mid = mapa[_so_digitos(r["cnpjConcedenteConvenente"])]
                reg = _registro(r, mid, repasses.get(str(r.get("cod") or "").strip()), hoje)
                print(f"  [{nomes[mid]}] {reg['nr_sigcon']} | {reg['situacao']} | "
                      f"R$ {reg['valor_total'] or 0:,.2f} | pago R$ {reg['valor_repassado'] or 0:,.2f}")
                print(f"       {(reg['orgao_concedente'] or '')[:52]} | {(reg['objeto'] or '')[:52]}")
                print(f"       vig {reg['dt_vigencia_inicial']} -> {reg['dt_vigencia_final']} | ano {reg['ano']}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    if "--dry" in sys.argv:
        _dry()
    else:
        ingest()
