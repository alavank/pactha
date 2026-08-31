-- SIGCON: apaga a DATA DE PUBLICACAO SUBSTITUTA (1o de janeiro do ano).
--
-- O coletor gravava `date(ano, 1, 1)` em `dt_publicacao` quando nao conseguia
-- abrir o detalhe do convenio. O comentario do codigo dizia com todas as letras
-- que "NAO eh data exata" — era so para a ordenacao do front funcionar. O
-- problema nunca foi o substituto existir: era ele morar na MESMA COLUNA da data
-- verdadeira, sem nada que os separasse depois. E
-- `ConvenioDetailModal.tsx:202` imprime essa coluna como "Data Publicação".
--
-- Medido em Araujos (30/08/2026): 15 dos 28 convenios SIGCON tinham 1o de
-- janeiro gravado — quatro em 2015, cinco em 2017, e um em cada de 2020, 2021,
-- 2023 (dois), 2025 e 2026. Para os mesmos convenios o portal do Estado publica
-- 30/11/2017, 24/12/2015, 08/05/2015...
--
-- O coletor ja parou de gravar o substituto. Este arquivo limpa o que ficou; a
-- data REAL volta pelo `sigcon_ckan_backfill`, que baixa o `dm_convenio` do
-- Estado a cada 6 horas e tem `dt_publicacao` de verdade.
--
-- ⚠️ A ORDENACAO NAO REGRIDE: quem ordenava por esta coluna passa a fazer a
-- queda para 1o de janeiro do `ano` no proprio SQL (routers/convenios.py) — no
-- lugar onde isso e criterio de ordem, e nao fato exibido ao cliente.
--
-- ⚠️ RISCO ACEITO, E PEQUENO: um convenio publicado DE VERDADE em 1o de janeiro
-- seria indistinguivel do substituto e perderia a data. 1o de janeiro e feriado
-- nacional e nao ha publicacao em diario oficial; e o proprio backfill do CKAN
-- repoe a data na rodada seguinte, caso exista.
--
-- ⚠️ SO fonte SIGCON: o FNS e as outras fontes nunca usaram esse substituto.
-- ⚠️ Idempotente: depois da primeira passada nao ha mais linha a casar.

UPDATE convenios_estadual
   SET dt_publicacao = NULL,
       updated_at = NOW()
 WHERE fonte ILIKE 'SIGCON%'
   AND ano IS NOT NULL
   AND dt_publicacao IS NOT NULL
   AND dt_publicacao = make_date(ano, 1, 1);
