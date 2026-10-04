# Metas com probabilidade de sucesso — modelo conceitual

**Status:** IMPLEMENTADO na F17 (2026-08-29) — migrations 48, 49 e 50, motor em
`app/engine/{simulacao,elegibilidade,projecao}.py`, tool `planejamento.simulacao_objetivo`,
CLI `plexo objetivo projetar|status`. O que continua pendente é a APROVAÇÃO de compliance:
`PLEXO_BASE v1` e `SIMULACAO_METAS v3` nascem `draft`, e o gate C48c impede que rascunho vire
número na tela do cliente. Ver §7 e §9 para o que a implementação decidiu e o que deixou aberto.

**Nota de implementação (2026-08-23), corrigida em 2026-08-29:** a policy `SIMULACAO_METAS` (confiança padrão, limiar de
materialidade, nº de caminhos, semente) já existe em draft (`seeds/dev.sql`); a tool
`planejamento.projecao_objetivo` (F2) é determinística de propósito e declara em `nota_metodo` que
percentis/probabilidade são do motor Monte Carlo descrito aqui (F5+). Nada deste documento foi
exibido a cliente; o gate de policy aprovada (migration 29) segura isso até o parecer de compliance.
A nota estava CERTA quanto à existência da policy — a F17 quase a contradisse por ter procurado
`SIMULACAO_METAS` só em `sql/`, e não em `seeds/dev.sql`, onde ela de fato estava. O placeholder
virou `v3` na migration 49, mantendo as chaves que ele nomeou.
**Escopo:** `engine`, `planning`, `diagnostics`
**Pendente de:** aprovação de compliance para exibição de percentis ao cliente

---

## 1. O problema que isso resolve

O motor, como desenhado hoje, responde metas com aritmética determinística: dado um alvo,
um horizonte e um aporte, ele calcula o PMT necessário e diz se cabe ou não cabe.

Isso é correto mas insuficiente. Ele responde *"não dá"* sem responder a pergunta que o
cliente realmente tem: **"e se eu aceitar risco, dá?"**

Sem essa resposta, o cliente vai buscar a resposta em outro lugar — normalmente com quem
ganha comissão para dizer que sim.

---

## 2. O erro de formulação a evitar

A tentação natural é montar o comparativo assim:

> Renda fixa: 95% de chance
> Renda variável: 20% de chance

**Isso está errado e é enganoso.** Os dois números medem alvos diferentes: os 95% são de
atingir o valor que a renda fixa entrega; os 20% são de atingir o alvo original. O cliente
lê como "renda fixa é mais garantida", quando na verdade está comparando duas metas
distintas.

Qualquer eixo comparativo precisa manter **uma das duas variáveis fixa**.

---

## 3. As duas formulações válidas

### Formulação A — fixa o alvo, varia a probabilidade

> Para chegar em R$ 200.000: renda fixa 0% · balanceado 2% · renda variável 12%

Responde diretamente a pergunta do cliente. Mas exibe probabilidade de atingir um valor
monetário específico, o que é o formato mais sensível do ponto de vista regulatório.

### Formulação B — fixa a confiança, varia o valor

> Com 90% de confiança você chega em: renda fixa R$ 38.000 · balanceado R$ 29.000 ·
> renda variável R$ 21.000

**Esta é a formulação recomendada.** Três razões:

1. Revela o custo do risco, que a formulação A esconde. Ao aumentar risco, o valor com
   alta confiança **cai** — porque risco não é só chance de subir.
2. É menos exposta regulatoriamente: descreve dispersão de cenário, não promete resultado.
3. Alinha com o posicionamento de rigor — mostra o cenário ruim primeiro.

Na prática as duas convivem: a formulação B governa a tela principal, a A aparece como
detalhe quando o cliente pede.

---

## 4. A regra central: quando risco é elegível

Esta é a peça que substitui a heurística ingênua "meta curta = renda fixa".

> **Risco só é elegível quando aumenta materialmente a probabilidade de sucesso da meta.**

É uma regra objetiva, auditável e independente de perfil declarado. Ela não depende de
opinião do assessor nem de quanto o cliente diz tolerar volatilidade — depende da
matemática da meta.

Consequência prática: o mesmo cliente, com o mesmo perfil de risco, recebe recomendação
de renda variável para uma meta e recusa para outra. O que governa é o horizonte da meta,
não o perfil da pessoa.

**Perfil de risco governa o bucket de longo prazo. Horizonte governa o bucket de meta.**

---

## 5. Demonstração

Caso base: cliente guarda R$ 1.000/mês, capital inicial R$ 0, alvo R$ 200.000.
Todos os valores em termos reais. Premissas ilustrativas — as reais vivem em tabela
versionada (ver seção 7).

### Horizonte de 36 meses — risco NÃO é elegível

Total depositado ao longo do período: R$ 36.000.

| Alocação | Pessimista (p5) | Mediana | Otimista (p95) | Chance de R$ 200k |
|---|---|---|---|---|
| 100% renda fixa | R$ 37.900 | R$ 38.400 | R$ 38.900 | 0% |
| 50 / 50 | R$ 28.500 | R$ 39.100 | R$ 52.000 | ~0% |
| 100% renda variável | R$ 21.400 | R$ 39.800 | R$ 65.900 | ~0,001% |

Leitura:

- O retorno necessário para R$ 1.000/mês virar R$ 200k em 36 meses é de **~160% ao ano
  por três anos consecutivos**. Não é renda variável, é loteria.
- Aumentar risco eleva a chance de sucesso de 0% para 0,001% — **ganho imaterial**.
- No cenário pessimista com renda variável o cliente termina com **R$ 21.400 tendo
  depositado R$ 36.000**. Ele perde 40% do que guardou sem ganhar chance nenhuma.

**Veredito do motor: risco vetado. A meta é reformulada, não financiada com volatilidade.**

### Horizonte de 120 meses — risco É elegível

| Alocação | Pessimista (p5) | Mediana | Chance de R$ 200k |
|---|---|---|---|
| 100% renda fixa | R$ 148.000 | R$ 150.500 | ~0% |
| 60 / 40 | R$ 78.000 | R$ 164.100 | ~30% |
| 100% renda variável | R$ 50.000 | R$ 171.100 | ~40% |

Leitura:

- Renda fixa dá quase certeza de R$ 150k e **certeza de nunca chegar** a R$ 200k.
- Renda variável eleva a chance de 0% para 40% — **ganho material**, risco elegível.
- O preço está explícito: o cenário pessimista cai de R$ 148k para R$ 50k.

**Veredito do motor: risco oferecido, com p5 exibido no mesmo destaque que a mediana.**

É a mesma máquina nos dois casos. Só muda o horizonte — e a regra decide sozinha.

---

## 6. O que o motor precisa produzir

Para cada meta, a `run` deve gerar:

1. **PMT necessário** — determinístico, já existe
2. **Verificação de capacidade** contra `budget.v_income_breakdown` — já existe
3. **Distribuição por alocação candidata** — Monte Carlo, ~10.000 caminhos
   - percentis p5, p25, p50, p75, p95 do valor terminal
   - probabilidade de atingir o alvo
   - probabilidade de terminar abaixo do total depositado (métrica de arrependimento)
4. **Decisão de elegibilidade de risco** aplicando a regra da seção 4
5. **Alavancas alternativas** quando a meta é inviável: reduzir alvo, esticar prazo,
   aumentar aporte — com o número de cada uma

Reprodutibilidade: a **semente aleatória** da simulação entra em `engine.run_inputs`
junto com as premissas. Sem isso a `run` não é reproduzível e a garantia de reproduzir
byte a byte o número que o cliente viu se perde.

---

## 7. Impacto no schema

### Já existe e serve

- `planning.scenario_simulations` — cada cenário de alocação com seus percentis
- `planning.goal_projections` — trajetória da meta ao longo do tempo
- `engine.runs` + `engine.run_inputs` — congelamento de inputs e reprodutibilidade
- `diagnostics.findings` — o achado "meta inviável" ou "risco não elegível"

### Falta e precisa ser criado

**Tabela de premissas de mercado versionadas.** Retorno esperado, volatilidade e matriz
de correlação por classe de ativo, com data de vigência e responsável pela definição.

Hoje isso está implícito em `engine.policy_versions`. Precisa ser explícito porque é
**o insumo mais contestável de todo o sistema** e o primeiro que um regulador vai pedir.
Sem versionamento próprio não há como responder "quais premissas estavam vigentes quando
esse cliente recebeu essa projeção".

### Verificado na F17 (2026-08-29)

- **`planning.scenario_simulations` comporta percentis?** Só como `jsonb` solto. A tabela
  tipada é `planning.goal_projections`, e foi ela que a migration 48 estendeu: `p5_brl`,
  `p25_brl`, `p75_brl`, `p95_brl` (junto dos p10/p50/p90 que já existiam),
  `prob_abaixo_do_depositado`, `alocacao_code` e `assumption_set_id`. Mais o CHECK
  `percentis_ordenados`, porque percentil fora de ordem não é dado ruim — é dado impossível.
- **`engine.run_inputs` aceita semente como input tipado?** Não: seus campos são `ref_id`,
  `ref_date` e `ref_hash`. A semente é inteiro e foi para `engine.runs.params`, que **já entra
  no `input_hash`** e portanto na identidade do run — lugar melhor que o suposto aqui. O gate
  `C48e` recusa projeção cujo run não registrou semente.
- **A métrica de arrependimento** (`prob_abaixo_do_depositado`) não estava prevista e foi
  acrescentada: é o risco que o cliente sente e que percentil nenhum comunica.

### Criado na F17

`market.assumption_sets` + `market.class_assumptions` + `market.class_correlations`
(migration 48), com `metodologia` NOT NULL, ciclo de aprovação igual ao de
`engine.policy_versions`, e duas constraints que não estavam previstas aqui:

- **unidade é constraint** — `retorno_real_aa` vive em [−0,30; 0,30] e a volatilidade em
  [0; 1], em FRAÇÃO. A F16 tinha perdido meia sessão com uma taxa em percentual lida como
  fração; agora a unidade errada é erro de INSERT, não bug silencioso;
- **matriz fechada na aprovação (C48b)** — par de correlação ausente seria lido como zero, e
  zero subestima a volatilidade da carteira inteira, que é o número que decide o cenário ruim.

---

## 8. Guardrails

### Compliance

- Exibir probabilidade de atingir valor monetário é território adjacente a projeção de
  rentabilidade. **Requer parecer antes de virar código.**
- Toda exibição é condicional e relativa: *"simulação sob as premissas X, Y, Z"*, com as
  premissas visíveis na própria tela, nunca em nota de rodapé.
- **p5 e mediana sempre juntos.** Mediana isolada é proibida em qualquer superfície.
- Nenhuma formulação pode sugerir garantia, expectativa ou histórico como previsão.

### Produto

O risco real de UX: o cliente lê "40% de chance" como promessa. A mediana vira
expectativa e o p5 vira surpresa desagradável dois anos depois.

**A defesa é hierarquia visual: o cenário pessimista precisa ter destaque igual ou maior
que a mediana.** Se a tela mostrar o número bom grande e o ruim pequeno, construímos
exatamente o que criticamos no modelo comissionado.

---

## 9. Decisões — o que a F17 fechou, e o que continua aberto

**Fechadas na implementação:**

2'. **Limiar de materialidade** — `limiar_materialidade_prob = 0,10` (10 pontos de
   probabilidade), o valor que o placeholder de 2026-08-23 já declarava. Vive em
   `SIMULACAO_METAS`, como o documento exigia.
3'. **Nível de confiança padrão** — 0,90, travado em `nivel_confianca_padrao`. É ele que
   define o `aporte_para_90_por_cento` e o ponto em que a curva de
   `destino.probabilidade_meta` satura em 1,0.
5'. **Uma condição a mais, que este documento não previa** — `piora_maxima_do_p5 = 0,10`.
   Sem ela a regra do §4 não funciona como escrita: mais risco quase sempre baixa o p5 para
   um mesmo aporte, então "risco só se aumentar materialmente a probabilidade" precisava de
   uma tolerância no outro lado, ou vetava tudo — inclusive as metas longas que o §5 usa
   como demonstração. Ver o cabeçalho da migration 49, com os números medidos.
6'. **Quando NENHUMA carteira alcança o alvo**, o veredito para de falar de risco e aponta o
   aporte: "o que move este plano é o aporte ou o prazo, não o risco". Foi o primeiro smoke
   real que expôs a necessidade — discutir carteira quando as três chegam a 0% responde a
   pergunta errada.

**Continuam abertas:**

1. **Meta inviável** — o motor propõe alvo reduzido automaticamente, ou devolve as
   alavancas e deixa o cliente escolher? Propor alvo de consumo reduzido é mais útil e
   mais arriscado; está fora do escopo de uma plataforma de investimento sugerir qual
   carro comprar.
2. **Limiar de materialidade** — qual delta de probabilidade torna risco elegível?
   Precisa ser um número em `policy_versions`, não julgamento caso a caso.
3. **Nível de confiança padrão** — 90% na formulação B é escolha, não consenso. Definir
   e travar.
4. **Origem das premissas** — comitê interno, fonte externa, ou modelo? Define quem
   assina e com que frequência revisa. A `metodologia` da `PLEXO_BASE v1` propõe uma
   resposta (Focus + série de 20 anos deflacionada, recalibração anual ou a 200 bps de
   movimento na Selic longa) e declara a limitação do método; ela é ponto de partida para
   essa decisão, não a decisão.
5. **A normal subestima a cauda.** Declarado na `metodologia`, na `limitacao` da tool e no
   rodapé do CLI. Trocar por t-Student ou por bootstrap histórico é melhoria real e não
   entrou nesta fase — premissa explícita e revisável vale mais que precisão silenciosa.

---

## 10. O que a F17 deixou fora, de propósito

- **O Builder de carteira.** As três alocações candidatas vêm de política, com pesos fixos.
  Elas respondem "risco compra probabilidade neste prazo?", que é a pergunta deste
  documento — e não "qual é a carteira ótima", que é outra fase e outra aprovação.
- **Carteiras Modelo**, pelo mesmo motivo.
- **Rebalanceamento na simulação.** Simula-se uma série agregada, o que é equivalente ao
  valor terminal de simular por classe e correlacionar. A equivalência se perde se um dia
  houver rebalanceamento periódico — está comentado em `app/engine/simulacao.py` para que
  ninguém descubra por acidente.
