/* A imagem GRANDE da prévia do link — logo do PACTHA ao lado do brasão (ou da
 * logo do cliente), o nome do cliente e o endereço. Ver `lib/previa-link.ts`.
 *
 * O Next liga este arquivo sozinho ao `og:image`/`twitter:image` de TODAS as
 * rotas (é convenção de arquivo na raiz de `app/`), e o gera no `next build`:
 * não há nada dinâmico aqui, e cada tenant tem a própria imagem de frontend.
 *
 * ⚠️ 1200×630 e fundo chapado de propósito. É a proporção que o WhatsApp mostra
 * no formato grande, e o PNG precisa ficar leve (o WhatsApp desiste de imagem
 * pesada e volta para o quadradinho).
 */
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { ImageResponse } from "next/og";

import { NOME_CLIENTE, SITE_URL, SLOGAN } from "@/lib/previa-link";

export const alt = NOME_CLIENTE ? `PACTHA - ${NOME_CLIENTE}` : "PACTHA";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const ROXO = "#5B5FEF";

/** PNG de `public/` como data URI, com a largura e altura lidas do cabeçalho —
 *  o renderizador exige as duas, e esticar um brasão seria pior que não ter. */
async function png(caminho: string) {
  const buf = await readFile(join(process.cwd(), "public", caminho.replace(/^\/+/, "")));
  // Assinatura PNG (8 bytes) + tamanho/tipo do IHDR (8): largura e altura em 16..24.
  const largura = buf.readUInt32BE(16);
  const altura = buf.readUInt32BE(20);
  return { src: `data:image/png;base64,${buf.toString("base64")}`, largura, altura };
}

/** Cabe a imagem numa caixa sem deformar. */
function caber(largura: number, altura: number, maxL: number, maxA: number) {
  const k = Math.min(maxL / largura, maxA / altura);
  return { width: Math.round(largura * k), height: Math.round(altura * k) };
}

export default async function Imagem() {
  const pactha = await png("/pactha-logo.png");
  const logoCliente = (process.env.NEXT_PUBLIC_CLIENT_LOGO || "").trim();
  let cliente: Awaited<ReturnType<typeof png>> | null = null;
  if (/\.png$/i.test(logoCliente)) {
    try {
      cliente = await png(logoCliente);
    } catch {
      cliente = null; // sem a logo, a prévia sai só com o PACTHA — não quebra o build
    }
  }
  const dominio = SITE_URL.replace(/^https?:\/\//, "").replace(/\/+$/, "");
  const tamPactha = caber(pactha.largura, pactha.altura, cliente ? 440 : 640, 140);
  const tamCliente = cliente ? caber(cliente.largura, cliente.altura, 420, 250) : null;

  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column",
                    background: "#FFFFFF" }}>
        <div style={{ flex: 1, display: "flex", flexDirection: "column",
                      alignItems: "center", justifyContent: "center", padding: "40px 64px 0" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center",
                        height: 270 }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={pactha.src} width={tamPactha.width} height={tamPactha.height} alt="" />
            {cliente && tamCliente && (
              <div style={{ display: "flex", alignItems: "center" }}>
                <div style={{ width: 3, height: 190, background: "#E4E4F4",
                              margin: "0 56px" }} />
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={cliente.src} width={tamCliente.width} height={tamCliente.height} alt="" />
              </div>
            )}
          </div>
          {NOME_CLIENTE && (
            <div style={{ display: "flex", marginTop: 26, fontSize: 68, color: "#14142B",
                          letterSpacing: -1 }}>
              {NOME_CLIENTE}
            </div>
          )}
          <div style={{ display: "flex", marginTop: 10, fontSize: 32, color: "#5A5A72" }}>
            {SLOGAN}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center",
                      height: 78, marginTop: 34, background: ROXO, color: "#FFFFFF",
                      fontSize: 30, letterSpacing: 0.5 }}>
          {dominio || "PACTHA"}
        </div>
      </div>
    ),
    size,
  );
}
