"use client";

/* A página do menu REGULARIDADE: a tela do município do seletor.
 *
 * O corpo mora em `components/regularidade/RegularidadeTela.tsx` desde
 * 19/09/2026, para o CONSOLIDADO abrir a mesma tela num modal para qualquer
 * município da carteira. Aqui só entra o município selecionado. */

import { useMunicipio } from "@/contexts/MunicipioContext";
import { RegularidadeTela } from "@/components/regularidade/RegularidadeTela";

export default function RegularidadePage() {
  const { municipioId } = useMunicipio();
  return <RegularidadeTela municipioId={municipioId} />;
}
