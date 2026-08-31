"""SIMEC Termos: as quatro colunas de DINHEIRO que o parser descartava.

Achado em 31/08/2026 investigando o convenio federal 932836/2021 (creche,
Programa SIMEC/PAR4, Araujos). O RM mostrava "Desembolsado: R$ 0,00" e o dono
apontou que no SIMEC ha empenho e pagamento. Estava certo: a pagina de
`carregaTermos.php` traz `Valor Empenhado`, `Pagamento Efetivado` (ou
`Valor Pago`), `Saldo Bancario` e `Prestacao de Contas` ao lado do valor do
termo, e o `_COLS` parava no "Valor do Termo".

⚠️ OS CABECALHOS DESTA FIXTURE FORAM COPIADOS DA PAGINA REAL de Araujos
(POST estuf=MG&muncod=3103900, lida em 31/08/2026), nao inventados a partir do
codigo. As DUAS variantes que a mesma pagina usa estao aqui, porque e justamente
a diferenca entre elas que quebra um mapeamento ingenuo:

  bloco de TC/aditivo ... | Valor do Termo | Valor Empenhado | Pagamento Efetivado | Saldo Bancario (CC + CP + Fundo)
  bloco de PAR/PAC ...... | Quantidade de Obra | Valor do Termo | Valor Empenhado | Valor Pago | Saldo Bancario (...) | Prestacao de Contas
"""
import os
import re

import pytest

from ingestion.simec_termos import _COLS, _mapa_colunas, parse_termos

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLETOR = os.path.join(RAIZ, "ingestion", "simec_termos.py")
MIGRATION = os.path.join(RAIZ, "migrations", "add_simec_termos_dinheiro.sql")

NOVAS = ["valor_empenhado", "valor_pago", "saldo_bancario", "prestacao_contas"]

# --- cabecalho do bloco de TC/aditivo (12 colunas), como o portal escreve -----
_CAB_TC = ("<tr><th>Termo de Compromisso</th><th>Processo</th>"
           "<th>N&ordm; do Documento</th><th>Tipo de Documento</th>"
           "<th>Tipo do Objeto</th><th>Data da Valida&ccedil;&atilde;o</th>"
           "<th>Per&iacute;odo do Pagamento</th><th>Vig&ecirc;ncia</th>"
           "<th>Valor do Termo</th><th>Valor Empenhado</th>"
           "<th>Pagamento Efetivado</th>"
           "<th>Saldo Banc&aacute;rio (CC + CP + Fundo)</th></tr>")

# a linha REAL da creche de Araujos
_TC_CRECHE = ("<tr><td></td><td>23400.002301/2021-01</td><td>202141430-1</td>"
              "<td>TC - Munic&iacute;pios - Com cl&aacute;usula suspensiva</td>"
              "<td>Obra</td><td>30/12/2021</td><td>13/03/2024</td>"
              "<td>30/12/2024 - (-609 dias)</td>"
              "<td>R$3.157.096,83</td><td>R$1.875.147,32</td>"
              "<td>R$572.978,05</td><td>R$0,00</td></tr>")

# --- cabecalho do bloco PAR/PAC (14 colunas): outro rotulo para o pago -------
_CAB_PAR = ("<tr><th>Termo de Compromisso</th><th>Processo</th>"
            "<th>N&ordm; do Documento</th><th>Tipo de Documento</th>"
            "<th>Tipo do Objeto</th><th>Data da Valida&ccedil;&atilde;o</th>"
            "<th>Per&iacute;odo do Pagamento</th><th>Vig&ecirc;ncia</th>"
            "<th>Quantidade de Obra</th><th>Valor do Termo</th>"
            "<th>Valor Empenhado</th><th>Valor Pago</th>"
            "<th>Saldo Banc&aacute;rio (CC + CP + Fundo)</th>"
            "<th>Presta&ccedil;&atilde;o de Contas</th></tr>")

_PAR_QUADRA = ("<tr><td></td><td>23400.005008/2013-88</td><td>04227/2013</td>"
               "<td>PAC2 04227/2013</td><td>PAC - Quadras</td>"
               "<td>19/08/2013</td><td>26/08/2013</td>"
               "<td>20/08/2015 (-4029 dias)</td><td>1</td>"
               "<td>R$510.000,00</td><td>R$510.000,00</td>"
               "<td>R$510.000,00</td><td>R$0,00</td><td>Enviada</td></tr>")


def _pagina(cab, *linhas):
    return "<html><body><table>" + cab + "".join(linhas) + "</table></body></html>"


def _codigo(caminho, marca="#"):
    return "\n".join(l for l in open(caminho, encoding="utf-8").read().splitlines()
                     if not l.lstrip().startswith(marca))


# --------------------------------------------------------------------------
# O que o dono viu faltando
# --------------------------------------------------------------------------
def test_a_creche_de_araujos_traz_empenho_e_pagamento():
    """A linha exata que o RM mostrava como se nada tivesse andado."""
    t = parse_termos(_pagina(_CAB_TC, _TC_CRECHE))[0]
    assert t["valor_termo"] == 3157096.83
    assert t["valor_empenhado"] == 1875147.32
    assert t["valor_pago"] == 572978.05
    assert t["saldo_bancario"] == 0.0


def test_o_outro_rotulo_do_pago_cai_no_mesmo_campo():
    """⚠️ A MESMA pagina usa 'Pagamento Efetivado' num bloco e 'Valor Pago' no
    outro. Mapear so um deixa metade dos termos sem pagamento."""
    t = parse_termos(_pagina(_CAB_PAR, _PAR_QUADRA))[0]
    assert t["valor_pago"] == 510000.00
    assert t["valor_empenhado"] == 510000.00
    assert t["prestacao_contas"] == "Enviada"
    assert t["quantidade_obra"] == "1"
    assert t["valor_termo"] == 510000.00


def test_valor_do_termo_nao_e_confundido_com_valor_pago():
    """⚠️ `_mapa_colunas` casa por FRAGMENTO com `any`. Um fragmento curto como
    'valor' faria 'Valor do Termo' cair em `valor_pago` — e o teste acima
    continuaria passando, porque na quadra os tres numeros sao iguais. Por isso
    a checagem e no MAPA DE INDICES, com o cabecalho de 14 colunas."""
    cab = [re.sub(r"<[^>]+>", "", c) for c in re.findall(r"<th>(.*?)</th>", _CAB_PAR)]
    cab = [c.replace("&ordm;", "º").replace("&aacute;", "á").replace("&ccedil;", "ç")
            .replace("&atilde;", "ã").replace("&eacute;", "é").replace("&iacute;", "í")
           for c in cab]
    idx = _mapa_colunas(cab)
    for campo in ("valor_termo", "valor_empenhado", "valor_pago",
                  "saldo_bancario", "prestacao_contas", "periodo_pagamento",
                  "quantidade_obra"):
        assert campo in idx, f"{campo} nao foi mapeado no cabecalho real"
    # cada um no seu lugar, e nenhum dividindo indice com outro
    assert cab[idx["valor_termo"]] == "Valor do Termo"
    assert cab[idx["valor_empenhado"]] == "Valor Empenhado"
    assert cab[idx["valor_pago"]] == "Valor Pago"
    assert cab[idx["periodo_pagamento"]] == "Período do Pagamento"
    assert len(set(idx.values())) == len(idx), f"duas chaves no mesmo indice: {idx}"


def test_nenhum_fragmento_novo_e_curto_demais():
    """A defesa contra a colisao acima voltar por descuido: 'valor' e 'pagamento'
    sozinhos casam com coluna errada."""
    for campo in NOVAS:
        for frag in _COLS[campo]:
            assert frag not in ("valor", "pagamento", "saldo", "pago"), \
                f"{campo}: fragmento '{frag}' e curto demais e casa coluna errada"


def test_termo_sem_as_colunas_de_dinheiro_nao_inventa_zero():
    """⚠️ Bloco antigo do portal, com 9 colunas. Ausencia tem de virar None —
    zero afirmaria 'nao houve empenho' sobre coluna que nao existe na tabela."""
    cab9 = ("<tr><th>Termo de Compromisso</th><th>Processo</th>"
            "<th>N&ordm; do Documento</th><th>Tipo de Documento</th>"
            "<th>Tipo do Objeto</th><th>Data da Valida&ccedil;&atilde;o</th>"
            "<th>Per&iacute;odo do Pagamento</th><th>Vig&ecirc;ncia</th>"
            "<th>Valor do Termo</th></tr>")
    linha = ("<tr><td>TC</td><td>23000.1/2023-11</td><td>202301</td><td>x</td>"
             "<td>Obra</td><td>12/03/2024</td><td>01/2024</td>"
             "<td>30/12/2024</td><td>R$1.000,00</td></tr>")
    t = parse_termos(_pagina(cab9, linha))[0]
    assert t["valor_termo"] == 1000.00
    for c in NOVAS:
        assert t[c] is None, f"{c} deveria ser None e veio {t[c]!r}"


# --------------------------------------------------------------------------
# As duas pontas: coletor e migration
# --------------------------------------------------------------------------
def test_toda_coluna_nova_chega_ao_INSERT():
    """⚠️ Sao DOIS lugares: o dicionario de `parse_termos` e o INSERT do
    `_upsert`. Tocar so um grava NULL em silencio."""
    src = _codigo(COLETOR)
    ini = src.index("INSERT INTO simec_termos")
    insert = src[ini:src.index("ON CONFLICT", ini)]
    assert insert.count("%s") > len(NOVAS), \
        "a fatia do INSERT saiu curta demais — o teste nao esta lendo o INSERT"
    for c in NOVAS:
        assert re.search(rf"\b{c}\b", insert), f"{c} fora das colunas do INSERT"


def test_as_novas_sao_sobrescritas_e_nao_preservadas():
    """Empenho, pago e saldo MUDAM. Um COALESCE congelaria o numero do dia em
    que a coluna nasceu — o mesmo erro que ja custou o #328."""
    src = _codigo(COLETOR)
    do_update = src[src.index("DO UPDATE SET"):src.index("raw_data=EXCLUDED.raw_data")]
    for c in NOVAS:
        assert f"{c}=EXCLUDED.{c}" in do_update, f"{c} nao e atualizado no upsert"
    assert "COALESCE(simec_termos." not in do_update


def test_a_migration_e_aditiva_e_esta_no_boot():
    from services.startup import MIGRATION_FILES
    assert "add_simec_termos_dinheiro.sql" in MIGRATION_FILES
    sql = _codigo(MIGRATION, "--")
    assert "DROP" not in sql.upper()
    assert "DEFAULT" not in sql.upper(), \
        "DEFAULT 0 diria 'nao houve empenho' sobre termo nunca relido"
    colunas = [l for l in sql.splitlines() if "ADD COLUMN" in l.upper()]
    assert len(colunas) == len(NOVAS)
    for l in colunas:
        assert "NOT NULL" not in l.upper(), l


def test_o_sql_da_migration_e_valido_para_o_postgres():
    pglast = pytest.importorskip("pglast", reason="pglast ausente — checagem PULADA")
    pglast.parse_sql(open(MIGRATION, encoding="utf-8").read())


def test_o_rm_le_as_quatro_no_fim_do_select():
    """⚠️ O resultado do SELECT do RM e lido por INDICE (r[0]..r[8] ja existiam).
    As novas tem de estar DEPOIS de valor_termo, ou tudo desloca em silencio."""
    rm = _codigo(os.path.join(RAIZ, "services", "rm_builder.py"))
    ini = rm.index("FROM simec_termos")
    sel = rm[rm.rindex("SELECT", 0, ini):ini]
    assert sel.index("valor_termo") < sel.index("valor_empenhado")
    for c in NOVAS:
        assert c in sel, f"{c} fora do SELECT do RM"
    assert "_money(r[9])" in rm and "_money(r[10])" in rm and "_money(r[11])" in rm
