"""
PDDE (Programa Dinheiro Direto na Escola, FNDE) — o SALDO parado na conta de cada
escola e a SITUAÇÃO de cada escola para receber a próxima parcela.

O PDDE é depositado pelo FNDE na conta de cada ESCOLA — da caixa escolar/APM (a
UEx, unidade executora) ou, quando a escola não tem uma, da prefeitura (a EEx,
entidade executora). O que o PACTHA não mostrava: quanto ficou PARADO nessas contas
(dinheiro que a escola não gastou) e quais escolas estão SUSPENSAS — a próxima
parcela que não vem. O dinheiro que ENTROU são as liberações do FNDE por entidade
(`simec_par_liberacoes`, da consulta `pls/simad` de `fnde_liberacoes.py`) e não é
coletado de novo aqui: a tela soma os dois pelo CNPJ da caixa escolar. (O arquivo de
transferências da CGU também traz o PDDE, ação 0515, na tela «Recursos recebidos por
pasta» — mas só as caixas que vêm com o código do município.)

Fonte (sem login, sem captcha, GET simples; a VPS responde 200 — medido 24/09/2026):
    https://www.fnde.gov.br/pddeinfo/  -> três relatórios, cada um com um botão
    "Gerar Relatório Excel" que devolve um .xlsx com TUDO (sem paginar):
      consultasaldoentidade/consultasaldoentidade/excel      (saldo por conta, mês)
      situacaoprestacaoconta/situacaoprestacaoconta/excel    (PC por escola, ano)
      relatoriosuspensao/relatoriosuspensao/excel            (suspensões, ano)
    O município vai como `co_municipio_fnde` = IBGE com 6 dígitos (Monte Sião
    314340, Nova Palma 431310) e `sg_uf`.

Medido para conferência (24-25/09/2026): Monte Sião, saldo de 08/2026 — 46 linhas,
16 CNPJs (13 caixas escolares municipais, 1 estadual, a APAE e a prefeitura);
situação da PC de 2025 — 29 linhas (escola × programa), todas adimplentes; nenhuma
suspensão em 2025 e duas em 2026 (a APAE, "Entidade não habilitada"). Santa Maria:
404 contas com todos os programas; 92 suspensões em 2026 (48 "UEX sem dirigente ativo", 17 delas em escola
MUNICIPAL). Nova Palma: 2 suspensões em 2026, ambas de escola ESTADUAL.

AS ARMADILHAS, medidas em 24-25/09/2026:

1. ⚠️ **A LISTAGEM HTML PAGINA DE 10 EM 10; A EXPORTAÇÃO TRAZ TUDO.** O botão de
   Excel está no HTML de resultado (escondido por `$('#gerarrelatorioexcel').hide()`
   no formulário, visível como ícone na barra de resultado). Conferido: o .xlsx tem
   exatamente o total que a listagem anuncia ("1-10 de 46 itens" → 46 linhas; 387
   em Santa Maria; 29 na PC; 92 nas suspensões). A exportação do ESTADO inteiro (MG,
   37.533 linhas, 18,7 s, 2,7 MB) também veio completa — mas sem código de
   município, só o NOME; por isso a consulta é por município, pelo código.

2. ⚠️ **PROGRAMA VAZIO NÃO É "TODOS".** O saldo com `co_programa` vazio usa um
   padrão do servidor com CINCO programas (PDDE, Equidade, Qualidade, Educação
   Especial = `A3`, PDE-Escola) — o cabeçalho da planilha diz quais —, e o seletor
   da tela lista 19 (Educação Integral, Ensino Médio, Emergencial...). O coletor
   manda a lista explícita: o seletor ∪ o padrão. Medido em 08/2026: Santa Maria
   passa de 387 para 404 contas (17 de "PDDE-Educação Integral") e Nova Palma
   ganha 2; Monte Sião não muda (46).
   ⚠️ O formulário é ISO-8859-1 (os códigos são ASCII; os rótulos vêm quebrados).

3. ⚠️ **MÊS NÃO PUBLICADO DÁ 200 COM ZERO LINHAS** — igual a "município sem conta".
   Em 24/09 o mais novo era 08/2026, e pedir 09/2026 devolveu a planilha só com o
   cabeçalho. O mês pedido sai SEMPRE do seletor do formulário (`<select
   name="mes">`), nunca da data de hoje. Mês listado e planilha sem linha nenhuma =
   `partial`, nada apagado.

4. ⚠️ **A MESMA CONTA APARECE DUAS VEZES, COM O MESMO SALDO**, quando a caixa escolar
   atende escola de duas redes (na exportação de MG: 45 contas, "MUNICIPAL" numa
   linha e "ESTADUAL" na outra; a prefeitura como EEx de escola municipal e
   particular). Somar as linhas contaria o mesmo dinheiro de novo. A gravação é
   UMA linha por (CNPJ, banco, agência, conta, programa), com as redes numa lista;
   saldo diferente na mesma conta é recusado (nunca medido).

5. ⚠️ **A REDE DECIDE DE QUEM É O DINHEIRO.** Metade das contas de um município pode
   ser de escola ESTADUAL (Santa Maria: 142 de 387) — a "Caixa Escolar Renato Franco
   Bueno", com R$ 62.167,73 parados em fundos em Monte Sião, é a UEx de uma escola
   estadual (EE Provedor Theofilo Tavares Paes), não da prefeitura. O saldo e a
   suspensão trazem "Rede de Ensino" na linha; a PC NÃO traz (só no cabeçalho, quando
   se filtra): o coletor pede a PC duas vezes — todas as redes e só a MUNICIPAL
   (`esferaAdm=2`) — e marca `municipal` pela segunda. A tela conta a rede
   municipal e mostra as outras à parte.

6. ⚠️ **A "SITUAÇÃO DA PC" DIZ ADIMPLENTE ONDE O RELATÓRIO DE SUSPENSÃO DIZ
   INADIMPLENTE.** Santa Maria 2026: as 235 linhas da PC dizem "Adimplente"/"NAO",
   e o relatório de suspensão tem 7 "Inadimplente (UEX)" e 48 "UEX sem dirigente
   ativo". A situação da PC é a posição em 01/01; o que trava a PRÓXIMA parcela é o
   relatório de suspensão (por parcela e motivo). Os dois são gravados; a tela usa
   a suspensão para o alerta.

7. **O MUNICÍPIO É CONFERIDO NA PRÓPRIA PLANILHA.** Código que não é do município
   ou UF trocada dá **400** "Um ou mais municípios não pertencem às UFs
   selecionadas." (o filtro não é ignorado em silêncio — provado com 999999 e com
   314340 em RS). O cabeçalho repete "Município: MONTE SIAO (MG)" e o ano/mês; toda
   linha tem de ter a mesma UF e o mesmo nome do cabeçalho, e o ano/mês pedido, ou
   a planilha é recusada.

8. **O EXCEL PODE SAIR COMO TEXTO DE ERRO.** O consolidado da PC de 2025 respondeu
   **500** com "Erro ao gerar arquivo Excel: ... ORA-01722: invalid number" (é por
   isso que se usa o DETALHADO por escola, que respondeu 200 nos anos medidos).
   Resposta que não é um .xlsx (não começa com "PK") é falha, nunca "zero linha".

9. **VALORES SÃO TEXTO** ("7.703,33") e o "Mês/Ano" do saldo é só o mês ("8"): o
   ano sai do cabeçalho ("Mês: 08/2026"). Colunas lidas por NOME; faltando uma, a
   planilha é recusada (`partial`, com o nome).

10. **SUSPENSÃO ZERO É RESPOSTA** (Monte Sião 2025: nenhuma) e é gravada — a
   planilha veio com o cabeçalho e o município. PC sem nenhuma escola e saldo sem
   nenhuma conta não são plausíveis para um município com escola: `partial`, nada
   apagado, a próxima rodada tenta de novo.

CUSTO (medido do Brasil, 24-25/09/2026): cada planilha de um município leva 0,4 a
2,7 s (uma resposta de 15,5 s isolada); o formulário, 0,5-2,4 s. Por município e
por noite, depois da carga inicial: suspensão do ano (1) + PC do ano (2) = 3
planilhas, ~5 s + pausas de `PDDE_PAUSA_S` (1,5 s). O saldo do mês mais novo entra
uma vez por mês (e é relido a cada `PDDE_RELER_DIAS`); o ano anterior (PC e
suspensão) é relido a cada `PDDE_RELER_DIAS` (7); a carga inicial do saldo
(`PDDE_MESES` = 12 meses) anda `PDDE_CARGA_POR_RODADA` (2) meses por município por
noite. A rodada faz primeiro o que é DIÁRIO de todo município e só depois a fila
(ano anterior, histórico) — estourar o orçamento `PDDE_BUDGET_S` na parte diária é
`partial` (município sem visita hoje); na fila, é só a fila.

Rodável por Scheduled Task em todo worker (fonte federal), ou à mão:
    python -u ingestion/pdde_info.py
    python -u ingestion/pdde_info.py --dry     # baixa, lê e resume, sem gravar
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("pdde_info")

FONTE = "pdde_info"
BASE = "https://www.fnde.gov.br/pddeinfo"
FORM_SALDO = f"{BASE}/consultasaldoentidade/consultasaldoentidade/consultasaldoentidade"
XLS_SALDO = f"{BASE}/consultasaldoentidade/consultasaldoentidade/excel"
XLS_PC = f"{BASE}/situacaoprestacaoconta/situacaoprestacaoconta/excel"
XLS_SUSP = f"{BASE}/relatoriosuspensao/relatoriosuspensao/excel"
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0; dados abertos FNDE)"}
TIMEOUT = 90

# Armadilha 2: o padrão do servidor quando `co_programa` vai vazio (lido do
# cabeçalho da planilha em 24/09/2026). Somado aos códigos do seletor da tela.
PROGRAMAS_PADRAO = ("02", "A3", "0B", "0A", "96")

PAUSA_S = float(os.getenv("PDDE_PAUSA_S") or 1.5)
ORCAMENTO_S = int(os.getenv("PDDE_BUDGET_S") or 420)
MESES = int(os.getenv("PDDE_MESES") or 12)
CARGA_POR_RODADA = int(os.getenv("PDDE_CARGA_POR_RODADA") or 2)
RELER_DIAS = int(os.getenv("PDDE_RELER_DIAS") or 7)

BRT = timezone(timedelta(hours=-3))

# As colunas de cada planilha, com o nome que a fonte publica (armadilha 9).
COLUNAS = {
    "saldo": ("UF", "Município", "Rede de Ensino", "CNPJ", "Razão Social", "Banco",
              "Agência", "Conta", "Mês/Ano", "Saldo Conta", "Saldo Fundos",
              "Saldo Poupança", "Saldo RDB/CDB", "Descrição Programa FNDE"),
    "prestacao": ("Ano", "Programa", "UF", "Município", "Entidade Executora - EEx",
                  "CNPJ EEx", "Situação Prestação de Contas EEx",
                  "Suspensão de Pagamento EEx", "Nome da Escola", "Código da Escola",
                  "CNPJ da Executora", "Situação Prestação de Contas UEx",
                  "Suspensão de Pagamento UEx", "Valor Total Previsto"),
    "suspensao": ("UF", "Município", "Rede de Ensino", "Programa", "Destinação",
                  "Cód. Escola", "Escola", "CNPJ", "Razão Social", "Tipo Suspensão"),
}


class PlanilhaRecusada(Exception):
    """A resposta não é a planilha pedida (erro da fonte, layout, outro município)."""


# ---------------------------------------------------------------------------
# Texto e números
# ---------------------------------------------------------------------------
def sem_acento(s) -> str:
    t = unicodedata.normalize("NFD", str(s or ""))
    return re.sub(r"\s+", " ", "".join(c for c in t if unicodedata.category(c) != "Mn")).strip()


def _chave(s) -> str:
    return sem_acento(s).lower()


def _txt(v) -> str | None:
    s = str(v).strip() if v is not None else ""
    return re.sub(r"\s+", " ", s) or None


def _dec(v) -> Decimal | None:
    """ "7.703,33" -> 7703.33 (armadilha 9). Número nativo também serve."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return Decimal(str(round(v, 2)))
    s = str(v).strip().replace("R$", "").strip()
    if not s:
        return None
    try:
        return Decimal(s.replace(".", "").replace(",", ".")) if "," in s else Decimal(s)
    except InvalidOperation:
        return None


def _doc(v, tam: int = 14) -> str | None:
    d = re.sub(r"\D", "", str(v or ""))
    if not d:
        return None
    return d.zfill(tam) if len(d) < tam else d


def _inep(v) -> str | None:
    d = re.sub(r"\D", "", str(v or ""))
    return d or None


def sim_nao(v) -> bool | None:
    t = _chave(v)
    return True if t in ("sim", "s") else False if t in ("nao", "n") else None


def rede_de(v) -> str:
    """"ADMINISTRAÇÃO PÚBLICA MUNICIPAL" -> municipal (armadilha 5)."""
    t = sem_acento(v).upper()
    if "MUNICIPAL" in t:
        return "municipal"
    if "ESTADUAL" in t:
        return "estadual"
    if "FEDERAL" in t:
        return "federal"
    if "PARTICULAR" in t or "PRIVAD" in t:
        return "particular"
    return "outra"


def hoje_brasilia() -> date:
    return datetime.now(BRT).date()


def mes_menos(m: date, n: int) -> date:
    a, b = divmod(m.year * 12 + (m.month - 1) - n, 12)
    return date(a, b + 1, 1)


# ---------------------------------------------------------------------------
# O formulário: meses publicados e códigos de programa
# ---------------------------------------------------------------------------
def _select(html: str, nome: str) -> str:
    m = re.search(rf'<select[^>]*name="{re.escape(nome)}"[^>]*>(.*?)</select>', html or "",
                  re.S | re.I)
    return m.group(1) if m else ""


def meses_publicados(html: str) -> list[date]:
    """Os meses do seletor do saldo, do mais novo para o mais velho (armadilha 3)."""
    meses = {date(int(a), int(m), 1)
             for m, a in re.findall(r'value="(\d{2})-(\d{4})"', _select(html, "mes"))
             if 1 <= int(m) <= 12}
    return sorted(meses, reverse=True)


def programas_do_formulario(html: str) -> list[str]:
    """Os códigos do seletor ∪ o padrão do servidor (armadilha 2), em ordem estável."""
    cods = re.findall(r'value="([0-9A-Z]{2})"', _select(html, "co_programa_fnde"))
    return sorted(set(cods) | set(PROGRAMAS_PADRAO))


# ---------------------------------------------------------------------------
# A planilha
# ---------------------------------------------------------------------------
@dataclass
class Planilha:
    meta: dict[str, str]
    linhas: list[dict[str, str | None]]


def ler_planilha(conteudo: bytes, relatorio: str) -> Planilha:
    """O .xlsx de um relatório -> cabeçalho ("Mês", "Ano", "UF", "Município"...) e
    linhas por nome de coluna (chave sem acento, minúscula). Armadilhas 8 e 9."""
    if not conteudo or conteudo[:2] != b"PK":
        texto = (conteudo or b"")[:200].decode("utf-8", "replace").strip()
        raise PlanilhaRecusada(f"a fonte não devolveu planilha: {texto or 'resposta vazia'}")
    import openpyxl
    ws = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True).worksheets[0]
    exigidas = [_chave(c) for c in COLUNAS[relatorio]]
    meta: dict[str, str] = {}
    cab: list[str] | None = None
    linhas: list[dict[str, str | None]] = []
    for r in ws.iter_rows(values_only=True):
        vals = [_txt(v) for v in r]
        if not any(vals):
            continue
        if cab is None:
            nomes = [_chave(v) for v in vals]
            if all(c in nomes for c in exigidas[:3]):
                faltam = [COLUNAS[relatorio][i] for i, c in enumerate(exigidas) if c not in nomes]
                if faltam:
                    raise PlanilhaRecusada(f"colunas ausentes na planilha de {relatorio}: {faltam}")
                cab = nomes
                continue
            texto = next((v for v in vals if v), "")
            if ":" in texto:
                k, _, v = texto.partition(":")
                meta[sem_acento(k).lower()] = v.strip()
            continue
        linhas.append({cab[i]: vals[i] if i < len(vals) else None
                       for i in range(len(cab)) if cab[i]})
    if cab is None:
        raise PlanilhaRecusada(f"planilha de {relatorio} sem a linha de cabeçalho")
    return Planilha(meta, linhas)


def confere(p: Planilha, uf: str, *, mes: date | None = None, ano: int | None = None) -> str:
    """Armadilha 7: a planilha é do município, da UF e do período pedidos? Devolve o
    nome do município como a fonte o escreve."""
    mun = p.meta.get("municipio") or ""
    m = re.match(r"(.+?)\s*\(([A-Z]{2})\)\s*$", mun)
    if not m or m.group(2) != uf:
        raise PlanilhaRecusada(f"cabeçalho sem o município da UF {uf}: {mun!r}")
    nome = sem_acento(m.group(1)).upper()
    if mes is not None and p.meta.get("mes") != f"{mes.month:02d}/{mes.year}":
        raise PlanilhaRecusada(f"mês do cabeçalho {p.meta.get('mes')!r} ≠ {mes:%m/%Y}")
    if ano is not None and p.meta.get("ano") != str(ano):
        raise PlanilhaRecusada(f"ano do cabeçalho {p.meta.get('ano')!r} ≠ {ano}")
    for x in p.linhas:
        if (x.get("uf") or "") != uf or sem_acento(x.get("municipio")).upper() != nome:
            raise PlanilhaRecusada(
                f"linha de outro município na planilha: {x.get('municipio')}/{x.get('uf')}")
        if ano is not None and x.get("ano") is not None and x.get("ano") != str(ano):
            raise PlanilhaRecusada(f"linha de outro ano na planilha: {x.get('ano')}")
        if mes is not None and x.get("mes/ano") not in (None, str(mes.month),
                                                         f"{mes.month:02d}"):
            raise PlanilhaRecusada(f"linha de outro mês na planilha: {x.get('mes/ano')}")
    return nome


def contas_do_saldo(linhas: list[dict]) -> dict[tuple, dict]:
    """Uma entrada por conta (armadilha 4): (cnpj, banco, agência, conta, programa)."""
    contas: dict[tuple, dict] = {}
    for x in linhas:
        cnpj = _doc(x.get("cnpj"))
        banco, ag, conta = (_txt(x.get(k)) or "" for k in ("banco", "agencia", "conta"))
        prog = _txt(x.get("descricao programa fnde")) or ""
        if not cnpj or not conta:
            raise PlanilhaRecusada(f"linha de saldo sem CNPJ ou conta: {x}")
        valores = tuple(_dec(x.get(k)) for k in
                        ("saldo conta", "saldo fundos", "saldo poupanca", "saldo rdb/cdb"))
        if any(v is None for v in valores):
            raise PlanilhaRecusada(f"saldo ilegível na conta {banco}/{ag}/{conta}: {x}")
        k = (cnpj, banco, ag, conta, prog)
        rede = rede_de(x.get("rede de ensino"))
        c = contas.get(k)
        if c is None:
            contas[k] = {"cnpj": cnpj, "razao_social": _txt(x.get("razao social")),
                         "banco": banco, "agencia": ag, "conta": conta, "programa": prog,
                         "redes": [rede], "valores": valores}
            continue
        if c["valores"] != valores:
            raise PlanilhaRecusada(f"a conta {banco}/{ag}/{conta} ({prog}) veio com dois "
                                   f"saldos diferentes: {c['valores']} e {valores}")
        if rede not in c["redes"]:
            c["redes"].append(rede)
    return contas


def linhas_da_prestacao(todas: list[dict], municipais: list[dict]) -> list[dict]:
    """A PC de todas as redes, com `municipal` marcado pela consulta filtrada
    (armadilha 5). Linha municipal que não está na consulta completa = recusa."""
    def k(x):
        return (_inep(x.get("codigo da escola")), _txt(x.get("programa")),
                _doc(x.get("cnpj da executora")), _doc(x.get("cnpj eex")))
    mun = {k(x) for x in municipais}
    ks = [k(x) for x in todas]
    sobra = mun - set(ks)
    if sobra:
        raise PlanilhaRecusada(f"{len(sobra)} linha(s) da PC municipal fora da PC completa")
    return [{
        "programa": _txt(x.get("programa")),
        "escola_inep": _inep(x.get("codigo da escola")),
        "escola_nome": _txt(x.get("nome da escola")),
        "eex_cnpj": _doc(x.get("cnpj eex")),
        "eex_nome": _txt(x.get("entidade executora - eex")),
        "eex_situacao": _txt(x.get("situacao prestacao de contas eex")),
        "eex_suspensa": sim_nao(x.get("suspensao de pagamento eex")),
        "uex_cnpj": _doc(x.get("cnpj da executora")),
        "uex_situacao": _txt(x.get("situacao prestacao de contas uex")),
        "uex_suspensa": sim_nao(x.get("suspensao de pagamento uex")),
        "valor_previsto": _dec(x.get("valor total previsto")),
        "municipal": kk in mun,
    } for x, kk in zip(todas, ks)]


def linhas_da_suspensao(linhas: list[dict]) -> list[dict]:
    out = []
    for x in linhas:
        tipo = _txt(x.get("tipo suspensao"))
        if not tipo:
            raise PlanilhaRecusada(f"suspensão sem tipo: {x}")
        out.append({
            "rede": rede_de(x.get("rede de ensino")),
            "programa": _txt(x.get("programa")),
            "destinacao": _txt(x.get("destinacao")),
            "escola_inep": _inep(x.get("cod. escola")),
            "escola_nome": _txt(x.get("escola")),
            "uex_cnpj": _doc(x.get("cnpj")),
            "uex_nome": _txt(x.get("razao social")),
            "tipo": tipo,
        })
    return out


# ---------------------------------------------------------------------------
# O que pedir a cada município nesta rodada
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Pedido:
    relatorio: str          # saldo | prestacao | suspensao
    referencia: date        # 1º do mês (saldo) ou 01/01 do ano
    diario: bool            # parte do "todo município todo dia"


def pedidos(hoje: date, meses: list[date], cargas: dict[tuple[str, date], datetime | date],
            janela: int = MESES, carga_por_rodada: int = CARGA_POR_RODADA,
            reler_dias: int = RELER_DIAS) -> list[Pedido]:
    """A fila de UM município, na ordem em que deve ser pedida.

    `cargas`: {(relatorio, referencia): quando foi carregado}. Diário: suspensão e
    PC do ano corrente, sempre; saldo do mês mais novo publicado quando não está
    carregado ou ficou velho. Fila: o ano anterior velho e até `carga_por_rodada`
    meses de saldo da janela que faltam, do mais novo para o mais velho."""
    def velho(chave) -> bool:
        quando = cargas.get(chave)
        if quando is None:
            return True
        d = quando.date() if isinstance(quando, datetime) else quando
        return (hoje - d).days >= reler_dias

    ano = hoje.year
    out = [Pedido("suspensao", date(ano, 1, 1), True),
           Pedido("prestacao", date(ano, 1, 1), True)]
    mais_novo = meses[0] if meses else None
    if mais_novo and velho(("saldo", mais_novo)):
        out.append(Pedido("saldo", mais_novo, True))
    for rel in ("suspensao", "prestacao"):
        if velho((rel, date(ano - 1, 1, 1))):
            out.append(Pedido(rel, date(ano - 1, 1, 1), False))
    if mais_novo:
        limite = mes_menos(mais_novo, janela - 1)
        faltam = [m for m in meses[1:] if m >= limite and ("saldo", m) not in cargas]
        out += [Pedido("saldo", m, False) for m in faltam[:carga_por_rodada]]
    return out


# ---------------------------------------------------------------------------
# Rede
# ---------------------------------------------------------------------------
def baixar(client: httpx.Client, url: str, params: dict) -> bytes:
    """Uma planilha. 5xx e timeout ganham UMA segunda tentativa; 400 não (é a
    fonte dizendo que o pedido está errado — armadilha 7)."""
    for tentativa in (1, 2):
        try:
            r = client.get(url, params=params)
        except httpx.TimeoutException:
            if tentativa == 2:
                raise PlanilhaRecusada(f"tempo esgotado ({TIMEOUT} s) em {url.rsplit('/', 3)[-3]}")
            time.sleep(5)
            continue
        except httpx.HTTPError as e:
            raise PlanilhaRecusada(f"{type(e).__name__}: {str(e)[:120]}")
        if r.status_code == 200:
            return r.content
        if r.status_code >= 500 and tentativa == 1:
            time.sleep(5)
            continue
        raise PlanilhaRecusada(f"HTTP {r.status_code}: {r.text[:160].strip()}")
    raise PlanilhaRecusada("sem resposta")


@dataclass
class Alvo:
    id: int
    nome: str
    ibge: str
    uf: str

    @property
    def codigo_fnde(self) -> str:
        return self.ibge[:6]


def ler(client: httpx.Client, a: Alvo, p: Pedido, programas: list[str]) -> tuple[list, int]:
    """(o que gravar, planilhas baixadas) de um pedido. Levanta PlanilhaRecusada."""
    base = {"sg_uf": a.uf, "co_municipio_fnde": a.codigo_fnde}
    if p.relatorio == "saldo":
        plan = ler_planilha(baixar(client, XLS_SALDO, {
            **base, "mes_referencia": f"{p.referencia:%m-%Y}", "cnpj": "", "esferaAdm": "",
            "co_programa": ",".join(f"'{c}'" for c in programas)}), "saldo")
        confere(plan, a.uf, mes=p.referencia)
        return list(contas_do_saldo(plan.linhas).values()), 1
    if p.relatorio == "suspensao":
        plan = ler_planilha(baixar(client, XLS_SUSP, {
            **base, "ano": p.referencia.year, "programa": "", "cnpj": "", "co_escola": ""}),
            "suspensao")
        confere(plan, a.uf, ano=p.referencia.year)
        return linhas_da_suspensao(plan.linhas), 1
    params = {**base, "an_exercicio": p.referencia.year, "cnpj": "", "co_escola": "",
              "programas": "", "tpRelatorio": 1}
    todas = ler_planilha(baixar(client, XLS_PC, {**params, "esferaAdm": ""}), "prestacao")
    confere(todas, a.uf, ano=p.referencia.year)
    time.sleep(PAUSA_S)
    mun = ler_planilha(baixar(client, XLS_PC, {**params, "esferaAdm": 2}), "prestacao")
    confere(mun, a.uf, ano=p.referencia.year)
    if "MUNICIPAL" not in sem_acento(mun.meta.get("rede de ensino")).upper():
        raise PlanilhaRecusada("a PC filtrada pela rede municipal não diz a rede no cabeçalho "
                               f"({mun.meta.get('rede de ensino')!r}) — o filtro mudou?")
    return linhas_da_prestacao(todas.linhas, mun.linhas), 2


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------
def _alvos(cur) -> list[Alvo]:
    """Todo município ativo, o que está há mais tempo sem visita primeiro."""
    cur.execute("""
        SELECT m.id, m.nome, coalesce(m.ibge_code::text, ''), upper(coalesce(m.uf, ''))
          FROM municipios m
          LEFT JOIN (SELECT municipio_id, max(carregado_em) AS ultima
                       FROM pdde_carga GROUP BY municipio_id) c ON c.municipio_id = m.id
         WHERE m.active
         ORDER BY c.ultima NULLS FIRST, m.id
    """)
    return [Alvo(mid, nome, re.sub(r"\D", "", ibge), uf) for mid, nome, ibge, uf in cur.fetchall()]


# UF pelo código IBGE (os 2 primeiros dígitos) — a chave é o IBGE, nunca o nome.
UF_DO_IBGE = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
    "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}


def _cargas(cur, mid: int) -> dict[tuple[str, date], datetime]:
    cur.execute("SELECT relatorio, referencia, carregado_em FROM pdde_carga "
                "WHERE municipio_id = %s", (mid,))
    return {(r, ref): quando for r, ref, quando in cur.fetchall()}


def _registra_carga(cur, mid: int, p: Pedido, linhas: int) -> None:
    cur.execute("""
        INSERT INTO pdde_carga (municipio_id, relatorio, referencia, linhas, carregado_em)
        VALUES (%s, %s, %s, %s, NOW())
        ON CONFLICT (municipio_id, relatorio, referencia)
        DO UPDATE SET linhas = EXCLUDED.linhas, carregado_em = NOW()
    """, (mid, p.relatorio, p.referencia, linhas))


def grava(cur, mid: int, p: Pedido, regs: list[dict]) -> tuple[int, str | None]:
    """Troca o (município, referência) do relatório INTEIRO. (gravadas, recusa).
    Quem chama faz o commit — uma transação por pedido."""
    from psycopg2.extras import execute_values
    if not regs and p.relatorio != "suspensao":
        # Armadilha 10: saldo sem conta / PC sem escola não é resposta plausível.
        return 0, (f"{p.relatorio} {p.referencia:%m/%Y}: planilha sem nenhuma linha — "
                   "nada apagado")
    if p.relatorio == "saldo":
        cur.execute("DELETE FROM pdde_saldo WHERE municipio_id = %s AND mes = %s",
                    (mid, p.referencia))
        execute_values(cur, """
            INSERT INTO pdde_saldo (municipio_id, mes, cnpj, razao_social, banco, agencia,
                conta, programa, redes, saldo_conta, saldo_fundos, saldo_poupanca,
                saldo_rdb_cdb) VALUES %s""",
            [(mid, p.referencia, c["cnpj"], c["razao_social"], c["banco"], c["agencia"],
              c["conta"], c["programa"], c["redes"], *c["valores"]) for c in regs])
    elif p.relatorio == "prestacao":
        cur.execute("DELETE FROM pdde_prestacao WHERE municipio_id = %s AND ano = %s",
                    (mid, p.referencia.year))
        cols = ("programa", "escola_inep", "escola_nome", "eex_cnpj", "eex_nome",
                "eex_situacao", "eex_suspensa", "uex_cnpj", "uex_situacao", "uex_suspensa",
                "valor_previsto", "municipal")
        execute_values(cur, f"INSERT INTO pdde_prestacao (municipio_id, ano, {', '.join(cols)}) "
                            "VALUES %s",
                       [(mid, p.referencia.year, *(x[c] for c in cols)) for x in regs])
    else:
        cur.execute("DELETE FROM pdde_suspensao WHERE municipio_id = %s AND ano = %s",
                    (mid, p.referencia.year))
        cols = ("rede", "programa", "destinacao", "escola_inep", "escola_nome", "uex_cnpj",
                "uex_nome", "tipo")
        if regs:
            execute_values(cur, f"INSERT INTO pdde_suspensao (municipio_id, ano, "
                                f"{', '.join(cols)}) VALUES %s",
                           [(mid, p.referencia.year, *(x[c] for c in cols)) for x in regs])
    _registra_carga(cur, mid, p, len(regs))
    return len(regs), None


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
@dataclass
class Rodada:
    gravadas: int = 0
    planilhas: int = 0
    lidos: int = 0          # pedidos lidos inteiros (gravados, ou só lidos em --dry)
    recusados: int = 0
    parcial: bool = False
    notas: list[str] = field(default_factory=list)
    sem_visita: list[str] = field(default_factory=list)
    fila_adiada: int = 0


def ingest(dry: bool = False) -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect

    t0 = time.monotonic()
    rod = Rodada()
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            alvos = _alvos(cur)
            if not alvos:
                if not dry:
                    _log_ingest(cur, conn, "success", 0, "nenhum município ativo")
                return 0
            hoje = hoje_brasilia()
            with httpx.Client(follow_redirects=True, headers=UA, timeout=TIMEOUT) as client:
                form = client.get(FORM_SALDO)
                form.raise_for_status()
                meses = meses_publicados(form.text)
                programas = programas_do_formulario(form.text)
                if not meses:
                    raise PlanilhaRecusada("o formulário do saldo não lista mais nenhum mês "
                                           "(`select name=mes`) — o layout mudou?")
                log.info("PDDE Info: saldo publicado até %s; %d programa(s); %d município(s)",
                         f"{meses[0]:%m/%Y}", len(programas), len(alvos))

                validos: list[tuple[Alvo, list[Pedido]]] = []
                for a in alvos:
                    uf = UF_DO_IBGE.get(a.ibge[:2], "")
                    if len(a.ibge) < 6 or not uf:
                        rod.parcial = True
                        rod.notas.append(f"{a.nome}: sem código IBGE válido ({a.ibge or '—'})")
                        continue
                    if a.uf and a.uf != uf:
                        rod.parcial = True
                        rod.notas.append(f"{a.nome}: UF {a.uf} ≠ UF do IBGE {a.ibge} ({uf})")
                        continue
                    a.uf = uf
                    validos.append((a, pedidos(hoje, meses, _cargas(cur, a.id))))

                # Primeiro o DIÁRIO de todo município; depois a fila (ver CUSTO).
                for diario in (True, False):
                    for a, fila in validos:
                        for p in (x for x in fila if x.diario is diario):
                            if time.monotonic() - t0 > ORCAMENTO_S:
                                if diario:
                                    if a.nome not in rod.sem_visita:
                                        rod.sem_visita.append(a.nome)
                                else:
                                    rod.fila_adiada += 1
                                continue
                            if rod.planilhas:
                                time.sleep(PAUSA_S)
                            _um_pedido(cur, conn, client, a, p, programas, rod, dry)
            return _fecha(cur, conn, rod, meses, dry)
        except Exception as e:
            conn.rollback()
            log.error("PDDE Info falhou: %s: %s", type(e).__name__, str(e)[:200])
            if not dry:
                _log_ingest(cur, conn, "error", rod.gravadas, f"{type(e).__name__}: {str(e)[:380]}")
            raise
        finally:
            cur.close()


def _um_pedido(cur, conn, client, a: Alvo, p: Pedido, programas: list[str], rod: Rodada,
               dry: bool) -> None:
    rotulo = f"{a.nome} {p.relatorio} {p.referencia:%m/%Y}" if p.relatorio == "saldo" \
        else f"{a.nome} {p.relatorio} {p.referencia.year}"
    t = time.monotonic()
    try:
        regs, n = ler(client, a, p, programas)
    except PlanilhaRecusada as e:
        rod.planilhas += 1
        rod.recusados += 1
        rod.parcial = True
        rod.notas.append(f"{rotulo}: {e}")
        log.warning("%s: recusada — %s", rotulo, e)
        return
    rod.planilhas += n
    rod.lidos += 1
    if dry:
        log.info("%s: %d linha(s) (%.1f s)", rotulo, len(regs), time.monotonic() - t)
        return
    try:
        gravadas, recusa = grava(cur, a.id, p, regs)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if recusa:
        rod.parcial = True
        rod.notas.append(f"{a.nome} {recusa}")
    rod.gravadas += gravadas
    log.info("%s: %d linha(s) (%.1f s)", rotulo, gravadas, time.monotonic() - t)


def _fecha(cur, conn, rod: Rodada, meses: list[date], dry: bool) -> int:
    if rod.sem_visita:
        rod.parcial = True
        rod.notas.insert(0, f"orçamento de {ORCAMENTO_S} s estourado: {len(rod.sem_visita)} "
                            f"município(s) sem a visita diária ({', '.join(rod.sem_visita[:5])})")
    if rod.fila_adiada:
        rod.notas.append(f"fila: {rod.fila_adiada} pedido(s) (ano anterior/histórico do saldo) "
                         "para a próxima rodada")
    if dry:
        return 0
    # Nenhum pedido lido e algum recusado = a fonte não respondeu a NADA (host fora,
    # bloqueio): `error`, não um `partial` que se confunde com um dia comum.
    status = ("error" if rod.recusados and not rod.lidos
              else "partial" if rod.parcial else "success")
    nota = " | ".join([f"saldo publicado até {meses[0]:%m/%Y}; {rod.planilhas} planilha(s)"]
                      + rod.notas)[:400]
    log.info("=== PDDE Info: %d linha(s), status=%s (%s) ===", rod.gravadas, status, nota)
    _log_ingest(cur, conn, status, rod.gravadas, nota)
    return rod.gravadas


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="baixa, lê e resume, sem gravar")
    ingest(dry=ap.parse_args().dry)
