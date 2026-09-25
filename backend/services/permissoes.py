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
import os
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
# SEC_TELEGRAM saiu em 05/09/2026 junto com o módulo (ver o bloco de permissões
# abaixo). A seção existia mesmo com o módulo desligado e deixava um cabeçalho
# sem nenhuma caixinha embaixo — era o que `test_toda_secao_tem_pelo_menos_uma_
# permissao` acusava em toda rodada da suíte.
SEC_AUDITORIA = "auditoria"

SECOES: list[dict] = [
    {"chave": SEC_TRABALHO, "rotulo": "Trabalho do dia a dia",
     "descricao": "O que a equipe produz dentro do sistema: anotações, "
                  "relatórios e documentos."},
    {"chave": SEC_CONVENIOS, "rotulo": "Convênios e transferências",
     "descricao": "As bases que o sistema coleta dos portais do governo. "
                  "«Atualizar dados» dispara uma coleta nova."},
    {"chave": SEC_CONSULTAS, "rotulo": "Consultas e fontes",
     "descricao": "Telas de consulta a bases externas. Só leitura e exportação."},
    {"chave": SEC_BI, "rotulo": "Painel de Indicadores (BI)",
     "descricao": "O painel do gestor, o Modo Tela da TV e o link público."},
    {"chave": SEC_IA, "rotulo": "Inteligência Artificial",
     "descricao": "A IA do PACTHA. Cada consulta é paga por chamada."},
    {"chave": SEC_COFRE, "rotulo": "Cofre de senhas e sessões",
     "descricao": "Credenciais de portais do governo. É a seção mais sensível "
                  "do sistema."},
    {"chave": SEC_USUARIOS, "rotulo": "Usuários e permissões",
     "descricao": "Quem pode cadastrar pessoas e decidir o que elas fazem."},
    {"chave": SEC_AUDITORIA, "rotulo": "Auditoria",
     "descricao": "A trilha de atividades. O arquivo exportado entrega IP, "
                  "e-mail e histórico de todo mundo."},
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
    # ⭐ A TELA DO MENU que este recurso governa — a chave de `user_telas`
    # (05/09/2026). E o que liga o catalogo de PERMISSAO ao MENU LATERAL, e por
    # isso e o campo que fechou o buraco mais antigo desta tela.
    #
    # Ate aqui `user_telas` e `user_permissoes` eram DUAS listas diferentes que
    # nao casavam: 4 recursos sem tela nenhuma, 1 tela sem recurso nenhum, e o
    # grupo FEDERAIS inteiro (7 telas) preso a uma chave so. O administrador
    # marcava «Transfere Gov» e concedia sete telas de uma vez sem saber.
    #
    # Agora a regra e 1:1 — cada folha do menu e um recurso, e o recurso diz
    # QUAL folha. A tela de Usuarios desenha a arvore percorrendo o menu e
    # casando por este campo (`frontend/src/lib/menu.ts`), e
    # `tests/test_arvore_segue_o_menu.py` quebra se um dos dois lados ganhar um
    # item que o outro nao tem.
    #
    # ⚠️ VAZIO = CAPACIDADE SEM TELA. Hoje so `transferegov.atualizar`: o botao
    # que dispara a coleta mora em Configuracoes › Sessoes, nao numa tela do
    # grupo FEDERAIS. A arvore desenha essas como linha SEM interruptor de
    # acesso — so a acao —, porque nao ha tela para ligar ou desligar.
    tela: str = ""
    # ⚠️ NAO e "o verbo parece de escrita". E: o guard de somente-leitura barra
    # esta acao? Ver o cabecalho do modulo.
    escrita: bool = False
    # ⭐ ABRANGENCIA POR UF (pedido do dono, 08/2026): em quais estados este
    # recurso existe de verdade. VAZIO = federal/nacional (aparece para todo
    # tenant). A tela de Usuarios usa isto para NAO oferecer módulo de outro
    # estado: no sistema de Santa Maria/RS nada de Minas Gerais aparece, e
    # vice-versa; a assessoria multi-estado ve um cartao por estado da carteira.
    #
    # ⚠️ ISTO NAO RESTRINGE DADO, E SO O CATALOGO. Quem separa o convenio do ES
    # do convenio de GO continua sendo a lista de MUNICIPIOS da pessoa
    # (`ensure_municipio_access`) — a mesma chave `convenios.ver` serve os dois
    # estados. Filtrar aqui evita oferecer ao administrador um modulo que
    # naquele tenant nunca teria dado nenhum; nao e uma segunda trava.
    #
    # ⚠️ As UFs daqui tem de bater com as da tela equivalente em
    # `frontend/src/lib/telas.ts` (que desenha os chips de tela) — o teste
    # `tests/test_catalogo_por_uf.py` quebra se divergirem.
    ufs: tuple = ()

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
            # Lista (e nao tuple): vai para JSON. Vazio = federal/nacional.
            "ufs": list(self.ufs),
            # A folha do menu que esta caixinha governa. Vazio = capacidade sem
            # tela (ver o campo `tela` acima).
            "tela": self.tela,
            # ⚠️ INERTE: a chave existe no catalogo mas NENHUMA rota a exige —
            # marcar nao abre nada porque nao ha porta. A arvore ESCONDE estas
            # (decisao do dono, 05/09/2026): caixinha que promete e nao entrega
            # e pior que caixinha faltando. Ver `PERMISSOES_INERTES`.
            "inerte": self.chave in PERMISSOES_INERTES,
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
        "frase": "Alterar {plural} que já existem, inclusive as de outras pessoas.",
        "escrita": True,
    },
    "excluir": {
        "rotulo": "Excluir",
        "frase": "Apagar {plural}. Não há desfazer.",
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
                 "situação e valores de dezenas de registros de uma vez, para "
                 "todo mundo — não só para quem clicou.",
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
    # UFs em que o recurso existe; vazio = federal/nacional. Ver `Permissao.ufs`.
    ufs: tuple = ()
    # A folha do menu que este recurso governa (chave de `user_telas`). Vazio =
    # capacidade sem tela. Ver `Permissao.tela`.
    tela: str = ""


# ⚠️ Recurso novo entra AQUI e em `migrations/add_permissoes_por_acao.sql` (a
# tabela-catalogo que serve de chave estrangeira). O teste
# `test_permissoes_catalogo.py::test_sql_semeia_exatamente_o_catalogo_do_python`
# quebra se os dois divergirem — de proposito: chave que existe so no Python nao
# pode ser gravada (a FK recusa), e chave que existe so no SQL e caixinha que
# nunca aparece na tela.
_RECURSOS: tuple = (
    # --- Trabalho do dia a dia (CRUD completo + exportar) -------------------
    _Recurso("gestao", SEC_TRABALHO, "Gestao Interna",
             "as anotações da Gestão Interna",
             "uma anotação nova na Gestão Interna",
             ("ver", "criar", "editar", "excluir", "exportar"),
             tela="gestao"),
    # AGENDAMENTOS — a agenda de trabalho da equipe. Sem `ufs`: é nacional, e
    # uma agenda não depende de que estado é o cliente.
    _Recurso("agendamentos", SEC_TRABALHO, "Agendamentos",
             "os agendamentos da equipe",
             "um agendamento novo",
             ("ver", "criar", "editar", "excluir", "exportar"),
             tela="agendamentos"),
    _Recurso("rm", SEC_TRABALHO, "Relatorio de Monitoramento",
             "os Relatórios de Monitoramento",
             "um Relatório de Monitoramento novo",
             ("ver", "criar", "editar", "excluir", "exportar"),
             tela="rm"),
    _Recurso("documentos", SEC_TRABALHO, "Geração de Documentos",
             "os documentos gerados",
             "um documento novo",
             ("ver", "criar", "editar", "excluir", "exportar"),
             tela="documentos"),

    # --- Convenios e transferencias (ver / exportar / atualizar) ------------
    # ⚠️ ufs = MG, ES — e ATE 05/09/2026 era (MG, ES, GO, RS), porque esta chave
    # governava o GRUPO ESTADUAIS INTEIRO: passavam por `convenios.ver` tambem
    # Repasses e Cofinanciamento (GO), Monitoramento e as quatro do RS. Cada uma
    # ganhou chave e tela proprias logo abaixo, e as UFs desceram com elas — e
    # por isso a lista daqui encolheu para onde ha convenio estadual DE VERDADE
    # (MG=SIGCON, ES=GConv/SEGER).
    #
    # ⚠️ TIRAR UMA UF DAQUI ESCONDE A CAIXINHA de um cliente que precisa dela.
    # A lista espelha `FONTE_CONVENIOS_ESTADUAIS` de
    # `frontend/src/lib/estadual.ts`, e `tests/test_catalogo_por_uf.py` quebra se
    # as duas divergirem.
    #
    # ⚠️ O ROTULO CONTINUA NEUTRO — nao diz "SIGCON", que e o nome do sistema de
    # MINAS. A mesma chave serve dois estados com portais de nomes diferentes
    # (MG=SIGCON, ES=Portal de Convenios/SEGER), e o
    # administrador de Santa Maria/RS lia "SIGCON" numa caixinha que no banco
    # dele so tem dado gaucho. E o mesmo defeito que `frontend/src/lib/
    # estadual.ts` existe para fechar (o sistema carimbava "CAGEC — Minas
    # Gerais" sobre cidade de Goias) e a mesma correcao que a tela `cauc` ja
    # tinha recebido ("Regularidade (federal e estadual)").
    #
    # ⚠️ `fonte` VAZIO pela mesma razao: ele so alimenta a frase de «Atualizar»
    # ("buscar dados novos {fonte}"), e ela dizia "no SIGCON-MG" em TODO tenant
    # — errado em tres dos quatro. Sem `fonte` a frase fica "buscar dados
    # novos", verdadeira em qualquer estado. Nomear o portal certo exigiria um
    # texto por UF, e o catalogo de permissoes nao sabe de que estado e a pessoa
    # que esta lendo — quem sabe disso e a TELA, que ja escreve a fonte no
    # cabecalho pelos mapas de `estadual.ts`.
    _Recurso("convenios", SEC_CONVENIOS, "Convênios Estaduais",
             "os convênios estaduais", "", ("ver", "exportar", "atualizar"),
             ufs=("MG", "ES", "PR", "TO"), tela="convenios"),

    # --- ESTADUAIS: as OUTRAS oito telas do grupo -------------------------
    # ⚠️⚠️ ELAS SAIRAM DE DENTRO DE `convenios` EM 05/09/2026, e a saida e o
    # ponto deste incremento. Ate aqui UMA chave (`convenios.ver`) abria as DEZ
    # telas do grupo ESTADUAIS — o administrador marcava «Convênios Estaduais» e
    # concedia, sem saber, Repasses, Cofinanciamento, Monitoramento e as cinco
    # do Rio Grande do Sul. A regra do dono agora e Modulo › Tela › Acao: «em
    # Federais posso liberar Em execução e não PAC».
    #
    # Aqui a divisao foi BARATA porque cada tela ja tinha router proprio
    # (`repasses.py`, `cofinanciamento.py`, `monitoramento.py`,
    # `consulta_popular.py`, `programas_rs.py`, `conteudo_rs.py`): so trocar o
    # `exige("convenios.ver")` pela chave da propria tela.
    #
    # ⚠️ AS UFs DESCEM COM ELAS, e por isso `convenios` encolheu de
    # (MG, ES, GO, RS) para (MG, ES): a lista antiga era a UNIAO do grupo
    # inteiro justamente porque a chave governava o grupo inteiro. Agora cada
    # tela carrega o proprio estado, e a de MG deixa de aparecer para o cliente
    # gaucho. As UFs espelham os mapas de `frontend/src/lib/estadual.ts` —
    # `tests/test_catalogo_por_uf.py` quebra se divergirem.
    #
    # ⚠️ SO `ver` NAS OITO: nenhuma delas tem rota de exportacao nem de coleta
    # sob demanda hoje. E a mesma regra do InvestSUS e do Obras.gov.br abaixo —
    # permissao que nao governa nada e pior que permissao faltando.
    _Recurso("repasses", SEC_CONVENIOS, "Repasses Estaduais",
             "os repasses estaduais recebidos pelo município", "",
             ("ver",), ufs=("GO",), tela="repasses"),
    _Recurso("cofinanciamento", SEC_CONVENIOS, "Cofinanciamento da Saúde",
             "os repasses do fundo estadual ao fundo municipal de saúde", "",
             ("ver",), ufs=("GO",), tela="cofinanciamento"),
    _Recurso("monitoramento", SEC_CONVENIOS, "Monitoramento de Convênios",
             "os registros mensais de execução dos convênios", "",
             ("ver",), ufs=("RS",), tela="monitoramento"),
    _Recurso("consulta_popular", SEC_CONVENIOS, "Consulta Popular",
             "as demandas aprovadas na Consulta Popular/COREDEs", "",
             ("ver",), ufs=("RS",), tela="consulta_popular"),
    _Recurso("programas_rs", SEC_CONVENIOS, "Programas do Estado",
             "as linhas de fomento do governo do estado", "",
             ("ver",), ufs=("RS",), tela="programas_rs"),
    _Recurso("funrigs", SEC_CONVENIOS, "Plano Rio Grande",
             "as linhas do fundo de reconstrução do estado", "",
             ("ver",), ufs=("RS",), tela="funrigs"),
    _Recurso("emendas_rs", SEC_CONVENIOS, "Emendas Estaduais RS",
             "as emendas parlamentares estaduais do Rio Grande do Sul", "",
             ("ver",), ufs=("RS",), tela="emendas_rs"),
    _Recurso("tce_rs", SEC_CONVENIOS, "TCE-RS",
             "as licitações, contratos e obras publicados pelo TCE-RS", "",
             ("ver",), ufs=("RS",), tela="tce_rs"),
    # TCE-PR (22/09/2026): o que o município declarou ao SIM-AM, pelo PIT —
    # convênios, obras, licitações, contratos e a despesa por fonte de recurso.
    # Só `ver`, pela regra das vizinhas: sem exportação nem coleta sob demanda.
    # As UFs espelham `TCE_ABERTO_POR_UF` de `frontend/src/lib/estadual.ts`.
    _Recurso("tce_pr", SEC_CONVENIOS, "TCE-PR",
             "os convênios, obras, contratos e a despesa por fonte publicados "
             "pelo TCE-PR", "",
             ("ver",), ufs=("PR",), tela="tce_pr"),

    # --- FEDERAIS: a COLETA, que nao e de tela nenhuma ---------------------
    # ⚠️ `tela` VAZIO de proposito, e este e o unico recurso assim no catalogo.
    # O botao que dispara a coleta do Transfere Gov mora em Configuracoes ›
    # Sessões (`frontend/.../sessoes/page.tsx`), e nao numa das oito telas do
    # grupo FEDERAIS — uma coleta so alimenta as oito de uma vez. Pendura-la
    # numa delas faria a arvore mentir sobre onde o botao esta; deixa-la sem
    # tela e a verdade, e a arvore desenha a linha sem interruptor de acesso.
    _Recurso("transferegov", SEC_CONVENIOS, "Transfere Gov (coleta)",
             "as transferências voluntárias federais", "",
             ("atualizar",), fonte="no Transfere Gov"),

    # --- FEDERAIS: as oito telas do grupo ----------------------------------
    # Mesma divisao das estaduais, e pelo mesmo pedido. Aqui ela custou mais:
    # quatro destas telas (Em execução, Voluntárias, Rejeitadas, Encerradas) sao
    # UM componente so (`components/TransfereGovPropostas.tsx`) batendo no mesmo
    # endpoint com a categoria em QUERY — e query e escolha do cliente, entao
    # gatear por ela nao seria trava. A categoria subiu para o CAMINHO
    # (`GET /api/transferegov/lista/{categoria}`) e o gate le o segmento; ver
    # `routers/transferegov.py`.
    _Recurso("transferegov_radar", SEC_CONVENIOS, "Radar de captação",
             "os programas federais com janela de proposta aberta", "",
             ("ver",), tela="transferegov_radar"),
    _Recurso("transferegov_geral", SEC_CONVENIOS, "Federais — Em execução",
             "os instrumentos federais já celebrados", "",
             ("ver", "exportar"), tela="transferegov_geral"),
    _Recurso("transferegov_especiais", SEC_CONVENIOS, "Federais — Especiais",
             "as transferências especiais e os planos de ação", "",
             ("ver", "exportar"), tela="transferegov_especiais"),
    _Recurso("transferegov_pac", SEC_CONVENIOS, "Federais — PAC (Novo PAC)",
             "os empreendimentos do Novo PAC no município", "",
             ("ver",), tela="transferegov_pac"),
    _Recurso("transferegov_voluntarias", SEC_CONVENIOS, "Federais — Voluntárias",
             "as propostas voluntárias federais", "",
             ("ver", "exportar"), tela="transferegov_voluntarias"),
    _Recurso("transferegov_rejeitadas", SEC_CONVENIOS, "Federais — Rejeitadas",
             "as propostas federais rejeitadas", "",
             ("ver", "exportar"), tela="transferegov_rejeitadas"),
    _Recurso("transferegov_encerradas", SEC_CONVENIOS, "Federais — Encerradas",
             "os instrumentos federais encerrados", "",
             ("ver", "exportar"), tela="transferegov_encerradas"),
    _Recurso("transferegov_cnpj", SEC_CONVENIOS, "Federais — CNPJ",
             "as propostas federais por CNPJ do proponente", "",
             ("ver",), tela="transferegov_cnpj"),
    # ⭐ EMENDAS FEDERAIS (06/09/2026) — a carteira de emenda parlamentar federal
    # do municipio e a execucao dela pela CGU. Nenhuma tela mostrava isso: a
    # emenda federal aparecia so como Transferencia Especial em «Especiais» e
    # como selo `TE` na lista de Convenios, e por um caminho que perdia 45% dela
    # (as que nunca viraram proposta). Ver ingestion/portal_transparencia.py.
    #
    # ⚠️ SO `ver`, pela mesma razao escrita acima para as oito estaduais e para o
    # InvestSUS: nao ha rota de exportacao nem de coleta sob demanda para
    # `exportar`/`atualizar` governarem. Permissao que nao governa nada e pior
    # que permissao faltando — e a saida "por na lista das inertes" so esconderia
    # a caixinha do administrador. `exportar` entra no MESMO PR que criar
    # `GET /api/export-pdf/emendas-federais`.
    #
    # ⚠️ SEM `ufs`: a fonte e FEDERAL. A chave da CGU estar ligada em dois dos
    # cinco tenants e OUTRA COISA — `ufs` diz onde a fonte EXISTE, e ela existe
    # em todo lugar. Quem conta a verdade sobre a chave e o payload da rota
    # (`fonte_ligada`), nao o catalogo de permissoes: marcar a tela como
    # estadual faria o administrador de Santa Maria nao conseguir liberar uma
    # tela que ele passa a ver no dia em que a chave for ligada.
    _Recurso("emendas_federais", SEC_CONVENIOS, "Federais — Emendas parlamentares",
             "as emendas parlamentares federais destinadas ao município", "",
             ("ver",), tela="emendas_federais"),

    _Recurso("cauc", SEC_CONVENIOS, "CAUC (regularidade federal)",
             "as pendências de regularidade fiscal do município", "",
             ("ver", "exportar", "atualizar"), fonte="no CAUC/STN",
             tela="cauc"),
    _Recurso("sismob", SEC_CONVENIOS, "Obras da Saúde (SISMOB)",
             "as obras de saúde do SISMOB", "",
             ("ver", "exportar", "atualizar"), fonte="no SISMOB",
             tela="sismob"),
    # Obras federais de TODAS as áreas (CIPI/Obras.gov.br) — mobilidade,
    # saneamento, habitação, segurança e a reconstrução da Defesa Civil, que
    # nenhuma outra tela mostrava.
    #
    # ⚠️ SÓ `ver`, e é a mesma razão escrita no InvestSUS logo abaixo: não há
    # rota de exportação nem de coleta sob demanda, e permissão que não governa
    # nada é pior que permissão faltando — aparece na tela de concessão, alguém
    # marca, e fica achando que concedeu algo. As duas entram no dia em que os
    # endpoints que elas protegeriam existirem.
    _Recurso("obrasgov", SEC_CONVENIOS, "Obras Federais (Obras.gov.br)",
             "as obras federais do município no Obras.gov.br", "",
             ("ver",), fonte="no Obras.gov.br", tela="obrasgov"),
    # A Gestão de Parcerias do Transferegov (07/09/2026): o módulo onde as
    # transferências passaram a ser processadas de 2024 em diante, e onde mora
    # a emenda de saúde. Só `ver` — não há exportação nem coleta sob demanda,
    # e permissão que não governa nada é pior que permissão faltando.
    _Recurso("parcerias", SEC_CONVENIOS, "Parcerias (emendas de saúde)",
             "as propostas e emendas do módulo de Parcerias", "",
             ("ver",), fonte="no Transferegov", tela="parcerias"),
    # O plano de ação Fundo a Fundo (07/09/2026). ⚠️ Não é o repasse — esse é
    # o `fns`. Aqui está o que o justifica, e a decomposição que diz quanto
    # daquele dinheiro veio de emenda. Só `ver`, pelo mesmo critério.
    _Recurso("faf_planos", SEC_CONVENIOS, "Planos de Ação (Fundo a Fundo)",
             "os planos de ação e a origem do repasse fundo a fundo", "",
             ("ver",), fonte="no Transferegov", tela="faf_planos"),
    # CGU (23/09/2026): os convênios federais que o TransfereGov NÃO tem — as
    # transferências legais da Defesa Civil e o histórico anterior a 2009 —, pela
    # planilha do Portal da Transparência. Só `ver`, pelo critério das vizinhas.
    _Recurso("cgu_convenios", SEC_CONVENIOS, "Defesa Civil e outros repasses (CGU)",
             "os repasses federais publicados pela CGU que o TransfereGov não tem", "",
             ("ver",), fonte="no Portal da Transparência", tela="cgu_convenios"),
    # Recursos recebidos por pasta (24/09/2026): todo repasse da União ao
    # município e aos fundos dele, mês a mês (FPM, FUNDEB, fundo a fundo, FNDE,
    # FNAS...), pelo arquivo de transferências da CGU. Só `ver`.
    _Recurso("cgu_transferencias", SEC_CONVENIOS, "Recursos recebidos por pasta",
             "os repasses federais recebidos pelo município, por pasta", "",
             ("ver",), fonte="no Portal da Transparência", tela="cgu_transferencias"),
    _Recurso("acordofes", SEC_CONVENIOS, "Acordo FES (dívida da saúde MG)",
             "os créditos e parcelas do Acordo FES", "",
             ("ver", "exportar", "atualizar"), fonte="na SES-MG",
             ufs=("MG",), tela="acordofes"),

    # --- Consultas e fontes (ver / exportar) -------------------------------
    # ⚠️ ufs = MG: a fonte de emendas estaduais coletada hoje e a do SIGCON-MG
    # (impositivas). Quando entrar coletor de outro estado, a UF entra aqui —
    # ver `FONTE_EMENDAS_ESTADUAIS` em `frontend/src/lib/estadual.ts`.
    _Recurso("emendas", SEC_CONSULTAS, "Emendas Estaduais",
             "as emendas parlamentares estaduais", "", ("ver", "exportar"),
             ufs=("MG",), tela="emendas"),
    _Recurso("fns", SEC_CONSULTAS, "Fundo Nacional de Saúde",
             "as propostas do Fundo Nacional de Saúde", "", ("ver", "exportar"),
             tela="fns"),
    # InvestSUS: os repasses fundo a fundo do FNS, por bloco e por competência.
    # ⚠️ SÓ `ver`, de propósito. A primeira versão declarava `exportar` e
    # `atualizar` também — e o `test_registro_rotas` reprovou, com razão: não há
    # rota que as exija, porque a fonte é fechada e o coletor ainda não existe.
    # Permissão que não governa nada é pior que permissão faltando: aparece na
    # tela de concessão, alguém marca, e fica achando que concedeu algo. As duas
    # entram junto com o coletor e com os endpoints que elas de fato protegem.
    _Recurso("investsus", SEC_CONSULTAS, "InvestSUS",
             "os repasses federais de saúde no InvestSUS", "",
             ("ver",), fonte="no InvestSUS/FNS", tela="investsus"),
    _Recurso("simec", SEC_CONSULTAS, "SIMEC - PAR (MEC)",
             "as liberações e dimensões do PAR", "", ("ver", "exportar"),
             tela="simec"),
    _Recurso("parlamentares", SEC_CONSULTAS, "Parlamentares",
             "a base de parlamentares e a atuação deles no município", "",
             ("ver", "exportar"), tela="parlamentares"),
    # ⭐ CONSOLIDADO (18/09/2026) — a carteira inteira do cliente, lado a lado,
    # para as perguntas que atravessam municípios ("onde o deputado X mandou
    # dinheiro para os nossos clientes"). Reverte a decisão de 05/08 SÓ nesta
    # forma: área própria, com número sempre quebrado por município; o seletor
    # de município continua sem "todos". Cada usuário vê os seus municípios
    # (`services/bi.resolve_scope`), nunca o tenant.
    _Recurso("consolidado", SEC_CONSULTAS, "Consolidado da carteira",
             "os dados de todos os municípios da carteira, lado a lado", "",
             ("ver", "exportar"), tela="consolidado"),
    # ⚠️ «PAINEIS MUNICIPAIS» NAO ENTRA AQUI, e a ausencia e deliberada — foi
    # tentada e desfeita em 05/09/2026. Ela e a unica tela do menu sem chave de
    # ACAO, e a primeira versao deste incremento lhe deu uma (`paineis.ver`) so
    # para fechar a simetria. `test_registro_rotas` reprovou, com razao: a tela e
    # um mural de paineis oficiais em iframe (Painel Municipalista e Estrutura
    # SUAS) e nao tem endpoint proprio nenhum — a chave nao governaria nada, que
    # e exatamente o defeito que `PERMISSOES_INERTES` documenta.
    #
    # Quem a governa e a TELA `paineis` em `user_telas`, e isso basta: a arvore
    # da tela de Usuarios desenha o interruptor de acesso mesmo sem acoes
    # embaixo (o mesmo desenho de «Modo Tela (TV)»). A chave entra no dia em que
    # existir um endpoint que ela proteja.
    # ⭐ Diario Oficial e FEDERAL desde 22/09/2026: a aba do DOU (atos coletados
    # por `ingestion/dou_federal.py`) vale para todo municipio, de qualquer UF.
    # O diario ESTADUAL continua sendo a SEGUNDA aba, so onde ha provedor
    # (`DIARIO_POR_UF` em `frontend/src/lib/estadual.ts`, routers `dou_*`). Ate
    # aqui a caixinha tinha `ufs=` e sumia no PR — onde agora ha o que conceder.
    _Recurso("dou", SEC_CONSULTAS, "Diário Oficial",
             "as publicações do Diário Oficial", "", ("ver", "exportar"),
             tela="dou"),
    _Recurso("frescor", SEC_CONSULTAS, "Status dos Dados",
             "há quanto tempo cada fonte foi coletada", "", ("ver", "exportar"),
             tela="frescor"),

    # --- Cofre (CRUD; `revelar` e especial, mais abaixo) --------------------
    _Recurso("cofre", SEC_COFRE, "Cofre de senhas",
             "as credenciais guardadas no cofre",
             "uma credencial nova no cofre",
             ("ver", "criar", "editar", "excluir"), tela="cofre"),

    # --- Usuarios (CRUD; `conceder` e `resetar_senha` sao especiais) --------
    # ⭐ GANHOU TELA em 05/09/2026, e a mudanca tem consequencia: ate aqui a aba
    # Usuarios era governada pelo PAPEL (`routers/users.py::_require_admin`), e
    # so por ele. O docstring daquela funcao ja previa a troca — "trocar isto por
    # permissao individual e o Incremento 5" — e o incremento aconteceu: toda
    # rota de `users.py` declara `exige("usuarios.<acao>")`. Com `AUTHZ_MODO` em
    # `bloqueio`, essas chaves passam a barrar de verdade, e o gate por papel
    # virou uma segunda regra que CONTRADIZ a primeira: o dono marca a aba para
    # o controlador interno e o papel o expulsa mesmo assim.
    #
    # ⚠️ A migration `add_permissoes_por_tela.sql` GARANTE `usuarios.*` a todo
    # `role='admin'` ativo. Sem isso, um administrador sem a caixinha marcada se
    # trancaria fora da unica tela que conserta o problema.
    _Recurso("usuarios", SEC_USUARIOS, "Usuários",
             "o cadastro de usuários", "um usuário novo",
             ("ver", "criar", "editar", "excluir"), tela="usuarios"),
    # PARAMETROS — a aba que cadastra as listas do cliente (hoje os perfis).
    # ⚠️ Ate 05/09/2026 ela pegava carona em `usuarios.ver`/`usuarios.editar`
    # (ver `routers/parametros.py`): quem podia editar PESSOAS podia editar as
    # LISTAS, e nao havia como separar. Sao duas responsabilidades diferentes —
    # e a regra do dono e que cada aba de Configuracoes se libera sozinha.
    _Recurso("parametros", SEC_USUARIOS, "Parâmetros",
             "as listas de cadastro do cliente", "",
             ("ver", "editar"), tela="parametros"),
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
            # ⚠️ O `.replace` fecha o buraco que um `fonte` VAZIO deixa, e
            # ele passou a existir de verdade quando Convenios Estaduais deixou
            # de nomear o portal de um estado so: sem isto a frase saia como
            # "buscar dados novos ." — espaco solto antes do ponto, na tela de
            # permissao que o cliente le.
            descricao=molde["frase"].format(
                plural=recurso.plural, singular=recurso.singular,
                fonte=recurso.fonte).replace("  ", " ").replace(" .", "."),
            escrita=molde["escrita"],
            ufs=recurso.ufs,
            tela=recurso.tela,
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
        chave="agendamentos.anexo_baixar", secao=SEC_TRABALHO, tela="agendamentos",
        recurso="agendamentos", recurso_rotulo="Agendamentos",
        verbo_rotulo="Baixar anexos",
        descricao="Abrir e baixar os arquivos anexados aos agendamentos. "
                  "Separado de «Ver» pela mesma razão da Gestão Interna: a "
                  "lista mostra QUE existe um anexo, esta caixinha entrega o "
                  "arquivo — que pode ser ofício, contrato ou foto de vistoria.",
        escrita=False,
    ),
    Permissao(
        chave="gestao.anexo_baixar", secao=SEC_TRABALHO, recurso="gestao",
        tela="gestao",
        recurso_rotulo="Gestao Interna", verbo_rotulo="Baixar anexos",
        descricao="Abrir e baixar os arquivos anexados as anotações. Separado "
                  "de «Ver» de propósito: a lista mostra que existe um anexo, "
                  "esta caixinha entrega o arquivo digitalizado — que pode ser "
                  "ofício, contrato ou documento pessoal.",
        escrita=False,
    ),
    Permissao(
        chave="cofre.revelar", secao=SEC_COFRE, recurso="cofre", tela="cofre",
        recurso_rotulo="Cofre de senhas", verbo_rotulo="Revelar a senha",
        descricao="Exibir a senha em CLARO na tela. Ver que a credencial existe "
                  "não é ver a credencial: «Ver» mostra o sistema, o usuário e "
                  "a senha mascarada; esta caixinha entrega a senha do portal "
                  "do governo. Toda revelação vira linha na trilha de auditoria.",
        escrita=False,   # GET /api/cofre/{id}/reveal — o guard de leitura nao barra
    ),
    Permissao(
        chave="sessoes.ver", secao=SEC_COFRE, recurso="sessoes", tela="sessoes",
        recurso_rotulo="Sessões gov.br", verbo_rotulo="Ver",
        descricao="Consultar o estado das sessões capturadas dos portais "
                  "(válida, expirada, quando foi renovada).",
        escrita=False,
    ),
    Permissao(
        chave="sessoes.capturar", secao=SEC_COFRE, recurso="sessoes", tela="sessoes",
        recurso_rotulo="Sessões gov.br", verbo_rotulo="Capturar sessão",
        descricao="Gravar uma sessão autenticada de portal do governo. O cookie "
                  "capturado vale como credencial viva enquanto não expira.",
        escrita=True,
    ),
    Permissao(
        chave="usuarios.conceder", secao=SEC_USUARIOS, recurso="usuarios",
        tela="usuarios",
        recurso_rotulo="Usuários", verbo_rotulo="Conceder permissões",
        descricao="Marcar e desmarcar as permissões de outras pessoas. Quem tem "
                  "esta caixinha decide o que a equipe faz no sistema — e só "
                  "consegue conceder o que ELE MESMO tem.",
        escrita=True,
    ),
    # ⚠️ `usuarios.modelos` SAIU em 05/09/2026, junto com o subsistema inteiro de
    # MODELOS DE PERMISSAO (decisao do dono: "nao quero modelos ou molde de
    # permissoes, prefiro mais ainda a forma de criar na mao um a um"). No lugar
    # do molde ficou o que ele pediu: COPIAR as permissoes de outro usuario ja
    # cadastrado, agora tambem no momento da criacao — ver
    # `routers/users.py::copiar_permissoes` e o modal de Usuarios.
    #
    # ⚠️ As linhas `usuarios.modelos` ja gravadas em `permissoes_catalogo` nos
    # cinco bancos NAO foram apagadas — mesma receita do Telegram (ver o bloco
    # mais abaixo): `user_permissoes.permissao` referencia essa tabela com
    # ON DELETE RESTRICT, e chave no banco sem par no Python e so uma caixinha
    # que nunca aparece na tela. Inerte, e nao buraco.
    Permissao(
        chave="usuarios.resetar_senha", secao=SEC_USUARIOS, recurso="usuarios",
        tela="usuarios",
        recurso_rotulo="Usuários", verbo_rotulo="Redefinir senha",
        descricao="Gerar uma senha temporária para outra pessoa. Quem redefine "
                  "a senha de alguém consegue entrar como essa pessoa até a "
                  "troca obrigatória no primeiro acesso.",
        escrita=True,
    ),
    Permissao(
        chave="bi.ver", secao=SEC_BI, recurso="bi", tela="bi",
        recurso_rotulo="Painel de Indicadores", verbo_rotulo="Ver",
        descricao="Abrir o Painel de Indicadores e os dashboards.",
        escrita=False,
    ),
    Permissao(
        chave="bi.exportar", secao=SEC_BI, recurso="bi", tela="bi",
        recurso_rotulo="Painel de Indicadores", verbo_rotulo="Exportar",
        descricao="Baixar os indicadores em arquivo.",
        escrita=False,
    ),
    Permissao(
        chave="bi.tela", secao=SEC_BI, recurso="bi", tela="bi_tela",
        recurso_rotulo="Painel de Indicadores", verbo_rotulo="Modo Tela (TV)",
        descricao="Configurar o Modo Tela — o painel em rodízio para a TV do "
                  "gabinete, com o filtro do próprio gestor.",
        # O guard de somente-leitura libera /api/bi/tela-filtros de proposito
        # (READONLY_WRITE_ALLOW): o prefeito filtra a propria TV sem deixar de
        # ser somente-leitura no resto do sistema.
        escrita=False,
    ),
    Permissao(
        chave="bi.link", secao=SEC_BI, recurso="bi", tela="bi_link",
        recurso_rotulo="Painel de Indicadores", verbo_rotulo="Gerar link público",
        descricao="Publicar um endereço que abre o painel SEM LOGIN. Enquanto o "
                  "link viver, quem tiver o endereço vê os dados do município — "
                  "e esses links circulam por WhatsApp.",
        escrita=False,   # mesmo motivo de bi.tela: /api/bi/tela-links esta na allowlist
    ),
    # ⭐ VIGÊNCIAS A VENCER — caixinha PROPRIA, e nao parte de `convenios`,
    # porque o botao mora no Painel de Indicadores e o pedido do dono e liberar
    # SO o monitoramento de vencimentos para certas pessoas, sem entregar o
    # modulo inteiro de Convênios Estaduais. O endpoint /api/convenios/alertas
    # aceita convenios.ver OU vigencias.ver — quem ja tem Convênios continua
    # vendo, nada muda para ele (ver routers/convenios.py). Federal: o alerta
    # existe em qualquer tenant que tenha instrumento com vigencia.
    Permissao(
        chave="vigencias.ver", secao=SEC_BI, recurso="vigencias", tela="bi",
        recurso_rotulo="Vigências a vencer", verbo_rotulo="Ver",
        descricao="Abrir o botão «Vigências ≤120d» do Painel de Indicadores e "
                  "consultar os instrumentos com vigência encerrando nos "
                  "próximos 120 dias. Quem já tem Convênios Estaduais já vê "
                  "isto — esta caixinha libera o botão sem entregar o módulo "
                  "inteiro.",
        escrita=False,
    ),
    # ⭐ EXPORTAR é caixinha SEPARADA de Ver, aqui pelo mesmo motivo de todo o
    # resto do catálogo: baixar não é ler. O arquivo sai da plataforma e deixa de
    # estar sob controle dela — é o argumento que `routers/export_pdf.py` já
    # documenta no topo, e o motivo de todo endpoint daquele router gravar linha
    # na trilha.
    #
    # ⚠️ NINGUÉM PERDE NADA AO SUBIR ISTO. O endpoint aceita `vigencias.exportar`
    # OU `convenios.exportar` (ver routers/export_pdf.py::export_vigencias): quem
    # já exporta Convênios Estaduais continua exportando. E com `AUTHZ_MODO=aviso`
    # (o default) a chave nem barra — durante a semana de observação ela só
    # registra na trilha quem teria sido negado, que é para isso que o modo
    # existe.
    Permissao(
        chave="vigencias.exportar", secao=SEC_BI, recurso="vigencias", tela="bi",
        recurso_rotulo="Vigências a vencer", verbo_rotulo="Exportar",
        descricao="Baixar em PDF ou Excel a lista de instrumentos com vigência "
                  "encerrando, com o totalizador por município. Quem já exporta "
                  "Convênios Estaduais já pode isto.",
        escrita=False,
    ),
    Permissao(
        chave="ai.usar", secao=SEC_IA, recurso="ai", tela="ai",
        recurso_rotulo="IA PACTHA", verbo_rotulo="Usar",
        descricao="Conversar com a IA do PACTHA. Cada pergunta é uma chamada "
                  "paga a API do modelo, e a resposta enxerga os dados dos "
                  "municípios que a pessoa já pode ver.",
        escrita=True,
    ),
    Permissao(
        chave="ai.exportar", secao=SEC_IA, recurso="ai", tela="ai",
        recurso_rotulo="IA PACTHA", verbo_rotulo="Exportar",
        descricao="Baixar em PDF uma conversa ou um relatório gerado pela IA.",
        escrita=True,    # o endpoint e POST (leva o texto no corpo)
    ),
    # TELEGRAM REMOVIDO em 05/09/2026 (decisão do dono). Estava desativado desde
    # 09/08/2026 atrás de `TELEGRAM_MODULE`, e a flag nunca foi ligada em tenant
    # nenhum — as duas chaves eram catálogo condicional que só existia em
    # ambiente de teste. O canal de avisos será WhatsApp com a API oficial da
    # Meta; quando existir, nasce com chaves próprias e não como herança desta.
    # ⚠️ As linhas `telegram.*` já gravadas em `permissoes_catalogo` nos cinco
    # bancos NÃO foram apagadas: `user_permissoes.permissao` referencia essa
    # tabela com ON DELETE RESTRICT, e chave no banco sem par no Python é só uma
    # caixinha que nunca aparece na tela — inerte. Apagar exigiria varrer
    # concessões e modelos em cinco bancos para ganhar nada.
    Permissao(
        chave="auditoria.ver", secao=SEC_AUDITORIA, recurso="auditoria",
        tela="auditoria",
        recurso_rotulo="Auditoria", verbo_rotulo="Ver",
        descricao="Abrir a trilha de atividades de TODO mundo — quem entrou, de "
                  "que IP, o que revelou e o que apagou.",
        escrita=False,
    ),
    Permissao(
        # ⭐ TELA PROPRIA desde 05/09/2026. A aba Telemetria declarava
        # `tela: "auditoria"` em `lib/configuracoes.ts` — a chave de OUTRA coisa
        # —, entao liberar a trilha de auditoria liberava junto o horario de
        # trabalho de todo mundo. A propria descricao abaixo ja dizia que sao
        # coisas diferentes e que por isso a caixinha «nasce desmarcada»; faltava
        # a tela acompanhar a caixinha.
        chave="uso.ver", secao=SEC_AUDITORIA, recurso="uso", tela="telemetria",
        recurso_rotulo="Telemetria", verbo_rotulo="Ver",
        descricao="Abrir a Telemetria: quais telas cada pessoa abriu, quanto "
                  "tempo ficou em cada uma e quem está online agora. É DIFERENTE "
                  "da Auditoria — a trilha guarda ato consequente e serve de "
                  "prova; a telemetria guarda navegação e serve para entender o "
                  "uso do sistema. Mostra o horário de trabalho de gente da "
                  "prefeitura, por isso é caixinha própria e nasce desmarcada.",
        escrita=False,
    ),
    Permissao(
        chave="auditoria.exportar", secao=SEC_AUDITORIA, recurso="auditoria",
        tela="auditoria",
        recurso_rotulo="Auditoria", verbo_rotulo="Exportar",
        descricao="Baixar a trilha em arquivo. Quem exporta leva consigo IP, "
                  "e-mail, histórico e quem revelou qual senha — é dado pessoal "
                  "sob a LGPD, por isso é uma caixinha separada de «Ver».",
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
# ⚠️ AS INERTES — caixinha que existe e nao abre porta nenhuma
# ---------------------------------------------------------------------------
# Cada uma esta aqui pelo mesmo motivo: o endpoint correspondente NAO EXISTE.
# Nao ha exportacao nestes modulos, e uma permissao que rota nenhuma consulta e
# uma promessa vazia na tela — o administrador marca, salva, e nada muda.
#
# ⭐ A DECISAO DO DONO (05/09/2026) foi ESCONDE-LAS DA ARVORE, e nao apaga-las:
# apagar exigiria varrer concessoes em cinco bancos para ganhar nada (a FK de
# `user_permissoes` e ON DELETE RESTRICT), e no dia em que a rota nascer a
# caixinha volta a aparecer com as concessoes antigas intactas.
#
# ⚠️ `bi.tela` e de outra especie: o Modo Tela e controlado pela TELA `bi_tela`
# (`user_telas`), nao por esta chave. Ver a nota de `/api/bi/tela-filtros` na
# allowlist de `registro_rotas` — declara-la ali apagaria a TV do gabinete.
#
# ⚠️ A LISTA E ESCRITA, E NAO CALCULADA, e o valor dela e exatamente a
# diferenca: foi assim que `sessoes.capturar` apareceu um dia — orfa no catalogo
# enquanto a rota que devia cobra-la estava livre por allowlist. Uma lista
# derivada teria escondido o defeito em vez de acusa-lo.
#
# Ela morava em `tests/test_registro_rotas.py`; subiu para ca em 05/09/2026
# porque agora o CATALOGO precisa dela (`Permissao.as_dict` marca `inerte`, e a
# arvore da tela de Usuarios filtra por esse campo). O teste continua sendo o
# guarda: ele importa esta lista e reprova se ela ficar mentirosa nos dois
# sentidos — chave inerte que ganhou rota, e chave sem rota fora da lista.
PERMISSOES_INERTES: frozenset = frozenset({
    "acordofes.exportar", "bi.exportar", "bi.tela", "cauc.exportar",
    "fns.exportar", "frescor.exportar", "gestao.exportar", "simec.exportar",
    "sismob.exportar",
})

# Rede contra typo: chave inerte que nao existe no catalogo esconderia nada e
# ninguem notaria.
_fantasmas = PERMISSOES_INERTES - TODAS
if _fantasmas:
    raise RuntimeError(
        f"PERMISSOES_INERTES cita chave que nao existe no catalogo: "
        f"{sorted(_fantasmas)}")
del _fantasmas


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
     "descricao": "Pode alterar e apagar qualquer registro do município, "
                  "inclusive os que outras pessoas criaram."},
    {"valor": ESCOPO_PROPRIOS, "rotulo": "Somente os que ele criou",
     "descricao": "Só altera e apaga o que ele mesmo cadastrou. Continua VENDO "
                  "a lista inteira do município — o alcance vale só para "
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
# routers/documentos.py, routers/gestao.py, routers/agendamentos.py).
#
# ⚠️ `agendamentos` ENTROU EM 02/09/2026 e a distincao importa: a tabela tem
# DUAS colunas de pessoa. `responsavel_id` e quem VAI FAZER — campo de negocio,
# escolhido no formulario, e que muda quando o trabalho passa para outro. Quem
# governa o alcance e `criado_por`, que e quem REGISTROU e nao muda nunca.
# Apontar o alcance para o responsavel faria a pessoa perder o direito de editar
# o proprio registro no instante em que repassasse a tarefa.
ESCOPO_RECURSOS: dict = {
    r.recurso: r for r in (
        RecursoEscopavel("gestao", "gestao_anotacoes", "criado_por"),
        RecursoEscopavel("agendamentos", "agendamentos", "criado_por"),
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
# ⭐ A FUNCAO PURA
# ---------------------------------------------------------------------------
def permissoes_efetivas(
    *,
    super_admin: bool = False,
    concedidas: Optional[Iterable[str]] = None,
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

    ⚠️ HAVIA UMA QUINTA REGRA — «somente-leitura subtrai as permissoes de
    escrita» — e ela SAIU em 05/09/2026 junto com o interruptor que a alimentava
    (decisao do dono: "essa opçao somente leitura tb pode tirar isso, pq era
    para o prefeito, nao precisa, prefiro dar permissao de visualizaçao separada
    pra cada menu ou modulo dai eu permito so visualizar sem editar nada").

    O que ela fazia agora se faz DESMARCANDO as caixinhas de escrita daquele
    modulo — que e mais fino, porque a trava antiga era tudo-ou-nada sobre a
    conta inteira. ⚠️ E so passou a valer de verdade no mesmo deploy, quando
    `AUTHZ_MODO` deixou de ser `aviso`: enquanto o modo era de aviso, quem
    impedia a escrita era exatamente aquele interruptor, e nao estas caixinhas.

    Devolve um frozenset (o chamador nao consegue mutar a resposta por engano).
    """
    if not ativo:
        return frozenset()

    if quiosque:
        return PERMISSOES_QUIOSQUE
    if super_admin:
        return TODAS
    return frozenset(
        chave for chave in (normalizar(c) for c in (concedidas or ()))
        if chave in CATALOGO
    )


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
                         # A folha do MENU que este recurso governa. E por aqui
                         # que a arvore da tela de Usuarios casa catalogo com
                         # menu lateral. Vazio = capacidade sem tela.
                         "tela": permissao.tela,
                         # A ABRANGENCIA POR UF vive no GRUPO porque e do
                         # RECURSO, e nao de cada verbo: a tela agrupa por
                         # recurso e e ali que ela decide mostrar ou esconder.
                         # Vazio = federal/nacional. Ver `Permissao.ufs`.
                         "ufs": list(permissao.ufs),
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
        # ⚠️ `modelos` SAIU daqui em 05/09/2026 — ver a nota em `usuarios.modelos`,
        # acima. O frontend nao le mais nada sobre moldes porque nao ha moldes.
        # As chaves INERTES viajam para a tela poder esconde-las: sem a lista, o
        # JavaScript teria de manter uma copia dela, e copia de lista de
        # permissao e a cicatriz que o cabecalho deste arquivo descreve.
        "inertes": sorted(PERMISSOES_INERTES),
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
