#!/usr/bin/env bash
# RECONHECIMENTO DE FONTES A PARTIR DO IP DA VPS — somente leitura.
#
# POR QUE ESTE SCRIPT EXISTE. O que responde da máquina de casa não prova nada
# sobre o servidor: o `dados.tce.rs.gov.br` devolve 200 de IP residencial e 403
# da VPS (medido em 17/08 e 29/08/2026). Antes de escrever coletor para uma
# fonte nova, o veredito tem de vir DO LUGAR ONDE O COLETOR VAI VIVER.
#
# UMA requisição por fonte, com pausa entre elas. Nada aqui grava, baixa dump
# grande nem repete chamada — várias destas fontes punem martelada (a API de
# Transferências Especiais deixou o IP da VPS 6h de castigo em 17/08).
#
# Rodar NA VPS:
#     ssh -i ~/.ssh/coolify_localhost root@54.232.208.118
#     bash /tmp/reconhecimento_fontes_vps.sh 2>&1 | tee /tmp/recon.txt
#
# Ou de casa, sem copiar arquivo:
#     ssh -i ~/.ssh/coolify_localhost root@54.232.208.118 'bash -s' \
#       < scripts/reconhecimento_fontes_vps.sh | tee recon.txt

PAUSA="${PAUSA:-3}"

sonda() {
  # sonda <rótulo> <url> [metodo]
  local rotulo="$1" url="$2" metodo="${3:-GET}"
  local extra=()
  [ "$metodo" = "HEAD" ] && extra=(-I)
  printf '%-34s ' "$rotulo"
  curl -s -o /dev/null "${extra[@]}" \
    -w 'http=%{http_code}  tempo=%{time_total}s  tam=%{size_download}  tipo=%{content_type}\n' \
    --max-time 45 \
    -H 'User-Agent: Mozilla/5.0 (PACTHA/1.0 reconhecimento de fontes)' \
    "$url" || echo "FALHOU (sem resposta)"
  sleep "$PAUSA"
}

echo "== reconhecimento de fontes — $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "== IP de saída: $(curl -s --max-time 20 https://api.ipify.org || echo '?')"
echo "== host: $(hostname)  |  carga: $(uptime | sed 's/.*average/average/')"
echo

echo "-- CONTROLES POSITIVOS (fontes que já coletamos hoje; se estas falharem, o problema é a rede, não a fonte)"
sonda "che.sefaz.rs.gov.br"        "https://che.sefaz.rs.gov.br/api/Entidade/Consultar?entidadeCnpj=88488358000156"
sonda "dados.rs.gov.br (CKAN CAGE)" "https://dados.rs.gov.br/api/3/action/package_show?id=convenios-do-estado"

echo
echo "-- api-publica.*.gestao.gov.br (Comunicado nº 23/2026 do MGI) — EM PRODUÇÃO"
# ⚠️ ESTAS TRÊS SÃO A CADEIA QUE `ingestion/transferegov_te.py` FAZ TODA RODADA,
# na ordem em que ele faz: CNPJ do município -> id_beneficiario -> planos. Elas
# entraram aqui em 07/09/2026, quando a listagem da Transferência Especial trocou
# a API interna da SPA por esta — até então o script sondava a fonte que o
# produto NÃO usava mais e não sondava a que ele passou a usar.
#
# O host está atrás de Cloudflare e todas as medições da migração saíram de IP
# residencial. 403/429 aqui significa que o cron `transferegov-te` não vai
# coletar nada, e o sintoma no produto é mudo: a tabela mantém o dado velho.
sonda "TE: beneficiário por CNPJ"  "https://api-publica.transferegov.gestao.gov.br/especiais/beneficiarios-especiais?cnpj_beneficiario=88488358000156&pagina=1&tamanho_da_pagina=200"
sonda "TE: planos do beneficiário" "https://api-publica.transferegov.gestao.gov.br/especiais/planos-acao-especiais?id_beneficiario=9970&pagina=1&tamanho_da_pagina=200"
sonda "TE: plano de trabalho"      "https://api-publica.transferegov.gestao.gov.br/especiais/planos-trabalho-especiais?id_plano_acao=35239&pagina=1&tamanho_da_pagina=200"
sonda "obrasgov (uf=RS)"           "https://api-publica.obrasgov.gestao.gov.br/obras/projeto-investimento?uf_principal=RS&pagina=1&tamanho_da_pagina=1"
sonda "dumps do TransfereGov"      "https://api-publica.transferegov.gestao.gov.br/downloads/dadosgov/siconv_programa.zip" HEAD

echo
echo "-- TCE-RS (o bloqueio a reconfirmar)"
sonda "tce-rs CKAN package_show"   "https://dados.tce.rs.gov.br/api/3/action/package_show?id=licitacoes-pm-de-nova-palma"
sonda "tce-rs ZIP licitações 53100" "https://dados.tce.rs.gov.br/dados/licitacon/licitacao/orgao/53100.csv.zip" HEAD
sonda "tce-rs ZIP empenhos 2026"   "https://dados.tce.rs.gov.br/dados/municipal/empenhos/2026/53100.csv.zip" HEAD

echo
echo "-- FEDERAIS AUSENTES DO PRODUTO"
sonda "siconfi tt/rreo (SM 2024)"  "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo?an_exercicio=2024&nr_periodo=6&co_tipo_demonstrativo=RREO&no_anexo=RREO-Anexo%2001&id_ente=4316907"
sonda "ibge municipio 4313102"     "https://servicodados.ibge.gov.br/api/v1/localidades/municipios/4313102"
sonda "s2id séries históricas"     "https://s2id.mi.gov.br/paginas/series/"
sonda "portal transparência (CGU)" "https://api.portaldatransparencia.gov.br/api-de-dados/emendas?ano=2025&pagina=1"
sonda "dados.gov.br CKAN"          "https://dados.gov.br/api/3/action/package_search?q=convenios&rows=1"

echo
echo "-- RS: RECONSTRUÇÃO E TRANSPARÊNCIA ESTADUAL"
sonda "transparencia.rs dados abertos" "https://www.transparencia.rs.gov.br/dados-abertos/dados-transparencia-rs/dados/"
sonda "transparencia.rs calamidade"    "https://www.transparencia.rs.gov.br/calamidade-publica-2024/"
sonda "reconstrucao.fazenda.rs"        "https://reconstrucao.fazenda.rs.gov.br/"

echo
echo "-- DIÁRIO OFICIAL DOS MUNICÍPIOS (FAMURS/SIGPub)"
sonda "diariomunicipal famurs"     "https://www.diariomunicipal.com.br/famurs/"

echo
echo "== fim. Cole a saída inteira de volta no chat."
