""""Nenhum dado encontrado" tinha TRES causas e a tela dizia uma so.

Quando um municipio nao mostra convenio estadual, isso pode ser:
  (a) nao ha credencial do SIGCON no Cofre para ele,
  (b) ha credencial e ela foi recusada,
  (c) a coleta rodou e o municipio nao tem convenio mesmo.

O cliente lia sempre como (c). E as duas primeiras sao pendencias ACIONAVEIS,
com um lugar exato para resolver — Configuracoes -> Cofre de Senhas.

⚠️ O estado (a) e MUDO por construcao: sem credencial o coletor nunca toca o
municipio, entao nao existe linha em `scraper_municipio_coleta` e o selo
"Atualizado em" nao tem o que mostrar. Era o unico dos tres SEM nenhum sinal.

O padrao copiado e o do InvestSUS (`routers/investsus.py`), que ja devolve o
estado da credencial e manda o usuario para o Cofre.
"""
import os

from services.coleta import (FRASE_CREDENCIAL, _teto_login,
                             classificar_credencial)


def test_sem_credencial_no_cofre():
    assert classificar_credencial(0, 0, False) == "sem_credencial"
    # e nao muda de ideia por causa de tentativa nenhuma: sem credencial, o
    # coletor nunca chegou a tentar
    assert classificar_credencial(0, 9, True) == "sem_credencial"


def test_credencial_recusada_mas_ainda_na_fila():
    assert classificar_credencial(1, 1, True, teto=3) == "recusada"
    assert classificar_credencial(1, 2, True, teto=3) == "recusada"


def test_recusada_seguidas_vezes_sai_da_fila():
    """No teto, o coletor para de tentar — e a tela precisa dizer isso, senao o
    municipio some da coleta em silencio."""
    assert classificar_credencial(1, 3, True, teto=3) == "fora_da_fila"
    assert classificar_credencial(1, 7, True, teto=3) == "fora_da_fila"


def test_coletado_e_realmente_vazio():
    """O terceiro estado, o unico que a tela dizia. Sem erro de login, a
    credencial esta OK e o vazio e a resposta do portal."""
    assert classificar_credencial(1, 0, False) == "ok"


def test_credencial_nova_que_ainda_nao_foi_coletada():
    """⚠️ O QUARTO estado, que quase passou batido. Sem ele, quem acabou de
    cadastrar a senha ve "Nenhum dado encontrado" e conclui que ela nao
    funcionou — quando so falta a proxima rodada do rodizio."""
    assert classificar_credencial(1, 0, False, houve_coleta=False) == "sem_coleta"


def test_o_quarto_estado_nao_encobre_a_recusa():
    """Se ja houve recusa, "ainda nao coletou" seria a mensagem errada: a ordem
    dos ramos poe a recusa antes."""
    assert classificar_credencial(1, 2, True, teto=3, houve_coleta=False) == "recusada"


def test_QUEDA_DO_PORTAL_NAO_ACUSA_A_SENHA():
    """⚠️ O ponto mais importante desta regra. Timeout de rede, portal fora do ar
    e erro de parsing NAO sao culpa da credencial. Mandar o cliente trocar uma
    senha que esta certa e pior do que nao avisar nada — ele mexe no que
    funciona e o problema continua."""
    assert classificar_credencial(1, 5, erro_de_login=False) == "ok"


def test_todo_estado_tem_frase_e_so_o_ok_e_mudo():
    """Estado sem frase seria um vazio novo, do mesmo tipo que este conserto
    veio eliminar."""
    for estado in ("sem_credencial", "recusada", "fora_da_fila"):
        assert FRASE_CREDENCIAL[estado].strip(), estado
        assert "Cofre de Senhas" in FRASE_CREDENCIAL[estado], \
            f"{estado}: a frase precisa dizer ONDE resolver"
    assert FRASE_CREDENCIAL["ok"] == ""
    # ⚠️ 'sem_coleta' e o unico em que a acao certa e ESPERAR. Mandar conferir a
    # senha aqui faria o cliente trocar uma credencial que nem foi usada ainda.
    assert FRASE_CREDENCIAL["sem_coleta"].strip()
    assert "Cofre de Senhas" not in FRASE_CREDENCIAL["sem_coleta"]


def test_todo_estado_da_funcao_tem_frase():
    """Estado sem frase seria um vazio novo, do mesmo tipo que este conserto veio
    eliminar. Este teste quebra quando alguem acrescentar um estado e esquecer."""
    possiveis = {
        classificar_credencial(0, 0, False),
        classificar_credencial(1, 1, True, teto=3),
        classificar_credencial(1, 3, True, teto=3),
        classificar_credencial(1, 0, False, houve_coleta=False),
        classificar_credencial(1, 0, False),
    }
    assert possiveis <= set(FRASE_CREDENCIAL), \
        f"estado sem frase: {possiveis - set(FRASE_CREDENCIAL)}"


def test_a_frase_nao_manda_trocar_senha_quando_nao_ha_senha():
    """'sem_credencial' e 'recusada' pedem coisas diferentes: cadastrar x
    conferir. Trocar as frases mandaria o cliente procurar o que nao existe."""
    assert "cadastre" in FRASE_CREDENCIAL["sem_credencial"].lower()
    assert "confira" in FRASE_CREDENCIAL["recusada"].lower()


def test_o_teto_acompanha_o_do_coletor():
    """Mesma env e mesmo default. ⚠️ A env e do WORKER e a API pode nao te-la:
    no pior caso a tela diz "recusada" onde o coletor ja diz "fora da fila" —
    muda a PALAVRA, nunca se o aviso aparece."""
    assert _teto_login() >= 1
    antes = os.environ.get("SIGCON_MAX_TENTATIVAS_LOGIN")
    try:
        os.environ["SIGCON_MAX_TENTATIVAS_LOGIN"] = "5"
        assert _teto_login() == 5
        os.environ["SIGCON_MAX_TENTATIVAS_LOGIN"] = "lixo"
        assert _teto_login() == 3, "env invalida nao pode derrubar a classificacao"
        os.environ["SIGCON_MAX_TENTATIVAS_LOGIN"] = "0"
        assert _teto_login() == 1, "teto zero faria todo municipio nascer fora da fila"
    finally:
        if antes is None:
            os.environ.pop("SIGCON_MAX_TENTATIVAS_LOGIN", None)
        else:
            os.environ["SIGCON_MAX_TENTATIVAS_LOGIN"] = antes


def test_o_schema_nasce_em_ok():
    """⚠️ DEFAULT 'ok' de proposito: sem `municipio_id` nao ha o que classificar,
    e a tela agregada nao pode passar a mostrar aviso de credencial."""
    from schemas.convenio import ConvenioListResponse
    r = ConvenioListResponse(items=[], total=0, page=1, per_page=20, pages=1)
    assert r.credencial == "ok"
    assert r.credencial_aviso == ""
