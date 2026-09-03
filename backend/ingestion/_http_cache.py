"""HTTP CONDICIONAL (ETag / If-Modified-Since) — a peca que faltava no repo.

⚠️ POR QUE ISTO EXISTE. A auditoria de 29/08/2026 mediu e registrou: **zero**
ocorrencias de ETag, If-None-Match, If-Modified-Since ou 304 nos 44 coletores; o
unico cache e por IDADE DE ARQUIVO em disco (`TRANSFEREGOV_CACHE_HORAS`), que
decide "ja faz 20h, baixa de novo" sem nunca perguntar ao servidor se algo
mudou. Resultado pratico medido na mesma auditoria: o CAUC e o Acordo FES sao
baixados **10 a 14 vezes por dia**, e o dump do SICONV federal custa 200 MB/dia
num host que compartilha 0,6 vCPU sustentado com outros dez projetos.

Esta funcao pergunta antes. Guarda o validador em `fonte_http_cache` (a chave e
a URL, porque um mesmo coletor baixa varios arquivos — um por orgao, um por ano)
e manda `If-None-Match` / `If-Modified-Since` na proxima vez. Servidor que
responde **304** custa um handshake, nao um download.

⚠️ SERVIDOR SEM VALIDADOR NAO E MOTIVO PARA NAO USAR. Quando nao vem `ETag` nem
`Last-Modified`, o download acontece e o `sha256` do conteudo responde "mudou?"
DEPOIS — nao economiza rede, mas evita reprocessar e reescrever o banco a toa,
que e a parte cara em tabela grande.

Uso:

    from ingestion._http_cache import baixar_se_mudou

    r = baixar_se_mudou(cur, client, url, fonte="tce_rs")
    if r.nao_mudou:
        log.info("  %s: 304, sem novidade", url)
        return 0
    processar(r.conteudo)
    r.confirmar(cur)      # so grava o selo DEPOIS de processar sem erro
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

log = logging.getLogger("http_cache")


@dataclass
class Resultado:
    url: str
    fonte: str
    nao_mudou: bool
    conteudo: bytes | None = None
    etag: str | None = None
    last_modified: str | None = None
    sha256: str | None = None
    tamanho: int | None = None
    # Preenchido quando o servidor nao deu validador e o hash decidiu.
    _decidido_por_hash: bool = field(default=False, repr=False)

    def confirmar(self, cur) -> None:
        """Grava o selo. ⚠️ CHAMAR SO DEPOIS DE PROCESSAR SEM ERRO.

        Gravar antes tem um modo de falha caro e silencioso: se o parser
        estourar no meio, o selo ficaria dizendo "ja tenho a versao X" e a
        proxima rodada responderia 304 sobre um arquivo que nunca foi
        processado — a fonte pararia de atualizar sem nenhum erro em log."""
        if self.nao_mudou:
            cur.execute("UPDATE fonte_http_cache SET conferido_em = NOW() "
                        "WHERE url = %s", (self.url,))
            return
        cur.execute("""
            INSERT INTO fonte_http_cache (url, fonte, etag, last_modified,
                                          tamanho, sha256, conferido_em,
                                          atualizado_em)
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (url) DO UPDATE SET
                fonte = EXCLUDED.fonte, etag = EXCLUDED.etag,
                last_modified = EXCLUDED.last_modified,
                tamanho = EXCLUDED.tamanho, sha256 = EXCLUDED.sha256,
                conferido_em = NOW(), atualizado_em = NOW()
        """, (self.url, self.fonte, self.etag, self.last_modified,
              self.tamanho, self.sha256))


def _selo(cur, url: str) -> tuple[str | None, str | None, str | None]:
    cur.execute("SELECT etag, last_modified, sha256 FROM fonte_http_cache "
                "WHERE url = %s", (url,))
    linha = cur.fetchone()
    return linha if linha else (None, None, None)


def baixar_se_mudou(cur, client, url: str, fonte: str, *,
                    timeout: int = 180, headers: dict | None = None,
                    forcar: bool = False) -> Resultado:
    """GET condicional. `nao_mudou=True` quando o servidor respondeu 304 ou
    quando o conteudo baixado tem o mesmo sha256 da ultima vez."""
    etag, last_mod, sha_antigo = (None, None, None) if forcar else _selo(cur, url)

    cab = dict(headers or {})
    if etag:
        cab["If-None-Match"] = etag
    if last_mod:
        cab["If-Modified-Since"] = last_mod

    r = client.get(url, headers=cab, timeout=timeout)

    if r.status_code == 304:
        return Resultado(url=url, fonte=fonte, nao_mudou=True)
    r.raise_for_status()

    conteudo = r.content
    sha = hashlib.sha256(conteudo).hexdigest()
    # ⚠️ O 304 e a economia de verdade (nem transfere). Este ramo pega o caso do
    # servidor que nao manda validador — ou que manda um ETag novo para conteudo
    # identico, o que acontece quando o arquivo e regerado todo dia a partir da
    # mesma base. Sem ele, o TCE-RS reescreveria 2.065 linhas por rodada por
    # causa de um cabecalho.
    if sha_antigo and sha == sha_antigo:
        return Resultado(url=url, fonte=fonte, nao_mudou=True,
                         _decidido_por_hash=True)

    return Resultado(
        url=url, fonte=fonte, nao_mudou=False, conteudo=conteudo,
        etag=r.headers.get("ETag"),
        last_modified=r.headers.get("Last-Modified"),
        sha256=sha, tamanho=len(conteudo),
    )
