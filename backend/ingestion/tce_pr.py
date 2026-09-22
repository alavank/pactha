"""
TCE-PR / PIT — o que o município do Paraná declarou ao Tribunal (SIM-AM).

O Portal Informação para Todos (pit.tce.pr.gov.br) publica, por exercício, um zip
com tudo o que as 399 prefeituras (e câmaras, autarquias, fundos) mandaram ao
SIM-AM: convênios, obras, licitações, contratos com aditivos, empenhos, receita.
É o equivalente paranaense do LicitaCon do RS — e mais, porque traz a DESPESA.

O dado que só esta fonte tem: a FONTE DE RECURSO de cada empenho. A prefeitura cria
uma fonte por convênio ("824 SECID Convênio 1748/2025 Pavimentação Pedras Irreg."),
e somar os empenhos por fonte diz quanto do dinheiro daquele convênio já foi
empenhado, liquidado e pago. Em Juranda (22/09/2026): R$ 40,2 mi empenhados em
"Transferências Voluntárias Públicas Estaduais" em 2026, R$ 6,0 mi liquidados.

    https://pit.tce.pr.gov.br/Arquivos/{ANO}_PIT_TodosArquivos.zip   (2013 em diante)

AS ARMADILHAS, todas medidas contra a fonte em 22/09/2026:

1. ⚠️ **O ZIP DE 2026 TEM 777 MB (o de 2017, 2 GB) E NÃO É BAIXADO.** O servidor
   (IIS) aceita `Range`, e o zip tem o índice no FIM: lê-se o índice e depois só
   os membros do município — 10 a 14 requisições e ~2-5 MB por ano em Juranda.
   `ZipRemoto` é um arquivo "seekable" sobre HTTP Range que o `zipfile` usa como
   se fosse local.

2. ⚠️ **O ARQUIVO PODE SER TROCADO NO MEIO DA LEITURA** (o do ano corrente é
   regerado toda semana). Um pedaço do zip velho com outro do novo dá lixo que o
   `zipfile` pode até aceitar. Por isso toda resposta 206 tem o ETag conferido
   contra o do HEAD, e divergência aborta o ANO (`ArquivoTrocado`) sem gravar —
   a próxima rodada lê inteiro. Não se usa `If-Range`: se o ETag mudasse, ele
   responderia 200 com os 777 MB.

3. ⚠️ **O CÓDIGO DO MUNICÍPIO TEM SEIS DÍGITOS** — o IBGE sem o verificador
   (Juranda = 411295). Nome de arquivo: `{ANO}_{IBGE6}_{Tema}.zip`, e dentro dele
   um XML por tabela (`{ANO}_{IBGE6}_Convenio.xml`...).

4. ⚠️ **ZIPS DE ANOS ANTIGOS SÃO CONGELADOS** (o de 2021 não muda desde 09/2023;
   o de 2013, desde 01/2020). O ETag de cada ano fica em `tce_pr_arquivos`, e ano
   com o mesmo ETag não é relido: a rodada normal é 14 HEADs e um ano de leitura.
   A consequência para a TELA: a situação de um convênio antigo é a de quando o
   arquivo daquele ano foi gerado.

5. ⚠️ **CADA ARQUIVO ANUAL SÓ TRAZ O QUE NASCEU NAQUELE ANO** e nada se repete
   entre anos (medido em convênio, obra, licitação e contrato, 2013-2026). Então
   (município, ano) é a fatia inteira: o coletor grava o ano e apaga do banco o
   que a fonte deixou de publicar naquele ano. EXCETO quando o arquivo vem vazio
   e o banco tem linhas — aí recusa apagar e a rodada é `partial` (arquivo vazio
   num dia de regeração não pode zerar o município).

6. ⚠️ **O ADITIVO MORA NO ANO DO ADITIVO**, não no do contrato (o arquivo de 2026
   aditiva contratos de 2023), e o mesmo número aparece em dois XML quando mexe em
   valor e prazo. Chave: (contrato, arquivo, ano, número).

7. ⚠️ **`EmpenhoPagamento.xml` VEM COM OS ATRIBUTOS DESLOCADOS**
   (`vlPagamentoBruto='BANCO'`, `cdIBGE='830.90'`). Não é lido: a nota de empenho
   já traz `vlLiquidacao` e `vlPagamento`, e são esses os somados.

8. ⚠️ **TEXTO COM ESPAÇO À DIREITA** (campos de largura fixa: `nmMunicipio`,
   `nmContratado`, `sgDocCredor='CNPJ        '`). Tudo passa por `strip()`.

9. ⚠️ **DADO COM ATRASO.** `ultimoEnvioSIMAMNesteExercicio` diz até que mês a
   entidade entregou (Juranda: 2026/06 em 22/09/2026). É o prazo do SIM-AM, não
   falha de coleta — vai para `tce_pr_arquivos.ultimo_envio` e a tela mostra.

10. ⚠️ **REFERÊNCIA DE CARACTERE INVÁLIDA NO XML** (`&#x1;`, texto colado de
    Word/PDF no objeto). O parser recusa o arquivo INTEIRO por um caractere, e o
    ano do município sumiria da tela. `xml_limpo` troca por espaço o que o XML
    1.0 proíbe, e só isso.

11. ⚠️ **A CODIFICAÇÃO MUDA DE ANO PARA ANO**: 2019-2021 são UTF-16 LE, os
    outros UTF-8 com BOM, e o arquivo vazio é `<root>SEM REGISTROS...`. Decodifica
    pelo BOM ANTES de qualquer limpeza.

Rodável por Scheduled Task no worker de tenant com município do PR, ou à mão:
    python -u ingestion/tce_pr.py                       # coleta de verdade
    python -u ingestion/tce_pr.py --dry --ibge 4112959  # sem banco: lê e resume
Envs: TCE_PR_FORCE=1 relê anos com ETag conhecido · TCE_PR_ANO_INICIAL (2013) ·
TCE_PR_ANOS_DESPESA (3: a despesa é agregada só nos últimos N exercícios).
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("tce_pr")

BASE = "https://pit.tce.pr.gov.br/Arquivos"
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0 dados abertos TCE-PR)"}
UF = "PR"
FONTE = "tce_pr"
TIMEOUT = 120
ANO_INICIAL = int(os.getenv("TCE_PR_ANO_INICIAL") or "2013")
ANOS_DESPESA = int(os.getenv("TCE_PR_ANOS_DESPESA") or "3")
FORCAR = (os.getenv("TCE_PR_FORCE") or "").strip() == "1"


class ArquivoTrocado(Exception):
    """O zip do ano mudou (ETag) no meio da leitura — armadilha 2."""


class ZipRemoto(io.RawIOBase):
    """Arquivo somente-leitura e "seekable" sobre HTTP Range (armadilha 1)."""

    def __init__(self, client: httpx.Client, url: str, etag: str, tamanho: int):
        self.client, self.url, self.etag, self.tamanho = client, url, etag, tamanho
        self.pos = 0
        self.requisicoes = 0
        self.baixado = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=io.SEEK_SET):
        if whence == io.SEEK_SET:
            self.pos = offset
        elif whence == io.SEEK_CUR:
            self.pos += offset
        else:
            self.pos = self.tamanho + offset
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.tamanho - self.pos
        if n <= 0 or self.pos >= self.tamanho:
            return b""
        fim = min(self.pos + n, self.tamanho) - 1
        r = self.client.get(self.url, headers={**UA, "Range": f"bytes={self.pos}-{fim}"},
                            timeout=TIMEOUT)
        if r.status_code != 206:
            raise httpx.HTTPStatusError(f"Range respondeu {r.status_code}",
                                        request=r.request, response=r)
        if (r.headers.get("etag") or "") != self.etag:
            raise ArquivoTrocado(f"{self.url}: ETag mudou durante a leitura")
        self.requisicoes += 1
        self.baixado += len(r.content)
        self.pos += len(r.content)
        return r.content

    def readinto(self, b):
        dado = self.read(len(b))
        b[:len(dado)] = dado
        return len(dado)


def url_do_ano(ano: int) -> str:
    return f"{BASE}/{ano}_PIT_TodosArquivos.zip"


def ibge6(ibge_code) -> str:
    """IBGE de 7 dígitos -> código do PIT, sem o verificador (armadilha 3)."""
    d = "".join(c for c in str(ibge_code or "") if c.isdigit())
    return d[:6] if len(d) == 7 else ""


# ---------------------------------------------------------------------------
# Conversores (ponto decimal, datas ISO, texto de largura fixa)
# ---------------------------------------------------------------------------
def _txt(v, limite: int | None = None):
    s = (v or "").strip()
    if not s:
        return None
    return s[:limite] if limite else s


def _dec(v):
    s = (v or "").strip()
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _int(v):
    s = (v or "").strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _data(v):
    s = (v or "").strip()
    if len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _momento(v):
    s = (v or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _raw(a: dict) -> str:
    return json.dumps({k: (v or "").strip() for k, v in a.items()}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Leitura do XML (atributos, um elemento por registro)
# ---------------------------------------------------------------------------
_REF_CARACTERE = re.compile(r"&#([xX][0-9a-fA-F]+|[0-9]+);")
_CONTROLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_DECLARACAO = re.compile(r"^\s*<\?xml[^>]*\?>")


def _ref_valida(m: re.Match) -> str:
    """Mantém a referência se o XML 1.0 aceita o caractere; senão, um espaço."""
    corpo = m.group(1)
    try:
        cp = int(corpo[1:], 16) if corpo[:1] in ("x", "X") else int(corpo)
    except ValueError:
        return " "
    ok = (cp in (0x9, 0xA, 0xD) or 0x20 <= cp <= 0xD7FF
          or 0xE000 <= cp <= 0xFFFD or 0x10000 <= cp <= 0x10FFFF)
    return m.group(0) if ok else " "


def _texto(dado: bytes) -> str:
    """Decodifica pelo BOM (armadilha 11): 2019-2021 vêm em UTF-16 LE, os outros
    anos em UTF-8 com BOM. Sem BOM, UTF-8."""
    if dado[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return dado.decode("utf-16")
    return dado.decode("utf-8-sig")


def xml_limpo(dado: bytes) -> bytes:
    """O XML em UTF-8, sem o que o XML 1.0 proíbe (armadilhas 10 e 11).

    O SIM-AM grava texto colado de Word/PDF com caractere de controle, e o TCE o
    escreve como `&#x1;` — o parser recusa o ARQUIVO INTEIRO por um caractere
    num objeto de licitação. A limpeza é feita no TEXTO, nunca nos bytes: em
    UTF-16 metade dos bytes é `\\x00`, e limpar bytes destruía o arquivo (foi o
    primeiro ensaio deste coletor). A declaração sai porque, reencodado em
    UTF-8, um `encoding="utf-16"` nela mentiria."""
    texto = _DECLARACAO.sub("", _texto(dado), count=1)
    texto = _CONTROLE.sub(" ", _REF_CARACTERE.sub(_ref_valida, texto))
    return texto.encode("utf-8")


def registros(zip_tema: bytes, nome_xml: str, tag: str) -> list[dict] | None:
    """Os registros `<tag .../>` de um XML dentro do zip do tema.

    `None` = o XML não está no zip (isso NÃO é "zero registros")."""
    with zipfile.ZipFile(io.BytesIO(zip_tema)) as z:
        if nome_xml not in z.namelist():
            return None
        dado = xml_limpo(z.read(nome_xml))
    saida = []
    for _ev, el in ET.iterparse(io.BytesIO(dado), events=("end",)):
        if el.tag == tag:
            saida.append(dict(el.attrib))
            el.clear()
    return saida


# ---------------------------------------------------------------------------
# Linhas das tabelas
# ---------------------------------------------------------------------------
def linha_convenio(mid: int, ano: int, a: dict) -> dict:
    return {
        "mid": mid, "ano": _int(a.get("nrAnoConvenio")) or ano,
        "id": _int(a.get("idConvenio")),
        "pessoa": _int(a.get("idPessoa")), "entidade": _txt(a.get("nmEntidade")),
        "nr": _txt(a.get("nrConvenio"), 40), "termo": _txt(a.get("nrTermo"), 40),
        "celebracao": _data(a.get("dtCelebracao")),
        "situacao": _txt(a.get("dsTipoSituacaoConvenio")),
        "esfera": _txt(a.get("dsConvenioEsfera")),
        "valor": _dec(a.get("vlConvenio")),
        "proprio": _dec(a.get("vlRecursoProprio")),
        "ini": _data(a.get("dtInicioVigencia")), "fim": _data(a.get("dtFimVigencia")),
        "objeto": _txt(a.get("dsObjeto")),
        "fonte": _txt(a.get("dsFonteReceita")),
        "plano": _txt(a.get("dsPlanoPadraoFonte")),
        "envio": _momento(a.get("dtEnvio")),
        "raw": _raw(a),
    }


def linha_obra(mid: int, ano: int, a: dict, bens: list[dict]) -> dict:
    return {
        "mid": mid, "ano": _int(a.get("nrAnoIntervencao")) or ano,
        "id": _int(a.get("idIntervencao")),
        "pessoa": _int(a.get("idPessoa")), "entidade": _txt(a.get("nmEntidade")),
        "cd": _txt(a.get("cdIntervencao"), 20),
        "nome": _txt(a.get("nmIntervencao")),
        "valor": _dec(a.get("vlIntervencao")),
        "inicio": _data(a.get("dtInicio")),
        "prazo": _int(a.get("nrPrazoExecucao")),
        "situacao": _txt(a.get("dsSituacao")),
        "regime": _txt(a.get("dsTipoRegimeIntervencao")),
        "medicao": _data(a.get("dtUltimaMedicao")),
        "bens": json.dumps([{
            "bem": _txt(b.get("dsBem")),
            "logradouro": _txt(b.get("nmLogradouro")),
            "coordenada": _txt(b.get("dsCoordenadaGeografica")),
        } for b in bens], ensure_ascii=False),
        "raw": _raw(a),
    }


def linha_licitacao(mid: int, ano: int, a: dict) -> dict:
    return {
        "mid": mid, "ano": _int(a.get("nrAnoLicitacao")) or ano,
        "id": _int(a.get("idLicitacao")),
        "pessoa": _int(a.get("idPessoa")), "entidade": _txt(a.get("nmEntidade")),
        "modalidade": _txt(a.get("dsModalidadeLicitacao")),
        "nr": _txt(a.get("nrLicitacao"), 40),
        "abertura": _data(a.get("dtAbertura")),
        "valor": _dec(a.get("vlLicitacao")),
        "situacao": _txt(a.get("dsTipoSituacaoLicitacao")),
        "classificacao": _txt(a.get("dsClassificacaoObjetoLicitacao")),
        "objeto": _txt(a.get("dsObjeto")),
        "raw": _raw(a),
    }


def linha_contrato(mid: int, ano: int, a: dict) -> dict:
    return {
        "mid": mid, "ano": _int(a.get("nrAnoContrato")) or ano,
        "id": _int(a.get("idContrato")),
        "pessoa": _int(a.get("idPessoa")), "entidade": _txt(a.get("nmEntidade")),
        "nr": _txt(a.get("nrContrato"), 40),
        "ato": _txt(a.get("dsTipoAtoContrato")),
        "contratado": _txt(a.get("nmContratado")),
        "doc": _txt(a.get("nrDocContratado"), 20),
        "valor": _dec(a.get("vlContrato")),
        "assinatura": _data(a.get("dtAssinatura")),
        "inicio": _data(a.get("dtInicio")), "fim": _data(a.get("dtFim")),
        "objeto": _txt(a.get("dsObjeto")),
        "raw": _raw(a),
    }


# XML de aditivo -> rótulo curto da coluna `arquivo` (armadilha 6).
ADITIVOS = {"ContratoAditivo": "valor", "ContratoAditivoPrazo": "prazo",
            "ContratoAditivoRescisao": "rescisao"}


def linha_aditivo(mid: int, ano: int, arquivo: str, a: dict) -> dict:
    # O id do contrato vem como `idcontrato` em dois XML e `idContrato` no de
    # rescisão — a fonte não padroniza a caixa.
    idc = a.get("idcontrato") or a.get("idContrato")
    return {
        "mid": mid, "ano": ano, "contrato": _int(idc), "arquivo": arquivo,
        "nr": _txt(a.get("nrAditivoContrato"), 20) or "?",
        "ano_ad": _int(a.get("nrAnoAditivoContrato")) or ano,
        "tipo": _txt(a.get("dsTipoAditivoContrato")),
        "operacao": _txt(a.get("dsTipoOperacaoAditivoContrato")),
        "vl": _dec(a.get("vlAditivo")),
        "vl_atual": _dec(a.get("vlAtualizadoContrato")),
        "fim": _data(a.get("dtFim")) if arquivo == "prazo" else None,
        "dt": _data(a.get("dtAditivoContrato")),
        "motivo": _txt(a.get("dsMotivoAditivoPrazoContrato")
                       or a.get("dsMotivoAditivoRescisaoContrato")
                       or a.get("dsMotivo")),
        "raw": _raw(a),
    }


def agrega_despesa(mid: int, ano: int, empenhos: list[dict]) -> list[dict]:
    """Soma os empenhos do exercício por (entidade, fonte de recurso)."""
    grupos: dict[tuple, dict] = {}
    for e in empenhos:
        pessoa = _int(e.get("idPessoa"))
        cd = _txt(e.get("cdFonteReceita"), 20) or "?"
        ds = _txt(e.get("dsFonteReceita")) or "(sem descrição)"
        g = grupos.setdefault((pessoa, cd, ds), {
            "mid": mid, "ano": ano, "pessoa": pessoa,
            "entidade": _txt(e.get("nmEntidade")), "cd": cd, "ds": ds,
            "plano": _txt(e.get("dsFontePlanoPadraoFonte")),
            "qt": 0, "emp": Decimal(0), "liq": Decimal(0), "pag": Decimal(0),
        })
        g["qt"] += 1
        g["emp"] += _dec(e.get("vlEmpenho")) or 0
        g["liq"] += _dec(e.get("vlLiquidacao")) or 0
        g["pag"] += _dec(e.get("vlPagamento")) or 0
    return [g for g in grupos.values() if g["pessoa"] is not None]


def referencias(regs: list[dict]) -> tuple[str | None, str | None]:
    """(DataReferencia, último envio ao SIM-AM) — armadilha 9."""
    ref = envio = None
    for a in regs:
        r = _txt(a.get("DataReferencia"), 10)
        u = _txt(a.get("ultimoEnvioSIMAMNesteExercicio"), 10)
        if r and (ref is None or r > ref):
            ref = r
        if u and (envio is None or u > envio):
            envio = u
    return ref, envio


# ---------------------------------------------------------------------------
# Leitura de um ano de um município
# ---------------------------------------------------------------------------
TEMAS = ("Convenio", "Obra", "Licitacao", "Contrato", "Despesa")


def ler_ano(z: zipfile.ZipFile, ano: int, ib6: str, mid: int,
            com_despesa: bool) -> dict:
    """Tudo o que interessa de UM município em UM ano, já em linhas de tabela.

    Tema cujo zip não existe fica em `faltando` e NÃO vira lista vazia: ausência
    de arquivo não autoriza apagar nada do banco."""
    nomes = set(z.namelist())
    out: dict = {"faltando": [], "refs": []}

    def tema(nome: str) -> bytes | None:
        membro = f"{ano}_{ib6}_{nome}.zip"
        if membro not in nomes:
            out["faltando"].append(nome)
            return None
        return z.read(membro)

    def xml(dado: bytes, tabela: str, tag: str | None = None) -> list[dict] | None:
        regs = registros(dado, f"{ano}_{ib6}_{tabela}.xml", tag or tabela)
        if regs is None:
            out["faltando"].append(tabela)
        else:
            out["refs"].extend(regs[:1])
        return regs

    d = tema("Convenio")
    if d is not None:
        regs = xml(d, "Convenio")
        if regs is not None:
            out["convenios"] = [linha_convenio(mid, ano, a) for a in regs]

    d = tema("Obra")
    if d is not None:
        obras = xml(d, "Intervencao")
        bens = registros(d, f"{ano}_{ib6}_IntervencaoBem.xml", "IntervencaoBem") or []
        if obras is not None:
            por_obra: dict = {}
            for b in bens:
                por_obra.setdefault(b.get("idIntervencao"), []).append(b)
            out["obras"] = [linha_obra(mid, ano, a, por_obra.get(a.get("idIntervencao"), []))
                            for a in obras]

    d = tema("Licitacao")
    if d is not None:
        regs = xml(d, "Licitacao")
        if regs is not None:
            out["licitacoes"] = [linha_licitacao(mid, ano, a) for a in regs]

    d = tema("Contrato")
    if d is not None:
        regs = xml(d, "Contrato")
        if regs is not None:
            out["contratos"] = [linha_contrato(mid, ano, a) for a in regs]
        aditivos = []
        completos = True
        for tabela, rotulo in ADITIVOS.items():
            regs = registros(d, f"{ano}_{ib6}_{tabela}.xml", tabela)
            if regs is None:
                completos = False
                out["faltando"].append(tabela)
                continue
            aditivos += [linha_aditivo(mid, ano, rotulo, a) for a in regs]
        if completos:
            out["aditivos"] = [x for x in aditivos if x["contrato"] is not None]

    if com_despesa:
        d = tema("Despesa")
        if d is not None:
            regs = xml(d, "Empenho")
            if regs is not None:
                out["despesa"] = agrega_despesa(mid, ano, regs)
    return out


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------
_SQL = {
    "convenios": ("tce_pr_convenios", "id_convenio", """
        INSERT INTO tce_pr_convenios (municipio_id, id_convenio, ano, id_pessoa,
            nm_entidade, nr_convenio, nr_termo, dt_celebracao, situacao, esfera,
            vl_convenio, vl_recurso_proprio, dt_inicio_vigencia, dt_fim_vigencia,
            ds_objeto, ds_fonte_receita, ds_plano_padrao_fonte, dt_envio, raw_data,
            atualizado_em)
        VALUES (%(mid)s, %(id)s, %(ano)s, %(pessoa)s, %(entidade)s, %(nr)s, %(termo)s,
            %(celebracao)s, %(situacao)s, %(esfera)s, %(valor)s, %(proprio)s, %(ini)s,
            %(fim)s, %(objeto)s, %(fonte)s, %(plano)s, %(envio)s, %(raw)s::jsonb, NOW())
        ON CONFLICT (id_convenio) DO UPDATE SET
            municipio_id = EXCLUDED.municipio_id, ano = EXCLUDED.ano,
            id_pessoa = EXCLUDED.id_pessoa, nm_entidade = EXCLUDED.nm_entidade,
            nr_convenio = EXCLUDED.nr_convenio, nr_termo = EXCLUDED.nr_termo,
            dt_celebracao = EXCLUDED.dt_celebracao, situacao = EXCLUDED.situacao,
            esfera = EXCLUDED.esfera, vl_convenio = EXCLUDED.vl_convenio,
            vl_recurso_proprio = EXCLUDED.vl_recurso_proprio,
            dt_inicio_vigencia = EXCLUDED.dt_inicio_vigencia,
            dt_fim_vigencia = EXCLUDED.dt_fim_vigencia, ds_objeto = EXCLUDED.ds_objeto,
            ds_fonte_receita = EXCLUDED.ds_fonte_receita,
            ds_plano_padrao_fonte = EXCLUDED.ds_plano_padrao_fonte,
            dt_envio = EXCLUDED.dt_envio, raw_data = EXCLUDED.raw_data,
            atualizado_em = NOW()
    """),
    "obras": ("tce_pr_obras", "id_intervencao", """
        INSERT INTO tce_pr_obras (municipio_id, id_intervencao, ano, id_pessoa,
            nm_entidade, cd_intervencao, nm_intervencao, vl_intervencao, dt_inicio,
            prazo_dias, situacao, regime, dt_ultima_medicao, bens, raw_data,
            atualizado_em)
        VALUES (%(mid)s, %(id)s, %(ano)s, %(pessoa)s, %(entidade)s, %(cd)s, %(nome)s,
            %(valor)s, %(inicio)s, %(prazo)s, %(situacao)s, %(regime)s, %(medicao)s,
            %(bens)s::jsonb, %(raw)s::jsonb, NOW())
        ON CONFLICT (id_intervencao) DO UPDATE SET
            municipio_id = EXCLUDED.municipio_id, ano = EXCLUDED.ano,
            id_pessoa = EXCLUDED.id_pessoa, nm_entidade = EXCLUDED.nm_entidade,
            cd_intervencao = EXCLUDED.cd_intervencao,
            nm_intervencao = EXCLUDED.nm_intervencao,
            vl_intervencao = EXCLUDED.vl_intervencao, dt_inicio = EXCLUDED.dt_inicio,
            prazo_dias = EXCLUDED.prazo_dias, situacao = EXCLUDED.situacao,
            regime = EXCLUDED.regime, dt_ultima_medicao = EXCLUDED.dt_ultima_medicao,
            bens = EXCLUDED.bens, raw_data = EXCLUDED.raw_data, atualizado_em = NOW()
    """),
    "licitacoes": ("tce_pr_licitacoes", "id_licitacao", """
        INSERT INTO tce_pr_licitacoes (municipio_id, id_licitacao, ano, id_pessoa,
            nm_entidade, modalidade, nr_licitacao, dt_abertura, vl_licitacao,
            situacao, classificacao, ds_objeto, raw_data, atualizado_em)
        VALUES (%(mid)s, %(id)s, %(ano)s, %(pessoa)s, %(entidade)s, %(modalidade)s,
            %(nr)s, %(abertura)s, %(valor)s, %(situacao)s, %(classificacao)s,
            %(objeto)s, %(raw)s::jsonb, NOW())
        ON CONFLICT (id_licitacao) DO UPDATE SET
            municipio_id = EXCLUDED.municipio_id, ano = EXCLUDED.ano,
            id_pessoa = EXCLUDED.id_pessoa, nm_entidade = EXCLUDED.nm_entidade,
            modalidade = EXCLUDED.modalidade, nr_licitacao = EXCLUDED.nr_licitacao,
            dt_abertura = EXCLUDED.dt_abertura, vl_licitacao = EXCLUDED.vl_licitacao,
            situacao = EXCLUDED.situacao, classificacao = EXCLUDED.classificacao,
            ds_objeto = EXCLUDED.ds_objeto, raw_data = EXCLUDED.raw_data,
            atualizado_em = NOW()
    """),
    "contratos": ("tce_pr_contratos", "id_contrato", """
        INSERT INTO tce_pr_contratos (municipio_id, id_contrato, ano, id_pessoa,
            nm_entidade, nr_contrato, tipo_ato, nm_contratado, nr_doc_contratado,
            vl_contrato, dt_assinatura, dt_inicio, dt_fim, ds_objeto, raw_data,
            atualizado_em)
        VALUES (%(mid)s, %(id)s, %(ano)s, %(pessoa)s, %(entidade)s, %(nr)s, %(ato)s,
            %(contratado)s, %(doc)s, %(valor)s, %(assinatura)s, %(inicio)s, %(fim)s,
            %(objeto)s, %(raw)s::jsonb, NOW())
        ON CONFLICT (id_contrato) DO UPDATE SET
            municipio_id = EXCLUDED.municipio_id, ano = EXCLUDED.ano,
            id_pessoa = EXCLUDED.id_pessoa, nm_entidade = EXCLUDED.nm_entidade,
            nr_contrato = EXCLUDED.nr_contrato, tipo_ato = EXCLUDED.tipo_ato,
            nm_contratado = EXCLUDED.nm_contratado,
            nr_doc_contratado = EXCLUDED.nr_doc_contratado,
            vl_contrato = EXCLUDED.vl_contrato, dt_assinatura = EXCLUDED.dt_assinatura,
            dt_inicio = EXCLUDED.dt_inicio, dt_fim = EXCLUDED.dt_fim,
            ds_objeto = EXCLUDED.ds_objeto, raw_data = EXCLUDED.raw_data,
            atualizado_em = NOW()
    """),
}

_SQL_ADITIVO = """
    INSERT INTO tce_pr_contratos_aditivos (municipio_id, ano, id_contrato, arquivo,
        nr_aditivo, ano_aditivo, tipo, operacao, vl_aditivo, vl_atualizado, dt_fim,
        dt_aditivo, motivo, raw_data, atualizado_em)
    VALUES (%(mid)s, %(ano)s, %(contrato)s, %(arquivo)s, %(nr)s, %(ano_ad)s, %(tipo)s,
        %(operacao)s, %(vl)s, %(vl_atual)s, %(fim)s, %(dt)s, %(motivo)s,
        %(raw)s::jsonb, NOW())
    ON CONFLICT (id_contrato, arquivo, ano_aditivo, nr_aditivo) DO UPDATE SET
        municipio_id = EXCLUDED.municipio_id, ano = EXCLUDED.ano,
        tipo = EXCLUDED.tipo, operacao = EXCLUDED.operacao,
        vl_aditivo = EXCLUDED.vl_aditivo, vl_atualizado = EXCLUDED.vl_atualizado,
        dt_fim = EXCLUDED.dt_fim, dt_aditivo = EXCLUDED.dt_aditivo,
        motivo = EXCLUDED.motivo, raw_data = EXCLUDED.raw_data, atualizado_em = NOW()
"""

_SQL_DESPESA = """
    INSERT INTO tce_pr_despesa_fonte (municipio_id, ano, id_pessoa, nm_entidade,
        cd_fonte, ds_fonte, ds_plano_padrao, qt_empenhos, vl_empenhado,
        vl_liquidado, vl_pago, atualizado_em)
    VALUES (%(mid)s, %(ano)s, %(pessoa)s, %(entidade)s, %(cd)s, %(ds)s, %(plano)s,
        %(qt)s, %(emp)s, %(liq)s, %(pag)s, NOW())
"""


def _substitui_ano(cur, chave_lote: str, mid: int, ano: int,
                   linhas: list[dict]) -> tuple[int, bool]:
    """Grava a fatia (município, ano) de uma tabela e apaga o que saiu da fonte.

    Devolve (gravadas, recusou). `recusou` = arquivo vazio com banco cheio
    (armadilha 5): não apaga nada e a rodada vira `partial`."""
    tabela, col_id, sql = _SQL[chave_lote]
    if not linhas:
        cur.execute(f"SELECT count(*) FROM {tabela} WHERE municipio_id = %s AND ano = %s",
                    (mid, ano))
        return 0, cur.fetchone()[0] > 0
    validas = [x for x in linhas if x["id"] is not None]
    for x in validas:
        cur.execute(sql, x)
    cur.execute(f"DELETE FROM {tabela} WHERE municipio_id = %s AND ano = %s "
                f"AND NOT ({col_id} = ANY(%s))",
                (mid, ano, [x["id"] for x in validas]))
    return len(validas), False


def _grava_lote(cur, mid: int, ano: int, lido: dict) -> tuple[dict, list[str]]:
    contagens, recusas = {}, []
    for chave in ("convenios", "obras", "licitacoes", "contratos"):
        if chave not in lido:
            continue
        n, recusou = _substitui_ano(cur, chave, mid, ano, lido[chave])
        contagens[chave] = n
        if recusou:
            recusas.append(chave)
    for chave, tabela, sql in (("aditivos", "tce_pr_contratos_aditivos", _SQL_ADITIVO),
                               ("despesa", "tce_pr_despesa_fonte", _SQL_DESPESA)):
        if chave not in lido:
            continue
        linhas = lido[chave]
        if not linhas:
            cur.execute(f"SELECT count(*) FROM {tabela} "
                        "WHERE municipio_id = %s AND ano = %s", (mid, ano))
            if cur.fetchone()[0] > 0:
                recusas.append(chave)
                continue
        cur.execute(f"DELETE FROM {tabela} WHERE municipio_id = %s AND ano = %s",
                    (mid, ano))
        for x in linhas:
            cur.execute(sql, x)
        contagens[chave] = len(linhas)
    return contagens, recusas


def _alvos(cur) -> list[dict]:
    cur.execute("""
        SELECT id, nome, ibge_code FROM municipios
         WHERE active AND upper(coalesce(uf, '')) = %s
         ORDER BY nome
    """, (UF,))
    return [{"id": r[0], "nome": r[1], "ib6": ibge6(r[2])} for r in cur.fetchall()]


def _etags(cur) -> dict:
    cur.execute("SELECT municipio_id, ano, etag FROM tce_pr_arquivos")
    return {(r[0], r[1]): r[2] for r in cur.fetchall()}


def _marca_arquivo(cur, mid: int, ano: int, etag: str, modificado: str | None,
                   lido: dict, contagens: dict) -> None:
    ref, envio = referencias(lido.get("refs") or [])
    cur.execute("""
        INSERT INTO tce_pr_arquivos (municipio_id, ano, etag, last_modified,
            referencia, ultimo_envio, contagens, atualizado_em)
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, NOW())
        ON CONFLICT (municipio_id, ano) DO UPDATE SET
            etag = EXCLUDED.etag, last_modified = EXCLUDED.last_modified,
            referencia = coalesce(EXCLUDED.referencia, tce_pr_arquivos.referencia),
            ultimo_envio = coalesce(EXCLUDED.ultimo_envio, tce_pr_arquivos.ultimo_envio),
            contagens = EXCLUDED.contagens, atualizado_em = NOW()
    """, (mid, ano, etag, modificado, ref, envio, json.dumps(contagens)))


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


# ---------------------------------------------------------------------------
# Rodada
# ---------------------------------------------------------------------------
def _anos() -> list[int]:
    return list(range(ANO_INICIAL, date.today().year + 1))


def _cabecalho(client: httpx.Client, ano: int) -> tuple[str, int, str | None] | None:
    """(etag, tamanho, last-modified) do zip do ano; None se o ano não existe."""
    r = client.head(url_do_ano(ano), headers=UA, timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    if "bytes" not in (r.headers.get("accept-ranges") or ""):
        raise RuntimeError(f"{url_do_ano(ano)} deixou de aceitar Range — baixar "
                           "o zip inteiro NÃO é o plano (centenas de MB)")
    return (r.headers.get("etag") or "", int(r.headers["content-length"]),
            r.headers.get("last-modified"))


def ingest(dry: bool = False) -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect

    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            alvos = [a for a in _alvos(cur) if a["ib6"]]
            if not alvos:
                log.info("nenhum município do PR — TCE-PR não se aplica a este tenant")
                if not dry:
                    _log_ingest(cur, conn, "success", 0)
                return 0
            conhecidos = _etags(cur)
            gravadas, notas, parcial = 0, [], False
            ano_atual = date.today().year
            with httpx.Client(follow_redirects=True) as client:
                for ano in _anos():
                    try:
                        cab = _cabecalho(client, ano)
                    except Exception as e:
                        parcial = True
                        notas.append(f"{ano}: HEAD falhou ({type(e).__name__})")
                        log.warning("  %s: HEAD falhou: %s", ano, str(e)[:150])
                        continue
                    if cab is None:
                        log.info("  %s: arquivo ainda não publicado", ano)
                        continue
                    etag, tamanho, modificado = cab
                    pendentes = [a for a in alvos
                                 if FORCAR or conhecidos.get((a["id"], ano)) != etag]
                    if not pendentes:
                        log.info("  %s: sem novidade (ETag %s)", ano, etag)
                        continue
                    remoto = ZipRemoto(client, url_do_ano(ano), etag, tamanho)
                    try:
                        z = zipfile.ZipFile(io.BufferedReader(remoto, buffer_size=1 << 16))
                        for a in pendentes:
                            com_despesa = ano > ano_atual - ANOS_DESPESA
                            lido = ler_ano(z, ano, a["ib6"], a["id"], com_despesa)
                            if lido["faltando"]:
                                parcial = True
                                notas.append(f"{a['nome']} {ano}: sem "
                                             + ", ".join(lido["faltando"][:4]))
                            if dry:
                                log.info("  %s %s: %s", a["nome"], ano, {
                                    k: len(v) for k, v in lido.items()
                                    if k not in ("faltando", "refs")})
                                continue
                            contagens, recusas = _grava_lote(cur, a["id"], ano, lido)
                            if recusas:
                                parcial = True
                                notas.append(f"{a['nome']} {ano}: arquivo vazio com "
                                             f"banco cheio em {', '.join(recusas)} — "
                                             "nada apagado")
                            # Selo só quando o ano entrou inteiro: com tema faltando
                            # ou recusado, a próxima rodada tenta de novo.
                            if not lido["faltando"] and not recusas:
                                _marca_arquivo(cur, a["id"], ano, etag, modificado,
                                               lido, contagens)
                            conn.commit()
                            gravadas += sum(contagens.values())
                            log.info("  %s %s: %s", a["nome"], ano, contagens)
                        log.info("  %s: %d requisição(ões), %.1f MB lidos de %.0f MB",
                                 ano, remoto.requisicoes, remoto.baixado / 1e6,
                                 tamanho / 1e6)
                    except ArquivoTrocado as e:
                        conn.rollback()
                        parcial = True
                        notas.append(f"{ano}: arquivo regerado durante a leitura")
                        log.warning("  %s", e)
                    except Exception as e:
                        conn.rollback()
                        parcial = True
                        notas.append(f"{ano}: {type(e).__name__}: {str(e)[:80]}")
                        log.warning("  %s: %s: %s", ano, type(e).__name__, str(e)[:200])
            if dry:
                return 0
            status = "partial" if parcial else "success"
            nota = " | ".join(notas)[:400] or None
            log.info("=== TCE-PR: %d linha(s) gravada(s), status=%s ===", gravadas, status)
            _log_ingest(cur, conn, status, gravadas, nota)
            return gravadas
        except Exception as e:
            conn.rollback()
            log.error("TCE-PR falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


def ensaio_sem_banco(ibge: str, anos: list[int]) -> None:
    """`--dry --ibge`: lê e resume sem banco — para conferir a fonte à mão."""
    ib6 = ibge6(ibge)
    with httpx.Client(follow_redirects=True) as client:
        for ano in anos:
            cab = _cabecalho(client, ano)
            if cab is None:
                log.info("%s: não publicado", ano)
                continue
            etag, tamanho, _ = cab
            remoto = ZipRemoto(client, url_do_ano(ano), etag, tamanho)
            z = zipfile.ZipFile(io.BufferedReader(remoto, buffer_size=1 << 16))
            lido = ler_ano(z, ano, ib6, 0, ano > date.today().year - ANOS_DESPESA)
            ref, envio = referencias(lido["refs"])
            log.info("%s: %s | referência %s, último envio %s | faltando %s | "
                     "%d req, %.1f MB", ano,
                     {k: len(v) for k, v in lido.items() if k not in ("faltando", "refs")},
                     ref, envio, lido["faltando"], remoto.requisicoes,
                     remoto.baixado / 1e6)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    p = argparse.ArgumentParser()
    p.add_argument("--dry", action="store_true")
    p.add_argument("--ibge", help="com --dry: lê só este município, sem banco")
    p.add_argument("--anos", help="com --ibge: lista separada por vírgula")
    a = p.parse_args()
    if a.dry and a.ibge:
        anos = [int(x) for x in a.anos.split(",")] if a.anos else _anos()
        ensaio_sem_banco(a.ibge, anos)
    else:
        ingest(dry=a.dry)
