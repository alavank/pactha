"""A ARMADILHA DO REUSO: chamar um endpoint como funcao arrasta a permissao dele.

O registro de `services/registro_rotas.py` compara a rota com o que ela DECLARA.
Ele nao tem como enxergar uma exigencia que entra por dentro — e ela entra
facil, porque endpoint no FastAPI e uma funcao comum e reusar a funcao e a coisa
obvia a fazer.

⭐ O CASO MEDIDO, que este arquivo existe para nao voltar. `routers/painel.py`
montava a home do Painel chamando `municipios.municipio_summary` e
`status_changes.listar` — os dois ENDPOINTS. Os dois checam
"convenios.ver OU transferegov.ver" no corpo (a checagem certa PARA ELES: a
rota /api/municipios/{id}/summary e a home do modulo de convenios). Resultado: as
rotas de /api/painel/*, que declaram `bi.ver` e so `bi.ver`, exigiam na pratica
uma SEGUNDA permissao que nao estava declarada em lugar nenhum.

Em `AUTHZ_MODO=bloqueio` isso e o Painel do prefeito morto: a concessao honesta
para "ele ve o Painel" e `bi.ver`, e com ela /visao, /timeline e /narrativa
devolviam 403. Em silencio — o front engole no `.catch()`, como a TV do
gabinete. E nenhum teste pegava, porque cada peca, sozinha, estava certa.

A regra que fica: **o nucleo de dados nao checa e nao recebe `current`; quem
checa e a PORTA.** Cada rota declara a propria exigencia e ninguem herda
exigencia por acidente de import.

Rodar:
    python -m pytest backend/tests/test_reuso_nao_herda_permissao.py -v
"""
import asyncio
import inspect
import pathlib
import re

import pytest
from fastapi import HTTPException

from routers import painel, status_changes
from routers.municipios import municipio_summary, summary_core

ROUTERS = pathlib.Path(__file__).resolve().parent.parent / "routers"

# Os endpoints que decidem permissao DENTRO do corpo. Chamar um destes como
# funcao, de outro router, e o defeito — nao o padrao `declarado()` deles, que
# esta certo.
#
# O padrao vem escrito caso a caso porque os dois nomes nao tem o mesmo risco:
# `municipio_summary` e unico no repo, mas `listar` e o nome de meia duzia de
# endpoints (gestao, documentos, rm, auditoria...) e casar o nome cru acusaria
# todos eles. Por isso o de status_changes so casa QUALIFICADO pelo modulo — e a
# segunda linha da tupla cobre a outra porta de entrada, o `import` do nome cru,
# que e como a chamada qualificada deixaria de existir sem o defeito sumir.
ENDPOINTS_QUE_CHECAM_NO_CORPO = (
    ("municipios", "municipio_summary", "summary_core",
     (r"(?<![\w.])municipio_summary\s*\(",
      r"import\s+[^\n]*\bmunicipio_summary\b")),
    ("status_changes", "listar", "listar_core",
     (r"status_changes\.listar\s*\(",
      r"from\s+routers\.status_changes\s+import\s+[^\n]*(?<![\w])listar(?![\w])")),
)


class Prefeito:
    """A conta do dia da virada: tem o Painel, e so o Painel."""

    id = 7
    email = "prefeito@montesiao.mg.gov.br"
    name = "Prefeito"
    role = "prefeito"
    active = True
    super_admin = False
    somente_leitura = True
    kiosk = False
    allowed_municipio_ids = [1]
    allowed_telas = ["bi"]
    allowed_permissoes = ["bi.ver"]


class DbQueNuncaResponde:
    """Se a checagem deixar passar, a execucao chega aqui — e e isso que se quer
    provar. Nao ha banco neste teste, e nao precisa haver: o que se mede e se a
    trava disparou ANTES."""

    async def execute(self, *a, **kw):
        raise AssertionError("passou da checagem de permissao")


@pytest.fixture
def bloqueio(monkeypatch):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")


# ---------------------------------------------------------------------------
# 1. O nucleo nao checa — e nem tem como
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nucleo", [summary_core, status_changes.listar_core])
def test_o_nucleo_nao_recebe_usuario(nucleo):
    """Sem `current` na assinatura nao ha o que checar, e a garantia deixa de
    depender de alguem lembrar: um `authz.exigir` que aparecesse la dentro nao
    teria de quem falar."""
    assert "current" not in inspect.signature(nucleo).parameters


def test_o_nucleo_do_resumo_entrega_dado_a_quem_so_tem_bi_ver(bloqueio):
    with pytest.raises(AssertionError, match="passou da checagem"):
        asyncio.run(summary_core(DbQueNuncaResponde(), 1))


def test_o_nucleo_das_mudancas_entrega_dado_a_quem_so_tem_bi_ver(bloqueio):
    with pytest.raises(AssertionError, match="passou da checagem"):
        asyncio.run(status_changes.listar_core(DbQueNuncaResponde(), [1], 30, 8))


# ---------------------------------------------------------------------------
# 2. A PORTA continua negando — a separacao nao afrouxou nada
# ---------------------------------------------------------------------------
def test_a_rota_do_resumo_continua_exigindo_convenios_ou_transferegov(bloqueio):
    """O contrario do teste acima, e ele importa tanto quanto: mover a logica
    para um nucleo sem checagem so vale se a checagem tiver FICADO na rota."""
    with pytest.raises(HTTPException) as e:
        asyncio.run(municipio_summary(
            1, ano=None, anos=None, db=DbQueNuncaResponde(), current=Prefeito()))
    assert e.value.status_code == 403


def test_a_rota_das_mudancas_continua_exigindo_convenios_ou_transferegov(bloqueio):
    with pytest.raises(HTTPException) as e:
        asyncio.run(status_changes.listar(
            municipio_id=1, days=30, limit=8,
            db=DbQueNuncaResponde(), current=Prefeito()))
    assert e.value.status_code == 403


# ---------------------------------------------------------------------------
# 3. Ninguem volta a chamar o endpoint
# ---------------------------------------------------------------------------
# Teste de FONTE porque o defeito e de fonte: a chamada errada e sintaticamente
# identica a certa e passa em qualquer teste que use super-admin. So a leitura do
# arquivo distingue `summary_core(...)` de `municipio_summary(...)`.
@pytest.mark.parametrize("modulo,endpoint,nucleo,padroes",
                         ENDPOINTS_QUE_CHECAM_NO_CORPO)
def test_nenhum_router_chama_o_endpoint_como_funcao(modulo, endpoint, nucleo,
                                                    padroes):
    dono = ROUTERS / f"{modulo}.py"
    compilados = [re.compile(p) for p in padroes]
    culpados = []
    for arquivo in sorted(ROUTERS.glob("*.py")):
        if arquivo == dono:
            continue          # e a casa da funcao; la a chamada e a rota
        texto = arquivo.read_text(encoding="utf-8")
        # `listar_core(` nao casa com `listar(`: o `\s*\(` do padrao exige que o
        # nome termine ali. E o alias do import (`from routers import
        # status_changes as _status_changes`) nao escapa, porque o padrao casa o
        # trecho `status_changes.listar(` que sobra na chamada.
        if any(c.search(texto) for c in compilados):
            culpados.append(arquivo.name)
    assert not culpados, (
        f"{culpados} chamam `{endpoint}` como funcao e herdam a permissao que "
        f"ela checa no corpo, sem declara-la. Use `{nucleo}`.")


def test_o_painel_usa_os_nucleos():
    """O outro lado da mesma moeda: a ausencia da chamada errada nao prova que a
    certa esta la — o Painel poderia ter perdido o dado."""
    texto = (ROUTERS / "painel.py").read_text(encoding="utf-8")
    assert "summary_core(" in texto
    assert "listar_core(" in texto
    assert painel.router.prefix == "/api/painel"
