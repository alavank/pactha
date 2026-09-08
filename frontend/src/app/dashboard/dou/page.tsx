"use client";

import React, { useState } from "react";
import api from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Bloco, BlocoHead, Campos, ItemLinha, Lista, Selo, Vazio } from "@/components/ui/superficies";
import { Search, Loader2, Eye, Download, Newspaper } from "lucide-react";
import { useUfDoMunicipio } from "@/lib/useUfDoMunicipio";
import { diarioDaUf } from "@/lib/estadual";
import { TituloTela } from "@/components/TituloTela";

interface JmgItem {
  id_jornal: number;
  data_publicacao: string;
  tipo_caderno: string;
  texto_resultado: string;
  pagina: number;
  url_visualizar: string;
  url_baixar: string;
}

interface JmgResponse {
  items: JmgItem[];
  pagina_atual: number;
  total_paginas: number;
  total_registros: number;
}

function fmtDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("pt-BR");
  } catch {
    return iso?.slice(0, 10) || "-";
  }
}

function ddmmaaaa(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/** O caderno vem por extenso ("Diário dos Municípios Mineiros") e nao cabe num
 *  selo de 10px. O selo leva a forma curta, que e o que o olho usa para varrer;
 *  o nome INTEIRO continua visivel no campo "Caderno" e no `title`. */
function siglaCaderno(c?: string): string {
  const u = (c || "").toUpperCase();
  if (u.includes("EXECUTIV")) return "Executivo";
  if (u.includes("MUNIC")) return "Municípios";
  if (u.includes("TERCEIR")) return "Terceiros";
  if (u.includes("LEGISLATIV")) return "Legislativo";
  if (u.includes("JUDIC")) return "Judiciário";
  return c || "Caderno";
}

/* Rotulo dos campos do formulario. 11px em --bi-muted, a mesma escala de rotulo
   de controle das outras telas do lote (e do rotulo do <Numero>).
   Era 10px MAIUSCULO em --bi-faint, que e o desenho reservado a rotulo de DADO
   (<Campos> em 9px, meta em 10px): o filtro passava a imitar o resultado. */
const ROTULO = "mb-1 block text-[11px]";
const ROTULO_COR = { color: "var(--bi-muted)" } as const;

/* NAO existe helper `xTom` nesta tela de proposito: uma publicacao do Diario
   nao tem situacao. Nada aqui e "cancelado" ou "pendente", entao nao ha o que
   pintar — o unico selo (caderno) e sempre neutro, que ja e o padrao. A unica
   cor da tela e a do erro de busca, que e alerta de verdade. */

export default function DouMGPage() {
  /* ⭐ O DIÁRIO SEGUE O ESTADO DO AMBIENTE, pelo registro por UF de
     `lib/estadual.ts` — estado novo é uma linha lá, não um `if` a mais aqui.
     `temCaderno` é só de MG: os 3 cadernos (Executivo/Municípios/Terceiros) são
     conceito do Jornal Minas Gerais — as plataformas dos outros estados servem
     edição única.

     ⚠️ SEM FALLBACK "MG", e a diferença aparece na tela do cliente. Enquanto
     a UF não chega (primeira pintura, ou carteira sem estado), a tela caía no
     Jornal Minas Gerais: um servidor de Nova Palma via o título "Diário Oficial
     MG" e uma busca que ia ao diário de outro estado — sem erro nenhum, só
     resultado errado. Agora ela espera saber onde está antes de dizer onde
     busca. O `prov` só é nulo neste intervalo: o menu já esconde a tela onde
     não há provedor. */
  const ufAmbiente = useUfDoMunicipio();
  const prov = diarioDaUf(ufAmbiente);
  const temCaderno = prov?.api === "/dou-mg";
  const base = prov?.api || "";
  const [texto, setTexto] = useState("");
  // Periodo padrao = ultimos 30 dias, IGUAL ao de antes. So mudou onde a conta
  // acontece: no inicializador preguicoso do estado em vez do corpo do
  // componente, que e impuro (o valor era recalculado a cada re-render e o
  // lint do React barrava).
  const [dataIni, setDataIni] = useState(() => ddmmaaaa(new Date(Date.now() - 30 * 86400_000)));
  const [dataFim, setDataFim] = useState(() => ddmmaaaa(new Date()));
  const [diarioExec, setDiarioExec] = useState(true);
  const [diarioMun, setDiarioMun] = useState(false);
  const [diarioTer, setDiarioTer] = useState(false);
  const [edicaoExtra, setEdicaoExtra] = useState(false);
  const [pagina, setPagina] = useState(1);
  const [data, setData] = useState<JmgResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [abrindo, setAbrindo] = useState<number | null>(null);

  // Ve/baixa a publicacao PELA plataforma (proxy backend extrai o PDF do JMG).
  const abrirPublicacao = async (id: number, download: boolean) => {
    setAbrindo(id);
    setError(null);
    try {
      const token = localStorage.getItem("pactha_token");
      const res = await fetch(`${api.defaults.baseURL}${base}/publicacao/${id}?download=${download}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        credentials: "include",
      });
      if (!res.ok) throw new Error(String(res.status));
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      if (download) {
        const a = document.createElement("a");
        a.href = url;
        a.download = `${(prov?.api || "").replace("/", "")}-${id}.pdf`;
        document.body.appendChild(a);
        a.click();
        a.remove();
      } else {
        window.open(url, "_blank");
      }
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch {
      setError("Não foi possível abrir a publicação. Tente novamente.");
    } finally {
      setAbrindo(null);
    }
  };

  const buscar = async (p = 1) => {
    if (!texto.trim()) {
      setError("Informe uma palavra ou frase para pesquisar.");
      return;
    }
    setError(null);
    setLoading(true);
    setPagina(p);
    try {
      // Fora de MG não há caderno nem `tamanho` (a plataforma fixa 10/página):
      // manda só o essencial. MG segue com o pedido de sempre, byte a byte.
      const params = temCaderno
        ? {
            texto: texto.trim(),
            data_inicial: dataIni,
            data_final: dataFim,
            diario_executivo: diarioExec,
            diario_municipios: diarioMun,
            diario_terceiros: diarioTer,
            edicao_extra: edicaoExtra,
            pagina: p,
            tamanho: 20,
          }
        : { texto: texto.trim(), data_inicial: dataIni, data_final: dataFim, pagina: p };
      const res = await api.get<JmgResponse>(`${base}/buscar`, { params });
      setData(res.data);
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (e as Error).message;
      setError(`Falha na busca: ${msg}`);
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  const limpar = () => {
    setTexto("");
    setDiarioExec(true);
    setDiarioMun(false);
    setDiarioTer(false);
    setEdicaoExtra(false);
    setData(null);
    setError(null);
  };

  const exportPdf = () => {
    if (!data) return;
    const titulos = data.items.map((it) => (it.texto_resultado || "").slice(0, 200));
    const edicoes = data.items.map((it) => `${it.data_publicacao}/${it.tipo_caderno}/p.${it.pagina}`);
    const qs = new URLSearchParams();
    // municipio_id é só pro nome do arquivo - usa 0 como placeholder
    qs.append("municipio_id", "0");
    titulos.forEach((t) => qs.append("titulos", t));
    edicoes.forEach((e) => qs.append("edicoes", e));
    // ⚠️ Mesmo conserto do `dashboard/convenios`: `pactha_token` é apagado do
    // localStorage no primeiro refresh, e `Bearer null` ATROPELA o cookie bom
    // no backend (o Bearer é lido antes). Pelo `api` vai o cookie e há retry.
    //
    // Note que `abrirPublicacao`, logo acima neste mesmo arquivo, JÁ protegia o
    // header (`token ? {...} : {}`) e por isso nunca quebrou — era só esta.
    api.get(`/export-pdf/dou?${qs.toString()}`, { responseType: "blob" })
      .then((r) => {
        const u = URL.createObjectURL(r.data as Blob);
        window.open(u, "_blank");
        setTimeout(() => URL.revokeObjectURL(u), 60000);
      })
      .catch(() => setError("Não foi possível gerar o PDF. Tente novamente."));
  };

  /* Depois dos hooks, nunca antes: um `return` acima deles mudaria a ordem de
     chamada entre renders. Aqui a UF ainda não chegou — e a tela prefere ficar
     em branco por um instante a apontar para o diário do estado errado. */
  if (!prov) {
    return <Vazio>Identificando o estado do município…</Vazio>;
  }

  return (
    <div className="space-y-4">
      <div>
        <TituloTela>{prov.titulo}</TituloTela>
        <p className="text-sm text-muted-foreground">Busca em tempo real no {prov.fonte}</p>
      </div>

      {/* O FORMULARIO DEIXOU DE SER UM PAINEL VIOLETA.
          Era um bloco `bg-primary text-white` — a cor mais forte da tela gasta
          no filtro, e nao no resultado. Agora e um <Bloco> igual aos demais: o
          que chama atencao passa a ser o que o gestor foi buscar. */}
      <Bloco className="p-3">
        <BlocoHead
          icon={Search}
          titulo="Busca de conteúdo"
          sub={temCaderno
            ? "Palavra ou frase, período de publicação e cadernos do Jornal Minas Gerais"
            : `Palavra ou frase e período de publicação no ${prov.titulo}`}
        />

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div className="md:col-span-2">
            <label className={ROTULO} style={ROTULO_COR}>Palavra ou frase *</label>
            <Input
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              placeholder="Ex: 1261002768/2025 ou MUNICIPIO DE ARAUJOS"
              onKeyDown={(e) => { if (e.key === "Enter") buscar(1); }}
            />
          </div>

          <div>
            <label className={ROTULO} style={ROTULO_COR}>Data inicial *</label>
            <Input
              type="date"
              value={dataIni}
              onChange={(e) => setDataIni(e.target.value)}
            />
          </div>
          <div>
            <label className={ROTULO} style={ROTULO_COR}>Data final *</label>
            <Input
              type="date"
              value={dataFim}
              onChange={(e) => setDataFim(e.target.value)}
            />
          </div>
        </div>

        {/* Os cadernos são conceito do Jornal Minas Gerais; as plataformas do
            ES e de GO servem edição única — a seção some fora de MG. */}
        {temCaderno && (
          <div className="mt-3">
            <span className={ROTULO} style={ROTULO_COR}>Cadernos *</span>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              <Toggle label="Diário do Executivo" checked={diarioExec} onChange={setDiarioExec} />
              <Toggle label="Diário dos Municípios Mineiros" checked={diarioMun} onChange={setDiarioMun} />
              <Toggle label="Diário de Terceiros" checked={diarioTer} onChange={setDiarioTer} />
              <Toggle label="Edição Extra" checked={edicaoExtra} onChange={setEdicaoExtra} />
            </div>
          </div>
        )}

        <div
          className="mt-3 flex items-center justify-end gap-2 border-t pt-3"
          style={{ borderColor: "var(--bi-line)" }}
        >
          <Button variant="ghost" size="sm" onClick={limpar}>
            Limpar filtros
          </Button>
          <Button size="sm" onClick={() => buscar(1)} disabled={loading}>
            {loading ? <Loader2 className="size-4 animate-spin mr-2" /> : <Search className="size-4 mr-2" />}
            Pesquisar
          </Button>
        </div>
      </Bloco>

      {/* Falha de busca continua colorida: e alerta de verdade, o unico da tela.
          A cor vem do token, nao de `bg-error/15`. */}
      {error && (
        <div
          role="alert"
          className="bi-card-flat px-3 py-2.5 text-[12px]"
          style={{ color: "var(--bi-crit-ink)" }}
        >
          {error}
        </div>
      )}

      {data && (
        <Bloco className="p-3">
          <BlocoHead
            icon={Newspaper}
            titulo={`${data.total_registros.toLocaleString("pt-BR")} resultado(s)`}
            sub={
              <>
                {texto ? `para “${texto}” · ` : ""}
                {fmtDate(dataIni)} até {fmtDate(dataFim)}
              </>
            }
            right={
              data.items.length > 0 && (
                <Button onClick={exportPdf} size="sm" variant="outline" title="Exportar para PDF">
                  📄 PDF
                </Button>
              )
            }
          />

          {data.items.length === 0 ? (
            <Vazio>Nenhum resultado encontrado.</Vazio>
          ) : (
            /* CADA PUBLICACAO VIROU CARTAO.
               Antes eram linhas separadas por borda, com a data/caderno/pagina
               numa frase corrida em cima e dois links violeta embaixo. As tres
               colunas agora vivem em <Campos>, em posicao FIXA: o olho desce a
               coluna "Publicação" de um resultado para o outro, coisa que a
               frase corrida impedia porque o trecho acima tem tamanho variavel. */
            <Lista>
              {data.items.map((it) => {
                const carregando = abrindo === it.id_jornal;
                return (
                  <ItemLinha
                    key={it.id_jornal}
                    /* O trecho casado e o conteudo do item — vem do JMG com
                       quebras de linha proprias, que `pre-wrap` preserva. */
                    titulo={<span className="whitespace-pre-wrap">{it.texto_resultado}</span>}
                    meta={
                      <>
                        <Selo title={it.tipo_caderno}>{siglaCaderno(it.tipo_caderno)}</Selo>
                        {/* Id do jornal: serve para ACHAR a edicao no portal,
                            nao para comparar — por isso fica na meta, nao na grade. */}
                        <span className="font-mono">jornal {it.id_jornal}</span>
                      </>
                    }
                    acao={
                      <>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          onClick={() => abrirPublicacao(it.id_jornal, false)}
                          disabled={carregando}
                          title="Visualizar publicação"
                          aria-label="Visualizar publicação"
                        >
                          {carregando ? <Loader2 className="size-4 animate-spin" /> : <Eye className="size-4" />}
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          onClick={() => abrirPublicacao(it.id_jornal, true)}
                          disabled={carregando}
                          title="Baixar publicação"
                          aria-label="Baixar publicação"
                        >
                          {carregando ? <Loader2 className="size-4 animate-spin" /> : <Download className="size-4" />}
                        </Button>
                      </>
                    }
                  >
                    <Campos
                      campos={[
                        { rotulo: "Publicação", valor: fmtDate(it.data_publicacao) },
                        { rotulo: "Caderno", valor: it.tipo_caderno || "—", title: it.tipo_caderno },
                        { rotulo: "Página", valor: it.pagina ?? "—" },
                      ]}
                    />
                  </ItemLinha>
                );
              })}
            </Lista>
          )}

          {data.total_paginas > 1 && (
            <div
              className="mt-3 flex items-center justify-between border-t pt-3"
              style={{ borderColor: "var(--bi-line)" }}
            >
              <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
                Página {data.pagina_atual} de {data.total_paginas}
              </p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={pagina <= 1 || loading}
                  onClick={() => buscar(pagina - 1)}
                >
                  Anterior
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={pagina >= data.total_paginas || loading}
                  onClick={() => buscar(pagina + 1)}
                >
                  Próximo
                </Button>
              </div>
            </div>
          )}
        </Bloco>
      )}
    </div>
  );
}

/** Chave liga/desliga do caderno.
 *
 *  Era verde quando ligada e VERMELHA quando desligada — vermelho de erro para
 *  dizer "esse caderno nao entra na busca", que nao e erro nenhum. Agora usa o
 *  par neutro da identidade (`--bi-cta`, que acompanha claro/escuro) para o
 *  ligado e a linha cinza para o desligado: o estado continua obvio sem gastar
 *  a cor de alerta. */
function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer select-none items-center gap-2 text-[11px]" style={{ color: "var(--bi-muted)" }}>
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className="relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors"
        style={{ background: checked ? "var(--bi-cta)" : "var(--bi-line-strong)" }}
        aria-pressed={checked}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full transition ${
            checked ? "translate-x-4" : "translate-x-0.5"
          }`}
          /* Desligada a bolinha era `--bi-surface` sobre trilho
             `--bi-line-strong`: 1,49:1 no claro e 1,51:1 no escuro — ela some,
             e o controle deixa de parecer um interruptor (vira uma pilula
             lisa). O estado em si sempre foi legivel, porque o TRILHO muda
             de cor; o que faltava era a bolinha. Invertida: clara sobre
             trilho escuro quando ligada, escura sobre trilho claro quando
             desligada. */
          style={{ background: checked ? "var(--bi-cta-ink)" : "var(--bi-muted)" }}
        />
      </button>
      <span>{label}</span>
    </label>
  );
}
