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

⭐ A TERCEIRA PORTA, BENEFICIARIO ESPECIFICO (17/09/2026). O programa ja nomeia
quem pode propor, e a lista mora em `siconv_programa_proponentes.zip`
(ID_PROGRAMA x ID_PROPONENTE; o CNPJ sai de `siconv_proponentes.zip`). Ate aqui
ela era descartada por falta desse cruzamento. Medido no dump de 17/09/2026, com
o recorte municipal: 112 programas abertos, 31 com a porta de beneficiario
aberta, e em 28 deles so ela. Nova Palma estava nomeada em 4 (Novo PAC Agua e
Esgoto entre eles), Santa Maria em 13, Monte Siao em 3, e nenhum aparecia.

⚠️ A MESMA LISTA SIGNIFICA COISAS DIFERENTES CONFORME A PORTA:
- beneficiario especifico: sao os NOMEADOS e ninguem propos ainda (Novo PAC Agua:
  5.623 listados, 0 propostas). Fora da lista, a porta nao abre.
- emenda: ~95% dos listados JA propuseram (Acao 00T1: 943 listados, 888
  propuseram). E quem teve emenda indicada, e a lista cresce durante a janela:
  estar fora dela NAO fecha a porta de emenda, so nao marca o municipio.
- recebimento: nenhum programa aberto hoje tem lista.
Por isso a coleta guarda a lista de CNPJs e quem decide e o router.

Rodar:  DATABASE_URL_SYNC=... python -u ingestion/programas_captacao.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime

import psycopg2

# ⚠️ SEM ESTA LINHA O COLETOR NAO SOBE DO JEITO QUE O CRON O CHAMA. O comando da
# Scheduled Task e `python -u ingestion/programas_captacao.py`, que poe
# `backend/ingestion/` em sys.path[0] — e nao `backend/`. Logo
# `import ingestion.transferegov_opendata` levanta ModuleNotFoundError na
# PRIMEIRA linha, antes de qualquer log: a task morre calada e a tabela fica
# vazia para sempre, sem uma linha em `ingestion_log` para acusar.
# Todos os outros coletores deste diretorio fazem exatamente isto (ver
# `fns_scraper.py`, `che_rs.py`, `convenios_rs.py`); este ficou de fora e o
# defeito so aparecia rodando o comando REAL, nao o `pytest`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.transferegov_opendata import _linhas  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("programas_captacao")

FONTE = "programas_captacao"
ARQUIVO = "siconv_programa.zip"
ARQUIVO_LISTA = "siconv_programa_proponentes.zip"
ARQUIVO_PROPONENTES = "siconv_proponentes.zip"

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
        # ⚠️ DUAS PORTAS, E O `continue` SO FECHA QUANDO AS DUAS ESTAO FECHADAS.
        #
        # Havia aqui `if fim is None or fim < hoje: continue`, olhando apenas
        # DT_PROG_FIM_RECEB_PROP. Medido no arquivo real em 02/09/2026, com o
        # mesmo recorte (DISPONIBILIZADO + natureza municipal): 17 programas com
        # recebimento aberto, 72 com emenda aberta, 112 na uniao. O radar
        # carregava 17 — 15% do que estava em pe. Por UF a distorcao e a que o
        # gestor sente: MG via 9 quando havia 35.
        #
        # E o descarte era ANTES de qualquer gravacao, entao nao era caso de
        # "temos e nao mostramos": os outros 95 nunca entravam no banco. A coleta
        # gravava `success` e ninguem tinha como perceber.
        #
        # ⚠️ AS DUAS PORTAS NAO SAO A MESMA COISA, e a distincao vai ate a tela.
        # Recebimento e proposta espontanea: a prefeitura protocola. Emenda
        # parlamentar depende de um deputado ou senador destinar o recurso — o
        # gestor NAO cumpre esse prazo sozinho. Listar as duas sem dizer qual e
        # qual faria o prefeito achar que basta protocolar, o que e pior que nao
        # mostrar. Por isso `portas` viaja junto com o programa.
        #
        # BENEF_ESP entra desde 17/09/2026 como a TERCEIRA porta, e a coleta a
        # guarda para todos. So o nomeado a ve: o router cruza o CNPJ do
        # municipio com `proponentes_cnpj` (ver `listas_de_proponentes`).
        fim = data_br(l.get("DT_PROG_FIM_RECEB_PROP"))
        ini = data_br(l.get("DT_PROG_INI_RECEB_PROP"))
        fim_em = data_br(l.get("DT_PROG_FIM_EMENDA_PAR"))
        ini_em = data_br(l.get("DT_PROG_INI_EMENDA_PAR"))
        fim_be = data_br(l.get("DT_PROG_FIM_BENEF_ESP"))
        ini_be = data_br(l.get("DT_PROG_INI_BENEF_ESP"))

        # "Aberta" e estar DENTRO da janela, e nao so antes do fim — o mesmo
        # criterio dos dois lados que o router ja aplicava ao recebimento.
        receb_aberta = fim is not None and fim >= hoje and (ini is None or ini <= hoje)
        emenda_aberta = fim_em is not None and fim_em >= hoje and (ini_em is None or ini_em <= hoje)
        benef_aberta = fim_be is not None and fim_be >= hoje and (ini_be is None or ini_be <= hoje)
        if not receb_aberta and not emenda_aberta and not benef_aberta:
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
                "dt_ini_receb": ini,
                "dt_fim_receb": fim,
                "dt_ini_emenda": ini_em,
                "dt_fim_emenda": fim_em,
                "dt_ini_benef": ini_be,
                "dt_fim_benef": fim_be,
                # ⚠️ QUAL PORTA ESTA ABERTA NAO E GRAVADO, e sim derivado das
                # datas no router. A tentacao e persistir "porta" aqui, mas seria
                # um "hoje" congelado: a coleta roda uma vez por dia e o valor
                # envelheceria entre uma rodada e outra, afirmando na tela que
                # uma janela esta aberta depois de ela fechar. As datas nao
                # envelhecem; a conclusao sobre elas, sim.
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
        # Encurtar o programa inteiro pela linha mais restritiva o faria sumir
        # da tela de quem ainda tem prazo. As UFs ficam no array; a data e a do
        # programa.
        #
        # ⚠️ E ISSO SO E HONESTO ENQUANTO AS DATAS NAO DIVERGIREM POR UF.
        # Medido em 02/09/2026: dos 17 programas abertos, ZERO trazem prazos
        # diferentes entre as UFs — a coluna e do programa, nao do par
        # (programa, UF). Se um dia divergir, guardar so a maior faria a tela
        # anunciar a um municipio um prazo que nao e dele, e a tabela teria de
        # passar a ser por (programa, UF). O `divergentes` abaixo existe para
        # esse dia CHEGAR COM AVISO em vez de em silencio.
        #
        # ⚠️ `fim` PODE SER None: programa aberto so por emenda ou por
        # beneficiario. Comparar None com data levantaria TypeError e derrubaria
        # a rodada inteira.
        if fim != p["dt_fim_receb"]:
            p["_prazos_divergentes"] = True
            if fim is not None and (p["dt_fim_receb"] is None or fim > p["dt_fim_receb"]):
                p["dt_fim_receb"] = fim

    divergentes = [p["id_programa"] for p in progs.values()
                   if p.pop("_prazos_divergentes", False)]
    if divergentes:
        log.warning(
            f"⚠️ {len(divergentes)} programa(s) com PRAZO DIFERENTE entre UFs "
            f"({', '.join(divergentes[:5])}). A tabela guarda um prazo por "
            f"PROGRAMA e passou a mostrar o mais longo para todas as UFs — "
            f"revise se a chave precisa virar (programa, UF).")
    return progs


def _int(x):
    try:
        return int(str(x).strip())
    except (TypeError, ValueError):
        return None


def cnpj_de(identif) -> str | None:
    """`IDENTIF_PROPONENTE` -> CNPJ de 14 digitos, ou None. Funcao PURA.

    Medido em 17/09/2026: 69.802 de 69.817 proponentes vem com 14 digitos; 14 vem
    com 9 caracteres nao numericos (CPF mascarado de pessoa fisica) e 1 com 12
    digitos, que e o CNPJ sem os zeros a esquerda.
    """
    d = "".join(ch for ch in str(identif or "") if ch.isdigit())
    if len(d) in (12, 13):
        d = d.zfill(14)
    return d if len(d) == 14 else None


def listas_de_proponentes(ids_programa, linhas_lista, linhas_proponentes) -> dict[str, list[str]] | None:
    """{id_programa: [CNPJ, ...]} dos programas pedidos que tem lista. PURA.

    Programa que nao aparece no arquivo nao tem lista (a chave fica de fora).
    Devolve **None** quando a leitura nao merece confianca, e o `run()` entao
    preserva a lista antiga em vez de gravar "sem lista":
    - uma coluna esperada sumiu do cabecalho (layout mudado);
    - a lista nao cita nenhum dos programas pedidos, ou nenhum proponente citado
      tem CNPJ no cadastro. Com 100+ programas abertos, zero e arquivo truncado,
      nao realidade: em 17/09/2026 eram 107 programas com lista.

    ⚠️ ESCONDER POR FALHA NOSSA E O PIOR RESULTADO AQUI. Sem lista, a porta de
    beneficiario some da tela de todo municipio. Por isso a falha preserva a
    lista antiga em vez de apaga-la.
    """
    ids = set(ids_programa)
    por_programa: dict[str, set[str]] = {}
    for l in linhas_lista:
        if "ID_PROGRAMA" not in l or "ID_PROPONENTE" not in l:
            log.error(f"{ARQUIVO_LISTA}: cabecalho sem ID_PROGRAMA/ID_PROPONENTE")
            return None
        pid = (l["ID_PROGRAMA"] or "").strip()
        if pid in ids:
            por_programa.setdefault(pid, set()).add((l["ID_PROPONENTE"] or "").strip())
    if ids and not por_programa:
        log.error(f"{ARQUIVO_LISTA}: nenhum dos {len(ids)} programas abertos tem lista — "
                  f"suspeita de arquivo truncado")
        return None

    procurados = set().union(*por_programa.values()) if por_programa else set()
    cnpj: dict[str, str] = {}
    for l in linhas_proponentes:
        if "ID_PROPONENTE" not in l or "IDENTIF_PROPONENTE" not in l:
            log.error(f"{ARQUIVO_PROPONENTES}: cabecalho sem ID_PROPONENTE/IDENTIF_PROPONENTE")
            return None
        i = (l["ID_PROPONENTE"] or "").strip()
        if i in procurados:
            c = cnpj_de(l["IDENTIF_PROPONENTE"])
            if c:
                cnpj[i] = c
    if procurados and not cnpj:
        log.error(f"{ARQUIVO_PROPONENTES}: nenhum dos {len(procurados)} proponentes "
                  f"listados tem CNPJ no cadastro — suspeita de arquivo truncado")
        return None

    return {pid: sorted({cnpj[i] for i in s if i in cnpj})
            for pid, s in por_programa.items()}


_SQL = """
    INSERT INTO programas_captacao
        (id_programa, cod_programa, nome, orgao, cod_orgao, modalidade,
         naturezas, ufs, acao_orcamentaria, subtipo, dt_ini_receb, dt_fim_receb,
         dt_ini_emenda, dt_fim_emenda, dt_disponibilizacao, ano_disponibilizacao,
         raw_data, dt_ini_benef, dt_fim_benef, proponentes_cnpj,
         visto_em, ausente_desde, updated_at)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,
            NOW(),NULL,NOW())
    ON CONFLICT (id_programa) DO UPDATE SET
        dt_ini_benef=EXCLUDED.dt_ini_benef, dt_fim_benef=EXCLUDED.dt_fim_benef,
        -- ⚠️ LISTA ILEGIVEL NESTA RODADA PRESERVA A ANTERIOR (o bind e
        -- `lista_ok`). Gravar NULL apagaria a porta de beneficiario de todo
        -- municipio por uma falha de download.
        proponentes_cnpj=CASE WHEN %s THEN EXCLUDED.proponentes_cnpj
                              ELSE programas_captacao.proponentes_cnpj END,
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


def hoje_br() -> date:
    """O "hoje" de Brasilia, e nao o do container.

    ⚠️ O CONTAINER RODA EM UTC e o pais que le a tela esta 3 horas atras. Entre
    21h e meia-noite de Brasilia o `date.today()` do container ja virou o dia —
    e um programa que fecha HOJE sumiria do radar na noite anterior, justamente
    nas horas em que alguem correndo atras do prazo iria olhar.

    Sem `zoneinfo` disponivel (imagem enxuta), cai no deslocamento fixo de -3h:
    o Brasil nao tem mais horario de verao desde 2019, entao o offset e estavel.
    """
    from datetime import datetime, timedelta, timezone
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    except Exception:
        return (datetime.now(timezone.utc) - timedelta(hours=3)).date()


def run() -> int:
    hoje = hoje_br()
    progs = agrupa(_linhas(ARQUIVO), hoje)
    log.info(f"programas abertos hoje ({hoje:%d/%m/%Y}): {len(progs)}")
    listas = None
    if progs:
        try:
            listas = listas_de_proponentes(progs.keys(), _linhas(ARQUIVO_LISTA),
                                           _linhas(ARQUIVO_PROPONENTES))
        except Exception as e:  # download ou zip ruim: o radar segue sem a lista nova
            log.error(f"listas de proponentes ilegiveis: {type(e).__name__}: {e}")
        if listas is not None:
            log.info(f"programas com lista de proponentes: {len(listas)}")

    # ⚠️ RODADA VAZIA NAO MARCA NADA COMO AUSENTE. Um download truncado, um
    # layout mudado ou uma queda do TransfereGov devolvem zero programa — e
    # marcar tudo ausente esvaziaria o radar inteiro por causa de uma falha
    # nossa. Sem dado, o certo e sair reclamando e deixar a tela como estava.
    cn = psycopg2.connect(_dsn())
    cur = cn.cursor()
    sumiram = 0
    parcial = None
    incompleta = None
    # ⚠️ UM `try/finally` PARA A LINHA DO `ingestion_log` SAIR SEMPRE. Sem ele,
    # excecao no meio (Postgres fora, `timeout` do cron, zip corrompido) saia
    # sem gravar nada — e o monitor de frescor nao ve rodada que nao logou: a
    # fonte envelheceria em silencio, o defeito que este arquivo existe para
    # nao repetir.
    try:
        if not progs:
            # ⚠️ RODADA VAZIA NAO MARCA NADA COMO AUSENTE. Download truncado,
            # layout mudado ou TransfereGov fora do ar devolvem zero programa —
            # marcar tudo ausente esvaziaria o radar inteiro por causa de uma
            # falha NOSSA. Sem dado, o certo e sair reclamando e deixar a tela
            # como estava.
            log.error("ZERO programas: NAO marquei ausencia. Confira o arquivo.")
            return 0

        for p in progs.values():
            cur.execute(_SQL, (
                p["id_programa"], p["cod_programa"], p["nome"], p["orgao"], p["cod_orgao"],
                p["modalidade"], sorted(p["naturezas"]), sorted(p["ufs"]),
                p["acao_orcamentaria"], p["subtipo"], p["dt_ini_receb"], p["dt_fim_receb"],
                p["dt_ini_emenda"], p["dt_fim_emenda"], p["dt_disponibilizacao"],
                p["ano_disponibilizacao"], json.dumps(p["raw"], ensure_ascii=False),
                p["dt_ini_benef"], p["dt_fim_benef"],
                (listas or {}).get(p["id_programa"]), listas is not None))
        cn.commit()

        # ⚠️ PISO PROPORCIONAL ANTES DE MARCAR AUSENCIA — nao basta guardar o
        # zero. A rodada vazia ja e barrada la em cima, mas o caso perigoso e o
        # PARCIAL: um arquivo truncado que descomprime e traz 2 dos 17
        # programas passa pelo `if not progs` e derruba 15 de uma vez. Ai o
        # radar esvazia quase todo, a tela diz "nenhum programa aberto para a
        # sua UF hoje" — frase que se le como informacao, nao como falha — e a
        # rodada seguinte demora um dia para ressuscitar. E o mesmo cuidado que
        # o `sismob_obras` ja toma; aqui ele faltava.
        cur.execute("SELECT count(*) FROM programas_captacao "
                    "WHERE ausente_desde IS NULL")
        ativos = (cur.fetchone() or [0])[0] or 0
        sumiram = 0
        if ativos and len(progs) < ativos * 0.5:
            log.error(
                f"⚠️ a rodada trouxe {len(progs)} programa(s) contra {ativos} "
                f"ativos no banco — queda de mais da metade. NAO marquei "
                f"ausencia: suspeita de arquivo parcial. Os dados novos foram "
                f"gravados; o que sumiu continua visivel ate a proxima rodada "
                f"confirmar.")
            parcial = (f"queda suspeita: {len(progs)} de {ativos} ativos — "
                       f"ausencia NAO marcada")
        else:
            parcial = None
            # Quem nao apareceu nesta rodada sai das telas, mas fica no banco.
            cur.execute("UPDATE programas_captacao "
                        "SET ausente_desde = COALESCE(ausente_desde, NOW()) "
                        "WHERE ausente_desde IS NULL AND NOT (id_programa = ANY(%s))",
                        (list(progs.keys()),))
            sumiram = cur.rowcount
        cn.commit()
        if listas is None:
            # ⚠️ NAO E 'success'. Os programas foram gravados, mas a porta de
            # beneficiario ficou com a lista da rodada anterior (ou sem nenhuma).
            aviso = "listas de proponentes ilegiveis — mantida a lista anterior"
            parcial = f"{parcial}; {aviso}" if parcial else aviso
        log.info(f"radar: {len(progs)} programa(s) aberto(s), "
                 f"{sumiram} marcado(s) como ausente(s)")
        return len(progs)
    except BaseException as e:  # inclui o SystemExit/KeyboardInterrupt do `timeout`
        incompleta = f"{type(e).__name__}: {e}"[:300]
        log.error(f"rodada interrompida: {incompleta}")
        raise
    finally:
        if incompleta:
            status, msg = "error", f"rodada interrompida ({incompleta})"
        elif not progs:
            status, msg = "error", ("nenhum programa aberto encontrado — nada foi "
                                    "marcado como ausente; suspeita de arquivo ou layout")
        else:
            # ⚠️ QUEDA SUSPEITA NAO E 'success'. A rodada gravou dado bom, mas
            # deixou de fazer metade do trabalho — e o monitor de frescor
            # precisa acusar isso, senao a unica pista fica num log que
            # ninguem le.
            status = "partial" if parcial else "success"
            msg = parcial or (f"{sumiram} programa(s) saiu(ram) do ar" if sumiram else None)
        # ⚠️ O ROLLBACK VAI NUM `try` PROPRIO — ver o mesmo bloco em `fns_faf`.
        # Junto do INSERT, uma falha dele levava embora a gravacao do log, que e
        # a unica coisa que este bloco existe para garantir.
        try:
            cn.rollback()  # limpa o que a excecao deixou pendente
        except Exception:
            pass
        try:
            cur.execute("INSERT INTO ingestion_log (source, status, records_inserted, "
                        "error_message, finished_at) VALUES (%s,%s,%s,%s,NOW())",
                        (FONTE, status, len(progs), msg))
            cn.commit()
        except Exception as e2:
            log.error(f"nao consegui gravar o ingestion_log: {e2}")
        for fechar in (cur.close, cn.close):
            try:
                fechar()
            except Exception:
                pass


# ⚠️ O `run_dadosabertos_cron` CHAMA `ingest()`, e nao `run()`. O laco dele faz
# `m.ingest()` por convencao; sem este nome o modulo entraria na lista e
# levantaria AttributeError, que o `except` do cron engole como aviso — a fonte
# ficaria "registrada" e nunca coletaria, sem nada acusando.
def ingest() -> int:
    """Nome que o cron de dados abertos procura. Devolve o total, como os irmaos."""
    return run()


if __name__ == "__main__":
    run()
