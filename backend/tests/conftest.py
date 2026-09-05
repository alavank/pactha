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

# ⚠️ E LIGA O BI, QUE E A CONFIGURACAO DE PRODUCAO. As cinco APIs tem `BI_MODULE`
# no Coolify (conferido em 05/09/2026 pela API), entao `pytest` sem esta linha
# testava uma configuracao que NAO existe em lugar nenhum: com a flag desligada
# o router /api/bi/* nem e montado, e tres testes de `test_registro_rotas.py`
# ficavam vermelhos para sempre — a allowlist prometia rotas de BI que o app
# daquele processo nao tinha.
#
# Por que isso importa mais do que parece: teste vermelho permanente nao e um
# teste a menos, e a suite INTEIRA a menos. O valor de um alarme esta no
# contraste, e "3 failed" fixo ensina o time a ler qualquer numero vermelho como
# ruido — inclusive o dia em que ele for regressao de verdade. Em 05/09/2026
# eram 10 vermelhos permanentes (7 do modulo Telegram, ja removido, 3 destes), e
# entre eles estava justamente o guardiao da chave estrangeira que impede uma
# migration de derrubar o boot de um tenant NOVO.
#
# `setdefault` de novo, e pela mesma razao das duas de cima: quem quiser rodar a
# suite com o BI desligado exporta `BI_MODULE=0` antes e continua no comando.
os.environ.setdefault("BI_MODULE", "true")

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
