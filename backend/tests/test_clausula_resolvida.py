"""Quando a cláusula suspensiva deixa de existir, o RM tem de parar de mostrá-la.

O JSONB `situacao_contratacao_detalhe` é a ÚNICA fonte que o RM lê para a caixa
âmbar (rm_builder lê `Situação Atual do Contrato` e `Motivo da Cláusula
Suspensiva` de dentro dele). Ele é protegido por COALESCE no upsert — o que
impede "não perguntei" de apagar dado bom, mas também o tornava ETERNO: as duas
fontes que se atualizam (o CSV diário e o backfill, que ainda ZERA motivo e data)
convergiam para "Normal" e o relatório seguia apontando pendência resolvida.

`_sem_clausula_confirmado` é o gatilho da limpeza, e o teste existe porque ela
autoriza APAGAR: o risco não é deixar de limpar, é limpar demais.
"""
from ingestion.transferegov_voluntarias import _sem_clausula_confirmado


def test_normal_confirma_que_nao_ha_mais_clausula():
    assert _sem_clausula_confirmado("Normal") is True
    assert _sem_clausula_confirmado("normal") is True
    assert _sem_clausula_confirmado("  Normal  ") is True


def test_clausula_e_liminar_nunca_autorizam_limpeza():
    assert _sem_clausula_confirmado("Cláusula Suspensiva") is False
    assert _sem_clausula_confirmado("Clausula Suspensiva") is False
    assert _sem_clausula_confirmado("Liminar Judicial") is False


def test_campo_nao_lido_preserva():
    """Vazio/None = "não perguntei" (TG_SKIP_ENRICH=1, skip incremental, falha de
    rede). Preservar é o propósito do COALESCE — apagar aqui destruiria dado bom
    em toda rodada que não lê o detalhe."""
    assert _sem_clausula_confirmado("") is False
    assert _sem_clausula_confirmado(None) is False
    assert _sem_clausula_confirmado("   ") is False


def test_valor_inesperado_preserva():
    """⚠️ O teste que define o desenho. A regra é pela POSITIVA ("é Normal?") e não
    pela negativa ("não casa com cláusula?"): com a negativa, a situação do CICLO
    — que é o fallback de `_sit` — autorizaria limpeza, e um bug de leitura
    zeraria a carteira inteira em silêncio. Na dúvida, PRESERVA."""
    for inesperado in ("Em execução", "Em análise", "Prestação de contas",
                       "Assinado", "?", "N/A", "Em Execucao"):
        assert _sem_clausula_confirmado(inesperado) is False
