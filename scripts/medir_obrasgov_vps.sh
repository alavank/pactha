#!/usr/bin/env bash
# OBRAS.GOV.BR — o host novo responde bem do IP da VPS?
#
# HISTORICO. Na bateria de 03/09/2026, `api.obrasgov.gestao.gov.br` devolveu
# 429 na PRIMEIRA requisicao feita da VPS. A migracao para
# `api-publica.obrasgov.gestao.gov.br/obras` (04/09/2026) resolveu isso em
# producao — ver `backend/ingestion/obrasgov.py` e `INFRA.md` §5 — e o host
# antigo hoje devolve 429 permanente (confirmado em 06/09/2026, de fora da
# VPS). Este script deixou de servir para diagnosticar o host antigo.
#
# PARA QUE SERVE AGORA. O host novo fica atras de Cloudflare, e o `dados.tce.
# rs.gov.br` ja ensinou que resposta de IP residencial nao prova nada sobre o
# IP da VPS. Antes de estender a coleta do Obras.gov.br (mais endpoints) ou de
# migrar outro modulo do TransfereGov (Especiais, Parcerias, Fundo a Fundo,
# mesmo dominio `api-publica.*.gestao.gov.br`) para producao, confirme daqui
# que o host novo responde bem — e nao apenas da maquina de casa.
#
# COMO LER O RESULTADO:
#
#   * 200 nas tres tentativas -> o host novo trata o IP da VPS igual ao IP
#     residencial. Pode prosseguir com a extensao/migracao planejada.
#   * 429 ou 403 -> o host novo pune ou bloqueia faixa de datacenter, como o
#     TCE-RS. Nao prosseguir; investigar antes de agendar qualquer coleta.
#
# Ainda assim, TRES REQUISICOES COM 90s ENTRE ELAS — o habito de nao martelar
# fonte federal vale mesmo quando ela nao esta mostrando sinal de penalidade.
#
# Rodar de casa (o `!` no Claude Code ja serve):
#     ssh -i ~/.ssh/coolify_localhost root@54.232.208.118 'bash -s' \
#       < scripts/medir_obrasgov_vps.sh

URL="https://api-publica.obrasgov.gestao.gov.br/obras/projeto-investimento?uf_principal=RS&pagina=1&tamanho_da_pagina=5"

echo "== Obras.gov.br (host novo) a partir de $(curl -s --max-time 20 https://api.ipify.org || echo '?')"
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
    echo "   (aguardando 90s — nao ha motivo para martelar fonte federal)"
    sleep 90
  fi
done

echo
echo "-- amostra do que voltou na ultima tentativa (vazio = bloqueio):"
head -c 300 /tmp/obrasgov_medicao.json 2>/dev/null || echo "(sem corpo)"
echo
echo
echo "== fim. Cole a saida inteira de volta no chat."
