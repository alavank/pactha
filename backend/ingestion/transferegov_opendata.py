"""Ingestao das Transferencias Voluntarias via DADOS ABERTOS (HTTP, sem navegador).

===========================================================================
O QUE ESTE MODULO E, E O QUE ELE NAO E
===========================================================================
Ele preenche a CAMADA BASE de `transferegov_propostas` -- tudo o que o portal
publica em CSV -- sem abrir Chromium. NAO substitui o
`transferegov_voluntarias.py` por inteiro: sobra uma fatia pequena que so
existe atras do login gov.br (historico de comunicacoes na area /private/ das
mandatarias, documentos do quadro resumo, contagem de processos de execucao).
Essa fatia continua com navegador, mas passa a ser o unico motivo para abri-lo.

Por que fazer assim, e nao um big-bang: rodando PRIMEIRO o dado aberto, a base
fica completa mesmo que o scraper autenticado falhe -- e ele falha com
frequencia, porque depende de sessao gov.br viva. Hoje acontece o inverso: se o
navegador trava, NADA e atualizado.

===========================================================================
POR QUE O DADO ABERTO E MAIS FIEL, E NAO SO MAIS BARATO
===========================================================================
O precedente esta no proprio repo: `fns_scraper.py` saiu do Playwright para
httpx e registrou "cobertura Piracema 49% -> 99%". O navegador PERDIA metade
dos registros por falha de paginacao e timeout.

Aqui o problema medido (auditoria de 2026-07-23) era pior: a rodada do
`transferegov_voluntarias` era abortada aos 3600s tendo percorrido cerca de 10
de 41 municipios, SEMPRE na mesma ordem alfabetica. Municipios da letra D em
diante nunca eram atualizados -- e o painel mostrava dado velho sem avisar.
Um CSV completo nao tem paginacao para falhar.

===========================================================================
DE ONDE VEM CADA CAMPO
===========================================================================
  siconv_proposta          -> numero_proposta, situacao, orgao, proponente,
                              identificacao, modalidade, objeto, vigencia,
                              dt_proposta, valores, id_proposta_siconv
                              (filtra por COD_MUNIC_IBGE -- mais confiavel que
                              casar CNPJ, que era o criterio do scraper)
  siconv_convenio          -> codigo_instrumento, situacao_siafi,
                              numero_processo, dt_assinatura, vigencia do
                              convenio, situacao_contratacao e clausula
                              suspensiva (data + motivo)
  siconv_emenda            -> parlamentar
  siconv_programa_proposta
    + siconv_programa      -> programa

NAO existe no dado aberto (o UPSERT usa COALESCE, entao o que o scraper
autenticado ja coletou e PRESERVADO): possui_parecer, processo_execucao_qtd,
historico_comunicacoes, documentos_quadro_resumo, situacao_contratacao_detalhe.

ATENCAO AO PRAZO: o ambiente antigo de dados abertos do TransfereGov e
DESLIGADO em 31/08/2026. Este modulo ja usa o endereco novo.

===========================================================================
IMPACTO NA PRIMEIRA RODADA (validado contra 3.140 registros reais do Freitas,
comparando campo a campo com o que o scraper ja gravou -- LER antes de ligar)
===========================================================================
A nova ingestao CORRIGE dados que o scraper de navegador gravou errado. Isso
significa que a primeira rodada MUDA numeros do painel do prefeito -- e esperado
e correto, mas quem cuida do painel deve saber:

 * VALORES trocados: o scraper gravou o REPASSE na coluna valor_global e a
   CONTRAPARTIDA em valor_repasse (medido: 2.817 de 3.140 divergem). O CSV
   oficial e coerente (repasse + contrapartida = global). Ao ligar, o total de
   "valor global" do painel sobe ~R$ 117 mi de uma vez, sem proposta nova --
   nenhum dado foi inventado, o antigo e que estava trocado.
 * MODALIDADE: ~950 linhas do banco tem lixo com TAB ("Contrato de Repasse\t
   Enviada para mandataria?..."). O dado aberto traz limpa.
 * SITUACAO: com convenio celebrado, passa a refletir a situacao do INSTRUMENTO
   (Em execucao / Prestacao de Contas / Anulado), como o portal mostra. Sem
   isso, convenios encerrados apareciam como "proposta em analise".

Rode com TG_OPENDATA_DRY_RUN=1 antes de ligar em producao. A guarda de
completude (TG_GUARD_MIN_RATIO) aborta se a coleta vier suspeitosamente menor
que o banco -- protege contra queda silenciosa da fonte.

Uso:  python -m ingestion.transferegov_opendata [municipio_id]
      TG_OPENDATA_DRY_RUN=1 coleta e relata SEM gravar.
"""
import csv
import io
import json
import logging
import os
import sys
import time
import zipfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tg_opendata")

BASE = os.getenv(
    "TRANSFEREGOV_DADOS_URL",
    "https://api-publica.transferegov.gestao.gov.br/downloads/dadosgov",
).rstrip("/")

_CACHE_DIR = os.getenv("SICONV_CACHE_DIR") or os.path.join(
    os.getenv("TEMP") or os.getenv("TMPDIR") or "/tmp", "siconv_opendata"
)
_CACHE_HORAS = int(os.getenv("TRANSFEREGOV_CACHE_HORAS", "20") or "20")

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def _db_url() -> str:
    return (os.getenv("DATABASE_URL_SYNC", "")
            .replace("&channel_binding=require", "").replace("?channel_binding=require", ""))


def _numero_proposta(bruto: str | None) -> str | None:
    """Normaliza NR_PROPOSTA para o formato da CHAVE ja gravada: 6 digitos com
    zero a esquerda + '/' + ano. Ex.: '2/2016' -> '000002/2016'.

    ISTO E CRITICO, NAO COSMETICO. A tabela tem UNIQUE (municipio_id,
    numero_proposta) e o UPSERT depende dela. O portal .jsf exibe o numero
    preenchido e foi assim que o scraper gravou as 3.158 linhas; o CSV traz sem
    preenchimento. Sem normalizar, medido em producao: apenas 114 de 3.158
    casariam -- o ON CONFLICT nunca dispararia e a ingestao INSERIRIA 3.332
    linhas duplicadas, deixando as 3.044 originais orfas e desatualizadas na
    tabela que alimenta o painel do prefeito. Os 114 que casavam eram so os que
    ja tinham 6 digitos naturalmente.
    """
    s = (bruto or "").strip()
    if not s or "/" not in s:
        return s or None
    numero, _, ano = s.partition("/")
    numero, ano = numero.strip(), ano.strip()
    if not numero.isdigit():
        return s
    return f"{numero.zfill(6)}/{ano}"


def _cnpj(bruto: str | None) -> str | None:
    """14 digitos -> 00.000.000/0000-00 (formato que o scraper ja gravava)."""
    s = "".join(c for c in (bruto or "") if c.isdigit())
    if len(s) != 14:
        return (bruto or "").strip() or None
    return f"{s[:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:]}"


def _processo(bruto: str | None) -> str | None:
    """17 digitos -> 00000.000000/0000-00 (numero unico de protocolo)."""
    s = "".join(c for c in (bruto or "") if c.isdigit())
    if len(s) != 17:
        return (bruto or "").strip() or None
    return f"{s[:5]}.{s[5:11]}/{s[11:15]}-{s[15:]}"


# Modalidade: o CSV traz em caixa alta (CONVENIO), o portal/banco em Title Case
# com acento (Convenio -> "Convênio"). Traduzir mantem os filtros do painel.
# NOTA: no banco esta coluna esta parcialmente CORROMPIDA -- o scraper capturou a
# celula errada e colou lixo com TAB ("Contrato de Repasse\tEnviada para
# mandataria?\tNao\tSituacao no SIAFI\t..."), em ~950 linhas. O dado aberto traz
# a modalidade LIMPA; as divergencias contra o banco nesse campo sao, na maioria,
# correcao desse lixo -- por isso NAO tentamos reproduzir o formato do banco aqui.
_MODALIDADE = {
    "CONVENIO": "Convênio",
    "CONTRATO DE REPASSE": "Contrato de Repasse",
    "CONVENIO OU CONTRATO DE REPASSE": "Convênio ou Contrato de Repasse",
    "TERMO DE COMPROMISSO": "Termo de Compromisso",
    "TERMO DE COLABORACAO": "Termo de Colaboração",
    "TERMO DE FOMENTO": "Termo de Fomento",
    "TERMO DE PARCERIA": "Termo de Parceria",
    "TERMO DE EXECUCAO DESCENTRALIZADA": "Termo de Execução Descentralizada",
}
_modalidades_desconhecidas: set[str] = set()


def _modalidade(bruta: str | None) -> str | None:
    s = (bruta or "").strip()
    if not s:
        return None
    if s.upper() in _MODALIDADE:
        return _MODALIDADE[s.upper()]
    if s not in _modalidades_desconhecidas:
        _modalidades_desconhecidas.add(s)
        logger.warning(f"  modalidade desconhecida no dado aberto: '{s}' -- gravando como veio")
    return s


# Situacao: quando a proposta virou convenio, o portal (e o scraper) mostram a
# situacao DO CONVENIO, nao a da proposta. Estes rotulos do CSV diferem do que o
# banco tem em poucos casos -- mapa DERIVADO da comparacao dos valores distintos
# dos dois lados (banco x SIT_CONVENIO/SIT_PROPOSTA do Freitas).
_SITUACAO = {
    "Convênio Anulado": "Instrumento Anulado",
    "Convênio Rescindido": "Instrumento Rescindido",
    "Cancelado": "Instrumento Anulado",
    "Inadimplente": "INADIMPLENTE",
    "Prestação de Contas Comprovada em Análise": "Prestação de Contas Comprovada - Em Análise",
    "Proposta/Plano de Trabalho Enviado para Análise": "Proposta/Plano de Trabalho enviado para Análise",
    "Proposta/Plano de Trabalho Complementado Enviado para Análise": "Proposta/Plano de Trabalho complementado enviada para Análise",
    "Proposta/Plano de Trabalho Complementado em Análise": "Proposta/Plano de Trabalho complementado em Análise",
    "Proposta/Plano de Trabalho Aprovado": "Proposta/Plano de Trabalho Aprovados",
    "Proposta Aprovada e Plano de Trabalho Complementado Enviado para Análise": "Proposta Aprovada e Plano de Trabalho Complementado enviado para Análise",
}


def _situacao(sit_proposta: str | None, sit_convenio: str | None) -> str | None:
    """Se ha convenio celebrado (SIT_CONVENIO preenchido), a situacao vem dele --
    e o que o portal mostra e o que enche as abas 'Em execucao'/'Encerradas' do
    painel. Senao, usa a situacao da proposta. Traduz os rotulos divergentes."""
    bruta = (sit_convenio or "").strip() or (sit_proposta or "").strip()
    if not bruta:
        return None
    return _SITUACAO.get(bruta, bruta)


def _orgao(cod: str | None, desc: str | None) -> str | None:
    """Reproduz o formato do scraper: 'CODIGO - NOME' (ex.: '36211 - FUNASA').
    O banco tem o codigo colado no rotulo; manter isso evita dois vocabularios
    de orgao convivendo no painel."""
    c = (cod or "").strip()
    d = (desc or "").strip()
    if c and d:
        return f"{c} - {d}"
    return d or None


def _money(v) -> float | None:
    s = (str(v) if v is not None else "").strip()
    if not s:
        return None
    s = s.replace("R$", "").replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


_datas_invalidas: set[str] = set()


def _data(v) -> str | None:
    """Normaliza para dd/mm/aaaa, o formato que o scraper ja gravava nas colunas
    de data (VARCHAR, nao DATE -- nao mexer nisso agora).

    Se a string nao for uma data reconhecivel, devolve None e LOGA (uma vez por
    valor). O fallback antigo `return s` gravava a string crua e foi o que
    transformou o bug do DIA_PROP='11' em falha silenciosa -- '11' passava como
    se fosse data. Agora um formato inesperado vira NULL visivel + aviso, nao
    lixo mascarado."""
    s = (str(v) if v is not None else "").strip()
    if not s:
        return None
    s = s.split(" ")[0]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    if s not in _datas_invalidas:
        _datas_invalidas.add(s)
        logger.warning(f"  valor de data nao reconhecido: '{s}' -- gravando NULL")
    return None


def _data_iso(v) -> str | None:
    """Para colunas DATE de verdade (clausula_suspensiva_dt_prevista)."""
    s = (str(v) if v is not None else "").strip().split(" ")[0]
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- download --

def _baixa(nome: str) -> str:
    """Baixa <nome>.zip para o cache e devolve o caminho local.

    Grava em disco de proposito: siconv_proposta.csv tem 751 MB
    descomprimido. O zipfile precisa de arquivo posicionavel para descomprimir
    em STREAM, sem carregar tudo na RAM -- o que importa numa maquina de
    7,6 GB compartilhada por 43 containers.
    """
    import httpx
    os.makedirs(_CACHE_DIR, exist_ok=True)
    destino = os.path.join(_CACHE_DIR, nome)
    if os.path.exists(destino) and os.path.getsize(destino) > 1000:
        idade_h = (time.time() - os.path.getmtime(destino)) / 3600
        if idade_h < _CACHE_HORAS:
            logger.info(f"  {nome}: cache de {idade_h:.1f}h")
            return destino

    logger.info(f"  baixando {nome} ...")
    # O .part leva o PID porque o cache pode ser um diretorio COMPARTILHADO entre
    # os workers dos 3 tenants (bind mount). Sem isso, dois downloads simultaneos
    # escreveriam no mesmo arquivo temporario e o resultado seria um zip corrompido
    # -- que quebraria a ingestao dos tres de uma vez. O os.replace no fim e
    # atomico, entao o "ultimo a terminar vence" e sempre deixa um arquivo integro.
    parcial = f"{destino}.{os.getpid()}.part"
    try:
        with httpx.stream("GET", f"{BASE}/{nome}", timeout=1800, follow_redirects=True) as r:
            r.raise_for_status()
            with open(parcial, "wb") as fh:
                for bloco in r.iter_bytes(1024 * 512):
                    fh.write(bloco)
        # Nao aceita download truncado: um zip cortado explodiria so la na frente,
        # no meio do parse, com erro confuso.
        if os.path.getsize(parcial) < 1000:
            raise OSError(f"download de {nome} veio vazio/truncado")
        os.replace(parcial, destino)
    finally:
        if os.path.exists(parcial):
            try:
                os.remove(parcial)
            except OSError:
                pass
    logger.info(f"  {nome}: {os.path.getsize(destino):,} bytes")
    return destino


def _linhas(nome: str):
    """Itera o CSV de dentro do zip como dicts, em stream.

    ENCODING: os arquivos sao UTF-8 COM BOM. Ler como latin-1 produz FALHA
    SILENCIOSA -- o BOM entra no nome da primeira coluna (`ï»¿ID_PROPOSTA`),
    todo .get() devolve None e a ingestao "conclui" trazendo zero. Este erro
    foi cometido e detectado na migracao do PAC; nao repetir.
    """
    caminho = _baixa(nome)
    with zipfile.ZipFile(caminho) as z:
        interno = z.namelist()[0]
        with z.open(interno) as bruto:
            texto = io.TextIOWrapper(bruto, encoding="utf-8-sig", errors="replace", newline="")
            leitor = csv.DictReader(texto, delimiter=";")
            if leitor.fieldnames:
                leitor.fieldnames = [c.strip().lstrip("﻿") for c in leitor.fieldnames]
            for linha in leitor:
                yield linha


# ------------------------------------------------------------- municipios ---

def _municipios(municipio_id=None) -> list[dict]:
    import psycopg2
    conn = psycopg2.connect(_db_url())
    cur = conn.cursor()
    if municipio_id:
        cur.execute("SELECT id, nome, uf, ibge_code FROM municipios WHERE id=%s", (int(municipio_id),))
    else:
        cur.execute("SELECT id, nome, uf, ibge_code FROM municipios WHERE active=true ORDER BY nome")
    muns = [{"id": r[0], "nome": r[1], "uf": r[2], "ibge": (r[3] or "").strip()} for r in cur.fetchall()]
    cur.close()
    conn.close()
    return muns


# ---------------------------------------------------------------- coleta ----

def _coleta(muns: list[dict]) -> dict[int, list[dict]]:
    por_ibge = {m["ibge"]: m["id"] for m in muns if m.get("ibge")}
    sem_ibge = [m["nome"] for m in muns if not m.get("ibge")]
    if sem_ibge:
        logger.warning(f"  {len(sem_ibge)} municipio(s) SEM ibge_code ficam de fora: {sem_ibge[:6]}")
    if not por_ibge:
        logger.error("  nenhum municipio com ibge_code - nada a fazer")
        return {}

    # Rascunhos que o portal .jsf NAO lista (e que o scraper nunca via). Manter
    # a paridade evita encher o painel com propostas que o municipio comecou e
    # nunca enviou. Ajustavel por env.
    _ignora_sit = {s.strip() for s in (os.getenv(
        "TG_IGNORA_SITUACOES",
        "Proposta/Plano de Trabalho Cadastrados|Proposta Eliminada em Chamamento Público|Eliminada em Análise Preliminar",
    ) or "").split("|") if s.strip()}

    # 1) Propostas do municipio (filtro por codigo IBGE, direto do arquivo)
    props: dict[str, dict] = {}          # ID_PROPOSTA -> registro
    n_ignoradas = 0
    for linha in _linhas("siconv_proposta.zip"):
        ibge = (linha.get("COD_MUNIC_IBGE") or "").strip()
        mun_id = por_ibge.get(ibge)
        if not mun_id:
            continue
        if (linha.get("SIT_PROPOSTA") or "").strip() in _ignora_sit:
            n_ignoradas += 1
            continue
        id_prop = (linha.get("ID_PROPOSTA") or "").strip()
        numero = (linha.get("NR_PROPOSTA") or "").strip()
        if not id_prop or not numero:
            continue
        props[id_prop] = {
            "municipio_id": mun_id,
            "numero_proposta": _numero_proposta(numero),
            # Situacao provisoria da PROPOSTA. Se houver convenio, o bloco (2)
            # substitui pela do convenio, que e o que o portal exibe.
            "situacao": _situacao(linha.get("SIT_PROPOSTA"), None),
            "_sit_proposta": (linha.get("SIT_PROPOSTA") or "").strip() or None,
            "orgao": _orgao(linha.get("COD_ORGAO") or linha.get("COD_ORGAO_SUP"),
                            linha.get("DESC_ORGAO") or linha.get("DESC_ORGAO_SUP")),
            "proponente": (linha.get("NM_PROPONENTE") or "").strip() or None,
            "identificacao": _cnpj(linha.get("IDENTIF_PROPONENTE")),
            "modalidade": _modalidade(linha.get("MODALIDADE")),
            "objeto": (linha.get("OBJETO_PROPOSTA") or "").strip() or None,
            # DIA_PROP e o DIA DO MES (1..31), NAO a data. A data completa esta
            # em DIA_PROPOSTA. Usar DIA_PROP gravaria "11" em dt_proposta -- e como
            # a coluna e VARCHAR, passaria sem erro (falha silenciosa, o mesmo
            # padrao do bug de encoding do PAC). Pego pela revisao adversarial.
            "dt_proposta": _data(linha.get("DIA_PROPOSTA")),
            "dt_inicio_vigencia": _data(linha.get("DIA_INIC_VIGENCIA_PROPOSTA")),
            "dt_fim_vigencia": _data(linha.get("DIA_FIM_VIGENCIA_PROPOSTA")),
            "valor_global": _money(linha.get("VL_GLOBAL_PROP")),
            "valor_repasse": _money(linha.get("VL_REPASSE_PROP")),
            "valor_contrapartida": _money(linha.get("VL_CONTRAPARTIDA_PROP")),
            "id_proposta_siconv": id_prop,
            # preenchidos adiante
            "codigo_instrumento": None, "situacao_siafi": None, "numero_processo": None,
            "dt_assinatura": None, "situacao_contratacao": None,
            "clausula_suspensiva_dt_prevista": None, "clausula_suspensiva_motivo": None,
            "parlamentar": None, "programa": None,
        }
    logger.info(f"  propostas encontradas: {len(props)} (ignoradas {n_ignoradas} nao-listadas)")
    if not props:
        return {}

    # 2) Convenio celebrado (nem toda proposta vira convenio)
    n_conv = 0
    for linha in _linhas("siconv_convenio.zip"):
        p = props.get((linha.get("ID_PROPOSTA") or "").strip())
        if p is None:
            continue
        n_conv += 1
        p["codigo_instrumento"] = (linha.get("NR_CONVENIO") or "").strip() or None
        p["situacao_siafi"] = (linha.get("SIT_CONVENIO") or "").strip() or None
        # Com convenio, a situacao EXIBIDA e a do convenio (enche 'Em execucao'/
        # 'Encerradas' no painel). Sem esta linha, um convenio com Prestacao de
        # Contas Concluida apareceria como "proposta em analise" -- 892 casos.
        p["situacao"] = _situacao(p.get("_sit_proposta"), linha.get("SIT_CONVENIO"))
        p["numero_processo"] = _processo(linha.get("NR_PROCESSO"))
        p["dt_assinatura"] = _data(linha.get("DIA_ASSIN_CONV"))
        p["situacao_contratacao"] = (linha.get("SITUACAO_CONTRATACAO") or "").strip() or None
        p["clausula_suspensiva_dt_prevista"] = _data_iso(linha.get("DATA_SUSPENSIVA"))
        p["clausula_suspensiva_motivo"] = (linha.get("MOTIVO_SUSPENSAO") or "").strip() or None
        # A vigencia do CONVENIO manda sobre a da proposta quando existe
        vi = _data(linha.get("DIA_INIC_VIGENC_CONV"))
        vf = _data(linha.get("DIA_FIM_VIGENC_CONV"))
        if vi:
            p["dt_inicio_vigencia"] = vi
        if vf:
            p["dt_fim_vigencia"] = vf
        for campo, col in (("valor_global", "VL_GLOBAL_CONV"),
                           ("valor_repasse", "VL_REPASSE_CONV"),
                           ("valor_contrapartida", "VL_CONTRAPARTIDA_CONV")):
            v = _money(linha.get(col))
            if v is not None:
                p[campo] = v
    logger.info(f"  com convenio celebrado: {n_conv}")

    # 3) Parlamentar da emenda. Uma proposta pode ter MAIS DE UMA emenda; o banco
    # grava os nomes distintos unidos por ', '. Acumular (nao pegar so o
    # primeiro) evita que uma busca por parlamentar deixe de achar a proposta.
    nomes_por_prop: dict[str, list[str]] = {}
    emenda_por_prop: dict[str, float] = {}
    for linha in _linhas("siconv_emenda.zip"):
        id_prop = (linha.get("ID_PROPOSTA") or "").strip()
        if id_prop not in props:
            continue
        nome = (linha.get("NOME_PARLAMENTAR") or "").strip()
        if nome:
            lst = nomes_por_prop.setdefault(id_prop, [])
            if nome not in lst:
                lst.append(nome)
        # valor_emenda = soma dos repasses de emenda da proposta (pode ter varias).
        # Validado 16/08/2026: p/ propostas 100% de emenda, a soma bate exatamente
        # com valor_repasse. valor_voluntario (repasse - emenda) e proponente
        # (contrapartida) sao DERIVADOS na leitura — sem coluna redundante.
        _ve = _money(linha.get("VALOR_REPASSE_EMENDA"))
        if _ve is not None:
            emenda_por_prop[id_prop] = emenda_por_prop.get(id_prop, 0) + float(_ve)
    for id_prop, nomes in nomes_por_prop.items():
        props[id_prop]["parlamentar"] = ", ".join(nomes)
    for id_prop, tot in emenda_por_prop.items():
        props[id_prop]["valor_emenda"] = tot
    logger.info(f"  com parlamentar: {len(nomes_por_prop)} | com valor_emenda: {len(emenda_por_prop)}")

    # 4) Programa (proposta -> programa -> nome)
    prop_para_prog: dict[str, str] = {}
    for linha in _linhas("siconv_programa_proposta.zip"):
        id_prop = (linha.get("ID_PROPOSTA") or "").strip()
        if id_prop in props:
            prop_para_prog[id_prop] = (linha.get("ID_PROGRAMA") or "").strip()
    ids_prog = set(prop_para_prog.values())
    nomes_prog: dict[str, str] = {}
    if ids_prog:
        for linha in _linhas("siconv_programa.zip"):
            pid = (linha.get("ID_PROGRAMA") or "").strip()
            if pid in ids_prog and pid not in nomes_prog:
                nomes_prog[pid] = (linha.get("NOME_PROGRAMA") or "").strip()
                if len(nomes_prog) == len(ids_prog):
                    break
    for id_prop, id_prog in prop_para_prog.items():
        props[id_prop]["programa"] = nomes_prog.get(id_prog) or None
    logger.info(f"  programas resolvidos: {len(nomes_prog)}/{len(ids_prog)}")

    por_municipio: dict[int, list[dict]] = {}
    for p in props.values():
        p.pop("_sit_proposta", None)  # chave interna, nao vai para o banco
        por_municipio.setdefault(p.pop("municipio_id"), []).append(p)
    return por_municipio


# ----------------------------------------------------------------- upsert ---

_CAMPOS = ("numero_proposta", "situacao", "orgao", "proponente", "identificacao",
           "codigo_instrumento", "modalidade", "situacao_siafi", "numero_processo",
           "objeto", "programa", "dt_inicio_vigencia", "dt_fim_vigencia",
           "dt_proposta", "dt_assinatura", "valor_global", "valor_repasse",
           "valor_contrapartida", "situacao_contratacao",
           "clausula_suspensiva_dt_prevista", "clausula_suspensiva_motivo",
           "parlamentar", "id_proposta_siconv", "valor_emenda")


# Campos em que o dado aberto e a FONTE AUTORITATIVA: quando ele traz um valor,
# ele SOBRESCREVE o do banco. Isso e proposital -- a comparacao contra producao
# mostrou que o scraper de navegador gravou dado ERRADO nestes campos, e um
# COALESCE cego congelaria o erro para sempre:
#   - valores: o scraper trocou global/repasse/contrapartida de lugar (gravou
#     repasse onde era global). O CSV oficial soma certo (repasse+contrapartida
#     = global); o banco nao.
#   - orgao: o scraper deixou o codigo colado ("36211 - FUNDACAO..."); o CSV traz
#     o nome limpo. numero_processo/identificacao: idem, com pontuacao propria.
#   - situacao: o scraper truncou rotulos ("...enviado par"); o CSV vem completo.
# `NULLIF(EXCLUDED.campo, '')` + COALESCE: se o dado aberto vier VAZIO naquele
# campo, mantem o que o banco tinha (nao apaga); se vier preenchido, sobrescreve.
_SOBRESCREVE = [
    "situacao", "orgao", "proponente", "identificacao", "modalidade",
    "situacao_siafi", "numero_processo", "objeto", "programa",
    "dt_inicio_vigencia", "dt_fim_vigencia", "dt_proposta", "dt_assinatura",
    "valor_global", "valor_repasse", "valor_contrapartida", "situacao_contratacao",
    "clausula_suspensiva_dt_prevista", "clausula_suspensiva_motivo",
    "codigo_instrumento", "id_proposta_siconv", "valor_emenda",
]
# Campo em que o COALESCE protege de verdade: o parlamentar as vezes so aparece
# no scraper autenticado (emenda impositiva recente que ainda nao entrou no
# arquivo de emendas). Se o dado aberto nao tiver, NAO apaga o que o banco tem.
_PRESERVA = ["parlamentar"]


def _upsert(mun_id: int, propostas: list[dict]) -> int:
    """UPSERT por (municipio_id, numero_proposta).

    Dois regimes, decididos comparando 3.158 registros reais contra o banco:
      - _SOBRESCREVE: dado aberto e autoritativo, corrige erros que o scraper
        gravou (valores trocados, orgao com codigo colado, situacao truncada).
        NULLIF evita apagar quando o CSV vier vazio naquele campo.
      - _PRESERVA + campos ausentes: o que so o scraper autenticado coleta
        (historico_comunicacoes, quadro resumo, processo_execucao_qtd,
        possui_parecer, detalhe, situacao_contratacao_detalhe) nem entra no SET,
        entao permanece intacto no UPDATE.
    """
    import psycopg2
    sets = [
        f"{c}=COALESCE(NULLIF(EXCLUDED.{c}::text, '')::{'numeric' if c.startswith('valor') else 'date' if c == 'clausula_suspensiva_dt_prevista' else 'text'}, transferegov_propostas.{c})"
        for c in _SOBRESCREVE
    ] + [
        f"{c}=COALESCE(EXCLUDED.{c}, transferegov_propostas.{c})" for c in _PRESERVA
    ] + ["raw_data=EXCLUDED.raw_data", "updated_at=NOW()"]
    sql = f"""
        INSERT INTO transferegov_propostas
            (municipio_id, numero_proposta, situacao, orgao, proponente, identificacao,
             codigo_instrumento, modalidade, situacao_siafi, numero_processo, objeto,
             programa, dt_inicio_vigencia, dt_fim_vigencia, dt_proposta, dt_assinatura,
             valor_global, valor_repasse, valor_contrapartida, situacao_contratacao,
             clausula_suspensiva_dt_prevista, clausula_suspensiva_motivo, parlamentar,
             id_proposta_siconv, valor_emenda, raw_data, updated_at)
        VALUES (%(m)s,%(numero_proposta)s,%(situacao)s,%(orgao)s,%(proponente)s,%(identificacao)s,
             %(codigo_instrumento)s,%(modalidade)s,%(situacao_siafi)s,%(numero_processo)s,%(objeto)s,
             %(programa)s,%(dt_inicio_vigencia)s,%(dt_fim_vigencia)s,%(dt_proposta)s,%(dt_assinatura)s,
             %(valor_global)s,%(valor_repasse)s,%(valor_contrapartida)s,%(situacao_contratacao)s,
             %(clausula_suspensiva_dt_prevista)s,%(clausula_suspensiva_motivo)s,%(parlamentar)s,
             %(id_proposta_siconv)s,%(valor_emenda)s,%(raw)s::jsonb, NOW())
        ON CONFLICT (municipio_id, numero_proposta) DO UPDATE SET
             {', '.join(sets)}
    """
    conn = psycopg2.connect(_db_url())
    cur = conn.cursor()
    n = 0
    for p in propostas:
        try:
            cur.execute(sql, {**{k: p.get(k) for k in _CAMPOS}, "m": mun_id,
                              "raw": json.dumps(p, ensure_ascii=False)})
            n += 1
        except Exception as e:
            logger.warning(f"upsert {p.get('numero_proposta')}: {str(e)[:100]}")
            conn.rollback()
            continue
    conn.commit()
    cur.close()
    conn.close()
    return n


def _registra_ingestao(total: int, ok: bool, erro: str | None = None) -> None:
    import psycopg2
    try:
        conn = psycopg2.connect(_db_url())
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ingestion_log (source, status, records_inserted, error_message, "
                "started_at, finished_at) VALUES ('transferegov_opendata', %s, %s, %s, NOW(), NOW())",
                ("success" if ok else "failed", total, (erro or "")[:500] or None),
            )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"  (ingestion_log nao registrado: {e})")


def run(municipio_id=None) -> int:
    t0 = time.monotonic()
    muns = _municipios(municipio_id)
    if not muns:
        logger.warning("Nenhum municipio ativo")
        return 0
    dry = (os.getenv("TG_OPENDATA_DRY_RUN", "") or "").strip() in ("1", "true", "yes")
    logger.info(f"=== TransfereGov Voluntarias (dados abertos): {len(muns)} municipios ===")
    if dry:
        logger.warning("  MODO SIMULACAO (TG_OPENDATA_DRY_RUN=1): nada sera gravado")

    total = 0
    try:
        por_municipio = _coleta(muns)
        coletadas = sum(len(v) for v in por_municipio.values())

        # GUARDA DE COMPLETUDE. Esta e a tabela principal do sistema. Se a coleta
        # vier MUITO menor que o que ja existe no banco, algo quebrou na fonte
        # (arquivo vazio, mudanca de layout, encoding) -- e um UPSERT em massa
        # com dado incompleto poderia sobrescrever campos bons. Abortamos ANTES
        # de gravar. Foi exatamente uma queda a zero silenciosa (encoding no PAC)
        # que motivou esta guarda. Desliga com TG_SKIP_GUARD=1.
        if not (os.getenv("TG_SKIP_GUARD", "") or "").strip() in ("1", "true", "yes"):
            import psycopg2
            _c = psycopg2.connect(_db_url())
            with _c.cursor() as _cur:
                ids = tuple(m["id"] for m in muns)
                _cur.execute(
                    "SELECT count(*) FROM transferegov_propostas WHERE municipio_id IN %s",
                    (ids,))
                no_banco = _cur.fetchone()[0]
            _c.close()
            piso = float(os.getenv("TG_GUARD_MIN_RATIO", "0.7") or "0.7")
            if no_banco > 50 and coletadas < no_banco * piso:
                raise RuntimeError(
                    f"guarda de completude: coletadas {coletadas} < {piso:.0%} de "
                    f"{no_banco} ja no banco. Fonte suspeita -- abortando sem gravar. "
                    f"(TG_SKIP_GUARD=1 forca)")

        nomes = {m["id"]: m["nome"] for m in muns}
        for mun_id, props in sorted(por_municipio.items(), key=lambda kv: nomes.get(kv[0], "")):
            if dry:
                logger.info(f"  [simulacao] {nomes.get(mun_id, mun_id)}: {len(props)} propostas")
                total += len(props)
                continue
            ins = _upsert(mun_id, props)
            logger.info(f"  {nomes.get(mun_id, mun_id)}: {ins} propostas")
            total += ins
        if not dry:
            _registra_ingestao(total, ok=True)
    except Exception as e:
        logger.error(f"falhou: {e}")
        if not dry:
            _registra_ingestao(total, ok=False, erro=str(e))
        raise
    logger.info(f"=== concluido: {total} propostas em {time.monotonic()-t0:.0f}s ===")
    return total


if __name__ == "__main__":
    mid = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(mid)
