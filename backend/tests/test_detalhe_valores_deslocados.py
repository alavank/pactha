"""O dinheiro deslocado sai do JSONB `detalhe`, e o CSV passa a mandar na coluna.

A trava `valores_coerentes` (#322) nasceu protegendo as tres COLUNAS de dinheiro
e nisso funciona. Faltavam duas coisas, medidas em Araujos em 30/08/2026:

1. O `detalhe` seguia gravado INTEIRO, com os valores deslocados dentro. 83 de 83
   propostas tinham o trio trocado no JSONB, e 61 tinham sido regravadas naquele
   mesmo dia — nao era passivo, era reescrita diaria.

2. A trava so barra o trio que NAO FECHA. Um deslocamento que por acaso fecha
   atravessa: 053238/2015 tem no portal 150.000/100.000/50.000 e ficou na
   plataforma com 100.000/50.000/50.000 — e 50.000 + 50.000 = 100.000.
"""
import os
import re

import pytest

from ingestion.transferegov_voluntarias import valores_coerentes

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLETOR = os.path.join(RAIZ, "ingestion", "transferegov_voluntarias.py")
MIGRATION = os.path.join(RAIZ, "migrations", "limpa_detalhe_valores_deslocados.sql")
CHAVES = ("Valor Global", "Valor de Repasse", "Valor de Contrapartida")


def _codigo(caminho, marca):
    return "\n".join(l for l in open(caminho, encoding="utf-8").read().splitlines()
                     if not l.lstrip().startswith(marca))


# --- a regra do descarte, reproduzida ---------------------------------------

def _limpa(det: dict, glob, rep, contra) -> dict:
    """Espelha o bloco do `_upsert`: trio incoerente -> as tres chaves saem."""
    det = dict(det)
    if not valores_coerentes(glob, rep, contra):
        sujos = [k for k in CHAVES if k in det]
        if sujos:
            for k in sujos:
                det.pop(k, None)
            det["_valores_descartados"] = sujos
    return det


def test_o_trio_deslocado_sai_do_detalhe():
    """O caso da creche de Araujos: 059522/2021. A pagina deu global=repasse e
    repasse=contrapartida; 3.819.853,65 nao e 3.823,68 + 3.823,68."""
    det = {"Valor Global": "R$ 3.819.853,65", "Valor de Repasse": "R$ 3.823,68",
           "Valor de Contrapartida": "R$ 3.823,68", "Órgão": "26000 - MEC"}
    out = _limpa(det, 3819853.65, 3823.68, 3823.68)
    assert not any(k in out for k in CHAVES)
    assert out["_valores_descartados"] == list(CHAVES)
    assert out["Órgão"] == "26000 - MEC", "o resto do detalhe nao pode ser tocado"


def test_o_trio_certo_fica():
    """O portal serve mais de um layout; onde a leitura sai certa, nada muda."""
    det = {"Valor Global": "R$ 150.000,00", "Valor de Repasse": "R$ 100.000,00",
           "Valor de Contrapartida": "R$ 50.000,00"}
    out = _limpa(det, 150000.0, 100000.0, 50000.0)
    assert all(k in out for k in CHAVES)
    assert "_valores_descartados" not in out


def test_o_marcador_separa_APAGADO_de_NUNCA_LIDO():
    """⚠️ Sem o marcador, "nao tem valor no detalhe" seria indistinguivel de
    "nunca li o detalhe" — a mesma confusao de medido x ausente que o repo ja
    paga caro em outros campos."""
    out = _limpa({"Valor Global": "R$ 1,00", "Valor de Repasse": "R$ 9,00"}, 1.0, 9.0, None)
    assert out["_valores_descartados"] == ["Valor Global", "Valor de Repasse"]
    vazio = _limpa({"Órgão": "x"}, 1.0, 9.0, None)
    assert "_valores_descartados" not in vazio, "sem chave de dinheiro nao ha o que marcar"


def test_apaga_em_vez_de_corrigir():
    """⚠️ Deliberado: o `detalhe` e o que a PAGINA disse. Escrever o valor certo
    ali inventaria uma leitura que nunca houve. Quem precisa do numero tem a
    coluna ao lado, que vem do CSV oficial."""
    out = _limpa({"Valor Global": "R$ 3.819.853,65", "Valor de Repasse": "R$ 3.823,68"},
                 3819853.65, 3823.68, None)
    assert "Valor Global" not in out
    assert "R$ 3.823.677,33" not in str(out), "corrigiu em vez de apagar"


# --- a coluna: quem manda -----------------------------------------------------

def test_a_coluna_vem_antes_do_EXCLUDED_no_upsert():
    """⚠️ ESTA ORDEM E O CONSERTO INTEIRO. Com o EXCLUDED na frente, o scraper
    sobrescrevia o valor do CSV — e a trava so o parava quando o trio nao fechava.
    Invertida de volta, o defeito ressuscita sem que nenhum outro teste perceba."""
    src = _codigo(COLETOR, "--")
    for c in ("valor_global", "valor_repasse", "valor_contrapartida"):
        m = re.search(rf"{c}=COALESCE\(([^,]+),", src)
        assert m, f"clausula de {c} nao encontrada"
        assert m.group(1).strip().startswith("transferegov_propostas."), \
            f"{c}: o EXCLUDED voltou para a frente da coluna"


def test_o_deslocamento_que_FECHA_e_o_ponto_cego_conhecido():
    """053238/2015: 100.000 = 50.000 + 50.000, entao a trava aprova. E por isso
    que a ordem do COALESCE importa — ela e a segunda linha de defesa."""
    assert valores_coerentes(100000.0, 50000.0, 50000.0) is True
    assert valores_coerentes(150000.0, 100000.0, 50000.0) is True


# --- a migration --------------------------------------------------------------

def test_a_migration_so_apaga_o_trio_que_nao_fecha():
    sql = _codigo(MIGRATION, "--")
    assert "abs(" in sql and "> 0.02" in sql, "sem a conta, apagaria tudo"
    assert sql.count("UPDATE transferegov_propostas") == 1
    assert "_valores_descartados" in sql
    # o regex antes do cast: detalhe e texto livre da tela
    assert sql.count("~ '^R\\$ ?[0-9.]+,[0-9]{2}$'") == 3


def test_a_migration_esta_na_lista_que_o_boot_executa():
    from services.startup import MIGRATION_FILES
    assert "limpa_detalhe_valores_deslocados.sql" in MIGRATION_FILES


def test_o_sql_da_migration_e_valido_para_o_postgres():
    pglast = pytest.importorskip("pglast", reason="pglast ausente — checagem PULADA")
    pglast.parse_sql(open(MIGRATION, encoding="utf-8").read())
