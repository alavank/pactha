"""
Job diario que envia alertas por email:
1. Editais novos (criados nas ultimas 24h)
2. Convenios com vigencia critica (<30 dias)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date, datetime, timedelta
from sqlalchemy import create_engine, text
from config import get_settings
from services.notifications import send_email, render_editais_alert, render_vigencia_alert, is_configured


def main():
    if not is_configured():
        print("SMTP nao configurado. Set SMTP_HOST/USER/PASSWORD nos secrets.")
        return

    settings = get_settings()
    engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))

    with engine.connect() as conn:
        # 1) Listar emails dos usuarios analyst/admin/gestor ativos
        users = conn.execute(text(
            "SELECT email FROM users WHERE active=true AND role IN ('admin','analyst','gestor')"
        )).fetchall()
        emails = [u[0] for u in users]
        if not emails:
            print("Nenhum destinatario.")
            return
        print(f"Destinatarios: {len(emails)}")

        # 2) Editais novos (criados nas ultimas 24h)
        cutoff = datetime.now() - timedelta(hours=24)
        editais = conn.execute(text("""
            SELECT titulo, orgao_concedente, area, valor_estimado, dt_fim
            FROM editais
            WHERE created_at > :c
            ORDER BY created_at DESC
            LIMIT 50
        """), {"c": cutoff}).fetchall()

        editais_dicts = [
            {"titulo": r[0], "orgao": r[1], "area": r[2],
             "valor_estimado": float(r[3] or 0), "dt_fim": r[4].strftime("%d/%m/%Y") if r[4] else "-"}
            for r in editais
        ]
        if editais_dicts:
            subj, html = render_editais_alert(editais_dicts)
            send_email(emails, subj, html)
            print(f"Alerta de {len(editais_dicts)} editais novos enviado")

        # 3) Convenios vencendo em < 30 dias
        hoje = date.today()
        em_30 = hoje + timedelta(days=30)
        vencendo = conn.execute(text("""
            SELECT nr_convenio, orgao_concedente, objeto, dt_fim_vigencia
            FROM convenios_federal
            WHERE dt_fim_vigencia BETWEEN :h AND :f
              AND LOWER(situacao) NOT IN ('concluido', 'concluido', 'anulado', 'cancelado')
            ORDER BY dt_fim_vigencia ASC
        """), {"h": hoje, "f": em_30}).fetchall()

        vencendo_dicts = [
            {"nr_convenio": r[0], "orgao": r[1], "objeto": (r[2] or "")[:120],
             "dias_restantes": (r[3] - hoje).days if r[3] else 0,
             "dt_fim": r[3].strftime("%d/%m/%Y") if r[3] else "-"}
            for r in vencendo
        ]
        if vencendo_dicts:
            subj, html = render_vigencia_alert(vencendo_dicts)
            send_email(emails, subj, html)
            print(f"Alerta de {len(vencendo_dicts)} convenios vencendo enviado")

        if not editais_dicts and not vencendo_dicts:
            print("Nada novo para alertar hoje.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback; traceback.print_exc()
        sys.exit(1)
