"""TERMOS DE COMPROMISSO do SIMEC/PAR (MEC) -> tabela simec_termos.

O que o PACTHA ja tinha do SIMEC era `simec_par_liberacoes`: os PAGAMENTOS (OB,
data, valor). Faltava o INSTRUMENTO — o Termo de Compromisso: processo, tipo,
vigencia e valor. E o que o relatorio precisa para dizer "o municipio tem um TC
com clausula suspensiva de R$ 3,1 mi vencido ha 595 dias".

FONTE (publica, SEM login — verificado ao vivo 17/08/2026):
    POST https://simec.mec.gov.br/par/carregaTermos.php
    form-data: estuf=<UF>&muncod=<codigo IBGE>&requisicao=
O GET devolve so o formulario (~30KB); o POST com o municipio devolve a pagina
com as tabelas (~110KB). O campo `requisicao` existe no form mas o valor nao
altera o resultado — mandamos vazio.

TABELAS: a pagina traz mais de uma (PAR/PAC/aditivos), TODAS com o mesmo cabecalho
util: Termo de Compromisso | Processo | Nº do Documento | Tipo de Documento |
Tipo do Objeto | Data da Validacao | Periodo do Pagamento | Vigencia |
Valor do Termo (ou Quantidade de Obra). Lemos todas e deduplicamos por
(processo, nº documento) — o portal repete a MESMA linha varias vezes.

Rodar:  python -m ingestion.simec_termos
        SIMEC_TERMOS_LOTE=5 python -m ingestion.simec_termos   (so N municipios)

ONDE RODA: Scheduled Task `simec-termos` nos QUATRO workers, as 06:10, com lock
PROPRIO (/tmp/simec_termos.lock — o /tmp/scraper.lock existe para serializar
Chromium, e esta fonte e httpx puro) e timeout 1700s. 1x/dia basta: o que ela
traz e o INSTRUMENTO, que muda em MESES; quem se move e o pagamento, e isso vem
4x/dia pelo simec_par.
"""
from __future__ import annotations
import os
import re
import json
import time
import logging
from datetime import datetime

import httpx
import psycopg2

logger = logging.getLogger("simec_termos")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

_URL = "https://simec.mec.gov.br/par/carregaTermos.php"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/131 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Content-Type": "application/x-www-form-urlencoded",
}
_DELAY = float(os.getenv("SIMEC_TERMOS_DELAY", "1.5") or "1.5")
# 1500s, pela regra de ouro do repo: orcamento interno + 1 municipio pesado, e a
# coluna `timeout` da Scheduled Task = interno + 120s. A task `simec-termos` dos
# 4 workers tem timeout 1700, entao 1500 e o numero que fecha a conta.
# ⚠️ O PR #259 baixou isto para 600 porque achava que a fonte rodava pendurada no
# orcamento do SIGCON. Ela nao roda: tem task PROPRIA, com lock proprio. Rodada
# cortada vira 'partial' no ingestion_log e o rodizio cobre o resto na proxima;
# se isso virar rotina, o certo e subir esta env no worker E o timeout da task
# junto, nunca so uma das duas.
_BUDGET_S = float(os.getenv("SIMEC_TERMOS_BUDGET_S", "1500") or "1500")

# Cabecalho util (o resto da pagina tem tabelas de layout, sem estes rotulos)
_COLS = {
    "processo": ("processo",),
    "nr_documento": ("documento",),          # "Nº do Documento"
    "tipo_documento": ("tipo de documento",),
    "tipo_objeto": ("tipo do objeto", "tipo de objeto"),
    "dt_validacao": ("data da valida",),
    "periodo_pagamento": ("per", "pagamento"),   # "Período do Pagamento"
    "vigencia_txt": ("vig",),
    "valor_termo": ("valor do termo",),
    "quantidade_obra": ("quantidade de obra",),
    # ⚠️ AS QUATRO DE DINHEIRO, ausentes ate 31/08/2026. A pagina sempre as
    # trouxe; o mapa e que parava no "valor do termo". Era por isso que o RM
    # mostrava so o valor pactuado do TC e nada do que foi empenhado ou pago.
    #
    # ⚠️ O rotulo do PAGO MUDA entre as tabelas da MESMA pagina: "Pagamento
    # Efetivado" no bloco de TC/aditivo, "Valor Pago" no de PAR/PAC. Os dois
    # fragmentos caem no mesmo campo.
    #
    # ⚠️ Fragmento CURTO aqui casa coluna errada, porque `_mapa_colunas` usa
    # `any`. "valor" sozinho pegaria "Valor do Termo"; "pagamento" sozinho
    # pegaria "Periodo do Pagamento". Por isso os fragmentos sao as expressoes
    # inteiras — ha um teste que reprova se um deles voltar a ser curto.
    "valor_empenhado": ("valor empenhado",),
    "valor_pago": ("pagamento efetivado", "valor pago"),
    "saldo_bancario": ("saldo banc",),
    "prestacao_contas": ("presta",),
}


def _sync_url() -> str:
    u = os.getenv("DATABASE_URL_SYNC", "") or os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
    return u.replace("&channel_binding=require", "").replace("?channel_binding=require", "")


# Chave do rodizio em `scraper_municipio_coleta` e `source` do `ingestion_log`.
# A convencao do repo e "a string e o nome do modulo" (simec_par.py grava
# 'simec_par'; transferegov_te.py grava 'transferegov_te').
# ⚠️ NAO REAPROVEITAR 'simec_par'. Sao dois coletores, duas tabelas
# (simec_par_liberacoes = os PAGAMENTOS; simec_termos = o INSTRUMENTO) e duas
# cadencias: compartilhar a string faria a rodada saudavel de um esconder a
# quebra do outro no frescor — e literalmente o defeito que deu ao lote horario
# do TransfereGov uma fonte so dele (ver watchdog_coleta.py).
FONTE_COLETA = "simec_termos"


def _marca_coleta(municipio_id: int, ok: bool, erro: str | None = None) -> None:
    """Carimba a passagem pelo municipio — SEMPRE, inclusive em erro.

    Copia deliberada de transferegov_voluntarias._marca_coleta: com NULLS FIRST,
    carimbar so quando a rodada volta com dado faz o municipio problematico (ou
    grande demais para a janela) ocupar o primeiro lugar da fila em TODA rodada,
    para sempre, e os demais nunca serem alcancados.

    CONEXAO PROPRIA (padrao do cagec_scraper): a contabilidade do rodizio nunca
    pode derrubar a coleta. No cursor compartilhado, um erro aqui abortaria a
    transacao e levaria junto os termos ja inseridos.
    """
    try:
        cx = psycopg2.connect(_sync_url())
        try:
            with cx.cursor() as c:
                c.execute(
                    "INSERT INTO scraper_municipio_coleta "
                    "  (fonte, municipio_id, ultima_coleta_em, ultimo_erro_em, ultimo_erro, tentativas) "
                    "VALUES (%s, %s, NOW(), CASE WHEN %s THEN NULL ELSE NOW() END, %s, "
                    "        CASE WHEN %s THEN 0 ELSE 1 END) "
                    "ON CONFLICT (fonte, municipio_id) DO UPDATE SET "
                    "  ultima_coleta_em = NOW(), "
                    "  ultimo_erro_em = CASE WHEN %s THEN scraper_municipio_coleta.ultimo_erro_em ELSE NOW() END, "
                    "  ultimo_erro    = CASE WHEN %s THEN NULL ELSE %s END, "
                    "  tentativas     = CASE WHEN %s THEN 0 ELSE scraper_municipio_coleta.tentativas + 1 END",
                    (FONTE_COLETA, municipio_id, ok,
                     ((erro or "")[:400] if not ok else None),
                     ok, ok, ok, (erro or "")[:400], ok))
            cx.commit()
        finally:
            cx.close()
    except Exception as e:
        logger.debug("  (rodizio nao registrado p/ municipio %s: %s)", municipio_id, e)


def _log_ingestao(status: str, n: int, erro: str | None = None) -> None:
    """Linha em `ingestion_log` (source 'simec_termos') no fim da rodada.

    Sem ela a fonte e INVISIVEL: nao aparece no monitor de frescor
    (routers/freshness.py), nao pode ser cobrada pelo watchdog (que so cobra
    fonte que ja tem linha no log) e nao entra no /api/control/ingestion.

    CONEXAO PROPRIA e excecao ENGOLIDA, como transferegov_te e sismob_obras:
    quando chegamos aqui o run() ja fechou cur/cn, e o `cn.rollback()` do except
    por municipio pode ter deixado a transacao suja. Falhar ao gravar o log nao
    pode desfazer coleta que deu certo — este coletor commita municipio a
    municipio.

    ⚠️ VOCABULARIO: 'success' / 'partial' / 'error'. O 'ok'/'parcial'/'erro' do
    cagec_scraper e dialeto historico e NAO deve ser imitado — quem le isto
    (watchdog_coleta.STATUS_SUCESSO, routers/freshness._SUCESSO) so aceita
    'success' e 'ok' como sucesso, e 'partial' fica de fora DE PROPOSITO.
    """
    try:
        cx = psycopg2.connect(_sync_url())
        c = cx.cursor()
        c.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, error_message, finished_at) "
            "VALUES ('simec_termos', %s, %s, %s, NOW())",
            (status, n, (erro[:500] if erro else None)),
        )
        cx.commit(); c.close(); cx.close()
    except Exception as e:
        logger.warning(f"ingestion_log falhou: {str(e)[:120]}")


def _txt(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _data(s: str):
    """Primeira data dd/mm/aaaa do texto (as celulas trazem varias, separadas por
    virgula, e a que interessa e a primeira)."""
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(0), "%d/%m/%Y").date()
    except ValueError:
        return None


def _valor(s: str):
    """'R$3.157.096,83' -> 3157096.83"""
    m = re.search(r"([\d.]+,\d{2})", (s or "").replace("\xa0", " "))
    if not m:
        return None
    try:
        return float(m.group(1).replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _mapa_colunas(cab: list[str]) -> dict:
    """indice de cada coluna util, casando por FRAGMENTO do cabecalho (os rotulos
    do portal tem acento e variam entre as tabelas)."""
    idx = {}
    for i, c in enumerate(cab):
        cl = (c or "").strip().casefold()
        for campo, frags in _COLS.items():
            if campo in idx:
                continue
            if all(f in cl for f in frags) if campo == "periodo_pagamento" else any(f in cl for f in frags):
                idx[campo] = i
    return idx


def parse_termos(html: str) -> list[dict]:
    """Todas as linhas de termo da pagina, deduplicadas. Funcao PURA (testavel)."""
    achados: dict[tuple, dict] = {}
    for tabela in re.findall(r"<table.*?</table>", html, re.S | re.I):
        linhas = re.findall(r"<tr.*?</tr>", tabela, re.S | re.I)
        if len(linhas) < 2:
            continue
        cab = [_txt(x) for x in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", linhas[0], re.S | re.I)]
        idx = _mapa_colunas(cab)
        # so vale a tabela que tem processo E documento (as de layout nao tem)
        if "processo" not in idx or "nr_documento" not in idx:
            continue
        for ln in linhas[1:]:
            cels = [_txt(x) for x in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", ln, re.S | re.I)]
            if not any(cels):
                continue
            def g(campo):
                i = idx.get(campo)
                return cels[i] if i is not None and i < len(cels) else ""
            proc, doc = g("processo"), g("nr_documento")
            if not (proc or doc):
                continue
            chave = (proc, doc)
            if chave in achados:      # o portal repete a MESMA linha
                continue
            achados[chave] = {
                "processo": proc or None,
                "nr_documento": doc or None,
                "tipo_documento": g("tipo_documento") or None,
                "tipo_objeto": g("tipo_objeto") or None,
                "dt_validacao": _data(g("dt_validacao")),
                "periodo_pagamento": g("periodo_pagamento") or None,
                "vigencia_txt": g("vigencia_txt") or None,
                "dt_vigencia": _data(g("vigencia_txt")),
                "valor_termo": _valor(g("valor_termo")),
                "quantidade_obra": (g("quantidade_obra") or None),
                "valor_empenhado": _valor(g("valor_empenhado")),
                "valor_pago": _valor(g("valor_pago")),
                "saldo_bancario": _valor(g("saldo_bancario")),
                "prestacao_contas": (g("prestacao_contas") or None),
                "raw": {k: g(k) for k in _COLS},
            }
    return list(achados.values())


def _upsert(cur, mid: int, t: dict):
    cur.execute(
        """INSERT INTO simec_termos
             (municipio_id, processo, nr_documento, tipo_documento, tipo_objeto,
              dt_validacao, periodo_pagamento, vigencia_txt, dt_vigencia,
              valor_termo, quantidade_obra,
              valor_empenhado, valor_pago, saldo_bancario, prestacao_contas,
              raw_data, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())
           ON CONFLICT (municipio_id, COALESCE(processo, ''), COALESCE(nr_documento, ''))
           DO UPDATE SET
             tipo_documento=EXCLUDED.tipo_documento, tipo_objeto=EXCLUDED.tipo_objeto,
             dt_validacao=EXCLUDED.dt_validacao, periodo_pagamento=EXCLUDED.periodo_pagamento,
             vigencia_txt=EXCLUDED.vigencia_txt, dt_vigencia=EXCLUDED.dt_vigencia,
             valor_termo=EXCLUDED.valor_termo, quantidade_obra=EXCLUDED.quantidade_obra,
             -- ⚠️ SOBRESCRITA DIRETA, sem COALESCE: o SIMEC e a fonte unica
             -- destas quatro, e empenho, pago e saldo MUDAM. Um COALESCE
             -- congelaria o numero do dia em que a coluna nasceu.
             valor_empenhado=EXCLUDED.valor_empenhado, valor_pago=EXCLUDED.valor_pago,
             saldo_bancario=EXCLUDED.saldo_bancario,
             prestacao_contas=EXCLUDED.prestacao_contas,
             raw_data=EXCLUDED.raw_data, updated_at=NOW()""",
        (mid, t["processo"], t["nr_documento"], t["tipo_documento"], t["tipo_objeto"],
         t["dt_validacao"], t["periodo_pagamento"], t["vigencia_txt"], t["dt_vigencia"],
         t["valor_termo"], t["quantidade_obra"],
         t["valor_empenhado"], t["valor_pago"], t["saldo_bancario"],
         t["prestacao_contas"], json.dumps(t["raw"], ensure_ascii=False)),
    )


def run(lote: int | None = None) -> dict:
    cn = psycopg2.connect(_sync_url())
    cur = cn.cursor()
    _lote = lote or int(os.getenv("SIMEC_TERMOS_LOTE", "0") or "0")
    # ⚠️ DUAS CORRECOES NO MESMO SELECT.
    #
    # 1. SO CARTEIRA ATIVA. Ex-cliente nao e municipio apagado — a regra do repo
    #    e "nunca deletar municipio, desativar", e so a Freitas tem 18
    #    desativados com o historico preservado. Sem o filtro eles entram no
    #    laco de POST um a um (requisicao + 1,5s de espera cada) e, pior, termo
    #    NOVO de ex-cliente e GRAVADO em simec_termos, que o RM le
    #    (services/rm_builder.py). Todo vizinho que visita municipio a municipio
    #    ja filtra: simec_par, sismob_obras, transferegov_voluntarias,
    #    cagec_scraper, che_rs. E `coalesce(m.active, true)`, nao `= true`,
    #    porque a coluna nao e NOT NULL — e como watchdog_coleta e routers/bi
    #    ja a leem.
    #
    # 2. O CARIMBO DO RODIZIO E `scraper_municipio_coleta`, NAO MAX(updated_at)
    #    da propria tabela. Ordenar pelo RESULTADO so avanca a fila quando a
    #    rodada volta com dado: municipio sem nenhum termo, com erro, ou cortado
    #    pelo orcamento fica NULL para sempre e ocupa a cabeca da fila em TODA
    #    rodada — os demais nunca sao alcancados. E a armadilha do PR #159,
    #    descrita palavra por palavra em transferegov_voluntarias._marca_coleta.
    _SQL_MUNS = """
        SELECT m.id, m.nome, m.ibge_code, m.uf
        FROM municipios m
        {join}
        WHERE coalesce(m.active, true)
          AND m.ibge_code IS NOT NULL AND btrim(m.ibge_code) <> ''
        {order}
    """
    try:
        cur.execute(_SQL_MUNS.format(
            join=("LEFT JOIN scraper_municipio_coleta sc "
                  "ON sc.municipio_id = m.id AND sc.fonte = %s"),
            order="ORDER BY sc.ultima_coleta_em ASC NULLS FIRST, m.nome"),
            (FONTE_COLETA,))
    except Exception as e:
        # Tabela do rodizio ausente (worker subiu antes da migration): degrada
        # para a ordem alfabetica em vez de quebrar — mesmo tratamento do cagec.
        # O rollback e OBRIGATORIO: sem ele a transacao fica envenenada e TODO
        # upsert seguinte falha.
        logger.warning("rodizio simec_termos indisponivel (%s: %s) — ordem alfabetica",
                       type(e).__name__, str(e)[:120])
        cn.rollback()
        cur.execute(_SQL_MUNS.format(join="", order="ORDER BY m.nome"))
    muns = cur.fetchall()
    if _lote:
        muns = muns[:_lote]
    logger.info(f"SIMEC termos: {len(muns)} municipio(s)")
    # `falhas` (portal recusou / excecao) baixa o status para 'partial'; `notas`
    # (municipio pulado por cadastro incompleto) viaja no error_message SEM
    # baixar o status — se um cadastro torto fizesse a fonte inteira nascer
    # 'partial', o watchdog acusaria "nenhum sucesso registrado" para sempre, que
    # e exatamente o motivo pelo qual o CAGEC ficou meses fora da vigilancia.
    # `truncado` marca a rodada cortada pelo orcamento: cobertura parcial.
    t0, total, com = time.time(), 0, 0
    falhas: list[str] = []
    notas: list[str] = []
    truncado = False
    with httpx.Client(timeout=60, verify=False, follow_redirects=True) as cli:
        cli.get(_URL, headers=_HEADERS)   # cookie de sessao do PHP
        for mid, nome, ibge, uf in muns:
            if (time.time() - t0) > _BUDGET_S:
                logger.warning("orcamento estourou — o resto entra na proxima rodada")
                truncado = True
                break
            # ⚠️ SEM DEFAULT "MG". O default de UF foi ARRANCADO do banco em
            # migrations/uf_sem_default_mg.sql exatamente porque "municipio
            # criado sem UF nascia 'MG' e todo filtro por estado passava a
            # mentir". Aqui o estrago seria o mesmo e MUDO: `estuf` errado
            # devolve HTTP 200 com a pagina sem tabela nenhuma, indistinguivel
            # de "municipio sem termo". Pular e registrar e honesto; adivinhar
            # nao e.
            uf = (uf or "").strip().upper()
            if not uf:
                notas.append(f"{nome}: sem UF cadastrada")
                logger.warning(f"  {nome}: sem UF — o SIMEC exige estuf; pulando")
                _marca_coleta(mid, False, "sem UF cadastrada")
                continue
            try:
                r = cli.post(_URL, data={"requisicao": "", "estuf": uf, "muncod": ibge},
                             headers=_HEADERS)
                if r.status_code != 200:
                    # 403/429/503 no SIMEC e ANTI-BOT, nao "municipio sem
                    # termo": o simec_par usa curl_cffi impersonando Chrome por
                    # isso ("httpx puro recebe 403 mesmo com headers de
                    # browser"), e a skill `ingestion` nomeia o SIMEC como O
                    # caso do curl_cffi. Se comecar a aparecer, a correcao e
                    # trocar o cliente — nao insistir.
                    msg = f"HTTP {r.status_code}" + (
                        " — anti-bot? trocar por curl_cffi, como em simec_par.py"
                        if r.status_code in (403, 429, 503) else "")
                    falhas.append(f"{nome}: {msg}")
                    logger.warning(f"  {nome}: {msg}")
                    _marca_coleta(mid, False, msg)
                    time.sleep(_DELAY)   # o `continue` antigo pulava o sleep e
                    continue             # martelava o portal justo na sequencia
                                         # de erros — o oposto do que se faz sob
                                         # rate-limit
                termos = parse_termos(r.text)
                for t in termos:
                    _upsert(cur, mid, t)
                cn.commit()
                total += len(termos)
                com += 1 if termos else 0
                # ok=True MESMO com zero termos: municipio sem Termo de
                # Compromisso no MEC e resposta LEGITIMA da fonte e nao pode
                # furar a fila do rodizio para sempre.
                _marca_coleta(mid, True)
                logger.info(f"  {nome}: {len(termos)} termo(s)")
            except Exception as ex:
                cn.rollback()
                falhas.append(f"{nome}: {type(ex).__name__}: {str(ex)[:80]}")
                logger.warning(f"  {nome}: {str(ex)[:120]}")
                _marca_coleta(mid, False, f"{type(ex).__name__}: {str(ex)[:200]}")
            time.sleep(_DELAY)
    cur.close(); cn.close()
    logger.info(f"SIMEC termos: FIM — {total} termos em {com} municipio(s), "
                f"{len(falhas)} falha(s), {time.time()-t0:.0f}s")

    # ⚠️ "COLETA ZERO E ERRO, NAO SUCESSO VAZIO" — licao literal do FNS, que
    # ficou ~20 dias coletando nada em silencio (o if/elif/else abaixo e o de
    # sismob_obras). Aqui o risco e ainda mais concreto: parse_termos e regex
    # sobre o HTML do portal; se o MEC trocar o layout, TODO municipio devolve
    # HTTP 200 com zero linhas, e um 'success' com 0 termos esconderia a quebra
    # por semanas.
    nota = "; ".join(falhas + notas)
    if truncado:
        nota = (nota + " | " if nota else "") + \
               "orcamento estourou: o resto entra na proxima rodada"
    if not muns:
        _log_ingestao("error", 0, "nenhum municipio ativo com ibge_code neste tenant")
    elif total == 0:
        _log_ingestao("error", 0,
                      nota[:500] or "nenhum termo coletado — conferir o layout do portal")
    elif falhas or truncado:
        _log_ingestao("partial", total, nota[:500])
    else:
        # Rodada BOA ainda carrega as notas no error_message (ex.: municipio sem
        # UF), como transferegov_te ja faz — nota nao rebaixa status.
        _log_ingestao("success", total, nota[:500] or None)
    return {"termos": total, "municipios_com_termo": com,
            "falhas": len(falhas), "truncado": truncado}


def ingest() -> int:
    """Entrypoint do agregador de dados abertos (run_dadosabertos_cron.run_all).

    ⚠️ HOJE NINGUEM CHAMA ISTO. A fonte roda pela Scheduled Task `simec-termos`
    dos 4 workers, que executa o `__main__` (run() direto, sem passar por aqui).
    Esta funcao fica como porta de entrada alternativa: se um dia a fonte voltar
    a ser pendurada no run_dadosabertos_cron.run_all(), o gate por env e o
    auto-throttle ja estao prontos — e sao NECESSARIOS naquele caminho, porque
    run_sigcon_cron DESCONTA do orcamento do SIGCON o tempo gasto no run_all e,
    se sobrarem menos de 300s, o scraper do SIGCON nem inicia.

    O PR #259 chegou a pendura-la la por premissa errada ("nao tem task em
    nenhum worker"); o PR seguinte desfez, porque a task existe nos quatro e e o
    caminho melhor (lock proprio, timeout proprio, nao rouba do SIGCON).

    Env: SIMEC_TERMOS_ENABLED=0 desliga NESTE caminho (o `__main__` ignora o
    gate); SIMEC_TERMOS_MIN_INTERVAL_H (default 20); SIMEC_TERMOS_FORCE=1 ignora
    o intervalo.
    """
    if os.getenv("SIMEC_TERMOS_ENABLED", "1") == "0":
        logger.info("SIMEC termos: desligado neste tenant (SIMEC_TERMOS_ENABLED=0)")
        return 0
    if not os.getenv("SIMEC_TERMOS_FORCE"):
        horas = float(os.getenv("SIMEC_TERMOS_MIN_INTERVAL_H", "20") or "20")
        try:
            cx = psycopg2.connect(_sync_url()); c = cx.cursor()
            # ⚠️ 'partial' CONTA como rodada aqui — divergencia DELIBERADA do
            # sismob_obras._deve_pular, que so olha 'success'. Um unico
            # municipio recusado pelo portal ja faz a rodada inteira sair
            # 'partial'; com o filtro estrito o throttle nunca pegaria e a fonte
            # voltaria a comer o orcamento do SIGCON nas quatro janelas do dia.
            c.execute("SELECT EXTRACT(EPOCH FROM (NOW() - max(finished_at)))/3600 "
                      "FROM ingestion_log WHERE source = 'simec_termos' "
                      "  AND status IN ('success', 'partial')")
            idade = c.fetchone()[0]
            c.close(); cx.close()
            if idade is not None and float(idade) < horas:
                logger.info("SIMEC termos: ultima coleta ha %.1fh (< %sh) — pulando "
                            "(SIMEC_TERMOS_FORCE=1 forca)", float(idade), horas)
                return 0
        except Exception:
            pass       # na duvida, coleta
    return run().get("termos", 0)


if __name__ == "__main__":
    run()
