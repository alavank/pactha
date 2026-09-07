"use client";

/* PARCERIAS — a emenda de saúde do município, com o parlamentar nomeado.
 *
 * ⭐ O QUE ESTA TELA MOSTRA QUE NENHUMA OUTRA MOSTRAVA. O módulo de Gestão de
 * Parcerias do Transferegov processa as transferências de 2024 em diante — 144
 * dos 176 programas publicados são Fundo a Fundo da Saúde —, e até 07/09/2026
 * era o único instrumento federal invisível à plataforma. Em Nova Palma são 11
 * propostas, R$ 2,18 mi, TODAS com emenda e parlamentar identificados.
 *
 * ⭐ E A PERGUNTA QUE ELA RESPONDE É "QUEM TROUXE". O ranking por parlamentar
 * abre a tela porque é a leitura que o gestor faz primeiro; a lista de
 * propostas vem depois, para quem quer o detalhe. No tenant trust isso são 84
 * propostas e R$ 67,7 mi só da Comissão da Saúde.
 *
 * ⚠️ NÃO CONFUNDIR COM «VOLUNTÁRIAS», a tela vizinha. Aquela mostra o convênio
 * discricionário do SICONV, que continua vindo dos dumps CSV. Esta é outro
 * módulo, com outro ciclo (proposta → parceria) e outro tipo de instrumento. As
 * duas coexistem de propósito, e por isso ficam lado a lado no menu.
 *
 * ⚠️ PROPOSTA SEM PARCERIA CELEBRADA NÃO É ERRO. O ciclo tem dois passos, e a
 * maioria das propostas de um ano corrente ainda não virou instrumento. A tela
 * diz «não celebrada» em vez de esconder a linha — quem lê precisa saber que a
 * proposta existe e em que pé está.
 *
 * ⚠️ E QUANDO NÃO HÁ DADO, A TELA NÃO CONCLUI "o município não tem emenda". A
 * coleta é nossa e diária: a ausência pode ser nossa.
 */

import React, { useEffect, useMemo, useState } from "react";
import {
  Building2, ExternalLink, HandCoins, Landmark, Loader2, Users, Wallet,
} from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import {
  Bloco, BlocoHead, Campos, ItemLinha, Lista, Numero, Selo, Vazio,
  situacaoTom,
} from "@/components/ui/superficies";

interface Proposta {
  /* ⚠️ Falso quando o recebedor não é a administração municipal — Fundo
     ESTADUAL de Saúde, associação privada, cooperativa. A linha aparece, mas
     não entra nos cartões nem no ranking. Ver o cabeçalho do router. */
  municipal: boolean;
  id_proposta: number;
  objeto: string | null;
  situacao: string | null;
  valor: number | null;
  ano: number | null;
  data_proposta: string | null;
  ente_recebedor: string | null;
  cnpj_recebedor: string | null;
  natureza_juridica: string | null;
  id_parceria: number | null;
  codigo_parceria: string | null;
  situacao_parceria: string | null;
  data_assinatura: string | null;
  numero_emenda: string | null;
  parlamentar: string | null;
  tipo_emenda: string | null;
  valor_emenda: number | null;
  resultado_esperado: string | null;
  url_fonte: string;
}

interface PorParlamentar {
  parlamentar: string;
  propostas: number;
  valor: number;
  tipo: string | null;
}

interface Resp {
  tem_dados: boolean;
  motivo?: string;
  itens?: Proposta[];
  total?: number;
  valor_total?: number;
  valor_emenda?: number;
  por_parlamentar?: PorParlamentar[];
  por_situacao?: Array<{ situacao: string; qtd: number }>;
  total_listado?: number;
  fora_do_municipio?: { qtd: number; valor: number };
  municipio?: { id: number; nome: string; uf: string };
}

const brl = (v: number | null | undefined) =>
  v == null
    ? "—" /* ⚠️ Não "R$ 0,00": proposta sem valor declarado não é de graça. */
    : v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

const dataBR = (s: string | null) =>
  s ? s.split("-").reverse().join("/") : null;

export default function ParceriasPage() {
  const { municipioId } = useMunicipio();
  /* ⚠️ A RESPOSTA GUARDA DE QUAL MUNICÍPIO ELA É, e `carregando` é DERIVADO
     disso — mesmo desenho de `obrasgov/page.tsx` e pela mesma razão: ao trocar
     de município, um `d` que sobrou do anterior apareceria por um quadro sob o
     cabeçalho do novo, mostrando a emenda de uma cidade no nome de outra. */
  const [res, setRes] = useState<{ mun: string; d: Resp | null; erro: string | null }>(
    { mun: "", d: null, erro: null });
  const [parlamentar, setParlamentar] = useState<string>("");

  const daVez = res.mun === municipioId;
  const carregando = !!municipioId && !daVez;
  const d = daVez ? res.d : null;
  const erro = daVez ? res.erro : null;

  useEffect(() => {
    if (!municipioId) return;
    let vivo = true;
    api
      .get<Resp>("/parcerias", { params: { municipio_id: municipioId } })
      .then((r) => {
        if (vivo) setRes({ mun: municipioId, d: r.data, erro: null });
      })
      .catch((e) => {
        if (vivo)
          setRes({
            mun: municipioId, d: null,
            erro: e?.response?.data?.detail || "Não foi possível carregar.",
          });
      });
    return () => { vivo = false; };
  }, [municipioId]);

  const itens = useMemo(() => {
    const todos = d?.itens || [];
    return parlamentar
      ? todos.filter((p) => p.parlamentar === parlamentar)
      : todos;
  }, [d, parlamentar]);

  if (!municipioId) {
    return <Vazio>Selecione um município.</Vazio>;
  }
  if (carregando) {
    return (
      <div className="flex items-center gap-2 py-6 text-sm"
           style={{ color: "var(--bi-muted)" }}>
        <Loader2 className="size-4 animate-spin" /> Carregando parcerias…
      </div>
    );
  }
  if (erro) return <Vazio>{erro}</Vazio>;
  if (!d?.tem_dados) {
    return (
      <Vazio>{d?.motivo || "Sem parcerias coletadas para este município."}</Vazio>
    );
  }

  const ranking = d.por_parlamentar || [];
  const fora = d.fora_do_municipio?.qtd ?? 0;

  return (
    <div className="flex flex-col gap-4">
      {/* ⭐ CABEÇALHO SOLTO, e não um `Bloco` com `BlocoHead`. A primeira versão
          embrulhava título + KPIs num cartão só, e os quatro `Numero` — que já
          são `bi-card` — viravam CARTÃO DENTRO DE CARTÃO, encostados na borda
          do de fora (o `Bloco` não traz padding próprio). Este é o mesmo
          cabeçalho das Obras Federais e das Emendas Federais: h1, o parágrafo
          do que a tela é, e a régua de números logo abaixo, no fundo da
          página. */}
      <header>
        <h1 className="bi-title text-[18px]">Parcerias</h1>
        <p className="mt-1 max-w-3xl text-[12px] leading-snug"
           style={{ color: "var(--bi-muted)" }}>
          O módulo do Transferegov que processa as transferências de 2024 em
          diante — onde a <b>emenda de saúde</b> vira proposta e, depois,
          instrumento. Nas propostas listadas aqui o parlamentar que indicou o
          recurso vem nomeado na própria fonte.
        </p>
      </header>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Numero
          icon={Landmark}
          rotulo="Propostas"
          valor={String(d.total ?? 0)}
          /* ⚠️ O cartão conta a ADMINISTRAÇÃO MUNICIPAL. O resto continua na
             lista abaixo, marcado — esconder faria a contagem não bater com o
             portal, e somar diria que a prefeitura recebeu o que não recebeu. */
          sub={fora > 0
            ? `+ ${fora} de outro recebedor no município`
            : undefined}
        />
        <Numero icon={Wallet} rotulo="Valor total" valor={brl(d.valor_total)} />
        <Numero icon={HandCoins} rotulo="Em emendas" valor={brl(d.valor_emenda)} />
        <Numero icon={Users} rotulo="Parlamentares"
                valor={String(ranking.length)} />
      </div>

      {/* ⭐ O RANKING ABRE A TELA porque é a pergunta que o gestor faz primeiro:
          quem trouxe recurso para a cidade. Clicar filtra a lista abaixo. */}
      {ranking.length > 0 && (
        <Bloco className="p-3">
          <BlocoHead
            icon={Users}
            titulo="Por parlamentar"
            sub={parlamentar
              ? `filtrando por ${parlamentar} — clique de novo para ver todos`
              : fora > 0
                ? "só o que veio para a administração municipal · clique num nome para filtrar"
                : "clique num nome para filtrar as propostas"}
          />
          <Lista>
            {ranking.map((p) => (
              <ItemLinha
                key={p.parlamentar}
                titulo={
                  parlamentar === p.parlamentar
                    ? `${p.parlamentar} · filtrando`
                    : p.parlamentar
                }
                meta={`${p.propostas} proposta${p.propostas > 1 ? "s" : ""}` +
                      (p.tipo ? ` · ${p.tipo}` : "")}
                valor={<span className="bi-num">{brl(p.valor)}</span>}
                onClick={() =>
                  setParlamentar(parlamentar === p.parlamentar ? "" : p.parlamentar)}
              />
            ))}
          </Lista>
        </Bloco>
      )}

      <Bloco className="p-3">
        <BlocoHead
          icon={Landmark}
          titulo={parlamentar ? `Propostas · ${parlamentar}` : "Propostas"}
          sub={`${itens.length} de ${d.total} · a fonte publica de 2024 em diante`}
        />
        <Lista>
          {itens.map((p) => (
            <LinhaProposta key={p.id_proposta} p={p} />
          ))}
        </Lista>
        {itens.length === 0 && (
          <Vazio>Nenhuma proposta deste parlamentar.</Vazio>
        )}
        {fora > 0 && !parlamentar && (
          <p className="mt-3 text-[11px] leading-relaxed"
             style={{ color: "var(--bi-muted)" }}>
            {fora} proposta{fora > 1 ? "s" : ""} acima {fora > 1 ? "têm" : "tem"}{" "}
            como recebedor uma entidade do município que não é a administração
            municipal — fundo estadual, associação, cooperativa. {fora > 1
              ? "Elas aparecem" : "Ela aparece"} na lista porque o dinheiro chega
            à cidade, mas {fora > 1 ? "ficam" : "fica"} fora dos totais e do
            ranking: não é recurso da prefeitura.
          </p>
        )}
      </Bloco>

      {(d.por_situacao?.length ?? 0) > 0 && (
        <Bloco className="p-3">
          <BlocoHead icon={Building2} titulo="Por situação" />
          <div className="flex flex-wrap gap-2">
            {d.por_situacao!.map((s) => (
              <Selo key={s.situacao} tom={situacaoTom(s.situacao)}>
                {s.situacao} · {s.qtd}
              </Selo>
            ))}
          </div>
        </Bloco>
      )}
    </div>
  );
}

/** Uma proposta na lista — FECHADA por padrão.
 *
 *  ⚠️ NASCEU SEMPRE ABERTA, e foi assim que o dono a viu: cada uma das onze
 *  linhas despejava dez campos mais o parágrafo de «resultado esperado», e a
 *  lista virava uma parede de texto de várias telas de rolagem. Lista é para
 *  varrer; detalhe é para quem pediu. O gesto de abrir é o mesmo das Obras
 *  Federais e das Emendas Federais — nesta identidade, item de lista que
 *  esconde detalhe SEMPRE abre no clique, e nunca vem aberto.
 *
 *  ⚠️ E O `cols={4}` NÃO É ENFEITE. Sem `cols`, a peça `Campos` abre UMA COLUNA
 *  POR CAMPO: com dez campos, dez colunas de ~150px numa janela de 1920, e
 *  «FUNDO PÚBLICO DA ADMINISTRAÇÃO MUNICIPAL» saía como «FUNDO PÚBLICO DA A…».
 *  Era metade do que o dono chamou de "formatação toda bugada". */
function LinhaProposta({ p }: { p: Proposta }) {
  const [aberto, setAberto] = useState(false);
  return (
    <ItemLinha
      titulo={p.objeto || `Proposta ${p.id_proposta}`}
      valor={<span className="bi-num">{brl(p.valor)}</span>}
      onClick={() => setAberto((v) => !v)}
      expandido={aberto}
      meta={
        <span className="flex flex-wrap items-center gap-1.5">
          <Selo tom={situacaoTom(p.situacao)}>{p.situacao || "—"}</Selo>
          {/* ⚠️ Proposta sem instrumento não é erro: o ciclo tem dois passos e a
              maioria do ano corrente ainda não celebrou. */}
          <Selo tom={p.id_parceria ? "ok" : "neutro"}>
            {p.id_parceria ? "parceria celebrada" : "não celebrada"}
          </Selo>
          {/* ⚠️ O aviso é a diferença entre «a cidade recebeu» e «alguém na
              cidade recebeu». O Fundo Estadual de Saúde atende o estado
              inteiro; a associação privada não é a prefeitura. */}
          {!p.municipal && (
            <Selo tom="atencao" title={p.natureza_juridica || undefined}>
              não é da prefeitura
            </Selo>
          )}
          {p.parlamentar && <span>{p.parlamentar}</span>}
          {p.ano && <span>{p.ano}</span>}
        </span>
      }
    >
      {aberto && (
        <div className="mt-2 flex flex-col gap-2">
          <Campos
            cols={4}
            campos={[
              { rotulo: "Emenda", valor: p.numero_emenda, mono: true },
              { rotulo: "Parlamentar", valor: p.parlamentar },
              { rotulo: "Tipo de emenda", valor: p.tipo_emenda },
              { rotulo: "Valor da emenda", valor: brl(p.valor_emenda) },
              /* Raramente é a prefeitura: em Nova Palma as 11 propostas são do
                 Fundo Municipal da Saúde, com CNPJ próprio. */
              { rotulo: "Recebedor", valor: p.ente_recebedor },
              { rotulo: "Natureza jurídica", valor: p.natureza_juridica },
              { rotulo: "Proposta em", valor: dataBR(p.data_proposta) },
              { rotulo: "Instrumento", valor: p.codigo_parceria, mono: true },
              { rotulo: "Situação do instrumento", valor: p.situacao_parceria },
              { rotulo: "Assinatura", valor: dataBR(p.data_assinatura) },
            ].filter((c) => c.valor && c.valor !== "—")}
          />
          {p.resultado_esperado && (
            <p className="text-[11px] leading-relaxed"
               style={{ color: "var(--bi-muted)" }}>
              {p.resultado_esperado}
            </p>
          )}
          {/* O link deixa qualquer número desta tela conferível na fonte — a
              mesma disciplina do `url_fonte` das Obras. */}
          <a
            href={p.url_fonte}
            target="_blank"
            rel="noreferrer"
            className="inline-flex w-fit items-center gap-1 text-[11px] underline"
            style={{ color: "var(--bi-muted)" }}
          >
            <ExternalLink className="size-3" /> ver na fonte
          </a>
        </div>
      )}
    </ItemLinha>
  );
}
