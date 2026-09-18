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

⭐ A FICHA DO PROGRAMA (18/09/2026, `ficha()`), o que a tela mostra ao clicar.
Etapa PROPRIA, com linha propria no `ingestion_log` (`programas_captacao_ficha`)
e auto-limite de 20h: o radar roda 4x/dia e a ficha le o `siconv_proposta`
(205 MB zipado, 13 s localmente), que muda uma vez por dia. Falha dela nao
mexe na lista, e vice-versa. Medido no dump de 18/09/2026, com 114 programas
abertos:
- EDICOES ANTERIORES por (orgao, nome sem o ano): 65 dos 114 tem. A chave por
  acao orcamentaria foi medida e DESCARTADA: `PACFIN25` junta Agua, Mobilidade e
  Drenagem, e `114420ZV` junta 64 programas de bancadas de estados diferentes.
- PROPOSTAS DE PREFEITURA: 22.138 na edicao aberta e 42.003 nas anteriores.
- APOIADORES: 5.311 indicacoes em 27 programas, 176 parlamentares/comissoes.

Rodar:  DATABASE_URL_SYNC=... python -u ingestion/programas_captacao.py
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import unicodedata
from datetime import date, datetime

import psycopg2
from psycopg2.extras import execute_values

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

from ingestion.transferegov_opendata import _linhas, _money  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("programas_captacao")

FONTE = "programas_captacao"
ARQUIVO = "siconv_programa.zip"
ARQUIVO_LISTA = "siconv_programa_proponentes.zip"
ARQUIVO_PROPONENTES = "siconv_proponentes.zip"

FONTE_FICHA = "programas_captacao_ficha"
ARQUIVO_PROGRAMA_PROPOSTA = "siconv_programa_proposta.zip"
ARQUIVO_PROPOSTA = "siconv_proposta.zip"
ARQUIVO_APOIADORES = "apoiadores_emendas_programas.zip"
FICHA_MIN_INTERVALO_H = float(os.getenv("PROGRAMAS_FICHA_MIN_INTERVAL_H", "20") or "20")
# Objeto mediano tem 66 caracteres e o maior, 4.978 (medido em 18/09/2026). A
# tela mostra exemplo, nao plano de trabalho.
OBJETO_MAX = 600
MUNICIPAL = "Administração Pública Municipal"

# ⚠️ CABECALHO CONFERIDO PELO NOME, coluna por coluna. O risco do dump e coluna
# renomeada, nao filtro ignorado: sem esta lista, um `.get()` de nome velho
# devolveria None em toda linha e a ficha sairia "sem proposta nenhuma".
COLUNAS_PROPOSTA = ("ID_PROPOSTA", "NATUREZA_JURIDICA", "SIT_PROPOSTA", "UF_PROPONENTE",
                    "COD_MUNIC_IBGE", "IDENTIF_PROPONENTE", "NM_PROPONENTE", "NR_PROPOSTA",
                    "ANO_PROP", "DIA_PROPOSTA", "VL_GLOBAL_PROP", "VL_REPASSE_PROP",
                    "VL_CONTRAPARTIDA_PROP", "OBJETO_PROPOSTA")
# ⚠️ SEM `CPF_PF_SOLICITANTE_APOIADORES_EMENDAS` DE PROPOSITO: e CPF de pessoa
# fisica, nenhuma tela usa, e o que nao se le nao vaza (LGPD).
COLUNAS_APOIADORES = ("ID_PROGRAMA", "NUMERO_EMENDA_APOIADORES_EMENDAS",
                      "NOME_PARLAMENTAR_APOIADORES_EMENDAS",
                      "PARLAMENTAR_SOLICITANTE_APOIADORES_EMENDAS",
                      "INDICACAO_APOIADORES_EMENDAS", "CNPJ_PROPONENTE_APOIADORES_EMENDAS",
                      "NOME_PROPONENTE_APOIADORES_EMENDAS",
                      "VALOR_REPASSE_PROPOSTA_APOIADORES_EMENDAS")

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


# ------------------------------------------------------------------ ficha ---

def _faltam(linha: dict, colunas) -> list[str]:
    return [c for c in colunas if c not in linha]


def nome_chave(nome) -> str:
    """O nome do programa sem acento, caixa, pontuacao e ANO. Funcao PURA.

    "Novo PAC - Mobilidade Urbana Sustentavel" de 2024, 2025 e 2026 viram a mesma
    chave; "... 2025" e "... 2026" tambem. Nome que o dump publica com `?` no
    lugar do acento ("AGROPECU?RIO") nao casa com o grafado certo — perde-se uma
    edicao, mas nunca se casa programa errado.
    """
    s = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"\b(19|20)\d\d\b", " ", s)
    return re.sub(r"[^A-Z0-9]+", " ", s).strip()


def edicoes_anteriores(abertos: dict[str, tuple[str, str]], linhas) -> dict[str, list[dict]] | None:
    """{id_aberto: [{id, ano, nome}, ...]} — as outras edicoes de cada programa
    aberto: mesmo orgao, mesmo `nome_chave`, id diferente e fora da lista de
    abertos. PURA. `abertos` e {id: (cod_orgao, nome)}.

    Todo aberto sai no resultado, com lista vazia quando nao ha edicao: vazio e
    "olhamos e nao ha", e o router so o diz porque `ficha_em` esta preenchido.
    Devolve None quando o cabecalho mudou.
    """
    dono: dict[tuple[str, str], list[str]] = {}
    for pid, (orgao, nome) in abertos.items():
        k = ((orgao or "").strip(), nome_chave(nome))
        if k[1]:
            dono.setdefault(k, []).append(pid)
    achados: dict[str, dict[str, dict]] = {pid: {} for pid in abertos}
    for i, l in enumerate(linhas):
        if i == 0 and _faltam(l, ("ID_PROGRAMA", "NOME_PROGRAMA", "COD_ORGAO_SUP_PROGRAMA")):
            log.error(f"{ARQUIVO}: cabecalho sem as colunas da edicao anterior")
            return None
        pid = (l["ID_PROGRAMA"] or "").strip()
        if not pid or pid in abertos:
            continue
        k = ((l["COD_ORGAO_SUP_PROGRAMA"] or "").strip(), nome_chave(l["NOME_PROGRAMA"]))
        for aberto in dono.get(k, ()):
            # O arquivo repete o programa uma vez por UF: fica a primeira.
            achados[aberto].setdefault(pid, {
                "id": pid, "ano": _int(l.get("ANO_DISPONIBILIZACAO")),
                "nome": (l["NOME_PROGRAMA"] or "").strip()})
    return {pid: sorted(v.values(), key=lambda e: (-(e["ano"] or 0), e["id"]))
            for pid, v in achados.items()}


def fase(situacao) -> str:
    """SIT_PROPOSTA -> aprovada | rejeitada | andamento. PURA.

    ⚠️ "Proposta Aprovada e Plano de Trabalho em Analise" E APROVADA: a proposta
    passou, falta o plano. Contar como andamento esconderia 3.961 aprovacoes num
    recorte de 102 mil propostas medido em 18/09/2026.
    "Eliminada em Chamamento Publico" e rejeicao. "Cadastrados" (rascunho que
    nao foi enviado) e andamento: nao foi decidido.
    """
    s = str(situacao or "").strip().lower()
    if "rejeitad" in s or "eliminad" in s:
        return "rejeitada"
    if s.startswith("proposta/plano de trabalho aprovad") or s.startswith("proposta aprovada"):
        return "aprovada"
    return "andamento"


def ligar_propostas(linhas, alvo) -> dict[str, set[str]] | None:
    """{id_proposta: {id_programa, ...}} das propostas dos programas em `alvo`. PURA."""
    alvo = set(alvo)
    ligadas: dict[str, set[str]] = {}
    for i, l in enumerate(linhas):
        if i == 0 and _faltam(l, ("ID_PROGRAMA", "ID_PROPOSTA")):
            log.error(f"{ARQUIVO_PROGRAMA_PROPOSTA}: cabecalho sem ID_PROGRAMA/ID_PROPOSTA")
            return None
        pid = (l["ID_PROGRAMA"] or "").strip()
        if pid in alvo:
            ligadas.setdefault((l["ID_PROPOSTA"] or "").strip(), set()).add(pid)
    return ligadas


def propostas_de_prefeitura(linhas, ligadas: dict[str, set[str]]) -> list[tuple] | None:
    """As linhas de `programas_captacao_propostas`, uma por (programa, proposta). PURA.

    So natureza municipal (ver a migration). Devolve None quando o cabecalho mudou.
    """
    saida: list[tuple] = []
    for i, l in enumerate(linhas):
        if i == 0 and _faltam(l, COLUNAS_PROPOSTA):
            log.error(f"{ARQUIVO_PROPOSTA}: faltam {_faltam(l, COLUNAS_PROPOSTA)}")
            return None
        ip = (l["ID_PROPOSTA"] or "").strip()
        progs = ligadas.get(ip)
        if not progs or (l["NATUREZA_JURIDICA"] or "").strip() != MUNICIPAL:
            continue
        sit = (l["SIT_PROPOSTA"] or "").strip()
        base = (ip, _int(l["ANO_PROP"]), data_br(l["DIA_PROPOSTA"]),
                (l["UF_PROPONENTE"] or "").strip().upper()[:2] or None,
                (l["COD_MUNIC_IBGE"] or "").strip()[:7] or None,
                cnpj_de(l["IDENTIF_PROPONENTE"]),
                (l["NM_PROPONENTE"] or "").strip() or None,
                (l["NR_PROPOSTA"] or "").strip()[:30] or None,
                sit or None, fase(sit),
                _money(l["VL_GLOBAL_PROP"]), _money(l["VL_REPASSE_PROP"]),
                _money(l["VL_CONTRAPARTIDA_PROP"]),
                (l["OBJETO_PROPOSTA"] or "").strip()[:OBJETO_MAX] or None)
        for pid in sorted(progs):
            saida.append((pid,) + base)
    return saida


def apoiadores_dos_abertos(linhas, abertos) -> list[dict] | None:
    """As indicacoes de emenda dos programas abertos. PURA. None = cabecalho mudou."""
    abertos = set(abertos)
    saida: list[dict] = []
    for i, l in enumerate(linhas):
        if i == 0 and _faltam(l, COLUNAS_APOIADORES):
            log.error(f"{ARQUIVO_APOIADORES}: faltam {_faltam(l, COLUNAS_APOIADORES)}")
            return None
        pid = (l["ID_PROGRAMA"] or "").strip()
        if pid not in abertos:
            continue
        saida.append({
            "id_programa": pid,
            "nr_emenda": (l["NUMERO_EMENDA_APOIADORES_EMENDAS"] or "").strip()[:20] or None,
            "parlamentar": (l["NOME_PARLAMENTAR_APOIADORES_EMENDAS"] or "").strip() or None,
            "solicitante": (l["PARLAMENTAR_SOLICITANTE_APOIADORES_EMENDAS"] or "").strip() or None,
            "indicacao": (l["INDICACAO_APOIADORES_EMENDAS"] or "").strip()[:40] or None,
            "cnpj": cnpj_de(l["CNPJ_PROPONENTE_APOIADORES_EMENDAS"]),
            "proponente": (l["NOME_PROPONENTE_APOIADORES_EMENDAS"] or "").strip() or None,
            "valor": _money(l["VALOR_REPASSE_PROPOSTA_APOIADORES_EMENDAS"]),
        })
    return saida


def ufs_por_cnpj(linhas, cnpjs) -> dict[str, str] | None:
    """{CNPJ: UF} dos proponentes pedidos, do cadastro `siconv_proponentes`. PURA.

    O arquivo de apoiadores nao traz UF, e "quem indica na sua UF" depende dela.
    Medido em 18/09/2026: os 3.150 CNPJs indicados estao todos no cadastro.
    """
    cnpjs = set(cnpjs)
    saida: dict[str, str] = {}
    for i, l in enumerate(linhas):
        if i == 0 and _faltam(l, ("IDENTIF_PROPONENTE", "UF_PROPONENTE")):
            log.error(f"{ARQUIVO_PROPONENTES}: cabecalho sem IDENTIF_PROPONENTE/UF_PROPONENTE")
            return None
        c = cnpj_de(l["IDENTIF_PROPONENTE"])
        if c in cnpjs:
            saida[c] = (l["UF_PROPONENTE"] or "").strip().upper()[:2]
    return saida


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


# Horas desde a ficha MAIS VELHA entre os programas ativos; NULL quando algum
# ainda nao tem ficha (programa publicado depois da ultima montagem) — ai monta
# de novo sem esperar as 20h, senao o programa novo ficaria um dia sem ficha.
_SQL_IDADE_FICHA = """
    SELECT CASE WHEN bool_or(ficha_em IS NULL) THEN NULL
                ELSE EXTRACT(EPOCH FROM NOW() - min(ficha_em)) / 3600 END
      FROM programas_captacao WHERE ausente_desde IS NULL
"""

_COLS_PROPOSTAS = ("id_programa, id_proposta, ano, dt_proposta, uf, ibge, cnpj, proponente, "
                   "nr_proposta, situacao, fase, vl_global, vl_repasse, vl_contrapartida, objeto")
_COLS_APOIADORES = ("id_programa, nr_emenda, parlamentar, solicitante, indicacao, cnpj, "
                    "proponente, uf, valor")


def _troca(cur, tabela: str, colunas: str, linhas: list[tuple]) -> None:
    """Troca a tabela inteira. Chamada DENTRO da transacao da montagem: quem le
    no meio ve a versao antiga inteira (MVCC), nunca metade."""
    cur.execute(f"DELETE FROM {tabela}")
    if linhas:
        execute_values(cur, f"INSERT INTO {tabela} ({colunas}) VALUES %s", linhas,
                       page_size=1000)


def ficha(forcar: bool = False) -> str | None:
    """Monta a ficha dos programas ativos. Devolve o status gravado no
    `ingestion_log`, ou None quando o auto-limite de 20h pulou a rodada.

    Duas partes independentes, e o status diz qual falhou:
    - PROPOSTAS + EDICOES (`siconv_programa`, `siconv_programa_proposta`,
      `siconv_proposta`): sem elas nao ha ficha, e `ficha_em` NAO avanca —
      a tela continua dizendo "ficha pendente" em vez de "ninguem propos".
      Falha = 'error'.
    - APOIADORES (`apoiadores_emendas_programas` + UF de `siconv_proponentes`):
      falha preserva a tabela anterior e sai 'partial'.
    """
    cn = psycopg2.connect(_dsn())
    cur = cn.cursor()
    status, avisos, gravadas = None, [], 0
    try:
        cur.execute(_SQL_IDADE_FICHA)
        idade = (cur.fetchone() or [None])[0]
        if not forcar and idade is not None and float(idade) < FICHA_MIN_INTERVALO_H:
            log.info(f"ficha montada ha {float(idade):.1f}h — pulo (limite "
                     f"{FICHA_MIN_INTERVALO_H:.0f}h)")
            return None

        status = "error"
        cur.execute("SELECT id_programa, cod_orgao, nome FROM programas_captacao "
                    "WHERE ausente_desde IS NULL")
        abertos = {r[0]: (r[1] or "", r[2] or "") for r in cur.fetchall()}
        if not abertos:
            avisos.append("nenhum programa ativo no banco — nada a montar")
            return status

        edicoes = propostas = None
        try:
            edicoes = edicoes_anteriores(abertos, _linhas(ARQUIVO))
            if edicoes is not None:
                alvo = set(abertos) | {e["id"] for es in edicoes.values() for e in es}
                ligadas = ligar_propostas(_linhas(ARQUIVO_PROGRAMA_PROPOSTA), alvo)
                if ligadas is not None:
                    propostas = propostas_de_prefeitura(_linhas(ARQUIVO_PROPOSTA), ligadas)
        except Exception as e:  # download ou zip ruim
            log.error(f"propostas ilegiveis: {type(e).__name__}: {e}")
        # ⚠️ ZERO PROPOSTA DE PREFEITURA EM 100+ PROGRAMAS E ARQUIVO RUIM, nao
        # realidade (eram 64 mil em 18/09/2026). Trocar a tabela por vazio faria
        # toda ficha dizer "ninguem propos" — pior que a ficha de ontem.
        if not propostas:
            avisos.append("propostas ilegiveis ou vazias — ficha anterior mantida")
            propostas = None

        apoio = None
        try:
            apoio = apoiadores_dos_abertos(_linhas(ARQUIVO_APOIADORES), abertos)
            if apoio:
                ufs = ufs_por_cnpj(_linhas(ARQUIVO_PROPONENTES),
                                   {a["cnpj"] for a in apoio if a["cnpj"]})
                if ufs is None:
                    apoio = None
                else:
                    for a in apoio:
                        a["uf"] = ufs.get(a["cnpj"]) or None
        except Exception as e:
            log.error(f"apoiadores ilegiveis: {type(e).__name__}: {e}")
            apoio = None
        if apoio == []:
            # ⚠️ Vazio pode ser real (fora da temporada de emenda), mas tambem
            # arquivo truncado. Com indicacao gravada da rodada anterior, a
            # duvida fica com o dado antigo — o router so o mostra para programa
            # que continua aberto.
            cur.execute("SELECT count(*) FROM programas_captacao_apoiadores")
            if ((cur.fetchone() or [0])[0] or 0) > 0:
                avisos.append("zero indicacao de emenda nos programas abertos — "
                              "mantidas as da rodada anterior")
                apoio = None
        elif apoio is None:
            avisos.append("apoiadores de emenda ilegiveis — mantidos os anteriores")

        if propostas is not None:
            _troca(cur, "programas_captacao_propostas", _COLS_PROPOSTAS, propostas)
            cur.executemany(
                "UPDATE programas_captacao SET edicoes_anteriores = %s::jsonb, "
                "ficha_em = NOW() WHERE id_programa = %s",
                [(json.dumps(es, ensure_ascii=False), pid) for pid, es in edicoes.items()])
            gravadas = len(propostas)
        if apoio is not None:
            _troca(cur, "programas_captacao_apoiadores", _COLS_APOIADORES,
                   [tuple(a.get(c.strip()) for c in _COLS_APOIADORES.split(","))
                    for a in apoio])
        cn.commit()
        status = "error" if propostas is None else ("partial" if avisos else "success")
        log.info(f"ficha: {gravadas} proposta(s) de prefeitura, "
                 f"{len(apoio) if apoio is not None else '—'} indicacao(oes) de emenda, "
                 f"{sum(1 for es in (edicoes or {}).values() if es)} programa(s) com "
                 f"edicao anterior")
        return status
    except BaseException as e:
        status = "error"
        avisos.append(f"rodada interrompida ({type(e).__name__}: {e})"[:300])
        raise
    finally:
        if status is not None:
            try:
                cn.rollback()
            except Exception:
                pass
            try:
                cur.execute("INSERT INTO ingestion_log (source, status, records_inserted, "
                            "error_message, finished_at) VALUES (%s,%s,%s,%s,NOW())",
                            (FONTE_FICHA, status, gravadas, "; ".join(avisos) or None))
                cn.commit()
            except Exception as e2:
                log.error(f"nao consegui gravar o ingestion_log da ficha: {e2}")
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
    """Nome que o cron de dados abertos procura. Devolve o total, como os irmaos.

    A ficha vem DEPOIS da lista e so com lista gravada: ela monta sobre os
    programas ativos no banco. Falha dela nao muda o que o `run()` devolve —
    tem linha propria no `ingestion_log`.
    """
    n = run()
    if n:
        try:
            ficha()
        except Exception as e:
            log.error(f"ficha falhou: {type(e).__name__}: {e}")
    return n


if __name__ == "__main__":
    ingest()
