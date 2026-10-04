# Checkpoint — Design da política de universo FQ5.6

Data: 2026-10-02

## Estado anterior
- fonte oficial B3 setorial: GREEN;
- issuer identity bridge: GREEN no run #113;
- quant.comparaveis_setor: shadow GREEN;
- coverage/promoção ainda bloqueadas.

## Decisão de design
Para ações brasileiras, o universo operacional deve ser derivado por regra da carteira vigente do IBrA B3 e persistido via infraestrutura já existente de market.index_weights. Não usar classificação setorial, Economatica ou lista manual como proxy de universo.

## Próximo dado necessário
Materializar o arquivo oficial B3 da carteira definitiva vigente contendo IBrA para congelar o layout real antes de parser/ingestão.

## Sem código
Nenhuma implementação de universo foi feita nesta etapa.
