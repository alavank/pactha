"""Voluntárias: a sessão gov.br vira RESERVA (PR 4 da §1.26, 15/09/2026).

Três raspagens deixam de rodar nos workers (o código fica, atrás de chave):
  - notas de empenho (`TG_NES=0`)       -> `notas_empenho_aberto` manda
  - OPs/OBs (`TG_OPS_OBS=0`)            -> `ops_obs_aberto` manda (PR 3)
  - licitações ("Processo de Execução", `TG_PROC_EXEC`, desligada por padrão)
                                        -> `arvore.processo_execucao` manda
Obras segue raspada (`TG_OBRAS=1`): ART/RT e responsável técnico não estão no dump.

O que se prova: a lista de licitações do dump tem o formato que o RM interpreta
("Pendente de desembolso" pelo aceite, "em elaboração" pela situação), os
leitores a preferem, e as chaves separam o que precisa separar.
"""
import json
from pathlib import Path

from ingestion import transferegov_arvore as ta
from services.voluntarias_dump import processo_execucao_preferido

BACKEND = Path(__file__).resolve().parents[1]
FIX = json.loads((BACKEND / "tests" / "fixtures" / "tg_arvore_dumps.json").read_text(encoding="utf-8"))


def _coleta():
    def ler(nome):
        yield from (dict(x) for x in FIX.get(nome, []))
    props = {p["ID_PROPOSTA"]: (4, p["IDENTIF_PROPONENTE"]) for p in FIX["_propostas"]}
    return ta.coleta(props, {"4313102": 4}, ler=ler)


# ---------------------------------------------------------------------------
# A lista de licitações do dump, no formato da tela
# ---------------------------------------------------------------------------
def test_a_arvore_traz_o_processo_de_execucao_no_formato_da_tela():
    c = _coleta()
    pe = c.arvores["1531858"]["processo_execucao"]
    assert len(pe) == 3 == c.arvores["1531858"]["_resumo"]["n_licitacoes"]
    assert set(pe[0]) == {"numero", "modalidade", "data_publicacao", "situacao",
                          "sistema_origem", "aceite"}
    # Mais recentes primeiro, e a constante da fonte traduzida.
    datas = [ta._dt(x["data_publicacao"]) for x in pe]
    assert datas == sorted(datas, reverse=True)
    assert all(x["situacao"] in ("Concluído", "Em elaboração") for x in pe)
    # Proposta sem convênio não ganha a chave (nada a afirmar).
    assert "processo_execucao" not in c.arvores["824122"]


def test_o_rm_le_aceite_e_elaboracao_na_lista_do_dump():
    from services.rm_builder import _lic_em_elaboracao, _licitacao_aceita
    lista = ta._processo_execucao([
        {"NR_LICITACAO": "1", "STATUS_LICITACAO": "EM_ELABORACAO",
         "DATA_PUBLICACAO_LICITACAO": "01/02/2026", "SITUACAO_ACEITE_PROCESSO_EXECU": "Aguardando Aceite"},
        {"NR_LICITACAO": "2", "STATUS_LICITACAO": "CONCLUIDO",
         "DATA_PUBLICACAO_LICITACAO": "01/01/2026", "SITUACAO_ACEITE_PROCESSO_EXECU": "Aceito"},
    ])
    assert _lic_em_elaboracao(lista) is True
    assert _licitacao_aceita(lista) is True
    assert _licitacao_aceita(lista[:1]) is False       # "Aguardando Aceite" não é aceite
    rejeitada = ta._processo_execucao([{"NR_LICITACAO": "3", "SITUACAO_ACEITE_PROCESSO_EXECU": "Rejeitado"}])
    assert _licitacao_aceita(rejeitada) is False


def test_a_lista_tem_teto_e_a_contagem_nao():
    """Convênio do Estado chega a 11.333 licitações: a lista para em 500, e a
    contagem inteira fica no `_resumo` (é ela que os leitores usam)."""
    muitas = [{"NR_LICITACAO": str(i), "DATA_PUBLICACAO_LICITACAO": "01/01/2020"} for i in range(600)]
    assert len(ta._processo_execucao(muitas)) == ta.TETO_PROCESSO_EXECUCAO == 500
    lst, qtd, fonte = processo_execucao_preferido(ta._processo_execucao(muitas), 600, None, None)
    assert (len(lst), qtd, fonte) == (500, 600, "dump")


def test_arquivo_de_licitacao_que_falha_mantem_a_lista_anterior():
    def ler(nome):
        if nome == "siconv_licitacao":
            raise ta.FalhaArquivo("siconv_licitacao: cabecalho sem ['X']")
        yield from (dict(x) for x in FIX.get(nome, []))
    props = {p["ID_PROPOSTA"]: (4, p["IDENTIF_PROPONENTE"]) for p in FIX["_propostas"]}
    c = ta.coleta(props, {"4313102": 4}, ler=ler)
    assert "processo_execucao" in c.chaves_mantidas
    assert "processo_execucao" not in c.arvores["1531858"]      # o `||` guarda a anterior


# ---------------------------------------------------------------------------
# Os leitores preferem o dump
# ---------------------------------------------------------------------------
def test_preferencia_dump_depois_raspagem():
    raspada = [{"numero": "9", "aceite": "Aceito"}]
    assert processo_execucao_preferido([], 0, raspada, 1) == ([], 0, "dump")
    assert processo_execucao_preferido(None, None, raspada, 1) == (raspada, 1, "portal")
    assert processo_execucao_preferido(None, None, None, None) == (None, None, None)
    # Contagem raspada sem lista (coletas antigas gravavam só o número).
    assert processo_execucao_preferido(None, None, None, 0) == (None, 0, "portal")


def test_rm_tela_e_ia_usam_as_funcoes_comuns():
    rm = (BACKEND / "services" / "rm_builder.py").read_text(encoding="utf-8")
    assert "processo_execucao_preferido(row[33], row[34], row[21], row[16])" in rm
    assert "_licitacao_aceita(_pe_lista)" in rm and "_lic_em_elaboracao(_pe_lista)" in rm
    assert "_licitacao_aceita(row[21])" not in rm
    rota = (BACKEND / "routers" / "transferegov.py").read_text(encoding="utf-8")
    assert "notas_empenho_preferidas(row[40], row[33])" in rota
    assert "jsonb_typeof(arvore->'processo_execucao') = 'array'" in rota
    ia = (BACKEND / "routers" / "ai.py").read_text(encoding="utf-8")
    assert "notas_empenho_preferidas(row[15], row[16])" in ia


# ---------------------------------------------------------------------------
# As chaves da raspagem
# ---------------------------------------------------------------------------
def test_as_chaves_separam_opsobs_de_obras_e_licitacao_e_reserva():
    src = (BACKEND / "ingestion" / "transferegov_voluntarias.py").read_text(encoding="utf-8")
    # Licitação pela tela: só com TG_PROC_EXEC=1 (padrão desligado).
    assert 'os.getenv("TG_PROC_EXEC", "0")' in src
    assert '_idp and _proc_exec_on and "normal" in _sit.lower()' in src
    # OPs/OBs e obras em chaves separadas; sem TG_OBRAS, vale TG_OPS_OBS (o antigo).
    assert "if _ops_obs_on:" in src and "if _obras_on:" in src
    assert 'os.getenv("TG_OBRAS")' in src
    assert "else _ops_obs_on" in src
