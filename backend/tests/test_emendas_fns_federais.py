"""Emendas de saúde do FNS na aba Federais (25/09/2026) — pelo CÓDIGO da emenda.

`nuAnoExercicio` + `coEmendaPolitica` (8 dígitos) é o código de 12 dígitos da
CGU (medido: 36 de 38 pares em Nova Palma, 54 de 58 em Monte Sião, mesmo
autor). O exemplo real de Nova Palma: proposta 36000590943202400, INCREMENTO
MAC, R$ 200 mil, paga, emenda 2024 3298 0006 — HEITOR SCHUCH na CGU.
"""
from services.emendas_unificadas import emendas_fns, totais, unificar_federais


def _parl(nome, co, ano="2024", vl=None):
    d = {"noApelidoPolitico": nome, "coEmendaPolitica": co, "nuAnoExercicio": ano}
    if vl is not None:
        d["vlIndObjeto"] = vl
    return d


def _prop(nu, parls, vl=200_000.0, pago=200_000.0, sit="PAGA"):
    return {"nuProposta": nu, "vlProposta": vl, "vlPago": pago,
            "situacao_desc": sit, "parlamentares": parls,
            "data_pagamento": "12/11/2024"}


def _grupo(props, objeto="INCREMENTO MAC", recurso="EMENDA INDIVIDUAL"):
    return {"objeto": objeto, "recurso": recurso, "props": props}


NOVA_PALMA = _prop("36000590943202400", [_parl("HEITOR SCHUCH", "32980006")])


def test_codigo_do_fns_e_o_da_cgu():
    e, = emendas_fns([_grupo([NOVA_PALMA])])
    assert e["codigo"] == "202432980006"
    assert e["autor"] == "HEITOR SCHUCH" and e["tipo"] == "INDIVIDUAL"
    assert e["valor"] == 200_000.0 and e["pago"] == 200_000.0
    assert e["objeto"] == "INCREMENTO MAC" and e["numero"] == "36000590943202400"


def test_coemenda_curto_ganha_os_zeros_a_esquerda():
    e, = emendas_fns([_grupo([_prop("1", [_parl("FULANO", "3298006")])])])
    assert e["codigo"] == "202403298006"


def test_a_mesma_proposta_em_dois_grupos_conta_uma_vez():
    """Armadilha 1: dois processos do mesmo tipo repetem a lista de propostas."""
    assert len(emendas_fns([_grupo([NOVA_PALMA]), _grupo([NOVA_PALMA])])) == 1


def test_dois_autores_na_proposta_cada_um_com_a_sua_parte_e_o_pago_dividido():
    p = _prop("2", [_parl("FULANO", "11110001", vl=150_000.0),
                    _parl("BELTRANO", "22220001", vl=50_000.0)])
    a, b = sorted(emendas_fns([_grupo([p])]), key=lambda e: -e["valor"])
    assert (a["autor"], a["valor"], a["pago"]) == ("FULANO", 150_000.0, 150_000.0)
    assert (b["autor"], b["valor"], b["pago"]) == ("BELTRANO", 50_000.0, 50_000.0)


def test_mesmo_autor_duas_emendas_na_mesma_proposta_sao_dois_codigos():
    p = _prop("3", [_parl("FULANO", "37080010", "2025", vl=250_000.0),
                    _parl("FULANO", "37080011", "2025", vl=200_000.0)], vl=450_000.0,
              pago=450_000.0)
    assert sorted(e["valor"] for e in emendas_fns([_grupo([p])])) == [200_000.0, 250_000.0]


def test_sem_codigo_nao_entra_e_sem_vlindobjeto_a_proposta_e_da_emenda():
    sem = _prop("4", [{"noApelidoPolitico": "FULANO"}])
    so_um = _prop("5", [_parl("FULANO", "12340001")], vl=80_000.0, pago=None)
    es = emendas_fns([_grupo([sem, so_um])])
    assert [(e["numero"], e["valor"], e["pago"]) for e in es] == [("5", 80_000.0, None)]


def _carteira(codigo, **kw):
    base = {"codigo_emenda": codigo, "ano": 2024, "autor": "Heitor Schuch",
            "tipo": "INDIVIDUAL", "impositiva": True, "valor_indicado": 200_000.0,
            "beneficiario_prefeitura": True, "propostas": [],
            "execucao_consultada": False, "grupo": "nao_consultada"}
    base.update(kw)
    return base


def test_so_no_fns_vira_linha_com_autor_e_recebido():
    fns = emendas_fns([_grupo([NOVA_PALMA])])
    ln, = unificar_federais([], [], [], [], [], fns)
    assert ln["origem"] == "fns" and ln["codigo_emenda"] == "202432980006"
    assert ln["autor"] == "HEITOR SCHUCH" and ln["ano"] == 2024
    assert ln["valor"] == 200_000.0 and ln["recebido_municipio"] == 200_000.0
    assert ln["instrumentos"][0]["origem"] == "fns"
    t = totais([ln])
    assert t["valor_prefeitura"] == 200_000.0 and t["recebido_municipio"] == 200_000.0


def test_na_carteira_vira_instrumento_e_nao_soma():
    """⚠️ O defeito caro: a proposta de saúde somada ao indicado da mesma emenda."""
    fns = emendas_fns([_grupo([NOVA_PALMA])])
    linhas = unificar_federais([_carteira("202432980006")], [], [], [], [], fns)
    assert len(linhas) == 1 and linhas[0]["origem"] == "federal"
    assert linhas[0]["instrumentos"][0]["origem"] == "fns"
    assert totais(linhas)["valor_prefeitura"] == 200_000.0


def test_no_parcerias_vira_instrumento():
    fns = emendas_fns([_grupo([_prop("9", [_parl("FULANO", "32980006", "2025")])])])
    parc = [{"id_proposta": 77, "numero_emenda": "2025.3298.0006", "parlamentar": "FULANO",
             "valor_emenda": 200_000.0, "ano": 2025}]
    linhas = unificar_federais([], [], parc, [], [], fns)
    assert len(linhas) == 1 and linhas[0]["origem"] == "parcerias"
    assert [i["origem"] for i in linhas[0]["instrumentos"]] == ["fns"]


def test_o_mesmo_codigo_em_duas_propostas_soma_as_partes_numa_linha():
    p1 = _prop("A", [_parl("FULANO", "11110001", vl=100_000.0)], vl=100_000.0, pago=100_000.0)
    p2 = _prop("B", [_parl("FULANO", "11110001", vl=60_000.0)], vl=60_000.0, pago=0.0)
    ln, = unificar_federais([], [], [], [], [], emendas_fns([_grupo([p1, p2])]))
    assert ln["valor"] == 160_000.0 and ln["recebido_municipio"] == 100_000.0
    assert len(ln["instrumentos"]) == 2


def test_sem_fns_nada_muda():
    assert unificar_federais([_carteira("202432980006")], [], [], [], []) == \
        unificar_federais([_carteira("202432980006")], [], [], [], [], [])
