import type { Visao } from "./painel";
import { formatCurrencyShort as money, formatInt as int } from "./format";
import { labelAno } from "./period";

// Textos em linguagem NÃO-técnica para o prefeito, derivados dos números.
// (Quando o backend com IA/Haiku estiver no ar, esta camada é substituída pela
// narrativa gerada; a assinatura das funções permanece.)

export function resumoExecutivo(v: Visao, ano: number | null): string {
  const k = v.kpis;
  const total = (k.valor_total_estadual || 0) + (k.valor_total_federal || 0);
  const nome = k.municipio.nome;
  const p: string[] = [];
  p.push(`Em ${labelAno(ano)}, ${nome} garantiu ${money(total)} em recursos, distribuídos em ${int(k.total_voluntarias)} propostas federais.`);
  if (v.semaforo.regular) {
    p.push(`A documentação está 100% em dia no CAUC — o município segue apto a receber novas transferências da União.`);
  } else {
    p.push(`Há ${int(v.semaforo.pendencias || 0)} pendência(s) no CAUC que podem travar novos repasses; regularizar é prioridade.`);
  }
  if (k.alertas_prestacao_contas > 0) {
    p.push(`Ponto de atenção: ${int(k.alertas_prestacao_contas)} convênios estão com prestação de contas vencida — regularizar libera novas captações.`);
  }
  return p.join(" ");
}

export function destaqueParlamentar(
  v: Visao,
  filtro: (nomeNorm: string, municipio: string) => boolean
): string | null {
  const nome = v.kpis.municipio.nome;
  const top = (v.top_parlamentares || []).filter((p) => filtro(p.nome_normalizado, nome))[0];
  if (!top) return null;
  return `${top.nome_display} foi quem mais destinou recurso ao município, somando ${money(top.valor_total)} em ${int(top.total_lancamentos)} lançamentos.`;
}

export function destaqueSaude(v: Visao): string | null {
  if (!v.saude) return null;
  const s = v.saude;
  if (s.divida_atual <= 0) return null;
  return `Na saúde, o Estado ainda deve ${money(s.divida_atual)} ao Fundo Municipal (Acordo FES) — de ${money(s.inicial)}, já foram pagos ${money(s.pago)}.`;
}
