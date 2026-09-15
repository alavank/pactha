-- migration: a-cada-boot
-- (a marca acima faz o runner rodar este arquivo em TODO boot, mesmo ja
-- registrado em `migrations_aplicadas` — ver `services/startup.py`)
--
-- SEMENTE DO super_admin — os QUATRO e-mails, e so eles. Era a secao 4 de
-- `add_role_vira_rotulo.sql` ate 15/09/2026; saiu de la para ser a UNICA coisa
-- que roda em todo boot (o resto daquele arquivo roda uma vez, e o `ALTER TABLE
-- users` dele pediria lock em todo start se o arquivo inteiro fosse marcado).
--
-- Espelha `services/auth.py::SUPER_ADMIN_EMAILS` (e a copia em
-- setup_db.py::seed_data). `admin@pactha.com.br` saiu da lista em
-- 02/08/2026 e NAO entra aqui: o e-mail era generico e adivinhavel, entao
-- qualquer admin do cliente que o recriasse na tela de Usuarios ganhava
-- poder de dono.
--
-- Roda a CADA boot, de proposito. Sao as contas donas da plataforma e a lista
-- continua no codigo como reforco (`is_super_admin` le a coluna E a lista),
-- entao re-semear aqui nao desfaz decisao de ninguem: apenas mantem o dado
-- igual ao codigo. Cobre tambem o caso de uma dessas contas ser criada num
-- tenant DEPOIS do boot anterior. Conceder super_admin a QUALQUER OUTRO usuario
-- e decisao de runtime, e esta migration nunca encosta nela.
--
-- `AND NOT super_admin` e a guarda contra reescrever a mesma linha em todo
-- start (mesma razao do `AND NOT kiosk` em add_users_kiosk.sql). UPDATE sem
-- DDL: pede so RowExclusive em `users`, que convive com leitura e escrita dos
-- outros — nao e o lock que travava o boot. `lower(btrim(email))` porque a
-- comparacao no codigo tambem e feita em minusculas e sem espaco.
UPDATE users
   SET super_admin = TRUE
 WHERE lower(btrim(email)) IN (
        'super-admin@alavank.com.br',
        'alavank.tecnologia@gmail.com',
        'matheus@alavank.com.br',
        'tiagomiller@alavank.com.br'
       )
   AND NOT super_admin;
