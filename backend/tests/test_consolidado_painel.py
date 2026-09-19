"""O PAINEL DA CARTEIRA — CONSOLIDADO, PR 2 (18/09/2026).

⚠️ O QUE ESTE ARQUIVO IMPEDE:
- "sem coleta" ou "estado sem fonte" virar VERDE;
- município com o prefeitura em dia e o Fundo de Saúde irregular aparecer em dia;
- o painel recalcular por conta própria o que as telas já calculam (duas contas
  para o mesmo dado);
- o resumo da carteira somar DINHEIRO (o risco de 05/08/2026).

Rodar: python -m pytest backend/tests/test_consolidado_painel.py -q
"""
from pathlib import Path

from services import consolidado_painel as CP

RAIZ = Path(__file__).resolve().parent.parent
MG = {"MG", "RS"}


def test_estado_sem_fonte_nao_e_em_dia():
    e = CP.estadual_do_municipio("GO", [], MG)
    assert e["cobertura"] == "sem_fonte" and e["regular"] is None


def test_sem_coleta_nao_e_em_dia():
    e = CP.estadual_do_municipio("MG", [], MG)
    assert e["cobertura"] == "sem_coleta" and e["regular"] is None


def test_uma_entidade_irregular_basta():
    """⚠️ Prefeitura regular + Fundo de Saúde irregular: cada cadastro trava o
    SEU convênio — a regra do `_semaforo_cagec`."""
    e = CP.estadual_do_municipio("MG", [(True, True, 0), (False, False, 4)], MG)
    assert e["regular"] is False and e["entidades_irregulares"] == 1 and e["pendencias"] == 4


def test_tudo_regular_e_em_dia_e_regular_nulo_nao_vira_verde():
    assert CP.estadual_do_municipio("RS", [(True, True, 0), (False, True, 0)], MG)["regular"] is True
    assert CP.estadual_do_municipio("MG", [(True, None, 0)], MG)["regular"] is None


def _linha(**kw):
    base = {"cauc": None, "estadual": None, "documentos": {"n": 0, "proximo_dias": None}}
    base.update(kw)
    return base


def test_irregular_vem_antes_de_documento_e_sem_dado_nao_pesa():
    irregular = _linha(cauc={"regular": False, "pendencias": 2})
    documento = _linha(documentos={"n": 1, "proximo_dias": 5})
    sem_dado = _linha()
    assert CP.atencao(irregular) > CP.atencao(documento) > CP.atencao(sem_dado) == 0


def test_cada_bloco_usa_a_conta_da_tela_de_origem():
    fonte = (RAIZ / "services" / "consolidado_painel.py").read_text(encoding="utf-8")
    for chamada in ("bi_cauc_rollup(db, ids)", "documentos_vencendo(db, ids",
                    "R._CTE_ABERTOS", "R._FILTRO_ABERTOS"):
        assert chamada in fonte, chamada


def test_os_resumos_contam_municipios_e_nao_somam_dinheiro():
    """⚠️ O risco de 05/08/2026: número da carteira lido como de um cliente."""
    fonte = (RAIZ / "services" / "consolidado_painel.py").read_text(encoding="utf-8")
    for bloco in fonte.split('"resumo": {')[1:]:
        resumo = bloco[:bloco.index("},")]
        assert "valor" not in resumo, "um resumo da carteira passou a somar dinheiro"
        assert "sum(1 for l in linhas" in resumo


def test_regularidade_nao_mistura_vencimento_nem_emenda():
    """Pedido do dono (19/09/2026): cada assunto na sua aba."""
    fonte = (RAIZ / "services" / "consolidado_painel.py").read_text(encoding="utf-8")
    corpo = fonte[fonte.index("async def montar_regularidade"):fonte.index("async def _radar")]
    assert "query_alertas_vigencia" not in corpo and "_fontes_federais" not in corpo


def test_as_rotas_resolvem_escopo_e_cobram_a_permissao():
    fonte = (RAIZ / "routers" / "consolidado.py").read_text(encoding="utf-8")
    for rota in ('@router.get("/regularidade"', '@router.get("/radar"'):
        bloco = fonte[fonte.index(rota):]
        bloco = bloco[:bloco.index("\n@router")]
        assert 'exige("consolidado.ver")' in bloco and "await _escopo(db, current)" in bloco
    assert '"/painel"' not in fonte, "o painel único foi dividido em abas"
