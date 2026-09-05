"""
A ABRANGENCIA POR UF DO CATALOGO — a mesma lista, escrita em tres lugares.

⭐ O PEDIDO (dono, 08/2026): "o sistema deve respeitar cada estado. Se for uma
cidade do Rio Grande do Sul, quando for criar usuario tem que aparecer so
modulos e permissoes daquele estado; nao tem que aparecer nada de Minas Gerais,
e vice-versa. Coisas em comum, por exemplo federais, ok."

Para isso, tres arquivos precisam concordar sobre EM QUE ESTADOS cada modulo
existe, e nenhum deles consegue importar os outros:

  1. `backend/services/permissoes.py`   `ufs` de cada `_Recurso` — recorta as
                                        CAIXINHAS do modal de Permissoes.
  2. `frontend/src/lib/telas.ts`        `ufs` de cada `TelaDef` — recorta os
                                        CHIPS de "Telas com acesso".
  3. `frontend/src/lib/estadual.ts`     os mapas de fonte por UF — sao a VERDADE
                                        sobre onde cada tela existe, e quem faz
                                        o menu lateral esconder o que nao ha.

⚠️ POR QUE UM TESTE, E NAO UM IMPORT. Divergir aqui NAO da erro: da um cliente
gaucho vendo a caixinha "Acordo FES (divida saude MG)", ou — o caso caro — um
estado novo entrando em `DIARIO_POR_UF` e a permissao do Diario Oficial
continuando escondida naquele tenant, sem ninguem entender por que o
administrador "nao consegue liberar" uma tela que ele ve no menu.

Este repo ja tem a cicatriz: `telas_catalog.py` e `telas.ts` sao a mesma lista
escrita duas vezes e divergiram em seis chaves (ver test_apagao_incremento_4.py).

Rodar:
    python -m pytest backend/tests/test_catalogo_por_uf.py -v
"""
import re
from pathlib import Path

import pytest

from services.permissoes import CATALOGO

REPO = Path(__file__).resolve().parent.parent.parent
TELAS_TS = REPO / "frontend" / "src" / "lib" / "telas.ts"
ESTADUAL_TS = REPO / "frontend" / "src" / "lib" / "estadual.ts"

# As 27 unidades da federacao. Guarda contra typo — "RJ" trocado por "JR" nao
# quebraria nada em tempo de execucao: so esconderia o modulo para sempre.
UFS_VALIDAS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}


def _fonte(arquivo: Path) -> str:
    if not arquivo.exists():      # backend empacotado sozinho
        pytest.skip("frontend nao esta neste checkout")
    return arquivo.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Leitura dos dois arquivos do frontend
# ---------------------------------------------------------------------------
def _ufs_das_telas() -> dict:
    """`{chave_da_tela: {UFs}}` lido de `TELAS` em telas.ts. Tela sem `ufs` (a
    federal) entra com conjunto VAZIO, e nao fica de fora: a diferenca entre
    "federal" e "esqueci de declarar" e justamente o que se quer comparar."""
    fonte = _fonte(TELAS_TS)
    saida = {}
    for chave, resto in re.findall(r'\{\s*key:\s*"([a-z_]+)",([^}]*)\}', fonte):
        lista = re.search(r'ufs:\s*\[([^\]]*)\]', resto)
        saida[chave] = set(re.findall(r'"([A-Z]{2})"', lista.group(1))) if lista else set()
    return saida


def _bloco(fonte: str, nome: str) -> str:
    """O trecho de `export const <nome>` ate o proximo `export`. Corta por
    ancora e nao por regex esperta: se alguem reorganizar o arquivo, o teste
    falha em vez de ler o bloco errado calado."""
    marca = f"export const {nome}"
    assert marca in fonte, f"{nome} sumiu de estadual.ts — conferir este teste"
    trecho = fonte[fonte.index(marca) + len(marca):]
    corte = trecho.find("\nexport ")
    return trecho if corte < 0 else trecho[:corte]


def _ufs_do_mapa(nome: str) -> set:
    """As chaves de um `Record<string, ...>` por UF (`  MG: {...}` ou
    `  MG: "..."`), ou os itens de um `new Set<string>([...])`."""
    bloco = _bloco(_fonte(ESTADUAL_TS), nome)
    if "new Set" in bloco.split("\n", 1)[0] or bloco.lstrip().startswith("= new Set"):
        dentro = re.search(r'\[([^\]]*)\]', bloco)
        return set(re.findall(r'"([A-Z]{2})"', dentro.group(1) if dentro else ""))
    return set(re.findall(r'(?m)^  ([A-Z]{2}):', bloco))


# ---------------------------------------------------------------------------
# Leitura do catalogo do Python
# ---------------------------------------------------------------------------
def _ufs_dos_recursos() -> dict:
    """`{recurso: {UFs}}` do catalogo de permissoes.

    Todas as caixinhas de um recurso tem as MESMAS UFs (elas saem do
    `_Recurso`), e o teste logo abaixo cobra isso — a tela agrupa por recurso e
    um verbo com abrangencia propria seria invisivel no desenho."""
    saida = {}
    for permissao in CATALOGO.values():
        saida.setdefault(permissao.recurso, set()).update(permissao.ufs)
    return saida


# ===========================================================================
# 1. Sanidade do proprio catalogo do Python
# ===========================================================================
def test_as_ufs_do_catalogo_existem():
    for chave, permissao in CATALOGO.items():
        for uf in permissao.ufs:
            assert uf in UFS_VALIDAS, f"{chave}: UF desconhecida {uf!r}"


def test_um_recurso_tem_uma_abrangencia_so():
    """Duas caixinhas do mesmo modulo com UFs diferentes nao teriam como ser
    desenhadas: o cartao por estado e por RECURSO, nao por verbo."""
    for permissao in CATALOGO.values():
        esperado = _ufs_dos_recursos()[permissao.recurso]
        assert set(permissao.ufs) == esperado, permissao.chave


def test_vigencias_e_federal():
    """A caixinha «Vigencias a vencer» vale em qualquer tenant: instrumento com
    prazo existe em todo lugar, e o alerta le convenio estadual E federal.
    Marca-la como estadual a esconderia justamente de quem so tem TransfereGov."""
    assert CATALOGO["vigencias.ver"].ufs == ()


# ===========================================================================
# 2. O Python x os chips do frontend
# ===========================================================================
def test_a_tela_e_a_permissao_concordam_sobre_os_estados():
    """A mesma chave governa o chip («Telas com acesso») e as caixinhas do modal
    de Permissoes. Divergir esconderia o chip num estado e a caixinha noutro —
    o administrador marcaria a tela e a pessoa continuaria sem poder abri-la."""
    telas = _ufs_das_telas()
    recursos = _ufs_dos_recursos()
    for chave, ufs_tela in telas.items():
        if chave not in recursos:
            # `bi_tela`, `bi_link` e `paineis` nao tem recurso homonimo (as duas
            # primeiras sao verbos de `bi`; a terceira nao tem caixinha). Nada a
            # comparar — e todas as tres sao federais dos dois lados.
            assert not ufs_tela, f"{chave}: tela com UF e sem recurso no Python"
            continue
        assert ufs_tela == recursos[chave], (
            f"{chave}: telas.ts diz {sorted(ufs_tela)} e permissoes.py diz "
            f"{sorted(recursos[chave])}"
        )


# ===========================================================================
# 3. Os dois catalogos x a VERDADE de estadual.ts
# ===========================================================================
def test_o_diario_oficial_cobre_os_estados_com_provedor():
    """`DIARIO_POR_UF` e quem decide se a tela do Diario aparece no menu. UF que
    ganha provedor e nao entra no catalogo vira tela visivel e impossivel de
    conceder."""
    assert _ufs_dos_recursos()["dou"] == _ufs_do_mapa("DIARIO_POR_UF")


def test_as_emendas_estaduais_cobrem_os_estados_com_coletor():
    assert _ufs_dos_recursos()["emendas"] == _ufs_do_mapa("FONTE_EMENDAS_ESTADUAIS")


def test_cada_tela_do_grupo_estaduais_carrega_o_proprio_estado():
    """⭐ ERA O CONTRARIO ATE 05/09/2026, e a inversao e o incremento inteiro.

    Ate aqui `convenios.ver` governava as DEZ telas do grupo «Estaduais» do
    menu, e por isso a abrangencia dela tinha de ser a UNIAO dos mapas de todas
    elas — (MG, ES, GO, RS). O efeito colateral era o que o dono mandou
    consertar: liberar «Convênios Estaduais» concedia junto Repasses,
    Cofinanciamento, Monitoramento e as quatro do RS, sem jeito de separar.

    Agora cada tela tem chave e UF proprias, e a conferencia e uma a uma: uma UF
    que ganhe a fonte de uma delas e nao entre no catalogo fica com o menu
    mostrando a tela e o cadastro de usuarios sem a caixinha para libera-la.

    ⚠️ E A UNIAO CONTINUA SENDO CONFERIDA no fim: nenhum estado pode ter sumido
    do grupo na divisao — que e o defeito que a divisao poderia introduzir."""
    recursos = _ufs_dos_recursos()
    por_tela = {
        "convenios": "FONTE_CONVENIOS_ESTADUAIS",
        "repasses": "REPASSES_POR_UF",
        "cofinanciamento": "COFINANCIAMENTO_POR_UF",
        "consulta_popular": "CONSULTA_POPULAR_POR_UF",
        "programas_rs": "PROGRAMAS_POR_UF",
        "funrigs": "CONTEUDO_ESTADUAL_POR_UF",
        "emendas_rs": "CONTEUDO_ESTADUAL_POR_UF",
        "tce_rs": "CONTEUDO_ESTADUAL_POR_UF",
    }
    for chave, mapa in por_tela.items():
        assert recursos[chave] == _ufs_do_mapa(mapa), (
            f"{chave}: catalogo diz {sorted(recursos[chave])} e {mapa} diz "
            f"{sorted(_ufs_do_mapa(mapa))}")

    # `monitoramento` nao sai de um dos mapas acima: ele espelha
    # `MONITORAMENTO_POR_UF`, que existe onde a NORMA estadual cria a obrigacao.
    assert recursos["monitoramento"] == _ufs_do_mapa("MONITORAMENTO_POR_UF")

    # A uniao: o grupo inteiro continua cobrindo os mesmos estados de antes da
    # divisao. Se esta linha cair, alguma tela perdeu o estado dela no caminho.
    uniao = set()
    for chave in list(por_tela) + ["monitoramento"]:
        uniao |= recursos[chave]
    esperado = set()
    for mapa in ("FONTE_CONVENIOS_ESTADUAIS", "REPASSES_POR_UF",
                 "COFINANCIAMENTO_POR_UF", "CONSULTA_POPULAR_POR_UF",
                 "PROGRAMAS_POR_UF", "CONTEUDO_ESTADUAL_POR_UF",
                 "MONITORAMENTO_POR_UF"):
        esperado |= _ufs_do_mapa(mapa)
    assert uniao == esperado


def test_o_acordo_fes_e_so_de_minas():
    """A divida da saude e um acordo da SES-MG — nao existe fora de Minas. Nao
    ha mapa em estadual.ts para ela: quem esconde a tela e o `ufAmbiente !==
    "MG"` do menu (frontend/src/app/dashboard/layout.tsx). Este teste e a copia
    escrita desse fato, para o catalogo nao afrouxar sozinho."""
    assert _ufs_dos_recursos()["acordofes"] == {"MG"}


# ===========================================================================
# 4. O que NAO pode virar estadual
# ===========================================================================
def test_os_modulos_federais_continuam_sem_uf():
    """A lista e NOMINAL de proposito: marcar um destes com UF por engano
    sumiria com ele em todo tenant de outro estado — e o TransfereGov ou o RM
    sumindo de um cliente e a falha mais cara que este recorte pode causar."""
    federais = ("transferegov", "rm", "gestao", "documentos", "fns", "sismob",
                "investsus", "simec", "parlamentares", "cauc", "bi", "ai",
                "usuarios", "cofre", "sessoes", "auditoria", "frescor", "uso",
                "vigencias")
    recursos = _ufs_dos_recursos()
    for recurso in federais:
        assert recursos.get(recurso, set()) == set(), recurso
