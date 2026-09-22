"""
Regularidade estadual do PARANÁ — as duas certidões públicas que o Estado exige
para a transferência voluntária, gravadas em `cagec_situacao` (fonte 'CERTIDOES-PR').

O Paraná não tem um "cadastro de convenentes" como o CAGEC mineiro ou o CHE
gaúcho. O que a SEAP-PR lista em "Certidões exigidas para Convênios" são
certidões, e duas delas têm consulta pública sem login e sem captcha:

1. **Certidão Negativa para Transferências Voluntárias** — SEFA-PR / Diretoria do
   Tesouro (LRF art. 25 §1º IV "a" e art. 51). Diz que o município homologou as
   contas no SICONFI e não tem débito com o Estado. Tem NÚMERO e VALIDADE.
       www4.pr.gov.br/Gestao/responsabilidade/INTER_EmissaoCertidao2.jsp?tipo=1&codMun=<cod>

2. **Pendências para a Certidão Liberatória** — TCE-PR (Res. 28/2011, o SIT). Diz
   se a entidade tem prestação de contas pendente no Tribunal. Sem validade: é a
   situação NA HORA da consulta.
       servicos.tce.pr.gov.br/TCEPR/Tribunal/CertidaoLiberatoria/
           srv_ConsultaPendenciasCertidaoLiberatoria.aspx?nrCNPJ=<cnpj14>

A CND de tributos estaduais e o CADIN-PR também são exigidos, mas estão atrás de
reCAPTCHA Enterprise — ficam como consulta manual, e a tela diz isso.

AS ARMADILHAS, medidas em 22/09/2026:

1. ⚠️ **A ROTA DA SEFA EMITE.** `INTER_EmissaoCertidao2.jsp` devolve a certidão
   VIGENTE quando há uma (Juranda: nº 00069059, emitida em 21/08, válida até
   20/10) e EMITE uma nova quando não há. Consultar o `tipo=4` gerou a certidão
   nº 00069295 na hora — e o `tipo=4` NÃO é "saúde/educação/assistência", como
   uma pesquisa anterior supôs: é a de GARANTIAS (art. 40 §10). Por isso este
   coletor pede SÓ o `tipo=1`, uma vez por dia: emite no máximo quando a anterior
   vence, que é o que a prefeitura faria à mão.

2. ⚠️ **O `codMun` DA SEFA NÃO É O IBGE** (Juranda = 844). Sai do `<select>` da
   página de emissão (`INTER_EmissaoCertidao.jsp`), que imprime o CNPJ da
   prefeitura em cada opção — o casamento é por CNPJ, e exige um só código para
   ele, senão o município é pulado com aviso (nunca adivinhado).

3. ⚠️ **HTML EM windows-1252** na SEFA e UTF-8 no TCE.

4. ⚠️ **FORMATO DESCONHECIDO NÃO É IRREGULAR.** Só vira `pendente` o texto que
   AFIRMA a pendência ("possui pendências" sem o "não"; SEFA sem a frase de
   certidão emitida mas com negativa explícita). Página que não casa com nenhum
   dos dois formatos conhecidos é falha de LEITURA: a rodada fica `partial` e a
   linha do banco não é tocada — não se pinta de vermelho um município que pode
   estar em dia.

5. ⚠️ **A validade vai em dd/mm/aaaa** em `itens[].validade` — a regra do CHE:
   `venceu()` da tela e `prazos_dos_itens` só entendem esse formato.

Rodável por Scheduled Task no worker de tenant com município do PR, ou à mão:
    python -u ingestion/regularidade_pr.py            # coleta de verdade
    python -u ingestion/regularidade_pr.py --dry      # consulta e mostra
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import sys
import unicodedata
from datetime import date, datetime

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("regularidade_pr")

UF = "PR"
FONTE = "CERTIDOES-PR"
SOURCE = "regularidade_pr"
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0 consulta publica de certidoes)"}
TIMEOUT = 60

SEFA = "https://www4.pr.gov.br/Gestao/responsabilidade"
URL_SEFA_LISTA = f"{SEFA}/INTER_EmissaoCertidao.jsp"
URL_SEFA_CERTIDAO = f"{SEFA}/INTER_EmissaoCertidao2.jsp"
URL_TCE = ("https://servicos.tce.pr.gov.br/TCEPR/Tribunal/CertidaoLiberatoria/"
           "srv_ConsultaPendenciasCertidaoLiberatoria.aspx")

MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5,
         "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
         "novembro": 11, "dezembro": 12}


class FormatoDesconhecido(Exception):
    """A página não casou com nenhum formato conhecido — armadilha 4."""


def _norm(s: str | None) -> str:
    t = unicodedata.normalize("NFD", (s or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def texto_da_pagina(bruto: str) -> str:
    """HTML -> texto corrido, sem script/style, entidades resolvidas."""
    t = re.sub(r"<(script|style)\b.*?</\1>", " ", bruto, flags=re.S | re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t).strip()


def _br(d: date | None) -> str | None:
    return d.strftime("%d/%m/%Y") if d else None


# ---------------------------------------------------------------------------
# SEFA — Certidão Negativa para Transferências Voluntárias
# ---------------------------------------------------------------------------
def codigos_sefa(bruto: str) -> dict[str, list[str]]:
    """{cnpj14: [codMun, ...]} a partir do <select> da página de emissão.

    Cada opção é `<option value = "844">Juranda   - CNPJ nº: 78.196.755/0001-09`
    (com espaços em volta do `=`). A chave é o CNPJ, nunca o nome — a regra do
    projeto, e o nome no select tem acento e espaço de preenchimento."""
    saida: dict[str, list[str]] = {}
    for cod, rotulo in re.findall(
            r"<option[^>]*value\s*=\s*[\"']?(\d+)[\"']?[^>]*>([^<]+)", bruto, re.I):
        m = re.search(r"CNPJ[^0-9]*([\d./-]{14,18})", html.unescape(rotulo), re.I)
        if not m:
            continue
        cnpj = re.sub(r"\D", "", m.group(1))
        if len(cnpj) == 14:
            saida.setdefault(cnpj, []).append(cod)
    return saida


def le_certidao_sefa(texto: str, hoje: date) -> dict:
    """Item da certidão da SEFA a partir do texto da página (armadilha 4)."""
    numero = re.search(r"Transfer[eê]ncias Volunt[aá]rias\s*N[ºo°]\s*(\d+)", texto, re.I)
    validade = re.search(r"validade at[eé]\s*(\d{1,2}) de ([a-zç]+) de (\d{4})", texto, re.I)
    emitida = re.search(r"Emitida Eletronicamente via Internet\s*(\d{2}/\d{2}/\d{4})", texto, re.I)
    if numero and validade:
        mes = MESES.get(_norm(validade.group(2)))
        if not mes:
            raise FormatoDesconhecido(f"mês ilegível: {validade.group(2)!r}")
        ate = date(int(validade.group(3)), mes, int(validade.group(1)))
        vigente = ate >= hoje
        return {
            "codigo": "PR-SEFA-TV", "grupo": "Certidões do Estado",
            "label": "Certidão Negativa para Transferências Voluntárias (SEFA-PR)",
            "valor": f"Nº {numero.group(1)}", "tipo": "regular" if vigente else "pendente",
            "status": "Vigente" if vigente else "Vencida",
            "validade": _br(ate),
            "detalhe": {"numero": numero.group(1),
                        "emitida_em": emitida.group(1) if emitida else None},
        }
    # Negativa explícita: a SEFA não emite para quem tem pendência e diz por quê.
    t = _norm(texto)
    if "nao foi possivel" in t or "nao e possivel" in t or "impossibilitad" in t \
            or "pendenc" in t or "nao atende" in t:
        motivo = texto[:400]
        return {
            "codigo": "PR-SEFA-TV", "grupo": "Certidões do Estado",
            "label": "Certidão Negativa para Transferências Voluntárias (SEFA-PR)",
            "valor": "Não emitida", "tipo": "pendente", "status": "Não emitida",
            "validade": None, "detalhe": {"motivo": motivo},
        }
    raise FormatoDesconhecido("página da SEFA sem certidão e sem negativa reconhecível")


# ---------------------------------------------------------------------------
# TCE-PR — pendências para a Certidão Liberatória
# ---------------------------------------------------------------------------
def le_liberatoria(texto: str) -> dict:
    """Item da Certidão Liberatória a partir do texto da página (armadilha 4)."""
    # ⚠️ Só o que vem DEPOIS de "Resultado": o título da página já diz
    # "Verificação de pendências", e ler a página inteira acusaria todo mundo.
    m = re.search(r"\bResultado\s+(.*)", texto, re.I)
    if not m:
        raise FormatoDesconhecido("página do TCE-PR sem o bloco 'Resultado'")
    resultado = m.group(1)[:600].strip()
    t = _norm(resultado)
    base = {"codigo": "PR-TCE-LIB", "grupo": "Certidões do Estado",
            "label": "Certidão Liberatória — pendências no TCE-PR", "validade": None}
    if "nao possui pendencias" in t:
        return {**base, "valor": "Sem pendências", "tipo": "regular",
                "status": "Sem pendências", "detalhe": {"resultado": resultado}}
    if "possui pendencias" in t or "possui pendencia" in t:
        return {**base, "valor": "Com pendências", "tipo": "pendente",
                "status": "Com pendências", "detalhe": {"resultado": resultado}}
    raise FormatoDesconhecido("página do TCE-PR sem resultado reconhecível")


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------
_SQL = """
INSERT INTO cagec_situacao (municipio_id, nome, uf, cnpj, tipo, principal,
                            situacao, regular, validade, itens, pendencias,
                            pendencias_codigos, data_pesquisa, fonte, raw_data,
                            crc_em, crc_erro, atualizado_em)
VALUES (%(mid)s, %(nome)s, 'PR', %(cnpj)s, 'Município', TRUE,
        %(situacao)s, %(regular)s, %(validade)s, %(itens)s::jsonb, %(pend)s,
        %(pend_cods)s, %(hoje)s, %(fonte)s, %(raw)s::jsonb,
        %(hoje)s, NULL, NOW())
ON CONFLICT (municipio_id, cnpj) DO UPDATE SET
    nome = EXCLUDED.nome, uf = EXCLUDED.uf, tipo = EXCLUDED.tipo,
    principal = EXCLUDED.principal,
    situacao = EXCLUDED.situacao, regular = EXCLUDED.regular,
    validade = EXCLUDED.validade, itens = EXCLUDED.itens,
    pendencias = EXCLUDED.pendencias,
    pendencias_codigos = EXCLUDED.pendencias_codigos,
    data_pesquisa = EXCLUDED.data_pesquisa,
    fonte = EXCLUDED.fonte, raw_data = EXCLUDED.raw_data,
    crc_em = EXCLUDED.crc_em, crc_erro = NULL,
    atualizado_em = NOW()
"""


def linha(alvo: dict, itens: list[dict], hoje: date, raw: dict) -> dict:
    pendentes = [i["codigo"] for i in itens if i["tipo"] == "pendente"]
    validades = [datetime.strptime(i["validade"], "%d/%m/%Y").date()
                 for i in itens if i["tipo"] == "regular" and i.get("validade")]
    return {
        "mid": alvo["id"], "nome": alvo["nome_entidade"],
        "cnpj": _mascara(alvo["cnpj14"]),
        # O vocabulário do CHE, e não o do CAGEC ("Regular/Irregular"): são
        # certidões, não um cadastro, e compará-las ao CRC mineiro induziria erro.
        "situacao": "Em dia" if not pendentes else "Com pendência(s)",
        "regular": not pendentes,
        # A próxima validade a segurar — a da certidão da SEFA. A Liberatória não
        # tem validade: vale na data da consulta.
        "validade": min(validades) if validades else None,
        "itens": json.dumps(itens, ensure_ascii=False),
        "pend": len(pendentes), "pend_cods": pendentes,
        "hoje": hoje, "fonte": FONTE,
        "raw": json.dumps(raw, ensure_ascii=False),
    }


def _mascara(c: str) -> str:
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"


def _alvos(cur) -> list[dict]:
    cur.execute("""
        SELECT id, nome, regexp_replace(coalesce(cnpj, ''), '\\D', '', 'g')
          FROM municipios
         WHERE active AND upper(coalesce(uf, '')) = %s ORDER BY nome
    """, (UF,))
    return [{"id": r[0], "nome": r[1], "cnpj14": r[2]} for r in cur.fetchall()]


def _log_ingest(cur, conn, status: str, n: int, nota: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES (%s, %s, %s, %s, NOW())",
            (SOURCE, status, n, nota))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.warning("ingestion_log falhou: %s", str(e)[:120])


def consultar(client: httpx.Client, alvo: dict, cod_sefa: str | None,
              hoje: date) -> tuple[list[dict], dict, list[str]]:
    """(itens, raw, falhas) de UM município. Falha de uma certidão não derruba a
    outra: sai o item que foi lido, e a falha vai para a nota da rodada."""
    itens, raw, falhas = [], {}, []
    if cod_sefa:
        try:
            r = client.get(URL_SEFA_CERTIDAO, params={"tipo": 1, "codMun": cod_sefa},
                           headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            texto = texto_da_pagina(r.content.decode("cp1252", "replace"))
            item = le_certidao_sefa(texto, hoje)
            itens.append(item)
            raw["sefa"] = {"codMun": cod_sefa, "texto": texto[:1500]}
            # A página imprime o nome oficial ("Prefeitura Municipal de Juranda").
            m = re.search(r"Dados do Munic[ií]pio:\s*(.+?)\s+Endere", texto)
            if m:
                alvo["nome_entidade"] = m.group(1).strip()
        except Exception as e:
            falhas.append(f"{alvo['nome']} SEFA: {type(e).__name__}: {str(e)[:80]}")
    else:
        falhas.append(f"{alvo['nome']} SEFA: codMun não encontrado no select")
    if len(alvo["cnpj14"]) == 14:
        try:
            r = client.get(URL_TCE, params={"nrCNPJ": alvo["cnpj14"]},
                           headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            texto = texto_da_pagina(r.text)
            itens.append(le_liberatoria(texto))
            raw["tce"] = {"texto": texto[:1500]}
        except Exception as e:
            falhas.append(f"{alvo['nome']} TCE: {type(e).__name__}: {str(e)[:80]}")
    else:
        falhas.append(f"{alvo['nome']}: sem CNPJ em `municipios` — Liberatória não consultada")
    return itens, raw, falhas


def ingest(dry: bool = False) -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect

    hoje = date.today()
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            alvos = _alvos(cur)
            if not alvos:
                log.info("nenhum município do PR — regularidade PR não se aplica")
                if not dry:
                    _log_ingest(cur, conn, "success", 0)
                return 0
            gravados, falhas = 0, []
            with httpx.Client(follow_redirects=True) as client:
                r = client.get(URL_SEFA_LISTA, headers=UA, timeout=TIMEOUT)
                r.raise_for_status()
                codigos = codigos_sefa(r.content.decode("cp1252", "replace"))
                for alvo in alvos:
                    alvo["nome_entidade"] = f"Prefeitura Municipal de {alvo['nome']}"
                    candidatos = codigos.get(alvo["cnpj14"], [])
                    # CNPJ repetido no select não se adivinha (armadilha 2).
                    cod = candidatos[0] if len(candidatos) == 1 else None
                    itens, raw, f = consultar(client, alvo, cod, hoje)
                    falhas += f
                    for i in itens:
                        log.info("  %s: %s — %s (%s)", alvo["nome"], i["label"],
                                 i["status"], i.get("validade") or "sem validade")
                    if dry or not itens or len(alvo["cnpj14"]) != 14:
                        # Sem CNPJ não há chave para a linha; sem item, nada a
                        # afirmar — a linha antiga fica como está (armadilha 4).
                        continue
                    cur.execute(_SQL, linha(alvo, itens, hoje, raw))
                    conn.commit()
                    gravados += 1
            if dry:
                return 0
            status = "partial" if falhas else "success"
            log.info("=== Regularidade PR: %d município(s), status=%s ===", gravados, status)
            _log_ingest(cur, conn, status, gravados, " | ".join(falhas)[:400] or None)
            return gravados
        except Exception as e:
            conn.rollback()
            log.error("Regularidade PR falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ingest(dry="--dry" in sys.argv)
