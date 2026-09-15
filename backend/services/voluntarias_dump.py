"""VOLUNTARIAS: o que a tela e o RM leem da ARVORE dos dumps (15/09/2026).

O coletor e `ingestion/transferegov_arvore.py`; aqui ficam as regras de LEITURA
que mais de um lugar usa — a lista, o modal e o RM tem de dizer a MESMA coisa
sobre o mesmo convenio (ver a memoria "mesmo dado, mesma conta em toda tela").

Funcoes PURAS: recebem o JSONB ja lido e a data de hoje, sem banco.
"""
from __future__ import annotations

import copy
import json
from datetime import date, datetime
from typing import Any, Optional

# Situacoes do CONVENIO (SIT_CONVENIO do dump) em que a prestacao de contas
# AINDA NAO FOI ENTREGUE. So nelas o prazo vencido e afirmacao segura: "Em
# Analise", "Aprovada", "Concluida" ja mostram que a prestacao foi enviada.
_PC_NAO_ENTREGUE = ("em execucao", "aguardando prestacao de contas")


def _jsonb(v) -> Any:
    if isinstance(v, (str, bytes)):
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return None
    return v


def _sem_acento(s: str) -> str:
    import unicodedata
    n = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in n if not unicodedata.combining(c)).lower().strip()


def data_br(v) -> Optional[date]:
    """'27/12/2022' ou '19/07/2024 15:22:47' -> date. None quando nao casa."""
    s = str(v or "").strip()[:10]
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except ValueError:
        return None


def dias_desde(v, hoje: Optional[date] = None) -> Optional[int]:
    d = data_br(v)
    if not d:
        return None
    return ((hoje or date.today()) - d).days


def sem_cpf(v):
    """A arvore SEM campo de CPF, em qualquer profundidade.

    O dump publica CPF de pessoa fisica em dois arquivos:
      - `apoiadores_emendas_programas.CPF_PF_SOLICITANTE_APOIADORES_EMENDAS`;
      - `execucao_fisica_cipi.cpf_responsavel_operacao`.
    Nenhuma tela usa. O nome da pessoa fica; o documento nao sai do banco para o
    navegador. E minimizacao (LGPD), e custa uma chave."""
    if isinstance(v, dict):
        return {k: sem_cpf(x) for k, x in v.items() if "cpf" not in str(k).lower()}
    if isinstance(v, list):
        return [sem_cpf(x) for x in v]
    return v


def ops_obs_preferido(aberto, raspado) -> tuple[Optional[dict], Optional[str]]:
    """O desembolso a mostrar: (bloco no formato `ops_obs`, fonte).

    ⭐ O DUMP MANDA (`ops_obs_aberto`). Ele vem do `siconv_desembolso.zip`, que
    nao depende da sessao gov.br (morta 297 h em 720 h na auditoria) e cobre
    todo convenio, enquanto a raspagem so existe onde a sessao estava viva.

    ⚠️ E NAO SE PERDE O QUE SO A RASPAGEM TEM. A tela logada traz o numero da
    NS e da OP e a SITUACAO de cada ordem bancaria, que o dump nao publica. Onde
    o numero da OB bate EXATAMENTE, esses campos passam para a linha do dump.
    Nao ha soma de linha "so da raspagem": a do portal inclui OP ainda nao paga,
    e somar as duas listas contaria o mesmo dinheiro duas vezes.

    Sem o dump (proposta sem convenio no arquivo, ou coletor ainda nao rodou),
    volta a raspagem, como antes."""
    a = _jsonb(aberto)
    r = _jsonb(raspado)
    if not isinstance(a, dict):
        return (r, "portal") if isinstance(r, dict) else (None, None)
    out = copy.deepcopy(a)
    por_ob = {}
    if isinstance(r, dict):
        for ob in r.get("obs") or []:
            if isinstance(ob, dict) and (ob.get("numero_ob") or "").strip():
                por_ob[ob["numero_ob"].strip()] = ob
    for ob in out.get("obs") or []:
        rasp = por_ob.get((ob.get("numero_ob") or "").strip())
        if rasp:
            for k in ("numero_ns", "numero_op", "numero_interno", "situacao", "gestao_emitente"):
                if rasp.get(k) and not ob.get(k):
                    ob[k] = rasp[k]
    return out, "dump"


def processo_execucao_preferido(lista_dump, n_dump, lista_raspada, qtd_raspada
                                ) -> tuple[Optional[list], Optional[int], Optional[str]]:
    """As licitacoes do instrumento ("Processo de Execucao"): (lista, qtd, fonte).

    ⭐ O DUMP MANDA desde 15/09/2026 (PR 4 da §1.26): `arvore.processo_execucao`
    tem o MESMO formato da lista raspada, e a raspagem dessa tela (sessao gov.br,
    SP `execucao`) passou a ser reserva (`TG_PROC_EXEC`, desligada). A contagem
    vem de `_resumo.n_licitacoes`, porque a lista da arvore tem teto (convenio
    do Estado chega a 11 mil licitacoes).

    Sem a lista do dump (proposta sem convenio, arvore ainda nao colhida), vale
    o que a raspagem gravou antes."""
    ld = _jsonb(lista_dump)
    if isinstance(ld, list):
        n = n_dump if isinstance(n_dump, int) else None
        if n is None:
            try:
                n = int(str(n_dump))
            except (TypeError, ValueError):
                n = len(ld)
        return ld, n, "dump"
    lr = _jsonb(lista_raspada)
    if lr is None and qtd_raspada is None:
        return None, None, None
    return (lr if isinstance(lr, list) else None), qtd_raspada, "portal"


def notas_empenho_preferidas(aberto, raspado) -> tuple[Optional[list], Optional[str]]:
    """A listagem de NEs a usar: (lista, fonte) — "dump", "dump+portal" ou "portal".

    ⭐ O DUMP MANDA desde 15/09/2026 (PR 4 da §1.26), quando existe
    (`notas_empenho_aberto` nao nulo). A raspagem da aba Execucao Concedente
    (`TG_NES`, sessao gov.br) foi desligada, e a coluna dela para de ser
    atualizada: dado velho NA FRENTE do novo e o que isto impede.

    ⚠️ E A RASPAGEM ANTIGA COMPLETA, porque "nao podemos perder informacao"
    (requisito do dono, `tests/test_rm_empenho_agregado.py`). Ela tem coisas que
    o dump nao tem, e elas CONTINUAM:
      - NE que so a tela listava — a MINUTA (`minuta_apenas`, que as funcoes do
        RM ja ignoram) e a NE que o dump publica com VALOR 0 e por isso fica fora
        de `notas_empenho_aberto` (convenio 901671: 2 das 3 NEs);
      - no numero que os dois tem, `minuta` e `valor_siafi` passam para a linha
        do dump; o valor e a situacao do dump mandam.
    NE que so o dump tem entra normalmente.

    Sem dump para a proposta, vale a listagem raspada gravada antes."""
    a = _jsonb(aberto)
    r = _jsonb(raspado)
    if not isinstance(a, list):
        return (r, "portal") if isinstance(r, list) else (None, None)
    out = [dict(x) for x in a if isinstance(x, dict)]
    por_num = {(x.get("numero") or "").strip(): x for x in out if (x.get("numero") or "").strip()}
    completou = False
    for n in r if isinstance(r, list) else []:
        if not isinstance(n, dict):
            continue
        numero = (n.get("numero") or "").strip()
        alvo = por_num.get(numero) if numero else None
        if alvo is not None:
            for k in ("minuta", "valor_siafi"):
                if n.get(k) not in (None, "") and alvo.get(k) in (None, ""):
                    alvo[k] = n[k]
        else:
            out.append(dict(n))
            completou = True
    return out, ("dump+portal" if completou else "dump")


def sinais_do_resumo(resumo, hoje: Optional[date] = None) -> Optional[dict]:
    """Os sinais que a LISTA mostra como selo, a partir do `_resumo` da arvore.

    Cada sinal so sai com PROVA no dado. Ausencia de sinal e "nada a apontar"
    OU "nao medido" — nunca afirmacao de que esta tudo bem.
      prorrogada          a vigencia atual difere da original do convenio
      dias_sem_desembolso so para convenio EM EXECUCAO com saldo a desembolsar:
                          dias desde o ultimo desembolso (ou desde a assinatura,
                          quando nunca houve) — contados HOJE, e nao na coleta
      pc_dias             dias ate o prazo da prestacao de contas (negativo =
                          vencido), SO quando o convenio mostra que ela nao foi
                          entregue ("Em execução" / "Aguardando...")
      execucao_fisica_pct o percentual publicado no resumo fisico-financeiro
      subsituacao         "Em processo de TCE", "Em Prorrogação"...
    """
    r = _jsonb(resumo)
    if not isinstance(r, dict) or not r.get("tem_convenio"):
        return None
    hoje = hoje or date.today()
    sit = _sem_acento(r.get("situacao_convenio") or "")
    out: dict[str, Any] = {
        "situacao_convenio": r.get("situacao_convenio"),
        "subsituacao": r.get("subsituacao_convenio") or None,
        "execucao_fisica_pct": r.get("execucao_fisica_pct"),
        "desembolsado": r.get("desembolsado"),
        "pago_fornecedores": r.get("pago_fornecedores"),
        "vigencia_original": r.get("vigencia_original"),
        "prorrogada": bool(r.get("vigencia_original") and r.get("vigencia_atual")
                           and data_br(r.get("vigencia_original")) != data_br(r.get("vigencia_atual"))),
        "dias_sem_desembolso": None,
        "nunca_desembolsou": False,
        "pc_limite": None,
        "pc_dias": None,
    }
    a_desemb = r.get("a_desembolsar")
    if sit == "em execucao" and a_desemb is not None and a_desemb > 0.01:
        if r.get("ultimo_desembolso"):
            out["dias_sem_desembolso"] = dias_desde(r.get("ultimo_desembolso"), hoje)
        elif r.get("assinatura"):
            out["dias_sem_desembolso"] = dias_desde(r.get("assinatura"), hoje)
            out["nunca_desembolsou"] = True
    if sit in _PC_NAO_ENTREGUE and r.get("prestacao_contas_limite"):
        lim = data_br(r.get("prestacao_contas_limite"))
        if lim:
            out["pc_limite"] = r.get("prestacao_contas_limite")
            out["pc_dias"] = (lim - hoje).days
    return out
