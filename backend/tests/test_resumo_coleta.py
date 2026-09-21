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


def test_recusa_VELHA_de_candidata_nao_vira_item_fixo__a_de_hoje_aparece():
    """`govbr_candidata` e evento, nao coleta periodica: a recusa fica como "ultimo
    estado" ate a proxima promocao, que pode levar semanas."""
    def _f(horas):
        return [{"source": "govbr_candidata", "status": "partial", "horas_desde": horas,
                 "error_message": "captura candidata RECUSADA: jar SEM login gov.br"}]
    assert "govbr_candidata" not in rc.montar_mensagem([_tenant_ok(fontes=_f(192.0))])
    assert "govbr_candidata" in rc.montar_mensagem([_tenant_ok(fontes=_f(0.3))])
    # so ESTA fonte: parcial velho de coleta periodica continua sendo noticia
    lote = [{"source": "transferegov_lote", "status": "partial", "horas_desde": 192.0,
             "error_message": "sessao gov.br fria"}]
    assert "transferegov_lote" in rc.montar_mensagem([_tenant_ok(fontes=lote)])


def test_dry_run_imprime_no_log_os_itens_que_o_telegram_cortou(monkeypatch, capsys):
    """Quem roda o dry run esta CONFERINDO producao. Em 21/09/2026 a pergunta era
    "a recaptura pegou nos seis?" e o item decisivo estava entre os cortados."""
    achados = [{"tipo": "fonte_parada", "chave": f"fonte{i}", "mensagem": "y" * 300,
                "criado_em": "2026-09-09T03:00:00"} for i in range(80)]
    monkeypatch.setenv("RESUMO_DRY_RUN", "1")
    monkeypatch.setattr(rc, "_tenants", lambda: [{"slug": "freitas"}])
    monkeypatch.setattr(rc, "coletar", lambda t, j: _tenant_ok(achados=achados))
    monkeypatch.setattr(rc, "tenants_ausentes", lambda a, b: [])
    monkeypatch.setattr(rc, "enviar", lambda t: pytest.fail("dry run enviou"))
    assert rc.main() == 0
    saida = capsys.readouterr().out
    assert "nao couberam" in saida and "lista COMPLETA" in saida
    completa = saida[saida.index("lista COMPLETA"):]
    assert all(f"fonte{i}" in completa for i in range(80)), "o log do dry run tambem cortou"


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

# --------------------------------------------------------------------------
# 8. O relatório de 09/09/2026 — os três defeitos do PRIMEIRO envio real.
#
# Ele chegou, e chegou dizendo três coisas erradas de um jeito convincente:
# acusou coletor APOSENTADO (última rodada em maio) de vir vazio; escondeu o
# MOTIVO das rodadas parciais, que estava gravado no banco; e cortou os últimos
# tenants inteiros para caber. O dono leu o conjunto como catástrofe.
# --------------------------------------------------------------------------

def test_o_aviso_de_volume_ignora_coletor_aposentado():
    """`sigcon_full` "trouxe 0, mediana 518" e `editais_pncp` "43, mediana 342":
    as duas últimas rodadas eram de MAIO, 116 dias antes. Fonte que parou de
    rodar é problema de FRESCOR — e disso o watchdog já cuida."""
    sql = _sql_do_volume()
    assert "INTERVAL '72 hours'" in sql
    assert "finished_at >" in sql


def test_rodada_parcial_diz_por_que_e_parcial():
    """O motivo já vinha na rota e o resumo não imprimia: 'fonte parada' sem
    causa mandou o dono procurar no lugar errado por uma manhã."""
    msg = rc.montar_mensagem([_tenant_ok(fontes=[{
        "source": "transferegov_lote", "status": "parcial", "horas_desde": 9.4,
        "error_message": "sessao gov.br fria: 153/153 leituras atras do login sem retorno",
        "registros": 230}])])
    assert "PARCIAL" in msg
    assert "153/153" in msg


def test_parcial_nao_usa_o_icone_de_erro():
    """Parcial trouxe dado; pintá-lo de vermelho infla o tamanho do problema —
    e foi assim que quatro avisos de ruído viraram 'catástrofe' na leitura."""
    msg = rc.montar_mensagem([_tenant_ok(fontes=[{
        "source": "transferegov_lote", "status": "parcial", "horas_desde": 9.4,
        "error_message": "x", "registros": 1}])])
    linha = [ln for ln in msg.splitlines() if "transferegov_lote" in ln][0]
    assert linha.startswith(rc.ICONE["atencao"])


def test_o_corte_nao_come_sempre_os_ultimos_tenants():
    """⚠️ MEDIDO NO PRIMEIRO ENVIO: 14 itens não couberam, e o corte cego (do fim
    para o começo) comeu novapalma e bgk INTEIROS enquanto o freitas ficava com
    doze linhas. Quem tem mais problema calava quem tem menos, todo dia."""
    muitos = [{"tipo": "fonte_parada", "chave": f"f{i}", "mensagem": "y" * 300,
               "criado_em": "2026-09-09T03:00:00"} for i in range(60)]
    msg = rc.montar_mensagem([
        _tenant_ok(slug="freitas", achados=muitos),
        _tenant_ok(slug="bgk-rs", achados=[{
            "tipo": "fonte_parada", "chave": "unico-do-bgk",
            "mensagem": "z" * 100, "criado_em": "2026-09-09T03:00:00"}]),
    ])
    assert len(msg) <= rc.LIMITE_TELEGRAM
    assert "unico-do-bgk" in msg, "o tenant com UM item foi cortado antes do que tinha 60"


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


# --------------------------------------------------------------------------
# 7. O workflow precisa CONSEGUIR RODAR.
#
# Medido em 09/09/2026: com `permissions: {}` o run 34352914795 morreu no passo 2
# — «repository 'https://github.com/alavank/pactha/' not found» — porque zerar o
# escopo tira do GITHUB_TOKEN o `contents: read` de que o actions/checkout
# precisa num repo PRIVADO. Num repo publico o mesmo arquivo funciona, e foi por
# isso que passou batido. O script inteiro estava certo e nunca era alcancado.
#
# Sem `yaml` de proposito: PyYAML nao esta em requirements-dev, e este vigia nao
# ganha dependencia nova para se testar.
# --------------------------------------------------------------------------

def _workflow_do_resumo() -> str:
    caminho = (Path(__file__).resolve().parents[2] / ".github" / "workflows"
               / "resumo-coleta.yml")
    return caminho.read_text(encoding="utf-8")


def test_workflow_consegue_clonar_o_repo_privado():
    # Só as linhas de verdade: o comentário que explica o defeito cita o
    # `permissions: {}` que ele proíbe, e casar com o texto inteiro acusaria a
    # própria explicação.
    linhas = [ln.strip() for ln in _workflow_do_resumo().splitlines()
              if not ln.strip().startswith("#")]
    assert "permissions: {}" not in linhas, (
        "repo e privado: sem contents:read o checkout falha antes do script")
    assert "contents: read" in linhas


def test_workflow_avisa_quando_ele_mesmo_falha():
    """Job que morre antes do script nao manda mensagem nenhuma — e ausencia de
    mensagem e o defeito que este vigia existe para matar. Vermelho na aba
    Actions so avisa quem for olhar a aba Actions."""
    texto = _workflow_do_resumo()
    assert "if: failure()" in texto
    assert "api.telegram.org" in texto.split("python scripts/resumo_coleta.py")[1]


def _tenant_fora(slug="freitas", erro="HTTP 401", recusa=False):
    return {"slug": slug, "ok": False, "erro": erro, "recusa": recusa}


# --------------------------------------------------------------------------
# 6. O alarme mais alto tem de acertar o ENDERECO.
#
# Medido em 09/09/2026, ensaiando o script com o secret ainda vazio: as seis
# APIs responderam 401 e o relatorio anunciou "suspeita de VPS fora do ar".
# Estava tudo no ar; o errado era a credencial. Alarme que aponta o lugar errado
# gasta a manha de quem tem pressa e, na terceira vez, deixa de ser lido.
# --------------------------------------------------------------------------

def test_todas_recusando_o_token_nao_vira_acusacao_de_vps():
    msg = rc.montar_mensagem([_tenant_fora(s, "HTTP 401", recusa=True)
                              for s in ("freitas", "trust", "bgk-rs")])
    assert "credencial" in msg and "PACTHA_RESUMO_TENANTS" in msg
    assert "VPS fora do ar" not in msg


def test_silencio_de_todas_continua_acusando_a_vps():
    """O alarme original e o motivo de este vigia existir; nao pode se perder no
    caminho de ensinar o outro caso."""
    msg = rc.montar_mensagem([_tenant_fora(s, "timeout") for s in ("freitas", "trust")])
    assert "VPS fora do ar" in msg


def test_recusa_misturada_com_silencio_diz_as_duas_coisas():
    """Metade recusando e metade muda sao duas causas; escolher uma esconde a outra."""
    msg = rc.montar_mensagem([_tenant_fora("freitas", "HTTP 401", recusa=True),
                              _tenant_fora("trust", "timeout")])
    assert "1 recusaram o token" in msg and "1 nao responderam" in msg


def test_quem_respondeu_401_nao_e_descrito_como_mudo():
    linha = rc._linha_tenant(_tenant_fora("bgk-rs", "HTTP 401", recusa=True))
    assert "recusou o token" in linha and "nao respondeu" not in linha


def test_coletar_marca_recusa_so_no_que_e_credencial(monkeypatch):
    """503 e a VPS engasgando; 401/403/409 e a API viva dizendo nao. Confundir os
    dois e o que fez o alarme apontar para o servidor errado."""
    import urllib.error
    import urllib.request

    def responder(codigo):
        def falso(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, codigo, "x", {}, None)
        monkeypatch.setattr(urllib.request, "urlopen", falso)
        return rc.coletar({"slug": "x", "api_url": "https://x", "control_token": "t"}, 24)

    assert responder(401)["recusa"] is True
    assert responder(409)["recusa"] is True
    assert responder(503)["recusa"] is False
    assert "slug do secret" in responder(409)["erro"]


def test_aviso_de_ausente_sobrevive_ao_corte():
    """Num dia ruim o corte come os detalhes de tras para frente; o ponto cego
    tem que estar acima da linha de corte, junto do cabecalho."""
    achados = [{"tipo": "fonte_parada", "chave": f"f{i}", "mensagem": "y" * 300,
                "criado_em": "2026-09-09T03:00:00"} for i in range(200)]
    msg = rc.montar_mensagem([_tenant_ok(achados=achados)], ausentes=["bgk"])
    assert "bgk" in msg and len(msg) <= rc.LIMITE_TELEGRAM
