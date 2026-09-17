"""
⭐⭐ A ÁRVORE DE PERMISSÕES SEGUE O MENU — a promessa feita ao dono, por escrito.

O pedido, palavra por palavra:

    "O modal de usuário mostra a árvore do jeito que está no menu lateral do
     ambiente. (...) Se o menu do cliente mudar (módulo novo liberado, aba
     nova), a tela de permissões acompanha sem código novo."

Isso só é verdade enquanto os DOIS LADOS falarem da mesma lista de telas:

    frontend/src/lib/menu.ts        a ESTRUTURA — grupos, ordem, rotas.
    frontend/src/lib/telas.ts       as CHAVES de `user_telas`.
    backend/services/permissoes.py  as AÇÕES, com `Permissao.tela` apontando
                                    para a chave.

Divergir NÃO aparece na tela como erro, e é por isso que este arquivo existe:

  * folha no menu SEM chave no catálogo de telas -> o item aparece na barra
    lateral e some da árvore de permissões. Módulo que ninguém consegue liberar.

  * chave no catálogo de PERMISSÕES apontando para uma tela que não está no
    menu -> caixinha que concede o que não existe. Foi assim que `suas` e
    `telegram` sobreviveram meses depois de removidos.

⚠️ LÊ OS ARQUIVOS `.ts` DO DISCO, e o precedente é `test_catalogo_por_uf.py`
(que já faz isso com `telas.ts` e `estadual.ts`). Derivar em vez de ler daria um
teste que concorda consigo mesmo.

Rodar:
    python -m pytest backend/tests/test_arvore_segue_o_menu.py -v
"""
import re
from pathlib import Path

import pytest

from services.permissoes import CATALOGO

REPO = Path(__file__).resolve().parent.parent.parent
MENU_TS = REPO / "frontend" / "src" / "lib" / "menu.ts"
TELAS_TS = REPO / "frontend" / "src" / "lib" / "telas.ts"


def _fonte(arquivo: Path) -> str:
    if not arquivo.exists():  # backend empacotado sozinho
        pytest.skip("frontend nao esta neste checkout")
    return arquivo.read_text(encoding="utf-8")


def _hrefs_com_abas() -> set[str]:
    """As folhas que são TELA COM ABAS (`abas:` na mesma linha do `href:`).

    Elas não têm chave própria: a permissão é a de cada aba. Ver `abas` em
    `lib/menu.ts` (Emendas parlamentares, 17/09/2026)."""
    return set(re.findall(r'href:\s*"(/dashboard[^"]*)"[^\n]*\babas:\s*\[', _fonte(MENU_TS)))


def _telas_das_abas() -> set[str]:
    """As chaves declaradas nas abas — contam como estar no menu."""
    return {
        chave
        for bloco in re.findall(r"\babas:\s*\[(.*?)\]\s*\}", _fonte(MENU_TS), re.S)
        for chave in re.findall(r'tela:\s*"([a-z_]+)"', bloco)
    }


def _hrefs_do_menu() -> list[str]:
    """Todo `href:` de `menu.ts`, na ordem em que aparecem — menos as telas com
    abas, cuja chave sai das abas e não da rota."""
    com_abas = _hrefs_com_abas()
    return [h for h in re.findall(r'href:\s*"(/dashboard[^"]*)"', _fonte(MENU_TS))
            if h not in com_abas]


def _chaves_de_tela() -> set[str]:
    """As `key:` de `TELAS` em telas.ts."""
    return set(re.findall(r'key:\s*"([a-z_]+)"', _fonte(TELAS_TS)))


def _telas_extras() -> set[str]:
    """As telas que uma folha do menu declara como CAPACIDADE dela.

    São telas de verdade (`user_telas`, catálogo, banco) que não têm item na
    barra lateral porque são botões dentro de outra tela. Ver `NavLeaf` em
    `lib/menu.ts`."""
    fonte = _fonte(MENU_TS)
    return {
        chave
        for bloco in re.findall(r"telasExtras:\s*\[([^\]]*)\]", fonte)
        for chave in re.findall(r'"([a-z_]+)"', bloco)
    }


def _href_para_tela(href: str) -> str:
    """A MESMA conta de `telas.ts::hrefToTela`, reescrita em Python.

    ⚠️ SIM, E UMA SEGUNDA IMPLEMENTACAO, e a duplicacao e o teste: se alguem
    mudar a regra de conversao de um lado so, as duas param de concordar e este
    arquivo acusa. Uma versao que IMPORTASSE a do frontend nao poderia
    discordar dela, e um teste que nao pode discordar nao testa nada."""
    sem_prefixo = re.sub(r"^/dashboard/configuracoes(?=/|$)", "/dashboard", href)
    seg = re.sub(r"^/dashboard/?", "", sem_prefixo).split("/")[0] or "dashboard"
    chave = seg.replace("-", "_")
    if chave == "transferegov":
        return "transferegov_especiais"
    # ⚠️ A HOME. `hrefToTela` devolve "dashboard" (e tem de continuar
    # devolvendo: o guard de rota usa aquela funcao, e concessao antiga com a
    # chave `dashboard` segue valendo). Mas a chave do CATALOGO e `bi` — a
    # arvore aplica a mesma excecao em `lib/arvorePermissoes.ts::telaDaFolha`.
    if chave == "dashboard":
        return "bi"
    return chave


# ---------------------------------------------------------------------------
# 1. Menu -> catalogo de telas
# ---------------------------------------------------------------------------
def test_toda_folha_do_menu_tem_chave_de_tela():
    """Item na barra lateral que não vira chave é módulo impossível de liberar:
    ele aparece para quem já tem acesso e não existe na tela de Usuários."""
    telas = _chaves_de_tela()
    orfas = {}
    for href in _hrefs_do_menu():
        chave = _href_para_tela(href)
        if chave not in telas:
            orfas[href] = chave
    assert not orfas, (
        f"folhas do menu sem chave em telas.ts: {orfas}. Uma tela no menu e "
        "fora do catalogo e um modulo que ninguem consegue liberar na tela de "
        "Usuarios")


def test_toda_chave_de_tela_esta_no_menu():
    """O outro lado. Chave que não tem folha correspondente é uma caixinha que
    concede o que não existe — foi assim que `suas` e `telegram` sobreviveram
    meses depois de os módulos terem sido removidos."""
    do_menu = {_href_para_tela(h) for h in _hrefs_do_menu()}
    # ⚠️ `telasExtras` CONTA COMO ESTAR NO MENU, e esta linha e uma CORRECAO de
    # 05/09/2026. A versao anterior deste teste tinha `bi_tela` e `bi_link` numa
    # lista de excecao escrita a mao, com o comentario dizendo que "a arvore as
    # desenha dentro do grupo do Painel" — e a arvore NAO as desenhava. A
    # excecao escondeu o buraco em vez de acusa-lo: as duas telas existiam em
    # `telas.ts`, no catalogo e no banco, e nao havia onde marca-las. O
    # administrador nao conseguia conceder nem tirar o Modo Tela, e foi o dono
    # quem percebeu, usando.
    #
    # Agora a folha DECLARA as capacidades dela (`telasExtras` em `menu.ts`) e o
    # teste le a declaracao. Nao ha mais lista de excecao — o que nao estiver
    # declarado em lugar nenhum quebra, que era o ponto desde o começo.
    sobrando = _chaves_de_tela() - do_menu - _telas_extras() - _telas_das_abas()
    assert not sobrando, (
        f"chaves em telas.ts que nao tem folha no menu nem `telasExtras`: "
        f"{sorted(sobrando)}. Uma tela que nao esta em nenhum dos dois nao "
        "aparece na arvore, e ninguem consegue conceder nem tirar")


def test_emendas_parlamentares_e_uma_tela_com_as_quatro_chaves_antigas():
    """⭐ Decisão do dono (17/09/2026): a tela única NÃO tem chave nova — cada aba
    cobra a que já existia. Se uma aba sumir da declaração, quem só tinha aquela
    permissão perde o item do menu e a linha na árvore de Usuários."""
    assert "/dashboard/emendas-parlamentares" in _hrefs_com_abas()
    assert {"emendas_federais", "emendas", "emendas_rs", "parlamentares"} <= _telas_das_abas()
    assert "emendas_parlamentares" not in _chaves_de_tela()
    # As rotas antigas saíram do menu (redirecionam para a aba).
    antigas = {"/dashboard/emendas-federais", "/dashboard/emendas",
               "/dashboard/emendas-rs", "/dashboard/parlamentares"}
    assert not antigas & set(re.findall(r'href:\s*"(/dashboard[^"]*)"', _fonte(MENU_TS)))


def test_as_capacidades_do_painel_estao_declaradas():
    """⭐ O CASO QUE MOTIVOU `telasExtras`. «Modo Tela (TV)» e «Gerar link
    público» são botões DENTRO do Painel, não itens da barra lateral — mas são
    permissão separada, por decisão do dono: *"um secretário pode precisar da TV
    da sala dele sem ter permissão de gerar um link que roda o município inteiro
    pelo WhatsApp"*.

    Nominal de propósito: se alguém remover a declaração para "simplificar", as
    duas somem da árvore em silêncio — que foi exatamente o que aconteceu."""
    assert {"bi_tela", "bi_link"} <= _telas_extras()


# ---------------------------------------------------------------------------
# 2. Catalogo de PERMISSOES -> catalogo de telas
# ---------------------------------------------------------------------------
def test_toda_permissao_aponta_para_uma_tela_que_existe():
    """`Permissao.tela` é a dobradiça entre o catálogo e o menu. Uma chave
    apontando para tela inexistente some da árvore em silêncio: o administrador
    nunca vê a caixinha, e a permissão fica sem caminho de concessão."""
    telas = _chaves_de_tela()
    erradas = {
        chave: p.tela for chave, p in CATALOGO.items()
        if p.tela and p.tela not in telas
    }
    assert not erradas, (
        f"permissoes apontando para tela que nao existe em telas.ts: {erradas}")


def test_a_unica_capacidade_sem_tela_e_a_coleta_do_transferegov():
    """⚠️ `tela` VAZIO é permitido, mas é a exceção — e a lista é NOMINAL para
    que a próxima entre por decisão escrita, e não por esquecimento.

    Hoje há uma só: a coleta do Transfere Gov. O botão dela mora em
    Configurações › Sessões, e uma coleta alimenta as oito telas de FEDERAIS de
    uma vez — pendurá-la em qualquer uma delas faria a árvore mentir sobre onde
    o botão está."""
    sem_tela = {c for c, p in CATALOGO.items() if not p.tela}
    assert sem_tela == {"transferegov.atualizar"}, (
        f"capacidade sem tela nova ou faltando: {sorted(sem_tela)}. A arvore "
        "desenha estas como linha SEM interruptor de acesso — se a nova for uma "
        "tela de verdade, ela precisa declarar `tela=`")


# ---------------------------------------------------------------------------
# 3. As telas SEM acao, que sao legitimas
# ---------------------------------------------------------------------------
def test_as_telas_sem_acao_sao_as_conhecidas():
    """Uma tela pode não ter caixinha nenhuma: aí o interruptor de acesso É a
    permissão inteira. São duas hoje, e cada uma por um motivo diferente —
    manter a lista nominal impede que uma tela NOVA nasça sem ações por
    esquecimento e ninguém note."""
    from services.permissoes import PERMISSOES_INERTES

    telas = _chaves_de_tela()
    # ⚠️ AS INERTES NÃO CONTAM COMO AÇÃO, e é assim que a árvore as trata: ela
    # esconde a caixinha que não abre rota nenhuma. Contá-las aqui faria o teste
    # dizer que `bi_tela` "tem ação" sobre uma tela que na prática só tem o
    # interruptor.
    com_acao = {
        p.tela for chave, p in CATALOGO.items()
        if p.tela and chave not in PERMISSOES_INERTES
    }
    sem_acao = telas - com_acao
    esperado = {
        # Mural de painéis oficiais em iframe: não tem endpoint próprio, então
        # uma chave de ação não governaria nada (ver `services/permissoes.py`).
        "paineis",
        # O Modo Tela é controlado pela TELA, não por `bi.tela` — que é inerte.
        "bi_tela",
    }
    assert sem_acao == esperado, (
        f"telas sem acao mudaram: {sorted(sem_acao)}. Tela nova sem caixinha "
        "nenhuma costuma ser `tela=` esquecido no catalogo, e nao uma decisao")
