#!/usr/bin/env python3
"""Gera dashboards mensais Grupo Valente — v3 (light theme).

Uso:
    python3 gerar_relatorio.py \\
        --mes "Marco" --ano 2026 \\
        --transacional /path/pivot-29.csv \\
        --pivot        /path/pivot-28.csv \\
        --saida        /path/saida/ \\
        --dias-uteis 31 --dias-total 31 --completo \\
        --metas '{"erivan":{"global":60000,"abc":48000}, ...}'
"""
import argparse, csv, json, os, re, sys
from collections import defaultdict
from datetime import datetime

SELLER_NAMES = {
    'Célio Alex':             'celio',
    'Erivan Lima':            'erivan',
    'Lucas de Mello Valente': 'lucas',
    'Roger de Lima silva':    'roger',
    'Róger Silva':            'roger',
    'Jalena':                 'jalena',
}

SELLER_LABEL = {
    'erivan': 'Erivan',
    'lucas':  'Lucas',
    'roger':  'Roger',
    'jalena': 'Jalena',
    'celio':  'Celio',
}

MES_ABREV = {
    'janeiro':'jan','fevereiro':'fev','marco':'mar','março':'mar',
    'abril':'abr','maio':'mai','junho':'jun','julho':'jul',
    'agosto':'ago','setembro':'set','outubro':'out',
    'novembro':'nov','dezembro':'dez',
}

# ----- Categorização (regras de comissao-grupo-valente) -----
def categorizar(nome_produto):
    n = (nome_produto or '').upper()
    # ordem de prioridade
    A = ['B.URB','BURB','CHOICE BRO','EMBAIXADOR','ELEGANCE','KANNEP','MACHO-LANDIA','MACHO-LÂNDIA','RAUK','BARBAROUS']
    B = ['BIG BARBER','BTH','ELEMENT','EVOLUTION','M2A','PLAY','SHARK BARBER','ALFA','LOOK']
    C = ['BABOON','DON ALCIDES','FOX']
    D = ['MANTA','RMC','TECHNATURE','ESSENCIAL']
    AC_A = ['BARBER POLE','KOMAKAI','SUPERBARBA','HIGMAXX']
    AC_B = ['CABELL','CRICKET','FENIX','SUPREME','TALGE','TOPPIK','UMI','MOFASHI','ALLEY','GRUPO VALENTE',
            'PENTE','CAPA DE CORTE','GOLA HIGIENICA','GOLA HIGIÊNICA','TRIPÉ','TRIPE','SACOLA']
    MAQ = ['ANDIS','BABYLISS','GALLETZ','GBS','JRL','KEMEI','WMARK','WAHL','ZHORN','GAMA','VGR','FALCONPRO','FALCON PRO']
    MOV = ['MARRI','LAV CHAMP','DOMPEL']

    for k in A:
        if k in n: return 'Produtos A'
    for k in B:
        if k in n: return 'Produtos B'
    for k in C:
        if k in n: return 'Produtos C'
    for k in D:
        if k in n: return 'Produtos D'
    for k in AC_A:
        if k in n: return 'Acessorios A'
    for k in AC_B:
        if k in n: return 'Acessorios B'
    for k in MAQ:
        if k in n: return 'Maquinario'
    for k in MOV:
        if k in n: return 'Movelaria'
    return 'Outros'

def marca(nome_produto):
    n = (nome_produto or '').upper()
    for marca in ['MACHO-LANDIA','MACHO-LÂNDIA','BARBAROUS','RAUK','KANNEP','EMBAIXADOR','CHOICE BRO',
                  'ELEGANCE','B.URB','BURB','BIG BARBER','BTH','ELEMENT','EVOLUTION','M2A','PLAY','SHARK',
                  'ALFA LOOK','BABOON','DON ALCIDES','FOX','MANTA','RMC','TECHNATURE','ESSENCIAL',
                  'BARBER POLE','KOMAKAI','SUPERBARBA','HIGMAXX','CABELL','CRICKET','FENIX','SUPREME',
                  'TALGE','TOPPIK','UMI','MOFASHI','ALLEY','GRUPO VALENTE','ANDIS','BABYLISS','GALLETZ',
                  'GBS','JRL','KEMEI','WMARK','WAHL','ZHORN','GAMA','VGR','FALCONPRO','FALCON PRO',
                  'MARRI','LAV CHAMP','DOMPEL']:
        if marca in n:
            return marca.title()
    return 'Outras'


def parse_br_num(s):
    if s is None or s == '':
        return 0.0
    s = s.replace('"','').strip()
    # formato BR: 1.234,56
    s = s.replace('.','').replace(',','.')
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_pivot(path):
    """Lê pivot do Sankhya. Detecta automaticamente entre dois formatos:
    - Hierárquico (pivot-15 style): Vendedor / Cliente / Venda em linhas próprias
    - Flat (pivot-30 style): Vendedor, Cliente, NumeroVenda, Produto em colunas, fill-down
    Retorna dict: { sale_id: vendor_key }
    """
    sale_to_vendor = {}
    with open(path, encoding='utf-8-sig') as f:
        first_line = f.readline()
        is_flat = ',Cliente,' in first_line and ',Número da venda,' in first_line

    if is_flat:
        return _parse_pivot_flat(path)
    return _parse_pivot_hier(path)


def _parse_pivot_flat(path):
    sale_to_vendor = {}
    current_vendor = None
    with open(path, encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        header = next(reader)
        col = {h.strip(): i for i, h in enumerate(header)}
        for row in reader:
            if not row:
                continue
            v = row[col['Vendedor']].strip() if col.get('Vendedor', -1) >= 0 else ''
            if v and v != 'Total geral':
                current_vendor = SELLER_NAMES.get(v, None)
            sale = row[col['Número da venda']].strip() if 'Número da venda' in col else ''
            if sale and current_vendor:
                sale_to_vendor[sale] = current_vendor
    return sale_to_vendor


def _parse_pivot_hier(path):
    sale_to_vendor = {}
    current_vendor = None
    with open(path, encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        header_seen = False
        for row in reader:
            if not row or all(c == '' for c in row):
                continue
            first = row[0].strip()
            if not header_seen:
                if first == 'Nome do produto/serviço':
                    header_seen = True
                continue
            non_empty = [i for i, c in enumerate(row) if c.strip()]
            if len(non_empty) == 1 and non_empty[0] == 0:
                if first in SELLER_NAMES:
                    current_vendor = SELLER_NAMES[first]
                else:
                    if first.replace('.', '').isdigit():
                        if current_vendor:
                            sale_to_vendor[first] = current_vendor
    return sale_to_vendor


def parse_transacional(path, sale_to_vendor):
    """Lê pivot-16 style: uma linha por item. Retorna lista de dicts."""
    items = []
    with open(path, encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        header = next(reader)
        # mapeia indices
        col = {h.strip(): i for i,h in enumerate(header)}
        for row in reader:
            if not row or len(row) < len(header):
                continue
            sale = row[col['Número da venda']].strip()
            data_str = row[col['Data da venda']].strip()
            if not data_str or data_str == '(em branco)':
                continue
            try:
                dt = datetime.strptime(data_str, '%d/%m/%Y')
            except ValueError:
                continue
            cliente = row[col['Cliente']].strip()
            produto = row[col['Nome do produto/serviço']].strip()
            qtd = parse_br_num(row[col['Quantidade de itens']])
            valor_bruto = parse_br_num(row[col['Valor bruto']])
            tipo = row[col.get('Tipo de item (produto ou serviço)', -1)].strip() if 'Tipo de item (produto ou serviço)' in col else 'Produto'

            vendor = sale_to_vendor.get(sale, 'desconhecido')

            items.append({
                'sale': sale,
                'data': dt,
                'cliente': cliente,
                'produto': produto,
                'qtd': qtd,
                'valor': valor_bruto,
                'vendor': vendor,
                'categoria': categorizar(produto),
                'marca': marca(produto),
                'tipo': tipo,
            })
    return items


def fmt_brl(v):
    s = f"{v:,.2f}"
    s = s.replace(',', 'X').replace('.', ',').replace('X', '.')
    return f"R$ {s}"


def aggregate(items):
    """Aggrega os dados em vários cortes."""
    out = {
        'total': 0.0,
        'pedidos': set(),
        'clientes': set(),
        'itens': 0,
        'por_vendedor': defaultdict(lambda: {
            'total':0.0,'pedidos':set(),'clientes':set(),'itens':0,
            'por_dia':defaultdict(float),'por_categoria':defaultdict(float),
            'por_marca':defaultdict(float),'top_clientes':defaultdict(float),
            'top_produtos':defaultdict(float),'abc':0.0,
        }),
        'por_dia': defaultdict(float),
        'por_categoria': defaultdict(float),
        'por_marca': defaultdict(float),
        'top_clientes': defaultdict(float),
        'abc': 0.0,
    }
    for it in items:
        out['total'] += it['valor']
        out['pedidos'].add(it['sale'])
        out['clientes'].add(it['cliente'])
        out['itens'] += int(it['qtd'])
        d = it['data'].day
        out['por_dia'][d] += it['valor']
        out['por_categoria'][it['categoria']] += it['valor']
        out['por_marca'][it['marca']] += it['valor']
        out['top_clientes'][it['cliente']] += it['valor']
        if it['categoria'] in ('Produtos A','Produtos B','Produtos C'):
            out['abc'] += it['valor']

        v = out['por_vendedor'][it['vendor']]
        v['total'] += it['valor']
        v['pedidos'].add(it['sale'])
        v['clientes'].add(it['cliente'])
        v['itens'] += int(it['qtd'])
        v['por_dia'][d] += it['valor']
        v['por_categoria'][it['categoria']] += it['valor']
        v['por_marca'][it['marca']] += it['valor']
        v['top_clientes'][it['cliente']] += it['valor']
        v['top_produtos'][it['produto']] += it['valor']
        if it['categoria'] in ('Produtos A','Produtos B','Produtos C'):
            v['abc'] += it['valor']
    return out


# ----- HTML generation -----

CSS = """
:root {
  --bg: #eef2f7; --card: #ffffff; --border: #cbd5e1;
  --text: #0d1e33; --muted: #475569; --muted2: #334155;
  --primary: #0473E3; --green: #15803d; --red: #b91c1c;
  --bg-soft: #f1f5f9;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font-family: 'Inter', sans-serif; min-height: 100vh; padding-bottom: 60px; }
.num { font-family: 'Space Grotesk', sans-serif; letter-spacing: -.01em; font-weight: 700; }
header { background: var(--card); border-bottom: 1px solid var(--border); padding: 18px 28px; display: flex; justify-content: space-between; align-items: center; }
header .brand { font-size: 16px; font-weight: 700; color: var(--primary); letter-spacing: 1px; }
header .meta { text-align: right; font-size: 12px; color: var(--muted); }
header .meta h1 { font-size: 18px; color: var(--text); margin-bottom: 2px; }
main { max-width: 1320px; margin: 0 auto; padding: 24px 20px; }
section { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 22px; margin-bottom: 18px; }
section h2 { font-size: 14px; color: var(--muted); margin-bottom: 16px; text-transform: uppercase; letter-spacing: 1.2px; font-weight: 600; }

/* Hero */
.hero { display: grid; grid-template-columns: 1.4fr 1fr; gap: 24px; align-items: stretch; }
.hero-main { display: flex; flex-direction: column; justify-content: center; }
.hero-label { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 1.2px; }
.hero-value { font-size: 64px; line-height: 1; margin: 8px 0 12px; }
.hero-sub { font-size: 13px; color: var(--muted2); margin-bottom: 14px; }
.bar-wrap { background: var(--bg-soft); border-radius: 999px; height: 14px; overflow: hidden; margin-bottom: 6px; }
.bar { height: 100%; border-radius: 999px; transition: width .4s; }
.bar-info { display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); }
.satellites { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.sat { background: var(--bg-soft); border-radius: 10px; padding: 14px; }
.sat-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }
.sat-val { font-size: 22px; margin-top: 6px; }

/* Cards de meta */
.metas-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.meta-card { background: var(--bg-soft); border-radius: 10px; padding: 18px; }
.meta-card h3 { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 1.2px; margin-bottom: 10px; font-weight: 600; }
.meta-row { display: flex; justify-content: space-between; font-size: 13px; padding: 4px 0; }
.meta-row span:last-child { font-weight: 600; }

/* Vendedores grid */
.sellers-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(260px,1fr)); gap: 14px; }
.seller-card { background: var(--bg-soft); border-radius: 10px; padding: 16px; }
.seller-name { font-size: 14px; font-weight: 600; margin-bottom: 8px; }
.seller-total { font-size: 26px; margin-bottom: 8px; }
.seller-row { display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); padding: 2px 0; }

/* Tables */
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); }
th { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); font-weight: 600; }
td.r, th.r { text-align: right; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
@media (max-width: 768px) {
  .hero { grid-template-columns: 1fr; }
  .hero-value { font-size: 44px; }
  .metas-grid, .two-col { grid-template-columns: 1fr; }
}
nav { background: var(--card); padding: 0 28px; border-bottom: 1px solid var(--border); }
nav a { display: inline-block; padding: 12px 4px; margin-right: 22px; color: var(--muted); text-decoration: none; font-size: 13px; font-weight: 500; border-bottom: 2px solid transparent; }
nav a.active, nav a:hover { color: var(--primary); border-bottom-color: var(--primary); }

/* Tabs (vendedores page) */
.tabs { display: flex; gap: 4px; margin-bottom: 16px; flex-wrap: wrap; }
.tab { padding: 10px 16px; background: var(--card); border: 1px solid var(--border); border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 500; color: var(--muted); }
.tab.active { background: var(--primary); color: white; border-color: var(--primary); }
.tab-pane { display: none; }
.tab-pane.active { display: block; }
"""

FONT_LINK = '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap">'
CHART_CDN = '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>'


def color_for_pct(pct):
    if pct >= 100: return 'var(--green)'
    if pct >= 80:  return 'var(--primary)'
    return 'var(--red)'


def hero_block(label, total, meta, sub_satellites):
    pct = (total / meta * 100) if meta else 0
    color = color_for_pct(pct)
    width = min(pct, 100)
    sats_html = ''.join(
        f'<div class="sat"><div class="sat-label">{lbl}</div><div class="sat-val num">{val}</div></div>'
        for lbl,val in sub_satellites
    )
    meta_text = f"Meta: {fmt_brl(meta)}" if meta else "Sem meta global definida"
    return f'''
<section>
  <div class="hero">
    <div class="hero-main">
      <div class="hero-label">{label}</div>
      <div class="hero-value num">{fmt_brl(total)}</div>
      <div class="hero-sub">{meta_text}</div>
      {'<div class="bar-wrap"><div class="bar" style="width:'+str(width)+'%; background:'+color+';"></div></div>' if meta else ''}
      {'<div class="bar-info"><span>'+f'{pct:.1f}% atingido'+'</span><span>'+fmt_brl(max(0,meta-total))+' faltando</span></div>' if meta else ''}
    </div>
    <div class="satellites">{sats_html}</div>
  </div>
</section>
'''


def metas_block(real_global, meta_global, real_abc, meta_abc, dias_uteis, dias_total, completo):
    """Card duplo: meta global + meta ABC com realizado/projeção/gap."""
    def card(titulo, real, meta):
        if not meta:
            return f'''
<div class="meta-card">
  <h3>{titulo}</h3>
  <div class="meta-row"><span>Realizado</span><span>{fmt_brl(real)}</span></div>
  <div class="meta-row"><span>Meta</span><span>—</span></div>
</div>'''
        if completo:
            proj = real
        else:
            proj = real * dias_total / max(dias_uteis,1)
        gap = meta - real
        pct = real/meta*100 if meta else 0
        color = color_for_pct(pct)
        width = min(pct,100)
        return f'''
<div class="meta-card">
  <h3>{titulo}</h3>
  <div class="meta-row"><span>Meta</span><span>{fmt_brl(meta)}</span></div>
  <div class="meta-row"><span>Realizado</span><span>{fmt_brl(real)}</span></div>
  <div class="meta-row"><span>Projeção</span><span>{fmt_brl(proj)}</span></div>
  <div class="meta-row"><span>Gap</span><span style="color:{'var(--green)' if gap<=0 else 'var(--red)'};">{fmt_brl(gap)}</span></div>
  <div class="bar-wrap" style="margin-top:10px;"><div class="bar" style="width:{width}%; background:{color};"></div></div>
  <div class="bar-info"><span>{pct:.1f}% atingido</span><span>{'Acima da meta' if gap<=0 else 'Faltando '+fmt_brl(gap)}</span></div>
</div>'''
    return f'''
<section>
  <h2>Metas — visão consolidada</h2>
  <div class="metas-grid">
    {card("Meta Global", real_global, meta_global)}
    {card("Produtos A + B + C", real_abc, meta_abc)}
  </div>
</section>'''


def sellers_block(agg, metas):
    cards = []
    # ordena por total desc
    vendors = sorted(agg['por_vendedor'].items(), key=lambda kv: -kv[1]['total'])
    for vkey, v in vendors:
        if vkey == 'desconhecido':
            continue
        nome = SELLER_LABEL.get(vkey, vkey.capitalize())
        m = metas.get(vkey, {})
        meta_g = m.get('global')
        pct = (v['total']/meta_g*100) if meta_g else None
        color = color_for_pct(pct) if pct is not None else 'var(--primary)'
        width = min(pct or 0, 100)
        bar_html = (f'<div class="bar-wrap" style="margin-top:8px;"><div class="bar" style="width:{width}%; background:{color};"></div></div>'
                    f'<div class="bar-info"><span>{pct:.1f}% da meta global</span></div>') if pct is not None else ''
        cards.append(f'''
<div class="seller-card">
  <div class="seller-name">{nome}</div>
  <div class="seller-total num">{fmt_brl(v['total'])}</div>
  <div class="seller-row"><span>Pedidos</span><span class="num">{len(v['pedidos'])}</span></div>
  <div class="seller-row"><span>Clientes</span><span class="num">{len(v['clientes'])}</span></div>
  <div class="seller-row"><span>Itens</span><span class="num">{v['itens']}</span></div>
  <div class="seller-row"><span>A+B+C</span><span class="num">{fmt_brl(v['abc'])}</span></div>
  {bar_html}
</div>''')
    return '<section><h2>Vendedores</h2><div class="sellers-grid">' + ''.join(cards) + '</div></section>'


def chart_section(title, chart_id, labels, data, kind='bar', height=280):
    return f'''
<section>
  <h2>{title}</h2>
  <div style="height:{height}px;"><canvas id="{chart_id}"></canvas></div>
  <script>
    new Chart(document.getElementById('{chart_id}'), {{
      type: '{kind}',
      data: {{
        labels: {json.dumps(labels)},
        datasets: [{{
          label: 'Vendas',
          data: {json.dumps(data)},
          backgroundColor: 'rgba(4, 115, 227, 0.7)',
          borderColor: '#0473E3', borderWidth: 2, tension: 0.3
        }}]
      }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{ y: {{ ticks: {{ callback: v => 'R$ '+v.toLocaleString('pt-BR') }} }} }}
      }}
    }});
  </script>
</section>'''


def table_section(title, rows, cols, top=10):
    rows = rows[:top]
    if not rows:
        return f'<section><h2>{title}</h2><p style="color:var(--muted)">Sem dados</p></section>'
    head = ''.join(f'<th class="{c.get("cls","")}">{c["label"]}</th>' for c in cols)
    body = ''
    for r in rows:
        cells = ''.join(f'<td class="{c.get("cls","")}">{c["fmt"](r)}</td>' for c in cols)
        body += f'<tr>{cells}</tr>'
    return f'<section><h2>{title}</h2><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></section>'


def gerar_index(agg, metas, mes_label, ano, dias_uteis, dias_total, completo):
    media_dia = agg['total'] / max(dias_uteis,1)
    sats = [
        ('Pedidos', f"{len(agg['pedidos'])}"),
        ('Clientes', f"{len(agg['clientes'])}"),
        ('Itens', f"{agg['itens']}"),
        ('Média/dia', fmt_brl(media_dia)),
    ]
    meta_global_total = sum(m.get('global',0) or 0 for m in metas.values())
    meta_abc_total = sum(m.get('abc',0) or 0 for m in metas.values())

    hero = hero_block(f'Total — {mes_label} {ano}', agg['total'], meta_global_total, sats)
    metas_html = metas_block(agg['total'], meta_global_total, agg['abc'], meta_abc_total, dias_uteis, dias_total, completo)
    sellers = sellers_block(agg, metas)

    # Evolução diária
    dias = sorted(agg['por_dia'].keys())
    evol = chart_section(f'Evolução diária — {mes_label} {ano}', 'evol_chart',
                         [f'Dia {d}' for d in dias],
                         [round(agg['por_dia'][d],2) for d in dias])

    # Categorias
    cats = sorted(agg['por_categoria'].items(), key=lambda kv: -kv[1])
    cat_chart = chart_section('Vendas por categoria', 'cat_chart',
                              [c[0] for c in cats],
                              [round(c[1],2) for c in cats])

    # Top clientes
    top_cli = sorted(agg['top_clientes'].items(), key=lambda kv: -kv[1])
    top_cli_table = table_section('Top 15 clientes',
                                  [{'cliente':k,'valor':v} for k,v in top_cli],
                                  [{'label':'Cliente','fmt': lambda r: r['cliente']},
                                   {'label':'Valor','cls':'r','fmt': lambda r: f'<span class="num">{fmt_brl(r["valor"])}</span>'}],
                                  top=15)

    body = hero + metas_html + sellers + evol + cat_chart + top_cli_table

    return f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Grupo Valente — {mes_label} {ano}</title>
{FONT_LINK}
{CHART_CDN}
<style>{CSS}</style>
</head>
<body>
<header>
  <div class="brand">GRUPO VALENTE</div>
  <div class="meta">
    <h1>Dashboard {mes_label} {ano}</h1>
    <div>{dias_total} dias{'' if completo else ' (em andamento)'} · gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}</div>
  </div>
</header>
<nav>
  <a href="index.html" class="active">Visão Geral</a>
  <a href="vendedores_{MES_ABREV.get(mes_label.lower(),mes_label.lower()[:3])}{str(ano)[-2:]}.html">Vendedores</a>
</nav>
<main>
  {body}
</main>
</body>
</html>'''


def gerar_vendedores(agg, metas, mes_label, ano, dias_uteis, dias_total, completo):
    vendors = sorted(agg['por_vendedor'].items(), key=lambda kv: -kv[1]['total'])
    vendors = [(k,v) for k,v in vendors if k != 'desconhecido']

    tabs = ''.join(
        f'<button class="tab {"active" if i==0 else ""}" onclick="showTab(\'{vk}\')">{SELLER_LABEL.get(vk,vk.capitalize())}</button>'
        for i,(vk,_) in enumerate(vendors)
    )

    panes = []
    for i,(vk,v) in enumerate(vendors):
        nome = SELLER_LABEL.get(vk, vk.capitalize())
        m = metas.get(vk, {})
        meta_g = m.get('global')
        meta_abc = m.get('abc')
        ticket = v['total']/max(len(v['pedidos']),1)
        sats = [
            ('Pedidos', f"{len(v['pedidos'])}"),
            ('Clientes', f"{len(v['clientes'])}"),
            ('Itens', f"{v['itens']}"),
            ('Ticket Médio', fmt_brl(ticket)),
        ]
        hero = hero_block(f'{nome} — {mes_label} {ano}', v['total'], meta_g or 0, sats)
        metas_html = metas_block(v['total'], meta_g, v['abc'], meta_abc, dias_uteis, dias_total, completo)

        dias = sorted(v['por_dia'].keys())
        evol = chart_section('Evolução diária', f'evol_{vk}',
                             [f'D{d}' for d in dias],
                             [round(v['por_dia'][d],2) for d in dias],
                             kind='line')

        # top produtos & clientes lado a lado
        top_p = sorted(v['top_produtos'].items(), key=lambda kv: -kv[1])[:10]
        top_c = sorted(v['top_clientes'].items(), key=lambda kv: -kv[1])[:10]
        tp_rows = ''.join(f'<tr><td>{p[0][:55]}</td><td class="r"><span class="num">{fmt_brl(p[1])}</span></td></tr>' for p in top_p)
        tc_rows = ''.join(f'<tr><td>{c[0][:45]}</td><td class="r"><span class="num">{fmt_brl(c[1])}</span></td></tr>' for c in top_c)
        twocol = f'''
<section>
  <h2>Top produtos & clientes</h2>
  <div class="two-col">
    <div><h3 style="font-size:12px; color:var(--muted); margin-bottom:8px; text-transform:uppercase;">Produtos</h3>
      <table><tbody>{tp_rows}</tbody></table></div>
    <div><h3 style="font-size:12px; color:var(--muted); margin-bottom:8px; text-transform:uppercase;">Clientes</h3>
      <table><tbody>{tc_rows}</tbody></table></div>
  </div>
</section>'''

        # categorias
        cats = sorted(v['por_categoria'].items(), key=lambda kv: -kv[1])
        cat_chart = chart_section('Vendas por categoria', f'cat_{vk}',
                                  [c[0] for c in cats],
                                  [round(c[1],2) for c in cats])

        # marcas top 15
        marcas = sorted(v['por_marca'].items(), key=lambda kv: -kv[1])[:15]
        marca_chart = chart_section('Top 15 marcas', f'marca_{vk}',
                                    [m[0] for m in marcas],
                                    [round(m[1],2) for m in marcas])

        pane_body = hero + metas_html + evol + twocol + cat_chart + marca_chart
        panes.append(f'<div class="tab-pane {"active" if i==0 else ""}" id="pane_{vk}">{pane_body}</div>')

    panes_html = ''.join(panes)

    return f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vendedores — {mes_label} {ano}</title>
{FONT_LINK}
{CHART_CDN}
<style>{CSS}</style>
</head>
<body>
<header>
  <div class="brand">GRUPO VALENTE</div>
  <div class="meta">
    <h1>Vendedores · {mes_label} {ano}</h1>
    <div>Detalhe individual</div>
  </div>
</header>
<nav>
  <a href="index.html">Visão Geral</a>
  <a class="active">Vendedores</a>
</nav>
<main>
  <div class="tabs">{tabs}</div>
  {panes_html}
</main>
<script>
function showTab(vk) {{
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('pane_'+vk).classList.add('active');
}}
</script>
</body>
</html>'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mes', required=True)
    ap.add_argument('--ano', required=True, type=int)
    ap.add_argument('--transacional', required=True)
    ap.add_argument('--pivot', required=True)
    ap.add_argument('--saida', required=True)
    ap.add_argument('--dias-uteis', required=True, type=int)
    ap.add_argument('--dias-total', required=True, type=int)
    ap.add_argument('--completo', action='store_true')
    ap.add_argument('--metas', required=True)
    args = ap.parse_args()

    metas = json.loads(args.metas)

    print('Lendo pivot por vendedor...')
    sale_to_vendor = parse_pivot(args.pivot)
    print(f'  {len(sale_to_vendor)} vendas mapeadas a vendedores')

    print('Lendo transacional...')
    items = parse_transacional(args.transacional, sale_to_vendor)
    print(f'  {len(items)} linhas de itens')

    print('Agregando...')
    agg = aggregate(items)

    mes_lower = args.mes.lower()
    abrev = MES_ABREV.get(mes_lower, mes_lower[:3])
    sufixo = f"{abrev}{str(args.ano)[-2:]}"

    os.makedirs(args.saida, exist_ok=True)

    idx_path = os.path.join(args.saida, f'index_{sufixo}.html')
    vd_path  = os.path.join(args.saida, f'vendedores_{sufixo}.html')

    with open(idx_path,'w',encoding='utf-8') as f:
        f.write(gerar_index(agg, metas, args.mes, args.ano, args.dias_uteis, args.dias_total, args.completo))
    print(f'OK {idx_path}')

    with open(vd_path,'w',encoding='utf-8') as f:
        f.write(gerar_vendedores(agg, metas, args.mes, args.ano, args.dias_uteis, args.dias_total, args.completo))
    print(f'OK {vd_path}')

    print()
    print('Resumo consolidado:')
    print(f'  Total:    {fmt_brl(agg["total"])}')
    print(f'  Pedidos:  {len(agg["pedidos"])}')
    print(f'  Itens:    {agg["itens"]}')
    print(f'  Clientes: {len(agg["clientes"])}')
    for vk in sorted(agg['por_vendedor'], key=lambda k: -agg['por_vendedor'][k]['total']):
        if vk == 'desconhecido': continue
        v = agg['por_vendedor'][vk]
        print(f'  {SELLER_LABEL.get(vk,vk):<8}: {fmt_brl(v["total"]):>16} | {len(v["pedidos"])} pedidos')


if __name__ == '__main__':
    main()
