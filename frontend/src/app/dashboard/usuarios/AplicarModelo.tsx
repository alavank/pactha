"use client";
// APLICAR UM MODELO — o atalho que impede o administrador de desistir.
//
// O PROBLEMA QUE ISTO RESOLVE E DE OPERACAO, e nao de seguranca: cadastrar um
// servidor novo virou marcar 66 caixas, e um administrador cansado marca TUDO.
// Quando isso acontece, o RBAC inteiro do produto vira decoracao — as 66
// caixinhas continuam la, todas ligadas, agora com 66 linhas no banco para
// disfarcar o velho "admin ve tudo".
//
// ⚠️ E O ATALHO NAO PODE TRAIR A REGRA DO DONO. Aplicar COPIA: as caixinhas sao
// preenchidas e continuam EDITAVEIS, nada e salvo, e nenhum vinculo sobra entre
// a pessoa e o modelo. Esta tela precisa DIZER isso — se ela nao disser, o
// administrador supoe heranca ("mudo o modelo e todo mundo muda junto"), deixa
// de conferir o cadastro individual e configura errado achando que acertou.
// Por isso a frase da copia e fixa no topo, e nao um texto de ajuda escondido.
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Check, Copy, Lock, Undo2 } from "lucide-react";
import {
  AcaoMini, Aviso, Bloco, BlocoHead, BOTAO_CTA, Campos, ESTILO_CTA, Selo,
} from "@/components/ui/superficies";
import type { MapaEscopos } from "@/lib/escopo";
import {
  recursosComEscopo, resumoPorRecurso, type Catalogo,
} from "@/lib/permissoes";
import {
  AVISO_COPIA_RESERVA, mesmoAlcance, mesmoConjunto, MODO_SOMAR,
  MODO_SUBSTITUIR, planoDoModelo, type Modelo, type PlanoModelo,
} from "@/lib/modelos";

/** O que foi aplicado, para o «Desfazer» e para a frase de estado. */
interface Aplicacao {
  nome: string;
  antesSel: Set<string>;
  antesEsc: MapaEscopos;
  depoisSel: Set<string>;
  depoisEsc: MapaEscopos;
}

export default function AplicarModelo({
  alvoId, catalogo, modelos, sel, esc, onAplicar, onDesfazer,
  onSalvarComoModelo,
}: {
  /** De QUEM sao estas permissoes. O plano e calculado no servidor, e o
   *  servidor precisa saber sobre quem — inclusive para recusar o pedido se
   *  quem esta aplicando nao puder mexer nesta pessoa (`_guard_target`). */
  alvoId: number;
  catalogo: Catalogo;
  modelos: Modelo[];
  sel: Set<string>;
  esc: MapaEscopos;
  /* `posso` e `alcanceTravado` SAÍRAM daqui: eram as entradas do
     anti-escalonamento calculado no navegador. Quem responde isso agora é o
     servidor, que é onde a regra já tinha teste. */
  /** Recebe também o MODO, que a tela de cima manda no `PUT` para a trilha
   *  saber de onde a gravação partiu. */
  onAplicar: (sel: Set<string>, esc: MapaEscopos, origem: { modeloId: number; modo: string }) => void;
  /** Volta ao estado de antes do último clique — e sem origem nenhuma. */
  onDesfazer: (sel: Set<string>, esc: MapaEscopos) => void;
  /** Vira o caminho de criacao a partir DAQUI: o administrador configura uma
   *  pessoa inteira e transforma aquilo num molde. So aparece para quem pode
   *  gerir modelos. */
  onSalvarComoModelo?: () => void;
}) {
  const [escolhido, setEscolhido] = useState<number | null>(null);
  const [aplicado, setAplicado] = useState<Aplicacao | null>(null);
  /* O modo VIVE no catálogo (rótulo e explicação vêm de lá). Sem o campo, a
     tela não oferece escolha nenhuma e substitui — que é o padrão do servidor
     e o que não concede nada por acidente. */
  const modosOferecidos = catalogo.modelos?.modos ?? [];
  const [modo, setModo] = useState<string>(
    catalogo.modelos?.default ?? MODO_SUBSTITUIR,
  );

  const comEscopo = useMemo(() => recursosComEscopo(catalogo), [catalogo]);
  const modelo = modelos.find((m) => m.id === escolhido) ?? null;

  /* ⭐ O PLANO VEM DO SERVIDOR. Antes esta tela recalculava a regra em
     TypeScript — uma segunda implementacao de `aplicar_modelo`, que tem 65
     testes no backend e nenhum aqui (o frontend nao tem runner). A copia sem
     teste era justamente a que rodava. Enquanto as duas concordassem ninguem
     veria nada; divergindo, a tela proporia uma caixinha que o `PUT` recusa e o
     administrador levaria um 403 sem entender o que fez. */
  /* ⚠️ O PLANO ANDA CARIMBADO com a pergunta que o gerou (modelo + modo +
     caixinhas + alcance). Sem o carimbo, trocar de modelo — ou marcar uma
     caixinha — deixaria na tela os números da pergunta ANTERIOR até a resposta
     nova chegar, e "A desmarcar 3" do modelo errado é pior que número nenhum.
     Também é o que dispensa `setPlano(null)` dentro do efeito: o plano velho
     simplesmente deixa de casar, sem render em cascata. */
  const [plano, setPlano] = useState<{ carimbo: string; dados: PlanoModelo } | null>(null);
  const [calculando, setCalculando] = useState(false);
  const [erroPlano, setErroPlano] = useState<{ carimbo: string; texto: string } | null>(null);

  /* Chaves ESTAVEIS: `sel` e `esc` sao objetos novos a cada render, e usa-los
     crus na dependencia dispararia uma requisicao por render. */
  const selChave = useMemo(() => [...sel].sort().join(","), [sel]);
  const escChave = useMemo(() => JSON.stringify(esc), [esc]);
  const carimbo = `${modelo?.id ?? 0}|${modo}|${selChave}|${escChave}`;

  const planoAtual = plano?.carimbo === carimbo ? plano.dados : null;
  const erroAtual = erroPlano?.carimbo === carimbo ? erroPlano.texto : null;

  useEffect(() => {
    if (!modelo) return;
    /* ESPERA 350ms. O modal e editavel, e o administrador marca varias
       caixinhas seguidas — sem isto seria uma requisicao por clique. Com a
       pausa, e uma por respiro. */
    let vivo = true;
    const t = setTimeout(() => {
      setCalculando(true);
      planoDoModelo(modelo.id, alvoId, modo, sel, esc)
        .then((p) => { if (vivo) setPlano({ carimbo, dados: p }); })
        .catch((e) => {
          if (!vivo) return;
          setErroPlano({
            carimbo,
            texto:
              (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
              || "Não foi possível calcular o que este modelo faria.",
          });
        })
        .finally(() => { if (vivo) setCalculando(false); });
    }, 350);
    return () => { vivo = false; clearTimeout(t); };
    // `sel`/`esc` e o modelo entram pelo `carimbo`, que é o que muda a resposta.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [carimbo, alvoId]);

  /* O servidor devolve CHAVES; a tela mostra RÓTULOS. O dicionário é o do
     catálogo — nenhuma palavra deste subsistema é reescrita aqui. */
  const rotuloDe = useMemo(() => {
    const m = new Map<string, string>();
    for (const p of catalogo.permissoes) m.set(p.chave, p.rotulo);
    return (c: string) => m.get(c) ?? c;
  }, [catalogo]);

  const rotuloDoModulo = useMemo(() => {
    const m = new Map<string, string>();
    for (const sec of catalogo.secoes) {
      for (const r of sec.recursos) m.set(r.recurso, r.recurso_rotulo);
    }
    return (r: string) => m.get(r) ?? r;
  }, [catalogo]);

  /** A aplicacao ainda esta INTACTA? Depois que o administrador mexe numa
   *  caixinha, «Desfazer» deixaria de cancelar aquele clique e passaria a jogar
   *  fora o ajuste dele junto — entao o botao some e a frase muda. */
  const intacto = !!aplicado
    && mesmoConjunto(sel, aplicado.depoisSel)
    && mesmoAlcance(esc, aplicado.depoisEsc, comEscopo);

  const aplicar = () => {
    /* `planoAtual`, e não `plano`: o guard tem de ser o MESMO que a tela usa
       para desenhar o botão, senão o clique aplicaria um plano vencido. */
    if (!modelo || !planoAtual) return;
    setAplicado({
      nome: modelo.nome,
      antesSel: new Set(sel),
      antesEsc: { ...esc },
      depoisSel: planoAtual.sel,
      depoisEsc: planoAtual.esc,
    });
    onAplicar(planoAtual.sel, planoAtual.esc, { modeloId: modelo.id, modo });
  };

  const desfazer = () => {
    if (!aplicado) return;
    /* Desfazer também apaga a ORIGEM: o Salvar seguinte não parte de modelo
       nenhum, e dizer à trilha que partiu seria contar uma história que não
       aconteceu. */
    onDesfazer(new Set(aplicado.antesSel), { ...aplicado.antesEsc });
    setAplicado(null);
  };

  return (
    <Bloco className="p-3">
      <BlocoHead
        icon={Copy}
        titulo="Aplicar um modelo"
        sub="O atalho para não marcar 66 caixinhas a cada cadastro."
        right={onSalvarComoModelo && (
          <AcaoMini onClick={onSalvarComoModelo}>Salvar como modelo</AcaoMini>
        )}
      />

      {/* A FRASE DA CÓPIA. Fica sempre visível, e não atrás de um ícone de
          ajuda: é ela que impede o administrador de supor herança. O texto vem
          do catálogo da API — nenhuma palavra deste subsistema é reescrita
          aqui (ver `lib/permissoes.ts`); a reserva só existe para o bloco nunca
          ficar calado sobre a cópia. */}
      <p className="text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
        {catalogo.modelos?.aviso ?? AVISO_COPIA_RESERVA}
      </p>

      {aplicado && (
        /* Estado, e não alerta: sem cor. O que ele responde é "eu cliquei e
           mudou alguma coisa?", que é a pergunta de quem acabou de aplicar e
           está olhando para 66 caixinhas embaralhadas. */
        <div className="bi-card-flat mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2">
          <Check className="size-3.5 shrink-0" style={{ color: "var(--bi-ok-ink)" }} />
          <span className="min-w-0 flex-1 text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
            {intacto ? (
              <>
                Modelo <b style={{ color: "var(--bi-text)" }}>{aplicado.nome}</b> copiado
                para as caixinhas. <b style={{ color: "var(--bi-text)" }}>Nada foi salvo</b> ainda.
              </>
            ) : (
              <>
                Modelo <b style={{ color: "var(--bi-text)" }}>{aplicado.nome}</b> copiado
                e depois ajustado à mão — vale o ajuste.
              </>
            )}
          </span>
          {intacto && (
            <AcaoMini onClick={desfazer}>
              <span className="flex items-center gap-1"><Undo2 className="size-3" /> Desfazer</span>
            </AcaoMini>
          )}
        </div>
      )}

      {modelos.length === 0 ? (
        <p className="mt-2 text-[11px] leading-snug" style={{ color: "var(--bi-faint)" }}>
          Nenhum modelo cadastrado. Dá para marcar as caixinhas à mão e depois
          guardar esta configuração como modelo, para o próximo cadastro sair em
          um clique.
        </p>
      ) : (
        /* SEM `role="radiogroup"` aqui de propósito: cada cartão abre uma prévia
           inteira dentro de si (e outro grupo de rádios, o do modo), e um
           radiogroup cujos filhos não são rádios promete ao leitor de tela uma
           navegação por setas que não existe. Os `<input type="radio">` com o
           mesmo `name` já se agrupam nativamente. */
        <div className="mt-2 flex flex-col gap-1.5">
          {modelos.map((m) => {
            const escolhidoAqui = m.id === escolhido;
            return (
              <div key={m.id} className="bi-card-flat px-3 py-2.5">
                <label className="flex cursor-pointer items-start gap-2">
                  <input
                    type="radio"
                    name="modelo-aplicar"
                    checked={escolhidoAqui}
                    onChange={() => setEscolhido(m.id)}
                    className="mt-0.5 size-3.5 shrink-0"
                    style={{ accentColor: "var(--bi-cta)" }}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-1.5">
                      <span className="text-[12px] font-medium leading-tight" style={{ color: "var(--bi-text)" }}>
                        {m.nome}
                      </span>
                      <Selo title="Caixinhas que este modelo marca.">
                        {m.permissoes.length} caixinha(s)
                      </Selo>
                    </span>
                    {m.descricao && (
                      <span className="mt-0.5 block text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                        {m.descricao}
                      </span>
                    )}
                  </span>
                </label>

                {/* ⚠️ ENQUANTO A CONTA NÃO CHEGA, e se ela FALHAR, a tela tem de
                    dizer. Sem estas duas linhas o bloco simplesmente não
                    aparece — e "não apareceu" é indistinguível de "este modelo
                    não faz nada", que é a leitura errada mais cara possível
                    aqui: o administrador conclui que já está tudo certo e vai
                    embora sem aplicar. */}
                {escolhidoAqui && !planoAtual && (
                  <p
                    className="mt-2 border-t pt-2 text-[11px] leading-snug"
                    style={{
                      borderColor: "var(--bi-line)",
                      color: erroAtual ? "var(--bi-crit-ink)" : "var(--bi-faint)",
                    }}
                  >
                    {erroAtual ?? (calculando
                      ? "Calculando o que este modelo faria nesta pessoa…"
                      : "Conferindo o que este modelo faria nesta pessoa…")}
                  </p>
                )}

                {escolhidoAqui && planoAtual && (
                  <div className="mt-2 border-t pt-2" style={{ borderColor: "var(--bi-line)" }}>
                    {/* COMO APLICAR — só onde há escolha de verdade. Rádio e não
                        interruptor: são dois estados NOMEADOS, e o padrão
                        («substituir») precisa estar escrito. Os textos vêm do
                        catálogo. */}
                    {modosOferecidos.length > 1 && (
                      <div
                        role="radiogroup"
                        aria-label="Como aplicar este modelo"
                        className="mb-2 flex flex-col gap-1.5 border-b pb-2"
                        style={{ borderColor: "var(--bi-line)" }}
                      >
                        <span className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>
                          Como aplicar
                        </span>
                        {modosOferecidos.map((op) => (
                          <label key={op.valor} className="flex cursor-pointer items-start gap-2">
                            <input
                              type="radio"
                              name={`modo-${m.id}`}
                              checked={modo === op.valor}
                              onChange={() => setModo(op.valor)}
                              className="mt-0.5 size-3.5 shrink-0"
                              style={{ accentColor: "var(--bi-cta)" }}
                            />
                            <span className="min-w-0 flex-1">
                              <span className="text-[12px] font-medium leading-tight" style={{ color: "var(--bi-text)" }}>
                                {op.rotulo}
                              </span>
                              <span className="mt-0.5 block text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                                {op.descricao}
                              </span>
                            </span>
                          </label>
                        ))}
                      </div>
                    )}

                    <div className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>
                      O que este modelo marca
                    </div>
                    <ul className="mt-1 flex flex-col gap-0.5 text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                      {resumoPorRecurso(catalogo, new Set(m.permissoes), undefined, m.escopos).map((l) => (
                        /* Marcador escrito à mão: o reset de CSS do projeto tira
                           o `list-style` e as linhas viram um parágrafo só. */
                        <li key={l} className="flex gap-1.5">
                          <span aria-hidden style={{ color: "var(--bi-faint)" }}>·</span>
                          <span className="min-w-0">{l}</span>
                        </li>
                      ))}
                      {m.permissoes.length === 0 && (
                        /* Modelo vazio faz coisas OPOSTAS nos dois modos, e a
                           frase tem de acompanhar: substituindo ele zera a
                           pessoa; somando não faz nada. */
                        <li style={{ color: "var(--bi-faint)" }}>
                          Nenhuma caixinha —{" "}
                          {modo === MODO_SOMAR
                            ? "somando, este modelo não muda nada."
                            : "este modelo zera as permissões da pessoa."}
                        </li>
                      )}
                    </ul>

                    {/* Os três números em POSIÇÕES FIXAS: é o que o clique vai
                        fazer NESTA pessoa, e não o que o modelo tem. */}
                    <Campos
                      cols={3}
                      campos={[
                        { rotulo: "A marcar", valor: planoAtual.vaiConceder.length },
                        {
                          rotulo: "A desmarcar",
                          valor: planoAtual.vaiRetirar.length,
                          // Cor só quando há o que perder: é a única parte deste
                          // clique que tira algo de um cadastro já feito.
                          tom: planoAtual.vaiRetirar.length > 0 ? "atencao" : "normal",
                          title: planoAtual.vaiRetirar.length > 0
                            ? planoAtual.vaiRetirar.map(rotuloDe).join(", ")
                            : "Nada do que está marcado hoje sai.",
                        },
                        {
                          rotulo: "Alcance alterado",
                          valor: planoAtual.alcanceAlterado.length,
                          // Já vêm como frase pronta do servidor ("Gestão
                          // Interna: Somente os que ele criou").
                          title: planoAtual.alcanceAlterado.length > 0
                            ? planoAtual.alcanceAlterado.join(", ")
                            : "Nenhum módulo muda de alcance.",
                        },
                      ]}
                    />

                    <p className="mt-2 text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                      {/* A regra do modo só é escrita aqui quando o catálogo não
                          a trouxe: com o seletor acima, ela já está dita — e por
                          quem manda nela. */}
                      {modosOferecidos.length > 1 ? null : (
                        <>
                          Aplicar <b style={{ color: "var(--bi-text)" }}>substitui</b> o
                          que está marcado — o modelo é o retrato inteiro do que a
                          pessoa faz, e não um acréscimo.{" "}
                        </>
                      )}
                      Nada é gravado agora: enquanto você não clicar em{" "}
                      <b style={{ color: "var(--bi-text)" }}>Salvar permissões</b>, dá
                      para desfazer.
                    </p>

                    {(planoAtual.naoAplicadas.length > 0 || planoAtual.preservadas.length > 0
                      || planoAtual.alcanceNaoAplicado.length > 0) && (
                      /* ⚠️ ANTI-ESCALONAMENTO, dito em português. Sem esta
                         faixa, o administrador leria o nome do modelo e
                         acreditaria que a pessoa ficou exatamente como ele
                         diz — quando o que ele não possui não foi nem
                         concedido nem retirado. O servidor recusa o mesmo. */
                      <Aviso
                        tom="atencao"
                        icon={Lock}
                        titulo="Este modelo não vai ser aplicado por inteiro."
                        className="mt-2"
                      >
                        <ul className="flex flex-col gap-1 text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                          {planoAtual.naoAplicadas.length > 0 && (
                            <li>
                              <b style={{ color: "var(--bi-text)" }}>
                                {planoAtual.naoAplicadas.length} caixinha(s) não vão ser concedidas
                              </b>{" "}
                              porque você não as tem: {planoAtual.naoAplicadas.map(rotuloDe).join(", ")}.
                            </li>
                          )}
                          {planoAtual.preservadas.length > 0 && (
                            <li>
                              <b style={{ color: "var(--bi-text)" }}>
                                {planoAtual.preservadas.length} caixinha(s) continuam marcadas
                              </b>{" "}
                              mesmo não estando no modelo, porque você não as tem para
                              poder retirar: {planoAtual.preservadas.map(rotuloDe).join(", ")}.
                            </li>
                          )}
                          {planoAtual.alcanceNaoAplicado.length > 0 && (
                            <li>
                              O alcance de{" "}
                              <b style={{ color: "var(--bi-text)" }}>
                                {planoAtual.alcanceNaoAplicado.map(rotuloDoModulo).join(", ")}
                              </b>{" "}
                              fica como está: nesses módulos você alcança só o próprio
                              trabalho, então não define o de outra pessoa.
                            </li>
                          )}
                        </ul>
                      </Aviso>
                    )}

                    <div className="mt-2 flex flex-wrap items-center justify-end gap-2">
                      {!planoAtual.mudou && (
                        <span className="mr-auto flex items-start gap-1 text-[11px] leading-snug" style={{ color: "var(--bi-faint)" }}>
                          <AlertTriangle className="mt-px size-3.5 shrink-0" />
                          As caixinhas já estão exatamente assim.
                        </span>
                      )}
                      <button
                        type="button"
                        className={BOTAO_CTA}
                        style={ESTILO_CTA}
                        onClick={aplicar}
                        disabled={!planoAtual.mudou || calculando}
                        title="Preenche as caixinhas abaixo. Nada é salvo agora."
                      >
                        <Copy className="size-4" />
                        Aplicar às caixinhas
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Bloco>
  );
}
