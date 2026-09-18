"""As CINCO guardas da consulta do radar — verificadas na ARVORE do SQL.

Nao ha Postgres de teste neste repo (SQL se valida com `pglast`), entao a
consulta do `routers/programas_captacao` nao pode ser exercitada contra banco.
O que da para fazer — e o que este arquivo faz — e PARSEAR o SQL com a gramatica
real do Postgres e exigir que as condicoes estejam la.

⚠️ POR QUE ISSO NAO E `assert "..." in sql`. Uma busca por substring passa com o
texto dentro de um comentario, de uma string, ou de um `OR` que anula a guarda.
O parser enxerga a ESTRUTURA: as condicoes tem de estar no WHERE e o topo do
WHERE tem de ser uma cadeia de AND. Cada guarda, se cair, produz um defeito
diferente e nenhum deles levanta erro:

    sem `ausente_desde IS NULL`   -> programa fora do ar volta para a tela;
    sem `dt_fim_receb >= hoje`    -> a tela anuncia prazo VENCIDO (a tabela e
                                     fotografia do dia da coleta);
    sem `dt_ini_receb <= hoje`    -> entra na conta de "abertos hoje" programa
                                     cuja janela so abre em novembro;
    sem `:nat = ANY(naturezas)`   -> aparece programa que so o consorcio assina;
    sem `:uf = ANY(ufs)`          -> prefeito mineiro recebe programa que so
                                     aceita municipio gaucho — "porta que nao
                                     abre", o defeito que o `programas_rs.py`
                                     ja documenta.

E, no fim do arquivo, a guarda do CARIMBO de coleta, que nao esta no WHERE: ele
tem de sair de consulta PROPRIA, porque deriva-lo das linhas filtradas fazia um
radar coletado se declarar nunca coletado.

Rodar: python -m pytest backend/tests/test_radar_router_guardas.py -q
"""
import re

import pytest

pglast = pytest.importorskip("pglast")

from routers import programas_captacao as R  # noqa: E402


def _constante(nome: str) -> str:
    """O texto de uma constante de SQL, lido do ARQUIVO do router.

    Le do arquivo, e nao do modulo importado, pela mesma razao de sempre: o que
    vai para o banco e o texto que esta no codigo."""
    fonte = open(R.__file__, encoding="utf-8").read()
    achado = re.search(rf'^{nome} = """(.*?)"""', fonte, re.S | re.M)
    assert achado, f"constante {nome} nao encontrada no router"
    return achado.group(1)


def _sql_da_rota() -> str:
    """O SELECT do radar, montado das MESMAS pecas que a rota monta.

    ⚠️ EM 04/09/2026 A CONSULTA DEIXOU DE SER UM BLOCO SO. A CTE e o filtro
    viraram constantes compartilhadas com o endpoint `/contagem`, que alimenta o
    contador do menu — porque um contador que discorde da tela e pior que
    contador nenhum. Este extrator acompanhou, e continua lendo do arquivo.

    ⚠️ E EXIGE QUE A ROTA CONCATENE ESSAS PECAS, logo abaixo. Sem essa
    verificacao a refatoracao teria aberto exatamente o buraco que o extrator
    antigo fechava: alguem define as constantes, o teste as valida, e a rota
    manda outra coisa para o banco."""
    fonte = open(R.__file__, encoding="utf-8").read()
    montagem = "text(_CTE_ABERTOS + _SELECT_LISTA + _FILTRO_ABERTOS + _ORDEM_LISTA)"
    assert montagem in fonte, (
        "a rota do radar nao monta mais a consulta com as constantes que este "
        f"teste valida (esperado: {montagem}) — ajuste o extrator DE PROPOSITO")
    sql = (_constante("_CTE_ABERTOS") + _constante("_SELECT_LISTA")
           + _constante("_FILTRO_ABERTOS") + _constante("_ORDEM_LISTA"))
    # `:uf`/`:nat` sao binds do SQLAlchemy; o Postgres nao os conhece.
    # ⚠️ O `(?<!:)` E OBRIGATORIO: sem ele o cast `::date` do Postgres virava
    # `:'date'` e o parser recusava a consulta INTEIRA — o teste passaria a
    # falhar por defeito dele proprio, escondendo se as guardas estao ou nao no
    # lugar. Bind e cast usam o mesmo caractere; so o dobrado e cast.
    return re.sub(r"(?<!:):(\w+)", r"'\1'", sql)


def _where_bruto():
    """O no do WHERE, direto da arvore do Postgres."""
    arvore = pglast.parse_sql(_sql_da_rota())
    return arvore[0].stmt.whereClause


@pytest.fixture(scope="module")
def where():
    sql = _sql_da_rota()
    arvore = pglast.parse_sql(sql)          # gramatica real: sintaxe invalida estoura aqui
    return pglast.prettify(sql).lower()


def test_a_consulta_e_sql_valido_de_postgres():
    """`prettify` so devolve texto se o parser aceitou a arvore inteira."""
    assert pglast.prettify(_sql_da_rota())


def test_esconde_programa_que_saiu_do_ar(where):
    """⚠️ Sem esta guarda o radar ressuscita programa fora de cartaz."""
    assert "ausente_desde is null" in where


def test_esconde_prazo_ja_vencido(where):
    """⚠️ A TABELA E FOTOGRAFIA DO DIA DA COLETA.

    Entre uma rodada e outra um prazo vence. Confiar so no corte do coletor
    deixaria a tela anunciando prazo morto — e o municipio montaria processo
    para nada.
    """
    # ⚠️ O "hoje" e o de BRASILIA, e nao o do servidor: `CURRENT_DATE` sai do
    # fuso da sessao do Postgres, que nos containers e UTC. Entre 21h e
    # meia-noite o dia ja virou la e o prazo sumiria uma noite antes.
    assert "dt_fim_receb >=" in where
    assert "america/sao_paulo" in where


def test_filtra_pela_UF_do_municipio(where):
    """⚠️ 9 dos 17 programas abertos sao regionais (medido em 02/09/2026)."""
    assert "any(ufs)" in where


def test_filtra_pela_natureza_da_prefeitura(where):
    """Consorcio publico e outra pessoa juridica; o prefeito nao assina por ele."""
    assert "any(naturezas)" in where
    assert R.NATUREZA_PREFEITURA == "Administração Pública Municipal"


def test_o_topo_do_WHERE_e_uma_cadeia_de_AND():
    """⚠️ A GUARDA QUE UM `in` NAO PEGARIA — e que ja pegou um defeito real.

    Um `OR` no TOPO do WHERE deixaria todas as substrings dos testes acima
    presentes e ainda assim liberaria a linha errada: basta uma perna ser
    verdadeira. Este teste olha a ARVORE — exige que a raiz do WHERE seja
    AND_EXPR, o que torna cada guarda obrigatoria.

    ⚠️ E POR QUE ELE NAO PROIBE `OR` EM QUALQUER LUGAR. A primeira versao
    proibia, por substring, e isso ACHOU UM DEFEITO DE VERDADE: o WHERE tinha
    `OR cardinality(ufs) = 0`, tratando array de UF vazio como "vale para todos"
    — um programa com UF perdida na coleta apareceria para TODO municipio do
    pais. Removido. Mas a proibicao cega tambem barrou, depois, um `OR`
    LEGITIMO e entre parenteses (`dt_ini_receb IS NULL OR <= hoje`), que e uma
    perna so da cadeia. A regra certa nao e "sem OR": e "o topo tem de ser AND",
    porque e isso que garante que nenhuma guarda pode ser dispensada.
    """
    raiz = _where_bruto()
    assert raiz.__class__.__name__ == "BoolExpr", (
        f"o topo do WHERE virou {raiz.__class__.__name__} — se nao e uma cadeia, "
        f"nao da para afirmar que toda guarda vale")
    # ⚠️ `.name`, e nao `str()`: `BoolExprType` e IntEnum, entao `str(boolop)`
    # devolve "0" e a comparacao com "AND_EXPR" seria SEMPRE falsa — um teste que
    # falha por engano e so barulho, mas o inverso (comparar com "0") passaria
    # tambem para OR_EXPR se a ordem do enum mudasse.
    assert raiz.boolop.name == "AND_EXPR", (
        f"o topo do WHERE e {raiz.boolop.name}, nao AND: alguma guarda pode ser "
        f"dispensada por outra")
    # ⚠️ ERAM 5 PERNAS, HOJE SAO 4, e nenhuma guarda foi perdida: as duas de data
    # (fim e inicio) viraram UMA perna, `porta_receb OR porta_emenda`, calculada
    # na CTE. O radar passou a carregar as duas portas — recebimento e emenda
    # parlamentar — e "aberto" deixou de ser uma data so. Quem garante que as
    # duas pontas de CADA janela continuam sendo exigidas e
    # `test_a_janela_de_inicio_tambem_e_guarda`, logo abaixo.
    assert len(raiz.args) >= 4, (
        f"o WHERE tem {len(raiz.args)} guardas no topo; sao 4 "
        f"(ausente_desde, portas, natureza, uf)")


# --------------------------------------------------------------------------
# O carimbo de coleta: consulta SEPARADA, e nao derivada do resultado
# --------------------------------------------------------------------------

def test_o_carimbo_de_coleta_nao_depende_do_filtro():
    """⚠️ ERA UM DEFEITO DE VERDADE, e o pior tipo: acusava pendencia inventada.

    `atualizado_em` saia de `max(visto_em)` das linhas JA FILTRADAS. Um
    municipio cuja UF nao tem nenhum programa aberto recebia lista vazia E
    carimbo nulo — e a tela usa o carimbo nulo para dizer "ainda nao coletamos
    aqui". Ou seja: radar coletado, funcionando, sem nada para aquela UF, se
    apresentava como coleta que nunca rodou.

    Sao dois fatos distintos: QUANDO olhamos nao depende do QUE achamos para
    voce. Por isso o carimbo virou consulta propria, sem WHERE de UF.
    """
    fonte = open(R.__file__, encoding="utf-8").read()
    carimbo = re.search(r'text\(\s*\n?\s*"SELECT max\(visto_em\)[^"]*"', fonte)
    assert carimbo, "a consulta do carimbo sumiu do router"
    sql = carimbo.group(0)
    assert "WHERE" not in sql.upper(), (
        "o carimbo ganhou um WHERE — se ele filtrar por UF, volta a confundir "
        "'nao ha programa para voce' com 'nunca coletamos'")
    # E o SELECT dos programas NAO pode mais trazer visto_em: se trouxer, alguem
    # voltou a derivar o carimbo dali.
    assert "visto_em" not in _sql_da_rota(), (
        "o SELECT dos programas voltou a ler visto_em — o carimbo tem consulta propria")


def test_a_janela_de_inicio_tambem_e_guarda():
    """"Aberto hoje" e estar DENTRO da janela, e nao apenas antes do fim.

    ⚠️ VALE PARA AS DUAS PORTAS. Desde 02/09/2026 o radar carrega tambem os
    programas abertos por EMENDA PARLAMENTAR (eram 67 invisiveis: o coletor
    descartava a linha olhando so `DT_PROG_FIM_RECEB_PROP`). Cada porta tem as
    suas duas pontas, e esquecer o `dt_ini` de UMA delas traria de volta o
    defeito que este teste existe para impedir — so que na porta nova, onde
    ninguem estaria olhando.
    """
    sql = pglast.prettify(_sql_da_rota()).lower()
    for porta in ("receb", "emenda", "benef"):
        assert f"dt_ini_{porta}" in sql, f"a ponta de INICIO da porta {porta} sumiu"
        assert f"dt_ini_{porta} <=" in sql, (
            f"`dt_ini_{porta}` aparece mas nao e comparado com hoje — a janela "
            f"voltou a ter um lado so")
        assert f"dt_fim_{porta} >=" in sql, f"a ponta de FIM da porta {porta} sumiu"

    # ⚠️ O FUSO E CALCULADO UMA VEZ SO, na CTE `hoje`, e reusado. A versao
    # anterior deste teste exigia `count("america/sao_paulo") >= 3` porque a
    # expressao se repetia a cada comparacao — e repeticao e como as pontas
    # passam a divergir (uma em UTC, outra em Brasilia, e um dia em que o
    # programa nao esta nem aberto nem fechado). Com uma fonte unica, a
    # divergencia deixa de ser possivel; o que este teste precisa garantir agora
    # e que ninguem volte a usar o dia do SERVIDOR.
    assert "america/sao_paulo" in sql, "o 'hoje' de Brasilia sumiu da consulta"
    assert "current_date" not in sql, (
        "voltou `CURRENT_DATE` — ele sai do fuso da sessao do Postgres, que nos "
        "containers e UTC: entre 21h e meia-noite o prazo que fecha HOJE some do "
        "radar na noite anterior")


def test_o_contador_do_menu_usa_o_MESMO_filtro_da_tela():
    """⚠️ A GUARDA QUE NASCEU COM O CONTADOR (04/09/2026).

    O menu mostra "Radar de captação · 7", e esse 7 vem de `/contagem`, um
    endpoint que só conta — a listagem inteira seria cara numa barra lateral
    renderizada em toda tela. Só que duas consultas para a mesma pergunta é
    exatamente como as respostas passam a divergir, e aqui a divergência tem
    consequência direta: o gestor clica em "7 oportunidades" e encontra seis.
    A partir daí ele não confia em nenhum número do sistema.

    Por isso a contagem tem de montar-se das MESMAS constantes — não de uma
    cópia do filtro, por mais idêntica que ela pareça no dia em que foi escrita.
    """
    fonte = open(R.__file__, encoding="utf-8").read()
    trecho = fonte[fonte.index("async def contagem"):]
    # Só o corpo da contagem: a ficha (18/09/2026), declarada abaixo, lê as
    # tabelas filhas `programas_captacao_*` — e isso não é a contagem.
    trecho = trecho[:trecho.index("\n# ---")]

    assert "_CTE_ABERTOS" in trecho, "a contagem não usa a CTE compartilhada"
    assert "_FILTRO_ABERTOS" in trecho, "a contagem não usa o filtro compartilhado"
    # E não pode ter reescrito o filtro por dentro: se aparecer um WHERE próprio
    # sobre a tabela, as duas respostas voltam a poder divergir.
    assert "FROM programas_captacao" not in trecho, (
        "a contagem voltou a ler a tabela por conta própria — ela deve partir "
        "de `base`, a CTE que a listagem também usa")
