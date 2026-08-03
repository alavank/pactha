"""
O CATALOGO de permissoes, servido por API.

Existe por uma regra so: **o frontend nunca copia a lista de permissoes**. Ele a
busca aqui. Este repo ja tem a cicatriz do contrario — `services/telas_catalog.py`
e `frontend/src/lib/telas.ts` divergiram em seis chaves, e o comentario de la
ainda avisa que tela nova precisa entrar em TRES lugares. Divergencia de catalogo
de permissao nao aparece na tela: ela some com o acesso de alguem, em silencio.

Duas rotas, as duas auto-escopadas (por isso estao em
`services/registro_rotas.py::ROTAS_LIVRES`):

    GET /api/permissoes/catalogo   o texto do produto, igual para todo mundo
    GET /api/permissoes/minhas     o que o PROPRIO usuario pode

⚠️ `minhas` NAO e a lista de caixinhas marcadas: e o conjunto EFETIVO, ja
resolvido pela funcao pura (super-admin recebe tudo, somente-leitura perde os
verbos de escrita). E o que a tela precisa para saber quais botoes desenhar — e
desenhar botao que o servidor vai negar e pior do que nao desenhar.
"""
from fastapi import APIRouter, Depends

from models.user import User
from services import authz, permissoes
from services.auth import get_current_user, is_super_admin

router = APIRouter(prefix="/api/permissoes", tags=["permissoes"])


@router.get("/catalogo")
async def catalogo(current: User = Depends(get_current_user)):
    """Todas as permissoes que existem, agrupadas por secao e recurso.

    Sem gate de permissao de proposito: e conteudo estatico do produto (nenhum
    dado de municipio) e a propria tela de permissoes precisa dele para
    desenhar. Quem PODE conceder e outra pergunta, respondida por
    `usuarios.conceder` no endpoint que grava."""
    return permissoes.catalogo_para_api()


@router.get("/minhas")
async def minhas(current: User = Depends(get_current_user)):
    """O conjunto EFETIVO de quem esta perguntando, mais um resumo legivel.

    `chaves` e o que a tela usa para habilitar botao; `resumo` e a frase que o
    administrador le na tela de Usuarios ("Relatorio de Monitoramento: Ver,
    Editar")."""
    efetivas = authz.permissoes_de(current)
    return {
        "chaves": sorted(efetivas),
        "resumo": permissoes.resumo(efetivas),
        # O frontend precisa saber que este usuario passa por cima de tudo para
        # nao desenhar a tela de permissoes como se houvesse algo a conceder a
        # ele — e para nao sugerir que da para tirar.
        "super_admin": is_super_admin(current),
        "somente_leitura": bool(getattr(current, "somente_leitura", False)),
        # `AUTHZ_MODO`: enquanto for "aviso" a trava so registra, e a tela pode
        # explicar isso a quem estranhar ver um botao que ainda funciona.
        "modo": authz.modo(),
    }
