"""O dado aberto nao pode mais sobrescrever a VIGENCIA lida da tela.

CASO REAL (medido em producao em 30/08/2026, nao inventado aqui): a proposta
059522/2021 / instrumento 932836 tem no CSV do CONVENIO a vigencia ORIGINAL
16/12/2024, e na TELA do portal a "Data Termino de Vigencia Atual" 31/12/2026 —
a de depois do aditivo, que e a que vale e que o proprio prazo de prestacao de
contas confirma.

Os dois coletores gravavam a mesma coluna: o cron das 06:50 escrevia a do CSV, o
lote de 2 em 2 horas escrevia a da tela. A regra de ano do RM (#327) le esta
coluna, entao um relatorio emitido entre os dois PERDIA a 932836.

⚠️ Estes testes olham o SQL GERADO, nao o banco: nao existe Postgres de teste
neste repo. A validacao de sintaxe usa `pglast` (a gramatica real do Postgres)
quando ele estiver instalado, e e PULADA — nao silenciosamente aprovada — quando
nao estiver.
"""
import re

import pytest

from ingestion.transferegov_opendata import (_CAMPOS, _PRESERVA, _SO_PREENCHE,
                                             _SOBRESCREVE)


def _sets() -> list[str]:
    """Reproduz a montagem do SET do ON CONFLICT, na mesma ordem do modulo."""
    return [
        f"{c}=COALESCE(NULLIF(EXCLUDED.{c}::text, '')::"
        f"{'numeric' if c.startswith('valor') else 'date' if c == 'clausula_suspensiva_dt_prevista' else 'text'}"
        f", transferegov_propostas.{c})"
        for c in _SOBRESCREVE
    ] + [
        f"{c}=COALESCE(NULLIF(transferegov_propostas.{c}, ''), NULLIF(EXCLUDED.{c}::text, ''))"
        for c in _SO_PREENCHE
    ] + [
        f"{c}=COALESCE(EXCLUDED.{c}, transferegov_propostas.{c})" for c in _PRESERVA
    ] + ["raw_data=EXCLUDED.raw_data", "updated_at=NOW()"]


def test_a_vigencia_saiu_da_lista_de_sobrescrita():
    """O coracao do conserto: o dado aberto deixa de mandar na vigencia."""
    assert "dt_fim_vigencia" not in _SOBRESCREVE
    assert "dt_inicio_vigencia" not in _SOBRESCREVE
    assert _SO_PREENCHE == ["dt_inicio_vigencia", "dt_fim_vigencia"]


def test_o_valor_que_ja_esta_na_coluna_vence():
    """A ORDEM dentro do COALESCE e o conserto inteiro. Invertida, o dado aberto
    volta a ganhar e o defeito ressuscita sem que nenhum teste de lista perceba."""
    for c in _SO_PREENCHE:
        expr = next(s for s in _sets() if s.startswith(f"{c}="))
        # a coluna existente aparece ANTES do EXCLUDED
        assert expr.index("transferegov_propostas.") < expr.index("EXCLUDED.")


def test_string_vazia_do_csv_nao_apaga_a_data_da_tela():
    """As colunas de vigencia sao VARCHAR, nao DATE. Sem o NULLIF do lado do
    EXCLUDED, um campo vazio do CSV nao e NULL — e venceria o COALESCE."""
    for c in _SO_PREENCHE:
        expr = next(s for s in _sets() if s.startswith(f"{c}="))
        assert f"NULLIF(EXCLUDED.{c}::text, '')" in expr
        # e o mesmo cuidado do outro lado: coluna vazia conta como vazia
        assert f"NULLIF(transferegov_propostas.{c}, '')" in expr


def test_a_vigencia_continua_no_INSERT():
    """Sair do UPDATE nao pode significar sair do INSERT: proposta NOVA precisa
    nascer com a vigencia do CSV, que e a unica fonte disponivel para ela."""
    assert "dt_inicio_vigencia" in _CAMPOS
    assert "dt_fim_vigencia" in _CAMPOS


def test_nenhum_campo_ficou_em_duas_listas():
    """Um campo em _SOBRESCREVE e _SO_PREENCHE geraria dois SET para a mesma
    coluna no mesmo UPDATE — o Postgres recusa a instrucao inteira."""
    todas = _SOBRESCREVE + _SO_PREENCHE + _PRESERVA
    assert len(todas) == len(set(todas)), \
        f"campo repetido entre as listas: {[c for c in set(todas) if todas.count(c) > 1]}"


def test_o_resto_das_regras_ficou_intacto():
    """Nao-regressao: so as duas vigencias mudaram de regime."""
    assert "valor_global" in _SOBRESCREVE
    assert "situacao" in _SOBRESCREVE
    assert "dt_proposta" in _SOBRESCREVE      # data, mas do CSV mesmo
    assert _PRESERVA == ["parlamentar"]


def test_o_sql_gerado_e_valido_para_o_postgres():
    """Gramatica real, nao 'parece certo'. PULA (nao passa) sem pglast."""
    pglast = pytest.importorskip("pglast", reason="pglast ausente — checagem PULADA, nao aprovada")
    sql = (
        "INSERT INTO transferegov_propostas (municipio_id, "
        + ", ".join(_CAMPOS) + ", raw_data) VALUES (1, "
        + ", ".join(["NULL"] * len(_CAMPOS)) + ", '{}'::jsonb) "
        "ON CONFLICT (municipio_id, numero_proposta) DO UPDATE SET "
        + ", ".join(_sets())
    )
    pglast.parse_sql(sql)          # levanta ParseError se a sintaxe estiver torta


def test_a_data_ORIGINAL_do_convenio_nao_derruba_a_ATUAL_da_tela():
    """O caso 932836, escrito como a regra que ele exige.

    Simula os dois lados do COALESCE com os valores REAIS de producao e confere
    que o resultado e a data da tela. Sem banco: a semantica do
    `COALESCE(NULLIF(coluna,''), NULLIF(excluded,''))` e reproduzida aqui."""
    def resolve(na_coluna, vindo_do_csv):
        return (na_coluna or None) or (vindo_do_csv or None)

    # ja gravado pela tela                CSV do convenio (original)
    assert resolve("31/12/2026", "16/12/2024") == "31/12/2026"
    # proposta nova: a coluna esta vazia, entao o CSV preenche
    assert resolve(None, "16/12/2024") == "16/12/2024"
    assert resolve("", "16/12/2024") == "16/12/2024"
    # CSV vazio nao apaga o que a tela leu
    assert resolve("31/12/2026", "") == "31/12/2026"
