"""A extensao de captura tem de conhecer TODOS os tenants que o deploy conhece.

A lista de tenants vive em dois arquivos que nunca se falaram:

  - `.github/workflows/build-backend.yml`, no env `TENANTS` — quem RECEBE deploy;
  - `extension/ambientes.js`, em `AMBIENTES_CONHECIDOS` — quem RECEBE a sessao
    gov.br capturada pela extensao do Chrome.

Cliente novo entra no primeiro (senao nao sobe) e e facil esquecer do segundo,
porque esquecer nao quebra nada VISIVEL: a captura simplesmente nunca chega
naquele tenant, o POST responde 200 para os outros, e o coletor gated registra
`parcial` em vez de erro.

⚠️ ACONTECEU EM 08-09/09/2026, e o comentario de `ambientes.js` ja tinha
PREVISTO em prosa: "o sexto cliente nasceria fora da captura exatamente como
santamaria e novapalma nasceram". O bgk-rs entrou no `TENANTS` em 08/09, ficou
fora de `AMBIENTES_CONHECIDOS`, e em 09/09 a medicao mostrou `extensao-captura`
com token nos outros cinco e NENHUM token emitido no bgk — com o
`transferegov_lote` dele acusando 216 leituras atras do login sem retorno desde
que o tenant nasceu. Cliente pagante sem a fonte federal mais rica.

Prosa nao segura porta. Este teste segura: acrescentar tenant no deploy sem
acrescentar na extensao reprova o PR.
"""
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOW = os.path.join(RAIZ, ".github", "workflows", "build-backend.yml")
AMBIENTES = os.path.join(RAIZ, "extension", "ambientes.js")

# ⚠️ EXCECAO HISTORICA, e a unica. O freitas foi o primeiro tenant e ficou com o
# host sem slug (`pactha-api-...`, e nao `pactha-freitas-api-...`). Renomear o
# host de um cliente em producao para arrumar a simetria custaria mais do que
# esta linha vale. Tenant novo NAO entra aqui: ele nasce com slug no host.
SEM_SLUG_NO_HOST = {"freitas": "pactha-api-"}


def _tenants_do_deploy():
    """Nomes do env `TENANTS` (trios `nome:api_uuid:worker_uuid`)."""
    txt = open(WORKFLOW, encoding="utf-8", errors="replace").read()
    bloco = re.search(r"TENANTS:\s*>-\s*\n(.*?)\n\s{0,6}steps:", txt, re.S)
    assert bloco, "nao achei o env TENANTS em build-backend.yml — o formato mudou"
    nomes = []
    for linha in bloco.group(1).splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        nomes.append(linha.split(":")[0])
    return nomes


def _apis_da_extensao():
    """As URLs de `AMBIENTES_CONHECIDOS`, sem os ambientes que o operador
    acrescentou a mao (esses vivem no storage do Chrome, nao aqui)."""
    txt = open(AMBIENTES, encoding="utf-8", errors="replace").read()
    bloco = re.search(r"AMBIENTES_CONHECIDOS\s*=\s*\[(.*?)\];", txt, re.S)
    assert bloco, "nao achei AMBIENTES_CONHECIDOS em ambientes.js — o formato mudou"
    corpo = "\n".join(
        l for l in bloco.group(1).splitlines() if not l.lstrip().startswith("//")
    )
    return re.findall(r"api:\s*[\"']([^\"']+)[\"']", corpo)


def test_todo_tenant_do_deploy_esta_na_extensao():
    """O teste que teria evitado o bgk nascer fora da captura."""
    tenants = _tenants_do_deploy()
    apis = _apis_da_extensao()

    faltando = []
    for nome in tenants:
        marca = SEM_SLUG_NO_HOST.get(nome, f"-{nome}-")
        if not any(marca in api for api in apis):
            faltando.append(nome)

    assert not faltando, (
        "tenant que RECEBE deploy e a extensao de captura nao conhece: "
        + ", ".join(faltando)
        + ". Acrescente em `extension/ambientes.js` (AMBIENTES_CONHECIDOS) no "
        "MESMO PR. Sem isso a sessao gov.br nunca chega nesse tenant e o "
        "coletor gated registra `parcial` para sempre, sem erro em lugar "
        "nenhum — foi o que aconteceu com o bgk-rs em 08/09/2026."
    )


def test_a_extensao_nao_conhece_tenant_que_nao_existe_mais():
    """O outro lado: cliente que saiu tem de sair da extensao tambem.

    Ambiente orfao nao e inofensivo — a extensao tenta POSTar nele a cada
    captura e a tela do popup passa a mostrar uma linha vermelha permanente,
    que e como se ensina o operador a ignorar a tela inteira.
    """
    tenants = _tenants_do_deploy()
    apis = _apis_da_extensao()

    orfas = []
    for api in apis:
        casou = any(
            SEM_SLUG_NO_HOST.get(nome, f"-{nome}-") in api for nome in tenants
        )
        if not casou:
            orfas.append(api)

    assert not orfas, (
        "a extensao conhece ambiente que nao recebe deploy: "
        + ", ".join(orfas)
        + ". Cliente que saiu tem de sair daqui tambem."
    )


def test_a_deteccao_realmente_enxerga_os_dois_arquivos():
    """Sem isto, um regex quebrado faria os dois testes acima passarem vazios."""
    tenants = _tenants_do_deploy()
    apis = _apis_da_extensao()

    assert len(tenants) >= 6, (
        f"li {len(tenants)} tenants do workflow — o env TENANTS mudou de forma"
    )
    assert len(apis) >= 6, (
        f"li {len(apis)} ambientes da extensao — AMBIENTES_CONHECIDOS mudou de forma"
    )
    assert "bgk" in tenants, "esperava o bgk no deploy"
    assert any("-bgk-" in a for a in apis), (
        "esperava o bgk na extensao — se sumiu, a correcao de 09/09/2026 foi desfeita"
    )
    assert len(tenants) == len(apis), (
        f"{len(tenants)} tenants no deploy contra {len(apis)} ambientes na "
        "extensao: os dois testes acima dizem qual lado esta sobrando"
    )
