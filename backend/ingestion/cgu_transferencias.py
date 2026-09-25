"""
CGU / Portal da Transparência — os RECURSOS RECEBIDOS POR PASTA: todo dinheiro que
a União transfere ao município e aos fundos dele, mês a mês, por órgão, programa e
ação — fundo a fundo da saúde, FNDE, FNAS, cultura (PNAB), defesa civil, FUNDEB,
FPM, royalties.

A pergunta que só esta fonte responde de uma vez: **quanto entrou, de onde, em
cada pasta?** As outras telas contam instrumento (convênio, plano, emenda); esta
conta o DINHEIRO do mês, inclusive o que não tem instrumento nenhum (FPM, FUNDEB,
PAB, PNAE, salário-educação).

Fonte (sem login, sem token; a VPS baixa com 200, medido em 24/09/2026):
    https://portaldatransparencia.gov.br/download-de-dados/transferencias/AAAAMM
      -> 302 -> https://dadosabertos-download.cgu.gov.br/PortalDaTransparencia/
                saida/transferencias/AAAAMM_Transferencias.zip
    ZIP de 3-5 MB, um CSV de 110-145 MB (latin-1, `;`, tudo entre aspas).
    08/2026: 144.284 linhas; 09/2026 (parcial, em 24/09): 182.971.

Medido para conferência (08/2026): Monte Sião FPM 3.088.067,34; FUNDEB (0C33)
641.762,93; PAB (219A, no Fundo Municipal de Saúde) 235.640,89; salário-educação
(0369, no CNPJ da SECRETARIA de educação) 168.526,80; petróleo 89.121,15; PNAE
33.765,50; PNATE 10.344,19; FNAS (219E + 219F + IGD 00US) 21.872,08. Nova Palma:
FPM 1.211.820,09; PAR (20RP) 159.027,33; PAB 88.317,82; FUNDEB 65.301,83;
complementação do FUNDEB (00SB) 8.756,83; PNATE 28.608,87; PNAE 4.399,75; FNAS
12.493,56.

AS ARMADILHAS, medidas em 24/09/2026:

1. ⚠️ **NÃO HÁ IBGE: O MUNICÍPIO VEM PELO CÓDIGO SIAFI** (Monte Sião = 4867, IBGE
   3143401; Nova Palma = 8765, IBGE 4313102), 4 dígitos com zero à esquerda
   ("0643" é Acrelândia), e o NOME vem sem acento. **Nunca casar pelo nome**: há
   uma Santa Maria no RS (8841), outra no RN (0424) e Santa Maria do Herval
   (7337) — a lição de 04/09/2026. O código sai, nesta ordem:
     a) `cauc_situacao.cod_siafi`, que o coletor do CAUC grava casando por IBGE;
     b) a tabela oficial do Tesouro (o CSV de municípios do CAUC no CKAN do
        Tesouro Transparente tem "Código IBGE" e "Código SIAFI" dos 5.569);
     c) só se as duas faltarem: o código das linhas em que o CNPJ da PREFEITURA
        é o favorecido (uma origem, não um palpite — o FPM vai sempre a ele).
   E é conferido: se a prefeitura aparece no arquivo e NENHUMA linha dela tem o
   código resolvido, o município não é gravado naquele mês (`partial`).
   A chave é (código, UF), nunca o código sozinho.

2. **O FAVORECIDO TAMBÉM CASA PELO CNPJ** — o da prefeitura e os de
   `municipio_entidades` —, mesmo sob outro código. ⚠️ Mas 22.678 linhas de
   09/2026 (5.498 de 08/2026) vêm SEM código de município: são entidades (caixa
   escolar, APM) que só entram se o CNPJ estiver cadastrado em
   `municipio_entidades`. Nome não entra.

3. ⚠️ **O MÊS CORRENTE É PARCIAL, E AS CONSTITUCIONAIS SÓ ENTRAM DEPOIS QUE ELE
   FECHA.** O arquivo é atualizado todo dia: em 24/09 o de 09/2026 já tinha
   182.971 linhas — TODAS "Legais, Voluntárias e Específicas". FPM, FUNDEB, ITR e
   royalties ("Constitucionais e Royalties") aparecem só no arquivo do mês
   fechado. Por isso cada rodada relê o mês corrente E o anterior, e a carga
   guarda se o mês já estava fechado quando foi lido (`mes_fechado`). E o
   arquivo muda ao longo do DIA: o de 09/2026 tinha 5,16 MB às 22:06 BRT e 5,3 MB
   às 22:28 (Santa Maria: 91 linhas, depois 92) — duas cargas no mesmo dia podem
   diferir sem que nada esteja errado.

4. **MÊS AINDA NÃO PUBLICADO DÁ 403** no host de download (medido com 202610), não
   404. Para o mês corrente isso é "ainda não saiu" (nota, sem `partial`); para
   qualquer outro mês é falha (`partial`), porque um bloqueio de IP tem a mesma
   cara.

5. **NÃO HÁ CHAVE NATURAL.** O mesmo (ação, favorecido) aparece em várias linhas
   no mesmo mês (o PAB de Monte Sião em 08/2026 são três: 11.250,00 + 12.448,89 +
   211.942,00, por plano orçamentário). Não há data do pagamento, OB, conta nem
   número de instrumento — é o total do mês. Então o (município, mês) é TROCADO
   INTEIRO numa transação (apaga + insere), e só depois de o arquivo ter sido lido
   até o fim.

6. **ARQUIVO SEM LINHA NÃO APAGA NADA.** Mês fechado sem nenhuma linha do
   município não é plausível (o FPM é mensal): vira `partial` e a carga não é
   registrada, para a próxima rodada tentar de novo. Mês aberto vazio só é
   gravado se o banco também estiver vazio para ele.

7. **CABEÇALHO CONFERIDO** (`COLUNAS`, as 36 do arquivo iguais em 01/2023, 10/2024,
   08/2026 e 09/2026): coluna renomeada é `partial` com o nome, nunca "zero
   linha". Linha de outro ANO/MÊS dentro do arquivo é contada e descartada.

8. ⛔ **O HOST DE DOWNLOAD TEM WAF, E ELE PEDE CAPTCHA.** Medido em 24/09/2026 a
   partir de um IP residencial: depois de ~30 arquivos em ~25 min — 24 deles num
   minuto, uma carga inicial sem pausa —, `dadosabertos-download.cgu.gov.br`
   passou a responder **HTTP 405 com `x-amzn-waf-action: captcha`** a qualquer
   arquivo. É o MESMO host da planilha de convênios (`cgu_convenios.py`) e da de
   emendas (`portal_transparencia.py`): um bloqueio causado aqui derruba as três
   fontes nos sete tenants, que saem do mesmo IP. Por isso:
     - pausa de `CGU_TRANSF_PAUSA_S` (padrão 30 s) entre um arquivo e outro;
     - no máximo `CGU_TRANSF_CARGA_POR_RODADA` (padrão 4) meses da carga inicial
       por noite, além do corrente e do anterior — 6 arquivos por tenant;
     - 405/429 ou o cabeçalho do WAF PARAM a rodada na hora (`partial`), sem
       tentar o mês seguinte: insistir sob captcha só estende a pena.

9. **CARGA INICIAL**: o que faltar dos últimos `CGU_TRANSF_MESES` meses (padrão
   24) entra aos poucos, do mais novo para o mais velho — com os padrões acima,
   ~6 noites para os 24 meses. Cada mês custa ~3 s (download + 1,3 s de leitura
   de 145 MB em streaming, medido) mais a pausa. A fila da carga inicial é o
   desenho, não falha (`success`, com a nota de quantos meses faltam); estourar o
   orçamento `CGU_TRANSF_BUDGET_S` (padrão 600 s, dentro do kill de 900 s da
   task) é `partial`.

A classificação por PASTA e por FAVORECIDO (prefeitura, fundo, secretaria,
escola, entidade) NÃO é gravada: é feita na leitura, por
`services/transferencias_pasta.py` — a mesma regra para toda tela.

Rodável por Scheduled Task em todo worker (federal), ou à mão:
    python -u ingestion/cgu_transferencias.py
    python -u ingestion/cgu_transferencias.py --dry          # lê e resume, não grava
Envs: CGU_TRANSF_MESES (24), CGU_TRANSF_CARGA_POR_RODADA (4), CGU_TRANSF_PAUSA_S
(30), CGU_TRANSF_BUDGET_S (600), CGU_TRANSF_FORCE=1 (relê a janela inteira — ainda
limitada pela carga por rodada).
"""
from __future__ import annotations

import argparse
import csv
import io
import logging
import os
import re
import sys
import tempfile
import time
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# O mesmo host e a mesma forma de baixar da planilha de convênios da CGU.
from ingestion.cgu_convenios import UA, baixar  # noqa: E402

log = logging.getLogger("cgu_transferencias")

FONTE = "cgu_transferencias"
ARQUIVO = "https://portaldatransparencia.gov.br/download-de-dados/transferencias/{}"
CAUC_CKAN = "https://www.tesourotransparente.gov.br/ckan/api/3/action/package_show?id=cauc"
BRT = timezone(timedelta(hours=-3))

MESES = int(os.getenv("CGU_TRANSF_MESES") or 24)
CARGA_POR_RODADA = int(os.getenv("CGU_TRANSF_CARGA_POR_RODADA") or 4)
PAUSA_S = float(os.getenv("CGU_TRANSF_PAUSA_S") or 30)
ORCAMENTO_S = int(os.getenv("CGU_TRANSF_BUDGET_S") or 600)
FORCAR = (os.getenv("CGU_TRANSF_FORCE") or "").strip() == "1"

# coluna do CSV -> campo da tabela `cgu_transferencias`
CAMPOS = (
    ("TIPO TRANSFERÊNCIA", "tipo_transferencia"),
    ("TIPO FAVORECIDO", "tipo_favorecido"),
    ("UF", "uf"),
    ("CÓDIGO MUNICÍPIO SIAFI", "siafi_municipio"),
    ("CÓDIGO ÓRGÃO SIAFI", "orgao_codigo"),
    ("NOME ÓRGÃO", "orgao_nome"),
    ("CÓDIGO UNIDADE GESTORA", "ug_codigo"),
    ("NOME UNIDADE GESTORA", "ug_nome"),
    ("CÓDIGO FUNÇÃO", "funcao_codigo"),
    ("NOME FUNÇÃO", "funcao_nome"),
    ("CÓDIGO SUBFUNÇÃO", "subfuncao_codigo"),
    ("NOME SUBFUNÇÃO", "subfuncao_nome"),
    ("CÓDIGO PROGRAMA", "programa_codigo"),
    ("NOME PROGRAMA", "programa_nome"),
    ("AÇÃO", "acao_codigo"),
    ("NOME AÇÃO", "acao_nome"),
    ("LINGUAGEM CIDADÃ", "linguagem_cidada"),
    ("NOME GRUPO DESPESA", "grupo_despesa"),
    ("NOME MODALIDADE APLICAÇÃO DESPESA", "modalidade"),
    ("NOME ELEMENTO DESPESA", "elemento"),
    ("CÓDIGO PLANO ORÇAMENTÁRIO", "plano_orcamentario_codigo"),
    ("NOME PLANO ORÇAMENTÁRIO", "plano_orcamentario"),
    ("NOME LOCALIZADOR", "localizador"),
    ("CÓDIGO FAVORECIDO", "favorecido_doc"),
    ("NOME FAVORECIDO", "favorecido_nome"),
)
COLUNAS = ("ANO / MÊS", "VALOR TRANSFERIDO") + tuple(c for c, _ in CAMPOS)
# "Sem informação" e "-1" são o NULO da CGU.
_SEM = {"", "-1", "sem informação", "sem informaçã", "sem informaç", "sem informa"}


class CabecalhoMudou(Exception):
    """O arquivo perdeu uma coluna que o coletor lê (armadilha 7)."""


def e_waf(r: httpx.Response) -> bool:
    """O WAF da CGU barrou (armadilha 8): 405 com `x-amzn-waf-action: captcha`
    (medido), ou 429. Não é "arquivo não existe" — é "pare de pedir"."""
    return bool(r.headers.get("x-amzn-waf-action")) or r.status_code in (405, 429)


# ---------------------------------------------------------------------------
# Campos
# ---------------------------------------------------------------------------
def _txt(v: str | None) -> str | None:
    v = (v or "").strip()
    return None if v.lower() in _SEM else v


def _dec(v: str | None) -> Decimal | None:
    v = (v or "").strip()
    if not v:
        return None
    try:
        return Decimal(v.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def _doc(v: str | None) -> str:
    return re.sub(r"\D", "", v or "")


def siafi4(v: str | None) -> str:
    """"643" e "0643" são o mesmo código (armadilha 1)."""
    v = (v or "").strip()
    return v.zfill(4) if v.isdigit() else ""


# ---------------------------------------------------------------------------
# Meses
# ---------------------------------------------------------------------------
def hoje_brasilia() -> date:
    return datetime.now(BRT).date()


def mes_menos(m: date, n: int) -> date:
    a, b = divmod(m.year * 12 + (m.month - 1) - n, 12)
    return date(a, b + 1, 1)


def aaaamm(m: date) -> str:
    return f"{m.year:04d}{m.month:02d}"


def meses_da_rodada(hoje: date, mids: set[int], carregados: dict[date, dict[int, bool]],
                    janela: int = MESES, forcar: bool = False) -> list[tuple[date, set[int]]]:
    """[(mês, municípios a gravar)] na ordem da rodada.

    Sempre o corrente e o anterior, para todos (armadilha 3). Depois a janela
    da carga inicial, do mais novo para o mais velho, só para quem ainda não tem o
    mês — ou o tem gravado de quando ele ainda estava aberto (`carregados[mes][mid]`
    é o `mes_fechado` da carga)."""
    corrente = hoje.replace(day=1)
    fila = [(corrente, set(mids)), (mes_menos(corrente, 1), set(mids))]
    for n in range(2, max(janela, 2)):
        m = mes_menos(corrente, n)
        ja = carregados.get(m, {})
        faltam = set(mids) if forcar else {i for i in mids if not ja.get(i)}
        if faltam:
            fila.append((m, faltam))
    return fila


# ---------------------------------------------------------------------------
# Código SIAFI (armadilha 1)
# ---------------------------------------------------------------------------
def siafi_por_ibge(texto: str) -> dict[str, tuple[str, str]]:
    """{IBGE: (SIAFI, UF)} do CSV de municípios do CAUC (Tesouro). O arquivo tem
    três linhas de preâmbulo antes do cabeçalho "UF";"Nome do Ente Federado";..."""
    linhas = texto.splitlines()
    ini = next((i for i, l in enumerate(linhas[:20]) if l.lstrip('"').upper().startswith("UF")),
               None)
    if ini is None:
        raise CabecalhoMudou("CSV do CAUC sem o cabeçalho que começa por UF")
    r = csv.reader(linhas[ini:], delimiter=";")
    h = [c.strip() for c in next(r)]
    try:
        i_uf, i_ibge, i_siafi = h.index("UF"), h.index("Código IBGE"), h.index("Código SIAFI")
    except ValueError as e:
        raise CabecalhoMudou(f"CSV do CAUC sem a coluna {e}") from None
    out = {}
    for row in r:
        if len(row) > max(i_uf, i_ibge, i_siafi) and row[i_ibge].strip().isdigit():
            out[row[i_ibge].strip()] = (siafi4(row[i_siafi]), row[i_uf].strip())
    return out


def baixar_tabela_siafi(client: httpx.Client) -> dict[str, tuple[str, str]]:
    """A tabela oficial IBGE↔SIAFI: o CSV de municípios do CAUC no CKAN do Tesouro
    (o mesmo recurso que `ingestion/cauc_ingest.py` lê)."""
    pkg = client.get(CAUC_CKAN, headers=UA, timeout=60).json()["result"]
    url = next((x["url"] for x in pkg.get("resources", [])
                if x.get("format") == "CSV" and "munic" in (x.get("name") or "").lower()), None)
    if not url:
        raise RuntimeError("CKAN do Tesouro sem o CSV de municípios do CAUC")
    r = client.get(url, headers=UA, timeout=120)
    r.raise_for_status()
    return siafi_por_ibge(r.content.decode("latin-1"))


# ---------------------------------------------------------------------------
# Leitura do arquivo do mês
# ---------------------------------------------------------------------------
@dataclass
class Alvo:
    id: int
    nome: str
    uf: str
    ibge: str
    cnpj: str
    extras: set = field(default_factory=set)
    siafi: str | None = None
    origem: str | None = None      # cauc_situacao | tabela_tesouro | cnpj_prefeitura

    @property
    def chave(self) -> tuple[str, str] | None:
        return (self.siafi, self.uf) if self.siafi else None


def leitor(z: zipfile.ZipFile):
    """(csv.reader já depois do cabeçalho, índice das colunas), com o cabeçalho
    conferido (armadilha 7)."""
    nome = next((n for n in z.namelist() if n.endswith("_Transferencias.csv")), None)
    if nome is None:
        raise CabecalhoMudou(f"o zip não tem *_Transferencias.csv ({z.namelist()})")
    r = csv.reader(io.TextIOWrapper(z.open(nome), encoding="latin-1", newline=""),
                   delimiter=";")
    h = next(r, [])
    faltando = [c for c in COLUNAS if c not in h]
    if faltando:
        raise CabecalhoMudou(f"{nome} sem as colunas {faltando}")
    return r, {c: h.index(c) for c in COLUNAS}


def codigos_pela_prefeitura(z: zipfile.ZipFile, alvos: list[Alvo]) -> dict[int, Counter]:
    """Pré-passada (só para quem ficou sem código): (código, UF) das linhas cujo
    favorecido é o CNPJ da prefeitura."""
    por_cnpj = {a.cnpj: a.id for a in alvos if a.cnpj}
    cont: dict[int, Counter] = {a.id: Counter() for a in alvos}
    r, ix = leitor(z)
    i_doc, i_s, i_uf = ix["CÓDIGO FAVORECIDO"], ix["CÓDIGO MUNICÍPIO SIAFI"], ix["UF"]
    for row in r:
        mid = por_cnpj.get(_doc(row[i_doc]))
        if mid is not None and siafi4(row[i_s]):
            cont[mid][(siafi4(row[i_s]), row[i_uf].strip())] += 1
    return cont


@dataclass
class Leitura:
    linhas: dict[int, list[dict]]
    # (código, UF) das linhas cujo favorecido é a PREFEITURA — a conferência.
    codigos_prefeitura: dict[int, Counter]
    total_arquivo: int = 0
    fora_do_mes: int = 0


def ler_mes(z: zipfile.ZipFile, mes: date, alvos: list[Alvo]) -> Leitura:
    """Uma passada em streaming pelo CSV (145 MB descompactados nunca ficam na
    memória): guarda só as linhas dos municípios do tenant."""
    por_codigo = {a.chave: a.id for a in alvos if a.chave}
    por_doc: dict[str, int] = {}
    prefeituras = {a.cnpj: a.id for a in alvos if a.cnpj}
    for a in alvos:
        for doc in [a.cnpj, *sorted(a.extras)]:
            if doc:
                por_doc.setdefault(doc, a.id)
    out = Leitura({a.id: [] for a in alvos}, {a.id: Counter() for a in alvos})
    r, ix = leitor(z)
    i_mes, i_valor = ix["ANO / MÊS"], ix["VALOR TRANSFERIDO"]
    i_s, i_uf, i_doc = ix["CÓDIGO MUNICÍPIO SIAFI"], ix["UF"], ix["CÓDIGO FAVORECIDO"]
    esperado = aaaamm(mes)
    for row in r:
        out.total_arquivo += 1
        if row[i_mes].strip() != esperado:
            out.fora_do_mes += 1
            continue
        chave = (siafi4(row[i_s]), row[i_uf].strip())
        doc = _doc(row[i_doc])
        if doc in prefeituras and chave[0]:
            out.codigos_prefeitura[prefeituras[doc]][chave] += 1
        mids = {m for m in (por_codigo.get(chave), por_doc.get(doc)) if m is not None}
        if not mids:
            continue
        x = {campo: _txt(row[ix[col]]) for col, campo in CAMPOS}
        x["siafi_municipio"] = chave[0] or None
        x["favorecido_doc"] = doc or None
        x["valor"] = _dec(row[i_valor]) or Decimal("0")
        for mid in mids:
            out.linhas[mid].append(x)
    return out


def divergente(a: Alvo, leitura: Leitura) -> bool:
    """A prefeitura aparece no arquivo e NENHUMA linha dela tem o código resolvido
    (armadilha 1): o código está errado — não gravar."""
    c = leitura.codigos_prefeitura.get(a.id) or Counter()
    return bool(c) and a.chave not in c


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------
_COLS = ("municipio_id", "mes") + tuple(campo for _, campo in CAMPOS) + ("valor",)


def _alvos(cur) -> list[Alvo]:
    cur.execute("""
        SELECT m.id, m.nome, upper(coalesce(m.uf, '')), coalesce(m.ibge_code::text, ''),
               regexp_replace(coalesce(m.cnpj, ''), '\\D', '', 'g'), c.cod_siafi
          FROM municipios m LEFT JOIN cauc_situacao c ON c.municipio_id = m.id
         WHERE m.active
         ORDER BY m.id
    """)
    alvos = []
    for mid, nome, uf, ibge, cnpj, cod in cur.fetchall():
        a = Alvo(mid, nome, uf, ibge, cnpj if len(cnpj) == 14 else "")
        if siafi4(cod):
            a.siafi, a.origem = siafi4(cod), "cauc_situacao"
        alvos.append(a)
    cur.execute("SELECT municipio_id, regexp_replace(cnpj, '\\D', '', 'g') "
                "FROM municipio_entidades")
    por_id = {a.id: a for a in alvos}
    for mid, cnpj in cur.fetchall():
        if mid in por_id and len(cnpj) == 14:
            por_id[mid].extras.add(cnpj)
    return alvos


def _carregados(cur) -> dict[date, dict[int, bool]]:
    cur.execute("SELECT mes, municipio_id, mes_fechado FROM cgu_transferencias_carga")
    out: dict[date, dict[int, bool]] = {}
    for mes, mid, fechado in cur.fetchall():
        out.setdefault(mes, {})[mid] = bool(fechado)
    return out


def _inserir_linhas(cur, linhas: list[dict]) -> None:
    from psycopg2.extras import execute_values
    execute_values(
        cur,
        f"INSERT INTO cgu_transferencias ({', '.join(_COLS)}) VALUES %s",
        [tuple(x[c] for c in _COLS) for x in linhas], page_size=1000)


def grava_mes(cur, a: Alvo, mes: date, linhas: list[dict], fechado: bool) -> tuple[int, str | None]:
    """(linhas gravadas, motivo da recusa). Troca o (município, mês) inteiro —
    armadilhas 5 e 6. Quem chama faz o commit (uma transação por município-mês)."""
    cur.execute("SELECT count(*) FROM cgu_transferencias WHERE municipio_id = %s AND mes = %s",
                (a.id, mes))
    no_banco = cur.fetchone()[0]
    if not linhas and fechado:
        return 0, f"{a.nome} {aaaamm(mes)}: mês fechado sem nenhuma linha — nada gravado"
    if not linhas and no_banco:
        return 0, (f"{a.nome} {aaaamm(mes)}: arquivo sem linha e banco com {no_banco} — "
                   "nada apagado")
    cur.execute("DELETE FROM cgu_transferencias WHERE municipio_id = %s AND mes = %s",
                (a.id, mes))
    if linhas:
        _inserir_linhas(cur, [{**x, "municipio_id": a.id, "mes": mes} for x in linhas])
    total = sum((x["valor"] for x in linhas), Decimal("0"))
    cur.execute("""
        INSERT INTO cgu_transferencias_carga (municipio_id, mes, linhas, total, mes_fechado,
            siafi_municipio, siafi_origem, carregado_em)
        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (municipio_id, mes) DO UPDATE SET linhas = EXCLUDED.linhas,
            total = EXCLUDED.total, mes_fechado = EXCLUDED.mes_fechado,
            siafi_municipio = EXCLUDED.siafi_municipio,
            siafi_origem = EXCLUDED.siafi_origem, carregado_em = NOW()
    """, (a.id, mes, len(linhas), total, fechado, a.siafi, a.origem))
    return len(linhas), None


def _log_ingest(cur, conn, status: str, n: int, nota: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES (%s, %s, %s, %s, NOW())",
            (FONTE, status, n, nota))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.warning("ingestion_log falhou: %s", str(e)[:120])


# ---------------------------------------------------------------------------
# Rodada
# ---------------------------------------------------------------------------
def resolver_codigos(alvos: list[Alvo], client: httpx.Client | None, notas: list[str]) -> None:
    """Completa o código SIAFI de quem não o tem em `cauc_situacao` pela tabela do
    Tesouro (armadilha 1b). Quem continuar sem código tenta a (c) no arquivo."""
    faltam = [a for a in alvos if not a.siafi and a.ibge]
    if not faltam or client is None:
        return
    try:
        tabela = baixar_tabela_siafi(client)
    except Exception as e:
        notas.append(f"tabela IBGE↔SIAFI do Tesouro indisponível ({type(e).__name__})")
        log.warning("tabela do Tesouro falhou: %s", str(e)[:200])
        return
    for a in faltam:
        cod = tabela.get(a.ibge)
        if cod and cod[0] and (not a.uf or cod[1] == a.uf):
            a.siafi, a.origem = cod[0], "tabela_tesouro"


def processar_mes(cur, conn, z: zipfile.ZipFile, mes: date, alvos: list[Alvo],
                  quem: set[int], fechado: bool, notas: list[str], dry: bool = False) -> tuple[int, bool]:
    """Lê o arquivo de UM mês e grava os municípios `quem`. (linhas, parcial)."""
    parcial = False
    sem = [a for a in alvos if not a.siafi]
    if sem:
        cont = codigos_pela_prefeitura(z, sem)
        for a in sem:
            if cont[a.id]:
                (a.siafi, uf), _ = cont[a.id].most_common(1)[0]
                if not a.uf or uf == a.uf:
                    a.origem = "cnpj_prefeitura"
                    a.uf = a.uf or uf
                else:
                    a.siafi = None
    leitura = ler_mes(z, mes, alvos)
    if leitura.fora_do_mes:
        notas.append(f"{aaaamm(mes)}: {leitura.fora_do_mes} linha(s) de outro mês descartadas")
    gravadas = 0
    for a in alvos:
        if a.id not in quem:
            continue
        if not a.siafi and not a.cnpj:
            parcial = True
            notas.append(f"{a.nome}: sem código SIAFI e sem CNPJ — não dá para casar")
            continue
        if not a.siafi:
            # Sem código, só entra o que casou pelo CNPJ — e mês fechado sem
            # prefeitura nenhuma é o mesmo caso da armadilha 6.
            parcial = True
            notas.append(f"{a.nome}: sem código SIAFI (IBGE {a.ibge or '?'}) — só pelo CNPJ")
        if a.siafi and divergente(a, leitura):
            parcial = True
            notas.append(f"{a.nome} {aaaamm(mes)}: código SIAFI {a.siafi} ({a.origem}) não é o "
                         f"das linhas da prefeitura {dict(leitura.codigos_prefeitura[a.id])}"
                         " — nada gravado")
            continue
        ls = leitura.linhas.get(a.id, [])
        if dry:
            log.info("  %s %s: %d linha(s), R$ %s", a.nome, aaaamm(mes), len(ls),
                     f"{sum((x['valor'] for x in ls), Decimal('0')):,.2f}")
            continue
        try:
            n, recusa = grava_mes(cur, a, mes, ls, fechado)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        if recusa:
            parcial = True
            notas.append(recusa)
        gravadas += n
    return gravadas, parcial


def ingest(dry: bool = False) -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect

    t0 = time.monotonic()
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            alvos = _alvos(cur)
            if not alvos:
                log.info("nenhum município ativo — nada a casar")
                if not dry:
                    _log_ingest(cur, conn, "success", 0, "nenhum município ativo")
                return 0
            notas: list[str] = []
            hoje = hoje_brasilia()
            corrente = hoje.replace(day=1)
            fila = meses_da_rodada(hoje, {a.id for a in alvos}, _carregados(cur),
                                   MESES, FORCAR)
            # Armadilha 8: o corrente, o anterior e no máximo CARGA_POR_RODADA da
            # carga inicial. O resto é a fila das próximas noites — desenho, não falha.
            na_fila = max(0, len(fila) - 2 - CARGA_POR_RODADA)
            fila = fila[:2 + CARGA_POR_RODADA]
            gravadas, parcial, lidos, adiados = 0, False, [], 0
            with httpx.Client(follow_redirects=True) as client:
                resolver_codigos(alvos, client, notas)
                for k, (mes, quem) in enumerate(fila):
                    if k >= 2 and time.monotonic() - t0 > ORCAMENTO_S:
                        adiados = len(fila) - k
                        break
                    if k:
                        time.sleep(PAUSA_S)
                    with tempfile.TemporaryFile() as f:
                        try:
                            tam = baixar(client, ARQUIVO.format(aaaamm(mes)), f)
                        except httpx.HTTPStatusError as e:
                            cod = e.response.status_code
                            log.warning("%s: HTTP %s", aaaamm(mes), cod)
                            if e_waf(e.response):
                                parcial = True
                                notas.append(f"{aaaamm(mes)}: WAF da CGU barrou (HTTP {cod}, "
                                             f"{e.response.headers.get('x-amzn-waf-action') or 'sem cabeçalho'})"
                                             " — rodada interrompida para não estender o bloqueio")
                                break
                            if mes == corrente and cod in (403, 404):
                                notas.append(f"{aaaamm(mes)} ainda não publicado ({cod})")
                            else:
                                parcial = True
                                notas.append(f"{aaaamm(mes)}: HTTP {cod}")
                            continue
                        log.info("%s: %.1f MB", aaaamm(mes), tam / 1e6)
                        n, p = processar_mes(cur, conn, zipfile.ZipFile(f), mes, alvos, quem,
                                             mes < corrente, notas, dry)
                    gravadas += n
                    parcial = parcial or p
                    lidos.append(aaaamm(mes))
            if adiados:
                parcial = True
                notas.append(f"orçamento de {ORCAMENTO_S} s estourado: {adiados} mês(es) "
                             "ficaram para a próxima rodada")
            if na_fila:
                notas.append(f"carga inicial: {na_fila} mês(es) na fila das próximas noites "
                             f"({CARGA_POR_RODADA} por rodada)")
            if dry:
                return 0
            status = "partial" if parcial else "success"
            nota = " | ".join([f"meses {', '.join(lidos) or 'nenhum'}"] + notas)[:400]
            log.info("=== CGU transferências: %d linha(s), status=%s (%s) ===", gravadas,
                     status, nota)
            _log_ingest(cur, conn, status, gravadas, nota)
            return gravadas
        except CabecalhoMudou as e:
            conn.rollback()
            log.error("CGU transferências: layout mudou: %s", e)
            if not dry:
                _log_ingest(cur, conn, "partial", 0, f"layout mudou: {str(e)[:300]}")
            return 0
        except Exception as e:
            conn.rollback()
            log.error("CGU transferências falhou: %s: %s", type(e).__name__, str(e)[:200])
            if not dry:
                _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    p = argparse.ArgumentParser()
    p.add_argument("--dry", action="store_true", help="lê e resume, sem gravar")
    ingest(dry=p.parse_args().dry)
