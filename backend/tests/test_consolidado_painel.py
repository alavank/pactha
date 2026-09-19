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
    base = {"cauc": None, "estadual": None, "vencimentos": {"n": 0, "proximo_dias": None},
            "documentos": {"n": 0, "proximo_dias": None}, "emendas": None, "radar": None}
    base.update(kw)
    return base


def test_irregular_vem_antes_de_prazo_e_sem_dado_nao_pesa():
    irregular = _linha(cauc={"regular": False, "pendencias": 2})
    prazo = _linha(vencimentos={"n": 1, "proximo_dias": 5})
    sem_dado = _linha()
    assert CP.atencao(irregular) > CP.atencao(prazo) > CP.atencao(sem_dado) == 0


def test_cada_bloco_usa_a_conta_da_tela_de_origem():
    fonte = (RAIZ / "services" / "consolidado_painel.py").read_text(encoding="utf-8")
    for chamada in ("bi_cauc_rollup(db, ids)", "query_alertas_vigencia(db, municipio_ids=ids",
                    "documentos_vencendo(db, ids", "_fontes_federais(db, mid)",
                    "unificar_federais(", "R._CTE_ABERTOS", "R._FILTRO_ABERTOS"):
        assert chamada in fonte, chamada


def test_o_resumo_conta_municipios_e_nao_soma_dinheiro():
    fonte = (RAIZ / "services" / "consolidado_painel.py").read_text(encoding="utf-8")
    resumo = fonte[fonte.index('"resumo": {'):fonte.index('"vencimentos": [_venc(v)')]
    assert "valor" not in resumo, "o resumo da carteira passou a somar dinheiro"
    assert resumo.count("sum(1 for l in linhas") == 6


def test_a_rota_do_painel_resolve_escopo_e_cobra_a_permissao():
    fonte = (RAIZ / "routers" / "consolidado.py").read_text(encoding="utf-8")
    bloco = fonte[fonte.index('@router.get("/painel"'):]
    bloco = bloco[:bloco.index("\n@router")]
    assert 'exige("consolidado.ver")' in bloco and "await _escopo(db, current)" in bloco
