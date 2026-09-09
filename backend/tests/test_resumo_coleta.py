"""
Resumo diario da coleta (`scripts/resumo_coleta.py` + `GET /api/control/resumo-coleta`).

⭐ O QUE ESTE ARQUIVO EXISTE PARA IMPEDIR

O resumo e o unico vigia que roda FORA da VPS — e portanto o unico que percebe
worker morto ou VPS fora do ar, casos em que o watchdog de dentro nao consegue
falar. Um relatorio desses falha de tres jeitos, todos silenciosos:

1. **Ele mente que esta tudo bem.** Zero rodadas na janela nao e dia calmo, e
   worker parado; e API que nao respondeu nao pode virar uma linha discreta.
2. **Ele nao cabe.** O Telegram corta em 4.096 caracteres, e um dia ruim com 44
   municipios gera muito mais que isso. Cortar no meio de um item deixa uma linha
   sem sentido no lugar da informacao.
3. **Ele some.** Se alguem devolver o `parse_mode`, o `_` de
   `transferegov_opendata` abre italico que nunca fecha e a API responde 400 —
   some no dia em que ha o que relatar.

O SQL da rota tambem e travado aqui, contra a arvore (`pglast`), porque nao ha
Postgres de teste: o que se garante e que a comparacao de volume e sempre da
fonte contra ELA MESMA, nunca entre fontes de semantica diferente.

Rodar:
    python -m pytest backend/tests/test_resumo_coleta.py -v
"""
import sys
from pathlib import Path

import pytest

# `scripts/` nao esta no sys.path da suite (o conftest poe `backend/`), e este e
# o unico teste que precisa de la.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import resumo_coleta as rc  # noqa: E402


def _tenant_ok(slug="freitas", rodadas=None, fontes=None, achados=None,
               volume=None, erros=None):
    return {"slug": slug, "ok": True, "dados": {
        "instance_slug": slug,
        "janela_horas": 24,
        "rodadas": rodadas if rodadas is not None else [{"status": "success", "n": 39}],
        "fontes": fontes or [],
        "achados": achados or [],
        "volume": volume or [],
        "erros": erros or [],
    }}


# --------------------------------------------------------------------------
# 1. O relatorio nao pode mentir que esta tudo bem.
# --------------------------------------------------------------------------

def test_zero_rodadas_e_worker_parado_nao_dia_calmo():
    msg = rc.montar_mensagem([_tenant_ok(rodadas=[])])
    assert "NENHUMA rodada" in msg and "worker parado" in msg


def test_api_fora_aparece_como_erro_no_tenant():
    msg = rc.montar_mensagem([{"slug": "trust", "ok": False, "erro": "timeout"}])
    assert "trust" in msg and "API nao respondeu" in msg


def test_todas_as_apis_fora_vira_alarme_de_vps():
    """O alarme mais alto que este relatorio sabe dar — e o que ninguem da hoje."""
    fora = [{"slug": s, "ok": False, "erro": "timeout"}
            for s in ("freitas", "trust", "montesiao-mg", "santamaria-rs", "novapalma-rs")]
    msg = rc.montar_mensagem(fora)
    assert "NENHUMA das 5 APIs respondeu" in msg
    assert "VPS fora do ar" in msg


def test_uma_api_fora_nao_vira_alarme_de_vps():
    """Um tenant fora e problema daquele tenant; cinco e problema do servidor."""
    r = [{"slug": "trust", "ok": False, "erro": "timeout"}, _tenant_ok()]
    assert "VPS fora do ar" not in rc.montar_mensagem(r)


def test_dia_limpo_diz_que_nao_ha_nada_a_olhar():
    msg = rc.montar_mensagem([_tenant_ok()])
    assert "Nada a olhar" in msg
    # ⚠️ Resumo que so chega em dia ruim nao prova que o vigia esta vivo. A
    # mensagem tem de sair TAMBEM quando esta tudo bem.
    assert "resumo da coleta" in msg


# --------------------------------------------------------------------------
# 2. O porque, que era o pedido: erro, municipio e onde olhar.
# --------------------------------------------------------------------------

def test_erro_de_fonte_traz_a_mensagem_gravada():
    """`error_message` existia no banco desde sempre e nao saia por rota nenhuma."""
    msg = rc.montar_mensagem([_tenant_ok(fontes=[{
        "source": "cagec", "status": "erro", "horas_desde": 3.2,
        "error_message": "TimeoutError no PESQUISAR do portal ZK", "registros": 0}])])
    assert "TimeoutError no PESQUISAR" in msg
    assert "cagec.mg.gov.br" in msg     # o "-> onde olhar"


def test_fonte_sem_mapa_de_onde_olhar_nao_inventa():
    msg = rc.montar_mensagem([_tenant_ok(fontes=[{
        "source": "fonte_nova_qualquer", "status": "erro", "horas_desde": 1,
        "error_message": "boom", "registros": 0}])])
    assert "boom" in msg and "->" not in msg


def test_achado_do_watchdog_traz_o_municipio():
    msg = rc.montar_mensagem([_tenant_ok(achados=[{
        "tipo": "credencial_recusada", "chave": "Piracema",
        "mensagem": "SIGCON recusou credencial — USUARIO REVOGADO",
        "criado_em": "2026-09-09T03:10:00"}])])
    assert "Piracema" in msg and "USUARIO REVOGADO" in msg


# A mensagem real, copiada do banco do novapalma em 08/09/2026.
_ALERTA_REAL = ("\U0001F7E0 *PACTHA novapalma-rs* — fonte parada\n"
                "`simec_par`\n"
                "ultimo sucesso ha 18.8h (limite 12h)")


def test_limpa_o_markdown_e_o_que_o_resumo_ja_diz():
    """O slug e a chave ja estao no cabecalho do item; repeti-los gasta os 4.096
    caracteres que o relatorio tem, e os `*` sairiam literais em texto puro."""
    limpo = rc._limpar_mensagem_watchdog(_ALERTA_REAL)
    assert "*" not in limpo and "`" not in limpo
    assert "PACTHA novapalma-rs" not in limpo
    assert limpo == "fonte parada: ultimo sucesso ha 18.8h (limite 12h)"


def test_mensagem_em_formato_inesperado_nao_vira_vazio():
    """Se o formato do watchdog mudar, degrade para a mensagem inteira."""
    assert rc._limpar_mensagem_watchdog("qualquer coisa nova") == "qualquer coisa nova"
    assert rc._limpar_mensagem_watchdog("") == ""


def test_repeticao_aparece_como_contagem():
    """⚠️ Medido no banco: um problema que dura o dia gera ~7 linhas iguais
    (tce_rs_portal 7x, transferegov_lote 7x). 21 linhas para 4 problemas fazem o
    relatorio deixar de ser lido — e 7x em 24h e informacao: e persistente."""
    msg = rc.montar_mensagem([_tenant_ok(achados=[{
        "tipo": "fonte_parada", "chave": "tce_rs_portal", "repeticoes": 7,
        "mensagem": _ALERTA_REAL, "criado_em": "2026-09-09T00:08:03"}])])
    assert "(7x em 24h)" in msg


def test_achado_unico_nao_ganha_contagem():
    msg = rc.montar_mensagem([_tenant_ok(achados=[{
        "tipo": "fonte_parada", "chave": "cauc", "repeticoes": 1,
        "mensagem": _ALERTA_REAL, "criado_em": "2026-09-09T00:08:03"}])])
    assert "1x em 24h" not in msg


def test_queda_de_volume_aparece_mesmo_com_status_verde():
    """A lacuna E da auditoria: `simec_par` gravou success com 0 registros 3x."""
    msg = rc.montar_mensagem([_tenant_ok(volume=[{
        "source": "simec_par", "ultimo": 0, "mediana": 311, "amostras": 30}])])
    assert "simec_par" in msg
    assert "mediana 311" in msg
    assert "quase vazia" in msg


def test_consulta_incompleta_do_tenant_e_reportada():
    """Tabela ausente devolve bloco vazio + nota; a nota nao pode ser engolida."""
    msg = rc.montar_mensagem([_tenant_ok(erros=["achados: relation ... does not exist"])])
    assert "consulta incompleta" in msg


# --------------------------------------------------------------------------
# 3. Cabe, e nao some.
# --------------------------------------------------------------------------

def test_mensagem_longa_cabe_no_limite_do_telegram():
    achados = [{"tipo": "municipio_defasado", "chave": f"Municipio {i}",
                "mensagem": "sem coleta ha mais de 48h " + "x" * 200,
                "criado_em": "2026-09-09T03:00:00"} for i in range(80)]
    msg = rc.montar_mensagem([_tenant_ok(achados=achados)])
    assert len(msg) <= rc.LIMITE_TELEGRAM


def test_corte_avisa_que_cortou():
    achados = [{"tipo": "fonte_parada", "chave": f"f{i}", "mensagem": "y" * 300,
                "criado_em": "2026-09-09T03:00:00"} for i in range(80)]
    msg = rc.montar_mensagem([_tenant_ok(achados=achados)])
    assert "nao couberam" in msg


def test_cabecalho_sobrevive_ao_corte():
    """Cortar ate sumir com o cabecalho deixaria uma mensagem sem contexto."""
    achados = [{"tipo": "fonte_parada", "chave": f"f{i}", "mensagem": "y" * 300,
                "criado_em": "2026-09-09T03:00:00"} for i in range(200)]
    msg = rc.montar_mensagem([_tenant_ok(achados=achados)])
    assert "PACTHA — resumo da coleta" in msg


def test_envio_nao_manda_parse_mode(monkeypatch):
    """Se voltar `parse_mode`, o `_` de transferegov_opendata mata o relatorio."""
    import json as _json
    import urllib.request

    capturado = {}

    class R:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def falso(req, timeout=None):
        capturado.update(_json.loads(req.data.decode("utf-8")))
        return R()

    monkeypatch.setattr(urllib.request, "urlopen", falso)
    monkeypatch.setenv("RESUMO_TELEGRAM_TOKEN", "123:ABC")
    monkeypatch.setenv("RESUMO_TELEGRAM_CHAT_ID", "555")

    assert rc.enviar("transferegov_opendata parado ha 31h") is True
    assert "parse_mode" not in capturado
    assert capturado["chat_id"] == "555"


def test_envio_sem_credencial_nao_explode(monkeypatch):
    monkeypatch.delenv("RESUMO_TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("RESUMO_TELEGRAM_CHAT_ID", raising=False)
    assert rc.enviar("qualquer coisa") is False


def test_falha_no_envio_nao_vaza_o_token(monkeypatch, capsys):
    import urllib.request

    monkeypatch.setenv("RESUMO_TELEGRAM_TOKEN", "123:TOKEN-SECRETO")
    monkeypatch.setenv("RESUMO_TELEGRAM_CHAT_ID", "555")
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: (_ for _ in ()).throw(
                            OSError(f"401 em {req.full_url}")))

    rc.enviar("alerta")

    assert "TOKEN-SECRETO" not in capsys.readouterr().out


# --------------------------------------------------------------------------
# 4. O coletor: erro de rede e conteudo, nao excecao.
# --------------------------------------------------------------------------

def test_coletar_transforma_falha_de_rede_em_dado(monkeypatch):
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: (_ for _ in ()).throw(OSError("recusou")))
    r = rc.coletar({"slug": "trust", "api_url": "https://x", "control_token": "t"}, 24)
    assert r["ok"] is False and "recusou" in r["erro"]


def test_coletar_manda_o_slug_como_anti_misrouting(monkeypatch):
    """Sem isto, trocar duas URLs no secret faz o relatorio atribuir os numeros
    de um cliente a outro por meses, sem sintoma nenhum."""
    import urllib.request

    visto = {}

    class R:
        def read(self): return b'{"rodadas":[]}'
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def falso(req, timeout=None):
        visto.update(req.headers)
        return R()

    monkeypatch.setattr(urllib.request, "urlopen", falso)
    rc.coletar({"slug": "novapalma-rs", "api_url": "https://x", "control_token": "t"}, 24)
    assert visto.get("X-tenant-slug") == "novapalma-rs"


def test_401_explica_o_que_fazer():
    """Erro de credencial tem de dizer QUAL credencial, senao vira adivinhacao."""
    import urllib.error
    import urllib.request

    def falso(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

    original = urllib.request.urlopen
    urllib.request.urlopen = falso
    try:
        r = rc.coletar({"slug": "x", "api_url": "https://x", "control_token": "t"}, 24)
    finally:
        urllib.request.urlopen = original
    assert "control token" in r["erro"]


# --------------------------------------------------------------------------
# 5. O SQL da rota, contra a arvore.
# --------------------------------------------------------------------------

def _sql_do_volume() -> str:
    import inspect

    from routers import control

    fonte = inspect.getsource(control.control_resumo_coleta)
    return fonte[fonte.index("WITH ranked AS"):].split('"""')[0].strip()


def test_volume_compara_a_fonte_com_ela_mesma():
    """⚠️ Mediana ENTRE fontes seria um numero com cara de metrica e sem
    significado: a semantica das contagens e inconsistente de proposito (o sigcon
    grava so `updated`, o cagec conta MUNICIPIOS). O particionamento por `source`
    e o que impede isso."""
    pglast = pytest.importorskip("pglast")

    sql = _sql_do_volume()
    arvore = pglast.parse_sql(sql)          # e Postgres valido, nao so uma string

    assert "PARTITION BY source" in sql, "a janela tem de ser por fonte"
    assert "h.source = u.source" in sql, "o join tem de casar a fonte com ela mesma"
    assert len(arvore) == 1


def test_volume_exige_amostra_minima_e_so_reporta_queda_grande():
    """Sem o piso de amostras, fonte recem-nascida vira alarme no primeiro dia;
    sem o limiar, variacao normal vira ruido diario e o relatorio perde o valor."""
    sql = _sql_do_volume()
    assert "amostras >= 5" in sql
    assert "mediana * 0.5" in sql


def test_rota_do_resumo_exige_escopo_de_leitura():
    """Rota de control sem dependency nenhuma responderia a qualquer um com token."""
    import inspect

    from routers import control

    bloco = inspect.getsource(control).split('@router.get("/resumo-coleta")')[1][:900]
    assert 'require_control_scope("control:data:read")' in bloco


def test_janela_e_limitada_nos_dois_lados():
    """`?horas=100000` faria uma varredura sem teto no ingestion_log de todos."""
    import inspect

    from routers import control

    fonte = inspect.getsource(control.control_resumo_coleta)
    assert "max(1, min(int(horas or 24), 168))" in fonte


# --------------------------------------------------------------------------
# 5. Tenant deployado que o relatorio nao olha.
#
# A lista de tenants mora num SECRET do repo, e secret nao acompanha merge: o
# `bgk` entrou na `main` em 08/09/2026, um dia depois deste script nascer "para
# os cinco". Um tenant fora do secret nao vira erro — ele some do relatorio, que
# continua verde. E exatamente o silencio-que-parece-saude que este vigia existe
# para matar, so que agora dentro do proprio vigia.
# --------------------------------------------------------------------------

def test_tenant_deployado_e_fora_do_secret_vira_linha():
    ausentes = rc.tenants_ausentes(["freitas", "trust"], ["freitas", "trust", "bgk"])
    assert ausentes == ["bgk"]
    msg = rc.montar_mensagem([_tenant_ok()], ausentes=ausentes)
    assert "bgk" in msg
    assert "PACTHA_RESUMO_TENANTS" in msg


def test_nome_curto_do_ci_casa_com_o_instance_slug_por_prefixo():
    """O CI chama `santamaria`; a API se chama `santamaria-rs`. Exigir igualdade
    faria o relatorio acusar ausencia dos tres tenants do RS todo santo dia — e
    alarme que sempre toca vira alarme que ninguem le."""
    assert rc.tenants_ausentes(
        ["freitas", "montesiao-mg", "santamaria-rs", "novapalma-rs"],
        ["freitas", "montesiao", "santamaria", "novapalma"]) == []


def test_conferencia_sem_o_arquivo_do_ci_nao_inventa_alarme():
    """Falha ao ler o workflow nao pode virar 'todos ausentes': a conferencia e
    um extra, e um extra nunca derruba o relatorio principal."""
    assert rc.tenants_do_ci("/caminho/que/nao/existe.yml") == []
    assert rc.tenants_ausentes(["freitas"], []) == []


def test_le_os_tenants_do_build_backend_de_verdade():
    """Se o formato dos trios mudar, a conferencia morre CALADA — devolve lista
    vazia e nunca mais acusa nada. Este teste e o que percebe."""
    nomes = rc.tenants_do_ci()
    assert "freitas" in nomes and "bgk" in nomes, nomes
    assert len(nomes) >= 6, nomes


def test_aviso_de_ausente_sobrevive_ao_corte():
    """Num dia ruim o corte come os detalhes de tras para frente; o ponto cego
    tem que estar acima da linha de corte, junto do cabecalho."""
    achados = [{"tipo": "fonte_parada", "chave": f"f{i}", "mensagem": "y" * 300,
                "criado_em": "2026-09-09T03:00:00"} for i in range(200)]
    msg = rc.montar_mensagem([_tenant_ok(achados=achados)], ausentes=["bgk"])
    assert "bgk" in msg and len(msg) <= rc.LIMITE_TELEGRAM
