#!/usr/bin/env python3
"""Diagrama COMPLETO do banco Synapta (00-27) — PNG/PDF/SVG.
Rotas ortogonais pelos corredores; rótulos viram números na legenda."""
import re, pathlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle
from matplotlib.lines import Line2D

# Caminhos relativos ao próprio script: tools/ é irmão de sql/ e diagrama/.
ROOT = pathlib.Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql"
OUT_DIR = ROOT / "diagrama"

FILES = sorted(f for f in SQL_DIR.glob("*.sql") if f.name[0].isdigit())

tables, views = {}, {}
for f in FILES:
    sql = re.sub(r"--[^\n]*", "", f.read_text(encoding="utf-8"))
    for m in re.finditer(r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)\.(\w+)", sql):
        tables.setdefault(m.group(1), []).append(m.group(2))
    for m in re.finditer(r"CREATE (MATERIALIZED )?VIEW (\w+)\.(\w+)", sql):
        views.setdefault(m.group(2), []).append(("mv " if m.group(1) else "v ") + m.group(3))

STAR = {
 "policy_versions","runs","artifacts","findings","actions","finding_observations",
 "holdings_snapshots","target_portfolios","target_allocations","model_portfolios",
 "value_entries","notifications","paywall_impressions","events","activity_log",
 "conversations","messages","usage_counters","tool_executions","prompt_versions",
 "evidence_findings","reports","extraction_runs","signals","change_proposals",
 "portfolio_scores","scopes","suitability_assessments",
 "assertions","members","income_sources","income_summaries","assets","valuations",
 "constraints","records","rationale_items","inputs",
}
NEW = {"assertions","members","life_events","income_sources","income_summaries",
       "assets","valuations","constraints","liquidity_requirements",
       "records","rationale_items","inputs"}

META = {
 "identity":   ("01","#dae8fc","#6c8ebf","escopo = raiz de tudo (C1)"),
 "billing":    ("03","#dae8fc","#6c8ebf","plan_prices VAZIA — preço [PENDENTE]"),
 "engine":     ("02","#ffe6cc","#d79b00","reproduzo byte a byte o nº que o cliente viu"),
 "market":     ("04","#d5e8d4","#82b366","D-1 é contrato; parent_issuer = conglomerado"),
 "wealth":     ("05","#d5e8d4","#82b366","C7: snapshot NUNCA sofre UPDATE"),
 "diagnostics":("06+15","#fff2cc","#d6b656","cooldown/supressão vivem no FINDING"),
 "planning":   ("07","#fff2cc","#d6b656","1 carteira-alvo ativa; Σ pesos = 1,000"),
 "budget":     ("08+24","#fff2cc","#d6b656","renda: fixo ≠ variável; piso ≠ média"),
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
 "preferences":("26","#d0e8f2","#3a7ca5","o veto do cliente é inviolável"),
 "decisions":  ("27","#d0e8f2","#3a7ca5","não existe entrega sem porquê"),
}
TOUCHED = {"context","budget","household","estate","preferences","decisions","planning"}

W, GX, GY = 330, 32, 40
HEAD, ROW, FOOT = 42, 14.5, 30
X = [46 + i*(W+GX) for i in range(5)]
PAGE_W = X[4] + W + 60
TOPBAR = 150

def box_h(s):
    return HEAD + ROW*(len(tables.get(s, [])) + len(views.get(s, []))) + FOOT

boxes = {}
colunas = {0:["identity","market","budget"],
           1:["billing","wealth","ledger"],
           2:["engine","diagnostics","copilot"],
           3:["planning","content"],
           4:["analytics","audit"]}
col_bottom = []
for c, schemas in colunas.items():
    y = TOPBAR
    for s in schemas:
        h = box_h(s); boxes[s] = (X[c], y, W, h); y += h + GY
    col_bottom.append(y - GY)

band1_y = max(col_bottom) + 34
ay = band1_y + 74
ah = 0
for c, s in enumerate(["agents","tools","llm","analysis","context"]):
    h = box_h(s); boxes[s] = (X[c], ay, W, h); ah = max(ah, h)

band2_y = ay + ah + 44
py = band2_y + 74
ph = 0
for c, s in enumerate(["household","estate","preferences","decisions","docs"]):
    h = box_h(s); boxes[s] = (X[c], py, W, h); ph = max(ph, h)

legend_y = py + ph + 40
LEG_H = 196
PAGE_H = legend_y + LEG_H + 30

fig = plt.figure(figsize=(PAGE_W/100, PAGE_H/100), dpi=100)
ax = fig.add_axes([0, 0, 1, 1]); ax.set_axis_off()
ax.set_xlim(0, PAGE_W); ax.set_ylim(PAGE_H, 0); ax.set_aspect("equal")
fig.patch.set_facecolor("white")

def rounded(x, y, w, h, fill, stroke, lw=1.4, ls="solid", z=2):
    ax.add_patch(FancyBboxPatch((x, y+h), w, -h,
        boxstyle="round,pad=0,rounding_size=7", linewidth=lw, linestyle=ls,
        facecolor=fill, edgecolor=stroke, zorder=z, mutation_aspect=1))

for s, (x, y, w, h) in boxes.items():
    file_, fill, stroke, note = META[s]
    novo = s in TOUCHED
    rounded(x, y, w, h, fill, stroke, lw=2.6 if novo else 1.3, z=5)
    ax.text(x+w/2, y+21, s, ha="center", va="center", fontsize=14,
            fontweight="bold", color="#141414", zorder=6)
    ax.text(x+w/2, y+35, f"({file_}) · {len(tables.get(s,[]))} tab.",
            ha="center", va="center", fontsize=8, color="#555555", zorder=6)
    ax.plot([x+12, x+w-12], [y+42, y+42], color=stroke, lw=0.9, zorder=6)
    ty = y + 42 + ROW*0.9
    for t in tables.get(s, []):
        star = "★ " if t in STAR else "     "
        col = "#8a1f1f" if t in STAR else "#222222"
        ax.text(x+18, ty, star+t, ha="left", va="center", fontsize=8.8,
                color=col, fontweight="bold" if t in NEW else "normal", zorder=6)
        if t in NEW:
            ax.text(x+w-16, ty, "novo", ha="right", va="center", fontsize=6.6,
                    color="#2f6f95", style="italic", zorder=6)
        ty += ROW
    for v in views.get(s, []):
        ax.text(x+18, ty, "     "+v, ha="left", va="center", fontsize=8.6,
                color="#3f6b3f", style="italic", zorder=6)
        ty += ROW
    ax.plot([x+12, x+w-12], [y+h-24, y+h-24], color=stroke, lw=0.9, zorder=6)
    ax.text(x+w/2, y+h-13, note, ha="center", va="center", fontsize=7.6,
            color="#4a4a4a", style="italic", zorder=6)

ax.text(46, 36, "SYNAPTA · Banco de dados — diagrama completo",
        ha="left", va="center", fontsize=23, fontweight="bold", color="#111111")
ax.text(46, 66, "PostgreSQL 16+ · 27 migrations (não existe 16 — número reservado) · "
                "130 tabelas · 16 views + 1 MV · dinheiro é numeric, nunca float",
        ha="left", va="center", fontsize=11, color="#333333")
ax.text(46, 88, "★ = regra inviolável com teste (T1–T40)  ·  itálico = view  ·  "
                "borda grossa = schema criado ou estendido na onda 22–27  ·  "
                "números nas setas = legenda no rodapé",
        ha="left", va="center", fontsize=9.6, color="#555555")

def band(y, fill, stroke, title, sub):
    rounded(46, y, X[4]+W-46, 46, fill, stroke, lw=1.8, z=3)
    ax.text(60, y+17, title, ha="left", va="center", fontsize=13.5,
            fontweight="bold", color="#141414", zorder=4)
    ax.text(60, y+33, sub, ha="left", va="center", fontsize=8.8, color="#3d3d3d", zorder=4)

band(band1_y, "#e1d5e7", "#9673a6",
     "Camada de Agentes IA (17–21)  —  Analista · Assessor · Educador · Contexto Pessoal",
     "fluxo: LLM entende → despacha p/ código pronto → roda → LLM sintetiza")
band(band2_y, "#d0e8f2", "#3a7ca5",
     "Camada de Contexto Pessoal (22–27)  —  quem é a pessoa, quanto ganha, quanto tem, o que recusa",
     "C22: a dúvida mora em context.assertions; tabela estruturada só recebe FATO CONFIRMADO")

# ---------------------------------------------------------------- rotas
def L(s): return boxes[s][0]
def R(s): return boxes[s][0] + boxes[s][2]
def T(s): return boxes[s][1]
def B(s): return boxes[s][1] + boxes[s][3]
def fx(s, f): return boxes[s][0] + f*boxes[s][2]
def fy(s, f): return boxes[s][1] + f*boxes[s][3]

GUT = [X[i] + W + GX/2 for i in range(4)]      # corredores verticais
TOPC = TOPBAR - 16                              # corredor horizontal do topo
RIGHT = X[4] + W + 26                           # corredor da margem direita
def corr(a, b):                                 # corredor entre duas caixas empilhadas
    return (B(a) + T(b)) / 2

edges = []
def E(pts, label, color="#6b6b6b", dashed=False):
    edges.append((pts, label, color, dashed))

RED, PUR, BLU = "#b03a36", "#8a63a8", "#2f6f95"

# núcleo
E([(R("identity"), fy("identity",.20)), (L("billing"), fy("identity",.20))],
  "escopo assina o plano")
E([(R("identity"), fy("identity",.80)), (GUT[0], fy("identity",.80)),
   (GUT[0], fy("wealth",.22)), (L("wealth"), fy("wealth",.22))],
  "toda tabela financeira aponta scope_id, nunca user_id")
E([(R("market"), fy("market",.55)), (GUT[0], fy("market",.55)),
   (GUT[0], fy("wealth",.60)), (L("wealth"), fy("wealth",.60))],
  "instrumentos e preços D-1")
E([(R("wealth"), fy("wealth",.30)), (GUT[1], fy("wealth",.30)),
   (GUT[1], fy("engine",.72)), (L("engine"), fy("engine",.72))],
  "posições viram engine.run_inputs")
E([(fx("engine",.5), B("engine")), (fx("diagnostics",.5), T("diagnostics"))],
  "runs geram findings")
E([(R("engine"), fy("engine",.40)), (GUT[2], fy("engine",.40)),
   (GUT[2], fy("planning",.16)), (L("planning"), fy("planning",.16))],
  "builder · projeção · drift")
E([(R("billing"), fy("billing",.62)), (GUT[1], fy("billing",.62)),
   (GUT[1], fy("diagnostics",.16)), (L("diagnostics"), fy("diagnostics",.16))],
  "min_plan: gate de plano no output", dashed=True)
E([(L("diagnostics"), fy("diagnostics",.88)), (GUT[1], fy("diagnostics",.88)),
   (GUT[1], fy("ledger",.30)), (R("ledger"), fy("ledger",.30))],
  "ação concluída vira valor no Ledger")
E([(R("diagnostics"), fy("diagnostics",.55)), (GUT[2], fy("diagnostics",.55)),
   (GUT[2], fy("content",.50)), (L("content"), fy("content",.50))],
  "sinais e notificações", color=RED)
E([(fx("diagnostics",.88), T("diagnostics")), (fx("diagnostics",.88), corr("engine","diagnostics")),
   (GUT[3], corr("engine","diagnostics")), (GUT[3], fy("analytics",.62)),
   (L("analytics"), fy("analytics",.62))],
  "gate_reveals → funil de paywall", dashed=True)
E([(fx("billing",.88), T("billing")), (fx("billing",.88), TOPC),
   (fx("analytics",.30), TOPC), (fx("analytics",.30), T("analytics"))],
  "preço exibido e conversão", dashed=True)
E([(R("budget"), fy("budget",.22)), (GUT[0], fy("budget",.22)),
   (GUT[0], corr("wealth","ledger")), (GUT[1], corr("wealth","ledger")),
   (GUT[1], fy("diagnostics",.92)), (L("diagnostics"), fy("diagnostics",.92))],
  "dívidas e reserva alimentam a Fundação", dashed=True)
E([(fx("planning",.5), B("planning")), (fx("content",.5), T("content"))],
  "drift e calendário viram sinais", dashed=True)
E([(fx("copilot",.55), T("copilot")), (fx("copilot",.55), B("diagnostics"))],
  "copilot LÊ números; nunca calcula", dashed=True)
E([(fx("engine",.92), T("engine")), (fx("engine",.92), TOPC-14),
   (RIGHT, TOPC-14), (RIGHT, fy("audit",.55)), (R("audit"), fy("audit",.55))],
  "trilha 'quem fez o quê' (≠ engine.runs)", dashed=True, color="#8c8c8c")

# agentes
E([(R("agents"), fy("agents",.42)), (L("tools"), fy("agents",.42))],
  "LLM despacha parâmetros para o código pronto", color=PUR)
E([(R("tools"), fy("tools",.50)), (GUT[2], fy("tools",.50)),
   (GUT[2], fy("analysis",.55)), (L("analysis"), fy("analysis",.55))],
  "execuções viram tasks e evidência", color=PUR)
E([(fx("llm",.20), B("llm")), (fx("llm",.20), band2_y-8),
   (fx("agents",.72), band2_y-8), (fx("agents",.72), B("agents"))],
  "sem prompt aprovado por compliance, sem conversa", color=PUR)
E([(fx("context",.16), T("context")), (fx("context",.16), band1_y+58),
   (fx("agents",.88), band1_y+58), (fx("agents",.88), T("agents"))],
  "contexto lê apenas conversas ENCERRADAS", dashed=True, color=PUR)
E([(fx("context",.62), T("context")), (fx("context",.62), band1_y-16),
   (fx("identity",.86), band1_y-16), (fx("identity",.86), B("identity"))],
  "mudança de perfil de risco exige NOVO suitability ★", color=RED)

# onda 22-27
E([(fx("context",.40), B("context")), (fx("context",.40), band2_y-16),
   (fx("household",.50), band2_y-16), (fx("household",.50), T("household"))],
  "C22 — fato CONFIRMADO vira estrutura; dúvida fica na asserção ★", color=RED)
E([(R("household"), fy("household",.45)), (L("estate"), fy("household",.45))],
  "quem é dono de quê", color=BLU)
E([(R("estate"), fy("estate",.62)), (L("preferences"), fy("estate",.62))],
  "iliquidez do patrimônio vira restrição", dashed=True, color=BLU)
E([(R("preferences"), fy("preferences",.35)), (L("decisions"), fy("preferences",.35))],
  "o veto entra como insumo do porquê", color=RED)
E([(fx("preferences",.30), T("preferences")), (fx("preferences",.30), band2_y-34),
   (GUT[3], band2_y-34), (GUT[3], corr("planning","content")),
   (fx("planning",.72), corr("planning","content")), (fx("planning",.72), B("planning"))],
  "C26a — carteira-alvo, adoção e aporte RECUSAM o que o cliente vetou ★", color=RED)
E([(R("decisions"), fy("decisions",.18)), (RIGHT, fy("decisions",.18)),
   (RIGHT, fy("audit",.85)), (R("audit"), fy("audit",.85))],
  "C27 — o que foi entregue, por quê e com base em quê", dashed=True, color=RED)
E([(fx("household",.14), T("household")), (fx("household",.14), band2_y-20),
   (fx("budget",.62), band2_y-20), (fx("budget",.62), B("budget"))],
  "renda e dependentes por pessoa do núcleo", dashed=True, color=BLU)

def marker_pos(pts):
    """ponto médio pelo comprimento do caminho"""
    segs, tot = [], 0.0
    for i in range(len(pts)-1):
        d = abs(pts[i+1][0]-pts[i][0]) + abs(pts[i+1][1]-pts[i][1])
        segs.append(d); tot += d
    half, acc = tot/2, 0.0
    for i, d in enumerate(segs):
        if acc + d >= half:
            t = (half - acc) / d if d else 0
            return (pts[i][0] + t*(pts[i+1][0]-pts[i][0]),
                    pts[i][1] + t*(pts[i+1][1]-pts[i][1]))
        acc += d
    return pts[-1]

for n, (pts, label, color, dashed) in enumerate(edges, start=1):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    ax.add_line(Line2D(xs[:-1], ys[:-1], color=color, zorder=1,
                       linewidth=1.1 if dashed else 1.9,
                       linestyle=(0,(4,3)) if dashed else "solid",
                       solid_capstyle="round"))
    ax.add_patch(FancyArrowPatch(pts[-2], pts[-1], arrowstyle="-|>",
        mutation_scale=12, color=color, zorder=1, shrinkA=0, shrinkB=1,
        linewidth=1.1 if dashed else 1.9,
        linestyle=(0,(4,3)) if dashed else "solid"))
    mx, my = marker_pos(pts)
    ax.add_patch(Circle((mx, my), 9.5, facecolor="white", edgecolor=color,
                        linewidth=1.4, zorder=7))
    ax.text(mx, my, str(n), ha="center", va="center", fontsize=7.6,
            fontweight="bold", color=color, zorder=8)

# ---------------------------------------------------------------- legenda
rounded(46, legend_y, X[4]+W-46, LEG_H, "#fbfbfb", "#9a9a9a", lw=1.2, ls=(0,(5,4)), z=3)
ax.text(60, legend_y+20, "Setas", ha="left", va="center", fontsize=11.5,
        fontweight="bold", color="#222222", zorder=4)
ax.text(112, legend_y+20,
        "cheia = dependência estrutural (FK / gate / trigger)     ·     "
        "tracejada = fluxo de leitura ou registro     ·     vermelha = regra-estrela",
        ha="left", va="center", fontsize=9, color="#444444", zorder=4)
cols_x = [62, 62 + (X[4]+W-46)/3, 62 + 2*(X[4]+W-46)/3]
per = (len(edges) + 2) // 3
for n, (pts, label, color, dashed) in enumerate(edges, start=1):
    c, r = (n-1)//per, (n-1) % per
    lx_, ly_ = cols_x[c], legend_y + 44 + r*15.5
    ax.add_patch(Circle((lx_+7, ly_), 7.6, facecolor="white", edgecolor=color,
                        linewidth=1.2, zorder=4))
    ax.text(lx_+7, ly_, str(n), ha="center", va="center", fontsize=6.8,
            fontweight="bold", color=color, zorder=5)
    ax.text(lx_+21, ly_, label, ha="left", va="center", fontsize=8.3,
            color="#2a2a2a", zorder=4)

out = OUT_DIR
for ext in ("png", "pdf", "svg"):
    fig.savefig(out/f"synapta_banco_00-27.{ext}",
                dpi=150 if ext == "png" else None, facecolor="white")
print(f"ok {PAGE_W}x{PAGE_H} · {len(edges)} setas")
