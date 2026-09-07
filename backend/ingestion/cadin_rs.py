"""
CADIN/RS e CFIL/RS — os cadastros NEGATIVOS do Rio Grande do Sul.

Enquanto o CHE (`ingestion/che_rs.py`) responde *"o município está habilitado a
convêniar?"*, estes dois respondem a outra pergunta, que nenhuma outra fonte
nossa fazia: *"existe pendência inscrita contra ele?"*.

    CADIN/RS  Cadastro Informativo das Pendências perante Órgãos e Entidades da
              Administração Pública Estadual — Lei estadual 10.697/1996.
    CFIL/RS   Cadastro de Fornecedores Impedidos de Licitar e Contratar com a
              Administração Pública Estadual — Lei estadual 11.389/1999.

FONTE (medida em 07/09/2026, do Windows e da VPS): o portal `cadin.sefaz.rs.gov.br`
é um SPA Angular, e por baixo dele há **duas rotas públicas, sem login e sem
token**, que devolvem a certidão em PDF:

    POST /api/Certidao/EmitirCertidao      {"Documento": "<cnpj14>"}  -> PDF CADIN
    POST /api/Certidao/EmitirCertidaoCfil  {"Documento": "<cnpj14>"}  -> PDF CFIL

O app tem também `/api/login-cidadao/*`, e é fácil concluir que a emissão exige
sessão. Não exige: as duas rotas responderam 200 com PDF de ~190 KB para o CNPJ
da prefeitura de Nova Palma sem cookie nenhum. O Login Cidadão serve às outras
telas do portal (as do próprio devedor), não à certidão pública.

⚠️ **A CERTIDÃO É DO MOMENTO, E NÃO TEM VALIDADE.** O texto diz *"Certificamos
que, na data de 07/09/2026, não constam pendências"* — e só. Diferente do CHE e
do CRC mineiro, aqui não há prazo a vencer: o que existe é a DATA DA CONSULTA.
Por isso `negativos_em` é obrigatório na tela, e por isso o botão de consultar
agora existe: uma certidão de ontem não é prova de hoje.

⚠️ **A CONSULTA É POR RAIZ DE CNPJ.** O PDF imprime `CNPJ(raiz): 88.488.358` —
oito dígitos. Duas entidades do mesmo município com a mesma raiz recebem
exatamente a mesma certidão, então consultamos uma vez por raiz e distribuímos o
resultado. Entidade com raiz própria (o caso comum dos fundos municipais) é
consulta separada, como tem de ser.

⚠️ **ONDE GRAVA: `cadastro_negativo`, tabela própria — e a razão é um caso real.**
As colunas `itens_negativos`/`negativos_em`/`negativos_erro` de `cagec_situacao`
foram criadas prevendo esta fonte, e a premissa delas era que toda entidade
consultada teria linha no cadastro estadual. É falsa justamente onde dói: o
**Fundo Municipal de Saúde de Nova Palma não tem cadastro no CHE** e é ele quem
está inscrito no CADIN/RS (1 pendência, incluída em 28/08/2026 pela Secretaria
Estadual da Saúde). Na primeira versão deste coletor a certidão dele foi
descartada com um "sem linha do CHE" no log — a única pendência real da carteira
jogada fora por causa da tabela escolhida. Ver `add_cadastro_negativo.sql`.

Uso: DATABASE_URL_SYNC=... python -u ingestion/cadin_rs.py
     CADIN_RS_MUNICIPIOS='Nova Palma' python -u ingestion/cadin_rs.py   (dirigido)
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import unicodedata
from datetime import date
from io import BytesIO

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("cadin_rs")

BASE = "https://cadin.sefaz.rs.gov.br/api/Certidao"
# O Origin/Referer não são exigidos hoje; vão porque a chamada é de um SPA e um
# WAF que passe a exigi-los quebraria a coleta de um jeito difícil de ler (403
# sem corpo). Custo zero, e o User-Agent diz quem somos.
CABECALHOS = {
    "User-Agent": "Mozilla/5.0 (PACTHA/1.0 certidao publica CADIN-CFIL/SEFAZ-RS)",
    "Content-Type": "application/json",
    "Accept": "application/pdf,application/json;q=0.8,*/*;q=0.5",
    "Origin": "https://cadin.sefaz.rs.gov.br",
    "Referer": "https://cadin.sefaz.rs.gov.br/",
}
UF = "RS"
TIMEOUT = 60

# (codigo, rota, label). O `codigo` é a chave estável usada na tela, nos alertas
# e no `painel_alertas_enviados.ref` — nunca derive do rótulo, que a SEFAZ pode
# reescrever.
CERTIDOES = (
    ("CADIN-RS", "EmitirCertidao",
     "CADIN/RS — Cadastro Informativo de Pendências (Lei 10.697/1996)"),
    ("CFIL-RS", "EmitirCertidaoCfil",
     "CFIL/RS — Impedidos de Licitar e Contratar (Lei 11.389/1999)"),
)
GRUPO = "Cadastros negativos — Rio Grande do Sul"


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn")


def _texto_do_pdf(dados: bytes) -> str:
    from pypdf import PdfReader
    bruto = "\n".join((p.extract_text() or "") for p in PdfReader(BytesIO(dados)).pages)
    return re.sub(r"\s+", " ", bruto).strip()


def _classifica(texto: str) -> tuple[str, str]:
    """(tipo, situacao) a partir do texto da certidão.

    ⚠️ A ORDEM DAS DUAS CHECAGENS É O QUE IMPORTA, e "não constam" contém
    "constam": procurar a frase positiva primeiro classificaria toda certidão
    limpa como pendência. E o padrão é FECHADO de propósito — texto que não
    casar com nenhuma das duas formas vira `indeterminado`, nunca "nada consta".
    Afirmar ausência de pendência a partir de um texto que não entendemos é o
    erro que trava um convênio sem ninguém saber.

    ⚠️ **A CERTIDÃO COM PENDÊNCIA CONTA QUANTAS SÃO, e o número entra no meio da
    frase**: "consta **1 pendência** para a pessoa em epígrafe". A primeira
    versão deste padrão exigia `consta(m) pend...` colado e classificou como
    `indeterminado` justamente o único caso real que existia na carteira — o
    Fundo Municipal de Saúde de Nova Palma, inscrito em 28/08/2026. Padrão que
    só foi testado contra certidão limpa não foi testado."""
    t = _sem_acento(texto).lower()
    if re.search(r"n[ao]o\s+constam?\s+(\d+\s+)?pend", t):
        return "regular", "Nada consta"
    m = re.search(r"(?<!n[ao]o\s)\bconstam?\s+(?:as\s+seguintes\s+|(\d+)\s+)?pend", t)
    if m:
        qtd = m.group(1)
        if not qtd:
            return "pendente", "Consta pendência"
        return "pendente", (f"Consta {qtd} pendência" if qtd == "1"
                            else f"Constam {qtd} pendências")
    if "consta inscri" in t:
        return "pendente", "Consta inscrição"
    return "indeterminado", "Não foi possível ler a certidão"


# A certidão COM pendência traz, antes do texto, um quadro que diz o essencial:
# quem inscreveu, quando, quantas e com quem falar para sanar. Sem isso a tela
# informaria que o município está travado sem dizer por quem — e o gestor não
# tem a quem ligar. Os rótulos são os literais do PDF.
_RE_DETALHE = re.compile(
    r"Entidade\s+Administra[çc][ãa]o\s+Direta\s*/\s*Indireta\s+CNPJ\s+"
    r"Data\s+Inclus[ãa]o\s+CADIN\s+Quantidade\s+Pend[êe]ncias\s+"
    r"Contato\s+para\s+demais\s+Informa[çc][õo]es\s+"
    r"(?P<orgao>.+?)\s+(?P<cnpj>\d{14})\s+(?P<inclusao>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<qtd>\d+)\s+(?P<contato>.+?)\s+Certid[ãa]o", re.IGNORECASE)


def _detalhes_da_inscricao(texto: str) -> dict | None:
    """Quem inscreveu, quando e o contato — só existe na certidão com pendência."""
    m = _RE_DETALHE.search(texto)
    if not m:
        return None
    d = m.groupdict()
    # ⚠️ O CNPJ da linha do quadro NÃO entra aqui. No único caso medido ele é o
    # mesmo do ente consultado, e não dá para afirmar se a coluna é do devedor
    # ou de quem inscreveu — rotulá-lo de "CNPJ do órgão" seria inventar. O que
    # é inequívoco (órgão, data, quantidade, contato) basta para agir.
    return {
        "orgao": " ".join(d["orgao"].split()),
        "inscrito_em": d["inclusao"],
        "quantidade": int(d["qtd"]),
        "contato": " ".join(d["contato"].split()),
    }


def _data_da_certidao(texto: str) -> str | None:
    """A data que a PRÓPRIA certidão afirma ("na data de 07/09/2026")."""
    m = re.search(r"na\s+data\s+de\s*(\d{2}/\d{2}/\d{4})", _sem_acento(texto).lower())
    return m.group(1) if m else None


def emitir(client: httpx.Client, rota: str, cnpj14: str) -> bytes:
    r = client.post(f"{BASE}/{rota}", json={"Documento": cnpj14},
                    headers=CABECALHOS, timeout=TIMEOUT)
    r.raise_for_status()
    if not r.content[:4] == b"%PDF":
        # HTML/JSON no lugar do PDF é o sintoma de portal fora do ar ou de uma
        # mudança na rota — e precisa aparecer como erro, não como certidão
        # ilegível.
        raise RuntimeError(
            f"resposta nao e PDF ({r.headers.get('content-type', '?')}, "
            f"{len(r.content)} bytes)")
    return r.content


def _razao_social(texto: str) -> str | None:
    """O nome que a certidão imprime — a única identificação que teremos de uma
    entidade fora do cadastro estadual."""
    # ⚠️ "Certificamos" TEM de estar entre os terminadores. Nos dois layouts a
    # razão social é seguida de coisas diferentes — na certidão com pendência
    # vem "Porto Alegre, ...", na limpa vem "Certificamos que, na data de..." —
    # e um padrão que só conhecesse "Certidão" (que não casa "Certificamos")
    # devolveria o parágrafo inteiro como se fosse o nome do ente.
    m = re.search(
        r"Raz[ãa]o\s+Social:\s*(.+?)\s+"
        r"(?:Porto\s+Alegre|Certificamos|Certid[ãa]o|CNPJ|ESTADO\s+DO)",
        texto, re.IGNORECASE)
    return " ".join(m.group(1).split()) if m else None


def consultar_entidade(client: httpx.Client, cnpj14: str) -> tuple[list[dict], str | None]:
    """As duas certidões de um CNPJ. Devolve (itens, erro).

    Uma certidão que falha não derruba a outra: o CFIL indisponível não é
    motivo para esconder o CADIN que respondeu."""
    itens: list[dict] = []
    erros: list[str] = []
    for codigo, rota, label in CERTIDOES:
        try:
            pdf = emitir(client, rota, cnpj14)
            texto = _texto_do_pdf(pdf)
            tipo, situacao = _classifica(texto)
            erro_item = None
            if tipo == "indeterminado":
                erro_item = "certidao emitida, texto nao reconhecido"
                erros.append(f"{codigo}: {erro_item}")
            itens.append({
                "codigo": codigo,
                "grupo": GRUPO,
                "label": label,
                # `valor` é a data que a certidão afirma — o lugar que a coluna
                # "validade" ocupa nas outras esferas. Aqui não há validade: o
                # que existe é a data da consulta.
                "valor": _data_da_certidao(texto) or date.today().strftime("%d/%m/%Y"),
                "tipo": tipo,
                "status": situacao,
                "entidade": _razao_social(texto),
                # Quem inscreveu, quando e o contato — só vem quando HÁ
                # pendência, e é o que transforma "você está travado" em "ligue
                # para tal órgão".
                "detalhes": _detalhes_da_inscricao(texto),
                "erro": erro_item,
                "nota": ("Certidão do momento, sem prazo de validade: vale para a data "
                         "em que foi emitida."),
            })
        except Exception as e:
            erros.append(f"{codigo}: {type(e).__name__}: {str(e)[:120]}")
    return itens, ("; ".join(erros) if erros else None)


def _alvos(cur, pedidos: list[str] | None = None) -> list[dict]:
    """As MESMAS entidades do CHE — a lista vem de lá de propósito.

    Duas listas de alvos para o mesmo estado divergiriam no primeiro fundo novo,
    e aí a tela teria CHE de uma entidade e CADIN de outra.

    `pedidos` (ids ou nomes) recorta a lista. Vem como ARGUMENTO, e não só da
    env, porque o botão "consultar agora" da tela precisa emitir a certidão de
    UM município — a certidão não tem validade, então "agora" é a única forma
    de provar a situação de agora."""
    from ingestion.che_rs import _alvos as alvos_che
    alvos = alvos_che(cur)
    if pedidos is None:
        pedidos = [p.strip() for p in (os.getenv("CADIN_RS_MUNICIPIOS", "") or "").split(",")
                   if p.strip()]
    pedidos = [str(p).strip() for p in pedidos if str(p).strip()]
    if pedidos:
        ids = {p for p in pedidos if p.isdigit()}
        nomes = {_sem_acento(p).upper() for p in pedidos if not p.isdigit()}
        alvos = [a for a in alvos
                 if str(a["id"]) in ids or _sem_acento(a["nome"]).upper() in nomes]
        log.info("CADIN/CFIL-RS: consulta dirigida por CADIN_RS_MUNICIPIOS (%d alvo(s))",
                 len(alvos))
    return alvos


_SQL_NEGATIVO = """
INSERT INTO cadastro_negativo (municipio_id, cnpj, entidade, uf, fonte, tipo,
                               situacao, quantidade, detalhes, consultado_em,
                               erro, atualizado_em)
VALUES (%(mid)s, %(cnpj)s, %(entidade)s, %(uf)s, %(fonte)s, %(tipo)s,
        %(situacao)s, %(qtd)s, %(detalhes)s::jsonb, NOW(), %(erro)s, NOW())
ON CONFLICT (municipio_id, cnpj, fonte) DO UPDATE SET
    entidade = COALESCE(EXCLUDED.entidade, cadastro_negativo.entidade),
    uf = EXCLUDED.uf, tipo = EXCLUDED.tipo, situacao = EXCLUDED.situacao,
    quantidade = EXCLUDED.quantidade, detalhes = EXCLUDED.detalhes,
    consultado_em = EXCLUDED.consultado_em, erro = EXCLUDED.erro,
    atualizado_em = NOW()
"""


def _salvar(cur, alvo: dict, itens: list[dict], erro: str | None) -> int:
    """Uma linha por (município, CNPJ, cadastro) em `cadastro_negativo`.

    ⚠️ GRAVA MESMO QUEM NÃO TEM CADASTRO ESTADUAL, e é o ponto todo desta
    tabela: a entidade inscrita no CADIN pode não existir em `cagec_situacao` —
    o Fundo Municipal de Saúde de Nova Palma é exatamente isso, e é ele que tem
    a pendência. Enquanto a gravação era um UPDATE em `cagec_situacao`, essa
    certidão era descartada com a mensagem "sem linha do CHE".

    Também grava o `indeterminado`: certidão que saiu e cujo texto não
    reconhecemos é informação (a tela diz que não sabe), não ausência."""
    n = 0
    for i in itens:
        det = i.get("detalhes")
        cur.execute(_SQL_NEGATIVO, {
            "mid": alvo["id"], "cnpj": alvo["cnpj14"],
            "entidade": i.get("entidade") or alvo.get("nome"),
            "uf": alvo.get("uf") or UF, "fonte": i["codigo"],
            "tipo": i["tipo"], "situacao": i["status"],
            "qtd": (det or {}).get("quantidade"),
            "detalhes": json.dumps(det, ensure_ascii=False) if det else None,
            "erro": i.get("erro") or erro,
        })
        n += 1
    return n


def _log_ingest(cur, conn, status: str, inseridos: int, erro: str | None = None):
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES ('cadin_rs', %s, %s, %s, NOW())",
            (status, inseridos, erro))
        conn.commit()
    except Exception as e:
        log.warning("ingestion_log falhou: %s", str(e)[:120])


def ingest(dry: bool = False, municipios: list[str] | None = None) -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            alvos = _alvos(cur, municipios)
            if not alvos:
                # Fonte que NÃO SE APLICA a este tenant (nenhum município do RS)
                # é `success` com zero, igual ao CHE: `partial` faria o watchdog
                # cobrar para sempre uma fonte saudável.
                log.info("nenhum municipio do RS com CNPJ conhecido — "
                         "CADIN/CFIL nao se aplica a este tenant")
                if not dry:
                    _log_ingest(cur, conn, "success", 0)
                return 0

            log.info("CADIN/CFIL-RS: %d entidade(s) a consultar", len(alvos))
            gravados = falhas = 0
            # Uma certidão por RAIZ: a fonte responde por raiz, e emitir duas
            # vezes o mesmo PDF seria bater no portal do Estado à toa.
            cache: dict[str, tuple[list[dict], str | None]] = {}
            with httpx.Client(follow_redirects=True, verify=False) as client:
                for a in alvos:
                    raiz = a["cnpj14"][:8]
                    if raiz not in cache:
                        cache[raiz] = consultar_entidade(client, a["cnpj14"])
                    itens, erro = cache[raiz]
                    rotulo = f"{a['nome']}/{a['uf']} {a['cnpj14']}"
                    if not itens:
                        falhas += 1
                        log.warning("  %s: nenhuma certidao emitida — %s", rotulo, erro)
                        continue
                    resumo = ", ".join(f"{i['codigo']}={i['status']}" for i in itens)
                    pend = [i for i in itens if i["tipo"] == "pendente"]
                    (log.warning if pend else log.info)("  %s: %s", rotulo, resumo)
                    for i in pend:
                        d = i.get("detalhes") or {}
                        if d:
                            log.warning("      inscrito por %s em %s — contato: %s",
                                        d.get("orgao"), d.get("inscrito_em"), d.get("contato"))
                    if dry:
                        continue
                    gravados += _salvar(cur, a, itens, erro)

            if dry:
                return 0
            conn.commit()
            log.info("=== CADIN/CFIL-RS: %d certidao(oes) gravada(s), %d falha(s) ===",
                     gravados, falhas)
            _log_ingest(cur, conn, "success" if not falhas else "partial", gravados)
            return gravados
        except Exception as e:
            conn.rollback()
            log.error("CADIN/CFIL-RS falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, f"{type(e).__name__}: {str(e)[:300]}")
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ingest(dry="--dry" in sys.argv)
