"""
O lock que serializa o boot (services/startup.py).

POR QUE ISTO TEM TESTE. O runner de migrations roda a lista INTEIRA a cada boot e
ENGOLE erro, e a API sobe com `uvicorn --workers 2` — dois processos chamando
`run_migrations()` ao mesmo tempo. A unica coisa que os separa e um advisory lock,
e ele estava QUEBRADO de um jeito invisivel: o lock e de SESSAO (morre com a
conexao) e a conexao que o segurava era descartada pelo coletor de lixo antes da
primeira migration rodar. Nenhum teste pegava, nenhum log reclamava, e o sintoma
so aparece em produÃ§ao, no boot, na forma de uma migration que "falhou" sem ter
falhado.

Sao testes de UNIDADE: nao ha Postgres aqui. O psycopg2 e substituido por um duplo
que registra as chamadas, e o que se verifica e o CONTRATO do boot, nao o SQL:

  1. a conexao do lock continua ABERTA enquanto as migrations rodam (a regressao);
  2. quem nao consegue o lock ESPERA e roda depois — nunca pula, porque worker que
     pula volta a servir com o schema pela metade;
  3. falha ao pegar o lock nao pode virar "nao rodar migration nenhuma".
"""
import sys
import types

import pytest


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, *args):
        self._conn.sqls.append(sql)
        if "pg_try_advisory_lock" in sql:
            # Acabado o roteiro, REPETE a ultima resposta. Antes isto devolvia
            # `True` por padrao, e o teste do teto de espera passava pelo motivo
            # errado: o duplo acabava concedendo o lock e o caminho do timeout
            # nunca era exercitado.
            if self._conn.roteiro:
                self._conn.resposta = self._conn.roteiro.pop(0)

    def fetchone(self):
        return (self._conn.resposta,)


class _FakeConn:
    """Conexao de mentira que anota se foi fechada e quando."""

    def __init__(self, roteiro, diario):
        # roteiro = respostas sucessivas do pg_try_advisory_lock
        self.roteiro = list(roteiro)
        self.diario = diario
        self.resposta = True
        self.autocommit = False
        self.fechada = False
        self.sqls = []

    def cursor(self):
        return _FakeCursor(self)

    def close(self):
        self.fechada = True
        self.diario.append("fechou_lock")


def _instalar_psycopg2_falso(monkeypatch, roteiro, diario):
    conexoes = []

    def connect(_url):
        c = _FakeConn(roteiro, diario)
        conexoes.append(c)
        return c

    modulo = types.ModuleType("psycopg2")
    modulo.connect = connect
    monkeypatch.setitem(sys.modules, "psycopg2", modulo)
    return conexoes


@pytest.fixture
def startup(monkeypatch):
    from services import startup as s

    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql://x:x@localhost/x")
    # Espera irrisoria: o teste nao pode gastar 2 minutos de relogio de verdade.
    monkeypatch.setattr(s, "LOCK_INTERVALO_S", 0.0)
    monkeypatch.setattr(s, "LOCK_ESPERA_S", 0.05)
    return s


def test_lock_continua_aberto_durante_as_migrations(startup, monkeypatch):
    """A REGRESSAO: o lock nao pode cair antes da primeira migration.

    Se ele cair, os dois workers rodam a lista em paralelo e o perdedor de uma
    corrida de DDL aborta a transacao inteira do arquivo — registrando falha num
    boot que deu certo."""
    diario = []
    conexoes = _instalar_psycopg2_falso(monkeypatch, roteiro=[True], diario=diario)

    def _migrations_falsas(_url):
        # No instante em que as migrations rodam, o lock TEM de estar de pe.
        assert conexoes[0].fechada is False, "o lock caiu antes das migrations"
        diario.append("rodou_migrations")

    monkeypatch.setattr(startup, "_rodar_migrations", _migrations_falsas)
    startup.run_migrations()

    # E depois de rodar, ai sim, ele e solto.
    assert diario == ["rodou_migrations", "fechou_lock"]


def test_quem_nao_pega_o_lock_espera_e_roda(startup, monkeypatch):
    """Esperar, e nao pular: worker que pula volta a servir com schema pela metade."""
    diario = []
    # Duas negativas e depois o outro worker larga o lock.
    conexoes = _instalar_psycopg2_falso(
        monkeypatch, roteiro=[False, False, True], diario=diario)
    monkeypatch.setattr(startup, "_rodar_migrations",
                        lambda _u: diario.append("rodou_migrations"))

    startup.run_migrations()

    assert diario == ["rodou_migrations", "fechou_lock"]
    # Sondou ate conseguir, em vez de desistir na primeira negativa.
    tentativas = [s for s in conexoes[0].sqls if "pg_try_advisory_lock" in s]
    assert len(tentativas) == 3


def test_lock_impossivel_nao_impede_as_migrations(startup, monkeypatch):
    """Boot sem schema e pior que boot com dois workers concorrendo.

    Estourado o teto de espera (ou caida a conexao do lock), o worker roda a lista
    assim mesmo — que e exatamente o comportamento que havia antes do lock existir.
    """
    diario = []
    # Uma unica negativa, repetida para sempre: o lock nunca e concedido.
    conexoes = _instalar_psycopg2_falso(monkeypatch, roteiro=[False], diario=diario)
    monkeypatch.setattr(startup, "_rodar_migrations",
                        lambda _u: diario.append("rodou_migrations"))

    startup.run_migrations()

    # Desistiu do lock (fechou a conexao dele) e AINDA ASSIM rodou as migrations.
    assert conexoes[0].fechada is True
    assert diario.count("rodou_migrations") == 1
    # Nao ha segunda conexao a fechar no fim: quem desiste do lock nao segura nada.
    assert diario.count("fechou_lock") == 1


def test_sem_database_url_nao_tenta_nada(startup, monkeypatch):
    """Sem banco configurado nao se abre conexao para pegar lock nenhum."""
    monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)
    monkeypatch.setenv("DATABASE_URL", "")
    chamou = []
    monkeypatch.setattr(startup, "_rodar_migrations", lambda _u: chamou.append(1))

    startup.run_migrations()

    assert chamou == []


def test_a_imutabilidade_e_a_ultima_migration_da_lista(startup):
    """Ordem que e requisito, nao arrumacao.

    `add_auditoria_imutavel.sql` instala o gatilho que RECUSA UPDATE em audit_log.
    Toda migration que ainda faz backfill na trilha (hoje add_auditoria_detalhada
    .sql, que reescreve `usuario_nome`) tem de rodar ANTES — com o gatilho no ar,
    um UPDATE de backfill derruba a migration inteira, e o runner engole o erro."""
    lista = startup.MIGRATION_FILES
    assert lista[-1] == "add_auditoria_imutavel.sql"
    assert lista.index("add_auditoria_detalhada.sql") < lista.index("add_auditoria_imutavel.sql")
