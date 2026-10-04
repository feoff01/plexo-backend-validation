#!/usr/bin/env python3
"""Gera synapta_banco.drawio — diagrama COMPLETO: todas as tabelas, por schema."""
import re, pathlib
from xml.sax.saxutils import quoteattr

# Caminhos relativos ao próprio script: tools/ é irmão de sql/ e diagrama/.
ROOT = pathlib.Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql"
OUT_DIR = ROOT / "diagrama"

FILES = sorted(f for f in SQL_DIR.glob("*.sql") if f.name[0].isdigit())

tables, views = {}, {}
for f in FILES:
    sql = re.sub(r"--[^\n]*", "", f.read_text(encoding="utf-8"))
    for m in re.finditer(r"CREATE TABLE (?:IF NOT EXISTS )?([\w]+)\.([\w]+)", sql):
        tables.setdefault(m.group(1), []).append(m.group(2))
    for m in re.finditer(r"CREATE (MATERIALIZED )?VIEW ([\w]+)\.([\w]+)", sql):
        views.setdefault(m.group(2), []).append(("mv " if m.group(1) else "v ") + m.group(3))

STAR = {  # tabelas com regra inviolável testada (T1–T24)
 "policy_versions","runs","artifacts","findings","actions","finding_observations",
 "holdings_snapshots","target_portfolios","target_allocations","model_portfolios",
 "value_entries","notifications","paywall_impressions","events","activity_log",
 "conversations","messages","usage_counters","tool_executions","prompt_versions",
 "evidence_findings","reports","extraction_runs","signals","change_proposals",
 "portfolio_scores","scopes","suitability_assessments",
 "assertions","members","income_sources","income_summaries","assets","valuations",
 "fact_definitions","client_indicators","client_scores",   # F14: catálogo e perfil
 "constraints","records","rationale_items","inputs",
}

META = {  # schema: (arquivo, cor, borda, nota)
 "identity":   ("01","#dae8fc","#6c8ebf","escopo = raiz de tudo (C1)"),
 "billing":    ("03","#dae8fc","#6c8ebf","plan_prices VAZIA — preço [PENDENTE]"),
 "engine":     ("02","#ffe6cc","#d79b00","reproduzo byte a byte o nº que o cliente viu"),
 "market":     ("04","#d5e8d4","#82b366","D-1 é contrato; parent_issuer = conglomerado"),
 "wealth":     ("05","#d5e8d4","#82b366","C7: snapshot NUNCA sofre UPDATE"),
 "diagnostics":("06+15","#fff2cc","#d6b656","cooldown/supressão vivem no FINDING"),
 "planning":   ("07","#fff2cc","#d6b656","1 carteira-alvo ativa; Σ pesos = 1,000"),
 "budget":     ("08","#fff2cc","#d6b656","pode ficar na gaveta sem afetar nada"),
 "content":    ("09","#f8cecc","#b85450","2 push/semana; excedente gravado suprimido"),
 "copilot":    ("10","#f8cecc","#b85450","LÊ números; nunca calcula"),
 "ledger":     ("11","#f8cecc","#b85450","sem 'retorno_mercado' no enum"),
 "analytics":  ("12+15","#f5f5f5","#999999","o fake-door é uma tabela"),
 "audit":      ("13","#f5f5f5","#999999","quem fez o quê (≠ engine.runs)"),
 "agents":     ("17","#e1d5e7","#9673a6","4 agentes como dado; cota via policy"),
 "tools":      ("18","#e1d5e7","#9673a6","LLM escolhe; o código calcula"),
 "llm":        ("19","#e1d5e7","#9673a6","sem prompt aprovado, sem conversa"),
 "analysis":   ("20","#e1d5e7","#9673a6","profundidade exclusiva do Analista"),
 "context":    ("21+22","#e1d5e7","#9673a6","fato ≠ inferência ≠ opinião"),
 "household":  ("23","#d0e8f2","#3a7ca5","quem depende, e até quando"),
 "estate":     ("25","#d0e8f2","#3a7ca5","bruto sem passivo é mentira"),
 "preferences":("26","#d0e8f2","#3a7ca5","veto do cliente é inviolável"),
 "decisions":  ("27","#d0e8f2","#3a7ca5","não há entrega sem porquê"),
 "docs":       ("34","#d5e8d4","#82b366","texto de terceiro só citável se aprovado"),
}

cells, _id = [], [1]
def nid():
    _id[0]+=1; return f"n{_id[0]}"

def vertex(label,x,y,w,h,style):
    i=nid()
    cells.append(f'<mxCell id="{i}" value={quoteattr(label)} style={quoteattr(style)} vertex="1" parent="1">'
                 f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
    return i

def edge(src,dst,label="",dashed=False,color="#666666",exit_=None,entry=None):
    i=nid()
    st=(f"edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;fontSize=10;fontColor=#444444;"
        f"strokeColor={color};strokeWidth={1 if dashed else 2};{'dashed=1;' if dashed else ''}")
    if exit_: st+=f"exitX={exit_[0]};exitY={exit_[1]};exitDx=0;exitDy=0;"
    if entry: st+=f"entryX={entry[0]};entryY={entry[1]};entryDx=0;entryDy=0;"
    cells.append(f'<mxCell id="{i}" value={quoteattr(label)} style={quoteattr(st)} edge="1" parent="1" '
                 f'source="{src}" target="{dst}"><mxGeometry relative="1" as="geometry"/></mxCell>')

def schema_box(schema,x,y,w):
    file_,fill,stroke,note = META[schema]
    tl = tables.get(schema,[])
    vl = views.get(schema,[])
    rows=[]
    for t in tl:
        rows.append(("★ " if t in STAR else "&nbsp;&nbsp; ") + t)
    for v in vl:
        rows.append("&nbsp;&nbsp; <i>"+v+"</i>")
    body="<br/>".join(rows)
    label=(f"<b style='font-size:14px'>{schema}</b> <font style='font-size:10px'>({file_}) · {len(tl)} tab.</font>"
           f"<hr size='1'/><div style='text-align:left;font-size:10px;line-height:1.35'>{body}</div>"
           f"<hr size='1'/><i><font style='font-size:9px' color='#555555'>{note}</font></i>")
    h = 78 + 15*len(rows)
    style=(f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
           f"align=center;verticalAlign=top;spacingTop=4;spacing=8;arcSize=6;")
    return vertex(label,x,y,w,h,style), h

W, GX, GY, TOP = 330, 30, 26, 120
X=[40+i*(W+GX) for i in range(5)]
colunas={0:["identity","market","budget"],
         1:["billing","wealth","ledger"],
         2:["engine","diagnostics","copilot"],
         3:["planning","content"],
         4:["analytics","audit"]}

vertex("<b style='font-size:20px'>SYNAPTA · Banco de dados — diagrama completo</b>"
       "<br/><font style='font-size:11px'>PostgreSQL 18 · 55 migrations (não existe 16) · 138 tabelas · 21 views + 1 MV · "
       "★ = regra inviolável com teste (T1–T129) · itálico = view</font>",
       40, 20, 1760, 60, "text;html=1;align=left;verticalAlign=middle;")

ids={}
col_bottom=[]
for c,schemas in colunas.items():
    y=TOP
    for s in schemas:
        i,h=schema_box(s,X[c],y,W)
        ids[s]=i
        y+=h+GY
    col_bottom.append(y)

band_y=max(col_bottom)+18
vertex("<b style='font-size:15px'>Camada de Agentes IA (17–21)</b> — Analista · Assessor · Educador · Contexto Pessoal"
       " &nbsp;·&nbsp; <font style='font-size:10px'>fluxo: LLM entende → despacha p/ código pronto → roda → LLM sintetiza</font>",
       40, band_y, 5*W+4*GX, 40,
       "text;html=1;align=left;verticalAlign=middle;fillColor=#e1d5e7;strokeColor=#9673a6;rounded=1;spacingLeft=12;")
ay=band_y+56
ah=0
for c,s in enumerate(["agents","tools","llm","analysis","context"]):
    i,h=schema_box(s,X[c],ay,W)
    ids[s]=i
    ah=max(ah,h)

cy=ay+ah+18
vertex("<b style='font-size:15px'>Camada de Contexto Pessoal (22–27)</b> — quem é a pessoa, quanto ganha, quanto tem, o que recusa"
       " &nbsp;·&nbsp; <font style='font-size:10px'>regra: dúvida mora em context.assertions; estrutura só recebe FATO CONFIRMADO (C22)</font>",
       40, cy, 5*W+4*GX, 40,
       "text;html=1;align=left;verticalAlign=middle;fillColor=#d0e8f2;strokeColor=#3a7ca5;rounded=1;spacingLeft=12;")
py=cy+56
ph=0
for c,s_ in enumerate(["household","estate","preferences","decisions","docs"]):
    i,h=schema_box(s_,X[c],py,W)
    ids[s_]=i
    ph=max(ph,h)

ly=py+ph+GY
vertex("<b>Setas</b><br/><font style='font-size:10px'>cheia = dependência estrutural (FK / gate / trigger) · "
       "tracejada = fluxo de leitura ou registro · vermelha = regra-estrela</font>",
       40, ly, 5*W+4*GX, 44,
       "rounded=1;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#999999;dashed=1;align=left;verticalAlign=middle;spacingLeft=12;")

E=edge
E(ids["identity"],ids["wealth"],"scope_id",exit_=(1,0.35),entry=(0,0.2))
E(ids["identity"],ids["billing"],"escopo assina",exit_=(1,0.12),entry=(0,0.12))
E(ids["market"],ids["wealth"],"instrumentos · preços D-1",exit_=(1,0.5),entry=(0,0.6))
E(ids["wealth"],ids["engine"],"insumos → run_inputs",exit_=(1,0.25),entry=(0,0.6))
E(ids["engine"],ids["diagnostics"],"runs geram findings",exit_=(0.5,1),entry=(0.5,0))
E(ids["engine"],ids["planning"],"builder · projeção · drift",exit_=(1,0.5),entry=(0,0.15))
E(ids["billing"],ids["diagnostics"],"min_plan (gate no output)",dashed=True,exit_=(1,0.5),entry=(0,0.25))
E(ids["diagnostics"],ids["ledger"],"ação concluída → valor",exit_=(0,0.8),entry=(1,0.3))
E(ids["diagnostics"],ids["content"],"sinais · notificações",color="#b85450",exit_=(1,0.55),entry=(0,0.55))
E(ids["diagnostics"],ids["analytics"],"gate_reveals → paywall",dashed=True,exit_=(1,0.2),entry=(0,0.55))
E(ids["billing"],ids["analytics"],"preço exibido / conversão",dashed=True,exit_=(1,0.3),entry=(0,0.3))
E(ids["budget"],ids["diagnostics"],"dívidas/reserva → Fundação",dashed=True,exit_=(1,0.4),entry=(0.2,1))
E(ids["planning"],ids["content"],"drift/calendário → sinais",dashed=True,exit_=(0.5,1),entry=(0.5,0))
E(ids["copilot"],ids["diagnostics"],"cited_refs: LÊ, não calcula",dashed=True,exit_=(0.5,0),entry=(0.7,1))
E(ids["engine"],ids["audit"],"trilha 'quem fez o quê'",dashed=True,color="#999999",exit_=(1,0.1),entry=(0,0.8))
E(ids["agents"],ids["tools"],"despacha parâmetros",color="#9673a6",exit_=(1,0.4),entry=(0,0.4))
E(ids["tools"],ids["analysis"],"execuções → tasks/evidência",color="#9673a6",exit_=(1,0.5),entry=(0,0.5))
E(ids["llm"],ids["agents"],"prompt aprovado = pré-condição",color="#9673a6",exit_=(0,0.25),entry=(1,0.7))
E(ids["analysis"],ids["llm"],"planner/síntese → model_calls",dashed=True,color="#9673a6",exit_=(0,0.35),entry=(1,0.45))
E(ids["context"],ids["agents"],"lê conversas ENCERRADAS",dashed=True,color="#9673a6",exit_=(0.15,0),entry=(0.85,1))
E(ids["context"],ids["identity"],"risco: exige NOVO suitability ★",color="#b85450",exit_=(1,0.1),entry=(1,0.9))
E(ids["agents"],ids["billing"],"cota por plano (AGENT_QUOTAS)",dashed=True,color="#9673a6",exit_=(0.35,0),entry=(0.15,1))
E(ids["tools"],ids["engine"],"mesmo padrão: git_sha + sha256",dashed=True,color="#9673a6",exit_=(0.65,0),entry=(0.35,1))
E(ids["context"],ids["household"],"fato confirmado → estrutura ★",color="#b85450",exit_=(0.5,1),entry=(0.5,0))
E(ids["household"],ids["estate"],"quem é dono do quê",exit_=(1,0.4),entry=(0,0.4))
E(ids["estate"],ids["preferences"],"iliquidez → restrição",dashed=True,exit_=(1,0.55),entry=(0,0.55))
E(ids["preferences"],ids["decisions"],"veto vira insumo do porquê",color="#b85450",exit_=(1,0.35),entry=(0,0.35))
E(ids["preferences"],ids["planning"],"gate: carteira-alvo recusa o vetado ★",color="#b85450",exit_=(0.5,0),entry=(0.35,1))
E(ids["decisions"],ids["identity"],"suitability VIGENTE na entrega ★",color="#b85450",dashed=True,exit_=(1,0.15),entry=(1,0.6))

page_h=ly+120
xml=(f'<mxfile host="app.diagrams.net" agent="synapta" version="24.7.7">'
     f'<diagram id="synapta-db" name="Banco Synapta (completo)">'
     f'<mxGraphModel dx="1600" dy="1000" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" '
     f'arrows="1" fold="1" page="1" pageScale="1" pageWidth="{5*W+4*GX+80}" pageHeight="{page_h}" math="0" shadow="0">'
     f'<root><mxCell id="0"/><mxCell id="1" parent="0"/>{"".join(cells)}</root>'
     f'</mxGraphModel></diagram></mxfile>')
out=OUT_DIR/"synapta_banco.drawio"
out.write_text(xml, encoding="utf-8")
import xml.etree.ElementTree as ET; ET.parse(out)
n_listed=sum(len(v) for v in tables.values())
print(f"drawio completo: {len(xml)} bytes · {len(cells)} células · {n_listed} tabelas listadas · páginas {5*W+4*GX+80}x{page_h}")
# Canário: o número é contado do SQL, então divergir significa que uma migration criou
# tabela e ninguém reviu o diagrama. Ficou parado em 135 desde a F17 — a migration 48
# acrescentou `assumption_sets`, `class_assumptions` e `class_correlations` e o assert
# não foi atualizado, então o canário estava morto justo quando devia cantar.
# Morreu de novo na 60: as duas tabelas do intake entraram e o número seguiu 138 (o real
# era 140). Cantou na 61 — 145 = 140 + as cinco do acervo de mercado. Canário só serve se
# quem passa por ele o atualiza; a conta está no `python tools/validador.py`.
assert n_listed==145, n_listed
