"""
Garantias do catalogo didatico (services/audit_catalog.py).

Rodar (pytest e dev-only, nao esta no requirements.txt da imagem):
    pip install pytest
    python -m pytest backend/tests/test_audit_catalog.py -v

O que estes testes protegem, em ordem de importancia:
  1. acao DESCONHECIDA nunca engasga - a trilha nao pode sumir por falta de rotulo;
  2. toda chave que o repo REALMENTE grava tem traducao (se alguem acrescentar
     um log_event com chave nova e esquecer do catalogo, cai na derivacao, mas o
     teste 2 avisa quando a chave ja existente perde o rotulo);
  3. a frase nunca sai pendurada numa preposicao sem alvo.
"""
import pytest

from services import audit_catalog as ac


# Todas as chaves que o repo REALMENTE grava, levantadas com
#   grep -rhoE 'action=(f?"[^"]+")' --include=*.py backend/ | sort -u
# Manter esta lista colada no grep: chave gravada que nao esta aqui e chave que
# ninguem percebe ter perdido a traducao.
CHAVES_DO_REPO = [
    "login.success", "login.fail", "login.disabled_user", "logout", "sso.login",
    "user.password_change.success", "user.password_change.fail",
    "user.create", "user.update", "user.reset_password",
    # A concessao de permissao por ACAO (routers/permissoes.py::conceder).
    "usuarios.conceder",
    "cofre.reveal", "cofre.create", "cofre.update", "cofre.delete",
    "session.create", "session.update",
    "service_token.create", "service_token.rotate", "service_token.revoke",
    "control.municipio.upsert", "control.municipio.patch", "control.refresh",
    "control.cofre.create", "control.cofre.patch", "control.cofre.reveal",
    "control.cofre.delete", "control.session_token.create",
    "control.session_token.rotate", "control.sso.mint",
    "control.user.create", "control.user.patch", "control.user.reset_password",
    "control.user.delete",
    # `auditoria.poda` (sem R) e gravada pela funcao audit_log_podar DO BANCO —
    # nao aparece num grep por `action=` no Python, so no .sql da migration.
    "auditoria.exportar", "auditoria.podar", "auditoria.poda",
    "auditoria.verificar_integridade",
    "export.rm", "rm.update", "rm.delete", "rm.auto_popular", "rm.config_rodape",
    # Chegaram com as pecas de cobertura (bi/convenios/documentos/gestao/
    # export_pdf) DEPOIS da primeira varredura deste catalogo.
    "bi.tela_link.create", "bi.tela_link.revoke",
    "coletor.disparo",
    "documento.create", "documento.update", "documento.delete",
    "export.documento", "export.gestao_anexo",
    "export.convenios", "export.voluntarias", "export.plano_acao",
    "export.emendas", "export.dou", "export.parlamentares",
    "export.ia_relatorio", "export.ia",
    "gestao.anotacao.create", "gestao.anotacao.update", "gestao.anotacao.delete",
    # Alcance por linha (Incremento 6): a passagem de quem esta restrito a
    # "somente os que ele criou" numa linha sem criador conhecido.
    "authz.sem_criador",
]

# Todo `target_type=` que o repo grava. O que faltar aqui sai na frase como
# snake_case desmontado ("bi tela link"), que nao e nome de coisa nenhuma.
TARGET_TYPES_DO_REPO = [
    "audit_log", "bi_tela_link", "cofre_senha", "cofre_session", "documento",
    "export", "gestao_anotacao", "municipio", "rm", "scraper", "service_token",
    "user",
    # services/authz.py: os alvos que a trava grava quando nega.
    "linha", "linha_propria", "permissao", "tela",
]


@pytest.mark.parametrize("chave", CHAVES_DO_REPO)
def test_chave_real_tem_traducao(chave):
    acao = ac.descrever_acao(chave)
    assert acao.conhecida, f"{chave} caiu na derivacao - falta cadastrar"
    assert acao.modulo in ac.MODULOS
    assert acao.risco in ac.RISCOS


@pytest.mark.parametrize("lixo", [None, "", "   ", ".", "...", "xpto",
                                  "acao.que.ninguem.cadastrou", "NAV.VIEW",
                                  "ação com espaço", "a" * 300])
def test_acao_desconhecida_nunca_engasga(lixo):
    """Requisito duro: auditoria jamais falha por falta de rotulo."""
    acao = ac.descrever_acao(lixo)
    assert acao.fragmento.strip()
    assert acao.modulo in ac.MODULOS
    assert acao.risco in ac.RISCOS
    frase = ac.frase_didatica(lixo, "Maria Silva", ac.alvo_legivel(lixo))
    assert frase.startswith("Maria Silva")


def test_desconhecida_nao_nasce_baixo_risco():
    """Ninguem classificou: nao pode parecer inofensiva."""
    assert ac.descrever_acao("modulo_novo.acao_nova").risco == ac.RISCO_MEDIO


def test_frase_do_enunciado():
    assert (ac.frase_didatica("cofre.reveal", "Maria Silva", "gov.br")
            == "Maria Silva revelou a senha de gov.br")


def test_frase_sem_alvo_nao_fica_pendurada():
    """Sem alvo, a preposicao some - nada de 'revelou a senha de'."""
    for chave, acao in ac.CATALOGO.items():
        frase = ac.frase_didatica(chave, "Maria")
        assert not frase.endswith((" de", " para", " em", " chamado", " —")), chave


def test_acao_sobre_o_proprio_ator_ignora_alvo():
    """login/logout/troca da propria senha nao repetem o e-mail no fim."""
    frase = ac.frase_didatica("logout", "maria@x.com", "maria@x.com")
    assert frase == "maria@x.com saiu do sistema"


def test_alvo_vem_do_details_e_nunca_do_token_da_central():
    """`details.token` e o ATOR (nome do token da Central), nao o alvo."""
    alvo = ac.alvo_legivel("control.user.patch", "user", "joao@x",
                           {"token": "central-prod"})
    assert alvo == "joao@x"


def test_navegacao_traduz_a_tela_nos_dois_desenhos():
    # tela em details
    assert ac.alvo_legivel("nav.view", "tela", None, {"tela": "cofre"}) == "Cofre de Senhas"
    # tela na propria chave
    assert ac.alvo_legivel("nav.dashboard") == "Dashboard"
    assert ac.descrever_acao("nav.dashboard").fragmento == "acessou a tela"
    assert ac.descrever_acao("nav.dashboard").risco == ac.RISCO_BAIXO


def test_riscos_altos_sao_os_que_o_dono_listou():
    for chave in ("cofre.reveal", "control.cofre.reveal", "cofre.delete",
                  "user.update", "user.create", "user.reset_password",
                  "usuarios.conceder",
                  "auditoria.exportar", "auditoria.podar", "auditoria.poda",
                  "session.create",
                  "service_token.create", "control.sso.mint"):
        assert ac.descrever_acao(chave).risco == ac.RISCO_ALTO, chave


def test_catalogo_para_api_e_serializavel_e_traz_o_filtro():
    import json

    payload = ac.catalogo_para_api()
    json.dumps(payload, ensure_ascii=False)  # nao levanta
    assert payload["modulos"] == ac.MODULOS
    assert {r["valor"] for r in payload["riscos"]} == set(ac.RISCOS)
    assert len(payload["acoes"]) == len(ac.CATALOGO)


def test_filtro_por_modulo_cobre_chave_exata_e_prefixo():
    """O filtro da tela precisa dos dois: prefixo pega chave nova, lista exata
    pega chave cujo prefixo mora em outro modulo (control.* e Suporte)."""
    assert "control.cofre.reveal" in ac.chaves_do_modulo(ac.MOD_SUPORTE)
    assert "control" in ac.prefixos_do_modulo(ac.MOD_SUPORTE)
    assert "cofre.reveal" in ac.chaves_do_modulo(ac.MOD_COFRE)
    assert "cofre" in ac.prefixos_do_modulo(ac.MOD_COFRE)


@pytest.mark.parametrize("tipo", TARGET_TYPES_DO_REPO)
def test_target_type_real_tem_rotulo(tipo):
    assert tipo in ac._TARGET_TYPE_ROTULOS, f"{tipo} sairia como snake_case cru"


def test_link_publico_do_painel_nao_vira_criacao_de_painel():
    """A derivacao pelo prefixo 'bi' + sufixo 'create' dizia 'criou um painel de
    indicadores', risco medio. O ato PUBLICA o painel sem login: e alto, e a
    frase tem de dizer o que aconteceu."""
    acao = ac.descrever_acao("bi.tela_link.create")
    assert acao.risco == ac.RISCO_ALTO
    assert "público" in acao.fragmento and "sem login" in acao.fragmento


def test_alvo_que_e_codigo_do_dominio_sai_traduzido():
    """`target_id` 'sigcon' e codigo de banco, nao nome de fonte."""
    assert ac.alvo_legivel("coletor.disparo", "scraper", "sigcon",
                           {"fonte": "sigcon"}) == "SIGCON-MG"


def test_detalhe_booleano_nao_vira_alvo():
    """bool e subclasse de int: sem guarda, a frase terminava em 'True'."""
    assert ac.alvo_legivel("cofre.update", "cofre_senha", 42,
                           {"source": True}) == "#42"


def test_troca_da_propria_senha_nao_conta_como_permissao():
    """`user.` mapeia para Usuarios, mas `user.password_change.*` mora em Acesso:
    sem a lista de excecoes o filtro de permissoes vem inflado."""
    excecoes = ac.excecoes_do_modulo(ac.MOD_USUARIOS)
    assert "user.password_change.success" in excecoes
    assert "user.password_change.fail" in excecoes
    assert "user.create" not in excecoes


def test_rotulo_de_tela_bate_com_o_menu_do_frontend():
    """Chave do frontend que o telas_catalog.py exclui de proposito: o rotulo
    tem de ser o MESMO de frontend/src/lib/telas.ts, senao a auditoria nomeia
    uma tela que nao existe no menu."""
    assert ac.rotulo_tela("bi_link") == "Gerar link público da TV"
    assert ac.rotulo_tela("cofre") == "Cofre de Senhas"
    assert ac.rotulo_tela("sessoes") == "Sessões (gov.br)"


def test_cache_de_derivacao_tem_teto():
    """Cache que so cresce dentro do worker e vazamento de memoria."""
    antes = dict(ac._DERIVADAS)
    try:
        ac._DERIVADAS.clear()
        for i in range(ac._DERIVADAS_MAX + 50):
            ac.descrever_acao(f"lixo.{i}")
        assert len(ac._DERIVADAS) <= ac._DERIVADAS_MAX
        # Estourado o teto, a traducao continua saindo — so nao e guardada.
        assert ac.descrever_acao("lixo.999999").fragmento.strip()
    finally:
        ac._DERIVADAS.clear()
        ac._DERIVADAS.update(antes)


def test_entrada_do_catalogo_e_imutavel():
    """Cacheada e compartilhada: se um consumidor mutasse, contaminaria os outros."""
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        ac.descrever_acao("cofre.reveal").fragmento = "outra coisa"
