"""O pago do SIMEC/PAR na PROPRIA linha da voluntaria (a creche 932836/2021).

Pedido do dono (15/09/2026): "da creche ainda falta o valor que ja foi pago,
esta no SIMEC" — e ele quer ve-lo na linha da creche, "em ambos" os RMs (anual
e completo). O SICONV mostra "Desembolsado: R$ 0,00" porque o FNDE paga o PAR
pelo SIMEC, fora da OB do SICONV; o pago JA era coletado (`simec_termos`,
desde 31/08) mas saia como item separado e so no RM completo.

A juncao e pelo Nº DO PROCESSO (SEI), digitos apenas: `numero_processo` da
voluntaria (dado aberto diario, NR_PROCESSO) x `simec_termos.processo`. Os
valores da fixture sao os da creche de Araujos (test_simec_termos_dinheiro).
"""
import os

from services import rm_pdf
from services.rm_builder import (_simec_na_linha, _simec_termos_mapa, _situacao_com_marcas,
                                 _so_digitos)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILDER = os.path.join(RAIZ, "services", "rm_builder.py")

# (processo, nr_documento, tipo_documento, tipo_objeto, dt_vigencia, valor_termo,
#  valor_empenhado, valor_pago, saldo_bancario, prestacao_contas)
CRECHE = ("23400.002301/2021-01", "202141430-1", "TC - Municípios - Com cláusula suspensiva",
          "Obra", None, 3157096.83, 1875147.32, 572978.05, 0.0, None)


def test_a_chave_e_so_digitos_dos_dois_lados():
    """O SIMEC escreve '23400.002301/2021-01'; o CSV do TransfereGov escreve com
    a pontuacao dele. Comparar texto seria apostar na grafia."""
    assert _so_digitos("23400.002301/2021-01") == "23400002301202101"
    assert _so_digitos("23400002301202101") == "23400002301202101"
    assert _so_digitos(None) == "" and _so_digitos("") == ""


def test_mapa_por_processo_ignora_termo_sem_processo_e_fica_com_o_mais_pago():
    aditivo = CRECHE[:7] + (600000.0, 0.0, "Enviada")   # o mesmo TC, relido com mais pago
    m = _simec_termos_mapa([CRECHE, ("", "X", "PAC", "Quadra", None, 1, 1, 1, 0, None), aditivo])
    assert list(m) == ["23400002301202101"]
    assert m["23400002301202101"]["valor_pago"] == 600000.0
    assert m["23400002301202101"]["nr_documento"] == "202141430-1"


def test_sem_termo_casado_nada_muda():
    assert _simec_na_linha(None, None) == {}
    assert _simec_na_linha({}, 0) == {}


def test_o_pago_do_simec_vira_o_desembolsado_SO_onde_o_siconv_nao_mediu():
    tc = _simec_termos_mapa([CRECHE])["23400002301202101"]
    c = _simec_na_linha(tc, None)
    assert c["valor_desembolsado"] == 572978.05
    # ⚠️ e o "a desembolsar" do SICONV sai junto: a revisao pegou a caixa do PDF
    # somando "Desembolsado R$ 572.978,05 (SIMEC) · A desembolsar R$ 3.819.853,65
    # (SICONV)" = R$ 4,39 mi num convenio de R$ 3,82 mi.
    assert "valor_a_desembolsar" in c and c["valor_a_desembolsar"] is None
    assert "pago R$ 572.978,05" in c["simec_pagamento"]
    # "no SIMEC" no rotulo: a mesma linha imprime o "Valor empenhado" das NEs do
    # SICONV (R$ 819 mil na creche) e os dois numeros diferem.
    assert "empenhado no SIMEC R$ 1.875.147,32" in c["simec_pagamento"]
    assert "TC 202141430-1" in c["simec_pagamento"]
    assert "processo 23400.002301/2021-01" in c["simec_pagamento"]
    # SICONV com OB medida (R$ 0,00 tambem e medicao? NAO: 0 e "nada saiu", e o
    # SIMEC diz que saiu) -> o pago do SIMEC entra
    assert "valor_desembolsado" in _simec_na_linha(tc, 0.0)
    # SICONV JA desembolsou: a OB do SICONV e a medicao e fica — inteira, com o
    # "a desembolsar" dela.
    c2 = _simec_na_linha(tc, 200000.0)
    assert "valor_desembolsado" not in c2 and "valor_a_desembolsar" not in c2
    assert "simec_pagamento" in c2


def test_simec_sem_pago_nao_afirma_desembolso():
    tc = dict(_simec_termos_mapa([CRECHE])["23400002301202101"], valor_pago=0.0)
    c = _simec_na_linha(tc, None)
    assert "valor_desembolsado" not in c
    assert "pago R$ 0,00" in c["simec_pagamento"]


def test_o_marcador_da_situacao_passa_a_dizer_desembolsado():
    """E a mesma funcao pura da voluntaria: com o pago do SIMEC no lugar do
    `valor_desembolsado`, a Situacao atual troca o silencio por 'Desembolsado'."""
    s = _situacao_com_marcas("Proposta/Plano de Trabalho Aprovados", False, True, 572978.05)
    assert s.endswith("Desembolsado: R$ 572.978,05")


def test_o_pdf_imprime_a_linha_do_simec():
    campos = rm_pdf._campos_do_item({"numero": "932836 /2021",
                                     "simec_pagamento": "empenhado R$ 1,00 · pago R$ 2,00 — TC X"})
    assert ("Pagamento SIMEC/PAR", "empenhado R$ 1,00 · pago R$ 2,00 — TC X") in campos
    assert not any(r == "Pagamento SIMEC/PAR" for r, _ in rm_pdf._campos_do_item({"numero": "1"}))


def test_o_select_das_voluntarias_traz_o_processo_por_ULTIMO():
    """O laco le por INDICE (row[N]); inserir no MEIO desloca tudo em silencio.
    `numero_processo` e a decima coluna pendurada no fim, row[33]."""
    src = open(BUILDER, encoding="utf-8").read()
    ini = src.index("SELECT id, numero_proposta, codigo_instrumento, situacao, orgao, objeto,")
    sel = src[ini:src.index("FROM transferegov_propostas WHERE municipio_id = :m", ini)]
    cols = [l.strip() for l in sel.splitlines() if l.strip() and not l.strip().startswith("--")]
    assert cols[-1] == "numero_processo"
    assert "_so_digitos(row[33])" in src


def test_o_termo_casado_nao_repete_e_so_e_marcado_DEPOIS_de_a_voluntaria_entrar():
    """Duas disciplinas no fonte, e a segunda e uma regressao que a revisao pegou:
    marcar o processo como "ja exibido" ANTES do add_item fazia o recorte
    'pagas' descartar a creche (nao paga no SICONV) E pular o termo (pago) —
    o dinheiro do FNDE sumia dos dois. O bloco dos termos fica atras do
    `if completo:` como sempre: `completo` e True nos dois chamadores, e o
    "anual" da tela e a selecao de anos."""
    src = open(BUILDER, encoding="utf-8").read()
    ini = src.index("=== SIMEC/PAR — TERMOS DE COMPROMISSO")
    bloco = src[ini:src.index("=== Novo PAC", ini)]
    assert "if completo:" in bloco and "in _simec_ja_exibidos" in bloco
    assert "_federal_destino(" not in bloco, "ramo 'anual' e codigo morto: completo=False nao tem chamador"
    # a query continua lendo as quatro de dinheiro no FIM (indice r[9]..r[12])
    assert "valor_empenhado, valor_pago, saldo_bancario, prestacao_contas" in bloco
    # a marcacao vem DEPOIS do add_item da voluntaria, condicionada ao retorno
    vol = src[src.index("_pac_ja_exibidos: set[str] = set()"):ini]
    i_add = vol.index("_entrou = add_item(parte, secao, orgao, {")
    i_mark = vol.index("_simec_ja_exibidos.add(_so_digitos(row[33]))")
    assert i_add < i_mark and "if (_entrou and _tc" in vol
    # e "Pendente de empenho" nao sai ao lado de empenho no SIMEC
    assert "and not _tc_empenhado)" in vol
