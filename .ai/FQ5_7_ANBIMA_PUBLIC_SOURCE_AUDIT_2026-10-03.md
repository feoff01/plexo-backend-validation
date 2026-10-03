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
