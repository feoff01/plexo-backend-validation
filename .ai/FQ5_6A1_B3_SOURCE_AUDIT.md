# FQ5.6A1 — Auditoria da fonte B3 para classificação setorial

Data: 2026-09-30
Estado: **fonte oficial identificada; contrato bulk público/gratuito não validado; coletor de rede bloqueado**

## Objetivo
Validar antes de código de rede qual fonte oficial da B3 pode sustentar `market.sector_classification`.

## Evidência oficial confirmada
A B3 mantém a consulta pública de classificação setorial, com atualização semanal no último dia útil da semana durante o processamento noturno. As páginas públicas de Empresas Listadas expõem CNPJ, códigos de negociação, atividade principal e classificação setor/subsetor/segmento.

A B3 oferece no UP2DATA o canal **Empresas Listadas**, incluindo `SummaryData`, descrito como cadastro-resumo das companhias.

## Contrato técnico
UP2DATA é o contrato estruturado oficial preferido para produção, mas o acesso recorrente é contratado/autenticado. O backend não deve assumir credenciais inexistentes ou embutir segredos.

O front-end público usa endpoints `listedCompaniesProxy`, mas nesta auditoria não foi encontrada documentação oficial da B3 declarando-os API pública estável com versão/SLA/contrato de campos. Eles não serão usados como fonte de produção.

## Decisão
1. fonte estruturada preferida: B3 UP2DATA / Empresas Listadas / SummaryData;
2. nenhum coletor HTTP até existir acesso autorizado + fixture oficial sanitizada, ou arquivo oficial equivalente obtido por processo autorizado;
3. não usar scraping, API de terceiros ou prefixo de ticker;
4. matching continua CNPJ -> issuer.

## Trabalho independente da rede
O loader PIT do schema existente pode avançar porque `ingestion_batch_id` e `ingestion_batches.finished_at` já permitem reconstruir quando o Plexo conheceu o snapshot.

## Limitação
Strict PIT mede availability no Plexo, não a data econômica/jurídica exata de vigência de uma reclassificação.

## Próximo gate da fonte
Obter bytes reais de SummaryData/export oficial, preservar fixture sanitizada, documentar layout/campos/versionamento, validar CNPJ + classificação + listing segment e definir hash/storage antes do parser/ingestão.
