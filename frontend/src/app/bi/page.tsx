// Rota antiga do Painel de Indicadores. O painel foi FUNDIDO ao menu Dashboard
// (nao fazia sentido ter dois menus para o mesmo publico), entao /bi e tudo que
// vinha embaixo dele agora leva para /dashboard. Fica como redirect permanente
// para nao quebrar link salvo, favorito ou atalho na TV.
import { redirect } from "next/navigation";

export default function BiRedirect() {
  redirect("/dashboard");
}
