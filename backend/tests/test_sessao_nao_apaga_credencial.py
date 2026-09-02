"""A captura de sessao nao pode gravar por cima de uma CREDENCIAL do Cofre.

⚠️ ISTO JA ACONTECEU EM PRODUCAO, e por isso o teste existe. A extensao antiga
mandava `municipio_id`; o casamento por (automation_key, municipio_id) achou a
credencial gov.br da prefeitura e o blob de cookies substituiu a SENHA. Em
02/09/2026 havia duas linhas assim — freitas IBGE 3103900 e montesiao IBGE
3143401, o mesmo CPF — e a senha nao volta: o Cofre guarda so o cifrado, que
agora e um JSON de cookies.

⚠️ E O SEGUNDO TESTE E O QUE IMPORTA DE VERDADE. O criterio de "isto e sessao?"
existe em DOIS lugares: aqui e em `govbr_renew._load_govbr`. Se eles divergirem,
a captura considera credencial o que o renovador considera sessao (ou o
contrario) — e o sintoma no campo e "recapturei e continua sem sessao", sem erro
em lugar nenhum. Por isso o teste le o outro arquivo em vez de confiar na
memoria de quem escreveu.
"""
import re
from pathlib import Path

from routers.session_capture import conteudo_e_sessao

RAIZ = Path(__file__).resolve().parent.parent


def test_json_e_sessao_e_senha_nao_e():
    assert conteudo_e_sessao('{"cookies": []}') is True
    assert conteudo_e_sessao('{"cookies":[{"name":"JSESSIONID"}]}') is True
    # Senhas de verdade: nada disso pode ser confundido com sessao.
    assert conteudo_e_sessao("C0nv3nio@2026") is False
    assert conteudo_e_sessao("03754377620") is False
    assert conteudo_e_sessao("") is False
    assert conteudo_e_sessao(None) is False
    # ⚠️ Uma senha que POR ACASO comece com "{" seria tratada como sessao. E o
    # mesmo furo que `_load_govbr` tem, e a decisao e manter os dois iguais:
    # divergir aqui e pior que o furo compartilhado.
    assert conteudo_e_sessao("{senha-esquisita") is True


def test_o_criterio_e_o_MESMO_do_renovador():
    """`govbr_renew` decide por `dec.startswith("{")` — sem strip, sem json.loads.

    Se alguem "melhorar" um dos lados (strip, tentar json.loads, checar chave
    `cookies`) sem mexer no outro, este teste cai antes de a divergencia chegar
    em producao.
    """
    fonte = (RAIZ / "ingestion" / "govbr_renew.py").read_text(encoding="utf-8")
    assert 'startswith("{")' in fonte, (
        "govbr_renew mudou o criterio de 'isto e sessao?'; "
        "conteudo_e_sessao em routers/session_capture.py precisa acompanhar"
    )


def test_o_guard_existe_e_so_dispara_com_municipio():
    """O guard tem de estar preso a `mid is not None`.

    Sem essa condicao ele passaria a valer para a captura de ESCOPO DE INSTANCIA
    — onde credencial nao mora — e toda captura normal criaria uma linha nova em
    vez de atualizar a existente, enchendo o Cofre de sessoes orfas que o
    renovador nunca le.
    """
    fonte = (RAIZ / "routers" / "session_capture.py").read_text(encoding="utf-8")
    guard = re.search(
        r"if item is not None and mid is not None:(.{0,600}?)item = None",
        fonte, re.S,
    )
    assert guard, "o guard que preserva credencial sumiu de session_capture.py"
    assert "conteudo_e_sessao" in guard.group(1), (
        "o guard deixou de usar `conteudo_e_sessao` — o criterio compartilhado"
    )


def test_os_quatro_leitores_da_sessao_concordam_no_recorte():
    """Os quatro lugares que carregam a sessao gov.br usam `municipio_id IS NULL`.

    ⚠️ SE UM SO FICAR DE FORA, o conjunto volta a se contradizer. Foi assim que o
    freitas quebrou: o keepalive re-salvava cookies numa linha que o renovador
    nao lia e, ao fazer isso, empurrava o `updated_at` dela para a frente — a
    linha errada vencia o ORDER BY para sempre, e a captura nova era gravada e
    ignorada.
    """
    alvos = [
        "ingestion/govbr_renew.py",
        "ingestion/govbr_keepalive.py",
        "routers/control.py",
        "routers/transferegov.py",
    ]
    faltando = []
    for rel in alvos:
        txt = (RAIZ / rel).read_text(encoding="utf-8")
        # ⚠️ ANCORA EM `FROM cofre_senhas`, e nao em `length(senha_hash) > 1000`.
        # A primeira versao deste teste procurava a segunda expressao e casou com
        # um COMENTARIO em portugues que a cita para explicar o incidente —
        # acusou falta de filtro num arquivo que tinha o filtro. Ancorar na
        # clausula FROM prende a busca a uma consulta de verdade.
        for trecho in re.findall(r"FROM cofre_senhas(.{0,300})", txt, re.S):
            if "length(senha_hash) > 1000" not in trecho:
                continue   # consulta que nao seleciona sessao; nao se aplica
            if "municipio_id IS NULL" not in trecho:
                faltando.append(rel)
                break
    assert not faltando, (
        "estes leitores da sessao govbr nao filtram escopo de instancia: "
        + ", ".join(faltando)
    )
