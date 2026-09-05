-- ===========================================================================
-- CADASTRO DE USUARIO: função na organização e WhatsApp (05/09/2026)
-- ===========================================================================
--
-- Pedido do dono, junto do modal unico de Configuracoes › Usuarios:
--
--   `funcao`    o cargo da pessoa na organizacao ("Secretário de
--               Administração", "Contadora"). TEXTO LIVRE de proposito, e nao
--               uma lista em `parametros`: cada prefeitura nomeia os cargos
--               dela, e uma lista fechada aqui seria mais uma tabela para o
--               cliente manter para ganhar nada. Nao concede NADA — e rotulo,
--               como o `role`.
--
--   `whatsapp`  o numero para os disparos que o sistema vai fazer (SMS/WhatsApp
--               pela API oficial da Meta, quando existirem). Guardado como o
--               usuario digitou, sem normalizar: normalizar numero de telefone
--               e decisao de quem for DISPARAR, e faze-lo aqui esconderia o que
--               a pessoa realmente cadastrou de quem for conferir.
--
-- ⚠️ AMBAS OPCIONAIS (sem NOT NULL, sem default). Um cadastro antigo nao tem
-- nenhuma das duas e continua valido; a tela mostra o campo vazio.
--
-- ⚠️ DADO PESSOAL. O WhatsApp entra na mesma categoria do e-mail para a LGPD, e
-- o `GET /api/users` (que ja devolve e-mail) e a unica rota que o expoe — ela
-- exige `usuarios.ver`. Nao entra em `UserResponse` de `/auth/me` por acidente:
-- entra porque a pessoa ve o proprio cadastro.
--
-- Idempotente: `IF NOT EXISTS` nas duas colunas.
-- ===========================================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS funcao VARCHAR(120);
ALTER TABLE users ADD COLUMN IF NOT EXISTS whatsapp VARCHAR(32);

COMMENT ON COLUMN users.funcao IS
    'Cargo na organizacao (texto livre). Rotulo: nao concede permissao nenhuma.';
COMMENT ON COLUMN users.whatsapp IS
    'Telefone para disparos do sistema, como o usuario digitou. Dado pessoal.';
