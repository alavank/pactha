"""O modulo AGENDAMENTOS: as invariantes que atravessam arquivo.

Nao ha Postgres aqui, entao o que da para garantir e a FORMA do que vai rodar —
e, neste modulo, quase todo defeito possivel e de forma:

⚠️ A PALETA E AS COLUNAS DO KANBAN VIVEM EM DOIS LUGARES. `routers/agendamentos`
(o que o router aceita e o que a tela pede pela API) e o SQL de
`add_agendamentos_compromisso.sql` (o seed das tres colunas fixas e o DEFAULT da
cor). Divergindo, o sintoma nao e erro: e um compromisso salvo numa cor que os
swatches nao marcam, ou uma coluna de entrada que o router procura pela chave e
nao acha — 500 no primeiro compromisso criado.

⚠️ O `_SELECT` E LIDO POR INDICE. `_row_to_dict` acessa `row[0]..row[20]`; uma
coluna acrescentada no MEIO da consulta faz todo campo depois dela passar a ler
o vizinho — sem erro nenhum, so com os valores trocados de lugar na tela. Aqui o
numero de colunas do SELECT e cruzado com os indices que o dicionario le.

⚠️ O `dados_b64` NAO PODE SAIR NA LISTAGEM NEM NO DETALHE. E a diferenca entre
ter e nao ter a permissao `agendamentos.anexo_baixar`: se o GET devolver o
base64 embutido, quem so tem `ver` ja recebeu o arquivo e a caixinha vira
promessa vazia. O modulo de Gestao tem esse buraco ABERTO e assumido por escrito
(routers/gestao.py); aqui ele foi fechado, e este teste e o que impede alguem de
reabri-lo copiando o molde.

⚠️ A LISTA E O RELATORIO TEM DE USAR O MESMO FILTRO. O dono pediu "o relatorio
respeita o filtro ativo"; duas montagens de WHERE divergem no primeiro ajuste, e
a divergencia aparece como "o relatorio veio com um compromisso a mais", sem
nada para culpar.

⚠️ ANOTACAO E APPEND-ONLY, e a trava e a AUSENCIA de rota. Nao ha trigger no
banco: se um dia aparecer um PUT ou um DELETE de anotacao neste router, a
garantia acaba em silencio. O teste procura por ele.

Rodar: python -m pytest backend/tests/test_agendamentos.py -q
"""
import io
import re
import tokenize
from datetime import date, time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from routers import agendamentos as R  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent
MIGR = BACKEND / "migrations"
SQL_BASE = (MIGR / "add_agendamentos.sql").read_text(encoding="utf-8")
SQL_NOVO = (MIGR / "add_agendamentos_compromisso.sql").read_text(encoding="utf-8")
FONTE = Path(R.__file__).read_text(encoding="utf-8")


def _so_o_codigo(txt: str) -> str:
    """O arquivo sem comentario e sem docstring — so o que de fato roda.

    ⚠️ ESTE ARQUIVO PRECISA DISSO PORQUE OS COMENTARIOS DO REPO CITAM CODIGO.
    Metade das notas do router escreve o defeito que ela evita — e escreve com o
    nome da funcao ou com o trecho de SQL. Uma varredura no texto cru acha o
    padrao proibido DENTRO da explicacao de por que ele nao pode existir, e o
    teste reprova o CONSERTO em vez do defeito. Aconteceu com `updated_at DESC`
    e com `exigir_dono_da_linha` na primeira versao deste arquivo.

    ⚠️ SO A TRIPLA NO INICIO DE UMA INSTRUCAO E DOCSTRING. O SQL do modulo mora
    em triplas tambem, mas depois de `=` ou de `(` — e continua no resultado,
    porque varios testes daqui conferem justamente esse SQL.

    ⚠️ MASCARA COM ESPACO EM VEZ DE REMOVER: as posicoes e as linhas ficam onde
    estavam, entao um `split("async def x(")` continua recortando o mesmo trecho.
    """
    chars = list(txt)
    inicio_da_linha = [0]
    for linha in txt.splitlines(keepends=True):
        inicio_da_linha.append(inicio_da_linha[-1] + len(linha))

    def apagar(ini, fim):
        for i in range(inicio_da_linha[ini[0] - 1] + ini[1],
                       inicio_da_linha[fim[0] - 1] + fim[1]):
            if chars[i] != "\n":
                chars[i] = " "

    triplas = ('"' * 3, "'" * 3)
    anterior = tokenize.ENCODING
    for tok in tokenize.generate_tokens(io.StringIO(txt).readline):
        if tok.type == tokenize.COMMENT:
            apagar(tok.start, tok.end)
            continue
        if (tok.type == tokenize.STRING and tok.string.startswith(triplas)
                and anterior in (tokenize.ENCODING, tokenize.INDENT,
                                 tokenize.DEDENT, tokenize.NEWLINE)):
            apagar(tok.start, tok.end)
        if tok.type != tokenize.NL:
            anterior = tok.type
    return "".join(chars)


CODIGO = _so_o_codigo(FONTE)


# ------------------------------------------------- a paleta, nos 2 lugares --

def test_a_paleta_nao_tem_cor_repetida_e_e_hex_de_7():
    """Cor repetida na paleta e um swatch que nao distingue nada; hex fora do
    formato `#rrggbb` nao cabe no `VARCHAR(7)` da coluna."""
    assert len(set(R.CORES)) == len(R.CORES)
    assert 8 <= len(R.CORES) <= 10, "o documento pede de 8 a 10 cores"
    for c in R.CORES:
        assert re.fullmatch(r"#[0-9a-f]{6}", c), c


def test_o_default_da_cor_no_banco_e_a_primeira_cor_da_paleta():
    """⚠️ A LINHA CRIADA SEM COR E A LINHA ANTIGA usam o DEFAULT do banco. Se ele
    nao estiver na paleta, a edicao abre com nenhum swatch marcado e salvar
    devolve 422 — num compromisso que a pessoa nem tentou colorir."""
    m = re.search(r"cor\s+VARCHAR\(7\)\s+NOT NULL\s+DEFAULT\s+'(#[0-9a-f]{6})'",
                  SQL_NOVO, re.I)
    assert m, "o DEFAULT de `cor` sumiu da migration"
    assert m.group(1).lower() == R.COR_PADRAO
    assert R.COR_PADRAO in R.CORES


@pytest.mark.parametrize("ruim", ["", "#fff", "vermelho", "#123456", "#12B886x"])
def test_cor_fora_da_paleta_e_422_com_a_lista(ruim):
    with pytest.raises(Exception) as e:
        R._valida_cor(ruim)
    assert getattr(e.value, "status_code", None) == 422


def test_cor_da_paleta_passa_sem_ligar_para_a_caixa():
    assert R._valida_cor("#12B886") == "#12b886"


# ------------------------------------------ as colunas fixas, nos 2 lugares --

def test_as_tres_colunas_fixas_do_python_sao_as_semeadas_pela_migration():
    """⚠️ A INVARIANTE PRINCIPAL DAS COLUNAS.

    O router procura «Solicitada» pela CHAVE (`_coluna_de_entrada`) porque
    SERIAL nao promete o mesmo id nos cinco bancos. Chave que o seed nao cria =
    500 em todo compromisso novo e em toda remocao de coluna customizada.
    """
    semeadas = tuple(re.findall(r"\(\s*'[^']+',\s*\d+,\s*TRUE,\s*'([a-z_]+)'\s*\)",
                                SQL_NOVO))
    assert semeadas == R.COLUNAS_FIXAS, (
        f"a migration semeia {semeadas} e o router conhece {R.COLUNAS_FIXAS}")
    assert R.COLUNA_ENTRADA in R.COLUNAS_FIXAS


def test_os_tetos_do_quadro_sao_os_do_documento():
    """3 fixas + ate 2 proprias = 5. Os dois numeros valem TAMBEM na API: duas
    abas abertas contam separado e o quadro acabaria com seis colunas."""
    assert R.MAX_COLUNAS == 5
    assert R.MAX_COLUNAS_CUSTOMIZADAS == 2
    assert len(R.COLUNAS_FIXAS) + R.MAX_COLUNAS_CUSTOMIZADAS == R.MAX_COLUNAS
    # E os dois tetos sao conferidos no corpo da rota, nao so no botao da tela.
    assert "len(colunas) >= MAX_COLUNAS" in CODIGO
    assert "MAX_COLUNAS_CUSTOMIZADAS" in CODIGO


def test_coluna_fixa_nao_se_renomeia_nem_se_apaga():
    """As duas rotas tem de recusar `fixa`. Sem isso, «Concluída» vira o que
    alguem quiser e `_coluna_de_entrada` continua procurando a chave — o quadro
    passa a ter uma coluna com nome trocado e o codigo nao percebe."""
    for rota in ("atualizar_coluna", "remover_coluna"):
        corpo = CODIGO.split(f"async def {rota}(", 1)[1].split("\n@router", 1)[0]
        assert 'alvo["fixa"]' in corpo, f"{rota} nao confere se a coluna e fixa"


# ------------------------------------------------------------- o horario ----

def test_periodo_sem_termino_e_422():
    with pytest.raises(Exception) as e:
        R._valida_horario(time(9, 0), True, None)
    assert getattr(e.value, "status_code", None) == 422


@pytest.mark.parametrize("fim", [time(9, 0), time(8, 30)])
def test_termino_menor_ou_igual_ao_inicio_e_422(fim):
    """⚠️ IGUAL TAMBEM E RECUSADO. Um bloco de duracao zero nao desenha altura
    nenhuma na semana: o compromisso existe no banco e some da tela."""
    with pytest.raises(Exception) as e:
        R._valida_horario(time(9, 0), True, fim)
    assert getattr(e.value, "status_code", None) == 422


def test_sem_periodo_a_hora_de_termino_e_ignorada_e_nao_recusada():
    """Desmarcar o toggle com uma hora ja digitada e gesto comum — recusar
    obrigaria a pessoa a limpar um campo que a tela nem mostra mais."""
    R._valida_horario(time(9, 0), False, time(8, 0))  # nao levanta


def test_sem_periodo_o_termino_nao_e_gravado():
    """⚠️ A REGRA MORA NO INSERT, e nao so na validacao: com `tem_periodo`
    falso, `hora_fim` vai NULL para o banco. Sem isso, desmarcar o periodo
    deixaria a hora antiga na linha e o bloco voltaria a esticar no dia em que
    alguem lesse `hora_fim` sem olhar a bandeira."""
    assert "body.hora_fim if body.tem_periodo else None" in CODIGO


def test_o_put_move_as_tres_do_horario_juntas():
    """Mexer em `tem_periodo` sem reescrever `hora_fim` e exatamente como o
    bloco esticado sobrevive ao toggle desmarcado."""
    assert 'enviados & {"hora_inicio", "tem_periodo", "hora_fim"}' in CODIGO


def test_o_put_decide_por_campo_ENVIADO_e_nao_por_nao_nulo():
    """⚠️ `is not None` DESCARTARIA EM SILENCIO as duas edicoes que mandam null:
    limpar o contato e tirar o termino. A pessoa apaga, salva, e o valor volta."""
    assert "model_fields_set" in CODIGO


# ----------------------------------------------------------- o contato ------

@pytest.mark.parametrize("entrada,esperado", [
    ("(51) 99999-8888", "51999998888"),
    ("51 3333-4444", "5133334444"),
    ("", None), (None, None), ("   ", None),
])
def test_a_mascara_do_contato_vira_digito_no_banco(entrada, esperado):
    """`(51) 99999-9999` e `51999999999` sao o MESMO numero — guardar a
    pontuacao faria os dois virarem numeros diferentes para qualquer comparacao,
    e os dois saem do mesmo formulario (colar de outro lugar nao passa pela
    mascara)."""
    assert R._so_digitos(entrada) == esperado


@pytest.mark.parametrize("ruim", ["123", "999998888", "519999988887777"])
def test_contato_com_quantidade_impossivel_de_digitos_e_422(ruim):
    with pytest.raises(Exception) as e:
        R._so_digitos(ruim)
    assert getattr(e.value, "status_code", None) == 422


# ------------------------------------------------------------ o anexo -------

def test_a_listagem_e_o_detalhe_NAO_devolvem_o_base64():
    """⚠️ O BURACO QUE O MOLDE TEM E ESTE MODULO NAO PODE TER.

    Com `dados_b64` na resposta do GET, quem tem apenas `agendamentos.ver` ja
    recebeu o arquivo — e a caixinha `anexo_baixar`, que existe justamente para
    separar "ver que ha um anexo" de "receber o documento", nao separa nada.

    O formulario novo nao anexa (o redesenho trocou anexo+relato por historico
    de anotacoes), mas o que ja foi anexado continua sendo servido — entao a
    regra continua valendo linha a linha.
    """
    linha = (1, 7, "Nova Palma", "RS", "Visita à obra", date(2026, 9, 15),
             time(9, 0), True, time(11, 30), date(2026, 9, 1), "Maria",
             "51999998888", "#12b886", 3, "Solicitada",
             [{"nome": "of.pdf", "mime": "application/pdf", "tamanho": 100,
               "dados_b64": "SEGREDO"}],
             2, "João", None, None, 4)
    d = R._row_to_dict(linha, with_anexos=False)
    assert d["anexos"] == [{"nome": "of.pdf", "mime": "application/pdf",
                            "tamanho": 100}]
    assert "SEGREDO" not in str(d)

    # ⚠️ E O PADRAO DO PARAMETRO E O LADO SEGURO. A primeira versao deste
    # modulo tinha `with_anexos: bool = True` e obrigava cada chamada a lembrar
    # de desligar — uma chamada nova esquecida vazaria o base64 em silencio.
    # Com `False` por padrao, o descuido omite em vez de vazar.
    assert "with_anexos: bool = False" in CODIGO, (
        "o padrao de `_row_to_dict` voltou a ser True — quem esquecer o "
        "argumento passa a vazar o conteudo do anexo")
    # E nenhuma chamada pode pedir o base64 sem que isso esteja escrito.
    for trecho in re.findall(r"_row_to_dict\(([^)]*)\)", CODIGO):
        assert "with_anexos=True" not in trecho, (
            f"chamada pedindo o base64: {trecho!r} — se for de proposito, "
            f"escreva o porque e ajuste este teste")


def test_o_dicionario_traduz_a_linha_inteira():
    """Os campos que a tela usa para desenhar chip, bloco e cartao."""
    linha = (1, 7, "Nova Palma", "RS", "Visita", date(2026, 9, 15),
             time(9, 0), True, time(11, 30), date(2026, 9, 1), "Maria",
             "51999998888", "#12b886", 3, "Solicitada", [], 2, "João",
             None, None, 4)
    d = R._row_to_dict(linha)
    assert d["demanda"] == "Visita"
    assert d["data"] == "2026-09-15"
    # ⚠️ SEM SEGUNDOS. `14:30:00` na tela e ruido que ninguem digitou, e o
    # `<input type="time">` do formulario nem aceita de volta.
    assert d["hora_inicio"] == "09:00" and d["hora_fim"] == "11:30"
    assert d["tem_periodo"] is True
    assert d["coluna"] == "Solicitada" and d["coluna_id"] == 3
    assert d["anotacoes_qtd"] == 4


def test_a_linha_sem_cor_nao_desenha_chip_transparente():
    """Linha anterior a coluna `cor` (ou com NULL por qualquer motivo) cai no
    padrao. Sem isso o chip sai sem cor nenhuma e o compromisso some do fundo."""
    linha = (1, 7, "X", "RS", "d", date(2026, 9, 1), time(8, 0), False, None,
             None, "", None, None, 1, "Solicitada", None, None, None, None,
             None, 0)
    assert R._row_to_dict(linha)["cor"] == R.COR_PADRAO


def test_o_SELECT_tem_exatamente_as_colunas_que_o_dicionario_le():
    """⚠️ O DEFEITO QUE ESTE TESTE PEGA NAO LEVANTA ERRO.

    `_row_to_dict` le `row[0]..row[N]` por POSICAO. Uma coluna acrescentada no
    meio do `_SELECT` empurra todas as seguintes: a demanda passa a mostrar a
    data, a data mostra a hora, e nada falha — so sai trocado na tela.
    """
    pglast = pytest.importorskip("pglast")
    arvore = pglast.parse_sql(R._SELECT + " WHERE a.id = 1")
    alvos = arvore[0].stmt.targetList
    indices = {int(i) for i in re.findall(r"row\[(\d+)\]", CODIGO)}
    assert indices == set(range(len(alvos))), (
        f"o SELECT tem {len(alvos)} colunas e `_row_to_dict` le os indices "
        f"{sorted(indices)}")


# ------------------------------------------------------------ o filtro ------

def test_filtro_vazio_nao_inventa_WHERE():
    onde, params = R._filtros(None, None, None, None, None)
    assert onde == "" and params == {}


def test_cada_filtro_vira_uma_condicao_com_bind():
    onde, params = R._filtros(7, date(2026, 9, 1), date(2026, 9, 30), 3, None)
    for pedaco in ("a.municipio_id = :m", "a.data >= :de", "a.data <= :ate",
                   "a.coluna_id = :k"):
        assert pedaco in onde
    assert params == {"m": 7, "de": date(2026, 9, 1), "ate": date(2026, 9, 30),
                      "k": 3}
    # Tudo por BIND: valor de usuario nunca entra concatenado no SQL.
    assert "'" not in onde


def test_a_busca_so_olha_municipio_demanda_e_solicitante():
    """⚠️ TRES CAMPOS, E SO ELES (decisao do dono). Varrer o contato faria uma
    busca por "99" devolver metade da agenda; varrer as anotacoes faria a linha
    aparecer por um texto que a lista nem mostra."""
    onde, params = R._filtros(None, None, None, None, "obra")
    assert onde.count("LIKE :q") == 3
    for coluna in ("m.nome", "a.demanda", "a.solicitante"):
        assert coluna in onde
    for fora in ("a.contato_whatsapp", "a.cor", "n.texto", "uc.name"):
        assert fora not in onde
    # O termo digitado vai por BIND, sempre.
    assert params["q"] == "%obra%"


def test_a_busca_ignora_acento_e_caixa_dos_DOIS_lados():
    """⚠️ O MESMO MAPA NO SQL E NO PYTHON. A extensao `unaccent` nao esta
    instalada em nenhum dos cinco bancos; normalizar so um dos lados faria
    "sao joao" nao achar "São João" — ou pior, achar so as vezes."""
    onde, params = R._filtros(None, None, None, None, "SÃO JOÃO")
    assert params["q"] == "%sao joao%"
    assert onde.count("translate(lower(") == 3
    for letra in ("á", "ç", "õ"):
        assert letra in onde, "o mapa de acentos sumiu do SQL"


def test_o_filtro_da_toolbar_se_SOMA_a_carteira_e_nao_a_substitui():
    """⚠️ Marcar cidades no filtro e escolha do usuario sobre o que ele JA pode
    ver. Se o `municipio_ids` substituisse o recorte da carteira, bastaria
    mandar um id qualquer na URL para ler a agenda de um cliente alheio."""
    onde, params = R._filtros(None, None, None, None, None, [1, 2, 3], [9])
    assert "a.municipio_id = ANY(:mids)" in onde
    assert "a.municipio_id = ANY(:mfiltro)" in onde
    assert params["mids"] == [1, 2, 3] and params["mfiltro"] == [9]


def test_a_lista_e_o_relatorio_usam_A_MESMA_funcao_de_filtro():
    """⚠️ O dono pediu "o relatorio respeita o filtro ativo". Duas montagens de
    WHERE divergem no primeiro ajuste, e a divergencia aparece como "o relatorio
    veio com um compromisso a mais" — sem nada para culpar."""
    chamadas = re.findall(r"_filtros\(", CODIGO)
    # 1 definicao + 2 usos (a lista e o relatorio)
    assert len(chamadas) == 3, (
        f"{len(chamadas)} referencias a _filtros; esperava 3 (a definicao, a "
        f"lista e o relatorio). Alguem montou um filtro proprio?")
    assert "onde, params = _filtros(" in CODIGO


def test_o_relatorio_tem_teto_de_linhas():
    """Sem teto, um filtro largo monta um PDF de milhares de paginas na memoria
    de um container que divide 2 vCPU com outros 42."""
    assert isinstance(R.MAX_EXPORT, int) and R.MAX_EXPORT > 0
    assert "len(rows) > MAX_EXPORT" in CODIGO


# ------------------------------------------------- a janela do relatorio ----

def test_a_semana_do_relatorio_comeca_na_SEGUNDA_como_a_grade():
    """⚠️ `weekday()` do Python ja da 0 na segunda; o `getDay()` do JavaScript
    da 0 no domingo, e e por isso que a tela faz `(d + 6) % 7`. Trocar um pelo
    outro desalinha o arquivo da tela em UM dia — que ninguem confere."""
    de, ate = R._janela("semana", date(2026, 9, 10))   # quinta
    assert (de, ate) == (date(2026, 9, 7), date(2026, 9, 13))
    assert de.weekday() == 0 and ate.weekday() == 6


@pytest.mark.parametrize("ref,esperado", [
    (date(2026, 2, 10), (date(2026, 2, 1), date(2026, 2, 28))),
    (date(2024, 2, 10), (date(2024, 2, 1), date(2024, 2, 29))),   # bissexto
    (date(2026, 12, 31), (date(2026, 12, 1), date(2026, 12, 31))),
])
def test_o_mes_do_relatorio_vai_do_dia_1_ao_ultimo(ref, esperado):
    assert R._janela("mes", ref) == esperado


def test_o_dia_do_relatorio_e_um_dia_so():
    assert R._janela("dia", date(2026, 9, 10)) == (date(2026, 9, 10),) * 2


def test_o_nome_do_arquivo_e_o_que_o_documento_pede():
    """`agendamentos-{dia|semana|mes}-{AAAA-MM-DD}.pdf`."""
    assert 'f"agendamentos-{periodo}-{ref:%Y-%m-%d}.pdf"' in CODIGO


# ------------------------------------------- o pedido "todos os MEUS" -------

def test_sem_municipio_o_recorte_e_a_carteira_da_pessoa():
    """⚠️ O DEFEITO QUE ESTE TESTE FECHA JA FOI PARA PRODUCAO.

    A opcao «todos os municipios» mandava a consulta sem `municipio_id`.
    O router chamava `ensure_municipio_access(current, None)`, que levanta 403
    ("Selecione um municipio permitido") para toda carteira restrita — e
    carteira so e `None` no super-admin da Alavank. Resultado: a opcao respondia
    403 para 100% dos usuarios reais do tenant, e o comentario da tela afirmava
    que o backend fazia um recorte que NAO EXISTIA no router.
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
    de AUTHZ_MODO. Trocar o valor do filtro no navegador da 403."""
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
        f"(a lista e o relatorio)")
    for m in chamadas:
        anterior = FONTE[:m.start()].rstrip().splitlines()[-1].strip()
        assert anterior.startswith("if municipio_id"), (
            f"chamada INCONDICIONAL de ensure_municipio_access, precedida por "
            f"{anterior!r}. Com `municipio_id=None` ela levanta 403 para toda "
            f"carteira restrita — e era esse o defeito que matava a opcao "
            f"«todos os municipios»")


def test_a_lista_e_o_relatorio_aplicam_O_MESMO_recorte():
    """O arquivo tem de trazer as linhas da tela, e isso inclui a carteira."""
    assert CODIGO.count("permitidos, vazia = _carteira(") == 2


# ------------------------------------------- o municipio implicito ----------

def test_a_criacao_nao_exige_municipio_no_corpo():
    """⭐ NUMA PREFEITURA NAO HA CAMPO DE MUNICIPIO EM LUGAR NENHUM DA TELA.

    O corpo chega sem `municipio_id` e quem responde e `_resolver_municipio`,
    que preenche com o unico municipio ativo do tenant. Exigir o campo no
    pydantic devolveria 422 num formulario que nao tem o campo para preencher.
    """
    corpo = R.CompromissoCreate(demanda="Visita", data=date(2026, 9, 1),
                                hora_inicio=time(9, 0), solicitante="Maria")
    assert corpo.municipio_id is None
    assert R.CompromissoCreate.model_fields["municipio_id"].is_required() is False


def test_o_municipio_implicito_so_vale_com_UM_municipio_ativo():
    """⚠️ E A CONTAGEM E DO TENANT, NAO DA CARTEIRA DA PESSOA. Numa assessoria
    de 42 cidades, um usuario com uma cidade so nao pode cair no modo prefeitura
    — ele criaria compromisso sem escolher e a proxima cidade herdaria o
    silencio. Por isso a consulta le `municipios` e nao `allowed_municipio_ids`."""
    corpo = CODIGO.split("async def _municipio_implicito(", 1)[1].split(
        "async def _resolver_municipio", 1)[0]
    assert "FROM municipios WHERE active = TRUE LIMIT 2" in corpo
    assert "allowed_municipio_ids" not in corpo
    assert "len(rows) == 1" in corpo


def test_a_coluna_municipio_continua_NOT_NULL():
    """⚠️ A DIVERGENCIA CONSCIENTE EM RELACAO AO DOCUMENTO, e ela e o motivo de
    `_municipio_implicito` existir. `municipio_id` nulo quebraria o JOIN de
    `municipios` (INNER: a linha sumiria), o recorte de carteira
    (`= ANY(:mids)` nunca casa com NULL — invisivel para toda carteira
    restrita) e o carimbo da trilha."""
    assert "municipio_id    INTEGER NOT NULL" in SQL_BASE
    assert "DROP NOT NULL" not in SQL_NOVO


# ------------------------------------ a anotacao e append-only --------------

def test_nao_existe_rota_de_editar_nem_de_apagar_anotacao():
    """⚠️ A TRAVA E A AUSENCIA DE ROTA — nao ha trigger no banco (diferente do
    `audit_log`). Um PUT ou DELETE de anotacao acrescentado aqui acabaria com a
    garantia em silencio, e o historico deixaria de ser historico."""
    rotas = re.findall(r'@router\.(get|post|put|patch|delete)\("([^"]*)"', CODIGO)
    for verbo, caminho in rotas:
        if "anotacoes" in caminho:
            assert verbo == "post", f"{verbo.upper()} {caminho} nao pode existir"


def test_anotar_nao_passa_pelo_alcance_por_linha():
    """«Qualquer usuario adiciona» (documento de redesenho). O alcance por linha
    restringe quem ALTERA o registro de outra pessoa; anotar cria linha NOVA,
    assinada por quem escreveu. Com o alcance aqui, o tecnico restrito aos
    proprios registros nao poderia responder no compromisso que a secretaria
    abriu — que e justamente a conversa que o historico existe para guardar."""
    corpo = CODIGO.split("async def anotar(", 1)[1].split("\n@router", 1)[0]
    assert "exigir_dono_da_linha" not in corpo


def test_o_texto_da_anotacao_nao_vai_para_a_trilha():
    """O `audit_log` nao se apaga, por decisao do dono, e a anotacao e campo
    livre: pode ter nome, telefone e o teor de uma conversa."""
    corpo = CODIGO.split("async def anotar(", 1)[1].split("\n@router", 1)[0]
    assert '"tamanho": len(texto)' in corpo
    assert '"texto": texto' not in corpo


def test_o_historico_sai_do_mais_antigo_para_o_mais_recente():
    """O campo de escrever fica embaixo: a anotacao nova aparece logo acima
    dele, que e onde o olho ja esta."""
    corpo = CODIGO.split("async def _anotacoes(", 1)[1].split(
        "async def _colunas(", 1)[0]
    assert "ORDER BY n.created_at ASC" in corpo


# ------------------------------------------------- a ordem da agenda --------

def test_a_lista_e_ordenada_por_dia_E_por_hora():
    """As outras telas do repo ordenam por `updated_at DESC` porque mostram
    historico. Aqui e uma AGENDA: `DESC` poria o mes que vem no topo. A hora
    entra porque o kanban e o card lateral empilham o MESMO dia."""
    assert CODIGO.count("ORDER BY a.data ASC, a.hora_inicio ASC, a.id ASC") == 2
    assert "updated_at DESC" not in CODIGO


# ------------------------------------ o SQL bate com o ESQUEMA de verdade ---

def _colunas_de_agendamentos() -> set:
    """As colunas da tabela, lidas das DUAS migrations que a montam."""
    corpo = SQL_BASE.split("CREATE TABLE IF NOT EXISTS agendamentos (", 1)[1]
    corpo = corpo.split(");", 1)[0]
    colunas = set(re.findall(r"^\s{4}([a-z_]+)\s", corpo, re.M))
    # O rename de `titulo` para `demanda`.
    renomes = re.findall(r"RENAME COLUMN\s+(\w+)\s+TO\s+(\w+)", SQL_NOVO, re.I)
    for de, para in renomes:
        colunas.discard(de)
        colunas.add(para)
    colunas |= set(re.findall(r"ADD COLUMN IF NOT EXISTS\s+(\w+)", SQL_NOVO, re.I))
    return colunas


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
        "a": _colunas_de_agendamentos(),
        "m": {c.name for c in Municipio.__table__.columns},
        "uc": {c.name for c in User.__table__.columns},
        "k": {"id", "nome", "ordem", "fixa", "chave", "created_at", "updated_at"},
        "n": {"id", "compromisso_id", "autor_id", "texto", "created_at"},
    }
    # ⚠️ SEM OS COMENTARIOS. O `_SELECT` traz uma nota `--` que CITA `ur.nome`
    # como exemplo do erro que este teste pega; varrer o texto cru fazia o teste
    # falhar por causa da propria explicacao. Comentario nao vai para o banco.
    sql = re.sub(r"--[^\n]*", "", R._SELECT)
    usadas = re.findall(r"\b(a|m|uc|k|n)\.([a-z_]+)", sql)
    assert usadas, "nao achei referencias de coluna no _SELECT"
    for alias, coluna in usadas:
        assert coluna in colunas[alias], (
            f"`{alias}.{coluna}` nao existe. Colunas de {alias}: "
            f"{sorted(colunas[alias])}. ⚠️ `municipios` usa `nome` e `users` usa "
            f"`name` — a troca das duas e o erro que este teste existe para pegar")


def test_toda_consulta_do_router_so_cita_coluna_que_existe():
    """O `_SELECT` nao e o unico SQL do arquivo: ha o UPDATE do PUT, o do
    kanban, a leitura do horario atual e as tres rotas de coluna. Um `a.titulo`
    esquecido em qualquer um deles e o mesmo ProgrammingError, so que noutra
    rota — e sem cobertura, so a tela do cliente descobre."""
    colunas = _colunas_de_agendamentos()
    sem_comentario = CODIGO
    # `SET <coluna> =` e `INSERT INTO agendamentos (...)`
    for m in re.finditer(r"UPDATE agendamentos\s+SET\s+([a-z_]+)\s*=", sem_comentario):
        assert m.group(1) in colunas, f"UPDATE de coluna inexistente: {m.group(1)}"
    ins = re.search(r"INSERT INTO agendamentos\s*\n\s*\(([^)]+)\)", sem_comentario)
    assert ins, "nao achei o INSERT de agendamentos"
    for c in re.findall(r"[a-z_]+", ins.group(1)):
        assert c in colunas, f"INSERT de coluna inexistente: {c}"


def test_a_migration_nova_nao_apaga_coluna_nenhuma():
    """⚠️ ADITIVA E SEM DROP, e por dois motivos: `relato`, `status`,
    `responsavel_id` e `anexos` guardam dado de cliente que o redesenho deixou
    de exibir mas nao autorizou apagar; e DROP em cinco bancos e irreversivel
    num boot que o runner engole em silencio se falhar."""
    assert not re.search(r"DROP\s+COLUMN", SQL_NOVO, re.I)
    assert not re.search(r"DROP\s+TABLE", SQL_NOVO, re.I)


def test_o_relato_antigo_vira_anotacao_sem_duplicar_a_cada_boot():
    """A migration roda a CADA boot dos cinco tenants. Sem o `NOT EXISTS`, cada
    reinicio acrescentaria mais uma copia do relato ao historico."""
    assert "INSERT INTO agendamentos_anotacoes" in SQL_NOVO
    assert "NOT EXISTS (SELECT 1 FROM agendamentos_anotacoes" in SQL_NOVO


def test_a_migration_esta_registrada_DEPOIS_da_que_cria_a_tabela():
    """Em banco novo, ALTER antes do CREATE falha — e o runner engole a falha."""
    from services.startup import MIGRATION_FILES
    assert MIGRATION_FILES.index("add_agendamentos.sql") < \
        MIGRATION_FILES.index("add_agendamentos_compromisso.sql")
