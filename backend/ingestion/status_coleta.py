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
        return "error", "recarga vazia (0 linhas); TRUNCATE desfeito, base anterior preservada"
    if antes and total < antes * 0.5:
        return "partial", f"queda de {antes} para {total} linhas (>50%) — verificar fonte"
    return "success", None


def por_falhas(gravados: int, falhas: int, rotulo: str = "item") -> tuple[str, str | None]:
    """Genérica por-falha (consulta_popular_rs, cofin_ses_go): algum esperado não
    rendeu => partial com motivo; nenhum => success. Zero legítimo NÃO é erro aqui."""
    if falhas:
        return "partial", f"{falhas} {rotulo}(s) sem dado"
    return "success", None


def segov_pagamentos(arquivos_ok: int, arquivos_total: int,
                     siafis_nossos: int, siafis_casados: int) -> tuple[str, str | None]:
    """Empenhos/pagamentos estaduais pelo CSV da SEGOV (segov_pagamentos.py).

    Zero NÃO é cego: sem recurso no `package_show` => o CKAN mudou de layout
    (error); nenhum CSV baixado => WAF/rede (error); havia convênios NOSSOS com
    SIAFI e nenhum casou => a chave do CSV mudou (partial); parte do lote falhou
    => partial com a conta. Tenant sem convênio com SIAFI é sucesso legítimo —
    não há o que casar.

    ⚠️ SEM PISO DE COBERTURA, de propósito: os CSVs cobrem só 2022 em diante,
    e um tenant cheio de convênios de 2015-2021 casa POUCO sem que nada esteja
    errado. Cobertura baixa não é sinal; ZERO com convênios nossos é. O coletor
    loga "N de M casaram" para quem quiser olhar."""
    if arquivos_total == 0:
        return "error", "package_show sem recursos 'Pagamentos'/'Restos a Pagar' (layout do CKAN mudou?)"
    if arquivos_ok == 0:
        return "error", f"nenhum dos {arquivos_total} CSVs baixou (WAF/rede)"
    if siafis_nossos and siafis_casados == 0:
        return "partial", f"{siafis_nossos} convenios com SIAFI e 0 casaram o CSV (chave mudou?)"
    if arquivos_ok < arquivos_total:
        return "partial", f"{arquivos_total - arquivos_ok} de {arquivos_total} CSVs falharam"
    return "success", None


def cge_despesa_ob(arquivos_ok: int, arquivos_total: int,
                   nes_nossas: int, nes_resolvidas: int) -> tuple[str, str | None]:
    """OBs (data/nº) pelos dumps da CGE (cge_despesa_ob.py).

    Sem recurso no package_show => layout do CKAN mudou (error); nenhum dump
    baixou => WAF/rede (error); havia NEs nossas do ano e nenhuma resolveu na
    dimensao de empenhos => a chave (nr, data, valor) mudou (partial); parte
    dos dumps falhou => partial com a conta. Sem NE nossa (segov_pagamentos
    ainda nao rodou) e sucesso legitimo — nao ha o que resolver."""
    if arquivos_total == 0:
        return "error", "package_show sem os dumps da CGE (despesa/restos_pagar — layout mudou?)"
    if arquivos_ok == 0:
        return "error", f"nenhum dos {arquivos_total} dumps baixou (WAF/rede)"
    if nes_nossas and nes_resolvidas == 0:
        return "partial", f"{nes_nossas} NEs da SEGOV e 0 resolveram em dm_empenho (chave mudou?)"
    if arquivos_ok < arquivos_total:
        return "partial", f"{arquivos_total - arquivos_ok} de {arquivos_total} dumps falharam"
    return "success", None
