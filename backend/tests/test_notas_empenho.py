"""NEs / Notas de Empenho (Execução Concedente) — o parser.

⚠️ A FIXTURE É RECONSTRUÍDA, NÃO CAPTURADA. A página está atrás da parede SAML
(medido: guest recebe 3469 bytes de "HTTP Post Binding"), então não foi possível
baixar o HTML real. O que está aqui reproduz a ESTRUTURA e os VALORES visíveis no
print do dono — os mesmos seis cabeçalhos, e as duas linhas do caso real. Se o
parser falhar contra a página de verdade, é aqui que a fixture precisa ser
trocada por uma capturada com sessão viva.

O caso que mais importa é a segunda linha: a MINUTA, sem número de empenho, com
valor de R$ 1,00. Ela não é dinheiro, e somá-la como empenho poria R$ 1,00 no
relatório como se fosse recurso.
"""
import httpx

from ingestion.transferegov_http import TgHttpEnrich


_HTML = """
<html><body>
<table>
  <tr>
    <th>N&uacute;mero do Empenho</th><th>N&uacute;mero da Minuta</th>
    <th>Valor do Empenho</th><th>Valor do Empenho no SIAFI</th>
    <th>Situa&ccedil;&atilde;o</th><th>Data de Emiss&atilde;o</th>
  </tr>
  <tr>
    <td>2026NE000320</td><td>202600000325</td>
    <td>R$ 280.000,00</td><td>R$ 280.000,00</td>
    <td>Enviado</td><td>09/03/2026</td>
  </tr>
  <tr>
    <td></td><td>202500001654</td>
    <td>R$ 1,00</td><td></td>
    <td>Minuta de Empenho</td><td>21/10/2025</td>
  </tr>
</table>
</body></html>
"""

_SAML = '<html><body><p>HTTP Post Binding</p><input name="SAMLResponse"/></body></html>'
_VAZIO = "<html><body><table><tr><th>Situação</th><th>Empenho</th></tr></table>" \
         "<p>Nenhum registro foi encontrado</p></body></html>"


def _resp(html):
    return httpx.Response(200, text=html)


def test_le_o_empenho_real():
    out = TgHttpEnrich._le_notas_empenho(_resp(_HTML))
    ne = out[0]
    assert ne["numero"] == "2026NE000320"
    assert ne["minuta"] == "202600000325"
    assert ne["valor"] == 280000.0
    assert ne["valor_siafi"] == 280000.0
    assert ne["situacao"] == "Enviado"
    assert ne["dt_emissao"] == "09/03/2026"
    assert ne["minuta_apenas"] is False


def test_minuta_e_marcada_e_nao_vira_dinheiro():
    """A linha da minuta tem R$ 1,00 e nenhum número de empenho. Marcá-la na
    LEITURA evita que cada consumidor tenha de redescobrir a regra."""
    out = TgHttpEnrich._le_notas_empenho(_resp(_HTML))
    assert len(out) == 2
    minuta = out[1]
    assert minuta["numero"] is None
    assert minuta["valor"] == 1.0
    assert minuta["minuta_apenas"] is True
    # a soma do que é empenho DE VERDADE ignora a minuta
    total = sum(n["valor"] or 0 for n in out if not n["minuta_apenas"])
    assert total == 280000.0


def test_valor_do_siafi_nao_se_confunde_com_o_valor_do_empenho():
    """Os dois cabeçalhos começam com "Valor do Empenho" — o do SIAFI é
    identificado pelo sufixo, e o outro é o primeiro que não é ele. Sem isso os
    dois índices apontariam para a mesma coluna."""
    out = TgHttpEnrich._le_notas_empenho(_resp(_HTML))
    assert out[0]["valor"] == 280000.0 and out[0]["valor_siafi"] == 280000.0
    assert out[1]["valor"] == 1.0 and out[1]["valor_siafi"] is None


def test_parede_saml_nao_vira_lista_vazia():
    """None (indeterminado) e [] (vazio de verdade) são coisas diferentes: o
    upsert é COALESCE, então None preserva e [] apagaria."""
    assert TgHttpEnrich._le_notas_empenho(_resp(_SAML)) is None


def test_sem_registro_e_lista_vazia():
    assert TgHttpEnrich._le_notas_empenho(_resp(_VAZIO)) == []


# ---------------------------------------------------------------------------
# ⚠️ A SEXTA SAÍDA — a que era MUDA (achado em produção, 25/08/2026)
# ---------------------------------------------------------------------------
class _RespHtml:
    def __init__(self, texto):
        self.text = texto
        self.content = texto.encode()


_GRADE = ("<html><body><table><tr><th>Número do Empenho</th><th>Minuta</th>"
          "<th>Valor do Empenho</th><th>Valor do Empenho no SIAFI</th>"
          "<th>Situação</th><th>Data de Emissão</th></tr>"
          "<tr><td>2026NE000320</td><td>2026ME1</td><td>R$ 280.000,00</td>"
          "<td>R$ 280.000,00</td><td>Enviado</td><td>09/03/2026</td></tr>"
          "<tr><td></td><td>2026ME2</td><td>R$ 1,00</td><td></td>"
          "<td>Minuta de Empenho</td><td>10/03/2026</td></tr></table></body></html>")


def test_a_grade_de_verdade_e_lida_e_a_minuta_marcada():
    from ingestion.transferegov_http import TgHttpEnrich
    r = TgHttpEnrich._le_notas_empenho(_RespHtml(_GRADE))
    assert len(r) == 2
    assert r[0]["numero"] == "2026NE000320" and r[0]["minuta_apenas"] is False
    assert r[1]["numero"] is None and r[1]["minuta_apenas"] is True


def test_vazio_declarado_e_LISTA_e_nao_None():
    """`[]` = "consultei e não há NE". `None` = "não consegui ler". A diferença
    decide se o RM pode dizer PENDENTE DE EMPENHO."""
    from ingestion.transferegov_http import TgHttpEnrich
    assert TgHttpEnrich._le_notas_empenho(
        _RespHtml("<html><body><p>Nenhum registro foi encontrado</p></body></html>")) == []


def test_pagina_sem_a_grade_devolve_None_e_DIZ_o_que_veio(caplog):
    """⚠️ ERA A SAÍDA MUDA. `notas_empenho` tem cinco returns que hoje logam o
    motivo; este sexto caía no fim da função sem uma linha, e o chamador só sabia
    escrever "sem retorno (sessão do SP fria?)".

    Foi o que fez 115 falhas por rodada parecerem sessão morta quando a página
    chegava 200, sem muro SAML e com a sessão comprovadamente quente
    (`keepalive: prestacao=vivo`). O log agora diz quantas tabelas vieram e quais
    são os cabeçalhos — é o que separa "layout mudou" de "a grade vem por POST"
    de "a página é outra"."""
    import logging
    from ingestion.transferegov_http import TgHttpEnrich
    outra = ("<html><body><table><tr><th>Proposta</th><th>Convenente</th></tr>"
             "<tr><td>1</td><td>x</td></tr></table></body></html>")
    with caplog.at_level(logging.INFO):
        assert TgHttpEnrich._le_notas_empenho(_RespHtml(outra)) is None
    texto = caplog.text
    assert "pagina sem a grade" in texto
    assert "Proposta|Convenente" in texto      # nomeia o que ACHOU
