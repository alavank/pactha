"""
Coloca `backend/` no sys.path para os testes importarem como o app importa
(`from services.x import y`), rodando o pytest da raiz do repo ou de backend/.

⚠️ E DA AS DUAS VARIAVEIS SEM AS QUAIS A SUITE NAO COLETA. `config.Settings`
exige `DATABASE_URL` e `JWT_SECRET`; qualquer teste que importe um router puxa
`database.py`, que chama `get_settings()` no import. Sem elas o pytest morre na
COLETA — medido em 02/09/2026: **40 arquivos de teste**, um terco da suite,
falhando antes de rodar uma linha, com um `ValidationError` do pydantic que nao
parece com "faltou env" para quem le de passagem.

Os valores sao de mentira de proposito e NAO abrem conexao: nenhum teste deste
repo fala com Postgres (nao existe banco de teste — SQL se valida com `pglast`).
O que eles fazem e deixar o import acontecer.

⚠️ `setdefault`, e nunca atribuicao: quem exporta um `DATABASE_URL` de verdade
antes de rodar continua com o dele. Substituir seria apontar um teste para um
banco que o dono nao escolheu.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://teste:teste@localhost/teste")
os.environ.setdefault("JWT_SECRET", "segredo-de-teste-nao-usar-em-lugar-nenhum")

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
