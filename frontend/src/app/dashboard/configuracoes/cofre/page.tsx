/* Aba de Configurações — a MESMA tela de /dashboard/cofre.
 *
 * Re-export e não cópia: a página original segue no lugar (bookmarks antigos
 * continuam funcionando) e os módulos irmãos que ela importa por caminho
 * relativo resolvem no diretório de origem. Mover os arquivos arrastaria
 * PermissoesModal/ModelosModal/etc. junto, sem ganho. */
export { default } from "@/app/dashboard/cofre/page";
