"""Parametros do ambiente — as listas que o CLIENTE cadastra.

Pedido do dono (11/08/2026): o administrador do cliente cadastra parametros e o
sistema os usa nos formularios. Primeiro tipo: `perfil_usuario` — o Perfil
(Rotulo) que antes era uma lista fixa em codigo.

⚠️ O ROTULO CONTINUA SENDO ROTULO. Cadastrar um perfil novo NAO cria poder
nenhum: quem concede acesso sao as telas, os municipios e as permissoes por
acao, usuario a usuario. A unica chave com significado no codigo e `admin`
(abre a tela de Usuarios e o Cofre — `routers/users.py::_require_admin`,
`routers/cofre.py`), e por isso ela nasce RESERVADA: o cliente reordena e ate
renomeia o texto, mas nao apaga nem troca a chave. Um cliente que apagasse
`admin` se trancaria fora do proprio sistema.

⚠️ ISOLAMENTO ENTRE CLIENTES e automatico: o PACTHA e single-tenant (um banco
por cliente), entao a tabela ja e privada — nao ha, nem deve haver, coluna de
tenant aqui (ver o cabecalho de `migrations/add_parametros.sql`).

PERMISSAO: a tela de Parametros vive em Configuracoes e e governada pelo PAPEL
`admin`, como as demais abas sem chave de tela (Usuarios, Service Tokens,
Status dos Dados). A leitura e aberta a quem esta logado de proposito — o
seletor de perfil do cadastro de usuario precisa dos rotulos para nao mostrar
chave crua, e a lista nao revela nada sensivel (sao rotulos de organizacao).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services import authz
from services.audit import registrar
from services.auth import ensure_tela, get_current_user
from services.registro_rotas import declarado, exige

router = APIRouter(prefix="/api/parametros", tags=["parametros"])

# Os tipos que o sistema conhece. Tipo novo entra aqui E ganha consumidor —
# lista que ninguem le e formulario que promete o que nao cumpre.
TIPOS = {
    "perfil_usuario": "Perfil (rótulo) de usuário",
}


# ⚠️ `_require_admin` SAIU em 05/09/2026. Parametros virou uma TELA de verdade
# (`parametros.ver` / `parametros.editar`, tela `parametros`), e o gate por PAPEL
# passou a contradizer a nova regra: o dono marcava a aba para alguem e o papel o
# expulsava mesmo assim. Quem barra agora sao as duas chaves, que e o que a tela
# de Usuarios desenha. Mesmo movimento feito em `routers/users.py`.
#
# ⚠️ E as duas chaves sao NOVAS: ate aqui esta tela pegava carona em
# `usuarios.ver`/`usuarios.editar` — quem editava PESSOAS editava as LISTAS, sem
# jeito de separar as duas coisas.


def _valida_tipo(tipo: str) -> str:
    if tipo not in TIPOS:
        raise HTTPException(400, f"Tipo de parâmetro desconhecido: {tipo}")
    return tipo


class ParametroCreate(BaseModel):
    tipo: str
    rotulo: str
    # A CHAVE gravada no cadastro (ex.: `users.role`). Opcional: quando o
    # administrador nao informa, derivamos do rotulo — ele nao deveria precisar
    # pensar em "chave" para cadastrar "Secretário de Saúde".
    valor: Optional[str] = None
    ordem: Optional[int] = None


class ParametroUpdate(BaseModel):
    # ⚠️ `valor` NAO entra: a chave e imutavel depois de criada. Renomea-la
    # orfanaria toda conta que ja a usa (o `users.role` continuaria com a chave
    # velha e a tela mostraria texto cru). Quem muda e o rotulo.
    rotulo: Optional[str] = None
    ordem: Optional[int] = None
    ativo: Optional[bool] = None


def _chave_de(rotulo: str) -> str:
    """"Secretário de Saúde" -> "secretario_de_saude". ASCII, minusculo e sem
    espaco porque a chave viaja em `users.role` (varchar) e e comparada em
    codigo — acento e maiuscula sao fonte de bug silencioso."""
    import re
    import unicodedata
    base = unicodedata.normalize("NFKD", rotulo or "").encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-zA-Z0-9]+", "_", base).strip("_").lower()
    return base[:40] or "perfil"


@router.get("", dependencies=[declarado("parametros.ver", "usuarios.ver")])
async def listar(
    tipo: str,
    incluir_inativos: bool = False,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Os parametros de um tipo.

    ⭐ ACEITA `parametros.ver` OU `usuarios.ver`, e o OU e a peca importante:
    quem cadastra PESSOA precisa dos rotulos de perfil para o seletor, e obrigar
    `parametros.ver` para isso significaria que conceder a tela de Usuarios sem
    a de Parametros produz um seletor de perfil vazio — cadastro quebrado por
    uma permissao que ninguem entenderia ter de marcar junto. A lista tambem
    alimenta a TRADUCAO de chave -> rotulo em qualquer tela.

    ⚠️ E so LEITURA. Escrever parametro continua exigindo `parametros.editar` +
    a tela `parametros`, que e a separacao que este incremento criou."""
    if not (authz.pode(current, "parametros.ver")
            or authz.pode(current, "usuarios.ver")):
        authz.exigir(current, "parametros.ver")
    _valida_tipo(tipo)
    where = "WHERE tipo = :t" + ("" if incluir_inativos else " AND ativo")
    rows = (await db.execute(text(
        f"SELECT id, tipo, valor, rotulo, ordem, ativo, reservado "
        f"FROM parametros {where} ORDER BY ordem, rotulo"), {"t": tipo})).fetchall()
    return [{"id": r[0], "tipo": r[1], "valor": r[2], "rotulo": r[3],
             "ordem": r[4], "ativo": r[5], "reservado": r[6]} for r in rows]


@router.post("", dependencies=[exige("parametros.editar")])
async def criar(
    req: ParametroCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_tela(current, "parametros")
    tipo = _valida_tipo(req.tipo)
    rotulo = (req.rotulo or "").strip()
    if not rotulo:
        raise HTTPException(400, "Informe o nome do parâmetro")
    valor = _chave_de(req.valor or rotulo)
    ja = (await db.execute(text(
        "SELECT id, ativo FROM parametros WHERE tipo = :t AND valor = :v"),
        {"t": tipo, "v": valor})).first()
    if ja:
        # Cadastrar de novo algo que existe DESATIVADO e, na cabeca de quem
        # cadastra, "trazer de volta" — e nao um erro. Reativa e atualiza o
        # rotulo em vez de mandar a pessoa procurar o registro escondido.
        if not ja[1]:
            await db.execute(text(
                "UPDATE parametros SET ativo = TRUE, rotulo = :r WHERE id = :i"),
                {"r": rotulo, "i": ja[0]})
            await db.commit()
            await registrar(db, action="parametro.reativar", user=current, request=request,
                            target_type="parametro", target_id=ja[0], alvo_nome=rotulo,
                            details={"tipo": tipo, "valor": valor})
            return {"id": ja[0], "tipo": tipo, "valor": valor, "rotulo": rotulo,
                    "reativado": True}
        raise HTTPException(400, f"Já existe «{rotulo}» nesta lista")
    ordem = req.ordem if req.ordem is not None else 100
    novo = (await db.execute(text(
        "INSERT INTO parametros (tipo, valor, rotulo, ordem, criado_por) "
        "VALUES (:t, :v, :r, :o, :u) RETURNING id"),
        {"t": tipo, "v": valor, "r": rotulo, "o": ordem,
         "u": getattr(current, "id", None)})).scalar()
    await db.commit()
    await registrar(db, action="parametro.criar", user=current, request=request,
                    target_type="parametro", target_id=novo, alvo_nome=rotulo,
                    details={"tipo": tipo, "valor": valor, "ordem": ordem})
    return {"id": novo, "tipo": tipo, "valor": valor, "rotulo": rotulo,
            "ordem": ordem, "ativo": True, "reservado": False}


@router.patch("/{param_id}", dependencies=[exige("parametros.editar")])
async def atualizar(
    param_id: int,
    req: ParametroUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_tela(current, "parametros")
    row = (await db.execute(text(
        "SELECT tipo, valor, rotulo, ordem, ativo, reservado FROM parametros WHERE id = :i"),
        {"i": param_id})).first()
    if not row:
        raise HTTPException(404, "Parâmetro não encontrado")
    tipo, valor, rotulo_antes, ordem_antes, ativo_antes, reservado = row
    # Reservado do sistema: reordenar pode, renomear pode (é só texto de tela),
    # DESATIVAR não — `admin` sumido da lista é o cliente trancado fora.
    if reservado and req.ativo is False:
        raise HTTPException(400, "Este perfil é do sistema e não pode ser desativado")
    rotulo = (req.rotulo or "").strip() if req.rotulo is not None else rotulo_antes
    if not rotulo:
        raise HTTPException(400, "O nome não pode ficar vazio")
    ordem = req.ordem if req.ordem is not None else ordem_antes
    ativo = req.ativo if req.ativo is not None else ativo_antes
    await db.execute(text(
        "UPDATE parametros SET rotulo = :r, ordem = :o, ativo = :a WHERE id = :i"),
        {"r": rotulo, "o": ordem, "a": ativo, "i": param_id})
    await db.commit()
    await registrar(
        db, action="parametro.editar", user=current, request=request,
        target_type="parametro", target_id=param_id, alvo_nome=rotulo,
        valor_antes={"rotulo": rotulo_antes, "ordem": ordem_antes, "ativo": ativo_antes},
        valor_depois={"rotulo": rotulo, "ordem": ordem, "ativo": ativo},
        details={"tipo": tipo, "valor": valor},
    )
    return {"id": param_id, "tipo": tipo, "valor": valor, "rotulo": rotulo,
            "ordem": ordem, "ativo": ativo, "reservado": reservado}


@router.delete("/{param_id}", dependencies=[exige("parametros.editar")])
async def excluir(
    param_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Exclui de vez — SO quando ninguem usa. Com gente cadastrada no perfil, a
    saida honesta e DESATIVAR (some do seletor, continua traduzindo quem tem)."""
    ensure_tela(current, "parametros")
    row = (await db.execute(text(
        "SELECT tipo, valor, rotulo, reservado FROM parametros WHERE id = :i"),
        {"i": param_id})).first()
    if not row:
        raise HTTPException(404, "Parâmetro não encontrado")
    tipo, valor, rotulo, reservado = row
    if reservado:
        raise HTTPException(400, "Este perfil é do sistema e não pode ser excluído")
    if tipo == "perfil_usuario":
        emuso = int((await db.execute(text(
            "SELECT count(*) FROM users WHERE role = :v"), {"v": valor})).scalar() or 0)
        if emuso:
            raise HTTPException(
                400,
                f"{emuso} usuário(s) usam este perfil. Desative-o em vez de excluir "
                f"— assim ele some do cadastro e continua identificando quem já o tem.")
    await db.execute(text("DELETE FROM parametros WHERE id = :i"), {"i": param_id})
    await db.commit()
    await registrar(db, action="parametro.excluir", user=current, request=request,
                    target_type="parametro", target_id=param_id, alvo_nome=rotulo,
                    details={"tipo": tipo, "valor": valor})
    return {"excluido": True, "id": param_id}
