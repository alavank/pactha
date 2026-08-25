/** Download do relatório de «Vigências a vencer» — PDF ou Excel.
 *
 *  Mora em `lib/` e não dentro do modal pelo motivo que `rmExport.ts` já
 *  documenta: a função de download do RM era byte a byte idêntica em duas telas
 *  e uma delas já foi esquecida numa mudança. Aqui há um chamador só hoje — o
 *  segundo (uma tela de vigências fora do Painel, por exemplo) encontra a função
 *  pronta em vez de copiar.
 */
import api from "@/lib/api";

export type FormatoVigencias = "pdf" | "xlsx";

const MIME_XLSX =
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

/** Nome do arquivo vindo do `Content-Disposition` (o backend é quem sabe a
 *  regra: `vigencias_120d_2026-08-25.xlsx`). Funciona mesmo cross-origin porque
 *  `backend/main.py` lista o cabeçalho em `expose_headers`. */
function nomeDoCabecalho(r: Response, alternativa: string): string {
  const cd = r.headers.get("content-disposition") || "";
  const m = /filename="?([^";]+)"?/i.exec(cd);
  return m ? m[1].trim() : alternativa;
}

export async function baixarVigencias(opts: {
  dias: number;
  /** Nomes selecionados no MultiSelect. Vazio = todos (o backend entende assim). */
  municipios: string[];
  ordem: "asc" | "desc";
  formato: FormatoVigencias;
}): Promise<void> {
  const { dias, municipios, ordem, formato } = opts;
  const qs = new URLSearchParams();
  qs.set("dias", String(dias));
  qs.set("ordem", ordem);
  qs.set("formato", formato);
  // ⚠️ `append` numa chave repetida, NÃO `set` com vírgulas. O FastAPI declara
  // `municipios: list[str] = Query(default=[])`, que lê `?municipios=A&municipios=B`;
  // uma string "A,B" chegaria como UM município chamado "A,B" e o arquivo sairia
  // vazio — sem erro nenhum, que é o pior jeito de errar.
  municipios.forEach((m) => qs.append("municipios", m));

  const url = `${api.defaults.baseURL}/export-pdf/vigencias?${qs.toString()}`;
  const token = localStorage.getItem("pactha_token");
  let href = "";
  try {
    const r = await fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    // Sem esta checagem um 403 viraria "arquivo": o PDF abriria uma aba com o
    // JSON do erro e o Excel salvaria uma planilha corrompida — e o usuário
    // culparia o Excel, não o PACTHA.
    if (!r.ok) {
      alert(
        r.status === 403
          ? "Você não tem permissão para exportar as vigências."
          : `Não foi possível gerar o arquivo (HTTP ${r.status}).`,
      );
      return;
    }
    // ⚠️ SKEW ENTRE BACKEND E FRONTEND. Os dois deployam por workflows
    // independentes e o laço de deploy do backend usa `continue` quando um
    // tenant falha — a janela em que o frontend novo fala com o backend velho
    // pode durar horas num tenant. Nela este endpoint ainda não existe (404, já
    // tratado acima) ou, num backend intermediário, devolveria outra coisa com
    // 200. A checagem do tipo fecha esse caso.
    const ct = (r.headers.get("content-type") || "").toLowerCase();
    const esperado = formato === "xlsx" ? "spreadsheetml" : "pdf";
    if (!ct.includes(esperado)) {
      alert(
        "Este ambiente ainda não foi atualizado para esta exportação " +
        "(o servidor devolveu outro formato). Tente de novo em alguns minutos.",
      );
      return;
    }
    const blob = await r.blob();
    href = URL.createObjectURL(blob);
    if (formato === "xlsx") {
      // O navegador não renderiza .xlsx: `window.open` de um blob assim abre aba
      // em branco ou salva arquivo sem nome. Precisa da âncora com `download`.
      const a = document.createElement("a");
      a.href = href;
      a.download = nomeDoCabecalho(r, "vigencias.xlsx");
      a.type = MIME_XLSX;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } else {
      // PDF abre em aba — o comportamento que o dono já conhece do RM.
      window.open(href, "_blank");
    }
  } catch (e) {
    console.error(e);
    alert("Erro ao gerar o arquivo de vigências.");
  } finally {
    // Revogar na hora cancelaria o download/aba que acabou de começar; o atraso
    // dá folga e ainda assim fecha o vazamento.
    if (href) window.setTimeout(() => URL.revokeObjectURL(href), 60_000);
  }
}
