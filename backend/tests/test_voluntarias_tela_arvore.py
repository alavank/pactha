"""Voluntárias: a tela e o RM leem a árvore dos dumps (15/09/2026).

O que se prova:
- o desembolso do dump manda, completado com a raspagem só onde a OB bate, sem
  somar as duas listas;
- os selos da lista só afirmam com prova (convênio EM EXECUÇÃO, prazo de
  prestação só quando ela não foi entregue) e são contados HOJE;
- CPF de pessoa física não sai para o navegador;
- a rota paginada devolve SÓ o resumo de quem não é da prefeitura (opção B).
"""
import asyncio
from datetime import date

import pytest

from services.voluntarias_dump import (
    dias_desde, ops_obs_preferido, sem_cpf, sinais_do_resumo)

HOJE = date(2026, 9, 15)


# ---------------------------------------------------------------------------
# O desembolso: dump primeiro
# ---------------------------------------------------------------------------
DUMP = {"valor_total_repasse": 238750.0, "valor_desembolsado": 213220.28,
        "valor_a_desembolsar": 25529.72, "data_ultimo_desembolso": "27/12/2022",
        "faixa_sem_desembolso": 365,
        "obs": [{"numero_ob": "2022OB800444", "valor": 213220.28, "data_emissao_ob": "27/12/2022"}]}
RASPADO = {"valor_desembolsado": 213220.28,
           "obs": [{"numero_ob": "2022OB800444", "numero_ns": "2022NS001", "numero_op": "2022OP9",
                    "situacao": "Efetuada", "valor": 213220.28},
                   {"numero_ob": "", "numero_op": "2023OP1", "situacao": "Aguardando", "valor": 999.0}]}


def test_o_dump_manda_e_a_raspagem_completa_so_onde_a_ob_bate():
    ops, fonte = ops_obs_preferido(DUMP, RASPADO)
    assert fonte == "dump"
    assert ops["valor_desembolsado"] == 213220.28
    assert len(ops["obs"]) == 1                          # a OP pendente NÃO entra
    ob = ops["obs"][0]
    assert (ob["numero_ns"], ob["numero_op"], ob["situacao"]) == ("2022NS001", "2022OP9", "Efetuada")
    assert "numero_ns" not in DUMP["obs"][0], "não pode alterar o bloco original"


def test_sem_dump_volta_a_raspagem_e_sem_nada_e_nada():
    assert ops_obs_preferido(None, RASPADO) == (RASPADO, "portal")
    assert ops_obs_preferido('{"obs": []}', None)[1] == "dump"   # JSONB como texto
    assert ops_obs_preferido(None, None) == (None, None)


def test_o_rm_le_o_mesmo_bloco_que_a_tela():
    from services import rm_builder
    assert rm_builder.ops_obs_preferido is ops_obs_preferido
    src = open(rm_builder.__file__, encoding="utf-8").read()
    assert "_desembolso_ops_obs(_ops_vol)" in src and "_ano_pagamento_ops_obs(_ops_vol)" in src
    assert "_desembolso_ops_obs(row[22])" not in src


# ---------------------------------------------------------------------------
# Os selos da lista
# ---------------------------------------------------------------------------
def _resumo(**kw):
    base = {"tem_convenio": True, "situacao_convenio": "Em execução",
            "vigencia_original": "30/08/2022", "vigencia_atual": "26/03/2024",
            "a_desembolsar": 25529.72, "ultimo_desembolso": "27/12/2022",
            "assinatura": "01/06/2020", "prestacao_contas_limite": "25/05/2024",
            "execucao_fisica_pct": 45.0}
    base.update(kw)
    return base


def test_selos_de_um_convenio_em_execucao():
    s = sinais_do_resumo(_resumo(), HOJE)
    assert s["prorrogada"] is True
    assert s["dias_sem_desembolso"] == (HOJE - date(2022, 12, 27)).days
    assert s["pc_dias"] == (date(2024, 5, 25) - HOJE).days < 0     # vencida
    assert s["execucao_fisica_pct"] == 45.0


def test_prestacao_entregue_nao_vira_prazo_vencido():
    """"Prestação de Contas em Análise" já mostra que ela foi enviada: o prazo
    passado não é mais pendência da prefeitura."""
    for sit in ("Prestação de Contas em Análise", "Prestação de Contas Aprovada",
                "Prestação de Contas Concluída"):
        s = sinais_do_resumo(_resumo(situacao_convenio=sit), HOJE)
        assert s["pc_dias"] is None and s["dias_sem_desembolso"] is None
    assert sinais_do_resumo(_resumo(situacao_convenio="Aguardando Prestação de Contas"),
                            HOJE)["pc_dias"] is not None


def test_sem_saldo_a_desembolsar_nao_ha_selo_de_desembolso():
    assert sinais_do_resumo(_resumo(a_desembolsar=0.0), HOJE)["dias_sem_desembolso"] is None


def test_nunca_desembolsou_conta_da_assinatura():
    s = sinais_do_resumo(_resumo(ultimo_desembolso=None), HOJE)
    assert s["nunca_desembolsou"] is True
    assert s["dias_sem_desembolso"] == (HOJE - date(2020, 6, 1)).days


def test_sem_convenio_ou_sem_arvore_nao_ha_selo():
    assert sinais_do_resumo(None) is None
    assert sinais_do_resumo({"tem_convenio": False}) is None


def test_vigencia_igual_nao_e_prorrogada():
    assert sinais_do_resumo(_resumo(vigencia_atual="30/08/2022"), HOJE)["prorrogada"] is False


def test_dias_sao_contados_hoje_e_nao_na_coleta():
    """Gravar a conta na coleta faria a árvore mudar todo dia sem a fonte mudar
    — e o selo envelheceria até a próxima rodada."""
    assert dias_desde("14/09/2026", HOJE) == 1
    assert dias_desde("lixo", HOJE) is None


# ---------------------------------------------------------------------------
# CPF não sai
# ---------------------------------------------------------------------------
def test_cpf_de_pessoa_fisica_nao_sai_para_a_tela():
    arv = {"emendas": [{"NR_EMENDA": "1", "apoiadores": [
        {"NOME_PF_SOLICITANTE_APOIADORES_EMENDAS": "Fulano",
         "CPF_PF_SOLICITANTE_APOIADORES_EMENDAS": "12345678900"}]}],
        "cipi": {"execucao_fisica": [{"cpf_responsavel_operacao": "x", "percentual_execucao": "50"}]}}
    limpo = sem_cpf(arv)
    ap = limpo["emendas"][0]["apoiadores"][0]
    assert ap == {"NOME_PF_SOLICITANTE_APOIADORES_EMENDAS": "Fulano"}
    assert limpo["cipi"]["execucao_fisica"][0] == {"percentual_execucao": "50"}


def test_a_fixture_real_nao_tem_cpf_depois_do_filtro():
    import json
    from pathlib import Path
    fix = json.loads((Path(__file__).parent / "fixtures" / "tg_arvore_dumps.json")
                     .read_text(encoding="utf-8"))
    from ingestion import transferegov_arvore as ta

    def ler(nome):
        yield from (dict(x) for x in fix.get(nome, []))
    props = {p["ID_PROPOSTA"]: (4, p["IDENTIF_PROPONENTE"]) for p in fix["_propostas"]}
    c = ta.coleta(props, {"4313102": 4}, ler=ler)
    assert "cpf" not in json.dumps(sem_cpf(c.arvores), ensure_ascii=False).lower()


# ---------------------------------------------------------------------------
# A rota paginada
# ---------------------------------------------------------------------------
class _Res:
    def __init__(self, linhas):
        self._l = linhas

    def first(self):
        return self._l[0] if self._l else None

    def fetchall(self):
        return self._l


class _Db:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.sql = []

    async def execute(self, stmt, params=None):
        self.sql.append((str(stmt), params))
        return _Res(self.respostas.pop(0))


class _Usuario:
    id = 1
    email = "a@b.c"
    allowed_telas = None
    allowed_municipio_ids = None
    role = "admin"
    super_admin = True


def _lista(db, **kw):
    from routers import transferegov as tg
    args = dict(tipo="pagamentos", numero_proposta="059522/2021", municipio_id=4, offset=0,
                limit=50, busca=None, db=db, current=_Usuario())
    args.update(kw)
    return asyncio.run(tg.voluntarias_arvore_lista(**args))


@pytest.fixture
def _sem_gate(monkeypatch):
    from routers import transferegov as tg
    monkeypatch.setattr(tg, "ensure_municipio_access", lambda *a, **k: None)
    monkeypatch.setattr(tg.authz, "pode", lambda *a, **k: True)


def test_quem_nao_e_prefeitura_recebe_so_o_resumo(_sem_gate):
    db = _Db([[("1531858", False, {"so_resumo": True, "n_pagamentos": 12868,
                                   "pago_fornecedores": 1.5e9})]])
    r = _lista(db)
    assert r["so_resumo"] is True and r["items"] == []
    assert r["resumo"]["n_pagamentos"] == 12868
    assert len(db.sql) == 1, "não pode consultar a tabela de pagamentos"


def test_a_prefeitura_recebe_a_pagina_ordenada_pela_data(_sem_gate):
    linha = ("M1", "27/12/2022", "88488358000156", "EMPRESA X", "Pagamento", 42000, "12", "NF 12", [])
    db = _Db([[("1531858", True, {"n_pagamentos": 1})], [(1, 42000)], [linha]])
    r = _lista(db, busca="empresa")
    assert r["total"] == 1 and r["soma"] == 42000.0
    assert r["items"][0]["fornecedor_nome"] == "EMPRESA X" and r["items"][0]["nr_dl"] == "12"
    sql_pagina, params = db.sql[2]
    assert "to_date(left(data_pagamento, 10), 'DD/MM/YYYY') END DESC NULLS LAST" in sql_pagina
    assert params["idp"] == "1531858" and params["b"] == "%empresa%"


def test_tipo_desconhecido_e_404(_sem_gate):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        _lista(_Db([]), tipo="qualquer")
    assert e.value.status_code == 404
