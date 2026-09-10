"""As colunas que o dado aberto sempre trouxe e o coletor nunca leu.

Primeira etapa da migracao para o ambiente `api-publica`. Nao ha endereco novo
nem chamada nova: `siconv_proposta` tem 36 colunas e `siconv_convenio` tem 40, e
o coletor lia cerca de vinte. Banco, agencia e conta eram raspados da TELA
LOGADA; saldo de conta e prazo de prestacao de contas do federal nao existiam em
lugar nenhum do produto.
"""
import os
import re

import pytest

from ingestion.transferegov_opendata import (_CAMPOS, _PRESERVA, _SO_PREENCHE,
                                             _SOBRESCREVE, _SOBRESCREVE_NOVAS)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLETOR = os.path.join(RAIZ, "ingestion", "transferegov_opendata.py")
# ⚠️ LISTA, e nao um arquivo so. As colunas de fonte unica chegaram em DUAS
# levas — as catorze de 31/08/2026 e as duas da clausula suspensiva de
# 09/09/2026 — e coluna nova NAO entra numa migration ja aplicada nos seis
# bancos: entra numa nova. Fixar um unico arquivo aqui obrigaria a proxima leva
# a escolher entre reescrever migration antiga (errado) e afrouxar o teste.
MIGRATIONS = [
    os.path.join(RAIZ, "migrations", "add_voluntarias_colunas_do_csv.sql"),
    os.path.join(RAIZ, "migrations", "add_clausula_suspensiva_retirada_dias.sql"),
]

NOVAS = ["banco", "agencia", "conta_corrente", "situacao_conta",
         "situacao_projeto_basico", "enviada_mandataria", "valor_empenhado",
         "valor_desembolsado", "saldo_conta", "dt_limite_prest_contas",
         "dt_fim_vigencia_original", "qtd_termos_aditivos", "qtd_prorrogas",
         "opera_obtv",
         # As duas da clausula suspensiva (09/09/2026). Mesma natureza das
         # catorze acima — so o dado aberto escreve nelas, e o valor MUDA (a
         # clausula e retirada um dia), entao sobrescrevem em vez de COALESCE.
         # Entrar aqui nao e formalidade: sao estes tres testes que garantem que
         # a coluna chegou a `_CAMPOS`, a lista do INSERT E ao VALUES — os tres
         # lugares que, tocados pela metade, gravam NULL em silencio.
         "clausula_suspensiva_dt_retirada", "clausula_suspensiva_dias"]


def _fonte():
    return open(COLETOR, encoding="utf-8").read()


def _codigo(caminho, marca="#"):
    return "\n".join(l for l in open(caminho, encoding="utf-8").read().splitlines()
                     if not l.lstrip().startswith(marca))


def _sql_das_migrations():
    return "\n".join(_codigo(m, "--") for m in MIGRATIONS)


def test_toda_coluna_nova_existe_em_alguma_migration():
    sql = _sql_das_migrations()
    for c in NOVAS:
        assert re.search(rf"ADD COLUMN IF NOT EXISTS\s+{c}\b", sql), (
            f"{c} esta em NOVAS mas nenhuma migration de MIGRATIONS a cria — "
            "o upsert vai falhar no boot do primeiro tenant"
        )


def test_as_migrations_sao_puramente_aditivas():
    """⚠️ Um repo, SEIS tenants: um ALTER que nao seja aditivo derruba os seis
    de uma vez. Nada de DROP, nada de NOT NULL, nada de DEFAULT.

    ⚠️ O `NOT NULL` proibido e o da DECLARACAO da coluna, e por isso a busca e
    linha a linha nas linhas de ADD COLUMN. Procurar a expressao no arquivo
    inteiro reprovava o `WHERE ... IS NOT NULL` do indice parcial, que e
    justamente o que se quer ali."""
    total_colunas = 0
    for caminho in MIGRATIONS:
        sql = _codigo(caminho, "--")
        nome = os.path.basename(caminho)
        assert "DROP" not in sql.upper(), nome
        assert "DEFAULT" not in sql.upper(), \
            f"{nome}: DEFAULT 0 afirmaria 'nao ha aditivo' sobre linha nunca coletada"
        colunas = [l for l in sql.splitlines() if "ADD COLUMN" in l.upper()]
        for l in colunas:
            assert "NOT NULL" not in l.upper(), \
                f"{nome}: coluna declarada NOT NULL: {l.strip()}"
        total_colunas += len(colunas)

    # ⚠️ A soma, e nao a contagem por arquivo: e ela que pega o caso de alguem
    # por a coluna em NOVAS, escrever a migration e esquecer o `ADD COLUMN` de
    # uma delas — o teste acima acha a que existe e cala sobre a que falta.
    assert total_colunas == len(NOVAS), \
        f"{total_colunas} linhas de ADD COLUMN somadas para {len(NOVAS)} colunas em NOVAS"


def test_as_migrations_estao_na_lista_do_boot():
    """Migration fora da MIGRATION_FILES nao roda: a coluna nunca nasce e o
    upsert quebra no primeiro boot que tentar grava-la."""
    from services.startup import MIGRATION_FILES
    for caminho in MIGRATIONS:
        nome = os.path.basename(caminho)
        assert nome in MIGRATION_FILES, f"{nome} fora da MIGRATION_FILES"


def test_o_sql_das_migrations_e_valido_para_o_postgres():
    pglast = pytest.importorskip("pglast", reason="pglast ausente — checagem PULADA")
    for caminho in MIGRATIONS:
        pglast.parse_sql(open(caminho, encoding="utf-8").read())


def test_toda_coluna_nova_chega_ao_INSERT_e_ao_dicionario():
    """⚠️ Sao DOIS lugares. `_CAMPOS` monta o dicionario de parametros e o
    INSERT nomeia as colunas; tocar so um deixa o campo sem valor e NADA acusa —
    o upsert grava NULL em silencio.

    ⚠️ A fatia comeca no INSERT e termina no PRIMEIRO `ON CONFLICT` DEPOIS
    dele. Sem o offset, `index("ON CONFLICT")` casava com um COMENTARIO la na
    linha 121 — antes do INSERT — e a fatia saia VAZIA. Um `for` sobre lista
    vazia nao acusa nada; aqui so quebrou porque NOVAS tem 14 itens. Dai o
    `assert insert` logo abaixo: e ele que garante que o teste esta olhando
    para alguma coisa."""
    src = _fonte()
    ini = src.index("INSERT INTO transferegov_propostas")
    insert = src[ini:src.index("ON CONFLICT", ini)]
    assert insert.count("%(") > len(NOVAS), \
        "a fatia do INSERT saiu curta demais — o teste nao esta lendo o INSERT"
    for c in NOVAS:
        assert c in _CAMPOS, f"{c} fora de _CAMPOS"
        assert re.search(rf"\b{c}\b", insert), f"{c} fora da lista de colunas do INSERT"
        assert f"%({c})s" in insert, f"{c} sem placeholder no VALUES"


def test_as_novas_sobrescrevem_por_serem_FONTE_UNICA():
    """Nenhum outro coletor escreve nestas colunas, entao nao ha valor de outra
    origem a preservar. E saldo e empenho MUDAM: um COALESCE cego congelaria o
    numero do dia em que a coluna nasceu."""
    assert set(_SOBRESCREVE_NOVAS) == set(NOVAS)
    src = _fonte()
    assert 'f"{c}=EXCLUDED.{c}" for c in _SOBRESCREVE_NOVAS' in src


def test_nenhuma_coluna_ficou_em_duas_listas():
    """Dois SET para a mesma coluna no mesmo UPDATE fazem o Postgres recusar a
    instrucao inteira."""
    todas = list(_SOBRESCREVE) + list(_SO_PREENCHE) + list(_PRESERVA) + list(_SOBRESCREVE_NOVAS)
    dup = [c for c in set(todas) if todas.count(c) > 1]
    assert not dup, f"coluna repetida entre as listas: {dup}"


# --- a vigencia: a mudanca de precedencia ------------------------------------

def test_a_vigencia_do_convenio_nao_sobrepoe_mais_a_da_proposta():
    """⚠️ ESTE E O CONSERTO NA ORIGEM da briga que custou o #328.

    O bloco fazia `dt_fim_vigencia = DIA_FIM_VIGENC_CONV`, e era dai que saia o
    16/12/2024 da 932836 — a data que o #317 usou para concluir, por engano, que
    a vigencia dela tinha vencido.

    Medido nos 1.519 convenios celebrados do tenant: 1.517 tem as duas vigencias
    IGUAIS; discordam em DUAS (932836 e 936202), e nas duas o registro do
    convenio esta parado sem TA nem prorroga enquanto a proposta e a TELA ja
    avancaram. Preferir a proposta muda duas linhas, as duas para o valor que a
    tela confirma."""
    src = _codigo(COLETOR)
    assert 'if not p.get("dt_fim_vigencia"):' in src, \
        "a vigencia do convenio voltou a sobrescrever a da proposta"
    assert 'if not p.get("dt_inicio_vigencia"):' in src


def test_a_vigencia_original_do_convenio_nao_se_perde():
    """Ela vai para coluna propria — e o que faz as duas caberem lado a lado em
    vez de disputarem o mesmo campo."""
    src = _codigo(COLETOR)
    assert 'p["dt_fim_vigencia_original"] = _data(linha.get("DIA_FIM_VIGENC_ORIGINAL_CONV"))' in src


def test_qtd_vazia_vira_None_e_nao_zero():
    """O CSV deixa QTD_TA em branco quando nao ha registro. Gravar 0 afirmaria
    'nenhum aditivo' sobre linha que o portal simplesmente nao preencheu."""
    def regra(s):
        s = (s or "").strip()
        return int(s) if s.isdigit() else None
    assert regra("") is None
    assert regra(None) is None
    assert regra("0") == 0
    assert regra("3") == 3
    assert regra("-") is None


def test_o_campo_que_vinha_COLADO_na_modalidade_ganhou_coluna():
    """"Enviada para mandatária?" era a celula seguinte, que o extrator da tela
    trazia grudada na modalidade em 27 de 83 propostas de Araujos. No CSV ela e
    uma coluna."""
    assert "enviada_mandataria" in NOVAS
    assert 'linha.get("ENVIADA_MANDATARIA")' in _fonte()
