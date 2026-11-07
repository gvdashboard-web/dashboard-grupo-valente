#!/usr/bin/env python3
"""Gera relatório HTML por produto a partir de produtos_cache.json.
Visual dark premium (modelo higimax_relatorio_10): Hero + KPIs, gráficos qtd/receita,
ranking de clientes, TENDÊNCIA (semestres + média móvel) e ANÁLISE DE CLIENTES/CHURN
(risco, frequência, última compra, atenção prioritária) + insights.

Gola e afins usam modo RECEITA (unidades incomparáveis entre fornecedores).
SEM margem/lucro (preferência do Lucas). Receita = bruto de linha (preço×qtd).

Uso: python3 gerar_relatorio_produto.py [cache.json] [pasta_saida]
"""
import sys, json, os

MESES_PT = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez']
REVENUE_ONLY = {'gola-higienica'}

def mlabel(ym):
    y,m = ym.split('-'); return f'{MESES_PT[int(m)-1]}/{y[2:]}'
def brl(v): return f'{round(v):,.0f}'.replace(',', '.')
def esc(s): return (s or '').replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')
def mdiff(a, b):
    ya,ma = int(a[:4]),int(a[5:7]); yb,mb = int(b[:4]),int(b[5:7])
    return (yb-ya)*12 + (mb-ma)

CSS = """*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root { --navy:#0a1628; --navy-2:#111f35; --navy-3:#172945; --blue:#2060c8; --blue-light:#3b82f6; --accent:#60a5fa; --gold:#f59e0b; --text:#e8f0fe; --muted:#9db4d4; --border:rgba(96,165,250,0.12); }
  html { scroll-behavior: smooth; }
  body { background: var(--navy); color: var(--text); font-family: 'DM Sans', sans-serif; font-weight: 300; line-height: 1.6; overflow-x: hidden; }
  .hero { min-height: 100vh; display: flex; flex-direction: column; justify-content: center; padding: 80px 60px; position: relative; overflow: hidden; }
  .hero::before { content:''; position:absolute; top:-200px; right:-200px; width:700px; height:700px; background:radial-gradient(circle, rgba(32,96,200,0.18) 0%, transparent 70%); pointer-events:none; }
  .hero::after { content:''; position:absolute; bottom:-100px; left:-100px; width:500px; height:500px; background:radial-gradient(circle, rgba(245,158,11,0.07) 0%, transparent 70%); pointer-events:none; }
  .hero-eyebrow { font-size:11px; letter-spacing:3px; text-transform:uppercase; color:var(--accent); margin-bottom:20px; opacity:0; animation:fadeUp 0.8s ease 0.1s forwards; }
  .hero-title { font-family:'DM Serif Display', serif; font-size:clamp(48px,7vw,96px); line-height:1.05; color:#fff; margin-bottom:12px; opacity:0; animation:fadeUp 0.8s ease 0.2s forwards; }
  .hero-title em { color:var(--accent); font-style:italic; }
  .hero-sub { font-size:16px; color:var(--muted); margin-bottom:56px; opacity:0; animation:fadeUp 0.8s ease 0.3s forwards; }
  .hero-kpis { display:grid; grid-template-columns:repeat(auto-fit, minmax(170px,1fr)); gap:16px; max-width:1100px; opacity:0; animation:fadeUp 0.8s ease 0.45s forwards; }
  .kpi-card { background:var(--navy-2); border:0.5px solid var(--border); border-radius:14px; padding:24px; transition:border-color 0.3s; }
  .kpi-card:hover { border-color:rgba(96,165,250,0.35); }
  .kpi-card .label { font-size:11px; letter-spacing:1.5px; text-transform:uppercase; color:var(--muted); margin-bottom:10px; }
  .kpi-card .value { font-family:'DM Serif Display', serif; font-size:34px; color:#fff; line-height:1; }
  .kpi-card .detail { font-size:12px; color:var(--muted); margin-top:6px; }
  .kpi-card.highlight { border-color:rgba(96,165,250,0.4); }
  .kpi-card.highlight .value { color:var(--accent); }
  .scroll-cue { position:absolute; bottom:40px; left:60px; font-size:12px; color:var(--muted); letter-spacing:1px; display:flex; align-items:center; gap:10px; opacity:0; animation:fadeUp 0.8s ease 0.7s forwards; }
  .scroll-cue::before { content:''; display:block; width:40px; height:0.5px; background:var(--muted); }
  section { padding:100px 60px; }
  .section-label { font-size:11px; letter-spacing:3px; text-transform:uppercase; color:var(--accent); margin-bottom:14px; }
  .section-title { font-family:'DM Serif Display', serif; font-size:clamp(32px,4vw,52px); color:#fff; line-height:1.1; margin-bottom:48px; }
  .section-title em { color:var(--accent); font-style:italic; }
  .chart-wrap { background:var(--navy-2); border:0.5px solid var(--border); border-radius:16px; padding:40px; }
  .chart-header { display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:32px; flex-wrap:wrap; gap:12px; }
  .chart-header h3 { font-family:'DM Serif Display', serif; font-size:24px; color:#fff; font-weight:400; }
  .chart-header span { font-size:13px; color:var(--muted); }
  .chart-container { position:relative; width:100%; height:320px; }
  .stat-grid { display:grid; gap:16px; margin-bottom:40px; }
  .stat-card { background:var(--navy-2); border:0.5px solid var(--border); border-radius:14px; padding:20px; }
  .stat-card .s-label { font-size:11px; letter-spacing:1.5px; text-transform:uppercase; color:var(--muted); margin-bottom:8px; }
  .stat-card .s-val { font-family:'DM Serif Display',serif; font-size:32px; color:#fff; line-height:1; }
  .stat-card .s-det { font-size:12px; color:var(--muted); margin-top:6px; }
  .client-grid { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
  .client-row { background:var(--navy-2); border:0.5px solid var(--border); border-radius:12px; padding:18px 20px; display:flex; align-items:center; gap:16px; transition:border-color 0.2s, transform 0.2s; }
  .client-row:hover { border-color:rgba(96,165,250,0.4); transform:translateY(-2px); }
  .rank { font-family:'DM Serif Display', serif; font-size:28px; color:var(--navy-3); min-width:36px; text-align:center; line-height:1; }
  .client-row.top1 .rank { color:var(--gold); }
  .client-row.top2 .rank { color:#94a3b8; }
  .client-row.top3 .rank { color:#b87333; }
  .client-info { flex:1; }
  .client-name { font-size:14px; font-weight:500; color:var(--text); }
  .client-qty { font-size:12px; color:var(--muted); margin-top:2px; }
  .bar-bg { width:80px; height:4px; background:var(--navy-3); border-radius:2px; overflow:hidden; }
  .bar-fill { height:100%; background:var(--blue-light); border-radius:2px; }
  .ctable { width:100%; border-collapse:collapse; font-size:13px; }
  .ctable th { text-align:center; padding:10px 14px; color:var(--muted); font-weight:500; letter-spacing:0.5px; font-size:11px; text-transform:uppercase; border-bottom:0.5px solid var(--border); }
  .ctable th:first-child, .ctable td:first-child { text-align:left; }
  .ctable td { text-align:center; padding:12px 14px; color:var(--text); border-bottom:0.5px solid rgba(96,165,250,0.06); }
  .badge { border-radius:20px; padding:3px 12px; font-size:11px; font-weight:600; letter-spacing:0.5px; }
  .b-alto { background:rgba(229,73,74,0.15); color:#E24B4A; }
  .b-medio { background:rgba(245,158,11,0.15); color:#f59e0b; }
  .b-ativo { background:rgba(29,158,117,0.15); color:#1D9E75; }
  .alert-box { margin-top:24px; background:rgba(229,73,74,0.08); border:0.5px solid rgba(229,73,74,0.3); border-radius:14px; padding:20px 24px; }
  .insights { display:grid; grid-template-columns:repeat(3,1fr); gap:16px; }
  .insight { border:0.5px solid var(--border); border-radius:14px; padding:28px; }
  .insight-icon { width:32px; height:32px; border-radius:8px; margin-bottom:16px; }
  .insight-icon.red { background:rgba(239,68,68,0.12); }
  .insight-icon.gold { background:rgba(245,158,11,0.15); }
  .insight-icon.blue { background:rgba(59,130,246,0.15); }
  .insight-icon.green { background:rgba(34,197,94,0.12); }
  .insight h4 { font-size:15px; font-weight:500; color:#fff; margin-bottom:8px; }
  .insight p { font-size:13px; color:var(--muted); line-height:1.6; }
  footer { padding:40px 60px; border-top:0.5px solid var(--border); display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; }
  footer p { font-size:12px; color:var(--muted); }
  .pill { background:var(--navy-2); border:0.5px solid var(--border); border-radius:20px; padding:6px 16px; font-size:12px; color:var(--accent); }
  .back-btn { position:fixed; top:22px; left:22px; z-index:60; background:rgba(17,31,53,0.82); backdrop-filter:blur(10px); border:0.5px solid var(--border); border-radius:24px; padding:9px 18px; font-size:13px; color:var(--accent); text-decoration:none; display:inline-flex; align-items:center; gap:7px; transition:border-color 0.2s, transform 0.2s, background 0.2s; }
  .back-btn:hover { border-color:rgba(96,165,250,0.5); transform:translateX(-3px); background:rgba(23,41,69,0.92); }
  @media (max-width:768px) { .back-btn { top:14px; left:14px; padding:7px 14px; font-size:12px; } }
  @keyframes fadeUp { from { opacity:0; transform:translateY(24px); } to { opacity:1; transform:translateY(0); } }
  .reveal { opacity:0; transform:translateY(30px); transition:opacity 0.7s ease, transform 0.7s ease; }
  .reveal.visible { opacity:1; transform:translateY(0); }
  @media (max-width:768px) { .hero, section, footer { padding:60px 24px; } .client-grid { grid-template-columns:1fr; } .insights { grid-template-columns:1fr; } .hero-kpis { grid-template-columns:1fr 1fr; } }"""


def kpi(label, value, detail, highlight=False):
    cls = 'kpi-card highlight' if highlight else 'kpi-card'
    return f'    <div class="{cls}"><div class="label">{label}</div><div class="value">{value}</div><div class="detail">{detail}</div></div>'

def insight(icon, titulo, texto):
    return f'    <div class="insight"><div class="insight-icon {icon}"></div><h4>{esc(titulo)}</h4><p>{esc(texto)}</p></div>'


def semestres(months_keys, vals):
    agg = {}; order = []
    for k,v in zip(months_keys, vals):
        h = 1 if int(k[5:7]) <= 6 else 2
        key = (int(k[:4]), h)
        if key not in agg: agg[key] = 0; order.append(key)
        agg[key] += v
    out = []
    peak = max((agg[k] for k in order), default=0)
    for (y,h) in order:
        mm = 'jan–jun' if h==1 else 'jul–dez'
        out.append((f'{h}º sem/{str(y)[2:]}', round(agg[(y,h)]), f'{h}º sem/{str(y)[2:]}\n({mm})', agg[(y,h)]==peak))
    return out


def classifica(desde):
    if desde <= 0: return ('ATIVO', 'b-ativo', 'ativo')
    if desde == 1: return ('BAIXO', 'b-ativo', 'baixo')
    if desde <= 4: return ('MÉDIO', 'b-medio', 'medio')
    return ('ALTO', 'b-alto', 'alto')


def churn(clientes, current_ym, is_rev, label_un):
    # ordena por métrica principal, pega top 15 com dado temporal
    keyf = (lambda v: v['receita']) if is_rev else (lambda v: v['qtd'])
    rows = [(nome,v) for nome,v in clientes.items() if keyf(v) > 0 and v.get('ultima')]
    rows.sort(key=lambda kv:-keyf(kv[1]))
    top = rows[:15]
    cnt = {'alto':0,'medio':0,'ativo':0}
    trs = []; alto_list = []
    for nome,v in top:
        ult_ym = v['ultima'][:7]; prim_ym = v.get('primeira', ult_ym)[:7]
        desde = mdiff(ult_ym, current_ym)
        span = mdiff(prim_ym, ult_ym) + 1
        n = v.get('n', len(v.get('meses', [])) or 1)
        txt, cls, grp = classifica(desde)
        cnt[grp if grp in cnt else 'ativo'] = cnt.get(grp if grp in cnt else 'ativo',0)
        if grp in ('ativo','baixo'): cnt['ativo'] += 1
        elif grp == 'medio': cnt['medio'] += 1
        else: cnt['alto'] += 1
        if span <= 1:
            freq = 'novo cliente' if n == 1 else f'{n}× em 1 mês'
        else:
            freq = f'~{n/span:.1f}× / mês'.replace('.', ',')
        if is_rev:
            col_tot = f'R$ {brl(v["receita"])}'
            col_ticket = f'R$ {brl(v["receita"]/n)}' if n else '—'
        else:
            col_tot = f'{round(v["qtd"])} un.'
            col_ticket = f'R$ {brl(v["receita"]/v["qtd"])}' if v['qtd'] else '—'
        badge_lbl = f'{txt}' + ('' if grp in ('ativo',) else f' · {desde} {"mês" if desde==1 else "meses"}')
        trs.append(
            f'        <tr><td>{esc(nome)}</td><td>{col_tot}</td><td style="color:var(--muted)">{freq}</td>'
            f'<td>{col_ticket}</td><td style="color:var(--muted)">{mlabel(ult_ym)}</td>'
            f'<td><span class="badge {cls}">{badge_lbl}</span></td></tr>')
        if grp == 'alto':
            alto_list.append((nome, v, desde))

    cards = (
        '  <div class="stat-grid reveal" style="grid-template-columns:repeat(3,1fr);">\n'
        f'    <div class="stat-card" style="border-color:rgba(229,73,74,0.5);text-align:center;"><div class="s-label" style="color:#E24B4A;">Risco alto</div><div class="s-val" style="color:#E24B4A;">{cnt["alto"]}</div><div class="s-det">parados muito além do habitual</div></div>\n'
        f'    <div class="stat-card" style="border-color:rgba(245,158,11,0.5);text-align:center;"><div class="s-label" style="color:#f59e0b;">Risco médio</div><div class="s-val" style="color:#f59e0b;">{cnt["medio"]}</div><div class="s-det">atraso moderado</div></div>\n'
        f'    <div class="stat-card" style="border-color:rgba(29,158,117,0.5);text-align:center;"><div class="s-label" style="color:#1D9E75;">Ativos</div><div class="s-val" style="color:#1D9E75;">{cnt["ativo"]}</div><div class="s-det">compraram recentemente</div></div>\n'
        '  </div>')

    table = ('  <div style="overflow-x:auto;" class="reveal">\n    <table class="ctable">\n'
             '      <thead><tr><th>Cliente</th><th>' + ('Receita' if is_rev else 'Total un.') +
             '</th><th>Freq. média</th><th>' + ('R$/compra' if is_rev else 'Ticket médio') +
             '</th><th>Última compra</th><th>Risco</th></tr></thead>\n      <tbody>\n'
             + '\n'.join(trs) + '\n      </tbody>\n    </table>\n  </div>')

    alto_list.sort(key=lambda x:-keyf(x[1]))
    if alto_list:
        nome,v,desde = alto_list[0]
        val = f'R$ {brl(v["receita"])}' if is_rev else f'{round(v["qtd"])} un'
        extra = ''
        if len(alto_list) > 1:
            outros = ', '.join(esc(a[0])[:22] for a in alto_list[1:3])
            extra = f' Junto com {outros}, são {len(alto_list)} clientes relevantes parados há vários meses.'
        callout = (
            '  <div class="alert-box reveal">\n'
            '    <div style="font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:#E24B4A;margin-bottom:8px;">⚠ Atenção prioritária</div>\n'
            f'    <p style="font-size:13px;color:var(--text);line-height:1.6;margin:0;"><strong>{esc(nome)}</strong> ({val}) está há <strong>{desde} meses sem comprar</strong> — um dos maiores do histórico.{extra} Uma reconexão pode recuperar parte dessa demanda.</p>\n'
            '  </div>')
    else:
        callout = (
            '  <div class="alert-box reveal" style="background:rgba(29,158,117,0.08);border-color:rgba(29,158,117,0.3);">\n'
            '    <div style="font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:#1D9E75;margin-bottom:8px;">✓ Base saudável</div>\n'
            '    <p style="font-size:13px;color:var(--text);line-height:1.6;margin:0;">Nenhum cliente relevante em risco alto no momento — a base recorrente está comprando dentro do ritmo esperado.</p>\n  </div>')
    return cards, table, callout


def build_script(is_rev, labels, qtys, revenue, sem, avg_val):
    series = revenue if is_rev else qtys
    sem_labels = [s[2] for s in sem]; sem_data = [s[1] for s in sem]
    sem_peak = [s[3] for s in sem]
    J = []
    J.append('const months=' + json.dumps(labels, ensure_ascii=False) + ';')
    J.append('const qtys=' + json.dumps(qtys) + ';')
    J.append('const revenue=' + json.dumps([round(r) for r in revenue]) + ';')
    J.append('const series=' + json.dumps([round(x) for x in series]) + ';')
    J.append('const semL=' + json.dumps(sem_labels, ensure_ascii=False) + ';const semD=' + json.dumps(sem_data) + ';const semPeak=' + json.dumps(sem_peak) + ';')
    J.append('const AVG=' + json.dumps(round(avg_val,1)) + ';const IS_REV=' + ('true' if is_rev else 'false') + ';')
    J.append(r"""
const maxR=Math.max(...revenue),maxQ=Math.max(...qtys),maxS=Math.max(...series);
function tl(fmt){return{id:'tl'+Math.random(),afterDatasetsDraw(c){const{ctx}=c;c.data.datasets.forEach((ds,i)=>{if(ds.type==='line')return;c.getDatasetMeta(i).data.forEach((b,idx)=>{if(ds.data[idx]==null)return;ctx.save();ctx.font='400 10px sans-serif';ctx.fillStyle='#8ab4d4';ctx.textAlign='center';ctx.textBaseline='bottom';ctx.fillText(fmt(ds.data[idx]),b.x,b.y-3);ctx.restore();});});}};}
const base={responsive:true,maintainAspectRatio:false,layout:{padding:{top:22}},plugins:{legend:{display:false}},scales:{x:{ticks:{color:'#7e9cbf',font:{size:10},autoSkip:false,maxRotation:45},grid:{display:false},border:{display:false}},y:{beginAtZero:true,grid:{color:'rgba(255,255,255,0.05)'},border:{display:false}}}};
const fk=v=>'R$'+(v/1000).toFixed(1)+'k';
if(document.getElementById('chartQty'))new Chart(chartQty,{type:'bar',data:{labels:months,datasets:[{data:qtys,backgroundColor:qtys.map(v=>v===maxQ?'#378ADD':'#185FA5'),borderRadius:4,borderSkipped:false}]},options:{...base,plugins:{...base.plugins,tooltip:{callbacks:{label:c=>` ${c.parsed.y} un.`}}},scales:{...base.scales,y:{...base.scales.y,ticks:{color:'#7e9cbf',font:{size:10},callback:v=>v+' un.'}}}},plugins:[tl(v=>v)]});
new Chart(chartRev,{type:'bar',data:{labels:months,datasets:[{data:revenue,backgroundColor:revenue.map(v=>v===maxR?'#378ADD':'#185FA5'),borderRadius:4,borderSkipped:false}]},options:{...base,plugins:{...base.plugins,tooltip:{callbacks:{label:c=>' R$ '+c.parsed.y.toLocaleString('pt-BR')}}},scales:{...base.scales,y:{...base.scales.y,ticks:{color:'#7e9cbf',font:{size:10},callback:fk}}}},plugins:[tl(fk)]});
new Chart(chartSem,{type:'bar',data:{labels:semL,datasets:[{data:semD,backgroundColor:semPeak.map(p=>p?'#378ADD':'#185FA5'),borderRadius:6,borderSkipped:false}]},options:{...base,plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>IS_REV?' R$ '+c.parsed.y.toLocaleString('pt-BR'):` ${c.parsed.y} un.`}}},scales:{...base.scales,y:{...base.scales.y,ticks:{color:'#7e9cbf',font:{size:10},callback:v=>IS_REV?fk(v):v+' un.'}}}},plugins:[tl(v=>IS_REV?fk(v):v)]});
function movAvg(a,w){return a.map((_,i)=>{if(i<w-1)return null;const s=a.slice(i-w+1,i+1);return Math.round(s.reduce((x,y)=>x+y,0)/w*10)/10;});}
new Chart(chartTrend,{data:{labels:months,datasets:[{type:'bar',data:series,backgroundColor:series.map(v=>v===maxS?'#378ADD':'#185FA5'),borderRadius:4,borderSkipped:false,order:2},{type:'line',data:movAvg(series,3),borderColor:'#E24B4A',borderWidth:2,pointRadius:0,tension:0.4,spanGaps:false,order:1},{type:'line',data:months.map(()=>AVG),borderColor:'#f59e0b',borderWidth:1.5,borderDash:[6,4],pointRadius:0,order:0}]},options:{...base,plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>c.dataset.type==='line'?(c.datasetIndex===1?` MM3: ${c.parsed.y}`:` média ${AVG}`):(IS_REV?' R$ '+c.parsed.y.toLocaleString('pt-BR'):` ${c.parsed.y} un.`)}}},scales:{...base.scales,y:{...base.scales.y,ticks:{color:'#7e9cbf',font:{size:10},callback:v=>IS_REV?fk(v):v+' un.'}}}}});
const obs=new IntersectionObserver(es=>{es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('visible');obs.unobserve(e.target);}});},{threshold:0.12});
document.querySelectorAll('.reveal').forEach(el=>obs.observe(el));
""")
    return '\n'.join(J)


def gerar(slug, d, ultimo_label):
    mk = sorted(d['months'].keys())
    qtys = [round(d['months'][k]['qtd']) for k in mk]
    revenue = [round(d['months'][k]['receita']) for k in mk]
    labels = [mlabel(k) for k in mk]
    n = len(mk); current_ym = mk[-1]
    is_rev = slug in REVENUE_ONLY or d.get('revenue_only')
    series = revenue if is_rev else qtys
    tot_q = sum(qtys); tot_r = sum(revenue)
    preco = (tot_r/tot_q) if tot_q else 0
    media_q = tot_q/n if n else 0
    media_r = tot_r/n if n else 0
    avg_val = media_r if is_rev else media_q
    estoque = d.get('estoque') or 0
    ult6 = series[-6:] if len(series)>=6 else series
    ritmo = (sum(ult6)/len(ult6)) if ult6 else 0
    cobertura = (estoque/(sum(qtys[-6:])/len(qtys[-6:]))) if (not is_rev and qtys[-6:] and sum(qtys[-6:])) else 0
    pico_i = revenue.index(max(revenue)) if revenue else 0
    pico_q_i = series.index(max(series)) if series else 0

    # clientes ranking (por métrica principal)
    keyf = (lambda v: v['receita']) if is_rev else (lambda v: v['qtd'])
    cli = sorted(d['clientes'].items(), key=lambda kv:-keyf(kv[1]))
    cli_base = sum(1 for _,v in cli if keyf(v) > 0)
    cli_ativos = sum(1 for _,v in cli if keyf(v) > 0 and v.get('ultima') and mdiff(v['ultima'][:7], current_ym) <= 3)
    top = [(k,v) for k,v in cli if keyf(v) > 0][:8]
    max_cli = keyf(top[0][1]) if top else 1
    top3 = sum(keyf(v) for _,v in top[:3]); base_tot = (tot_r if is_rev else tot_q) or 1
    top3_pct = top3/base_tot*100

    sem = semestres(mk, series)
    sem_cards = ''
    for s in sem[-4:]:
        bstyle = " style='border-color:rgba(96,165,250,0.4)'" if s[3] else ''
        vstyle = " style='color:var(--accent)'" if s[3] else ''
        peak = ' ↑ pico' if s[3] else ''
        val = ('R$ ' + brl(s[1])) if is_rev else (str(s[1]) + ' un.')
        sem_cards += (f'    <div class="stat-card"{bstyle}>'
                      f'<div class="s-label">{s[0]}{peak}</div>'
                      f'<div class="s-val"{vstyle}>{val}</div></div>\n')
    churn_cards, churn_table, churn_callout = churn(d['clientes'], current_ym, is_rev, 'un')

    # KPIs (modelo: 3 no hero)
    if is_rev:
        kpis = [kpi('Receita bruta', f'R${brl(tot_r)}', f'R$ {brl(media_r)}/mês', True),
                kpi('Receita recente', f'R${brl(ritmo)}', 'média/mês (6m)'),
                kpi('Clientes ativos', f'{cli_ativos}', f'{cli_base} no histórico · ativo = compra ≤3m')]
    else:
        kpis = [kpi('Unidades vendidas', f'{tot_q}', f'média {media_q:.1f} un/mês'),
                kpi('Receita bruta', f'R${brl(tot_r)}', f'R$ {brl(media_r)}/mês', True),
                kpi('Clientes ativos', f'{cli_ativos}', f'{cli_base} no histórico · ativo = compra ≤3m')]

    # client ranking rows
    rows = []
    for i,(nome,v) in enumerate(top):
        topcls = f' top{i+1}' if i<3 else ''
        w = round(keyf(v)/max_cli*100)
        pct = keyf(v)/base_tot*100
        det = (f'R$ {brl(v["receita"])} · {pct:.1f}% da receita') if is_rev else (f'{round(v["qtd"])} unidades · {pct:.1f}% do total')
        rows.append(f'    <div class="client-row{topcls}"><div class="rank">{i+1}</div>'
                    f'<div class="client-info"><div class="client-name">{esc(nome)}</div>'
                    f'<div class="client-qty">{det}</div></div>'
                    f'<div class="bar-bg"><div class="bar-fill" style="width:{w}%"></div></div></div>')

    # tendência recente p/ insight
    r3 = (sum(series[-3:])/len(series[-3:])) if series[-3:] else 0
    delta = ((r3-avg_val)/avg_val*100) if avg_val else 0
    tre_icon = 'green' if delta>10 else ('red' if delta<-10 else 'blue')
    tre_dir = 'acima' if delta>=0 else 'abaixo'
    meses_com = sum(1 for x in series if x>0)
    ins = []
    ins.append(insight('gold','Melhor mês', f'Pico em {labels[pico_i]} com R${brl(revenue[pico_i])} de receita'
                       + ('.' if is_rev else f' ({qtys[pico_i]} un).')))
    if is_rev:
        ins.append(insight('blue','Troca de fornecedor',
            'Até Nov/2025 a gola vinha do NECK PAPER (rolos de 100); desde Dez/2025 via FOX/DPM (por unidade). '
            'Como as embalagens não são comparáveis, o relatório usa RECEITA — a única métrica consistente.'))
    else:
        cob_icon = 'green' if cobertura>=2 else ('gold' if cobertura>=1 else 'red')
        cob_txt = 'confortável' if cobertura>=2 else ('apertado' if cobertura>=1 else 'crítico')
        ins.append(insight(cob_icon, f'Estoque {cob_txt}',
            f'{estoque:.0f} em estoque. No ritmo recente (~{ritmo:.0f}/mês, 6m), são ~{cobertura:.1f} meses de cobertura.'))
    ins.append(insight('blue','Concentração de clientes',
        f'Top 3 somam {top3_pct:.0f}% {"da receita" if is_rev else "das unidades"}, entre {cli_base} clientes no histórico ({cli_ativos} ativos nos últimos 3m).'))
    if top:
        n1 = top[0]
        v1 = (f'R$ {brl(n1[1]["receita"])}') if is_rev else (f'{round(n1[1]["qtd"])} un')
        ins.append(insight('gold','Cliente líder', f'{esc(n1[0])} puxa a demanda: {v1} ({keyf(n1[1])/base_tot*100:.0f}% do total).'))
    ins.append(insight(tre_icon,'Tendência recente',
        f'Últimos 3 meses {"~R$"+brl(r3) if is_rev else f"~{r3:.0f} un"}/mês — {abs(delta):.0f}% {tre_dir} da média histórica.'))
    ins.append(insight('blue','Consistência de demanda',
        f'{meses_com} de {n} meses com venda. {("Receita média R$"+brl(media_r)+"/mês.") if is_rev else ("Ticket médio R$"+brl(preco)+".")}'))

    # charts: modo unidade tem chartQty; receita só chartRev
    qty_chart_section = '' if is_rev else f"""
<section>
  <div class="section-label reveal">Evolução temporal</div>
  <h2 class="section-title reveal">Vendas mês<br>a <em>mês</em></h2>
  <div class="chart-wrap reveal">
    <div class="chart-header"><h3>Quantidade vendida</h3><span>Total: {tot_q} unidades · {labels[0]} – {labels[-1]} ({ultimo_label})</span></div>
    <div class="chart-container"><canvas id="chartQty"></canvas></div>
  </div>
</section>"""
    rev_chart_pad = 'padding-top:0;' if not is_rev else ''
    rev_header_extra = f' · Pico {labels[pico_i]} R${brl(revenue[pico_i])}'

    footer_pills = (
        f'<span class="pill">Receita total: R$ {brl(tot_r)}</span><span class="pill">Estoque: {estoque:.0f} un.</span><span class="pill">{cli_ativos} clientes</span>'
        if is_rev else
        f'<span class="pill">Estoque: {estoque:.0f} un.</span><span class="pill">Preço médio: R$ {brl(preco)}</span><span class="pill">{tot_q} vendas totais</span>')
    metodo = 'por receita' if is_rev else 'por unidade'

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(d['label'])} · Relatório de Vendas</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
  {CSS}
</style>
</head>
<body>
<a href="index.html" class="back-btn">← Todos os produtos</a>
<section class="hero">
  <div class="hero-eyebrow">Relatório de Vendas · {labels[0]} – {labels[-1]} · {metodo}</div>
  <h1 class="hero-title">{esc(d['label'])}</h1>
  <p class="hero-sub">{esc(d['subtitle'])} · Histórico completo de movimentação</p>
  <div class="hero-kpis">
{chr(10).join(kpis)}
  </div>
  <div class="scroll-cue">role para ver a análise</div>
</section>
{qty_chart_section}
<section style="{rev_chart_pad}">
  <div class="chart-wrap reveal">
    <div class="chart-header"><h3>Receita mensal</h3><span>Total R$ {brl(tot_r)}{rev_header_extra} · {ultimo_label}</span></div>
    <div class="chart-container"><canvas id="chartRev"></canvas></div>
  </div>
</section>
<section>
  <div class="section-label reveal">Clientes</div>
  <h2 class="section-title reveal">Quem mais<br><em>compra</em></h2>
  <div class="client-grid reveal">
{chr(10).join(rows) if rows else '    <p style="color:var(--muted)">Sem clientes no período.</p>'}
  </div>
</section>
<section>
  <div class="section-label reveal">Tendência</div>
  <h2 class="section-title reveal">Evolução por<br><em>semestre</em></h2>
  <div class="stat-grid reveal" style="grid-template-columns:repeat({min(4,len(sem))},1fr);">
{sem_cards}  </div>
  <div class="chart-wrap reveal">
    <div class="chart-header"><h3>{"Receita" if is_rev else "Unidades"} por semestre</h3><span>pico destacado</span></div>
    <div class="chart-container"><canvas id="chartSem"></canvas></div>
  </div>
  <div class="chart-wrap reveal" style="margin-top:40px;">
    <div class="chart-header"><h3>Tendência mensal com média móvel</h3><span>linha vermelha = média móvel 3m · tracejado = média histórica</span></div>
    <div class="chart-container"><canvas id="chartTrend"></canvas></div>
  </div>
</section>
<section>
  <div class="section-label reveal">Análise de clientes</div>
  <h2 class="section-title reveal">Frequência &amp;<br><em>risco de churn</em></h2>
{churn_cards}
{churn_table}
{churn_callout}
</section>
<section>
  <div class="section-label reveal">Insights</div>
  <h2 class="section-title reveal">Pontos de<br><em>atenção</em></h2>
  <div class="insights reveal">
{chr(10).join(ins)}
  </div>
</section>
<footer>
  <p>Conta Azul Pro · {labels[0]} – {labels[-1]} · {ultimo_label} · Dados via API · {metodo} · SKU {", ".join(d['skus'])}</p>
  <div style="display:flex;gap:10px;flex-wrap:wrap;">{footer_pills}</div>
</footer>
<script>
{build_script(is_rev, labels, qtys, revenue, sem, avg_val)}
</script>
</body>
</html>"""
    return html


def gerar_indice(blob, saida):
    prods = blob['products']
    cards = []
    for slug,d in prods.items():
        is_rev = slug in REVENUE_ONLY
        tot = f'R$ {brl(d["total_receita"])}' if is_rev else f'{round(d["total_qtd"])} un · R$ {brl(d["total_receita"])}'
        cards.append(
            f'<a href="{slug}.html" style="text-decoration:none;"><div class="kpi-card" style="cursor:pointer;">'
            f'<div class="label">{esc(d["subtitle"])[:42]}</div>'
            f'<div class="value" style="font-size:26px;">{esc(d["label"])}</div>'
            f'<div class="detail">{tot} · estoque {round(d.get("estoque") or 0)}</div></div></a>')
    html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Produtos · Grupo Valente</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>{CSS}</style></head>
<body><section class="hero" style="min-height:auto;padding-bottom:60px;">
  <div class="hero-eyebrow">Grupo Valente · Relatórios por produto</div>
  <h1 class="hero-title">Produtos<br><em>monitorados</em></h1>
  <p class="hero-sub">Atualizado automaticamente via Conta Azul · {blob.get('period',{}).get('start','')} – {blob.get('period',{}).get('end','')}</p>
  <div class="hero-kpis" style="grid-template-columns:repeat(auto-fit,minmax(240px,1fr));">
  {''.join(cards)}
  </div>
</section></body></html>"""
    with open(os.path.join(saida,'index.html'),'w') as f:
        f.write(html)


def main():
    _base = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
    cache = sys.argv[1] if len(sys.argv)>1 else os.path.join(_base, 'produtos_cache.json')
    saida = sys.argv[2] if len(sys.argv)>2 else os.path.join(_base, 'relatorios-produtos')
    os.makedirs(saida, exist_ok=True)
    with open(cache) as f:
        blob = json.load(f)
    _end = blob.get('period',{}).get('end','')
    ultimo_label = f'{MESES_PT[int(_end[5:7])-1].lower()} parcial' if _end else ''
    for slug, d in blob['products'].items():
        with open(os.path.join(saida, f'{slug}.html'),'w') as f:
            f.write(gerar(slug, d, ultimo_label))
        print(f'OK {slug}  ({round(d["total_qtd"])} un, R$ {round(d["total_receita"]):,})')
    gerar_indice(blob, saida)
    print(f'OK index.html')

if __name__ == '__main__':
    main()
