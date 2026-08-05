"""Contas julgadas irregulares — TCM-GO (Tribunal de Contas dos MUNICÍPIOS).

⚠️ EM GOIÁS QUEM JULGA CONTA MUNICIPAL É O TCM-GO, e não o TCE-GO. São dois
tribunais distintos: o TCE cuida do Estado. Rotular errado aqui repetiria o
defeito que `lib/estadual.ts` documenta ter cometido ("CAGEC — Minas Gerais"
sobre cidade de Goiás).

Fonte: `https://ws.tcm.go.gov.br/api/rest/dados/contas-irregulares` — pública,
sem login, sem captcha, sem chave. Um GET, CSV inteiro.

⚠️ ISTO É INDÍCIO, NÃO DOCUMENTO. A lista diz quem TEM conta julgada irregular;
não diz que quem não aparece está regular. Anápolis e Itaberaí têm ZERO linhas
— isso significa "sem conta irregular listada", não "em dia". Ver a migration,
que carrega a mesma advertência, e a tela, que nunca fica verde por isto.

⚠️ TRÊS ARMADILHAS MEDIDAS NA FONTE (05/08/2026):

1. **A negociação de conteúdo é invertida.** Com `Accept: application/json` a
   API responde **406 com corpo vazio**. Tem de ser `Accept: */*`.
2. **É UTF-8** — o levantamento anterior dizia latin-1, e está errado: os bytes
   do cabeçalho são `Munic\xc3\xadpio`. Decodificar como latin-1 vira
   "MunicÃ­pio" e nenhum município casa.
3. **O nome do município vem SEM os conectivos**: a base grava "APARECIDA
   GOIANIA", não "Aparecida de Goiânia" — e um casamento por prefixo colaria
   **"APARECIDA RIO DOCE"** (outro município, que existe na base) em Aparecida
   de Goiânia. Por isso a chave normaliza removendo DE/DA/DO/DAS/DOS dos DOIS
   lados e compara IGUALDADE, nunca prefixo.
"""
import csv
import io
import logging
import os
import re
import sys
import unicodedata
from datetime import date, datetime

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

log = logging.getLogger("tcm-go")

URL = "https://ws.tcm.go.gov.br/api/rest/dados/contas-irregulares"
FONTE = "TCM-GO"
UF = "GO"

COLUNAS_MINIMAS = {"Município", "Nome", "Processo/Fase", "TipoLista"}
# Conectivos que a origem do TCM omite no nome do município.
_CONECTIVOS = {"DE", "DA", "DO", "DAS", "DOS", "D"}


def _decodificar(raw: bytes) -> str:
    """utf-8 ANTES de latin-1: latin-1 nunca falha e esconderia o UTF-8 atrás
    de mojibake — foi o que o levantamento anterior concluiu errado."""
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _sem_acento(s) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s or ""))
                if not unicodedata.combining(c))
    return " ".join(s.upper().split())


def chave_municipio(nome: str) -> str:
    """Nome comparável dos DOIS lados: sem acento, sem o sufixo de entidade e
    sem conectivos. "Aparecida de Goiânia" e "APARECIDA GOIANIA - FMS" caem no
    mesmo "APARECIDA GOIANIA"; "APARECIDA RIO DOCE" continua distinto."""
    base = _sem_acento(nome).split(" - ")[0]
    return " ".join(p for p in base.split() if p not in _CONECTIVOS)


def entidade_de(nome: str) -> str | None:
    """O que vem depois do " - ": FMS, COMURG, FUNDEB... None = a prefeitura."""
    partes = _sem_acento(nome).split(" - ", 1)
    return partes[1].strip()[:200] if len(partes) > 1 and partes[1].strip() else None


def _data(s) -> date | None:
    t = (s or "").strip()
    for f in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t, f).date()
        except ValueError:
            pass
    return None


def _chave(r: dict) -> str:
    """A origem não tem id.

    ⚠️ O NOME ENTRA NA CHAVE, e não é redundância com o CPF. O CPF vem
    mascarado ao ponto de virar "00***.***-***" para pessoas diferentes — medido
    no arquivo: 3 pares de RESPONSÁVEIS DISTINTOS dividiam processo, acórdão,
    assunto e a mesma máscara de CPF. Sem o nome, um deles sumia em silêncio
    (134 linhas viravam 131)."""
    return "|".join([
        _sem_acento(r.get("Município")),
        (r.get("Processo/Fase") or "").strip(),
        (r.get("CPF") or "").strip(),
        _sem_acento(r.get("Nome")),
        (r.get("Acórdão/Resolução") or "").strip(),
        (r.get("Assunto") or "").strip(),
    ])


def _mapa_municipios(cur) -> dict:
    """chave normalizada -> municipio_id, para os municípios de GO do tenant."""
    cur.execute("SELECT id, nome FROM municipios "
                "WHERE active AND upper(coalesce(uf, '')) = %s", (UF,))
    mapa = {}
    for mid, nome in cur.fetchall():
        mapa[chave_municipio(nome)] = mid
    return mapa


def _log_ingest(cur, status: str, inseridos: int, erro: str | None = None):
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES (%s,%s,%s,%s,NOW())",
            ("tcm_go", status, inseridos, erro))
    except Exception:
        pass


def ingest() -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            mapa = _mapa_municipios(cur)
            if not mapa:
                log.info("nenhum municipio de GO neste tenant — TCM-GO nao se aplica")
                _log_ingest(cur, "success", 0)
                conn.commit()
                return 0
            log.info("TCM-GO: %d municipio(s) de GO no mapa", len(mapa))

            with httpx.Client(timeout=120, follow_redirects=True) as cli:
                # ⚠️ Accept: */* — com application/json a API devolve 406 vazio.
                r = cli.get(URL, headers={"Accept": "*/*",
                                          "User-Agent": "Mozilla/5.0"})
                r.raise_for_status()
                texto = _decodificar(r.content)

            leitor = csv.DictReader(io.StringIO(texto))
            faltando = COLUNAS_MINIMAS - set(leitor.fieldnames or [])
            if faltando:
                raise RuntimeError(
                    f"formato inesperado: faltam {sorted(faltando)} | "
                    f"colunas: {sorted(leitor.fieldnames or [])[:8]}")
            linhas = list(leitor)

            import json as _json
            gravados = 0
            for row in linhas:
                mid = mapa.get(chave_municipio(row.get("Município")))
                if not mid:
                    continue
                cur.execute("""
                    INSERT INTO contas_irregulares (
                        municipio_id, fonte, chave, entidade, responsavel, cpf,
                        assunto, competencia, processo, dt_transito,
                        dt_julgamento, acordao, url, tipo_lista, raw_data
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT (fonte, chave) DO UPDATE SET
                        tipo_lista = EXCLUDED.tipo_lista,
                        dt_transito = EXCLUDED.dt_transito,
                        url = EXCLUDED.url,
                        raw_data = EXCLUDED.raw_data,
                        updated_at = NOW()
                """, (
                    mid, FONTE, _chave(row),
                    entidade_de(row.get("Município")),
                    (row.get("Nome") or "").strip()[:200],
                    (row.get("CPF") or "").strip()[:30],
                    (row.get("Assunto") or "").strip()[:200],
                    (row.get("Mês/Ano") or "").strip()[:20],
                    (row.get("Processo/Fase") or "").strip()[:80],
                    _data(row.get("Dt. Trânsito Julgado")),
                    _data(row.get("Data Julgamento")),
                    (row.get("Acórdão/Resolução") or "").strip()[:160],
                    (row.get("Url") or "").strip() or None,
                    (row.get("TipoLista") or "").strip()[:160],
                    _json.dumps({k: (v or "") for k, v in row.items()},
                                ensure_ascii=False),
                ))
                gravados += 1

            conn.commit()
            log.info("TCM-GO: %d linha(s) na fonte, %d dos nossos municipios",
                     len(linhas), gravados)
            _log_ingest(cur, "success", gravados)
            conn.commit()
            return gravados
        except Exception as e:
            conn.rollback()
            log.error("TCM-GO falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, "error", 0, str(e)[:400])
            conn.commit()
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ingest()
