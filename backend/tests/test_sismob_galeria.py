"""O registro fotográfico da obra — o metadado que vale mesmo sem a imagem.

O modal de fotos do PACTHA existe para o gestor não sair do sistema. Só que a
imagem depende de um serviço do Ministério que, medido em 07/09/2026, responde
**500** na imagem cheia e devolve um PNG de "Pré-visualização não disponível" na
miniatura — o mesmo arquivo, byte a byte, em obras de municípios diferentes.

Por isso a parte que precisa estar certa é o METADADO: grupo, quantidade e data.
É ele que responde a pergunta que a situação da obra não responde — *em que fase
o município parou de registrar*. Na UBS João Bernardes de Souza (Bueno
Brandão/MG, proposta 184232, R$ 2,01 mi) a resposta é dura: as 12 fotos são de
«Terreno» e «Placa da obra», a última é de 08/08/2025, e não há nenhum grupo de
execução — enquanto a situação diz "Em início de execução".

O payload abaixo é o real, recortado da fonte.

Rodar:
    python -m pytest backend/tests/test_sismob_galeria.py -v
"""
from routers.sismob import galeria_do_raw

# Recorte fiel de https://sismobcidadao.saude.gov.br/api/public/obras/184232
RAW = {
    "noEstabelecimentoProposta": "UBS João Bernardes de Souza",
    "dsSituacaoObra": "Em início de execução",
    "gruposFotografias": [
        {"noGrupo": "Terreno - acesso principal",
         "fotos": [{"id": "928c8371-4725-4c46-8ed5-9bed56a579b5",
                    "dtAtualizacao": "2025-08-08T01:59:50.569+0000"}]},
        {"noGrupo": "Terreno",
         "fotos": [{"id": f"velha-{i}", "dtAtualizacao": "2025-02-12T10:00:00.000+0000"}
                   for i in range(6)]},
        {"noGrupo": "Placa da obra",
         "fotos": [{"id": "placa-1", "dtAtualizacao": "2025-08-08T01:59:50.900+0000"}]},
        # Grupo declarado e vazio: o SISMOB cria os sete grupos sempre, mesmo
        # sem foto. Contá-lo como grupo diria que há registro onde não há.
        {"noGrupo": "Fachada", "fotos": []},
    ],
}


def test_grupo_vazio_nao_entra():
    """Sete grupos declarados, três com foto — a tela não pode listar quatro."""
    g = galeria_do_raw(RAW)
    assert [x["grupo"] for x in g] == [
        "Terreno - acesso principal", "Placa da obra", "Terreno"]


def test_ordem_e_do_mais_recente_para_o_mais_antigo():
    """A primeira linha do modal é a fase em que o registro parou."""
    g = galeria_do_raw(RAW)
    assert [x["ultima_em"] for x in g] == ["2025-08-08", "2025-08-08", "2025-02-12"]


def test_contagem_e_data_por_grupo():
    g = {x["grupo"]: x for x in galeria_do_raw(RAW)}
    assert g["Terreno"]["total"] == 6
    assert g["Terreno"]["ultima_em"] == "2025-02-12"
    assert g["Placa da obra"]["total"] == 1


def test_ids_preservados_para_o_proxy():
    """O id é o que o endpoint de imagem valida — sem ele, não há foto a servir."""
    ids = {f["id"] for g in galeria_do_raw(RAW) for f in g["fotos"]}
    assert "928c8371-4725-4c46-8ed5-9bed56a579b5" in ids
    assert len(ids) == 8


def test_foto_sem_id_e_descartada():
    """Entrada sem id não vira card quebrado no modal."""
    g = galeria_do_raw({"gruposFotografias": [
        {"noGrupo": "X", "fotos": [{"dtAtualizacao": "2025-01-01T00:00:00.000+0000"},
                                   {"id": "ok", "dtAtualizacao": None}]}]})
    assert len(g) == 1 and g[0]["total"] == 1 and g[0]["fotos"][0]["id"] == "ok"


def test_sem_fotos_nao_quebra():
    assert galeria_do_raw({}) == []
    assert galeria_do_raw(None) == []
    assert galeria_do_raw({"gruposFotografias": None}) == []
