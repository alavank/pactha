"""A tela de Convênios e os exports usam O MESMO recorte.

⚠️ POR QUE ESTE ARQUIVO EXISTE. Em 03/09/2026 o dono relatou: marcava "apenas os
convênios em vigor" e o PDF saía com a base inteira. A causa não era filtro
perdido no caminho — `exportPdf` mandava só `municipio_id` e a rota não aceitava
mais nada. Parâmetro não declarado é simplesmente IGNORADO pelo FastAPI, sem
erro nenhum, e o aviso disso já estava escrito na rota vizinha
(`export_voluntarias_pdf`) desde antes.

⚠️ ESTA É A SEXTA VEZ QUE O PREDICADO DESTA TELA CAUSA UM DEFEITO. `_cond_fonte`
nasceu para matar quatro cópias da regra de fonte, e o comentário dela registra
que a duplicação "deixou o export PDF de fora e contar propostas de saude como
convenio". `export_pdf.py` se descrevia como "a QUINTA copia da mesma" e pedia,
por escrito, a unificação. Ela foi feita: `services/convenios_filtro.py`.

⚠️ O TESTE QUE NÃO ADIANTA. Contar ocorrências de `condicoes(` no fonte deixaria
passar exatamente o defeito de hoje: um parâmetro ESQUECIDO na assinatura do
export não muda contagem nenhuma — o service recebe `None`, o documento sai sem
aquele recorte, e o verde continua verde. Por isso aqui se comparam as
ASSINATURAS, nome a nome e anotação a anotação.
"""
import inspect
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from routers import convenios as R          # noqa: E402
from routers import export_pdf as E         # noqa: E402
from services import convenios_filtro as F  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent

# `page`/`per_page` são da paginação da tela; `formato` é só do export; o resto é
# encanamento do FastAPI. Tudo o que não estiver aqui TEM de existir dos dois lados.
_FORA = {"page", "per_page", "formato", "db", "current", "request"}


def _params(fn):
    return {n: p for n, p in inspect.signature(fn).parameters.items() if n not in _FORA}


def test_o_export_aceita_TODOS_os_filtros_da_tela():
    lista = _params(R.list_convenios)
    export = _params(E.export_convenios_pdf)
    faltando = sorted(set(lista) - set(export))
    assert not faltando, (
        f"o export não aceita {faltando} — a tela filtra por isso e o documento "
        f"sairia sem o recorte, em silêncio (o FastAPI ignora o que não declara)")


def test_o_export_nao_inventa_filtro_que_a_tela_nao_tem():
    sobrando = sorted(set(_params(E.export_convenios_pdf)) - set(_params(R.list_convenios)))
    assert not sobrando, (
        f"o export aceita {sobrando}, que a tela não manda — um recorte que "
        f"ninguém consegue reproduzir olhando a tela")


def test_os_tipos_batem_dos_dois_lados():
    """⚠️ Tipo errado não é detalhe: `anos` é list[int] contra coluna INT e as
    datas são `date`. Declarar como str manda bind de texto para o asyncpg — 500
    seco ou comparação diferente, sem nada na tela."""
    lista, export = _params(R.list_convenios), _params(E.export_convenios_pdf)
    # Exceção sancionada: a tela aceita "todos os municípios da carteira"
    # (`Optional[int]`), o export é sempre de UM município — é assim desde
    # sempre, e `ensure_municipio_access(current, None)` responderia 403 para
    # qualquer carteira restrita.
    divergentes = [
        n for n in sorted(set(lista) & set(export))
        if n != "municipio_id" and lista[n].annotation != export[n].annotation
    ]
    assert not divergentes, f"tipos divergem entre tela e export: {divergentes}"
    assert export["municipio_id"].annotation is int


def test_o_recorte_descreve_o_que_foi_APLICADO():
    """`vigencias` e `pagamentos` são dicionários de regras: valor desconhecido é
    descartado em silêncio. Descrever o PEDIDO faria um link velho do painel com
    `?vigencia=vence45` gerar documento que AFIRMA "Vence em 45 dias" sobre a
    base inteira — pior que o documento mudo de antes, porque mente por escrito."""
    conds, recorte = F.condicoes(municipio_id=1, vigencias=["vence45"])
    assert not any("45" in r for r in recorte), (
        "o recorte citou um filtro que o SQL não aplicou")
    conds_ok, recorte_ok = F.condicoes(municipio_id=1, vigencias=["vence30"])
    assert any("30 dias" in r for r in recorte_ok)
    # Um valor válido tem de acrescentar condição; um inválido, não.
    assert len(conds_ok) > len(conds)


def test_em_vigor_e_situacao_e_nao_vigencia():
    """⚠️ O ERRO QUE EU MESMO COMETI AO DIAGNOSTICAR, e por isso está travado.

    "Em vigor" NÃO é o filtro de vigência: `VIGENCIA_OPCOES` na tela é
    vence30/60/90/120 e prestacao. "Em vigor" é VALOR da coluna `situacao`,
    escrito pelo coletor (`sigcon_scraper.py:66` mapeia VIGENTE -> "Em vigor").
    Quem "consertar" só a vigência não conserta a queixa do dono, e o teste de
    aceitação escrito sobre `vigencias` passaria verde com o defeito vivo."""
    tela = (RAIZ.parent / "frontend" / "src" / "app" / "dashboard" / "convenios"
            / "page.tsx").read_text(encoding="utf-8")
    import re
    m = re.search(r"VIGENCIA_OPCOES\s*=\s*\[([^\]]*)\]", tela)
    assert m, "VIGENCIA_OPCOES sumiu da tela"
    assert "vigor" not in m.group(1).lower(), (
        "apareceu 'vigor' nas opções de vigência — se a semântica mudou, este "
        "teste e o cabeçalho de convenios_filtro.py precisam mudar junto")
    _, recorte = F.condicoes(municipio_id=1, situacoes=["Em vigor"])
    assert any("Em vigor" in r for r in recorte)


def test_a_ordem_do_export_e_a_mesma_da_tela():
    """Sem a mesma ordem, as MESMAS linhas saem embaralhadas: `_sort_key` empata
    muito e o `sort` do Python é estável, então os empates preservam a ordem de
    chegada — que é esta."""
    fonte_router = (RAIZ / "routers" / "convenios.py").read_text(encoding="utf-8")
    fonte_export = (RAIZ / "routers" / "export_pdf.py").read_text(encoding="utf-8")
    assert "filtro.ordem()" in fonte_router
    assert "filtro.ordem()" in fonte_export


def test_fonte_omitida_nao_e_ausencia_de_filtro():
    """⚠️ O único dos oito em que esquecer o parâmetro produz um conjunto ATIVO.
    Sem escolha, `cond_fonte` devolve "tudo menos FNS" — então um export que não
    recebesse `fontes` sairia SEM FNS com a tela mostrando FNS."""
    conds_sem, _ = F.condicoes(municipio_id=1)
    conds_fns, _ = F.condicoes(municipio_id=1, fontes=["FNS"])
    assert len(conds_sem) == len(conds_fns)      # a condição de fonte existe nos dois
    assert str(conds_sem[-1]) != str(conds_fns[-1])


def test_o_teto_do_export_e_o_mesmo_da_tela():
    """Teto maior que o da tela reproduz a assinatura do defeito histórico:
    2.000 na tela e 3.500 no arquivo, indistinguível de "o PDF não respeita o
    filtro"."""
    tela = (RAIZ.parent / "frontend" / "src" / "app" / "dashboard" / "convenios"
            / "page.tsx").read_text(encoding="utf-8")
    import re
    m = re.search(r"const PER_PAGE\s*=\s*(\d+)", tela)
    assert m, "PER_PAGE sumiu da tela"
    assert E.MAX_EXPORT_CONVENIOS <= int(m.group(1)), (
        f"o export leva até {E.MAX_EXPORT_CONVENIOS} e a tela mostra "
        f"{m.group(1)} — o arquivo traria linhas que a tela não mostrou")


def test_os_tres_formatos_usam_as_mesmas_colunas():
    from services import convenios_export as X
    chaves = [c[0] for c in X.COLUNAS]
    assert len(chaves) == len(set(chaves))
    linha = X.linha_de(type("C", (), {
        "raw_data": {}, "fonte": "SIGCON-MG", "nr_plano_trabalho": "123",
        "nr_sigcon": "9/2026", "orgao_concedente": "SEDESE", "objeto": "Praça",
        "objetivo": None, "situacao": "Em vigor", "valor_concedente": 10.0,
        "valor_total": 20.0, "dt_vigencia_inicial": date(2026, 1, 1),
        "dt_vigencia_atual": date(2026, 12, 31), "dt_vigencia_final": None,
    })())
    assert set(linha) == set(chaves), "a linha e as colunas divergiram"
    # `objetivo` tem precedência sobre `objeto` (dialeto do ES); com objetivo
    # nulo, cai para objeto — o caso de MG.
    assert linha["objeto"] == "Praça"
    assert linha["repasse"] == 10.0
