"""
Catálogo didático das ações de auditoria.

FONTE ÚNICA da tradução "chave técnica -> frase que um secretário entende".
Alimenta a lista, o modal, o filtro por módulo e o CSV/PDF exportado. NÃO é
copiado para o JavaScript: o frontend busca este catálogo por API (senão a chave
e o rótulo divergem em silêncio, exatamente o defeito que a auditoria existe
para não ter).

A frase é montada em três pedaços — `<ator> <fragmento> [<prep>] <alvo>`:

    frase_didatica("cofre.reveal", "Maria Silva", "gov.br")
    -> "Maria Silva revelou a senha de gov.br"

Por que `prep` é um campo separado: nem toda ação tem alvo (um `logout` não tem).
Se a preposição vivesse grudada no fragmento ("revelou a senha de"), a frase sem
alvo terminaria pendurada — "Maria Silva revelou a senha de".

REGRA DURA: ação desconhecida NUNCA engasga. Toda chave que não estiver na tabela
cai em `_derivar`, que produz módulo, risco e um rótulo legível a partir da
própria string. Auditoria que some por falta de rótulo é pior que auditoria feia.
Por isso também o risco derivado é `medio` por padrão (nunca `baixo`): ação nova
que ninguém classificou não pode nascer parecendo inofensiva.
"""
from dataclasses import dataclass, replace
from typing import Any, Optional

from services.telas_catalog import TELAS_CATALOG

# --- Risco ------------------------------------------------------------------
# Valores de fio (ASCII, sem acento) — vão para JSON, CSV e filtro de URL.
RISCO_ALTO = "alto"
RISCO_MEDIO = "medio"
RISCO_BAIXO = "baixo"
RISCOS = (RISCO_ALTO, RISCO_MEDIO, RISCO_BAIXO)

RISCO_ROTULOS = {
    RISCO_ALTO: "Alto",
    RISCO_MEDIO: "Médio",
    RISCO_BAIXO: "Baixo",
}

# Tom do <Selo> da identidade visual. Cor SÓ onde significa alerta: se "médio"
# pintasse de amarelo, a tela inteira ficaria amarela e ninguém mais enxergaria
# o que é grave. Só o risco alto ganha cor; os outros continuam texto.
RISCO_TOM = {
    RISCO_ALTO: "critico",
    RISCO_MEDIO: "neutro",
    RISCO_BAIXO: "neutro",
}

_ALTO, _MEDIO, _BAIXO = RISCO_ALTO, RISCO_MEDIO, RISCO_BAIXO

# --- Módulos ----------------------------------------------------------------
# São RÓTULOS de agrupamento da tela de auditoria, não as telas do RBAC. Ficam
# separados de propósito: o que a prefeitura pergunta numa auditoria é "o que a
# Alavank fez aqui dentro?", e essa pergunta só tem resposta se todo o canal
# `control.*` cair num módulo próprio — não diluído em Cofre/Usuários.
MOD_ACESSO = "Acesso"
MOD_USUARIOS = "Usuários e permissões"
MOD_COFRE = "Cofre de senhas"
MOD_SESSOES = "Sessões gov.br"
MOD_INTEGRACOES = "Integrações e tokens"
MOD_SUPORTE = "Suporte Alavank"
MOD_MUNICIPIOS = "Municípios"
MOD_DADOS = "Dados e coleta"
MOD_RELATORIOS = "Relatórios e exportações"
MOD_AUDITORIA = "Auditoria"
MOD_NAVEGACAO = "Navegação"
MOD_OUTROS = "Outros"

# Ordem do filtro: do que mais dói para o que menos dói.
MODULOS = [
    MOD_ACESSO,
    MOD_USUARIOS,
    MOD_COFRE,
    MOD_SESSOES,
    MOD_INTEGRACOES,
    MOD_SUPORTE,
    MOD_MUNICIPIOS,
    MOD_DADOS,
    MOD_RELATORIOS,
    MOD_AUDITORIA,
    MOD_NAVEGACAO,
    MOD_OUTROS,
]


@dataclass(frozen=True)
class Acao:
    """Uma linha do catálogo. Congelada porque é cacheada e devolvida a vários
    consumidores — se um deles mutasse, contaminaria os outros."""

    chave: str
    fragmento: str
    modulo: str
    risco: str
    prep: Optional[str] = None
    nota: Optional[str] = None
    # sem_alvo: a ação é sobre o PRÓPRIO ator (login, logout, troca da própria
    # senha). Sem isso a frase sairia "fulano@x tentou entrar ... fulano@x".
    sem_alvo: bool = False
    # conhecida=False -> veio de derivação. A tela mostra a chave crua junto,
    # para o auditor não achar que o sistema entendeu mais do que entendeu.
    conhecida: bool = True

    def as_dict(self) -> dict:
        return {
            "acao": self.chave,
            "fragmento": self.fragmento,
            "modulo": self.modulo,
            "risco": self.risco,
            "risco_rotulo": RISCO_ROTULOS.get(self.risco, self.risco),
            "risco_tom": RISCO_TOM.get(self.risco, "neutro"),
            "prep": self.prep,
            "nota": self.nota,
            "sem_alvo": self.sem_alvo,
            "conhecida": self.conhecida,
        }


def _a(fragmento: str, modulo: str, risco: str, *, prep: Optional[str] = None,
       nota: Optional[str] = None, sem_alvo: bool = False) -> dict:
    return {"fragmento": fragmento, "modulo": modulo, "risco": risco,
            "prep": prep, "nota": nota, "sem_alvo": sem_alvo}


# ---------------------------------------------------------------------------
# CHAVES REAIS — levantadas varrendo `log_event(...)` no repo (32 chamadas em 6
# arquivos). Não inventar: chave que ninguém grava vira filtro que nunca acha
# nada. As duas de `control.session_token.*` são montadas em runtime
# (routers/control.py, create vs rotate) — por isso não aparecem num grep ingênuo.
# ---------------------------------------------------------------------------
_TABELA: dict[str, dict] = {
    # --- Acesso (routers/auth.py) -----------------------------------------
    "login.success": _a("entrou no sistema", MOD_ACESSO, _MEDIO, sem_alvo=True),
    "sessao.encerrada": _a(
        "encerrou a sessão", MOD_ACESSO, _MEDIO, sem_alvo=True,
        nota="A PONTE ENTRE OS DOIS SISTEMAS. O «saiu do sistema» sempre foi uma "
             "linha seca; esta traz a DURAÇÃO junto — quanto tempo total, quanto "
             "ativo, quanto ocioso e quantos atos. Os números vêm da Telemetria, "
             "que sabe medir isso; o registro fica aqui, que é onde ele é "
             "imutável. Uma linha por sessão, nunca uma por batimento.",
    ),
    "login.fail": _a(
        "tentou entrar e a senha não conferiu", MOD_ACESSO, _MEDIO, sem_alvo=True,
        nota="Várias seguidas do mesmo e-mail ou do mesmo IP é o padrão de "
             "tentativa de invasão — vale filtrar por e-mail e por IP.",
    ),
    "login.disabled_user": _a(
        "tentou entrar com uma conta desativada", MOD_ACESSO, _MEDIO, sem_alvo=True,
        nota="A conta foi desligada mas alguém ainda tem a senha dela. "
             "Investigar se a credencial vazou no desligamento.",
    ),
    "logout": _a("saiu do sistema", MOD_ACESSO, _BAIXO, sem_alvo=True),
    "sso.login": _a(
        "entrou por acesso de suporte da Alavank", MOD_ACESSO, _ALTO, sem_alvo=True,
        nota="Sessão aberta por SSO técnico emitido pela Central. É um "
             "terceiro dentro do sistema da prefeitura: tem de bater com um "
             "chamado aberto.",
    ),
    "user.password_change.success": _a(
        "trocou a própria senha", MOD_ACESSO, _MEDIO, sem_alvo=True),
    "user.password_change.fail": _a(
        "errou a senha atual ao tentar trocar a própria senha", MOD_ACESSO,
        _MEDIO, sem_alvo=True),

    # --- Usuários e permissões (routers/users.py e auth.py::register) ------
    # Tudo alto: quem mexe em usuário mexe em PODER dentro do sistema, e é
    # exatamente a pergunta "quem deu essa permissão a essa pessoa, e quando".
    "user.create": _a("criou o usuário", MOD_USUARIOS, _ALTO),
    "user.update": _a(
        "alterou o cadastro e as permissões", MOD_USUARIOS, _ALTO, prep="de",
        nota="O detalhe traz o valor ANTES e DEPOIS de cada campo, inclusive "
             "telas e municípios liberados.",
    ),
    # Separada de `user.update` de propósito: aquela é "alterou o cadastro" e
    # vem junto com correção de nome e troca de rótulo. Esta é SÓ poder, e é a
    # que o auditor filtra quando a pergunta é "quem deixou fulano revelar
    # senha do gov.br, e quando".
    "usuarios.conceder": _a(
        "alterou as permissões", MOD_USUARIOS, _ALTO, prep="de",
        nota="O detalhe traz o que foi CONCEDIDO e o que foi RETIRADO, caixinha "
             "por caixinha, e o resumo do que a pessoa passou a poder. Quem "
             "concede só consegue conceder o que ele mesmo tem. Em linhas "
             "anteriores a 09/2026 o detalhe pode citar um MODELO de permissão "
             "— o subsistema foi removido, mas o registro do que aconteceu "
             "continua válido.",
    ),
    # --- Modelos de permissão — HISTÓRICO ----------------------------------
    # ⚠️ O SUBSISTEMA FOI REMOVIDO em 05/09/2026 (decisão do dono) e nenhuma
    # destas quatro ações é emitida por código nenhum hoje. Elas CONTINUAM aqui
    # porque a trilha é append-only: as linhas gravadas nos cinco bancos entre
    # 08/2026 e 09/2026 existem para sempre, e sem a tradução o auditor leria
    # `modelo_permissao.aplicar` cru numa tela que existe justamente para não
    # exigir isso dele. Traduzir o passado não ressuscita a funcionalidade.
    #
    # Alto nos quatro, e a razão continua válida para quem lê o histórico: um
    # modelo era uma RECEITA de permissão. Quem escrevia o molde influenciava o
    # que TODOS os outros administradores concediam — um molde chamado "Somente
    # consulta" que carregasse "Revelar a senha" enganava quem confiava no nome.
    "modelo_permissao.criar": _a(
        "criou o modelo de permissões", MOD_USUARIOS, _ALTO, prep="chamado",
        nota="Modelo é um MOLDE, não um grupo: ele não dá permissão a ninguém "
             "sozinho. O detalhe traz as caixinhas que ele carrega — vale "
             "conferir se o nome descreve honestamente o conteúdo.",
    ),
    "modelo_permissao.editar": _a(
        "alterou o modelo de permissões", MOD_USUARIOS, _ALTO, prep="chamado",
        nota="⚠️ Alterar o modelo NÃO altera ninguém que já o recebeu: aplicar "
             "um modelo COPIA as permissões para a pessoa naquele instante. "
             "Quem já foi configurado continua exatamente como estava — as "
             "correções valem só para as próximas aplicações.",
    ),
    "modelo_permissao.excluir": _a(
        "excluiu o modelo de permissões", MOD_USUARIOS, _ALTO, prep="chamado",
        nota="Ninguém perde acesso por isto. O modelo era só um molde; as "
             "permissões que ele copiou para as pessoas continuam nos "
             "cadastros delas. O detalhe guarda o conteúdo do modelo apagado.",
    ),
    # O alvo aqui é a PESSOA (é por ela que o auditor filtra); o nome do modelo
    # está no detalhe. Esta linha responde "onde este molde foi aplicado?" —
    # pergunta de revisão de acesso que a linha `usuarios.conceder` sozinha não
    # responde, porque lá o modelo é só uma nota do que mudou.
    "modelo_permissao.aplicar": _a(
        "aplicou um modelo de permissões ao cadastro", MOD_USUARIOS, _ALTO,
        prep="de",
        nota="Aplicar COPIA as caixinhas do modelo para a pessoa. O que ela "
             "passou a poder está na linha «alterou as permissões» do mesmo "
             "instante, com o valor antes e depois — esta linha diz qual "
             "modelo serviu de ponto de partida e em que modo (substituir ou "
             "somar). Depois de aplicado não sobra vínculo nenhum: mexer no "
             "modelo não mexe mais nesta pessoa.",
    ),
    "user.reset_password": _a(
        "gerou uma senha temporária", MOD_USUARIOS, _ALTO, prep="para",
        nota="Quem redefine a senha de outra pessoa consegue entrar como ela "
             "até a troca obrigatória no primeiro acesso.",
    ),

    # --- Cofre de senhas (routers/cofre.py) --------------------------------
    "cofre.reveal": _a(
        "revelou a senha", MOD_COFRE, _ALTO, prep="de",
        nota="Leitura de credencial em claro. É o evento mais sensível da "
             "trilha: a senha de um portal do governo foi exibida na tela.",
    ),
    "cofre.create": _a("cadastrou a senha", MOD_COFRE, _MEDIO, prep="de"),
    "cofre.update": _a("alterou a senha", MOD_COFRE, _MEDIO, prep="de"),
    "cofre.delete": _a("excluiu a senha", MOD_COFRE, _ALTO, prep="de"),

    # --- Sessões gov.br (routers/session_capture.py) -----------------------
    # Gravadas pela extensão de captura (service token), não por pessoa: o ator
    # costuma ser o token, e o `details.principal` diz qual.
    "session.create": _a(
        "capturou a sessão", MOD_SESSOES, _ALTO, prep="de",
        nota="Cookie de sessão autenticada de portal do governo guardado no "
             "cofre. Vale como credencial viva enquanto não expira.",
    ),
    "session.update": _a(
        "renovou a sessão capturada", MOD_SESSOES, _ALTO, prep="de"),
    "session.candidata": _a(
        "enviou uma sessão candidata", MOD_SESSOES, _MEDIO, prep="de",
        nota="A sessão gov.br em uso estava viva e NÃO foi substituída: a captura "
             "ficou guardada à parte, e o worker só a promove se ela autenticar. "
             "É a guarda contra o Chrome deslogado derrubar a sessão do servidor.",
    ),

    # --- Integrações e tokens (routers/service_tokens.py) ------------------
    "service_token.create": _a(
        "emitiu o token de integração", MOD_INTEGRACOES, _ALTO, prep="chamado",
        nota="Token de serviço é permissão de máquina: vale sem senha e sem "
             "expiração até ser revogado.",
    ),
    "service_token.rotate": _a(
        "rotacionou o token de integração", MOD_INTEGRACOES, _ALTO, prep="chamado"),
    "service_token.revoke": _a(
        "revogou o token de integração", MOD_INTEGRACOES, _ALTO, prep="chamado"),

    # --- Suporte Alavank: canal `control.*` (routers/control.py) -----------
    # O ator aqui é a Central (token de control), não um servidor da prefeitura.
    "control.municipio.upsert": _a(
        "cadastrou ou atualizou o município", MOD_SUPORTE, _MEDIO),
    "control.municipio.patch": _a("alterou o município", MOD_SUPORTE, _MEDIO),
    "control.refresh": _a(
        "disparou uma atualização de dados", MOD_SUPORTE, _BAIXO, prep="de"),
    "control.cofre.create": _a(
        "cadastrou a senha", MOD_SUPORTE, _MEDIO, prep="de"),
    "control.cofre.patch": _a("alterou a senha", MOD_SUPORTE, _MEDIO, prep="de"),
    "control.cofre.reveal": _a(
        "revelou a senha", MOD_SUPORTE, _ALTO, prep="de",
        nota="Senha do município exibida pela Central, fora do sistema da "
             "prefeitura. Tem de bater com um chamado aberto.",
    ),
    "control.cofre.delete": _a("excluiu a senha", MOD_SUPORTE, _ALTO, prep="de"),
    # sem_alvo: o token da extensão é único e já vem nomeado no fragmento —
    # repetir o `details.name` sairia "...da extensão de captura extensao-captura".
    "control.session_token.create": _a(
        "emitiu o token da extensão de captura", MOD_SUPORTE, _ALTO, sem_alvo=True),
    "control.session_token.rotate": _a(
        "rotacionou o token da extensão de captura", MOD_SUPORTE, _ALTO,
        sem_alvo=True),
    "control.sso.mint": _a(
        "abriu um acesso de suporte", MOD_SUPORTE, _ALTO, prep="para o técnico",
        nota="A Central emitiu um passe de entrada para um técnico da Alavank. "
             "O uso do passe aparece depois como 'sso.login'.",
    ),
    "control.user.create": _a("criou o usuário", MOD_SUPORTE, _ALTO),
    "control.user.patch": _a(
        "alterou o cadastro e as permissões", MOD_SUPORTE, _ALTO, prep="de"),
    "control.user.reset_password": _a(
        "gerou uma senha temporária", MOD_SUPORTE, _ALTO, prep="para"),
    "control.user.delete": _a("excluiu o usuário", MOD_SUPORTE, _ALTO),

    # ---------------------------------------------------------------------
    # CHAVES NOVAS deste incremento (peça de cobertura). Se a cobertura fechar
    # com nome diferente, é aqui que se corrige — e enquanto isso a derivação
    # segura a frase sem quebrar nada.
    # ---------------------------------------------------------------------
    "nav.view": _a(
        "acessou a tela", MOD_NAVEGACAO, _BAIXO,
        nota="Navegação é registrada de forma deduplicada: só ao trocar de "
             "tela ou após 5 minutos na mesma. Consulta individual não é "
             "registrada. Retenção de 12 meses.",
    ),
    # Travessão: o alvo de uma exportação é o nome do relatório, e nenhuma
    # preposição serve para tudo ("exportou em PDF de Convênios" mente).
    "export.pdf": _a("exportou em PDF", MOD_RELATORIOS, _MEDIO, prep="—"),
    "export.xlsx": _a("exportou em Excel", MOD_RELATORIOS, _MEDIO, prep="—"),
    "export.csv": _a("exportou em CSV", MOD_RELATORIOS, _MEDIO, prep="—"),
    "export.rm": _a("exportou o Relatório de Monitoramento", MOD_RELATORIOS,
                    _MEDIO, prep="—"),
    "export.documento": _a("exportou o documento", MOD_RELATORIOS, _MEDIO,
                           prep="—"),
    "export.gestao_anexo": _a(
        "baixou um anexo da gestão interna", MOD_RELATORIOS, _MEDIO, prep="—",
        nota="Anexo digitalizado saindo da plataforma. O detalhe guarda o nome "
             "do arquivo, o tipo e o tamanho.",
    ),
    # Um relatório por tipo (`export.<tipo>`, routers/export_pdf.py). Cadastrados
    # UM A UM em vez de deixados na derivação porque os oito `tipo=` são literais
    # no código: o auditor merece ler "exportou a lista de convênios", não
    # "exportou dados do sistema — plano_acao".
    # sem_alvo em todos: o `target_id` É o próprio tipo, que o fragmento já disse
    # — repetir sairia "exportou a lista de convênios — convenios".
    "export.convenios": _a("exportou a lista de convênios", MOD_RELATORIOS,
                           _MEDIO, sem_alvo=True),
    "export.voluntarias": _a("exportou a lista de transferências voluntárias",
                             MOD_RELATORIOS, _MEDIO, sem_alvo=True),
    "export.plano_acao": _a("exportou o plano de ação", MOD_RELATORIOS, _MEDIO,
                            sem_alvo=True),
    "export.emendas": _a("exportou a lista de emendas", MOD_RELATORIOS, _MEDIO,
                         sem_alvo=True),
    "export.dou": _a("exportou as publicações do Diário Oficial",
                     MOD_RELATORIOS, _MEDIO, sem_alvo=True),
    "export.parlamentares": _a("exportou a lista de parlamentares",
                               MOD_RELATORIOS, _MEDIO, sem_alvo=True),
    "export.ia_relatorio": _a("exportou um relatório gerado pela IA",
                              MOD_RELATORIOS, _MEDIO, sem_alvo=True),
    "export.ia": _a("exportou uma conversa com a IA", MOD_RELATORIOS, _MEDIO,
                    sem_alvo=True),

    # Geração de Documentos (routers/documentos.py).
    "documento.create": _a("gerou o documento", MOD_RELATORIOS, _MEDIO, prep="—"),
    "documento.update": _a("alterou o documento", MOD_RELATORIOS, _MEDIO, prep="—"),
    "documento.delete": _a("excluiu o documento", MOD_RELATORIOS, _ALTO, prep="—"),

    # Painel de Indicadores — link público da TV (routers/bi.py).
    # Cadastradas à mão porque a derivação MENTIA nas duas: prefixo "bi" +
    # sufixo "create" sai "criou um painel de indicadores" e risco médio. O ato
    # não cria painel nenhum — ABRE o painel do município para qualquer um que
    # tenha o endereço, sem login. Isso é publicação de dado, e é ALTO.
    "bi.tela_link.create": _a(
        "gerou um link público (sem login) do painel", MOD_RELATORIOS, _ALTO,
        prep="—",
        nota="Enquanto o link viver, quem tiver o endereço vê o painel sem "
             "senha. O detalhe guarda o caminho, o tipo e a data de expiração; "
             "o token NÃO é registrado, para a trilha não virar uma cópia da "
             "própria credencial.",
    ),
    "bi.tela_link.revoke": _a(
        "revogou o link público do painel", MOD_RELATORIOS, _MEDIO, prep="—",
        nota="Revogar derruba o link e o usuário de quiosque atrelado a ele."),

    # Gestão interna (routers/gestao.py). Módulo DADOS de propósito: é o mesmo
    # para onde `_PREFIXO_MODULO` manda o prefixo "gestao" — chave exata e
    # prefixo divergindo é o que faz o mesmo evento cair em dois filtros.
    "gestao.anotacao.create": _a("registrou a anotação", MOD_DADOS, _MEDIO,
                                 prep="—"),
    "gestao.anotacao.update": _a("alterou a anotação", MOD_DADOS, _MEDIO,
                                 prep="—"),
    "gestao.anotacao.delete": _a("excluiu a anotação", MOD_DADOS, _ALTO,
                                 prep="—"),

    # Coleta de dados sob demanda (routers/convenios.py).
    "coletor.disparo": _a(
        "mandou atualizar os dados", MOD_DADOS, _MEDIO, prep="de",
        nota="Uma coleta muda situação e valores de dezenas de convênios de uma "
             "vez. O pedido fica registrado inclusive quando NÃO entra na fila "
             "(já havia coleta rodando) — 'quem mandou atualizar antes do "
             "número mudar' é a pergunta que este evento responde.",
    ),

    # Relatório de Monitoramento (routers/rm.py).
    "rm.update": _a("editou o Relatório de Monitoramento", MOD_RELATORIOS,
                    _MEDIO, prep="—"),
    "rm.auto_popular": _a(
        "repopulou o Relatório de Monitoramento", MOD_RELATORIOS, _MEDIO, prep="—",
        nota="Repopular DESCARTA a redação manual do relatório e põe os dados "
             "atuais no lugar. É o evento que responde 'quem apagou o que eu "
             "tinha escrito'.",
    ),
    "rm.delete": _a("excluiu o Relatório de Monitoramento", MOD_RELATORIOS,
                    _ALTO, prep="—"),
    "rm.config_rodape": _a(
        "alterou o rodapé padrão dos Relatórios de Monitoramento",
        MOD_RELATORIOS, _MEDIO, sem_alvo=True,
        nota="O rodapé sai impresso no pé de TODA página de TODO relatório do "
             "cliente — é o endereço de quem assina o documento oficial. Não é "
             "por relatório: vale para os próximos que forem gerados. O "
             "valor-antes/valor-depois traz também de ONDE vinha o texto "
             "(`env` = variável de ambiente, `salvo` = editado pela tela).",
    ),
    # Ação PRÓPRIA, e não uma nota dentro de `rm.config_rodape`: os dois campos
    # são salvos pela mesma tela mas dizem coisas diferentes, e "quem trocou o
    # contato do papel timbrado" é a pergunta que aparece depois de um relatório
    # sair com o e-mail de outra assessoria. Junto no mesmo evento, um filtro por
    # "rodapé" traria trocas de e-mail e vice-versa.
    "rm.config_email": _a(
        "alterou o e-mail padrão do cabeçalho dos Relatórios de Monitoramento",
        MOD_RELATORIOS, _MEDIO, sem_alvo=True,
        nota="O e-mail sai impresso no cabeçalho de TODA página de TODO "
             "relatório do cliente, ao lado do logo — é o contato para quem "
             "recebe o documento responder. Não é por relatório: vale para os "
             "próximos que forem gerados. O valor-antes/valor-depois traz também "
             "de ONDE vinha o texto (`env` = variável de ambiente, `salvo` = "
             "editado pela tela).",
    ),
    # --- Trava de permissão em modo aviso (services/authz.py) --------------
    # Módulo "Usuários e permissões" porque é ali que está a CORREÇÃO: cada uma
    # destas linhas é um cadastro para arrumar antes de ligar o bloqueio.
    #
    # Risco médio nas duas, deliberadamente. Alto encheria o filtro de "alto"
    # com o trabalho de uma semana inteira e afogaria o que é de fato grave —
    # e `authz.negaria` nem é um incidente: é o sistema avisando com
    # antecedência o que vai barrar quando a trava for ligada.
    "authz.negaria": _a(
        "entrou onde ainda não tem permissão", MOD_USUARIOS, _MEDIO, prep="—",
        nota="A trava de permissão está em MODO AVISO (AUTHZ_MODO=aviso): o "
             "acesso FOI PERMITIDO e apenas registrado. Cada linha destas é um "
             "cadastro a conferir — ou a pessoa precisa da permissão e alguém "
             "tem de concedê-la, ou não precisa e o acesso vai parar sozinho "
             "quando a trava for ligada. O detalhe traz o que foi exigido e o "
             "que a pessoa tem hoje ('possui'); lista vazia é conta criada sem "
             "nenhuma permissão que vem trabalhando porque nunca houve trava.",
    ),
    "authz.negou": _a(
        "foi barrado por falta de permissão", MOD_USUARIOS, _MEDIO, prep="—",
        nota="A trava está LIGADA (AUTHZ_MODO=bloqueio) e o acesso foi negado "
             "de verdade: a pessoa levou 403 e não viu o dado. Se ela precisa "
             "trabalhar nisso, falta conceder a tela ou o município no cadastro.",
    ),
    "authz.sem_criador": _a(
        "alterou um registro sem criador conhecido", MOD_USUARIOS, _MEDIO,
        prep="—",
        nota="Esta pessoa está configurada como «Somente os que ele criou» neste "
             "módulo, mas a linha que ela tocou está com o criador em branco — "
             "ou é anterior ao campo, ou a conta de quem criou foi excluída. O "
             "sistema DEIXOU PASSAR de propósito: negar trancaria para sempre "
             "todo registro antigo e todo registro de quem saiu da prefeitura. "
             "Cada linha destas mede o tamanho desse vão; ele fecha quando o "
             "campo de criador for preenchido nos registros antigos.",
    ),
    "authz.sem_dono": _a(
        "mexeu num registro que não pertence a município nenhum", MOD_USUARIOS,
        _MEDIO, prep="—",
        nota="A linha tocada está com o município em branco, então não há como "
             "dizer de quem ela é e a trava não conseguiu decidir — o acesso "
             "seguiu. É defeito de cadastro (ou de importação) e some quando a "
             "coluna de município passar a ser obrigatória naquela tabela.",
    ),

    # A trilha da própria trilha. Duas grafias de propósito: `auditoria.*` é o
    # que a tela nova grava, `audit.*` fica como sinônimo porque a tabela já
    # nasceu com esse prefixo (o comentário de models/audit.py cita "export.pdf")
    # e um dia alguém vai gravar assim. Rótulo igual nos dois: o auditor não pode
    # ver dois eventos diferentes onde aconteceu a mesma coisa.
    "auditoria.exportar": _a(
        "exportou a trilha de auditoria", MOD_AUDITORIA, _ALTO, sem_alvo=True,
        nota="A trilha inteira saiu do sistema num arquivo. Quem exporta leva "
             "consigo IP, e-mail e histórico de todo mundo — é dado pessoal "
             "sob a LGPD. O detalhe guarda o filtro usado e quantas linhas "
             "saíram.",
    ),
    "auditoria.podar": _a(
        "executou o expurgo de retenção da trilha de auditoria", MOD_AUDITORIA,
        _ALTO, sem_alvo=True,
        nota="Apagar histórico é ato consciente: de fábrica o sistema NÃO "
             "apaga. A própria poda fica registrada aqui, com quantos "
             "registros e de que período saíram.",
    ),
    # ⚠️ `auditoria.poda` (sem o R) e a grafia que a funcao `audit_log_podar` do
    # BANCO grava — ela roda dentro do Postgres, na mesma transacao do DELETE, e
    # nao passa por services/audit.py. Sem esta entrada, o unico evento capaz de
    # apagar linhas da trilha apareceria na tela com rotulo derivado e risco
    # "medio": o expurgo, que e o ato mais grave que existe aqui, ficaria com
    # cara de rotina.
    "auditoria.poda": _a(
        "executou o expurgo de retenção da trilha de auditoria (direto no banco)",
        MOD_AUDITORIA, _ALTO, sem_alvo=True,
        nota="Apagar histórico é ato consciente: de fábrica o sistema NÃO "
             "apaga. Esta linha é a própria poda se registrando — o detalhe "
             "guarda quantos registros saíram, até que data, com que filtro, "
             "por quem e por quê, e o selo da última linha removida (é ele que "
             "deixa o vão explicável na conferência de integridade).",
    ),
    "auditoria.verificar_integridade": _a(
        "conferiu a integridade da trilha de auditoria", MOD_AUDITORIA, _MEDIO,
        sem_alvo=True,
        nota="Refez a corrente de selos da trilha para checar se algum registro "
             "foi alterado, apagado ou trocado de lugar. O detalhe guarda o "
             "resultado, quantos registros foram conferidos e o estado das "
             "travas do banco no momento da conferência.",
    ),
    # sem_alvo nas duas: o alvo É a trilha, e ela já está dita no fragmento.
    "audit.export": _a(
        "exportou a trilha de auditoria", MOD_AUDITORIA, _ALTO, sem_alvo=True,
        nota="A trilha inteira saiu do sistema num arquivo. Quem exporta leva "
             "consigo IP, e-mail e histórico de todo mundo — é dado pessoal "
             "sob a LGPD.",
    ),
    "audit.prune": _a(
        "podou registros antigos da trilha de auditoria", MOD_AUDITORIA, _ALTO,
        sem_alvo=True,
        nota="Apagar histórico é ato consciente: de fábrica o sistema NÃO "
             "apaga. A própria poda fica registrada aqui, com quantos "
             "registros e de que período saíram.",
    ),
}

CATALOGO: dict[str, Acao] = {
    chave: Acao(chave=chave, **campos) for chave, campos in _TABELA.items()
}

# --- Derivação de ação desconhecida -----------------------------------------
# Primeiro segmento da chave -> módulo. Cobre chave nova que apareça antes de
# alguém lembrar de cadastrar aqui.
_PREFIXO_MODULO: dict[str, str] = {
    "login": MOD_ACESSO,
    "logout": MOD_ACESSO,
    "sso": MOD_ACESSO,
    "auth": MOD_ACESSO,
    "user": MOD_USUARIOS,
    "users": MOD_USUARIOS,
    "usuarios": MOD_USUARIOS,
    "permissao": MOD_USUARIOS,
    "permissoes": MOD_USUARIOS,
    # O molde (Incremento 7). Cai em Usuários porque é ali que ele é escrito e
    # é dali que ele sai para os cadastros das pessoas.
    "modelo_permissao": MOD_USUARIOS,
    "modelo": MOD_USUARIOS,
    "modelos": MOD_USUARIOS,
    # Trava de permissão (services/authz.py). Cai no MESMO módulo de Usuários
    # porque é ali que o dono vai corrigir o que a trava apontou — separá-la
    # obrigaria a olhar dois filtros para responder uma pergunta só.
    "authz": MOD_USUARIOS,
    "cofre": MOD_COFRE,
    "session": MOD_SESSOES,
    "sessao": MOD_SESSOES,
    "service_token": MOD_INTEGRACOES,
    "token": MOD_INTEGRACOES,
    "telegram": MOD_INTEGRACOES,
    "control": MOD_SUPORTE,
    "municipio": MOD_MUNICIPIOS,
    "municipios": MOD_MUNICIPIOS,
    "scraper": MOD_DADOS,
    "coletor": MOD_DADOS,
    "ingestao": MOD_DADOS,
    "convenio": MOD_DADOS,
    "convenios": MOD_DADOS,
    "export": MOD_RELATORIOS,
    "exportacao": MOD_RELATORIOS,
    "rm": MOD_RELATORIOS,
    "relatorio": MOD_RELATORIOS,
    "documento": MOD_RELATORIOS,
    "documentos": MOD_RELATORIOS,
    "bi": MOD_RELATORIOS,
    "painel": MOD_RELATORIOS,
    "gestao": MOD_DADOS,
    "ai": MOD_DADOS,
    "ia": MOD_DADOS,
    "audit": MOD_AUDITORIA,
    "auditoria": MOD_AUDITORIA,
    "nav": MOD_NAVEGACAO,
    "navegacao": MOD_NAVEGACAO,
}

# Segundo segmento de uma chave de navegação que NÃO é o nome de uma tela — é só
# o verbo da família (`nav.view`, `nav.tela`). Nesses casos a tela vem em
# `details`, não na chave, e tratar "view" como tela sairia "acessou a tela view".
_NAV_SEGMENTOS_GENERICOS = {"view", "tela", "telas", "abrir", "visualizar",
                            "acessar", "open"}

# Último segmento da chave -> verbo em 3ª pessoa do passado.
_VERBOS: dict[str, str] = {
    "create": "criou",
    "created": "criou",
    "add": "criou",
    "upsert": "cadastrou ou atualizou",
    "update": "alterou",
    "patch": "alterou",
    "edit": "alterou",
    "put": "alterou",
    "delete": "excluiu",
    "remove": "excluiu",
    "purge": "excluiu",
    "prune": "podou",
    "reveal": "revelou",
    "export": "exportou",
    "download": "baixou",
    "import": "importou",
    "view": "acessou",
    "open": "acessou",
    "read": "consultou",
    "rotate": "rotacionou",
    "revoke": "revogou",
    "mint": "emitiu",
    "refresh": "atualizou",
    "run": "executou",
    "send": "enviou",
    "success": "concluiu",
    "fail": "tentou, sem sucesso,",
    # Infinitivos em português: chave nova do repo já vem assim
    # (`auditoria.exportar`, `auditoria.podar`), e a derivação tem de acompanhar.
    "criar": "criou",
    "editar": "alterou",
    "alterar": "alterou",
    "atualizar": "atualizou",
    "excluir": "excluiu",
    "remover": "excluiu",
    "exportar": "exportou",
    "importar": "importou",
    "revelar": "revelou",
    "podar": "podou",
    "abrir": "acessou",
    "gerar": "gerou",
    "enviar": "enviou",
}

# Primeiro segmento -> substantivo COM artigo, para a frase derivada sair em
# português ("excluiu um convênio") em vez de eco da chave ("excluiu convenio").
_SUBSTANTIVO_PREFIXO: dict[str, str] = {
    "user": "um usuário",
    "users": "um usuário",
    "cofre": "uma senha do cofre",
    "session": "uma sessão capturada",
    "sessao": "uma sessão capturada",
    "service_token": "um token de integração",
    "token": "um token de integração",
    "municipio": "um município",
    "municipios": "um município",
    "convenio": "um convênio",
    "convenios": "um convênio",
    "scraper": "uma coleta de dados",
    "coletor": "uma coleta de dados",
    "ingestao": "uma coleta de dados",
    "rm": "um relatório de monitoramento",
    "relatorio": "um relatório",
    "documento": "um documento",
    "documentos": "um documento",
    "bi": "um painel de indicadores",
    "audit": "a trilha de auditoria",
    "auditoria": "a trilha de auditoria",
    # O módulo saiu em 05/09/2026, mas este rótulo FICA: o `audit_log` é
    # append-only e guarda atos de antes de 09/08/2026. Tirar a tradução não
    # apagaria o registro — só o deixaria ilegível na tela de Auditoria.
    "telegram": "uma notificação do Telegram",
    "navegacao": "uma tela",
    "exportacao": "uma exportação",
    "gestao": "um registro da gestão interna",
    "ai": "uma consulta à IA",
    "ia": "uma consulta à IA",
    "painel": "um painel de indicadores",
    "authz": "uma permissão",
    "modelo_permissao": "um modelo de permissões",
    "modelo": "um modelo de permissões",
    "modelos": "um modelo de permissões",
}

# Palavras que, em QUALQUER posição da chave, sobem o risco derivado para alto.
# "export" NÃO entra: exportar relatório é rotina do dia a dia e marcá-lo como
# alto encheria o filtro de ruído — o que é alto é exportar a AUDITORIA, e essa
# o gatilho "audit" já pega.
_GATILHOS_ALTO = (
    "delete", "remove", "purge", "prune", "reveal", "senha",
    "password", "permiss", "role", "token", "sso", "audit", "session",
)


def _legivel(fragmento_chave: str) -> str:
    """'service_token' -> 'service token'. Só desmonta o snake_case; não tenta
    traduzir, porque chutar tradução de chave desconhecida mente pior do que
    mostrar a chave crua."""
    return fragmento_chave.replace("_", " ").strip()


def _derivar(action: str) -> Acao:
    bruta = (action or "").strip()
    if not bruta:
        # Nem chave existe. Ainda assim tem de virar linha na tela.
        return Acao(chave="", fragmento="executou uma ação não identificada",
                    modulo=MOD_OUTROS, risco=RISCO_MEDIO, conhecida=False)

    partes = [p for p in bruta.split(".") if p]
    prefixo = partes[0] if partes else bruta
    sufixo = partes[-1] if partes else bruta

    modulo = _PREFIXO_MODULO.get(prefixo, MOD_OUTROS)

    minuscula = bruta.lower()
    if modulo == MOD_NAVEGACAO:
        risco = RISCO_BAIXO
    elif any(g in minuscula for g in _GATILHOS_ALTO):
        risco = RISCO_ALTO
    else:
        # Nunca 'baixo' por omissão: ação que ninguém classificou não pode
        # nascer parecendo inofensiva.
        risco = RISCO_MEDIO

    # Navegação antes do verbo: a cobertura pode gravar a tela na própria chave
    # (`nav.dashboard`) ou numa chave fixa com a tela em `details` (`nav.view`,
    # `nav.tela`). A frase tem de sair igual nos dois desenhos — o nome da tela
    # vira o alvo (ver `alvo_legivel`).
    if modulo == MOD_NAVEGACAO and len(partes) > 1:
        return Acao(chave=bruta, fragmento="acessou a tela", modulo=modulo,
                    risco=risco, conhecida=False)

    verbo = _VERBOS.get(sufixo.lower())

    # Exportação é a outra família que cresce sozinha (uma ação por tela/formato:
    # `export.convenios`, `exportacao.cauc`). Sem esta regra a frase viraria
    # "executou a ação export.convenios" — técnica demais para o dono do sistema.
    if prefixo in ("export", "exportacao") and len(partes) > 1 and not verbo:
        return Acao(chave=bruta, fragmento="exportou dados do sistema",
                    modulo=modulo, risco=risco, prep="—", conhecida=False)

    if verbo and len(partes) > 1:
        substantivo = _SUBSTANTIVO_PREFIXO.get(
            prefixo, f"um registro de {_legivel(prefixo)}")
        fragmento = f"{verbo} {substantivo}"
    elif verbo:
        fragmento = verbo
    else:
        fragmento = f"executou a ação “{bruta}”"

    # Travessão porque a frase derivada não tem preposição confiável: "excluiu
    # um convênio de 123" mentiria sobre a relação; "— 123" só justapõe.
    return Acao(chave=bruta, fragmento=fragmento, modulo=modulo, risco=risco,
                prep="—", conhecida=False)


# Cache de derivação: a lista pagina 100 linhas e o CSV exporta milhares, quase
# sempre repetindo as mesmas chaves. dict simples (não lru_cache) porque o valor
# é imutável e o universo de chaves é pequeno e limitado.
_DERIVADAS: dict[str, Acao] = {}
# Teto do cache. A navegação vai gravar `nav.<tela>` a partir da rota que o
# NAVEGADOR informa: um usuário autenticado que forje rotas distintas encheria
# este dicionário para sempre, e cache que só cresce dentro de um worker de API
# é vazamento de memória. Estourado o teto, a derivação continua — só deixa de
# ser guardada.
_DERIVADAS_MAX = 2_000


def _chave(action: Optional[str]) -> str:
    """Normaliza o que chegou do banco. `action` é NOT NULL na tabela, mas a
    trilha tem de sobreviver a linha velha, importada ou torta."""
    return (action or "").strip()


def descrever_acao(action: Optional[str]) -> Acao:
    """Traduz a chave técnica. NUNCA levanta exceção nem devolve None."""
    chave = _chave(action)
    encontrada = CATALOGO.get(chave)
    if encontrada is not None:
        return encontrada
    derivada = _DERIVADAS.get(chave)
    if derivada is None:
        derivada = _derivar(chave)
        if len(_DERIVADAS) < _DERIVADAS_MAX:
            _DERIVADAS[chave] = derivada
    return derivada


def frase_didatica(action: Optional[str], ator: Optional[str] = None,
                   alvo: Optional[str] = None) -> str:
    """Monta '<ator> <fragmento> [<prep>] <alvo>'. Sem ponto final: quem exibe
    decide a pontuação (a lista não usa, o PDF usa)."""
    acao = descrever_acao(action)
    partes: list[str] = [(ator or "").strip() or "Sistema", acao.fragmento]
    alvo_limpo = (alvo or "").strip()
    if alvo_limpo and not acao.sem_alvo:
        # Alvo que é só um id ("#42") dispensa preposição: "excluiu a senha #42"
        # em vez de "excluiu a senha de #42".
        if acao.prep and not alvo_limpo.startswith("#"):
            partes.append(acao.prep)
        partes.append(alvo_limpo)
    return " ".join(p for p in partes if p)


# --- Alvo legível -----------------------------------------------------------
# Todo `target_type=` que o repo REALMENTE grava tem de estar aqui: o que falta
# cai no `_legivel()`, que só desmonta o snake_case — e a linha sai dizendo
# "bi tela link", que não é nome de coisa nenhuma para quem lê a trilha.
_TARGET_TYPE_ROTULOS: dict[str, str] = {
    "user": "usuário",
    "cofre_senha": "senha do cofre",
    "cofre_session": "sessão capturada",
    "service_token": "token de integração",
    "municipio": "município",
    "scraper": "coleta",
    "convenio": "convênio",
    "audit_log": "trilha de auditoria",
    "tela": "tela",
    "rm": "relatório de monitoramento",
    "documento": "documento",
    "bi_tela_link": "link público do painel",
    "gestao_anotacao": "anotação da gestão interna",
    "export": "exportação",
    # Configuracao do modulo RM (hoje so o rodape padrao). Sem esta linha o alvo
    # sairia como "rm config" — o `_legivel` so desmonta o snake_case.
    "rm_config": "configuração do Relatório de Monitoramento",
    # Alvos gravados por services/authz.py. "tela" e "municipio" já existem
    # acima; "linha" é o registro solto cujo município está em branco.
    "linha": "registro",
    # Alcance por linha: a pessoa está restrita a «Somente os que ele criou» e
    # tocou num registro de OUTRA pessoa. Rótulo próprio para o auditor não ler
    # "registro" e achar que é o mesmo caso do município em branco.
    "linha_propria": "registro de outra pessoa",
    "permissao": "permissão",
    # O molde do Incremento 7. Sem esta linha o alvo sairia como "modelo
    # permissao" (o `_legivel` só desmonta o snake_case), que não é nome de
    # coisa nenhuma para quem lê a trilha.
    "modelo_permissao": "modelo de permissões",
}

# Alguns `target_id` são CÓDIGO, não número nem nome ("sigcon", "plano_acao").
# Sem tradução a frase termina em jargão de banco. Só vale por tipo de alvo, para
# um código de um domínio não sequestrar o nome de outro.
_ALVO_POR_TIPO: dict[str, dict[str, str]] = {
    "scraper": {
        "sigcon": "SIGCON-MG",
        "transferegov": "Transfere Gov",
        "cauc": "CAUC",
        "fns": "Fundo Nacional de Saúde",
        "sismob": "SISMOB",
        "obrasgov": "Obras.gov.br",
        "simec": "SIMEC - PAR",
        "dou": "Diário Oficial",
    },
    # Rede de segurança para um `export.<tipo>` novo: os oito de hoje estão
    # catalogados com `sem_alvo`, então nem chegam aqui.
    "export": {
        "convenios": "convênios",
        "voluntarias": "transferências voluntárias",
        "plano_acao": "plano de ação",
        "emendas": "emendas",
        "dou": "Diário Oficial",
        "parlamentares": "parlamentares",
        "ia_relatorio": "relatório da IA",
        "ia": "conversa com a IA",
    },
}

# Chaves de `details` que servem de nome do ALVO, em ordem de preferência.
# 'token' está FORA de propósito: nas chamadas `control.*` ele guarda o nome do
# token da Central, ou seja, o ATOR — usá-lo como alvo trocaria os dois papéis.
_CHAVES_ALVO = ("sistema", "tela", "titulo", "new_email", "email", "nome",
                "name", "automation_key", "source")

# Telas que existem no frontend mas NÃO no catálogo do backend: o
# `telas_catalog.py` exclui de propósito as operacionais da Alavank (cofre,
# sessões), porque ele serve para o Console CONCEDER telas a usuário de cliente.
# A auditoria tem o problema inverso — precisa saber NOMEAR a tela que jamais
# concederia. Daí o complemento local em vez de mexer naquele arquivo.
_TELAS_EXTRA = {
    "cofre": "Cofre de Senhas",
    "sessoes": "Sessões (gov.br)",
    # ⚠️ `suas` FICA AQUI MESMO TENDO SAÍDO DO PRODUTO, e a exceção é o ponto:
    # a trilha descreve o PASSADO. Existem linhas gravadas em que alguém
    # concedeu ou usou esta tela, e elas continuarão existindo — apagar o rótulo
    # faria o auditor ler `suas` cru numa linha de 2026 e não saber o que era.
    # Catálogo de auditoria só cresce; quem encolhe é o catálogo de telas.
    "suas": "Estrutura SUAS (MDS)",
    "paineis": "Painéis Municipais",
    "bi_tela": "Modo Tela (TV) do BI",
    # Rótulo COPIADO de frontend/src/lib/telas.ts, palavra por palavra. Se aqui
    # dissesse "Link público da TV" e o menu dissesse "Gerar link público da TV",
    # o auditor procuraria no sistema uma tela com um nome que não existe.
    "bi_link": "Gerar link público da TV",
    "auditoria": "Auditoria",
}

# O complemento vem PRIMEIRO de propósito: `telas_catalog.py` é o canônico e tem
# de vencer sempre. Se uma tela do complemento entrar lá depois (foi o caso de
# "auditoria"), o rótulo oficial passa a valer sozinho, sem ninguém precisar
# lembrar de apagar a linha daqui.
_TELA_ROTULOS: dict[str, str] = {
    **_TELAS_EXTRA,
    **{t["key"]: t["label"] for t in TELAS_CATALOG},
}


def rotulo_tela(key: Optional[str]) -> str:
    """Chave de tela -> nome que aparece no menu. Chave desconhecida volta como
    veio: melhor mostrar 'xpto' do que sumir com a linha."""
    k = (key or "").strip()
    return _TELA_ROTULOS.get(k, k)


def rotulo_target_type(target_type: Optional[str]) -> str:
    t = (target_type or "").strip()
    return _TARGET_TYPE_ROTULOS.get(t, _legivel(t))


_PALAVRAS_VAZIAS = {"do", "da", "de", "dos", "das", "um", "uma", "com"}


def _ecoa(tipo: str, fragmento: str) -> bool:
    """O rótulo do tipo já foi dito no fragmento? Sem isso a frase sai gaguejando
    ('excluiu a senha de senha do cofre') e trilha que gagueja ninguém lê."""
    frag = fragmento.lower()
    return any(
        palavra in frag
        for palavra in tipo.lower().split()
        if len(palavra) >= 4 and palavra not in _PALAVRAS_VAZIAS
    )


def alvo_legivel(action: Optional[str], target_type: Optional[str] = None,
                 target_id: Optional[Any] = None,
                 details: Optional[dict] = None) -> str:
    """Descobre COMO chamar o alvo do evento, na mesma ordem para lista, modal e
    CSV — se cada consumidor decidisse sozinho, o mesmo evento apareceria com
    nome diferente em cada lugar e a trilha perderia credibilidade.

    Só lê chaves de `details` que estão na allowlist `_CHAVES_ALVO`: `details` é
    campo livre em JSONB e despejar valor arbitrário na frase é como um dado
    sensível vaza para um CSV que ninguém revisou.
    """
    acao = descrever_acao(action)
    if acao.sem_alvo:
        return ""

    if isinstance(details, dict):
        for chave in _CHAVES_ALVO:
            valor = details.get(chave)
            # `bool` é subclasse de `int` em Python: sem descartá-lo, um
            # `details={"source": true}` gravado por outro módulo faria a frase
            # terminar em "True". `details` é JSONB livre — a checagem de tipo é
            # a única coisa entre ele e o texto que o auditor lê.
            if isinstance(valor, bool):
                continue
            if isinstance(valor, (str, int)) and str(valor).strip():
                texto = str(valor).strip()
                # 'tela' é chave técnica do RBAC; na frase tem de virar o nome
                # que a pessoa vê no menu.
                return rotulo_tela(texto) if chave == "tela" else texto

    # Navegação com a tela na PRÓPRIA chave (`nav.dashboard`): o alvo não está
    # em lugar nenhum do registro, está no nome da ação.
    partes = [p for p in _chave(action).split(".") if p]
    if len(partes) > 1 and partes[0] in ("nav", "navegacao") \
            and partes[1] not in _NAV_SEGMENTOS_GENERICOS:
        return rotulo_tela(".".join(partes[1:]))

    if target_id is not None and str(target_id).strip():
        alvo = str(target_id).strip()
        tipo_bruto = (target_type or "").strip()
        if tipo_bruto == "tela" or acao.modulo == MOD_NAVEGACAO:
            return rotulo_tela(alvo)
        # `target_id` que é código do domínio ("sigcon"), não id nem nome.
        traduzido = _ALVO_POR_TIPO.get(tipo_bruto, {}).get(alvo)
        if traduzido:
            return traduzido
        # id numérico sozinho não diz nada ("excluiu a senha de 42"); ganha o
        # tipo na frente e vira "excluiu ... do usuário #42" — a menos que o
        # fragmento já diga o tipo, aí só o número.
        if alvo.isdigit():
            tipo = rotulo_target_type(target_type) if target_type else ""
            if tipo and not _ecoa(tipo, acao.fragmento):
                return f"{tipo} #{alvo}"
            return f"#{alvo}"
        return alvo

    # Último recurso: o TIPO do alvo, quando não sobrou nome nem id.
    tipo = rotulo_target_type(target_type) if target_type else ""
    return "" if (not tipo or _ecoa(tipo, acao.fragmento)) else tipo


# --- Consultas de apoio (filtro da tela e da query) --------------------------
def modulos_disponiveis() -> list[str]:
    """Módulos distintos, na ordem do filtro. Inclui os que hoje só existiriam
    por derivação — o filtro não pode ficar vazio esperando a primeira ação de
    um módulo aparecer."""
    return list(MODULOS)


def chaves_do_modulo(modulo: str) -> list[str]:
    """Chaves EXATAS conhecidas de um módulo (para `action IN (...)`)."""
    return [k for k, a in CATALOGO.items() if a.modulo == modulo]


def prefixos_do_modulo(modulo: str) -> list[str]:
    """Prefixos do módulo (para `action LIKE 'prefixo.%'`). Usar JUNTO com
    `chaves_do_modulo`: o prefixo pega a chave nova que ainda não foi cadastrada
    aqui, e a lista exata pega a chave cujo prefixo mora em outro módulo (todo
    `control.*` é Suporte Alavank, e não Cofre/Usuários)."""
    return sorted({p for p, m in _PREFIXO_MODULO.items() if m == modulo})


def excecoes_do_modulo(modulo: str) -> list[str]:
    """Chaves que o PREFIXO deste módulo pegaria mas que o catálogo pôs em outro.

    Existe porque `prefixos_do_modulo` sozinho double-conta: `user.` mapeia para
    "Usuários e permissões", mas `user.password_change.*` está catalogado em
    "Acesso" (trocar a PRÓPRIA senha não é mexer em permissão de ninguém). Sem
    esta lista o mesmo evento aparece nos dois filtros, e um relatório de
    permissões concedidas sai inflado por trocas de senha rotineiras.

    Uso: `(action IN chaves_do_modulo OR action LIKE 'pref.%')
          AND action NOT IN excecoes_do_modulo`.
    """
    prefixos = set(prefixos_do_modulo(modulo))
    return sorted(
        chave for chave, acao in CATALOGO.items()
        if acao.modulo != modulo
        and chave.split(".", 1)[0] in prefixos
        and "." in chave
    )


def catalogo_para_api() -> dict:
    """Payload que o frontend busca uma vez e usa em lista, modal e filtro."""
    return {
        "acoes": [CATALOGO[k].as_dict() for k in sorted(CATALOGO)],
        "modulos": modulos_disponiveis(),
        "riscos": [
            {"valor": r, "rotulo": RISCO_ROTULOS[r], "tom": RISCO_TOM[r]}
            for r in RISCOS
        ],
        "target_types": [
            {"valor": k, "rotulo": v} for k, v in sorted(_TARGET_TYPE_ROTULOS.items())
        ],
    }


def registrar_acao(chave: str, fragmento: str, modulo: str, risco: str,
                   **extras) -> Acao:
    """Cadastra/sobrescreve uma ação em tempo de import. Existe para o dia em que
    um módulo novo quiser trazer o próprio vocabulário sem editar este arquivo —
    e para os testes. NÃO chamar depois do boot: a tela lê o catálogo montado."""
    acao = replace(Acao(chave=chave, fragmento=fragmento, modulo=modulo,
                        risco=risco), **extras)
    CATALOGO[chave] = acao
    _DERIVADAS.pop(chave, None)
    if acao.modulo not in MODULOS:
        MODULOS.insert(len(MODULOS) - 1, acao.modulo)  # antes de "Outros"
    return acao
