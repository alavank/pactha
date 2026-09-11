"""Diagnóstico READ-ONLY da auditoria de coleta (M-5 e M-7).

⚠️ SOMENTE LEITURA — nenhum UPDATE/DELETE/INSERT. Só mede e imprime, para o dono
decidir se há correção a fazer. Não corrige nada automaticamente (era a regra da
auditoria e continua valendo para o histórico).

Uso (em ambiente com acesso ao banco do tenant — NÃO roda na sessão de auditoria):
    DATABASE_URL_SYNC=postgresql://... python scripts/diagnostico_auditoria.py

Produção: PENDENTE (esta sessão não tem control token/DB). Rode por tenant e cole a
saída — daí sai a evidência que fecha M-5 e M-7.
"""
import os
import sys

import psycopg2


def _conn():
    url = (os.getenv("DATABASE_URL_SYNC") or os.getenv("DATABASE_URL", "").replace("+asyncpg", ""))
    url = url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    if not url:
        sys.exit("defina DATABASE_URL_SYNC")
    return psycopg2.connect(url)


# ── M-5: colisões da chave sintética SHA1 do CAGE-RS (convenios_rs) ──────────
_M5 = [
    ("mesmo nr_sigcon em >1 linha CAGE-RS (colisão intra-fonte)", """
        SELECT nr_sigcon, count(*) AS n
        FROM convenios_estadual
        WHERE fonte ILIKE '%CAGE%'
        GROUP BY nr_sigcon HAVING count(*) > 1
        ORDER BY n DESC LIMIT 50;"""),
    ("nr_sigcon compartilhado entre fontes diferentes (colisão inter-fonte)", """
        SELECT nr_sigcon, array_agg(DISTINCT fonte) AS fontes, count(*) AS n
        FROM convenios_estadual
        GROUP BY nr_sigcon HAVING count(DISTINCT fonte) > 1
        ORDER BY n DESC LIMIT 50;"""),
]

# ── M-7: possível contaminação de _casa_municipio (vínculo por NOME != CNPJ) ─
_M7 = [
    ("planos TE cujo CNPJ do beneficiário aponta município DIFERENTE do vinculado", """
        SELECT te.plano_acao_id, te.municipio_id AS mun_vinculado,
               m.id AS mun_por_cnpj, te.beneficiario_cnpj, te.beneficiario_nome
        FROM transferegov_te te
        JOIN municipios m
          ON regexp_replace(coalesce(m.cnpj,''),'\\D','','g')
           = regexp_replace(coalesce(te.beneficiario_cnpj,''),'\\D','','g')
        WHERE m.id IS NOT NULL AND m.id <> te.municipio_id
        ORDER BY te.municipio_id LIMIT 100;"""),
]


def _roda(cur, titulo, sql):
    print(f"\n### {titulo}")
    try:
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        if not rows:
            print("   (nenhum — OK)")
            return 0
        print("   " + " | ".join(cols))
        for r in rows:
            print("   " + " | ".join(str(x) for x in r))
        print(f"   >>> {len(rows)} linha(s) — REVISAR")
        return len(rows)
    except Exception as e:
        print(f"   ERRO ao consultar: {str(e)[:120]}")
        return -1


def main():
    conn = _conn(); cur = conn.cursor()
    conn.set_session(readonly=True)  # trava: qualquer escrita falha
    print("=== DIAGNÓSTICO M-5 (colisão de chave CAGE-RS) ===")
    for t, q in _M5:
        _roda(cur, t, q)
    print("\n=== DIAGNÓSTICO M-7 (contaminação _casa_municipio na TE) ===")
    for t, q in _M7:
        _roda(cur, t, q)
    cur.close(); conn.close()
    print("\n(Read-only. Nada foi alterado. Cole a saída para fechar M-5/M-7.)")


if __name__ == "__main__":
    main()
