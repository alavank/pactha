#!/usr/bin/env python3
"""reconcilia_tg.py — Reconciliacao amostral CSV dados abertos TransfereGov x export do banco PACTHA (READ-ONLY).

Replica backend/ingestion/transferegov_opendata.py: _numero_proposta (:113), _money (:223),
_situacao/_SITUACAO (:188-209), TG_IGNORA_SITUACOES (:373-376), exigencia ID_PROPOSTA+NR_PROPOSTA (:389-392),
join convenio (:429-457) e emenda (:465-484). Chave de comparacao = (COD_MUNIC_IBGE, numero_proposta normalizado).

Uso:
  python reconcilia_tg.py --export csv/export_tg.csv --out out/reconciliacao.md
      [--ibge 3108008,3100000] [--cache csv/cache] [--db-snapshot "2026-08-29 02:10"]
      [--ignora-situacoes "A|B|C"] [--max-linhas 300]
So stdlib. Downloads ~200-400 MB (cache 20h); leitura do siconv_proposta (751 MB) ~1-3 min.
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import time
import unicodedata
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://api-publica.transferegov.gestao.gov.br/downloads/dadosgov"
CACHE_HORAS = 20
TOL = Decimal("0.01")
IGNORA_DEFAULT = ("Proposta/Plano de Trabalho Cadastrados|Proposta Eliminada em Chamamento Público|"
                  "Eliminada em Análise Preliminar")
# copia literal de transferegov_opendata.py:_SITUACAO (CONFERIR contra o arquivo antes de rodar)
SITUACAO_MAP = {
    "Convênio Anulado": "Instrumento Anulado",
    "Convênio Rescindido": "Instrumento Rescindido",
    "Cancelado": "Instrumento Anulado",
    "Inadimplente": "INADIMPLENTE",
    "Prestação de Contas Comprovada em Análise": "Prestação de Contas Comprovada - Em Análise",
    "Proposta/Plano de Trabalho Enviado para Análise": "Proposta/Plano de Trabalho enviado para Análise",
    "Proposta/Plano de Trabalho Complementado Enviado para Análise": "Proposta/Plano de Trabalho complementado enviada para Análise",
    "Proposta/Plano de Trabalho Complementado em Análise": "Proposta/Plano de Trabalho complementado em Análise",
    "Proposta/Plano de Trabalho Aprovado": "Proposta/Plano de Trabalho Aprovados",
    "Proposta Aprovada e Plano de Trabalho Complementado Enviado para Análise": "Proposta Aprovada e Plano de Trabalho Complementado enviado para Análise",
}
COLS_PROP = {"COD_MUNIC_IBGE", "SIT_PROPOSTA", "ID_PROPOSTA", "NR_PROPOSTA", "VL_GLOBAL_PROP",
             "VL_REPASSE_PROP", "VL_CONTRAPARTIDA_PROP", "DIA_PROPOSTA", "NM_PROPONENTE"}
COLS_CONV = {"ID_PROPOSTA", "NR_CONVENIO", "SIT_CONVENIO", "VL_GLOBAL_CONV", "VL_REPASSE_CONV", "VL_CONTRAPARTIDA_CONV"}
COLS_EMEN = {"ID_PROPOSTA", "NOME_PARLAMENTAR", "VALOR_REPASSE_EMENDA"}
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# ------------------------------------------------------------ normalizacoes (espelho do coletor)
def numero_proposta(bruto):
    s = (bruto or "").strip()
    if not s or "/" not in s:
        return s or None
    numero, _, ano = s.partition("/")
    numero, ano = numero.strip(), ano.strip()
    if not numero.isdigit():
        return s
    return f"{numero.zfill(6)}/{ano}"


def money(v):
    s = (str(v) if v is not None else "").strip()
    if not s:
        return None
    s = s.replace("R$", "").replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def situacao(sit_prop, sit_conv):
    bruta = (sit_conv or "").strip() or (sit_prop or "").strip()
    return SITUACAO_MAP.get(bruta, bruta) if bruta else None


def norm(s):
    """comparacao 'suave' de rotulo: sem acento, caixa, pontuacao (estado igual, grafia diferente)."""
    if s is None:
        return ""
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def dec_db(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def data_br(s):
    s = (s or "").strip().split(" ")[0]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def txt(s):
    return (s or "").strip() or None


# ------------------------------------------------------------ download (stream, cache) + leitura no zip
def baixa(nome, cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    dest = os.path.join(cache_dir, nome)
    meta = dest + ".meta.json"
    if os.path.exists(dest) and os.path.getsize(dest) > 1000 and (time.time() - os.path.getmtime(dest)) / 3600 < CACHE_HORAS:
        info = json.load(open(meta, encoding="utf-8")) if os.path.exists(meta) else {}
        log(f"  {nome}: cache {(time.time()-os.path.getmtime(dest))/3600:.1f}h | Last-Modified={info.get('last_modified')}")
        return dest, info
    url = f"{BASE}/{nome}"
    log(f"  baixando {url}")
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (auditoria PACTHA; download unico)"})
    part = f"{dest}.{os.getpid()}.part"
    try:
        with urlopen(req, timeout=180) as r, open(part, "wb") as fh:
            info = {"url": url, "last_modified": r.headers.get("Last-Modified"),
                    "content_length": r.headers.get("Content-Length"),
                    "baixado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            tot = marco = 0
            while True:
                b = r.read(512 * 1024)
                if not b:
                    break
                fh.write(b)
                tot += len(b)
                if tot - marco >= 50 * 1024 * 1024:
                    marco = tot
                    log(f"    {nome}: {tot/1e6:.0f} MB")
        if os.path.getsize(part) < 1000:
            raise OSError(f"{nome}: download vazio/truncado")
        os.replace(part, dest)
        json.dump(info, open(meta, "w", encoding="utf-8"))
        log(f"  {nome}: {os.path.getsize(dest):,} bytes | Last-Modified={info['last_modified']}")
        return dest, info
    except HTTPError as e:
        raise SystemExit(f"{url} -> HTTP {e.code}. Se 404: endereco de dados abertos mudou "
                         f"(ambiente antigo desligado em 31/08/2026; conferir TRANSFEREGOV_DADOS_URL no worker).")
    except URLError as e:
        raise SystemExit(f"{url} -> {e}")
    finally:
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:
                pass


def linhas(caminho, obrigatorias):
    """Itera o CSV de dentro do zip em stream (sem descompactar em disco), utf-8-sig, ';'."""
    with zipfile.ZipFile(caminho) as z:
        interno = z.namelist()[0]
        with z.open(interno) as bruto:
            texto = io.TextIOWrapper(bruto, encoding="utf-8-sig", errors="replace", newline="")
            leitor = csv.DictReader(texto, delimiter=";")
            if leitor.fieldnames:
                leitor.fieldnames = [c.strip().lstrip("\ufeff") for c in leitor.fieldnames]
            faltam = obrigatorias - set(leitor.fieldnames or [])
            if faltam:
                raise SystemExit(f"{os.path.basename(caminho)}: colunas ausentes {sorted(faltam)} — layout mudou? "
                                 f"cabecalho={(leitor.fieldnames or [])[:30]}")
            yield from leitor


# ------------------------------------------------------------ coleta do CSV (mesma logica do coletor)
def coleta_csv(cache_dir, alvos, ignora):
    props, ignoradas, colisoes, meta = {}, {}, defaultdict(list), {}
    n_lidas = n_sem_chave = 0
    caminho, meta["siconv_proposta.zip"] = baixa("siconv_proposta.zip", cache_dir)
    for l in linhas(caminho, COLS_PROP):
        ibge = (l.get("COD_MUNIC_IBGE") or "").strip()
        if ibge not in alvos:
            continue
        n_lidas += 1
        sit = (l.get("SIT_PROPOSTA") or "").strip()
        idp = (l.get("ID_PROPOSTA") or "").strip()
        nr = numero_proposta(l.get("NR_PROPOSTA"))
        if sit in ignora:
            ignoradas[idp or f"?{n_lidas}"] = {"ibge": ibge, "nr": nr, "sit": sit}
            continue
        if not idp or not nr:
            n_sem_chave += 1
            continue
        props[idp] = {
            "ibge": ibge, "nr": nr, "id": idp, "sit_prop": sit,
            "situacao": situacao(sit, None),
            "proponente": txt(l.get("NM_PROPONENTE")),
            "codigo_instrumento": None, "situacao_siafi": None, "n_conv": 0,
            "valor_global": money(l.get("VL_GLOBAL_PROP")),
            "valor_repasse": money(l.get("VL_REPASSE_PROP")),
            "valor_contrapartida": money(l.get("VL_CONTRAPARTIDA_PROP")),
            "valor_emenda": None, "parlamentar": None,
            "dt_proposta": data_br(l.get("DIA_PROPOSTA")),
        }
        colisoes[(ibge, nr)].append(idp)
    log(f"  propostas dos alvos: lidas={n_lidas} validas={len(props)} ignoradas_por_situacao={len(ignoradas)} sem_chave={n_sem_chave}")

    caminho, meta["siconv_convenio.zip"] = baixa("siconv_convenio.zip", cache_dir)
    n_conv = 0
    for l in linhas(caminho, COLS_CONV):
        p = props.get((l.get("ID_PROPOSTA") or "").strip())
        if p is None:
            continue
        n_conv += 1
        p["n_conv"] += 1
        p["codigo_instrumento"] = txt(l.get("NR_CONVENIO"))
        p["situacao_siafi"] = txt(l.get("SIT_CONVENIO"))
        p["situacao"] = situacao(p["sit_prop"], l.get("SIT_CONVENIO"))
        for campo, col in (("valor_global", "VL_GLOBAL_CONV"), ("valor_repasse", "VL_REPASSE_CONV"),
                           ("valor_contrapartida", "VL_CONTRAPARTIDA_CONV")):
            v = money(l.get(col))
            if v is not None:
                p[campo] = v
    log(f"  com convenio: {n_conv}")

    caminho, meta["siconv_emenda.zip"] = baixa("siconv_emenda.zip", cache_dir)
    nomes, soma = defaultdict(list), defaultdict(Decimal)
    for l in linhas(caminho, COLS_EMEN):
        idp = (l.get("ID_PROPOSTA") or "").strip()
        if idp not in props:
            continue
        nome = (l.get("NOME_PARLAMENTAR") or "").strip()
        if nome and nome not in nomes[idp]:
            nomes[idp].append(nome)
        ve = money(l.get("VALOR_REPASSE_EMENDA"))
        if ve is not None:
            soma[idp] += ve
    for idp, ns in nomes.items():
        props[idp]["parlamentar"] = ", ".join(ns)
    for idp, tot in soma.items():
        props[idp]["valor_emenda"] = tot
    log(f"  com parlamentar: {len(nomes)} | com valor_emenda: {len(soma)}")

    # chave do banco = (municipio, numero_proposta); em colisao o upsert deixa o ULTIMO do arquivo vencer
    por_chave = {}
    for p in props.values():
        por_chave[(p["ibge"], p["nr"])] = p
    colis = {k: v for k, v in colisoes.items() if len(v) > 1}
    return por_chave, ignoradas, colis, meta


# ------------------------------------------------------------ export do banco (psql --csv)
def carrega_export(path):
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    need = {"ibge_code", "nome", "numero_proposta", "codigo_instrumento", "situacao", "situacao_siafi",
            "valor_global", "valor_repasse", "valor_contrapartida", "valor_emenda"}
    if not rows:
        raise SystemExit("export vazio")
    if need - set(rows[0].keys()):
        raise SystemExit(f"export sem colunas {sorted(need - set(rows[0]))}")
    db, nomes = {}, {}
    for r in rows:
        k = (r["ibge_code"].strip(), r["numero_proposta"].strip())
        db[k] = r
        nomes[k[0]] = r["nome"]
    return db, nomes


# ------------------------------------------------------------ comparacao
def cmp_dec(a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= TOL


def compara(alvos, csvk, dbk, ignoradas, colisoes, snapshot):
    ign_por_chave = {(v["ibge"], v["nr"]): v["sit"] for v in ignoradas.values()}
    nr_em_outro = defaultdict(set)
    for (ibge, nr) in csvk:
        nr_em_outro[nr].add(ibge)
    out = {}
    for ibge, nome in alvos.items():
        c = {k: v for k, v in csvk.items() if k[0] == ibge}
        d = {k: v for k, v in dbk.items() if k[0] == ibge}
        so_csv, so_db, ambos = sorted(set(c) - set(d)), sorted(set(d) - set(c)), sorted(set(c) & set(d))
        r = {"nome": nome, "n_csv": len(c), "n_db": len(d), "ambos": len(ambos),
             "instr_csv": sum(1 for v in c.values() if v["codigo_instrumento"]),
             "instr_db": sum(1 for v in d.values() if txt(v["codigo_instrumento"])),
             "vg_csv": sum((v["valor_global"] or Decimal(0)) for v in c.values()),
             "vg_db": sum((dec_db(v["valor_global"]) or Decimal(0)) for v in d.values()),
             "vr_csv": sum((v["valor_repasse"] or Decimal(0)) for v in c.values()),
             "vr_db": sum((dec_db(v["valor_repasse"]) or Decimal(0)) for v in d.values()),
             "so_csv": [], "so_db": [], "div": [],
             "colisoes": {k[1]: v for k, v in colisoes.items() if k[0] == ibge},
             "ignoradas_no_csv": sum(1 for v in ignoradas.values() if v["ibge"] == ibge)}
        for k in so_csv:
            p = c[k]
            nova = bool(snapshot and p["dt_proposta"] and p["dt_proposta"] >= snapshot)
            r["so_csv"].append({"nr": k[1], "id": p["id"], "situacao": p["situacao"], "instr": p["codigo_instrumento"],
                                "vg": p["valor_global"], "dt_proposta": p["dt_proposta"], "proponente": p["proponente"],
                                "classe": "nova apos snapshot do banco" if nova else "FALTA NO BANCO"})
        for k in so_db:
            row = d[k]
            if k in ign_por_chave:
                classe = f"ignorada por situacao ({ign_por_chave[k]})"
            elif k[1] in nr_em_outro:
                classe = f"mesmo numero em outro IBGE {sorted(nr_em_outro[k[1]])}"
            else:
                classe = "AUSENTE NO CSV (removida na origem? so scraper por CNPJ?)"
            r["so_db"].append({"nr": k[1], "situacao": row["situacao"], "instr": row["codigo_instrumento"],
                               "vg": row["valor_global"], "id_siconv": row.get("id_proposta_siconv"),
                               "updated_at": row.get("updated_at"), "classe": classe})
        for k in ambos:
            p, row = c[k], d[k]
            difs = []
            if p["codigo_instrumento"] != txt(row["codigo_instrumento"]):
                difs.append(("codigo_instrumento", p["codigo_instrumento"], row["codigo_instrumento"]))
            if p["situacao"] != txt(row["situacao"]):
                tipo = "situacao(rotulo)" if norm(p["situacao"]) == norm(row["situacao"]) else "situacao(ESTADO)"
                difs.append((tipo, p["situacao"], row["situacao"]))
            if p["situacao_siafi"] != txt(row["situacao_siafi"]):
                difs.append(("situacao_siafi", p["situacao_siafi"], row["situacao_siafi"]))
            for f in ("valor_global", "valor_repasse", "valor_contrapartida", "valor_emenda"):
                if not cmp_dec(p[f], dec_db(row[f])):
                    difs.append((f, p[f], row[f]))
            ids = txt(row.get("id_proposta_siconv"))
            if ids and p["id"] != ids:
                difs.append(("id_proposta_siconv", p["id"], ids))
            if difs:
                r["div"].append({"nr": k[1], "difs": difs, "updated_at": row.get("updated_at"),
                                 "det_at": row.get("detalhe_atualizado_em")})
        out[ibge] = r
    return out


# ------------------------------------------------------------ relatorio
def esc(s):
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ")


def escreve_md(path, res, meta, args, ignora):
    L = ["# Reconciliação amostral — CSV dados abertos TransfereGov × banco Freitas", ""]
    L.append(f"- Gerado em: {datetime.now().isoformat(timespec='seconds')} (hora local)")
    L.append(f"- Export do banco: `{args.export}` | snapshot do banco (último `transferegov_opendata` success): **{args.db_snapshot or 'não informado'}**")
    for k, v in meta.items():
        L.append(f"- `{k}`: Last-Modified=`{v.get('last_modified')}` bytes={v.get('content_length')} baixado_em={v.get('baixado_em_utc')}")
    L.append(f"- Situações ignoradas (TG_IGNORA_SITUACOES): `{' | '.join(sorted(ignora))}`")
    L.append(f"- Tolerância monetária: {TOL}")
    L.append("")
    L.append("## Resumo por município")
    L.append("")
    L.append("| Município | IBGE | CSV | Banco | Ambos | Só CSV | Só banco | Ignoradas (CSV) | Instr CSV | Instr banco | Σ global CSV | Σ global banco | Δ global | Σ repasse CSV | Σ repasse banco | Diverg. | Colisões |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for ibge, r in res.items():
        L.append(f"| {r['nome']} | {ibge} | {r['n_csv']} | {r['n_db']} | {r['ambos']} | {len(r['so_csv'])} | {len(r['so_db'])} | "
                 f"{r['ignoradas_no_csv']} | {r['instr_csv']} | {r['instr_db']} | {r['vg_csv']:,.2f} | {r['vg_db']:,.2f} | "
                 f"{r['vg_csv']-r['vg_db']:,.2f} | {r['vr_csv']:,.2f} | {r['vr_db']:,.2f} | {len(r['div'])} | {len(r['colisoes'])} |")
    L.append("")
    L.append("## Classificação das diferenças (todas as amostras)")
    L.append("")
    agg = defaultdict(int)
    for r in res.values():
        for x in r["so_csv"]:
            agg[f"só CSV: {x['classe']}"] += 1
        for x in r["so_db"]:
            agg[f"só banco: {x['classe'].split(' (')[0]}"] += 1
        for x in r["div"]:
            for f, _, _ in x["difs"]:
                agg[f"campo: {f}"] += 1
    for k in sorted(agg):
        L.append(f"- {k}: **{agg[k]}**")
    L.append("")
    mx = args.max_linhas
    for ibge, r in res.items():
        L.append(f"## {r['nome']} ({ibge})")
        L.append("")
        if r["colisoes"]:
            L.append("### Colisões de chave (mesmo numero_proposta no CSV para o município — o upsert deixa o último vencer)")
            L.append("")
            for nr, ids in r["colisoes"].items():
                L.append(f"- `{nr}`: ID_PROPOSTA {ids}")
            L.append("")
        L.append(f"### Só no CSV ({len(r['so_csv'])})")
        L.append("")
        if r["so_csv"]:
            L.append("| numero_proposta | ID_PROPOSTA | situação | instrumento | valor_global | dt_proposta | proponente | classe |")
            L.append("|---|---|---|---|---:|---|---|---|")
            for x in r["so_csv"][:mx]:
                L.append(f"| {x['nr']} | {x['id']} | {esc(x['situacao'])} | {esc(x['instr'])} | {x['vg'] or ''} | "
                         f"{x['dt_proposta'] or ''} | {esc(x['proponente'])} | {x['classe']} |")
            if len(r["so_csv"]) > mx:
                L.append(f"| … | | | | | | | +{len(r['so_csv'])-mx} linhas |")
        L.append("")
        L.append(f"### Só no banco ({len(r['so_db'])})")
        L.append("")
        if r["so_db"]:
            L.append("| numero_proposta | id_proposta_siconv | situação (banco) | instrumento | valor_global | updated_at | classe |")
            L.append("|---|---|---|---|---:|---|---|")
            for x in r["so_db"][:mx]:
                L.append(f"| {x['nr']} | {esc(x['id_siconv'])} | {esc(x['situacao'])} | {esc(x['instr'])} | {x['vg'] or ''} | "
                         f"{esc(x['updated_at'])} | {esc(x['classe'])} |")
            if len(r["so_db"]) > mx:
                L.append(f"| … | | | | | | +{len(r['so_db'])-mx} linhas |")
        L.append("")
        L.append(f"### Em ambos com valor diferente ({len(r['div'])} propostas)")
        L.append("")
        if r["div"]:
            L.append("| numero_proposta | campo | CSV | banco | updated_at banco | detalhe_atualizado_em |")
            L.append("|---|---|---|---|---|---|")
            n = 0
            for x in r["div"]:
                for f, a, b in x["difs"]:
                    n += 1
                    if n <= mx:
                        L.append(f"| {x['nr']} | {f} | {esc(a)} | {esc(b)} | {esc(x['updated_at'])} | {esc(x['det_at'])} |")
            if n > mx:
                L.append(f"| … | | | | | +{n-mx} linhas |")
        L.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    log(f"relatorio: {path}")


def resumo_json(res, meta, args):
    r = {"gerado_em": datetime.now().isoformat(timespec="seconds"), "db_snapshot": args.db_snapshot,
         "arquivos": meta, "municipios": {}}
    for ibge, x in res.items():
        r["municipios"][ibge] = {
            "nome": x["nome"], "n_csv": x["n_csv"], "n_db": x["n_db"], "ambos": x["ambos"],
            "so_csv": len(x["so_csv"]), "so_csv_falta_no_banco": sum(1 for s in x["so_csv"] if s["classe"] == "FALTA NO BANCO"),
            "so_db": len(x["so_db"]), "so_db_ignorada_situacao": sum(1 for s in x["so_db"] if s["classe"].startswith("ignorada")),
            "so_db_ausente_csv": sum(1 for s in x["so_db"] if s["classe"].startswith("AUSENTE")),
            "instr_csv": x["instr_csv"], "instr_db": x["instr_db"],
            "vg_csv": str(x["vg_csv"]), "vg_db": str(x["vg_db"]), "delta_vg": str(x["vg_csv"] - x["vg_db"]),
            "propostas_divergentes": len(x["div"]),
            "campos_divergentes": dict(sorted(
                ((f, sum(1 for d in x["div"] for g, _, _ in d["difs"] if g == f))
                 for f in {g for d in x["div"] for g, _, _ in d["difs"]}))),
            "colisoes": len(x["colisoes"]),
        }
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", required=True, help="CSV do x13 (psql --csv)")
    ap.add_argument("--out", required=True, help="Markdown de saida (o .json vai ao lado)")
    ap.add_argument("--ibge", default="", help="lista separada por virgula; default = todos do export")
    ap.add_argument("--cache", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "csv", "cache"))
    ap.add_argument("--db-snapshot", default="", help="'YYYY-MM-DD HH:MM' (UTC) do ultimo transferegov_opendata success")
    ap.add_argument("--ignora-situacoes", default=IGNORA_DEFAULT, help="mesmo valor de TG_IGNORA_SITUACOES do worker")
    ap.add_argument("--max-linhas", type=int, default=300)
    args = ap.parse_args()

    dbk, nomes = carrega_export(args.export)
    alvos = {i.strip(): nomes.get(i.strip(), "?") for i in args.ibge.split(",") if i.strip()} or dict(nomes)
    ignora = {s.strip() for s in args.ignora_situacoes.split("|") if s.strip()}
    snapshot = None
    if args.db_snapshot:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                snapshot = datetime.strptime(args.db_snapshot.strip(), fmt).date()
                break
            except ValueError:
                pass
        if snapshot is None:
            raise SystemExit("--db-snapshot: use 'YYYY-MM-DD HH:MM' ou 'YYYY-MM-DD'")
    log(f"alvos: {alvos}")

    csvk, ignoradas, colisoes, meta = coleta_csv(args.cache, alvos, ignora)
    res = compara(alvos, csvk, dbk, ignoradas, colisoes, snapshot)
    escreve_md(args.out, res, meta, args, ignora)
    js = resumo_json(res, meta, args)
    jpath = os.path.splitext(args.out)[0] + ".json"
    with open(jpath, "w", encoding="utf-8") as fh:
        json.dump(js, fh, ensure_ascii=False, indent=1, default=str)
    print(json.dumps(js["municipios"], ensure_ascii=False, indent=1))
    log(f"json: {jpath}")


if __name__ == "__main__":
    main()
