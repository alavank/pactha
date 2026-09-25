"""Recursos recebidos por pasta (`ingestion/cgu_transferencias.py` +
`services/transferencias_pasta.py` + `routers/cgu_transferencias.montar`) — as
armadilhas medidas em 24/09/2026, com linhas REAIS dos arquivos da CGU.

Os fixtures em `fixtures/cgu_transferencias/` são recortes byte a byte (latin-1)
dos arquivos 202608 e 202609 e do CSV de municípios do CAUC:
- 202608: as 46 linhas de Monte Sião/MG (SIAFI 4867) e Nova Palma/RS (8765), mais
  3 de Santa Maria/RS (8841), 2 de Santa Maria do Herval/RS (7337, o homônimo), 2
  entidades do RS SEM código de município e 1 linha do Estado do Acre;
- 202609 (parcial, lido em 24/09): as 25 de Monte Sião — com os 12 caixas
  escolares do PDDE (13, não 12) e a Funasa — e 3 de Nova Palma.
"""
import asyncio  # noqa: F401  (padrão da suíte: asyncio.run onde há corrotina)
import io
import zipfile
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from ingestion import cgu_transferencias as c
from routers import cgu_transferencias as rota
from services import transferencias_pasta as tp

FIX = Path(__file__).parent / "fixtures" / "cgu_transferencias"
MS = "22646525000131"        # prefeitura de Monte Sião/MG
NP = "88488358000156"        # prefeitura de Nova Palma/RS
SM = "88488366000100"        # prefeitura de Santa Maria/RS
AGO, SET = date(2026, 8, 1), date(2026, 9, 1)


def _zip(mes: str) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{mes}_Transferencias.csv", (FIX / f"cgu_transferencias_{mes}.csv").read_bytes())
    buf.seek(0)
    return zipfile.ZipFile(buf)


def _alvos() -> list[c.Alvo]:
    return [c.Alvo(1, "Monte Sião", "MG", "3143401", MS, siafi="4867", origem="cauc_situacao"),
            c.Alvo(2, "Nova Palma", "RS", "4313102", NP, siafi="8765", origem="cauc_situacao")]


def _soma(linhas, **filtro) -> Decimal:
    return sum((x["valor"] for x in linhas
                if all(x.get(k) == v for k, v in filtro.items())), Decimal("0"))


# ---------------------------------------------------------------------------
# Leitura e filtro por SIAFI
# ---------------------------------------------------------------------------
def test_cabecalho_real_e_o_esperado():
    """Armadilha 7: o cabeçalho do fixture (bytes reais) tem todas as COLUNAS."""
    r, ix = c.leitor(_zip("202608"))
    assert set(c.COLUNAS) <= set(ix)
    assert sum(1 for _ in r) == 54


def test_coluna_renomeada_e_erro_com_o_nome():
    bruto = (FIX / "cgu_transferencias_202608.csv").read_bytes().replace(
        "CÓDIGO FAVORECIDO".encode("latin-1"), b"CODIGO FAVORECIDO", 1)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("202608_Transferencias.csv", bruto)
    buf.seek(0)
    with pytest.raises(c.CabecalhoMudou, match="CÓDIGO FAVORECIDO"):
        c.leitor(zipfile.ZipFile(buf))
    with pytest.raises(c.CabecalhoMudou):
        c.leitor(zipfile.ZipFile(io.BytesIO(_vazio_zip())))


def _vazio_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("leiame.txt", b"x")
    return buf.getvalue()


def test_filtro_por_codigo_siafi_e_uf():
    """Armadilha 1: casa por (código SIAFI, UF). Santa Maria (8841), o homônimo
    Santa Maria do Herval (7337), as entidades sem código e o Estado do Acre não
    entram em Monte Sião nem em Nova Palma."""
    lido = c.ler_mes(_zip("202608"), AGO, _alvos())
    assert lido.total_arquivo == 54 and lido.fora_do_mes == 0
    assert len(lido.linhas[1]) == 22 and len(lido.linhas[2]) == 24
    assert {x["siafi_municipio"] for x in lido.linhas[1]} == {"4867"}
    assert {x["siafi_municipio"] for x in lido.linhas[2]} == {"8765"}


def test_nome_nunca_casa_santa_maria_nao_leva_o_herval():
    """A lição de 04/09/2026: Santa Maria recebe as 3 linhas do 8841 e NENHUMA das
    2 de Santa Maria do Herval (7337), que o nome casaria."""
    alvos = [c.Alvo(3, "Santa Maria", "RS", "4316907", SM, siafi="8841")]
    lido = c.ler_mes(_zip("202608"), AGO, alvos)
    assert len(lido.linhas[3]) == 3
    assert all(x["siafi_municipio"] == "8841" for x in lido.linhas[3])


def test_mesmo_codigo_em_outra_uf_nao_casa():
    alvos = [c.Alvo(9, "X", "MG", "", "", siafi="8765")]
    assert c.ler_mes(_zip("202608"), AGO, alvos).linhas[9] == []


def test_entidade_sem_codigo_so_entra_pelo_cnpj_cadastrado():
    """Armadilha 2: linha sem código de município entra só pelo CNPJ de
    `municipio_entidades` — nunca pelo nome."""
    r, ix = c.leitor(_zip("202608"))
    sem = [row for row in r if not row[ix["CÓDIGO MUNICÍPIO SIAFI"]]
           and row[ix["UF"]] == "RS"]
    assert len(sem) == 2
    doc = c._doc(sem[0][ix["CÓDIGO FAVORECIDO"]])
    alvo = c.Alvo(2, "Nova Palma", "RS", "4313102", NP, extras={doc}, siafi="8765")
    lido = c.ler_mes(_zip("202608"), AGO, [alvo])
    assert len(lido.linhas[2]) == 25
    assert sum(1 for x in lido.linhas[2] if x["siafi_municipio"] is None) == 1


def test_linha_de_outro_mes_e_descartada():
    lido = c.ler_mes(_zip("202609"), AGO, _alvos())
    assert lido.fora_do_mes == lido.total_arquivo == 28
    assert lido.linhas == {1: [], 2: []}


# ---------------------------------------------------------------------------
# Os números medidos (08/2026) — os mesmos que a VPS conferiu
# ---------------------------------------------------------------------------
def test_numeros_de_monte_siao_em_agosto():
    ls = c.ler_mes(_zip("202608"), AGO, _alvos()).linhas[1]
    assert _soma(ls, acao_codigo="0045") == Decimal("3088067.34")        # FPM
    assert _soma(ls, acao_codigo="0C33") == Decimal("641762.93")         # FUNDEB
    assert _soma(ls, acao_codigo="219A") == Decimal("235640.89")         # PAB (3 linhas)
    assert _soma(ls, acao_codigo="0369") == Decimal("168526.80")         # salário-educação
    assert _soma(ls, acao_codigo="0A53") == Decimal("89121.15")          # petróleo
    assert _soma(ls, acao_codigo="00PI") == Decimal("33765.50")          # PNAE
    assert _soma(ls, acao_codigo="0969") == Decimal("10344.19")          # PNATE
    fnas = sum((x["valor"] for x in ls if x["orgao_codigo"] == "55001"), Decimal("0"))
    assert fnas == Decimal("21872.08")
    # O salário-educação vai à SECRETARIA de educação, não à prefeitura.
    (sal,) = [x for x in ls if x["acao_codigo"] == "0369"]
    assert sal["favorecido_doc"] == "61994863000116"
    assert tp.grupo_favorecido(sal["favorecido_doc"], sal["favorecido_nome"],
                               sal["tipo_favorecido"], sal["orgao_codigo"], MS) == "secretaria"


def test_numeros_de_nova_palma_em_agosto():
    ls = c.ler_mes(_zip("202608"), AGO, _alvos()).linhas[2]
    assert _soma(ls, acao_codigo="0045") == Decimal("1211820.09")
    assert _soma(ls, acao_codigo="20RP") == Decimal("159027.33")         # PAR
    assert _soma(ls, acao_codigo="219A") == Decimal("88317.82")
    assert _soma(ls, acao_codigo="0C33") == Decimal("65301.83")
    assert _soma(ls, acao_codigo="00SB") == Decimal("8756.83")           # complementação
    assert _soma(ls, acao_codigo="0969") == Decimal("28608.87")
    assert _soma(ls, acao_codigo="00PI") == Decimal("4399.75")
    fnas = sum((x["valor"] for x in ls if x["orgao_codigo"] == "55001"), Decimal("0"))
    assert fnas == Decimal("12493.56")


def test_mes_corrente_nao_tem_constitucionais():
    """Armadilha 3: 09/2026, lido em 24/09, só tem 'Legais, Voluntárias e
    Específicas' — o FPM de setembro ainda não existe no arquivo."""
    ls = c.ler_mes(_zip("202609"), SET, _alvos()).linhas[1]
    assert ls and {x["tipo_transferencia"] for x in ls} == {"Legais, Voluntárias e Específicas"}
    assert _soma(ls, acao_codigo="21CI") == Decimal("105000.00")         # Funasa
    assert sum(1 for x in ls if x["acao_codigo"] == "0515") == 13        # PDDE: 13 caixas (o relatório dizia 12)


# ---------------------------------------------------------------------------
# Código SIAFI (armadilha 1)
# ---------------------------------------------------------------------------
def test_tabela_ibge_siafi_do_tesouro():
    t = c.siafi_por_ibge((FIX / "cauc_municipios_recorte.csv").read_bytes().decode("latin-1"))
    assert t["3143401"] == ("4867", "MG")
    assert t["4313102"] == ("8765", "RS")
    assert t["4316907"] == ("8841", "RS")
    assert t["4316956"] == ("7337", "RS")         # Santa Maria do Herval: outro código
    assert t["1200013"] == ("0643", "AC")         # zero à esquerda preservado
    with pytest.raises(c.CabecalhoMudou):
        c.siafi_por_ibge('"Data da Pesquisa"\n"nada";"aqui"\n')


def test_siafi_normaliza_zero_a_esquerda():
    assert c.siafi4("643") == c.siafi4("0643") == "0643"
    assert c.siafi4("") == c.siafi4(None) == ""


def test_codigo_pela_prefeitura_quando_as_tabelas_faltam():
    alvos = [c.Alvo(1, "Monte Sião", "MG", "", MS)]
    cont = c.codigos_pela_prefeitura(_zip("202608"), alvos)
    assert cont[1].most_common(1)[0][0] == ("4867", "MG")


def test_codigo_divergente_nao_grava():
    """O código resolvido não é o das linhas da prefeitura: o município não é gravado."""
    errado = [c.Alvo(1, "Monte Sião", "MG", "3143401", MS, siafi="4868", origem="cauc_situacao")]
    lido = c.ler_mes(_zip("202608"), AGO, errado)
    assert c.divergente(errado[0], lido)
    certo = _alvos()
    assert not c.divergente(certo[0], c.ler_mes(_zip("202608"), AGO, certo))


# ---------------------------------------------------------------------------
# Classificação por PASTA e por FAVORECIDO
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tipo,orgao,funcao,subfuncao,acao,esperada", [
    ("Constitucionais e Royalties", "-1", "28", "845", "0045", "constitucionais"),     # FPM
    ("Constitucionais e Royalties", "-1", "28", "845", "0C33", "constitucionais"),     # FUNDEB
    ("Constitucionais e Royalties", "-1", "12", "847", "00SB", "constitucionais"),     # complementação
    ("Constitucionais e Royalties", "-1", "28", "845", "006M", "constitucionais"),     # ITR
    ("Constitucionais e Royalties", "-1", "28", "845", "0A53", "royalties"),           # petróleo
    ("Constitucionais e Royalties", "-1", "28", "845", "0547", "royalties"),           # CFEM
    ("Constitucionais e Royalties", "-1", "28", "845", "0546", "royalties"),           # recursos hídricos
    ("Legais, Voluntárias e Específicas", "36000", "10", "301", "219A", "saude"),     # PAB
    ("Legais, Voluntárias e Específicas", "36211", "10", "512", "21CI", "saude"),     # Funasa
    ("Legais, Voluntárias e Específicas", "26298", "28", "846", "0369", "educacao"),  # salário-educação
    ("Legais, Voluntárias e Específicas", "26298", "12", "306", "00PI", "educacao"),  # PNAE
    ("Legais, Voluntárias e Específicas", "55001", "08", "244", "219E", "assistencia"),
    ("Legais, Voluntárias e Específicas", "42000", "28", "392", "00UV", "cultura"),   # PNAB
    ("Legais, Voluntárias e Específicas", "42000", "13", "392", "20ZF", "cultura"),
    ("Legais, Voluntárias e Específicas", "53000", "06", "182", "22BO", "defesa_civil"),
    ("Legais, Voluntárias e Específicas", "56000", "15", "182", "8865", "defesa_civil"),
    ("Legais, Voluntárias e Específicas", "56000", "15", "451", "00T1", "outras"),
    ("Legais, Voluntárias e Específicas", "53000", "20", "608", "00SX", "outras"),
])
def test_pasta(tipo, orgao, funcao, subfuncao, acao, esperada):
    assert tp.pasta(tipo, orgao, funcao, subfuncao, acao) == esperada


@pytest.mark.parametrize("doc,nome,tipo,orgao,esperado", [
    (MS, "MUNICIPIO DE MONTE SIAO", "Administração Pública Municipal", "-1", "prefeitura"),
    ("11875540000135", "FUNDO MUNICIPAL DE SAUDE", "Administração Pública", "36000", "fundo"),
    ("1", "1201FUNDO MUNICIPAL DE SAUDE DE ACRELANDIA", "Administração Pública", "36000", "fundo"),
    ("2", "FUNDO MINICIPAL DE SAUDE", "Administração Pública", "36000", "fundo"),
    ("3", "FUNDO MUNICIPAL DE CULTURA", "Sem Informação", "42000", "fundo"),
    ("4", "MUNICIPIO DE PASSO FUNDO", "Administração Pública Municipal", "26298", "orgao_municipal"),
    ("61994863000116", "SECRETARIA MUNICIPAL DE EDUCACAO", "Administração Pública", "26298", "secretaria"),
    ("5", "DEPARTAMENTO DE EDUCACAO", "Administração Pública Municipal", "26298", "secretaria"),
    ("28545919000180", "CAIXA ESCOLAR CANTINHO DA FELICIDADE", "Entidades Sem Fins Lucrativos",
     "26298", "escola"),
    ("6", "CIRCULO DE PAIS E MESTRES DA ESCOLA MUNICIPAL X", "Entidades Sem Fins Lucrativos",
     "26298", "escola"),
    ("74704008000507", "FUNDACAO DE APOIO DA UNIVERSIDADE FEDERAL DO RS", "Entidades Sem Fins Lucrativos",
     "36000", "entidade"),
    ("7", "BANCO DO BRASIL SA", "Entidades Empresariais Privadas", "26298", "entidade"),
    ("8", "FUNDO ESTADUAL DE SAUDE - FES", "Administração Pública", "36000", "outro_ente"),
    ("9", "FUNDO DE SAUDE DO DISTRITO FEDERAL", "Administração Pública", "36000", "outro_ente"),
    ("63606479000124", "ESTADO DO ACRE", "Administração Pública Estadual ou do Distrito Federal",
     "-1", "outro_ente"),
])
def test_grupo_favorecido(doc, nome, tipo, orgao, esperado):
    assert tp.grupo_favorecido(doc, nome, tipo, orgao, MS) == esperado


def test_toda_linha_real_tem_pasta_e_grupo_conhecidos():
    for mes, m in (("202608", AGO), ("202609", SET)):
        for ls in c.ler_mes(_zip(mes), m, _alvos()).linhas.values():
            for x in ls:
                assert tp.pasta(x["tipo_transferencia"], x["orgao_codigo"], x["funcao_codigo"],
                                x["subfuncao_codigo"], x["acao_codigo"]) in tp.ROTULO_PASTA
                assert tp.grupo_favorecido(x["favorecido_doc"], x["favorecido_nome"],
                                           x["tipo_favorecido"], x["orgao_codigo"],
                                           MS) in tp.ROTULO_GRUPO


def test_waf_da_cgu_e_reconhecido():
    """Armadilha 8 (medida em 24/09/2026): depois de uma carga sem pausa, o host
    de download passou a responder 405 com `x-amzn-waf-action: captcha`. Isso
    PARA a rodada; o 403 do mês ainda não publicado, não."""
    import httpx
    assert c.e_waf(httpx.Response(405, headers={"x-amzn-waf-action": "captcha"}))
    assert c.e_waf(httpx.Response(429))
    assert not c.e_waf(httpx.Response(403))
    assert not c.e_waf(httpx.Response(404))


# ---------------------------------------------------------------------------
# Meses da rodada
# ---------------------------------------------------------------------------
def test_meses_da_rodada_corrente_anterior_e_carga_inicial():
    hoje = date(2026, 9, 24)
    fila = c.meses_da_rodada(hoje, {1, 2}, {date(2026, 7, 1): {1: True}}, janela=4)
    assert fila == [(SET, {1, 2}), (AGO, {1, 2}), (date(2026, 7, 1), {2}),
                    (date(2026, 6, 1), {1, 2})]
    # Gravado enquanto o mês ainda corria (mes_fechado = FALSE): volta à fila.
    fila = c.meses_da_rodada(hoje, {1, 2}, {date(2026, 7, 1): {1: False, 2: True}}, janela=3)
    assert fila[2] == (date(2026, 7, 1), {1})
    # Sem carga inicial: só o corrente e o anterior. Virada de ano.
    assert c.meses_da_rodada(date(2027, 1, 3), {1}, {}, janela=2) == [
        (date(2027, 1, 1), {1}), (date(2026, 12, 1), {1})]


# ---------------------------------------------------------------------------
# Idempotência: o (município, mês) é trocado inteiro (armadilhas 5 e 6)
# ---------------------------------------------------------------------------
class _Cur:
    """Banco falso: só as quatro instruções que `grava_mes` emite."""

    def __init__(self):
        self.linhas: dict[tuple, list] = {}
        self.carga: dict[tuple, dict] = {}
        self._um = None

    def execute(self, sql, p=None):
        s = " ".join(sql.split())
        if s.startswith("SELECT count(*) FROM cgu_transferencias WHERE"):
            self._um = (len(self.linhas.get(tuple(p), [])),)
        elif s.startswith("DELETE FROM cgu_transferencias WHERE"):
            self.linhas.pop(tuple(p), None)
        elif s.startswith("INSERT INTO cgu_transferencias_carga"):
            mid, mes, n, total, fechado, siafi, origem = p
            self.carga[(mid, mes)] = {"linhas": n, "total": total, "mes_fechado": fechado,
                                      "siafi": siafi, "origem": origem}
        else:
            raise AssertionError(f"SQL inesperado: {s[:80]}")

    def fetchone(self):
        return self._um


class _Conn:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


@pytest.fixture
def banco(monkeypatch):
    def inserir(cur, linhas):
        for x in linhas:
            cur.linhas.setdefault((x["municipio_id"], x["mes"]), []).append(x)
    monkeypatch.setattr(c, "_inserir_linhas", inserir)
    return _Cur(), _Conn()


def _estado(cur):
    return ({k: sorted((x["acao_codigo"] or "", str(x["valor"])) for x in v)
             for k, v in cur.linhas.items()},
            {k: (v["linhas"], v["total"], v["mes_fechado"]) for k, v in cur.carga.items()})


def test_rodar_duas_vezes_da_o_mesmo_banco(banco):
    cur, conn = banco
    for _ in range(2):
        notas: list[str] = []
        n, parcial = c.processar_mes(cur, conn, _zip("202608"), AGO, _alvos(), {1, 2}, True, notas)
        assert (n, parcial, notas) == (46, False, [])
    linhas, carga = _estado(cur)
    assert len(linhas[(1, AGO)]) == 22 and len(linhas[(2, AGO)]) == 24
    assert carga[(1, AGO)][0] == 22 and carga[(1, AGO)][2] is True
    assert cur.carga[(1, AGO)]["siafi"] == "4867"
    antes = _estado(cur)
    c.processar_mes(cur, conn, _zip("202608"), AGO, _alvos(), {1, 2}, True, [])
    assert _estado(cur) == antes


def test_mes_fechado_sem_linha_nao_apaga_nem_registra(banco):
    cur, conn = banco
    c.processar_mes(cur, conn, _zip("202608"), AGO, _alvos(), {1, 2}, True, [])
    antes = _estado(cur)
    # O arquivo de setembro lido como se fosse agosto: nenhuma linha do mês.
    notas: list[str] = []
    n, parcial = c.processar_mes(cur, conn, _zip("202609"), AGO, _alvos(), {1, 2}, True, notas)
    assert (n, parcial) == (0, True)
    assert any("mês fechado sem nenhuma linha" in x for x in notas)
    assert _estado(cur) == antes


def test_mes_aberto_vazio_so_grava_se_o_banco_tambem_esta_vazio(banco):
    cur, conn = banco
    vazio = [c.Alvo(7, "Sem nada", "MG", "", "", siafi="9999")]
    n, parcial = c.processar_mes(cur, conn, _zip("202609"), SET, vazio, {7}, False, [])
    assert (n, parcial) == (0, False)
    assert cur.carga[(7, SET)]["linhas"] == 0            # "olhamos, e não havia nada"
    cur.linhas[(7, SET)] = [{"acao_codigo": "X", "valor": Decimal("1")}]
    notas: list[str] = []
    n, parcial = c.processar_mes(cur, conn, _zip("202609"), SET, vazio, {7}, False, notas)
    assert parcial and "nada apagado" in notas[0]
    assert cur.linhas[(7, SET)]


def test_so_grava_quem_foi_pedido(banco):
    cur, conn = banco
    c.processar_mes(cur, conn, _zip("202608"), AGO, _alvos(), {2}, True, [])
    assert (1, AGO) not in cur.carga and (2, AGO) in cur.carga


# ---------------------------------------------------------------------------
# A conta da tela (`routers/cgu_transferencias.montar`)
# ---------------------------------------------------------------------------
def _linhas_da_rota(mid: int) -> list[dict]:
    """O que a rota agrupa no SQL, montado das linhas lidas dos fixtures."""
    agg: dict[tuple, Decimal] = {}
    campos = ("tipo_transferencia", "tipo_favorecido", "orgao_codigo", "orgao_nome",
              "funcao_codigo", "subfuncao_codigo", "acao_codigo", "acao_nome",
              "linguagem_cidada", "favorecido_doc", "favorecido_nome")
    for mes, m in (("202608", AGO), ("202609", SET)):
        for x in c.ler_mes(_zip(mes), m, _alvos()).linhas[mid]:
            k = (m,) + tuple(x[f] for f in campos)
            agg[k] = agg.get(k, Decimal("0")) + x["valor"]
    return [dict(zip(("mes",) + campos, k), valor=v) for k, v in agg.items()]


def _cargas():
    return [{"mes": SET, "mes_fechado": False, "carregado_em": datetime(2026, 9, 24)},
            {"mes": AGO, "mes_fechado": True, "carregado_em": datetime(2026, 9, 24)}]


def test_a_conta_da_tela_e_uma_so():
    corpo = rota.montar(rota.classificar(_linhas_da_rota(1), MS), _cargas(), SET, 12,
                        "municipio", None)
    pastas = {p["chave"]: p["total"] for p in corpo["pastas"]}
    # FPM + FUNDEB + ITR de agosto (a complementação é só de Nova Palma).
    assert pastas["constitucionais"] == pytest.approx(3088067.34 + 641762.93 + 2262.82)
    assert pastas["royalties"] == pytest.approx(89121.15 + 138.71)
    # Mesmo número por três caminhos: total, soma das pastas, soma da série.
    assert corpo["total"] == pytest.approx(sum(pastas.values()))
    assert corpo["total"] == pytest.approx(sum(s["total"] for s in corpo["serie"]))
    assert corpo["total"] == pytest.approx(sum(d["total"] for d in corpo["detalhe"]))
    ago = next(s for s in corpo["serie"] if s["mes"] == "2026-08")
    set_ = next(s for s in corpo["serie"] if s["mes"] == "2026-09")
    assert (ago["parcial"], ago["sem_constitucionais"]) == (False, False)
    assert (set_["parcial"], set_["sem_constitucionais"]) == (True, True)
    jul = next(s for s in corpo["serie"] if s["mes"] == "2026-07")
    assert jul["coletado"] is False                    # não carregado ≠ zero
    assert len(corpo["serie"]) == 12


def test_escolas_ficam_fora_da_conta_do_municipio():
    """Os 13 caixas escolares do PDDE de setembro (R$ 50.225): em `por_grupo`,
    sempre; no total, só com `quem=todos`."""
    ls = rota.classificar(_linhas_da_rota(1), MS)
    mun = rota.montar(ls, _cargas(), SET, 12, "municipio", None)
    todos = rota.montar(ls, _cargas(), SET, 12, "todos", None)
    escolas = next(g for g in mun["por_grupo"] if g["grupo"] == "escola")
    assert escolas["favorecidos"] == 13 and escolas["na_conta"] is False
    assert escolas["total"] == pytest.approx(50225.00)
    assert todos["total"] == pytest.approx(mun["total"] + escolas["total"])
    assert not any(d["grupo"] == "escola" for d in mun["detalhe"])


def test_detalhe_de_um_mes_so():
    ls = rota.classificar(_linhas_da_rota(1), MS)
    corpo = rota.montar(ls, _cargas(), SET, 12, "municipio", AGO)
    assert corpo["mes_detalhe"] == "2026-08"
    pab = [d for d in corpo["detalhe"] if d["acao_codigo"] == "219A"]
    assert len(pab) == 1 and pab[0]["total"] == pytest.approx(235640.89)
    assert Counter(d["pasta"] for d in corpo["detalhe"])["saude"] >= 1
