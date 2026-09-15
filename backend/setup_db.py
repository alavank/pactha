"""
Script para criar tabelas e seed inicial no PostgreSQL.
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
            uf VARCHAR(2),  -- sem default: UF e decisao de quem provisiona, nunca herdada
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

        -- ⚠️ SEM AS TABELAS DO REFACTOR LEAN (2026-05). `convenios_federal`,
        -- `emendas`, `desembolsos`, `editais`, `edital_acompanhamento`,
        -- `prestacao_contas`, `prestacao_documentos` e `dados_eleitorais` eram
        -- criadas AQUI a cada boot e derrubadas logo depois por
        -- `migrations/drop_lean_tables.sql`. O DROP ... CASCADE tira as chaves
        -- estrangeiras para `convenios_estadual`/`municipios`/`users` e precisa de
        -- lock nelas: em 15/09/2026 o boot da API da Freitas ficou esperando o
        -- `sigcon`, que escrevia em `convenios_estadual`, ate o healthcheck do
        -- Coolify desistir e voltar o container antigo. Guardado por
        -- `tests/test_boot_nao_recria_tabela_morta.py`.

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
            -- ⚠️ TEXTO, e não DATE: o coletor grava "dd/mm/aaaa" cru (o rótulo
            -- vem assim do detalhe do TransfereGov) e as telas leem esse texto.
            -- Declaradas DATE aqui, o Postgres convertia usando o DateStyle do
            -- servidor (MDY) e trocava dia por mês EM SILÊNCIO quando o dia era
            -- <= 12, ou abortava a coleta do município quando passava disso.
            -- Os 3 bancos vindos do Neon sempre foram varchar; era este arquivo
            -- que divergia. Ver `migrations/fix_transferegov_datas_texto.sql`.
            dt_inicio_vigencia VARCHAR(20),
            dt_fim_vigencia VARCHAR(20),
            dt_proposta VARCHAR(20),
            dt_assinatura VARCHAR(20),
            detalhe JSONB,
            raw_data JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(municipio_id, numero_proposta)
        );
        -- Colunas valor_*/situacao_contratacao*/clausula_*/parlamentar/id_proposta_siconv
        -- sao adicionadas pelas migrations add_voluntarias_* (ADD COLUMN IF NOT EXISTS).

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
        CREATE INDEX IF NOT EXISTS idx_convenios_est_municipio ON convenios_estadual(municipio_id);
        CREATE INDEX IF NOT EXISTS idx_convenios_est_situacao ON convenios_estadual(situacao);
        CREATE INDEX IF NOT EXISTS idx_convenios_est_vigencia ON convenios_estadual(dt_vigencia_atual);
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
    # A conta de BOOTSTRAP, e o unico jeito de entrar num tenant recem-criado.
    #
    # Era `admin@pactha.com.br`, que tinha dois problemas: o nome dizia "mais um
    # admin" quando na verdade e a chave da plataforma, e ele estava em
    # SUPER_ADMIN_EMAILS — entao qualquer admin do cliente que recriasse aquele
    # e-mail na tela de Usuarios recebia super poder. Agora o e-mail e explicito
    # e esta na lista por ser o que ele e, nao por herdar o nome de "admin".
    #
    # A senha e ALEATORIA por tenant (`_gen_password`, so impressa no console) e
    # `users.must_change_password` tem DEFAULT TRUE, entao o primeiro acesso e
    # obrigado a trocar. Nao existe senha igual em dois clientes.
    admin_email = os.getenv("ADMIN_EMAIL", "super-admin@alavank.com.br")
    # Permite override por env (CI/CD), ou gera aleatoria
    admin_pwd = os.getenv("ADMIN_PASSWORD") or _gen_password()
    admin_hash = hash_password(admin_pwd)

    senhas_geradas = [("ADMIN", admin_email, admin_pwd)]

    with engine.connect() as conn:
        # O MUNICIPIO DO CLIENTE, vindo do ambiente DESTE tenant.
        #
        # Aqui havia seis municipios fixos (Araújos, Nova Serrana, Bom Despacho,
        # São Tiago, Toledo, Piracema). Um cliente novo nascia com seis cidades
        # que nao sao dele — e isso nao para no visual: o front auto-seleciona o
        # PRIMEIRO da lista, e todo coletor itera os municipios cadastrados. O
        # tenant novo abria mostrando "Araújos" e comecava a raspar dado de seis
        # municipios de terceiro, gastando a VPS e sujando a base.
        #
        # Sem as tres variaveis nao se inventa municipio: zero linha, e o log diz
        # o que faltou. Base vazia e um problema visivel; base com o municipio
        # errado e um problema que passa despercebido por semanas.
        mun_nome = (os.getenv("MUNICIPIO_NOME") or "").strip()
        mun_ibge = (os.getenv("MUNICIPIO_IBGE") or "").strip()
        mun_uf = (os.getenv("MUNICIPIO_UF") or "").strip().upper()
        if mun_nome and mun_ibge and mun_uf:
            conn.execute(text("""
            INSERT INTO municipios (nome, ibge_code, uf) VALUES (:n, :i, :u)
            ON CONFLICT (ibge_code) DO NOTHING;
            """), {"n": mun_nome, "i": mun_ibge, "u": mun_uf})
            print(f"[seed] municipio do tenant: {mun_nome}-{mun_uf} (IBGE {mun_ibge})")
        else:
            print("[seed] SEM municipio: defina MUNICIPIO_NOME, MUNICIPIO_IBGE e "
                  "MUNICIPIO_UF no ambiente do tenant. O sistema sobe, mas nao "
                  "coleta nada ate existir municipio.")

        # AS CONTAS DE DONO — as unicas com que um tenant nasce.
        #
        # Antes nasciam tambem cinco analistas da Freitas, fixas no codigo: um
        # cliente novo vinha com cinco pessoas de OUTRO cliente com acesso. Quem
        # trabalha no cliente e cadastrado por quem entra, na tela de Usuarios.
        #
        # As tres sao exatamente `services.auth.SUPER_ADMIN_EMAILS`. Nao da para
        # importar de la (o seed roda antes/fora do app), entao a lista esta
        # repetida — e a duplicacao esta ANOTADA nos dois lados, porque divergir
        # aqui significa tenant novo sem dono nenhum.
        for email, nome in [
            (admin_email, "Super Admin"),
            ("alavank.tecnologia@gmail.com", "Tiago Miller"),
            ("tiagomiller@alavank.com.br", "Tiago Miller"),
            ("matheus@alavank.com.br", "Matheus"),
        ]:
            pwd = admin_pwd if email == admin_email else _gen_password()
            if email != admin_email:
                senhas_geradas.append(("SUPER-ADMIN", email, pwd))
            conn.execute(text("""
            INSERT INTO users (email, name, password_hash, role) VALUES
                (:email, :name, :hash, 'admin')
            ON CONFLICT (email) DO NOTHING;
            """), {"email": email, "name": nome, "hash": hash_password(pwd)})

        conn.commit()
        print("\n" + "=" * 60)
        print("SENHAS GERADAS (anote agora - NAO serao mostradas novamente)")
        print("=" * 60)
        for role, email, pwd in senhas_geradas:
            print(f"  [{role}] {email}  ->  {pwd}")
        print("=" * 60)
        print("Os usuarios devem trocar a senha no primeiro login.\n")


if __name__ == "__main__":
    print("Criando tabelas no PostgreSQL...")
    create_tables()
    print("\nInserindo dados iniciais...")
    seed_data()
    print("\nSetup concluido!")
