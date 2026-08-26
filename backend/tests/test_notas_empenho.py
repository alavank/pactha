"""NEs / Notas de Empenho (Execução Concedente) — o parser.

⚠️ A FIXTURE É RECONSTRUÍDA, NÃO CAPTURADA. A página está atrás da parede SAML
(medido: guest recebe 3469 bytes de "HTTP Post Binding"), então não foi possível
baixar o HTML real. O que está aqui reproduz a ESTRUTURA e os VALORES visíveis no
print do dono — os mesmos seis cabeçalhos, e as duas linhas do caso real. Se o
parser falhar contra a página de verdade, é aqui que a fixture precisa ser
trocada por uma capturada com sessão viva.

O caso que mais importa é a segunda linha: a MINUTA, sem número de empenho, com
valor de R$ 1,00. Ela não é dinheiro, e somá-la como empenho poria R$ 1,00 no
relatório como se fosse recurso.
"""
import httpx

from ingestion.transferegov_http import TgHttpEnrich


_HTML = """
<html><body>
<table>
  <tr>
    <th>N&uacute;mero do Empenho</th><th>N&uacute;mero da Minuta</th>
    <th>Valor do Empenho</th><th>Valor do Empenho no SIAFI</th>
    <th>Situa&ccedil;&atilde;o</th><th>Data de Emiss&atilde;o</th>
  </tr>
  <tr>
    <td>2026NE000320</td><td>202600000325</td>
    <td>R$ 280.000,00</td><td>R$ 280.000,00</td>
    <td>Enviado</td><td>09/03/2026</td>
  </tr>
  <tr>
    <td></td><td>202500001654</td>
    <td>R$ 1,00</td><td></td>
    <td>Minuta de Empenho</td><td>21/10/2025</td>
  </tr>
</table>
</body></html>
"""

_SAML = '<html><body><p>HTTP Post Binding</p><input name="SAMLResponse"/></body></html>'
_VAZIO = "<html><body><table><tr><th>Situação</th><th>Empenho</th></tr></table>" \
         "<p>Nenhum registro foi encontrado</p></body></html>"


def _resp(html):
    return httpx.Response(200, text=html)


def test_le_o_empenho_real():
    out = TgHttpEnrich._le_notas_empenho(_resp(_HTML))
    ne = out[0]
    assert ne["numero"] == "2026NE000320"
    assert ne["minuta"] == "202600000325"
    assert ne["valor"] == 280000.0
    assert ne["valor_siafi"] == 280000.0
    assert ne["situacao"] == "Enviado"
    assert ne["dt_emissao"] == "09/03/2026"
    assert ne["minuta_apenas"] is False


def test_minuta_e_marcada_e_nao_vira_dinheiro():
    """A linha da minuta tem R$ 1,00 e nenhum número de empenho. Marcá-la na
    LEITURA evita que cada consumidor tenha de redescobrir a regra."""
    out = TgHttpEnrich._le_notas_empenho(_resp(_HTML))
    assert len(out) == 2
    minuta = out[1]
    assert minuta["numero"] is None
    assert minuta["valor"] == 1.0
    assert minuta["minuta_apenas"] is True
    # a soma do que é empenho DE VERDADE ignora a minuta
    total = sum(n["valor"] or 0 for n in out if not n["minuta_apenas"])
    assert total == 280000.0


def test_valor_do_siafi_nao_se_confunde_com_o_valor_do_empenho():
    """Os dois cabeçalhos começam com "Valor do Empenho" — o do SIAFI é
    identificado pelo sufixo, e o outro é o primeiro que não é ele. Sem isso os
    dois índices apontariam para a mesma coluna."""
    out = TgHttpEnrich._le_notas_empenho(_resp(_HTML))
    assert out[0]["valor"] == 280000.0 and out[0]["valor_siafi"] == 280000.0
    assert out[1]["valor"] == 1.0 and out[1]["valor_siafi"] is None


def test_parede_saml_nao_vira_lista_vazia():
    """None (indeterminado) e [] (vazio de verdade) são coisas diferentes: o
    upsert é COALESCE, então None preserva e [] apagaria."""
    assert TgHttpEnrich._le_notas_empenho(_resp(_SAML)) is None


def test_sem_registro_e_lista_vazia():
    assert TgHttpEnrich._le_notas_empenho(_resp(_VAZIO)) == []


# ---------------------------------------------------------------------------
# ⚠️ A SEXTA SAÍDA — a que era MUDA (achado em produção, 25/08/2026)
# ---------------------------------------------------------------------------
class _RespHtml:
    def __init__(self, texto):
        self.text = texto
        self.content = texto.encode()


_GRADE = ("<html><body><table><tr><th>Número do Empenho</th><th>Minuta</th>"
          "<th>Valor do Empenho</th><th>Valor do Empenho no SIAFI</th>"
          "<th>Situação</th><th>Data de Emissão</th></tr>"
          "<tr><td>2026NE000320</td><td>2026ME1</td><td>R$ 280.000,00</td>"
          "<td>R$ 280.000,00</td><td>Enviado</td><td>09/03/2026</td></tr>"
          "<tr><td></td><td>2026ME2</td><td>R$ 1,00</td><td></td>"
          "<td>Minuta de Empenho</td><td>10/03/2026</td></tr></table></body></html>")


def test_a_grade_de_verdade_e_lida_e_a_minuta_marcada():
    from ingestion.transferegov_http import TgHttpEnrich
    r = TgHttpEnrich._le_notas_empenho(_RespHtml(_GRADE))
    assert len(r) == 2
    assert r[0]["numero"] == "2026NE000320" and r[0]["minuta_apenas"] is False
    assert r[1]["numero"] is None and r[1]["minuta_apenas"] is True


def test_vazio_declarado_e_LISTA_e_nao_None():
    """`[]` = "consultei e não há NE". `None` = "não consegui ler". A diferença
    decide se o RM pode dizer PENDENTE DE EMPENHO."""
    from ingestion.transferegov_http import TgHttpEnrich
    assert TgHttpEnrich._le_notas_empenho(
        _RespHtml("<html><body><p>Nenhum registro foi encontrado</p></body></html>")) == []


def test_pagina_sem_a_grade_devolve_None_e_DIZ_o_que_veio(caplog):
    """⚠️ ERA A SAÍDA MUDA. `notas_empenho` tem cinco returns que hoje logam o
    motivo; este sexto caía no fim da função sem uma linha, e o chamador só sabia
    escrever "sem retorno (sessão do SP fria?)".

    Foi o que fez 115 falhas por rodada parecerem sessão morta quando a página
    chegava 200, sem muro SAML e com a sessão comprovadamente quente
    (`keepalive: prestacao=vivo`). O log agora diz quantas tabelas vieram e quais
    são os cabeçalhos — é o que separa "layout mudou" de "a grade vem por POST"
    de "a página é outra"."""
    import logging
    from ingestion.transferegov_http import TgHttpEnrich
    outra = ("<html><body><table><tr><th>Proposta</th><th>Convenente</th></tr>"
             "<tr><td>1</td><td>x</td></tr></table></body></html>")
    with caplog.at_level(logging.INFO):
        assert TgHttpEnrich._le_notas_empenho(_RespHtml(outra)) is None
    texto = caplog.text
    assert "pagina sem a grade" in texto
    assert "Proposta|Convenente" in texto      # nomeia o que ACHOU


# ---------------------------------------------------------------------------
# ⚠️ O CAMINHO DO BROWSER — a tela de NEs é JSF e o GET só devolve a casca
# ---------------------------------------------------------------------------
class _PaginaFalsa:
    """O mínimo de uma page do Playwright que `_extrai_notas_empenho` usa.

    ⚠️ DUAS ETAPAS, e a ordem importa: a função primeiro abre o DETALHE da
    proposta (para estabelecer o contexto do instrumento na sessão) e só depois a
    grade. O 1º `evaluate` lê o texto do detalhe; o 2º devolve o payload da grade.
    Foi a falta da 1ª etapa que fazia o browser pedir a tela sem convênio
    selecionado e receber a casca."""

    def __init__(self, linhas, url="https://discricionarias.transferegov.sistema.gov.br/x",
                 texto_detalhe="Dados da Proposta", vazio_declarado=False):
        # `linhas` vira o payload do JS: `None` = a grade não estava na página.
        # `vazio_declarado` = a página traz "Nenhum registro foi encontrado" —
        # é ele, e só ele, que autoriza o `[]` que APAGA.
        self._payload = ({"linhas": linhas, "cab_na_linha": 0,
                          "vazio_declarado": vazio_declarado} if linhas is not None
                         else {"linhas": None, "tabelas": 1, "tem_dt": False,
                               "bytes": 51896, "saml": False, "assinaturas": [],
                               "vazio_declarado": vazio_declarado})
        self._texto_detalhe = texto_detalhe
        self.url = url
        self.visitou = []
        self._chamadas = 0

    async def goto(self, url, **kw):
        self.visitou.append(url)

    async def wait_for_timeout(self, _ms):
        return None

    async def wait_for_selector(self, _sel, **kw):
        return None

    async def evaluate(self, _js):
        self._chamadas += 1
        return self._texto_detalhe if self._chamadas == 1 else self._payload


def _colher(pagina):
    import asyncio
    from ingestion.transferegov_voluntarias import _extrai_notas_empenho
    return asyncio.run(_extrai_notas_empenho(pagina, "123456"))


def test_o_browser_le_a_grade_e_marca_a_minuta():
    """A saída do `evaluate` são só STRINGS da tela; a conversão de valor e a
    marca da minuta acontecem em Python, como em `_extrai_ops_obs`."""
    r = _colher(_PaginaFalsa([
        {"numero": "2026NE000320", "minuta": "2026ME1", "valor": "R$ 280.000,00",
         "valor_siafi": "R$ 280.000,00", "situacao": "Enviado", "dt_emissao": "09/03/2026"},
        {"numero": None, "minuta": "2026ME2", "valor": "R$ 1,00", "valor_siafi": None,
         "situacao": "Minuta de Empenho", "dt_emissao": "10/03/2026"},
    ]))
    assert len(r) == 2
    assert r[0]["valor"] == 280000.0 and r[0]["minuta_apenas"] is False
    assert r[1]["valor"] == 1.0 and r[1]["minuta_apenas"] is True


def test_grade_ausente_devolve_None_e_NUNCA_apaga():
    """`None` do evaluate = a grade não estava lá. Como o `_upsert` é COALESCE,
    devolver None preserva o que já havia — devolver `[]` apagaria."""
    assert _colher(_PaginaFalsa(None)) is None


def test_tela_aberta_e_vazia_COM_A_FRASE_e_lista_vazia():
    assert _colher(_PaginaFalsa([], vazio_declarado=True)) == []


def test_grade_vazia_SEM_a_frase_NAO_apaga():
    """⚠️ O caso que quase entrou em produção. Grade vazia sem "Nenhum registro
    foi encontrado" é indeterminado — `[]` gravaria `'[]'` e o COALESCE apagaria
    os empenhos que já estavam lá."""
    assert _colher(_PaginaFalsa([], vazio_declarado=False)) is None


def test_linha_sem_numero_e_sem_minuta_e_descartada():
    """E se TODAS forem descartadas, o resultado é `None`, não `[]`: ler linhas e
    nenhuma servir é sinal de tabela errada — o rodapé "Voltar", por exemplo — e
    afirmar "não há empenho" ali apagaria os de verdade.

    ⚠️ É a SEGUNDA porta do mesmo portão: aqui a lista chegou NÃO vazia do JS, e
    quem a zerou foi o filtro. Uma guarda só no JS não fecharia este caminho."""
    lixo = {"numero": None, "minuta": None, "valor": "R$ 5,00",
            "valor_siafi": None, "situacao": "x", "dt_emissao": None}
    assert _colher(_PaginaFalsa([lixo])) is None
    # com a frase do portal, o vazio é uma afirmação legítima
    assert _colher(_PaginaFalsa([lixo], vazio_declarado=True)) == []


def test_sem_sessao_autenticada_nao_tenta():
    """`page_auth` None = o lote rodou sem browser autenticado. Não há o que
    fazer, e afirmar `[]` aqui seria dizer "não há empenho" sem ter olhado."""
    assert _colher(None) is None


def test_redirect_para_o_login_devolve_None():
    p = _PaginaFalsa([], url="https://idp.transferegov.sistema.gov.br/idp/login")
    assert _colher(p) is None


# ---------------------------------------------------------------------------
# ⭐ O PONTO CEGO DO CABEÇALHO — a causa real, achada em 25/08/2026
#
# O parser procurava o cabeçalho SÓ na primeira linha da tabela. Num
# `rich:dataTable` (RichFaces, que é o que esta tela usa) a linha 0 costuma ser
# um espaçador/facet vazio e o cabeçalho real é a 1. Sem casar, dava `continue` e
# descartava a grade inteira — em silêncio, com a página certa em mãos.
#
# Pior: a linha de diagnóstico imprimia "1 tabela(s)" quando o número era, na
# verdade, "1 tabela COM TEXTO NA PRIMEIRA LINHA". Foi essa medição, lida como
# prova de que a grade não estava na página, que mandou a investigação inteira
# para o caminho errado ("é JSF por POST com ViewState") — hipótese que nunca
# chegou a ser demonstrada.
# ---------------------------------------------------------------------------
_LINHA_DADOS = """<tr><td>2026NE000320</td><td>202600000325</td>
    <td>R$ 280.000,00</td><td>R$ 280.000,00</td><td>Enviado</td><td>09/03/2026</td></tr>"""
_CAB = """<tr><th>Número do Empenho</th><th>Minuta</th><th>Valor do Empenho</th>
    <th>Valor do Empenho no SIAFI</th><th>Situação</th><th>Data de Emissão</th></tr>"""


def _pagina(miolo):
    """⚠️ COM `<html><body>`: sem eles o lxml descarta a tabela e o teste acusaria
    o parser por um defeito da fixture. Já aconteceu neste arquivo."""
    return f"<html><body>{miolo}</body></html>"


def test_cabecalho_na_SEGUNDA_linha_e_encontrado():
    """O caso que quebrava. A linha 0 é o espaçador do RichFaces."""
    html = _pagina(f"""
      <table id="contador"><tr><td>30:00</td></tr></table>
      <table id="formListarEmpenhosNovoSiafi:dtEmpenhos">
        <thead><tr><td></td><td></td></tr>{_CAB}</thead>
        <tbody>{_LINHA_DADOS}</tbody>
      </table>""")
    out = TgHttpEnrich._le_notas_empenho(_resp(html))
    assert out is not None, "a grade estava na página e o parser não a viu"
    assert len(out) == 1 and out[0]["numero"] == "2026NE000320"
    assert out[0]["valor"] == 280000.0


def test_cabecalho_na_primeira_linha_continua_funcionando():
    """Não-regressão: a forma antiga não pode ter deixado de ser lida."""
    html = _pagina(f"<table>{_CAB}{_LINHA_DADOS}</table>")
    out = TgHttpEnrich._le_notas_empenho(_resp(html))
    assert out and out[0]["numero"] == "2026NE000320"


def test_a_grade_DENTRO_de_uma_tabela_de_layout_e_lida_certa():
    """⚠️ `.//tr` descia na tabela ANINHADA. O portal envolve grades em tabelas de
    layout, e assim as linhas da de FORA (a moldura) entravam na contagem da grade
    — a primeira delas virava "cabeçalho" e a leitura saía torta.

    Agora as linhas são filhas DIRETAS: a moldura de fora não casa cabeçalho
    nenhum, o laço segue para a tabela de dentro, e é ela que é lida."""
    html = _pagina(f"""
      <table id="moldura">
        <tr><td>Execução Concedente</td></tr>
        <tr><td>
          <table id="formListarEmpenhosNovoSiafi:dtEmpenhos">
            <thead>{_CAB}</thead><tbody>{_LINHA_DADOS}</tbody>
          </table>
        </td></tr>
      </table>""")
    out = TgHttpEnrich._le_notas_empenho(_resp(html))
    assert out is not None and len(out) == 1, out
    assert out[0]["numero"] == "2026NE000320"


def test_grade_casada_e_VAZIA_sem_confirmacao_devolve_None():
    """⚠️ `[]` APAGA (o `_upsert` é COALESCE). Cabeçalho certo com zero linhas
    também acontece quando o contexto do instrumento não trocou e o JSF devolveu
    a grade ainda não repovoada — afirmar "não há empenho" ali seria inventar."""
    html = _pagina(f'<table id="dtEmpenhos"><thead>{_CAB}</thead><tbody></tbody></table>')
    assert TgHttpEnrich._le_notas_empenho(_resp(html)) is None


def test_grade_vazia_COM_a_frase_do_portal_e_lista_vazia():
    html = _pagina(f'<table id="dtEmpenhos"><thead>{_CAB}</thead><tbody></tbody></table>'
                   "<p>Nenhum registro foi encontrado</p>")
    assert TgHttpEnrich._le_notas_empenho(_resp(html)) == []


def test_pagina_sem_grade_nenhuma_continua_None():
    html = _pagina('<table id="contador"><tr><td>30:00</td></tr></table>')
    assert TgHttpEnrich._le_notas_empenho(_resp(html)) is None


# ---------------------------------------------------------------------------
# PARIDADE ENTRE OS DOIS LEITORES
#
# A grade é lida em DOIS lugares — o parser HTTP (lxml, testado acima com HTML
# real) e o JS injetado no browser. Os dois têm de aplicar as MESMAS regras, e
# não há como exercitar o JS aqui: jsdom não está no projeto e não vale instalar
# uma dependência para isto.
#
# O que dá para garantir é que ninguém conserte um e esqueça o outro — que é
# exatamente como este defeito nasceu: o `trs[0]` estava errado NOS DOIS, e a
# primeira correção mexeu só no Python.
# ---------------------------------------------------------------------------
def _js_do_browser() -> str:
    import io
    from pathlib import Path
    fonte = Path(__file__).resolve().parent.parent / "ingestion" / "transferegov_voluntarias.py"
    s = io.open(fonte, encoding="utf-8").read()
    return s.split('r_js = await page_auth.evaluate("""')[1].split('""")')[0]


def test_o_JS_do_browser_procura_o_cabecalho_ALEM_da_primeira_linha():
    js = _js_do_browser()
    assert "Math.min(trs.length, 4)" in js, "o JS voltou a olhar só a 1ª linha"
    assert "iCab" in js and "trs.slice(iCab + 1)" in js


def test_o_JS_do_browser_tem_a_guarda_das_3_COLUNAS():
    """⚠️ A guarda existia e era INERTE. Ela conta células do cabeçalho, e o JS
    lia as células com `querySelectorAll('th,td')` — DESCENDENTES. A linha da
    moldura recebia as próprias células mais todas as da grade de dentro,
    `h.length` passava de 10, e a guarda nunca disparava.

    Por isso a asserção é NEGATIVA: o que protege não é a guarda estar escrita, é
    a seleção de células ser direta."""
    js = _js_do_browser()
    assert "h.length < 3" in js
    assert "querySelectorAll('th,td')" not in js, "voltou a ler células DESCENDENTES"
    assert "querySelectorAll(':scope > th, :scope > td')" in js


def test_o_JS_do_browser_le_CELULAS_diretas_nas_linhas_de_dado():
    """Uma célula com tabelinha de botão dentro acrescentaria células fantasma e
    deslocaria todas as colunas seguintes — o valor de um empenho iria para o
    campo do número. O parser HTTP sempre usou `findall("td")` (direto)."""
    js = _js_do_browser()
    assert "tr.querySelectorAll('td')" not in js, "voltou a ler células DESCENDENTES"
    assert "querySelectorAll(':scope > td')" in js


def test_o_JS_do_browser_le_linhas_DIRETAS():
    js = _js_do_browser()
    assert ":scope > tbody > tr" in js and ":scope > tr" in js
    # `querySelectorAll('tr')` solto é o que descia na tabela aninhada
    assert "t.querySelectorAll('tr')" not in js


def test_o_JS_do_browser_ANCORA_no_id_da_grade():
    """`dtEmpenhos` é o único sinal que uma moldura nunca tem — guarda por
    largura cobre moldura de 1 célula, ancorar no id cobre qualquer largura."""
    assert "dtEmpenhos' i]" in _js_do_browser()


def test_o_browser_NAO_pode_devolver_lista_vazia_sozinho():
    """⚠️ O defeito mais grave da revisão. `[]` grava `'[]'` e o COALESCE do
    `_upsert` APAGA os empenhos. E o browser só roda quando o HTTP devolveu None
    — inclusive quando esse None veio da guarda gêmea do lado HTTP. Ou seja: o
    primeiro leitor se recusava a apagar e o segundo apagava em seguida, no mesmo
    instrumento e na mesma rodada.

    Quem decide é o Python, e são DOIS portões: a lista chegar vazia, e o filtro
    de linha zerar uma lista não vazia."""
    import inspect
    from ingestion.transferegov_voluntarias import _extrai_notas_empenho

    src = inspect.getsource(_extrai_notas_empenho).split('"""', 2)[2]
    assert src.count('r_js.get("vazio_declarado")') >= 2, (
        "faltou um dos dois portões que impedem o browser de apagar")
    assert "vazio_declarado: vazioDecl" in _js_do_browser()


def test_o_JS_do_browser_NAO_afirma_vazio_sem_a_frase_do_portal():
    """Mesma regra do COALESCE: `[]` apaga, e só a frase do portal autoriza."""
    js = _js_do_browser()
    assert "Nenhum registro foi encontrado" in js


def test_o_browser_estabelece_o_CONTEXTO_antes_de_pedir_a_grade():
    """⚠️ A etapa que faltava. O `_seta_contexto` do lado HTTP vive no cookie jar
    do httpx e não alcança o Chromium: sem repetir o GET do detalhe na própria
    página, o portal serve a tela de empenhos SEM convênio selecionado."""
    import inspect
    from ingestion.transferegov_voluntarias import _extrai_notas_empenho

    # ⚠️ SEM A DOCSTRING. Ela CITA as duas URLs, ao explicar o defeito — medir a
    # ordem no texto inteiro compara a explicação, não o código. A 1ª versão deste
    # teste caiu nisso e acusou a ordem errada.
    src = inspect.getsource(_extrai_notas_empenho).split('"""', 2)[2]
    i_det = src.find("ResultadoDaConsultaDePropostaDetalharProposta")
    i_ne = src.find("listarEmpenhosNovoSiafi")
    assert i_det > 0, "o detalhe da proposta não é aberto"
    assert i_ne > i_det, "a grade é pedida ANTES de estabelecer o contexto"
    # e o `id_proposta` tem de ser USADO (ele entrava e era descartado)
    assert "idProposta={id_proposta}" in src


def test_toda_saida_None_do_browser_deixa_log():
    """O defeito do #286 ('a sexta saída era muda'), que eu reproduzi no caminho
    novo no mesmo dia. Cada `return None` precisa de um `logger` antes."""
    import inspect
    from ingestion.transferegov_voluntarias import _extrai_notas_empenho

    linhas = inspect.getsource(_extrai_notas_empenho).splitlines()
    mudas = []
    for i, ln in enumerate(linhas):
        if ln.strip() == "return None":
            # olha as 6 linhas acima em busca de um log
            if not any("logger." in linhas[j] for j in range(max(0, i - 6), i)):
                mudas.append(i + 1)
    assert not mudas, f"saídas None sem log nas linhas {mudas}"
