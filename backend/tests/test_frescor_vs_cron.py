"""O prazo que o vigia cobra tem de caber na cadência que a fonte realmente tem.

⚠️ O DEFEITO QUE ISTO IMPEDE JÁ ACONTECEU, e foi caro de um jeito indireto:
prazo MENOR que o intervalo faz a fonte nascer atrasada **todo dia**, no mesmo
horário, para sempre. Não é um alarme errado ocasional — é um alarme que sempre
toca, e alarme que sempre toca ninguém lê. No resumo diário de 09/09/2026,
quatro dos itens de "o que olhar" eram exatamente isto, e o conjunto foi lido
como catástrofe operacional pelo dono.

A cadência abaixo foi MEDIDA nas Scheduled Tasks dos seis workers em
09/09/2026, pela API do Coolify — não é suposição de leitura de código (o
código, aliás, jurava que o lote era horário; não é desde algum ponto de 2026).

O teste é de VALOR, e não de cron, porque o cron não mora neste repositório:
a fonte de verdade das agendas é o Coolify (ver `INFRA.md` §5). O que se guarda
aqui é o resultado da medição, para que abaixar um prazo exija passar por esta
lista e pelo motivo.
"""
from ingestion.watchdog_coleta import FRESCOR_HORAS_NACIONAL, FRESCOR_HORAS_POR_UF

# fonte -> (maior vão real em horas, onde foi medido)
CADENCIA_MEDIDA = {
    "cauc": (20, "cauc-manha `25 10-14 * * *` nos seis: cinco rodadas de manhã "
                 "e um vão de 20h até a próxima"),
    "simec_par": (24, "run_all() em MG; Scheduled Task própria diária no RS"),
    "transferegov_lote": (24, "1x/dia em montesiao, santamaria, novapalma e bgk "
                              "(03:25–05:52 UTC); 4x/dia em freitas e trust desde 10/09"),
    "transferegov_opendata": (24, "run() diário do transferegov_voluntarias"),
    "transferegov_voluntarias": (24, "idem"),
    "siconv_licitacao": (24, "pendurado no mesmo run() diário"),
    "portal_transparencia": (24, "task `portal-transparencia`, 1x/dia"),
    "sismob": (24, "run_all(), com auto-limite de 1x/dia no próprio ingest()"),
    "siconfi": (24, "task `siconfi`, 1x/dia"),
}

CADENCIA_MEDIDA_POR_UF = {
    "MG": {"sigcon_scraper": (24, "task `sigcon` diária nos três de MG: "
                                  "freitas 05:45, trust 06:30, montesiao 06:45 UTC"),
           # Morava em CADENCIA_MEDIDA e por isso só se conferia o prazo NACIONAL
           # (30h) — que em MG não vale, porque o mapa da UF sobrescreve. O prazo
           # de MG era 12h e passou por este teste de 09/09 a 10/09/2026.
           "acordofes": (24, "dentro do run_all() do cron `sigcon`, 1x/dia nos três de MG")},
    "RS": {"che_rs": (24, "task `che-rs`, 1x/dia"),
           "cadin_rs": (24, "task `cadin-rs`, 1x/dia")},
}


def test_nenhum_prazo_e_menor_que_a_cadencia_real():
    """Prazo < cadência = a fonte está 'atrasada' a maior parte do dia, sempre."""
    for fonte, (intervalo, onde) in CADENCIA_MEDIDA.items():
        prazo = FRESCOR_HORAS_NACIONAL.get(fonte)
        assert prazo is not None, f"{fonte} saiu do catálogo — deixaria de ser vigiada"
        assert prazo >= intervalo, (
            f"{fonte}: cobra {prazo}h mas roda a cada {intervalo}h ({onde}). "
            "Isso faz o alarme tocar todo dia e o relatório perder o valor.")


def test_nenhum_prazo_por_uf_e_menor_que_a_cadencia_real():
    for uf, fontes in CADENCIA_MEDIDA_POR_UF.items():
        for fonte, (intervalo, onde) in fontes.items():
            prazo = FRESCOR_HORAS_POR_UF[uf].get(fonte)
            assert prazo is not None, f"{uf}/{fonte} saiu do catálogo"
            assert prazo >= intervalo, f"{uf}/{fonte}: cobra {prazo}h, roda a cada {intervalo}h ({onde})"


def test_a_folga_existe_mas_nao_e_infinita():
    """O outro lado do erro: prazo folgado demais deixa a fonte morrer em paz.

    Duas cadências + um pouco é o teto — passou disso, uma fonte pode ficar dois
    dias parada sem ninguém saber, que é o problema que o watchdog resolve."""
    for fonte, (intervalo, _) in CADENCIA_MEDIDA.items():
        prazo = FRESCOR_HORAS_NACIONAL[fonte]
        assert prazo <= intervalo * 2 + 12, (
            f"{fonte}: {prazo}h para uma fonte de {intervalo}h é folga demais")
    for uf, fontes in CADENCIA_MEDIDA_POR_UF.items():
        for fonte, (intervalo, _) in fontes.items():
            prazo = FRESCOR_HORAS_POR_UF[uf][fonte]
            assert prazo <= intervalo * 2 + 12, (
                f"{uf}/{fonte}: {prazo}h para uma fonte de {intervalo}h é folga demais")


def test_uma_fonte_tem_prazo_em_um_lugar_so():
    """A mesma fonte no catálogo nacional E no de uma UF = dois prazos, e o que
    vale é o que ninguém está olhando.

    `frescor_esperado()` aplica o mapa da UF por cima do nacional. Foi assim que
    o `acordofes` ficou com 30h no nacional (conserto de 09/09) e 12h em MG — e
    como os três tenants que o coletam são de MG, o conserto não valeu em lugar
    nenhum: o alarme seguiu tocando toda tarde."""
    for uf, fontes in FRESCOR_HORAS_POR_UF.items():
        duplicadas = sorted(set(fontes) & set(FRESCOR_HORAS_NACIONAL))
        assert not duplicadas, (
            f"{uf}: {duplicadas} também estão no catálogo nacional — em tenant de "
            f"{uf} vale o prazo da UF e o nacional vira enfeite. Deixe um só.")
