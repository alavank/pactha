"""
CAGEC — Cadastro Geral de Convenentes de Minas Gerais.

Regularidade ESTADUAL: o par mineiro do CAUC federal. Sem CAGEC regular o
municipio nao assina convenio novo com o Estado.

ONDE FICA (descoberto em 2026-07-30, vale registrar porque nao e obvio):
  O CAGEC **nao esta** no SIGCON-MG. O portal de convenios (sigconv2, "Modulo
  Saida") nao tem uma unica ocorrencia da palavra CAGEC em todo o HTML, nem no
  menu de 29 itens. O CAGEC vive em portal proprio:
      https://www.portalcagec.mg.gov.br/  -> sistema em www.cagec.mg.gov.br
  e a consulta que usamos aqui e **PUBLICA**:
      http://www.cagec.mg.gov.br/convenente-web/consultaParceiros
  Isso e melhor que a area logada: funciona para QUALQUER municipio e nao
  depende da credencial do cliente (que pode expirar ou ser trocada).

O QUE A CONSULTA PUBLICA DEVOLVE (colunas do grid):
  CNPJ | Nome ou Razao Social | Nome Fantasia | Municipio | UF |
  Genero de Parceiro | Tipo de Parceiro | **Situacao para Parceria** |
  **Possui Impedimento** | Emitir CRC
  Nao ha validade nem lista de exigencias aqui — para isso seria preciso o CRC
  (so emitido para quem esta regular) ou a area logada. Por isso `validade`,
  `itens` e `pendencias` ficam nulos/zerados: preferimos campo vazio a campo
  inventado.

ARMADILHAS DO PORTAL (custaram tempo, ficam anotadas):
  1. E ZK Framework: os ids dos componentes sao GERADOS POR SESSAO (sBFQv1,
     sBFQh4...). Nao da para fixar id nenhum — localizamos por placeholder e
     por texto de BOTAO.
  2. A pagina tem a frase "clique no botao [PESQUISAR]". Um seletor por texto
     casa com essa INSTRUCAO antes do botao, o clique nao faz nada e a busca
     parece devolver vazio. Por isso restringimos a elementos de botao.
  3. O grid so aparece depois do postback; sem espera a tabela volta so com o
     cabecalho.

Cron: junto com o SIGCON (run_sigcon_cron.py) ou avulso.
"""
from __future__ import annotations
import asyncio
import logging
import os
import re
import sys
import unicodedata
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger("cagec_scraper")

URL_CONSULTA = "http://www.cagec.mg.gov.br/convenente-web/consultaParceiros"

# "Situacao para Parceria" — o vocabulario do portal. So tratamos como REGULAR
# o que for explicitamente regular; qualquer outro rotulo (inclusive um que
# apareca no futuro e nao conhecemos) fica como NAO regular, que e o lado
# seguro: melhor alarmar a toa do que exibir verde para quem esta impedido.
_REGULARES = ("regular", "regularizado")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _municipios_alvo() -> list[dict]:
    """Municipios ativos + CNPJ descoberto nos dados que ja temos.

    O CNPJ nao esta na tabela `municipios` (nao existe a coluna), entao ele e
    inferido das fontes ja coletadas — na pratica as emendas estaduais trazem
    `cnpj_beneficiario` do proprio municipio, e o PAC traz `cnpj`."""
    import psycopg2
    url = os.getenv("DATABASE_URL_SYNC", "")
    url = url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    conn = psycopg2.connect(url)
    cur = conn.cursor()
    cur.execute("""
        SELECT m.id, m.nome, m.uf,
               COALESCE(
                 (SELECT regexp_replace(e.cnpj_beneficiario, '\\D', '', 'g')
                    FROM emendas_estaduais e
                   WHERE e.municipio_id = m.id
                     AND e.beneficiario ILIKE '%MUNIC%'
                     AND e.cnpj_beneficiario IS NOT NULL
                   LIMIT 1),
                 (SELECT regexp_replace(p.cnpj, '\\D', '', 'g')
                    FROM transferegov_pac p
                   WHERE p.municipio_id = m.id AND p.cnpj IS NOT NULL
                   LIMIT 1)
               ) AS cnpj
        FROM municipios m
        WHERE m.active = true
        ORDER BY m.nome
    """)
    alvos = [{"id": r[0], "nome": r[1], "uf": r[2], "cnpj": r[3]} for r in cur.fetchall()]
    conn.close()
    return alvos


async def _consultar(page, cnpj: str) -> dict | None:
    """Uma consulta na tela publica. Devolve {rotulo_da_coluna: valor} ou None.

    Lemos CELULA A CELULA e casamos pelo texto do CABECALHO. Regex em cima da
    linha concatenada erra (corta "MUNICIPIO DE MONTE SIAO" no primeiro token)
    e indice fixo quebra se o portal reordenar uma coluna."""
    await page.goto(URL_CONSULTA, timeout=60000, wait_until="domcontentloaded")
    await page.wait_for_timeout(3500)

    # O campo de CNPJ e o unico com mascara contendo '/'.
    campo = page.locator("input[type=text][placeholder*='/']").first
    if not await campo.count():
        raise RuntimeError("campo de CNPJ nao encontrado na consulta publica do CAGEC")
    await campo.click()
    await campo.type(cnpj, delay=35)
    await page.wait_for_timeout(400)

    # SO elementos de botao: por texto puro cairia na instrucao "clique no
    # botao [PESQUISAR]" e o clique nao faria nada (ver armadilha 2 no topo).
    botoes = page.locator("button, .z-button, .z-toolbarbutton, a.z-button, "
                          "input[type=button], input[type=submit]")
    alvo = None
    for i in range(await botoes.count()):
        try:
            t = _norm(await botoes.nth(i).inner_text()).upper()
        except Exception:
            continue
        if t.startswith("PESQUISAR"):
            alvo = botoes.nth(i)
            break
    if alvo is None:
        raise RuntimeError("botao PESQUISAR nao encontrado")
    await alvo.click()
    await page.wait_for_timeout(9000)  # postback do ZK

    # [[celulas da linha 1], [celulas da linha 2], ...]
    grade = await page.eval_on_selector_all(
        ".z-listitem, .z-row, tbody tr",
        # th/.z-listheader tambem: sem eles a linha do CABECALHO sai vazia,
        # e sem cabecalho nao ha como casar coluna por rotulo.
        "els => els.map(tr => Array.from(tr.querySelectorAll("
        "  'td, th, .z-listcell, .z-row-cell, .z-listheader, .z-column'))"
        "  .map(c => (c.innerText||'').trim().replace(/\\s+/g,' ')))")
    grade = [l for l in grade if l]
    if not grade:
        return None

    cabecalho = None
    alvo_digitos = _so_digitos(cnpj)
    for linha in grade:
        junto = " ".join(linha)
        if "CNPJ" in junto and ("Razão Social" in junto or "Razao Social" in junto):
            cabecalho = linha
            continue
        if _so_digitos(junto).startswith(alvo_digitos[:8]):
            if not cabecalho:
                return None
            return {_norm(cabecalho[i]): _norm(v)
                    for i, v in enumerate(linha) if i < len(cabecalho)}
    return None


def _pegar(linha: dict, *pedacos: str) -> str | None:
    """Valor da coluna cujo rotulo contem todos os pedacos (sem acento/caixa)."""
    def limpo(s: str) -> str:
        s = unicodedata.normalize("NFKD", s or "")
        return "".join(c for c in s if not unicodedata.combining(c)).lower()
    for rotulo, valor in linha.items():
        r = limpo(rotulo)
        if all(limpo(p) in r for p in pedacos):
            return valor or None
    return None


def _extrair(linha: dict) -> dict:
    """Le a linha do grid pelos rotulos das colunas."""
    return {
        "situacao": _pegar(linha, "situacao", "parceria"),
        "impedimento": _pegar(linha, "impedimento"),
        "nome": _pegar(linha, "nome", "razao social") or _pegar(linha, "razao social"),
        "tipo": _pegar(linha, "tipo"),
    }


def _salvar(mun: dict, cnpj_fmt: str, extraido: dict) -> None:
    import psycopg2
    url = os.getenv("DATABASE_URL_SYNC", "")
    url = url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    conn = psycopg2.connect(url)
    cur = conn.cursor()
    situacao = extraido.get("situacao")
    regular = bool(situacao) and situacao.strip().lower() in _REGULARES
    impedimento = (extraido.get("impedimento") or "").strip().lower()
    # A consulta publica nao lista as exigencias uma a uma. Registramos os dois
    # fatos que ela DE FATO informa, no formato do CAUC, para a mesma tela
    # desenhar as duas colunas — e nada alem disso.
    itens = [
        {"codigo": "SIT", "grupo": "CAGEC", "label": "Situação para Parceria",
         "valor": situacao or "-", "tipo": "regular" if regular else "pendente",
         "status": situacao or "-"},
        {"codigo": "IMP", "grupo": "CAGEC", "label": "Possui Impedimento",
         "valor": extraido.get("impedimento") or "-",
         "tipo": "pendente" if impedimento == "sim" else "regular",
         "status": extraido.get("impedimento") or "-"},
    ]
    pend = sum(1 for i in itens if i["tipo"] == "pendente")
    cur.execute("""
        INSERT INTO cagec_situacao (municipio_id, nome, uf, cnpj, situacao, regular,
                                    validade, itens, pendencias, pendencias_codigos,
                                    data_pesquisa, atualizado_em)
        VALUES (%s, %s, %s, %s, %s, %s, NULL, %s::jsonb, %s, %s, %s, NOW())
        ON CONFLICT (municipio_id) DO UPDATE SET
            nome = EXCLUDED.nome, uf = EXCLUDED.uf, cnpj = EXCLUDED.cnpj,
            situacao = EXCLUDED.situacao, regular = EXCLUDED.regular,
            itens = EXCLUDED.itens, pendencias = EXCLUDED.pendencias,
            pendencias_codigos = EXCLUDED.pendencias_codigos,
            data_pesquisa = EXCLUDED.data_pesquisa, atualizado_em = NOW()
    """, (mun["id"], extraido.get("nome") or mun["nome"], mun["uf"], cnpj_fmt,
          situacao, regular,
          __import__("json").dumps(itens, ensure_ascii=False), pend,
          [i["codigo"] for i in itens if i["tipo"] == "pendente"],
          date.today()))
    conn.commit()
    conn.close()


async def _rodar() -> tuple[int, int]:
    from playwright.async_api import async_playwright
    alvos = _municipios_alvo()
    logger.info("CAGEC: %d municipio(s) ativos", len(alvos))
    ok = falha = 0
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await br.new_context(locale="pt-BR")
        page = await ctx.new_page()
        try:
            for mun in alvos:
                if not mun["cnpj"]:
                    logger.warning("  %s: sem CNPJ conhecido — pulando "
                                   "(colete emendas estaduais ou PAC antes)", mun["nome"])
                    falha += 1
                    continue
                try:
                    achado = await _consultar(page, mun["cnpj"])
                except Exception as e:
                    logger.error("  %s: erro na consulta — %s", mun["nome"], str(e)[:120])
                    falha += 1
                    continue
                if not achado:
                    logger.warning("  %s: CNPJ %s nao encontrado no CAGEC", mun["nome"], mun["cnpj"])
                    falha += 1
                    continue
                m = re.search(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", " ".join(achado.values()))
                cnpj_fmt = m.group(0) if m else mun["cnpj"]
                extraido = _extrair(achado)
                _salvar(mun, cnpj_fmt, extraido)
                logger.info("  %s: situacao=%s impedimento=%s", mun["nome"],
                            extraido.get("situacao"), extraido.get("impedimento"))
                ok += 1
        finally:
            await br.close()
    return ok, falha


def main():
    ok, falha = asyncio.run(_rodar())
    logger.info("=== CAGEC: %d coletado(s), %d falha(s) ===", ok, falha)
    try:
        import psycopg2
        url = os.getenv("DATABASE_URL_SYNC", "")
        url = url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
        conn = psycopg2.connect(url)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, finished_at) "
            "VALUES ('cagec', %s, %s, NOW())",
            ("ok" if ok and not falha else ("parcial" if ok else "erro"), ok))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("nao consegui registrar em ingestion_log: %s", str(e)[:100])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    main()
