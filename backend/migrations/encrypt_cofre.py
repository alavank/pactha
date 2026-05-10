"""
Migration: encripta valores legados do cofre (plaintext -> AES-GCM).
Tambem adiciona colunas must_change_password e last_login_at na tabela users.

Uso:
    COFRE_KEY=<32-byte-key> python backend/migrations/encrypt_cofre.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, text
from config import get_settings
from services import crypto

settings = get_settings()
engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))


def main():
    with engine.begin() as conn:
        # Adiciona colunas em users (se nao existirem)
        conn.execute(text("""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN DEFAULT TRUE;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;
        """))
        # Marca usuarios existentes (admin) como nao precisando trocar senha imediato
        # para nao bloquear ninguem sem aviso
        # (deixar como TRUE por default, mas existentes nao tem must_change definido)

        # Encripta senhas legadas do cofre
        rows = conn.execute(text(
            "SELECT id, senha_hash FROM cofre_senhas WHERE senha_hash IS NOT NULL"
        )).fetchall()

        n_encrypted = 0
        for cid, senha in rows:
            if not senha:
                continue
            if str(senha).startswith("v1:"):
                continue  # ja encriptado
            try:
                enc = crypto.encrypt(str(senha))
                conn.execute(text("UPDATE cofre_senhas SET senha_hash = :s WHERE id = :i"), {"s": enc, "i": cid})
                n_encrypted += 1
            except Exception as e:
                print(f"  ERRO encriptando id={cid}: {e}")

        print(f"Encriptados: {n_encrypted}/{len(rows)} registros do cofre")


if __name__ == "__main__":
    if not os.getenv("COFRE_KEY"):
        print("ERRO: COFRE_KEY nao definida. Aborte e configure primeiro.")
        sys.exit(1)
    main()
