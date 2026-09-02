"""O modulo AGENDAMENTOS: as invariantes que atravessam arquivo.

Nao ha Postgres aqui, entao o que da para garantir e a FORMA do que vai rodar —
e, neste modulo, quase todo defeito possivel e de forma:

⚠️ OS TRES STATUS VIVEM EM TRES LUGARES. `routers/agendamentos.STATUS` (o que o
router aceita), o CHECK de `add_agendamentos.sql` (o que o banco aceita) e as
colunas do kanban na tela. Se o Python aceitar um valor que o banco recusa, o
usuario leva 500 ao arrastar o cartao; se o banco aceitar um que o Python nao
conhece, o agendamento some do quadro — nao aparece em coluna nenhuma, e sem
erro. Este arquivo le o SQL e compara.

⚠️ O `dados_b64` NAO PODE SAIR NA LISTAGEM NEM NO DETALHE. E a diferenca entre
ter e nao ter a permissao `agendamentos.anexo_baixar`: se o GET devolver o
base64 embutido, quem so tem `ver` ja recebeu o arquivo e a caixinha vira
promessa vazia. O modulo de Gestao tem esse buraco ABERTO e assumido por escrito
(routers/gestao.py); aqui ele foi fechado, e este teste e o que impede alguem de
reabri-lo copiando o molde.

⚠️ A LISTA E A EXPORTACAO TEM DE USAR O MESMO FILTRO. O dono pediu "exportar
conforme o filtro"; duas montagens de WHERE divergem no primeiro ajuste, e a
divergencia aparece como "o relatorio veio com um agendamento a mais", sem nada
para culpar.

Rodar: python -m pytest backend/tests/test_agendamentos.py -q
"""
import re
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from routers import agendamentos as R  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent
SQL = (BACKEND / "migrations" / "add_agendamentos.sql").read_text(encoding="utf-8")
FONTE = Path(R.__file__).read_text(encoding="utf-8")


# ------------------------------------------------- os status, nos 3 lugares --

def test_os_status_do_python_sao_os_do_CHECK_do_banco():
    """⚠️ A INVARIANTE PRINCIPAL DESTE ARQUIVO.

    Python aceitando o que o banco recusa = 500 ao arrastar o cartao.
    Banco aceitando o que o Python nao conhece = agendamento invisivel no
    kanban, sem erro nenhum. Os dois lados tem de ser a MESMA lista.
    """
    m = re.search(r"CHECK\s*\(\s*status\s+IN\s*\(([^)]+)\)", SQL, re.I)
    assert m, "o CHECK de status sumiu da migration"
    do_banco = tuple(re.findall(r"'([a-z_]+)'", m.group(1)))
    assert do_banco == R.STATUS, (
        f"o banco aceita {do_banco} e o router aceita {R.STATUS}")


def test_todo_status_tem_rotulo_para_a_tela():
    """Status sem rotulo vira coluna sem nome no kanban."""
    assert set(R.STATUS_ROTULO) == set(R.STATUS)
    assert all(R.STATUS_ROTULO[s].strip() for s in R.STATUS)


def test_o_default_da_coluna_e_um_status_valido():
    """`DEFAULT 'a_fazer'` tem de estar na lista, senao todo INSERT sem status
    explicito e recusado pelo proprio CHECK — e o INSERT do router nao manda
    status quando o formulario nao escolhe."""
    m = re.search(r"status\s+VARCHAR\(\d+\)\s+NOT NULL\s+DEFAULT\s+'([a-z_]+)'", SQL, re.I)
    assert m, "o DEFAULT de status sumiu"
    assert m.group(1) in R.STATUS


@pytest.mark.parametrize("ruim", ["", "pendente", "A_FAZER", "feito", None, 0])
def test_status_invalido_e_recusado_antes_do_banco(ruim):
    """422 com a lista dos validos, e nao 500 vindo do CHECK: o erro do banco
    sobe como "violates check constraint", que nao diz nada a quem le."""
    if ruim is None:
        return  # None = "nao mexer no status" no PUT, e caso legitimo
    with pytest.raises(Exception) as e:
        R._valida(R.StatusUpdate(status=str(ruim)))
    assert getattr(e.value, "status_code", None) == 422


# ------------------------------------------------------------ o anexo -------

def test_a_listagem_e_o_detalhe_NAO_devolvem_o_base64():
    """⚠️ O BURACO QUE O MOLDE TEM E ESTE MODULO NAO PODE TER.

    Com `dados_b64` na resposta do GET, quem tem apenas `agendamentos.ver` ja
    recebeu o arquivo — e a caixinha `anexo_baixar`, que existe justamente para
    separar "ver que ha um anexo" de "receber o documento", nao separa nada.
    """
    linha = (1, 7, "Monte Sião", 3, "Maria", "Visita", "relato", date(2026, 9, 15),
             "a_fazer", [{"nome": "of.pdf", "mime": "application/pdf",
                          "tamanho": 100, "dados_b64": "SEGREDO"}],
             2, "João", None, None)
    d = R._row_to_dict(linha, with_anexos=False)
    assert d["anexos"] == [{"nome": "of.pdf", "mime": "application/pdf", "tamanho": 100}]
    assert "SEGREDO" not in str(d)

    # ⚠️ E O PADRAO DO PARAMETRO E O LADO SEGURO. A primeira versao deste
    # modulo tinha `with_anexos: bool = True` e obrigava cada chamada a lembrar
    # de desligar — uma chamada nova esquecida vazaria o base64 em silencio.
    # Com `False` por padrao, o descuido omite em vez de vazar.
    assert "with_anexos: bool = False" in FONTE, (
        "o padrao de `_row_to_dict` voltou a ser True — quem esquecer o "
        "argumento passa a vazar o conteudo do anexo")
    # E nenhuma chamada pode pedir o base64 sem que isso esteja escrito.
    for trecho in re.findall(r"_row_to_dict\(([^)]*)\)", FONTE):
        assert "with_anexos=True" not in trecho, (
            f"chamada pedindo o base64: {trecho!r} — se for de proposito, "
            f"escreva o porque e ajuste este teste")


def test_o_teto_do_anexo_e_o_mesmo_do_modulo_de_gestao():
    """Dois limites diferentes para o mesmo tipo de arquivo fariam a pessoa
    aprender o limite num modulo e ser recusada no outro."""
    gestao = (BACKEND / "routers" / "gestao.py").read_text(encoding="utf-8")
    m = re.search(r"MAX_ANEXO_BYTES\s*=\s*(\d+)\s*\*\s*1024\s*\*\s*1024", gestao)
    assert m, "o teto do gestao mudou de forma — conferir este teste"
    assert R.MAX_ANEXO_BYTES == int(m.group(1)) * 1024 * 1024


def test_anexo_grande_demais_e_413_com_o_nome_do_arquivo():
    """413 e nao 500, e a mensagem diz QUAL arquivo — com tres anexos, "excedeu
    o limite" sem o nome obriga a pessoa a tentar de novo por eliminacao."""
    grande = R.Anexo(nome="scan.pdf", mime="application/pdf",
                     dados_b64="x" * (R.MAX_ANEXO_BYTES + 1))
    with pytest.raises(Exception) as e:
        R._valida(R.AgendamentoCreate(municipio_id=1, titulo="t",
                                      data=date(2026, 9, 1), anexos=[grande]))
    assert getattr(e.value, "status_code", None) == 413
    assert "scan.pdf" in str(e.value.detail)


def test_o_rotulo_da_trilha_nunca_leva_o_conteudo():
    """O `audit_log` nao se apaga, por decisao do dono: um base64 la dentro sao
    megabytes permanentes por anexo."""
    rot = R._rotulo_anexos([{"nome": "a.pdf", "mime": "application/pdf",
                             "tamanho": 9, "dados_b64": "SEGREDO"}])
    assert rot == [{"nome": "a.pdf", "mime": "application/pdf", "tamanho": 9}]
    assert "SEGREDO" not in str(rot)


# ------------------------------------------------------------ o filtro ------

def test_filtro_vazio_nao_inventa_WHERE():
    onde, params = R._filtros(None, None, None, None, None)
    assert onde == "" and params == {}


def test_cada_filtro_vira_uma_condicao_com_bind():
    onde, params = R._filtros(7, date(2026, 9, 1), date(2026, 9, 30),
                              "a_fazer", 3)
    for pedaco in ("a.municipio_id = :m", "a.data >= :de", "a.data <= :ate",
                   "a.status = :s", "a.responsavel_id = :r"):
        assert pedaco in onde
    assert params == {"m": 7, "de": date(2026, 9, 1), "ate": date(2026, 9, 30),
                      "s": "a_fazer", "r": 3}
    # Tudo por BIND: valor de usuario nunca entra concatenado no SQL.
    assert "'" not in onde


def test_a_lista_e_a_exportacao_usam_A_MESMA_funcao_de_filtro():
    """⚠️ O dono pediu "exportar conforme o filtro". Duas montagens de WHERE
    divergem no primeiro ajuste, e a divergencia aparece como "o relatorio veio
    com um agendamento a mais" — sem nada para culpar."""
    chamadas = re.findall(r"_filtros\(", FONTE)
    # 1 definicao + 2 usos (listar e exportar)
    assert len(chamadas) == 3, (
        f"{len(chamadas)} referencias a _filtros; esperava 3 (a definicao, a "
        f"lista e a exportacao). Alguem montou um filtro proprio?")
    assert "onde, params = _filtros(" in FONTE


def test_a_exportacao_tem_teto_de_linhas():
    """Sem teto, um filtro largo monta um PDF de milhares de paginas na memoria
    de um container que divide 2 vCPU com outros 42."""
    assert isinstance(R.MAX_EXPORT, int) and R.MAX_EXPORT > 0
    assert "len(rows) > MAX_EXPORT" in FONTE


# ------------------------------------------------- a ordem da agenda --------

def test_a_lista_e_ordenada_do_mais_PROXIMO_para_o_mais_distante():
    """As outras telas do repo ordenam por `updated_at DESC` porque mostram
    historico. Aqui e uma AGENDA: `DESC` poria o mes que vem no topo e o
    compromisso de amanha no fim."""
    assert "ORDER BY a.data ASC" in FONTE
    assert "updated_at DESC" not in FONTE


# ------------------------------------------- o pedido "todos os MEUS" -------

def test_sem_municipio_o_recorte_e_a_carteira_da_pessoa():
    """⚠️ O DEFEITO QUE ESTE TESTE FECHA JA FOI PARA PRODUCAO.

    A opcao «Todos os meus municipios» mandava a consulta sem `municipio_id`.
    O router chamava `ensure_municipio_access(current, None)`, que levanta 403
    ("Selecione um municipio permitido") para toda carteira restrita — e
    carteira so e `None` no super-admin da Alavank. Resultado: a opcao respondia
    403 para 100% dos usuarios reais do tenant, e o comentario da tela afirmava
    que o backend fazia um recorte que NAO EXISTIA no router.

    Agora "todos" significa TODOS OS MEUS, com o desenho que o
    `routers/convenios.py` ja usava.
    """
    class U:
        allowed_municipio_ids = {5, 12, 30}

    permitidos, vazia = R._carteira(U(), None)
    assert vazia is False
    assert sorted(permitidos) == [5, 12, 30]
    onde, params = R._filtros(None, None, None, None, None, permitidos)
    assert "a.municipio_id = ANY(:mids)" in onde
    assert sorted(params["mids"]) == [5, 12, 30]


def test_super_admin_sem_municipio_nao_ganha_filtro():
    """Carteira `None` é o alcance total da conta de suporte — filtrar por uma
    lista vazia esconderia dela justamente o que ela existe para ver."""
    class U:
        allowed_municipio_ids = None

    permitidos, vazia = R._carteira(U(), None)
    assert permitidos is None and vazia is False
    onde, _ = R._filtros(None, None, None, None, None, permitidos)
    assert onde == ""


def test_carteira_VAZIA_devolve_vazio_e_nao_o_tenant_inteiro():
    """⚠️ O FAIL-CLOSED. Sem este ramo, quem nao alcanca municipio nenhum cairia
    no mesmo caminho do super-admin — consulta sem WHERE, tenant inteiro."""
    class U:
        allowed_municipio_ids = set()

    permitidos, vazia = R._carteira(U(), None)
    assert vazia is True and permitidos is None


def test_com_municipio_escolhido_quem_valida_e_o_ensure():
    """Com municipio no pedido, `_carteira` sai de cena: o filtro e ele, e o
    acesso e conferido por `ensure_municipio_access` — que NEGA nos dois modos
    de AUTHZ_MODO. Trocar o valor do <select> no navegador da 403."""
    class U:
        allowed_municipio_ids = {5}

    assert R._carteira(U(), 9) == (None, False)
    # ⚠️ TODA chamada de `ensure_municipio_access` tem de vir guardada por
    # `if municipio_id:`. A primeira versao deste teste procurava a string no
    # arquivo INTEIRO: com o guard removido da `listar` e mantido na
    # `exportar`, ele continuava achando e passava — o defeito original voltava
    # sem quebrar nada. Provado por mutacao; por isso agora e uma varredura de
    # TODAS as ocorrencias, e nao um `in`.
    chamadas = [m for m in re.finditer(r"^\s*ensure_municipio_access\(", FONTE, re.M)]
    assert len(chamadas) == 2, (
        f"{len(chamadas)} chamadas de ensure_municipio_access; eram 2 "
        f"(a lista e a exportacao)")
    for m in chamadas:
        anterior = FONTE[:m.start()].rstrip().splitlines()[-1].strip()
        assert anterior.startswith("if municipio_id"), (
            f"chamada INCONDICIONAL de ensure_municipio_access, precedida por "
            f"{anterior!r}. Com `municipio_id=None` ela levanta 403 para toda "
            f"carteira restrita — e era esse o defeito que matava a opcao "
            f"«Todos os meus municipios»")


def test_a_lista_e_a_exportacao_aplicam_O_MESMO_recorte():
    """O arquivo tem de trazer as linhas da tela, e isso inclui a carteira."""
    assert FONTE.count("permitidos, vazia = _carteira(") == 2
    assert FONTE.count("responsavel_id,\n                            permitidos)") == 2


# ------------------------------------ o SQL bate com o ESQUEMA de verdade ---

def test_o_select_so_usa_coluna_que_existe_no_modelo():
    """⚠️ ESTE TESTE NASCEU DE UM ERRO EM PRODUCAO, e o erro foi de vocabulario.

    `municipios` tem `nome` (portugues) e `users` tem `name` (ingles). O
    `_SELECT` fazia `ur.nome` / `uc.nome` e a tela do cliente respondeu
    `ProgrammingError` — coluna inexistente.

    ⚠️ E POR QUE A SUITE INTEIRA DEIXOU PASSAR: os testes de arvore validam a
    GRAMATICA do SQL com `pglast`, que nao conhece esquema nenhum. `ur.nome` e
    SQL perfeitamente valido; so nao existe naquela tabela. Sem Postgres de
    teste, a unica forma de cercar isso e cruzar o SQL com os MODELOS
    SQLAlchemy, que sao a definicao das colunas que o `create_all` cria.
    """
    from models.municipio import Municipio
    from models.user import User

    colunas = {
        "a": None,   # `agendamentos` nao tem modelo: nasce da migration
        "m": {c.name for c in Municipio.__table__.columns},
        "ur": {c.name for c in User.__table__.columns},
        "uc": {c.name for c in User.__table__.columns},
    }
    # ⚠️ SEM OS COMENTARIOS. O `_SELECT` traz uma nota `--` que CITA `ur.nome`
    # como exemplo do erro que este teste pega; varrer o texto cru fazia o teste
    # falhar por causa da propria explicacao. Comentario nao vai para o banco.
    sql = re.sub(r"--[^\n]*", "", R._SELECT)
    usadas = re.findall(r"\b(a|m|ur|uc)\.([a-z_]+)", sql)
    assert usadas, "nao achei referencias de coluna no _SELECT"
    for alias, coluna in usadas:
        esperadas = colunas[alias]
        if esperadas is None:
            continue
        assert coluna in esperadas, (
            f"`{alias}.{coluna}` nao existe no modelo. Colunas de {alias}: "
            f"{sorted(esperadas)}. ⚠️ `municipios` usa `nome` e `users` usa "
            f"`name` — a troca das duas e o erro que este teste existe para pegar")


def test_as_colunas_de_agendamentos_batem_com_a_migration():
    """O alias `a` nao tem modelo (a tabela nasce da migration), entao a
    referencia e o proprio CREATE TABLE."""
    corpo = SQL.split("CREATE TABLE IF NOT EXISTS agendamentos (", 1)[1].split(");", 1)[0]
    do_banco = set(re.findall(r"^\s{4}([a-z_]+)\s", corpo, re.M))
    assert "titulo" in do_banco and "relato" in do_banco, (
        f"nao consegui ler as colunas da migration: {sorted(do_banco)}")
    usadas = {c for al, c in re.findall(r"\b(a)\.([a-z_]+)", R._SELECT)}
    faltam = usadas - do_banco
    assert not faltam, f"o _SELECT usa coluna que a migration nao cria: {sorted(faltam)}"
