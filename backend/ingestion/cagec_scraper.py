"""
CAGEC — Cadastro Geral de Convenentes de Minas Gerais.

Regularidade ESTADUAL: o par mineiro do CAUC federal. Sem CAGEC regular o
municipio nao assina convenio novo com o Estado e tem parcela retida mesmo em
convenio ja assinado.

ONDE FICA (nao e obvio, vale registrar):
  O CAGEC **nao esta** no SIGCON-MG. O portal de convenios (sigconv2) nao tem
  uma unica ocorrencia da palavra CAGEC em todo o HTML, nem no menu de 29 itens.
  O CAGEC vive em portal proprio e a consulta e **PUBLICA**:
      http://www.cagec.mg.gov.br/convenente-web/consultaParceiros
  Isso e melhor que a area logada: funciona para QUALQUER municipio e nao
  depende da credencial do cliente (que pode expirar ou ser trocada).

O QUE COLETAMOS — e por que o CRC importa:
  A LINHA do resultado da busca so diz "Situacao para Parceria: Irregular".
  Isso e quase inutil para o gestor: ele fica sabendo que esta travado, e nao
  o que destravar. Mas a propria linha tem um botao **"Emitir CRC"** que baixa
  o Certificado de Registro Cadastral em PDF — e o CRC **sai mesmo para
  municipio IRREGULAR**, listando TODAS as ~24 obrigacoes com situacao
  (Vigente/Vencido) e **data de validade de cada uma**, mais CADIN-MG, SIAFI,
  representante legal e vencimento do mandato.
  Medido em Monte Siao (30/07/2026): situacao "Irregular" por UM item — o
  Certificado de Regularidade do FGTS, vencido em 29/07/2026. Sem o CRC, o
  sistema so conseguiria dizer "irregular"; com ele, diz o que fazer.

  Por isso o CRC e o caminho PRINCIPAL e a linha e so conferencia/fallback.

ARMADILHAS DO PORTAL (todas ja custaram tempo):
  1. E ZK Framework: os ids dos componentes sao GERADOS POR SESSAO (sBFQv1,
     sBFQh4...). Nao da para fixar id nenhum — localizamos por placeholder e
     por texto de BOTAO.
  2. A pagina tem a frase "clique no botao [PESQUISAR]". Um seletor por texto
     casa com essa INSTRUCAO antes do botao, o clique nao faz nada e a busca
     parece devolver vazio.
  3. O cabecalho do grid usa th/.z-listheader. Fora do seletor de celulas, a
     linha do cabecalho sai vazia e e descartada — e sem cabecalho nao da para
     casar coluna por rotulo.
  4. "Emitir CRC" nao e <a> nem <button>: casa so por texto. Pegamos a ULTIMA
     ocorrencia porque as primeiras sao ancestrais que apenas CONTEM o texto.

Cron: `cagec`, 5h40 (depois do sigcon das 4h — o CNPJ sai das emendas).
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import re
import sys
import unicodedata
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger("cagec_scraper")

URL_CONSULTA = "http://www.cagec.mg.gov.br/convenente-web/consultaParceiros"

# So tratamos como REGULAR o que for explicitamente regular; qualquer outro
# rotulo (inclusive um que apareca no futuro e nao conhecemos) fica como NAO
# regular. E o lado seguro: melhor alarmar a toa do que pintar de verde quem
# esta impedido de assinar convenio.
_REGULARES = ("regular", "regularizado", "vigente")

_STATUS = r"(Vigente|Vencido|Pendente|Regular|Irregular|N[ãa]o se aplica|Em an[áa]lise)"
_RE_ITEM = re.compile(_STATUS + r"\s*(\d{2}/\d{2}/\d{4})?(?=\s|$)")
_GRUPOS_CRC = ("Credenciamento do Representante Legal", "Habilitação Jurídica",
               "Regularidade Fiscal e Trabalhista", "Responsabilidade e Transparência Fiscal")
_RODAPE = re.compile(r"GOVERNO DO ESTADO DE MINAS GERAIS.*?P[áa]gina \d+ de \d+", re.S)
_BOILER_CAUC = re.compile(
    r"^Extrato do Serviço Auxiliar de Informações para Transferências Voluntárias\s*"
    r"\(CAUC\),?\s*demonstrando o\s*", re.I)
_SUFIXO_CAUC = re.compile(r"\s*[-–]?\s*em situação\s*[\"“]?Comprovado[\"”]?\.?\s*$", re.I)

# Codigo estavel por obrigacao. Estabilidade importa: e por ele que o alerta
# "seu FGTS vence em 30 dias" sabe que esta falando da mesma linha da coleta
# anterior. Ordem importa — a primeira regra que casar vence.
_CODIGOS = [
    (r"item\s*([\d.]+)", lambda m: "CAUC-" + m.group(1).rstrip(".")),
    (r"fgts", "FGTS"),
    (r"trabalhista|cndt", "CNDT"),
    (r"dívida ativa da uni|créditos tributários federais", "RFB-PGFN"),
    (r"débitos tributários estadual", "CDT-MG"),
    (r"limites dívidas|opera[çc][ãa]o de cr[ée]dito", "TCE-DIVIDA"),
    (r"despesa total com pessoal", "TCE-PESSOAL"),
    (r"ampla divulga[çc]", "DECL-TRANSPARENCIA"),
    (r"autorretrato|selfie", "SELFIE"),
    (r"cadastro de pessoas f[íi]sicas|\bcpf\b", "CPF-PREFEITO"),
    (r"carteira de identidade|cnh|passaporte", "ID-PREFEITO"),
    (r"ata de elei[çc]|termo de posse|diploma eleitoral", "POSSE"),
    (r"documento do prefeito|endere[çc]o.*do prefeito", "END-PREFEITO"),
    (r"inscri[çc][ãa]o no cnpj", "CNPJ"),
    (r"endere[çc]o da sede", "END-SEDE"),
    (r"comunica[çc][ãa]o.*eletr[ôo]nic", "AUTORIZ-ELETRONICA"),
    (r"concord[âa]ncia e veracidade", "TERMO-VERACIDADE"),
]


def _limpo(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _sem_acento(s: str) -> str:
    n = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in n if not unicodedata.combining(c)).lower()


def _so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _codigo_do_item(label: str, usados: set) -> str | None:
    low = label.lower()
    for padrao, alvo in _CODIGOS:
        m = re.search(padrao, low)
        if m:
            cod = alvo(m) if callable(alvo) else alvo
            if cod not in usados:
                return cod
    return None


def _rotulo(label: str) -> str:
    """Tira o boilerplate dos itens do CAUC — o texto util e o do meio.

    Normaliza o espaco ANTES de casar: os padroes sao ancorados no inicio, e um
    unico espaco a esquerda (que sobra ao remendar a quebra de pagina) fazia a
    ancora falhar e o rotulo sair com o boilerplate inteiro."""
    l = _limpo(label)
    l = _BOILER_CAUC.sub("", l)
    l = _SUFIXO_CAUC.sub("", l)
    return _limpo(l).strip(" -¿\"")


# --------------------------------------------------------------------------
# Leitura do CRC
# --------------------------------------------------------------------------
def parse_crc(texto: str) -> tuple[dict, list[dict]]:
    """(cabecalho, itens) a partir do texto do PDF do CRC."""
    corpo = _RODAPE.sub("\n", texto)

    def pega(padrao, flags=0):
        m = re.search(padrao, corpo, flags)
        return _limpo(m.group(1)) if m else None

    cabecalho = {
        "numero_cadastro": pega(r"N[°º] DO CADASTRO:\s*(\d+)"),
        "situacao": pega(r"SITUA[ÇC][ÃA]O:\s*(\w+)"),
        "cadin": pega(r"\(CADIN-MG\):\s*(\w+)"),
        "siafi": pega(r"Situa[çc][ãa]o atual no SIAFI:\s*(\w+)"),
        "razao_social": pega(r"Raz[ãa]o Social:\s*(.+)"),
        "representante": pega(r"\nNome\s+([A-ZÁ-Ú][A-ZÁ-Ú \.]+)\n"),
        "mandato_ate": pega(r"Data Vencimento Mandato.*?\n(\d{2}/\d{2}/\d{4})", re.S),
    }

    # O cabecalho tem "SITUACAO: Irregular", que casaria como se fosse item —
    # a lista de obrigacoes so comeca depois de DOCUMENTACAO.
    lista = corpo.split("DOCUMENTAÇÃO", 1)[1] if "DOCUMENTAÇÃO" in corpo else corpo

    grupo_atual = "Outras"
    itens, usados, pos = [], set(), 0
    for m in _RE_ITEM.finditer(lista):
        bruto = lista[pos:m.start()]
        pos = m.end()
        for g in _GRUPOS_CRC:
            if g in bruto:
                grupo_atual = g
                bruto = bruto.split(g)[-1]
        label = _limpo(bruto).replace("Situação Validade", "").strip(" -¿")
        if len(label) < 12:
            continue
        cod = _codigo_do_item(label, usados) or f"OUTRO-{len(itens) + 1}"
        usados.add(cod)
        situacao = _limpo(m.group(1))
        itens.append({
            "codigo": cod,
            "grupo": grupo_atual,
            "label": _rotulo(label)[:220],
            "valor": m.group(2) or situacao,
            "tipo": "regular" if _sem_acento(situacao) in _REGULARES else "pendente",
            "status": situacao,
            "validade": m.group(2),
        })

    _remendar_quebra_de_pagina(itens)

    # CADIN e SIAFI sao checagens de regularidade de verdade, nao enfeite de
    # cabecalho — entram como item para aparecer na mesma lista da tela.
    if cabecalho.get("cadin"):
        inscrito = _sem_acento(cabecalho["cadin"]).startswith("s")
        itens.append({
            "codigo": "CADIN-MG", "grupo": "Adimplência com o Estado",
            "label": "Inscrição no CADIN-MG (Cadastro Informativo de Inadimplência)",
            "valor": cabecalho["cadin"], "status": cabecalho["cadin"],
            "tipo": "pendente" if inscrito else "regular", "validade": None,
        })
    if cabecalho.get("siafi"):
        normal = _sem_acento(cabecalho["siafi"]) == "normal"
        itens.append({
            "codigo": "SIAFI-MG", "grupo": "Adimplência com o Estado",
            "label": "Situação no SIAFI-MG", "valor": cabecalho["siafi"],
            "status": cabecalho["siafi"],
            "tipo": "regular" if normal else "pendente", "validade": None,
        })
    if cabecalho.get("mandato_ate"):
        # Informativo (tipo 'na'): quase toda a documentacao do prefeito vence
        # junto com o mandato, entao essa data explica um bloco de validades.
        rep = cabecalho.get("representante")
        itens.append({
            "codigo": "MANDATO", "grupo": "Representante Legal",
            "label": "Vencimento do mandato do representante legal"
                     + (f" — {rep}" if rep else ""),
            "valor": cabecalho["mandato_ate"], "status": "Informativo",
            "tipo": "na", "validade": cabecalho["mandato_ate"],
        })
    return cabecalho, itens


def _remendar_quebra_de_pagina(itens: list[dict]) -> None:
    """Conserta o item partido pela quebra de pagina do PDF.

    Quando o rotulo de uma obrigacao atravessa a virada de pagina, o status cai
    ANTES do fim do texto: o item fica so com "Item 4.1" e o resto do rotulo
    aparece grudado no comeco do item seguinte. Aqui a cauda volta para o dono."""
    for i, it in enumerate(itens[:-1]):
        if not re.fullmatch(r"Item [\d.]+\.?", it["label"] or ""):
            continue
        seguinte = itens[i + 1]
        m = re.search(r"\s*(?:Extrato do|Item \d)", seguinte["label"] or "")
        if not m or m.start() == 0:
            continue
        cauda, resto = seguinte["label"][:m.start()], seguinte["label"][m.start():]
        it["label"] = _rotulo(f"{it['label']} - {cauda}")[:220]
        seguinte["label"] = _rotulo(resto)[:220]


async def _baixar_crc(page) -> bytes | None:
    """Clica 'Emitir CRC' na linha do resultado e devolve o PDF."""
    loc = page.locator("*:has-text('Emitir CRC')")
    n = await loc.count()
    if not n:
        return None
    # A ULTIMA ocorrencia: as primeiras sao ancestrais (body, tabela, linha)
    # que apenas CONTEM o texto; o elemento clicavel e o mais profundo.
    try:
        async with page.expect_download(timeout=30000) as dl:
            await loc.nth(n - 1).click()
        caminho = await (await dl.value).path()
        with open(caminho, "rb") as f:
            return f.read()
    except Exception as e:
        logger.warning("    CRC nao baixou: %s: %s", type(e).__name__, str(e)[:90])
        return None


def _texto_do_pdf(dados: bytes) -> str:
    from io import BytesIO
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(BytesIO(dados)).pages)


# --------------------------------------------------------------------------
# Portal
# --------------------------------------------------------------------------
def _municipios_alvo() -> list[dict]:
    """Municipios ativos + CNPJ descoberto nos dados que ja temos.

    O CNPJ nao esta na tabela `municipios` (nao existe a coluna), entao vem das
    fontes ja coletadas: as emendas estaduais trazem `cnpj_beneficiario` do
    proprio municipio, e o PAC traz `cnpj`."""
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
    """Busca por CNPJ. Devolve {rotulo_da_coluna: valor} da linha, ou None.

    Lemos CELULA A CELULA e casamos pelo texto do CABECALHO. Regex na linha
    concatenada erra (corta "MUNICIPIO DE MONTE SIAO" no primeiro token) e
    indice fixo quebra se o portal reordenar uma coluna."""
    await page.goto(URL_CONSULTA, timeout=60000, wait_until="domcontentloaded")
    await page.wait_for_timeout(3500)

    campo = page.locator("input[type=text][placeholder*='/']").first
    if not await campo.count():
        raise RuntimeError("campo de CNPJ nao encontrado na consulta publica do CAGEC")
    await campo.click()
    await campo.type(cnpj, delay=35)
    await page.wait_for_timeout(400)

    # SO elementos de botao: por texto puro cairia na instrucao "clique no
    # botao [PESQUISAR]" e o clique nao faria nada (armadilha 2 no topo).
    botoes = page.locator("button, .z-button, .z-toolbarbutton, a.z-button, "
                          "input[type=button], input[type=submit]")
    alvo = None
    for i in range(await botoes.count()):
        try:
            if _limpo(await botoes.nth(i).inner_text()).upper().startswith("PESQUISAR"):
                alvo = botoes.nth(i)
                break
        except Exception:
            continue
    if alvo is None:
        raise RuntimeError("botao PESQUISAR nao encontrado")
    await alvo.click()
    await page.wait_for_timeout(9000)  # postback do ZK

    grade = await page.eval_on_selector_all(
        ".z-listitem, .z-row, tbody tr",
        # th/.z-listheader tambem: sem eles a linha do CABECALHO sai vazia, e
        # sem cabecalho nao ha como casar coluna por rotulo (armadilha 3).
        "els => els.map(tr => Array.from(tr.querySelectorAll("
        "  'td, th, .z-listcell, .z-row-cell, .z-listheader, .z-column'))"
        "  .map(c => (c.innerText||'').trim().replace(/\\s+/g,' ')))")
    grade = [l for l in grade if l]

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
            return {_limpo(cabecalho[i]): _limpo(v)
                    for i, v in enumerate(linha) if i < len(cabecalho)}
    return None


def _pegar(linha: dict, *pedacos: str) -> str | None:
    """Valor da coluna cujo rotulo contem todos os pedacos (sem acento/caixa)."""
    for rotulo, valor in (linha or {}).items():
        r = _sem_acento(rotulo)
        if all(_sem_acento(p) in r for p in pedacos):
            return valor or None
    return None


# --------------------------------------------------------------------------
# Persistencia
# --------------------------------------------------------------------------
def _proxima_validade(itens: list[dict]) -> date | None:
    """Data em que a regularidade ATUAL comeca a cair.

    O CRC nao tem uma validade unica — cada obrigacao tem a sua. A data util
    para o gestor e a mais proxima entre as que ainda estao vigentes: e o
    proximo prazo que ele precisa segurar."""
    datas = []
    for i in itens:
        if i.get("tipo") == "regular" and i.get("validade"):
            try:
                datas.append(datetime.strptime(i["validade"], "%d/%m/%Y").date())
            except ValueError:
                continue
    return min(datas) if datas else None


def _salvar(mun: dict, cnpj_fmt: str, situacao: str | None, nome: str | None,
            itens: list[dict]) -> None:
    import psycopg2
    url = os.getenv("DATABASE_URL_SYNC", "")
    url = url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    conn = psycopg2.connect(url)
    cur = conn.cursor()
    regular = bool(situacao) and _sem_acento(situacao) in _REGULARES
    pendentes = [i["codigo"] for i in itens if i.get("tipo") == "pendente"]
    cur.execute("""
        INSERT INTO cagec_situacao (municipio_id, nome, uf, cnpj, situacao, regular,
                                    validade, itens, pendencias, pendencias_codigos,
                                    data_pesquisa, atualizado_em)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, NOW())
        ON CONFLICT (municipio_id) DO UPDATE SET
            nome = EXCLUDED.nome, uf = EXCLUDED.uf, cnpj = EXCLUDED.cnpj,
            situacao = EXCLUDED.situacao, regular = EXCLUDED.regular,
            validade = EXCLUDED.validade, itens = EXCLUDED.itens,
            pendencias = EXCLUDED.pendencias,
            pendencias_codigos = EXCLUDED.pendencias_codigos,
            data_pesquisa = EXCLUDED.data_pesquisa, atualizado_em = NOW()
    """, (mun["id"], nome or mun["nome"], mun["uf"], cnpj_fmt, situacao, regular,
          _proxima_validade(itens), json.dumps(itens, ensure_ascii=False),
          len(pendentes), pendentes, date.today()))
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
async def _rodar() -> tuple[int, int]:
    from playwright.async_api import async_playwright
    alvos = _municipios_alvo()
    logger.info("CAGEC: %d municipio(s) ativos", len(alvos))
    ok = falha = 0
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await br.new_context(locale="pt-BR", accept_downloads=True)
        page = await ctx.new_page()
        try:
            for mun in alvos:
                if not mun["cnpj"]:
                    logger.warning("  %s: sem CNPJ conhecido — pulando "
                                   "(colete emendas estaduais ou PAC antes)", mun["nome"])
                    falha += 1
                    continue
                try:
                    linha = await _consultar(page, mun["cnpj"])
                except Exception as e:
                    logger.error("  %s: erro na consulta — %s: %s", mun["nome"],
                                 type(e).__name__, str(e)[:110])
                    falha += 1
                    continue
                if not linha:
                    logger.warning("  %s: CNPJ %s nao encontrado no CAGEC",
                                   mun["nome"], mun["cnpj"])
                    falha += 1
                    continue

                m = re.search(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", " ".join(linha.values()))
                cnpj_fmt = m.group(0) if m else mun["cnpj"]
                situacao = _pegar(linha, "situacao", "parceria")
                nome = _pegar(linha, "nome", "razao social") or _pegar(linha, "razao social")

                # Caminho principal: o CRC, que traz as obrigacoes uma a uma.
                itens: list[dict] = []
                pdf = await _baixar_crc(page)
                if pdf:
                    try:
                        cab, itens = parse_crc(_texto_do_pdf(pdf))
                        situacao = cab.get("situacao") or situacao
                        nome = cab.get("razao_social") or nome
                    except Exception as e:
                        logger.warning("  %s: CRC baixou mas nao foi lido — %s: %s",
                                       mun["nome"], type(e).__name__, str(e)[:110])
                        itens = []

                if not itens:
                    # Fallback: so o que a linha da. Menos util, mas nao mente —
                    # e da para ver na tela que veio sem detalhamento.
                    logger.warning("  %s: sem CRC, gravando so a situacao da linha",
                                   mun["nome"])
                    imped = _pegar(linha, "impedimento")
                    itens = [{
                        "codigo": "SIT", "grupo": "CAGEC",
                        "label": "Situação para Parceria", "valor": situacao or "-",
                        "status": situacao or "-", "validade": None,
                        "tipo": "regular" if (situacao and _sem_acento(situacao) in _REGULARES)
                                else "pendente",
                    }]
                    if imped:
                        itens.append({
                            "codigo": "IMP", "grupo": "CAGEC",
                            "label": "Possui Impedimento", "valor": imped, "status": imped,
                            "tipo": "pendente" if _sem_acento(imped) == "sim" else "regular",
                            "validade": None,
                        })

                _salvar(mun, cnpj_fmt, situacao, nome, itens)
                pend = [i["codigo"] for i in itens if i.get("tipo") == "pendente"]
                logger.info("  %s: %s | %d obrigacao(oes) lida(s) | pendente(s): %s",
                            mun["nome"], situacao, len(itens), ", ".join(pend) or "nenhuma")
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
