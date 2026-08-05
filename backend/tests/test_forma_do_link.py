"""A forma do link de TV: criar e listar têm de devolver O MESMO objeto.

O DEFEITO QUE ESTE ARQUIVO EXISTE PARA IMPEDIR (visto em produção, 04/08/2026)
-----------------------------------------------------------------------------
`POST /api/bi/tela-links` devolvia `{slug, caminho, kind, dias}` e
`GET /api/bi/tela-links` devolvia sete campos. A tela insere o item devolvido
pelo POST direto na lista, sem recarregar — então o link recém-criado aparecia
como "Sem destinatário" e "Sem prazo — vale até você revogar", com o nome e a
validade certos guardados no banco o tempo todo.

⚠️ E o pior desse defeito é ele se consertar sozinho: bastava fechar e reabrir o
modal. Quem vê conclui que o sistema perdeu o que digitou — e depois que ele
"volta", conclui que o sistema é errático. Nenhum erro aparece em log nenhum.

A causa não foi distração: eram DOIS dicionários montados à mão, um em cada
rota. Enquanto forem dois, voltam a divergir no próximo campo. Por isso a forma
virou `_link_para_api`, e é ela que estes testes prendem.
"""
from datetime import datetime, timedelta, timezone

import pytest

from routers.bi import _link_para_api

AGORA = datetime(2026, 8, 4, 2, 30, tzinfo=timezone.utc)

# Os campos que a tela lê. Tirar um daqui é quebrar a tela; acrescentar sem
# passar pela função é reabrir a porta do defeito.
CAMPOS = {"slug", "caminho", "kind", "nome", "criado_em", "expira_em",
          "revogado", "ultimo_acesso",
          # Cidade em que o link foi FIXADO (None = segue o dono). A lista mostra
          # "Cidade · Modo" e a previa de WhatsApp cita a cidade — sem isso, uma
          # assessoria com 50 links nao distingue um do outro.
          "cidade"}


def _criacao(**troca):
    base = dict(slug="abc123", nome="Secretário de Saúde", criado_em=AGORA,
                expira_em=AGORA + timedelta(days=30), revogado=False,
                ultimo_acesso=None, kind="tela")
    base.update(troca)
    return base


def test_criar_e_listar_devolvem_os_mesmos_campos():
    """⭐ O teste que teria pego o defeito.

    `dias` é o único extra da criação, e de propósito: é o prazo PEDIDO, que
    serve para a tela confirmar o que acabou de acontecer. Fora ele, as duas
    respostas são o mesmo objeto."""
    d = _criacao()
    criado = _link_para_api(**d, dias=30)
    listado = _link_para_api(**d)
    assert set(listado) == CAMPOS
    assert set(criado) == CAMPOS | {"dias"}
    for campo in CAMPOS:
        assert criado[campo] == listado[campo], f"divergiram em {campo}"


def test_o_nome_e_a_validade_sobrevivem_a_criacao():
    """O sintoma exato do print: nome e prazo presentes na resposta do POST."""
    ficha = _link_para_api(**_criacao(), dias=30)
    assert ficha["nome"] == "Secretário de Saúde"
    assert ficha["expira_em"] == "2026-09-03T02:30:00+00:00"
    assert ficha["criado_em"] == "2026-08-04T02:30:00+00:00"


def test_sem_prazo_continua_sendo_nulo_e_nao_some():
    """Link sem prazo é `expira_em: None` — e o campo PRECISA vir, senão a tela
    não distingue "sem prazo" de "não sei", que são frases diferentes."""
    ficha = _link_para_api(**_criacao(expira_em=None), dias=None)
    assert "expira_em" in ficha and ficha["expira_em"] is None
    assert "dias" not in ficha  # `dias=None` não inventa campo na listagem


def test_sem_destinatario_e_nome_nulo_e_nao_string_vazia():
    """A tela decide a frase "Sem destinatário" pelo nulo. String vazia passaria
    pelo `if` e imprimiria um rótulo em branco."""
    assert _link_para_api(**_criacao(nome=None))["nome"] is None


@pytest.mark.parametrize("kind,prefixo", [("tela", "/t/"), ("mobile", "/m/")])
def test_o_caminho_segue_o_tipo(kind, prefixo):
    """TV e celular são endereços diferentes — e é o que separa um link do
    outro quando o gestor pede "os dois" e recebe duas linhas na lista."""
    ficha = _link_para_api(**_criacao(kind=kind))
    assert ficha["caminho"].startswith(prefixo)
    assert ficha["kind"] == kind


def test_kind_ausente_vira_tela_nas_duas_rotas():
    """Linha antiga, gravada antes de o tipo existir, é TV — e não pode virar
    `None` num lado e `"tela"` no outro."""
    assert _link_para_api(**_criacao(kind=None))["kind"] == "tela"


def test_revogado_e_sempre_booleano():
    """O banco devolve bool, mas a criação passa um literal. `None` viraria
    `false` no JSON e ninguém notaria — melhor a conversão ser explícita."""
    assert _link_para_api(**_criacao(revogado=None))["revogado"] is False
    assert _link_para_api(**_criacao(revogado=True))["revogado"] is True
