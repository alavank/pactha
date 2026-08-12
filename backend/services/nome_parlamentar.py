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

import unicodedata

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
