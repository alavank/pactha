-- Tipo do link publicado: TV de parede ou aplicativo de celular.
--
-- Sao superficies com comportamento DIFERENTE, nao so tamanho de tela:
--   'tela'   -> /t/<slug>  segue o filtro do dono em tempo real (a TV do
--               gabinete tem de mostrar o que o gestor filtrou no sistema).
--   'mobile' -> /m/<slug>  filtro PROPRIO no aparelho. O prefeito na rua precisa
--               poder mexer no periodo durante uma reuniao sem que isso mude a
--               TV do gabinete — e sem depender de alguem no computador.
--
-- Default 'tela' de proposito: os links que ja existem foram publicados como TV.
ALTER TABLE bi_tela_links
    ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'tela';
