"""Migration que ALTERA uma tabela tem de vir DEPOIS da que a CRIA.

Achado no primeiro boot do tenant `novapalma-rs` (01/09/2026), o quinto banco
criado do zero:

    Migration add_detalhe_pagina_rodizio.sql falhou:
        relation "scraper_municipio_coleta" does not exist

`add_detalhe_pagina_rodizio.sql` estava na posicao 90 da MIGRATION_FILES e
`add_scraper_municipio_coleta.sql`, que CRIA a tabela, na 151.

Em tenant ANTIGO isso nunca doeu: a tabela ja existia de um deploy anterior, e a
ordem so importa na primeira vez. Em banco NOVO a migration falha — e o runner
ENGOLE a falha e segue, entao o tenant nasce sem a coluna e o laco de detalhe do
SIGCON passa a reler so a pagina 1. Em silencio, que e justamente o defeito que
aquela migration existe para consertar.

E a mesma familia de armadilha que o Santa Maria expos em 08/2026 quando foi o
primeiro banco criado do zero. Este teste existe para que o SEXTO tenant nao
descubra a proxima por acidente.
"""
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGR = os.path.join(RAIZ, "migrations")

_CREATE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)", re.I)
_ALTER = re.compile(r"ALTER\s+TABLE\s+(?:ONLY\s+)?([a-z_][a-z0-9_]*)", re.I)
_INDEX = re.compile(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?"
                    r"(?:IF\s+NOT\s+EXISTS\s+)?\S+\s+ON\s+([a-z_][a-z0-9_]*)", re.I)


def _sql(nome):
    caminho = os.path.join(MIGR, nome)
    if not os.path.exists(caminho):
        return ""
    txt = open(caminho, encoding="utf-8", errors="replace").read()
    # tira comentario de linha: eles citam nome de tabela em prosa
    return "\n".join(l for l in txt.splitlines() if not l.lstrip().startswith("--"))


def test_toda_tabela_alterada_ja_foi_criada_antes():
    """⚠️ Percorre a MIGRATION_FILES NA ORDEM e vai acumulando as tabelas que
    ja existem. Uma migration que ALTERA (ou indexa) tabela ainda nao criada por
    nenhuma anterior reprova.

    Tabela que NENHUMA migration cria e ignorada: vem do `create_all` dos
    modelos SQLAlchemy, que roda ANTES da lista (ver services/startup.py)."""
    from services.startup import MIGRATION_FILES

    criadas_por = {}
    for nome in MIGRATION_FILES:
        for t in _CREATE.findall(_sql(nome)):
            criadas_por.setdefault(t.lower(), nome)

    vistas = set()
    faltas = []
    for nome in MIGRATION_FILES:
        sql = _sql(nome)
        # ⚠️ AS CRIACOES DO PROPRIO ARQUIVO ENTRAM PRIMEIRO. Quase toda migration
        # de tabela nova faz CREATE e, logo abaixo, o CREATE INDEX dela — isso e
        # correto e roda na mesma transacao. Conferir os ALTER antes de registrar
        # os CREATE deste arquivo reprovava 30 migrations sadias e escondia a
        # unica de verdade.
        vistas |= {t.lower() for t in _CREATE.findall(sql)}
        for t in {x.lower() for x in _ALTER.findall(sql) + _INDEX.findall(sql)}:
            # so cobra tabela que ALGUMA migration cria; o resto vem do create_all
            if t in criadas_por and t not in vistas:
                faltas.append(f"{nome} mexe em '{t}', criada só por "
                              f"{criadas_por[t]} (mais adiante na lista)")

    assert not faltas, (
        "migration depende de tabela criada DEPOIS dela — quebra em banco novo "
        "e o runner engole a falha:\n  " + "\n  ".join(faltas))


def test_o_caso_que_originou_o_teste_esta_na_ordem_certa():
    """A regressao concreta do novapalma-rs, cravada por nome."""
    from services.startup import MIGRATION_FILES
    i_cria = MIGRATION_FILES.index("add_scraper_municipio_coleta.sql")
    i_usa = MIGRATION_FILES.index("add_detalhe_pagina_rodizio.sql")
    assert i_cria < i_usa, (
        "add_detalhe_pagina_rodizio.sql (posicao %d) ALTERA a tabela que "
        "add_scraper_municipio_coleta.sql (posicao %d) cria" % (i_usa, i_cria))


def test_a_deteccao_realmente_enxerga_o_par_do_incidente():
    """⚠️ Teste da FERRAMENTA. Se as regexes nao casassem nada, o teste de cima
    passaria para sempre e diria que a lista esta sa — o modo de falha exato que
    este arquivo existe para impedir."""
    cria = _sql("add_scraper_municipio_coleta.sql")
    usa = _sql("add_detalhe_pagina_rodizio.sql")
    assert cria, "nao consegui ler add_scraper_municipio_coleta.sql"
    assert usa, "nao consegui ler add_detalhe_pagina_rodizio.sql"
    assert "scraper_municipio_coleta" in {t.lower() for t in _CREATE.findall(cria)}, \
        "a regex de CREATE TABLE nao acha a tabela do incidente"
    alvo = {t.lower() for t in _ALTER.findall(usa) + _INDEX.findall(usa)}
    assert "scraper_municipio_coleta" in alvo, \
        "a regex de ALTER/INDEX nao acha a tabela do incidente"
