"use client";

/* OBRAS FEDERAIS — o Obras.gov.br / CIPI do município.
 *
 * ⭐ O QUE ESTA TELA MOSTRA QUE NENHUMA OUTRA MOSTRAVA. O SISMOB cobre saúde e o
 * SIMEC cobre educação. O resto — mobilidade, saneamento, habitação, segurança
 * e a RECONSTRUÇÃO DA DEFESA CIVIL — não aparecia em lugar nenhum do sistema.
 * Em Nova Palma são 21 das 30 obras: a reconstrução pós-enchente inteira.
 *
 * ⭐ ELA REPETE, DE PROPÓSITO, OBRA QUE O SISMOB JÁ MOSTRA. Decisão do dono
 * (04/09/2026): esta é a visão GERAL, e esconder metade dela para evitar
 * repetição daria um número que não bate com o portal do Governo. Cada obra traz
 * de qual sistema veio — quando é SISMOB, a tela DIZ, em vez de fingir que a
 * repetição não existe.
 *
 * ⚠️ O QUE ORDENA A TELA É A SITUAÇÃO, NÃO O VALOR — e NÃO a data efetiva, que
 * a fonte deixa vazia em 100% das obras coletadas (e em 65 das "Concluída" da
 * própria API). Quem classifica é `_classificar`, no servidor, para tela, TV e
 * PDF concordarem sobre o que é urgente.
 *
 * ⭐ E SÃO QUATRO GRUPOS, não três: «exigem atenção» (obra que começou e travou)
 * é coisa diferente de «não saiu do papel» (projeto cadastrado cuja data
 * prevista já passou). A cobrança de cada uma é com gente diferente, e somá-las
 * esconderia as duas — a primeira versão desta tela abria Nova Palma com 27 de
 * 30 obras "urgentes", que é o mesmo que nenhuma.
 *
 * ⚠️ E QUANDO NÃO HÁ DADO, A TELA NÃO CONCLUI "o município não tem obra". O
 * vínculo é por CNPJ e a coleta é nossa: a ausência pode ser nossa, e afirmar o
 * contrário seria acusar a prefeitura de uma omissão que ela não cometeu.
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle, CalendarClock, CheckCircle2, ExternalLink, HardHat,
  Layers, Loader2, TrendingUp,
} from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { useAnoCorrentePadrao } from "@/lib/anoPadrao";
import {
  Bloco, BlocoHead, Campos, ItemLinha, Lista, Numero, Selo, Vazio,
  situacaoTom,
} from "@/components/ui/superficies";
import { TituloTela } from "@/components/TituloTela";

interface Obra {
  id_unico: string;
  nome: string | null;
  descricao: string | null;
  funcao_social: string | null;
  meta_global: string | null;
  natureza: string | null;
  especie: string | null;
  situacao: string | null;
  endereco: string | null;
  cep: string | null;
  data_inicial_prevista: string | null;
  data_final_prevista: string | null;
  data_inicial_efetiva: string | null;
  data_final_efetiva: string | null;
  data_cadastro: string | null;
  populacao_beneficiada: number | null;
  empregos_gerados: number | null;
  valor: number | null;
  origens_recurso: string[];
  eixos: string[];
  tipos: string[];
  tomadores: string[];
  executores: string[];
  repassadores: string[];
  sistema_origem: string | null;
  /* ⭐ DE QUEM É A OBRA. `prefeitura` = um CNPJ do município bate com
     tomador/executor; `territorio` = só a geometria do Governo aponta, e o
     dono é outro ente (UFSM, DNIT, IF); `abrangencia` = programa guarda-chuva
     que NÃO é uma obra nesta cidade. Ver o cabeçalho do router. */
  vinculo: "prefeitura" | "territorio" | "abrangencia";
  abrangencia_municipios: number | null;
  ano: number | null;
  url_fonte: string;
  grupo: "acao" | "papel" | "andamento" | "encerradas";
  alerta: string | null;
  motivo: string | null;
}
interface Fatia { nome: string; obras: number; valor: number }
interface Resp {
  tem_dados: boolean;
  motivo?: string;
  totais?: { obras: number; valor: number; valor_acao: number;
    valor_papel: number; empregos: number; populacao: number };
  acao?: Obra[];
  papel?: Obra[];
  andamento?: Obra[];
  encerradas?: Obra[];
  por_situacao?: Fatia[];
  por_eixo?: Fatia[];
  por_sistema?: Fatia[];
  por_origem?: Fatia[];
  anos?: number[];
  guarda_chuva?: { obras: number; valor: number };
  coletado_em?: string | null;
}

const brl = (v: number | null | undefined) =>
  v == null ? "—"
    : v.toLocaleString("pt-BR", { style: "currency", currency: "BRL",
                                 maximumFractionDigits: 0 });
const dia = (s: string | null | undefined) =>
  s ? new Date(s + "T12:00:00").toLocaleDateString("pt-BR") : null;

/** ⚠️ Um selo por alerta, com a palavra que o gestor usaria — e não o código
 *  interno. "prazo_vencido" não é português. */
const ROTULO_ALERTA: Record<string, string> = {
  prazo_vencido: "Prazo vencido",
  nao_comecou: "Não começou",
  paralisada: "Paralisada",
  inacabada: "Inacabada",
  nao_saiu_do_papel: "Não começou",
};

function LinhaObra({ o }: { o: Obra }) {
  const [aberto, setAberto] = useState(false);
  const prazo = dia(o.data_final_prevista);
  const fim = dia(o.data_final_efetiva);
  const inicio = dia(o.data_inicial_efetiva) || dia(o.data_inicial_prevista);

  return (
    <ItemLinha
      titulo={
        <span className="flex flex-wrap items-center gap-1.5">
          <span className="min-w-0">{o.nome || o.id_unico}</span>
          {o.situacao && (
            <Selo tom={situacaoTom(o.situacao)}>{o.situacao}</Selo>
          )}
          {o.alerta && (
            <Selo tom="critico" title={o.motivo || undefined}>
              {ROTULO_ALERTA[o.alerta] || o.alerta}
            </Selo>
          )}
          {/* ⚠️ «A obra está aqui» não é «a obra é da prefeitura». Em Santa
              Maria as obras que só a geometria acha são da UFSM, do DNIT e do
              IF Farroupilha — o município é o lugar, não o dono. */}
          {o.vinculo === "territorio" && (
            <Selo tom="neutro"
                  title="O Governo aponta esta obra no território do município, mas o tomador/executor é outro ente.">
              no território
            </Selo>
          )}
          {o.vinculo === "abrangencia" && (
            <Selo tom="atencao"
                  title={`Programa com geometria em ${o.abrangencia_municipios ?? "centenas de"} municípios — não é uma obra desta cidade.`}>
              programa em {o.abrangencia_municipios ?? "vários"} municípios
            </Selo>
          )}
          {/* A repetição com o SISMOB, dita em voz alta. */}
          {o.sistema_origem === "SISMOB" && (
            <Selo title="Esta obra também aparece na tela Obras da Saúde (SISMOB).">
              também no SISMOB
            </Selo>
          )}
        </span>
      }
      valor={<span className="bi-num">{brl(o.valor)}</span>}
      meta={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
          {o.especie && <span>{o.especie}</span>}
          {o.tipos[0] && <span>{o.tipos[0]}</span>}
          {inicio && <span>início {inicio}</span>}
          {prazo && <span>prazo {prazo}</span>}
          {fim && <span>concluída em {fim}</span>}
        </span>
      }
      onClick={() => setAberto((v) => !v)}
      expandido={aberto}
    >
      {aberto && (
        <div className="mt-2 flex flex-col gap-2">
          {o.motivo && (
            <div className="text-[11px] leading-snug"
                 style={{ color: "var(--bi-crit-ink)" }}>
              {o.motivo}
            </div>
          )}
          <Campos
            cols={2}
            campos={[
              { rotulo: "Identificador (CIPI)", valor: o.id_unico },
              { rotulo: "Sistema de origem", valor: o.sistema_origem || "—" },
              { rotulo: "Natureza", valor: o.natureza || "—" },
              { rotulo: "Espécie", valor: o.especie || "—" },
              { rotulo: "Eixo", valor: o.eixos.join(", ") || "—" },
              { rotulo: "Tipo", valor: o.tipos.join(", ") || "—" },
              { rotulo: "Origem do recurso",
                valor: o.origens_recurso.join(", ") || "—" },
              { rotulo: "Repassador", valor: o.repassadores.join(", ") || "—" },
              { rotulo: "Tomador", valor: o.tomadores.join(", ") || "—" },
              { rotulo: "Executor", valor: o.executores.join(", ") || "—" },
              /* ⚠️ PREVISTO E EFETIVO LADO A LADO, e o vazio fica vazio: é a
                 comparação que denuncia a obra parada. Preencher a efetiva com
                 a prevista apagaria exatamente esse sinal. */
              { rotulo: "Início previsto",
                valor: dia(o.data_inicial_prevista) || "—" },
              { rotulo: "Início efetivo",
                valor: dia(o.data_inicial_efetiva) || "não registrado",
                tom: o.data_inicial_efetiva ? "normal" : "atencao" },
              { rotulo: "Conclusão prevista",
                valor: dia(o.data_final_prevista) || "—" },
              { rotulo: "Conclusão efetiva",
                valor: dia(o.data_final_efetiva) || "não registrada",
                tom: o.data_final_efetiva ? "normal" : "atencao" },
              ...(o.populacao_beneficiada
                ? [{ rotulo: "População beneficiada",
                     valor: o.populacao_beneficiada.toLocaleString("pt-BR") }]
                : []),
              ...(o.empregos_gerados
                ? [{ rotulo: "Empregos gerados",
                     valor: o.empregos_gerados.toLocaleString("pt-BR") }]
                : []),
              ...(o.endereco ? [{ rotulo: "Endereço", valor: o.endereco }] : []),
            ]}
          />
          {o.funcao_social && (
            <div className="text-[11px] leading-snug"
                 style={{ color: "var(--bi-muted)" }}>
              <b>Função social:</b> {o.funcao_social}
            </div>
          )}
          {o.meta_global && (
            <div className="text-[11px] leading-snug"
                 style={{ color: "var(--bi-muted)" }}>
              <b>Meta:</b> {o.meta_global}
            </div>
          )}
          {o.descricao && (
            <div className="text-[11px] leading-snug"
                 style={{ color: "var(--bi-muted)" }}>
              {o.descricao}
            </div>
          )}
          {/* Todo número desta tela é conferível na fonte, uma obra por vez. */}
          <a
            href={o.url_fonte}
            target="_blank"
            rel="noreferrer"
            className="inline-flex w-fit items-center gap-1 text-[11px] underline"
            style={{ color: "var(--bi-accent-ink)" }}
          >
            <ExternalLink className="size-3" />
            conferir esta obra no Obras.gov.br
          </a>
        </div>
      )}
    </ItemLinha>
  );
}

function Distribuicao({ titulo, sub, icon, fatias }: {
  titulo: string; sub?: string;
  icon: React.ComponentType<{ className?: string }>;
  fatias: Fatia[];
}) {
  if (!fatias.length) return null;
  const maior = Math.max(...fatias.map((f) => f.valor), 1);
  return (
    <Bloco className="p-4">
      <BlocoHead icon={icon} titulo={titulo} sub={sub} />
      <ul className="flex flex-col gap-2">
        {fatias.slice(0, 8).map((f) => (
          <li key={f.nome}>
            <div className="flex items-baseline justify-between gap-2 text-[12px]">
              <span className="min-w-0 truncate" title={f.nome}>{f.nome}</span>
              <span className="bi-num shrink-0 text-[11px]"
                    style={{ color: "var(--bi-muted)" }}>
                {f.obras} · {brl(f.valor)}
              </span>
            </div>
            <div className="mt-1 h-1.5 rounded-full"
                 style={{ background: "var(--bi-line)" }}>
              <div
                className="h-1.5 rounded-full"
                style={{ width: `${Math.max(2, (f.valor / maior) * 100)}%`,
                         background: "var(--bi-accent-ink)" }}
              />
            </div>
          </li>
        ))}
      </ul>
    </Bloco>
  );
}

export default function ObrasFederaisPage() {
  const { municipioId } = useMunicipio();
  /* ⚠️ A RESPOSTA GUARDA DE QUAL MUNICÍPIO ELA É, e `carregando` é DERIVADO
     disso — não é um `useState` que o efeito liga e desliga. Duas razões, e a
     segunda é a que importa:
     1. o lint (`react-hooks/set-state-in-effect`) reprova `setState` síncrono
        no corpo de um efeito, porque dispara renderização em cascata;
     2. ao TROCAR de município, um `d` que sobrou do anterior apareceria por um
        quadro com o nome do novo — a tela mostraria as obras de um município
        sob o cabeçalho de outro, que é pior que uma tela em branco. */
  const [res, setRes] = useState<{ mun: string; d: Resp | null; erro: string | null }>(
    { mun: "", d: null, erro: null });
  const [anos, setAnos] = useState<string[]>([]);
  const [situacao, setSituacao] = useState<string>("");

  const daVez = res.mun === municipioId;
  const carregando = !!municipioId && !daVez;
  const d = daVez ? res.d : null;
  const erro = daVez ? res.erro : null;

  useEffect(() => {
    if (!municipioId) return;
    let vivo = true;
    api
      .get<Resp>("/obrasgov", { params: { municipio_id: municipioId } })
      .then((r) => {
        if (vivo) setRes({ mun: municipioId, d: r.data, erro: null });
      })
      .catch((e) => {
        if (vivo) setRes({ mun: municipioId, d: null,
          erro: e?.response?.data?.detail || "Não foi possível carregar." });
      });
    return () => { vivo = false; };
  }, [municipioId]);

  /* ⭐ O ano corrente já vem marcado — pedido do dono, e vale para toda tela
     que filtra por ano. Ver lib/anoPadrao.ts. */
  const aplicarAnos = useCallback((a: string[]) => setAnos(a), []);
  useAnoCorrentePadrao(d?.anos, aplicarAnos);

  const filtrar = useCallback(
    (lista: Obra[] | undefined) =>
      (lista || []).filter(
        (o) =>
          /* ⚠️ O GUARDA-CHUVA SAI DAQUI e vai para bloco próprio. Medido no
             freitas: 56 projetos «abrangencia» somam R$ 15,89 BILHÕES contra
             R$ 606,8 mi de TODAS as 421 obras da prefeitura — 96% do valor. É o
             mesmo projeto repetido («Manutenção rodoviária na malha federal do
             DNIT em MG», 790 municípios) caindo em 41 das 42 cidades. Deixá-lo
             nas listas classificadas também poria 56 obras do DNIT no topo de
             «Exigem atenção», empurrando para baixo a obra que é da cidade. */
          o.vinculo !== "abrangencia" &&
          (!anos.length || (o.ano != null && anos.includes(String(o.ano)))) &&
          (!situacao || o.situacao === situacao),
      ),
    [anos, situacao],
  );

  const acao = useMemo(() => filtrar(d?.acao), [d, filtrar]);
  const papel = useMemo(() => filtrar(d?.papel), [d, filtrar]);
  const andamento = useMemo(() => filtrar(d?.andamento), [d, filtrar]);
  const encerradas = useMemo(() => filtrar(d?.encerradas), [d, filtrar]);
  const visiveis = acao.length + papel.length + andamento.length
    + encerradas.length;
  /* Os programas que passam pelo município, no mesmo filtro de ano e situação
     das demais — mas contados à parte. */
  const guardaChuva = useMemo(() => {
    const todas = [...(d?.acao || []), ...(d?.papel || []),
                   ...(d?.andamento || []), ...(d?.encerradas || [])];
    return todas.filter(
      (o) =>
        o.vinculo === "abrangencia" &&
        (!anos.length || (o.ano != null && anos.includes(String(o.ano)))) &&
        (!situacao || o.situacao === situacao),
    );
  }, [d, anos, situacao]);
  /* ⚠️ Os totais dos cartões acompanham o FILTRO, e não os totais do servidor.
     Cartão dizendo 360 com 12 obras na lista abaixo é o tipo de divergência que
     faz o gestor desconfiar de tudo o mais que a tela diz. */
  const somaVisivel = useMemo(
    () => [...acao, ...papel, ...andamento, ...encerradas]
      .reduce((s, o) => s + (o.valor || 0), 0),
    [acao, papel, andamento, encerradas],
  );

  if (!municipioId) {
    return <Vazio>Selecione um município para ver as obras federais.</Vazio>;
  }
  if (carregando) {
    return (
      <div className="flex items-center gap-2 py-6 text-[13px]"
           style={{ color: "var(--bi-muted)" }}>
        <Loader2 className="size-4 animate-spin" /> Carregando obras federais…
      </div>
    );
  }
  if (erro) {
    return <Vazio>{erro}</Vazio>;
  }
  if (!d?.tem_dados) {
    return (
      <Vazio>{d?.motivo || "Sem obras federais coletadas para este município."}</Vazio>
    );
  }

  const t = d.totais!;
  /* ⚠️ A ORDEM CONTA UMA HISTÓRIA, e «não saiu do papel» é seção PRÓPRIA e não
     um pedaço de «exigem atenção»: obra parada se cobra do executor, projeto
     encalhado se cobra do órgão repassador. Somá-las esconderia as duas — e foi
     o que a primeira versão fez, abrindo Nova Palma com 27 de 30 obras
     "urgentes". Ver `_classificar` no router. */
  const secoes: Array<[string, string, Obra[],
    React.ComponentType<{ className?: string }>]> = [
    ["Exigem atenção", "em execução com prazo vencido, paralisada ou inacabada",
     acao, AlertTriangle],
    ["Não saiu do papel", "cadastrada, com a data prevista já vencida",
     papel, CalendarClock],
    ["Em andamento", "dentro do prazo previsto pela fonte", andamento, HardHat],
    ["Encerradas", "concluídas ou canceladas", encerradas, CheckCircle2],
  ];

  return (
    <div className="flex flex-col gap-4">
      <header>
        <TituloTela>Obras Federais</TituloTela>
        <p className="mt-1 max-w-3xl text-[12px] leading-snug"
           style={{ color: "var(--bi-muted)" }}>
          Todas as obras federais do município no Cadastro Integrado de Projetos
          de Investimento (Obras.gov.br) — mobilidade, saneamento, habitação,
          segurança e defesa civil, além das de saúde e educação que também
          aparecem em telas próprias. O município é reconhecido pelo CNPJ.
          {d.coletado_em && (
            <> Coletado em {new Date(d.coletado_em).toLocaleDateString("pt-BR")}.</>
          )}
        </p>
      </header>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Numero icon={HardHat} rotulo="Obras no filtro" valor={visiveis}
                sub={`de ${t.obras} coletada(s)`} />
        <Numero icon={TrendingUp} rotulo="Investimento previsto"
                valor={brl(somaVisivel)}
                sub={anos.length ? `em ${anos.join(", ")}` : "todos os anos"} />
        <Numero icon={AlertTriangle} rotulo="Exigem atenção" valor={acao.length}
                tom={acao.length ? "critico" : "neutro"}
                sub={acao.length ? brl(acao.reduce((s, o) => s + (o.valor || 0), 0))
                                 : "nenhuma obra parada"} />
        {/* ⚠️ O VALOR AQUI É O QUE MAIS DIZ: em Nova Palma são R$ 24,7 milhões
            cadastrados que ainda não viraram canteiro. A contagem sozinha não
            mostraria o tamanho do que está encalhado. */}
        <Numero icon={CalendarClock} rotulo="Não saiu do papel" valor={papel.length}
                tom={papel.length ? "atencao" : "neutro"}
                sub={papel.length ? brl(papel.reduce((s, o) => s + (o.valor || 0), 0))
                                  : "nenhum projeto encalhado"} />
      </div>

      <Bloco className="p-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
            Ano
          </span>
          <div className="flex flex-wrap gap-1.5">
            {(d.anos || []).map((a) => {
              const on = anos.includes(String(a));
              return (
                <button
                  key={a}
                  type="button"
                  onClick={() =>
                    setAnos((atual) =>
                      atual.includes(String(a))
                        ? atual.filter((x) => x !== String(a))
                        : [...atual, String(a)])}
                  className="rounded-full px-2.5 py-1 text-[11px] transition-colors"
                  style={on
                    ? { background: "var(--bi-accent-soft)",
                        color: "var(--bi-accent-ink)" }
                    : { background: "var(--bi-line)", color: "var(--bi-muted)" }}
                >
                  {a}
                </button>
              );
            })}
            {anos.length > 0 && (
              <button
                type="button"
                onClick={() => setAnos([])}
                className="rounded-full px-2.5 py-1 text-[11px] underline"
                style={{ color: "var(--bi-faint)" }}
              >
                todos
              </button>
            )}
          </div>
          <span className="ml-2 text-[11px]" style={{ color: "var(--bi-faint)" }}>
            Situação
          </span>
          <select
            value={situacao}
            onChange={(e) => setSituacao(e.target.value)}
            className="rounded-md px-2 py-1 text-[11px]"
            style={{ background: "var(--bi-surface-2)", color: "var(--bi-text)",
                     border: "1px solid var(--bi-line)" }}
          >
            <option value="">todas</option>
            {(d.por_situacao || []).map((s) => (
              <option key={s.nome} value={s.nome}>
                {s.nome} ({s.obras})
              </option>
            ))}
          </select>
        </div>
      </Bloco>

      {secoes.map(([titulo, sub, lista, icon]) => (
        <Bloco key={titulo} className="p-4">
          <BlocoHead
            icon={icon}
            titulo={titulo}
            sub={sub}
            right={
              <span className="bi-num text-[12px]" style={{ color: "var(--bi-muted)" }}>
                {lista.length}
              </span>
            }
          />
          {lista.length ? (
            <Lista>
              {lista.map((o) => <LinhaObra key={o.id_unico} o={o} />)}
            </Lista>
          ) : (
            <Vazio>
              {titulo === "Exigem atenção"
                ? "Nenhuma obra com prazo vencido ou parada neste filtro."
                : "Nenhuma obra neste filtro."}
            </Vazio>
          )}
        </Bloco>
      ))}

      {guardaChuva.length > 0 && (
        <Bloco className="p-4">
          <BlocoHead
            icon={Layers}
            titulo="Programas que passam pelo município"
            sub="não entram nos totais acima — são obras de abrangência estadual ou nacional"
            right={
              <span className="bi-num text-[12px]" style={{ color: "var(--bi-muted)" }}>
                {guardaChuva.length}
              </span>
            }
          />
          <p className="mb-2 text-[11px] leading-relaxed"
             style={{ color: "var(--bi-muted)" }}>
            O Governo cadastra estes projetos com geometria em dezenas ou
            centenas de municípios — «Manutenção rodoviária na malha federal do
            DNIT», por exemplo, alcança 790 cidades. O programa de fato passa
            por aqui, mas o valor dele é do programa inteiro: somá-lo diria que
            o município tem em obras federais o que o país inteiro tem.
          </p>
          <Lista>
            {guardaChuva.map((o) => <LinhaObra key={o.id_unico} o={o} />)}
          </Lista>
        </Bloco>
      )}

      <div className="grid gap-3 lg:grid-cols-3">
        <Distribuicao titulo="Por eixo" icon={Layers}
                      sub="a área da política pública" fatias={d.por_eixo || []} />
        <Distribuicao titulo="Por origem do recurso" icon={TrendingUp}
                      sub="quem paga a obra" fatias={d.por_origem || []} />
        {/* ⚠️ Este bloco é o que torna a repetição HONESTA: ele mostra quantas
            destas obras chegam também por outra tela nossa. */}
        <Distribuicao titulo="Por sistema de origem" icon={CalendarClock}
                      sub="de onde o Governo cadastrou — SISMOB também aparece em Obras da Saúde"
                      fatias={d.por_sistema || []} />
      </div>
    </div>
  );
}
