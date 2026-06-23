"""Schemas dos documentos do módulo "Geração de Documentos".

Fonte ÚNICA de verdade: o mesmo schema dirige (1) o formulário dinâmico no
frontend, (2) o render DOCX e (3) o render PDF. Adicionar um novo tipo de
documento = adicionar um schema aqui.

Estrutura de um schema:
{
  "tipo": "plano_sustentabilidade",
  "titulo": "Plano de Sustentabilidade",
  "secoes": [
     {"titulo": "APRESENTAÇÃO", "campos": [
         {"key","label","tipo","ajuda","opcoes"?,"exemplo"?}, ...]},
     {"titulo": "RISCOS ...", "tipo":"lista", "key":"riscos",
      "item_label":"Risco", "campos":[...]},
  ]
}

Tipos de campo: text | textarea | select | date | currency.
Seção com "tipo":"lista" => repetível; os dados ficam em dados[secao.key] = [ {..}, .. ].
"""
from __future__ import annotations


PLANO_SUSTENTABILIDADE = {
    "tipo": "plano_sustentabilidade",
    "titulo": "Plano de Sustentabilidade",
    "descricao": "Plano que demonstra como o objeto do instrumento será mantido, operado e conservado após a conclusão do convênio/contrato de repasse.",
    "secoes": [
        {
            "titulo": "APRESENTAÇÃO",
            "campos": [
                {"key": "convenio_proposta", "label": "Convênio/Proposta", "tipo": "text",
                 "ajuda": "Informe o número da proposta, do convênio, do contrato de repasse ou de outro instrumento de transferência vinculado ao Plano de Sustentabilidade. Utilize a identificação exatamente como consta no sistema oficial ou no instrumento celebrado."},
                {"key": "objeto", "label": "Objeto", "tipo": "textarea",
                 "ajuda": "Descreva, de forma clara e resumida, o objeto que será executado ou adquirido com os recursos do instrumento. O texto deve corresponder ao objeto aprovado no Plano de Trabalho, sem alterar sua finalidade.",
                 "exemplo": "Aquisição de máquinas e equipamentos conforme detalhado no Plano de Trabalho."},
                {"key": "valor_global", "label": "Valor global", "tipo": "currency",
                 "ajuda": "Informe o valor total do instrumento, correspondente à soma do valor de repasse, da contrapartida e de outros recursos eventualmente previstos."},
                {"key": "valor_repasse", "label": "Valor de repasse", "tipo": "currency",
                 "ajuda": "Informe o valor dos recursos que serão transferidos pelo órgão concedente ou pela União."},
                {"key": "valor_contrapartida", "label": "Valor de contrapartida", "tipo": "text",
                 "ajuda": "Informe o valor da contrapartida financeira ou economicamente mensurável de responsabilidade do convenente. Quando não houver contrapartida, registrar “Não se aplica” ou “R$ 0,00”, conforme o instrumento."},
                {"key": "vigencia", "label": "Vigência", "tipo": "text",
                 "ajuda": "Informe o prazo total de vigência do instrumento, preferencialmente em meses, conforme estabelecido no convênio, contrato de repasse ou instrumento equivalente."},
                {"key": "vigencia_inicio", "label": "Início da vigência", "tipo": "text",
                 "ajuda": "Informe a data de início da vigência ou o evento que determinará seu início, conforme previsto no instrumento.",
                 "exemplo": "A contar da data de publicação do extrato do instrumento no Diário Oficial da União."},
                {"key": "vigencia_termino", "label": "Término da vigência", "tipo": "text",
                 "ajuda": "Informe a data prevista para o encerramento da vigência do instrumento, quando já definida."},
            ],
        },
        {
            "titulo": "OBJETIVOS DO CONVÊNIO",
            "campos": [
                {"key": "objetivo_geral", "label": "Objetivo geral", "tipo": "textarea",
                 "ajuda": "Descreva o principal resultado que o órgão pretende alcançar com a execução do objeto. O objetivo deve estar diretamente relacionado ao problema identificado, à finalidade do programa e aos benefícios esperados para a população."},
                {"key": "objetivos_especificos", "label": "Objetivos específicos", "tipo": "textarea",
                 "ajuda": "Informe os resultados específicos a serem alcançados. Use verbos no infinitivo (melhorar, ampliar, reduzir, fortalecer, proporcionar, garantir, promover, apoiar). Demonstre, quando possível: qual estrutura/serviço será fortalecido; qual problema será reduzido; quais serviços serão ampliados; quem será beneficiado; como contribuirá para o desenvolvimento local; e a relação com as diretrizes do programa federal. Evite descrever procedimentos administrativos."},
            ],
        },
        {
            "titulo": "IMPACTOS SOCIOECONÔMICOS",
            "campos": [
                {"key": "impactos_descricao", "label": "Descrição dos impactos socioeconômicos", "tipo": "textarea",
                 "ajuda": "Descreva os benefícios sociais, econômicos, produtivos, ambientais ou institucionais que permanecerão após a conclusão. Informe como o objeto contribuirá para: melhoria da qualidade de vida; geração/manutenção de emprego e renda; fortalecimento das atividades econômicas locais; redução de custos; melhoria do acesso a serviços públicos; atendimento de comunidades urbanas/rurais; ampliação da capacidade operacional; desenvolvimento sustentável; redução de desigualdades."},
                {"key": "publico_beneficiario", "label": "Público beneficiário", "tipo": "textarea",
                 "ajuda": "Informe quais grupos, comunidades, setores produtivos ou parcelas da população serão direta e indiretamente beneficiados.",
                 "exemplo": "Produtores rurais, agricultores familiares, estudantes, usuários do SUS, moradores da zona rural, servidores municipais ou população em geral."},
                {"key": "area_abrangencia", "label": "Área de abrangência", "tipo": "textarea",
                 "ajuda": "Informe os bairros, distritos, comunidades, zonas rurais, municípios ou regiões que serão atendidos pelo objeto."},
            ],
        },
        {
            "titulo": "DURABILIDADE E MANUTENÇÃO DO OBJETO",
            "campos": [
                {"key": "durabilidade_manutencao", "label": "Durabilidade e manutenção", "tipo": "textarea",
                 "ajuda": "Informe a vida útil estimada do objeto, o responsável por sua manutenção, os procedimentos de manutenção preventiva e corretiva, a periodicidade das intervenções, a forma de controle dos serviços realizados e os recursos disponíveis para garantir sua conservação e funcionamento."},
            ],
        },
        {
            "titulo": "ARMAZENAMENTO E GARANTIA",
            "campos": [
                {"key": "armazenamento_garantia", "label": "Armazenamento e garantia", "tipo": "textarea",
                 "ajuda": "Informe a unidade responsável pela guarda e controle do objeto, o local e as condições de armazenamento, o responsável pelo controle de uso, os dados de contato da unidade, o prazo e a cobertura da garantia e a forma de prestação da assistência técnica durante e após a garantia. Quando não aplicável, apresente a justificativa."},
            ],
        },
        {
            "titulo": "CUSTOS E FONTES DE RECURSOS",
            "campos": [
                {"key": "custos_operacao", "label": "Custos de operação", "tipo": "textarea",
                 "ajuda": "Descreva as despesas necessárias para que o objeto permaneça em funcionamento após a entrega. Ex.: combustível, energia elétrica, água, internet, mão de obra, materiais de consumo, seguros, licenciamento, pneus, peças, lubrificantes, insumos, serviços técnicos, limpeza, vigilância, treinamento de operadores."},
                {"key": "custos_manutencao", "label": "Custos de manutenção", "tipo": "textarea",
                 "ajuda": "Descreva as despesas previstas com manutenção preventiva, corretiva, revisões, reposição de peças, assistência técnica e demais serviços necessários à conservação do objeto."},
                {"key": "responsavel_custos", "label": "Responsável pelos custos", "tipo": "text",
                 "ajuda": "Informe qual órgão ou entidade ficará responsável pelo pagamento das despesas de operação e manutenção após o encerramento do instrumento."},
                {"key": "fonte_recursos", "label": "Fonte dos recursos", "tipo": "textarea",
                 "ajuda": "Informe as fontes orçamentárias ou financeiras que custearão a operação e a manutenção. Ex.: recursos próprios do município, receitas de impostos e transferências, fundos municipais, dotações da secretaria, contratos de manutenção, recursos de programas específicos, outras fontes legalmente disponíveis."},
                {"key": "dotacao_orcamentaria", "label": "Dotação orçamentária", "tipo": "textarea",
                 "ajuda": "Informe, quando disponível, o código da dotação, atividade, projeto, elemento de despesa ou rubrica orçamentária que suportará os custos.",
                 "exemplo": "3.3.90.30 – Material de Consumo; 3.3.90.39 – Outros Serviços de Terceiros – Pessoa Jurídica; 4.4.90.52 – Equipamentos e Material Permanente."},
                {"key": "disponibilidade_futura", "label": "Disponibilidade orçamentária futura", "tipo": "textarea",
                 "ajuda": "Descreva como o órgão garantirá a previsão dos recursos necessários nos orçamentos dos exercícios seguintes.",
                 "exemplo": "Os valores necessários serão previstos anualmente na Lei Orçamentária do Município (informe o número da Lei e seu ano), observada a disponibilidade financeira e orçamentária."},
            ],
        },
        {
            "titulo": "RISCOS E MEDIDAS PREVENTIVAS",
            "tipo": "lista",
            "key": "riscos",
            "item_label": "Risco",
            "ajuda": "Cadastre um item para cada risco identificado.",
            "campos": [
                {"key": "categoria", "label": "Categoria do risco", "tipo": "select",
                 "opcoes": ["Financeiro", "Humano ou técnico", "Ambiental", "Prazo ou tempo",
                            "Material", "Operacional", "Funcionalidade", "Patrimonial",
                            "Jurídico", "Tecnológico", "Segurança", "Outros"],
                 "ajuda": "Selecione a categoria que melhor representa o risco identificado."},
                {"key": "descricao", "label": "Descrição do risco", "tipo": "textarea",
                 "ajuda": "Descreva de forma objetiva o evento que poderá comprometer a execução, a conservação, o funcionamento ou a continuidade do objeto. O risco deve representar uma situação possível e futura.",
                 "exemplo": "Insuficiência de recursos financeiros para realização das manutenções preventivas e corretivas."},
                {"key": "existe", "label": "O risco existe?", "tipo": "select",
                 "opcoes": ["Sim", "Não", "Não se aplica"],
                 "ajuda": "“Sim” quando o risco puder ocorrer; “Não” quando analisado e não relevante; “Não se aplica” quando não tiver relação com a natureza do objeto."},
                {"key": "probabilidade", "label": "Probabilidade", "tipo": "select",
                 "opcoes": ["Baixa", "Média", "Alta"],
                 "ajuda": "Classifique a possibilidade de ocorrência considerando o histórico do órgão, as características do objeto e as condições locais."},
                {"key": "impacto", "label": "Impacto", "tipo": "select",
                 "opcoes": ["Baixo", "Médio", "Alto"],
                 "ajuda": "Classifique os efeitos do risco considerando prejuízos à execução, à conservação, à funcionalidade e ao atendimento da população."},
                {"key": "medidas", "label": "Medidas preventivas", "tipo": "textarea",
                 "ajuda": "Descreva as providências para evitar, reduzir ou controlar o risco. Devem ser específicas, executáveis e compatíveis com a capacidade do órgão (ex.: prever recursos no orçamento, designar responsável, manutenções periódicas, exigir garantia, assistência técnica, controle patrimonial, capacitação, seguro)."},
                {"key": "responsavel", "label": "Responsável pela medida preventiva", "tipo": "text",
                 "ajuda": "Informe o órgão, unidade, setor ou agente público responsável pela implementação e acompanhamento da medida."},
                {"key": "prazo", "label": "Prazo de implementação", "tipo": "text",
                 "ajuda": "Informe quando a medida preventiva deverá ser iniciada ou concluída."},
            ],
        },
        {
            "titulo": "ÓRGÃOS E ENTIDADES RESPONSÁVEIS",
            "campos": [
                {"key": "orgao_responsavel", "label": "Órgão responsável pela sustentabilidade do objeto", "tipo": "text",
                 "ajuda": "Informe o órgão, secretaria, departamento ou entidade responsável pela utilização, conservação, operação, manutenção e continuidade do objeto após a entrega."},
                {"key": "unidade_administrativa", "label": "Unidade administrativa responsável", "tipo": "text",
                 "ajuda": "Informe, quando aplicável, o setor específico dentro da secretaria/entidade que fará o acompanhamento cotidiano do objeto."},
                {"key": "responsavel_nome", "label": "Nome do responsável", "tipo": "text",
                 "ajuda": "Informe o nome completo do agente público responsável pela sustentabilidade do objeto."},
                {"key": "responsavel_cargo", "label": "Cargo ou função", "tipo": "text",
                 "ajuda": "Informe o cargo, função ou vínculo institucional do responsável."},
                {"key": "responsavel_telefone", "label": "Telefone do responsável", "tipo": "text",
                 "ajuda": "Informe o telefone institucional ou funcional do responsável."},
                {"key": "responsavel_email", "label": "E-mail do responsável", "tipo": "text",
                 "ajuda": "Informe o endereço eletrônico institucional do responsável."},
                {"key": "responsabilidades", "label": "Responsabilidades atribuídas", "tipo": "textarea",
                 "ajuda": "Descreva resumidamente as atribuições do responsável (ex.: acompanhar a utilização; manter registros de uso; providenciar manutenções; controlar prazos de garantia; comunicar defeitos; fiscalizar a finalidade; manter o controle patrimonial; assegurar os recursos necessários)."},
            ],
        },
        {
            "titulo": "LOCAL, DATA E ASSINATURAS",
            "campos": [
                {"key": "municipio", "label": "Município", "tipo": "text",
                 "ajuda": "Informe o município em que o documento será formalizado."},
                {"key": "estado", "label": "Estado", "tipo": "text",
                 "ajuda": "Informe a unidade da Federação."},
                {"key": "data", "label": "Data", "tipo": "date",
                 "ajuda": "Informe a data de emissão ou assinatura do Plano de Sustentabilidade."},
                {"key": "assinante_convenente", "label": "Responsável pelo convenente", "tipo": "textarea",
                 "ajuda": "Informe o nome completo, cargo e órgão do representante legal do convenente responsável pela assinatura do documento."},
                {"key": "assinante_sustentabilidade", "label": "Responsável pela sustentabilidade do objeto", "tipo": "textarea",
                 "ajuda": "Informe o nome completo, cargo, órgão e unidade administrativa da pessoa responsável pela continuidade, manutenção e adequada utilização do objeto."},
            ],
        },
    ],
    "rodape_assinatura": (
        "O documento deverá ser assinado pelo representante legal do convenente e pelo responsável "
        "pela sustentabilidade do objeto, preferencialmente por meio de assinatura eletrônica válida "
        "ou conforme os procedimentos administrativos adotados pelo órgão."
    ),
}

SCHEMAS = {
    PLANO_SUSTENTABILIDADE["tipo"]: PLANO_SUSTENTABILIDADE,
}


def get_schema(tipo: str) -> dict | None:
    return SCHEMAS.get(tipo)


def listar_tipos() -> list[dict]:
    """Tipos disponíveis no módulo (p/ o menu 'Novo documento')."""
    return [{"tipo": s["tipo"], "titulo": s["titulo"], "descricao": s.get("descricao", "")}
            for s in SCHEMAS.values()]
