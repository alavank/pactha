"""
Script para criar tabelas e seed inicial no Neon PostgreSQL.
Executa de forma sincrona para simplicidade.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import create_engine, text
from config import get_settings
from services.auth import hash_password

settings = get_settings()

# Use sync URL
db_url = settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", "")
engine = create_engine(db_url)


def create_tables():
    with engine.connect() as conn:
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS municipios (
            id SERIAL PRIMARY KEY,
            nome VARCHAR(200) NOT NULL,
            ibge_code VARCHAR(7) UNIQUE NOT NULL,
            uf VARCHAR(2) DEFAULT 'MG',
            active BOOLEAN DEFAULT true,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            name VARCHAR(200) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(50) DEFAULT 'analyst',
            active BOOLEAN DEFAULT true,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS parlamentares (
            id SERIAL PRIMARY KEY,
            nome VARCHAR(300) NOT NULL,
            partido VARCHAR(50),
            uf VARCHAR(2),
            esfera VARCHAR(20),
            legislatura VARCHAR(20),
            external_id VARCHAR(100),
            UNIQUE(nome, partido, esfera)
        );

        CREATE TABLE IF NOT EXISTS convenios_federal (
            id SERIAL PRIMARY KEY,
            nr_convenio VARCHAR(50) UNIQUE NOT NULL,
            municipio_id INTEGER REFERENCES municipios(id),
            proponente_nome VARCHAR(500),
            orgao_concedente VARCHAR(500),
            objeto TEXT,
            situacao VARCHAR(200),
            valor_global NUMERIC(18,2),
            valor_repasse NUMERIC(18,2),
            valor_contrapartida NUMERIC(18,2),
            valor_empenhado NUMERIC(18,2),
            valor_desembolsado NUMERIC(18,2),
            dt_inicio DATE,
            dt_fim DATE,
            dt_fim_vigencia DATE,
            ano INTEGER,
            programa VARCHAR(500),
            modalidade VARCHAR(200),
            raw_data JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS convenios_estadual (
            id SERIAL PRIMARY KEY,
            nr_sigcon VARCHAR(50),
            nr_siafi VARCHAR(50),
            municipio_id INTEGER REFERENCES municipios(id),
            convenente_nome VARCHAR(500),
            orgao_concedente VARCHAR(500),
            objeto TEXT,
            objetivo TEXT,
            situacao VARCHAR(200),
            tp_instrumento VARCHAR(100),
            valor_concedente NUMERIC(18,2),
            valor_emenda_parlamentar NUMERIC(18,2),
            valor_contrapartida NUMERIC(18,2),
            valor_total NUMERIC(18,2),
            valor_repassado NUMERIC(18,2),
            dt_publicacao DATE,
            dt_vigencia_inicial DATE,
            dt_vigencia_final DATE,
            dt_vigencia_atual DATE,
            ano INTEGER,
            etapa_sigcon VARCHAR(200),
            etapa_sigcon_nr INTEGER,
            raw_data JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS transferegov_propostas (
            id SERIAL PRIMARY KEY,
            municipio_id INTEGER REFERENCES municipios(id),
            numero_proposta VARCHAR(20) NOT NULL,
            situacao VARCHAR(300),
            orgao VARCHAR(300),
            proponente VARCHAR(300),
            possui_parecer VARCHAR(10),
            identificacao VARCHAR(30),
            codigo_instrumento VARCHAR(30),
            modalidade VARCHAR(100),
            situacao_siafi VARCHAR(200),
            numero_processo VARCHAR(50),
            objeto TEXT,
            programa VARCHAR(300),
            dt_inicio_vigencia DATE,
            dt_fim_vigencia DATE,
            dt_proposta DATE,
            dt_assinatura DATE,
            detalhe JSONB,
            raw_data JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(municipio_id, numero_proposta)
        );
        -- Colunas valor_*/situacao_contratacao*/clausula_*/parlamentar/id_proposta_siconv
        -- sao adicionadas pelas migrations add_voluntarias_* (ADD COLUMN IF NOT EXISTS).

        CREATE TABLE IF NOT EXISTS emendas (
            id SERIAL PRIMARY KEY,
            nr_emenda VARCHAR(100),
            parlamentar_id INTEGER REFERENCES parlamentares(id),
            municipio_id INTEGER REFERENCES municipios(id),
            convenio_federal_id INTEGER REFERENCES convenios_federal(id),
            convenio_estadual_id INTEGER REFERENCES convenios_estadual(id),
            valor NUMERIC(18,2),
            ano INTEGER,
            tipo VARCHAR(100),
            esfera VARCHAR(20),
            funcao VARCHAR(200),
            subfuncao VARCHAR(200),
            raw_data JSONB
        );

        CREATE TABLE IF NOT EXISTS desembolsos (
            id SERIAL PRIMARY KEY,
            convenio_federal_id INTEGER REFERENCES convenios_federal(id),
            data_desembolso DATE,
            valor NUMERIC(18,2),
            nr_ordem_bancaria VARCHAR(100),
            raw_data JSONB
        );

        CREATE TABLE IF NOT EXISTS editais (
            id SERIAL PRIMARY KEY,
            titulo VARCHAR(1000) NOT NULL,
            orgao VARCHAR(500),
            area VARCHAR(100),
            esfera VARCHAR(20),
            url TEXT,
            dt_publicacao DATE,
            dt_encerramento DATE,
            valor_total NUMERIC(18,2),
            resumo TEXT,
            status VARCHAR(50) DEFAULT 'aberto',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS edital_acompanhamento (
            id SERIAL PRIMARY KEY,
            edital_id INTEGER REFERENCES editais(id),
            municipio_id INTEGER REFERENCES municipios(id),
            user_id INTEGER REFERENCES users(id),
            notas TEXT,
            status VARCHAR(50) DEFAULT 'acompanhando',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(edital_id, municipio_id)
        );

        CREATE TABLE IF NOT EXISTS prestacao_contas (
            id SERIAL PRIMARY KEY,
            convenio_estadual_id INTEGER REFERENCES convenios_estadual(id),
            convenio_federal_id INTEGER REFERENCES convenios_federal(id),
            municipio_id INTEGER REFERENCES municipios(id),
            etapa_atual INTEGER DEFAULT 1,
            etapa_nome VARCHAR(200),
            responsavel_id INTEGER REFERENCES users(id),
            status VARCHAR(100) DEFAULT 'pendente',
            observacoes TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS prestacao_documentos (
            id SERIAL PRIMARY KEY,
            prestacao_id INTEGER REFERENCES prestacao_contas(id),
            documento_nome VARCHAR(500) NOT NULL,
            enviado BOOLEAN DEFAULT false,
            dt_envio DATE,
            responsavel_id INTEGER REFERENCES users(id),
            observacao TEXT
        );

        CREATE TABLE IF NOT EXISTS dados_eleitorais (
            id SERIAL PRIMARY KEY,
            parlamentar_id INTEGER REFERENCES parlamentares(id),
            municipio_id INTEGER REFERENCES municipios(id),
            ano_eleicao INTEGER,
            votos INTEGER,
            cargo VARCHAR(100),
            eleito BOOLEAN,
            UNIQUE(parlamentar_id, municipio_id, ano_eleicao, cargo)
        );

        CREATE TABLE IF NOT EXISTS ingestion_log (
            id SERIAL PRIMARY KEY,
            source VARCHAR(100) NOT NULL,
            started_at TIMESTAMPTZ DEFAULT NOW(),
            finished_at TIMESTAMPTZ,
            status VARCHAR(50) DEFAULT 'running',
            records_processed INTEGER DEFAULT 0,
            records_inserted INTEGER DEFAULT 0,
            records_updated INTEGER DEFAULT 0,
            error_message TEXT
        );

        -- Indexes
        CREATE INDEX IF NOT EXISTS idx_convenios_fed_municipio ON convenios_federal(municipio_id);
        CREATE INDEX IF NOT EXISTS idx_convenios_fed_situacao ON convenios_federal(situacao);
        CREATE INDEX IF NOT EXISTS idx_convenios_fed_vigencia ON convenios_federal(dt_fim_vigencia);
        CREATE INDEX IF NOT EXISTS idx_convenios_est_municipio ON convenios_estadual(municipio_id);
        CREATE INDEX IF NOT EXISTS idx_convenios_est_situacao ON convenios_estadual(situacao);
        CREATE INDEX IF NOT EXISTS idx_convenios_est_vigencia ON convenios_estadual(dt_vigencia_atual);
        CREATE INDEX IF NOT EXISTS idx_emendas_parlamentar ON emendas(parlamentar_id);
        CREATE INDEX IF NOT EXISTS idx_emendas_municipio ON emendas(municipio_id);
        CREATE INDEX IF NOT EXISTS idx_editais_area ON editais(area);
        CREATE INDEX IF NOT EXISTS idx_editais_status ON editais(status);
        """))
        conn.commit()
        print("Tabelas criadas com sucesso!")


def _gen_password(length: int = 16) -> str:
    """Gera senha aleatoria forte."""
    import secrets, string
    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def seed_data():
    """Cria municipios piloto + admin + analistas com senhas geradas aleatoriamente.
    As senhas sao impressas no console — NAO sao gravadas em disco nem versionadas.
    Usuarios devem trocar no primeiro login (campo must_change_password).
    """
    import os
    admin_email = os.getenv("ADMIN_EMAIL", "admin@pactha.com.br")
    # Permite override por env (CI/CD), ou gera aleatoria
    admin_pwd = os.getenv("ADMIN_PASSWORD") or _gen_password()
    admin_hash = hash_password(admin_pwd)

    senhas_geradas = [("ADMIN", admin_email, admin_pwd)]

    with engine.connect() as conn:
        # Municipios piloto
        conn.execute(text("""
        INSERT INTO municipios (nome, ibge_code, uf) VALUES
            ('Araújos', '3104502', 'MG'),
            ('Nova Serrana', '3145208', 'MG'),
            ('Bom Despacho', '3107406', 'MG'),
            ('São Tiago', '3164704', 'MG'),
            ('Toledo', '3169406', 'MG'),
            ('Piracema', '3151206', 'MG')
        ON CONFLICT (ibge_code) DO NOTHING;
        """))

        # Admin user (so cria se nao existir; nao sobrescreve senha existente)
        conn.execute(text("""
        INSERT INTO users (email, name, password_hash, role) VALUES
            (:email, :name, :hash, 'admin')
        ON CONFLICT (email) DO NOTHING;
        """), {"email": admin_email, "name": "Administrador", "hash": admin_hash})

        for user in [
            ("lara@freitas.com.br", "Lara"),
            ("marcia@freitas.com.br", "Marcia Alves"),
            ("laiza@freitas.com.br", "Laiza Brena"),
            ("larissa@freitas.com.br", "Larissa Faustino"),
            ("dani@freitas.com.br", "Daniele Vicente"),
        ]:
            pwd = _gen_password()
            senhas_geradas.append(("ANALYST", user[0], pwd))
            conn.execute(text("""
            INSERT INTO users (email, name, password_hash, role) VALUES
                (:email, :name, :hash, 'analyst')
            ON CONFLICT (email) DO NOTHING;
            """), {"email": user[0], "name": user[1], "hash": hash_password(pwd)})

        conn.commit()
        print("\n" + "=" * 60)
        print("SENHAS GERADAS (anote agora - NAO serao mostradas novamente)")
        print("=" * 60)
        for role, email, pwd in senhas_geradas:
            print(f"  [{role}] {email}  ->  {pwd}")
        print("=" * 60)
        print("Os usuarios devem trocar a senha no primeiro login.\n")


if __name__ == "__main__":
    print("Criando tabelas no Neon PostgreSQL...")
    create_tables()
    print("\nInserindo dados iniciais...")
    seed_data()
    print("\nSetup concluido!")
