"""
Liberações do FNDE por ENTIDADE do município — a consulta legada `pls/simad`.

    POST https://www.fnde.gov.br/pls/simad/internet_fnde.liberacoes_result_pc
         p_ano=AAAA  p_uf=UF  p_municipio=IBGE6        -> LISTA de entidades
    GET  ...liberacoes_result_pc?p_ano=AAAA&p_cgc=CNPJ -> as liberações dela no ano

Grava em `simec_par_liberacoes` (a MESMA tabela, as MESMAS colunas e o MESMO
parser de linha do relatório do SIMEC — `simec_par.parse_relatorio`), agora com
QUEM recebeu: `cnpj_favorecido`, `favorecido`, `tipo_favorecido`, `fonte =
'fnde_simad'`. A regra do que soma no município mora em `services/liberacoes_fnde.py`.

POR QUE UM COLETOR NOVO E NÃO UM REMENDO NO `simec_par.py` (24/09/2026):
- outro host, outra pilha: httpx puro, sem Cloudflare (o SIMEC precisa do
  curl_cffi impersonando Chrome);
- outra cadência: dezenas de entidades por município e vários anos por noite,
  com orçamento de tempo próprio — dentro do `run_all()` do SIGCON ele roubaria
  o tempo do raspador;
- falha separada no `ingestion_log` (`fnde_liberacoes`): se o simad cair, o
  vigia acusa ELE, e o SIMEC — que segue dono das DIMENSÕES do PAR — não fica
  com cara de quebrado. Um não esconde a falha do outro.

O QUE O SIMEC NÃO DAVA (medido em 24/09/2026):
1. Só o CNPJ da PREFEITURA. Monte Sião passou a receber o salário-educação
   (QUOTA) no CNPJ da SECRETARIA de educação (61.994.863/0001-16) em 03/2026: o
   SIMEC mostrava jan+fev (R$ 444.050,84) e escondia R$ 1.168.706,81 de mar a set.
   Nova Palma: QUOTA nenhuma (vai toda à Secretaria, R$ 169.008,08 em 2026).
2. O PDDE das escolas (pago às caixas escolares / CPM): 14 caixas em Monte Sião,
   6 CPMs em Nova Palma, ~56 entidades em Santa Maria.
3. Só o ano corrente. O simad responde qualquer ano de 2000 em diante.

AS ARMADILHAS (medidas em 24/09/2026):
1. ⚠️ **A MESMA OB PAGA VÁRIAS CAIXAS ESCOLARES** (o PDDE sai em OB de lista):
   em Monte Sião a OB 007948 de 30/04/2026 paga 6 caixas e a 008849 de
   08/05/2026 paga 7 — daí a chave única com o CNPJ
   (`add_fnde_liberacoes_favorecido.sql`). (CNPJ, data, OB) não repetiu em nada.
2. **`p_municipio` é o IBGE de 6 DÍGITOS.** Com 7 ("3143401") a resposta é
   "Não foram encontrados dados" — idêntica a município sem nada. O filtro foi
   provado com valor impossível (999999 -> "Não foram encontrados"), e cada linha
   da lista carrega o município no `onclick`: se vier outro, o filtro foi
   ignorado e a lista inteira é RECUSADA (e há teto de entidades por lista).
3. **`p_uf` é ignorado quando há município** (UF errada devolve a mesma lista);
   vai só por fidelidade ao formulário. `p_cgc` sozinho basta no passo 2.
4. **Latin-1/cp1252.** A página se declara ISO-8859-1 e traz 0x96 (travessão do
   cp1252) no nome do PDDE: decodifica-se cp1252 com `errors="replace"` — o mesmo
   do SIMEC, e por isso o `programa` sai com a MESMA grafia dos dois lados
   ("ALIMENTAÇÃO ESCOLAR"), que é o que deixa a chave casar.
5. **Cada tabela traz a linha "Total:"** — a soma das linhas lidas tem de bater
   com ela, senão a entidade conta como falha (linha perdida no parser: foi assim
   que o PNAE sumiu do SIMEC com o html.parser, PR #566).
6. **"Dados referentes ao fechamento do dia: DD/MM/AAAA"** em toda página: o FNDE
   fecha D-1. Vai para `fnde_liberacoes_carga.fechamento` e para a tela.
7. **Oracle antigo, URL frágil.** Três falhas seguidas de rede/HTTP = host fora:
   para de insistir. Para o ANO CORRENTE do município que falhou, o relatório do
   SIMEC entra como plano B (`simec_par.grava_liberacoes_reserva`, que nunca
   escreve por cima do simad), e a rodada é `partial` com o motivo. Nada é
   apagado: aqui só se faz upsert — a única remoção é da linha do SIMEC que o
   simad acabou de confirmar com a mesma data e OB (`_SQL_SUPERA_SIMEC`).

A AGENDA: toda noite o ano corrente e o anterior de TODO município (regra do
dono). O histórico (de `FNDE_LIB_ANO_INICIAL`, padrão 2015) entra em carga
inicial, `FNDE_LIB_ANOS_CARGA` anos por município por rodada (padrão 3), do mais
novo para o mais velho; ano antigo lido inteiro não é relido
(`fnde_liberacoes_carga.completo`). Pausa de `FNDE_LIB_PAUSA_S` entre páginas.

Rodável por Scheduled Task ou à mão:
    python -u ingestion/fnde_liberacoes.py
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import date

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bs4 import BeautifulSoup  # noqa: E402

from ingestion import simec_par  # noqa: E402
from services.liberacoes_fnde import tipo_favorecido  # noqa: E402

log = logging.getLogger("fnde_liberacoes")

URL = "https://www.fnde.gov.br/pls/simad/internet_fnde.liberacoes_result_pc"
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0; liberacoes FNDE)"}
SOURCE = "fnde_liberacoes"
FONTE = "fnde_simad"
TIMEOUT = 40
# Santa Maria/RS (~280 mil hab.) tem ~56 entidades num ano. Uma lista acima disto
# é filtro ignorado (a base nacional), nunca um município.
TETO_ENTIDADES = 1500
FALHAS_SEGUIDAS_HOST_FORA = 3


def _env_int(nome: str, padrao: int) -> int:
    try:
        return int(os.getenv(nome, "") or padrao)
    except ValueError:
        return padrao


def _env_float(nome: str, padrao: float) -> float:
    try:
        return float(os.getenv(nome, "") or padrao)
    except ValueError:
        return padrao


class FalhaSimad(Exception):
    """O simad não respondeu o que se pediu (rede, HTTP, layout, filtro ignorado)."""


# ---------------------------------------------------------------- parsing ---

_RX_FECHAMENTO = re.compile(r"fechamento\s+do\s+dia:\s*(?:<[^>]+>\s*)*(\d{2})/(\d{2})/(\d{4})", re.I)
_RX_SEM_DADOS = re.compile(r"N.o\s+foram\s+encontrados\s+dados", re.I)
_RX_ENTIDADE = re.compile(r"Entidade\.*:\s*([\d./-]+)\s*-\s*(.+)")
_RX_MUNICIPIO = re.compile(r"Munic.pio\.*:\s*(.+)")
_RX_ARGS = re.compile(r"'([^']*)'")


def _decodifica(conteudo: bytes) -> str:
    return conteudo.decode("cp1252", errors="replace")


def _so_digitos(v: str | None) -> str:
    return re.sub(r"\D", "", v or "")


def fechamento(html: str) -> date | None:
    m = _RX_FECHAMENTO.search(html)
    if not m:
        return None
    d, mes, a = (int(x) for x in m.groups())
    try:
        return date(a, mes, d)
    except ValueError:
        return None


def parse_lista(html: str, ibge6: str) -> dict:
    """A lista de entidades do município. `estado`: 'ok' | 'vazio' | 'entidade'
    (a consulta pulou direto para a página de UMA entidade) | 'invalido'."""
    fech = fechamento(html)
    if _RX_SEM_DADOS.search(html):
        return {"estado": "vazio", "entidades": [], "fechamento": fech}
    if "LISTA DE ENTIDADES" not in html.upper():
        if _RX_ENTIDADE.search(BeautifulSoup(html, "lxml").get_text("\n")):
            return {"estado": "entidade", "entidades": [], "fechamento": fech}
        return {"estado": "invalido", "entidades": [], "fechamento": fech,
                "motivo": "página sem 'LISTA DE ENTIDADES' nem 'Não foram encontrados' — layout mudou?"}
    soup = BeautifulSoup(html, "lxml")
    ents: dict[str, dict] = {}
    for a in soup.find_all("a", onclick=True):
        oc = a.get("onclick") or ""
        if "enviarFormulario" not in oc:
            continue
        args = _RX_ARGS.findall(oc)
        if len(args) < 6:
            continue
        _ano, _prog, uf, muni, _tp, cgc = args[:6]
        if _so_digitos(muni) != ibge6:
            # ⚠️ o filtro de município foi ignorado: nunca gravar a lista de outro
            return {"estado": "invalido", "entidades": [], "fechamento": fech,
                    "motivo": f"a lista trouxe entidade do município {muni}, pedido {ibge6} — filtro ignorado?"}
        cnpj = _so_digitos(cgc)
        if len(cnpj) != 14:
            continue
        texto = a.get_text(" ", strip=True)
        e = ents.setdefault(cnpj, {"cnpj": cnpj, "nome": None, "uf": uf})
        if _so_digitos(texto) != cnpj and texto:
            e["nome"] = re.sub(r"\s+", " ", texto)
    if not ents:
        return {"estado": "invalido", "entidades": [], "fechamento": fech,
                "motivo": "'LISTA DE ENTIDADES' sem nenhuma entidade legível — layout mudou?"}
    return {"estado": "ok", "entidades": list(ents.values()), "fechamento": fech}


def _totais_das_tabelas(html: str) -> dict[str, float]:
    """A linha "Total:" de cada tabela de programa, por `programa_full` (o mesmo
    título que `simec_par.parse_relatorio` grava)."""
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, float] = {}
    for t in soup.find_all("table"):
        rows = t.find_all("tr")
        if len(rows) < 2:
            continue
        hdr = [c.get_text(" ", strip=True).lower() for c in rows[1].find_all(["th", "td"])]
        if not hdr or "data pgto" not in hdr[0]:
            continue
        titulo = rows[0].get_text(" ", strip=True)[:200]
        for r in rows[2:]:
            cells = [c.get_text(" ", strip=True) for c in r.find_all(["th", "td"])]
            if cells and cells[0].lower().startswith("total") and len(cells) > 1:
                v = simec_par._parse_money(cells[1])
                if v is not None:
                    out[titulo] = round(out.get(titulo, 0.0) + v, 2)
    return out


def parse_entidade(html: str) -> dict:
    """A página de liberações de UMA entidade num ano. `estado`: 'ok' | 'vazio' |
    'invalido'. `divergencias` lista o programa cuja soma das linhas não bate com
    a linha "Total:" da própria tabela."""
    fech = fechamento(html)
    if _RX_SEM_DADOS.search(html):
        return {"estado": "vazio", "liberacoes": [], "fechamento": fech, "divergencias": []}
    texto = BeautifulSoup(html, "lxml").get_text("\n")
    me = _RX_ENTIDADE.search(texto)
    if not me:
        return {"estado": "invalido", "liberacoes": [], "fechamento": fech, "divergencias": [],
                "motivo": "página sem 'Entidade..:' — layout mudou?"}
    mm = _RX_MUNICIPIO.search(texto)
    libs = simec_par.parse_relatorio(html)["liberacoes"]
    totais = _totais_das_tabelas(html)
    somas: dict[str, float] = {}
    for li in libs:
        somas[li["programa_full"]] = round(somas.get(li["programa_full"], 0.0) + (li["valor"] or 0), 2)
    divergencias = [f"{p}: linhas {somas.get(p, 0.0):.2f} x total {v:.2f}"
                    for p, v in totais.items() if abs(somas.get(p, 0.0) - v) > 0.005]
    if not libs and not totais:
        return {"estado": "invalido", "liberacoes": [], "fechamento": fech, "divergencias": [],
                "motivo": "entidade sem nenhuma tabela de liberação — layout mudou?"}
    return {
        "estado": "ok",
        "cnpj": _so_digitos(me.group(1)),
        "nome": re.sub(r"\s+", " ", me.group(2)).strip(),
        "municipio": re.sub(r"\s+", " ", mm.group(1)).strip() if mm else None,
        "fechamento": fech,
        "liberacoes": libs,
        "divergencias": divergencias,
    }


# ------------------------------------------------------------------- rede ---

class Simad:
    """O cliente HTTP com a pausa e o disjuntor de host fora."""

    def __init__(self, client: httpx.Client, pausa_s: float):
        self.client = client
        self.pausa_s = pausa_s
        self.falhas_seguidas = 0
        self.n_paginas = 0

    @property
    def fora(self) -> bool:
        return self.falhas_seguidas >= FALHAS_SEGUIDAS_HOST_FORA

    def _pede(self, metodo: str, **kw) -> str:
        if self.fora:
            raise FalhaSimad("simad fora do ar (falhas seguidas) — não insisto nesta rodada")
        ultimo = None
        for tentativa in range(2):
            if self.n_paginas:
                time.sleep(self.pausa_s)
            self.n_paginas += 1
            try:
                r = self.client.request(metodo, URL, **kw)
                if r.status_code == 200:
                    self.falhas_seguidas = 0
                    return _decodifica(r.content)
                ultimo = f"HTTP {r.status_code}"
            except httpx.HTTPError as e:
                ultimo = f"{type(e).__name__}: {str(e)[:80]}"
            if tentativa == 0:
                time.sleep(3)
        self.falhas_seguidas += 1
        raise FalhaSimad(ultimo or "sem resposta")

    def lista(self, ano: int, uf: str, ibge6: str) -> str:
        return self._pede("POST", data={"p_ano": str(ano), "p_uf": uf or "", "p_municipio": ibge6})

    def entidade(self, ano: int, cnpj: str) -> str:
        return self._pede("GET", params={"p_ano": str(ano), "p_cgc": cnpj})


def coleta_ano(simad: Simad, mun: dict, ano: int) -> dict:
    """Tudo o que o simad tem do município no ano. Levanta FalhaSimad se a LISTA
    falhar; falha de UMA entidade deixa o ano `completo = False` com o motivo."""
    ibge6 = _so_digitos(mun["ibge"])[:6]
    lista = parse_lista(simad.lista(ano, mun.get("uf") or "", ibge6), ibge6)
    if lista["estado"] == "invalido":
        simad.falhas_seguidas += 1
        raise FalhaSimad(lista["motivo"])
    if lista["estado"] == "entidade":
        # nunca medido (todo município tem prefeitura + caixas), mas seria a página
        # de UMA entidade sem o CNPJ na mão: recusar é mais honesto que adivinhar.
        raise FalhaSimad("a lista pulou direto para uma entidade — formato não tratado")
    ents = lista["entidades"]
    if len(ents) > TETO_ENTIDADES:
        raise FalhaSimad(f"{len(ents)} entidades (> {TETO_ENTIDADES}) — filtro de município ignorado?")
    out = {"fechamento": lista["fechamento"], "entidades": ents, "liberacoes": [], "erros": []}
    for ent in ents:
        try:
            pag = parse_entidade(simad.entidade(ano, ent["cnpj"]))
        except FalhaSimad as e:
            out["erros"].append(f"{ent['cnpj']}: {e}")
            continue
        if pag["estado"] != "ok":
            # a lista disse que a entidade recebeu neste ano: página vazia é suspeita
            out["erros"].append(f"{ent['cnpj']}: {pag.get('motivo') or pag['estado']}")
            continue
        if pag["cnpj"] != ent["cnpj"]:
            out["erros"].append(f"{ent['cnpj']}: a página respondeu {pag['cnpj']}")
            continue
        if pag["divergencias"]:
            out["erros"].append(f"{ent['cnpj']}: soma ≠ Total ({'; '.join(pag['divergencias'])[:160]})")
        nome = ent.get("nome") or pag["nome"]
        tipo = tipo_favorecido(ent["cnpj"], nome, mun.get("cnpj"))
        for li in pag["liberacoes"]:
            if not (li.get("dt_pgto") and li.get("ob")):
                out["erros"].append(f"{ent['cnpj']}: liberação sem data/OB ({li.get('programa')})")
                continue
            out["liberacoes"].append({**li, "cnpj_favorecido": ent["cnpj"],
                                      "favorecido": nome, "tipo_favorecido": tipo})
    return out


# ---------------------------------------------------------------- gravação ---

_SQL_UPSERT = """
    INSERT INTO simec_par_liberacoes
        (municipio_id, programa, programa_full, dt_pgto, ob, valor, parcela, descricao,
         banco, agencia, conta, ano, raw, cnpj_favorecido, favorecido, tipo_favorecido,
         fonte, updated_at)
    VALUES (%(mid)s, %(programa)s, %(programa_full)s, %(dt_pgto)s, %(ob)s, %(valor)s,
            %(parcela)s, %(descricao)s, %(banco)s, %(agencia)s, %(conta)s, %(ano)s,
            %(raw)s::jsonb, %(cnpj_favorecido)s, %(favorecido)s, %(tipo_favorecido)s,
            'fnde_simad', NOW())
    ON CONFLICT (municipio_id, cnpj_favorecido, programa, dt_pgto, ob) DO UPDATE SET
        programa_full = EXCLUDED.programa_full, valor = EXCLUDED.valor,
        parcela = EXCLUDED.parcela, descricao = EXCLUDED.descricao,
        banco = EXCLUDED.banco, agencia = EXCLUDED.agencia, conta = EXCLUDED.conta,
        ano = EXCLUDED.ano, raw = EXCLUDED.raw, favorecido = EXCLUDED.favorecido,
        tipo_favorecido = EXCLUDED.tipo_favorecido, fonte = 'fnde_simad', updated_at = NOW()
"""

# A linha do SIMEC (plano B, só prefeitura) que o simad acabou de confirmar com a
# MESMA data e OB da prefeitura, gravada sob outra chave (CNPJ vazio/diferente no
# cadastro, grafia do programa): é a mesma liberação duas vezes — sai a do SIMEC.
# (Mesma chave não precisa: o upsert acima já a converteu em 'fnde_simad'.)
_SQL_SUPERA_SIMEC = """
    DELETE FROM simec_par_liberacoes s
     USING simec_par_liberacoes f
     WHERE s.municipio_id = %(mid)s AND s.fonte = 'simec' AND s.tipo_favorecido = 'prefeitura'
       AND f.municipio_id = s.municipio_id AND f.fonte = 'fnde_simad'
       AND f.tipo_favorecido = 'prefeitura'
       AND f.dt_pgto = s.dt_pgto AND f.ob = s.ob AND f.id <> s.id
"""

_SQL_CARGA = """
    INSERT INTO fnde_liberacoes_carga (municipio_id, ano, fechamento, n_entidades,
        n_liberacoes, completo, erro, atualizado_em)
    VALUES (%(mid)s, %(ano)s, %(fechamento)s, %(n_entidades)s, %(n_liberacoes)s,
            %(completo)s, %(erro)s, NOW())
    ON CONFLICT (municipio_id, ano) DO UPDATE SET
        fechamento = COALESCE(EXCLUDED.fechamento, fnde_liberacoes_carga.fechamento),
        n_entidades = CASE WHEN EXCLUDED.completo THEN EXCLUDED.n_entidades
                           ELSE GREATEST(EXCLUDED.n_entidades, fnde_liberacoes_carga.n_entidades) END,
        n_liberacoes = CASE WHEN EXCLUDED.completo THEN EXCLUDED.n_liberacoes
                            ELSE GREATEST(EXCLUDED.n_liberacoes, fnde_liberacoes_carga.n_liberacoes) END,
        completo = EXCLUDED.completo, erro = EXCLUDED.erro, atualizado_em = NOW()
"""


def grava(cur, mid: int, ano: int, res: dict | None, erro: str | None = None) -> int:
    """Upsert das liberações + estado da carga. Nunca apaga liberação do simad."""
    n = 0
    if res is not None:
        for li in res["liberacoes"]:
            cur.execute(_SQL_UPSERT, {
                "mid": mid, "programa": li["programa"], "programa_full": li["programa_full"],
                "dt_pgto": li["dt_pgto"], "ob": li["ob"], "valor": li["valor"],
                "parcela": li["parcela"], "descricao": li["descricao"], "banco": li["banco"],
                "agencia": li["agencia"], "conta": li["conta"], "ano": li["ano"],
                "raw": json.dumps(li, default=str, ensure_ascii=False),
                "cnpj_favorecido": li["cnpj_favorecido"], "favorecido": li["favorecido"],
                "tipo_favorecido": li["tipo_favorecido"],
            })
            n += 1
        cur.execute(_SQL_SUPERA_SIMEC, {"mid": mid})
        erro = "; ".join(res["erros"])[:500] or None
    cur.execute(_SQL_CARGA, {
        "mid": mid, "ano": ano,
        "fechamento": res["fechamento"] if res else None,
        "n_entidades": len(res["entidades"]) if res else 0,
        "n_liberacoes": n,
        "completo": bool(res is not None and not res["erros"]),
        "erro": erro[:500] if erro else None,
    })
    return n


# ---------------------------------------------------------------- rodada ---

def _municipios(cur) -> list[dict]:
    cur.execute("SELECT id, nome, uf, ibge_code, cnpj FROM municipios "
                "WHERE active = true AND ibge_code IS NOT NULL ORDER BY nome")
    out = []
    for r in cur.fetchall():
        if len(_so_digitos(r[3])) >= 6:
            out.append({"id": r[0], "nome": r[1], "uf": r[2], "ibge": r[3], "cnpj": r[4]})
    return out


def _anos_completos(cur, mid: int) -> set[int]:
    cur.execute("SELECT ano FROM fnde_liberacoes_carga WHERE municipio_id = %s AND completo", (mid,))
    return {r[0] for r in cur.fetchall()}


def _log_ingest(cur, conn, status: str, n: int, nota: str | None) -> None:
    try:
        cur.execute("INSERT INTO ingestion_log (source, status, records_inserted, error_message, "
                    "finished_at) VALUES (%s, %s, %s, %s, NOW())",
                    (SOURCE, status, n, (nota or None) and nota[:1000]))
        conn.commit()
    except Exception as e:  # o log nunca derruba a rodada
        conn.rollback()
        log.warning("ingestion_log falhou: %s", str(e)[:120])


def _reserva_simec(cur, mun: dict) -> int | None:
    """Plano B do ano corrente: o relatório do SIMEC (só prefeitura). None = o
    SIMEC também falhou."""
    try:
        data = simec_par.scrape_municipio({**mun, "ibge": _so_digitos(mun["ibge"])})
    except Exception as e:  # curl_cffi/Cloudflare: plano B não derruba a rodada
        log.warning("  plano B SIMEC falhou para %s: %s", mun["nome"], str(e)[:120])
        return None
    if data is None:
        return None
    return simec_par.grava_liberacoes_reserva(cur, mun["id"], mun.get("cnpj"), data["liberacoes"])


def status_da_rodada(n_mun: int, sem_ano_corrente: int, problemas: list[str]) -> tuple[str, str | None]:
    """error = NENHUM município ficou com o ano corrente lido — nem pelo simad nem
    pelo plano B do SIMEC; partial = qualquer problema (simad que falhou e o SIMEC
    cobriu, entidade que falhou, orçamento que acabou antes de ler o
    corrente/anterior de todos); success = tudo lido do simad."""
    if n_mun and sem_ano_corrente >= n_mun:
        return "error", "; ".join(problemas)[:1000] or "simad sem resposta para nenhum município"
    if problemas:
        return "partial", "; ".join(problemas)[:1000]
    return "success", None


def run() -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect

    ano_inicial = _env_int("FNDE_LIB_ANO_INICIAL", 2015)
    anos_carga = _env_int("FNDE_LIB_ANOS_CARGA", 3)
    pausa = _env_float("FNDE_LIB_PAUSA_S", 0.3)
    budget = _env_int("FNDE_LIB_BUDGET_S", 2400)
    reserva = os.getenv("FNDE_LIB_SIMEC_RESERVA", "1") != "0"
    t0 = time.monotonic()
    hoje = date.today()
    anos_noite = [hoje.year, hoje.year - 1]

    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        muns = _municipios(cur)
        if not muns:
            _log_ingest(cur, conn, "success", 0, "nenhum município ativo com IBGE")
            return 0
        log.info("=== FNDE liberações (simad): %d município(s), anos %s + carga desde %d ===",
                 len(muns), anos_noite, ano_inicial)
        total = 0
        problemas: list[str] = []
        sem_ano_corrente = 0     # nem simad nem plano B
        with httpx.Client(headers=UA, timeout=TIMEOUT, follow_redirects=True) as client:
            simad = Simad(client, pausa)

            def um_ano(mun: dict, ano: int) -> bool:
                """Lê e grava UM (município, ano). True se veio do simad (mesmo
                incompleto), False se a lista falhou."""
                nonlocal total
                try:
                    res = coleta_ano(simad, mun, ano)
                except FalhaSimad as e:
                    grava(cur, mun["id"], ano, None, f"lista: {e}")
                    conn.commit()
                    problemas.append(f"{mun['nome']} {ano}: {e}")
                    log.warning("  %s %d: simad falhou — %s", mun["nome"], ano, e)
                    return False
                n = grava(cur, mun["id"], ano, res)
                conn.commit()
                total += n
                if res["erros"]:
                    problemas.append(f"{mun['nome']} {ano}: {len(res['erros'])} entidade(s) com falha "
                                     f"({res['erros'][0][:120]})")
                log.info("  %s %d: %d entidade(s), %d liberação(ões)%s — fechamento %s",
                         mun["nome"], ano, len(res["entidades"]), n,
                         f", {len(res['erros'])} falha(s)" if res["erros"] else "", res["fechamento"])
                return True

            # 1) corrente + anterior de TODO município — a regra do dono.
            for i, mun in enumerate(muns):
                if time.monotonic() - t0 > budget:
                    problemas.append(f"orçamento de {budget}s acabou: {len(muns) - i} município(s) "
                                     f"sem o ano corrente/anterior nesta rodada")
                    sem_ano_corrente += len(muns) - i
                    break
                for ano in anos_noite:
                    ok = um_ano(mun, ano)
                    if ok or ano != hoje.year:
                        continue
                    n = _reserva_simec(cur, mun) if reserva else None
                    conn.commit()
                    if n is None:
                        sem_ano_corrente += 1
                        problemas.append(f"{mun['nome']}: plano B (SIMEC) "
                                         f"{'também falhou' if reserva else 'desligado'}")
                    else:
                        total += n
                        problemas.append(f"{mun['nome']}: ano corrente pelo SIMEC (plano B, só "
                                         f"prefeitura; {n} liberação(ões) nova(s)/atualizada(s))")

            # 2) carga inicial do histórico, com o tempo que sobrar.
            pendentes = 0
            if not simad.fora:
                for mun in muns:
                    feitos = _anos_completos(cur, mun["id"])
                    faltam = [a for a in range(hoje.year - 2, ano_inicial - 1, -1) if a not in feitos]
                    pendentes += max(0, len(faltam) - anos_carga)
                    for ano in faltam[:anos_carga]:
                        if time.monotonic() - t0 > budget or simad.fora:
                            pendentes += 1
                            continue
                        um_ano(mun, ano)
            if pendentes:
                log.info("carga inicial: %d (município, ano) ficam para as próximas rodadas", pendentes)

        status, nota = status_da_rodada(len(muns), sem_ano_corrente, problemas)
        if status == "success" and pendentes:
            nota = f"carga inicial: faltam {pendentes} (município, ano)"
        log.info("=== FNDE liberações: %s — %d liberação(ões) gravadas, %d página(s), %.0fs ===",
                 status, total, simad.n_paginas, time.monotonic() - t0)
        _log_ingest(cur, conn, status, total, nota)
        cur.close()
        return total


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    run()
