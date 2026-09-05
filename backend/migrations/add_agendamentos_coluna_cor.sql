-- AGENDAMENTOS: cor no cabecalho da coluna do kanban.
--
-- Rodada 1 de ajustes (05/09/2026). O documento de redesenho pedia colunas fixas
-- imutaveis; o dono reviu: TODAS as colunas — inclusive as tres iniciais —
-- passam a ser renomeaveis e a receber uma cor de cabecalho escolhida por quem
-- usa. O que NAO muda: as tres iniciais continuam sem poder ser removidas, e o
-- teto de cinco continua.
--
-- ⚠️ A COR E UM HEX DA MESMA PALETA DO COMPROMISSO (`routers/agendamentos.PALETA`),
-- e nao uma cor clara propria. O cabecalho e desenhado com `color-mix` sobre a
-- superficie do tema (ver `.ag-solto` em globals.css): a MESMA cor sai como
-- pastel no tema claro e como tom escuro discreto no tema escuro. Guardar aqui o
-- pastel ja calculado obrigaria a uma segunda paleta para o tema escuro — que e
-- exatamente a duplicacao que a paleta do compromisso ja evita.
--
-- ⚠️ RENOMEAR A FIXA NAO MEXE NA `chave`. O router continua achando a coluna de
-- entrada por `chave = 'solicitada'` (SERIAL nao promete o mesmo id nos cinco
-- bancos); o `nome` e so o rotulo da tela. Quem renomear «Solicitada» para
-- «Aguardando» continua com a coluna de entrada funcionando.
--
-- Idempotente e aditiva.

ALTER TABLE agendamentos_colunas
    ADD COLUMN IF NOT EXISTS cor VARCHAR(7) NOT NULL DEFAULT '#7b8794';

-- As cores de partida das tres fixas, so onde ninguem escolheu ainda (o UPDATE
-- casa com o DEFAULT). Vem do print de referencia `estilo-usar-cores.jpg`:
-- neutro para a fila de entrada, ambar para o que esta andando, menta para o
-- concluido — a mesma leitura de semaforo que o quadro ja tinha nas cores dos
-- status antigos.
UPDATE agendamentos_colunas SET cor = '#f5b93f'
 WHERE chave = 'em_andamento' AND cor = '#7b8794';
UPDATE agendamentos_colunas SET cor = '#12b886'
 WHERE chave = 'concluida' AND cor = '#7b8794';
