"""
Unificar parlamentares duplicados: mesmo nome (normalizado) em registros diferentes.
Consolida em uma unica row e atualiza referencias em emendas/dados_eleitorais.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unicodedata
from sqlalchemy import create_engine, text
from config import get_settings

settings = get_settings()
engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))


def norm(s):
    if not s:
        return ""
    s = str(s).strip().upper()
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def main():
    print("=== Deduplicando parlamentares ===")

    with engine.connect() as conn:
        # Get all parlamentares
        rows = conn.execute(text("""
            SELECT id, nome, partido, esfera, uf FROM parlamentares ORDER BY id
        """)).fetchall()
        print(f"  Total parlamentares: {len(rows)}")

        # Group by normalized name + esfera
        groups = {}
        for row in rows:
            key = (norm(row[1]), row[3] or "federal")
            groups.setdefault(key, []).append(row)

        dups = {k: v for k, v in groups.items() if len(v) > 1}
        print(f"  Grupos duplicados: {len(dups)}")

        merged = 0
        for (name_norm, esfera), group in dups.items():
            # Pick the canonical row: prefer one with partido filled, else smallest id
            canonical = next((r for r in group if r[2]), group[0])
            canonical_id = canonical[0]
            canonical_partido = canonical[2]

            # Update canonical with best info from group
            best_partido = canonical_partido
            for r in group:
                if r[2] and not best_partido:
                    best_partido = r[2]

            conn.execute(text("""
                UPDATE parlamentares SET partido = :p WHERE id = :id AND partido IS NULL
            """), {"p": best_partido, "id": canonical_id})

            # Update references
            other_ids = [r[0] for r in group if r[0] != canonical_id]
            for other_id in other_ids:
                conn.execute(text("""
                    UPDATE emendas SET parlamentar_id = :c WHERE parlamentar_id = :o
                """), {"c": canonical_id, "o": other_id})
                conn.execute(text("""
                    UPDATE dados_eleitorais SET parlamentar_id = :c WHERE parlamentar_id = :o
                """), {"c": canonical_id, "o": other_id})
                conn.execute(text("DELETE FROM parlamentares WHERE id = :o"), {"o": other_id})
                merged += 1

        conn.commit()
        print(f"  Merged: {merged}")

        # Final count
        total = conn.execute(text("SELECT COUNT(*) FROM parlamentares")).scalar()
        print(f"  Total apos dedup: {total}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback; traceback.print_exc()
        sys.exit(1)
