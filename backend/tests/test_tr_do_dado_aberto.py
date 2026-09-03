"""O Termo de Referência aparece pelo dado aberto quando a sessão gov.br está fria.

⚠️ POR QUE ISTO EXISTE. Em 03/09/2026 o dono relatou que o convênio 981397/2025
(Araújos/MG) não mostrava o Termo de Referência, e supôs: "essa aba do termo de
referência não abre quando está pelo acesso privado". Ele estava certo — a
auditoria do repo já tinha medido o SP `execucao` frio ("SP execucao frio" 519×,
sessão morta 298 de 720 horas em 30 dias), e `projeto_basico` NÃO tem caminho sem
sessão, enquanto a Licitação tem. Por isso uma sumia e a outra não.

⚠️ O DADO JÁ ESTAVA NO BANCO. `situacao_projeto_basico` chega no
`siconv_proposta.zip` desde 31/08 (transferegov_opendata.py:426) e, medido em
produção no freitas, estava preenchida em 2.799 de 3.200 propostas — com NENHUMA
tela lendo. Para o 981397 o valor é literalmente "Em Análise", que é a informação
que o dono disse faltar. Não era coleta, não era sessão: era dado coletado e não
exibido.

⚠️ A ARMADILHA QUE ESTE ARQUIVO GUARDA. O dict da rota lê o resultado por ÍNDICE
POSICIONAL (`row[0]`..`row[34]`). Uma coluna inserida no MEIO do SELECT desloca
todos os seguintes em silêncio — a tela passa a mostrar um campo no lugar de
outro, sem erro nenhum. Hoje mesmo esse tipo de defeito produziu um
`ProgrammingError` na tela de Agendamentos. Por isso as três últimas colunas do
SELECT são declaradamente "a última", e este teste conta.
"""
import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

RAIZ = Path(__file__).resolve().parent.parent
ROTA = RAIZ / "routers" / "transferegov.py"
TELA = (RAIZ.parent / "frontend" / "src" / "components" / "TransfereGovPropostas.tsx")


def _bloco_detalhe() -> str:
    """O SELECT da rota de DETALHE (a que alimenta o modal da proposta).

    ⚠️ ESCOLHE O BLOCO PELO CONTEÚDO, e não pelo primeiro que casa. Este arquivo
    tem DOIS `SELECT numero_proposta` — o da listagem e o do detalhe — e a
    primeira versão deste helper pegou o da listagem, acusando "23 colunas mas lê
    row[34]" sobre um SELECT que não é o testado. Um teste que protege o bloco
    errado falha (ou passa) por motivo nenhum. A mesma armadilha já está anotada
    em tests/test_radar_router_guardas.py.
    """
    fonte = ROTA.read_text(encoding="utf-8")
    blocos = re.findall(r'SELECT numero_proposta.*?FROM transferegov_propostas', fonte, re.S)
    alvo = [b for b in blocos if "situacao_projeto_basico" in b]
    assert len(alvo) == 1, (
        f"esperava UM SELECT com `situacao_projeto_basico`, achei {len(alvo)} "
        f"(de {len(blocos)} candidatos) — se a rota foi duplicada, este teste "
        f"passou a proteger o bloco errado")
    return alvo[0]


def _colunas(sql: str) -> list[str]:
    """As colunas do SELECT, sem comentários e sem a cláusula FROM em diante."""
    corpo = sql.split("FROM")[0]
    corpo = "\n".join(l for l in corpo.splitlines() if not l.strip().startswith("--"))
    corpo = corpo.replace("SELECT", "", 1)
    return [c.strip() for c in corpo.split(",") if c.strip()]


def test_a_situacao_do_TR_esta_no_select_e_e_a_ULTIMA_coluna():
    cols = _colunas(_bloco_detalhe())
    assert "situacao_projeto_basico" in cols, (
        "a rota parou de trazer `situacao_projeto_basico` — é o ÚNICO caminho do "
        "Termo de Referência que funciona com a sessão gov.br fria")
    assert cols[-1] == "situacao_projeto_basico", (
        f"`situacao_projeto_basico` deixou de ser a última coluna (é a {cols.index('situacao_projeto_basico')}ª "
        f"de {len(cols)}). O dict lê por ÍNDICE: inserir no meio desloca todos os "
        f"row[N] seguintes em silêncio, e a tela passa a mostrar um campo no lugar de outro")


def test_o_indice_lido_bate_com_o_numero_de_colunas():
    """⚠️ O guarda que pega o deslocamento sem depender de ninguém lembrar.

    Se alguém acrescentar uma coluna e esquecer de ler o novo índice — ou ler um
    índice que não existe —, a conta abaixo não fecha."""
    cols = _colunas(_bloco_detalhe())
    fonte = ROTA.read_text(encoding="utf-8")
    trecho = fonte[fonte.index("situacao_projeto_basico"):]
    maior = max(int(n) for n in re.findall(r"row\[(\d+)\]", trecho[:4000]))
    assert maior == len(cols) - 1, (
        f"o SELECT tem {len(cols)} colunas (índices 0..{len(cols)-1}) mas o dict "
        f"lê até row[{maior}] — alguém acrescentou coluna sem ler, ou lê índice inexistente")


def test_a_tela_mostra_o_TR_do_dado_aberto_quando_a_versao_logada_nao_veio():
    tela = TELA.read_text(encoding="utf-8")
    assert "situacao_projeto_basico" in tela, "a tela não lê o campo novo"
    # ⚠️ SÓ como fallback: com as duas caixas visíveis, o gestor veria o mesmo
    # assunto duas vezes, eventualmente com rótulos diferentes.
    assert re.search(r"!detalhe\.projeto_basico\?\.situacao\s*&&\s*detalhe\.situacao_projeto_basico",
                     tela), (
        "a caixa do dado aberto deixou de ser condicionada à ausência da versão "
        "logada — as duas apareceriam juntas")
    # E o rótulo tem de dizer de onde o dado veio: "Em Análise" sem contexto se
    # confunde com a leitura da tela autenticada, que traz documentos e datas.
    assert "dado aberto" in tela.lower(), (
        "sumiu a menção à origem; quem precisa do detalhe não saberia que tem de "
        "abrir o portal")


def test_o_coletor_continua_gravando_a_coluna():
    """Sem o coletor, a tela nova mostra vazio para sempre — e caladamente."""
    col = (RAIZ / "ingestion" / "transferegov_opendata.py").read_text(encoding="utf-8")
    assert '"situacao_projeto_basico"' in col
    assert "SITUACAO_PROJETO_BASICO" in col, (
        "o coletor parou de ler a coluna do CSV federal")
