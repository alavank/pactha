// /bi/alertas, /bi/parlamentares, /bi/config -> viraram abas do /dashboard.
// /bi/tv -> virou /tela (Modo Tela). Mantemos o mapeamento para nao quebrar
// links antigos, inclusive o do quiosque colado na TV.
import { redirect } from "next/navigation";

const MAPA: Record<string, string> = {
  alertas: "/dashboard?aba=geral",
  parlamentares: "/dashboard?aba=parlamentares",
  config: "/dashboard",
};

export default async function BiRestoRedirect({
  params,
}: {
  params: Promise<{ resto?: string[] }>;
}) {
  const { resto } = await params;
  const primeiro = resto?.[0] ?? "";
  redirect(MAPA[primeiro] ?? "/dashboard");
}
