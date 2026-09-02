"""O RADAR DE CAPTACAO: o corte que transforma 1,2 milhao de linhas em 9 programas.

⚠️ O ERRO CENTRAL QUE ESTE ARQUIVO IMPEDE E CONFUNDIR "PUBLICADO" COM "ABERTO".
Medido no arquivo real em 02/09/2026: 1.006.720 linhas trazem
SIT_PROGRAMA = DISPONIBILIZADO. Se o radar cortasse so por situacao, a tela
receberia um catalogo historico com cara de oportunidade. O que decide e a DATA:
`DT_PROG_FIM_RECEB_PROP >= hoje` derruba para 1.314 linhas, das quais 307 sao
municipais — e essas 307 sao **17 programas**, porque o arquivo repete o programa
uma vez por UF habilitada.

⚠️ E A UF E RESTRICAO DE VERDADE, nao metadado. Dos 17, 9 sao regionais:
"INFRA-ESTRUTURA BASICA SR(RS)" so aceita municipio gaucho. Sem o filtro, a tela
ofereceria a um prefeito mineiro uma porta que nao abre — o mesmo defeito que o
`programas_rs.py` ja documenta para o lado estadual.

⚠️ RODADA VAZIA NAO PODE MARCAR AUSENCIA. Um download truncado devolve zero
programa; marcar tudo como ausente esvaziaria o radar por causa de uma falha
NOSSA. O `run()` sai reclamando e nao toca no banco — testado abaixo com um
banco falso que registra tudo que receberia.

Rodar: python -m pytest backend/tests/test_radar_captacao.py -q
"""
from datetime import date

import pytest

pytest.importorskip("psycopg2")

from ingestion import programas_captacao as P  # noqa: E402

HOJE = date(2026, 9, 2)


def _linha(**kw):
    """Uma linha do siconv_programa.zip, com os padroes do caso feliz."""
    base = {
        "ID_PROGRAMA": "56385", "COD_PROGRAMA": "2629120260003",
        "NOME_PROGRAMA": "Programa X", "SIT_PROGRAMA": "DISPONIBILIZADO",
        "DESC_ORGAO_SUP_PROGRAMA": "MINISTERIO DA EDUCACAO",
        "COD_ORGAO_SUP_PROGRAMA": "26000",
        "MODALIDADE_PROGRAMA": "CONVENIO",
        "NATUREZA_JURIDICA_PROGRAMA": "Administração Pública Municipal",
        "UF_PROGRAMA": "MG", "ACAO_ORCAMENTARIA": "000020RJ",
        "NOME_SUBTIPO_PROGRAMA": "", "DESCRICAO_SUBTIPO_PROGRAMA": "",
        "DATA_DISPONIBILIZACAO": "03/05/2026", "ANO_DISPONIBILIZACAO": "2026",
        "DT_PROG_INI_RECEB_PROP": "10/03/2026",
        "DT_PROG_FIM_RECEB_PROP": "31/12/2026",
        "DT_PROG_INI_EMENDA_PAR": "", "DT_PROG_FIM_EMENDA_PAR": "",
    }
    base.update(kw)
    return base


# --------------------------------------------------------------- data_br ---

def test_data_br_le_o_formato_do_arquivo_e_iso():
    assert P.data_br("31/12/2026") == date(2026, 12, 31)
    assert P.data_br("2026-12-31") == date(2026, 12, 31)


@pytest.mark.parametrize("lixo", ["", "   ", None, "31-12-2026", "sem data", "0000-00-00"])
def test_data_br_devolve_None_no_lixo(lixo):
    """⚠️ Data ilegivel NAO pode virar hoje nem 2099.

    Virando hoje, o programa some da tela; virando 2099, fica aberto para sempre.
    None e o unico valor honesto, e o `agrupa` descarta a linha.
    """
    assert P.data_br(lixo) is None


# ---------------------------------------------------------------- agrupa ---

def test_o_corte_e_a_data_e_nao_a_situacao():
    """⚠️ O TESTE PRINCIPAL. Prazo vencido nao e oportunidade, mesmo
    DISPONIBILIZADO — e um milhao de linhas do arquivo estao nesse estado."""
    vencido = _linha(ID_PROGRAMA="1", DT_PROG_FIM_RECEB_PROP="31/12/2025")
    aberto = _linha(ID_PROGRAMA="2", DT_PROG_FIM_RECEB_PROP="31/12/2026")
    assert set(P.agrupa([vencido, aberto], HOJE)) == {"2"}


def test_o_prazo_de_hoje_ainda_conta():
    """`>= hoje`, e nao `>`: quem fecha hoje ainda da para protocolar."""
    assert P.agrupa([_linha(DT_PROG_FIM_RECEB_PROP="02/09/2026")], HOJE)


def test_situacao_diferente_de_disponibilizado_nao_entra():
    for sit in ("CADASTRADO", "INATIVO", ""):
        assert P.agrupa([_linha(SIT_PROGRAMA=sit)], HOJE) == {}


def test_natureza_de_fora_nao_entra():
    """Organizacao da Sociedade Civil e empresa publica nao sao a prefeitura."""
    for nat in ("Organização da Sociedade Civil",
                "Empresa pública/Sociedade de economia mista",
                "Administração Pública Estadual ou do Distrito Federal"):
        assert P.agrupa([_linha(NATUREZA_JURIDICA_PROGRAMA=nat)], HOJE) == {}


def test_consorcio_entra_na_coleta_mas_marcado():
    """Coletado com a natureza carimbada; quem filtra para a tela e o router."""
    d = P.agrupa([_linha(NATUREZA_JURIDICA_PROGRAMA="Consórcio Público")], HOJE)
    assert d["56385"]["naturezas"] == {"Consórcio Público"}


def test_uma_linha_por_UF_vira_UM_programa_com_as_UFs_juntas():
    """⚠️ 307 linhas municipais sao 17 programas. Sem o agrupamento, a tela
    mostraria o mesmo programa 27 vezes."""
    linhas = [_linha(UF_PROGRAMA=uf) for uf in ("MG", "SP", "RS", "MG")]
    d = P.agrupa(linhas, HOJE)
    assert len(d) == 1
    assert d["56385"]["ufs"] == {"MG", "SP", "RS"}


def test_prazo_do_programa_e_o_MAIS_LONGO_entre_as_linhas():
    """⚠️ Encurtar o programa pela linha mais restritiva o faria sumir da tela
    de quem ainda tem prazo. As UFs ficam no array; a data e a do programa."""
    d = P.agrupa([
        _linha(UF_PROGRAMA="MG", DT_PROG_FIM_RECEB_PROP="30/09/2026"),
        _linha(UF_PROGRAMA="SP", DT_PROG_FIM_RECEB_PROP="31/12/2026"),
    ], HOJE)
    assert d["56385"]["dt_fim_receb"] == date(2026, 12, 31)


def test_programa_sem_id_nao_entra():
    """Sem ID_PROGRAMA nao ha chave primaria — o upsert quebraria."""
    assert P.agrupa([_linha(ID_PROGRAMA="")], HOJE) == {}


def test_data_fim_ilegivel_derruba_a_linha():
    """Sem prazo legivel nao da para afirmar que esta aberto."""
    assert P.agrupa([_linha(DT_PROG_FIM_RECEB_PROP="sem data")], HOJE) == {}


def test_janela_de_emenda_e_guardada_separada_do_prazo_de_proposta():
    """São dois prazos e o gestor não cumpre o segundo sozinho — depende de um
    gabinete indicar. Somá-los num campo só apagaria essa diferença."""
    d = P.agrupa([_linha(DT_PROG_INI_EMENDA_PAR="01/01/2026",
                         DT_PROG_FIM_EMENDA_PAR="31/10/2026")], HOJE)
    p = d["56385"]
    assert p["dt_fim_emenda"] == date(2026, 10, 31)
    assert p["dt_fim_receb"] == date(2026, 12, 31)


def test_campos_do_arquivo_chegam_inteiros():
    d = P.agrupa([_linha()], HOJE)["56385"]
    assert d["nome"] == "Programa X"
    assert d["orgao"] == "MINISTERIO DA EDUCACAO"
    assert d["modalidade"] == "CONVENIO"
    assert d["ano_disponibilizacao"] == 2026
    assert d["raw"]["ID_PROGRAMA"] == "56385"


# ------------------------------------------------------------------- run ---

class _Cursor:
    """⚠️ `fetchone` DEVOLVE ZERO ATIVOS POR PADRAO, e a escolha importa: com
    zero no banco o piso proporcional nao dispara, entao o caso base continua
    exercitando a marcacao de ausencia. Os testes do piso sobrescrevem
    `fetchone` para simular um banco povoado."""

    def __init__(self):
        self.execs = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.execs.append((sql, params))

    def fetchone(self):
        return (0,)

    def close(self):
        pass


class _Conn:
    """⚠️ TEM `rollback` PORQUE O CODIGO REAL O CHAMA — e a primeira versao deste
    fake NAO tinha. O `AttributeError` era engolido pelo `except` do bloco de
    encerramento e a linha do `ingestion_log` deixava de ser gravada: o teste
    apontou uma fragilidade de verdade no coletor (rollback e log dividiam o
    mesmo `try`), que foi separada. Fake pobre demais esconde defeito; fake
    pobre demais que FALHA, revela."""

    def __init__(self, cur):
        self._c = cur
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self._c

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def _log(cur):
    """A tupla de parametros do INSERT no ingestion_log, ou None."""
    for sql, params in cur.execs:
        if "ingestion_log" in sql:
            return params
    return None


def test_rodada_vazia_nao_marca_ninguem_como_ausente(monkeypatch):
    """⚠️ O SEGUNDO TESTE MAIS IMPORTANTE DAQUI.

    Arquivo truncado, layout mudado ou TransfereGov fora do ar devolvem zero
    programa. Se o `run()` marcasse ausencia mesmo assim, o radar inteiro se
    apagaria por causa de uma falha nossa — e voltaria sozinho na rodada
    seguinte, o que faz o defeito parecer fantasma.
    """
    cur = _Cursor()
    monkeypatch.setattr(P, "_linhas", lambda _a: iter([]))
    monkeypatch.setattr(P.psycopg2, "connect", lambda _d: _Conn(cur))
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql://x/y")

    assert P.run() == 0
    sqls = " ".join(s for s, _ in cur.execs)
    assert "UPDATE programas_captacao" not in sqls, "marcou ausencia sobre rodada vazia"
    # ⚠️ E o log sai 'error'. Zero programa aberto no Brasil inteiro nao e um
    # resultado plausivel — tratar como 'success' pintaria verde sobre falha,
    # que foi o defeito encontrado em tres coletores na auditoria de 31/08.
    #
    # ⚠️ O STATUS E CONFERIDO NO PARAMETRO, e nao na string do SQL. A primeira
    # versao procurava `'error'` DENTRO do texto da consulta; quando o status
    # virou bind (%s), como manda a casa, o teste passou a nao achar nada e
    # falhou — mas se o bind tivesse vindo antes do teste, ele teria passado
    # cego para sempre, porque a substring nunca mais apareceria no SQL.
    p = _log(cur)
    assert p is not None, "rodada vazia saiu sem gravar ingestion_log"
    assert p[0] == P.FONTE
    assert p[1] == "error"
    assert p[2] == 0


def test_rodada_com_dado_grava_e_marca_os_que_sumiram(monkeypatch):
    cur = _Cursor()
    monkeypatch.setattr(P, "_linhas", lambda _a: iter([_linha(ID_PROGRAMA="7")]))
    monkeypatch.setattr(P.psycopg2, "connect", lambda _d: _Conn(cur))
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql://x/y")

    assert P.run() == 1
    sqls = [s for s, _ in cur.execs]
    assert any("INSERT INTO programas_captacao" in s for s in sqls)
    ausencia = next((s, p) for s, p in cur.execs if s.startswith("UPDATE programas_captacao"))
    # A ausencia e marcada por EXCLUSAO da lista vista — e a lista tem o "7".
    assert ausencia[1] == (["7"],)
    p = _log(cur)
    assert p is not None and p[1] == "success" and p[2] == 1


def test_o_upsert_RESSUSCITA_programa_que_voltou():
    """⚠️ `ausente_desde=NULL` no ON CONFLICT, verificado na ARVORE do SQL.

    Sem essa atribuicao, um programa marcado como ausente e depois REOFERECIDO
    pelo TransfereGov continuaria marcado para sempre: a coleta o encontraria,
    gravaria todos os campos novos, e a tela — que filtra `ausente_desde IS
    NULL` — nunca mais o mostraria. O radar perderia programa aberto em silencio,
    e cada rodada reforcaria o erro em vez de corrigi-lo.

    ⚠️ E POR QUE ISSO PRECISA DE TESTE PROPRIO. Os testes do `run()` conferem que
    o INSERT foi EXECUTADO (`"INSERT INTO programas_captacao" in sql`) e com
    quais parametros — nada disso olha o corpo do ON CONFLICT. Apagar a linha
    passava com a suite inteira verde; provado por mutacao em 02/09/2026.
    """
    pglast = pytest.importorskip("pglast")
    sql = P._SQL.replace("%s", "NULL")
    arvore = pglast.parse_sql(sql)[0].stmt          # sintaxe invalida estoura aqui
    alvos = [t.name for t in arvore.onConflictClause.targetList]
    assert "ausente_desde" in alvos, (
        "o ON CONFLICT parou de zerar `ausente_desde`: programa reoferecido "
        f"ficaria invisivel para sempre. Campos atualizados: {alvos}")
    assert "visto_em" in alvos, "sem `visto_em` o monitor de frescor congela"
    # E o conflito tem de ser na identidade do programa, nao em outra coisa.
    assert [i.name for i in arvore.onConflictClause.infer.indexElems] == ["id_programa"]


def test_prazo_divergente_entre_UFs_grita_no_log(caplog):
    """⚠️ O ALARME PARA O DIA EM QUE A FONTE MUDAR DE FORMA.

    A tabela guarda UM prazo por programa, e isso só é honesto porque as UFs do
    mesmo programa trazem a mesma data — medido em 02/09/2026: zero divergências
    entre os 17 abertos. Se um dia divergir, guardar a maior faria a tela
    anunciar a um município um prazo que não é dele. Este aviso é o que impede
    essa mudança de passar em silêncio.
    """
    with caplog.at_level("WARNING", logger="programas_captacao"):
        d = P.agrupa([
            _linha(UF_PROGRAMA="MG", DT_PROG_FIM_RECEB_PROP="30/09/2026"),
            _linha(UF_PROGRAMA="SP", DT_PROG_FIM_RECEB_PROP="31/12/2026"),
        ], HOJE)
    assert d["56385"]["dt_fim_receb"] == date(2026, 12, 31)
    assert "PRAZO DIFERENTE entre UFs" in caplog.text
    assert "56385" in caplog.text


def test_prazo_igual_entre_UFs_nao_gera_alarme(caplog):
    """O aviso acima só serve se NÃO disparar no caso normal — que é a regra."""
    with caplog.at_level("WARNING", logger="programas_captacao"):
        P.agrupa([_linha(UF_PROGRAMA="MG"), _linha(UF_PROGRAMA="SP")], HOJE)
    assert "PRAZO DIFERENTE" not in caplog.text


def test_queda_de_mais_da_metade_NAO_marca_ausencia(monkeypatch):
    """⚠️ O PISO PROPORCIONAL — o caso que o `if not progs` não pega.

    Rodada vazia já é barrada. O perigoso é o PARCIAL: um zip truncado que
    descomprime e traz 2 dos 17 programas passa por aquela guarda e derruba 15
    de uma vez. O radar esvazia quase todo e a tela diz "nenhum programa aberto
    para a sua UF hoje" — frase que se lê como informação, não como falha.
    """
    cur = _Cursor()
    conn = _Conn(cur)
    cur.fetchone = lambda: (17,)          # 17 ativos no banco...
    monkeypatch.setattr(P, "_linhas", lambda _a: iter([_linha(ID_PROGRAMA="7")]))
    monkeypatch.setattr(P.psycopg2, "connect", lambda _d: conn)
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql://x/y")

    assert P.run() == 1                    # ...e a rodada trouxe 1
    sqls = [s for s, _ in cur.execs]
    assert any("INSERT INTO programas_captacao" in s for s in sqls), \
        "os dados novos TEM de ser gravados; o que se suspende e so a ausencia"
    assert not any(s.startswith("UPDATE programas_captacao") for s in sqls), \
        "marcou ausencia numa queda de 17 para 1"
    # ⚠️ E o log sai 'partial': a rodada gravou dado bom mas deixou metade do
    # trabalho por fazer. 'success' esconderia isso num log que ninguem le.
    p = _log(cur)
    assert p[1] == "partial"
    assert "queda suspeita" in (p[3] or "")


def test_queda_pequena_marca_ausencia_normalmente(monkeypatch):
    """O piso não pode virar trava: programa que sai de cartaz TEM de sair."""
    cur = _Cursor()
    conn = _Conn(cur)
    cur.fetchone = lambda: (2,)           # 2 ativos, a rodada traz 1 -> 50%
    monkeypatch.setattr(P, "_linhas", lambda _a: iter([_linha(ID_PROGRAMA="7")]))
    monkeypatch.setattr(P.psycopg2, "connect", lambda _d: conn)
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql://x/y")

    assert P.run() == 1
    assert any(s.startswith("UPDATE programas_captacao") for s in cur.execs and
               [s for s, _ in cur.execs]), "deixou de marcar ausencia legitima"
    assert _log(cur)[1] == "success"


def test_rodada_que_estoura_no_meio_grava_error_e_nao_some(monkeypatch):
    """⚠️ EXCECAO NO MEIO TEM DE DEIXAR LINHA NO `ingestion_log`.

    Postgres fora, `timeout` do cron, zip corrompido: sem o `finally`, a rodada
    morria sem gravar nada — e o monitor de frescor NAO VE rodada que nao logou.
    A fonte envelheceria em silencio, que e o defeito que este coletor foi
    escrito para nao repetir. O status tem de ser 'error', nao 'success'.
    """
    cur = _Cursor()
    conn = _Conn(cur)

    def explode(sql, params=None):
        cur.execs.append((sql, params))
        if "INSERT INTO programas_captacao" in sql:
            raise RuntimeError("conexao caiu no meio")

    cur.execute = explode
    monkeypatch.setattr(P, "_linhas", lambda _a: iter([_linha(ID_PROGRAMA="7")]))
    monkeypatch.setattr(P.psycopg2, "connect", lambda _d: conn)
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql://x/y")

    with pytest.raises(RuntimeError):
        P.run()
    p = _log(cur)
    assert p is not None, "rodada interrompida saiu sem gravar ingestion_log"
    assert p[1] == "error"
    assert "interrompida" in (p[3] or "")
    assert conn.rollbacks == 1, "nao limpou a transacao antes de gravar o log"
