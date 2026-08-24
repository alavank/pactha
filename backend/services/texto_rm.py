"""Padronizacao de MAIUSCULAS dos textos do RM.

O portal escreve o mesmo campo de tres jeitos: TUDO EM CAIXA ALTA ("EXECUCAO DE
OBRAS..."), tudo em caixa baixa, ou ja formatado. O RM imprime os tres lado a
lado e o documento chega assim ao prefeito. Este modulo padroniza — com uma
regra que ele NAO pode violar: nunca estragar o que ja estava certo.

TRES GARANTIAS, nesta ordem de importancia:

1. SO MEXE NO QUE ESTA QUEBRADO. Texto em caixa MISTA volta byte a byte, sem
   passar por nada. Caixa mista e decisao de alguem — do portal, ou do proprio
   builder, que ja monta frase pronta (`_obra_resumo`, `_nes_resumo`). Adivinhar
   por cima dela e onde um padronizador estraga documento. So texto TODO em
   caixa alta ou TODO em caixa baixa e reescrito.

2. NUNCA INVENTA CARACTERE. Nenhum acento e acrescentado: "CAIXA ECONOMICA"
   viraria "Caixa Economica", nao "Caixa Economica" com circunflexo — a fonte
   nao tem o acento e adivinhar acento e adivinhar palavra. Ha DUAS excecoes, e
   as duas sao DADO e nao palpite: a tabela `_EXCECOES` (grafias canonicas
   escritas a mao, casadas por igualdade exata) e o nome do PROPRIO MUNICIPIO,
   que vem da tabela `municipios`.

3. NUNCA PROMOVE MINUSCULA A SIGLA. "500 mg" continua "500 mg". A lista de
   siglas so vale para token que a FONTE ja escreveu em caixa alta.

DUAS SAIDAS, porque "primeira letra maiuscula" quer dizer coisas diferentes:

  frase(...)        SENTENCE CASE. Primeira letra da frase maiuscula, o resto
                    minusculo. Para OBJETO, situacao, evento, alteracao — que
                    sao frases. E o que o dono pediu, literalmente.
  nome_proprio(...) TITLE CASE com particula minuscula. Para PARLAMENTAR,
                    BANCO, PROGRAMA e ORGAO — que sao NOMES. "JUNIO AMARAL" em
                    sentence case viraria "Junio amaral", que e erro grosseiro
                    em documento assinado.

CUSTO CONHECIDO DO SENTENCE CASE: nome proprio DENTRO de uma frase e rebaixado
("...NA ESCOLA JOAO XXIII" -> "...na escola joao XXIII"). O unico nome proprio
que o RM sabe com certeza qual e — o do municipio do relatorio — fica protegido
via `proprios` (ver `proprios_do_municipio`). Os demais dependem do olho humano:
e por isso que a padronizacao roda no BUILDER, cujo resultado o usuario revisa na
tela (frontend/src/app/dashboard/rm/[id]/page.tsx) antes de emitir o PDF.

PURO DE PROPOSITO: nenhuma consulta, nenhum I/O, nenhuma dependencia do request.
Testavel em backend/tests/test_texto_rm.py sem banco.
"""
from __future__ import annotations

import re
import unicodedata

# Vogais SEM acento: o teste roda sobre o texto ja normalizado (_sem_acento).
_VOGAIS = frozenset("AEIOU")

# Tokens em caixa alta que NAO sao palavra: preservados como vieram.
# Vale so para token que a FONTE escreveu em caixa alta (garantia 3 do topo).
# Lista de DADO, feita para crescer: uma sigla nova e uma linha aqui mais um
# teste. NAO inventar entrada "por seguranca" — cada sigla ambigua e uma palavra
# portuguesa que este modulo passa a estragar em silencio.
_SIGLAS = frozenset({
    # UFs — so as que nao colidem com palavra/particula em portugues
    "MG", "ES", "GO", "RS", "DF", "SP", "RJ", "PR", "SC", "BA", "PE", "CE",
    "MT", "MS", "RN", "PB", "PI",
    # DE FORA DE PROPOSITO: SE, TO, PA, AL, AM, AC, AP, MA, RO, RR. Todas
    # colidem com palavra ou particula ("se", "to", "pa", "ao"...), e num objeto
    # em caixa alta a palavra e muito mais frequente que a UF no sufixo. Efeito:
    # "CIDADE/TO" sai "cidade/to". Decisao do dono para incluir.
    # Sistemas e orgaos que este repositorio le
    "SNEAELIS", "SIGCON", "SICONV", "SIMEC", "SIAFI", "SIAPE", "SICONFI",
    "FNS", "FNDE", "MEC", "SUS", "PAC", "PNAE", "PNATE", "FUNDEB", "CAUC",
    "CAGEC", "SISMOB", "INVESTSUS", "TCE", "TCU", "CGU", "AGU", "IBGE",
    "INSS", "DNIT", "FUNASA", "INCRA", "IBAMA", "ANVISA", "ANEEL", "CODEVASF",
    # AMBIGUA, incluida de proposito: "PAR" (SIMEC/PAR, tabela
    # simec_par_liberacoes) tambem e a palavra "par". Em objeto de convenio
    # "SIMEC/PAR" e muito mais frequente que "par de" — mas a colisao existe.
    "PAR",
    # Documentos, cadastros e tributos
    "CNPJ", "CPF", "CEP", "UF", "ART", "RRT", "CREA", "CAU", "OB", "NE", "OP",
    "IPTU", "ISS", "ICMS", "IRRF", "FGTS", "PIS", "PPA", "LOA", "LDO",
    # Equipamentos publicos
    "UBS", "ESF", "PSF", "CRAS", "CREAS", "SAMU", "UPA", "CAPS", "APAE",
    "EMEI", "EMEF",
})

# Particulas que ficam minusculas DENTRO de um nome proprio (nunca na 1a posicao).
_ATONAS = frozenset({
    "de", "da", "do", "das", "dos", "e", "em", "no", "na", "nos", "nas",
    "a", "o", "as", "os", "ao", "aos", "à", "às", "para", "por",
    "pelo", "pela", "com", "sem", "sob", "sobre", "entre", "ou", "até",
})

# Grafias CANONICAS, casadas por igualdade exata do texto INTEIRO (sem acento,
# caixa alta, espaco unico). E o UNICO lugar onde o modulo pode ACRESCENTAR
# acento — porque aqui a grafia foi escrita a mao, nao adivinhada. Sem esta
# tabela, "CAIXA ECONOMICA FEDERAL" (o portal grava sem acento) sairia
# "Caixa Economica Federal" no relatorio. Tabela para o dono crescer.
_EXCECOES = {
    "CAIXA ECONOMICA FEDERAL": "Caixa Econômica Federal",
    "CAIXA ECONOMICA FEDERAL S.A.": "Caixa Econômica Federal S.A.",
    "BANCO DO BRASIL": "Banco do Brasil",
    "BANCO DO BRASIL S.A.": "Banco do Brasil S.A.",
    "BANCO DO BRASIL SA": "Banco do Brasil S.A.",
    "BANCO BRADESCO": "Banco Bradesco",
    "BANCO BRADESCO S.A.": "Banco Bradesco S.A.",
    "ITAU UNIBANCO": "Itaú Unibanco",
    "ITAU UNIBANCO S.A.": "Itaú Unibanco S.A.",
    "BANCO SANTANDER": "Banco Santander",
    "BANCO SANTANDER (BRASIL) S.A.": "Banco Santander (Brasil) S.A.",
    "BANCO DE BRASILIA": "Banco de Brasília",
    "BANCO DO NORDESTE DO BRASIL": "Banco do Nordeste do Brasil",
    "BANCO COOPERATIVO SICREDI": "Banco Cooperativo Sicredi",
    "BANCO COOPERATIVO DO BRASIL": "Banco Cooperativo do Brasil",
    "SICOOB": "Sicoob",
    "SICREDI": "Sicredi",
}

# Algarismo romano ESTRITO e curto ("ETAPA II", "FASE IV").
# O limite de 4 caracteres nao e estetica: sem ele "CIVIL" (C-I-V-I-L, todas
# letras romanas) sobreviveria em caixa alta no meio de "construcao civil".
_ROMANO = re.compile(
    r"^(?=[IVXLCDM]{1,4}$)M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")

# Alterna corridas de caracteres de PALAVRA e de NAO-PALAVRA, para reconstruir a
# string com pontuacao e espacos IDENTICOS aos da origem (inclusive espaco duplo).
_TOKENS = re.compile(r"[^\W_]+|[\W_]+", re.UNICODE)

# Pontuacao que encerra frase (a proxima palavra volta a ser maiuscula). O `·`
# esta aqui porque e o separador que o proprio rm_builder usa em `situacao_atual`
# ("Em execucao · PENDENTE DE DESEMBOLSO").
_FIM_DE_FRASE = frozenset(".!?·\n")

# MARCADORES do relatorio: caixa alta DE PROPOSITO, e nao texto que o portal
# escreveu torto. Sao os avisos que o rm_builder ACRESCENTA a `situacao_atual`
# (ver _situacao_com_marcas) e existem para gritar na pagina — rebaixa-los a
# "Pendente de desembolso" apagaria justamente o sinal, e ninguem pediu isso.
#
# So valem como SEGMENTO INTEIRO entre os separadores ` · ` que o builder usa;
# a palavra "pendente" no meio de uma frase do portal segue sendo padronizada.
_MARCAS = frozenset({"PENDENTE DE EMPENHO", "PENDENTE DE DESEMBOLSO"})
_SEPARADOR = " · "


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def _chave(s) -> str:
    """Texto comparavel: sem acento, caixa alta, espaco unico."""
    return " ".join(_sem_acento(str(s or "")).upper().split())


def _capitaliza(tok: str) -> str:
    """1a letra maiuscula, o resto minusculo."""
    return tok[:1].upper() + tok[1:].lower()


def _tem_vogal(tok: str) -> bool:
    return any(c in _VOGAIS for c in _sem_acento(tok).upper())


def _precisa_padronizar(s: str) -> bool:
    """GARANTIA 1: so texto TODO em caixa alta ou TODO em caixa baixa e mexido.

    Caixa mista volta intacta — e o que impede o modulo de estragar
    "SNEAELIS (Emenda Parlamentar Individual - RP6 - Convenio)", que ja esta
    certo, e de reprocessar o que o usuario corrigiu a mao na tela do RM.
    Menos de duas letras: nada a decidir, volta como veio."""
    letras = [c for c in s if c.isalpha()]
    if len(letras) < 2:
        return False
    return any(c.islower() for c in letras) != any(c.isupper() for c in letras)


def _token(tok: str, *, primeira: bool, modo: str, alta: bool,
           proprios: dict, inicial: bool = False) -> str:
    """Decide UM token. A ordem das regras E a especificacao — primeira que casa
    vence, e as protecoes vem todas antes de qualquer reescrita."""
    # 1. Tem digito -> e codigo, numero ou identificador. Intocavel.
    #    Cobre 993503/2026 (em dois tokens), 1060-0, 2026NE000320 e RP6.
    if any(c.isdigit() for c in tok):
        return tok
    chave = _sem_acento(tok).upper()
    # 2. Nome do municipio do relatorio, na grafia CANONICA da tabela municipios.
    #    Piso de 3 letras para nao capturar particula de nome composto
    #    ("Monte Siao do Sul" nao pode transformar todo "do" em "Do").
    if len(chave) >= 3 and chave in proprios:
        return proprios[chave]
    if alta:
        # 3. Sigla conhecida — SO quando a FONTE escreveu em caixa alta.
        if chave in _SIGLAS:
            return tok
        # 4. Letra solta SEGUIDA DE PONTO e inicial de nome ("J." de "J. AMARAL").
        #    ⚠️ O PONTO E O SINAL, e nao o simples "tem uma letra so". Sem ele a
        #    regra vencia a regra 7 e produzia dois erros medidos por teste:
        #    "JOSE DA SILVA E SOUZA" -> "Silva E Souza" (o "e" e CONJUNCAO) e
        #    "FALTA A VISTORIA" -> "Falta A vistoria" (o "a" e ARTIGO).
        #    Letra solta SEM ponto cai nas regras seguintes, que ja resolvem bem:
        #    consoante nao tem vogal e sobrevive pela regra 5 ("ANEXO B"), "I" e
        #    "V" sobrevivem pela 6 (romano), e so as vogais que sao palavra em
        #    portugues (a/e/o) chegam a reescrita.
        if len(tok) == 1 and inicial:
            return tok.upper()
        # 5. Sem NENHUMA vogal -> nao e palavra portuguesa. Cobre sigla que nao
        #    esta na lista (PSDB, MW, CNH) sem risco: toda palavra do portugues
        #    tem vogal.
        if not _tem_vogal(tok):
            return tok
        # 6. Algarismo romano curto e valido ("ETAPA II", "FASE IV").
        if _ROMANO.match(chave):
            return tok
    # 7. Reescrita.
    if modo == "nome" and not primeira and tok.lower() in _ATONAS:
        return tok.lower()
    if modo == "nome" or primeira:
        return _capitaliza(tok)
    return tok.lower()


def _aplica(texto, modo: str, proprios: dict | None = None) -> str:
    s = "" if texto is None else str(texto)
    # MARCADORES: quando o texto e a composicao ` · ` do rm_builder, cada
    # segmento e decidido por conta propria e os de `_MARCAS` passam intactos.
    # Sem isto, "PLANO DE TRABALHO EM ANALISE · PENDENTE DE DESEMBOLSO" (todo em
    # caixa alta, como algumas fontes escrevem) sairia com o aviso rebaixado a
    # "Pendente de desembolso" — o sinal apagado junto com o defeito.
    if _SEPARADOR in s:
        return _SEPARADOR.join(
            p if _chave(p) in _MARCAS else _aplica(p, modo, proprios)
            for p in s.split(_SEPARADOR))
    if _chave(s) in _MARCAS:
        return s
    if not _precisa_padronizar(s):
        return s
    alta = any(c.isupper() for c in s)
    mapa = {_sem_acento(str(k)).upper(): v for k, v in (proprios or {}).items()}
    toks = _TOKENS.findall(s)
    saida: list[str] = []
    primeira = True
    for i, tok in enumerate(toks):
        if tok[0].isalnum():
            # "e uma INICIAL?" = a letra e seguida imediatamente de ponto
            # ("J." de "J. AMARAL"). E o unico sinal confiavel — ver a regra 4.
            prox = toks[i + 1] if i + 1 < len(toks) else ""
            saida.append(_token(tok, primeira=primeira, modo=modo, alta=alta,
                                proprios=mapa, inicial=prox.startswith(".")))
            primeira = False
        else:
            saida.append(tok)
            if any(c in _FIM_DE_FRASE for c in tok):
                primeira = True
    return "".join(saida)


def frase(texto, proprios: dict | None = None) -> str:
    """SENTENCE CASE: so a primeira letra da frase em maiuscula.

    Para OBJETO, situacao, evento e alteracao. Exemplo (com o municipio Araujos
    em `proprios`):
      "EXECUCAO DE OBRAS ... NO MUNICIPIO DE ARAUJOS/MG"
      -> "Execucao de obras ... no municipio de Araujos/MG"
    Texto em caixa mista volta identico."""
    return _aplica(texto, "frase", proprios)


def nome_proprio(texto, proprios: dict | None = None) -> str:
    """TITLE CASE com particula minuscula, para NOME (pessoa, banco, orgao,
    programa).

      "JUNIO AMARAL"            -> "Junio Amaral"   (acento NAO e inventado)
      "JOSE DA SILVA"           -> "Jose da Silva"
      "CAIXA ECONOMICA FEDERAL" -> grafia canonica de _EXCECOES

    A consulta a `_EXCECOES` acontece ANTES da guarda de caixa mista, de
    proposito: nome de banco e string fixa, e vale canonizar venha como vier."""
    s = "" if texto is None else str(texto)
    canon = _EXCECOES.get(_chave(s))
    if canon:
        return canon
    return _aplica(s, "nome", proprios)


def proprios_do_municipio(mun) -> dict:
    """Palavras do nome do MUNICIPIO do relatorio, com a grafia da tabela
    `municipios` — o unico nome proprio que o RM sabe, de fato, qual e.

    E daqui que sai a restauracao de acento em "ARAUJOS/MG" -> "Araujos/MG" com
    acento: nao ha adivinhacao, a grafia vem do banco. `mun` None (municipio
    apagado) devolve {} e a padronizacao segue sem esse nome protegido."""
    nome = (getattr(mun, "nome", "") or "").strip()
    if not nome:
        return {}
    # Tenant que grava o nome do municipio em CAIXA ALTA: normaliza primeiro,
    # senao o "nome canonico" injetado seria ele mesmo em caixa alta.
    nome = nome_proprio(nome)
    return {p: p for p in nome.split() if len(p) >= 3}


# --------------------------------------------------------------------------
# Aplicacao ao ITEM do RM
# --------------------------------------------------------------------------
# LISTA BRANCA, e nunca "todas as chaves de texto". Percorrer o dict inteiro
# reescreveria campo que NAO pode mudar, e o estrago seria silencioso:
#
#   numero          identificador do instrumento (993503/2026, 2026NE000320)
#   situacao_base   e o campo que CLASSIFICA (rm_export._e_pendencia, :216)
#   nes             ja e frase montada com numero e valor (_nes_resumo)
#   agencia, conta  codigos bancarios
#   tipo            vocabulario controlado do proprio builder, e no SIMEC e a
#                   sigla do programa (PNAE, PNATE) — rm_builder.py:1288
#   fonte, fonte_ref, ordem, ano_item, valor_*, dt_*, desembolsos,
#   processo_execucao_lista, simec_*  -> dado, nao texto de leitura
#
# Tambem NAO entram aqui, e nao devem entrar: o titulo da PARTE
# (_titulos_partes_completo), o titulo da SECAO (_SEC_FED_PLURAL e irmaos,
# rm_builder.py:49-53) e o titulo do relatorio (rm_pdf.py:474). Os tres estao em
# caixa alta DE PROPOSITO, copiados do documento de referencia — o dono nao pediu
# para mexer neles.
_CAMPOS_FRASE = (
    "objeto", "situacao_atual", "situacao_contratacao", "situacao_contrato",
    "clausula_motivo", "projeto_basico", "obra",
    "evento_atual", "evento_situacao", "evento_consideracoes",
    "alteracao_situacao", "alteracao_tipo", "alteracao_titulo",
)
_CAMPOS_NOME = ("parlamentar", "banco", "programa", "evento_responsavel")


def normalizar_item(item: dict, proprios: dict | None = None) -> dict:
    """Padroniza a caixa dos campos de LEITURA do item, no lugar (e devolve o
    mesmo dict, por conveniencia de encadeamento).

    `isinstance(v, str)` nao e paranoia: `add_item` recebe o item com
    `**_desembolso_ops_obs(...)`, `**_evento_atual(...)` e
    `**_alteracao_campos(...)` fundidos, entao ha lista e numero no mesmo dict."""
    for k in _CAMPOS_FRASE:
        v = item.get(k)
        if isinstance(v, str) and v:
            item[k] = frase(v, proprios)
    for k in _CAMPOS_NOME:
        v = item.get(k)
        if isinstance(v, str) and v:
            item[k] = nome_proprio(v, proprios)
    return item
