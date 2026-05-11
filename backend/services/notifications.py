"""
Notificacoes por email (alertas de editais novos + vigencia).
SMTP via env vars: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM.
"""
import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Iterable

logger = logging.getLogger("notifications")


def _smtp_config():
    return {
        "host": os.getenv("SMTP_HOST"),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": os.getenv("SMTP_USER"),
        "password": os.getenv("SMTP_PASSWORD"),
        "from_addr": os.getenv("SMTP_FROM") or os.getenv("SMTP_USER"),
        "use_tls": os.getenv("SMTP_TLS", "true").lower() == "true",
    }


def is_configured() -> bool:
    cfg = _smtp_config()
    return all([cfg["host"], cfg["user"], cfg["password"]])


def send_email(to: Iterable[str] | str, subject: str, html_body: str, text_body: str | None = None) -> bool:
    """Envia email HTML. Retorna True se enviou."""
    if not is_configured():
        logger.warning("SMTP nao configurado - email NAO enviado")
        return False

    cfg = _smtp_config()
    if isinstance(to, str):
        to = [to]
    to_list = list(to)
    if not to_list:
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = cfg["from_addr"]
    msg["To"] = ", ".join(to_list)
    msg["Subject"] = subject
    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as server:
            if cfg["use_tls"]:
                server.starttls()
            server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["from_addr"], to_list, msg.as_string())
        logger.info(f"Email enviado para {to_list[:3]}{'...' if len(to_list)>3 else ''}: {subject}")
        return True
    except Exception as e:
        logger.exception(f"Falha SMTP: {e}")
        return False


def render_editais_alert(editais: list[dict], municipio_nome: str = None) -> tuple[str, str]:
    """Retorna (subject, html) para alerta de editais novos."""
    n = len(editais)
    subject = f"[PACTA] {n} novo{'s' if n>1 else ''} edital{'is' if n>1 else ''} relevante{'s' if n>1 else ''}"
    if municipio_nome:
        subject += f" - {municipio_nome}"

    items_html = ""
    for e in editais[:20]:
        items_html += f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #eee;">
            <strong>{e.get('titulo', '-')}</strong><br>
            <span style="color:#666;font-size:12px;">{e.get('orgao', '')} · {e.get('area', '')}</span>
          </td>
          <td style="padding:8px;border-bottom:1px solid #eee;text-align:right;">
            <span style="color:#1f4e79;font-weight:bold;">R$ {e.get('valor_estimado', 0):,.0f}</span><br>
            <span style="color:#999;font-size:11px;">Prazo: {e.get('dt_fim', '-')}</span>
          </td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;max-width:640px;margin:auto;color:#333;">
  <div style="background:#0b1f3b;color:#fff;padding:20px;">
    <h2 style="margin:0;">PACTA - Alerta de Editais</h2>
    <p style="margin:5px 0 0;opacity:.85;">Novos editais relevantes encontrados</p>
  </div>
  <div style="padding:20px;">
    <p>Encontramos <strong>{n} edital{'is' if n>1 else ''}</strong> que podem interessar:</p>
    <table style="width:100%;border-collapse:collapse;">{items_html}</table>
    <p style="margin-top:20px;">
      <a href="https://pacta-production.up.railway.app/dashboard/editais"
         style="display:inline-block;background:#1f4e79;color:#fff;padding:10px 18px;border-radius:4px;text-decoration:none;">
         Ver todos os editais
      </a>
    </p>
  </div>
  <div style="background:#f0f4f8;padding:15px;font-size:11px;color:#666;text-align:center;">
    PACTA - Plataforma de Acompanhamento &middot; Freitas &amp; Associados
  </div>
</body></html>"""
    return subject, html


def render_vigencia_alert(convenios: list[dict]) -> tuple[str, str]:
    """Retorna (subject, html) para convenios vencendo."""
    n = len(convenios)
    subject = f"[PACTA] {n} convenio{'s' if n>1 else ''} com vigencia critica"
    items_html = ""
    for c in convenios[:30]:
        cor = "#dc2626" if c.get('dias_restantes', 0) < 30 else "#d97706"
        items_html += f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #eee;">
            <strong>{c.get('nr_convenio', '-')}</strong> · {c.get('orgao', '')}<br>
            <span style="color:#666;font-size:12px;">{c.get('objeto', '')[:80]}</span>
          </td>
          <td style="padding:8px;border-bottom:1px solid #eee;text-align:right;">
            <span style="color:{cor};font-weight:bold;">{c.get('dias_restantes', '-')}d restantes</span><br>
            <span style="color:#999;font-size:11px;">Vence: {c.get('dt_fim', '-')}</span>
          </td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;max-width:640px;margin:auto;color:#333;">
  <div style="background:#dc2626;color:#fff;padding:20px;">
    <h2 style="margin:0;">PACTA - Alerta de Vigencia</h2>
    <p style="margin:5px 0 0;">Convenios com prazo critico</p>
  </div>
  <div style="padding:20px;">
    <table style="width:100%;border-collapse:collapse;">{items_html}</table>
    <p style="margin-top:20px;">
      <a href="https://pacta-production.up.railway.app/dashboard"
         style="display:inline-block;background:#1f4e79;color:#fff;padding:10px 18px;border-radius:4px;text-decoration:none;">
         Acessar Dashboard
      </a>
    </p>
  </div>
</body></html>"""
    return subject, html
