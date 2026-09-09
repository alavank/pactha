"""CADASTROS NEGATIVOS — CADIN e CFIL, a quarta coluna da regularidade.

As outras três respondem "o município está em dia?": o CAUC (União), o cadastro
estadual de convenentes (CAGEC em Minas, CHE no RS) e o Tesouro (contas e CAPAG).
Esta responde outra pergunta, e a resposta trava sozinha: **existe pendência
INSCRITA contra o ente?**

    CADIN-MG  vem do CRC do CAGEC (uma linha entre as ~27) — `cagec_scraper.py`
    CADIN-RS  certidão pública da CAGE/SEFAZ-RS ------------- `cadin_rs.py`
    CFIL-RS   idem, fornecedores impedidos de licitar ------- `cadin_rs.py`

⚠️ **A LINHA MAIS IMPORTANTE PODE NÃO SER A DA PREFEITURA.** Cada entidade tem
inscrição própria, e a única pendência real da carteira em 07/09/2026 era do
**Fundo Municipal de Saúde de Nova Palma** — que nem cadastro no CHE tem. Por
isso a fonte é `cadastro_negativo` (tabela própria, uma linha por entidade e por
cadastro) e não uma coluna de `cagec_situacao`.

⚠️ **`tipo = 'indeterminado'` NÃO É "nada consta".** É a certidão que saiu e cujo
texto não reconhecemos. A tela precisa dizer que não sabe — pintar de verde o que
não foi lido é o erro que este módulo inteiro existe para evitar.

⚠️ **NÃO HÁ VALIDADE.** A certidão afirma a situação "na data de <dia>", e só.
`consultado_em` é obrigatório na tela, e é por isso que existe o botão de
consultar agora: uma certidão de ontem não é prova de hoje.

Mesma tela do CAUC (`cauc`) e mesma chave: as quatro colunas da regularidade
respondem a uma pergunta só, e meia tela não é uma concessão que o administrador
queira fazer.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services import authz
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.registro_rotas import exige

router = APIRouter(prefix="/api/cadastros-negativos", tags=["regularidade"])

# O que cada cadastro é, em uma frase, e o que a inscrição trava. Fica no
# servidor porque a tela desenha os três com o mesmo componente e o texto muda
# por estado — o mesmo motivo de `services/cadastro_estadual.py` existir.
CATALOGO = {
    "CADIN-MG": {
        "sigla": "CADIN-MG",
        "nome": "Cadastro Informativo de Inadimplência do Estado de Minas Gerais",
        "uf": "MG",
        "orgao": "SEF-MG",
        "trava": "impede convênio e liberação de parcela com o Estado",
        # Procedência honesta: em Minas não há consulta pública automatizável (o
        # portal da Fazenda é formulário com CAPTCHA). Quem entrega é o CRC.
        "origem": "Lido do CRC do CAGEC — o certificado traz a linha do CADIN-MG.",
    },
    "CADIN-RS": {
        "sigla": "CADIN/RS",
        "nome": "Cadastro Informativo das Pendências perante Órgãos e Entidades "
                "da Administração Pública Estadual",
        "uf": "RS",
        "orgao": "CAGE/SEFAZ-RS",
        "lei": "Lei estadual 10.697/1996",
        "trava": "impede receber transferência voluntária do Estado",
        "origem": "Certidão pública emitida em cadin.sefaz.rs.gov.br.",
    },
    "CFIL-RS": {
        "sigla": "CFIL/RS",
        "nome": "Cadastro de Fornecedores Impedidos de Licitar e Contratar com a "
                "Administração Pública Estadual",
        "uf": "RS",
        "orgao": "CAGE/SEFAZ-RS",
        "lei": "Lei estadual 11.389/1999",
        "trava": "impede licitar e contratar com o Estado",
        "origem": "Certidão pública emitida em cadin.sefaz.rs.gov.br.",
    },
}


async def _ultimo_bloqueio(db: AsyncSession) -> dict | None:
    """Por que a última rodada do `cadin_rs` não trouxe certidão.

    ⚠️ ESTA FUNÇÃO EXISTE PORQUE A TELA MENTIU POR DOIS DIAS. Em 07/09/2026 a
    SEFAZ/RS reescreveu o portal e pôs reCAPTCHA na consulta pública; a coleta
    passou a gravar `partial` com zero certidões, e a tela seguiu dizendo
    "ainda não foram consultados" — que é o oposto do que aconteceu. Ausência
    tem CAUSA, e a causa já estava gravada no `ingestion_log`; ninguém a lia.

    Genérica de propósito: qualquer rodada que termine fora de `success` com
    mensagem vira aviso na tela. O dia em que a fonte quebrar por outro motivo,
    a tela conta esse outro motivo sem ninguém precisar mexer aqui."""
    row = (await db.execute(text("""
        SELECT lower(status), error_message, finished_at
          FROM ingestion_log
         WHERE source = 'cadin_rs'
         ORDER BY id DESC LIMIT 1
    """))).first()
    if not row:
        return None
    status, msg, quando = row
    if status in ("success", "ok") or not (msg or "").strip():
        return None
    return {"motivo": " ".join(msg.split())[:400],
            "desde": quando.isoformat() if quando else None,
            "portal": "https://cadin.sefaz.rs.gov.br"}


async def fetch_negativos(db: AsyncSession, municipio_id: int) -> dict:
    """Núcleo da consulta, SEM gate — reusável pelo Painel como os irmãos."""
    linhas = (await db.execute(text("""
        SELECT cnpj, entidade, uf, fonte, tipo, situacao, quantidade,
               detalhes, consultado_em, erro
          FROM cadastro_negativo
         WHERE municipio_id = :m
         ORDER BY fonte, entidade NULLS LAST
    """), {"m": municipio_id})).fetchall()

    uf = (await db.execute(text("SELECT uf FROM municipios WHERE id = :m"),
                           {"m": municipio_id})).scalar()
    uf = (uf or "").strip().upper()
    # O que EXISTE para este estado, mesmo sem coleta. Sem isto a tela não
    # distingue "consultamos e nada consta" de "não acompanhamos este estado" —
    # e as duas coisas pintam de verde do mesmo jeito.
    previstos = [c for c, d in CATALOGO.items() if d["uf"] == uf]

    # Só o RS tem coleta automática destes cadastros; em Minas o CADIN vem do CRC.
    bloqueio = await _ultimo_bloqueio(db) if uf == "RS" else None

    if not linhas:
        return {
            "tem_dados": False,
            "uf": uf,
            "cadastros_previstos": previstos,
            "catalogo": {c: CATALOGO[c] for c in previstos},
            "bloqueio": bloqueio,
            "motivo": (
                bloqueio["motivo"] if bloqueio else
                f"Os cadastros negativos deste município ({', '.join(CATALOGO[c]['sigla'] for c in previstos)}) "
                "ainda não foram consultados."
                if previstos else
                "Este sistema ainda não acompanha cadastro negativo estadual "
                f"{'de ' + uf if uf else ''}. Não trate a ausência como “nada consta”."),
        }

    itens = [{
        "cnpj": l[0],
        "entidade": l[1],
        "uf": l[2],
        "fonte": l[3],
        "tipo": l[4],
        "situacao": l[5],
        "quantidade": l[6],
        # {"orgao","inscrito_em","quantidade","contato"} — quem inscreveu e com
        # quem falar. Só existe quando HÁ pendência.
        "detalhes": l[7],
        "consultado_em": l[8].isoformat() if l[8] else None,
        "erro": l[9],
    } for l in linhas]

    pendentes = [i for i in itens if i["tipo"] == "pendente"]
    indeterminados = [i for i in itens if i["tipo"] == "indeterminado"]
    return {
        "tem_dados": True,
        "uf": uf,
        # Certidão velha na tela + porta fechada na origem é o pior par: o dado
        # parece atual porque está lá. O aviso vai junto MESMO com dados.
        "bloqueio": bloqueio,
        "cadastros_previstos": previstos,
        "catalogo": {c: CATALOGO[c] for c in sorted({i["fonte"] for i in itens} | set(previstos))
                     if c in CATALOGO},
        "itens": itens,
        # `limpo` exige que NADA esteja pendente E que nada esteja indeterminado:
        # afirmar ausência de inscrição a partir de uma certidão ilegível é o
        # erro que trava um repasse sem ninguém saber.
        "limpo": not pendentes and not indeterminados,
        "pendencias": len(pendentes),
        "indeterminados": len(indeterminados),
        "consultado_em": max((i["consultado_em"] for i in itens if i["consultado_em"]),
                             default=None),
    }


@router.get("", dependencies=[exige("cauc.ver")])
async def situacao(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """CADIN/CFIL do município, por entidade."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "cauc")
    return await fetch_negativos(db, municipio_id)


@router.post("/refresh", dependencies=[exige("cauc.atualizar")])
async def refresh(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Emite a certidão AGORA, para este município.

    Existe porque a certidão do RS não tem validade: ela afirma a situação da
    data em que foi emitida. Numa reunião, "a de ontem" não serve.

    ⚠️ RECORTADO POR MUNICÍPIO, ao contrário do refresh do CAUC (que baixa o
    dataset do Tesouro inteiro e por isso não aceita recorte). Aqui é uma
    requisição por entidade, então exigir o município é o que impede uma conta
    de disparar a carteira toda numa VPS de 0,6 vCPU.

    Só o RS: em Minas o CADIN vem dentro do CRC, e emitir CRC é a rodada do
    CAGEC — que é Playwright, não cabe num clique síncrono."""
    ensure_municipio_access(current, municipio_id)
    authz.exigir_tela(current, "cauc")
    uf = (await db.execute(text("SELECT uf FROM municipios WHERE id = :m"),
                           {"m": municipio_id})).scalar()
    if (uf or "").strip().upper() != "RS":
        return {"ok": False,
                "motivo": "A consulta sob demanda existe só para CADIN/RS e CFIL/RS. "
                          "Em Minas o CADIN-MG é lido do CRC, na rodada do CAGEC."}
    import anyio

    from ingestion.cadin_rs import ingest
    n = await anyio.to_thread.run_sync(lambda: ingest(municipios=[str(municipio_id)]))
    dados = await fetch_negativos(db, municipio_id)
    # ⚠️ ZERO CERTIDÃO NÃO É SUCESSO. Enquanto isto devolvia `ok: True` com
    # `certidoes: 0`, o botão "Consultar agora" piscava e não dizia nada — e o
    # portal estava fora do alcance desde 07/09/2026. Quem clica precisa saber
    # que a porta fechou e por onde consultar na mão.
    if not n and dados.get("bloqueio"):
        return {"ok": False, "certidoes": 0,
                "motivo": dados["bloqueio"]["motivo"], **dados}
    return {"ok": True, "certidoes": n, **dados}
