"""Banco, agência e conta do convênio ESTADUAL, lidos da seção "Conta Específica".

⚠️ POR QUE EXISTE. `convenios_estadual` tem as colunas `banco`, `agencia`,
`conta_corrente`, `saldo_bancario` e `dt_saldo` desde sempre — marcadas no modelo
como "Campos do Relatorio de Monitoramento (RM)" — e NENHUM coletor as escrevia.
O RM já desenha as quatro linhas (`rm_builder.py:1669` lê `c.banco`, a COLUNA, não
`raw_data`); elas saíam vazias porque ninguém produzia o dado. O dono cobrou em
03/09/2026 e gravou um vídeo mostrando onde ele mora no SIGCON.

⚠️ A SONDA VEIO ANTES DO PARSER, e isso mudou o resultado. Rodando o diagnóstico
do próprio scraper em produção, o accordion do convênio expõe 25 seções e a nossa
aparece como `'Conta Específica\xa0 '` — com espaço NÃO-QUEBRÁVEL no fim. Casar
por igualdade, ou com espaço comum, não acha nada e falha CALADO. Escrever o
parser a partir do vídeo teria caído exatamente nisso.
"""
import re
from pathlib import Path

import pytest

pytest.importorskip("psycopg2")

from ingestion.sigcon_scraper import ler_conta_especifica as L  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
SCRAPER = RAIZ / "ingestion" / "sigcon_scraper.py"

# O texto que `_PC_TEXTO_FN` produz: rótulo, dois-pontos, valor, um por linha.
# O Banco é um <select> — o JS já rende `selectedOptions[0].text`, por isso
# "BRASIL" aparece como texto.
PAINEL = """Conta Específica
Banco: BRASIL
Agência: 1060
DV da Agência: 0
Praça bancária: BELO HORIZONTE
Conta Corrente: 5724440080
DV da Conta: 1
"""


def test_le_os_tres_campos():
    r = L(PAINEL)
    assert r == {"banco": "BRASIL", "agencia": "1060", "conta_corrente": "5724440080"}


def test_o_DV_nao_rouba_o_rotulo_da_agencia():
    """⚠️ A ARMADILHA CENTRAL DESTE PARSER.

    Dentro de "DV da Agência" existe a palavra "Agência". O desempate é "quem
    começa antes ganha" — e "DV da Agência" só começa antes se o rótulo do DV
    EXISTIR na lista. Sem ele, o convênio do vídeo gravaria `agencia="0"` (o
    dígito verificador) em vez de 1060, e ninguém perceberia: 0 é um valor
    plausível numa coluna de texto.
    """
    r = L(PAINEL)
    assert r["agencia"] == "1060", "o DV foi lido como se fosse a agência"
    assert r["conta_corrente"] == "5724440080", "o DV da conta virou a conta"
    # E os campos de ocupação não vazam para o retorno.
    assert not any(k.startswith("_") for k in r)


def test_ausencia_devolve_None_e_nao_string_vazia():
    """Chave ausente é "não veio". O upsert faz COALESCE: gravar "" apagaria o
    valor que a rodada anterior conseguiu ler."""
    assert L(None) is None
    assert L("") is None
    assert L("Conta Específica  \n") is None          # seção aberta e vazia
    assert L("Banco:\nAgência:\n") is None                  # rótulos sem valor


def test_recusa_CPF_e_CNPJ():
    """⚠️ NÃO É ZELO EXCESSIVO: na Prestação de Contas, uma regra frouxa gravou
    `030.725.676-62` — um CPF — no campo do nº SEI. Dado pessoal indo para a tela
    e para um documento entregue ao município. Estes campos ficam ao lado de CPF
    e CNPJ no mesmo formulário."""
    assert L("Conta Corrente: 030.725.676-62") is None
    assert L("Agência: 18.300.996/0001-16") is None
    assert L("Banco: 030.725.676-62") is None


def test_recusa_placeholder_do_dropdown():
    assert L("Banco: Selecione") is None
    assert L("Banco: -") is None


def test_aceita_banco_com_codigo_e_nome():
    r = L("Banco: 001 - Banco do Brasil S.A.\nAgência: 1060-0\nConta Corrente: 5724440080\n")
    assert r["banco"] == "001 - Banco do Brasil S.A."
    assert r["agencia"] == "1060-0"


def test_o_alvo_do_JS_e_trocado_de_verdade():
    """⚠️ O `assert` do `_troca_alvo` é o que impede o pior desfecho silencioso.

    O JS da Conta Específica é o MESMO da Prestação de Contas com o cabeçalho
    trocado — reaproveitado porque aquele carrega correções caras (o `SELECT` que
    rende o texto da opção, sem o qual o "BRASIL" não apareceria; a queda do
    painel para o corpo; accordion E aba). Se alguém reescrever a grafia do alvo
    lá em cima, a troca vira no-op e o coletor passa a ler o painel ERRADO,
    gravando banco/agência a partir da Prestação de Contas.
    """
    from ingestion import sigcon_scraper as S
    assert "conta" in S._CE_JS and "espec" in S._CE_JS
    assert "presta" not in S._CE_JS, "o alvo não foi trocado — lendo o painel errado"
    assert "presta" not in S._CE_JS_TEXTO
    with pytest.raises(AssertionError):
        S._troca_alvo("() => { const alvo=/outra coisa/i; }")


def test_o_INSERT_posicional_continua_alinhado():
    """⚠️ Colunas, `%s` e tupla têm de ter o MESMO tamanho.

    O INSERT casa por ORDEM. Uma diferença aqui não levanta erro de sintaxe:
    estoura em produção, no meio da rodada, e o SAVEPOINT por registro engole a
    falha — a rodada termina "com sucesso" tendo gravado menos.
    """
    s = SCRAPER.read_text(encoding="utf-8")
    i = s.index("INSERT INTO convenios_estadual")
    bloco = s[i:i + 1600]
    cols_txt = bloco[bloco.index("(") + 1:bloco.index(") VALUES")]
    # ⚠️ TIRA COMENTÁRIO ANTES DE DIVIDIR: comentário com vírgula vira coluna
    # fantasma se a ordem for invertida (aconteceu na 1ª versão deste teste).
    cols_txt = "\n".join(l for l in cols_txt.splitlines() if not l.strip().startswith("--"))
    cols = [c.strip() for c in cols_txt.split(",") if c.strip()]
    vals = bloco[bloco.index(") VALUES") + 8:]
    n_ph = vals[:vals.index(")")].count("%s")
    assert len(cols) == n_ph, f"{len(cols)} colunas para {n_ph} placeholders"

    j = s.index('RETURNING (xmax = 0) AS is_insert')
    ini = s.index('""", (', j) + len('""", (')
    d, itens, k = 0, 1, ini
    while k < len(s):
        c = s[k]
        if c == "#":
            k = s.index("\n", k); continue
        if c in "([{":
            d += 1
        elif c in ")]}":
            if d == 0:
                break
            d -= 1
        elif c == "," and d == 0:
            itens += 1
        k += 1
    if s[k - 40:k].rstrip().rstrip(")").rstrip().endswith(","):
        itens -= 1
    assert itens == n_ph, f"{itens} valores na tupla para {n_ph} placeholders"
    for c in ("banco", "agencia", "conta_corrente"):
        assert c in cols, f"{c} saiu do INSERT"


def test_o_conflito_PRESERVA_o_que_ja_foi_coletado():
    """⚠️ COALESCE, e não `EXCLUDED` cru.

    A Conta Específica é a QUARTA e última das leituras extras, e a primeira a
    cair quando o orçamento da rodada acaba. Com sobrescrita crua, toda rodada
    que não chegasse até ela APAGARIA o banco e a agência já coletados —
    `NULL` significa "não veio nesta rodada", nunca "o convênio não tem conta".
    """
    s = SCRAPER.read_text(encoding="utf-8")
    for c in ("banco", "agencia", "conta_corrente"):
        assert re.search(rf"{c} = COALESCE\(EXCLUDED\.{c}, convenios_estadual\.{c}\)", s), (
            f"{c} deixou de ser preservado no ON CONFLICT")


def test_o_RM_le_a_COLUNA_e_nao_o_raw_data():
    """Se o RM lesse `raw_data`, bastaria o `data.update()`; como ele lê a coluna
    (`c.banco`), o INSERT tinha de ganhar os três campos. Este teste trava a
    premissa — se o RM mudar de fonte, o coletor precisa acompanhar."""
    rm = (RAIZ / "services" / "rm_builder.py").read_text(encoding="utf-8")
    assert '"banco": c.banco or ""' in rm, (
        "o RM mudou de fonte para banco/agência/conta; o INSERT do sigcon_scraper "
        "precisa acompanhar")
