"""
Ingestao SIGCON-MG completa via CKAN resources + join das dimensoes.
Popula convenios_estadual para todos os 5 municipios piloto.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx, gzip, io, pandas as pd, json, unicodedata
from sqlalchemy import create_engine, text
from config import get_settings
from ingestion.base import parse_date_br, parse_decimal_br, clean_string

settings = get_settings()
engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))

BASE_DL = "https://dados.mg.gov.br/dataset/52fcf7e5-d9a6-4b17-a491-12a5a978aecd/resource"
RESOURCES = {
    "convenio": ("23de2c3f-cbf6-494a-8b32-4c9c151fb999", "dm_convenio.csv.gz"),
    "municipio": ("9cd4ddc8-7efd-45dc-b572-9ea6840c9815", "dm_municipio.csv.gz"),
    "conv_saida": ("d8b48c2b-c2ec-451a-99f0-0421987ceeba", "ft_convenio.csv.gz"),
    "conv_atend": ("b8c80cc1-f5fe-4ff3-b3b9-c9071bfd1afb", "ft_convenio_tipoatendimento.csv.gz"),
    "conv_meta":  ("882446db-56b0-484b-a44f-225c7c0f0e52", "ft_convenio_metaetapa.csv.gz"),
    "conv_alt":   ("e8576d81-221b-4337-bb83-dceae2a2b5cb", "fl_convenio_alteracao.csv.gz"),
    "conv_interv": ("eb926c4c-8065-44d7-a802-cb3b1b1cb280", "fl_convenio_interveniente.csv.gz"),
    "orgao": ("cf96b7cc-b534-4c4b-8338-dce4c9ed5517", "dm_orgao_concedente.csv.gz"),
    "situacao": ("1ddced7a-dfcf-4ca2-8c3c-23439b944bb2", "dm_situacao_convenio.csv.gz"),
    "convenente": ("3b9d9df2-1a50-451d-bc7e-3a0b82fcf821", "dm_convenente.csv.gz"),
}

def _load_target_names():
    """Carrega nomes dos municipios ativos do DB (normalizados)."""
    eng = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT nome FROM municipios WHERE active=true AND uf='MG'"
        )).fetchall()
    out = []
    for (nome,) in rows:
        s = str(nome).strip().upper()
        s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
        out.append(s)
    return out


TARGET_NAMES = _load_target_names()
print(f"SIGCON municipios alvo: {TARGET_NAMES}")


def norm(s):
    if s is None:
        return ""
    s = str(s).strip().upper()
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def dl(key):
    rid, name = RESOURCES[key]
    url = f"{BASE_DL}/{rid}/download/{name}"
    print(f"  Downloading {name}...")
    with httpx.Client(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
        r = client.get(url, follow_redirects=True)
        r.raise_for_status()
    return pd.read_csv(io.BytesIO(gzip.decompress(r.content)), sep=";", encoding="utf-8", dtype=str, low_memory=False)


def main():
    print("=== Ingestao SIGCON-MG (full pipeline) ===")

    df_conv = dl("convenio")
    df_mun = dl("municipio")
    df_fact = dl("conv_saida")
    df_orgao = dl("orgao")
    df_sit = dl("situacao")
    # Tabelas extras: usadas para descobrir mais id_convenios alem do limite 5k de cada fato
    try:
        df_conve = dl("convenente")
        df_atend = dl("conv_atend")
    except Exception as e:
        print(f"  Aviso: nao baixou convenente/atendimento: {e}")
        df_conve = pd.DataFrame(columns=["id_convenente","nome"])
        df_atend = pd.DataFrame(columns=["id_convenio","id_municipio","id_convenente"])

    print(f"  Convenios: {len(df_conv)}, Municipios: {len(df_mun)}, Facts: {len(df_fact)}")

    # Find target municipalities (match by normalized name)
    df_mun["_norm"] = df_mun["nome"].apply(norm)
    target_muns = df_mun[df_mun["_norm"].isin(TARGET_NAMES)]
    print(f"  Target municipios in SIGCON: {len(target_muns)}")

    if len(target_muns) == 0:
        print("  ERRO: nenhum municipio encontrado")
        return

    # Map SIGCON id_municipio -> our DB municipio_id
    mun_db_map = {}
    with engine.connect() as conn:
        for _, row in target_muns.iterrows():
            nome_norm = row["_norm"]
            result = conn.execute(text("""
                SELECT id FROM municipios
                WHERE UPPER(nome) = :n OR :n = ANY(ARRAY[UPPER(nome)])
            """), {"n": nome_norm})
            # Fallback: normalize DB name
            db_rows = conn.execute(text("SELECT id, nome FROM municipios")).fetchall()
            for dbr in db_rows:
                if norm(dbr[1]) == nome_norm:
                    mun_db_map[str(row["id_municipio"])] = dbr[0]
                    break

    print(f"  Mapeamento DB: {mun_db_map}")

    # Filter fact table by target municipalities
    target_mun_ids = set(mun_db_map.keys())
    filt_facts = df_fact[df_fact["id_municipio"].astype(str).isin(target_mun_ids)]
    print(f"  Fact records (Convenio Saida): {len(filt_facts)}")

    # === EXTENSAO: cruzar Convenente + tabelas fato adicionais ===
    # Limite CKAN bulk: 5000 linhas por fato. Pra ampliar cobertura, descobrir
    # id_convenios via outras tabelas (Tipo Atendimento) + filtrar Convenente
    # por nome dos 6 municipios alvo (pega ONGs, hospitais, APAEs alem das prefeituras).
    extra_conv_ids = set()
    extra_facts_by_conv_id = {}  # id_convenio -> linha fato escolhida (com valores)
    prefeituras = pd.DataFrame(columns=["id_convenente", "_nome_norm"])
    if len(df_conve) > 0:
        df_conve = df_conve.copy()
        df_conve["_nome_norm"] = df_conve["nome"].fillna("").apply(norm)
        # Pega convenentes cujos nomes contem o nome do municipio alvo
        # Inclui prefeituras (MUNICIPIO DE X) + ONGs/APAEs/hospitais locais
        mask = df_conve["_nome_norm"].apply(
            lambda n: any(tn in n for tn in TARGET_NAMES)
        )
        prefeituras = df_conve[mask]
        target_convenente_ids = set(prefeituras["id_convenente"].astype(str))
        print(f"  Convenentes alvo (todas entidades dos 6 muns): {len(target_convenente_ids)}")

        # Cruza com fato Convenio Tipo Atendimento (5k extra)
        if len(df_atend) > 0 and "id_convenente" in df_atend.columns:
            extra = df_atend[df_atend["id_convenente"].astype(str).isin(target_convenente_ids)]
            extra_conv_ids |= set(extra["id_convenio"].astype(str))
            for _, row in extra.iterrows():
                cid = str(row["id_convenio"])
                if cid not in extra_facts_by_conv_id:
                    extra_facts_by_conv_id[cid] = row
            print(f"  Extras via Convenio Tipo Atendimento: {len(extra)} linhas -> {len(extra_facts_by_conv_id)} novos id_convenios")

        # Cruza com fato Convenio Saida tambem por id_convenente (alem de id_municipio)
        if "id_convenente" in df_fact.columns:
            extra2 = df_fact[df_fact["id_convenente"].astype(str).isin(target_convenente_ids)]
            extra_conv_ids |= set(extra2["id_convenio"].astype(str))
            for _, row in extra2.iterrows():
                cid = str(row["id_convenio"])
                if cid not in extra_facts_by_conv_id:
                    extra_facts_by_conv_id[cid] = row
            print(f"  Extras via Convenio Saida + convenente: total acumulado {len(extra_facts_by_conv_id)} id_convenios")

    # Get convenio details (uniao do que veio direto + descoberto via convenente)
    target_conv_ids = set(filt_facts["id_convenio"].astype(str).tolist()) | extra_conv_ids
    filt_convs = df_conv[df_conv["id_convenio"].astype(str).isin(target_conv_ids)]
    print(f"  Total convenios alvo (apos cruzamento): {len(target_conv_ids)}")
    print(f"  Convenios encontrados em dim Convenio: {len(filt_convs)}")

    # Pre-monta mapa id_convenio -> id_convenente (para resolver municipio_db quando
    # vier somente via convenente)
    conve_to_mun = {}
    if len(prefeituras) > 0:
        # Pra cada convenente, descobrir o municipio alvo do nome
        for _, p in prefeituras.iterrows():
            nome = p["_nome_norm"]
            for tn in TARGET_NAMES:
                if tn in nome:
                    # Resolve TARGET name -> mun_db_id via mun_db_map (mas por nome, nao id_municipio sigcon)
                    # Lookup direto no DB
                    with engine.connect() as cn:
                        rid = cn.execute(text("SELECT id FROM municipios WHERE UPPER(translate(nome,'áéíóúàâêôãõçÁÉÍÓÚÀÂÊÔÃÕÇ','AEIOUAAEOAOCAEIOUAAEOAOC')) = :n"), {"n": tn}).first()
                        if rid:
                            conve_to_mun[str(p["id_convenente"])] = rid[0]
                    break

    # Index facts por id_convenio pra acesso O(1) no loop
    filt_facts_idx = {str(r["id_convenio"]): r for _, r in filt_facts.iterrows()}
    convs_idx = {str(r["id_convenio"]): r for _, r in filt_convs.iterrows()}

    inserted = 0
    updated = 0
    with engine.connect() as conn:
        # NAO faz DELETE antes - SIGCON-MG bulk e capped em 5000 facts (paginacao CKAN).
        # DELETE+INSERT perderia historico real se nova execucao trouxesse menos dados.
        # Usa UPSERT em nr_sigcon (UNIQUE INDEX existe).

        for conv_id in target_conv_ids:
            crow = convs_idx.get(conv_id)
            if crow is None:
                continue
            # Fact: prefer Convenio Saida (tem mais valores), fallback para extras.
            # NAO usar `or` em pd.Series (ambiguous truth value) - explicit None check.
            fact = filt_facts_idx.get(conv_id)
            if fact is None:
                fact = extra_facts_by_conv_id.get(conv_id)
            if fact is None:
                # Sem nenhum fato - usa apenas dim
                fact = pd.Series(dtype=object)

            # Resolve municipio_db_id: 1) via id_municipio do fato, 2) via convenente
            mun_db_id = None
            mun_sigcon_id = str(fact.get("id_municipio") or "")
            if mun_sigcon_id and mun_sigcon_id != "nan":
                mun_db_id = mun_db_map.get(mun_sigcon_id)
            if not mun_db_id:
                conve_id = str(fact.get("id_convenente") or "")
                if conve_id:
                    mun_db_id = conve_to_mun.get(conve_id)
            if not mun_db_id:
                continue

            nr_sigcon = clean_string(crow.get("nr_sigcon")) or f"SIGCON-{conv_id}"

            orgao_name = None
            orgao_id = str(fact.get("id_orgao", ""))
            if orgao_id:
                om = df_orgao[df_orgao["id_orgao"].astype(str) == orgao_id]
                if len(om) > 0:
                    orgao_name = clean_string(om.iloc[0].get("nome"))

            dt_pub = parse_date_br(crow.get("dt_publicacao"))
            dt_ini = parse_date_br(crow.get("dt_vigencia_inicial"))
            dt_fim = parse_date_br(crow.get("dt_vigencia_final"))
            dt_atual = parse_date_br(crow.get("dt_vigencia_atual"))

            try:
                # Extrair Numero do Plano de Trabalho (= nr_plano_sigcon no CSV)
                # e Data Assinatura (proxy = dt_publicacao no SIGCON-MG)
                nr_plano_trab = clean_string(crow.get("nr_plano_sigcon"))
                res = conn.execute(text("""
                    INSERT INTO convenios_estadual (
                        nr_sigcon, nr_siafi, municipio_id, orgao_concedente,
                        objeto, objetivo, tp_instrumento,
                        valor_concedente, valor_emenda_parlamentar, valor_contrapartida, valor_total, valor_repassado,
                        dt_publicacao, dt_vigencia_inicial, dt_vigencia_final, dt_vigencia_atual,
                        ano, situacao, raw_data,
                        nr_plano_trabalho, dt_assinatura
                    ) VALUES (
                        :nr, :siafi, :mun, :orgao, :obj, :objetivo, :tp,
                        :vc, :ve, :vcp, :vt, :vrep,
                        :dp, :di, :df, :da,
                        :ano, :sit, :raw,
                        :npt, :dass
                    )
                    ON CONFLICT (nr_sigcon) DO UPDATE SET
                        valor_concedente = EXCLUDED.valor_concedente,
                        valor_emenda_parlamentar = EXCLUDED.valor_emenda_parlamentar,
                        valor_contrapartida = EXCLUDED.valor_contrapartida,
                        valor_total = EXCLUDED.valor_total,
                        valor_repassado = EXCLUDED.valor_repassado,
                        dt_vigencia_atual = EXCLUDED.dt_vigencia_atual,
                        situacao = EXCLUDED.situacao,
                        raw_data = EXCLUDED.raw_data,
                        nr_plano_trabalho = COALESCE(EXCLUDED.nr_plano_trabalho, convenios_estadual.nr_plano_trabalho),
                        dt_assinatura = COALESCE(EXCLUDED.dt_assinatura, convenios_estadual.dt_assinatura),
                        updated_at = NOW()
                    RETURNING (xmax = 0) AS inserted
                """), {
                    "nr": nr_sigcon,
                    "siafi": clean_string(crow.get("nr_siafi")),
                    "mun": mun_db_id,
                    "orgao": orgao_name,
                    "obj": clean_string(crow.get("nome")),
                    "objetivo": clean_string(crow.get("objetivo")),
                    "tp": clean_string(crow.get("tp_instrumento")),
                    "vc": parse_decimal_br(fact.get("vr_concede_atual")),
                    "ve": parse_decimal_br(fact.get("vr_emen_parl_atual")),
                    "vcp": parse_decimal_br(fact.get("vr_contra_atual")),
                    "vt": parse_decimal_br(fact.get("vr_total_atual")),
                    "vrep": parse_decimal_br(fact.get("vr_rep_concede_atual")),
                    "dp": dt_pub, "di": dt_ini, "df": dt_fim, "da": dt_atual,
                    # Ano = dt_publicacao (referencia real); dt_vigencia pode ser
                    # +30 anos em Transferencia Especial MG (vigencia indeterminada)
                    "ano": (dt_pub.year if dt_pub else (dt_ini.year if dt_ini else None)),
                    "sit": "Em vigor" if dt_atual else None,
                    "raw": json.dumps(
                        {k: clean_string(v) for k, v in {**crow.to_dict(), **fact.to_dict()}.items() if clean_string(v)},
                        ensure_ascii=False, default=str,
                    ),
                    "npt": nr_plano_trab,
                    "dass": dt_pub,
                })
                row = res.fetchone()
                if row and row[0]:
                    inserted += 1
                else:
                    updated += 1
            except Exception as e:
                if "duplicate" not in str(e).lower():
                    print(f"  Error: {e}")
                continue

        conn.execute(text("""
            INSERT INTO ingestion_log (source, status, records_processed, records_inserted, finished_at)
            VALUES ('sigcon_full', 'success', :n, :n, NOW())
        """), {"n": inserted})
        conn.commit()

    print(f"\n  Total inseridos: {inserted}")

    # Re-generate prestacao_contas for all active estadual convenios
    print("\n  Regenerando prestacoes...")
    from datetime import date, timedelta
    SIGCON_DOCS = [
        "Plano de trabalho", "Cronograma fisico-financeiro",
        "Comprovantes de pagamento", "Notas fiscais",
        "Relatorio de execucao", "Termo de recebimento",
    ]
    prestacao_count = 0
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, municipio_id, situacao, dt_vigencia_atual, dt_vigencia_final
            FROM convenios_estadual
        """)).fetchall()
        for row in rows:
            # Infer stage from situacao
            sit = (row[2] or "").lower()
            etapa_nr, etapa_nome = 7, "Execucao"
            if "concluido" in sit or "encerr" in sit:
                etapa_nr, etapa_nome = 16, "Encerramento"
            elif "prestacao" in sit:
                etapa_nr, etapa_nome = 12, "Prest. Contas - Analise"
            elif "analise" in sit:
                etapa_nr, etapa_nome = 3, "Analise Tecnica"
            elif "celebrado" in sit:
                etapa_nr, etapa_nome = 6, "Celebracao"

            # Override if vigencia passed
            dt_vig = row[3] or row[4]
            if dt_vig and dt_vig < date.today() and etapa_nr < 12:
                etapa_nr, etapa_nome = 12, "Prest. Contas - Analise"

            status = "em_andamento"
            if etapa_nr >= 14:
                status = "concluido"
            elif etapa_nr <= 4:
                status = "pendente"

            result = conn.execute(text("""
                INSERT INTO prestacao_contas (convenio_estadual_id, municipio_id, etapa_atual, etapa_nome, status)
                VALUES (:c, :m, :en, :enm, :s)
                RETURNING id
            """), {"c": row[0], "m": row[1], "en": etapa_nr, "enm": etapa_nome, "s": status})
            pid = result.scalar()

            for doc in SIGCON_DOCS:
                enviado = etapa_nr >= 11
                conn.execute(text("""
                    INSERT INTO prestacao_documentos (prestacao_id, documento_nome, enviado, dt_envio)
                    VALUES (:p, :d, :e, :dt)
                """), {"p": pid, "d": doc, "e": enviado,
                       "dt": date.today() - timedelta(days=30) if enviado else None})
            prestacao_count += 1

        conn.commit()
    print(f"  Prestacoes regeneradas: {prestacao_count}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO ingestion_log (source, status, error_message, finished_at)
                VALUES ('sigcon_full', 'failed', :e, NOW())
            """), {"e": str(e)[:500]})
            conn.commit()
        print(f"ERROR: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
