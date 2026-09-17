import { redirect } from "next/navigation";

// ⭐ A TELA VIROU ABA (17/09/2026): Emendas parlamentares › Estaduais. A rota
// fica para não quebrar favorito, link salvo nem o histórico de uso.
export default function EmendasRsAntiga() {
  redirect("/dashboard/emendas-parlamentares?aba=estaduais");
}
