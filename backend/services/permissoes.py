"""
CATALOGO de permissoes por ACAO (`recurso.acao`) e a funcao PURA que resolve
"o que este usuario pode".

POR QUE ESTE ARQUIVO EXISTE
---------------------------
Ate o Incremento 4 a permissao era BINARIA: ou a pessoa via a tela, ou nao via.
Quem via `rm` criava, editava, apagava e exportava Relatorio de Monitoramento —
nao existia dar LEITURA sem ESCRITA em lugar nenhum do sistema. A regra do dono
e outra, e ele a disse assim:

    "as permissoes serao assim mesmo: algumas pessoas so vao VER, outras EDITAR
     e assim por diante, e isso POR USUARIO."

    "existe sim uma categoria, quase um grupo, que sao os SUPER-ADMIN. So isso,
     simples assim: esses tem tudo, fazem tudo no sistema. Mas SO ELES. Eles sao
     tipo 'ROOT'."

Entao: super-admin passa por cima de tudo sem caixinha marcada; todo o resto
vale EXATAMENTE o que estiver marcado NO USUARIO.

AS TRES REGRAS DE DESENHO DESTE ARQUIVO
---------------------------------------
1. FONTE UNICA, NO BACKEND. O frontend NUNCA copia esta lista: ele a busca por
   API (`GET /api/permissoes/catalogo`). Este repo ja tem a cicatriz do contrario
   — `services/telas_catalog.py` e `frontend/src/lib/telas.ts` divergiram em seis
   chaves, e o comentario de la avisa que tela nova precisa entrar em TRES
   lugares. Divergencia de catalogo de permissao nao aparece na tela: ela some
   com o acesso de alguem, em silencio.

2. SEM BANCO. `permissoes_efetivas` e uma funcao PURA: recebe fatos sobre o
   usuario e devolve o conjunto de chaves. E o que torna o RBAC auditavel (da
   para ler a regra inteira num lugar so, e testa-la por tabela-verdade) e o que
   impede alguem reintroduzir um atalho `if role == 'admin'` daqui a seis meses
   — o atalho nao teria onde caber.

3. A CHAVE E DADO, O ROTULO E TEXTO. `rm.excluir` e contrato: vai para o banco
   (`user_permissoes.permissao`), para a API e para o `exige()` do router.
   Rotulo e descricao existem so para a tela; mudar a redacao nunca muda quem
   pode o que.

O QUE MORA AQUI E O QUE NAO MORA
--------------------------------
    aqui                       services/authz.py            services/registro_rotas.py
    ----                       -----------------            --------------------------
    o catalogo                 `exigir(user, "rm.excluir")` `exige("rm.excluir")` no router
    a funcao pura              o `AUTHZ_MODO`               a varredura de boot
    quem "escreve"             a linha na trilha            a allowlist de rotas livres

⚠️ O `escrita` de cada permissao NAO e "o verbo parece de escrita". E uma
pergunta operacional: **o guard de somente-leitura de `get_current_user` barra
esta acao?** Ele e por METODO HTTP (POST/PUT/PATCH/DELETE) com uma allowlist de
prefixos do Painel (`services/auth.py::READONLY_WRITE_ALLOW`). Por isso
`ai.exportar` e escrita (o endpoint e POST) e `bi.link` NAO e (o prefixo esta na
allowlist, para o prefeito publicar a propria TV). Marcar pelo verbo, e nao pelo
que o sistema faz, produziria uma tela que promete um botao que devolve 403.
"""
from dataclasses import dataclass
from typing import Iterable, Optional


# ---------------------------------------------------------------------------
# Secoes — o agrupamento da tela de permissoes, na ordem em que ela desenha
# ---------------------------------------------------------------------------
# A chave (slug ASCII) vai para o banco e para a API; o rotulo e so texto.
SEC_TRABALHO = "trabalho"
SEC_CONVENIOS = "convenios"
SEC_CONSULTAS = "consultas"
SEC_BI = "bi"
SEC_IA = "ia"
SEC_COFRE = "cofre"
SEC_USUARIOS = "usuarios"
SEC_TELEGRAM = "telegram"
SEC_AUDITORIA = "auditoria"

SECOES: list[dict] = [
    {"chave": SEC_TRABALHO, "rotulo": "Trabalho do dia a dia",
     "descricao": "O que a equipe produz dentro do sistema: anotacoes, "
                  "relatorios e documentos."},
    {"chave": SEC_CONVENIOS, "rotulo": "Convenios e transferencias",
     "descricao": "As bases que o sistema coleta dos portais do governo. "
                  "«Atualizar dados» dispara uma coleta nova."},
    {"chave": SEC_CONSULTAS, "rotulo": "Consultas e fontes",
     "descricao": "Telas de consulta a bases externas. So leitura e exportacao."},
    {"chave": SEC_BI, "rotulo": "Painel de Indicadores (BI)",
     "descricao": "O painel do gestor, o Modo Tela da TV e o link publico."},
    {"chave": SEC_IA, "rotulo": "Inteligencia Artificial",
     "descricao": "A IA do PACTHA. Cada consulta e paga por chamada."},
    {"chave": SEC_COFRE, "rotulo": "Cofre de senhas e sessoes",
     "descricao": "Credenciais de portais do governo. E a secao mais sensivel "
                  "do sistema."},
    {"chave": SEC_USUARIOS, "rotulo": "Usuarios e permissoes",
     "descricao": "Quem pode cadastrar pessoas e decidir o que elas fazem."},
    {"chave": SEC_TELEGRAM, "rotulo": "Telegram",
     "descricao": "Avisos no celular."},
    {"chave": SEC_AUDITORIA, "rotulo": "Auditoria",
     "descricao": "A trilha de atividades. O arquivo exportado entrega IP, "
                  "e-mail e historico de todo mundo."},
]

_SECAO_ROTULO = {s["chave"]: s["rotulo"] for s in SECOES}


# ---------------------------------------------------------------------------
# A permissao
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Permissao:
    """Uma caixinha da tela. Congelada porque e cacheada e devolvida a varios
    consumidores — se um deles mutasse, contaminaria os outros."""

    chave: str            # `rm.excluir` — CONTRATO (banco, API, router)
    secao: str            # slug de SECOES
    recurso: str          # `rm` — agrupa as caixinhas de um mesmo assunto
    recurso_rotulo: str   # "Relatorio de Monitoramento"
    verbo_rotulo: str     # "Excluir"
    descricao: str        # a frase que explica o que a caixinha libera
    # ⚠️ NAO e "o verbo parece de escrita". E: o guard de somente-leitura barra
    # esta acao? Ver o cabecalho do modulo.
    escrita: bool = False

    @property
    def rotulo(self) -> str:
        """Rotulo COMPLETO, para quando a caixinha aparece fora do agrupamento
        (resumo do usuario, trilha de auditoria, CSV)."""
        return f"{self.recurso_rotulo} — {self.verbo_rotulo}"

    def as_dict(self) -> dict:
        return {
            "chave": self.chave,
            "secao": self.secao,
            "secao_rotulo": _SECAO_ROTULO.get(self.secao, self.secao),
            "recurso": self.recurso,
            "recurso_rotulo": self.recurso_rotulo,
            "verbo": self.chave.split(".", 1)[1],
            "verbo_rotulo": self.verbo_rotulo,
            "rotulo": self.rotulo,
            "descricao": self.descricao,
            "escrita": self.escrita,
        }


# ---------------------------------------------------------------------------
# Os verbos — texto gerado, para 60 caixinhas nao virarem 60 redacoes diferentes
# ---------------------------------------------------------------------------
# Redacao uniforme nao e economia de digitacao: e o que permite ao administrador
# ler a quinta caixinha sem reler a frase inteira. So o que E diferente entre um
# recurso e outro (o alvo) muda de linha para linha.
_VERBOS: dict[str, dict] = {
    "ver": {
        "rotulo": "Ver",
        "frase": "Abrir a tela e consultar {plural}.",
        "escrita": False,
    },
    "criar": {
        "rotulo": "Criar",
        "frase": "Cadastrar {singular}.",
        "escrita": True,
    },
    "editar": {
        "rotulo": "Editar",
        "frase": "Alterar {plural} que ja existem, inclusive as de outras pessoas.",
        "escrita": True,
    },
    "excluir": {
        "rotulo": "Excluir",
        "frase": "Apagar {plural}. Nao ha desfazer.",
        "escrita": True,
    },
    "exportar": {
        "rotulo": "Exportar",
        "frase": "Baixar {plural} em arquivo. O dado sai do sistema.",
        "escrita": False,
    },
    "atualizar": {
        "rotulo": "Atualizar dados",
        "frase": "Mandar o sistema buscar dados novos {fonte}. Uma coleta muda "
                 "situacao e valores de dezenas de registros de uma vez, para "
                 "todo mundo — nao so para quem clicou.",
        "escrita": True,
    },
}


@dataclass(frozen=True)
class _Recurso:
    chave: str
    secao: str
    rotulo: str
    plural: str            # "os Relatorios de Monitoramento"
    singular: str          # "um Relatorio de Monitoramento novo"
    verbos: tuple
    fonte: str = ""        # so para o verbo `atualizar`: "no SIGCON-MG"


# ⚠️ Recurso novo entra AQUI e em `migrations/add_permissoes_por_acao.sql` (a
# tabela-catalogo que serve de chave estrangeira). O teste
# `test_permissoes_catalogo.py::test_sql_semeia_exatamente_o_catalogo_do_python`
# quebra se os dois divergirem — de proposito: chave que existe so no Python nao
# pode ser gravada (a FK recusa), e chave que existe so no SQL e caixinha que
# nunca aparece na tela.
_RECURSOS: tuple = (
    # --- Trabalho do dia a dia (CRUD completo + exportar) -------------------
    _Recurso("gestao", SEC_TRABALHO, "Gestao Interna",
             "as anotacoes da Gestao Interna",
             "uma anotacao nova na Gestao Interna",
             ("ver", "criar", "editar", "excluir", "exportar")),
    _Recurso("rm", SEC_TRABALHO, "Relatorio de Monitoramento",
             "os Relatorios de Monitoramento",
             "um Relatorio de Monitoramento novo",
             ("ver", "criar", "editar", "excluir", "exportar")),
    _Recurso("documentos", SEC_TRABALHO, "Geracao de Documentos",
             "os documentos gerados",
             "um documento novo",
             ("ver", "criar", "editar", "excluir", "exportar")),

    # --- Convenios e transferencias (ver / exportar / atualizar) ------------
    _Recurso("convenios", SEC_CONVENIOS, "SIGCON (convenios estaduais)",
             "os convenios estaduais", "", ("ver", "exportar", "atualizar"),
             fonte="no SIGCON-MG"),
    _Recurso("transferegov", SEC_CONVENIOS, "Transfere Gov",
             "as transferencias voluntarias federais", "",
             ("ver", "exportar", "atualizar"), fonte="no Transfere Gov"),
    _Recurso("cauc", SEC_CONVENIOS, "CAUC (regularidade federal)",
             "as pendencias de regularidade fiscal do municipio", "",
             ("ver", "exportar", "atualizar"), fonte="no CAUC/STN"),
    _Recurso("sismob", SEC_CONVENIOS, "Obras da Saude (SISMOB)",
             "as obras de saude do SISMOB", "",
             ("ver", "exportar", "atualizar"), fonte="no SISMOB"),
    _Recurso("acordofes", SEC_CONVENIOS, "Acordo FES (divida da saude MG)",
             "os creditos e parcelas do Acordo FES", "",
             ("ver", "exportar", "atualizar"), fonte="na SES-MG"),

    # --- Consultas e fontes (ver / exportar) -------------------------------
    _Recurso("emendas", SEC_CONSULTAS, "Emendas Estaduais",
             "as emendas parlamentares estaduais", "", ("ver", "exportar")),
    _Recurso("fns", SEC_CONSULTAS, "Fundo Nacional de Saude",
             "as propostas do Fundo Nacional de Saude", "", ("ver", "exportar")),
    _Recurso("simec", SEC_CONSULTAS, "SIMEC - PAR (MEC)",
             "as liberacoes e dimensoes do PAR", "", ("ver", "exportar")),
    _Recurso("parlamentares", SEC_CONSULTAS, "Parlamentares",
             "a base de parlamentares e a atuacao deles no municipio", "",
             ("ver", "exportar")),
    _Recurso("dou", SEC_CONSULTAS, "Diario Oficial",
             "as publicacoes do Diario Oficial", "", ("ver", "exportar")),
    _Recurso("frescor", SEC_CONSULTAS, "Monitor de frescor dos dados",
             "ha quanto tempo cada fonte foi coletada", "", ("ver", "exportar")),

    # --- Cofre (CRUD; `revelar` e especial, mais abaixo) --------------------
    _Recurso("cofre", SEC_COFRE, "Cofre de senhas",
             "as credenciais guardadas no cofre",
             "uma credencial nova no cofre",
             ("ver", "criar", "editar", "excluir")),

    # --- Usuarios (CRUD; `conceder` e `resetar_senha` sao especiais) --------
    _Recurso("usuarios", SEC_USUARIOS, "Usuarios",
             "o cadastro de usuarios", "um usuario novo",
             ("ver", "criar", "editar", "excluir")),
)


def _gerar(recurso: _Recurso) -> list[Permissao]:
    saida = []
    for verbo in recurso.verbos:
        molde = _VERBOS[verbo]
        saida.append(Permissao(
            chave=f"{recurso.chave}.{verbo}",
            secao=recurso.secao,
            recurso=recurso.chave,
            recurso_rotulo=recurso.rotulo,
            verbo_rotulo=molde["rotulo"],
            descricao=molde["frase"].format(
                plural=recurso.plural, singular=recurso.singular,
                fonte=recurso.fonte),
            escrita=molde["escrita"],
        ))
    return saida


# ---------------------------------------------------------------------------
# As ESPECIAIS — as que nao cabem em `recurso.verbo`
# ---------------------------------------------------------------------------
# Cada uma existe porque separa dois poderes que o verbo generico juntaria. Sao
# as linhas mais importantes deste arquivo; a descricao de cada uma diz POR QUE
# ela e uma caixinha propria.
_ESPECIAIS: tuple = (
    Permissao(
        chave="gestao.anexo_baixar", secao=SEC_TRABALHO, recurso="gestao",
        recurso_rotulo="Gestao Interna", verbo_rotulo="Baixar anexos",
        descricao="Abrir e baixar os arquivos anexados as anotacoes. Separado "
                  "de «Ver» de proposito: a lista mostra que existe um anexo, "
                  "esta caixinha entrega o arquivo digitalizado — que pode ser "
                  "oficio, contrato ou documento pessoal.",
        escrita=False,
    ),
    Permissao(
        chave="cofre.revelar", secao=SEC_COFRE, recurso="cofre",
        recurso_rotulo="Cofre de senhas", verbo_rotulo="Revelar a senha",
        descricao="Exibir a senha em CLARO na tela. Ver que a credencial existe "
                  "nao e ver a credencial: «Ver» mostra o sistema, o usuario e "
                  "a senha mascarada; esta caixinha entrega a senha do portal "
                  "do governo. Toda revelacao vira linha na trilha de auditoria.",
        escrita=False,   # GET /api/cofre/{id}/reveal — o guard de leitura nao barra
    ),
    Permissao(
        chave="sessoes.ver", secao=SEC_COFRE, recurso="sessoes",
        recurso_rotulo="Sessoes gov.br", verbo_rotulo="Ver",
        descricao="Consultar o estado das sessoes capturadas dos portais "
                  "(valida, expirada, quando foi renovada).",
        escrita=False,
    ),
    Permissao(
        chave="sessoes.capturar", secao=SEC_COFRE, recurso="sessoes",
        recurso_rotulo="Sessoes gov.br", verbo_rotulo="Capturar sessao",
        descricao="Gravar uma sessao autenticada de portal do governo. O cookie "
                  "capturado vale como credencial viva enquanto nao expira.",
        escrita=True,
    ),
    Permissao(
        chave="usuarios.conceder", secao=SEC_USUARIOS, recurso="usuarios",
        recurso_rotulo="Usuarios", verbo_rotulo="Conceder permissoes",
        descricao="Marcar e desmarcar as permissoes de outras pessoas. Quem tem "
                  "esta caixinha decide o que a equipe faz no sistema — e so "
                  "consegue conceder o que ELE MESMO tem.",
        escrita=True,
    ),
    Permissao(
        chave="usuarios.resetar_senha", secao=SEC_USUARIOS, recurso="usuarios",
        recurso_rotulo="Usuarios", verbo_rotulo="Redefinir senha",
        descricao="Gerar uma senha temporaria para outra pessoa. Quem redefine "
                  "a senha de alguem consegue entrar como essa pessoa ate a "
                  "troca obrigatoria no primeiro acesso.",
        escrita=True,
    ),
    Permissao(
        chave="bi.ver", secao=SEC_BI, recurso="bi",
        recurso_rotulo="Painel de Indicadores", verbo_rotulo="Ver",
        descricao="Abrir o Painel de Indicadores e os dashboards.",
        escrita=False,
    ),
    Permissao(
        chave="bi.exportar", secao=SEC_BI, recurso="bi",
        recurso_rotulo="Painel de Indicadores", verbo_rotulo="Exportar",
        descricao="Baixar os indicadores em arquivo.",
        escrita=False,
    ),
    Permissao(
        chave="bi.tela", secao=SEC_BI, recurso="bi",
        recurso_rotulo="Painel de Indicadores", verbo_rotulo="Modo Tela (TV)",
        descricao="Configurar o Modo Tela — o painel em rodizio para a TV do "
                  "gabinete, com o filtro do proprio gestor.",
        # O guard de somente-leitura libera /api/bi/tela-filtros de proposito
        # (READONLY_WRITE_ALLOW): o prefeito filtra a propria TV sem deixar de
        # ser somente-leitura no resto do sistema.
        escrita=False,
    ),
    Permissao(
        chave="bi.link", secao=SEC_BI, recurso="bi",
        recurso_rotulo="Painel de Indicadores", verbo_rotulo="Gerar link publico",
        descricao="Publicar um endereco que abre o painel SEM LOGIN. Enquanto o "
                  "link viver, quem tiver o endereco ve os dados do municipio — "
                  "e esses links circulam por WhatsApp.",
        escrita=False,   # mesmo motivo de bi.tela: /api/bi/tela-links esta na allowlist
    ),
    Permissao(
        chave="ai.usar", secao=SEC_IA, recurso="ai",
        recurso_rotulo="IA PACTHA", verbo_rotulo="Usar",
        descricao="Conversar com a IA do PACTHA. Cada pergunta e uma chamada "
                  "paga a API do modelo, e a resposta enxerga os dados dos "
                  "municipios que a pessoa ja pode ver.",
        escrita=True,
    ),
    Permissao(
        chave="ai.exportar", secao=SEC_IA, recurso="ai",
        recurso_rotulo="IA PACTHA", verbo_rotulo="Exportar",
        descricao="Baixar em PDF uma conversa ou um relatorio gerado pela IA.",
        escrita=True,    # o endpoint e POST (leva o texto no corpo)
    ),
    Permissao(
        chave="telegram.vincular", secao=SEC_TELEGRAM, recurso="telegram",
        recurso_rotulo="Telegram", verbo_rotulo="Vincular o proprio celular",
        descricao="Gerar o codigo que liga o PROPRIO Telegram ao sistema, para "
                  "receber avisos.",
        escrita=True,
    ),
    Permissao(
        chave="telegram.administrar", secao=SEC_TELEGRAM, recurso="telegram",
        recurso_rotulo="Telegram", verbo_rotulo="Administrar a integracao",
        descricao="Configurar o webhook e mexer na integracao inteira, nao so "
                  "no proprio vinculo.",
        escrita=True,
    ),
    Permissao(
        chave="auditoria.ver", secao=SEC_AUDITORIA, recurso="auditoria",
        recurso_rotulo="Auditoria", verbo_rotulo="Ver",
        descricao="Abrir a trilha de atividades de TODO mundo — quem entrou, de "
                  "que IP, o que revelou e o que apagou.",
        escrita=False,
    ),
    Permissao(
        chave="auditoria.exportar", secao=SEC_AUDITORIA, recurso="auditoria",
        recurso_rotulo="Auditoria", verbo_rotulo="Exportar",
        descricao="Baixar a trilha em arquivo. Quem exporta leva consigo IP, "
                  "e-mail, historico e quem revelou qual senha — e dado pessoal "
                  "sob a LGPD, por isso e uma caixinha separada de «Ver».",
        escrita=False,
    ),
)


def _montar() -> dict:
    catalogo: dict[str, Permissao] = {}
    for recurso in _RECURSOS:
        for permissao in _gerar(recurso):
            catalogo[permissao.chave] = permissao
    for permissao in _ESPECIAIS:
        if permissao.chave in catalogo:      # rede contra colisao silenciosa
            raise RuntimeError(
                f"permissao {permissao.chave!r} declarada duas vezes no catalogo")
        catalogo[permissao.chave] = permissao
    return catalogo


CATALOGO: dict[str, Permissao] = _montar()

# Frozenset porque e comparado a cada requisicao e nao pode ser mutado por
# consumidor nenhum.
TODAS: frozenset = frozenset(CATALOGO)


# ---------------------------------------------------------------------------
# Quiosque — o que o link PUBLICO de TV pode
# ---------------------------------------------------------------------------
# A conta de quiosque e um `viewer` REAL criado em runtime por
# `routers/bi.py::_ensure_kiosk_user` quando alguem publica um link de TV. Ela
# passa por `get_current_user` como qualquer usuario e nao tem linha nenhuma em
# `user_permissoes` — ou seja, pelo caminho normal ela ficaria com ZERO
# permissao, e no dia em que os routers do BI declararem `bi.ver` toda TV de
# gabinete de Monte Siao apagaria junto.
#
# O conjunto abaixo e o que aquele link REALMENTE alcanca hoje, e nada alem: o
# guard de `services/auth.py::KIOSK_GET_PERMITIDOS` ja limita o quiosque a uma
# lista EXATA de GETs do painel. Aqui so estamos dizendo a mesma coisa na lingua
# das permissoes, para as duas travas concordarem em vez de brigarem.
PERMISSOES_QUIOSQUE: frozenset = frozenset({"bi.ver"})


# ---------------------------------------------------------------------------
# Normalizacao
# ---------------------------------------------------------------------------
def normalizar(chave) -> str:
    """Chave como o sistema a compara: sem espaco, minuscula. Nunca levanta —
    recebe o que vier do banco, do JSON e da tela."""
    return str(chave or "").strip().lower()


def existe(chave) -> bool:
    return normalizar(chave) in CATALOGO


def descrever(chave) -> Optional[Permissao]:
    return CATALOGO.get(normalizar(chave))


# ---------------------------------------------------------------------------
# ⭐ A FUNCAO PURA
# ---------------------------------------------------------------------------
def permissoes_efetivas(
    *,
    super_admin: bool = False,
    concedidas: Optional[Iterable[str]] = None,
    somente_leitura: bool = False,
    quiosque: bool = False,
    ativo: bool = True,
) -> frozenset:
    """O que este usuario pode, resolvido a partir de FATOS — sem banco, sem
    `Request`, sem `User`, sem import de outro modulo do app.

    Todo o RBAC de acao do PACTHA cabe nas cinco regras abaixo, e elas valem
    NESTA ORDEM. Ler a ordem e ler o sistema inteiro:

      1. CONTA DESATIVADA nao pode nada. Ela nem passa do login
         (`get_current_user` recusa `not user.active`); devolver permissao para
         ela so serviria para a tela desenhar um acesso que nao existe.

      2. QUIOSQUE vale o conjunto fixo `PERMISSOES_QUIOSQUE`, e vem ANTES do
         super-admin de proposito: o quiosque e um token de 365 dias que circula
         em WhatsApp, e nao pode herdar poder de ninguem por acidente.

      3. SUPER-ADMIN pode TUDO — a regra do dono, palavra por palavra: "esses
         tem tudo, fazem tudo no sistema... eles sao tipo ROOT". Nao olha
         `concedidas`: nao existe caixinha para marcar, e nao pode existir jeito
         de um administrador do cliente REVOGAR permissao do dono da plataforma.

      4. TODO O RESTO vale exatamente o que estiver marcado no usuario. Chave
         que nao existe no catalogo e DESCARTADA (typo, permissao removida numa
         versao futura, lixo de importacao) — o banco ja recusa gravar chave
         invalida, e aqui a segunda trava garante que nem um `concedidas` vindo
         de outro caminho consegue conceder o que nao existe.

         ⚠️ `concedidas=None` e VAZIO, e nao "sem limite". A convencao inversa
         (`allowed_telas = None` = admin) e a que criou o deus por default no
         Incremento 4; aqui None so pode significar "nao carreguei nada", e a
         resposta fail-closed para isso e "entao nao pode nada".

      5. SOMENTE-LEITURA subtrai as permissoes de escrita, DEPOIS de tudo —
         inclusive do super-admin. Nao e teimosia: o guard de somente-leitura
         mora em `get_current_user`, ACIMA de qualquer permissao, e barra o
         metodo HTTP antes de a checagem de permissao acontecer. Se esta funcao
         dissesse que um super-admin marcado somente-leitura pode `rm.excluir`,
         ela estaria mentindo sobre o comportamento do sistema — e a tela
         desenharia um botao que devolve 403. Ver `escrita` no cabecalho.

    Devolve um frozenset (o chamador nao consegue mutar a resposta por engano).
    """
    if not ativo:
        return frozenset()

    if quiosque:
        efetivas = PERMISSOES_QUIOSQUE
    elif super_admin:
        efetivas = TODAS
    else:
        efetivas = frozenset(
            chave for chave in (normalizar(c) for c in (concedidas or ()))
            if chave in CATALOGO
        )

    if somente_leitura:
        efetivas = frozenset(c for c in efetivas if not CATALOGO[c].escrita)

    return efetivas


# ---------------------------------------------------------------------------
# Apoio para a TELA (item G) e para o ANTI-ESCALONAMENTO (item F)
# ---------------------------------------------------------------------------
def por_secao(chaves: Optional[Iterable[str]] = None) -> list[dict]:
    """O catalogo agrupado como a tela desenha: secao -> recurso -> caixinhas.

    `chaves=None` devolve o catalogo inteiro; passando um conjunto, devolve so
    aquelas (e o que serve ao "resumo legivel do que a pessoa pode")."""
    permitidas = None if chaves is None else {normalizar(c) for c in chaves}
    saida = []
    for secao in SECOES:
        recursos: list[dict] = []
        indice: dict[str, dict] = {}
        for chave, permissao in CATALOGO.items():
            if permissao.secao != secao["chave"]:
                continue
            if permitidas is not None and chave not in permitidas:
                continue
            grupo = indice.get(permissao.recurso)
            if grupo is None:
                grupo = {"recurso": permissao.recurso,
                         "recurso_rotulo": permissao.recurso_rotulo,
                         "permissoes": []}
                indice[permissao.recurso] = grupo
                recursos.append(grupo)
            grupo["permissoes"].append(permissao.as_dict())
        if recursos:
            saida.append({**secao, "recursos": recursos})
    return saida


def catalogo_para_api() -> dict:
    """Payload que o frontend busca. NAO copiar esta lista para o JavaScript —
    ver a regra 1 no cabecalho."""
    return {
        "secoes": por_secao(),
        "permissoes": [CATALOGO[c].as_dict() for c in sorted(CATALOGO)],
        "total": len(CATALOGO),
    }


def resumo(chaves: Iterable[str]) -> list[str]:
    """Frases curtas do que a pessoa pode, para o administrador conferir sem ler
    75 caixinhas: uma linha por recurso, com os verbos que ela tem.

        ["Relatorio de Monitoramento: Ver, Editar, Exportar", ...]
    """
    tem = {normalizar(c) for c in chaves}
    linhas: list[str] = []
    vistos: dict[str, list[str]] = {}
    ordem: list[str] = []
    for chave, permissao in CATALOGO.items():
        if chave not in tem:
            continue
        if permissao.recurso not in vistos:
            vistos[permissao.recurso] = []
            ordem.append(permissao.recurso)
        vistos[permissao.recurso].append(permissao.verbo_rotulo)
    for recurso in ordem:
        rotulo = next(p.recurso_rotulo for p in CATALOGO.values()
                      if p.recurso == recurso)
        linhas.append(f"{rotulo}: {', '.join(vistos[recurso])}")
    return linhas
