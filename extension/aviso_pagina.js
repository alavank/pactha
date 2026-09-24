// PACTHA — faixa de aviso nas telas do TransfereGov (content script, 2.4.5).
//
// ⭐ POR QUE ISTO EXISTE (24/09/2026, medido no Chrome do dono). O Chrome estava no
// "Acesso Livre" (visitante) do TransfereGov: nesse modo a porta 1 nunca pede login,
// a captura é barrada (certo) e a pessoa não sabe o que fazer. E a tela de login do
// idp tem, logo abaixo de «Entrar com gov.br», um link «Acesso livre» — a armadilha:
// quem clica ali volta a ser visitante. O popup só fala quando é aberto; a faixa
// fala ONDE a decisão é tomada.
//
// ⚠️ O QUE ELA NÃO FAZ, de propósito: não clica, não preenche, não mexe em
// formulário, não lê nem envia nada da página além do TÍTULO e do texto visível
// necessários para decidir, e não pede a permissão "scripting". Tudo em try/catch:
// o aviso nunca pode quebrar a página do governo.
(function () {
  try {
    var ID = "pactha-aviso-faixa";
    var TEXTO_LOGIN = "PACTHA: clique em «Entrar com gov.br». Não use «Acesso livre» — "
      + "visitante não conecta os servidores.";
    // ⛔ Sem mandar clicar em «Sair do Acesso Livre»: ele desloga TAMBÉM o gov.br deste
    // Chrome (medido em 24/09/2026) — e, com ele, a sessão que os servidores usam.
    // ⚠️ SÓ COM VISITANTE CONFIRMADO PELA EXTENSÃO (24/09/2026 ~16h). A conta do dono
    // não tem perfil no Discricionárias: com o login gov.br valendo, TODA página dele é
    // "Acesso Livre" — e isso não barra a captura (o /private/ do mandatárias abre). A
    // faixa só aparece com `pactha_visitante` recente, que o porteiro grava quando o
    // visitante é PURO (sem login nenhum). Com a «Captura completa» em curso, nada: o
    // roteiro segue para a porta 2, que é quem pede o login.
    var TEXTO_LIVRE = "PACTHA: este Chrome está no Acesso Livre (visitante) e SEM login gov.br — "
      + "os servidores não conectam assim. Use «Captura completa» no PACTHA e, na tela de login, "
      + "«Entrar com gov.br». Evite «Sair do Acesso Livre»: ele desliga o gov.br deste Chrome.";
    var VISITANTE_VALE_MS = 6 * 60 * 60 * 1000;   // o mesmo prazo do background/popup
    // O mesmo prazo do roteiro no background (20 min sem avançar / 60 min no total):
    // roteiro vencido que ficou no storage não acende a faixa.
    var ROTEIRO_TTL_MS = 20 * 60 * 1000;
    var ROTEIRO_MAX_MS = 60 * 60 * 1000;

    var titulo = function () {
      try { return String(document.title || ""); } catch (_) { return ""; }
    };
    /* Visitante pelo MESMO marcador da sonda (`corpoEhAcessoLivre`): o botão de saída
       dizendo "Sair do Acesso Livre". O título não decide — a página logada não foi
       medida, e o servidor já viu "Acesso Livre" no cabeçalho de sessão logada. */
    var ehAcessoLivre = function () {
      try {
        var s = document.querySelector("span.exit");
        return !!s && /^\s*sair\s+do\s+acesso\s+livre/i.test(String(s.textContent || ""));
      } catch (_) {
        return false;
      }
    };
    var roteiroAtivo = function (r) {
      if (!r) return false;
      var agora = Date.now();
      return !(agora - (r.em || 0) > ROTEIRO_TTL_MS || agora - (r.inicio || r.em || 0) > ROTEIRO_MAX_MS);
    };
    var ehTelaDeLogin = function () {
      if (/login do transferegov/i.test(titulo())) return true;
      try {
        var corpo = document.body;
        return !!corpo && /entrar com gov\.br/i.test(String(corpo.innerText || ""));
      } catch (_) {
        return false;
      }
    };

    var faixa = function (texto) {
      try {
        if (document.getElementById(ID)) return;
        var div = document.createElement("div");
        div.id = ID;
        div.setAttribute("role", "status");
        div.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:2147483647;"
          + "background:#9b2c2c;color:#fff;font:600 14px/1.4 Arial,Helvetica,sans-serif;"
          + "padding:10px 48px 10px 14px;box-shadow:0 2px 6px rgba(0,0,0,.35);text-align:left;";
        var msg = document.createElement("span");
        msg.textContent = texto;
        var fechar = document.createElement("button");
        fechar.type = "button";
        fechar.textContent = "×";
        fechar.setAttribute("aria-label", "Fechar o aviso do PACTHA");
        fechar.style.cssText = "position:absolute;top:6px;right:10px;background:transparent;"
          + "border:0;color:#fff;font:700 22px/1 Arial,sans-serif;cursor:pointer;padding:2px 6px;";
        fechar.addEventListener("click", function () {
          try { div.remove(); } catch (_) { /* página sem remove: some na próxima navegação */ }
        });
        div.appendChild(msg);
        div.appendChild(fechar);
        (document.body || document.documentElement).appendChild(div);
      } catch (_) { /* a faixa é aviso; a página segue como estava */ }
    };

    var decidir = function () {
      try {
        var livre = ehAcessoLivre();
        if (!livre && !ehTelaDeLogin()) return;
        chrome.storage.local.get(["pactha_roteiro", "pactha_visitante"], function (d) {
          try {
            var r = d && d.pactha_roteiro;
            var ativo = roteiroAtivo(r);
            if (livre) {
              var v = d && d.pactha_visitante;
              var puro = !!(v && v.quando && Date.now() - Date.parse(v.quando) < VISITANTE_VALE_MS);
              if (puro && !ativo) faixa(TEXTO_LIVRE);
              return;
            }
            // Na tela de login, só com a «Captura completa» em curso: fora dela, uma
            // faixa em todo login do TransfereGov seria ruído (e deixaria de ser lida).
            if (ativo) faixa(TEXTO_LOGIN);
          } catch (_) { /* ignore */ }
        });
      } catch (_) { /* ignore */ }
    };

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", decidir, { once: true });
    } else {
      decidir();
    }
  } catch (_) {
    /* nunca quebra a página */
  }
})();
