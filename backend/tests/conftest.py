"""
Coloca `backend/` no sys.path para os testes importarem como o app importa
(`from services.x import y`), rodando o pytest da raiz do repo ou de backend/.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
