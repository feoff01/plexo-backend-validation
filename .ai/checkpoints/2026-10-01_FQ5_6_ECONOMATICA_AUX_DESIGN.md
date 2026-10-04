# Checkpoint — design integração auxiliar Economatica

Data: 2026-10-01

- Economatica será fonte própria, nunca B3.
- Somente setor/subsetor corrente.
- Ticker exato -> instrumento -> issuer.
- Sem retrodatação pelos anos dos workbooks.
- Parser XLSX stdlib, sem dependência nova.
- Preços/fundamentos Economatica ficam fora.
- Sem fallback automático de source.
- Implementação autorizada apenas em shadow.

Documento: `.ai/FQ5_6_ECONOMATICA_AUX_SOURCE_DESIGN.md`.
