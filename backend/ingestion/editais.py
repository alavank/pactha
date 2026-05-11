"""
Ingestao de editais reais.
Fonte: PNCP - Portal Nacional de Contratacoes Publicas
  API publica: https://pncp.gov.br/api/consulta/v1/

Busca editais abertos (avisos de contratacao) relevantes para MG
nas areas: saude, educacao, obras, cultura, esporte.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from sqlalchemy import create_engine, text
from datetime import datetime, date, timedelta
from config import get_settings

settings = get_settings()
engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))

PNCP_BASE = "https://pncp.gov.br/api/consulta/v1"


def classify_area(objeto):
    obj = (objeto or "").lower()
    if any(k in obj for k in ["saude", "ubs", "hospital", "medic", "sus", "ambulancia", "samu"]):
        return "Saude"
    if any(k in obj for k in ["escola", "educa", "creche", "escolar", "merenda", "transporte escolar"]):
        return "Educacao"
    if any(k in obj for k in ["quadra", "ginasio", "esporte", "esportiv", "arena", "campo de futebol"]):
        return "Esporte"
    if any(k in obj for k in ["cultura", "biblioteca", "teatro", "museu", "centro cultural"]):
        return "Cultura"
    if any(k in obj for k in ["pavimenta", "asfalto", "obra", "drenagem", "calcamento", "recapeamento", "recape"]):
        return "Obras/Infraestrutura"
    if any(k in obj for k in ["social", "assistencia", "cras", "creas", "suas"]):
        return "Assistencia Social"
    if any(k in obj for k in ["agric", "trator", "rural", "pecuari"]):
        return "Agricultura"
    if any(k in obj for k in ["turismo", "evento"]):
        return "Turismo"
    return "Outros"


# Palavras-chave por area (planilha "5_Editais_Radar")
# Usado para filtrar editais relevantes para os clientes Freitas
RADAR_KEYWORDS = {
    "Cultura": ["teatro", "biblioteca", "centro cultural", "patrimonio cultural"],
    "Esporte": ["quadra", "ginasio", "arena", "campo de futebol", "academia ao ar livre"],
    "Obras": ["asfalto", "pavimentacao", "drenagem", "ponte", "estrada vicinal"],
    "Saude": ["UBS", "hospital", "ambulancia", "samu", "academia da saude"],
    "Educacao": ["escola", "creche", "reforma de escola", "transporte escolar"],
    "Assistencia Social": ["CRAS", "CREAS", "centro de convivencia"],
}


def is_radar_relevant(titulo: str) -> tuple[bool, str | None]:
    """Retorna (relevante, area_chave) para os editais do radar Freitas."""
    if not titulo:
        return False, None
    t = titulo.lower()
    for area, kws in RADAR_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in t:
                return True, area
    return False, None


# Orgaos federais e estaduais MG monitorados pela Freitas (planilha)
ORGAOS_RADAR = {
    "federal": [
        "Ministerio da Cultura", "Ministerio do Esporte", "Ministerio das Cidades",
        "Ministerio da Saude", "FNDE",
    ],
    "estadual": [
        "SEGOV", "SEDESE", "SEINFRA", "SECULT", "SEE",
    ],
}


def is_orgao_radar(orgao: str) -> bool:
    """Verifica se o orgao concedente esta na lista do radar Freitas."""
    if not orgao:
        return False
    o = orgao.upper()
    keywords = [
        "CULTURA", "ESPORTE", "CIDADES", "SAUDE", "FNDE",
        "SEGOV", "SEDESE", "SEINFRA", "SECULT", "SEE",
        "EDUCACAO", "INFRAESTRUTURA",
    ]
    return any(k in o for k in keywords)


def fetch_editais_pncp():
    """Busca avisos de contratacao no PNCP recentes, filtrando por MG e municipios piloto."""
    print("\n=== Ingestao de Editais reais (PNCP) ===")

    hoje = date.today()
    data_ini = (hoje - timedelta(days=30)).strftime("%Y%m%d")
    data_fim = (hoje + timedelta(days=180)).strftime("%Y%m%d")

    editais = []

    # PNCP consulta: avisos de contratacao com proposta em aberto
    # Endpoint: /contratacoes/proposta
    url = f"{PNCP_BASE}/contratacoes/proposta"

    # Modalidades: 6=Pregao eletronico, 8=Dispensa, 4=Concorrencia, 5=Tomada de Precos, 1=Leilao
    modalidades = [6, 8, 4, 5]  # pregao, dispensa, concorrencia, tomada

    for modalidade in modalidades:
        pagina = 1
        while True:
            params = {
                "dataFinal": data_fim,
                "codigoModalidadeContratacao": modalidade,
                "uf": "MG",
                "pagina": pagina,
                "tamanhoPagina": 50,
            }
            try:
                print(f"  Modalidade {modalidade} pagina {pagina}...")
                with httpx.Client(timeout=60.0) as client:
                    r = client.get(url, params=params, follow_redirects=True)
                if r.status_code != 200:
                    print(f"    HTTP {r.status_code}")
                    break
                data = r.json()
                items = data.get("data", []) or []
                total_pag = data.get("totalPaginas", 1) or 1
                print(f"    {len(items)} itens (pagina {pagina}/{total_pag})")
                if not items:
                    break
                editais.extend(items)
                if pagina >= total_pag or pagina >= 5:  # max 5 paginas por modalidade
                    break
                pagina += 1
            except Exception as e:
                print(f"    Erro: {e}")
                break

    print(f"\n  Total itens PNCP: {len(editais)}")
    return editais


def ingest_editais():
    editais = fetch_editais_pncp()
    if not editais:
        print("  Nenhum edital encontrado")
        return 0

    inserted = 0
    with engine.connect() as conn:
        # Clear and re-insert
        conn.execute(text("DELETE FROM edital_acompanhamento"))
        conn.execute(text("DELETE FROM editais"))

        for e in editais:
            try:
                titulo = (e.get("objetoCompra") or e.get("objeto") or "")[:900]
                if not titulo:
                    continue

                orgao = e.get("orgaoEntidade", {}).get("razaoSocial") if isinstance(e.get("orgaoEntidade"), dict) else None
                if not orgao:
                    orgao = e.get("nomeRazaoSocialFornecedor") or e.get("unidadeOrgao", {}).get("nomeUnidade") if isinstance(e.get("unidadeOrgao"), dict) else None

                valor = e.get("valorTotalEstimado") or e.get("valorTotalHomologado") or 0
                try:
                    valor = float(valor) if valor else 0
                except Exception:
                    valor = 0

                dt_pub = e.get("dataPublicacaoPncp") or e.get("dataAberturaProposta")
                dt_end = e.get("dataEncerramentoProposta") or e.get("dataFinalProposta")

                def parse_pncp_date(s):
                    if not s:
                        return None
                    try:
                        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
                    except Exception:
                        try:
                            return datetime.strptime(s[:10], "%Y-%m-%d").date()
                        except Exception:
                            return None

                dt_pub_d = parse_pncp_date(dt_pub)
                dt_end_d = parse_pncp_date(dt_end)

                area = classify_area(titulo)
                url_pncp = f"https://pncp.gov.br/app/editais/{e.get('numeroControlePNCP', '')}" if e.get("numeroControlePNCP") else None

                # Flag radar: edital de interesse Freitas (palavra-chave + orgao)
                radar_match, radar_area = is_radar_relevant(titulo)
                no_radar = radar_match or is_orgao_radar(orgao)

                # Esfera baseada no orgao
                esfera_v = "estadual" if any(s in (orgao or "").upper()
                                              for s in ("SEGOV", "SEDESE", "SEINFRA", "SECULT",
                                                        "SEE", "GOVERNO DE MINAS", "ESTADO DE MINAS")) else "federal"

                conn.execute(text("""
                    INSERT INTO editais (
                        titulo, orgao, area, esfera, url,
                        dt_publicacao, dt_encerramento, valor_total, resumo, status
                    ) VALUES (:t, :o, :a, :esf, :u, :dp, :de, :v, :r, 'aberto')
                """), {
                    "t": titulo, "o": orgao, "a": radar_area or area,
                    "esf": esfera_v, "u": url_pncp,
                    "dp": dt_pub_d, "de": dt_end_d, "v": valor,
                    "r": ("[RADAR FREITAS] " if no_radar else "") +
                         f"Modalidade: {e.get('modalidadeNome', '-')}",
                })
                inserted += 1
            except Exception as ex:
                print(f"  Erro inserindo: {ex}")
                continue

        conn.execute(text("""
            INSERT INTO ingestion_log (source, status, records_inserted, finished_at)
            VALUES ('editais_pncp', 'success', :n, NOW())
        """), {"n": inserted})
        conn.commit()

    print(f"\n  Editais inseridos: {inserted}")
    return inserted


if __name__ == "__main__":
    try:
        ingest_editais()
    except Exception as e:
        import traceback; traceback.print_exc()
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO ingestion_log (source, status, error_message, finished_at)
                VALUES ('editais_pncp', 'failed', :e, NOW())
            """), {"e": str(e)[:500]})
            conn.commit()
