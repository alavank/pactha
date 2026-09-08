"use client";

/* PLANOS DE AÇÃO (FUNDO A FUNDO) — o que justifica o repasse, e de onde ele vem.
 *
 * ⭐ O QUE ESTA TELA MOSTRA QUE «FUNDO NACIONAL DE SAÚDE» NÃO MOSTRA. Aquela
 * conta o repasse consolidado por bloco: o dinheiro que ENTRA. Esta conta o
 * plano de ação que o justifica — diagnóstico, objetivos, vigência — e,
 * sobretudo, a DECOMPOSIÇÃO do valor entre emenda parlamentar, repasse
 * específico, voluntário, recursos próprios e rendimentos. Só por aqui o gestor
 * sabe quanto daquele repasse veio de emenda.
 *
 * ⚠️ E NÃO É SÓ SAÚDE, apesar do nome. Os quatro planos de Nova Palma
 * (R$ 413.420,20) são do MINISTÉRIO DA CULTURA, Lei Aldir Blanc. No tenant
 * trust os órgãos mais frequentes são MinC, SENASP (segurança), SPPE
 * (trabalho), MCID (cidades) e FNDE (educação) — o Ministério da Saúde nem
 * aparece no topo. Por isso o órgão repassador é mostrado em cada linha, e a
 * tela não assume saúde em lugar nenhum.
 *
 * ⚠️ O QUE ESTÁ AQUI É DO MUNICÍPIO, E ISSO CUSTOU UM CONSERTO. O filtro da
 * fonte entrega todo ente SEDIADO na cidade, e a sede do governo estadual é a
 * capital: R$ 470 mi do Estado de Goiás estavam creditados a Goiânia, cujo
 * município tem R$ 73 mi. O coletor passou a descartar ente estadual
 * (`ingestion/faf_planos.py::e_do_municipio`). Se um número aqui parecer grande
 * demais para a cidade, é isso que se deve conferir primeiro.
 *
 * ⚠️ E QUANDO NÃO HÁ DADO, A TELA NÃO CONCLUI "o município não tem plano". A
 * coleta é nossa e diária: a ausência pode ser nossa.
 */

import React, { useEffect, useMemo, useState } from "react";
import {
  Building2, ExternalLink, FileCheck2, Landmark, Loader2, PiggyBank, Wallet,
} from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import {
  Bloco, BlocoHead, Campos, ItemLinha, Lista, Numero, Selo, Vazio,
  situacaoTom,
} from "@/components/ui/superficies";
import { TituloTela } from "@/components/TituloTela";

interface Relatorio {
  id: number | string | null;
  data: string | null;
  tipo: string | null;
  situacao: string | null;
  valor_executado: number | null;
  valor_pendente: number | null;
  resultados: string | null;
}

interface Plano {
  id_plano_acao: string;
  codigo: string | null;
  situacao: string | null;
  inicio_vigencia: string | null;
  fim_vigencia: string | null;
  diagnostico: string | null;
  objetivos: string | null;
  valor_total: number | null;
  valor_emenda: number | null;
  valor_especifico: number | null;
  valor_voluntario: number | null;
  valor_proprios: number | null;
  valor_rendimentos: number | null;
  valor_custeio: number | null;
  valor_investimento: number | null;
  valor_saldo: number | null;
  orgao: string | null;
  sigla_orgao: string | null;
  fundo: string | null;
  ente_recebedor: string | null;
  cnpj_recebedor: string | null;
  tipo_unidade: string | null;
  relatorios: Relatorio[];
  url_fonte: string;
}

interface Origem { chave: string; rotulo: string; valor: number }
interface PorOrgao { sigla: string; orgao: string | null; planos: number; valor: number }

interface Resp {
  tem_dados: boolean;
  motivo?: string;
  itens?: Plano[];
  total?: number;
  valor_total?: number;
  valor_saldo?: number;
  valor_custeio?: number;
  valor_investimento?: number;
  por_origem?: Origem[];
  por_orgao?: PorOrgao[];
  com_relatorio?: number;
  municipio?: { id: number; nome: string; uf: string };
}

const brl = (v: number | null | undefined) =>
  v == null
    ? "—" /* ⚠️ Não "R$ 0,00": plano sem valor declarado não é de graça. */
    : v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

const dataBR = (s: string | null) => (s ? s.split("-").reverse().join("/") : null);

/* A fonte manda `ADITIVACAO_ENVIADA_PARA_ANALISE`. Numa tela lida por gestor,
   caixa-alta com underscore é ruído de banco vazando para a interface. */
const humano = (s: string | null) =>
  s ? s.replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase()) : null;

/* `situacaoTom` é compartilhada por ~15 telas e não conhece o vocabulário desta
   fonte: «AUTORIZADO» é o estado BOM aqui (172 de 204 planos no trust) e cairia
   em cinza. O ajuste fica local de propósito — mexer na função compartilhada
   por causa de uma palavra mudaria a cor das outras catorze. */
const tomDoPlano = (s: string | null) =>
  /autorizad/i.test(s || "") ? ("ok" as const) : situacaoTom(s);

/* O título de um plano é o que ele se propõe a fazer. A fonte não tem campo de
   objeto curto — `objetivos_plano_acao` é texto corrido, às vezes um parágrafo —
   e o código (`30882120200002-001617`) não diz nada a quem lê. Então o objetivo
   truncado vira o título, e o texto inteiro continua no corpo, ao lado do
   diagnóstico. Sem objetivo, o código é melhor que "Plano 1617". */
function tituloDoPlano(p: Plano): string {
  const t = (p.objetivos || "").trim().replace(/\s+/g, " ");
  if (!t) return p.codigo || `Plano ${p.id_plano_acao}`;
  return t.length > 110 ? `${t.slice(0, 110).trimEnd()}…` : t;
}

export default function FafPlanosPage() {
  const { municipioId } = useMunicipio();
  /* ⚠️ A RESPOSTA GUARDA DE QUAL MUNICÍPIO ELA É, e `carregando` é DERIVADO
     disso — mesmo desenho de `parcerias/page.tsx` e pela mesma razão: ao trocar
     de município, um `d` que sobrou do anterior apareceria por um quadro sob o
     cabeçalho do novo, mostrando o plano de uma cidade no nome de outra. */
  const [res, setRes] = useState<{ mun: string; d: Resp | null; erro: string | null }>(
    { mun: "", d: null, erro: null });
  const [orgao, setOrgao] = useState<string>("");

  const daVez = res.mun === municipioId;
  const carregando = !!municipioId && !daVez;
  const d = daVez ? res.d : null;
  const erro = daVez ? res.erro : null;

  useEffect(() => {
    if (!municipioId) return;
    let vivo = true;
    api
      .get<Resp>("/faf-planos", { params: { municipio_id: municipioId } })
      .then((r) => { if (vivo) setRes({ mun: municipioId, d: r.data, erro: null }); })
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
    return orgao
      ? todos.filter((p) => (p.sigla_orgao || p.orgao || "—") === orgao)
      : todos;
  }, [d, orgao]);

  if (!municipioId) {
    return <Vazio>Selecione um município.</Vazio>;
  }
  if (carregando) {
    return (
      <div className="flex items-center gap-2 py-6 text-sm"
           style={{ color: "var(--bi-muted)" }}>
        <Loader2 className="size-4 animate-spin" /> Carregando planos de ação…
      </div>
    );
  }
  if (erro) return <Vazio>{erro}</Vazio>;
  if (!d?.tem_dados) {
    return (
      <Vazio>{d?.motivo || "Sem planos de ação coletados para este município."}</Vazio>
    );
  }

  const origens = d.por_origem || [];
  const orgaos = d.por_orgao || [];
  const maiorOrigem = Math.max(...origens.map((o) => o.valor), 1);

  return (
    <div className="flex flex-col gap-4">
      {/* ⭐ CABEÇALHO SOLTO — ver a nota gêmea em `parcerias/page.tsx`. Os quatro
          `Numero` já são `bi-card`; dentro de um `Bloco` viravam cartão dentro
          de cartão, encostados na borda do de fora. */}
      <header>
        <TituloTela>Planos de Ação (Fundo a Fundo)</TituloTela>
        <p className="mt-1 max-w-3xl text-[12px] leading-snug"
           style={{ color: "var(--bi-muted)" }}>
          O plano que justifica cada repasse fundo a fundo — diagnóstico,
          objetivos, vigência — e a <b>decomposição do valor</b> que o repasse
          consolidado do Fundo Nacional de Saúde não separa: quanto veio de
          emenda parlamentar, de repasse específico, de recursos próprios.
          Apesar do nome, não é só saúde: cultura, segurança e educação também
          repassam por aqui.
        </p>
      </header>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Numero icon={Landmark} rotulo="Planos" valor={String(d.total ?? 0)} />
        <Numero icon={Wallet} rotulo="Valor total" valor={brl(d.valor_total)} />
        <Numero icon={PiggyBank} rotulo="Saldo disponível"
                valor={brl(d.valor_saldo)} sub="o que ainda não foi usado" />
        {/* ⭐ Prestação de contas é o buraco que esta fonte preenche: a tabela
            `prestacao_contas` é dropada a cada boot, e até aqui ela só existia
            como texto dentro de um campo de situação. */}
        <Numero icon={FileCheck2} rotulo="Com prestação de contas"
                valor={`${d.com_relatorio ?? 0} de ${d.total ?? 0}`} />
      </div>

      {/* ⭐ A DECOMPOSIÇÃO É O PRODUTO DESTA TELA. O ConsultaFNS diz quanto
          entrou; só aqui se sabe quanto daquilo veio de emenda parlamentar. */}
      {origens.length > 0 && (
        <Bloco className="p-3">
          <BlocoHead
            icon={PiggyBank}
            titulo="De onde vem o dinheiro"
            sub="a origem que o repasse consolidado do FNS não separa"
          />
          <div className="space-y-2.5">
            {origens.map((o) => (
              <div key={o.chave}>
                <div className="flex items-baseline justify-between gap-3 text-[12px]">
                  <span>{o.rotulo}</span>
                  <span className="bi-num shrink-0">{brl(o.valor)}</span>
                </div>
                {/* A barra é comparação entre origens, não percentual do total:
                    rendimento de aplicação ao lado de repasse específico ficaria
                    invisível numa escala absoluta. */}
                <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full"
                     style={{ background: "var(--bi-line)" }}>
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${Math.max(2, (o.valor / maiorOrigem) * 100)}%`,
                      background: o.chave === "emenda"
                        ? "var(--bi-accent-ink)" : "var(--bi-muted)",
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-2 text-[11px]"
               style={{ color: "var(--bi-muted)" }}>
            <span>Custeio {brl(d.valor_custeio)}</span>
            <span>·</span>
            <span>Investimento {brl(d.valor_investimento)}</span>
          </div>
        </Bloco>
      )}

      {/* ⚠️ Este bloco é o que desfaz o mal-entendido do nome: «fundo a fundo»
          soa SUS, mas em Nova Palma são quatro planos do Ministério da Cultura.
          Clicar filtra a lista abaixo. */}
      {orgaos.length > 0 && (
        <Bloco className="p-3">
          <BlocoHead
            icon={Building2}
            titulo="Por órgão repassador"
            sub={orgao
              ? `filtrando por ${orgao} — clique de novo para ver todos`
              : "não é só saúde: clique num órgão para filtrar"}
          />
          <Lista>
            {orgaos.map((o) => (
              <ItemLinha
                key={o.sigla}
                titulo={orgao === o.sigla ? `${o.sigla} · filtrando` : o.sigla}
                meta={o.orgao || undefined}
                valor={<span className="bi-num">{brl(o.valor)}</span>}
                onClick={() => setOrgao(orgao === o.sigla ? "" : o.sigla)}
              />
            ))}
          </Lista>
        </Bloco>
      )}

      <Bloco className="p-3">
        <BlocoHead
          icon={Landmark}
          titulo={orgao ? `Planos · ${orgao}` : "Planos de ação"}
          sub={`${itens.length} de ${d.total}`}
        />
        <Lista>
          {itens.map((p) => (
            <LinhaPlano key={p.id_plano_acao} p={p} />
          ))}
        </Lista>
        {itens.length === 0 && <Vazio>Nenhum plano deste órgão.</Vazio>}
      </Bloco>
    </div>
  );
}

/** Um plano na lista — FECHADO por padrão.
 *
 *  ⚠️ ERA ESTA A TELA MAIS MACHUCADA DAS DUAS. Cada plano abria com onze campos
 *  em ONZE COLUNAS (`Campos` sem `cols` abre uma coluna por campo) e, logo
 *  abaixo, o `diagnostico` e os `objetivos` INTEIROS — que na Lei Aldir Blanc
 *  são dois parágrafos de texto legal transcritos por extenso. Quatro planos
 *  davam quatro telas de rolagem de texto jurídico, e o número, que é o que a
 *  tela existe para mostrar, ficava perdido no meio.
 *
 *  Fechado, o item é título + selos + valor. Aberto, ele entrega o dossiê
 *  inteiro — nada foi removido, só deixou de ser obrigatório. */
function LinhaPlano({ p }: { p: Plano }) {
  const [aberto, setAberto] = useState(false);
  return (
    <ItemLinha
      titulo={tituloDoPlano(p)}
      valor={<span className="bi-num">{brl(p.valor_total)}</span>}
      onClick={() => setAberto((v) => !v)}
      expandido={aberto}
      meta={
        <span className="flex flex-wrap items-center gap-1.5">
          <Selo tom={tomDoPlano(p.situacao)}>{humano(p.situacao) || "—"}</Selo>
          {p.sigla_orgao && (
            <Selo tom="neutro" title={p.orgao || undefined}>{p.sigla_orgao}</Selo>
          )}
          {p.relatorios.length > 0 && (
            <Selo tom="ok">
              <FileCheck2 className="mr-1 inline size-3" />
              {p.relatorios.length} relatório
              {p.relatorios.length > 1 ? "s" : ""}
            </Selo>
          )}
          {(p.inicio_vigencia || p.fim_vigencia) && (
            <span>
              {dataBR(p.inicio_vigencia) || "?"} a {dataBR(p.fim_vigencia) || "?"}
            </span>
          )}
        </span>
      }
    >
      {aberto && (
        <div className="mt-2 flex flex-col gap-2">
          <Campos
            cols={4}
            campos={[
              { rotulo: "Emenda parlamentar", valor: brl(p.valor_emenda) },
              { rotulo: "Repasse específico", valor: brl(p.valor_especifico) },
              { rotulo: "Repasse voluntário", valor: brl(p.valor_voluntario) },
              { rotulo: "Recursos próprios", valor: brl(p.valor_proprios) },
              { rotulo: "Rendimentos", valor: brl(p.valor_rendimentos) },
              { rotulo: "Custeio", valor: brl(p.valor_custeio) },
              { rotulo: "Investimento", valor: brl(p.valor_investimento) },
              { rotulo: "Saldo disponível", valor: brl(p.valor_saldo) },
              { rotulo: "Fundo repassador", valor: p.fundo },
              { rotulo: "Recebedor", valor: p.ente_recebedor },
              { rotulo: "Código do plano", valor: p.codigo, mono: true },
            ].filter((c) => c.valor && c.valor !== "—" && c.valor !== "R$ 0,00")}
          />

          {/* ⭐ O TEXTO QUE O FNS NÃO PUBLICA: por que o repasse existe e o que o
              município se comprometeu a fazer com ele. Fica atrás do clique
              porque é dossiê, não linha de lista. */}
          {(p.diagnostico || p.objetivos) && (
            <div className="space-y-1.5 text-[11px] leading-relaxed"
                 style={{ color: "var(--bi-muted)" }}>
              {p.diagnostico && <p><b>Diagnóstico:</b> {p.diagnostico}</p>}
              {p.objetivos && <p><b>Objetivos:</b> {p.objetivos}</p>}
            </div>
          )}

          {p.relatorios.length > 0 && (
            <div>
              <div className="mb-1 text-[11px] font-medium"
                   style={{ color: "var(--bi-muted)" }}>
                Prestação de contas
              </div>
              <Lista>
                {p.relatorios.map((r, i) => (
                  <ItemLinha
                    key={r.id ?? i}
                    titulo={`${humano(r.tipo) || "Relatório"}${
                      r.data ? ` · ${dataBR(r.data)}` : ""}`}
                    meta={
                      <Selo tom={situacaoTom(r.situacao)}>
                        {humano(r.situacao) || "—"}
                      </Selo>
                    }
                    valor={r.valor_executado != null
                      ? <span className="bi-num">executado {brl(r.valor_executado)}</span>
                      : undefined}
                  >
                    {r.resultados ? (
                      <p className="mt-1 text-[11px] leading-relaxed"
                         style={{ color: "var(--bi-faint)" }}>
                        {r.resultados}
                      </p>
                    ) : null}
                  </ItemLinha>
                ))}
              </Lista>
            </div>
          )}

          {/* O link deixa qualquer número desta tela conferível na fonte — a
              mesma disciplina do `url_fonte` das Obras e das Parcerias. */}
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