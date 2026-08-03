"""
A conferencia da corrente de selos da trilha (services/audit_integridade.py).

⚠️ NAO HA POSTGRES AQUI. Estes testes exercitam o NUCLEO PURO — a classe que
percorre a corrente — e os textos que a tela mostra. E de proposito que esse
nucleo nao conhece banco: o que ele decide ("a trilha esta intacta ou nao") e a
unica coisa neste incremento que nao pode estar errada, e uma decisao que so da
para testar com Postgres na frente e uma decisao que ninguem testa.

O que estes testes protegem, em ordem de importancia:

  1. ALARME FALSO. Uma conferencia que grita "trilha adulterada" numa trilha
     intacta e pior do que nao ter conferencia: ensina o auditor a ignorar o
     alarme. Por isso ha caso para selo em MAIUSCULA, para CHAR(64) com espaco
     a direita e para os tres formatos possiveis de genese.
  2. ALARME QUE NAO TOCA. Conteudo editado, linha apagada do meio e linha sem
     selo TEM de parar a conferencia e apontar a PRIMEIRA divergencia.
  3. A EMENDA entre dois lotes e entre duas chamadas. E o ponto onde uma
     remocao passaria despercebida se o percurso recomecasse "do zero".
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from services import audit_integridade as ai


AGORA = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)


def _selo(n: int) -> str:
    """Selo de mentira, mas com a FORMA do real (64 hex minusculos)."""
    return f"{n:064x}"


def _corrente(quantidade: int, *, genese: str = "", calcular: bool = True):
    """Corrente intacta de `quantidade` linhas, ids 1..n."""
    linhas = []
    anterior = genese
    for i in range(1, quantidade + 1):
        atual = _selo(i)
        linhas.append(ai.Linha(
            id=i, created_at=AGORA + timedelta(minutes=i), hash_anterior=anterior,
            selo=atual, selo_calculado=atual if calcular else None,
            action="login.success",
        ))
        anterior = atual
    return linhas


def _conferir(linhas, **kw):
    kw.setdefault("inicio_absoluto", True)
    conf = ai.Conferencia(**kw)
    conf.processar(linhas)
    return conf


# ---------------------------------------------------------------------------
# 1. Corrente intacta — nenhum alarme falso
# ---------------------------------------------------------------------------
def test_corrente_intacta_nao_acusa_nada():
    conf = _conferir(_corrente(50))
    assert conf.integra
    assert conf.conferidos == 50
    assert (conf.primeiro_id, conf.ultimo_id) == (1, 50)
    assert conf.observacoes == []


@pytest.mark.parametrize("genese", ["", None, "0" * 64])
def test_genese_aceita_as_tres_representacoes(genese):
    """A migration pode gravar a primeira linha com NULL, '' ou 64 zeros. As
    tres querem dizer a mesma coisa — "nao ha linha anterior" — e nenhuma pode
    virar acusacao."""
    linhas = _corrente(3)
    primeira = linhas[0]
    linhas[0] = ai.Linha(id=primeira.id, created_at=primeira.created_at,
                         hash_anterior=genese, selo=primeira.selo,
                         selo_calculado=primeira.selo_calculado)
    conf = _conferir(linhas)
    assert conf.integra
    assert conf.observacoes == []


def test_selo_em_maiuscula_e_char64_com_espaco_nao_e_divergencia():
    """CHAR(64) volta com espaco a direita quando o valor e mais curto, e nada
    obriga a funcao do banco a devolver hex minusculo. Comparar selo cru faria
    "trilha adulterada" aparecer por diferenca de caixa."""
    a, b = _selo(1), _selo(2)
    linhas = [
        ai.Linha(id=1, created_at=AGORA, hash_anterior="", selo=a.upper(),
                 selo_calculado=a + "   "),
        ai.Linha(id=2, created_at=AGORA, hash_anterior=a + " ", selo=b,
                 selo_calculado=b.upper()),
    ]
    assert _conferir(linhas).integra


# ---------------------------------------------------------------------------
# 2. Os tres achados
# ---------------------------------------------------------------------------
def test_conteudo_editado_e_apontado_na_linha_certa():
    linhas = _corrente(10)
    alvo = linhas[6]                       # id 7
    linhas[6] = ai.Linha(id=alvo.id, created_at=alvo.created_at,
                         hash_anterior=alvo.hash_anterior, selo=alvo.selo,
                         selo_calculado=_selo(999))   # recalculo nao bate
    conf = _conferir(linhas)
    assert not conf.integra
    assert conf.divergencia.tipo == ai.TIPO_CONTEUDO
    assert conf.divergencia.id == 7
    # Para no primeiro achado: as 3 linhas seguintes nao entram na contagem.
    assert conf.conferidos == 6


def test_linha_apagada_do_meio_quebra_o_elo():
    linhas = _corrente(10)
    del linhas[4]                          # some a linha de id 5
    conf = _conferir(linhas)
    assert conf.divergencia.tipo == ai.TIPO_ELO
    assert conf.divergencia.id == 6        # a primeira que nao encaixa
    assert conf.divergencia.id_anterior == 4


def test_linhas_reordenadas_quebram_o_elo():
    linhas = _corrente(6)
    linhas[2], linhas[3] = linhas[3], linhas[2]
    assert _conferir(linhas).divergencia.tipo == ai.TIPO_ELO


@pytest.mark.parametrize("vazio", [None, "", "    "])
def test_linha_sem_selo_e_denunciada(vazio):
    """Linha gravada com o gatilho desligado (ou nao alcancada pela conversao).
    Nao pode ser confundida com linha intacta."""
    linhas = _corrente(4)
    alvo = linhas[2]
    linhas[2] = ai.Linha(id=alvo.id, created_at=alvo.created_at,
                         hash_anterior=alvo.hash_anterior, selo=vazio,
                         selo_calculado=alvo.selo_calculado)
    conf = _conferir(linhas)
    assert conf.divergencia.tipo == ai.TIPO_SEM_SELO
    assert conf.divergencia.id == 3


def test_recalculo_vazio_e_divergencia_e_nao_modo_degradado():
    """`None` em selo_calculado = "nao recalculei" (modo somente_elo). String
    vazia = "recalculei e deu nada", que e divergencia. Tratar os dois igual
    faria um erro da funcao do banco virar trilha aprovada."""
    linhas = _corrente(2)
    alvo = linhas[1]
    linhas[1] = ai.Linha(id=alvo.id, created_at=alvo.created_at,
                         hash_anterior=alvo.hash_anterior, selo=alvo.selo,
                         selo_calculado="")
    assert _conferir(linhas).divergencia.tipo == ai.TIPO_CONTEUDO


def test_primeira_divergencia_vence_as_seguintes():
    """Depois que a corrente quebra, tudo que vem depois e consequencia. A
    resposta tem de apontar a PRIMEIRA — listar as derivadas esconderia a que
    importa."""
    linhas = _corrente(9)
    for i in (3, 5, 7):
        alvo = linhas[i]
        linhas[i] = ai.Linha(id=alvo.id, created_at=alvo.created_at,
                             hash_anterior=alvo.hash_anterior, selo=alvo.selo,
                             selo_calculado=_selo(500 + i))
    assert _conferir(linhas).divergencia.id == 4


# ---------------------------------------------------------------------------
# 3. Emendas: entre lotes e entre chamadas
# ---------------------------------------------------------------------------
def test_lotes_dao_o_mesmo_resultado_que_uma_passada_so():
    linhas = _corrente(30)
    del linhas[19]                         # some a linha 20

    inteiro = _conferir(linhas)
    partido = ai.Conferencia(inicio_absoluto=True)
    for i in range(0, len(linhas), 7):     # lotes de 7, a emenda cai no meio
        if not partido.processar(linhas[i:i + 7]):
            break

    assert partido.divergencia.tipo == inteiro.divergencia.tipo
    assert partido.divergencia.id == inteiro.divergencia.id
    assert partido.conferidos == inteiro.conferidos


def test_continuacao_ancorada_confere_a_emenda():
    """Continuar do registro N sem levar o selo dele deixaria exatamente uma
    remocao (a da emenda) invisivel."""
    linhas = _corrente(20)
    segunda_metade = linhas[10:]

    ok = _conferir(segunda_metade, inicio_absoluto=False,
                   selo_ancora=linhas[9].selo)
    assert ok.integra and ok.conferidos == 10

    ruim = _conferir(segunda_metade, inicio_absoluto=False,
                     selo_ancora=_selo(4242))
    assert ruim.divergencia.tipo == ai.TIPO_ELO
    assert ruim.divergencia.id == 11
    assert ruim.conferidos == 0


def test_comeco_no_meio_sem_ancora_nao_inventa_divergencia():
    """Sem selo de ancora nao ha o que comparar na primeira linha; a conferencia
    segue e o resultado e honesto sobre o trecho que cobriu."""
    conf = _conferir(_corrente(20)[10:], inicio_absoluto=False)
    assert conf.integra and conf.conferidos == 10


def test_primeira_linha_apontando_para_anterior_vira_observacao_e_nao_alarme():
    """Se as linhas mais antigas foram podadas, a que sobrou aponta para um selo
    que nao esta mais na tabela. Nao da para distinguir isso de "a conferencia
    comecou no meio" — entao vira OBSERVACAO, nunca acusacao."""
    linhas = _corrente(3, genese=_selo(777))
    conf = _conferir(linhas)
    assert conf.integra
    assert [o["tipo"] for o in conf.observacoes] == ["inicio_apos_vao"]


# ---------------------------------------------------------------------------
# 3b. Poda de retencao: o vao LEGITIMO nao pode virar alarme
# ---------------------------------------------------------------------------
# `audit_log_podar` (migration) apaga linhas de proposito e grava o proprio ato
# na trilha, com o selo da ultima linha removida em `details.hash_ultimo_podado`.
# Sem a reconciliacao abaixo, a PRIMEIRA poda de retencao — que o dono pediu —
# deixaria a tela em alarme vermelho para sempre.
def _poda(selo_fechando, *, evento_id=900, linhas=4, menor=None, maior=None):
    return {selo_fechando: {"evento_id": evento_id, "quando": AGORA,
                            "linhas": linhas, "menor_id": menor, "maior_id": maior}}


def test_vao_de_poda_registrada_nao_e_divergencia():
    linhas = _corrente(12)
    # A poda apaga os ids 7 a 10. Quem fecha o vao e o selo da ULTIMA linha
    # apagada (id 10) — e para ele que a linha 11 continua apontando.
    selo_do_ultimo_podado = linhas[9].selo
    del linhas[6:10]
    conf = _conferir(linhas, podas=_poda(selo_do_ultimo_podado, menor=7, maior=10))
    assert conf.integra
    assert conf.conferidos == 8
    obs = conf.observacoes[0]
    assert obs["tipo"] == "vao_explicado"
    assert (obs["depois_de_id"], obs["antes_de_id"]) == (6, 11)
    assert obs["evento_id"] == 900


def test_vao_sem_poda_registrada_continua_sendo_divergencia():
    """O que da valor a reconciliacao e ela NAO valer para todo vao."""
    linhas = _corrente(12)
    del linhas[6:10]
    assert _conferir(linhas, podas={}).divergencia.tipo == ai.TIPO_ELO


def test_poda_com_faixa_de_ids_fora_do_vao_nao_serve_de_alibi():
    """Reaproveitar um `hash_ultimo_podado` antigo nao pode carimbar de "poda"
    uma remocao feita a mao: a faixa removida tem de caber DENTRO do vao."""
    linhas = _corrente(12)
    selo = linhas[9].selo
    del linhas[6:10]
    # O selo CASA, mas a poda registrada diz ter removido os ids 200..300 —
    # nada a ver com este vao, que esta entre o 6 e o 11.
    conf = _conferir(linhas, podas=_poda(selo, menor=200, maior=300))
    assert conf.divergencia.tipo == ai.TIPO_ELO


def test_poda_do_inicio_da_trilha_e_reconhecida_na_primeira_linha():
    linhas = _corrente(4, genese=_selo(777))
    conf = _conferir(linhas, podas=_poda(_selo(777), evento_id=42, linhas=99, maior=0))
    assert conf.integra
    assert conf.observacoes[0]["tipo"] == "inicio_apos_poda"
    assert conf.observacoes[0]["evento_id"] == 42


# ---------------------------------------------------------------------------
# 3c. Poda POR PREFIXO — a que o dono realmente pediu (navegação, 12 meses)
# ---------------------------------------------------------------------------
# Retenção por tipo de ação apaga linhas SALPICADAS: cada trecho removido vira um
# vão, e cada vão aponta para um selo DIFERENTE — sendo que a poda só guardou o
# selo do ÚLTIMO. Nenhum desses vãos casa por selo. Sem a reconciliação por
# faixa, a primeira poda de retenção do sistema deixaria a tela em alarme
# vermelho PERMANENTE (limpar exigiria UPDATE, que o banco recusa).
def _corrente_esburacada():
    """12 linhas, com 3-4 e 7-8 removidas por uma poda de prefixo."""
    linhas = _corrente(12)
    ultimo_selo_removido = linhas[7].selo      # id 8, o maior id removido
    del linhas[6:8]                            # ids 7 e 8
    del linhas[2:4]                            # ids 3 e 4
    return linhas, ultimo_selo_removido


def test_poda_por_prefixo_deixa_varios_vaos_e_nenhum_e_divergencia():
    linhas, selo_do_ultimo = _corrente_esburacada()
    podas = _poda(selo_do_ultimo, linhas=4, menor=3, maior=8)
    podas[selo_do_ultimo]["contigua"] = False   # a poda ADMITE ter deixado buracos

    conf = _conferir(linhas, podas=podas)

    assert conf.integra
    assert conf.conferidos == 8
    # Os dois vãos são do MESMO ato: viram UMA observação com a contagem, e não
    # duas linhas iguais na tela (nem 3.000, numa poda de verdade).
    assert len(conf.observacoes) == 1
    obs = conf.observacoes[0]
    assert obs["tipo"] == "vao_explicado" and obs["vaos"] == 2
    assert (obs["depois_de_id"], obs["antes_de_id"]) == (2, 9)


def test_poda_que_se_declarou_contigua_nao_serve_de_alibi_por_faixa():
    """O que dá valor à prova por faixa é ela NÃO valer para toda poda.

    Poda sem filtro faz um corte limpo: um vão só, casado pelo selo. Se aparece
    um vão que aquele selo não fecha, houve remoção que a poda não explica —
    ainda que caia dentro da faixa de ids que ela removeu."""
    linhas, selo_do_ultimo = _corrente_esburacada()
    podas = _poda(selo_do_ultimo, linhas=4, menor=3, maior=8)
    podas[selo_do_ultimo]["contigua"] = True

    conf = _conferir(linhas, podas=podas)
    assert conf.divergencia.tipo == ai.TIPO_ELO
    assert conf.divergencia.id == 5      # o primeiro vão, que o selo não fecha


def test_poda_registrada_antes_do_vao_nao_explica_o_vao():
    """Álibi emitido antes do fato. A poda é gravada na trilha DEPOIS do DELETE,
    então o id do evento é maior que o de qualquer linha que ela removeu — e
    maior ou igual ao da sobrevivente que aponta para o vão. Um evento anterior
    é sinal de que alguém reaproveitou um registro de poda velho."""
    linhas, selo_do_ultimo = _corrente_esburacada()
    podas = _poda(selo_do_ultimo, evento_id=2, linhas=4, menor=3, maior=8)
    podas[selo_do_ultimo]["contigua"] = False

    assert _conferir(linhas, podas=podas).divergencia.tipo == ai.TIPO_ELO


def test_observacoes_tem_teto_e_o_excedente_vira_contagem():
    """Memória constante vale também para as observações: uma poda por prefixo
    pode deixar milhares de vãos, e uma lista que cresce com a tabela quebra a
    promessa deste módulo. O que não pode é o excedente sumir calado."""
    conf = ai.Conferencia(inicio_absoluto=True)
    for i in range(ai.LIMITE_OBSERVACOES + 7):
        conf._anotar({"tipo": "inicio_apos_vao", "antes_de_id": i})

    assert len(conf.observacoes) == ai.LIMITE_OBSERVACOES
    assert conf.observacoes_omitidas == 7


# ---------------------------------------------------------------------------
# 4. Modo degradado (sem a funcao de selo do banco)
# ---------------------------------------------------------------------------
def test_somente_elo_acha_remocao_mas_nao_acha_edicao():
    """O que o modo degradado promete e menos — e a tela diz isso. O que ele NAO
    pode fazer e aprovar em silencio uma remocao."""
    editada = _corrente(6, calcular=False)
    assert _conferir(editada).integra          # edicao passa: nao ha recalculo

    removida = _corrente(6, calcular=False)
    del removida[2]
    assert _conferir(removida).divergencia.tipo == ai.TIPO_ELO


# ---------------------------------------------------------------------------
# 5. SQL montado — a unica interpolacao de string do modulo
# ---------------------------------------------------------------------------
def test_sql_do_lote_usa_a_funcao_do_banco_e_tem_cursor():
    sql = ai._sql_lote("public.audit_log_selo")
    assert "public.audit_log_selo(a.*)" in sql
    assert "a.id > :cursor" in sql and "ORDER BY a.id" in sql and "LIMIT :lote" in sql


def test_sql_sem_funcao_nao_recalcula_nada():
    assert "NULL::text AS selo_calculado" in ai._sql_lote(None)


@pytest.mark.parametrize("nome", [
    "audit_log_selo; DROP TABLE audit_log --",
    "public.f(a.*), pg_sleep(10)",
    'evil"',
    "Função",
    "",
])
def test_peneira_do_nome_de_funcao_recusa_o_que_nao_e_identificador(nome):
    """O nome vem do catalogo do Postgres, nao do usuario — mas ele e o unico
    pedaco interpolado em SQL neste modulo, e a peneira e o que garante que
    continue seguro se um dia a origem mudar."""
    assert ai._NOME_FUNCAO_OK.match(nome) is None


def test_peneira_aceita_identificador_qualificado():
    for nome in ("audit_log_hash", "public.audit_log_hash", "_selo$1"):
        assert ai._NOME_FUNCAO_OK.match(nome) is not None


# ---------------------------------------------------------------------------
# 6. O texto da tela (routers/auditoria.py)
# ---------------------------------------------------------------------------
from routers import auditoria as ra  # noqa: E402  (precisa das env de teste)


def _res(**kw):
    base = {"situacao": "integra", "modo": ai.MODO_COMPLETO, "conferidos": 12480,
            "primeiro_id": 1, "ultimo_id": 12480, "primeiro_em": AGORA,
            "ultimo_em": AGORA, "completo": True, "divergencia": None}
    base.update(kw)
    return base


@pytest.mark.parametrize("situacao", ["integra", "parcial", "vazia", "nada_novo",
                                      "indisponivel"])
def test_todo_desfecho_tem_titulo_e_mensagem(situacao):
    """Resultado sem texto e tela em branco: o usuario clica e nao sabe o que
    aconteceu."""
    t = ra._texto_integridade(_res(situacao=situacao))
    assert t["titulo"].strip() and t["mensagem"].strip()
    assert t["tom"] in ("ok", "neutro", "critico")


def test_divergencia_sai_critica_e_com_o_que_fazer():
    t = ra._texto_integridade(_res(
        situacao="divergente", conferidos=6,
        divergencia={"tipo": ai.TIPO_CONTEUDO, "id": 7, "quando": AGORA,
                     "acao": "cofre.reveal", "id_anterior": 6}))
    assert t["tom"] == "critico"
    assert "7" in t["titulo"]
    assert "ALTERADO" in t["mensagem"]
    assert t["o_que_fazer"] and "incidente" in t["o_que_fazer"].lower()


def test_modo_degradado_nao_promete_conteudo_conferido():
    """Sem a funcao de selo da para provar que nada sumiu, NAO que nada foi
    editado. A palavra "íntegra" sozinha, ali, afirmaria mais do que se conferiu."""
    t = ra._texto_integridade(_res(modo=ai.MODO_SOMENTE_ELO))
    assert "encadeamento" in t["mensagem"].lower()
    assert "não foi encontrada" in t["mensagem"]
    assert t["titulo"] == "Encadeamento íntegro"


def test_formula_que_nao_bate_e_defeito_tecnico_e_nao_trilha_adulterada():
    """A causa mais provavel de o selo nao bater em TODAS as linhas e a formula
    do gatilho e a da conferencia terem divergido — nao alguem ter reescrito a
    trilha inteira. O texto tem de dizer isso, senao a tela acusa adulteracao
    onde ha bug."""
    t = ra._texto_integridade(_res(modo=ai.MODO_SOMENTE_ELO, formula_nao_confere=True))
    assert t["tom"] == "ok"           # nao e alarme de seguranca
    assert "problema técnico" in t["mensagem"]
    assert "não alteração de registro" in t["mensagem"]


def test_numero_sai_com_ponto_de_milhar():
    assert ra._numero(12480) == "12.480"
    assert ra._numero(None) == "0"


def test_ressalva_diz_o_que_a_corrente_nao_impede():
    """Item (E) do pedido: o texto da tela nao pode prometer o que o sistema nao
    cumpre. Quem tem a senha do banco derruba o gatilho — isso fica ESCRITO."""
    texto = ra.RESSALVA_INTEGRIDADE.lower()
    assert "não prova" in texto
    assert "administrador do banco" in texto


def test_aviso_de_imutabilidade_do_catalogo_e_honesto():
    """A nota de conformidade que a tela imprime tem de dizer as DUAS coisas: o
    banco recusa alteracao/exclusao, E existe um cenario que a corrente nao
    impede. Antes deste incremento ela dizia so "o sistema nao oferece nenhuma
    forma de alterar", que descrevia a aplicacao e calava sobre o banco."""
    aviso = asyncio.run(ra.catalogo(current=None))["aviso_imutabilidade"]
    assert "recusa alteração" in aviso
    assert "não é uma barreira absoluta" in aviso
    assert "Verificar integridade" in aviso


def test_protecao_desligada_vira_alerta_na_tela():
    """Trava que alguem derrubou tem de APARECER derrubada — uma tela que jura
    'exclusão bloqueada' lendo texto fixo diria o mesmo depois do estrago."""
    tela = ra._protecoes_para_tela({
        "sela_insercao": True, "bloqueia_alteracao": True,
        "bloqueia_exclusao": False, "bloqueia_limpeza": True,
        "papel": {"papel_separado": False},
    })
    assert len(tela["alertas"]) == 1
    assert "Exclusão recusada pelo banco" in tela["alertas"][0]
    assert [i["ativo"] for i in tela["itens"]] == [True, True, False, True]
    # Papel unico nao e alerta: e decisao de infra do dono, dita em nota.
    assert tela["papel_separado"] is False
    assert "decisão de infraestrutura" in tela["nota_papel"]


def test_papel_separado_muda_a_nota_e_nao_gera_alerta():
    tela = ra._protecoes_para_tela({
        "sela_insercao": True, "bloqueia_alteracao": True,
        "bloqueia_exclusao": True, "bloqueia_limpeza": True,
        "papel": {"papel_separado": True},
    })
    assert tela["alertas"] == []
    assert "duas camadas" in tela["nota_papel"]


def test_campo_fora_do_selo_vira_alerta_na_tela():
    """"Íntegra" só vale para o que o selo cobre. Campo de fora pode ser
    reescrito sem quebrar a corrente, e o gestor lê "íntegra" como "o registro
    inteiro está intacto" — tem todo o direito. Então a lista aparece."""
    tela = ra._protecoes_para_tela({
        "sela_insercao": True, "bloqueia_alteracao": True,
        "bloqueia_exclusao": True, "bloqueia_limpeza": True,
        "papel": {"papel_separado": True},
        "campos_fora_do_selo": ["origem_do_ato"],
    })
    alerta = " ".join(tela["alertas"])
    assert "origem_do_ato" in alerta and "não é detectada" in alerta.lower()
    # Não é acusação de adulteração: é defeito técnico, e a frase diz isso.
    assert "não sinal de" in alerta


# ---------------------------------------------------------------------------
# 7. O endpoint montando a resposta (sem banco: o serviço é substituído)
# ---------------------------------------------------------------------------
class _Usuario:
    id = 1
    email = "ana@montesiao.mg.gov.br"
    name = "Ana"
    allowed_telas = None        # admin: ensure_tela deixa passar
    allowed_municipio_ids = None


def _chamar_endpoint(monkeypatch, veredito):
    """Roda o endpoint com o serviço e a gravação da trilha substituídos.

    O que este teste cobre e nenhum outro cobre: a MONTAGEM da resposta. Um
    `KeyError` aqui — chave que o serviço parou de devolver, data que não vira
    texto — só apareceria em produção, no clique do usuário."""
    registrado = {}

    async def _conferir(db, **kw):
        return dict(veredito)

    async def _registrar(db, **kw):
        registrado.update(kw)
        return True

    monkeypatch.setattr(ra.audit_integridade, "conferir", _conferir)
    monkeypatch.setattr(ra, "registrar", _registrar)
    corpo = asyncio.run(ra.verificar_integridade(
        request=None, desde_id=None, max_linhas=None, db=None, current=_Usuario()))
    return corpo, registrado


_PROTECOES_OK = {"sela_insercao": True, "bloqueia_alteracao": True,
                 "bloqueia_exclusao": True, "bloqueia_limpeza": True,
                 "gatilhos": [], "papel": {"papel_separado": False}}


def test_endpoint_monta_resposta_integra_e_registra_na_propria_trilha(monkeypatch):
    corpo, registrado = _chamar_endpoint(monkeypatch, _res(protecoes=_PROTECOES_OK))

    assert corpo["situacao"] == "integra" and corpo["tom"] == "ok"
    assert corpo["faixa"]["do_id"] == 1 and corpo["faixa"]["de"]
    assert corpo["ressalva"] == ra.RESSALVA_INTEGRIDADE
    assert corpo["protecoes"]["alertas"] == []
    assert corpo["divergencia"] is None
    # A conferencia entra na trilha, com o desfecho no nome do alvo.
    assert registrado["action"] == "auditoria.verificar_integridade"
    assert registrado["resultado"] == "sucesso"
    assert "íntegra" in registrado["alvo_nome"]


def test_endpoint_traduz_observacao_de_poda_para_portugues(monkeypatch):
    """A observacao sai ESTRUTURADA do serviço e vira frase aqui — o mesmo
    desenho da lista, do modal e do CSV: uma fonte só de palavras."""
    corpo, registrado = _chamar_endpoint(monkeypatch, _res(
        protecoes=_PROTECOES_OK,
        observacoes=[{"tipo": "vao_explicado", "depois_de_id": 6, "antes_de_id": 11,
                      "evento_id": 900, "quando": AGORA, "linhas": 4,
                      "menor_id": 7, "maior_id": 10}]))
    frase = corpo["observacoes"][0]
    assert "vão" in frase and "nº 900" in frase and "4 registros" in frase
    assert "explicado" in frase
    assert registrado["details"]["vaos_explicados"] == 1


def test_endpoint_diz_quantos_trechos_e_que_a_prova_foi_por_faixa(monkeypatch):
    """Poda por prefixo: a frase tem de dizer que foram VÁRIOS trechos e que o
    que fecha a conta é a faixa declarada, não o selo de cada vão. Apresentar a
    prova fraca com a cara da forte é o tipo de meia-verdade que derruba um
    laudo inteiro numa perícia."""
    corpo, _ = _chamar_endpoint(monkeypatch, _res(
        protecoes=_PROTECOES_OK,
        observacoes=[{"tipo": "vao_explicado", "depois_de_id": 2, "antes_de_id": 9,
                      "evento_id": 900, "quando": AGORA, "linhas": 12480,
                      "vaos": 3117, "menor_id": 3, "maior_id": 8,
                      "reconciliacao": "faixa"}]))
    frase = corpo["observacoes"][0]
    assert "3.117 trechos" in frase and "12.480 registros" in frase
    assert "faixa de registros" in frase


def test_endpoint_nao_esconde_as_observacoes_que_nao_couberam(monkeypatch):
    corpo, _ = _chamar_endpoint(monkeypatch, _res(
        protecoes=_PROTECOES_OK,
        observacoes=[{"tipo": "inicio_apos_vao", "antes_de_id": 51}],
        observacoes_omitidas=204))
    assert "mais 204" in corpo["observacoes"][-1]


def test_endpoint_avisa_quando_o_inicio_da_trilha_nao_tem_poda_que_explique(monkeypatch):
    corpo, _ = _chamar_endpoint(monkeypatch, _res(
        protecoes=_PROTECOES_OK,
        observacoes=[{"tipo": "inicio_apos_vao", "antes_de_id": 51}]))
    assert "Merece explicação" in corpo["observacoes"][0]


def test_endpoint_divergente_registra_como_erro_e_nao_repete_a_frase(monkeypatch):
    """`resultado=erro` e o que torna a conferencia que ACUSOU filtravel na
    propria tela. E o bloco `divergencia` leva so fatos: a explicacao ja esta em
    `mensagem`, e duplicar faria a tela imprimir o mesmo paragrafo duas vezes."""
    corpo, registrado = _chamar_endpoint(monkeypatch, _res(
        situacao="divergente", conferidos=6, protecoes=_PROTECOES_OK,
        divergencia={"tipo": ai.TIPO_ELO, "id": 7, "quando": AGORA,
                     "acao": "cofre.reveal", "id_anterior": 6}))

    assert corpo["tom"] == "critico"
    assert corpo["divergencia"]["id"] == 7
    assert corpo["divergencia"]["acao_rotulo"] == "REVELOU uma senha guardada"
    assert "o_que_significa" not in corpo["divergencia"]
    assert registrado["resultado"] == "erro"
    assert "DIVERGÊNCIA" in registrado["alvo_nome"]
    assert registrado["details"]["divergencia"] == {"tipo": ai.TIPO_ELO, "id": 7}


def test_endpoint_barra_quem_nao_tem_a_tela(monkeypatch):
    """Mesmo portao da listagem — a conferencia diz quanta trilha existe e ate
    quando, que ja e informacao de auditoria."""
    import fastapi

    class _SemTela(_Usuario):
        allowed_telas = ["dashboard"]

    async def _nunca(*a, **kw):     # pragma: no cover - nao deve ser alcancado
        raise AssertionError("o gate deixou passar")

    monkeypatch.setattr(ra.audit_integridade, "conferir", _nunca)
    with pytest.raises(fastapi.HTTPException) as erro:
        asyncio.run(ra.verificar_integridade(
            request=None, desde_id=None, max_linhas=None, db=None,
            current=_SemTela()))
    assert erro.value.status_code == 403


def test_endpoint_indisponivel_nao_estoura_por_chave_faltando(monkeypatch):
    """O caminho de banco sem as colunas de selo devolve um dicionario mais
    pobre. Ele TEM de montar resposta igual — falhar no caminho de erro é o pior
    lugar para falhar."""
    corpo, registrado = _chamar_endpoint(monkeypatch, {
        "situacao": "indisponivel", "motivo": "sem_colunas", "modo": None,
        "funcao_selo": None, "conferidos": 0, "primeiro_id": None,
        "ultimo_id": None, "primeiro_em": None, "ultimo_em": None,
        "completo": False, "continuacao": False, "esgotou_tempo": False,
        "formula_nao_confere": False, "continuar_de": None, "observacoes": [],
        "divergencia": None, "protecoes": {}, "duracao_ms": 3,
    })
    assert corpo["situacao"] == "indisponivel"
    assert corpo["faixa"]["de"] is None
    # Protecao nenhuma lida = quatro alertas. Silencio aqui seria a tela dizendo
    # que esta tudo trancado num banco onde nada foi conferido.
    assert len(corpo["protecoes"]["alertas"]) == 4
    assert registrado["resultado"] == "erro"


def test_rota_de_integridade_vem_antes_da_rota_de_id():
    """/{evento_id} e `int`: declarada antes, ela engoliria /integridade com um
    422. O arquivo avisa isso em comentario — este teste faz o aviso valer."""
    caminhos = [r.path for r in ra.router.routes]
    assert (caminhos.index("/api/auditoria/integridade")
            < caminhos.index("/api/auditoria/{evento_id}"))
