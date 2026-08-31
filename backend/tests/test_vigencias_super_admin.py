"""O modal de Vigencias do super-admin mostrava so os convenios ESTADUAIS.

Relatado pelo dono e confirmado no codigo: o bloco que acrescenta as VOLUNTARIAS
federais estava atras de `if municipio_id or municipio_ids:`. O super-admin tem
`allowed_municipio_ids = None`, o handler deixa `mids = None`, os dois parametros
chegam nulos e o portao da falso — o bloco inteiro era pulado.

O bloco dos ESTADUAIS, logo acima, nunca teve esse portao: sem municipio ele
consulta o tenant inteiro. Dai a assimetria — usuario comum (carteira = lista nao
vazia) via os dois; super-admin via so um.

"Sem recorte" significa TODOS, e nao NENHUM.
"""
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTER = os.path.join(RAIZ, "routers", "convenios.py")


def _fonte():
    return open(ROUTER, encoding="utf-8").read()


def _codigo():
    return "\n".join(l for l in _fonte().splitlines() if not l.lstrip().startswith("#"))


def test_o_portao_que_apagava_as_voluntarias_sumiu():
    """⚠️ A checagem roda sobre o codigo SEM COMENTARIO: a explicacao do conserto
    cita o portao antigo para dizer o que ele fazia."""
    assert "if municipio_id or municipio_ids:" not in _codigo()


def test_sem_municipio_a_consulta_abre_para_o_tenant_inteiro():
    """O ramo novo: nenhum recorte -> WHERE TRUE, igual ao que os estaduais ja
    faziam. Sao dois endpoints (/alertas e /prestacao-contas) e os dois mudaram."""
    codigo = _codigo()
    assert codigo.count('_mun_sql = "TRUE"; _vp = {}') == 2


def test_os_recortes_de_quem_TEM_carteira_continuam_iguais():
    """Nao-regressao: usuario comum e consulta por municipio nao podem mudar de
    comportamento — a assimetria se resolve abrindo o lado que faltava, nao
    fechando o que funcionava."""
    codigo = _codigo()
    assert codigo.count('_mun_sql = "municipio_id = :m"') == 2
    assert codigo.count('_mun_sql = "municipio_id = ANY(:mids)"') == 2


def test_a_ordem_dos_ramos_poe_o_mais_especifico_primeiro():
    """municipio_id (um municipio) antes de municipio_ids (carteira) antes de
    TRUE (tudo). Invertida, a consulta por municipio viraria consulta do tenant."""
    codigo = _codigo()
    for trecho in re.findall(r"if municipio_id:.*?_vp = \{\}", codigo, re.S):
        i_um = trecho.index('"municipio_id = :m"')
        i_lista = trecho.index('"municipio_id = ANY(:mids)"')
        i_tudo = trecho.index('"TRUE"')
        assert i_um < i_lista < i_tudo


def test_a_carteira_VAZIA_continua_devolvendo_nada():
    """⚠️ O caso que NAO pode ser confundido com "sem recorte": usuario cuja
    carteira e vazia tem `mids == []` e o handler devolve [] ANTES de chegar
    aqui. Se um dia esse `return []` sair, o `elif municipio_ids:` daria falso e
    a lista vazia cairia no ramo TRUE — o usuario passaria a ver o tenant
    inteiro. E por isso que o ramo do meio testa a LISTA, e nao `is not None`."""
    fonte = _fonte()
    assert "return []          # carteira vazia" in fonte or \
           re.search(r"if not mids:\s*\n\s*return \[\]", fonte), \
        "a guarda da carteira vazia sumiu do handler"
    assert "elif municipio_ids:" in _codigo(), \
        "o ramo do meio precisa testar a lista (vazia = falso), nao `is not None`"
