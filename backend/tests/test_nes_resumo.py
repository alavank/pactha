"""A linha "Situação do NEs" do RM.

Troca a INFERÊNCIA pelo DOCUMENTO: até aqui o único sinal de empenho era
`detalhe->>'Empenhado'` (Sim/Não), que o próprio rm_builder documenta como furado
— marcava "Aprovadas" como empenhadas sem empenho real.

O caso que os testes existem para travar é a MINUTA: a listagem do portal mistura
o empenho de verdade com uma linha de minuta, sem número e com valor de R$ 1,00.
"""
from services.rm_builder import _nes_resumo


_REAL = {"numero": "2026NE000320", "minuta": "202600000325", "valor": 280000.0,
         "valor_siafi": 280000.0, "situacao": "Enviado",
         "dt_emissao": "09/03/2026", "minuta_apenas": False}
_MINUTA = {"numero": None, "minuta": "202500001654", "valor": 1.0,
           "valor_siafi": None, "situacao": "Minuta de Empenho",
           "dt_emissao": "21/10/2025", "minuta_apenas": True}


def test_imprime_numero_valor_situacao_e_data():
    assert _nes_resumo([_REAL]) == "2026NE000320 — R$ 280.000,00 — Enviado (09/03/2026)"


def test_a_minuta_de_um_real_nao_entra():
    """⚠️ O teste mais importante do arquivo. A minuta tem R$ 1,00 e nenhum
    número; imprimi-la poria R$ 1,00 no relatório como se fosse recurso."""
    t = _nes_resumo([_REAL, _MINUTA])
    assert "R$ 1,00" not in t
    assert "Minuta" not in t
    assert t == "2026NE000320 — R$ 280.000,00 — Enviado (09/03/2026)"


def test_so_minuta_nao_gera_linha():
    assert _nes_resumo([_MINUTA]) == ""


def test_varias_notas_saem_separadas():
    outra = dict(_REAL, numero="2026NE000999", valor=15000.0, dt_emissao="10/03/2026")
    t = _nes_resumo([_REAL, outra])
    assert "2026NE000320" in t and "2026NE000999" in t and ";" in t


def test_nao_coletado_e_vazio_e_nao_afirma_ausencia():
    """Proposta nunca consultada tem a coluna NULA e cai no mesmo vazio de quem
    foi consultado e não tem NE. Por isso o RM apenas OMITE a linha — escrever
    "sem empenho" afirmaria algo que não foi medido."""
    for vazio in (None, [], {}, "nao e json"):
        assert _nes_resumo(vazio) == ""


def test_aceita_jsonb_como_texto():
    """Dependendo do driver o JSONB chega como str."""
    import json
    assert "2026NE000320" in _nes_resumo(json.dumps([_REAL]))
