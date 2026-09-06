"""
Emendas federais (CGU + dump SICONV) — os testes das armadilhas MEDIDAS.

⚠️ ESTE ARQUIVO NÃO TESTA "o parser parseia". Cada teste aqui existe porque a
medição de 06/09/2026 encontrou um jeito concreto de o coletor MENTIR EM
SILÊNCIO, e o número que motiva cada um está escrito no próprio teste. As três
que mais custariam:

  1. `VALOR_REPASSE_EMENDA` vem VAZIO em 113.658 das 298.114 linhas (38%). Sem o
     fallback, Nova Palma sai como R$ 9,23 mi em vez de R$ 13,68 mi — um terço
     do dinheiro some, e some plausivelmente.
  2. `NR_EMENDA` vem vazio (7.059), com 4 dígitos (444) e com 9 (1). Um `zfill`
     produziria um código VÁLIDO E DE OUTRA EMENDA — número plausível e errado
     não tem como ser percebido depois.
  3. O agregado da CGU é NACIONAL. `linha_cgu` não tem e não pode ter
     `municipio_id`; o dia em que tiver, o primeiro `SUM(...) GROUP BY` da tela
     repete o total do Brasil em cada município.

Rodar:
    python -m pytest backend/tests/test_portal_transparencia.py -v
"""
import re

import pytest

import ingestion.portal_transparencia as pt
from ingestion.portal_transparencia import (
    Bloqueado, Orcamento, ano_do_programa, cnpj14, codigo_emenda,
    linha_carteira, linha_cgu, linha_documento, orgao_do_programa, paginar,
    valor_dump)


class _Resposta:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")


class ClienteFalso:
    """Serve páginas POR NÚMERO, e registra o que foi pedido.

    ⚠️ Indexado por `pagina` e não pela ordem das chamadas: um dublê sequencial
    passaria por um motivo que a fonte real não tem. E a paginação da CGU começa
    em **1** — um dublê indexado a partir de 0 esconderia o erro de quem pulasse
    a primeira página."""

    def __init__(self, paginas, status=200):
        self.paginas = paginas
        self.pedidos: list[int] = []
        self.params: list[dict] = []
        self.status = status

    def get(self, url, params=None, **kw):
        params = params or {}
        n = params.get("pagina", 1)
        self.pedidos.append(n)
        self.params.append(dict(params))
        if self.status != 200:
            return _Resposta(None, status=self.status)
        if n < 1 or n > len(self.paginas):
            return _Resposta([])
        return _Resposta(self.paginas[n - 1])


@pytest.fixture(autouse=True)
def _sem_espera(monkeypatch):
    """A pausa real é de 0,7 s por requisição. O teste mede a LÓGICA."""
    monkeypatch.setattr(pt.time, "sleep", lambda _s: None)
    # O tamanho de página é APRENDIDO e vive num global — sem zerar, um teste
    # contamina o outro e a parada curta liga cedo demais no seguinte.
    pt._TAM_PAGINA = None
    pt._REQUISICOES = 0
    monkeypatch.setenv("PORTAL_TRANSPARENCIA_API_KEY", "chave-de-teste")


# ---------------------------------------------------------------------------
# codigo_emenda — a hipótese, e o que NUNCA se adivinha
# ---------------------------------------------------------------------------
def test_codigo_de_12_digitos_e_ano_mais_numero():
    """A hipótese: ano (posições 5:9 do programa) + NR_EMENDA.

    2023 + 32980002 = 202332980002. É o formato que o `codigoEmendaFormatado` do
    TransfereGov já usa ('202341760002-Nome do Parlamentar'), o que dá o grupo de
    controle do `--verificar`."""
    assert codigo_emenda("3600020230012", "32980002") == "202332980002"
    assert codigo_emenda("  3600020230012 ", " 32980002 ") == "202332980002"


def test_nr_emenda_vazio_devolve_none_e_nunca_um_codigo_curto():
    """7.059 das 298.114 linhas do dump vêm sem número.

    ⚠️ Emitir '2023' + '' = '2023' produziria um código de 4 dígitos que a API
    rejeita ou, pior, casa com outra coisa. A LINHA continua valendo — tem
    parlamentar, valor e beneficiário —, ela só nunca entra na fila da CGU."""
    assert codigo_emenda("3600020230012", "") is None
    assert codigo_emenda("3600020230012", "   ") is None


def test_nr_emenda_de_4_digitos_nao_leva_zfill():
    """444 linhas trazem o formato antigo, de 4 dígitos.

    ⚠️⚠️ `'1234'.zfill(8)` = `'00001234'` é um código VÁLIDO E DE OUTRA EMENDA.
    Um número plausível e errado não tem como ser percebido depois — é a razão
    de esta função devolver None em vez de completar."""
    assert codigo_emenda("3600020230012", "1234") is None


def test_nr_emenda_de_9_digitos_devolve_none():
    """1 linha do dump. Fora do contrato é None, não truncamento."""
    assert codigo_emenda("3600020230012", "123456789") is None


def test_programa_sem_13_digitos_devolve_none():
    """COD_PROGRAMA_EMENDA = órgão SIAFI (5) + ano (4) + seq (4). Sem os 13, o
    ano sairia truncado — e um ano truncado gera um código de 12 dígitos
    sintaticamente perfeito e semanticamente errado."""
    assert codigo_emenda("360002023001", "32980002") is None
    assert codigo_emenda("", "32980002") is None
    assert codigo_emenda("36000202300XY", "32980002") is None


def test_ano_absurdo_devolve_none_em_vez_de_sair_calado():
    """Ano fora de [1998, 2100] significa que o layout mudou de posição. Sair
    calado com um código inventado é pior que não coletar."""
    assert codigo_emenda("3600018000012", "32980002") is None
    assert ano_do_programa("3600020230012") == 2023
    assert ano_do_programa("360002023001") is None


def test_orgao_siafi_sao_os_5_primeiros():
    """36000 = Saúde, 56000 = Cidades/Desenvolvimento Regional. É o que dá a
    área de destino da emenda na tela."""
    assert orgao_do_programa("3600020230012") == "36000"
    assert orgao_do_programa("5600020230012") == "56000"
    assert orgao_do_programa("nao-e-numero") is None


# ---------------------------------------------------------------------------
# CNPJ — onde o zfill é certo, e onde o município NÃO vem do nome
# ---------------------------------------------------------------------------
def test_cnpj_com_13_digitos_ganha_o_zero_da_esquerda():
    """7 das 298.114 linhas vêm com 13 dígitos: o zero à esquerda foi comido
    pelo CSV, e o número continua sendo o mesmo CNPJ.

    ⚠️ Aqui o zfill é CERTO e no `NR_EMENDA` é errado, e a diferença é de
    natureza: no CNPJ o zero perdido não muda a identidade; no número da emenda,
    muda."""
    assert cnpj14("8848835800015") == "08848835800015"
    assert cnpj14("88.488.358/0001-56") == "88488358000156"
    assert cnpj14("88488358000156") == "88488358000156"


def test_cnpj_invalido_ou_curto_devolve_none():
    assert cnpj14("") is None
    assert cnpj14(None) is None
    assert cnpj14("123") is None
    assert cnpj14("1" * 15) is None


def test_o_municipio_sai_do_cnpj_e_nunca_do_nome():
    """⚠️ DIRETRIZ DO DONO (04/09/2026), e ela tem número: casar por nome trouxe
    379 obras da UFSM como se fossem da prefeitura de Santa Maria, e Santa Maria
    do Herval como se fosse Santa Maria.

    `linha_carteira` recebe o alvo JÁ RESOLVIDO por CNPJ. Não há, e não pode
    haver, nenhum caminho em que o nome do beneficiário decida o município."""
    l = {"BENEFICIARIO_EMENDA": "88488358000156",
         "NOME_PARLAMENTAR": "PREFEITURA MUNICIPAL DE SANTA MARIA DO HERVAL",
         "COD_PROGRAMA_EMENDA": "3600020230012", "NR_EMENDA": "32980002"}
    alvo = {"municipio_id": 7, "cnpj": "88488358000156",
            "nome": "MUNICÍPIO DE NOVA PALMA", "vinculo": "prefeitura"}
    linha = linha_carteira(l, alvo)
    # O município é o do ALVO (resolvido por CNPJ), e o nome que aparece no dump
    # — de outro município, aqui — não tem influência nenhuma.
    assert linha["municipio_id"] == 7
    assert linha["beneficiario_cnpj"] == "88488358000156"
    assert linha["beneficiario_nome"] == "MUNICÍPIO DE NOVA PALMA"
    # Trocar o alvo troca o município; trocar o texto do dump não troca nada.
    outro = {**alvo, "municipio_id": 99}
    assert linha_carteira(l, outro)["municipio_id"] == 99
    l2 = {**l, "NOME_PARLAMENTAR": "OUTRO NOME QUALQUER"}
    assert linha_carteira(l2, alvo)["municipio_id"] == 7


# ---------------------------------------------------------------------------
# Valores — os dois campos, e o parser que não pode ser o errado
# ---------------------------------------------------------------------------
def test_valor_cai_para_o_segundo_campo_quando_o_primeiro_vem_vazio():
    """⚠️ `VALOR_REPASSE_EMENDA` está VAZIO em 113.658 das 298.114 linhas (38%).

    Sem este fallback, Nova Palma sai como R$ 9,23 mi em vez de R$ 13,68 mi.
    O número menor também parece plausível — é por isso que precisa de teste."""
    assert valor_dump({"VALOR_REPASSE_EMENDA": "100000",
                       "VALOR_REPASSE_PROPOSTA_EMENDA": "0"}) == 100000.0
    assert valor_dump({"VALOR_REPASSE_EMENDA": "",
                       "VALOR_REPASSE_PROPOSTA_EMENDA": "592000"}) == 592000.0
    assert valor_dump({"VALOR_REPASSE_EMENDA": "",
                       "VALOR_REPASSE_PROPOSTA_EMENDA": ""}) is None


def test_virgula_decimal_e_notacao_cientifica_nao_estouram():
    """Os valores vêm com vírgula decimal e SEM separador de milhar
    ('222857,14'), mais 22 casos de notação científica negativa
    ('-5,8207660913467e-11').

    ⚠️ E o conversor tem de ser o CONDICIONAL (`transferegov_opendata._money`).
    O `_money` de `siconv_emenda_backfill` faz `replace('.','')` sem condicional:
    '1234567.89' viraria 123456789 — cem vezes maior, sem exceção e sem log."""
    assert valor_dump({"VALOR_REPASSE_EMENDA": "222857,14"}) == 222857.14
    assert valor_dump({"VALOR_REPASSE_EMENDA": "1234567.89"}) == 1234567.89
    v = valor_dump({"VALOR_REPASSE_EMENDA": "-5,8207660913467e-11"})
    assert v is None or abs(v) < 1  # o que não pode é estourar


def test_vazio_vira_none_e_nunca_zero():
    """"A fonte não informou" ≠ "não pagou nada". Zero é uma AFIRMAÇÃO que a
    fonte não fez — o mesmo princípio de `routers/obrasgov.py:186-188`."""
    assert valor_dump({"VALOR_REPASSE_EMENDA": None,
                       "VALOR_REPASSE_PROPOSTA_EMENDA": None}) is None
    assert linha_cgu({"valorPago": ""})["valor_pago"] is None
    assert linha_cgu({"valorPago": "0"})["valor_pago"] == 0.0


# ---------------------------------------------------------------------------
# linha_carteira — classificação sem chute
# ---------------------------------------------------------------------------
def _linha(**kw):
    base = {"ID_PROPOSTA": "123", "COD_PROGRAMA_EMENDA": "3600020230012",
            "NR_EMENDA": "32980002", "NOME_PARLAMENTAR": "HEITOR SCHUCH",
            "BENEFICIARIO_EMENDA": "88488358000156", "IND_IMPOSITIVO": "SIM",
            "TIPO_PARLAMENTAR": "INDIVIDUAL", "QUALIF_PROPONENTE": "X",
            "VALOR_REPASSE_PROPOSTA_EMENDA": "100000",
            "VALOR_REPASSE_EMENDA": "100000"}
    base.update(kw)
    return base


_ALVO = {"municipio_id": 1, "cnpj": "88488358000156",
         "nome": "MUNICÍPIO DE NOVA PALMA", "vinculo": "prefeitura"}


def test_tipo_parlamentar_vazio_vira_none_e_nao_individual():
    """`TIPO_PARLAMENTAR` vem vazio em 10.654 das 298.114 linhas.

    ⚠️ Um COALESCE para 'INDIVIDUAL' INVENTARIA classificação — e ela é o que
    decide se o autor entra no ranking como pessoa ou como colegiado."""
    assert linha_carteira(_linha(TIPO_PARLAMENTAR=""), _ALVO)["tipo_parlamentar"] is None
    assert linha_carteira(_linha(), _ALVO)["tipo_parlamentar"] == "INDIVIDUAL"


def test_impositiva_so_e_true_com_sim_explicito():
    assert linha_carteira(_linha(IND_IMPOSITIVO="SIM"), _ALVO)["impositiva"] is True
    assert linha_carteira(_linha(IND_IMPOSITIVO="NÃO"), _ALVO)["impositiva"] is False
    assert linha_carteira(_linha(IND_IMPOSITIVO=""), _ALVO)["impositiva"] is None


def test_e_prefeitura_vem_do_vinculo_do_cnpj():
    """É o que a tela usa para separar «do município» de «de entidade do
    município» — em Nova Palma são 8 emendas ao Hospital N. S. da Piedade, e
    somá-las sem dizer prometeria ao gestor um caixa que não é dele."""
    assert linha_carteira(_linha(), _ALVO)["e_prefeitura"] is True
    hosp = {**_ALVO, "vinculo": "pac", "nome": "HOSPITAL"}
    assert linha_carteira(_linha(), hosp)["e_prefeitura"] is False


def test_a_linha_sem_codigo_continua_sendo_gravada():
    """⚠️ O TESTE QUE IMPEDE ALGUÉM DE «LIMPAR» 7.059 LINHAS BOAS.

    Sem número de emenda a linha não pode ser perguntada à CGU — mas ela tem
    parlamentar, valor e beneficiário, que é o que a carteira mostra. Descartá-la
    apagaria dinheiro real da tela."""
    linha = linha_carteira(_linha(NR_EMENDA=""), _ALVO)
    assert linha["codigo_emenda"] is None
    assert linha["parlamentar"] == "HEITOR SCHUCH"
    assert linha["valor_repasse_emenda"] == 100000.0
    assert linha["municipio_id"] == 1


# ---------------------------------------------------------------------------
# linha_cgu / linha_documento — o que a fonte diz, e o que ela não diz
# ---------------------------------------------------------------------------
def test_o_agregado_da_cgu_nao_tem_municipio():
    """⚠️⚠️ A GUARDA MAIS IMPORTANTE DO MÓDULO. `/emendas?codigoEmenda=` devolve
    o agregado da emenda INTEIRA: uma emenda de bancada de R$ 30 mi que passou
    por Nova Palma com R$ 250 mil traz R$ 30 mi.

    Sem `municipio_id` na linha (e sem a coluna na tabela), o
    `SUM(valor_pago) GROUP BY municipio_id` que produziria esse número é
    impossível de escrever por acidente. A guarda é o schema, não a disciplina
    de quem escreve a query."""
    linha = linha_cgu({"codigoEmenda": "202332980002", "valorPago": "30000000",
                       "localidadeDoGasto": "NOVA PALMA - RS"})
    assert "municipio_id" not in linha
    # `localidadeDoGasto` é guardada como TEXTO informativo — nunca como chave.
    assert linha["localidade_gasto"] == "NOVA PALMA - RS"


def test_os_seis_valores_do_dto_sao_lidos_pelos_nomes_exatos():
    """Nome de campo errado devolveria None sem erro e a linha gravaria vazia —
    a fonte parece pobre e ninguém desconfia do código."""
    linha = linha_cgu({
        "codigoEmenda": "202332980002", "valorEmpenhado": "100",
        "valorLiquidado": "90", "valorPago": "80", "valorRestoInscrito": "20",
        "valorRestoCancelado": "5", "valorRestoPago": "15"})
    assert (linha["valor_empenhado"], linha["valor_liquidado"],
            linha["valor_pago"]) == (100.0, 90.0, 80.0)
    assert (linha["valor_resto_inscrito"], linha["valor_resto_cancelado"],
            linha["valor_resto_pago"]) == (20.0, 5.0, 15.0)


def test_documento_nao_tem_campo_de_valor():
    """⚠️ É A FONTE, NÃO ESQUECIMENTO: o `DocumentoRelacionadoEmendaDTO` responde
    QUANDO e EM QUE FASE, jamais QUANTO. Uma coluna de valor aqui convidaria a
    tela a somar documentos como se fossem pagamentos."""
    d = linha_documento("202332980002", {
        "id": 9, "data": "12/03/2024", "fase": "Empenho",
        "codigoDocumento": "153173000012024NE000001", "especieTipo": "Empenho"})
    assert d is not None
    assert not [k for k in d if "valor" in k]
    assert d["data"].isoformat() == "2024-03-12"


def test_documento_sem_id_e_descartado():
    assert linha_documento("202332980002", {"fase": "Empenho"}) is None


# ---------------------------------------------------------------------------
# paginar — cota, truncamento e o 429 que NÃO se retenta
# ---------------------------------------------------------------------------
def test_paginacao_comeca_em_1_e_para_na_pagina_vazia():
    c = ClienteFalso([[{"a": 1}], [{"a": 2}], []])
    itens, completo = paginar(c, "/emendas", {})
    assert [i["a"] for i in itens] == [1, 2]
    assert completo is True
    assert c.pedidos[0] == 1


def test_teto_de_paginas_devolve_completo_false():
    """⚠️ A VERSÃO ANTERIOR REGISTRAVA O TETO EM LOG E DEVOLVIA DADO TRUNCADO,
    com a rodada seguindo como sucesso. Para `/emendas/documentos` isso seria
    "pagamentos faltando" com luz verde. Agora quem chama recebe `completo` e
    decide o status."""
    c = ClienteFalso([[{"a": i}] for i in range(10)])
    itens, completo = paginar(c, "/emendas", {}, teto_paginas=3)
    assert len(itens) == 3
    assert completo is False


def test_parada_curta_so_liga_depois_de_aprender_o_tamanho():
    """⭐ Metade da cota sai daqui: com a parada em "página vazia", uma consulta
    de 1 resultado custava DUAS requisições.

    ⚠️ Mas a parada curta só pode ligar DEPOIS de a rodada ter visto uma página
    cheia. Chutar o tamanho e a CGU mudar truncaria em silêncio — que é pior que
    gastar a requisição. Com o tamanho desconhecido, um lote de 1 item AINDA
    pede a página 2."""
    c = ClienteFalso([[{"a": 1}], []])
    itens, completo = paginar(c, "/emendas", {})
    assert c.pedidos == [1, 2], "sem tamanho aprendido, tem de pedir a página 2"
    assert completo is True

    pt._TAM_PAGINA = None
    cheia = [{"a": i} for i in range(15)]
    c2 = ClienteFalso([cheia, [{"a": 99}]])
    itens2, completo2 = paginar(c2, "/emendas", {})
    assert c2.pedidos == [1, 2], "a página curta encerra sem pedir a 3ª"
    assert len(itens2) == 16
    assert completo2 is True


def test_401_vira_permission_error_com_a_causa_certa():
    """Chave revogada ou token suspenso por 8h precisa GRITAR — vira `error` na
    rodada, não `partial`."""
    c = ClienteFalso([], status=401)
    with pytest.raises(PermissionError) as e:
        paginar(c, "/emendas", {})
    assert "chave-api-dados" in str(e.value)


def test_429_nao_e_retentado_e_a_mesma_pagina_nao_e_pedida_duas_vezes():
    """⚠️⚠️ O OPOSTO DO `obrasgov.pagina()`, DE PROPÓSITO.

    A medição de 17/08/2026 na API `especiais` do TransfereGov (INFRA.md §5)
    mostrou que REQUISIÇÃO REJEITADA TAMBÉM RENOVA A PENA: as próprias
    retentativas do backoff mantiveram o IP em 403 por mais de 6 horas. A CGU
    suspende o TOKEN por 8h, e o token é o mesmo nos cinco tenants — um backoff
    aqui derrubaria a fonte inteira, no ambiente inteiro, por uma noite e meia."""
    c = ClienteFalso([], status=429)
    with pytest.raises(Bloqueado):
        paginar(c, "/emendas", {})
    assert c.pedidos == [1], "429 não pode ser retentado"


def test_orcamento_interrompe_e_marca_incompleto():
    """⚠️ O ORÇAMENTO EXISTE POR CAUSA DE UM ACIDENTE QUE JÁ ACONTECEU: o
    INFRA.md §8 registra uma Scheduled Task presa em `* * * * *` por 34 horas
    (~1.440 execuções). Com este coletor isso seria o teto diário da CGU e o
    token suspenso — por isso o teto é contado em código, e não confiado à
    atenção de quem revisa o cron."""
    c = ClienteFalso([[{"a": i}] for i in range(10)])
    orc = Orcamento(60, 2)
    itens, completo = paginar(c, "/emendas", {}, orcamento=orc)
    assert orc.estourou is True
    assert completo is False
    assert len(c.pedidos) == 2


def test_a_pausa_vem_antes_da_requisicao_e_nao_depois(monkeypatch):
    """⚠️ Antes a pausa ficava abaixo do `extend` e era pulada justamente no
    retorno da página VAZIA — ou seja, o coletor martelava mais rápido no
    cenário em que a maioria dos códigos não casa, que é quando ele deve ir
    devagar. Mesma lição do `fns_faf`."""
    dormiu: list[float] = []
    monkeypatch.setattr(pt.time, "sleep", lambda s: dormiu.append(s))
    c = ClienteFalso([[{"a": 1}], [{"a": 2}], []])
    paginar(c, "/emendas", {})
    assert len(dormiu) == 2, "uma pausa antes de cada página depois da primeira"


# ---------------------------------------------------------------------------
# O contrato do módulo
# ---------------------------------------------------------------------------
def test_as_dez_colunas_do_dump_estao_declaradas():
    """A guarda de layout confere estas contra o `fieldnames` e ABORTA. Cabeçalho
    errado hoje produz "zero em silêncio" — a ingestão "conclui" trazendo nada e
    a tela esvazia sem nenhum erro em log (`transferegov_opendata.py:326-329`,
    escrito depois de acontecer na migração do PAC)."""
    assert len(pt.COLUNAS_DUMP) == 10
    assert "BENEFICIARIO_EMENDA" in pt.COLUNAS_DUMP
    assert "VALOR_REPASSE_PROPOSTA_EMENDA" in pt.COLUNAS_DUMP


def test_sem_chave_o_coletor_se_reconhece_desabilitado(monkeypatch):
    """A fase 2 é inerte sem chave, e isso é decisão — não defeito."""
    monkeypatch.delenv("PORTAL_TRANSPARENCIA_API_KEY", raising=False)
    assert pt.habilitado() is False
    monkeypatch.setenv("PORTAL_TRANSPARENCIA_API_KEY", "  ")
    assert pt.habilitado() is False


def test_o_cabecalho_leva_a_chave_no_nome_exato():
    """`chave-api-dados`, confirmado no `components.securitySchemes` do
    `/v3/api-docs`. Um `Authorization: Bearer` devolveria 401 para sempre."""
    assert "chave-api-dados" in pt._cabecalhos()

# ---------------------------------------------------------------------------
# De onde saem os CNPJs — e a fonte que nasceu de R$ 1,2 milhão invisível
# ---------------------------------------------------------------------------
def _codigo_de_alvos() -> str:
    """O corpo de `alvos()` SEM a docstring.

    ⚠️ A distinção importa: a docstring cita `siconv_proponentes` de propósito,
    para registrar por que aquele caminho NÃO é usado. Um teste que varresse o
    texto inteiro reprovaria a explicação junto com o defeito — e o autor
    seguinte apagaria a explicação para o teste passar."""
    import inspect

    src = inspect.getsource(pt.alvos)
    ini = src.find('"""')
    fim = src.find('"""', ini + 3)
    return src[:ini] + src[fim + 3:] if ini != -1 and fim != -1 else src
def test_alvos_le_as_quatro_fontes_de_cnpj_e_o_cadastro_vem_primeiro():
    """⭐ `municipio_entidades` ENTROU EM 06/09/2026 POR CAUSA DE UM NÚMERO.

    A primeira carga real de Nova Palma trouxe **69 das 77 linhas** do dump. As 8
    que faltaram são da Associação Hospital Nossa Senhora da Piedade — R$ 1,2
    milhão em emendas que existem, são do município, e não apareciam em lugar
    nenhum. Hospital filantrópico não aparece em obra do SISMOB nem em proposta
    do PAC, então as três fontes antigas nunca o alcançariam.

    ⚠️ E O CADASTRO VEM PRIMEIRO na ordem: se o mesmo CNPJ estiver em duas
    fontes, fica o nome que uma PESSOA escreveu, e não o rótulo que a API de
    obras usa.

    ⚠️ A saída fácil era a proibida — casar o NOME do município no dump de
    proponentes. É a regra que o dono cravou em 04/09/2026 (379 obras da UFSM em
    Santa Maria). O CNPJ tem de ter ORIGEM, não dedução."""
    for fonte in ("municipios", "municipio_entidades", "sismob_obras",
                  "transferegov_pac"):
        assert fonte in _codigo_de_alvos(), f"{fonte} deixou de ser fonte de CNPJ"
    assert re.findall(r'""", "(\w+)"', _codigo_de_alvos())[0] == "entidade", (
        "o cadastro explícito tem de ser consultado ANTES do garimpo")


def test_alvos_nao_casa_municipio_por_nome_em_lugar_nenhum():
    """⚠️ A GUARDA DA REGRA DO DONO, no CÓDIGO da função (a docstring dela fala
    de `siconv_proponentes` justamente para dizer por que ele NÃO é usado —
    testar o arquivo inteiro reprovaria a explicação junto com o defeito).

    Nenhuma das quatro fontes pode juntar por nome, nem a de proponentes do
    dump, que seria o atalho óbvio para achar o hospital."""
    codigo = _codigo_de_alvos()
    assert "proponentes" not in codigo.lower()
    assert "MUNICIPIO_PROPONENTE" not in codigo
    assert "ILIKE" not in codigo.upper()

# ---------------------------------------------------------------------------
# Os três defeitos que só a CARGA REAL de 06/09/2026 revelou
# ---------------------------------------------------------------------------
def test_o_teto_de_documentos_cobre_o_pior_caso_medido():
    """⚠️ O PRIMEIRO VALOR ESTAVA ERRADO, e o erro era invisível.

    Com `teto=20`, a rodada de Nova Palma truncou QUATRO emendas. A maior tem
    **300 documentos** (2.810 no total das 44) e a CGU serve 15 por página —
    300/15 = exatamente 20. O teto batia no limite e cortava justamente as
    emendas mais executadas, que são as que mais interessam.

    60 páginas ≈ 900 documentos: três vezes o pior caso medido."""
    assert pt.TETO_DOCUMENTOS >= 40, (
        "teto abaixo do pior caso medido (300 documentos = 20 páginas)")


def test_documento_truncado_faz_a_rodada_sair_partial():
    """⚠️⚠️ «PAGAMENTOS FALTANDO COM LUZ VERDE» é o modo de falha que este repo
    mais paga caro — foi assim que a Freitas passou nove dias com o CAGEC
    quebrado. Emenda cortada no teto é execução incompleta na tela, e a rodada
    tem de dizer isso.

    Este teste lê o próprio código de `execucao()`, porque a alternativa seria
    um dublê de Postgres que o repo não tem."""
    import inspect

    src = inspect.getsource(pt.execucao)
    assert 'rel["truncados"].append' in src, (
        "o `completo` de documentos_da_emenda voltou a ser descartado")
    ingest = inspect.getsource(pt.ingest)
    assert 'ex["truncados"]' in ingest and '"partial"' in ingest, (
        "truncamento tem de virar `partial`, nunca `success`")


def test_documentos_da_emenda_devolve_o_par_e_nao_so_a_lista():
    """A assinatura é `(itens, completo)`. Quem chama precisa poder saber."""
    c = ClienteFalso([[{"id": 1}], []])
    itens, completo = pt.documentos_da_emenda(c, "202332980002")
    assert completo is True and len(itens) == 1


def test_texto_de_fonte_externa_nao_tem_largura_na_migration():
    """⚠️ A CARGA REAL ABORTOU COM `value too long for character varying(20)`.

    O campo era `autor`, que eu declarei estreito supondo ser um CÓDIGO curto (o
    `3298` de Heitor Schuch). Não é: em emenda de colegiado a CGU manda o NOME
    no mesmo campo — «COM. DESENV REGIONAL E TURISMO», 30 caracteres. E
    `tipo_emenda` estava a DOIS caracteres do teto (58 de 60).

    A regra que sai daqui: texto que vem de fonte externa não tem largura.
    VARCHAR(n) só protege contra o que NÓS escrevemos; contra o que o Governo
    escreve, ele troca um dado inesperado por uma coleta abortada."""
    from pathlib import Path

    sql = (Path(__file__).resolve().parents[1] / "migrations"
           / "add_emendas_federais_texto.sql").read_text(encoding="utf-8")
    for col in ("autor", "nome_autor", "tipo_emenda", "numero_emenda",
                "tipo_parlamentar", "parlamentar", "beneficiario_nome",
                "codigo_documento"):
        assert re.search(rf"ALTER COLUMN {col} TYPE TEXT", sql), col


def test_a_migration_de_texto_esta_depois_da_que_cria_as_tabelas():
    """Inverter a ordem quebra banco NOVO: o ALTER cairia sobre tabela que ainda
    não existe, e o runner ENGOLE a falha (migration que falha não derruba o
    boot)."""
    from services.startup import MIGRATION_FILES

    assert (MIGRATION_FILES.index("add_emendas_federais_texto.sql")
            > MIGRATION_FILES.index("add_emendas_federais.sql"))

def test_a_fila_da_te_e_filtrada_por_cnpj():
    """⚠️ DEFEITO MEU, medido na primeira rodada com chave em Monte Sião: a fila
    nasceu com **545 códigos** em vez dos 31 da carteira — fator de 17.

    A causa: `transferegov_te` guarda os planos do ESTADO inteiro, e o
    `municipio_id` dela vem de casamento por SUBSTRING DE NOME, com contaminação
    medida (628 de 890 linhas com CNPJ divergente na base trust). Semear tudo
    gastava o orçamento da noite consultando emenda de outro município.

    ⚠️ Não CORROMPIA nada — `emendas_federais_cgu` é nacional por desenho e a
    tela só mostra o que dá JOIN com a carteira. Mas gastava cota com o que
    ninguém ia ler.

    ⚠️ E o `OR ... = ''` no fim NÃO é descuido: TE sem CNPJ do beneficiário não
    tem como ser recuperada pelo dump (Transferência Especial vive em outro
    sistema e não está no `siconv_emenda.zip`). Perder emenda legítima para
    economizar requisição seria o pior dos dois erros."""
    import inspect

    src = inspect.getsource(pt.semear_fila)
    assert "beneficiario_cnpj" in src and "= ANY(%s)" in src, (
        "a semeadura da TE voltou a não filtrar por CNPJ")
    assert "coalesce(te.beneficiario_cnpj, '') = ''" in src, (
        "o resgate da TE sem CNPJ sumiu — emenda legítima seria perdida")
    # A assinatura tem de aceitar a lista, senão o filtro nunca recebe nada.
    assert "cnpjs" in inspect.signature(pt.semear_fila).parameters

def test_emenda_de_colegiado_nao_busca_linha_do_tempo():
    """⚠️⚠️ A MEDIÇÃO QUE MOTIVOU, em Monte Sião, primeira rodada com chave:

        COMISSAO      4 emendas -> 3.600 documentos (TODAS truncadas no teto)
        INDIVIDUAL   27 emendas ->    15 documentos

    Emenda de comissão/bancada é NACIONAL: atende o país inteiro, e os 900+
    documentos dela são de outros municípios. Buscar isso custou 240
    requisições — quase toda a cota da noite — para gravar 3.600 linhas que
    ninguém vai ler e que não dizem nada sobre o município.

    ⚠️ O AGREGADO continua sendo buscado (1 requisição, e é ele que alimenta os
    valores da tela). O que se pula é só a linha do tempo. E a tela DIZ isso na
    gaveta — vazio sem explicação seria lido como «não houve execução»."""
    import inspect

    assert set(pt.TIPOS_COLEGIADO) == {"COMISSAO", "BANCADA", "RELATOR GERAL"}
    src = inspect.getsource(pt.execucao)
    assert "colegiado" in src and "not colegiado" in src, (
        "a linha do tempo voltou a ser buscada para emenda de colegiado")
    # O agregado NÃO pode ter sido pulado junto — é ele que dá os valores.
    assert "_consulta_um(client, codigo, ano, estrategia, orc)" in src


def test_a_fila_traz_o_tipo_para_a_decisao_de_colegiado():
    """Sem o tipo na fila, a decisão acima seria impossível — e o coletor
    voltaria a gastar a noite em documento de emenda nacional."""
    import inspect

    src = inspect.getsource(pt.fila)
    assert "tipo_parlamentar" in src

def test_a_fila_orfa_e_limpa_antes_de_semear():
    """⚠️ O FILTRO DA SEMEADURA SOZINHO NÃO BASTOU, e a medição de 06/09/2026
    mostrou por quê: a fila é uma tabela PERSISTENTE. Depois do conserto, Nova
    Palma seguia com **283 códigos** para uma carteira de 44, e Monte Sião com
    545 para 31 — todos herdados da rodada anterior ao filtro.

    ⚠️⚠️ E o órfão escapava TAMBÉM do filtro de colegiado: aquele decide pelo
    `tipo_parlamentar` da CARTEIRA, e código fora dela tem tipo NULL — não é
    reconhecido como colegiado e volta a puxar centenas de documentos. Os dois
    consertos só funcionam juntos.

    ⚠️ E a limpeza é SÓ da fila, que é controle. `emendas_federais_cgu` e
    `..._documentos` ficam: são nacionais por desenho, não aparecem na tela sem
    o JOIN com a carteira, e apagar dado já pago em requisição trocaria espaço
    em disco por cota da próxima noite."""
    import inspect

    src = inspect.getsource(pt.limpar_fila_orfa)
    assert "DELETE FROM emendas_federais_consulta" in src
    # NÃO pode apagar o que já foi coletado.
    assert "DELETE FROM emendas_federais_cgu" not in src
    assert "DELETE FROM emendas_federais_documentos" not in src
    # A ordem importa: limpar ANTES de semear, senão o órfão sobrevive à rodada.
    ex = inspect.getsource(pt.execucao)
    assert ex.index("limpar_fila_orfa") < ex.index("semear_fila")


# ---------------------------------------------------------------------------
# Os achados da varredura adversarial de 06/09/2026
# ---------------------------------------------------------------------------
def test_a_pausa_vale_entre_codigos_e_nao_so_entre_paginas(monkeypatch):
    """⚠️ O FREIO ESTAVA PELA METADE, e a medição prova.

    A condição era `if pagina > 1 or out`. Como quase toda consulta resolve em
    UMA página, cada código novo entrava com `pagina=1` e `out=[]` — ou seja,
    NÃO havia pausa entre códigos, só dentro de um.

    Medido em produção: Nova Palma fez 112 requisições em ~50 s (134 req/min) e
    Monte Sião 265 em ~133 s (120 req/min), contra os ~86 que o desenho
    prometia. Não estourou porque `/emendas` está na faixa de 400/700 — mas a
    faixa RESTRITA é 180, e o freio existe para respeitar o pior caso."""
    dormiu = []
    monkeypatch.setattr(pt.time, "sleep", lambda s: dormiu.append(s))
    pt._REQUISICOES = 0
    # Três CÓDIGOS diferentes, cada um resolvendo em uma página só.
    for _ in range(3):
        paginar(ClienteFalso([[{"a": 1}], []]), "/emendas", {})
    # 3 códigos x 2 páginas = 6 requisições; a 1ª da rodada não dorme.
    assert len(dormiu) == 5, (
        "sem pausa entre códigos o coletor anda a 134 req/min em vez de 86")


def test_erro_de_transporte_nao_vira_a_cgu_nao_conhece_este_codigo():
    """⚠️ `False` em `achou_agregado` é uma AFIRMAÇÃO — a tela imprime «Sem
    registro na CGU». Timeout, 500 e 503 não afirmam nada sobre a emenda: são
    ausência NOSSA, e o valor certo é NULL.

    Gravar `False` trocava um problema de rede por uma acusação ao dado, e ainda
    queimava uma das três tentativas do backoff."""
    import inspect

    src = inspect.getsource(pt.execucao)
    assert "marcas.append((codigo, None, 0, str(e)[:200]))" in src, (
        "erro de transporte voltou a ser gravado como «não conhece o código»")


def test_resposta_200_que_nao_e_lista_nao_e_fim_de_paginacao():
    """⚠️ Se a CGU passar a devolver um envelope (`{\"data\": [...]}`), tratar
    como «acabou» zeraria a fonte EM SILÊNCIO — o modo de falha mais caro deste
    repo. `completo=False` faz a rodada sair `partial`."""
    envelope = ClienteFalso([{"data": [{"a": 1}]}])
    itens, completo = paginar(envelope, "/emendas", {})
    assert itens == [] and completo is False


def test_json_invalido_com_200_nao_passa_por_fim_de_paginacao():
    """Página de manutenção ou WAF com HTTP 200: é falha, não fim."""
    class _Html:
        status_code = 200

        def json(self):
            raise ValueError("not json")

        def raise_for_status(self):
            pass

    class _Cli:
        def get(self, *a, **k):
            return _Html()

    itens, completo = paginar(_Cli(), "/emendas", {})
    assert itens == [] and completo is False
