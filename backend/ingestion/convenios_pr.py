"""
Convênios do ESTADO DO PARANÁ com o município -> convenios_estadual (fonte SIT-PR).

O Portal da Transparência do Paraná publica, por exercício, os convênios que o
Estado firmou com municípios, consórcios e entidades — é o Sistema Integrado de
Transferências (SIT) do TCE-PR em formato aberto:

    https://www.transparencia.download.pr.gov.br/exportacao/CONVENIOS/CONVENIOS-{ANO}.zip
    (2007 em diante; dois CSV com `;`: TB_CONVENIO_EMPREENDIMENTO e TB_CONVENIO_ENTIDADE)

Juranda/PR (22/09/2026): 20 convênios da prefeitura, com concedente, objeto,
vigência, situação, VALOR TOTAL e VALOR JÁ REPASSADO, e o número SIT.

AS ARMADILHAS, todas medidas contra a fonte em 22/09/2026:

1. ⚠️ **O NOME DO ARQUIVO NÃO APARECE NA PÁGINA.** O portal monta o link por
   JavaScript no clique; o endereço acima só foi descoberto simulando o botão.
   Com o nome certo, o download direto responde 200 sem login. O layout
   anunciado (`LAYOUT-CONVENIOS.csv`) responde 404.

2. ⚠️ **O `ibge` NÃO É O IBGE.** É o código IBGE SEM o prefixo da UF (41) e sem
   zero à esquerda: Juranda 4112959 -> `12959`, Curitiba 4106902 -> `6902`.

3. ⚠️ **O TOMADOR NÃO TEM CNPJ**, só nome. O `ibge` diz ONDE ele está, não QUEM é:
   em Juranda, 6 das 26 linhas de 2026 são da APAE local. Entra só ente
   MUNICIPAL (prefeitura, fundo municipal) cujo nome contém o do município —
   a mesma regra das Voluntárias ("o que não é da prefeitura sai das somas").
   Consórcio intermunicipal fica de fora: é outro CNPJ, sediado em outro IBGE.

4. ⚠️ **TRÊS COLUNAS DE REPASSE E NENHUM DICIONÁRIO.** `total_repasses` é o valor
   do Estado no convênio e `total_repassado` o que já saiu — conferido centavo a
   centavo contra o PAGO que o município declara ao TCE-PR (SECID 1748/2025:
   R$ 1.589.909,65 nos dois; SEIL CV004: R$ 554.429,20 nos dois). O
   `total_repassado_1` veio 0,00 em todas as linhas do Juranda e não é usado.
   Vazio (convênio "Formalizada", ainda sem repasse) continua vazio, não zero.

5. ⚠️ **TODO ARQUIVO É REGERADO TODO DIA** (~08:12 UTC) com a situação ATUAL, e
   um convênio aparece em todo exercício em que esteve vigente (10.241 dos 13.316
   de 2026 também estão no de 2025, com os MESMOS valores). A chave é
   `convenio_empreendimento_cod`, estável entre arquivos; lendo os anos em ordem,
   o mais recente vence.

Rodável por Scheduled Task no worker de tenant com município do PR, ou à mão:
    python -u ingestion/convenios_pr.py            # coleta de verdade
    python -u ingestion/convenios_pr.py --dry      # baixa, casa e mostra
Envs: CONVENIOS_PR_ANO_INICIAL (2007).
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import sys
import unicodedata
import zipfile
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("convenios_pr")

BASE = "https://www.transparencia.download.pr.gov.br/exportacao/CONVENIOS"
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0 dados abertos PR)"}
UF = "PR"
FONTE = "SIT-PR"          # procedência gravada em convenios_estadual.fonte
SOURCE = "convenios_pr"   # nome no ingestion_log
TIMEOUT = 120
ANO_INICIAL = int(os.getenv("CONVENIOS_PR_ANO_INICIAL") or "2007")

# Colunas lidas por NOME. Faltando alguma, o ano é recusado (e a rodada vira
# `partial`) — o risco deste dump é coluna renomeada, não filtro ignorado.
COLUNAS = ("convenio_empreendimento_cod", "convenio_entidade_cod", "concedente",
           "dt_celebracao", "dt_publicacao", "dt_vigencia_fim", "dt_vigencia_inicio",
           "ibge", "info_adicional", "numero", "objeto", "situacao", "tomador",
           "total_contra_partida", "total_repassado", "total_repasses", "atividade")


def url_do_ano(ano: int) -> str:
    return f"{BASE}/CONVENIOS-{ano}.zip"


def codigo_pr(ibge_code) -> int | None:
    """IBGE de 7 dígitos -> o `ibge` do arquivo (armadilha 2)."""
    d = "".join(c for c in str(ibge_code or "") if c.isdigit())
    if len(d) != 7 or not d.startswith("41"):
        return None
    return int(d[2:])


def _norm(s: str | None) -> str:
    t = unicodedata.normalize("NFD", (s or "").upper())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", t).split())


def e_ente_municipal(tomador: str | None, nome_municipio: str) -> bool:
    """O tomador é a prefeitura (ou fundo municipal) DESTE município? (armadilha 3)

    Exige as duas coisas: ser ente municipal pelo nome E citar o município. A
    APAE de Juranda tem o IBGE de Juranda e não é a prefeitura; o "MUNICÍPIO DE
    JURANDA" é."""
    t, m = _norm(tomador), _norm(nome_municipio)
    if not m or not re.search(rf"\b{re.escape(m)}\b", t):
        return False
    return (t.startswith("MUNICIPIO") or t.startswith("PREFEITURA")
            or t.startswith("FUNDO MUNICIPAL"))


def _dec(v):
    s = (v or "").strip()
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _data(v):
    s = (v or "").strip()
    if len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def nr_sit(info: str | None) -> str | None:
    """"Este Empreendimento corresponde ao SIT nr. 78968 ..." -> "78968"."""
    m = re.search(r"SIT\s*nr\.?\s*(\d+)", info or "", re.I)
    return m.group(1) if m else None


def ler_zip(conteudo: bytes, ano: int) -> tuple[list[dict], dict[str, dict]]:
    """(convênios, concedentes por código) de um CONVENIOS-{ANO}.zip."""
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        nomes = z.namelist()
        emp = next((n for n in nomes if "EMPREENDIMENTO" in n.upper()), None)
        ent = next((n for n in nomes if "ENTIDADE" in n.upper()), None)
        if not emp:
            raise ValueError(f"{ano}: sem TB_CONVENIO_EMPREENDIMENTO (tem: {nomes})")
        linhas = list(csv.DictReader(io.StringIO(z.read(emp).decode("utf-8-sig")),
                                     delimiter=";"))
        entidades = {}
        if ent:
            for r in csv.DictReader(io.StringIO(z.read(ent).decode("utf-8-sig")),
                                    delimiter=";"):
                entidades[(r.get("convenio_entidade_cod") or "").strip()] = r
    faltam = [c for c in COLUNAS if linhas and c not in linhas[0]]
    if faltam:
        raise ValueError(f"{ano}: colunas ausentes {faltam}")
    return linhas, entidades


def registro(r: dict, municipio_id: int, entidades: dict) -> dict:
    v_conc = _dec(r.get("total_repasses"))
    v_contra = _dec(r.get("total_contra_partida"))
    total = None
    if v_conc is not None or v_contra is not None:
        total = (v_conc or 0) + (v_contra or 0)
    celebracao = _data(r.get("dt_celebracao"))
    fim = _data(r.get("dt_vigencia_fim"))
    concedente = entidades.get((r.get("convenio_entidade_cod") or "").strip()) or {}
    raw = {k: (v or "").strip() for k, v in r.items() if k}
    # A tela de Convênios lê o número publicado em `raw_data.nr_instrumento`.
    raw["nr_instrumento"] = (r.get("numero") or "").strip() or None
    raw["nr_sit"] = nr_sit(r.get("info_adicional"))
    raw["concedente_cnpj"] = (concedente.get("cnpj") or "").strip() or None
    return {
        "nr": f"PR-{(r.get('convenio_empreendimento_cod') or '').strip()}",
        "mid": municipio_id,
        "convenente": (r.get("tomador") or "").strip()[:500] or None,
        "orgao": (r.get("concedente") or "").strip()[:500] or None,
        "objeto": (r.get("objeto") or "").strip() or None,
        "situacao": (r.get("situacao") or "").strip()[:200] or None,
        "programa": (r.get("atividade") or "").strip()[:100] or None,
        "v_conc": v_conc, "v_contra": v_contra, "v_total": total,
        # ⚠️ Vazio continua vazio (armadilha 4): "Formalizada" ainda não recebeu.
        "v_repassado": _dec(r.get("total_repassado")),
        "dt_pub": _data(r.get("dt_publicacao")),
        "dt_ini": _data(r.get("dt_vigencia_inicio")),
        "dt_fim": fim,
        "dt_ass": celebracao,
        "ano": celebracao.year if celebracao else None,
        "fonte": FONTE,
        "raw": json.dumps(raw, ensure_ascii=False),
    }


_SQL = """
INSERT INTO convenios_estadual (
    nr_sigcon, municipio_id, convenente_nome, orgao_concedente, objeto, situacao,
    tp_instrumento, tipo_programa, valor_concedente, valor_contrapartida,
    valor_total, valor_repassado, dt_publicacao, dt_vigencia_inicial,
    dt_vigencia_final, dt_vigencia_atual, dt_assinatura, ano, fonte, raw_data,
    created_at, updated_at)
VALUES (
    %(nr)s, %(mid)s, %(convenente)s, %(orgao)s, %(objeto)s, %(situacao)s,
    'Convênio', %(programa)s, %(v_conc)s, %(v_contra)s, %(v_total)s,
    %(v_repassado)s, %(dt_pub)s, %(dt_ini)s, %(dt_fim)s, %(dt_fim)s, %(dt_ass)s,
    %(ano)s, %(fonte)s, %(raw)s::jsonb, NOW(), NOW())
ON CONFLICT (nr_sigcon) DO UPDATE SET
    municipio_id = EXCLUDED.municipio_id,
    convenente_nome = EXCLUDED.convenente_nome,
    orgao_concedente = EXCLUDED.orgao_concedente,
    objeto = EXCLUDED.objeto, situacao = EXCLUDED.situacao,
    tipo_programa = EXCLUDED.tipo_programa,
    valor_concedente = EXCLUDED.valor_concedente,
    valor_contrapartida = EXCLUDED.valor_contrapartida,
    valor_total = EXCLUDED.valor_total,
    valor_repassado = EXCLUDED.valor_repassado,
    dt_publicacao = EXCLUDED.dt_publicacao,
    dt_vigencia_inicial = EXCLUDED.dt_vigencia_inicial,
    dt_vigencia_final = EXCLUDED.dt_vigencia_final,
    dt_vigencia_atual = EXCLUDED.dt_vigencia_atual,
    dt_assinatura = EXCLUDED.dt_assinatura,
    ano = EXCLUDED.ano,
    -- ⚠️ `fonte` NÃO entra no UPDATE (a regra do convenios_rs): só o INSERT
    -- define a procedência. O prefixo "PR-" já impede colisão com outra fonte.
    raw_data = EXCLUDED.raw_data,
    updated_at = NOW()
"""


def _alvos(cur) -> list[dict]:
    cur.execute("""
        SELECT id, nome, ibge_code FROM municipios
         WHERE active AND upper(coalesce(uf, '')) = %s ORDER BY nome
    """, (UF,))
    return [{"id": r[0], "nome": r[1], "cod": codigo_pr(r[2])} for r in cur.fetchall()]


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


def coletar(client: httpx.Client, alvos: list[dict]) -> tuple[dict, list[str], dict]:
    """Lê todos os anos e devolve ({nr: registro}, falhas, fora_da_regra).

    `fora_da_regra` conta, por município, as linhas com o IBGE dele que NÃO são
    ente municipal (APAE, associação) — vai para o log, para ninguém achar que
    sumiram."""
    por_cod = {a["cod"]: a for a in alvos if a["cod"]}
    achados: dict[str, dict] = {}
    falhas: list[str] = []
    fora: dict[str, set] = {}
    for ano in range(ANO_INICIAL, date.today().year + 1):
        try:
            r = client.get(url_do_ano(ano), headers=UA, timeout=TIMEOUT)
            if r.status_code == 404:
                log.info("  %s: não publicado", ano)
                continue
            r.raise_for_status()
            linhas, entidades = ler_zip(r.content, ano)
        except Exception as e:
            falhas.append(f"{ano}: {type(e).__name__}: {str(e)[:80]}")
            log.warning("  %s: %s: %s", ano, type(e).__name__, str(e)[:200])
            continue
        n = 0
        for x in linhas:
            try:
                cod = int((x.get("ibge") or "").strip())
            except ValueError:
                continue
            alvo = por_cod.get(cod)
            if not alvo:
                continue
            if not e_ente_municipal(x.get("tomador"), alvo["nome"]):
                fora.setdefault(alvo["nome"], set()).add(x.get("convenio_empreendimento_cod"))
                continue
            reg = registro(x, alvo["id"], entidades)
            # Anos em ordem crescente: o arquivo mais recente vence (armadilha 5).
            achados[reg["nr"]] = reg
            n += 1
        log.info("  %s: %d linha(s) no arquivo, %d do(s) município(s)", ano, len(linhas), n)
    return achados, falhas, {k: len(v) for k, v in fora.items()}


def ingest(dry: bool = False) -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect

    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            alvos = [a for a in _alvos(cur) if a["cod"]]
            if not alvos:
                log.info("nenhum município do PR — convênios do PR não se aplicam")
                if not dry:
                    _log_ingest(cur, conn, "success", 0)
                return 0
            with httpx.Client(follow_redirects=True) as client:
                achados, falhas, fora = coletar(client, alvos)
            for nome, n in fora.items():
                log.info("  %s: %d convênio(s) de entidade não municipal com o IBGE "
                         "do município — fora, pela regra das Voluntárias", nome, n)
            if dry:
                for reg in sorted(achados.values(), key=lambda x: str(x["dt_ass"])):
                    log.info("    %s %s | %s | %s | repassado %s de %s", reg["nr"],
                             reg["dt_ass"], (reg["orgao"] or "")[:30], reg["situacao"],
                             reg["v_repassado"], reg["v_conc"])
                return 0
            for reg in achados.values():
                cur.execute(_SQL, reg)
            conn.commit()
            status = "partial" if falhas else "success"
            log.info("=== Convênios PR: %d gravado(s), status=%s ===", len(achados), status)
            _log_ingest(cur, conn, status, len(achados),
                        " | ".join(falhas)[:400] or None)
            return len(achados)
        except Exception as e:
            conn.rollback()
            log.error("Convênios PR falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ingest(dry="--dry" in sys.argv)
