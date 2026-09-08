// A ÁREA ÚTIL DO DASHBOARD — um valor, um lugar.
//
// Existe porque em 07/09/2026 o dono mandou um print com setas desenhadas por
// cima: "cada um segue um tamanho, e isso não pode; tem que aproveitar a tela".
// O `dashboard/layout.tsx` tinha três regimes de largura (largura toda,
// `max-w-[1600px]` e `max-w-7xl`), e numa janela de 1920 isso dava três margens
// esquerdas diferentes conforme o item de menu clicado.
//
// ⚠️ NÃO ACRESCENTE UM `max-w` AQUI. A largura útil é a da janela; o limite de
// linha legível é assunto do PARÁGRAFO (`max-w-3xl` no `<p>` de cada tela), não
// da página — travar a página inteira para proteger o parágrafo custava ~700px
// de dado em toda tela que é grade, cartão ou lista, que são todas.
//
// Quem usa:
//  · `dashboard/layout.tsx`, no contêiner de toda tela que não seja `telaCheia`;
//  · as `telaCheia` (Painel de Indicadores e Agendamentos), que não recebem o
//    padding do contêiner porque pintam fundo próprio até a borda — e por isso
//    aplicam este mesmo valor por dentro.
//
// Mudar aqui muda nos três. É exatamente isso que a constante existe para
// garantir: a divergência anterior nasceu de cada um escrever o seu.
export const PADDING_PADRAO = "px-4 py-5 sm:px-6 lg:px-8";
