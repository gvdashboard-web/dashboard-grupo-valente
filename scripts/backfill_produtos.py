#!/usr/bin/env python3
"""Backfill histórico de 5 produtos via API Conta Azul -> cache JSON.
Varre todas as vendas Mai/2024..Jun/2026, casa itens por nome, agrega por mês e cliente.
Checkpoint por mês. Read-only na API.
"""
import sys, json, unicodedata, os
_SCRIPTDIR = os.path.dirname(os.path.abspath(__file__))
_BASE = os.path.abspath(os.path.join(_SCRIPTDIR, '..'))  # raiz do repo gv-dashboard (local ou CI)
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, _SCRIPTDIR)
from ca_client import ContaAzulClient

OUT = os.environ.get('PRODUTOS_CACHE') or os.path.join(_BASE, 'produtos_cache.json')

def norm(s):
    s = unicodedata.normalize('NFD', s or '')
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn').upper()

# slug, label, subtitle, skus, predicado(nome_normalizado)
PRODUTOS = [
    dict(slug='toalha-higimax', label='Toalha Higimax',
         subtitle='Barbearia 30×45 cm · 500 UN.', skus=['20556379485060'],
         match=lambda n: 'HIGIMAX' in n),
    dict(slug='lamina-superbarba', label='Lâmina Superbarba',
         subtitle='Lâmina Super Inoxidável', skus=['V9400-U'],
         match=lambda n: 'SUPERBARBA' in n),
    dict(slug='gola-higienica', label='Gola Higiênica',
         subtitle='Descartável de pescoço · FOX + DPM + Neck Paper', skus=['FX0047','DPM0045','ACR0031'],
         match=lambda n: 'GOLA' in n and 'HIGI' in n,
         qty_mult=lambda n: 100 if 'NECK PAPER' in n else 1),
    dict(slug='luvas', label='Luvas',
         subtitle='Nitrílica/Vinil Talge · P/M/G (agregado)', skus=['7062','7350','7351','7352'],
         match=lambda n: 'LUVA' in n and 'TALGE' in n),
    dict(slug='mascaras-tnt', label='Máscaras TNT',
         subtitle='TNT tripla elástico descartável', skus=['7392'],
         match=lambda n: 'MASCARA' in n and 'TNT' in n),
    dict(slug='johnnie-lizz', label='Johnnie Lizz',
         subtitle='Macho-Lândia · 1L + 200ml (agregado)', skus=['ML0015','ML0032'],
         match=lambda n: 'JOHNNIE' in n),
    dict(slug='komakai', label='Komakai',
         subtitle='Tesouras profissionais · marca completa (sem distinção de modelo)',
         skus=['KOMAKAI · todos os modelos'], estoque_by_name=True, from_ym='2026-01',
         match=lambda n: 'KOMAKAI' in n),
    dict(slug='embaixador', label='Embaixador',
         subtitle='Marca completa · sem distinção de modelo',
         skus=['EMBAIXADOR · todos os produtos'], estoque_by_name=True,
         match=lambda n: 'EMBAIXADOR' in n),
    dict(slug='bth', label='BTH',
         subtitle='Marca completa · sem distinção de modelo',
         skus=['BTH · todos os produtos'], estoque_by_name=True,
         match=lambda n: 'BTH' in n),
]
PROD_FROM = {p['slug']: p.get('from_ym') for p in PRODUTOS}
NOMES_MATCH = defaultdict(set)   # debug: nomes distintos casados por produto (vai pro log do Action)

def meses_range(ini_y, ini_m, fim_y, fim_m):
    y,m = ini_y, ini_m
    while (y,m) <= (fim_y,fim_m):
        yield y,m
        m += 1
        if m>12: m=1; y+=1

import calendar
HOJE = datetime.now(); CUR_Y, CUR_M = HOJE.year, HOJE.month; HOJE_STR = HOJE.strftime('%Y-%m-%d')
client = ContaAzulClient()
print('Conectado. Buscando estoque atual...', file=sys.stderr)

# Estoque atual de todos os SKUs
catalogo = []
pg=1
while True:
    r = client.get('/produto/busca', pagina=pg, tamanho_pagina=1000)
    it = r.get('itens',[])
    if not it: break
    catalogo.extend(it)
    if len(it)<1000: break
    pg+=1
sku_info = {p.get('codigo_sku'): p for p in catalogo}

# Estrutura de acumulação
data = {}
for prod in PRODUTOS:
    if prod.get('estoque_by_name'):
        matched = [p for p in catalogo if prod['match'](norm(p.get('nome','')))]
        est = sum((p.get('estoque') or 0) for p in matched)
        vendas = [p.get('valor_venda') for p in matched if p.get('status')=='ATIVO' and p.get('valor_venda')]
    else:
        est = sum((sku_info.get(s,{}).get('estoque') or 0) for s in prod['skus'])
        vendas = [sku_info.get(s,{}).get('valor_venda') for s in prod['skus'] if sku_info.get(s,{}).get('valor_venda')]
    data[prod['slug']] = dict(
        label=prod['label'], subtitle=prod['subtitle'], skus=prod['skus'],
        estoque=est, valor_venda=(max(vendas) if vendas else None),
        months={}, clientes=defaultdict(lambda:{'qtd':0,'receita':0.0,'meses':set(),'ultima':'','primeira':'','n':0}),
        total_qtd=0, total_receita=0.0)

def save():
    out = {}
    for slug,d in data.items():
        out[slug] = dict(d)
        cli_ser = {}
        for k,v in d['clientes'].items():
            vv = dict(v); vv['meses'] = sorted(v['meses'])
            cli_ser[k] = vv
        out[slug]['clientes'] = cli_ser
    with open(OUT,'w') as f:
        json.dump({'period':{'start':'2024-05','end':f'{CUR_Y:04d}-{CUR_M:02d}'},'products':out}, f, ensure_ascii=False, indent=1)

for y,m in meses_range(2024,5,CUR_Y,CUR_M):
    ym = f'{y:04d}-{m:02d}'
    ult_dia = calendar.monthrange(y,m)[1]
    fim = f'{ym}-{ult_dia:02d}' if not (y==CUR_Y and m==CUR_M) else HOJE_STR
    ini = f'{ym}-01'
    mes_acc = {p['slug']:{'qtd':0,'receita':0.0} for p in PRODUTOS}
    pagina=1; n_vendas=0
    while True:
        res = client.get('/venda/busca', data_inicio=ini, data_fim=fim,
                         totais='APPROVED', pagina=pagina, tamanho_pagina=500)
        vendas = res.get('itens',[]) if isinstance(res,dict) else []
        if not vendas: break
        for venda in vendas:
            sid = venda['id']; cli = venda.get('cliente',{}).get('nome','?')
            sdate = venda.get('data','')
            try:
                ir = client.get(f'/venda/{sid}/itens', tamanho_pagina=200)
                itens = ir.get('itens',[]) if isinstance(ir,dict) else []
            except Exception as e:
                print(f'  aviso itens {venda.get("numero")}: {str(e)[:60]}', file=sys.stderr)
                continue
            for it in itens:
                nm = norm(it.get('nome',''))
                qtd = it.get('quantidade',0) or 0
                rec = (it.get('valor',0) or 0) * qtd
                for prod in PRODUTOS:
                    if prod['match'](nm):
                        if prod.get('from_ym') and ym < prod['from_ym']:
                            break  # produto rastreado só a partir de from_ym (ex.: Komakai só 2026)
                        slug=prod['slug']
                        NOMES_MATCH[slug].add(it.get('nome',''))
                        qeff = qtd * prod.get('qty_mult', lambda n:1)(nm)
                        mes_acc[slug]['qtd'] += qeff
                        mes_acc[slug]['receita'] += rec
                        c = data[slug]['clientes'][cli]
                        c['qtd'] += qeff; c['receita'] += rec; c['n'] += 1
                        c['meses'].add(ym)
                        if sdate > c['ultima']: c['ultima'] = sdate
                        if not c['primeira'] or sdate < c['primeira']: c['primeira'] = sdate
                        data[slug]['total_qtd'] += qeff
                        data[slug]['total_receita'] += rec
                        break
            n_vendas+=1
        if len(vendas)<500: break
        pagina+=1
    for slug,acc in mes_acc.items():
        fr = PROD_FROM.get(slug)
        if fr and ym < fr: continue   # não grava meses anteriores ao from_ym (Komakai só 2026)
        data[slug]['months'][ym] = acc
    save()
    resumo = ' | '.join(f"{p['slug'][:6]}:{mes_acc[p['slug']]['qtd']}" for p in PRODUTOS)
    print(f'{ym}: {n_vendas} vendas | {resumo}', file=sys.stderr)

print('\nBACKFILL COMPLETO. Cache salvo em '+OUT, file=sys.stderr)
for slug,d in data.items():
    print(f"  {d['label']}: {d['total_qtd']} un · R$ {d['total_receita']:,.2f} · estoque {d['estoque']}", file=sys.stderr)
print('\n=== NOMES CASADOS POR PRODUTO (conferencia) ===', file=sys.stderr)
for slug in sorted(NOMES_MATCH):
    print(f"  [{slug}] {len(NOMES_MATCH[slug])} nomes:", file=sys.stderr)
    for nm in sorted(NOMES_MATCH[slug]):
        print(f"      - {nm}", file=sys.stderr)
