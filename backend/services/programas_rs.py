"""Catálogo dos programas estaduais de fomento do RIO GRANDE DO SUL.

⭐ POR QUE ISTO É CONTEÚDO CURADO E NÃO COLETA, e por que mesmo assim entra.

Nenhum desses programas publica dado estruturado por município: são páginas
institucionais, editais em PDF e chamamentos anunciados em notícia. Não há CSV,
não há API. A tentação seria deixá-los de fora até existir coletor — e essa é
exatamente a decisão errada, pela regra que organiza o roadmap do RS
(`docs/MAPA_RS.md` §13):

    Um painel de captação vale pelo que o gestor NÃO SABIA que existia. Omitir
    um programa porque a coleta é difícil transfere a ele o trabalho de
    descobrir sozinho — que é o que ele paga para não fazer.

Então entregamos o que dá: o que o programa é, quem opera, o que exige, como se
candidata e o link oficial. **E a tela diz, com todas as letras, que a abertura
de chamamento não é monitorada automaticamente** — meia verdade apresentada como
verdade inteira é pior que ausência.

⚠️ VALORES E EDIÇÕES SÃO DATADOS DE PROPÓSITO. Cada número aqui carrega a data
em que foi lido na fonte. Um "R$ 645 milhões" sem data envelhece em silêncio e um
dia vira mentira na tela do prefeito; com a data, o leitor sabe o que está vendo.
Ao atualizar, atualize a data junto.

⚠️ MORA EM `services/` e não em `routers/`: a imagem do worker não copia
`/app/routers` (ver o cabeçalho de `services/cauc_catalogo.py`). Se um alerta
sobre abertura de chamamento existir um dia, ele precisará deste catálogo.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Programa:
    chave: str
    nome: str
    orgao: str
    area: str                 # 'infraestrutura' | 'saude' | 'agropecuaria' | 'social'
    resumo: str
    # O que o município precisa ter/fazer. É a parte acionável: o gestor lê e
    # sabe se está apto hoje.
    exigencias: tuple[str, ...] = ()
    como: str = ""            # como se candidata
    url: str = ""
    # Números com a data em que foram lidos — ver o aviso do cabeçalho.
    numeros: str = ""
    observacao: str = ""


CATALOGO: tuple[Programa, ...] = (
    Programa(
        chave="pavimenta",
        nome="Avançar Pavimenta RS",
        orgao="Sedur / SOP — operado via DAER e Selt",
        area="infraestrutura",
        resumo="Pavimentação urbana por chamamento público, com contrapartida "
               "municipal. É o maior programa de obras do guarda-chuva Avançar.",
        exigencias=(
            "Contrapartida municipal (o percentual sai no edital de cada edição)",
            "Habilitação estadual válida (CHE) e adimplência no CADIN/RS",
            "Projeto de engenharia compatível com o objeto do chamamento",
        ),
        como="Adesão por chamamento público, quando a Sedur abre a edição. "
             "As edições anteriores foram anunciadas no site da secretaria.",
        url="https://www.sedur.rs.gov.br/avancar-pavimenta-rs",
        numeros="1ª e 2ª edições somam 445 municípios, R$ 645 milhões do Estado "
                "e R$ 475,4 milhões de contrapartida; 3ª edição em curso com 193 "
                "municípios e R$ 200 milhões (lido em 16/08/2026)",
    ),
    Programa(
        chave="avancar-saude",
        nome="Avançar na Saúde",
        orgao="SES-RS",
        area="saude",
        resumo="Guarda-chuva de investimento em saúde: obras, equipamentos e "
               "estruturação de serviços municipais.",
        exigencias=(
            "Adimplência no CADIN/RS — o Fundo Estadual de Saúde só paga a "
            "município adimplente",
            "Fundo Municipal de Saúde com cadastro regular",
        ),
        como="Conforme a linha: chamamento, emenda ou pactuação na CIB.",
        url="https://saude.rs.gov.br/",
        numeros="mais de R$ 950 milhões anunciados no programa (lido em 16/08/2026)",
    ),
    Programa(
        chave="assistir",
        nome="Programa Assistir",
        orgao="SES-RS",
        area="saude",
        resumo="Apoio financeiro a hospitais e serviços de saúde, incluindo os "
               "de gestão municipal.",
        exigencias=("Adimplência no CADIN/RS",
                    "Serviço habilitado junto à SES"),
        como="Pactuação com a SES, conforme a linha do programa.",
        url="https://saude.rs.gov.br/",
    ),
    Programa(
        chave="rbc-rs",
        nome="Rede Bem Cuidar RS (RBC/RS) — PIAPS",
        orgao="SES-RS",
        area="saude",
        resumo="Custeio MENSAL por equipe de atenção primária, repassado fundo a "
               "fundo. Diferente dos demais: é receita recorrente, não projeto.",
        exigencias=(
            "Equipe habilitada no modelo da Rede Bem Cuidar",
            "Adimplência no CADIN/RS para o repasse fundo a fundo",
        ),
        como="Adesão pela SES, com incentivo por equipe qualificada.",
        url="https://saude.rs.gov.br/rbcrs-incentivo",
        numeros="R$ 8.500 por equipe/mês (lido em 16/08/2026)",
        observacao="Por ser fundo a fundo e mensal, o valor aparece nos "
                   "pagamentos do FES — a conferência do que entrou é pelo "
                   "portal de pagamentos da SES.",
    ),
    Programa(
        chave="avancar-agropecuaria",
        nome="Avançar na Agropecuária",
        orgao="SEAPI / SDR",
        area="agropecuaria",
        resumo="Investimento em desenvolvimento rural: estradas vicinais, "
               "estruturação produtiva e apoio ao setor primário.",
        exigencias=("Habilitação estadual válida (CHE)",
                    "Contrapartida conforme a linha"),
        como="Chamamento e convênios via SDR/SEAPI.",
        url="https://sdr.rs.gov.br/avancar",
        numeros="recuperação de estradas vicinais até R$ 300 mil por município, "
                "via FUNRIGS (lido em 16/08/2026)",
    ),
    Programa(
        chave="feaper",
        nome="FEAPER — Fundo de Apoio ao Setor Primário",
        orgao="SEAPI / SDR",
        area="agropecuaria",
        resumo="Fundo estadual do setor primário, historicamente ligado à "
               "Consulta Popular — parte das demandas eleitas na região é "
               "executada por ele.",
        exigencias=("Projeto aprovado na linha do fundo",
                    "Habilitação estadual válida (CHE)"),
        como="Via SDR, frequentemente a partir de demanda eleita na Consulta "
             "Popular do COREDE.",
        url="https://sdr.rs.gov.br/",
        observacao="A ligação com a Consulta Popular é a razão de acompanhar as "
                   "duas telas juntas: a demanda eleita na região vira execução "
                   "por aqui.",
    ),
    Programa(
        chave="avancar-pocos",
        nome="Avançar Poços",
        orgao="SDR / Corsan-parceiros",
        area="agropecuaria",
        resumo="Perfuração e recuperação de poços artesianos para abastecimento "
               "em comunidades rurais.",
        exigencias=("Demanda cadastrada junto à SDR",
                    "Contrapartida ou cessão de área, conforme a linha"),
        como="Chamamento da SDR.",
        url="https://sdr.rs.gov.br/avancar",
    ),
)

# Bases normativas que valem para o conjunto — o gestor costuma pedir a fonte
# quando leva a proposta ao jurídico.
NORMAS = (
    ("Decreto nº 50.272/2013 e IN CAGE nº 06/2016",
     "convênios em programas setoriais estaduais"),
    ("LDO estadual do exercício",
     "define a contrapartida exigida de cada município"),
    ("Lei nº 13.019/2014 (MROSC)",
     "quando a parceria for com organização da sociedade civil"),
)

# ⭐ A FRASE QUE A TELA É OBRIGADA A MOSTRAR. Sem ela, um catálogo estático se
# passa por monitoramento — e o gestor confiaria que seria avisado de uma
# abertura de edital que ninguém está vigiando.
AVISO_NAO_AUTOMATICO = (
    "Este catálogo é mantido pela equipe do PACTHA a partir das páginas oficiais "
    "de cada programa. A abertura de chamamentos e editais ainda NÃO é "
    "monitorada automaticamente: confirme prazos e condições no site do órgão "
    "antes de decidir."
)


def por_area() -> dict[str, list[Programa]]:
    """O catálogo agrupado, na ordem em que a tela mostra."""
    out: dict[str, list[Programa]] = {}
    for p in CATALOGO:
        out.setdefault(p.area, []).append(p)
    return out


AREAS = {
    "infraestrutura": "Infraestrutura e obras",
    "saude": "Saúde",
    "agropecuaria": "Agropecuária e desenvolvimento rural",
    "social": "Assistência social",
}
