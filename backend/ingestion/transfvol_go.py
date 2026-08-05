"""Transferências Voluntárias do Estado de GOIÁS — dados abertos da CGE-GO.

Fonte: CKAN `dadosabertos.go.gov.br`, dataset "Transferências Voluntárias"
(d95472ce-e543-4e5e-8472-cd73cd966e40). Recursos MENSAIS
(`Transferências Voluntárias AAAAMM`) mais ZIPs anuais para o histórico.

⚠️ ISTO É PAGAMENTO, NÃO INSTRUMENTO. A base não traz número de convênio,
vigência nem situação — traz quem recebeu, quando, quanto e por qual unidade
orçamentária. Por isso grava em `repasses_estaduais` e não em
`convenios_estadual` (ver a migration, que explica a decisão).

⚠️ CINCO ARMADILHAS, TODAS MEDIDAS NO ARQUIVO REAL (05/2026) — não supostas:

1. **O ENCODING MUDA DE MÊS PARA MÊS.** 202605/202604/202601 são latin-1;
   202602 é UTF-8. Fixar um só corrompe o outro — e o estrago não é cosmético:
   com latin-1 num arquivo UTF-8, a coluna "Unidade Orçamentária" vira
   "Unidade OrÃ§amentÃ¡ria" e o mês inteiro é descartado pela guarda de esquema.
   Por isso `_decodificar` TENTA utf-8 primeiro (latin-1 aceita qualquer byte e
   nunca falha, então tem de ser o último).
2. **CNPJ mascarado** (`01.067.479/0001-46`). Casa por dígitos.
3. **DUAS colunas de processo**, com nomes quase iguais e valores DIFERENTES:
   `Numero Processo` (2026.2850.035.00005) e `Numero de Processo`
   (202400010023224). As duas são reais e as duas entram na chave.
4. **Não existe id.** A chave é composta de 7 campos. Com 5 campos, duas
   parcelas do mesmo valor, no mesmo dia, do mesmo processo, colidiam — só se
   distinguem pelo outro processo e pela fonte de recursos. Medido: 1281 linhas
   -> 1281 chaves com os 7; 1280 com 5. Chave curta = pagamento sumindo calado.
5. **Valor com vírgula decimal e sem separador de milhar**: "10237,5" são
   R$ 10.237,50 e "50000" são R$ 50.000,00.

BÔNUS: a coluna DESCRICAO traz, em parte das linhas, o número da emenda e o
deputado autor — extraídos aqui por regex, com o cuidado de parar antes do
"Beneficiario:" (senão o nome do deputado sai grudado no da entidade).
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

log = logging.getLogger("transfvol-go")

CKAN = "https://dadosabertos.go.gov.br"
DATASET = "d95472ce-e543-4e5e-8472-cd73cd966e40"
FONTE = "TRANSFVOL-GO"
UF = "GO"
# Quantos meses para trás buscar a cada rodada. 6 cobre o atraso de publicação
# (o mês 202605 saiu em 22/06) sem baixar o histórico inteiro todo dia.
MESES_ATRAS = 6

# ⚠️ AS COLUNAS QUE O ARQUIVO TEM DE TER. Sem esta conferência o coletor é cego:
# medido em 05/08/2026, o recurso publicado como "Transferências Voluntárias
# 202603" contém OUTRO ARQUIVO — 49 mil linhas, delimitado por vírgula, esquema
# diferente, dados de 2024. O coletor processou tudo, casou ZERO e registrou
# "success". Um mês inteiro poderia sumir do painel sem uma linha de aviso.
#
# Erro na origem a gente não conserta; erro na origem PASSANDO POR NÓS EM
# SILÊNCIO, sim.
COLUNAS_MINIMAS = {"CPF/CNPJ", "Data do Repasse", "Valor do Pagamento (R$)",
                   "Unidade Orçamentária", "Numero de Processo"}

_NOME_MES = re.compile(r"(\d{6})\s*$")
# "Emenda ... número 642 ... Deputado (a) FULANO DE TAL" — para antes de
# "Beneficiario", "Objeto", ponto final ou ponto-e-vírgula.
_EMENDA = re.compile(
    r"[Ee]menda\s+(?:Parlamentar\s+)?(?:Impositiva\s+)?"
    r"n[uú]mero\s*(\d{1,6})", re.S)
_AUTOR = re.compile(
    r"Deputad[oa]\s*\(?\s*a?\s*\)?\s*"
    r"([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-Za-zÀ-ÿ'\s\.]{3,60}?)"
    r"(?=\s*(?:Benefici|Objeto|[.;,]|$))", re.S)


def _decodificar(raw: bytes) -> str:
    """O encoding varia por competência (ver armadilha 1). utf-8 ANTES de
    latin-1: latin-1 decodifica qualquer sequência de bytes sem erro, então
    tentá-lo primeiro esconderia todo arquivo UTF-8 atrás de mojibake."""
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _so_digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _limpo(s) -> str:
    """Tira o \xa0 (espaço não separável) que a origem usa dentro do texto."""
    return " ".join(str(s or "").replace("\xa0", " ").split())


def _valor(s) -> float | None:
    """"10237,5" -> 10237.5 · "50000" -> 50000.0. Vírgula é decimal; não há
    separador de milhar (conferido no arquivo)."""
    t = _so_digitos_virgula(s)
    if not t:
        return None
    try:
        return float(t.replace(",", "."))
    except ValueError:
        return None


def _so_digitos_virgula(s) -> str:
    return re.sub(r"[^\d,]", "", str(s or ""))


def _data(s) -> date | None:
    t = (s or "").strip()
    for f in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t, f).date()
        except ValueError:
            pass
    return None


def _chave(r: dict) -> str:
    """Os 7 campos que tornam a linha única. Ver a armadilha 4 no topo."""
    return "|".join([
        _so_digitos(r.get("CPF/CNPJ")),
        (r.get("Data do Repasse") or "").strip(),
        (r.get("Valor do Pagamento (R$)") or "").strip(),
        _limpo(r.get("Unidade Orçamentária"))[:120],
        (r.get("Numero de Processo") or "").strip(),
        (r.get("Numero Processo") or "").strip(),
        (r.get("Fonte de Recursos") or "").strip(),
    ])


def _emenda_autor(descricao: str) -> tuple[str | None, str | None]:
    d = descricao or ""
    m_num = _EMENDA.search(d)
    m_aut = _AUTOR.search(d)
    autor = _limpo(m_aut.group(1)).strip(" .") if m_aut else None
    return (m_num.group(1) if m_num else None, autor or None)


def _recursos_mensais(client: httpx.Client) -> list[tuple[str, str]]:
    """[(AAAAMM, url)] dos CSVs mensais, do mais novo para o mais antigo."""
    r = client.get(f"{CKAN}/api/3/action/package_show",
                   params={"id": DATASET}, timeout=60)
    r.raise_for_status()
    saida = []
    for rec in (r.json().get("result") or {}).get("resources", []):
        if (rec.get("format") or "").upper() != "CSV":
            continue
        m = _NOME_MES.search(rec.get("name") or "")
        if m and rec.get("url"):
            saida.append((m.group(1), rec["url"]))
    return sorted(saida, reverse=True)


def _mapa_cnpj(cur) -> dict:
    """CNPJ (14 dígitos) -> municipio_id, para os municípios de GO do tenant.

    ⚠️ CNPJ ambíguo (o mesmo em dois municípios — acontece com consórcio) é
    EXCLUÍDO e logado, em vez de resolvido por sorteio: gravar o repasse no
    município errado é pior que não gravar. Mesma decisão do coletor do ES.
    """
    cur.execute("""
        SELECT cnpj_digitos, municipio_id FROM (
            SELECT regexp_replace(coalesce(t.cnpj, ''), '\\D', '', 'g') AS cnpj_digitos,
                   t.municipio_id
            FROM transferegov_pac t JOIN municipios m ON m.id = t.municipio_id
            WHERE m.active AND upper(coalesce(m.uf, '')) = %s
            UNION
            SELECT regexp_replace(coalesce(s.nu_cnpj, ''), '\\D', '', 'g'),
                   s.municipio_id
            FROM sismob_obras s JOIN municipios m ON m.id = s.municipio_id
            WHERE m.active AND upper(coalesce(m.uf, '')) = %s
        ) q WHERE length(cnpj_digitos) = 14
    """, (UF, UF))
    porcnpj: dict[str, set] = {}
    for cnpj, mid in cur.fetchall():
        porcnpj.setdefault(cnpj, set()).add(mid)
    mapa, ambiguos = {}, []
    for cnpj, ids in porcnpj.items():
        if len(ids) == 1:
            mapa[cnpj] = next(iter(ids))
        else:
            ambiguos.append((cnpj, sorted(ids)))
    for cnpj, ids in ambiguos:
        log.warning("CNPJ %s aparece em %s — EXCLUIDO do mapa (nao adivinhamos)",
                    cnpj, ids)
    return mapa


def _gravar(cur, mid: int, r: dict) -> None:
    desc = _limpo(r.get("DESCRICAO"))
    num, autor = _emenda_autor(desc)
    dt = _data(r.get("Data do Repasse"))
    import json as _json
    cur.execute("""
        INSERT INTO repasses_estaduais (
            municipio_id, fonte, chave, cnpj, credor, orgao, formalidade,
            elemento, sub_elemento, processo, processo_alt, fonte_recursos,
            descricao, emenda_numero, emenda_autor, data_repasse, valor, ano,
            raw_data
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
        ON CONFLICT (fonte, chave) DO UPDATE SET
            credor = EXCLUDED.credor,
            descricao = EXCLUDED.descricao,
            emenda_numero = COALESCE(EXCLUDED.emenda_numero, repasses_estaduais.emenda_numero),
            emenda_autor = COALESCE(EXCLUDED.emenda_autor, repasses_estaduais.emenda_autor),
            valor = EXCLUDED.valor,
            raw_data = EXCLUDED.raw_data,
            updated_at = NOW()
    """, (
        mid, FONTE, _chave(r), _so_digitos(r.get("CPF/CNPJ"))[:14],
        _limpo(r.get("Nome/Razão Social do Credor"))[:300],
        _limpo(r.get("Unidade Orçamentária"))[:300],
        _limpo(r.get("Formalidade"))[:120],
        _limpo(r.get("Elemento Despesa"))[:160],
        _limpo(r.get("Sub Elemento"))[:200],
        (r.get("Numero Processo") or "").strip()[:60],
        (r.get("Numero de Processo") or "").strip()[:60],
        (r.get("Fonte de Recursos") or "").strip()[:40],
        desc[:4000], (num or None), (autor[:160] if autor else None),
        dt, _valor(r.get("Valor do Pagamento (R$)")),
        dt.year if dt else None,
        _json.dumps({k: _limpo(v) for k, v in r.items()}, ensure_ascii=False),
    ))


def _log_ingest(cur, status: str, inseridos: int, erro: str | None = None):
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES (%s,%s,%s,%s,NOW())",
            ("transfvol_go", status, inseridos, erro))
    except Exception:
        pass


def ingest() -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect
    # ⚠️ `neon_connect` é CONTEXT MANAGER (lição do coletor do ES: `conn =
    # neon_connect(...)` estoura no primeiro `.cursor()`).
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            mapa = _mapa_cnpj(cur)
            if not mapa:
                log.info("nenhum municipio de GO com CNPJ conhecido — "
                         "Transferencias Voluntarias de GO nao se aplica a este tenant")
                _log_ingest(cur, "success", 0)
                conn.commit()
                return 0
            log.info("TransfVol-GO: %d CNPJ(s) de municipio de GO no mapa", len(mapa))

            gravados = achados = 0
            formato_ruim: list[str] = []
            with httpx.Client(follow_redirects=True, timeout=120,
                              headers={"User-Agent": "Mozilla/5.0"}) as cli:
                recursos = _recursos_mensais(cli)[:MESES_ATRAS]
                if not recursos:
                    raise RuntimeError("nenhum recurso CSV mensal no CKAN de GO")
                for competencia, url in recursos:
                    resp = cli.get(url)
                    resp.raise_for_status()
                    # Encoding detectado, não assumido: ver armadilha 1.
                    texto = _decodificar(resp.content)
                    leitor = csv.DictReader(io.StringIO(texto), delimiter=";")
                    achadas = set(leitor.fieldnames or [])
                    faltando = COLUNAS_MINIMAS - achadas
                    if faltando:
                        # NÃO é "mês sem repasse": é arquivo com outro formato.
                        # Sai alto no log e derruba o status para `partial`, para
                        # o monitor de coleta acusar em vez de mostrar verde.
                        log.warning(
                            "  %s: FORMATO INESPERADO — faltam %s | colunas do arquivo: %s"
                            " | %d linha(s) IGNORADAS (recurso publicado com outro"
                            " arquivo na origem)",
                            competencia, sorted(faltando),
                            sorted(achadas)[:6], texto.count(chr(10)))
                        formato_ruim.append(competencia)
                        continue
                    linhas = list(leitor)
                    do_mes = 0
                    for r in linhas:
                        mid = mapa.get(_so_digitos(r.get("CPF/CNPJ")))
                        if not mid:
                            continue
                        achados += 1
                        _gravar(cur, mid, r)
                        gravados += 1
                        do_mes += 1
                    log.info("  %s: %d de %d linha(s) sao dos nossos municipios",
                             competencia, do_mes, len(linhas))
            conn.commit()
            log.info("TransfVol-GO: %d repasse(s) encontrados, %d gravados%s",
                     achados, gravados,
                     f" | {len(formato_ruim)} mes(es) ignorados: {formato_ruim}"
                     if formato_ruim else "")
            # Mês ignorado por formato NÃO pode sair como sucesso.
            status = "success" if (gravados == achados and not formato_ruim) else "partial"
            _log_ingest(cur, status, gravados,
                        f"competencias com formato inesperado: {formato_ruim}"
                        if formato_ruim else None)
            conn.commit()
            return gravados
        except Exception as e:
            conn.rollback()
            log.error("TransfVol-GO falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, "error", 0, str(e)[:400])
            conn.commit()
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ingest()
