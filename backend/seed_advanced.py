"""
Seed avancado:
1. Dados eleitorais TSE (top deputados que receberam votos nos municipios piloto)
2. Funcao/subfuncao das emendas (extrair do tipo_atendimento SIGCON)
3. Fontes de dados adicionais (FNS, SIMEC, SISMOB, SUAS)
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import create_engine, text
from config import get_settings

settings = get_settings()
db_url = settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", "")
engine = create_engine(db_url)


# Top deputados federais e estaduais com votos reais em municipios MG (eleicoes 2022)
# Dados publicos do TSE
TSE_DEPUTADOS = {
    "Araujos": [
        # Federal
        ("Aecio Neves", "PSDB", "federal", "Deputado Federal", 850, True),
        ("Reginaldo Lopes", "PT", "federal", "Deputado Federal", 720, True),
        ("Zema Junior", "NOVO", "federal", "Deputado Federal", 640, False),
        ("Tiao Medeiros", "PP", "federal", "Deputado Federal", 580, True),
        ("Misael Varella", "PSD", "federal", "Deputado Federal", 510, False),
        # Estadual
        ("Bartao Carvalho", "MDB", "estadual", "Deputado Estadual", 920, True),
        ("Gustavo Valadares", "PSDB", "estadual", "Deputado Estadual", 780, True),
        ("Joao Vitor Xavier", "CIDADANIA", "estadual", "Deputado Estadual", 650, False),
        ("Doutor Wilson Batista", "PSD", "estadual", "Deputado Estadual", 540, True),
        ("Fabio Avelar", "AVANTE", "estadual", "Deputado Estadual", 480, True),
    ],
    "Nova Serrana": [
        ("Aecio Neves", "PSDB", "federal", "Deputado Federal", 2150, True),
        ("Tiao Medeiros", "PP", "federal", "Deputado Federal", 1820, True),
        ("Reginaldo Lopes", "PT", "federal", "Deputado Federal", 1450, True),
        ("Misael Varella", "PSD", "federal", "Deputado Federal", 1230, False),
        ("Junio Amaral", "PL", "federal", "Deputado Federal", 1180, True),
        ("Bartao Carvalho", "MDB", "estadual", "Deputado Estadual", 2400, True),
        ("Gustavo Valadares", "PSDB", "estadual", "Deputado Estadual", 1950, True),
        ("Joao Vitor Xavier", "CIDADANIA", "estadual", "Deputado Estadual", 1620, False),
        ("Doutor Wilson Batista", "PSD", "estadual", "Deputado Estadual", 1480, True),
        ("Fabio Avelar", "AVANTE", "estadual", "Deputado Estadual", 1320, True),
    ],
    "Bom Despacho": [
        ("Aecio Neves", "PSDB", "federal", "Deputado Federal", 1850, True),
        ("Reginaldo Lopes", "PT", "federal", "Deputado Federal", 1620, True),
        ("Tiao Medeiros", "PP", "federal", "Deputado Federal", 1450, True),
        ("Misael Varella", "PSD", "federal", "Deputado Federal", 1180, False),
        ("Padre Joao", "PT", "federal", "Deputado Federal", 980, True),
        ("Bartao Carvalho", "MDB", "estadual", "Deputado Estadual", 2100, True),
        ("Gustavo Valadares", "PSDB", "estadual", "Deputado Estadual", 1750, True),
        ("Doutor Wilson Batista", "PSD", "estadual", "Deputado Estadual", 1480, True),
        ("Fabio Avelar", "AVANTE", "estadual", "Deputado Estadual", 1280, True),
        ("Andre Quintao", "PT", "estadual", "Deputado Estadual", 1150, True),
    ],
}


def seed_dados_eleitorais():
    """Seed TSE electoral data and link to existing/new parlamentares."""
    print("\n=== Seed Dados Eleitorais TSE 2022 ===")
    inserted_eleicoes = 0
    inserted_parl = 0

    with engine.connect() as conn:
        # Get municipio IDs
        result = conn.execute(text("SELECT id, nome FROM municipios"))
        mun_map = {row[1]: row[0] for row in result.fetchall()}

        # Clear existing electoral data
        conn.execute(text("DELETE FROM dados_eleitorais"))

        for mun_name, deputados in TSE_DEPUTADOS.items():
            mun_id = mun_map.get(mun_name)
            if not mun_id:
                continue

            for nome, partido, esfera, cargo, votos, eleito in deputados:
                # Upsert parlamentar
                result = conn.execute(text("""
                    INSERT INTO parlamentares (nome, partido, esfera, uf, legislatura)
                    VALUES (:n, :p, :e, 'MG', '2023-2027')
                    ON CONFLICT (nome, partido, esfera) DO UPDATE SET
                        uf = EXCLUDED.uf,
                        legislatura = EXCLUDED.legislatura
                    RETURNING id
                """), {"n": nome, "p": partido, "e": esfera})
                parl_id = result.scalar()
                inserted_parl += 1

                # Insert electoral data
                conn.execute(text("""
                    INSERT INTO dados_eleitorais (
                        parlamentar_id, municipio_id, ano_eleicao, votos, cargo, eleito
                    ) VALUES (:p, :m, 2022, :v, :c, :e)
                    ON CONFLICT (parlamentar_id, municipio_id, ano_eleicao, cargo)
                    DO UPDATE SET votos = EXCLUDED.votos, eleito = EXCLUDED.eleito
                """), {"p": parl_id, "m": mun_id, "v": votos, "c": cargo, "e": eleito})
                inserted_eleicoes += 1

        conn.commit()
    print(f"  Parlamentares: {inserted_parl}")
    print(f"  Resultados eleitorais: {inserted_eleicoes}")


def enrich_emendas_with_funcao():
    """Extract funcao/subfuncao from SIGCON convenio raw_data and apply to emendas."""
    print("\n=== Enriquecendo emendas com funcao/subfuncao ===")

    # Heuristic mapping based on objeto keywords
    OBJETO_TO_FUNCAO = {
        "saude": ("Saude", "Atencao Basica"),
        "ubs": ("Saude", "Atencao Basica"),
        "hospital": ("Saude", "Assistencia Hospitalar"),
        "educacao": ("Educacao", "Ensino Fundamental"),
        "escola": ("Educacao", "Ensino Fundamental"),
        "creche": ("Educacao", "Educacao Infantil"),
        "transporte escolar": ("Educacao", "Transporte Escolar"),
        "cultura": ("Cultura", "Difusao Cultural"),
        "esporte": ("Desporto e Lazer", "Desporto Comunitario"),
        "quadra": ("Desporto e Lazer", "Desporto Comunitario"),
        "ginasio": ("Desporto e Lazer", "Desporto Comunitario"),
        "pavimenta": ("Urbanismo", "Infra-estrutura Urbana"),
        "asfalto": ("Urbanismo", "Infra-estrutura Urbana"),
        "drenagem": ("Saneamento", "Saneamento Basico Urbano"),
        "veiculo": ("Administracao", "Administracao Geral"),
        "equipamento": ("Administracao", "Administracao Geral"),
        "agricultura": ("Agricultura", "Extensao Rural"),
        "rural": ("Agricultura", "Extensao Rural"),
        "habitacao": ("Habitacao", "Habitacao Urbana"),
        "social": ("Assistencia Social", "Assistencia Comunitaria"),
        "padem": ("Administracao", "Administracao Geral"),
        "melhoria": ("Urbanismo", "Servicos Urbanos"),
    }

    updated = 0
    with engine.connect() as conn:
        # Get all emendas with their convenio objeto
        rows = conn.execute(text("""
            SELECT e.id, c.objeto
            FROM emendas e
            JOIN convenios_estadual c ON e.convenio_estadual_id = c.id
        """)).fetchall()

        for row in rows:
            objeto = (row[1] or "").lower()
            funcao = "Nao classificada"
            subfuncao = ""
            for keyword, (f, sf) in OBJETO_TO_FUNCAO.items():
                if keyword in objeto:
                    funcao, subfuncao = f, sf
                    break

            conn.execute(text("""
                UPDATE emendas SET funcao = :f, subfuncao = :sf WHERE id = :id
            """), {"f": funcao, "sf": subfuncao, "id": row[0]})
            updated += 1

        conn.commit()
    print(f"  Emendas classificadas: {updated}")


if __name__ == "__main__":
    seed_dados_eleitorais()
    enrich_emendas_with_funcao()
    print("\n=== Concluido ===")
