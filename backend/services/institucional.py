"""
Detecta e cadastra automaticamente parlamentares "institucionais" (rotulos
que nao sao deputados individuais).

Usado pelos pipelines de emendas para garantir que se aparecer um nome novo
do tipo "Comissao de Obras", "Bloco XYZ", "Programa ABC", "Bancada de SP",
etc. - ele e cadastrado como parlamentar institucional automaticamente.

Sem isso, esses rotulos novos seriam ignorados ou cadastrados sem padrao.
"""
import re
import unicodedata


# Keywords que identificam rotulos institucionais (case-insensitive)
KEYWORDS_INSTITUCIONAIS = [
    "BANCADA",
    "COMISS",  # Comissao, Comissao da Saude, etc.
    "BLOCO",
    "RELATOR",
    "PROGRAMA",
    "DOACAO", "DOAÇÃO",
    "RESOLUC",
    "PROPOSTA VOLUNTARIA",
    "EMENDA COLETIVA",
    "FETAEMG",
    "FAEMG",
    "VERIFICAR",  # placeholder Freitas - so cadastra se nao tiver
]

# Programas / siglas conhecidos (estaduais MG ou federais)
PROGRAMAS_CONHECIDOS = [
    "PROMAQ", "TRAVESSIA", "VIVAVALE", "MINAS COMUNICA",
    "AGUA PARA TODOS", "AGENTES DO BEM",
    "SIMEC", "PAR4", "PAR-4",
    "NOVO PAC", "PAC", "CFFO",
]


def is_institucional(nome: str) -> bool:
    """True se o nome parece ser institucional (nao parlamentar individual)."""
    if not nome: return False
    n = unicodedata.normalize("NFKD", nome.upper())
    n = "".join(c for c in n if not unicodedata.combining(c))
    return (
        any(kw in n for kw in KEYWORDS_INSTITUCIONAIS) or
        any(prog in n for prog in PROGRAMAS_CONHECIDOS)
    )


def normalize_institucional(nome: str) -> str:
    """Normaliza o nome de um rotulo institucional para inserir no DB.
    Garante consistencia (UPPER, sem acentos, sem espacos extras)."""
    if not nome: return ""
    n = unicodedata.normalize("NFKD", nome.upper())
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = re.sub(r"\s+", " ", n).strip()
    return n[:300]


def ensure_parlamentar(conn, nome: str, esfera: str = "federal", uf: str = "BR") -> int | None:
    """Garante que um parlamentar (individual OU institucional) existe no DB.
    Retorna o id. Idempotente: nao duplica se ja existir (case-insensitive).

    Para institucionais, padroniza para UPPER sem acentos.
    Para individuais, mantem capitalizacao original.
    """
    if not nome or len(nome.strip()) < 2:
        return None

    inst = is_institucional(nome)
    nome_db = normalize_institucional(nome) if inst else nome.strip()[:300]
    nome_busca = normalize_institucional(nome)  # sempre busca case-insensitive

    from sqlalchemy import text
    r = conn.execute(text("""
        SELECT id FROM parlamentares
        WHERE upper(translate(nome,
            'ÁÉÍÓÚÀÂÊÔÃÕÇáéíóúàâêôãõç',
            'AEIOUAAEOAOCAEIOUAAEOAOC'
        )) = upper(translate(:n,
            'ÁÉÍÓÚÀÂÊÔÃÕÇáéíóúàâêôãõç',
            'AEIOUAAEOAOCAEIOUAAEOAOC'
        ))
        LIMIT 1
    """), {"n": nome_busca}).first()

    if r:
        return r[0]

    # Cadastra novo
    res = conn.execute(text("""
        INSERT INTO parlamentares (nome, esfera, uf, legislatura)
        VALUES (:n, :e, :u, '2023-2027')
        RETURNING id
    """), {
        "n": nome_db,
        "e": esfera,
        "u": uf if uf else ("MG" if esfera == "estadual" else "BR"),
    })
    return res.scalar()
