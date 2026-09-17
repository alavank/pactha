"use client";
// VISUALIZADOR DE DOCUMENTO — o anexo abre AQUI DENTRO, num modal.
//
// ⭐ REGRA DO DONO (16/09/2026): todo arquivo que o PACTHA mostra — anexo de
// convênio, PDF de diário oficial, foto de obra, anexo interno — abre neste
// modal, na mesma página. Sair do sistema é escolha da pessoa (o botão "Fonte
// oficial"), nunca o efeito do clique. Por isso: NADA de `window.open(blob)` nem
// `<a target=_blank>` para ARQUIVO. Link para PÁGINA de portal ("conferir no
// Obras.gov") continua em nova aba — os sites gov.br recusam iframe.
//
// ⚠️ O IFRAME APONTA PARA O `blob:`, NUNCA PARA A ROTA `/api/...`. O backend
// manda `X-Frame-Options: DENY` e `frame-ancestors 'none'` em toda resposta
// (`services/security_headers.py`), então a rota dentro de um iframe mostra a
// página de bloqueio do navegador. Buscar pelo `api` e embutir o object URL
// resolve sem afrouxar o header — e ainda traz cookie, refresh silencioso e o
// status de erro legível, que um `src` direto engoliria.
//
// O tipo sai dos BYTES, não do content-type: anexo interno guarda o `mime` que
// o navegador de quem subiu declarou, e origem de governo manda
// `application/octet-stream` para PDF. Um PDF com tipo errado vira download
// em vez de pré-visualização.
import React, { useEffect, useRef, useState } from "react";
import { Download, ExternalLink, FileWarning, Loader2, Printer } from "lucide-react";
import api from "@/lib/api";
import {
  BOTAO_SEC, ESTILO_SEC, Modal, ModalCorpo, ModalHead, Vazio,
} from "@/components/ui/superficies";

export interface DocumentoAlvo {
  titulo: string;
  /** Rota do PACTHA, relativa ao `api` (ex.: `/sismob/obra/1/foto/abc`). */
  src: string;
  sub?: React.ReactNode;
  /** Página ou arquivo na fonte oficial. Sem ela, o botão não aparece. */
  urlFonte?: string | null;
  /** Nome usado no "Baixar". Sem extensão, ela é posta pelo tipo detectado. */
  nomeArquivo?: string;
  /** Mensagem para o 403 — cada tela sabe qual caixinha de permissão pedir. */
  mensagem403?: string;
}

type Tipo = "pdf" | "imagem" | "outro";

const EXT: Record<string, string> = {
  "application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg",
  "image/gif": "gif", "image/webp": "webp",
};

/** Tipo pelos primeiros bytes. Devolve também o mime certo para recriar o blob. */
async function detectarTipo(b: Blob): Promise<{ tipo: Tipo; mime: string }> {
  const h = new Uint8Array(await b.slice(0, 12).arrayBuffer());
  const ascii = (i: number, n: number) => String.fromCharCode(...h.slice(i, i + n));
  if (ascii(0, 4) === "%PDF") return { tipo: "pdf", mime: "application/pdf" };
  if (h[0] === 0x89 && ascii(1, 3) === "PNG") return { tipo: "imagem", mime: "image/png" };
  if (h[0] === 0xff && h[1] === 0xd8 && h[2] === 0xff) return { tipo: "imagem", mime: "image/jpeg" };
  if (ascii(0, 3) === "GIF") return { tipo: "imagem", mime: "image/gif" };
  if (ascii(0, 4) === "RIFF" && ascii(8, 4) === "WEBP") return { tipo: "imagem", mime: "image/webp" };
  return { tipo: "outro", mime: b.type || "application/octet-stream" };
}

/** A mensagem do backend. O corpo de erro chega como Blob porque o pedido é
 *  blob — sem o `.text()` o `detail` some e sobra a genérica. */
async function lerErro(e: unknown, doc: DocumentoAlvo): Promise<{ msg: string; sessao: boolean }> {
  const r = (e as { response?: { data?: Blob; status?: number } })?.response;
  if (!r) return { msg: "Sem resposta do PACTHA. Confira a conexão e tente de novo.", sessao: false };
  let corpo: { detail?: unknown; motivo?: string } = {};
  try { corpo = JSON.parse((await r.data?.text()) || "{}"); } catch { /* não era JSON */ }
  const det = corpo.detail as { motivo?: string; mensagem?: string } | string | undefined;
  const motivo = corpo.motivo || (typeof det === "object" ? det?.motivo : undefined);
  if (r.status === 409 && motivo === "sessao_indisponivel") {
    return {
      msg: "O portal oficial só entrega este arquivo com a sessão gov.br, e ela está caída agora. "
         + "Abra na fonte oficial ou tente de novo depois que a sessão for recapturada.",
      sessao: true,
    };
  }
  if (r.status === 403) {
    return { msg: doc.mensagem403 || "Você não tem permissão para abrir este arquivo.", sessao: false };
  }
  const texto = typeof det === "string" ? det : typeof det === "object" ? det?.mensagem : undefined;
  return { msg: texto || `Não foi possível abrir o arquivo (HTTP ${r.status}).`, sessao: false };
}

/** Celular: o visualizador de PDF do navegador não roda dentro de iframe
 *  (Chrome Android mostra um quadro vazio, Safari iOS só a 1ª página). Lá o
 *  modal oferece Abrir/Baixar em destaque em vez de um quadro quebrado. */
function ehToque(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(pointer: coarse)").matches;
}

export function VisualizadorDocumento({ doc, onFechar, nivel = 1 }: {
  /** `null` = fechado. */
  doc: DocumentoAlvo | null;
  onFechar: () => void;
  /** 2 quando abre de dentro de outro modal (ex.: detalhe da proposta). */
  nivel?: 1 | 2;
}) {
  if (!doc) return null;
  // `key` pelo arquivo: trocar de documento com o modal aberto remonta o
  // conteúdo e o estado (blob, erro, relógio, zoom) nasce limpo.
  return <Aberto key={doc.src} doc={doc} onFechar={onFechar} nivel={nivel} />;
}

function Aberto({ doc, onFechar, nivel }: {
  doc: DocumentoAlvo; onFechar: () => void; nivel: 1 | 2;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [tipo, setTipo] = useState<Tipo>("outro");
  const [ext, setExt] = useState("");
  const [erro, setErro] = useState<{ msg: string; sessao: boolean } | null>(null);
  const [segundos, setSegundos] = useState(0);
  const [zoom, setZoom] = useState(false);
  const quadro = useRef<HTMLIFrameElement>(null);
  const src = doc.src;

  useEffect(() => {
    const ctl = new AbortController();
    let objeto: string | null = null;
    // O relógio é o que segura a pessoa num arquivo que vem do portal na hora:
    // "buscando… 7 s" diz que está andando; um spinner mudo parece travado.
    const t0 = Date.now();
    const relogio = window.setInterval(() => setSegundos(Math.floor((Date.now() - t0) / 1000)), 1000);
    api.get(src, { responseType: "blob", signal: ctl.signal })
      .then(async (r) => {
        const bruto = r.data as Blob;
        const d = await detectarTipo(bruto);
        if (ctl.signal.aborted) return;
        objeto = URL.createObjectURL(new Blob([bruto], { type: d.mime }));
        setTipo(d.tipo); setExt(EXT[d.mime] || ""); setUrl(objeto);
      })
      .catch(async (e) => {
        if (ctl.signal.aborted) return;
        setErro(await lerErro(e, doc));
      })
      .finally(() => window.clearInterval(relogio));
    // Fechar no meio cancela o download; fechar depois devolve a memória do blob.
    return () => {
      ctl.abort();
      window.clearInterval(relogio);
      if (objeto) URL.revokeObjectURL(objeto);
    };
    // `doc` inteiro fora das deps de propósito: o chamador costuma montar o
    // objeto inline, e a identidade nova a cada render refaria o download.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src]);

  const nome = (() => {
    const base = doc.nomeArquivo || doc.titulo;
    return ext && !base.toLowerCase().endsWith(`.${ext}`) ? `${base}.${ext}` : base;
  })();

  const baixar = () => {
    if (!url) return;
    const a = document.createElement("a");
    a.href = url; a.download = nome;
    document.body.appendChild(a); a.click(); a.remove();
  };

  const imprimir = () => {
    if (!url) return;
    if (tipo === "pdf" && quadro.current?.contentWindow) {
      try { quadro.current.contentWindow.focus(); quadro.current.contentWindow.print(); return; }
      catch { /* visualizador do navegador recusou — cai no iframe oculto */ }
    }
    // Imagem (ou PDF no celular, sem quadro): iframe oculto só com o arquivo.
    const f = document.createElement("iframe");
    f.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0";
    if (tipo === "imagem") {
      f.srcdoc = `<html><body style="margin:0"><img src="${url}" style="max-width:100%" onload="window.print()"></body></html>`;
    } else {
      f.src = url;
      f.onload = () => f.contentWindow?.print();
    }
    document.body.appendChild(f);
    window.setTimeout(() => f.remove(), 60_000);
  };

  const toque = ehToque();
  const acoes = (
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" className={BOTAO_SEC} style={ESTILO_SEC} onClick={baixar} disabled={!url}>
        <Download className="size-3.5" /> Baixar
      </button>
      <button type="button" className={BOTAO_SEC} style={ESTILO_SEC} onClick={imprimir}
              disabled={!url || tipo === "outro"}>
        <Printer className="size-3.5" /> Imprimir
      </button>
      {doc.urlFonte && (
        <a href={doc.urlFonte} target="_blank" rel="noopener noreferrer"
           className={BOTAO_SEC} style={ESTILO_SEC}
           title="Abre o documento no site oficial, numa nova aba">
          <ExternalLink className="size-3.5" /> Fonte oficial
        </a>
      )}
    </div>
  );

  return (
    <Modal aberto onFechar={onFechar} maxW="max-w-5xl" nivel={nivel} rotulo={doc.titulo}>
      <ModalHead titulo={doc.titulo} sub={doc.sub} onFechar={onFechar} abaixo={acoes} />
      <ModalCorpo className="flex flex-col">
        {erro ? (
          <div className="flex flex-col items-center gap-3 py-10 text-center">
            <FileWarning className="size-6" style={{ color: erro.sessao ? "var(--bi-warn-ink)" : "var(--bi-crit-ink)" }} />
            <p className="max-w-md text-[12px] leading-snug" style={{ color: "var(--bi-text)" }}>{erro.msg}</p>
          </div>
        ) : !url ? (
          <div className="flex flex-col items-center gap-2 py-16">
            <Loader2 className="size-5 animate-spin" style={{ color: "var(--bi-muted)" }} />
            <span className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
              Buscando o arquivo{segundos >= 2 ? `… ${segundos} s` : "…"}
            </span>
          </div>
        ) : tipo === "pdf" && !toque ? (
          <iframe ref={quadro} src={url} title={doc.titulo}
                  className="h-[68vh] w-full rounded-lg border"
                  style={{ borderColor: "var(--bi-line)", background: "var(--bi-surface)" }} />
        ) : tipo === "imagem" ? (
          <div className={`flex justify-center ${zoom ? "overflow-auto" : ""}`}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={url} alt={doc.titulo} onClick={() => setZoom((z) => !z)}
                 title={zoom ? "Clique para ajustar à tela" : "Clique para ver no tamanho original"}
                 className={zoom ? "max-w-none cursor-zoom-out" : "max-h-[68vh] max-w-full cursor-zoom-in object-contain"} />
          </div>
        ) : (
          <Vazio>
            {tipo === "pdf"
              ? "Neste aparelho o PDF não abre dentro da tela. Use Baixar para ver no leitor do celular."
              : "Este tipo de arquivo não tem pré-visualização. Use Baixar para abrir no seu computador."}
          </Vazio>
        )}
      </ModalCorpo>
    </Modal>
  );
}
