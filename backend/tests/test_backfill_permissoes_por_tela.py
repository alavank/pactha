"""
⚠️⚠️ O BACKFILL DE `add_permissoes_por_tela.sql` — o arquivo de maior risco do
incremento «permissão por tela» (05/09/2026).

POR QUE ELE PRECISA DE UM TESTE PRÓPRIO
---------------------------------------
`AUTHZ_MODO` virou `bloqueio` por DEFAULT no MESMO deploy (decisão do dono,
depois de a consequência ter sido posta na mesa). A partir daquele boot, caixinha
desmarcada RECUSA de verdade — e até a véspera não recusava nada, porque em
`aviso` o `exige()` só registrava.

Consequência: existem contas em produção com telas e ZERO linha em
`user_permissoes`, que funcionavam perfeitamente. E existem contas cuja permissão
`transferegov.ver` abria as sete telas do grupo FEDERAIS. Uma linha esquecida
nesta migration não é "um detalhe a acertar depois" — é alguém trancado fora
amanhã de manhã, em cinco prefeituras ao mesmo tempo.

Este arquivo NÃO roda SQL (não há Postgres na suíte). Ele lê a migration como
TEXTO e confere as invariantes que a mordida costuma ter: chave que ficou de
fora do mapa, guard faltando, ordem errada em `MIGRATION_FILES`.

Rodar:
    python -m pytest backend/tests/test_backfill_permissoes_por_tela.py -v
"""
import re
from pathlib import Path

from services.permissoes import CATALOGO, PERMISSOES_INERTES
from services.startup import MIGRATION_FILES

BACKEND = Path(__file__).resolve().parent.parent
ARQUIVO = BACKEND / "migrations" / "add_permissoes_por_tela.sql"
# ⚠️ O `::text` SAI ANTES DA COMPARACAO. A primeira linha de todo `VALUES` do
# Postgres precisa do cast para o tipo da coluna ficar definido — e essa e uma
# regra de SQL, nao a invariante que este arquivo mede. Sem a limpeza, o teste
# quebraria se alguem apenas REORDENASSE o mapa, o que nao muda nada.
SQL = ARQUIVO.read_text(encoding="utf-8").replace("::text", "")

# As telas que o grupo FEDERAIS e o grupo ESTADUAIS passaram a ter. Escritas
# NOMINALMENTE: a graça do teste é justamente comparar a lista escrita aqui com
# a escrita na migration — derivar as duas da mesma fonte não acusaria nada.
FEDERAIS = [
    "transferegov_radar", "transferegov_geral", "transferegov_especiais",
    "transferegov_pac", "transferegov_voluntarias", "transferegov_rejeitadas",
    "transferegov_encerradas", "transferegov_cnpj",
]
ESTADUAIS = [
    "repasses", "cofinanciamento", "monitoramento", "consulta_popular",
    "programas_rs", "funrigs", "emendas_rs", "tce_rs",
]


# ---------------------------------------------------------------------------
# 1. NINGUEM PERDE TELA
# ---------------------------------------------------------------------------
def test_quem_tinha_transferegov_ganha_as_oito_telas_federais():
    """Sem isto, TODO usuário com o grupo FEDERAIS perde os sete itens no
    deploy — a chave antiga deixou de existir como tela."""
    for tela in FEDERAIS:
        assert f"('transferegov', '{tela}')" in SQL, tela


def test_quem_tinha_convenios_ganha_as_oito_telas_estaduais():
    """Idem para o grupo ESTADUAIS. `convenios` e `emendas` continuam existindo
    como tela — só as OITO que estavam escondidas dentro de `convenios` entram
    na tradução."""
    for tela in ESTADUAIS:
        assert f"('convenios', '{tela}')" in SQL, tela


def test_convenios_e_emendas_NAO_sao_traduzidas():
    """⚠️ Elas já eram telas e continuam sendo. Traduzir `convenios` para
    `convenios` seria inofensivo, mas traduzir `emendas` para qualquer coisa
    indicaria que alguém entendeu a divisão ao contrário."""
    assert "('convenios', 'convenios')" not in SQL
    assert "('emendas'," not in SQL


def test_a_telemetria_herda_de_quem_tinha_a_auditoria():
    """A aba Telemetria declarava `tela: "auditoria"` — a chave de outra coisa.
    Quem tinha a trilha já via a telemetria, então traduzir preserva o acesso de
    hoje; separar as duas dali para a frente é decisão do administrador."""
    assert "('auditoria', 'telemetria')" in SQL


# ---------------------------------------------------------------------------
# 2. NINGUEM PERDE ACAO
# ---------------------------------------------------------------------------
def test_toda_tela_federal_e_estadual_traduz_o_ver():
    for tela in FEDERAIS:
        assert f"('transferegov.ver', '{tela}.ver')" in SQL, tela
    for tela in ESTADUAIS:
        assert f"('convenios.ver', '{tela}.ver')" in SQL, tela


def test_o_exportar_traduz_exatamente_para_as_telas_que_exportam():
    """⚠️ NEM TODA TELA EXPORTA, e o par tem de bater com o catálogo. Traduzir
    `exportar` para uma tela que não tem a chave gravaria permissão inexistente
    (a FK recusa, e a migration inteira aborta); deixar de traduzir para uma que
    tem tira o botão de PDF de quem sempre o teve."""
    for tela in FEDERAIS:
        tem_chave = f"{tela}.exportar" in CATALOGO
        traduz = f"('transferegov.exportar', '{tela}.exportar')" in SQL
        assert tem_chave == traduz, (
            f"{tela}: catalogo diz exportar={tem_chave}, migration diz {traduz}")


def test_parametros_herda_de_usuarios():
    """A aba de Parâmetros pegava carona em `usuarios.*` — quem editava PESSOAS
    editava as LISTAS. Traduzir preserva o acesso de hoje."""
    assert "('usuarios.ver', 'parametros.ver')" in SQL
    assert "('usuarios.editar', 'parametros.editar')" in SQL


def test_toda_chave_nova_do_incremento_e_alcancavel():
    """⭐ A INVARIANTE MAIS IMPORTANTE DO ARQUIVO.

    Chave nova que ninguém recebe e ninguém pode receber é uma tela que sumiu.
    Cada chave criada neste incremento tem de chegar a alguém por UM dos três
    caminhos: a tradução da permissão antiga (parte 3), a derivação a partir das
    telas para quem não tinha caixinha nenhuma (parte 4), ou o anti-lockout de
    administrador (parte 5).

    A parte 4 alcança QUALQUER chave cujo prefixo seja uma tela que a pessoa
    tem — então basta a chave existir no catálogo e não ser inerte."""
    novas = [
        f"{t}.{v}" for t in FEDERAIS + ESTADUAIS + ["parametros"]
        for v in ("ver", "exportar", "editar")
        if f"{t}.{v}" in CATALOGO
    ]
    assert novas, "nenhuma chave nova encontrada — o catalogo mudou de forma?"
    for chave in novas:
        assert chave not in PERMISSOES_INERTES, (
            f"{chave} nasceu inerte: ela nao abre rota nenhuma, entao nao "
            "deveria ter sido criada (ver a regra em services/permissoes.py)")


# ---------------------------------------------------------------------------
# 3. AS GUARDAS
# ---------------------------------------------------------------------------
def test_cada_parte_tem_o_proprio_guard_de_uma_vez_so():
    """⚠️ RODAR DE NOVO RE-CONCEDERIA o que o administrador tivesse retirado no
    meio-tempo — a mesma classe de erro que a regra "só quem tem zero caixinha"
    evita. Cinco partes, cinco marcas distintas."""
    marcas = set(re.findall(r"VALUES \('(add_permissoes_por_tela:[a-z_]+)'\)", SQL))
    assert len(marcas) == 5, (
        f"esperava 5 guards distintos, achei {sorted(marcas)}")
    assert SQL.count("INSERT INTO migration_backfills") == 5


def test_a_derivacao_alcanca_SO_quem_nao_tem_caixinha_nenhuma():
    """⚠️ A ASSIMETRIA DELIBERADA. Quem JÁ TEM linha foi configurado de
    propósito, e acrescentar caixinha desfaria uma restrição que alguém
    escolheu. Quem não tem nenhuma nunca foi configurado — e com `bloqueio`
    perderia tudo."""
    assert "NOT EXISTS (SELECT 1 FROM user_permissoes up WHERE up.user_id = u.id)" in SQL


def test_a_derivacao_pula_as_inertes():
    """Conceder chave que não abre rota nenhuma encheria `user_permissoes` de
    linha que não governa nada — e a árvore nem as desenha."""
    for chave in PERMISSOES_INERTES:
        assert f"'{chave}'" in SQL, (
            f"{chave} nao esta na lista de exclusao da parte 4")


def test_o_antilockout_do_admin_existe_e_cobre_o_conjunto_inteiro():
    """⭐ A LINHA QUE IMPEDE O PIOR CENÁRIO. `_require_admin` virou
    `_exige_tela_usuarios` em `routers/users.py`: um administrador sem
    `usuarios.*` se trancaria fora da única tela que conserta o problema."""
    assert "add_permissoes_por_tela:antilockout_admin" in SQL
    for verbo in ("ver", "criar", "editar", "excluir", "conceder", "resetar_senha"):
        assert f"('usuarios.{verbo}')" in SQL or f"'usuarios.{verbo}'" in SQL, verbo
    # E as TELAS de administração, sem as quais as chaves não bastam: a aba
    # Usuários é governada pela tela `usuarios` desde que `_require_admin` virou
    # `_exige_tela_usuarios`.
    assert "('usuarios'), ('frescor'), ('parametros')" in SQL


def test_quiosque_e_super_admin_ficam_de_fora():
    """O `viewer` do link público não é pessoa (o guard dele é outro), e o
    super-admin já recebe o catálogo inteiro pela função pura — desenhar 96
    caixinhas marcadas para o dono da plataforma sugeriria que alguém poderia
    desmarcá-las."""
    assert SQL.count("COALESCE(u.kiosk, FALSE) = FALSE") >= 3
    assert SQL.count("COALESCE(u.super_admin, FALSE) = FALSE") >= 2


# ---------------------------------------------------------------------------
# 4. A ORDEM
# ---------------------------------------------------------------------------
def test_roda_depois_da_migration_que_cria_a_tabela_catalogo():
    """⚠️ DEPENDÊNCIA DURA: este arquivo faz INSERT em `user_permissoes`, cuja
    FK aponta para `permissoes_catalogo` — que nasce e é semeada em
    `add_permissoes_por_acao.sql`. Inverter a ordem quebra banco NOVO no
    primeiro boot, que é a classe de bug que Nova Palma já expôs uma vez."""
    assert MIGRATION_FILES.index("add_permissoes_por_tela.sql") \
        > MIGRATION_FILES.index("add_permissoes_por_acao.sql")


def test_o_perfil_prefeito_e_desativado_depois_da_tabela_de_parametros():
    assert MIGRATION_FILES.index("desativa_perfil_prefeito.sql") \
        > MIGRATION_FILES.index("add_parametros.sql")


def test_as_tres_migrations_do_incremento_estao_registradas():
    for nome in ("add_usuario_funcao_whatsapp.sql", "desativa_perfil_prefeito.sql",
                 "add_permissoes_por_tela.sql"):
        assert nome in MIGRATION_FILES, nome
        assert (BACKEND / "migrations" / nome).exists(), nome
