"""O RELATÓRIO DE PARLAMENTARES no MODELO DA PLANILHA do cliente (24/09/2026).

Pedido do dono: "na aba parlamentares eu gostaria que o pdf ficasse nesse modelo"
— a planilha `EmendasNikolasFerreiraBomDespacho.xlsx` (aba "Emendas por
categoria"): um título "RECURSOS PAGOS BOM DESPACHO – EMENDAS INDICADAS POR
NIKOLAS FERREIRA", as colunas MUNICÍPIO | ANO | RECURSO | MINISTÉRIO DE ORIGEM |
VALOR GLOBAL (R$) | PLANO DE AÇÃO / PROPOSTA | SITUAÇÃO ATUAL, uma faixa por ÁREA
(SAÚDE, INFRAESTRUTURA...), subtotal por área e TOTAL GERAL.

Este módulo é a LÓGICA, pura (sem banco, sem reportlab): recebe o `detalhe` de
`routers/parlamentares.py::detalhe_core` e devolve o bloco pronto para desenhar.
Quem desenha é `routers/export_pdf.py::export_parlamentares_pdf`.

⚠️⚠️ NÃO CONTAR O MESMO DINHEIRO DUAS VEZES — a regra, fonte a fonte:

  1. INSTRUMENTO VENCE A INDICAÇÃO. A emenda é a indicação; o instrumento
     (plano da TE, proposta do FNS, convênio) é o dinheiro andando. Onde os dois
     casam por CHAVE, sai o instrumento e a emenda não se repete:
       - carteira CGU x voluntária: `id_proposta` (já descontado em `detalhe_core`);
       - carteira CGU x TE: o código de 12 dígitos (idem);
       - emenda ESTADUAL x convênio SIGCON: o nº da indicação que o convênio
         carrega (`raw_data.nr_indicacao`/`indicacoes`) — descontado AQUI, e só
         quando o convênio está no mesmo bloco (senão a indicação some junto)
         E FICA NO TOTAL COM VALOR (`_convenio_vence`): convênio em
         Cadastramento com R$ 0,00 (Araújos, 002567/2026, SEAPA) ou rescindido/
         cancelado não apaga a indicação que carrega;
       - seleção do Novo PAC x voluntária: o "Número da Proposta Novo PAC" que a
         voluntária carrega (`_pac_da_voluntaria`, a regra do RM) — idem;
       - FNS: UMA linha por (município, nº da proposta), com a PARTE do autor
         (soma dos `vlIndObjeto` dele) — em `detalhe_core` e
         `nome_parlamentar.propostas_saude_por_autor`.
  2. SEM CHAVE CASADA, FORA DO TOTAL. O que sobra da carteira CGU depois do
     desconto pode ser o mesmo dinheiro de uma proposta do FNS ou de uma seleção
     do PAC, e não foi casado pelo número da emenda nesta base: o PAC não traz o
     número; o FNS traz (`coEmendaPolitica` + `nuAnoExercicio`), mas o formato
     dele contra o `codigo_emenda` de 12 dígitos nunca foi medido, e casar por
     nome apagaria emenda legítima (a regra de `services/emendas_unificadas.py`).
     Então essas linhas saem numa seção própria, "EMENDAS FEDERAIS SEM
     INSTRUMENTO IDENTIFICADO", FORA do total geral, e o PDF diz isso.
  3. O QUE NÃO É RECURSO, FORA DO TOTAL. Seleção do PAC não selecionada, plano
     da TE IMPEDIDO, convênio SIGCON em Cadastramento (`_em_cadastramento`, que
     o RM nem imprime), proposta do FNS rejeitada/bloqueada/arquivada
     (`_fns_classifica`, a regra do RM para o FNS) e instrumento cancelado/
     rejeitado/anulado (`_fed_status` == 'dead', a regra do RM) aparecem, mas em
     `GRUPO_NAO_RECURSO`, fora da soma. Nada some do relatório.

⭐ ÁREAS — regra EXPLÍCITA e conservadora (`area_por_funcoes`/`area_por_orgao`):
  - FNS é SAÚDE, sempre (é o Fundo Nacional de SAÚDE).
  - Transferência especial: pela FUNÇÃO orçamentária de cada finalidade do
    plano (a classificação oficial da despesa: 10 Saúde, 12 Educação, 8
    Assistência, 15/16/17/26 Urbanismo/Habitação/Saneamento/Transporte, 20
    Agricultura, 27 Desporto e Lazer, 6 Segurança, 13 Cultura, 23/695 Turismo).
  - Demais: pelo nome do MINISTÉRIO/SECRETARIA (palavras e siglas listadas em
    `_PALAVRAS_AREA` e `_SIGLAS_AREA`).
  - ESPORTE-OBRA é INFRAESTRUTURA: a quadra do modelo (TE só de INVESTIMENTO,
    "Reforma da quadra esportiva") cai em INFRAESTRUTURA. Esporte com custeio
    fica em ESPORTE E LAZER.
  - Duas áreas diferentes no mesmo instrumento, ou nenhuma reconhecida: OUTROS.
    Na dúvida, OUTROS — área errada engana mais que área genérica.
  Ordem das faixas: pela SOMA, maior primeiro (no modelo, SAÚDE 450 mil antes de
  INFRAESTRUTURA 400 mil — as duas regras concordam); OUTROS sempre por último.

⭐ "PAGOS" NO TÍTULO SÓ COM TUDO PAGO: toda linha do total com pagamento MEDIDO
(TE com OB de 100%, FNS com repasse e nada a pagar, voluntária desembolsada por
inteiro, indicação estadual paga na planilha da SEGOV) e nenhuma linha fora do
total. Qualquer outra coisa é "RECURSOS PARA <CIDADE>" — não se afirma "pagos"
do que não foi pago, nem do que não foi consultado. SIGCON e PAC não têm medição
de pagamento aqui: nunca contam como pagos.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from services.execucao_te import frase_execucao_te
from services.rm_builder import (
    _em_cadastramento, _fed_status, _fmt_brl, _fns_classifica, _mesma_proposta)
from services.texto_rm import frase, nome_proprio

# As faixas do modelo, na ordem de desempate. OUTROS é sempre a última.
AREAS: tuple[str, ...] = (
    "SAÚDE", "EDUCAÇÃO", "ASSISTÊNCIA SOCIAL", "INFRAESTRUTURA", "AGRICULTURA",
    "ESPORTE E LAZER", "SEGURANÇA", "CULTURA", "TURISMO", "OUTROS",
)
OUTROS = "OUTROS"

GRUPO_NAO_RECURSO = "PROPOSTAS NÃO SELECIONADAS, EM CADASTRAMENTO, CANCELADAS OU IMPEDIDAS"
GRUPO_SEM_INSTRUMENTO = "EMENDAS FEDERAIS SEM INSTRUMENTO IDENTIFICADO"
GRUPOS_FORA: tuple[str, ...] = (GRUPO_NAO_RECURSO, GRUPO_SEM_INSTRUMENTO)

SEM_DADO = "—"

# ---------------------------------------------------------------------------
# ÁREAS
# ---------------------------------------------------------------------------
# FUNÇÃO orçamentária (Portaria MOG 42/1999) -> faixa. É o que o plano da TE
# traz em cada finalidade (`cd_area_politica_publica_tipo_pt`).
_AREA_POR_FUNCAO: dict[int, str] = {
    10: "SAÚDE",
    12: "EDUCAÇÃO",
    8: "ASSISTÊNCIA SOCIAL",
    15: "INFRAESTRUTURA",    # Urbanismo
    16: "INFRAESTRUTURA",    # Habitação
    17: "INFRAESTRUTURA",    # Saneamento
    26: "INFRAESTRUTURA",    # Transporte
    20: "AGRICULTURA",
    27: "ESPORTE E LAZER",   # Desporto e Lazer (obra -> INFRAESTRUTURA, abaixo)
    6: "SEGURANÇA",          # Segurança Pública (inclui 182 Defesa Civil)
    13: "CULTURA",
}
# Turismo não é função: é a SUBFUNÇÃO 695 da função 23 (Comércio e Serviços).
_FUNCAO_COMERCIO, _SUBFUNCAO_TURISMO = 23, 695

# Palavras do nome do ÓRGÃO (sem acento, caixa alta, palavra inteira). Uma área
# por linha; um nome que case DUAS áreas ("Cultura e Turismo") vira OUTROS.
# ⚠️ "Ministério da Cidadania" (2019-2022: assistência + esporte + cultura) e
# "Ministério da Defesa" ficam de fora de propósito: não dá para dizer a área.
_PALAVRAS_AREA: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("SAÚDE", ("SAUDE", "FUNASA")),
    ("EDUCAÇÃO", ("EDUCACAO", "FNDE")),
    ("ASSISTÊNCIA SOCIAL", ("ASSISTENCIA SOCIAL", "DESENVOLVIMENTO SOCIAL")),
    ("INFRAESTRUTURA", ("CIDADES", "DESENVOLVIMENTO REGIONAL", "INTEGRACAO",
                        "INFRAESTRUTURA", "TRANSPORTES?", "OBRAS", "ESTRADAS DE RODAGEM",
                        "HABITACAO", "SANEAMENTO", "DESENVOLVIMENTO URBANO",
                        "MOBILIDADE")),
    ("AGRICULTURA", ("AGRICULTURA", "AGRARIO", "PECUARIA", "ABASTECIMENTO", "PESCA")),
    ("ESPORTE E LAZER", ("ESPORTES?", "DESPORTO")),
    ("SEGURANÇA", ("SEGURANCA PUBLICA", "DEFESA SOCIAL", "DEFESA CIVIL")),
    ("CULTURA", ("CULTURA",)),
    ("TURISMO", ("TURISMO",)),
)
# Siglas de órgão ESTADUAL (MG, a fonte das emendas estaduais e do SIGCON), por
# token inteiro. Só as que não deixam dúvida — SEDESE (desenvolvimento social E
# esportes) e SECULT (cultura E turismo) ficam de fora e caem em OUTROS.
_SIGLAS_AREA: dict[str, str] = {
    "SES": "SAÚDE", "FES": "SAÚDE",
    "SEE": "EDUCAÇÃO",
    "SEINFRA": "INFRAESTRUTURA", "DER": "INFRAESTRUTURA",
    "SEAPA": "AGRICULTURA",
    "SEJUSP": "SEGURANÇA",
}
# ESPORTE-OBRA: o objeto fala de obra. Só vale para tirar do ESPORTE E LAZER.
_OBRA = re.compile(r"\b(CONSTRU\w*|REFORMA\w*|AMPLIA\w*|OBRAS?|PAVIMENTA\w*|"
                   r"COBERTURA\w*|REVITALIZA\w*)\b")


def _chave(s) -> str:
    """Sem acento, caixa alta, espaço único."""
    t = "".join(c for c in unicodedata.normalize("NFKD", str(s or ""))
                if not unicodedata.combining(c))
    return " ".join(t.upper().split())


def _uma(areas: set) -> str:
    """Exatamente uma área reconhecida -> ela; nenhuma ou mais de uma -> OUTROS."""
    areas = {a for a in areas if a and a != OUTROS}
    return next(iter(areas)) if len(areas) == 1 else OUTROS


def _e_obra(texto) -> bool:
    return bool(_OBRA.search(_chave(texto)))


def pares_de_funcao(funcoes, subfuncoes=None, texto=None) -> list[list]:
    """[[função, subfunção|None], ...] de um plano da TE, sem repetição.

    Primeiro as FINALIDADES da árvore (`cd_area_politica_publica_tipo_pt` e
    `cd_area_politica_publica_pt`, na mesma ordem — as duas listas saem do mesmo
    `$.executores[*].finalidades[*]`). Sem árvore, as áreas da LISTAGEM, em
    texto: "27-Desporto e Lazer / 812-Desporto Comunitário , 15-Urbanismo /
    451-Infraestrutura Urbana". Nunca levanta."""
    out: list[list] = []

    def _int(v):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None

    fs = funcoes if isinstance(funcoes, list) else []
    ss = subfuncoes if isinstance(subfuncoes, list) else []
    for i, f in enumerate(fs):
        fi = _int(f)
        if fi is None:
            continue
        par = [fi, _int(ss[i]) if i < len(ss) else None]
        if par not in out:
            out.append(par)
    if not out and texto:
        for m in re.finditer(r"(?:^|,)\s*(\d{1,2})\s*-[^/,]*/\s*(\d{3})\s*-", str(texto)):
            par = [int(m.group(1)), int(m.group(2))]
            if par not in out:
                out.append(par)
    return out


def area_por_funcoes(pares, so_investimento: bool = False) -> str:
    """A faixa de um plano da TE pelas funções orçamentárias das finalidades.
    Desporto e Lazer SÓ de investimento é obra -> INFRAESTRUTURA (a quadra do
    modelo)."""
    areas: set = set()
    for par in pares or []:
        try:
            f, s = par[0], (par[1] if len(par) > 1 else None)
        except (TypeError, IndexError):
            continue
        a = ("TURISMO" if (f == _FUNCAO_COMERCIO and s == _SUBFUNCAO_TURISMO)
             else _AREA_POR_FUNCAO.get(f, OUTROS))
        if a == "ESPORTE E LAZER" and so_investimento:
            a = "INFRAESTRUTURA"
        areas.add(a)
    if OUTROS in areas:
        # Uma finalidade fora da tabela já faz o plano ter duas áreas.
        return OUTROS
    return _uma(areas)


def area_por_orgao(orgao, objeto=None, so_investimento: bool = False) -> str:
    """A faixa pelo nome do MINISTÉRIO/SECRETARIA (e siglas estaduais). O
    `objeto` só serve para o esporte-obra."""
    chave = _chave(orgao)
    if not chave:
        return OUTROS
    areas = {area for area, padroes in _PALAVRAS_AREA
             if any(re.search(rf"\b{p}\b", chave) for p in padroes)}
    tokens = set(re.findall(r"[A-Z]+", chave))
    areas |= {a for sigla, a in _SIGLAS_AREA.items() if sigla in tokens}
    if "ESPORTE E LAZER" in areas and (so_investimento or _e_obra(objeto)):
        areas.discard("ESPORTE E LAZER")
        areas.add("INFRAESTRUTURA")
    return _uma(areas)


# ---------------------------------------------------------------------------
# MINISTÉRIO pelo órgão SIAFI (PAC e carteira CGU)
# ---------------------------------------------------------------------------
# A preposição de cada nome de `routers/emendas_federais.ORGAOS_SIAFI` (que tem
# o nome curto, tirado do dump do Governo). Código sem preposição aqui sai com o
# nome curto como veio; código desconhecido, com o próprio código.
_PREPOSICAO_SIAFI: dict[str, str] = {
    "22000": "da", "24000": "da", "25000": "da", "26000": "da", "30000": "da",
    "36000": "da", "39000": "da", "44000": "do", "49000": "do", "51000": "do",
    "52000": "da", "53000": "da", "54000": "do", "55000": "do", "56000": "das",
    "58000": "da", "81000": "dos",
}


def ministerio_siafi(codigo) -> Optional[str]:
    """'36000' -> 'Ministério da Saúde'. None sem código."""
    cod = str(codigo or "").strip()
    if not cod:
        return None
    from routers.emendas_federais import ORGAOS_SIAFI
    nome = ORGAOS_SIAFI.get(cod)
    if not nome:
        return f"Órgão SIAFI {cod}"
    prep = _PREPOSICAO_SIAFI.get(cod)
    return f"Ministério {prep} {nome}" if prep else nome


# A fonte das voluntárias grava o órgão em caixa alta e SEM acento
# ("MINISTERIO DOS TRANSPORTES"); o modelo do cliente escreve "Ministério da
# Saúde". Só as palavras de NOME DE MINISTÉRIO — nada de corretor geral.
_ACENTOS_MINISTERIO = {
    "ministerio": "ministério", "saude": "saúde", "educacao": "educação",
    "integracao": "integração", "agrario": "agrário", "pecuaria": "pecuária",
    "ciencia": "ciência", "inovacao": "inovação", "inovacoes": "inovações",
    "comunicacoes": "comunicações", "justica": "justiça", "seguranca": "segurança",
    "publica": "pública", "publicos": "públicos", "assistencia": "assistência",
    "familia": "família", "gestao": "gestão", "servicos": "serviços",
    "previdencia": "previdência", "relacoes": "relações", "industria": "indústria",
    "comercio": "comércio", "orcamento": "orçamento", "indigenas": "indígenas",
    "economico": "econômico", "agricola": "agrícola", "energia": "energia",
}


def _acentua_ministerio(nome: str) -> str:
    out = []
    for p in str(nome or "").split(" "):
        certo = _ACENTOS_MINISTERIO.get(p.casefold())
        if certo:
            p = certo[0].upper() + certo[1:] if p[:1].isupper() else certo
        out.append(p)
    return " ".join(out)


def _sem_acento(s) -> str:
    """Para COMPARAR nomes: sem acento, sem caixa, espaços colapsados."""
    t = "".join(c for c in unicodedata.normalize("NFKD", str(s or ""))
                if not unicodedata.combining(c))
    return " ".join(t.casefold().split())


def ministerio_do_orgao(orgao) -> str:
    """O MINISTÉRIO DE ORIGEM de um órgão gravado como "CÓDIGO - NOME" — o
    formato das voluntárias ("36000 - MINISTERIO DA SAUDE", "36211 - FUNASA",
    `ingestion/transferegov_opendata._orgao`). Antes o PDF imprimia o rótulo
    cru: "36000 - Ministerio da Saude" na coluna do ministério.

    Código de 5 dígitos: o órgão SUPERIOR do SIAFI é o código com os três
    últimos zerados (36211 FUNASA -> 36000 Saúde; 26298 FNDE, autarquia -> 26000
    Educação), e o nome sai de `ministerio_siafi`. Código que o mapa
    (`routers/emendas_federais.ORGAOS_SIAFI`) não conhece, ou órgão sem código:
    o órgão como veio (`nome_proprio`) — nada de "Órgão SIAFI 99000" inventado
    por cima de um nome que a fonte deu. Vazio -> "—"."""
    txt = str(orgao or "").strip()
    if not txt:
        return SEM_DADO
    m = re.match(r"(\d{5})\s*-?\s*(.*)$", txt)
    if not m:
        return nome_proprio(txt)
    codigo, nome_fonte = m.group(1), m.group(2).strip()
    from routers.emendas_federais import ORGAOS_SIAFI
    superior = codigo[:2] + "000"
    mapa = ministerio_siafi(superior) if superior in ORGAOS_SIAFI else None
    # ⚠️ O NOME DA FONTE VENCE O MAPA (revisão de 24/09/2026). O mapa tem UM nome
    # por código e não muda com o ano: "39000 - MINISTERIO DOS TRANSPORTES" saía
    # "Ministério da Infraestrutura" (extinto em 2023) e "25000 - MINISTERIO DA
    # FAZENDA", "Ministério da Economia". O mapa só entra (a) quando o código é o
    # PRÓPRIO ministério e o nome dele é o mesmo da fonte — aí dá os acentos
    # ("MINISTERIO DA SAUDE" -> "Ministério da Saúde") — ou (b) quando o órgão é
    # uma entidade VINCULADA (FUNASA, FNDE: código != superior), para dizer a qual
    # ministério ela pertence.
    if mapa and codigo != superior:
        return mapa
    if mapa and (not nome_fonte or _sem_acento(mapa) == _sem_acento(nome_fonte)):
        return mapa
    if nome_fonte:
        return _acentua_ministerio(nome_proprio(nome_fonte))
    return mapa or nome_proprio(txt)


def orgao_do_programa(programa_codigo) -> Optional[str]:
    """Os 5 primeiros dígitos do código de programa de 13 = órgão SIAFI — a regra
    de `ingestion/portal_transparencia.orgao_do_programa`, importada."""
    from ingestion.portal_transparencia import orgao_do_programa as _odp
    try:
        return _odp(str(programa_codigo or ""))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Formatação
# ---------------------------------------------------------------------------
def fmt_valor(v) -> str:
    """#,##0.00 do modelo, em pt-BR e sem "R$" (o cabeçalho já diz)."""
    try:
        return f"{float(v):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    except (TypeError, ValueError):
        return SEM_DADO


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _data_br(s) -> str:
    t = str(s or "").strip()
    if len(t) >= 10 and t[4] == "-" and t[7] == "-":
        return f"{t[8:10]}/{t[5:7]}/{t[:4]}"
    return t


def _ano(v) -> Optional[int]:
    try:
        a = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    return a if 1990 <= a <= 2100 else None


def _ano_do_numero(numero) -> Optional[int]:
    """'034595/2026' -> 2026."""
    return _ano(str(numero or "").rpartition("/")[2])


def _ponto(s: str) -> str:
    s = (s or "").strip()
    return s if not s or s.endswith((".", "!", "?")) else s + "."


def _morto(situacao) -> bool:
    """Cancelado, rejeitado, anulado, rescindido — a regra do RM."""
    return bool(situacao) and _fed_status(str(situacao)) == "dead"


def _fns_morta(situacao) -> bool:
    """Proposta do FNS que não é recurso: a regra do RM PARA O FNS
    (`rm_builder._fns_classifica` -> "Rejeitada", que o RM trata como morta em
    `_fns_retem`). ⚠️ NÃO `_morto`: `_fed_status` não conhece "arquivad" nem
    "bloquead", e uma proposta ARQUIVADA/BLOQUEADA entrava no total geral."""
    return bool(situacao) and _fns_classifica(str(situacao), "") == "Rejeitada"


def _convenio_fora(situacao) -> bool:
    """Convênio SIGCON fora do total: morto (a regra do RM) ou em CADASTRAMENTO
    (`rm_builder._em_cadastramento`, a palavra inteira — o RM nem o imprime:
    cadastro sem análise, sem celebração, sem dinheiro)."""
    return _morto(situacao) or _em_cadastramento(situacao)


def _convenio_vence(c: dict) -> bool:
    """O convênio SIGCON pode tomar o lugar da indicação estadual que carrega?
    Só quando ELE conta no total (nem morto nem em cadastramento) e tem valor.
    Senão a indicação fica: o caso real é Araújos, convênio 002567/2026 da SEAPA,
    R$ 0,00, "Cadastramento" — ele apagava do total a indicação que era o único
    registro do dinheiro."""
    return not _convenio_fora(c.get("situacao")) and _f(c.get("valor_total")) > 0


def _linha(fonte: str, x: dict, **kw) -> dict:
    base = {
        "fonte": fonte,
        "municipio": str(x.get("municipio_nome") or SEM_DADO).upper(),
        "municipio_id": x.get("municipio_id"),
        "ano": None, "recurso": "", "ministerio": SEM_DADO, "valor": 0.0,
        "referencias": [], "situacao": "", "area": OUTROS, "pago": False,
        "fora": None,
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Uma linha por instrumento
# ---------------------------------------------------------------------------
def linha_te(x: dict) -> dict:
    custeio, inv = _f(x.get("valor_custeio")), _f(x.get("valor_investimento"))
    so_inv = inv > 0 and custeio <= 0
    natureza = ("Investimento" if so_inv
                else "Custeio" if custeio > 0 and inv <= 0
                else "Custeio e Investimento" if custeio > 0 and inv > 0 else None)
    objetos = list(dict.fromkeys(x.get("objetos_executor") or []))
    base = " / ".join(objetos) or str(x.get("objeto") or "").strip()
    recurso = frase(base).strip() if base else "Transferência especial"
    recurso = recurso.rstrip(". ")
    recurso += (f" (Transferência especial – {natureza})" if natureza
                else " (Transferência especial)")
    ex = {"estado": x.get("execucao_estado"), "valor_pago": x.get("valor_pago"),
          "dt_ultimo_pagamento": x.get("dt_ultimo_pagamento")}
    sit = frase_execucao_te(ex, x.get("valor_total"))
    if x.get("relatorio_gestao"):
        sit += " " + x["relatorio_gestao"]
    impedido = _chave(x.get("situacao")) == "IMPEDIDO"
    if impedido:
        sit = "Plano impedido no Transferegov. " + sit
    cod = str(x.get("codigo") or "")
    return _linha(
        "plano_acao", x,
        # O ano do plano (`detalhe_core._ano_do_plano`); detalhe antigo sem ele
        # cai nos dígitos 5-8 do código ('09032024-070446' -> 2024).
        ano=_ano(x.get("ano")) or (_ano(cod[4:8]) if len(cod) >= 8 else None),
        recurso=recurso,
        # ⚠️ O órgão do PROGRAMA, como a API oficial manda — Fazenda em 2023-2025,
        # Economia até 2022, MGI em 2026 (captura de 14/09/2026). Sem dado, "—".
        ministerio=(x.get("orgao_programa") or SEM_DADO),
        valor=_f(x.get("valor_total")),
        referencias=[f"Plano de Ação: {x['codigo']}"] if x.get("codigo") else [],
        situacao=sit,
        area=area_por_funcoes(x.get("funcoes") or [], so_inv),
        pago=x.get("execucao_estado") == "pago",
        fora=GRUPO_NAO_RECURSO if impedido else None,
    )


def _objeto_fns(objeto) -> str:
    """'INCREMENTO MAC - ... — Proc 25000.1' -> sem o processo (vai na referência)."""
    return str(objeto or "").split(" — Proc", 1)[0].strip()


def linha_fns(x: dict) -> dict:
    tipo = str(x.get("tipo_proposta") or "").strip()
    recurso = frase(tipo) if tipo else frase(_objeto_fns(x.get("objeto")))
    # `valor_total` é a PARTE do autor na proposta; o pagamento é da PROPOSTA
    # inteira (`valor_proposta`) — "pago em parte" divide pelo total dela.
    valor = _f(x.get("valor_total"))
    total_proposta = _num(x.get("valor_proposta")) or valor
    vp, vpg = _num(x.get("vl_pago")), _num(x.get("vl_pagar"))
    dt = str(x.get("data_pagamento") or "").strip()
    morta = _fns_morta(x.get("situacao"))
    pago = bool(vp and vp > 0 and not (vpg and vpg > 0))
    if morta:
        # ⚠️ FORA DO TOTAL, e a frase diz POR QUÊ (revisão de 24/09/2026): uma
        # proposta ARQUIVADA/BLOQUEADA com repasse registrado saía só "Pagamento
        # realizado em …", sem o motivo — contradizendo a nota do grupo. Mostra a
        # situação primeiro (como o RM mostra `situacao_desc`) e o pagamento depois,
        # e não conta como "pago" para o título.
        sit = _ponto(frase(x.get("situacao") or "")) or "Proposta encerrada."
        if vp and vp > 0:
            sit += f" Repasse registrado: {_fmt_brl(vp)}" + (f" em {dt}." if dt else ".")
        pago = False
    elif pago:
        # A regra do RM (`rm_builder`, ramo FNS): repasse feito e nada a pagar.
        sit = f"Pagamento realizado em {dt}." if dt else "Pagamento realizado (data não coletada)."
    elif vp and vp > 0:
        sit = f"Pago em parte: {_fmt_brl(vp)} de {_fmt_brl(total_proposta)}"
        if abs(total_proposta - valor) > 0.01:
            sit += " da proposta"
        sit += f"; último pagamento em {dt}." if dt else "."
    elif x.get("situacao"):
        sit = _ponto(frase(x["situacao"]))
    elif vp == 0:
        sit = "Sem pagamento registrado."
    else:
        sit = "Situação da proposta não informada."
    return _linha(
        "fns", x, ano=_ano(x.get("ano")), recurso=recurso or "Proposta de saúde",
        ministerio="Ministério da Saúde",   # FNS = Fundo Nacional de SAÚDE
        valor=valor,
        referencias=[f"Proposta: {x['numero']}"] if x.get("numero") else [],
        situacao=sit, area="SAÚDE", pago=pago,
        fora=GRUPO_NAO_RECURSO if morta else None,
    )


def linha_voluntaria(x: dict) -> dict:
    refs = []
    if x.get("codigo_instrumento"):
        refs.append(f"Convênio: {x['codigo_instrumento']}")
    if x.get("numero_proposta"):
        refs.append(f"Proposta: {x['numero_proposta']}")
    if x.get("pac_origem"):
        refs.append(f"Novo PAC: {x['pac_origem']}")
    sit = _ponto(frase(x.get("situacao") or "")) or "Situação não informada."
    pago = False
    if x.get("desembolso_consultado"):
        vd, va = _f(x.get("valor_desembolsado")), _num(x.get("valor_a_desembolsar"))
        dt = str(x.get("dt_ultimo_desembolso") or "").strip()
        if vd > 0 and va is not None and va <= 0.01:
            pago = True
            sit += f" Pagamento realizado em {dt}." if dt else " Pagamento realizado."
        elif vd > 0:
            de = f" de {_fmt_brl(vd + va)}" if va is not None else ""
            sit += f" Pago em parte: {_fmt_brl(vd)}{de}"
            sit += f"; último pagamento em {dt}." if dt else "."
        else:
            sit += " Nenhum pagamento registrado."
    orgao = str(x.get("orgao") or "").strip()
    return _linha(
        "voluntaria", x, ano=_ano_do_numero(x.get("numero_proposta")),
        recurso=frase(x.get("objeto") or "") or "(objeto não informado)",
        # "36000 - MINISTERIO DA SAUDE" -> "Ministério da Saúde" (órgão superior).
        ministerio=ministerio_do_orgao(orgao),
        valor=_f(x.get("valor_global")), referencias=refs, situacao=sit,
        area=area_por_orgao(orgao, x.get("objeto")), pago=pago,
        fora=GRUPO_NAO_RECURSO if _morto(x.get("situacao")) else None,
    )


def linha_sigcon(x: dict, indicacoes_casadas=()) -> dict:
    refs = [f"Convênio: {x['numero']}"] if x.get("numero") else []
    refs += [f"Indicação: {i}" for i in indicacoes_casadas]
    sit = _ponto(frase(x.get("situacao") or "")) or "Situação não informada."
    vig = _data_br(x.get("dt_vigencia_atual") or x.get("dt_vigencia_final"))
    if vig:
        sit += f" Vigência até {vig}."
    orgao = str(x.get("orgao") or "").strip()
    return _linha(
        "sigcon", x, ano=_ano(x.get("ano")),
        recurso=frase(x.get("objeto") or "") or "(objeto não informado)",
        ministerio=nome_proprio(orgao) if orgao else SEM_DADO,
        valor=_f(x.get("valor_total")), referencias=refs, situacao=sit,
        area=area_por_orgao(orgao, x.get("objeto")),
        pago=False,   # o pagamento do SIGCON não é lido aqui: nunca "pago"
        # Morto ou em CADASTRAMENTO: fora do total, como o RM (que nem o imprime).
        fora=GRUPO_NAO_RECURSO if _convenio_fora(x.get("situacao")) else None,
    )


def linha_estadual(x: dict) -> dict:
    tipo = str(x.get("tipo_atendimento") or "").strip()
    tipo = "" if tipo in ("-", "--") else tipo
    benef = str(x.get("beneficiario") or "").strip()
    recurso = frase(tipo or x.get("grupo_despesa") or "Indicação estadual")
    if benef:
        recurso += f" – {nome_proprio(benef)}"
    valor = _f(x.get("valor_indicacao"))
    sit = _ponto(frase(x.get("status_indicacao") or "")) or "Situação não informada."
    pago = False
    vp = _num(x.get("valor_pago"))
    if vp is not None:
        # A planilha da SEGOV (24/09/2026). NULO = não trouxe; zero = afirmou zero.
        quando = _data_br(x.get("execucao_em"))
        fonte = f"planilha da SEGOV de {quando}" if quando else "planilha da SEGOV"
        if vp > 0 and vp >= valor - 0.01:
            pago = True
            sit += f" Pago: {_fmt_brl(vp)} ({fonte})."
        elif vp > 0:
            sit += f" Pago em parte: {_fmt_brl(vp)} de {_fmt_brl(valor)} ({fonte})."
        elif (_num(x.get("valor_empenhado")) or 0) > 0:
            sit += f" Empenhado, sem pagamento na {fonte}."
        else:
            sit += f" Sem pagamento na {fonte}."
    uo = str(x.get("uo_sigla") or "").strip()
    # ÁREA PELA UO; o TIPO só quando a UO não dá área. Juntar os dois num texto
    # só fazia "SES" + "Obras" casar SAÚDE e INFRAESTRUTURA -> OUTROS: a obra da
    # saúde (e da educação, SEE) sumia da faixa dela.
    area = area_por_orgao(uo, tipo)
    if area == OUTROS:
        area = area_por_orgao(tipo, tipo)
    return _linha(
        "emenda", x, ano=_ano(x.get("ano")), recurso=recurso,
        ministerio=uo or SEM_DADO, valor=valor,
        referencias=[f"Indicação: {x['nr_indicacao']}"] if x.get("nr_indicacao") else [],
        situacao=sit, area=area, pago=pago,
        fora=GRUPO_NAO_RECURSO if _morto(x.get("status_indicacao")) else None,
    )


def linha_pac(x: dict) -> dict:
    sit_txt = str(x.get("situacao") or "").strip()
    selecionada = _chave(sit_txt) in ("SELECIONADA", "SELECIONADO")
    ministerio = ministerio_siafi(orgao_do_programa(x.get("programa_codigo")))
    programa = str(x.get("programa") or "").strip()
    objeto = x.get("objeto") or programa
    # Área pelo ministério; sem ele (ou ministério sem área clara), pelo nome do
    # PROGRAMA ("Novo PAC Seleções - Saúde: UBS"), que é a política pública.
    area = area_por_orgao(ministerio, objeto) if ministerio else OUTROS
    if area == OUTROS:
        area = area_por_orgao(programa, objeto)
    return _linha(
        "pac", x, ano=_ano_do_numero(x.get("numero_proposta")),
        recurso=frase(objeto) or "Seleção do Novo PAC",
        ministerio=ministerio or SEM_DADO, valor=_f(x.get("valor_total")),
        referencias=[f"Proposta: {x['numero_proposta']}"] if x.get("numero_proposta") else [],
        situacao=f"Seleção do Novo PAC: {_ponto(frase(sit_txt))}" if sit_txt
        else "Seleção do Novo PAC: situação não informada.",
        area=area,
        pago=False,   # seleção não é pagamento
        # SÓ a selecionada é recurso (a regra do RM); o resto do funil fica fora.
        fora=None if selecionada else GRUPO_NAO_RECURSO,
    )


def linha_carteira(x: dict) -> dict:
    cod = x.get("codigo_emenda") or x.get("nr_emenda")
    benef = str(x.get("beneficiario_nome") or "").strip()
    recurso = f"Emenda federal nº {cod}" if cod else "Emenda federal (sem nº na fonte)"
    if benef:
        recurso += f" – {nome_proprio(benef)}"
    return _linha(
        "emenda_federal", x, ano=_ano(x.get("ano")), recurso=recurso,
        ministerio=ministerio_siafi(x.get("orgao_siafi")) or SEM_DADO,
        valor=_f(x.get("valor_total")),
        referencias=[f"Emenda: {cod}"] if cod else [],
        situacao=("Indicada na carteira da CGU; o instrumento que a executa não foi "
                  "identificado com segurança nesta base."),
        area=OUTROS, pago=False, fora=GRUPO_SEM_INSTRUMENTO,
    )


# ---------------------------------------------------------------------------
# O bloco de UM parlamentar
# ---------------------------------------------------------------------------
def linhas_do_detalhe(det: dict) -> list[dict]:
    """Todas as linhas do parlamentar — as da conta (`fora` None) e as de fora,
    já SEM as duplicatas da regra 1 do topo."""
    det = det or {}
    sigcon = det.get("sigcon") or []
    voluntarias = det.get("voluntarias") or []

    # Regra 1: indicação estadual executada por convênio SIGCON DESTE bloco — e
    # só o convênio que conta no total com valor vence (`_convenio_vence`).
    inds_por_conv: dict[int, list[str]] = {}
    conv_de: dict[tuple, int] = {}
    for i, c in enumerate(sigcon):
        if not _convenio_vence(c):
            continue
        for ind in c.get("indicacoes") or []:
            conv_de.setdefault((c.get("municipio_id"), str(ind).strip()), i)
    linhas: list[dict] = []
    estaduais: list[dict] = []
    for e in det.get("emendas") or []:
        k = (e.get("municipio_id"), str(e.get("nr_indicacao") or "").strip())
        if k[1] and k in conv_de:
            inds_por_conv.setdefault(conv_de[k], []).append(k[1])
            continue
        estaduais.append(linha_estadual(e))
    for i, c in enumerate(sigcon):
        linhas.append(linha_sigcon(c, sorted(inds_por_conv.get(i, []))))
    linhas += estaduais

    linhas += [linha_voluntaria(v) for v in voluntarias]
    linhas += [linha_te(t) for t in det.get("plano_acao") or []]

    # Regra 1: seleção do PAC que virou a voluntária deste bloco.
    origens = [v.get("pac_origem") for v in voluntarias if v.get("pac_origem")]
    for p in det.get("pac") or []:
        if any(_mesma_proposta(p.get("numero_proposta"), o) for o in origens):
            continue
        linhas.append(linha_pac(p))

    linhas += [linha_fns(f) for f in det.get("fns") or []]
    # Regra 2: a carteira que sobrou, fora do total.
    linhas += [linha_carteira(e) for e in det.get("emendas_federais") or []]
    return linhas


def montar_bloco(nome: str, det: dict, cidade: str) -> dict:
    """O bloco de UM parlamentar: título, faixas por área com subtotal, total e
    as seções de fora do total. `cidade` já em MAIÚSCULAS ("BOM DESPACHO" ou
    "TODOS OS MUNICÍPIOS")."""
    linhas = linhas_do_detalhe(det)
    conta = [l for l in linhas if not l["fora"]]
    fora_l = [l for l in linhas if l["fora"]]

    def _ordena(ls):
        return sorted(ls, key=lambda l: (-(l["ano"] or 0), -l["valor"], l["recurso"]))

    por_area: dict[str, list] = {}
    for l in conta:
        por_area.setdefault(l["area"], []).append(l)
    areas = []
    for area, ls in por_area.items():
        areas.append({"area": area, "linhas": _ordena(ls),
                      "subtotal": round(sum(l["valor"] for l in ls), 2)})
    areas.sort(key=lambda a: (a["area"] == OUTROS, -a["subtotal"], AREAS.index(a["area"])))

    fora = []
    for g in GRUPOS_FORA:
        ls = [l for l in fora_l if l["fora"] == g]
        if ls:
            fora.append({"grupo": g, "linhas": _ordena(ls),
                         "soma": round(sum(l["valor"] for l in ls), 2)})

    todas_pagas = bool(conta) and all(l["pago"] for l in conta) and not fora_l
    titulo = (f"RECURSOS {'PAGOS' if todas_pagas else 'PARA'} {cidade} – "
              f"EMENDAS INDICADAS POR {str(nome or '').strip().upper()}")
    return {
        "titulo": titulo,
        "todas_pagas": todas_pagas,
        "areas": areas,
        "total": round(sum(l["valor"] for l in conta), 2) if conta else None,
        "fora": fora,
        "n_linhas": len(linhas),
    }
