"""Molde nao pode citar permissao que o catalogo nao tem.

Achado em 09/09/2026 subindo a stack local com banco NOVO, o primeiro teste do
PACTHA feito fora de producao:

    Migration add_modelos_de_permissao.sql falhou: insert or update on table
    "modelo_permissoes" violates foreign key constraint
    "modelo_permissoes_permissao_fkey"

Em 05/09/2026 `add_permissoes_por_tela.sql` fatiou o modulo TransfereGov por
tela: `transferegov.ver` virou oito chaves (`transferegov_geral.ver`,
`transferegov_voluntarias.ver`, ...) e saiu do catalogo. A semente dos MOLDES
continuou pedindo a chave velha, que e FK de `permissoes_catalogo`.

⚠️ O ESTRAGO E MAIOR DO QUE UM MOLDE ERRADO. A migration inteira e UMA
transacao: a violacao da FK reverte tambem o `CREATE TABLE` de
`modelos_permissao`, `modelo_permissoes` e `modelo_escopos`. E como o runner
engole erro de migration e a API sobe assim mesmo (services/startup.py), o
tenant nasce SEM a funcionalidade de modelos e nada avisa — o unico sinal e a
linha `Startup migrations: 125/126` no log do boot.

⚠️ E POR QUE NINGUEM VIU POR QUATRO DIAS: o fatiamento nao APAGA a chave velha
de quem ja a tinha. Nos cinco tenants criados antes de 05/09 `transferegov.ver`
continua no catalogo, entao la a migration passa (126/126). So banco NOVO
quebra — e banco novo so nasce quando entra cliente. Medido nos dois lados:
dump do novapalma-rs restaurado local = 104 chaves no catalogo, 3 tabelas de
molde, 4 moldes; banco criado do zero = 99 chaves, ZERO tabelas de molde.

E a mesma familia de armadilha de `test_migrations_ordem_tabela.py`: custo que
so aparece no proximo cliente, e que o cliente descobre primeiro.
"""
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGR = os.path.join(RAIZ, "migrations")

MOLDES = "add_modelos_de_permissao.sql"

# Um bloco `INSERT INTO <tabela> ... ;` inteiro, para so entao pescar as tuplas
# de dentro dele. Pescar no arquivo todo traria a lista de OUTROS inserts — em
# add_permissoes_por_acao.sql existe um `(tela, permissao, bool)` que daria
# falso positivo e faria este teste passar sempre.
def _bloco_insert(sql, tabela):
    return re.findall(r"INSERT\s+INTO\s+" + tabela + r"\b.*?;", sql, re.I | re.S)


_PRIMEIRO_DA_TUPLA = re.compile(r"\(\s*'([a-z0-9_.]+)'", re.I)
# ('Nome do molde'::text, 'chave.acao'::text) -> a segunda string
_SEGUNDO_DA_TUPLA = re.compile(
    r"\(\s*'[^']+'(?:::text)?\s*,\s*'([a-z0-9_]+\.[a-z0-9_]+)'(?:::text)?\s*\)", re.I
)


def _sql(nome):
    """Le a migration SEM as linhas de comentario: elas citam chave em prosa."""
    caminho = os.path.join(MIGR, nome)
    if not os.path.exists(caminho):
        return ""
    txt = open(caminho, encoding="utf-8", errors="replace").read()
    return "\n".join(l for l in txt.splitlines() if not l.lstrip().startswith("--"))


def _bloco_entre(sql, abre, fecha):
    m = re.search(abre + r"(.*?)" + fecha, sql, re.I | re.S)
    return m.group(1) if m else ""


def _catalogo_ate(nome_alvo):
    """Chaves que existem no catalogo quando `nome_alvo` roda.

    Percorre a MIGRATION_FILES NA ORDEM e para no alvo: chave inserida DEPOIS
    nao vale, que e a metade da armadilha (a outra e a chave que nunca existiu).
    """
    from services.startup import MIGRATION_FILES

    chaves = set()
    for nome in MIGRATION_FILES:
        if nome == nome_alvo:
            break
        for bloco in _bloco_insert(_sql(nome), "permissoes_catalogo"):
            chaves.update(_PRIMEIRO_DA_TUPLA.findall(bloco))
    return chaves


def _recursos_ate(nome_alvo):
    from services.startup import MIGRATION_FILES

    recursos = set()
    for nome in MIGRATION_FILES:
        if nome == nome_alvo:
            break
        for bloco in _bloco_insert(_sql(nome), "escopo_recursos"):
            recursos.update(_PRIMEIRO_DA_TUPLA.findall(bloco))
    return recursos


def _permissoes_dos_moldes():
    corpo = _bloco_entre(
        _sql(MOLDES),
        r"conteudo\s*\(\s*modelo\s*,\s*permissao\s*\)\s*AS\s*\(",
        r"\)\s*,\s*ins_conteudo",
    )
    return set(_SEGUNDO_DA_TUPLA.findall(corpo))


def _recursos_dos_moldes():
    corpo = _bloco_entre(
        _sql(MOLDES),
        r"alcance\s*\(\s*modelo\s*,\s*recurso\s*,\s*escopo\s*\)\s*AS\s*\(",
        r"\)\s*INSERT\s+INTO\s+modelo_escopos",
    )
    # ('molde'::text, 'recurso'::text, 'escopo'::text) -> a do meio
    return set(
        re.findall(
            r"\(\s*'[^']+'(?:::text)?\s*,\s*'([a-z0-9_]+)'(?:::text)?\s*,\s*'[^']+'",
            corpo,
            re.I,
        )
    )


def test_toda_permissao_de_molde_existe_no_catalogo():
    """O teste que teria evitado o incidente de 05-09/09/2026."""
    pedidas = _permissoes_dos_moldes()
    catalogo = _catalogo_ate(MOLDES)

    faltando = sorted(pedidas - catalogo)
    assert not faltando, (
        "A semente de " + MOLDES + " cita permissao que o catalogo nao tem: "
        + ", ".join(faltando)
        + ". `modelo_permissoes.permissao` e FK de `permissoes_catalogo`: a "
        "migration INTEIRA reverte, inclusive o CREATE TABLE das tres tabelas "
        "de molde, e o tenant NOVO nasce sem a funcionalidade — em silencio, "
        "porque o runner engole a falha e a API sobe. Renomeou permissao? "
        "atualize esta semente no MESMO commit."
    )


def test_todo_recurso_de_escopo_de_molde_existe():
    """Mesma FK, outro INSERT: `modelo_escopos.recurso` -> `escopo_recursos`."""
    pedidos = _recursos_dos_moldes()
    existentes = _recursos_ate(MOLDES)

    faltando = sorted(pedidos - existentes)
    assert not faltando, (
        "A semente de " + MOLDES + " cita recurso de escopo inexistente: "
        + ", ".join(faltando)
        + ". Mesmo estrago do teste acima: derruba a migration inteira."
    )


def test_as_chaves_do_incidente_nao_voltam():
    """Regressao nomeada: `transferegov.ver`/`.exportar` nao existem mais.

    Ficam citadas aqui de proposito. Quem copiar um bloco antigo de molde de
    outra branch traz a chave velha junto, e o nome dela neste arquivo e o que
    liga o vermelho ao incidente de 05/09/2026.
    """
    pedidas = _permissoes_dos_moldes()
    mortas = {"transferegov.ver", "transferegov.exportar"}
    voltaram = sorted(pedidas & mortas)
    assert not voltaram, (
        "Chave aposentada pelo fatiamento por tela voltou para a semente dos "
        "moldes: " + ", ".join(voltaram) + ". A traducao oficial esta em "
        "add_permissoes_por_tela.sql (oito telas em `.ver`, cinco em "
        "`.exportar`)."
    )


def test_a_deteccao_realmente_enxerga_a_semente():
    """Sem isto, um regex quebrado faria os tres testes acima passarem vazios.

    Foi assim que a familia de teste de migration deste repo ja se enganou uma
    vez: conjunto vazio nao viola nada.
    """
    pedidas = _permissoes_dos_moldes()
    assert len(pedidas) > 40, (
        "o parser leu " + str(len(pedidas)) + " permissoes da semente dos "
        "moldes — o CTE `conteudo` mudou de forma e os testes acima viraram "
        "enfeite"
    )
    assert "bi.ver" in pedidas, "esperava as permissoes do molde do prefeito"
    assert "transferegov_geral.ver" in pedidas, (
        "esperava as telas federais fatiadas — se sumiram, a correcao de "
        "09/09/2026 foi desfeita"
    )

    assert _recursos_dos_moldes() == {"gestao", "rm", "documentos"}, (
        "o CTE `alcance` mudou de forma e test_todo_recurso_... virou enfeite"
    )

    catalogo = _catalogo_ate(MOLDES)
    assert len(catalogo) > 80, (
        "o parser leu " + str(len(catalogo)) + " chaves de catalogo — o INSERT "
        "de `permissoes_catalogo` mudou de forma"
    )
