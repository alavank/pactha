"""
⚠️⚠️ A REDE QUE SEGURA O DEPLOY DE «PERMISSAO POR TELA» (05/09/2026).

O PROBLEMA QUE ELA RESOLVE
--------------------------
Duas chaves viraram dezoito: `transferegov` -> as 8 telas de FEDERAIS,
`convenios` -> as 10 de ESTADUAIS. `add_permissoes_por_tela.sql` traduz as
concessoes de todo mundo.

⚠️ MAS MIGRATION QUE FALHA NAO DERRUBA O BOOT. `services/startup.py` captura a
excecao, escreve uma linha no log e o processo segue — o `except` so trata
"already exists" como esperado, e o resto vira log. Com `AUTHZ_MODO=bloqueio`
ligado no MESMO deploy (decisao do dono), o desfecho de uma falha ali seria: API
no ar, ninguem traduzido, e todo usuario perdendo os dois maiores grupos do menu.
Em cinco prefeituras, em silencio.

E `AUTHZ_MODO=aviso` NAO SALVARIA: `ensure_tela` e da familia antiga e nega nos
DOIS modos. A valvula de escape que existe para as caixinhas nao existe para as
telas.

Entao a compatibilidade mora no CODIGO, e nao no dado. Este arquivo garante as
tres propriedades que a tornam segura:

  1. ela cobre EXATAMENTE as telas/chaves que o incremento dividiu;
  2. ela SO AMPLIA — nao ha caminho em que tire acesso de alguem;
  3. os dois lados (backend e frontend) dizem a mesma coisa.

Rodar:
    python -m pytest backend/tests/test_compat_telas_renomeadas.py -v
"""
import re
from pathlib import Path

import pytest

from services.auth import (
    TELAS_DE_ADMINISTRACAO, TELAS_RENOMEADAS, expandir_telas_legadas,
)
from services.permissoes import (
    CATALOGO, _CHAVES_RENOMEADAS, permissoes_efetivas,
)

REPO = Path(__file__).resolve().parent.parent.parent
TELAS_TS = REPO / "frontend" / "src" / "lib" / "telas.ts"


# ---------------------------------------------------------------------------
# 1. A rede cobre o que o incremento dividiu
# ---------------------------------------------------------------------------
def test_quem_tinha_transferegov_alcanca_as_oito_telas():
    telas = expandir_telas_legadas({"transferegov"})
    assert "transferegov_geral" in telas
    assert "transferegov_pac" in telas
    assert len(telas) == 9  # a antiga + as oito novas


def test_quem_tinha_convenios_alcanca_as_dez():
    telas = expandir_telas_legadas({"convenios"})
    assert "repasses" in telas and "tce_rs" in telas
    # `convenios` continua sendo tela; ganha as oito irmas.
    assert "convenios" in telas and len(telas) == 9


def test_quem_tinha_a_trilha_alcanca_a_telemetria():
    assert "telemetria" in expandir_telas_legadas({"auditoria"})


def test_toda_tela_de_destino_existe_no_catalogo_do_frontend():
    """Traduzir para uma tela que nao existe seria conceder o nada."""
    if not TELAS_TS.exists():
        pytest.skip("frontend nao esta neste checkout")
    validas = set(re.findall(r'key:\s*"([a-z_]+)"', TELAS_TS.read_text(encoding="utf-8")))
    for antiga, novas in TELAS_RENOMEADAS.items():
        for nova in novas:
            assert nova in validas, f"{antiga} -> {nova} nao existe em telas.ts"


def test_toda_chave_de_destino_existe_no_catalogo_de_permissoes():
    for antiga, novas in _CHAVES_RENOMEADAS.items():
        for nova in novas:
            assert nova in CATALOGO, f"{antiga} -> {nova} nao existe no catalogo"


# ---------------------------------------------------------------------------
# 2. A rede SO AMPLIA
# ---------------------------------------------------------------------------
def test_expandir_e_idempotente():
    """Rodar sobre um conjunto ja traduzido nao pode mudar nada — e o caso do
    dia seguinte, quando a migration ja gravou as chaves novas."""
    uma = expandir_telas_legadas({"transferegov", "convenios"})
    assert expandir_telas_legadas(uma) == uma


def test_expandir_nunca_tira_tela():
    entrada = {"transferegov", "rm", "gestao", "cofre"}
    saida = expandir_telas_legadas(entrada)
    assert entrada <= saida


# ---------------------------------------------------------------------------
# 2b. A rede das ABAS DE ADMINISTRACAO — a que nasceu do defeito em producao
# ---------------------------------------------------------------------------
def test_admin_volta_a_abrir_as_tres_abas_de_administracao():
    """⚠️ MEDIDO NO FREITAS EM 05/09/2026: a migration que gravaria a linha
    (`add_permissoes_por_tela.sql`, parte 2) nao rodou, e todo `role='admin'`
    nao-super ficou com a aba Usuarios VISIVEL e a tela devolvendo 403 — a unica
    tela que conserta permissao era a que ninguem conseguia abrir."""
    assert TELAS_DE_ADMINISTRACAO <= expandir_telas_legadas(set(), "admin")
    assert TELAS_DE_ADMINISTRACAO <= expandir_telas_legadas({"rm"}, "ADMIN")


def test_a_rede_de_administracao_alcanca_SO_o_papel_admin():
    """⚠️ A PROPRIEDADE QUE A IMPEDE DE VIRAR O DEUS POR DEFAULT que o
    Incremento 4 matou. Ela restaura o que o PAPEL abria na vespera — tres
    telas, nominais — e nada alem."""
    for papel in ("usuario", "prefeito", "analyst", "viewer", ""):
        assert expandir_telas_legadas({"rm"}, papel) == {"rm"}, papel


def test_o_admin_nao_ganha_o_produto_por_ser_admin():
    """Um admin sem linha nenhuma continua sem Cofre, sem Convenios, sem as
    telas de dado. A rede e nominal e curta de proposito."""
    telas = expandir_telas_legadas(set(), "admin")
    assert telas == set(TELAS_DE_ADMINISTRACAO)
    for proibida in ("cofre", "convenios", "sessoes", "auditoria", "bi"):
        assert proibida not in telas, proibida


def test_quem_nao_tem_a_chave_antiga_nao_ganha_nada():
    """⚠️ A propriedade que impede a rede de virar concessao: ela e disparada
    pela chave ANTIGA, e por nada mais."""
    assert expandir_telas_legadas({"rm", "gestao"}) == {"rm", "gestao"}
    assert permissoes_efetivas(concedidas={"rm.ver"}) == frozenset({"rm.ver"})


def test_a_expansao_de_acao_nao_inventa_escrita():
    """Quem tinha `transferegov.ver` ganha os oito `ver` — e NENHUM `exportar`.
    Traduzir leitura em escrita seria escalonamento por migration."""
    efetivas = permissoes_efetivas(concedidas={"transferegov.ver"})
    assert "transferegov_geral.ver" in efetivas
    assert not any(c.endswith(".exportar") for c in efetivas)


def test_o_exportar_antigo_traduz_so_para_quem_exporta():
    efetivas = permissoes_efetivas(concedidas={"transferegov.exportar"})
    assert "transferegov_geral.exportar" in efetivas
    # PAC, CNPJ e Radar nao tem rota de exportacao — e nao ganham chave que nao
    # existe (ela seria descartada pelo filtro do catalogo, mas o mapa nao deve
    # sequer tentar).
    assert "transferegov_pac.exportar" not in efetivas
    assert "transferegov_cnpj.exportar" not in efetivas


def test_conta_desativada_continua_sem_nada():
    """A rede entra DEPOIS das regras de corte da funcao pura, e nao antes."""
    assert permissoes_efetivas(concedidas={"transferegov.ver"}, ativo=False) == frozenset()


# ---------------------------------------------------------------------------
# 3. Os dois lados dizem a mesma coisa
# ---------------------------------------------------------------------------
def test_o_frontend_espelha_o_mapa_do_backend():
    """O menu (frontend) e o `ensure_tela` (backend) tem de concordar. Divergir
    aqui produz o pior par possivel: o backend libera e a tela esconde — sem
    erro nenhum para investigar."""
    if not TELAS_TS.exists():
        pytest.skip("frontend nao esta neste checkout")
    fonte = TELAS_TS.read_text(encoding="utf-8")
    bloco = fonte[fonte.index("export const TELAS_RENOMEADAS"):]
    bloco = bloco[:bloco.index("};")]
    do_front: dict = {}
    for antiga, corpo in re.findall(r"(\w+):\s*\[([^\]]*)\]", bloco):
        do_front[antiga] = set(re.findall(r'"([a-z_]+)"', corpo))
    do_back = {a: set(n) for a, n in TELAS_RENOMEADAS.items()}
    assert do_front == do_back, (
        f"telas.ts diz {do_front} e services/auth.py diz {do_back}")
