"""
Trilha de auditoria — LEITURA da audit_log para a tela "Auditoria".

Tres promessas desta camada, todas do pedido do dono:

  1. DIDATICA. Cada linha ja sai do servidor com a frase pronta ("Fulano revelou
     a senha do SIGCON-MG"), com o navegador e o dispositivo interpretados. O
     frontend NAO recalcula nada — assim a mesma frase vale na lista, no modal e
     no CSV exportado, em vez de tres versoes da verdade que divergem na primeira
     acao nova que alguem esquecer de traduzir em um dos tres lugares.
  2. HONESTA. Nada de `except: return []`. O endpoint irmao
     (routers/control.py::control_audit) engole excecao e devolve lista vazia —
     auditoria que FALHA fica indistinguivel de auditoria SEM EVENTOS, que e o
     pior defeito possivel numa trilha: some justo quando o banco esta com
     problema, que e quando ela mais importa. Aqui erro vira erro (500).
  3. RECORTADA POR DATA. Periodo obrigatorio, com default de 30 dias. O mesmo
     endpoint irmao nao filtra por data e varre a tabela inteira toda vez; com 5
     anos de retencao isso vira varredura de milhoes de linhas por abertura de
     tela.

SO LEITURA. Nao existe aqui nenhuma rota de escrita, edicao ou exclusao, de
proposito: a imutabilidade de verdade (append-only no banco, papel proprio e
encadeamento por hash) e o Incremento 3, e nada neste arquivo atrapalha isso
depois — nada daqui grava na audit_log a nao ser o registro da propria
exportacao, que passa pelo servico de auditoria como qualquer outro evento.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.audit import AuditLog
from models.municipio import Municipio
from models.user import User
# Catalogo didatico e leitor de User-Agent: sao SERVICOS proprios, com teste,
# e nao copias locais. Reescrever qualquer um dos dois aqui daria duas
# traducoes do MESMO evento — o defeito que esta tela existe pra nao ter.
from services.audit_catalog import (
    CATALOGO as CATALOGO_ACOES,
    RISCO_ALTO,
    alvo_legivel,
    descrever_acao,
    frase_didatica,
)
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.user_agent import parse_user_agent
# `registrar_critico` (e nao `registrar`) de proposito: e a porta que PROPAGA a
# falha de gravacao. Se a linha da exportacao nao entrar, a exportacao nao
# acontece — baixar a trilha inteira nao pode ser o unico ato do sistema sem
# rastro.
#
# `registrar` (melhor esforco) entra junto so para a CONFERENCIA de integridade:
# ali a resposta e o produto de seguranca, e nao pode ser o INSERT do registro
# da conferencia que decide se o auditor fica sabendo que a trilha foi
# adulterada. Ver `verificar_integridade`.
from services.audit import registrar, registrar_critico
from services import audit_integridade

logger = logging.getLogger("auditoria")

router = APIRouter(prefix="/api/auditoria", tags=["auditoria"])

# Fuso do NEGOCIO. O usuario pensa "os acessos do dia 3", nao "das 03:00Z do dia
# 3 as 03:00Z do dia 4" — entao o periodo e recortado em horario de Brasilia e a
# data/hora exibida ja vem convertida. Fallback de offset fixo porque a imagem
# python:3.12-slim pode subir sem tzdata; o Brasil nao tem horario de verao
# desde 2019 (Dec. 9.772/2019), entao -03:00 e estavel hoje — se voltar, basta a
# tzdata estar instalada que o ZoneInfo assume sozinho.
try:
    from zoneinfo import ZoneInfo
    TZ_BR = ZoneInfo("America/Sao_Paulo")
except Exception:  # pragma: no cover
    TZ_BR = timezone(timedelta(hours=-3))

JANELA_PADRAO_DIAS = 30
PER_PAGE_PADRAO = 50
PER_PAGE_MAX = 200

# Teto DECLARADO da exportacao (vai no /catalogo, pra tela avisar antes do
# clique) e repetido DENTRO do arquivo quando corta. Sem teto, um pedido de 5
# anos monta dezenas de MB em memoria em cada um dos 2 workers da API.
EXPORT_MAX_LINHAS = 25_000


# ---------------------------------------------------------------------------
# Catalogo: modulos, acoes e as frases didaticas
# ---------------------------------------------------------------------------
# O "modulo" nao existe como coluna: e derivado do prefixo da acao. Vantagem de
# derivar em vez de gravar: as 32 chamadas de log_event que ja existem entram no
# recorte sem migration nenhuma, e uma acao nova aparece na trilha mesmo que
# ninguem a cadastre aqui (ela cai em "outros" — nunca some).
#
# As acoes `control.*` sao da Central da Alavank e ficam no modulo FUNCIONAL
# (control.cofre.reveal -> Cofre), nao num modulo "Central": a pergunta do
# auditor e "quem viu essa senha", e a resposta nao pode depender de ele saber
# que existe um plano de controle.
MODULOS = [
    {"key": "acesso", "label": "Acesso e sessão",
     "prefixos": ("login.", "logout", "sso.", "control.sso.")},
    {"key": "usuarios", "label": "Usuários e permissões",
     "prefixos": ("user.", "control.user.")},
    {"key": "cofre", "label": "Cofre de senhas",
     "prefixos": ("cofre.", "control.cofre.", "session.")},
    # `control.session_token.*` (routers/control.py, nome montado em runtime —
    # nao aparece num grep ingenuo por `action="`) e emissao/rotacao do token da
    # extensao de captura. Sem este prefixo o ato caia em "Outros", que e onde
    # ninguem procura por criacao de credencial de maquina.
    {"key": "integracoes", "label": "Integrações e tokens",
     "prefixos": ("service_token.", "control.session_token.")},
    {"key": "municipios", "label": "Municípios",
     "prefixos": ("municipio.", "control.municipio.")},
    # "coletor." e o que routers/convenios.py grava de verdade (coletor.disparo);
    # "scraper."/"ingestao." ficam pelos jobs. Prefixo que ninguem grava e filtro
    # que nunca acha nada — e o inverso, acao gravada sem prefixo aqui, e evento
    # que some do filtro do modulo.
    {"key": "dados", "label": "Atualização de dados",
     "prefixos": ("control.refresh", "coletor.", "scraper.", "ingestao.")},
    {"key": "navegacao", "label": "Navegação",
     "prefixos": ("nav.", "navegacao.")},
    {"key": "exportacao", "label": "Exportações",
     "prefixos": ("export.", "exportacao.")},
    {"key": "auditoria", "label": "Auditoria",
     "prefixos": ("auditoria.", "audit.")},
    # ⚠️ "documento." no SINGULAR e o que routers/documentos.py grava
    # (documento.create/update/delete). Com so o plural, as tres acoes caiam em
    # "Outros" e o filtro "Documentos e relatórios" vinha vazio.
    {"key": "documentos", "label": "Documentos e relatórios",
     "prefixos": ("documento.", "documentos.", "rm.")},
    {"key": "gestao", "label": "Gestão interna",
     "prefixos": ("gestao.",)},
    {"key": "ia", "label": "IA PACTHA", "prefixos": ("ai.", "ia.")},
    {"key": "bi", "label": "Painel de Indicadores", "prefixos": ("bi.", "painel.")},
    {"key": "telegram", "label": "Telegram", "prefixos": ("telegram.",)},
    # "outros" nao tem prefixo: e o complemento de todos os acima. Existe pra que
    # uma acao nova continue filtravel antes de alguem cadastra-la aqui.
    {"key": "outros", "label": "Outros", "prefixos": ()},
]
MODULO_LABEL = {m["key"]: m["label"] for m in MODULOS}

# Prefixo mais LONGO primeiro: "control.cofre." tem de ganhar de "control." caso
# um modulo generico seja acrescentado depois.
_PREFIXOS = sorted(
    ((p, m["key"]) for m in MODULOS for p in m["prefixos"]),
    key=lambda t: -len(t[0]),
)

# Acao -> (rotulo curto, severidade, molde da frase didatica).
# Severidade e o que a tela pinta: "critico" = mexeu em segredo/permissao,
# "alerta" = falhou ou saiu dado do sistema, "info" = rotina.
# Placeholders do molde: {quem}, {alvo}, {onde}, {email}, {perfil}, {mudancas}.
ACOES: dict[str, tuple[str, str, str]] = {
    # --- Acesso ---
    "login.success": ("Entrou no sistema", "info", "{quem} entrou no sistema."),
    "login.fail": ("Tentativa de entrada RECUSADA", "alerta",
                   "Tentativa de entrada RECUSADA para o e-mail {email}: "
                   "usuário inexistente ou senha incorreta."),
    "login.disabled_user": ("Entrada bloqueada (conta desativada)", "alerta",
                            "{quem} tentou entrar, mas a conta está DESATIVADA."),
    "logout": ("Saiu do sistema", "info", "{quem} saiu do sistema."),
    "sso.login": ("Entrou por acesso técnico da Alavank (SSO)", "alerta",
                  "{quem} entrou no sistema por acesso técnico da Central Alavank (SSO)."),
    "control.sso.mint": ("Gerou acesso técnico da Alavank (SSO)", "critico",
                         "{quem} gerou um acesso técnico (SSO) para entrar no sistema "
                         "como {alvo}."),
    # --- Usuarios e permissoes ---
    "user.create": ("Criou usuário", "critico", "{quem} criou {alvo}{perfil}."),
    "user.update": ("Alterou usuário / permissões", "critico",
                    "{quem} alterou {alvo}{mudancas}."),
    "user.reset_password": ("Redefiniu a senha de outro usuário", "critico",
                            "{quem} redefiniu a senha de {alvo}."),
    "user.password_change.success": ("Trocou a própria senha", "info",
                                     "{quem} trocou a própria senha."),
    "user.password_change.fail": ("Erro ao trocar a própria senha", "alerta",
                                  "{quem} tentou trocar a própria senha e errou a senha atual."),
    "control.user.create": ("Criou usuário (pela Central Alavank)", "critico",
                            "{quem} criou {alvo}{perfil} pela Central Alavank."),
    "control.user.patch": ("Alterou usuário (pela Central Alavank)", "critico",
                           "{quem} alterou {alvo} pela Central Alavank{mudancas}."),
    "control.user.reset_password": ("Redefiniu senha (pela Central Alavank)", "critico",
                                    "{quem} redefiniu a senha de {alvo} pela Central Alavank."),
    "control.user.delete": ("Excluiu usuário (pela Central Alavank)", "critico",
                            "{quem} excluiu {alvo} pela Central Alavank."),
    # --- Cofre de senhas ---
    "cofre.reveal": ("REVELOU uma senha guardada", "critico", "{quem} revelou {alvo}."),
    "cofre.create": ("Guardou uma senha no cofre", "critico", "{quem} guardou {alvo} no cofre."),
    "cofre.update": ("Alterou uma senha guardada", "critico", "{quem} alterou {alvo}."),
    "cofre.delete": ("Excluiu uma senha do cofre", "critico", "{quem} excluiu {alvo} do cofre."),
    "control.cofre.reveal": ("REVELOU uma senha (pela Central Alavank)", "critico",
                             "{quem} revelou {alvo} pela Central Alavank."),
    "control.cofre.create": ("Guardou uma senha (pela Central Alavank)", "critico",
                             "{quem} guardou {alvo} no cofre pela Central Alavank."),
    "control.cofre.patch": ("Alterou uma senha (pela Central Alavank)", "critico",
                            "{quem} alterou {alvo} pela Central Alavank."),
    "control.cofre.delete": ("Excluiu uma senha (pela Central Alavank)", "critico",
                             "{quem} excluiu {alvo} do cofre pela Central Alavank."),
    "session.create": ("Guardou uma sessão capturada", "critico",
                       "{quem} guardou {alvo} no cofre."),
    "session.update": ("Atualizou uma sessão capturada", "info",
                       "{quem} atualizou {alvo}."),
    # --- Integracoes ---
    "service_token.create": ("Criou token de integração", "critico",
                             "{quem} criou {alvo}."),
    "service_token.revoke": ("Revogou token de integração", "critico",
                             "{quem} revogou {alvo}."),
    "service_token.rotate": ("Trocou o segredo de um token", "critico",
                             "{quem} trocou o segredo de {alvo}."),
    # --- Municipios e dados ---
    "control.municipio.upsert": ("Cadastrou/atualizou município", "alerta",
                                 "{quem} cadastrou ou atualizou {alvo} pela Central Alavank."),
    "control.municipio.patch": ("Alterou município", "alerta",
                                "{quem} alterou {alvo} pela Central Alavank."),
    "control.refresh": ("Pediu atualização dos dados", "info",
                        "{quem} pediu uma atualização dos dados ({alvo}) pela Central Alavank."),
    # --- Auditoria ---
    "auditoria.exportar": ("EXPORTOU a trilha de auditoria", "critico",
                           "{quem} exportou {alvo}{onde}."),
    "auditoria.podar": ("Podou a trilha (expurgo de retenção)", "critico",
                        "{quem} executou o expurgo de retenção da trilha de auditoria."),
    # Grafia gravada pela funcao `audit_log_podar` DO BANCO (ela roda dentro do
    # Postgres e nao passa por services/audit.py). Mesmo rótulo da de cima: o
    # auditor não pode ver dois eventos diferentes onde aconteceu a mesma coisa.
    "auditoria.poda": ("Podou a trilha (expurgo de retenção)", "critico",
                       "{quem} executou o expurgo de retenção da trilha de "
                       "auditoria, direto no banco de dados."),
    # O veredito nao entra na frase: ele vai em `alvo_nome` ("12.480 registros —
    # íntegra"), que a lista, o modal e a coluna "Nome do alvo" do CSV ja
    # mostram. Frase e veredito no mesmo lugar obrigaria um molde por desfecho.
    "auditoria.verificar_integridade": ("Conferiu a integridade da trilha", "alerta",
                                        "{quem} conferiu a integridade da trilha de "
                                        "auditoria."),
}

# Regra por PREFIXO, usada quando a acao nao esta no catalogo acima. Cobre as
# familias que crescem sozinhas (navegacao e exportacao geram uma acao por tela)
# sem obrigar ninguem a cadastrar item por item.
REGRAS_PREFIXO: list[tuple[str, tuple[str, str, str]]] = [
    ("nav.", ("Abriu uma tela", "info", "{quem} abriu {alvo}.")),
    ("navegacao.", ("Abriu uma tela", "info", "{quem} abriu {alvo}.")),
    ("export.", ("Exportou dados do sistema", "alerta", "{quem} exportou {alvo}.")),
    ("exportacao.", ("Exportou dados do sistema", "alerta", "{quem} exportou {alvo}.")),
    ("auditoria.", ("Ação na auditoria", "alerta", "{quem} executou «{acao}» na auditoria.")),
]

# Vocabulario FECHADO da coluna `resultado` (models/audit.py + a CHECK da
# migration). NAO derivamos o resultado da acao aqui: quem grava ja normalizou
# (services/audit.py::_resultado) e uma segunda regra do lado da leitura
# divergiria da primeira sem ninguem perceber.
#
# NULL tem significado PROPRIO e por isso e um filtro: e linha anterior a este
# incremento. A migration deliberadamente NAO fez backfill de `resultado` — dar
# "sucesso" a elas seria a trilha afirmando o que nao sabe. Entao a tela tambem
# nao afirma: mostra "não informado".
RESULTADOS = [
    {"key": "sucesso", "label": "Concluída"},
    {"key": "negado", "label": "Negada / bloqueada"},
    {"key": "erro", "label": "Erro"},
    {"key": "nao_informado", "label": "Não informado (registro antigo)",
     "descricao": "Evento anterior à auditoria detalhada: o sistema não "
                  "registrava o desfecho da ação nessa época."},
]
SEVERIDADES = [
    {"key": "critico", "label": "Sensível", "descricao":
     "Mexeu em segredo, permissão ou conta de usuário."},
    {"key": "alerta", "label": "Atenção", "descricao":
     "Falhou, foi recusada, ou tirou dado de dentro do sistema."},
    {"key": "info", "label": "Rotina", "descricao": "Uso normal do sistema."},
]


# Ordem de gravidade, para combinar duas leituras da mesma acao sem que a mais
# branda apague a mais grave. Nunca o contrario: rebaixar severidade e o unico
# erro desta escala que faz o auditor deixar de olhar uma linha.
_ORDEM_SEVERIDADE = {"info": 0, "alerta": 1, "critico": 2}


def _maior_severidade(a: str, b: str) -> str:
    return a if _ORDEM_SEVERIDADE.get(a, 0) >= _ORDEM_SEVERIDADE.get(b, 0) else b


def _modulo_de(action: str) -> str:
    for prefixo, key in _PREFIXOS:
        if action.startswith(prefixo):
            return key
    return "outros"


def _regra_de(action: str) -> tuple[str, str, Optional[str]]:
    """(rotulo, severidade, molde) da acao. Desconhecida NUNCA fica em branco.

    Molde `None` e SENTINELA: quer dizer "a frase e montada pelo catalogo
    didatico" (services/audit_catalog.py), que ja sabe encaixar a preposicao
    certa e nao repetir o tipo do alvo dentro da propria frase.

    Antes daqui sair para o catalogo, TODA acao que este arquivo nao lista caia
    numa frase tecnica ("Fulano executou a ação «bi.tela_link.create»") com
    severidade "info". Ou seja: publicar o painel do municipio num link SEM
    LOGIN, excluir documento, apagar o Relatorio de Monitoramento e emitir token
    de maquina apareciam na tela como ROTINA, com a chave de banco no lugar do
    rotulo. O catalogo ja classificou essas familias por risco — perguntar a ele
    e melhor do que manter aqui uma segunda tabela que divergiria da primeira."""
    if action in ACOES:
        return ACOES[action]

    # A regra por FAMILIA nao decide sozinha: ela define o PISO de severidade.
    # "export." vale "alerta" porque dado saiu do sistema — e isso continua
    # valendo mesmo quando o catalogo souber dizer, com mais precisao, QUAL
    # relatorio saiu (ele classifica exportacao como risco medio, que aqui seria
    # so "info", e a trilha perderia a marca de que houve saida de dado).
    piso = None
    for prefixo, regra in REGRAS_PREFIXO:
        if action.startswith(prefixo):
            piso = regra
            break

    catalogada = descrever_acao(action)
    fragmento = (catalogada.fragmento or "").strip()
    # `conhecida=False` significa que o catalogo tambem nao sabe — ele derivou da
    # propria string. Nesse caso a regra de familia diz mais do que a derivacao.
    if fragmento and catalogada.conhecida:
        # So risco ALTO vira "critico". "medio" e o piso de quem ninguem
        # classificou (o proprio audit_catalog diz isso), entao promove-lo a
        # "Atenção" pintaria a tela inteira — e cor que aparece em tudo deixa de
        # significar alerta.
        severidade = "critico" if catalogada.risco == RISCO_ALTO else "info"
        if piso:
            severidade = _maior_severidade(severidade, piso[1])
        return (fragmento[:1].upper() + fragmento[1:], severidade, None)
    if piso:
        return piso
    if fragmento:
        return (fragmento[:1].upper() + fragmento[1:],
                "critico" if catalogada.risco == RISCO_ALTO else "info", None)
    return (f"Ação «{action}»", "info", "{quem} executou a ação «{acao}»{alvo_sufixo}.")


# ---------------------------------------------------------------------------
# Interpretacao do User-Agent (navegador / sistema / dispositivo)
# ---------------------------------------------------------------------------
def _interpretar_ua(ua: Optional[str]) -> dict:
    """Adapta `services/user_agent.py` ao formato do bloco `origem`.

    NAO ha regex aqui: a leitura do User-Agent e um servico proprio, com bateria
    de teste, e o que este arquivo faz e so encaixar as chaves. Uma segunda
    tabela de assinaturas dentro do router significaria que "Edge" na tela e
    "Edge" no PDF podem divergir no dia em que so uma das duas for atualizada —
    e a interpretacao roda na LEITURA justamente pra que melhora-la conserte
    tambem os registros de cinco anos atras.

    O UA cru continua na resposta: interpretacao e conveniencia, a evidencia e
    o texto original."""
    dados = parse_user_agent(ua)
    navegador = f"{dados['navegador']} {dados['versao']}".strip()
    return {
        "navegador": navegador,
        "sistema": dados["sistema"],
        "dispositivo": dados["dispositivo"],
        "resumo": dados["resumo"],
        # `bot=True` e achado de auditoria (acesso de robo/automacao com sessao
        # de gente), nao enfeite — por isso sobe pra resposta em vez de ficar so
        # dissolvido no texto do resumo.
        "automacao": bool(dados["bot"]),
        "user_agent": (ua or "").strip(),
    }


# ---------------------------------------------------------------------------
# Montagem da linha didatica
# ---------------------------------------------------------------------------
_ROTULO_CAMPO = {
    "name": "Nome", "nome": "Nome", "email": "E-mail", "new_email": "E-mail",
    "role": "Perfil", "active": "Ativo", "telas": "Telas liberadas",
    "municipio_ids": "Municípios liberados", "municipios": "Municípios liberados",
    "must_change_password": "Exigir troca de senha", "senha": "Senha",
    "sistema": "Sistema", "usuario": "Usuário", "url": "Endereço",
    "categoria": "Categoria", "observacao": "Observação", "scopes": "Permissões do token",
}
# Com o artigo junto: estes rotulos entram no MEIO da frase ("Ana alterou o
# usuário «Maria»"), e sem artigo a frase sai telegráfica.
#
# ⚠️ TEM de cobrir todo `target_type=` que o repo grava de verdade. O que falta
# cai no `t.replace("_", " ")` la embaixo e a frase sai com jargao de banco —
# "gestao anotacao #12", "bi tela link «TV do gabinete»" — que nao e nome de
# coisa nenhuma pra quem le a trilha.
_ROTULO_ALVO = {
    "user": "o usuário", "cofre_senha": "a senha", "cofre_session": "a sessão capturada",
    "service_token": "o token de integração", "municipio": "o município",
    "scraper": "a coleta de dados", "audit_log": "a trilha de auditoria",
    "auditoria": "a trilha de auditoria", "convenio": "o convênio",
    "documento": "o documento", "tela": "a tela",
    "rm": "o Relatório de Monitoramento",
    "gestao_anotacao": "a anotação da gestão interna",
    "bi_tela_link": "o link público do Painel",
    "export": "a exportação",
}


def _texto_valor(v) -> str:
    """Valor legivel pra leigo. Lista vira lista separada por virgula (e nao o
    `['a', 'b']` do Python), booleano vira Sim/Não, vazio fica explicito — senao
    "de: para: " numa alteracao de permissao nao diz nada."""
    if v is None:
        return "(vazio)"
    if isinstance(v, bool):
        return "Sim" if v else "Não"
    if isinstance(v, (list, tuple, set)):
        itens = [str(x) for x in v]
        return ", ".join(sorted(itens)) if itens else "(nenhum)"
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    s = str(v).strip()
    return s if s else "(vazio)"


def _alteracoes(valor_antes, valor_depois) -> list[dict]:
    """Traduz as colunas valor_antes/valor_depois em linhas campo · de · para.

    E este par que responde "quem deu essa permissao a essa pessoa, e quando":
    sem valor-antes, a trilha diz que houve alteracao mas nao diz o que mudou.
    Quem grava ja reduziu aos campos que MUDARAM (services/audit.py::
    campos_alterados) — aqui so traduzimos para portugues de leigo. Linha
    anterior ao incremento tem os dois NULL e simplesmente nao rende linhas."""
    antes = valor_antes if isinstance(valor_antes, dict) else {}
    depois = valor_depois if isinstance(valor_depois, dict) else {}
    if not antes and not depois:
        return []
    linhas = []
    for campo in sorted(set(antes) | set(depois)):
        va, vd = antes.get(campo), depois.get(campo)
        # Compara pelo texto ja normalizado: ["a","b"] e ["b","a"] sao a MESMA
        # permissao, e listar isso como mudanca produziria ruido a cada gravacao.
        ta, td = _texto_valor(va), _texto_valor(vd)
        if ta == td:
            continue
        linhas.append({"campo": _ROTULO_CAMPO.get(campo, campo), "de": ta, "para": td})
    return linhas


def _descrever_alvo(target_type: Optional[str], target_id: Optional[str],
                    alvo_nome: Optional[str], details: Optional[dict]) -> str:
    """Sintagma do alvo em portugues corrente ("a senha do sistema «SIGCON-MG»").
    Preferimos o rotulo humano ao id tecnico: "a senha #12" nao ajuda ninguem a
    decidir se aquele acesso foi indevido."""
    d = details if isinstance(details, dict) else {}
    t = (target_type or "").strip()

    # `alvo_nome` e o nome CONGELADO no instante do ato (coluna propria). Vence
    # tudo: sobrevive a exclusao do alvo, que e justamente quando o id nao diz
    # mais nada. Linhas anteriores ao incremento tem NULL e caem nas regras
    # abaixo, que remontam o nome a partir de `details`.
    if alvo_nome and alvo_nome.strip():
        rotulo = _ROTULO_ALVO.get(t) or (t.replace("_", " ") if t else "")
        return f"{rotulo} «{alvo_nome.strip()}»".strip()

    if t == "cofre_senha":
        sistema = d.get("sistema")
        return f"a senha do sistema «{sistema}»" if sistema else f"a senha #{target_id}"
    if t == "cofre_session":
        chave = d.get("automation_key")
        return f"a sessão capturada de «{chave}»" if chave else f"a sessão capturada #{target_id}"
    if t == "user":
        alvo = d.get("new_email") or d.get("email") or d.get("user_email")
        return f"o usuário {alvo}" if alvo else f"o usuário #{target_id}"
    if t == "service_token":
        nome = d.get("name")
        return f"o token de integração «{nome}»" if nome else f"o token de integração #{target_id}"
    if t == "municipio":
        nome = d.get("nome") or d.get("municipio") or d.get("ibge") or target_id
        return f"o município «{nome}»"
    if t == "scraper":
        return f"a fonte «{target_id}»" if target_id else "a coleta de dados"
    if t in ("audit_log", "auditoria"):
        return "a trilha de auditoria"

    # Navegacao/telas: a acao nem sempre traz target_type, o rotulo vem em details.
    tela = d.get("titulo") or d.get("tela") or d.get("rota") or d.get("path")
    if tela and t in ("", "tela", "pagina", "rota", "screen"):
        return f"a tela «{tela}»"

    if t:
        rotulo = _ROTULO_ALVO.get(t, t.replace("_", " "))
        return f"{rotulo} #{target_id}" if target_id else rotulo
    return ""


def _descrever_quem(nome: Optional[str], email: Optional[str],
                    details: Optional[dict]) -> dict:
    """Quem fez. Cobre os tres tipos de autor que a tabela guarda:
      - usuario do sistema (id + email);
      - token da Central Alavank (as chamadas control.* nao tem usuario);
      - ninguem (tentativa de login que falhou antes de existir usuario).
    Nunca devolve vazio: linha de auditoria sem autor visivel e linha inutil."""
    d = details if isinstance(details, dict) else {}
    nome = (nome or "").strip()
    email = (email or "").strip()
    if nome and email:
        rotulo = f"{nome} ({email})"
    elif email:
        rotulo = email
    elif nome:
        rotulo = nome
    elif d.get("token"):
        rotulo = f"Central Alavank (token «{d['token']}»)"
    elif d.get("principal"):
        rotulo = f"Integração «{d['principal']}»"
    elif d.get("email"):
        rotulo = f"{d['email']} (não autenticado)"
    else:
        rotulo = "Não identificado"
    return {"nome": nome or None, "email": email or None, "rotulo": rotulo}


def _resumo_mudancas(alteracoes: list[dict]) -> str:
    """Resumo curto das mudancas pra caber na frase da LISTA. O detalhe completo
    fica no modal — aqui e so pra tela responder sem precisar de clique."""
    if not alteracoes:
        return ""
    partes = [f"{a['campo']}: {a['de']} → {a['para']}" for a in alteracoes[:3]]
    if len(alteracoes) > 3:
        partes.append(f"e mais {len(alteracoes) - 3} campo(s)")
    return " — " + "; ".join(partes)


def _quando(dt: Optional[datetime]) -> tuple[str, Optional[str]]:
    if dt is None:
        return ("—", None)
    # created_at e TIMESTAMPTZ; se por algum caminho vier naive, assume UTC (que
    # e como o NOW() do servidor grava) em vez de fingir que ja e local.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(TZ_BR)
    return (local.strftime("%d/%m/%Y %H:%M:%S"), local.isoformat())


def _montar_item(a: AuditLog, nome_municipio: Optional[str]) -> dict:
    """A linha COMPLETA e ja interpretada. Tudo que a tela mostra sai daqui.

    O nome do autor vem da COLUNA `usuario_nome` (congelada no ato), nao de um
    JOIN com users: a trilha tem de continuar dizendo quem foi depois de a conta
    ser excluida — `control.user.delete` zera o `user_id` — e tem de dizer o nome
    que a pessoa TINHA no dia, nao o que ela tem hoje."""
    rotulo_acao, severidade, molde = _regra_de(a.action)
    details = a.details if isinstance(a.details, dict) else None
    alvo = _descrever_alvo(a.target_type, a.target_id, a.alvo_nome, details)
    quem = _descrever_quem(a.usuario_nome, a.user_email, details)
    alteracoes = _alteracoes(a.valor_antes, a.valor_depois)
    resultado = a.resultado or "nao_informado"

    d = details or {}
    contexto = {
        "quem": quem["rotulo"],
        "alvo": alvo or "um item do sistema",
        "alvo_sufixo": f" em {alvo}" if alvo else "",
        "acao": a.action,
        "email": d.get("email") or a.user_email or "(não informado)",
        "perfil": f" com o perfil «{d['role']}»" if d.get("role") else "",
        "mudancas": _resumo_mudancas(alteracoes),
        "onde": f" do município {nome_municipio}" if nome_municipio else "",
    }
    if molde is None:
        # Acao fora do catalogo local: a frase inteira vem do catalogo didatico,
        # que escolhe a preposicao pelo tipo do ato e omite o alvo quando o ato e
        # sobre o proprio autor. Montar aqui um "{quem} <fragmento> em {alvo}"
        # generico gaguejaria — "excluiu o documento em o documento «Ofício 12»".
        # `alvo_nome` (coluna congelada) vem na frente do palpite por `details`.
        alvo_cru = (a.alvo_nome or "").strip() or alvo_legivel(
            a.action, a.target_type, a.target_id, details)
        frase = frase_didatica(a.action, quem["rotulo"], alvo_cru) + "."
    else:
        try:
            frase = molde.format(**contexto)
        except (KeyError, IndexError):
            # Molde novo com placeholder que ninguem definiu: melhor uma frase
            # pobre do que uma linha de auditoria que some por erro de formatacao.
            logger.warning("Molde de frase invalido para a acao %s", a.action)
            frase = f"{quem['rotulo']}: {rotulo_acao}."

    quando_txt, quando_iso = _quando(a.created_at)
    sessao_txt, sessao_iso = _quando(a.sessao_inicio) if a.sessao_inicio else ("—", None)
    modulo = _modulo_de(a.action)
    return {
        "id": a.id,
        "quando": quando_txt,
        "quando_iso": quando_iso,
        "usuario": {"id": a.user_id, **quem},
        "acao": a.action,
        "acao_rotulo": rotulo_acao,
        "modulo": modulo,
        "modulo_rotulo": MODULO_LABEL.get(modulo, "Outros"),
        "resultado": resultado,
        "resultado_rotulo": _rotulo_resultado(resultado),
        # Um ato de rotina que foi NEGADO ou deu ERRO deixa de ser rotina: e a
        # tentativa barrada que o auditor procura. Acao ja sensivel continua
        # sensivel — negar nao a torna menos grave.
        "severidade": ("alerta" if (resultado in ("negado", "erro") and severidade == "info")
                       else severidade),
        "o_que_aconteceu": frase,
        "alvo": {"tipo": a.target_type, "id": a.target_id, "rotulo": alvo or None,
                 "nome": a.alvo_nome},
        "municipio": ({"id": a.municipio_id, "nome": nome_municipio}
                      if a.municipio_id else None),
        "origem": {
            "ip": a.ip or "Não registrado",
            "metodo": a.http_metodo,
            "rota": a.http_path,
            **_interpretar_ua(a.user_agent),
        },
        # Agrupa "entrou as 9h12 e ate as 9h40 fez isto e aquilo". O id e um hash
        # curto (nao serve de credencial) e existe pra tela poder oferecer "ver
        # tudo desta sessao" — o filtro `sessao` da listagem recebe este valor.
        "sessao": {"id": a.sessao_id, "inicio": sessao_txt, "inicio_iso": sessao_iso}
                  if a.sessao_id else None,
        "alteracoes": alteracoes,
        "detalhes": details,
    }


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------
def _esc(texto: str) -> str:
    """Escapa os curingas do LIKE. Sem isto, buscar por "_" ou "%" devolve a
    tabela inteira e o usuario conclui que o filtro nao funciona."""
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _janela(de: Optional[date], ate: Optional[date]) -> tuple[datetime, datetime, date, date]:
    """Periodo efetivo, em horario de Brasilia. `ate` e INCLUSIVO (quem pede
    "até 03/08" quer o dia 03 inteiro), entao o corte de cima e 04/08 00:00.
    Default de 30 dias: a tela NUNCA abre sem recorte de data."""
    hoje = datetime.now(TZ_BR).date()
    fim_d = ate or hoje
    ini_d = de or (fim_d - timedelta(days=JANELA_PADRAO_DIAS))
    if ini_d > fim_d:
        raise HTTPException(400, "A data inicial não pode ser posterior à data final")
    ini = datetime.combine(ini_d, time.min, tzinfo=TZ_BR)
    fim = datetime.combine(fim_d + timedelta(days=1), time.min, tzinfo=TZ_BR)
    return ini, fim, ini_d, fim_d


def _cond_modulo(modulo: str):
    if modulo == "outros":
        return ~or_(*[AuditLog.action.like(_esc(p) + "%", escape="\\")
                      for p, _ in _PREFIXOS])
    prefixos = [p for p, k in _PREFIXOS if k == modulo]
    if not prefixos:
        raise HTTPException(400, f"Módulo desconhecido: {modulo}")
    return or_(*[AuditLog.action.like(_esc(p) + "%", escape="\\") for p in prefixos])


def _cond_resultado(resultado: str):
    """Filtra pela COLUNA, nunca por deducao. `nao_informado` = IS NULL, que e o
    recorte "linhas anteriores a este incremento" — util pra saber ate onde a
    trilha detalhada alcanca."""
    if resultado == "nao_informado":
        return AuditLog.resultado.is_(None)
    if resultado in {r["key"] for r in RESULTADOS}:
        return AuditLog.resultado == resultado
    raise HTTPException(400, "Resultado inválido (use: sucesso | negado | erro | nao_informado)")


def _cond_escopo(current: User) -> list:
    """Recorte por municipio do proprio usuario. Admin (allowed_municipio_ids
    None) ve tudo. Nao-admin ve o que e do municipio dele MAIS os eventos sem
    municipio — login, troca de senha e gestao de usuario sao da INSTANCIA, nao
    de uma prefeitura, e esconde-los deixaria a trilha justamente sem a parte
    que mais importa pra seguranca. Vive numa funcao so porque a lista e o
    detalhe TEM de concordar: se o detalhe fosse mais permissivo, bastaria
    adivinhar o id pra ler o evento que a lista nao mostra."""
    permitidos = getattr(current, "allowed_municipio_ids", None)
    if permitidos is None:
        return []
    if permitidos:
        return [or_(AuditLog.municipio_id.is_(None),
                    AuditLog.municipio_id.in_(permitidos))]
    return [AuditLog.municipio_id.is_(None)]


def _condicoes(*, ini: datetime, fim: datetime, usuario: Optional[str],
               acao: Optional[str], modulo: Optional[str], municipio_id: Optional[int],
               resultado: Optional[str], sessao: Optional[str], busca: Optional[str],
               current: User) -> list:
    """Conjunto de condicoes compartilhado por lista, contagem e exportacao —
    uma fonte so, pra contagem nao mentir em relacao ao que a lista mostra e pro
    CSV nao exportar mais do que a tela deixou ver."""
    conds = [AuditLog.created_at >= ini, AuditLog.created_at < fim]

    if usuario and usuario.strip():
        # Busca nas COLUNAS congeladas (e-mail e nome do autor no dia do ato).
        # Procurar pelo nome ATUAL do cadastro daria o efeito perverso de sumir
        # com o historico de quem mudou de nome.
        p = f"%{_esc(usuario.strip())}%"
        conds.append(or_(AuditLog.user_email.ilike(p, escape="\\"),
                         AuditLog.usuario_nome.ilike(p, escape="\\")))
    if acao and acao.strip():
        # Prefixo: "cofre." traz a familia inteira, "cofre.reveal" traz so ela.
        conds.append(AuditLog.action.ilike(_esc(acao.strip()) + "%", escape="\\"))
    if modulo and modulo.strip():
        conds.append(_cond_modulo(modulo.strip()))
    if resultado and resultado.strip():
        conds.append(_cond_resultado(resultado.strip()))
    if municipio_id:
        conds.append(AuditLog.municipio_id == municipio_id)
    if sessao and sessao.strip():
        # Igualdade exata: e o que o indice parcial idx_audit_sessao atende, e o
        # valor vem da propria resposta (item.sessao.id), nunca digitado.
        conds.append(AuditLog.sessao_id == sessao.strip())
    if busca and busca.strip():
        p = f"%{_esc(busca.strip())}%"
        conds.append(or_(
            AuditLog.user_email.ilike(p, escape="\\"),
            AuditLog.usuario_nome.ilike(p, escape="\\"),
            AuditLog.action.ilike(p, escape="\\"),
            AuditLog.target_id.ilike(p, escape="\\"),
            AuditLog.alvo_nome.ilike(p, escape="\\"),
            AuditLog.ip.ilike(p, escape="\\"),
            AuditLog.http_path.ilike(p, escape="\\"),
            # details e JSONB: o CAST deixa a busca livre alcancar o sistema do
            # cofre, o e-mail tentado no login, o nome do token etc.
            cast(AuditLog.details, Text).ilike(p, escape="\\"),
        ))

    conds.extend(_cond_escopo(current))
    return conds


def _base_query(conds: list):
    """SELECT + LEFT JOIN so no municipio (para o NOME do recorte).

    LEFT e nao INNER de proposito: `audit_log.municipio_id` NAO tem FK (a trilha
    nao segue o ciclo de vida do alvo), entao um municipio removido do cadastro
    deixaria os eventos dele fora de um INNER JOIN — sumindo com a trilha
    justamente do que foi apagado.

    Nao ha join com `users`: nome e e-mail do autor estao congelados em coluna."""
    return (
        select(AuditLog, Municipio.nome)
        .outerjoin(Municipio, Municipio.id == AuditLog.municipio_id)
        .where(*conds)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    )


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
# Celula que COMECA com um destes e formula pro Excel/LibreOffice: `=cmd|...`
# num user-agent ou num nome de sistema forjado vira execucao na maquina de quem
# abrir o relatorio. Tab e CR entram na lista porque a planilha os come e passa a
# ler o proximo caractere como inicio da celula (OWASP CSV Injection).
_GATILHOS_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _celula_segura(valor) -> str:
    """Prefixa apostrofo no que a planilha executaria. O apostrofo faz a celula
    ser tratada como TEXTO — o dado continua inteiro e legivel, so nao roda."""
    if valor is None:
        return ""
    s = str(valor)
    if s[:1] in _GATILHOS_FORMULA:
        return "'" + s
    return s


def _rotulo_resultado(chave: str) -> str:
    for r in RESULTADOS:
        if r["key"] == chave:
            return r["label"]
    return chave


def _rotulo_severidade(chave: str) -> str:
    """So para o CSV. O JSON continua devolvendo a CHAVE (`critico`/`alerta`/
    `info`), que e o que a tela usa pra decidir a cor — trocar por rotulo ali
    quebraria a tela em silencio. Mas o arquivo entregue ao controle interno e
    lido por gente, e "critico" na coluna e jargao: vai "Sensível"."""
    for s in SEVERIDADES:
        if s["key"] == chave:
            return s["label"]
    return chave


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
# ATENCAO A ORDEM: as rotas literais (/catalogo, /exportar, /minha-atividade)
# TEM de vir antes de /{id}. O FastAPI casa na ordem de declaracao e /{id} com
# `int` engoliria "catalogo" devolvendo 422 em vez de servir o catalogo.

@router.get("/catalogo")
async def catalogo(current: User = Depends(get_current_user)):
    """Dicionario de modulos, acoes, resultados e severidades para a tela montar
    os filtros e as legendas. So autenticacao, SEM ensure_tela: e conteudo
    estatico (nenhum dado do cliente) e a tela "Minha atividade" — que qualquer
    usuario pode abrir — precisa das mesmas legendas."""
    # UNIAO com o catalogo didatico, e nao so `ACOES`: as familias que este
    # arquivo nao lista (documento.*, rm.*, gestao.*, bi.tela_link.*,
    # control.session_token.*, export.*) TEM de aparecer no seletor de acao,
    # senao o gestor abre o filtro, nao encontra "excluiu o documento" e conclui
    # que o sistema nao registra aquilo. `_regra_de` e a fonte unica do rotulo e
    # da severidade — aqui so montamos a lista.
    acoes = []
    for chave in sorted(set(ACOES) | set(CATALOGO_ACOES)):
        rotulo, severidade, _molde = _regra_de(chave)
        modulo = _modulo_de(chave)
        acoes.append({
            "key": chave, "rotulo": rotulo, "modulo": modulo,
            "modulo_rotulo": MODULO_LABEL.get(modulo, "Outros"),
            "severidade": severidade,
        })
    return {
        "modulos": [{"key": m["key"], "label": m["label"]} for m in MODULOS],
        "acoes": acoes,
        "resultados": RESULTADOS,
        "severidades": SEVERIDADES,
        "periodo_padrao_dias": JANELA_PADRAO_DIAS,
        "export_max_linhas": EXPORT_MAX_LINHAS,
        "per_page_max": PER_PAGE_MAX,
        "fuso": "America/Sao_Paulo",
        # Politica declarada pelo dono. Fica no catalogo pra tela poder explicar
        # ao usuario, em vez de a regra viver so na cabeca de quem a definiu.
        "retencao": {
            "seguranca_meses": 60,
            "navegacao_meses": 12,
            "poda_automatica": False,
            "texto": "A trilha é preservada por padrão: nada é apagado "
                     "automaticamente. A poda é um ato consciente, registrado na "
                     "própria trilha. Referência de retenção: 5 anos para acesso, "
                     "segurança e permissões; 12 meses para navegação.",
        },
        # ⚠️ TEXTO DE CONFORMIDADE — mudou porque o sistema passou a cumprir
        # mais, e a frase antiga ("o sistema não oferece nenhuma forma de
        # alterar") descrevia apenas a APLICACAO. Hoje a recusa esta no BANCO
        # (gatilho append-only) e ha uma corrente de selos conferivel na tela.
        #
        # A ultima frase e deliberada e nao deve ser suavizada: quem tem a senha
        # de administrador do banco pode derrubar a protecao. Um texto de
        # conformidade que promete "impossivel alterar" vira, numa pericia, uma
        # afirmacao falsa — e derruba junto a credibilidade do que e verdade.
        "aviso_imutabilidade": (
            "Os registros desta trilha são somente leitura. O sistema não oferece "
            "nenhuma tela, botão ou endereço que altere ou exclua um evento já "
            "gravado, e o próprio banco de dados recusa alteração, exclusão e "
            "limpeza da tabela. Cada registro leva um selo calculado dentro do "
            "banco a partir do registro anterior, formando uma corrente: mexer "
            "num registro antigo quebra o selo de todos os seguintes, e o botão "
            "«Verificar integridade» mostra exatamente onde. A corrente não é uma "
            "barreira absoluta — quem tiver a senha de administrador do banco de "
            "dados pode desligar a proteção e refazer os selos; o que ela "
            "garante é que nenhuma alteração passa despercebida."),
    }


@router.get("/minha-atividade")
async def minha_atividade(
    de: Optional[date] = Query(None, description="Início do período (AAAA-MM-DD)"),
    ate: Optional[date] = Query(None, description="Fim do período, inclusivo"),
    page: int = Query(1, ge=1),
    per_page: int = Query(PER_PAGE_PADRAO, ge=1, le=PER_PAGE_MAX),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """A PROPRIA trilha do usuario — sem precisar da tela `auditoria`.

    Direito de acesso do titular (LGPD, art. 18): a pessoa pode saber o que foi
    registrado sobre ela sem depender de um administrador. O recorte e por
    user_id (nao por e-mail) pra que trocar o e-mail de cadastro nao esconda nem
    revele historico de outra pessoa."""
    ini, fim, ini_d, fim_d = _janela(de, ate)
    conds = [AuditLog.created_at >= ini, AuditLog.created_at < fim,
             AuditLog.user_id == current.id]

    total = (await db.execute(
        select(func.count()).select_from(AuditLog).where(*conds))).scalar_one()
    rows = (await db.execute(
        _base_query(conds).limit(per_page).offset((page - 1) * per_page))).all()

    return {
        "items": [_montar_item(a, nome_m) for a, nome_m in rows],
        "total": total, "page": page, "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "periodo": {"de": ini_d.isoformat(), "ate": fim_d.isoformat()},
    }


@router.get("/exportar")
async def exportar(
    request: Request,
    de: Optional[date] = Query(None, description="Início do período (AAAA-MM-DD)"),
    ate: Optional[date] = Query(None, description="Fim do período, inclusivo"),
    usuario: Optional[str] = Query(None, description="Nome ou e-mail (parcial)"),
    acao: Optional[str] = Query(None, description="Chave da ação ou prefixo"),
    modulo: Optional[str] = Query(None, description="Chave do módulo"),
    municipio_id: Optional[int] = Query(None),
    resultado: Optional[str] = Query(None, description="sucesso | negado | erro | nao_informado"),
    sessao: Optional[str] = Query(None, description="Id de sessão (item.sessao.id)"),
    busca: Optional[str] = Query(None, description="Busca livre"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Exporta em CSV o MESMO recorte que a tela está mostrando.

    Tres cuidados que nao sao obvios:
      - BOM (\\ufeff) no inicio: sem ele o Excel abre o arquivo como ANSI e
        "Município" vira "MunicÃ­pio" — relatorio de auditoria ilegivel.
      - Separador ';': o Excel em pt-BR usa o separador de LISTA do sistema, que
        aqui e ponto-e-virgula; com virgula ele joga a linha toda numa celula.
      - Escape de formula: celula que comeca com = + - @ e executada pelo Excel
        ao abrir. Um user-agent ou um nome de sistema forjado viraria uma formula
        rodando na maquina do auditor. Prefixamos apostrofo (OWASP CSV
        Injection) — o dado continua visivel, so nao e mais executavel.

    A propria exportacao e auditada: baixar a trilha inteira e justamente o ato
    que nao pode ser o unico sem rastro."""
    ensure_tela(current, "auditoria")
    if municipio_id:
        ensure_municipio_access(current, municipio_id)
    ini, fim, ini_d, fim_d = _janela(de, ate)
    conds = _condicoes(ini=ini, fim=fim, usuario=usuario, acao=acao, modulo=modulo,
                       municipio_id=municipio_id, resultado=resultado, sessao=sessao,
                       busca=busca, current=current)

    # limit = teto + 1: descobre que truncou sem pagar um count(*) sobre o
    # periodo inteiro so pra decidir se avisa.
    rows = (await db.execute(_base_query(conds).limit(EXPORT_MAX_LINHAS + 1))).all()
    truncado = len(rows) > EXPORT_MAX_LINHAS
    if truncado:
        rows = rows[:EXPORT_MAX_LINHAS]

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    w.writerow([
        "ID do registro", "Data e hora (Brasília)", "Usuário", "E-mail", "Ação",
        "O que aconteceu", "Módulo", "Resultado", "Criticidade", "Município",
        "IP de origem", "Dispositivo", "Navegador", "Sistema", "Método", "Rota",
        "Sessão", "Tipo do alvo", "ID do alvo", "Nome do alvo", "Alterações",
        "Detalhes técnicos (JSON)", "User-Agent completo",
    ])
    for a, nome_m in rows:
        it = _montar_item(a, nome_m)
        alteracoes = "; ".join(f"{c['campo']}: {c['de']} → {c['para']}"
                               for c in it["alteracoes"])
        w.writerow([_celula_segura(x) for x in [
            # Coluna "Usuário": cai no rotulo quando nao ha nome congelado —
            # senao a linha de tentativa de invasao (que nao tem usuario) sai do
            # arquivo em branco, justo a que o auditor esta procurando.
            it["id"], it["quando"], it["usuario"]["nome"] or it["usuario"]["rotulo"],
            it["usuario"]["email"] or "",
            it["acao"], it["o_que_aconteceu"], it["modulo_rotulo"],
            it["resultado_rotulo"], _rotulo_severidade(it["severidade"]),
            (it["municipio"] or {}).get("nome") or "", it["origem"]["ip"],
            it["origem"]["dispositivo"], it["origem"]["navegador"], it["origem"]["sistema"],
            it["origem"]["metodo"] or "", it["origem"]["rota"] or "",
            (it["sessao"] or {}).get("id") or "",
            it["alvo"]["tipo"] or "", it["alvo"]["id"] or "", it["alvo"]["nome"] or "",
            alteracoes,
            json.dumps(it["detalhes"], ensure_ascii=False) if it["detalhes"] else "",
            it["origem"]["user_agent"],
        ]])
    if truncado:
        # Aviso DENTRO do arquivo: um CSV cortado em silencio vira prova de que
        # "nao houve mais nada" — exatamente o oposto do que aconteceu.
        w.writerow([])
        w.writerow([_celula_segura(
            f"*** ATENÇÃO: exportação INCOMPLETA. O teto do sistema é de "
            f"{EXPORT_MAX_LINHAS} linhas e o filtro selecionado tem mais que isso. "
            f"Foram exportados os {EXPORT_MAX_LINHAS} eventos MAIS RECENTES do "
            f"período. Reduza o período ou aplique filtros para obter o restante. ***"
        )])

    filtros = {"de": ini_d.isoformat(), "ate": fim_d.isoformat(), "usuario": usuario,
               "acao": acao, "modulo": modulo, "municipio_id": municipio_id,
               "resultado": resultado, "sessao": sessao, "busca": busca}
    # `alvo_nome` diz, em uma linha, O QUE saiu do sistema — e o que a auditoria
    # de LGPD procura primeiro. Sem ele o registro diria apenas "exportou", sem
    # volume nem periodo, e seria preciso abrir o detalhe pra ter ideia do dano.
    await registrar_critico(
        db, action="auditoria.exportar", user=current, request=request,
        target_type="audit_log", target_id=None, municipio_id=municipio_id,
        alvo_nome=(f"{len(rows)} evento(s) de {ini_d:%d/%m/%Y} a {fim_d:%d/%m/%Y}"
                   + (" — RECORTE TRUNCADO" if truncado else "")),
        details={"formato": "csv", "linhas": len(rows), "truncado": truncado,
                 "teto": EXPORT_MAX_LINHAS, "filtros": filtros},
    )

    agora = datetime.now(TZ_BR).strftime("%Y%m%d_%H%M%S")
    nome = f"auditoria_pactha_{ini_d:%Y-%m-%d}_a_{fim_d:%Y-%m-%d}_{agora}.csv"
    # "utf-8-sig" = UTF-8 COM BOM (U+FEFF no inicio). Escrito pelo codec, e nao
    # concatenando o caractere no fonte: BOM literal e invisivel — some num diff,
    # some numa normalizacao de arquivo, e o acento volta a quebrar sem aviso.
    dados = buf.getvalue().encode("utf-8-sig")
    return StreamingResponse(
        io.BytesIO(dados),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome}"',
                 "X-Auditoria-Linhas": str(len(rows)),
                 "X-Auditoria-Truncado": "1" if truncado else "0"},
    )


# ---------------------------------------------------------------------------
# Conferencia da corrente de selos (imutabilidade)
# ---------------------------------------------------------------------------
# Todo o texto que a tela mostra e montado AQUI, junto com as outras frases da
# auditoria. E a mesma regra da lista, do modal e do CSV: uma fonte so de
# palavras. Se o frontend escrevesse "trilha íntegra" por conta propria, um dia
# o servidor mudaria o criterio e a tela continuaria dizendo a frase antiga.

# Ressalva de HONESTIDADE, obrigatoria na resposta. O dono pediu trilha
# "imutavel"; o que o sistema entrega e append-only imposto pelo banco MAIS uma
# corrente de selos. Quem tem a senha de dono do banco derruba o gatilho e
# refaz a corrente inteira — a corrente nao IMPEDE isso, ela obriga o atalho a
# aparecer. Prometer "impossivel alterar" seria o tipo de frase de conformidade
# que, no dia de uma pericia, transforma um controle bom numa alegacao falsa.
RESSALVA_INTEGRIDADE = (
    "O que esta conferência prova: nenhum registro foi alterado, removido ou "
    "trocado de lugar depois de gravado. O sistema não tem nenhuma tela, botão "
    "ou rota que altere a trilha, e o próprio banco de dados recusa alteração, "
    "exclusão e limpeza da tabela. O que ela NÃO prova: quem tiver a senha de "
    "administrador do banco de dados pode desligar essa proteção e refazer os "
    "selos. A corrente de selos não impede esse cenário — ela obriga quem tentar "
    "a refazer TODOS os registros seguintes, e qualquer atalho aparece aqui."
)

# Rotulos das travas, para a tela mostrar o estado real do banco em vez de uma
# promessa fixa em texto.
_ROTULO_PROTECAO = [
    ("sela_insercao", "Selo automático em cada registro novo",
     "O banco calcula o selo sozinho, no momento da gravação. Nem a aplicação "
     "consegue escolher o valor."),
    ("bloqueia_alteracao", "Alteração recusada pelo banco",
     "Um UPDATE em qualquer registro da trilha é recusado com erro."),
    ("bloqueia_exclusao", "Exclusão recusada pelo banco",
     "Um DELETE é recusado com erro, exceto pelo caminho controlado de poda, "
     "que fica registrado na própria trilha."),
    ("bloqueia_limpeza", "Limpeza da tabela recusada",
     "Um TRUNCATE (apagar tudo de uma vez) é recusado com erro."),
]


def _numero(n: Optional[int]) -> str:
    """Milhar com ponto, como se escreve em portugues."""
    return f"{int(n or 0):,}".replace(",", ".")


def _registros(n: Optional[int]) -> str:
    """"1 registro" / "12.480 registros". Concordancia importa: a tela de
    auditoria e lida por controle interno e por vereador, e "conferimos os 1
    registros" e o tipo de detalhe que faz o leitor duvidar do resto."""
    return "1 registro" if int(n or 0) == 1 else f"{_numero(n)} registros"


def _protecoes_para_tela(prot: dict) -> dict:
    """Traduz o catalogo do Postgres em algo que um leigo lê.

    A lista de travas vem do banco e nao de constante: trava que alguem
    desligou tem de APARECER desligada. Uma tela que jura "exclusão bloqueada"
    lendo um texto fixo nao vale nada — ela diria a mesma coisa depois de o
    gatilho ser derrubado, que e exatamente o momento em que ela precisava
    avisar."""
    itens, alertas = [], []
    for chave, rotulo, explicacao in _ROTULO_PROTECAO:
        ativo = bool(prot.get(chave))
        itens.append({"chave": chave, "rotulo": rotulo, "ativo": ativo,
                      "explicacao": explicacao})
        if not ativo:
            alertas.append(f"A proteção «{rotulo}» NÃO está ativa neste banco de dados.")

    # Campo fora do selo é o ponto cego mais traiçoeiro deste painel: a
    # conferência diria "íntegra" e estaria certa — sobre os campos que ela
    # confere. Sem esta frase, o gestor leria "íntegra" como "o registro inteiro
    # está intacto", que é o que ele tem todo o direito de entender. O serviço
    # PROVA a lista contra o banco (apaga o campo e vê se o selo muda), então
    # aqui é só traduzir.
    fora = [str(c) for c in (prot.get("campos_fora_do_selo") or [])]
    if fora:
        alertas.append(
            "Há campo do registro que NÃO entra no selo: "
            + ", ".join(f"«{c}»" for c in fora)
            + ". Alteração nesses campos não é detectada pela conferência. "
              "Avise o suporte técnico — é defeito a corrigir, não sinal de "
              "que algo foi alterado.")

    papel = prot.get("papel") or {}
    separado = bool(papel.get("papel_separado"))
    # NAO e alerta: hoje ha um usuario so no banco, por decisao de infra que o
    # dono ainda nao tomou (item D do pedido — trocar o DATABASE_URL de um
    # cliente vivo pode trancar a aplicacao fora do banco). Vira NOTA: o estado
    # e dito, sem pintar de vermelho uma escolha consciente.
    nota_papel = (
        "A aplicação entra no banco com um usuário que não tem permissão de "
        "alterar nem de excluir esta tabela — a proteção existe em duas camadas."
        if separado else
        "A aplicação entra no banco com o usuário dono da tabela: a recusa de "
        "alteração e exclusão vem do gatilho, e não da permissão. Separar o "
        "papel do banco é uma melhoria já documentada, e depende de uma decisão "
        "de infraestrutura do dono."
    )
    return {
        "itens": itens,
        "alertas": alertas,
        "papel_separado": separado,
        "nota_papel": nota_papel,
        "gatilhos": prot.get("gatilhos") or [],
    }


def _texto_observacao(obs: dict) -> str:
    """Frase de uma observacao da conferencia (vãos explicados e afins).

    Vão explicado NAO e alarme: e a poda de retenção funcionando como o dono
    pediu — apagar com rastro. Mas também não pode sumir da tela: "faltam 249
    registros aqui, e foi fulano quem podou, no dia tal" é justamente o que o
    controle interno vai querer ver."""
    tipo = obs.get("tipo")
    evento = obs.get("evento_id")
    quando, _ = _quando(obs.get("quando")) if obs.get("quando") else ("—", None)
    quantos = (f"{_registros(obs['linhas'])}" if obs.get("linhas")
               else "Alguns registros")
    # A poda por prefixo (retenção de 12 meses da navegação) tira linhas
    # salpicadas: o mesmo ato deixa muitos vãos. A conferência já os soma; a
    # frase tem de dizer que foram vários, senão o gestor lê "um vão" e vai
    # procurar um buraco só.
    vaos = int(obs.get("vaos") or 1)
    trechos = "" if vaos <= 1 else f", em {_numero(vaos)} trechos"
    # Reconciliação por FAIXA é mais fraca que por SELO e não pode chegar à tela
    # com a mesma cara: ali a poda declarou ter deixado buracos naquele intervalo
    # de registros, e é o intervalo — não o selo de cada vão — que fecha a conta.
    por_faixa = obs.get("reconciliacao") == "faixa"

    # A ressalva é a mesma nos dois tipos de vão, e por isso mora numa variável:
    # duas redações do mesmo aviso divergem no dia em que alguém melhorar uma só.
    ressalva_faixa = (
        " Essa poda apagou registros salteados (por tipo de ação), então o que "
        "confere é a faixa de registros que ela declarou ter removido, e não o "
        "selo de cada vão." if por_faixa else "")

    if tipo == "vao_explicado":
        return (
            f"Entre o registro nº {obs.get('depois_de_id')} e o nº "
            f"{obs.get('antes_de_id')} há um vão{trechos}: {quantos.lower()} foram "
            f"apagados pela poda de retenção registrada no evento nº {evento}, "
            f"de {quando}. O vão está explicado — a própria poda ficou na trilha."
            + ressalva_faixa)
    if tipo == "inicio_apos_poda":
        return (
            f"A trilha começa no registro nº {obs.get('antes_de_id')} porque "
            f"{quantos.lower()} mais antigos foram apagados pela poda de retenção "
            f"registrada no evento nº {evento}, de {quando}. O vão está explicado."
            + ressalva_faixa)
    if tipo == "inicio_apos_vao":
        return (
            f"O registro mais antigo desta trilha (nº {obs.get('antes_de_id')}) "
            "aponta para um registro anterior que não está mais na tabela, e não "
            "há poda de retenção registrada que explique isso. Merece explicação: "
            "pode ser uma restauração de backup ou uma migração de banco — mas "
            "também pode ser remoção do início da trilha.")
    return str(obs)  # pragma: no cover - tipo novo nunca fica invisível


def _observacoes_para_tela(res: dict) -> list[str]:
    """As observações em português, e a conta do que não coube.

    A conferência tem teto de observações (uma poda por prefixo pode deixar
    milhares de vãos). Omitir em silêncio seria a tela mostrar menos do que foi
    encontrado sem dizer — exatamente o tipo de meia-verdade que este painel não
    pode dar."""
    frases = [_texto_observacao(o) for o in (res.get("observacoes") or [])]
    omitidas = int(res.get("observacoes_omitidas") or 0)
    if omitidas:
        frases.append(
            f"Há mais {_numero(omitidas)} observação(ões) do mesmo tipo que não "
            "estão listadas aqui, para a resposta não ficar impraticável. Elas "
            "não indicam divergência: a conferência parou apenas de descrevê-las "
            "uma a uma.")
    return frases


def _texto_divergencia(tipo: str, id_linha: int, quando: str,
                       id_anterior: Optional[int]) -> tuple[str, str]:
    """(o que significa, o que fazer) — em portugues de gente."""
    if tipo == audit_integridade.TIPO_CONTEUDO:
        significa = (
            f"O conteúdo do registro nº {id_linha}, de {quando}, não confere com "
            "o selo que o banco gravou no instante em que ele foi criado. Ou seja: "
            "esse registro foi ALTERADO depois de gravado."
        )
    elif tipo == audit_integridade.TIPO_ELO:
        anterior = f"nº {id_anterior}" if id_anterior else "o registro anterior"
        # A frase diz que a poda foi DESCARTADA como explicação, e não apenas
        # que há um vão: a conferência já procurou o evento de poda que fecharia
        # esse buraco e não achou. Sem essa linha, o gestor que acabou de rodar
        # uma poda legítima leria a tela como acusação.
        significa = (
            f"O registro nº {id_linha}, de {quando}, não se encaixa em {anterior}: "
            "ele aponta para um registro anterior diferente. Isso acontece quando "
            "um registro do meio da trilha é APAGADO ou quando a ordem é alterada. "
            "Não há poda de retenção registrada na trilha que explique esse vão."
        )
    elif tipo == audit_integridade.TIPO_SEM_SELO:
        significa = (
            f"O registro nº {id_linha}, de {quando}, foi gravado SEM selo. Ou ele "
            "é anterior à proteção e não foi alcançado pela conversão, ou foi "
            "gravado com a proteção desligada."
        )
    else:  # pragma: no cover - tipo novo sem tradução nunca fica em branco
        significa = f"O registro nº {id_linha}, de {quando}, não confere."

    fazer = (
        "Trate como incidente de segurança: NÃO apague nem edite nada, guarde "
        "esta tela, e verifique quem tem acesso de administrador ao banco de "
        "dados. Abra o registro nº {id} na lista para ver o que ele diz hoje."
    ).format(id=id_linha)
    return significa, fazer


def _texto_integridade(res: dict) -> dict:
    """Titulo, mensagem e tom a partir do veredito cru do serviço."""
    situacao = res["situacao"]
    quantos = _registros(res.get("conferidos"))
    de_txt, _ = _quando(res.get("primeiro_em"))
    ate_txt, _ = _quando(res.get("ultimo_em"))
    if res.get("primeiro_em") and res.get("ultimo_em"):
        faixa = f" (em {de_txt})" if de_txt == ate_txt else f" (de {de_txt} até {ate_txt})"
    else:
        faixa = ""
    parcial = res.get("modo") == audit_integridade.MODO_SOMENTE_ELO
    # Ressalva do modo degradado: sem a função de selo do banco dá para provar
    # que nada foi REMOVIDO, mas não que nada foi EDITADO. Dizer "íntegra" seco
    # nesse caso seria afirmar mais do que foi conferido.
    #
    # Duas causas, dois textos. "Não encontrei a função" e "a função existe e
    # não reproduz nem os selos mais antigos" pedem providências diferentes, e a
    # segunda NÃO pode sair com cara de trilha adulterada: o que ela indica é
    # divergência de fórmula entre o gatilho e a conferência.
    if not parcial:
        complemento = ""
    elif res.get("formula_nao_confere"):
        complemento = (
            " Atenção: nesta conferência foi possível checar apenas o "
            "encadeamento (nenhum registro removido ou fora de ordem). A função "
            "de selo do banco não reproduziu nem os selos mais antigos da "
            "trilha, o que indica um problema técnico na fórmula do selo — e "
            "não alteração de registro. Avise o suporte técnico.")
    else:
        complemento = (
            " Atenção: nesta conferência foi possível checar apenas o "
            "encadeamento (nenhum registro removido ou fora de ordem). A "
            "checagem do conteúdo de cada registro depende da função de selo do "
            "banco, que não foi encontrada — avise o suporte técnico.")

    if situacao == "indisponivel":
        return {
            "tom": "neutro",
            "titulo": "Conferência ainda não disponível",
            "mensagem": (
                "Este banco de dados ainda não tem as colunas de selo da trilha. "
                "Elas são criadas automaticamente na próxima subida da aplicação. "
                "Enquanto isso, a trilha continua sendo somente leitura pelo "
                "sistema — o que falta é a conferência, não a proteção."),
            "o_que_fazer": "Se a mensagem persistir depois de uma reinicialização, "
                           "avise o suporte técnico.",
        }
    if situacao == "vazia":
        return {"tom": "neutro", "titulo": "Nada a conferir",
                "mensagem": "A trilha de auditoria ainda não tem registros.",
                "o_que_fazer": None}
    if situacao == "nada_novo":
        return {"tom": "ok", "titulo": "Conferência concluída",
                "mensagem": "Não há registros novos depois do ponto já conferido: "
                            "a trilha foi percorrida até o fim." + complemento,
                "o_que_fazer": None}
    if situacao == "divergente":
        div = res["divergencia"]
        quando_txt, _ = _quando(div.get("quando"))
        significa, fazer = _texto_divergencia(
            div["tipo"], div["id"], quando_txt, div.get("id_anterior"))
        conferidos = int(res.get("conferidos") or 0)
        anteriores = ("" if conferidos == 0 else
                      "O registro anterior a ele confere. " if conferidos == 1 else
                      f"Os {quantos} anteriores a ele conferem. ")
        return {
            "tom": "critico",
            "titulo": f"Divergência encontrada no registro nº {div['id']}",
            "mensagem": anteriores + significa,
            "o_que_fazer": fazer,
        }
    if situacao == "parcial":
        return {
            "tom": "neutro",
            "titulo": f"Íntegra até o registro nº {res.get('ultimo_id')}",
            "mensagem": (
                f"Conferimos {quantos}{faixa} e todos conferem. A "
                "conferência parou antes do fim para não prender o sistema: ainda "
                "há registros mais novos. Clique novamente para continuar de onde "
                "parou." + complemento),
            "o_que_fazer": None,
        }
    return {
        "tom": "ok",
        "titulo": "Trilha íntegra" if not parcial else "Encadeamento íntegro",
        "mensagem": (
            f"Conferimos {quantos} da trilha{faixa}. Nenhum foi alterado, "
            "removido ou trocado de lugar depois de gravado." + complemento),
        "o_que_fazer": None,
    }


@router.get("/integridade")
async def verificar_integridade(
    request: Request,
    desde_id: Optional[int] = Query(
        None, ge=0, description="Continua a conferência a partir deste registro "
                                "(use o `continuar_de` da resposta anterior)"),
    max_linhas: Optional[int] = Query(
        None, ge=1, le=5_000_000, description="Teto de registros nesta chamada"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Refaz a corrente de selos e diz até onde a trilha está íntegra.

    COMO FUNCIONA. Cada linha da `audit_log` carrega o selo da linha anterior
    (`hash_anterior`) e o seu proprio (`hash`), calculado DENTRO do banco por um
    gatilho no momento da gravacao — nem a aplicacao escolhe o valor. Refazer a
    conta linha a linha responde tres perguntas de uma vez: alguem editou um
    registro? alguem apagou um do meio? algum registro entrou sem selo?

    ONDE A CONTA E FEITA. No BANCO, chamando a mesma funcao que o gatilho usa —
    ver `services/audit_integridade.py`. Reimplementar a formula em Python daria
    duas versoes da mesma verdade, e o sintoma da divergencia seria a tela
    gritando "adulterada" para uma trilha intacta.

    MEMORIA. Leitura em lotes com cursor por `id`: a memoria nao cresce com a
    tabela. Ha orcamento de tempo; estourando, a resposta e honesta ("íntegra
    até o registro N") e traz `continuar_de` para a proxima chamada.

    CUSTO DA CORRENTE, para constar: o selo de uma linha depende da anterior,
    entao as insercoes na `audit_log` passam a SERIALIZAR. No volume desta casa
    (centenas de eventos por dia) e irrelevante. O limite pratico e a ordem de
    algumas centenas de insercoes por segundo; se um dia o sistema chegar la, o
    caminho e quebrar a corrente por dia (uma corrente independente por data,
    ancorada no ultimo selo do dia anterior) — a prova continua valendo e as
    insercoes deixam de disputar a mesma ponta.

    GATE: mesma tela `auditoria` da listagem. Sem recorte por municipio, porque
    a corrente e uma so — e por isso a resposta identifica a linha divergente
    pelo NUMERO e nao pelo conteudo: para ler o que ela diz, o usuario abre o
    registro na lista, que ja aplica o recorte dele."""
    ensure_tela(current, "auditoria")

    res = await audit_integridade.conferir(
        db, desde_id=desde_id, max_linhas=max_linhas)
    texto = _texto_integridade(res)
    # O bloco `divergencia` leva so os FATOS. A explicacao e o "o que fazer" ja
    # sairam em `mensagem`/`o_que_fazer`, montados pela mesma funcao: repetir a
    # frase aqui faria a tela mostrar o mesmo paragrafo duas vezes conforme o
    # frontend escolhesse um campo ou outro.
    div = res.get("divergencia")
    if div:
        quando_txt, quando_iso = _quando(div.get("quando"))
        div = {
            "tipo": div["tipo"], "id": div["id"], "id_anterior": div.get("id_anterior"),
            "quando": quando_txt, "quando_iso": quando_iso,
            "acao": div.get("acao"),
            "acao_rotulo": _regra_de(div["acao"])[0] if div.get("acao") else None,
        }

    de_txt, de_iso = _quando(res.get("primeiro_em"))
    ate_txt, ate_iso = _quando(res.get("ultimo_em"))
    corpo = {
        "situacao": res["situacao"],
        **texto,
        "ressalva": RESSALVA_INTEGRIDADE,
        "conferidos": res["conferidos"],
        "faixa": {
            "do_id": res.get("primeiro_id"), "ate_id": res.get("ultimo_id"),
            "de": de_txt if res.get("primeiro_em") else None, "de_iso": de_iso,
            "ate": ate_txt if res.get("ultimo_em") else None, "ate_iso": ate_iso,
        },
        "completo": res["completo"],
        "continuar_de": res.get("continuar_de"),
        "modo": res.get("modo"),
        "formula_nao_confere": bool(res.get("formula_nao_confere")),
        "duracao_ms": res.get("duracao_ms"),
        "divergencia": div,
        "observacoes": _observacoes_para_tela(res),
        "protecoes": _protecoes_para_tela(res.get("protecoes") or {}),
        "conferido_em": datetime.now(TZ_BR).strftime("%d/%m/%Y %H:%M:%S"),
    }

    # A conferencia entra na propria trilha: "quem conferiu, quando, e o que
    # viu" e evidencia de monitoramento (ISO/IEC 27001, A.8.15/A.5.28) — e, se
    # alguem adulterar a trilha, o registro de que a divergencia FOI VISTA
    # naquele dia e o que amarra a linha do tempo do incidente.
    #
    # Porta de MELHOR ESFORCO, e nao a critica: aqui o produto e a RESPOSTA. Se
    # o INSERT do registro falhar, esconder do auditor que a trilha esta
    # adulterada seria trocar um problema grande por um catastrofico. A falha
    # fica no log da aplicacao (services/audit.py loga com `exception`).
    resumo = (f"{_numero(res['conferidos'])} registro(s) conferido(s) — "
              + {"integra": "íntegra", "parcial": "íntegra até aqui",
                 "vazia": "trilha vazia", "nada_novo": "nada novo desde a última",
                 "divergente": "DIVERGÊNCIA ENCONTRADA",
                 "indisponivel": "conferência indisponível"}.get(res["situacao"],
                                                                 res["situacao"]))
    await registrar(
        db, action="auditoria.verificar_integridade", user=current, request=request,
        target_type="audit_log", target_id=None, alvo_nome=resumo,
        # `erro` marca o desfecho que o auditor procura no filtro por resultado:
        # a conferencia que NAO deu certo. Nao e erro de execucao — e o alarme.
        resultado=("erro" if res["situacao"] in ("divergente", "indisponivel")
                   else "sucesso"),
        details={
            "situacao": res["situacao"], "modo": res.get("modo"),
            "conferidos": res["conferidos"], "completo": res["completo"],
            "do_id": res.get("primeiro_id"), "ate_id": res.get("ultimo_id"),
            "duracao_ms": res.get("duracao_ms"),
            # Quantos vaos de poda a conferencia teve de reconciliar. Numero que
            # cresce sozinho e sinal de que alguem anda podando com frequencia.
            "vaos_explicados": sum(1 for o in (res.get("observacoes") or [])
                                   if o.get("tipo", "").startswith(("vao_", "inicio_apos_poda"))),
            "divergencia": ({"tipo": div["tipo"], "id": div["id"]} if div else None),
            "protecoes": {c: bool((res.get("protecoes") or {}).get(c))
                          for c, _r, _e in _ROTULO_PROTECAO},
        },
    )
    return corpo


@router.get("")
async def listar(
    de: Optional[date] = Query(None, description="Início do período (AAAA-MM-DD)"),
    ate: Optional[date] = Query(None, description="Fim do período, inclusivo"),
    usuario: Optional[str] = Query(None, description="Nome ou e-mail (parcial)"),
    acao: Optional[str] = Query(None, description="Chave da ação ou prefixo (ex.: 'cofre.')"),
    modulo: Optional[str] = Query(None, description="Chave do módulo (ver /catalogo)"),
    municipio_id: Optional[int] = Query(None),
    resultado: Optional[str] = Query(None, description="sucesso | negado | erro | nao_informado"),
    sessao: Optional[str] = Query(None, description="Id de sessão: tudo que foi feito numa mesma entrada"),
    busca: Optional[str] = Query(None, description="Busca livre (e-mail, ação, IP, alvo, rota, detalhes)"),
    page: int = Query(1, ge=1),
    per_page: int = Query(PER_PAGE_PADRAO, ge=1, le=PER_PAGE_MAX),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Lista paginada da trilha, do mais recente para o mais antigo.

    Nao ha try/except devolvendo lista vazia: se a consulta falhar, o chamador
    recebe 500 e o handler global de main.py devolve `detail` com referencia de
    log. Trilha vazia e trilha quebrada precisam ser distinguiveis."""
    ensure_tela(current, "auditoria")
    if municipio_id:
        ensure_municipio_access(current, municipio_id)
    ini, fim, ini_d, fim_d = _janela(de, ate)
    conds = _condicoes(ini=ini, fim=fim, usuario=usuario, acao=acao, modulo=modulo,
                       municipio_id=municipio_id, resultado=resultado, sessao=sessao,
                       busca=busca, current=current)

    # A contagem NAO precisa do join de municipios: todo filtro cai em coluna da
    # propria audit_log (o join existe so pra buscar o NOME do municipio).
    total = (await db.execute(
        select(func.count()).select_from(AuditLog).where(*conds))).scalar_one()
    rows = (await db.execute(
        _base_query(conds).limit(per_page).offset((page - 1) * per_page))).all()

    return {
        "items": [_montar_item(a, nome_m) for a, nome_m in rows],
        "total": total, "page": page, "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "periodo": {"de": ini_d.isoformat(), "ate": fim_d.isoformat()},
        "export_max_linhas": EXPORT_MAX_LINHAS,
    }


@router.get("/{evento_id}")
async def detalhe(
    evento_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Um evento, com tudo — e o conteudo do modal.

    O escopo por municipio do usuario vale aqui tambem: sem isso, quem nao pode
    LISTAR o evento de outra prefeitura poderia le-lo adivinhando o id."""
    ensure_tela(current, "auditoria")
    conds = [AuditLog.id == evento_id, *_cond_escopo(current)]
    row = (await db.execute(_base_query(conds))).first()
    if row is None:
        raise HTTPException(404, "Evento de auditoria não encontrado")
    a, nome_m = row
    item = _montar_item(a, nome_m)
    item["imutavel"] = True   # a tela declara ao usuario que ninguem edita isto
    return item


