#!/usr/bin/env bash
# OBRAS.GOV.BR — o 429 e penalidade acumulada ou recusa a datacenter?
#
# POR QUE ESTA MEDICAO EXISTE. Na bateria de 03/09/2026, a API devolveu 429 na
# PRIMEIRA requisicao feita da VPS. Isso nao distingue duas causas com
# consequencias opostas:
#
#   (a) PENALIDADE ACUMULADA no IP. O `INFRA.md` §5 documenta a API de
#       Transferencias Especiais deixando esta mesma VPS **mais de 6 horas** de
#       castigo depois de rodadas encadeadas — e requisicao rejeitada RENOVA a
#       pena. Se for isso, o coletor funciona: basta espacar.
#   (b) RECUSA IMEDIATA a faixa de datacenter, como o TCE-RS faz. Se for isso, o
#       coletor nao funciona daqui, e a Scheduled Tarefa nao deve ser criada.
#
# COMO LER O RESULTADO:
#
#   * Algum 200 nas tres tentativas  -> e (a). O rate limit e vencivel com
#     espacamento, e o coletor pode ser ligado (ele ja espaca 8s por pagina e
#     tem backoff de ate 120s no 429).
#   * 429 nas tres, com 90s de intervalo -> e (b), ou uma penalidade longa. Nos
#     dois casos: nao ligar ainda, e repetir esta medicao depois de algumas
#     horas de silencio total do IP.
#
# ⚠️ TRES REQUISICOES, COM 90s ENTRE ELAS, E SO ISSO. Nao aumente o numero nem
# reduza a espera "para ter mais dados": sob penalidade, cada tentativa RENOVA o
# castigo — foi exatamente assim que o IP ficou 6h bloqueado no TransfereGov.
#
# Rodar de casa (o `!` no Claude Code ja serve):
#     ssh -i ~/.ssh/coolify_localhost root@54.232.208.118 'bash -s' \
#       < scripts/medir_obrasgov_vps.sh

URL="https://api.obrasgov.gestao.gov.br/obrasgov/api/projeto-investimento?uf=RS&pagina=0&tamanhoDaPagina=5"

echo "== Obras.gov.br a partir de $(curl -s --max-time 20 https://api.ipify.org || echo '?')"
echo "== $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo

for i in 1 2 3; do
  printf 'tentativa %d: ' "$i"
  curl -s -o /tmp/obrasgov_medicao.json \
    -w 'http=%{http_code}  tempo=%{time_total}s  tam=%{size_download}\n' \
    --max-time 40 \
    -H 'User-Agent: Mozilla/5.0 (PACTHA/1.0 medicao de rate limit)' \
    "$URL"
  if [ "$i" -lt 3 ]; then
    echo "   (aguardando 90s — sob penalidade, tentar de novo cedo demais RENOVA o castigo)"
    sleep 90
  fi
done

echo
echo "-- amostra do que voltou na ultima tentativa (vazio = 429):"
head -c 300 /tmp/obrasgov_medicao.json 2>/dev/null || echo "(sem corpo)"
echo
echo
echo "== fim. Cole a saida inteira de volta no chat."
