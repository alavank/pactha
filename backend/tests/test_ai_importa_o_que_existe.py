"""O chat não pode importar, dentro de função, um nome que não existe mais.

⚠️ O DEFEITO QUE ISTO PREVINE DUROU OITO DIAS: em 06/09/2026 a listagem da SPA
saiu de `routers/transferegov.py` (com `_fetch_listagem` e `_norm`), mas
`routers/ai.py` importava os dois DENTRO das ferramentas `query_plano_acao` e
`search_by_parlamentar`. Import dentro de função só explode quando a função
roda — o boot sobe, a suíte passa, e toda pergunta sobre emenda Pix respondia
"Erro ao consultar a API" até 14/09/2026. Justo a fonte por onde chega a
maioria das emendas de deputado federal.

Este teste lê o `ai.py` e confere que cada `from routers.<x> import <nome>` e
`from services.<x> import <nome>` aponta para um nome que existe.
"""
import ast
import importlib
import inspect

from routers import ai


def test_todo_import_tardio_do_chat_aponta_para_nome_que_existe():
    faltando = []
    for no in ast.walk(ast.parse(inspect.getsource(ai))):
        if not isinstance(no, ast.ImportFrom) or not no.module:
            continue
        if not no.module.startswith(("routers.", "services.", "ingestion.")):
            continue
        mod = importlib.import_module(no.module)
        for alias in no.names:
            if not hasattr(mod, alias.name):
                faltando.append(f"{no.module}.{alias.name} (linha {no.lineno})")
    assert not faltando, "o chat importa nome que não existe mais:\n  " + "\n  ".join(faltando)
