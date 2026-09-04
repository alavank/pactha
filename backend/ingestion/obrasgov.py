"""
Obras.gov.br / CIPI — obras federais no municipio, sem login e sem token.

O Cadastro Integrado de Projetos de Investimento reune as obras federais com
execucao fisica, fontes de recurso, tomador e executor. Complementa o SISMOB (so
saude) e o SIMEC (so educacao): aqui entra o resto — mobilidade, saneamento,
habitacao, seguranca, e a **reconstrucao da Defesa Civil**, que em Nova Palma e
22 dos 30 projetos.

⭐⭐ **04/09/2026: A FONTE MUDOU DE HOST, E COM ELA SUMIRAM TRES ARMADILHAS.**
Ate 03/09 este coletor falava com `api.obrasgov.gestao.gov.br`, que **recusa o
IP da VPS** (429 na primeira requisicao, medido tres vezes) — e por isso ficou
pronto e desligado por dois dias. O Governo publica o MESMO acervo em
**`api-publica.obrasgov.gestao.gov.br/obras`**, com contrato OpenAPI proprio,
e esse host **responde 200 ao servidor** (0,16 s, medido em 04/09).

O que a medicao contra a API nova mostrou, ponto a ponto contra o que a antiga
obrigava:

    paginacao mente (`last` sempre true) .... NAO: total_items constante (10.372
                                             no RS) em qualquer pagina/tamanho
    paginas se sobrepoem (41 de 200) ....... NAO: zero repetidos, ordem estavel
    rate limit apertado (3s -> 429) ........ NAO: 12 requisicoes seguidas SEM
                                             pausa, zero erro, 0,72 s de media
    projeto sem CNPJ ....................... MELHOR: 87% tem (antes 60%)
    filtro desconhecido ignorado em silencio  SIM, CONTINUA — ver armadilha 1

Por isso a varredura caiu de ~8 minutos por UF (60 paginas x 8 s de pausa) para
~75 segundos (52 paginas de 200 a ~0,7 s). O teto de `tamanho_da_pagina` e
**200**; 201 devolve 422.

AS ARMADILHAS QUE VALEM NESTA API, todas medidas em 04/09/2026:

1. ⚠️⚠️ **NAO EXISTE FILTRO TERRITORIAL, E PARAMETRO DESCONHECIDO NAO DA ERRO.**
   `codigo_ibge=4313102` devolve HTTP 200 com o estado inteiro — `total_items`
   identico ao da consulta sem filtro. Quem confiasse nele gravaria obra do
   Amapa como sendo do municipio. O recorte e feito AQUI, e o unico filtro do
   contrato que serve e `uf_principal`.

2. ⚠️⚠️ **O MUNICIPIO SE RECONHECE POR CNPJ, NUNCA POR NOME** (diretriz do dono,
   04/09/2026). Casar por nome trouxe, na medicao, **379 obras da Universidade
   Federal de Santa Maria** como se fossem da prefeitura — mais 6 do hospital
   universitario. Nome tem homonimo e o erro e silencioso: nao levanta excecao,
   nao zera a contagem, so mistura dinheiro de outro ente no painel do cliente.
   Por isso este coletor depende de `municipios.cnpj` estar preenchido (o
   `ingestion/siconfi.py` preenche sozinho, do cadastro de entes do Tesouro) e
   soma os CNPJs proprios de fundos e autarquias ja conhecidos.

3. ⚠️ **O PROJETO RARAMENTE DIZ ONDE FICA.** De 200 projetos do RS medidos, so
   32 tinham CEP ou endereco — e 174 tinham CNPJ em `tomadores`/`executores`. O
   CNPJ e o caminho; endereco e enfeite.

4. ⚠️ **`sistema_resp` REVELA SOBREPOSICAO COM O QUE JA COLETAMOS.** Uma UBS do
   RS veio com `sistema_resp: SISMOB` — ou seja, o CIPI reune obras que o
   `sismob_obras` ja traz por outro caminho. A coluna `sistema_origem` guarda
   isso para a tela poder dizer "esta obra voce ja ve no SISMOB" em vez de
   mostrar a mesma obra duas vezes como se fossem duas.

5. ⚠️ **UMA OBRA PODE TER VARIOS TOMADORES**, e um deles pode ser de outro ente
   (consorcio, obra intermunicipal). O casamento e por interseccao de CNPJ com a
   carteira; um projeto que casa com dois municipios da carteira e gravado para
   os dois, e a chave `id_unico` faz a ultima gravacao vencer — ver o cabecalho
   de `migrations/add_obrasgov.sql`.

Rodavel por Scheduled Task em qualquer worker, ou a mao:
    python -u ingestion/obrasgov.py            # coleta de verdade
    python -u ingestion/obrasgov.py --dry      # varre e mostra, sem gravar
"""
import json
import logging
import os
import re
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("obrasgov")

# ⚠️ `api-publica`, e nao `api`. O host sem o prefixo e o que bloqueia a VPS.
BASE = os.getenv("OBRASGOV_BASE",
                 "https://api-publica.obrasgov.gestao.gov.br/obras")
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0 dados abertos Obras.gov.br)",
      "Accept": "application/json"}
FONTE = "OBRASGOV"
TIMEOUT = 90

# Teto da fonte: 201 devolve 422.
TAMANHO_PAGINA = min(int(os.getenv("OBRASGOV_TAMANHO_PAGINA", "200") or "200"), 200)
# Sem rate limit observado (12 requisicoes seguidas, zero erro). Meio segundo e
# cortesia com a fonte, nao necessidade — e ainda deixa a varredura do RS em
# ~75 s.
PAUSA_S = float(os.getenv("OBRASGOV_PAUSA_S", "0.5") or "0.5")
# Guarda contra `total_pages` absurdo. 52 paginas cobrem o RS; 400 cobre SP com
# folga e ainda impede um laco infinito se a fonte mudar de comportamento.
TETO_PAGINAS = int(os.getenv("OBRASGOV_TETO_PAGINAS", "400") or "400")
MIN_INTERVAL_H = int(os.getenv("OBRASGOV_MIN_INTERVAL_H", "20") or "20")


def _so_digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


# ⚠️ A FONTE MANDA PARTE DO TEXTO COM ACENTO CODIFICADO DUAS VEZES, e isso e
# dela, nao nosso. Medido em 04/09/2026 pedindo o projeto `137854.31-54`: os
# bytes que chegam sao
#
#     b'Creche Proinf\xc3\x83\xc2\xa2ncia  - Ara\xc3\x83\xc2\xbajos'
#
# que e o UTF-8 de "Ã¢" — ou seja, o Governo leu um texto latin-1 como se fosse
# UTF-8 e gravou o resultado. Na tela sai "Creche ProinfÃ¢ncia - AraÃºjos".
#
# O conserto e exato: reinterpretar os bytes como latin-1 desfaz a camada extra.
# Mas ele SO PODE SER APLICADO ONDE O ESTRAGO EXISTE — em "PAVIMENTAÇÃO", que
# esta correto, a mesma operacao produziria lixo. Por isso as tres guardas:
# procurar a assinatura do estrago, tentar a conversao, e desistir se ela nao
# melhorar. Sem elas, um "conserto" cego corromperia o texto sadio da maioria.
_MOJIBAKE = re.compile(r"Ã[-¿]|Â[-¿]|â€")


def _texto(v) -> str | None:
    """Texto da fonte, com o acento duplamente codificado desfeito."""
    s = str(v or "").strip()
    if not s:
        return None
    for _ in range(2):        # a fonte tem casos de DUAS camadas
        if not _MOJIBAKE.search(s):
            break
        try:
            candidato = s.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
        # So aceita se de fato reduziu o estrago: uma conversao que nao melhora
        # e uma conversao que esta errada.
        if len(_MOJIBAKE.findall(candidato)) >= len(_MOJIBAKE.findall(s)):
            break
        s = candidato
    return s or None


def pagina(client: httpx.Client, uf: str, n: int) -> dict | None:
    """Uma pagina da UF. `None` = desistiu, e NAO significa "acabou".

    Mantem backoff no 429 mesmo sem rate limit observado: a medicao de hoje nao
    promete o comportamento de amanha, e o custo de ter a rede pronta e zero
    enquanto ela nao for usada."""
    params = {"uf_principal": uf, "pagina": n, "tamanho_da_pagina": TAMANHO_PAGINA}
    for espera in (0, 15, 45, 90):
        if espera:
            log.info("    429 — aguardando %ds", espera)
            time.sleep(espera)
        r = client.get(f"{BASE}/projeto-investimento", params=params,
                       headers=UA, timeout=TIMEOUT)
        if r.status_code == 429:
            continue
        r.raise_for_status()
        return r.json()
    return None


def varrer_uf(client: httpx.Client, uf: str) -> tuple[dict, bool]:
    """Todos os projetos da UF, por `id_projeto_investimento`.

    Devolve (projetos, completo). `completo=False` quando a varredura parou por
    rate limit ou pelo teto — e nesse caso a rodada NAO pode marcar obra como
    ausente, porque a ausencia pode ser nossa.

    ⚠️ Aqui `total_pages` E confiavel (medido: constante em qualquer pagina e
    tamanho), diferente da API antiga, onde ele era calculado a partir da pagina
    pedida. Ainda assim o dedup por id continua: ele custa nada e protege de uma
    mudanca de ordenacao que ninguem anunciaria."""
    por_id: dict[str, dict] = {}
    n, total_pages = 1, None
    while n <= TETO_PAGINAS:
        d = pagina(client, uf, n)
        if d is None:
            if n == 1:
                log.error("  %s: 429 JA NA PRIMEIRA PAGINA. Se isto persistir, o "
                          "host novo passou a recusar o IP como o antigo faz — "
                          "conferir com scripts/medir_obrasgov_vps.sh", uf)
            else:
                log.warning("  %s: interrompida por rate limit na pagina %d "
                            "(%d projeto(s)) — resultado PARCIAL", uf, n, len(por_id))
            return por_id, False

        itens = d.get("data") or []
        if total_pages is None:
            total_pages = d.get("total_pages") or 1
            log.info("  %s: %s projeto(s) em %s pagina(s)",
                     uf, d.get("total_items"), total_pages)
        if not itens:
            return por_id, True
        novos = 0
        for x in itens:
            uid = x.get("id_projeto_investimento")
            if uid and uid not in por_id:
                por_id[uid] = x
                novos += 1
        if n % 10 == 0 or n == total_pages:
            log.info("    pagina %d/%s — acumulado %d", n, total_pages, len(por_id))
        if n >= total_pages:
            return por_id, True
        n += 1
        time.sleep(PAUSA_S)
    log.warning("  %s: teto de %d paginas — resultado PARCIAL", uf, TETO_PAGINAS)
    return por_id, False


def cnpjs_do_projeto(p: dict) -> set[str]:
    """CNPJs de 14 digitos em tomadores e executores (armadilhas 2 e 3).

    ⚠️ Cada lista tem o SEU nome de campo (`cnpj_tomador`, `cnpj_executor`) —
    nao ha um `codigo` generico como na API antiga. Ler o campo errado devolve
    conjunto vazio e o municipio fica sem nenhuma obra, em silencio."""
    out = set()
    for lista, campo in (("tomadores", "cnpj_tomador"),
                         ("executores", "cnpj_executor")):
        for x in (p.get(lista) or []):
            c = _so_digitos(x.get(campo))
            # Orgao federal aparece com codigo SIAFI/UG curto (36210), que nao
            # casa com CNPJ nenhum e cai fora pelo comprimento.
            if len(c) == 14:
                out.add(c)
    return out


def _alvos(cur) -> dict[str, list[dict]]:
    """{uf: [municipios]} com os CNPJs conhecidos de cada um.

    Mesma descoberta do `che_rs.py`: a prefeitura vem de `municipios.cnpj` e as
    demais entidades (tipicamente o Fundo Municipal de Saude) saem das fontes
    federais ja coletadas."""
    cur.execute("""
        SELECT id, nome, upper(coalesce(uf,'')),
               regexp_replace(coalesce(cnpj,''), '\\D', '', 'g')
          FROM municipios
         WHERE active AND coalesce(uf,'') <> ''
         ORDER BY nome
    """)
    municipios = [{"id": r[0], "nome": r[1], "uf": r[2], "cnpjs": set()}
                  for r in cur.fetchall()]
    proprio = {m["id"]: m for m in municipios}
    ids = list(proprio)
    cur.execute("""
        SELECT id, regexp_replace(coalesce(cnpj,''), '\\D', '', 'g')
          FROM municipios WHERE active
    """)
    cnpj_proprio = {r[0]: r[1] for r in cur.fetchall()}

    extras: dict[int, set[str]] = {}
    if ids:
        cur.execute("""
            SELECT DISTINCT municipio_id, cnpj FROM (
                SELECT s.municipio_id,
                       regexp_replace(coalesce(s.nu_cnpj,''), '\\D', '', 'g') AS cnpj
                  FROM sismob_obras s WHERE s.municipio_id = ANY(%s)
                UNION
                SELECT p.municipio_id,
                       regexp_replace(coalesce(p.cnpj,''), '\\D', '', 'g')
                  FROM transferegov_pac p WHERE p.municipio_id = ANY(%s)
            ) t WHERE length(cnpj) = 14
        """, (ids, ids))
        for mid, cnpj in cur.fetchall():
            extras.setdefault(mid, set()).add(cnpj)

    por_uf: dict[str, list[dict]] = {}
    for m in municipios:
        if len(cnpj_proprio.get(m["id"]) or "") == 14:
            m["cnpjs"].add(cnpj_proprio[m["id"]])
        m["cnpjs"] |= extras.get(m["id"], set())
        if m["cnpjs"]:
            por_uf.setdefault(m["uf"], []).append(m)
        else:
            log.info("  %s/%s: sem CNPJ conhecido — nao da para reconhecer as "
                     "obras dele (rode ingestion/siconfi.py, que preenche)",
                     m["nome"], m["uf"])
    return por_uf


_SQL = """
INSERT INTO obrasgov_projetos (
    municipio_id, id_unico, nome, descricao, funcao_social, meta_global,
    natureza, especie, situacao, uf, cep, endereco,
    data_inicial_prevista, data_final_prevista, data_inicial_efetiva,
    data_final_efetiva, data_situacao, data_cadastro,
    populacao_beneficiada, empregos_gerados, valor_investimento_previsto,
    origens_recurso, eixos, tipos, tomadores, executores, repassadores,
    sistema_origem, raw_data, atualizado_em)
VALUES (%(mid)s, %(uid)s, %(nome)s, %(desc)s, %(social)s, %(meta)s,
        %(natureza)s, %(especie)s, %(situacao)s, %(uf)s, %(cep)s, %(end)s,
        %(dt_ini_prev)s, %(dt_fim_prev)s, %(dt_ini_efe)s, %(dt_fim_efe)s,
        %(dt_sit)s, %(dt_cad)s, %(pop)s, %(empregos)s, %(valor)s,
        %(origens)s, %(eixos)s, %(tipos)s, %(tomadores)s, %(executores)s,
        %(repassadores)s, %(sistema)s, %(raw)s::jsonb, NOW())
ON CONFLICT (id_unico) DO UPDATE SET
    municipio_id = EXCLUDED.municipio_id, nome = EXCLUDED.nome,
    descricao = EXCLUDED.descricao, funcao_social = EXCLUDED.funcao_social,
    meta_global = EXCLUDED.meta_global, natureza = EXCLUDED.natureza,
    especie = EXCLUDED.especie, situacao = EXCLUDED.situacao, uf = EXCLUDED.uf,
    cep = EXCLUDED.cep, endereco = EXCLUDED.endereco,
    data_inicial_prevista = EXCLUDED.data_inicial_prevista,
    data_final_prevista = EXCLUDED.data_final_prevista,
    data_inicial_efetiva = EXCLUDED.data_inicial_efetiva,
    data_final_efetiva = EXCLUDED.data_final_efetiva,
    data_situacao = EXCLUDED.data_situacao, data_cadastro = EXCLUDED.data_cadastro,
    populacao_beneficiada = EXCLUDED.populacao_beneficiada,
    empregos_gerados = EXCLUDED.empregos_gerados,
    valor_investimento_previsto = EXCLUDED.valor_investimento_previsto,
    origens_recurso = EXCLUDED.origens_recurso, eixos = EXCLUDED.eixos,
    tipos = EXCLUDED.tipos, tomadores = EXCLUDED.tomadores,
    executores = EXCLUDED.executores, repassadores = EXCLUDED.repassadores,
    sistema_origem = EXCLUDED.sistema_origem,
    raw_data = EXCLUDED.raw_data, atualizado_em = NOW()
"""


def _lista(itens, *campos) -> list[str]:
    """Nomes de uma lista aninhada, tentando os campos na ordem dada."""
    fora = []
    for x in (itens or []):
        for c in campos:
            v = _texto(x.get(c))
            if v:
                fora.append(v)
                break
    return fora


def _data(v):
    """`None` continua `None`: data efetiva vazia e "ainda nao aconteceu"."""
    s = str(v or "").strip()
    return s[:10] if s else None


def linha(municipio_id: int, p: dict) -> dict:
    """Uma linha do banco a partir do projeto da API nova.

    ⚠️ TODOS os nomes de campo mudaram com o host (camelCase -> snake_case, e
    varios renomeados: `nome` -> `desc_nome`, `fontesDeRecurso` ->
    `investimentos_previstos`). Ler um campo antigo devolve `None` sem erro
    nenhum — a linha grava vazia e ninguem percebe."""
    invest = p.get("investimentos_previstos") or []
    # A fonte traz uma linha por origem (Federal, Estadual, Municipal).
    valor = None
    for f in invest:
        v = f.get("vl_investimento_previsto")
        if isinstance(v, (int, float)):
            valor = (valor or 0) + v
    eixos_tipos = p.get("eixos_tipos") or []
    return {
        "mid": municipio_id,
        "uid": p.get("id_projeto_investimento"),
        "nome": _texto(p.get("desc_nome")),
        "desc": _texto(p.get("desc_projeto")),
        "social": _texto(p.get("desc_funcao_social")),
        "meta": _texto(p.get("desc_meta_global")),
        "natureza": p.get("natureza_intervencao"),
        "especie": p.get("especie_intervencao"),
        "situacao": p.get("situacao"),
        "uf": p.get("uf_principal"),
        "cep": str(p.get("nr_cep") or "").strip() or None,
        "end": _texto(p.get("desc_endereco")),
        "dt_ini_prev": _data(p.get("dt_inicial_prevista")),
        "dt_fim_prev": _data(p.get("dt_final_prevista")),
        "dt_ini_efe": _data(p.get("dt_inicial_efetiva")),
        "dt_fim_efe": _data(p.get("dt_final_efetiva")),
        # A API nova nao publica data da situacao; o campo fica nulo em vez de
        # receber a de cadastro, que responderia outra pergunta.
        "dt_sit": None,
        "dt_cad": _data(p.get("dt_cadastro")),
        "pop": p.get("populacao_beneficiada"),
        "empregos": p.get("qtd_empregos_gerados"),
        "valor": valor,
        "origens": [_texto(f.get("desc_nome_fonte_recurso")) or ""
                    for f in invest],
        "eixos": _lista(eixos_tipos, "eixo"),
        "tipos": _lista(eixos_tipos, "tipo"),
        "tomadores": _lista(p.get("tomadores"), "organizacao_tomador"),
        "executores": _lista(p.get("executores"), "organizacao_executor"),
        "repassadores": _lista(p.get("repassadores"), "organizacao_repassador"),
        # Armadilha 4: diz se a obra ja chega por outro coletor nosso.
        "sistema": p.get("sistema_resp"),
        "raw": json.dumps(p, ensure_ascii=False),
    }


def _log_ingest(cur, conn, status: str, n: int, erro: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES ('obrasgov', %s, %s, %s, NOW())",
            (status, n, erro))
        conn.commit()
    except Exception as e:
        log.warning("ingestion_log falhou: %s", str(e)[:120])


def ingest(dry: bool = False) -> int:
    from datetime import datetime

    from ingestion._resilience import get_sync_db_url, neon_connect

    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            if not dry and os.getenv("OBRASGOV_FORCE") != "1":
                cur.execute("SELECT max(finished_at) FROM ingestion_log "
                            "WHERE source = 'obrasgov' AND status IN ('success','ok')")
                ultimo = (cur.fetchone() or [None])[0]
                if ultimo:
                    horas = (datetime.now(ultimo.tzinfo) - ultimo).total_seconds() / 3600
                    if horas < MIN_INTERVAL_H:
                        log.info("ultima coleta ha %.1fh (< %dh) — pulando. "
                                 "OBRASGOV_FORCE=1 forca.", horas, MIN_INTERVAL_H)
                        return 0

            por_uf = _alvos(cur)
            if not por_uf:
                log.info("nenhum municipio com CNPJ conhecido — nada a reconhecer")
                if not dry:
                    _log_ingest(cur, conn, "success", 0)
                return 0

            gravados = 0
            parciais = []
            with httpx.Client(follow_redirects=True) as client:
                for uf, municipios in sorted(por_uf.items()):
                    log.info("UF %s: %d municipio(s) na carteira", uf, len(municipios))
                    projetos, completo = varrer_uf(client, uf)
                    if not completo:
                        parciais.append(uf)
                    # Indice CNPJ -> municipio, montado uma vez (armadilha 2).
                    de_quem: dict[str, dict] = {}
                    for m in municipios:
                        for c in m["cnpjs"]:
                            de_quem[c] = m
                    achados = 0
                    por_municipio: dict[str, int] = {}
                    for p in projetos.values():
                        donos = {de_quem[c]["id"]: de_quem[c]["nome"]
                                 for c in cnpjs_do_projeto(p) if c in de_quem}
                        for mid, nome in donos.items():
                            achados += 1
                            por_municipio[nome] = por_municipio.get(nome, 0) + 1
                            if dry:
                                continue
                            cur.execute(_SQL, linha(mid, p))
                            gravados += 1
                    log.info("  %s: %d projeto(s) varrido(s), %d da carteira%s",
                             uf, len(projetos), achados,
                             (" — " + ", ".join(f"{k}: {v}" for k, v in
                                                sorted(por_municipio.items())))
                             if por_municipio else "")
                    if dry:
                        for p in list(projetos.values())[:3]:
                            log.info("      %s  %s", p.get("id_projeto_investimento"),
                                     (p.get("desc_nome") or "")[:60])

            if dry:
                return 0
            conn.commit()
            log.info("=== Obras.gov.br: %d linha(s) gravada(s)%s ===", gravados,
                     f", PARCIAL em {', '.join(parciais)}" if parciais else "")
            if parciais:
                # ⚠️ Varredura interrompida por rate limit NAO e sucesso: a
                # ausencia de uma obra pode ser nossa, nao da fonte.
                _log_ingest(cur, conn, "partial", gravados,
                            "varredura interrompida por rate limit (429) em: "
                            + ", ".join(parciais))
            else:
                _log_ingest(cur, conn, "success", gravados)
            return gravados
        except Exception as e:
            conn.rollback()
            log.error("Obras.gov.br falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ingest(dry="--dry" in sys.argv)
