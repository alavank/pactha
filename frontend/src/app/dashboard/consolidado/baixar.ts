import api from "@/lib/api";

/** Baixa um arquivo do backend com o token e os cookies da sessão, pelo mesmo
 *  caminho do PDF da tela Parlamentares: o axios não entrega o arquivo como um
 *  blob navegável. Lança erro com o status HTTP — 403 é "sem a caixinha
 *  Exportar do Consolidado", e a tela diz isso. */
export async function baixarArquivo(caminho: string, nomeArquivo: string): Promise<void> {
  const token = localStorage.getItem("pactha_token");
  const res = await fetch(`${api.defaults.baseURL}${caminho}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    credentials: "include",
  });
  if (!res.ok) throw new Error(String(res.status));
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = nomeArquivo;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

export function mensagemDeErro(e: unknown): string {
  return e instanceof Error && e.message === "403"
    ? "Você não tem a permissão de exportar o Consolidado. Peça ao administrador em Usuários."
    : "Não foi possível gerar o arquivo. Tente de novo.";
}
