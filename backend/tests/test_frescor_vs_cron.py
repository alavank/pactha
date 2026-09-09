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
    "acordofes": (24, "dentro do run_all() do cron `sigcon`, 1x/dia"),
    "simec_par": (24, "run_all() em MG; Scheduled Task própria diária no RS"),
    "transferegov_lote": (24, "uma task por tenant, 1x/dia — freitas 03:25 … bgk 05:52 UTC"),
    "transferegov_opendata": (24, "run() diário do transferegov_voluntarias"),
    "transferegov_voluntarias": (24, "idem"),
    "siconv_licitacao": (24, "pendurado no mesmo run() diário"),
    "portal_transparencia": (24, "task `portal-transparencia`, 1x/dia"),
    "sismob": (24, "run_all(), com auto-limite de 1x/dia no próprio ingest()"),
    "siconfi": (24, "task `siconfi`, 1x/dia"),
}

CADENCIA_MEDIDA_POR_UF = {
    "MG": {"sigcon_scraper": (24, "task `sigcon` diária nos três de MG: "
                                  "freitas 05:45, trust 06:30, montesiao 06:45 UTC")},
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
