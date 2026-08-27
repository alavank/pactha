"""Portal da Transparência de MG — confirmar se o Estado pagou o convênio.

⚠️ AS FIXTURES SÃO HTML REAL, capturado do portal em 26/08/2026 (PM Pequi, CNPJ
18.313.874/0001-64). Não foram reconstruídas à mão — e a diferença importa: dois
defeitos deste parser só apareceram quando ele encontrou o HTML de verdade.

O vínculo com o convênio existe num único lugar: o TEXTO LIVRE do "Descrição
Histórico do Empenho". Os dados abertos do Estado (`dm_empenho_desp_AAAA.csv.gz`)
têm 9 colunas e não trazem esse campo — verificado baixando o arquivo.
"""
import io
from pathlib import Path

import pytest

from ingestion.transparencia_mg import (
    casar_convenio, classificar, extrair_referencias, ler_detalhe_empenho,
    ler_id_favorecido, ler_ids_empenho, ler_pagamentos, ler_token,
    montar_pagamentos, normalizar_ref,
)

_FIX = Path(__file__).resolve().parent / "fixtures"
CNPJ = "18313874000164"


def _html(nome: str) -> str:
    return io.open(_FIX / nome, encoding="utf-8", errors="replace").read()


# ------------------------------------------------ passo 1: CNPJ -> id --------
def test_resolve_o_id_do_favorecido_a_partir_do_CNPJ():
    """⚠️ O passo que destravou tudo, e ele não era óbvio: o portal NÃO tem
    autocomplete (digitar no campo não dispara requisição nenhuma) e o POST do
    formulário com o CNPJ cru resolve para id=0. O id estava no link da própria
    página de favorecidos."""
    assert ler_id_favorecido(_html("transpmg_favorecidos.html"), CNPJ) == "1207020"


def test_o_CNPJ_pode_vir_com_pontuacao():
    assert ler_id_favorecido(_html("transpmg_favorecidos.html"),
                             "18.313.874/0001-64") == "1207020"


def test_ignora_o_id_ZERO_que_a_pagina_cita_de_si_mesma():
    """⚠️ O 1º defeito que o HTML real pegou. A página traz o link do breadcrumb
    para si mesma (`.../0/0/<cnpj>/4`), e `re.search` achava esse ZERO primeiro —
    o coletor concluiria que não resolveu, com o id logo adiante no mesmo HTML."""
    h = ('<a href="/consultas-1/despesa-estado/despesa/despesa-favorecidos/'
         f'2026/01-01-2026/31-12-2026/0/0/{CNPJ}/4">Favorecidos</a>'
         '<a href="/consultas-1/despesa-estado/despesa/despesa-favorecidos/'
         f'2026/01-01-2026/31-12-2026/1207020/0/{CNPJ}/4/0/empenhado">PM PEQUI</a>')
    assert ler_id_favorecido(h, CNPJ) == "1207020"


def test_sem_favorecido_devolve_None():
    assert ler_id_favorecido("<html><body>nada</body></html>", CNPJ) is None


# --------------------------------------------- passo 2: listagem ------------
def test_le_os_empenhos_e_o_token_da_listagem():
    h = _html("transpmg_listagem.html")
    assert len(ler_ids_empenho(h)) == 3
    assert ler_token(h) and len(ler_token(h)) == 32


def test_ids_repetidos_nao_viram_duas_visitas():
    h = '<a data-idEmpenho="1">a</a><a data-idEmpenho="1">b</a><a data-idEmpenho="2">c</a>'
    assert ler_ids_empenho(h) == ["1", "2"]


# ------------------------------------------- passo 3: histórico -------------
def test_le_os_campos_do_empenho_no_HTML_real():
    """⚠️ O 2º defeito que o HTML real pegou. O texto achatado do portal é UMA
    linha só — "Número do Empenho: 881 Ano de Exercício: 2026 Data de Registro…" —
    e a 1ª versão parava o valor em "dois espaços", devolvendo None em tudo. O
    valor tem de ir até o PRÓXIMO RÓTULO CONHECIDO."""
    d = ler_detalhe_empenho(_html("transpmg_empenho.html"))
    assert d["tem_rotulo"] is True
    assert d["nr_empenho"] == "881"
    assert d["ano_exercicio"] == "2026"
    assert d["tipo_empenho"] == "ESTIMADO"
    assert "TRANSPORTE ESCOLAR" in d["historico"].upper()


def test_extrai_o_convenio_do_texto_livre():
    d = ler_detalhe_empenho(_html("transpmg_empenho.html"))
    ref, solto = extrair_referencias(d["historico"])
    assert ref == "1261002849/2025"
    assert solto == "9492993"


def test_o_numero_SOLTO_nao_e_confundido_com_convenio():
    """⚠️ A razão de a regex exigir a BARRA e o ano de 4 dígitos. Logo depois do
    número do convênio vem outro número solto, e um padrão de "6 ou mais dígitos"
    pegaria os dois — o segundo viraria um convênio que não existe."""
    ref, solto = extrair_referencias("MUNICIPIO DE PEQUI 1261002849/2025 9492993")
    assert ref == "1261002849/2025" and solto == "9492993"


@pytest.mark.parametrize("h", ["", None, "APROPRIACAO EMPENHO - INVESTIMENTOS",
                               "nota 123 de 2025", "12/2025"])
def test_historico_sem_numero_no_formato_devolve_nada(h):
    assert extrair_referencias(h) == (None, None)


# --------------------------------------------- passo 4: pagamento ----------
def test_le_o_pagamento_no_HTML_real():
    pg = ler_pagamentos(_html("transpmg_pagamento.html"))
    assert len(pg) == 1
    assert pg[0]["data"] == "25/03/2026"
    assert pg[0]["numero"] == "1939"
    assert pg[0]["situacao"] == "Acatada pelo banco"
    assert pg[0]["valor"] == 938793.55


def test_o_bloco_de_pagamento_sai_no_FORMATO_ops_obs():
    """⚠️ Formato copiado das voluntárias de propósito: `rm_builder.
    _desembolso_ops_obs` e `rm_pdf._desembolso_destaque` já sabem lê-lo. Um
    formato próprio exigiria um segundo parser no builder — e seria a segunda
    cópia da mesma regra, que neste repo é o jeito conhecido de as duas
    divergirem."""
    b = montar_pagamentos(ler_pagamentos(_html("transpmg_pagamento.html")))
    assert b["valor_desembolsado"] == 938793.55
    assert b["data_ultimo_desembolso"] == "25/03/2026"
    assert b["obs"][0]["numero_ob"] == "1939"
    assert set(b["obs"][0]) == {"data_emissao_ob", "valor", "numero_ob", "situacao"}


# ------------------------------------------------- a JUNÇÃO ----------------
CONV = [
    {"id": 10, "nr_proposta": "1261002849/2025", "nr_plano_trabalho": None,
     "nr_siafi": None, "nr_sigcon": None},
    {"id": 20, "nr_proposta": "999/2020", "nr_plano_trabalho": None,
     "nr_siafi": "9492993", "nr_sigcon": None},
]


def test_casa_pelo_numero_da_proposta():
    assert casar_convenio("1261002849/2025", CONV) == (10, "casado", "nr_proposta")


def test_a_pontuacao_nao_atrapalha():
    """O portal e o SIGCON escrevem o mesmo número de jeitos diferentes."""
    assert normalizar_ref("1261002849/2025") == normalizar_ref("012610028492025")
    cid, st, _ = casar_convenio("1261002849/2025",
                                [{"id": 7, "nr_proposta": "01261002849-2025"}])
    assert (cid, st) == (7, "casado")


def test_AMBIGUIDADE_nao_escolhe():
    """⚠️ Dois convênios com o mesmo número devolvem `ambiguo` e vínculo NENHUM.
    Escolher "o primeiro" seria inventar um vínculo com 50% de chance de estar
    errado — e ninguém saberia, porque o relatório não mostra a dúvida."""
    dois = [{"id": 1, "nr_proposta": "555/2025"}, {"id": 2, "nr_proposta": "555/2025"}]
    cid, st, _ = casar_convenio("555/2025", dois)
    assert cid is None and st == "ambiguo"


def test_sem_convenio_correspondente_e_nao_casou():
    cid, st, _ = casar_convenio("777777/2025", CONV)
    assert cid is None and st == "nao_casou"


def test_sem_numero_extraido_e_sem_numero():
    assert casar_convenio(None, CONV)[1] == "sem_numero"


def test_o_numero_SOLTO_nao_e_usado_para_juntar():
    """⚠️ O número solto TEM CARA de `nr_siafi` — repare que `CONV[1]` tem
    exatamente esse valor em `nr_siafi`, e casar_convenio o encontraria. Mas isso
    é HIPÓTESE, não medição: juntar por hipótese vincula pagamento ao convênio
    errado.

    A garantia está antes, no extrator: ele devolve o solto num campo SEPARADO, e
    quem vira `ref` é só o que tem barra e ano. Ele é guardado em coluna própria
    justamente para poder ser MEDIDO antes de virar chave."""
    ref, solto = extrair_referencias("MUNICIPIO 1261002849/2025 9492993")
    assert ref == "1261002849/2025", "o solto nao pode virar a referencia"
    assert solto == "9492993"
    # o vínculo sai pela `ref`, e é o convênio 10 — não o 20, que tem o solto
    assert casar_convenio(ref, CONV)[0] == 10


# --------------------------------------- os SETE estados do vínculo --------
def test_cada_falha_tem_um_estado_PROPRIO():
    """⚠️ Nenhum destes colapsa num NULL. Sem a distinção, uma mudança de rótulo
    no portal se disfarça de "empenho sem histórico" para sempre: a cobertura cai
    e nada acusa — o defeito que já custou um ciclo inteiro nas Notas de
    Empenho."""
    assert classificar(False, False, None, None, None, "") == "detalhe_falhou"
    assert classificar(True, False, None, None, None, "") == "layout_mudou"
    assert classificar(True, True, "", None, None, "") == "sem_historico"
    assert classificar(True, True, "texto", None, None, "sem_numero") == "sem_numero"
    assert classificar(True, True, "t", "1/2025", None, "nao_casou") == "nao_casou"
    assert classificar(True, True, "t", "1/2025", None, "ambiguo") == "ambiguo"
    assert classificar(True, True, "t", "1/2025", 10, "casado") == "casado"


def test_o_fluxo_completo_com_o_HTML_REAL():
    """Ponta a ponta, com o que o portal devolveu de verdade."""
    idf = ler_id_favorecido(_html("transpmg_favorecidos.html"), CNPJ)
    d = ler_detalhe_empenho(_html("transpmg_empenho.html"))
    ref, solto = extrair_referencias(d["historico"])
    cid, st, met = casar_convenio(ref, CONV)
    pg = montar_pagamentos(ler_pagamentos(_html("transpmg_pagamento.html")))
    assert idf == "1207020"
    assert (ref, solto) == ("1261002849/2025", "9492993")
    assert (cid, st, met) == (10, "casado", "nr_proposta")
    assert pg["valor_desembolsado"] == 938793.55
    assert classificar(True, d["tem_rotulo"], d["historico"], ref, cid, st) == "casado"
