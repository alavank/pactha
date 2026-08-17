"""
A regra do Decreto 56.939/2023 (RS) — monitoramento mensal de convênios.

O que estes testes provam, e por que cada um existe:

  (a) A CONTAGEM. Quantos meses de registro faltam, contados do jeito que a
      norma conta — e não do jeito ingênuo, que cobraria o mês corrente no dia 1º
      e transformaria o produto num alarme diário.
  (b) O ALARME É NO 2º MÊS, não no 3º. O prejuízo (suspensão de parcela) chega
      no 3º; um aviso que só toca junto com o dano não vale nada.
  (c) ⭐ O FALSO ALARME DE ESTREIA NÃO ACONTECE. Com a tabela vazia — que é o
      estado de todo tenant antes da credencial PCPRS — a regra devolve
      "não conectado", nunca uma parede vermelha. É o teste mais importante do
      arquivo: um falso positivo aqui ensina o cliente a ignorar o alerta para
      sempre, inclusive quando ele for verdadeiro.
  (d) A EXCEÇÃO DE CALAMIDADE (120 dias) desarma o alarme de quem está
      legalmente em dia — e o default é SEM exceção, para não silenciar alarme
      real por omissão de cadastro.
  (e) Convênio FORA de execução não entra no universo. O dump da CAGE traz
      instrumento em fase anterior à celebração, que não está sob a obrigação.
  (f) A FRASE não afirma que o bloqueio aconteceu. Vemos ausência de registro,
      não a decisão do Estado.

Rodar:
    python -m pytest backend/tests/test_monitoramento_rs.py -v
"""
from datetime import date

from services.monitoramento_rs import (
    avaliar, competencia, competencias_exigidas, esta_em_execucao,
)


def _conv(chave="C1", situacao="Em execução", ini=date(2024, 1, 10), fim=date(2027, 12, 31)):
    return {"chave": chave, "convenio_id": 1, "rotulo": "Convênio de teste",
            "situacao": situacao, "dt_inicio": ini, "dt_fim": fim}


# --------------------------------------------------------------- (a) contagem

def test_competencia_e_ano_mes():
    assert competencia(date(2026, 8, 17)) == "2026-08"


def test_o_mes_corrente_so_e_exigido_depois_do_dia_15():
    """⚠️ O erro mais fácil de cometer aqui. Até o dia 15 o município está
    dentro do direito dele; cobrar antes faria o sistema apitar todo dia 1º."""
    ini = date(2026, 1, 1)
    # dia 10 de agosto: julho ainda NÃO venceu (vence 15/08)
    ate_dia_10 = competencias_exigidas(ini, None, date(2026, 8, 10))
    assert "2026-07" not in ate_dia_10
    assert "2026-06" in ate_dia_10
    # dia 16: julho passou a ser exigível
    depois = competencias_exigidas(ini, None, date(2026, 8, 16))
    assert "2026-07" in depois


def test_nao_cobra_competencia_anterior_a_vigencia_do_decreto():
    """Convênio de 2019 não deve competência de 2019 — o decreto é de 03/2023."""
    exigidas = competencias_exigidas(date(2019, 5, 1), None, date(2026, 8, 20))
    assert exigidas[0] == "2023-03"


def test_convenio_encerrado_nao_acumula_depois_do_fim_da_vigencia():
    exigidas = competencias_exigidas(date(2024, 1, 1), date(2024, 6, 30),
                                     date(2026, 8, 20))
    assert exigidas[-1] == "2024-06"


# ------------------------------------------------- (b) o alarme é no 2º mês

def test_um_mes_e_atencao_dois_meses_e_alarme():
    hoje = date(2026, 8, 20)
    conv = [_conv(ini=date(2026, 1, 1))]
    exigidas = competencias_exigidas(date(2026, 1, 1), None, hoje)

    # tudo registrado menos o último mês -> atenção
    reg = {("C1", m) for m in exigidas[:-1]}
    r = avaliar(conv, reg, hoje=hoje)
    assert r["nivel"] == "atencao"
    assert r["pendencias"][0].meses_em_atraso == 1

    # faltando dois -> alarme, e a frase cita a consequência prevista
    reg2 = {("C1", m) for m in exigidas[:-2]}
    r2 = avaliar(conv, reg2, hoje=hoje)
    assert r2["nivel"] == "alarme"
    assert r2["pendencias"][0].meses_em_atraso == 2
    assert "suspensão das parcelas" in r2["resumo"]


def test_tudo_registrado_fica_em_dia_e_nao_lista_pendencia():
    hoje = date(2026, 8, 20)
    exigidas = competencias_exigidas(date(2026, 1, 1), None, hoje)
    r = avaliar([_conv(ini=date(2026, 1, 1))], {("C1", m) for m in exigidas}, hoje=hoje)
    assert r["nivel"] == "em_dia"
    assert r["pendencias"] == []
    assert r["em_dia"] == 1


# ------------------------------------- (c) ⭐ o falso alarme de estreia

def test_sem_nenhum_registro_a_regra_diz_NAO_CONECTADO_e_nao_alarme():
    """⭐ O TESTE MAIS IMPORTANTE DESTE ARQUIVO.

    Enquanto não houver credencial PCPRS, `monitoramento_convenios` está vazia.
    Uma contagem ingênua acusaria 100% dos convênios como atrasados, e o cliente
    abriria o sistema numa parede vermelha inteiramente falsa — depois disso,
    ignoraria o alerta para sempre."""
    hoje = date(2026, 8, 20)
    muitos = [_conv(chave=f"C{i}", ini=date(2023, 1, 1)) for i in range(30)]
    r = avaliar(muitos, set(), hoje=hoje, tem_algum_registro=False)
    assert r["estado"] == "nao_conectado"
    assert r["nivel"] == "desconhecido"
    assert r["pendencias"] == []
    # e a frase explica o que falta, sem culpar o município
    assert "PCPRS" in r["resumo"]


def test_com_a_fonte_conectada_a_ausencia_volta_a_ser_atraso_de_verdade():
    """A guarda (c) não pode virar mordaça: uma vez conectado, ausência é
    atraso, e o alarme tem de tocar."""
    hoje = date(2026, 8, 20)
    r = avaliar([_conv(ini=date(2026, 1, 1))], set(), hoje=hoje,
                tem_algum_registro=True)
    assert r["estado"] == "avaliado"
    assert r["nivel"] == "alarme"


# ------------------------------------------- (d) a exceção de calamidade

def test_calamidade_da_120_dias_em_vez_do_dia_15():
    """Município em calamidade não pode ser acusado de atraso que a norma lhe
    perdoou (Nota Técnica SPGG, pós-enchentes de 2024)."""
    hoje = date(2026, 8, 20)
    conv = [_conv(ini=date(2026, 5, 1))]

    # SEM exceção: maio, junho e julho já venceram (dia 15 do mês seguinte)
    sem = avaliar(conv, set(), hoje=hoje)
    assert sem["nivel"] == "alarme"
    assert sem["pendencias"][0].atrasadas == ["2026-05", "2026-06", "2026-07"]

    # COM calamidade: 120 dias após o fim de cada competência. Maio só vence em
    # 28/09 — ou seja, o município que a norma perdoou não deve NADA ainda, e o
    # alarme simplesmente não existe. Este é o ponto: a exceção não "reduz" o
    # atraso, ela o elimina enquanto vale.
    com = avaliar(conv, set(), hoje=hoje, calamidade_ate=date(2026, 12, 31))
    assert com["regime"] == "calamidade"
    assert com["nivel"] == "em_dia"
    assert com["pendencias"] == []
    assert com["avaliados"] == 1          # o convênio FOI avaliado, e passou


def test_calamidade_VENCIDA_nao_vale_mais():
    """Default é SEM exceção, e exceção expirada é o mesmo que não ter: o risco
    de silenciar alarme real por omissão de cadastro é maior que o inverso."""
    hoje = date(2026, 8, 20)
    r = avaliar([_conv(ini=date(2026, 1, 1))], set(), hoje=hoje,
                calamidade_ate=date(2025, 12, 31))
    assert r["regime"] == "padrao"


# ---------------------------------------- (e) universo: só o que executa

def test_liberado_para_assembleia_CONTA_apesar_do_nome():
    """⚠️ A armadilha mais cara deste módulo, e a razão deste teste existir.

    "Liberado para Assembleia Legislativa" *parece* convênio que ainda nem foi
    celebrado, e a primeira versão da regra o excluiu por isso — resultado: dos
    108 convênios reais de Santa Maria, **zero** eram avaliados e o alarme jamais
    tocaria. Um alerta que nunca dispara é pior que alerta nenhum.

    Medido no dump da CAGE: essa situação inclui um convênio de R$ 10 milhões
    **integralmente pago**, com vigência até 2030. O campo descreve etapa do
    trâmite, não estado de execução."""
    hoje = date(2026, 8, 20)
    r = avaliar([_conv(situacao="Liberado para Assembléia Legislativa",
                       ini=date(2026, 1, 1))], set(), hoje=hoje)
    assert r["avaliados"] == 1
    assert r["nivel"] == "alarme"


def test_convenio_encerrado_de_verdade_fica_fora():
    """O que sai do universo é o que a situação diz estar ENCERRADO — não o que
    está no meio do trâmite."""
    hoje = date(2026, 8, 20)
    for situacao in ("Cancelado", "EXTINTO", "Rescindido", "Não aprovado"):
        r = avaliar([_conv(situacao=situacao, ini=date(2026, 1, 1))], set(), hoje=hoje)
        assert r["avaliados"] == 0, f"{situacao} deveria ficar fora"


def test_situacao_sem_acento_e_em_caixa_alta_tambem_e_reconhecida():
    """O dump mistura grafias ao longo dos anos."""
    assert not esta_em_execucao("EXTINTO", date(2024, 1, 1), None, date(2026, 8, 20))
    assert not esta_em_execucao("Rescindido", date(2024, 1, 1), None, date(2026, 8, 20))


def test_vigencia_futura_ou_encerrada_nao_esta_em_execucao():
    hoje = date(2026, 8, 20)
    assert not esta_em_execucao("Em execução", date(2027, 1, 1), None, hoje)
    assert not esta_em_execucao("Em execução", date(2024, 1, 1), date(2025, 1, 1), hoje)
    assert esta_em_execucao("Em execução", date(2024, 1, 1), date(2027, 1, 1), hoje)


def test_sem_data_de_inicio_nao_afirma_que_comecou():
    assert not esta_em_execucao("Em execução", None, None, date(2026, 8, 20))


# --------------------------------------------- (f) a frase é honesta

def test_a_frase_nao_afirma_que_o_bloqueio_ja_aconteceu():
    """Vemos a AUSÊNCIA de registro, não a decisão do Estado. A frase descreve o
    que a norma prevê — não o que já teria sido aplicado."""
    hoje = date(2026, 8, 20)
    r = avaliar([_conv(ini=date(2025, 1, 1))], set(), hoje=hoje)
    resumo = r["resumo"].lower()
    assert "a norma prevê" in resumo
    for proibida in ("você está bloqueado", "parcelas suspensas",
                     "convênio bloqueado", "está impedido"):
        assert proibida not in resumo
