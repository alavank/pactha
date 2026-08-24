"""A BUSCA das propostas federais: o padrão ILIKE que sobrevive ao acento que a
coleta apagou.

O portal serve U+FFFD no lugar da letra acentuada e o `_clean` do coletor APAGA
esse caractere — o banco guarda "MUNICPIO DE SO GONALO" onde o portal queria
"MUNICÍPIO DE SÃO GONÇALO". Sem tolerar isso, separar a caixa única em quatro
campos só troca uma caixa que não acha por quatro que não acham.
"""
import re

from routers.transferegov import _CATEGORIA_SQL, _digits, _padrao_like


def _casa(padrao: str, texto: str) -> bool:
    """Simula o ILIKE do Postgres sobre o padrão gerado: `%` = qualquer trecho,
    `_` = um caractere, `\\` escapa o próximo. Sem isso o teste afirmaria sobre
    a string do padrão e não sobre o que ela ACHA."""
    rx, i = [], 0
    while i < len(padrao):
        c = padrao[i]
        if c == "\\" and i + 1 < len(padrao):
            rx.append(re.escape(padrao[i + 1])); i += 2; continue
        rx.append(".*" if c == "%" else "." if c == "_" else re.escape(c))
        i += 1
    return re.fullmatch("".join(rx), texto, re.I | re.S) is not None


# ---------------------------------------------------------------------------
# O caso que motivou o campo
# ---------------------------------------------------------------------------
def test_o_termo_acentuado_acha_o_nome_com_o_acento_APAGADO():
    p = _padrao_like("São Gonçalo")
    assert _casa(p, "MUNICPIO DE SO GONALO")        # como está no banco
    assert _casa(p, "MUNICÍPIO DE SÃO GONÇALO")     # como o portal queria
    assert _casa(p, "MUNICIPIO DE SAO GONCALO")     # sem acento


def test_termo_sem_acento_continua_achando_o_texto_acentuado():
    assert _casa(_padrao_like("Araujos"), "MUNICÍPIO DE ARAUJOS")


def test_o_padrao_e_um_contains():
    p = _padrao_like("981397")
    assert _casa(p, "981397")
    assert _casa(p, "convênio 981397/2025")
    assert not _casa(p, "981398")


# ---------------------------------------------------------------------------
# Curingas digitados: sem escapar, o filtro devolveria a base inteira
# ---------------------------------------------------------------------------
def test_porcento_digitado_e_literal_e_nao_traz_tudo():
    p = _padrao_like("50%")
    assert _casa(p, "desconto de 50% na obra")
    assert not _casa(p, "obra sem desconto")


def test_underline_digitado_casa_underline_e_nao_qualquer_letra():
    p = _padrao_like("a_b")
    assert _casa(p, "xxa_byy")
    assert not _casa(p, "xxaXbyy")


def test_barra_invertida_e_escapada():
    assert _casa(_padrao_like("a\\b"), "za\\bz")


# ---------------------------------------------------------------------------
# Termo vazio: quem chama TEM de pular o filtro
# ---------------------------------------------------------------------------
def test_termo_vazio_devolve_string_vazia_e_nao_um_curinga():
    # ⚠️ "%%" traria a base inteira e pareceria "o filtro não funciona".
    for t in ("", "   ", None):
        assert _padrao_like(t or "") == ""


# ---------------------------------------------------------------------------
# CNPJ: só os dígitos, dos dois lados
# ---------------------------------------------------------------------------
def test_cnpj_com_e_sem_mascara_dao_os_mesmos_digitos():
    assert _digits("18.243.220/0001-01") == _digits("18243220000101")
    assert _digits("18243220000101") == "18243220000101"


def test_termo_sem_digito_nenhum_nao_vira_filtro_de_cnpj():
    assert _digits("prefeitura") == ""


# ---------------------------------------------------------------------------
# _CATEGORIA_SQL: o link do PAC não pode levar a uma tela vazia
# ---------------------------------------------------------------------------
def test_a_categoria_cobre_as_quatro_telas_e_tem_saida_para_situacao_nula():
    # `situacao` NULA cai no ELSE, igual ao ramo `situacao IS NULL` do handler.
    for cat in ("'voluntarias'", "'rejeitadas'", "'encerradas'", "'geral'"):
        assert cat in _CATEGORIA_SQL
    assert _CATEGORIA_SQL.strip().startswith("CASE")
    assert _CATEGORIA_SQL.strip().endswith("END")
    # Sem qualificador de tabela: só vale onde transferegov_propostas é a única
    # tabela com a coluna `situacao`.
    assert "p.situacao" not in _CATEGORIA_SQL
