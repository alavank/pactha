"use client";
// A FRASE QUE EXPLICA O BOTÃO QUE SUMIU.
//
// Sem ela, o efeito do alcance "somente os que ele criou" é uma lista em que
// alguns cartões têm o botão de editar e outros não — e a leitura natural disso
// não é "não é meu", é "o sistema está com defeito". Foi o mesmo raciocínio que
// pôs a linha das caixinhas travadas no modal de permissões.
//
// Por que UMA frase acima da lista, e não um selo em cada linha bloqueada: numa
// lista de quarenta registros em que a pessoa criou três, o selo apareceria
// trinta e sete vezes. Aviso que se repete em quase toda linha deixa de ser
// aviso e vira textura de fundo — e ainda empurra o dado para baixo.
//
// ⚠️ SÓ APARECE NA LISTA MISTA — parte das linhas com botão, parte sem. Essa é a
// assinatura exata da regra de autoria, e é a única situação em que a frase é
// verdadeira. Os dois extremos são outra coisa:
//   · nenhuma linha bloqueada — a esmagadora maioria das contas, que estão em
//     `todos`: a tela fica byte-idêntica ao que era antes deste incremento;
//   · TODAS bloqueadas — aí o motivo não é autoria, é a permissão do verbo
//     faltando (`authz.pode_editar_item` some as duas coisas). Dizer "só os que
//     você criou" ali seria explicar o botão ausente pela razão errada, e mandar
//     a pessoa cobrar do administrador a coisa errada.
import { Lock } from "lucide-react";

export default function AvisoEscopo({
  bloqueadas, total, plural,
}: {
  bloqueadas: number;
  total: number;
  /** O substantivo no plural, com artigo: "os documentos", "as anotações". */
  plural: string;
}) {
  if (bloqueadas <= 0 || bloqueadas >= total) return null;
  return (
    <p
      className="mb-2 flex items-start gap-1.5 px-1 text-[11px]"
      style={{ color: "var(--bi-muted)" }}
    >
      {/* Marcador não-textual: a diferença entre uma linha com botão e uma sem
          é a ausência de um botão, que não se anuncia sozinha. */}
      <Lock className="mt-px size-3.5 shrink-0" style={{ color: "var(--bi-faint)" }} />
      <span>
        Você vê a lista inteira, mas só altera {plural} que <b>você criou</b> —
        {" "}em <b>{bloqueadas} de {total}</b> os botões de editar e excluir não aparecem.
      </span>
    </p>
  );
}
