# FQ5.7 — Auditoria da fonte pública ANBIMA após foundation GREEN

Data: 2026-10-03
Estado: **fonte pública atual confirmada; adapter físico continua bloqueado**

## Fonte oficial confirmada

ANBIMA mantém duas superfícies oficiais relevantes:

1. ANBIMA Developers:
   - endpoint documentado: `GET /feed/precos-indices/v1/titulos-publicos/curvas-juros`;
   - divulgação diária a partir das 20h;
   - parâmetro opcional `data=AAAA-MM-DD`;
   - campos ETTJ: `vertice_du`, `taxa_prefixadas`, `taxa_ipca`, `taxa_implicita`;
   - unidade: % a.a./252 d.u.;
   - acesso autenticado.

2. Página pública de fechamento:
   - `https://www.anbima.com.br/informacoes/est-termo/CZ.asp`;
   - consulta oficial dos últimos cinco dias úteis;
   - UI oferece XLS/CSV/TXT/XML;
   - snapshot observado em 2026-10-03: referência 02/10/2026.

## Cobertura atual observada na página oficial

Para 02/10/2026:
- ETTJ IPCA: 65 vértices, de 252 a 8.316 d.u. em passos de 126;
- ETTJ PRE: 19 vértices, de 252 a 2.520 d.u.;
- inflação implícita: 19 vértices, de 252 a 2.520 d.u.;
- parâmetros Svensson também são publicados, mas continuam fora da tranche.

Essa cobertura é compatível com o loader já GREEN, que não exige que as três curvas tenham os mesmos vértices e não interpola.

## Anexos da conversa

Foi revisada a lista de arquivos enviados pelo usuário. Há:
- Economatica;
- classificação setorial B3;
- composição/índices B3;
- snapshots do backend.

Não há arquivo ANBIMA/ETTJ anexado até este ponto.

## Decisão de adapter físico

A UI pública oferece downloads, mas nesta sessão não foi possível materializar os bytes do CSV/XML nem provar por documentação oficial uma URL GET estável para download.

Portanto:
- NÃO criar scraper HTML de produção;
- NÃO adotar endpoint/form action descoberto por fontes de terceiros como contrato;
- NÃO hardcodar a tabela visual atual;
- manter o adapter API/CSV físico bloqueado até receber bytes reais oficiais ou acesso autorizado;
- a fundação semântica/loader permanece GREEN e independente do formato físico.

## Próxima ação segura

Aceitar um dos seguintes insumos:
1. CSV/XML/XLS oficial baixado pela própria página ANBIMA;
2. payload JSON real da API Developers, sem credenciais;
3. execução do adapter em ambiente autorizado que materialize um fixture sanitizado.

Depois disso:
- congelar parser físico contra bytes reais;
- medir cobertura histórica efetiva;
- decidir primeira capability pública sob reuse-before-build.


## Verificação adicional no fechamento do handoff — 2026-10-03

A página oficial continuava exibindo a curva de referência 02/10/2026 e opções XLS/CSV/TXT/XML. A documentação ANBIMA Developers continuava confirmando o endpoint autenticado e os campos ETTJ.

Uma requisição direta ao domínio oficial para `CZ-down.asp` foi identificada como resposta `text/csv`, mas este ambiente não conseguiu materializar os bytes e não provou, por documentação oficial, o contrato completo de parâmetros/form do download público.

A decisão permanece: não implementar adapter físico por suposição, scraper HTML ou contrato de terceiros. O próximo chat deve avançar somente com bytes oficiais CSV/XML/XLS ou payload JSON real autorizado.


## Source gate encerrado — 2026-10-03
O bloqueio `BLOCKED_AT_OFFICIAL_BYTES` foi removido. O endpoint first-party `CZ-down.asp` foi materializado via runner do repositório autorizado e retornou `CurvaZero_.csv`, `text/csv`, 2.899 bytes, SHA-256 `a254ebf789b41cb83838d9b0df29c4d094f1a4c37ddf0f1400d94637267af1f7`. A referência física é 02/10/2026.

Coverage física observada: 65 vértices IPCA, 19 PRE e 19 inflação implícita. A superfície pública declara últimos cinco dias úteis; a API Developers aceita consulta por data, sujeita ao acesso autorizado. Fixture/parser foram congelados. Estado do source gate: GREEN.

## Cobertura física revalidada — 2026-10-03

O contrato first-party do download público foi confirmado pelo próprio HTML/JavaScript oficial: para download, o formulário envia POST diretamente a `CZ-down.asp`; no estado auditado o limite exposto era `Dt_Ref_Ver=20260925`.

Materialização física validada por data:
- 02/10/2026 — SHA-256 `a254ebf789b41cb83838d9b0df29c4d094f1a4c37ddf0f1400d94637267af1f7`;
- 01/10/2026 — `a8fabca0c437e6520b84939b7c074121ba973cd77b61955cd04a9ae3ae6f9a87`;
- 30/09/2026 — `550d7fc277333ce8d4e88d4a43ab856ce84778f1eed163935e52a9d2adf4d9f4`;
- 29/09/2026 — `bfd3686b19793209cd5248c275f33ea938e9fe1348587f4e9734816517895ca1`;
- 28/09/2026 — `54b15c0b6a12455e97b1e97b5bfda4c66c2573f6f8a1d92a53f0d2a196620ab5`;
- 25/09/2026 — `9794c267c2934af72bfc5d29046c454d9caa52cca77247b5e8b5cf3d2be9c220`.

Todas as seis respostas são CSVs distintos, com a data econômica correta e 65/19/19 vértices IPCA/PRE/inflação implícita aceitos pelo parser canônico.

Uma resposta para 24/09/2026 também foi observada no servidor, mas fica deliberadamente fora do contrato do produto: não tratar retenção técnica além do limite exposto pela UI como histórico suportado ou garantido.

Estado final desta auditoria: **source gate GREEN / janela pública física comprovada / sem scraper de produção**.

