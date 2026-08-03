"""
A funcao PURA que resolve "o que este usuario pode" — por TABELA-VERDADE.

POR QUE ESTE ARQUIVO EXISTE, e por que ele e o mais importante do incremento:

O RBAC do PACTHA ja foi atalho tres vezes. Era `if role == 'admin'` zerando os
limites (Incremento 4), era `READONLY_ROLES` decidindo escrita pelo papel, era o
Cofre olhando `user.role` direto no router. Toda vez a regra estava espalhada em
if espalhado por arquivo, e toda vez ninguem conseguia responder de cabeca "quem
pode o que" — que e a pergunta que uma prefeitura faz numa auditoria.

`permissoes_efetivas` existe para essa pergunta ter UMA resposta, escrita num
lugar so, sem banco, sem `Request`, sem `User`. E a tabela-verdade abaixo existe
para que qualquer mudanca nela seja uma decisao consciente: quem reintroduzir um
atalho vai ter de vir aqui apagar uma linha que diz, em portugues, o que aquele
atalho quebra.

Rodar:
    python -m pytest backend/tests/test_permissoes_pura.py -v
"""
import re

import pytest

from services import permissoes
from services.permissoes import (CATALOGO, PERMISSOES_QUIOSQUE, TODAS,
                                 permissoes_efetivas)

SEM_ESCRITA = frozenset(c for c, p in CATALOGO.items() if not p.escrita)


# ===========================================================================
# TABELA-VERDADE
# ===========================================================================
# Cada linha: (nome do caso, entradas, conjunto esperado).
# O nome nao e enfeite — e ele que aparece no `-v` e no relatorio de CI, e e
# assim que alguem descobre O QUE quebrou sem abrir o arquivo.
TABELA = [
    # --- 1. Conta desativada nao pode nada -------------------------------
    ("desativado nao pode nada, nem sendo super-admin",
     dict(ativo=False, super_admin=True), frozenset()),
    ("desativado nao pode nada, mesmo com permissao concedida",
     dict(ativo=False, concedidas={"rm.ver", "rm.excluir"}), frozenset()),
    ("desativado vence ate o quiosque",
     dict(ativo=False, quiosque=True), frozenset()),

    # --- 2. Quiosque vale o conjunto fixo, e vem antes do super-admin -----
    ("quiosque vale o conjunto fixo",
     dict(quiosque=True), PERMISSOES_QUIOSQUE),
    ("quiosque NAO herda poder de super-admin",
     dict(quiosque=True, super_admin=True), PERMISSOES_QUIOSQUE),
    ("quiosque ignora o que estiver concedido na conta",
     dict(quiosque=True, concedidas={"cofre.revelar", "usuarios.excluir"}),
     PERMISSOES_QUIOSQUE),

    # --- 3. Super-admin e ROOT -------------------------------------------
    ("super-admin sem caixinha nenhuma pode tudo",
     dict(super_admin=True), TODAS),
    ("super-admin com a lista VAZIA continua podendo tudo",
     dict(super_admin=True, concedidas=set()), TODAS),
    ("super-admin nao pode ser REVOGADO por concessao parcial",
     dict(super_admin=True, concedidas={"rm.ver"}), TODAS),

    # --- 4. Todo o resto vale o que esta marcado -------------------------
    ("sem nada carregado e ZERO (None nao e 'sem limite')",
     dict(concedidas=None), frozenset()),
    ("lista vazia e zero",
     dict(concedidas=set()), frozenset()),
    ("vale exatamente o que esta marcado",
     dict(concedidas={"rm.ver", "rm.editar"}), frozenset({"rm.ver", "rm.editar"})),
    ("ver sem editar e um estado valido (a regra do dono)",
     dict(concedidas={"gestao.ver"}), frozenset({"gestao.ver"})),
    ("editar sem ver tambem e valido — quem monta a tela e a tela",
     dict(concedidas={"gestao.editar"}), frozenset({"gestao.editar"})),
    ("chave inexistente e DESCARTADA (typo nao concede)",
     dict(concedidas={"rm.ver", "rm.excluri", "documentoss.ver", ""}),
     frozenset({"rm.ver"})),
    ("chave com caixa e espaco e normalizada",
     dict(concedidas={" RM.Ver ", "rm.ver"}), frozenset({"rm.ver"})),
    ("papel nao aparece na conta: quem so tem a lista, so tem a lista",
     dict(concedidas={"convenios.ver"}), frozenset({"convenios.ver"})),

    # --- 5. Somente-leitura subtrai a escrita, por ultimo ----------------
    ("somente-leitura perde os verbos de escrita",
     dict(concedidas={"rm.ver", "rm.editar", "rm.excluir", "rm.exportar"},
          somente_leitura=True), frozenset({"rm.ver", "rm.exportar"})),
    ("somente-leitura alcanca ATE o super-admin (o guard e acima da permissao)",
     dict(super_admin=True, somente_leitura=True), SEM_ESCRITA),
    ("somente-leitura NAO tira o Modo Tela nem o link publico do prefeito",
     dict(concedidas={"bi.ver", "bi.tela", "bi.link"}, somente_leitura=True),
     frozenset({"bi.ver", "bi.tela", "bi.link"})),
    ("somente-leitura tira a IA (o endpoint e POST e o guard barra)",
     dict(concedidas={"ai.usar", "ai.exportar"}, somente_leitura=True),
     frozenset()),
    ("somente-leitura NAO tira revelar a senha (o endpoint e GET)",
     dict(concedidas={"cofre.ver", "cofre.revelar", "cofre.excluir"},
          somente_leitura=True), frozenset({"cofre.ver", "cofre.revelar"})),
]


@pytest.mark.parametrize("nome,entradas,esperado", TABELA,
                         ids=[linha[0] for linha in TABELA])
def test_tabela_verdade(nome, entradas, esperado):
    assert permissoes_efetivas(**entradas) == esperado


def test_devolve_frozenset_para_o_chamador_nao_mutar():
    """A resposta e comparada a cada requisicao e viaja para a API. Se fosse um
    set comum, um consumidor distraido (`efetivas.add(...)` num teste, um
    `.pop()` numa serializacao) alteraria a permissao de quem estivesse na
    requisicao seguinte."""
    assert isinstance(permissoes_efetivas(concedidas={"rm.ver"}), frozenset)
    assert isinstance(permissoes_efetivas(super_admin=True), frozenset)


def test_nao_devolve_o_proprio_catalogo_para_quem_nao_e_super():
    """Rede contra o erro classico de retornar a constante por engano: o
    conjunto do super-admin E `TODAS`, e um `return TODAS` no ramo errado daria
    o sistema inteiro a um usuario comum."""
    assert permissoes_efetivas(concedidas={"rm.ver"}) is not TODAS


def test_a_funcao_e_pura_nao_guarda_estado():
    """Duas chamadas iguais, resultados iguais — e a primeira nao contamina a
    segunda. E o que permite chama-la por requisicao sem cache e sem medo."""
    primeira = permissoes_efetivas(concedidas={"rm.ver"})
    permissoes_efetivas(super_admin=True)
    assert permissoes_efetivas(concedidas={"rm.ver"}) == primeira


def test_lista_concedida_nao_e_alterada():
    entrada = {"rm.ver", "lixo.que.nao.existe"}
    copia = set(entrada)
    permissoes_efetivas(concedidas=entrada)
    assert entrada == copia


def test_aceita_qualquer_iteravel():
    """Vem do banco como set, da API como lista, de um teste como tupla."""
    for forma in (["rm.ver"], ("rm.ver",), {"rm.ver"}, iter(["rm.ver"])):
        assert permissoes_efetivas(concedidas=forma) == frozenset({"rm.ver"})


# ===========================================================================
# O CATALOGO
# ===========================================================================
def test_toda_chave_tem_a_forma_recurso_ponto_acao():
    """A chave e CONTRATO: vai para o banco, para a API e para o `exige()` do
    router. Chave com maiuscula, acento ou espaco quebraria a comparacao em
    algum dos tres — e a falha seria silenciosa."""
    molde = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
    invalidas = [c for c in CATALOGO if not molde.match(c)]
    assert invalidas == []


def test_todas_bate_com_o_catalogo():
    assert TODAS == frozenset(CATALOGO)


def test_toda_permissao_tem_rotulo_e_descricao_em_portugues():
    """Sem descricao, a tela vira 66 caixinhas com jargao — e o administrador
    marca no chute. A descricao e o que torna a delegacao possivel."""
    for chave, permissao in CATALOGO.items():
        assert permissao.descricao.strip(), chave
        assert len(permissao.descricao) > 20, chave
        assert permissao.descricao.rstrip().endswith("."), chave
        assert permissao.verbo_rotulo.strip(), chave
        assert permissao.recurso_rotulo.strip(), chave


def test_toda_permissao_pertence_a_uma_secao_conhecida():
    conhecidas = {s["chave"] for s in permissoes.SECOES}
    assert {p.secao for p in CATALOGO.values()} <= conhecidas


def test_toda_secao_tem_pelo_menos_uma_permissao():
    """Secao vazia e um cabecalho sozinho na tela — e o sinal de que alguem
    removeu um recurso e esqueceu a secao."""
    usadas = {p.secao for p in CATALOGO.values()}
    faltando = [s["chave"] for s in permissoes.SECOES if s["chave"] not in usadas]
    assert faltando == []


def test_as_especiais_que_o_dono_pediu_existem():
    """As chaves que separam dois poderes que o verbo generico juntaria. Se uma
    delas sumir num refactor, o poder volta a ser concedido de carona."""
    for chave in ("cofre.revelar", "gestao.anexo_baixar", "usuarios.conceder",
                  "usuarios.resetar_senha", "auditoria.exportar", "bi.tela",
                  "bi.link", "ai.usar", "sessoes.capturar",
                  "telegram.administrar"):
        assert chave in CATALOGO, chave


def test_ver_e_exportar_nunca_sao_escrita():
    """`escrita` decide o que o perfil somente-leitura perde. Marcar um `ver`
    como escrita apagaria a tela do prefeito."""
    for chave, permissao in CATALOGO.items():
        if chave.endswith(".ver"):
            assert not permissao.escrita, chave


def test_verbos_destrutivos_sao_sempre_escrita():
    for chave, permissao in CATALOGO.items():
        if chave.rsplit(".", 1)[1] in ("criar", "editar", "excluir", "atualizar"):
            assert permissao.escrita, chave


def test_por_secao_devolve_o_catalogo_inteiro():
    total = sum(len(g["permissoes"])
                for secao in permissoes.por_secao()
                for g in secao["recursos"])
    assert total == len(CATALOGO)


def test_por_secao_filtrado_so_traz_o_que_a_pessoa_tem():
    saida = permissoes.por_secao({"rm.ver", "rm.excluir"})
    chaves = [p["chave"] for s in saida for g in s["recursos"]
              for p in g["permissoes"]]
    assert sorted(chaves) == ["rm.excluir", "rm.ver"]
    # Secao sem nada nao aparece: cabecalho vazio na tela e ruido.
    assert [s["chave"] for s in saida] == [permissoes.SEC_TRABALHO]


def test_resumo_agrupa_por_recurso():
    assert permissoes.resumo({"rm.ver", "rm.editar", "cofre.revelar"}) == [
        "Relatorio de Monitoramento: Ver, Editar",
        "Cofre de senhas: Revelar a senha",
    ]


def test_resumo_de_quem_nao_pode_nada_e_vazio():
    assert permissoes.resumo(set()) == []


def test_catalogo_para_api_nao_esconde_nada():
    payload = permissoes.catalogo_para_api()
    assert payload["total"] == len(CATALOGO)
    assert len(payload["permissoes"]) == len(CATALOGO)
    assert {p["chave"] for p in payload["permissoes"]} == set(CATALOGO)
    # A API entrega a DESCRICAO: e por isso que o frontend nao precisa copiar
    # a lista — e a copia e o defeito que este arquivo existe para evitar.
    assert all(p["descricao"] for p in payload["permissoes"])
