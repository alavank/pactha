"""
Conferencia da trilha imutavel — refaz a CORRENTE DE SELOS da `audit_log`.

O QUE E A CORRENTE. A migration de imutabilidade poe duas colunas em cada linha:
`hash_anterior` (o selo da linha imediatamente anterior) e `hash` (o selo desta
linha, calculado DENTRO do banco por um gatilho BEFORE INSERT, sobre o par
"selo anterior + conteudo desta linha"). Como cada selo depende do anterior,
mexer numa linha antiga invalida o selo dela E o de todas as seguintes.

O QUE ESTE MODULO PROVA — e o que NAO prova. Ele detecta:

    conteudo_alterado  o selo gravado nao bate com o selo recalculado a partir
                       do conteudo atual da linha -> alguem editou a linha;
    elo_quebrado       o `hash_anterior` de uma linha nao e o `hash` da linha
                       anterior -> alguem apagou ou reordenou linhas;
    sem_selo           linha gravada sem selo -> foi gravada com o gatilho
                       ausente/desligado (ou o backfill nao alcancou ela).

VAO EXPLICADO x VAO SEM EXPLICACAO. A poda de retencao (`audit_log_podar`, na
migration) APAGA linhas de proposito e deixa um vao: a primeira linha
sobrevivente continua apontando, em `hash_anterior`, para o selo da ultima linha
removida. Um vao desses e legitimo — e o proprio evento de poda, que a funcao
grava na trilha na MESMA transacao, guarda em `details.hash_ultimo_podado` o
selo que fecha o vao.

Entao, ao encontrar um elo quebrado, este modulo procura a poda que o explica
antes de acusar: casou, vira OBSERVACAO ("aqui houve uma poda registrada no
evento nº X") e a conferencia SEGUE; nao casou, e divergencia. Sem essa
reconciliacao, a primeira poda de retencao — um ato normal, pedido pelo dono —
deixaria a tela em alarme vermelho permanente, e o alarme que toca sempre e o
alarme que ninguem mais escuta. O inverso e o que da valor a tudo: vao SEM poda
que o explique e a assinatura de remocao por fora.

Ele NAO prova que ninguem com a senha de DONO do banco pode reescrever tudo:
quem derruba o gatilho e recalcula a corrente inteira nao aparece aqui. A
corrente nao IMPEDE, ela DENUNCIA o atalho — quem quiser mexer numa linha tem
de refazer todas as posteriores. Essa ressalva sobe para a tela de proposito
(routers/auditoria.py): texto de conformidade que promete mais do que o sistema
cumpre e pior que nao ter texto nenhum.

⚠️ NAO REIMPLEMENTAMOS A FORMULA DO SELO AQUI. O selo e calculado por uma funcao
SQL que a propria migration cria, e e ELA que este modulo chama (`{funcao}(a.*)`
por linha, dentro do banco). Uma segunda formula escrita em Python divergiria da
primeira no dia em que alguem acrescentasse uma coluna a `audit_log` — e o
sintoma seria a tela gritando "TRILHA ADULTERADA" para uma trilha intacta, que e
o pior defeito possivel aqui: alarme falso ensina o auditor a ignorar o alarme.

Por isso a funcao e DESCOBERTA por FORMA, e nao pelo nome: procuramos, no
catalogo do proprio Postgres, funcao de 1 argumento cujo tipo e o composto
`audit_log` e que devolve texto. Havendo mais de uma candidata (por exemplo, uma
que monta o payload e outra que sela), a escolhida e a que REPRODUZ os selos ja
gravados numa amostra — o criterio e o resultado, nao a convencao de nome.

MODO DEGRADADO, honesto: se nenhuma funcao for encontrada, ainda da para
conferir o ENCADEAMENTO (nenhuma linha removida ou reordenada) sem conferir o
CONTEUDO. Nesse caso o resultado sai marcado `somente_elo` e a tela diz que a
conferencia foi parcial — em vez de fingir sucesso ou devolver erro.

CUSTO. A leitura e em LOTES por `id`, com cursor: a memoria nao cresce com o
tamanho da tabela. O que cresce e o tempo — uma passada e O(n) com um sha256 por
linha. Ha orcamento de tempo: estourou, a resposta sai HONESTA ("integra ate a
linha N") com o cursor para continuar, em vez de segurar o worker por minutos.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("auditoria.integridade")

# Lote de leitura. 1.000 linhas com ~2 KB cada = ~2 MB por lote, por worker —
# constante, independente de a tabela ter mil ou dez milhoes de linhas.
LOTE_PADRAO = 1_000
LOTE_MAX = 5_000

# Orcamento de tempo de UMA chamada. Menor que o timeout do proxy do Next
# (`experimental.proxyTimeout`) de proposito: quem tem de decidir que a
# conferencia foi longe demais e este codigo, que sabe dizer ate onde conferiu —
# nao o proxy, que corta a resposta e devolve texto puro sem `detail`.
ORCAMENTO_PADRAO_S = 20.0

# Valores aceitos como "nao ha selo anterior" na PRIMEIRA linha da tabela. A
# migration pode representar a genese como NULL, string vazia ou uma constante
# de 64 zeros; as tres sao equivalentes e nenhuma delas e sinal de adulteracao.
_GENESE = frozenset({"", "0" * 64})

# O nome da funcao vem do catalogo do Postgres (`regproc`), nao de entrada do
# usuario — mas ele e interpolado em SQL, entao passa por uma peneira estreita
# antes. Defesa em profundidade: se um dia a origem mudar, a peneira continua.
_NOME_FUNCAO_OK = re.compile(r"^[a-z_][a-z0-9_$]*(\.[a-z_][a-z0-9_$]*)?$")

MODO_COMPLETO = "completa"
MODO_SOMENTE_ELO = "somente_elo"

# Teto de observacoes numa resposta. Uma poda POR PREFIXO (a retencao de 12
# meses da navegacao, que o dono pediu) apaga linhas SALPICADAS no meio das que
# ficam: cada trecho removido vira um vao, e podem ser dezenas de milhares deles.
# Vaos seguidos da MESMA poda ja se juntam num unico item (ver `_anotar_vao`),
# entao chegar aqui exige podas alternadas — mas o teto existe porque uma lista
# que cresce com a tabela quebra a promessa de memoria constante deste modulo, e
# uma resposta com 40.000 frases nao e lida por ninguem.
LIMITE_OBSERVACOES = 50

# Os tres achados possiveis. Sao chaves de fio (ASCII, sem acento): vao para
# JSON, para a tela e para o `details` da propria trilha.
TIPO_CONTEUDO = "conteudo_alterado"
TIPO_ELO = "elo_quebrado"
TIPO_SEM_SELO = "sem_selo"


# ---------------------------------------------------------------------------
# Nucleo PURO — percorre a corrente sem saber que existe banco
# ---------------------------------------------------------------------------
# Separado do SQL de proposito: e a parte que decide se a trilha esta intacta, e
# ela precisa ser testavel sem Postgres (aqui nao ha banco nos testes) e sem
# depender de qual foi a formula do selo.
@dataclass(frozen=True)
class Linha:
    """Uma linha da trilha, ja com o selo recalculado pelo banco."""
    id: int
    created_at: Optional[datetime]
    hash_anterior: Optional[str]
    selo: Optional[str]
    # None = nao foi recalculado (modo somente_elo). Diferente de "" (recalculou
    # e deu vazio), que seria divergencia.
    selo_calculado: Optional[str]
    action: Optional[str] = None


@dataclass(frozen=True)
class Divergencia:
    tipo: str
    id: int
    created_at: Optional[datetime] = None
    action: Optional[str] = None
    id_anterior: Optional[int] = None


def _norma(selo: Any) -> str:
    """Forma canonica do selo para COMPARAR.

    `strip()` porque a coluna e CHAR(64) e o Postgres preenche com espaco a
    direita quando o valor e mais curto; `lower()` porque `encode(...,'hex')`
    devolve minusculas mas nada obriga uma variante da funcao a fazer o mesmo.
    Comparar selo por igualdade crua faria "trilha adulterada" aparecer por
    diferenca de maiuscula — alarme falso e o defeito mais caro deste modulo."""
    return str(selo or "").strip().lower()


class Conferencia:
    """Estado do percurso pela corrente. Alimentada lote a lote.

    PARA no primeiro achado, de proposito: depois que a corrente quebra, tudo o
    que vem depois e consequencia daquele ponto, e listar mil "divergencias"
    derivadas esconderia a unica que importa — a primeira. E tambem limita o
    trabalho: trilha adulterada nao vira varredura da tabela inteira."""

    def __init__(self, *, inicio_absoluto: bool, selo_ancora: Optional[str] = None,
                 podas: Optional[dict[str, dict]] = None):
        # inicio_absoluto = comecamos na PRIMEIRA linha da tabela (nao ha elo
        # anterior a conferir). Numa continuacao, `selo_ancora` e o selo da
        # ultima linha ja conferida — sem ele, a emenda entre duas chamadas
        # seria justamente o ponto onde uma remocao passaria despercebida.
        self.inicio_absoluto = inicio_absoluto
        self.anterior_selo: Optional[str] = _norma(selo_ancora) if selo_ancora else None
        self.anterior_id: Optional[int] = None
        # Selo da ultima linha podada -> evento de poda que o registrou. Vem
        # pronto do banco (`carregar_podas`) para que esta classe continue pura:
        # a reconciliacao de vao e regra de leitura da corrente, e regra que so
        # roda com Postgres na frente e regra que ninguem testa.
        self.podas: dict[str, dict] = podas or {}
        self.conferidos = 0
        self.primeiro_id: Optional[int] = None
        self.ultimo_id: Optional[int] = None
        self.primeiro_em: Optional[datetime] = None
        self.ultimo_em: Optional[datetime] = None
        self.divergencia: Optional[Divergencia] = None
        # Observacoes sao ESTRUTURADAS, nao frases: quem escreve o portugues da
        # tela e o router, junto com o resto do texto da auditoria.
        self.observacoes: list[dict] = []
        # Quantas observacoes bateram no teto. Nao pode virar silencio: a tela
        # tem de dizer que houve mais do que ela esta mostrando.
        self.observacoes_omitidas = 0

    @property
    def integra(self) -> bool:
        return self.divergencia is None

    def _anotar(self, obs: dict) -> None:
        """Guarda uma observacao respeitando o teto (o excedente vira contagem)."""
        if len(self.observacoes) < LIMITE_OBSERVACOES:
            self.observacoes.append(obs)
        else:
            self.observacoes_omitidas += 1

    def _anotar_vao(self, poda: dict, antes_de_id: int) -> None:
        """Vao explicado, JUNTANDO os seguidos da mesma poda.

        Uma poda por prefixo deixa um vao a cada trecho removido — podem ser
        milhares, todos do MESMO ato. Listados um a um, eles enterrariam
        qualquer outra observacao e fariam a resposta crescer com o tamanho da
        tabela. Somados, viram a frase que o controle interno quer ler:
        "faltam 12.480 registros em 3.117 trechos, todos da poda nº 900"."""
        ultima = self.observacoes[-1] if self.observacoes else None
        if (ultima is not None and ultima.get("tipo") == "vao_explicado"
                and ultima.get("evento_id") == poda.get("evento_id")):
            ultima["vaos"] = int(ultima.get("vaos") or 1) + 1
            ultima["antes_de_id"] = antes_de_id
            return
        self._anotar({"tipo": "vao_explicado", "depois_de_id": self.anterior_id,
                      "antes_de_id": antes_de_id, "vaos": 1, **poda})

    def _poda_que_explica(self, selo_apontado: str, id_atual: int) -> Optional[dict]:
        """A poda registrada que fecha ESTE vao — ou None.

        SAO DUAS PROVAS, de forcas diferentes, e a distincao sai na resposta
        (`reconciliacao`) para que a tela nao apresente a fraca como se fosse a
        forte:

        POR SELO (forte). O vao aponta exatamente para o selo da ultima linha
        que a poda removeu (`hash_ultimo_podado`). E o caso da poda sem filtro:
        um corte limpo, um vao so. Aqui se exige que TODA a faixa removida caiba
        dentro deste vao — sem isso, bastaria reaproveitar um
        `hash_ultimo_podado` antigo para carimbar de "poda" uma remocao feita a
        mao.

        POR FAIXA (fraca, e por isso condicionada). A poda com `p_prefixos` — a
        retencao de 12 meses da navegacao, que o dono pediu — apaga linhas
        SALPICADAS: cada trecho vira um vao proprio e cada vao aponta para um
        selo DIFERENTE, sendo que a poda so guardou o ULTIMO. Nenhum desses vaos
        casa por selo, e sem este caminho a primeira poda de retencao por
        prefixo deixaria a tela em alarme vermelho permanente — impossivel de
        limpar, porque limpar exigiria UPDATE, que o banco recusa.

        O que a prova por faixa exige: a poda tem de ADMITIR que deixou buracos
        (`faixa_contigua` falso — a funcao do banco calcula isso na hora), a
        faixa declarada tem de se sobrepor a este vao, e o registro da poda tem
        de ser POSTERIOR a linha que se esta conferindo (uma poda nao explica
        vao que apareceu depois dela).

        O que ela NAO prova, e esta e a parte honesta: dentro de uma faixa que a
        propria poda declarou esburacada, nao da para distinguir um trecho que a
        poda removeu de um que alguem removeu a mao. O que segura esse flanco e
        que o evento de poda esta na corrente, imutavel, com autor, motivo e
        contagem — e uma poda inventada para acobertar remocao e, ela propria,
        um registro a explicar."""
        # 1. Prova por SELO.
        poda = self.podas.get(selo_apontado)
        if poda is not None and self._faixa_bate(poda, id_atual, estrita=True):
            return {**poda, "reconciliacao": "selo"}

        # 2. Prova por FAIXA, so para poda que se declarou esburacada.
        for cand in self.podas.values():
            # `is True` e nao truthy: poda registrada por uma versao anterior da
            # funcao do banco nao tem o campo (None), e nesse caso "nao sabemos"
            # nao pode virar "era contigua" — seria transformar falta de dado em
            # alarme, que e o defeito que este modulo mais evita.
            if cand.get("contigua") is True:
                continue
            if self._faixa_bate(cand, id_atual, estrita=False):
                return {**cand, "reconciliacao": "faixa"}
        return None

    def _faixa_bate(self, poda: dict, id_atual: int, *, estrita: bool) -> bool:
        """A faixa que a poda declarou ter removido cabe neste vao?"""
        menor, maior = poda.get("menor_id"), poda.get("maior_id")
        evento = poda.get("evento_id")
        # A poda e gravada na trilha DEPOIS do DELETE, entao o id do evento e
        # maior que o de qualquer linha que ela removeu — e maior ou igual ao da
        # sobrevivente que aponta para o vao (igual quando a poda alcancou a
        # ultima linha e o proprio evento virou o sobrevivente). Um evento
        # ANTERIOR a linha conferida nao pode explicar o vao dela: seria um
        # alibi emitido antes do fato.
        if evento is not None and evento < id_atual:
            return False
        if estrita:
            # Tudo o que a poda removeu tem de estar DENTRO deste vao.
            if maior is not None and maior >= id_atual:
                return False
            if (menor is not None and self.anterior_id is not None
                    and menor <= self.anterior_id):
                return False
            return True
        # Por faixa: exige os dois extremos declarados e sobreposicao com o vao
        # (a poda removeu ALGUMA linha entre a ultima conferida e esta).
        if menor is None or maior is None:
            return False
        if menor >= id_atual:
            return False
        if self.anterior_id is not None and maior <= self.anterior_id:
            return False
        return True

    def processar(self, linhas: Sequence[Linha]) -> bool:
        """Consome um lote. Devolve False quando deve parar (achou algo)."""
        for ln in linhas:
            if self.divergencia is not None:
                return False

            selo = _norma(ln.selo)
            anterior_declarado = _norma(ln.hash_anterior)

            if self.anterior_selo is None and self.inicio_absoluto and self.conferidos == 0:
                # Primeira linha da tabela: nao ha elo a conferir. Mas se ela
                # aponta para um selo anterior que NAO e a genese, ou havia
                # linhas antes dela (removidas), ou a conferencia comecou no
                # meio. Vira OBSERVACAO e nao divergencia: nao da para
                # distinguir os dois casos daqui, e acusar adulteracao sem
                # poder provar seria exatamente o alarme falso que este modulo
                # tenta nao dar.
                if anterior_declarado and anterior_declarado not in _GENESE:
                    poda = self._poda_que_explica(anterior_declarado, ln.id)
                    self._anotar(
                        {"tipo": "inicio_apos_poda", "antes_de_id": ln.id, **poda}
                        if poda else {"tipo": "inicio_apos_vao", "antes_de_id": ln.id}
                    )
            elif self.anterior_selo is not None and anterior_declarado != self.anterior_selo:
                # Vao: ou ha uma poda registrada que o explica, ou alguem removeu
                # linhas por fora. So o segundo caso e divergencia.
                poda = self._poda_que_explica(anterior_declarado, ln.id)
                if poda is None:
                    self.divergencia = Divergencia(
                        tipo=TIPO_ELO, id=ln.id, created_at=ln.created_at,
                        action=ln.action, id_anterior=self.anterior_id,
                    )
                    return False
                self._anotar_vao(poda, ln.id)

            if not selo:
                self.divergencia = Divergencia(
                    tipo=TIPO_SEM_SELO, id=ln.id, created_at=ln.created_at,
                    action=ln.action, id_anterior=self.anterior_id,
                )
                return False

            # `is not None` e nao truthy: no modo somente_elo o recalculo nem
            # aconteceu (None) e nao ha o que comparar; um recalculo que deu
            # string vazia, esse sim, e divergencia.
            if ln.selo_calculado is not None and _norma(ln.selo_calculado) != selo:
                self.divergencia = Divergencia(
                    tipo=TIPO_CONTEUDO, id=ln.id, created_at=ln.created_at,
                    action=ln.action, id_anterior=self.anterior_id,
                )
                return False

            self.conferidos += 1
            if self.primeiro_id is None:
                self.primeiro_id, self.primeiro_em = ln.id, ln.created_at
            self.ultimo_id, self.ultimo_em = ln.id, ln.created_at
            self.anterior_selo, self.anterior_id = selo, ln.id

        return True


# ---------------------------------------------------------------------------
# Camada de banco
# ---------------------------------------------------------------------------
async def colunas_de_selo(db: AsyncSession) -> dict[str, bool]:
    """As colunas do incremento existem neste banco?

    Consultado em vez de assumido: a API sobe e roda as migrations no boot, mas
    o runner ENGOLE erro (services/startup.py). Um banco em que a migration
    falhou continua servindo a tela; o certo e a conferencia dizer "ainda nao
    disponivel" em vez de estourar com "column does not exist".

    Pelo catalogo e nao por `information_schema.columns`: aquele filtra so por
    `table_name` e responderia por uma `audit_log` de OUTRO schema. Aqui
    `to_regclass` resolve exatamente a tabela que a aplicacao enxerga, que e a
    mesma resolucao usada nas consultas de gatilho e de permissao logo abaixo —
    tres respostas sobre objetos diferentes nao formariam um diagnostico."""
    sql = text(
        "SELECT a.attname FROM pg_catalog.pg_attribute a "
        "WHERE a.attrelid = to_regclass('audit_log') "
        "  AND a.attname IN ('hash', 'hash_anterior') "
        "  AND a.attnum > 0 AND NOT a.attisdropped"
    )
    achadas = {r[0] for r in (await db.execute(sql)).all()}
    return {"hash": "hash" in achadas, "hash_anterior": "hash_anterior" in achadas}


async def descobrir_funcao_selo(db: AsyncSession) -> tuple[Optional[str], int, int]:
    """Acha, no catalogo do Postgres, a funcao que sela uma linha de `audit_log`.

    Devolve `(funcao, acertos, tamanho_da_amostra)`.

    Por FORMA e nao por nome: 1 argumento do tipo composto `audit_log`,
    devolvendo texto. Gatilho nao entra nesse filtro (funcao de gatilho nao tem
    argumento declarado e devolve `trigger`), entao nao ha como confundir.

    Havendo mais de uma candidata, decide o RESULTADO: usamos a que reproduz os
    selos ja gravados numa amostra. E o unico criterio que nao depende de
    convencao de nome combinada entre dois arquivos que ninguem le junto.

    Os `acertos` sobem junto porque quem chama precisa deles para uma decisao
    que nao e de nomenclatura, e sim de honestidade — ver `conferir`."""
    sql = text(
        """
        SELECT p.oid::regproc::text AS chamada
        FROM pg_catalog.pg_proc p
        WHERE p.pronargs = 1
          AND p.proargtypes[0] = to_regtype('audit_log')
          AND p.prorettype IN (to_regtype('text'), to_regtype('character'),
                               to_regtype('character varying'))
          AND pg_catalog.pg_function_is_visible(p.oid)
        ORDER BY (p.proname LIKE '%hash%' OR p.proname LIKE '%selo%') DESC, p.proname
        """
    )
    candidatas = [r[0] for r in (await db.execute(sql)).all()
                  if _NOME_FUNCAO_OK.match(r[0] or "")]
    if not candidatas:
        return None, 0, 0

    melhor, melhor_acertos, melhor_amostra = None, -1, 0
    for nome in candidatas:
        acertos, amostrados = await _acertos_na_amostra(db, nome)
        if acertos > melhor_acertos:
            melhor, melhor_acertos, melhor_amostra = nome, acertos, amostrados

    # So `-1` desqualifica — e a candidata que ESTOUROU ao ser chamada
    # (assinatura compativel, corpo esperando outra coisa). Zero acerto nao
    # desqualifica aqui; quem decide o que fazer com isso e `conferir`.
    if melhor_acertos < 0:
        return None, 0, 0
    return melhor, melhor_acertos, melhor_amostra


async def _acertos_na_amostra(db: AsyncSession, funcao: str,
                              tamanho: int = 5) -> tuple[int, int]:
    """(acertos, linhas amostradas) — quanto a funcao reproduz do que ja existe.

    Amostra pelas linhas MAIS ANTIGAS: sao as com menos chance de serem o alvo
    de uma adulteracao recente, e as que existem em qualquer banco.

    `(-1, 0)` = a candidata estourou ao ser chamada."""
    sql = text(
        f"""
        SELECT count(*) FILTER (WHERE lower(btrim({funcao}(a.*))) = lower(btrim(a."hash"))),
               count(*)
        FROM audit_log a
        WHERE a."hash" IS NOT NULL
          AND a.id IN (SELECT id FROM audit_log WHERE "hash" IS NOT NULL
                       ORDER BY id LIMIT :n)
        """
    )
    try:
        # SAVEPOINT: sem ele, uma candidata que estoura deixa a transacao em
        # estado abortado e TODA consulta seguinte falha com "current
        # transaction is aborted" — a conferencia morreria por causa de uma
        # funcao alheia que so estava sendo testada.
        async with db.begin_nested():
            linha = (await db.execute(sql, {"n": tamanho})).first()
        return (int(linha[0] or 0), int(linha[1] or 0)) if linha else (0, 0)
    except Exception:
        # Candidata que estoura (assinatura compativel mas corpo que espera
        # outra coisa) simplesmente perde a disputa; nao derruba a conferencia.
        logger.warning("Candidata a funcao de selo falhou na amostra: %s", funcao,
                       exc_info=True)
        return -1, 0


# Bits de `pg_trigger.tgtype` (src/include/catalog/pg_trigger.h). Lidos aqui em
# vez de fazer regex em `pg_get_triggerdef`: o texto da definicao muda com a
# versao do Postgres, os bits nao mudam desde sempre.
_TG_ROW, _TG_BEFORE, _TG_INSERT, _TG_DELETE, _TG_UPDATE, _TG_TRUNCATE = 1, 2, 4, 8, 16, 32


async def campos_fora_do_selo(db: AsyncSession, funcao: Optional[str]) -> list[str]:
    """Colunas de `audit_log` que NAO entram no selo — provado, nao lido.

    O PONTO CEGO QUE ISTO FECHA. A corrente prova que o conteudo selado nao
    mudou. Se um campo ficar de FORA da conta do selo, ele pode ser reescrito a
    vontade sem quebrar elo nenhum, e a conferencia continua dizendo "íntegra" —
    a prova provaria um subconjunto e a tela nao saberia dizer qual. Nao e
    hipotese remota: a lista de colunas do selo e FIXA de proposito (para uma
    coluna nova nao invalidar todos os selos antigos), entao acrescentar coluna a
    `audit_log` e deixar ela de fora do selo e o caminho natural — e silencioso.

    COMO SE PROVA, sem reimplementar nada. Pega-se uma linha real, apaga-se UM
    campo dela e pergunta-se ao banco o selo das duas versoes. Se o selo nao
    mudar, aquele campo nao entra na conta. E o mesmo raciocinio da conferencia
    (perguntar ao banco, nunca refazer a formula em Python) aplicado a cobertura
    em vez do conteudo.

    LIMITES, ditos: so da para testar campo que tenha valor na amostra — campo
    nulo em todas as linhas amostradas nao aparece nem como coberto nem como
    descoberto, porque apagar o que ja esta apagado nao muda nada. Por isso a
    amostra sao as linhas MAIS RECENTES: sao as mais preenchidas (as antigas
    vieram de antes das colunas de detalhe existirem).

    `hash` fica fora da lista porque ele e o RESULTADO; `hash_anterior` entra,
    e tem de dar coberto — ele e o elo, e se nao entrasse no selo daria para
    reapontar uma linha para outro antecessor sem quebrar nada."""
    # Mesma peneira de `descobrir_funcao_selo`: o nome vem do catalogo do
    # Postgres, mas e interpolado em SQL. Repetida aqui porque esta funcao e
    # chamavel por fora e nao pode depender de quem a chama ter peneirado antes.
    if not funcao or not _NOME_FUNCAO_OK.match(funcao):
        return []
    sql = text(
        f"""
        WITH amostra AS (
            SELECT to_jsonb(a) AS linha FROM audit_log a
             WHERE a."hash" IS NOT NULL ORDER BY a.id DESC LIMIT :n
        ),
        colunas AS (
            SELECT att.attname, att.attnum
              FROM pg_catalog.pg_attribute att
             WHERE att.attrelid = to_regclass('audit_log')
               AND att.attnum > 0 AND NOT att.attisdropped
               AND att.attname <> 'hash'
        )
        SELECT c.attname
          FROM colunas c JOIN amostra s ON s.linha ->> c.attname IS NOT NULL
         GROUP BY c.attname, c.attnum
        HAVING NOT bool_or(
            {funcao}(jsonb_populate_record(NULL::audit_log, s.linha))
            IS DISTINCT FROM
            {funcao}(jsonb_populate_record(
                NULL::audit_log, jsonb_set(s.linha, ARRAY[c.attname], 'null'::jsonb)))
        )
         ORDER BY c.attnum
        """
    )
    try:
        # SAVEPOINT pelo mesmo motivo da amostra de candidatas: uma funcao que
        # estoure aqui nao pode abortar a transacao da conferencia inteira.
        async with db.begin_nested():
            linhas = (await db.execute(sql, {"n": 5})).all()
        return [r[0] for r in linhas]
    except Exception:
        # Falha aqui e diagnostico perdido, nao conferencia errada: devolve vazio
        # e avisa no log. Inventar "esta tudo coberto" seria pior; inventar
        # "esta tudo descoberto" encheria a tela de alarme falso.
        logger.warning("Nao foi possivel provar a cobertura do selo", exc_info=True)
        return []


async def ler_protecoes(db: AsyncSession, funcao: Optional[str] = None) -> dict:
    """Estado das travas que o banco impoe HOJE, lido do catalogo.

    Existe porque a corrente de selos tem um ponto cego: ela denuncia a linha
    ALTERADA, mas nao denuncia o gatilho DESLIGADO — enquanto ninguem usar a
    brecha, tudo confere. Ler o catalogo fecha esse vao: se a trava sumiu, a
    conferencia diz isso na mesma resposta, antes de haver dano.

    O bloco de papel do banco e o item (D) do pedido: enquanto a aplicacao usar
    o usuario dono da tabela, ela CONTINUA podendo alterar e apagar — o gatilho
    e que recusa. Dizer isso na cara e o que separa conformidade de encenacao."""
    gatilhos: list[dict] = []
    try:
        linhas = (await db.execute(text(
            "SELECT t.tgname, t.tgtype, t.tgenabled "
            "FROM pg_catalog.pg_trigger t "
            "WHERE t.tgrelid = to_regclass('audit_log') AND NOT t.tgisinternal "
            "ORDER BY t.tgname"
        ))).all()
    except Exception:
        logger.warning("Nao foi possivel ler os gatilhos de audit_log", exc_info=True)
        linhas = []

    sela = bloq_update = bloq_delete = bloq_truncate = False
    for nome, tgtype, tgenabled in linhas:
        tipo = int(tgtype or 0)
        # 'D' = DISABLE. Qualquer outro estado ('O' origem, 'A' always,
        # 'R' replica) dispara em uso normal da aplicacao.
        ativo = (tgenabled or "O") != "D"
        eventos = [nome_ev for bit, nome_ev in (
            (_TG_INSERT, "INSERT"), (_TG_UPDATE, "UPDATE"),
            (_TG_DELETE, "DELETE"), (_TG_TRUNCATE, "TRUNCATE"),
        ) if tipo & bit]
        antes = bool(tipo & _TG_BEFORE)
        if ativo:
            if "INSERT" in eventos and antes:
                sela = True
            bloq_update = bloq_update or "UPDATE" in eventos
            bloq_delete = bloq_delete or "DELETE" in eventos
            bloq_truncate = bloq_truncate or "TRUNCATE" in eventos
        gatilhos.append({
            "nome": nome,
            "eventos": eventos,
            "momento": "antes" if antes else "depois",
            "por_linha": bool(tipo & _TG_ROW),
            "ativo": ativo,
        })

    papel: dict = {}
    try:
        linha = (await db.execute(text(
            """
            SELECT current_user,
                   has_table_privilege(current_user, to_regclass('audit_log'), 'UPDATE'),
                   has_table_privilege(current_user, to_regclass('audit_log'), 'DELETE'),
                   pg_catalog.pg_get_userbyid(c.relowner),
                   COALESCE((SELECT r.rolsuper FROM pg_catalog.pg_roles r
                             WHERE r.rolname = current_user), false)
            FROM pg_catalog.pg_class c
            WHERE c.oid = to_regclass('audit_log')
            """
        ))).first()
        if linha:
            usuario, pode_alterar, pode_excluir, dono, superusuario = linha
            papel = {
                "usuario": usuario,
                "dono_da_tabela": dono,
                "superusuario": bool(superusuario),
                # `has_table_privilege` responde pelo GRANT, nao pelo gatilho: e
                # exatamente a distincao que interessa aqui.
                "pode_alterar_por_permissao": bool(pode_alterar),
                "pode_excluir_por_permissao": bool(pode_excluir),
                "papel_separado": not (pode_alterar or pode_excluir),
            }
    except Exception:
        logger.warning("Nao foi possivel ler o papel do banco", exc_info=True)

    return {
        "gatilhos": gatilhos,
        "sela_insercao": sela,
        "bloqueia_alteracao": bloq_update,
        "bloqueia_exclusao": bloq_delete,
        "bloqueia_limpeza": bloq_truncate,
        "papel": papel,
        # Campo que nao entra no selo pode ser reescrito sem quebrar a corrente.
        # Lista vazia e o estado normal — e e o unico estado em que a frase
        # "nenhum registro foi alterado" vale para o registro INTEIRO.
        "campos_fora_do_selo": await campos_fora_do_selo(db, funcao),
    }


def _sql_lote(funcao: Optional[str]) -> str:
    """SELECT do lote. O selo e recalculado DENTRO do banco, linha a linha.

    `a.*` passa a linha inteira para a funcao — assim uma coluna nova entra no
    selo sem que este arquivo precise saber que ela existe."""
    calculado = f"{funcao}(a.*)" if funcao else "NULL::text"
    return (
        'SELECT a.id, a.created_at, a."hash_anterior", a."hash", '
        f'{calculado} AS selo_calculado, a.action '
        "FROM audit_log a WHERE a.id > :cursor ORDER BY a.id LIMIT :lote"
    )


# Grafias do evento de poda. `auditoria.poda` e o que a funcao do banco grava;
# as outras duas ja existiam no catalogo didatico. Ler as tres e o que impede
# que uma poda registrada com o nome "errado" apareca como remocao clandestina.
_SQL_PODAS = """
    SELECT a.id, a.created_at,
           lower(btrim(a.details->>'hash_ultimo_podado')) AS selo,
           CASE WHEN a.details->>'linhas_removidas'  ~ '^[0-9]+$'
                THEN (a.details->>'linhas_removidas')::bigint END,
           CASE WHEN a.details->>'menor_id_removido' ~ '^[0-9]+$'
                THEN (a.details->>'menor_id_removido')::bigint END,
           CASE WHEN a.details->>'maior_id_removido' ~ '^[0-9]+$'
                THEN (a.details->>'maior_id_removido')::bigint END,
           -- Tri-estado de proposito: true (corte limpo), false (assumidamente
           -- esburacada) e NULL (poda gravada por uma versao da funcao que
           -- ainda nao calculava isto). `jsonb_typeof` evita que a string
           -- "false" de um `details` forjado a mao vire booleano.
           CASE WHEN jsonb_typeof(a.details->'faixa_contigua') = 'boolean'
                THEN (a.details->>'faixa_contigua')::boolean END
      FROM audit_log a
     WHERE (a.action LIKE 'auditoria.poda%' OR a.action = 'audit.prune')
       AND a.details->>'hash_ultimo_podado' IS NOT NULL
     ORDER BY a.id
"""


async def carregar_podas(db: AsyncSession) -> dict[str, dict]:
    """Selo da ultima linha podada -> evento de poda, para reconciliar os vaos.

    Sao pouquissimas linhas (uma por poda executada na vida do sistema), entao
    carregar tudo de uma vez custa menos que uma consulta por vao — e mantem a
    classe que percorre a corrente sem acesso a banco.

    O CAST e defensivo (`~ '^[0-9]+$'`) porque `details` e JSONB livre: uma
    linha `auditoria.poda` inserida a mao com lixo nesses campos derrubaria a
    conferencia inteira num cast direto, e derrubar a conferencia e o que um
    adversario gostaria de conseguir."""
    try:
        linhas = (await db.execute(text(_SQL_PODAS))).all()
    except Exception:
        # Sem as podas a conferencia ainda roda; ela so fica mais SEVERA (um vao
        # legitimo vira divergencia). Falhar fechado, com aviso no log.
        logger.warning("Nao foi possivel carregar os eventos de poda", exc_info=True)
        return {}
    podas: dict[str, dict] = {}
    for pid, quando, selo, linhas_removidas, menor, maior, contigua in linhas:
        if not selo:
            continue
        podas[selo] = {"evento_id": pid, "quando": quando,
                       "linhas": int(linhas_removidas) if linhas_removidas else None,
                       "menor_id": int(menor) if menor else None,
                       "maior_id": int(maior) if maior else None,
                       "contigua": None if contigua is None else bool(contigua)}
    return podas


async def _selo_ancora(db: AsyncSession, desde_id: int) -> Optional[str]:
    """Selo da ultima linha ATE `desde_id` — a emenda de uma continuacao."""
    linha = (await db.execute(text(
        'SELECT a."hash" FROM audit_log a WHERE a.id <= :ate '
        "ORDER BY a.id DESC LIMIT 1"
    ), {"ate": desde_id})).first()
    return linha[0] if linha else None


async def conferir(
    db: AsyncSession,
    *,
    desde_id: Optional[int] = None,
    lote: int = LOTE_PADRAO,
    max_linhas: Optional[int] = None,
    orcamento_s: float = ORCAMENTO_PADRAO_S,
) -> dict:
    """Percorre a trilha e devolve o veredito CRU (sem texto de tela).

    A traducao para portugues de leigo fica no router, junto com as outras
    frases da auditoria: uma fonte so de texto, como ja vale para a lista, o
    modal e o CSV."""
    lote = max(1, min(int(lote or LOTE_PADRAO), LOTE_MAX))
    inicio = time.monotonic()

    colunas = await colunas_de_selo(db)
    if not (colunas["hash"] and colunas["hash_anterior"]):
        # Devolve o MESMO conjunto de chaves do caminho normal: quem consome
        # (router e, depois, a tela) nao pode ter de saber que este caminho e
        # mais pobre — chave faltando vira KeyError na resposta de erro, que e
        # o momento em que menos se pode falhar.
        return {
            "situacao": "indisponivel",
            "motivo": "sem_colunas",
            "modo": None,
            "funcao_selo": None,
            "conferidos": 0,
            "primeiro_id": None, "ultimo_id": None,
            "primeiro_em": None, "ultimo_em": None,
            "completo": False,
            "continuacao": bool(desde_id),
            "esgotou_tempo": False,
            "formula_nao_confere": False,
            "continuar_de": None,
            "observacoes": [],
            "observacoes_omitidas": 0,
            "divergencia": None,
            "protecoes": await ler_protecoes(db),
            "duracao_ms": int((time.monotonic() - inicio) * 1000),
        }

    funcao, acertos, amostrados = await descobrir_funcao_selo(db)

    # ⚠️ TRAVA CONTRA O ALARME FALSO SISTEMICO. Se a funcao encontrada nao
    # reproduz NEM UM dos selos mais antigos da trilha, o que ha e divergencia
    # de FORMULA — por exemplo, um selo que inclui a propria coluna `hash` no
    # calculo (no gatilho BEFORE INSERT ela ainda e nula; na linha ja gravada,
    # nao) — e nao adulteracao. Seguir em frente marcaria TODA a trilha como
    # adulterada, que e o pior desfecho possivel: alarme que toca sempre e
    # alarme que ninguem mais escuta.
    #
    # O risco do outro lado e estreito e esta declarado: so escapa quem
    # adulterar TODAS as linhas mais antigas da amostra. Um unico acerto ja
    # devolve a conferencia ao modo completo, e ai qualquer linha mexida
    # aparece.
    formula_nao_confere = bool(funcao and amostrados > 0 and acertos == 0)
    if formula_nao_confere:
        logger.error(
            "Funcao de selo %s nao reproduz nenhum dos %d selos amostrados: a "
            "conferencia caiu para somente_elo em vez de acusar a trilha inteira.",
            funcao, amostrados,
        )
        funcao = None

    modo = MODO_COMPLETO if funcao else MODO_SOMENTE_ELO
    if funcao is None and not formula_nao_confere:
        logger.warning(
            "Conferencia de integridade sem funcao de selo no banco: so o "
            "encadeamento sera conferido."
        )

    cursor = int(desde_id or 0)
    continuacao = cursor > 0
    ancora = await _selo_ancora(db, cursor) if continuacao else None
    # Sem ancora nao existe linha ANTES do cursor — logo estamos no comeco
    # absoluto da tabela, mesmo que o chamador tenha mandado um `desde_id`.
    conf = Conferencia(inicio_absoluto=(ancora is None), selo_ancora=ancora,
                       podas=await carregar_podas(db))

    sql = text(_sql_lote(funcao))
    continuar = True
    esgotou_tempo = False
    restam = None if max_linhas is None else max(1, int(max_linhas))

    while continuar:
        tamanho = lote if restam is None else min(lote, restam)
        linhas = (await db.execute(sql, {"cursor": cursor, "lote": tamanho})).all()
        if not linhas:
            break
        cursor = linhas[-1][0]
        continuar = conf.processar([
            Linha(id=r[0], created_at=r[1], hash_anterior=r[2], selo=r[3],
                  selo_calculado=r[4], action=r[5])
            for r in linhas
        ])
        if restam is not None:
            restam -= len(linhas)
            if restam <= 0:
                break
        if len(linhas) < tamanho:
            break
        if time.monotonic() - inicio > orcamento_s:
            esgotou_tempo = True
            break

    # `completo` so pergunta se sobrou linha DEPOIS da ultima conferida — um
    # EXISTS por indice, e nao um count(*) da tabela toda so para preencher um
    # numero na tela.
    faltam = False
    if conf.integra and conf.ultimo_id is not None:
        faltam = bool((await db.execute(text(
            "SELECT EXISTS(SELECT 1 FROM audit_log WHERE id > :ultimo)"
        ), {"ultimo": conf.ultimo_id})).scalar_one())

    if conf.divergencia is not None:
        situacao = "divergente"
    elif conf.conferidos == 0:
        # Numa CONTINUACAO isso quer dizer "nao sobrou nada depois do cursor",
        # e nao "a trilha esta vazia". Confundir os dois faria a tela anunciar
        # trilha sem registros ao usuario que acabou de conferir a trilha
        # inteira em duas etapas.
        situacao = "nada_novo" if continuacao else "vazia"
    elif faltam:
        situacao = "parcial"
    else:
        situacao = "integra"

    div = conf.divergencia
    return {
        "situacao": situacao,
        "modo": modo,
        "funcao_selo": funcao,
        "conferidos": conf.conferidos,
        "primeiro_id": conf.primeiro_id,
        "ultimo_id": conf.ultimo_id,
        "primeiro_em": conf.primeiro_em,
        "ultimo_em": conf.ultimo_em,
        # "completo" = chegou ao fim da tabela. Estourar o orcamento de tempo
        # EXATAMENTE na ultima linha nao torna a conferencia incompleta — o que
        # define e sobrar linha depois, nao o cronometro.
        "completo": situacao in ("integra", "vazia", "nada_novo"),
        "continuacao": continuacao,
        "esgotou_tempo": esgotou_tempo,
        # Sinaliza para a tela que o modo degradado NAO e "falta a funcao no
        # banco" e sim "a funcao existe e nao bate": e defeito tecnico a
        # corrigir, com texto proprio, e nao um recado para o usuario ignorar.
        "formula_nao_confere": formula_nao_confere,
        "continuar_de": conf.ultimo_id if faltam else None,
        "observacoes": list(conf.observacoes),
        # Quantas nao couberam no teto. Sai como numero e nao como frase: quem
        # escreve o portugues e o router.
        "observacoes_omitidas": conf.observacoes_omitidas,
        "divergencia": None if div is None else {
            "tipo": div.tipo,
            "id": div.id,
            "quando": div.created_at,
            "acao": div.action,
            "id_anterior": div.id_anterior,
        },
        "protecoes": await ler_protecoes(db, funcao),
        "duracao_ms": int((time.monotonic() - inicio) * 1000),
    }
