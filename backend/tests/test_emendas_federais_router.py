"""
O router de emendas federais — as guardas que só a chamada real pegaria.

⚠️ ESTE ARQUIVO NASCEU DE UM 500 EM PRODUÇÃO. O `_SQL_ITENS` tem 25 colunas
(índices 0..24) e o Python lia `x[25]`, além de ler `x[23]` e `x[24]` no lugar de
`x[22]` e `x[23]`. Resultado: **IndexError em todo município com carteira** — a
tela nunca tinha sido aberta com dado —, e os dois vizinhos liam o campo errado
em silêncio (`execucao_consultada` lia `achou_agregado`, `encontrada` lia a
contagem de documentos).

Nada disso aparece em revisão de código nem em teste de unidade: o repo não tem
Postgres de teste, e o defeito só existe na fronteira entre o TEXTO do SQL e a
INDEXAÇÃO POSICIONAL em Python. É essa fronteira que este arquivo guarda.

Rodar:
    python -m pytest backend/tests/test_emendas_federais_router.py -v
"""
import re
from pathlib import Path

import pytest

_FONTE = (Path(__file__).resolve().parents[1] / "routers"
          / "emendas_federais.py").read_text(encoding="utf-8")


def _colunas_do_select() -> list:
    """As colunas do `_SQL_ITENS`, contadas no nível 0 de parênteses.

    Contar ingenuamente por vírgula quebraria em `coalesce(a, 0)` e em
    `array_agg(DISTINCT nullif(x, ''))` — que é exatamente onde o SELECT desta
    consulta vive."""
    sql = _FONTE.split('_SQL_ITENS = """', 1)[1].split('"""', 1)[0]
    sel = sql.split("SELECT", 1)[1].split("FROM emendas_federais_carteira", 1)[0]
    cols, prof, buf = [], 0, ""
    for ch in sel:
        if ch == "(":
            prof += 1
        elif ch == ")":
            prof -= 1
        if ch == "," and prof == 0:
            cols.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        cols.append(buf.strip())
    return cols


def _indices_usados() -> set:
    """`x[N]` no CÓDIGO, ignorando comentário — o comentário do conserto cita
    `x[25]` de propósito, para registrar o que estourou."""
    linhas = [l for l in _FONTE.splitlines() if not l.strip().startswith("#")]
    return {int(m) for m in re.findall(r"x\[(\d+)\]", "\n".join(linhas))}


def _codigo_sem_comentario() -> str:
    return "\n".join(l for l in _FONTE.splitlines()
                     if not l.strip().startswith("#"))


def test_nenhum_indice_passa_do_fim_do_select():
    """⚠️ O DEFEITO EXATO QUE DERRUBOU A TELA: `x[25]` num SELECT de 25 colunas.

    IndexError não é degradação — é 500 na cara do gestor, em todo município que
    tenha uma linha de carteira."""
    cols = _colunas_do_select()
    usados = _indices_usados()
    assert usados, "nenhum x[N] encontrado — a leitura posicional mudou de forma"
    assert max(usados) < len(cols), (
        f"x[{max(usados)}] nao existe: o SELECT tem {len(cols)} colunas "
        f"(0..{len(cols) - 1})")


@pytest.mark.parametrize("indice,trecho", [
    (11, "valor_indicado"),
    (12, "propostas"),
    (13, "valor_empenhado"),
    (18, "valor_resto_pago"),
    (22, "consultado_em"),
    (23, "achou_agregado"),
    (24, "n_documentos"),
])
def test_cada_indice_aponta_para_a_coluna_que_o_codigo_pensa(indice, trecho):
    """⚠️ ESTE É O TESTE QUE IMPORTA, e o `x[25]` foi só o sintoma barulhento.

    Os índices vizinhos estavam deslocados por um e liam campo errado **sem erro
    nenhum**: `execucao_consultada` lia `achou_agregado` (nunca None, então toda
    emenda parecia consultada) e `encontrada` lia a contagem de documentos
    (número, não booleano — «Sem registro na CGU» nunca apareceria).

    Deslocamento silencioso é pior que IndexError: o 500 alguém vê."""
    cols = _colunas_do_select()
    assert trecho in cols[indice], (
        f"x[{indice}] deveria conter «{trecho}», mas a coluna e «{cols[indice]}»")


def test_o_agregado_da_cgu_nao_entra_em_nenhuma_soma_do_router():
    """⚠️⚠️ R$ 4.051.927.813,24 — o total que a tela mostrava para Nova Palma,
    município de 5.676 habitantes cuja carteira é de R$ 13,68 milhões.

    O agregado da CGU é da emenda INTEIRA, nacional. A fonte não publica «quanto
    desta emenda foi pago a este município», e somá-lo por emenda inventa um
    número grande, plausível e conferível por qualquer um.

    O schema já impedia o `SUM(...) GROUP BY municipio_id` (a tabela do agregado
    não tem `municipio_id`). Não bastou: a soma foi escrita em Python,
    contornando a própria guarda. Esta trava o outro lado."""
    codigo = _codigo_sem_comentario()
    for campo in ("valor_empenhado", "valor_liquidado", "valor_pago",
                  "valor_resto_inscrito", "valor_resto_pago",
                  "valor_resto_cancelado"):
        assert f'+= e["{campo}"]' not in codigo, (
            f"{campo} e NACIONAL e voltou a ser somado")
    # `valor_indicado` PODE somar: vem do dump e e a fatia DESTE municipio.
    assert 'tot["indicado"] += e["valor_indicado"]' in codigo


def test_o_valor_do_dump_nao_e_multiplicado_pelo_join_com_a_cgu():
    """⚠️ MEDIDO EM PRODUÇÃO, 06/09/2026: a CGU devolve MAIS DE UMA LINHA por
    código. O código `202341160001` voltou com duas —

        VERA CRUZ - RS · Saúde              · R$    50.548,00
        MÚLTIPLO       · Encargos especiais · R$ 5.000.000,00

    Como `sum(c.valor_repasse_emenda)` fica no MESMO `GROUP BY` de um
    `LEFT JOIN emendas_federais_cgu`, k linhas na CGU multiplicam por k o valor
    que veio do dump — e o dinheiro do município sobe sozinho, plausível, sem
    nada na tela denunciando.

    Hoje nenhum código DA CARTEIRA tem duas linhas (medido: zero nos dois
    municípios), então o defeito está latente. A agregação prévia é correta nos
    dois mundos: se k for sempre 1 não muda número nenhum, e se não for, é a
    diferença entre o total certo e um total maior."""
    sql = _FONTE.split('_SQL_ITENS = """', 1)[1].split('"""', 1)[0]
    tem_lateral = "LEFT JOIN LATERAL" in sql.upper()
    tem_cte = re.search(r"WITH\s+\w+\s+AS\s*\(", sql, re.I) is not None
    assert tem_lateral or tem_cte, (
        "o agregado da CGU precisa ser reduzido a UMA linha por codigo ANTES do "
        "join (LATERAL ou CTE); um LEFT JOIN direto multiplica o valor do dump")


def test_fonte_ligada_vem_do_dado_e_nao_de_uma_env_do_worker():
    """⚠️⚠️ A env `PORTAL_TRANSPARENCIA_API_KEY` mora no WORKER. A API é outro
    container e outro processo — ela nunca a vê.

    Medido em 06/09/2026: Nova Palma com **64 de 67 emendas já consultadas** na
    CGU, e a tela dizendo «a chave não está configurada», escondendo toda a
    execução atrás de «—». O router estava perguntando à configuração de um
    processo que ele não enxerga, em vez de perguntar ao dado que ele tem na
    frente."""
    codigo = _codigo_sem_comentario()
    assert "PORTAL_TRANSPARENCIA_API_KEY" not in codigo, (
        "o router voltou a ler uma env que vive no worker")
    assert "chave_ok = consultadas > 0" in codigo
