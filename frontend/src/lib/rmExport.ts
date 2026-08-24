/** Download do relatório RM (PDF ou Word) — usado pela LISTA e pelo DETALHE.
 *
 *  ⚠️ EXISTE PARA NÃO HAVER DUAS CÓPIAS. Até aqui a função `exportar` era
 *  byte a byte idêntica em `dashboard/rm/page.tsx` e `dashboard/rm/[id]/page.tsx`,
 *  e uma das duas já foi esquecida em mudança anterior. Com o download morando
 *  aqui, uma tela não pode divergir da outra.
 */
import api from "@/lib/api";

export type TipoRm = "completo" | "resumido";
/** ⚠️ ERA `"pdf"` — uma união de UM membro só. Passar "docx" era erro de TS, e
 *  `next.config.ts` não tem `ignoreBuildErrors`: quebraria o build dos 4 tenants. */
export type FormatoRm = "pdf" | "docx";

const TIPO_MIME_DOCX =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

/** Nome do arquivo vindo do `Content-Disposition`.
 *
 *  Dá para ler mesmo sendo `fetch` cross-origin porque o backend lista esse
 *  cabeçalho em `expose_headers` (backend/main.py). Assim a regra do nome
 *  (`RM-Completo-Monte_Siao-01-07-2026.docx`) fica num lugar só: no servidor.
 *  Sem `decodeURIComponent` de propósito — o backend escreve o nome cru, sem
 *  percent-encoding, e decodificar um `%` solto lançaria exceção. */
function nomeDoCabecalho(r: Response, alternativa: string): string {
  const cd = r.headers.get("content-disposition") || "";
  const m = /filename="?([^";]+)"?/i.exec(cd);
  return m ? m[1].trim() : alternativa;
}

/** Busca o relatório e entrega ao usuário.
 *
 *  PDF continua abrindo em aba (`window.open`), que é o comportamento que o dono
 *  já conhece. WORD **baixa**: o navegador não renderiza .docx, e um
 *  `window.open` de blob .docx abre aba em branco ou salva um arquivo sem nome.
 *  Por isso a âncora com `download`.
 *
 *  ⚠️ O `Content-Disposition: attachment` que o backend manda NÃO chega ao
 *  usuário: o conteúdo vem por `fetch` e vira `blob`, e o blob não carrega
 *  cabeçalho nenhum. Quem nomeia o arquivo é o `a.download` daqui. */
export async function baixarRelatorioRm(
  id: number | string,
  tipo: TipoRm,
  formato: FormatoRm = "pdf",
): Promise<void> {
  const url = `${api.defaults.baseURL}/rm/${id}/pdf?tipo=${tipo}&formato=${formato}`;
  const token = localStorage.getItem("pactha_token");
  let href = "";
  try {
    const r = await fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    // ⚠️ Sem esta checagem um 400/403 virava "arquivo": no PDF abria uma aba com
    // o JSON de erro; no Word o usuário salvaria um .docx corrompido e
    // reclamaria do Word, não do PACTHA.
    if (!r.ok) {
      alert(`Não foi possível gerar o relatório (HTTP ${r.status}).`);
      return;
    }
    // ⚠️ SKEW ENTRE BACKEND E FRONTEND. Os dois deployam por workflows
    // INDEPENDENTES (o próprio build-frontend.yml declara "SKEW ACEITO"), e o
    // laço de deploy do backend usa `continue` quando um tenant falha — a janela
    // em que o frontend novo conversa com o backend velho pode durar horas num
    // tenant. Nela, `?formato=docx` volta um PDF com HTTP 200, e sem esta
    // checagem o usuário salvaria um ".docx" que é PDF por dentro e culparia o
    // Word por não abrir.
    const ct = (r.headers.get("content-type") || "").toLowerCase();
    if (formato === "docx" && !ct.includes("wordprocessingml")) {
      alert(
        "Este ambiente ainda não foi atualizado para o export em Word " +
        "(o servidor devolveu PDF). Tente de novo em alguns minutos.",
      );
      return;
    }
    const blob = await r.blob();
    href = URL.createObjectURL(blob);
    if (formato === "docx") {
      const a = document.createElement("a");
      a.href = href;
      a.download = nomeDoCabecalho(r, `RM-${tipo}.docx`);
      a.type = TIPO_MIME_DOCX;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } else {
      window.open(href, "_blank");
    }
  } catch (e) {
    console.error(e);
    alert("Erro ao gerar o relatório.");
  } finally {
    // Revogar na hora cancelaria o download/aba que acabou de começar; o atraso
    // dá folga e ainda assim fecha o vazamento que existia (o código antigo
    // nunca chamava `revokeObjectURL`).
    if (href) window.setTimeout(() => URL.revokeObjectURL(href), 60_000);
  }
}
