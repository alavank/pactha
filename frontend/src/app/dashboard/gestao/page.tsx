"use client";

import React, { useEffect, useState, useCallback, useMemo } from "react";
import { Edit2, Eraser, FileText, Paperclip } from "lucide-react";
import api from "@/lib/api";
// A cópia local desta função lia data pura como UTC e mostrava o dia anterior —
// o mesmo campo que o modal de anotação exibe, na mesma tela.
import { formatDataCurta as fmtData } from "@/lib/bi-format";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { Button } from "@/components/ui/button";
import {
  Campos,
  ItemLinha,
  Lista,
  Numero,
  Selo,
  Vazio,
  situacaoTom,
} from "@/components/ui/superficies";
import AnotacaoModal from "@/components/AnotacaoModal";
import AvisoEscopo from "@/components/AvisoEscopo";
import { contarSemEscrita } from "@/lib/escopo";
import { TituloTela } from "@/components/TituloTela";

interface Anotacao {
  id: number;
  municipio_id: number;
  fonte: string;
  fonte_ref: string;
  numero_referencia?: string;
  status_interno?: string | null;
  status_custom?: string | null;
  protocolo?: string | null;
  data_protocolo?: string | null;
  observacoes?: string | null;
  anexos: Array<{ nome: string; mime: string; tamanho?: number }>;
  updated_at?: string;
  /** O veredito do servidor sobre ESTA anotação — ver `lib/escopo.ts`.
   *
   *  Aqui ele não esconde botão nenhum: esta lista não tem botão de editar, ela
   *  ABRE a anotação. Quem esconde é o modal (`AnotacaoModal`), que é onde os
   *  botões estão. O campo serve à frase que explica isso antes do clique. */
  pode_editar?: boolean | null;
  pode_excluir?: boolean | null;
}

const FONTE_LABEL: Record<string, string> = {
  sigcon: "SIGCON (Estadual)",
  voluntaria: "Voluntária (SICONV)",
  plano_acao: "Plano de Ação (TG Especial)",
  fns: "FNS",
  simec: "SIMEC",
  emenda: "Emenda Estadual",
  rm: "Item de RM",
};

/** Versão curta para o selo do cartão. O rótulo completo continua acessível no
 *  `title` e é o que aparece no filtro — "Plano de Ação (TG Especial)" dentro de
 *  um selo de 10px empurraria o resto da meta para a linha de baixo. */
const FONTE_CURTA: Record<string, string> = {
  sigcon: "SIGCON",
  voluntaria: "SICONV",
  plano_acao: "Plano de Ação",
  fns: "FNS",
  simec: "SIMEC",
  emenda: "Emenda",
  rm: "RM",
};

// O mapa FONTE_COLOR (violeta/azul/verde/amarelo por fonte) foi removido: sete
// fontes, sete cores, e a cor deixava de significar "olhe aqui" para significar
// apenas "esta linha existe". A fonte é uma CLASSIFICAÇÃO, não um alerta — vai
// em selo cinza. A única cor que sobra na tela é a do status, e ela vem de
// `situacaoTom`, a regra única do sistema.

/* Escolha nativa com os tokens da identidade — o MESMO desenho que as telas de
   RM e do Cofre já usam. Repetido aqui como constante (e não copiado inline nos
   dois <select>) para os dois filtros não poderem divergir um do outro. */
const SELECT_CLS = "h-9 rounded-md border px-3 text-[13px]";
const SELECT_ESTILO: React.CSSProperties = {
  borderColor: "var(--bi-line)",
  background: "var(--bi-surface)",
  color: "var(--bi-text)",
};



export default function GestaoPage() {
  const { municipioId } = useMunicipio();

  const [items, setItems] = useState<Anotacao[]>([]);
  const [loading, setLoading] = useState(false);
  const [filtroFonte, setFiltroFonte] = useState<string>("");
  const [filtroStatus, setFiltroStatus] = useState<string>("");
  const [statusOpcoes, setStatusOpcoes] = useState<string[]>([]);
  const [openItem, setOpenItem] = useState<Anotacao | null>(null);

  const carregar = useCallback(async () => {
    if (!municipioId) return;
    setLoading(true);
    try {
      const params: Record<string, string> = { municipio_id: municipioId };
      if (filtroFonte) params.fonte = filtroFonte;
      if (filtroStatus) params.status = filtroStatus;
      const r = await api.get<{ items: Anotacao[] }>("/gestao/anotacoes", { params });
      setItems(r.data.items);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  }, [municipioId, filtroFonte, filtroStatus]);

  useEffect(() => { carregar(); }, [carregar]);

  useEffect(() => {
    api.get<{ opcoes: string[] }>("/gestao/status-opcoes")
      .then((r) => setStatusOpcoes(r.data.opcoes)).catch(() => {});
  }, []);

  // A barra "N anotação(ões)" virou KPI. Protocolo e anexo são o que distingue
  // uma anotação de rascunho de uma com lastro (foi protocolada / tem o PDF
  // junto), e essa contagem era a pergunta que o gestor fazia contando na tela.
  const resumo = useMemo(() => ({
    total: items.length,
    comProtocolo: items.filter((a) => !!a.protocolo).length,
    comAnexo: items.filter((a) => (a.anexos?.length ?? 0) > 0).length,
  }), [items]);

  const filtrando = !!(filtroFonte || filtroStatus);

  if (!municipioId) {
    // `<Vazio>` e não um `text-muted-foreground` solto: é o mesmo estado vazio
    // de CAUC, SISMOB e Sessões. `text-muted-foreground` é do tema antigo e não
    // acompanha os tokens `--bi-*`.
    return <Vazio>Selecione um município para ver as anotações.</Vazio>;
  }

  return (
    <div className="space-y-4">
      <div className="border-b pb-4" style={{ borderColor: "var(--bi-line)" }}>
        <TituloTela>Gestão Interna</TituloTela>
        <p className="mt-1 max-w-3xl text-sm leading-snug" style={{ color: "var(--bi-muted)" }}>
          Anotações paralelas aos dados oficiais. Marque status próprio (ex: &quot;prestação enviada
          fisicamente&quot;), protocolos, datas, observações e anexe PDFs/imagens sem alterar
          os dados brutos do scraper.
        </p>
      </div>

      <div className="grid gap-2 sm:grid-cols-3">
        <Numero
          icon={Edit2}
          rotulo="Anotações"
          valor={resumo.total}
          sub={filtrando ? "no recorte filtrado" : "todas as fontes"}
        />
        <Numero icon={FileText} rotulo="Com protocolo" valor={resumo.comProtocolo} />
        <Numero icon={Paperclip} rotulo="Com anexo" valor={resumo.comAnexo} />
      </div>

      {/* Filtros soltos, sem a moldura cinza de antes.
          O <select> usa o desenho que RM e Cofre já fixaram para escolha nativa
          (h-9 / rounded-md / 13px sobre os tokens `--bi-*`), e não as classes do
          MultiSelect: o MultiSelect nem aparece nesta tela, e `base-300` aponta
          para `--bi-line` no claro mas para `--bi-line-strong` no escuro — o
          mesmo controle ficava com borda diferente da do Cofre no tema escuro. */}
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor="filtro-fonte" className="mb-1 block text-[11px]" style={{ color: "var(--bi-muted)" }}>
            Fonte
          </label>
          <select
            id="filtro-fonte"
            value={filtroFonte} onChange={(e) => setFiltroFonte(e.target.value)}
            className={SELECT_CLS}
            style={SELECT_ESTILO}
          >
            <option value="">Todas</option>
            {Object.entries(FONTE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="filtro-status" className="mb-1 block text-[11px]" style={{ color: "var(--bi-muted)" }}>
            Status
          </label>
          <select
            id="filtro-status"
            value={filtroStatus} onChange={(e) => setFiltroStatus(e.target.value)}
            className={SELECT_CLS}
            style={SELECT_ESTILO}
          >
            <option value="">Todos</option>
            {statusOpcoes.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <Button variant="outline" onClick={() => { setFiltroFonte(""); setFiltroStatus(""); }}>
          <Eraser className="size-4 mr-1" /> Limpar
        </Button>
      </div>

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            /* `--bi-surface-2`, não `bg-base-200`: base-200 aponta para
               `--bi-bg`, que é a cor do FUNDO da página — o esqueleto ficava
               invisível. Mesmo conserto que o Cofre já tinha feito. */
            <div
              key={i}
              className="h-16 animate-pulse rounded-lg"
              style={{ background: "var(--bi-surface-2)" }}
            />
          ))}
        </div>
      ) : items.length === 0 ? (
        <Vazio>
          {filtrando
            ? "Nenhuma anotação com esses filtros."
            : (
              <>
                Nenhuma anotação ainda. Use o ícone <Edit2 className="inline size-3.5" /> nas telas
                de Convênios, Voluntárias ou outras para criar anotações.
              </>
            )}
        </Vazio>
      ) : (
        /* A lista deixou de ser <ul className="divide-y"> dentro de uma caixa com
           cabeçalho. Cada anotação é um cartão: o número de referência como
           título, fonte e status em selo, e os quatro campos que o gestor
           compara entre itens em POSIÇÕES FIXAS — protocolo, data, anexos e
           atualização caem sempre na mesma coluna, então o olho desce a lista
           como descia na tabela, sem existir tabela. */
        <>
        <AvisoEscopo
          bloqueadas={contarSemEscrita(items)}
          total={items.length}
          plural="as anotações"
        />
        <Lista>
          {items.map((a) => {
            // "Outro" é o valor sentinela do select; o texto que vale está no
            // status_custom. Sem isto o cartão anunciaria "Outro" para todos.
            const status = a.status_interno === "Outro"
              ? (a.status_custom || "Outro")
              : a.status_interno;
            const nAnexos = a.anexos?.length ?? 0;
            const numero = a.numero_referencia || a.fonte_ref;
            return (
              <ItemLinha
                key={a.id}
                onClick={() => setOpenItem(a)}
                titulo={
                  <span
                    className="font-mono"
                    title={a.numero_referencia && a.numero_referencia !== a.fonte_ref
                      ? `Referência interna: ${a.fonte_ref}`
                      : undefined}
                  >
                    {numero}
                  </span>
                }
                meta={
                  <>
                    <Selo title={FONTE_LABEL[a.fonte] || a.fonte}>
                      {FONTE_CURTA[a.fonte] || FONTE_LABEL[a.fonte] || a.fonte}
                    </Selo>
                    {status && (
                      <Selo tom={situacaoTom(status)} title={status}>{status}</Selo>
                    )}
                  </>
                }
              >
                {a.observacoes && (
                  /* Duas linhas no cartão e o texto inteiro no title: a
                     observação é longa por natureza, e quem quer ler tudo abre
                     a anotação. Era o mesmo line-clamp-2 de antes. */
                  <p
                    className="mt-1 line-clamp-2 text-[12px] leading-snug"
                    style={{ color: "var(--bi-muted)" }}
                    title={a.observacoes}
                  >
                    {a.observacoes}
                  </p>
                )}
                <Campos
                  campos={[
                    { rotulo: "Protocolo", valor: a.protocolo || "—", title: a.protocolo || undefined },
                    { rotulo: "Data do protocolo", valor: a.data_protocolo ? fmtData(a.data_protocolo) : "—" },
                    {
                      rotulo: "Anexos",
                      valor: nAnexos > 0 ? (
                        <span className="inline-flex items-center gap-1">
                          <Paperclip className="size-3" /> {nAnexos}
                        </span>
                      ) : "—",
                      title: nAnexos > 0
                        ? a.anexos.map((x) => x.nome).join(" · ")
                        : "Sem anexos",
                    },
                    { rotulo: "Atualizado", valor: fmtData(a.updated_at) },
                  ]}
                />
              </ItemLinha>
            );
          })}
        </Lista>
        </>
      )}

      {openItem && (
        <AnotacaoModal
          open={!!openItem}
          onClose={() => { setOpenItem(null); carregar(); }}
          fonte={openItem.fonte}
          fonteRef={openItem.fonte_ref}
          municipioId={openItem.municipio_id}
          numeroReferencia={openItem.numero_referencia || openItem.fonte_ref}
          onChanged={carregar}
        />
      )}
    </div>
  );
}
