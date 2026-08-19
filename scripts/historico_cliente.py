#!/usr/bin/env python3
"""Historico de compras de um cliente (busca por trecho do nome).

Varre as vendas dos vendedores monitorados nos ultimos N meses, seleciona
os clientes cujo nome contem o termo e detalha compras, produtos, marcas,
categorias e cadencia.

Uso:
    python3 historico_cliente.py "soul" [meses=12]

Saida: relatorio legivel + bloco JSON entre ===JSON=== / ===FIM===
"""
import calendar
import json
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))
from ca_client import ContaAzulClient
from gerar_relatorio import categorizar
from atualizar_dados import inferir_marca, VENDOR_FULL_NAMES

MANAUS_TZ = timezone(timedelta(hours=-4))

SELLER_NAMES = {
    'Erivan Lima': 'erivan', 'Lucas de Mello Valente': 'lucas',
    'Róger Silva': 'roger', 'Roger de Lima silva': 'roger',
    'Jalena': 'jalena', 'Célio Alex': 'celio',
}

GRUPO = {
    'Produtos A': 'Cosmeticos', 'Produtos B': 'Cosmeticos',
    'Produtos C': 'Cosmeticos', 'Produtos D': 'Cosmeticos',
    'Acessorios A': 'Acessorios', 'Acessorios B': 'Acessorios',
    'Maquinario': 'Maquinario', 'Movelaria': 'Moveis', 'Outros': 'Outros',
}


def norm(s):
    s = unicodedata.normalize('NFKD', (s or '').upper())
    return ''.join(c for c in s if not unicodedata.combining(c))


def main():
    termo = sys.argv[1] if len(sys.argv) > 1 else 'soul'
    meses = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    alvo = norm(termo)

    client = ContaAzulClient()
    vendedores = client.get('/venda/vendedores')
    id_to_key = {v['id']: SELLER_NAMES[v['nome']]
                 for v in vendedores if v['nome'] in SELLER_NAMES}
    ids = list(id_to_key)
    print(f'Busca: "{termo}" | {meses} meses | {len(ids)} vendedor(es) monitorado(s)\n')

    hoje = datetime.now(MANAUS_TZ).replace(tzinfo=None)
    janela = []
    a, m = hoje.year, hoje.month
    for _ in range(meses):
        janela.append((a, m))
        m -= 1
        if m < 1:
            m, a = 12, a - 1
    janela.reverse()

    compras = []          # cada venda casada
    nomes = defaultdict(float)
    for ano_b, mes_b in janela:
        primeiro = f'{ano_b:04d}-{mes_b:02d}-01'
        ultimo = f'{ano_b:04d}-{mes_b:02d}-{calendar.monthrange(ano_b, mes_b)[1]:02d}'
        for vid in ids:
            pagina = 1
            while True:
                res = client.get('/venda/busca', ids_vendedores=[vid],
                                 data_inicio=primeiro, data_fim=ultimo,
                                 totais='APPROVED', pagina=pagina, tamanho_pagina=500)
                vendas = res.get('itens', []) if isinstance(res, dict) else []
                if not vendas:
                    break
                for v in vendas:
                    nome_c = ((v.get('cliente') or {}).get('nome') or '').strip()
                    if alvo not in norm(nome_c):
                        continue
                    try:
                        dt = datetime.strptime(v['data'], '%Y-%m-%d')
                    except (KeyError, ValueError):
                        continue
                    liq = v.get('total', 0) or 0
                    itens_det = []
                    try:
                        ir = client.get(f"/venda/{v['id']}/itens", tamanho_pagina=200)
                        for it in (ir.get('itens', []) if isinstance(ir, dict) else []):
                            q = it.get('quantidade', 0) or 0
                            itens_det.append({
                                'p': it.get('nome', ''), 'q': int(q),
                                'v': round((it.get('valor', 0) or 0) * q, 2),
                            })
                    except Exception as e:
                        print(f"    aviso: itens da venda {v.get('numero')} falharam: {e}")
                    compras.append({
                        'data': dt.strftime('%Y-%m-%d'),
                        'cliente': nome_c,
                        'vendedor': VENDOR_FULL_NAMES.get(id_to_key.get(vid, ''), '?'),
                        'liquido': round(liq, 2),
                        'itens': itens_det,
                    })
                    nomes[nome_c] += liq
                if len(vendas) < 500:
                    break
                pagina += 1

    if not compras:
        print(f'Nenhuma compra encontrada para "{termo}".')
        print('\n===JSON===')
        print(json.dumps({'termo': termo, 'compras': []}, ensure_ascii=False))
        print('===FIM===')
        return

    compras.sort(key=lambda x: x['data'])
    total_liq = sum(c['liquido'] for c in compras)
    print(f'{len(compras)} compra(s) | liquido R$ {total_liq:,.2f}')
    print('\nRazoes sociais encontradas:')
    for n, v in sorted(nomes.items(), key=lambda kv: -kv[1]):
        print(f'  {n[:50]:<50} R$ {v:>10,.2f}')

    por_mes = defaultdict(lambda: {'v': 0.0, 'n': 0})
    por_prod = defaultdict(lambda: {'v': 0.0, 'q': 0})
    por_marca = defaultdict(float)
    por_grupo = defaultdict(float)
    por_vend = defaultdict(float)
    for c in compras:
        ym = c['data'][:7]
        por_mes[ym]['v'] += c['liquido']
        por_mes[ym]['n'] += 1
        por_vend[c['vendedor']] += c['liquido']
        for it in c['itens']:
            por_prod[it['p']]['v'] += it['v']
            por_prod[it['p']]['q'] += it['q']
            por_marca[inferir_marca(it['p'])] += it['v']
            por_grupo[GRUPO.get(categorizar(it['p']), 'Outros')] += it['v']

    print('\nPor mes:')
    for ym in sorted(por_mes):
        d = por_mes[ym]
        print(f"  {ym}: R$ {d['v']:>9,.2f}  ({d['n']} compra(s))")

    datas = [datetime.strptime(c['data'], '%Y-%m-%d') for c in compras]
    intervalos = [(datas[i] - datas[i - 1]).days for i in range(1, len(datas))]
    interv_medio = sum(intervalos) / len(intervalos) if intervalos else 0
    dias_silencio = (hoje.date() - datas[-1].date()).days

    print(f'\nPrimeira compra: {datas[0].strftime("%d/%m/%Y")} | ultima: {datas[-1].strftime("%d/%m/%Y")}')
    print(f'Intervalo medio: {interv_medio:.0f} dias | sem comprar ha {dias_silencio} dias')
    print(f'Ticket medio: R$ {total_liq / len(compras):,.2f}')
    print('\nAtendido por:')
    for v, val in sorted(por_vend.items(), key=lambda kv: -kv[1]):
        print(f'  {v:<26} R$ {val:>10,.2f}  ({val/total_liq*100:.0f}%)')
    print('\nTop produtos:')
    for p, d in sorted(por_prod.items(), key=lambda kv: -kv[1]['v'])[:12]:
        print(f"  {p[:52]:<52} {d['q']:>4}un  R$ {d['v']:>9,.2f}")

    print('\n===JSON===')
    print(json.dumps({
        'termo': termo, 'gerado_em': hoje.strftime('%d/%m/%Y'),
        'meses': [f'{a:04d}-{m:02d}' for a, m in janela],
        'n_compras': len(compras), 'total_liquido': round(total_liq, 2),
        'razoes_sociais': {n: round(v, 2) for n, v in nomes.items()},
        'por_mes': {k: {'v': round(d['v'], 2), 'n': d['n']} for k, d in por_mes.items()},
        'por_marca': sorted([[k, round(v, 2)] for k, v in por_marca.items()], key=lambda x: -x[1]),
        'por_grupo': {k: round(v, 2) for k, v in por_grupo.items()},
        'por_vendedor': {k: round(v, 2) for k, v in por_vend.items()},
        'top_produtos': [[p, round(d['v'], 2), d['q']] for p, d in
                         sorted(por_prod.items(), key=lambda kv: -kv[1]['v'])[:25]],
        'compras': compras,
        'intervalo_medio': round(interv_medio, 1),
        'dias_silencio': dias_silencio,
        'ticket_medio': round(total_liq / len(compras), 2),
    }, ensure_ascii=False))
    print('===FIM===')


if __name__ == '__main__':
    main()
