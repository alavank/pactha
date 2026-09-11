"""Emenda Pix (Transferência Especial): dados bancários no sistema.

Pedido do dono (11/09/2026): "coloca os dados bancários nas emendas Pix; dentro
do sistema do transferegov tem as informações". Confirmado contra a API pública
`api-publica.transferegov.gestao.gov.br/especiais/planos-acao-especiais`: o plano
de ação traz `codigo_banco_plano_acao`/`nome_banco_plano_acao`,
`numero_agencia_plano_acao`+`dv_agencia_plano_acao`,
`numero_conta_plano_acao`+`dv_conta_plano_acao`. O coletor (`transferegov_te.py`)
já guarda o plano inteiro em `raw_data` — só faltava expor. Este teste guarda a
fiação (o `_num_dv` e o fato de o `buscar`/export lerem esses campos).
"""
import os
import re

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/d")
os.environ.setdefault("JWT_SECRET", "x")
os.environ.setdefault("BI_MODULE", "1")

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fonte(p):
    return open(os.path.join(RAIZ, p), encoding="utf-8").read()


def test_num_dv_monta_agencia_e_conta():
    from routers.transferegov import _num_dv
    assert _num_dv("12345", "6") == "12345-6"   # número + DV
    assert _num_dv("999", "") == "999"          # sem DV
    assert _num_dv("", "") is None              # sem número não inventa
    assert _num_dv(None, None) is None


def test_buscar_expoe_banco_agencia_conta_do_plano():
    """O `buscar` da TE lê os campos bancários do raw_data do plano de ação."""
    src = _fonte("routers/transferegov.py")
    assert 'raw.get("nome_banco_plano_acao")' in src
    assert 'raw.get("numero_agencia_plano_acao")' in src and 'raw.get("dv_agencia_plano_acao")' in src
    assert 'raw.get("numero_conta_plano_acao")' in src and 'raw.get("dv_conta_plano_acao")' in src
    # os três campos saem no item devolvido
    assert re.search(r'"banco":\s*raw\.get', src)
    assert '"agencia": _num_dv(' in src and '"conta": _num_dv(' in src


def test_export_plano_acao_tem_coluna_dados_bancarios():
    src = _fonte("routers/export_pdf.py")
    assert '"Dados bancários"' in src
    # a célula combina banco/agência/conta do item
    assert 'it.get("banco")' in src and 'it.get("agencia")' in src and 'it.get("conta")' in src
