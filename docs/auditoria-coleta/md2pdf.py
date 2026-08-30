"""md2pdf.py — converte docs/AUDITORIA_COLETA.md em PDF.
Caminho 1: markdown -> HTML (python-markdown) -> Chrome/Edge headless --print-to-pdf.
(WeasyPrint nao importa neste Windows: faltam as libs GTK/pango.)
Uso: python md2pdf.py <entrada.md> <saida.pdf>
"""
import os, subprocess, sys, shutil
import markdown

src, dst = sys.argv[1], sys.argv[2]
html_path = os.path.splitext(dst)[0] + ".html"
texto = open(src, encoding="utf-8").read()
corpo = markdown.markdown(texto, extensions=["tables", "fenced_code", "toc", "sane_lists"])
css = """
@page { size: A4; margin: 16mm 14mm 16mm 14mm; }
body { font-family: "Segoe UI", Arial, sans-serif; font-size: 10.5pt; line-height: 1.38; color: #111; }
h1 { font-size: 20pt; border-bottom: 2px solid #1f3b73; padding-bottom: 4px; margin-top: 18pt; page-break-before: always; }
h1:first-of-type { page-break-before: auto; }
h2 { font-size: 15pt; color: #1f3b73; margin-top: 16pt; }
h3 { font-size: 12pt; margin-top: 12pt; }
table { border-collapse: collapse; width: 100%; font-size: 8.6pt; margin: 6pt 0; page-break-inside: auto; }
th, td { border: 1px solid #bbb; padding: 3px 5px; vertical-align: top; }
th { background: #eef2f8; }
tr { page-break-inside: avoid; }
code { font-family: Consolas, "Courier New", monospace; font-size: 8.6pt; background: #f4f4f4; padding: 0 2px; }
pre { background: #f4f4f4; border: 1px solid #ddd; padding: 6px; font-size: 8.2pt; white-space: pre-wrap; word-break: break-word; }
blockquote { border-left: 4px solid #1f3b73; margin: 8pt 0; padding: 4pt 10pt; background: #f7f9fc; }
a { color: #1f3b73; text-decoration: none; }
"""
html = f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><title>Auditoria da coleta — PACTHA</title><style>{css}</style></head><body>{corpo}</body></html>"
open(html_path, "w", encoding="utf-8").write(html)

cands = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
         r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]
exe = next((c for c in cands if os.path.exists(c)), None) or shutil.which("chrome") or shutil.which("msedge")
if not exe:
    sys.exit("nenhum Chrome/Edge encontrado")
url = "file:///" + html_path.replace("\\", "/")
cmd = [exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--no-first-run", "--no-default-browser-check",
       f"--print-to-pdf={dst}", "--print-to-pdf-no-header", url]
r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
ok = os.path.exists(dst) and os.path.getsize(dst) > 10000
print("exe:", exe)
print("pdf:", dst, os.path.getsize(dst) if os.path.exists(dst) else "AUSENTE", "ok" if ok else "FALHOU")
if not ok:
    print(r.stdout[-2000:], r.stderr[-2000:])
