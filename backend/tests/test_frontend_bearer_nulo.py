"""Nenhuma tela pode mandar `Authorization: Bearer ${token}` sem proteger o nulo.

31/08/2026: a exportacao de PDF da tela de Convenios (SIGCON) voltava
`{"detail":"Token inválido"}`. A causa nao era sessao vencida:

  1. `lib/api.ts` APAGA `pactha_token` do localStorage assim que o primeiro
     refresh da certo — e a "auto-cura" comentada la. Dai em diante
     `getItem("pactha_token")` devolve SEMPRE null.
  2. Tres telas montavam `Authorization: Bearer ${token}` sem proteger, o que
     vira a string literal "Bearer null".
  3. O backend le o BEARER ANTES DO COOKIE (`services/auth.py`:
     `if credentials: token = credentials.credentials`), entao o header
     invalido ATROPELAVA uma sessao boa. Dai "Token invalido" e nao
     "Token expirado" — o que atrasou o diagnostico.

Medido no log da API: `/api/export-pdf/convenios` teve 6 respostas 401 contra
1 sucesso; o unico sucesso foi logo apos um login, antes do primeiro refresh.

Nao ha suite de frontend neste repo (ver CLAUDE.md), entao a guarda mora aqui e
le o codigo-fonte — mesma tecnica de `test_registro_rotas`.
"""
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(RAIZ, "frontend", "src")

# `Bearer ${...}` SEM um `?` antes na mesma expressao — isto e, sem o
# `token ? { Authorization: ... } : {}` que as telas corretas usam.
_BEARER = re.compile(r"Authorization:\s*`Bearer \$\{([A-Za-z_.]+)\}`")


def _arquivos():
    for base, _, nomes in os.walk(SRC):
        for n in nomes:
            if n.endswith((".ts", ".tsx")):
                yield os.path.join(base, n)


def _rel(p):
    return os.path.relpath(p, RAIZ).replace("\\", "/")


def test_nenhum_bearer_sem_guarda_de_nulo():
    """⚠️ A guarda aceita duas formas, e as duas existem no repo hoje:

        headers: token ? { Authorization: `Bearer ${token}` } : {}
        ...(token ? { Authorization: `Bearer ${token}` } : {})

    O que ela reprova e o header montado direto, que manda "Bearer null" depois
    do primeiro refresh e derruba a sessao boa."""
    faltas = []
    for caminho in _arquivos():
        txt = open(caminho, encoding="utf-8").read()
        for m in _BEARER.finditer(txt):
            # a linha inteira em volta do casamento
            ini = txt.rfind("\n", 0, m.start()) + 1
            fim = txt.find("\n", m.end())
            linha = txt[ini:fim if fim > 0 else len(txt)]
            var = m.group(1)
            # protegido quando a MESMA linha tem o ternario sobre a variavel
            if re.search(rf"\b{re.escape(var)}\s*\?", linha):
                continue
            n = txt.count("\n", 0, m.start()) + 1
            faltas.append(f"{_rel(caminho)}:{n} -> {linha.strip()[:90]}")
    assert not faltas, (
        "header Authorization sem guarda de nulo (manda 'Bearer null' e "
        "atropela o cookie):\n  " + "\n  ".join(faltas))


def test_a_regex_da_guarda_realmente_pega_o_caso_ruim():
    """⚠️ Teste da FERRAMENTA, nao do codigo. Uma regex que nao casa nada faria
    o teste acima passar para sempre, dando a impressao de que o repo esta
    limpo — que e exatamente o modo de falha que este arquivo existe para
    impedir."""
    ruim = 'fetch(url, { headers: { Authorization: `Bearer ${token}` } })'
    bom1 = 'headers: token ? { Authorization: `Bearer ${token}` } : {},'
    bom2 = '...(token ? { Authorization: `Bearer ${token}` } : {}),'
    assert _BEARER.search(ruim), "a regex nao acha nem o caso ruim"
    for b in (bom1, bom2):
        m = _BEARER.search(b)
        assert m, "a regex deveria casar o texto e a guarda e que o absolve"
        assert re.search(rf"\b{m.group(1)}\s*\?", b), "a guarda nao reconhece a forma boa"


def test_as_tres_telas_do_incidente_usam_o_cliente_api():
    """As que quebraram passam a exportar pelo `api` (cookie + retry do
    interceptor), e nao por `fetch` cru."""
    for rel, rota in (("app/dashboard/convenios/page.tsx", "/export-pdf/convenios"),
                      # Virou aba de «Emendas parlamentares» em 17/09/2026.
                      ("components/emendas/AbaEstaduaisMG.tsx", "/export-pdf/emendas"),
                      ("app/dashboard/dou/page.tsx", "/export-pdf/dou")):
        txt = open(os.path.join(SRC, *rel.split("/")), encoding="utf-8").read()
        assert 'api.get("' + rota in txt or "api.get(`" + rota in txt, \
            f"{rel} nao exporta pelo cliente api"
        assert f'fetch(`${{api.defaults.baseURL}}{rota}' not in txt, \
            f"{rel} voltou a usar fetch cru"
