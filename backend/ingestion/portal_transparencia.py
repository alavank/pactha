"""
Pipeline Portal da Transparencia (CGU) - convenios federais por municipio.

Fonte oficial: https://api.portaldatransparencia.gov.br
Autenticacao: header chave-api-dados (gratuita, 3M req/dia)
Cadastro: https://api.portaldatransparencia.gov.br/api-de-dados/cadastrar-email

Captura convenios + emendas dos orgaos federais que NAO estavam cobertos
pelo TransfereGov bulk (FNS, FNDE, MAPA, MTUR, ESPORTE, etc).
"""
import os
import sys
import time
import logging
import re
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from sqlalchemy import create_engine, text
from config import get_settings

logger = logging.getLogger("portal_transp")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

API_KEY = os.getenv("PORTAL_TRANSPARENCIA_KEY", "")
BASE = "https://api.portaldatransparencia.gov.br/api-de-dados"
PAGE_SIZE = 500


def _client():
    if not API_KEY:
        raise RuntimeError(
            "PORTAL_TRANSPARENCIA_KEY nao configurada. Cadastre em "
            "https://api.portaldatransparencia.gov.br/api-de-dados/cadastrar-email"
        )
    return httpx.Client(
        verify=False,
        timeout=30,
        headers={"chave-api-dados": API_KEY, "Accept": "application/json", "User-Agent": "PACTA/1.0"},
    )


def parse_dec(s):
    if s is None:
        return None
    if isinstance(s, (int, float, Decimal)):
        return float(s)
    s = str(s).strip()
    if not s:
        return None
    # "1.234,56" -> 1234.56
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def parse_date(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None


def fetch_convenios(client, ibge: str, ano_inicial=2015, ano_final=2026):
    """Pagina TODOS os convenios federais para o municipio.
    A API retorna 15 itens/pagina (PAGE_SIZE real e 15, nao 500).
    Continua paginando ate retornar vazio.
    """
    out = []
    for pag in range(1, 100):  # max 100 paginas = 1500 convenios
        try:
            r = client.get(
                f"{BASE}/convenios",
                params={
                    "dataInicial": f"01/01/{ano_inicial}",
                    "dataFinal": f"31/12/{ano_final}",
                    "codigoIBGE": ibge,
                    "pagina": pag,
                },
            )
        except Exception as e:
            logger.error(f"  Erro pag {pag}: {e}")
            break
        if r.status_code != 200:
            logger.warning(f"  HTTP {r.status_code} pag {pag}: {r.text[:200]}")
            break
        data = r.json()
        if not data:
            break  # so para quando vier vazio
        out.extend(data)
        time.sleep(0.4)  # rate limit
    return out


def fetch_emendas(client, ibge: str, ano_inicial=2020, ano_final=2026):
    """Lista emendas parlamentares federais para o municipio (via Portal CGU).

    Endpoint: /emendas?codigoMunicipioBeneficiario=...&ano=...
    Retorna nome do parlamentar autor + ID da emenda + valor empenhado.
    Permite linkar parlamentar ao convenio via raw_data['id_pt'] ou nrEmenda.
    """
    out = []
    for ano in range(ano_inicial, ano_final + 1):
        for pag in range(1, 100):
            try:
                r = client.get(
                    f"{BASE}/emendas",
                    params={
                        "codigoMunicipioBeneficiario": ibge,
                        "ano": ano,
                        "pagina": pag,
                    },
                )
            except Exception as e:
                logger.error(f"  emendas {ano} pag {pag}: {e}")
                break
            if r.status_code == 404:
                break
            if r.status_code != 200:
                logger.warning(f"  emendas HTTP {r.status_code} {ano}/{pag}: {r.text[:200]}")
                break
            data = r.json() or []
            if not data:
                break
            out.extend(data)
            time.sleep(0.4)
    return out


def link_emendas_to_convenios(conn, mun_id: int, emendas: list[dict], ibge: str | None = None):
    """Cria registros em `emendas` linkando convenios federais ao parlamentar.

    Estrategia de match (apenas emendas REAIS do municipio):
    1. id_proposta/id_pt presente no raw_data do convenio do municipio
    2. nr_convenio textual em algum campo da emenda
    3. (opcional) IBGE do beneficiario igual ao do municipio alvo

    Emendas que NAO matcham nenhum convenio do municipio sao DESCARTADAS.
    Sem isso, o endpoint /emendas da CGU retorna autores de emendas que
    beneficiaram outros municipios e contaminava o levantamento (ex.: 2250
    emendas com 590 parlamentares falsos em Piracema).
    """
    if not emendas:
        return 0

    # Mapa convenio: id_pt -> (id, nr_convenio)
    rows = conn.execute(text("""
        SELECT id, nr_convenio, COALESCE(raw_data->>'id_pt', '') as id_pt
        FROM convenios_federal WHERE municipio_id = :m
    """), {"m": mun_id}).fetchall()
    by_id_pt = {r[2]: (r[0], r[1]) for r in rows if r[2]}
    by_nr = {r[1]: r[0] for r in rows if r[1]}

    inserted = 0
    descartados = 0
    parl_cache: dict[str, int] = {}
    for em in emendas:
        # Achar convenio ANTES de criar parlamentar (evita poluir tabela)
        conv_id = None
        id_pt_raw = em.get("idConvenio")
        if not id_pt_raw and isinstance(em.get("convenio"), dict):
            id_pt_raw = em["convenio"].get("id")
        id_pt = str(id_pt_raw) if id_pt_raw else ""
        if id_pt and id_pt in by_id_pt:
            conv_id = by_id_pt[id_pt][0]
        elif em.get("numeroConvenio"):
            nr = str(em.get("numeroConvenio"))[:50]
            if nr in by_nr:
                conv_id = by_nr[nr]

        # Validacao adicional: se a emenda traz IBGE do beneficiario, exigir
        # que bata com o do municipio alvo. Sem isso, a CGU as vezes retorna
        # emendas de outros municipios (3164704 -> retorna 3151206 por engano).
        if ibge and not conv_id:
            ibge_em = None
            for k in ("codigoMunicipioBeneficiario", "ibgeBeneficiario"):
                if em.get(k):
                    ibge_em = str(em[k]); break
            if ibge_em and ibge_em != ibge:
                descartados += 1; continue

        # Sem conv_id E sem nome do parlamentar conhecido, descarta
        if not conv_id:
            descartados += 1
            continue

        nome_parl = (
            em.get("nomeAutor")
            or (em.get("autor", {}).get("nome") if isinstance(em.get("autor"), dict) else em.get("autor"))
            or em.get("nomeParlamentar")
        )
        if not nome_parl:
            descartados += 1
            continue
        nome_parl = str(nome_parl).strip().upper()[:300]
        nr_emenda = str(em.get("numeroEmenda") or em.get("codigoEmenda") or "")[:100] or None
        valor = parse_dec(em.get("valorEmpenhado") or em.get("valor") or em.get("valorPago")) or 0
        ano = em.get("ano")

        if nome_parl in parl_cache:
            parl_id = parl_cache[nome_parl]
        else:
            r = conn.execute(text("""
                SELECT id FROM parlamentares
                WHERE upper(nome) = :n LIMIT 1
            """), {"n": nome_parl}).first()
            if r:
                parl_id = r[0]
            else:
                ins = conn.execute(text("""
                    INSERT INTO parlamentares (nome, esfera, uf)
                    VALUES (:n, 'federal', 'MG') RETURNING id
                """), {"n": nome_parl})
                parl_id = ins.scalar()
            parl_cache[nome_parl] = parl_id

        conn.execute(text("""
            INSERT INTO emendas (
                nr_emenda, parlamentar_id, municipio_id, convenio_federal_id,
                valor, tipo, esfera, ano
            ) VALUES (:ne, :p, :m, :cf, :v, 'Indicacao Parlamentar', 'federal', :a)
        """), {
            "ne": nr_emenda, "p": parl_id, "m": mun_id, "cf": conv_id,
            "v": float(valor), "a": int(ano) if ano else None,
        })
        inserted += 1
    if descartados:
        logger.info(f"  ({descartados} emendas descartadas - nao matcham convenio do municipio)")
    return inserted


def upsert_convenio(conn, mun_id: int, c: dict):
    """Insere ou atualiza convenio_federal."""
    dim = c.get("dimConvenio") or {}
    nr = (dim.get("numero") or dim.get("codigo") or f"PT-{c.get('id')}")[:50]
    objeto = (dim.get("objeto") or "")[:1000]
    situacao = (c.get("situacao") or "")[:200]

    orgao_obj = c.get("orgao") or {}
    orgao_max = orgao_obj.get("orgaoMaximo") or {}
    orgao_concedente = (orgao_obj.get("sigla") or orgao_obj.get("nome") or "?")[:200]
    orgao_superior_nome = orgao_max.get("nome") or ""

    dt_inicio = parse_date(c.get("dataInicioVigencia"))
    dt_fim = parse_date(c.get("dataFinalVigencia"))

    valor_total = parse_dec(c.get("valorTotal") or dim.get("valor"))
    valor_repasse = parse_dec(c.get("valorRepasse") or c.get("valorLiberado"))

    # Tentar extrair ano da dt_inicio
    ano = dt_inicio.year if dt_inicio else None

    raw = {
        "fonte": "PortalTransparencia",
        "id_pt": c.get("id"),
        "convenente": (c.get("convenente") or {}).get("nome"),
        "orgao_superior": orgao_superior_nome,
        "valorContrapartida": c.get("valorContrapartida"),
        "valorRepasse": c.get("valorRepasse"),
    }
    import json as jsonlib

    conn.execute(text("""
        INSERT INTO convenios_federal (
            nr_convenio, municipio_id, orgao_concedente, objeto,
            situacao, valor_global, valor_repasse,
            dt_inicio, dt_fim, dt_fim_vigencia, ano,
            programa, fonte, raw_data, updated_at
        ) VALUES (
            :nr, :mun, :orgao, :obj, :sit, :vg, :vr,
            :di, :df, :df, :ano, :prog, :fonte, CAST(:raw AS jsonb), NOW()
        )
        ON CONFLICT (nr_convenio) DO UPDATE SET
            orgao_concedente = EXCLUDED.orgao_concedente,
            situacao = EXCLUDED.situacao,
            valor_global = COALESCE(EXCLUDED.valor_global, convenios_federal.valor_global),
            valor_repasse = COALESCE(EXCLUDED.valor_repasse, convenios_federal.valor_repasse),
            dt_inicio = COALESCE(EXCLUDED.dt_inicio, convenios_federal.dt_inicio),
            dt_fim = COALESCE(EXCLUDED.dt_fim, convenios_federal.dt_fim),
            dt_fim_vigencia = COALESCE(EXCLUDED.dt_fim_vigencia, convenios_federal.dt_fim_vigencia),
            raw_data = EXCLUDED.raw_data,
            updated_at = NOW()
    """), {
        "nr": nr, "mun": mun_id, "orgao": orgao_concedente, "obj": objeto,
        "sit": situacao, "vg": valor_total, "vr": valor_repasse,
        "di": dt_inicio, "df": dt_fim, "ano": ano,
        "prog": orgao_superior_nome[:200], "fonte": "PortalTransparencia",
        "raw": jsonlib.dumps(raw, ensure_ascii=False, default=str),
    })


def main():
    settings = get_settings()
    engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))

    with engine.connect() as conn:
        muns = conn.execute(text(
            "SELECT id, nome, ibge_code FROM municipios WHERE active=true AND ibge_code IS NOT NULL ORDER BY nome"
        )).fetchall()

    logger.info(f"=== Portal da Transparencia - {len(muns)} municipios ===")
    total_inseridos = 0

    with _client() as cli:
        for mid, nome, ibge in muns:
            logger.info(f"\n>>> {nome} (IBGE {ibge})")
            try:
                convs = fetch_convenios(cli, ibge, ano_inicial=2020, ano_final=2026)
                logger.info(f"  {len(convs)} convenios encontrados")
                if not convs:
                    continue

                # Resumo orgaos
                orgaos = {}
                for c in convs:
                    o = (c.get("orgao") or {}).get("sigla", "?")
                    orgaos[o] = orgaos.get(o, 0) + 1
                logger.info(f"  Orgaos: {orgaos}")

                # Filtrar SO os que realmente sao do municipio.
                # ATENCAO: a CGU TEM BUG DE DADOS. Para Piracema (IBGE 3151206)
                # ela retorna convenios cujo convenente e "MUNICIPIO DE PIRAPORA"
                # mesmo com municipioConvenente.codigoIBGE=3151206 no JSON.
                # Logo, NAO podemos confiar no IBGE da CGU - precisamos cruzar
                # com nome do convenente E objeto.
                #
                # Regra:
                # 1. Se convenente OU objeto menciona claramente outro municipio
                #    conhecido -> descarta.
                # 2. Se convenente OU objeto menciona o nome do municipio alvo -> aceita.
                # 3. Fallback (sem nome no convenente): aceita se IBGE bate
                #    e convenente nao for "Municipio de X" diferente.
                nome_norm = (nome or "").upper().strip()
                # Nomes de outros municipios MG conhecidos por causar colisao
                # com IBGE proximo (lexicografico). Sao apenas pistas para descarte.
                CONFLITOS = ["PIRAPORA", "PIRAPETINGA", "PIRAJUBA", "PIRANGA",
                             "PIRANGUCU", "PIRANGUINHO", "PIRAUBA", "PIRAJUI"]
                # Remover o proprio nome alvo dos conflitos
                CONFLITOS = [c for c in CONFLITOS if c != nome_norm]

                def is_valid(c):
                    conv_nome = ((c.get("convenente") or {}).get("nome") or "").upper()
                    objeto = ((c.get("dimConvenio") or {}).get("objeto") or "").upper()
                    haystack = f"{conv_nome} {objeto}"

                    # 1. Aceita explicitamente se mencionar o municipio alvo
                    if nome_norm and nome_norm in haystack:
                        return True

                    # 2. Descarta se mencionar outro municipio MG conhecido
                    for outro in CONFLITOS:
                        if outro in haystack:
                            return False

                    # 3. Sem pista: aceita se IBGE bate E convenente nao for
                    # "MUNICIPIO DE X" sem mencionar nome alvo (caso "Atletico X"
                    # ou "Associacao Y" nao deveria entrar sem evidencia).
                    mc = c.get("municipioConvenente") or {}
                    if mc.get("codigoIBGE") == ibge:
                        if conv_nome.startswith("MUNICIPIO DE "):
                            # Convenente Municipio diferente - se nao mencionou alvo,
                            # melhor descartar para evitar contaminacao.
                            return False
                        return True
                    return False

                convs_validos = [c for c in convs if is_valid(c)]
                if len(convs_validos) != len(convs):
                    logger.info(
                        f"  {len(convs) - len(convs_validos)} convenios descartados "
                        f"(municipio diferente - bug CGU cross-IBGE)"
                    )

                with engine.begin() as conn:
                    for c in convs_validos:
                        try:
                            upsert_convenio(conn, mid, c)
                            total_inseridos += 1
                        except Exception as e:
                            logger.error(f"  Falha upsert {c.get('id')}: {e}")

                # Coletar emendas e linkar ao parlamentar
                try:
                    emendas = fetch_emendas(cli, ibge, ano_inicial=2020, ano_final=2026)
                    if emendas:
                        with engine.begin() as conn:
                            # Limpar emendas federais previas DESTE municipio antes de reinserir
                            conn.execute(text(
                                "DELETE FROM emendas WHERE municipio_id=:m AND esfera='federal' "
                                "AND tipo='Indicacao Parlamentar'"
                            ), {"m": mid})
                            n = link_emendas_to_convenios(conn, mid, emendas, ibge=ibge)
                            logger.info(f"  + {n} emendas parlamentares linkadas")
                except Exception as e:
                    logger.error(f"  Falha emendas {nome}: {e}")
            except Exception as e:
                logger.error(f"  ERRO {nome}: {e}")
            time.sleep(1)

    # Log final
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO ingestion_log (source, status, records_inserted, finished_at)
            VALUES ('portal_transparencia', 'success', :n, NOW())
        """), {"n": total_inseridos})

    logger.info(f"\n=== Total inseridos/atualizados: {total_inseridos} ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback; traceback.print_exc()
        sys.exit(1)
