"""Decisão de status do ingestion_log — funções PURAS, por fonte (auditoria 11/09).

Extraído dos coletores para ser TESTÁVEL por entrada→saída (sem banco, sem rede):
o §14 pede comportamento, não `assert "success" in file`. Cada função devolve
`(status, erro)` no vocabulário do watchdog (`success`/`partial`/`error`), e a
regra de zero NUNCA é cega — é a semântica da fonte que decide.

⚠️ Estas funções NÃO decidem sozinhas o efeito colateral (ex.: o rollback do
siconv_federal fica no coletor); elas só traduzem contadores → status honesto.
"""
from __future__ import annotations


def simec_par(n_mun: int, falhas: int) -> tuple[str, str | None]:
    """SIMEC-PAR: a decisão é por FALHA DE FETCH, não por contagem. Um tenant de 1
    município pode legitimamente ter 0 liberações — 0 registros SEM falha é success.
    Todos os municípios falharam => error (Cloudflare/layout); alguns => partial."""
    if n_mun and falhas == n_mun:
        return "error", f"todos os {n_mun} municipios sem resposta do SIMEC (curl_cffi/layout?)"
    if falhas:
        return "partial", f"{falhas} de {n_mun} municipio(s) sem resposta"
    return "success", None


def cauc(n_gravados: int, esperado: int) -> tuple[str, str | None]:
    """CAUC é lista NACIONAL — todo município ativo deveria casar. Aqui zero-inesperado
    faz sentido: casou menos que o esperado => algo quebrou; zero com municípios => error."""
    if esperado and n_gravados == 0:
        return "error", f"CAUC casou 0 de {esperado} municipios (CSV/layout?)"
    if n_gravados < esperado:
        return "partial", f"CAUC casou {n_gravados} de {esperado} municipios"
    return "success", None


def acordofes(batch_len: int, matched: int) -> tuple[str, str | None]:
    """Acordo FES: planilha vazia (batch=0) => error (implausível 0 credores);
    credores carregados mas nenhum vinculado a município => partial (vínculo por nome)."""
    if batch_len == 0:
        return "error", "planilha AcordoFES vazia/ilegivel (layout/indices?)"
    if matched == 0:
        return "partial", "credores carregados mas 0 vinculados a municipio (matching por nome?)"
    return "success", None


def sigcon_ckan(ours_len: int, matched: int, tem_fatos: bool) -> tuple[str, str | None]:
    """Backfill do CKAN-MG: só ENRIQUECE o que já existe (zero não é erro por si).
    Havia convênios nossos e nenhum casou o dump => matching/dump quebrado; o
    ft_convenio (repasse) não baixou => enriquecimento incompleto."""
    if ours_len and matched == 0:
        return "partial", f"{ours_len} convenios SIGCON e 0 casaram o dado aberto (dump/matching?)"
    if not tem_fatos:
        return "partial", "ft_convenio (repasse) nao baixou — enriquecimento parcial"
    return "success", None


def siconv_federal(total: int, antes: int) -> tuple[str, str | None]:
    """Recarga da base nacional. total=0 => recarga vazia (o coletor faz rollback e
    PRESERVA a base anterior) => error. Queda >50% vs. anterior => partial (pode ser
    limpeza real da fonte, mas o watchdog olha)."""
    if total == 0:
        return "error", f"recarga vazia (0 linhas); TRUNCATE desfeito, base anterior preservada"
    if antes and total < antes * 0.5:
        return "partial", f"queda de {antes} para {total} linhas (>50%) — verificar fonte"
    return "success", None


def por_falhas(gravados: int, falhas: int, rotulo: str = "item") -> tuple[str, str | None]:
    """Genérica por-falha (consulta_popular_rs, cofin_ses_go): algum esperado não
    rendeu => partial com motivo; nenhum => success. Zero legítimo NÃO é erro aqui."""
    if falhas:
        return "partial", f"{falhas} {rotulo}(s) sem dado"
    return "success", None
