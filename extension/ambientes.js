// AMBIENTES — a lista de tenants e o envio da MESMA captura para todos.
//
// ⭐ POR QUE ISTO EXISTE. A extensão guardava UM `pactha_api` e UM
// `pactha_token`. Como cada tenant tem banco e Cofre próprios e não há
// propagação entre eles, capturar a sessão gov.br significava reconfigurar a
// extensão e recapturar CINCO vezes — um ritual que ninguém completa.
//
// Em 02/09/2026 isso cobrou a conta: a sessão caiu, o dono recapturou uma vez, e
// o resultado foi 1 de 5 conectados. Freitas reconectou; trust e montesião
// ficaram em `needs_recapture`; santamaria e novapalma apareceram com "sem
// sessao govbr no Cofre" — NUNCA tinham sido capturados. O novapalma estava no
// ar desde 01/09.
//
// ⚠️ E O MODO DE FALHA ERA SILENCIOSO, que é o que torna isto urgente: capturar
// num ambiente e esquecer os outros não dá erro em lugar nenhum. As coletas
// atrás de login simplesmente param, e o produto leva semanas para reclamar —
// uma sessão já ficou morta 41% de um mês sem nada acusar.
//
// Decisão do dono (02/09/2026): "não faz sentido uma captura para cada um, tem
// que ser uma só".

/* ⚠️ `municipio_id: 0` É O PONTO MAIS IMPORTANTE DESTE ARQUIVO.
 *
 * O ID de município é LOCAL de cada tenant: o `6` do freitas é uma cidade e o
 * `6` do trust é outra. Mandar o mesmo número para os cinco amarraria a sessão
 * a uma cidade diferente em cada banco — e ninguém veria, porque o POST
 * responde 200 do mesmo jeito.
 *
 * O backend trata `None`/`0` como ESCOPO DE INSTÂNCIA (ver
 * `routers/session_capture.py`), e é o escopo correto: a sessão gov.br é do
 * operador, não de um município, e o próprio backend diz que ela "serve
 * cross-mun". Por isso a captura multi-ambiente NUNCA manda id de município. */
const AMBIENTE_ESCOPO_INSTANCIA = 0;

// Os cinco tenants em produção (02/09/2026). O `token` nasce vazio: ele é
// PRÓPRIO de cada ambiente (os service tokens vivem no banco de cada um) e é
// colado pela tela de configuração.
// ⚠️ Toda URL aqui precisa casar com `host_permissions` no manifest.json —
// fora dele o Chrome bloqueia o fetch ANTES de sair (MV3) e a captura falha sem
// nunca chegar ao servidor. `https://*.sslip.io/*` cobre os cinco.
const AMBIENTES_CONHECIDOS = [
  { nome: "Freitas", api: "https://pactha-api-54-232-208-118.sslip.io/api" },
  { nome: "Trust", api: "https://pactha-trust-api-54-232-208-118.sslip.io/api" },
  { nome: "Monte Sião - MG", api: "https://pactha-montesiao-mg-api-54-232-208-118.sslip.io/api" },
  { nome: "Santa Maria - RS", api: "https://pactha-santamaria-rs-api-54-232-208-118.sslip.io/api" },
  { nome: "Nova Palma - RS", api: "https://pactha-novapalma-rs-api-54-232-208-118.sslip.io/api" },
];

/** A lista salva, já migrada do formato antigo.
 *
 * ⚠️ A MIGRAÇÃO NÃO PODE PERDER O TOKEN QUE JÁ FUNCIONAVA. Quem já usa a
 * extensão tem `pactha_api` + `pactha_token` gravados; se a lista nova nascesse
 * vazia, a pessoa abriria o popup e descobriria que a extensão "esqueceu" a
 * configuração — e provavelmente reconfiguraria só um ambiente, que é
 * exatamente o problema que este arquivo veio resolver.
 */
async function lerAmbientes() {
  const dados = await new Promise((res) =>
    chrome.storage.local.get(["pactha_ambientes", "pactha_api", "pactha_token"], res));

  if (Array.isArray(dados.pactha_ambientes) && dados.pactha_ambientes.length) {
    return dados.pactha_ambientes;
  }

  // Primeira vez com a versão nova: monta a lista dos conhecidos e leva o token
  // antigo para o ambiente cuja API bate com a que estava configurada.
  const apiAntiga = (dados.pactha_api || "").replace(/\/+$/, "");
  const tokenAntigo = dados.pactha_token || "";
  const lista = AMBIENTES_CONHECIDOS.map((a) => ({
    ...a,
    token: apiAntiga && a.api.replace(/\/+$/, "") === apiAntiga ? tokenAntigo : "",
    ativo: true,
  }));
  // API antiga que não é nenhuma das conhecidas (ambiente próprio, teste): não
  // se perde — entra como uma entrada a mais.
  if (apiAntiga && !AMBIENTES_CONHECIDOS.some((a) => a.api.replace(/\/+$/, "") === apiAntiga)) {
    lista.push({ nome: "Configurado antes", api: dados.pactha_api, token: tokenAntigo, ativo: true });
  }
  await salvarAmbientes(lista);
  return lista;
}

async function salvarAmbientes(lista) {
  return new Promise((res) => chrome.storage.local.set({ pactha_ambientes: lista }, res));
}

/** Manda o MESMO payload para todos os ambientes com token configurado.
 *
 * Devolve uma linha por ambiente: `{ nome, ok, detalhe }`.
 *
 * ⚠️ NUNCA DEVOLVE UM "OK" ÚNICO, e essa é a regra central. O defeito que este
 * arquivo conserta é justamente o sucesso parcial invisível: três ambientes
 * gravando e dois falhando tem de aparecer como três e dois, nomeados. Um
 * resumo agregado ("enviado!") reproduziria o problema com outra roupa.
 *
 * ⚠️ AMBIENTE SEM TOKEN NÃO É ERRO DE REDE — é configuração faltando, e a
 * mensagem diz isso. Tratar os dois como "falhou" mandaria a pessoa investigar
 * conectividade quando o que falta é colar uma chave.
 */
async function enviarParaTodos(payload, lista) {
  const alvos = (lista || []).filter((a) => a.ativo !== false);
  if (!alvos.length) return [];

  // ⚠️ O `municipio_id` do payload é IGNORADO de propósito — ver o comentário
  // de `AMBIENTE_ESCOPO_INSTANCIA` no topo. Sobrescrever aqui, e não no
  // chamador, garante que nenhuma tela futura consiga reintroduzir o id local.
  const corpo = JSON.stringify({ ...payload, municipio_id: AMBIENTE_ESCOPO_INSTANCIA });

  return Promise.all(alvos.map(async (amb) => {
    if (!amb.token) {
      return { nome: amb.nome, ok: false, detalhe: "sem token configurado" };
    }
    // Token longevo (service token) vai como X-Service-Token — não expira em
    // 60min como o JWT. Aceita os dois prefixos: os antigos usavam `pacta_`
    // (sem H) e cairiam no caminho do Bearer, resultando em 401.
    const ehServiceToken = amb.token.startsWith("pactha_") || amb.token.startsWith("pacta_");
    const auth = ehServiceToken
      ? { "X-Service-Token": amb.token }
      : { Authorization: `Bearer ${amb.token}` };
    try {
      const r = await fetch(`${amb.api}/session-capture`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...auth },
        body: corpo,
      });
      if (r.status === 401) return { nome: amb.nome, ok: false, detalhe: "token inválido" };
      if (!r.ok) return { nome: amb.nome, ok: false, detalhe: `HTTP ${r.status}` };
      const d = await r.json().catch(() => ({}));
      return { nome: amb.nome, ok: true, detalhe: d.id ? `id=${d.id}` : "gravado" };
    } catch (e) {
      // ⚠️ "Failed to fetch" aqui quase sempre é host_permissions, e não rede:
      // o Chrome bloqueia o fetch antes de sair e a mensagem não diz isso.
      const msg = String(e && e.message || e);
      return {
        nome: amb.nome, ok: false,
        detalhe: /failed to fetch/i.test(msg)
          ? "bloqueado (confira host_permissions no manifest)"
          : msg.slice(0, 60),
      };
    }
  }));
}

/** "3 de 5 ambientes" — o resumo que acompanha a lista, nunca a substitui. */
function resumoEnvio(resultados) {
  const ok = resultados.filter((r) => r.ok).length;
  return `${ok} de ${resultados.length} ambiente(s)`;
}
