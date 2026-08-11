"use client";

import { SlidersHorizontal } from "lucide-react";
import { Bloco, BlocoHead, Vazio } from "@/components/ui/superficies";

/** ⭐ PARÂMETROS — o que o cliente cadastra para o sistema usar.
 *
 *  A aba nasce aqui, na estrutura, e ganha o primeiro tipo de parâmetro
 *  (Perfil/Rótulo de usuário) no incremento seguinte. Ela aparece desde já de
 *  propósito: o dono pediu a casa de Configurações inteira, e uma aba anunciada
 *  no menu que ainda não existe é pior que uma aba honesta dizendo o que vem.
 *
 *  ⚠️ Cada cliente terá os SEUS parâmetros. Isso não custa código: o PACTHA é
 *  single-tenant — cada cliente tem o próprio banco —, então "não compartilhar
 *  com outro cliente" já é o comportamento natural da tabela.
 */
export default function ParametrosPage() {
  return (
    <div className="space-y-4">
      <Bloco className="p-4">
        <BlocoHead
          icon={SlidersHorizontal}
          titulo="Parâmetros do ambiente"
          sub="Listas que este cliente cadastra e o sistema usa nos formulários"
        />
        <Vazio>
          Em breve: cadastro dos <b>Perfis (Rótulos)</b> de usuário deste ambiente —
          o que hoje é uma lista fixa (Administrador, Usuário, Prefeito) passa a
          ser cadastrável aqui, e o cadastro de usuários puxa direto desta lista.
        </Vazio>
      </Bloco>
    </div>
  );
}
