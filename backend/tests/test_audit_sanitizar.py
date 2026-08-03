"""O sanitizador da trilha, atacado pelo que ele PRECISA barrar.

Por que este arquivo existe: a trilha e append-only (Inc. 3), entao segredo que
passa daqui fica gravado para sempre num sistema de setor publico. Nao da para
"limpar depois".

O caso `privateKey` nao e hipotetico — foi um VAZAMENTO REAL encontrado ao atacar
a primeira versao. A lista negra trazia `private_key` com sublinhado e a
comparacao era por substring na chave em minusculas, entao `privatekey` nao
casava. `apiKey` escapava de ser bug so porque a lista, por acaso, tinha as duas
grafias. Hoje os dois lados sao ACHATADOS (so alfanumerico), e por isso a classe
inteira de grafias cai numa entrada so.
"""
import pytest

from services.audit import sanitizar

JWT = "eyJhbGciOiJIUzI1NiJ9.PAYLOAD.assinatura"
SENHA = "Monte2011+"


def _texto(v) -> str:
    return repr(sanitizar(v))


@pytest.mark.parametrize("entrada", [
    {"senha": SENHA},
    {"SENHA": SENHA},
    {"senha_atual": SENHA, "nova_senha": SENHA},
    {"password": SENHA},
    {"user": {"cfg": {"secret": JWT}}},                 # aninhada
    {"cookies": [{"name": "s", "value": JWT}]},         # dentro de lista
    {"tokens": [JWT, JWT]},
    {"Authorization": f"Bearer {JWT}"},
    # As tres grafias da MESMA chave — a que vazava e as vizinhas.
    {"privateKey": JWT},
    {"private_key": JWT},
    {"private-key": JWT},
    {"Private Key": JWT},
    {"apiKey": JWT},
    {"csrfToken": JWT},
])
def test_segredo_nunca_sai_em_claro(entrada):
    saida = _texto(entrada)
    assert JWT not in saida and SENHA not in saida, saida


@pytest.mark.parametrize("chave", ["cookie_size", "cookieSize"])
def test_metrica_numerica_passa_em_qualquer_grafia(chave):
    """Excecao nominal: METRICA sobre o segredo, nunca o segredo."""
    assert sanitizar({chave: 1234}) == {chave: 1234}


@pytest.mark.parametrize("chave", ["cookie_size", "cookieSize", "senha_changed"])
def test_excecao_abusada_com_string_e_redigida(chave):
    """A segunda trava: um segredo nunca e numero nem booleano."""
    assert JWT not in _texto({chave: JWT})


def test_bool_de_metrica_passa():
    assert sanitizar({"senha_changed": True}) == {"senha_changed": True}


def test_dado_limpo_atravessa_intacto():
    d = {"municipio": "Monte Sião", "total": 12, "ativo": True}
    assert sanitizar(d) == d


# --- estruturas hostis: nao podem DERRUBAR a acao ---------------------------
# `registrar_critico` roda na mesma transacao do negocio: uma excecao aqui
# impediria o usuario de salvar o proprio trabalho.

def test_aninhamento_profundo_nao_estoura_nem_vaza():
    d: dict = {}
    cur = d
    for _ in range(200):
        cur["n"] = {}
        cur = cur["n"]
    cur["senha"] = JWT
    assert JWT not in _texto(d)


def test_referencia_circular_nao_estoura():
    d: dict = {"a": 1}
    d["eu"] = d
    sanitizar(d)   # nao pode levantar RecursionError


def test_colecao_gigante_e_truncada_com_marca():
    saida = sanitizar({"lista": list(range(100_000))})
    lista = saida["lista"]
    assert len(lista) < 1000
    # o corte tem de DEIXAR MARCA: auditor nao pode ler lista podada como
    # lista completa e concluir que alguem removeu itens.
    assert "nao registrados" in str(lista[-1])
