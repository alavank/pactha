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
        chave="usuarios.modelos", secao=SEC_USUARIOS, recurso="usuarios",
        recurso_rotulo="Usuarios", verbo_rotulo="Gerenciar modelos",
        descricao="Criar, alterar e apagar os MODELOS de permissao — os moldes "
                  "que preenchem as caixinhas de uma vez. Separada de «Conceder "
                  "permissoes» de proposito: quem concede decide o que UMA "
                  "pessoa faz; quem escreve um molde escreve a RECEITA que os "
                  "outros administradores vao aplicar, e um molde chamado "
                  "«Somente consulta» que carregue «Revelar a senha» engana "
                  "quem confia no nome. Aplicar um molde NAO precisa desta "
                  "caixinha (basta «Conceder permissoes»), e continua limitado "
                  "ao que quem aplica ja tem.",
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
# ⭐ ALCANCE (escopo de linha) — "todos os registros" x "so os que ele criou"
# ---------------------------------------------------------------------------
# A regra do dono, palavra por palavra:
#
#     "Escopo (Editar somente os dele): e uma regra de nivel de linha. O sistema
#      valida se o ID do usuario logado e o mesmo criador do registro. Se for,
#      ele deixa editar; se nao for, o botao some ou fica bloqueado. (...) isso
#      aconteceria POR MODULO — algum usuario pode ter acesso de editar em um
#      modulo mas em outro ele so pode ver."
#
# E a decisao dele sobre o alcance, ja tomada: **o escopo vale SO PARA
# ESCRITA** (editar e excluir). A pessoa continua VENDO a lista inteira do
# municipio. Filtrar tambem a LEITURA foi recusado, e o motivo e operacional:
# dois servidores do mesmo setor deixariam de ver o trabalho um do outro, e o
# registro de quem saiu da prefeitura sumiria da tela.
#
# ⚠️ POR QUE ISTO NAO E UMA PERMISSAO NOVA DO CATALOGO. `gestao.editar` responde
# "esta pessoa edita anotacao?"; o alcance responde "QUAIS anotacoes". Sao duas
# perguntas, e juntar as duas numa caixinha (`gestao.editar_proprios`) dobraria o
# catalogo, faria a tela ter duas caixinhas que se contradizem quando as duas
# forem marcadas, e obrigaria o backfill a adivinhar qual delas dar a quem hoje
# edita. O alcance e um MODIFICADOR das caixinhas de escrita de um recurso.
ESCOPO_TODOS = "todos"          # o default — NAO restringe ninguem
ESCOPO_PROPRIOS = "proprios"    # so as linhas em que ele e o criador

ESCOPOS: tuple = (ESCOPO_TODOS, ESCOPO_PROPRIOS)

# Texto da tela. Fica aqui pelo mesmo motivo do resto do catalogo: o frontend
# nao copia lista nenhuma, busca por `GET /api/permissoes/catalogo`.
ESCOPO_OPCOES: tuple = (
    {"valor": ESCOPO_TODOS, "rotulo": "Todos os registros",
     "descricao": "Pode alterar e apagar qualquer registro do municipio, "
                  "inclusive os que outras pessoas criaram."},
    {"valor": ESCOPO_PROPRIOS, "rotulo": "Somente os que ele criou",
     "descricao": "So altera e apaga o que ele mesmo cadastrou. Continua VENDO "
                  "a lista inteira do municipio — o alcance vale so para "
                  "escrita."},
)

# Os VERBOS que o alcance modifica. `ver` e `exportar` ficam de fora por decisao
# do dono (ver acima); `criar` fica de fora porque nao ha linha anterior de quem
# julgar o dono — o registro nasce dele.
VERBOS_ESCOPAVEIS: tuple = ("editar", "excluir")


@dataclass(frozen=True)
class RecursoEscopavel:
    """Um modulo que aceita alcance, e ONDE mora o criador da linha.

    ⚠️ `tabela` e `coluna_dono` viram literal de SQL em
    `services/authz.py::exigir_dono_da_linha`. Ficam aqui, e nao espalhados pelos
    routers, porque uma copia divergente do nome da tabela e uma checagem que
    deixa de checar sem ninguem notar — e porque este mapa e o que a migration
    semeia e o teste confere."""

    recurso: str
    tabela: str
    coluna_dono: str


# ⚠️ RECURSO SO ENTRA AQUI SE A TABELA DELE TIVER A COLUNA DE CRIADOR. Sem ela,
# TODA linha seria "sem criador conhecido" e o alcance viraria uma opcao na tela
# que nao faz nada — falha silenciosa de permissao, que e o defeito que este
# subsistema inteiro existe para nao ter. Os tres abaixo sao os unicos modulos
# com CRUD de verdade E com `criado_por` gravado no INSERT (routers/rm.py,
# routers/documentos.py, routers/gestao.py).
ESCOPO_RECURSOS: dict = {
    r.recurso: r for r in (
        RecursoEscopavel("gestao", "gestao_anotacoes", "criado_por"),
        RecursoEscopavel("rm", "rm_relatorios", "criado_por"),
        RecursoEscopavel("documentos", "documentos_gerados", "criado_por"),
    )
}


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


def normalizar_escopo(valor) -> str:
    """O alcance como o sistema o compara. ⚠️ VALOR DESCONHECIDO VIRA `todos`.

    Fail-OPEN, e e a mesma escolha (e o mesmo motivo) de
    `services/authz.py::modo`: "fechar por engano" aqui e tirar de alguem a
    edicao que ele sempre teve, por causa de um valor torto no banco ou de um
    campo que chegou vazio do JSON. Restringir e ato DELIBERADO do administrador
    — nunca efeito colateral de dado sujo. A gravacao e outra historia: la o
    valor invalido e RECUSADO com 400 (ver routers/permissoes.py::_validar_escopos)
    e pela restricao CHECK da tabela, entao lixo nao entra por esta porta."""
    bruto = str(valor or "").strip().lower()
    return bruto if bruto in ESCOPOS else ESCOPO_TODOS


def escopavel(recurso) -> bool:
    """Este modulo aceita alcance por linha?"""
    return normalizar(recurso) in ESCOPO_RECURSOS


def descrever_recurso_escopavel(recurso) -> Optional[RecursoEscopavel]:
    return ESCOPO_RECURSOS.get(normalizar(recurso))


def permissoes_escopadas(recurso) -> tuple:
    """As chaves de escrita que o alcance daquele modulo modifica.

    E o que a TELA precisa para saber quando desenhar a escolha de alcance: a
    regra do dono e que ela "so aparece se ele tiver editar OU excluir naquele
    modulo — sem isso a escolha nao significa nada e vira ruido"."""
    chave_recurso = normalizar(recurso)
    if chave_recurso not in ESCOPO_RECURSOS:
        return ()
    return tuple(
        f"{chave_recurso}.{verbo}" for verbo in VERBOS_ESCOPAVEIS
        if f"{chave_recurso}.{verbo}" in CATALOGO
    )


def escopos_para_api() -> dict:
    """O vocabulario do alcance, para o frontend nao reescrever nenhuma parte
    dele. Vai dentro de `catalogo_para_api`."""
    return {
        "default": ESCOPO_TODOS,
        "opcoes": [dict(o) for o in ESCOPO_OPCOES],
        "verbos": list(VERBOS_ESCOPAVEIS),
        "recursos": {
            chave: {
                "recurso": chave,
                "recurso_rotulo": next(
                    (p.recurso_rotulo for p in CATALOGO.values()
                     if p.recurso == chave), chave),
                "permissoes": list(permissoes_escopadas(chave)),
            }
            for chave in ESCOPO_RECURSOS
        },
    }


# ---------------------------------------------------------------------------
# ⭐⭐ MODELO DE PERMISSAO (Incremento 7) — o MOLDE, e por que ele nao e grupo
# ---------------------------------------------------------------------------
# O problema que o molde resolve e de OPERACAO, e nao de seguranca: o catalogo
# tem dezenas de caixinhas, e cadastrar um servidor novo virou marcar todas elas
# a mao. Um administrador cansado marca TUDO — e ai o RBAC por usuario, que e a
# regra do dono, vira decoracao na pratica. Sem esta peca, a anterior se desfaz
# sozinha.
#
# ⚠️⚠️ E A SOLUCAO NAO PODE TRAIR A REGRA. A regra do dono, palavra por palavra:
#
#     "as permissoes sao colocadas no usuario da pessoa, INDIVIDUALMENTE. Grupo
#      e so ROTULO. Nao da pra limitar dentro de uma prefeitura que todos os
#      analistas terao o mesmo acesso, isso e besteira."
#
# Entao o molde NAO E HERANCA e NAO E "grupo com permissoes". E COPIA: aplicar
# um modelo preenche as caixinhas DAQUELE usuario NAQUELE instante, e acabou o
# vinculo. Depois disso o modelo pode mudar, ser renomeado ou ser APAGADO que o
# usuario nao muda em nada.
#
# A diferenca nao e filosofica, e a unica coisa que mantem o sistema
# respondivel: com heranca, "o que esta pessoa pode?" deixaria de ter resposta
# olhando a pessoa — seria preciso saber a que grupo ela pertence, o que aquele
# grupo tem HOJE, e o que ele tinha quando alguem reclamou. Com copia, a
# resposta continua sendo as caixinhas marcadas no cadastro dela, que e
# exatamente o que o administrador ve na tela.
#
# CONSEQUENCIA PRATICA, e ela precisa estar escrita em algum lugar: editar um
# molde NAO corrige ninguem. Se um molde saiu errado e ja foi aplicado a cinco
# pessoas, sao cinco cadastros a corrigir. E o preco da regra do dono, e ele e
# menor do que o preco de nao conseguir responder quem pode o que.
MODO_SUBSTITUIR = "substituir"
MODO_SOMAR = "somar"

MODOS_APLICACAO: tuple = (MODO_SUBSTITUIR, MODO_SOMAR)

# ⚠️ O DEFAULT E `substituir`, E A ESCOLHA E DELIBERADA — pense em quem clica no
# molde por engano num usuario JA configurado:
#
#   SOMAR por engano CONCEDE em silencio. As caixinhas que ja estavam marcadas
#   continuam marcadas, as do molde aparecem marcadas junto, e nada na tela
#   distingue uma da outra. O administrador salva sem perceber que acabou de dar
#   acesso a mais — e desfazer exige saber o que havia antes, que ninguem
#   guardou. E a direcao que ABRE o sistema.
#
#   SUBSTITUIR por engano TIRA — e isso e VISIVEL. Caixinha marcada desmarca na
#   frente do administrador, e nada foi gravado ainda: Cancelar desfaz tudo. O
#   erro aparece no exato instante em que acontece, que e a unica hora em que
#   ele custa barato.
#
# E ha a razao de significado: so em `substituir` o nome do molde diz a verdade.
# Aplicar «Somente consulta» somando a quem operava o Cofre produz uma pessoa
# que nao e nem uma coisa nem outra, e ninguem consegue mais dizer o que ela e
# olhando o molde. `somar` continua existindo porque "acrescentar o Cofre ao que
# ela ja tem" e pedido real, e proibi-lo empurraria o administrador de volta
# para as vinte caixinhas a mao — mas ele e ESCOLHA EXPLICITA, nunca o silencio.
# (Mesma regra do repo em `routers/users.py`: o campo omitido nao pode ser o
# campo mais permissivo.)
MODO_APLICACAO_OPCOES: tuple = (
    {"valor": MODO_SUBSTITUIR, "rotulo": "Substituir o que ela tem",
     "descricao": "As caixinhas passam a ser EXATAMENTE as do modelo. O que "
                  "estava marcado e nao esta no modelo e desmarcado — voce ve "
                  "isso acontecer antes de salvar."},
    {"valor": MODO_SOMAR, "rotulo": "Somar ao que ela ja tem",
     "descricao": "Acrescenta as caixinhas do modelo e nao desmarca nenhuma. O "
                  "alcance por modulo fica como esta. Use quando a pessoa "
                  "acumula duas funcoes."},
)


def normalizar_modo_aplicacao(valor) -> str:
    """O modo como o sistema o compara. Desconhecido cai em `substituir` — o
    modo que nao concede nada por acidente. Ver o comentario acima: aqui o
    fail-safe e o RESTRITIVO, ao contrario de `normalizar_escopo`, porque
    errar para o lado do `somar` seria conceder em silencio."""
    bruto = str(valor or "").strip().lower()
    return bruto if bruto in MODOS_APLICACAO else MODO_SUBSTITUIR


def aplicar_modelo(
    *,
    do_modelo: Optional[Iterable[str]] = None,
    do_alvo: Optional[Iterable[str]] = None,
    pode_conceder: Optional[Iterable[str]] = None,
    modo: str = MODO_SUBSTITUIR,
) -> dict:
    """⭐ O MOLDE aplicado a uma pessoa — PURO: sem banco, sem `Request`, sem
    `User`. Devolve o estado que as caixinhas devem mostrar, e nada e gravado.

    Os tres conjuntos de entrada:
        do_modelo      as chaves do molde
        do_alvo        as chaves que a pessoa TEM hoje
        pode_conceder  as chaves de quem esta aplicando (o efetivo dele)

    ⚠️ `pode_conceder` E O ANTI-ESCALONAMENTO, E ELE VALE AQUI TAMBEM. Um molde
    com `cofre.revelar` aplicado por quem NAO tem `cofre.revelar` nao pode dar
    essa chave — senao o molde viraria a porta dos fundos da trava que
    `routers/permissoes.py::_barrar_escalonamento` instalou na porta da frente.
    Duas travas dizendo a mesma coisa: esta, para a tela nunca PROPOR o que o
    servidor vai recusar; e a de la, que continua sendo a que decide na hora de
    gravar (uma tela adulterada nao contorna nada).

    ⚠️ E A TRAVA VALE NOS DOIS SENTIDOS. Em `substituir`, o que a pessoa tem
    FORA do alcance de quem aplica e PRESERVADO intocado — nao e "removido pelo
    molde". Sem isso, aplicar um molde seria o jeito de um administrador sem
    acesso ao Cofre desligar o acesso de quem tem, que e exatamente o que
    `_barrar_escalonamento` recusa quando a mesma coisa e feita caixinha a
    caixinha. (E, como efeito colateral util, e o que faz o PUT seguinte nunca
    esbarrar na trava por causa do molde.)

    Chave fora do catalogo e descartada em silencio, como na funcao pura de
    resolucao: molde antigo com chave que saiu do catalogo nao pode virar erro
    na cara do administrador.
    """
    modo_limpo = normalizar_modo_aplicacao(modo)

    molde = frozenset(c for c in (normalizar(x) for x in (do_modelo or ()))
                      if c in CATALOGO)
    atuais = frozenset(c for c in (normalizar(x) for x in (do_alvo or ()))
                       if c in CATALOGO)
    minhas = frozenset(c for c in (normalizar(x) for x in (pode_conceder or ()))
                       if c in CATALOGO)

    do_molde_permitido = molde & minhas
    # O que a pessoa tem e quem aplica NAO alcanca: fica como esta, nos dois
    # modos. E a metade "nao retirar" do anti-escalonamento.
    intocaveis = atuais - minhas

    if modo_limpo == MODO_SOMAR:
        resultado = atuais | do_molde_permitido
    else:
        resultado = do_molde_permitido | intocaveis

    return {
        "modo": modo_limpo,
        # ⭐ O que a tela deve MARCAR.
        "permissoes": sorted(resultado),
        "atuais": sorted(atuais),
        # O que o Salvar seguinte vai mudar, ja mastigado para a tela avisar
        # antes do clique.
        "vai_conceder": sorted(resultado - atuais),
        "vai_retirar": sorted(atuais - resultado),
        # ⚠️ Caixinha do MOLDE que nao entrou. Tem de aparecer na tela: um molde
        # aplicado pela metade em silencio faria o administrador jurar que
        # concedeu o que nao concedeu.
        "nao_aplicadas": sorted(molde - resultado),
        # Caixinha da PESSOA que ficou intocada por estar fora do alcance de
        # quem aplica. Nao e falha — e a trava funcionando —, mas quem aplicou
        # precisa saber que aquilo continua la.
        "preservadas": sorted(intocaveis),
    }


def aplicar_modelo_escopos(
    *,
    do_modelo: Optional[dict] = None,
    do_alvo: Optional[dict] = None,
    pode_definir: Optional[Iterable[str]] = None,
    modo: str = MODO_SUBSTITUIR,
) -> dict:
    """O ALCANCE por modulo que vem junto do molde. Puro, como o de cima.

    `pode_definir` sao os modulos em que QUEM APLICA alcanca todos os registros
    — os unicos em que ele pode mexer, pela mesma regra de
    `routers/permissoes.py::_barrar_escalonamento_escopo`.

    ⚠️ EM `somar` O ALCANCE NAO E TOCADO, e a decisao merece a frase: alcance e
    um RADIO ("todos" x "somente os que ele criou"), e nao existe soma de dois
    radios. Qualquer regra que inventassemos aqui ("o mais restritivo vence", "o
    do molde vence") seria uma regra que ninguem consegue prever olhando a tela.
    Somar acrescenta CAIXINHAS; o alcance fica exatamente como o administrador o
    deixou, e a tela diz isso.

    Devolve so o que RESTRINGE (`proprios`), que e a mesma convencao do banco e
    do resto do sistema: ausencia de linha e `todos`."""
    modo_limpo = normalizar_modo_aplicacao(modo)

    def _limpar(bruto) -> dict:
        if not isinstance(bruto, dict):
            return {}
        limpo = {}
        for recurso, valor in bruto.items():
            chave = normalizar(recurso)
            if not escopavel(chave):
                continue
            escopo = normalizar_escopo(valor)
            if escopo != ESCOPO_TODOS:
                limpo[chave] = escopo
        return limpo

    molde = _limpar(do_modelo)
    atuais = _limpar(do_alvo)
    meus = {normalizar(r) for r in (pode_definir or ()) if escopavel(normalizar(r))}

    if modo_limpo == MODO_SOMAR:
        resultado = dict(atuais)
        nao_aplicados = sorted(
            r for r in molde if molde[r] != atuais.get(r, ESCOPO_TODOS))
    else:
        resultado = {}
        nao_aplicados = []
        for recurso in ESCOPO_RECURSOS:
            desejado = molde.get(recurso, ESCOPO_TODOS)
            atual = atuais.get(recurso, ESCOPO_TODOS)
            # Modulo fora do alcance de quem aplica fica como esta — nem
            # apertando nem soltando. Ver `_barrar_escalonamento_escopo`.
            escolhido = desejado if recurso in meus else atual
            if escolhido != ESCOPO_TODOS:
                resultado[recurso] = escolhido
            if recurso not in meus and desejado != atual:
                nao_aplicados.append(recurso)

    return {
        "modo": modo_limpo,
        # So o que restringe — a mesma convencao do banco.
        "escopos": resultado,
        "atuais": dict(atuais),
        "nao_aplicados": sorted(nao_aplicados),
        "alterados": sorted(
            r for r in set(atuais) | set(resultado)
            if atuais.get(r, ESCOPO_TODOS) != resultado.get(r, ESCOPO_TODOS)),
    }


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
                         # O alcance por linha e um MODIFICADOR deste recurso, e
                         # nao uma caixinha: por isso viaja no grupo e nao na
                         # lista de permissoes. `escopo_permissoes` diz quais
                         # caixinhas ele modifica — a tela so desenha a escolha
                         # se alguma delas estiver marcada.
                         "escopavel": escopavel(permissao.recurso),
                         "escopo_permissoes": list(
                             permissoes_escopadas(permissao.recurso)),
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
        "escopos": escopos_para_api(),
        # O vocabulario do MOLDE (modos de aplicacao e o aviso obrigatorio). Vem
        # junto do catalogo pelo mesmo motivo do alcance: o frontend nao copia
        # texto nenhum deste subsistema.
        "modelos": modelos_para_api(),
    }


def modelos_para_api() -> dict:
    """O vocabulario do MOLDE, para o frontend nao reescrever nenhuma parte dele
    (regra 1 do cabecalho). Vai dentro de `catalogo_para_api`."""
    return {
        "default": MODO_SUBSTITUIR,
        "modos": [dict(m) for m in MODO_APLICACAO_OPCOES],
        # A frase que a tela e OBRIGADA a mostrar. Ela nao e enfeite: o dono
        # exigiu que "a tela DIGA" que aplicar e copiar, porque o administrador
        # que achar que e vinculo vai editar o molde esperando que a pessoa
        # mude junto — e ela nao muda.
        "aviso": ("Aplicar um modelo COPIA as permissoes para o cadastro desta "
                  "pessoa, agora. As caixinhas continuam editaveis e nada e "
                  "gravado ate voce salvar. Depois de salvo, mexer no modelo "
                  "NAO mexe mais nesta pessoa."),
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
