"""As guardas das TRES consultas do `_faf` — verificadas na ARVORE do SQL.

⚠️ ESTE ARQUIVO EXISTE PORQUE OS TESTES DO `test_investsus_faf.py` ERAM CEGOS
PARA O SQL, e a cegueira foi provada por mutacao em 02/09/2026. As tres mutacoes
abaixo passavam com a suite inteira verde:

    tirar `AND ano = :a`        -> a tela soma 2026 COM 2025 e publica um total
                                   que nao existe em ano nenhum;
    tirar `WHERE municipio_id`  -> o dinheiro de saude de OUTRA prefeitura
                                   aparece na tela desta;
    trocar o filtro dos anos    -> o seletor de anos lista anos que sao de outro
                                   municipio.

Nenhuma delas quebrava nada, porque aqueles testes exercitam o AGRUPAMENTO com
um banco falso: eles conferem o que o `_faf` faz com as linhas que RECEBE, e o
fake devolve as linhas que o teste escolheu. O filtro vive no SQL, e o SQL
nunca era lido — o fake respondia igual com ou sem WHERE.

⚠️ E O TESTE DE VAZAMENTO ERA O MAIS ENGANOSO. `test_consulta_e_filtrada_pelo_
municipio_pedido` afirma `all(p.get("m") == 77 ...)`: ele confere que o
PARAMETRO foi passado, e nao que a consulta o USA. Apagar o `WHERE` do SQL
deixa o bind intacto — o teste continua verde enquanto o banco devolve o
municipio inteiro. Parametro passado nao e filtro aplicado.

Nao ha Postgres de teste neste repo (SQL se valida com `pglast`), entao a via e
a mesma do `test_radar_router_guardas.py`: parsear com a gramatica real e exigir
a estrutura.

Rodar: python -m pytest backend/tests/test_investsus_faf_guardas.py -q
"""
import re

import pytest

pglast = pytest.importorskip("pglast")

from routers import investsus as R  # noqa: E402


def _consultas() -> list[str]:
    """Toda consulta do router que le `fns_repasse_faf`, com os binds trocados.

    Pega por CONTEUDO e nao por posicao: acrescentar outra consulta ao arquivo
    nao pode fazer este teste passar a proteger a errada, em silencio.

    ⚠️ O `(?<!:)` no regex e obrigatorio — sem ele o cast `::date` do Postgres
    viraria `:'date'` e o parser recusaria a consulta inteira, fazendo o teste
    falhar por defeito proprio em vez de por guarda ausente.
    """
    fonte = open(R.__file__, encoding="utf-8").read()
    # ⚠️ UMA ALTERNANCIA SO, e o bloco triplo PRIMEIRO. Com duas buscas
    # separadas o `"""..."""` casava tambem na segunda (ele contem aspas) e a
    # mesma consulta era contada duas vezes — o teste falhava por defeito
    # proprio, dizendo "achei 3" onde ha 2.
    blocos = re.findall(r'text\(\s*(""".*?"""|(?:"[^"]*"\s*)+)\s*\)', fonte, re.S)
    achadas = [re.sub(r"(?<!:):(\w+)", r"'\1'", b.strip('"').replace('"', " "))
               for b in blocos if "fns_repasse_faf" in b]
    assert len(achadas) == 3, (
        f"esperava 3 consultas a fns_repasse_faf no router, achei {len(achadas)} "
        f"— se o numero mudou de proposito, ajuste este teste junto")
    return achadas


def _wheres():
    """Os nos de WHERE das duas consultas, achatados em lista de condicoes."""
    saida = []
    for sql in _consultas():
        w = pglast.parse_sql(sql)[0].stmt.whereClause
        assert w is not None, f"consulta SEM WHERE nenhum:\n{sql}"
        if w.__class__.__name__ == "BoolExpr":
            assert w.boolop.name == "AND_EXPR", (
                "o topo do WHERE nao e AND — alguma guarda pode ser dispensada")
            saida.append(list(w.args))
        else:
            saida.append([w])
    return saida


def test_as_tres_consultas_sao_sql_valido():
    for sql in _consultas():
        assert pglast.prettify(sql)


def test_toda_consulta_filtra_pelo_MUNICIPIO():
    """⚠️ A GUARDA MAIS IMPORTANTE DO REPO INTEIRO NESTA TELA.

    Sem ela, um usuario ve o dinheiro de saude de outra prefeitura — e a carteira
    do freitas tem 60 municipios, entao nao e hipotese remota. O teste antigo
    conferia o PARAMETRO; parametro passado nao e filtro aplicado.
    """
    for i, condicoes in enumerate(_wheres()):
        texto = " ".join(pglast.prettify(_consultas()[i]).lower().split())
        assert "municipio_id = 'm'" in texto, (
            f"a consulta {i + 1} nao filtra por municipio_id:\n{texto}")
        assert len(condicoes) >= 1


def test_a_consulta_das_LINHAS_filtra_tambem_pelo_ANO():
    """⚠️ Sem `AND ano = :a` a tela SOMA os anos.

    O total do municipio viraria 2026 + 2025 + ... — um numero que nao existe em
    ano nenhum, exibido embaixo do rotulo "Total repassado no ano". O seletor de
    anos continuaria funcionando (ele so muda `alvo`), entao a tela pareceria
    certa: trocar o ano nao mudaria o valor, e ninguem estranha um total grande.
    """
    # ⚠️ `bloco_codigo` DEIXOU DE IDENTIFICAR esta consulta: a serie historica
    # tambem usa a coluna, dentro do NOT EXISTS que remove a linha de total do
    # bloco. Quem a identifica e o `grupo_nome` do SELECT, que so ela projeta.
    linhas = next(s for s in _consultas() if "grupo_nome" in s)
    texto = " ".join(pglast.prettify(linhas).lower().split())
    assert "ano = 'a'" in texto, f"filtro de ano ausente:\n{texto}"


def test_a_consulta_dos_ANOS_e_do_municipio_pedido():
    """O seletor da tela nao pode listar ano que e de outro municipio."""
    anos = next(s for s in _consultas() if "distinct ano" in s.lower())
    texto = " ".join(pglast.prettify(anos).lower().split())
    assert "municipio_id = 'm'" in texto
    # E ordenado do mais recente para o mais antigo: o `alvo` padrao e `anos[0]`,
    # entao inverter a ordem faria a tela abrir no ano mais VELHO.
    assert "order by ano desc" in texto


def test_a_SERIE_historica_nao_soma_dinheiro_duas_vezes():
    """⚠️ A serie e o unico lugar do router que agrega SEM filtrar por ano.

    Por isso ela precisa da mesma protecao do laco: `grupo_codigo = 0` e a linha
    de TOTAL do bloco, gravada quando o portal nao detalhou grupos, e convive
    com as linhas de grupo. Somar as duas contaria o mesmo repasse duas vezes —
    e a barra do historico mostraria um ano com o dobro do dinheiro que existiu,
    justamente na tela que o gestor usa para comparar ano a ano.
    """
    serie = next(s for s in _consultas() if "group by ano" in s.lower())
    texto = " ".join(pglast.prettify(serie).lower().split())
    assert "grupo_codigo <> 0" in texto, (
        f"a serie soma a linha de total do bloco junto com os grupos:\n{texto}")
    assert "not exists" in texto, (
        "sem o NOT EXISTS, bloco que veio SO com o total do bloco some da serie")
    assert "municipio_id = 'm'" in texto
    # Quatro anos: e o recorte que a tela desenha. Mais que isso nao cabe na
    # barra; menos esconde justamente o ano em que o desconto mudou de patamar.
    assert "limit 4" in texto
