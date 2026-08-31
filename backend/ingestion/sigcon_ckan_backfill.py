"""Backfill de contrapartida + vigência dos convênios SIGCON-MG a partir do
dataset PÚBLICO do Estado (CKAN dados.mg.gov.br — 'convenios-saida').

POR QUE: o click-through do detalhe no portal SIGCON é instável e limitado à
1a página — pega poucos convênios por rodada. O dataset CKAN tem TODOS os
convênios do Estado (~88k) com valor de contrapartida e datas de vigência.
Aqui casamos por nr_siafi / nr_sigcon com os nossos convênios e preenchemos
valor_contrapartida + dt_vigencia_inicial/atual/final (sem scraping, completo).

NAO tem data de ASSINATURA nem responsáveis/emendas — esses seguem vindo do
scraper logado (sigcon_scraper). Este modulo cobre contrapartida/vigência/dias.

Recurso: 'Convênio' (dm_convenio.csv.gz) do pacote convenios-saida.
Uso: COFRE_KEY (nao precisa) DATABASE_URL_SYNC=... python ingestion/sigcon_ckan_backfill.py
"""
from __future__ import annotations
import os
import csv
import gzip
import io
import json
import logging
from datetime import datetime

import httpx
import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sigcon_ckan_backfill")

# Recurso "Convênio" (dm_convenio) do pacote convenios-saida (dados.mg.gov.br)
DM_CONVENIO_URL = ("https://dados.mg.gov.br/dataset/52fcf7e5-d9a6-4b17-a491-12a5a978aecd/"
                   "resource/23de2c3f-cbf6-494a-8b32-4c9c151fb999/download/dm_convenio.csv.gz")
# Recurso "Convênio de Saída" (ft_convenio) — traz vr_rep_concede_atual = valor
# EFETIVAMENTE REPASSADO pelo concedente (o "pagamento" real). Chaveado por
# id_convenio (liga ao nr_siafi/nr_sigcon via dm_convenio).
FT_CONVENIO_URL = ("https://dados.mg.gov.br/dataset/52fcf7e5-d9a6-4b17-a491-12a5a978aecd/"
                   "resource/d8b48c2b-c2ec-451a-99f0-0421987ceeba/download/ft_convenio.csv.gz")
# Dimensoes usadas so pela INSERCAO (ver `_inserir_faltantes`). Juntas somam
# ~1,9 MB — o `dm_convenio` sozinho ja tem 9,6 MB.
_BASE_REC = ("https://dados.mg.gov.br/dataset/52fcf7e5-d9a6-4b17-a491-12a5a978aecd/resource/")
DM_MUNICIPIO_URL = _BASE_REC + "9cd4ddc8-7efd-45dc-b572-9ea6840c9815/download/dm_municipio.csv.gz"
DM_CONVENENTE_URL = _BASE_REC + "3b9d9df2-1a50-451d-bc7e-3a0b82fcf821/download/dm_convenente.csv.gz"
DM_ORGAO_URL = _BASE_REC + "cf96b7cc-b534-4c4b-8338-dce4c9ed5517/download/dm_orgao_concedente.csv.gz"
DM_SITUACAO_URL = _BASE_REC + "1ddced7a-dfcf-4ca2-8c3c-23439b944bb2/download/dm_situacao_convenio.csv.gz"
# ⚠️ A SITUACAO DO CONVENIO MORA AQUI, e nao no `ft_convenio`: e o unico fato do
# pacote com a coluna `id_situacao`.
FT_TIPOATENDIMENTO_URL = (_BASE_REC +
                          "b8c80cc1-f5fe-4ff3-b3b9-c9071bfd1afb/download/ft_convenio_tipoatendimento.csv.gz")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131 Safari/537.36"


def _clean_col(c: str) -> str:
    """Normaliza cabecalho CSV: remove BOM (UTF-8 lido como latin-1 vira 'ï»¿')."""
    return (c or "").strip().lstrip("ï»¿﻿ ").strip()


def _sync_url() -> str:
    return (os.getenv("DATABASE_URL_SYNC", "")
            .replace("&channel_binding=require", "").replace("?channel_binding=require", ""))


def _money(s: str):
    s = (s or "").strip().replace("R$", "").strip()
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _dt(s: str):
    s = (s or "").strip()[:10]
    for f in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def _baixar(url: str) -> bytes:
    with httpx.Client(timeout=180, follow_redirects=True, verify=False,
                      headers={"User-Agent": UA}) as cli:
        r = cli.get(url)
        r.raise_for_status()
        return r.content


def _baixar_dataset() -> bytes:
    return _baixar(DM_CONVENIO_URL)


def _linhas(gz_bytes: bytes):
    """Itera o csv.gz como dicts, com o cabecalho ja limpo do BOM.

    ⚠️ latin-1 e delimitador ';'. E o `_clean_col` nao e enfeite: o arquivo e
    UTF-8 COM BOM lido como latin-1, entao a PRIMEIRA coluna chega como
    'ï»¿id_situacao'. Sem limpar, todo .get() dessa coluna devolve None e o
    casamento inteiro sai vazio — sem erro nenhum. Eu reproduzi esse exato
    engano durante a auditoria."""
    with gzip.open(io.BytesIO(gz_bytes), "rt", encoding="latin-1") as f:
        rd = csv.reader(f, delimiter=";")
        cols = [_clean_col(c) for c in next(rd)]
        for row in rd:
            yield dict(zip(cols, row))


def _fato_por_convenio(gz_bytes: bytes) -> dict:
    """id_convenio -> {municipio, convenente, orgao, valores} do ft_convenio.

    Mesma varredura que o `_repasse_por_id` faz, mas guardando tambem as chaves
    de dimensao — sao elas que permitem partir do MUNICIPIO em vez de partir do
    que a plataforma ja conhece."""
    tmp: dict = {}
    for r in _linhas(gz_bytes):
        idc = (r.get("id_convenio") or "").strip()
        if not idc:
            continue
        ano = int(r.get("ano_particao") or 0)
        if idc in tmp and ano < tmp[idc]["_ano"]:
            continue
        tmp[idc] = {
            "_ano": ano,
            "id_municipio": (r.get("id_municipio") or "").strip(),
            "id_convenente": (r.get("id_convenente") or "").strip(),
            "id_orgao": (r.get("id_orgao") or "").strip(),
            "concede": _money(r.get("vr_concede_atual")),
            "contra": _money(r.get("vr_contra_atual")),
            "total": _money(r.get("vr_total_atual")),
            "repassado": _money(r.get("vr_rep_concede_atual")),
        }
    return tmp


def _situacao_por_convenio(gz_tipo: bytes, gz_sit: bytes) -> dict:
    """id_convenio -> situacao PUBLICADA pelo Estado, no vocabulario da plataforma.

    ⚠️ A situacao NAO esta no `ft_convenio` — esta no `ft_convenio_tipoatendimento`,
    que tem a coluna `id_situacao`. Levei a auditoria inteira achando que o dado
    aberto nao publicava situacao.

    ⚠️ A TRADUCAO E MEDIDA, NAO ADIVINHADA. Nos 18 convenios de Araujos que
    existem nos dois lados, o cruzamento deu 18/18 sem excecao:
        ENCERRADO -> "Encerrado"  (12 de 12)
        VIGENTE   -> "Em vigor"   (6 de 6)
    `CANCELADO` segue o mesmo padrao de caixa e cai em "Cancelado".

    ⚠️ `CONVENIO CADASTRADO` FICA VERBATIM, de proposito. Ele nao aparece em
    NENHUM dos 18 casados — ou seja, nao ha uma unica linha que autorize traduzi-lo
    — e mapea-lo para "Cadastramento" (que na plataforma significa ANTES da
    celebracao) seria mentira: dos 45 convenios de Araujos com esse rotulo, 23 ja
    tiveram repasse do Estado. Melhor a palavra do portal do que um palpite meu.
    """
    nomes: dict = {}
    for r in _linhas(gz_sit):
        i = (r.get("id_situacao") or "").strip()
        v = int(r.get("fl_versao") or 0)
        if i and (i not in nomes or v >= nomes[i][0]):
            nomes[i] = (v, (r.get("nome") or "").strip())
    traduz = {"ENCERRADO": "Encerrado", "VIGENTE": "Em vigor", "CANCELADO": "Cancelado"}
    out: dict = {}
    vistos: dict = {}
    for r in _linhas(gz_tipo):
        idc = (r.get("id_convenio") or "").strip()
        if not idc:
            continue
        ano = int(r.get("ano_particao") or 0)
        if idc in vistos and ano < vistos[idc]:
            continue
        vistos[idc] = ano
        bruto = nomes.get((r.get("id_situacao") or "").strip(), (0, ""))[1]
        out[idc] = traduz.get(bruto, bruto) or None
    return out


def _repasse_por_id(gz_bytes: bytes) -> dict:
    """id_convenio -> valor repassado real (vr_rep_concede_atual, versao mais recente)."""
    tmp: dict = {}
    with gzip.open(io.BytesIO(gz_bytes), "rt", encoding="latin-1") as f:
        rd = csv.reader(f, delimiter=";")
        idx = {_clean_col(c): i for i, c in enumerate(next(rd))}

        def g(row, c):
            i = idx.get(c)
            return row[i] if i is not None and i < len(row) else ""

        for row in rd:
            idc = (g(row, "id_convenio") or "").strip()
            if not idc:
                continue
            ano = int(g(row, "ano_particao") or 0)
            rep = _money(g(row, "vr_rep_concede_atual"))
            if idc not in tmp or ano >= tmp[idc][0]:
                tmp[idc] = (ano, rep)
    return {k: v[1] for k, v in tmp.items()}


def _index_dataset(gz_bytes: bytes):
    """Indexa dm_convenio por nr_siafi, por nr_sigcon e por id_convenio.

    O terceiro indice (`by_id`) e o que a INSERCAO usa: ela parte do municipio,
    entao chega com o `id_convenio` do fato e precisa da dimensao a partir dele.
    Ele carrega mais campos que os outros dois — objetivo, tipo de instrumento,
    numero do plano e a data de publicacao REAL, que a plataforma nao tinha (o
    scraper grava 1o de janeiro como substituto quando nao abre o detalhe)."""
    by_siafi: dict = {}
    by_sigcon: dict = {}
    by_id: dict = {}
    n = 0
    with gzip.open(io.BytesIO(gz_bytes), "rt", encoding="latin-1") as f:
        rd = csv.reader(f, delimiter=";")
        cols = next(rd)
        idx = {_clean_col(c): i for i, c in enumerate(cols)}

        def g(row, c):
            i = idx.get(c)
            return row[i] if i is not None and i < len(row) else ""

        for row in rd:
            n += 1
            rec = {
                "id": (g(row, "id_convenio") or "").strip(),
                "obj": (g(row, "nome") or g(row, "objetivo") or "").strip(),
                "contra": _money(g(row, "vr_contra_public")),
                "vig_ini": _dt(g(row, "dt_vigencia_inicial")),
                "vig_fim": _dt(g(row, "dt_vigencia_final")),
                "vig_atual": _dt(g(row, "dt_vigencia_atual")),
                "ver": int(g(row, "fl_versao") or 0),
            }
            siafi = (g(row, "nr_siafi") or "").strip()
            sigcon = (g(row, "nr_sigcon") or "").strip()
            if siafi and (siafi not in by_siafi or rec["ver"] >= by_siafi[siafi]["ver"]):
                by_siafi[siafi] = rec
            if sigcon and (sigcon not in by_sigcon or rec["ver"] >= by_sigcon[sigcon]["ver"]):
                by_sigcon[sigcon] = rec
            idc = rec["id"]
            if idc and (idc not in by_id or rec["ver"] >= by_id[idc]["ver"]):
                by_id[idc] = {**rec, "siafi": siafi, "sigcon": sigcon,
                              "plano": (g(row, "nr_plano_sigcon") or "").strip(),
                              "objetivo": (g(row, "objetivo") or "").strip(),
                              "tp": (g(row, "tp_instrumento") or "").strip(),
                              "dt_pub": _dt(g(row, "dt_publicacao"))}
    log.info(f"dataset CKAN: {n} convenios | by_siafi={len(by_siafi)} "
             f"by_sigcon={len(by_sigcon)} by_id={len(by_id)}")
    return by_siafi, by_sigcon, by_id


_SQL_INSERT = """
    INSERT INTO convenios_estadual
        (municipio_id, nr_sigcon, nr_siafi, nr_plano_trabalho, convenente_nome,
         orgao_concedente, objeto, objetivo, situacao, tp_instrumento,
         valor_concedente, valor_contrapartida, valor_total, valor_repassado,
         dt_publicacao, dt_vigencia_inicial, dt_vigencia_final, dt_vigencia_atual,
         ano, fonte, raw_data, created_at, updated_at)
    VALUES (%(municipio_id)s, %(nr_sigcon)s, %(nr_siafi)s, %(nr_plano)s, %(convenente)s,
            %(orgao)s, %(objeto)s, %(objetivo)s, %(situacao)s, %(tp_instrumento)s,
            %(concede)s, %(contra)s, %(total)s, %(repassado)s,
            %(dt_pub)s, %(vig_ini)s, %(vig_fim)s, %(vig_atual)s,
            %(ano)s, 'SIGCON-MG', %(raw)s::jsonb, NOW(), NOW())
    ON CONFLICT (nr_siafi) WHERE nr_siafi IS NOT NULL AND nr_siafi <> ''
    DO NOTHING
"""


def _inserir_faltantes(conn, dim_by_id: dict, fatos: dict, situacoes: dict) -> int:
    """INSERE os convenios que o Estado publica e a plataforma nao tem.

    ⚠️ POR QUE ISTO PRECISOU EXISTIR. Ate aqui este arquivo era UPDATE-ONLY: ele
    seleciona os convenios que a tabela JA TEM e atualiza um por um. Nao havia um
    unico INSERT. O dataset com TODOS os convenios do municipio era baixado a
    cada 6 horas, lido e descartado.

    Medido em Araujos (auditoria de 30/08/2026): o Estado publica 63 convenios da
    prefeitura e a plataforma tinha 18. Faltavam 45, R$ 4.465.654,15 — e 23 deles
    JA TINHAM REPASSE do Estado. Sao, na quase totalidade, Transferencias
    Especiais de emenda parlamentar (2021-2025) e o estoque de 2007-2014, que a
    grade logada do SIGCON simplesmente nao lista.

    ⚠️ O RECORTE E O CNPJ DA PREFEITURA, e nao a localizacao. O `dm_municipio` do
    Estado diz onde o CONVENENTE fica, nao quem ele e: dos 75 convenios com
    municipio "Araujos", 12 sao de APAE, Lar Santo Ambrosio, Araujos EC, Guarani
    FC e uma caixa escolar. Nao sao convenios do municipio e nao entram. Por isso
    o filtro casa `dm_convenente.nr_documento` contra `municipios.cnpj` — que
    esta preenchido nos 42 municipios ativos, conferido antes de escrever isto.

    ⚠️ ON CONFLICT (nr_siafi) DO NOTHING: quem manda no convenio e a tela logada.
    Este caminho so ACRESCENTA o que ela nao alcanca; nunca sobrescreve o que ela
    ja trouxe. O UPDATE de enriquecimento que roda logo depois continua sendo o
    unico que mexe em linha existente.
    """
    cur = conn.cursor()
    cur.execute("SELECT id, ibge_code, regexp_replace(coalesce(cnpj,''), '[^0-9]', '', 'g') "
                "FROM municipios WHERE active = true AND upper(coalesce(uf,'')) = 'MG'")
    nossos = {}
    for mid, ibge, cnpj in cur.fetchall():
        if ibge and len(cnpj) == 14:
            nossos[(ibge or "").strip()] = (mid, cnpj)
    if not nossos:
        log.info("nenhum municipio de MG com CNPJ — insercao do CKAN pulada")
        return 0

    # IBGE -> id_municipio do Estado
    ibge_por_id = {}
    for r in _linhas(_baixar(DM_MUNICIPIO_URL)):
        ibge_por_id[(r.get("id_municipio") or "").strip()] = (r.get("cd_municipio_ibge") or "").strip()
    convenentes = {(r.get("id_convenente") or "").strip():
                   ((r.get("nome") or "").strip(),
                    "".join(c for c in (r.get("nr_documento") or "") if c.isdigit()))
                   for r in _linhas(_baixar(DM_CONVENENTE_URL))}
    orgaos = {(r.get("id_orgao") or "").strip(): (r.get("nome") or "").strip()
              for r in _linhas(_baixar(DM_ORGAO_URL))}

    cur.execute("SELECT nr_siafi FROM convenios_estadual "
                "WHERE nr_siafi IS NOT NULL AND nr_siafi <> ''")
    ja_temos = {str(r[0]).strip() for r in cur.fetchall()}

    novos = 0
    for idc, dim in dim_by_id.items():
        siafi = (dim.get("siafi") or "").strip()
        if not siafi or siafi in ja_temos:
            continue
        fato = fatos.get(idc)
        if not fato:
            continue
        alvo = nossos.get(ibge_por_id.get(fato["id_municipio"], ""))
        if not alvo:
            continue
        mid, cnpj_mun = alvo
        nome_conv, doc_conv = convenentes.get(fato["id_convenente"], ("", ""))
        if doc_conv != cnpj_mun:
            continue                      # entidade sediada no municipio, nao o municipio
        pub = dim.get("dt_pub")
        try:
            cur.execute(_SQL_INSERT, {
                "municipio_id": mid,
                # mesma convencao do scraper para convenio celebrado: o SIAFI
                # tambem ocupa o nr_sigcon, que tem UNIQUE proprio na tabela.
                "nr_sigcon": siafi, "nr_siafi": siafi,
                "nr_plano": dim.get("plano") or None,
                "convenente": nome_conv or None,
                "orgao": orgaos.get(fato["id_orgao"]) or None,
                "objeto": dim.get("obj") or None,
                "objetivo": dim.get("objetivo") or None,
                "situacao": situacoes.get(idc),
                "tp_instrumento": dim.get("tp") or None,
                "concede": fato.get("concede"), "contra": fato.get("contra"),
                "total": fato.get("total"), "repassado": fato.get("repassado"),
                "dt_pub": pub, "vig_ini": dim.get("vig_ini"),
                "vig_fim": dim.get("vig_fim"),
                "vig_atual": dim.get("vig_atual") or dim.get("vig_fim"),
                "ano": pub.year if pub else None,
                "raw": json.dumps({**{k: v for k, v in dim.items() if k != "ver"},
                                   "_origem": "ckan_convenios_saida",
                                   "id_convenio": idc},
                                  ensure_ascii=False, default=str),
            })
            novos += cur.rowcount
        except Exception as e:
            log.warning(f"insert CKAN siafi={siafi}: {str(e)[:110]}")
            conn.rollback()
            continue
    conn.commit()
    log.info(f"CKAN: {novos} convenio(s) do municipio inseridos (nao existiam na tabela)")
    cur.close()
    return novos


def backfill() -> int:
    """Baixa o dataset, casa com os convenios SIGCON e preenche contrapartida +
    vigencia faltantes. Retorna nº de registros atualizados."""
    # Tenant sem municipio de MG nao tem convenio SIGCON para enriquecer —
    # baixar o dataset mineiro a cada 6 horas aqui era puro desperdicio.
    import os as _os
    import psycopg2 as _pg
    try:
        _c = _pg.connect(_os.environ["DATABASE_URL_SYNC"])
        _k = _c.cursor()
        _k.execute("SELECT count(*) FROM municipios "
                   "WHERE active = true AND upper(coalesce(uf, '')) = 'MG'")
        _n = _k.fetchone()[0]
        _c.close()
    except Exception:
        _n = -1  # na duvida, segue o fluxo de sempre
    if _n == 0:
        log.info("nenhum municipio de MG neste tenant — dataset SIGCON-MG nao baixado")
        return 0
    try:
        gz = _baixar_dataset()
    except Exception as e:
        log.error(f"falha ao baixar dataset CKAN: {str(e)[:120]}")
        return 0
    by_siafi, by_sigcon, by_id = _index_dataset(gz)
    # ft_convenio: valor EFETIVAMENTE REPASSADO por id_convenio (o "pagamento")
    # e, desde 30/08/2026, tambem as chaves de dimensao que a insercao precisa.
    try:
        _gz_ft = _baixar(FT_CONVENIO_URL)
        fatos = _fato_por_convenio(_gz_ft)
        rep_by_id = {k: v["repassado"] for k, v in fatos.items()}
        log.info(f"ft_convenio: {len(rep_by_id)} convenios com repasse")
    except Exception as e:
        fatos, rep_by_id = {}, {}
        log.warning(f"ft_convenio (repasse) falhou: {str(e)[:120]}")
    conn = psycopg2.connect(_sync_url()); cur = conn.cursor()

    # ⚠️ INSERCAO ANTES DO UPDATE, de proposito: o que entrar aqui ja e
    # enriquecido pelo laco de baixo na MESMA rodada, em vez de esperar 6 horas.
    # Toda a etapa e opcional — se qualquer download de dimensao falhar, o
    # backfill de enriquecimento (que e o comportamento antigo) segue inteiro.
    # ⚠️ DESLIGADA POR PADRAO, e isso e uma decisao, nao timidez. Medido contra
    # os arquivos reais antes do deploy: ligada, esta etapa insere 2.658
    # convenios no tenant freitas — R$ 508.526.428,66, dos quais
    # R$ 305.323.292,34 o Estado registra como JA REPASSADOS — em 41 dos 42
    # municipios. Isso quase DOBRA `convenios_estadual` (2.411 linhas hoje) e
    # muda de uma vez todo painel, KPI e relatorio dos 41.
    #
    # E ha um segundo motivo para o dono decidir: os convenios que entram vem
    # rotulados "CONVENIO CADASTRADO", o unico valor de situacao do Estado SEM
    # traducao calibrada (ver `_situacao_por_convenio`). O `_fed_status` do RM le
    # esse rotulo como PRE-EMPENHO — o que e conservador, mas subestima os que ja
    # tiveram repasse. Mudar essa classificacao e outra decisao, de outro PR.
    #
    # SIGCON_CKAN_INSERT=1 liga por tenant, sem deploy.
    inseridos = 0
    if fatos and os.getenv("SIGCON_CKAN_INSERT", "0").strip() in ("1", "true", "yes"):
        try:
            situacoes = _situacao_por_convenio(_baixar(FT_TIPOATENDIMENTO_URL),
                                               _baixar(DM_SITUACAO_URL))
            inseridos = _inserir_faltantes(conn, by_id, fatos, situacoes)
        except Exception as e:
            conn.rollback()
            log.warning(f"insercao CKAN falhou (o enriquecimento segue): {str(e)[:140]}")
    cur.execute("SELECT id, nr_siafi, nr_sigcon, nr_proposta, nr_plano_trabalho "
                "FROM convenios_estadual WHERE fonte ILIKE 'SIGCON%'")
    ours = cur.fetchall()
    matched = upd = rep_set = 0
    for cid, siafi, sigcon, prop, plano in ours:
        rec = None
        for k in (siafi, sigcon, prop, plano):
            k = (k or "").strip()
            if not k:
                continue
            if k in by_siafi:
                rec = by_siafi[k]; break
            if k in by_sigcon:
                rec = by_sigcon[k]; break
        if not rec:
            continue
        matched += 1
        # repasse real (vr_rep_concede_atual). None = desconhecido -> mantem; 0 = nao repassado
        repassado = rep_by_id.get(rec.get("id")) if rec.get("id") else None
        if repassado is not None:
            rep_set += 1
        cur.execute("""UPDATE convenios_estadual SET
            valor_contrapartida = COALESCE(valor_contrapartida, %s),
            dt_vigencia_inicial = COALESCE(dt_vigencia_inicial, %s),
            dt_vigencia_atual   = COALESCE(dt_vigencia_atual, %s),
            dt_vigencia_final   = COALESCE(dt_vigencia_final, %s),
            objeto = CASE WHEN length(trim(coalesce(objeto, ''))) <= 3
                          THEN COALESCE(NULLIF(%s, ''), objeto) ELSE objeto END,
            valor_repassado = CASE WHEN %s::numeric IS NOT NULL THEN %s::numeric ELSE valor_repassado END,
            updated_at = NOW()
          WHERE id = %s""",
          (rec["contra"], rec["vig_ini"], rec["vig_atual"] or rec["vig_fim"], rec["vig_fim"],
           rec.get("obj"), repassado, repassado, cid))
        if cur.rowcount:
            upd += 1
    conn.commit()
    log.info(f"SIGCON: {len(ours)} convenios | casados={matched} | atualizados={upd} | "
             f"repasse_preenchido={rep_set} | inseridos={inseridos}")
    try:
        cur.execute("INSERT INTO ingestion_log (source, status, records_inserted, finished_at) "
                    "VALUES ('sigcon_ckan_backfill','success',%s,NOW())", (upd + inseridos,))
        conn.commit()
    except Exception:
        conn.rollback()
    cur.close(); conn.close()
    return upd + inseridos


if __name__ == "__main__":
    backfill()
