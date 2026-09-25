"""Recursos recebidos por PASTA — a regra única que classifica cada linha das
transferências da CGU (`ingestion/cgu_transferencias.py`).

Uma função, usada pela rota e pelos testes: "o mesmo dado dá a mesma conta em
toda tela" (regra do dono). Nada disso é gravado no banco — a classificação é
feita na LEITURA, então mudar a regra aqui vale para os 24 meses já carregados
sem recoletar nada.

A PASTA (medido no arquivo nacional de 08/2026, 144.284 linhas), na ordem em que
a regra decide — a primeira que casa vence:

1. **Royalties** — pela AÇÃO: 0A53 (petróleo e gás), 0547 (CFEM, mineração),
   0546 (recursos hídricos), 0223 (Itaipu). Vêm como "Constitucionais e
   Royalties" e SEM órgão (`CÓDIGO ÓRGÃO SIAFI = -1`), por isso a ação decide.
2. **Constitucionais (FPM, FUNDEB, ITR)** — o resto do tipo "Constitucionais e
   Royalties": FPM (0045), FUNDEB (0C33), complementação da União ao FUNDEB
   (00SB — vem com função 12 Educação, mas é FUNDEB, e FUNDEB é constitucional),
   ITR (006M), IOF-ouro (00H6). ⚠️ Só entram no arquivo DEPOIS que o mês fecha.
3. **Defesa civil** — subfunção 182 (Defesa civil) ou ação 22BO. Vem ANTES da
   função porque a Defesa Civil é função 06 (Segurança pública) no MIDR e 15
   (Urbanismo) no Ministério das Cidades (8865, riscos de movimento de massa).
4. **Saúde** — função 10, ou órgão 36xxx (Ministério da Saúde, Funasa 36211).
5. **Educação** — função 12, ou órgão 26xxx. ⚠️ O salário-educação (0369) é
   FNDE com função 28 (Encargos especiais): sem o órgão ele cairia em Outras.
6. **Assistência social** — função 08, ou órgão 55xxx (FNAS 55001, MDS 55000).
7. **Cultura** — função 13, ou órgão 42xxx (MinC) / 34902 (Fundo Nacional de
   Cultura). ⚠️ A PNAB/Aldir Blanc (00UV) é MinC com função 28.
8. **Outras** — o que sobrar (Cidades, Integração fora da Defesa Civil, Esporte,
   Agricultura, Fazenda...). Nada é descartado.

O FAVORECIDO (quem recebeu), para separar o que é do MUNICÍPIO do que só está
NELE — a pergunta da regra do dono "nada é descartado, mas fica fora das contas":

- `prefeitura`  — o CNPJ da prefeitura (`municipios.cnpj`);
- `fundo`       — fundo municipal (FMS, FMAS, FUNDEB municipal...), pelo nome;
- `secretaria`  — secretaria/departamento municipal com CNPJ próprio (o
                  salário-educação vai à SECRETARIA de educação, não à prefeitura);
- `orgao_municipal` — outro órgão da administração municipal (tipo "Administração
                  Pública Municipal" ou nome com MUNICIPIO/PREFEITURA);
- `escola`      — caixa escolar, APM, CPM, conselho escolar: a unidade executora
                  do PDDE. Entidade que recebe do FNDE é escola por definição; o
                  nome só completa. ⚠️ Pode ser de escola ESTADUAL — não dá para
                  saber pelo nome —, por isso fica FORA do total do município;
- `entidade`    — entidade sem fins lucrativos, empresa, fundação (em Santa Maria,
                  a fundação de apoio da UFSM recebeu R$ 3,08 mi em 09/2026);
- `outro_ente`  — Estado ou outro ente que só está sediado no município.

`DO_MUNICIPIO` = prefeitura + fundo + secretaria + órgão municipal: é o total da
tela. Escola e entidade aparecem em grupo próprio, fora da conta.
"""
from __future__ import annotations

import re
import unicodedata

# (chave, rótulo) na ordem em que a tela mostra.
PASTAS: tuple[tuple[str, str], ...] = (
    ("constitucionais", "Constitucionais (FPM, FUNDEB, ITR)"),
    ("saude", "Saúde"),
    ("educacao", "Educação"),
    ("assistencia", "Assistência social"),
    ("cultura", "Cultura"),
    ("defesa_civil", "Defesa civil"),
    ("royalties", "Royalties e compensações"),
    ("outras", "Outras"),
)
ROTULO_PASTA = dict(PASTAS)

GRUPOS: tuple[tuple[str, str], ...] = (
    ("prefeitura", "Prefeitura"),
    ("fundo", "Fundos municipais"),
    ("secretaria", "Secretarias municipais"),
    ("orgao_municipal", "Outros órgãos municipais"),
    ("escola", "Escolas (caixas escolares, APM)"),
    ("entidade", "Entidades"),
    ("outro_ente", "Outros entes sediados no município"),
)
ROTULO_GRUPO = dict(GRUPOS)
DO_MUNICIPIO = frozenset({"prefeitura", "fundo", "secretaria", "orgao_municipal"})

ACOES_ROYALTIES = frozenset({"0A53", "0547", "0546", "0223"})
ACOES_DEFESA_CIVIL = frozenset({"22BO"})
# O FNDE: a entidade que recebe dele é ESCOLA — a unidade executora do PDDE (0515)
# ou a escola comunitária/filantrópica do PNAE. Nome não é preciso para isso.
ORGAO_FNDE = "26298"


def _s(v) -> str:
    return (v or "").strip()


def pasta(tipo_transferencia: str | None, orgao: str | None, funcao: str | None,
          subfuncao: str | None, acao: str | None) -> str:
    """A pasta de UMA linha. Ver a ordem das regras no cabeçalho."""
    acao = _s(acao).upper()
    orgao = _s(orgao)
    funcao = _s(funcao).zfill(2) if _s(funcao) else ""
    subfuncao = _s(subfuncao)
    if acao in ACOES_ROYALTIES:
        return "royalties"
    if _s(tipo_transferencia).lower().startswith("constitucionais"):
        return "constitucionais"
    if subfuncao == "182" or acao in ACOES_DEFESA_CIVIL:
        return "defesa_civil"
    if funcao == "10" or orgao.startswith("36"):
        return "saude"
    if funcao == "12" or orgao.startswith("26"):
        return "educacao"
    if funcao == "08" or orgao.startswith("55"):
        return "assistencia"
    if funcao == "13" or orgao.startswith("42") or orgao == "34902":
        return "cultura"
    return "outras"


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.upper())
                   if unicodedata.category(c) != "Mn")


# ⚠️ "FUNDO" NO FIM DO NOME NÃO: "MUNICIPIO DE PASSO FUNDO" e "MUNICIPIO DE POCO
# FUNDO" viravam fundo. No meio, sim, e sem `\b` de propósito — a CGU publica
# (medido em 08-09/2026) "SSFUNDO MUNICIPAL", "1201FUNDO MUNICIPAL",
# "FUNDOMUNICIPAL", "FUNDO MINICIPAL", "FUNDO MJNICIPAL", "FUNDO M SAUDE",
# "FUNCO MUNICIPAL". O fundo ESTADUAL é barrado antes, por `_RX_ESTADO`.
_RX_FUNDO = re.compile(r"FUNDO(?!\s*$)|FUNCO MUNICIPAL|\bFUMAS|"
                       r"\bF\.? ?M\.? ?S\b|\bF\.? ?M\.? ?A\.? ?S\b|\bFUNDEB\b")
_RX_MUN = re.compile(r"MUNICIP|MUNCIPIO|PREFEIT|\bMUN\b")
_RX_SECRETARIA = re.compile(r"\bSECRETARIA\b|\bSEC\.?\s|\bDEPARTAMENTO\b|\bDIRETORIA\b|"
                            r"\bDIVISAO\b|\bSECAO\b|\bGERENCIA\b")
# "FUNDO ESTADUAL DE SAUDE", "ESTADO DO MARANHAO - FUNDO ESTADUAL", "FUNDO DE SAUDE
# DO DISTRITO FEDERAL": vêm como "Administração Pública", sem esfera.
_RX_ESTADO = re.compile(r"\bESTADO\b|\bESTADUA|\bGOVERNO DO\b|\bDISTRITO FEDERAL\b")
_RX_ESCOLA = re.compile(r"CAIXA ESCOLAR|\bPAIS\b.*\bMESTRES\b|\bPAIS\b.*\bPROF|\bMESTRES\b.*\bPAIS\b|"
                        r"\bC\.?P\.?M\.?\b|\bA\.?P\.?M\.?F?\b|\bA\.?P\.?P\.?\b|CONSELHO ESCOLAR|"
                        r"CONSELHO ESCOLA|CONSELHO DELIBERATIVO|UNIDADE EXECUTORA|"
                        r"COLEGIADO ESCOLAR|UNIDADE ESCOLAR|ESCOLA (MUNICIPAL|ESTADUAL)")


def grupo_favorecido(doc: str | None, nome: str | None, tipo: str | None,
                     orgao: str | None, cnpj_prefeitura: str | None) -> str:
    """Quem recebeu, em um dos `GRUPOS`. Ver o cabeçalho."""
    doc = re.sub(r"\D", "", doc or "")
    if cnpj_prefeitura and doc == cnpj_prefeitura:
        return "prefeitura"
    n = _sem_acento(_s(nome))
    t = _sem_acento(_s(tipo))
    if t.startswith("ADMINISTRACAO PUBLICA ESTADUAL") or t.startswith("ADMINISTRACAO PUBLICA FEDERAL"):
        return "outro_ente"
    municipal = t.startswith("ADMINISTRACAO PUBLICA MUNICIPAL") or bool(_RX_MUN.search(n))
    # "Sem Informação" também traz fundo municipal (FUNDO MUNICIPAL DE CULTURA,
    # medido em 09/2026): passa pelas mesmas perguntas de nome.
    publico = t.startswith("ADMINISTRACAO PUBLICA") or t.startswith("SEM INFORMACAO")
    if publico:
        # "Administração Pública" (sem esfera) é como a CGU classifica os FUNDOS
        # — e também um órgão estadual sediado aqui; o nome desempata.
        if _RX_ESTADO.search(n) and not municipal:
            return "outro_ente"
        if _RX_FUNDO.search(n):
            return "fundo"
        if _RX_ESCOLA.search(n) and "SECRETARIA" not in n:
            return "escola"
        if _RX_SECRETARIA.search(n) and municipal:
            return "secretaria"
        if municipal:
            return "orgao_municipal"
        if t.startswith("ADMINISTRACAO PUBLICA"):
            return "outro_ente"
    # Entidade sem fins lucrativos que recebe do FNDE é escola (PDDE/PNAE). Só
    # ela: com o FNDE também recebem o Banco do Brasil e uma empresa de obras do
    # Estado do RJ (medido em 09/2026), que escola não são.
    sem_fins = t.startswith("ENTIDADES SEM FINS") or t.startswith("SEM INFORMACAO")
    if (sem_fins and _s(orgao) == ORGAO_FNDE) or _RX_ESCOLA.search(n):
        return "escola"
    return "entidade"
