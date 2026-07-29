// A TV mudou de endereco: /bi/tv -> /tela (Modo Tela).
//
// Este redirect existe porque o link do quiosque pode estar COLADO na TV, num
// atalho do navegador em modo quiosque ou num favorito do gabinete. Ele preserva
// a query inteira (?kiosk=<token>&scope=...), senao a TV voltaria pedindo login.
import { redirect } from "next/navigation";

export default async function BiTvRedirect({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(sp)) {
    if (Array.isArray(v)) v.forEach((x) => qs.append(k, x));
    else if (v != null) qs.set(k, v);
  }
  const query = qs.toString();
  redirect(query ? `/tela?${query}` : "/tela");
}
