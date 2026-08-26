"""O e-mail do cabeçalho do RM: precedência, vazio-é-decisão, e os DOIS formatos.

O pedido do dono foi "coloque o e-mail ao lado do logo do lado direito, assim
como o rodapé, um campo para padronizar o email que vai exibir". O "assim como o
rodapé" é literal, e é o que estes testes guardam: mesma precedência de três
camadas, mesma regra do vazio, e presença nos dois renderizadores.
"""
import asyncio
import io
import re
import zipfile

import pytest

from services import rm_config
from services.rm_docx import gerar_docx_rm
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm

from services.rm_pdf import _on_page, gerar_pdf

META = {"data_referencia": "2026-08-24", "cidade_emissao": "Brasília/DF",
        "titulo": "RELATÓRIO DE MONITORAMENTO – ARAÚJOS/MG",
        "rodape": "Setor SHS Quadra 6 — Brasília/DF.", "escopo": "completo"}

CONTEUDO = {"partes": [{"ordem": 1, "titulo": "PARTE 1", "secoes": [
    {"ordem": 1, "titulo": "FEDERAIS", "grupos": [
        {"ordem": 1, "orgao": "Ministério do Esporte", "itens": [
            {"tipo": "Convênio", "numero": "981397/2025", "objeto": "Quadra"}]}]}]}]}

EMAIL = "contato@assessoria.com.br"


# --------------------------------------------------------- precedência --------
class _Res:
    def __init__(self, v):
        self._v = v

    def first(self):
        return self._v


class _Db:
    """Devolve a linha de `configuracoes` que o teste quiser — inclusive NENHUMA."""

    def __init__(self, linha):
        self._linha = linha
        self.sql = []

    async def execute(self, stmt, params=None):
        self.sql.append(" ".join(str(stmt).split()))
        return _Res(self._linha)


def _rodar(coro):
    return asyncio.run(coro)


def test_sem_linha_salva_vale_a_env(monkeypatch):
    monkeypatch.setattr(rm_config, "_env_de", lambda c: "da-env@x.com")
    assert _rodar(rm_config.email_padrao(_Db(None))) == "da-env@x.com"


def test_linha_salva_GANHA_da_env(monkeypatch):
    """A ordem 2-antes-de-3 é o ponto do pedido: o contrário faria o campo
    digitável não servir para nada justamente em quem define a env."""
    monkeypatch.setattr(rm_config, "_env_de", lambda c: "da-env@x.com")
    assert _rodar(rm_config.email_padrao(_Db(("salvo@x.com",)))) == "salvo@x.com"


def test_VAZIO_SALVO_e_uma_DECISAO_e_nao_deixa_a_env_ressuscitar(monkeypatch):
    """⚠️ O teste que justifica o `is not None` em vez de `if valor`. Com o teste
    ingênuo, apagar o e-mail faria a env voltar no próximo relatório — e a pessoa
    apagaria de novo, sem entender por que ele reaparece."""
    monkeypatch.setattr(rm_config, "_env_de", lambda c: "da-env@x.com")
    assert _rodar(rm_config.email_padrao(_Db(("",)))) == ""


def test_salvo_distingue_ausente_de_vazio(monkeypatch):
    monkeypatch.setattr(rm_config, "_env_de", lambda c: "x")
    assert _rodar(rm_config.email_salvo(_Db(None))) is None      # nunca gravado
    assert _rodar(rm_config.email_salvo(_Db(("",)))) == ""       # gravado vazio


def test_chave_desconhecida_e_recusada():
    """⚠️ `_ENV_DA_CHAVE` também é ALLOWLIST: sem ela, um `campo` vindo do corpo
    de um request viraria `getattr(settings, <qualquer coisa>)` — leitura
    arbitrária de configuração."""
    with pytest.raises(ValueError):
        _rodar(rm_config.salvo(_Db(None), "rm.qualquer_outra"))
    with pytest.raises(ValueError):
        _rodar(rm_config.gravar(_Db(None), "os.environ", "x", 1))


def test_rodape_e_email_usam_chaves_DIFERENTES():
    """Óbvio, e é justamente por ser óbvio que uma cópia mal feita erraria aqui —
    os dois passariam a ler a mesma linha de `configuracoes`."""
    assert rm_config.CHAVE_RODAPE != rm_config.CHAVE_EMAIL
    db = _Db(None)
    _rodar(rm_config.email_salvo(db))
    assert "configuracoes" in db.sql[0]


# ------------------------------------------------------------------- PDF ------
def test_pdf_com_email_difere_do_pdf_sem():
    com = gerar_pdf({**META, "email": EMAIL}, CONTEUDO, "Araújos")
    sem = gerar_pdf(META, CONTEUDO, "Araújos")
    assert com[:4] == b"%PDF" and sem[:4] == b"%PDF"
    assert com != sem


class _CanvasEspiao:
    """Anota o que foi DESENHADO. Comparar bytes de PDF não serviria aqui: este
    módulo não liga `rl_config.invariant`, então cada emissão carrega timestamp e
    ID próprios e dois PDFs de mesmo conteúdo nunca saem iguais."""

    def __init__(self):
        self.direita = []

    def saveState(self): pass
    def restoreState(self): pass
    def setFont(self, *a): pass
    def setFillColor(self, *a): pass
    def drawImage(self, *a, **k): pass
    def drawCentredString(self, *a): pass

    def drawRightString(self, x, y, txt):
        self.direita.append((x, y, txt))


class _Doc:
    page = 1


@pytest.mark.parametrize("valor", [None, "", "   "])
def test_pdf_NAO_desenha_email_quando_nao_ha(valor):
    """⚠️ O teste que impede "None" impresso no cabeçalho de todo RM antigo. A
    coluna é NULL em TODO relatório gerado antes dela existir, e um
    `meta.get("email", "")` devolveria None — o default do `get` só vale para
    chave AUSENTE, nunca para chave presente valendo None."""
    c = _CanvasEspiao()
    _on_page(c, _Doc(), "rodapé qualquer", (valor or "").strip())
    assert [t for _, _, t in c.direita] == ["1"]      # só o número da página


def test_pdf_desenha_o_email_A_DIREITA_na_faixa_do_logo():
    c = _CanvasEspiao()
    _on_page(c, _Doc(), "rodapé", EMAIL)
    achou = [(x, y) for x, y, t in c.direita if t == EMAIL]
    assert len(achou) == 1, c.direita
    x, y = achou[0]
    # ⚠️ `_MARGENS_CM[3]` (a margem DIREITA), e não um literal. A 1ª versão deste
    # teste afirmava `A4[0] - 2 * cm` — o mesmo engano do código que ele deveria
    # vigiar, porque os dois saíram da mesma suposição errada. Teste escrito a
    # partir da implementação confirma a implementação, inclusive quando ela está
    # errada; por isso a asserção agora vem da constante da margem.
    from services.rm_pdf import _MARGENS_CM

    assert abs(x - (A4[0] - _MARGENS_CM[3] * cm)) < 0.5
    # E na FAIXA DO LOGO, no topo — não junto ao rodapé.
    assert y > A4[1] / 2


# ------------------------------------------------------------------ WORD ------
def _cabecalho_xml(meta):
    z = zipfile.ZipFile(io.BytesIO(gerar_docx_rm(meta, CONTEUDO, "Araújos")))
    nomes = [n for n in z.namelist() if re.match(r"word/header\d*\.xml", n)]
    assert nomes, f"nenhum cabeçalho no .docx: {z.namelist()}"
    return " ".join(z.read(n).decode("utf-8") for n in nomes)


def test_word_imprime_o_email_no_cabecalho():
    assert EMAIL in _cabecalho_xml({**META, "email": EMAIL})


def test_word_com_email_None_nao_escreve_None():
    xml = _cabecalho_xml({**META, "email": None})
    textos = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml)
    assert "None" not in " ".join(textos)


def test_word_alinha_o_email_a_direita_com_TABULACAO():
    """Não há posição absoluta para texto no cabeçalho do Word como há no canvas
    do PDF: quem alinha é uma tabulação `right` na borda da área útil — a mesma
    técnica já usada no rodapé deste arquivo."""
    xml = _cabecalho_xml({**META, "email": EMAIL})
    assert 'w:val="right"' in xml
    # 21,0 − 2,0 − 1,5 = 17,5 cm de área útil -> 17,5 * 567 = 9922,5 twips
    assert re.search(r'w:tab [^>]*w:pos="99[0-9]{2}"', xml), xml[:0] or "tab fora da borda"


def test_word_NAO_herda_as_tabulacoes_de_papel_carta():
    """⚠️ `w:tabs` é CUMULATIVO na herança de estilo. Sem `_limpar_tabulacoes`, a
    parada herdada em 4680 twips (papel Carta) vem ANTES da nossa e o `\\t`
    pararia no MEIO da página, não na borda direita."""
    xml = _cabecalho_xml({**META, "email": EMAIL})
    # A limpeza é DECLARATIVA: `w:val="clear"` naquela posição exata, e não a
    # ausência da string. Foi o que este teste aprendeu ao nascer errado.
    for pos in ("4680", "9360"):
        assert re.search(rf'<w:tab w:val="clear" w:pos="{pos}"/>', xml), pos
    # E a nossa parada tem de vir DEPOIS das duas limpezas, senão não adianta.
    assert xml.index('w:pos="9360"') < xml.index('w:val="right"')


# --------------------------------------------------- os dois formatos ---------
def test_PDF_e_WORD_poem_o_email_NA_MESMA_COLUNA():
    """⚠️ O TESTE QUE FALTAVA — e a ausência dele deixou um defeito passar.

    A 1ª versão escreveu `A4[0] - 2 * cm` no `drawRightString`, e `2 cm` é a
    margem ESQUERDA (`_MARGENS_CM[2]`); a direita é 1,5. O e-mail saía a 19,00 cm
    no PDF enquanto o número da página, a borda útil e a tabulação do Word estavam
    todos a 19,50. Meio centímetro de divergência entre os dois formatos do mesmo
    relatório, sem nada acusando — não há nada mais que compare PDF e Word.

    A conta do Word: a tabulação é medida A PARTIR DA MARGEM ESQUERDA no OOXML,
    então a coluna absoluta é `margem_esq + área_útil`."""
    from services.rm_pdf import _MARGENS_CM, _PAG_LARG_CM

    c = _CanvasEspiao()
    _on_page(c, _Doc(), "rodapé", EMAIL)
    x_pdf_cm = [x for x, _, t in c.direita if t == EMAIL][0] / cm

    xml = _cabecalho_xml({**META, "email": EMAIL})
    twips = int(re.search(r'<w:tab w:val="right" w:pos="(\d+)"/>'
                          r'|<w:tab w:pos="(\d+)" w:val="right"/>', xml)
                .group(1) or re.search(r'w:pos="(\d+)" w:val="right"', xml).group(1))
    x_word_cm = _MARGENS_CM[2] + twips / 567.0      # 1 cm = 567 twips

    assert abs(x_pdf_cm - x_word_cm) < 0.02, f"PDF {x_pdf_cm:.2f} vs Word {x_word_cm:.2f}"
    # E os dois na borda útil de verdade — não num número que só por acaso coincide.
    assert abs(x_pdf_cm - (_PAG_LARG_CM - _MARGENS_CM[3])) < 0.02


def test_o_numero_da_pagina_usa_a_MESMA_borda_do_email():
    """Dentro do próprio PDF: o e-mail no topo e o número da página no pé têm de
    cair na mesma coluna. Era aqui que os 19,00 contra 19,50 apareciam a olho nu,
    numa página impressa, para quem soubesse olhar."""
    c = _CanvasEspiao()
    _on_page(c, _Doc(), "rodapé", EMAIL)
    xs = {t: x for x, _, t in c.direita}
    assert abs(xs[EMAIL] - xs["1"]) < 0.01


def test_word_sobe_o_email_para_o_MEIO_do_logo():
    """⚠️ Sem `w:position` o e-mail sai SOB o logo, não ao lado: no Word a imagem
    inline assenta o pé na linha de base, e o run de texto compartilha essa linha.
    O valor é derivado de `_LOGO_ALT_CM` — trocar a altura do logo move os dois
    formatos juntos."""
    from services.rm_pdf import _LOGO_ALT_CM

    xml = _cabecalho_xml({**META, "email": EMAIL})
    m = re.search(r'<w:position w:val="(\d+)"/>', xml)
    assert m, "o run do e-mail não subiu — ele sairia pendurado abaixo do logo"
    # meios-pontos -> cm, e tem de bater com metade da altura do logo
    assert abs(int(m.group(1)) / 2 / 28.3465 - _LOGO_ALT_CM / 2) < 0.02


def test_os_DOIS_formatos_recebem_o_email():
    """PDF e Word saem do mesmo `meta`. Este teste falha no dia em que alguém
    acrescentar um campo de cabeçalho em só um dos renderizadores — que é
    exatamente o que já aconteceu com `grupo_titulo`/`item_id`."""
    m = {**META, "email": EMAIL}
    assert gerar_pdf(m, CONTEUDO, "Araújos") != gerar_pdf(META, CONTEUDO, "Araújos")
    assert EMAIL in _cabecalho_xml(m)


# ---------------------------------------------------------------------------
# CAIXA DO LOGO — marca LARGA não pode sair encolhida
#
# A caixa era 3,6 × 1,8 cm. Com `preserveAspectRatio` manda a dimensão que
# estoura primeiro, então uma marca de ~3:1 batia na LARGURA e descia para ~1,2 cm
# de altura — um terço menor que um brasão quase quadrado ao lado. Não era corte,
# era encolhimento, que é mais difícil de perceber.
# ---------------------------------------------------------------------------
def test_a_caixa_comporta_marca_larga_com_a_ALTURA_INTEIRA():
    from services.rm_pdf import _LOGO_ALT_CM, _LOGO_LARG_CM

    # o logo do Freitas é ~2,8:1; a caixa tem de aguentar isso sem encolher
    assert _LOGO_LARG_CM / _LOGO_ALT_CM >= 2.8


def test_alargar_a_caixa_NAO_mexe_no_brasao_quase_quadrado():
    """⚠️ O teste que torna a mudança segura para os outros três tenants. Marca
    limitada pela ALTURA sai igual, porque quem manda é a dimensão que estoura
    primeiro — e para ela a largura nunca foi o limite."""
    from services.rm_pdf import _LOGO_ALT_CM, _LOGO_LARG_CM

    for prop in (512 / 487, 1.0, 1.5, 2.0):        # Monte Sião, quadrado, etc.
        larg = prop * _LOGO_ALT_CM
        assert larg <= _LOGO_LARG_CM, (
            f"proporção {prop:.2f}:1 passou a ser limitada pela largura")


def test_a_caixa_cabe_na_faixa_ANTES_do_email():
    """O logo começa na margem esquerda e o e-mail é alinhado à direita. A caixa
    não pode crescer a ponto de encostar num no outro."""
    from services.rm_pdf import _LOGO_LARG_CM, _MARGENS_CM, _PAG_LARG_CM

    fim_do_logo = _MARGENS_CM[2] + _LOGO_LARG_CM
    inicio_do_email = _PAG_LARG_CM - _MARGENS_CM[3]
    assert fim_do_logo < inicio_do_email - 2.0, "logo perto demais do e-mail"


def test_o_WORD_usa_a_MESMA_caixa_do_PDF():
    """⚠️ O `add_picture` com uma dimensão só escala a outra SEM TETO. Sem o
    cálculo, acima de ~3,2:1 o PDF passa a limitar pela largura e o Word
    continuaria com 1,8 cm de altura, transbordando a faixa — e a divergência só
    apareceria com os dois documentos abertos lado a lado."""
    import inspect

    from services import rm_docx

    src = inspect.getsource(rm_docx._montar_secao)
    assert "_LOGO_LARG_CM" in src, "o Word não conhece o teto de largura"
    assert "px_width" in src and "px_height" in src
