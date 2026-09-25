"""
Repasses do FUNDO ESTADUAL DE SAÚDE do RS (SES-RS) — o que o Estado pagou, mês a
mês, ao Fundo Municipal de Saúde e aos hospitais/entidades de cada município.

    https://saude.rs.gov.br/pagamentos-mes
    -> "GERAL PAGOS em <MÊS> Programas Municipais e INCENTIVOS <ANO> FESGERAL" (.xls)

Uma planilha por mês de PAGAMENTO, com o Estado inteiro (8.217 linhas em
setembro/2026, R$ 401,9 mi pagos e R$ 13,2 mi retidos): município, credor,
projeto/subprojeto (PIAPS, MAC, ASSISTIR, UPA, SAMU, Inverno Gaúcho...),
modalidade, recurso ESTADUAL ou FEDERAL (o MAC federal que passa pelo Estado),
competência, empenho, data, valor PAGO, valor RETIDO com o motivo, liquidação,
processos e o histórico (que cita a portaria / Res. CIB).

É o único repasse ESTADUAL de saúde do RS no PACTHA. Nova Palma, setembro/2026:
ao Fundo Municipal PIAPS 28.673,75, CAPS 12.000, Regulação 9.113,60; ao hospital
local ASSISTIR 242.460,04, MAC 153.512,06 e cofinanciamento ambulatorial 125.000.

AS ARMADILHAS, medidas em 24/09/2026:

1. ⚠️ **O NOME DO ARQUIVO TEM PREFIXO DE HORA** (`/upload/arquivos/202609/
   24074153-geral-pagos-em-setembro-...-2026-fesgeral.xls`). Nunca montar o nome:
   ler os links da página (HTML simples). E a SES REPUBLICA O ANO INTEIRO TODO
   DIA com nome novo — setembro sai com pagamentos até a véspera.

2. ⚠️ **LINK VELHO CONTINUA NA PÁGINA E DÁ 404.** Janeiro/2026 aparece duas vezes
   (`202602/11082111-...` e `202609/24074244-...`); o antigo responde 404. Vale o
   mais NOVO de cada mês (pasta aaaamm + prefixo ddhhmmss); 404 num link tenta o
   seguinte do mesmo mês, e só depois vira falha.

3. ⚠️ **O HOST USA COOKIE DE BALANCEADOR (TS/F5).** Um `httpx.Client` guarda o
   cookie entre a página e os arquivos — requisição avulsa sem ele pode tomar a
   página de desafio. Um arquivo que não começa pela assinatura OLE do .xls é
   recusado (página de erro servida com 200).

4. ⚠️ **.xls BIFF EXPORTADO DO ACCESS**, não .xlsx — precisa do `xlrd`. Três
   linhas de título, cabeçalho na 5ª, data em SERIAL DO EXCEL, linha "TOTAIS"
   no fim. E O CABEÇALHO VARIA: fevereiro/2026 tem uma 37ª coluna vazia. Colunas
   lidas por NOME; faltando uma obrigatória, o mês é recusado (`partial`, nada
   apagado). O mês/ano do título ("Valores PAGOS e RETIDOS no MÊS de SETEMBRO
   2026") tem de bater com o do link, e a soma das linhas com a linha TOTAIS — é
   essa conta que prova que o arquivo veio inteiro.

5. ⚠️ **"CÓD. MUNICÍPIO" NÃO É O IBGE.** É o código ESTADUAL (CAGE/SEFAZ): Nova
   Palma = 083, Santa Maria = 109. O casamento é por
   `services/municipios_rs_codigo_estadual.py`, tabela versionada gerada por
   `scripts/gerar_depara_municipios_rs.py` por uma cadeia de CNPJs em fontes
   oficiais — NUNCA pelo nome (a lição da Santa Maria do Herval). Município do
   cliente fora da tabela vira nota (`partial`), nunca "zero repasse".

6. ⚠️ **O MESMO CÓDIGO DE MUNICÍPIO TRAZ O FUNDO MUNICIPAL E OS HOSPITAIS.**
   ASSISTIR, SUS Gaúcho e MAC vão DIRETO ao hospital, não ao fundo — em Nova
   Palma o hospital recebe 6x o que o fundo recebe no ano. O Fundo Municipal é o
   credor que recebe "Transferências a Municípios - Fundo a Fundo" (modalidade
   41), pelo CÓDIGO do credor (não pelo nome): em Guaíba um hospital privado
   também aparece com modalidade 41, e fica fora porque o fundo tem muito mais
   linhas. Todas as linhas desse credor contam para a prefeitura (Santa Maria
   recebe também em modalidade 40 e 90); o resto vai para "hospitais e
   entidades", FORA do total da prefeitura — inclusive autarquia/fundação
   municipal e até "PREF MUN DE JAGUARI" (2 linhas como aplicação direta), que
   aparecem com o nome delas no bloco de fora, sem somar.

7. ⚠️ **RETENÇÃO É LINHA PRÓPRIA** (valor_pago 0, valor_retido > 0, com o
   motivo). Para o Fundo Municipal é dinheiro que não chegou: "REST TETO MAC
   CONASEMS" (desconto da contribuição ao CONASEMS, CIB 630/24), "RETENCAO -
   RECURSO 6" (pagamento a maior), "MULTAS AUDITORIA DO SUS" — Nova Palma R$
   3.706,80 em 2026, Santa Maria R$ 35.268,87. No hospital, a maior parte é
   TRIBUTO do prestador (ISSQN, IRRF) ou consignado — não é perda. `tipo_retencao`
   separa as duas leituras.

8. ⚠️ **HÁ VALOR NEGATIVO** (61 pagamentos e 33 retenções em 2026): estorno. Fica
   com o sinal — a soma da fonte (linha TOTAIS) conta assim.

9. ⚠️ **O ARQUIVO ANUAL `/fes-programas-municipais` É INCOMPLETO** — não traz
   MAC, Inverno Gaúcho, Piso da Enfermagem nem os hospitais. Não usar.

10. **SEM CHAVE NATURAL** (empenho+data+valor se repete). Carga por (município,
    ano, mês): apaga e insere na mesma transação, com o mês lido inteiro. O hash
    do arquivo (`fes_rs_arquivos`) pula o mês que veio igual — quase todos, já que
    a republicação diária reescreve o ano inteiro.

Só roda em tenant com município do RS; nos outros sai `success` 0 sem baixar.
Rodável por Scheduled Task ou à mão:
    python -u ingestion/fes_rs.py            # coleta de verdade
    python -u ingestion/fes_rs.py --dry      # baixa, lê, casa e mostra
    FES_RS_ANOS=2025,2026 python -u ingestion/fes_rs.py   # carga de anos passados
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.municipios_rs_codigo_estadual import CODIGO_ESTADUAL_PARA_IBGE  # noqa: E402

log = logging.getLogger("fes_rs")

BASE = "https://saude.rs.gov.br"
PAGINA = f"{BASE}/pagamentos-mes"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131 Safari/537.36"}
UF = "RS"
SOURCE = "fes_rs"
TIMEOUT = 180
# A SES republica todo dia (armadilha 1). Mais que isso sem arquivo novo na
# página = a fonte parou, e a rodada diz (`partial`).
IDADE_MAX_DIAS = int(os.getenv("FES_RS_IDADE_MAX_DIAS") or "10")
# Sobe quando a leitura muda de um jeito que exige reler arquivo igual.
VERSAO_LEITOR = 1
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"      # assinatura de arquivo .xls (BIFF/OLE2)

MESES = {"JANEIRO": 1, "FEVEREIRO": 2, "MARCO": 3, "ABRIL": 4, "MAIO": 5, "JUNHO": 6,
         "JULHO": 7, "AGOSTO": 8, "SETEMBRO": 9, "OUTUBRO": 10, "NOVEMBRO": 11,
         "DEZEMBRO": 12}
RE_LINK = re.compile(
    r'href="(/upload/arquivos/(\d{6})/(\d{8})-[^"]*?pagos-em-([a-z]+)-[^"]*?'
    r'(20\d{2})-fesgeral\.xls)"', re.I)

# Nosso campo -> rótulo da coluna na planilha (comparado sem acento/caixa).
COLUNAS = {
    "cod_municipio": "Cód. Município", "municipio": "Município", "crs": "CRS",
    "credor": "Credor", "cod_credor": "Cód. Credor",
    "cod_projeto": "Cód. Projeto", "projeto": "Projeto",
    "cod_subprojeto": "Cód. Sub-Projeto", "subprojeto": "SubProjeto",
    "cod_modalidade": "Cód. Modalidade", "modalidade": "Modalidade",
    "cod_recurso": "Cód. Recurso", "recurso": "Recurso", "fonte_recurso": "Fonte",
    "competencia_ano": "ano competência", "competencia_mes": "mês competência",
    "nr_empenho": "Nº Empenho", "data": "Data",
    "valor_pago": "Valor pago", "valor_retido": "Valor retido",
    "cod_retencao": "Cod Tab Retencao", "motivo_retencao": "Descrição tabela Reten",
    "documento": "Doc Credor", "nr_liquidacao": "Nº Liquidação",
    "processo_empenho": "Nº Processo Emp", "processo_liquidacao": "Nº processo Liq",
    "historico": "Historico Liq",
}
# Sem estas a linha não tem sentido; as outras faltando viram None.
OBRIGATORIAS = ("cod_municipio", "credor", "cod_credor", "projeto", "cod_modalidade",
                "data", "valor_pago", "valor_retido")

# Retenção por código da tabela (armadilha 7); o motivo por extenso decide o resto.
_TIPO_POR_CODIGO = {"0440": "tributo", "0539": "tributo", "0594": "judicial",
                    "0070": "judicial", "0791": "consignado"}


def _n(s) -> str:
    """Sem acento, maiúsculo, só letra/dígito separados por um espaço."""
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", s).split())


def _txt(v) -> str | None:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = " ".join(str(v if v is not None else "").split())
    return s or None


def _int(v) -> int | None:
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None


def _dec(v) -> Decimal:
    if v in (None, ""):
        return Decimal("0")
    return Decimal(str(round(float(v), 2)))


def tipo_retencao(cod: str | None, motivo: str | None) -> str:
    if (cod or "").strip() in _TIPO_POR_CODIGO:
        return _TIPO_POR_CODIGO[(cod or "").strip()]
    m = _n(motivo)
    if re.search(r"ISSQN|IRRF|INSS|IMPOSTO|TRIBUT", m):
        return "tributo"
    if re.search(r"JUDIC|PENHORA|BLOQUEIO", m):
        return "judicial"
    if re.search(r"CONSIGNAD|EMPRESTIMO", m):
        return "consignado"
    if re.search(r"CONASEMS|MULTA|AUDITORIA|RESTIT|\bREST\b|RETENCAO|DESC|METAS|ANTECIP|INDEVID", m):
        return "desconto"
    return "outra"


# ---------------------------------------------------------------------------
# A página
# ---------------------------------------------------------------------------
def links_da_pagina(html: str) -> dict[tuple[int, int], list[tuple[str, datetime]]]:
    """{(ano, mês): [(url, publicado_em), ...]} do mais NOVO para o mais velho
    (armadilha 2). `publicado_em` sai da pasta aaaamm + prefixo ddhhmmss."""
    out: dict[tuple[int, int], list[tuple[str, datetime]]] = defaultdict(list)
    for href, pasta, prefixo, mes_txt, ano in RE_LINK.findall(html or ""):
        mes = MESES.get(_n(mes_txt))
        if not mes:
            log.warning("link com mês desconhecido: %s", href)
            continue
        try:
            pub = datetime(int(pasta[:4]), int(pasta[4:]), int(prefixo[:2]),
                           int(prefixo[2:4]), int(prefixo[4:6]), int(prefixo[6:]))
        except ValueError:
            pub = datetime(int(pasta[:4]), int(pasta[4:]), 1)
        url = BASE + href
        if url not in [u for u, _ in out[(int(ano), mes)]]:
            out[(int(ano), mes)].append((url, pub))
    return {k: sorted(v, key=lambda x: x[1], reverse=True) for k, v in out.items()}


# ---------------------------------------------------------------------------
# A planilha
# ---------------------------------------------------------------------------
@dataclass
class Planilha:
    ano: int
    mes: int
    linhas: list[dict] = field(default_factory=list)
    total_pago: Decimal = Decimal("0")
    total_retido: Decimal = Decimal("0")
    pago_ate: date | None = None


def ler_planilha(conteudo: bytes, ano: int, mes: int) -> Planilha:
    """Lê o .xls do mês inteiro. ValueError em qualquer sinal de arquivo errado ou
    incompleto (armadilhas 3 e 4) — quem chama não apaga nada nesse caso."""
    import xlrd

    if not conteudo.startswith(OLE):
        raise ValueError("não é .xls (página de erro/desafio servida no lugar?)")
    book = xlrd.open_workbook(file_contents=conteudo)
    s = book.sheet_by_index(0)
    return ler_grade([s.row_values(r) for r in range(s.nrows)], ano, mes, book.datemode)


def ler_grade(grade: list[list], ano: int, mes: int, datemode: int = 0) -> Planilha:
    """A leitura em si, sobre a grade de células (valores como o xlrd os dá:
    texto, float, serial de data). Separada para o teste rodar o recorte real
    sem guardar 5 MB de .xls no repositório."""
    import xlrd

    def cel(r, c):
        return grade[r][c] if r < len(grade) and c < len(grade[r]) else ""

    # Título: o mês/ano do ARQUIVO tem de ser o do link.
    titulo = " ".join(_n(cel(r, 0)) for r in range(min(4, len(grade))))
    m = re.search(r"MES DE ([A-Z]+) (20\d{2})", titulo)
    if not m or MESES.get(m.group(1)) != mes or int(m.group(2)) != ano:
        raise ValueError(f"título não é de {mes:02d}/{ano}: {titulo[:120]!r}")
    # Cabeçalho: a linha que começa por "Município" (a 5ª hoje).
    ini = next((r for r in range(min(15, len(grade))) if _n(cel(r, 0)) == "MUNICIPIO"),
               None)
    if ini is None:
        raise ValueError("cabeçalho 'Município' não encontrado nas 15 primeiras linhas")
    cab = {_n(v): i for i, v in enumerate(grade[ini]) if _n(v)}
    ix = {campo: cab.get(_n(rotulo)) for campo, rotulo in COLUNAS.items()}
    faltam = [COLUNAS[c] for c in OBRIGATORIAS if ix[c] is None]
    if faltam:
        raise ValueError(f"coluna(s) ausente(s): {', '.join(faltam)}")

    pl = Planilha(ano, mes)
    totais = None
    for r in range(ini + 1, len(grade)):
        v = grade[r]
        if not v:
            continue
        primeiro = _n(v[0])
        if primeiro == "TOTAIS":
            totais = (_dec(v[ix["valor_pago"]]), _dec(v[ix["valor_retido"]]))
            break
        if not any(str(x).strip() for x in v):
            continue
        cod = _int(v[ix["cod_municipio"]])
        if cod is None:
            raise ValueError(f"linha {r + 1}: código de município ilegível {v[ix['cod_municipio']]!r}")

        def g(campo):
            i = ix[campo]
            return v[i] if i is not None and i < len(v) else None

        dt = g("data")
        if isinstance(dt, (int, float)) and not isinstance(dt, bool):
            dt = xlrd.xldate.xldate_as_datetime(dt, datemode).date()
        else:
            try:
                dt = datetime.strptime(str(dt).strip(), "%d/%m/%Y").date()
            except ValueError:
                dt = None
        linha = {
            "cod_municipio": cod, "municipio": _txt(g("municipio")),
            "crs": _txt(g("crs")), "credor": _txt(g("credor")) or "",
            "cod_credor": (_txt(g("cod_credor")) or "").strip(),
            "cod_projeto": _txt(g("cod_projeto")), "projeto": _txt(g("projeto")),
            "cod_subprojeto": _txt(g("cod_subprojeto")), "subprojeto": _txt(g("subprojeto")),
            "cod_modalidade": _txt(g("cod_modalidade")), "modalidade": _txt(g("modalidade")),
            "cod_recurso": _txt(g("cod_recurso")), "recurso": _txt(g("recurso")),
            "fonte_recurso": _txt(g("fonte_recurso")),
            "competencia_ano": _int(g("competencia_ano")),
            "competencia_mes": _int(g("competencia_mes")),
            "nr_empenho": _txt(g("nr_empenho")), "data_pagamento": dt,
            "valor_pago": _dec(g("valor_pago")), "valor_retido": _dec(g("valor_retido")),
            "cod_retencao": _txt(g("cod_retencao")),
            "motivo_retencao": _txt(g("motivo_retencao")),
            "documento": _txt(g("documento")), "nr_liquidacao": _txt(g("nr_liquidacao")),
            "processo_empenho": _txt(g("processo_empenho")),
            "processo_liquidacao": _txt(g("processo_liquidacao")),
            "historico": _txt(g("historico")),
        }
        # "0000" sem motivo = linha sem retenção; não guardar o código vazio.
        if not linha["valor_retido"]:
            linha["cod_retencao"] = linha["motivo_retencao"] = None
            linha["tipo_retencao"] = None
        else:
            linha["tipo_retencao"] = tipo_retencao(linha["cod_retencao"], linha["motivo_retencao"])
        pl.linhas.append(linha)
        pl.total_pago += linha["valor_pago"]
        pl.total_retido += linha["valor_retido"]
        if dt and (pl.pago_ate is None or dt > pl.pago_ate):
            pl.pago_ate = dt
    if totais is None:
        raise ValueError(f"sem a linha TOTAIS ({len(pl.linhas)} linhas lidas) — arquivo cortado?")
    if abs(totais[0] - pl.total_pago) > Decimal("0.05") or \
            abs(totais[1] - pl.total_retido) > Decimal("0.05"):
        raise ValueError(f"soma das linhas ({pl.total_pago} pago, {pl.total_retido} retido) "
                         f"≠ TOTAIS ({totais[0]}, {totais[1]})")
    pl.total_pago, pl.total_retido = totais
    return pl


# ---------------------------------------------------------------------------
# Casamento: município (código estadual -> IBGE) e fundo × entidade
# ---------------------------------------------------------------------------
def codigos_dos_alvos(alvos: list[dict]) -> tuple[dict[int, dict], list[str]]:
    """({código estadual: alvo}, [nomes sem código]) — pelo IBGE, nunca o nome."""
    por_ibge = {v: k for k, v in CODIGO_ESTADUAL_PARA_IBGE.items()}
    out: dict[int, dict] = {}
    sem: list[str] = []
    for a in alvos:
        ibge = re.sub(r"\D", "", a.get("ibge") or "")
        cod = por_ibge.get(int(ibge)) if len(ibge) == 7 else None
        if cod is None:
            sem.append(f"{a['nome']} (IBGE {ibge or '?'})")
        else:
            out[cod] = a
    return out, sem


def fundos_por_municipio(linhas: list[dict]) -> dict[int, str]:
    """{código do município: Cód. Credor do Fundo Municipal} — o credor com mais
    linhas de 'Fundo a Fundo' (modalidade 41) sob aquele código (armadilha 6)."""
    votos: dict[int, Counter] = defaultdict(Counter)
    for ln in linhas:
        if (ln.get("cod_modalidade") or "").strip() == "41" and ln.get("cod_credor"):
            votos[ln["cod_municipio"]][ln["cod_credor"]] += 1
    return {cod: c.most_common(1)[0][0] for cod, c in votos.items()}


def registros(pl: Planilha, cod_para_alvo: dict[int, dict],
              fundos: dict[int, str]) -> list[dict]:
    out = []
    for ln in pl.linhas:
        alvo = cod_para_alvo.get(ln["cod_municipio"])
        if not alvo:
            continue
        out.append({**ln, "municipio_id": alvo["id"], "ano": pl.ano, "mes": pl.mes,
                    "fundo_municipal": bool(fundos.get(ln["cod_municipio"]))
                    and ln["cod_credor"] == fundos[ln["cod_municipio"]]})
    return out


def status_da_rodada(meses: int, falhas: list[str], sem_depara: list[str],
                     idade_dias: int | None) -> tuple[str, str | None]:
    """Zero não é cego: todo mês falhou => error; algum mês, município sem código
    ou fonte parada => partial com o motivo; o resto => success (inclusive o mês
    pulado por hash igual, que é a rodada normal)."""
    notas = list(falhas)
    if sem_depara:
        notas.append("sem código estadual (de-para) para " + ", ".join(sem_depara)
                     + " — regerar services/municipios_rs_codigo_estadual.py")
    if idade_dias is not None and idade_dias > IDADE_MAX_DIAS:
        notas.append(f"a SES não publica planilha nova há {idade_dias} dias")
    if meses and len(falhas) >= meses:
        return "error", " | ".join(notas)[:400]
    return ("partial" if notas else "success"), (" | ".join(notas)[:400] or None)


# ---------------------------------------------------------------------------
# Rede
# ---------------------------------------------------------------------------
def _baixar(client: httpx.Client, url: str) -> bytes:
    ultimo: Exception | None = None
    for _ in range(3):
        try:
            r = client.get(url, headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            return r.content
        except httpx.TransportError as e:
            ultimo = e
    raise ultimo or RuntimeError(url)


def _anos(hoje: date) -> list[int]:
    env = os.getenv("FES_RS_ANOS")
    if env:
        return sorted({int(x) for x in env.split(",") if x.strip().isdigit()})
    # Em janeiro/fevereiro o ano anterior ainda é republicado fechado (o de 2025
    # saiu de novo em 08/01/2026) e o ano novo pode nem ter arquivo.
    return [hoje.year - 1, hoje.year] if hoje.month <= 2 else [hoje.year]


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------
def _alvos(cur) -> list[dict]:
    cur.execute("""
        SELECT id, nome, coalesce(ibge_code, '')
          FROM municipios WHERE active AND upper(coalesce(uf, '')) = %s
         ORDER BY id
    """, (UF,))
    return [{"id": r[0], "nome": r[1], "ibge": (r[2] or "").strip()} for r in cur.fetchall()]


def _log_ingest(cur, conn, status: str, n: int, nota: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES (%s, %s, %s, %s, NOW())",
            (SOURCE, status, n, nota))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.warning("ingestion_log falhou: %s", str(e)[:120])


_CAMPOS = ("municipio_id", "ano", "mes", "cod_municipio", "crs", "credor", "cod_credor",
           "fundo_municipal", "cod_projeto", "projeto", "cod_subprojeto", "subprojeto",
           "cod_modalidade", "modalidade", "cod_recurso", "recurso", "fonte_recurso",
           "competencia_ano", "competencia_mes", "nr_empenho", "data_pagamento",
           "valor_pago", "valor_retido", "cod_retencao", "motivo_retencao",
           "tipo_retencao", "documento", "nr_liquidacao", "processo_empenho",
           "processo_liquidacao", "historico")
_COLS_SQL = ", ".join("cod_municipio_rs" if c == "cod_municipio" else c for c in _CAMPOS)


def grava_mes(cur, pl: Planilha, regs: list[dict], ids_alvo: list[int], url: str,
              publicado: datetime | None, sha: str, assinatura: str) -> None:
    """Apaga e insere o mês dos municípios do tenant — o chamador comita, e só
    chega aqui com a planilha lida inteira (armadilha 10)."""
    import psycopg2.extras
    cur.execute("DELETE FROM fes_rs_pagamentos WHERE ano = %s AND mes = %s "
                "AND municipio_id = ANY(%s)", (pl.ano, pl.mes, ids_alvo))
    if regs:
        psycopg2.extras.execute_values(
            cur, f"INSERT INTO fes_rs_pagamentos ({_COLS_SQL}) VALUES %s",
            [tuple(r[c] for c in _CAMPOS) for r in regs], page_size=500)
    cur.execute("""
        INSERT INTO fes_rs_arquivos (ano, mes, url, sha256, assinatura, publicado_em,
                                     pago_ate, linhas, total_pago, total_retido, lido_em)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (ano, mes) DO UPDATE SET
            url = EXCLUDED.url, sha256 = EXCLUDED.sha256, assinatura = EXCLUDED.assinatura,
            publicado_em = EXCLUDED.publicado_em, pago_ate = EXCLUDED.pago_ate,
            linhas = EXCLUDED.linhas, total_pago = EXCLUDED.total_pago,
            total_retido = EXCLUDED.total_retido, lido_em = NOW()
    """, (pl.ano, pl.mes, url, sha, assinatura, publicado, pl.pago_ate, len(pl.linhas),
          pl.total_pago, pl.total_retido))


def ingest(dry: bool = False) -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect

    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            alvos = _alvos(cur)
            if not alvos:
                log.info("nenhum município do RS — o FES gaúcho não se aplica")
                if not dry:
                    _log_ingest(cur, conn, "success", 0)
                return 0
            cod_para_alvo, sem_depara = codigos_dos_alvos(alvos)
            for s_ in sem_depara:
                log.warning("  sem código estadual: %s", s_)
            if not cod_para_alvo:
                status, nota = status_da_rodada(0, [], sem_depara, None)
                if not dry:
                    _log_ingest(cur, conn, status, 0, nota)
                return 0
            ids_alvo = [a["id"] for a in cod_para_alvo.values()]
            assinatura = f"v{VERSAO_LEITOR}|" + ",".join(
                sorted(a["ibge"] for a in cod_para_alvo.values()))
            cur.execute("SELECT ano, mes, sha256, assinatura FROM fes_rs_arquivos")
            lidos = {(r[0], r[1]): (r[2], r[3]) for r in cur.fetchall()}
            anos = _anos(date.today())

            falhas: list[str] = []
            planilhas: dict[tuple[int, int], tuple[Planilha, str, datetime, str]] = {}
            inalterados = 0
            with httpx.Client(follow_redirects=True) as client:   # guarda o cookie TS
                try:
                    p = client.get(PAGINA, headers=UA, timeout=60)
                    p.raise_for_status()
                    links = links_da_pagina(p.text)
                except Exception as e:
                    nota = f"página {PAGINA}: {type(e).__name__}: {str(e)[:150]}"
                    log.error(nota)
                    if not dry:
                        _log_ingest(cur, conn, "error", 0, nota)
                    return 0
                if not links:
                    nota = "a página não tem nenhum link '...-fesgeral.xls' — layout mudou?"
                    log.error(nota)
                    if not dry:
                        _log_ingest(cur, conn, "error", 0, nota)
                    return 0
                idade = (datetime.now() - max(pub for v in links.values()
                                              for _, pub in v)).days
                meses = sorted(k for k in links if k[0] in anos)
                log.info("página: %d mês(es) listados, %d do(s) ano(s) %s; mais novo "
                         "publicado há %d dia(s)", len(links), len(meses), anos, idade)
                for ano, mes in meses:
                    conteudo = url = pub = None
                    erros = []
                    for u, pb in links[(ano, mes)]:
                        try:
                            conteudo, url, pub = _baixar(client, u), u, pb
                            break
                        except httpx.HTTPStatusError as e:
                            erros.append(f"HTTP {e.response.status_code}")
                        except Exception as e:
                            erros.append(type(e).__name__)
                    if conteudo is None:
                        falhas.append(f"{mes:02d}/{ano}: {', '.join(erros)}")
                        continue
                    sha = hashlib.sha256(conteudo).hexdigest()
                    if lidos.get((ano, mes)) == (sha, assinatura):
                        inalterados += 1
                        continue
                    try:
                        planilhas[(ano, mes)] = (ler_planilha(conteudo, ano, mes), url, pub, sha)
                    except Exception as e:
                        falhas.append(f"{mes:02d}/{ano}: {type(e).__name__}: {str(e)[:120]}")
                        log.warning("  %02d/%d recusado: %s", mes, ano, e)

            # Fundo Municipal de cada município: pelo que se leu agora; sem
            # modalidade 41 nos meses relidos, o credor que já está gravado.
            fundos = fundos_por_municipio(
                [ln for pl, *_ in planilhas.values() for ln in pl.linhas
                 if ln["cod_municipio"] in cod_para_alvo])
            for cod, alvo in cod_para_alvo.items():
                if cod not in fundos:
                    cur.execute("""
                        SELECT cod_credor FROM fes_rs_pagamentos
                         WHERE municipio_id = %s AND fundo_municipal
                         GROUP BY cod_credor ORDER BY count(*) DESC LIMIT 1
                    """, (alvo["id"],))
                    r = cur.fetchone()
                    if r:
                        fundos[cod] = r[0]

            n = 0
            for (ano, mes), (pl, url, pub, sha) in sorted(planilhas.items()):
                regs = registros(pl, cod_para_alvo, fundos)
                for cod, alvo in cod_para_alvo.items():
                    doa = [r for r in regs if r["municipio_id"] == alvo["id"]]
                    f_ = sum(r["valor_pago"] for r in doa if r["fundo_municipal"])
                    o_ = sum(r["valor_pago"] for r in doa if not r["fundo_municipal"])
                    rt = sum(r["valor_retido"] for r in doa if r["fundo_municipal"])
                    log.info("  %02d/%d %s: %d linha(s); fundo R$ %s (retido %s); "
                             "hospitais/entidades R$ %s", mes, ano, alvo["nome"], len(doa),
                             f_, rt, o_)
                if dry:
                    continue
                grava_mes(cur, pl, regs, ids_alvo, url, pub, sha, assinatura)
                conn.commit()
                n += len(regs)
            status, nota = status_da_rodada(len(meses), falhas, sem_depara, idade)
            log.info("=== FES-RS: %d mês(es) relido(s), %d igual(is), %d falha(s), %d "
                     "linha(s) gravada(s), status=%s ===", len(planilhas), inalterados,
                     len(falhas), n, status)
            if not dry:
                _log_ingest(cur, conn, status, n, nota)
            return n
        except Exception as e:
            conn.rollback()
            log.error("FES-RS falhou: %s: %s", type(e).__name__, str(e)[:200])
            if not dry:
                _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ingest(dry="--dry" in sys.argv)
