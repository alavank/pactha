"""
SNC — o Sistema Nacional de Cultura: a adesão do município e as LEIS que ele registrou
(sistema, órgão gestor, conselho, FUNDO e plano de cultura). Serve a uma pergunta só,
que tem data marcada:

    Lei 14.399/2022 (PNAB), art. 6º, § 8º (incluído pela Lei 15.132/2025):
    "A partir de 2027, somente receberão os recursos previstos nesta Lei os entes
    federativos que dispuserem de fundo de cultura, conforme regulamento."

Até 2026 o repasse vai para a estrutura que o ente indicar (§ 7º). O município sem
fundo de cultura PERDE o PNAB em 2027 — dinheiro certo, todo ano, para todo município.

Fonte: a página pública de adesão, por IBGE de 7 dígitos, sem login:
    https://snc.cultura.gov.br/adesao/detalhar/<IBGE7>

AS ARMADILHAS, medidas em 26/09/2026:

1. **É HTML (UTF-8, declarado no Content-Type).** Cada componente é um `<div class="documentDescription">`
   com `fa-check` (e o link do documento) ou `fa-times` (não registrado). A situação
   do acordo e a data de publicação vêm em `texto_situacao`.

2. ⚠️ **A PÁGINA TRAZ DADO PESSOAL** — nome, e-mail e telefone do prefeito, do gestor
   de cultura e de cada conselheiro. NADA disso é lido nem gravado: o coletor recorta
   só o bloco da situação e o dos componentes.

3. **"Lei do Fundo de Cultura" ✔ NÃO PROVA QUE O FUNDO ESTÁ APTO** ("conforme
   regulamento"): prova que o município registrou no SNC uma lei que cria o fundo (em
   Nova Palma é a própria lei do sistema). E o contrário também vale: o município pode
   ter a lei e não ter registrado. Por isso a tela cruza com o DINHEIRO: se o PNAB
   (ação 00UV na planilha da CGU, `cgu_transferencias`) já cai num CNPJ de FUNDO de
   cultura, o fundo existe. Ver `services/cultura_pnab.py`.

4. **IBGE fora do cadastro dá 404** (medido com 9999999) — não 200 vazio. 404 é
   `partial` com o município nomeado; o que já estava gravado fica.

5. **Os nomes dos componentes variam** entre municípios ("Lei de criação do Conselho
   de Política Cultural" × "Lei de Regulamentação da Criação do Conselho de Políticas
   Culturais", e às vezes "Ata de reunião do Conselho"): são guardados como a página
   escreve, e o FUNDO é achado por conter "FUNDO".

Rodável por Scheduled Task ou à mão:
    python -u ingestion/snc_cultura.py            # coleta de verdade
    python -u ingestion/snc_cultura.py --dry      # lê e mostra, não grava
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import unicodedata
from datetime import date

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("snc_cultura")

FONTE = "snc_cultura"
URL = "https://snc.cultura.gov.br/adesao/detalhar/{ibge}"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131 Safari/537.36"}
PAUSA_S = 1.0
MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
         "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}

_RE_SIT = re.compile(r'class="texto_situacao">\s*([^<]+?)\s*<', re.S)
_RE_COMP = re.compile(
    r'class="documentDescription"[^>]*>\s*<i class="fa (fa-check|fa-times)"></i>\s*'
    r'(?:<a href="([^"]*)"[^>]*>\s*)?([^<]+?)\s*(?:</a>\s*)?</div>', re.S)


class PaginaRecusada(ValueError):
    """A página não tem o bloco esperado — o layout mudou."""


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")


def data_extenso(s: str | None) -> date | None:
    """"16 de Junho de 2017" -> date; "Sem data de publicação" -> None."""
    m = re.match(r"\s*(\d{1,2}) de (\w+) de (\d{4})", _sem_acento(s or "").lower())
    if not m or m.group(2) not in MESES:
        return None
    try:
        return date(int(m.group(3)), MESES[m.group(2)], int(m.group(1)))
    except ValueError:
        return None


def ler_pagina(html: str) -> dict:
    """{situacao, data_publicacao, componentes: [{nome, registrado, documento}]}.
    Só os dois blocos da armadilha 2 — nenhum dado pessoal sai daqui."""
    a = html.find("painel_situacao")
    b = html.find("voltar-topo")
    if a < 0 or b < a:
        raise PaginaRecusada("bloco 'painel_situacao' ausente — o layout do SNC mudou?")
    trecho = html[a:b]
    textos = _RE_SIT.findall(trecho)
    if not textos:
        raise PaginaRecusada("situação do acordo ausente")
    comps = []
    for icone, href, nome in _RE_COMP.findall(trecho):
        doc = None
        if icone == "fa-check" and href and href != "None":
            doc = href if href.startswith("http") else f"https://snc.cultura.gov.br{href}"
        comps.append({"nome": re.sub(r"\s+", " ", nome).strip(),
                      "registrado": icone == "fa-check", "documento": doc})
    if not comps:
        raise PaginaRecusada("nenhum componente (lei do sistema, fundo...) na página")
    return {
        "situacao": textos[0],
        "data_publicacao": data_extenso(textos[1]) if len(textos) > 1 else None,
        "componentes": comps,
    }


def fundo_registrado(componentes: list[dict]) -> bool:
    return any("FUNDO" in _sem_acento(c["nome"]).upper() and c["registrado"] for c in componentes)


def _log_ingest(cur, conn, status: str, n: int, nota: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES (%s, %s, %s, %s, NOW())",
            (FONTE, status, n, nota))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.warning("ingestion_log falhou: %s", str(e)[:120])


def ingest(dry: bool = False) -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect

    notas, gravadas = [], 0
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT id, nome, coalesce(ibge_code::text, '') FROM municipios "
                        "WHERE active ORDER BY id")
            alvos = [(m, n, re.sub(r"\D", "", i)) for m, n, i in cur.fetchall()]
            with httpx.Client(follow_redirects=True, headers=UA, timeout=40) as client:
                for k, (mid, nome, ibge) in enumerate(alvos):
                    if len(ibge) != 7:
                        notas.append(f"{nome}: sem IBGE de 7 dígitos")
                        continue
                    if k:
                        time.sleep(PAUSA_S)
                    try:
                        r = client.get(URL.format(ibge=ibge))
                        if r.status_code == 404:
                            notas.append(f"{nome}: IBGE {ibge} não existe no SNC (404)")
                            continue
                        r.raise_for_status()
                        d = ler_pagina(r.text)
                    except (httpx.HTTPError, PaginaRecusada) as e:
                        notas.append(f"{nome}: {type(e).__name__}: {str(e)[:80]}")
                        continue
                    log.info("%s: %s; fundo %s", nome, d["situacao"],
                             "registrado" if fundo_registrado(d["componentes"]) else "NÃO registrado")
                    if dry:
                        continue
                    cur.execute("""
                        INSERT INTO snc_cultura (municipio_id, situacao, data_publicacao,
                                                 componentes, fundo_registrado, lido_em)
                        VALUES (%s, %s, %s, %s::jsonb, %s, NOW())
                        ON CONFLICT (municipio_id) DO UPDATE SET situacao = EXCLUDED.situacao,
                            data_publicacao = EXCLUDED.data_publicacao,
                            componentes = EXCLUDED.componentes,
                            fundo_registrado = EXCLUDED.fundo_registrado, lido_em = NOW()
                    """, (mid, d["situacao"], d["data_publicacao"],
                          json.dumps(d["componentes"], ensure_ascii=False),
                          fundo_registrado(d["componentes"])))
                    conn.commit()
                    gravadas += 1
            if dry:
                return 0
            status = "partial" if notas else "success"
            _log_ingest(cur, conn, status, gravadas, "; ".join(notas)[:480] or None)
            return gravadas
        except Exception as e:
            conn.rollback()
            log.error("SNC falhou: %s: %s", type(e).__name__, str(e)[:200])
            if not dry:
                _log_ingest(cur, conn, "error", gravadas, f"{type(e).__name__}: {str(e)[:380]}")
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ingest(dry="--dry" in sys.argv)
