#!/usr/bin/env python
"""Verificador de INTEGRIDADE do PACTHA — roda no tenant e diz o que esta torto.

POR QUE ESTE ARQUIVO EXISTE
---------------------------
A auditoria externa de 29/08/2026 e os sete agentes de verificacao produziram
~33 mil caracteres de SQL de conferencia. Nenhum deles cabia no jeito que eu
vinha usando para consultar producao: o comando de Scheduled Task do Coolify
trava perto de 230 caracteres, e essas consultas tem CTE e FILTER de 3 a 6 KB.

Recortar cada uma em pedacinhos de 90 chars — o que eu fiz durante a sessao —
nao escala, perde a riqueza da consulta e, pior, ja me fez ler LOG VELHO como
se fosse resultado novo mais de uma vez. O mecanismo certo e este: o SQL mora no
repositorio, versionado e revisavel, e a task do Coolify vira um comando curto.

    flock -n -E 99 /tmp/scraper.lock python -u ingestion/diagnostico_integridade.py

⚠️ MORA EM `ingestion/` E NAO EM `scripts/`, e isso NAO e arrumacao: o
`Dockerfile.scraper` copia so ingestion/, models/, services/, schemas/ e dois
arquivos soltos. Um verificador em `scripts/` simplesmente NAO EXISTE dentro do
container — a task rodaria e diria 'can't open file'. E a companhia certa: e
onde ja vivem `watchdog_coleta.py` e os `run_*_cron.py`, que sao operacionais
pelo mesmo motivo.

⚠️ SO LEITURA. Nenhuma consulta aqui escreve. E de proposito: um verificador que
tambem conserta nao serve para AUDITAR o conserto.

COMO LER O RESULTADO
--------------------
Cada checagem imprime OK / ATENCAO / FALHA e a frase do que aquilo significa. O
processo sai com codigo 1 se houver qualquer FALHA — assim ele serve tanto para
leitura humana quanto para virar alarme depois.

⚠️ CHECAGEM QUE NAO RODA NAO E CHECAGEM QUE PASSOU. Coluna ou tabela ausente
vira PULADA e aparece no resumo. Um tenant onde metade pula com "tudo OK" no
final seria a mesma mentira que este arquivo existe para combater.
"""
import os
import sys

# ---------------------------------------------------------------------------
# AS CHECAGENS. `limite` decide o veredito: quanto do resultado ainda e
# aceitavel. `explica` e o que o numero PROVA — sem isso, um numero solto nao
# vira decisao.
# ---------------------------------------------------------------------------
CHECAGENS = [
    {
        "nome": "valores: trio incoerente (global <> repasse + contrapartida)",
        "sql": """
            SELECT count(*) FILTER (WHERE valor_global IS NOT NULL
                                      AND valor_repasse IS NOT NULL
                                      AND valor_contrapartida IS NOT NULL
                                      AND round(valor_repasse + valor_contrapartida, 2)
                                          <> round(valor_global, 2)),
                   count(*)
              FROM transferegov_propostas
        """,
        "explica": (
            "Deslocamento de campo do grab_money: cada rotulo colhia o valor do "
            "SEGUINTE. Medido em 29/08: 854 de 3.199 (27%). Depois do #322 e da "
            "reingestao do CSV: 29, e esses 29 sao do DADO OFICIAL (global maior "
            "que a soma e legitimo em ~0,9% da carteira)."
        ),
        "limite": 60,
    },
    {
        "nome": "valores: aritmeticamente IMPOSSIVEL (global < repasse)",
        "sql": """
            SELECT count(*), 0 FROM transferegov_propostas
             WHERE valor_global IS NOT NULL AND valor_repasse IS NOT NULL
               AND valor_global < valor_repasse
        """,
        "explica": "Nao existe convenio em que o repasse supere o valor global. "
                   "Qualquer numero acima de zero e corrupcao, nao dado.",
        "limite": 0,
    },
    {
        "nome": "ART/RRT: obra com medicao atestada e ZERO ART lida",
        "sql": """
            SELECT count(*), 0 FROM transferegov_propostas p
             WHERE p.obras ? 'lotes'
               AND jsonb_array_length(p.obras->'lotes') > 0
               AND (SELECT count(*) FROM jsonb_array_elements(p.obras->'lotes') l
                     WHERE jsonb_array_length(COALESCE(l->'arts','[]'::jsonb)) > 0) = 0
               AND (SELECT COALESCE(sum((l->>'medicoes_atestadas')::int), 0)
                      FROM jsonb_array_elements(p.obras->'lotes') l) > 0
        """,
        "explica": (
            "Medicao atestada NAO EXISTE sem ART cadastrada — entao `arts: []` "
            "com medicao > 0 so pode ser leitura que falhou. Cada linha aqui e um "
            "RM que imprimiu 'falta ART/RRT' acusando o municipio (#323). O "
            "passivo nao tem conserto por migration: a origem do [] nao foi "
            "gravada. Tem de cair sozinho conforme as obras sao recoletadas."
        ),
        "limite": 0,
    },
    {
        "nome": "gov.br: fatia atras do login CONGELADA (dias sem leitura)",
        "sql": """
            SELECT COALESCE(EXTRACT(day FROM now() - max(historico_atualizado_em))::int, 999),
                   count(*)
              FROM transferegov_propostas
        """,
        "explica": (
            "A linha parece fresca porque `updated_at` e tocado a cada upsert, "
            "mas o carimbo do que so existe atras do login e outro. Distancia "
            "grande = sessao fria: NE, projeto basico, licitacao e clausula "
            "parados. O #324 faz a RODADA sair 'parcial' nesse caso; esta "
            "checagem mede o ESTADO, nao a rodada."
        ),
        "limite": 3,
    },
    {
        "nome": "ingestion_log: rodadas que nasceram JA ENCERRADAS (crash e invisivel)",
        "sql": """
            SELECT count(*) FILTER (WHERE finished_at IS NOT NULL
                                      AND (started_at IS NULL
                                           OR finished_at - started_at < interval '1 second')),
                   count(*)
              FROM ingestion_log
             WHERE COALESCE(finished_at, started_at) > now() - interval '30 days'
        """,
        "explica": (
            "⚠️ A PRIMEIRA VERSAO DESTA CHECAGEM ESTAVA ERRADA e deu 0 de 2.172, "
            "parecendo aprovacao. Ela contava 'linha sem par inicio/fim' — mas a "
            "rodada que MORRE nao deixa linha NENHUMA para ser contada. Estava "
            "medindo o que EXISTE, quando o defeito e o que FALTA. E o mesmo erro "
            "de forma que os seis achados da auditoria tem.\n"
            "           Agora mede o SINTOMA que da para ver: linha que nasce ja "
            "encerrada (duracao zero ou sem `started_at`) e coletor que nao abre a "
            "rodada — e coletor que nao abre e coletor cujo crash e invisivel. "
            "Alto e o esperado hoje: nenhum dos 28 INSERTs grava 'running'."
        ),
        "limite": 999999,          # informativo: ainda nao ha conserto no ar
    },
    {
        "nome": "SIGCON: municipios ATIVOS sem convenio estadual nenhum",
        "sql": """
            SELECT count(*), (SELECT count(*) FROM municipios WHERE COALESCE(active, true))
              FROM municipios m
             WHERE COALESCE(m.active, true)
               AND NOT EXISTS (SELECT 1 FROM convenios_estadual c
                                WHERE c.municipio_id = m.id
                                  AND upper(COALESCE(c.fonte,'')) LIKE 'SIGCON%')
        """,
        "explica": (
            "O auditor achou 20 de 42. ⚠️ Este numero sozinho NAO acusa defeito: "
            "sem credencial no Cofre o SIGCON nao tem como coletar, e isso e "
            "pendencia comercial, nao bug. O defeito de software e a TELA mostrar "
            "o mesmo vazio para tres estados diferentes — sem credencial, "
            "credencial recusada, e coletado sem convenio."
        ),
        "limite": 999999,          # informativo
    },
    {
        "nome": "prestacao de contas: convenios com a secao lida",
        "sql": """
            SELECT count(raw_data->'prestacao_contas_status'),
                   count(*) FROM convenios_estadual
             WHERE upper(COALESCE(fonte,'')) LIKE 'SIGCON%'
        """,
        "explica": (
            "Cobertura do que foi entregue em 27-29/08. Cresce a cada rodada "
            "conforme o rodizio de pagina (#319) alcanca convenios que o laco de "
            "detalhe nunca lia."
        ),
        "limite": 999999,          # informativo: quanto MAIOR, melhor
    },
]


def _dsn() -> str:
    u = os.getenv("DATABASE_URL_SYNC", "") or os.getenv("DATABASE_URL", "")
    return u.replace("&channel_binding=require", "").replace("?channel_binding=require", "")


def main() -> int:
    try:
        import psycopg2
    except ImportError:
        print("psycopg2 ausente"); return 2
    dsn = _dsn()
    if not dsn:
        print("DATABASE_URL_SYNC ausente"); return 2

    conn = psycopg2.connect(dsn)
    falhas = puladas = 0
    print(f"=== DIAGNOSTICO DE INTEGRIDADE — {os.getenv('INSTANCE_SLUG', '?')} ===\n")
    for c in CHECAGENS:
        try:
            with conn.cursor() as cur:
                cur.execute(c["sql"])
                achado, total = cur.fetchone()
            conn.rollback()          # so leitura: nao deixa transacao aberta
        except Exception as e:
            conn.rollback()
            puladas += 1
            print(f"[PULADA ] {c['nome']}\n           {str(e).splitlines()[0][:110]}\n")
            continue
        achado = int(achado or 0)
        if achado > c["limite"]:
            selo, marca = ("[FALHA  ]", True) if c["limite"] < 999999 else ("[INFO   ]", False)
            falhas += 1 if marca else 0
        else:
            selo = "[OK     ]"
        de = f" de {total}" if total else ""
        print(f"{selo} {c['nome']}: {achado}{de}")
        print(f"           {c['explica']}\n")

    print(f"=== {len(CHECAGENS)} checagens | {falhas} falha(s) | {puladas} pulada(s) ===")
    if puladas:
        # ⚠️ Checagem que nao roda NAO e checagem que passou.
        print("⚠️ Ha checagem PULADA: o resultado acima esta INCOMPLETO.")
    conn.close()
    return 1 if (falhas or puladas) else 0


if __name__ == "__main__":
    sys.exit(main())
