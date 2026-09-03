#!/usr/bin/env bash
# TCE-RS: o portal.tce.rs.gov.br responde da VPS? (o dados.tce.rs.gov.br nao)
#
# ⭐ POR QUE ISTO PODE MUDAR TUDO. O que esta bloqueado e o
# **`dados.tce.rs.gov.br`** — o portal CKAN de dados abertos, 403 medido tres
# vezes. Mas o proprio TCE publica APIs em **OUTRO HOST**,
# `portal.tce.rs.gov.br`, e elas respondem SEM AUTENTICACAO:
#
#   /api/qonws/q/licitacon.licitacoes    licitacoes por orgao, com situacao
#   /api/qonws/q/licitacon.contratos     contratos por orgao
#   /api/qonws/q/licitacon.remessas      ⭐ as REMESSAS: data de recebimento,
#                                        situacao e responsavel. E a conferencia
#                                        de prazo que a tela hoje diz nao ser
#                                        automatica.
#   /api/qonws/q/licitacon_dominios.orgaos   de-para CD_ORGAO x CNPJ x IBGE
#   /api/obras/v1/orgaos/{cnpj}/obras    LicitaCon Obras (execucao contratual)
#
# Medido do IP residencial em 03/09/2026: todos 200. Santa Maria tem 120 obras
# no LicitaCon Obras; Nova Palma tem a remessa de 2026/01 registrada.
#
# SE ESTE HOST RESPONDER DA VPS, o oficio deixa de ser caminho critico: da para
# coletar licitacao, contrato, obra e remessa sem o CKAN bloqueado. O que se
# perde e o dump historico completo em CSV — mas o que a tela precisa mostrar
# esta aqui.
#
# COMO LER: os dois controles positivos primeiro (CHE e CKAN da CAGE). Se eles
# passarem e o portal.tce falhar, e bloqueio do host. Se o portal.tce passar,
# temos a fonte de volta.
#
# Rodar de casa (o `!` do Claude Code serve):
#     ssh -i ~/.ssh/coolify_localhost root@54.232.208.118 'bash -s' \
#       < scripts/medir_tce_portal_vps.sh

PAUSA="${PAUSA:-3}"

sonda() {
  local rotulo="$1" url="$2"
  printf '%-42s ' "$rotulo"
  curl -s -o /tmp/tce_portal.out \
    -w 'http=%{http_code}  tempo=%{time_total}s  tam=%{size_download}\n' \
    --max-time 45 \
    -H 'Accept: application/json' \
    -H 'User-Agent: Mozilla/5.0 (PACTHA/1.0 consulta publica TCE-RS)' \
    "$url" || echo "FALHOU (sem resposta)"
  sleep "$PAUSA"
}

echo "== TCE-RS portal.tce.rs.gov.br a partir de $(curl -s --max-time 20 https://api.ipify.org || echo '?')"
echo "== $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo

echo "-- CONTROLES: se estes falharem, o problema e a rede, nao o host"
sonda "che.sefaz.rs.gov.br (funciona hoje)" \
  "https://che.sefaz.rs.gov.br/api/Entidade/Consultar?entidadeCnpj=88488358000156"
sonda "dados.tce.rs.gov.br (BLOQUEADO)" \
  "https://dados.tce.rs.gov.br/api/3/action/package_show?id=licitacoes-pm-de-nova-palma"

echo
echo "-- O HOST NOVO: portal.tce.rs.gov.br"
sonda "qonws: orgaos (de-para IBGE)" \
  "https://portal.tce.rs.gov.br/api/qonws/q/licitacon_dominios.orgaos.json?limit=2"
sonda "qonws: remessas Nova Palma 2026/1" \
  "https://portal.tce.rs.gov.br/api/qonws/q/licitacon.remessas.json?cd_orgao=53100&ano_exercicio=2026&periodo=1&limit=3"
sonda "obras: orgaos-fiscalizados" \
  "https://portal.tce.rs.gov.br/api/obras/v1/orgaos-fiscalizados"
sonda "obras: 120 obras de Santa Maria" \
  "https://portal.tce.rs.gov.br/api/obras/v1/orgaos/88488366000100/obras?page=0&size=3"

echo
echo "-- amostra do que voltou na ultima chamada:"
head -c 300 /tmp/tce_portal.out 2>/dev/null || echo "(sem corpo)"
echo
echo
echo "== fim. Cole a saida inteira de volta no chat."
