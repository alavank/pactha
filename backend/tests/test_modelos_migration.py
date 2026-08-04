"""A migration dos MODELOS de permissao — e a promessa de que o molde nao virou
grupo pelas costas.

QUATRO COISAS SAO TESTADAS AQUI, e as quatro tem historico neste repo:

1. ⭐ NAO EXISTE VINCULO USUARIO -> MODELO. E a regra do dono ("grupo e so
   ROTULO"), e ela so se sustenta se o schema nao tiver por onde amarrar uma
   pessoa a um molde. Uma coluna `modelo_id` em `users` (ou uma tabela de
   juncao) apareceria como conveniencia e transformaria copia em heranca — e
   ninguem notaria ate alguem editar um modelo e mudar quinze cadastros.

2. A SEMENTE CRUZA `migration_backfills`. O runner roda TODO arquivo a CADA boot
   e engole erro. Molde e dado que o ADMINISTRADOR apaga e edita: sem a marca, o
   boot seguinte ressuscita o molde apagado ontem.

3. O CONTEUDO DO MOLDE SO USA CHAVE QUE EXISTE. A FK ja recusaria em tempo de
   execucao — mas a semente roda no PRIMEIRO boot de um tenant novo, e uma chave
   errada ali derrubaria a transacao inteira da migration (o runner engole o
   erro e o banco fica sem as tabelas, em silencio).

4. A MIGRATION ESTA REGISTRADA NO RUNNER, na ordem certa. Migration orfa ja
   aconteceu neste repo — add_siconv_federal.sql nasceu fora da lista.

Rodar:
    python -m pytest backend/tests/test_modelos_migration.py -v
"""
import re
from pathlib import Path

import pytest

from services.permissoes import CATALOGO, ESCOPO_RECURSOS, ESCOPOS
from services.startup import MIGRATION_FILES

MIGRACOES = Path(__file__).resolve().parent.parent / "migrations"
ARQUIVO = MIGRACOES / "add_modelos_de_permissao.sql"
SQL = ARQUIVO.read_text(encoding="utf-8")

# O arquivo tem uma lista de VALUES por assunto. Cortamos no titulo da secao 4
# em vez de separar por regex esperto: se alguem reorganizar o arquivo, o teste
# falha em vez de ler a lista errada calado.
MARCO = "4. ⭐ SEMENTE"
assert MARCO in SQL, "a secao da semente mudou de titulo — conferir este teste"
TRECHO_DDL, TRECHO_SEMENTE = SQL.split(MARCO, 1)

# ⚠️ O `(?:::text)?` DO FIM NAO E ENFEITE. A primeira linha de cada lista de
# VALUES leva o molde `'...'::text` nas DUAS colunas, para o Postgres saber o
# tipo. Sem aceitar isso aqui, o regex pula exatamente essa linha — e um teste
# que confere 72 de 73 chaves passa verde sem olhar a que interessa.
_CONTEUDO = re.compile(r"\('([^']+)'(?:::text)?,\s*'([a-z_]+\.[a-z_]+)'(?:::text)?\)")
_ALCANCE = re.compile(
    r"\('([^']+)'(?:::text)?,\s*'([a-z_]+)'(?:::text)?,\s*'([a-z_]+)'(?:::text)?\)")


def _conteudo() -> list:
    return _CONTEUDO.findall(TRECHO_SEMENTE)


def _alcance() -> list:
    trecho = TRECHO_SEMENTE.split("alcance(modelo, recurso, escopo)", 1)[1]
    return _ALCANCE.findall(trecho)


# ===========================================================================
# 1. ⭐ O molde NAO e grupo
# ===========================================================================
def test_nenhuma_tabela_de_modelo_aponta_para_um_USUARIO_como_membro():
    """⚠️ SE ESTE TESTE QUEBRAR, LEIA ANTES DE "CONSERTAR".

    A regra do dono, palavra por palavra: "as permissoes sao colocadas no
    usuario da pessoa, INDIVIDUALMENTE. Grupo e so ROTULO."

    O unico jeito de essa regra sobreviver a manutencao e o schema nao ter por
    onde ligar uma pessoa a um molde. As unicas colunas de `users` permitidas
    aqui sao de PROCEDENCIA (`criado_por`, `atualizado_por`) — quem escreveu o
    molde, e nao quem o "pertence".

    Uma tabela `modelo_usuarios` ou uma coluna `modelo_id` em `users` pareceria
    conveniente e transformaria COPIA em HERANCA: no dia seguinte, "o que esta
    pessoa pode?" deixaria de ter resposta olhando a pessoa."""
    referencias = re.findall(r"REFERENCES\s+users\(id\)", SQL)
    colunas = re.findall(r"^\s*(\w+)\s+INTEGER REFERENCES users\(id\)", SQL, re.M)
    assert set(colunas) == {"criado_por", "atualizado_por"}, colunas
    assert len(referencias) == len(colunas)
    assert not re.search(r"CREATE TABLE[^;]*modelo_usuarios", SQL, re.I)
    assert not re.search(r"usuario_modelos|user_modelos", SQL, re.I)


def test_o_conteudo_do_molde_e_por_MODELO_e_nunca_por_usuario():
    """As duas tabelas de conteudo sao chaveadas pelo MODELO. Se alguma delas
    ganhasse `user_id`, o molde passaria a guardar estado de pessoa."""
    for tabela in ("modelo_permissoes", "modelo_escopos"):
        trecho = SQL.split(f"CREATE TABLE IF NOT EXISTS {tabela}", 1)[1]
        corpo = trecho.split(");", 1)[0]
        assert "modelo_id" in corpo, tabela
        assert "user_id" not in corpo, tabela


# ===========================================================================
# 2. ⭐ A semente roda UMA VEZ na vida do banco
# ===========================================================================
def test_a_semente_cruza_migration_backfills():
    """⚠️ Ao contrario da semente do CATALOGO de permissoes, que roda a cada
    boot de proposito.

    A diferenca e quem manda no dado: catalogo ninguem edita nem apaga; molde e
    dado de trabalho do cliente. Sem a marca, o administrador que apagasse o
    molde que nao serve a prefeitura dele o veria de volta no boot seguinte — e
    o defeito seria invisivel ate alguem reclamar que "o modelo voltou
    sozinho"."""
    assert "migration_backfills" in TRECHO_SEMENTE
    assert "add_modelos_de_permissao:semente_dos_quatro_moldes" in TRECHO_SEMENTE
    assert "ON CONFLICT (nome) DO NOTHING" in TRECHO_SEMENTE
    assert "RETURNING nome" in TRECHO_SEMENTE
    # A marca so habilita o INSERT se ela for CRUZADA com a consulta.
    assert re.search(r"FROM\s+marca,\s*definicao", TRECHO_SEMENTE)


def test_o_conteudo_so_entra_para_os_moldes_recem_criados():
    """`novos` so devolve linha na primeira vez (o `RETURNING` do INSERT com
    `ON CONFLICT DO NOTHING`). Se o conteudo fosse inserido a partir de um
    SELECT na tabela inteira, a caixinha que o administrador tirou de um molde
    voltaria a cada boot."""
    for tabela in ("modelo_permissoes", "modelo_escopos"):
        trecho = TRECHO_SEMENTE.split(f"INSERT INTO {tabela}", 1)[1]
        cabeca = trecho.split("ON CONFLICT", 1)[0]
        assert re.search(r"FROM\s+novos\s+n", cabeca), tabela
        assert "modelos_permissao" not in cabeca, (
            f"{tabela} esta lendo a tabela de modelos direto — o conteudo "
            "voltaria a cada boot")


# ===========================================================================
# 3. O conteudo semeado
# ===========================================================================
def test_a_semente_so_usa_chave_que_existe_no_catalogo():
    """A FK recusaria em tempo de execucao — mas aqui o erro derrubaria a
    transacao inteira da migration no PRIMEIRO boot de um tenant novo, e o
    runner engole o erro: as tabelas simplesmente nao existiriam."""
    chaves = {permissao for _, permissao in _conteudo()}
    assert chaves - set(CATALOGO) == set()


def test_a_semente_so_usa_modulo_escopavel_e_valor_valido():
    for _, recurso, escopo in _alcance():
        assert recurso in ESCOPO_RECURSOS, recurso
        assert escopo in ESCOPOS, escopo


def test_os_quatro_moldes_estao_la_com_os_nomes_das_TELAS():
    """"NAO invente cargo que nao existe; olhe as telas do sistema para nomear."
    Sao os quatro modos de usar o PACTHA que existem hoje."""
    nomes = {nome for nome, _ in _conteudo()}
    assert nomes == {"Somente consulta", "Gestao Interna - operacao",
                     "Cofre e convenios", "Painel do prefeito"}


def test_o_nome_do_molde_bate_entre_a_definicao_e_o_conteudo():
    """⚠️ O conteudo entra por JOIN no NOME (`ON c.modelo = n.nome`). Um typo de
    um caractere numa das listas nao quebra nada em tempo de execucao: o molde
    nasceria VAZIO, e o administrador so descobriria ao aplicar e ver zero
    caixinha marcada. E o tipo de defeito que so um teste pega."""
    trecho = TRECHO_SEMENTE.split("), novos AS", 1)[0]
    declarados = set(re.findall(r"\('([^']+)'(?:::text)?,\s*\n", trecho))
    assert declarados, "a lista `definicao` mudou de forma — conferir este teste"
    assert {nome for nome, _ in _conteudo()} - declarados == set()
    assert {nome for nome, _, _ in _alcance()} - declarados == set()
    # E o contrario: molde declarado sem uma caixinha sequer seria um molde que
    # nao faz nada.
    assert declarados - {nome for nome, _ in _conteudo()} == set()


def test_nenhum_molde_carrega_acao_irreversivel_sem_alcance():
    """⚠️ Regra (b) do cabecalho da migration: aplicar um molde no usuario
    errado nao pode custar dado que nao volta.

    `excluir` so aparece no molde de operacao, e la ele vem com o alcance
    «somente os que ele criou» nos MESMOS tres modulos — a pessoa apaga o que
    ela mesma criou, nunca o trabalho de um colega. `cofre.excluir` nao aparece
    em molde nenhum."""
    por_molde: dict = {}
    for nome, permissao in _conteudo():
        por_molde.setdefault(nome, set()).add(permissao)
    escopados = {(nome, recurso) for nome, recurso, escopo in _alcance()
                 if escopo == "proprios"}

    assert "cofre.excluir" not in por_molde["Cofre e convenios"]
    for nome, chaves in por_molde.items():
        for chave in chaves:
            recurso, verbo = chave.split(".", 1)
            if verbo != "excluir":
                continue
            assert recurso in ESCOPO_RECURSOS, f"{nome}: {chave} sem alcance possivel"
            assert (nome, recurso) in escopados, (
                f"{nome} carrega {chave} sem restringir o alcance de {recurso}")


def test_nenhum_molde_publica_o_link_sem_login_do_painel():
    """Regra (c): `bi.link` abre o Painel para quem tiver o endereco, SEM login,
    e esses links circulam por WhatsApp. Publicar tem de ser clique
    deliberado — nunca efeito de aplicar um molde."""
    assert "bi.link" not in {p for _, p in _conteudo()}


def test_o_molde_do_prefeito_e_so_o_painel():
    do_prefeito = {p for nome, p in _conteudo() if nome == "Painel do prefeito"}
    assert do_prefeito == {"bi.ver", "bi.exportar", "bi.tela"}


def test_o_molde_de_consulta_nao_escreve_nada():
    """"Somente consulta" que dispare uma coleta (`atualizar`) mudaria situacao
    e valores de dezenas de registros para TODO MUNDO."""
    do_consulta = {p for nome, p in _conteudo() if nome == "Somente consulta"}
    assert do_consulta
    for chave in do_consulta:
        assert not CATALOGO[chave].escrita, chave
        assert chave.rsplit(".", 1)[1] in ("ver", "exportar"), chave
    # O anexo digitalizado e leitura, mas e a unica que entrega documento
    # escaneado — fica de fora de proposito (regra (a): molde e piso).
    assert "gestao.anexo_baixar" not in do_consulta


def test_nenhum_molde_concede_o_poder_de_mexer_em_gente():
    """Molde que carregue `usuarios.*` seria um molde capaz de fabricar outro
    administrador — e aplicavel por quem so queria cadastrar um servidor."""
    for nome, permissao in _conteudo():
        assert not permissao.startswith("usuarios."), f"{nome}: {permissao}"
        assert not permissao.startswith("auditoria."), f"{nome}: {permissao}"


def test_a_semente_nao_repete_a_mesma_caixinha_no_mesmo_molde():
    pares = _conteudo()
    assert len(pares) == len(set(pares))


# ===========================================================================
# 4. As tabelas
# ===========================================================================
def test_a_fk_do_conteudo_aponta_para_o_catalogo_de_permissoes():
    """Sem a FK, um typo (`cofre.revellar`) gravaria: um molde que promete uma
    permissao e nunca a concede — falha silenciosa multiplicada por todo mundo
    que aplicar o molde."""
    assert re.search(
        r"permissao TEXT NOT NULL REFERENCES permissoes_catalogo\s*\(chave\)", SQL)
    assert re.search(
        r"recurso   TEXT NOT NULL REFERENCES escopo_recursos\s*\(recurso\)", SQL)


def test_apagar_o_modelo_leva_o_conteudo_e_o_catalogo_e_restrict():
    assert SQL.count("REFERENCES modelos_permissao(id) ON DELETE CASCADE") == 2
    # Tirar do catalogo uma permissao (ou um modulo escopavel) que um molde usa
    # tem de DOER — a mesma regra de `user_permissoes`.
    assert len(re.findall(
        r"REFERENCES (?:permissoes_catalogo|escopo_recursos)\s*\([a-z]+\)\s*\n?\s*"
        r"ON UPDATE CASCADE ON DELETE RESTRICT", SQL)) == 2
    # Apagar a conta de quem criou nao pode levar junto o molde que a
    # prefeitura inteira usa.
    assert SQL.count("REFERENCES users(id) ON DELETE SET NULL") == 2


def test_o_banco_recusa_valor_de_alcance_fora_do_vocabulario():
    assert re.search(r"CHECK \(escopo IN \('todos', 'proprios'\)\)", SQL)


def test_o_nome_e_unico_inclusive_na_caixa_alta():
    """O molde e escolhido PELO NOME num seletor: "Cofre" e "cofre" lado a lado
    fariam o administrador aplicar um achando que era o outro."""
    assert re.search(r"nome\s+TEXT NOT NULL UNIQUE", SQL)
    assert "ux_modelos_permissao_nome_lower" in SQL
    assert "lower(nome)" in SQL


def test_as_tabelas_sao_idempotentes():
    """O runner executa o arquivo inteiro a cada boot."""
    assert SQL.count("CREATE TABLE IF NOT EXISTS") == 3
    assert SQL.count("CREATE INDEX IF NOT EXISTS") == 1
    assert SQL.count("CREATE UNIQUE INDEX IF NOT EXISTS") == 1


def test_o_sql_e_valido():
    pglast = pytest.importorskip("pglast")
    assert len(pglast.parse_sql(SQL)) >= 5


# ===========================================================================
# 5. A ordem no runner
# ===========================================================================
def test_a_migration_esta_registrada_no_runner():
    assert "add_modelos_de_permissao.sql" in MIGRATION_FILES


def test_a_ordem_das_dependencias():
    """Le `permissoes_catalogo` (alvo da FK do conteudo) e `escopo_recursos`
    (alvo da FK do alcance), e tem de vir ANTES do append-only da trilha."""
    indice = MIGRATION_FILES.index("add_modelos_de_permissao.sql")
    assert indice > MIGRATION_FILES.index("add_permissoes_por_acao.sql")
    assert indice > MIGRATION_FILES.index("add_escopo_por_modulo.sql")
    assert indice < MIGRATION_FILES.index("add_auditoria_imutavel.sql")
    assert MIGRATION_FILES[-1] == "add_auditoria_imutavel.sql"


def test_o_arquivo_existe_com_o_nome_registrado():
    assert ARQUIVO.exists()


# ===========================================================================
# 6. A permissao nova, na semente do catalogo
# ===========================================================================
def test_a_caixinha_de_gerenciar_modelos_esta_no_catalogo_do_sql():
    """Chave que existe so no Python NAO E GRAVAVEL (a FK recusa). A semente
    fica em add_permissoes_por_acao.sql, que e onde mora a tabela-catalogo."""
    outra = (MIGRACOES / "add_permissoes_por_acao.sql").read_text(encoding="utf-8")
    assert "('usuarios.modelos', 'usuarios', TRUE)" in outra
    assert "usuarios.modelos" in CATALOGO
    assert CATALOGO["usuarios.modelos"].escrita is True
