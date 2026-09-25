"""CÓDIGO ESTADUAL de município do RS (o "Cód. Município" das planilhas da
SES-RS, que é o `Cod_Municipio` da CAGE/SEFAZ) -> IBGE.

GERADO por `scripts/gerar_depara_municipios_rs.py` — não editar à mão; o método
e as armadilhas estão lá. Cadeia sem nome: fundo municipal na planilha do FES
(Cód. Credor) -> CNPJ na despesa do Estado (dados.rs.gov.br) -> IBGE no arquivo
REPASSE-FAF do Portal FNS -> 7 dígitos pelo SICONFI.

Gerado em 24/09/2026: 497 de 497 municípios.
"""

CODIGO_ESTADUAL_PARA_IBGE: dict[int, int] = {
    1: 4300109,  # Agudo
    2: 4300406,  # Alegrete
    3: 4300802,  # Antônio Prado
    4: 4300901,  # Aratiba
    5: 4301008,  # Arroio do Meio
    6: 4301305,  # Arroio Grande
    7: 4301404,  # Arvorezinha
    8: 4301602,  # Bagé
    9: 4301909,  # Barra do Ribeiro
    10: 4302105,  # Bento Gonçalves
    11: 4302303,  # Bom Jesus
    12: 4302402,  # Bom Retiro do Sul
    13: 4302808,  # Caçapava do Sul
    14: 4302907,  # Cacequi
    15: 4303004,  # Cachoeira do Sul
    16: 4307401,  # Esmeralda
    17: 4303509,  # Camaquã
    18: 4303806,  # Campinas do Sul
    19: 4303905,  # Campo Bom
    20: 4304002,  # Campo Novo
    21: 4304200,  # Candelária
    22: 4304408,  # Canela
    23: 4304507,  # Canguçu
    24: 4304606,  # Canoas
    25: 4304705,  # Carazinho
    26: 4304804,  # Carlos Barbosa
    27: 4304903,  # Casca
    28: 4305009,  # Catuípe
    29: 4305108,  # Caxias do Sul
    30: 4305207,  # Cerro Largo
    31: 4305306,  # Chapada
    32: 4305801,  # Constantina
    33: 4306007,  # Crissiumal
    34: 4306106,  # Cruz Alta
    35: 4306403,  # Dois Irmãos
    36: 4306601,  # Dom Pedrito
    37: 4306809,  # Encantado
    38: 4306908,  # Encruzilhada do Sul
    39: 4307005,  # Erechim
    40: 4307203,  # Erval Grande
    41: 4307500,  # Espumoso
    42: 4307609,  # Estância Velha
    43: 4307708,  # Esteio
    44: 4307807,  # Estrela
    45: 4307906,  # Farroupilha
    46: 4308003,  # Faxinal do Soturno
    47: 4308102,  # Feliz
    48: 4308201,  # Flores da Cunha
    49: 4308508,  # Frederico Westphalen
    50: 4308607,  # Garibaldi
    51: 4308706,  # Gaurama
    52: 4308805,  # General Câmara
    53: 4319802,  # São Vicente do Sul
    54: 4308904,  # Getúlio Vargas
    55: 4309001,  # Giruá
    56: 4309100,  # Gramado
    57: 4309209,  # Gravataí
    58: 4309308,  # Guaíba
    59: 4309407,  # Guaporé
    60: 4309506,  # Guarani das Missões
    61: 4307104,  # Herval
    62: 4309605,  # Horizontina
    63: 4309704,  # Humaitá
    64: 4310009,  # Ibirubá
    65: 4310207,  # Ijuí
    66: 4310504,  # Iraí
    67: 4310603,  # Itaqui
    68: 4311007,  # Jaguarão
    69: 4311106,  # Jaguari
    70: 4311205,  # Júlio de Castilhos
    71: 4311304,  # Lagoa Vermelha
    72: 4311403,  # Lajeado
    73: 4311502,  # Lavras do Sul
    74: 4311700,  # Machadinho
    75: 4311809,  # Marau
    76: 4311908,  # Marcelino Ramos
    77: 4312203,  # Maximiliano de Almeida
    78: 4312401,  # Montenegro
    79: 4312500,  # Mostardas
    80: 4312609,  # Muçum
    81: 4312658,  # Não-Me-Toque
    82: 4312708,  # Nonoai
    83: 4313102,  # Nova Palma
    84: 4313201,  # Nova Petrópolis
    85: 4313300,  # Nova Prata
    86: 4313409,  # Novo Hamburgo
    87: 4313508,  # Osório
    88: 4313607,  # Paim Filho
    89: 4313706,  # Palmeira das Missões
    90: 4313904,  # Panambi
    91: 4314100,  # Passo Fundo
    92: 4314209,  # Pedro Osório
    93: 4314407,  # Pelotas
    94: 4314506,  # Pinheiro Machado
    95: 4314605,  # Piratini
    96: 4314902,  # Porto Alegre
    97: 4315008,  # Porto Lucena
    98: 4315305,  # Quaraí
    99: 4315503,  # Restinga Sêca
    100: 4315602,  # Rio Grande
    101: 4315701,  # Rio Pardo
    102: 4315800,  # Roca Sales
    103: 4316006,  # Rolante
    104: 4316402,  # Rosário do Sul
    105: 4316600,  # Sananduva
    106: 4317103,  # Sant'Ana do Livramento
    107: 4316709,  # Santa Bárbara do Sul
    108: 4316808,  # Santa Cruz do Sul
    109: 4316907,  # Santa Maria
    110: 4317202,  # Santa Rosa
    111: 4317301,  # Santa Vitória do Palmar
    112: 4317400,  # Santiago
    113: 4317509,  # Santo Ângelo
    114: 4317608,  # Santo Antônio da Patrulha
    115: 4317806,  # Santo Augusto
    116: 4317905,  # Santo Cristo
    117: 4318002,  # São Borja
    118: 4318101,  # São Francisco de Assis
    119: 4318200,  # São Francisco de Paula
    120: 4318309,  # São Gabriel
    121: 4318408,  # São Jerônimo
    122: 4318507,  # São José do Norte
    123: 4318606,  # São José do Ouro
    124: 4318705,  # São Leopoldo
    125: 4318804,  # São Lourenço do Sul
    126: 4318903,  # São Luiz Gonzaga
    127: 4319406,  # São Pedro do Sul
    128: 4319505,  # São Sebastião do Caí
    129: 4319604,  # São Sepé
    130: 4319703,  # São Valentim
    131: 4319901,  # Sapiranga
    132: 4320008,  # Sapucaia do Sul
    133: 4320107,  # Sarandi
    134: 4320206,  # Seberi
    135: 4320404,  # Serafina Corrêa
    136: 4320701,  # Sobradinho
    137: 4320800,  # Soledade
    138: 4320909,  # Tapejara
    139: 4321006,  # Tapera
    140: 4321105,  # Tapes
    141: 4321204,  # Taquara
    142: 4321303,  # Taquari
    143: 4321402,  # Tenente Portela
    144: 4321501,  # Torres
    145: 4321600,  # Tramandaí
    146: 4321709,  # Três Coroas
    147: 4321808,  # Três de Maio
    148: 4321907,  # Três Passos
    149: 4322004,  # Triunfo
    150: 4322103,  # Tucunduva
    151: 4322202,  # Tupanciretã
    152: 4322301,  # Tuparendi
    153: 4322400,  # Uruguaiana
    154: 4322509,  # Vacaria
    155: 4322608,  # Venâncio Aires
    156: 4322707,  # Vera Cruz
    157: 4322806,  # Veranópolis
    158: 4322905,  # Viadutos
    159: 4323002,  # Viamão
    160: 4305603,  # Colorado
    161: 4310108,  # Igrejinha
    162: 4300208,  # Ajuricaba
    163: 4300307,  # Alecrim
    164: 4300505,  # Alpestre
    165: 4300604,  # Alvorada
    166: 4300703,  # Anta Gorda
    167: 4301107,  # Arroio dos Ratos
    168: 4301206,  # Arroio do Tigre
    169: 4301503,  # Augusto Pestana
    170: 4301701,  # Barão de Cotegipe
    171: 4301800,  # Barracão
    172: 4302006,  # Barros Cassal
    173: 4302204,  # Boa Vista do Buricá
    174: 4302501,  # Bossoroca
    175: 4302600,  # Braga
    176: 4302709,  # Butiá
    177: 4303103,  # Cachoeirinha
    178: 4303202,  # Cacique Doble
    179: 4303301,  # Caibaté
    180: 4303400,  # Caiçara
    181: 4303608,  # Cambará do Sul
    182: 4303707,  # Campina das Missões
    183: 4304309,  # Cândido Godói
    184: 4305405,  # Chiapetta
    185: 4305504,  # Ciríaco
    186: 4305702,  # Condor
    187: 4305900,  # Coronel Bicaco
    188: 4306205,  # Cruzeiro do Sul
    189: 4306304,  # David Canabarro
    190: 4306502,  # Dom Feliciano
    191: 4306700,  # Dona Francisca
    192: 4307302,  # Erval Seco
    193: 4308300,  # Fontoura Xavier
    194: 4308409,  # Formigueiro
    195: 4309803,  # Ibiaçá
    196: 4309902,  # Ibiraiaras
    197: 4310306,  # Ilópolis
    198: 4310405,  # Independência
    199: 4310702,  # Itatiba do Sul
    200: 4310801,  # Ivoti
    201: 4310900,  # Jacutinga
    202: 4311601,  # Liberato Salzano
    203: 4312005,  # Mariano Moro
    204: 4312104,  # Mata
    205: 4312302,  # Miraguaí
    206: 4312807,  # Nova Araçá
    207: 4312906,  # Nova Bassano
    208: 4313003,  # Nova Bréscia
    209: 4313805,  # Palmitinho
    210: 4314001,  # Paraí
    211: 4314308,  # Pejuçara
    212: 4314704,  # Planalto
    213: 4314803,  # Portão
    214: 4315107,  # Porto Xavier
    215: 4315206,  # Putinga
    216: 4315404,  # Redentora
    217: 4315909,  # Rodeio Bonito
    218: 4316105,  # Ronda Alta
    219: 4316204,  # Rondinha
    220: 4316303,  # Roque Gonzales
    221: 4316501,  # Salvador do Sul
    222: 4317004,  # Santana da Boa Vista
    223: 4317707,  # Santo Antônio das Missões
    224: 4319000,  # São Marcos
    225: 4319109,  # São Martinho
    226: 4319208,  # São Nicolau
    227: 4319307,  # São Paulo das Missões
    228: 4320305,  # Selbach
    229: 4320503,  # Sertão
    230: 4320602,  # Severiano de Almeida
    231: 4323101,  # Vicente Dutra
    232: 4323200,  # Victor Graeff
    233: 4302352,  # Bom Princípio
    234: 4304630,  # Capão da Canoa
    235: 4304663,  # Capão do Leão
    236: 4305355,  # Charqueadas
    237: 4305959,  # Cotiporã
    238: 4308458,  # Fortaleza dos Valos
    239: 4311155,  # Jóia
    240: 4313656,  # Palmares do Sul
    241: 4314050,  # Parobé
    242: 4316451,  # Salto do Jacuí
    243: 4321352,  # Tavares
    244: 4321451,  # Teutônia
    245: 4300059,  # Água Santa
    246: 4300455,  # Alegria
    247: 4300554,  # Alto Alegre
    248: 4300638,  # Amaral Ferrador
    249: 4300661,  # André da Rocha
    250: 4301057,  # Arroio do Sal
    251: 4301552,  # Áurea
    252: 4301651,  # Barão
    253: 4302451,  # Boqueirão do Leão
    254: 4302659,  # Brochier
    255: 4303558,  # Camargo
    256: 4304101,  # Campos Borges
    257: 4304689,  # Capela de Santana
    258: 4304952,  # Caseiros
    259: 4305132,  # Cerro Branco
    260: 4305157,  # Cerro Grande
    261: 4305173,  # Cerro Grande do Sul
    262: 4305454,  # Cidreira
    263: 4306056,  # Cristal
    264: 4306353,  # Dezesseis de Novembro
    265: 4306452,  # Dois Lajeados
    266: 4306734,  # Doutor Maurício Cardoso
    267: 4306767,  # Eldorado do Sul
    268: 4306957,  # Entre Rios do Sul
    269: 4306932,  # Entre-Ijuís
    270: 4306973,  # Erebango
    271: 4307054,  # Ernestina
    272: 4307559,  # Estação
    273: 4307831,  # Eugênio de Castro
    274: 4307864,  # Fagundes Varela
    275: 4308052,  # Faxinalzinho
    276: 4309050,  # Glorinha
    277: 4309258,  # Guabiju
    278: 4309555,  # Harmonia
    279: 4309753,  # Ibarama
    280: 4309951,  # Ibirapuitã
    281: 4310330,  # Imbé
    282: 4310363,  # Imigrante
    283: 4310439,  # Ipê
    284: 4310462,  # Ipiranga do Sul
    285: 4310553,  # Itacurubi
    286: 4310751,  # Ivorá
    287: 4310850,  # Jaboticaba
    288: 4311122,  # Jaquirana
    289: 4311254,  # Lagoão
    290: 4312351,  # Montauri
    291: 4312450,  # Morro Redondo
    292: 4312757,  # Nova Alvorada
    293: 4313037,  # Nova Esperança do Sul
    294: 4313060,  # Nova Hartz
    295: 4313359,  # Nova Roma do Sul
    296: 4313953,  # Pantano Grande
    297: 4314027,  # Paraíso do Sul
    298: 4314159,  # Paverama
    299: 4314456,  # Pinhal
    300: 4314555,  # Pirapó
    301: 4314753,  # Poço das Antas
    302: 4315131,  # Pouso Novo
    303: 4315156,  # Progresso
    304: 4315172,  # Protásio Alves
    305: 4315354,  # Quinze de Novembro
    306: 4315453,  # Relvado
    307: 4315750,  # Riozinho
    308: 4316436,  # Saldanha Marinho
    309: 4316956,  # Santa Maria do Herval
    310: 4318051,  # São Domingos do Sul
    311: 4318424,  # São João da Urtiga
    312: 4318440,  # São Jorge
    313: 4318465,  # São José do Herval
    314: 4318481,  # São José do Hortêncio
    315: 4319158,  # São Miguel das Missões
    316: 4320230,  # Sede Nova
    317: 4320263,  # Segredo
    318: 4320651,  # Silveira Martins
    319: 4321329,  # Taquaruçu do Sul
    320: 4321436,  # Terra de Areia
    321: 4321634,  # Três Arroios
    322: 4321667,  # Três Cachoeiras
    323: 4321857,  # Três Palmeiras
    324: 4321956,  # Trindade do Sul
    325: 4322152,  # Tunas
    326: 4322251,  # Tupandi
    327: 4322558,  # Vanini
    328: 4323309,  # Vila Flores
    329: 4323408,  # Vila Maria
    330: 4323507,  # Vista Alegre
    331: 4323606,  # Vista Alegre do Prata
    332: 4323705,  # Vista Gaúcha
    333: 4319752,  # São Vendelino
    334: 4300570,  # Alto Feliz
    335: 4300646,  # Ametista do Sul
    336: 4300851,  # Arambaré
    337: 4301750,  # Barão do Triunfo
    338: 4301859,  # Barra do Guarita
    339: 4301925,  # Barra do Rio Azul
    340: 4301958,  # Barra Funda
    341: 4302154,  # Boa Vista das Missões
    342: 4302378,  # Bom Progresso
    343: 4303673,  # Campestre da Serra
    344: 4304358,  # Candiota
    345: 4304697,  # Capitão
    346: 4304853,  # Carlos Gomes
    347: 4305116,  # Centenário
    348: 4305371,  # Charrua
    349: 4305587,  # Colinas
    350: 4305850,  # Coqueiros do Sul
    351: 4305871,  # Coronel Barros
    352: 4305975,  # Coxilha
    353: 4306320,  # Derrubadas
    354: 4306429,  # Dois Irmãos das Missões
    355: 4306924,  # Engenho Velho
    356: 4308656,  # Garruchos
    357: 4308854,  # Gentil
    358: 4309126,  # Gramado dos Loureiros
    359: 4309159,  # Gramado Xavier
    360: 4309654,  # Hulha Negra
    361: 4310413,  # Inhacorá
    362: 4310579,  # Itapuca
    363: 4311270,  # Lagoa dos Três Cantos
    364: 4311429,  # Lajeado do Bugre
    365: 4311627,  # Lindolfo Collor
    366: 4311643,  # Linha Nova
    367: 4311759,  # Manoel Viana
    368: 4311775,  # Maquiné
    369: 4311791,  # Maratá
    370: 4311981,  # Mariana Pimentel
    371: 4312138,  # Mato Castelhano
    372: 4312153,  # Mato Leitão
    373: 4312252,  # Minas do Leão
    374: 4312385,  # Monte Belo do Sul
    375: 4312427,  # Mormaço
    376: 4312443,  # Morrinhos do Sul
    377: 4312476,  # Morro Reuter
    378: 4312625,  # Muliterno
    379: 4312674,  # Nicolau Vergueiro
    380: 4312955,  # Nova Boa Vista
    381: 4313086,  # Nova Pádua
    382: 4313375,  # Nova Santa Rita
    383: 4313490,  # Novo Barreiro
    384: 4313425,  # Novo Machado
    385: 4313441,  # Novo Tiradentes
    386: 4314035,  # Pareci Novo
    387: 4314076,  # Passo do Sobrado
    388: 4314423,  # Picada Café
    389: 4314472,  # Pinhal Grande
    390: 4314498,  # Pinheirinho do Vale
    391: 4314779,  # Pontão
    392: 4314787,  # Ponte Preta
    393: 4315057,  # Porto Mauá
    394: 4315073,  # Porto Vera Cruz
    395: 4315149,  # Presidente Lucena
    396: 4315321,  # Quevedos
    397: 4315552,  # Rio dos Índios
    398: 4316428,  # Sagrada Família
    399: 4316477,  # Salvador das Missões
    400: 4316758,  # Santa Clara do Sul
    401: 4317251,  # Santa Tereza
    402: 4317558,  # Santo Antônio do Palma
    403: 4317756,  # Santo Antônio do Planalto
    404: 4317954,  # Santo Expedito do Sul
    405: 4318432,  # São João do Polêsine
    406: 4318457,  # São José das Missões
    407: 4318499,  # São José do Inhacorá
    408: 4318622,  # São José dos Ausentes
    409: 4319125,  # São Martinho da Serra
    410: 4319356,  # São Pedro da Serra
    411: 4319372,  # São Pedro do Butiá
    412: 4319711,  # São Valentim do Sul
    413: 4319737,  # São Valério do Sul
    414: 4320354,  # Sentinela do Sul
    415: 4320453,  # Sério
    416: 4320552,  # Sertão Santana
    417: 4320677,  # Sinimbu
    418: 4321477,  # Tiradentes do Sul
    419: 4321626,  # Travesseiro
    420: 4321832,  # Três Forquilhas
    421: 4322186,  # Tupanci do Sul
    422: 4322350,  # União da Serra
    423: 4322533,  # Vale do Sol
    424: 4322541,  # Vale Real
    425: 4323457,  # Vila Nova do Sul
    426: 4323754,  # Vitória das Missões
    427: 4323804,  # Xangri-lá
    428: 4300877,  # Araricá
    429: 4301636,  # Balneário Pinhal
    430: 4301875,  # Barra do Quaraí
    431: 4302055,  # Benjamin Constant do Sul
    432: 4302253,  # Boa Vista do Sul
    433: 4304671,  # Capivari do Sul
    434: 4304713,  # Caraá
    435: 4305124,  # Cerrito
    436: 4305439,  # Chuí
    437: 4305447,  # Chuvisca
    438: 4306072,  # Cristal do Sul
    439: 4306379,  # Dilermando de Aguiar
    440: 4306551,  # Dom Pedro de Alcântara
    441: 4306759,  # Doutor Ricardo
    442: 4307450,  # Esperança do Sul
    443: 4307815,  # Estrela Velha
    444: 4308078,  # Fazenda Vilanova
    445: 4308250,  # Floriano Peixoto
    446: 4309571,  # Herveiras
    447: 4310538,  # Itaara
    448: 4311130,  # Jari
    449: 4311718,  # Maçambará
    450: 4311734,  # Mampituba
    451: 4312054,  # Marques de Souza
    452: 4312377,  # Monte Alegre dos Campos
    453: 4312617,  # Muitos Capões
    454: 4313011,  # Nova Candelária
    455: 4313334,  # Nova Ramada
    456: 4313391,  # Novo Cabrais
    457: 4314068,  # Passa Sete
    458: 4320321,  # Senador Salgado Filho
    459: 4320578,  # Sete de Setembro
    460: 4320859,  # Tabaí
    461: 4321493,  # Toropi
    462: 4322327,  # Turuçu
    463: 4322343,  # Ubiretama
    464: 4322376,  # Unistalda
    465: 4322525,  # Vale Verde
    466: 4322855,  # Vespasiano Corrêa
    467: 4323358,  # Vila Lângaro
    468: 4300034,  # Aceguá
    469: 4300471,  # Almirante Tamandaré do Sul
    470: 4301073,  # Arroio do Padre
    471: 4302220,  # Boa Vista do Cadeado
    472: 4302238,  # Boa Vista do Incra
    473: 4302584,  # Bozano
    474: 4304614,  # Canudos do Vale
    475: 4304622,  # Capão Bonito do Sul
    476: 4304655,  # Capão do Cipó
    477: 4305934,  # Coronel Pilar
    478: 4305835,  # Coqueiro Baixo
    479: 4306130,  # Cruzaltense
    480: 4308433,  # Forquetinha
    481: 4310652,  # Itati
    482: 4310876,  # Jacuizinho
    483: 4311239,  # Lagoa Bonita do Sul
    484: 4312179,  # Mato Queimado
    485: 4313466,  # Novo Xingu
    486: 4314134,  # Paulo Bento
    487: 4314175,  # Pedras Altas
    488: 4314464,  # Pinhal da Serra
    489: 4314548,  # Pinto Bandeira
    490: 4315313,  # Quatro Irmãos
    491: 4315958,  # Rolador
    492: 4318614,  # São José do Sul
    493: 4319364,  # São Pedro das Missões
    494: 4316733,  # Santa Cecília do Sul
    495: 4316972,  # Santa Margarida do Sul
    496: 4321469,  # Tio Hugo
    497: 4323770,  # Westfália
}
