"""O renderizador WORD do RM — services/rm_docx.

Não há teste de RENDER em lugar nenhum deste repositório: nem para o PDF, nem
para o Word. O documento vai assinado ao prefeito, então o que se prova aqui é o
que ninguém consegue ver lendo o código — a ORDEM do XML que o Word exige, a
equivalência com o PDF, e as três armadilhas que fariam o arquivo sair errado sem
levantar exceção nenhuma.
"""
import io
import re
import zipfile

from services.rm_docx import (
    _SUCESSORES_PBDR, _desescapar, _uma_linha, gerar_docx_rm,
)
from services.rm_pdf import roteiro_rm

META = {"data_referencia": "2026-08-24", "cidade_emissao": "Brasília/DF",
        "titulo": "RELATÓRIO DE MONITORAMENTO – ARAÚJOS/MG",
        "rodape": "Setor SHS Quadra 6 — Brasília/DF.", "escopo": "completo"}

UM_ITEM = {"partes": [{"ordem": 1, "titulo": "PARTE 1 - DEMANDAS EM BRASÍLIA", "secoes": [
    {"ordem": 1, "titulo": "INSTRUMENTOS DE REPASSE FEDERAIS", "grupos": [
        {"ordem": 1, "orgao": "Ministério do Esporte", "itens": [
            {"tipo": "Convênio", "numero": "981397 /2025",
             "objeto": "Reforma da quadra", "situacao_atual": "Em execução",
             "valor_global": 368000.0}]}]}]}]}

COM_CAIXA = {"partes": [{"ordem": 1, "titulo": "PARTE 1", "secoes": [
    {"ordem": 1, "titulo": "FEDERAIS", "grupos": [
        {"ordem": 1, "orgao": "FNS", "itens": [
            {"tipo": "Proposta", "numero": "048291/2025", "objeto": "UBS",
             "situacao_contratacao": "Cláusula Suspensiva",
             "clausula_motivo": "Pendência documental",
             "clausula_dt": "2026-09-01",
             "valor_desembolsado": 280000.0,
             "obra": "A obra encontra-se em execução."}]}]}]}]}

DUAS_PARTES = {"partes": [
    {"ordem": 1, "titulo": "PARTE 1", "secoes": [{"ordem": 1, "titulo": "A", "grupos": [
        {"ordem": 1, "orgao": "Org A", "itens": [
            {"tipo": "Convênio", "numero": "1/2025", "objeto": "x"}]}]}]},
    {"ordem": 2, "titulo": "PARTE 2", "secoes": [{"ordem": 1, "titulo": "B", "grupos": [
        {"ordem": 1, "orgao": "Org B", "itens": [
            {"tipo": "Convênio", "numero": "2/2025", "objeto": "y"}]}]}]}]}


def _zip(conteudo, meta=None):
    return zipfile.ZipFile(io.BytesIO(
        gerar_docx_rm(meta or META, conteudo, "Araújos")))


def _xml(conteudo, parte="word/document.xml", meta=None):
    return _zip(conteudo, meta).read(parte).decode("utf-8")


def _texto(xml):
    return " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))


# ---------------------------------------------------------------------------
# É um .docx de verdade?
# ---------------------------------------------------------------------------
def test_sai_um_zip_com_as_pecas_que_o_word_exige():
    nomes = _zip(UM_ITEM).namelist()
    for parte in ("[Content_Types].xml", "word/document.xml", "word/footer1.xml"):
        assert parte in nomes, f"faltou {parte}"


def test_relatorio_vazio_nao_quebra_e_explica_o_que_fazer():
    txt = _texto(_xml({"partes": []}))
    assert "Auto-popular" in txt


# ---------------------------------------------------------------------------
# ⚠️ A ARMADILHA Nº 1: a ordem do schema ECMA-376
# ---------------------------------------------------------------------------
def test_pBdr_vem_antes_de_shd_e_os_dois_antes_do_espacamento():
    """`w:pPr` tem sequência FIXA. Fora de ordem, o Word ou acusa "conteúdo
    ilegível" ou DESCARTA o elemento EM SILÊNCIO — e a caixa âmbar da cláusula
    suspensiva sumiria do documento oficial sem ninguém perceber."""
    xml = _xml(COM_CAIXA)
    bloco = re.search(r"<w:pPr>(?:(?!</w:pPr>).)*?<w:pBdr>.*?</w:pPr>", xml, re.S)
    assert bloco, "nenhum parágrafo com moldura foi gerado"
    tags = [t for t in re.findall(r"<(w:[a-zA-Z]+)", bloco.group(0))]
    assert tags.index("w:pBdr") < tags.index("w:shd"), "pBdr tem de vir antes de shd"
    if "w:spacing" in tags:
        assert tags.index("w:shd") < tags.index("w:spacing")
    if "w:ind" in tags:
        assert tags.index("w:shd") < tags.index("w:ind")


def test_a_lista_de_sucessores_comeca_onde_o_schema_manda():
    # Recorte literal de CT_PPr._tag_seq. Se alguém reordenar isto, a inserção
    # passa a cair no lugar errado — e o efeito é silencioso.
    assert _SUCESSORES_PBDR[0] == "w:shd"
    assert _SUCESSORES_PBDR[1] == "w:tabs"
    assert "w:spacing" in _SUCESSORES_PBDR and "w:jc" in _SUCESSORES_PBDR


# ---------------------------------------------------------------------------
# ⚠️ A ARMADILHA Nº 2: as tabulações herdadas do estilo Footer
# ---------------------------------------------------------------------------
def test_o_rodape_limpa_as_tabulacoes_de_papel_carta_antes_de_por_as_dele():
    """`w:tabs` é CUMULATIVO na herança de estilo, e o `Footer` do template traz
    paradas de papel CARTA (4680 e 9360 twips). Sem limpar, o endereço sai fora
    do centro e o número da página dentro da margem — em toda página."""
    xml = _xml(UM_ITEM, "word/footer1.xml")
    limpas = re.findall(r'<w:tab [^>]*w:val="clear"[^>]*w:pos="(\d+)"', xml)
    assert set(limpas) == {"4680", "9360"}, f"limpou {limpas}"
    assert 'w:val="center"' in xml and 'w:val="right"' in xml


def test_o_rodape_traz_o_endereco_e_o_numero_de_pagina_como_campo():
    xml = _xml(UM_ITEM, "word/footer1.xml")
    assert "Setor SHS Quadra 6" in _texto(xml)
    # PAGE como CAMPO do Word, não como texto fixo: senão toda página sairia "1".
    assert "PAGE" in xml and "fldChar" in xml


# ---------------------------------------------------------------------------
# ⚠️ A ARMADILHA Nº 3: `\n` e `\t` viram <w:br/> no Word e espaço no PDF
# ---------------------------------------------------------------------------
def test_quebra_e_tabulacao_no_valor_do_campo_viram_espaco():
    assert _uma_linha("Reforma\nda\tquadra") == "Reforma da quadra"
    assert _uma_linha("  dois   espaços  ") == "dois espaços"
    assert _uma_linha(None) == "None"      # o chamador já garante str


def test_o_objeto_com_quebra_sai_numa_linha_so():
    cont = {"partes": [{"ordem": 1, "titulo": "P", "secoes": [{"ordem": 1, "titulo": "S",
            "grupos": [{"ordem": 1, "orgao": "O", "itens": [
                {"tipo": "Convênio", "numero": "1/2025",
                 "objeto": "Linha um\nLinha dois"}]}]}]}]}
    xml = _xml(cont)
    corpo = xml.split("<w:body>")[1]
    assert "Linha um Linha dois" in _texto(corpo)
    assert "<w:br/>" not in corpo


# ---------------------------------------------------------------------------
# Equivalência com o PDF — os dois consomem o MESMO roteiro
# ---------------------------------------------------------------------------
def test_cada_caixa_do_roteiro_vira_exatamente_uma_moldura():
    """Se o Word desenhasse uma caixa a mais ou a menos que o PDF, os dois
    documentos contariam histórias diferentes sobre o mesmo convênio."""
    for cont in (UM_ITEM, COM_CAIXA, DUAS_PARTES, {"partes": []}):
        caixas = sum(1 for t, _ in roteiro_rm(META, cont, "Araújos") if t == "caixa")
        assert _xml(cont).count("<w:pBdr>") == caixas


def test_todo_texto_do_roteiro_chega_ao_documento():
    txt = _texto(_xml(COM_CAIXA))
    for evento, dado in roteiro_rm(META, COM_CAIXA, "Araújos"):
        if evento in ("titulo", "parte", "secao", "grupo", "item"):
            assert _uma_linha(dado) in txt, f"sumiu do .docx: {dado!r}"


def test_a_segunda_parte_comeca_em_pagina_nova():
    xml = _xml(DUAS_PARTES)
    assert "pageBreakBefore" in xml
    # UMA quebra para DUAS partes — a primeira não pode nascer quebrada.
    assert xml.count("pageBreakBefore") == 1


# ---------------------------------------------------------------------------
# O mini-HTML das caixas não pode sair literal
# ---------------------------------------------------------------------------
def test_as_tags_do_markup_nao_saem_impressas():
    txt = _texto(_xml(COM_CAIXA))
    for tag in ("<b>", "</b>", "<i>", "<br/>"):
        assert tag not in txt, f"{tag} saiu literal no documento"


def test_desescapar_desfaz_o_escape_na_ordem_certa():
    # `&amp;` POR ÚLTIMO: na ordem inversa, o texto original "&lt;" sairia "<".
    assert _desescapar("a &amp;lt; b") == "a &lt; b"
    assert _desescapar("Obras &amp; Serviços") == "Obras & Serviços"
    assert _desescapar("&lt;b&gt;") == "<b>"


def test_o_negrito_do_markup_vira_negrito_de_verdade():
    xml = _xml(COM_CAIXA)
    assert "<w:b/>" in xml or 'w:val="true"' in xml or "<w:b " in xml


# ---------------------------------------------------------------------------
# Página e margens
# ---------------------------------------------------------------------------
def test_a_pagina_e_A4_e_nao_o_carta_do_template():
    """O template padrão do python-docx é CARTA. Sem trocar, o RM abriria em
    21,59 x 27,94 cm."""
    xml = _xml(UM_ITEM)
    pg = re.search(r'<w:pgSz [^>]*w:w="(\d+)" w:h="(\d+)"', xml)
    assert pg, "sem w:pgSz"
    # twips: 21,0 cm = 11906 · 29,7 cm = 16838 (tolerância de arredondamento)
    assert abs(int(pg.group(1)) - 11906) <= 2, pg.group(1)
    assert abs(int(pg.group(2)) - 16838) <= 2, pg.group(2)


def test_as_margens_sao_as_mesmas_constantes_do_pdf():
    from services.rm_pdf import _MARGENS_CM
    xml = _xml(UM_ITEM)
    m = re.search(r'<w:pgMar [^>]*w:top="(\d+)"[^>]*w:right="(\d+)"'
                  r'[^>]*w:bottom="(\d+)"[^>]*w:left="(\d+)"', xml)
    assert m, "sem w:pgMar"
    tw = lambda cm: round(cm * 567)      # 1 cm = 567 twips
    assert abs(int(m.group(1)) - tw(_MARGENS_CM[0])) <= 2   # topo
    assert abs(int(m.group(3)) - tw(_MARGENS_CM[1])) <= 2   # base
    assert abs(int(m.group(4)) - tw(_MARGENS_CM[2])) <= 2   # esquerda
    assert abs(int(m.group(2)) - tw(_MARGENS_CM[3])) <= 2   # direita
