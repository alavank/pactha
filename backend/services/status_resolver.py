"""
Resolve a frase de "Situacao atual" no padrao Freitas a partir dos campos do
convenio. Sem isso, o RM exibe apenas a `situacao` macro do scraper (ex.:
"Em execucao") que e generica demais.

O RM da Freitas usa frases combinadas como:
  - "Pendente de empenho."
  - "Empenhado em 31/03/2026. Pendente de desembolso."
  - "Empenho realizado em 07/04/2026. Pendente de desembolso."
  - "Em desembolso parcial. Saldo a desembolsar R$ X."
  - "Pagamento realizado em 05/05/2026. Em prestacao de contas."
  - "Prestacao de contas em analise tecnica."
  - "Concluido. Aprovada com ressalvas."
"""
from datetime import date
from typing import Any


def fmt_date_br(d: Any) -> str | None:
    if not d:
        return None
    if isinstance(d, str):
        try:
            from datetime import datetime
            d = datetime.fromisoformat(d).date()
        except Exception:
            return d
    try:
        return d.strftime("%d/%m/%Y")
    except Exception:
        return str(d)


def resolve_status(c, esfera: str = "federal") -> str:
    """Constroi a frase completa de situacao atual."""
    sit_raw = (getattr(c, "situacao", None) or "").strip()
    sit_lower = sit_raw.lower()

    # Campos comuns
    val_global = float(getattr(c, "valor_global", 0) or getattr(c, "valor_total", 0) or 0)
    val_repasse = float(getattr(c, "valor_repasse", 0) or getattr(c, "valor_concedente", 0) or 0)
    val_emp = float(getattr(c, "valor_empenhado", 0) or 0)
    val_des = float(getattr(c, "valor_desembolsado", 0) or 0)
    dt_emp = getattr(c, "dt_empenho", None)
    dt_des = getattr(c, "dt_desembolso", None)
    dt_vig = getattr(c, "dt_fim_vigencia", None) or getattr(c, "dt_vigencia_atual", None) \
             or getattr(c, "dt_vigencia_final", None)

    # 1. Estados FINAIS - prevalecem sobre tudo
    finais = {
        "anulad": "Anulado.",
        "cancelad": "Cancelado.",
        "rescindid": "Rescindido.",
    }
    for kw, frase in finais.items():
        if kw in sit_lower:
            return frase

    # 2. Prestacao aprovada (com ou sem ressalva)
    if "aprovada com ressalvas" in sit_lower or "aprovada com ressalva" in sit_lower:
        return "Concluido. Prestacao de contas aprovada com ressalvas."
    if "aprovad" in sit_lower and ("prestac" in sit_lower or "conta" in sit_lower):
        return "Concluido. Prestacao de contas aprovada."

    # 3. Prestacao em analise/diligencia
    if "diligencia" in sit_lower:
        return "Em diligencia (prestacao de contas)."
    if "recurso" in sit_lower and "prestac" in sit_lower:
        return "Em recurso (prestacao de contas)."
    if any(kw in sit_lower for kw in ["analise tecnica", "analise financeira"]):
        return "Prestacao de contas em analise tecnica/financeira."
    if "analise" in sit_lower and "prestac" in sit_lower:
        return "Prestacao de contas em analise."

    # 4. Pagamento ja realizado
    if dt_des:
        base = f"Pagamento realizado em {fmt_date_br(dt_des)}."
        if dt_vig and dt_vig < date.today():
            return f"{base} Em prestacao de contas."
        return base

    # 5. Empenhado mas nao desembolsado
    if dt_emp:
        return f"Empenho realizado em {fmt_date_br(dt_emp)}. Pendente de desembolso."
    if val_emp > 0 and val_des == 0:
        return "Empenhado. Pendente de desembolso."

    # 6. Desembolso parcial (calculo)
    if val_emp > 0 and val_des > 0 and val_des < val_emp:
        falta = val_emp - val_des
        falta_fmt = f"R$ {falta:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"Em desembolso parcial. Saldo a desembolsar {falta_fmt}."

    # 7. Vigencia vencida sem desembolso -> em prestacao
    if dt_vig and dt_vig < date.today() and val_des == 0:
        return "Vigencia encerrada. Pendente de prestacao de contas."

    # 8. Pendente de empenho (default federal sem dt_emp/dt_des)
    if esfera == "federal":
        if any(kw in sit_lower for kw in ["pendente", "elabora", "proposta", "plano"]):
            return "Pendente de empenho."
        if not sit_raw:
            return "Pendente de empenho."

    # 9. Em execucao/em vigor (estaduais)
    if "vigor" in sit_lower or "execuc" in sit_lower:
        if dt_vig:
            return f"Em vigor. Vigencia ate {fmt_date_br(dt_vig)}."
        return "Em vigor."

    # 10. Promessa (estadual SES)
    if "promessa" in sit_lower:
        return "Promessa de indicacao."

    # 11. Fallback - mantem a situacao raw com primeira letra maiuscula
    return sit_raw[0].upper() + sit_raw[1:] + ("." if not sit_raw.endswith(".") else "")
