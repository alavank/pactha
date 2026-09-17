"use client";

/* EMENDAS PARLAMENTARES FEDERAIS — a aba Federais da tela única (17/09/2026).
 *
 * Sucede a tela «Federais › Emendas parlamentares» (06/09/2026), e herda dela as
 * três regras que a fizeram confiável:
 *   · «—» NÃO É R$ 0: execução não consultada é ausência NOSSA;
 *   · OS CARTÕES DE EXECUÇÃO CONTAM EMENDA, NÃO SOMAM DINHEIRO — o agregado da
 *     CGU é da emenda inteira, nacional (somado, deu R$ 4 bi em Nova Palma);
 *   · O AVISO VEM ANTES DO CONTEÚDO, nunca no rodapé.
 *
 * ⭐ O QUE MUDOU: a lista junta a emenda de QUATRO lugares — a carteira (dump +
 * CGU), o Plano de Ação da emenda Pix, a proposta de saúde de Parcerias e o
 * convênio voluntário. O servidor casa pelo código de 12 dígitos
 * (`services/emendas_unificadas.py`): o que casa vira INSTRUMENTO da linha e não
 * soma; o que não casa vira linha própria. Medido na Freitas em 17/09/2026: a
 * carteira bate uma a uma com a tela antiga, e nenhuma linha solta tem par na
 * carteira (mesmo autor, ano e valor).
 *
 * ⚠️ OS FILTROS VÃO AO SERVIDOR, e os totais voltam com eles: cartão que soma a
 * base inteira embaixo de uma lista filtrada se contradiz na tela.
 */

import React, { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Banknote, Landmark, Loader2, Users } from "lucide-react";

import api from "@/lib/api";
import { formatDataHora, horasDesde } from "@/lib/bi-format";
import {
  Abas, Aviso, Bloco, BlocoHead, ItemLinha, Lista, Numero, Selo, Vazio,
} from "@/components/ui/superficies";
import { SeloCadastro } from "@/components/emendas/AbaParlamentares";
import { brl, type Autor, type Instrumento, type Origem } from "@/components/emendas/DetalheEmenda";

interface Linha {
  chave: string;
  origem: Origem;
  id: string;
  origem_rotulo: string;
  origens: Origem[];
  codigo_emenda: string | null;
  ano: number | null;
  autor: string | null;
  autores: string[];
  parlamentares: Autor[];
  colegiado: boolean;
  tipo: string | null;
  impositiva: boolean | null;
  objeto: string | null;
  situacao: string | null;
  valor: number | null;
  municipal: boolean;
  beneficiario?: string | null;
  orgao?: string | null;
  grupo: "nao_consultada" | "nao_encontrada" | "sem_empenho" | "parado" | "andamento" | "paga" | null;
  motivo: string | null;
  execucao_consultada?: boolean;
  execucao: Record<string, number | null> | null;
  instrumentos: Instrumento[];
}

interface Resp {
  tem_dados: boolean;
  estado: string | null;
  aviso: string | null;
  coleta_em: string | null;
  coleta_falhas: number | null;
  execucao: { consultadas: number; total: number } | null;
  totais: {
    emendas: number; valor_prefeitura: number; fora_prefeitura_n: number;
    fora_prefeitura_valor: number; parado_n: number; com_pagamento_n: number;
    nao_consultadas_n: number; impositivas_n: number; por_origem: Record<string, number>;
  };
  items: Linha[];
  anos: number[];
  tipos: string[];
  origens: Origem[];
  autores: string[];
}

const ROTULO_TIPO: Record<string, string> = {
  INDIVIDUAL: "Individual", BANCADA: "Bancada", COMISSAO: "Comissão", "RELATOR GERAL": "Relator-geral",
};
const ROTULO_GRUPO: Record<string, string> = {
  nao_consultada: "Execução não consultada", nao_encontrada: "Sem registro na CGU",
  sem_empenho: "Sem empenho", parado: "Sem pagamento", andamento: "Pago em parte", paga: "Paga",
};
const TOM_GRUPO: Record<string, "neutro" | "ok" | "atencao" | "critico"> = {
  nao_consultada: "neutro", nao_encontrada: "neutro", sem_empenho: "atencao",
  parado: "critico", andamento: "atencao", paga: "ok",
};
/* O selo curto de cada origem. «Pix» e «Saúde» porque é assim que o gestor
   chama; o nome completo vai no `title`. */
const SELO_ORIGEM: Record<string, string> = {
  federal: "Carteira", te: "Pix", parcerias: "Saúde", indicacao: "Saúde · indicada",
  voluntaria: "Voluntária",
};

function LinhaEmenda({ e, onAbrir }: { e: Linha; onAbrir: () => void }) {
  return (
    <ItemLinha
      onClick={onAbrir}
      titulo={
        <span className="flex flex-wrap items-center gap-1.5">
          <span className="min-w-0">{e.autor || "Autor não informado"}</span>
          {e.parlamentares.map((p) => <SeloCadastro key={p.nome} c={p.cadastro} />)}
          {/* Selo de origem só quando a linha tem MAIS que a carteira: a emenda
              só indicada é a norma, e pintar todas apagaria o sinal. */}
          {e.origens.filter((o) => o !== "federal").map((o) => (
            <Selo key={o} tom="acento" title={e.instrumentos.find((i) => i.origem === o)?.rotulo || e.origem_rotulo}>
              {SELO_ORIGEM[o] || o}
            </Selo>
          ))}
          {!e.municipal && (
            <Selo tom="acento" title="Emenda destinada a uma entidade do município, e não à Prefeitura — fica fora do total">
              {e.beneficiario || "não é a Prefeitura"}
            </Selo>
          )}
          {e.impositiva && e.origem === "federal" && (
            <Selo title="Execução obrigatória por norma constitucional">Impositiva</Selo>
          )}
          {e.grupo && (
            <Selo tom={TOM_GRUPO[e.grupo]} title={e.motivo || undefined}>{ROTULO_GRUPO[e.grupo]}</Selo>
          )}
          {!e.grupo && e.situacao && <Selo>{e.situacao}</Selo>}
        </span>
      }
      valor={<span className="bi-num">{brl(e.valor)}</span>}
      meta={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
          {e.ano && <span>{e.ano}</span>}
          {e.tipo && <span>{ROTULO_TIPO[e.tipo] || e.tipo}</span>}
          {e.orgao && <span>{e.orgao}</span>}
          {e.codigo_emenda && <span>nº {e.codigo_emenda}</span>}
          {e.objeto && <span className="truncate">{e.objeto}</span>}
        </span>
      }
    />
  );
}

export default function AbaFederais({ municipioId, onAbrir }: {
  municipioId: string;
  onAbrir: (origem: Origem, id: string) => void;
}) {
  const [ano, setAno] = useState("");
  const [autor, setAutor] = useState("");
  const [tipo, setTipo] = useState("");
  const [origem, setOrigem] = useState("");
  const [vista, setVista] = useState<"todas" | "acao" | "autor">("todas");
  /* ⚠️ A RESPOSTA GUARDA A CHAVE DO PEDIDO, e `carregando` é derivado: ao trocar
     de município ou filtro, um `d` do pedido anterior apareceria por um quadro
     sob o filtro novo. */
  const chave = `${municipioId}|${ano}|${autor}|${tipo}|${origem}`;
  const [res, setRes] = useState<{ chave: string; d: Resp | null; erro: string | null } | null>(null);
  const [opcoes, setOpcoes] = useState<Pick<Resp, "anos" | "tipos" | "origens" | "autores"> | null>(null);

  useEffect(() => {
    if (!municipioId) return;
    let vivo = true;
    const params: Record<string, string> = { municipio_id: municipioId };
    if (ano) params.ano = ano;
    if (autor) params.autor = autor;
    if (tipo) params.tipo = tipo;
    if (origem) params.origem = origem;
    api.get<Resp>("/emendas-parlamentares/federais", { params })
      .then((r) => {
        if (!vivo) return;
        setRes({ chave, d: r.data, erro: null });
        // As opções dos filtros vêm da base INTEIRA e ficam enquanto o próximo
        // pedido carrega — senão o filtro some no meio da troca.
        setOpcoes({ anos: r.data.anos, tipos: r.data.tipos, origens: r.data.origens, autores: r.data.autores });
      })
      .catch((e) => {
        if (vivo) setRes({ chave, d: null, erro: e?.response?.data?.detail || "Não foi possível carregar." });
      });
    return () => { vivo = false; };
  }, [chave, municipioId, ano, autor, tipo, origem]);

  const daVez = res?.chave === chave;
  const d = daVez ? res!.d : null;
  const itens = useMemo(() => d?.items || [], [d]);
  /* «Precisa de cobrança» é ESTREITO de propósito: não consultada NÃO entra. */
  const acao = useMemo(() => itens.filter((e) => e.grupo === "parado"), [itens]);
  const porAutor = useMemo(() => {
    const m = new Map<string, { autor: string; colegiado: boolean; n: number; valor: number; parado: number; linha: Linha }>();
    for (const e of itens) {
      if (!e.autor) continue;
      const a = m.get(e.autor) || { autor: e.autor, colegiado: e.colegiado, n: 0, valor: 0, parado: 0, linha: e };
      a.n += 1;
      // Só a prefeitura soma, a mesma regra do cartão.
      if (e.municipal) a.valor += e.valor || 0;
      if (e.grupo === "parado") a.parado += 1;
      m.set(e.autor, a);
    }
    return [...m.values()].sort((x, y) => y.valor - x.valor);
  }, [itens]);

  if (!municipioId) return <Vazio>Selecione um município para ver as emendas federais.</Vazio>;
  if (!daVez) {
    return (
      <div className="flex items-center gap-2 py-6 text-[13px]" style={{ color: "var(--bi-muted)" }}>
        <Loader2 className="size-4 animate-spin" /> Carregando emendas federais…
      </div>
    );
  }
  if (res?.erro) return <Vazio>{res.erro}</Vazio>;

  const t = d?.totais;
  const aviso = d?.aviso ? (
    <Aviso tom={d.estado === "sem_cnpj" ? "critico" : "atencao"} icon={AlertTriangle}
      titulo={
        d.estado === "sem_chave" ? "Carteira completa, execução ainda não consultada"
        : d.estado === "sem_cnpj" ? "Falta o CNPJ do município"
        : d.estado === "sem_emendas" ? "Nenhuma emenda federal na carteira"
        : d.estado === "sem_coleta" ? "A coleta ainda não rodou"
        : "Execução consultada em parte da carteira"
      }>
      {d.aviso}
    </Aviso>
  ) : null;

  const filtro = (rotulo: string, valor: string, set: (v: string) => void, lista: Array<[string, string]>) =>
    lista.length > 1 || valor ? (
      <select className="bi-input h-7 rounded px-2 text-[12px]" value={valor}
              onChange={(ev) => set(ev.target.value)} aria-label={rotulo}>
        <option value="">{rotulo}</option>
        {lista.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    ) : null;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="max-w-3xl text-[12px] leading-snug" style={{ color: "var(--bi-muted)" }}>
          Toda emenda federal do município numa lista só: a indicada (dados abertos do
          TransfereGov, pelo CNPJ), a Pix, a de saúde (Parcerias) e a que virou convênio.
          A execução vem do Portal da Transparência da CGU. Clique numa emenda para ver o
          detalhe inteiro.
        </p>
        {(d?.coleta_falhas ?? 0) > 0 ? (
          <p className="mt-1 text-[11px]" style={{ color: "var(--bi-warn-ink)" }}>
            não foi possível concluir a última coleta — exibindo os últimos dados obtidos
          </p>
        ) : d?.coleta_em ? (
          <p className="mt-1 text-[11px]"
             style={{ color: (horasDesde(d.coleta_em) ?? 0) > 26 ? "var(--bi-warn-ink)" : "var(--bi-muted)" }}>
            Atualizado em {formatDataHora(d.coleta_em)}
            {d.execucao && <> · execução consultada em {d.execucao.consultadas} de {d.execucao.total} emendas da carteira</>}
          </p>
        ) : null}
      </div>

      {aviso}

      {!d?.tem_dados ? (
        !d?.aviso && <Vazio>Sem emendas federais coletadas para este município.</Vazio>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Numero icon={Landmark} rotulo="Emendas" valor={t?.emendas ?? 0}
                    sub={Object.entries(t?.por_origem || {})
                      .map(([o, n]) => `${n} ${SELO_ORIGEM[o] || o}`).join(" · ")} />
            {/* ⭐ O `sub` impede a leitura errada: o hospital da cidade aparece na
                lista, mas não é caixa da Prefeitura. */}
            <Numero icon={Banknote} rotulo="À Prefeitura" valor={brl(t?.valor_prefeitura)}
                    sub={t?.fora_prefeitura_n
                      ? `+ ${brl(t.fora_prefeitura_valor)} a ${t.fora_prefeitura_n} entidade(s), fora do total`
                      : "tudo destinado à Prefeitura"} />
            {/* ⚠️⚠️ CONTA EMENDA, NÃO SOMA DINHEIRO — ver o cabeçalho. */}
            <Numero icon={Banknote} rotulo="Com pagamento na CGU" valor={t?.com_pagamento_n ?? 0}
                    sub={t?.nao_consultadas_n
                      ? `${t.nao_consultadas_n} da carteira ainda não consultada(s)`
                      : "inclui o resto a pagar quitado"} />
            <Numero icon={AlertTriangle} rotulo="Precisa de cobrança" valor={acao.length}
                    tom={acao.length ? "critico" : "neutro"}
                    onClick={acao.length ? () => setVista("acao") : undefined}
                    sub={acao.length ? "empenhada e sem pagamento" : "nada empenhado e parado"} />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {filtro("Todos os anos", ano, setAno, (opcoes?.anos || []).map((a) => [String(a), String(a)]))}
            {filtro("Todos os autores", autor, setAutor, (opcoes?.autores || []).map((a) => [a, a]))}
            {filtro("Todos os tipos", tipo, setTipo, (opcoes?.tipos || []).map((x) => [x, ROTULO_TIPO[x] || x]))}
            {filtro("Todas as origens", origem, setOrigem, (opcoes?.origens || []).map((o) => [o, SELO_ORIGEM[o] || o]))}
          </div>

          <Abas valor={vista} onChange={setVista} opcoes={[
            { valor: "todas", label: `Todas (${itens.length})` },
            { valor: "acao", label: `Precisa de cobrança (${acao.length})` },
            { valor: "autor", label: `Por parlamentar (${porAutor.filter((a) => !a.colegiado).length})` },
          ]} />

          {vista !== "autor" && (
            <Bloco className="p-3">
              <BlocoHead icon={vista === "acao" ? AlertTriangle : Landmark}
                         titulo={vista === "acao" ? "Precisa de cobrança" : "Todas as emendas"}
                         sub={vista === "acao" ? "empenhada e sem nenhum pagamento" : `${itens.length} no filtro`} />
              {(vista === "acao" ? acao : itens).length ? (
                <Lista>
                  {(vista === "acao" ? acao : itens).map((e) => (
                    <LinhaEmenda key={e.chave} e={e} onAbrir={() => onAbrir(e.origem, e.id)} />
                  ))}
                </Lista>
              ) : (
                <Vazio>
                  {vista === "acao"
                    ? "Nenhuma emenda empenhada e parada no filtro atual."
                    : "Nenhuma emenda no filtro atual."}
                </Vazio>
              )}
            </Bloco>
          )}

          {vista === "autor" && (
            [false, true].map((col) => {
              const lista = porAutor.filter((a) => a.colegiado === col);
              if (!lista.length) return null;
              return (
                <Bloco key={String(col)} className="p-3">
                  {/* ⚠️ COLEGIADO EM BLOCO PRÓPRIO: bancada e comissão não são gente. */}
                  <BlocoHead icon={Users}
                    titulo={col ? "Emendas de colegiado" : "Quem destinou recurso ao município"}
                    sub={col ? "bancada, comissão e relator-geral — não são de um parlamentar"
                             : "do maior valor à Prefeitura para o menor"} />
                  <Lista>
                    {lista.map((a) => (
                      <ItemLinha key={a.autor}
                        onClick={() => { setAutor(a.autor); setVista("todas"); }}
                        titulo={<span className="flex flex-wrap items-center gap-1.5">
                          {a.autor}
                          {a.linha.parlamentares.map((p) => <SeloCadastro key={p.nome} c={p.cadastro} />)}
                        </span>}
                        valor={<span className="bi-num">{brl(a.valor)}</span>}
                        meta={<span className="flex flex-wrap items-center gap-x-3">
                          <span>{a.n} emenda(s)</span>
                          {!!a.parado && <Selo tom="critico">{a.parado} sem pagamento</Selo>}
                        </span>} />
                    ))}
                  </Lista>
                </Bloco>
              );
            })
          )}
        </>
      )}
    </div>
  );
}
