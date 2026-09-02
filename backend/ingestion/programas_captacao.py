"""RADAR DE CAPTACAO: os programas federais com prazo ABERTO para propor.

A plataforma inteira olha para tras — convenio assinado, emenda indicada, obra
em medicao. Este coletor olha para frente: a porta que ainda esta aberta.

FONTE: `siconv_programa.zip` do TransfereGov (dado aberto, sem login), o mesmo
arquivo que o `transferegov_opendata` ja baixa para resolver o NOME do programa
de uma proposta. Aqui ele e lido pelo outro lado: nao "que programa e este que
eu ja usei", e sim "que programa eu ainda posso usar".

MEDIDO EM 02/09/2026, na rodada que criou este arquivo:

    1.257.102 linhas no arquivo
    1.006.720 com SIT_PROGRAMA = DISPONIBILIZADO
        1.314 com o prazo de proposta ainda EM PE
          307 dessas abertas a Administracao Publica Municipal
           17 PROGRAMAS distintos  <- o numero que cabe numa tela

⚠️ "DISPONIBILIZADO" SOZINHO NAO E OPORTUNIDADE. Um milhao de linhas trazem essa
situacao — o campo diz que o programa foi publicado algum dia, e nao que da para
propor hoje. O corte que importa e a DATA: `DT_PROG_FIM_RECEB_PROP >= hoje`.
Filtrar so pela situacao devolveria um catalogo historico com cara de radar.

⚠️ O ARQUIVO REPETE O PROGRAMA UMA VEZ POR UF HABILITADA. As 307 linhas
municipais sao 17 programas. Este coletor AGRUPA por ID_PROGRAMA e junta as UFs
num array — a tabela guarda 17 linhas, nao 307.

⚠️ E A UF E RESTRICAO DE VERDADE. Dos 17, 8 valem para o Brasil inteiro e 9 sao
regionais ("INFRA-ESTRUTURA BASICA SR(RS)" so aceita municipio gaucho). Ignorar
`UF_PROGRAMA` faria a tela oferecer a um prefeito mineiro uma porta que nao abre.

⚠️ SEM ROSTO PROPRIO NO ARQUIVO: nao ha valor, teto, nem dotacao. O radar diz
QUE existe e ATE QUANDO — nao quanto. Inventar um valor seria pior que omitir.

Rodar:  DATABASE_URL_SYNC=... python -u ingestion/programas_captacao.py
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime

import psycopg2
from psycopg2.extras import Json  # noqa: F401  (mantido: legibilidade do modulo)

from ingestion.transferegov_opendata import _linhas

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("programas_captacao")

FONTE = "programas_captacao"
ARQUIVO = "siconv_programa.zip"

# As duas naturezas que interessam a uma prefeitura. O consorcio entra porque
# muitos municipios captam por ele; a TELA filtra so o que a prefeitura propoe
# direto — ver o cabecalho da migration.
NATUREZAS = ("Administração Pública Municipal", "Consórcio Público")


def _dsn() -> str:
    u = os.getenv("DATABASE_URL_SYNC", "") or os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
    return u.replace("&channel_binding=require", "").replace("?channel_binding=require", "")


def data_br(s) -> date | None:
    """dd/mm/aaaa (o formato do arquivo) ou ISO. Funcao PURA.

    ⚠️ Devolve None em qualquer coisa que nao seja data. Um `DT_PROG_FIM_RECEB`
    ilegivel NAO pode virar "hoje" nem "2099" por acidente: o primeiro sumiria
    com o programa da tela, o segundo o deixaria aberto para sempre.
    """
    s = (s or "").strip()
    if not s:
        return None
    for f in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10], f).date()
        except ValueError:
            pass
    return None


def agrupa(linhas, hoje: date) -> dict[str, dict]:
    """As linhas (programa x UF) viram um dicionario por programa. PURA.

    O corte inteiro do radar mora aqui: situacao DISPONIBILIZADO, natureza de
    interesse, e prazo de proposta ainda EM PE.
    """
    progs: dict[str, dict] = {}
    for l in linhas:
        if (l.get("SIT_PROGRAMA") or "").strip() != "DISPONIBILIZADO":
            continue
        nat = (l.get("NATUREZA_JURIDICA_PROGRAMA") or "").strip()
        if nat not in NATUREZAS:
            continue
        fim = data_br(l.get("DT_PROG_FIM_RECEB_PROP"))
        if fim is None or fim < hoje:
            continue
        pid = (l.get("ID_PROGRAMA") or "").strip()
        if not pid:
            continue

        p = progs.get(pid)
        if p is None:
            p = progs[pid] = {
                "id_programa": pid,
                "cod_programa": (l.get("COD_PROGRAMA") or "").strip() or None,
                "nome": (l.get("NOME_PROGRAMA") or "").strip(),
                "orgao": (l.get("DESC_ORGAO_SUP_PROGRAMA") or "").strip() or None,
                "cod_orgao": (l.get("COD_ORGAO_SUP_PROGRAMA") or "").strip() or None,
                "modalidade": (l.get("MODALIDADE_PROGRAMA") or "").strip() or None,
                "acao_orcamentaria": (l.get("ACAO_ORCAMENTARIA") or "").strip() or None,
                "subtipo": (l.get("NOME_SUBTIPO_PROGRAMA") or "").strip() or None,
                "dt_ini_receb": data_br(l.get("DT_PROG_INI_RECEB_PROP")),
                "dt_fim_receb": fim,
                "dt_ini_emenda": data_br(l.get("DT_PROG_INI_EMENDA_PAR")),
                "dt_fim_emenda": data_br(l.get("DT_PROG_FIM_EMENDA_PAR")),
                "dt_disponibilizacao": data_br(l.get("DATA_DISPONIBILIZACAO")),
                "ano_disponibilizacao": _int(l.get("ANO_DISPONIBILIZACAO")),
                "naturezas": set(),
                "ufs": set(),
                "raw": l,
            }
        p["naturezas"].add(nat)
        uf = (l.get("UF_PROGRAMA") or "").strip().upper()
        if uf:
            p["ufs"].add(uf)
        # ⚠️ O PRAZO QUE VALE E O MAIS LONGO ENTRE AS LINHAS DO MESMO PROGRAMA.
        # O arquivo pode trazer datas diferentes por UF; encurtar o programa
        # inteiro pela linha mais restritiva o faria sumir da tela de quem
        # ainda tem prazo. As UFs ficam no array; a data e a do programa.
        if fim > p["dt_fim_receb"]:
            p["dt_fim_receb"] = fim
    return progs


def _int(x):
    try:
        return int(str(x).strip())
    except (TypeError, ValueError):
        return None


_SQL = """
    INSERT INTO programas_captacao
        (id_programa, cod_programa, nome, orgao, cod_orgao, modalidade,
         naturezas, ufs, acao_orcamentaria, subtipo, dt_ini_receb, dt_fim_receb,
         dt_ini_emenda, dt_fim_emenda, dt_disponibilizacao, ano_disponibilizacao,
         raw_data, visto_em, ausente_desde, updated_at)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,NOW(),NULL,NOW())
    ON CONFLICT (id_programa) DO UPDATE SET
        cod_programa=EXCLUDED.cod_programa, nome=EXCLUDED.nome,
        orgao=EXCLUDED.orgao, cod_orgao=EXCLUDED.cod_orgao,
        modalidade=EXCLUDED.modalidade, naturezas=EXCLUDED.naturezas,
        ufs=EXCLUDED.ufs, acao_orcamentaria=EXCLUDED.acao_orcamentaria,
        subtipo=EXCLUDED.subtipo, dt_ini_receb=EXCLUDED.dt_ini_receb,
        dt_fim_receb=EXCLUDED.dt_fim_receb, dt_ini_emenda=EXCLUDED.dt_ini_emenda,
        dt_fim_emenda=EXCLUDED.dt_fim_emenda,
        dt_disponibilizacao=EXCLUDED.dt_disponibilizacao,
        ano_disponibilizacao=EXCLUDED.ano_disponibilizacao,
        raw_data=EXCLUDED.raw_data, visto_em=NOW(),
        -- ⚠️ RESSUSCITA. Programa que voltou a ser oferecido volta para a tela;
        -- sem este NULL ele ficaria marcado como ausente para sempre.
        ausente_desde=NULL, updated_at=NOW()
"""


def run() -> int:
    hoje = date.today()
    progs = agrupa(_linhas(ARQUIVO), hoje)
    log.info(f"programas abertos hoje ({hoje:%d/%m/%Y}): {len(progs)}")

    # ⚠️ RODADA VAZIA NAO MARCA NADA COMO AUSENTE. Um download truncado, um
    # layout mudado ou uma queda do TransfereGov devolvem zero programa — e
    # marcar tudo ausente esvaziaria o radar inteiro por causa de uma falha
    # nossa. Sem dado, o certo e sair reclamando e deixar a tela como estava.
    if not progs:
        cn = psycopg2.connect(_dsn())
        cur = cn.cursor()
        cur.execute("INSERT INTO ingestion_log (source, status, records_inserted, "
                    "error_message, finished_at) VALUES (%s,'error',0,%s,NOW())",
                    (FONTE, "nenhum programa aberto encontrado — nada foi marcado "
                            "como ausente; suspeita de arquivo ou layout"))
        cn.commit()
        cur.close()
        cn.close()
        log.error("ZERO programas: NAO marquei ausencia. Confira o arquivo.")
        return 0

    cn = psycopg2.connect(_dsn())
    cur = cn.cursor()
    for p in progs.values():
        cur.execute(_SQL, (
            p["id_programa"], p["cod_programa"], p["nome"], p["orgao"], p["cod_orgao"],
            p["modalidade"], sorted(p["naturezas"]), sorted(p["ufs"]),
            p["acao_orcamentaria"], p["subtipo"], p["dt_ini_receb"], p["dt_fim_receb"],
            p["dt_ini_emenda"], p["dt_fim_emenda"], p["dt_disponibilizacao"],
            p["ano_disponibilizacao"], json.dumps(p["raw"], ensure_ascii=False)))
    cn.commit()

    # Quem nao apareceu nesta rodada sai das telas, mas fica no banco.
    cur.execute("UPDATE programas_captacao "
                "SET ausente_desde = COALESCE(ausente_desde, NOW()) "
                "WHERE ausente_desde IS NULL AND NOT (id_programa = ANY(%s))",
                (list(progs.keys()),))
    sumiram = cur.rowcount
    cn.commit()

    cur.execute("INSERT INTO ingestion_log (source, status, records_inserted, "
                "error_message, finished_at) VALUES (%s,'success',%s,%s,NOW())",
                (FONTE, len(progs),
                 f"{sumiram} programa(s) saiu(ram) do ar" if sumiram else None))
    cn.commit()
    cur.close()
    cn.close()
    log.info(f"radar: {len(progs)} programa(s) aberto(s), {sumiram} marcado(s) como ausente(s)")
    return len(progs)


if __name__ == "__main__":
    run()
