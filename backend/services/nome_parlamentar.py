"""O que NAO e nome de parlamentar.

Por que este modulo existe, com o numero que o motivou: no cliente freitas, o
maior parlamentar do ranking era **"Não há"** — 12 convenios, R$ 14.936.735,03,
em 7 municipios. Treze vezes o valor do segundo colocado (LOHANNA,
R$ 1.160.833,33). Ele aparecia na tela de Parlamentares, no Painel de
Indicadores e no relatorio RM, porque o campo `responsaveis` do SIGCON-MG traz
literalmente o texto "Não há" quando o portal nao tem responsavel, e os tres
lugares tratavam isso como nome de pessoa.

⚠️ POR QUE UM MODULO, E NAO UM `if` EM CADA LUGAR: sao TRES consumidores
(routers/parlamentares.py, services/bi_abas.py, services/rm_builder.py) lendo a
mesma coluna. Neste mesmo repositorio, a regra de "excluir FNS" ficou copiada em
quatro lugares e foi esquecida no quinto — o export PDF, que passou meses
contando propostas de saude como convenio estadual. Aqui a regra mora num lugar
so, de proposito.

⚠️ E NAO se aplica ao MODAL de Convenios. La o campo "Responsável(is)" mostra o
que o portal escreveu, e "Responsável(is): Não há" e frase correta em portugues
— vira DADO, nao ruido. O que nao pode e essa frase virar uma PESSOA num
ranking. Trocar por "-" no modal perderia a distincao entre "a fonte disse que
nao ha" e "nunca coletamos".
"""
from __future__ import annotations

import json
import unicodedata


def _valor_proposta(v) -> float:
    """vlProposta -> float tolerante. O JSON do FNS traz numero, mas defende de
    string ('500000.0') e de formato inesperado sem derrubar a agregacao."""
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def emendas_saude_por_autor(linha_propostas) -> list[tuple[str | None, float]]:
    """As emendas de saude do FNS por AUTOR, de `raw_data['linhaPropostas']`.

    ⚠️ POR QUE ESTE MODULO, E NAO CADA TELA. O autor da emenda de saude NAO esta
    no nivel raiz do raw_data (os campos noAutor/noParlamentar/responsaveis vem
    vazios para FNS) — ele mora ANINHADO em
    `linhaPropostas[].parlamentares[].{noApelidoPolitico|noParlamentar|nome}`.
    O RM ja desce ate la (services/rm_builder.py, laco do FNS); a tela de
    Parlamentares e a aba do BI liam so o raiz e por isso escondiam a emenda
    (medido em 04/09/2026: "Incremento pap" R$400k do Igor Timo, Nova Serrana,
    no banco e no RM, ausente das duas telas). A extracao mora AQUI, num lugar
    so, pela mesma razao do resto do modulo — a regra de "excluir FNS" ja ficou
    copiada em cinco lugares e foi esquecida num deles.

    Devolve UMA tupla por proposta individual: `(autor, vlProposta)`, com um par
    por parlamentar quando a proposta tem varios (rateio da agregacao por autor).
    `autor` e `None` quando a proposta nao tem parlamentar real — o chamador
    decide o fallback (o Fundo Municipal, para o valor nao se perder).
    Tolera `linha_propostas` como lista JSONB ja parseada OU string.
    """
    if isinstance(linha_propostas, str):
        try:
            linha_propostas = json.loads(linha_propostas)
        except (ValueError, TypeError):
            return []
    if not isinstance(linha_propostas, list):
        return []
    out: list[tuple[str | None, float]] = []
    for prop in linha_propostas:
        if not isinstance(prop, dict):
            continue
        val = _valor_proposta(prop.get("vlProposta"))
        parls = prop.get("parlamentares")
        nomes = []
        if isinstance(parls, list):
            for pp in parls:
                if not isinstance(pp, dict):
                    continue
                nm = (pp.get("noApelidoPolitico") or pp.get("noParlamentar")
                      or pp.get("nome") or "").strip()
                if e_parlamentar_real(nm):
                    nomes.append(nm)
        if nomes:
            for nm in nomes:
                out.append((nm, val))
        else:
            out.append((None, val))
    return out

# Comparacao por IGUALDADE EXATA do texto normalizado, NUNCA por substring: um
# parlamentar de verdade pode se chamar "Ana Nao..." ou conter qualquer um
# desses fragmentos, e uma regra por substring o apagaria em silencio — o
# oposto do defeito que este modulo conserta.
#
# A lista sai do dado REAL das tres bases, nao de imaginacao. Cada entrada
# especulativa e uma chance de engolir um nome legitimo amanha.
_NAO_E_NOME = {
    "NAO HA",        # SIGCON-MG, 12 lancamentos / R$ 14,9 mi no freitas
    "NAO INFORMADO",
    "N/A",
    "NA",
    "SEM RESPONSAVEL",
    "NENHUM",
    "-",
    "--",
}


def _chave(nome: str) -> str:
    """UPPER, sem acento, espaco unico — a mesma normalizacao que os tres
    consumidores ja usam para agrupar (`_norm`), replicada aqui para a decisao
    nao depender de qual deles chamou."""
    if not nome:
        return ""
    s = "".join(c for c in unicodedata.normalize("NFKD", str(nome))
                if not unicodedata.combining(c))
    return " ".join(s.upper().split())


def e_parlamentar_real(nome: str) -> bool:
    """False quando o texto e marcador de ausencia do portal, e nao uma pessoa.

    Mantem o piso de 3 caracteres que os consumidores ja aplicavam — ele existe
    para descartar iniciais soltas e lixo de parsing, e continua valendo aqui
    para a regra viver inteira num lugar so.
    """
    s = (nome or "").strip()
    if len(s) < 3:
        return False
    return _chave(s) not in _NAO_E_NOME


# ---------------------------------------------------------------------------
# PESSOA vs INSTITUICAO
# ---------------------------------------------------------------------------
# Motivo, com o caso que originou: na tela de Parlamentares de Conceicao da
# Barra/ES os dois primeiros colocados eram "FUNDO MUNICIPAL DE SAUDE —
# Conceicao da Barra" (R$ 37,4 mi) e "MUNICIPIO DE CONCEICAO DA BARRA"
# (R$ 12,3 mi) — juntos, 80% do valor da tela. Nao sao erro de coleta: o PAC
# cai no `proponente` quando a proposta nao tem emenda parlamentar, e o FNS nao
# publica o autor da emenda de saude, entao o Fundo entra como proponente. O
# dado esta certo; o que estava errado era chama-los de "parlamentar".
#
# ⚠️ Isto NAO exclui ninguem. Classifica, para a tela poder separar. Sumir com
# esses lancamentos esconderia 80% do dinheiro do municipio — o oposto do que
# se quer. Quem consome decide o que mostrar; aqui so se responde "e pessoa?".
#
# ⚠️ Comparacao por PALAVRA INTEIRA do nome normalizado, nunca por substring —
# a mesma disciplina do bloco acima. "BARRA" contem "ARR", e um parlamentar
# pode se chamar "Fundao"; so descartamos quando a palavra inteira bate.
_TERMOS_INSTITUCIONAIS = {
    # os dois que motivaram o modulo
    "FUNDO", "FUNDOS", "MUNICIPIO", "MUNICIPAL",
    # entes e orgaos
    "PREFEITURA", "ESTADO", "GOVERNO", "UNIAO", "MINISTERIO", "SECRETARIA",
    "DEPARTAMENTO", "SUPERINTENDENCIA", "AUTARQUIA", "AGENCIA", "GABINETE",
    "DIRETORIA", "CAMARA", "CONSELHO", "DISTRITO", "TESOURO",
    # Emenda de BANCADA e do coletivo, nao de uma pessoa. Entrou depois da
    # primeira auditoria, que quase deixou passar um resultado INCOERENTE: das
    # cinco bancadas reais da base (GOIAS, MINAS GERAIS, TOCANTINS, ESPIRITO
    # SANTO, DISTRITO FEDERAL), so a do DISTRITO FEDERAL caia em "outro" — e por
    # acidente, porque "DISTRITO" ja estava na lista acima. As outras quatro
    # seriam exibidas como se fossem gente, na mesma tela.
    "BANCADA",
    # Emenda de COMISSAO e de RELATOR, pelo mesmo motivo: o autor e o colegiado
    # ou o cargo, nao uma pessoa. Sao 15 na base ("COMISSAO DE TURISMO E
    # DESPORTO - CTD", "RELATOR GERAL"), e 4 delas apareciam no ranking de
    # Conceicao da Barra/ES.
    "COMISSAO", "RELATOR",
    # pessoas juridicas de direito privado / terceiro setor
    "INSTITUTO", "FUNDACAO", "ASSOCIACAO", "CONSORCIO", "COOPERATIVA",
    "SINDICATO", "EMPRESA", "COMPANHIA", "LTDA", "EIRELI",
    # equipamentos publicos que aparecem como proponente
    "HOSPITAL", "UNIVERSIDADE", "FACULDADE", "BANCO",
}


def e_pessoa(nome: str) -> bool:
    """True quando o texto parece nome de PESSOA (um parlamentar), False quando
    e uma entidade (fundo, municipio, prefeitura, instituto...).

    Deliberadamente conservadora: na duvida responde True. Um parlamentar
    classificado como "outro" some da aba que abre por padrao — falha
    silenciosa e cara. Uma entidade classificada como parlamentar so polui uma
    lista, e e visivel. Por isso a lista acima nao inclui termos que apelidos
    parlamentares reais usam ("Delegado", "Professora", "Doutor", "Sargento",
    "Coronel", "Cabo", "Pastor", "Padre", "Policial", "Bombeiro"), mesmo que
    alguns tambem nomeiem instituicoes.
    """
    if not e_parlamentar_real(nome):
        return False
    lista = _chave(nome).replace("/", " ").replace(".", " ").split()
    palavras = set(lista)
    if palavras & _TERMOS_INSTITUCIONAIS:
        return False
    # "COM." e como o TransfereGov abrevia COMISSAO ("COM. TURISMO", "COM.
    # DESENV REGIONAL E TURISMO"). So vale como PRIMEIRA palavra, e nao entra no
    # conjunto acima de proposito: "com" solto no meio de um nome e preposicao
    # comum, e derrubaria gente. Nome de pessoa nao COMECA com "Com".
    if lista and lista[0] == "COM" and len(lista) > 1:
        return False
    # CNPJ no meio do nome (14 digitos seguidos) — proponente, nunca pessoa.
    if any(p.isdigit() and len(p) >= 11 for p in palavras):
        return False
    return True
