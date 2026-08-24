"""Catalogo das CONSULTAS (fontes) que compoem o Relatorio de Monitoramento.

⚠️ A CHAVE DESTE CATALOGO E, LITERALMENTE, A STRING QUE O ITEM CARREGA EM
`item["fonte"]` NO services/rm_builder.py. Nao e um rotulo paralelo: e a MESMA
palavra, comparada com `in` no filtro de `add_item`. Fonte nova nasce em DOIS
lugares e nos dois com a mesma palavra — a chamada de `add_item` la e uma linha
aqui — e backend/tests/test_rm_fontes.py le o codigo-fonte do builder e quebra
no dia em que os dois divergirem.

⚠️ E O BACKEND QUE MANDA. A tela NAO tem lista de consultas escrita em
TypeScript: ela pede `GET /api/rm/fontes` e desenha o que vier. O precedente e
`services/telas_catalog.py` x `frontend/src/lib/telas.ts` — a mesma lista nos
dois lados, que ja divergiu em rotulo e em chave. Aqui divergir nao deixa a tela
feia: deixa o filtro SEM EFEITO, calado, porque a chave nao casa com nada.

CONVENCAO DO VAZIO (a mesma dos anos, a mesma do MultiSelect da tela):
selecao VAZIA = TODAS as consultas = o RM completo de hoje, byte a byte.
`normalizar` devolve [] tambem quando TODAS estao marcadas — "marquei tudo" e
"nao marquei nada" precisam ser o MESMO relatorio, e nao dois, porque esta lista
ENTRA NA IDENTIDADE do RM (municipio_id, anos, fontes).

Por que na identidade e nao como atributo: gerar "so TransfereGov de 2026" NAO
PODE apagar o RM completo de 2026. O POST /api/rm e um UPSERT
(`ON CONFLICT DO UPDATE`), entao um `fontes` fora da chave faria o relatorio
filtrado sobrescrever o completo — destruicao silenciosa de trabalho.
"""

# Ordem desta lista = ordem do dropdown. FEDERAIS primeiro, ESTADUAIS depois,
# como o proprio RM ordena as secoes.
#
# `rotulo` e o nome longo (dropdown, onde ha espaco); `curto` e o nome que cabe
# num selo de lista e numa linha de PDF.
#
# ⚠️ "SIGCONV" NAO EXISTE. O dono escreveu isso no pedido, mas sao dois sistemas
# diferentes com nomes parecidos: SICONV e o nome ANTIGO do TransfereGov federal
# (hoje `voluntaria`), e SIGCON-MG e o sistema ESTADUAL de Minas. Os rotulos
# abaixo saem no dropdown, no selo da lista e no PDF entregue ao prefeito —
# confirmar com ele antes de considerar fechado.
FONTES_RM = [
    # --- FEDERAIS ---
    {"chave": "voluntaria", "rotulo": "TransfereGov — Transferências Voluntárias (convênios)", "curto": "TransfereGov"},
    {"chave": "transferencia_especial", "rotulo": "TransfereGov — Transferência Especial (Emenda Pix)", "curto": "Emenda Pix"},
    {"chave": "pac", "rotulo": "TransfereGov — Novo PAC / Seleções", "curto": "Novo PAC"},
    {"chave": "fns", "rotulo": "Fundo Nacional de Saúde (FNS)", "curto": "FNS"},
    {"chave": "simec", "rotulo": "SIMEC/PAR — Liberações (MEC)", "curto": "SIMEC"},
    {"chave": "simec_termo", "rotulo": "SIMEC/PAR — Termos de Compromisso (MEC)", "curto": "SIMEC Termos"},
    # --- ESTADUAIS ---
    {"chave": "sigcon", "rotulo": "SIGCON-MG — Convênios Estaduais", "curto": "SIGCON"},
    {"chave": "emenda_estadual", "rotulo": "SIGCON-MG — Emendas / Indicações Estaduais", "curto": "Emendas MG"},
]

CHAVES = tuple(f["chave"] for f in FONTES_RM)
_CURTOS = {f["chave"]: f["curto"] for f in FONTES_RM}


def catalogo() -> list[dict]:
    """O que a tela desenha. Copia rasa de proposito: quem consome nao edita o
    catalogo do processo por acidente."""
    return [dict(f) for f in FONTES_RM]


def normalizar(fontes) -> list[str]:
    """Lista canonica de consultas: so chave conhecida, sem repetir, ORDENADA.

    ORDENADA porque a identidade do RM e um indice UNICO sobre ARRAY, e para o
    Postgres {'fns','pac'} e {'pac','fns'} sao chaves DIFERENTES. Sem esta
    ordenacao, o mesmo pedido com as caixas marcadas noutra ordem criaria um
    SEGUNDO relatorio identico ao primeiro. E o mesmo cuidado que `anos` ja tem
    em routers/rm.py.

    Chave desconhecida e DESCARTADA (e nao 400): a tela so oferece o que veio
    deste catalogo, entao chave estranha e link velho, URL digitada a mao ou
    cliente antigo — derrubar a geracao por causa disso nao ajuda ninguem. Se
    sobrar vazio, o pedido vira o COMPLETO, que e o padrao seguro.

    TODAS marcadas devolve [] — ver o cabecalho do modulo."""
    limpo = sorted({str(f).strip() for f in (fontes or []) if str(f).strip() in CHAVES})
    return [] if len(limpo) == len(CHAVES) else limpo


def no_escopo(selecao, fonte: str) -> bool:
    """Este item entra no relatorio? Selecao VAZIA = todas (o completo de hoje).

    PONTO UNICO DO RECORTE: `rm_builder.add_item` chama isto para as NOVE
    insercoes de item (as DUAS do FNS inclusive), e o laco das voluntarias chama
    de novo para saber se pode alimentar a deduplicacao do Novo PAC.

    Comparacao EXATA, nunca por prefixo: "simec" (liberacoes) e "simec_termo"
    (o instrumento) sao consultas diferentes, e um `startswith` fundiria as
    duas."""
    if not selecao:
        return True
    return (fonte or "") in selecao


def rotulo_longo(fontes) -> str:
    """Nomes curtos separados por virgula — vai no TITULO padrao do RM e na linha
    de escopo do PDF.

    Vazio devolve "" e NAO "Todas as consultas": quem chama usa o vazio para nao
    escrever nada, e e assim que o RM completo continua com o titulo e a pagina
    identicos aos de hoje."""
    return ", ".join(_CURTOS.get(k, k) for k in (fontes or []))


def slug(fontes) -> str:
    """Pedaco do NOME DO ARQUIVO. Vazio = "" (o completo mantem o nome de hoje).

    Sem isto o RM filtrado e o completo baixam com o MESMO nome
    (`RM-Completo-Monte_Siao-01-07-2026.pdf`) e o segundo sobrescreve o primeiro
    na pasta de downloads: dois documentos diferentes, um arquivo so. Usa a
    CHAVE crua (ASCII, sem espaco nem acento) porque o valor entra num header
    `Content-Disposition` que nao tem `filename*=UTF-8''`."""
    return "-".join(fontes or [])
