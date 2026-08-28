"use client";
// Identidade visual compartilhada: a MARCA (PACTHA) e o ENTE ATENDIDO (brasão +
// nome da cidade). Vive num arquivo só porque aparece em quatro lugares — Painel
// de Indicadores, Modo Tela, link público e sidebar — e três desses precisam
// ficar idênticos por definição: são a mesma tela em superfícies diferentes.
//
// Regra combinada com o usuário:
//   - a logo do PACTHA anda SOZINHA (sem o brasão colado nela);
//   - o brasão anda junto do NOME DA CIDADE, como título do ente atendido.
// Antes os dois viviam grudados num chip no topo da sidebar, o que misturava
// quem é o fornecedor com quem é o cliente.

/** Assinatura do produto. Igual para todo tenant, então não é env var. */
export const SUBTITULO_PACTHA =
  "Captação de Recursos | Convênios | Transferências Governamentais";

/** Brasão/logo do cliente, embutido no build por tenant (build-arg do CI). */
export const CLIENT_LOGO = process.env.NEXT_PUBLIC_CLIENT_LOGO || "";

/** AJUSTES POR ARTE. Os brasões (Monte Sião, Santa Maria) são quase quadrados,
 *  coloridos e de peso centrado: o alinhamento padrão serve. A logo do Freitas
 *  não, em dois pontos:
 *
 *  - é PNG transparente com letras azul-marinho e some sobre o fundo escuro —
 *    ganha fundo claro só nesse tema (`.logo-cliente-fundo-claro`, globals.css);
 *  - o PESO VISUAL dela fica no terço de cima ("FREITAS" grande em cima,
 *    "& ASSOCIADOS" fino embaixo, e a cauda do leão no canto inferior). O
 *    `items-center` alinha o centro GEOMÉTRICO da imagem ao centro do nome da
 *    cidade, e o "FREITAS" saía acima da linha do nome — o dono viu a logo
 *    "meio pra cima". Medido no arquivo (28/08/2026, 998×354): o centro de
 *    massa do alfa está a 36% da altura; deslocar a imagem 14% da própria
 *    altura para baixo põe o "FREITAS" na linha do nome. ⚠️ Se a arte for
 *    recortada de novo, medir de novo (centro de massa do canal alfa).
 *
 *  Só ao lado do nome (`EnteAtendido`); no login a logo fica sozinha, centrada
 *  numa coluna, e não há o que alinhar. */
const AJUSTE_LOGO = /freitas/i.test(CLIENT_LOGO)
  ? { classe: "logo-cliente-fundo-claro", deslocamento: "14%" }
  : { classe: "", deslocamento: undefined };
export const CLIENT_LOGO_CLASSE = AJUSTE_LOGO.classe;

/** Nome do cliente embutido no build — usado só como último recurso, quando a
 *  API ainda não respondeu (o nome real vem de /api/municipios). */
export const CLIENT_SUBTITLE = process.env.NEXT_PUBLIC_CLIENT_SUBTITLE || "";

/**
 * Marca do produto: logo do PACTHA + assinatura embaixo.
 * É o "Dashboard PACTHA" do cabeçalho — a logo faz o papel do título, então não
 * repetimos a palavra em texto ao lado dela.
 */
export function MarcaPactha({
  className = "",
  compacta,
}: {
  className?: string;
  compacta?: boolean;
}) {
  const alt = compacta ? "h-5 w-auto object-contain" : "h-7 w-auto object-contain";
  return (
    <div className={`flex flex-col items-center leading-tight ${className}`}>
      {/* Duas artes, uma escondida por CSS (ver globals.css). A do escuro tem a
          PALAVRA em branco e o SÍMBOLO na cor original — a logo original é
          tinta preta e desaparecia no fundo escuro. Trocar por CSS em vez de
          por estado React evita piscar a arte errada na primeira pintura. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/pactha-logo.png" alt="PACTHA" className={`marca-clara ${alt}`} />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/pactha-logo-dark.png" alt="PACTHA" className={`marca-escura ${alt}`} />
      <span
        className={`mt-1 text-center ${compacta ? "text-[9px]" : "text-[10px]"}`}
        style={{ color: "var(--bi-faint, currentColor)", opacity: 0.75 }}
      >
        {SUBTITULO_PACTHA}
      </span>
    </div>
  );
}

/**
 * Cabeçalho do Painel de Indicadores: ente à esquerda, marca ao centro,
 * controles à direita. É o MESMO arranjo do Modo Tela e do link público — de
 * propósito, para as três superfícies não divergirem com o tempo.
 */
export function CabecalhoBi({
  nomeMunicipio,
  legenda,
  right,
}: {
  nomeMunicipio?: string | null;
  legenda?: string;
  right?: React.ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-3">
      <div className="flex min-w-0 flex-col">
        <EnteAtendido nome={nomeMunicipio} />
        {legenda && (
          <span className="mt-0.5 truncate text-[12px]" style={{ color: "var(--bi-muted)" }}>
            {legenda}
          </span>
        )}
      </div>
      <MarcaPactha className="order-last w-full sm:order-none sm:mx-auto sm:w-auto" />
      {right && <div className="ml-auto flex flex-wrap items-center gap-2">{right}</div>}
    </div>
  );
}

/**
 * Ente atendido: brasão + nome, em linha, com peso de título.
 * `nome` vem da API quando disponível; sem ela, cai no valor do build.
 */
export function EnteAtendido({
  nome,
  className = "",
  tamanho = "grande",
}: {
  nome?: string | null;
  className?: string;
  tamanho?: "grande" | "medio";
}) {
  const rotulo = nome || CLIENT_SUBTITLE || "—";
  const grande = tamanho === "grande";
  return (
    <div className={`flex min-w-0 items-center gap-2.5 ${className}`}>
      {CLIENT_LOGO && (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img
          src={CLIENT_LOGO}
          alt=""
          aria-hidden
          /* ⚠️ `max-w-[120px]`, era 52. Mesmo defeito que a caixa do logo no RM
             tinha: `object-contain` nunca corta — ele ENCOLHE —, e um logo largo
             batia no teto de largura e descia a altura junto. O do Freitas é
             2,80:1: a `h-8` ele precisa de ~90px e era espremido a 52, saindo com
             18px de altura em vez de 32. Não sumia nada, só ficava pequeno demais
             para ler o "& ASSOCIADOS".

             Como no RM, alargar o teto NÃO mexe em quem já estava certo: brasão
             quase quadrado ocupa ~32px de largura e nunca chegou perto do limite.
             120px cobre 2,80:1 nos dois tamanhos (h-10 pede 112px).

             O custo é honesto: o nome do município ao lado tem menos espaço. Ele
             está sob `min-w-0` + `truncate`, então encurta em vez de estourar o
             layout. */
          className={`${grande ? "h-10" : "h-8"} w-auto max-w-[120px] shrink-0 object-contain ${CLIENT_LOGO_CLASSE}`}
          /* O deslocamento óptico é em % da PRÓPRIA altura (transform), então
             vale igual no h-10 do cabeçalho e no h-8 da barra lateral. */
          style={AJUSTE_LOGO.deslocamento ? { transform: `translateY(${AJUSTE_LOGO.deslocamento})` } : undefined}
        />
      )}
      <span
        className={`truncate font-bold ${grande ? "text-[20px] sm:text-[24px]" : "text-[15px]"}`}
        title={rotulo}
      >
        {rotulo}
      </span>
    </div>
  );
}
